# WikiJuez — Sistema de Resoluciones Judiciales

Aplicación de escritorio (PyQt6) para organizar expedientes, bibliografía y plantillas,
generar **prompts estructurados** para el asistente en Cursor (según `.cursorrules`) y
exportar borradores desde Markdown a Word o PDF.

La interfaz puede **generar el acto con Claude** vía API Anthropic («GENERAR CON CLAUDE») o seguir el flujo de
**copiar el prompt** para Cursor. El texto de los PDF se obtiene **en local** con `app/core/pdf_extract.py`
(pdfplumber y, si hace falta, Tesseract); la API puede recibir además los PDF como **documento nativo**
(ver variables `ADIUTOR_API_PDF_*` en `.env.example`).

---

## Requisitos

- Python 3.9 o superior (3.10+ recomendado)
- Dependencias listadas en `app/requirements.txt`
- **Opcional:** [Ollama](https://ollama.com/) en el mismo equipo si quieres usar el worker con modelo local
- **PDF escaneados (OCR):** **Tesseract** (pdfplumber primero; si el texto nativo es insuficiente, render + pytesseract; si sigue débil, segundo paso con OCR de página completa vía PyMuPDF). macOS: `brew install tesseract tesseract-lang`. Linux: `sudo apt install tesseract-ocr tesseract-ocr-spa`. Variables útiles: `ADIUTOR_OCR_MAX_PAGES` (default 100), `ADIUTOR_OCR_ZOOM` (default 2.0), `ADIUTOR_OCR_DPI` (default 150, paso MuPDF), `ADIUTOR_TESSERACT_CONFIG` (default `--oem 3 --psm 6`), `ADIUTOR_OCR_LANG` (default `spa`). Desactivar OCR: `ADIUTOR_OCR=0`.
- **Corpus (resoluciones previas):** se pueden procesar **varios archivos a la vez** (por defecto 3 en paralelo). Ajusta `ADIUTOR_CORPUS_WORKERS` (1–8). Incluye `.pdf`, `.docx` y **`.doc`** (macOS: `textutil`; Linux: `antiword` si está instalado).

---

## Instalación

```bash
cd WikiJuridico

python3 -m venv .venv
source .venv/bin/activate

pip install --upgrade pip
pip install -r app/requirements.txt
```

En macOS puedes usar el script `setup.sh`, que crea el venv e instala dependencias.

---

## Uso

```bash
source .venv/bin/activate
python app/main.py
```

---

## Flujo de trabajo (interfaz actual)

1. Crea o selecciona un **caso** bajo `01_raw/caso_NNN_…` y añade archivos (incluida la carpeta `fuentes/`).
2. Gestiona **plantillas** y **bibliografía** desde las pestañas correspondientes.
3. Pulsa **GENERAR PROMPT** / **GENERAR PROMPT ACTUALIZADO** para obtener el texto listo para pegar en Cursor y redactar la resolución según la plantilla y el checklist.
4. En **Resoluciones**, revisa los `.md` en `03_outputs/resoluciones/` (la lista muestra primero los **más recientes por fecha de archivo**).
5. Exporta a **Word** o **PDF** cuando lo necesites.

#### Jurisprudencia desde la web y bibliografía guardada

**Qué usa el modelo.** WikiJuez sólo incrusta contenido que está en el árbol del proyecto. En la generación principal, el prompt incluye bibliografía de **`01_raw/bibliografia/<materia>/`** (la materia activa en la barra lateral), **`01_raw/bibliografia/global/`** y, si existen, **`02_wiki/jurisprudencia/jurisprudencia.md`** y **`02_wiki/conceptos/conceptos.md`**. Obsidian no enlaza por sí solo: si el vault no es esta carpeta del proyecto, copie las notas a esas rutas.

**Flujo manual** (material tomado de la web u otra fuente):

1. Sintetice el precedente (expediente, tribunal, fecha, ratio, fuente; extracto literal breve sólo si lo va a reproducir).
2. Guarde **`.md` o `.txt`** en la bibliografía de esa materia, o use **Bibliografía → Nota rápida de jurisprudencia** para rellenar la plantilla.
3. Sirve usar el expediente en el nombre del archivo (p. ej. `Cas_1421-2023_resumen.md`) para el filtro por nombre al iterar.
4. Preparar/generar el caso **de nuevo** para que el archivo entre en el bloque de bibliografía del prompt.

**Iteración.** Puede marcarse **Reinyectar extracto de bibliografía** (coincidencia por expediente en el acto, o bibliografía completa respetando cupos de texto).

Si parece que no usa lo guardado: revise la materia, que la lista Bibliografía liste los archivos, que haya regenerado tras añadir notas y, con PDF escaneados, que el OCR haya producido texto legible.

**PDF difícil:** en la pestaña Bibliografía use **«Probar lectura PDF»**. Si la extracción es mala, guarde `mismo_nombre.txt` o `.md` junto al PDF (transcripción); la app lo fusiona. Variables útiles: `ADIUTOR_OCR_DPI`, `ADIUTOR_OCR_ZOOM`, `ADIUTOR_PDF_NATIVE_MIN_WORDS` (véase `.env.example`).

### PDF en esta Mac frente a PDF en Claude (web o API con archivo)

No es el mismo motor de lectura:

| Dónde | Qué ocurre |
|-------|------------|
| **WikiJuez (local)** | El PDF se convierte a texto en su equipo: capa nativa (pdfplumber + PyMuPDF texto), archivo compañero `.txt`/`.md`, y si hace falta **OCR Tesseract** (orientado a imprenta). Manuscritos o escaneos muy malos suelen seguir siendo el cuello de botella aquí. |
| **Claude con archivo** (chat web o Messages API con `document`) | El proveedor procesa el binario en sus servidores y puede combinar texto, render y **modelos con visión** sobre las páginas. Por eso el mismo archivo a veces «se lee mejor» allí que solo con Tesseract local. |

**Opciones en el producto (sin abandonar el flujo actual):**

- **A — Sin código:** transcripción manual o `.txt`/`.md` junto al PDF; afinar OCR con variables de entorno.
- **B — Generación con API:** con `ADIUTOR_API_PDF_ATTACH=1` (predeterminado) los PDF del expediente y bibliografía del prompt se envían también como **documento nativo** en la petición, además del texto ya extraído localmente. Límites: `ADIUTOR_API_PDF_MAX_TOTAL_MB`, `ADIUTOR_API_PDF_MAX_FILES`. Desactivar solo el envío por API: `ADIUTOR_API_PDF_ATTACH=0`.
- **C — Prototipo visión por páginas:** si desactiva el adjunto PDF (`ADIUTOR_API_PDF_ATTACH=0`) y define `ADIUTOR_VISION_PDF_PAGES` > 0, la primera petición puede incluir las **primeras N páginas del primer PDF** como imágenes PNG (alto coste en tokens; ver `app/core/pdf_vision_pages.py` y `.env.example`).

---

## Estructura del proyecto

```
WikiJuridico/
├── app/
│   ├── main.py
│   ├── requirements.txt
│   ├── core/
│   │   ├── claude_worker.py   ← prompts enriquecidos; iteración (ancla / reinyección bib.)
│   │   ├── file_manager.py    ← rutas, plantillas, exportación
│   │   ├── pdf_extract.py     ← texto PDF local (pdfplumber, OCR, compañero .txt/.md)
│   │   ├── pdf_vision_pages.py ← prototipo: primeras páginas → PNG para API (opcional)
│   │   └── pdf_reader.py      ← envoltorio simple
│   └── ui/
│       ├── main_window.py          ← ventana principal PyQt6
│       └── juris_quick_note_dialog.py  ← nota rápida → .md en bibliografía
├── 01_raw/
│   ├── caso_NNN_…/            ← expedientes por caso
│   ├── bibliografia/          ← doctrina y jurisprudencia (PDF y Word en la app)
│   └── plantillas/
├── 02_wiki/
│   └── INDEX.md
├── 03_outputs/
│   ├── resoluciones/
│   └── exports/
├── .cursorrules
└── .env.example               ← plantilla (ANTHROPIC_API_KEY, OCR, PDF API, etc.)
```

---

## Notas importantes

- El asistente en Cursor debe seguir las reglas de `.cursorrules` (sin inventar jurisprudencia).
- Los PDFs solo con imagen (sin texto seleccionable) requieren OCR antes de cargarlos si necesitas citar folios automáticamente.
- Para **GENERAR CON CLAUDE** hace falta `ANTHROPIC_API_KEY` en `.env` (copie desde `.env.example`). Otras variables opcionales están documentadas allí (PDF en API, OCR, visión por páginas, etc.).
