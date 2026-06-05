# -*- coding: utf-8 -*-
"""CLI: procesar corpus pendiente (misma logica que el boton en la app)."""
from __future__ import annotations

import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.core.env_load import load_repo_dotenv

load_repo_dotenv()

from app.core.file_manager import (  # noqa: E402
    BASE_DIR,
    MATERIA_PRISION_PREVENTIVA,
    MATERIA_SLUGS,
    dir_casos_previos_wiki,
    materia_label,
    pending_corpus_pdfs,
    read_corpus_index,
    write_corpus_index,
)
from app.core.wiki_worker import _get_client, _ingest_corpus_file_step  # noqa: E402


def _p(msg: str) -> None:
    print(msg, flush=True)


def main() -> int:
    materia = sys.argv[1] if len(sys.argv) > 1 else MATERIA_PRISION_PREVENTIVA
    if materia not in MATERIA_SLUGS:
        _p(f"Materia invalida: {materia}")
        return 1

    try:
        n_workers = int(os.environ.get("ADIUTOR_CORPUS_WORKERS", "3"))
    except ValueError:
        n_workers = 3
    n_workers = max(1, min(8, n_workers))

    _p("Cargando cliente API y lista de archivos...")
    client = _get_client()
    pending = pending_corpus_pdfs(materia)
    total = len(pending)
    _p(f"Materia: {materia} | pendientes: {total} | workers: {n_workers}")
    if total == 0:
        _p("Nada que procesar.")
        return 0

    mat_label = materia_label(materia)
    idx = read_corpus_index(materia)
    dest_dir = dir_casos_previos_wiki(materia)
    dest_dir.mkdir(parents=True, exist_ok=True)
    lock = threading.Lock()
    procesados = 0
    fallos = 0

    with ThreadPoolExecutor(max_workers=min(n_workers, total)) as pool:
        futs = {
            pool.submit(_ingest_corpus_file_step, p, mat_label, client): p for p in pending
        }
        for fut in as_completed(futs):
            src = futs[fut]
            try:
                r = fut.result()
            except Exception as e:
                _p(f"ERROR {src.name}: {e}")
                fallos += 1
                continue
            if not r.get("ok"):
                _p(f"OMITIDO {r.get('name', src.name)}: {r.get('err', '')[:200]}")
                fallos += 1
                continue
            ts = datetime.now().strftime("%Y-%m-%d %H:%M")
            ficha_path = dest_dir / f"{r['stem']}.md"
            body = (
                f"<!-- ficha generada {ts} | fuente: {r['name']} (CLI) -->\n\n"
                f"{r['ficha_md']}"
            )
            with lock:
                ficha_path.write_text(body, encoding="utf-8")
                idx[r["name"]] = str(ficha_path.relative_to(BASE_DIR))
                write_corpus_index(materia, idx)
            procesados += 1
            _p(f"OK {procesados}/{total} {r['name']}")

    _p(f"--- Listo. Fichas nuevas: {procesados}. Problemas: {fallos}.")
    return 0 if procesados or total == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
