import os
import json
import re
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from api import governed_report_jobs as jobs
from api import governed_report_recovery as recovery
from api import governed_report_qualifications as qualifications
from api import record_governed_reports as reports


class DiagnosticRetryTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.root = tempfile.TemporaryDirectory()
        self.original_root = reports.REPORT_ROOT
        reports.REPORT_ROOT = Path(self.root.name)
        self.record = {"reference": "CR-1", "title": "Canonical record", "finding": "Original wording", "status": "recorded", "version": 1}
        self.record_context = patch.object(reports.rda, "record_context", return_value=self.record)
        self.record_context.start()
        self.mode = patch.dict(os.environ, {qualifications.REVIEW_MODE_ENV: qualifications.SOLE_MODE})
        self.mode.start()
        self.report = reports.create_report(
            self.connection,
            title="Internal report",
            purpose="Review selected record",
            audience="Administrators",
            distribution_class="internal_working",
            canonical_record_reference="CR-1",
            document_ids=[],
            association_ids=[],
            sections=[{"title": "Record", "blocks": [{"content_type": "verbatim_source", "text": "Original wording", "source_identity": {"object_kind": "canonical_record", "object_id": "CR-1"}, "inclusion_rationale": "Deliberately selected."}]}],
            exclusions=[],
            requested_formats=["docx", "html", "pdf"],
            rendering_profile="internal",
            template_version="cde-internal-v1",
            actor="nick",
            actor_role="administrator",
            idempotency_key="diagnostic-retry-report",
        )
        for status, key in (("assembly_reviewed", "diagnostic-assembly"), ("privacy_reviewed", "diagnostic-privacy"), ("redaction_reviewed", "diagnostic-redaction"), ("approved_for_generation", "diagnostic-approval")):
            self.report = reports.confirm_creator_gate(self.connection, report_id=self.report["id"], resulting_status=status, rationale="Sole administrator fixture confirmation", actor="nick", actor_role="administrator", acknowledged=True, idempotency_key=key)
        self.original_job = jobs.enqueue_generation(self.connection, report_id=self.report["id"], actor="nick", governed_action="enqueue_generation", idempotency_key="diagnostic-original")
        self.connection.execute("UPDATE record_governed_reports SET lifecycle_status='validation_failed' WHERE id=?", (self.report["id"],))
        self.connection.execute("UPDATE record_governed_report_versions SET lifecycle_status='validation_failed' WHERE report_id=?", (self.report["id"],))
        self.connection.execute("UPDATE stage77_report_jobs SET state='failed_terminal',attempt_count=1,terminal_at='2026-01-01T00:00:00Z',terminal_outcome='validation_failed',failure_phase='rendering',failure_code=? WHERE id=?", (jobs.DIAGNOSTIC_RETRY_FAILURE_CODE, self.original_job["id"]))
        diagnostic = jobs.make_diagnostic(phase="rendering", operation="renderer_invocation", checkpoint="entered", code=jobs.DIAGNOSTIC_RETRY_FAILURE_CODE, format_category="multiple")
        self.connection.execute(
            "INSERT INTO record_governed_report_generation_attempts (version_id,requested_formats_json,actor,actor_role,requested_at,result,diagnostics_json,request_payload_json,idempotency_key) VALUES(?,?,?,?,?,?,?,?,?)",
            (self.report["versions"][-1]["id"], '["docx", "html", "pdf"]', jobs.WORKER_IDENTITY, "system_worker", "2026-01-01T00:00:00Z", "validation_failed", json.dumps([diagnostic], separators=(",", ":")), "{}", f"stage77-job-{self.original_job['id']}"),
        )
        self.connection.execute(
            "INSERT INTO stage77_report_job_events(job_id,event_type,resulting_state,actor,occurred_at,payload_json) VALUES(?,?,?,?,?,?)",
            (self.original_job["id"], "terminal", "failed_terminal", jobs.WORKER_IDENTITY, "2026-01-01T00:00:01Z", json.dumps({"phase": "rendering", "operation": "renderer_invocation", "checkpoint": "entered", "code": jobs.DIAGNOSTIC_RETRY_FAILURE_CODE, "diagnostic": diagnostic, **diagnostic}, separators=(",", ":"))),
        )
        self.connection.commit()

    def tearDown(self):
        self.connection.close()
        self.mode.stop()
        self.record_context.stop()
        reports.REPORT_ROOT = self.original_root
        self.root.cleanup()

    def authorize(self, rationale="Bounded diagnostic observability correction deployed"):
        return jobs.authorize_diagnostic_retry(self.connection, predecessor_job_id=self.original_job["id"], actor="nick", actor_role="admin", rationale=rationale, acknowledged=True)

    def _set_recovery_state(self, state, *, worker_drained=0, manifest_digest=None, maintenance_epoch=1):
        recovery.ensure_recovery_tables(self.connection)
        self.connection.execute("DELETE FROM stage77_recovery_control")
        self.connection.execute(
            "INSERT INTO stage77_recovery_control(singleton,operation_id,recovery_point_id,operation_type,requested_actor,governed_action,state,maintenance_epoch,requested_at,schema_version,worker_drained,manifest_digest) VALUES(1,?,?,?,?,?,?,?,?,?,?,?)",
            ("operation-1", "point-1", "capture", "admin", "capture", state, maintenance_epoch, "2026-01-01T00:00:00Z", recovery.RECOVERY_SCHEMA_VERSION, worker_drained, manifest_digest),
        )
        self.connection.commit()

    def test_one_linked_retry_is_atomic_and_preserves_original(self):
        successor = self.authorize()
        self.assertEqual(successor["retry_of_job_id"], self.original_job["id"])
        self.assertEqual(successor["governed_action"], jobs.DIAGNOSTIC_RETRY_ACTION)
        self.assertEqual(jobs.get_job(self.connection, self.original_job["id"])["state"], "failed_terminal")
        self.assertEqual(reports.get_report(self.connection, self.report["id"])["lifecycle_status"], "generation_requested")
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM record_governed_report_events WHERE event_type='diagnostic_retry_authorized'").fetchone()[0], 1)
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM stage77_report_job_events WHERE event_type=?", (jobs.DIAGNOSTIC_RETRY_EVENT,)).fetchone()[0], 1)

    def test_identical_replay_is_idempotent_and_conflicting_replay_fails(self):
        first = self.authorize()
        replay = self.authorize()
        self.assertEqual(replay["id"], first["id"])
        with self.assertRaisesRegex(ValueError, "idempotency_conflict"):
            self.authorize("A materially different rationale")
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM stage77_report_jobs WHERE retry_of_job_id=?", (self.original_job["id"],)).fetchone()[0], 1)

    def test_ineligible_terminal_failure_is_rejected_without_mutation(self):
        self.connection.execute("UPDATE stage77_report_jobs SET failure_code='pdf_invalid' WHERE id=?", (self.original_job["id"],))
        self.connection.commit()
        with self.assertRaisesRegex(ValueError, "predecessor_invalid"):
            self.authorize()
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM stage77_report_jobs WHERE retry_of_job_id IS NOT NULL").fetchone()[0], 0)
        self.assertEqual(reports.get_report(self.connection, self.report["id"])["lifecycle_status"], "validation_failed")

    def test_concurrent_successor_insertion_is_rejected_by_fixed_identity(self):
        self.connection.execute("INSERT INTO stage77_report_jobs(report_id,report_version_id,specification_digest,requested_formats_json,rendering_profile,template_version,publication_engine_version,requesting_actor,governed_action,requested_at,state,attempt_count,max_attempts,next_eligible_at,idempotency_key,retry_of_job_id,maintenance_epoch,schema_version) SELECT report_id,report_version_id,specification_digest,requested_formats_json,rendering_profile,template_version,publication_engine_version,'nick',?,requested_at,'queued',0,3,next_eligible_at,?,id,0,schema_version FROM stage77_report_jobs WHERE id=?", (jobs.DIAGNOSTIC_RETRY_ACTION, "stage77-other-key-%s" % self.original_job["id"], self.original_job["id"]))
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute("INSERT INTO stage77_report_jobs(report_id,report_version_id,specification_digest,requested_formats_json,rendering_profile,template_version,publication_engine_version,requesting_actor,governed_action,requested_at,state,attempt_count,max_attempts,next_eligible_at,idempotency_key,retry_of_job_id,maintenance_epoch,schema_version) SELECT report_id,report_version_id,specification_digest,requested_formats_json,rendering_profile,template_version,publication_engine_version,'nick',?,requested_at,'queued',0,3,next_eligible_at,?,id,0,schema_version FROM stage77_report_jobs WHERE id=?", (jobs.DIAGNOSTIC_RETRY_ACTION, "stage77-other-key-2-%s" % self.original_job["id"], self.original_job["id"]))
        self.connection.commit()
        with self.assertRaisesRegex(ValueError, "successor_exists|event_missing|contract_invalid"):
            self.authorize()
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM stage77_report_jobs WHERE retry_of_job_id=?", (self.original_job["id"],)).fetchone()[0], 1)

    def test_incomplete_predecessor_diagnostic_is_rejected(self):
        self.connection.execute("UPDATE record_governed_report_generation_attempts SET diagnostics_json='[]' WHERE idempotency_key=?", (f"stage77-job-{self.original_job['id']}",))
        self.connection.commit()
        with self.assertRaisesRegex(ValueError, "diagnostic_invalid"):
            self.authorize()
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM stage77_report_jobs WHERE retry_of_job_id IS NOT NULL").fetchone()[0], 0)

    def test_completed_recovery_epoch_permits_authorization_without_recovery_mutation(self):
        self._set_recovery_state("completed", worker_drained=1, manifest_digest="m" * 64, maintenance_epoch=1)
        before = dict(recovery.recovery_status(self.connection))
        self.assertTrue(recovery.recovery_allows_claim(self.connection))
        successor = self.authorize()
        after = dict(recovery.recovery_status(self.connection))
        self.assertEqual(successor["retry_of_job_id"], self.original_job["id"])
        self.assertEqual(after, before)

    def test_worker_revalidation_uses_the_same_completed_recovery_decision(self):
        self._set_recovery_state("completed", worker_drained=1, manifest_digest="m" * 64, maintenance_epoch=1)
        successor = self.authorize()
        report = reports.get_report(self.connection, self.report["id"])
        jobs._revalidate_diagnostic_retry_job(self.connection, jobs.get_job(self.connection, successor["id"]), report)

    def test_retry_recovery_eligibility_matches_authoritative_claim_matrix(self):
        permitted = [
            (None, 0, None),
            ("completed", 1, "m" * 64),
            ("failed", 1, None),
            ("restore_ready", 1, "m" * 64),
            ("restore_failed", 1, None),
        ]
        for state, drained, manifest in permitted:
            with self.subTest(state=state):
                if state is None:
                    self.connection.execute("DROP TABLE IF EXISTS stage77_recovery_control")
                    self.connection.commit()
                else:
                    self._set_recovery_state(state, worker_drained=drained, manifest_digest=manifest)
                self.assertTrue(recovery.recovery_allows_claim(self.connection))
                self.assertIsNotNone(jobs.diagnostic_retry_candidate(self.connection, self.report["id"], "nick"))
                self.connection.execute("DELETE FROM stage77_report_jobs WHERE retry_of_job_id IS NOT NULL")
                self.connection.execute("UPDATE record_governed_reports SET lifecycle_status='validation_failed' WHERE id=?", (self.report["id"],))
                self.connection.execute("UPDATE record_governed_report_versions SET lifecycle_status='validation_failed' WHERE report_id=?", (self.report["id"],))
                self.connection.commit()

        blocked = [
            ("requested", 0, None),
            ("draining", 0, None),
            ("quiesced", 1, None),
            ("capturing", 1, None),
            ("validating", 1, None),
            ("restore_validating", 1, None),
            ("failed", 0, None),
            ("restore_failed", 0, None),
            ("restore_ready", 1, None),
        ]
        for state, drained, manifest in blocked:
            with self.subTest(state=state):
                self._set_recovery_state(state, worker_drained=drained, manifest_digest=manifest)
                self.assertFalse(recovery.recovery_allows_claim(self.connection))
                self.assertIsNone(jobs.diagnostic_retry_candidate(self.connection, self.report["id"], "nick"))

    def test_unknown_or_stale_recovery_evidence_fails_closed_for_retry(self):
        with patch.object(recovery, "recovery_status", return_value={"state": "unknown", "maintenance_epoch": 0}):
            self.assertFalse(recovery.recovery_allows_claim(self.connection))
            self.assertIsNone(jobs.diagnostic_retry_candidate(self.connection, self.report["id"], "nick"))
        for epoch in (None, True, False, 1.5, "1", 0, -1, 10**100):
            with self.subTest(epoch=repr(epoch)), patch.object(recovery, "recovery_status", return_value={"state": "completed", "maintenance_epoch": epoch}):
                self.assertFalse(recovery.recovery_allows_claim(self.connection))
                self.assertIsNone(jobs.diagnostic_retry_candidate(self.connection, self.report["id"], "nick"))
        self._set_recovery_state("completed", worker_drained=1, manifest_digest="m" * 64, maintenance_epoch=1)
        self.connection.execute("UPDATE stage77_report_jobs SET maintenance_epoch=2 WHERE id=?", (self.original_job["id"],))
        self.connection.commit()
        self.assertFalse(recovery.recovery_allows_claim(self.connection))
        self.assertIsNone(jobs.diagnostic_retry_candidate(self.connection, self.report["id"], "nick"))

    def test_exact_legacy_pair_is_selected_and_bound_to_successor(self):
        attempt_raw = json.dumps(list(__import__("api.governed_report_diagnostics", fromlist=["LEGACY_ATTEMPT_DIAGNOSTICS"]).LEGACY_ATTEMPT_DIAGNOSTICS), separators=(",", ":"))
        terminal_raw = json.dumps(__import__("api.governed_report_diagnostics", fromlist=["LEGACY_TERMINAL_PAYLOAD"]).LEGACY_TERMINAL_PAYLOAD, separators=(",", ":"), sort_keys=True)
        self.connection.execute("UPDATE record_governed_report_generation_attempts SET diagnostics_json=? WHERE idempotency_key=?", (attempt_raw, f"stage77-job-{self.original_job['id']}"))
        self.connection.execute("UPDATE stage77_report_job_events SET payload_json=? WHERE job_id=? AND event_type='terminal'", (terminal_raw, self.original_job["id"]))
        self.connection.commit()
        successor = self.authorize()
        self.assertEqual(successor["retry_of_job_id"], self.original_job["id"])
        event = self.connection.execute("SELECT payload_json FROM stage77_report_job_events WHERE job_id=? AND event_type=?", (successor["id"], jobs.DIAGNOSTIC_RETRY_EVENT)).fetchone()
        payload = json.loads(event[0])
        self.assertEqual(payload["diagnostic_contract_id"], "legacy_pre_propagation_diagnostic_contract_v1")
        self.assertEqual(payload["predecessor_attempt_diagnostic_sha256"], "f5fa57e6989a8406c99bd3c26b877694515f44af74426684fbcc18a0268abd63")
        self.assertEqual(payload["predecessor_terminal_diagnostic_sha256"], "f7456646b23f037b18af45f5019d5c817b54649cf28da14eecdf838817495239")

    def test_legacy_selector_rejects_mixed_or_unknown_shapes(self):
        from api.governed_report_diagnostics import select_diagnostic_contract
        legacy_attempt = json.dumps(["governed_report_generation_validation_failed", "AdapterFailure"], separators=(",", ":"))
        legacy_terminal = json.dumps({"phase": "rendering", "code": jobs.DIAGNOSTIC_RETRY_FAILURE_CODE}, separators=(",", ":"), sort_keys=True)
        with self.assertRaisesRegex(ValueError, "bounded_diagnostic_contract_invalid"):
            select_diagnostic_contract(attempt_raw=legacy_attempt, terminal_raw=json.dumps({"phase": "rendering", "operation": "renderer_invocation", "checkpoint": "entered", "code": jobs.DIAGNOSTIC_RETRY_FAILURE_CODE, "diagnostic": {}}, separators=(",", ":")))
        with self.assertRaisesRegex(ValueError, "bounded_diagnostic_contract_invalid"):
            select_diagnostic_contract(attempt_raw=legacy_attempt.replace("AdapterFailure", "UnknownFailure"), terminal_raw=legacy_terminal)

    def test_legacy_payload_digests_are_exact_sha256_and_bound(self):
        import hashlib
        from api import governed_report_diagnostics as diagnostics
        attempt_raw = json.dumps(list(diagnostics.LEGACY_ATTEMPT_DIAGNOSTICS), separators=(",", ":"))
        terminal_raw = json.dumps(diagnostics.LEGACY_TERMINAL_PAYLOAD, separators=(",", ":"), sort_keys=True)
        self.assertRegex(diagnostics.LEGACY_ATTEMPT_SHA256, r"^[0-9a-f]{64}$")
        self.assertRegex(diagnostics.LEGACY_TERMINAL_SHA256, r"^[0-9a-f]{64}$")
        self.assertEqual(hashlib.sha256(attempt_raw.encode()).hexdigest(), diagnostics.LEGACY_ATTEMPT_SHA256)
        self.assertEqual(hashlib.sha256(terminal_raw.encode()).hexdigest(), diagnostics.LEGACY_TERMINAL_SHA256)

    def test_rendered_form_is_private_and_has_fixed_declaration(self):
        import importlib
        with patch.dict(os.environ, {"RECORDS_DB_PATH": str(Path(self.root.name) / "route.db")}):
            admin_session = importlib.import_module("api.routes.admin_session")
        detail = reports.get_report(self.connection, self.report["id"])
        diagnostic_retry = jobs.diagnostic_retry_candidate(self.connection, self.report["id"], "nick")
        html = admin_session._stage75_html(session={"username": "nick", "role": "admin"}, reports=[detail], candidates={}, detail=detail, diagnostic_retry=diagnostic_retry)
        self.assertIn("Authorize one diagnostic retry", html)
        self.assertIn("predates the current diagnostic propagation contract", html)
        self.assertIn("exact historical bounded pair has been validated", html)
        self.assertIn("root renderer cause remains unidentified", html)
        self.assertIn(jobs.DIAGNOSTIC_RETRY_DECLARATION, html)
        self.assertIn('name="acknowledged" value="1" required', html)
        self.assertIn(f'action="/api/admin/session/governed-report-jobs/{self.original_job["id"]}/diagnostic-retry"', html)
        self.assertNotIn("/diagnostic-retry" , admin_session._stage75_html(session={"username": "nick", "role": "admin"}, reports=[detail], candidates={}, detail=detail))
        source = Path(admin_session.__file__).read_text(encoding="utf-8")
        route_decorators = re.findall(
            r'@router\.(get|post|put|patch|delete)\("([^"]*diagnostic-retry[^"]*)"',
            source,
        )
        self.assertEqual(
            route_decorators,
            [("post", "/api/admin/session/governed-report-jobs/{job_id}/diagnostic-retry")],
        )
        self.assertNotIn(
            '"/admin/governed-report-jobs/{job_id}/diagnostic-retry"',
            source,
        )


if __name__ == "__main__":
    unittest.main()
