import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


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
                "diagnostics": [{"format": "pdf", "failure_location": "catalog_open_action", "failure_reason": "executable_action", "failure_step": "open_action_resolution", "failure_structure": "action_dictionary", "failure_operand": "none", "failure_operand_kind": "none", "failure_operand_count": "not_applicable", "failure_operand_kinds": [], "failure_destination_mode": "not_applicable", "failure_trailing_kinds": [], "page_registry_state": "populated", "reference_identity_result": "not_applicable", "resolution_result": "not_applicable", "resolved_target_comparison": "not_applicable", "page_reference_attribute": "indirect_reference"}],
                "artifacts": [],
            }
            self.adapter._write_result(result_path, result)
            self.assertEqual(self.rendering._read_adapter_result(result_path, root, "a" * 64)["diagnostics"], result["diagnostics"])
            for key, value in (("failure_location", "/data/private"), ("failure_reason", "raw object"), ("failure_step", "raw step"), ("failure_structure", "raw structure"), ("failure_operand", "raw operand"), ("failure_operand_kind", "raw kind"), ("failure_operand_count", "seven"), ("failure_operand_kinds", ["raw kind"]), ("failure_destination_mode", "raw mode"), ("failure_trailing_kinds", ["raw kind"]), ("page_registry_state", "raw state"), ("reference_identity_result", "raw identity"), ("resolution_result", "raw resolution"), ("resolved_target_comparison", "raw comparison"), ("page_reference_attribute", "raw attribute")):
                candidate = json.loads(json.dumps(result))
                candidate["diagnostics"][0][key] = value
                result_path.write_text(json.dumps(candidate), encoding="utf-8")
                with self.assertRaises(self.rendering.AdapterFailure):
                    self.rendering._read_adapter_result(result_path, root, "a" * 64)

    def test_unexpected_pdf_diagnostic_is_checkpointed_and_strict(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result_path = root / "adapter-result.json"
            result = {
                "schema_version": "1", "ok": False, "phase": "pdf_inspection",
                "code": "unexpected_adapter_failure", "cleanup": "passed", "specification_digest": "",
                "diagnostics": [{"format": "pdf", "failure_step": "page_reference_attribute", "failure_operation": "read_indirect_reference", "inspection_step": "page_reference_registry", "failure_exception_class": "attribute_error", "failure_boundary": "function_body"}],
                "artifacts": [],
            }
            self.adapter._write_result(result_path, result)
            self.assertEqual(self.rendering._read_adapter_result(result_path, root, "a" * 64)["diagnostics"], result["diagnostics"])
            for key, value in (("failure_step", "raw"), ("failure_operation", "raw"), ("inspection_step", "raw"), ("failure_exception_class", "raw"), ("failure_boundary", "raw"), ("failure_operation", "read_stderr"), ("failure_exception_class", "RuntimeError")):
                candidate = json.loads(json.dumps(result))
                candidate["diagnostics"][0][key] = value
                result_path.write_text(json.dumps(candidate), encoding="utf-8")
                with self.assertRaises(self.rendering.AdapterFailure):
                    self.rendering._read_adapter_result(result_path, root, "a" * 64)

    def test_unexpected_failure_requires_all_bounded_fields(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result_path = root / "adapter-result.json"
            result = {
                "schema_version": "1", "ok": False, "phase": "pdf_inspection",
                "code": "unexpected_adapter_failure", "cleanup": "passed", "specification_digest": "",
                "diagnostics": [{"format": "pdf", "failure_step": "page_reference_attribute", "failure_operation": "read_indirect_reference", "inspection_step": "page_reference_registry", "failure_exception_class": "attribute_error", "failure_boundary": "function_body"}],
                "artifacts": [],
            }
            for field in ("failure_step", "failure_operation", "inspection_step", "failure_exception_class", "failure_boundary"):
                candidate = json.loads(json.dumps(result))
                del candidate["diagnostics"][0][field]
                result_path.write_text(json.dumps(candidate), encoding="utf-8")
                with self.assertRaises(self.rendering.AdapterFailure) as raised:
                    self.rendering._read_adapter_result(result_path, root, "a" * 64)
                self.assertEqual(raised.exception.code, "adapter_return_contract_invalid")

            for value in ("unknown", "raw"):
                candidate = json.loads(json.dumps(result))
                candidate["diagnostics"][0]["inspection_step"] = value
                result_path.write_text(json.dumps(candidate), encoding="utf-8")
                with self.assertRaises(self.rendering.AdapterFailure) as raised:
                    self.rendering._read_adapter_result(result_path, root, "a" * 64)
                self.assertEqual(raised.exception.code, "adapter_return_contract_invalid")

    def test_parent_subprocess_boundary_preserves_unexpected_diagnostic(self):
        specification = {"publication_engine_version": "2.0.0", "requested_formats": []}
        digest = __import__("api.record_governed_reports", fromlist=["canonical_json"]).canonical_json(specification)
        digest = hashlib.sha256(digest.encode()).hexdigest()
        diagnostic = {"format": "pdf", "failure_step": "page_reference_attribute", "failure_operation": "read_indirect_reference", "inspection_step": "page_reference_registry", "failure_exception_class": "attribute_error", "failure_boundary": "function_body"}

        class Process:
            returncode = 1

            def communicate(self, timeout=None):
                result_path = Path(command[-1])
                result_path.write_text(json.dumps({"schema_version": "1", "ok": False, "phase": "pdf_inspection", "code": "unexpected_adapter_failure", "cleanup": "passed", "specification_digest": "", "diagnostics": [diagnostic], "artifacts": []}), encoding="utf-8")
                return "", ""

        with tempfile.TemporaryDirectory() as temp:
            command = []
            def spawn(arguments, **kwargs):
                command[:] = arguments
                return Process()
            with self.assertRaises(self.rendering.AdapterFailure) as raised, patch.object(self.rendering.subprocess, "Popen", side_effect=spawn):
                self.rendering.render_frozen_report(specification, digest, Path(temp) / "out")
            self.assertEqual(raised.exception.code, "unexpected_adapter_failure")
            self.assertEqual(raised.exception.diagnostic, diagnostic)

    def test_parent_accepts_current_child_validation_return_shape(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result_path = root / "adapter-result.json"
            diagnostic = {
                "format": "pdf", "failure_step": "pdf_inspection", "failure_operation": "validate_pdf",
                "inspection_step": "validation_return_enter", "failure_exception_class": "value_error",
                "failure_boundary": "function_body",
            }
            result = {
                "schema_version": "1", "ok": False, "phase": "pdf_inspection",
                "code": "unexpected_adapter_failure", "cleanup": "passed", "specification_digest": "",
                "diagnostics": [diagnostic], "artifacts": [],
            }
            self.adapter._write_result(result_path, result)
            parsed = self.rendering._read_adapter_result(result_path, root, "a" * 64)
            self.assertEqual(parsed["diagnostics"], [diagnostic])

    def test_real_subprocess_child_writer_round_trips_validation_return_shape(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result_path = root / "adapter-result.json"
            diagnostic = {
                "format": "pdf", "failure_step": "pdf_inspection", "failure_operation": "validate_pdf",
                "inspection_step": "validation_return_enter", "failure_exception_class": "value_error",
                "failure_boundary": "function_body",
            }
            result = {
                "schema_version": "1", "ok": False, "phase": "pdf_inspection",
                "code": "unexpected_adapter_failure", "cleanup": "passed", "specification_digest": "",
                "diagnostics": [diagnostic], "artifacts": [],
            }
            child = (
                "import importlib.util, json, sys; "
                "spec=importlib.util.spec_from_file_location('child_adapter', sys.argv[2]); "
                "module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module); "
                "module._write_result(__import__('pathlib').Path(sys.argv[1]), json.loads(sys.argv[3]))"
            )
            completed = subprocess.run(
                [sys.executable, "-c", child, str(result_path), str(ADAPTER_PATH), json.dumps(result)],
                cwd=ROOT, capture_output=True, text=True, check=False,
            )
            self.assertEqual(completed.returncode, 0)
            parsed = self.rendering._read_adapter_result(result_path, root, "a" * 64)
            self.assertEqual(parsed["diagnostics"], [diagnostic])

    def test_outer_child_failure_boundary_round_trips_bounded_diagnostic(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result_path = root / "adapter-result.json"
            child = (
                "import importlib.util, sys; "
                "spec=importlib.util.spec_from_file_location('child_adapter', sys.argv[2]); "
                "module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module); "
                "module._write_result(__import__('pathlib').Path(sys.argv[1]), module._unexpected_failure_result(ValueError()))"
            )
            completed = subprocess.run(
                [sys.executable, "-c", child, str(result_path), str(ADAPTER_PATH)],
                cwd=ROOT, capture_output=True, text=True, check=False,
            )
            self.assertEqual(completed.returncode, 0)
            parsed = self.rendering._read_adapter_result(result_path, root, "a" * 64)
            self.assertEqual(parsed["phase"], "result_serialization")
            self.assertEqual(parsed["code"], "unexpected_adapter_failure")
            self.assertEqual(parsed["diagnostics"], [{
                "format": "pdf",
                "failure_step": "result_serialization",
                "failure_operation": "unknown",
                "failure_exception_class": "value_error",
                "inspection_step": "validation_result_construction",
                "failure_boundary": "result_serialization",
            }])

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
