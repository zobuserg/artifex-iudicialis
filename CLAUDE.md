# Artifex Iudicialis — Contexto para Claude Code

## Qué es esto

App de escritorio (PyQt6, Windows) que genera resoluciones judiciales para la
**Sala Penal de Apelaciones de Chincha y Pisco** del Poder Judicial del Perú.
El cliente es un juez. El sistema automatiza la redacción de autos de vista
usando un pipeline LangGraph con tres puntos de control donde el juez aprueba
o corrige antes de continuar.

## ⚠️ LEER PRIMERO — UI viva y protocolo de cambios

El usuario es **un juez sin experiencia en programación** que trabaja por
vibecoding. Si no se siguen estas dos secciones, los cambios "fallan en
silencio": se aplican pero el juez nunca los ve, y concluye que no funcionaron.

### UI VIVA — dónde tocar

- **La interfaz que el juez ve al correr la app es `app/ui/fabrica.py`.**
  TODO cambio visual o de flujo va AHÍ.
- `app/ui/main_window.py` y `app/ui/artifex_page.py` son **rutas de UI antiguas**
  que siguen en el repo por compatibilidad. **Editarlas NO cambia nada en la app
  que corre el juez.** Excepción: `WikiConsultaPage` (chat del wiki) vive en
  `main_window.py` y se reutiliza desde `fabrica.py`.
- Si no estás 100% seguro de qué pantalla/elemento se refiere el juez,
  **pide una captura** antes de tocar. No adivines.

### Protocolo de vibecoding (obligatorio en cada cambio)

1. **Confirmar el qué.** Reformular el pedido en una frase, en lenguaje llano,
   antes de editar.
2. **Localizar antes de tocar.** Leer el código real (grep + Read). Identificar
   el archivo correcto (casi siempre `fabrica.py`).
3. **Cambio quirúrgico.** Tocar lo mínimo. No mezclar refactors con el arreglo.
4. **Verificar SIEMPRE.** `py_compile` como mínimo; correr la app si aplica.
   Nunca decir "hecho" sin haber verificado.
5. **Decir cómo verlo.** Indicar al juez: "cierra y reabre la app (no hay recarga
   en caliente) y ve a tal pantalla". El juez no lee código: la confirmación
   visual es su única forma de validar.
6. **Separar diagnosticar de arreglar.** Si algo falla, primero diagnosticar;
   no encadenar parches a ciegas. Si un bug se resiste, empezar conversación
   nueva (el contexto se degrada).

> Estas reglas están alineadas con los principios de Karpathy para CLAUDE.md
> (pensar antes de codear · simplicidad · cambios quirúrgicos · ejecución
> verificada) y con las prácticas anti «doom loop» del vibecoding.

## Cómo correr la app

```powershell
# Desde la raíz del proyecto
.\.venv\Scripts\python.exe -m app
```

Requiere `.env` con `ANTHROPIC_API_KEY`. Ver `.env.example`.

## Arquitectura — el pipeline

```
E1  node_resumen_hechos      → resume los hechos del expediente (RAG sobre PDFs)
★①  node_cp_hechos           → INTERRUPT: el juez revisa el resumen
E2  node_busqueda_fundamentos → busca jurisprudencia y normas (RAG + Tavily opcional)
★②  node_cp_fuentes          → INTERRUPT: el juez selecciona fuentes
E3  node_redaccion            → redacta el borrador completo
E4  node_verificacion         → verifica citas (sin API, ~9ms)
★③  node_cp_borrador          → INTERRUPT: el juez revisa, puede reescribir fragmentos
E6  node_formato              → exporta .docx con encabezado institucional oficial
```

Los tres `interrupt()` de LangGraph pausan el grafo. La UI reanuda con
`Command(resume={"accion": "aprobar", "texto": "..."})`.

## Entrada / Salida — HECHOS CANÓNICOS (no re-investigar)

**Lectura (cualquier formato):** el lector universal es
`app/core/claude_worker.py::read_file_text()`. Soporta `.pdf .docx .doc .pages .md
.txt` + audio. La fuente de verdad de formatos es `DOC_SUFFIXES` y el helper
`qt_open_filter()`. **TODOS los QFileDialog de la UI usan `qt_open_filter()`** — no
hardcodear filtros. Para agregar un formato: ampliar `read_file_text` + `DOC_SUFFIXES`.

**Exportación (renderizado del .docx):** el renderizador OFICIAL es
`app/core/word_export.py::text_to_docx_faithful()` — reproduce el texto del modelo
LITERAL (respeta el formato de la plantilla, no reinyecta cabecera). Lo usan E6
(`node_formato`) y la revisión. `markdown_to_docx()` es LEGACY y NO se usa.
**Membrete pág. 1**: si existe `app/resources/membrete.png` (imagen válida >1KB), se
inserta a ancho de cuerpo al inicio de la página 1 (`_insert_membrete`) y se OMITEN
las líneas de texto PODER JUDICIAL/CORTE/SALA (ya están en la imagen, evita duplicar).

> Mapa de arquitectura completo en
> `/Users/dagumar/.claude/projects/-Users-dagumar/memory/project_architecture.md`.

## Archivos clave

```
app/
  __main__.py          → entry point (python -m app)
  main.py              → lanza ArtifexWindow
  ui/
    artifex_window.py  → QMainWindow principal (solo envuelve FabricaWidget)
    fabrica.py         → TODO el UI: 5 pantallas, workers, bucle de corrección
  artifex/
    graph.py           → compile_graph(), make_config(), nodos de checkpoint
    nodes.py           → node_resumen_hechos, node_busqueda_fundamentos, node_redaccion,
                         node_verificacion, node_pulido, node_formato, _buscar_en_vivo
    state.py           → CasoState (Pydantic), Etapa (enum), Postura (enum)
    llm.py             → call_model() con fallback de modelos
  core/
    word_export.py     → markdown_to_docx(), _build_header(), _parse_lines()
    file_manager.py    → BASE_DIR, MATERIA_SLUGS/LABELS, list_case_folders(),
                         read_fuentes_slots(), slot_labels_for(), materia_label()
    env_load.py        → load_repo_dotenv()
    pdf_extract.py     → extracción de texto de PDFs (pdfplumber + OCR opcional)
    claude_worker.py   → workers del sistema viejo (mantener para compatibilidad)
    wiki_worker.py     → ingesta de bibliografía y corpus (sistema viejo)

outputs/               → .docx generados (ignorado por git)
01_raw/                → documentos del juez organizados por materia/caso (ignorado por git)
  prision_preventiva/
    caso_018_robo/
      solicitud_inicial/     ← requerimiento fiscal
      resolucion_apelada/    ← auto de primera instancia
      recurso_apelacion/     ← recurso que llegó a la Sala
      anexos/                ← actos de investigación, pruebas
      audio/                 ← transcripciones de audiencia
      otros/                 ← resto
```

## Modelos

La cuenta de Anthropic del cliente tiene acceso a:
- `claude-opus-4-5` ← modelo principal (E3, redacción)
- `claude-sonnet-4-5` ← fallback y pulido de lenguaje

Configurar en `.env`:
```
ADIUTOR_CLAUDE_RESOLUTION_MODEL=claude-opus-4-5,claude-sonnet-4-5
```

Además, el pre-filtro de artículos (E2, `wiki_worker.extract_relevant_articles`) usa:
- `claude-haiku-4-5-20251001` ← SÍ disponible y verificado en esta cuenta (~1s).

**NO usar:** `claude-opus-4-7`, `claude-sonnet-4-6` — no disponibles en esta cuenta.
(El fallback viejo `claude-3-5-haiku-20241022` da 404; el primario Haiku 4.5 funciona.)

## Rendimiento — códigos globales en texto plano

`01_raw/bibliografia/global/` debe contener los códigos (CP, CPP, Constitución)
como **.txt**, no PDF. E2 los lee en cada generación; en PDF (175 MB) tardaba
~140 s por corrida, en .txt es instantáneo. Los PDF originales se guardan en
`01_raw/bibliografia/_global_pdf_originales/`. Si se agregan códigos nuevos en
PDF, conviene convertirlos a .txt una sola vez.

## Formato del .docx — FIDELIDAD A LA PLANTILLA (cambiado 2026-06-07)

**Una sola fuente de formato: la plantilla.** El modelo reproduce el encabezado y el
formato EXACTOS de la plantilla (Bloque 3), incluyendo PODER JUDICIAL / CORTE / el
nombre de la Sala tal como aparece en la plantilla y el bloque de metadatos. El
exportador renderiza ese texto **tal cual**, sin reinyectar cabecera ni reformatear.

- Renderizador: `word_export.text_to_docx_faithful()` (NO `markdown_to_docx`).
  Usado por E6 (`node_formato`) y por la función "Revisar resolución" (`fabrica.py`).
- Instrucción al modelo: `_espina_aprobada()` en `nodes.py` le ordena reproducir el
  encabezado y formato de la plantilla al pie de la letra (antes le decía lo
  contrario — esa contradicción causaba encabezados duplicados y "SALA PENAL" en
  lugar de "SALA SUPERIOR PENAL").
- `markdown_to_docx()` se conserva por compatibilidad pero ya NO se usa en el pipeline.

**Por qué:** son resoluciones judiciales, no borradores — el formato debe ser
estricto e idéntico a la plantilla. El estilo de casa hardcodeado en
`markdown_to_docx` no respetaba las diferencias entre plantillas (p. ej. punto final
en títulos romanos, nombre de la Sala).

## Estado del proyecto (al momento de este commit)

- Pipeline LangGraph completo y funcional (E1→E6 con 3 checkpoints)
- UI nueva con diseño papel cálido (mockup de referencia)
- Bucle de corrección implementado (checkpoint ③: seleccionar fragmento → reescribir)
- Boletines en vivo (Tavily) implementado en E2
- Cargar borrador .md → salta directo a checkpoint ③
- Setup screen: materia + caso (surcos) + metadata + postura + instrucción particular

## Reglas de código para este proyecto

1. **No romper el pipeline LangGraph** — `graph.py` y los nodos son el corazón.
   Cualquier cambio en `nodes.py` requiere probar con el test de cadena.

2. **Los datos del juez nunca van al git** — `01_raw/`, `02_wiki/`, `03_outputs/`,
   `outputs/`, `.env` están en `.gitignore`. Nunca hacer `git add -A` sin revisar.

3. **Modelos disponibles** — solo `claude-opus-4-5` y `claude-sonnet-4-5`. No cambiar
   por otros sin confirmar con el juez.

4. **El .docx no se toca directo** — todo cambio de formato va por `word_export.py`.
   La función `_parse_lines()` filtra los duplicados del encabezado que Claude escribe.

5. **Surgical changes** — tocar solo lo necesario. El `main_window.py` viejo sigue
   ahí por compatibilidad; no eliminarlo aún.

## Tests

```powershell
# Test de cadena completa (requiere API key activa, ~18 min)
.\.venv\Scripts\python.exe test_cadena_caso012.py
```

Los outputs de test van a `outputs/prueba_cadena/` (ignorado por git).

## Memoria de sesión — LEER AL INICIAR

Al iniciar cualquier sesión en este proyecto, leer obligatoriamente:

```
/Users/dagumar/.claude/projects/-Users-dagumar/memory/MEMORY.md
```

Ese índice apunta a los archivos de memoria relevantes. Leer los que apliquen al
trabajo de la sesión antes de responder cualquier pregunta técnica.

**Actualizar la memoria cuando:**
- Termina una regeneración de resolución (con resultado en chars)
- Se confirma o descarta un fix de calidad
- Cambia el objetivo del troubleshooting activo
- El juez aprueba un resultado como satisfactorio

## Cómo instalar desde cero (en otra máquina)

```powershell
git clone https://github.com/zobuserg/artifex-iudicialis.git
cd artifex-iudicialis
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r app/requirements.txt
copy .env.example .env
# Editar .env con la clave API
notepad .env
python -m app
```
