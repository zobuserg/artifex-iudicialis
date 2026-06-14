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
    QListWidget,
    QListWidgetItem,
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
    create_case_folder,
    dir_bibliografia_materia,
    dir_corpus_materia,
    get_next_case_number,
    list_bibliografia,
    list_case_folders,
    list_corpus_pdfs,
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


class _NoScrollComboBox(QComboBox):
    """Combo que NO cambia de valor con la rueda/scroll del mouse.

    Por defecto QComboBox captura el evento de rueda y cambia de selección cuando el
    cursor pasa por encima mientras se hace scroll en la página — provoca cambios de
    caso/materia/postura accidentales. Aquí el scroll se ignora y se propaga al
    contenedor (la página se desplaza); el valor solo cambia por clic o teclado.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def wheelEvent(self, event):  # noqa: N802 (firma de Qt)
        event.ignore()


def _combo_con_despliegue(combo: "QComboBox") -> QWidget:
    """Envuelve un combo con un botón lateral ▼ que abre su menú desplegable.

    El botón es un disparador explícito de ``showPopup()`` para que el despliegue
    sea evidente (además de la flecha nativa del combo).
    """
    w = QWidget()
    w.setStyleSheet("border: none;")
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(6)
    h.addWidget(combo, 1)
    btn = QPushButton("▼")
    btn.setToolTip("Desplegar opciones")
    btn.setFixedSize(36, 36)
    btn.setStyleSheet(_BTN_SMALL_GHOST)
    btn.clicked.connect(lambda: combo.showPopup())
    h.addWidget(btn)
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


class _IterarWorker(QThread):
    """Iteración post-resolución: produce SOLO la corrección/ampliación pedida,
    para anexarla al final del documento sin tocar la resolución ya generada."""
    done  = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, resolucion: str, instruccion: str, parent=None):
        super().__init__(parent)
        self._resolucion  = resolucion
        self._instruccion = instruccion

    def run(self):
        try:
            from app.artifex.llm import call_model
            prompt = (
                "Eres asistente del juez de la Sala Superior Penal de Apelaciones de "
                "Chincha y Pisco. La resolución de abajo YA está firmada en su forma y "
                "NO debe reescribirse. El juez pide una corrección o ampliación puntual; "
                "tu tarea es producir SOLO ese texto nuevo, para anexarlo a continuación "
                "de la resolución (no reproduzcas la resolución completa).\n\n"
                "INSTRUCCIÓN DEL JUEZ:\n"
                f"{self._instruccion}\n\n"
                "Reglas:\n"
                "• Devuelve únicamente el numeral/ítem corregido o el desarrollo ampliado "
                "que pide la instrucción, con el mismo estilo técnico-jurídico y formato "
                "de la resolución (numeración, tercera persona impersonal).\n"
                "• Si corriges un numeral, encabézalo indicando cuál (p. ej. «Numeral 12 "
                "(corregido):»). Si amplías, titúlalo de forma clara.\n"
                "• No inventes citas ni jurisprudencia sin respaldo. Sé preciso.\n\n"
                "RESOLUCIÓN (solo como contexto — NO la reproduzcas):\n"
                f"{self._resolucion[:18000]}"
            )
            texto, _ = call_model(
                prompt,
                max_tokens=6000,
            )
            self.done.emit(texto.strip())
        except Exception as exc:
            self.error.emit(str(exc))


class _BuscarWebWorker(QThread):
    """Búsqueda web jurídica (jurisprudencia/casaciones/AP/TC + doctrina/libros).

    Si el juez escribió un término, busca con ese; si lo dejó vacío, destila las
    palabras clave del contexto del caso con Haiku y busca con esas keywords.
    """
    done        = pyqtSignal(str)
    query_usada = pyqtSignal(str)   # términos efectivamente buscados (para el campo)
    error       = pyqtSignal(str)

    def __init__(self, termino: str, contexto: str = "", parent=None):
        super().__init__(parent)
        self._termino  = termino or ""
        self._contexto = contexto or ""

    def run(self):
        try:
            from app.artifex.nodes import buscar_web_juridica, destilar_terminos_busqueda
            query = self._termino.strip()
            if not query:
                query = destilar_terminos_busqueda(self._contexto) or self._contexto[:120]
            query = query.strip()
            self.query_usada.emit(query)
            self.done.emit(buscar_web_juridica(query))
        except Exception as exc:
            self.error.emit(str(exc))


class _TranscribeWorker(QThread):
    """Transcribe un archivo de audio con Whisper y devuelve el texto resultante."""
    done  = pyqtSignal(str, str)   # (txt_path, texto_transcripcion)
    error = pyqtSignal(str)

    def __init__(self, audio_path: Path, parent=None):
        super().__init__(parent)
        self._audio_path = audio_path

    def run(self):
        try:
            from app.core.whisper_local import transcribe_audio_to_txt, whisper_cli_available
            if not whisper_cli_available():
                self.error.emit(
                    "Whisper no está instalado. Instala con: pip install openai-whisper\n"
                    "O coloca manualmente un archivo <nombre_audio>.txt en la misma carpeta."
                )
                return
            ok, result = transcribe_audio_to_txt(self._audio_path)
            if not ok:
                self.error.emit(result)
                return
            txt_path = Path(result)
            texto = txt_path.read_text(encoding="utf-8", errors="replace") if txt_path.is_file() else result
            self.done.emit(str(txt_path), texto)
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

        # Botón de transcripción (solo ranura audio)
        self._btn_transcribe: QPushButton | None = None
        if slot_key == "audio":
            self._btn_transcribe = QPushButton("🎙")
            self._btn_transcribe.setToolTip("Ver / generar transcripción del audio (Whisper)")
            self._btn_transcribe.setFixedSize(28, 28)
            self._btn_transcribe.setStyleSheet(
                f"QPushButton {{ background: {_C['panel2']}; color: {_C['kraft']}; "
                f"border: 1px solid {_C['hair']}; border-radius: 7px; "
                f"font-size: 14px; padding: 0; }}"
                f"QPushButton:hover {{ background: {_C['gold_s']}; border-color: {_C['gold']}; }}"
            )
            self._btn_transcribe.clicked.connect(self._on_transcribir)
            self._btn_transcribe.hide()
            lay.addWidget(self._btn_transcribe)

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

        # Mostrar botón de transcripción si hay archivos de audio
        if self._btn_transcribe is not None:
            from app.core.claude_worker import AUDIO_SUFFIXES
            has_audio = any(f.suffix.lower() in AUDIO_SUFFIXES for f in self._files)
            if has_audio:
                self._btn_transcribe.show()
                # Indicar si ya existe transcripción para el primer audio
                has_transcript = any(
                    (f.parent / f"{f.stem}.txt").is_file()
                    for f in self._files
                    if f.suffix.lower() in AUDIO_SUFFIXES
                )
                self._btn_transcribe.setToolTip(
                    "Transcripción disponible — clic para ver" if has_transcript
                    else "Transcribir audio con Whisper (o ver si ya existe .txt)"
                )
                self._btn_transcribe.setStyleSheet(
                    f"QPushButton {{ background: {_C['teal_s'] if has_transcript else _C['panel2']}; "
                    f"color: {_C['teal_d'] if has_transcript else _C['kraft']}; "
                    f"border: 1px solid {_C['teal'] if has_transcript else _C['hair']}; "
                    f"border-radius: 7px; font-size: 14px; padding: 0; }}"
                    f"QPushButton:hover {{ background: {_C['gold_s']}; border-color: {_C['gold']}; }}"
                )
            else:
                self._btn_transcribe.hide()

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

    def _on_transcribir(self):
        """Ver o generar transcripción de los audios en este slot."""
        from app.core.claude_worker import AUDIO_SUFFIXES
        audio_files = [f for f in self._files if f.suffix.lower() in AUDIO_SUFFIXES]
        if not audio_files:
            QMessageBox.information(self, "Transcripción", "No hay archivos de audio en esta ranura.")
            return

        # Mostrar archivos y estado de transcripción
        dlg = QDialog(self)
        dlg.setWindowTitle("Audio de audiencia — Transcripción")
        dlg.resize(680, 500)
        dlg.setStyleSheet(f"background: {_C['paper']};")
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(10)
        lay.addWidget(_lbl("Audio de audiencia · Transcripción", bold=True, size=14))

        # Selección de archivo
        row = QHBoxLayout()
        row.addWidget(_lbl("Archivo:", size=12))
        combo = _NoScrollComboBox()
        combo.setStyleSheet(_INPUT_SS)
        for f in audio_files:
            combo.addItem(f.name, userData=str(f))
        row.addWidget(combo, 1)
        lay.addLayout(row)

        # Vista de transcripción
        txt = QPlainTextEdit()
        txt.setStyleSheet(_INPUT_SS + "QPlainTextEdit { font-size: 12px; min-height: 240px; }")
        txt.setReadOnly(True)
        lay.addWidget(txt, 1)

        status_lbl = _lbl("", color=_C["faint"], size=11)
        lay.addWidget(status_lbl)

        def _cargar_transcript():
            idx = combo.currentIndex()
            audio_path = Path(combo.itemData(idx))
            txt_path = audio_path.parent / f"{audio_path.stem}.txt"
            if txt_path.is_file():
                content = txt_path.read_text(encoding="utf-8", errors="replace")
                txt.setPlainText(content)
                status_lbl.setText(f"Transcripción cargada desde: {txt_path.name}")
            else:
                txt.setPlainText("")
                status_lbl.setText("Sin transcripción. Usa 'Transcribir' para generarla con Whisper.")

        combo.currentIndexChanged.connect(_cargar_transcript)
        _cargar_transcript()

        def _run_transcribe():
            idx = combo.currentIndex()
            audio_path = Path(combo.itemData(idx))
            btn_transcribe_now.setEnabled(False)
            status_lbl.setText("Transcribiendo… (puede tardar varios minutos)")

            worker = _TranscribeWorker(audio_path, parent=dlg)

            def on_done(txt_path, texto):
                txt.setPlainText(texto)
                status_lbl.setText(f"Transcripción guardada en: {Path(txt_path).name}")
                btn_transcribe_now.setEnabled(True)
                self.set_files(list(self._files))  # actualizar indicador de estado

            def on_error(msg):
                status_lbl.setText(f"Error: {msg}")
                btn_transcribe_now.setEnabled(True)

            worker.done.connect(on_done)
            worker.error.connect(on_error)
            worker.start()

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_transcribe_now = QPushButton("🎙  Transcribir con Whisper")
        btn_transcribe_now.setStyleSheet(_BTN_GOLD)
        btn_transcribe_now.clicked.connect(_run_transcribe)
        btn_row.addWidget(btn_transcribe_now)
        btn_close = QPushButton("Cerrar")
        btn_close.setStyleSheet(_BTN_GHOST)
        btn_close.clicked.connect(dlg.accept)
        btn_row.addWidget(btn_close)
        lay.addLayout(btn_row)

        dlg.exec()


# ── Diálogos de bibliografía ─────────────────────────────────────────────────

class _NoteEditorDialog(QDialog):
    """Editor de texto simple para crear o editar notas .md en la bibliografía."""

    def __init__(self, titulo: str = "Nueva nota", texto: str = "",
                 nombre_fijo: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle(titulo)
        self.resize(700, 500)
        self.setStyleSheet(f"background: {_C['paper']};")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(10)

        # Nombre del archivo (ocultable si es edición)
        self._row_nombre = QWidget()
        rn_lay = QHBoxLayout(self._row_nombre)
        rn_lay.setContentsMargins(0, 0, 0, 0)
        rn_lay.setSpacing(8)
        rn_lay.addWidget(_lbl("Nombre:", size=12))
        self._inp_nombre = QLineEdit()
        self._inp_nombre.setPlaceholderText("ej: jurisprudencia_casacion_PP")
        self._inp_nombre.setStyleSheet(_INPUT_SS)
        if nombre_fijo:
            self._inp_nombre.setText(nombre_fijo)
            self._inp_nombre.setReadOnly(True)
        rn_lay.addWidget(self._inp_nombre, 1)
        rn_lay.addWidget(_lbl(".md", color=_C["faint"], size=11))
        lay.addWidget(self._row_nombre)

        # Editor de texto
        self._txt = QPlainTextEdit()
        self._txt.setPlainText(texto)
        self._txt.setStyleSheet(
            _INPUT_SS + "QPlainTextEdit { font-size: 12px; min-height: 280px; }"
        )
        lay.addWidget(self._txt, 1)

        # Botones
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_cancel = QPushButton("Cancelar")
        btn_cancel.setStyleSheet(_BTN_GHOST)
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)
        btn_ok = QPushButton("💾  Guardar")
        btn_ok.setStyleSheet(_BTN_PRIMARY)
        btn_ok.clicked.connect(self.accept)
        btn_row.addWidget(btn_ok)
        lay.addLayout(btn_row)

    def nombre(self) -> str:
        return self._inp_nombre.text().strip()

    def texto(self) -> str:
        return self._txt.toPlainText()


class _BibliografiaDialog(QDialog):
    """Gestionar la bibliografía de una materia: ver, agregar, editar notas, eliminar."""

    def __init__(self, materia: str, parent=None):
        super().__init__(parent)
        self._materia = materia
        mat_label = MATERIA_LABELS.get(materia, materia)
        self.setWindowTitle(f"Bibliografía · {mat_label}")
        self.resize(760, 540)
        self.setStyleSheet(f"background: {_C['paper']};")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 14)
        lay.setSpacing(10)

        # Encabezado
        lay.addWidget(_lbl(f"Bibliografía adicional — {mat_label}", bold=True, size=15))
        info = _lbl(
            "Se incluye automáticamente en la redacción de todos los casos de esta materia. "
            "Los archivos .md/.txt son editables directamente.",
            color=_C["faint"], size=10,
        )
        info.setWordWrap(True)
        lay.addWidget(info)

        # Lista con scroll
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(
            f"QScrollArea {{ border: 1px solid {_C['hair']}; border-radius: 8px;"
            f" background: {_C['card']}; }}"
        )
        self._list_widget = QWidget()
        self._list_widget.setStyleSheet(f"background: {_C['card']};")
        self._list_lay = QVBoxLayout(self._list_widget)
        self._list_lay.setContentsMargins(10, 10, 10, 10)
        self._list_lay.setSpacing(5)
        scroll.setWidget(self._list_widget)
        lay.addWidget(scroll, 1)

        # Barra de progreso de ingesta (oculta por defecto)
        self._ingest_worker = None
        self._progress_lbl = _lbl("", color=_C["teal_d"], size=10)
        self._progress_lbl.setWordWrap(True)
        self._progress_lbl.setVisible(False)
        lay.addWidget(self._progress_lbl)

        # Botones inferiores
        btn_row = QHBoxLayout()
        btn_add = QPushButton("➕  Agregar archivos…")
        btn_add.setStyleSheet(_BTN_GHOST)
        btn_add.clicked.connect(self._on_agregar)
        btn_row.addWidget(btn_add)

        btn_nota = QPushButton("📝  Nueva nota rápida…")
        btn_nota.setStyleSheet(_BTN_GHOST)
        btn_nota.clicked.connect(self._on_nueva_nota)
        btn_row.addWidget(btn_nota)

        self._btn_fichas = QPushButton("⚙  Generar fichas wiki…")
        self._btn_fichas.setStyleSheet(_BTN_GHOST)
        self._btn_fichas.setToolTip(
            "Procesa los PDF/Word de esta materia que aún no tienen ficha wiki.\n"
            "Las fichas se guardan en 02_wiki/bibliografia/ y quedan disponibles\n"
            "para el chat de la wiki sin truncar el contenido."
        )
        self._btn_fichas.clicked.connect(self._on_generar_fichas)
        btn_row.addWidget(self._btn_fichas)

        btn_row.addStretch()

        btn_cerrar = QPushButton("Cerrar")
        btn_cerrar.setStyleSheet(_BTN_PRIMARY)
        btn_cerrar.clicked.connect(self.accept)
        btn_row.addWidget(btn_cerrar)
        lay.addLayout(btn_row)

        self._refresh()

    # ── helpers ──────────────────────────────────────────────────────────────

    def _refresh(self):
        """Reconstruye la lista de archivos."""
        while self._list_lay.count():
            item = self._list_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        try:
            files = list_bibliografia(self._materia)
        except Exception:
            files = []

        if not files:
            lbl = _lbl(
                "Sin archivos. Usa los botones de abajo para agregar bibliografía o crear una nota.",
                color=_C["faint"], size=11,
            )
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setWordWrap(True)
            self._list_lay.addWidget(lbl)
            self._list_lay.addStretch()
            return

        for f in files:
            row = QWidget()
            row.setStyleSheet(
                f"background: {_C['panel']}; border-radius: 6px;"
                f" border: 1px solid {_C['hair']};"
            )
            rl = QHBoxLayout(row)
            rl.setContentsMargins(10, 6, 8, 6)
            rl.setSpacing(8)

            is_text = f.suffix.lower() in (".md", ".txt")
            icon = "📝" if is_text else "📄"
            lbl_name = _lbl(f"{icon}  {f.name}", size=11)
            lbl_name.setToolTip(str(f))
            rl.addWidget(lbl_name, 1)

            if is_text:
                btn_edit = QPushButton("✏")
                btn_edit.setToolTip("Editar contenido")
                btn_edit.setFixedWidth(32)
                btn_edit.setStyleSheet(_BTN_SMALL_GHOST)
                btn_edit.clicked.connect(lambda _, path=f: self._on_editar(path))
                rl.addWidget(btn_edit)

            btn_del = QPushButton("🗑")
            btn_del.setToolTip("Eliminar de la bibliografía")
            btn_del.setFixedWidth(32)
            btn_del.setStyleSheet(_BTN_SMALL_GHOST)
            btn_del.clicked.connect(lambda _, path=f: self._on_eliminar(path))
            rl.addWidget(btn_del)

            self._list_lay.addWidget(row)

        self._list_lay.addStretch()

    # ── acciones ─────────────────────────────────────────────────────────────

    def _on_generar_fichas(self):
        """Lanza BibliografiaIngestorWorker para generar fichas wiki de los PDFs pendientes."""
        from app.core.wiki_worker import BibliografiaIngestorWorker
        from app.core.file_manager import pending_bibliografia_for_fichas

        if self._ingest_worker and self._ingest_worker.isRunning():
            QMessageBox.information(self, "En curso", "Ya hay una ingesta en curso. Espera a que termine.")
            return

        try:
            pendientes = pending_bibliografia_for_fichas(self._materia)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudo leer pendientes:\n{e}")
            return

        if not pendientes:
            QMessageBox.information(
                self, "Al día",
                "Todos los archivos de esta materia ya tienen ficha wiki.\n"
                "No hay nada pendiente.",
            )
            return

        resp = QMessageBox.question(
            self, "Generar fichas wiki",
            f"Se generarán fichas para {len(pendientes)} archivo(s) pendiente(s).\n"
            "Esto usa la API de Claude (Haiku) y puede tardar unos minutos.\n\n"
            "¿Continuar?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if resp != QMessageBox.StandardButton.Yes:
            return

        self._btn_fichas.setEnabled(False)
        self._progress_lbl.setText(f"⏳ Procesando 0/{len(pendientes)}…")
        self._progress_lbl.setVisible(True)

        self._ingest_worker = BibliografiaIngestorWorker(self._materia)

        def _on_progress(cur, tot, name):
            self._progress_lbl.setText(f"⏳ Procesando {cur}/{tot} — {name}")

        def _on_finished(n):
            self._progress_lbl.setText(
                f"✓ {n} ficha(s) generada(s) en 02_wiki/bibliografia/{self._materia}/"
                if n else "Sin cambios — archivos ya procesados."
            )
            self._btn_fichas.setEnabled(True)
            self._refresh()

        def _on_error(msg):
            self._progress_lbl.setText(f"Error: {msg[:120]}")
            self._btn_fichas.setEnabled(True)

        self._ingest_worker.progress.connect(_on_progress)
        self._ingest_worker.finished.connect(_on_finished)
        self._ingest_worker.error_occurred.connect(_on_error)
        self._ingest_worker.start()

    def _on_agregar(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Agregar archivos a la bibliografía",
            str(BASE_DIR / "01_raw"), qt_open_filter(),
        )
        n = 0
        for p in paths:
            try:
                add_bibliografia(Path(p), materia=self._materia)
                n += 1
            except Exception:
                pass
        if n:
            self._refresh()

    def _on_nueva_nota(self):
        dlg = _NoteEditorDialog("Nueva nota rápida", parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        texto = dlg.texto().strip()
        if not texto:
            QMessageBox.information(self, "Sin contenido", "La nota está vacía.")
            return
        nombre = dlg.nombre() or "nota_rapida"
        if not nombre.endswith(".md"):
            nombre += ".md"
        nombre = nombre.replace(" ", "_")
        dest_dir = dir_bibliografia_materia(self._materia)
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / nombre
        # Evitar sobreescritura silenciosa
        i = 1
        while dest.exists():
            stem = Path(nombre).stem
            dest = dest_dir / f"{stem}_{i}.md"
            i += 1
        try:
            dest.write_text(texto, encoding="utf-8")
            self._refresh()
        except Exception as e:
            QMessageBox.critical(self, "Error al guardar", f"{e}")

    def _on_editar(self, path: Path):
        try:
            texto = path.read_text(encoding="utf-8")
        except Exception as e:
            QMessageBox.critical(self, "Error al leer", f"{e}")
            return
        dlg = _NoteEditorDialog(
            f"Editar — {path.name}", texto=texto,
            nombre_fijo=path.stem, parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            path.write_text(dlg.texto(), encoding="utf-8")
        except Exception as e:
            QMessageBox.critical(self, "Error al guardar", f"{e}")

    def _on_eliminar(self, path: Path):
        resp = QMessageBox.question(
            self, "Eliminar archivo",
            f"¿Eliminar «{path.name}» de la bibliografía?\nEsta acción no se puede deshacer.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if resp != QMessageBox.StandardButton.Yes:
            return
        try:
            path.unlink()
            self._refresh()
        except Exception as e:
            QMessageBox.critical(self, "Error al eliminar", f"{e}")


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
    ver_proceso     = pyqtSignal(str)    # caso_path cuando pulsa "Ver proceso"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background: {_C['paper']};")
        self._live_web = False
        self._slot_cards: dict[str, _SlotCard] = {}
        self._resoluciones_estilo: list[Path] = []   # hasta 3 resoluciones de referencia
        self._meta_cache: dict[str, dict] = {}       # caso_path → metadatos extraídos (evita re-llamar API)
        self._meta_caso_actual: str = ""             # caso visible (para sincronizar auto-extracción)
        self._meta_worker_caso: str = ""             # caso para el que corre el worker en curso

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
        self._cmb_materia = _NoScrollComboBox()
        self._cmb_materia.setStyleSheet(_INPUT_SS + "QComboBox { padding: 10px 14px; }")
        _default_idx = 0
        for i, slug in enumerate(sorted(MATERIA_SLUGS)):
            label = MATERIA_LABELS.get(slug, slug)
            self._cmb_materia.addItem(label, userData=slug)
            if slug == "prision_preventiva":
                _default_idx = i
        self._cmb_materia.setCurrentIndex(_default_idx)
        self._cmb_materia.currentIndexChanged.connect(self._on_materia_changed)
        mat_l.addWidget(_combo_con_despliegue(self._cmb_materia))
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
        self._btn_nuevo_caso = QPushButton("＋  Nuevo caso")
        self._btn_nuevo_caso.setToolTip("Crear un caso nuevo")
        self._btn_nuevo_caso.setStyleSheet(_BTN_SMALL_GHOST)
        self._btn_nuevo_caso.clicked.connect(self._on_nuevo_caso)
        ch_lay.addWidget(self._btn_nuevo_caso)
        self._btn_casos_ant = QPushButton("📂  Casos anteriores")
        self._btn_casos_ant.setToolTip("Seleccionar y abrir un caso ya procesado")
        self._btn_casos_ant.setStyleSheet(_BTN_SMALL_GHOST)
        self._btn_casos_ant.clicked.connect(self._on_casos_anteriores)
        ch_lay.addWidget(self._btn_casos_ant)
        caso_l.addWidget(caso_header)
        self._cmb_caso = _NoScrollComboBox()
        self._cmb_caso.setStyleSheet(_INPUT_SS + "QComboBox { padding: 10px 14px; }")
        self._cmb_caso.currentIndexChanged.connect(self._on_caso_changed)
        caso_l.addWidget(_combo_con_despliegue(self._cmb_caso))
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
        self._btn_ver_proceso = QPushButton("🔍  Ver proceso")
        self._btn_ver_proceso.setStyleSheet(_BTN_SMALL_GHOST)
        self._btn_ver_proceso.setToolTip(
            "Revisa dentro de la app los hechos, fuentes y borrador que se usaron "
            "para generar la resolución de este caso."
        )
        self._btn_ver_proceso.setVisible(False)
        self._btn_ver_proceso.clicked.connect(self._on_ver_proceso_caso)
        sh_lay.addWidget(self._btn_ver_proceso)
        self._btn_ver_resolucion = QPushButton("📄  Abrir .docx")
        self._btn_ver_resolucion.setStyleSheet(_BTN_SMALL_GHOST)
        self._btn_ver_resolucion.setToolTip("Abre el documento .docx generado para este caso")
        self._btn_ver_resolucion.setVisible(False)
        self._btn_ver_resolucion.clicked.connect(self._on_ver_resolucion_caso)
        sh_lay.addWidget(self._btn_ver_resolucion)
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

        # Los datos se extraen AUTOMÁTICAMENTE al seleccionar el caso (ver _auto_meta).
        # Los campos quedan editables para corregir lo que haga falta. Este botón
        # solo fuerza una nueva extracción si el juez la pide.
        self._AUTOCOMPLETAR_TXT = "↻  Volver a extraer datos del documento"
        self._btn_autocompletar = QPushButton(self._AUTOCOMPLETAR_TXT)
        self._btn_autocompletar.setStyleSheet(_BTN_SMALL_GHOST)
        self._btn_autocompletar.setToolTip(
            "Los datos del expediente se completan solos al elegir el caso.\n"
            "Edítelos libremente si algo está mal, o pulse aquí para volver\n"
            "a extraerlos desde los documentos."
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
        self._cmb_postura = _NoScrollComboBox()
        self._cmb_postura.setStyleSheet(_INPUT_SS + "QComboBox { padding: 10px 14px; }")
        self._cmb_postura.addItem("CONFIRMAR",            userData="confirmar")
        self._cmb_postura.addItem("REVOCAR",              userData="revocar")
        self._cmb_postura.addItem("REVOCAR PARCIALMENTE", userData="revocar_parcial")
        right_l.addWidget(_combo_con_despliegue(self._cmb_postura))

        right_l.addWidget(_section_label("Plantilla (formato del acto)"))
        plantilla_row = QWidget()
        plantilla_row.setStyleSheet("border: none;")
        plantilla_lay = QHBoxLayout(plantilla_row)
        plantilla_lay.setContentsMargins(0, 0, 0, 0)
        plantilla_lay.setSpacing(6)
        self._cmb_plantilla = _NoScrollComboBox()
        self._cmb_plantilla.setStyleSheet(_INPUT_SS + "QComboBox { padding: 10px 14px; }")
        self._cmb_plantilla.setToolTip(
            "Modelo de resolución que define formato, acápites y esquema.\n"
            "Se carga de 01_raw/plantillas/<materia>/. El acto seguirá su estructura.\n"
            "Por defecto se usa la primera plantilla de la materia."
        )
        plantilla_lay.addWidget(self._cmb_plantilla, 1)
        _btn_desplegar_plantilla = QPushButton("▼")
        _btn_desplegar_plantilla.setToolTip("Desplegar opciones")
        _btn_desplegar_plantilla.setFixedSize(36, 36)
        _btn_desplegar_plantilla.setStyleSheet(_BTN_SMALL_GHOST)
        _btn_desplegar_plantilla.clicked.connect(lambda: self._cmb_plantilla.showPopup())
        plantilla_lay.addWidget(_btn_desplegar_plantilla)
        _btn_ver_plantilla = QPushButton("👁")
        _btn_ver_plantilla.setToolTip("Ver el contenido de la plantilla seleccionada")
        _btn_ver_plantilla.setFixedSize(36, 36)
        _btn_ver_plantilla.setStyleSheet(_BTN_SMALL_GHOST)
        _btn_ver_plantilla.clicked.connect(self._on_ver_plantilla)
        plantilla_lay.addWidget(_btn_ver_plantilla)
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

        right_l.addWidget(_section_label("Estilo del magistrado (corpus)"))
        corpus_w = QWidget()
        corpus_w.setStyleSheet("border: none;")
        corpus_l = QVBoxLayout(corpus_w)
        corpus_l.setContentsMargins(0, 0, 0, 0)
        corpus_l.setSpacing(4)
        self._btn_corpus = QPushButton("📄  Seleccionar resoluciones de referencia…")
        self._btn_corpus.setStyleSheet(_BTN_GHOST)
        self._btn_corpus.setToolTip(
            "Selecciona hasta 3 resoluciones propias del magistrado como referencia de estilo.\n"
            "El sistema las usará para imitar tu vocabulario, estructura y tono — no su contenido.\n"
            "Los archivos deben estar en 01_raw/<materia>/corpus_magistrado/."
        )
        self._btn_corpus.clicked.connect(self._on_seleccionar_corpus)
        corpus_l.addWidget(self._btn_corpus)
        self._corpus_lbl = _lbl("Sin resoluciones de referencia seleccionadas.",
                                color=_C["faint"], size=10)
        self._corpus_lbl.setWordWrap(True)
        self._corpus_lbl.setStyleSheet(f"color: {_C['faint']}; font-size: 10px; border: none;")
        corpus_l.addWidget(self._corpus_lbl)
        right_l.addWidget(corpus_w)

        right_l.addWidget(_section_label("Bibliografía adicional"))
        bib_w = QWidget()
        bib_w.setStyleSheet("border: none;")
        bib_l = QVBoxLayout(bib_w)
        bib_l.setContentsMargins(0, 0, 0, 0)
        bib_l.setSpacing(4)
        self._btn_add_bib = QPushButton("📚  Gestionar bibliografía…")
        self._btn_add_bib.setStyleSheet(_BTN_GHOST)
        self._btn_add_bib.setToolTip(
            "Ver, agregar, editar y eliminar archivos de la bibliografía de esta materia.\n"
            "Se incluye automáticamente en la redacción (Bloque 5) de los casos de la materia."
        )
        self._btn_add_bib.clicked.connect(self._on_gestionar_bibliografia)
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

    def _materia_de_path(self, p: Path) -> str:
        """Infiere el slug de materia desde 01_raw/<materia>/caso_… (o PP por defecto)."""
        try:
            parts = p.parts
            if "01_raw" in parts:
                i = parts.index("01_raw")
                if i + 1 < len(parts) and parts[i + 1] in MATERIA_SLUGS:
                    return parts[i + 1]
        except Exception:
            pass
        return "prision_preventiva"

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

    def _on_gestionar_bibliografia(self):
        materia = self._current_materia_slug()
        dlg = _BibliografiaDialog(materia, parent=self)
        dlg.exec()
        # Refrescar el label de resumen al cerrar
        self._refresh_bibliografia()

    def _on_ver_plantilla(self):
        """Muestra el contenido de la plantilla seleccionada en el combo."""
        from app.core.claude_worker import read_file_text
        path_str = self._current_plantilla_path()
        if not path_str:
            QMessageBox.information(self, "Sin plantilla", "No hay plantilla seleccionada.")
            return
        path = Path(path_str)
        if not path.is_file():
            QMessageBox.warning(self, "No encontrada", f"El archivo no existe:\n{path}")
            return
        try:
            contenido = read_file_text(path)
        except Exception as e:
            QMessageBox.critical(self, "Error al leer", str(e))
            return
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Plantilla — {path.name}")
        dlg.resize(860, 620)
        dlg.setStyleSheet(f"background: {_C['paper']};")
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(16, 14, 16, 12)
        lay.setSpacing(8)
        lay.addWidget(_lbl(path.name, bold=True, size=13))
        txt = QTextEdit()
        txt.setPlainText(contenido)
        txt.setReadOnly(True)
        txt.setStyleSheet(_INPUT_SS + "QTextEdit { font-size: 12px; }")
        lay.addWidget(txt, 1)
        btn = QPushButton("Cerrar")
        btn.setStyleSheet(_BTN_GHOST)
        btn.clicked.connect(dlg.accept)
        lay.addWidget(btn, alignment=Qt.AlignmentFlag.AlignRight)
        dlg.exec()

    def _on_seleccionar_corpus(self):
        """Abre el selector de resoluciones de referencia (corpus del magistrado)."""
        materia = self._current_materia_slug()
        archivos = list_corpus_pdfs(materia)
        corpus_dir = dir_corpus_materia(materia)

        if not archivos:
            resp = QMessageBox.question(
                self, "Corpus vacío",
                f"No hay resoluciones en:\n{corpus_dir}\n\n"
                "¿Deseas agregar archivos ahora?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if resp == QMessageBox.StandardButton.Yes:
                paths, _ = QFileDialog.getOpenFileNames(
                    self, "Agregar resoluciones al corpus",
                    str(BASE_DIR), qt_open_filter(),
                )
                for p in paths:
                    try:
                        import shutil
                        shutil.copy2(p, corpus_dir / Path(p).name)
                    except Exception:
                        pass
                archivos = list_corpus_pdfs(materia)
            if not archivos:
                return

        # Diálogo de selección
        dlg = QDialog(self)
        dlg.setWindowTitle("Estilo del magistrado — selecciona hasta 3 resoluciones")
        dlg.resize(680, 480)
        dlg.setStyleSheet(f"background: {_C['paper']};")
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(18, 16, 18, 12)
        lay.setSpacing(10)

        lay.addWidget(_lbl("Resoluciones de referencia de estilo", bold=True, size=14))
        info = _lbl(
            "Selecciona hasta 3. El modelo imitará tu vocabulario y estructura — "
            "no los hechos ni las decisiones de estas resoluciones.",
            color=_C["faint"], size=10,
        )
        info.setWordWrap(True)
        lay.addWidget(info)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(
            f"QScrollArea {{ border: 1px solid {_C['hair']}; border-radius: 8px; "
            f"background: {_C['card']}; }}"
        )
        container = QWidget()
        container.setStyleSheet(f"background: {_C['card']};")
        c_lay = QVBoxLayout(container)
        c_lay.setContentsMargins(10, 10, 10, 10)
        c_lay.setSpacing(5)

        checks: list[tuple[QCheckBox, Path]] = []
        ya_sel = {str(p) for p in self._resoluciones_estilo}
        for f in archivos:
            cb = QCheckBox(f.name)
            cb.setChecked(str(f) in ya_sel)
            cb.setStyleSheet("font-size: 12px; padding: 4px;")
            checks.append((cb, f))
            c_lay.addWidget(cb)
        c_lay.addStretch()
        scroll.setWidget(container)
        lay.addWidget(scroll, 1)

        lbl_count = _lbl("", color=_C["gold_d"], size=11)
        lay.addWidget(lbl_count)

        def _update_count():
            n = sum(1 for cb, _ in checks if cb.isChecked())
            lbl_count.setText(f"{n}/3 seleccionadas")
            if n > 3:
                # Desmarcar la última marcada si supera 3
                for cb, _ in checks:
                    if cb.isChecked():
                        cb.setChecked(False)
                        break

        for cb, _ in checks:
            cb.toggled.connect(lambda _: _update_count())
        _update_count()

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_cancel = QPushButton("Cancelar")
        btn_cancel.setStyleSheet(_BTN_GHOST)
        btn_cancel.clicked.connect(dlg.reject)
        btn_row.addWidget(btn_cancel)
        btn_ok = QPushButton("Confirmar selección")
        btn_ok.setStyleSheet(_BTN_PRIMARY)
        btn_ok.clicked.connect(dlg.accept)
        btn_row.addWidget(btn_ok)
        lay.addLayout(btn_row)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        seleccionadas = [f for cb, f in checks if cb.isChecked()][:3]
        self._resoluciones_estilo = seleccionadas
        if seleccionadas:
            nombres = ", ".join(p.name for p in seleccionadas)
            self._corpus_lbl.setText(f"{len(seleccionadas)}/3 · {nombres}")
            self._btn_corpus.setText(f"📄  {len(seleccionadas)} resolución(es) seleccionada(s)")
        else:
            self._corpus_lbl.setText("Sin resoluciones de referencia seleccionadas.")
            self._btn_corpus.setText("📄  Seleccionar resoluciones de referencia…")

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
        # Cambiar la materia a mano = preparar un caso NUEVO en esa materia.
        # El combo de Caso ya lista todos los casos, así que no se filtra; solo
        # se vuelve a "— Nuevo caso —" para evitar quedar con un caso de otra
        # materia desincronizado (la materia se usa en _on_iniciar).
        self._cmb_caso.blockSignals(True)
        self._cmb_caso.setCurrentIndex(0)
        self._cmb_caso.blockSignals(False)
        materia = self._current_materia_slug()
        labels = slot_labels_for(materia)
        for key, card in self._slot_cards.items():
            card._title.setText(labels.get(key, key))
        self._refresh_plantillas()
        self._refresh_bibliografia()
        self._refresh_slots()
        self._auto_meta()

    def _on_caso_changed(self, _idx: int):
        # Al elegir un caso, ajustar la materia a la suya y refrescar lo que
        # depende de la materia (etiquetas de ranuras, plantillas, bibliografía).
        caso = self._current_caso_path()
        if caso is not None:
            self._sync_materia_a_caso(caso)
            materia = self._current_materia_slug()
            labels = slot_labels_for(materia)
            for key, card in self._slot_cards.items():
                card._title.setText(labels.get(key, key))
            self._refresh_plantillas()
            self._refresh_bibliografia()
        self._refresh_slots()
        self._auto_meta()

    def _auto_meta(self):
        """Al cambiar de caso, completa los datos del expediente automáticamente.

        Estrategia (sin gasto innecesario de API):
          1. Si es el mismo caso ya visible, no hace nada.
          2. Limpia los campos (son de otro caso).
          3. Si ya se extrajo este caso en la sesión → restaura de caché (gratis).
          4. Si no, y el caso tiene documentos → dispara la extracción en segundo plano.
        Los campos quedan siempre editables para corrección manual.
        """
        caso = self._current_caso_path()
        key = str(caso) if caso else ""
        if key == self._meta_caso_actual:
            return

        # Antes de cambiar, conservar lo que el juez dejó en el caso anterior
        # (incluye sus correcciones manuales) para no perderlo al volver.
        if self._meta_caso_actual:
            actuales = {
                "expediente": self._exp.text().strip(), "imputados": self._imp.text().strip(),
                "delito": self._del.text().strip(), "agraviado": self._agr.text().strip(),
                "juzgado": self._juz.text().strip(),
            }
            if any(actuales.values()):
                self._meta_cache[self._meta_caso_actual] = actuales

        self._meta_caso_actual = key

        # Limpiar campos del caso anterior.
        for w in (self._exp, self._imp, self._del, self._agr, self._juz):
            w.clear()

        if not caso or not caso.exists():
            self._btn_autocompletar.setText(self._AUTOCOMPLETAR_TXT)
            return

        # Caché: restaurar sin volver a llamar a la API.
        if key in self._meta_cache:
            self._aplicar_meta(self._meta_cache[key], from_cache=True)
            return

        # Si hay una extracción en curso, no encimar otra.
        worker = getattr(self, "_meta_worker", None)
        if worker is not None and worker.isRunning():
            return

        # ¿El caso tiene documentos para leer?
        try:
            slots = read_fuentes_slots(caso)
        except Exception:
            slots = {}
        if not any(slots.values()):
            self._btn_autocompletar.setText(self._AUTOCOMPLETAR_TXT)
            return

        # Disparar extracción automática (no manual: respeta campos ya escritos).
        self._on_autocompletar(manual=False)

    def _on_nuevo_caso(self):
        """Crea una carpeta de caso nueva y la selecciona en el combo."""
        materia = self._current_materia_slug()
        nombre, ok = QInputDialog.getText(
            self, "Nuevo caso",
            "Nombre descriptivo del caso (ej: robo agravado):",
        )
        if not ok or not nombre.strip():
            return
        try:
            numero = get_next_case_number(materia)
            caso_dir = create_case_folder(numero, nombre.strip(), materia)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudo crear el caso:\n{e}")
            return
        self._refresh_casos(seleccionar=str(caso_dir))

    def _on_casos_anteriores(self):
        """Abre el selector de casos anteriores. Al elegir uno lo carga en el stepper."""
        dlg = _CasosAnterioresDialog(parent=self)
        dlg.caso_seleccionado.connect(self._cargar_caso_anterior)
        dlg.exec()

    def _cargar_caso_anterior(self, caso_path: str):
        """Carga un caso anterior: lo pone en el combo y abre el proceso en el stepper."""
        self._refresh_casos(seleccionar=caso_path)
        self.ver_proceso.emit(caso_path)

    # ── Autocompletado de datos del expediente ────────────────────────────
    def _autocompletar_reset(self, delay_ms: int = 4000):
        QTimer.singleShot(delay_ms, lambda: self._btn_autocompletar.setText(self._AUTOCOMPLETAR_TXT))

    def _on_autocompletar(self, _checked: bool = False, *, manual: bool = True):
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
        if manual:
            # Re-extracción explícita: limpiar caché y campos para volver a leer.
            self._meta_cache.pop(str(caso), None)
            for w in (self._exp, self._imp, self._del, self._agr, self._juz):
                w.clear()
        labels = slot_labels_for(self._current_materia_slug())
        self._meta_worker_caso = str(caso)
        self._btn_autocompletar.setEnabled(False)
        self._btn_autocompletar.setText("⏳  Leyendo documentos y extrayendo datos…")
        self._meta_worker = _MetaWorker(slots, labels, parent=self)
        self._meta_worker.done.connect(self._on_meta_done)
        self._meta_worker.failed.connect(self._on_meta_failed)
        self._meta_worker.start()

    def _aplicar_meta(self, data: dict, from_cache: bool = False) -> int:
        """Vuelca los metadatos a los campos. No sobrescribe lo que el juez ya editó."""
        campos = {
            "expediente": self._exp, "imputados": self._imp, "delito": self._del,
            "agraviado": self._agr, "juzgado": self._juz,
        }
        n = 0
        for k, widget in campos.items():
            val = (data or {}).get(k, "")
            if val:
                if not widget.text().strip():     # respeta correcciones manuales
                    widget.setText(val)
                n += 1
        self._btn_autocompletar.setEnabled(True)
        if n:
            sufijo = "" if from_cache else " — revise y corrija"
            self._btn_autocompletar.setText(f"✨  Datos completados ({n}/5){sufijo}")
        else:
            self._btn_autocompletar.setText("No se extrajeron datos — complete a mano")
        self._autocompletar_reset()
        return n

    def _on_meta_done(self, data: dict):
        # Cachear para este caso (evita re-llamar a la API al volver a seleccionarlo).
        if self._meta_worker_caso:
            self._meta_cache[self._meta_worker_caso] = data or {}
        # Si el juez ya cambió de caso mientras corría el worker, no piso sus campos.
        if self._meta_worker_caso and self._meta_worker_caso != self._meta_caso_actual:
            self._btn_autocompletar.setEnabled(True)
            self._btn_autocompletar.setText(self._AUTOCOMPLETAR_TXT)
            return
        self._aplicar_meta(data)

    def _on_meta_failed(self, msg: str):
        self._btn_autocompletar.setEnabled(True)
        self._btn_autocompletar.setText(f"Error al autocompletar: {msg[:40]}")
        self._autocompletar_reset(4000)

    def _refresh_casos(self, seleccionar: str | None = None):
        """Actualiza el combo de caso.

        El combo muestra SOLO el caso activo (el recién creado o el seleccionado
        desde "Casos anteriores"). No lista todos los expedientes — para eso está
        el botón "📂 Casos anteriores".
        """
        self._cmb_caso.blockSignals(True)
        self._cmb_caso.clear()
        self._cmb_caso.addItem("— Sin caso seleccionado —", userData="")

        if seleccionar:
            p = Path(seleccionar)
            mat = self._materia_de_path(p)
            etiqueta = f"{MATERIA_LABELS.get(mat, mat)} · {p.name}"
            self._cmb_caso.addItem(etiqueta, userData=seleccionar)
            self._cmb_caso.setCurrentIndex(1)
        else:
            self._cmb_caso.setCurrentIndex(0)

        self._cmb_caso.blockSignals(False)

        caso_sel = self._current_caso_path()
        if caso_sel is not None:
            self._sync_materia_a_caso(caso_sel)
        materia = self._current_materia_slug()
        labels = slot_labels_for(materia)
        for key, card in self._slot_cards.items():
            card._title.setText(labels.get(key, key))
        self._refresh_plantillas()
        self._refresh_bibliografia()
        self._refresh_slots()
        self._auto_meta()

    def _sync_materia_a_caso(self, caso: Path):
        """Ajusta el combo de Materia a la materia del caso, sin re-disparar señales."""
        mat = self._materia_de_path(caso)
        if mat == self._current_materia_slug():
            return
        self._cmb_materia.blockSignals(True)
        for i in range(self._cmb_materia.count()):
            if self._cmb_materia.itemData(i) == mat:
                self._cmb_materia.setCurrentIndex(i)
                break
        self._cmb_materia.blockSignals(False)

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
        self._update_ver_resolucion_btn(caso)

    def _update_ver_resolucion_btn(self, caso: "Path | None"):
        """Muestra botones de revisión si el caso ya tiene .docx o proceso guardado."""
        docx_files = []
        if caso:
            out_dir = BASE_DIR / "outputs" / caso.name
            if out_dir.is_dir():
                docx_files = sorted(out_dir.glob("*.docx"), key=lambda p: p.stat().st_mtime, reverse=True)
        self._btn_ver_resolucion.setVisible(bool(docx_files))
        if docx_files:
            self._btn_ver_resolucion.setProperty("_docx_files", [str(p) for p in docx_files])
            n = len(docx_files)
            self._btn_ver_resolucion.setToolTip("\n".join(p.name for p in docx_files[:5]))
            self._btn_ver_resolucion.setText(f"📄  Abrir .docx{' (' + str(n) + ')' if n > 1 else ''}")
        # El botón "Ver proceso" aparece si hay proceso guardado (.md en proceso/)
        # o, como heurística para casos previos, si hay un .docx generado.
        hay_proceso = False
        if caso:
            try:
                from app.artifex.graph import has_proceso_guardado
                hay_proceso = has_proceso_guardado(caso.name)
            except Exception:
                hay_proceso = False
        self._btn_ver_proceso.setVisible(bool(docx_files) or hay_proceso)

    def _on_ver_resolucion_caso(self):
        """Abre la(s) resolución(es) generada(s) para el caso seleccionado."""
        paths = self._btn_ver_resolucion.property("_docx_files") or []
        if not paths:
            return
        if len(paths) == 1:
            QDesktopServices.openUrl(QUrl.fromLocalFile(paths[0]))
            return
        # Más de una: mostrar lista para elegir
        dlg = QDialog(self)
        dlg.setWindowTitle("📄  Resoluciones generadas para este caso")
        dlg.resize(560, 300)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(16, 16, 16, 12)
        lay.setSpacing(8)
        lay.addWidget(_lbl("Haz doble clic para abrir la resolución:", size=12))
        from datetime import datetime
        lista = QListWidget()
        lista.setStyleSheet(
            f"background:{_C['card']}; border:1px solid {_C['hair']};"
            f"border-radius:8px; font-size:12px; padding:4px;"
        )
        for p_str in paths:
            p = Path(p_str)
            ts = datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            item = QListWidgetItem(f"{p.name}   —   {ts}")
            item.setData(Qt.ItemDataRole.UserRole, p_str)
            lista.addItem(item)
        lay.addWidget(lista, 1)
        btn_row = QHBoxLayout()
        btn_abrir_carpeta = QPushButton("📁  Abrir carpeta")
        btn_abrir_carpeta.setStyleSheet(_BTN_GHOST)
        out_dir = str(Path(paths[0]).parent)
        btn_abrir_carpeta.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(out_dir))
        )
        btn_row.addWidget(btn_abrir_carpeta)
        btn_row.addStretch()
        btn_cerrar = QPushButton("Cerrar")
        btn_cerrar.setStyleSheet(_BTN_GHOST)
        btn_cerrar.clicked.connect(dlg.reject)
        btn_row.addWidget(btn_cerrar)
        lay.addLayout(btn_row)
        lista.itemDoubleClicked.connect(
            lambda item: (QDesktopServices.openUrl(QUrl.fromLocalFile(item.data(Qt.ItemDataRole.UserRole))), dlg.accept())
        )
        dlg.exec()

    def _on_ver_proceso_caso(self):
        """Pide al contenedor que cargue el proceso (hechos/fuentes/borrador) del caso."""
        caso = self._current_caso_path()
        if caso:
            self.ver_proceso.emit(str(caso))

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
        out_root = BASE_DIR / "outputs"
        default_dir = str(out_root) if out_root.exists() else str(BASE_DIR)
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Cargar borrador",
            default_dir,
            qt_open_filter(),
        )
        if path:
            self.cargar_borrador.emit(path)

    def _on_iniciar(self):
        caso_path = self._cmb_caso.currentData() or ""
        materia   = self._current_materia_slug()
        postura   = self._cmb_postura.currentData() or "confirmar"

        try:
            bib_files = [str(p) for p in list_bibliografia(materia)]
        except Exception:
            bib_files = []

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
            "resoluciones_estilo":    list(self._resoluciones_estilo),
            "bibliografia":           bib_files,
        })


# ── Pantalla 1: Checkpoint ① hechos ──────────────────────────────────────────

class _HechosScreen(QWidget):
    confirmar = pyqtSignal(str, str)   # (hechos, agravios) aprobados / editados
    volver    = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background: {_C['paper']};")
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 22, 28, 28)
        root.setSpacing(12)

        badge = _lbl("★  Control del juez ①", bold=True, size=12, color=_C["gold_d"])
        badge.setStyleSheet(
            f"color: {_C['gold_d']}; background: {_C['gold_s']}; "
            f"border: 1px solid {_C['gold']}; border-radius: 8px; "
            f"padding: 4px 12px; font-size: 12px; font-weight: 700;"
        )
        root.addWidget(badge)

        root.addWidget(_lbl("Hechos y problema jurídico", bold=True, size=22))
        root.addWidget(_lbl(
            "El sistema extrajo dos cosas de los documentos: los hechos del caso y los "
            "agravios del recurso. Revise y corrija ambos — el problema jurídico determina "
            "qué jurisprudencia buscará el sistema.",
            color=_C["ink2"],
        ))

        # ── Editor superior: hechos ──
        root.addWidget(_lbl("Resumen de hechos", bold=True, size=13, color=_C["teal_d"]))
        self._editor_hechos = QPlainTextEdit()
        self._editor_hechos.setStyleSheet(
            _INPUT_SS + "QPlainTextEdit { min-height: 160px; max-height: 260px; }"
        )
        self._editor_hechos.setPlaceholderText("El sistema llenará este campo automáticamente…")
        root.addWidget(self._editor_hechos, 2)

        # ── Editor inferior: problema jurídico / agravios ──
        hdr_row = QHBoxLayout()
        lbl_agr = _lbl("Problema jurídico del recurso (agravios)", bold=True, size=13,
                       color=_C["gold_d"])
        hdr_row.addWidget(lbl_agr)
        hdr_row.addStretch()
        tip = _lbl("⚡ Este campo guía la búsqueda RAG", size=10, color=_C["faint"])
        tip.setStyleSheet(f"color: {_C['faint']}; font-size: 10px;")
        hdr_row.addWidget(tip)
        root.addLayout(hdr_row)

        self._editor_agravios = QPlainTextEdit()
        self._editor_agravios.setStyleSheet(
            _INPUT_SS + f"QPlainTextEdit {{ min-height: 120px; max-height: 200px;"
            f" border-color: {_C['gold']}; }}"
        )
        self._editor_agravios.setPlaceholderText(
            "Los agravios específicos que plantea el apelante (qué cuestiona y por qué)…"
        )
        root.addWidget(self._editor_agravios, 1)

        root.addWidget(_lbl(
            "✎  Edite directamente. Su versión corregida es la que avanza al RAG.",
            color=_C["faint"], size=11,
        ))

        self._review_banner = _lbl(
            "📌  Modo revisión — solo lectura. Los cambios aquí no afectan la resolución ya generada.",
            color="#7a5700", size=11,
        )
        self._review_banner.setWordWrap(True)
        self._review_banner.setStyleSheet(
            "background: #fff8e1; border: 1px solid #f0c060; border-radius: 8px; "
            "padding: 6px 12px; font-size: 11px;"
        )
        self._review_banner.setVisible(False)
        root.addWidget(self._review_banner)

        btn_row = QWidget()
        br = QHBoxLayout(btn_row)
        br.setContentsMargins(0, 0, 0, 0)
        volver_btn = QPushButton("←  Volver")
        volver_btn.setStyleSheet(_BTN_GHOST)
        volver_btn.clicked.connect(self.volver)
        br.addWidget(volver_btn)
        br.addStretch()
        self._cont_btn = QPushButton("Confirmar y continuar  →")
        self._cont_btn.setStyleSheet(_BTN_GOLD)
        self._cont_btn.clicked.connect(self._on_confirmar)
        br.addWidget(self._cont_btn)
        root.addWidget(btn_row)

    def _on_confirmar(self):
        self.confirmar.emit(
            self._editor_hechos.toPlainText(),
            self._editor_agravios.toPlainText(),
        )

    def set_texto(self, hechos: str, agravios: str = ""):
        self._editor_hechos.setPlainText(hechos)
        self._editor_agravios.setPlainText(agravios)

    def set_review_mode(self, enabled: bool):
        self._review_banner.setVisible(enabled)
        self._editor_hechos.setReadOnly(enabled)
        self._editor_agravios.setReadOnly(enabled)
        if enabled:
            self._cont_btn.setText("Ver fuentes  →")
            self._cont_btn.setStyleSheet(_BTN_GHOST)
        else:
            self._cont_btn.setText("Confirmar y continuar  →")
            self._cont_btn.setStyleSheet(_BTN_GOLD)


# ── Pantalla 2: Checkpoint ② fuentes ─────────────────────────────────────────

class _FuentesScreen(QWidget):
    aprobar    = pyqtSignal(str)   # texto final de fuentes (solo las marcadas)
    volver     = pyqtSignal()
    buscar_web = pyqtSignal(str)   # disparar búsqueda web jurídica con el término editado

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

        # ── Fila de búsqueda web (término editable) ──────────────────────────
        search_row = QWidget()
        sr = QHBoxLayout(search_row)
        sr.setContentsMargins(0, 0, 0, 0)
        sr.setSpacing(8)
        sr.addWidget(_lbl("🔎 Buscar:", bold=True, size=12))
        self._inp_web = QLineEdit()
        self._inp_web.setPlaceholderText(
            "Términos de búsqueda (déjalo vacío y extraigo las palabras clave del caso) "
            "— jurisprudencia, casación, acuerdo plenario, TC, doctrina…"
        )
        self._inp_web.returnPressed.connect(self._emit_buscar_web)
        sr.addWidget(self._inp_web, 1)
        self._btn_web = QPushButton("🔎  Buscar en la web")
        self._btn_web.setStyleSheet(_BTN_SAGE)
        self._btn_web.setToolTip(
            "Busca en la web jurisprudencia, casaciones, acuerdos plenarios, sentencias "
            "del TC y doctrina/libros relacionados. Los resultados se agregan abajo, "
            "verificables y seleccionables."
        )
        self._btn_web.clicked.connect(self._emit_buscar_web)
        sr.addWidget(self._btn_web)
        root.addWidget(search_row)

        self._list_container = QWidget()
        self._list_container.setStyleSheet("background: transparent;")
        self._list_lay = QVBoxLayout(self._list_container)
        self._list_lay.setContentsMargins(0, 0, 0, 0)
        self._list_lay.setSpacing(8)

        scroll = _scroll(self._list_container)
        root.addWidget(scroll, 1)

        self._review_banner_f = _lbl(
            "📌  Modo revisión — solo lectura. Los cambios aquí no afectan la resolución ya generada.",
            color="#7a5700", size=11,
        )
        self._review_banner_f.setWordWrap(True)
        self._review_banner_f.setStyleSheet(
            "background: #fff8e1; border: 1px solid #f0c060; border-radius: 8px; "
            "padding: 6px 12px; font-size: 11px;"
        )
        self._review_banner_f.setVisible(False)
        root.addWidget(self._review_banner_f)

        btn_row = QWidget()
        br = QHBoxLayout(btn_row)
        br.setContentsMargins(0, 0, 0, 0)
        volver_btn = QPushButton("←  Volver")
        volver_btn.setStyleSheet(_BTN_GHOST)
        volver_btn.clicked.connect(self.volver)
        br.addWidget(volver_btn)
        br.addStretch()
        self._apr_btn = QPushButton("Aprobar fuentes y redactar  →")
        self._apr_btn.setStyleSheet(_BTN_GOLD)
        self._apr_btn.clicked.connect(self._on_aprobar)
        br.addWidget(self._apr_btn)
        root.addWidget(btn_row)
        self._web_n = 0

    def _emit_buscar_web(self):
        self.buscar_web.emit(self._inp_web.text().strip())

    def mostrar_query_usada(self, query: str):
        """Muestra en el campo los términos que se buscaron (las keywords destiladas),
        para que el juez vea qué se buscó y pueda refinar la siguiente búsqueda."""
        if query:
            self._inp_web.setText(query.strip())

    def set_busy_web(self, busy: bool):
        self._btn_web.setEnabled(not busy)
        self._inp_web.setEnabled(not busy)
        self._btn_web.setText("⏳  Buscando…" if busy else "🔎  Buscar en la web")

    def append_busqueda_web(self, texto: str):
        """Anexa los resultados de una búsqueda web como una sección plegable nueva,
        sin tocar las fuentes ya listadas ni su selección."""
        if not texto or not texto.strip():
            return
        items: list[tuple[str, bool]] = []
        for bloque in texto.split("\n\n"):
            b = bloque.strip()
            if b.startswith("•"):
                cuerpo = b.lstrip("• ").strip()
                if cuerpo:
                    items.append((cuerpo, True))
        if not items:
            return
        # Quitar el stretch final (último item del layout) para insertar antes de él.
        last = self._list_lay.count() - 1
        if last >= 0 and self._list_lay.itemAt(last).spacerItem() is not None:
            self._list_lay.takeAt(last)
        self._web_n += 1
        self._add_seccion_plegable(f"🔎 BÚSQUEDA WEB {self._web_n}", items)
        self._list_lay.addStretch()

    def set_review_mode(self, enabled: bool):
        self._review_banner_f.setVisible(enabled)
        for cb, _ in self._checks:
            cb.setEnabled(not enabled)
        # La búsqueda web sigue disponible en revisión: solo anexa resultados al
        # panel (con 🔗 para abrir cada fuente), no re-dispara el grafo terminado.
        self._btn_web.setVisible(True)
        if enabled:
            self._apr_btn.setText("Ver borrador  →")
            self._apr_btn.setStyleSheet(_BTN_GHOST)
        else:
            self._apr_btn.setText("Aprobar fuentes y redactar  →")
            self._apr_btn.setStyleSheet(_BTN_GOLD)

    def _clear_list(self):
        while self._list_lay.count():
            item = self._list_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._checks.clear()
        self._web_n = 0

    def set_fuentes_raw(self, texto: str):
        """Fallback: muestra TODO el texto de fuentes como un único ítem seleccionable,
        sin parsear. Se usa si el parser estructurado falla, para no bloquear el avance."""
        self._clear_list()
        self._add_seccion_plegable("Fuentes (texto completo)", [(texto.strip(), False)])
        self._list_lay.addStretch()

    def set_fuentes(self, texto: str):
        while self._list_lay.count():
            item = self._list_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._checks.clear()
        self._web_n = 0

        # El texto de fuentes es Markdown estructurado:
        #   ##  sección principal      (## (A) NORMAS, ## (B) JURISPRUDENCIA, …)
        #   ### subsección             (### A.1. Norma Penal, ### B.1. Valoración…)
        #   **Título**                 fundamento (artículo, casación, doctrina)
        #   párrafos / > citas / - viñetas / *Aplica a:*   → CUERPO del fundamento
        #   •                          ítem de búsqueda en vivo (con URL)
        # Cada FUNDAMENTO (título en negrita + todo su cuerpo) es UN ítem seleccionable,
        # agrupado en su sección principal. Así no se fragmenta el contenido.
        import re as _re_src
        items: list[tuple[str, str, bool]] = []   # (sección_principal, texto, en_vivo)
        seccion_princ = ""
        subseccion = ""
        current: str | None = None
        current_sec = ""

        re_titulo_bold = _re_src.compile(r"^\*\*(.+?)\*\*:?\s*$")

        def _limpiar_md(t: str) -> str:
            """Quita símbolos de énfasis Markdown (**, *, `, >, #) para mostrar texto limpio."""
            t = _re_src.sub(r"\*\*(.+?)\*\*", r"\1", t)
            t = _re_src.sub(r"`([^`]+)`", r"\1", t)
            t = t.replace("**", "").replace("*", "").replace("`", "")
            return t.strip()

        def _push_item():
            nonlocal current
            if current and current.strip():
                items.append((current_sec, current.strip(), "[EN VIVO]" in current))
            current = None

        lineas = texto.splitlines()
        for i, linea in enumerate(lineas):
            raw = linea.rstrip()
            s = raw.strip()
            if not s:
                continue
            if _re_src.fullmatch(r"[-*_]{3,}", s):
                continue  # separador horizontal, ignorar
            m_h = _re_src.match(r"^(#+)\s*(.*)$", s)
            if m_h:
                _push_item()
                nivel = len(m_h.group(1))
                titulo = _limpiar_md(m_h.group(2).strip())
                if nivel <= 2:
                    seccion_princ = titulo or seccion_princ
                    subseccion = ""
                else:
                    subseccion = titulo
                continue
            # Fila de tabla Markdown: | celda | celda |  (E2 a veces tabula las fuentes).
            if s.startswith("|") and s.count("|") >= 2:
                if _re_src.fullmatch(r"\|[\s|:\-]+\|?", s):
                    continue  # fila separadora |---|---|
                # Cabecera de tabla: la fila siguiente no vacía es separadora → omitir.
                nxt = ""
                for j in range(i + 1, len(lineas)):
                    if lineas[j].strip():
                        nxt = lineas[j].strip()
                        break
                if _re_src.fullmatch(r"\|[\s|:\-]+\|?", nxt):
                    continue
                celdas = [c.strip() for c in s.strip("|").split("|")]
                celdas = [c for c in celdas if c]
                if not celdas:
                    continue
                _push_item()
                current_sec = seccion_princ
                cuerpo = _limpiar_md(" — ".join(celdas))
                current = (f"[{subseccion}] " if subseccion else "") + cuerpo
                _push_item()   # cada fila es un fundamento completo en sí mismo
                continue
            m_bold = re_titulo_bold.match(s)
            es_numerado = bool(_re_src.match(r"^\d{1,3}[.)]\s", s))
            es_vineta_live = s[:1] == "•"
            if m_bold or es_numerado or es_vineta_live:
                # Inicio de un fundamento nuevo (título en negrita, numeral, o ítem en vivo).
                _push_item()
                current_sec = seccion_princ
                if m_bold:
                    cuerpo = _limpiar_md(m_bold.group(1).strip())
                else:
                    cuerpo = _limpiar_md(
                        _re_src.sub(r"^\d{1,3}[.)]\s*", "", s).lstrip("•-* ").strip()
                    )
                current = (f"[{subseccion}] " if subseccion else "") + cuerpo
            else:
                # Cuerpo del fundamento: párrafo, cita (>), viñeta (-) o "Aplica a:".
                detalle = s.lstrip(">").strip().lstrip("•-* ").strip()
                detalle = _limpiar_md(detalle)
                if not detalle:
                    continue
                if current:
                    current += " — " + detalle
                else:
                    current_sec = seccion_princ
                    current = (f"[{subseccion}] " if subseccion else "") + detalle
        _push_item()

        if not items:
            items = [("", _limpiar_md(texto.strip()), False)]

        # Agrupar por sección principal, preservando el orden de aparición.
        orden: list[str] = []
        grupos: dict[str, list[tuple[str, bool]]] = {}
        for sec, text, is_live in items:
            sec = sec or "Fundamentos"
            if sec not in grupos:
                grupos[sec] = []
                orden.append(sec)
            grupos[sec].append((text, is_live))

        for sec in orden:
            self._add_seccion_plegable(sec, grupos[sec])

        self._list_lay.addStretch()

    def _add_seccion_plegable(self, titulo: str, rows_data: list[tuple[str, bool]]):
        """Bloque plegable: encabezado clicable (▼/▶) + ítems de la sección."""
        cont = QWidget()
        cont.setStyleSheet("background: transparent;")
        cl = QVBoxLayout(cont)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(6)

        n = len(rows_data)
        titulo_disp = titulo if len(titulo) <= 60 else titulo[:57] + "…"
        header = QPushButton(f"▼  {titulo_disp}   ·   {n}")
        header.setCheckable(True)
        header.setChecked(True)
        header.setCursor(Qt.CursorShape.PointingHandCursor)
        if len(titulo) > 60:
            header.setToolTip(titulo)
        header.setStyleSheet(
            f"QPushButton {{ background: {_C['teal_s']}; color: {_C['teal_d']}; "
            f"border: 1px solid {_C['hair']}; border-radius: 9px; padding: 9px 14px; "
            f"font-size: 12px; font-weight: 700; text-align: left; }}"
            f"QPushButton:hover {{ background: {_C['gold_s']}; }}"
        )
        cl.addWidget(header)

        body = QWidget()
        body.setStyleSheet("background: transparent;")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(10, 0, 0, 0)
        bl.setSpacing(8)
        for text, is_live in rows_data:
            if text:
                bl.addWidget(self._build_fuente_row(text, is_live))
        cl.addWidget(body)

        def _toggle(checked: bool):
            body.setVisible(checked)
            header.setText(f"{'▼' if checked else '▶'}  {titulo_disp}   ·   {n}")
        header.toggled.connect(_toggle)

        self._list_lay.addWidget(cont)

    def _build_fuente_row(self, text: str, is_live: bool) -> QWidget:
        """Construye una tarjeta de fuente (checkbox + texto + tag + 🔗/👁) y la registra."""
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
        txt_w.setStyleSheet("border: none;")
        tl = QVBoxLayout(txt_w)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(2)
        display = text[:220] + "…" if len(text) > 220 else text
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

        # Ítems "en vivo": botón 🔗 para abrir y verificar la fuente.
        if is_live:
            import re as _re
            m = _re.search(r"https?://\S+", text)
            if m:
                url = m.group(0).rstrip(".,;)")
                btn_link = QPushButton("🔗")
                btn_link.setToolTip(f"Abrir y verificar la fuente:\n{url}")
                btn_link.setFixedWidth(32)
                btn_link.setStyleSheet(_BTN_SMALL_GHOST)
                btn_link.clicked.connect(
                    lambda _, u=url: QDesktopServices.openUrl(QUrl(u))
                )
                rl.addWidget(btn_link)

        if len(text) > 220:
            btn_ver = QPushButton("👁")
            btn_ver.setToolTip("Ver texto completo")
            btn_ver.setFixedWidth(32)
            btn_ver.setStyleSheet(_BTN_SMALL_GHOST)
            btn_ver.clicked.connect(lambda _, t=text: self._ver_fuente_completa(t))
            rl.addWidget(btn_ver)

        self._checks.append((cb, text))
        return row

    def _ver_fuente_completa(self, texto: str):
        dlg = QDialog(self)
        dlg.setWindowTitle("Fuente completa")
        dlg.resize(800, 520)
        dlg.setStyleSheet(f"background: {_C['paper']};")
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(16, 16, 16, 12)
        lay.setSpacing(8)
        txt = QTextEdit()
        txt.setPlainText(texto)
        txt.setReadOnly(True)
        txt.setStyleSheet(
            _INPUT_SS + "QTextEdit { font-size: 12px; line-height: 1.5; }"
        )
        lay.addWidget(txt, 1)
        btn_cerrar = QPushButton("Cerrar")
        btn_cerrar.setStyleSheet(_BTN_GHOST)
        btn_cerrar.clicked.connect(dlg.accept)
        lay.addWidget(btn_cerrar, alignment=Qt.AlignmentFlag.AlignRight)
        dlg.exec()

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

        self._review_banner_b = _lbl(
            "📌  Modo revisión — solo lectura. El borrador que se ve es el que se usó para generar el .docx.",
            color="#7a5700", size=11,
        )
        self._review_banner_b.setWordWrap(True)
        self._review_banner_b.setStyleSheet(
            "background: #fff8e1; border: 1px solid #f0c060; border-radius: 8px; "
            "padding: 6px 12px; font-size: 11px;"
        )
        self._review_banner_b.setVisible(False)
        root.addWidget(self._review_banner_b)

        btn_row = QWidget()
        br = QHBoxLayout(btn_row)
        br.setContentsMargins(0, 0, 0, 0)
        volver_btn = QPushButton("←  Volver")
        volver_btn.setStyleSheet(_BTN_GHOST)
        volver_btn.clicked.connect(self.volver)
        br.addWidget(volver_btn)
        br.addStretch()
        self._apr_btn_b = QPushButton("Aprobar y dar formato  →")
        self._apr_btn_b.setStyleSheet(_BTN_GOLD)
        self._apr_btn_b.clicked.connect(lambda: self.aprobar.emit(self._editor.toPlainText()))
        br.addWidget(self._apr_btn_b)
        root.addWidget(btn_row)

    def set_review_mode(self, enabled: bool):
        self._review_banner_b.setVisible(enabled)
        self._editor.setReadOnly(enabled)
        if enabled:
            self._apr_btn_b.setText("Ver resolución final  →")
            self._apr_btn_b.setStyleSheet(_BTN_GHOST)
            # Ocultar herramientas de edición en modo revisión
            self._btn_rewrite.setEnabled(False)
            self._btn_pulir.setEnabled(False)
        else:
            self._apr_btn_b.setText("Aprobar y dar formato  →")
            self._apr_btn_b.setStyleSheet(_BTN_GOLD)
            self._btn_rewrite.setEnabled(True)
            self._btn_pulir.setEnabled(True)

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
    reiniciar       = pyqtSignal()
    editar_borrador = pyqtSignal()   # (legado) volver al paso 3 para corregir y regenerar
    iterar          = pyqtSignal(str)  # pedir corrección/ampliación → se anexa al final

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

        self._exp_lbl = _lbl("", color=_C["ink2"], size=12)
        root.addWidget(self._exp_lbl)

        self._txt_resolucion = QTextEdit()
        self._txt_resolucion.setReadOnly(True)
        self._txt_resolucion.setPlaceholderText("El texto de la resolución generada aparecerá aquí.")
        self._txt_resolucion.setStyleSheet(
            f"background: {_C['card']}; border: 1px solid {_C['hair']}; "
            f"border-radius: 10px; padding: 14px; font-family: 'Courier New', monospace; font-size: 12px;"
        )
        root.addWidget(self._txt_resolucion, 1)

        # ── Panel de iteración: pedir corrección/ampliación (se anexa al final) ──
        self._iter_box = QWidget()
        self._iter_box.setStyleSheet(_PANEL_SS)
        ib = QVBoxLayout(self._iter_box)
        ib.setContentsMargins(16, 12, 16, 12)
        ib.setSpacing(8)
        ib.addWidget(_lbl(
            "Corregir o ampliar (sin tocar la resolución) — la respuesta se agrega al final del documento",
            bold=True, size=12,
        ))
        self._txt_instruccion = QPlainTextEdit()
        self._txt_instruccion.setPlaceholderText(
            "Ej.: «Amplía el considerando 7 con el test de proporcionalidad» o "
            "«Corrige el numeral 12: la fecha correcta es 14/03/2026». Puedes pedir "
            "cuantas iteraciones quieras; cada una se añade a continuación."
        )
        self._txt_instruccion.setFixedHeight(70)
        self._txt_instruccion.setStyleSheet(_INPUT_SS + "QPlainTextEdit { font-size: 12px; }")
        ib.addWidget(self._txt_instruccion)
        ib_btns = QHBoxLayout()
        ib_btns.addStretch()
        self._btn_iterar = QPushButton("➕  Pedir corrección / ampliación")
        self._btn_iterar.setStyleSheet(_BTN_SAGE)
        self._btn_iterar.setToolTip(
            "Envía la instrucción; la respuesta se anexa al final del documento "
            "(la resolución ya generada no se modifica). Iteración ilimitada."
        )
        self._btn_iterar.clicked.connect(self._on_iterar_click)
        self._btn_iterar.setEnabled(False)
        ib_btns.addWidget(self._btn_iterar)
        ib.addLayout(ib_btns)
        root.addWidget(self._iter_box)

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

    def set_docx(self, path: str, expediente: str = "", borrador: str = "", can_edit: bool = False):
        self._docx_path = path
        if path:
            p = Path(path)
            self._docx_lbl.setText(f"Archivo generado: {p.name}")
            self._docx_lbl.setStyleSheet(f"color: {_C['teal_d']}; font-size: 12px;")
            self._btn_dl.setEnabled(True)
            self._btn_abrir.setEnabled(True)
        if expediente:
            self._exp_lbl.setText(f"Expediente N.° {expediente}")
        if borrador:
            self._txt_resolucion.setPlainText(borrador)
        self._btn_iterar.setEnabled(can_edit)

    def _on_iterar_click(self):
        instr = self._txt_instruccion.toPlainText().strip()
        if not instr:
            return
        self.set_busy_iter(True)
        self.iterar.emit(instr)

    def set_busy_iter(self, busy: bool):
        self._btn_iterar.setEnabled(not busy)
        self._btn_iterar.setText(
            "⏳  Procesando…" if busy else "➕  Pedir corrección / ampliación"
        )

    def iteracion_terminada(self, texto_completo: str):
        """Refresca la vista con el documento ya extendido y limpia el campo."""
        self._txt_resolucion.setPlainText(texto_completo)
        self._txt_instruccion.clear()
        self.set_busy_iter(False)
        # Llevar el scroll al final para ver lo recién anexado.
        cur = self._txt_resolucion.textCursor()
        cur.movePosition(QTextCursor.MoveOperation.End)
        self._txt_resolucion.setTextCursor(cur)

    def _abrir_docx(self):
        if self._docx_path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self._docx_path))

    def _abrir_carpeta(self):
        if self._docx_path:
            QDesktopServices.openUrl(
                QUrl.fromLocalFile(str(Path(self._docx_path).parent))
            )


# ── Selector de casos anteriores ─────────────────────────────────────────────

class _CasosAnterioresDialog(QDialog):
    """Lista todos los expedientes procesados. Al hacer doble-clic (o Abrir),
    emite la ruta del caso para que el Setup la cargue en el stepper."""

    caso_seleccionado = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Casos anteriores")
        self.resize(620, 480)
        self.setStyleSheet(f"background: {_C['paper']};")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 20, 20, 16)
        lay.setSpacing(10)

        lay.addWidget(_lbl("Selecciona un caso para abrirlo en el pipeline", bold=True, size=14))

        # Búsqueda
        self._inp_buscar = QLineEdit()
        self._inp_buscar.setPlaceholderText("Buscar por nombre…")
        self._inp_buscar.setStyleSheet(_INPUT_SS)
        self._inp_buscar.textChanged.connect(self._filtrar)
        lay.addWidget(self._inp_buscar)

        # Lista
        self._lista = QListWidget()
        self._lista.setStyleSheet(
            f"QListWidget {{ background: {_C['card']}; border: 1px solid {_C['hair']}; "
            f"border-radius: 10px; padding: 4px; font-size: 13px; }}"
            f"QListWidget::item {{ padding: 10px 14px; border-radius: 8px; }}"
            f"QListWidget::item:selected {{ background: {_C['gold_s']}; color: {_C['gold_d']}; }}"
            f"QListWidget::item:hover {{ background: {_C['panel2']}; }}"
        )
        self._lista.itemDoubleClicked.connect(self._on_abrir)
        lay.addWidget(self._lista, 1)

        btn_row = QHBoxLayout()
        btn_cerrar = QPushButton("Cancelar")
        btn_cerrar.setStyleSheet(_BTN_GHOST)
        btn_cerrar.clicked.connect(self.reject)
        btn_row.addWidget(btn_cerrar)
        btn_row.addStretch()
        self._btn_abrir = QPushButton("Abrir caso  →")
        self._btn_abrir.setStyleSheet(_BTN_GOLD)
        self._btn_abrir.setEnabled(False)
        self._btn_abrir.clicked.connect(self._on_abrir)
        btn_row.addWidget(self._btn_abrir)
        lay.addLayout(btn_row)

        self._lista.currentItemChanged.connect(
            lambda cur, _: self._btn_abrir.setEnabled(cur is not None)
        )

        self._cargar_casos()

    def _cargar_casos(self):
        self._lista.clear()
        try:
            carpetas = list_case_folders(None)
        except Exception:
            return
        # Agrupar por materia
        grupos: dict[str, list[Path]] = {}
        for p in carpetas:
            mat = p.parts[p.parts.index("01_raw") + 1] if "01_raw" in p.parts else "otros"
            grupos.setdefault(mat, []).append(p)

        for mat, casos in sorted(grupos.items()):
            mat_label = MATERIA_LABELS.get(mat, mat)
            hdr = QListWidgetItem(f"── {mat_label} ──")
            hdr.setFlags(Qt.ItemFlag.NoItemFlags)
            hdr.setForeground(QColor(_C["faint"]))
            self._lista.addItem(hdr)
            for caso in sorted(casos, key=lambda p: p.name, reverse=True):
                item = QListWidgetItem(f"  {caso.name}")
                item.setData(Qt.ItemDataRole.UserRole, str(caso))
                self._lista.addItem(item)

    def _filtrar(self, texto: str):
        texto = texto.lower().strip()
        for i in range(self._lista.count()):
            item = self._lista.item(i)
            path = item.data(Qt.ItemDataRole.UserRole)
            if not path:
                item.setHidden(False)
                continue
            item.setHidden(texto != "" and texto not in item.text().lower())

    def _on_abrir(self, *_):
        item = self._lista.currentItem()
        if item is None:
            return
        path = item.data(Qt.ItemDataRole.UserRole)
        if not path:
            return
        self.caso_seleccionado.emit(path)
        self.accept()


# ── Adiutor Iudicis 1 — modo clásico (prompt único) ──────────────────────────

class _AdiutorUnoDialog(QDialog):
    """Genera la resolución con un solo prompt, sin checkpoints (sistema clásico).

    Toma el cfg del caso ya configurado en la Setup screen, construye el prompt
    exactamente como lo hacía Adiutor 1 (build_enriched_prompt + ClaudeWorker),
    muestra el texto en streaming y exporta a .docx al terminar.
    """

    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Adiutor Iudicis 1 — Modo clásico")
        self.resize(860, 640)
        self.setStyleSheet(f"background: {_C['paper']};")
        self._cfg = cfg
        self._worker = None
        self._texto_acumulado = ""

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 20, 20, 16)
        lay.setSpacing(12)

        # Encabezado
        hdr = QHBoxLayout()
        titulo = _lbl("⚡  Adiutor Iudicis 1", bold=True, size=16)
        titulo.setStyleSheet(f"color: {_C['ink']}; font-weight: 700; font-size: 16px;")
        hdr.addWidget(titulo)
        hdr.addStretch()
        caso_nombre = Path(cfg.get("caso_path", "")).name
        hdr.addWidget(_lbl(caso_nombre, color=_C["faint"], size=11))
        lay.addLayout(hdr)

        lay.addWidget(_lbl(
            "Generando resolución con un solo prompt — sin checkpoints, sin pipeline.",
            color=_C["ink2"], size=12,
        ))

        # Status
        self._status_lbl = _lbl("Preparando…", color=_C["faint"], size=11)
        lay.addWidget(self._status_lbl)

        # Editor de streaming
        self._editor = QPlainTextEdit()
        self._editor.setReadOnly(True)
        self._editor.setStyleSheet(
            _INPUT_SS + "QPlainTextEdit { font-size: 12px; font-family: monospace; }"
        )
        lay.addWidget(self._editor, 1)

        # Botones
        btn_row = QHBoxLayout()
        self._btn_cancelar = QPushButton("Cancelar")
        self._btn_cancelar.setStyleSheet(_BTN_GHOST)
        self._btn_cancelar.clicked.connect(self._on_cancelar)
        btn_row.addWidget(self._btn_cancelar)
        btn_row.addStretch()
        self._btn_exportar = QPushButton("📄  Exportar .docx")
        self._btn_exportar.setStyleSheet(_BTN_GOLD)
        self._btn_exportar.setEnabled(False)
        self._btn_exportar.clicked.connect(self._on_exportar)
        btn_row.addWidget(self._btn_exportar)
        lay.addLayout(btn_row)

        # Arrancar generación al abrir
        QTimer.singleShot(100, self._iniciar_generacion)

    def _iniciar_generacion(self):
        from app.core.env_load import load_repo_dotenv
        from app.core.claude_worker import ClaudeWorker
        from app.core.file_manager import (
            read_fuentes_slots,
            read_instruccion_general,
            slot_labels_for,
            materia_label as ml,
        )
        from app.artifex.nodes import _prompt_kwargs_from_state
        from app.artifex.state import CasoState, Postura

        load_repo_dotenv()
        cfg = self._cfg
        materia = cfg.get("materia", "")
        caso_folder = Path(cfg.get("caso_path", ""))

        postura_map = {
            "confirmar":       Postura.CONFIRMAR,
            "revocar":         Postura.REVOCAR,
            "revocar_parcial": Postura.REVOCAR_PARCIAL,
            "personalizado":   Postura.PERSONALIZADO,
        }
        postura = postura_map.get(cfg.get("postura", "confirmar"), Postura.CONFIRMAR)

        try:
            slots = read_fuentes_slots(caso_folder)
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
                resoluciones_estilo=[Path(p) for p in cfg.get("resoluciones_estilo", [])],
                bibliografia=[Path(p) for p in cfg.get("bibliografia", [])],
            )
        except Exception as e:
            self._status_lbl.setText(f"Error al preparar el caso: {e}")
            return

        task = {"prompt_kwargs": _prompt_kwargs_from_state(state)}
        self._worker = ClaudeWorker(task, parent=self)
        self._worker.chunk_ready.connect(self._on_chunk)
        self._worker.status.connect(lambda msg: self._status_lbl.setText(msg))
        self._worker.finished.connect(self._on_terminado)
        self._worker.error_occurred.connect(self._on_error)
        self._worker.start()

    def _on_chunk(self, texto: str):
        self._texto_acumulado += texto
        self._editor.setPlainText(self._texto_acumulado)
        sb = self._editor.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _on_terminado(self):
        self._status_lbl.setText("✓ Resolución generada. Puedes exportar a .docx.")
        self._btn_cancelar.setText("Cerrar")
        self._btn_exportar.setEnabled(True)
        self._worker = None

    def _on_error(self, msg: str):
        self._status_lbl.setText(f"Error: {msg}")
        self._btn_cancelar.setText("Cerrar")
        self._worker = None

    def _on_cancelar(self):
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(2000)
        self.reject()

    def _on_exportar(self):
        from app.core.word_export import text_to_docx_faithful
        from app.core.file_manager import BASE_DIR

        caso_folder = Path(self._cfg.get("caso_path", ""))
        out_dir = BASE_DIR / "outputs" / caso_folder.name
        out_dir.mkdir(parents=True, exist_ok=True)

        from datetime import datetime
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        docx_path = out_dir / f"adiutor1_{caso_folder.name}_{ts}.docx"

        try:
            text_to_docx_faithful(self._texto_acumulado, str(docx_path))
            self._status_lbl.setText(f"✓ Exportado: {docx_path.name}")
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(docx_path)))
        except Exception as e:
            self._status_lbl.setText(f"Error al exportar: {e}")

    def closeEvent(self, event):
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(2000)
        super().closeEvent(event)


# ── Historial de casos ────────────────────────────────────────────────────────

class _HistorialDialog(QDialog):
    """Panel de historial de casos procesados.

    Lista todos los expedientes en 01_raw/<materia>/caso_* ordenados por fecha.
    Muestra si existe resolución .md generada y/o proceso guardado. Permite abrir
    la carpeta en Finder, ver la resolución, o reabrir el proceso (hechos →
    fuentes → borrador → resolución) en el stepper en modo revisión.
    """

    ver_proceso = pyqtSignal(str)   # emite el path del caso para revisar su proceso

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Historial de expedientes")
        self.resize(820, 580)
        self.setStyleSheet(f"background: {_C['paper']};")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 14)
        lay.setSpacing(10)

        lay.addWidget(_lbl("Historial de expedientes", bold=True, size=15))
        lay.addWidget(_lbl(
            "Todos los expedientes en 01_raw/, más reciente primero. "
            "Verde = resolución generada. Gris = pendiente.",
            color=_C["faint"], size=11,
        ))
        lay.addWidget(_sep())

        # Filtro por materia
        filter_row = QHBoxLayout()
        filter_row.addWidget(_lbl("Materia:", size=12))
        self._combo_materia = _NoScrollComboBox()
        self._combo_materia.setStyleSheet(_INPUT_SS)
        self._combo_materia.addItem("Todas las materias", userData=None)
        for slug, label in sorted(MATERIA_LABELS.items(), key=lambda x: x[1]):
            self._combo_materia.addItem(label, userData=slug)
        filter_row.addWidget(self._combo_materia, 1)
        btn_refresh = QPushButton("⟳ Actualizar")
        btn_refresh.setStyleSheet(_BTN_SMALL_GHOST)
        btn_refresh.clicked.connect(self._reload)
        filter_row.addWidget(btn_refresh)
        lay.addLayout(filter_row)

        # Lista de casos
        self._list = QListWidget()
        self._list.setStyleSheet(
            f"QListWidget {{ background: {_C['card']}; border: 1px solid {_C['hair']}; "
            f"border-radius: 10px; font-size: 12px; }}"
            f"QListWidget::item {{ padding: 8px 12px; border-bottom: 1px solid {_C['hair']}; }}"
            f"QListWidget::item:selected {{ background: {_C['teal_s']}; color: {_C['teal_d']}; }}"
        )
        self._list.currentRowChanged.connect(self._on_sel_changed)
        lay.addWidget(self._list, 1)

        # Panel de info del caso seleccionado
        self._info_lbl = _lbl("Selecciona un expediente para ver detalles.", color=_C["faint"], size=11)
        lay.addWidget(self._info_lbl)

        # Botones de acción
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._btn_abrir_carpeta = QPushButton("📂  Abrir carpeta")
        self._btn_abrir_carpeta.setStyleSheet(_BTN_GHOST)
        self._btn_abrir_carpeta.setEnabled(False)
        self._btn_abrir_carpeta.clicked.connect(self._on_abrir_carpeta)
        btn_row.addWidget(self._btn_abrir_carpeta)
        self._btn_ver_proceso = QPushButton("🔍  Ver proceso")
        self._btn_ver_proceso.setStyleSheet(_BTN_GHOST)
        self._btn_ver_proceso.setEnabled(False)
        self._btn_ver_proceso.setToolTip("Reabre el proceso (hechos → fuentes → borrador) en el stepper.")
        self._btn_ver_proceso.clicked.connect(self._on_ver_proceso_click)
        btn_row.addWidget(self._btn_ver_proceso)
        self._btn_ver_resolucion = QPushButton("📄  Ver resolución")
        self._btn_ver_resolucion.setStyleSheet(_BTN_PRIMARY)
        self._btn_ver_resolucion.setEnabled(False)
        self._btn_ver_resolucion.clicked.connect(self._on_ver_resolucion)
        btn_row.addWidget(self._btn_ver_resolucion)
        btn_cerrar = QPushButton("Cerrar")
        btn_cerrar.setStyleSheet(_BTN_GHOST)
        btn_cerrar.clicked.connect(self.accept)
        btn_row.addWidget(btn_cerrar)
        lay.addLayout(btn_row)

        self._combo_materia.currentIndexChanged.connect(self._reload)
        self._folders: list[Path] = []
        self._reload()

    def _reload(self):
        materia = self._combo_materia.currentData()
        try:
            self._folders = list_case_folders(materia=materia)
        except Exception:
            self._folders = []

        self._list.clear()
        for folder in self._folders:
            # Inferir materia del path
            from app.core.file_manager import MATERIA_LABELS as _ML, BASE_DIR as _BD
            try:
                rel = folder.relative_to(_BD / "01_raw")
                mat_slug = rel.parts[0] if len(rel.parts) > 1 else ""
            except Exception:
                mat_slug = ""
            mat_lbl = _ML.get(mat_slug, mat_slug.replace("_", " ").capitalize()) if mat_slug else "—"

            # Estado de resolución
            from app.core.file_manager import find_resolucion_md_for_case
            res_md = find_resolucion_md_for_case(folder, mat_slug) if mat_slug else None
            estado = "✓  resolución" if res_md else "○  pendiente"

            # Fecha de modificación
            try:
                from datetime import datetime
                mtime = folder.stat().st_mtime
                fecha = datetime.fromtimestamp(mtime).strftime("%d/%m/%Y")
            except Exception:
                fecha = "—"

            item = QListWidgetItem(
                f"  {folder.name}  ·  {mat_lbl}  ·  {fecha}  ·  {estado}"
            )
            if res_md:
                item.setForeground(QColor(_C["teal_d"]))
            else:
                item.setForeground(QColor(_C["faint"]))
            self._list.addItem(item)

        count = len(self._folders)
        self._info_lbl.setText(
            f"{count} expediente(s) encontrado(s)." if count else "No hay expedientes en 01_raw/."
        )
        self._btn_abrir_carpeta.setEnabled(False)
        self._btn_ver_resolucion.setEnabled(False)

    def _on_sel_changed(self, row: int):
        ok = 0 <= row < len(self._folders)
        self._btn_abrir_carpeta.setEnabled(ok)
        if not ok:
            self._info_lbl.setText("Selecciona un expediente para ver detalles.")
            self._btn_ver_resolucion.setEnabled(False)
            return

        folder = self._folders[row]
        from app.core.file_manager import MATERIA_LABELS as _ML, BASE_DIR as _BD, find_resolucion_md_for_case
        try:
            rel = folder.relative_to(_BD / "01_raw")
            mat_slug = rel.parts[0] if len(rel.parts) > 1 else ""
        except Exception:
            mat_slug = ""
        mat_lbl = _ML.get(mat_slug, "—")
        res_md = find_resolucion_md_for_case(folder, mat_slug) if mat_slug else None

        files = list(folder.rglob("*")) if folder.is_dir() else []
        n_files = sum(1 for f in files if f.is_file())
        info = (
            f"{folder.name}  ·  {mat_lbl}  ·  {n_files} archivo(s)"
            + (f"  ·  Resolución: {res_md.name}" if res_md else "  ·  Sin resolución generada")
        )
        # ¿Hay proceso guardado (.md en outputs/<caso>/proceso/)?
        try:
            from app.artifex.graph import has_proceso_guardado
            hay_proceso = has_proceso_guardado(folder.name)
        except Exception:
            hay_proceso = False
        if hay_proceso:
            info += "  ·  Proceso disponible"
        self._info_lbl.setText(info)
        self._btn_ver_resolucion.setEnabled(res_md is not None)
        self._btn_ver_proceso.setEnabled(hay_proceso)

    def _on_ver_proceso_click(self):
        row = self._list.currentRow()
        if 0 <= row < len(self._folders):
            self.ver_proceso.emit(str(self._folders[row]))
            self.accept()

    def _on_abrir_carpeta(self):
        row = self._list.currentRow()
        if 0 <= row < len(self._folders):
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._folders[row])))

    def _on_ver_resolucion(self):
        row = self._list.currentRow()
        if not (0 <= row < len(self._folders)):
            return
        folder = self._folders[row]
        from app.core.file_manager import MATERIA_LABELS as _ML, BASE_DIR as _BD, find_resolucion_md_for_case
        try:
            rel = folder.relative_to(_BD / "01_raw")
            mat_slug = rel.parts[0] if len(rel.parts) > 1 else ""
        except Exception:
            mat_slug = ""
        res_md = find_resolucion_md_for_case(folder, mat_slug) if mat_slug else None
        if not res_md:
            return
        texto = res_md.read_text(encoding="utf-8", errors="replace")
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Resolución — {folder.name}")
        dlg.resize(800, 640)
        dlg.setStyleSheet(f"background: {_C['paper']};")
        vl = QVBoxLayout(dlg)
        vl.setContentsMargins(16, 14, 16, 12)
        vl.addWidget(_lbl(res_md.name, bold=True, size=13))
        txt = QPlainTextEdit()
        txt.setPlainText(texto)
        txt.setReadOnly(True)
        txt.setStyleSheet(_INPUT_SS + "QPlainTextEdit { font-size: 11px; }")
        vl.addWidget(txt, 1)
        btn_abrir = QPushButton("Abrir en Finder")
        btn_abrir.setStyleSheet(_BTN_GHOST)
        btn_abrir.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(res_md.parent))))
        btn_ok = QPushButton("Cerrar")
        btn_ok.setStyleSheet(_BTN_PRIMARY)
        btn_ok.clicked.connect(dlg.accept)
        br = QHBoxLayout()
        br.addStretch()
        br.addWidget(btn_abrir)
        br.addWidget(btn_ok)
        vl.addLayout(br)
        dlg.exec()


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
        self._folder_name    = ""     # carpeta del caso en curso (para persistir el proceso a .md)
        self._iter_n         = 0      # nº de iteraciones (correcciones/ampliaciones) post-resolución
        self._iter_worker: _IterarWorker | None = None
        self._web_worker:  _BuscarWebWorker | None = None
        self._last_borrador  = ""     # texto del borrador para mostrarlo en pantalla final
        self._shortcut_state = None   # CasoState snapshot para modo "cargar borrador" o re-export post-pipeline
        self._review_mode    = False  # True tras generar la resolución: stepper navegable, sin re-disparar el grafo
        self._iterating      = False  # True cuando el juez edita el borrador post-generación para regenerar el .docx

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

        self._btn_adiutor1 = QPushButton("⚡  Adiutor Iudicis 1")
        self._btn_adiutor1.setStyleSheet(_BTN_GHOST)
        self._btn_adiutor1.setToolTip(
            "Modo clásico — genera la resolución completa con un solo prompt, "
            "sin checkpoints. Más rápido, sin pipeline."
        )
        self._btn_adiutor1.clicked.connect(self._abrir_adiutor_uno)
        top_lay.addWidget(self._btn_adiutor1)
        top_lay.addSpacing(8)

        self._btn_revisar = QPushButton("📋  Revisar resolución")
        self._btn_revisar.setStyleSheet(_BTN_GHOST)
        self._btn_revisar.setToolTip("Analiza y corrige un borrador de resolución usando el wiki y bibliografía del magistrado.")
        self._btn_revisar.clicked.connect(self._abrir_revision)
        top_lay.addWidget(self._btn_revisar)
        top_lay.addSpacing(8)

        self._btn_historial = QPushButton("📁  Historial")
        self._btn_historial.setStyleSheet(_BTN_GHOST)
        self._btn_historial.setToolTip("Ver historial de expedientes procesados.")
        self._btn_historial.clicked.connect(self._abrir_historial)
        top_lay.addWidget(self._btn_historial)
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
        self._setup.ver_proceso.connect(self._on_ver_proceso)
        self._hechos.confirmar.connect(self._on_hechos_confirmados)
        self._hechos.volver.connect(lambda: self._go(0))
        self._fuentes.aprobar.connect(self._on_fuentes_aprobadas)
        self._fuentes.volver.connect(lambda: self._go(1))
        self._fuentes.buscar_web.connect(self._on_buscar_web_fuentes)
        self._borrador.aprobar.connect(self._on_borrador_aprobado)
        self._borrador.volver.connect(lambda: self._go(2))
        self._final.reiniciar.connect(self._on_reiniciar)
        self._final.iterar.connect(self._on_iterar_final)

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
        self._hechos.set_review_mode(True)
        self._fuentes.set_review_mode(True)
        self._borrador.set_review_mode(True)

    def _set_status(self, msg: str):
        self._status_bar.setText(msg)

    def _abrir_adiutor_uno(self):
        """Abre el modo clásico de generación con un solo prompt (Adiutor Iudicis 1)."""
        cfg = getattr(self, "_current_cfg", None)
        if not cfg or not cfg.get("caso_path"):
            QMessageBox.information(
                self, "Adiutor Iudicis 1",
                "Primero configura el caso en la pantalla de inicio\n"
                "(selecciona materia, caso y documentos).",
            )
            return
        dlg = _AdiutorUnoDialog(cfg, parent=self)
        dlg.exec()

    def _abrir_historial(self):
        """Abre el panel de historial de expedientes."""
        dlg = _HistorialDialog(parent=self)
        dlg.ver_proceso.connect(self._on_ver_proceso)
        dlg.exec()

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
        self._folder_name = caso_folder.name
        self._set_status("Iniciando fábrica…")

        # Arrancar SIEMPRE en estado limpio: una corrida nueva no debe heredar el
        # modo revisión de un caso visto antes. Si se hereda, "confirmar" navega como
        # revisión en vez de disparar el siguiente nodo del pipeline (era el bug que
        # dejaba el caso trabado en Hechos sin poder pasar a Fuentes).
        self._review_mode = False
        self._iterating   = False
        self._iter_n      = 0
        self._hechos.set_review_mode(False)
        self._fuentes.set_review_mode(False)
        self._borrador.set_review_mode(False)

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
                resoluciones_estilo=[Path(p) for p in cfg.get("resoluciones_estilo", [])],
                bibliografia=[Path(p) for p in cfg.get("bibliografia", [])],
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

    def _persistir_proceso(self):
        """Vuelca el estado actual del grafo (hechos/agravios/fuentes/borrador) a
        archivos .md en outputs/<caso>/proceso/. Best-effort, nunca rompe la UI."""
        if not self._folder_name or not self._graph or not self._thread_id:
            return
        try:
            from app.artifex.graph import save_proceso_to_folder
            snap = self._graph.get_state(make_config_local(self._thread_id))
            if snap and snap.values:
                save_proceso_to_folder(self._folder_name, snap.values)
        except Exception:
            pass

    def _on_checkpoint_hit(self, data: dict):
        cp        = data.get("checkpoint", "")
        contenido = data.get("contenido", "")
        # Persistir el proceso generado hasta este checkpoint (robusto, legible).
        self._persistir_proceso()

        # Blindaje: un fallo al renderizar una pantalla NUNCA debe dejar al juez
        # varado (parecería "no pasa nada"). Si algo revienta, se avanza igual y se
        # muestra el error de forma visible.
        try:
            if cp == "hechos":
                agravios = data.get("agravios", "")
                self._hechos.set_texto(contenido, agravios)
                self._go(1)
                self._set_status("★ Checkpoint ① — revise los hechos y el problema jurídico.")
            elif cp == "fuentes":
                try:
                    self._fuentes.set_fuentes(contenido)
                except Exception as e_parse:
                    # El parser falló: mostrar el texto crudo para no bloquear el avance.
                    self._fuentes.set_fuentes_raw(contenido)
                    self._set_status(f"Fuentes mostradas en crudo (parser: {e_parse}).")
                self._go(2)
                if not self._status_bar.text().startswith("Fuentes mostradas"):
                    self._set_status("★ Checkpoint ② — revise las fuentes.")
            elif cp == "borrador":
                self._last_borrador = contenido  # guardar para mostrarlo en pantalla final
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
                self._set_status(f"Checkpoint desconocido: {cp!r}. Contenido recibido: "
                                 f"{len(contenido)} caracteres.")
        except Exception as exc:
            import traceback
            traceback.print_exc()
            self._set_status(f"Error al mostrar el checkpoint «{cp}»: {exc}")
            QMessageBox.critical(
                self, "Error al avanzar",
                f"El proceso continuó pero falló al mostrar la pantalla de «{cp}».\n\n{exc}",
            )

    def _on_pipeline_done(self, docx_path: str):
        # Guardar el estado final del grafo para poder re-exportar si el juez edita el borrador.
        if self._graph and self._thread_id and self._shortcut_state is None:
            try:
                snap = self._graph.get_state(make_config_local(self._thread_id))
                if snap:
                    vals = snap.values
                    if hasattr(vals, "borrador"):
                        self._shortcut_state = vals
                    elif isinstance(vals, dict):
                        from app.artifex.state import CasoState
                        fields = CasoState.model_fields.keys()
                        self._shortcut_state = CasoState(**{k: v for k, v in vals.items() if k in fields})
            except Exception:
                pass
        # Persistir el proceso completo del caso (hechos/agravios/fuentes/borrador).
        self._persistir_proceso()
        can_edit = self._shortcut_state is not None
        self._final.set_docx(docx_path, expediente=self._expediente, borrador=self._last_borrador, can_edit=can_edit)
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

    def _on_hechos_confirmados(self, texto: str, agravios: str):
        if self._review_mode:           # solo revisión: avanzar al siguiente paso (Fuentes)
            self._go(2)
            return
        self._set_status("⏳ Buscando fundamentos (RAG)… ~40 s. No cierres la ventana.")
        self._resume({"accion": "aprobar", "texto": texto, "agravios": agravios})

    def _on_fuentes_aprobadas(self, texto: str):
        if self._review_mode:           # solo revisión: avanzar al siguiente paso (Borrador)
            self._go(3)
            return
        self._set_status("⏳ Redactando la resolución… 1-3 min. No cierres la ventana.")
        self._resume({"accion": "aprobar", "texto": texto})

    def _on_borrador_aprobado(self, texto: str):
        if self._review_mode and not self._iterating:
            # Solo revisión sin edición activa: volver a la pantalla final.
            self._go(4)
            return
        if self._shortcut_state is not None:
            # Modo iteración post-pipeline o modo "cargar borrador": exportar directo.
            self._iterating = False
            self._borrador.set_review_mode(True)
            self._shortcut_export(texto)
        else:
            self._set_status("⏳ Generando el .docx… No cierres la ventana.")
            self._resume({"accion": "aprobar", "texto": texto})

    def _on_editar_borrador_post_pipeline(self):
        """(Legado) El juez quiere corregir el borrador y regenerar el .docx."""
        self._iterating = True
        self._borrador.set_review_mode(False)  # reactiva la edición
        self._go(3)

    def _on_iterar_final(self, instruccion: str):
        """Iteración post-resolución: pide una corrección/ampliación al modelo y la
        ANEXA al final del documento, sin modificar la resolución ya generada.
        Ilimitada: cada llamada agrega un bloque más a continuación."""
        if not instruccion.strip():
            self._final.set_busy_iter(False)
            return
        if not self._last_borrador.strip():
            self._set_status("No hay resolución sobre la que iterar.")
            self._final.set_busy_iter(False)
            return
        self._set_status("⏳ Generando la corrección/ampliación… No cierres la ventana.")
        self._iter_worker = _IterarWorker(self._last_borrador, instruccion, parent=self)
        self._iter_worker.done.connect(
            lambda resp, instr=instruccion: self._on_iteracion_lista(instr, resp)
        )
        self._iter_worker.error.connect(self._on_iter_error)
        self._iter_worker.start()

    def _on_iteracion_lista(self, instruccion: str, respuesta: str):
        self._iter_n += 1
        sep = "═" * 60
        addenda = (
            f"\n\n\n{sep}\n"
            f"CORRECCIÓN / AMPLIACIÓN {self._iter_n} (a solicitud del magistrado)\n"
            f"Instrucción: {instruccion.strip()}\n"
            f"{'─' * 60}\n"
            f"{respuesta.strip()}\n"
        )
        self._last_borrador = self._last_borrador.rstrip() + addenda

        # Regenerar el .docx con el documento extendido (resolución + adendas).
        docx_path = ""
        if self._shortcut_state is not None:
            try:
                from app.artifex.nodes import node_formato
                self._shortcut_state.borrador = self._last_borrador
                st = node_formato(self._shortcut_state)
                docx_path = st.documento_final or ""
            except Exception as e:
                self._set_status(f"Iteración anexada; error al regenerar .docx: {e}")

        self._final.iteracion_terminada(self._last_borrador)
        if docx_path:
            self._final.set_docx(docx_path, expediente=self._expediente)
        # Persistir el proceso extendido a .md.
        if self._folder_name:
            try:
                from app.artifex.graph import save_proceso_to_folder
                save_proceso_to_folder(self._folder_name, {"borrador": self._last_borrador})
            except Exception:
                pass
        self._set_status(f"✓ Corrección/ampliación {self._iter_n} anexada al final del documento.")

    def _on_iter_error(self, msg: str):
        self._final.set_busy_iter(False)
        self._set_status(f"Error en la iteración: {msg[:120]}")
        QMessageBox.critical(self, "Iteración", msg)

    # ── Búsqueda web en Fuentes ───────────────────────────────────────────

    def _contexto_caso_para_busqueda(self) -> str:
        """Reúne el contexto del caso (delito, materia, enfoque del juez, agravios)
        para que Haiku DESTILE las palabras clave. No se usa como query literal."""
        cfg = self._current_cfg
        instr    = cfg.get("instruccion_particular", "").strip()
        delito   = cfg.get("delito", "").strip()
        materia  = cfg.get("materia_label", cfg.get("materia", "")).strip()
        agravios = ""
        if self._shortcut_state:
            instr    = instr   or (self._shortcut_state.instruccion_particular or "")
            delito   = delito  or (self._shortcut_state.delito or "")
            materia  = materia or (self._shortcut_state.materia_label or "")
            agravios = (self._shortcut_state.agravios or "")[:600]
        partes = [
            f"Delito y materia: {delito} {materia}".strip(),
            f"Enfoque del juez para este caso: {instr}" if instr else "",
            f"Agravios del recurso: {agravios}" if agravios else "",
        ]
        return "\n".join(p for p in partes if p).strip()

    def _on_buscar_web_fuentes(self, termino: str = ""):
        """Lanza búsqueda Tavily sobre jurisprudencia y doctrina relacionadas al caso.
        Si el juez escribió un término, busca con ese; si lo dejó vacío, destila las
        palabras clave del caso con Haiku y busca con esas keywords."""
        termino  = (termino or "").strip()
        contexto = self._contexto_caso_para_busqueda()
        if not termino and not contexto:
            QMessageBox.information(self, "Buscar en la web",
                "Escribe qué buscar, o configura primero el caso (delito/instrucción).")
            return

        self._fuentes.set_busy_web(True)
        if termino:
            self._set_status(f"⏳ Buscando en la web: «{termino[:80]}»…")
        else:
            self._set_status("⏳ Destilando palabras clave del caso y buscando en la web…")

        self._web_worker = _BuscarWebWorker(termino, contexto=contexto, parent=self)
        self._web_worker.query_usada.connect(self._fuentes.mostrar_query_usada)
        self._web_worker.done.connect(self._on_busqueda_web_lista)
        self._web_worker.error.connect(self._on_busqueda_web_error)
        self._web_worker.start()

    def _on_busqueda_web_lista(self, resultado: str):
        self._fuentes.set_busy_web(False)
        if resultado.strip():
            self._fuentes.append_busqueda_web(resultado)
            self._set_status("✓ Resultados web agregados a Fuentes. Revisa y selecciona los pertinentes.")
        else:
            self._set_status("La búsqueda no devolvió resultados. Intenta con un término más específico.")

    def _on_busqueda_web_error(self, msg: str):
        self._fuentes.set_busy_web(False)
        self._set_status(f"Error en la búsqueda web: {msg[:120]}")
        QMessageBox.critical(self, "Buscar en la web", msg)

    def _on_ver_proceso(self, caso_path: str):
        """Recupera el proceso guardado de un caso (hechos/fuentes/borrador) y lo
        carga en el stepper en modo revisión, para revisar sesiones anteriores."""
        from app.artifex.graph import recover_state_by_folder

        folder = Path(caso_path).name
        self._set_status(f"Recuperando proceso de {folder}…")
        state = recover_state_by_folder(folder)

        has_process = state is not None and (
            state.hechos_resumen or state.fuentes or state.borrador
        )

        # Buscar el .docx final independientemente del proceso.
        docx = (state.documento_final if state else "") or ""
        if not docx or not Path(docx).is_file():
            out_dir = BASE_DIR / "outputs" / folder
            cands = (
                sorted(out_dir.glob("*.docx"), key=lambda p: p.stat().st_mtime, reverse=True)
                if out_dir.is_dir() else []
            )
            docx = str(cands[0]) if cands else ""

        if not has_process and not docx:
            QMessageBox.information(
                self, "Ver proceso",
                "No se encontró el proceso ni la resolución de este caso.\n\n"
                "Esto ocurre con casos que aún no han sido procesados.",
            )
            self._set_status("Proceso no disponible para este caso.")
            return

        # Guardar estado (puede ser None si solo hay .docx sin proceso).
        self._shortcut_state = state

        if has_process:
            self._hechos.set_texto(state.hechos_resumen or "", state.agravios or "")
            self._fuentes.set_fuentes(state.fuentes or "")
            self._borrador.set_borrador(state.borrador or "", citas_ok=state.citas_ok, avisos=[])
            self._last_borrador = state.borrador or ""
            self._expediente = state.expediente or ""

        # Poblar _current_cfg para que Adiutor Iudicis 1 pueda arrancar desde este caso.
        if state is not None:
            from app.core.file_manager import list_bibliografia
            try:
                bib_files = [str(p) for p in list_bibliografia(state.materia)]
            except Exception:
                bib_files = []
            self._current_cfg = {
                "materia":                state.materia,
                "caso_path":              caso_path,
                "plantilla_path":         str(state.plantilla_path) if state.plantilla_path else "",
                "expediente":             state.expediente or "",
                "imputados":              state.imputados or "",
                "delito":                 state.delito or "",
                "agraviado":              state.agraviado or "",
                "juzgado":                state.juzgado or "",
                "postura":                state.postura if isinstance(state.postura, str) else (state.postura.value if state.postura else "confirmar"),
                "instruccion_particular": state.instruccion_particular or "",
                "use_live_web":           False,
                "resoluciones_estilo":    [],
                "bibliografia":           bib_files,
            }
        elif caso_path:
            # Sin state guardado (solo .docx): al menos tenemos el path.
            self._current_cfg = {"caso_path": caso_path, "materia": ""}

        self._final.set_docx(
            docx,
            expediente=self._expediente,
            borrador=self._last_borrador,
            can_edit=True,
        )

        # Habilitar TODO el stepper siempre que haya algo que revisar.
        self._enable_review_nav()
        # Si hay proceso completo, abrir en Hechos; si solo hay .docx, ir a Resolución.
        self._go(1 if has_process else 4)
        self._set_status(f"Revisando proceso de {folder} — navega por el stepper de arriba.")

    def _shortcut_export(self, borrador: str):
        """Exporta .docx directamente sin pasar por el grafo (modo cargar borrador)."""
        from app.artifex.nodes import node_formato
        state = self._shortcut_state
        state.borrador = borrador
        try:
            state = node_formato(state)
            docx = state.documento_final or ""
            self._last_borrador = borrador
            self._final.set_docx(docx, expediente=state.expediente, borrador=borrador, can_edit=True)
            self._go(4)
            self._enable_review_nav()
            self._set_status("✓ Resolución generada.")
        except Exception as e:
            self._set_status(f"Error al exportar: {e}")

    def _on_reiniciar(self):
        self._thread_id      = None
        self._shortcut_state = None
        self._review_mode    = False
        self._iterating      = False
        self._iter_n         = 0
        self._last_borrador  = ""
        self._hechos.set_review_mode(False)
        self._fuentes.set_review_mode(False)
        self._borrador.set_review_mode(False)
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
        self.setWindowTitle("📋 Revisar y corregir resolución — Adiutor Iudicis.2")
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
        btn_mis = QPushButton("🗂  Mis resoluciones")
        btn_mis.setStyleSheet(_BTN_GHOST)
        btn_mis.setToolTip("Lista las resoluciones generadas por Adiutor Iudicis.2 (carpeta outputs/)")
        btn_mis.clicked.connect(self._on_mis_resoluciones)
        carga_row.addWidget(btn_mis)
        btn_cargar = QPushButton("📂  Cargar archivo…")
        btn_cargar.setStyleSheet(_BTN_GHOST)
        btn_cargar.clicked.connect(self._on_cargar)
        carga_row.addWidget(btn_cargar)
        root.addLayout(carga_row)

        # ── Materia (para instrucción general y wiki) ──
        mat_row = QHBoxLayout()
        mat_row.addWidget(_lbl("Materia:", size=12))
        self._cmb_materia = _NoScrollComboBox()
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

        # ── Panel análisis jurídico ──
        analisis_panel = QWidget()
        analisis_layout = QVBoxLayout(analisis_panel)
        analisis_layout.setContentsMargins(0, 0, 0, 0)
        analisis_layout.setSpacing(6)

        analisis_header = QHBoxLayout()
        analisis_header.addWidget(_lbl("Análisis jurídico", bold=True, size=12))
        analisis_header.addStretch()
        btn_expandir_analisis = QPushButton("⛶  Expandir")
        btn_expandir_analisis.setStyleSheet(_BTN_SMALL_GHOST)
        btn_expandir_analisis.setToolTip("Ver el análisis jurídico en ventana grande")
        btn_expandir_analisis.clicked.connect(self._on_expandir_analisis)
        analisis_header.addWidget(btn_expandir_analisis)
        analisis_layout.addLayout(analisis_header)

        self._txt_analisis = QTextEdit()
        self._txt_analisis.setReadOnly(True)
        self._txt_analisis.setPlaceholderText("El análisis técnico-jurídico aparecerá aquí…")
        self._txt_analisis.setStyleSheet(
            f"background: {_C['card']}; border: 1px solid {_C['hair']}; "
            f"border-radius: 10px; padding: 12px; font-size: 13px;"
        )
        analisis_layout.addWidget(self._txt_analisis, 1)
        splitter.addWidget(analisis_panel)

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
            # Mostrar el texto cargado para poder leerlo/expandirlo antes de corregir.
            # Cuando se genere la corrección, este texto se reemplazará.
            self._txt_resultado.setPlainText(text)
            self._btn_reescribir.setEnabled(True)
            # Guardar ruta para restaurar en próxima apertura
            from PyQt6.QtCore import QSettings
            QSettings("ArtifexIudicialis", "RevisionDialog").setValue("ultimo_borrador", path)
            return True, ""
        except Exception as exc:
            return False, str(exc)

    def _on_mis_resoluciones(self):
        """Muestra un listado de los .docx generados por Artifex (outputs/)."""
        out_root = BASE_DIR / "outputs"
        archivos = sorted(
            out_root.rglob("*.docx") if out_root.exists() else [],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not archivos:
            QMessageBox.information(self, "Mis resoluciones",
                "No se encontraron resoluciones generadas en la carpeta outputs/.\n"
                "Genera al menos una resolución primero.")
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("🗂  Mis resoluciones generadas")
        dlg.resize(620, 420)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        lay.addWidget(_lbl("Haz doble clic para cargar la resolución en el revisor:", size=12))

        lista = QListWidget()
        lista.setStyleSheet(
            f"background:{_C['card']}; border:1px solid {_C['hair']};"
            f"border-radius:8px; font-size:12px; padding:4px;"
        )
        from datetime import datetime
        for p in archivos:
            ts = datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            item = QListWidgetItem(f"{p.name}   —   {ts}   [{p.parent.name}]")
            item.setData(Qt.ItemDataRole.UserRole, str(p))
            lista.addItem(item)
        lay.addWidget(lista, 1)

        btn_row = QHBoxLayout()
        btn_abrir_carpeta = QPushButton("📁  Abrir carpeta outputs")
        btn_abrir_carpeta.setStyleSheet(_BTN_GHOST)
        btn_abrir_carpeta.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(out_root)))
        )
        btn_row.addWidget(btn_abrir_carpeta)
        btn_row.addStretch()
        btn_cerrar = QPushButton("Cerrar")
        btn_cerrar.setStyleSheet(_BTN_GHOST)
        btn_cerrar.clicked.connect(dlg.reject)
        btn_row.addWidget(btn_cerrar)
        lay.addLayout(btn_row)

        def _cargar_seleccion():
            item = lista.currentItem()
            if not item:
                return
            path = item.data(Qt.ItemDataRole.UserRole)
            ok, err = self._cargar_archivo(path)
            if ok:
                dlg.accept()
            else:
                QMessageBox.warning(dlg, "Error de lectura",
                    f"No se pudo extraer texto del archivo:\n{err}")

        lista.itemDoubleClicked.connect(lambda _: _cargar_seleccion())
        dlg.exec()

    def _on_cargar(self):
        out_root = BASE_DIR / "outputs"
        default_dir = str(out_root) if out_root.exists() else str(Path.home())
        path, _ = QFileDialog.getOpenFileName(
            self, "Cargar borrador de resolución", default_dir,
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

    # ── Expandir análisis jurídico ────────────────────────────────
    def _on_expandir_analisis(self):
        """Abre el análisis jurídico en una ventana grande para revisión cómoda."""
        texto = self._txt_analisis.toPlainText()
        if not texto.strip():
            QMessageBox.information(
                self, "Sin contenido",
                "Primero genera el análisis pulsando «🔍 Analizar»."
            )
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Análisis jurídico — Vista expandida")
        dlg.resize(960, 780)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(8)
        txt = QTextEdit()
        txt.setHtml(self._txt_analisis.toHtml())
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
