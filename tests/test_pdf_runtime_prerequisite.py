import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
DIAGNOSTIC = ROOT / "scripts" / "check_pdf_runtime.py"


class PdfRuntimePrerequisiteTests(unittest.TestCase):
    def test_railpack_declares_required_runtime_packages(self):
        config = json.loads((ROOT / "railway.json").read_text(encoding="utf-8"))
        packages = config["build"]["variables"]["RAILPACK_DEPLOY_APT_PACKAGES"].split()
        self.assertEqual(
            packages,
            ["libreoffice", "poppler-utils", "fontconfig", "fonts-dejavu-core", "fonts-liberation2"],
        )
        self.assertEqual(config["deploy"]["startCommand"], "uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000}")
        self.assertEqual(config["deploy"]["numReplicas"], 1)

    def test_railpack_package_declaration_cannot_omit_a_required_package(self):
        config = json.loads((ROOT / "railway.json").read_text(encoding="utf-8"))
        packages = set(config["build"]["variables"]["RAILPACK_DEPLOY_APT_PACKAGES"].split())
        for required in ("libreoffice", "poppler-utils", "fontconfig", "fonts-dejavu-core", "fonts-liberation2"):
            with self.subTest(required=required):
                self.assertIn(required, packages)

    def test_pypdf_is_pinned_and_stage75_still_excludes_pdf(self):
        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        self.assertIn("pypdf==5.9.0", requirements)
        stage75 = (ROOT / "api" / "record_governed_reports.py").read_text(encoding="utf-8")
        self.assertIn('OUTPUT_FORMATS = {"docx", "html"}', stage75)
        self.assertNotIn('OUTPUT_FORMATS = {"docx", "html", "pdf"}', stage75)

    def test_diagnostic_has_required_commands_and_fonts(self):
        source = DIAGNOSTIC.read_text(encoding="utf-8")
        for value in ("libreoffice", "soffice", "pdfinfo", "pdftotext", "fc-list", "DejaVu Sans", "Liberation Sans", "pypdf"):
            self.assertIn(value, source)

    def test_libreoffice_aliases_require_one_usable_entry_point(self):
        module = self._load_diagnostic()
        with patch.object(module.shutil, "which", side_effect=lambda command: None if command == "soffice" else "/usr/bin/" + command), patch.object(module, "_command_version", return_value="version"), patch.object(module, "_font_family_available", return_value=True), patch.object(module, "_module_version", return_value=module.REQUIRED_PYPDF_VERSION), patch.object(module, "_temporary_directory_check", return_value=(True, "test")):
            _, ok = module.collect_diagnostic()
        self.assertTrue(ok)

    def test_nonzero_tool_version_command_fails_closed(self):
        module = self._load_diagnostic()
        with patch.object(module.shutil, "which", return_value="/usr/bin/tool"), patch.object(module.subprocess, "run", return_value=type("Result", (), {"returncode": 1, "stdout": "bad", "stderr": "error"})()):
            self.assertIsNone(module._command_version("pdfinfo"))

    def test_missing_any_mandatory_command_fails(self):
        module = self._load_diagnostic()
        real_which = module.shutil.which

        for missing in module.REQUIRED_COMMANDS:
            with self.subTest(missing=missing):
                def missing_command(command, missing=missing):
                    return None if command == missing else real_which(command)

                with patch.object(module.shutil, "which", side_effect=missing_command):
                    report, ok = module.collect_diagnostic()
                self.assertFalse(ok)
                self.assertIsNone(report["commands"][missing]["path"])

    def test_missing_both_libreoffice_aliases_fails(self):
        module = self._load_diagnostic()
        with patch.object(module.shutil, "which", return_value=None):
            _, ok = module.collect_diagnostic()
        self.assertFalse(ok)

    def test_missing_font_fails(self):
        module = self._load_diagnostic()
        with patch.object(module, "_font_family_available", return_value=False):
            report, ok = module.collect_diagnostic()
        self.assertFalse(ok)
        self.assertFalse(report["fonts"]["DejaVu Sans"])

    def test_missing_pypdf_fails(self):
        module = self._load_diagnostic()
        with patch.object(module, "_module_version", return_value=None):
            report, ok = module.collect_diagnostic()
        self.assertFalse(ok)
        self.assertFalse(report["python_modules"]["pypdf"]["importable"])

    def test_wrong_pypdf_version_fails(self):
        module = self._load_diagnostic()
        with patch.object(module, "_module_version", return_value="6.0.0"):
            report, ok = module.collect_diagnostic()
        self.assertFalse(ok)
        self.assertEqual(report["python_modules"]["pypdf"]["version"], "6.0.0")

    def test_version_timeout_fails_without_traceback(self):
        module = self._load_diagnostic()
        with patch.object(module.subprocess, "run", side_effect=subprocess.TimeoutExpired("pdfinfo", 10)):
            self.assertIsNone(module._command_version("pdfinfo"))

    def test_temporary_probe_is_separate_from_data(self):
        module = self._load_diagnostic()
        ok, detail = module._temporary_directory_check()
        self.assertTrue(ok)
        self.assertNotIn("/data", detail)

    def test_diagnostic_is_not_imported_by_application_or_public_routes(self):
        main_source = (ROOT / "api" / "main.py").read_text(encoding="utf-8")
        self.assertNotIn("check_pdf_runtime", main_source)
        self.assertNotIn("check_pdf_runtime", "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "api" / "routes").glob("*.py")))

    def test_stage76_is_not_registered(self):
        ledger = (ROOT / "docs" / "releases" / "CDE_PLATFORM_STAGE_LEDGER.md").read_text(encoding="utf-8")
        self.assertNotRegex(ledger, r"\|\s*76\s*\|")

    def test_diagnostic_output_contains_no_environment_values(self):
        env = os.environ.copy()
        env["STAGE76_TEST_SECRET"] = "must-not-appear"
        completed = subprocess.run([sys.executable, str(DIAGNOSTIC)], env=env, capture_output=True, text=True, check=False)
        self.assertNotIn("must-not-appear", completed.stdout)
        self.assertNotIn("must-not-appear", completed.stderr)

    @staticmethod
    def _load_diagnostic():
        import importlib.util

        spec = importlib.util.spec_from_file_location("check_pdf_runtime", DIAGNOSTIC)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module


if __name__ == "__main__":
    unittest.main()
