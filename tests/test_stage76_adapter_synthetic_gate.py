import hashlib
import importlib.util
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_stage76_adapter_synthetic.py"


def load_checker():
    spec = importlib.util.spec_from_file_location("check_stage76_adapter_synthetic", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class Stage76AdapterSyntheticGateTests(unittest.TestCase):
    def test_wrapper_has_three_fail_fast_gates_in_order(self):
        wrapper = (ROOT / "scripts" / "check_pdf_predeploy_gate.sh").read_text(encoding="utf-8")
        self.assertIn("set -eu", wrapper)
        commands = [
            "python scripts/check_pdf_runtime.py",
            "python scripts/check_pdf_synthetic_conversion.py",
            "python scripts/check_stage76_adapter_synthetic.py",
        ]
        positions = [wrapper.index(command) for command in commands]
        self.assertEqual(positions, sorted(positions))
        self.assertNotIn("|| true", wrapper)
        self.assertNotIn("; true", wrapper)

    def test_each_failed_gate_stops_the_following_gate(self):
        wrapper = ROOT / "scripts" / "check_pdf_predeploy_gate.sh"
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            fake_python = directory / "python"
            log = directory / "calls.log"
            fake_python.write_text(
                "#!/bin/sh\n"
                "printf '%s\\n' \"$1\" >> \"$LOG\"\n"
                "case \"$FAIL_AT:$1\" in\n"
                "  runtime:scripts/check_pdf_runtime.py|synthetic:scripts/check_pdf_synthetic_conversion.py|adapter:scripts/check_stage76_adapter_synthetic.py) exit 1 ;;\n"
                "esac\n",
                encoding="utf-8",
            )
            fake_python.chmod(0o700)
            base_env = {"PATH": f"{directory}:/usr/bin:/bin", "LOG": str(log)}
            for failure, expected in (("runtime", ["scripts/check_pdf_runtime.py"]), ("synthetic", ["scripts/check_pdf_runtime.py", "scripts/check_pdf_synthetic_conversion.py"]), ("adapter", ["scripts/check_pdf_runtime.py", "scripts/check_pdf_synthetic_conversion.py", "scripts/check_stage76_adapter_synthetic.py"]), ("", ["scripts/check_pdf_runtime.py", "scripts/check_pdf_synthetic_conversion.py", "scripts/check_stage76_adapter_synthetic.py"])):
                with self.subTest(failure=failure):
                    log.unlink(missing_ok=True)
                    environment = {**base_env, "FAIL_AT": failure}
                    completed = subprocess.run(["sh", str(wrapper)], cwd=ROOT, env=environment, capture_output=True, text=True, check=False)
                    self.assertEqual(completed.returncode, 1 if failure else 0)
                    self.assertEqual(log.read_text(encoding="utf-8").splitlines(), expected)

    def test_specification_is_immutable_and_has_all_synthetic_content_types(self):
        checker = load_checker()
        specification = checker._synthetic_specification()
        before = checker._canonical(specification)
        checker._validate_specification(specification)
        self.assertEqual(before, checker._canonical(specification))
        self.assertEqual(
            [block["content_type"] for block in specification["sections"][0]["blocks"]],
            ["verbatim_source", "faithful_paraphrase", "administrative_summary", "qualification", "limitation", "redaction_notice"],
        )

    def test_invalid_specification_is_rejected_before_adapter(self):
        checker = load_checker()
        with patch.object(checker, "_synthetic_specification", return_value={"requested_formats": ["pdf"]}), patch.object(checker, "_confined_temporary_directory") as temporary:
            with self.assertRaisesRegex(checker.AdapterGateError, "synthetic_specification_invalid"):
                checker.run_check()
            temporary.assert_not_called()

    def _fake_render(self, specification, digest, root):
        self.assertEqual(digest, hashlib.sha256(self._checker._canonical(specification).encode()).hexdigest())
        self.assertEqual(specification["requested_formats"], ["docx", "html", "pdf"])
        docx_path = root / "report.docx"
        html_path = root / "report.html"
        pdf_path = root / "report.pdf"
        xml = "<w:document><w:body>" + "".join(f"<w:t>{marker}</w:t>" for marker in self._checker.MARKERS) + "</w:body></w:document>"
        with zipfile.ZipFile(docx_path, "w") as package:
            package.writestr("word/document.xml", xml)
        html_path.write_text("<html><body>" + " ".join(self._checker.MARKERS) + "</body></html>", encoding="utf-8")
        pdf_path.write_bytes(b"%PDF-1.7 synthetic")
        artifacts = []
        for format_name, path in (("docx", docx_path), ("html", html_path), ("pdf", pdf_path)):
            artifacts.append({"format": format_name, "path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "size_bytes": path.stat().st_size, "renderer_version": "2.0.0"})
        return {
            "specification_digest": digest,
            "artifacts": artifacts,
            "diagnostics": [{"format": "pdf", "libreoffice_version": "synthetic", "pdfinfo_version": "synthetic", "pypdf_version": "5.9.0", "extraction_backend": "pdftotext", "page_count": 1, "size_bytes": pdf_path.stat().st_size, "ordered_content": "ok", "metadata_attachments_annotations": "ok"}],
        }

    def test_run_check_uses_governed_bridge_and_cleans_outputs(self):
        checker = load_checker()
        self._checker = checker
        with patch("api.report_rendering.render_frozen_report", side_effect=self._fake_render) as render:
            checker.run_check()
        render.assert_called_once()

    def test_direct_invocation_fails_closed_without_traceback(self):
        completed = subprocess.run([sys.executable, str(SCRIPT)], cwd=ROOT, capture_output=True, text=True, check=False)
        self.assertEqual(completed.returncode, 1)
        self.assertRegex(completed.stderr, r"^stage76_adapter_gate=failed code=[a-z_]+$")
        self.assertNotIn("Traceback", completed.stderr)

    def test_adapter_input_mutation_is_rejected(self):
        checker = load_checker()

        def mutate(specification, _digest, _root):
            specification["title"] = "MUTATED"
            return {}

        with patch("api.report_rendering.render_frozen_report", side_effect=mutate):
            with self.assertRaisesRegex(checker.AdapterGateError, "specification_mutated"):
                checker.run_check()

    def test_artifact_omission_digest_mismatch_and_outside_root_are_rejected(self):
        checker = load_checker()
        self._checker = checker
        specification = checker._synthetic_specification()
        digest = checker._digest(specification)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            valid = self._fake_render(specification, digest, root)
            for name, result in (
                ("missing", {**valid, "artifacts": valid["artifacts"][:2]}),
                ("digest", {**valid, "artifacts": [{**valid["artifacts"][0], "sha256": "0" * 64}, *valid["artifacts"][1:]]}),
            ):
                with self.subTest(case=name):
                    with self.assertRaises(checker.AdapterGateError):
                        checker._validate_result(result, specification, digest, root)
            outside = root.parent / "stage76-outside.pdf"
            outside.write_bytes(b"outside")
            try:
                changed = {**valid, "artifacts": [{**valid["artifacts"][2], "path": str(outside)}, *valid["artifacts"][0:2]]}
                with self.assertRaisesRegex(checker.AdapterGateError, "artifact_path_invalid"):
                    checker._validate_result(changed, specification, digest, root)
            finally:
                outside.unlink()

    def test_external_access_guard_blocks_database_and_network(self):
        checker = load_checker()
        with checker._prohibit_external_access():
            with self.assertRaisesRegex(checker.AdapterGateError, "prohibited_external_access"):
                sqlite3.connect(":memory:")

            with self.assertRaisesRegex(checker.AdapterGateError, "prohibited_external_access"):
                checker.socket.socket()

            with self.assertRaisesRegex(checker.AdapterGateError, "prohibited_route_import"):
                __import__("api.routes.records")

    def test_external_access_guard_allows_safe_engine_import_and_local_executable(self):
        checker = load_checker()
        with checker._prohibit_external_access():
            from api.report_rendering import render_frozen_report

            self.assertTrue(callable(render_frozen_report))
            completed = subprocess.run([sys.executable, "-c", "print('ok')"], capture_output=True, text=True, check=True)
        self.assertEqual(completed.stdout.strip(), "ok")

    def test_phase_failures_use_stable_specific_codes(self):
        checker = load_checker()
        with patch.object(checker, "_synthetic_specification", side_effect=ValueError("private details")):
            with self.assertRaisesRegex(checker.AdapterGateError, "synthetic_specification_failed"):
                checker.run_check()
        with patch.object(checker, "_synthetic_specification", return_value=checker._synthetic_specification()), patch.object(checker, "_digest", side_effect=ValueError("private details")):
            with self.assertRaisesRegex(checker.AdapterGateError, "specification_digest_failed"):
                checker.run_check()
        for error, expected in ((ValueError("renderer failed"), "adapter_reported_failure"), (OSError("renderer unavailable"), "adapter_invocation_failed"), (RuntimeError("unexpected"), "unexpected_adapter_error")):
            with self.subTest(expected=expected), patch("api.report_rendering.render_frozen_report", side_effect=error):
                with self.assertRaisesRegex(checker.AdapterGateError, expected):
                    checker.run_check()

    def test_malformed_adapter_return_uses_contract_code(self):
        checker = load_checker()
        for result in (None, {"specification_digest": "bad", "artifacts": "not-a-list"}, {"specification_digest": "bad", "artifacts": []}):
            with self.subTest(result=result):
                with patch("api.report_rendering.render_frozen_report", return_value=result):
                    with self.assertRaises(checker.AdapterGateError):
                        checker.run_check()

    def test_data_path_access_is_not_permitted_by_checker_contract(self):
        checker = load_checker()
        original_read_text = Path.read_text

        def guarded_read_text(path, *args, **kwargs):
            if str(path).startswith("/data"):
                raise checker.AdapterGateError("prohibited_data_access")
            return original_read_text(path, *args, **kwargs)

        with patch.object(Path, "read_text", guarded_read_text):
            with self.assertRaisesRegex(checker.AdapterGateError, "prohibited_data_access"):
                Path("/data/records.db").read_text()

    def test_failure_diagnostic_is_bounded_and_does_not_include_paths_or_content(self):
        checker = load_checker()
        with patch.object(checker, "run_check", side_effect=checker.AdapterGateError("temporary_directory_not_confined")):
            with patch("builtins.print") as output:
                self.assertEqual(checker.main(), 1)
        rendered = " ".join(str(call) for call in output.call_args_list)
        self.assertIn("stage76_adapter_gate=failed code=temporary_directory_not_confined", rendered)
        self.assertNotIn("/", rendered)
        self.assertNotIn("STAGE76_", rendered)
        self.assertNotIn("adapter_execution_failed", SCRIPT.read_text(encoding="utf-8"))

    def test_no_application_route_or_gate_imports_checker(self):
        main_source = (ROOT / "api" / "main.py").read_text(encoding="utf-8")
        route_source = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "api" / "routes").glob("*.py"))
        self.assertNotIn("check_stage76_adapter_synthetic", main_source)
        self.assertNotIn("check_stage76_adapter_synthetic", route_source)

    def test_no_stage761_or_ledger_status_change(self):
        ledger = (ROOT / "docs" / "releases" / "CDE_PLATFORM_STAGE_LEDGER.md").read_text(encoding="utf-8")
        self.assertNotIn("Stage 76.1", ledger)
        self.assertRegex(ledger, r"\|\s*76\s*\|.*Implemented · pending merge · pending deployment")


if __name__ == "__main__":
    unittest.main()
