# -*- coding: utf-8 -*-
"""
PDF text extraction (todo **antes** de enviar el prompt a Claude):

1. Texto nativo con **pdfplumber**.
2. Texto nativo con **PyMuPDF** (capa de texto sin Tesseract); se conserva el más rico frente al paso 1.
3. Si aún no alcanza el umbral de calidad: archivo **compañero** ``.txt`` / ``.md`` junto al PDF
   (si basta para redactar, se devuelve **sin** pasar a OCR).
4. Solo entonces: render + **Tesseract** (y, si hace falta, OCR integrado MuPDF).

OCR system deps: macOS `brew install tesseract tesseract-lang`
Linux: `apt install tesseract-ocr tesseract-ocr-spa`
pip: pymupdf pytesseract pillow

Env:
  ADIUTOR_OCR=0 — desactiva OCR
  ADIUTOR_OCR_MAX_PAGES — máx. páginas por PDF (default 100)
  ADIUTOR_OCR_ZOOM — escala render→Tesseract pytesseract (default 2.0)
  ADIUTOR_OCR_DPI — resolución para paso alternativo MuPDF full-page OCR (default 150)
  ADIUTOR_OCR_LANG — idioma Tesseract en paso MuPDF (default spa)
  ADIUTOR_TESSERACT_CONFIG — p.ej. --oem 3 --psm 6 (bloque uniforme, adecuado a escritos)
  ADIUTOR_PDF_NATIVE_MIN_WORDS — mínimo de «palabras» (tokens 4+ letras) para aceptar solo
    capa de texto nativa sin OCR (predeterminado 18; baje a 12 si el PDF tiene poco texto seleccionable).

Archivo compañero: si junto a ``expediente.pdf`` existe ``expediente.txt`` o ``expediente.md`` con
al menos ~80 caracteres, se fusiona al resultado (prioridad si la extracción automática falla).
"""

from __future__ import annotations

import io
import os
import re
import shutil
from pathlib import Path

_tesseract_bootstrapped = False

_MIN_NATIVE_CHARS = 50
# Evita aceptar solo encabezados/pies con “texto nativo” corrupto o mínimo.
_DEFAULT_MIN_NATIVE_WORD_TOKENS = 18
_TOKEN_RE = re.compile(r"[\wáéíóúñüÁÉÍÓÚÑÜ]{4,}")
_DEFAULT_OCR_MAX_PAGES = 100
# Si el PDF “tiene” texto nativo pero es poco sustantivo, forzar OCR de todos modos.
_COMPANION_MIN_CHARS = 80
# Si el primer OCR (pixmap+pytesseract) queda por debajo, se prueba MuPDF full-page OCR.
_WEAK_OCR_WORD_THRESHOLD = 45


def _word_token_count(text: str) -> int:
    if not text:
        return 0
    return len(_TOKEN_RE.findall(text))


def _env_native_min_word_tokens() -> int:
    try:
        return max(8, int(os.environ.get("ADIUTOR_PDF_NATIVE_MIN_WORDS", _DEFAULT_MIN_NATIVE_WORD_TOKENS)))
    except ValueError:
        return _DEFAULT_MIN_NATIVE_WORD_TOKENS


def _native_layer_sufficient(native: str) -> bool:
    """True solo si hay bastante texto nativo real (no solo basura de fuentes embebidas)."""
    sig = "".join(c for c in native if c.isalnum() or c.isspace())
    if len(sig.strip()) < _MIN_NATIVE_CHARS:
        return False
    return _word_token_count(native) >= _env_native_min_word_tokens()


def _ocr_tesseract_configs() -> list[str]:
    """Varias PSM: documento uniforme, columna única, automático (útil en autos escaneados)."""
    primary = _tesseract_user_config().strip()
    alts = [
        "--oem 3 --psm 4",
        "--oem 3 --psm 3",
        "--oem 3 --psm 1",
    ]
    out: list[str] = []
    for c in [primary] + alts:
        if c and c not in out:
            out.append(c)
    return out


def _load_companion_text(pdf: Path) -> str | None:
    """
    Si junto al PDF existe un .txt o .md con el mismo nombre base, úsese como respaldo
    (transcripción manual, OCR externo, etc.).
    """
    for candidate in (pdf.with_suffix(".txt"), pdf.with_suffix(".md")):
        if not candidate.is_file():
            continue
        try:
            raw = candidate.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            continue
        if len(raw) < _COMPANION_MIN_CHARS:
            continue
        return (
            f"[Texto leído desde `{candidate.name}` (misma carpeta que `{pdf.name}`). "
            "Compruebe que corresponde al mismo documento.]\n\n"
            f"{raw}"
        )
    return None


def _pdf_body_is_weak_or_failed(main: str) -> bool:
    s = (main or "").strip()
    if not s:
        return True
    if _word_token_count(s) < 30:
        return True
    low = s.lower()
    if s.startswith("[error") or s.startswith("[formato no soportado"):
        return True
    if s.startswith("[el archivo '") and "no contiene texto" in low:
        return True
    if "sin texto" in low and "tras ocr" in low:
        return True
    if "ocr no ejecutado" in low:
        return True
    if "no se pudo leer" in low and s.startswith("["):
        return True
    return False


def _merge_companion_into_pdf_text(pdf: Path, main: str) -> str:
    comp = _load_companion_text(pdf)
    if not comp:
        return main
    if _pdf_body_is_weak_or_failed(main):
        return (
            comp
            + "\n\n[--- Salida automática del PDF (referencia; puede estar vacía o con ruido de OCR) ---]\n\n"
            + (main or "").strip()
        ).strip()
    return (
        (main or "").rstrip()
        + "\n\n[--- Texto complementario desde archivo .txt/.md junto al PDF ---]\n\n"
        + comp
    )


def _env_ocr_enabled() -> bool:
    v = os.environ.get("ADIUTOR_OCR", "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def _env_ocr_max_pages() -> int:
    try:
        return max(1, int(os.environ.get("ADIUTOR_OCR_MAX_PAGES", _DEFAULT_OCR_MAX_PAGES)))
    except ValueError:
        return _DEFAULT_OCR_MAX_PAGES


def _env_ocr_zoom() -> float:
    """Escala PyMuPDF para OCR. Menor = más rápido (p. ej. 1.5)."""
    try:
        z = float(os.environ.get("ADIUTOR_OCR_ZOOM", "2.0"))
        return min(3.0, max(1.0, z))
    except ValueError:
        return 2.0


def _env_ocr_dpi() -> int:
    try:
        return min(300, max(72, int(os.environ.get("ADIUTOR_OCR_DPI", "150"))))
    except ValueError:
        return 150


def _tesseract_user_config() -> str:
    """PSM/OEM recomendado para documentos jurídicos en bloque (ajustable)."""
    return os.environ.get("ADIUTOR_TESSERACT_CONFIG", "--oem 3 --psm 6").strip()


def _extract_native_pdfplumber(path: Path) -> str:
    import pdfplumber

    parts: list[str] = []
    with pdfplumber.open(str(path)) as pdf:
        for i, page in enumerate(pdf.pages, 1):
            t = page.extract_text()
            if t and t.strip():
                parts.append(f"[P\u00e1gina {i}]\n{t.strip()}")
    return "\n\n".join(parts)


def _extract_native_pymupdf_text_layer(path: Path) -> str:
    """
    Segundo intento «normal» (sin OCR): capa de texto que expone PyMuPDF.
    Útil cuando pdfplumber deja poco pero el PDF sí tiene texto embebido legible por MuPDF.
    """
    try:
        import fitz
    except ImportError:
        return ""
    try:
        doc = fitz.open(path)
    except Exception:
        return ""
    parts: list[str] = []
    try:
        if getattr(doc, "needs_pass", False):
            return ""
        for i in range(doc.page_count):
            page = doc[i]
            t = page.get_text("text")
            if t and t.strip():
                parts.append(f"[P\u00e1gina {i + 1}]\n{t.strip()}")
    finally:
        doc.close()
    return "\n\n".join(parts)


def _companion_merged_before_ocr(path: Path, native: str, plumber_error: str | None) -> str | None:
    """
    Tras agotar capas nativas (pdfplumber + MuPDF texto): si hay .txt/.md compañero y,
    fusionado con lo extraído, el resultado ya supera el umbral de texto «suficiente»,
    devolverlo aquí y **no** ejecutar Tesseract.
    """
    if not _load_companion_text(path):
        return None
    if native.strip():
        main = native
    elif plumber_error:
        main = f"[Error leyendo {path.name} con pdfplumber: {plumber_error}]"
    else:
        main = ""
    merged = _merge_companion_into_pdf_text(path, main)
    if _native_layer_sufficient(merged):
        return merged
    return None


def bootstrap_tesseract() -> None:
    """
    Asegura que Tesseract sea visible al lanzar la app desde Finder/Dock (PATH mínimo en macOS).
    Idempotente; no sobrescribe ADIUTOR_TESSERACT_CMD ni PATH si ya resuelve el binario.
    """
    global _tesseract_bootstrapped
    if _tesseract_bootstrapped:
        return
    _tesseract_bootstrapped = True

    candidates: list[Path] = []
    env_cmd = os.environ.get("ADIUTOR_TESSERACT_CMD", "").strip()
    if env_cmd:
        candidates.append(Path(env_cmd).expanduser())
    found = shutil.which("tesseract")
    if found:
        candidates.append(Path(found))
    for p in (
        Path("/opt/homebrew/bin/tesseract"),
        Path("/usr/local/bin/tesseract"),
    ):
        candidates.append(p)

    tess: Path | None = None
    for c in candidates:
        try:
            if c.is_file():
                tess = c.resolve()
                break
        except OSError:
            continue
    if tess is None:
        return

    tess_dir = str(tess.parent)
    path = os.environ.get("PATH", "")
    if tess_dir not in path.split(":"):
        os.environ["PATH"] = f"{tess_dir}:{path}" if path else tess_dir

    try:
        import pytesseract

        pytesseract.pytesseract.tesseract_cmd = str(tess)
    except ImportError:
        pass


def _tesseract_install_hint() -> str:
    return (
        "\n\n[OCR no ejecutado: falta Tesseract. "
        "macOS: brew install tesseract tesseract-lang | "
        "Ubuntu/Debian: sudo apt install tesseract-ocr tesseract-ocr-spa | "
        "Si ya está instalado y abre la app desde el icono, reinicie tras actualizar "
        "o defina ADIUTOR_TESSERACT_CMD=/opt/homebrew/bin/tesseract en .env]"
    )


def _ocr_page_text(png_bytes: bytes, page_num: int) -> str:
    import pytesseract
    from PIL import Image

    img = Image.open(io.BytesIO(png_bytes))
    last_err: Exception | None = None
    min_chars = 22
    for cfg in _ocr_tesseract_configs():
        for lang in ("spa+eng", "spa", "eng"):
            try:
                raw = pytesseract.image_to_string(img, lang=lang, config=cfg)
                if raw and len(raw.strip()) >= min_chars:
                    return f"[P\u00e1gina {page_num} \u2014 OCR]\n{raw.strip()}"
            except Exception as e:
                last_err = e
                continue
        try:
            raw = pytesseract.image_to_string(img, config=cfg)
            if raw and len(raw.strip()) >= min_chars:
                return f"[P\u00e1gina {page_num} \u2014 OCR]\n{raw.strip()}"
        except Exception as e:
            last_err = e
    if last_err:
        return f"[P\u00e1gina {page_num} \u2014 OCR fall\u00f3: {last_err}]"
    return ""


def _extract_ocr_pymupdf(path: Path) -> tuple[str, str]:
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return "", "[OCR: instale pymupdf: pip install pymupdf]"

    try:
        import pytesseract
    except ImportError:
        return "", "[OCR: instale pytesseract: pip install pytesseract]"

    try:
        pytesseract.get_tesseract_version()
    except pytesseract.TesseractNotFoundError:
        return "", _tesseract_install_hint()

    parts: list[str] = []
    note = ""
    max_pages = _env_ocr_max_pages()
    try:
        doc = fitz.open(path)
    except Exception as e:
        return "", f"[OCR: no se pudo abrir el PDF: {e}]"

    total = doc.page_count
    limit = min(total, max_pages)
    if total > max_pages:
        note = (
            f"\n\n[OCR: solo {limit} de {total} p\u00e1ginas. "
            f"Aumente ADIUTOR_OCR_MAX_PAGES si hace falta.]"
        )

    zoom = _env_ocr_zoom()
    try:
        for i in range(limit):
            page = doc[i]
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            png = pix.tobytes("png")
            block = _ocr_page_text(png, i + 1)
            if block:
                parts.append(block)
    finally:
        doc.close()

    return "\n\n".join(parts), note


def _extract_ocr_mupdf_textpage(path: Path) -> tuple[str, str]:
    """
    Segundo paso: PyMuPDF genera textpage con OCR de página completa (otro pipeline Tesseract).
    Suele funcionar mejor cuando el render manual + pytesseract devuelve poco texto.
    """
    try:
        import fitz
    except ImportError:
        return "", ""

    max_pages = _env_ocr_max_pages()
    dpi = _env_ocr_dpi()
    lang_primary = os.environ.get("ADIUTOR_OCR_LANG", "spa").strip() or "spa"
    langs_try: list[str] = [lang_primary]
    if lang_primary not in ("spa+eng", "eng"):
        langs_try.append("spa+eng")
    langs_try.append("eng")

    parts: list[str] = []
    note = ""
    try:
        doc = fitz.open(path)
    except Exception:
        return "", ""

    total = doc.page_count
    limit = min(total, max_pages)
    if total > max_pages:
        note = (
            f"\n\n[OCR-MuPDF: solo {limit} de {total} p\u00e1ginas. "
            f"Aumente ADIUTOR_OCR_MAX_PAGES.]"
        )
    try:
        for i in range(limit):
            page = doc[i]
            block = ""
            for lang in langs_try:
                try:
                    tp = page.get_textpage_ocr(flags=0, language=lang, dpi=dpi, full=True)
                    t = page.get_text("text", textpage=tp)
                    if t and len(t.strip()) > 30:
                        block = f"[P\u00e1gina {i + 1} \u2014 OCR-MuPDF]\n{t.strip()}"
                        break
                except Exception:
                    continue
            if block:
                parts.append(block)
    finally:
        doc.close()

    return "\n\n".join(parts), note


def _ocr_body_too_weak(body: str) -> bool:
    if not body or not body.strip():
        return True
    if _word_token_count(body) < _WEAK_OCR_WORD_THRESHOLD:
        return True
    # Muchas páginas con fallo explícito de tesseract
    if body.count("OCR fall") > 3:
        return True
    return False


def _pick_richer_text(a: str, b: str) -> str:
    return a if _word_token_count(a) >= _word_token_count(b) else b


def probe_pdf_readability(path: Path | str) -> tuple[int, int, str, bool]:
    """
    Ejecuta la misma extracción que el prompt y devuelve:
    (tokens_palabra_4+, caracteres_totales, vista_previa, parece_fallo_o_muy_pobre).
    """
    path = Path(path)
    t = extract_pdf_text(path)
    wc = _word_token_count(t)
    cc = len(t)
    prev = (t[:2200] + "\n…") if len(t) > 2200 else t
    bad = _pdf_body_is_weak_or_failed(t)
    return wc, cc, prev, bad


def extract_pdf_text(path: Path | str, *, use_ocr: bool | None = None) -> str:
    """Texto completo: pdfplumber → PyMuPDF (texto nativo) → compañero .txt/.md si evita OCR → Tesseract.

    Orden pensado para surcos del expediente **antes** de Claude: primero lectura «normal»
    (capas de texto y transcripción manual vecina); solo si sigue siendo insuficiente, OCR.

    Si el PDF se lee bien con las capas nativas, el compañero se **anexa** al final (ver ``_merge_companion_into_pdf_text``).
    """
    bootstrap_tesseract()
    path = Path(path)
    plumber_error: str | None = None
    native = ""
    try:
        native = _extract_native_pdfplumber(path)
    except Exception as e:
        plumber_error = str(e)

    native_fitz = _extract_native_pymupdf_text_layer(path)
    if native_fitz.strip():
        native = _pick_richer_text(native, native_fitz)

    effective_ocr = _env_ocr_enabled() if use_ocr is None else use_ocr

    if native and _native_layer_sufficient(native):
        return _merge_companion_into_pdf_text(path, native)

    if not effective_ocr:
        if native:
            return _merge_companion_into_pdf_text(path, native)
        if plumber_error:
            return _merge_companion_into_pdf_text(
                path, f"[Error leyendo {path.name} con pdfplumber: {plumber_error}]"
            )
        return _merge_companion_into_pdf_text(
            path,
            (
                f"[El archivo '{path.name}' no contiene texto extra\u00edble o est\u00e1 escaneado. "
                f"OCR desactivado (ADIUTOR_OCR=0); instale Tesseract y active OCR.]"
            ),
        )

    rescued = _companion_merged_before_ocr(path, native, plumber_error)
    if rescued is not None:
        return rescued

    ocr_body, ocr_note = _extract_ocr_pymupdf(path)
    if _ocr_body_too_weak(ocr_body):
        alt, alt_note = _extract_ocr_mupdf_textpage(path)
        if alt.strip():
            chosen = _pick_richer_text(ocr_body, alt)
            if chosen == alt:
                ocr_body = alt
                ocr_note = (alt_note or "") + (ocr_note or "")
            else:
                ocr_note = (ocr_note or "") + (alt_note or "")

    if ocr_body and len(ocr_body.strip()) > 10:
        return _merge_companion_into_pdf_text(path, ocr_body + ocr_note)

    if native:
        return _merge_companion_into_pdf_text(path, native + (ocr_note or ""))
    if plumber_error:
        return _merge_companion_into_pdf_text(
            path,
            (
                f"[Error leyendo {path.name} con pdfplumber: {plumber_error}]"
                f"{ocr_note or ''}"
            ),
        )
    if ocr_note:
        return _merge_companion_into_pdf_text(
            path, f"[{path.name}: sin texto \u00fatil tras OCR]{ocr_note}"
        )
    return _merge_companion_into_pdf_text(
        path,
        (
            f"[El archivo '{path.name}' no contiene texto extra\u00edble ni resultado OCR. "
            f"Instale Tesseract y datos spa (tesseract-lang). "
            f"Opciones: mismo nombre + `.txt`/`.md` en la misma carpeta; "
            f"ADIUTOR_OCR_DPI=200; ADIUTOR_OCR_ZOOM=2.5; ADIUTOR_TESSERACT_CONFIG='--oem 3 --psm 4'; "
            f"ADIUTOR_PDF_NATIVE_MIN_WORDS=12 si el PDF tiene poco texto seleccionable.]"
        ),
    )
