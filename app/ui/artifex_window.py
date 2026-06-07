"""
artifex_window.py — Ventana principal de Artifex Iudicialis.

Diseño limpio, una sola responsabilidad: mostrar la Fábrica de Resoluciones.
Sin pestañas, sin barras de herramientas redundantes. La complejidad vive dentro
de FabricaWidget; esta ventana solo la envuelve con el marco de sistema operativo.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QFont, QIcon
from PyQt6.QtWidgets import QMainWindow, QWidget, QVBoxLayout

from app.ui.fabrica import FabricaWidget, _C


class ArtifexWindow(QMainWindow):
    """Ventana principal de Artifex Iudicialis."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Adiutor Iudicis.2 — Redactor de Resoluciones")
        self.resize(1100, 760)
        self.setMinimumSize(860, 600)
        self.setStyleSheet(f"QMainWindow {{ background: {_C['paper']}; }}")

        # Widget central: la Fábrica
        self._fabrica = FabricaWidget()
        self.setCentralWidget(self._fabrica)

    def closeEvent(self, event):
        self._fabrica.closeEvent(event)
        super().closeEvent(event)
