#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regenera 02_wiki/bibliografia/_extracts/referencias_desde_pdfs_pp.md desde los dos PDF PP."""
from __future__ import annotations

import importlib.util
import re
import sys
from datetime import date
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import fitz  # PyMuPDF

from app.core.pdf_extract import extract_pdf_text

BIB = ROOT / "01_raw/bibliografia/prision_preventiva"
OUT = ROOT / "02_wiki/bibliografia/_extracts/referencias_desde_pdfs_pp.md"
OUT_CRITERIOS = ROOT / "02_wiki/bibliografia/_extracts/criterios_jurisprudenciales_estado_arte_pp.md"

# PDF compendio Estado del arte (prioriza v3 reconstruido si existe).
ESTADO_PDF_NAMES = (
    "Estado_del_Arte_PP_v3_reconstruido copia.pdf",
    "estado del arte pp.pdf",
)


def norm_space(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip())


def md_fence_text_lines(content: str) -> list[str]:
    """Varias lineas Markdown: fence text para que Obsidian no interprete [corchetes]."""
    t = content.replace("\r\n", "\n").strip()
    t = t.replace("```", "`\u200b``")
    return ["```text", t, "```"]


def estado_pdf_path() -> Path:
    for name in ESTADO_PDF_NAMES:
        p = BIB / name
        if p.is_file():
            return p
    raise FileNotFoundError(
        "No Estado del arte PDF in %s (tried: %s)" % (BIB, ESTADO_PDF_NAMES)
    )


def extract_estado_bracket_citations(estado_txt: str) -> list[str]:
    """Citas del tipo [Cas. ...], [TC, ...], etc., en el cuerpo del compendio."""
    out: list[str] = []
    seen: set[str] = set()
    i = 0
    while True:
        j = estado_txt.find("[", i)
        if j == -1:
            break
        k = estado_txt.find("]", j)
        if k == -1:
            break
        inner = norm_space(estado_txt[j + 1 : k])
        if 8 <= len(inner) <= 220:
            low = inner.lower()
            if re.search(
                r"(cas\.|casaci[\u00f3o]n|apel\.|tc\b|corte|exp\.|rn\s|ap\s|stc|acuerdo|"
                r"corteidh|sentencia\s+plenaria|\bra\s+\d|ape\s+\d)",
                low,
            ):
                if inner not in seen:
                    seen.add(inner)
                    out.append(inner)
        i = j + 1
    return out


def _load_extra_wiki_keys() -> list[tuple[str, str]]:
    p = Path(__file__).resolve().parent / "wiki_keys_pp_presupuestos_extra.py"
    if not p.is_file():
        return []
    spec = importlib.util.spec_from_file_location("_pp_extra_wk", p)
    if spec is None or spec.loader is None:
        return []
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return list(getattr(mod, "EXTRA_WIKI_KEYS", []))


def _combine_wiki_key_lists(*groups: list[tuple[str, str]]) -> list[tuple[str, str]]:
    merged: list[tuple[str, str]] = []
    for g in groups:
        merged.extend(g)
    seen: set[str] = set()
    unique: list[tuple[str, str]] = []
    for k, link in merged:
        kn = k.replace(" ", "").replace("\u00a0", "")
        if kn in seen:
            continue
        seen.add(kn)
        unique.append((k, link))
    unique.sort(key=lambda x: len(x[0].replace(" ", "")), reverse=True)
    return unique


# Wikilinks con escapes para mantener este .py en ASCII puro donde basta.
# Claves base + EXTRA (presupuestos PP / Estado del arte). Orden final: longitud
# descendente (subcadena mas larga gana en wiki_for). La SPC 01-2017/CIJ-433
# sigue en la lista base; el APE 01-2017/CIJ-116 y el AP 01-2019/CIJ-116 se
# distinguen por el a�o en la subcadena.
WIKI_KEYS_BASE = [
    ("01-2017/CIJ-433", "[[Sentencia Plenaria Casatoria 01-2017/CIJ-433]]"),
    ("01-2019/CIJ-116", "[[Acuerdo Plenario 01-2019/CIJ-116]]"),
    ("02-2018-SPN", "[[Acuerdo Plenario 02-2018-SPN/02-2018-SPN]]"),
    ("03248-2019", "[[TC Exp. N.\u00b0 03248-2019-PHC/TC]]"),
    ("02771-2019", "[[TC Exp. N.\u00b0 02771-2019-PHC/TC]]"),
    ("02576-2011", "[[TC Exp. N.\u00b0 02576-2011-PHC/TC]]"),
    ("02926-2019", "[[TC Exp. N.\u00b0 2926-2019-PHC/TC]]"),
    ("03337-2011", "[[TC Exp. N.\u00b0 03337-2011-PHC/TC]]"),
    ("1421-2023", "[[Casaci\u00f3n 1421-2023/Loreto]]"),
    ("1445-2018", "[[Casaci\u00f3n 1445-2018/Nacional]]"),
    ("1673-2017", "[[Casaci\u00f3n 1673-2017/Nacional]]"),
    ("1039-2016", "[[Casaci\u00f3n 1039-2016/Arequipa]]"),
    ("626-2013", "[[Casaci\u00f3n 626-2013/Moquegua]]"),
    ("238-2020", "[[Casaci\u00f3n 238-2020/Lambayeque]]"),
    ("325-2011", "[[Resoluci\u00f3n Administrativa 325-2011-P-PJ]]"),
    ("38-2024", "[[Apelaci\u00f3n 38-2024/Ayacucho]]"),
    ("1091-2002", "[[Expediente N.\u00b0 1091-2002-HC/TC (Silva Checa)]]"),
    ("0019-2005", "[[STC Exp. N.\u00b0 0019-2005-PI/TC]]"),
    ("2926-2019", "[[TC Exp. N.\u00b0 2926-2019-PHC/TC]]"),
    ("Jenkinsvs.Argentina", "[[Corte IDH/Jenkins vs. Argentina]]"),
    ("Us\u00f3nRam\u00edrezvs.Venezuela", "[[Corte IDH/Us\u00f3n Ram\u00edrez vs. Venezuela]]"),
]

WIKI_KEYS = _combine_wiki_key_lists(WIKI_KEYS_BASE, _load_extra_wiki_keys())


def wiki_for(text: str) -> Optional[str]:
    t = text.replace(" ", "").replace("\u00a0", "")
    for key, link in WIKI_KEYS:
        if key.replace(" ", "").replace("\u00a0", "") in t:
            return link
    return None


def trim_criterion_body(body: str) -> str:
    """Recorta el texto del criterio: fin de epigrafe numerada, anexo, etc."""
    body = body.strip()
    _l = r"A-Za-z\u00c1\u00c9\u00cd\u00d3\u00da\u00d1\u00e1\u00e9\u00ed\u00f3\u00fa\u00f1"
    for pat in (
        r"\n\s*REFERENCIAS\s+JURISPRUDENCIALES\b",
        rf"\n\s*\d+\.\s+[{_l}]",
        rf"\n\s*[IVXLC]{{1,4}}\.\s+[A-Z{_l}]",
        rf"\n\s*[a-z]\)\s+[{_l}]",
        r"\n\s*\u2022\s+[A-Z]",  # listas tipo bullet del anexo
    ):
        m = re.search(pat, body)
        if m:
            body = body[: m.start()].strip()
    return body


def build_criterios_markdown(estado_txt: str, estado_rel: str) -> str:
    """Un bloque por cada [cita] doctrinal seguida de parrafo en el compendio *Estado del arte*."""
    chunks: list[tuple[str, str]] = []
    parts = re.split(r"(?=\[[^\]]+\])", estado_txt)
    seen: set[tuple[str, str]] = set()
    for seg in parts[1:]:
        m = re.match(r"\[([^\]]+)\]\s*(.*)", seg, re.DOTALL)
        if not m:
            continue
        tag, body = m.group(1).strip(), trim_criterion_body(m.group(2))
        body_one = norm_space(body)
        if len(body_one) < 12:
            continue
        key = (tag, body_one)
        if key in seen:
            continue
        seen.add(key)
        chunks.append((tag, body_one))

    today = date.today().isoformat()
    lines: list[str] = [
        "<!-- Generado por tools/refresh_pp_bib_pdf_extracts.py; no editar a mano salvo bloque libre al final -->",
        "",
        "# Criterios jurisprudenciales \u2014 compendio *Estado del arte* (prisi\u00f3n preventiva)",
        "",
        "**Resumen (3 puntos clave)**",
        "",
        "- Cada entrada incluye una **l\u00ednea completa en bloque c\u00f3digo** `[identificador] tesis` tal como en el PDF, para que Obsidian/Markdown **no interpreten** los corchetes como sintaxis de enlace; debajo va la **tesis** lista para citar en fichas.",
        "- La **identificaci\u00f3n y uso** de estas citas est\u00e1 **contrastada** seg\u00fan el criterio del titular del repositorio (misma l\u00ednea que el resto de la bibliograf\u00eda PP).",
        "- Para enlaces autom\u00e1ticos a notas `.md` usar **Nota en el wiki**; el inventario crudo sigue en [[bibliografia/_extracts/referencias_desde_pdfs_pp]].",
        "",
        f"**Fecha de generaci\u00f3n:** {today}",
        "",
        f"**PDF fuente:** `{estado_rel}`",
        "",
        "---",
        "",
        f"## Criterios por orden de aparici\u00f3n en el compendio (_total: {len(chunks)}_)",
        "",
    ]
    for n, (tag, body_one) in enumerate(chunks, start=1):
        w = wiki_for("[" + tag + "]")
        wiki_line = w if w else "_*(sin enlace autom\u00e1tico en el script; ver inventario y fuente primaria.)*_"
        safe_tag = tag.replace("`", "'")
        compendio_line = f"[{safe_tag}] {body_one}".replace("```", "`\u200b``")
        lines.extend(
            [
                f"### {n}. {safe_tag}",
                "",
                "**L\u00ednea en el compendio** (reproducci\u00f3n fiel; bloque `text` para que el visor no trate `[]` como enlace):",
                "",
                "```text",
                compendio_line,
                "```",
                "",
                "**Tesis / criterio** *(para argumentar en fichas del wiki):*",
                "",
                f"*{body_one}*",
                "",
                f"**Nota en el wiki:** {wiki_line}",
                "",
                "---",
                "",
            ]
        )
    return "\n".join(lines)


def main() -> None:
    try:
        p_est = estado_pdf_path()
    except FileNotFoundError as e:
        print(e, file=sys.stderr)
        sys.exit(1)
    p_jur = BIB / "Jurisprudencia actual pp.pdf"
    if not p_jur.is_file():
        print("Falta PDF", p_jur, file=sys.stderr)
        sys.exit(1)

    doc = fitz.open(p_est)
    estado_txt = "\n\n".join(doc[i].get_text() for i in range(len(doc)))
    doc.close()
    jur_txt = extract_pdf_text(p_jur)
    haystack = jur_txt + "\n" + estado_txt

    wiki_hits: dict[str, set[str]] = {}
    for line in haystack.splitlines():
        line = line.strip()
        if len(line) < 12:
            continue
        w = wiki_for(line)
        if w:
            wiki_hits.setdefault(w, set()).add(norm_space(line)[:220])

    bracket: set[str] = set()
    for m in re.finditer(r"\[([^\]]{8,140})\]", jur_txt):
        t = norm_space(m.group(1))
        if re.search(r"(acuerdo|casaci|cas\.|pleno|apel|tribunal|exp\.|stc|phc|tc|sala)", t, re.I):
            bracket.add(t)
    for m in re.finditer(
        r"Casaci[\u00f3o]n\s+\d+[-\u2013\u2014-]\d+\s*,\s*[A-Za-z\u00c1\u00e1\u00c9\u00e9\u00cd\u00ed"
        r"\u00d3\u00f3\u00da\u00fa\u00d1\u00f1\u00da .]+",
        jur_txt,
        re.I,
    ):
        bracket.add(norm_space(m.group(0)))

    pending: list[str] = []
    linked_lines: list[tuple[str, str]] = []
    for b in sorted(bracket, key=lambda x: x.lower()):
        w = wiki_for(b)
        if w:
            linked_lines.append((w, b))
        else:
            pending.append(b)

    marker = "**ESTADO DEL ARTE**"
    idx = estado_txt.find(marker)
    if idx == -1:
        idx = estado_txt.find("ESTADO DEL ARTE")
    frag = estado_txt[idx:] if idx != -1 else estado_txt
    if idx == -1:
        idx2 = estado_txt.find("I. NATURALEZA")
        frag = estado_txt[idx2:] if idx2 != -1 else estado_txt

    estado_rel = p_est.relative_to(ROOT).as_posix()
    estado_brackets = extract_estado_bracket_citations(estado_txt)

    hdr = (
        "<!-- Lista generada por script; la identificaci\u00f3n de expedientes contrastada seg\u00fan criterio del repositorio -->\n"
        "\n"
        "# Referencias detectadas en los PDF de bibliograf\u00eda PP\n"
        "\n"
        f"**Fecha de extracci\u00f3n:** {date.today().isoformat()}\n"
        "\n"
        f"**Fuentes:** `01_raw/bibliografia/prision_preventiva/{p_est.name}`; "
        "`Jurisprudencia actual pp.pdf`. Texto: PyMuPDF / `app.core.pdf_extract` "
        f"(Estado del arte: `{estado_rel}`).\n"
        "\n"
        "## Estado de contrastaci\u00f3n\n"
        "\n"
        "La **jurisprudencia y expedientes** que estos compendios mencionan han sido **contrastados** con las fuentes oficiales (PJ, TC, etc.) seg\u00fan el criterio del titular del repositorio. "
        "Las muestras bajo \u00abEn el PDF (muestra)\u00bb van en **bloques de c\u00f3digo** con etiqueta `text` (fenced code blocks) para que **Obsidian y Markdown no traten los corchetes** "
        "de las citas como sintaxis de enlace. Pueden tener errores de OCR; contrastar con el PDF o el texto oficial si se transcriben.\n"
        "\n"
        "## Menciones que enlazan con [[jurisprudencia]] (por n\u00famero de expediente)\n"
        "\n"
    )
    lines_out: list[str] = [hdr]
    for w in sorted(wiki_hits.keys()):
        lines_out.append(f"### {w}")
        for ex in sorted(wiki_hits[w])[:5]:
            lines_out.append("- _En el PDF (muestra):_")
            lines_out.extend(md_fence_text_lines(ex))
        if len(wiki_hits[w]) > 5:
            lines_out.append(f"- _\u2026 y {len(wiki_hits[w]) - 5} l\u00edneas m\u00e1s._")
        lines_out.append("")

    lines_out.append(
        "## Sumario entre corchetes (Jurisprudencia actual) \u2014 con nota en wiki cuando hubo coincidencia\n"
        "\n"
    )
    seen_w: list[str] = []
    for w, _b in sorted(linked_lines, key=lambda x: (x[0], x[1])):
        if w not in seen_w:
            lines_out.append(f"- {w}")
            seen_w.append(w)
    lines_out.append("")
    lines_out.append(
        "### \u00cdtems del sumario u otras citas sin **nota dedicada en el wiki** a\u00fan "
        "(la identificaci\u00f3n del expediente puede estar contrastada; falta volcar a `02_wiki/jurisprudencia/`)\n"
    )
    lines_out.append("")
    for b in pending:
        lines_out.append("- _Item (sumario / pendiente):_")
        lines_out.extend(md_fence_text_lines(b))

    lines_out.extend(
        [
            "",
            "## \u00abEstado del arte\u00bb \u2014 inventario de citas entre corchetes (cuerpo del compendio)",
            "",
            "Cada identificador aparece en un **bloque de c\u00f3digo** (`text`) como `[contenido del PDF]` para lectura segura en Obsidian.",
            "",
            f"_PDF utilizado:_ `{estado_rel}` \u2014 _total \u00fanico:_ {len(estado_brackets)}",
            "",
        ]
    )
    for inner in estado_brackets:
        w = wiki_for(inner)
        suffix = f" \u2192 {w}" if w else ""
        lines_out.append("- **Cita en el compendio:**")
        lines_out.extend(md_fence_text_lines(f"[{inner}]"))
        if suffix:
            lines_out.append(f"    {suffix.strip()}")
        lines_out.append("")

    lines_out.extend(
        [
            "",
            "## \u00abEstado del arte\u00bb \u2014 fragmento legible (desde marca en PDF)",
            "",
            "```",
            frag[:8000],
        ]
    )
    if len(frag) > 8000:
        lines_out.append("\n[\u2026truncado\u2026]")
    lines_out.append("```")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines_out), encoding="utf-8")
    print("Escrito", OUT.relative_to(ROOT))

    crit = build_criterios_markdown(estado_txt, estado_rel)
    OUT_CRITERIOS.parent.mkdir(parents=True, exist_ok=True)
    OUT_CRITERIOS.write_text(crit, encoding="utf-8")
    print("Escrito", OUT_CRITERIOS.relative_to(ROOT))


if __name__ == "__main__":
    main()
