# -*- coding: utf-8 -*-
"""
Validador automático de salida generada (post-proceso local).

Complementa las defensas anti-injection de entrada: detecta desviaciones del acto
respecto a postura, estructura mínima, metatexto de sistema e citas no respaldadas.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field


@dataclass
class ValidationFinding:
    code: str
    message: str
    severity: str  # "warning" | "error"


@dataclass
class ValidationReport:
    findings: list[ValidationFinding] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return any(f.severity == "error" for f in self.findings)

    @property
    def has_warnings(self) -> bool:
        return any(f.severity == "warning" for f in self.findings)

    @property
    def ok(self) -> bool:
        return not self.findings

    @property
    def blocks_export(self) -> bool:
        return self.has_errors

    def summary_lines(self) -> list[str]:
        if not self.findings:
            return ["Validación de salida: sin observaciones."]
        out: list[str] = []
        for f in self.findings:
            tag = "ERROR" if f.severity == "error" else "AVISO"
            out.append(f"[{tag}] {f.message}")
        return out


_METATEXTO_PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    (
        "metatexto_wikijuez",
        re.compile(r"(?i)wikijuez\s+informa|wiki\s*juez"),
        "Aparece metatexto de aplicación (WikiJuez) en el acto.",
    ),
    (
        "metatexto_ia",
        re.compile(
            r"(?i)(?:como\s+(?:un\s+)?(?:asistente|modelo)\s+(?:de\s+)?(?:ia|inteligencia artificial|lenguaje))"
            r"|(?:language\s+model|large\s+language\s+model)"
        ),
        "Aparece metatexto de asistente/modelo de IA en el acto.",
    ),
    (
        "metatexto_juris_vacia",
        re.compile(r"(?i)no\s+se\s+encontr[oó]\s+jurisprudencia\s+guardada"),
        "Aparece leyenda de «jurisprudencia no encontrada» (metatexto prohibido).",
    ),
    (
        "inyeccion_reflejada",
        re.compile(
            r"(?i)(?:ignore\s+(?:all\s+)?(?:previous|prior)\s+instructions"
            r"|ignor[ae]\s+(?:todas?\s+)?(?:las\s+)?instrucciones?\s+anteriores)"
        ),
        "El acto repite frases típicas de manipulación de instrucciones.",
    ),
    (
        "metatexto_proveedor",
        re.compile(r"(?i)\b(?:anthropic|openai|chatgpt)\b"),
        "Aparece referencia al proveedor del modelo en el acto.",
    ),
)

_STRUCTURE_VISTOS = re.compile(r"(?im)^\s*VISTOS?\b")
_STRUCTURE_CONSIDERANDO = re.compile(r"(?im)^\s*CONSIDERANDO")
_STRUCTURE_RESUELVE = re.compile(r"(?im)^\s*RESUELV")

_REVOCATORY_DISPOSITIVO = re.compile(
    r"(?is)"
    r"(?:SE\s+REVOCA|REVOCANDO\s+(?:LA\s+)?(?:SENTENCIA|RESOLUCI[oó]N|TENENCIA)"
    r"|REVOCAR\s+(?:LA\s+)?(?:SENTENCIA|RESOLUCI[oó]N)"
    r"|MODIFICANDO\s+(?:LA\s+)?(?:SENTENCIA|RESOLUCI[oó]N))"
)

_CONFIRMATORY_DISPOSITIVO = re.compile(
    r"(?is)(?:SE\s+CONFIRMA|CONFIRMANDO\s+(?:LA\s+)?(?:SENTENCIA|RESOLUCI[oó]N)|CONFIRMAR\s+(?:LA\s+)?(?:SENTENCIA|RESOLUCI[oó]N))"
)

_BROKEN_CITATION = re.compile(r"(?i)(?:N\.?\s*°\s*0{2,}\b|\bissued\b)")

_CARGOS_MP_SECTION = re.compile(
    r"(?ims)"
    r"(?:^|\n)\s*(?:II[\.\)]\s*[^\n]*(?:HECHOS|CARGOS)\s+(?:IMPUTADOS|ATRIBUIDOS)"
    r"|(?:HECHOS|CARGOS)\s+IMPUTADOS\s+POR\s+EL\s+MINISTERIO\s+P[ÚU]BLICO)[^\n]*\n"
    r"(.*?)"
    r"(?:^\s*III[\.\)]|\Z)"
)

_PP_PROBATORIO_EN_II: tuple[tuple[str, re.Pattern[str], str], ...] = (
    (
        "pp_ii_declaracion_imputado",
        re.compile(
            r"(?i)(?:declaraci[oó]n\s+(?:del\s+)?imputado|en\s+su\s+declaraci[oó]n"
            r"|(?:el\s+)?imputado\s+(?:manifest[oó]|declar[oó]|confes[oó]|admiti[oó]))"
        ),
        "La sección II incluye declaración o confesión del imputado; eso es prueba, no imputación fiscal.",
    ),
    (
        "pp_ii_reconocimiento_agraviado",
        re.compile(r"(?i)(?:reconocimiento\s+del\s+agraviado|agraviado\s+reconoci[oó]|reconoci[oó].{0,40}agraviado)"),
        "La sección II incluye reconocimiento del agraviado; eso es prueba, no imputación fiscal.",
    ),
    (
        "pp_ii_folios_probatorios",
        re.compile(r"(?i)folios?\s+\d+.{0,80}(?:declaraci[oó]n|confesi[oó]n|imputado\s+manifest)"),
        "La sección II cita folios con actuación probatoria del imputado; pertenece a considerandos.",
    ),
)

_PP_ART194_TYPICITY = re.compile(
    r"(?i)(?:art[ií]culo\s+194|art\.?\s*194\b|"
    r"adquiere|recibe|oculta|facilita|traslada|guarda|dispone|"
    r"procedencia\s+delictuosa|conocimiento\s+.*\s+procedencia)"
)

_PP_ART195_PENALTY_ONLY = re.compile(
    r"(?i)pena\s+no\s+(?:ser[aá]|ser)\s+menor"
)

_PP_ART427_TYPICITY = re.compile(
    r"(?i)(?:art[ií]culo\s+427|art\.?\s*427\b|documento\s+(?:p[uú]blico\s+)?falso|"
    r"hace\s+uso\s+de\s+un\s+documento|falsificaci[oó]n\s+de\s+documentos)"
)

_PP_RECEPTACION = re.compile(r"(?i)receptaci[oó]n")

_CITATION_EXTRACTORS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"STC\s+Exp\.?\s*N\.?\s*°?\s*[\d][\d\-A-Za-z./]*(?:/TC)?",
        re.IGNORECASE,
    ),
    re.compile(r"Casaci[oó]n\s+N\.?\s*°?\s*[\d][\d\-A-Za-z./]*", re.IGNORECASE),
    re.compile(r"Acuerdo\s+Plenario\s+N\.?\s*°?\s*[\d][\d\-A-Za-z./]*", re.IGNORECASE),
)


def _norm(s: str) -> str:
    t = unicodedata.normalize("NFKD", s or "")
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", t).strip().lower()


def _resolutive_tail(text: str) -> str:
    t = text or ""
    m = list(_STRUCTURE_RESUELVE.finditer(t))
    if m:
        return t[m[-1].start() :]
    if len(t) > 1200:
        return t[int(len(t) * 0.65) :]
    return t


def _extract_citations(text: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for pat in _CITATION_EXTRACTORS:
        for m in pat.finditer(text or ""):
            raw = m.group(0).strip()
            key = _norm(raw)
            if key and key not in seen:
                seen.add(key)
                found.append(raw)
    return found


def _citation_in_corpus(citation: str, corpus_norm: str) -> bool:
    c = _norm(citation)
    if not c:
        return True
    if c in corpus_norm:
        return True
    digits = re.findall(r"\d{3,}", c)
    if digits:
        core = digits[0]
        if core in corpus_norm:
            return True
    return False


def _extract_cargos_mp_section(text: str) -> str:
    m = _CARGOS_MP_SECTION.search(text or "")
    return m.group(1).strip() if m else ""


def _extract_calificacion_block(section: str) -> str:
    m = re.search(
        r"(?is)calificaci[oó]n\s+jur[ií]dica\s*:?\s*(.*)$",
        section or "",
    )
    return m.group(1).strip() if m else (section or "")


def _validate_cargos_mp_section(
    text: str,
    *,
    delito: str = "",
    report: ValidationReport,
) -> None:
    section = _extract_cargos_mp_section(text)
    if not section or len(section) < 80:
        return

    for code, pat, msg in _PP_PROBATORIO_EN_II:
        if pat.search(section):
            report.findings.append(ValidationFinding(code, msg, "warning"))

    calif = _extract_calificacion_block(section)
    calif_norm = _norm(calif)
    delito_norm = _norm(delito)
    hay_receptacion = bool(
        _PP_RECEPTACION.search(calif)
        or _PP_RECEPTACION.search(delito)
        or re.search(r"(?i)194", calif)
        or "194" in delito_norm
    )
    if hay_receptacion:
        if not _PP_ART194_TYPICITY.search(calif):
            report.findings.append(
                ValidationFinding(
                    "pp_calificacion_art194_incompleta",
                    "La calificación de receptación no incluye la tipicidad base del artículo 194 CP "
                    "(adquirir, recibir, ocultar, procedencia delictuosa, etc.).",
                    "error",
                )
            )
        elif _PP_ART195_PENALTY_ONLY.search(calif) and not re.search(
            r"(?i)art[ií]culo\s+194|art\.?\s*194", calif
        ):
            report.findings.append(
                ValidationFinding(
                    "pp_calificacion_195_sin_194",
                    "La calificación cita el agravante del artículo 195 (pena) sin enlazar "
                    "explícitamente el tipo base del artículo 194.",
                    "warning",
                )
            )

    hay_427 = bool(
        re.search(r"(?i)427", calif)
        or re.search(r"(?i)documento", delito)
        or "427" in delito_norm
    )
    if hay_427 and not _PP_ART427_TYPICITY.search(calif):
        report.findings.append(
            ValidationFinding(
                "pp_calificacion_art427_incompleta",
                "La calificación no describe la tipicidad del artículo 427 CP "
                "(documento falso / uso / falsificación), solo penas o referencias sueltas.",
                "warning",
            )
        )


def validate_resolution_output(
    text: str,
    *,
    postura: str = "",
    tipo: str = "",
    source_corpus: str = "",
    expect_full_act: bool = True,
    iteration_mode: str | None = None,
    materia: str = "",
    delito: str = "",
) -> ValidationReport:
    """
    Valida texto generado antes de exportar o cerrar revisión.

    ``iteration_mode``: ``solo_correcciones`` relaja estructura; ``resolucion_completa`` no.
    """
    report = ValidationReport()
    body = (text or "").strip()
    if not body:
        report.findings.append(
            ValidationFinding("empty", "No hay texto para validar.", "error")
        )
        return report

    for code, pat, msg in _METATEXTO_PATTERNS:
        if pat.search(body):
            report.findings.append(ValidationFinding(code, msg, "error"))

    if _BROKEN_CITATION.search(body):
        report.findings.append(
            ValidationFinding(
                "cita_rota",
                "Detectada cita con numeración sospechosa (p. ej. N.° 00) o marcador pendiente mal cerrado.",
                "warning",
            )
        )

    p = (postura or "").strip().lower()
    if p.startswith("confirmar"):
        tail = _resolutive_tail(body)
        if _REVOCATORY_DISPOSITIVO.search(tail) and not _CONFIRMATORY_DISPOSITIVO.search(tail):
            report.findings.append(
                ValidationFinding(
                    "postura_confirmar",
                    "La postura es CONFIRMAR, pero el tramo resolutivo sugiere revocación o modificación "
                    "de la sentencia apelada.",
                    "error",
                )
            )

    full_act = expect_full_act and iteration_mode != "solo_correcciones"
    if full_act and len(body) >= 700:
        missing: list[str] = []
        if not _STRUCTURE_VISTOS.search(body):
            missing.append("Vistos")
        if not _STRUCTURE_CONSIDERANDO.search(body):
            missing.append("Considerando(s)")
        if not _STRUCTURE_RESUELVE.search(body):
            missing.append("Resuelve")
        if missing:
            report.findings.append(
                ValidationFinding(
                    "estructura_incompleta",
                    "Faltan rótulos procesales esperados: " + ", ".join(missing) + ".",
                    "warning",
                )
            )

    corpus_norm = _norm(source_corpus)
    if corpus_norm:
        for cite in _extract_citations(body):
            if not _citation_in_corpus(cite, corpus_norm):
                report.findings.append(
                    ValidationFinding(
                        "cita_sin_respaldo",
                        f"La cita «{cite}» no aparece en las fuentes embebidas del prompt "
                        f"(plantilla, bloques 4–5, bibliografía o instrucciones).",
                        "warning",
                    )
                )

    if tipo and full_act and len(body) >= 400:
        tl = tipo.strip().lower()
        if "sentencia" in tl and not re.search(r"(?i)sentencia\s+de\s+vista", body[:2500]):
            report.findings.append(
                ValidationFinding(
                    "rotulo_tipo",
                    f"El tipo pedido («{tipo}») no muestra claramente el rótulo «Sentencia de Vista» "
                    "en el encabezado.",
                    "warning",
                )
            )

    if full_act:
        _validate_cargos_mp_section(body, delito=delito, report=report)

    return report
