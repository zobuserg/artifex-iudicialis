"""
Carga variables desde un archivo .env en la raíz del repositorio.
No sobrescribe variables ya definidas en el entorno (export en shell gana).

Uso: al inicio de main(), antes de crear la ventana:
    from app.core.env_load import load_repo_dotenv
    load_repo_dotenv()
"""

from __future__ import annotations

import os
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def load_repo_dotenv(env_path: Path | None = None) -> bool:
    """
    Lee `REPO_ROOT/.env` (o env_path) y hace os.environ.setdefault(k, v).
    Devuelve True si el archivo existió y se procesó.
    """
    path = env_path or (_REPO_ROOT / ".env")
    if not path.is_file():
        return False
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        if not key:
            continue
        val = val.strip()
        if (val.startswith('"') and val.endswith('"')) or (
            val.startswith("'") and val.endswith("'")
        ):
            val = val[1:-1]
        # No pisar si ya está definida y no vacía (export en shell tiene prioridad)
        existing = os.environ.get(key)
        if existing is not None and str(existing).strip():
            continue
        os.environ[key] = val
    return True


def repo_dotenv_path() -> Path:
    """Ruta canónica de `.env` en la raíz del repositorio."""
    return _REPO_ROOT / ".env"


def set_repo_env_var(key: str, value: str, env_path: Path | None = None) -> None:
    """
    Inserta o actualiza una línea `CLAVE=valor` en el `.env` del repo.
    No modifica líneas comentadas ni comentarios; preserva el resto del archivo.
    Crea `.env` si no existe. El valor no debe contener saltos de línea.
    """
    path = env_path or repo_dotenv_path()
    key = key.strip()
    if not key or "=" in key:
        raise ValueError("clave .env inválida")
    if "\n" in value or "\r" in value:
        raise ValueError("valor .env inválido")
    value = value.strip()
    new_line = f"{key}={value}\n"

    if path.is_file():
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines(keepends=True)
    else:
        lines = []
        path.parent.mkdir(parents=True, exist_ok=True)

    out: list[str] = []
    replaced = False
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith("#") or not stripped.strip():
            out.append(line)
            continue
        s = stripped
        if s.startswith("export "):
            s = s[7:].lstrip()
        if s.startswith(f"{key}="):
            out.append(new_line)
            replaced = True
        else:
            out.append(line)
    if not replaced:
        if out and not out[-1].endswith("\n"):
            out[-1] = out[-1] + "\n"
        out.append(new_line)
    path.write_text("".join(out), encoding="utf-8")
