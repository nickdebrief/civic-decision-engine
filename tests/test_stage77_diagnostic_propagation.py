import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from api import governed_report_diagnostics as diagnostics
from api import governed_report_qualifications as qualifications
from api import governed_report_jobs as jobs
from api import record_governed_reports as reports
from api.report_rendering import AdapterFailure


class QualificationProjectionTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.TemporaryDirectory()
        self.db_path = Path(self.root.name) / "records.db"
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.old_root = reports.REPORT_ROOT
        reports.REPORT_ROOT = Path(self.root.name)
        self.record = {"reference": "CR-PROJECTION", "title": "Synthetic record", "finding": "Bounded wording", "status": "recorded", "version": 1}
        self.record_patch = patch.object(reports.rda, "record_context", return_value=self.record)
        self.record_patch.start()
        with patch.dict(os.environ, {qualifications.REVIEW_MODE_ENV: qualifications.SOLE_MODE}):
            self.report = reports.create_report(
                self.conn,
                title="Synthetic internal report",
                purpose="Projection boundary test",
                audience="Administrators",
                distribution_class="internal_working",
                canonical_record_reference="CR-PROJECTION",
                document_ids=[], association_ids=[],
                sections=[{"title": "Record", "blocks": [{"content_type": "verbatim_source", "text": "Bounded wording", "source_identity": {"object_kind": "canonical_record", "object_id": "CR-PROJECTION"}, "inclusion_rationale": "Controlled fixture."}]}],
                exclusions=[], requested_formats=["docx", "html", "pdf"],
                rendering_profile="internal", template_version="cde-internal-v1",
                actor="nick", actor_role="administrator", idempotency_key="projection-report",
            )
            for status, key in (("assembly_reviewed", "projection-assembly"), ("privacy_reviewed", "projection-privacy"), ("redaction_reviewed", "projection-redaction"), ("approved_for_generation", "projection-approval")):
                self.report = reports.confirm_creator_gate(
                    self.conn, report_id=self.report["id"], resulting_status=status,
                    rationale="Controlled qualification fixture.", actor="nick",
                    actor_role="administrator", acknowledged=True, idempotency_key=key,
                )

    def tearDown(self):
        reports.REPORT_ROOT = self.old_root
        self.record_patch.stop()
        self.conn.close()
        self.root.cleanup()

    def _projection(self):
        version = self.report["versions"][0]
        final = qualifications.latest_final(self.conn, self.report["id"])
        return qualifications.rendering_projection(
            self.conn, report_id=self.report["id"], report_version_id=version["id"],
            specification_digest=version["specification_digest"],
            qualification_id=final["id"], qualification_digest=final["digest"],
        )

    def test_projection_is_exact_deterministic_and_adapter_accepted(self):
        from scripts.evidence_led_governance_pipeline import report_adapter
        final = qualifications.latest_final(self.conn, self.report["id"])
        full = dict(final["payload"])
        full.update({"qualification_id": final["id"], "qualification_digest": final["digest"], "disclosure": qualifications.DISCLOSURE})
        specification = self.report["versions"][0]["specification"]
        with self.assertRaises(report_adapter.AdapterFailure):
            report_adapter.make_book(specification, full)
        projected = self._projection()
        self.assertEqual(set(projected), qualifications.RENDERING_QUALIFICATION_FIELDS)
        self.assertEqual(projected, self._projection())
        before = dict(final["payload"])
        report_adapter.make_book(specification, projected)
        self.assertEqual(final["payload"], before)
        with self.assertRaises(report_adapter.AdapterFailure):
            report_adapter.make_book(specification, {**projected, "extra": "rejected"})
        with self.assertRaises(report_adapter.AdapterFailure):
            report_adapter.make_book(specification, {key: value for key, value in projected.items() if key != "disclosure"})

    def test_worker_projects_before_real_adapter_boundary(self):
        from scripts.evidence_led_governance_pipeline import report_adapter
        with patch.dict(os.environ, {qualifications.REVIEW_MODE_ENV: qualifications.SOLE_MODE}):
            jobs.ensure_job_tables(self.conn)
            item = jobs.enqueue_generation(
                self.conn, report_id=self.report["id"], actor="nick",
                governed_action="enqueue_generation", idempotency_key="projection-worker",
            )
            claimed = jobs.claim_one(self.conn)
            self.assertEqual(claimed["id"], item["id"])
            seen = {}

            def controlled_generation(_conn, *, governance_qualification=None, **_kwargs):
                seen.update(governance_qualification or {})
                report_adapter.make_book(self.report["versions"][0]["specification"], governance_qualification)
                return self.report

            with patch.object(jobs.reports, "generate_report", side_effect=controlled_generation), patch.object(jobs, "_artifact_rows_valid", return_value=True):
                jobs.execute_job(str(self.db_path), claimed)
        self.assertEqual(set(seen), qualifications.RENDERING_QUALIFICATION_FIELDS)
        self.assertEqual(jobs.get_job(self.conn, item["id"])["state"], "succeeded")

    def test_projection_rejects_stale_identity_specification_and_envelope(self):
        final = qualifications.latest_final(self.conn, self.report["id"])
        version = self.report["versions"][0]
        args = {"report_id": self.report["id"], "report_version_id": version["id"], "specification_digest": version["specification_digest"], "qualification_id": final["id"], "qualification_digest": final["digest"]}
        with self.assertRaisesRegex(ValueError, "qualification_specification_invalid"):
            qualifications.rendering_projection(self.conn, **{**args, "specification_digest": "0" * 64})
        with self.assertRaisesRegex(ValueError, "qualification_identity_invalid"):
            qualifications.rendering_projection(self.conn, **{**args, "qualification_digest": "0" * 64})
        payload = dict(final["payload"])
        payload.pop("rationale")
        self.conn.execute("UPDATE record_governed_report_qualifications SET qualification_payload_json=? WHERE id=?", (reports.canonical_json(payload), final["id"]))
        with self.assertRaises(ValueError):
            qualifications.rendering_projection(self.conn, **args)
        payload["rationale"] = "Controlled qualification fixture."
        payload["unexpected"] = True
        self.conn.execute("UPDATE record_governed_report_qualifications SET qualification_payload_json=? WHERE id=?", (reports.canonical_json(payload), final["id"]))
        with self.assertRaises(ValueError):
            qualifications.rendering_projection(self.conn, **args)

    def test_projection_rejects_non_internal_distribution_and_wrong_ownership(self):
        final = qualifications.latest_final(self.conn, self.report["id"])
        version = self.report["versions"][0]
        args = {"report_id": self.report["id"], "report_version_id": version["id"], "specification_digest": version["specification_digest"], "qualification_id": final["id"], "qualification_digest": final["digest"]}
        self.conn.execute("UPDATE record_governed_reports SET distribution_class='public' WHERE id=?", (self.report["id"],))
        with self.assertRaisesRegex(ValueError, "qualification_distribution_invalid"):
            qualifications.rendering_projection(self.conn, **args)
        self.conn.execute("UPDATE record_governed_reports SET distribution_class='internal_working' WHERE id=?", (self.report["id"],))
        with self.assertRaisesRegex(ValueError, "ownership_invalid"):
            qualifications.rendering_projection(self.conn, **{**args, "report_version_id": version["id"] + 100})


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
        # A structured failure record receives persisted_at only in the
        # committed terminal-event projection; the caller's input stays
        # unchanged. Legacy diagnostic contracts retain their exact form.
        if "failure_record" in value:
            self.assertIsNone(value["failure_record"]["persisted_at"])
            persisted_at = payload["diagnostic"]["failure_record"]["persisted_at"]
            self.assertIsInstance(persisted_at, str)
            self.assertTrue(persisted_at)
            self.assertEqual(payload["diagnostic"], diagnostics.with_persisted_at(value, persisted_at=persisted_at))
        else:
            self.assertEqual(payload["diagnostic"], value)
        self.assertEqual(payload["operation"], value["failure_operation"])
        self.assertEqual(payload["checkpoint"], value["failure_checkpoint"])
        self.assertEqual(payload["code"], value["failure_code"])
        self.assertNotIn("raw_error", payload)


class E2V2DiagnosticContractTests(Stage75ToStage77PropagationTests):
    def _v2(self, *, state="known", target_class="governed_report", status="passed", relationship="completed_after_primary"):
        return diagnostics.make_diagnostic(phase="rendering", operation="renderer_invocation", checkpoint="entered", code="governed_report_renderer_failed", cleanup_status=status, failure_context={"schema_version": diagnostics.STRUCTURED_FAILURE_SCHEMA_VERSION_V2, "affected_target_state": state, "affected_target_class": target_class, "cleanup_relationship": relationship})

    def test_v2_selection_is_explicit_and_unsupported_version_is_rejected(self):
        value = self._v2()
        terminal = {"phase": value["failure_phase"], "operation": value["failure_operation"], "checkpoint": value["failure_checkpoint"], "code": value["failure_code"], "diagnostic": value, **value}
        self.assertEqual(diagnostics.select_diagnostic_contract(attempt_raw=reports.canonical_json([value]), terminal_raw=reports.canonical_json(terminal))["contract_id"], diagnostics.STRUCTURED_FAILURE_DIAGNOSTIC_CONTRACT)
        future = {**value["failure_record"], "schema_version": "structured_failure_attribution.v3"}
        rejected = {**value, "failure_record": future}
        with self.assertRaisesRegex(ValueError, "bounded_failure_record_invalid"):
            diagnostics.select_diagnostic_contract(attempt_raw=reports.canonical_json([rejected]), terminal_raw=reports.canonical_json({"phase": rejected["failure_phase"], "operation": rejected["failure_operation"], "checkpoint": rejected["failure_checkpoint"], "code": rejected["failure_code"], "diagnostic": rejected, **rejected}))

    def test_v2_terminal_event_persists_and_fresh_readback_preserves_primary(self):
        jobs.ensure_job_tables(self.conn)
        job = jobs.enqueue_generation(self.conn, report_id=self.report["id"], actor="generator", governed_action="enqueue_generation", idempotency_key="e2-v2-terminal")
        claimed = jobs.claim_one(self.conn)
        value = self._v2(status="failed", relationship="failed_after_primary")
        self.assertTrue(jobs._terminal(self.conn, job["id"], claimed["lease_token"], "failed_terminal", jobs.WORKER_IDENTITY, phase="rendering", code="governed_report_renderer_failed", diagnostic=value, commit=True))
        payload = json.loads(self.conn.execute("SELECT payload_json FROM stage77_report_job_events WHERE job_id=? AND event_type='terminal'", (job["id"],)).fetchone()[0])
        self.assertEqual(payload["code"], "governed_report_renderer_failed")
        self.assertEqual(payload["diagnostic"]["failure_record"]["cleanup_relationship"], "failed_after_primary")
        self.assertIsNotNone(payload["diagnostic"]["failure_record"]["persisted_at"])

    def _authorised_job(self, key):
        jobs.ensure_job_tables(self.conn); jobs.ensure_post_correction_tables(self.conn)
        job = jobs.enqueue_generation(self.conn, report_id=self.report["id"], actor="generator", governed_action="enqueue_generation", idempotency_key=key)
        claimed = jobs.claim_one(self.conn)
        version = self.report["versions"][0]
        auth = f"auth-{job['id']}"
        self.conn.execute("INSERT INTO stage77_post_correction_authorizations(id,report_id,report_version_id,qualification_id,job1_id,job2_id,state,idempotency_key,payload_json,authorization_digest,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)", (auth, self.report["id"], version["id"], 1, job["id"], job["id"], "authorized", f"key-{job['id']}", "{}", "0" * 64, "2026-01-01T00:00:00Z"))
        self.conn.execute("UPDATE stage77_report_jobs SET post_correction_authorization_id=? WHERE id=?", (auth, job["id"])); self.conn.commit()
        return job, claimed, auth

    def test_terminal_consumes_exactly_one_authorization_with_outer_commit(self):
        job, claimed, auth = self._authorised_job("outer-commit")
        self.conn.execute("BEGIN")
        self.assertTrue(jobs._terminal(self.conn, job["id"], claimed["lease_token"], "failed_terminal", jobs.WORKER_IDENTITY, phase="validation", code="artifact_integrity_failed", commit=False))
        self.conn.commit()
        self.assertEqual(self.conn.execute("SELECT state FROM stage77_post_correction_authorizations WHERE id=?", (auth,)).fetchone()[0], "consumed")

    def test_terminal_stages_success_for_outer_rollback(self):
        job, claimed, auth = self._authorised_job("outer-rollback")
        self.conn.execute("BEGIN")
        self.assertTrue(jobs._terminal(self.conn, job["id"], claimed["lease_token"], "failed_terminal", jobs.WORKER_IDENTITY, phase="validation", code="artifact_integrity_failed", commit=False))
        self.conn.rollback()
        self.assertEqual(self.conn.execute("SELECT state FROM stage77_report_jobs WHERE id=?", (job["id"],)).fetchone()[0], "leased")
        self.assertEqual(self.conn.execute("SELECT state FROM stage77_post_correction_authorizations WHERE id=?", (auth,)).fetchone()[0], "authorized")

    def test_terminal_explicit_helper_commit_persists_complete_transition(self):
        jobs.ensure_job_tables(self.conn)
        job = jobs.enqueue_generation(self.conn, report_id=self.report["id"], actor="generator", governed_action="enqueue_generation", idempotency_key="helper-commit")
        claimed = jobs.claim_one(self.conn)
        self.assertTrue(jobs._terminal(self.conn, job["id"], claimed["lease_token"], "failed_terminal", jobs.WORKER_IDENTITY, phase="validation", code="artifact_integrity_failed", commit=True))
        self.assertFalse(self.conn.in_transaction)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM stage77_report_job_events WHERE job_id=? AND event_type='terminal'", (job["id"],)).fetchone()[0], 1)

    def test_terminal_release_failure_rolls_back_group_and_preserves_outer_ownership(self):
        job, claimed, auth = self._authorised_job("release-failure")
        class Failing:
            def __init__(self, conn): self.conn, self.failed = conn, False
            def execute(self, sql, values=()):
                if sql == "RELEASE SAVEPOINT stage77_terminal_event" and not self.failed: self.failed = True; raise sqlite3.OperationalError("forced release failure")
                return self.conn.execute(sql, values)
            @property
            def in_transaction(self): return self.conn.in_transaction
            def commit(self): return self.conn.commit()
        self.conn.execute("BEGIN")
        with self.assertRaisesRegex(sqlite3.OperationalError, "forced release failure"):
            jobs._terminal(Failing(self.conn), job["id"], claimed["lease_token"], "failed_terminal", jobs.WORKER_IDENTITY, phase="validation", code="artifact_integrity_failed", commit=False)
        self.assertTrue(self.conn.in_transaction); self.conn.commit()
        self.assertEqual(self.conn.execute("SELECT state FROM stage77_report_jobs WHERE id=?", (job["id"],)).fetchone()[0], "leased")
        self.assertEqual(self.conn.execute("SELECT state FROM stage77_post_correction_authorizations WHERE id=?", (auth,)).fetchone()[0], "authorized")

if __name__ == "__main__":
    unittest.main()
