"""Recuperación de fichas (casos previos, jurisprudencia) para el pipeline.

Ranking en dos pasos:
  1. Prefiltro léxico (solapamiento de palabras clave) — rápido, sin red.
  2. Re-ranking semántico con Haiku (opcional) sobre los mejores candidatos.

No se usan embeddings vectoriales porque la cuenta no tiene proveedor (Voyage/
OpenAI) y un modelo local (torch) sería una dependencia pesada y frágil en
Python 3.14. El re-ranking con Haiku da calidad semántica equivalente sin
infraestructura nueva. Si en el futuro hay clave de embeddings, este módulo es
el único punto a cambiar.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

_WORD = re.compile(r"[a-záéíóúñ0-9]{4,}")
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


def _toks(s: str) -> set[str]:
    return set(_WORD.findall((s or "").lower()))


def strip_meta(txt: str) -> str:
    """Quita comentarios HTML (metadatos de las fichas)."""
    return _HTML_COMMENT.sub("", txt or "")


def load_fichas(
    directory: Path, *, recursive: bool = True, exclude_names: tuple[str, ...] = (),
) -> list[Path]:
    if not directory.is_dir():
        return []
    it = directory.rglob("*.md") if recursive else directory.glob("*.md")
    return [
        f for f in it
        if f.is_file() and not f.name.startswith(".") and f.name not in exclude_names
    ]


def lexical_rank(
    fichas: list[Path],
    query_text: str,
    *,
    top: int = 12,
    boost_terms: tuple[str, ...] = (),
    boost_weight: int = 10,
) -> list[tuple[int, Path, str]]:
    """Mejores `top` fichas por solapamiento de palabras clave. (score, path, texto).

    ``boost_terms`` (p. ej. el delito del caso) pesan ``boost_weight`` cada uno: una
    ficha del MISMO delito/tipo de hecho sube por encima de fichas que solo comparten
    vocabulario genérico (reparación civil, pago, plazo…). Sin esto, casos de un delito
    distinto pero con jerga económica similar (p. ej. OAF) desplazan a los pertinentes.
    """
    q = _toks(query_text)
    boost = _toks(" ".join(boost_terms))
    if not q and not boost:
        return []
    scored: list[tuple[int, Path, str]] = []
    for f in fichas:
        try:
            txt = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        ftoks = _toks(f.stem + " " + strip_meta(txt)[:2000])
        score = len(q & ftoks) + boost_weight * len(boost & ftoks)
        if score > 0:
            scored.append((score, f, txt))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[:top]


def haiku_rerank(
    query_text: str,
    candidates: list[tuple[int, Path, str]],
    *,
    k: int = 5,
    focus: str = "",
) -> list[tuple[Path, str]]:
    """Re-ranking semántico con Haiku sobre los candidatos del prefiltro léxico.

    ``focus`` (p. ej. el delito) se le da a Haiku como criterio dominante: debe
    priorizar documentos del MISMO delito/tipo de hecho. Si Haiku falla o hay pocos
    candidatos, cae al orden léxico. Devuelve <=k (path, texto).
    """
    if len(candidates) <= k:
        return [(f, t) for _, f, t in candidates]
    try:
        from app.core.wiki_worker import _call_haiku, _get_client

        listado = "\n".join(f"{i}. {f.stem.replace('_', ' ')}" for i, (_, f, _) in enumerate(candidates))
        foco_txt = (
            f"DELITO / TIPO DE CASO ACTUAL (criterio PRINCIPAL de afinidad): {focus}\n"
            "Prioriza documentos del MISMO delito o tipo de hecho; un documento de otro "
            "delito NO es pertinente aunque comparta vocabulario (reparación civil, pago, "
            "plazos).\n\n"
            if focus else ""
        )
        prompt = (
            foco_txt
            + "CASO ACTUAL:\n" + (query_text or "")[:1500] + "\n\n"
            "DOCUMENTOS CANDIDATOS (índice. título):\n" + listado + "\n\n"
            f"Devuelve SOLO un arreglo JSON con los índices de los {k} documentos MÁS "
            "pertinentes al caso actual, del más al menos relevante. "
            "Ejemplo de formato: [3, 0, 7, 1, 5]"
        )
        raw = _call_haiku(_get_client(), prompt, max_tokens=120) or ""
        m = re.search(r"\[[^\]]*\]", raw)
        idxs = json.loads(m.group()) if m else []
        out: list[tuple[Path, str]] = []
        for i in idxs:
            if isinstance(i, int) and 0 <= i < len(candidates):
                _, f, t = candidates[i]
                out.append((f, t))
            if len(out) >= k:
                break
        if out:
            return out
    except Exception:
        pass
    return [(f, t) for _, f, t in candidates[:k]]


def retrieve(
    directory: Path,
    query_text: str,
    *,
    k: int = 5,
    prefilter: int = 12,
    use_haiku: bool = True,
    exclude_names: tuple[str, ...] = (),
    focus: str = "",
) -> list[tuple[Path, str]]:
    """Pipeline completo: carga fichas → prefiltro léxico → re-rank Haiku → top k.

    ``focus`` (p. ej. el delito del caso) prioriza fichas del mismo delito/tipo de
    hecho, tanto en el prefiltro léxico (boost) como en el re-rank Haiku.
    """
    fichas = load_fichas(directory, exclude_names=exclude_names)
    if not fichas:
        return []
    boost = (focus,) if focus else ()
    cands = lexical_rank(fichas, query_text, top=max(prefilter, k), boost_terms=boost)
    if not cands:
        return []
    if use_haiku:
        return haiku_rerank(query_text, cands, k=k, focus=focus)
    return [(f, t) for _, f, t in cands[:k]]


def one_line_summary(txt: str, limite: int = 900) -> str:
    """Resumen en UNA línea (sin comentarios, viñetas ni líneas en blanco)."""
    txt = strip_meta(txt)
    limpio: list[str] = []
    for ln in txt.splitlines():
        s = ln.strip().lstrip("#•-*> ").strip()
        if s:
            limpio.append(s)
    return (" · ".join(limpio))[:limite]
