"""
Artifex Iudicialis — entry point.
Run from the project root:
    python -m app
    python app/main.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.env_load import load_repo_dotenv
from app.core.pdf_extract import bootstrap_tesseract

load_repo_dotenv()
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

    app.setApplicationName("Adiutor Iudicis.2")
    app.setApplicationDisplayName("Adiutor Iudicis.2")
    app.setOrganizationName("Poder Judicial del Perú")

    _base = QFont()
    _base.setPointSize(13)
    app.setFont(_base)

    from app.ui.artifex_window import ArtifexWindow
    window = ArtifexWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
