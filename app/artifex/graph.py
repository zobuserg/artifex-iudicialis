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
    """Checkpoint ① — pausa para que el juez revise el resumen de hechos.

    La UI muestra ``state.hechos_resumen`` y espera la respuesta.
    Acepta:
      {"accion": "aprobar"}
      {"accion": "editar", "texto": "<nuevo resumen>"}
    """
    human = interrupt({
        "checkpoint": "hechos",
        "etiqueta": "Checkpoint ① — Resumen de hechos",
        "instruccion": (
            "Lee el resumen y decide: 'aprobar' para continuar con estos hechos, "
            "'editar' para reemplazar el texto antes de buscar fundamentos."
        ),
        "contenido": state.hechos_resumen or "",
    })

    accion = (human or {}).get("accion", "aprobar")
    if accion == "editar":
        texto = (human or {}).get("texto", state.hechos_resumen or "")
        return {"hechos_resumen": texto, "etapa": Etapa.BUSQUEDA}
    return {"etapa": Etapa.BUSQUEDA}


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

    accion = (human or {}).get("accion", "aprobar")
    if accion == "editar":
        texto = (human or {}).get("texto", state.fuentes or "")
        return {"fuentes": texto, "etapa": Etapa.REDACCION}
    return {"etapa": Etapa.REDACCION}


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
