import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ADAPTER_PATH = ROOT / "scripts" / "evidence_led_governance_pipeline" / "report_adapter.py"


def load_adapter():
    spec = importlib.util.spec_from_file_location("stage76_result_contract_adapter", ADAPTER_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class Stage76AdapterResultContractTests(unittest.TestCase):
    def setUp(self):
        self.rendering = __import__("api.report_rendering", fromlist=["_read_adapter_result"])
        self.adapter = load_adapter()

    def _valid_files(self, root):
        files = {}
        for format_name in ("docx", "html", "pdf"):
            path = root / f"report.{format_name}"
            path.write_bytes(f"{format_name}-synthetic".encode())
            files[format_name] = path
        return files

    def _valid_result(self, root, digest="a" * 64):
        files = self._valid_files(root)
        return {
            "schema_version": "1",
            "ok": True,
            "phase": "result_serialization",
            "code": "completed",
            "cleanup": "passed",
            "specification_digest": digest,
            "diagnostics": [{
                "format": "pdf",
                "libreoffice_version": "LibreOffice synthetic",
                "pdfinfo_version": "pdfinfo synthetic",
                "pypdf_version": "5.9.0",
                "extraction_backend": "pdftotext",
                "page_count": 1,
                "size_bytes": files["pdf"].stat().st_size,
                "ordered_content": "ok",
                "metadata_attachments_annotations": "ok",
            }],
            "artifacts": [
                {"format": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "size_bytes": path.stat().st_size, "renderer_version": "2.0.0"}
                for name, path in files.items()
            ],
        }

    def test_success_result_is_written_atomically_and_strictly_read(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result_path = root / "adapter-result.json"
            expected = self._valid_result(root)
            self.adapter._write_result(result_path, expected)
            actual = self.rendering._read_adapter_result(result_path, root, "a" * 64)
            self.assertEqual(actual, expected)
            self.assertFalse((root / ".adapter-result.json.tmp").exists())

    def test_artifact_digest_and_requested_format_set_are_verified(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result = self._valid_result(root)
            result_path = root / "adapter-result.json"
            self.adapter._write_result(result_path, result)
            with self.assertRaises(self.rendering.AdapterFailure):
                self.rendering._read_adapter_result(result_path, root, "a" * 64, {"docx", "html"})
            result["artifacts"][0]["sha256"] = "0" * 64
            result_path.write_text(json.dumps(result), encoding="utf-8")
            with self.assertRaises(self.rendering.AdapterFailure):
                self.rendering._read_adapter_result(result_path, root, "a" * 64)

    def test_unknown_fields_and_nested_diagnostics_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result_path = root / "adapter-result.json"
            result = self._valid_result(root)
            for mutation in (
                lambda value: value.update(extra="secret"),
                lambda value: value["diagnostics"][0].update(extra="secret"),
                lambda value: value["diagnostics"][0].update(format="docx"),
                lambda value: value["artifacts"][0].update(sha256="G" * 64),
            ):
                candidate = json.loads(json.dumps(result))
                mutation(candidate)
                result_path.write_text(json.dumps(candidate), encoding="utf-8")
                with self.assertRaises(self.rendering.AdapterFailure):
                    self.rendering._read_adapter_result(result_path, root, "a" * 64)

    def test_failure_result_preserves_only_controlled_phase_and_code(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result_path = root / "adapter-result.json"
            self.adapter._write_result(result_path, {
                "schema_version": "1", "ok": False, "phase": "pdf_inspection",
                "code": "pdf_metadata_invalid", "cleanup": "failed",
                "specification_digest": "", "diagnostics": [], "artifacts": [],
            })
            result = self.rendering._read_adapter_result(result_path, root, "a" * 64)
            self.assertEqual((result["phase"], result["code"], result["cleanup"]), ("pdf_inspection", "pdf_metadata_invalid", "failed"))
            failure = self.rendering.AdapterFailure(result["phase"], result["code"], result["cleanup"])
            self.assertEqual(str(failure), "governed_report_renderer_failed")
            self.assertNotIn("metadata", str(failure))

    def test_metadata_failure_diagnostic_is_strictly_bounded(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result_path = root / "adapter-result.json"
            self.adapter._write_result(result_path, {
                "schema_version": "1", "ok": False, "phase": "pdf_inspection",
                "code": "pdf_metadata_invalid", "cleanup": "passed",
                "specification_digest": "", "diagnostics": [{
                    "format": "pdf", "failure_field": "/Producer", "failure_reason": "unexpected_value",
                }], "artifacts": [],
            })
            result = self.rendering._read_adapter_result(result_path, root, "a" * 64)
            self.assertEqual(result["diagnostics"], [{"format": "pdf", "failure_field": "/Producer", "failure_reason": "unexpected_value"}])
            for bad in ("/data/private", "raw metadata value"):
                candidate = json.loads(json.dumps(result))
                candidate["diagnostics"][0]["failure_field"] = bad
                result_path.write_text(json.dumps(candidate), encoding="utf-8")
                with self.assertRaises(self.rendering.AdapterFailure):
                    self.rendering._read_adapter_result(result_path, root, "a" * 64)

    def test_action_failure_diagnostic_is_strictly_bounded(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result_path = root / "adapter-result.json"
            result = {
                "schema_version": "1", "ok": False, "phase": "pdf_inspection",
                "code": "pdf_action_invalid", "cleanup": "passed", "specification_digest": "",
                "diagnostics": [{"format": "pdf", "failure_location": "catalog_open_action", "failure_reason": "executable_action"}],
                "artifacts": [],
            }
            self.adapter._write_result(result_path, result)
            self.assertEqual(self.rendering._read_adapter_result(result_path, root, "a" * 64)["diagnostics"], result["diagnostics"])
            for key, value in (("failure_location", "/data/private"), ("failure_reason", "raw object")):
                candidate = json.loads(json.dumps(result))
                candidate["diagnostics"][0][key] = value
                result_path.write_text(json.dumps(candidate), encoding="utf-8")
                with self.assertRaises(self.rendering.AdapterFailure):
                    self.rendering._read_adapter_result(result_path, root, "a" * 64)

    def test_all_controlled_failure_phases_and_codes_round_trip(self):
        cases = (
            ("input_load", "adapter_input_missing"),
            ("input_validation", "adapter_input_invalid"),
            ("specification_validation", "specification_digest_mismatch"),
            ("model_adaptation", "adapter_model_invalid"),
            ("docx_render", "docx_render_failed"),
            ("html_render", "html_render_failed"),
            ("pdf_conversion", "pdf_conversion_failed"),
            ("pdf_inspection", "pdf_invalid"),
            ("cross_format_equivalence", "equivalence_failed"),
            ("artifact_digest", "artifact_digest_failed"),
            ("result_serialization", "adapter_result_write_failed"),
            ("cleanup", "cleanup_failed"),
        )
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result_path = root / "adapter-result.json"
            for phase, code in cases:
                with self.subTest(phase=phase, code=code):
                    self.adapter._write_result(result_path, {
                        "schema_version": "1", "ok": False, "phase": phase,
                        "code": code, "cleanup": "unknown", "specification_digest": "",
                        "diagnostics": [], "artifacts": [],
                    })
                    result = self.rendering._read_adapter_result(result_path, root, "a" * 64)
                    self.assertEqual((result["phase"], result["code"]), (phase, code))

    def test_unknown_phase_or_code_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result_path = root / "adapter-result.json"
            for key, value in (("phase", "not_a_phase"), ("code", "not_a_code")):
                result = self._valid_result(root)
                result[key] = value
                result_path.write_text(json.dumps(result), encoding="utf-8")
                with self.subTest(key=key):
                    with self.assertRaises(self.rendering.AdapterFailure):
                        self.rendering._read_adapter_result(result_path, root, "a" * 64)

    def test_missing_malformed_oversized_and_symlink_results_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result_path = root / "adapter-result.json"
            with self.assertRaises(self.rendering.AdapterFailure):
                self.rendering._read_adapter_result(result_path, root, "a" * 64)
            result_path.write_text("not-json", encoding="utf-8")
            with self.assertRaises(self.rendering.AdapterFailure):
                self.rendering._read_adapter_result(result_path, root, "a" * 64)
            result_path.write_text("x" * (self.rendering.RESULT_MAX_BYTES + 1), encoding="utf-8")
            with self.assertRaises(self.rendering.AdapterFailure):
                self.rendering._read_adapter_result(result_path, root, "a" * 64)
            target = root / "target.json"
            target.write_text(json.dumps(self._valid_result(root)), encoding="utf-8")
            result_path.unlink()
            result_path.symlink_to(target)
            with self.assertRaises(self.rendering.AdapterFailure):
                self.rendering._read_adapter_result(result_path, root, "a" * 64)

    def test_child_failure_result_is_safe_and_does_not_propagate_stderr(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            request = root / "missing.json"
            output = root / "output"
            output.mkdir()
            result_path = root / "adapter-result.json"
            completed = subprocess.run(
                [sys.executable, str(ADAPTER_PATH), str(request), str(output), str(result_path)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 1)
            self.assertEqual(completed.stdout, "")
            self.assertEqual(completed.stderr, "")
            result = json.loads(result_path.read_text(encoding="utf-8"))
            self.assertEqual(set(result), {"schema_version", "ok", "phase", "code", "cleanup", "specification_digest", "diagnostics", "artifacts"})
            self.assertFalse(result["ok"])
            self.assertIn(result["phase"], self.rendering.RESULT_PHASES)
            self.assertIn(result["code"], self.rendering.RESULT_CODES)
            self.assertEqual(result["diagnostics"], [])
            self.assertNotIn("missing.json", result_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
