"""
Worker thread que lee los archivos del expediente, arma el prompt
con contenido embebido y llama a la API de Anthropic (Claude) con streaming.

Resoluciones (generación + iteración): modelo configurable vía ``ADIUTOR_CLAUDE_RESOLUTION_MODEL`` \
(por defecto Opus 4.7 con fallback a Sonnet 4.6).

Requiere:  pip install anthropic pdfplumber pymupdf pytesseract pillow
            (Tesseract en el sistema para OCR en PDF escaneados)
API key:   variable de entorno ANTHROPIC_API_KEY

Opcional: adjuntar los mismos PDF del expediente y bibliografía como bloques ``document``
nativos en la API (además del texto extraído en el prompt), vía ``ADIUTOR_API_PDF_ATTACH``.
Ver documentación Anthropic «PDF support» y límites de tamaño de petición.

Reintentos ante fallos transitorios del proveedor (5xx, 429, timeout): ``ADIUTOR_STREAM_MAX_ATTEMPTS``
(intentos por modelo, predeterminado 3), ``ADIUTOR_STREAM_RETRY_BASE_SEC`` (base exponencial,
predeterminado 2s), ``ADIUTOR_STREAM_RETRY_MAX_SEC`` (tope por espera, predeterminado 90s).
"""

from __future__ import annotations

import base64
import os
import re
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
import sys
import zipfile
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from app.core.human_editor_hints import (
    CARGOS_MP_LITERAL_ES,
    CLAUDE_WORKER_EDITOR_APPEND_ES,
    ITER_WORKER_SYSTEM_PREFIX_ES,
    REGLAS_TRANSVERSALES_ANTIAI_MAGISTRADO_ES,
)
from app.core.prompt_injection_guard import (
    rules_for_untrusted_sources,
    system_injection_guard_es,
    wrap_untrusted_document,
)


# Modelos para redacción/iteración de resoluciones (API Messages). Wiki/fichas siguen usando Haiku en wiki_worker.
_RESOLUTION_MODEL_ENV = "ADIUTOR_CLAUDE_RESOLUTION_MODEL"
_RESOLUTION_FALLBACK_AFTER_OPUS_DEFAULT = ("claude-sonnet-4-6",)


def resolution_model_candidates() -> tuple[str, ...]:
    """
    Cadena de modelos API a probar en orden si uno falla (p. ej. sin acceso Opus).

    Env ADIUTOR_CLAUDE_RESOLUTION_MODEL:
      - Una id: ``claude-opus-4-7``
      - Varios separados por coma o punto y coma (se intentan en ese orden).

    Por defecto: Opus 4.7 primero; luego Sonnet 4.6.
    """
    raw = os.environ.get(_RESOLUTION_MODEL_ENV, "").strip()
    if raw:
        parts = re.split(r"[,;]\s*", raw)
        xs = tuple(p.strip() for p in parts if p.strip())
        if xs:
            return xs
    return ("claude-opus-4-7",) + _RESOLUTION_FALLBACK_AFTER_OPUS_DEFAULT


def resolution_model_badge_label() -> str:
    """Texto corto para la UI (primer modelo configurado)."""
    raw = resolution_model_candidates()[0]
    aliases = {
        "claude-opus-4-7": "Opus 4.7",
        "claude-opus-4-6": "Opus 4.6",
        "claude-sonnet-4-6": "Sonnet 4.6",
    }
    if raw in aliases:
        return aliases[raw]
    return raw.removeprefix("claude-")


_RESOLUTION_MAX_TOKENS_ENV = "ADIUTOR_CLAUDE_RESOLUTION_MAX_TOKENS"
_RESOLUTION_MAX_TOKENS_DEFAULT = 26000


def resolution_max_output_tokens() -> int:
    """Salida máxima por llamada Messages (principal + continuaciones)."""
    try:
        v = int(os.environ.get(_RESOLUTION_MAX_TOKENS_ENV, str(_RESOLUTION_MAX_TOKENS_DEFAULT)))
    except ValueError:
        v = _RESOLUTION_MAX_TOKENS_DEFAULT
    return max(4_096, min(128_000, v))


# ── Presupuesto de tamaño del prompt (evita superar el límite de 200k tokens) ──
# El expediente y la bibliografía se incrustan como texto; con muchos anexos el
# prompt puede pasar el máximo de la API. Estos topes (en caracteres) limitan el
# texto embebido priorizando lo crítico (solicitud, resolución apelada, recurso).
_SLOTS_TEXT_BUDGET_ENV = "ADIUTOR_PROMPT_SLOTS_MAX_CHARS"
_SLOTS_TEXT_BUDGET_DEFAULT = 280_000
_BIB_TEXT_BUDGET_ENV = "ADIUTOR_PROMPT_BIB_MAX_CHARS"
_BIB_TEXT_BUDGET_DEFAULT = 120_000


def _slots_text_budget_chars() -> int:
    try:
        return max(20_000, int(os.environ.get(_SLOTS_TEXT_BUDGET_ENV, str(_SLOTS_TEXT_BUDGET_DEFAULT))))
    except ValueError:
        return _SLOTS_TEXT_BUDGET_DEFAULT


def _bib_text_budget_chars() -> int:
    try:
        return max(10_000, int(os.environ.get(_BIB_TEXT_BUDGET_ENV, str(_BIB_TEXT_BUDGET_DEFAULT))))
    except ValueError:
        return _BIB_TEXT_BUDGET_DEFAULT


_STREAM_MAX_ATTEMPTS_ENV = "ADIUTOR_STREAM_MAX_ATTEMPTS"
_STREAM_RETRY_BASE_ENV = "ADIUTOR_STREAM_RETRY_BASE_SEC"
_STREAM_RETRY_MAX_ENV = "ADIUTOR_STREAM_RETRY_MAX_SEC"


def resolution_stream_max_attempts() -> int:
    """Intentos por modelo ante errores reintentables de la API (cada intento es un stream nuevo)."""
    try:
        v = int(os.environ.get(_STREAM_MAX_ATTEMPTS_ENV, "3"))
    except ValueError:
        v = 3
    return max(1, min(8, v))


def resolution_stream_retry_base_sec() -> float:
    try:
        v = float(os.environ.get(_STREAM_RETRY_BASE_ENV, "2.0"))
    except ValueError:
        return 2.0
    return max(0.5, v)


def resolution_stream_retry_max_sec() -> float:
    try:
        v = float(os.environ.get(_STREAM_RETRY_MAX_ENV, "90"))
    except ValueError:
        return 90.0
    return max(1.0, v)


def resolution_stream_retry_delay_sec(attempt: int) -> float:
    """Backoff exponencial acotado; nunca devuelve esperas negativas para la UI."""
    exp = max(0, attempt - 1)
    return max(
        0.5,
        min(
            resolution_stream_retry_base_sec() * (2 ** exp),
            resolution_stream_retry_max_sec(),
        ),
    )


def format_anthropic_stream_exception(exc: BaseException) -> str:
    """Texto para UI/logs: mensaje SDK + request-id + trozo de body si existen."""
    parts: list[str] = []
    msg = str(exc).strip()
    if msg:
        parts.append(msg)
    rid = getattr(exc, "request_id", None)
    if isinstance(rid, str) and rid.strip():
        parts.append(f"request-id: {rid.strip()}")
    body = getattr(exc, "body", None)
    if body is not None and body != {}:
        bstr = repr(body)
        if len(bstr) > 280:
            bstr = bstr[:277] + "…"
        parts.append(f"body: {bstr}")
    if len(parts) <= 1:
        return parts[0] if parts else type(exc).__name__
    return " — ".join(parts)


def anthropic_stream_error_retryable(exc: BaseException) -> bool:
    """True si conviene reintentar el mismo modelo tras backoff."""
    try:
        import anthropic
    except ImportError:
        return False
    if isinstance(exc, anthropic.APITimeoutError):
        return True
    if isinstance(exc, anthropic.APIConnectionError):
        return True
    if isinstance(exc, anthropic.RateLimitError):
        return True
    if isinstance(exc, anthropic.InternalServerError):
        return True
    if isinstance(exc, anthropic.APIStatusError):
        code = int(getattr(exc, "status_code", 0) or 0)
        return code in (408, 425, 429, 500, 502, 503, 504)
    return False


def _interruptible_sleep(seconds: float, cancelled_fn: Callable[[], bool], *, step: float = 0.25) -> bool:
    """
    Espera hasta ``seconds`` salvo cancelación.
    Returns True si completó la espera; False si ``cancelled_fn()`` fue True antes de terminar.
    """
    if seconds <= 0:
        return True
    cap = resolution_stream_retry_max_sec()
    seconds = min(seconds, max(0.5, cap))
    slept = 0.0
    while slept < seconds:
        if cancelled_fn():
            return False
        time.sleep(min(step, seconds - slept))
        slept += step
    return not cancelled_fn()


def consume_claude_messages_stream_once(
    client,
    *,
    model: str,
    max_tokens: int,
    system,
    messages: list,
    cancelled_fn: Callable[[], bool],
    chunk_emit: Callable[[str], None],
) -> tuple[list[str], object | None, bool]:
    """
    Una sesión ``messages.stream``.

    Returns:
        (assembled_text_parts, final_message, cancelled_by_user)
    """
    assembled: list[str] = []
    with client.messages.stream(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=messages,
    ) as stream:
        user_broke = False
        for text in stream.text_stream:
            if cancelled_fn():
                user_broke = True
                break
            if text:
                assembled.append(text)
                chunk_emit(text)
        if user_broke or cancelled_fn():
            return assembled, None, True
        fm = stream.get_final_message()
        return assembled, fm, False


def resolution_lacks_closing_heuristic(acto: str, *, min_chars: int = 2200) -> bool:
    """
    Heurística barata: actos largos suelen cerrar con firma / dispositivo / «firma el magistrado».
    Reduce falsos negativos si end_turn llegó antes de tiempo sin max_tokens declarado por API (raro).
    """
    t = (acto or "").strip()
    if len(t) < min_chars:
        return False
    tail = t[-5200:]
    tl = tail.upper()
    needles = (
        " FIRMO",
        "FIRMADO",
        "\nATO",
        "\nATO.",
        " MAGISTRAD",
        " FIRMA EL ",
        "\nDISPOSITIVO",
        " POR TANTO,",
        "SS.\n",
        "\nSS.",
        "\nS.S.",
    )
    return not any(k in tl for k in needles)


@dataclass
class GenerationOutcome:
    """Estado después de cerrar streaming de Claude (primera llamada o continuación)."""

    cancelled: bool = False
    stop_reason: str | None = None
    model_used: str = ""
    max_tokens_truncation: bool = False
    suspicious_missing_cierre: bool = False

    def likely_incomplete(self) -> bool:
        if self.cancelled:
            return True
        if self.max_tokens_truncation:
            return True
        if self.stop_reason == "max_tokens":
            return True
        # end_turn pero sin marca de cierre en textos muy largos
        if self.suspicious_missing_cierre and (self.stop_reason in (None, "end_turn")):
            return True
        return False

    def reasons_spanish(self) -> list[str]:
        out: list[str] = []
        if self.cancelled:
            out.append("Generación cancelada por el usuario.")
        if self.max_tokens_truncation or self.stop_reason == "max_tokens":
            out.append(
                "El modelo alcanzó el límite de salida (max_tokens); el acto puede haberse cortado."
            )
        if self.suspicious_missing_cierre and not self.cancelled:
            out.append(
                "No se detectó en el tramo final un cierre típico (firma, dispositivo, etc.); "
                "revise si falta parte del acto."
            )
        if self.stop_reason and self.stop_reason not in ("end_turn", "max_tokens"):
            out.append(f"Motivo de parada del API: {self.stop_reason}.")
        return out


def build_resolution_system_blocks() -> list[dict]:
    """Bloques `system` con caché efímera para generación y continuación de resoluciones."""
    return [
        {
            "type": "text",
            "text": (
                "Eres un asistente jurídico experto de la Sala Superior Penal de Apelaciones. "
                "Redactas resoluciones judiciales completas siguiendo exactamente "
                "la estructura de la plantilla proporcionada. "
                "Usas ÚNICAMENTE el contenido de los documentos embebidos en el prompt. "
                "Las fuentes por ranuras (PDF, audio transcrito, etc.) deben reflejarse en el acto conforme "
                "las instrucciones de materia/caso: si piden explicitación o un modo concreto por surco, obedece ese mandato."
                "Nunca inventas jurisprudencia, normas ni referencias."
                + system_injection_guard_es()
                + CLAUDE_WORKER_EDITOR_APPEND_ES
            ),
            "cache_control": {"type": "ephemeral"},
        }
    ]


_CONTINUATION_USER_ES = (
    "El acto judicial que estás redactando quedó **incompleto** o se cortó antes del cierre procesal.\n\n"
    "En el historial tienes:\n"
    "1) El **prompt completo** original (rol user) con plantilla y fuentes.\n"
    "2) Tu **respuesta parcial** (rol assistant) con el texto ya emitido.\n\n"
    "**Instrucciones obligatorias:**\n"
    "— No repitas encabezados, resultandos ni considerandos ya cubiertos; continúa **justo después** "
    "del último carácter coherente del acto parcial.\n"
    "— Completa exclusivamente lo **que falta**: considerandos posteriores, dispositivo/fallo, "
    "cierre y firmas según la plantilla y el estilo de sala.\n"
    "— No inventes hechos ni precedentes que no estuvieran ya sustentados en el material del prompt original.\n"
    "— Devuelve **solo** el texto **nuevo** que continúa el acto (no reenvíes el bloque anterior íntegro).\n"
)


# ---------------------------------------------------------------------------
# Extracción de texto
# ---------------------------------------------------------------------------

AUDIO_SUFFIXES = frozenset({".mp3", ".m4a", ".wav", ".ogg", ".webm", ".flac", ".aac"})

# Formatos de documento que read_file_text() sabe leer (texto extraíble).
DOC_SUFFIXES = (".pdf", ".docx", ".doc", ".pages", ".md", ".txt")


def qt_open_filter(*, include_audio: bool = False) -> str:
    """Cadena de filtro para QFileDialog con TODOS los formatos soportados.

    Fuente única de verdad: si read_file_text() aprende un formato nuevo, se agrega
    aquí y toda la UI lo acepta. `include_audio=True` para selectores de fuentes del
    caso (transcripción de audiencias); False para borradores/resoluciones.
    """
    docs = " ".join(f"*{s}" for s in DOC_SUFFIXES)
    if include_audio:
        audio = " ".join(f"*{s}" for s in sorted(AUDIO_SUFFIXES))
        return (
            f"Todos los soportados ({docs} {audio});;"
            f"Documentos ({docs});;"
            f"Audio ({audio});;"
            f"Todos los archivos (*)"
        )
    return f"Documentos ({docs});;Todos los archivos (*)"


def _env_whisper_auto() -> bool:
    """Por defecto, si Whisper está instalado se usa al leer audio sin `.txt`."""
    return os.environ.get("ADIUTOR_WHISPER_AUTO", "1").strip().lower() not in (
        "0", "false", "no", "off",
    )


def _read_audio_text(path: Path) -> str:
    """
    Transcripción lista para Claude: mismo nombre con extensión `.txt`,
    o transcripción automática con el CLI `whisper` si existe (ver transcribe_audio_to_txt).
    """
    try:
        p = Path(path).expanduser()
    except OSError:
        return f"[Error: ruta inválida para audio: {path}]"
    if not p.is_file():
        return f"[Error: archivo de audio no encontrado: `{p.name}`]"

    side = p.with_suffix(".txt")
    if side.is_file():
        try:
            return side.read_text(encoding="utf-8", errors="replace").strip()
        except OSError as e:
            return f"[Error leyendo transcripción `{side.name}`: {e}]"

    if _env_whisper_auto():
        try:
            from app.core.whisper_local import transcribe_audio_to_txt, whisper_cli_available

            if whisper_cli_available():
                ok, out = transcribe_audio_to_txt(p)
                if ok:
                    tp = Path(out)
                    if tp.is_file():
                        try:
                            return tp.read_text(encoding="utf-8", errors="replace").strip()
                        except OSError as e:
                            return (
                                f"[Audio `{p.name}`: Whisper generó archivo pero falló lectura: {e}]"
                            )
                    return (
                        f"[Audio `{p.name}`: Whisper finalizó sin archivo .txt esperado: {out}]"
                    )
                return f"[Audio `{p.name}`: transcripción Whisper falló — {out}]"
        except Exception as e:
            return f"[Audio `{p.name}`: error ejecutando Whisper: {e}]"

    return (
        f"[Audio `{p.name}` sin transcripción. Coloque `{p.stem}.txt` en la misma carpeta que "
        f"el audio, o ejecute desde la ranura «Audio» la transcripción; instale Whisper "
        f"(CLI `whisper` en el PATH tras `pip install openai-whisper`). "
        f"Transcripción automática al generar: ADIUTOR_WHISPER_AUTO=1 (por defecto).]"
    )


def _pdf_to_text(path: Path) -> str:
    """Extrae texto de PDF (capa nativa + OCR Tesseract si hace falta)."""
    try:
        import fitz  # PyMuPDF

        doc = fitz.open(path)
        try:
            if doc.needs_pass:
                return (
                    f"[{path.name}: este PDF está cifrado o exige contraseña. "
                    "Exporte o guarde una copia sin protección en el expediente.]"
                )
        finally:
            doc.close()
    except ImportError:
        pass
    except Exception:
        pass

    try:
        from app.core.pdf_extract import extract_pdf_text

        return extract_pdf_text(path)
    except Exception as e:
        return f"[Error leyendo {path.name}: {e}]"


def _docx_to_text(path: Path) -> str:
    """Extrae texto plano de un .docx sin dependencias extra."""
    try:
        with zipfile.ZipFile(path) as z:
            xml = z.read("word/document.xml").decode("utf-8")
        paras = re.findall(r"<w:p[ >].*?</w:p>", xml, re.DOTALL)
        lines: list[str] = []
        for p in paras:
            texts = re.findall(r"<w:t[^>]*>(.*?)</w:t>", p, re.DOTALL)
            line = "".join(texts).strip()
            if line and not line.startswith("<w:"):
                lines.append(line)
        return "\n\n".join(lines) or f"[{path.name}: documento vacío]"
    except Exception as e:
        return f"[Error leyendo {path.name}: {e}]"


def _textutil_to_plain(path: Path, timeout: int = 120) -> str | None:
    """macOS: textutil a texto plano. None si no hay texto o no existe la herramienta."""
    try:
        result = subprocess.run(
            ["textutil", "-convert", "txt", "-stdout", str(path)],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode == 0 and result.stdout and result.stdout.strip():
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    return None


def _pages_to_text(path: Path) -> str:
    """Extrae texto de un .pages usando textutil (incluido en macOS)."""
    t = _textutil_to_plain(path, timeout=30)
    if t:
        return t
    if sys.platform == "darwin":
        return f"[{path.name}: no se pudo extraer texto con textutil]"
    return f"[{path.name}: textutil no disponible — exporta a Word o PDF]"


def _doc_binary_to_text(path: Path) -> str:
    """
    Microsoft Word .doc (binario, no es ZIP como .docx).
    macOS: textutil. Linux: antiword si está instalado.
    """
    t = _textutil_to_plain(path, timeout=180)
    if t:
        return t
    if sys.platform != "darwin":
        try:
            r = subprocess.run(
                ["antiword", str(path)],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip()
        except FileNotFoundError:
            pass
        except Exception as e:
            return f"[Error leyendo {path.name}: {e}]"
    return (
        f"[{path.name}: .doc no legible en este sistema. Convierta a .docx o a PDF con texto, "
        f"o use macOS (textutil) / instale: sudo apt install antiword]"
    )


def read_file_text(path: Path) -> str:
    """Lee cualquier archivo soportado y devuelve su texto."""
    ext = path.suffix.lower()
    if ext in AUDIO_SUFFIXES:
        return _read_audio_text(path)
    if ext == ".pdf":
        return _pdf_to_text(path)
    if ext == ".docx":
        return _docx_to_text(path)
    if ext == ".doc":
        return _doc_binary_to_text(path)
    if ext == ".pages":
        return _pages_to_text(path)
    if ext in (".md", ".txt"):
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return f"[Error leyendo {path.name}: {e}]"
    return f"[Formato no soportado: {path.name}]"


def is_failed_document_extraction(text: str) -> bool:
    """
    True si read_file_text devolvió un marcador de fallo, no contenido útil.
    (No confundir con texto válido que empiece por [Página 1] u OCR.)
    """
    s = (text or "").strip()
    if not s:
        return True
    if s.startswith("[Error ") or s.startswith("[Formato no soportado"):
        return True
    if s.startswith("[Audio `") and ("sin transcripción" in s or "fall" in s.lower()):
        return True
    if (
        s.startswith("[")
        and "este PDF está cifrado" in s
        and "copia sin protección" in s
    ):
        return True
    low = s.lower()
    # Mensajes de pdf_extract / pdfplumber cuando no hay texto útil
    if s.startswith("[El archivo '") and "no contiene texto" in low:
        return True
    if "no contiene texto extra" in low and "ocr" in low:
        return True
    if "sin texto" in low and "\u00fatil tras ocr" in low:
        return True
    if "ocr no ejecutado" in low:
        return True
    if "no se pudo leer" in low and s.startswith("["):
        return True
    return False


def read_slot_document_text(path: Path) -> str:
    """
    Lectura para ranuras del expediente: resuelve la ruta real bajo `01_raw/…/fuentes/`
    y avisa si el archivo falta o si la extracción (PDF/audio) no es usable.
    """
    try:
        p = Path(path).expanduser().resolve(strict=False)
    except OSError:
        return (
            f"[ALERTA — ruta inválida: `{path}`. Pulse «PREPARAR CASO» de nuevo "
            f"tras colocar los archivos en fuentes/.]"
        )
    if not p.is_file():
        return (
            f"[ALERTA — no se encontró `{path.name}` en disco. "
            f"La app debe leer desde `01_raw/…/fuentes/`; vuelva a «PREPARAR CASO».]"
        )
    body = read_file_text(p)
    if is_failed_document_extraction(body):
        return (
            "[⚠️ EXTRACCIÓN NO UTILIZABLE — el acto debe reconocer esta limitación y, "
            "para audio, exigir archivo `.txt` junto al mismo; para PDF, revisar OCR/Tesseract, "
            "subir `.txt`/`.md` con el **mismo nombre base** que el PDF en la misma carpeta, "
            "o convertir a Word con texto seleccionable.]\n\n"
            + body
        )
    return body


_CRITICAL_EXTRACTION_SLOT_KEYS = frozenset(
    {
        "solicitud_inicial",
        "resolucion_apelada",
        "recurso_apelacion",
    }
)


def _slot_document_has_unusable_extraction(text: str) -> bool:
    """Detecta marcadores embebidos por `read_slot_document_text` en el Bloque 4."""
    s = (text or "").strip()
    if not s:
        return True
    if s.startswith("[ALERTA"):
        return True
    return s.startswith("[⚠️ EXTRACCIÓN NO UTILIZABLE")


def _raise_unusable_critical_sources(failures: list[str]) -> None:
    if not failures:
        return
    listed = "\n".join(f"- {x}" for x in failures[:12])
    more = "\n- …" if len(failures) > 12 else ""
    raise RuntimeError(
        "No se enviará a Claude todavía.\n\n"
        "La extracción local no produjo texto utilizable en fuente(s) esencial(es):\n"
        f"{listed}{more}\n\n"
        "Si se envía así, la resolución saldrá incompleta o no utilizable, especialmente "
        "cuando los PDF nativos se omiten por tamaño.\n\n"
        "Solución: ejecute OCR/Tesseract, convierta a Word o PDF con texto seleccionable, "
        "o coloque un archivo .txt/.md con el mismo nombre base junto al PDF en la misma ranura."
    )


SEP = "═" * 55


def _block_parametros_institucionales_peru() -> str:
    return (
        f"{SEP}\n"
        "BLOQUE 1B · PARÁMETROS INSTITUCIONALES DE REDACCIÓN (PERÚ)\n"
        f"{SEP}\n"
        "Estas reglas generales se aplican en TODOS los casos, además de la plantilla, "
        "la instrucción general de materia y la instrucción particular del expediente.\n\n"
        "Contexto fijo del acto:\n"
        "• Tipo: resolución judicial.\n"
        "• Ámbito: penal y constitucional.\n"
        "• País/ordenamiento: Perú.\n"
        "• Instancia: apelación.\n\n"
        "Estructura y forma:\n"
        "• Mantén estructura Vistos, Considerando(s) y Resuelve.\n"
        "• Considerandos numerados.\n"
        "• Sin tope rígido de extensión: conjuga brevedad, claridad, precisión y profundidad; "
        "sin relleno, redundancias ni párrafos meramente protocolares.\n\n"
        "Estilo y tratamiento:\n"
        "• Lenguaje claro sin renunciar al rigor técnico-jurídico.\n"
        "• Redacción en tercera persona impersonal.\n"
        "• Identifica a las partes por nombre completo, salvo en delitos contra la libertad sexual: "
        "víctima y testigos menores, cuando corresponda, con iniciales.\n\n"
        "Redacción judicial clara (operativa):\n"
        "• Usa frases preferentemente breves y párrafos de una sola idea.\n"
        "• Evita fórmulas vacías o de relleno (por ejemplo: cabe señalar, es menester, "
        "en ese orden de ideas) salvo necesidad argumentativa real.\n"
        "• No repitas doctrina, jurisprudencia ni hechos si no aportan al punto controvertido.\n"
        "• Cada considerando debe cumplir una función verificable: hecho probado, norma aplicable, "
        "estándar jurisprudencial, inferencia del caso o respuesta a un agravio.\n"
        "• Conserva la terminología penal, procesal penal y constitucional necesaria, pero explica "
        "su aplicación al caso con lenguaje directo.\n\n"
        "Modo de síntesis jurídica (regla por defecto):\n"
        "• Redacta de modo breve, claro y preciso, sin sacrificar suficiencia jurídica.\n"
        "• No sacrifiques fundamentación por brevedad; sacrifica redundancia, retórica y "
        "transcripción innecesaria, **excepto en cargos imputados por el MP, que van en transcripción literal**.\n"
        "• En cada punto relevante articula: hecho o agravio, norma/estándar, valoración e inferencia, "
        "y conclusión.\n\n"
        "Jerarquía de fundamentación (triple anclaje):\n"
        "• Orden de peso decisorio: normativo > jurisprudencial > doctrinal.\n"
        "• El eje argumental parte de Constitución, tratados, ley y reglamento.\n"
        "• La jurisprudencia opera como criterio de interpretación y aplicación, con peso reforzado "
        "cuando provenga del TC peruano, Acuerdos Plenarios o Casaciones de la Corte Suprema; "
        "cuando corresponda, incluye normativa convencional y decisiones de la Corte IDH/CIDH.\n"
        "• La doctrina cumple función auxiliar, ilustrativa o de refuerzo, sin sustituir el análisis "
        "normativo ni jurisprudencial.\n"
        "• En hábeas corpus prioriza: (i) Tribunal Constitucional peruano, (ii) Corte Suprema penal "
        "(Acuerdos Plenarios y Casaciones), (iii) Corte IDH para control de convencionalidad, "
        "(iv) doctrina nacional.\n"
        "• Cuando corresponda controlar la motivación de la resolución impugnada, aplica STC "
        "00728-2008-PHC/TC (caso Giuliana Llamoja) y STC Exp. N.° 01747-2013-PA/TC.\n"
        "• Si el caso lo amerita, aplica test de proporcionalidad (idoneidad, necesidad y "
        "proporcionalidad en sentido estricto/ponderación) con enfoque operativo según la línea "
        "del TC peruano.\n\n"
        "Jurisprudencia y verificación:\n"
        "• Nunca inventes fuentes. Si no hay respaldo verificable, decláralo expresamente.\n"
        "• Busca y usa solo jurisprudencia que conste en los documentos embebidos, bibliografía, wiki, "
        "plantilla o material proporcionado; si no logras verificar una sentencia, no la cites.\n"
        "• Formatos de cita válidos: STC Exp. N.° XXXX-AAAA-XX/TC, fundamento N.; "
        "Casación N.° XXX-AAAA, sede, considerando N.; doctrina en APA y nota al pie/cita en cuerpo "
        "cuando corresponda.\n\n"
        "Operativa de redacción:\n"
        "• Trabaja con escritos, pruebas, resoluciones previas y normativa proporcionados en PDF/Word "
        "o texto extraído.\n"
        "• Si el expediente es extenso, realiza primero un mapeo interno del contenido para identificar "
        "puntos controvertidos, pretensión impugnatoria, agravios y documentos relevantes antes de redactar.\n"
        "• Si detectas que el caso amerita test de proporcionalidad o control de motivación tipo Llamoja/"
        "STC 01747-2013-PA/TC, incorpora ese enfoque de modo expreso en el desarrollo; si el magistrado "
        "pidió confirmación previa, señálalo antes de cerrar el borrador.\n"
        "• Los datos del expediente no son parte del razonamiento ni del cuerpo resolutivo: deben ir "
        "en el encabezado previo al rótulo «Auto de Vista» o «Sentencia de Vista», según corresponda.\n"
        "• Ese encabezado previo debe incluir, en todos los casos con la misma estructura de rubros y cuando "
        "conste en las fuentes: expediente, imputado(s), delito, agraviado y procedencia. "
        "Si falta un rubro, extráelos de la documentación del expediente o del formulario; solo marca un rubro como "
        "no determinado cuando no figure en las fuentes.\n"
        "• Redacta en el sentido de fallo indicado; cuando el expediente lo permita y no contradiga la "
        "instrucción principal, puedes señalar alternativas razonadas de fallo (confirmar, revocar o nulidad).\n"
        "• La postura indicada por el magistrado es vinculante para el proyecto principal: si se ordena "
        "CONFIRMAR, el razonamiento y la parte resolutiva deben confirmar la resolución apelada; queda "
        "prohibido revocarla, reformarla o sustituir la medida por comparecencia, salvo orden expresa "
        "posterior del magistrado.\n"
        "• El rubro de fundamentos del recurso de apelación debe ser estrictamente descriptivo: resume "
        "solo agravios, expresiones y argumentos que consten en el escrito de apelación. No agregues "
        "argumentos plausibles, defensas genéricas ni inferencias no formuladas por el recurrente.\n"
        "• La absolución de agravios se hace únicamente sobre agravios surgidos del recurso de apelación. "
        "No conviertas en agravios los alegatos finales de primera instancia, teorías defensivas del juicio "
        "ni argumentos consignados en la sentencia apelada, salvo que el recurso de apelación los reproduzca "
        "o los incorpore expresamente como agravio.\n"
        "• Antes de entregar, realiza una depuración interna: elimina redundancias, fusiona párrafos "
        "que repiten la misma idea, suprime introducciones protocolares sin contenido, verifica que "
        "cada considerando responda a un problema jurídico o agravio, y conserva solo citas normativas "
        "y jurisprudenciales necesarias para resolver.\n\n"
        f"{CARGOS_MP_LITERAL_ES}\n"
    )


PP_CALIFICACION_RECEPTACION_EXTRA = (
    "Calificación en prisión preventiva (cuando el fiscal impute receptación u otros delitos concurrentes):\n"
    "• Tras la transcripción literal fiscal, verifica que la calificación incluya tipicidad completa y conexa "
    "(p. ej. art. 194 CP + agravante art. 195 + art. 427 CP), no solo el párrafo de pena del agravante.\n"
)


def _is_prision_preventiva(folder_name: str, materia_label: str) -> bool:
    fn = (folder_name or "").lower()
    ml = (materia_label or "").lower()
    return fn.startswith("prision_preventiva/") or "prisi" in ml and "preventiva" in ml


def build_enriched_prompt(
    *,
    plantilla_path: Path | None,
    slots: dict[str, list[Path]],          # slot_key → [Path]
    slot_labels: dict[str, str],            # slot_key → etiqueta legible
    bibliografia: list[Path],
    instruccion_general: str,
    instruccion_particular: str,
    postura: str,
    postura_personalizada: str,
    agravios: str,
    expediente: str,
    imputados: str,
    delito: str,
    agraviado: str,
    juzgado: str,
    materia_label: str,
    modo: str,
    borrador_path: str,
    folder_name: str,
    caso_num: str,
    tipo: str,
    resoluciones_estilo: list[Path] | None = None,
    warnings_out: list[str] | None = None,
) -> str:
    """Arma el prompt con el contenido de los archivos embebido."""

    blocks: list[str] = [f"# Procesar caso: {folder_name}\n"]

    # ── BLOQUE 1: Rol y tribunal ──────────────────────────────────────────
    blocks.append(
        f"{SEP}\n"
        "BLOQUE 1 · ROL Y TRIBUNAL\n"
        f"{SEP}\n"
        "Eres asistente jurídico del juez de la Sala Superior Penal de Apelaciones.\n"
        "• Usa ÚNICAMENTE el contenido de los documentos embebidos en este prompt.\n"
        "• No inventes casaciones, artículos, libros ni referencias.\n"
        "• Si citas jurisprudencia, debe estar en la bibliografía o en la plantilla.\n"
        "• Estilo: técnico-jurídico, preciso, elocuente sin retórica vacía.\n"
        "• Respeta el razonamiento silogístico judicial.\n"
    )
    blocks.append(_block_parametros_institucionales_peru())

    # ── BLOQUE 2: Instrucción permanente de la materia ────────────────────
    ig = (instruccion_general or "").strip()
    if ig:
        blocks.append(
            f"{SEP}\n"
            f"BLOQUE 2 · INSTRUCCIÓN PERMANENTE ({materia_label})\n"
            f"{SEP}\n"
            f"{ig}\n"
        )

    if _is_prision_preventiva(folder_name, materia_label):
        blocks.append(
            f"{SEP}\n"
            "BLOQUE 2 · COMPLEMENTO PP — CALIFICACIÓN RECEPTACIÓN\n"
            f"{SEP}\n"
            f"{PP_CALIFICACION_RECEPTACION_EXTRA}\n"
        )

    # ── BLOQUE 3: Plantilla (contenido embebido) ──────────────────────────
    if plantilla_path and plantilla_path.is_file():
        pla_text = read_file_text(plantilla_path)
        blocks.append(
            f"{SEP}\n"
            "BLOQUE 3 · PLANTILLA MAESTRA (estructura obligatoria)\n"
            f"{SEP}\n"
            "LEE ÍNTEGRA ANTES DE ESCRIBIR UNA SOLA LÍNEA.\n"
            "Sigue EXACTAMENTE: encabezado, tabla de datos, numeración de secciones,\n"
            "orden de considerandos, checklist y formato de firma S.S.\n"
            "La parte común de la plantilla (lugar y fecha, Vistos, rótulos, orden de secciones, "
            "formato de encabezado y cierre) debe reproducirse en cuanto no se oponga a la "
            "particularidad del caso. La plantilla se incorpora para seguir formato e ítems a "
            "desarrollar; no la ignores ni la sustituyas por un formato propio.\n"
            "El caso de ejemplo en la plantilla es solo referencia estructural: los datos reales "
            "son los del expediente en el Bloque 4.\n\n"
            f"{pla_text}\n"
        )

    # ── BLOQUE 3B: Resoluciones de referencia de estilo (corpus del magistrado) ─
    estilo_paths = [p for p in (resoluciones_estilo or []) if p and Path(p).is_file()]
    if estilo_paths:
        partes_estilo: list[str] = [
            f"{SEP}\n"
            "BLOQUE 3B · ESTILO DEL MAGISTRADO (referencia de redacción)\n"
            f"{SEP}\n"
            "Las siguientes resoluciones del propio magistrado se incluyen EXCLUSIVAMENTE "
            "como referencia de ESTILO DE REDACCIÓN: vocabulario, estructura de considerandos, "
            "forma de citar jurisprudencia, nivel de detalle y tono. "
            "NO uses los hechos, datos de partes ni decisiones de estas resoluciones en el caso "
            "que estás redactando — son del todo distintos. Solo imita el estilo.\n"
        ]
        for i, p in enumerate(estilo_paths[:3], 1):
            try:
                contenido = read_file_text(Path(p))
                partes_estilo.append(
                    f"--- RESOLUCIÓN DE REFERENCIA {i} · {Path(p).name} ---\n"
                    f"{contenido}\n"
                    f"--- FIN RESOLUCIÓN {i} ---\n"
                )
            except Exception:
                pass
        if len(partes_estilo) > 1:   # solo si al menos una se leyó
            blocks.append("\n\n".join(partes_estilo))

    # ── BLOQUE 4: Fuentes del expediente (contenido embebido) ─────────────
    has_slots = any(v for v in slots.values())
    fuentes_header = (
        f"{SEP}\n"
        "BLOQUE 4 · FUENTES DEL EXPEDIENTE (ranuras / surcos)\n"
        f"{SEP}\n"
        "Cada sección `###` más abajo corresponde a una ranura cargada en la app (solicitud inicial, "
        "resolución apelada, recurso, anexos, audio, otros).\n\n"
        "REGLAS DE USO PARA EL ACTO QUE REDACTES:\n"
        "• **Modalidad cuando el magistrado la ordena:** si en el Bloque 2 (instrucción de materia) o en "
        "el Bloque 6 (instrucción particular) se pide **explicitar cada ranura**, desarrollar **los surcos** "
        "con **titulaciones identificables** (mismo orden o el orden indicado), o usar un **modo concreto** "
        "(síntesis por ranura frente al original; ítems numerados uno por archivo; tabla; transcripción destacada;"
        " cita textual mínima, etc.), **obedece literalmente ese modo.** No sustituyas por un formato genérico "
        "si el magistrado fijó otra forma.\n"
        "• **Sin mandato especial de forma:** debe **notarse igualmente** en el acto el contenido de cada ranura "
        "donde haya archivo (resumen/adecuación jurídica), de modo que ningún PDF ni la transcripción de audio "
        "queden absorbidos sin dejar huella racional.\n"
        "• Para **audio**, usa la transcripción incrustada en este bloque si existe texto.\n"
        "• Si aparece ⚠️ o [ALERTA], dilo en el acto como limitación técnica.\n"
        "• NO ignores el Bloque 4 por la plantilla o un ejemplo ficticio.\n\n"
        + rules_for_untrusted_sources()
        + "\n"
        "ESTOS SON LOS HECHOS Y ACTUADOS REALES DEL CASO — no los del ejemplo en la plantilla.\n"
    )
    fuente_parts: list[str] = [fuentes_header]
    critical_extraction_failures: list[str] = []
    noncritical_extraction_failures: list[str] = []
    if has_slots:
        from app.core.file_manager import SLOT_KEYS
        slots_budget = _slots_text_budget_chars()
        slots_used = 0
        slots_truncated = False
        for key in SLOT_KEYS:
            paths = slots.get(key, [])
            if not paths:
                continue
            label = slot_labels.get(key, key.replace("_", " ").capitalize())
            fuente_parts.append(f"\n### {label}\n")
            for p in paths:
                body = read_slot_document_text(p)
                if _slot_document_has_unusable_extraction(body):
                    item = f"{label}: {Path(p).name}"
                    if key in _CRITICAL_EXTRACTION_SLOT_KEYS:
                        critical_extraction_failures.append(item)
                    else:
                        noncritical_extraction_failures.append(item)
                # Presupuesto de tamaño: los slots críticos van primero (orden de
                # SLOT_KEYS), así que si algo se trunca son los secundarios (anexos/otros).
                remaining = slots_budget - slots_used
                if remaining <= 0:
                    fuente_parts.append(
                        f"\n[⚠️ {Path(p).name}: omitido del prompt por límite de tamaño; "
                        "el resumen de hechos aprobado por el juez ya recoge lo esencial.]\n"
                    )
                    slots_truncated = True
                    continue
                if len(body) > remaining:
                    body = body[:remaining] + "\n\n[⚠️ documento truncado por límite de tamaño del prompt]"
                    slots_truncated = True
                slots_used += len(body)
                fuente_parts.append(
                    wrap_untrusted_document(
                        Path(p).name,
                        body,
                        source_kind=f"fuente_expediente/{key}",
                    )
                )
        if slots_truncated and warnings_out is not None:
            warnings_out.append(
                "Aviso: el expediente supera el límite de tokens del modelo; se truncaron "
                "documentos secundarios (anexos/otros) en el prompt de redacción. Los hechos "
                "y las fuentes aprobados por el juez no se ven afectados."
            )
    else:
        fuente_parts.append("(No se cargaron fuentes — extrae los datos de los archivos del caso.)\n")
    blocks.append("\n".join(fuente_parts))
    if noncritical_extraction_failures and warnings_out is not None:
        warnings_out.append(
            "Advertencia: hay fuente(s) secundaria(s) sin texto local utilizable: "
            + "; ".join(noncritical_extraction_failures[:8])
            + ("…" if len(noncritical_extraction_failures) > 8 else "")
        )
    _raise_unusable_critical_sources(critical_extraction_failures)

    # ── BLOQUE 5: Bibliografía (contenido embebido, con cache) ────────────
    bib_parts: list[str] = [
        f"{SEP}\n"
        "BLOQUE 5 · BIBLIOGRAFÍA AUTORIZADA\n"
        f"{SEP}\n"
        "IMPORTANTE: Solo puedes citar jurisprudencia y doctrina que aparezca\n"
        "en estos documentos. Si un precedente no está aquí, no lo cites.\n"
        "Test de pertinencia obligatorio antes de cada cita: (1) el problema jurídico del precedente\n"
        "debe coincidir con el punto que fundamentas; (2) la ratio debe resolver ese mismo tipo de\n"
        "cuestión, no solo tratar genéricamente prisión preventiva o apelación; (3) los hechos relevantes\n"
        "no deben volver engañosa la analogía. Si falla cualquiera de esos tres filtros, omite la cita.\n"
        "No uses una casación real para una regla distinta a su ratio: por ejemplo, una casación sobre\n"
        "interés superior del niño no sustenta salud, adicciones, atención penitenciaria ni otro tema ajeno.\n"
        "La bibliografía disponible autoriza consultar; NO obliga a citar ni a adornar la resolución.\n"
        + rules_for_untrusted_sources()
    ]
    has_bib = False
    bib_budget = _bib_text_budget_chars()
    bib_used = 0
    bib_truncated = False
    if bibliografia:
        has_bib = True
        for p in bibliografia:
            txt = read_file_text(p)
            remaining = bib_budget - bib_used
            if remaining <= 0:
                bib_truncated = True
                break
            if len(txt) > remaining:
                txt = txt[:remaining] + "\n\n[⚠️ bibliografía truncada por límite de tamaño del prompt]"
                bib_truncated = True
            bib_used += len(txt)
            bib_parts.append(
                wrap_untrusted_document(
                    p.name,
                    txt,
                    source_kind="bibliografia",
                )
            )

    # Bibliografía global: solo artículos relevantes (pre-filtro Haiku)
    from app.core.file_manager import list_bibliografia_global
    from app.core.wiki_worker import extract_relevant_articles

    gfiles = list_bibliografia_global()
    if gfiles:
        arts, gwarn = extract_relevant_articles(
            delito=delito or "",
            materia=materia_label or "",
            descripcion=agravios or "",
        )
        if arts:
            has_bib = True
            remaining = bib_budget - bib_used
            if remaining > 0:
                if len(arts) > remaining:
                    arts = arts[:remaining] + "\n\n[⚠️ artículos truncados por límite de tamaño del prompt]"
                    bib_truncated = True
                bib_used += len(arts)
                bib_parts.append(
                    f"\n{SEP}\n"
                    "ARTÍCULOS DE CÓDIGOS APLICABLES AL CASO\n"
                    f"{SEP}\n"
                    + wrap_untrusted_document(
                        "articulos_codigos_global",
                        arts,
                        source_kind="bibliografia_global",
                    )
                )
            else:
                bib_truncated = True
        if gwarn and warnings_out is not None:
            warnings_out.append(gwarn)

    # Criterios consolidados del magistrado (wiki rebuild)
    from app.core.file_manager import BASE_DIR as _BASE_DIR
    _wiki_dir = _BASE_DIR / "02_wiki"
    for _wiki_file, _wiki_title in (
        (_wiki_dir / "jurisprudencia" / "jurisprudencia.md", "JURISPRUDENCIA CONSOLIDADA DEL MAGISTRADO"),
        (_wiki_dir / "conceptos" / "conceptos.md",           "CONCEPTOS JURÍDICOS CONSOLIDADOS DEL MAGISTRADO"),
    ):
        if _wiki_file.is_file():
            _txt = _wiki_file.read_text(encoding="utf-8", errors="replace").strip()
            if _txt:
                has_bib = True
                bib_parts.append(
                    f"\n{SEP}\n"
                    f"{_wiki_title}\n"
                    f"{SEP}\n"
                    "Estos son los criterios y precedentes que el magistrado aplica de forma\n"
                    "consistente. Úsalos como referencia prioritaria al fundamentar.\n\n"
                    + wrap_untrusted_document(
                        _wiki_file.name,
                        _txt,
                        source_kind="wiki_consolidada",
                    )
                )

    if not has_bib:
        # Sin esto el modelo suele inventar un «banner» tipo «no se encontró jurisprudencia guardada».
        bib_parts.append(
            "\n--- (Sin documentos de bibliografía embebidos) ---\n\n"
            "**Estado:** No hay archivos en la bibliografía de la materia activa, ni extractos útiles "
            "desde bibliografía global, ni texto en `02_wiki/jurisprudencia/jurisprudencia.md` ni en "
            "`02_wiki/conceptos/conceptos.md` que se haya podido incluir aquí.\n\n"
            "**Redacción:** Fundamenta con normas y hechos del Bloque 4 y la plantilla. "
            "Solo cita precedentes que aparezcan literalmente en la plantilla o en el Bloque 4.\n\n"
            "**Prohibido en el cuerpo del acto:** No escribas leyendas, banderolas ni avisos al estilo "
            "«No se encontró jurisprudencia guardada», «WikiJuez informa», mensajes de sistema o de "
            "aplicación; el acto debe comenzar como resolución judicial (p. ej. Vistos) sin metatexto.\n"
        )

    blocks.append("\n".join(bib_parts))

    # ── BLOQUE 6: Configuración del caso ──────────────────────────────────
    meta: list[str] = []
    if expediente: meta.append(f"- Expediente: {expediente}")
    if imputados:  meta.append(f"- Imputado(s): {imputados}")
    if delito:     meta.append(f"- Delito: {delito}")
    if agraviado:  meta.append(f"- Agraviado: {agraviado}")
    if juzgado:    meta.append(f"- Juzgado de origen: {juzgado}")
    if not meta:
        meta.append("(Extrae los metadatos de las fuentes del caso.)")

    postura_texto = _formato_postura(postura, postura_personalizada)
    ag = (agravios or "").strip()
    agravios_block = (
        f"\nAgravios a absolver (uno por párrafo):\n{ag}\n"
        if ag else
        "\nAgravios: extráelos del recurso de apelación, numéralos y absuelve cada uno.\n"
    )

    ip = (instruccion_particular or "").strip()
    ip_block = f"\nInstrucción particular de este caso:\n{ip}\n" if ip else ""

    blocks.append(
        f"{SEP}\n"
        "BLOQUE 6 · CONFIGURACIÓN DEL CASO\n"
        f"{SEP}\n"
        "Metadatos:\n" + "\n".join(meta) +
        "\n\nPostura judicial:\n" + postura_texto +
        agravios_block + ip_block +
        "\n**Nota sobre ranuras:** cualquier modo u orden solicitado ahí mismo o en "
        "la instrucción general de materia (Bloque 2) para explicitar/developar cada surco tiene "
        "**prioridad** sobre hábitos de redacción del modelo.\n"
    )

    # ── BLOQUE 7: Tarea ───────────────────────────────────────────────────
    if modo == "continuar" and borrador_path:
        tarea = (
            f"{SEP}\n"
            "BLOQUE 7 · TAREA — CONTINUAR BORRADOR\n"
            f"{SEP}\n"
            f"El magistrado inició la resolución en `{borrador_path}`.\n"
            "Formato posible: .md, .doc, .docx, .pdf o .pages (Pages: exportar a Word/PDF si no se lee).\n"
            "Busca el marcador [[CONTINUAR AQUÍ]]. Si no existe, continúa\n"
            "después del último párrafo escrito.\n"
            "NO reescribas lo que el magistrado ya escribió.\n"
            "Continúa exactamente el hilo argumentativo desarrollado.\n"
            "Al terminar guarda como versión nueva sin sobreescribir el original.\n"
        )
    else:
        tarea = (
            f"{SEP}\n"
            "BLOQUE 7 · TAREA — REDACTAR RESOLUCIÓN COMPLETA\n"
            f"{SEP}\n"
            f"Redacta la **{tipo}** completa, lista para revisión y firma:\n"
            "0. Antes de redactar, identifica en las fuentes expediente, imputado(s), delito, agraviado y "
            "   procedencia; colócalos en el encabezado previo al rótulo «Auto de Vista» o "
            "   «Sentencia de Vista», no dentro del cuerpo resolutivo.\n"
            "1. Lee ÍNTEGRAMENTE la plantilla (Bloque 3) antes de escribir. "
            "La plantilla es el modelo de EXTENSIÓN Y PROFUNDIDAD — la resolución final debe ser "
            "comparable en longitud y densidad jurídica a la plantilla, no más corta. "
            "Sigue su formato: lugar y fecha, Vistos, rótulos, orden de secciones, encabezado, "
            "cierre y firma. Cada considerando de la plantilla muestra el nivel de análisis esperado "
            "— ese mismo nivel se aplica a los hechos del caso actual.\n"
            "2. Incorpora el sustento del **Bloque 4** (PDF en surcos, recurso(s), transcripción de audio). "
            "Si el magistrado **ordenó** explicitar **cada** ranura o un **modo** concreto de exposición (Bloques 2 o 6), "
            "respétalo; si no, integra con claridad sin dejar ranuras «invisibles».\n"
            "3. Los datos procesales salen del Bloque 4 — NO uses datos del ejemplo ficticio.\n"
            "4. Aplica la postura indicada (Bloque 6) sin oscilar: si es CONFIRMAR, no redactes fallo revocatorio "
            "ni sustituyas la medida por comparecencia u otra consecuencia incompatible.\n"
            "5. En el rubro fundamentos del recurso, desarrolla CON PROFUNDIDAD COMPLETA cada agravio "
            "tal como aparece en el recurso de apelación — mínimo 3 oraciones por agravio explicando "
            "(a) qué vicio alega la defensa, (b) con qué argumento concreto lo sustenta, (c) qué "
            "consecuencia jurídica pretende. Si el agravio tiene sub-puntos (i)(ii)(iii), recógelos "
            "todos. NO reduzcas el agravio a una línea-título. Solo usa lo que consta en el recurso "
            "de apelación — no extraigas agravios de alegatos de primera instancia. Luego absuelve "
            "cada agravio en párrafo propio con la misma profundidad, sin fusionarlos ni inventar.\n"
            "5 ter. Cargos imputados por el MP: transcripción literal del escrito fiscal en solicitud_inicial; "
            "sin parafrasear, sin prueba ni valoración del a quo.\n"
        )
        if _is_prision_preventiva(folder_name, materia_label):
            tarea += (
                "5 bis. Cargos imputados: transcripción literal del requerimiento fiscal (ranura solicitud_inicial); "
                "verifica calificación completa si hay receptación agravada (art. 194 + 195 + 427 u otros).\n"
            )
        tarea += (
            "6. Cita solo jurisprudencia presente en el Bloque 5 o en la plantilla.\n"
            "   Si el Bloque 5 indica que no hay documentos adjuntos, no inventes precedentes ni "
            "abras el acto con avisos tipo «no se encontró jurisprudencia»; integra la limitación "
            "solo dentro del razonamiento si procede.\n"
            "7. Si el expediente es extenso, realiza primero mapeo interno de puntos controvertidos\n"
            "   y luego redacta la versión final sin perder profundidad.\n"
            "8. Si el magistrado lo solicita y el expediente lo permite, agrega alternativas de fallo\n"
            "   razonadas (confirmar/revocar/nulidad), claramente separadas del texto principal.\n"
            f"9. Incluye `{caso_num}` en el nombre del archivo al guardar.\n"
        )
    blocks.append(tarea)

    # ── Reglas transversales + checklist ─────────────────────────────────
    blocks.append(
        f"{SEP}\n"
        "REGLAS TRANSVERSALES\n"
        f"{SEP}\n"
        "• NUNCA inventes números de casación, folios, fechas ni nombres.\n"
        "• Si un argumento no tiene respaldo en los documentos, dilo explícitamente.\n"
        "• Fundamentos del recurso: solo argumentos del escrito de apelación; no atribuyas al recurrente "
        "expresiones que no consten allí.\n"
        "• Absolución de agravios: responde únicamente agravios del recurso de apelación; no uses alegatos "
        "finales, defensas de primera instancia ni argumentos recogidos en la sentencia como agravios si "
        "no fueron reproducidos en el recurso.\n"
        "• Postura indicada: vinculante para el proyecto principal; confirmar no puede terminar en revocar.\n"
        "• Metadatos: deben aparecer al inicio y extraerse de la documentación cuando el formulario esté incompleto.\n"
        "• Profundidad y orden por **función procesal** (documento «Estructura funcional»):\n"
        "  orden: apertura → planteamiento del caso → cargos impugnados → considerandos → costas → Resuelve;\n"
        "  apertura y cargos: cargos imputados del MP en **transcripción literal** (solicitud_inicial); "
        "planteamiento: parte dispositiva apelada + agravios (resumen fiel,\n"
        "  sin fusionar ni alterar sentido; sin agravios ficticios) + síntesis fiel de MP, civil, interrogatorio;\n"
        "  considerandos: máxima elaboración — competencia revisora, tipo literal, estándar de prueba, análisis\n"
        "  individual listado del juez a quo **y** valoración conjunta, más absolución de agravios\n"
        "  (preferencia: un considerando por agravio en orden); Resuelve: sintético.\n"
        "• Ranuras: si Bloque 2 o 6 determinan **explicitación** o **modo** de los surcos, aplícalo; no lo sustituyas por costumbre de redacción.\n"
    )
    if _is_prision_preventiva(folder_name, materia_label):
        blocks[-1] += f"\n{PP_CALIFICACION_RECEPTACION_EXTRA}\n"
    blocks.append(REGLAS_TRANSVERSALES_ANTIAI_MAGISTRADO_ES)

    return "\n".join(b for b in blocks if b)


def _formato_postura(postura: str, personalizada: str) -> str:
    p = (postura or "").strip().lower()
    if "confir" in p:
        return (
            "CONFIRMAR la resolución apelada. Valida el razonamiento del a quo;\n"
            "desestima cada agravio argumentativamente. La parte resolutiva debe confirmar;\n"
            "no revoques, no reformes ni sustituyas la medida por comparecencia u otra consecuencia incompatible."
        )
    if p == "revocar" or ("revo" in p and "parcial" not in p):
        return (
            "REVOCAR la resolución apelada. Identifica los errores del a quo\n"
            "y construye el razonamiento inverso."
        )
    if "parcial" in p or "modific" in p:
        return (
            "REVOCAR PARCIALMENTE / MODIFICAR la resolución apelada.\n"
            "Precisa qué extremos se mantienen y cuáles se modifican."
        )
    extra = (personalizada or "").strip()
    return f"OTROS — instrucciones del magistrado:\n{extra}" if extra else f"{postura}."


# ---------------------------------------------------------------------------
# PDF nativos en Messages API (además de extracción local en el prompt)
# ---------------------------------------------------------------------------

def _env_api_pdf_attach_enabled() -> bool:
    return os.environ.get("ADIUTOR_API_PDF_ATTACH", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def _env_api_pdf_max_total_bytes() -> int:
    try:
        mb = float(os.environ.get("ADIUTOR_API_PDF_MAX_TOTAL_MB", "22"))
        return int(max(1.0, mb) * 1024 * 1024)
    except ValueError:
        return 22 * 1024 * 1024


def _env_api_pdf_auto_skip_total_bytes() -> int:
    """
    Umbral preventivo: si los PDF candidatos superan este total, no se envían como
    documentos nativos porque Anthropic puede tokenizarlos por encima de 1M tokens.

    Valor 0 desactiva este seguro. Default conservador: 6 MB.
    """
    try:
        mb = float(os.environ.get("ADIUTOR_API_PDF_AUTO_SKIP_TOTAL_MB", "6"))
    except ValueError:
        mb = 6.0
    if mb <= 0:
        return 0
    return int(max(1.0, mb) * 1024 * 1024)


def _env_api_pdf_max_files() -> int:
    try:
        return max(1, min(50, int(os.environ.get("ADIUTOR_API_PDF_MAX_FILES", "20"))))
    except ValueError:
        return 20


def collect_pdf_paths_for_api_attachment(prompt_kwargs: dict) -> list[Path]:
    """Rutas PDF únicas desde ranuras del expediente y bibliografía del prompt enriquecido."""
    seen: set[str] = set()
    out: list[Path] = []
    slots = prompt_kwargs.get("slots") or {}
    if isinstance(slots, dict):
        for paths in slots.values():
            for p in paths or []:
                pp = Path(p)
                if pp.suffix.lower() != ".pdf" or not pp.is_file():
                    continue
                try:
                    key = str(pp.resolve())
                except OSError:
                    key = str(pp)
                if key in seen:
                    continue
                seen.add(key)
                out.append(pp)
    for p in prompt_kwargs.get("bibliografia") or []:
        pp = Path(p)
        if pp.suffix.lower() != ".pdf" or not pp.is_file():
            continue
        try:
            key = str(pp.resolve())
        except OSError:
            key = str(pp)
        if key in seen:
            continue
        seen.add(key)
        out.append(pp)
    return out


def build_resolution_user_message_content(
    prompt_text: str,
    prompt_kwargs: dict,
    *,
    warnings_out: list[str] | None = None,
) -> str | list[dict | str]:
    """
    Construye el contenido del primer mensaje ``user`` para la API.

    Prioridad:
    1) Si ``ADIUTOR_API_PDF_ATTACH`` está activo: adjunta PDF como bloques ``document`` en base64
       (además del texto largo del prompt con extracción local).
    2) Si no, y ``ADIUTOR_VISION_PDF_PAGES`` > 0: prototipo — primeras páginas del primer PDF como
       imágenes PNG (ver ``pdf_vision_pages``).
    3) Si no: solo texto.

    Desactivar adjuntos PDF: ``ADIUTOR_API_PDF_ATTACH=0``.
    """
    from app.core.pdf_vision_pages import (
        anthropic_image_blocks_from_pngs,
        env_vision_pdf_pages,
        render_pdf_pages_to_png_bytes,
    )

    if _env_api_pdf_attach_enabled():
        if env_vision_pdf_pages() > 0 and warnings_out is not None:
            warnings_out.append(
                "Visión por páginas (ADIUTOR_VISION_PDF_PAGES) omitida: activo adjunto PDF nativo "
                "(ADIUTOR_API_PDF_ATTACH)."
            )
        pdfs = collect_pdf_paths_for_api_attachment(prompt_kwargs)
        if not pdfs:
            return prompt_text

        candidate_sizes: list[tuple[Path, int]] = []
        candidate_total = 0
        unreadable: list[str] = []
        for p in pdfs:
            try:
                sz = Path(p).stat().st_size
            except OSError as e:
                unreadable.append(f"{Path(p).name}: {e}")
                continue
            candidate_sizes.append((Path(p), sz))
            candidate_total += sz

        auto_skip = _env_api_pdf_auto_skip_total_bytes()
        if auto_skip and candidate_total > auto_skip:
            if warnings_out is not None:
                mb_total = candidate_total / (1024 * 1024)
                mb_limit = auto_skip / (1024 * 1024)
                largest = sorted(candidate_sizes, key=lambda x: x[1], reverse=True)[:3]
                detail = "; ".join(
                    f"{p.name} ~{sz / (1024 * 1024):.1f} MB" for p, sz in largest
                )
                warnings_out.append(
                    "PDF en API omitido automáticamente: los PDF candidatos suman "
                    f"~{mb_total:.1f} MB y superan el umbral seguro ~{mb_limit:.1f} MB "
                    "(ADIUTOR_API_PDF_AUTO_SKIP_TOTAL_MB). Se usará el texto extraído local "
                    "para evitar errores de Anthropic por prompt > 1M tokens."
                    + (f" Archivos mayores: {detail}." if detail else "")
                )
                if unreadable:
                    warnings_out.append(
                        "PDF en API: no se pudo medir " + "; ".join(unreadable[:4])
                    )
            return prompt_text

        max_total = _env_api_pdf_max_total_bytes()
        max_files = _env_api_pdf_max_files()
        used = 0
        doc_blocks: list[dict] = []
        skipped: list[str] = []

        for p in pdfs[:max_files]:
            try:
                raw = Path(p).read_bytes()
            except OSError as e:
                skipped.append(f"{Path(p).name}: {e}")
                continue
            sz = len(raw)
            if sz > max_total:
                skipped.append(f"{Path(p).name}: supera solo el cupo total ({max_total // (1024 * 1024)} MB)")
                continue
            if used + sz > max_total:
                skipped.append(
                    f"{Path(p).name}: cupo API de PDFs agotado (~{used // (1024 * 1024)} MB de ~{max_total // (1024 * 1024)} MB)"
                )
                continue
            used += sz
            b64 = base64.standard_b64encode(raw).decode("ascii")
            doc_blocks.append(
                {
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": "application/pdf",
                        "data": b64,
                    },
                }
            )

        if not doc_blocks:
            if skipped and warnings_out is not None:
                warnings_out.append(
                    "PDF en API: no se adjuntó ningún archivo (" + "; ".join(skipped[:6]) + ")."
                )
            return prompt_text

        preamble = (
            "A continuación hay uno o más PDF en formato nativo de la API de Anthropic "
            "(el servicio los procesa con capacidad visual sobre el documento). "
            "El mismo material ya consta como texto extraído en el mensaje largo que sigue; "
            "use ambas representaciones para mayor fidelidad (manuscritos, sellos, tablas escaneadas).\n\n"
        )
        content: list[dict | str] = [{"type": "text", "text": preamble}]
        content.extend(doc_blocks)
        content.append({"type": "text", "text": prompt_text})

        if skipped and warnings_out is not None:
            warnings_out.append(
                f"PDF en API: adjuntos {len(doc_blocks)} archivo(s), ~{used // (1024 * 1024)} MB. "
                "Omitidos: " + "; ".join(skipped[:8])
                + ("…" if len(skipped) > 8 else "")
            )
        return content

    n_pages = env_vision_pdf_pages()
    if n_pages > 0:
        pdfs = collect_pdf_paths_for_api_attachment(prompt_kwargs)
        if pdfs:
            pngs = render_pdf_pages_to_png_bytes(pdfs[0], max_pages=n_pages)
            if pngs:
                img_blocks = anthropic_image_blocks_from_pngs(pngs)
                preamble = (
                    f"Las siguientes {len(img_blocks)} imagen(es) son las primeras páginas del PDF "
                    f"«{pdfs[0].name}» (render local a PNG; prototipo ADIUTOR_VISION_PDF_PAGES). "
                    "El prompt completo con texto extraído en esta máquina sigue al final. "
                    "Use imágenes y texto para redactar.\n\n"
                )
                out: list[dict | str] = [{"type": "text", "text": preamble}]
                out.extend(img_blocks)
                out.append({"type": "text", "text": prompt_text})
                if warnings_out is not None:
                    warnings_out.append(
                        f"Visión por páginas: {len(img_blocks)} PNG del PDF «{pdfs[0].name}» "
                        "(coste alto en tokens; desactive con ADIUTOR_VISION_PDF_PAGES=0)."
                    )
                return out
            if warnings_out is not None:
                warnings_out.append(
                    f"ADIUTOR_VISION_PDF_PAGES={n_pages}: no se pudieron renderizar páginas de «{pdfs[0].name}» "
                    "(¿PyMuPDF instalado? ¿PDF cifrado?)."
                )

    return prompt_text


# ---------------------------------------------------------------------------
# Worker thread principal
# ---------------------------------------------------------------------------

class ClaudeWorker(QThread):
    """
    Hilo que lee archivos, arma el prompt y llama a Claude API con streaming.

    Señales:
      chunk_ready(str)   — fragmento de texto recibido
      status(str)        — mensaje de progreso
      finished()         — generación completada
      error_occurred(str)— mensaje de error
    """

    chunk_ready    = pyqtSignal(str)
    status         = pyqtSignal(str)
    finished       = pyqtSignal()
    error_occurred = pyqtSignal(str)

    def __init__(self, task: dict, parent=None):
        super().__init__(parent)
        self.task = task
        self._cancelled = False
        self.built_prompt: str = ""
        self.last_built_prompt: str = ""
        self.last_initial_user_content: str | list = ""
        self.last_generation_outcome: GenerationOutcome | None = None

    def cancel(self):
        self._cancelled = True

    def run(self):
        self.last_generation_outcome = None
        self.last_initial_user_content = ""
        try:
            self.status.emit("Leyendo documentos del expediente…")
            gen_warn: list[str] = []
            prompt = build_enriched_prompt(
                **self.task["prompt_kwargs"],
                warnings_out=gen_warn,
            )
            for w in gen_warn:
                self.status.emit(w)
            if self._cancelled:
                co = GenerationOutcome(cancelled=True)
                self.last_generation_outcome = co
                self.finished.emit()
                return
            self.built_prompt = prompt
            self.last_built_prompt = prompt
            pdf_warn: list[str] = []
            self.last_initial_user_content = build_resolution_user_message_content(
                prompt,
                self.task["prompt_kwargs"],
                warnings_out=pdf_warn,
            )
            for w in pdf_warn:
                self.status.emit(w)
            self.status.emit("Conectando con Claude API…")
            self._stream_anthropic(
                [{"role": "user", "content": self.last_initial_user_content}],
            )
            self.finished.emit()
        except Exception as exc:
            self.error_occurred.emit(str(exc))

    def _stream_anthropic(self, messages: list[dict]) -> GenerationOutcome | None:
        try:
            import anthropic
        except ImportError:
            raise RuntimeError(
                "El paquete 'anthropic' no está instalado.\n"
                "Ejecuta:  pip install anthropic"
            )

        api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError(
                "No se encontró ANTHROPIC_API_KEY.\n"
                "Configúrala con:  export ANTHROPIC_API_KEY=sk-ant-…"
            )

        client = anthropic.Anthropic(api_key=api_key)
        system_msg = build_resolution_system_blocks()
        mtu = resolution_max_output_tokens()
        errors: list[str] = []
        max_attempts = resolution_stream_max_attempts()

        for model in resolution_model_candidates():
            for attempt in range(max_attempts):
                if self._cancelled:
                    out = GenerationOutcome(cancelled=True, model_used=model)
                    self.last_generation_outcome = out
                    return out
                if attempt == 0:
                    self.status.emit(f"Generando resolución con Claude ({model})…")
                else:
                    delay = resolution_stream_retry_delay_sec(attempt)
                    self.status.emit(
                        f"{model}: fallo temporal del servidor — reintento "
                        f"{attempt + 1}/{max_attempts} (espera ~{delay:.0f}s)…"
                    )
                    if not _interruptible_sleep(delay, lambda: self._cancelled):
                        out = GenerationOutcome(cancelled=True, model_used=model)
                        self.last_generation_outcome = out
                        return out
                try:
                    parts, fm, cancelled_stream = consume_claude_messages_stream_once(
                        client,
                        model=model,
                        max_tokens=mtu,
                        system=system_msg,
                        messages=messages,
                        cancelled_fn=lambda: self._cancelled,
                        chunk_emit=self.chunk_ready.emit,
                    )
                    if cancelled_stream:
                        out = GenerationOutcome(cancelled=True, model_used=model)
                        self.last_generation_outcome = out
                        return out
                    sr = getattr(fm, "stop_reason", None)
                    body = "".join(parts)
                    mx = sr == "max_tokens"
                    susp = resolution_lacks_closing_heuristic(body)
                    out = GenerationOutcome(
                        cancelled=False,
                        stop_reason=sr,
                        model_used=model,
                        max_tokens_truncation=mx,
                        suspicious_missing_cierre=susp,
                    )
                    self.last_generation_outcome = out
                    return out
                except Exception as e:
                    detail = format_anthropic_stream_exception(e)
                    if attempt < max_attempts - 1 and anthropic_stream_error_retryable(e):
                        short = detail.replace("\n", " ").strip()
                        if len(short) > 170:
                            short = short[:167] + "…"
                        self.status.emit(f"{model}: error reintentable — {short}")
                        continue
                    errors.append(f"{model}: {detail}")
                    break

        raise RuntimeError(
            "No se pudo generar la resolución con ningún modelo configurado:\n"
            + "\n".join(errors)
        )


class ResolutionContinuationWorker(QThread):
    """Segunda llamada en contexto multiturn para completar acto cortado por max_tokens u omisiones."""

    chunk_ready = pyqtSignal(str)
    status = pyqtSignal(str)
    finished = pyqtSignal()
    error_occurred = pyqtSignal(str)

    def __init__(
        self,
        *,
        initial_user_content: str | list,
        assistant_partial: str,
        parent=None,
    ):
        super().__init__(parent)
        self.initial_user_content = initial_user_content
        self.assistant_partial = assistant_partial or ""
        self._cancelled = False
        self.last_generation_outcome: GenerationOutcome | None = None

    def cancel(self):
        self._cancelled = True

    def run(self):
        self.last_generation_outcome = None
        api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if not api_key:
            self.error_occurred.emit(
                "No se encontró ANTHROPIC_API_KEY para continuar la resolución."
            )
            return
        try:
            import anthropic

            c0 = self.initial_user_content
            if isinstance(c0, str):
                if not c0.strip():
                    self.error_occurred.emit(
                        "No hay contenido user inicial para continuar (prompt vacío)."
                    )
                    return
            elif isinstance(c0, list):
                if not c0:
                    self.error_occurred.emit(
                        "No hay contenido user inicial para continuar (lista vacía)."
                    )
                    return
            else:
                self.error_occurred.emit("Contenido user inicial inválido.")
                return

            msgs: list[dict] = [
                {"role": "user", "content": self.initial_user_content},
                {
                    "role": "assistant",
                    "content": [{"type": "text", "text": self.assistant_partial}],
                },
                {"role": "user", "content": _CONTINUATION_USER_ES},
            ]
            mtu = resolution_max_output_tokens()

            errors: list[str] = []
            max_attempts = resolution_stream_max_attempts()

            client = anthropic.Anthropic(api_key=api_key)
            system_msg = build_resolution_system_blocks()

            for model in resolution_model_candidates():
                for attempt in range(max_attempts):
                    if self._cancelled:
                        self.last_generation_outcome = GenerationOutcome(
                            cancelled=True,
                            model_used=model,
                        )
                        self.finished.emit()
                        return
                    if attempt == 0:
                        self.status.emit(f"Continuando acto con Claude ({model})…")
                    else:
                        delay = resolution_stream_retry_delay_sec(attempt)
                        self.status.emit(
                            f"{model}: fallo temporal — continuación reintento "
                            f"{attempt + 1}/{max_attempts} (~{delay:.0f}s)…"
                        )
                        if not _interruptible_sleep(delay, lambda: self._cancelled):
                            self.last_generation_outcome = GenerationOutcome(
                                cancelled=True,
                                model_used=model,
                            )
                            self.finished.emit()
                            return
                    try:
                        parts, fm, cancelled_stream = consume_claude_messages_stream_once(
                            client,
                            model=model,
                            max_tokens=mtu,
                            system=system_msg,
                            messages=msgs,
                            cancelled_fn=lambda: self._cancelled,
                            chunk_emit=self.chunk_ready.emit,
                        )
                        if cancelled_stream:
                            self.last_generation_outcome = GenerationOutcome(
                                cancelled=True,
                                model_used=model,
                            )
                            self.finished.emit()
                            return
                        sr = getattr(fm, "stop_reason", None)
                        appended = "".join(parts)
                        combined = self.assistant_partial + appended
                        mx = sr == "max_tokens"
                        susp = resolution_lacks_closing_heuristic(combined)
                        self.last_generation_outcome = GenerationOutcome(
                            cancelled=False,
                            stop_reason=sr,
                            model_used=model,
                            max_tokens_truncation=mx,
                            suspicious_missing_cierre=susp,
                        )
                        self.finished.emit()
                        return
                    except Exception as e:
                        detail = format_anthropic_stream_exception(e)
                        if attempt < max_attempts - 1 and anthropic_stream_error_retryable(e):
                            short = detail.replace("\n", " ").strip()
                            if len(short) > 170:
                                short = short[:167] + "…"
                            self.status.emit(f"{model}: error reintentable — {short}")
                            continue
                        errors.append(f"{model}: {detail}")
                        break

            raise RuntimeError(
                "Continuación: ningún modelo respondió:\n" + "\n".join(errors)
            )
        except Exception as exc:
            self.error_occurred.emit(str(exc))


# ---------------------------------------------------------------------------
# Worker de iteración — aplica modificaciones del magistrado
# ---------------------------------------------------------------------------

_ITER_IG_MAX = 14000  # caracteres máx. de instrucción general incrustada
_ITER_JURIS_ANCHOR_MAX = 5200  # tope para extractos del acto + fichas wiki en iteración
_ITER_WIKI_FICHA_MAX_EACH = 2000
_ITER_BIB_REINJECT_TOTAL_MAX = 14000
_ITER_BIB_REINJECT_EACH_MAX = 4500

JURIS_QUICK_NOTE_TEMPLATE_MD = """## [STC | Casación | …] [referencia oficial completa del expediente]

- Tribunal:
- Fecha:
- Materia en una línea:
- Fuente: [URL o nombre del PDF en bibliografía]

**Problema jurídico:** …

**Ratio (síntesis):**
…

**Encaje con el caso (opcional):** …

**Extracto reproducible (solo si habrá cita literal):**
«…»
"""


def build_iteration_bibliografia_reinject_block(
    act_text: str,
    materia_slug: str,
    mode: str,
) -> str:
    """
    Extractos de `01_raw/bibliografia/` opcionales en iteración.

    ``mode``: ``off`` cadena vacía; ``matched`` sólo archivos cuyo nombre coincide con
    expedientes detectados en el acto; ``full`` toda la bibliografía de materia más global
    con cupos por archivo y total.
    """
    m = (mode or "").strip().lower()
    if m in ("", "off", "none", "no", "false"):
        return ""
    if m not in ("matched", "full"):
        m = "matched"

    from app.core.file_manager import MATERIA_SLUGS, list_bibliografia, list_bibliografia_global

    ms = (materia_slug or "").strip()
    paths: list[Path] = []
    if ms in MATERIA_SLUGS:
        paths.extend(list_bibliografia(ms))
    paths.extend(list_bibliografia_global())

    seen: set[str] = set()
    uniq: list[Path] = []
    for p in paths:
        try:
            key = str(p.resolve())
        except OSError:
            key = str(p)
        if key not in seen:
            seen.add(key)
            uniq.append(p)

    if m == "matched":
        needles = _expediente_tokens_from_act(act_text)
        if not needles:
            return (
                "\n### Reinyección de bibliografía (solo coincidentes)\n\n"
                "_No se detectaron en el acto patrones de expediente (p. ej. 01421-2023); "
                "no se pudo filtrar por nombre de archivo. Use el modo «completa» o incluya "
                "números de expediente en el texto del acto._\n\n"
            )
        targets = [
            p
            for p in uniq
            if any(_needle_in_biblio_filename(n, p.name) for n in needles)
        ]
        sub = "solo archivos cuyo nombre coincide con expedientes detectados en el acto"
        if not targets:
            return (
                "\n### Reinyección de bibliografía (solo coincidentes)\n\n"
                "_Ningún archivo en bibliografía tiene un nombre que encaje con los "
                "expedientes detectados en el acto._\n\n"
            )
    else:
        targets = uniq
        sub = "bibliografía de la materia activa más carpeta global"

    if not targets:
        return (
            "\n### Reinyección de bibliografía\n\n"
            "_No hay archivos en `01_raw/bibliografia/` para esta materia ni en global._\n\n"
        )

    header = (
        f"\n### Extracto de bibliografía reinyectado ({sub})\n\n"
        "Texto leído desde `01_raw/bibliografia/`. Úselo junto con el acto y las instrucciones; "
        "no invente otros precedentes.\n\n"
    )
    parts: list[str] = [header]
    remaining = max(0, _ITER_BIB_REINJECT_TOTAL_MAX - len(header))
    nf = len(targets)
    per_file = min(_ITER_BIB_REINJECT_EACH_MAX, max(900, remaining // max(1, nf)))

    for p in targets:
        if remaining < 350:
            parts.append(
                "\n_(…cupo de reinyección agotado; quedan archivos en bibliografía sin volcar.)_\n"
            )
            break
        try:
            body = read_file_text(p)
        except Exception as exc:
            body = f"[Error leyendo {p.name}: {exc}]"
        cap = min(per_file, max(400, remaining - 60))
        snippet = _truncate_for_prompt(body, cap)
        block = f"#### {p.name}\n{snippet}\n\n"
        if len(block) > remaining:
            snippet2 = _truncate_for_prompt(body, max(200, remaining - 80))
            block = f"#### {p.name}\n{snippet2}\n\n"
        parts.append(block)
        remaining -= len(block)

    return "".join(parts)


def _norm_hyphens(s: str) -> str:
    return (
        (s or "")
        .replace("\u2011", "-")
        .replace("\u2013", "-")
        .replace("\u2014", "-")
        .replace("–", "-")
        .replace("‑", "-")
    )


_CIT_SEARCH = re.compile(
    r"(?is)"
    r"\bSTC\b|STC\s+Exp|"
    r"PHC\s*/\s*TC|PA\s*/\s*TC|CV\s*/\s*TC|"
    r"Exp\.?\s*N\.?\s*°?\s*[\d\w\-]{3,}|"
    r"Casaci[oó]n(?:\s+Penal)?\s+N\.?\s*°?\s*[\d\-]|"
    r"Acuerdo\s+Plenario\s+N\.?\s*°?\s*[\d\-]|"
    r"\bRTC\s+N\.?\s*°?\s*[\d\-]|"
    r"\bRN\s+N\.?\s*°?\s*[\d\w\-]+|"
    r"Corte\s+(?:Interamericana|IDH)|"
    r"\b\d{4,5}-\d{4}-[A-Z]{2,}(?:/[A-Z]{2,})?\b"
)


def _uniq_preserve(xs: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in xs:
        k = x.strip().lower()
        if not k or k in seen:
            continue
        seen.add(k)
        out.append(x.strip())
    return out


def _paragraphs_touching_juris(act: str) -> list[str]:
    paras = re.split(r"\n\s*\n+", act or "")
    out: list[str] = []
    for p in paras:
        pt = p.strip()
        if not pt or len(pt) > 6000:
            continue
        if _CIT_SEARCH.search(pt):
            out.append(_truncate_for_prompt(pt, 760))
    return _uniq_preserve(out)


def _snippets_around_cit_matches(act: str, *, max_snips: int = 14) -> list[str]:
    t = act or ""
    out: list[str] = []
    for m in _CIT_SEARCH.finditer(t):
        start = max(0, m.start() - 180)
        end = min(len(t), m.end() + 380)
        sn = _norm_hyphens(t[start:end]).strip()
        sn = " ".join(sn.split())
        if sn:
            out.append(sn)
        if len(out) >= max_snips:
            break
    return _uniq_preserve(out)


def _expediente_tokens_from_act(act: str) -> list[str]:
    """Fragmentos tipo 03689-2013-PHC/TC para cruzar con nombres de fichas .md."""
    t = _norm_hyphens(act or "")
    toks: list[str] = []
    for pat in (
        r"\b\d{4,5}-\d{4}-[A-Za-z]{2,}(?:/[A-Za-z]{2,})?\b",
        r"\b\d{4,5}-\d{4}\b",
    ):
        for m in re.finditer(pat, t):
            toks.append(m.group(0))
    return _uniq_preserve(toks)[:32]


def _needle_in_biblio_filename(needle: str, filename: str) -> bool:
    """True si `needle` (expediente) parece estar representado en el nombre de ficha."""
    n = "".join(c for c in needle.upper() if c.isalnum())
    fb = "".join(c for c in filename.upper() if c.isalnum())
    return len(n) >= 9 and n in fb


def _collect_wiki_fichas_for_act(materia_slug: str, act: str) -> list[Path]:
    from app.core.file_manager import MATERIA_SLUGS, dir_bibliografia_global_wiki, dir_bibliografia_wiki

    needles = _expediente_tokens_from_act(act)
    if not needles:
        return []

    roots: list[Path] = []
    if materia_slug and materia_slug in MATERIA_SLUGS:
        mw = dir_bibliografia_wiki(materia_slug)
        if mw.is_dir():
            roots.append(mw)
    gw = dir_bibliografia_global_wiki()
    if gw.is_dir():
        roots.append(gw)

    picked: list[Path] = []
    seen: set[str] = set()
    for base in roots:
        for fp in base.rglob("*.md"):
            if not fp.is_file() or fp.name.startswith("."):
                continue
            if fp.name in seen:
                continue
            for nd in needles:
                if _needle_in_biblio_filename(nd, fp.name):
                    seen.add(fp.name)
                    picked.append(fp)
                    break
            if len(picked) >= 14:
                return picked
    return picked


def build_iteration_juris_anchor_block(act_text: str, materia_slug: str = "") -> str:
    """
    Contexto reinyectado en iteración/corrección: párrafos del acto donde ya aparece
    jurisprudencia y, si aplica, extractos de fichas 02_wiki/bibliografia que casen
    con expedientes citados (no sustituye el Bloque 5 completo de la primera generación).
    """
    act = (act_text or "").strip()
    if not act:
        return ""

    paras = _paragraphs_touching_juris(act)
    if not paras:
        paras = _snippets_around_cit_matches(act)

    fichas = _collect_wiki_fichas_for_act((materia_slug or "").strip(), act)

    parts: list[str] = []
    budget = _ITER_JURIS_ANCHOR_MAX

    if paras:
        head = (
            "### Ancla · precedentes ya presentes en el acto\n\n"
            "Fragmentos **extraídos automáticamente** del TEXTO ACTUAL (párrafos donde aparecen "
            "STC, expediente del TC, casación u otro precedente típico). "
            "**Reutilízalos** al fundamentar en esta iteración; **no** añadas STC/AP/casaciones "
            "que no figuren aquí ni en tus instrucciones.\n\n"
        )
        body_lines: list[str] = []
        for i, pg in enumerate(paras, start=1):
            chunk = f"**[{i}]** {pg}\n"
            if len(head) + sum(len(x) for x in body_lines) + len(chunk) > budget:
                body_lines.append("_(…hay más párrafos citados en el acto…)_\n")
                break
            body_lines.append(chunk)
        parts.append(head + "".join(body_lines))
        budget = max(0, _ITER_JURIS_ANCHOR_MAX - sum(len(p) for p in parts))

    if fichas and budget > 400:
        sec_prefix = (
            "\n\n### Ancla · fichas de biblioteca (wiki) vinculadas a expedientes detectados\n\n"
            "Extractos **cortos** de `02_wiki/bibliografia/` cuyo nombre coincide con un "
            "expediente citado en el acto. Usa solo esto (más instrucciones y el acto) como "
            "respaldo de contenido; no inventes otras sentencias.\n\n"
        )
        room = budget - len(sec_prefix)
        if room > 350:
            acc: list[str] = [sec_prefix]
            used = len(sec_prefix)
            per = min(_ITER_WIKI_FICHA_MAX_EACH, max(600, room // max(1, len(fichas))))
            for fp in fichas:
                if used >= budget - 40:
                    break
                try:
                    raw = read_file_text(fp)
                except Exception as exc:
                    raw = f"[No se pudo leer {fp.name}: {exc}]"
                cap = min(per, max(200, budget - used - 60))
                snippet = _truncate_for_prompt(raw, cap)
                block = f"#### {fp.name}\n{snippet}\n\n"
                acc.append(block)
                used += len(block)
            parts.append("".join(acc))

    if not parts:
        return (
            "### Ancla de jurisprudencia\n\n"
            "No se detectaron en el acto referencias claras a STC, expediente del TC, casación u "
            "AP (patrón automático). **No inventes precedentes.** Si debe citarse uno, transcribe "
            "el dato íntegro en la instrucción de esta iteración o agrégalo primero en el texto del acto.\n\n"
        )

    return "".join(parts)


def _truncate_for_prompt(s: str, max_chars: int) -> str:
    s = (s or "").strip()
    if not s:
        return ""
    if len(s) <= max_chars:
        return s
    return s[:max_chars].rstrip() + "\n\n[…texto truncado por límite de contexto…]"


class _IterWorker(QThread):
    """
    Dos modos:

    - ``solo_correcciones``: solo el texto nuevo o revisado correspondiente al punto o puntos pedidos,
      sin volcar de nuevo todo el acto (predeterminado).
    - ``resolucion_completa``: un acto íntegro consolidado tras varias correcciones parciales
      u orientaciones locales (solo cuando explícitamente se pide mediante el botón de la interfaz).

    Prioridad ligera a las anotaciones en el texto: sin la redacción completa repetida cuando no conviene.

    Distinto del ``finished()`` nativo de QThread para evitar sombras/confusión entre señales.
    """
    chunk_ready = pyqtSignal(str)
    iteration_finished = pyqtSignal()
    error_occurred = pyqtSignal(str)
    status = pyqtSignal(str)

    def __init__(
        self,
        *,
        texto: str,
        instruccion_iter: str,
        api_key: str,
        instruccion_general: str = "",
        instruccion_particular_caso: str = "",
        materia_label_txt: str = "",
        materia_slug: str = "",
        bib_reinject_mode: str = "off",
        iteration_mode: str = "solo_correcciones",
        parent=None,
    ):
        super().__init__(parent)
        self.texto = texto
        self.instruccion_iter = instruccion_iter
        self.instruccion_general = instruccion_general
        self.instruccion_particular_caso = instruccion_particular_caso
        self.materia_label_txt = materia_label_txt
        self.materia_slug = (materia_slug or "").strip()
        br = (bib_reinject_mode or "off").strip().lower()
        self.bib_reinject_mode = br if br in ("off", "matched", "full") else "off"
        self.iteration_mode = iteration_mode if iteration_mode == "resolucion_completa" else "solo_correcciones"
        self.api_key = api_key
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            import anthropic

            client = anthropic.Anthropic(api_key=self.api_key)

            ig = _truncate_for_prompt(self.instruccion_general, _ITER_IG_MAX)
            ipc = _truncate_for_prompt(self.instruccion_particular_caso, 8000)
            it = (self.instruccion_iter or "").strip()
            ml = (self.materia_label_txt or "").strip()

            iter_block = (
                it
                if it
                else (
                    "(El magistrado no escribió texto en el cuadro de iteración; "
                    "usa solo las anotaciones o marcas en el TEXTO ACTUAL DEL ACTO, si existen.)"
                )
            )

            if ml:
                mat_line = f"**Materia activa:** {ml}\n\n"
            else:
                mat_line = ""

            anchor_md = build_iteration_juris_anchor_block(self.texto, self.materia_slug).strip()
            if anchor_md:
                anchor_md = anchor_md + "\n\n"

            bib_extra = build_iteration_bibliografia_reinject_block(
                self.texto, self.materia_slug, self.bib_reinject_mode
            ).strip()
            if bib_extra:
                bib_extra = bib_extra + "\n\n"

            base_context = (
                "Eres el asistente jurídico del magistrado de la Sala Superior Penal de Apelaciones.\n\n"
                "## Prioridad de instrucciones (de mayor a menor)\n"
                "1. Instrucciones del cuadro de **esta iteración**.\n"
                "2. Instrucción **particular persistente** de este caso (formulario).\n"
                "3. Reglas generales institucionales transversales.\n"
                "4. Instrucción **general de la materia** (archivo permanente).\n"
                "5. Marcas/anotaciones en el propio texto (paréntesis, tachado, MAYÚSCULAS, [notas]).\n\n"
                + rules_for_untrusted_sources()
                + f"{mat_line}"
                f"{_block_parametros_institucionales_peru()}\n"
                "### Instrucción general de la materia (orientación)\n"
                f"{ig if ig else '(No cargada en pantalla.)'}\n\n"
                "### Instrucción particular de este caso (persistente)\n"
                f"{ipc if ipc else '(Ninguna.)'}\n\n"
                "### Instrucción de esta solicitud\n"
                f"{iter_block}\n\n"
                f"{anchor_md}"
                f"{bib_extra}"
                "---\n\n"
                "### TEXTO ACTUAL DEL ACTO (puede llevar histórico, separadores entre versiones o apuntes puntuales)\n\n"
                + wrap_untrusted_document(
                    "acto_actual",
                    self.texto,
                    source_kind="acto_borrador",
                )
            )

            # La iteración no reenvía bibliografía/plantilla embebida: sin este candado el modelo tiende a
            # «inventar» STC plausibles o a corromper numeración (p. ej. fragmentos tipo «issued»).
            citation_guard = (
                "\n\n## Límites sobre jurisprudencia y citas (obligatorio)\n"
                "- **Prohibido** inventar números de expediente del TC, Casación o Acuerdo Plenario, "
                "ni fundamentos inexistentes.\n"
                "- **Solo** incorpora STC/casación/AP si ya figuran **explícitamente** en el TEXTO ACTUAL DEL ACTO, "
                "en el bloque «Ancla · precedentes / fichas» que va arriba del acto en este mensaje, "
                "en el bloque «Extracto de bibliografía reinyectado» si aparece, "
                "o si el magistrado las transcribe en la instrucción de esta iteración "
                "(o en instrucciones del bloque superior).\n"
                "- Si piden «fundamentar más», «reforzar con jurisprudencia» o similar y **no** hay precedente "
                "identificable en ese material, **no** rellenes con sentencias genéricas: señala la laguna en una línea "
                "y usa `[CITA PENDIENTE DE VERIFICACIÓN]` donde iría la cita.\n"
                "- Redacción **solo en español** procesal; no insertes palabras sueltas en inglés. "
                "Verifica que cada cita tenga numeración completa y legible (p. ej. STC Exp. N.° …), sin trozos "
                "como «N.° 00» ni caracteres basura.\n"
            )
            base_ctx = base_context + citation_guard

            if self.iteration_mode == "solo_correcciones":
                prompt = (
                    base_ctx
                    + "\n\n## Objetivo de ESTA SOLICITUD (modo puntual — obligatorio)\n"
                      "NO entregues de nuevo todo el auto o sentencia íntegra salvo que el magistrado haya pedido "
                      "explícitamente un repaso total en el cuadro de iteración.\n\n"
                      "Devuelve **únicamente** lo que se necesita para atender la petición concreta:\n"
                      "- Si pide corregir un apartado, un fundamento, un párrafo o un inciso: devuelve **solo** "
                      "el texto sustituto o la redacción nueva de ese bloque (puedes titularlo con una línea breve, "
                      "p. ej. «Sustituto — [sección o tema]»).\n"
                      "- Si pide varios puntos: enumera **solo** esas correcciones, cada una claramente delimitada.\n"
                      "- Si la petición es puramente conceptual (p. ej. «¿cómo citar Cas. X?»), responde de forma breve "
                      "y aplicable al acto, sin volcar el acto completo.\n\n"
                      "### Prohibido en este modo\n"
                      "- No repitas por completo secciones extensas del acto que **no** estén en el encargo.\n"
                      "- No antepongas frases de cortesía («Claro», «Aquí tienes el acto actualizado»).\n\n"
                      "### Salida\n"
                      "Solo el texto pedido (correcciones y, si aplica, títulos mínimos de referencia). "
                      "Si no hay nada que cambiar según el encargo, indícalo en una o dos líneas.\n"
                )
                system_txt = (
                    ITER_WORKER_SYSTEM_PREFIX_ES
                    + system_injection_guard_es()
                    + "\n\nModo correcciones puntuales: no entregues el acto judicial completo salvo orden explícita "
                    "en la instrucción de iteración. Sé conciso."
                )
                max_tokens_iter = min(12000, resolution_max_output_tokens())
            else:
                prompt = (
                    "## Objetivo (modo acto íntegro consolidado)\n\n"
                    + base_ctx
                    + "\n\nEl magistrado solicita una **única versión consolidada del acto completo**. "
                      "Integra las correcciones parciales, versiones intermedias u orientaciones que figuren "
                      "en el TEXTO ACTUAL, elimina líneas tachadas/notas procesales donde proceda adoptar texto definitivo "
                      "y conserva una estructura coherente con la plantilla e instrucciones de materia/caso.\n\n"
                      "## Qué hacer con el texto\n"
                      "- Si el encargo menciona reorganizar grandes bloques («resumen del recurso», «contestar cada punto»), "
                      "aplícalo al documento íntegro aquí sí.\n"
                      "- No inventes casaciones ni referencias nuevas.\n\n"
                      "### Salida\n"
                      "Devuelve **solo** el texto del acto completo consolidado, sin prefijos ni comentarios meta.\n"
                )
                system_txt = (
                    ITER_WORKER_SYSTEM_PREFIX_ES
                    + system_injection_guard_es()
                    + "\n\nProducir un acto judicial completo bien integrado cuando el magistrado pide consolidación íntegra. "
                    "Cumple instrucciones de estructura y contenido prioritarias sobre el borrador disperso anterior."
                )
                max_tokens_iter = resolution_max_output_tokens()

            iter_errors: list[str] = []
            max_attempts = resolution_stream_max_attempts()
            iter_msgs = [{"role": "user", "content": prompt}]

            for model in resolution_model_candidates():
                for attempt in range(max_attempts):
                    if self._cancelled:
                        self.iteration_finished.emit()
                        return
                    if attempt == 0:
                        self.status.emit(f"Iteración con Claude ({model})…")
                    else:
                        delay = resolution_stream_retry_delay_sec(attempt)
                        self.status.emit(
                            f"{model}: fallo temporal — reintento iteración "
                            f"{attempt + 1}/{max_attempts} (~{delay:.0f}s)…"
                        )
                        if not _interruptible_sleep(delay, lambda: self._cancelled):
                            self.iteration_finished.emit()
                            return
                    try:
                        _parts, _fm, cancelled_stream = consume_claude_messages_stream_once(
                            client,
                            model=model,
                            max_tokens=max_tokens_iter,
                            system=system_txt,
                            messages=iter_msgs,
                            cancelled_fn=lambda: self._cancelled,
                            chunk_emit=self.chunk_ready.emit,
                        )
                        if cancelled_stream:
                            self.iteration_finished.emit()
                            return
                        self.iteration_finished.emit()
                        return
                    except Exception as e:
                        detail = format_anthropic_stream_exception(e)
                        if attempt < max_attempts - 1 and anthropic_stream_error_retryable(e):
                            short = detail.replace("\n", " ").strip()
                            if len(short) > 170:
                                short = short[:167] + "…"
                            self.status.emit(f"{model}: error reintentable — {short}")
                            continue
                        iter_errors.append(f"{model}: {detail}")
                        break

            raise RuntimeError(
                "Iteración: ningún modelo de resolución respondió:\n"
                + "\n".join(iter_errors)
            )
        except Exception as exc:
            self.error_occurred.emit(str(exc))
