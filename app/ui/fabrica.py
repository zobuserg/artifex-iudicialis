"""
fabrica.py — Interfaz completa de la Fábrica de Resoluciones (Artifex Iudicialis).

Diseño basado en el mockup del artefacto: estilo papel cálido, stepper dorado,
pantallas apiladas. Incorpora todas las funciones del plan:

  Pantalla 0 · El caso   — materia, caso (slot-based), datos, postura
  Pantalla 1 · ★ Hechos  — resumen editable (checkpoint ①)
  Pantalla 2 · ★ Fuentes — fundamentos con checkboxes RAG/en-vivo (checkpoint ②)
  Pantalla 3 · ★ Borrador — texto + "Reescribir selección" + "Pulir" (checkpoint ③)
  Pantalla 4 · Resolución — documento final + descarga .docx

Cada pantalla es un QWidget dentro de un QStackedWidget.
Los workers LangGraph corren en QThread para no bloquear la UI.
"""

from __future__ import annotations

import difflib
import uuid
from pathlib import Path
from typing import Any

from PyQt6.QtCore import Qt, QThread, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QDesktopServices, QFont, QPalette, QTextCursor
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.core.claude_worker import qt_open_filter
from app.core.env_load import load_repo_dotenv
from app.core.file_manager import (
    BASE_DIR,
    MATERIA_LABELS,
    MATERIA_SLUGS,
    SLOT_KEYS,
    add_bibliografia,
    add_plantilla,
    add_to_case,
    list_bibliografia,
    list_case_folders,
    list_plantillas,
    materia_label,
    read_fuentes_slots,
    read_instruccion_general,
    slot_labels_for,
)

load_repo_dotenv()

# ── Paleta de colores (papel cálido, del mockup) ──────────────────────────────

_C = {
    "paper":    "#f1e7d3",
    "panel":    "#fbf6ea",
    "panel2":   "#f6efe0",
    "card":     "#fffdf8",
    "ink":      "#272a36",
    "ink2":     "#5b5647",
    "faint":    "#938c78",
    "hair":     "#e2d6bd",
    "teal":     "#2f857f",
    "teal_d":   "#1f5f5a",
    "teal_s":   "#e2f0ee",
    "gold":     "#c69a3f",
    "gold_d":   "#9c7a2c",
    "gold_s":   "#f7edd4",
    "alert":    "#c4634c",
    "sage":     "#6f9a76",
    "kraft":    "#b9743f",
}

_STEP_BASE = f"""
    QPushButton {{
        background: {_C['panel2']};
        color: {_C['ink2']};
        border: 1px solid {_C['hair']};
        border-radius: 10px;
        padding: 10px 14px;
        font-size: 13px;
        font-weight: 600;
        text-align: left;
    }}
    QPushButton:hover {{ background: {_C['card']}; }}
"""
_STEP_ACTIVE = f"""
    QPushButton {{
        background: {_C['card']};
        color: {_C['ink']};
        border: 1.5px solid {_C['hair']};
        border-radius: 10px;
        padding: 10px 14px;
        font-size: 13px;
        font-weight: 700;
    }}
"""
_STEP_CHK_ACTIVE = f"""
    QPushButton {{
        background: {_C['gold_s']};
        color: {_C['gold_d']};
        border: 1.5px solid {_C['gold']};
        border-radius: 10px;
        padding: 10px 14px;
        font-size: 13px;
        font-weight: 700;
    }}
"""
_BTN_PRIMARY = f"""
    QPushButton {{
        background: {_C['teal']};
        color: #fff;
        border: none;
        border-radius: 10px;
        padding: 12px 24px;
        font-size: 14px;
        font-weight: 700;
    }}
    QPushButton:hover {{ background: {_C['teal_d']}; }}
    QPushButton:disabled {{ background: {_C['hair']}; color: {_C['faint']}; }}
"""
_BTN_GOLD = f"""
    QPushButton {{
        background: {_C['gold']};
        color: #fff;
        border: none;
        border-radius: 10px;
        padding: 12px 24px;
        font-size: 14px;
        font-weight: 700;
    }}
    QPushButton:hover {{ background: {_C['gold_d']}; }}
    QPushButton:disabled {{ background: {_C['hair']}; color: {_C['faint']}; }}
"""
_BTN_GHOST = f"""
    QPushButton {{
        background: transparent;
        color: {_C['ink2']};
        border: 1px solid {_C['hair']};
        border-radius: 10px;
        padding: 11px 22px;
        font-size: 13px;
        font-weight: 600;
    }}
    QPushButton:hover {{ background: {_C['card']}; }}
    QPushButton:disabled {{ color: {_C['faint']}; }}
"""
_BTN_SAGE = f"""
    QPushButton {{
        background: {_C['sage']};
        color: #fff;
        border: none;
        border-radius: 10px;
        padding: 11px 20px;
        font-size: 13px;
        font-weight: 700;
    }}
    QPushButton:hover {{ background: #5a8a62; }}
    QPushButton:disabled {{ background: {_C['hair']}; color: {_C['faint']}; }}
"""
_BTN_SMALL_GHOST = f"""
    QPushButton {{
        background: transparent;
        color: {_C['ink2']};
        border: 1px solid {_C['hair']};
        border-radius: 8px;
        padding: 6px 12px;
        font-size: 12px;
        font-weight: 600;
    }}
    QPushButton:hover {{ background: {_C['card']}; }}
"""
_INPUT_SS = f"""
    QLineEdit, QComboBox, QPlainTextEdit, QTextEdit {{
        background: {_C['card']};
        color: {_C['ink']};
        border: 1px solid {_C['hair']};
        border-radius: 10px;
        padding: 10px 14px;
        font-size: 13px;
    }}
    QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus, QTextEdit:focus {{
        border: 1.5px solid {_C['teal']};
    }}
    QComboBox::drop-down {{ border: none; }}
"""
_PANEL_SS = f"background: {_C['panel']}; border: 1px solid {_C['hair']}; border-radius: 14px;"
_GOLD_PANEL_SS = f"background: {_C['gold_s']}; border: 1.5px solid {_C['gold']}; border-radius: 14px;"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _lbl(text: str, *, bold=False, size=13, color=None) -> QLabel:
    w = QLabel(text)
    color = color or _C["ink"]
    w.setStyleSheet(
        f"color: {color}; font-size: {size}px;"
        + (" font-weight: 700;" if bold else "")
    )
    w.setWordWrap(True)
    return w


def _sep() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    f.setStyleSheet(f"color: {_C['hair']}; background: {_C['hair']}; border: none; max-height: 1px;")
    return f


def _card(content: QWidget, gold=False) -> QWidget:
    wrap = QWidget()
    wrap.setStyleSheet(_GOLD_PANEL_SS if gold else _PANEL_SS)
    lay = QVBoxLayout(wrap)
    lay.setContentsMargins(22, 18, 22, 18)
    lay.setSpacing(12)
    lay.addWidget(content)
    return wrap


def _scroll(inner: QWidget) -> QScrollArea:
    sa = QScrollArea()
    sa.setWidgetResizable(True)
    sa.setWidget(inner)
    sa.setStyleSheet(f"QScrollArea {{ border: none; background: {_C['paper']}; }}")
    return sa


def _section_label(text: str) -> QLabel:
    """Etiqueta de sección con estilo teal."""
    w = QLabel(text)
    w.setStyleSheet(
        f"color: {_C['teal_d']}; font-size: 13px; font-weight: 700; "
        f"padding-top: 6px;"
    )
    return w


# ── Workers ───────────────────────────────────────────────────────────────────

class _ArtifexWorker(QThread):
    step_done      = pyqtSignal(str)
    checkpoint_hit = pyqtSignal(dict)
    pipeline_done  = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(self, graph, invoke_arg: Any, config: dict, parent=None):
        super().__init__(parent)
        self._graph      = graph
        self._invoke_arg = invoke_arg
        self._config     = config

    def run(self):
        try:
            for chunk in self._graph.stream(
                self._invoke_arg,
                config=self._config,
                stream_mode="updates",
            ):
                for node_name in chunk:
                    if not node_name.startswith("__"):
                        self.step_done.emit(node_name)

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
                vals = snap.values
                docx = ""
                if isinstance(vals, dict):
                    docx = vals.get("documento_final") or ""
                elif hasattr(vals, "documento_final"):
                    docx = vals.documento_final or ""
                self.pipeline_done.emit(docx)
        except Exception as exc:
            self.error_occurred.emit(str(exc))


class _PulirWorker(QThread):
    done  = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, borrador: str, parent=None):
        super().__init__(parent)
        self._borrador = borrador

    def run(self):
        try:
            from app.artifex.state import CasoState, Postura, Etapa
            from app.artifex.nodes import node_pulido
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


class _RewriteWorker(QThread):
    """Bucle de corrección: reescribe solo el fragmento seleccionado."""
    done  = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, borrador: str, fragmento: str, instruccion: str, parent=None):
        super().__init__(parent)
        self._borrador    = borrador
        self._fragmento   = fragmento
        self._instruccion = instruccion

    def run(self):
        try:
            from app.artifex.llm import call_model
            prompt = (
                "Eres asistente del juez de la Sala Penal de Apelaciones.\n"
                "A continuación tienes el borrador completo de una resolución judicial "
                "y un fragmento específico que el juez quiere mejorar.\n\n"
                "INSTRUCCIÓN DEL JUEZ:\n"
                f"{self._instruccion}\n\n"
                "BORRADOR COMPLETO (solo para contexto — no lo reproduzcas):\n"
                f"{self._borrador[:8000]}\n\n"
                "FRAGMENTO A REESCRIBIR:\n"
                f"{self._fragmento}\n\n"
                "Devuelve ÚNICAMENTE el fragmento reescrito siguiendo la instrucción. "
                "Sin marcadores, sin el resto del borrador, sin explicaciones."
            )
            texto, _ = call_model(
                prompt,
                models=("claude-sonnet-4-5", "claude-opus-4-5"),
                max_tokens=2048,
            )
            self.done.emit(texto.strip())
        except Exception as exc:
            self.error.emit(str(exc))


# ── Widget de ranura de documentos ────────────────────────────────────────────

class _SlotCard(QWidget):
    """Tarjeta visual de una ranura del expediente (p. ej. 'solicitud_inicial').

    Muestra cuántos archivos hay, sus nombres, y permite agregar más con un botón +.
    """

    files_changed = pyqtSignal()   # se emite cuando se agregan archivos

    def __init__(self, slot_key: str, label: str, caso_folder: Path | None = None, parent=None):
        super().__init__(parent)
        self._slot_key = slot_key
        self._caso_folder = caso_folder
        self._files: list[Path] = []

        self.setStyleSheet(
            f"background: {_C['card']}; border: 1px solid {_C['hair']}; border-radius: 11px;"
        )

        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(12)

        # Indicador de estado (círculo)
        self._dot = QLabel("○")
        self._dot.setFixedWidth(20)
        self._dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._dot.setStyleSheet(f"color: {_C['faint']}; font-size: 16px; border: none;")
        lay.addWidget(self._dot)

        # Textos
        txt_w = QWidget()
        txt_w.setStyleSheet("border: none;")
        tl = QVBoxLayout(txt_w)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(1)
        self._title = _lbl(label, bold=True, size=12)
        self._title.setStyleSheet(f"color: {_C['ink']}; font-size: 12px; font-weight: 700; border: none;")
        tl.addWidget(self._title)
        self._detail = _lbl("sin archivos", color=_C["faint"], size=10)
        self._detail.setStyleSheet(f"color: {_C['faint']}; font-size: 10px; border: none;")
        tl.addWidget(self._detail)
        lay.addWidget(txt_w, 1)

        # Contador
        self._count_lbl = _lbl("0", bold=True, size=12, color=_C["faint"])
        self._count_lbl.setFixedWidth(28)
        self._count_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._count_lbl.setStyleSheet(
            f"background: {_C['panel2']}; color: {_C['faint']}; "
            f"border-radius: 7px; font-size: 12px; font-weight: 700; "
            f"padding: 2px; border: none;"
        )
        lay.addWidget(self._count_lbl)

        # Botón agregar
        self._btn_add = QPushButton("+")
        self._btn_add.setToolTip("Agregar archivos a esta ranura")
        self._btn_add.setFixedSize(28, 28)
        self._btn_add.setStyleSheet(
            f"QPushButton {{ background: {_C['panel2']}; color: {_C['teal_d']}; "
            f"border: 1px solid {_C['hair']}; border-radius: 7px; "
            f"font-size: 16px; font-weight: 700; padding: 0; }}"
            f"QPushButton:hover {{ background: {_C['teal_s']}; border-color: {_C['teal']}; }}"
        )
        self._btn_add.clicked.connect(self._on_add_files)
        lay.addWidget(self._btn_add)

    def set_files(self, files: list[Path]):
        self._files = list(files)
        n = len(self._files)
        if n == 0:
            self._dot.setText("○")
            self._dot.setStyleSheet(f"color: {_C['faint']}; font-size: 16px; border: none;")
            self._detail.setText("sin archivos")
            self._detail.setStyleSheet(f"color: {_C['faint']}; font-size: 10px; border: none;")
            self._count_lbl.setText("0")
            self._count_lbl.setStyleSheet(
                f"background: {_C['panel2']}; color: {_C['faint']}; "
                f"border-radius: 7px; font-size: 12px; font-weight: 700; padding: 2px; border: none;"
            )
            self.setStyleSheet(
                f"background: {_C['card']}; border: 1px solid {_C['hair']}; border-radius: 11px;"
            )
        else:
            self._dot.setText("●")
            self._dot.setStyleSheet(f"color: {_C['teal']}; font-size: 16px; border: none;")
            names = [f.name for f in self._files[:3]]
            detail = ", ".join(names) + ("…" if n > 3 else "")
            self._detail.setText(detail)
            self._detail.setStyleSheet(f"color: {_C['teal_d']}; font-size: 10px; border: none;")
            self._count_lbl.setText(str(n))
            self._count_lbl.setStyleSheet(
                f"background: {_C['teal_s']}; color: {_C['teal_d']}; "
                f"border-radius: 7px; font-size: 12px; font-weight: 700; padding: 2px; border: none;"
            )
            self.setStyleSheet(
                f"background: {_C['card']}; border: 1.5px solid {_C['teal']}; border-radius: 11px;"
            )

    def set_caso_folder(self, folder: Path | None):
        self._caso_folder = folder

    def _on_add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            f"Agregar a: {self._title.text()}",
            str(BASE_DIR / "01_raw"),
            qt_open_filter(include_audio=True),
        )
        if not paths or not self._caso_folder:
            return
        from app.core.file_manager import (
            read_fuentes_slots,
            write_fuentes_slots_manifest,
        )
        fuentes = self._caso_folder / "fuentes"
        slot_dir = fuentes / self._slot_key
        slot_dir.mkdir(parents=True, exist_ok=True)
        # Copiar a fuentes/<slot>/ (misma convención que lee el pipeline)
        for p in paths:
            add_to_case(Path(p), fuentes, self._slot_key)
        # Reconstruir el manifiesto desde el estado físico actual para que la UI
        # y la fábrica coincidan (evita que el manifiesto previo oculte lo nuevo).
        current = read_fuentes_slots(self._caso_folder)
        mapping: dict[str, list[str]] = {}
        for k, files in current.items():
            rels = []
            for f in files:
                try:
                    rels.append(f.relative_to(fuentes).as_posix())
                except ValueError:
                    pass
            if rels:
                mapping[k] = rels
        # Asegurar que los recién agregados estén bajo este slot
        rels = mapping.get(self._slot_key, [])
        for f in slot_dir.iterdir():
            if f.is_file():
                r = f.relative_to(fuentes).as_posix()
                if r not in rels:
                    rels.append(r)
        mapping[self._slot_key] = rels
        write_fuentes_slots_manifest(self._caso_folder, mapping)
        self.set_files([f for f in slot_dir.iterdir() if f.is_file()])
        self.files_changed.emit()


# ── Pantalla 0: El caso ─────────────────────────────────────────────────────

class _MetaWorker(QThread):
    """Extrae los metadatos del expediente en segundo plano (Haiku), sin bloquear la UI."""

    done   = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, slots, slot_labels, parent=None):
        super().__init__(parent)
        self._slots = slots
        self._slot_labels = slot_labels

    def run(self):
        try:
            from app.artifex.metadata_extract import extract_expediente_metadata
            self.done.emit(extract_expediente_metadata(self._slots, self._slot_labels) or {})
        except Exception as exc:
            self.failed.emit(str(exc))


class _SetupScreen(QWidget):
    """Pantalla 0 — el juez configura el caso antes de iniciar la fábrica.

    Evolución del viejo Adiutor: mismo flujo (materia→caso→metadata→postura)
    pero ahora con vista de ranuras que muestra qué archivos hay en cada slot,
    permite agregar archivos inline, y da retroalimentación visual antes de iniciar.
    """

    iniciar         = pyqtSignal(dict)   # config dict cuando pulsa Iniciar
    cargar_borrador = pyqtSignal(str)    # path .md cuando pulsa Cargar borrador

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background: {_C['paper']};")
        self._live_web = False
        self._slot_cards: dict[str, _SlotCard] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 22, 28, 28)
        root.setSpacing(0)

        # ── Título ──
        t = _lbl("Preparar el caso", bold=True, size=24)
        t.setStyleSheet(f"color: {_C['ink']}; font-size: 24px; font-weight: 700;")
        root.addWidget(t)
        root.addSpacing(6)
        root.addWidget(_lbl(
            "Seleccione la materia y el expediente. Revise las ranuras de documentos "
            "— puede agregar archivos directamente desde aquí.",
            color=_C["ink2"], size=13,
        ))
        root.addSpacing(20)

        # ── Fila superior: materia + caso ──
        top_row = QWidget()
        top_lay = QHBoxLayout(top_row)
        top_lay.setContentsMargins(0, 0, 0, 0)
        top_lay.setSpacing(16)

        # Materia
        mat_w = QWidget()
        mat_l = QVBoxLayout(mat_w)
        mat_l.setContentsMargins(0, 0, 0, 0)
        mat_l.setSpacing(6)
        mat_l.addWidget(_section_label("Materia"))
        self._cmb_materia = QComboBox()
        self._cmb_materia.setStyleSheet(_INPUT_SS + "QComboBox { padding: 10px 14px; }")
        _default_idx = 0
        for i, slug in enumerate(sorted(MATERIA_SLUGS)):
            label = MATERIA_LABELS.get(slug, slug)
            self._cmb_materia.addItem(label, userData=slug)
            if slug == "prision_preventiva":
                _default_idx = i
        self._cmb_materia.setCurrentIndex(_default_idx)
        self._cmb_materia.currentIndexChanged.connect(self._on_materia_changed)
        mat_l.addWidget(self._cmb_materia)
        top_lay.addWidget(mat_w, 2)

        # Caso
        caso_w = QWidget()
        caso_l = QVBoxLayout(caso_w)
        caso_l.setContentsMargins(0, 0, 0, 0)
        caso_l.setSpacing(6)
        caso_header = QWidget()
        ch_lay = QHBoxLayout(caso_header)
        ch_lay.setContentsMargins(0, 0, 0, 0)
        ch_lay.setSpacing(8)
        ch_lay.addWidget(_section_label("Caso"))
        ch_lay.addStretch()
        self._btn_nuevo_caso = QPushButton("＋")
        self._btn_nuevo_caso.setToolTip("Crear nuevo caso")
        self._btn_nuevo_caso.setStyleSheet(_BTN_SMALL_GHOST)
        self._btn_nuevo_caso.setFixedWidth(36)
        self._btn_nuevo_caso.clicked.connect(self._on_nuevo_caso)
        ch_lay.addWidget(self._btn_nuevo_caso)
        self._btn_refresh = QPushButton("↻")
        self._btn_refresh.setToolTip("Actualizar lista de casos")
        self._btn_refresh.setStyleSheet(_BTN_SMALL_GHOST)
        self._btn_refresh.setFixedWidth(36)
        self._btn_refresh.clicked.connect(self._refresh_casos)
        ch_lay.addWidget(self._btn_refresh)
        caso_l.addWidget(caso_header)
        self._cmb_caso = QComboBox()
        self._cmb_caso.setStyleSheet(_INPUT_SS + "QComboBox { padding: 10px 14px; }")
        self._cmb_caso.currentIndexChanged.connect(self._on_caso_changed)
        caso_l.addWidget(self._cmb_caso)
        top_lay.addWidget(caso_w, 3)

        root.addWidget(top_row)
        root.addSpacing(16)

        # ── Panel de ranuras del expediente (la evolución principal) ──
        slots_header = QWidget()
        sh_lay = QHBoxLayout(slots_header)
        sh_lay.setContentsMargins(0, 0, 0, 0)
        sh_lay.setSpacing(8)
        sh_lay.addWidget(_section_label("Documentos del expediente"))
        sh_lay.addStretch()
        self._slots_summary = _lbl("", color=_C["faint"], size=11)
        sh_lay.addWidget(self._slots_summary)
        root.addWidget(slots_header)
        root.addSpacing(8)

        # Grid 2×3 de tarjetas de ranura
        slots_grid = QWidget()
        sg = QGridLayout(slots_grid)
        sg.setContentsMargins(0, 0, 0, 0)
        sg.setSpacing(8)

        # Etiquetas default — se actualizan cuando cambia la materia
        default_labels = {
            "solicitud_inicial": "Solicitud / requerimiento",
            "resolucion_apelada": "Resolución apelada",
            "recurso_apelacion": "Recurso de apelación",
            "anexos": "Anexos / pruebas",
            "audio": "Audio de audiencia",
            "otros": "Otros",
        }
        for idx, slot_key in enumerate(SLOT_KEYS):
            card = _SlotCard(slot_key, default_labels.get(slot_key, slot_key))
            card.files_changed.connect(self._update_slots_summary)
            self._slot_cards[slot_key] = card
            row = idx // 3
            col = idx % 3
            sg.addWidget(card, row, col)

        root.addWidget(slots_grid)
        root.addSpacing(16)

        # ── Fila central: datos del expediente (grid 2×3) + postura ──
        mid_row = QWidget()
        mid_lay = QHBoxLayout(mid_row)
        mid_lay.setContentsMargins(0, 0, 0, 0)
        mid_lay.setSpacing(20)

        # Datos
        datos_w = QWidget()
        datos_l = QVBoxLayout(datos_w)
        datos_l.setContentsMargins(0, 0, 0, 0)
        datos_l.setSpacing(6)
        datos_l.addWidget(_section_label("Datos del expediente"))

        def _inp(ph: str) -> QLineEdit:
            w = QLineEdit()
            w.setPlaceholderText(ph)
            w.setStyleSheet(_INPUT_SS)
            return w

        self._exp = _inp("Expediente Nº")
        self._imp = _inp("Imputado(s)")
        self._del = _inp("Delito imputado")
        self._agr = _inp("Agraviado")
        self._juz = _inp("Juzgado de origen")

        grid_w = QWidget()
        grid = QGridLayout(grid_w)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(8)
        grid.addWidget(self._exp, 0, 0)
        grid.addWidget(self._imp, 0, 1)
        grid.addWidget(self._del, 1, 0)
        grid.addWidget(self._agr, 1, 1)
        grid.addWidget(self._juz, 2, 0, 1, 2)
        datos_l.addWidget(grid_w)

        self._AUTOCOMPLETAR_TXT = "✨  Autocompletar datos desde los documentos"
        self._btn_autocompletar = QPushButton(self._AUTOCOMPLETAR_TXT)
        self._btn_autocompletar.setStyleSheet(_BTN_GHOST)
        self._btn_autocompletar.setToolTip(
            "Lee las primeras páginas de los documentos del caso y propone\n"
            "Expediente Nº, imputados, delito, agraviado y juzgado.\n"
            "El juez revisa y corrige lo que haga falta."
        )
        self._btn_autocompletar.clicked.connect(self._on_autocompletar)
        datos_l.addWidget(self._btn_autocompletar)

        mid_lay.addWidget(datos_w, 3)

        # Postura + instrucción + fuentes (columna derecha compacta)
        right_w = QWidget()
        right_l = QVBoxLayout(right_w)
        right_l.setContentsMargins(0, 0, 0, 0)
        right_l.setSpacing(10)

        right_l.addWidget(_section_label("Postura"))
        self._cmb_postura = QComboBox()
        self._cmb_postura.setStyleSheet(_INPUT_SS + "QComboBox { padding: 10px 14px; }")
        self._cmb_postura.addItem("CONFIRMAR",            userData="confirmar")
        self._cmb_postura.addItem("REVOCAR",              userData="revocar")
        self._cmb_postura.addItem("REVOCAR PARCIALMENTE", userData="revocar_parcial")
        right_l.addWidget(self._cmb_postura)

        right_l.addWidget(_section_label("Plantilla (formato del acto)"))
        plantilla_row = QWidget()
        plantilla_row.setStyleSheet("border: none;")
        plantilla_lay = QHBoxLayout(plantilla_row)
        plantilla_lay.setContentsMargins(0, 0, 0, 0)
        plantilla_lay.setSpacing(6)
        self._cmb_plantilla = QComboBox()
        self._cmb_plantilla.setStyleSheet(_INPUT_SS + "QComboBox { padding: 10px 14px; }")
        self._cmb_plantilla.setToolTip(
            "Modelo de resolución que define formato, acápites y esquema.\n"
            "Se carga de 01_raw/plantillas/<materia>/. El acto seguirá su estructura.\n"
            "Por defecto se usa la primera plantilla de la materia."
        )
        plantilla_lay.addWidget(self._cmb_plantilla, 1)
        self._btn_add_plantilla = QPushButton("＋")
        self._btn_add_plantilla.setToolTip(
            "Subir nueva plantilla (.docx/.md) para esta materia.\n"
            "Aparecerá en el selector de arriba al instante."
        )
        self._btn_add_plantilla.setFixedSize(36, 36)
        self._btn_add_plantilla.setStyleSheet(
            f"QPushButton {{ background: {_C['panel2']}; color: {_C['teal_d']}; "
            f"border: 1px solid {_C['hair']}; border-radius: 9px; "
            f"font-size: 18px; font-weight: 700; padding: 0; }}"
            f"QPushButton:hover {{ background: {_C['teal_s']}; border-color: {_C['teal']}; }}"
        )
        self._btn_add_plantilla.clicked.connect(self._on_add_plantilla)
        plantilla_lay.addWidget(self._btn_add_plantilla)
        right_l.addWidget(plantilla_row)

        right_l.addWidget(_section_label("Bibliografía adicional"))
        bib_w = QWidget()
        bib_w.setStyleSheet("border: none;")
        bib_l = QVBoxLayout(bib_w)
        bib_l.setContentsMargins(0, 0, 0, 0)
        bib_l.setSpacing(4)
        self._btn_add_bib = QPushButton("📚  Agregar bibliografía…")
        self._btn_add_bib.setStyleSheet(_BTN_GHOST)
        self._btn_add_bib.setToolTip(
            "Sube PDF/Word/Markdown a la bibliografía de esta materia.\n"
            "Se incluye automáticamente en la redacción (Bloque 5) de los casos de la materia.\n"
            "Equivale a la 'bibliografía por caso' del app anterior."
        )
        self._btn_add_bib.clicked.connect(self._on_add_bibliografia)
        bib_l.addWidget(self._btn_add_bib)
        self._bib_lbl = _lbl("…", color=_C["faint"], size=10)
        self._bib_lbl.setWordWrap(True)
        self._bib_lbl.setStyleSheet(f"color: {_C['faint']}; font-size: 10px; border: none;")
        bib_l.addWidget(self._bib_lbl)
        right_l.addWidget(bib_w)

        right_l.addWidget(_section_label("Instrucción particular"))
        self._instruccion = QPlainTextEdit()
        self._instruccion.setPlaceholderText("Notas del juez para este caso…")
        self._instruccion.setStyleSheet(
            _INPUT_SS + "QPlainTextEdit { min-height: 50px; max-height: 80px; }"
        )
        self._instruccion.setMaximumHeight(80)
        right_l.addWidget(self._instruccion)

        # Fuentes inline
        right_l.addWidget(_section_label("Fuentes"))
        src_row = QWidget()
        src_row.setStyleSheet(
            f"background: {_C['card']}; border: 1px solid {_C['hair']}; border-radius: 10px;"
        )
        src_lay = QHBoxLayout(src_row)
        src_lay.setContentsMargins(12, 8, 12, 8)
        src_lay.setSpacing(8)
        src_txt = _lbl("📚 RAG activo", bold=True, size=11)
        src_txt.setStyleSheet(f"color: {_C['sage']}; font-size: 11px; font-weight: 700; border: none;")
        src_lay.addWidget(src_txt)
        src_lay.addStretch()
        self._live_btn = QPushButton("🌐 En vivo")
        self._live_btn.setCheckable(True)
        self._live_btn.setToolTip("Buscar en LP Derecho, SPIJ, Gaceta Jurídica (Tavily)")
        self._live_btn.setStyleSheet(f"""
            QPushButton {{
                background: {_C['hair']}; color: {_C['ink2']};
                border: none; border-radius: 7px;
                padding: 4px 10px; font-size: 11px; font-weight: 600;
            }}
            QPushButton:checked {{ background: {_C['teal']}; color: #fff; }}
        """)
        self._live_btn.toggled.connect(lambda on: setattr(self, "_live_web", on))
        src_lay.addWidget(self._live_btn)
        right_l.addWidget(src_row)

        right_l.addStretch()
        mid_lay.addWidget(right_w, 2)

        root.addWidget(mid_row)
        root.addStretch()
        root.addSpacing(12)

        # ── Botones finales ──
        btn_row = QWidget()
        br = QHBoxLayout(btn_row)
        br.setContentsMargins(0, 0, 0, 0)
        br.setSpacing(12)

        self._btn_borrador = QPushButton("📂  Cargar borrador")
        self._btn_borrador.setStyleSheet(_BTN_GHOST)
        self._btn_borrador.setToolTip(
            "Cargar un borrador existente (.pdf, .docx, .doc, .md, .txt, .pages)\n"
            "y saltar directo al Control ③ — evita los ~18 minutos de E1-E3."
        )
        self._btn_borrador.clicked.connect(self._on_cargar_borrador)
        br.addWidget(self._btn_borrador)

        br.addStretch()

        self._btn_iniciar = QPushButton("Iniciar redacción  →")
        self._btn_iniciar.setStyleSheet(_BTN_PRIMARY)
        self._btn_iniciar.clicked.connect(self._on_iniciar)
        br.addWidget(self._btn_iniciar)

        root.addWidget(btn_row)

        # Poblar al inicio
        self._refresh_casos()

    # ── Lógica ───────────────────────────────────────────────────────────

    def _current_materia_slug(self) -> str:
        data = self._cmb_materia.currentData()
        return data if data else "prision_preventiva"

    def _current_caso_path(self) -> Path | None:
        data = self._cmb_caso.currentData()
        return Path(data) if data else None

    def _current_plantilla_path(self) -> str:
        return self._cmb_plantilla.currentData() or ""

    def _refresh_plantillas(self):
        """Lista las plantillas de la materia; usa la primera por defecto."""
        materia = self._current_materia_slug()
        self._cmb_plantilla.blockSignals(True)
        self._cmb_plantilla.clear()
        try:
            plantillas = list_plantillas(materia)
        except Exception:
            plantillas = []
        for p in plantillas:
            self._cmb_plantilla.addItem(p.name, userData=str(p))
        self._cmb_plantilla.addItem("— Sin plantilla —", userData="")
        # Por defecto, la primera plantilla disponible (índice 0) si existe.
        self._cmb_plantilla.setCurrentIndex(0)
        self._cmb_plantilla.blockSignals(False)

    def _refresh_bibliografia(self):
        """Muestra la bibliografía de la materia que se incluirá en la redacción."""
        materia = self._current_materia_slug()
        try:
            files = list_bibliografia(materia)
        except Exception:
            files = []
        if files:
            names = ", ".join(f.name for f in files[:3]) + ("…" if len(files) > 3 else "")
            self._bib_lbl.setText(f"{len(files)} archivo(s) de la materia · {names}")
        else:
            self._bib_lbl.setText("Sin bibliografía adicional para esta materia.")

    def _on_add_bibliografia(self):
        materia = self._current_materia_slug()
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Agregar bibliografía a la materia",
            str(BASE_DIR / "01_raw"),
            qt_open_filter(),
        )
        if not paths:
            return
        n = 0
        for p in paths:
            try:
                add_bibliografia(Path(p), materia=materia)
                n += 1
            except Exception:
                pass
        self._refresh_bibliografia()
        if n:
            self._btn_add_bib.setText(f"✓  {n} agregado(s) a la bibliografía")
            QTimer.singleShot(2500, lambda: self._btn_add_bib.setText("📚  Agregar bibliografía…"))

    def _on_add_plantilla(self):
        """Sube una nueva plantilla para la materia y la selecciona en el selector."""
        materia = self._current_materia_slug()
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Subir plantilla para esta materia",
            str(BASE_DIR / "01_raw"),
            qt_open_filter(),
        )
        if not paths:
            return
        n = 0
        for p in paths:
            try:
                add_plantilla(Path(p), materia=materia)
                n += 1
            except Exception:
                pass
        if n:
            self._refresh_plantillas()
            # Seleccionar la recién subida (la primera, que es la más reciente por nombre)
            self._btn_add_plantilla.setText("✓")
            QTimer.singleShot(2500, lambda: self._btn_add_plantilla.setText("＋"))

    def _on_materia_changed(self, _idx: int):
        self._refresh_casos()
        # Actualizar etiquetas de las ranuras según la materia
        materia = self._current_materia_slug()
        labels = slot_labels_for(materia)
        for key, card in self._slot_cards.items():
            card._title.setText(labels.get(key, key))

    def _on_caso_changed(self, _idx: int):
        self._refresh_slots()

    def _on_nuevo_caso(self):
        """Crea una carpeta de caso nueva y la selecciona en el combo."""
        materia = self._current_materia_slug()
        nombre, ok = QInputDialog.getText(
            self, "Nuevo caso",
            "Nombre del caso (ej: caso_021_robo_agravado):",
        )
        if not ok or not nombre.strip():
            return
        nombre = nombre.strip().replace(" ", "_")
        caso_dir = BASE_DIR / "01_raw" / materia / nombre / "fuentes"
        try:
            caso_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudo crear el caso:\n{e}")
            return
        self._refresh_casos(seleccionar=str(caso_dir.parent))

    # ── Autocompletado de datos del expediente ────────────────────────────
    def _autocompletar_reset(self, delay_ms: int = 4000):
        QTimer.singleShot(delay_ms, lambda: self._btn_autocompletar.setText(self._AUTOCOMPLETAR_TXT))

    def _on_autocompletar(self):
        caso = self._current_caso_path()
        if caso is None or not caso.exists():
            self._btn_autocompletar.setText("Selecciona un caso primero")
            self._autocompletar_reset(2500)
            return
        slots = read_fuentes_slots(caso)
        if not any(slots.values()):
            self._btn_autocompletar.setText("Este caso no tiene documentos")
            self._autocompletar_reset(2500)
            return
        labels = slot_labels_for(self._current_materia_slug())
        self._btn_autocompletar.setEnabled(False)
        self._btn_autocompletar.setText("⏳  Leyendo documentos y extrayendo datos…")
        self._meta_worker = _MetaWorker(slots, labels, parent=self)
        self._meta_worker.done.connect(self._on_meta_done)
        self._meta_worker.failed.connect(self._on_meta_failed)
        self._meta_worker.start()

    def _on_meta_done(self, data: dict):
        campos = {
            "expediente": self._exp, "imputados": self._imp, "delito": self._del,
            "agraviado": self._agr, "juzgado": self._juz,
        }
        n = 0
        for k, widget in campos.items():
            val = (data or {}).get(k, "")
            if val:
                widget.setText(val)
                n += 1
        self._btn_autocompletar.setEnabled(True)
        if n:
            self._btn_autocompletar.setText(f"✨  Autocompletado ({n}/5) — revise y corrija")
        else:
            self._btn_autocompletar.setText("No se pudieron extraer datos — complete a mano")
        self._autocompletar_reset()

    def _on_meta_failed(self, msg: str):
        self._btn_autocompletar.setEnabled(True)
        self._btn_autocompletar.setText(f"Error al autocompletar: {msg[:40]}")
        self._autocompletar_reset(4000)

    def _refresh_casos(self, seleccionar: str | None = None):
        materia = self._current_materia_slug()
        self._cmb_caso.blockSignals(True)
        self._cmb_caso.clear()
        # Primera opción: placeholder para nuevo caso
        self._cmb_caso.addItem("— Nuevo caso —", userData="")
        carpetas = list_case_folders(materia)
        for p in carpetas:
            self._cmb_caso.addItem(p.name, userData=str(p))
        # Seleccionar caso específico si se indica; si no, quedarse en "Nuevo caso"
        if seleccionar:
            for i in range(self._cmb_caso.count()):
                if self._cmb_caso.itemData(i) == seleccionar:
                    self._cmb_caso.setCurrentIndex(i)
                    break
        else:
            self._cmb_caso.setCurrentIndex(0)
        self._cmb_caso.blockSignals(False)
        # Actualizar etiquetas de las ranuras
        labels = slot_labels_for(materia)
        for key, card in self._slot_cards.items():
            card._title.setText(labels.get(key, key))
        self._refresh_plantillas()
        self._refresh_bibliografia()
        self._refresh_slots()

    def _refresh_slots(self):
        """Lee los archivos de cada ranura del caso seleccionado y actualiza las tarjetas.

        Usa la MISMA fuente que el pipeline (``read_fuentes_slots``: manifiesto de
        slots o, en su defecto, subcarpetas ``fuentes/<slot>/``), para que la UI
        muestre exactamente lo que la fábrica va a leer.
        """
        caso = self._current_caso_path()
        slots_map: dict = {}
        if caso and caso.exists():
            try:
                slots_map = read_fuentes_slots(caso)
            except Exception:
                slots_map = {}
        for key, card in self._slot_cards.items():
            card.set_caso_folder(caso)
            files = [f for f in slots_map.get(key, []) if f.is_file()]
            card.set_files(files)
        self._update_slots_summary()

    def _update_slots_summary(self):
        total = sum(len(c._files) for c in self._slot_cards.values())
        filled = sum(1 for c in self._slot_cards.values() if c._files)
        if total == 0:
            self._slots_summary.setText("Sin documentos cargados")
            self._slots_summary.setStyleSheet(f"color: {_C['alert']}; font-size: 11px;")
        else:
            self._slots_summary.setText(
                f"{total} archivo(s) en {filled} de {len(SLOT_KEYS)} ranuras"
            )
            self._slots_summary.setStyleSheet(f"color: {_C['teal_d']}; font-size: 11px;")

    def _on_cargar_borrador(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Cargar borrador",
            str(BASE_DIR / "03_outputs" / "resoluciones"),
            qt_open_filter(),
        )
        if path:
            self.cargar_borrador.emit(path)

    def _on_iniciar(self):
        caso_path = self._cmb_caso.currentData() or ""
        materia   = self._current_materia_slug()
        postura   = self._cmb_postura.currentData() or "confirmar"

        self.iniciar.emit({
            "materia":                materia,
            "caso_path":              caso_path,
            "plantilla_path":         self._current_plantilla_path(),
            "expediente":             self._exp.text().strip(),
            "imputados":              self._imp.text().strip(),
            "delito":                 self._del.text().strip(),
            "agraviado":              self._agr.text().strip(),
            "juzgado":                self._juz.text().strip(),
            "postura":                postura,
            "instruccion_particular": self._instruccion.toPlainText().strip(),
            "use_live_web":           self._live_web,
        })


# ── Pantalla 1: Checkpoint ① hechos ──────────────────────────────────────────

class _HechosScreen(QWidget):
    confirmar = pyqtSignal(str)   # texto aprobado / editado
    volver    = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background: {_C['paper']};")
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 22, 28, 28)
        root.setSpacing(16)

        badge = _lbl("★  Control del juez ①", bold=True, size=12, color=_C["gold_d"])
        badge.setStyleSheet(
            f"color: {_C['gold_d']}; background: {_C['gold_s']}; "
            f"border: 1px solid {_C['gold']}; border-radius: 8px; "
            f"padding: 4px 12px; font-size: 12px; font-weight: 700;"
        )
        root.addWidget(badge)

        root.addWidget(_lbl("Confirmar los hechos", bold=True, size=22))
        root.addWidget(_lbl(
            "El sistema leyó los documentos y resumió los hechos y agravios. "
            "Revise y corrija lo que haga falta — todo lo que viene se construye sobre esto.",
            color=_C["ink2"],
        ))

        root.addWidget(_lbl("Hechos y agravios — editable", bold=True, size=13, color=_C["teal_d"]))
        self._editor = QPlainTextEdit()
        self._editor.setStyleSheet(_INPUT_SS + f"QPlainTextEdit {{ min-height: 220px; }}")
        self._editor.setPlaceholderText("El sistema llenará este campo automáticamente…")
        root.addWidget(self._editor, 1)

        root.addWidget(_lbl(
            "✎  Edite el texto directamente. Su versión corregida es la que avanza.",
            color=_C["faint"], size=11,
        ))

        btn_row = QWidget()
        br = QHBoxLayout(btn_row)
        br.setContentsMargins(0, 0, 0, 0)
        volver_btn = QPushButton("←  Volver")
        volver_btn.setStyleSheet(_BTN_GHOST)
        volver_btn.clicked.connect(self.volver)
        br.addWidget(volver_btn)
        br.addStretch()
        cont_btn = QPushButton("Confirmar y continuar  →")
        cont_btn.setStyleSheet(_BTN_GOLD)
        cont_btn.clicked.connect(lambda: self.confirmar.emit(self._editor.toPlainText()))
        br.addWidget(cont_btn)
        root.addWidget(btn_row)

    def set_texto(self, texto: str):
        self._editor.setPlainText(texto)


# ── Pantalla 2: Checkpoint ② fuentes ─────────────────────────────────────────

class _FuentesScreen(QWidget):
    aprobar = pyqtSignal(str)   # texto final de fuentes (solo las marcadas)
    volver  = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background: {_C['paper']};")
        self._checks: list[tuple[QCheckBox, str]] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 22, 28, 28)
        root.setSpacing(16)

        badge = _lbl("★  Control del juez ②", bold=True, size=12, color=_C["gold_d"])
        badge.setStyleSheet(
            f"color: {_C['gold_d']}; background: {_C['gold_s']}; "
            f"border: 1px solid {_C['gold']}; border-radius: 8px; "
            f"padding: 4px 12px; font-size: 12px; font-weight: 700;"
        )
        root.addWidget(badge)

        root.addWidget(_lbl("Revisar las fuentes", bold=True, size=22))
        root.addWidget(_lbl(
            "Estos son los fundamentos que la fábrica usará para redactar. "
            "Quite lo que no corresponda. Cada fuente indica de dónde salió.",
            color=_C["ink2"],
        ))

        self._list_container = QWidget()
        self._list_container.setStyleSheet("background: transparent;")
        self._list_lay = QVBoxLayout(self._list_container)
        self._list_lay.setContentsMargins(0, 0, 0, 0)
        self._list_lay.setSpacing(8)

        scroll = _scroll(self._list_container)
        root.addWidget(scroll, 1)

        btn_row = QWidget()
        br = QHBoxLayout(btn_row)
        br.setContentsMargins(0, 0, 0, 0)
        volver_btn = QPushButton("←  Volver")
        volver_btn.setStyleSheet(_BTN_GHOST)
        volver_btn.clicked.connect(self.volver)
        br.addWidget(volver_btn)
        br.addStretch()
        apr_btn = QPushButton("Aprobar fuentes y redactar  →")
        apr_btn.setStyleSheet(_BTN_GOLD)
        apr_btn.clicked.connect(self._on_aprobar)
        br.addWidget(apr_btn)
        root.addWidget(btn_row)

    def set_fuentes(self, texto: str):
        while self._list_lay.count():
            item = self._list_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._checks.clear()

        lineas = texto.strip().split("\n")
        items: list[tuple[str, bool]] = []
        buf = ""
        for linea in lineas:
            s = linea.strip()
            if not s:
                if buf:
                    items.append((buf.strip(), "[EN VIVO]" in buf))
                    buf = ""
            elif s.startswith(("•", "-", "*", "#", "##", "###")):
                if buf:
                    items.append((buf.strip(), "[EN VIVO]" in buf))
                buf = s.lstrip("•-*# ")
            else:
                buf = (buf + " " + s).strip() if buf else s
        if buf:
            items.append((buf.strip(), "[EN VIVO]" in buf))

        if not items:
            items = [(texto.strip(), False)]

        for text, is_live in items:
            if not text:
                continue
            row = QWidget()
            row.setStyleSheet(
                f"background: {_C['card']}; border: 1px solid {_C['hair']}; border-radius: 10px;"
            )
            rl = QHBoxLayout(row)
            rl.setContentsMargins(14, 10, 14, 10)
            rl.setSpacing(12)

            cb = QCheckBox()
            cb.setChecked(True)
            cb.setStyleSheet("QCheckBox::indicator { width: 20px; height: 20px; }")
            rl.addWidget(cb)

            txt_w = QWidget()
            tl = QVBoxLayout(txt_w)
            tl.setContentsMargins(0, 0, 0, 0)
            tl.setSpacing(2)
            display = text[:200] + "…" if len(text) > 200 else text
            tl.addWidget(_lbl(display, size=12))
            rl.addWidget(txt_w, 1)

            tag_color = _C["teal_d"] if is_live else _C["kraft"]
            tag_bg    = _C["teal_s"] if is_live else "#f0e2cc"
            tag_text  = "en vivo" if is_live else "biblioteca · RAG"
            tag = _lbl(f" {tag_text} ", size=10, color=tag_color)
            tag.setStyleSheet(
                f"background: {tag_bg}; color: {tag_color}; "
                f"border-radius: 5px; padding: 2px 6px; font-size: 10px;"
            )
            rl.addWidget(tag)

            self._list_lay.addWidget(row)
            self._checks.append((cb, text))

        self._list_lay.addStretch()

    def _on_aprobar(self):
        seleccionadas = [txt for cb, txt in self._checks if cb.isChecked()]
        resultado = "\n\n".join(seleccionadas) if seleccionadas else ""
        self.aprobar.emit(resultado)


# ── Reporte de pulido: diff exacto original vs. pulido (sin IA) ───────────────

def _diff_cambios(original: str, pulido: str) -> list[tuple[str, str, str]]:
    """Compara palabra por palabra original vs. pulido y devuelve los tramos que
    cambiaron como (tipo, antes, despues). Determinista: refleja exactamente lo
    que cambió, sin intervención de IA (cero riesgo de inventar correcciones)."""
    a = (original or "").split()
    b = (pulido or "").split()
    sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    cambios: list[tuple[str, str, str]] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        cambios.append((tag, " ".join(a[i1:i2]), " ".join(b[j1:j2])))
    return cambios


def _reporte_html(cambios: list[tuple[str, str, str]]) -> str:
    """Construye el HTML del reporte de cambios para mostrarlo en un QTextEdit."""
    from html import escape

    if not cambios:
        return (
            "<p style='color:#5b6b5e;'>No se detectaron diferencias entre el "
            "borrador original y el pulido.</p>"
        )
    filas = []
    for n, (tag, antes, despues) in enumerate(cambios, 1):
        if tag == "replace":
            cuerpo = (
                f"<span style='color:#9c4a3c;text-decoration:line-through;'>{escape(antes)}</span>"
                f" &nbsp;→&nbsp; "
                f"<span style='color:#2f6b4f;'>{escape(despues)}</span>"
            )
            etq = "Corrección"
        elif tag == "delete":
            cuerpo = f"<span style='color:#9c4a3c;text-decoration:line-through;'>{escape(antes)}</span>"
            etq = "Eliminado"
        else:  # insert
            cuerpo = f"<span style='color:#2f6b4f;'>{escape(despues)}</span>"
            etq = "Añadido"
        filas.append(
            f"<p style='margin:0 0 10px 0;'>"
            f"<b>{n}. {etq}</b><br>{cuerpo}</p>"
        )
    return "".join(filas)


# ── Pantalla 3: Checkpoint ③ borrador ────────────────────────────────────────

class _BorradorScreen(QWidget):
    aprobar = pyqtSignal(str)
    volver  = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background: {_C['paper']};")
        self._pulir_worker:   _PulirWorker   | None = None
        self._rewrite_worker: _RewriteWorker | None = None
        self._pulido_original: str = ""   # texto previo al pulido, para el reporte de cambios

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 22, 28, 28)
        root.setSpacing(14)

        badge = _lbl("★  Control del juez ③", bold=True, size=12, color=_C["gold_d"])
        badge.setStyleSheet(
            f"color: {_C['gold_d']}; background: {_C['gold_s']}; "
            f"border: 1px solid {_C['gold']}; border-radius: 8px; "
            f"padding: 4px 12px; font-size: 12px; font-weight: 700;"
        )
        root.addWidget(badge)

        root.addWidget(_lbl("Revisar el borrador", bold=True, size=22))

        self._verif_lbl = _lbl("", color=_C["teal_d"], size=12)
        self._verif_lbl.setStyleSheet(
            f"background: {_C['teal_s']}; border: 1px solid {_C['teal']}; "
            f"border-radius: 9px; padding: 8px 14px; color: {_C['teal_d']}; font-size: 12px;"
        )
        root.addWidget(self._verif_lbl)

        root.addWidget(_lbl(
            "Revise la resolución. Seleccione texto y pulse «Reescribir» para que la fábrica "
            "corrija solo esa parte sin tocar el resto.",
            color=_C["ink2"],
        ))

        self._editor = QPlainTextEdit()
        self._editor.setStyleSheet(
            _INPUT_SS + "QPlainTextEdit { min-height: 260px; font-size: 13px; }"
        )
        root.addWidget(self._editor, 1)

        tool_row = QWidget()
        tl = QHBoxLayout(tool_row)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(10)

        self._btn_rewrite = QPushButton("✏️  Reescribir selección")
        self._btn_rewrite.setStyleSheet(_BTN_GHOST)
        self._btn_rewrite.clicked.connect(self._on_rewrite)
        tl.addWidget(self._btn_rewrite)

        self._btn_pulir = QPushButton("✨  Pulir lenguaje")
        self._btn_pulir.setStyleSheet(_BTN_GHOST)
        self._btn_pulir.clicked.connect(self._on_pulir)
        tl.addWidget(self._btn_pulir)

        tl.addStretch()

        self._status_lbl = _lbl("", color=_C["faint"], size=11)
        tl.addWidget(self._status_lbl)

        root.addWidget(tool_row)

        btn_row = QWidget()
        br = QHBoxLayout(btn_row)
        br.setContentsMargins(0, 0, 0, 0)
        volver_btn = QPushButton("←  Volver")
        volver_btn.setStyleSheet(_BTN_GHOST)
        volver_btn.clicked.connect(self.volver)
        br.addWidget(volver_btn)
        br.addStretch()
        apr_btn = QPushButton("Aprobar y dar formato  →")
        apr_btn.setStyleSheet(_BTN_GOLD)
        apr_btn.clicked.connect(lambda: self.aprobar.emit(self._editor.toPlainText()))
        br.addWidget(apr_btn)
        root.addWidget(btn_row)

    def set_borrador(self, texto: str, citas_ok: bool | None = None, avisos: list[str] | None = None):
        self._editor.setPlainText(texto)
        if citas_ok is True:
            self._verif_lbl.setText("✓  Verificación de citas: OK — sin referencias inventadas.")
            self._verif_lbl.setStyleSheet(
                f"background: {_C['teal_s']}; border: 1px solid {_C['teal']}; "
                f"border-radius: 9px; padding: 8px 14px; color: {_C['teal_d']}; font-size: 12px;"
            )
        elif citas_ok is False:
            self._verif_lbl.setText("⚠  Hay citas con observaciones. Revise el borrador.")
            self._verif_lbl.setStyleSheet(
                f"background: #fdf0e4; border: 1px solid {_C['kraft']}; "
                f"border-radius: 9px; padding: 8px 14px; color: {_C['kraft']}; font-size: 12px;"
            )
        else:
            self._verif_lbl.setText("ℹ  Borrador listo para revisión.")
        n_avisos = len([a for a in (avisos or []) if "[E4]" in a])
        if n_avisos:
            self._verif_lbl.setText(self._verif_lbl.text() + f"  ({n_avisos} aviso(s) de E4)")

    def _set_status(self, msg: str, error=False):
        color = _C["alert"] if error else _C["faint"]
        self._status_lbl.setText(msg)
        self._status_lbl.setStyleSheet(f"color: {color}; font-size: 11px;")

    def _on_rewrite(self):
        cursor = self._editor.textCursor()
        fragmento = cursor.selectedText().strip()
        if not fragmento:
            self._set_status("Seleccione un fragmento de texto primero.", error=True)
            return

        instruccion, ok = QInputDialog.getText(
            self, "Reescribir selección",
            "¿Qué debe mejorar este fragmento? (instrucción para la fábrica):",
        )
        if not ok or not instruccion.strip():
            return

        borrador = self._editor.toPlainText()
        self._btn_rewrite.setEnabled(False)
        self._btn_pulir.setEnabled(False)
        self._btn_rewrite.setText("⏳  Reescribiendo…")
        self._set_status("Reescribiendo el fragmento seleccionado (~20s)…")

        self._rewrite_worker = _RewriteWorker(borrador, fragmento, instruccion, parent=self)
        self._rewrite_worker.done.connect(self._on_rewrite_done)
        self._rewrite_worker.error.connect(self._on_rewrite_error)
        self._rewrite_worker.start()

    def _on_rewrite_done(self, nuevo: str):
        cursor = self._editor.textCursor()
        if cursor.hasSelection():
            cursor.insertText(nuevo)
        else:
            cursor.movePosition(QTextCursor.MoveOperation.End)
            cursor.insertText("\n\n[REESCRITURA]:\n" + nuevo)
        self._btn_rewrite.setEnabled(True)
        self._btn_pulir.setEnabled(True)
        self._btn_rewrite.setText("✏️  Reescribir selección")
        self._set_status("✔ Fragmento reescrito. Revise y apruebe cuando esté listo.")

    def _on_rewrite_error(self, msg: str):
        self._btn_rewrite.setEnabled(True)
        self._btn_pulir.setEnabled(True)
        self._btn_rewrite.setText("✏️  Reescribir selección")
        self._set_status(f"Error al reescribir: {msg}", error=True)

    def _on_pulir(self):
        borrador = self._editor.toPlainText().strip()
        if not borrador:
            self._set_status("Nada que pulir — el editor está vacío.", error=True)
            return
        self._pulido_original = borrador
        self._btn_pulir.setEnabled(False)
        self._btn_rewrite.setEnabled(False)
        self._btn_pulir.setText("⏳  Puliendo…")
        self._set_status("Puliendo lenguaje (~30s)…")
        self._pulir_worker = _PulirWorker(borrador, parent=self)
        self._pulir_worker.done.connect(self._on_pulido_done)
        self._pulir_worker.error.connect(self._on_pulido_error)
        self._pulir_worker.start()

    def _on_pulido_done(self, texto: str):
        self._editor.setPlainText(texto)
        self._btn_pulir.setEnabled(True)
        self._btn_rewrite.setEnabled(True)
        self._btn_pulir.setText("✨  Pulir lenguaje")
        n = self._mostrar_reporte_pulido(self._pulido_original, texto)
        if n == 0:
            self._set_status("✔ Pulido: no se detectaron cambios de lenguaje.")
        else:
            self._set_status(f"✔ Lenguaje pulido — {n} cambio(s). Revise y apruebe.")

    def _mostrar_reporte_pulido(self, original: str, pulido: str) -> int:
        """Compara original vs. pulido (diff exacto, sin IA) y muestra un reporte
        de lo corregido en una ventana. Devuelve el número de cambios."""
        cambios = _diff_cambios(original, pulido)
        dlg = QDialog(self)
        dlg.setWindowTitle("Reporte de pulido de lenguaje")
        dlg.resize(720, 520)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(12)

        titulo = _lbl("✨  Reporte de pulido de lenguaje", bold=True, size=16)
        lay.addWidget(titulo)
        resumen = (
            "Sin cambios: el texto ya estaba pulido."
            if not cambios
            else f"Se realizaron {len(cambios)} corrección(es). Comparación exacta original → pulido:"
        )
        lay.addWidget(_lbl(resumen, color=_C["ink2"], size=12))

        vista = QTextEdit()
        vista.setReadOnly(True)
        vista.setHtml(_reporte_html(cambios))
        lay.addWidget(vista, 1)

        cerrar = QPushButton("Cerrar")
        cerrar.setStyleSheet(_BTN_GHOST)
        cerrar.clicked.connect(dlg.accept)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(cerrar)
        lay.addLayout(row)

        dlg.exec()
        return len(cambios)

    def _on_pulido_error(self, msg: str):
        self._btn_pulir.setEnabled(True)
        self._btn_rewrite.setEnabled(True)
        self._btn_pulir.setText("✨  Pulir lenguaje")
        self._set_status(f"Error en pulido: {msg}", error=True)


# ── Pantalla 4: Resolución final ──────────────────────────────────────────────

class _FinalScreen(QWidget):
    reiniciar = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background: {_C['paper']};")
        self._docx_path: str = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 22, 28, 28)
        root.setSpacing(16)

        badge = _lbl("✓  Resolución lista", bold=True, size=12, color=_C["sage"])
        badge.setStyleSheet(
            f"color: {_C['sage']}; background: #eaf5ed; "
            f"border: 1px solid {_C['sage']}; border-radius: 8px; "
            f"padding: 4px 12px; font-size: 12px; font-weight: 700;"
        )
        root.addWidget(badge)

        root.addWidget(_lbl("Resolución final", bold=True, size=22))
        root.addWidget(_lbl(
            "La plantilla aplicó el formato oficial — tipografía, sangrías y encabezado. "
            "Lista para su revisión final y firma.",
            color=_C["ink2"],
        ))

        self._docx_lbl = _lbl("", color=_C["faint"], size=12)
        root.addWidget(self._docx_lbl)

        preview_card = QWidget()
        preview_card.setStyleSheet(
            f"background: {_C['card']}; border: 1px solid {_C['hair']}; "
            f"border-radius: 12px; padding: 20px;"
        )
        pl = QVBoxLayout(preview_card)
        pl.setSpacing(8)

        header_lbl = _lbl("⚖  PODER JUDICIAL", bold=True, size=16, color=_C["gold_d"])
        header_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_lbl.setStyleSheet(
            f"color: {_C['gold_d']}; font-size: 16px; font-weight: 700;"
        )
        pl.addWidget(header_lbl)

        self._exp_lbl = _lbl("", color=_C["ink2"], size=12)
        self._exp_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pl.addWidget(self._exp_lbl)

        pl.addWidget(_sep())

        self._preview_txt = _lbl(
            "El documento se generó correctamente. Ábralo con el botón de abajo.",
            color=_C["ink2"],
        )
        pl.addWidget(self._preview_txt)

        root.addWidget(preview_card, 1)

        btn_row = QWidget()
        br = QHBoxLayout(btn_row)
        br.setContentsMargins(0, 0, 0, 0)
        br.setSpacing(12)

        reiniciar_btn = QPushButton("↺  Nuevo caso")
        reiniciar_btn.setStyleSheet(_BTN_GHOST)
        reiniciar_btn.clicked.connect(self.reiniciar)
        br.addWidget(reiniciar_btn)

        br.addStretch()

        self._btn_abrir = QPushButton("📂  Abrir carpeta")
        self._btn_abrir.setStyleSheet(_BTN_GHOST)
        self._btn_abrir.clicked.connect(self._abrir_carpeta)
        self._btn_abrir.setEnabled(False)
        br.addWidget(self._btn_abrir)

        self._btn_dl = QPushButton("⬇  Abrir .docx")
        self._btn_dl.setStyleSheet(_BTN_PRIMARY)
        self._btn_dl.clicked.connect(self._abrir_docx)
        self._btn_dl.setEnabled(False)
        br.addWidget(self._btn_dl)

        root.addWidget(btn_row)

    def set_docx(self, path: str, expediente: str = ""):
        self._docx_path = path
        if path:
            p = Path(path)
            self._docx_lbl.setText(f"Archivo generado: {p.name}")
            self._docx_lbl.setStyleSheet(f"color: {_C['teal_d']}; font-size: 12px;")
            self._btn_dl.setEnabled(True)
            self._btn_abrir.setEnabled(True)
        if expediente:
            self._exp_lbl.setText(f"Expediente N.° {expediente}")

    def _abrir_docx(self):
        if self._docx_path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self._docx_path))

    def _abrir_carpeta(self):
        if self._docx_path:
            QDesktopServices.openUrl(
                QUrl.fromLocalFile(str(Path(self._docx_path).parent))
            )


# ── Ventana principal de la Fábrica ──────────────────────────────────────────

class FabricaWidget(QWidget):
    """Widget principal que contiene stepper + pantallas apiladas."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background: {_C['paper']};")

        self._graph          = None
        self._graph_conn     = None
        self._thread_id      = None
        self._worker: _ArtifexWorker | None = None
        self._current_cfg: dict = {}
        self._expediente     = ""
        self._shortcut_state = None   # CasoState snapshot para modo "cargar borrador"
        self._review_mode    = False  # True tras generar la resolución: stepper navegable, sin re-disparar el grafo

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Top bar ──
        top = QWidget()
        top.setStyleSheet(
            f"background: {_C['panel2']}; border-bottom: 1px solid {_C['hair']};"
        )
        top_lay = QHBoxLayout(top)
        top_lay.setContentsMargins(22, 12, 22, 12)

        brand = _lbl("⚖  Redactor de Resoluciones", bold=True, size=16)
        brand.setStyleSheet(f"color: {_C['ink']}; font-size: 16px; font-weight: 700;")
        top_lay.addWidget(brand)
        top_lay.addStretch()

        self._btn_revisar = QPushButton("📋  Revisar resolución")
        self._btn_revisar.setStyleSheet(_BTN_GHOST)
        self._btn_revisar.setToolTip("Analiza y corrige un borrador de resolución usando el wiki y bibliografía del magistrado.")
        self._btn_revisar.clicked.connect(self._abrir_revision)
        top_lay.addWidget(self._btn_revisar)
        top_lay.addSpacing(8)

        self._btn_wiki = QPushButton("🔍  Consultar wiki")
        self._btn_wiki.setStyleSheet(_BTN_GHOST)
        self._btn_wiki.setToolTip("Abre el chat de consulta al wiki (02_wiki/) en una ventana aparte.")
        self._btn_wiki.clicked.connect(self._abrir_consultar_wiki)
        top_lay.addWidget(self._btn_wiki)
        top_lay.addSpacing(8)

        self._btn_restart = QPushButton("🔄")
        self._btn_restart.setToolTip("Reiniciar la app (recarga todos los cambios sin cerrar manualmente)")
        self._btn_restart.setStyleSheet(_BTN_SMALL_GHOST)
        self._btn_restart.setFixedWidth(36)
        self._btn_restart.clicked.connect(self._reiniciar_app)
        top_lay.addWidget(self._btn_restart)
        top_lay.addSpacing(12)

        self._status_bar = _lbl("Lista para iniciar.", color=_C["faint"], size=11)
        top_lay.addWidget(self._status_bar)

        root.addWidget(top)
        self._wiki_dlg: QDialog | None = None

        # ── Stepper ──
        stepper = QWidget()
        stepper.setStyleSheet(
            f"background: {_C['panel2']}; border-bottom: 1px solid {_C['hair']};"
        )
        sl = QHBoxLayout(stepper)
        sl.setContentsMargins(16, 10, 16, 10)
        sl.setSpacing(8)

        self._steps: list[QPushButton] = []
        step_defs = [
            ("1", "El caso",    False),
            ("★", "Hechos ①",   True),
            ("★", "Fuentes ②",  True),
            ("★", "Borrador ③", True),
            ("✓", "Resolución", False),
        ]
        for i, (num, label, _is_chk) in enumerate(step_defs):
            btn = QPushButton(f"  {num}  {label}")
            btn.setStyleSheet(_STEP_BASE)
            btn.setCheckable(False)
            btn.setEnabled(False)
            btn.clicked.connect(lambda _=False, idx=i: self._on_step_clicked(idx))
            sl.addWidget(btn)
            self._steps.append(btn)

        root.addWidget(stepper)

        # ── Pantallas ──
        self._stack = QStackedWidget()
        self._stack.setStyleSheet(f"background: {_C['paper']};")

        self._setup    = _SetupScreen()
        self._hechos   = _HechosScreen()
        self._fuentes  = _FuentesScreen()
        self._borrador = _BorradorScreen()
        self._final    = _FinalScreen()

        for s in (self._setup, self._hechos, self._fuentes, self._borrador, self._final):
            wrap = _scroll(s)
            self._stack.addWidget(wrap)

        root.addWidget(self._stack, 1)

        # ── Señales ──
        self._setup.iniciar.connect(self._on_iniciar)
        self._setup.cargar_borrador.connect(self._on_cargar_borrador)
        self._hechos.confirmar.connect(self._on_hechos_confirmados)
        self._hechos.volver.connect(lambda: self._go(0))
        self._fuentes.aprobar.connect(self._on_fuentes_aprobadas)
        self._fuentes.volver.connect(lambda: self._go(1))
        self._borrador.aprobar.connect(self._on_borrador_aprobado)
        self._borrador.volver.connect(lambda: self._go(2))
        self._final.reiniciar.connect(self._on_reiniciar)

        self._go(0)

    # ── Navegación ────────────────────────────────────────────────────────

    def _go(self, idx: int):
        self._stack.setCurrentIndex(idx)
        for i, btn in enumerate(self._steps):
            is_active = (i == idx)
            is_chk    = (i in (1, 2, 3))
            if is_active and is_chk:
                btn.setStyleSheet(_STEP_CHK_ACTIVE)
            elif is_active:
                btn.setStyleSheet(_STEP_ACTIVE)
            else:
                btn.setStyleSheet(_STEP_BASE)

    def _on_step_clicked(self, idx: int):
        """Clic en un recuadro del stepper. Solo navega si está habilitado
        (modo revisión, tras generar la resolución)."""
        if self._steps[idx].isEnabled():
            self._go(idx)

    def _enable_review_nav(self):
        """Tras generar la resolución final, deja el stepper navegable para que
        el juez pueda revisar Caso, Hechos, Fuentes y Borrador con un clic."""
        self._review_mode = True
        for btn in self._steps:
            btn.setEnabled(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)

    def _set_status(self, msg: str):
        self._status_bar.setText(msg)

    def _abrir_revision(self):
        """Abre la ventana de revisión y corrección de borradores."""
        if not hasattr(self, "_revision_dlg") or self._revision_dlg is None:
            self._revision_dlg = _RevisionDialog()   # sin parent → ventana independiente
        self._revision_dlg.show()
        self._revision_dlg.raise_()
        self._revision_dlg.activateWindow()

    def _reiniciar_app(self):
        """Relanza la app desde cero sin cerrar manualmente la ventana."""
        import sys, subprocess
        from PyQt6.QtWidgets import QApplication
        subprocess.Popen([sys.executable, "-m", "app"],
                         cwd=str(BASE_DIR))
        QApplication.instance().quit()

    def _abrir_consultar_wiki(self):
        """Abre el chat de «Consultar wiki» en una ventana aparte.

        La ventana se oculta al cerrarla (no se destruye) para preservar
        el historial de la conversación. Al volver a hacer clic aparece
        con todo el contexto intacto.
        """
        if self._wiki_dlg is not None:
            # Ya existe — mostrar y traer al frente (aunque estuviera oculta)
            self._wiki_dlg.show()
            self._wiki_dlg.raise_()
            self._wiki_dlg.activateWindow()
            return
        try:
            from app.ui.main_window import WikiConsultaPage
        except Exception as exc:
            QMessageBox.critical(
                self, "Consultar wiki",
                f"No se pudo abrir el chat del wiki:\n{exc}",
            )
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("Consultar wiki — Adiutor Iudicis.2")
        dlg.resize(820, 640)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(WikiConsultaPage(dlg))
        self._wiki_dlg = dlg

        # Interceptar el cierre: ocultar en vez de destruir
        dlg.closeEvent = lambda event: (event.ignore(), dlg.hide())

        dlg.show()  # no modal: deja seguir trabajando en la resolución

    # ── Inicio del pipeline ───────────────────────────────────────────────

    def _on_iniciar(self, cfg: dict):
        from app.core.env_load import load_repo_dotenv
        load_repo_dotenv()

        materia   = cfg["materia"]
        caso_path = cfg.get("caso_path", "")
        self._expediente  = cfg.get("expediente", "")
        self._current_cfg = cfg

        if not caso_path:
            self._set_status("Selecciona un caso antes de iniciar.")
            return

        caso_folder = Path(caso_path)
        self._set_status("Iniciando fábrica…")
        self._go(1)
        self._hechos.set_texto("⏳  Procesando documentos…")

        try:
            from app.artifex.graph import compile_graph, make_config
            from app.artifex.state import CasoState, Postura
            from app.core.file_manager import (
                read_fuentes_slots,
                read_instruccion_general,
                slot_labels_for,
                materia_label as ml,
            )

            slots = read_fuentes_slots(caso_folder)

            postura_map = {
                "confirmar":       Postura.CONFIRMAR,
                "revocar":         Postura.REVOCAR,
                "revocar_parcial": Postura.REVOCAR_PARCIAL,
                "personalizado":   Postura.PERSONALIZADO,
            }
            postura = postura_map.get(cfg.get("postura", "confirmar"), Postura.CONFIRMAR)

            state = CasoState(
                materia=materia,
                materia_label=ml(materia),
                folder_name=caso_folder.name,
                caso_num=caso_folder.name.split("_")[1] if "_" in caso_folder.name else "",
                slots=slots,
                slot_labels=slot_labels_for(materia),
                postura=postura,
                plantilla_path=(Path(cfg["plantilla_path"]) if cfg.get("plantilla_path") else None),
                expediente=cfg.get("expediente", ""),
                imputados=cfg.get("imputados", ""),
                delito=cfg.get("delito", "") or ml(materia),
                agraviado=cfg.get("agraviado", "") or "El Estado",
                juzgado=cfg.get("juzgado", ""),
                instruccion_particular=cfg.get("instruccion_particular", ""),
                instruccion_general=read_instruccion_general(materia),
                use_live_web=cfg.get("use_live_web", False),
            )

            if self._graph is None:
                self._graph, self._graph_conn = compile_graph()

            self._thread_id = str(uuid.uuid4())
            config = make_config(self._thread_id)

            self._shortcut_state = None
            self._worker = _ArtifexWorker(self._graph, state, config, parent=self)
            self._worker.step_done.connect(self._on_step_done)
            self._worker.checkpoint_hit.connect(self._on_checkpoint_hit)
            self._worker.pipeline_done.connect(self._on_pipeline_done)
            self._worker.error_occurred.connect(self._on_error)
            self._worker.start()

        except Exception as exc:
            self._set_status(f"Error al iniciar: {exc}")
            self._hechos.set_texto(f"Error: {exc}")

    def _on_step_done(self, node: str):
        labels = {
            "resumen_hechos": "Resumiendo hechos…",
            "busqueda":       "Buscando fundamentos (RAG)…",
            "redaccion":      "Redactando resolución…",
            "verificacion":   "Verificando citas…",
            "formato":        "Generando .docx…",
        }
        if node in labels:
            self._set_status(labels[node])

    def _on_checkpoint_hit(self, data: dict):
        cp        = data.get("checkpoint", "")
        contenido = data.get("contenido", "")

        if cp == "hechos":
            self._hechos.set_texto(contenido)
            self._go(1)
            self._set_status("★ Checkpoint ① — revise los hechos.")
        elif cp == "fuentes":
            self._fuentes.set_fuentes(contenido)
            self._go(2)
            self._set_status("★ Checkpoint ② — revise las fuentes.")
        elif cp == "borrador":
            snap = self._graph.get_state(make_config_local(self._thread_id))
            citas_ok = None
            avisos   = []
            if snap:
                vals = snap.values
                if isinstance(vals, dict):
                    citas_ok = vals.get("citas_ok")
                    avisos   = vals.get("avisos", [])
                elif hasattr(vals, "citas_ok"):
                    citas_ok = vals.citas_ok
                    avisos   = getattr(vals, "avisos", [])
            self._borrador.set_borrador(contenido, citas_ok=citas_ok, avisos=avisos)
            self._go(3)
            self._set_status("★ Checkpoint ③ — revise el borrador.")
        else:
            self._set_status(f"Checkpoint desconocido: {cp}")

    def _on_pipeline_done(self, docx_path: str):
        self._final.set_docx(docx_path, expediente=self._expediente)
        self._go(4)
        self._enable_review_nav()
        self._set_status("✓ Resolución generada y lista.")

    def _on_error(self, msg: str):
        self._set_status(f"Error: {msg[:120]}")
        QMessageBox.critical(self, "Error en la fábrica", msg)

    # ── Cargar borrador existente (shortcut → checkpoint ③) ───────────────

    def _on_cargar_borrador(self, path: str):
        """Cargar borrador .md existente → salta directo a checkpoint ③."""
        from app.core.file_manager import read_instruccion_general, materia_label as ml

        borrador = Path(path).read_text(encoding="utf-8", errors="replace").strip()
        if not borrador:
            self._set_status("El archivo está vacío.")
            return

        cfg     = self._current_cfg
        materia = cfg.get("materia", "prision_preventiva")

        try:
            from app.artifex.state import CasoState, Postura, Etapa
            from app.artifex.nodes import node_verificacion

            postura_map = {
                "confirmar":       Postura.CONFIRMAR,
                "revocar":         Postura.REVOCAR,
                "revocar_parcial": Postura.REVOCAR_PARCIAL,
            }
            postura = postura_map.get(cfg.get("postura", "confirmar"), Postura.CONFIRMAR)

            caso_path   = cfg.get("caso_path", "")
            caso_folder = Path(caso_path) if caso_path else Path(".")

            state = CasoState(
                materia=materia,
                materia_label=ml(materia),
                folder_name=caso_folder.name,
                expediente=cfg.get("expediente", ""),
                imputados=cfg.get("imputados", ""),
                delito=cfg.get("delito", "") or ml(materia),
                agraviado=cfg.get("agraviado", "") or "El Estado",
                juzgado=cfg.get("juzgado", ""),
                postura=postura,
                instruccion_general=read_instruccion_general(materia),
                borrador=borrador,
                etapa=Etapa.VERIFICACION,
            )
            state = node_verificacion(state)
        except Exception as e:
            self._set_status(f"Error al cargar borrador: {e}")
            return

        avisos_e4 = [a for a in state.avisos if a.startswith("[E4]")]
        nota = ("\n\nAVISOS DE VALIDACION:\n" + "\n".join(avisos_e4)) if avisos_e4 else ""
        self._borrador.set_borrador(
            borrador + nota,
            citas_ok=state.citas_ok,
            avisos=state.avisos,
        )
        self._thread_id      = ""
        self._shortcut_state = state
        self._go(3)
        self._set_status(f"Borrador cargado: {Path(path).name}")

    # ── Resumir después de checkpoints ───────────────────────────────────

    def _resume(self, response: dict):
        from app.artifex.graph import make_config
        from langgraph.types import Command
        config = make_config(self._thread_id)
        self._worker = _ArtifexWorker(
            self._graph, Command(resume=response), config, parent=self
        )
        self._worker.step_done.connect(self._on_step_done)
        self._worker.checkpoint_hit.connect(self._on_checkpoint_hit)
        self._worker.pipeline_done.connect(self._on_pipeline_done)
        self._worker.error_occurred.connect(self._on_error)
        self._worker.start()

    def _on_hechos_confirmados(self, texto: str):
        if self._review_mode:           # solo revisión: no re-disparar el grafo terminado
            self._go(4)
            return
        self._set_status("⏳ Buscando fundamentos (RAG)… ~40 s. No cierres la ventana.")
        self._resume({"accion": "aprobar", "texto": texto})

    def _on_fuentes_aprobadas(self, texto: str):
        if self._review_mode:           # solo revisión: no re-disparar el grafo terminado
            self._go(4)
            return
        self._set_status("⏳ Redactando la resolución… 1-3 min. No cierres la ventana.")
        self._resume({"accion": "aprobar", "texto": texto})

    def _on_borrador_aprobado(self, texto: str):
        if self._review_mode:           # solo revisión: no re-disparar el grafo terminado
            self._go(4)
            return
        if self._shortcut_state is not None:
            self._shortcut_export(texto)
        else:
            self._set_status("⏳ Generando el .docx… No cierres la ventana.")
            self._resume({"accion": "aprobar", "texto": texto})

    def _shortcut_export(self, borrador: str):
        """Exporta .docx directamente sin pasar por el grafo (modo cargar borrador)."""
        from app.artifex.nodes import node_formato
        state = self._shortcut_state
        state.borrador = borrador
        try:
            state = node_formato(state)
            docx = state.documento_final or ""
            self._final.set_docx(docx, expediente=state.expediente)
            self._go(4)
            self._enable_review_nav()
            self._set_status("✓ Resolución generada.")
        except Exception as e:
            self._set_status(f"Error al exportar: {e}")

    def _on_reiniciar(self):
        self._thread_id      = None
        self._shortcut_state = None
        self._review_mode    = False
        for btn in self._steps:
            btn.setEnabled(False)
            btn.unsetCursor()
        self._set_status("Lista para iniciar.")
        self._go(0)

    def closeEvent(self, event):
        # Evita el abort de Qt ("QThread: Destroyed while thread is still
        # running"): si un worker sigue trabajando, esperamos a que termine el
        # paso actual antes de destruir la ventana.
        w = getattr(self, "_worker", None)
        if w is not None and w.isRunning():
            r = QMessageBox.question(
                self,
                "La fábrica está trabajando",
                "Hay un paso en proceso (resumen, búsqueda o redacción).\n\n"
                "Si sales ahora se esperará a que termine el paso actual "
                "para no interrumpirlo. ¿Salir de todos modos?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if r != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self._set_status("Esperando a que termine el paso actual antes de cerrar…")
            w.wait()  # bloquea hasta que run() retorne (no destruye el hilo en vuelo)
        if self._graph_conn:
            try:
                self._graph_conn.close()
            except Exception:
                pass
        super().closeEvent(event)


def make_config_local(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


# ═══════════════════════════════════════════════════════════════════════════════
# REVISAR Y CORREGIR RESOLUCIÓN — worker + diálogo
# ═══════════════════════════════════════════════════════════════════════════════

_REVISION_SYSTEM = (
    "Eres un experto procesalista penal peruano que actúa como asesor jurídico "
    "de la Sala Penal de Apelaciones de Chincha y Pisco. Tu tarea es revisar y "
    "mejorar proyectos de resoluciones judiciales. Trabajas con la jurisprudencia, "
    "conceptos y bibliografía del magistrado. Nunca inventas citas ni normas. "
    "Eres directo, técnico y preciso."
)

def _build_analisis_prompt(instruccion_bloque: str, wiki: str, borrador: str) -> str:
    return (
        "A continuación te proporciono:\n"
        "1. El WIKI DEL MAGISTRADO (jurisprudencia consolidada, conceptos y criterios propios de la Sala)\n"
        "2. La INSTRUCCIÓN GENERAL DE LA MATERIA (reglas de redacción y estructura)\n"
        "3. El BORRADOR DE RESOLUCIÓN a revisar\n\n"
        + instruccion_bloque + "\n"
        "══════════════════════════════════════════\n"
        "WIKI DEL MAGISTRADO\n"
        "══════════════════════════════════════════\n"
        + wiki + "\n\n"
        "══════════════════════════════════════════\n"
        "BORRADOR DE RESOLUCIÓN\n"
        "══════════════════════════════════════════\n"
        + borrador + "\n\n"
        "══════════════════════════════════════════\n"
        "TAREA — ANÁLISIS TÉCNICO-JURÍDICO\n"
        "══════════════════════════════════════════\n"
        "Realiza un análisis técnico-jurídico exhaustivo del borrador. Estructura tu análisis en:\n\n"
        "I. IDENTIFICACIÓN Y ESTRUCTURA — tipo de resolución, partes, materia, decisión.\n"
        "II. FORTALEZAS — qué está bien resuelto y por qué.\n"
        "III. OBSERVACIONES Y DEBILIDADES — errores de fondo, omisiones argumentales, errores formales, "
        "citas incorrectas o ausentes. Ordénalas por importancia.\n"
        "IV. VALORACIÓN GLOBAL — tabla resumen.\n"
        "V. CONCLUSIÓN — síntesis y prioridades de corrección.\n\n"
        "Sé específico: cita el párrafo o sección exacta que presenta el problema."
    )


def _build_correccion_prompt(instruccion_bloque: str, wiki: str,
                              borrador: str, analisis: str) -> str:
    return (
        "A continuación te proporciono:\n"
        "1. El WIKI DEL MAGISTRADO (jurisprudencia consolidada, conceptos y criterios propios de la Sala)\n"
        "2. La INSTRUCCIÓN GENERAL DE LA MATERIA (reglas de redacción y estructura)\n"
        "3. El BORRADOR ORIGINAL con sus debilidades\n"
        "4. El ANÁLISIS TÉCNICO-JURÍDICO ya realizado\n\n"
        + instruccion_bloque + "\n"
        "══════════════════════════════════════════\n"
        "WIKI DEL MAGISTRADO\n"
        "══════════════════════════════════════════\n"
        + wiki + "\n\n"
        "══════════════════════════════════════════\n"
        "BORRADOR ORIGINAL\n"
        "══════════════════════════════════════════\n"
        + borrador + "\n\n"
        "══════════════════════════════════════════\n"
        "ANÁLISIS TÉCNICO-JURÍDICO (ya realizado)\n"
        "══════════════════════════════════════════\n"
        + analisis + "\n\n"
        "══════════════════════════════════════════\n"
        "TAREA — EMITIR RESOLUCIÓN CORREGIDA\n"
        "══════════════════════════════════════════\n"
        "Aplica TODAS las correcciones identificadas en el análisis y redacta la resolución definitiva.\n"
        "Reglas de CONTENIDO:\n"
        "- Conserva íntegramente los fundamentos correctos — solo reescribe lo que tiene error u omisión.\n"
        "- Para cada debilidad identificada, incorpora la corrección correspondiente.\n"
        "- No reduzcas la extensión del texto; si algo faltaba, agrégalo.\n"
        "- Usa solo jurisprudencia que conste en el wiki o en el borrador original.\n"
        "\n"
        "Reglas de FORMATO (CRÍTICAS — el documento debe salir IDÉNTICO en su forma al borrador original):\n"
        "- Reproduce EXACTAMENTE el encabezado del borrador original tal como está escrito "
        "(PODER JUDICIAL, CORTE SUPERIOR…, el nombre EXACTO de la Sala, y el bloque "
        "EXPEDIENTE/IMPUTADO/DELITO/AGRAVIADO/MATERIA/PROCEDENCIA con sus dos puntos). No lo cambies, "
        "no lo resumas, no lo reordenes.\n"
        "- Mantén los títulos de sección con su MISMA forma: numeración romana seguida de punto "
        "(I., II., III.…), el título en mayúsculas y SU PUNTO FINAL si el original lo tiene "
        "(ej: «I. RESOLUCIÓN MATERIA DE APELACIÓN.»).\n"
        "- Conserva los subtítulos que el original pone en LÍNEA PROPIA "
        "(ej: «De la defensa técnica del imputado», «Del representante del Ministerio Público») "
        "como líneas independientes, NO los fusiones con el párrafo numerado siguiente.\n"
        "- Conserva el MISMO esquema de numeración de párrafos (4.1., 4.2., 6.1., 6.2.…).\n"
        "- Mantén una línea en blanco entre bloques igual que el original.\n"
        "- NO uses Markdown (nada de #, **, listas con guiones). Devuelve texto plano con el mismo "
        "formato visual del borrador original.\n"
        "- Devuelve ÚNICAMENTE el texto de la resolución corregida, sin explicaciones ni comentarios al margen."
    )


def _build_reescritura_prompt(resolucion: str, fragmento: str, instruccion: str) -> str:
    """Prompt para reescribir un fragmento específico de la resolución corregida."""
    return (
        "Eres un juez superior penal peruano. Se te entrega una resolución judicial completa "
        "y un fragmento específico de ella que debe ser reescrito según la instrucción indicada.\n\n"
        "INSTRUCCIÓN DE CORRECCIÓN:\n"
        + instruccion + "\n\n"
        "══════════════════════════════════════════\n"
        "FRAGMENTO A REESCRIBIR (devuelve SOLO el fragmento reescrito, nada más):\n"
        "══════════════════════════════════════════\n"
        + fragmento + "\n\n"
        "══════════════════════════════════════════\n"
        "CONTEXTO — RESOLUCIÓN COMPLETA (solo para referencia, NO devolver):\n"
        "══════════════════════════════════════════\n"
        + resolucion + "\n\n"
        "REGLAS ABSOLUTAS:\n"
        "1. Devuelve ÚNICAMENTE el fragmento reescrito — sin encabezados, sin explicaciones, "
        "sin comentarios al margen.\n"
        "2. Mantén el estilo, tono y nivel de formalidad judicial de la resolución completa.\n"
        "3. Aplica exactamente la instrucción de corrección indicada.\n"
        "4. No reduzcas la extensión — si la instrucción pide desarrollar, desarrolla en profundidad.\n"
        "5. No repitas el fragmento original; devuelve directamente la versión corregida.\n"
    )


class _RevisionWorker(QThread):
    """Worker que ejecuta análisis o corrección en segundo plano."""
    chunk = pyqtSignal(str)
    done  = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, prompt: str, parent=None):
        super().__init__(parent)
        self._prompt = prompt

    def run(self):
        import traceback, pathlib
        try:
            from app.core.claude_worker import resolution_model_candidates
            from app.core.wiki_worker import _get_client
            client = _get_client()
            model = resolution_model_candidates()[0]
            resp = client.messages.create(
                model=model,
                max_tokens=8192,
                system=_REVISION_SYSTEM,
                messages=[{"role": "user", "content": self._prompt}],
                timeout=600,
            )
            text = "".join(
                getattr(b, "text", "") for b in resp.content
            ).strip()
            self.done.emit(text)
        except Exception as exc:
            tb = traceback.format_exc()
            pathlib.Path("/tmp/artifex_revision.log").write_text(tb)
            self.error.emit(f"{exc}\n\nDetalle en /tmp/artifex_revision.log")


class _RevisionDialog(QDialog):
    """Ventana de revisión y corrección de borradores de resolución."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("📋 Revisar y corregir resolución — Artifex Iudicialis")
        self.resize(1000, 760)
        self._borrador_text: str = ""
        self._analisis_text: str = ""
        self._worker: _RevisionWorker | None = None
        self._rewrite_cursor = None

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        # ── Título ──
        titulo = _lbl("📋  Revisar y corregir resolución", bold=True, size=16)
        titulo.setStyleSheet(f"color: {_C['ink']}; font-weight: 700;")
        root.addWidget(titulo)

        subtitulo = _lbl(
            "Analiza un borrador usando el wiki y bibliografía del magistrado, "
            "luego emite la versión corregida en .docx.", color=_C["faint"], size=11
        )
        subtitulo.setWordWrap(True)
        root.addWidget(subtitulo)

        # ── Fila: cargar borrador ──
        carga_row = QHBoxLayout()
        self._lbl_archivo = _lbl("Sin archivo cargado", color=_C["faint"], size=12)
        self._lbl_archivo.setWordWrap(True)
        carga_row.addWidget(self._lbl_archivo, 1)
        btn_cargar = QPushButton("📂  Cargar borrador (.doc / .docx)")
        btn_cargar.setStyleSheet(_BTN_GHOST)
        btn_cargar.clicked.connect(self._on_cargar)
        carga_row.addWidget(btn_cargar)
        root.addLayout(carga_row)

        # ── Materia (para instrucción general y wiki) ──
        mat_row = QHBoxLayout()
        mat_row.addWidget(_lbl("Materia:", size=12))
        self._cmb_materia = QComboBox()
        self._cmb_materia.setStyleSheet(_INPUT_SS)
        for slug in sorted(MATERIA_SLUGS):
            label = MATERIA_LABELS.get(slug, slug.replace("_", " ").capitalize())
            self._cmb_materia.addItem(label, userData=slug)
        self._cmb_materia.currentIndexChanged.connect(self._on_materia_changed)
        mat_row.addWidget(self._cmb_materia, 1)
        root.addLayout(mat_row)

        self._inp_materia_custom = QLineEdit()
        self._inp_materia_custom.setPlaceholderText("Escribe la materia (ej: control de plazos, hábeas corpus…)")
        self._inp_materia_custom.setStyleSheet(_INPUT_SS)
        self._inp_materia_custom.setVisible(False)
        root.addWidget(self._inp_materia_custom)

        # ── Instrucción particular ──
        root.addWidget(_lbl("Instrucción particular (opcional):", size=12))
        self._inp_instruccion = QPlainTextEdit()
        self._inp_instruccion.setPlaceholderText(
            "Ej: enfócate en el plazo razonable y el cómputo del artículo 334.2 CPP"
        )
        self._inp_instruccion.setFixedHeight(60)
        self._inp_instruccion.setStyleSheet(_INPUT_SS)
        root.addWidget(self._inp_instruccion)

        # ── Botones de acción ──
        btn_row = QHBoxLayout()
        self._btn_analizar = QPushButton("🔍  Analizar")
        self._btn_analizar.setStyleSheet(_BTN_GHOST)
        self._btn_analizar.setEnabled(False)
        self._btn_analizar.clicked.connect(self._on_analizar)
        btn_row.addWidget(self._btn_analizar)

        self._btn_corregir = QPushButton("✅  Corregir y emitir .docx")
        self._btn_corregir.setStyleSheet(_BTN_SAGE)
        self._btn_corregir.setEnabled(False)
        self._btn_corregir.clicked.connect(self._on_corregir)
        btn_row.addWidget(self._btn_corregir)

        btn_row.addStretch()
        self._lbl_status = _lbl("", color=_C["faint"], size=11)
        btn_row.addWidget(self._lbl_status)
        root.addLayout(btn_row)

        # ── Área de resultado (análisis / resolución corregida) ──
        splitter = QSplitter(Qt.Orientation.Vertical)

        self._txt_analisis = QTextEdit()
        self._txt_analisis.setReadOnly(True)
        self._txt_analisis.setPlaceholderText("El análisis técnico-jurídico aparecerá aquí…")
        self._txt_analisis.setStyleSheet(
            f"background: {_C['card']}; border: 1px solid {_C['hair']}; "
            f"border-radius: 10px; padding: 12px; font-size: 13px;"
        )
        splitter.addWidget(self._txt_analisis)

        # ── Panel resolución corregida ──
        res_panel = QWidget()
        res_layout = QVBoxLayout(res_panel)
        res_layout.setContentsMargins(0, 8, 0, 0)
        res_layout.setSpacing(6)

        res_header = QHBoxLayout()
        res_header.addWidget(_lbl("Resolución corregida", bold=True, size=12))
        res_header.addStretch()
        btn_expandir = QPushButton("⛶  Expandir")
        btn_expandir.setStyleSheet(_BTN_SMALL_GHOST)
        btn_expandir.setToolTip("Ver la resolución en ventana grande")
        btn_expandir.clicked.connect(self._on_expandir)
        res_header.addWidget(btn_expandir)
        btn_guardar_docx = QPushButton("💾  Guardar .docx")
        btn_guardar_docx.setStyleSheet(_BTN_SMALL_GHOST)
        btn_guardar_docx.clicked.connect(lambda: self._exportar_docx(self._txt_resultado.toPlainText()))
        res_header.addWidget(btn_guardar_docx)
        res_layout.addLayout(res_header)

        self._txt_resultado = QTextEdit()
        self._txt_resultado.setReadOnly(False)  # editable para correcciones manuales
        self._txt_resultado.setPlaceholderText("La resolución corregida aparecerá aquí… (editable)")
        self._txt_resultado.setStyleSheet(
            f"background: {_C['card']}; border: 1px solid {_C['hair']}; "
            f"border-radius: 10px; padding: 12px; font-size: 13px;"
        )
        res_layout.addWidget(self._txt_resultado, 1)

        # ── Bucle de corrección (igual al checkpoint ③) ──
        iter_frame = QFrame()
        iter_frame.setStyleSheet(
            f"background: {_C['panel2']}; border: 1px solid {_C['hair']}; border-radius: 10px;"
        )
        iter_lay = QVBoxLayout(iter_frame)
        iter_lay.setContentsMargins(12, 10, 12, 10)
        iter_lay.setSpacing(6)
        iter_lay.addWidget(_lbl("✏️  Reescribir selección", bold=True, size=12))
        iter_lay.addWidget(_lbl(
            "Selecciona un fragmento en el texto de arriba, escribe la instrucción y pulsa Reescribir.",
            color=_C["faint"], size=11
        ))
        self._inp_iter = QPlainTextEdit()
        self._inp_iter.setPlaceholderText(
            "Instrucción para reescribir el fragmento seleccionado…\n"
            "Ej: desarrolla más el análisis del plazo razonable con referencia al art. 8.1 CADH"
        )
        self._inp_iter.setFixedHeight(64)
        self._inp_iter.setStyleSheet(_INPUT_SS)
        iter_lay.addWidget(self._inp_iter)
        self._btn_reescribir = QPushButton("✏️  Reescribir selección")
        self._btn_reescribir.setStyleSheet(_BTN_GHOST)
        self._btn_reescribir.setEnabled(False)
        self._btn_reescribir.clicked.connect(self._on_reescribir)
        iter_lay.addWidget(self._btn_reescribir)
        res_layout.addWidget(iter_frame)

        splitter.addWidget(res_panel)
        splitter.setSizes([300, 450])
        root.addWidget(splitter, 1)

    # ── Handlers ──────────────────────────────────────────────────────────────

    def _cargar_archivo(self, path: str):
        """Carga un archivo y actualiza la UI. Reutilizable desde botón o auto-restauración."""
        try:
            from app.core.claude_worker import read_file_text
            text = read_file_text(Path(path))
            if not text.strip() or "[Error" in text[:80]:
                return False, text[:200]
            self._borrador_text = text
            self._ultimo_path = path
            nombre = Path(path).name
            self._lbl_archivo.setText(f"✓ {nombre}  ({len(text):,} chars)")
            self._lbl_archivo.setStyleSheet(f"color: {_C['teal']}; font-size: 12px;")
            self._btn_analizar.setEnabled(True)
            # Guardar ruta para restaurar en próxima apertura
            from PyQt6.QtCore import QSettings
            QSettings("ArtifexIudicialis", "RevisionDialog").setValue("ultimo_borrador", path)
            return True, ""
        except Exception as exc:
            return False, str(exc)

    def _on_cargar(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Cargar borrador de resolución", str(Path.home()),
            qt_open_filter()
        )
        if not path:
            return
        ok, err = self._cargar_archivo(path)
        if not ok:
            QMessageBox.warning(self, "Error de lectura",
                f"No se pudo extraer texto del archivo:\n{err}")
            return
        self._analisis_text = ""
        self._txt_analisis.clear()
        self._txt_resultado.clear()
        self._btn_corregir.setEnabled(False)

    def _restaurar_ultimo_archivo(self):
        """Al abrir la ventana, restaura el último archivo cargado si sigue existiendo."""
        from PyQt6.QtCore import QSettings
        path = QSettings("ArtifexIudicialis", "RevisionDialog").value("ultimo_borrador", "")
        if path and Path(path).exists() and not self._borrador_text:
            ok, _ = self._cargar_archivo(path)
            if ok:
                self._set_status(f"Archivo restaurado: {Path(path).name}")

    def _on_materia_changed(self, _idx: int):
        es_otros = (self._cmb_materia.currentData() or "") == "otros"
        self._inp_materia_custom.setVisible(es_otros)

    def _materia_slug(self) -> str:
        data = self._cmb_materia.currentData() or ""
        if data == "otros":
            custom = self._inp_materia_custom.text().strip()
            return custom.lower().replace(" ", "_") if custom else "otros"
        return data or "prision_preventiva"

    def _build_wiki_context(self) -> str:
        """Lee wiki consolidada + instrucción general de la materia seleccionada."""
        from app.artifex.nodes import _leer_wiki_consolidada
        wiki = _leer_wiki_consolidada()
        return wiki if wiki.strip() else "(wiki vacío — reconstruye el wiki desde la app)"

    def _instruccion_bloque(self) -> str:
        materia = self._materia_slug()
        # Solo leer instrucción general si la materia es una de las conocidas
        instruccion = ""
        try:
            instruccion = read_instruccion_general(materia)
        except (ValueError, Exception):
            pass  # materia custom — sin instrucción general preexistente
        particular = self._inp_instruccion.toPlainText().strip()
        bloque = ""
        if instruccion:
            bloque += (
                f"══════════════════════════════════════════\n"
                f"INSTRUCCIÓN GENERAL DE LA MATERIA\n"
                f"══════════════════════════════════════════\n{instruccion}\n"
            )
        if particular:
            bloque += (
                f"\n══════════════════════════════════════════\n"
                f"INSTRUCCIÓN PARTICULAR DEL MAGISTRADO\n"
                f"══════════════════════════════════════════\n{particular}\n"
            )
        return bloque

    def _on_analizar(self):
        if self._worker and self._worker.isRunning():
            return
        try:
            self._set_status("Construyendo contexto…")
            self._btn_analizar.setEnabled(False)
            self._btn_corregir.setEnabled(False)
            self._txt_analisis.setPlainText("⏳ Analizando el borrador con el wiki del magistrado…")

            instruccion = self._instruccion_bloque()
            wiki = self._build_wiki_context()
            prompt = _build_analisis_prompt(
                instruccion_bloque=instruccion,
                wiki=wiki,
                borrador=self._borrador_text,
            )
            self._set_status(f"Enviando a modelo ({len(prompt):,} chars)…")
            self._worker = _RevisionWorker(prompt)   # sin parent — evita problemas de ownership Qt
            self._worker.done.connect(self._on_analisis_done)
            self._worker.error.connect(self._on_error)
            self._worker.start()
        except Exception as exc:
            import traceback, pathlib
            tb = traceback.format_exc()
            pathlib.Path("/tmp/artifex_revision.log").write_text(tb)
            self._btn_analizar.setEnabled(True)
            self._set_status(f"Error: {exc}")
            QMessageBox.critical(self, "Error al preparar el análisis",
                f"{exc}\n\nDetalle en /tmp/artifex_revision.log")

    def _on_analisis_done(self, texto: str):
        self._analisis_text = texto
        self._txt_analisis.setMarkdown(texto)
        self._btn_analizar.setEnabled(True)
        self._btn_corregir.setEnabled(True)
        self._set_status("Análisis listo. Puedes corregir y emitir el .docx.")

    def _on_corregir(self):
        if self._worker and self._worker.isRunning():
            return
        if not self._analisis_text:
            QMessageBox.information(self, "Primero analiza",
                "Ejecuta primero el análisis antes de corregir.")
            return
        self._set_status("Generando resolución corregida…")
        self._btn_analizar.setEnabled(False)
        self._btn_corregir.setEnabled(False)
        self._txt_resultado.setPlainText("⏳ Emitiendo resolución corregida…")

        prompt = _build_correccion_prompt(
            instruccion_bloque=self._instruccion_bloque(),
            wiki=self._build_wiki_context(),
            borrador=self._borrador_text,
            analisis=self._analisis_text,
        )
        self._worker = _RevisionWorker(prompt)
        self._worker.done.connect(self._on_correccion_done)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_correccion_done(self, texto: str):
        self._txt_resultado.setPlainText(texto)
        self._btn_analizar.setEnabled(True)
        self._btn_corregir.setEnabled(True)
        self._btn_reescribir.setEnabled(True)
        self._set_status("Resolución corregida lista. Guardando .docx…")
        self._exportar_docx(texto)

    def _exportar_docx(self, texto: str):
        from app.core.word_export import text_to_docx_faithful
        from app.core.file_manager import BASE_DIR
        import datetime
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = BASE_DIR / "outputs" / "revisiones"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"resolucion_corregida_{ts}.docx"
        try:
            text_to_docx_faithful(texto, out_path)
            self._set_status(f"✓ Guardado en outputs/revisiones/{out_path.name}")
            QMessageBox.information(
                self, "Resolución exportada",
                f"Resolución corregida guardada en:\n{out_path}"
            )
        except Exception as exc:
            self._set_status(f"Error al exportar: {exc}")
            QMessageBox.critical(self, "Error al exportar .docx", str(exc))

    # ── Expandir resolución corregida ─────────────────────────────
    def _on_expandir(self):
        """Abre la resolución corregida en una ventana grande para revisión cómoda."""
        texto = self._txt_resultado.toPlainText()
        if not texto.strip():
            QMessageBox.information(
                self, "Sin contenido",
                "Primero genera la resolución corregida."
            )
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Resolución corregida — Vista expandida")
        dlg.resize(960, 780)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(8)
        txt = QTextEdit()
        txt.setPlainText(texto)
        txt.setReadOnly(True)
        txt.setStyleSheet(
            f"background: {_C['card']}; border: 1px solid {_C['hair']}; "
            f"border-radius: 8px; padding: 12px; font-size: 13px;"
        )
        lay.addWidget(txt, 1)
        btn_cerrar = QPushButton("Cerrar")
        btn_cerrar.setStyleSheet(_BTN_GHOST)
        btn_cerrar.clicked.connect(dlg.accept)
        lay.addWidget(btn_cerrar, alignment=Qt.AlignmentFlag.AlignRight)
        dlg.exec()

    # ── Bucle de corrección (igual al checkpoint ③) ───────────────
    def _on_reescribir(self):
        """Reescribe el fragmento seleccionado en _txt_resultado con la instrucción dada."""
        if self._worker and self._worker.isRunning():
            QMessageBox.information(
                self, "Ocupado",
                "Espera a que termine la operación en curso."
            )
            return
        cursor = self._txt_resultado.textCursor()
        seleccion = cursor.selectedText().strip()
        if not seleccion:
            QMessageBox.information(
                self, "Sin selección",
                "Selecciona el fragmento que quieres reescribir en el área de resolución corregida."
            )
            return
        instruccion = self._inp_iter.toPlainText().strip()
        if not instruccion:
            QMessageBox.information(
                self, "Sin instrucción",
                "Escribe la instrucción de corrección antes de reescribir."
            )
            return
        resolucion_completa = self._txt_resultado.toPlainText()
        prompt = _build_reescritura_prompt(resolucion_completa, seleccion, instruccion)
        self._rewrite_cursor = cursor
        self._set_status(f"Reescribiendo fragmento ({len(seleccion):,} chars)…")
        self._btn_reescribir.setEnabled(False)
        self._btn_analizar.setEnabled(False)
        self._btn_corregir.setEnabled(False)
        self._worker = _RevisionWorker(prompt)
        self._worker.done.connect(self._on_reescritura_done)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_reescritura_done(self, nuevo_texto: str):
        """Reemplaza la selección en _txt_resultado con el texto reescrito."""
        if self._rewrite_cursor is not None:
            self._rewrite_cursor.insertText(nuevo_texto)
            self._txt_resultado.setTextCursor(self._rewrite_cursor)
            self._rewrite_cursor = None
        self._btn_reescribir.setEnabled(True)
        self._btn_analizar.setEnabled(True)
        self._btn_corregir.setEnabled(bool(self._analisis_text))
        self._set_status(
            "Fragmento reescrito. Puedes seleccionar otro fragmento y volver a iterar."
        )

    def _on_error(self, msg: str):
        self._btn_analizar.setEnabled(True)
        self._btn_corregir.setEnabled(bool(self._analisis_text))
        self._btn_reescribir.setEnabled(bool(self._txt_resultado.toPlainText().strip()))
        self._rewrite_cursor = None
        self._set_status(f"Error: {msg[:80]}")
        QMessageBox.critical(self, "Error", msg)

    def showEvent(self, event):
        super().showEvent(event)
        self._restaurar_ultimo_archivo()

    def closeEvent(self, event):
        """Ocultar en vez de cerrar — preserva el estado de la ventana."""
        event.ignore()
        self.hide()

    def _set_status(self, msg: str):
        self._lbl_status.setText(msg)
