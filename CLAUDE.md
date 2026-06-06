# Artifex Iudicialis — Contexto para Claude Code

## Qué es esto

App de escritorio (PyQt6, Windows) que genera resoluciones judiciales para la
**Sala Penal de Apelaciones de Chincha y Pisco** del Poder Judicial del Perú.
El cliente es un juez. El sistema automatiza la redacción de autos de vista
usando un pipeline LangGraph con tres puntos de control donde el juez aprueba
o corrige antes de continuar.

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

**NO usar:** `claude-opus-4-7`, `claude-sonnet-4-6`, `claude-haiku-4-5` — no disponibles
en esta cuenta.

## Encabezado institucional del .docx

El sistema agrega automáticamente el encabezado en `word_export.py`:
```
PODER JUDICIAL
CORTE SUPERIOR DE JUSTICIA DE ICA
SALA PENAL DE APELACIONES DE CHINCHA Y PISCO
```
Claude **no debe** repetir este encabezado en el borrador. Ver `_espina_aprobada()`
en `nodes.py` — ya tiene la instrucción explícita.

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
