# -*- coding: utf-8 -*-
"""Dialog for quick jurisprudence Markdown note saved under 01_raw/bibliografia/<materia>/."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QMessageBox,
    QTextEdit,
    QVBoxLayout,
)


def open_edit_bibliografia_note(parent, path: Path) -> bool:
    """
    Intenta editar ``path``. Devuelve True si el usuario guardo y cerro con Accept.
    """
    path = Path(path)
    try:
        initial = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        QMessageBox.warning(
            parent,
            "Error",
            f"No se pudo leer para edici\u00f3n:\n{e}",
        )
        return False
    dlg = EditBibliografiaNoteDialog(parent, path=path, initial_text=initial)
    return dlg.exec() == QDialog.DialogCode.Accepted

from app.core.claude_worker import JURIS_QUICK_NOTE_TEMPLATE_MD
from app.core.file_manager import dir_bibliografia_materia


def _safe_note_stem(stem: str) -> str:
    s = "".join(c if c.isalnum() or c in "._-" else "_" for c in (stem or "").strip())
    return s.strip("._") or ""


class JurisQuickNoteDialog(QDialog):
    """Edit template and save as .md under materia bibliography."""

    def __init__(self, parent, *, materia_slug: str):
        super().__init__(parent)
        self._materia_slug = materia_slug
        self._saved_path: Path | None = None
        self.setWindowTitle("Nota r\u00e1pida de jurisprudencia")
        self.setMinimumWidth(560)
        self.setMinimumHeight(420)

        lo = QVBoxLayout(self)

        hi = QLabel(
            "Complete la plantilla y guarde. El archivo se crear\u00e1 en la carpeta "
            "01_raw/bibliografia/<materia>/ seg\u00fan la materia activa en la barra lateral. "
            "Luego genere el prompt de nuevo o, al iterar, active la reinyecci\u00f3n si la necesita."
        )
        hi.setWordWrap(True)
        lo.addWidget(hi)

        lbl_fn = QLabel("Nombre del archivo (sin .md)")
        lo.addWidget(lbl_fn)

        dt = datetime.now().strftime("%Y-%m-%d")
        default_stem = f"nota_juris_{dt}"
        self._name_edit = QLineEdit(default_stem)
        self._name_edit.setPlaceholderText("Ej.: Cas_1421-2023_resumen_web")
        lo.addWidget(self._name_edit)

        self._body_edit = QTextEdit()
        self._body_edit.setPlainText(JURIS_QUICK_NOTE_TEMPLATE_MD)
        self._body_edit.setMinimumHeight(260)
        lo.addWidget(self._body_edit, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        save_btn = buttons.button(QDialogButtonBox.StandardButton.Save)
        if save_btn:
            save_btn.setText("Guardar en bibliograf\u00eda")
        lo.addWidget(buttons)

    def saved_path(self) -> Path | None:
        return self._saved_path

    def _on_save(self):
        stem_in = self._name_edit.text().strip()
        stem = _safe_note_stem(stem_in) or _safe_note_stem(
            f"nota_juris_{datetime.now().strftime('%Y%m%d_%H%M')}"
        )
        dest_dir = dir_bibliografia_materia(self._materia_slug)
        dest_dir.mkdir(parents=True, exist_ok=True)
        out = dest_dir / f"{stem}.md"
        if out.exists():
            r = QMessageBox.question(
                self,
                "Sobrescribir",
                f"Ya existe \u00ab{out.name}\u00bb. \u00bfSobrescribir?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if r != QMessageBox.StandardButton.Yes:
                return
        body = self._body_edit.toPlainText()
        try:
            out.write_text(body if body.endswith("\n") else body + "\n", encoding="utf-8")
        except OSError as e:
            QMessageBox.warning(self, "Error", f"No se pudo guardar:\n{e}")
            return
        self._saved_path = out
        self.accept()


class EditBibliografiaNoteDialog(QDialog):
    """Editor de texto plano para una nota .md o .txt ya guardada en bibliografia."""

    def __init__(self, parent, *, path: Path, initial_text: str):
        super().__init__(parent)
        self._path = path.resolve()
        self._initial = initial_text
        self.setMinimumWidth(600)
        self.setMinimumHeight(480)
        self.setWindowTitle(f"Editar \u2014 {path.name}")

        lo = QVBoxLayout(self)

        info = QLabel(f"{path.name}\n{self._path}")
        info.setWordWrap(True)
        info.setStyleSheet("color: #888; font-size: 11px;")
        lo.addWidget(info)

        self._edit = QTextEdit()
        self._edit.setPlainText(initial_text)
        self._edit.setPlaceholderText(
            "Texto Markdown o plano (UTF-8)."
        )
        lo.addWidget(self._edit, 1)

        box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        sv = box.button(QDialogButtonBox.StandardButton.Save)
        if sv:
            sv.setText("Guardar")
        box.accepted.connect(self._save)
        box.rejected.connect(self._on_cancel_requested)
        lo.addWidget(box)

    def _on_cancel_requested(self):
        cur = self._edit.toPlainText()
        if cur != self._initial:
            r = QMessageBox.question(
                self,
                "Descartar cambios",
                "\u00bfDescartar los cambios no guardados?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if r != QMessageBox.StandardButton.Yes:
                return
        self.reject()

    def _save(self):
        body = self._edit.toPlainText()
        try:
            self._path.write_text(body if body.endswith("\n") else body + "\n", encoding="utf-8")
        except OSError as e:
            QMessageBox.warning(self, "Error", f"No se pudo guardar:\n{e}")
            return
        self._initial = body
        self.accept()
