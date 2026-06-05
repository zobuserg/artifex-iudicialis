from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


class PromptInvariantTests(unittest.TestCase):
    """Candados de contenido: reglas generales que no deben desaparecer del motor."""

    def _read(self, rel: str) -> str:
        return (ROOT / rel).read_text(encoding="utf-8", errors="replace")

    def assertContainsAll(self, text: str, needles: list[str], *, where: str) -> None:
        missing = [needle for needle in needles if needle not in text]
        self.assertFalse(missing, f"Faltan invariantes en {where}: {missing}")

    def test_claude_worker_keeps_transversal_judicial_rules(self) -> None:
        text = self._read("app/core/claude_worker.py")
        self.assertContainsAll(
            text,
            [
                "Estas reglas generales se aplican en TODOS los casos",
                "resolución judicial",
                "penal y constitucional",
                "Perú",
                "apelación",
                "Vistos, Considerando(s)",
                "tercera persona impersonal",
                "Redacción judicial clara",
                "frases preferentemente breves",
                "Cada considerando debe cumplir una función verificable",
                "Modo de síntesis jurídica",
                "No sacrifiques fundamentación por brevedad",
                "depuración interna",
                "La postura indicada por el magistrado es vinculante",
                "CONFIRMAR, el razonamiento y la parte resolutiva deben confirmar",
                "prohibido revocarla",
                "fundamentos del recurso de apelación debe ser estrictamente descriptivo",
                "solo agravios, expresiones y argumentos que consten",
                "La absolución de agravios se hace únicamente sobre agravios surgidos del recurso de apelación",
                "alegatos finales de primera instancia",
                "argumentos consignados en la sentencia apelada",
                "datos del expediente no son parte del razonamiento ni del cuerpo resolutivo",
                "encabezado previo al rótulo",
                "Auto de Vista",
                "Sentencia de Vista",
                "extráelos de la documentación",
                "lugar y fecha",
                "Vistos",
                "no se oponga a la",
                "normativo > jurisprudencial > doctrinal",
                "00728-2008-PHC/TC",
                "STC Exp. N.° 01747-2013-PA/TC",
                "test de proporcionalidad",
                "Nunca inventes fuentes",
                "Test de pertinencia obligatorio",
                "No uses una casación real para una regla distinta",
                "encabezado previo",
                "instrucción general de materia",
                "instrucción particular",
                "rules_for_untrusted_sources",
                "wrap_untrusted_document",
                "CARGOS_MP_LITERAL_ES",
                "transcripción literal",
                "solicitud_inicial",
            ],
            where="app/core/claude_worker.py",
        )

    def test_cursor_prompt_keeps_same_transversal_rules(self) -> None:
        text = self._read("app/core/file_manager.py")
        self.assertContainsAll(
            text,
            [
                "Estas reglas generales se aplican en TODOS los casos",
                "Tipo: resolución judicial",
                "Ámbito: penal y constitucional",
                "País/ordenamiento: Perú",
                "Instancia: apelación",
                "Considerandos numerados",
                "Redacción judicial clara",
                "frases preferentemente breves",
                "Cada considerando debe cumplir una función verificable",
                "Modo de síntesis jurídica",
                "No sacrifiques fundamentación por brevedad",
                "depuración interna",
                "La postura indicada por el magistrado es vinculante",
                "si se ordena",
                "prohibido revocarla",
                "fundamentos del recurso de apelación debe ser estrictamente descriptivo",
                "solo agravios, expresiones y argumentos que consten",
                "La absolución de agravios se hace únicamente sobre agravios surgidos del recurso de apelación",
                "alegatos finales de primera instancia",
                "argumentos consignados en la sentencia apelada",
                "datos del expediente no son parte del razonamiento ni del cuerpo resolutivo",
                "encabezado previo al rótulo",
                "Auto de Vista",
                "Sentencia de Vista",
                "extráelos de la documentación",
                "lugar y fecha",
                "Vistos",
                "no se oponga a la particularidad",
                "normativo > jurisprudencial > doctrinal",
                "STC 00728-2008-PHC/TC",
                "STC Exp. N.° 01747-2013-PA/TC",
                "test de proporcionalidad",
                "Nunca inventes fuentes",
                "Test de pertinencia obligatorio",
                "No uses una casación real para una regla distinta",
                "encabezado previo",
                "BLOQUE 2 · INSTRUCCIÓN PERMANENTE",
                "rules_for_untrusted_sources",
                "CARGOS_MP_LITERAL_ES",
                "transcripción literal",
            ],
            where="app/core/file_manager.py",
        )

    def test_cursor_rule_documents_lock_and_unlock_policy(self) -> None:
        text = self._read(".cursor/rules/proteccion-motor-wikijuez.mdc")
        self.assertContainsAll(
            text,
            [
                "Permitido Sin Abrir Candado",
                "Candado: Requiere Orden Expresa",
                "autorizo modificar codigo",
                "abre candado",
                "app/core/claude_worker.py",
                "app/core/file_manager.py",
                "01_raw/",
                "02_wiki/",
            ],
            where=".cursor/rules/proteccion-motor-wikijuez.mdc",
        )

    def test_claude_retry_delay_never_goes_negative(self) -> None:
        qtcore = types.ModuleType("PyQt6.QtCore")
        qtcore.QThread = type("QThread", (), {})
        qtcore.pyqtSignal = lambda *args, **kwargs: object()
        pyqt6 = types.ModuleType("PyQt6")
        pyqt6.QtCore = qtcore

        sys.modules.pop("app.core.claude_worker", None)
        with patch.dict(sys.modules, {"PyQt6": pyqt6, "PyQt6.QtCore": qtcore}):
            from app.core import claude_worker

            with patch.dict(
                "os.environ",
                {
                    "ADIUTOR_STREAM_RETRY_BASE_SEC": "-2",
                    "ADIUTOR_STREAM_RETRY_MAX_SEC": "-2",
                },
            ):
                self.assertGreaterEqual(claude_worker.resolution_stream_retry_base_sec(), 0.5)
                self.assertGreaterEqual(claude_worker.resolution_stream_retry_max_sec(), 1.0)
                self.assertGreaterEqual(claude_worker.resolution_stream_retry_delay_sec(1), 0.5)
                self.assertGreaterEqual(claude_worker.resolution_stream_retry_delay_sec(2), 0.5)

    def test_pdf_native_auto_skip_threshold_is_safe_by_default(self) -> None:
        qtcore = types.ModuleType("PyQt6.QtCore")
        qtcore.QThread = type("QThread", (), {})
        qtcore.pyqtSignal = lambda *args, **kwargs: object()
        pyqt6 = types.ModuleType("PyQt6")
        pyqt6.QtCore = qtcore

        sys.modules.pop("app.core.claude_worker", None)
        with patch.dict(sys.modules, {"PyQt6": pyqt6, "PyQt6.QtCore": qtcore}):
            from app.core import claude_worker

            with patch.dict("os.environ", {}, clear=True):
                self.assertEqual(
                    claude_worker._env_api_pdf_auto_skip_total_bytes(),
                    6 * 1024 * 1024,
                )
            with patch.dict("os.environ", {"ADIUTOR_API_PDF_AUTO_SKIP_TOTAL_MB": "-2"}):
                self.assertEqual(claude_worker._env_api_pdf_auto_skip_total_bytes(), 0)
            with patch.dict("os.environ", {"ADIUTOR_API_PDF_AUTO_SKIP_TOTAL_MB": "0"}):
                self.assertEqual(claude_worker._env_api_pdf_auto_skip_total_bytes(), 0)

    def test_critical_unusable_extraction_blocks_generation_prompt(self) -> None:
        qtcore = types.ModuleType("PyQt6.QtCore")
        qtcore.QThread = type("QThread", (), {})
        qtcore.pyqtSignal = lambda *args, **kwargs: object()
        pyqt6 = types.ModuleType("PyQt6")
        pyqt6.QtCore = qtcore

        sys.modules.pop("app.core.claude_worker", None)
        with patch.dict(sys.modules, {"PyQt6": pyqt6, "PyQt6.QtCore": qtcore}):
            from app.core import claude_worker

            with self.assertRaisesRegex(RuntimeError, "No se enviará a Claude todavía"):
                claude_worker.build_enriched_prompt(
                    plantilla_path=None,
                    slots={"solicitud_inicial": [Path("fuentes/requerimiento_ilegible.pdf")]},
                    slot_labels={"solicitud_inicial": "Requerimiento fiscal"},
                    bibliografia=[],
                    instruccion_general="",
                    instruccion_particular="",
                    postura="Confirmar",
                    postura_personalizada="",
                    agravios="",
                    expediente="",
                    imputados="",
                    delito="",
                    agraviado="",
                    juzgado="",
                    materia_label="Prisión preventiva",
                    modo="generar",
                    borrador_path="",
                    folder_name="prision_preventiva/caso_test",
                    caso_num="test",
                    tipo="Auto de Vista",
                )


if __name__ == "__main__":
    unittest.main()
