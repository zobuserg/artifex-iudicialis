"""
La caja que viaja la cinta — estado Pydantic de un caso en la fábrica.

Hoy, el motor antiguo pasa un ``dict`` suelto (``prompt_kwargs``) a
``build_enriched_prompt``: ~20 campos sin validar. Esta es la versión
formalizada de esa caja, con dos diferencias clave:

  1. Validación: los campos tienen tipo y se verifican al construir el estado.
     Un caso mal armado falla aquí, antes de gastar una llamada a la API.

  2. Campos de progreso: además de las entradas del juez, la caja lleva los
     resultados que cada estación va llenando (resumen de hechos, fuentes,
     borrador, citas verificadas, documento final). Empiezan vacíos y se
     completan a medida que la cinta avanza.

Referencia visual: la "fábrica de resoluciones". Cada campo está anotado con
la estación que lo llena y quién decide (dorado = el juez, verde = la máquina).
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field


class Etapa(str, Enum):
    """Dónde está la caja en la cinta. Avanza en este orden."""

    INGRESO = "ingreso"            # IN · expediente recién cargado
    RESUMEN = "resumen"           # estación 1 · resumen de hechos
    CHECKPOINT_HECHOS = "checkpoint_hechos"   # ★ ALTO · el juez revisa ①
    BUSQUEDA = "busqueda"         # estación 2 · búsqueda de fundamentos (RAG)
    CHECKPOINT_FUENTES = "checkpoint_fuentes"  # ★ ALTO · el juez revisa ②
    REDACCION = "redaccion"       # estación 3 · redacción de la resolución
    VERIFICACION = "verificacion" # estación 4 · red contra cita falsa
    PULIDO = "pulido"             # estación 5 · pulido del lenguaje
    CHECKPOINT_BORRADOR = "checkpoint_borrador"  # ★ ALTO · el juez revisa ③
    FORMATO = "formato"           # estación 6 · plantilla .docx
    FINAL = "final"               # OUT · resolución lista a firma


class Postura(str, Enum):
    """Dirección de la decisión del juez sobre la apelación.

    Espejo de ``_formato_postura`` en claude_worker.py. ``PERSONALIZADO`` usa
    el texto libre de ``CasoState.postura_personalizada``.
    """

    CONFIRMAR = "confirmar"
    REVOCAR = "revocar"
    REVOCAR_PARCIAL = "revocar_parcial"
    PERSONALIZADO = "personalizado"


class CasoState(BaseModel):
    """La caja completa: entradas del juez + resultados de cada estación.

    Las entradas (las pone el juez en el muelle) son obligatorias o tienen un
    default razonable. Los resultados de estación empiezan en ``None`` y los
    llena la cinta a medida que avanza.
    """

    model_config = {"arbitrary_types_allowed": True}

    # ── Identidad del caso ────────────────────────────────────────────────
    materia: str = Field(description="Slug de la materia, p. ej. 'prision_preventiva'")
    materia_label: str = Field(default="", description="Etiqueta legible de la materia")
    folder_name: str = Field(description="Carpeta del caso, p. ej. 'caso_018_robo'")
    caso_num: str = Field(default="", description="Número del caso (texto)")
    tipo: str = Field(default="", description="Subtipo dentro de la materia")

    # ── Entradas del juez (dorado · el muelle) ────────────────────────────
    # Los 6 surcos del expediente: slot_key → lista de rutas de archivo.
    slots: dict[str, list[Path]] = Field(default_factory=dict)
    slot_labels: dict[str, str] = Field(default_factory=dict)
    plantilla_path: Path | None = Field(default=None)
    postura: Postura = Field(default=Postura.CONFIRMAR)
    postura_personalizada: str = Field(default="")
    agravios: str = Field(default="", description="Agravios; si vacío, se extraen del recurso")
    agravios_list: list[str] = Field(default_factory=list, description="Agravios parseados en lista (uno por ítem)")
    instruccion_particular: str = Field(default="", description="Nota del juez para este caso")
    # Hasta 3 resoluciones del magistrado como referencia de ESTILO (no contenido jurídico).
    resoluciones_estilo: list[Path] = Field(
        default_factory=list,
        description="Resoluciones propias del juez para guiar el tono y estilo de redacción",
    )

    # ── Metadatos del encabezado (dorado) ─────────────────────────────────
    expediente: str = Field(default="")
    imputados: str = Field(default="")
    delito: str = Field(default="")
    agraviado: str = Field(default="")
    juzgado: str = Field(default="")

    # ── Contexto automático (verde · el sistema lo inyecta solo) ──────────
    # Se llenan en la estación de búsqueda; no los toca el juez.
    instruccion_general: str = Field(default="", description="Instrucción permanente de la materia")
    bibliografia: list[Path] = Field(default_factory=list)

    # ── Modo de generación ────────────────────────────────────────────────
    modo: str = Field(default="completo", description="'completo' o 'continuar'")
    borrador_path: str = Field(default="")

    # ── Resultados de estación (se llenan en la cinta) ────────────────────
    # estación 1 → el juez revisa ①
    hechos_resumen: str | None = Field(default=None)
    # estación 2 (RAG) → el juez revisa ②
    fuentes: str | None = Field(default=None, description="Fundamentos hallados (normas/jurisprudencia)")
    # estación 3
    borrador: str | None = Field(default=None)
    # estación 4 — red contra cita falsa
    citas_ok: bool | None = Field(default=None)
    # estación 6 → OUT
    documento_final: str | None = Field(default=None)

    # ── Opciones de búsqueda ──────────────────────────────────────────────
    use_live_web: bool = Field(default=False, description="Si True, E2 busca en web (Tavily) además del RAG")

    # ── Control de la cinta ───────────────────────────────────────────────
    etapa: Etapa = Field(default=Etapa.INGRESO)
    avisos: list[str] = Field(default_factory=list, description="Warnings acumulados (tamaño, OCR, etc.)")

    def slot_count(self) -> int:
        """Cuántos archivos hay cargados en total entre los 6 surcos."""
        return sum(len(v) for v in self.slots.values())
