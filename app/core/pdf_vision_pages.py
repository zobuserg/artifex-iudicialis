# -*- coding: utf-8 -*-
"""
Prototipo (opción C del plan): primeras páginas de un PDF como imágenes PNG en Messages API.

Uso: variable ``ADIUTOR_VISION_PDF_PAGES`` > 0 **y** ``ADIUTOR_API_PDF_ATTACH=0`` en generación de
resolución: se envían las N primeras páginas del **primer** PDF del expediente/bibliografía como
bloques ``image`` (base64), además del texto del prompt.

Coste: muchos tokens; no combinar con adjunto PDF completo (document) en el mismo mensaje.

Env:
  ADIUTOR_VISION_PDF_PAGES — número de páginas (0 = desactivado; tope interno 20)
  ADIUTOR_VISION_PDF_DPI — resolución del render (72–200; predeterminado 120)
"""

from __future__ import annotations

import base64
import os
from pathlib import Path


def env_vision_pdf_pages() -> int:
    try:
        return max(0, min(20, int(os.environ.get("ADIUTOR_VISION_PDF_PAGES", "0"))))
    except ValueError:
        return 0


def env_vision_pdf_dpi() -> int:
    try:
        return max(72, min(200, int(os.environ.get("ADIUTOR_VISION_PDF_DPI", "120"))))
    except ValueError:
        return 120


def render_pdf_pages_to_png_bytes(
    path: Path | str,
    *,
    max_pages: int,
    dpi: int | None = None,
) -> list[bytes]:
    """Renderiza hasta ``max_pages`` páginas a PNG (bytes)."""
    path = Path(path)
    d = env_vision_pdf_dpi() if dpi is None else dpi
    try:
        import fitz
    except ImportError:
        return []

    try:
        doc = fitz.open(path)
    except Exception:
        return []

    out: list[bytes] = []
    try:
        if getattr(doc, "needs_pass", False):
            return []
        n = min(max(1, max_pages), doc.page_count)
        scale = d / 72.0
        mat = fitz.Matrix(scale, scale)
        for i in range(n):
            page = doc[i]
            pix = page.get_pixmap(matrix=mat, alpha=False)
            out.append(pix.tobytes("png"))
    finally:
        doc.close()
    return out


def anthropic_image_blocks_from_pngs(pngs: list[bytes]) -> list[dict]:
    """Bloques ``content`` para Messages API (tipo image + base64)."""
    blocks: list[dict] = []
    for png in pngs:
        b64 = base64.standard_b64encode(png).decode("ascii")
        blocks.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": b64,
                },
            }
        )
    return blocks
