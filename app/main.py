"""
Adiutor Iudicis — entry point.
Run from the project root:
    python app/main.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.env_load import load_repo_dotenv
from app.core.pdf_extract import bootstrap_tesseract

# ANTHROPIC_API_KEY y otras variables desde .env en la raíz del repo
load_repo_dotenv()
# Finder/Dock en macOS no incluye Homebrew en PATH; Tesseract debe resolverse antes del OCR.
bootstrap_tesseract()

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QApplication, QStyleFactory

from app.core.file_manager import (
    dir_instrucciones_generales,
    migrate_legacy_caso_folders_to_materia,
    migrate_legacy_materia_folders,
    migrate_stray_root_caso_folders,
)
from app.ui.main_window import MainWindow


def main():
    migrate_legacy_materia_folders()
    migrate_legacy_caso_folders_to_materia()
    migrate_stray_root_caso_folders()
    dir_instrucciones_generales()
    app = QApplication(sys.argv)
    if sys.platform == "darwin":
        _fusion = QStyleFactory.create("Fusion")
        if _fusion is not None:
            app.setStyle(_fusion)
    app.setApplicationName("Adiutor Iudicis")
    app.setApplicationDisplayName("Adiutor Iudicis")
    app.setOrganizationName("Poder Judicial del Perú")
    # Fuentes del sistema (evita fijar nombres que disparen búsquedas costosas en consola, p. ej. "Segoe UI" en QSS)
    _base = QFont()
    _base.setPointSize(13)
    app.setFont(_base)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
