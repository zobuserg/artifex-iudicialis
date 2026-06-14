"""
graph.py — Grafo LangGraph de la fábrica de resoluciones.

Arquitectura de la cinta:

  START
    └─► node_resumen_hechos        [E1]
          └─► node_cp_hechos       [★ ALTO — el juez revisa ①]
                └─► node_busqueda  [E2]
                      └─► node_cp_fuentes  [★ ALTO — el juez revisa ②]
                            └─► node_redaccion  [E3]
                                  └─► node_cp_borrador  [★ ALTO — el juez revisa ③]
                                        └─► node_formato  [E6]
                                              └─► END

Los tres nodos de checkpoint usan ``interrupt()`` de LangGraph para pausar
la ejecución y esperar la respuesta del juez.  La UI reanuda con:

    graph.invoke(Command(resume={"accion": "aprobar"}), config=config)
    graph.invoke(Command(resume={"accion": "editar", "texto": "..."}), config=config)

El grafo usa ``MemorySaver`` por defecto (estado en memoria, sin base de datos).
Para producción se puede cambiar por un checkpointer con persistencia (SQLite,
Postgres) sin modificar este módulo.
"""

from __future__ import annotations

from typing import Any

import os
import warnings

# Suprimir DeprecationWarning de LangGraph sobre tipos Enum en msgpack.
# Etapa y Postura se deserializan correctamente; el warning es solo preventivo.
# Se puede volver a habilitar con LANGGRAPH_STRICT_MSGPACK=true para auditar.
os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "false")
warnings.filterwarnings(
    "ignore",
    message="Deserializing unregistered type",
    category=DeprecationWarning,
)

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from app.artifex.state import CasoState, Etapa
from app.core.file_manager import BASE_DIR
from app.artifex.nodes import (
    node_busqueda_fundamentos,
    node_formato,
    node_redaccion,
    node_resumen_hechos,
    node_verificacion,
)


# ── Nodos de checkpoint (human-in-the-loop) ───────────────────────────────────

def node_cp_hechos(state: CasoState) -> dict[str, Any]:
    """Checkpoint ① — pausa para que el juez revise hechos Y problema jurídico.

    La UI muestra dos campos editables:
      - hechos_resumen  (narración objetiva de los hechos)
      - agravios        (problema jurídico del recurso — lo que determina el RAG)

    Acepta:
      {"accion": "aprobar"}
      {"accion": "aprobar", "texto": "<hechos editados>", "agravios": "<agravios editados>"}
    """
    human = interrupt({
        "checkpoint": "hechos",
        "etiqueta": "Checkpoint ① — Hechos y problema jurídico",
        "instruccion": (
            "Revisa el resumen de hechos y el problema jurídico del recurso. "
            "Corrige lo que haga falta — el problema jurídico determina qué "
            "jurisprudencia buscará el sistema."
        ),
        "contenido": state.hechos_resumen or "",
        "agravios":  state.agravios or "",
    })

    h = human or {}
    updates: dict[str, Any] = {"etapa": Etapa.BUSQUEDA}
    if "texto" in h:
        updates["hechos_resumen"] = h["texto"]
    if "agravios" in h:
        updates["agravios"] = h["agravios"]
    return updates


def node_cp_fuentes(state: CasoState) -> dict[str, Any]:
    """Checkpoint ② — pausa para que el juez revise los fundamentos curados.

    Acepta:
      {"accion": "aprobar"}
      {"accion": "editar", "texto": "<nuevos fundamentos>"}
    """
    human = interrupt({
        "checkpoint": "fuentes",
        "etiqueta": "Checkpoint ② — Fundamentos jurídicos",
        "instruccion": (
            "Revisa la lista de normas y jurisprudencia curada. "
            "'aprobar' para redactar con estos fundamentos, "
            "'editar' para ajustar la lista antes de la redacción."
        ),
        "contenido": state.fuentes or "",
    })

    h = human or {}
    updates: dict[str, Any] = {"etapa": Etapa.REDACCION}
    # La UI siempre envía el texto filtrado por los checkboxes del juez, tanto
    # en "aprobar" como en "editar". Siempre actualizamos state.fuentes para
    # que solo los fundamentos que el juez marcó lleguen a E3.
    if "texto" in h:
        updates["fuentes"] = h["texto"]
    return updates


def node_cp_borrador(state: CasoState) -> dict[str, Any]:
    """Checkpoint ③ — pausa para que el juez revise el borrador completo.

    Incluye los avisos de E4 (validación) para que el juez vea si hay
    citas sin respaldo, postura incoherente o estructura incompleta.

    Acepta:
      {"accion": "aprobar"}
      {"accion": "editar", "texto": "<borrador corregido>"}
    """
    # Filtrar solo los avisos de E4 para mostrarlos en el checkpoint
    avisos_e4 = [a for a in state.avisos if a.startswith("[E4]")]
    nota_validacion = ""
    if avisos_e4:
        nota_validacion = "\n\nAVISOS DE VALIDACION:\n" + "\n".join(avisos_e4)

    human = interrupt({
        "checkpoint": "borrador",
        "etiqueta": "Checkpoint ③ — Borrador de la resolución",
        "instruccion": (
            "Revisa el borrador completo. "
            "'aprobar' para generar el .docx final, "
            "'editar' para corregir el texto antes de exportar."
            + (f" — {len(avisos_e4)} aviso(s) de validación." if avisos_e4 else "")
        ),
        "contenido": (state.borrador or "") + nota_validacion,
    })

    accion = (human or {}).get("accion", "aprobar")
    if accion == "editar":
        texto = (human or {}).get("texto", state.borrador or "")
        return {"borrador": texto, "etapa": Etapa.FORMATO}
    return {"etapa": Etapa.FORMATO}


# ── Construcción del grafo ────────────────────────────────────────────────────

def _build_builder() -> StateGraph:
    """Ensambla el StateGraph sin compilar (útil para testing)."""
    builder = StateGraph(CasoState)

    # Estaciones de la fábrica
    builder.add_node("resumen_hechos",    node_resumen_hechos)
    builder.add_node("cp_hechos",         node_cp_hechos)
    builder.add_node("busqueda",          node_busqueda_fundamentos)
    builder.add_node("cp_fuentes",        node_cp_fuentes)
    builder.add_node("redaccion",         node_redaccion)
    builder.add_node("verificacion",      node_verificacion)
    builder.add_node("cp_borrador",       node_cp_borrador)
    builder.add_node("formato",           node_formato)

    # Cinta lineal: E1 → cp① → E2 → cp② → E3 → E4 → cp③ → E6
    builder.add_edge(START,             "resumen_hechos")
    builder.add_edge("resumen_hechos",  "cp_hechos")
    builder.add_edge("cp_hechos",       "busqueda")
    builder.add_edge("busqueda",        "cp_fuentes")
    builder.add_edge("cp_fuentes",      "redaccion")
    builder.add_edge("redaccion",       "verificacion")
    builder.add_edge("verificacion",    "cp_borrador")
    builder.add_edge("cp_borrador",     "formato")
    builder.add_edge("formato",         END)

    return builder


_DB_PATH = BASE_DIR / "outputs" / "artifex_state.db"


def _default_checkpointer():
    """SqliteSaver sobre ``outputs/artifex_state.db`` (persiste entre reinicios).

    Usa una conexión sqlite3 directa con ``check_same_thread=False`` para
    permitir acceso desde hilos QThread sin necesidad de context-manager.
    Devuelve también la conexión para que el llamador pueda cerrarla al salir.
    """
    import sqlite3 as _sqlite3
    from langgraph.checkpoint.sqlite import SqliteSaver as _SqliteSaver

    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = _sqlite3.connect(str(_DB_PATH), check_same_thread=False)
    return _SqliteSaver(conn), conn


def compile_graph(checkpointer=None):
    """Devuelve el grafo compilado.

    Args:
        checkpointer: checkpointer de LangGraph.  Si es ``None`` usa
            ``SqliteSaver`` sobre ``outputs/artifex_state.db`` (persistente).
            Pasar ``MemorySaver()`` para tests sin disco.

    Returns:
        (compiled_graph, conn) donde ``conn`` es la conexión sqlite (o None
        si se pasó un checkpointer externo). Llamar ``conn.close()`` al salir.
    """
    if checkpointer is None:
        saver, conn = _default_checkpointer()
    else:
        saver, conn = checkpointer, None
    return _build_builder().compile(checkpointer=saver), conn


# ── API de uso ────────────────────────────────────────────────────────────────

def make_config(thread_id: str) -> dict:
    """Config mínima para identificar un caso en el checkpointer."""
    return {"configurable": {"thread_id": thread_id}}


def start_run(graph, state: CasoState, thread_id: str) -> dict:
    """Arranca el grafo desde el inicio.

    Devuelve el resultado de ``graph.invoke`` que puede ser:
      - El estado final (si llegó a END sin interrupciones)
      - Un dict con ``__interrupt__`` si se pausó en un checkpoint
    """
    config = make_config(thread_id)
    return graph.invoke(state, config=config)


def resume_run(graph, response: dict, thread_id: str) -> dict:
    """Reanuda el grafo después de un checkpoint.

    Args:
        graph:      grafo compilado.
        response:   dict con la respuesta del juez, ej:
                    {"accion": "aprobar"}
                    {"accion": "editar", "texto": "nuevo texto"}
        thread_id:  el mismo thread_id que se usó en start_run.

    Returns:
        Resultado de ``graph.invoke`` (puede volver a pausarse).
    """
    config = make_config(thread_id)
    return graph.invoke(Command(resume=response), config=config)


def get_state(graph, thread_id: str):
    """Devuelve el estado actual del grafo para un thread_id."""
    config = make_config(thread_id)
    return graph.get_state(config)


# ── Persistencia del proceso como archivos .md (robusto, legible en Obsidian) ──
#
# El proceso (hechos, agravios, fuentes, borrador) se guarda como .md en
# outputs/<folder_name>/proceso/. Esto hace que "Ver proceso" NO dependa de la
# BD SQLite (binaria, frágil) ni de que exista el .docx. Los archivos son
# legibles directamente y abribles en Obsidian.

# Campo de CasoState → nombre de archivo en la carpeta proceso/.
_PROCESO_FILES: dict[str, str] = {
    "hechos_resumen": "01_hechos.md",
    "agravios":       "02_agravios.md",
    "fuentes":        "03_fuentes.md",
    "borrador":       "04_borrador.md",
}


def proceso_dir(folder_name: str) -> "Any":
    """Carpeta outputs/<folder_name>/proceso/ donde se persiste el proceso."""
    return BASE_DIR / "outputs" / folder_name / "proceso"


def _proceso_field(values, key: str):
    """Lee un campo de un dict o de un CasoState indistintamente."""
    if isinstance(values, dict):
        return values.get(key)
    return getattr(values, key, None)


def save_proceso_to_folder(folder_name: str, values) -> None:
    """Persiste hechos/agravios/fuentes/borrador como .md en outputs/<folder>/proceso/.

    ``values`` puede ser un dict (snapshot del grafo) o un CasoState. Solo escribe
    los campos con contenido (no borra un .md previo escribiendo vacío). No lanza:
    la persistencia es best-effort y nunca debe romper el pipeline ni la UI.
    """
    if not folder_name:
        return
    try:
        d = proceso_dir(folder_name)
        d.mkdir(parents=True, exist_ok=True)
        for field, fname in _PROCESO_FILES.items():
            txt = _proceso_field(values, field)
            if txt and str(txt).strip():
                (d / fname).write_text(str(txt).strip(), encoding="utf-8")
    except Exception:
        pass


def has_proceso_guardado(folder_name: str) -> bool:
    """True si existe al menos un .md de proceso para el caso (chequeo barato)."""
    if not folder_name:
        return False
    d = proceso_dir(folder_name)
    if not d.is_dir():
        return False
    return any((d / fname).is_file() for fname in _PROCESO_FILES.values())


def load_proceso_from_folder(folder_name: str) -> dict:
    """Lee los .md de proceso de outputs/<folder>/proceso/ en un dict de campos.

    Devuelve {} si no hay nada. Es la fuente preferida (legible, robusta) frente
    al checkpointer SQLite.
    """
    out: dict[str, str] = {}
    d = proceso_dir(folder_name)
    if not d.is_dir():
        return out
    for field, fname in _PROCESO_FILES.items():
        p = d / fname
        if p.is_file():
            try:
                txt = p.read_text(encoding="utf-8", errors="replace").strip()
            except OSError:
                continue
            if txt:
                out[field] = txt
    return out


def _recover_from_sqlite(folder_name: str, db_path=None) -> dict | None:
    """Snapshot más completo del caso desde el checkpointer SQLite (o None)."""
    import sqlite3
    from langgraph.checkpoint.sqlite import SqliteSaver

    path = db_path or _DB_PATH
    if not path.is_file():
        return None

    conn = sqlite3.connect(str(path), check_same_thread=False)
    try:
        saver = SqliteSaver(conn)
        best: dict | None = None
        best_score = -1
        for cp in saver.list(None):
            vals = cp.checkpoint.get("channel_values", {})
            if not isinstance(vals, dict):
                continue
            if vals.get("folder_name") != folder_name:
                continue
            score = (
                bool(vals.get("hechos_resumen"))
                + bool(vals.get("fuentes"))
                + bool(vals.get("borrador"))
            )
            if score > best_score:
                best_score, best = score, vals
        return best
    except Exception:
        return None
    finally:
        conn.close()


def recover_state_by_folder(folder_name: str, db_path=None) -> CasoState | None:
    """Recupera el estado de un caso ya procesado para revisar su proceso completo.

    Fuente combinada y robusta:
      1. Base de metadatos: el snapshot más completo del checkpointer SQLite
         (materia, expediente, postura, slots, documento_final…).
      2. Sobre esa base se SUPERPONEN los .md de proceso de
         outputs/<folder>/proceso/ (hechos, agravios, fuentes, borrador) cuando
         existen — son legibles, recientes e independientes de la BD.

    Si solo hay archivos .md (sin SQLite), construye un estado mínimo con la
    materia inferida del disco. Devuelve ``None`` si no hay nada que recuperar.
    """
    from app.core.file_manager import (
        DEFAULT_MATERIA,
        list_case_folders,
        materia_label as _ml,
    )

    sqlite_vals = _recover_from_sqlite(folder_name, db_path=db_path)
    file_vals = load_proceso_from_folder(folder_name)

    if sqlite_vals is None and not file_vals:
        return None

    fields = set(CasoState.model_fields.keys())
    data: dict = {}
    if sqlite_vals:
        data.update({k: v for k, v in sqlite_vals.items() if k in fields})
    # Los .md de proceso tienen prioridad (más legibles y robustos que la BD).
    data.update({k: v for k, v in file_vals.items() if k in fields})

    # Mínimos para construir un CasoState válido cuando no había SQLite.
    data.setdefault("folder_name", folder_name)
    if not data.get("materia"):
        materia = DEFAULT_MATERIA
        try:
            for f in list_case_folders(materia=None):
                if f.name == folder_name:
                    parts = f.parts
                    if "01_raw" in parts:
                        i = parts.index("01_raw")
                        if i + 1 < len(parts):
                            materia = parts[i + 1]
                    break
        except Exception:
            pass
        data["materia"] = materia
    if not data.get("materia_label"):
        try:
            data["materia_label"] = _ml(data["materia"])
        except Exception:
            data["materia_label"] = ""

    try:
        return CasoState(**data)
    except Exception:
        return CasoState.model_construct(**data)
