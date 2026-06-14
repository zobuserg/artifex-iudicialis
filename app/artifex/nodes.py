"""
Las estaciones de la cinta — cada función es una estación de la fábrica.

Una estación recibe la caja (CasoState), hace su trabajo, llena su campo de
resultado y devuelve la caja avanzada a la siguiente etapa. Reusan las
funciones puras de app/core (lectura de surcos, guard anti-inyección) para
mantener el mismo espíritu del motor antiguo.

Estaciones construidas:
  [1] node_resumen_hechos       — resume los hechos del expediente
  [2] node_busqueda_fundamentos — RAG: cura la lista de fundamentos
  [3] node_redaccion            — redacta el borrador completo
  [4] node_verificacion         — valida citas y estructura (sin API)
  [5] node_pulido               — pulido de lenguaje (Haiku, opcional)
  [6] node_formato              — exporta el borrador a .docx judicial
"""

from __future__ import annotations

from pathlib import Path

from app.core.claude_worker import (
    _slot_document_has_unusable_extraction,
    build_enriched_prompt,
    read_slot_document_text,
    resolution_max_output_tokens,
)
from app.core.file_manager import BASE_DIR, list_bibliografia
from app.core.output_validator import validate_resolution_output
from app.core.word_export import markdown_to_docx, resolution_docx_filename, text_to_docx_faithful
from app.core.prompt_injection_guard import (
    system_injection_guard_es,
    wrap_untrusted_document,
)
from app.core.wiki_worker import extract_relevant_articles
from app.artifex.llm import call_model
from app.artifex.state import CasoState, Etapa

# Surcos que cuentan los hechos del caso (lo demás es prueba o accesorio).
_SLOTS_HECHOS: tuple[str, ...] = (
    "solicitud_inicial",
    "resolucion_apelada",
    "recurso_apelacion",
)

_RESUMEN_SYSTEM = (
    "Eres asistente del juez de la Sala Superior Penal de Apelaciones. Tu tarea en "
    "esta estación es analizar los documentos del expediente y producir DOS secciones "
    "bien diferenciadas. NO opines, NO resuelvas, NO cites normas ni jurisprudencia "
    "que no estén literalmente en los documentos. Sé fiel y objetivo. "
    + system_injection_guard_es()
)

_RESUMEN_INSTRUCCION = (
    "A partir ÚNICAMENTE de los documentos embebidos abajo, produce exactamente "
    "dos secciones con los encabezados indicados:\n\n"
    "## RESUMEN DE HECHOS\n"
    "Narra de forma objetiva y neutral:\n"
    "  1. Qué solicitó la parte (requerimiento/solicitud inicial).\n"
    "  2. Qué decidió el juez de primera instancia (resolución apelada).\n"
    "  3. Qué cuestiona la parte en su recurso de apelación.\n\n"
    "## PROBLEMA JURÍDICO DEL RECURSO\n"
    "Identifica con precisión los AGRAVIOS concretos que plantea el apelante: "
    "qué puntos específicos de la resolución impugna, bajo qué argumentos jurídicos, "
    "y qué pretende obtener con la apelación. Estos agravios son el núcleo del "
    "problema jurídico que la Sala debe resolver. Si hay varios agravios, "
    "enuméralos separadamente. Si el recurso no está disponible, indícalo.\n\n"
    "Sé fiel a los documentos. No agregues hechos ni argumentos que no estén ahí. "
    "Si un dato no aparece, dilo explícitamente en lugar de inventarlo."
)


def node_resumen_hechos(state: CasoState) -> CasoState:
    """Estación 1 — lee los surcos del expediente y produce el resumen de hechos.

    Llena ``state.hechos_resumen`` y avanza la etapa al checkpoint ① (donde el
    juez revisa antes de seguir).
    """
    partes: list[str] = [_RESUMEN_INSTRUCCION, ""]

    leidos = 0
    for key in _SLOTS_HECHOS:
        for path in state.slots.get(key, []):
            texto = read_slot_document_text(path)
            if not texto.strip():
                continue
            etiqueta = state.slot_labels.get(key, key)
            partes.append(
                wrap_untrusted_document(
                    f"{etiqueta} · {path.name}",
                    texto,
                    source_kind=f"fuente_expediente/{key}",
                )
            )
            leidos += 1

    if leidos == 0:
        state.avisos.append(
            "Estación resumen: no se pudo leer ningún documento de hechos "
            "(solicitud, resolución apelada o recurso)."
        )
        state.hechos_resumen = ""
        state.etapa = Etapa.CHECKPOINT_HECHOS
        return state

    prompt = "\n\n".join(partes)
    texto, modelo = call_model(prompt, system=_RESUMEN_SYSTEM, max_tokens=4096)

    # Separar las dos secciones del output estructurado.
    hechos_resumen, agravios = _split_resumen_agravios(texto)
    state.hechos_resumen = hechos_resumen
    if agravios and not state.agravios:   # no sobreescribir si el juez ya editó
        state.agravios = agravios
    # Parsear lista individual de agravios (siempre actualiza desde el texto actual)
    state.agravios_list = _parse_agravios_list(state.agravios or agravios)
    state.etapa = Etapa.CHECKPOINT_HECHOS
    state.avisos.append(f"Estación resumen: {leidos} documento(s) leído(s) · modelo {modelo}")
    return state


def _split_resumen_agravios(texto: str) -> tuple[str, str]:
    """Divide el output estructurado de E1 en (hechos_resumen, agravios).

    Busca el encabezado '## PROBLEMA JURÍDICO DEL RECURSO' para separar.
    Si no lo encuentra, devuelve el texto completo como hechos y agravios vacío.
    """
    import re
    patron = re.compile(
        r"##\s*PROBLEMA\s+JUR[IÍ]DICO\s+DEL\s+RECURSO",
        re.IGNORECASE,
    )
    m = patron.search(texto)
    if not m:
        return texto.strip(), ""
    hechos = texto[:m.start()].strip()
    # Quitar el encabezado "## RESUMEN DE HECHOS" si aparece al inicio
    hechos = re.sub(r"^##\s*RESUMEN\s+DE\s+HECHOS\s*\n?", "", hechos, flags=re.IGNORECASE).strip()
    agravios = texto[m.end():].strip()
    return hechos, agravios


def _parse_agravios_list(agravios_text: str) -> list[str]:
    """Extrae la lista individual de agravios desde el texto de la sección de agravios.

    Soporta: numeración (1. / 1) / a) / a.) / - / •), párrafos separados por línea en blanco.
    Devuelve lista de strings; si no detecta estructura, devuelve el texto completo como un ítem.
    """
    import re

    text = agravios_text.strip()
    if not text:
        return []

    # Patrón: ítems que empiezan con número o letra seguido de . o ) o solo número,
    # o con guión/bala, al inicio de línea.
    patron_item = re.compile(
        r"^(?:\d{1,2}[.)]\s+|[a-zA-Z][.)]\s+|\d{1,2}\s+[-–]\s+|[-•]\s+)",
        re.MULTILINE,
    )

    items: list[str] = []
    splits = list(patron_item.finditer(text))
    if len(splits) >= 2:
        for i, m in enumerate(splits):
            start = m.start()
            end = splits[i + 1].start() if i + 1 < len(splits) else len(text)
            item = text[start:end].strip()
            # Quitar el marcador inicial del ítem
            item_body = patron_item.sub("", item, count=1).strip()
            if item_body:
                items.append(item_body)
        return items

    # Fallback: párrafos separados por línea en blanco
    parrafos = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if len(parrafos) >= 2:
        return parrafos

    return [text]


# ── Estación 2: búsqueda de fundamentos (el RAG) ──────────────────────────

_BUSQUEDA_SYSTEM = (
    "Eres asistente del juez de la Sala Superior Penal de Apelaciones. Tu tarea en esta "
    "estación es identificar los FUNDAMENTOS JURÍDICOS pertinentes al caso "
    "(normas y jurisprudencia), usando ÚNICAMENTE el material del almacén "
    "embebido abajo. No inventes artículos, casaciones ni acuerdos plenarios: "
    "si algo parece necesario pero no está en el material, dilo como un vacío a "
    "cubrir, no lo fabriques. " + system_injection_guard_es()
)


def _leer_wiki_consolidada() -> str:
    """Jurisprudencia y conceptos consolidados del magistrado (wiki rebuild)."""
    partes: list[str] = []
    wiki = BASE_DIR / "02_wiki"
    for ruta, titulo in (
        (wiki / "jurisprudencia" / "jurisprudencia.md", "JURISPRUDENCIA CONSOLIDADA DEL MAGISTRADO"),
        (wiki / "conceptos" / "conceptos.md", "CONCEPTOS JURÍDICOS CONSOLIDADOS DEL MAGISTRADO"),
    ):
        if ruta.is_file():
            txt = ruta.read_text(encoding="utf-8", errors="replace").strip()
            if txt:
                partes.append(f"### {titulo}\n\n{txt}")
    return "\n\n".join(partes)


def node_busqueda_fundamentos(state: CasoState) -> CasoState:
    """Estación 2 — el RAG. Cura la lista de fundamentos pertinentes al caso.

    Reusa el pre-filtro Haiku (artículos de códigos globales) + la bibliografía
    de la materia + la wiki consolidada. Llena ``state.fuentes`` con una lista
    revisable y avanza al checkpoint ② (aprueba / quita / añade).
    """
    # 1. Bibliografía de la materia (rutas) — la usará la redacción más adelante.
    state.bibliografia = list_bibliografia(state.materia)

    # 2. Pre-filtro Haiku: artículos de códigos globales (CP/CPP/Constitución).
    articulos_txt, aviso = extract_relevant_articles(
        delito=state.delito,
        materia=state.materia,
        descripcion=state.hechos_resumen or "",
    )
    if aviso:
        state.avisos.append(f"Estación búsqueda (códigos globales): {aviso}")

    # 3. Wiki consolidada del magistrado.
    wiki_txt = _leer_wiki_consolidada()

    # 3b. Fichas individuales de jurisprudencia más afines (prefiltro léxico + re-rank Haiku).
    #     Complementa el consolidado con las fichas sueltas más pertinentes al caso actual.
    juris_fichas = _retrieve_jurisprudencia(state, k=6)

    # 4. Material disponible en el almacén.
    material: list[str] = []
    if articulos_txt.strip():
        material.append("## ARTÍCULOS DE CÓDIGOS APLICABLES (pre-filtrados)\n\n" + articulos_txt)
    if wiki_txt.strip():
        material.append("## ALMACÉN JURISPRUDENCIAL / CONCEPTUAL\n\n" + wiki_txt)
    if juris_fichas.strip():
        material.append(juris_fichas)
    if state.bibliografia:
        nombres = "\n".join(f"- {p.name}" for p in state.bibliografia)
        material.append("## BIBLIOGRAFÍA DE LA MATERIA (disponible para la redacción)\n\n" + nombres)

    if not material:
        state.avisos.append(
            "Estación búsqueda: el almacén no devolvió material (sin artículos, "
            "sin wiki consolidada, sin bibliografía de materia)."
        )
        state.fuentes = ""
        state.etapa = Etapa.CHECKPOINT_FUENTES
        return state

    agravios_txt = state.agravios.strip() if state.agravios.strip() else "(no especificados)"
    instruccion = (
        "PROBLEMA JURÍDICO DEL RECURSO (agravios del apelante):\n"
        f"{agravios_txt}\n\n"
        "RESUMEN DE HECHOS:\n"
        f"{state.hechos_resumen or '(sin resumen)'}\n\n"
        f"DELITO IMPUTADO: {state.delito or '(no especificado)'}\n\n"
        "Con base en el PROBLEMA JURÍDICO y SOLO en el material del almacén de abajo, "
        "elabora una lista curada de FUNDAMENTOS JURÍDICOS pertinentes para "
        "resolver ESPECÍFICAMENTE los agravios planteados. Para cada fundamento indica:\n"
        "  • La norma o precedente (artículo, casación, acuerdo plenario).\n"
        "  • Una línea de por qué aplica a ESTE agravio concreto.\n\n"
        "Agrupa en: (A) Normas aplicables, (B) Jurisprudencia/precedentes, "
        "(C) Conceptos pertinentes. Al final, si detectas un fundamento que el "
        "caso claramente exige pero que NO está en el material, anótalo bajo "
        "'(D) Vacíos a cubrir' — sin inventarlo.\n\n"
        "=== MATERIAL DEL ALMACÉN ===\n\n" + "\n\n".join(material)
    )

    fuentes, modelo = call_model(instruccion, system=_BUSQUEDA_SYSTEM, max_tokens=4096)

    # 5. Quiosco de boletines en vivo (opcional — Tavily).
    fuentes_live = ""
    if state.use_live_web:
        fuentes_live = _buscar_en_vivo(state)
        if fuentes_live:
            fuentes = fuentes + "\n\n" + fuentes_live

    # 6. Casos previos del magistrado (corpus): las 5 fichas más afines como
    #    ítems seleccionables. El juez decide en el checkpoint ② cuáles conservar.
    previos = _retrieve_casos_previos(state, k=5)
    if previos:
        fuentes = fuentes + "\n\n" + previos

    state.fuentes = fuentes
    state.etapa = Etapa.CHECKPOINT_FUENTES
    n_previos = previos.count("[CASO PREVIO")
    n_juris   = juris_fichas.count("- **") if juris_fichas else 0
    state.avisos.append(
        f"Estación búsqueda: {len(state.bibliografia)} doc(s) de materia · modelo {modelo}"
        + (" · boletines en vivo incluidos" if fuentes_live else "")
        + (f" · {n_juris} ficha(s) de jurisprudencia" if n_juris else "")
        + (f" · {n_previos} caso(s) previo(s) propuesto(s)" if n_previos else "")
    )
    return state


def _query_text(state: CasoState) -> str:
    """Texto de consulta para el RAG.

    Usa los agravios como foco principal si están disponibles — son el problema
    jurídico concreto que la Sala debe resolver y determinan qué jurisprudencia
    es realmente relevante. Si no hay agravios, cae a los hechos generales.
    """
    base = state.agravios.strip() if state.agravios.strip() else (state.hechos_resumen or "")
    return f"{state.delito or ''} {state.materia_label or ''} {base}"


def _retrieve_casos_previos(state: CasoState, k: int = 5) -> str:
    """Las fichas de casos previos del magistrado más afines, como viñetas seleccionables.

    Ranking en dos pasos (prefiltro léxico + re-rank semántico con Haiku). Se incluyen
    como referencia de estilo/criterio del juez, NO como precedente vinculante.
    """
    from app.artifex.retrieval import retrieve, one_line_summary
    from app.core.file_manager import dir_casos_previos_wiki

    try:
        carpeta = dir_casos_previos_wiki(state.materia)
    except Exception:
        return ""
    resultados = retrieve(
        carpeta, _query_text(state), k=k, prefilter=12, focus=state.delito,
    )
    if not resultados:
        return ""
    partes = [
        "## (E) CASOS PREVIOS DEL MAGISTRADO — referencia de estilo y criterio "
        "(seleccione cuáles aplicar; NO se citan como precedente vinculante)",
    ]
    for f, txt in resultados:
        partes.append(f"• [CASO PREVIO] {f.stem.replace('_', ' ')} — {one_line_summary(txt)}")
    return "\n".join(partes)


def _retrieve_jurisprudencia(state: CasoState, k: int = 6) -> str:
    """Fichas de jurisprudencia del magistrado más afines al caso (texto para E2).

    Alimenta el material desde el que el modelo cura los fundamentos (B). Antes solo
    se usaba el consolidado de ~6.5 KB; esto suma las fichas individuales pertinentes.
    """
    from app.artifex.retrieval import retrieve, one_line_summary
    from app.core.file_manager import BASE_DIR

    carpeta = BASE_DIR / "02_wiki" / "jurisprudencia"
    resultados = retrieve(
        carpeta, _query_text(state), k=k, prefilter=14,
        exclude_names=("jurisprudencia.md",),  # el consolidado ya se incluye aparte
        focus=state.delito,
    )
    if not resultados:
        return ""
    partes = ["### FICHAS DE JURISPRUDENCIA PERTINENTES (almacén del magistrado)"]
    for f, txt in resultados:
        partes.append(f"- **{f.stem.replace('_', ' ')}**: {one_line_summary(txt, 700)}")
    return "\n".join(partes)


def destilar_terminos_busqueda(contexto: str) -> str:
    """Extrae con Haiku las PALABRAS CLAVE / conceptos jurídicos del caso para una
    búsqueda web útil. Devuelve una sola línea de términos (sin nombres propios,
    fechas ni datos del expediente). Si falla, devuelve un recorte del contexto.

    Costo: una llamada a Haiku (~1 s, fracción de centavo). Necesario porque copiar
    el texto del caso da búsquedas pobres; las keywords destiladas dan resultados
    relacionados con la proposición jurídica.
    """
    contexto = (contexto or "").strip()
    if not contexto:
        return ""
    system = (
        "Eres un asistente jurídico peruano. Del contexto de un caso penal, extrae "
        "las PALABRAS CLAVE y CONCEPTOS JURÍDICOS centrales para buscar jurisprudencia "
        "y doctrina relacionada. Devuelve SOLO una línea con 4 a 8 términos o conceptos "
        "jurídicos separados por espacios (p. ej. 'atentado libertad de trabajo dolo "
        "libertad sindical reposición'). NO incluyas nombres de personas, fechas, "
        "números de expediente ni montos. Sin explicaciones, solo los términos."
    )
    try:
        out, _ = call_model(
            contexto[:2000], system=system, max_tokens=120,
            models=("claude-haiku-4-5-20251001",),
        )
        out = " ".join(out.split())
        return out[:200]
    except Exception:
        return ""


def buscar_web_juridica(
    tema: str,
    *,
    max_por_tipo: int = 4,
    profundidad: str = "advanced",
    restringir_dominios: bool = False,
) -> str:
    """Búsqueda web jurídica verificable vía Tavily, lista para el checkpoint ②.

    Hace dos búsquedas:
      • Jurisprudencia: casaciones, acuerdos plenarios, sentencias del TC y Corte Suprema.
      • Doctrina: artículos y libros jurídicos, con sus párrafos pertinentes.
    Por defecto busca en TODA la web (más resultados); los dominios de confianza se
    aplican solo si ``restringir_dominios=True``. Cada resultado es un ítem
    SELECCIONABLE (viñeta `•`) con extracto y URL verificable, para que el juez revise
    y escoja cuáles entran. Devuelve '' si no hay resultados.
    """
    import os
    try:
        from tavily import TavilyClient  # type: ignore[import]
    except ImportError:
        return "[EN VIVO] Error: tavily-python no instalado."

    api_key = os.environ.get("TAVILY_API_KEY", "")
    if not api_key:
        return "[EN VIVO] Error: TAVILY_API_KEY no configurada en .env"

    tema = (tema or "").strip() or "derecho penal"
    dominios = [
        "lpderecho.pe",
        "gacetajuridica.com.pe",
        "spij.minjus.gob.pe",
        "dialogoconlajurisprudencia.com",
        "pj.gob.pe",
        "tc.gob.pe",
    ]
    busquedas = [
        ("Jurisprudencia",
         f"jurisprudencia {tema} Perú casación acuerdo plenario sentencia "
         "Corte Suprema Tribunal Constitucional"),
        ("Doctrina/Libros",
         f"doctrina artículo jurídico libro {tema} Perú análisis comentario "
         "penal presupuestos requisitos interpretación"),
    ]

    try:
        client = TavilyClient(api_key=api_key)
        partes: list[str] = [
            "## (D) BÚSQUEDA WEB — jurisprudencia y doctrina (verificable; "
            "marque las que desee usar; NO se citan sin su revisión)"
        ]
        vistos: set[str] = set()
        for etiqueta, query in busquedas:
            try:
                kwargs = dict(
                    query=query, search_depth=profundidad, max_results=max_por_tipo,
                )
                if restringir_dominios:
                    kwargs["include_domains"] = dominios
                results = client.search(**kwargs)
            except Exception as exc:
                partes.append(f"• [EN VIVO · {etiqueta}] Error en la búsqueda: {exc}")
                continue
            for r in results.get("results", []):
                url = (r.get("url") or "").strip()
                if not url or url in vistos:
                    continue
                vistos.add(url)
                title = (r.get("title") or "Sin título").strip()
                # Extracto más largo: el párrafo pertinente del artículo/sentencia.
                content = " ".join((r.get("content") or "").split())[:1100]
                partes.append(
                    f"• [EN VIVO · {etiqueta}] {title} — {content} Fuente: {url}"
                )
        if len(partes) == 1:
            return ""   # sin resultados: no añadir una sección vacía
        return "\n\n".join(partes)
    except Exception as exc:
        return f"[EN VIVO] Error en búsqueda web: {exc}"


def _buscar_en_vivo(state: CasoState) -> str:
    """Búsqueda en vivo durante E2 (si state.use_live_web=True). Deriva el tema del caso."""
    tema = f"{state.delito or ''} {state.materia_label or ''} {(state.agravios or '')[:300]}".strip()
    return buscar_web_juridica(tema, max_por_tipo=3, profundidad="basic")


# ── Estación 3: redacción de la resolución ────────────────────────────────

SEP = "═" * 55


def _espina_aprobada(state: CasoState) -> str:
    """Bloque rector con lo que el juez ya revisó en los checkpoints ① y ②."""

    # Bloque de agravios: parsear fresco desde state.agravios (captura ediciones del juez).
    agravios_list_fresh = _parse_agravios_list(state.agravios) if state.agravios.strip() else state.agravios_list
    agravios_list = agravios_list_fresh if len(agravios_list_fresh) >= 2 else []
    if agravios_list:
        agravios_bloque = (
            "## AGRAVIOS A RESOLVER — REGLA DE PROFUNDIDAD POR AGRAVIO\n\n"
            f"El recurso plantea {len(agravios_list)} agravio(s) independientes. "
            "La resolución DEBE contener un BLOQUE DE CONSIDERANDOS DEDICADO Y COMPLETO "
            "para CADA agravio numerado abajo. Cada bloque debe cubrir como mínimo:\n"
            "  1. El agravio planteado (parafraseado en lenguaje judicial).\n"
            "  2. La norma o estándar jurisprudencial aplicable.\n"
            "  3. La valoración del caso concreto frente a ese estándar.\n"
            "  4. La conclusión para ese agravio (fundado / infundado / parcialmente fundado).\n"
            "NO fundir ni resumir agravios distintos en un mismo bloque. "
            "Un agravio desatendido es causal de nulidad.\n\n"
        )
        for i, agr in enumerate(agravios_list, 1):
            agravios_bloque += f"AGRAVIO {i} (desarrollar en su propio bloque de considerandos):\n{agr}\n\n"
    else:
        agravios_bloque = (
            "## AGRAVIOS DEL APELANTE\n\n"
            f"{(state.agravios or '(no especificados)').strip()}\n\n"
        )

    return (
        f"{SEP}\n"
        "ESPINA APROBADA POR EL JUEZ (revisada en checkpoints ① hechos y ② fuentes)\n"
        f"{SEP}\n"
        "El magistrado ya revisó y aprobó el resumen de hechos y la lista de "
        "fundamentos de abajo. Son la GUÍA DE CONTENIDO — definen qué temas cubre "
        "la resolución y cuál es la postura. NO son una guía de longitud: la "
        "resolución debe ser TAN EXTENSA Y DETALLADA como la plantilla (Bloque 3). "
        "El expediente crudo (Bloque 4) es la fuente principal para construir los "
        "considerandos con toda la profundidad que el caso exige — cita folios, "
        "transcribe declaraciones clave, analiza cada elemento de convicción en "
        "párrafo propio. No contradigas la espina aprobada en su dirección, pero "
        "SÍ expándela hasta alcanzar la riqueza jurídica de la plantilla.\n\n"
        "📌 FORMATO Y ENCABEZADO — REPRODUCE LA PLANTILLA AL PIE DE LA LETRA\n"
        "Esto es una RESOLUCIÓN JUDICIAL, no un borrador: su FORMA debe ser IDÉNTICA a "
        "la de la plantilla (Bloque 3). El documento final se genera reproduciendo TU "
        "texto tal cual — el sistema NO reformatea, NO filtra y NO agrega encabezados. "
        "Todo lo que debe aparecer en el .docx debe estar en el texto que generes. Por tanto:\n"
        "• INICIA el documento con el encabezado institucional EXACTO de la plantilla: "
        "las líneas PODER JUDICIAL / CORTE SUPERIOR DE JUSTICIA DE ICA / el nombre de la "
        "Sala TAL COMO APARECE EN LA PLANTILLA (no lo cambies ni lo abrevies), seguidas "
        "del bloque de metadatos (EXPEDIENTE / IMPUTADO / DELITO / AGRAVIADO / MATERIA / "
        "PROCEDENCIA) con los MISMOS rótulos, dos puntos y tabulaciones de la plantilla, "
        "pero con los DATOS REALES de este caso.\n"
        "• Reproduce los títulos de sección con la MISMA forma que la plantilla "
        "(numeración romana, mayúsculas, y el punto final solo si la plantilla lo uso).\n"
        "• Conserva los subtítulos en LÍNEA PROPIA (ej. «De la defensa técnica del "
        "imputado») sin fusionarlos con el párrafo numerado siguiente.\n"
        "• Mantén el mismo esquema de numeración de párrafos y las líneas en blanco "
        "entre bloques que usa la plantilla.\n"
        "• NO uses Markdown (nada de #, **, viñetas con guión). Devuelve TEXTO PLANO con "
        "el formato visual de la plantilla.\n"
        "• NOMBRE OFICIAL DE LA SALA: cuando menciones el órgano en el encabezado o en "
        "el cuerpo, escríbelo SIEMPRE como «Sala Superior Penal de Apelaciones de Chincha "
        "y Pisco» (NO «Sala Superior Penal de Apelaciones»). La Corte es «Corte Superior de "
        "Justicia de Ica».\n\n"
        "## HECHOS APROBADOS\n\n"
        f"{(state.hechos_resumen or '(sin resumen)').strip()}\n\n"
        + agravios_bloque
        + "## FUNDAMENTOS APROBADOS\n\n"
        f"{(state.fuentes or '(sin fundamentos)').strip()}\n"
    )


def _slots_legibles(state: CasoState) -> dict[str, list[Path]]:
    """Devuelve solo los surcos donde al menos un archivo extrajo texto útil.

    En la fábrica, los documentos ya fueron procesados en estaciones 1 y 2.
    La espina aprobada captura lo extraíble. Pasarle al motor antiguo surcos
    con texto ilegible activaría _raise_unusable_critical_sources; este filtro
    los excluye. Usa el mismo criterio que el guard interno de build_enriched_prompt
    (_slot_document_has_unusable_extraction) para garantizar consistencia.
    """
    resultado: dict[str, list[Path]] = {}
    for key, paths in state.slots.items():
        legibles = [
            p for p in paths
            if not _slot_document_has_unusable_extraction(read_slot_document_text(p))
        ]
        if legibles:
            resultado[key] = legibles
    return resultado


def _prompt_kwargs_from_state(state: CasoState) -> dict:
    """Traduce la caja CasoState a los kwargs de build_enriched_prompt."""
    return {
        "plantilla_path": state.plantilla_path,
        "slots": _slots_legibles(state),
        "slot_labels": state.slot_labels,
        "bibliografia": state.bibliografia,
        "instruccion_general": state.instruccion_general,
        "instruccion_particular": state.instruccion_particular,
        "postura": state.postura.value,
        "postura_personalizada": state.postura_personalizada,
        "agravios": state.agravios,
        "expediente": state.expediente,
        "imputados": state.imputados,
        "delito": state.delito,
        "agraviado": state.agraviado,
        "juzgado": state.juzgado,
        "materia_label": state.materia_label,
        "modo": state.modo,
        "borrador_path": state.borrador_path,
        "folder_name": state.folder_name,
        "caso_num": state.caso_num,
        "tipo": state.tipo or "resolución de vista",
        "resoluciones_estilo": state.resoluciones_estilo,
    }


def build_redaccion_prompt(state: CasoState) -> str:
    """Arma el prompt de redacción: espina aprobada + el prompt enriquecido completo.

    Reusa build_enriched_prompt (motor probado: reglas institucionales, surcos,
    plantilla, bibliografía, postura, reglas transversales anti-AI) y le antepone
    los hechos y fundamentos ya aprobados por el juez. Puede lanzar si un surco
    crítico es ilegible (mismo guard que el motor antiguo).
    """
    base = build_enriched_prompt(
        **_prompt_kwargs_from_state(state),
        warnings_out=state.avisos,
    )
    return _espina_aprobada(state) + "\n\n" + base


def node_redaccion(state: CasoState) -> CasoState:
    """Estación 3 — redacta el borrador completo de la resolución.

    Llena ``state.borrador`` y avanza a la verificación (estación 4).
    """
    prompt = build_redaccion_prompt(state)
    borrador, modelo = call_model(
        prompt,
        system=system_injection_guard_es(),
        max_tokens=resolution_max_output_tokens(),
    )
    state.borrador = borrador
    state.etapa = Etapa.VERIFICACION
    state.avisos.append(f"Estación redacción: borrador generado · modelo {modelo}")
    return state


# ── Estación 4: verificación de citas y estructura ────────────────────────

def node_verificacion(state: CasoState) -> CasoState:
    """Estación 4 — valida el borrador sin llamar a la API.

    Usa ``output_validator.validate_resolution_output`` para detectar:
      • Metatexto de IA filtrado en el acto (error)
      • Postura incongruente con el dispositivo (error)
      • Citas sin respaldo en el corpus curado (advertencia)
      • Estructura procesal mínima ausente (advertencia)

    El corpus de contraste es la wiki consolidada + los fundamentos curados
    de la estación 2, que ya contienen las casaciones y acuerdos plenarios
    que el modelo debería haber citado.

    No bloquea el pipeline: los errores se acumulan en ``state.avisos``
    y se presentan al juez en el checkpoint ③ junto al borrador.
    """
    borrador = (state.borrador or "").strip()
    if not borrador:
        state.avisos.append("Estacion verificacion: borrador vacio, saltando.")
        state.etapa = Etapa.CHECKPOINT_BORRADOR
        return state

    # Corpus de contraste: wiki + fuentes curadas de E2
    corpus_parts: list[str] = []
    wiki_txt = _leer_wiki_consolidada()
    if wiki_txt:
        corpus_parts.append(wiki_txt)
    if state.fuentes:
        corpus_parts.append(state.fuentes)
    corpus = "\n\n".join(corpus_parts)

    report = validate_resolution_output(
        borrador,
        postura=state.postura.value,
        tipo=state.tipo or "auto de vista",
        source_corpus=corpus,
        expect_full_act=True,
        materia=state.materia,
        delito=state.delito,
    )

    state.citas_ok = not report.has_errors
    for linea in report.summary_lines():
        state.avisos.append(f"[E4] {linea}")

    state.etapa = Etapa.CHECKPOINT_BORRADOR
    return state


# ── Estación 5: pulido de lenguaje (opcional, Haiku) ─────────────────────

_PULIDO_SYSTEM = (
    "Eres revisor de estilo jurídico de una Sala Superior Penal de Apelaciones peruana. "
    "Tu única tarea es pulir el LENGUAJE del auto de vista que recibirás, sin "
    "cambiar NADA del fondo jurídico: ni la postura, ni las citas, ni los hechos, "
    "ni la decisión. Solo corrige: redundancias, frases inapropiadas para un acto "
    "judicial, errores tipográficos evidentes y concordancia gramatical. "
    "Devuelve ÚNICAMENTE el texto corregido, sin explicaciones ni comentarios. "
    + system_injection_guard_es()
)


def node_pulido(state: CasoState) -> CasoState:
    """Estación 5 — pulido de lenguaje con Sonnet (fallback Opus).

    Estación OPCIONAL: si no hay borrador o si el juez decide saltarla,
    simplemente pasa el texto sin modificar.  Llama a Claude Sonnet en lugar
    de Opus para mantener el coste más bajo sin comprometer el estilo.
    """
    borrador = (state.borrador or "").strip()
    if not borrador:
        state.avisos.append("Estacion pulido: borrador vacio, saltando.")
        state.etapa = Etapa.CHECKPOINT_BORRADOR
        return state

    prompt = (
        "A continuación el borrador a pulir. "
        "Devuelve SOLO el texto corregido:\n\n"
        f"{borrador}"
    )
    # Sonnet: equilibrio coste/calidad, sin comprometer el fondo del acto
    pulido, modelo = call_model(
        prompt,
        system=_PULIDO_SYSTEM,
        max_tokens=16000,
        models=("claude-sonnet-4-5", "claude-opus-4-5"),
    )

    state.borrador = pulido or borrador
    state.etapa = Etapa.CHECKPOINT_BORRADOR
    state.avisos.append(f"Estacion pulido: revision completada · modelo {modelo}")
    return state


# ── Estación 6: formato / exportación .docx ───────────────────────────────

_SALA_NOMBRE = "SALA SUPERIOR PENAL DE APELACIONES DE CHINCHA Y PISCO"
_CORTE_NOMBRE = "CORTE SUPERIOR DE JUSTICIA DE ICA"


def node_formato(state: CasoState) -> CasoState:
    """Estación 6 — convierte el borrador Markdown al .docx judicial oficial.

    Toma ``state.borrador`` (texto de la estación 3 o el pulido de la 5),
    construye la cabecera institucional con los metadatos del caso y llama
    a ``word_export.markdown_to_docx``.  Guarda la ruta del documento
    resultante en ``state.documento_final`` y avanza a ``Etapa.FINAL``.

    El .docx se guarda en:
        <BASE_DIR>/outputs/<folder_name>/<filename>

    donde ``filename`` sigue el patrón ``EXP_<expediente>_<materia>.docx``
    (o ``<folder_name>.docx`` si no hay expediente).
    """
    borrador = (state.borrador or "").strip()
    if not borrador:
        state.avisos.append("Estacion formato: borrador vacio — no se genero .docx.")
        state.etapa = Etapa.FINAL
        return state

    filename = resolution_docx_filename(state.materia, state.folder_name, state.expediente)
    out_dir = BASE_DIR / "outputs" / state.folder_name
    dest = out_dir / filename

    # Renderizado FIEL: el modelo ya reprodujo el encabezado y el formato de la
    # plantilla; el exportador NO reinyecta cabecera ni reformatea (eso causaba
    # encabezados duplicados y "SALA PENAL" en vez de "SALA SUPERIOR PENAL").
    try:
        text_to_docx_faithful(borrador, dest)
        state.documento_final = str(dest)
        state.etapa = Etapa.FINAL
        state.avisos.append(f"Estacion formato: .docx generado -> {dest.name}")
    except Exception as exc:
        state.avisos.append(f"Estacion formato: ERROR al generar .docx — {exc}")
        state.etapa = Etapa.FINAL

    return state
