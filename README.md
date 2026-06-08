# Artifex Iudicialis — Fábrica de Resoluciones Judiciales

Aplicación de escritorio (Windows, PyQt6)  
Genera resoluciones en formato `.docx` oficial, con IA y control total del usuario en cada paso.

---

## Cómo funciona

El sistema usa un **pipeline LangGraph** con tres puntos de control donde el juez decide:

```
E1 Resumen de hechos
      ★ Control ① — el juez revisa y aprueba el resumen
E2 Búsqueda de fundamentos (RAG + boletines en vivo opcional)
      ★ Control ② — el juez selecciona los fundamentos a usar
E3 Redacción del borrador
E4 Verificación de citas
      ★ Control ③ — el juez revisa el borrador, puede reescribir párrafos
E6 Formato .docx oficial
```

**Bucle de corrección:** en el Control ③, seleccione cualquier fragmento de texto,
escriba una instrucción ("simplifica este párrafo / agrega cita del Acuerdo Plenario X"),
y la fábrica reescribe solo esa parte sin tocar el resto.

**Boletines en vivo:** active el toggle al iniciar y la fábrica busca jurisprudencia reciente
en LP Derecho, SPIJ, Gaceta Jurídica y el portal del Poder Judicial (Tavily).

---

## Requisitos

- Python 3.10 o superior  
- Clave API de Anthropic ([console.anthropic.com](https://console.anthropic.com))  
- Opcional: clave Tavily ([tavily.com](https://tavily.com)) para boletines en vivo

---

## Instalación (Windows)

```powershell
# 1. Clonar el repositorio
git clone https://github.com/zobuserg/artifex-iudicialis.git
cd artifex-iudicialis

# 2. Crear entorno virtual
python -m venv .venv
.venv\Scripts\Activate.ps1

# 3. Instalar dependencias
pip install -r app/requirements.txt

# 4. Configurar claves
copy .env.example .env
# Abrir .env y pegar ANTHROPIC_API_KEY (y TAVILY_API_KEY si se usa)
notepad .env

# 5. Ejecutar
python -m app
```

---

## Variables de entorno (`.env`)

| Variable | Obligatoria | Descripción |
|---|---|---|
| `ANTHROPIC_API_KEY` | ✅ | Clave API de Anthropic |
| `TAVILY_API_KEY` | Opcional | Para boletines en vivo |
| `ADIUTOR_CLAUDE_RESOLUTION_MODEL` | Opcional | Modelos a usar (default: `claude-opus-4-5,claude-sonnet-4-5`) |

---

## Estructura del proyecto

```
app/
  artifex/          ← motor LangGraph (grafo, nodos, estado)
  core/             ← utilidades (PDF, Word, file manager, LLM)
  ui/
    fabrica.py      ← UI completa (pantallas 0-4, workers, bucle de corrección)
    artifex_window.py ← ventana principal
01_raw/             ← documentos del juez (ignorados por git — datos privados)
outputs/            ← resoluciones generadas (ignoradas por git)
```

---

## Datos privados

Los directorios `01_raw/`, `02_wiki/`, `03_outputs/` y `outputs/` están en `.gitignore`.
Nunca se suben expedientes ni resoluciones al repositorio.
