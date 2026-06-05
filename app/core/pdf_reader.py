from pathlib import Path

from app.core.pdf_extract import extract_pdf_text


def extract_text_from_pdf(pdf_path: str) -> str:
    """Extract all text from a PDF (native layer + OCR if scanned)."""
    path = Path(pdf_path)
    try:
        return extract_pdf_text(path)
    except Exception as e:
        raise RuntimeError(f"No se pudo leer '{path.name}': {e}") from e
