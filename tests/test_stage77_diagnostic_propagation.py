import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from api import governed_report_diagnostics as diagnostics
from api import governed_report_jobs as jobs
from api import record_governed_reports as reports
from api.report_rendering import AdapterFailure


class BoundedDiagnosticContractTests(unittest.TestCase):
    def test_contract_rejects_raw_or_malformed_values(self):
        value = diagnostics.make_diagnostic(
            phase="validation",
            operation="pdf_validation",
            checkpoint="validation",
            code="pdf_invalid",
            cleanup_status="passed",
            adapter_invocation_entered=True,
            adapter_process_started=True,
            adapter_result_received=True,
            format_category="pdf",
        )
        self.assertEqual(set(value), diagnostics.DIAGNOSTIC_FIELDS)
        self.assertNotIn("message", value)
        with self.assertRaisesRegex(ValueError, "bounded_diagnostic_contract_invalid"):
            diagnostics.validate_diagnostic({**value, "raw_error": "private detail"})
        with self.assertRaisesRegex(ValueError, "bounded_diagnostic_contract_invalid"):
            diagnostics.validate_diagnostic({**value, "adapter_process_started": 1})
        with self.assertRaisesRegex(ValueError, "bounded_diagnostic_contract_invalid"):
            diagnostics.validate_diagnostic({**value, "adapter_invocation_entered": False, "adapter_process_started": True})
        with self.assertRaisesRegex(ValueError, "bounded_diagnostic_contract_invalid"):
            diagnostics.validate_diagnostic({**value, "adapter_process_started": False, "adapter_result_received": True})
        with self.assertRaisesRegex(ValueError, "bounded_diagnostic_contract_invalid"):
            diagnostics.validate_diagnostic({**value, "failure_checkpoint": "process_started", "adapter_process_started": False})
        with self.assertRaisesRegex(ValueError, "bounded_diagnostic_contract_invalid"):
            diagnostics.validate_diagnostic({**value, "failure_checkpoint": "result_received", "adapter_result_received": False})

    def test_transitional_job2_pair_is_exact_and_current_pair_is_distinct(self):
        transitional_attempt = reports.canonical_json([diagnostics.TRANSITIONAL_DIAGNOSTIC])
        transitional_terminal = reports.canonical_json({
            "phase": "rendering",
            "code": "governed_report_renderer_failed",
            "diagnostic": diagnostics.TRANSITIONAL_DIAGNOSTIC,
            **diagnostics.TRANSITIONAL_DIAGNOSTIC,
        })
        selected = diagnostics.select_diagnostic_contract(attempt_raw=transitional_attempt, terminal_raw=transitional_terminal)
        self.assertEqual(selected["contract_id"], diagnostics.TRANSITIONAL_DIAGNOSTIC_CONTRACT)
        self.assertEqual(selected["attempt_sha256"], diagnostics.TRANSITIONAL_ATTEMPT_SHA256)
        self.assertEqual(selected["terminal_sha256"], diagnostics.TRANSITIONAL_TERMINAL_SHA256)
        current_terminal = reports.canonical_json({
            "phase": "rendering",
            "operation": "adapter_preparation",
            "checkpoint": "starting",
            "code": "adapter_input_invalid",
            "diagnostic": diagnostics.TRANSITIONAL_DIAGNOSTIC,
            **diagnostics.TRANSITIONAL_DIAGNOSTIC,
        })
        current = diagnostics.select_diagnostic_contract(attempt_raw=transitional_attempt, terminal_raw=current_terminal)
        self.assertEqual(current["contract_id"], diagnostics.CURRENT_DIAGNOSTIC_CONTRACT)
        with self.assertRaisesRegex(ValueError, "bounded_diagnostic_contract_invalid"):
            diagnostics.select_diagnostic_contract(attempt_raw=transitional_attempt, terminal_raw=current_terminal.replace("adapter_preparation", "renderer_invocation"))
        with self.assertRaisesRegex(ValueError, "bounded_diagnostic_contract_invalid"):
            diagnostics.select_diagnostic_contract(attempt_raw=transitional_attempt, terminal_raw=current_terminal.replace('"operation":"adapter_preparation"', '"operation":"adapter_launch"'))
        with self.assertRaisesRegex(ValueError, "bounded_diagnostic_contract_invalid"):
            diagnostics.select_diagnostic_contract(attempt_raw=transitional_attempt, terminal_raw=current_terminal.replace('"checkpoint":"starting"', '"checkpoint":"validation"'))
        with self.assertRaisesRegex(ValueError, "bounded_diagnostic_contract_invalid"):
            diagnostics.select_diagnostic_contract(attempt_raw=transitional_attempt, terminal_raw=current_terminal.replace('"failure_code":"adapter_input_invalid"', '"failure_code":"pdf_invalid"', 1))

    def test_adapter_failure_maps_to_bounded_contract_without_detail(self):
        failure = AdapterFailure(
            "pdf_inspection",
            "pdf_invalid",
            "passed",
            {"format": "pdf", "failure_operation": "inspect_pdf", "private": "must not escape"},
            True,
            True,
            True,
        )
        value = failure.diagnostic_payload()
        self.assertEqual(value["failure_operation"], "pdf_validation")
        self.assertEqual(value["failure_code"], "pdf_invalid")
        self.assertTrue(value["adapter_result_received"])
        self.assertNotIn("private", value)

    def test_controlled_adapter_fixture_reproduces_qualification_input_boundary(self):
        from scripts.evidence_led_governance_pipeline import report_adapter

        specification = {
            "title": "Synthetic internal report",
            "purpose": "Bounded adapter diagnosis",
            "specification_schema_version": "1",
            "sections": [],
        }
        qualification = {
            "review_mode": "sole_administrator",
            "disclosure_version": "sole-admin-v1",
            "disclosure": "Independent administrator review did not occur. This report was confirmed and approved by its creator under the declared sole-administrator operating constraint. It remains restricted to authorised internal use.",
            "qualification_id": 4,
            "qualification_digest": "a" * 64,
            "specification_digest": "b" * 64,
            "distribution_restriction": "internal_working",
        }
        with self.assertRaises(report_adapter.AdapterFailure) as raised:
            report_adapter.make_book(specification, qualification)
        self.assertEqual(raised.exception.phase, "specification_validation")
        self.assertEqual(raised.exception.code, "adapter_input_invalid")


class Stage75ToStage77PropagationTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.root = tempfile.TemporaryDirectory()
        reports.REPORT_ROOT = Path(self.root.name)
        self.record = {"reference": "CR-1", "title": "Canonical record", "finding": "Original wording", "status": "recorded", "version": 1}
        self.record_context_patch = patch.object(reports.rda, "record_context", side_effect=lambda _conn, _reference: dict(self.record))
        self.record_context_patch.start()
        self.report = reports.create_report(
            self.conn,
            title="Internal report",
            purpose="Review selected record",
            audience="Administrators",
            distribution_class="internal_working",
            canonical_record_reference="CR-1",
            document_ids=[],
            association_ids=[],
            sections=[{"title": "Record", "blocks": [{"content_type": "verbatim_source", "text": "Original wording", "source_identity": {"object_kind": "canonical_record", "object_id": "CR-1"}, "inclusion_rationale": "Deliberately selected."}]}],
            exclusions=[],
            requested_formats=["docx", "html"],
            rendering_profile="internal",
            template_version="cde-internal-v1",
            actor="creator",
            actor_role="administrator",
            idempotency_key="create-1",
        )
        for status, actor, key in (("assembly_reviewed", "reviewer", "review-1"), ("privacy_reviewed", "privacy", "review-2"), ("redaction_reviewed", "redactor", "review-3"), ("approved_for_generation", "approver", "review-4")):
            self.report = reports.transition_report(self.conn, report_id=self.report["id"], resulting_status=status, rationale="Review", actor=actor, actor_role="administrator", declaration={"acknowledged": True}, idempotency_key=key)

    def tearDown(self):
        self.conn.close()
        self.root.cleanup()
        self.record_context_patch.stop()

    def test_stage75_attempt_preserves_inner_failure(self):
        failure = AdapterFailure("pdf_inspection", "pdf_invalid", "passed", {"format": "pdf", "failure_operation": "inspect_pdf"}, True, True, True)
        with patch("api.report_rendering.render_frozen_report", side_effect=failure):
            with self.assertRaises(reports.GovernedReportGenerationFailure) as raised:
                reports.generate_report(self.conn, report_id=self.report["id"], actor="generator", actor_role="administrator", idempotency_key="generation-1")
        self.assertEqual(raised.exception.diagnostic["failure_operation"], "pdf_validation")
        stored = json.loads(self.conn.execute("SELECT diagnostics_json FROM record_governed_report_generation_attempts").fetchone()[0])
        self.assertEqual(stored[0], raised.exception.diagnostic)
        self.assertEqual(reports.get_report(self.conn, self.report["id"])["artifacts"], [])
        self.assertFalse(list(Path(self.root.name).rglob("*.pdf")))

    def test_cleanup_failure_does_not_replace_primary_failure(self):
        failure = AdapterFailure("pdf_inspection", "pdf_invalid", "failed", {"format": "pdf", "failure_operation": "inspect_pdf"}, True, True, True)
        with patch("api.report_rendering.render_frozen_report", side_effect=failure), patch.object(reports, "_cleanup_generation_output", return_value="passed"):
            with self.assertRaises(reports.GovernedReportGenerationFailure) as raised:
                reports.generate_report(self.conn, report_id=self.report["id"], actor="generator", actor_role="administrator", idempotency_key="cleanup-failure")
        self.assertEqual(raised.exception.diagnostic["failure_code"], "pdf_invalid")
        self.assertEqual(raised.exception.diagnostic["cleanup_status"], "failed")

    def test_outer_cleanup_failure_is_bounded_without_changing_primary_code(self):
        failure = AdapterFailure("pdf_inspection", "pdf_invalid", "passed", {"format": "pdf", "failure_operation": "inspect_pdf"}, True, True, True)
        with patch("api.report_rendering.render_frozen_report", side_effect=failure), patch.object(reports, "_cleanup_generation_output", return_value="failed"):
            with self.assertRaises(reports.GovernedReportGenerationFailure) as raised:
                reports.generate_report(self.conn, report_id=self.report["id"], actor="generator", actor_role="administrator", idempotency_key="outer-cleanup-failure")
        self.assertEqual(raised.exception.diagnostic["failure_code"], "pdf_invalid")
        self.assertEqual(raised.exception.diagnostic["cleanup_status"], "failed")

    def test_terminal_event_carries_only_validated_diagnostic(self):
        jobs.ensure_job_tables(self.conn)
        job = jobs.enqueue_generation(self.conn, report_id=self.report["id"], actor="generator", governed_action="enqueue_generation", idempotency_key="job-1")
        claimed = jobs.claim_one(self.conn)
        value = diagnostics.make_diagnostic(phase="validation", operation="pdf_validation", checkpoint="validation", code="pdf_invalid", cleanup_status="passed", adapter_invocation_entered=True, adapter_process_started=True, adapter_result_received=True, format_category="pdf")
        self.assertTrue(jobs._terminal(self.conn, job["id"], claimed["lease_token"], "failed_terminal", jobs.WORKER_IDENTITY, phase="rendering", code="governed_report_renderer_failed", diagnostic=value))
        payload = json.loads(self.conn.execute("SELECT payload_json FROM stage77_report_job_events WHERE event_type='terminal'").fetchone()[0])
        self.assertEqual(payload["diagnostic"], value)
        self.assertEqual(payload["operation"], value["failure_operation"])
        self.assertEqual(payload["checkpoint"], value["failure_checkpoint"])
        self.assertEqual(payload["code"], value["failure_code"])
        self.assertNotIn("raw_error", payload)


if __name__ == "__main__":
    unittest.main()
