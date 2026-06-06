"""
Adiutor Iudicis — Asistente de Redacción Judicial
Procesamiento inteligente: Cursor + .cursorrules (sin API, sin Ollama)
"""

from __future__ import annotations

import html
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QEvent, Qt, QTimer, QUrl, QSize, pyqtSignal
from PyQt6.QtGui import QColor, QDesktopServices, QFont, QGuiApplication, QKeySequence, QShortcut, QShowEvent
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTextEdit,
    QAbstractItemView,
    QTreeWidget,
    QTreeWidgetItem,
    QGridLayout,
    QStyle,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from app.core.whisper_local import transcribe_audio_to_txt, whisper_cli_available
from app.core.claude_worker import (
    ClaudeWorker,
    ResolutionContinuationWorker,
    build_enriched_prompt,
    resolution_model_badge_label,
    _IterWorker,
)
from app.core.wiki_worker import (
    BIBLIO_INGEST_SCOPE_GLOBAL,
    BibliografiaIngestorWorker,
    CorrectionLearningWorker,
    CorpusIngestorWorker,
    ResolutionFichaWorker,
    WikiRebuildWorker,
    WikiQueryWorker,
)
from app.core.file_manager import (
    BASE_DIR,
    DEFAULT_MATERIA,
    DIRS,
    MATERIA_APELACION_SENT,
    MATERIA_BENEFICIOS_PENIT,
    MATERIA_CESACION_PP,
    MATERIA_CONSULTAS,
    MATERIA_ENJUICIAMIENTO,
    MATERIA_LABELS,
    MATERIA_MEDIDAS_COERC,
    MATERIA_NULIDAD,
    MATERIA_OTROS,
    MATERIA_PRISION_PREVENTIVA,
    MATERIA_PROLONGACION_PP,
    MATERIA_QUEJAS_DERECHO,
    MATERIA_RECURSOS_QUEJA,
    MATERIA_SLUGS,
    MATERIA_SOBRESEIMIENTO,
    MATERIA_TUTELA,
    SLOT_KEYS,
    add_bibliografia,
    add_bibliografia_global,
    list_bibliografia_global,
    dir_bibliografia_global,
    add_plantilla,
    add_to_case,
    BORRADOR_CONTINUAR_QFILE_FILTER,
    build_cursor_prompt,
    case_folder_name,
    copy_to,
    create_case_folder,
    dir_bibliografia_materia,
    dir_corpus_materia,
    dir_casos_previos_wiki,
    dir_instrucciones_generales,
    dir_plantillas_materia,
    dir_resoluciones_materia,
    get_next_case_number,
    infer_materia_from_resoluciones_md,
    is_valid_borrador_continuar_path,
    list_bibliografia,
    list_case_files,
    list_case_folders,
    list_corpus_wiki_fichas,
    list_plantillas,
    list_resoluciones,
    materia_label,
    pending_bibliografia_for_fichas,
    pending_bibliografia_global_for_fichas,
    pending_corpus_pdfs,
    read_fuentes_slots,
    read_instruccion_general,
    save_instruccion_general,
    save_prompt_to_resoluciones_folder,
    save_resolucion_cursor_text,
    save_resolucion_generada_backup,
    slot_labels_for,
    write_fuentes_slots_manifest,
)
from app.core.env_load import set_repo_env_var
from app.core.output_validator import ValidationReport, validate_resolution_output
from app.core.pdf_extract import probe_pdf_readability
from app.ui.juris_quick_note_dialog import JurisQuickNoteDialog, open_edit_bibliografia_note
from app.ui.artifex_page import ArtifexPage
from app.ui.theme import build_global_stylesheet, get_app_theme

# ─── Tema (env ADIUTOR_THEME: soft | light | dark) ─────────────────────────
_TH = get_app_theme()
BG = _TH.bg
BG_CARD = _TH.bg_card
BG_INPUT = _TH.bg_input
GOLD = _TH.gold
GOLD_H = _TH.gold_h
TEXT = _TH.text
MUTED = _TH.muted
BORDER = _TH.border
SUCCESS = _TH.success
ERROR = _TH.error
READER_CANVAS = _TH.reader_canvas
CLAUDE_ACCENT = _TH.claude_accent
TEXT_ON_GOLD = _TH.text_on_gold
CODE_PANEL_BG = _TH.code_panel_bg
CODE_MD_BG = _TH.code_md_bg
CODE_INLINE_COLOR = _TH.code_inline_color
WIKI_ASST_BG = _TH.wiki_asst_bg
WIKI_ERROR_BG = _TH.wiki_error_bg
GEN_CLAUDE_BG = _TH.gen_claude_bg
GEN_CLAUDE_FG = _TH.gen_claude_fg
GEN_CLAUDE_BORDER = _TH.gen_claude_border
GEN_CLAUDE_HOVER_BG = _TH.gen_claude_hover_bg
GEN_CLAUDE_HOVER_FG = _TH.gen_claude_hover_fg
GEN_LABEL_COLOR = _TH.gen_label_color
NAV_ROW_HOVER = _TH.nav_row_hover
STYLE = build_global_stylesheet(_TH)

# Bibliografía (coherente con `file_manager.BIBLIOGRAFIA_SUFFIXES`)
BIBLIO_QFILE_FILTER = (
    "Bibliografía (*.pdf *.doc *.docx *.md *.txt);;Todos los archivos (*)"
)

def restart_amanuensis_application(parent: QWidget | None = None) -> None:
    """Relanza el proceso con el mismo intérprete y argumentos para cargar el código actualizado en disco."""
    try:
        os.execl(sys.executable, sys.executable, *sys.argv)
    except OSError as e:
        win = parent or QApplication.activeWindow()
        QMessageBox.critical(
            win,
            "No se pudo reiniciar Adiutor Iudicis",
            f"No se pudo iniciar un proceso nuevo con el mismo intérprete.\n\n{e}",
        )


# Misma lógica visual que «Consultar wiki»: panel de lectura hundido + tipografía (READER_CANVAS, serif)
def _qss_text_reader(
    *,
    border_color: str | None = None,
) -> str:
    """Bloques de solo lectura largos: resoluciones, plantilla .md, salida del chat wiki, texto generado."""
    b = border_color or BORDER
    return f"""
        QTextEdit {{
            background-color: {READER_CANVAS};
            color: {TEXT};
            border: 1px solid {b};
            border-radius: 12px;
            padding: 18px 16px;
            font-family: "Georgia", "Noto Serif", "Times New Roman", serif;
            font-size: 13px;
            line-height: 1.55;
            selection-background-color: {GOLD};
            selection-color: {TEXT_ON_GOLD};
        }}
    """


def _qss_word_editor() -> str:
    """Editor de resoluciones con apariencia de hoja Microsoft Word.

    Fondo blanco, fuente Arial Narrow 13 pt (la misma del documento final),
    texto negro, padding generoso que simula los márgenes de página,
    sin bordes redondeados ni colores de tema — igual a Word.
    """
    return """
        QTextEdit {
            background-color: #ffffff;
            color: #000000;
            border: 1px solid #c8c8c8;
            border-radius: 0px;
            padding: 48px 72px;
            font-family: "Arial Narrow", "Arial", sans-serif;
            font-size: 14px;
            line-height: 1.6;
            selection-background-color: #b8d4f0;
            selection-color: #000000;
        }
        QScrollBar:vertical {
            background: #f0f0f0;
            width: 10px;
            border: none;
        }
        QScrollBar::handle:vertical {
            background: #b0b0b0;
            border-radius: 5px;
            min-height: 24px;
        }
        QScrollBar::handle:vertical:hover {
            background: #808080;
        }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
    """


def _qss_text_composer_plain() -> str:
    """Refuerza el estilo global (útil en widgets dentro de contenedores con otra hoja)."""
    return f"""
        QPlainTextEdit {{
            background-color: {BG_INPUT};
            color: {TEXT};
            border: 1px solid {BORDER};
            border-radius: 8px;
            padding: 10px 12px;
            font-size: 13px;
            line-height: 1.5;
        }}
        QPlainTextEdit:focus {{ border-color: {GOLD}; }}
    """


def _qss_text_composer_rich() -> str:
    """QTextEdit multilínea de formularios (instrucción, sugerencias)."""
    return f"""
        QTextEdit {{
            background-color: {BG_INPUT};
            color: {TEXT};
            border: 1px solid {BORDER};
            border-radius: 8px;
            padding: 10px 12px;
            font-size: 13px;
            line-height: 1.5;
        }}
        QTextEdit:focus {{ border-color: {GOLD}; }}
    """


def _qss_text_code_readonly() -> str:
    """Prompts técnicos y salidas monoespacio."""
    return f"""
        QTextEdit {{
            background-color: {CODE_PANEL_BG};
            color: {GOLD};
            border: 1px solid {BORDER};
            border-radius: 8px;
            padding: 12px 14px;
            font-family: "Menlo", "Courier New", "Monaco", monospace;
            font-size: 12px;
            line-height: 1.45;
        }}
    """


def _resolucion_viewer_document_css() -> str:
    """Tema de lectura para Markdown en QTextEdit (sincronizado con el panel de «Consultar wiki»)."""
    return f"""
        html, body {{ background-color: transparent; color: {TEXT}; }}
        body {{
            font-family: Georgia, 'Noto Serif', 'Times New Roman', serif;
            font-size: 14px;
            line-height: 1.65;
        }}
        p {{ margin: 0.5em 0; }}
        h1 {{
            color: {GOLD};
            font-size: 1.45em;
            font-weight: 700;
            margin: 0.85em 0 0.4em;
            line-height: 1.2;
        }}
        h2 {{
            color: {GOLD};
            font-size: 1.2em;
            font-weight: 700;
            margin: 0.7em 0 0.35em;
            line-height: 1.25;
        }}
        h3, h4 {{
            color: {GOLD};
            font-size: 1.05em;
            font-weight: 600;
            margin: 0.55em 0 0.3em;
        }}
        strong, b {{ color: {TEXT}; font-weight: 700; }}
        em, i {{ color: {MUTED}; }}
        code {{
            background-color: {CODE_MD_BG};
            color: {CODE_INLINE_COLOR};
            padding: 2px 6px;
            border-radius: 4px;
            font-family: 'Menlo', 'Monaco', 'Courier New', monospace;
            font-size: 0.88em;
        }}
        pre {{
            background-color: {CODE_MD_BG};
            color: {TEXT};
            padding: 12px 14px;
            border-radius: 8px;
            border: 1px solid {BORDER};
            font-family: 'Menlo', 'Monaco', 'Courier New', monospace;
            font-size: 12px;
            line-height: 1.45;
            margin: 0.65em 0;
            white-space: pre-wrap;
        }}
        pre code {{ background: transparent; padding: 0; border: none; color: {TEXT}; }}
        blockquote {{
            color: {MUTED};
            border-left: 3px solid {GOLD};
            margin: 0.55em 0;
            padding: 0.15em 0 0.15em 14px;
        }}
        a {{ color: {GOLD}; text-decoration: none; }}
        ul, ol {{ margin: 0.45em 0; padding-left: 1.35em; }}
        li {{ margin: 0.22em 0; }}
        hr {{ border: none; border-top: 1px solid {BORDER}; margin: 1em 0; }}
        table {{ border-collapse: collapse; width: 100%; margin: 0.5em 0; }}
        th, td {{ border: 1px solid {BORDER}; padding: 6px 8px; }}
        th {{ background-color: {BG_INPUT}; color: {GOLD}; font-weight: 600; }}
    """


_RE_MD_IMAGE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")


def _markdown_resolve_local_images(md: str, md_file_dir: Path) -> str:
    """
    QTextEdit.setMarkdown() no resuelve rutas relativas respecto al .md; las imágenes
    quedan como rectángulos en blanco. Convierte rutas locales existentes a file:// absolutas.
    """

    def repl(m: re.Match[str]) -> str:
        alt = m.group(1)
        raw_inner = m.group(2).strip()
        # Título opcional: ![](ruta "título")
        mtitle = re.match(r"^(.+?)(\s+\"[^\"]*\"\s*)$", raw_inner)
        if mtitle:
            path_part = mtitle.group(1).strip()
            quoted_title = mtitle.group(2).strip()
        else:
            path_part = raw_inner
            quoted_title = ""
        path_part = path_part.strip().strip("<>").strip('"')
        if not path_part:
            return m.group(0)
        low = path_part.lower()
        if low.startswith(("http://", "https://", "data:", "file:")):
            return m.group(0)
        pth = Path(path_part)
        if not pth.is_absolute():
            candidate = (md_file_dir / pth).resolve()
        else:
            candidate = pth.resolve()
        if not candidate.is_file():
            return f"*[Imagen no encontrada: `{path_part}`]*"
        url = QUrl.fromLocalFile(str(candidate)).toString()
        if quoted_title:
            return f"![{alt}]({url} {quoted_title})"
        return f"![{alt}]({url})"

    return _RE_MD_IMAGE.sub(repl, md)


def _section_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"color: {GOLD}; font-size: 10px; font-weight: 700;"
        f" letter-spacing: 2px; background: transparent;"
    )
    return lbl


def _apply_soft_shadow(widget: QFrame, *, blur: int = 32, dy: int = 8, alpha: int = 72) -> None:
    """Sombra suave bajo tarjetas (estilo panel moderno)."""
    eff = QGraphicsDropShadowEffect(widget)
    eff.setBlurRadius(blur)
    eff.setOffset(0, dy)
    eff.setColor(QColor(0, 0, 0, alpha))
    widget.setGraphicsEffect(eff)


def _welcome_hero() -> QFrame:
    """Cabecera de la pantalla de inicio: marca centrada, ritmo vertical simétrico."""
    fr = QFrame()
    fr.setObjectName("WelcomeHero")
    fr.setStyleSheet(
        f"QFrame#WelcomeHero {{"
        f" background-color: {READER_CANVAS};"
        f" border: 1px solid {BORDER};"
        f" border-radius: 18px;}}"
    )
    v = QVBoxLayout(fr)
    v.setContentsMargins(40, 32, 40, 36)
    v.setSpacing(12)
    kicker = QLabel("ASISTENTE DE REDACCIÓN JUDICIAL")
    kicker.setAlignment(Qt.AlignmentFlag.AlignCenter)
    kicker.setStyleSheet(
        f"color: {MUTED}; font-size: 12px; font-weight: 700; letter-spacing: 4px; "
        f"background: transparent;"
    )
    v.addWidget(kicker)
    title = QLabel("ADIUTOR IUDICIS")
    title.setAlignment(Qt.AlignmentFlag.AlignCenter)
    title.setStyleSheet(
        f"color: {GOLD}; font-size: 38px; font-weight: 700; letter-spacing: 3px; "
        f"background: transparent;"
    )
    v.addWidget(title)
    accent_row = QHBoxLayout()
    accent_row.setContentsMargins(0, 4, 0, 8)
    accent = QFrame()
    accent.setFixedHeight(3)
    accent.setFixedWidth(96)
    accent.setStyleSheet(
        f"background-color: {GOLD}; border: none; border-radius: 2px;"
    )
    accent_row.addStretch(1)
    accent_row.addWidget(accent)
    accent_row.addStretch(1)
    v.addLayout(accent_row)
    tag = QLabel("Expedientes · corpus · wiki · bibliografía")
    tag.setAlignment(Qt.AlignmentFlag.AlignCenter)
    tag.setStyleSheet(
        f"color: {MUTED}; font-size: 14px; font-weight: 500; letter-spacing: 0.5px; "
        f"background: transparent;"
    )
    v.addWidget(tag)
    _apply_soft_shadow(fr, blur=36, dy=10, alpha=48)
    return fr


def _start_panel_card(
    title: str,
    description: str | None = None,
    *,
    primary: bool = False,
    min_height: int = 0,
) -> tuple[QFrame, QVBoxLayout]:
    """Tarjeta del panel de inicio; primary destaca la acción principal (nuevo expediente)."""
    oid = "StartPanelCardPrimary" if primary else "StartPanelCard"
    box = QFrame()
    box.setObjectName(oid)
    if primary:
        box.setStyleSheet(
            f"QFrame#{oid} {{"
            f" background-color: {BG_CARD};"
            f" border: 2px solid {GOLD};"
            f" border-radius: 16px;}}"
        )
    else:
        box.setStyleSheet(
            f"QFrame#{oid} {{"
            f" background-color: {BG_CARD};"
            f" border: 1px solid {BORDER};"
            f" border-radius: 16px;}}"
        )
    lay = QVBoxLayout(box)
    lay.setContentsMargins(28, 24, 28, 26)
    lay.setSpacing(14)
    if min_height > 0:
        box.setMinimumHeight(min_height)
    t = QLabel(title)
    if primary:
        t.setStyleSheet(
            f"color: {GOLD}; font-size: 19px; font-weight: 700; background: transparent;"
            f" letter-spacing: 0.3px;"
        )
    else:
        t.setStyleSheet(
            f"color: {TEXT}; font-size: 18px; font-weight: 700; background: transparent;"
        )
    t.setWordWrap(True)
    lay.addWidget(t)
    if description:
        d = QLabel(description)
        d.setWordWrap(True)
        d.setStyleSheet(
            f"color: {MUTED}; font-size: 15px; line-height: 1.55; background: transparent;"
        )
        lay.addWidget(d)
    return box, lay


def _card(parent_layout: QVBoxLayout, title: str | None = None) -> QFrame:
    card = QFrame()
    card.setStyleSheet(f"""
        QFrame {{
            background-color: {BG_CARD};
            border: 1px solid {BORDER};
            border-radius: 10px;
        }}
    """)
    vbox = QVBoxLayout(card)
    vbox.setContentsMargins(16, 13, 16, 14)
    vbox.setSpacing(10)
    if title:
        vbox.addWidget(_section_label(title))
    parent_layout.addWidget(card)
    return card


def _btn(label: str, primary: bool = False, *, start_screen: bool = False) -> QPushButton:
    """start_screen: tipografía ~+25% en botones primarios de la pantalla de inicio."""
    b = QPushButton(label)
    if primary:
        fs, pad = (16, 14) if start_screen else (14, 12)
        b.setStyleSheet(f"""
            QPushButton {{
                background-color: {GOLD}; color: {TEXT_ON_GOLD};
                border: none; border-radius: 8px;
                font-size: {fs}px; font-weight: 700;
                padding: {pad}px; letter-spacing: 1px;
            }}
            QPushButton:hover {{ background-color: {GOLD_H}; }}
            QPushButton:disabled {{ background: {BG_CARD}; color: {MUTED}; }}
        """)
    return b


def _stabilize_combo_popup(combo: QComboBox) -> QComboBox:
    """Evita popups nativos vacíos de QComboBox en macOS usando una vista Qt explícita."""
    view = QListView(combo)
    view.setMouseTracking(False)
    view.setUniformItemSizes(True)
    view.setStyleSheet(f"""
        QListView {{
            background-color: {BG_INPUT};
            color: {TEXT};
            border: 1px solid {BORDER};
            outline: none;
            padding: 2px;
        }}
        QListView::item {{
            padding: 6px 10px;
            min-height: 24px;
        }}
        QListView::item:selected {{
            background-color: {GOLD};
            color: {TEXT_ON_GOLD};
        }}
    """)
    combo.setView(view)
    combo.setMaxVisibleItems(12)
    _macos_disable_native_chrome(view)
    _macos_disable_native_chrome(view.viewport())
    combo.hidePopup()
    return combo


_last_file_dialog_dir: Path | None = None


def _macos_disable_native_chrome(widget: QWidget) -> None:
    """Evita ventanas nativas fantasma (mini NSWindow con semáforos) en macOS."""
    if sys.platform != "darwin":
        return
    widget.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors, True)
    if hasattr(Qt.WidgetAttribute, "WA_MacShowFocusRect"):
        widget.setAttribute(Qt.WidgetAttribute.WA_MacShowFocusRect, False)


def _file_dialog_sidebar_urls() -> list[QUrl]:
    """Atajos del selector: incluye volúmenes USB en /Volumes/ (p. ej. KINGSTON)."""
    urls: list[QUrl] = []
    seen: set[str] = set()

    def _add(path: Path) -> None:
        try:
            resolved = path.expanduser().resolve()
        except OSError:
            return
        key = str(resolved)
        if key in seen or not resolved.exists():
            return
        seen.add(key)
        urls.append(QUrl.fromLocalFile(key))

    for path in (
        Path.home(),
        Path.home() / "Desktop",
        Path.home() / "Documents",
        Path.home() / "Downloads",
        BASE_DIR,
        BASE_DIR / "01_raw",
    ):
        _add(path)

    volumes = Path("/Volumes")
    if volumes.is_dir():
        for vol in sorted(volumes.iterdir(), key=lambda p: p.name.lower()):
            if vol.is_dir() and not vol.name.startswith("."):
                _add(vol)

    return urls


def _effective_file_dialog_start(start_dir: str) -> str:
    global _last_file_dialog_dir
    if _last_file_dialog_dir is not None and _last_file_dialog_dir.is_dir():
        return str(_last_file_dialog_dir)
    start = Path(start_dir).expanduser()
    if start.is_dir():
        return str(start)
    return str(Path.home())


def _remember_file_dialog_paths(paths: list[str]) -> None:
    global _last_file_dialog_dir
    for raw in paths:
        if not raw:
            continue
        parent = Path(raw).expanduser().parent
        if parent.is_dir():
            _last_file_dialog_dir = parent
            return


def _configure_file_dialog(dlg: QFileDialog, *, native_on_macos: bool = True) -> None:
    """Configura sidebar y, en macOS, preferir Finder nativo (USB / volúmenes externos)."""
    dlg.setSidebarUrls(_file_dialog_sidebar_urls())
    if sys.platform == "darwin" and native_on_macos:
        dlg.setOption(QFileDialog.Option.DontUseNativeDialog, False)
    else:
        dlg.setOption(QFileDialog.Option.DontUseNativeDialog, True)


def _stabilize_slot_list(lst: QListWidget) -> QListWidget:
    """Lista de ranuras sin popups ni ventanas nativas en macOS."""
    lst.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
    lst.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    lst.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)
    _macos_disable_native_chrome(lst)
    _macos_disable_native_chrome(lst.viewport())
    return lst


def _purge_orphan_top_level_windows(*, keep: QWidget | None = None) -> None:
    """Cierra ventanas Qt huérfanas que macOS muestra como mini ventanas «Python»."""
    app = QApplication.instance()
    if app is None:
        return
    main = keep.window() if keep is not None else None
    for w in list(app.topLevelWidgets()):
        if main is not None and w is main:
            continue
        if isinstance(w, QFileDialog):
            w.hide()
            w.close()
            w.deleteLater()
            continue
        if w.width() > 480 or w.height() > 480:
            continue
        title = w.windowTitle().strip()
        flags = w.windowFlags()
        if (
            title in ("", "Python")
            or bool(flags & Qt.WindowType.Popup)
            or bool(flags & Qt.WindowType.Tool)
            or (w.width() < 260 and w.height() < 260)
        ):
            w.hide()
            w.close()
            w.deleteLater()


def _dismiss_floating_artifacts(root: QWidget | None = None) -> None:
    """Cierra tooltips, popups de combo y ventanas huérfanas (macOS)."""
    QToolTip.hideText()
    _purge_orphan_top_level_windows(keep=root)
    _purge_orphan_qwindows(
        keep_window=root.windowHandle() if root is not None else None,
    )
    app = QApplication.instance()
    if app is not None:
        for w in app.topLevelWidgets():
            if isinstance(w, QFileDialog):
                w.hide()
                w.close()
    host = root or QApplication.activeWindow()
    if host is None:
        return
    for combo in host.findChildren(QComboBox):
        combo.hidePopup()
        view = combo.view()
        if view is not None:
            popup = view.window()
            if popup is not None and popup is not host.window():
                popup.hide()
                popup.close()


def _prepare_file_dialog() -> None:
    """Cierra popups flotantes antes de abrir un selector (artefacto macOS)."""
    _dismiss_floating_artifacts()


def _pick_open_file_names(
    parent: QWidget,
    title: str,
    start_dir: str,
    filt: str,
) -> tuple[list[str], str]:
    _prepare_file_dialog()
    dlg = QFileDialog(parent, title, _effective_file_dialog_start(start_dir), filt)
    _configure_file_dialog(dlg, native_on_macos=True)
    dlg.setFileMode(QFileDialog.FileMode.ExistingFiles)
    dlg.setViewMode(QFileDialog.ViewMode.List)
    if dlg.exec() != QDialog.DialogCode.Accepted:
        dlg.deleteLater()
        _dismiss_floating_artifacts(parent)
        return [], ""
    files = dlg.selectedFiles()
    selected = dlg.selectedNameFilter()
    dlg.deleteLater()
    _remember_file_dialog_paths(files)
    _dismiss_floating_artifacts(parent)
    return files, selected


def _pick_open_file_name(
    parent: QWidget,
    title: str,
    start_dir: str,
    filt: str,
) -> tuple[str, str]:
    _prepare_file_dialog()
    dlg = QFileDialog(parent, title, _effective_file_dialog_start(start_dir), filt)
    _configure_file_dialog(dlg, native_on_macos=True)
    dlg.setFileMode(QFileDialog.FileMode.ExistingFile)
    dlg.setViewMode(QFileDialog.ViewMode.List)
    if dlg.exec() != QDialog.DialogCode.Accepted:
        dlg.deleteLater()
        _dismiss_floating_artifacts(parent)
        return "", ""
    files = dlg.selectedFiles()
    selected = dlg.selectedNameFilter()
    dlg.deleteLater()
    _remember_file_dialog_paths(files)
    _dismiss_floating_artifacts(parent)
    return (files[0] if files else ""), selected


def _pick_save_file_name(
    parent: QWidget,
    title: str,
    start_dir: str,
    filt: str,
) -> tuple[str, str]:
    _prepare_file_dialog()
    dlg = QFileDialog(parent, title, _effective_file_dialog_start(start_dir), filt)
    _configure_file_dialog(dlg, native_on_macos=True)
    dlg.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
    dlg.setViewMode(QFileDialog.ViewMode.List)
    if dlg.exec() != QDialog.DialogCode.Accepted:
        dlg.deleteLater()
        _dismiss_floating_artifacts(parent)
        return "", ""
    files = dlg.selectedFiles()
    selected = dlg.selectedNameFilter()
    dlg.deleteLater()
    _remember_file_dialog_paths(files)
    _dismiss_floating_artifacts(parent)
    return (files[0] if files else ""), selected


class _SlotActionLabel(QLabel):
    """Etiqueta clicable en lugar de QPushButton (evita mini NSWindow «Python» en macOS)."""

    activated = pyqtSignal()

    def __init__(self, text: str, parent: QWidget | None = None):
        super().__init__(text, parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._enabled = True
        _macos_disable_native_chrome(self)

    def setEnabled(self, enabled: bool) -> None:  # noqa: N802 — API Qt
        self._enabled = enabled
        super().setEnabled(enabled)

    def mousePressEvent(self, event):
        if (
            self._enabled
            and event.button() == Qt.MouseButton.LeftButton
        ):
            self.activated.emit()
        super().mousePressEvent(event)


def _purge_orphan_qwindows(*, keep_window=None) -> None:
    """Cierra ventanas QWindow pequeñas (popups de combo/diálogo) no capturadas por topLevelWidgets."""
    app = QGuiApplication.instance()
    if app is None:
        return
    main = keep_window
    if main is None:
        active = QApplication.activeWindow()
        main = active.windowHandle() if active is not None else None
    for win in list(app.allWindows()):
        if main is not None and win is main:
            continue
        if win.width() > 480 or win.height() > 480:
            continue
        title = (win.title() or "").strip()
        if (
            title in ("", "Python")
            or (win.width() < 260 and win.height() < 260)
        ):
            win.hide()


def _open_with_system_default(parent: QWidget, path: Path) -> None:
    """Abre el documento para visualización: PDF en Preview, Word en Microsoft Word (macOS)."""
    import subprocess
    import sys

    if not path.is_file():
        QMessageBox.warning(parent, "No encontrado", f"El archivo no existe:\n{path}")
        return
    ext = path.suffix.lower()

    if sys.platform == "darwin":
        # Bundle IDs: independientes del idioma del sistema (p. ej. Preview vs «Vista previa»).
        commands_to_try: list[list[str]] = []
        if ext == ".pdf":
            commands_to_try = [
                ["open", "-b", "com.apple.Preview", str(path)],
                ["open", str(path)],
            ]
        elif ext in (".doc", ".docx"):
            commands_to_try = [
                ["open", "-b", "com.microsoft.Word", str(path)],
                ["open", "-b", "com.apple.Pages", str(path)],
                ["open", str(path)],
            ]
        else:
            commands_to_try = [["open", str(path)]]

        last_detail = ""
        for cmd in commands_to_try:
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode == 0:
                return
            last_detail = (r.stderr or r.stdout or "").strip() or f"código {r.returncode}"
        QMessageBox.warning(
            parent,
            "No se pudo abrir",
            "No se pudo mostrar el documento con Preview, Word, Pages ni la app "
            "predeterminada. Instala Microsoft Word o usa Preview para PDF.\n\n"
            f"Detalle: {last_detail}\n\n"
            f"Ruta:\n{path}",
        )
        return
    else:
        try:
            import os

            os.startfile(str(path))  # type: ignore[attr-defined]
        except (AttributeError, OSError) as e:
            r = subprocess.run(["xdg-open", str(path)], capture_output=True, text=True)
            if r.returncode != 0:
                QMessageBox.warning(parent, "No se pudo abrir", f"{e}\n\n{path}")


def _show_markdown_viewer(parent: QWidget, path: Path) -> None:
    """Muestra el contenido de un .md en una ventana de solo lectura (no depende de `open`)."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        QMessageBox.warning(parent, "Error", str(e))
        return
    dlg = QDialog(parent)
    dlg.setWindowTitle(f"Documento — {path.name}")
    dlg.setWindowFlags(
        Qt.WindowType.Window
        | Qt.WindowType.WindowTitleHint
        | Qt.WindowType.WindowCloseButtonHint
        | Qt.WindowType.WindowSystemMenuHint
    )
    dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
    dlg.resize(760, 600)
    dlg.setStyleSheet(f"background-color: {BG}; color: {TEXT};")
    vbox = QVBoxLayout(dlg)
    vbox.setContentsMargins(14, 14, 14, 14)
    vbox.setSpacing(10)

    top = QHBoxLayout()
    title_lbl = QLabel(path.name)
    title_lbl.setStyleSheet(f"color: {GOLD}; font-weight: 700; font-size: 14px;")
    title_lbl.setWordWrap(True)
    top.addWidget(title_lbl, 1)
    close_top = _btn("Cerrar", primary=True)
    close_top.setFixedHeight(36)
    close_top.setMinimumWidth(120)
    close_top.setToolTip("Cerrar esta ventana (también Esc o la X de la barra de título)")
    close_top.clicked.connect(dlg.close)
    top.addWidget(close_top, 0, Qt.AlignmentFlag.AlignTop)
    vbox.addLayout(top)

    viewer = QTextEdit()
    viewer.setReadOnly(True)
    viewer.setAcceptRichText(True)
    viewer.setStyleSheet(_qss_text_reader())
    viewer.document().setDefaultStyleSheet(_resolucion_viewer_document_css())
    viewer.document().setDocumentMargin(12)
    _vfont = QFont("Georgia", 13)
    viewer.setFont(_vfont)
    viewer.document().setDefaultFont(_vfont)
    if path.suffix.lower() == ".md":
        prepared = _markdown_resolve_local_images(text, path.parent)
        viewer.setMarkdown(prepared)
        # Qt a veces deja el visor en blanco con MD complejo; forzar texto plano si quedó vacío.
        if not viewer.toPlainText().strip():
            viewer.setPlainText(text)
    else:
        viewer.setPlainText(text)
    vbox.addWidget(viewer, 1)

    box = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Close,
    )
    b_close = box.button(QDialogButtonBox.StandardButton.Close)
    if b_close is not None:
        b_close.setText("Cerrar")
    box.rejected.connect(dlg.close)
    vbox.addWidget(box)

    esc = QShortcut(QKeySequence(Qt.Key.Key_Escape), dlg)
    esc.activated.connect(dlg.close)

    dlg.setModal(True)
    dlg.exec()


# ─── Pages ──────────────────────────────────────────────────────────────────


class InstruccionGeneralEdit(QPlainTextEdit):
    """Texto plano con pegado explícito (Cmd/Ctrl+V) para evitar fallos bajo QScrollArea / macOS."""

    def mousePressEvent(self, event):
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.StandardKey.Paste):
            clip = QApplication.clipboard()
            if clip is not None:
                t = clip.text()
                if t:
                    self.insertPlainText(t)
            event.accept()
            return
        super().keyPressEvent(event)


class NuevoCasoPage(QScrollArea):
    def __init__(
        self,
        open_case_cb=None,
        materia_getter=None,
        materia_setter=None,
        back_to_start_cb=None,
        welcome_only_cb=None,
        parent=None,
    ):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # No robar el foco: los QTextEdit deben recibir clic y teclado
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self._slot_files: dict[str, list[Path]] = {k: [] for k in SLOT_KEYS}
        self._slot_labels: dict[str, QLabel] = {}
        self._slot_panels: dict[str, QFrame] = {}
        self._slot_display_lbl: dict[str, QLabel] = {}
        self._slot_rm_btns: dict[str, _SlotActionLabel] = {}
        self._borrador_continuar: Path | None = None
        self._selected_plantilla: Path | None = None
        self._open_case_cb = open_case_cb        # callback(Path) → not used anymore
        self._back_to_start_cb = back_to_start_cb
        self._welcome_only_cb = welcome_only_cb  # bienvenida sin reset (conserva historial / borrador)
        self._existing_folder: Path | None = None  # set when editing an existing case
        self._materia_getter = materia_getter or (lambda: DEFAULT_MATERIA)
        self._materia_setter = materia_setter
        self._instruccion_materia_loaded: str | None = None
        self._last_folder_rel: str | None = None
        self._last_materia_prompt: str | None = None
        self._generate_kwargs: dict | None = None   # kwargs para ClaudeWorker
        self._worker: ClaudeWorker | None = None    # worker activo
        self._continuation_worker: ResolutionContinuationWorker | None = None
        self._resolution_incomplete_seq = 0
        self._last_prompt_for_continue = ""
        self._last_user_content_for_continue: str | list = ""
        self._last_output_validation: ValidationReport | None = None
        self._wiki_worker = None                    # worker wiki activo
        self._biblio_ingest_worker = None          # ingest Haiku doctrina desde bibliografía
        self._learning_worker = None               # aprendizaje silencioso desde correcciones
        self._corpus_manual_pick: list[Path] = []

        container = QWidget()
        self._layout = QVBoxLayout(container)
        self._layout.setContentsMargins(24, 20, 24, 24)
        self._layout.setSpacing(14)
        self.setWidget(container)

        self._build()

    def _build(self):
        lo = self._layout

        # ── Start panel (default view) — columna centrada, tarjetas, hero ────
        self._start_panel = QWidget()
        sp_root = QVBoxLayout(self._start_panel)
        sp_root.setContentsMargins(20, 16, 20, 24)
        sp_root.setSpacing(0)

        col_wrap = QWidget()
        col_wrap.setMaximumWidth(1120)
        col = QVBoxLayout(col_wrap)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(24)

        # Primera franja: solo el recuadro de marca / ADIUTOR IUDICIS (ancho completo)
        col.addWidget(_welcome_hero())

        # Debajo: texto guía + tarjetas en rejilla de dos columnas
        cards_grid = QGridLayout()
        cards_grid.setContentsMargins(0, 4, 0, 0)
        cards_grid.setHorizontalSpacing(22)
        cards_grid.setVerticalSpacing(22)
        cards_grid.setColumnStretch(0, 1)
        cards_grid.setColumnStretch(1, 1)
        cards_grid.setColumnMinimumWidth(0, 340)
        cards_grid.setColumnMinimumWidth(1, 340)

        intro_wrap = QWidget()
        intro_l = QVBoxLayout(intro_wrap)
        intro_l.setContentsMargins(0, 8, 0, 0)
        intro_l.setSpacing(10)
        _tag = QLabel(
            "Organiza por materia las fuentes, el corpus, las plantillas y el historial. "
            "Crea un expediente y prepara el borrador con tu flujo habitual (p. ej. Cursor o Claude API)."
        )
        _tag.setAlignment(Qt.AlignmentFlag.AlignCenter)
        _tag.setWordWrap(True)
        _tag.setStyleSheet(
            f"color: {MUTED}; font-size: 15px; line-height: 1.55; background: transparent;"
        )
        intro_l.addWidget(_tag)
        _steps = QLabel(
            "1 · Nuevo expediente  →  2 · Materia dentro del formulario  →  3 · Fuentes y «Preparar caso»"
        )
        _steps.setAlignment(Qt.AlignmentFlag.AlignCenter)
        _steps.setWordWrap(True)
        _steps.setStyleSheet(
            f"color: {GOLD}; font-size: 14px; font-weight: 600; background: transparent;"
        )
        intro_l.addWidget(_steps)
        cards_grid.addWidget(intro_wrap, 0, 0, 1, 2)

        # Instrucción general (visible al elegir materia en la barra lateral)
        self._ig_start_container = QWidget()
        self._ig_start_container.setObjectName("WelcomeSection")
        self._ig_start_container.setStyleSheet(
            f"QWidget#WelcomeSection {{"
            f" background-color: {BG_CARD};"
            f" border: 1px solid {BORDER};"
            f" border-radius: 16px;}}"
        )
        ig_v = QVBoxLayout(self._ig_start_container)
        ig_v.setContentsMargins(25, 20, 25, 22)
        ig_v.setSpacing(12)
        ig_head = QLabel("INSTRUCCIÓN GENERAL DE LA MATERIA")
        ig_head.setAlignment(Qt.AlignmentFlag.AlignLeft)
        ig_head.setStyleSheet(
            f"color: {GOLD}; font-size: 13px; font-weight: 700; letter-spacing: 2px; background: transparent;"
        )
        ig_v.addWidget(ig_head)
        ig_sub = QLabel(
            "Un .md por materia en 01_raw/instrucciones_generales/. Define tono, énfasis y criterios "
            "comunes; se usa al preparar casos y en el prompt a Claude."
        )
        ig_sub.setAlignment(Qt.AlignmentFlag.AlignLeft)
        ig_sub.setWordWrap(True)
        ig_sub.setStyleSheet(f"color: {MUTED}; font-size: 15px; line-height: 1.5; background: transparent;")
        ig_v.addWidget(ig_sub)
        self._instruccion_general_path_lbl = QLabel("")
        self._instruccion_general_path_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self._instruccion_general_path_lbl.setWordWrap(True)
        self._instruccion_general_path_lbl.setStyleSheet(f"color: {GOLD}; font-size: 14px;")
        ig_v.addWidget(self._instruccion_general_path_lbl)
        self._instruccion_general_edit = InstruccionGeneralEdit()
        self._instruccion_general_edit.setMinimumHeight(120)
        self._instruccion_general_edit.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._instruccion_general_edit.setLineWrapMode(
            QPlainTextEdit.LineWrapMode.WidgetWidth
        )
        self._instruccion_general_edit.setUndoRedoEnabled(True)
        ig_v.addWidget(self._instruccion_general_edit)
        ig_btn_row = QHBoxLayout()
        self._instruccion_general_save_btn = _btn("Guardar instrucción general", primary=False)
        self._instruccion_general_save_btn.setToolTip(
            "Guarda el texto en el archivo .md de esta materia."
        )
        self._instruccion_general_save_btn.clicked.connect(self._save_instruccion_general)
        ig_btn_row.addWidget(self._instruccion_general_save_btn)
        self._instruccion_general_open_folder_btn = _btn("Abrir carpeta", primary=False)
        self._instruccion_general_open_folder_btn.setToolTip(
            "Abre 01_raw/instrucciones_generales/ en el explorador de archivos."
        )
        self._instruccion_general_open_folder_btn.clicked.connect(
            self._open_instrucciones_generales_folder
        )
        ig_btn_row.addWidget(self._instruccion_general_open_folder_btn)
        ig_btn_row.addStretch()
        ig_v.addLayout(ig_btn_row)
        cards_grid.addWidget(self._ig_start_container, 1, 0, 1, 2)
        self._ig_start_container.setVisible(False)

        new_card, new_lay = _start_panel_card(
            "Nuevo expediente",
            "Crea la carpeta del caso bajo 01_raw/<materia>/ con las ranuras de fuentes. "
            "Luego podrás preparar el prompt y el borrador.",
            primary=True,
            min_height=432,
        )
        _apply_soft_shadow(new_card, blur=26, dy=6, alpha=58)
        create_btn = _btn("＋  Crear expediente", primary=True, start_screen=True)
        create_btn.setMinimumHeight(56)
        create_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        create_btn.setToolTip(
            "Abre el formulario para un expediente nuevo. Si ya hay un borrador o un caso del historial "
            "en curso, se pedirá confirmación antes de descartarlo."
        )
        create_btn.clicked.connect(self._on_create_expediente_clicked)
        new_lay.addWidget(create_btn)
        self._continue_expediente_btn = _btn("↩  Continuar expediente", primary=False, start_screen=True)
        self._continue_expediente_btn.setMinimumHeight(48)
        self._continue_expediente_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._continue_expediente_btn.setToolTip(
            "Vuelve al formulario sin pasar por «Crear expediente» (conserva expediente del historial o borrador)."
        )
        self._continue_expediente_btn.clicked.connect(self.resume_form_session)
        self._continue_expediente_btn.setVisible(False)
        new_lay.addWidget(self._continue_expediente_btn)
        new_lay.addStretch(1)
        cards_grid.addWidget(new_card, 2, 0)

        hist_card, hist_lay = _start_panel_card(
            "Expedientes recientes",
            "Solo se listan casos de la materia que tengas activa. Clic para abrir; "
            "el logo de la barra lateral vuelve a esta vista y permite cambiar de materia.",
            min_height=432,
        )
        self._hist_scope_lbl = QLabel("")
        self._hist_scope_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self._hist_scope_lbl.setWordWrap(True)
        self._hist_scope_lbl.setStyleSheet(
            f"color: {GOLD}; font-size: 15px; font-weight: 600; background: transparent;"
        )
        hist_lay.addWidget(self._hist_scope_lbl)
        self._hist_next_num_lbl = QLabel("")
        self._hist_next_num_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self._hist_next_num_lbl.setWordWrap(True)
        self._hist_next_num_lbl.setStyleSheet(
            f"color: {MUTED}; font-size: 15px; background: transparent;"
        )
        hist_lay.addWidget(self._hist_next_num_lbl)
        self._hist_list = QListWidget()
        self._hist_list.setStyleSheet(f"""
            QListWidget {{
                background-color: {READER_CANVAS};
                border: 1px solid {BORDER};
                border-radius: 8px;
                padding: 4px;
                outline: none;
            }}
            QListWidget::item {{
                padding: 10px 14px;
                border-radius: 6px;
                color: {TEXT};
                font-size: 16px;
            }}
            QListWidget::item:hover {{ background-color: {BG_INPUT}; color: {GOLD}; }}
            QListWidget::item:selected {{ background-color: {GOLD}; color: {TEXT_ON_GOLD}; font-weight: 700; }}
        """)
        self._hist_list.setMaximumHeight(220)
        self._hist_list.setMinimumHeight(100)
        self._hist_list.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self._hist_list.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        if hasattr(Qt.WidgetAttribute, "WA_MacShowFocusRect"):
            self._hist_list.setAttribute(Qt.WidgetAttribute.WA_MacShowFocusRect, False)
        self._hist_list.itemClicked.connect(self._open_historic_case)
        hist_lay.addWidget(self._hist_list)
        hist_hint = QLabel(
            "Clic en una fila para abrir. Si no ves listados, elige una materia en el árbol de la barra."
        )
        hist_hint.setAlignment(Qt.AlignmentFlag.AlignLeft)
        hist_hint.setWordWrap(True)
        hist_hint.setStyleSheet(f"color: {MUTED}; font-size: 14px; background: transparent;")
        hist_lay.addWidget(hist_hint)
        hist_lay.addStretch(1)
        _apply_soft_shadow(hist_card, blur=22, dy=5, alpha=42)
        cards_grid.addWidget(hist_card, 2, 1)

        cor_card, cor_lay = _start_panel_card(
            "Corpus del magistrado e índice wiki",
            "Resoluciones previas y fichas en 02_wiki/. Requiere materia (para la ruta 01_raw/<materia>/).",
            min_height=348,
        )
        self._corpus_start_lbl = QLabel("")
        self._corpus_start_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self._corpus_start_lbl.setWordWrap(True)
        self._corpus_start_lbl.setStyleSheet(
            f"color: {MUTED}; font-size: 14px; background: transparent;"
        )
        cor_lay.addWidget(self._corpus_start_lbl)
        cgrid = QGridLayout()
        cgrid.setHorizontalSpacing(10)
        cgrid.setVerticalSpacing(8)
        self._corpus_open_btn = _btn("Abrir carpeta corpus", primary=False)
        self._corpus_open_btn.setToolTip("01_raw/<materia>/corpus_magistrado/")
        self._corpus_open_btn.setMinimumHeight(40)
        self._corpus_open_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._corpus_open_btn.clicked.connect(self._open_corpus_magistrado_folder)
        self._corpus_add_btn = _btn("＋  Agregar al corpus", primary=True, start_screen=True)
        self._corpus_add_btn.setToolTip("PDFs/DOCX de resoluciones previas del magistrado")
        self._corpus_add_btn.setMinimumHeight(40)
        self._corpus_add_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._corpus_add_btn.clicked.connect(self._add_files_to_corpus)
        self._corpus_ingest_btn = _btn("⚙  Procesar pendiente", primary=False)
        self._corpus_ingest_btn.setToolTip(
            "Genera fichas wiki vía Haiku: si el PDF es decisorio desarrolla ratio decidendi; "
            "si es doctrina usa plantilla doctrinal. Paralelo: ADIUTOR_CORPUS_WORKERS "
            "(p. ej. 3). Tamaños: ADIUTOR_CORPUS_FICHA_* en .env."
        )
        self._corpus_ingest_btn.setMinimumHeight(40)
        self._corpus_ingest_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._corpus_ingest_btn.clicked.connect(self._run_corpus_ingestor)
        self._wiki_rebuild_btn = _btn("🔄  Reconstruir wiki", primary=False)
        self._wiki_rebuild_btn.setToolTip("Reconstruye INDEX.md y conexiones en 02_wiki/")
        self._wiki_rebuild_btn.setMinimumHeight(40)
        self._wiki_rebuild_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._wiki_rebuild_btn.clicked.connect(self._run_wiki_rebuild)
        cgrid.addWidget(self._corpus_open_btn, 0, 0)
        cgrid.addWidget(self._corpus_add_btn, 0, 1)
        cgrid.addWidget(self._corpus_ingest_btn, 1, 0)
        cgrid.addWidget(self._wiki_rebuild_btn, 1, 1)
        cor_lay.addLayout(cgrid)
        self._wiki_status_lbl = QLabel("")
        self._wiki_status_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self._wiki_status_lbl.setWordWrap(True)
        self._wiki_status_lbl.setStyleSheet(
            f"color: {MUTED}; font-size: 14px; background: transparent;"
        )
        cor_lay.addWidget(self._wiki_status_lbl)
        cor_lay.addStretch(1)
        _apply_soft_shadow(cor_card, blur=22, dy=5, alpha=42)
        cards_grid.addWidget(cor_card, 3, 0)

        glob_card, glob_lay = _start_panel_card(
            "Bibliografía global",
            "CPP, códigos y textos reutilizables en todos los casos. Carpeta: 01_raw/bibliografia/global/. "
            "Obsidian sólo puede abrir estos archivos automáticamente si el vault de Obsidian "
            "es esta misma carpeta del proyecto WikiJuez; si las notas están en otro vault, cópielas aquí.",
            min_height=348,
        )
        self._glob_bib_status_lbl = QLabel(self._glob_bib_status_text())
        self._glob_bib_status_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self._glob_bib_status_lbl.setWordWrap(True)
        self._glob_bib_status_lbl.setStyleSheet(
            f"color: {MUTED}; font-size: 14px; background: transparent;"
        )
        glob_lay.addWidget(self._glob_bib_status_lbl)
        glob_row = QHBoxLayout()
        glob_row.setSpacing(10)
        self._glob_bib_add_btn = _btn("＋  Agregar código o ley", primary=True, start_screen=True)
        self._glob_bib_add_btn.setToolTip(
            "Disponible en todos los casos y materias"
        )
        self._glob_bib_add_btn.setMinimumHeight(40)
        self._glob_bib_add_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._glob_bib_add_btn.clicked.connect(self._add_global_bibliografia)
        self._glob_bib_open_btn = _btn("Abrir carpeta", primary=False)
        self._glob_bib_open_btn.setMinimumHeight(40)
        self._glob_bib_open_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._glob_bib_open_btn.clicked.connect(self._open_global_bibliografia_folder)
        self._glob_bib_ficha_btn = _btn("📄 Fichas doctrina (Haiku)", primary=False)
        self._glob_bib_ficha_btn.setMinimumHeight(40)
        self._glob_bib_ficha_btn.setToolTip(
            "PDF/Word/md pendientes → 02_wiki/bibliografia/global/ usando el mismo tamaño/env "
            "ADIUTOR_CORPUS_FICHA_* que corpus y doctrina por materia."
        )
        self._glob_bib_ficha_btn.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self._glob_bib_ficha_btn.clicked.connect(self._run_bibliografia_ficha_global)
        glob_row.addWidget(self._glob_bib_add_btn, 1)
        glob_row.addWidget(self._glob_bib_open_btn, 1)
        glob_row.addWidget(self._glob_bib_ficha_btn, 1)
        glob_lay.addLayout(glob_row)
        glob_lay.addStretch(1)
        _apply_soft_shadow(glob_card, blur=22, dy=5, alpha=42)
        cards_grid.addWidget(glob_card, 3, 1)

        col.addLayout(cards_grid)

        # Centrar columna en pantallas anchas
        sp_center = QHBoxLayout()
        sp_center.setContentsMargins(0, 0, 0, 0)
        sp_center.addStretch(1)
        sp_center.addWidget(col_wrap, 0)
        sp_center.addStretch(1)
        sp_root.addLayout(sp_center)

        lo.addWidget(self._start_panel, 1)

        # ── Form panel (hidden until CREAR PROYECTO is clicked) ──────────────
        self._form_panel = QWidget()
        self._form_panel.setVisible(False)
        fv = QVBoxLayout(self._form_panel)
        fv.setContentsMargins(0, 0, 0, 0)
        fv.setSpacing(14)

        # Header: «Inicio» = misma lógica que logo/Casos; «Bienvenida» = solo ocultar formulario.
        head_row = QHBoxLayout()
        head_row.setSpacing(12)
        _head_nav_style = f"""
                QPushButton {{
                    background-color: {BG_CARD}; color: {GOLD};
                    border: 1px solid {GOLD}; border-radius: 8px;
                    padding: 6px 16px; font-size: 13px; font-weight: 600;
                }}
                QPushButton:hover {{ background-color: {GOLD}; color: {TEXT_ON_GOLD}; }}
            """
        if self._back_to_start_cb:
            back_inicio = QPushButton("←  Inicio")
            back_inicio.setToolTip(
                "Igual que el logo o «Casos» en la barra: vuelve a la bienvenida. "
                "Si el expediente se abrió desde el historial, se cierra esa sesión y se limpia el formulario. "
                "Si es un caso nuevo en curso, el borrador se conserva al usar «Crear expediente» otra vez."
            )
            back_inicio.setCursor(Qt.CursorShape.PointingHandCursor)
            back_inicio.setFixedHeight(36)
            back_inicio.setStyleSheet(_head_nav_style)
            back_inicio.clicked.connect(lambda: self._back_to_start_cb())
            head_row.addWidget(back_inicio, 0)
        if self._welcome_only_cb:
            btn_welcome = QPushButton("Bienvenida")
            btn_welcome.setToolTip(
                "Solo oculta el formulario y muestra la bienvenida: no cierra la sesión del expediente "
                "abierto desde el historial ni borra el borrador. Para cerrar sesión de un caso del historial "
                "usa «Inicio», el logo o «Casos»."
            )
            btn_welcome.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_welcome.setFixedHeight(36)
            btn_welcome.setStyleSheet(_head_nav_style)
            btn_welcome.clicked.connect(lambda: self._welcome_only_cb())
            head_row.addWidget(btn_welcome, 0)
        h = QLabel("NUEVO CASO")
        h.setStyleSheet(
            f"color: {GOLD}; font-size: 18px; font-weight: 700; letter-spacing: 2px;"
        )
        head_row.addWidget(h, 0)
        head_row.addStretch(1)
        fv.addLayout(head_row)
        sub = QLabel("Organiza archivos del expediente y genera la resolución")
        sub.setStyleSheet(f"color: {MUTED}; font-size: 12px;")
        fv.addWidget(sub)
        self._caso_materia_lbl = QLabel("")
        self._caso_materia_lbl.setWordWrap(True)
        self._caso_materia_lbl.setStyleSheet(f"color: {GOLD}; font-size: 12px;")
        fv.addWidget(self._caso_materia_lbl)

        # ── 1. Identificación ────────────────────────────────────────────────
        meta_card = _card(fv, "1 · IDENTIFICACIÓN")
        meta_row = QHBoxLayout()
        meta_row.setSpacing(12)

        materia_col = QVBoxLayout()
        materia_col.addWidget(QLabel("Materia"))
        self._materia_combo = QComboBox()
        _stabilize_combo_popup(self._materia_combo)
        self._materia_combo.setMinimumWidth(250)
        self._materia_combo.setToolTip(
            "Elige aquí la materia del expediente. Esta selección fija la ruta, "
            "la numeración, las ranuras, bibliografía, plantillas y prompt del caso."
        )
        self._materia_combo.addItem("Elige materia...", None)
        for slug, label in MATERIA_LABELS.items():
            self._materia_combo.addItem(label, slug)
        self._materia_combo.currentIndexChanged.connect(self._on_form_materia_changed)
        materia_col.addWidget(self._materia_combo)
        meta_row.addLayout(materia_col, 1)

        num_col = QVBoxLayout()
        num_col.addWidget(QLabel("Número (auto)"))
        self._num_lbl = QLineEdit()
        self._num_lbl.setReadOnly(True)
        self._num_lbl.setFixedWidth(90)
        num_col.addWidget(self._num_lbl)
        meta_row.addLayout(num_col)

        name_col = QVBoxLayout()
        name_col.addWidget(QLabel("Nombre del caso"))
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("fraude_bancario")
        name_col.addWidget(self._name_edit)
        meta_row.addLayout(name_col, 1)
        meta_card.layout().addLayout(meta_row)

        # ── 2. Fuentes por ranuras (6 slots según materia) ───────────────────
        fue_card = _card(
            fv,
            "2 · FUENTES DEL CASO  (6 ranuras — arrastra la calificación documental)",
        )
        fue_hint = QLabel(
            "Pulsa ＋ en cada ranura para elegir archivos (Finder: barra lateral → KINGSTON u otro USB). "
            "Doble clic en un archivo listado para abrirlo."
        )
        fue_hint.setWordWrap(True)
        fue_hint.setStyleSheet(f"color: {MUTED}; font-size: 11px;")
        fue_card.layout().addWidget(fue_hint)
        self._slots_wrap = QWidget()
        sv = QVBoxLayout(self._slots_wrap)
        sv.setContentsMargins(0, 0, 0, 0)
        sv.setSpacing(10)
        for slot_key in SLOT_KEYS:
            row = QHBoxLayout()
            row.setSpacing(10)
            left = QVBoxLayout()
            lab = QLabel("")
            lab.setWordWrap(True)
            lab.setStyleSheet(
                f"color: {GOLD}; font-size: 11px; font-weight: 600;"
            )
            self._slot_labels[slot_key] = lab
            panel = QFrame()
            panel.setMinimumHeight(48)
            panel.setMaximumHeight(100)
            _macos_disable_native_chrome(panel)
            panel.setStyleSheet(f"""
                QFrame {{
                    background-color: {BG_INPUT}; color: {TEXT};
                    border: 1px solid {BORDER}; border-radius: 6px;
                }}
            """)
            file_lay = QVBoxLayout(panel)
            file_lay.setContentsMargins(4, 4, 4, 4)
            file_lay.setSpacing(0)
            slot_lbl = QLabel("(ningún archivo)")
            slot_lbl.setWordWrap(True)
            slot_lbl.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
            slot_lbl.setCursor(Qt.CursorShape.PointingHandCursor)
            slot_lbl.setProperty("slot_key", slot_key)
            slot_lbl.setStyleSheet(
                f"color: {MUTED}; font-size: 11px; padding: 3px 6px; border-radius: 4px;"
            )
            _macos_disable_native_chrome(slot_lbl)
            slot_lbl.installEventFilter(self)
            file_lay.addWidget(slot_lbl)
            self._slot_panels[slot_key] = panel
            self._slot_display_lbl[slot_key] = slot_lbl
            left.addWidget(lab)
            left.addWidget(panel)
            row.addLayout(left, 1)
            bt_col = QVBoxLayout()
            add_b = _SlotActionLabel("＋")
            add_b.setMinimumSize(50, 44)
            add_b.setStyleSheet(f"""
                QLabel {{
                    background-color: {BG_INPUT};
                    color: {GOLD};
                    border: 2px solid {GOLD};
                    border-radius: 8px;
                    padding: 4px 6px;
                }}
            """)
            rm_b = _SlotActionLabel("✕")
            rm_b.setMinimumSize(50, 36)
            rm_b.setEnabled(False)
            rm_b.setStyleSheet(f"""
                QLabel {{
                    background-color: {BG_INPUT}; color: {ERROR};
                    border: 2px solid {ERROR}; border-radius: 8px; padding: 2px 6px;
                }}
            """)
            rm_b.activated.connect(
                lambda sk=slot_key: self._slot_remove(sk)
            )
            self._slot_rm_btns[slot_key] = rm_b
            add_b.activated.connect(lambda sk=slot_key: self._slot_add(sk))
            bt_col.addWidget(add_b)
            bt_col.addWidget(rm_b)
            if slot_key == "audio":
                tw = QPushButton()
                st = self.style()
                _ico_sz_s = QSize(24, 24)
                _im = st.standardIcon(QStyle.StandardPixmap.SP_MediaPlay)
                tw.setIcon(_im)
                tw.setIconSize(_ico_sz_s)
                if tw.icon().isNull():
                    tw.setText("🎙")
                tw.setMinimumSize(50, 36)
                tw.setCursor(Qt.CursorShape.PointingHandCursor)
                _macos_disable_native_chrome(tw)
                tw.setStyleSheet(f"""
                    QPushButton {{
                        background-color: {BG_INPUT};
                        color: {GOLD};
                        border: 2px solid {BORDER};
                        border-radius: 8px; padding: 2px 6px;
                    }}
                    QPushButton:hover {{ border: 2px solid {GOLD};
                        background-color: {BG_CARD}; }}
                """)
                tw.clicked.connect(lambda checked=False, sk=slot_key: self._slot_transcribe_audio(sk))
                bt_col.addWidget(tw)
            bt_col.addStretch()
            row.addLayout(bt_col)
            sv.addLayout(row)
        fue_card.layout().addWidget(self._slots_wrap)
        self._update_slot_title_labels()

        # ── 3. Configuración de la resolución ─────────────────────────────────
        cfg_card = _card(fv, "3 · CONFIGURACIÓN DE LA RESOLUCIÓN")
        tipo_row = QHBoxLayout()
        tipo_row.setSpacing(12)

        tipo_col = QVBoxLayout()
        tipo_col.addWidget(QLabel("Tipo de resolución"))
        self._tipo_combo = QComboBox()
        _stabilize_combo_popup(self._tipo_combo)
        self._tipo_combo.addItems([
            "Auto de Vista — Apelación PP",
            "Auto de Vista — Cese de PP",
            "Auto de Vista — Apelación Comparecencia",
            "Sentencia Plenaria",
            "Otro",
        ])
        tipo_col.addWidget(self._tipo_combo)
        tipo_row.addLayout(tipo_col, 1)

        postura_col = QVBoxLayout()
        postura_col.addWidget(QLabel("Postura judicial"))
        self._postura_combo = QComboBox()
        _stabilize_combo_popup(self._postura_combo)
        self._postura_combo.addItems([
            "Confirmar",
            "Revocar",
            "Revocar parcialmente",
            "Modificar",
            "Otros",
        ])
        self._postura_combo.currentTextChanged.connect(self._on_postura_changed)
        postura_col.addWidget(self._postura_combo)
        self._postura_otros_edit = QPlainTextEdit()
        self._postura_otros_edit.setPlaceholderText(
            "Solo si elegiste «Otros»: instrucciones concretas de postura o decisión."
        )
        self._postura_otros_edit.setFixedHeight(70)
        self._postura_otros_edit.setVisible(False)
        postura_col.addWidget(self._postura_otros_edit)
        tipo_row.addLayout(postura_col, 1)
        cfg_card.layout().addLayout(tipo_row)

        ag_row = QVBoxLayout()
        ag_row.addWidget(QLabel("Agravios de la defensa (opcional — uno por línea o párrafo corto)"))
        self._agravios_edit = QPlainTextEdit()
        self._agravios_edit.setFixedHeight(88)
        self._agravios_edit.setPlaceholderText(
            "Si ya los tienes identificados, pégalos aquí; si no, el modelo los extraerá del recurso."
        )
        ag_row.addWidget(self._agravios_edit)
        cfg_card.layout().addLayout(ag_row)

        modo_row = QHBoxLayout()
        modo_row.setSpacing(12)
        modo_l = QVBoxLayout()
        modo_l.addWidget(QLabel("Modo de trabajo"))
        self._modo_combo = QComboBox()
        _stabilize_combo_popup(self._modo_combo)
        self._modo_combo.addItems([
            "Generar resolución completa desde cero",
            "Continuar borrador del magistrado",
        ])
        self._modo_combo.setToolTip(
            "«Continuar borrador» requiere elegir un archivo (Markdown, Word, PDF o Pages). "
            "El botón «Elegir borrador…» también cambia solo a este modo si pulsas estando en «Generar…»."
        )
        modo_l.addWidget(self._modo_combo)
        modo_row.addLayout(modo_l, 1)
        modo_r = QVBoxLayout()
        modo_r.addWidget(QLabel("Borrador a continuar"))
        borrador_pick = QHBoxLayout()
        self._borrador_lbl = QLabel("(ninguno)")
        self._borrador_lbl.setStyleSheet(f"color: {MUTED}; font-size: 11px;")
        self._borrador_lbl.setWordWrap(True)
        self._btn_borrador_pick = _btn("Elegir borrador…")
        self._btn_borrador_pick.setToolTip(
            "Formatos: .md, .doc, .docx, .pdf, .pages. Carpeta típica: 03_outputs/resoluciones/<materia>/. "
            "Si no elegiste materia en la barra lateral, se abre la carpeta general de resoluciones."
        )
        self._btn_borrador_pick.clicked.connect(self._pick_borrador_continuar)
        borrador_pick.addWidget(self._borrador_lbl, 1)
        borrador_pick.addWidget(self._btn_borrador_pick)
        modo_r.addLayout(borrador_pick)
        modo_row.addLayout(modo_r, 1)
        cfg_card.layout().addLayout(modo_row)
        self._modo_combo.currentIndexChanged.connect(self._on_modo_changed)
        self._on_modo_changed()

        self._corpus_style_cb = QCheckBox(
            "Incluir hasta 3 resoluciones del corpus del magistrado como referencia de estilo (Bloque 6)"
        )
        self._corpus_style_cb.setStyleSheet(f"color: {TEXT}; font-size: 12px;")
        self._corpus_style_cb.setChecked(False)
        cfg_card.layout().addWidget(self._corpus_style_cb)
        corp_pick_row = QHBoxLayout()
        self._corpus_pick_lbl = QLabel("")
        self._corpus_pick_lbl.setWordWrap(True)
        self._corpus_pick_lbl.setStyleSheet(f"color: {MUTED}; font-size: 11px;")
        self._corpus_pick_btn = _btn("Elegir 3 fichas del corpus…", primary=False)
        self._corpus_pick_btn.setToolTip(
            "Elige hasta 3 fichas en 02_wiki/casos_previos/<materia>/. Si no eliges ninguna, "
            "se usan las 3 primeras por orden de nombre como hasta ahora."
        )
        self._corpus_pick_btn.clicked.connect(self._pick_corpus_fichas_manual)
        self._corpus_style_cb.toggled.connect(self._sync_corpus_pick_widgets_enabled)
        corp_pick_row.addWidget(self._corpus_pick_lbl, 1)
        corp_pick_row.addWidget(self._corpus_pick_btn, 0)
        cfg_card.layout().addLayout(corp_pick_row)
        self._refresh_corpus_pick_label()
        self._sync_corpus_pick_widgets_enabled()

        # ── Metadatos del caso (colapsable) ─────────────────────────────────
        meta_toggle = QPushButton("▾  Metadatos del caso")
        meta_toggle.setCheckable(True)
        meta_toggle.setChecked(True)
        meta_toggle.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {GOLD};
                border: none; font-size: 12px; text-align: left; padding: 4px 0; font-weight: 600;
            }}
            QPushButton:checked {{ color: {GOLD}; }}
        """)
        cfg_card.layout().addWidget(meta_toggle)

        self._meta_widget = QWidget()
        self._meta_widget.setVisible(True)
        meta_form = QVBoxLayout(self._meta_widget)
        meta_form.setContentsMargins(0, 4, 0, 0)
        meta_form.setSpacing(8)

        row1 = QHBoxLayout()
        row1.setSpacing(12)
        exp_col = QVBoxLayout()
        exp_col.addWidget(QLabel("N.° de expediente"))
        self._exp_edit = QLineEdit()
        self._exp_edit.setPlaceholderText("00492-2026-63-1411-JR-PE-01")
        exp_col.addWidget(self._exp_edit)
        row1.addLayout(exp_col, 2)
        juz_col = QVBoxLayout()
        juz_col.addWidget(QLabel("Juzgado de origen"))
        self._juz_edit = QLineEdit()
        self._juz_edit.setPlaceholderText("1.° JIP de Pisco")
        juz_col.addWidget(self._juz_edit)
        row1.addLayout(juz_col, 2)
        meta_form.addLayout(row1)

        meta_form.addWidget(QLabel("Imputado(s)"))
        self._imp_edit = QLineEdit()
        self._imp_edit.setPlaceholderText("JUAN PÉREZ FLORES / CARLOS RÍOS CUBA")
        meta_form.addWidget(self._imp_edit)

        row3 = QHBoxLayout()
        row3.setSpacing(12)
        del_col = QVBoxLayout()
        del_col.addWidget(QLabel("Delito"))
        self._del_edit = QLineEdit()
        self._del_edit.setPlaceholderText("Homicidio simple (art. 106 CP)")
        del_col.addWidget(self._del_edit)
        row3.addLayout(del_col, 1)
        agr_col = QVBoxLayout()
        agr_col.addWidget(QLabel("Agraviado"))
        self._agr_edit = QLineEdit()
        self._agr_edit.setPlaceholderText("Nombre del agraviado")
        agr_col.addWidget(self._agr_edit)
        row3.addLayout(agr_col, 1)
        meta_form.addLayout(row3)

        cfg_card.layout().addWidget(self._meta_widget)
        meta_toggle.toggled.connect(self._meta_widget.setVisible)
        meta_toggle.toggled.connect(
            lambda checked: meta_toggle.setText(
                "▾  Metadatos del caso" if checked
                else "▸  Metadatos del caso"
            )
        )

        ip_title = QLabel("Instrucción particular (este caso)")
        ip_title.setStyleSheet(f"color: {TEXT}; font-weight: 600; font-size: 12px;")
        cfg_card.layout().addWidget(ip_title)
        self._instruccion_edit = QTextEdit()
        self._instruccion_edit.setPlaceholderText(
            "Ej.: confirma/auto de vista; responde agravios por cada ranura…"
        )
        self._instruccion_edit.setFixedHeight(64)
        cfg_card.layout().addWidget(self._instruccion_edit)

        # ── 4. Bibliografía (colapsable — carga automática por materia) ──────────
        bib_card = _card(fv, None)
        bib_toggle = QPushButton("▸  Bibliografía  —  se carga automáticamente por materia")
        bib_toggle.setCheckable(True)
        bib_toggle.setChecked(False)
        bib_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        bib_toggle.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {MUTED};
                border: none; font-size: 12px; text-align: left; padding: 2px 0;
            }}
            QPushButton:checked {{ color: {GOLD}; }}
        """)
        bib_card.layout().addWidget(bib_toggle)
        self._bib_detail_widget = QWidget()
        self._bib_detail_widget.setVisible(False)
        bib_dv = QVBoxLayout(self._bib_detail_widget)
        bib_dv.setContentsMargins(0, 6, 0, 0)
        bib_dv.setSpacing(8)
        bib_top = QHBoxLayout()
        bib_btn = _btn("＋  Agregar doctrina / ley")
        bib_btn.clicked.connect(self._add_bib)
        self._bib_count = QLabel("")
        self._bib_count.setStyleSheet(f"color: {MUTED}; font-size: 11px;")
        bib_top.addWidget(bib_btn)
        bib_top.addStretch()
        bib_top.addWidget(self._bib_count)
        bib_dv.addLayout(bib_top)
        self._bib_list = QListWidget()
        self._bib_list.setMinimumHeight(40)
        self._bib_list.setMaximumHeight(110)
        bib_dv.addWidget(self._bib_list)
        bib_card.layout().addWidget(self._bib_detail_widget)
        bib_toggle.toggled.connect(self._bib_detail_widget.setVisible)
        bib_toggle.toggled.connect(
            lambda c: bib_toggle.setText(
                "▾  Bibliografía  —  se carga automáticamente por materia" if c
                else "▸  Bibliografía  —  se carga automáticamente por materia"
            )
        )

        # ── 5. Plantilla (colapsable — carga automática por materia) ──────────
        pla_card = _card(fv, None)
        pla_toggle = QPushButton("▸  Plantilla  —  se carga automáticamente por materia")
        pla_toggle.setCheckable(True)
        pla_toggle.setChecked(False)
        pla_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        pla_toggle.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {MUTED};
                border: none; font-size: 12px; text-align: left; padding: 2px 0;
            }}
            QPushButton:checked {{ color: {GOLD}; }}
        """)
        pla_card.layout().addWidget(pla_toggle)
        self._pla_detail_widget = QWidget()
        self._pla_detail_widget.setVisible(False)
        pla_dv = QVBoxLayout(self._pla_detail_widget)
        pla_dv.setContentsMargins(0, 6, 0, 0)
        pla_dv.setSpacing(8)
        self._pla_selected_lbl = QLabel("Ninguna seleccionada")
        self._pla_selected_lbl.setStyleSheet(f"color: {MUTED}; font-size: 12px; padding: 2px 0;")
        pla_dv.addWidget(self._pla_selected_lbl)
        pla_btn_row = QHBoxLayout()
        pla_sel_btn = _btn("📋  Cambiar plantilla")
        pla_sel_btn.clicked.connect(self._pick_plantilla_existing)
        self._pla_clear_btn = _btn("Sin plantilla", primary=False)
        self._pla_clear_btn.setToolTip(
            "Quita la plantilla seleccionada; el prompt usará sin_plantilla (solo instrucciones y fuentes)."
        )
        self._pla_clear_btn.clicked.connect(self._clear_plantilla_selection)
        self._pla_upload_btn = _btn("＋  Subir", primary=False)
        self._pla_upload_btn.clicked.connect(self._upload_plantilla_from_form)
        self._pla_open_btn = QPushButton("Abrir ↗")
        self._pla_open_btn.setFixedHeight(34)
        self._pla_open_btn.setEnabled(False)
        self._pla_open_btn.clicked.connect(self._open_plantilla)
        pla_btn_row.addWidget(pla_sel_btn)
        pla_btn_row.addWidget(self._pla_clear_btn)
        pla_btn_row.addWidget(self._pla_upload_btn)
        pla_btn_row.addStretch()
        pla_btn_row.addWidget(self._pla_open_btn)
        pla_dv.addLayout(pla_btn_row)
        pla_card.layout().addWidget(self._pla_detail_widget)
        pla_toggle.toggled.connect(self._pla_detail_widget.setVisible)
        pla_toggle.toggled.connect(
            lambda c: pla_toggle.setText(
                "▾  Plantilla  —  se carga automáticamente por materia" if c
                else "▸  Plantilla  —  se carga automáticamente por materia"
            )
        )

        # ── Prepare button ───────────────────────────────────────────────────
        self._prep_btn = _btn("PREPARAR CASO", primary=True)
        self._prep_btn.setMinimumHeight(50)
        self._prep_btn.clicked.connect(self._prepare)
        fv.addWidget(self._prep_btn)

        self._prompt_frame = QFrame()
        self._prompt_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {BG_CARD};
                border: 2px solid {GOLD};
                border-radius: 10px;
            }}
        """)
        pf_layout = QVBoxLayout(self._prompt_frame)
        pf_layout.setContentsMargins(18, 14, 18, 14)
        pf_layout.setSpacing(10)

        pf_header = QHBoxLayout()
        pf_title = QLabel("✓  Caso listo — genera la resolución:")
        pf_title.setStyleSheet(f"color: {SUCCESS}; font-weight: 700; font-size: 13px;")
        self._copy_prompt_btn = _btn("Copiar prompt")
        self._copy_prompt_btn.setFixedHeight(32)
        self._copy_prompt_btn.setVisible(False)   # oculto — se mantiene por compatibilidad interna
        self._copy_prompt_btn.clicked.connect(self._copy_prompt)
        pf_header.addWidget(pf_title)
        pf_header.addStretch()
        pf_layout.addLayout(pf_header)

        # ── Botón Generar con Claude ─────────────────────────────────────
        gen_row = QHBoxLayout()
        self._gen_claude_btn = QPushButton("⚡  GENERAR CON CLAUDE")
        self._gen_claude_btn.setFixedHeight(44)
        self._gen_claude_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {GEN_CLAUDE_BG};
                color: {GEN_CLAUDE_FG};
                border: 1px solid {GEN_CLAUDE_BORDER};
                border-radius: 8px;
                font-size: 14px; font-weight: 700;
                padding: 0 20px; letter-spacing: 1px;
            }}
            QPushButton:hover {{ background-color: {GEN_CLAUDE_HOVER_BG}; color: {GEN_CLAUDE_HOVER_FG}; }}
            QPushButton:disabled {{ background: {BG_CARD}; color: {MUTED}; border-color: {BORDER}; }}
        """)
        self._gen_claude_btn.setToolTip(
            "Genera el acto vía API Anthropic (Opus/Sonnet según .env). El prompt incluye el texto "
            "extraído en esta Mac (pdfplumber/OCR). No es el mismo motor que si usted sube el PDF al "
            "chat web de Claude: con ADIUTOR_API_PDF_ATTACH=1 (predeterminado) también se envían los PDF "
            "del caso como documento nativo en la API (mejor manuscritos/escaneos). Manuscrito difícil: "
            "archivo .txt/.md junto al PDF, o ADIUTOR_API_PDF_ATTACH=0 y ADIUTOR_VISION_PDF_PAGES=N "
            "(prototipo, primeras páginas como imagen; alto coste en tokens). Ver README."
        )
        self._gen_claude_btn.clicked.connect(self._generate_with_claude)
        self._cancel_gen_btn = QPushButton("✕ Cancelar")
        self._cancel_gen_btn.setFixedHeight(44)
        self._cancel_gen_btn.setVisible(False)
        self._cancel_gen_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {BG_CARD}; color: {ERROR};
                border: 1px solid {ERROR}; border-radius: 8px;
                font-size: 13px; font-weight: 600; padding: 0 16px;
            }}
            QPushButton:hover {{ background-color: {ERROR}; color: #ffffff; }}
        """)
        self._cancel_gen_btn.clicked.connect(self._cancel_generation)
        gen_row.addWidget(self._gen_claude_btn, 1)
        gen_row.addWidget(self._cancel_gen_btn)
        pf_layout.addLayout(gen_row)

        self._gen_status_lbl = QLabel("")
        self._gen_status_lbl.setStyleSheet(f"color: {MUTED}; font-size: 11px;")
        self._gen_status_lbl.setVisible(False)
        pf_layout.addWidget(self._gen_status_lbl)

        # ── Área de resolución generada (streaming) ──────────────────────
        self._gen_output_label = QLabel("Resolución generada — editable directamente")
        self._gen_output_label.setStyleSheet(
            f"color: {MUTED}; font-size: 11px; font-weight: 500;"
        )
        self._gen_output_label.setVisible(False)
        pf_layout.addWidget(self._gen_output_label)

        # Contenedor gris que simula el escritorio de Word
        self._word_canvas = QFrame()
        self._word_canvas.setStyleSheet("QFrame { background-color: #d0d0d0; border: none; }")
        self._word_canvas.setVisible(False)
        word_canvas_layout = QVBoxLayout(self._word_canvas)
        word_canvas_layout.setContentsMargins(40, 28, 40, 28)
        word_canvas_layout.setSpacing(0)

        self._gen_output_area = QTextEdit()
        self._gen_output_area.setReadOnly(False)
        self._gen_output_area.setMinimumHeight(520)
        self._gen_output_area.setStyleSheet(_qss_word_editor())
        _word_font = QFont("Arial Narrow", 14)
        _word_font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
        self._gen_output_area.setFont(_word_font)
        self._gen_output_area.document().setDefaultFont(_word_font)
        self._gen_output_area.document().setDocumentMargin(0)
        word_canvas_layout.addWidget(self._gen_output_area)
        pf_layout.addWidget(self._word_canvas)

        gen_copy_row = QHBoxLayout()
        # Botones ocultos permanentes (conservados para no romper referencias)
        self._gen_copy_btn = QPushButton()
        self._gen_copy_btn.setVisible(False)
        self._gen_copy_btn.clicked.connect(self._copy_gen_output)
        self._gen_save_btn = QPushButton()
        self._gen_save_btn.setVisible(False)
        self._gen_save_btn.clicked.connect(self._save_gen_output)
        self._gen_export_pdf_btn = QPushButton()
        self._gen_export_pdf_btn.setVisible(False)
        self._gen_export_pdf_btn.clicked.connect(self._export_gen_pdf)
        # ── Botones visibles ──────────────────────────────────────────────────
        self._gen_export_docx_btn = QPushButton("⬇  Abrir en Word")
        self._gen_export_docx_btn.setFixedHeight(38)
        self._gen_export_docx_btn.setVisible(False)
        self._gen_export_docx_btn.clicked.connect(self._export_gen_docx)
        self._gen_export_docx_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {GEN_CLAUDE_BG}; color: {GEN_CLAUDE_FG};
                border: 1px solid {GEN_CLAUDE_BORDER}; border-radius: 6px;
                font-size: 13px; font-weight: 700; padding: 0 18px;
            }}
            QPushButton:hover {{ background-color: {GEN_CLAUDE_HOVER_BG}; color: {GEN_CLAUDE_HOVER_FG}; }}
        """)
        self._gen_import_corrected_btn = QPushButton("\U0001f4c2  Word corregido → v2")
        self._gen_import_corrected_btn.setFixedHeight(38)
        self._gen_import_corrected_btn.setVisible(False)
        self._gen_import_corrected_btn.clicked.connect(self._import_corrected_word)
        self._gen_import_corrected_btn.setToolTip(
            "Selecciona el Word que corregiste en Microsoft Word. "
            "Claude lee las correcciones y genera una v2 limpia."
        )
        self._gen_import_corrected_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {BG_CARD}; color: {GOLD};
                border: 1px solid {GOLD}; border-radius: 6px;
                font-size: 13px; font-weight: 600; padding: 0 18px;
            }}
            QPushButton:hover {{ background-color: {GOLD}; color: {TEXT_ON_GOLD}; }}
        """)
        self._gen_expand_btn = QPushButton("⛶  Pantalla completa")
        self._gen_expand_btn.setFixedHeight(38)
        self._gen_expand_btn.setVisible(False)
        self._gen_expand_btn.clicked.connect(self._open_editor_fullscreen)
        self._gen_continue_btn = QPushButton("⚿  Continuar acto (Claude)")
        self._gen_continue_btn.setFixedHeight(30)
        self._gen_continue_btn.setVisible(False)
        self._gen_continue_btn.setToolTip(
            "Tras una salida cortada por límite de tokens o sin cierre claro: segunda llamada al modelo "
            "que sólo debe añadir lo faltante."
        )
        self._gen_continue_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {BG_CARD}; color: {GOLD};
                border: 1px solid {GOLD}; border-radius: 6px;
                font-size: 12px; font-weight: 600; padding: 0 12px;
            }}
            QPushButton:hover {{ background-color: {NAV_ROW_HOVER}; }}
            QPushButton:disabled {{ color: {MUTED}; border-color: {BORDER}; }}
        """)
        self._gen_continue_btn.clicked.connect(self._continue_resolution_generation)
        gen_copy_row.addWidget(self._gen_export_docx_btn)
        gen_copy_row.addWidget(self._gen_import_corrected_btn)
        gen_copy_row.addWidget(self._gen_expand_btn)
        gen_copy_row.addWidget(self._gen_continue_btn)
        gen_copy_row.addStretch()
        pf_layout.addLayout(gen_copy_row)

        self._prompt_area = QTextEdit()
        self._prompt_area.setReadOnly(True)
        self._prompt_area.setVisible(False)   # oculto — el prompt va directo a la API
        self._prompt_area.setMinimumHeight(160)
        self._prompt_area.setStyleSheet(_qss_text_code_readonly())
        pf_layout.addWidget(self._prompt_area)

        self._prompt_saved_lbl = QLabel("")
        self._prompt_saved_lbl.setWordWrap(True)
        self._prompt_saved_lbl.setStyleSheet(f"color: {SUCCESS}; font-size: 11px;")
        pf_layout.addWidget(self._prompt_saved_lbl)

        # ── Iteración sobre resolución generada ──────────────────────────────
        iter_sep = QLabel("── Iteración ─────────────────────────────────────────")
        iter_sep.setStyleSheet(f"color: {BORDER}; font-size: 11px;")
        pf_layout.addWidget(iter_sep)

        iter_hint = QLabel(
            "**Modo habitual — «✦ Aplicar modificaciones»:** el modelo debe devolver solo la corrección de lo que pide "
            "(un apartado, un fundamento, varios puntos…), no reescribir todo el auto salvo que usted así lo ordena "
            "en el cuadro. **Al final**, si ya acumula ajustes puntuales y desea una sola versión cerrada del acto con "
            "todo incorporado, use **«↯ Consolidar acto íntegro»** (lleva tiempo y tokens mayores)."
        )
        iter_hint.setWordWrap(True)
        iter_hint.setStyleSheet(f"color: {MUTED}; font-size: 11px;")
        pf_layout.addWidget(iter_hint)

        self._iter_instruccion_edit = QPlainTextEdit()
        self._iter_instruccion_edit.setMaximumHeight(88)
        self._iter_instruccion_edit.setPlaceholderText(
            "Instrucción para Claude — Ej.: corrige el considerando IV.2 conforme la Cas. 626-2013; "
            "amplía el análisis del peligro de fuga; cambia el dispositivo…"
        )
        pf_layout.addWidget(self._iter_instruccion_edit)

        self._iter_bib_chk = QCheckBox(
            "Reinyectar extracto de bibliografía en esta iteración "
            "(01_raw/bibliografia: consume más contexto)"
        )
        self._iter_bib_chk.setChecked(False)
        self._iter_bib_chk.setStyleSheet(f"color: {MUTED}; font-size: 11px;")
        iter_bib_row = QHBoxLayout()
        iter_bib_row.setSpacing(10)
        iter_bib_row.addWidget(self._iter_bib_chk)
        self._iter_bib_mode = QComboBox()
        _stabilize_combo_popup(self._iter_bib_mode)
        self._iter_bib_mode.addItem(
            "Coincidencia: nombre de archivo ↔ expediente en el acto",
            "matched",
        )
        self._iter_bib_mode.addItem(
            "Completa: materia + global (extractos truncados hasta un cupo)",
            "full",
        )
        self._iter_bib_mode.setToolTip(
            "«Coincidencia»: usa dígitos de expediente detectados en el texto del acto (p. ej. 01421-2023). "
            "«Completa»: incluye todos los archivos hasta el límite del sistema."
        )
        self._iter_bib_mode.setEnabled(False)
        self._iter_bib_chk.toggled.connect(self._iter_bib_mode.setEnabled)
        iter_bib_row.addWidget(self._iter_bib_mode, 1)
        pf_layout.addLayout(iter_bib_row)

        iter_btn_row = QHBoxLayout()
        self._apply_iter_btn = _btn("✦  Aplicar modificaciones", primary=True)
        self._apply_iter_btn.setMinimumHeight(40)
        self._apply_iter_btn.setVisible(False)
        self._apply_iter_btn.clicked.connect(lambda: self._apply_modifications(False))
        self._consolid_iter_btn = QPushButton("↯  Consolidar acto íntegro")
        self._consolid_iter_btn.setMinimumHeight(40)
        self._consolid_iter_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._consolid_iter_btn.setToolTip(
            "Genera una sola versión completa del acto integrando el texto actual (historial de ajustes puntuales, "
            "versiones intermedias si las hay). Use tras varios pasos «Aplicar modificaciones». "
            "Consume más tiempo y modelo que las correcciones puntuales."
        )
        self._consolid_iter_btn.setVisible(False)
        self._consolid_iter_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {BG_CARD}; color: {TEXT};
                border: 1px solid {CLAUDE_ACCENT}; border-radius: 8px;
                font-size: 12px; font-weight: 600; padding: 0 14px;
            }}
            QPushButton:hover {{
                background-color: {NAV_ROW_HOVER};
                border-color: {GOLD}; color: {GOLD};
            }}
        """)
        self._consolid_iter_btn.clicked.connect(lambda: self._apply_modifications(True))
        self._cancel_iter_btn = QPushButton("✕ Cancelar")
        self._cancel_iter_btn.setFixedHeight(40)
        self._cancel_iter_btn.setVisible(False)
        self._cancel_iter_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {BG_CARD}; color: {ERROR};
                border: 1px solid {ERROR}; border-radius: 8px;
                font-size: 13px; font-weight: 600; padding: 0 16px;
            }}
            QPushButton:hover {{ background-color: {ERROR}; color: #ffffff; }}
        """)
        self._cancel_iter_btn.clicked.connect(self._cancel_iteration)
        self._iter_status_lbl = QLabel("")
        self._iter_status_lbl.setStyleSheet(f"color: {MUTED}; font-size: 11px;")
        iter_btn_row.addWidget(self._apply_iter_btn, 1)
        iter_btn_row.addWidget(self._consolid_iter_btn, 1)
        iter_btn_row.addWidget(self._cancel_iter_btn)
        pf_layout.addLayout(iter_btn_row)
        pf_layout.addWidget(self._iter_status_lbl)

        # placeholder para compatibilidad interna
        self._cursor_respuesta_edit = QPlainTextEdit()
        self._cursor_respuesta_edit.setVisible(False)

        folder_row = QHBoxLayout()
        self._folder_lbl = QLabel("")
        self._folder_lbl.setStyleSheet(f"color: {MUTED}; font-size: 11px;")
        folder_row.addWidget(self._folder_lbl)
        folder_row.addStretch()
        new_case_btn = QPushButton("＋  Nuevo caso")
        new_case_btn.setFixedHeight(28)
        new_case_btn.setToolTip("Descarta el borrador de este formulario, limpia todo y vuelve al inicio")
        new_case_btn.clicked.connect(self._reset)
        folder_row.addWidget(new_case_btn)
        pf_layout.addLayout(folder_row)

        fv.addWidget(self._prompt_frame)
        self._prompt_frame.setVisible(False)
        fv.addStretch()

        lo.addWidget(self._form_panel)
        self.refresh_materia_dependent_ui()
        self._on_postura_changed()

    # ── Slots ────────────────────────────────────────────────────────────────

    def _open_corpus_magistrado_folder(self):
        m = self._current_materia()
        if m is None:
            QMessageBox.information(self, "Materia", "Elige una materia primero.")
            return
        path = str(dir_corpus_materia(m).resolve())
        try:
            if sys.platform == "darwin":
                subprocess.run(["open", path], check=False)
            elif sys.platform == "win32":
                os.startfile(path)  # type: ignore[attr-defined]
            else:
                QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        except Exception as e:
            QMessageBox.warning(self, "Carpeta", f"No se pudo abrir:\n{path}\n\n{e}")

    def _add_files_to_corpus(self):
        m = self._current_materia()
        if m is None:
            QMessageBox.information(self, "Materia", "Elige una materia primero en la barra lateral.")
            return
        files, _ = _pick_open_file_names(
            self,
            "Seleccionar resoluciones del magistrado",
            str(Path.home()),
            "Documentos (*.pdf *.docx *.doc *.pages);;PDF (*.pdf);;Word (*.docx *.doc);;Pages (*.pages);;Todos (*)",
        )
        if not files:
            return
        dest_dir = dir_corpus_materia(m)
        copiados = []
        errores = []
        for f in files:
            src = Path(f)
            dest = dest_dir / src.name
            try:
                import shutil as _shutil
                _shutil.copy2(src, dest)
                copiados.append(src.name)
            except Exception as e:
                errores.append(f"{src.name}: {e}")
        msg = f"{len(copiados)} archivo(s) agregado(s) al corpus."
        if errores:
            msg += "\n\nErrores:\n" + "\n".join(errores)
        QMessageBox.information(self, "Corpus actualizado", msg)
        # Auto-disparar ingestor para los archivos recién agregados
        if copiados:
            self._run_corpus_ingestor()

    def _glob_bib_status_text(self) -> str:
        files = list_bibliografia_global()
        if not files:
            return (
                "Sin archivos globales — agrega CP, CPP o Constitución en "
                "`01_raw/bibliografia/global/` (botón «Abrir carpeta»)."
            )
        names = ", ".join(f.name for f in files)
        return (
            f"{len(files)} archivo(s) detectado(s) para extracto de artículos al **generar con Claude**: "
            f"{names}."
        )

    def _add_global_bibliografia(self):
        files, _ = _pick_open_file_names(
            self,
            "Agregar código / ley global",
            str(Path.home()),
            "Documentos (*.pdf *.docx *.doc);;PDF (*.pdf);;Word (*.docx *.doc);;Todos (*)",
        )
        if not files:
            return
        copiados = []
        for f in files:
            try:
                add_bibliografia_global(Path(f))
                copiados.append(Path(f).name)
            except Exception as e:
                QMessageBox.critical(self, "Error", str(e))
        if copiados:
            self._glob_bib_status_lbl.setText(self._glob_bib_status_text())
            QMessageBox.information(
                self, "Bibliografía global",
                f"{len(copiados)} archivo(s) agregado(s):\n" + "\n".join(copiados),
            )

    def _open_global_bibliografia_folder(self):
        path = str(dir_bibliografia_global().resolve())
        try:
            if sys.platform == "darwin":
                subprocess.run(["open", path], check=False)
            else:
                QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        except Exception as e:
            QMessageBox.warning(self, "Carpeta", f"No se pudo abrir:\n{e}")

    def _run_corpus_ingestor(self):
        m = self._current_materia()
        if m is None:
            return
        if self._biblio_ingest_worker and self._biblio_ingest_worker.isRunning():
            QMessageBox.information(
                self, "Wiki",
                "Espere a que termine el ingest de fichas doctrina desde bibliografía.",
            )
            return
        if self._wiki_worker and self._wiki_worker.isRunning():
            return
        from app.core.file_manager import pending_corpus_pdfs
        pending = pending_corpus_pdfs(m)
        if not pending:
            if hasattr(self, "_wiki_status_lbl"):
                self._wiki_status_lbl.setText("Corpus al día — no hay documentos pendientes.")
            return
        if hasattr(self, "_wiki_status_lbl"):
            self._wiki_status_lbl.setText(f"Procesando corpus: 0/{len(pending)}…")
        self._wiki_worker = CorpusIngestorWorker(m, parent=self)
        self._wiki_worker.progress.connect(
            lambda cur, tot, name: self._wiki_status_lbl.setText(
                f"Procesando corpus: {cur}/{tot} — {name}"
            ) if hasattr(self, "_wiki_status_lbl") else None
        )
        self._wiki_worker.finished.connect(self._on_ingestor_finished)
        self._wiki_worker.error_occurred.connect(
            lambda msg: self._wiki_status_lbl.setText(f"Error corpus: {msg[:80]}")
            if hasattr(self, "_wiki_status_lbl") else None
        )
        self._wiki_worker.start()

    def _run_bibliografia_ficha_materia(self):
        """Genera fichas doctrina desde 01_raw/bibliografia/<materia>/ → 02_wiki/bibliografia/."""
        m = self._current_materia()
        if m is None:
            QMessageBox.information(
                self, "Materia",
                "Elige una materia en la barra lateral.",
            )
            return
        if self._wiki_worker and self._wiki_worker.isRunning():
            QMessageBox.information(
                self, "Wiki",
                "Ya hay una operación wiki en curso (corpus o reconstrucción).",
            )
            return
        if self._biblio_ingest_worker and self._biblio_ingest_worker.isRunning():
            return
        pending = pending_bibliografia_for_fichas(m)
        if not pending:
            if hasattr(self, "_wiki_status_lbl"):
                self._wiki_status_lbl.setText(
                    "Bibliografía al día — no hay archivos doctrina pendientes "
                    "(01_raw/bibliografia/…)."
                )
            return
        if hasattr(self, "_wiki_status_lbl"):
            self._wiki_status_lbl.setText(
                f"Fichas doctrina (Haiku): 0/{len(pending)}…"
            )
        self._biblio_ingest_worker = BibliografiaIngestorWorker(m, parent=self)
        self._biblio_ingest_worker.progress.connect(
            lambda cur, tot, name: self._wiki_status_lbl.setText(
                f"Fichas doctrina: {cur}/{tot} — {name}"
            ) if hasattr(self, "_wiki_status_lbl") else None
        )
        self._biblio_ingest_worker.finished.connect(self._on_biblio_ingest_finished)
        self._biblio_ingest_worker.error_occurred.connect(
            lambda msg: self._wiki_status_lbl.setText(f"Doctrina: {msg[:85]}…")
            if hasattr(self, "_wiki_status_lbl") else None
        )
        self._biblio_ingest_worker.start()

    def _run_bibliografia_ficha_global(self):
        """Fichas desde 01_raw/bibliografia/global/ → 02_wiki/bibliografia/global/."""
        if self._wiki_worker and self._wiki_worker.isRunning():
            QMessageBox.information(
                self, "Wiki",
                "Ya hay una operación wiki en curso (corpus o reconstrucción).",
            )
            return
        if self._biblio_ingest_worker and self._biblio_ingest_worker.isRunning():
            return
        pending = pending_bibliografia_global_for_fichas()
        if not pending:
            if hasattr(self, "_wiki_status_lbl"):
                self._wiki_status_lbl.setText(
                    "Bibliografía global al día — no hay pendientes de ficha doctrina."
                )
            return
        if hasattr(self, "_wiki_status_lbl"):
            self._wiki_status_lbl.setText(
                f"Fichas doctrina global: 0/{len(pending)}…"
            )
        self._biblio_ingest_worker = BibliografiaIngestorWorker(
            BIBLIO_INGEST_SCOPE_GLOBAL,
            parent=self,
        )
        self._biblio_ingest_worker.progress.connect(
            lambda cur, tot, name: self._wiki_status_lbl.setText(
                f"Doctrina global: {cur}/{tot} — {name}"
            ) if hasattr(self, "_wiki_status_lbl") else None
        )
        self._biblio_ingest_worker.finished.connect(self._on_biblio_ingest_finished)
        self._biblio_ingest_worker.error_occurred.connect(
            lambda msg: self._wiki_status_lbl.setText(f"Doctrina global: {msg[:85]}…")
            if hasattr(self, "_wiki_status_lbl") else None
        )
        self._biblio_ingest_worker.start()

    def _on_biblio_ingest_finished(self, n: int):
        if hasattr(self, "_wiki_status_lbl"):
            self._wiki_status_lbl.setText(
                f"✓ Doctrina: {n} ficha(s) nueva(s) en 02_wiki/bibliografia/ "
                "(pulse «Reconstruir wiki» para INDEX)."
            )

    def _on_ingestor_finished(self, n: int):
        if hasattr(self, "_wiki_status_lbl"):
            self._wiki_status_lbl.setText(
                f"✓ Corpus procesado: {n} ficha(s) nueva(s) generada(s)."
            )

    def _run_resolution_ficha(self):
        """Genera ficha wiki de la resolución recién creada (en background)."""
        if not self._last_folder_rel or not self._last_materia_prompt:
            return
        texto = self._gen_output_area.toPlainText().strip()
        if not texto:
            return
        kwargs = (self._generate_kwargs or {}).get("prompt_kwargs", {})
        w = ResolutionFichaWorker(
            materia=self._last_materia_prompt,
            folder_rel=self._last_folder_rel,
            resolution_text=texto,
            tipo=kwargs.get("tipo", "Resolución"),
            expediente=kwargs.get("expediente", ""),
            imputado=kwargs.get("imputados", ""),
            delito=kwargs.get("delito", ""),
            parent=self,
        )
        w.finished.connect(
            lambda ruta: self._gen_status_lbl.setText(f"✓ Guardada + ficha wiki: {ruta}")
        )
        w.error_occurred.connect(
            lambda msg: self._gen_status_lbl.setText(f"✓ Guardada (ficha wiki falló: {msg[:60]})")
        )
        w.start()

    def _run_wiki_rebuild(self):
        if self._biblio_ingest_worker and self._biblio_ingest_worker.isRunning():
            QMessageBox.information(
                self, "Wiki",
                "Espere a que termine el ingest de fichas doctrina.",
            )
            return
        if self._wiki_worker and self._wiki_worker.isRunning():
            QMessageBox.information(self, "Wiki", "Ya hay una operación wiki en curso.")
            return
        if hasattr(self, "_wiki_status_lbl"):
            self._wiki_status_lbl.setText("Reconstruyendo wiki…")
        self._wiki_worker = WikiRebuildWorker(parent=self)
        self._wiki_worker.status.connect(
            lambda msg: self._wiki_status_lbl.setText(msg)
            if hasattr(self, "_wiki_status_lbl") else None
        )
        self._wiki_worker.finished.connect(self._on_wiki_rebuild_finished)
        self._wiki_worker.error_occurred.connect(
            lambda msg: self._wiki_status_lbl.setText(f"Error wiki: {msg[:80]}")
            if hasattr(self, "_wiki_status_lbl") else None
        )
        self._wiki_worker.start()

    def _on_wiki_rebuild_finished(self):
        if hasattr(self, "_wiki_status_lbl"):
            self._wiki_status_lbl.setText("✓ Wiki reconstruido — abre Obsidian para ver los cambios.")

    def _current_materia(self) -> str | None:
        """Materia efectiva del caso: primero el combo del formulario, luego la barra lateral."""
        if hasattr(self, "_materia_combo"):
            data = self._materia_combo.currentData(Qt.ItemDataRole.UserRole)
            if isinstance(data, str) and data in MATERIA_SLUGS:
                return data
        m = self._materia_getter()
        return m if isinstance(m, str) and m in MATERIA_SLUGS else None

    def _hide_all_combo_popups(self) -> None:
        for attr in (
            "_materia_combo", "_tipo_combo", "_postura_combo",
            "_modo_combo", "_iter_bib_mode",
        ):
            combo = getattr(self, attr, None)
            if isinstance(combo, QComboBox):
                combo.hidePopup()
                view = combo.view()
                if view is not None:
                    popup = view.window()
                    if popup is not None and popup is not self.window():
                        popup.hide()
                        popup.close()
        _purge_orphan_top_level_windows(keep=self)

    def _sync_form_materia_combo(self, materia: str | None = None):
        if not hasattr(self, "_materia_combo"):
            return
        target = materia if materia in MATERIA_SLUGS else self._materia_getter()
        idx = self._materia_combo.findData(target, Qt.ItemDataRole.UserRole)
        self._materia_combo.blockSignals(True)
        try:
            self._materia_combo.setCurrentIndex(idx if idx >= 0 else 0)
        finally:
            self._materia_combo.blockSignals(False)
        self._materia_combo.hidePopup()

    def _on_form_materia_changed(self):
        m = self._current_materia()
        if m and self._materia_setter:
            self._materia_setter(m)
        self.refresh_materia_dependent_ui()

    def refresh_materia_dependent_ui(self):
        """Sincroniza número sugerido e historial con la materia de la barra lateral."""
        m = self._current_materia()
        if m is None:
            self._caso_materia_lbl.setText(
                "Sin materia activa — despliega la barra lateral y elige una materia "
                "(clic en el nombre de la materia o en Bibliografía / Plantillas / Resoluciones)."
            )
            self._hist_scope_lbl.setText("Mostrando expedientes: (elige una materia primero)")
            self._hist_next_num_lbl.setText(
                "Numeración por materia: elige una materia para ver el siguiente número de expediente."
            )
            if hasattr(self, "_corpus_start_lbl"):
                self._corpus_start_lbl.setText("")
        else:
            lab = materia_label(m)
            self._caso_materia_lbl.setText(
                f"Materia activa: {lab} — los nuevos expedientes se crean en "
                f"`01_raw/{m}/caso_NNN_nombre/`."
            )
            self._hist_scope_lbl.setText(f"Mostrando expedientes de: {lab}")
            next_n = get_next_case_number(m)
            self._hist_next_num_lbl.setText(
                f"Siguiente número en esta materia (conteo propio): {next_n:03d}  →  "
                f"01_raw/{m}/caso_{next_n:03d}_…"
            )
            if hasattr(self, "_corpus_start_lbl"):
                pend = len(pending_corpus_pdfs(m))
                self._corpus_start_lbl.setText(
                    f"Corpus magistrado: {pend} PDF(s) sin ficha wiki en "
                    f"`01_raw/{m}/corpus_magistrado/` (el ingestor fino sigue siendo desde Cursor)."
                )
        if self._form_panel.isVisible() and self._existing_folder is None:
            self._refresh_num()
        self._reload_history()
        self._sync_instruccion_general_widget()
        self._update_slot_title_labels()
        if hasattr(self, "_ig_start_container"):
            self._ig_start_container.setVisible(m is not None)
        self._revalidate_corpus_manual_pick()
        self._sync_corpus_pick_widgets_enabled()
        self._update_continue_button_visibility()

    def _sync_instruccion_general_widget(self):
        """Carga la instrucción general desde disco al cambiar de materia (un .md por materia)."""
        m = self._current_materia()
        self._instruccion_general_open_folder_btn.setEnabled(True)
        if m is None:
            self._instruccion_general_edit.clear()
            self._instruccion_general_edit.setPlaceholderText(
                "Elige una materia en la barra lateral (clic en su nombre o en Bibliografía / "
                "Plantillas / Resoluciones); luego podrás escribir aquí."
            )
            self._instruccion_general_edit.setEnabled(False)
            self._instruccion_general_save_btn.setEnabled(False)
            self._instruccion_general_path_lbl.setText("")
            self._instruccion_materia_loaded = None
            return
        self._instruccion_general_edit.setEnabled(True)
        self._instruccion_general_save_btn.setEnabled(True)
        self._instruccion_general_path_lbl.setText(
            f"📁  01_raw/instrucciones_generales/{m}.md"
        )
        self._instruccion_general_edit.setPlaceholderText(
            "Criterios comunes a todos los expedientes de esta materia: tono, énfasis, líneas argumentales, "
            "citación… Pulsa «Guardar instrucción general» para conservar el archivo."
        )
        if self._instruccion_materia_loaded != m:
            self._instruccion_general_edit.setPlainText(read_instruccion_general(m))
            self._instruccion_materia_loaded = m

    def _save_instruccion_general(self):
        m = self._current_materia()
        if m is None:
            QMessageBox.information(
                self, "Materia",
                "Elige primero una materia en la barra lateral.",
            )
            return
        try:
            save_instruccion_general(m, self._instruccion_general_edit.toPlainText())
        except OSError as e:
            QMessageBox.critical(self, "Error", f"No se pudo guardar:\n{e}")
            return
        self._instruccion_materia_loaded = m
        QMessageBox.information(
            self, "Guardado",
            f"Instrucción general guardada para esta materia.\n\n"
            f"01_raw/instrucciones_generales/{m}.md",
        )

    def _open_instrucciones_generales_folder(self):
        """Abre `01_raw/instrucciones_generales/` en el Finder / explorador."""
        d = dir_instrucciones_generales()
        path = str(d.resolve())
        try:
            if sys.platform == "darwin":
                subprocess.run(["open", path], check=False)
            elif sys.platform == "win32":
                os.startfile(path)  # type: ignore[attr-defined]
            else:
                QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        except Exception as e:
            QMessageBox.warning(
                self,
                "No se pudo abrir la carpeta",
                f"Ábrela manualmente:\n\n{path}\n\n{e}",
            )

    def _reload_history(self):
        self._hist_list.clear()
        m = self._current_materia()
        if m is None:
            item = QListWidgetItem(
                "Elige una materia en la barra lateral (clic en «Prisión preventiva», "
                "«Beneficios penitenciarios» o «Apelación de sentencias», o en una subsección)."
            )
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            item.setForeground(__import__("PyQt6.QtGui", fromlist=["QColor"]).QColor(MUTED))
            self._hist_list.addItem(item)
            return
        cases = list_case_folders(materia=m)
        if not cases:
            item = QListWidgetItem(
                "Sin expedientes en esta materia — pulsa «CREAR PROYECTO NUEVO»"
            )
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            item.setForeground(__import__("PyQt6.QtGui", fromlist=["QColor"]).QColor(MUTED))
            self._hist_list.addItem(item)
            return
        raw_root = BASE_DIR / "01_raw"
        for folder in cases:
            try:
                rel = folder.relative_to(raw_root)
                label = str(rel).replace("\\", "/")
            except ValueError:
                label = folder.name
            item = QListWidgetItem(f"📁  {label}")
            item.setData(Qt.ItemDataRole.UserRole, folder)
            self._hist_list.addItem(item)

    def _open_historic_case(self, item: QListWidgetItem):
        _dismiss_floating_artifacts(self)
        folder: Path | None = item.data(Qt.ItemDataRole.UserRole)
        if folder is None:
            return
        flags = item.flags()
        if not (flags & Qt.ItemFlag.ItemIsEnabled):
            return
        self._load_existing_case(folder)

    def _load_existing_case(self, folder: Path):
        """Open the form pre-filled with an existing case — same UI as new case."""
        _dismiss_floating_artifacts(self)
        self._existing_folder = folder
        for materia in MATERIA_SLUGS:
            if (BASE_DIR / "01_raw" / materia) in folder.parents or folder.parent.name == materia:
                self._sync_form_materia_combo(materia)
                break

        # Parse number and name from folder name: caso_003_homicidio_pp_492
        parts = folder.name.split("_", 2)
        num_str = parts[1] if len(parts) > 1 else "?"
        name_str = parts[2] if len(parts) > 2 else folder.name

        self._num_lbl.setText(num_str)
        self._name_edit.setText(name_str)
        self._name_edit.setReadOnly(True)
        self._name_edit.setStyleSheet(
            f"background-color: {BG_INPUT}; color: {MUTED};"
            f" border: 1px solid {BORDER}; border-radius: 6px; padding: 8px 12px;"
        )

        self._clear_slot_ui()
        loaded = read_fuentes_slots(folder)
        for key in SLOT_KEYS:
            self._slot_files[key] = list(loaded[key])
            self._rebuild_slot_display(
                key,
                muted=bool(self._slot_files[key]),
                case_folder=folder if self._slot_files[key] else None,
            )

        self._prep_btn.setText("PREPARAR CASO")

        # No arrastrar modo «continuar borrador» ni plantilla de otra sesión al abrir un expediente del historial.
        self._modo_combo.blockSignals(True)
        self._modo_combo.setCurrentIndex(0)
        self._modo_combo.blockSignals(False)
        self._borrador_continuar = None
        self._borrador_lbl.setText("(ninguno)")
        self._clear_plantilla_selection()

        self._start_panel.setVisible(False)
        self._form_panel.setVisible(True)
        self._hide_all_combo_popups()
        for delay in (0, 50, 120, 350, 700):
            QTimer.singleShot(delay, self._hide_all_combo_popups)
            QTimer.singleShot(delay, lambda _self=self: _dismiss_floating_artifacts(_self))

        # Cargar resolución previa si existe
        self._load_existing_resolucion(folder)
        _dismiss_floating_artifacts(self)

    def _load_existing_resolucion(self, folder: Path):
        """Si hay una resolución guardada para este caso, la carga en el área de output."""
        from app.core.file_manager import (
            MATERIA_SLUGS,
            DIRS,
            find_resolucion_md_for_case,
        )
        # Determinar materia desde la ruta de la carpeta
        materia = None
        for m in MATERIA_SLUGS:
            if (BASE_DIR / "01_raw" / m) in folder.parents or folder.parent.name == m:
                materia = m
                break
        if materia is None:
            return

        resolucion_path = find_resolucion_md_for_case(folder, materia)
        if resolucion_path is None:
            self._gen_output_area.clear()
            self._gen_status_lbl.setStyleSheet(f"color: {MUTED}; font-size: 11px;")
            self._gen_status_lbl.setText(
                "No se enlazó ningún .md de resolución con esta carpeta. "
                "Si el archivo está en la pestaña «Resoluciones», el nombre puede no coincidir "
                "con el expediente; renombra el .md a <carpeta>_resolucion.md o regenera."
            )
            self._gen_status_lbl.setVisible(True)
            return

        texto = resolucion_path.read_text(encoding="utf-8", errors="replace").strip()
        # Quitar el comentario de cabecera si existe
        if texto.startswith("<!--"):
            end = texto.find("-->")
            if end != -1:
                texto = texto[end + 3:].strip()

        if not texto:
            return

        # Determinar folder_rel para guardar/exportar
        raw = BASE_DIR / "01_raw"
        try:
            folder_rel = str(folder.relative_to(raw)).replace("\\", "/")
        except ValueError:
            folder_rel = folder.name

        # Cargar en la UI
        self._last_folder_rel = folder_rel
        self._last_materia_prompt = materia

        self._gen_output_area.setPlainText(texto)
        self._word_canvas.setVisible(True)
        self._gen_output_label.setVisible(True)
        self._gen_status_lbl.setText(f"Resolución cargada: {resolucion_path.name}")
        self._gen_status_lbl.setVisible(True)
        self._gen_copy_btn.setVisible(True)
        self._gen_save_btn.setVisible(True)
        self._gen_expand_btn.setVisible(True)
        self._gen_export_docx_btn.setVisible(True)
        self._gen_import_corrected_btn.setVisible(True)
        self._gen_export_pdf_btn.setVisible(True)
        self._apply_iter_btn.setVisible(True)
        self._consolid_iter_btn.setVisible(True)
        self._prompt_frame.setVisible(True)
        self._gen_claude_btn.setEnabled(True)

    def can_resume_case_session(self) -> bool:
        """Hay expediente del historial, borrador o datos que «Continuar expediente» puede reabrir."""
        if self._existing_folder is not None:
            return True
        if self._name_edit.text().strip():
            return True
        if any(self._slot_files[k] for k in SLOT_KEYS):
            return True
        if self._selected_plantilla is not None:
            return True
        if self._borrador_continuar is not None:
            return True
        if self._modo_combo.currentIndex() != 0:
            return True
        if self._bib_list.count() > 0:
            return True
        if self._instruccion_edit.toPlainText().strip():
            return True
        if self._agravios_edit.toPlainText().strip():
            return True
        if self._postura_otros_edit.toPlainText().strip():
            return True
        if self._tipo_combo.currentIndex() != 0:
            return True
        if self._postura_combo.currentIndex() != 0:
            return True
        if self._corpus_style_cb.isChecked():
            return True
        if getattr(self, "_corpus_manual_pick", None):
            return True
        if self._prompt_frame.isVisible():
            return True
        if self._prompt_area.toPlainText().strip():
            return True
        if self._gen_output_area.toPlainText().strip():
            return True
        if self._cursor_respuesta_edit.toPlainText().strip():
            return True
        for _w in (
            self._exp_edit,
            self._imp_edit,
            self._del_edit,
            self._agr_edit,
            self._juz_edit,
        ):
            if _w.text().strip():
                return True
        return False

    def resume_form_session(self):
        """Muestra el formulario sin tocar `_existing_folder` ni el borrador (tras «Bienvenida» o similar)."""
        if not self.can_resume_case_session():
            return
        self._start_panel.setVisible(False)
        self._form_panel.setVisible(True)

    def _on_create_expediente_clicked(self):
        if self.can_resume_case_session():
            reply = QMessageBox.question(
                self,
                "Nuevo expediente",
                "Ya hay un expediente o borrador en curso. ¿Descartarlo y comenzar uno nuevo desde cero?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            self._clear_case_draft_shared()
        self._show_form()

    def _update_continue_button_visibility(self):
        if hasattr(self, "_continue_expediente_btn"):
            self._continue_expediente_btn.setVisible(self.can_resume_case_session())

    def _show_form(self):
        self._existing_folder = None
        self._sync_form_materia_combo()
        self._name_edit.setReadOnly(False)
        self._name_edit.setStyleSheet("")
        self._start_panel.setVisible(False)
        self._form_panel.setVisible(True)
        self._refresh_num()

    def _refresh_num(self):
        m = self._current_materia()
        if m is None:
            self._num_lbl.setText("—")
            return
        self._next_num = get_next_case_number(m)
        self._num_lbl.setText(f"{self._next_num:03d}")

    def _add_bib(self):
        m = self._current_materia()
        if m is None:
            QMessageBox.information(
                self, "Materia",
                "Elige primero una materia en la barra lateral.",
            )
            return
        paths, _ = _pick_open_file_names(
            self, "Agregar bibliografía (PDF o Word)",
            str(dir_bibliografia_materia(m)),
            BIBLIO_QFILE_FILTER,
        )
        for p in paths:
            try:
                add_bibliografia(Path(p), materia=m)
                self._bib_list.addItem(QListWidgetItem(f"📚  {Path(p).name}"))
            except Exception as e:
                QMessageBox.warning(self, "Error", f"No se pudo copiar {Path(p).name}:\n{e}")
        n = self._bib_list.count()
        self._bib_count.setText(f"{n} archivo{'s' if n != 1 else ''}" if n else "")

    def _clear_plantilla_selection(self):
        """Quita la plantilla activa (equivalente a sin_plantilla en build_cursor_prompt)."""
        self._selected_plantilla = None
        self._pla_selected_lbl.setText("Ninguna seleccionada")
        self._pla_selected_lbl.setStyleSheet(
            f"color: {MUTED}; font-size: 12px; padding: 4px 0;"
        )
        self._pla_open_btn.setEnabled(False)

    def _pick_plantilla_existing(self):
        m = self._current_materia()
        if m is None:
            QMessageBox.information(
                self, "Materia",
                "Elige primero una materia en la barra lateral.",
            )
            return
        plantillas = list_plantillas(m)
        if not plantillas:
            QMessageBox.information(
                self, "Sin plantillas",
                "No hay plantillas guardadas aún.\nUsa '＋ Subir nueva plantilla' para agregar una."
            )
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("Seleccionar plantilla")
        dlg.resize(520, 320)
        dlg.setStyleSheet(f"background-color: {BG}; color: {TEXT};")
        dv = QVBoxLayout(dlg)
        dv.setContentsMargins(16, 16, 16, 16)
        dv.setSpacing(10)

        lbl = QLabel("Selecciona la plantilla a usar:")
        lbl.setStyleSheet(f"color: {GOLD}; font-weight: 700; font-size: 13px;")
        dv.addWidget(lbl)

        lst = QListWidget()
        lst.setStyleSheet(f"""
            QListWidget {{
                background-color: {BG_INPUT}; color: {TEXT};
                border: 1px solid {BORDER}; border-radius: 6px; padding: 4px;
            }}
            QListWidget::item {{ padding: 8px 10px; border-radius: 4px; }}
            QListWidget::item:selected {{ background-color: {GOLD}; color: {BG}; font-weight: 600; }}
        """)
        plantillas_dir = DIRS["plantillas"] / m
        for p in plantillas:
            try:
                rel = p.relative_to(plantillas_dir)
                label = str(rel) if len(rel.parts) > 1 else p.name
            except ValueError:
                label = p.name
            item = QListWidgetItem(f"📋  {label}")
            item.setData(Qt.ItemDataRole.UserRole, p)
            lst.addItem(item)
        if lst.count():
            lst.setCurrentRow(0)
        dv.addWidget(lst, 1)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.button(QDialogButtonBox.StandardButton.Ok).setText("Seleccionar")
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        dv.addWidget(btns)

        if dlg.exec() == QDialog.DialogCode.Accepted:
            item = lst.currentItem()
            if item:
                self._selected_plantilla = item.data(Qt.ItemDataRole.UserRole)
                try:
                    rel = self._selected_plantilla.relative_to(DIRS["plantillas"] / m)
                    label = str(rel) if len(rel.parts) > 1 else self._selected_plantilla.name
                except ValueError:
                    label = self._selected_plantilla.name
                self._pla_selected_lbl.setText(f"📋  {label}")
                self._pla_selected_lbl.setStyleSheet(
                    f"color: {GOLD}; font-size: 12px; padding: 4px 0; font-weight: 600;"
                )
                self._pla_open_btn.setEnabled(True)

    def _open_plantilla(self, *_):
        if not self._selected_plantilla:
            return
        path = self._selected_plantilla
        if path.suffix.lower() in (".pdf", ".docx", ".doc"):
            _open_with_system_default(self, path)
        else:
            _show_markdown_viewer(self, path)

    def _update_slot_title_labels(self):
        m = self._current_materia()
        if m is None:
            labels = slot_labels_for(DEFAULT_MATERIA)
        else:
            labels = slot_labels_for(m)
        for key in SLOT_KEYS:
            lab = self._slot_labels.get(key)
            if lab is not None:
                lab.setText(labels.get(key, key))

    def _on_postura_changed(self, text: str = ""):
        t = text or self._postura_combo.currentText()
        self._postura_otros_edit.setVisible(t == "Otros")

    def _on_modo_changed(self, index: int = -1):
        # «Elegir borrador…» permanece activo: al pulsarlo se fuerza el modo «Continuar borrador».
        self._borrador_lbl.setEnabled(True)
        self._btn_borrador_pick.setEnabled(True)
        # Al volver a «Generar desde cero», no dejar colgada la ruta del borrador (evita confusión en la UI).
        cur = self._modo_combo.currentIndex() if index < 0 else index
        if cur == 0:
            self._borrador_continuar = None
            self._borrador_lbl.setText("(ninguno)")

    def _pick_borrador_continuar(self):
        if self._modo_combo.currentIndex() != 1:
            self._modo_combo.setCurrentIndex(1)
        m = self._current_materia()
        if m is None:
            start = str(DIRS["resoluciones"])
        else:
            start = str(dir_resoluciones_materia(m))
        path, _ = _pick_open_file_name(
            self, "Borrador a continuar", start,
            BORRADOR_CONTINUAR_QFILE_FILTER,
        )
        if not path:
            return
        self._borrador_continuar = Path(path)
        if not is_valid_borrador_continuar_path(self._borrador_continuar):
            QMessageBox.warning(
                self,
                "Formato no admitido",
                "Formatos admitidos: Markdown (.md), Word (.doc, .docx), PDF (.pdf) y Pages (.pages).",
            )
            self._borrador_continuar = None
            self._borrador_lbl.setText("(ninguno)")
            return
        try:
            rel = self._borrador_continuar.relative_to(BASE_DIR.resolve())
            self._borrador_lbl.setText(str(rel))
        except ValueError:
            self._borrador_lbl.setText(str(self._borrador_continuar))

    def _sync_corpus_pick_widgets_enabled(self, *_):
        m = self._current_materia()
        if hasattr(self, "_corpus_pick_btn"):
            self._corpus_pick_btn.setEnabled(
                bool(self._corpus_style_cb.isChecked() and m is not None)
            )

    def _refresh_corpus_pick_label(self):
        if not hasattr(self, "_corpus_pick_lbl"):
            return
        picks = self._corpus_manual_pick or []
        if picks:
            names = ", ".join(p.name for p in picks)
            self._corpus_pick_lbl.setText(
                f"Corpus para estilo: seleccionadas ({len(picks)}): {names}"
            )
        else:
            self._corpus_pick_lbl.setText(
                "Corpus para estilo: modo automático (3 primeras por nombre de archivo) "
                "— o pulsa «Elegir…» con la casilla de corpus marcada."
            )

    def _revalidate_corpus_manual_pick(self):
        """Quita rutas inválidas o fuera de 02_wiki/casos_previos/<materia>/."""
        m = self._current_materia()
        picks = getattr(self, "_corpus_manual_pick", None) or []
        if not picks:
            self._refresh_corpus_pick_label()
            return
        if m is None:
            self._corpus_manual_pick.clear()
            self._refresh_corpus_pick_label()
            return
        base = dir_casos_previos_wiki(m).resolve()
        keep: list[Path] = []
        for p in picks:
            try:
                rp = p.expanduser().resolve()
            except OSError:
                continue
            if not rp.is_file() or rp.suffix.lower() != ".md":
                continue
            try:
                rp.relative_to(base)
            except ValueError:
                continue
            keep.append(rp)
        self._corpus_manual_pick[:] = keep
        self._refresh_corpus_pick_label()

    def _pick_corpus_fichas_manual(self):
        m = self._current_materia()
        if m is None:
            QMessageBox.information(
                self,
                "Materia",
                "Elige primero una materia en la barra lateral.",
            )
            return
        fichas = list_corpus_wiki_fichas(m)
        if not fichas:
            QMessageBox.information(
                self,
                "Sin fichas corpus",
                f"No hay notas .md en `02_wiki/casos_previos/{m}/`.\n\n"
                "Desde la pantalla inicial agrega PDFs al corpus magistrado y pulsa «Procesar pendiente», "
                "o coloca fichas .md válidas en esa carpeta.",
            )
            return

        dlg = QDialog(self)
        dlg.setWindowTitle(f"Corpus por estilo ({m}) — hasta 3 fichas")
        dlg.resize(580, 420)
        dlg.setStyleSheet(f"background-color: {BG}; color: {TEXT};")
        dv = QVBoxLayout(dlg)
        dv.setContentsMargins(16, 16, 16, 16)
        dv.setSpacing(10)
        hint = QLabel(
            "Selecciona hasta 3 filas usando Ctrl+Clic en Windows/Linux o Cmd+Clic en macOS sobre cada nota.\n\n"
            "Si aceptas sin ninguna selección, se vuelve al modo automático (3 primeras por nombre)."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {MUTED}; font-size: 12px;")
        dv.addWidget(hint)
        lst = QListWidget()
        lst.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        lst.setStyleSheet(f"""
            QListWidget {{
                background-color: {BG_INPUT}; color: {TEXT};
                border: 1px solid {BORDER}; border-radius: 6px; padding: 4px;
            }}
            QListWidget::item {{ padding: 8px 10px; border-radius: 4px; }}
            QListWidget::item:selected {{ background-color: {GOLD}; color: {BG}; font-weight: 600; }}
        """)

        picked_resolved: set[Path] = set()
        for p in self._corpus_manual_pick:
            try:
                picked_resolved.add(p.expanduser().resolve())
            except OSError:
                continue

        for fp in fichas:
            item = QListWidgetItem(fp.name)
            item.setData(Qt.ItemDataRole.UserRole, fp)
            try:
                if fp.expanduser().resolve() in picked_resolved:
                    item.setSelected(True)
            except OSError:
                pass
            lst.addItem(item)

        dv.addWidget(lst, 1)

        bb = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        bb.button(QDialogButtonBox.StandardButton.Ok).setText("Guardar selección")
        bb.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")

        selection_out: list[Path] = []

        def attempt_ok():
            sel: list[Path] = []
            for i in range(lst.count()):
                it = lst.item(i)
                if it.isSelected():
                    raw = it.data(Qt.ItemDataRole.UserRole)
                    if raw is not None:
                        sel.append(Path(raw))
            if len(sel) > 3:
                QMessageBox.warning(
                    dlg,
                    "Demasiadas fichas",
                    "Seleccioná como máximo 3 fichas. Usá Ctrl/Cmd+Clic para desmarcar filas.",
                )
                return
            selection_out[:] = sel
            dlg.accept()

        bb.accepted.connect(attempt_ok)
        bb.rejected.connect(dlg.reject)
        dv.addWidget(bb)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        if not selection_out:
            self._corpus_manual_pick.clear()
        else:
            resolved: list[Path] = []
            for fp in selection_out:
                try:
                    resolved.append(fp.expanduser().resolve())
                except OSError:
                    continue
            self._corpus_manual_pick[:] = resolved[:3]
        self._refresh_corpus_pick_label()

    def eventFilter(self, obj, event):
        slot_key = obj.property("slot_key") if isinstance(obj, QLabel) else None
        if slot_key and (
            event.type() == QEvent.Type.MouseButtonDblClick
            and event.button() == Qt.MouseButton.LeftButton
        ):
            files = self._slot_files.get(str(slot_key)) or []
            if files:
                self._slot_open_path(files[0])
            return True
        return super().eventFilter(obj, event)

    def _rebuild_slot_display(
        self,
        slot_key: str,
        *,
        muted: bool = False,
        case_folder: Path | None = None,
    ) -> None:
        lines: list[str] = []
        for fpath in self._slot_files[slot_key]:
            if case_folder is not None:
                try:
                    lines.append(f"✅  {fpath.relative_to(case_folder)}")
                except ValueError:
                    lines.append(f"✅  {fpath.name}")
            else:
                lines.append(f"📄  {fpath.name}")
        lbl = self._slot_display_lbl[slot_key]
        rm = self._slot_rm_btns[slot_key]
        if lines:
            color = MUTED if (muted or case_folder is not None) else TEXT
            lbl.setText("\n".join(lines))
            lbl.setStyleSheet(
                f"color: {color}; font-size: 11px; padding: 3px 6px; border-radius: 4px;"
            )
            rm.setEnabled(True)
            rm.setStyleSheet(f"""
                QLabel {{
                    background-color: {BG_INPUT}; color: {ERROR};
                    border: 2px solid {ERROR}; border-radius: 8px; padding: 2px 6px;
                }}
            """)
        else:
            lbl.setText("(ningún archivo)")
            lbl.setStyleSheet(
                f"color: {MUTED}; font-size: 11px; padding: 3px 6px; border-radius: 4px;"
            )
            rm.setEnabled(False)
            rm.setStyleSheet(f"""
                QLabel {{
                    background-color: {BG_CARD}; color: {MUTED};
                    border: 2px solid {BORDER}; border-radius: 8px; padding: 2px 6px;
                }}
            """)

    def _slot_open_path(self, path: Path) -> None:
        _dismiss_floating_artifacts(self)
        path = path.expanduser()
        if not path.is_file():
            QMessageBox.warning(
                self,
                "Archivo no disponible",
                f"No se encontró el archivo (pudo moverse o borrarse):\n\n{path}",
            )
            return
        url = QUrl.fromLocalFile(str(path.resolve()))
        if not QDesktopServices.openUrl(url):
            QMessageBox.warning(
                self,
                "No se pudo abrir",
                f"El sistema no pudo abrir:\n\n{path.resolve()}",
            )

    def _slot_add(self, slot_key: str):
        paths, _ = _pick_open_file_names(
            self, f"Archivos — {slot_key}",
            str(BASE_DIR / "01_raw"),
            "Todos los archivos (*)",
        )
        if not paths:
            _dismiss_floating_artifacts(self)
            return
        for p in paths:
            self._slot_files[slot_key].append(Path(p))
        self._rebuild_slot_display(slot_key)
        _dismiss_floating_artifacts(self)

    def _slot_remove(self, slot_key: str):
        _dismiss_floating_artifacts(self)
        if not self._slot_files[slot_key]:
            return
        self._slot_files[slot_key].pop()
        self._rebuild_slot_display(slot_key)

    def _slot_transcribe_audio(self, slot_key: str):
        QToolTip.hideText()
        if slot_key != "audio":
            return
        path, _ = _pick_open_file_name(
            self, "Audio para transcribir",
            str(BASE_DIR / "01_raw"),
            "Audio (*.mp3 *.wav *.m4a *.ogg);;Todos (*)",
        )
        if not path:
            return
        ok, msg = transcribe_audio_to_txt(Path(path))
        if ok:
            txt_path = Path(msg)
            self._slot_files[slot_key].append(txt_path)
            self._rebuild_slot_display(slot_key)
            QMessageBox.information(
                self, "Transcripción",
                f"Listo:\n{msg}",
            )
        else:
            tip = ""
            if not whisper_cli_available():
                tip = "\n\nInstala: pip install openai-whisper"
            QMessageBox.warning(self, "Whisper", msg + tip)

    def _edit_current(self):
        self._prompt_frame.setVisible(False)
        self._prep_btn.setText("↺  REGENERAR PROMPT")

    def _clear_slot_ui(self):
        for key in SLOT_KEYS:
            self._slot_files[key].clear()
            self._rebuild_slot_display(key)

    def _clear_generation_output_ui(self):
        """Oculta y vacía el bloque de resolución generada (Claude / guardado)."""
        self._gen_output_area.clear()
        self._word_canvas.setVisible(False)
        self._gen_output_label.setVisible(False)
        self._gen_copy_btn.setVisible(False)
        self._gen_save_btn.setVisible(False)
        self._gen_expand_btn.setVisible(False)
        self._gen_export_docx_btn.setVisible(False)
        self._gen_import_corrected_btn.setVisible(False)
        self._gen_export_pdf_btn.setVisible(False)
        self._gen_continue_btn.setVisible(False)
        self._gen_status_lbl.setVisible(False)
        self._apply_iter_btn.setVisible(False)
        self._consolid_iter_btn.setVisible(False)

    def _clear_case_draft_shared(self):
        """Estado del expediente en curso: ranuras, metadatos, prompt preparado y salida generada."""
        self._existing_folder = None
        self._clear_slot_ui()
        self._name_edit.clear()
        self._name_edit.setReadOnly(False)
        self._name_edit.setStyleSheet("")
        self._tipo_combo.setCurrentIndex(0)
        self._postura_combo.setCurrentIndex(0)
        self._postura_otros_edit.clear()
        self._agravios_edit.clear()
        self._modo_combo.setCurrentIndex(0)
        self._borrador_continuar = None
        self._borrador_lbl.setText("(ninguno)")
        self._corpus_style_cb.setChecked(False)
        self._corpus_manual_pick.clear()
        self._refresh_corpus_pick_label()
        self._sync_corpus_pick_widgets_enabled()
        self._on_modo_changed()
        self._instruccion_edit.clear()
        self._bib_list.clear()
        self._bib_count.setText("")
        self._exp_edit.clear()
        self._imp_edit.clear()
        self._del_edit.clear()
        self._agr_edit.clear()
        self._juz_edit.clear()
        self._meta_widget.setVisible(False)
        self._clear_plantilla_selection()
        self._prep_btn.setText("PREPARAR CASO")
        self._prompt_frame.setVisible(False)
        self._prompt_saved_lbl.setText("")
        self._prompt_saved_lbl.setStyleSheet(f"color: {SUCCESS}; font-size: 11px;")
        self._resolution_incomplete_seq = 0
        self._last_prompt_for_continue = ""
        self._last_user_content_for_continue = ""
        self._last_output_validation = None
        self._cursor_respuesta_edit.clear()
        self._last_folder_rel = None
        self._last_materia_prompt = None
        self._generate_kwargs = None
        self._gen_claude_btn.setEnabled(False)
        self._clear_generation_output_ui()
        self._sync_form_materia_combo()

    def reset_draft_for_materia_change(self):
        """Al cambiar de materia en la barra lateral, el borrador del caso anterior no aplica."""
        self._clear_case_draft_shared()

    def _prepare(self):
        mat0 = self._current_materia()
        modo = "continuar" if self._modo_combo.currentIndex() == 1 else "generar"
        if mat0 is None and modo == "continuar" and self._borrador_continuar is not None:
            if is_valid_borrador_continuar_path(self._borrador_continuar):
                mat0 = infer_materia_from_resoluciones_md(self._borrador_continuar)
        if mat0 is None:
            QMessageBox.warning(
                self, "Materia",
                "Elige primero una materia en el formulario de este expediente, "
                "o bien en modo «Continuar borrador» elige un archivo dentro de "
                "`03_outputs/resoluciones/<materia>/` para deducir la materia desde la ruta.",
            )
            return
        borrador_rel = ""
        if modo == "continuar":
            if not is_valid_borrador_continuar_path(self._borrador_continuar):
                QMessageBox.warning(
                    self,
                    "Borrador",
                    "Elige un borrador existente en «Elegir borrador…» (.md, .doc, .docx, .pdf o .pages).",
                )
                return
            try:
                borrador_rel = str(
                    self._borrador_continuar.resolve().relative_to(BASE_DIR.resolve())
                ).replace("\\", "/")
            except ValueError:
                borrador_rel = str(self._borrador_continuar)

        plantilla_name = self._selected_plantilla.name if self._selected_plantilla else "sin_plantilla"
        tipo = self._tipo_combo.currentText()
        postura = self._postura_combo.currentText()
        postura_personalizada = (
            self._postura_otros_edit.toPlainText().strip() if postura == "Otros" else ""
        )
        agravios = self._agravios_edit.toPlainText().strip()
        instruccion = self._instruccion_edit.toPlainText().strip()
        instruccion_general = self._instruccion_general_edit.toPlainText().strip()

        raw = BASE_DIR / "01_raw"
        base_res = BASE_DIR.resolve()

        def copy_slots_into(folder: Path) -> dict[str, list[str]]:
            slots_prompt: dict[str, list[str]] = {k: [] for k in SLOT_KEYS}
            manifest: dict[str, list[str]] = {}
            for key in SLOT_KEYS:
                rels: list[str] = []
                for src in self._slot_files[key]:
                    dest_dir = folder / "fuentes" / key
                    dest_dir.mkdir(parents=True, exist_ok=True)
                    dest = dest_dir / src.name
                    if not src.is_file():
                        continue
                    if src.resolve() != dest.resolve():
                        copy_to(src, dest)
                    rp = dest.resolve().relative_to(base_res)
                    slots_prompt[key].append(str(rp).replace("\\", "/"))
                    rels.append(f"{key}/{dest.name}")
                if rels:
                    manifest[key] = rels
            write_fuentes_slots_manifest(folder, manifest)
            return slots_prompt

        if self._existing_folder:
            try:
                slots_prompt = copy_slots_into(self._existing_folder)
            except Exception as e:
                QMessageBox.critical(self, "Error", f"No se pudieron copiar los archivos:\n{e}")
                return
            folder_rel = str(self._existing_folder.relative_to(raw)).replace("\\", "/")
            case_folder = self._existing_folder
        else:
            nombre = self._name_edit.text().strip()
            if not nombre:
                QMessageBox.warning(self, "Falta el nombre", "Ingresa el nombre del caso.")
                return
            self._refresh_num()
            try:
                folder = create_case_folder(self._next_num, nombre, materia=mat0)
                slots_prompt = copy_slots_into(folder)
            except Exception as e:
                QMessageBox.critical(self, "Error", f"No se pudieron copiar los archivos:\n{e}")
                return
            folder_rel = str(folder.relative_to(raw)).replace("\\", "/")
            case_folder = folder

        # Rutas reales bajo 01_raw/.../fuentes/ (los archivos pegados al expediente). Si se usan rutas del
        # diálogo anterior, un PDF movido o sólo en la copia del caso no llega a Claude.
        slots_paths_for_claude = read_fuentes_slots(case_folder)

        bib_paths = [
            str(p.relative_to(BASE_DIR)).replace("\\", "/")
            for p in list_bibliografia(mat0)
        ]
        corpus_sample = None
        if self._corpus_style_cb.isChecked():
            todas = list_corpus_wiki_fichas(mat0)
            usar: list[Path] = []
            base_prev = dir_casos_previos_wiki(mat0).resolve()
            for pth in getattr(self, "_corpus_manual_pick", [])[:3]:
                try:
                    rr = Path(pth).expanduser().resolve()
                except OSError:
                    continue
                if not rr.is_file() or rr.suffix.lower() != ".md":
                    continue
                try:
                    rr.relative_to(base_prev)
                except ValueError:
                    continue
                usar.append(rr)
            if usar:
                src = usar
            else:
                src = todas[:3]
            if src:
                corpus_sample = [
                    str(f.relative_to(BASE_DIR)).replace("\\", "/") for f in src
                ]

        prompt = build_cursor_prompt(
            folder_rel,
            plantilla_name,
            tipo,
            postura,
            instruccion,
            instruccion_general=instruccion_general,
            expediente=self._exp_edit.text().strip(),
            imputados=self._imp_edit.text().strip(),
            delito=self._del_edit.text().strip(),
            agraviado=self._agr_edit.text().strip(),
            juzgado=self._juz_edit.text().strip(),
            materia=mat0,
            postura_personalizada=postura_personalizada,
            agravios=agravios,
            modo=modo,
            borrador_path=borrador_rel,
            slots=slots_prompt,
            bibliografia_activa=bib_paths if bib_paths else None,
            corpus_sample=corpus_sample,
        )
        self._prompt_area.setPlainText(prompt)
        self._folder_lbl.setText(f"📁  01_raw/{folder_rel}/")
        self._last_folder_rel = folder_rel
        self._last_materia_prompt = mat0
        self._prompt_saved_lbl.setStyleSheet(f"color: {SUCCESS}; font-size: 11px;")
        self._prompt_saved_lbl.setText("")
        try:
            p = save_prompt_to_resoluciones_folder(mat0, folder_rel, prompt)
            rel = p.relative_to(BASE_DIR)
            bib_note = ""
            if not bib_paths:
                bib_note = (
                    "\n\n⚠ **Bibliografía de esta matería vacía** (`01_raw/bibliografia/"
                    f"{mat0}/`). El prompt ya incluye instrucciones para no mostrar avisos tipo "
                    "«no se encontró jurisprudencia». Añada .md/.pdf aquí o en global si necesita precedentes embebidos."
                )
            self._prompt_saved_lbl.setText(
                f"✓ Prompt guardado automáticamente: `{rel}`" + bib_note
            )
        except OSError as e:
            self._prompt_saved_lbl.setText(
                f"No se pudo guardar el prompt en disco: {e}"
            )
            self._prompt_saved_lbl.setStyleSheet(f"color: {ERROR}; font-size: 11px;")
        self._prompt_frame.setVisible(True)
        self._prep_btn.setText("↺  ACTUALIZAR PROMPT")

        # Guardar kwargs para ClaudeWorker (generación directa)
        bib_paths_obj = list_bibliografia(mat0)
        self._generate_kwargs = {
            "prompt_kwargs": {
                "plantilla_path": self._selected_plantilla,
                "slots": slots_paths_for_claude,
                "slot_labels": slot_labels_for(mat0),
                "bibliografia": bib_paths_obj,
                "instruccion_general": instruccion_general,
                "instruccion_particular": instruccion,
                "postura": postura,
                "postura_personalizada": postura_personalizada,
                "agravios": agravios,
                "expediente": self._exp_edit.text().strip(),
                "imputados": self._imp_edit.text().strip(),
                "delito": self._del_edit.text().strip(),
                "agraviado": self._agr_edit.text().strip(),
                "juzgado": self._juz_edit.text().strip(),
                "materia_label": materia_label(mat0),
                "modo": modo,
                "borrador_path": borrador_rel,
                "folder_name": folder_rel,
                "caso_num": folder_rel.split("/")[-1].split("_")[1] if "_" in folder_rel else "000",
                "tipo": tipo,
            }
        }
        self._gen_claude_btn.setEnabled(True)
        # Limpiar output anterior si hubo
        self._clear_generation_output_ui()

    # ── Generación directa con Claude API ────────────────────────────────

    def _prompt_corpus_for_validation(self) -> str:
        w = self._worker
        prompt = ""
        if w is not None:
            prompt = (
                getattr(w, "last_built_prompt", None)
                or getattr(w, "built_prompt", "")
                or ""
            )
        if not prompt:
            prompt = self._last_prompt_for_continue or ""
        if isinstance(prompt, list):
            parts: list[str] = []
            for block in prompt:
                if isinstance(block, dict):
                    t = block.get("text")
                    if t:
                        parts.append(str(t))
                elif isinstance(block, str):
                    parts.append(block)
            prompt = "\n".join(parts)
        return str(prompt)

    def _validate_gen_output(
        self,
        texto: str,
        *,
        expect_full_act: bool = True,
        iteration_mode: str | None = None,
    ) -> ValidationReport:
        pk = (self._generate_kwargs or {}).get("prompt_kwargs") or {}
        folder = str(pk.get("folder_name", "") or "")
        materia = folder.split("/")[0] if "/" in folder else ""
        return validate_resolution_output(
            texto,
            postura=pk.get("postura", "") or self._postura_combo.currentText(),
            tipo=pk.get("tipo", "") or self._tipo_combo.currentText(),
            source_corpus=self._prompt_corpus_for_validation(),
            expect_full_act=expect_full_act,
            iteration_mode=iteration_mode,
            materia=materia,
            delito=pk.get("delito", "") or self._del_edit.text().strip(),
        )

    def _apply_output_validation_ui(self, report: ValidationReport) -> None:
        self._last_output_validation = report
        if report.ok:
            return
        color = ERROR if report.has_errors else GOLD
        self._gen_status_lbl.setStyleSheet(
            f"color: {color}; font-size: 11px; font-weight: 600;"
        )
        prefix = "Revisión de salida — errores detectados" if report.has_errors else "Revisión de salida — avisos"
        self._gen_status_lbl.setText(f"{prefix} (ver diálogo).")
        box_fn = QMessageBox.critical if report.has_errors else QMessageBox.warning
        title = "Revisión de salida — corrija antes de exportar" if report.has_errors else "Revisión de salida"
        extra = (
            "\n\nLa exportación a Word/PDF quedará bloqueada hasta corregir o exportar bajo su responsabilidad."
            if report.has_errors
            else "\n\nPuede editar el acto antes de firmar o exportar."
        )
        box_fn(
            self,
            title,
            "\n".join(report.summary_lines()) + extra,
        )

    def _export_allowed_after_validation(self) -> bool:
        texto = self._gen_output_area.toPlainText().strip()
        if texto:
            self._last_output_validation = self._validate_gen_output(
                texto,
                expect_full_act=True,
            )
        vr = self._last_output_validation
        if vr is None or not vr.blocks_export:
            return True
        ans = QMessageBox.warning(
            self,
            "Exportación bloqueada",
            "\n".join(vr.summary_lines())
            + "\n\nLa validación automática detectó problemas graves.\n"
            "¿Exportar de todos modos bajo su responsabilidad?",
            QMessageBox.StandardButton.No | QMessageBox.StandardButton.Yes,
            QMessageBox.StandardButton.No,
        )
        return ans == QMessageBox.StandardButton.Yes

    def _generate_with_claude(self):
        if not self._generate_kwargs:
            QMessageBox.warning(self, "Sin caso", "Prepara el caso primero con «PREPARAR CASO».")
            return
        if self._continuation_worker and self._continuation_worker.isRunning():
            QMessageBox.information(
                self,
                "En curso",
                "Espere a que termine «Continuar acto» antes de lanzar una generación nueva.",
            )
            return
        import os
        if not os.environ.get("ANTHROPIC_API_KEY", "").strip():
            QMessageBox.warning(
                self, "API Key no configurada",
                "Configura ANTHROPIC_API_KEY de una de estas formas:\n\n"
                "1) Archivo `.env` en la raíz del repo (copia de `.env.example`):\n"
                "   ANTHROPIC_API_KEY=sk-ant-…\n\n"
                "2) En la terminal, antes de lanzar la app:\n"
                "   export ANTHROPIC_API_KEY=sk-ant-…\n\n"
                "Reiniciá la app tras guardar `.env`.",
            )
            return

        self._gen_claude_btn.setEnabled(False)
        self._cancel_gen_btn.setVisible(True)
        self._resolution_incomplete_seq = 0
        self._last_prompt_for_continue = ""
        self._last_user_content_for_continue = ""
        self._gen_continue_btn.setVisible(False)
        self._gen_status_lbl.setStyleSheet(f"color: {MUTED}; font-size: 11px;")
        self._gen_status_lbl.setText("Leyendo documentos…")
        self._gen_status_lbl.setVisible(True)
        self._gen_output_area.clear()
        self._word_canvas.setVisible(True)
        self._gen_output_label.setVisible(True)
        self._gen_copy_btn.setVisible(False)
        self._gen_save_btn.setVisible(False)
        self._gen_expand_btn.setVisible(False)
        self._gen_export_docx_btn.setVisible(False)
        self._gen_import_corrected_btn.setVisible(False)
        self._gen_export_pdf_btn.setVisible(False)

        self._worker = ClaudeWorker(self._generate_kwargs)
        self._worker.chunk_ready.connect(self._on_gen_chunk)
        self._worker.status.connect(self._gen_status_lbl.setText)
        self._worker.finished.connect(self._on_gen_finished)
        self._worker.error_occurred.connect(self._on_gen_error)
        self._worker.start()

    def _cancel_generation(self):
        if self._continuation_worker and self._continuation_worker.isRunning():
            self._continuation_worker.cancel()
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
        self._cancel_gen_btn.setVisible(False)
        self._gen_claude_btn.setEnabled(True)
        self._gen_continue_btn.setEnabled(True)
        self._gen_status_lbl.setText("Cancelado.")

    def _on_gen_chunk(self, text: str):
        cursor = self._gen_output_area.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText(text)
        self._gen_output_area.setTextCursor(cursor)
        self._gen_output_area.ensureCursorVisible()

    def _on_gen_finished(self):
        self._cancel_gen_btn.setVisible(False)
        self._gen_claude_btn.setEnabled(True)
        texto = self._gen_output_area.toPlainText().strip()
        outcome = getattr(self._worker, "last_generation_outcome", None)
        self._last_prompt_for_continue = (
            getattr(self._worker, "last_built_prompt", None)
            or getattr(self._worker, "built_prompt", "")
            or ""
        ).strip()
        uc = getattr(self._worker, "last_initial_user_content", None)
        if uc is None or uc == "" or (isinstance(uc, list) and not uc):
            self._last_user_content_for_continue = self._last_prompt_for_continue
        else:
            self._last_user_content_for_continue = uc

        incomplete = bool(outcome and outcome.likely_incomplete())
        backup_rel = ""

        if texto:
            self._gen_copy_btn.setVisible(True)
            self._gen_save_btn.setVisible(True)
            self._gen_expand_btn.setVisible(True)
            self._gen_export_docx_btn.setVisible(True)
            self._gen_import_corrected_btn.setVisible(True)
            self._gen_export_pdf_btn.setVisible(True)
            self._apply_iter_btn.setVisible(True)
            self._consolid_iter_btn.setVisible(True)

        if incomplete and texto:
            if self._last_folder_rel and self._last_materia_prompt:
                self._resolution_incomplete_seq += 1
                slug_tag = (
                    "maxtokens"
                    if outcome
                    and (outcome.max_tokens_truncation or outcome.stop_reason == "max_tokens")
                    else "revision"
                )
                slug = f"incompleta_{self._resolution_incomplete_seq:02d}_{slug_tag}"
                try:
                    bp = save_resolucion_generada_backup(
                        self._last_materia_prompt,
                        self._last_folder_rel,
                        texto,
                        sufijo_slug=slug,
                    )
                    backup_rel = bp.relative_to(BASE_DIR).as_posix()
                except OSError as e:
                    backup_rel = f"(no se pudo guardar backup: {e})"

            lines = []
            if outcome:
                lines.extend(outcome.reasons_spanish())
            if backup_rel.startswith("("):
                lines.append(backup_rel)
            elif backup_rel:
                lines.append(f"Copia de respaldo en:\n{backup_rel}")
            elif not self._last_folder_rel:
                lines.append("(No hay expediente asociado: no se creó copia automática en disco.)")
            self._gen_status_lbl.setStyleSheet(
                f"color: {GOLD}; font-size: 11px; font-weight: 600;"
            )
            self._gen_status_lbl.setText(
                "Resolución posiblemente incompleta — revise el final del acto y use «Continuar acto» "
                "o edite antes de cerrar."
            )
            QMessageBox.warning(
                self,
                "Resolución posiblemente incompleta",
                "\n\n".join(lines)
                + "\n\n"
                + "Opciones recomendadas:\n"
                "• Pulse «⚿ Continuar acto (Claude)» para que el modelo añada solo lo pendiente;\n"
                "• Edite aquí mismo y luego «Guardar» cuando el texto esté cerrado.",
            )
            self._gen_continue_btn.setVisible(self._continuation_context_available())

            return

        if incomplete and not texto:
            self._gen_status_lbl.setStyleSheet(f"color: {ERROR}; font-size: 11px;")
            self._gen_status_lbl.setText(
                outcome.reasons_spanish()[0]
                if outcome and outcome.reasons_spanish()
                else "Sin texto generado (posible cancelación o vacío)."
            )
            QMessageBox.warning(
                self,
                "Generación incompleta",
                "\n".join(outcome.reasons_spanish())
                if outcome
                else "No se obtuvo contenido.",
            )
            self._gen_continue_btn.setVisible(False)
            return

        self._gen_status_lbl.setStyleSheet(f"color: {MUTED}; font-size: 11px;")
        self._gen_status_lbl.setText("✓ Resolución generada.")
        self._gen_continue_btn.setVisible(False)
        vr = self._validate_gen_output(texto, expect_full_act=True)
        self._apply_output_validation_ui(vr)
        if vr.ok:
            self._gen_status_lbl.setStyleSheet(f"color: {MUTED}; font-size: 11px;")
            self._gen_status_lbl.setText("✓ Resolución generada.")
        self._save_gen_output(silent=True)
        self._run_resolution_ficha()

    def _continuation_context_available(self) -> bool:
        """Hay primer turno user guardado (texto o multimodal con PDF) para «Continuar acto»."""
        c = getattr(self, "_last_user_content_for_continue", None)
        if c is None:
            return bool(self._last_prompt_for_continue.strip())
        if isinstance(c, str):
            return bool(c.strip())
        return len(c) > 0

    def _continue_resolution_generation(self):
        """Segunda llamada multiturn tras salida incompleta (max_tokens / cierre sospechoso)."""
        content0 = self._last_user_content_for_continue
        if content0 is None or (
            isinstance(content0, str) and not content0.strip()
        ) or (isinstance(content0, list) and not content0):
            QMessageBox.warning(
                self, "Sin contexto",
                "No hay prompt original en memoria. Use «GENERAR CON CLAUDE» de nuevo "
                "(o prepare el caso otra vez) para reconstruir el contexto completo.",
            )
            return
        parcial = self._gen_output_area.toPlainText()
        if not parcial.strip():
            QMessageBox.warning(self, "Sin texto", "No hay acto parcial para continuar.")
            return
        import os as _os
        if not _os.environ.get("ANTHROPIC_API_KEY", "").strip():
            QMessageBox.warning(self, "API Key", "Configura ANTHROPIC_API_KEY primero.")
            return

        self._continuation_worker = ResolutionContinuationWorker(
            initial_user_content=content0,
            assistant_partial=parcial.strip(),
            parent=self,
        )
        self._gen_claude_btn.setEnabled(False)
        self._gen_continue_btn.setEnabled(False)
        self._cancel_gen_btn.setVisible(True)
        self._continuation_worker.chunk_ready.connect(self._on_gen_chunk)
        self._continuation_worker.status.connect(self._gen_status_lbl.setText)
        self._continuation_worker.finished.connect(self._on_continue_finished)
        self._continuation_worker.error_occurred.connect(self._on_continue_error)
        self._continuation_worker.start()

    def _on_continue_finished(self):
        self._cancel_gen_btn.setVisible(False)
        self._gen_claude_btn.setEnabled(True)
        self._gen_continue_btn.setEnabled(True)
        w = self._continuation_worker
        texto_completo = self._gen_output_area.toPlainText().strip()
        outcome = getattr(w, "last_generation_outcome", None) if w else None

        incomplete = bool(outcome and outcome.likely_incomplete())

        backup_rel = ""
        if incomplete and texto_completo:
            if self._last_folder_rel and self._last_materia_prompt:
                self._resolution_incomplete_seq += 1
                slug_tag = (
                    "maxtokens"
                    if outcome
                    and (outcome.max_tokens_truncation or outcome.stop_reason == "max_tokens")
                    else "revision"
                )
                slug = f"tras_continuar_{self._resolution_incomplete_seq:02d}_{slug_tag}"
                try:
                    bp = save_resolucion_generada_backup(
                        self._last_materia_prompt,
                        self._last_folder_rel,
                        texto_completo,
                        sufijo_slug=slug,
                    )
                    backup_rel = bp.relative_to(BASE_DIR).as_posix()
                except OSError as e:
                    backup_rel = f"(no se pudo guardar backup: {e})"
            else:
                backup_rel = "(Sin expediente asociado: no hay copia en 03_outputs/.)"

        if incomplete:
            lines = []
            if outcome:
                lines.extend(outcome.reasons_spanish())
            if backup_rel:
                if backup_rel.startswith("("):
                    lines.append(backup_rel)
                else:
                    lines.append(f"Nueva copia de respaldo:\n{backup_rel}")
            self._gen_status_lbl.setStyleSheet(
                f"color: {GOLD}; font-size: 11px; font-weight: 600;"
            )
            self._gen_status_lbl.setText(
                "Aún puede faltar texto — revise o pulse «Continuar acto» otra vez."
            )
            QMessageBox.warning(
                self,
                "Continuación: posible salida incompleta",
                "\n\n".join(lines),
            )
            self._gen_continue_btn.setVisible(True)
            return

        self._gen_status_lbl.setStyleSheet(f"color: {MUTED}; font-size: 11px;")
        self._gen_status_lbl.setText("✓ Acto cerrado después de continuación.")
        self._gen_continue_btn.setVisible(False)
        vr = self._validate_gen_output(texto_completo, expect_full_act=True)
        self._apply_output_validation_ui(vr)
        if vr.ok:
            self._gen_status_lbl.setStyleSheet(f"color: {MUTED}; font-size: 11px;")
            self._gen_status_lbl.setText("✓ Acto cerrado después de continuación.")
        self._save_gen_output(silent=True)
        self._run_resolution_ficha()

    def _on_continue_error(self, msg: str):
        self._cancel_gen_btn.setVisible(False)
        self._gen_claude_btn.setEnabled(True)
        self._gen_continue_btn.setEnabled(True)
        self._gen_continue_btn.setVisible(True)
        self._gen_status_lbl.setStyleSheet(f"color: {ERROR}; font-size: 11px;")
        self._gen_status_lbl.setText(f"Error continuación: {msg[:140]}")
        QMessageBox.critical(self, "Error al continuar el acto", msg)

    def _on_gen_error(self, msg: str):
        self._cancel_gen_btn.setVisible(False)
        self._gen_claude_btn.setEnabled(True)
        self._gen_status_lbl.setStyleSheet(f"color: {ERROR}; font-size: 11px;")
        self._gen_status_lbl.setText(f"Error: {msg[:120]}")
        QMessageBox.critical(self, "Error al generar", msg)

    def _copy_gen_output(self):
        t = self._gen_output_area.toPlainText()
        if t:
            QApplication.clipboard().setText(t)
            orig = self._gen_copy_btn.text()
            self._gen_copy_btn.setText("✓ Copiado")
            QTimer.singleShot(2000, lambda: self._gen_copy_btn.setText(orig))

    def _save_gen_output(self, silent: bool = False):
        if not self._last_folder_rel or not self._last_materia_prompt:
            if not silent:
                QMessageBox.warning(self, "Sin caso", "Prepara el caso primero.")
            return
        texto = self._gen_output_area.toPlainText().strip()
        if not texto:
            return
        try:
            p = save_resolucion_cursor_text(
                self._last_materia_prompt,
                self._last_folder_rel,
                texto,
            )
            rel = p.relative_to(BASE_DIR)
            if not silent:
                QMessageBox.information(
                    self, "Guardado",
                    f"Resolución guardada:\n\n`{rel}`",
                )
            else:
                self._gen_status_lbl.setText(f"✓ Guardada: {rel}")
        except OSError as e:
            if not silent:
                QMessageBox.critical(self, "Error", str(e))
            return

        # — Guardado automático en Word (silencioso, siempre) —
        try:
            from app.core.file_manager import export_to_docx
            meta = {
                "expediente": getattr(self, "_exp_edit", None) and self._exp_edit.text().strip() or "",
                "imputado":   getattr(self, "_imp_edit", None) and self._imp_edit.text().strip() or "",
                "delito":     getattr(self, "_del_edit", None) and self._del_edit.text().strip() or "",
                "agraviado":  getattr(self, "_agr_edit", None) and self._agr_edit.text().strip() or "",
            }
            export_to_docx(p, metadata=meta)
        except Exception:
            pass  # El Word es secundario; el .md ya se guardó

    def _apply_modifications(self, full_document: bool):
        """Itera sobre la resolución.

        ``full_document`` False → solo correcciones puntuales (predeterminado).
        ``full_document`` True → acto íntegro consolidado desde el botón dedicado.
        """
        if not self._last_materia_prompt:
            QMessageBox.warning(
                self, "Sin caso",
                "Abre o prepara el expediente de nuevo para asociar materia e instrucciones.",
            )
            return
        texto_editado = self._gen_output_area.toPlainText().strip()
        if not texto_editado:
            QMessageBox.warning(self, "Sin texto", "No hay resolución para iterar.")
            return
        instruccion = self._iter_instruccion_edit.toPlainText().strip()

        if full_document:
            ans = QMessageBox.question(
                self,
                "Consolidar acto íntegro",
                "Se generará una **versión única completa** del auto/sentencia, integrando "
                "el texto que ve en el área (incluidos ajustes puntuales o versiones anteriores).\n\n"
                "Este paso suele tardar más y usar más modelo que las correcciones punto a punto.\n\n"
                "¿Continuar?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if ans != QMessageBox.StandardButton.Yes:
                return

        api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if not api_key:
            QMessageBox.warning(self, "API Key", "Configura ANTHROPIC_API_KEY primero.")
            return

        modo = "resolucion_completa" if full_document else "solo_correcciones"
        bib_mode = "off"
        if self._iter_bib_chk.isChecked():
            bib_mode = self._iter_bib_mode.currentData() or "matched"
            if bib_mode not in ("matched", "full"):
                bib_mode = "matched"
        self._apply_iter_btn.setEnabled(False)
        self._consolid_iter_btn.setEnabled(False)
        self._cancel_iter_btn.setVisible(True)
        self._iter_status_lbl.setText(
            "Generando acto consolidado íntegro…"
            if full_document
            else "Aplicando modificaciones (solo puntos solicitados)…"
        )
        self._iter_worker = _IterWorker(
            texto=texto_editado,
            instruccion_iter=instruccion,
            api_key=api_key,
            instruccion_general=self._instruccion_general_edit.toPlainText().strip(),
            instruccion_particular_caso=self._instruccion_edit.toPlainText().strip(),
            materia_label_txt=materia_label(self._last_materia_prompt),
            materia_slug=(self._last_materia_prompt or "").strip(),
            bib_reinject_mode=bib_mode,
            iteration_mode=modo,
            parent=self,
        )
        self._iter_worker.chunk_ready.connect(self._on_iter_chunk)
        self._iter_worker.iteration_finished.connect(self._on_iter_finished)
        self._iter_worker.error_occurred.connect(self._on_iter_error)
        self._iter_worker.status.connect(self._iter_status_lbl.setText)
        self._iter_worker.start()

    def _cancel_iteration(self):
        if hasattr(self, "_iter_worker") and self._iter_worker.isRunning():
            self._iter_worker.cancel()
        self._cancel_iter_btn.setVisible(False)
        self._apply_iter_btn.setEnabled(True)
        self._consolid_iter_btn.setEnabled(True)
        self._iter_status_lbl.setText("")

    def _on_iter_chunk(self, text: str):
        if not hasattr(self, "_iter_started") or not self._iter_started:
            # Insertar separador de versión antes del primer chunk
            from datetime import datetime as _dt

            full = (
                getattr(self._iter_worker, "iteration_mode", "") == "resolucion_completa"
            )
            self._iter_version = getattr(self, "_iter_version", 1) + 1
            dt = _dt.now().strftime("%d/%m/%Y %H:%M")
            if full:
                sep = (
                    f"\n\n{'─' * 60}\n"
                    f"### Versión íntegra consolidada — {dt}\n"
                    f"_(orden de consolidación n.º {self._iter_version})_\n"
                    f"{'─' * 60}\n\n"
                )
            else:
                sep = (
                    f"\n\n{'─' * 60}\n"
                    f"### Ajustes puntuales — {dt}\n"
                    f"_(orden de iteración n.º {self._iter_version})_\n"
                    f"{'─' * 60}\n\n"
                )
            cursor = self._gen_output_area.textCursor()
            cursor.movePosition(cursor.MoveOperation.End)
            cursor.insertText(sep)
            self._gen_output_area.setTextCursor(cursor)
            self._iter_started = True
        cursor = self._gen_output_area.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText(text)
        self._gen_output_area.setTextCursor(cursor)
        self._gen_output_area.ensureCursorVisible()

    def _on_iter_finished(self):
        self._iter_started = False
        self._cancel_iter_btn.setVisible(False)
        self._apply_iter_btn.setEnabled(True)
        self._consolid_iter_btn.setEnabled(True)
        full = getattr(self._iter_worker, "iteration_mode", "") == "resolucion_completa"
        self._iter_status_lbl.setText(
            "✓ Acto íntegro consolidado guardado abajo."
            if full
            else "✓ Corrección(es) aplicada(s) debajo."
        )
        # — Fase 4: aprendizaje silencioso desde la instrucción de corrección —
        instruccion_iter = getattr(self, "_iter_instruccion_edit", None)
        if instruccion_iter:
            instruccion_text = instruccion_iter.toPlainText().strip()
            if instruccion_text and self._last_materia_prompt:
                self._learning_worker = CorrectionLearningWorker(
                    instruccion_text,
                    self._last_materia_prompt,
                    parent=self,
                )
                self._learning_worker.start()
        self._iter_instruccion_edit.clear()
        texto = self._gen_output_area.toPlainText().strip()
        mode = getattr(self._iter_worker, "iteration_mode", "solo_correcciones")
        vr = self._validate_gen_output(
            texto,
            expect_full_act=(mode == "resolucion_completa"),
            iteration_mode=mode,
        )
        self._apply_output_validation_ui(vr)
        self._save_gen_output(silent=True)

    def _on_iter_error(self, msg: str):
        self._cancel_iter_btn.setVisible(False)
        self._apply_iter_btn.setEnabled(True)
        self._consolid_iter_btn.setEnabled(True)
        self._iter_status_lbl.setText(f"Error: {msg[:120]}")

    def _open_editor_fullscreen(self):
        """Abre la resolución en un editor de pantalla completa para editar."""
        dlg = QDialog(self)
        dlg.setWindowTitle("Editor Word — Resolución")
        dlg.resize(1100, 780)
        dlg.setStyleSheet(f"background-color: {BG}; color: {TEXT};")
        dv = QVBoxLayout(dlg)
        dv.setContentsMargins(16, 16, 16, 16)
        dv.setSpacing(10)

        lbl = QLabel(
            "Edita la resolución directamente en vista tipo Word. "
            "Los cambios se reflejan en la app al guardar."
        )
        lbl.setStyleSheet(f"color: {MUTED}; font-size: 11px;")
        dv.addWidget(lbl)

        word_canvas = QFrame()
        word_canvas.setStyleSheet("QFrame { background-color: #d0d0d0; border: none; }")
        word_canvas_layout = QVBoxLayout(word_canvas)
        word_canvas_layout.setContentsMargins(58, 34, 58, 34)
        word_canvas_layout.setSpacing(0)

        editor = QTextEdit()
        editor.setPlainText(self._gen_output_area.toPlainText())
        editor.setStyleSheet(_qss_word_editor())
        _word_font = QFont("Arial Narrow", 14)
        _word_font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
        editor.setFont(_word_font)
        editor.document().setDefaultFont(_word_font)
        editor.document().setDocumentMargin(0)
        word_canvas_layout.addWidget(editor)
        dv.addWidget(word_canvas, 1)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Close
        )
        btns.button(QDialogButtonBox.StandardButton.Save).setText("Guardar cambios")
        btns.button(QDialogButtonBox.StandardButton.Close).setText("Cerrar sin guardar")
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        dv.addWidget(btns)

        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._gen_output_area.setPlainText(editor.toPlainText())
            self._save_gen_output(silent=True)

    def _export_gen_docx(self):
        """Guarda primero y exporta a Word en formato judicial real (Arial Narrow, márgenes de la Sala)."""
        self._save_gen_output(silent=True)
        if not self._export_allowed_after_validation():
            return
        if not self._last_folder_rel or not self._last_materia_prompt:
            return
        from app.core.file_manager import list_resoluciones, export_to_docx
        resoluciones = list_resoluciones(self._last_materia_prompt)
        if not resoluciones:
            QMessageBox.information(self, "Sin archivo", "Guarda la resolución primero.")
            return
        md_path = resoluciones[0]  # la más reciente
        # Metadatos del formulario activo → cabecera del Word
        meta = {
            "expediente":  getattr(self, "_exp_edit",  None) and self._exp_edit.text().strip()  or "",
            "imputado":    getattr(self, "_imp_edit",  None) and self._imp_edit.text().strip()  or "",
            "delito":      getattr(self, "_del_edit",  None) and self._del_edit.text().strip()  or "",
            "agraviado":   getattr(self, "_agr_edit",  None) and self._agr_edit.text().strip()  or "",
            "procedencia": "",
        }
        try:
            dest = export_to_docx(md_path, metadata=meta)
            QMessageBox.information(
                self, "Word exportado ✓",
                f"Resolución guardada en formato judicial:\n{dest}"
            )
            if sys.platform == "darwin":
                import subprocess as _sp
                _sp.run(["open", str(dest)], check=False)
        except Exception as e:
            QMessageBox.critical(self, "Error al exportar", str(e))

    def _export_gen_pdf(self):
        """Guarda primero y exporta a PDF."""
        self._save_gen_output(silent=True)
        if not self._export_allowed_after_validation():
            return
        if not self._last_folder_rel or not self._last_materia_prompt:
            return
        from app.core.file_manager import list_resoluciones, export_to_pdf
        resoluciones = list_resoluciones(self._last_materia_prompt)
        if not resoluciones:
            QMessageBox.information(self, "Sin archivo", "Guarda la resolución primero.")
            return
        md_path = resoluciones[0]
        try:
            dest = export_to_pdf(md_path)
            QMessageBox.information(self, "Exportado", f"PDF guardado en:\n{dest}")
            if sys.platform == "darwin":
                import subprocess as _sp
                _sp.run(["open", str(dest)], check=False)
        except Exception as e:
            QMessageBox.critical(self, "Error al exportar", str(e))

    def _upload_plantilla_from_form(self):
        """Sube un archivo como nueva plantilla para la materia activa."""
        m = self._current_materia()
        if m is None:
            QMessageBox.information(self, "Materia", "Elige una materia primero.")
            return
        files, _ = _pick_open_file_names(
            self, "Seleccionar plantilla",
            str(Path.home()),
            "Documentos (*.md *.pdf *.docx *.doc);;Todos (*)",
        )
        if not files:
            return
        from app.core.file_manager import add_plantilla
        for f in files:
            try:
                dest = add_plantilla(Path(f), materia=m)
                self._selected_plantilla = dest
                self._pla_selected_lbl.setText(f"📋  {dest.name}")
                self._pla_selected_lbl.setStyleSheet(
                    f"color: {SUCCESS}; font-size: 12px; font-weight: 600; padding: 4px 0;"
                )
                self._pla_open_btn.setEnabled(True)
            except Exception as e:
                QMessageBox.critical(self, "Error", str(e))

    def _paste_cursor_respuesta_desde_clipboard(self):
        clip = QApplication.clipboard()
        if clip is None:
            return
        t = clip.text()
        if t:
            self._cursor_respuesta_edit.setPlainText(t)

    def _save_cursor_respuesta_a_disco(self):
        if not self._last_folder_rel or not self._last_materia_prompt:
            QMessageBox.warning(
                self, "Sin caso activo",
                "Genera primero el prompt con «PREPARAR CASO».",
            )
            return
        texto = self._cursor_respuesta_edit.toPlainText().strip()
        if not texto:
            QMessageBox.information(
                self, "Vacío",
                "Pegá o escribí el texto que devolvió Cursor antes de guardar.",
            )
            return
        try:
            p = save_resolucion_cursor_text(
                self._last_materia_prompt,
                self._last_folder_rel,
                texto,
            )
            rel = p.relative_to(BASE_DIR)
            QMessageBox.information(
                self, "Guardado",
                f"Resolución guardada:\n\n`{rel}`\n\n"
                "Abrí la pestaña Resoluciones (misma materia) y pulsá «Actualizar» si no la ves.",
            )
        except OSError as e:
            QMessageBox.critical(self, "Error", str(e))

    def _copy_prompt(self):
        QApplication.clipboard().setText(self._prompt_area.toPlainText())
        original = self._copy_prompt_btn.text()
        self._copy_prompt_btn.setText("✓ Copiado")
        QTimer.singleShot(2000, lambda: self._copy_prompt_btn.setText(original))

    def _return_to_welcome_keep_draft(self):
        """Muestra la pantalla inicial (logo, historial). Si antes se llamó a reset_draft_for_materia_change, el formulario ya está limpio."""
        self._form_panel.setVisible(False)
        self._start_panel.setVisible(True)
        self.refresh_materia_dependent_ui()

    def _reset(self):
        """Descarta todo el borrador y vuelve al inicio (solo «＋ Nuevo caso» en el bloque del prompt)."""
        self._clear_case_draft_shared()
        self._form_panel.setVisible(False)
        self._start_panel.setVisible(True)
        self.refresh_materia_dependent_ui()

    def _import_corrected_word(self):
        """Abre el Word corregido por el juez, extrae el texto y genera una v2 con Claude."""
        path, _ = _pick_open_file_name(
            self,
            "Seleccionar Word corregido",
            str(Path.home() / "Desktop"),
            "Word (*.docx *.doc);;Todos (*)",
        )
        if not path:
            return

        try:
            from app.core.claude_worker import read_file_text
            texto_corregido = read_file_text(Path(path))
        except Exception:
            try:
                import docx as _dx
                doc = _dx.Document(path)
                texto_corregido = "\n".join(p.text for p in doc.paragraphs)
            except Exception as e:
                QMessageBox.critical(self, "Error", f"No se pudo leer el Word:\n{e}")
                return

        if not texto_corregido or not texto_corregido.strip():
            QMessageBox.warning(self, "Vacío", "El Word no tiene texto legible.")
            return

        texto_original = self._gen_output_area.toPlainText().strip()
        materia_slug = self._last_materia_prompt if hasattr(self, '_last_materia_prompt') else ""
        materia_txt = materia_label(materia_slug) if materia_slug else "materia penal"

        instruccion_v2 = (
            f"El magistrado corrigió manualmente la resolución en Microsoft Word. "
            f"Genera una versión 2 (v2) limpia y completa incorporando TODAS las correcciones, "
            f"manteniendo el formato judicial de la Sala Penal ({materia_txt}). "
            f"No omitas ningún considerando ni sección. Listo para firmar.\n\n"
            f"DOCUMENTO CORREGIDO:\n{texto_corregido[:60000]}"
        )

        api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if not api_key:
            QMessageBox.warning(self, "API Key", "Configura ANTHROPIC_API_KEY primero.")
            return

        # Aprendizaje silencioso
        if texto_original and materia_slug:
            _lw = CorrectionLearningWorker(
                f"Correcciones en Word. Original: {texto_original[:2000]}. "
                f"Corregido: {texto_corregido[:2000]}",
                materia_slug, parent=self,
            )
            _lw.start()

        self._gen_export_docx_btn.setEnabled(False)
        self._gen_import_corrected_btn.setEnabled(False)
        self._gen_import_corrected_btn.setText("Generando v2...")
        if hasattr(self, '_iter_status_lbl'):
            self._iter_status_lbl.setText("Leyendo correcciones y generando v2...")

        instruccion_general = ""
        instruccion_particular = ""
        if hasattr(self, '_instruccion_general_edit'):
            instruccion_general = self._instruccion_general_edit.toPlainText().strip()
        if hasattr(self, '_instruccion_edit'):
            instruccion_particular = self._instruccion_edit.toPlainText().strip()

        self._iter_worker = _IterWorker(
            texto=texto_original or texto_corregido,
            instruccion_iter=instruccion_v2,
            api_key=api_key,
            instruccion_general=instruccion_general,
            instruccion_particular_caso=instruccion_particular,
            materia_label_txt=materia_txt,
            materia_slug=materia_slug,
            bib_reinject_mode="off",
            iteration_mode="resolucion_completa",
            parent=self,
        )
        self._iter_worker.chunk_ready.connect(self._on_iter_chunk)
        self._iter_worker.iteration_finished.connect(self._on_corrected_word_finished)
        self._iter_worker.error_occurred.connect(self._on_corrected_word_error)
        if hasattr(self, "_iter_status_lbl"):
            self._iter_worker.status.connect(self._iter_status_lbl.setText)
        self._iter_worker.start()

    def _on_corrected_word_finished(self):
        self._iter_started = False
        self._gen_export_docx_btn.setEnabled(True)
        self._gen_import_corrected_btn.setEnabled(True)
        self._gen_import_corrected_btn.setText("\U0001f4c2  Word corregido → v2")
        if hasattr(self, '_iter_status_lbl'):
            self._iter_status_lbl.setText("✓ v2 generada. Revisa y exporta a Word.")
        self._save_gen_output(silent=True)

    def _on_corrected_word_error(self, msg: str):
        self._gen_export_docx_btn.setEnabled(True)
        self._gen_import_corrected_btn.setEnabled(True)
        self._gen_import_corrected_btn.setText("\U0001f4c2  Word corregido → v2")
        if hasattr(self, '_iter_status_lbl'):
            self._iter_status_lbl.setText(f"Error: {msg[:120]}")


class ResolucionesPage(QWidget):
    def __init__(self, materia_getter=None, parent=None):
        super().__init__(parent)
        self._materia_getter = materia_getter or (lambda: DEFAULT_MATERIA)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 24)
        layout.setSpacing(12)

        hdr_row = QHBoxLayout()
        h = QLabel("RESOLUCIONES GENERADAS")
        h.setStyleSheet(
            f"color: {GOLD}; font-size: 18px; font-weight: 700; letter-spacing: 2px;"
        )
        refresh = QPushButton("↺  Actualizar")
        refresh.setFixedHeight(32)
        refresh.clicked.connect(self._load_list)
        open_res = QPushButton("📂  Abrir carpeta")
        open_res.setFixedHeight(32)
        open_res.setToolTip(
            "Abre en el Finder la carpeta donde deben guardarse los .md "
            "(Adiutor Iudicis solo muestra archivos ya guardados ahí)."
        )
        open_res.clicked.connect(self._open_resoluciones_folder)
        hdr_row.addWidget(h)
        hdr_row.addStretch()
        hdr_row.addWidget(open_res)
        hdr_row.addWidget(refresh)
        layout.addLayout(hdr_row)

        self._sub = QLabel("")
        self._sub.setWordWrap(True)
        self._sub.setStyleSheet(f"color: {MUTED}; font-size: 12px;")
        layout.addWidget(self._sub)

        self._current_path: Path | None = None
        # Contenido .md original (copiar / iterar prompt); la vista usa Markdown enriquecido
        self._viewer_source_text: str = ""

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(2)

        # Left: file list
        left = QWidget()
        left_vbox = QVBoxLayout(left)
        left_vbox.setContentsMargins(0, 0, 0, 0)
        left_vbox.setSpacing(6)
        self._list = QListWidget()
        self._list.currentItemChanged.connect(self._on_select)
        left_vbox.addWidget(self._list)
        splitter.addWidget(left)

        # Right: viewer
        right = QWidget()
        right_vbox = QVBoxLayout(right)
        right_vbox.setContentsMargins(0, 0, 0, 0)
        right_vbox.setSpacing(8)

        btn_row = QHBoxLayout()
        self._copy_btn = QPushButton("Copiar todo")
        self._copy_btn.setFixedHeight(30)
        self._copy_btn.clicked.connect(self._copy_content)
        self._save_btn = QPushButton("Guardar como TXT")
        self._save_btn.setFixedHeight(30)
        self._save_btn.clicked.connect(self._save_content)

        _export_btn_style = f"""
            QPushButton {{
                background-color: {BG_CARD}; color: {GOLD};
                border: 1px solid {GOLD}; border-radius: 6px;
                padding: 4px 14px; font-size: 12px; font-weight: 600;
            }}
            QPushButton:hover {{ background-color: {GOLD}; color: {TEXT_ON_GOLD}; }}
            QPushButton:disabled {{ color: {MUTED}; border-color: {BORDER}; }}
        """
        self._export_docx_btn = QPushButton("⬇  Word (.docx)")
        self._export_docx_btn.setFixedHeight(30)
        self._export_docx_btn.setStyleSheet(_export_btn_style)
        self._export_docx_btn.setEnabled(False)
        self._export_docx_btn.clicked.connect(self._export_docx)

        self._export_pdf_btn = QPushButton("⬇  PDF")
        self._export_pdf_btn.setFixedHeight(30)
        self._export_pdf_btn.setStyleSheet(_export_btn_style)
        self._export_pdf_btn.setEnabled(False)
        self._export_pdf_btn.clicked.connect(self._export_pdf)

        btn_row.addWidget(self._export_docx_btn)
        btn_row.addWidget(self._export_pdf_btn)
        btn_row.addStretch()
        btn_row.addWidget(self._copy_btn)
        btn_row.addWidget(self._save_btn)
        right_vbox.addLayout(btn_row)

        self._viewer = QTextEdit()
        self._viewer.setReadOnly(True)
        self._viewer.setAcceptRichText(True)
        self._viewer.setStyleSheet(_qss_text_reader())
        self._viewer.document().setDefaultStyleSheet(_resolucion_viewer_document_css())
        self._viewer.document().setDocumentMargin(12)
        _rv_font = QFont("Georgia", 13)
        self._viewer.setFont(_rv_font)
        self._viewer.document().setDefaultFont(_rv_font)
        self._viewer.setPlaceholderText(
            "Selecciona una resolución de la lista para verla aquí."
        )
        right_vbox.addWidget(self._viewer)

        # placeholders para compatibilidad interna
        self._iter_edit = QTextEdit()
        self._iter_edit.setVisible(False)
        self._iter_btn = QPushButton()
        self._iter_btn.setVisible(False)
        self._iter_copy_btn = QPushButton()
        self._iter_copy_btn.setVisible(False)
        self._iter_prompt_area = QTextEdit()
        self._iter_prompt_area.setVisible(False)
        splitter.addWidget(right)

        splitter.setSizes([280, 720])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, 1)

        self._load_list()

    def showEvent(self, event: QShowEvent):
        """Vuelve a leer la carpeta al mostrar la pestaña (archivos añadidos fuera de la app)."""
        super().showEvent(event)
        self._load_list()

    def _load_list(self):
        m = self._materia_getter()
        if m is None:
            self._sub.setText(
                "Elige una materia en la barra lateral (nombre de la materia o "
                "Bibliografía / Plantillas / Resoluciones)."
            )
            self._list.clear()
            self._viewer.clear()
            self._viewer_source_text = ""
            return
        self._list.clear()
        self._viewer.clear()
        self._viewer_source_text = ""
        files = list_resoluciones(m)
        base_rel = f"03_outputs/resoluciones/{m}/"
        if not files:
            self._sub.setText(
                f"{base_rel}\n\n"
                "Aún no hay archivos .md en esta carpeta. La app no crea la resolución sola: "
                "cuando Cursor termine el borrador, guarda el archivo aquí (nombre descriptivo, "
                "p. ej. caso_006_lesiones_culposas_autovista.md) y pulsa «↺ Actualizar»."
            )
        else:
            self._sub.setText(
                f"{base_rel}  —  borradores .md (más recientes primero). "
                "Lectura con formato (Markdown): títulos, listas y énfasis. "
                "Si acabas de guardar un archivo fuera de la app, pulsa «Actualizar»."
            )
        for f in files:
            item = QListWidgetItem(f.name)
            item.setData(Qt.ItemDataRole.UserRole, f)
            self._list.addItem(item)
        if self._list.count():
            self._list.setCurrentRow(0)

    def _open_resoluciones_folder(self):
        m = self._materia_getter()
        if m is None:
            QMessageBox.information(
                self, "Materia",
                "Elige primero una materia en la barra lateral.",
            )
            return
        d = dir_resoluciones_materia(m)
        path = str(d.resolve())
        try:
            if sys.platform == "darwin":
                subprocess.run(["open", path], check=False)
            elif sys.platform == "win32":
                os.startfile(path)  # type: ignore[attr-defined]
            else:
                QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        except Exception as e:
            QMessageBox.warning(
                self, "No se pudo abrir la carpeta", f"{path}\n\n{e}",
            )

    def _on_select(self, current, _prev):
        if not current:
            return
        path: Path = current.data(Qt.ItemDataRole.UserRole)
        self._current_path = path
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            self._viewer_source_text = text
            is_md = path.suffix.lower() == ".md"
            if is_md:
                try:
                    prepared = _markdown_resolve_local_images(text, path.parent)
                    self._viewer.setMarkdown(prepared)
                    if not self._viewer.toPlainText().strip():
                        self._viewer.setPlainText(text)
                except Exception:
                    self._viewer.setPlainText(text)
            else:
                self._viewer.setPlainText(text)
            self._viewer.document().setDefaultFont(QFont("Georgia", 13))
            self._iter_prompt_area.setVisible(False)
            self._iter_copy_btn.setVisible(False)
            self._export_docx_btn.setEnabled(is_md)
            self._export_pdf_btn.setEnabled(is_md)
        except Exception as e:
            self._viewer_source_text = ""
            self._viewer.setPlainText(f"Error leyendo archivo:\n{e}")

    def _copy_content(self):
        t = self._viewer_source_text.strip() if self._viewer_source_text else ""
        if not t:
            t = self._viewer.toPlainText()
        if t:
            QApplication.clipboard().setText(t)

    def _save_content(self):
        t = self._viewer_source_text if self._viewer_source_text else self._viewer.toPlainText()
        if not t:
            return
        path, _ = _pick_save_file_name(
            self, "Guardar resolución", "", "Texto (*.txt *.md)"
        )
        if path:
            Path(path).write_text(t, encoding="utf-8")

    def _export_docx(self):
        if not self._current_path:
            return
        try:
            from app.core.file_manager import export_to_docx
            dest = export_to_docx(self._current_path)
            _open_with_system_default(self, dest)
        except Exception as e:
            QMessageBox.warning(self, "Error al exportar", str(e))

    def _export_pdf(self):
        if not self._current_path:
            return
        try:
            from app.core.file_manager import export_to_pdf
            dest = export_to_pdf(self._current_path)
            _open_with_system_default(self, dest)
        except Exception as e:
            QMessageBox.warning(self, "Error al exportar", str(e))

    def _generate_iter_prompt(self):
        content = (
            self._viewer_source_text.strip()
            if self._viewer_source_text
            else self._viewer.toPlainText().strip()
        )
        instruccion = self._iter_edit.toPlainText().strip()
        if not content:
            QMessageBox.warning(self, "Sin resolución", "Selecciona una resolución primero.")
            return
        item = self._list.currentItem()
        file_name = item.text() if item else "resolución"

        # Compute next version suffix
        stem = Path(file_name).stem
        suffix = Path(file_name).suffix or ".md"
        import re as _re
        m = _re.search(r"_v(\d+)$", stem)
        if m:
            next_v = int(m.group(1)) + 1
            base_stem = stem[:m.start()]
        else:
            next_v = 1
            base_stem = stem
        new_name = f"{base_stem}_v{next_v}{suffix}"
        mat = self._materia_getter()
        if mat is None:
            QMessageBox.information(
                self, "Materia",
                "Elige primero una materia en la barra lateral.",
            )
            return

        instruccion_line = f"\n\nInstrucción: {instruccion}" if instruccion else ""
        prompt = (
            f"Revisa y mejora la siguiente resolución judicial ({file_name})."
            f"{instruccion_line}\n\n"
            f"IMPORTANTE: NO sobreescribas el archivo original. "
            f"Guarda el resultado como un archivo NUEVO: "
            f"03_outputs/resoluciones/{mat}/{new_name}\n\n"
            f"Mantén el formato exacto de la plantilla maestra (encabezado, numerales I-VII, "
            f"tabla de datos, firma S.S.).\n\n"
            f"--- RESOLUCIÓN ACTUAL ({file_name}) ---\n"
            f"{content[:3000]}{'...[continúa]' if len(content) > 3000 else ''}"
        )
        self._iter_prompt_area.setPlainText(prompt)
        self._iter_prompt_area.setVisible(True)
        self._iter_copy_btn.setVisible(True)

    def _copy_iter_prompt(self):
        t = self._iter_prompt_area.toPlainText()
        if t:
            QApplication.clipboard().setText(t)
            orig = self._iter_copy_btn.text()
            self._iter_copy_btn.setText("✓ Copiado")
            QTimer.singleShot(2000, lambda: self._iter_copy_btn.setText(orig))


class _FileLibraryPage(QWidget):
    """Bibliografía por materia del caso (carpeta 01_raw/bibliografia/<materia>/)."""

    def __init__(
        self,
        title: str,
        materia_getter,
        file_filter: str,
        parent=None,
        format_hint: str | None = None,
        bib_ficha_cb=None,
    ):
        super().__init__(parent)
        self._materia_getter = materia_getter
        self._bib_ficha_cb = bib_ficha_cb
        self._filter = file_filter
        self._dest_dir = dir_bibliografia_materia(DEFAULT_MATERIA)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 24)
        layout.setSpacing(14)

        hdr_row = QHBoxLayout()
        h = QLabel(title)
        h.setStyleSheet(
            f"color: {GOLD}; font-size: 18px; font-weight: 700; letter-spacing: 2px;"
        )
        hdr_row.addWidget(h)
        hdr_row.addStretch()
        layout.addLayout(hdr_row)

        self._path_lbl = QLabel()
        self._path_lbl.setStyleSheet(f"color: {MUTED}; font-size: 12px;")
        layout.addWidget(self._path_lbl)
        if format_hint:
            hint_lbl = QLabel(format_hint)
            hint_lbl.setWordWrap(True)
            hint_lbl.setStyleSheet(f"color: {MUTED}; font-size: 11px;")
            layout.addWidget(hint_lbl)

        _open_style = f"""
            QPushButton {{
                background-color: {BG_CARD}; color: {GOLD};
                border: 1px solid {GOLD}; border-radius: 6px;
                padding: 4px 14px; font-size: 12px; font-weight: 600;
            }}
            QPushButton:hover {{ background-color: {GOLD}; color: {TEXT_ON_GOLD}; }}
            QPushButton:disabled {{ color: {MUTED}; border-color: {BORDER}; background: {BG_CARD}; }}
        """
        btn_row = QHBoxLayout()
        add_btn = _btn(f"＋  Agregar archivo")
        add_btn.clicked.connect(self._add_file)
        self._open_btn = QPushButton("📂  Ver / abrir")
        self._open_btn.setFixedHeight(34)
        self._open_btn.setToolTip(
            "Markdown y .txt: vista de solo lectura en WikiJuez. "
            "Para cambiar el texto use \u00abEditar\u00bb o doble clic sobre el archivo. "
            "PDF y Word: aplicaci\u00f3n del sistema."
        )
        self._open_btn.setStyleSheet(_open_style)
        self._open_btn.setEnabled(False)
        self._open_btn.clicked.connect(self._open_file)
        self._edit_note_btn = QPushButton("✎  Editar")
        self._edit_note_btn.setFixedHeight(34)
        self._edit_note_btn.setToolTip(
            "S\u00f3lo Markdown y .txt: edita el contenido y gu\u00e1rdalo "
            "sobre el mismo archivo (UTF-8)."
        )
        self._edit_note_btn.setStyleSheet(_open_style)
        self._edit_note_btn.setEnabled(False)
        self._edit_note_btn.clicked.connect(self._edit_bibliografia_note)
        self._probe_pdf_btn = QPushButton("🔎  Probar lectura PDF")
        self._probe_pdf_btn.setFixedHeight(34)
        self._probe_pdf_btn.setToolTip(
            "Ejecuta la misma extracción **local** que usará el prompt (pdfplumber + OCR en esta Mac). "
            "Eso no equivale a subir el PDF al chat web de Claude (otro procesamiento en servidor). "
            "Si la vista previa es mala: mismo_nombre.txt/.md junto al PDF, o en «Generar con Claude» "
            "dejar ADIUTOR_API_PDF_ATTACH=1 para enviar el PDF por API. Ver README."
        )
        self._probe_pdf_btn.setStyleSheet(_open_style)
        self._probe_pdf_btn.setEnabled(False)
        self._probe_pdf_btn.clicked.connect(self._probe_bibliografia_pdf)
        self._del_btn = QPushButton("✕  Eliminar")
        self._del_btn.setFixedHeight(34)
        self._del_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {BG_CARD}; color: {ERROR};
                border: 1px solid {ERROR}; border-radius: 6px;
                padding: 4px 14px; font-size: 12px; font-weight: 600;
            }}
            QPushButton:hover {{ background-color: {ERROR}; color: #ffffff; }}
            QPushButton:disabled {{ color: {MUTED}; border-color: {BORDER}; background: {BG_CARD}; }}
        """)
        self._del_btn.setEnabled(False)
        self._del_btn.clicked.connect(self._delete_file)
        refresh_btn = QPushButton("↺  Actualizar")
        refresh_btn.setFixedHeight(34)
        refresh_btn.clicked.connect(self._load)
        self._ficha_btn = QPushButton("📄 Fichas doctrina")
        self._ficha_btn.setFixedHeight(34)
        self._ficha_btn.setToolTip(
            "Ingest Haiku desde archivos pendientes → 02_wiki/bibliografia/<materia>/ "
            "(índice en 01_raw/bibliografia/<materia>/). Env ADIUTOR_CORPUS_FICHA_*."
        )
        self._ficha_btn.setStyleSheet(_open_style)
        self._ficha_btn.setVisible(bool(bib_ficha_cb))
        self._ficha_btn.clicked.connect(self._run_bib_ficha_ingest)
        btn_row.addWidget(add_btn)
        btn_row.addWidget(self._open_btn)
        btn_row.addWidget(self._edit_note_btn)
        btn_row.addWidget(self._probe_pdf_btn)
        btn_row.addWidget(self._del_btn)
        btn_row.addWidget(self._ficha_btn)
        btn_row.addStretch()
        btn_row.addWidget(refresh_btn)
        layout.addLayout(btn_row)

        quick_row = QHBoxLayout()
        self._juris_quick_btn = QPushButton("⚡ Nota rápida de jurisprudencia…")
        self._juris_quick_btn.setFixedHeight(34)
        self._juris_quick_btn.setToolTip(
            "Abre un editor con plantilla (STC, Casación…); guarda un .md en la bibliografía de esta materia."
        )
        self._juris_quick_btn.setStyleSheet(_open_style)
        self._juris_quick_btn.clicked.connect(self._juris_quick_note)
        quick_row.addWidget(self._juris_quick_btn)
        quick_row.addStretch()
        layout.addLayout(quick_row)

        self._list = QListWidget()
        self._list.currentItemChanged.connect(self._on_bib_select)
        self._list.itemDoubleClicked.connect(self._on_bib_double_click)
        layout.addWidget(self._list, 1)

        bib_use = QLabel(
            "Al preparar o generar la resolución con esta misma materia en la barra lateral, "
            "todos estos archivos se incrustan en el prompt (BLOQUE 5 · bibliografía autorizada)."
        )
        bib_use.setWordWrap(True)
        bib_use.setStyleSheet(f"color: {MUTED}; font-size: 10px;")
        layout.addWidget(bib_use)

        self._count_lbl = QLabel("")
        self._count_lbl.setStyleSheet(f"color: {MUTED}; font-size: 11px;")
        layout.addWidget(self._count_lbl)

        self._load()

    def _run_bib_ficha_ingest(self):
        if self._bib_ficha_cb:
            self._bib_ficha_cb()

    def _juris_quick_note(self):
        m = self._materia_getter()
        if m is None:
            QMessageBox.information(
                self,
                "Materia",
                "Elija primero una materia en la barra lateral.",
            )
            return
        dlg = JurisQuickNoteDialog(self, materia_slug=m)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._load()

    def _load(self):
        m = self._materia_getter()
        if m is None:
            self._path_lbl.setText("—  (elige una materia en la barra lateral)")
            self._list.clear()
            self._count_lbl.setText("")
            return
        self._dest_dir = dir_bibliografia_materia(m)
        self._path_lbl.setText(f"📁  {self._dest_dir.relative_to(BASE_DIR)}")
        self._list.clear()
        files = list_bibliografia(m)
        for f in files:
            size_kb = max(1, f.stat().st_size // 1024)
            try:
                rel = f.relative_to(self._dest_dir)
                label = str(rel) if len(rel.parts) > 1 else f.name
            except ValueError:
                label = f.name
            item = QListWidgetItem(f"📄  {label}  ({size_kb} KB)")
            item.setData(Qt.ItemDataRole.UserRole, f)
            self._list.addItem(item)
        n = len(files)
        self._count_lbl.setText(f"{n} archivo{'s' if n != 1 else ''}")
        if self._list.count() > 0:
            self._list.setCurrentRow(0)
        else:
            self._open_btn.setEnabled(False)
            self._edit_note_btn.setEnabled(False)
            self._probe_pdf_btn.setEnabled(False)
            self._del_btn.setEnabled(False)

    def _on_bib_select(self, current, _prev):
        enabled = current is not None
        self._open_btn.setEnabled(enabled)
        self._del_btn.setEnabled(enabled)
        edit_ok = False
        pdf_ok = False
        if current is not None:
            pth: Path = current.data(Qt.ItemDataRole.UserRole)
            suf = pth.suffix.lower()
            edit_ok = suf in (".md", ".txt")
            pdf_ok = suf == ".pdf"
        self._edit_note_btn.setEnabled(enabled and edit_ok)
        self._probe_pdf_btn.setEnabled(enabled and pdf_ok)

    def _on_bib_double_click(self, _item: QListWidgetItem):
        cur = self._list.currentItem()
        if not cur:
            return
        path: Path = cur.data(Qt.ItemDataRole.UserRole)
        if path.suffix.lower() in (".md", ".txt"):
            if open_edit_bibliografia_note(self, path):
                self._load()
            return
        self._open_file()

    def _add_file(self):
        m = self._materia_getter()
        if m is None:
            QMessageBox.information(
                self, "Materia",
                "Elige primero una materia en la barra lateral.",
            )
            return
        paths, _ = _pick_open_file_names(
            self, "Seleccionar archivos", str(self._dest_dir), self._filter
        )
        added = 0
        for p in paths:
            try:
                add_bibliografia(Path(p), materia=m)
                added += 1
            except Exception as e:
                QMessageBox.warning(self, "Error", f"No se pudo copiar {Path(p).name}:\n{e}")
        if added:
            self._load()

    def _open_file(self):
        item = self._list.currentItem()
        if not item:
            return
        path: Path = item.data(Qt.ItemDataRole.UserRole)
        if path.suffix.lower() in (".md", ".txt"):
            _show_markdown_viewer(self, path)
            return
        _open_with_system_default(self, path)

    def _edit_bibliografia_note(self):
        item = self._list.currentItem()
        if not item:
            return
        path: Path = item.data(Qt.ItemDataRole.UserRole)
        if path.suffix.lower() not in (".md", ".txt"):
            return
        if open_edit_bibliografia_note(self, path):
            self._load()

    def _probe_bibliografia_pdf(self):
        item = self._list.currentItem()
        if not item:
            return
        path: Path = item.data(Qt.ItemDataRole.UserRole)
        if path.suffix.lower() != ".pdf":
            return
        try:
            wc, cc, prev, bad = probe_pdf_readability(path)
        except Exception as e:
            QMessageBox.warning(self, "Probar PDF", f"Error al leer el PDF:\n{e}")
            return
        estado = (
            "DÉBIL o mensaje de error — conviene .txt/.md compañero, subir DPI/ZOOM o revisar Tesseract."
            if bad
            else "La extracción supera el umbral mínimo heurístico (siga revisando calidad en la vista previa)."
        )
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Lectura de PDF — {path.name}")
        dlg.resize(720, 520)
        lo = QVBoxLayout(dlg)
        meta = QLabel(
            f"Tokens (~palabras de 4+ letras): {wc}\n"
            f"Caracteres totales: {cc}\n\n{estado}"
        )
        meta.setWordWrap(True)
        lo.addWidget(meta)
        te = QPlainTextEdit()
        te.setReadOnly(True)
        te.setPlainText(prev)
        te.setStyleSheet(_qss_text_code_readonly())
        lo.addWidget(te, 1)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(dlg.close)
        bb.accepted.connect(dlg.close)
        lo.addWidget(bb)
        dlg.exec()

    def _delete_file(self):
        item = self._list.currentItem()
        if not item:
            return
        path: Path = item.data(Qt.ItemDataRole.UserRole)
        reply = QMessageBox.question(
            self, "Eliminar archivo",
            f"¿Eliminar permanentemente de la bibliografía?\n\n{path.name}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if reply == QMessageBox.StandardButton.Yes:
            try:
                path.unlink()
                self._load()
            except Exception as e:
                QMessageBox.warning(self, "Error", f"No se pudo eliminar:\n{e}")


# ─── Plantillas Page ─────────────────────────────────────────────────────────

class PlantillasPage(QWidget):
    """Plantillas por materia — 01_raw/plantillas/<materia>/"""

    def __init__(self, materia_getter=None, parent=None):
        super().__init__(parent)
        self._materia_getter = materia_getter or (lambda: DEFAULT_MATERIA)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 24)
        layout.setSpacing(12)

        # Header
        hdr_row = QHBoxLayout()
        h = QLabel("BIBLIOTECA DE PLANTILLAS")
        h.setStyleSheet(
            f"color: {GOLD}; font-size: 18px; font-weight: 700; letter-spacing: 2px;"
        )
        refresh_btn = QPushButton("↺  Actualizar")
        refresh_btn.setFixedHeight(32)
        refresh_btn.clicked.connect(self._load)
        hdr_row.addWidget(h)
        hdr_row.addStretch()
        hdr_row.addWidget(refresh_btn)
        layout.addLayout(hdr_row)

        self._sub = QLabel("")
        self._sub.setWordWrap(True)
        self._sub.setStyleSheet(f"color: {MUTED}; font-size: 12px;")
        layout.addWidget(self._sub)

        # Buttons
        btn_row = QHBoxLayout()
        add_btn = _btn("＋  Subir nueva plantilla")
        add_btn.clicked.connect(self._upload)

        _action_style = f"""
            QPushButton {{
                background-color: {BG_CARD}; color: {GOLD};
                border: 1px solid {GOLD}; border-radius: 6px;
                padding: 4px 14px; font-size: 12px; font-weight: 600;
            }}
            QPushButton:hover {{ background-color: {GOLD}; color: {TEXT_ON_GOLD}; }}
            QPushButton:disabled {{ color: {MUTED}; border-color: {BORDER}; background: {BG_CARD}; }}
        """
        self._open_btn = QPushButton("📂  Abrir")
        self._open_btn.setFixedHeight(34)
        self._open_btn.setStyleSheet(_action_style)
        self._open_btn.setEnabled(False)
        self._open_btn.setToolTip("Abre el archivo para revisarlo (Markdown en ventana integrada; resto con la app del sistema).")
        self._open_btn.clicked.connect(lambda: self._open_file())

        self._copy_out_btn = QPushButton("💾  Guardar copia…")
        self._copy_out_btn.setFixedHeight(34)
        self._copy_out_btn.setStyleSheet(_action_style)
        self._copy_out_btn.setEnabled(False)
        self._copy_out_btn.setToolTip(
            "Copia el archivo seleccionado a Descargas u otra carpeta (equivalente a «descargar» del repositorio)."
        )
        self._copy_out_btn.clicked.connect(self._save_copy_elsewhere)

        self._del_btn = QPushButton("✕  Eliminar")
        self._del_btn.setFixedHeight(34)
        self._del_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {BG_CARD}; color: {ERROR};
                border: 1px solid {ERROR}; border-radius: 6px;
                padding: 4px 14px; font-size: 12px; font-weight: 600;
            }}
            QPushButton:hover {{ background-color: {ERROR}; color: #ffffff; }}
            QPushButton:disabled {{ color: {MUTED}; border-color: {BORDER}; background: {BG_CARD}; }}
        """)
        self._del_btn.setEnabled(False)
        self._del_btn.clicked.connect(self._delete_file)

        self._count_lbl = QLabel("")
        self._count_lbl.setStyleSheet(f"color: {MUTED}; font-size: 11px;")

        btn_row.addWidget(add_btn)
        btn_row.addWidget(self._open_btn)
        btn_row.addWidget(self._copy_out_btn)
        btn_row.addWidget(self._del_btn)
        btn_row.addStretch()
        btn_row.addWidget(self._count_lbl)
        layout.addLayout(btn_row)

        # List
        self._list = QListWidget()
        self._list.setStyleSheet(f"""
            QListWidget {{
                background-color: {BG_INPUT}; color: {TEXT};
                border: 1px solid {BORDER}; border-radius: 8px; padding: 6px;
            }}
            QListWidget::item {{ padding: 8px 10px; border-radius: 4px; }}
            QListWidget::item:selected {{ background-color: {GOLD}; color: {BG}; font-weight: 600; }}
        """)
        self._list.currentItemChanged.connect(self._on_select)
        self._list.itemActivated.connect(self._open_file)
        layout.addWidget(self._list, 1)

        self._load()

    def _load(self):
        m = self._materia_getter()
        if m is None:
            self._sub.setText(
                "Elige una materia en la barra lateral (nombre de la materia o "
                "Bibliografía / Plantillas / Resoluciones)."
            )
            self._list.clear()
            self._count_lbl.setText("")
            self._open_btn.setEnabled(False)
            self._copy_out_btn.setEnabled(False)
            self._del_btn.setEnabled(False)
            return
        self._sub.setText(
            f"01_raw/plantillas/{m}/  —  sube y gestiona plantillas para esta materia "
            f"(elige la materia en la barra lateral). "
            f"Doble clic o Enter abre el archivo; «Guardar copia» lo exporta a tu carpeta."
        )
        self._list.clear()
        files = list_plantillas(m)
        plantillas_root = DIRS["plantillas"] / m
        for f in files:
            try:
                rel = f.relative_to(plantillas_root)
                parts = rel.parts
                if len(parts) > 1:
                    folder_icon = "🗂  " + parts[0] + "  /  "
                    label = folder_icon + f.name
                else:
                    label = "📋  " + f.name
            except ValueError:
                label = "📋  " + f.name
            size_kb = max(1, f.stat().st_size // 1024)
            item = QListWidgetItem(f"{label}   ({size_kb} KB)")
            item.setData(Qt.ItemDataRole.UserRole, f)
            self._list.addItem(item)
        n = len(files)
        self._count_lbl.setText(f"{n} plantilla{'s' if n != 1 else ''}")
        self._open_btn.setEnabled(False)
        self._copy_out_btn.setEnabled(False)
        self._del_btn.setEnabled(False)

    def _on_select(self, current, _prev):
        enabled = current is not None
        self._open_btn.setEnabled(enabled)
        self._copy_out_btn.setEnabled(enabled)
        self._del_btn.setEnabled(enabled)

    def _upload(self):
        m = self._materia_getter()
        if m is None:
            QMessageBox.information(
                self, "Materia",
                "Elige primero una materia en la barra lateral.",
            )
            return
        dir_plantillas_materia(m)
        paths, _ = _pick_open_file_names(
            self, "Seleccionar plantilla", str(DIRS["plantillas"] / m),
            "Todos los archivos (*)"
        )
        if not paths:
            return
        default_sub = "documentos" if m == MATERIA_OTROS else "prisiones_preventivas"
        tipo, ok = QInputDialog.getText(
            self, "Tipo de plantilla",
            "¿En qué subcarpeta guardarla? (dentro de la materia actual)\n\n"
            "Ejemplos:  documentos  ·  estilo  ·  sentencias  ·  comparecencias\n"
            "Dejar vacío = guardar en la raíz de esta materia (01_raw/plantillas/<materia>/).",
            text=default_sub,
        )
        if not ok:
            return
        tipo = tipo.strip()
        added = 0
        for p_str in paths:
            try:
                add_plantilla(Path(p_str), tipo, materia=m)
                added += 1
            except Exception as e:
                QMessageBox.warning(self, "Error", f"No se pudo agregar {Path(p_str).name}:\n{e}")
        if added:
            self._load()

    def _open_file(self, item: QListWidgetItem | None = None):
        it = item if item is not None else self._list.currentItem()
        if not it:
            return
        path: Path = it.data(Qt.ItemDataRole.UserRole)
        if path.suffix.lower() == ".md":
            _show_markdown_viewer(self, path)
        else:
            _open_with_system_default(self, path)

    def _save_copy_elsewhere(self):
        item = self._list.currentItem()
        if not item:
            return
        path: Path = item.data(Qt.ItemDataRole.UserRole)
        if not path.is_file():
            QMessageBox.warning(self, "No encontrado", f"El archivo no existe:\n{path}")
            return
        suggested = Path.home() / "Downloads" / path.name
        dest, _ = _pick_save_file_name(
            self,
            "Guardar copia del archivo",
            str(suggested),
            "Todos los archivos (*)",
        )
        if not dest:
            return
        dest_p = Path(dest)
        try:
            shutil.copy2(path, dest_p)
        except OSError as e:
            QMessageBox.warning(self, "No se pudo guardar", str(e))
            return
        QMessageBox.information(
            self,
            "Copia guardada",
            f"Se guardó una copia en:\n{dest_p}",
        )

    def _delete_file(self):
        item = self._list.currentItem()
        if not item:
            return
        path: Path = item.data(Qt.ItemDataRole.UserRole)
        reply = QMessageBox.question(
            self, "Eliminar plantilla",
            f"¿Eliminar permanentemente?\n\n{path.name}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if reply == QMessageBox.StandardButton.Yes:
            try:
                path.unlink()
                self._load()
            except Exception as e:
                QMessageBox.warning(self, "Error", f"No se pudo eliminar:\n{e}")


# ─── AgregarFuentes Page ─────────────────────────────────────────────────────

class AgregarFuentesPage(QScrollArea):
    """Add files to an existing case folder without creating a new case."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._case_folder: Path | None = None

        container = QWidget()
        self._layout = QVBoxLayout(container)
        self._layout.setContentsMargins(24, 20, 24, 24)
        self._layout.setSpacing(14)
        self.setWidget(container)
        self._build()

    def _build(self):
        lo = self._layout

        # ── Header ──────────────────────────────────────────────────────────
        h = QLabel("AGREGAR FUENTES A CASO EXISTENTE")
        h.setStyleSheet(
            f"color: {GOLD}; font-size: 18px; font-weight: 700; letter-spacing: 2px;"
        )
        lo.addWidget(h)
        sub = QLabel("Sin crear un caso nuevo — elige el caso y agrega fuentes, plantillas o cualquier documento")
        sub.setStyleSheet(f"color: {MUTED}; font-size: 12px;")
        sub.setWordWrap(True)
        lo.addWidget(sub)

        # ── Case selector ────────────────────────────────────────────────────
        sel_card = _card(lo, "SELECCIONAR CASO ACTIVO")
        sel_lbl = QLabel("¿A qué caso quieres agregar archivos?")
        sel_lbl.setStyleSheet(f"color: {TEXT}; font-size: 13px;")
        sel_card.layout().addWidget(sel_lbl)
        sel_row = QHBoxLayout()
        self._case_combo = QComboBox()
        _stabilize_combo_popup(self._case_combo)
        self._case_combo.setMinimumWidth(360)
        self._case_combo.setFixedHeight(40)
        self._case_combo.setStyleSheet(f"""
            QComboBox {{
                background-color: {BG_INPUT};
                color: {GOLD};
                border: 2px solid {GOLD};
                border-radius: 6px;
                padding: 7px 12px;
                font-size: 14px;
                font-weight: 600;
            }}
            QComboBox::drop-down {{ border: none; width: 24px; }}
            QComboBox QAbstractItemView {{
                background-color: {BG_CARD};
                color: {TEXT};
                border: 1px solid {BORDER};
                selection-background-color: {GOLD};
                selection-color: {BG};
            }}
        """)
        self._case_combo.currentIndexChanged.connect(self._on_case_changed)
        refresh_btn = QPushButton("↺")
        refresh_btn.setFixedSize(34, 34)
        refresh_btn.setToolTip("Recargar lista de casos")
        refresh_btn.clicked.connect(self._reload_cases)
        sel_row.addWidget(self._case_combo, 1)
        sel_row.addWidget(refresh_btn)
        sel_card.layout().addLayout(sel_row)
        self._case_path_lbl = QLabel("")
        self._case_path_lbl.setStyleSheet(f"color: {MUTED}; font-size: 11px;")
        sel_card.layout().addWidget(self._case_path_lbl)
        # _reload_cases() called at end of _build, after all widgets exist

        # ── Files already in case ────────────────────────────────────────────
        contents_card = _card(lo, "ARCHIVOS ACTUALES EN EL CASO")
        contents_btn_row = QHBoxLayout()
        self._contents_remove_btn = QPushButton("✕  Eliminar archivo")
        self._contents_remove_btn.setFixedHeight(30)
        self._contents_remove_btn.setEnabled(False)
        self._contents_remove_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {BG_CARD}; color: {ERROR};
                border: 1px solid {ERROR}; border-radius: 6px; padding: 4px 12px; font-size: 12px;
            }}
            QPushButton:hover {{ background-color: {ERROR}; color: #ffffff; }}
            QPushButton:disabled {{ color: {MUTED}; border-color: {BORDER}; background: {BG_CARD}; }}
        """)
        self._contents_remove_btn.clicked.connect(self._remove_case_file)
        self._contents_count = QLabel("")
        self._contents_count.setStyleSheet(f"color: {MUTED}; font-size: 11px;")
        contents_btn_row.addWidget(self._contents_remove_btn)
        contents_btn_row.addStretch()
        contents_btn_row.addWidget(self._contents_count)
        contents_card.layout().addLayout(contents_btn_row)
        self._contents_list = QListWidget()
        self._contents_list.setMinimumHeight(100)
        self._contents_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self._contents_list.currentItemChanged.connect(
            lambda cur, _: self._contents_remove_btn.setEnabled(cur is not None)
        )
        contents_card.layout().addWidget(self._contents_list)

        # ── Add files ────────────────────────────────────────────────────────
        add_card = _card(lo, "AGREGAR ARCHIVOS")

        # Fuentes row
        fue_row = QHBoxLayout()
        fue_btn = _btn("＋  Agregar fuentes / documentos del caso")
        fue_btn.clicked.connect(self._add_fuentes)
        fue_row.addWidget(fue_btn)
        fue_note = QLabel("→ va a fuentes/")
        fue_note.setStyleSheet(f"color: {MUTED}; font-size: 11px;")
        fue_row.addStretch()
        fue_row.addWidget(fue_note)
        add_card.layout().addLayout(fue_row)

        # Raíz row
        root_row = QHBoxLayout()
        root_btn = _btn("＋  Agregar a raíz del caso")
        root_btn.clicked.connect(self._add_root)
        root_row.addWidget(root_btn)
        root_note = QLabel("→ va directo a caso_XXX/")
        root_note.setStyleSheet(f"color: {MUTED}; font-size: 11px;")
        root_row.addStretch()
        root_row.addWidget(root_note)
        add_card.layout().addLayout(root_row)

        # Added files log
        self._added_list = QListWidget()
        self._added_list.setMinimumHeight(60)
        add_card.layout().addWidget(self._added_list)

        # ── Instrucción libre ───────────────────────────────────────────────
        inst_card = _card(lo, "INSTRUCCIÓN PARA CURSOR")
        inst_card.layout().addWidget(QLabel("Escribe exactamente qué quieres que haga Cursor con este caso:"))
        self._agre_instruccion_edit = QTextEdit()
        self._agre_instruccion_edit.setPlaceholderText(
            "Ej: emite proyecto res vista confirmando prisión preventiva y responde "
            "argumentando sólidamente los agravios expuestos en la apelación del auto de prisión"
        )
        self._agre_instruccion_edit.setFixedHeight(80)
        self._agre_instruccion_edit.setStyleSheet(_qss_text_composer_rich())
        inst_card.layout().addWidget(self._agre_instruccion_edit)

        # ── Prompt ──────────────────────────────────────────────────────────
        self._gen_btn = _btn("GENERAR PROMPT ACTUALIZADO", primary=True)
        self._gen_btn.setMinimumHeight(48)
        self._gen_btn.setEnabled(False)
        self._gen_btn.clicked.connect(self._generate_prompt)
        lo.addWidget(self._gen_btn)

        self._prompt_frame = QFrame()
        self._prompt_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {BG_CARD};
                border: 2px solid {GOLD};
                border-radius: 10px;
            }}
        """)
        pf_layout = QVBoxLayout(self._prompt_frame)
        pf_layout.setContentsMargins(18, 14, 18, 14)
        pf_layout.setSpacing(10)
        pf_title = QLabel("✓  Prompt actualizado. Cópialo en Cursor:")
        pf_title.setStyleSheet(f"color: {SUCCESS}; font-weight: 700; font-size: 13px;")
        pf_layout.addWidget(pf_title)
        self._prompt_area = QTextEdit()
        self._prompt_area.setReadOnly(True)
        self._prompt_area.setMinimumHeight(140)
        self._prompt_area.setStyleSheet(_qss_text_code_readonly())
        pf_layout.addWidget(self._prompt_area)
        copy_row = QHBoxLayout()
        copy_row.addStretch()
        self._copy_btn = _btn("Copiar prompt")
        self._copy_btn.setFixedHeight(32)
        self._copy_btn.clicked.connect(self._copy_prompt)
        copy_row.addWidget(self._copy_btn)
        pf_layout.addLayout(copy_row)
        lo.addWidget(self._prompt_frame)
        self._prompt_frame.setVisible(False)
        lo.addStretch()
        # Load cases now that all widgets exist
        self._reload_cases()

    def refresh(self, select_folder: Path | None = None):
        self._reload_cases(select_folder=select_folder)

    def _reload_cases(self, select_folder: Path | None = None):
        self._case_combo.blockSignals(True)
        self._case_combo.clear()
        self._case_combo.addItem("— Selecciona un caso —", None)
        target_idx = 1
        for i, folder in enumerate(list_case_folders(), start=1):
            self._case_combo.addItem(folder.name, folder)
            if select_folder and folder == select_folder:
                target_idx = i
        if self._case_combo.count() > 1:
            self._case_combo.setCurrentIndex(target_idx)
        self._case_combo.blockSignals(False)
        idx = self._case_combo.currentIndex()
        self._on_case_changed(idx)

    def _on_case_changed(self, _idx: int):
        folder = self._case_combo.currentData()
        self._case_folder = folder
        self._gen_btn.setEnabled(folder is not None)
        self._prompt_frame.setVisible(False)
        self._added_list.clear()
        if folder:
            self._case_path_lbl.setText(f"📁  01_raw/{folder.name}/")
            self._refresh_contents()
        else:
            self._case_path_lbl.setText("")
            self._contents_list.clear()
            self._contents_count.setText("")

    def _refresh_contents(self):
        self._contents_list.clear()
        if not self._case_folder:
            return
        files = list_case_files(self._case_folder)
        for f in files:
            rel = f.relative_to(self._case_folder)
            item = QListWidgetItem(f"📄  {rel}")
            item.setData(Qt.ItemDataRole.UserRole, f)
            self._contents_list.addItem(item)
        n = len(files)
        self._contents_count.setText(f"{n} archivo{'s' if n != 1 else ''} en la carpeta")
        self._contents_remove_btn.setEnabled(False)

    def _remove_case_file(self):
        item = self._contents_list.currentItem()
        if not item:
            return
        path: Path = item.data(Qt.ItemDataRole.UserRole)
        reply = QMessageBox.question(
            self, "Eliminar archivo",
            f"¿Eliminar permanentemente?\n\n{path.name}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if reply == QMessageBox.StandardButton.Yes:
            try:
                path.unlink()
                self._refresh_contents()
            except Exception as e:
                QMessageBox.warning(self, "Error", f"No se pudo eliminar:\n{e}")

    def _add_files(self, subfolder: str | None):
        if not self._case_folder:
            QMessageBox.warning(self, "Sin caso", "Selecciona un caso primero.")
            return
        paths, _ = _pick_open_file_names(
            self, "Seleccionar archivos",
            str(self._case_folder),
            "Todos los archivos (*)"
        )
        for p in paths:
            src = Path(p)
            try:
                dest = add_to_case(src, self._case_folder, subfolder)
                label = f"fuentes/{src.name}" if subfolder else src.name
                self._added_list.addItem(QListWidgetItem(f"✓  {label}"))
            except Exception as e:
                QMessageBox.warning(self, "Error", f"No se pudo copiar {src.name}:\n{e}")
        if paths:
            self._refresh_contents()

    def _add_fuentes(self):
        self._add_files("fuentes")

    def _add_root(self):
        self._add_files(None)

    def _generate_prompt(self):
        if not self._case_folder:
            return
        folder_name = self._case_folder.name
        instruccion = self._agre_instruccion_edit.toPlainText().strip()
        instruccion_line = (
            f"\n\n## Instrucción específica del magistrado\n{instruccion}"
            if instruccion else ""
        )
        prompt = (
            f"# Continuar caso: {folder_name}\n\n"
            f"## Fuentes\n"
            f"1. Lee todos los archivos en `01_raw/{folder_name}/` (incluidos los recién agregados)\n"
            f"2. Lee los PDF y Word en `01_raw/bibliografia/{DEFAULT_MATERIA}/` "
            f"(ajusta la subcarpeta si trabajas otra materia)\n"
            f"3. Lee la plantilla en `01_raw/plantillas/{DEFAULT_MATERIA}/` que corresponda\n"
            f"   — sigue EXACTAMENTE su estructura, secciones y formato\n\n"
            f"## Checklist obligatorio — NO omitas ningún punto\n"
            f"- [ ] Fecha completa en el encabezado\n"
            f"- [ ] Tabla de datos: expediente, imputados, delito, agraviado, procedencia\n"
            f"- [ ] Todos los agravios de la defensa respondidos individualmente\n"
            f"- [ ] Primer presupuesto: cada elemento de convicción con folio y aporte probatorio\n"
            f"- [ ] Peligro de fuga (art. 269 CPP) Y obstaculización (art. 270 CPP) — por separado\n"
            f"- [ ] Plazo justificado cronológicamente (etapas + diligencias pendientes)\n"
            f"- [ ] Test de proporcionalidad completo (idoneidad, necesidad, proporcionalidad estricta)\n"
            f"- [ ] Firma S.S. con nombres de los tres magistrados\n\n"
            f"## Salida\n"
            f"- Guarda la resolución en `03_outputs/resoluciones/{DEFAULT_MATERIA}/` como archivo NUEVO "
            f"(nunca sobreescribas — usa sufijo _v1, _v2…)\n"
            f"- Actualiza `02_wiki/casos/` e `INDEX.md`"
            f"{instruccion_line}"
        )
        self._prompt_area.setPlainText(prompt)
        self._prompt_frame.setVisible(True)

    def _copy_prompt(self):
        QApplication.clipboard().setText(self._prompt_area.toPlainText())
        original = self._copy_btn.text()
        self._copy_btn.setText("✓ Copiado")
        QTimer.singleShot(2000, lambda: self._copy_btn.setText(original))


# ─── Navigation sidebar ─────────────────────────────────────────────────────

class _SidebarLogo(QWidget):
    """Cabecera lateral clicable: vuelve al inicio de la app (Casos / bienvenida)."""

    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 12, 20, 12)
        lay.setSpacing(2)
        t = QLabel("⚖  ADIUTOR IUDICIS")
        t.setStyleSheet(
            f"color: {GOLD}; font-size: 21px; font-weight: 700; letter-spacing: 1px;"
        )
        s = QLabel("Gestor de archivos")
        s.setStyleSheet(f"color: {MUTED}; font-size: 14px;")
        lay.addWidget(t)
        lay.addWidget(s)
        # Los QLabel capturaban el clic y el padre no recibía mouseReleaseEvent → _go_home no corría
        t.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        s.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(
            "Inicio: pestaña Casos y bienvenida. Si venías de un expediente del historial, se cierra; "
            "si estabas creando un caso nuevo, el borrador se conserva al volver a «Crear expediente»."
        )
        self.setStyleSheet(
            f"background-color: {BG_CARD}; border-bottom: 1px solid {BORDER};"
        )
        self.setFixedHeight(72)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)


class NavButton(QPushButton):
    def __init__(self, icon: str, label: str, parent=None):
        super().__init__(parent)
        self.setText(f"  {icon}  {label}")
        self.setCheckable(True)
        self.setFixedHeight(52)
        self._apply_style(False)

    def _apply_style(self, active: bool):
        if active:
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: {BG_INPUT};
                    color: {GOLD};
                    border: none;
                    border-left: 3px solid {GOLD};
                    border-radius: 0px;
                    font-size: 13px;
                    font-weight: 700;
                    text-align: left;
                    padding-left: 16px;
                }}
            """)
        else:
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: transparent;
                    color: {MUTED};
                    border: none;
                    border-left: 3px solid transparent;
                    border-radius: 0px;
                    font-size: 13px;
                    font-weight: 400;
                    text-align: left;
                    padding-left: 16px;
                }}
                QPushButton:hover {{ color: {TEXT}; background-color: {BG_CARD}; }}
            """)

    def setActive(self, active: bool):
        self._apply_style(active)


# ─── Wiki chat HTML (burbujas + formato legible) ────────────────────────────

def _wiki_inline_bold_escape(fragment: str) -> str:
    """Escapa HTML y convierte **negrita** en <b>."""
    parts = re.split(r"(\*\*.+?\*\*)", fragment)
    out: list[str] = []
    for p in parts:
        if len(p) >= 4 and p.startswith("**") and p.endswith("**"):
            out.append("<b>" + html.escape(p[2:-2]) + "</b>")
        else:
            out.append(html.escape(p))
    return "".join(out)


def _wiki_format_assistant_reply_html(text: str) -> str:
    """Párrafos, listas con guion, encabezados ## y negritas en respuestas del modelo."""
    raw = (text or "").strip()
    if not raw:
        return f"<p style='color:{MUTED};font-style:italic;margin:8px 0;'>Sin contenido.</p>"

    chunks: list[str] = []
    for block in re.split(r"\n\s*\n", raw):
        block = block.strip()
        if not block:
            continue
        if block.startswith("##"):
            lines_h = block.split("\n")
            title = html.escape(re.sub(r"^#+\s*", "", lines_h[0]).strip())
            chunks.append(
                f"<div style='font-weight:700;color:{GOLD};margin:16px 0 8px 0;"
                f"font-size:14px;border-bottom:1px solid {BORDER};padding-bottom:4px;'>"
                f"{title}</div>"
            )
            if len(lines_h) > 1:
                rest_h = "\n".join(lines_h[1:]).strip()
                if rest_h:
                    body_h = _wiki_inline_bold_escape(rest_h).replace("\n", "<br/>")
                    chunks.append(
                        f"<p style='margin:8px 0 12px 0;line-height:1.6;'>{body_h}</p>"
                    )
            continue

        lines = block.split("\n")
        non_empty = [ln for ln in lines if ln.strip()]
        is_bullets = non_empty and all(re.match(r"^\s*[-*]\s+", ln) for ln in non_empty)
        if is_bullets:
            lis: list[str] = []
            for ln in non_empty:
                content = re.sub(r"^\s*[-*]\s+", "", ln).strip()
                inner = _wiki_inline_bold_escape(content).replace("\n", "<br/>")
                lis.append(f"<li style='margin:5px 0;line-height:1.5;'>{inner}</li>")
            chunks.append(
                f"<ul style='margin:8px 0 8px 4px;padding-left:20px;'>{''.join(lis)}</ul>"
            )
            continue

        is_numbered = non_empty and all(
            re.match(r"^\s*\d+[\.)]\s+", ln) for ln in non_empty
        )
        if is_numbered:
            lis = []
            for ln in non_empty:
                content = re.sub(r"^\s*\d+[\.)]\s+", "", ln).strip()
                inner = _wiki_inline_bold_escape(content).replace("\n", "<br/>")
                lis.append(f"<li style='margin:5px 0;line-height:1.5;'>{inner}</li>")
            chunks.append(
                f"<ol style='margin:8px 0 8px 4px;padding-left:22px;'>{''.join(lis)}</ol>"
            )
            continue

        body = _wiki_inline_bold_escape(block).replace("\n", "<br/>")
        chunks.append(f"<p style='margin:10px 0;line-height:1.6;'>{body}</p>")

    return "".join(chunks)


def _wiki_user_bubble_html(texto: str) -> str:
    body = html.escape(texto.strip()).replace("\n", "<br/>")
    return (
        f"<div style='margin:0 0 16px 36px;padding:14px 16px;border-radius:12px;"
        f"background-color:{BG_INPUT};border:1px solid {BORDER};"
        f"border-right:3px solid {GOLD};'>"
        f"<div style='font-size:10px;color:{MUTED};margin-bottom:8px;"
        f"text-transform:uppercase;letter-spacing:1px;'>Usted</div>"
        f"<div style='color:{TEXT};font-size:13px;line-height:1.55;'>{body}</div></div>"
    )


def _wiki_assistant_bubble_html(inner: str) -> str:
    return (
        f"<div style='margin:0 36px 16px 0;padding:14px 16px;border-radius:12px;"
        f"background-color:{WIKI_ASST_BG};border:1px solid {BORDER};"
        f"border-left:3px solid {SUCCESS};'>"
        f"<div style='font-size:10px;color:{MUTED};margin-bottom:8px;"
        f"text-transform:uppercase;letter-spacing:1px;'>Asistente</div>"
        f"<div style='color:{TEXT};font-size:13px;'>{inner}</div></div>"
    )


def _wiki_error_bubble_html(message: str) -> str:
    body = html.escape(message).replace("\n", "<br/>")
    return (
        f"<div style='margin:0 0 16px 0;padding:12px 14px;border-radius:10px;"
        f"background-color:{WIKI_ERROR_BG};border:1px solid {ERROR};'>"
        f"<div style='font-size:10px;color:{ERROR};margin-bottom:6px;"
        f"text-transform:uppercase;letter-spacing:1px;'>Error</div>"
        f"<div style='color:{TEXT};font-size:12px;line-height:1.5;'>{body}</div>"
        f"<div style='color:{MUTED};font-size:11px;margin-top:10px;'>"
        f"Revise conexión, ANTHROPIC_API_KEY en .env y notas en 02_wiki/.</div></div>"
    )


# ─── Wiki Consulta Page ─────────────────────────────────────────────────────

class WikiConsultaPage(QWidget):
    """Chat de consulta al wiki (varios turnos: pregunta, respuesta, réplica)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker: WikiQueryWorker | None = None
        self._chat_history: list[tuple[str, str]] = []
        self._pending_assistant = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 24)
        layout.setSpacing(14)

        h = QLabel("CONSULTAR WIKI (CHAT)")
        h.setStyleSheet(
            f"color: {GOLD}; font-size: 18px; font-weight: 700; letter-spacing: 2px;"
        )
        layout.addWidget(h)

        sub = QLabel(
            "Conversación usando principalmente las notas en 02_wiki/ (fichas, índice, consolidados); "
            "por defecto no se procesan todos los PDF de bibliografía en este chat "
            "(variable ADIUTOR_WIKI_CHAT_INCLUDE_DOCS para activarlo). Fragmentos por consulta están limitados. "
            "Los audios solo se leen si existe un .txt junto al archivo (aquí no se usa Whisper, para no "
            "bloquear la app). Para redactar desde PDFs completos use «PREPARAR CASO» o generación con Claude. "
            "Puede responder a aclaraciones o contestar sugerencias del asistente. "
            "Use «Nueva conversación» para borrar el hilo."
        )
        sub.setWordWrap(True)
        sub.setStyleSheet(f"color: {MUTED}; font-size: 12px;")
        layout.addWidget(sub)

        chat_lbl = _section_label("CONVERSACIÓN")
        layout.addWidget(chat_lbl)

        self._output = QTextEdit()
        self._output.setReadOnly(True)
        self._output.setAcceptRichText(True)
        self._output.setPlaceholderText(
            "Aquí verá el hilo con formato claro (burbujas). Escriba abajo y pulse Enviar."
        )
        self._output.setStyleSheet(_qss_text_reader())
        layout.addWidget(self._output, 1)

        self._input = QPlainTextEdit()
        self._input.setPlaceholderText(
            "Escriba su mensaje… (Enter envía; Mayús+Enter salto de línea)"
        )
        self._input.setFixedHeight(88)
        self._input.setStyleSheet(_qss_text_composer_plain())
        layout.addWidget(self._input)

        btn_row = QHBoxLayout()
        self._ask_btn = _btn("Enviar", primary=True)
        self._ask_btn.setFixedWidth(140)
        self._ask_btn.clicked.connect(self._run_query)
        self._clear_btn = _btn("Nueva conversación")
        self._clear_btn.setFixedWidth(200)
        self._clear_btn.setToolTip("Borra el chat y el historial enviado al modelo")
        self._clear_btn.clicked.connect(self._clear)
        btn_row.addWidget(self._ask_btn)
        btn_row.addSpacing(8)
        btn_row.addWidget(self._clear_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self._status_lbl = QLabel("")
        self._status_lbl.setStyleSheet(f"color: {MUTED}; font-size: 11px;")
        layout.addWidget(self._status_lbl)

        self._input.installEventFilter(self)

    def eventFilter(self, obj, event):
        if obj is self._input and event.type() == QEvent.Type.KeyPress:
            k = event.key()
            if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
                    self._run_query()
                    return True
        return super().eventFilter(obj, event)

    def _append_user_bubble(self, texto: str):
        cur = self._output.textCursor()
        cur.movePosition(cur.MoveOperation.End)
        cur.insertHtml(_wiki_user_bubble_html(texto))
        self._output.setTextCursor(cur)
        self._output.ensureCursorVisible()

    def _run_query(self):
        pregunta = self._input.toPlainText().strip()
        if not pregunta:
            return
        if self._worker and self._worker.isRunning():
            return

        self._chat_history.append(("user", pregunta))
        self._input.clear()
        self._append_user_bubble(pregunta)

        self._pending_assistant = ""
        self._ask_btn.setEnabled(False)
        self._status_lbl.setText("Consultando el wiki…")

        self._worker = WikiQueryWorker(list(self._chat_history), parent=self)
        _qc = Qt.ConnectionType.QueuedConnection
        self._worker.progress.connect(self._status_lbl.setText, _qc)
        self._worker.chunk_ready.connect(self._on_chunk, _qc)
        self._worker.query_completed.connect(self._on_done, _qc)
        self._worker.error_occurred.connect(self._on_error, _qc)
        self._worker.start()

    def _on_chunk(self, text: str):
        self._pending_assistant = text
        inner = _wiki_format_assistant_reply_html(text)
        cur = self._output.textCursor()
        cur.movePosition(cur.MoveOperation.End)
        cur.insertHtml(_wiki_assistant_bubble_html(inner))
        self._output.setTextCursor(cur)
        self._output.ensureCursorVisible()

    def _on_done(self):
        reply = self._pending_assistant.strip()
        if reply:
            self._chat_history.append(("assistant", reply))
        self._pending_assistant = ""
        self._ask_btn.setEnabled(True)
        self._status_lbl.setText("")

    def _on_error(self, msg: str):
        if self._chat_history and self._chat_history[-1][0] == "user":
            self._chat_history.pop()
        self._ask_btn.setEnabled(True)
        self._status_lbl.setText(f"Error: {msg[:400]}")
        cur = self._output.textCursor()
        cur.movePosition(cur.MoveOperation.End)
        cur.insertHtml(
            _wiki_error_bubble_html(
                f"No se pudo obtener respuesta.\n\n{msg}"
            )
        )
        self._output.setTextCursor(cur)
        self._output.ensureCursorVisible()

    def _clear(self):
        if self._worker and self._worker.isRunning():
            return
        self._input.clear()
        self._output.clear()
        self._chat_history.clear()
        self._pending_assistant = ""
        self._status_lbl.setText("")


# ─── Main window ────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Adiutor Iudicis — Asistente de Redacción Judicial")
        self.setMinimumSize(1100, 680)
        self.resize(1300, 800)
        self.setStyleSheet(STYLE)
        self._nav_context: str | None = None
        self._nav_leaf_items: dict[tuple[int, str], QTreeWidgetItem] = {}
        self._build_ui()

    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        main_h = QHBoxLayout(root)
        main_h.setContentsMargins(0, 0, 0, 0)
        main_h.setSpacing(0)

        # ── Sidebar (mín./máx. ancho; el separador permite ampliar la columna izquierda) ──
        sidebar = QWidget()
        sidebar.setMinimumWidth(200)
        # Tope amplio: la barra de materia puede crecer mucho al arrastrar el separador.
        sidebar.setMaximumWidth(2000)
        sidebar.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding
        )
        sidebar.setStyleSheet(
            f"background-color: {BG_CARD}; border-right: 1px solid {BORDER};"
        )
        sb_vbox = QVBoxLayout(sidebar)
        sb_vbox.setContentsMargins(0, 0, 0, 0)
        sb_vbox.setSpacing(0)

        # Logo (clic → inicio de la aplicación)
        self._sidebar_logo = _SidebarLogo()
        self._sidebar_logo.clicked.connect(self._go_home)
        sb_vbox.addWidget(self._sidebar_logo)

        self._reload_app_btn = QPushButton("↻  Actualizar aplicación")
        self._reload_app_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._reload_app_btn.setToolTip(
            "Cierra y vuelve a abrir Adiutor Iudicis para cargar el código actual del disco "
            "(tras modificar la app sin cerrarla a mano)."
        )
        self._reload_app_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {MUTED};
                border: none;
                border-bottom: 1px solid {BORDER};
                padding: 8px 16px 10px 16px;
                font-size: 11px;
                font-weight: 600;
                text-align: center;
            }}
            QPushButton:hover {{ color: {GOLD}; background-color: {NAV_ROW_HOVER}; }}
        """)
        self._reload_app_btn.clicked.connect(self._confirm_restart_application)
        sb_vbox.addWidget(self._reload_app_btn)

        self._feedback_btn = QPushButton("💬  Sugerencias / Fallos")
        self._feedback_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._feedback_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {MUTED};
                border: none; border-bottom: 1px solid {BORDER};
                padding: 7px 16px; font-size: 11px; text-align: center;
            }}
            QPushButton:hover {{ color: {GOLD}; background-color: {NAV_ROW_HOVER}; }}
        """)
        self._feedback_btn.clicked.connect(self._open_feedback_dialog)
        sb_vbox.addWidget(self._feedback_btn)

        theme_lbl = QLabel("APARIENCIA")
        theme_lbl.setStyleSheet(
            f"color: {MUTED}; font-size: 9px; font-weight: 700; letter-spacing: 2px;"
            f" padding: 12px 16px 4px 16px; background: transparent;"
        )
        sb_vbox.addWidget(theme_lbl)
        self._theme_combo = QComboBox()
        _stabilize_combo_popup(self._theme_combo)
        self._theme_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        self._theme_combo.setToolTip(
            "Elige el tema visual. Se guarda en el archivo .env del repositorio y se "
            "reinicia la aplicación para aplicar colores en toda la interfaz."
        )
        for label, tid in (
            ("Suave (oscuro azulado)", "soft"),
            ("Claro", "light"),
            ("Contraste (oscuro)", "dark"),
        ):
            self._theme_combo.addItem(label, tid)
        cur_theme = get_app_theme().name
        idx = self._theme_combo.findData(cur_theme, Qt.ItemDataRole.UserRole)
        if idx >= 0:
            self._theme_combo.setCurrentIndex(idx)
        self._theme_combo.activated.connect(self._on_theme_selected)
        sb_vbox.addWidget(self._theme_combo)

        # Casos — nivel superior (siempre visible)
        self._casos_btn = NavButton("⚖", "Casos")
        self._casos_btn.clicked.connect(self._go_home)
        sb_vbox.addWidget(self._casos_btn)

        # Consultar wiki — nivel superior (siempre visible)
        self._consulta_btn = NavButton("🔍", "Consultar wiki")
        self._consulta_btn.clicked.connect(lambda: self._switch_page(4))
        sb_vbox.addWidget(self._consulta_btn)

        # Fábrica Artifex — nivel superior (siempre visible)
        self._artifex_btn = NavButton("🏭", "Fábrica")
        self._artifex_btn.clicked.connect(lambda: self._switch_page(5))
        sb_vbox.addWidget(self._artifex_btn)

        mat_lbl = QLabel("MATERIA DEL CASO")
        mat_lbl.setStyleSheet(
            f"color: {MUTED}; font-size: 9px; font-weight: 700; letter-spacing: 2px;"
            f" padding: 14px 16px 4px 16px; background: transparent;"
        )
        sb_vbox.addWidget(mat_lbl)

        self._nav_tree = QTreeWidget()
        self._nav_tree.setHeaderHidden(True)
        self._nav_tree.setIndentation(14)
        self._nav_tree.setAnimated(True)
        self._nav_tree.setRootIsDecorated(True)
        self._nav_tree.setExpandsOnDoubleClick(False)
        self._nav_tree.setStyleSheet(f"""
            QTreeWidget {{
                background-color: {BG_CARD};
                border: none;
                outline: none;
                font-size: 12px;
            }}
            QTreeWidget::item {{
                padding: 5px 4px 5px 6px;
                border-radius: 3px;
            }}
            QTreeWidget::item:selected {{
                background-color: {BG_INPUT};
                color: {GOLD};
                font-weight: 600;
            }}
            QTreeWidget::item:hover:!selected {{
                background-color: {NAV_ROW_HOVER};
            }}
        """)
        self._nav_tree.itemClicked.connect(self._on_nav_tree_item_clicked)

        # Las 14 materias se muestran como secciones colapsables en la barra lateral.
        # Orden: penal procesal primero (PP, cesación, prolongación), luego etapa
        # intermedia y juicio, luego post-sentencia, luego misceláneos.
        _sections = [
            (MATERIA_LABELS[MATERIA_PRISION_PREVENTIVA], MATERIA_PRISION_PREVENTIVA),
            (MATERIA_LABELS[MATERIA_CESACION_PP], MATERIA_CESACION_PP),
            (MATERIA_LABELS[MATERIA_PROLONGACION_PP], MATERIA_PROLONGACION_PP),
            (MATERIA_LABELS[MATERIA_MEDIDAS_COERC], MATERIA_MEDIDAS_COERC),
            (MATERIA_LABELS[MATERIA_SOBRESEIMIENTO], MATERIA_SOBRESEIMIENTO),
            (MATERIA_LABELS[MATERIA_ENJUICIAMIENTO], MATERIA_ENJUICIAMIENTO),
            (MATERIA_LABELS[MATERIA_APELACION_SENT], MATERIA_APELACION_SENT),
            (MATERIA_LABELS[MATERIA_BENEFICIOS_PENIT], MATERIA_BENEFICIOS_PENIT),
            (MATERIA_LABELS[MATERIA_TUTELA], MATERIA_TUTELA),
            (MATERIA_LABELS[MATERIA_NULIDAD], MATERIA_NULIDAD),
            (MATERIA_LABELS[MATERIA_QUEJAS_DERECHO], MATERIA_QUEJAS_DERECHO),
            (MATERIA_LABELS[MATERIA_RECURSOS_QUEJA], MATERIA_RECURSOS_QUEJA),
            (MATERIA_LABELS[MATERIA_CONSULTAS], MATERIA_CONSULTAS),
            (MATERIA_LABELS[MATERIA_OTROS], MATERIA_OTROS),
        ]
        # Orden lógico de trabajo: fuentes → modelo → resultado (resolución)
        _leaves = [
            ("📚", "Bibliografía", 3),
            ("📋", "Plantillas", 2),
            ("📄", "Resoluciones", 1),
        ]
        self._nav_leaf_items.clear()
        for title, ctx in _sections:
            parent = QTreeWidgetItem([title])
            parent.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
            )
            parent.setData(0, Qt.ItemDataRole.UserRole, ctx)
            parent.setToolTip(
                0,
                "Clic para desplegar u ocultar. El clic también fija la materia del caso "
                "(expedientes, bibliografía y plantillas por materia).",
            )
            for icon, name, page_idx in _leaves:
                ch = QTreeWidgetItem(parent, [f"{icon}  {name}"])
                ch.setData(0, Qt.ItemDataRole.UserRole, (page_idx, ctx))
                self._nav_leaf_items[(page_idx, ctx)] = ch
            self._nav_tree.addTopLevelItem(parent)
        self._nav_tree.collapseAll()
        sb_vbox.addWidget(self._nav_tree, 1)

        sb_vbox.addStretch()

        # Model badge at bottom of sidebar
        badge = QLabel(f"⚡ Claude API · {resolution_model_badge_label()}")
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet(
            f"color: {MUTED}; font-size: 10px; padding: 12px;"
            f" border-top: 1px solid {BORDER};"
        )
        badge.setWordWrap(True)
        sb_vbox.addWidget(badge)

        # ── Content stack ────────────────────────────────────────────────────
        self._stack = QStackedWidget()
        self._stack.setStyleSheet(f"background-color: {BG};")

        _mg = lambda: self._nav_context
        self._page_caso = NuevoCasoPage(
            open_case_cb=self._open_existing_case,
            materia_getter=_mg,
            materia_setter=self._set_nav_context_from_case_form,
            back_to_start_cb=self._go_home,
            welcome_only_cb=self._welcome_keep_session,
        )
        self._page_agre = AgregarFuentesPage()
        self._page_res = ResolucionesPage(materia_getter=_mg)
        self._page_pla = PlantillasPage(materia_getter=_mg)
        self._page_bib = _FileLibraryPage(
            title="BIBLIOGRAFÍA",
            materia_getter=_mg,
            file_filter=BIBLIO_QFILE_FILTER,
            format_hint=(
                "Formatos: PDF, Word, Markdown y texto (.pdf, .doc, .docx, .md, .txt). "
                "Los archivos se guardan bajo la materia activa en la barra lateral. "
                "PDF escaneado: puede poner `mismo_nombre.txt` o `.md` junto al PDF (transcripción) "
                "— WikiJuez lo fusiona automáticamente. Use «Probar lectura PDF» para comprobar antes de generar. "
                "Obsidian: sólo lo que está en estas carpetas del proyecto entra al prompt; otro vault requiere copiar aquí."
            ),
            bib_ficha_cb=lambda: self._page_caso._run_bibliografia_ficha_materia(),
        )
        self._page_consulta = WikiConsultaPage()

        self._page_artifex = ArtifexPage()

        for page in (self._page_caso, self._page_res, self._page_pla, self._page_bib, self._page_consulta, self._page_artifex):
            self._stack.addWidget(page)

        # Barra lateral + contenido: el usuario puede ampliar la columna izquierda arrastrando.
        self._main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._main_splitter.setHandleWidth(5)
        self._main_splitter.setChildrenCollapsible(False)
        self._main_splitter.setStyleSheet(f"""
            QSplitter::handle:horizontal {{
                background: {BORDER};
                width: 5px;
                margin: 0 1px;
            }}
            QSplitter::handle:horizontal:hover {{ background: {GOLD}; }}
        """)
        self._main_splitter.addWidget(sidebar)
        self._main_splitter.addWidget(self._stack)
        self._main_splitter.setStretchFactor(0, 0)
        self._main_splitter.setStretchFactor(1, 1)
        w = max(self.width(), 1100)
        self._main_splitter.setSizes([260, w - 260])

        main_h.addWidget(self._main_splitter, 1)
        self._switch_page(0)

    def _open_existing_case(self, folder: Path):
        self._page_caso._load_existing_case(folder)
        self._switch_page(0)

    def _go_home(self):
        """Pestaña Casos + bienvenida.

        - Expediente abierto desde **historial** (`_existing_folder`): se cierra la sesión y se limpia
          el formulario (inicio limpio para un caso nuevo).
        - **Nuevo expediente** en curso (formulario sin carpeta de historial): se oculta el formulario
          pero se **conserva el borrador** al volver con «Crear expediente».
        """
        if self._page_caso._existing_folder is not None:
            self._page_caso._reset()
        else:
            self._page_caso._return_to_welcome_keep_draft()
        self._switch_page(0)

    def _welcome_keep_session(self):
        """Bienvenida sin cerrar sesión del historial ni borrar borrador (solo oculta el formulario)."""
        self._page_caso._return_to_welcome_keep_draft()
        self._switch_page(0)

    def _open_feedback_dialog(self):
        from datetime import datetime as _dt
        dlg = QDialog(self)
        dlg.setWindowTitle("Sugerencias y fallos — Adiutor Iudicis")
        dlg.resize(540, 360)
        dlg.setStyleSheet(f"background-color: {BG}; color: {TEXT};")
        dv = QVBoxLayout(dlg)
        dv.setContentsMargins(20, 20, 20, 20)
        dv.setSpacing(12)

        lbl = QLabel("Describe el fallo o sugerencia. Se guarda en el repositorio para revisión.")
        lbl.setWordWrap(True)
        lbl.setStyleSheet(f"color: {MUTED}; font-size: 12px;")
        dv.addWidget(lbl)

        edit = QTextEdit()
        edit.setPlaceholderText(
            "Ej: «Al abrir el caso 009 no aparece la resolución»\n"
            "     «Sería útil tener un campo para la fecha de los hechos»\n"
            "     «El botón Aplicar modificaciones no responde»…"
        )
        edit.setStyleSheet(_qss_text_composer_rich())
        dv.addWidget(edit, 1)

        # Mostrar feedback previo
        feedback_path = BASE_DIR / "03_outputs" / "sugerencias.md"
        if feedback_path.exists():
            prev_lbl = QLabel(f"Registro guardado en: {feedback_path.relative_to(BASE_DIR)}")
            prev_lbl.setStyleSheet(f"color: {MUTED}; font-size: 10px;")
            dv.addWidget(prev_lbl)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        btns.button(QDialogButtonBox.StandardButton.Save).setText("Guardar sugerencia")
        btns.button(QDialogButtonBox.StandardButton.Cancel).setText("Cerrar")
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        dv.addWidget(btns)

        if dlg.exec() == QDialog.DialogCode.Accepted:
            texto = edit.toPlainText().strip()
            if not texto:
                return
            feedback_path.parent.mkdir(parents=True, exist_ok=True)
            ts = _dt.now().strftime("%Y-%m-%d %H:%M")
            entrada = f"\n---\n**{ts}**\n{texto}\n"
            with open(feedback_path, "a", encoding="utf-8") as f:
                f.write(entrada)
            QMessageBox.information(
                self, "Guardado",
                "Sugerencia registrada. Gracias."
            )

    def _on_theme_selected(self, index: int) -> None:
        """Guarda ADIUTOR_THEME en .env y reinicia (los colores se fijan al cargar el módulo)."""
        tid = self._theme_combo.itemData(index, Qt.ItemDataRole.UserRole)
        if tid is None or str(tid) == get_app_theme().name:
            return
        try:
            set_repo_env_var("ADIUTOR_THEME", str(tid))
        except (OSError, ValueError) as e:
            QMessageBox.critical(
                self,
                "No se pudo guardar el tema",
                f"No se pudo escribir en el archivo .env:\n\n{e}",
            )
            revert = self._theme_combo.findData(
                get_app_theme().name, Qt.ItemDataRole.UserRole
            )
            if revert >= 0:
                self._theme_combo.blockSignals(True)
                self._theme_combo.setCurrentIndex(revert)
                self._theme_combo.blockSignals(False)
            return
        os.environ["ADIUTOR_THEME"] = str(tid)
        restart_amanuensis_application(self)

    def _set_nav_context_from_case_form(self, materia: str):
        """Sincroniza la materia elegida dentro de Nuevo expediente con el resto de la app."""
        if materia not in MATERIA_SLUGS:
            return
        changed = self._nav_context != materia
        self._nav_context = materia
        if changed:
            self._page_res._load_list()
            self._page_pla._load()
            self._page_bib._load()

    def _confirm_restart_application(self):
        reply = QMessageBox.question(
            self,
            "Actualizar Adiutor Iudicis",
            "Se cerrará la aplicación y se abrirá de nuevo para cargar los cambios guardados "
            "en el código (mismo intérprete y carpeta de trabajo).\n\n¿Continuar?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        restart_amanuensis_application(self)

    def _on_nav_tree_item_clicked(self, item: QTreeWidgetItem, column: int):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if item.childCount() > 0:
            if isinstance(data, str) and data in MATERIA_SLUGS:
                # Otra materia = otro contexto: no arrastrar ranuras ni borrador del caso anterior
                changed = self._nav_context != data
                self._nav_context = data
                if changed:
                    self._page_caso.reset_draft_for_materia_change()
                self._page_caso._return_to_welcome_keep_draft()
            item.setExpanded(not item.isExpanded())
            return
        if not isinstance(data, tuple) or len(data) != 2:
            return
        idx, ctx = data
        self._switch_page(int(idx), str(ctx))

    def _switch_page(self, index: int, context: str | None = None):
        if index in (1, 2, 3) and context is not None:
            materia_changed = self._nav_context != context
            self._nav_context = context
            # Al cambiar de materia, la vista de Casos vuelve al inicio y se limpia el borrador del caso
            if materia_changed:
                self._page_caso.reset_draft_for_materia_change()
                self._page_caso._return_to_welcome_keep_draft()
        # Pestaña Casos: no borrar la materia (sigue valiendo para nuevos expedientes)
        self._stack.setCurrentIndex(index)
        if index == 0:
            self._page_caso._sync_form_materia_combo()
        self._casos_btn.setActive(index == 0)
        self._consulta_btn.setActive(index == 4)
        self._nav_tree.blockSignals(True)
        try:
            if index in (0, 4):
                self._nav_tree.clearSelection()
            else:
                key = (index, context)
                leaf = self._nav_leaf_items.get(key)
                if leaf is not None:
                    self._nav_tree.setCurrentItem(leaf)
        finally:
            self._nav_tree.blockSignals(False)
        if index == 0:
            self._page_caso.refresh_materia_dependent_ui()
        elif index == 1:
            self._page_res._load_list()
        elif index == 2:
            self._page_pla._load()
        elif index == 3:
            self._page_bib._load()
