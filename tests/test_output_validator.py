from __future__ import annotations

import unittest

from app.core.output_validator import validate_resolution_output


class OutputValidatorTests(unittest.TestCase):
    def test_ok_minimal_correction(self) -> None:
        r = validate_resolution_output(
            "Sustituto — fundamento III\n\nTexto corregido del considerando.",
            iteration_mode="solo_correcciones",
            expect_full_act=False,
        )
        self.assertTrue(r.ok)

    def test_metatexto_is_error(self) -> None:
        r = validate_resolution_output(
            "VISTOS\n\nWikiJuez informa que no hay jurisprudencia.\n\nRESUELVE: confirmar.",
            postura="Confirmar",
            source_corpus="",
        )
        self.assertTrue(r.has_errors)
        self.assertTrue(r.blocks_export)

    def test_confirmar_with_revocacion_is_error(self) -> None:
        r = validate_resolution_output(
            "VISTOS\n\nCONSIDERANDO: ...\n\nRESUELVE:\nSE REVOCA LA SENTENCIA APELADA.",
            postura="Confirmar",
            source_corpus="",
        )
        self.assertTrue(r.has_errors)

    def test_missing_structure_is_warning(self) -> None:
        r = validate_resolution_output(
            "Texto largo " * 120,
            postura="Revocar",
            source_corpus="",
            expect_full_act=True,
        )
        self.assertTrue(r.has_warnings)
        self.assertFalse(r.blocks_export)

    def test_citation_not_in_corpus_is_warning(self) -> None:
        r = validate_resolution_output(
            "VISTOS\n\nCONSIDERANDO: conforme a STC Exp. N.° 9999-2099-PHC/TC.\n\nRESUELVE: confirmar.",
            postura="Confirmar",
            source_corpus="normas del código penal",
        )
        self.assertTrue(r.has_warnings)
        codes = {f.code for f in r.findings}
        self.assertIn("cita_sin_respaldo", codes)

    def test_citation_in_corpus_passes(self) -> None:
        corpus = "Precedente STC Exp. N.° 00728-2008-PHC/TC aplicable."
        r = validate_resolution_output(
            "VISTOS\n\nCONSIDERANDO: STC Exp. N.° 00728-2008-PHC/TC.\n\nRESUELVE: confirmar.",
            postura="Confirmar",
            source_corpus=corpus,
        )
        self.assertFalse(any(f.code == "cita_sin_respaldo" for f in r.findings))

    def test_pp_section_ii_declaracion_is_warning(self) -> None:
        acto = (
            "VISTOS\n\n"
            "II. HECHOS IMPUTADOS POR EL MINISTERIO PÚBLICO\n\n"
            "Circunstancias posteriores: en su declaración el imputado admitió participar en el robo.\n\n"
            "III. AGRAVIOS\n\n"
            "CONSIDERANDO: ...\n\nRESUELVE: confirmar."
        )
        r = validate_resolution_output(
            acto,
            postura="Confirmar",
            delito="Receptación agravada",
        )
        codes = {f.code for f in r.findings}
        self.assertIn("pp_ii_declaracion_imputado", codes)

    def test_pp_calificacion_art194_incompleta_is_error(self) -> None:
        acto = (
            "VISTOS\n\n"
            "II. HECHOS IMPUTADOS POR EL MINISTERIO PÚBLICO\n\n"
            "Calificación jurídica: receptación agravada; pena no será menor de seis años "
            "de pena privativa de libertad.\n\n"
            "III. AGRAVIOS\n\n"
            "CONSIDERANDO: ...\n\nRESUELVE: confirmar."
        )
        r = validate_resolution_output(
            acto,
            postura="Confirmar",
            delito="Receptación agravada",
        )
        self.assertTrue(r.has_errors)
        self.assertTrue(any(f.code == "pp_calificacion_art194_incompleta" for f in r.findings))

    def test_pp_calificacion_completa_passes(self) -> None:
        acto = (
            "VISTOS\n\n"
            "II. HECHOS IMPUTADOS POR EL MINISTERIO PÚBLICO\n\n"
            "Calificación jurídica: artículo 194 CP — quien adquiere, recibe, oculta o "
            "facilita bienes de procedencia delictuosa; agravante artículo 195; artículo 427 CP "
            "— uso de documento público falso.\n\n"
            "III. AGRAVIOS\n\n"
            "CONSIDERANDO: ...\n\nRESUELVE: confirmar."
        )
        r = validate_resolution_output(
            acto,
            postura="Confirmar",
            delito="Receptación agravada",
        )
        self.assertFalse(any(f.code == "pp_calificacion_art194_incompleta" for f in r.findings))


if __name__ == "__main__":
    unittest.main()
