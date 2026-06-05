"""
WikiWorker — Ingestión de corpus y reconstrucción del wiki Obsidian.
Usa claude-haiku-4-5; el tamaño del fragmento enviado y la salida se ajustan con env ADIUTOR_CORPUS_FICHA_*.

Workers:
  CorpusIngestorWorker      — corpus magistrado (clasifica decisorio vs doctrina mal ubicada)
  BibliografiaIngestorWorker — 01_raw/bibliografia → 02_wiki/bibliografia (ficha doctrina)
  ResolutionFichaWorker     — ficha de una resolución recién generada (siempre decisorio)
  WikiRebuildWorker         — reconstruye INDEX.md, conceptos y jurisprudencia

PDF en corpus/bibliografía: si la lectura local (pdfplumber/OCR) falla, el ingest puede enviar el PDF
a Haiku como documento nativo en la API (ver ADIUTOR_WIKI_INGEST_PDF_NATIVE).
"""

from __future__ import annotations

import base64
import os
import re
import threading
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from app.core.claude_worker import (
    AUDIO_SUFFIXES,
    is_failed_document_extraction,
    read_file_text,
)
from app.core.prompt_injection_guard import (
    rules_for_untrusted_sources,
    wrap_untrusted_document,
)
from app.core.file_manager import (
    BASE_DIR,
    BIBLIOGRAFIA_SUFFIXES,
    MATERIA_SLUGS,
    bibliography_source_rel_key,
    dir_bibliografia_global_wiki,
    dir_bibliografia_wiki,
    dir_casos_previos_wiki,
    list_bibliografia,
    list_bibliografia_global,
    list_case_folders,
    materia_label,
    pending_bibliografia_for_fichas,
    pending_bibliografia_global_for_fichas,
    pending_corpus_pdfs,
    read_bibliografia_global_wiki_index,
    read_bibliografia_wiki_index,
    read_corpus_index,
    write_bibliografia_global_wiki_index,
    write_bibliografia_wiki_index,
    write_corpus_index,
    list_corpus_wiki_fichas,
)

from app.core.human_editor_hints import WIKI_CONSULT_SYSTEM_PROMPT


HAIKU = "claude-haiku-4-5-20251001"
# Si el ID principal no está disponible en la cuenta, se prueba el siguiente.
HAIKU_MODEL_FALLBACKS = ("claude-3-5-haiku-20241022",)

# ── Prompts ────────────────────────────────────────────────────────────────

# Fragmentos reutilizables (el ingest del corpus combina clasificación + ambos formatos).
_FICHA_JUDICIAL_CORPUS_FORM = """Eres un asistente jurídico. Genera una ficha **judicial decisoria**.
Usa [[WikiLinks]] para jurisprudencia y conceptos cuando consten.

**Ratio decidendi (solo aquí):** incluye sólo el razonamiento que **vincula de modo necesario** \
con lo **resuelto** (confirmación/revocación/modificación y ante qué agravios o capitales puede inferirse). \
No confundas con obiter dicta, doctrina ornamental o repetición del relato. La sección "## Ratio decidendi" \
debe ser la **más desarrollada** de la ficha salvo que el acto sea puramente técnico y breve. \
Hechos: sólo los imprescindibles para entender qué problema acarrea cada presupuesto.

Orden práctico: identifica resultado(s) sustanciales; remonta al tramo del acto donde se traban norma/evidencia/estándar \
de control con ese resultado; vértelo en bullets sin vaciar contenido jurídico.

Orientación: unas **{target_words} palabras** como guía; prioriza desarrollo sobre la ratio y presupuestos.

Formato exacto (solo si clasificaste el documento como acto decisorio):
# [tipo de resolución] — [expediente si aparece, si no "s/n"]
## Datos
- Materia: {materia}
- Fallo: CONFIRMA / REVOCA / MODIFICA (uno solo, según cupe)
- Delito:
- Imputado:

## Hechos clave
- Viñetas según necesidad procesal.

## Presupuestos analizados
- Problema y cómo lo resolvió la sala por cada presupuesto; rubro/fundamento solo si aparece así en el acto.

## Ratio decidendi
- Encadenamiento norma/evidencia/criterios de control hasta el dispositivo, por cada núcleo resolutorio \
(sin repetir dato factual que no lleve al fallo).

## Jurisprudencia citada
- [[…]] — papel en esta decisión (una línea).

## Conceptos aplicados
- [[…]]

## Notas de estilo
(1-4 líneas si se percibe.)
"""

_FICHA_DOCTRINA_FORM = """Eres un asistente jurídico. Genera una ficha **de doctrina** (no decisoria).
Usa [[WikiLinks]] para conceptos. **No inventes ratio decidendi, fallo, delito expediente si no existen** \
en este texto — es obra o comentario académico, no sentencia.

**Objetivo:** inventario argumental recuperable: tesis del autor, cómo apoya cada una, nociones útiles para un penalista \
y articulación con normas/precedentes que el mismo texto discuta.

Orientación: unas **{target_words} palabras**.

Contexto materia/flujo origen (metadatos, no contenido jurídico inventado): {materia_context}
Archivo fuente (referencia): {fuente}

Formato exacto:
# Doctrina — [autor si surge; obra o capítulo si surge; si no desde el contenido disponible]
## Datos
- Tema principal:
- Alcance territorial o dogmático (si el texto lo delimita):

## Tesis nucleares
- 3–7 proposiciones en voz neutral (conclusiones fuertes del autor).

## Argumentario del autor
- Premisas y pasos hasta cada tesis (encadenamiento del **autor**, no del juez).

## Conceptos definidos o propuestos
- [[…]] — (definición o matiz útil según el texto)

## Interacción normativa
- Artículos, bloques CPP/CP o normas tratadas como soporte/crítica.

## Precedentes o jurisprudencia tratados
- Qué rol juegan (confirman, reinterpretan, cuestionan), según el texto.

## Límites y problemas abiertos
- Condiciones o reservas del propio autor; líneas pendientes si las indica.
"""

_CORPUS_CLASSIFY_PREFACE = """Lee el documento siguiente y clasifícalo en **una única categoría**:

**JUDICIAL** — Es un **acto jurisdiccional decisorio**: sentencia, auto que decide recurso/medida/coerción \
u otro resultado con efectos resolutivos en el proceso sobre personas/hechos concretos. Entonces reproduce **solo** \
el formato bajo «=== FORMATO-JUDICIAL ===».

**DOCTRINA** — Es texto **doctrinal, académico o doctrinario/informativo** sin dispositivo que resuelva un recurso/medida \
en un caso claro (comentarios legales, capítulos de libro, artículos, manuales). Entonces reproduce **solo** \
el formato bajo «=== FORMATO-DOCTRINA ===». No fuerces fallo tipo CONFIRMA/REVOCA ni ratio de juez.

Salida: **solo** una ficha en el formato elegido (sin párrafos meta explicando la elección).


=== FORMATO-JUDICIAL ===
{judicial_block}


=== FORMATO-DOCTRINA ===
{doctrine_block}
"""


def _build_corpus_ficha_prompt(
    *,
    materia_label: str,
    texto_fragmento: str,
    target_words: int,
    source_is_native_pdf: bool = False,
) -> str:
    jb = _FICHA_JUDICIAL_CORPUS_FORM.format(materia=materia_label, target_words=target_words)
    db = _FICHA_DOCTRINA_FORM.format(
        materia_context=f"Ámbito repositorio: materia etiquetada «{materia_label}» (corpus magistrado / mezclas).",
        fuente="(nombre de archivo aparecerá sólo fuera del modelo; no lo inventes)",
        target_words=target_words,
    )
    head = _CORPUS_CLASSIFY_PREFACE.format(judicial_block=jb, doctrine_block=db)
    if source_is_native_pdf:
        return (
            head
            + "\n\n---\n**FUENTE:** el PDF del corpus va **adjunto** en este mensaje de la API "
            "(extracción local de texto en esta máquina falló o fue inutilizable). "
            "Clasifique según las reglas anteriores (JUDICIAL vs DOCTRINA) y redacte **solo** "
            "la ficha en el formato elegido a partir del contenido **legible** del PDF.\n"
        )
    return head + "\n\n---\nDOCUMENTO (fragmento proporcionado):\n" + wrap_untrusted_document(
        "corpus_fragmento",
        texto_fragmento,
        source_kind="corpus_ingest",
    )


def _build_doctrina_ficha_prompt(
    *,
    materia_context: str,
    fuente: str,
    texto_fragmento: str,
    target_words: int,
    source_is_native_pdf: bool = False,
) -> str:
    head = _FICHA_DOCTRINA_FORM.format(
        materia_context=materia_context,
        fuente=fuente,
        target_words=target_words,
    )
    if source_is_native_pdf:
        return (
            head
            + "\n\n---\n**FUENTE:** el PDF va **adjunto** en este mensaje de la API "
            "(extracción local falló o fue inutilizable). Redacte la ficha doctrinal **solo** "
            "con base en el contenido legible del PDF.\n"
        )
    return head + "\n\n---\nTEXTO:\n" + wrap_untrusted_document(
        fuente or "doctrina_fragmento",
        texto_fragmento,
        source_kind="doctrina_ingest",
    )


_FICHA_RESOLUCION = """Eres un asistente jurídico. El texto es una **resolución judicial recién generada** \
(acto decisorio): produce su ficha wiki para Obsidian.

Usa [[WikiLinks]] para jurisprudencia y conceptos.

**Ratio decidendi:** prioriza el encadenamiento que **vincula de modo necesario** con el **fallo** \
(CONFIRMA/REVOCA/MODIFICA). No diluyas en relato que no alimente el dispositivo. Lo obiter o meramente ilustrativo \
puede ir comprimido. La sección "## Ratio decidendi" debe ser la más sustantiva de la ficha salvo un acto muy breve.

Orientación: unas **{target_words} palabras** como guía.

Formato exacto:
# {tipo} — {expediente}
## Datos
- Materia: {materia}
- Imputado: {imputado}
- Delito: {delito}
- Fallo: CONFIRMA / REVOCA / MODIFICA (uno solo)

## Argumentos centrales
- Bullets con desarrollo (no solo menciones).

## Ratio decidendi
- Cómo la sala conecta evidencia, normas y estándares de control con el fallo, paso a paso.

## Jurisprudencia citada
- [[…]]

## Conceptos aplicados
- [[…]]

---
RESOLUCIÓN:
{texto}
"""

_REBUILD_WIKI = """Eres un asistente jurídico de la Sala Penal de Apelaciones. \
Tienes fichas wiki: resoluciones/casos y, en su caso, **fichas de doctrina** (bibliografía convertida a notas).

Genera exactamente tres secciones separadas por la línea "---SECCION---":

SECCIÓN 1 — INDEX.md completo:
Lista **casos/actos** agrupados por materia (cuando la ficha sea judicial): nombre de ficha, fallo, delito, una línea.
Si hay **fichas doctrina** (título empieza por "Doctrina" o provienen de `02_wiki/bibliografia/`), agrúpalas aparte bajo \
«Doctrina y bibliografía» con enlace [[…]] y una línea de tesis o tema.
Usa [[WikiLinks]].

SECCIÓN 2 — Notas de conceptos jurídicos:
Por cada concepto que aparezca en las fichas, escribe:
## [[NombreConcepto]]
Definición breve (1 línea).
- En **fichas judiciales**, indica en qué tramo o presupuesto se concentra la **ratio decidendi** que sostiene el resultado, \
si se deduce de la ficha.
- En **fichas doctrina**, indica qué **tesis del autor** o argumento apoya ese concepto y enlaza a la ficha fuente.
Casos/actos donde se aplicó: [[caso1]], [[caso2]]… (y fichas doctrina: [[…]] si aplica).

SECCIÓN 3 — Notas de jurisprudencia:
Por cada casación/acuerdo plenario citado, escribe:
## [[Nombre exacto del precedente]]
Tema central (1 línea). Usado en: [[caso1]], [[caso2]]…

FICHAS:
{fichas}
"""

# Scope para BibliografiaIngestorWorker: materia slug o constante global.
BIBLIO_INGEST_SCOPE_GLOBAL = "__global__"


# Ingest corpus + fichas post-resolución: riqueza configurable (antes fijo 12 k chars · 1024 tokens).
_FICHA_INPUT_CHARS_ENV = "ADIUTOR_CORPUS_FICHA_INPUT_CHARS"
_FICHA_OUTPUT_TOKENS_ENV = "ADIUTOR_CORPUS_FICHA_OUTPUT_TOKENS"
_FICHA_TARGET_WORDS_ENV = "ADIUTOR_CORPUS_FICHA_TARGET_WORDS"


# Sufijo en comentario HTML de la ficha cuando el ingest usó PDF nativo en la API (Haiku).
_INGEST_FICHA_COMMENT_PDF_NATIVE_SUFFIX = (
    " · ingest: PDF como documento en API (Haiku; extracción local falló)"
)


def wiki_ficha_input_char_limit() -> int:
    """Cuántos caracteres del texto se envían a Haiku (por defecto ~más amplio que 12 000)."""
    try:
        v = int(os.environ.get(_FICHA_INPUT_CHARS_ENV, "48000"))
    except ValueError:
        v = 48000
    return max(4_000, min(220_000, v))


def wiki_ficha_max_output_tokens() -> int:
    """Tope de salida; muy bajo ⇒ ficha incompleta aunque el prompt sea rico."""
    try:
        v = int(os.environ.get(_FICHA_OUTPUT_TOKENS_ENV, "4096"))
    except ValueError:
        v = 4096
    return max(1024, min(16_384, v))


def wiki_ficha_target_words() -> int:
    """Guía verbal en el prompt; no cuenta tokens del modelo pero orienta densidad."""
    try:
        v = int(os.environ.get(_FICHA_TARGET_WORDS_ENV, "900"))
    except ValueError:
        v = 900
    return max(350, min(4000, v))


# ── Helpers ────────────────────────────────────────────────────────────────

def _get_client():
    try:
        import anthropic
    except ImportError:
        raise RuntimeError("Instala el paquete anthropic: pip install anthropic")
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY no configurada.")
    try:
        import httpx

        return anthropic.Anthropic(
            api_key=api_key,
            timeout=httpx.Timeout(180.0, connect=30.0),
        )
    except Exception:
        return anthropic.Anthropic(api_key=api_key)


def _messages_create_haiku(client, *, max_tokens: int, messages: list, system: str | None = None):
    """Llama a la API probando Haiku principal y modelos de respaldo."""
    errors: list[str] = []
    for model in (HAIKU,) + HAIKU_MODEL_FALLBACKS:
        try:
            kwargs: dict = {
                "model": model,
                "max_tokens": max_tokens,
                "messages": messages,
            }
            if system:
                kwargs["system"] = system
            return client.messages.create(**kwargs)
        except Exception as e:
            errors.append(f"{model}: {e}")
            continue
    raise RuntimeError(
        "No se pudo usar ningún modelo Haiku. Detalle:\n" + "\n".join(errors)
    )


def _bibliografia_paths_inventory(max_chars: int = 6000) -> str:
    """
    Lista rutas relativas de 01_raw/bibliografia/<materia>/ para el chat «Consultar wiki».

    No incluye el texto de PDF/Word (sería enorme y duplica el flujo de Cursor/Claude en redacción);
    solo permite al modelo saber qué hay en disco y remitir a esas rutas.
    """
    lines: list[str] = [
        "### INVENTARIO_BIBLIOGRAFIA_REPOSITORIO",
        "Rutas bajo `01_raw/bibliografia/<materia>/` y global. Complemento de listado: "
        "el contenido extraído suele aparecer arriba en `TEXTO_DOCUMENTOS_REPOSITORY`.",
    ]
    used = len("\n".join(lines))
    any_files = False
    for m in sorted(MATERIA_SLUGS):
        files = list_bibliografia(m)
        if not files:
            continue
        any_files = True
        chunk = [f"\n**Materia `{m}`:**"]
        for f in files:
            try:
                rel = f.relative_to(BASE_DIR)
                row = f"  - `{rel.as_posix()}`"
            except ValueError:
                row = f"  - `{f}`"
            chunk.append(row)
        block = "\n".join(chunk)
        if used + len(block) + 2 > max_chars:
            lines.append("\n[... resto de bibliografía omitido por límite de tamaño ...]")
            break
        lines.append(block)
        used += len(block) + 1
    if not any_files:
        return ""
    return "\n".join(lines)


# En «Consultar wiki» NO se transcribe audio con Whisper (podría bloquear minutos por cada .mp3).
# Solo .txt colindante — la generación de resoluciones sigue usando read_file_text con Whisper opcional.


def _read_document_for_wiki_chat(path: Path) -> str:
    """Texto para Consultar wiki: sin Whisper automático sobre audio (evita cuelgues)."""
    ext = path.suffix.lower()
    if ext in AUDIO_SUFFIXES:
        side = path.with_suffix(".txt")
        if side.is_file():
            try:
                return side.read_text(encoding="utf-8", errors="replace").strip()
            except OSError as e:
                return f"[Error leyendo transcripción `{side.name}`: {e}]"
        return (
            f"[Audio `{path.name}` — en «Consultar wiki» solo se usa un `.txt` junto al archivo. "
            f"Transcriba con el botón del expediente o Whisper; no se ejecuta aquí para no bloquear la app.]"
        )
    return read_file_text(path)


def _iter_paths_bibliografia_cases_wiki_md() -> list[Path]:
    """Rutas ordenadas: bibliografía por materia + global; notas wiki bajo 02_wiki/bibliografia/; fuentes de expedientes."""
    seen: set[str] = set()
    out: list[Path] = []

    def _add(p: Path) -> None:
        try:
            k = str(p.resolve())
        except OSError:
            return
        if k not in seen:
            seen.add(k)
            out.append(p)

    for m in sorted(MATERIA_SLUGS):
        for p in list_bibliografia(m):
            _add(p)
    for p in list_bibliografia_global():
        _add(p)

    wiki_bib = BASE_DIR / "02_wiki" / "bibliografia"
    if wiki_bib.is_dir():
        for md in wiki_bib.rglob("*.md"):
            if not md.name.startswith("."):
                _add(md)

    try:
        ok_exts = set(BIBLIOGRAFIA_SUFFIXES) | set(AUDIO_SUFFIXES)
        for caso in list_case_folders(None):
            fd = caso / "fuentes"
            if not fd.is_dir():
                continue
            for f in fd.rglob("*"):
                if not f.is_file() or f.name.startswith("."):
                    continue
                if f.suffix.lower() in ok_exts:
                    _add(f)
    except OSError:
        pass

    def _prio(p: Path) -> tuple:
        s = str(p.resolve()).lower().replace("\\", "/")
        if "/02_wiki/bibliografia/" in s:
            loc = 0
        elif "/bibliografia/" in s and "/01_raw/" in s:
            loc = 1
        elif "/fuentes/" in s:
            loc = 2
        else:
            loc = 3
        suf = p.suffix.lower()
        if suf in (".md", ".txt"):
            kind = 0
        elif suf in AUDIO_SUFFIXES:
            kind = 4
        else:
            kind = 2
        return (loc, kind, s)

    out.sort(key=_prio)
    return out


def _iter_paths_wiki_chat_fast() -> list[Path]:
    """Solo bibliografía + 02_wiki/bibliografia — sin escanear todos los expedientes (`fuentes/`).

    El modo completo (muy lento) se activa con env `ADIUTOR_WIKI_SCAN_FUENTES=1`.
    """
    seen: set[str] = set()
    out: list[Path] = []

    def _add(p: Path) -> None:
        try:
            k = str(p.resolve())
        except OSError:
            return
        if k not in seen:
            seen.add(k)
            out.append(p)

    for m in sorted(MATERIA_SLUGS):
        for p in list_bibliografia(m):
            _add(p)
    for p in list_bibliografia_global():
        _add(p)

    wiki_bib = BASE_DIR / "02_wiki" / "bibliografia"
    if wiki_bib.is_dir():
        for md in wiki_bib.rglob("*.md"):
            if not md.name.startswith("."):
                _add(md)

    def _prio_fast(p: Path) -> tuple:
        s = str(p.resolve()).lower().replace("\\", "/")
        if "/02_wiki/bibliografia/" in s:
            loc = 0
        elif "/bibliografia/" in s and "/01_raw/" in s:
            loc = 1
        else:
            loc = 2
        suf = p.suffix.lower()
        kind = 0 if suf in (".md", ".txt") else (4 if suf in AUDIO_SUFFIXES else 2)
        return (loc, kind, s)

    out.sort(key=_prio_fast)
    return out


def _document_paths_for_wiki_query() -> list[Path]:
    """Rutas cuyo texto se incluye en «Consultar wiki»."""
    v = os.environ.get("ADIUTOR_WIKI_SCAN_FUENTES", "").strip().lower()
    if v in ("1", "true", "yes", "on"):
        return _iter_paths_bibliografia_cases_wiki_md()
    return _iter_paths_wiki_chat_fast()


def _truncate_block(text: str, cap: int) -> str:
    t = text.strip()
    if len(t) <= cap:
        return t
    return t[:cap] + f"\n\n[... texto truncado a {cap} caracteres ...]"


def _build_document_extractions_section(
    max_chars: int,
    *,
    max_files: int = 42,
    per_file_cap: int = 4000,
) -> str:
    """Extractos PDF/Word/md/txt/audio (vía .txt junto al audio) para Consultar wiki.

    Los límites de archivos están acotados: recorrer decenas de PDF con OCR podría
    bloquear la interfaz durante minutos.
    """
    paths = _document_paths_for_wiki_query()
    if not paths or max_chars < 900:
        return ""

    lines: list[str] = [
        "### TEXTO_DOCUMENTOS_REPOSITORY",
        "**Contexto documental (modo rápido):** `01_raw/bibliografia/<materia>/`, bibliografía global, "
        "`02_wiki/bibliografia/`. Para incluir también **todos los archivos en `fuentes/` de cada expediente** "
        "(lento), defina antes de lanzar la app: `ADIUTOR_WIKI_SCAN_FUENTES=1`. "
        "Para audio aquí solo se usa `.txt` colindante; sin Whisper.",
        "",
    ]

    remaining = max_chars - len("\n".join(lines)) - 200
    if remaining < 600:
        return ""

    n_appended = 0
    stopped_early = False
    for pi, path in enumerate(paths[:max_files]):
        if remaining < 440:
            stopped_early = True
            break
        try:
            rel = path.relative_to(BASE_DIR)
            rel_pos = rel.as_posix()
        except ValueError:
            rel_pos = path.name

        hdr = f"---\n#### archivo: `{rel_pos}`\n"
        overhead = len(hdr.encode("utf-8")) + 8
        text_room = remaining - overhead
        if text_room < 120:
            stopped_early = True
            break

        raw = ""
        try:
            raw = _read_document_for_wiki_chat(path)
        except Exception as e:
            raw = f"[Error leyendo `{path.name}`: {e}]"

        cap_txt = max(160, min(per_file_cap, text_room))
        truncated = _truncate_block(raw, cap_txt)
        block = f"{hdr}{truncated}\n"
        while len(block) > remaining and cap_txt > 120:
            cap_txt = int(cap_txt * 0.85)
            truncated = _truncate_block(raw, cap_txt)
            block = f"{hdr}{truncated}\n"
        if len(block) > remaining:
            truncated = _truncate_block(raw, max(80, remaining - overhead))
            block = f"{hdr}{truncated}\n"
        remaining -= len(block)
        lines.append(block)
        n_appended += 1

    if stopped_early and n_appended < len(paths):
        lines.append(
            "[... no se incluyeron más archivos por límite de contexto de la consulta. "
            "Puede acortar la lista de expedientes o priorizar una materia en una futura versión.]"
        )
    elif n_appended >= max_files and len(paths) > max_files:
        lines.append(
            f"[... límite de {max_files} archivo(s) en esta consulta; "
            f"hay {len(paths) - max_files} adicional(es) en el repositorio.]"
        )

    return "\n".join(lines)


_WIKI_MD_MAX_FILES_ENV = "ADIUTOR_WIKI_MD_MAX_FILES"
# Máximo de fichas .md extras por zona (juris otros / casos) antes de omitir.

# Límite de entradas examinadas por rglob (muchas notas vacías = n_added nunca llegaba al tope).
_WIKI_MD_MAX_TRAVERSAL_STEPS_DEFAULT = 4000


def _gather_wiki_markdown_only(max_chars: int) -> str:
    """Índice + fichas .md sin cargar todo el árbol en RAM (antes causaba bloqueos)."""

    try:
        cap_extra = max(60, min(400, int(os.environ.get(_WIKI_MD_MAX_FILES_ENV, "180"))))
    except ValueError:
        cap_extra = 180
    try:
        max_traversal = max(500, int(os.environ.get("ADIUTOR_WIKI_MD_MAX_TRAVERSAL", "0")))
    except ValueError:
        max_traversal = 0
    if max_traversal <= 0:
        max_traversal = max(_WIKI_MD_MAX_TRAVERSAL_STEPS_DEFAULT, cap_extra * 24)

    wiki_dir = BASE_DIR / "02_wiki"
    parts: list[str] = []

    budget = max_chars

    def consume(text: str) -> None:
        nonlocal budget
        if budget <= 0:
            return
        if len(text) <= budget:
            parts.append(text)
            budget -= len(text)
        else:
            parts.append(text[: budget])
            budget = 0

    sep = "\n\n"

    for ruta, titulo in (
        (wiki_dir / "INDEX.md", "INDICE_DE_CASOS"),
        (wiki_dir / "jurisprudencia" / "jurisprudencia.md", "JURISPRUDENCIA_CONSOLIDADA"),
        (wiki_dir / "conceptos" / "conceptos.md", "CONCEPTOS_CONSOLIDADOS"),
    ):
        if budget <= 0:
            break
        if not ruta.is_file():
            continue
        txt = ruta.read_text(encoding="utf-8", errors="replace").strip()
        if not txt:
            continue
        consume(f"### {titulo}\n{txt}{sep}")

    jur_root = wiki_dir / "jurisprudencia"
    n_added = 0
    # No usar sorted(rglob(...)): materializa todas las rutas en RAM antes de iterar — bloqueaba la UI.
    if jur_root.is_dir() and budget > 200:
        steps_j = 0
        for md in jur_root.rglob("*.md"):
            steps_j += 1
            if steps_j > max_traversal:
                consume(
                    "[... barrido detenido: demasiadas notas ignoradas/vacías bajo jurisprudencia/. "
                    f"Ajuste {_WIKI_MD_MAX_FILES_ENV} o "
                    "`ADIUTOR_WIKI_MD_MAX_TRAVERSAL` (>500).]\n\n"
                )
                break
            if budget <= 0:
                break
            if md.name == "jurisprudencia.md" and md.parent == jur_root:
                continue
            if md.name.startswith("."):
                continue
            if n_added >= cap_extra:
                consume(
                    "[... omitidas más notas bajo jurisprudencia/ por límite de archivos "
                    f"(var. entorno {_WIKI_MD_MAX_FILES_ENV}≈{cap_extra}); suba hasta 400 si necesita.]\n\n"
                )
                break
            try:
                txt = md.read_text(encoding="utf-8", errors="replace").strip()
            except OSError:
                continue
            if not txt:
                continue
            try:
                rel = md.relative_to(wiki_dir)
            except ValueError:
                rel = md
            n_added += 1
            consume(f"### JURISPRUDENCIA_NOTA {rel.as_posix()}\n{txt}{sep}")

    for sub, pref in (
        (wiki_dir / "casos", "CASO"),
        (wiki_dir / "casos_previos", "CASO_PREVIO"),
    ):
        n_added_sub = 0
        if not sub.is_dir() or budget <= 0:
            continue
        steps_s = 0
        for md in sub.rglob("*.md"):
            steps_s += 1
            if steps_s > max_traversal:
                consume(
                    f"[... barrido detenido en `{sub.name}/`: demasiadas entradas .md vacías "
                    "o rutas antes de cumplir el cupo. Ajuste `ADIUTOR_WIKI_MD_MAX_TRAVERSAL`.]\n\n"
                )
                break
            if budget <= 0:
                break
            if md.name.startswith("."):
                continue
            if n_added_sub >= cap_extra:
                consume(
                    f"[... omitidas más notas en {sub.name}/ (límite {cap_extra}); {_WIKI_MD_MAX_FILES_ENV}.]\n\n"
                )
                break
            try:
                txt = md.read_text(encoding="utf-8", errors="replace").strip()
            except OSError:
                continue
            if not txt:
                continue
            try:
                rel = md.relative_to(wiki_dir)
            except ValueError:
                rel = md
            n_added_sub += 1
            consume(f"### {pref} {rel.as_posix()}\n{txt}{sep}")

    return "\n".join(parts).strip()


def _gather_wiki_context_for_query(max_chars: int = 58000) -> str:
    """
    Contexto para «Consultar wiki».

    Por defecto **no** ejecuta `_build_document_extractions_section` (lectura OCR de todos
    los PDF de bibliografía) — eso puede bloquear la interfaz. Para activarlo:
    `ADIUTOR_WIKI_CHAT_INCLUDE_DOCS=1`.

    Las notas .md ya no precargan miles de archivos en memoria antes de truncar.
    """
    include_docs = os.environ.get("ADIUTOR_WIKI_CHAT_INCLUDE_DOCS", "").strip().lower() in (
        "1", "yes", "true", "on",
    )
    doc_sec = ""
    if include_docs:
        doc_cap = min(30000, max(12000, (max_chars * 48) // 100))
        doc_sec = _build_document_extractions_section(doc_cap).strip()

    overhead = len(doc_sec) + 700 if doc_sec else 450
    wiki_cap = max(4000, max_chars - overhead)
    wiki_sec = _gather_wiki_markdown_only(wiki_cap).strip()

    sep = "\n\n" + "─" * 48 + "\n\n"
    if doc_sec:
        wiki_part = (
            wiki_sec
            if wiki_sec
            else "_(No hay notas .md adicionales en el cupo — o `02_wiki/` vacío para lo no consolidado.)_"
        )
        merged = "### SECCION_A_DOCUMENTOS\n\n" + doc_sec + sep + "### SECCION_B_WIKI_MD\n\n" + wiki_part
    else:
        merged = wiki_sec if wiki_sec else "_(Vacío.)_"

    reserve = min(6000, max(1600, max_chars - len(merged) - 500))
    if reserve > 500:
        inv = _bibliografia_paths_inventory(max_chars=reserve)
        if inv.strip():
            merged = f"{merged}\n\n### INVENTARIO_RUTAS_RESTO\n{inv}"

    return merged


def _call_haiku(client, prompt: str, *, max_tokens: int | None = None) -> str:
    """Llamada simple (no streaming) a Haiku. Devuelve el texto generado."""
    mt = wiki_ficha_max_output_tokens() if max_tokens is None else max_tokens
    resp = _messages_create_haiku(
        client,
        max_tokens=mt,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.content[0].text.strip()


def _env_wiki_ingest_pdf_native_enabled() -> bool:
    """Si la extracción local de un PDF falla, intentar ficha vía PDF nativo en Messages (Haiku)."""
    return os.environ.get("ADIUTOR_WIKI_INGEST_PDF_NATIVE", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def _wiki_ingest_pdf_native_max_bytes() -> int:
    try:
        mb = float(os.environ.get("ADIUTOR_WIKI_PDF_NATIVE_MAX_MB", "20"))
        return int(max(1.0, min(32.0, mb)) * 1024 * 1024)
    except ValueError:
        return 20 * 1024 * 1024


def _call_haiku_with_pdf_document(
    client,
    prompt: str,
    pdf_path: Path,
    *,
    max_tokens: int | None = None,
) -> str:
    """
    Haiku con el PDF como bloque document en Messages (misma idea que subir el archivo en el chat de Claude).
    Usado cuando pdfplumber/OCR local no producen texto utilizable para el ingest wiki.
    """
    max_b = _wiki_ingest_pdf_native_max_bytes()
    try:
        raw = pdf_path.read_bytes()
    except OSError as e:
        raise RuntimeError(f"No se pudo leer el PDF: {e}") from e
    if len(raw) > max_b:
        mb_lim = max_b // (1024 * 1024)
        raise RuntimeError(
            f"PDF demasiado grande para la API de ingest (~{len(raw) // (1024 * 1024)} MB); "
            f"límite ~{mb_lim} MB (variable ADIUTOR_WIKI_PDF_NATIVE_MAX_MB)."
        )
    b64 = base64.standard_b64encode(raw).decode("ascii")
    mt = wiki_ficha_max_output_tokens() if max_tokens is None else max_tokens
    content: list[dict | str] = [
        {"type": "text", "text": prompt},
        {
            "type": "document",
            "source": {
                "type": "base64",
                "media_type": "application/pdf",
                "data": b64,
            },
        },
    ]
    resp = _messages_create_haiku(
        client,
        max_tokens=mt,
        messages=[{"role": "user", "content": content}],
    )
    out_parts: list[str] = []
    for block in resp.content:
        if getattr(block, "type", None) == "text" and getattr(block, "text", None):
            out_parts.append(block.text)
    text = "".join(out_parts).strip()
    if not text:
        raise RuntimeError("La API devolvió vacío al procesar el PDF.")
    return text


def _safe_stem(name: str) -> str:
    out = []
    for c in name:
        if c.isalnum() or c in "._-":
            out.append(c)
        else:
            out.append("_")
    return "".join(out).strip("_") or "ficha"


def _stem_from_bib_rel_key(rel_key: str) -> str:
    """Nombre de ficha único ante subcarpetas (clave relativa → stem seguro)."""
    return _safe_stem(rel_key.replace("/", "__"))


def _ingest_corpus_file_step(
    src_path: Path,
    mat_label: str,
    client,
) -> dict:
    """
    Un archivo: extracción + Haiku. Devuelve dict {ok, name, ...} thread-safe
    (la escritura a disco va en el hilo principal del worker con candado).
    """
    texto = read_file_text(src_path)
    if is_failed_document_extraction(texto):
        if (
            src_path.suffix.lower() == ".pdf"
            and _env_wiki_ingest_pdf_native_enabled()
        ):
            try:
                prompt = _build_corpus_ficha_prompt(
                    materia_label=mat_label,
                    texto_fragmento="",
                    target_words=wiki_ficha_target_words(),
                    source_is_native_pdf=True,
                )
                ficha_md = _call_haiku_with_pdf_document(client, prompt, src_path)
                stem = _safe_stem(src_path.stem)
                return {
                    "ok": True,
                    "name": src_path.name,
                    "stem": stem,
                    "ficha_md": ficha_md,
                    "via_pdf_native": True,
                }
            except Exception as e:
                return {
                    "ok": False,
                    "name": src_path.name,
                    "err": (
                        f"sin texto extra\u00edble localmente; fall\u00f3 tambi\u00e9n lectura por API con PDF nativo: {e}. "
                        f"Extracto local: {texto[:220].strip()}"
                    ),
                }
        return {
            "ok": False,
            "name": src_path.name,
            "err": f"sin texto extra\u00edble: {texto[:300].strip()}",
        }
    lim = wiki_ficha_input_char_limit()
    fragmento = texto[:lim]
    if len(texto) > lim:
        fragmento = (
            fragmento.rstrip()
            + "\n\n[AVISO DEL SISTEMA — fragmento truncado aquí "
            f"({lim:,} caracteres de {len(texto):,} totales); "
            f"aumentar env {_FICHA_INPUT_CHARS_ENV} para cubrir más cuerpo.]\n"
        )
    prompt = _build_corpus_ficha_prompt(
        materia_label=mat_label,
        texto_fragmento=fragmento,
        target_words=wiki_ficha_target_words(),
    )
    try:
        ficha_md = _call_haiku(client, prompt)
    except Exception as e:
        return {"ok": False, "name": src_path.name, "err": str(e)}
    stem = _safe_stem(src_path.stem)
    return {
        "ok": True,
        "name": src_path.name,
        "stem": stem,
        "ficha_md": ficha_md,
    }


# ── Worker 1: Ingestor de corpus ──────────────────────────────────────────

class CorpusIngestorWorker(QThread):
    """Procesa los PDFs pendientes del corpus y genera fichas wiki."""

    progress = pyqtSignal(int, int, str)   # (actual, total, nombre_archivo)
    finished = pyqtSignal(int)             # docs procesados
    error_occurred = pyqtSignal(str)

    def __init__(self, materia: str, parent=None):
        super().__init__(parent)
        self.materia = materia
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            client = _get_client()
            pending = pending_corpus_pdfs(self.materia)
            total = len(pending)
            if total == 0:
                self.finished.emit(0)
                return

            idx = read_corpus_index(self.materia)
            dest_dir = dir_casos_previos_wiki(self.materia)
            dest_dir.mkdir(parents=True, exist_ok=True)
            mat_label = materia_label(self.materia)
            procesados = 0
            lock = threading.Lock()

            try:
                n_workers = int(os.environ.get("ADIUTOR_CORPUS_WORKERS", "3"))
            except ValueError:
                n_workers = 3
            n_workers = max(1, min(8, n_workers, total))

            with ThreadPoolExecutor(max_workers=n_workers) as pool:
                future_map = {
                    pool.submit(
                        _ingest_corpus_file_step, src, mat_label, client
                    ): src
                    for src in pending
                }
                done = 0
                for fut in as_completed(future_map):
                    if self._cancelled:
                        break
                    src = future_map[fut]
                    try:
                        r = fut.result()
                    except Exception as e:
                        self.error_occurred.emit(f"{src.name}: {e}")
                        done += 1
                        self.progress.emit(done, total, src.name)
                        continue
                    done += 1
                    self.progress.emit(done, total, r.get("name", src.name))
                    if not r.get("ok"):
                        if r.get("err"):
                            self.error_occurred.emit(
                                f"{r['name']}: {r['err'][:450]}"
                            )
                        continue
                    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
                    ficha_path = dest_dir / f"{r['stem']}.md"
                    pdf_api_note = (
                        _INGEST_FICHA_COMMENT_PDF_NATIVE_SUFFIX if r.get("via_pdf_native") else ""
                    )
                    body = (
                        f"<!-- ficha generada {ts} · fuente: {r['name']}{pdf_api_note} -->\n\n"
                        f"{r['ficha_md']}"
                    )
                    with lock:
                        ficha_path.write_text(body, encoding="utf-8")
                        idx[r["name"]] = str(ficha_path.relative_to(BASE_DIR))
                        write_corpus_index(self.materia, idx)
                    procesados += 1

            if procesados == 0 and total > 0 and not self._cancelled:
                self.error_occurred.emit(
                    f"No se generó ninguna ficha de {total} archivo(s). "
                    "Revise los avisos: PDF con texto u OCR local, .doc/.docx legibles, "
                    "ANTHROPIC_API_KEY en .env, o PDF nativo con Haiku (ADIUTOR_WIKI_INGEST_PDF_NATIVE). "
                    f"(Procesamiento en paralelo: {n_workers} a la vez — ADIUTOR_CORPUS_WORKERS)"
                )

            self.finished.emit(procesados)

        except Exception as exc:
            self.error_occurred.emit(str(exc))


def _ingest_bibliografia_file_step(
    src_path: Path,
    *,
    scope: str,
    client,
) -> dict:
    """
    Una obra de doctrina desde 01_raw/bibliografia: ficha doctrina única.

    scope: materia válida (slug) o BIBLIO_INGEST_SCOPE_GLOBAL.
    """
    texto = read_file_text(src_path)
    if is_failed_document_extraction(texto):
        if (
            src_path.suffix.lower() == ".pdf"
            and _env_wiki_ingest_pdf_native_enabled()
        ):
            try:
                if scope == BIBLIO_INGEST_SCOPE_GLOBAL:
                    rel_key = bibliography_source_rel_key(src_path, materia=None)
                    mctx = "Bibliografía global (01_raw/bibliografia/global/) — uso transversal entre materias."
                else:
                    rel_key = bibliography_source_rel_key(src_path, materia=scope)
                    mctx = (
                        f"Bibliografía materia «{materia_label(scope)}» "
                        f"(01_raw/bibliografia/{scope}/)."
                    )
                prompt = _build_doctrina_ficha_prompt(
                    materia_context=mctx,
                    fuente=src_path.name,
                    texto_fragmento="",
                    target_words=wiki_ficha_target_words(),
                    source_is_native_pdf=True,
                )
                ficha_md = _call_haiku_with_pdf_document(client, prompt, src_path)
                stem = _stem_from_bib_rel_key(rel_key)
                return {
                    "ok": True,
                    "name": src_path.name,
                    "rel_key": rel_key,
                    "stem": stem,
                    "ficha_md": ficha_md,
                    "via_pdf_native": True,
                }
            except Exception as e:
                return {
                    "ok": False,
                    "name": src_path.name,
                    "err": (
                        f"sin texto extra\u00edble localmente; fall\u00f3 lectura por API con PDF nativo: {e}. "
                        f"Extracto local: {texto[:220].strip()}"
                    ),
                }
        return {
            "ok": False,
            "name": src_path.name,
            "err": f"sin texto extra\u00edble: {texto[:300].strip()}",
        }
    if scope == BIBLIO_INGEST_SCOPE_GLOBAL:
        rel_key = bibliography_source_rel_key(src_path, materia=None)
        mctx = "Bibliografía global (01_raw/bibliografia/global/) — uso transversal entre materias."
    else:
        rel_key = bibliography_source_rel_key(src_path, materia=scope)
        mctx = (
            f"Bibliografía materia «{materia_label(scope)}» "
            f"(01_raw/bibliografia/{scope}/)."
        )

    lim = wiki_ficha_input_char_limit()
    fragmento = texto[:lim]
    if len(texto) > lim:
        fragmento = (
            fragmento.rstrip()
            + "\n\n[AVISO DEL SISTEMA — fragmento truncado; "
            f"aumentar env {_FICHA_INPUT_CHARS_ENV}.]\n"
        )
    prompt = _build_doctrina_ficha_prompt(
        materia_context=mctx,
        fuente=src_path.name,
        texto_fragmento=fragmento,
        target_words=wiki_ficha_target_words(),
    )
    try:
        ficha_md = _call_haiku(client, prompt)
    except Exception as e:
        return {"ok": False, "name": src_path.name, "err": str(e)}
    stem = _stem_from_bib_rel_key(rel_key)
    return {
        "ok": True,
        "name": src_path.name,
        "rel_key": rel_key,
        "stem": stem,
        "ficha_md": ficha_md,
    }


# ── Worker 1b: Ingest bibliografía → fichas doctrina ──────────────────────

class BibliografiaIngestorWorker(QThread):
    """Procesa PDF/Word/Markdown pendientes de bibliografía y escribe 02_wiki/bibliografia/."""

    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(int)
    error_occurred = pyqtSignal(str)

    def __init__(self, scope: str, parent=None):
        """
        scope: slug de materia (p. ej. prision_preventiva) o BIBLIO_INGEST_SCOPE_GLOBAL.
        """
        super().__init__(parent)
        self.scope = scope
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            client = _get_client()
            if self.scope == BIBLIO_INGEST_SCOPE_GLOBAL:
                pending = pending_bibliografia_global_for_fichas()
                idx = read_bibliografia_global_wiki_index()
                dest_dir = dir_bibliografia_global_wiki()
                label = "global"
            else:
                pending = pending_bibliografia_for_fichas(self.scope)
                idx = read_bibliografia_wiki_index(self.scope)
                dest_dir = dir_bibliografia_wiki(self.scope)
                label = self.scope

            total = len(pending)
            if total == 0:
                self.finished.emit(0)
                return

            dest_dir.mkdir(parents=True, exist_ok=True)
            procesados = 0
            lock = threading.Lock()

            try:
                n_workers = int(os.environ.get("ADIUTOR_CORPUS_WORKERS", "3"))
            except ValueError:
                n_workers = 3
            n_workers = max(1, min(8, n_workers, total))

            with ThreadPoolExecutor(max_workers=n_workers) as pool:
                future_map = {
                    pool.submit(_ingest_bibliografia_file_step, src, scope=self.scope, client=client): src
                    for src in pending
                }
                done = 0
                for fut in as_completed(future_map):
                    if self._cancelled:
                        break
                    src = future_map[fut]
                    try:
                        r = fut.result()
                    except Exception as e:
                        self.error_occurred.emit(f"{src.name}: {e}")
                        done += 1
                        self.progress.emit(done, total, src.name)
                        continue
                    done += 1
                    self.progress.emit(done, total, r.get("name", src.name))
                    if not r.get("ok"):
                        if r.get("err"):
                            self.error_occurred.emit(f"{r['name']}: {r['err'][:450]}")
                        continue
                    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
                    rk = r.get("rel_key", src.name)
                    ficha_path = dest_dir / f"{r['stem']}.md"
                    pdf_api_note = (
                        _INGEST_FICHA_COMMENT_PDF_NATIVE_SUFFIX if r.get("via_pdf_native") else ""
                    )
                    body = (
                        f"<!-- ficha doctrina {ts} · bibliografía/{label} · fuente: {r['name']} · clave: {rk}{pdf_api_note} -->\n\n"
                        f"{r['ficha_md']}"
                    )
                    with lock:
                        ficha_path.write_text(body, encoding="utf-8")
                        idx[rk] = str(ficha_path.relative_to(BASE_DIR))
                        if self.scope == BIBLIO_INGEST_SCOPE_GLOBAL:
                            write_bibliografia_global_wiki_index(idx)
                        else:
                            write_bibliografia_wiki_index(self.scope, idx)
                    procesados += 1

            if procesados == 0 and total > 0 and not self._cancelled:
                self.error_occurred.emit(
                    f"No se generó ninguna ficha doctrina de {total} archivo(s). "
                    "Revise extracción de texto, ANTHROPIC_API_KEY, avisos arriba y PDF nativo Haiku (ADIUTOR_WIKI_INGEST_PDF_NATIVE). "
                    f"(Paralelismo: ADIUTOR_CORPUS_WORKERS={n_workers})"
                )

            self.finished.emit(procesados)

        except Exception as exc:
            self.error_occurred.emit(str(exc))


# ── Worker 2: Ficha de resolución recién generada ─────────────────────────

class ResolutionFichaWorker(QThread):
    """Genera la ficha wiki de una resolución recién creada."""

    finished = pyqtSignal(str)         # ruta de la ficha guardada
    error_occurred = pyqtSignal(str)

    def __init__(
        self,
        *,
        materia: str,
        folder_rel: str,
        resolution_text: str,
        tipo: str,
        expediente: str,
        imputado: str,
        delito: str,
        parent=None,
    ):
        super().__init__(parent)
        self.materia = materia
        self.folder_rel = folder_rel
        self.resolution_text = resolution_text
        self.tipo = tipo
        self.expediente = expediente
        self.imputado = imputado
        self.delito = delito

    def run(self):
        try:
            client = _get_client()
            lim = wiki_ficha_input_char_limit()
            rt = self.resolution_text or ""
            fragmento = rt[:lim]
            if len(rt) > lim:
                fragmento = (
                    fragmento.rstrip()
                    + "\n\n[AVISO DEL SISTEMA — fragmento truncado; "
                    f"aumentar env {_FICHA_INPUT_CHARS_ENV}.]\n"
                )
            prompt = _FICHA_RESOLUCION.format(
                tipo=self.tipo or "Resolución",
                expediente=self.expediente or "s/n",
                materia=materia_label(self.materia),
                imputado=self.imputado or "—",
                delito=self.delito or "—",
                target_words=wiki_ficha_target_words(),
                texto=fragmento,
            )
            ficha_md = _call_haiku(client, prompt)

            # Guardar en 02_wiki/casos/<materia>/
            dest_dir = BASE_DIR / "02_wiki" / "casos" / self.materia
            dest_dir.mkdir(parents=True, exist_ok=True)
            stem = _safe_stem(self.folder_rel.split("/")[-1])
            ficha_path = dest_dir / f"{stem}.md"
            ts = datetime.now().strftime("%Y-%m-%d %H:%M")
            ficha_path.write_text(
                f"<!-- ficha auto-generada {ts} · {self.folder_rel} -->\n\n{ficha_md}",
                encoding="utf-8",
            )
            self.finished.emit(str(ficha_path.relative_to(BASE_DIR)))

        except Exception as exc:
            self.error_occurred.emit(str(exc))


# ── Worker 3: Rebuild del wiki ────────────────────────────────────────────

class WikiRebuildWorker(QThread):
    """Lee fichas de todas las materias y reconstruye INDEX.md, conceptos y jurisprudencia."""

    status = pyqtSignal(str)
    finished = pyqtSignal()
    error_occurred = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

    def run(self):
        try:
            client = _get_client()

            # Recopilar fichas de TODAS las materias
            self.status.emit("Leyendo fichas del wiki…")
            fichas_paths: list[Path] = []

            # corpus previo: 02_wiki/casos_previos/*/
            casos_previos_root = BASE_DIR / "02_wiki" / "casos_previos"
            if casos_previos_root.is_dir():
                fichas_paths.extend(
                    f for f in casos_previos_root.rglob("*.md")
                    if not f.name.startswith(".")
                )

            # resoluciones generadas: 02_wiki/casos/*/
            casos_root = BASE_DIR / "02_wiki" / "casos"
            if casos_root.is_dir():
                fichas_paths.extend(
                    f for f in casos_root.rglob("*.md")
                    if not f.name.startswith(".")
                )

            # doctrina desde ingest bibliografía
            bib_wiki_root = BASE_DIR / "02_wiki" / "bibliografia"
            if bib_wiki_root.is_dir():
                fichas_paths.extend(
                    f for f in bib_wiki_root.rglob("*.md")
                    if not f.name.startswith(".")
                )

            if not fichas_paths:
                self.error_occurred.emit(
                    "No hay fichas wiki aún. Procesa corpus, genera fichas desde bibliografía "
                    "o crea resoluciones para poblar 02_wiki/."
                )
                return

            # Concatenar fichas (limitar para no exceder tokens)
            self.status.emit(f"Analizando {len(fichas_paths)} fichas…")
            partes: list[str] = []
            tokens_est = 0
            for fp in fichas_paths:
                txt = fp.read_text(encoding="utf-8", errors="replace")
                tokens_est += len(txt) // 4
                if tokens_est > 60000:
                    partes.append(
                        f"\n[... {len(fichas_paths) - len(partes)} fichas adicionales omitidas por límite de tokens ...]"
                    )
                    break
                # Incluir la materia (nombre de la carpeta padre) como contexto
                materia_carpeta = fp.parent.name
                partes.append(f"### {fp.stem} [{materia_carpeta}]\n{txt}\n")

            fichas_concat = "\n".join(partes)

            self.status.emit("Generando wiki con Claude…")
            prompt = _REBUILD_WIKI.format(fichas=fichas_concat)

            resp = _messages_create_haiku(
                client,
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}],
            )
            output = ""
            for block in resp.content:
                if block.type == "text":
                    output += block.text
            output = output.strip()

            # Separar secciones
            secciones = output.split("---SECCION---")
            ts = datetime.now().strftime("%Y-%m-%d %H:%M")

            wiki_dir = BASE_DIR / "02_wiki"
            wiki_dir.mkdir(parents=True, exist_ok=True)

            # Sección 1: INDEX.md
            self.status.emit("Escribiendo INDEX.md…")
            if len(secciones) >= 1:
                index_path = wiki_dir / "INDEX.md"
                index_path.write_text(
                    f"<!-- Rebuild automático · {ts} · {len(fichas_paths)} fichas -->\n\n"
                    + secciones[0].strip(),
                    encoding="utf-8",
                )

            # Sección 2: conceptos
            if len(secciones) >= 2:
                self.status.emit("Escribiendo notas de conceptos…")
                conc_dir = wiki_dir / "conceptos"
                conc_dir.mkdir(parents=True, exist_ok=True)
                (conc_dir / "conceptos.md").write_text(
                    f"<!-- Rebuild · {ts} -->\n\n" + secciones[1].strip(),
                    encoding="utf-8",
                )

            # Sección 3: jurisprudencia
            if len(secciones) >= 3:
                self.status.emit("Escribiendo notas de jurisprudencia…")
                jur_dir = wiki_dir / "jurisprudencia"
                jur_dir.mkdir(parents=True, exist_ok=True)
                (jur_dir / "jurisprudencia.md").write_text(
                    f"<!-- Rebuild · {ts} -->\n\n" + secciones[2].strip(),
                    encoding="utf-8",
                )

            self.finished.emit()

        except Exception as exc:
            self.error_occurred.emit(str(exc))


# ── Worker 4: Consulta al wiki ────────────────────────────────────────────

_CONSULTA_WIKI_BASE = """Eres el asistente jur\u00eddico personal del magistrado. \
Tienes acceso a su wiki (fichas .md) y, al inicio del contexto, a **fragmentos extraídos** \
de PDF, Word (.doc/.docx), texto (.txt), Markdown y notas bajo `02_wiki/bibliografia/`, \
así como archivos en `fuentes/` de los expedientes en `01_raw/`.

Las secciones **TEXTO_DOCUMENTOS_REPOSITORY** / **SECCION_A_DOCUMENTOS** contienen texto \
real de esos archivos (puede ir truncado). Puedes citar o resumir ese contenido cuando aparezca. \
El bloque **INVENTARIO_RUTAS_RESTO** al final solo lista rutas adicionales sin texto embebido.

Para **audio** (.mp3, .m4a, etc.) solo verás texto si existe un archivo `.txt` transcrito \
junto al audio (p. ej. tras usar Whisper o el botón del expediente). Si ves un aviso entre corchetes, \
indica que falta transcripción.

Responde bas\u00e1ndote \u00daNICAMENTE en el texto del bloque adjunto a este mensaje \
o en lo ya dicho en esta conversaci\u00f3n. \
Si la informaci\u00f3n no est\u00e1 en ese texto, dilo claro. \
Si sugieres una acci\u00f3n (revisar un caso, ampliar un criterio), el magistrado puede \
contestarte en el siguiente mensaje: mant\u00e9n el hilo dialogal.

Si tu respuesta incluye formulaciones propuestas para un acto judicial, debe sonar como magistratura humana bien informada: \
actúa como editor que quitó huellas propias del texto modelo-homogéneo orientándote en Wikipedia \
"Signs of AI writing" (WikiProject AI Cleanup), sin relajar el control sobre las fuentes ni inventar citas.

S\u00e9 conciso y directo.

---
WIKI DEL MAGISTRADO (contexto para toda esta conversacion):
---
{wiki_contenido}
---
FIN DEL CONTENIDO DEL WIKI.
---
MENSAJE DEL MAGISTRADO:
{user_text}"""

_CONSULTA_WIKI_FOLLOWUP = """Contin\u00faa la conversaci\u00f3n. Mismas reglas: solo lo apoyado \
en el wiki que recibiste en el primer mensaje de esta conversaci\u00f3n o en tus respuestas \
anteriores; no inventes jurisprudencia ni datos. Si el magistrado responde a una \
pregunta o sugerencia tuya, atiende eso de forma directa. \
Las propuestas de redacci\u00f3n deben estar humanizadas (lista orientadora Wikipedia \
«Signs of AI writing» / WikiProject AI Cleanup).

MENSAJE DEL MAGISTRADO:
{user_text}"""


def _consulta_pack_first_message(wiki_contenido: str, user_text: str) -> str:
    """
    Sin `str.format`: contenidos Markdown pueden tener '{{ ... }}' o llaves sueltas y rompen `.format`.
    """
    wrapped_wiki = wrap_untrusted_document(
        "wiki_contexto_consulta",
        wiki_contenido,
        source_kind="wiki_chat",
    )
    return (
        rules_for_untrusted_sources()
        + _CONSULTA_WIKI_BASE.replace("{wiki_contenido}", wrapped_wiki).replace(
            "{user_text}", user_text
        )
    )


def _consulta_pack_followup(user_text: str) -> str:
    """Ídem sin `.format` por seguridad sobre texto ingresado por usuario/wiki."""
    return _CONSULTA_WIKI_FOLLOWUP.replace("{user_text}", user_text)


class WikiQueryWorker(QThread):
    """Chat multi-turno al wiki (Haiku, sin streaming)."""

    chunk_ready = pyqtSignal(str)
    # Distinto del `finished()` nativo de QThread (evita sombras/conflictos entre señales).
    query_completed = pyqtSignal()
    error_occurred = pyqtSignal(str)
    progress = pyqtSignal(str)

    def __init__(self, history: list[tuple[str, str]], parent=None):
        super().__init__(parent)
        self.history = history

    def run(self):
        try:
            self.progress.emit("Preparando…")
            from app.core.env_load import load_repo_dotenv

            load_repo_dotenv()
            client = _get_client()

            self.progress.emit(
                "Construyendo contexto (notas 02_wiki/; PDF omitidos salvo "
                "ADIUTOR_WIKI_CHAT_INCLUDE_DOCS=1 — sin escaneo pesado de expedientes por defecto)…"
            )
            try:
                wiki_contenido = _gather_wiki_context_for_query(58000)
            except Exception as gather_exc:
                import traceback

                self.error_occurred.emit(
                    f"Error al leer el repositorio para el chat:\n{gather_exc}\n\n"
                    f"{traceback.format_exc()[:1200]}"
                )
                return
            if not wiki_contenido.strip():
                self.error_occurred.emit(
                    "El wiki no tiene texto utilizable. Cree notas en 02_wiki/casos/ "
                    "o pulse «Reconstruir wiki» tras tener fichas."
                )
                return

            messages: list[dict] = []
            first_user_packed = False
            for role, content in self.history:
                c = (content or "").strip()
                if not c:
                    continue
                if role == "user":
                    if not first_user_packed:
                        packed = _consulta_pack_first_message(wiki_contenido, c)
                        messages.append({"role": "user", "content": packed})
                        first_user_packed = True
                    else:
                        follow = _consulta_pack_followup(c)
                        messages.append({"role": "user", "content": follow})
                elif role == "assistant":
                    messages.append({"role": "assistant", "content": c})

            if not messages:
                self.error_occurred.emit("No hay mensajes para enviar.")
                return

            self.progress.emit("Enviando solicitud a Claude (Haiku)…")
            resp = _messages_create_haiku(
                client,
                max_tokens=4096,
                messages=messages,
                system=WIKI_CONSULT_SYSTEM_PROMPT,
            )
            text = ""
            for block in resp.content:
                if hasattr(block, "text") and block.text:
                    text += block.text
            text = text.strip()
            if not text:
                self.error_occurred.emit(
                    "La API devolvi\u00f3 una respuesta vac\u00eda. Revise el modelo y la clave API."
                )
                return

            self.chunk_ready.emit(text)
            self.query_completed.emit()

        except Exception as exc:
            import traceback

            self.error_occurred.emit(
                f"{type(exc).__name__}: {exc}\n\n{traceback.format_exc()[:2000]}"
            )


# ── Función: pre-filtro de artículos relevantes ───────────────────────────

_GLOBAL_CODE_MAX_CHARS_ENV = "ADIUTOR_GLOBAL_CODE_MAX_CHARS"


def _global_code_max_chars() -> int:
    try:
        v = int(os.environ.get(_GLOBAL_CODE_MAX_CHARS_ENV, "80000"))
    except ValueError:
        v = 80000
    return max(20000, min(600_000, v))


def _fold_ascii(s: str) -> str:
    nk = unicodedata.normalize("NFKD", (s or "").strip())
    return "".join(c for c in nk if not unicodedata.combining(c)).lower()


def _match_stem_for_codigo(codigo_nombre: str, stems: list[str]) -> str | None:
    """Empareja nombre de código (Haiku) ↔ stem de archivo (p. ej. CP_2024 vs Código Penal)."""
    if not codigo_nombre or not stems:
        return None
    cf = _fold_ascii(codigo_nombre)
    stem_folds = [(s, _fold_ascii(s)) for s in stems]

    def pick(pred) -> str | None:
        for s, sf in stem_folds:
            if pred(sf):
                return s
        return None

    if "procesal" in cf or cf.strip() == "cpp" or "cpp" in cf.split():
        hit = pick(
            lambda sf: "procesal" in sf
            or "_cpp" in sf
            or sf.endswith("cpp")
            or re.search(r"\bcpp\b", sf) is not None
        )
        if hit:
            return hit
    if "constitu" in cf or "magna" in cf or " carta " in f" {cf} ":
        hit = pick(
            lambda sf: "constitu" in sf
            or sf == "cn"
            or "magna" in sf
            or "cart" in sf
        )
        if hit:
            return hit
    if "penal" in cf:
        hit = pick(lambda sf: "penal" in sf and "procesal" not in sf)
        if hit:
            return hit
        hit = pick(
            lambda sf: sf == "cp"
            or sf.startswith("cp_")
            or "codpen" in sf
            or "c_penal" in sf
            or sf == "c.p.p"  # uncommon
        )
        if hit:
            return hit

    generic = frozenset({"codigo", "ley", "peruano", "peruana", "el", "la", "los", "las", "de", "del"})
    words = [w for w in re.split(r"[^\w]+", cf) if len(w) > 2 and w not in generic]
    for s, sf in stem_folds:
        if any(w in sf for w in words):
            return s
    return None


def _first_article_snippet(texto_codigo: str, num: str) -> str | None:
    """Localiza un artículo por varias plantillas (OCR/PDF varía)."""
    n = re.escape(str(num).strip())
    patterns = [
        rf"(?:Artículo|Articulo|ARTÍCULO|ARTICULO)\s*{n}\s*[°.]?[^\n]*\n(?:.|\n){{0,1600}}",
        rf"(?:Art\.|ART\.|art\.)\s*{n}\s*[°.]?[^\n]*\n(?:.|\n){{0,1600}}",
        rf"\bART\.?\s*{n}\b[°.]?[^\n]*\n(?:.|\n){{0,1200}}",
        rf"\bArt\.?\s*{n}\b[°.]?\s+[^\n]+\n(?:.|\n){{0,1200}}",
    ]
    cap = 5200
    for pat in patterns:
        m = re.search(pat, texto_codigo, re.IGNORECASE | re.DOTALL)
        if m:
            frag = m.group(0).strip()
            return frag if len(frag) <= cap else frag[:cap] + "\n[…truncado…]"
    return None


_PREFILTRO_PROMPT = """Eres un asistente jurídico peruano. Dado el siguiente caso, \
identifica qué artículos específicos de los códigos legales son relevantes.

Caso:
- Delito imputado: {delito}
- Materia: {materia}
- Descripción adicional: {descripcion}

Códigos disponibles (nombres EXACTOS tal como aparecen; elige el objeto \"codigo\" del JSON copiando uno de ellos o un sinónimo muy cercano como \"Código Penal\", \"Código Procesal Penal\", \"Constitución Política del Estado\"):
{codigos_disponibles}

Responde ÚNICAMENTE con una lista JSON de objetos, sin texto adicional:
[
  {{"codigo": "Código Procesal Penal", "articulos": ["268", "269", "270"]}},
  {{"codigo": "Código Penal", "articulos": ["111"]}}
]

Solo incluye artículos que sean directamente aplicables. Máximo 15 artículos en total.
"""


def extract_relevant_articles(
    *,
    delito: str,
    materia: str,
    descripcion: str = "",
) -> tuple[str, str | None]:
    """
    Llama a Haiku para identificar artículos y extrae texto desde `01_raw/bibliografia/global/`.

    Returns:
        (texto_para_prompt, aviso_usuario). Si no hay archivos globales, ``(\"\", None)``.
        Si hay archivos pero no se pudo incrustar nada, segundo valor explica el motivo.
    """
    import json

    global_files = list_bibliografia_global()
    if not global_files:
        return ("", None)

    max_c = _global_code_max_chars()
    codigos_texto: dict[str, str] = {}
    for f in global_files:
        texto = read_file_text(f)
        codigos_texto[f.stem] = (texto or "")[:max_c]

    if not any((t or "").strip() for t in codigos_texto.values()):
        return (
            "",
            "Bibliografía global: los archivos existen pero no se obtuvo texto útil (PDF/cifrado/OCR). Revise extracción.",
        )

    stems = list(codigos_texto.keys())
    codigos_disponibles = "\n".join(f"- {nombre}" for nombre in stems)

    client = _get_client()
    prompt = _PREFILTRO_PROMPT.format(
        delito=delito or "no especificado",
        materia=materia,
        descripcion=descripcion or "",
        codigos_disponibles=codigos_disponibles,
    )

    articulos_por_codigo: list[dict] = []
    try:
        resp = _messages_create_haiku(
            client,
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = ""
        for block in resp.content:
            if getattr(block, "type", "") == "text" or hasattr(block, "text"):
                tx = getattr(block, "text", "") or ""
                raw += tx
        raw = raw.strip()
        match = re.search(r"\[.*\]", raw, re.DOTALL)
        if not match:
            return (
                "",
                "Bibliografía global: Haiku no devolvió lista JSON de artículos — no se incrustaron extractos. Revise la API o reintente.",
            )
        articulos_por_codigo = json.loads(match.group())
        if not isinstance(articulos_por_codigo, list):
            articulos_por_codigo = []
    except Exception as e:
        return (
            "",
            f"Bibliografía global: fallo al obtener o interpretar artículos ({type(e).__name__}). "
            f"No se incrustó CP/Constitución automáticamente.",
        )

    partes: list[str] = []
    issues: list[str] = []
    stems_sorted = sorted(stems, key=len, reverse=True)

    for entrada in articulos_por_codigo:
        if not isinstance(entrada, dict):
            continue
        codigo_nombre = str(entrada.get("codigo", "") or "")
        nums = entrada.get("articulos", [])
        if not nums or not isinstance(nums, list):
            continue

        stem_pick = _match_stem_for_codigo(codigo_nombre, stems_sorted)
        if not stem_pick:
            issues.append(f"sin archivo para código «{codigo_nombre[:40]}»")
            continue
        texto_codigo = codigos_texto.get(stem_pick) or ""

        articulos_encontrados: list[str] = []
        for num in nums:
            snip = _first_article_snippet(texto_codigo, str(num))
            if snip:
                articulos_encontrados.append(snip)
            else:
                issues.append(
                    f"«{codigo_nombre[:24]}» art. {num} no hallado "
                    f"(OCR/formato o artículo fuera del trozo leído; suba {_GLOBAL_CODE_MAX_CHARS_ENV})."
                )

        if articulos_encontrados:
            partes.append(f"\n### {codigo_nombre} — Artículos relevantes\n")
            partes.extend(art + "\n" for art in articulos_encontrados)

    out = "\n".join(partes).strip()
    if out:
        return (out, None)

    detail = "; ".join(issues[:6]) if issues else "revise nombres de archivo (Codigo_Penal, CPP, Constitucion…) y formato «Artículo N»."
    return (
        "",
        f"Bibliografía global: hay {len(global_files)} archivo(s) pero no se incrustó ningún artículo. {detail}",
    )


# ── CorrectionLearningWorker ─────────────────────────────────────────────────

_CORRECTION_PROMPT = """Eres un asistente jurídico especializado en redacción judicial peruana.

Un magistrado acaba de corregir un fragmento de una resolución judicial.

INSTRUCCIÓN DE CORRECCIÓN DEL MAGISTRADO:
{instruccion}

MATERIA: {materia}

Tu tarea: extrae UNA SOLA regla de escritura o criterio judicial implícito en esa corrección.
La regla debe ser:
- Concreta y accionable (no genérica)
- Expresada en primera persona como preferencia del magistrado
- Útil para generar futuras resoluciones de la misma materia
- Máximo 2 líneas

Devuelve SOLO la regla, sin explicaciones ni prefijos.
Ejemplo de formato correcto:
"Prefiero que los considerandos de prisión preventiva citen expresamente el art. 268 CPP antes de analizar cada presupuesto."

Regla extraída:"""

_CONCEPTOS_MD_PATH = BASE_DIR / "02_wiki" / "conceptos" / "conceptos.md"
_CONCEPTOS_MD_LEARNING_HEADER = "\n\n## Criterios aprendidos del magistrado\n\n"
_MAX_RULE_LENGTH = 300  # caracteres máximos para una regla individual


class CorrectionLearningWorker(QThread):
    """
    Extrae silenciosamente la regla implícita en una corrección del magistrado
    y la escribe en 02_wiki/conceptos/conceptos.md.

    No emite señales visibles al usuario — opera completamente en background.
    Si falla, el error se registra en el log de Python pero no interrumpe la UI.
    """

    def __init__(
        self,
        instruccion: str,
        materia: str,
        *,
        parent=None,
    ):
        super().__init__(parent)
        self._instruccion = instruccion.strip()
        self._materia = materia

    def run(self) -> None:
        if not self._instruccion:
            return
        try:
            client = _get_client()
            prompt = _CORRECTION_PROMPT.format(
                instruccion=self._instruccion[:1200],
                materia=self._materia or "general",
            )
            regla = _call_haiku(client, prompt, max_tokens=256)
            if not regla or len(regla.strip()) < 10:
                return
            regla = regla.strip().strip('"').strip("'")[:_MAX_RULE_LENGTH]
            self._append_rule(regla)
        except Exception:
            pass  # silencioso — no interrumpe la UI

    def _append_rule(self, regla: str) -> None:
        """Añade la regla al archivo conceptos.md creando la sección si no existe."""
        dest = _CONCEPTOS_MD_PATH
        dest.parent.mkdir(parents=True, exist_ok=True)

        ts = datetime.now().strftime("%Y-%m-%d")
        entry = f"- [{ts}] ({self._materia}) {regla}\n"

        if dest.is_file():
            existing = dest.read_text(encoding="utf-8", errors="replace")
        else:
            existing = "# Conceptos y criterios del magistrado\n"

        if _CONCEPTOS_MD_LEARNING_HEADER.strip() in existing:
            # Sección ya existe — añadir al final de ella
            idx = existing.find(_CONCEPTOS_MD_LEARNING_HEADER.strip())
            insert_pos = existing.find("\n\n##", idx + 1)
            if insert_pos == -1:
                new_content = existing.rstrip() + "\n" + entry
            else:
                new_content = existing[:insert_pos] + entry + existing[insert_pos:]
        else:
            # Crear sección por primera vez
            new_content = existing.rstrip() + _CONCEPTOS_MD_LEARNING_HEADER + entry

        dest.write_text(new_content, encoding="utf-8")
