"""
artifex_page.py — Tab de la fábrica Artifex en la UI principal.

Layout:
  ┌─────────────────┬────────────────────────────────────────────┐
  │ CONFIGURACIÓN   │  PIPELINE (pasos + estado)                 │
  │ (formulario)    │                                            │
  │                 │  ━━━━━━━━━━ CHECKPOINT ACTIVO ━━━━━━━━━━  │
  │                 │  [texto del contenido a revisar]           │
  │                 │  [Aprobar]  [Editar y continuar]           │
  └─────────────────┴────────────────────────────────────────────┘

El worker corre graph.invoke() en un QThread. Cuando LangGraph hace
interrupt(), el thread termina, emite checkpoint_hit y la UI lo maneja.
"Aprobar" / "Editar" llanza un nuevo thread con Command(resume=...).
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from PyQt6.QtCore import Qt, QThread, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QFont
from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.core.env_load import load_repo_dotenv
from app.core.file_manager import (
    BASE_DIR,
    MATERIA_LABELS,
    MATERIA_SLUGS,
    list_case_folders,
    materia_label,
    read_fuentes_slots,
    read_instruccion_general,
    slot_labels_for,
)
from app.ui.theme import get_app_theme

_TH = get_app_theme()

# ── Colores del tema ──────────────────────────────────────────────────────────
BG        = _TH.bg
BG_CARD   = _TH.bg_card
BG_INPUT  = _TH.bg_input
GOLD      = _TH.gold
TEXT      = _TH.text
MUTED     = _TH.muted
BORDER    = _TH.border
SUCCESS   = _TH.success
ERROR     = _TH.error

# Colores de estado de cada paso del pipeline
_CLR_IDLE    = "#5a5a6a"   # gris — pendiente
_CLR_RUNNING = "#c9a227"   # dorado — en ejecución
_CLR_PAUSED  = "#4fc3f7"   # azul claro — checkpoint activo
_CLR_DONE    = "#66bb6a"   # verde — completado
_CLR_ERROR   = "#ef5350"   # rojo — error


# ── Worker: corre UNA invocación del grafo en un hilo separado ────────────────

class _ArtifexWorker(QThread):
    """Corre graph.stream() en background.

    Señales:
      step_done(node_name)    — un nodo terminó (para actualizar el pipeline visual)
      checkpoint_hit(dict)    — interrupt: contiene "checkpoint", "contenido", etc.
      pipeline_done(str)      — llegó a END; str = ruta del .docx (puede ser '')
      error_occurred(str)     — excepción
    """

    step_done      = pyqtSignal(str)
    checkpoint_hit = pyqtSignal(dict)
    pipeline_done  = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(self, graph, invoke_arg: Any, config: dict, parent=None):
        super().__init__(parent)
        self._graph      = graph
        self._invoke_arg = invoke_arg   # CasoState (primer run) o Command (resume)
        self._config     = config

    def run(self):
        try:
            # stream() emite un dict por nodo completado: {"node_name": state_update}
            for chunk in self._graph.stream(
                self._invoke_arg,
                config=self._config,
                stream_mode="updates",
            ):
                for node_name in chunk:
                    if not node_name.startswith("__"):
                        self.step_done.emit(node_name)

            # Después del stream: interrupt o END
            snap = self._graph.get_state(self._config)
            if snap.next:
                interrupts = []
                for task in snap.tasks:
                    interrupts.extend(task.interrupts)
                if interrupts:
                    self.checkpoint_hit.emit(interrupts[0].value)
                else:
                    self.checkpoint_hit.emit({"checkpoint": "?", "contenido": ""})
            else:
                state_vals = snap.values
                docx = ""
                if isinstance(state_vals, dict):
                    docx = state_vals.get("documento_final") or ""
                elif hasattr(state_vals, "documento_final"):
                    docx = state_vals.documento_final or ""
                self.pipeline_done.emit(docx)

        except Exception as exc:
            self.error_occurred.emit(str(exc))


# ── Worker auxiliar: pulido de lenguaje (E5, opcional) ───────────────────────

class _PulirWorker(QThread):
    """Corre node_pulido() en background.

    Emite:
      done(str)   — borrador pulido
      error(str)  — mensaje de error
    """

    done  = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, borrador: str, parent=None):
        super().__init__(parent)
        self._borrador = borrador

    def run(self):
        try:
            from app.artifex.state import CasoState, Postura, Etapa
            from app.artifex.nodes import node_pulido

            # Estado mínimo — node_pulido solo necesita state.borrador
            state = CasoState(
                materia="prision_preventiva",
                materia_label="",
                folder_name="",
                postura=Postura.CONFIRMAR,
                borrador=self._borrador,
                etapa=Etapa.VERIFICACION,
            )
            state = node_pulido(state)
            self.done.emit(state.borrador or self._borrador)
        except Exception as exc:
            self.error.emit(str(exc))


# ── Widgets auxiliares ────────────────────────────────────────────────────────

def _label(text: str, bold: bool = False, color: str = TEXT, size: int = 11) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"color: {color}; font-size: {size}px;"
        + (" font-weight: bold;" if bold else "")
    )
    return lbl


def _field(placeholder: str = "") -> QLineEdit:
    w = QLineEdit()
    w.setPlaceholderText(placeholder)
    w.setStyleSheet(
        f"background: {BG_INPUT}; color: {TEXT}; border: 1px solid {BORDER};"
        "border-radius: 4px; padding: 4px 8px; font-size: 11px;"
    )
    return w


def _btn(text: str, color: str = GOLD, fg: str = "#000") -> QPushButton:
    b = QPushButton(text)
    b.setStyleSheet(
        f"background: {color}; color: {fg}; border-radius: 5px;"
        "padding: 7px 18px; font-size: 12px; font-weight: bold;"
        f"border: none;"
    )
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    return b


class _PipelineStep(QWidget):
    """Un paso del pipeline con indicador de estado."""

    LABELS = {
        "resumen_hechos":  ("E1", "Resumen de hechos"),
        "cp_hechos":       ("★①", "Checkpoint — hechos"),
        "busqueda":        ("E2", "Fundamentos (RAG)"),
        "cp_fuentes":      ("★②", "Checkpoint — fuentes"),
        "redaccion":       ("E3", "Redacción"),
        "verificacion":    ("E4", "Verificación de citas"),
        "cp_borrador":     ("★③", "Checkpoint — borrador"),
        "formato":         ("E6", "Exportar .docx"),
    }

    def __init__(self, node_key: str):
        super().__init__()
        self._key = node_key
        badge_txt, label_txt = self.LABELS.get(node_key, ("?", node_key))

        row = QHBoxLayout(self)
        row.setContentsMargins(4, 2, 4, 2)
        row.setSpacing(8)

        self._badge = QLabel(badge_txt)
        self._badge.setFixedWidth(34)
        self._badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._badge.setStyleSheet(
            f"background: {_CLR_IDLE}; color: #fff; border-radius: 4px;"
            "font-size: 10px; font-weight: bold; padding: 2px 4px;"
        )

        self._name = QLabel(label_txt)
        self._name.setStyleSheet(f"color: {MUTED}; font-size: 11px;")

        self._status = QLabel("pendiente")
        self._status.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._status.setStyleSheet(f"color: {_CLR_IDLE}; font-size: 10px;")

        row.addWidget(self._badge)
        row.addWidget(self._name, stretch=1)
        row.addWidget(self._status)

    def set_idle(self):
        self._badge.setStyleSheet(
            f"background: {_CLR_IDLE}; color: #fff; border-radius: 4px;"
            "font-size: 10px; font-weight: bold; padding: 2px 4px;"
        )
        self._name.setStyleSheet(f"color: {MUTED}; font-size: 11px;")
        self._status.setText("pendiente")
        self._status.setStyleSheet(f"color: {_CLR_IDLE}; font-size: 10px;")

    def set_running(self):
        self._badge.setStyleSheet(
            f"background: {_CLR_RUNNING}; color: #000; border-radius: 4px;"
            "font-size: 10px; font-weight: bold; padding: 2px 4px;"
        )
        self._name.setStyleSheet(f"color: {TEXT}; font-size: 11px; font-weight: bold;")
        self._status.setText("ejecutando…")
        self._status.setStyleSheet(f"color: {_CLR_RUNNING}; font-size: 10px;")

    def set_paused(self):
        self._badge.setStyleSheet(
            f"background: {_CLR_PAUSED}; color: #000; border-radius: 4px;"
            "font-size: 10px; font-weight: bold; padding: 2px 4px;"
        )
        self._name.setStyleSheet(f"color: {TEXT}; font-size: 11px; font-weight: bold;")
        self._status.setText("esperando revisión")
        self._status.setStyleSheet(f"color: {_CLR_PAUSED}; font-size: 10px;")

    def set_done(self):
        self._badge.setStyleSheet(
            f"background: {_CLR_DONE}; color: #fff; border-radius: 4px;"
            "font-size: 10px; font-weight: bold; padding: 2px 4px;"
        )
        self._name.setStyleSheet(f"color: {TEXT}; font-size: 11px;")
        self._status.setText("listo")
        self._status.setStyleSheet(f"color: {_CLR_DONE}; font-size: 10px;")

    def set_error(self):
        self._badge.setStyleSheet(
            f"background: {_CLR_ERROR}; color: #fff; border-radius: 4px;"
            "font-size: 10px; font-weight: bold; padding: 2px 4px;"
        )
        self._status.setText("error")
        self._status.setStyleSheet(f"color: {_CLR_ERROR}; font-size: 10px;")


# ── Página principal ──────────────────────────────────────────────────────────

class ArtifexPage(QWidget):
    """Tab «Fábrica» — pipeline completo de redacción automatizada."""

    # Orden de steps del pipeline (8 pasos con E4)
    # idx: 0=E1  1=cp① 2=E2  3=cp② 4=E3  5=E4  6=cp③  7=E6
    _STEP_ORDER = [
        "resumen_hechos", "cp_hechos",
        "busqueda", "cp_fuentes",
        "redaccion", "verificacion", "cp_borrador",
        "formato",
    ]

    # Mapa checkpoint → índice del step en el pipeline
    _CP_TO_STEP = {
        "hechos":   1,   # cp_hechos
        "fuentes":  3,   # cp_fuentes
        "borrador": 6,   # cp_borrador (idx 6 con E4 incluido)
    }
    _CP_DONE_BEFORE = {
        "hechos":   [0],              # solo E1 hecho cuando llega cp①
        "fuentes":  [0, 1, 2],        # E1+cp①+E2 hechos cuando llega cp②
        "borrador": [0, 1, 2, 3, 4, 5],  # E1→E4 hechos cuando llega cp③
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._graph = None          # compilado al primer uso
        self._db_conn = None        # conexión SQLite (ciclo de vida de la página)
        self._thread_id: str = ""
        self._worker: _ArtifexWorker | None = None
        self._current_checkpoint: dict = {}
        self._shortcut_state = None  # CasoState pre-cargado (modo "cargar borrador")

        self._build_ui()

    # ── Construcción UI ───────────────────────────────────────────────────────

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setStyleSheet(f"background: {BG};")

        splitter.addWidget(self._build_left_panel())
        splitter.addWidget(self._build_right_panel())
        splitter.setSizes([320, 700])
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)

        root.addWidget(splitter)

    def _build_left_panel(self) -> QWidget:
        w = QWidget()
        w.setMinimumWidth(280)
        w.setMaximumWidth(380)
        w.setStyleSheet(f"background: {BG_CARD}; border-right: 1px solid {BORDER};")

        vbox = QVBoxLayout(w)
        vbox.setContentsMargins(16, 16, 16, 16)
        vbox.setSpacing(10)

        # Título
        title = QLabel("FÁBRICA ARTIFEX")
        title.setStyleSheet(
            f"color: {GOLD}; font-size: 13px; font-weight: bold; letter-spacing: 1px;"
        )
        vbox.addWidget(title)

        sub = QLabel("Redacción asistida con checkpoints del juez")
        sub.setStyleSheet(f"color: {MUTED}; font-size: 10px;")
        sub.setWordWrap(True)
        vbox.addWidget(sub)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {BORDER};")
        vbox.addWidget(sep)

        # Materia
        vbox.addWidget(_label("Materia", bold=True))
        self._cmb_materia = QComboBox()
        self._cmb_materia.setStyleSheet(
            f"background: {BG_INPUT}; color: {TEXT}; border: 1px solid {BORDER};"
            "border-radius: 4px; padding: 4px 8px; font-size: 11px;"
        )
        for slug in sorted(MATERIA_SLUGS):
            self._cmb_materia.addItem(MATERIA_LABELS.get(slug, slug), slug)
        # Dejar prision_preventiva como default si existe
        idx = self._cmb_materia.findData("prision_preventiva")
        if idx >= 0:
            self._cmb_materia.setCurrentIndex(idx)
        self._cmb_materia.currentIndexChanged.connect(self._on_materia_change)
        vbox.addWidget(self._cmb_materia)

        # Caso
        vbox.addWidget(_label("Caso", bold=True))
        self._cmb_caso = QComboBox()
        self._cmb_caso.setStyleSheet(
            f"background: {BG_INPUT}; color: {TEXT}; border: 1px solid {BORDER};"
            "border-radius: 4px; padding: 4px 8px; font-size: 11px;"
        )
        vbox.addWidget(self._cmb_caso)

        # Metadatos
        for attr, label, ph in [
            ("_fld_exp",      "Expediente",  "ej. 634-2026-68"),
            ("_fld_imp",      "Imputados",   "nombre(s)"),
            ("_fld_delito",   "Delito",      "ej. tenencia ilegal de armas"),
            ("_fld_agrav",    "Agraviado",   "ej. El Estado"),
            ("_fld_juzgado",  "Juzgado",     "juzgado de origen"),
        ]:
            vbox.addWidget(_label(label, bold=True))
            fld = _field(ph)
            setattr(self, attr, fld)
            vbox.addWidget(fld)

        # Postura
        vbox.addWidget(_label("Postura", bold=True))
        self._cmb_postura = QComboBox()
        self._cmb_postura.setStyleSheet(
            f"background: {BG_INPUT}; color: {TEXT}; border: 1px solid {BORDER};"
            "border-radius: 4px; padding: 4px 8px; font-size: 11px;"
        )
        for val, lbl in [
            ("confirmar",      "CONFIRMAR"),
            ("revocar",        "REVOCAR"),
            ("revocar_parcial","REVOCAR PARCIALMENTE"),
        ]:
            self._cmb_postura.addItem(lbl, val)
        vbox.addWidget(self._cmb_postura)

        vbox.addStretch()

        # Botón iniciar
        self._btn_iniciar = _btn("▶  INICIAR PIPELINE")
        self._btn_iniciar.clicked.connect(self._on_iniciar)
        vbox.addWidget(self._btn_iniciar)

        # Botón cargar borrador (shortcut: salta E1-E3)
        self._btn_cargar = _btn("📂  Cargar borrador .md", color=BG_INPUT, fg=TEXT)
        self._btn_cargar.setToolTip(
            "Carga un borrador existente (.md) y va directo al\n"
            "Checkpoint ③ para revisar y exportar sin re-ejecutar\n"
            "las estaciones E1-E3 (evita los ~19 minutos de API)."
        )
        self._btn_cargar.clicked.connect(self._on_cargar_borrador)
        vbox.addWidget(self._btn_cargar)

        # Status
        self._lbl_status = QLabel("")
        self._lbl_status.setStyleSheet(f"color: {MUTED}; font-size: 10px;")
        self._lbl_status.setWordWrap(True)
        vbox.addWidget(self._lbl_status)

        self._on_materia_change()   # poblar combo de casos
        return w

    def _build_right_panel(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet(f"background: {BG};")

        vbox = QVBoxLayout(w)
        vbox.setContentsMargins(20, 16, 20, 16)
        vbox.setSpacing(12)

        # Pipeline steps
        steps_label = _label("PIPELINE", bold=True, size=12)
        vbox.addWidget(steps_label)

        self._steps: dict[str, _PipelineStep] = {}
        for key in ArtifexPage._STEP_ORDER:
            step = _PipelineStep(key)
            self._steps[key] = step
            vbox.addWidget(step)

        # Separador
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {BORDER};")
        vbox.addWidget(sep)

        # Área de checkpoint
        self._cp_title = _label("", bold=True, color=_CLR_PAUSED, size=12)
        vbox.addWidget(self._cp_title)

        self._cp_instruccion = _label("", color=MUTED)
        self._cp_instruccion.setWordWrap(True)
        vbox.addWidget(self._cp_instruccion)

        self._cp_editor = QPlainTextEdit()
        self._cp_editor.setReadOnly(True)
        self._cp_editor.setStyleSheet(
            f"background: {BG_CARD}; color: {TEXT}; border: 1px solid {BORDER};"
            "border-radius: 4px; font-size: 11px; font-family: 'Consolas', monospace;"
        )
        self._cp_editor.setMinimumHeight(220)
        vbox.addWidget(self._cp_editor, stretch=1)

        # Botones de checkpoint
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self._btn_aprobar = _btn("✔  Aprobar", color=SUCCESS, fg="#000")
        self._btn_aprobar.clicked.connect(self._on_aprobar)
        self._btn_aprobar.setVisible(False)

        self._btn_editar = _btn("✎  Editar", color=BG_CARD, fg=TEXT)
        self._btn_editar.clicked.connect(self._on_editar)
        self._btn_editar.setVisible(False)

        self._btn_pulir = _btn("✨  Pulir lenguaje", color=BG_CARD, fg=TEXT)
        self._btn_pulir.setToolTip(
            "Pasa el borrador por Claude Sonnet para pulir\n"
            "el lenguaje sin cambiar el fondo jurídico.\n"
            "Solo disponible en Checkpoint ③ (borrador)."
        )
        self._btn_pulir.clicked.connect(self._on_pulir)
        self._btn_pulir.setVisible(False)

        self._btn_guardar_edicion = _btn("✔  Guardar edición", color=SUCCESS, fg="#000")
        self._btn_guardar_edicion.clicked.connect(self._on_guardar_edicion)
        self._btn_guardar_edicion.setVisible(False)

        btn_row.addWidget(self._btn_aprobar)
        btn_row.addWidget(self._btn_editar)
        btn_row.addWidget(self._btn_pulir)
        btn_row.addWidget(self._btn_guardar_edicion)
        btn_row.addStretch()
        vbox.addLayout(btn_row)

        # Resultado final + botón abrir
        res_row = QHBoxLayout()
        self._lbl_resultado = QLabel("")
        self._lbl_resultado.setStyleSheet(
            f"color: {SUCCESS}; font-size: 12px; font-weight: bold;"
        )
        self._lbl_resultado.setWordWrap(True)
        self._btn_abrir_docx = _btn("📄 Abrir .docx", color="#2d6a4f", fg="#fff")
        self._btn_abrir_docx.setVisible(False)
        self._btn_abrir_docx.clicked.connect(self._on_abrir_docx)
        res_row.addWidget(self._lbl_resultado, stretch=1)
        res_row.addWidget(self._btn_abrir_docx)
        vbox.addLayout(res_row)

        return w

    # ── Lógica de materia / caso ──────────────────────────────────────────────

    def _on_materia_change(self):
        materia = self._current_materia()
        self._cmb_caso.clear()
        try:
            carpetas = list_case_folders(materia)
            for f in carpetas:
                self._cmb_caso.addItem(f.name, str(f))
        except Exception:
            pass

    def _current_materia(self) -> str:
        return self._cmb_materia.currentData() or "prision_preventiva"

    # ── Modo "Cargar borrador" (shortcut: salta E1-E3) ────────────────────────

    def _on_cargar_borrador(self):
        """Carga un .md existente y va directo al Checkpoint ③."""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Seleccionar borrador (.md)",
            str(Path("outputs")),
            "Markdown (*.md);;Todos los archivos (*)",
        )
        if not path:
            return

        borrador = Path(path).read_text(encoding="utf-8", errors="replace").strip()
        if not borrador:
            self._set_status("El archivo está vacío.", error=True)
            return

        materia   = self._current_materia()
        expediente = self._fld_exp.text().strip()
        imputados  = self._fld_imp.text().strip()
        delito     = self._fld_delito.text().strip()
        agraviado  = self._fld_agrav.text().strip()
        juzgado    = self._fld_juzgado.text().strip()
        postura_v  = self._cmb_postura.currentData() or "confirmar"

        try:
            from app.artifex.state import CasoState, Postura, Etapa
            caso_path = self._cmb_caso.currentData() or ""
            caso_folder = Path(caso_path) if caso_path else Path(".")
            state = CasoState(
                materia=materia,
                materia_label=materia_label(materia),
                folder_name=caso_folder.name,
                expediente=expediente,
                imputados=imputados,
                delito=delito or materia_label(materia),
                agraviado=agraviado or "El Estado",
                juzgado=juzgado,
                postura=Postura(postura_v),
                instruccion_general=read_instruccion_general(materia),
                borrador=borrador,
                etapa=Etapa.VERIFICACION,
            )
        except Exception as e:
            self._set_status(f"Error al construir estado: {e}", error=True)
            return

        # Correr E4 directamente (9ms, sin API)
        self._reset_pipeline_ui()
        self._lbl_resultado.setText("")

        # Marcar E1-E4 como done visualmente
        for key in ["resumen_hechos", "cp_hechos", "busqueda", "cp_fuentes",
                    "redaccion", "verificacion"]:
            self._steps[key].set_done()
        self._steps["cp_borrador"].set_running()

        try:
            from app.artifex.nodes import node_verificacion
            state = node_verificacion(state)
        except Exception as e:
            self._set_status(f"Error en verificación: {e}", error=True)
            return

        # Guardar en shortcut_state para el flujo Aprobar/Editar→E6
        self._shortcut_state = state
        self._thread_id = ""  # no usamos grafo en este modo

        # Construir el payload del checkpoint igual que node_cp_borrador
        avisos_e4 = [a for a in state.avisos if a.startswith("[E4]")]
        nota = ("\n\nAVISOS DE VALIDACION:\n" + "\n".join(avisos_e4)) if avisos_e4 else ""
        self._on_checkpoint_hit({
            "checkpoint": "borrador",
            "etiqueta": "Checkpoint ③ — Borrador cargado",
            "instruccion": (
                "Borrador cargado desde archivo. Revisa y aprueba para generar el .docx."
                + (f" — {len(avisos_e4)} aviso(s) de validación." if avisos_e4 else "")
            ),
            "contenido": borrador + nota,
        })
        self._set_status(f"Borrador cargado: {Path(path).name}")

    # ── Iniciar pipeline ──────────────────────────────────────────────────────

    def _on_iniciar(self):
        if self._worker and self._worker.isRunning():
            return

        load_repo_dotenv()
        if self._graph is None:
            try:
                from app.artifex.graph import compile_graph
                self._graph, self._db_conn = compile_graph()
            except Exception as e:
                self._set_status(f"Error al compilar grafo: {e}", error=True)
                return

        materia    = self._current_materia()
        caso_path  = self._cmb_caso.currentData()
        expediente = self._fld_exp.text().strip()
        imputados  = self._fld_imp.text().strip()
        delito     = self._fld_delito.text().strip()
        agraviado  = self._fld_agrav.text().strip()
        juzgado    = self._fld_juzgado.text().strip()
        postura_v  = self._cmb_postura.currentData() or "confirmar"

        if not caso_path:
            self._set_status("Selecciona un caso antes de iniciar.", error=True)
            return

        caso_folder = Path(caso_path)

        try:
            from app.artifex.state import CasoState, Postura
            slots = read_fuentes_slots(caso_folder)
            state = CasoState(
                materia=materia,
                materia_label=materia_label(materia),
                folder_name=caso_folder.name,
                caso_num=caso_folder.name.split("_")[1] if "_" in caso_folder.name else "",
                slots=slots,
                slot_labels=slot_labels_for(materia),
                expediente=expediente,
                imputados=imputados,
                delito=delito or materia_label(materia),
                agraviado=agraviado or "El Estado",
                juzgado=juzgado,
                postura=Postura(postura_v),
                instruccion_general=read_instruccion_general(materia),
            )
        except Exception as e:
            self._set_status(f"Error al cargar el caso: {e}", error=True)
            return

        # Nuevo thread_id para este run
        self._thread_id = str(uuid.uuid4())
        self._shortcut_state = None  # salir de modo shortcut si estaba activo
        self._reset_pipeline_ui()
        self._lbl_resultado.setText("")
        self._set_status("Ejecutando: Resumen de hechos…")
        self._btn_iniciar.setEnabled(False)
        # Marcar el primer paso como "running" inmediatamente
        self._steps["resumen_hechos"].set_running()

        self._run_invoke(state)

    # ── Checkpoint: aprobar / editar ──────────────────────────────────────────

    def _on_aprobar(self):
        self._hide_checkpoint_buttons()
        if self._shortcut_state is not None:
            self._shortcut_export(self._shortcut_state.borrador)
            return
        self._set_status("Aprobado — continuando…")
        self._mark_next_idle_as_running()
        self._run_invoke({"accion": "aprobar"}, is_resume=True)

    def _on_editar(self):
        """Cambia el editor a modo edición."""
        self._cp_editor.setReadOnly(False)
        self._cp_editor.setStyleSheet(
            f"background: {BG_INPUT}; color: {TEXT}; border: 1px solid {GOLD};"
            "border-radius: 4px; font-size: 11px; font-family: 'Consolas', monospace;"
        )
        self._btn_aprobar.setVisible(False)
        self._btn_editar.setVisible(False)
        self._btn_guardar_edicion.setVisible(True)

    def _on_guardar_edicion(self):
        texto_editado = self._cp_editor.toPlainText()
        self._cp_editor.setReadOnly(True)
        self._cp_editor.setStyleSheet(
            f"background: {BG_CARD}; color: {TEXT}; border: 1px solid {BORDER};"
            "border-radius: 4px; font-size: 11px; font-family: 'Consolas', monospace;"
        )
        self._hide_checkpoint_buttons()
        if self._shortcut_state is not None:
            self._shortcut_export(texto_editado)
            return
        self._set_status("Edición guardada — continuando…")
        self._mark_next_idle_as_running()
        self._run_invoke({"accion": "editar", "texto": texto_editado}, is_resume=True)

    def _on_pulir(self):
        """Lanza E5 (node_pulido) en background y actualiza el editor al terminar."""
        borrador = self._cp_editor.toPlainText().strip()
        if not borrador:
            self._set_status("Nada que pulir — el editor está vacío.", error=True)
            return

        # Bloquear UI mientras trabaja Haiku
        self._btn_aprobar.setEnabled(False)
        self._btn_editar.setEnabled(False)
        self._btn_pulir.setEnabled(False)
        self._btn_pulir.setText("⏳  Puliendo…")
        self._set_status("Puliendo lenguaje con Claude Haiku (~30s)…")

        self._pulir_worker = _PulirWorker(borrador, parent=self)
        self._pulir_worker.done.connect(self._on_pulido_done)
        self._pulir_worker.error.connect(self._on_pulido_error)
        self._pulir_worker.start()

    def _on_pulido_done(self, texto_pulido: str):
        self._cp_editor.setPlainText(texto_pulido)
        # Si estaba en modo shortcut, actualizar el borrador en el state
        if self._shortcut_state is not None:
            self._shortcut_state.borrador = texto_pulido

        self._btn_aprobar.setEnabled(True)
        self._btn_editar.setEnabled(True)
        self._btn_pulir.setEnabled(True)
        self._btn_pulir.setText("✨  Pulir lenguaje")
        self._btn_pulir.setVisible(True)
        self._set_status("✔ Lenguaje pulido. Revisa y aprueba cuando estés listo.")

    def _on_pulido_error(self, msg: str):
        self._btn_aprobar.setEnabled(True)
        self._btn_editar.setEnabled(True)
        self._btn_pulir.setEnabled(True)
        self._btn_pulir.setText("✨  Pulir lenguaje")
        self._set_status(f"Error en pulido: {msg}", error=True)

    def _hide_checkpoint_buttons(self):
        self._btn_aprobar.setVisible(False)
        self._btn_editar.setVisible(False)
        self._btn_pulir.setVisible(False)
        self._btn_guardar_edicion.setVisible(False)

    # ── Worker ────────────────────────────────────────────────────────────────

    def _run_invoke(self, arg: Any, *, is_resume: bool = False):
        from langgraph.types import Command
        from app.artifex.graph import make_config

        if is_resume:
            invoke_arg = Command(resume=arg)
        else:
            invoke_arg = arg

        config = make_config(self._thread_id)
        self._worker = _ArtifexWorker(self._graph, invoke_arg, config, parent=self)
        self._worker.step_done.connect(self._on_step_done)
        self._worker.checkpoint_hit.connect(self._on_checkpoint_hit)
        self._worker.pipeline_done.connect(self._on_pipeline_done)
        self._worker.error_occurred.connect(self._on_error)
        self._worker.start()

    # ── Señales del worker ────────────────────────────────────────────────────

    def _on_step_done(self, node_name: str):
        """Un nodo terminó: lo marca como done y activa el siguiente como running."""
        order = ArtifexPage._STEP_ORDER
        if node_name not in order:
            return
        idx = order.index(node_name)
        self._steps[node_name].set_done()
        # Activar el siguiente paso como "running" (si existe y no es checkpoint)
        next_idx = idx + 1
        if next_idx < len(order):
            next_key = order[next_idx]
            # Los checkpoints se muestran como "running" brevemente antes del interrupt
            self._steps[next_key].set_running()
            self._set_status(f"Ejecutando: {_PipelineStep.LABELS.get(next_key, (None, next_key))[1]}…")

    def _on_checkpoint_hit(self, info: dict):
        cp_key = info.get("checkpoint", "")
        step_idx = self._CP_TO_STEP.get(cp_key, -1)
        done_indices = self._CP_DONE_BEFORE.get(cp_key, [])

        for i, key in enumerate(ArtifexPage._STEP_ORDER):
            if i in done_indices:
                self._steps[key].set_done()
            elif i == step_idx:
                self._steps[key].set_paused()
            else:
                self._steps[key].set_idle()

        # Mostrar contenido del checkpoint
        self._cp_title.setText(info.get("etiqueta", f"Checkpoint — {cp_key}"))
        self._cp_instruccion.setText(info.get("instruccion", ""))
        contenido = info.get("contenido", "")
        self._cp_editor.setPlainText(contenido)
        self._cp_editor.setReadOnly(True)
        self._cp_editor.setStyleSheet(
            f"background: {BG_CARD}; color: {TEXT}; border: 1px solid {BORDER};"
            "border-radius: 4px; font-size: 11px; font-family: 'Consolas', monospace;"
        )

        self._btn_aprobar.setVisible(True)
        self._btn_editar.setVisible(True)
        self._btn_guardar_edicion.setVisible(False)
        # "Pulir lenguaje" solo en el checkpoint del borrador (el texto es largo y editable)
        self._btn_pulir.setVisible(cp_key == "borrador")

        self._set_status(f"Esperando revisión en checkpoint: {cp_key}")
        self._btn_iniciar.setEnabled(True)

        self._current_checkpoint = info

    def _on_pipeline_done(self, docx_path: str):
        # Marcar todos como done
        for step in self._steps.values():
            step.set_done()

        self._cp_title.setText("")
        self._cp_instruccion.setText("")
        self._hide_checkpoint_buttons()

        self._docx_path = docx_path
        if docx_path:
            nombre = Path(docx_path).name
            self._lbl_resultado.setText(f"✔  {nombre}")
            self._btn_abrir_docx.setVisible(True)
        else:
            self._lbl_resultado.setText("Pipeline completado.")
            self._btn_abrir_docx.setVisible(False)

        self._set_status("Listo.")
        self._btn_iniciar.setEnabled(True)

    def _on_abrir_docx(self):
        path = getattr(self, "_docx_path", "")
        if path and Path(path).is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _shortcut_export(self, borrador_texto: str):
        """Exporta directamente a .docx en modo shortcut (sin grafo)."""
        state = self._shortcut_state
        if state is None:
            return
        state.borrador = borrador_texto

        self._steps["cp_borrador"].set_done()
        self._steps["formato"].set_running()
        self._set_status("Generando .docx…")

        try:
            from app.artifex.nodes import node_formato
            state = node_formato(state)
            self._shortcut_state = None
            self._on_pipeline_done(state.documento_final or "")
        except Exception as e:
            self._on_error(f"Exportación fallida: {e}")

    def _on_error(self, msg: str):
        for step in self._steps.values():
            step.set_error()
        self._set_status(f"Error: {msg}", error=True)
        self._btn_iniciar.setEnabled(True)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _mark_next_idle_as_running(self):
        """Marca el primer paso que todavía esté en 'idle' como 'running'."""
        for key in ArtifexPage._STEP_ORDER:
            step = self._steps[key]
            # Detectar si está idle comparando el texto del status
            if step._status.text() in ("pendiente", ""):
                step.set_running()
                self._set_status(
                    f"Ejecutando: {_PipelineStep.LABELS.get(key, (None, key))[1]}…"
                )
                return

    def _reset_pipeline_ui(self):
        for step in self._steps.values():
            step.set_idle()
        self._cp_title.setText("")
        self._cp_instruccion.setText("")
        self._cp_editor.setPlainText("")
        self._hide_checkpoint_buttons()

    def _set_status(self, msg: str, *, error: bool = False):
        color = ERROR if error else MUTED
        self._lbl_status.setStyleSheet(f"color: {color}; font-size: 10px;")
        self._lbl_status.setText(msg)
