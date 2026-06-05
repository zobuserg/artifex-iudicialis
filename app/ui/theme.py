# -*- coding: utf-8 -*-
"""
Temas visuales de Adiutor Iudicis (Wiki Juez).

Variable de entorno: ADIUTOR_THEME
  - soft   (predeterminado): interfaz moderna oscura (slate, oro, tipografia de sistema)
  - light  : interfaz clara, buena para uso prolongado de día
  - dark   : esquema original (alto contraste)

Cargar .env antes de importar main_window (app/main.py ya llama load_repo_dotenv).
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class AppTheme:
    name: str
    bg: str
    bg_card: str
    bg_input: str
    gold: str
    gold_h: str
    text: str
    muted: str
    border: str
    success: str
    error: str
    reader_canvas: str
    claude_accent: str
    """Texto sobre botones/ítem seleccionado dorado (evita gris claro ilegible en tema light)."""
    text_on_gold: str
    code_panel_bg: str
    code_md_bg: str
    code_inline_color: str
    wiki_asst_bg: str
    wiki_error_bg: str
    gen_claude_bg: str
    gen_claude_fg: str
    gen_claude_border: str
    gen_claude_hover_bg: str
    gen_claude_hover_fg: str
    gen_label_color: str
    nav_row_hover: str


def _resolve_theme_name() -> str:
    try:
        from app.core.env_load import load_repo_dotenv

        load_repo_dotenv()
    except Exception:
        pass
    v = (os.environ.get("ADIUTOR_THEME") or "soft").strip().lower()
    if v in ("soft", "calm", "modern", "default"):
        return "soft"
    if v in ("light", "claro", "day", "dia", "día", "blanco"):
        return "light"
    if v in ("dark", "oscuro", "classic", "night", "negro"):
        return "dark"
    return "soft"


def _themes() -> dict[str, AppTheme]:
    return {
        "dark": AppTheme(
            name="dark",
            bg="#0f1117",
            bg_card="#161b25",
            bg_input="#1e2330",
            gold="#c9a84c",
            gold_h="#d4b05a",
            text="#e8e8e8",
            muted="#8892a4",
            border="#2a2f3e",
            success="#4caf7d",
            error="#e05555",
            reader_canvas="#0d1017",
            claude_accent="#7aa2f7",
            text_on_gold="#0f1117",
            code_panel_bg="#0a0e14",
            code_md_bg="#141a22",
            code_inline_color="#c8d0da",
            wiki_asst_bg="#1a2030",
            wiki_error_bg="#251a1c",
            gen_claude_bg="#1a2a4a",
            gen_claude_fg="#7aa2f7",
            gen_claude_border="#7aa2f7",
            gen_claude_hover_bg="#7aa2f7",
            gen_claude_hover_fg="#0f1117",
            gen_label_color="#7aa2f7",
            nav_row_hover="rgba(255,255,255,0.06)",
        ),
        "soft": AppTheme(
            name="soft",
            bg="#0c1018",
            bg_card="#141c2a",
            bg_input="#1c2638",
            gold="#d4a84b",
            gold_h="#e0b860",
            text="#eef1f7",
            muted="#8b95a8",
            border="#2f3d52",
            success="#3dcc8c",
            error="#e85d5d",
            reader_canvas="#0a0e16",
            claude_accent="#6ea8ff",
            text_on_gold="#0d0f14",
            code_panel_bg="#0a101c",
            code_md_bg="#151d2e",
            code_inline_color="#c5ceda",
            wiki_asst_bg="#1a2434",
            wiki_error_bg="#2a1820",
            gen_claude_bg="#1a2d4d",
            gen_claude_fg="#8ab4ff",
            gen_claude_border="#5c8fd4",
            gen_claude_hover_bg="#5c8fd4",
            gen_claude_hover_fg="#0d0f14",
            gen_label_color="#8ab4ff",
            nav_row_hover="rgba(255,255,255,0.055)",
        ),
        "light": AppTheme(
            name="light",
            bg="#eef1f5",
            bg_card="#ffffff",
            bg_input="#ffffff",
            gold="#7a5f1a",
            gold_h="#8f7020",
            text="#1e2430",
            muted="#5c6474",
            border="#c9d0dc",
            success="#1d7a4a",
            error="#b83232",
            reader_canvas="#f6f7fa",
            claude_accent="#2563c7",
            text_on_gold="#141820",
            code_panel_bg="#e8ebf0",
            code_md_bg="#eceff3",
            code_inline_color="#3a4455",
            wiki_asst_bg="#e4eaf5",
            wiki_error_bg="#f5e4e4",
            gen_claude_bg="#e8eef8",
            gen_claude_fg="#1e3a5f",
            gen_claude_border="#2563c7",
            gen_claude_hover_bg="#2563c7",
            gen_claude_hover_fg="#ffffff",
            gen_label_color="#1e4a7a",
            nav_row_hover="rgba(0,0,0,0.06)",
        ),
    }


def get_app_theme() -> AppTheme:
    n = _resolve_theme_name()
    return _themes().get(n) or _themes()["soft"]


def build_global_stylesheet(t: AppTheme) -> str:
    """QSS global de la ventana (botones, listas, campos, selección)."""
    return f"""
QMainWindow, QWidget {{
    background-color: {t.bg};
    color: {t.text};
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Helvetica, "PingFang SC", "Hiragino Sans", "Arial Unicode MS", sans-serif;
    font-size: 13px;
}}
QToolTip {{
    background-color: {t.bg_card};
    color: {t.text};
    border: 1px solid {t.border};
    border-radius: 8px;
    padding: 8px 10px;
}}
QScrollArea {{ border: none; background: {t.bg}; }}
QScrollBar:vertical {{
    background: {t.bg_card}; width: 9px; border-radius: 4px; margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {t.border}; border-radius: 4px; min-height: 28px;
}}
QScrollBar::handle:vertical:hover {{ background: {t.gold}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}

QPushButton {{
    background-color: {t.bg_card};
    color: {t.gold};
    border: 1px solid {t.gold};
    border-radius: 10px;
    padding: 9px 18px;
    font-weight: 600;
}}
QPushButton:hover  {{ background-color: {t.gold}; color: {t.text_on_gold}; }}
QPushButton:pressed {{ background-color: {t.gold_h}; color: {t.text_on_gold}; }}
QPushButton:disabled {{ background: {t.bg_card}; color: {t.muted}; border-color: {t.border}; }}

QLineEdit {{
    background-color: {t.bg_input};
    color: {t.text};
    border: 1px solid {t.border};
    border-radius: 10px;
    padding: 10px 14px;
    font-size: 13px;
}}
QLineEdit:focus {{ border-color: {t.gold}; }}
QLineEdit:read-only {{ color: {t.muted}; }}

QComboBox {{
    background-color: {t.bg_input};
    color: {t.text};
    border: 1px solid {t.border};
    border-radius: 10px;
    padding: 8px 14px;
    min-height: 22px;
    font-size: 13px;
}}
QComboBox:focus {{ border-color: {t.gold}; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox::down-arrow {{
    width: 10px; height: 10px;
    border-left: 2px solid {t.muted};
    border-bottom: 2px solid {t.muted};
    margin-right: 6px;
}}
QComboBox QAbstractItemView {{
    background-color: {t.bg_card};
    color: {t.text};
    border: 1px solid {t.border};
    selection-background-color: {t.gold};
    selection-color: {t.text_on_gold};
    outline: none;
}}

QTextEdit {{
    background-color: {t.bg_input};
    color: {t.text};
    border: 1px solid {t.border};
    border-radius: 10px;
    padding: 12px 14px;
    font-size: 13px;
    line-height: 1.5;
    selection-background-color: {t.gold};
    selection-color: {t.text_on_gold};
}}
QTextEdit:focus {{ border-color: {t.gold}; }}

QPlainTextEdit {{
    background-color: {t.bg_input};
    color: {t.text};
    border: 1px solid {t.border};
    border-radius: 10px;
    padding: 12px 14px;
    font-size: 13px;
    line-height: 1.5;
    selection-background-color: {t.gold};
    selection-color: {t.text_on_gold};
}}
QPlainTextEdit:focus {{ border-color: {t.gold}; }}

QListWidget {{
    background-color: {t.bg_input};
    color: {t.text};
    border: 1px solid {t.border};
    border-radius: 10px;
    padding: 6px;
    outline: none;
    font-size: 13px;
}}
QListWidget::item {{ padding: 9px 12px; border-radius: 7px; }}
QListWidget::item:selected {{ background-color: {t.gold}; color: {t.text_on_gold}; font-weight: 600; }}
QListWidget::item:hover:!selected {{ background-color: {t.bg_card}; }}

QTreeWidget {{
    background-color: {t.bg};
    color: {t.text};
    border: none;
    outline: none;
    font-size: 12px;
}}
QTreeWidget::item {{ padding: 4px 2px; min-height: 20px; }}
QTreeWidget::item:selected {{ background: {t.bg_input}; color: {t.gold}; }}
QTreeWidget::item:hover {{ background: {t.bg_card}; }}

QSplitter::handle {{ background-color: {t.border}; }}
QSplitter::handle:horizontal {{ width: 2px; }}
QSplitter::handle:vertical   {{ height: 2px; }}
"""
