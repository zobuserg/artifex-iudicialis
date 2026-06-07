"""Autocompletado de los datos del expediente (Expediente Nº, imputados, delito,
agraviado, juzgado) a partir de los documentos cargados.

Diseñado para ser RÁPIDO: lee solo las primeras páginas de los documentos clave
(no hace OCR de PDFs enteros como E1) y usa Haiku para extraer los campos. El
juez revisa y corrige lo que el modelo proponga.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

# Slots que típicamente llevan la carátula/encabezado con los metadatos.
_SLOTS_META = ("resolucion_apelada", "solicitud_inicial", "recurso_apelacion")

_CAMPOS = ("expediente", "imputados", "delito", "agraviado", "juzgado")

_PROMPT = (
    "Eres asistente de un juez penal. Del texto de los documentos de un "
    "expediente (abajo) extrae SOLO estos datos de carátula:\n"
    "  - expediente: número de expediente (ej. '389-2026-83' o 'EXP. N° 389-2026-83-...').\n"
    "  - imputados: nombre(s) del/los imputado(s) o procesado(s).\n"
    "  - delito: el delito imputado.\n"
    "  - agraviado: el agraviado (si es el Estado, escribe 'El Estado').\n"
    "  - juzgado: el juzgado/órgano de origen que emitió la resolución apelada.\n\n"
    "Responde ÚNICAMENTE con un objeto JSON con esas cinco claves. Si un dato no "
    "aparece con claridad, deja la cadena vacía \"\". No inventes nada.\n\n"
    "=== DOCUMENTOS ===\n\n"
)


def _fast_text(path: Path, max_pages: int = 3, max_chars: int = 6000) -> str:
    """Texto de las primeras páginas/sección, sin OCR pesado."""
    suf = path.suffix.lower()
    try:
        if suf == ".pdf":
            import pdfplumber

            partes: list[str] = []
            with pdfplumber.open(str(path)) as pdf:
                for page in pdf.pages[:max_pages]:
                    partes.append(page.extract_text() or "")
            return "\n".join(partes)[:max_chars]
        # docx / doc / txt / md
        from app.core.claude_worker import read_slot_document_text

        return (read_slot_document_text(path) or "")[:max_chars]
    except Exception:
        return ""


def extract_expediente_metadata(
    slots: dict[str, list[Path]],
    slot_labels: dict[str, str] | None = None,
) -> dict[str, str]:
    """Devuelve {expediente, imputados, delito, agraviado, juzgado} o {} si no hay material."""
    slot_labels = slot_labels or {}
    chunks: list[str] = []
    for key in _SLOTS_META:
        for p in (slots.get(key) or [])[:1]:  # primer documento de cada slot clave
            txt = _fast_text(p)
            if txt.strip():
                etiqueta = slot_labels.get(key, key)
                chunks.append(f"[{etiqueta} · {p.name}]\n{txt}")

    if not chunks:
        return {}

    from app.core.wiki_worker import _call_haiku, _get_client

    client = _get_client()
    raw = _call_haiku(client, _PROMPT + "\n\n".join(chunks), max_tokens=400) or ""
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return {}
    try:
        data = json.loads(match.group())
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    # Normaliza: solo los campos esperados, como cadenas limpias.
    return {c: str(data.get(c, "") or "").strip() for c in _CAMPOS}
