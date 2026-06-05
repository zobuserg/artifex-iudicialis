#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Crea notas atomicas en 02_wiki/jurisprudencia/ desde criterios sin enlace (Estado del arte PP).

Uso:
  python3 tools/seed_estado_arte_presupuestos_atomics.py
  python3 tools/seed_estado_arte_presupuestos_atomics.py --emit-keys

No sobreescribe notas existentes (primera corrida).
"""
from __future__ import annotations

import argparse
import re
from collections import defaultdict
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
CRITERIOS = ROOT / "02_wiki/bibliografia/_extracts/criterios_jurisprudenciales_estado_arte_pp.md"
JUR = ROOT / "02_wiki/jurisprudencia"
EXTRA_KEYS_OUT = ROOT / "tools/wiki_keys_pp_presupuestos_extra.py"

DEG = "\u00b0"
EM = "\u2014"

THEME_HEADINGS: dict[str, str] = {
    "I": f"I {EM} Elementos de convicci\u00f3n / sospecha grave (art. 268.a CPP)",
    "II": f"II {EM} Prognosis de pena (art. 268.b CPP)",
    "III": f"III {EM} Peligro de fuga (art. 268.c CPP)",
    "IV": f"IV {EM} Peligro de obstaculizaci\u00f3n (art. 268.c CPP)",
    "V": f"V {EM} Proporcionalidad y l\u00edmites punitivos en la cautelar",
    "VI": f"VI {EM} Motivaci\u00f3n y est\u00e1ndar de control (TC / constitucional)",
    "VII": f"VII {EM} Copulatividad y estructura de los presupuestos",
    "IX": f"IX {EM} Plazos, RN, prolongaci\u00f3n y complejidad procesal",
    "X": f"X {EM} Otros criterios del compendio (matizaci\u00f3n pr\u00e1ctica)",
    "XI": f"XI {EM} Arraigo, medidas sustitutivas y variaci\u00f3n de la cautelar",
    "XII": f"XII {EM} Derecho internacional (Corte IDH / TEDH)",
    "XIII": f"XIII {EM} Acuerdos de salas y criterios internos",
}


def strip_trailing_paren(tag: str) -> str:
    return re.sub(r"\s*\([^)]*\)\s*$", "", tag.strip()).strip()


def parse_blocks(text: str) -> list[tuple[str, str, str]]:
    blocks = text.split("\n---\n")
    out: list[tuple[str, str, str]] = []
    for b in blocks:
        if "###" not in b or "**Nota en el wiki:**" not in b:
            continue
        m = re.search(r"^### \d+\.\s*((?:.|\n)+?)\n\n\*\*L", b, re.M)
        if not m:
            continue
        tag = " ".join(m.group(1).split())
        crit = re.search(r"\*\*Tesis / criterio\*\*.*?\n\n\*([^\*]+)\*", b, re.S)
        thesis = crit.group(1).strip().replace("\n", " ") if crit else ""
        code = re.search(r"```text\n(.+?)\n```", b, re.S)
        comp = code.group(1).strip().replace("\n", " ") if code else ""
        if not comp:
            continue
        out.append((tag, thesis, comp))
    return out


def classify_theme_code(thesis: str, tag: str) -> str:
    s = (thesis + " " + tag).lower()
    t0 = tag.replace(" ", "").lower()
    if "corteidh" in t0:
        return "XII"
    if tag.lower().startswith("tedh"):
        return "XII"
    if tag.lower().startswith("acuerdo 2-2017-sps"):
        return "XIII"
    if re.match(r"^RN\s", tag, re.I):
        return "IX"
    if "obstaculiz" in s or "fuentes de prueba" in s or "perturbar" in s:
        return "IV"
    if "fuga" in s or "extrad" in s or "fronter" in s:
        return "III"
    if "proporcional" in s or ("punitiv" in s and "pena" in s):
        return "V"
    if "arresto domiciliario" in s or "medida sustitutiva" in s or "comparecencia" in s:
        return "XI"
    if (
        "plazo" in s
        or "pr\u00f3rroga" in s
        or "prolongaci\u00f3n" in s
        or "adecuaci\u00f3n" in s
        or tag.upper().startswith("APE ")
    ):
        return "IX"
    if "motivaci\u00f3n" in s or "arbitrar" in s or "inconstitucional" in s:
        return "VI"
    if "pena" in s and (
        "grave" in s or "suficiente" in s or "prognosis" in s or "expectativa" in s
    ):
        return "II"
    if (
        "elementos de convicci\u00f3n" in s
        or "indicios" in s
        or "sospecha" in s
        or "colaborador" in s
    ):
        return "I"
    if "copulativ" in s or "concurrente" in s:
        return "VII"
    if "arraigo" in s or "domicilio" in s or "laboral" in s:
        return "XI"
    return "X"


def theme_label(code: str) -> str:
    return THEME_HEADINGS.get(code, THEME_HEADINGS["X"])


def wikilink_from_parts(folder: str, leaf: str) -> str:
    return f"[[{folder}/{leaf}]]"


def resolve(
    tag: str, thesis: str, comp: str
) -> Optional[tuple[Path, str, str, list[str]]]:
    raw = strip_trailing_paren(" ".join(tag.split()))
    if raw.upper().startswith("REFERENCIAS"):
        return None

    if "00502-2018" in raw and "04780-2017" in raw:
        name = "TC Exp. acumulado 04780-2017 y 00502-2018-PHC/TC.md"
        wl = "[[TC Exp. acumulado 04780-2017 y 00502-2018-PHC/TC]]"
        keys = [
            "PHC/TCy00502-2018-PHC/TC",
            "00502-2018-PHC/TC",
            "Humala-Heredia",
        ]
        return JUR / name, "TC Exp. acumulado 04780-2017 y 00502-2018-PHC/TC", wl, keys

    # Formato habitual: 02463-2019-PHC/TC o 2915-2004-HC/TC (gui�n antes de PHC/HC).
    m = re.search(r"TC,\s*Exp\.\s*(\d+(?:-\d+)+-(?:PHC|HC)/TC)", raw)
    if m:
        mid = m.group(1)
        name = f"TC Exp. N.{DEG} {mid}.md"
        wl = f"[[TC Exp. N.{DEG} {mid}]]"
        return JUR / name, f"TC Exp. N.{DEG} {mid}", wl, [mid]

    m = re.search(r"Cas\.\s*(\d+-\d+)/(.+)", raw)
    if m:
        num, sede = m.group(1), m.group(2).strip()
        folder = f"Casaci\u00f3n {num}"
        leaf = sede + ".md"
        wl = wikilink_from_parts(folder, sede)
        kn = sede.replace(" ", "")
        return JUR / folder / leaf, f"Cas. {num}/{sede}", wl, [f"{num}/{kn}", num]

    m = re.search(r"Apel\.\s*(\d+-\d+)/(.+)", raw)
    if m:
        num, sede = m.group(1), m.group(2).strip()
        folder = f"Apelaci\u00f3n {num}"
        leaf = sede + ".md"
        wl = wikilink_from_parts(folder, sede)
        kn = sede.replace(" ", "")
        return JUR / folder / leaf, f"Apel. {num}/{sede}", wl, [f"{num}/{kn}", num]

    m = re.search(r"RN\s+(\d+-\d+)/(.+)", raw)
    if m:
        num, sede = m.group(1), m.group(2).strip()
        folder = f"RN {num}"
        leaf = sede + ".md"
        wl = wikilink_from_parts(folder, sede)
        kn = sede.replace(" ", "")
        return JUR / folder / leaf, f"RN {num}/{sede}", wl, [f"{num}/{kn}", num]

    m = re.search(r"APE\s+(\d+-\d+)/(CIJ-\d+)", raw, re.I)
    if m:
        y, cij = m.group(1), m.group(2)
        folder = f"Acuerdo Plenario {y}"
        leaf = f"{cij}.md"
        wl = wikilink_from_parts(folder, cij)
        return JUR / folder / leaf, f"APE {y}/{cij}", wl, [f"{y}/{cij}"]

    m = re.search(rf"Exp\.\s*N\.\s*[{DEG}\u00ba]\s*(\d+-\d+-\d+)", raw, re.I)
    if m:
        eid = m.group(1)
        folder = "Primera Sala Penal Apelaciones Nacional"
        leaf = f"Exp. {eid}.md"
        wl = wikilink_from_parts(folder, f"Exp. {eid}")
        return JUR / folder / leaf, f"Exp. N.{DEG} {eid}", wl, [eid]

    m = re.search(r"^Exp\.\s+([\d\-]+)\s*(?:,|$)", raw)
    if m:
        eid = m.group(1)
        folder = "Corte Superior"
        leaf = f"Exp. {eid}.md"
        wl = wikilink_from_parts(folder, f"Exp. {eid}")
        return JUR / folder / leaf, f"Exp. {eid}", wl, [eid]

    m = re.search(r"Corte Superior,\s*Exp\.\s*(.+)", raw)
    if m:
        eid = m.group(1).strip().rstrip(",").strip()
        folder = "Corte Superior"
        leaf = f"Exp. {eid}.md"
        wl = wikilink_from_parts(folder, f"Exp. {eid}")
        return JUR / folder / leaf, f"Corte Superior, Exp. {eid}", wl, [re.sub(r"\s+", "", eid)]

    if raw.startswith("Acuerdo 2-2017-SPS"):
        folder = "Acuerdo 2-2017-SPS-CSJLL"
        leaf = "2-2017-SPS-CSJLL.md"
        wl = wikilink_from_parts(folder, "2-2017-SPS-CSJLL")
        return JUR / folder / leaf, "Acuerdo 2-2017-SPS-CSJLL", wl, ["2-2017-SPS-CSJLL", "2-2017-SPS"]

    if raw.startswith("CorteIDH"):
        rest = raw.split(",", 1)[1].strip() if "," in raw else raw
        rest = re.sub(r"^caso\s+", "", rest, flags=re.I)
        rest = re.sub(r",\s*p\u00e1rr\.\s*\d+", "", rest, flags=re.I)
        title = rest.strip()
        safe = title + ".md"
        wl = f"[[Corte IDH/{title}]]"
        keys = [re.sub(r"\s+", "", title)]
        return JUR / "Corte IDH" / safe, title, wl, keys

    if raw.startswith("TEDH"):
        rest = raw.split(",", 1)[1].strip() if "," in raw else raw.replace("TEDH,", "").strip()
        title = rest.strip()
        safe = title + ".md"
        wl = f"[[TEDH/{title}]]"
        return JUR / "TEDH" / safe, title, wl, [re.sub(r"\s+", "", title)]

    return None


def note_body(title: str, theme_code: str, thesis: str, comp: str) -> str:
    theme_line = theme_label(theme_code)
    short = theme_line.split(EM, 1)[-1].strip()
    zwfence = "`" + "\u200b" + "``"
    comp_safe = comp.replace("```", zwfence)
    return (
        f"# {title}\n\n"
        "**Resumen (3 puntos clave)**\n\n"
        f"- Criterio del compendio *Estado del arte* (v3) vinculado a **{short}**.\n"
        "- Encaje pr\u00e1ctico con los **presupuestos del art. 268 CPP** seg\u00fan el apartado tem\u00e1tico indicado abajo.\n"
        "- Contrastar con la resoluci\u00f3n oficial (PJ, TC, etc.) antes de citar en un auto definitivo.\n\n"
        f"**Presupuesto / tema (art. 268 CPP {EM} gu\u00eda *Estado del arte*)**\n\n"
        f"- {theme_line}\n\n"
        "## L\u00ednea del compendio (reproducci\u00f3n para citar)\n\n"
        "```text\n"
        f"{comp_safe}\n"
        "```\n\n"
        "## Tesis / criterio (ficha)\n\n"
        f"*{thesis}*\n\n"
        "## Ver tambi\u00e9n\n\n"
        "- [[Presupuestos PP art. 268 CPP - indice Estado del arte]]\n"
        "- [[jurisprudencia]]\n"
        "- [[bibliografia/_extracts/criterios_jurisprudenciales_estado_arte_pp]]\n\n"
        "## Fuentes\n\n"
        "- `01_raw/bibliografia/prision_preventiva/Estado_del_Arte_PP_v3_reconstruido copia.pdf`\n"
    )


def merge_key_tuples(
    priority: list[tuple[str, str]], rest: list[tuple[str, str]]
) -> list[tuple[str, str]]:
    merged: list[tuple[str, str]] = []
    merged.extend(priority)
    merged.extend(rest)
    rest_only = merged[len(priority) :]
    rest_only.sort(key=lambda x: len(x[0].replace(" ", "")), reverse=True)
    ordered = priority + rest_only
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for k, link in ordered:
        kn = k.replace(" ", "").replace("\u00a0", "")
        if kn in seen:
            continue
        seen.add(kn)
        out.append((k, link))
    return out


def emit_extra_py(keys: list[tuple[str, str]]) -> str:
    lines = [
        "# -*- coding: utf-8 -*-",
        '"""Claves wiki_for adicionales (Estado del arte -> notas presupuestos PP).',
        "Generado por tools/seed_estado_arte_presupuestos_atomics.py --emit-keys.",
        '"""',
        "from __future__ import annotations",
        "",
        "EXTRA_WIKI_KEYS: list[tuple[str, str]] = [",
    ]
    for k, w in keys:
        lines.append(f"    ({k!r}, {w!r}),")
    lines.append("]")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--emit-keys",
        action="store_true",
        help="Regenera tools/wiki_keys_pp_presupuestos_extra.py",
    )
    args = ap.parse_args()

    text = CRITERIOS.read_text(encoding="utf-8")
    blocks = parse_blocks(text)
    by_section: dict[str, list[str]] = defaultdict(list)
    collected: list[tuple[str, str]] = []
    humala_priority: list[tuple[str, str]] = [
        ("PHC/TCy00502-2018-PHC/TC", "[[TC Exp. acumulado 04780-2017 y 00502-2018-PHC/TC]]"),
        ("00502-2018-PHC/TC", "[[TC Exp. acumulado 04780-2017 y 00502-2018-PHC/TC]]"),
        ("Humala-Heredia", "[[TC Exp. acumulado 04780-2017 y 00502-2018-PHC/TC]]"),
    ]

    written = 0
    skipped = 0
    for tag, thesis, comp in blocks:
        r = resolve(tag, thesis, comp)
        if r is None:
            skipped += 1
            continue
        path, title, wl, keys = r
        code = classify_theme_code(thesis, tag)
        by_section[code].append(wl)
        for k in keys:
            kk = k.replace(" ", "").replace("\u00a0", "")
            if kk:
                collected.append((kk, wl))

        if args.emit_keys:
            continue

        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file():
            skipped += 1
            continue
        path.write_text(note_body(title, code, thesis, comp), encoding="utf-8")
        written += 1

    merged = merge_key_tuples(humala_priority, collected)

    if args.emit_keys:
        EXTRA_KEYS_OUT.write_text(emit_extra_py(merged), encoding="utf-8")
        print("Escrito", EXTRA_KEYS_OUT.relative_to(ROOT), "claves:", len(merged))
        return

    hub_path = JUR / "Presupuestos PP art. 268 CPP - indice Estado del arte.md"
    hub_lines = [
        "<!-- Indice tematico: presupuestos PP + criterios Estado del arte (v3) -->",
        "",
        f"# Presupuestos PP (art. 268 CPP) {EM} \u00edndice *Estado del arte*",
        "",
        "**Resumen (3 puntos clave)**",
        "",
        "- Ordena las **notas nuevas** generadas desde el compendio cuando el script a\u00fan no enlazaba la cita.",
        "- Cada entrada se clasifica por **presupuesto / tema** (268 CPP y est\u00e1ndar convencional).",
        "- El detalle de la tesis est\u00e1 en la nota enlazada y en [[bibliografia/_extracts/criterios_jurisprudenciales_estado_arte_pp]].",
        "",
    ]
    order = ["I", "II", "III", "IV", "V", "VI", "VII", "IX", "X", "XI", "XII", "XIII"]
    for sec in order:
        heading = THEME_HEADINGS.get(sec)
        if not heading:
            continue
        hub_lines.append(f"## {heading}")
        hub_lines.append("")
        links = sorted(set(by_section.get(sec, [])))
        if not links:
            hub_lines.append(
                "_*(Ninguna nota clasificada en esta secci\u00f3n en la \u00faltima corrida.)*_"
            )
        else:
            hub_lines.extend(f"- {x}" for x in links)
        hub_lines.append("")

    hub_lines.extend(
        [
            "## Fuentes",
            "",
            "- `01_raw/bibliografia/prision_preventiva/Estado_del_Arte_PP_v3_reconstruido copia.pdf`",
            "- `tools/seed_estado_arte_presupuestos_atomics.py`",
            "",
        ]
    )
    hub_path.write_text("\n".join(hub_lines), encoding="utf-8")

    print("Notas nuevas:", written, "omitidas (existentes o basura):", skipped)
    print("Claves extra acumuladas (pares):", len(merged))
    print("Ejecute con --emit-keys para volcar tools/wiki_keys_pp_presupuestos_extra.py")


if __name__ == "__main__":
    main()
