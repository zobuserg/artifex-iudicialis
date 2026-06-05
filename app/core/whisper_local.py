"""
Transcripción de audio local usando el CLI de OpenAI Whisper.

Instalar:  pip install openai-whisper
El módulo es completamente opcional — si Whisper no está instalado la app
sigue funcionando; el botón 🎙 muestra un mensaje de instrucción.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def whisper_cli_available() -> bool:
    """True si el ejecutable `whisper` está en el PATH."""
    return shutil.which("whisper") is not None


def transcribe_audio_to_txt(audio_path: Path) -> tuple[bool, str]:
    """Transcribe *audio_path* a texto usando el CLI `whisper`.

    Devuelve ``(True, str(txt_path))`` en éxito o ``(False, mensaje_error)``
    si Whisper no está disponible o falla.

    El archivo .txt se guarda junto al audio original
    (mismo directorio, mismo nombre, extensión .txt).
    """
    if not whisper_cli_available():
        return (
            False,
            "El CLI de Whisper no está instalado o no se encuentra en el PATH.",
        )

    if not audio_path.is_file():
        return False, f"El archivo no existe: {audio_path}"

    output_dir = audio_path.parent
    try:
        result = subprocess.run(
            [
                "whisper",
                str(audio_path),
                "--output_format", "txt",
                "--output_dir", str(output_dir),
            ],
            capture_output=True,
            text=True,
            timeout=600,   # 10 min máximo
        )
    except subprocess.TimeoutExpired:
        return False, "La transcripción tardó demasiado (> 10 min) y fue cancelada."
    except OSError as e:
        return False, f"No se pudo ejecutar whisper: {e}"

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        return False, f"Whisper devolvió error (código {result.returncode}):\n{detail}"

    # Whisper genera <nombre_sin_ext>.txt en output_dir
    txt_path = output_dir / (audio_path.stem + ".txt")
    if not txt_path.is_file():
        # Busca cualquier .txt recién generado por si el nombre difiere
        candidates = sorted(output_dir.glob("*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
        if candidates:
            txt_path = candidates[0]
        else:
            return False, "Whisper terminó pero no se encontró el archivo .txt generado."

    return True, str(txt_path)
