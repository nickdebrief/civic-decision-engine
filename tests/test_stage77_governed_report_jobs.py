import sqlite3
import tempfile
import threading
import time
import unittest
import os
import base64
import hashlib
from pathlib import Path
from unittest.mock import patch

from api import governed_report_jobs as jobs
from api import governed_report_recovery as recovery
from api import governed_report_diagnostics as diagnostics
from api import record_governed_reports as reports


class Stage77JobTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.conn = sqlite3.connect(Path(self.temp.name) / "records.db", isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.report = {
            "id": 7,
            "lifecycle_status": "approved_for_generation",
            "versions": [{
                "id": 11,
                "version_number": 1,
                "specification_digest": "a" * 64,
                "specification": {
                    "requested_formats": ["docx", "html"],
                    "rendering_profile": "internal",
                    "template_version": "cde-internal-v1",
                    "publication_engine_version": "2.0.0",
                },
            }],
        }
        self.digest_patch = patch.object(jobs.reports, "specification_digest", return_value="a" * 64)
        self.report_patch = patch.object(jobs.reports, "get_report", return_value=self.report)
        self.digest_patch.start(); self.report_patch.start()

    def tearDown(self):
        self.report_patch.stop(); self.digest_patch.stop(); self.conn.close(); self.temp.cleanup()

    def test_enqueue_is_idempotent_and_atomic(self):
        first = jobs.enqueue_generation(self.conn, report_id=7, actor="admin-a", governed_action="enqueue_generation", idempotency_key="same")
        second = jobs.enqueue_generation(self.conn, report_id=7, actor="admin-a", governed_action="enqueue_generation", idempotency_key="same")
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM stage77_report_jobs").fetchone()[0], 1)
        with self.assertRaisesRegex(ValueError, "idempotency_conflict"):
            jobs.enqueue_generation(self.conn, report_id=7, actor="admin-b", governed_action="enqueue_generation", idempotency_key="same")

    def test_enqueue_rolls_back_job_event_and_lifecycle_together(self):
        jobs.reports.ensure_report_tables(self.conn)
        jobs.ensure_job_tables(self.conn)
        self.conn.execute("CREATE TRIGGER fail_stage77_event BEFORE INSERT ON stage77_report_job_events BEGIN SELECT RAISE(ABORT, 'controlled'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            jobs.enqueue_generation(self.conn, report_id=7, actor="admin-a", governed_action="enqueue_generation", idempotency_key="rollback")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM stage77_report_jobs").fetchone()[0], 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM stage77_report_job_events").fetchone()[0], 0)
        self.assertEqual(self.report["lifecycle_status"], "approved_for_generation")

    def test_claim_heartbeat_and_stale_token_are_fenced(self):
        item = jobs.enqueue_generation(self.conn, report_id=7, actor="admin-a", governed_action="enqueue_generation", idempotency_key="claim")
        claimed = jobs.claim_one(self.conn, "worker-a")
        self.assertEqual(claimed["id"], item["id"])
        self.assertTrue(jobs.heartbeat(self.conn, item["id"], claimed["lease_token"]))
        self.assertFalse(jobs.heartbeat(self.conn, item["id"], "stale-token"))
        self.assertIsNone(jobs.claim_one(self.conn, "worker-b"))

    def test_cancel_queued_job_never_claims(self):
        item = jobs.enqueue_generation(self.conn, report_id=7, actor="admin-a", governed_action="enqueue_generation", idempotency_key="cancel")
        cancelled = jobs.request_cancel(self.conn, item["id"], "admin-a")
        self.assertEqual(cancelled["state"], "cancelled")
        self.assertIsNone(jobs.claim_one(self.conn))

    def test_worker_success_is_terminal_and_replay_does_not_render_twice(self):
        item = jobs.enqueue_generation(self.conn, report_id=7, actor="admin-a", governed_action="enqueue_generation", idempotency_key="success")
        claimed = jobs.claim_one(self.conn)
        with patch.object(jobs.reports, "generate_report", side_effect=lambda *_args, **_kwargs: self.report) as render, patch.object(jobs, "_artifact_rows_valid", return_value=True):
            jobs.execute_job(str(Path(self.temp.name) / "records.db"), claimed)
            jobs.execute_job(str(Path(self.temp.name) / "records.db"), claimed)
        self.assertEqual(render.call_count, 1)
        self.assertEqual(render.call_args.kwargs["governed_job_id"], item["id"])
        self.assertEqual(jobs.get_job(self.conn, item["id"])["state"], "succeeded")

    def test_worker_preserves_stage75_bounded_failure_diagnostic(self):
        item = jobs.enqueue_generation(self.conn, report_id=7, actor="admin-a", governed_action="enqueue_generation", idempotency_key="diagnostic")
        claimed = jobs.claim_one(self.conn)
        value = diagnostics.make_diagnostic(
            phase="validation", operation="pdf_validation", checkpoint="validation",
            code="pdf_invalid", cleanup_status="passed",
            adapter_invocation_entered=True, adapter_process_started=True,
            adapter_result_received=True, format_category="pdf",
        )
        failure = reports.GovernedReportGenerationFailure(value)
        with patch.object(jobs.reports, "generate_report", side_effect=failure):
            jobs.execute_job(str(Path(self.temp.name) / "records.db"), claimed)
        event = self.conn.execute("SELECT payload_json FROM stage77_report_job_events WHERE job_id=? AND event_type='terminal'", (item["id"],)).fetchone()
        self.assertIsNotNone(event)
        payload = __import__("json").loads(event[0])
        self.assertEqual(payload["diagnostic"], value)
        self.assertEqual(jobs.get_job(self.conn, item["id"])["state"], "failed_terminal")

    def test_worker_rejects_malformed_inner_diagnostic_closed(self):
        item = jobs.enqueue_generation(self.conn, report_id=7, actor="admin-a", governed_action="enqueue_generation", idempotency_key="malformed-diagnostic")
        claimed = jobs.claim_one(self.conn)

        class MalformedFailure(ValueError):
            def diagnostic_payload(self):
                return {"failure_code": "pdf_invalid"}

        with patch.object(jobs.reports, "generate_report", side_effect=MalformedFailure("private detail")):
            jobs.execute_job(str(Path(self.temp.name) / "records.db"), claimed)
        payload = __import__("json").loads(self.conn.execute("SELECT payload_json FROM stage77_report_job_events WHERE job_id=? AND event_type='terminal'", (item["id"],)).fetchone()[0])
        self.assertEqual(payload["diagnostic"]["failure_code"], "adapter_return_contract_invalid")
        self.assertNotIn("private detail", __import__("json").dumps(payload))

    def test_terminal_idempotent_replay_returns_job_after_report_lifecycle_changes(self):
        item = jobs.enqueue_generation(self.conn, report_id=7, actor="admin-a", governed_action="enqueue_generation", idempotency_key="terminal-replay")
        self.conn.execute("UPDATE stage77_report_jobs SET state='succeeded',terminal_outcome='succeeded' WHERE id=?", (item["id"],))
        replay = jobs.enqueue_generation(self.conn, report_id=7, actor="admin-a", governed_action="enqueue_generation", idempotency_key="terminal-replay")
        self.assertEqual(replay["id"], item["id"])

    def test_listing_is_read_only_when_queue_tables_are_absent(self):
        self.assertEqual(jobs.list_jobs(self.conn), [])
        self.assertIsNone(self.conn.execute("SELECT 1 FROM sqlite_master WHERE name='stage77_report_jobs'").fetchone())

    def test_generation_http_boundary_enqueues_without_rendering(self):
        source = (Path(__file__).parents[1] / "api" / "routes" / "admin_session.py").read_text(encoding="utf-8")
        boundary = source[source.index("def admin_governed_report_generate"):source.index("def admin_governed_report_supersede")]
        self.assertIn("rg77.enqueue_generation", boundary)
        self.assertNotIn("rg75.generate_report", boundary)
        self.assertNotIn("render_frozen_report", boundary)

    def test_two_separate_connections_have_one_winning_claim(self):
        item = jobs.enqueue_generation(self.conn, report_id=7, actor="admin-a", governed_action="enqueue_generation", idempotency_key="claim-race")
        db_path = Path(self.temp.name) / "records.db"
        self.conn.close()
        results = []
        barrier = threading.Barrier(2)
        bootstrap = jobs._connect(db_path)
        bootstrap.close()

        def claim(owner):
            connection = jobs._connect(db_path)
            try:
                barrier.wait(timeout=2)
                results.append(jobs.claim_one(connection, owner))
            finally:
                connection.close()

        first = threading.Thread(target=claim, args=("worker-a",))
        second = threading.Thread(target=claim, args=("worker-b",))
        first.start(); second.start(); first.join(timeout=5); second.join(timeout=5)
        self.assertEqual(sum(result is not None for result in results), 1)
        self.assertEqual(len(results), 2)
        self.conn = jobs._connect(db_path)

    def test_heartbeat_runs_during_blocking_render_and_stops_after_terminal(self):
        item = jobs.enqueue_generation(self.conn, report_id=7, actor="admin-a", governed_action="enqueue_generation", idempotency_key="heartbeat-render")
        claimed = jobs.claim_one(self.conn)

        def blocking_render(*_args, **_kwargs):
            time.sleep(0.08)
            return self.report

        with patch.object(jobs, "HEARTBEAT_SECONDS", 0.01), patch.object(jobs.reports, "generate_report", side_effect=blocking_render), patch.object(jobs, "_artifact_rows_valid", return_value=True):
            jobs.execute_job(str(Path(self.temp.name) / "records.db"), claimed)
        heartbeat_events = self.conn.execute("SELECT COUNT(*) FROM stage77_report_job_events WHERE job_id=? AND event_type='heartbeat'", (item["id"],)).fetchone()[0]
        self.assertGreaterEqual(heartbeat_events, 2)
        before = heartbeat_events
        time.sleep(0.03)
        after = self.conn.execute("SELECT COUNT(*) FROM stage77_report_job_events WHERE job_id=? AND event_type='heartbeat'", (item["id"],)).fetchone()[0]
        self.assertEqual(before, after)

    def test_cancelled_job_cannot_be_completed_by_current_token(self):
        item = jobs.enqueue_generation(self.conn, report_id=7, actor="admin-a", governed_action="enqueue_generation", idempotency_key="cancel-fence")
        claimed = jobs.claim_one(self.conn)
        jobs.request_cancel(self.conn, item["id"], "admin-a")
        self.assertFalse(jobs._terminal(self.conn, item["id"], claimed["lease_token"], "succeeded", jobs.WORKER_IDENTITY, phase="rendering", code="completed"))
        self.assertEqual(jobs.get_job(self.conn, item["id"])["state"], "cancel_requested")
        self.assertTrue(jobs._terminal(self.conn, item["id"], claimed["lease_token"], "cancelled", jobs.WORKER_IDENTITY, phase="cancellation", code="cancelled"))

    def test_worker_and_admin_connection_configuration_matches(self):
        path = Path(self.temp.name) / "pragma.db"
        connection = jobs._connect(path)
        try:
            self.assertEqual(connection.execute("PRAGMA journal_mode").fetchone()[0].lower(), "wal")
            self.assertEqual(connection.execute("PRAGMA busy_timeout").fetchone()[0], jobs.BUSY_TIMEOUT_MS)
            self.assertEqual(connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)
            self.assertEqual(connection.execute("PRAGMA synchronous").fetchone()[0], 1)
        finally:
            connection.close()

    def test_real_worker_loop_announces_readiness_with_empty_queue(self):
        path = Path(self.temp.name) / "worker-ready.db"
        stop = threading.Event()
        stop.set()
        ready = []
        self.assertEqual(jobs.worker_loop(str(path), stop, lambda: ready.append(True)), 0)
        self.assertEqual(ready, [True])
        check = sqlite3.connect(path)
        for table in ("record_governed_reports", "record_governed_report_versions", "record_governed_report_artifacts", "stage77_report_jobs", "stage77_report_job_events", "stage77_recovery_control", "stage77_recovery_events"):
            self.assertIsNotNone(check.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone())
        self.assertEqual(check.execute("SELECT COUNT(*) FROM record_governed_reports").fetchone()[0], 0)
        self.assertEqual(check.execute("SELECT COUNT(*) FROM record_governed_report_versions").fetchone()[0], 0)
        self.assertEqual(check.execute("SELECT COUNT(*) FROM record_governed_report_artifacts").fetchone()[0], 0)
        for table in ("record_governed_report_events", "record_governed_report_generation_attempts", "stage77_report_job_events"):
            self.assertEqual(check.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0)
        check.close()

    def test_worker_initialization_adds_stage75_schema_without_touching_recovery_state(self):
        path = Path(self.temp.name) / "production-shaped.db"
        connection = jobs._connect(path)
        jobs.reports.ensure_report_tables(connection)
        specification = recovery.canonical_json({"fixture": "worker-initialization"})
        specification_digest = recovery.digest_bytes(specification.encode("utf-8"))
        connection.execute("INSERT INTO record_governed_reports (idempotency_key,schema_version,report_type,title,purpose,intended_audience,distribution_class,created_by,created_by_role,created_at,lifecycle_status,request_payload_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", ("worker-report", "stage75.governed_report.v1", "canonical_record_report", "Worker fixture", "Worker schema validation", "internal", "internal_working", "admin", "administrator", "2026-01-01T00:00:00Z", "generated", "{}"))
        report_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
        connection.execute("INSERT INTO record_governed_report_versions (report_id,version_number,canonical_record_reference,specification_schema_version,specification_json,specification_digest,requested_formats_json,publication_engine_version,rendering_profile,template_version,created_by,created_at,lifecycle_status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (report_id, 1, "worker-fixture", "stage75.report_specification.v1", specification, specification_digest, "[]", "2.0.0", "internal", "cde-internal-v1", "admin", "2026-01-01T00:00:00Z", "generated"))
        jobs.ensure_job_tables(connection)
        recovery.ensure_recovery_tables(connection)
        recovery.request_recovery(connection, actor="admin", governed_action="synthetic")
        recovery.fail_recovery(connection, phase="capture", code="sqlite_error")
        before = recovery.recovery_status(connection)
        before_events = connection.execute("SELECT COUNT(*) FROM stage77_recovery_events").fetchone()[0]
        connection.close()
        stop = threading.Event(); stop.set(); ready = []
        self.assertEqual(jobs.worker_loop(str(path), stop, lambda: ready.append(True)), 0)
        check = sqlite3.connect(path)
        check.row_factory = sqlite3.Row
        self.assertEqual(ready, [True])
        self.assertEqual(check.execute("SELECT COUNT(*) FROM record_governed_reports").fetchone()[0], 1)
        self.assertEqual(check.execute("SELECT COUNT(*) FROM record_governed_report_versions").fetchone()[0], 1)
        self.assertEqual(check.execute("SELECT COUNT(*) FROM record_governed_report_artifacts").fetchone()[0], 0)
        self.assertEqual(check.execute("SELECT COUNT(*) FROM record_governed_report_events").fetchone()[0], 0)
        self.assertEqual(check.execute("SELECT COUNT(*) FROM record_governed_report_generation_attempts").fetchone()[0], 0)
        after = recovery.recovery_status(check)
        self.assertEqual(after["operation_id"], before["operation_id"])
        self.assertEqual(after["maintenance_epoch"], before["maintenance_epoch"])
        self.assertEqual(after["state"], "failed")
        self.assertEqual(check.execute("SELECT COUNT(*) FROM stage77_recovery_events").fetchone()[0], before_events)
        check.close()
        artifact_root = Path(self.temp.name) / "artifacts"
        artifact_root.mkdir()
        recovery_root = Path(self.temp.name) / "recovery"
        result = recovery.capture_recovery_point(database_path=path, artifact_root=artifact_root, recovery_root=recovery_root, approved_root=Path(self.temp.name), actor="admin", governed_action="synthetic-capture")
        manifest = __import__("json").loads((recovery_root / f"recovery-{result['recovery_point_id']}" / "manifest.json").read_text())
        self.assertEqual(manifest["job_event_bound"], 0)
        self.assertEqual(manifest["counts"]["reports"], 1)
        self.assertEqual(manifest["counts"]["versions"], 1)
        self.assertEqual(manifest["counts"]["artifacts"], 0)

    def test_empty_readiness_is_operational_but_recovery_ineligible(self):
        path = Path(self.temp.name) / "empty-readiness.db"
        connection = jobs._connect(path)
        jobs.reports.ensure_report_tables(connection)
        jobs.ensure_job_tables(connection)
        jobs.ensure_post_correction_tables(connection)
        recovery.ensure_recovery_tables(connection)
        artifact_root = Path(self.temp.name) / "empty-artifacts"
        artifact_root.mkdir()
        recovery_root = Path(self.temp.name) / "empty-recovery"
        before = tuple(connection.execute("SELECT COUNT(*) FROM record_governed_reports").fetchone())
        with self.assertRaisesRegex(recovery.RecoveryOperationFailure, "recovery_state_ineligible") as raised:
            recovery.capture_recovery_point(database_path=path, artifact_root=artifact_root, recovery_root=recovery_root, approved_root=Path(self.temp.name), actor="admin", governed_action="synthetic-capture")
        self.assertEqual(raised.exception.code, "recovery_state_ineligible")
        self.assertEqual(tuple(connection.execute("SELECT COUNT(*) FROM record_governed_reports").fetchone()), before)
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM record_governed_report_versions").fetchone()[0], 0)
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM stage77_recovery_point_evidence").fetchone()[0], 0)
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM stage77_recovery_point_evidence_events").fetchone()[0], 0)
        self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM pragma_foreign_key_check").fetchone()[0], 0)
        connection.close()

    def test_worker_withholds_readiness_on_incompatible_stage75_schema(self):
        path = Path(self.temp.name) / "incompatible-stage75.db"
        connection = sqlite3.connect(path)
        connection.execute("CREATE TABLE record_governed_reports(id TEXT, idempotency_key TEXT, lifecycle_status TEXT)")
        connection.commit(); connection.close()
        stop = threading.Event(); stop.set(); ready = []
        self.assertEqual(jobs.worker_loop(str(path), stop, lambda: ready.append(True)), 1)
        self.assertEqual(ready, [])

    def test_worker_initialization_is_idempotent_and_preserves_report_data(self):
        path = Path(self.temp.name) / "idempotent-stage75.db"
        stop = threading.Event(); stop.set()
        self.assertEqual(jobs.worker_loop(str(path), stop), 0)
        connection = sqlite3.connect(path)
        connection.execute("INSERT INTO record_governed_reports VALUES(1,'key','stage75.governed_report.v1','canonical_record_report','title','purpose','audience','internal_working','actor','admin','now','draft_specification','{}')")
        connection.commit(); connection.close()
        self.assertEqual(jobs.worker_loop(str(path), stop), 0)
        check = sqlite3.connect(path)
        self.assertEqual(check.execute("SELECT COUNT(*) FROM record_governed_reports").fetchone()[0], 1)
        self.assertEqual(check.execute("SELECT title FROM record_governed_reports WHERE id=1").fetchone()[0], "title")
        check.close()

    def test_concurrent_worker_initialization_is_bounded_and_idempotent(self):
        path = Path(self.temp.name) / "concurrent-stage75.db"
        barrier = threading.Barrier(2)
        results = []

        def initialize():
            barrier.wait(timeout=2)
            stop = threading.Event(); stop.set()
            results.append(jobs.worker_loop(str(path), stop))

        first = threading.Thread(target=initialize); second = threading.Thread(target=initialize)
        first.start(); second.start(); first.join(timeout=5); second.join(timeout=5)
        self.assertEqual(sorted(results), [0, 0])
        check = sqlite3.connect(path)
        self.assertEqual(check.execute("SELECT COUNT(*) FROM record_governed_reports").fetchone()[0], 0)
        check.close()

    def test_startup_connection_failure_uses_bounded_failure_marker(self):
        stop = threading.Event(); stop.set()
        with patch.object(jobs, "_connect", side_effect=sqlite3.OperationalError("database is locked")):
            with patch("builtins.print") as printed:
                self.assertEqual(jobs.worker_loop("/nonexistent/records.db", stop), 1)
        printed.assert_called_once_with("stage77_worker=startup_failure code=initialization_failed", flush=True)

    def test_retry_requires_terminal_failure(self):
        item = jobs.enqueue_generation(self.conn, report_id=7, actor="admin-a", governed_action="enqueue_generation", idempotency_key="retry")
        self.conn.execute("UPDATE stage77_report_jobs SET state='failed_terminal' WHERE id=?", (item["id"],))
        retry = jobs.retry_job(self.conn, item["id"], "admin-a")
        self.assertEqual(retry["retry_of_job_id"], item["id"])

    def test_retry_successor_execution_passes_successor_job_id_not_predecessor(self):
        item = jobs.enqueue_generation(self.conn, report_id=7, actor="admin-a", governed_action="enqueue_generation", idempotency_key="retry-current-job")
        self.conn.execute("UPDATE stage77_report_jobs SET state='failed_terminal' WHERE id=?", (item["id"],))
        successor = jobs.retry_job(self.conn, item["id"], "admin-a")
        claimed = jobs.claim_one(self.conn)
        self.assertEqual(claimed["id"], successor["id"])
        with patch.object(jobs.reports, "generate_report", side_effect=lambda *_args, **_kwargs: self.report) as render, patch.object(jobs, "_artifact_rows_valid", return_value=True):
            jobs.execute_job(str(Path(self.temp.name) / "records.db"), claimed)
        self.assertEqual(render.call_args.kwargs["governed_job_id"], successor["id"])
        self.assertNotEqual(render.call_args.kwargs["governed_job_id"], item["id"])


class Stage77SupervisorContractTests(unittest.TestCase):
    def test_runtime_wrapper_and_supervisor_are_bounded(self):
        root = Path(__file__).parents[1]
        wrapper = (root / "scripts/start_cde_runtime.sh").read_text()
        supervisor = (root / "scripts/cde_runtime_supervisor.py").read_text()
        self.assertIn("check_report_storage_runtime.py --mode durable", wrapper)
        self.assertIn("exec python scripts/cde_runtime_supervisor.py", wrapper)
        self.assertIn("--host", supervisor)
        self.assertIn("0.0.0.0", supervisor)
        self.assertIn("SIGTERM", supervisor)
        self.assertIn("stage77_supervisor=drain_start", supervisor)
        self.assertIn("governed_report_worker", supervisor)


class Stage77CustodyV2ContractTests(unittest.TestCase):
    # TEST ONLY — NOT PRODUCTION AUTHORITY (RFC 8032 test key one).
    _SEED = bytes.fromhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60")

    def _payload(self):
        value = {"schema": jobs.CUSTODY_V2_SCHEMA, "key_id": "test-ed25519-rfc8032-1", "mandate_id": "mandate-1", "mandate_digest": "a" * 64, "report_id": 1, "report_version_id": 1, "predecessor_job_ids": [1, 2], "purpose": jobs.CUSTODY_V2_PURPOSE, "runtime": {"project_id": "11111111-1111-1111-1111-111111111111", "service_id": "22222222-2222-2222-2222-222222222222", "environment_id": "33333333-3333-3333-3333-333333333333", "deployment_id": "44444444-4444-4444-4444-444444444444", "git_commit_sha": "b" * 40}, "capture_started_at": "2026-09-13T00:00:00Z", "capture_completed_at": "2026-09-13T00:00:01Z", "fence_result": True, "database": {"device": 1, "inode": 2, "size": 3, "mtime_ns": 4, "sha256": "c" * 64}, "checkpoint_result": True, "wal_result": True, "shm_result": True, "open_handle_result": True, "artifact_inventory_digest": "d" * 64, "points_1_5_digest": "e" * 64, "archive": {"id": "archive-1", "sha256": "f" * 64}, "encryption_profile": "aes256-gcm-v1", "encrypted_export": {"id": "export-1", "sha256": "1" * 64}, "transport": True, "receipt": {"id": "receipt-1", "sha256": "2" * 64}, "recovery_verification": {"id": "recovery-1", "sha256": "3" * 64}, "post_transport_verification": True, "created_at": "2026-09-13T00:00:02Z", "evidence_set_id": "evidence-1", "evidence_set_digest": "4" * 64}
        value["canonical_payload_digest"] = hashlib.sha256(jobs._canonical_v2(value)).hexdigest()
        return value

    def _recording_fixture(self):
        conn = sqlite3.connect(":memory:"); conn.row_factory = sqlite3.Row
        jobs.ensure_custody_v2_tables(conn)
        payload = self._payload()
        mandate = {"report_id": 1, "report_version_id": 1, "purpose": jobs.CUSTODY_V2_PURPOSE, "predecessor_job_ids": [1, 2], "runtime": payload["runtime"]}
        conn.execute("INSERT INTO stage77_custody_v2_mandates(id,report_id,report_version_id,predecessor_job_1_id,predecessor_job_2_id,purpose,mandate_json,mandate_digest,idempotency_key,state,actor,declaration,rationale,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", ("mandate-1", 1, 1, 1, 2, jobs.CUSTODY_V2_PURPOSE, jobs._canonical_v2(mandate).decode(), "a" * 64, "mandate-key", "created", "admin", "d", "r", "now"))
        conn.execute("INSERT INTO stage77_custody_evidence_sets(id,mandate_id,report_id,report_version_id,job1_id,job2_id,runtime_json,payload_json,payload_digest,idempotency_key,state,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", ("evidence-1", "mandate-1", 1, 1, 1, 2, jobs._canonical_v2(payload["runtime"]).decode(), "{}", "4" * 64, "evidence-key", "registered", "now"))
        return conn, payload

    def test_evidence_binding_is_required_and_covered_by_the_role_a_signature(self):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        payload = self._payload()
        private = Ed25519PrivateKey.from_private_bytes(self._SEED)
        signature = private.sign(jobs.CUSTODY_V2_DOMAIN + jobs._canonical_v2(payload))
        for field, value in (("evidence_set_id", None), ("evidence_set_digest", None), ("evidence_set_id", "bad/path"), ("evidence_set_digest", "0" * 63)):
            with self.subTest(field=field, value=value):
                mutated = dict(payload); mutated[field] = value
                if value is not None:
                    mutated["canonical_payload_digest"] = hashlib.sha256(jobs._canonical_v2({key: item for key, item in mutated.items() if key != "canonical_payload_digest"})).hexdigest()
                with self.assertRaises(ValueError): jobs._v2_validate_payload(mutated)
        changed = dict(payload); changed["evidence_set_digest"] = "0" * 64
        with self.assertRaises(Exception): private.public_key().verify(signature, jobs.CUSTODY_V2_DOMAIN + jobs._canonical_v2(changed))

    def test_record_v2_attestation_requires_matching_registered_evidence_and_persists_it_immutably(self):
        conn, payload = self._recording_fixture()
        try:
            raw = jobs._canonical_v2({"payload": payload, "signature": "test"}).decode()
            with patch.object(jobs, "_v2_verify_envelope", return_value=(payload, "test", "fingerprint")), patch.object(jobs, "custody_v2_runtime_authority", return_value=payload["runtime"]):
                row = jobs.record_custody_v2_envelope(conn, envelope_json=raw, actor="admin")
            self.assertEqual((row["evidence_set_id"], row["evidence_set_digest"]), ("evidence-1", "4" * 64))
            with self.assertRaises(sqlite3.DatabaseError): conn.execute("UPDATE stage77_custody_v2_attestations SET evidence_set_id='other' WHERE id=?", (row["id"],))
            with self.assertRaises(sqlite3.DatabaseError): conn.execute("UPDATE stage77_custody_v2_attestations SET evidence_set_digest=? WHERE id=?", ("0" * 64, row["id"]))
        finally:
            conn.close()

    def test_missing_substituted_or_nonregistered_evidence_cannot_be_replaced_by_an_envelope_claim(self):
        for state in ("missing", "invalidated", "expired", "consumed"):
            with self.subTest(state=state):
                conn, payload = self._recording_fixture()
                try:
                    if state == "missing": payload = {**payload, "evidence_set_id": "missing-evidence"}
                    else: conn.execute("UPDATE stage77_custody_evidence_sets SET state=?", (state,))
                    raw = jobs._canonical_v2({"payload": payload, "signature": "test"}).decode()
                    with patch.object(jobs, "_v2_verify_envelope", return_value=(payload, "test", "fingerprint")), patch.object(jobs, "custody_v2_runtime_authority", return_value=payload["runtime"]):
                        with self.assertRaisesRegex(ValueError, "custody_evidence_unavailable"):
                            jobs.record_custody_v2_envelope(conn, envelope_json=raw, actor="admin")
                finally:
                    conn.close()

    def test_v2_attestation_binding_replay_requires_identical_authority_and_conflicts_fail(self):
        conn, payload = self._recording_fixture()
        try:
            raw = jobs._canonical_v2({"payload": payload, "signature": "test"}).decode()
            with patch.object(jobs, "_v2_verify_envelope", return_value=(payload, "test", "fingerprint")), patch.object(jobs, "custody_v2_runtime_authority", return_value=payload["runtime"]):
                first = jobs.record_custody_v2_envelope(conn, envelope_json=raw, actor="admin")
                replay = jobs.record_custody_v2_envelope(conn, envelope_json=raw, actor="admin")
                self.assertEqual(replay["id"], first["id"])
                changed = dict(payload); changed["evidence_set_digest"] = "0" * 64
                with patch.object(jobs, "_v2_verify_envelope", return_value=(changed, "test", "fingerprint")):
                    with self.assertRaises(ValueError): jobs.record_custody_v2_envelope(conn, envelope_json=raw, actor="admin")
            self.assertEqual(first["state"], "verified")
        finally:
            conn.close()

    def test_full_public_vector_verifies_and_mutations_fail_closed(self):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        private = Ed25519PrivateKey.from_private_bytes(self._SEED)
        public = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        self.assertEqual(hashlib.sha256(public).hexdigest(), "21fe31dfa154a261626bf854046fd2271b7bed4b6abe45aa58877ef47f9721b9")
        payload = self._payload()
        signature = private.sign(jobs.CUSTODY_V2_DOMAIN + jobs._canonical_v2(payload))
        envelope = {"payload": payload, "signature": base64.b64encode(signature).decode("ascii")}
        raw = jobs._canonical_v2(envelope).decode("utf-8")
        keyring = {"keys": [{"id": payload["key_id"], "public_key_b64": base64.b64encode(public).decode("ascii"), "fingerprint": hashlib.sha256(public).hexdigest(), "state": "active"}]}
        environment = {jobs.CUSTODY_V2_ENABLE_ENV: "1", jobs.CUSTODY_V2_KEYRING_ENV: jobs._canonical_v2(keyring).decode("utf-8")}
        with patch.dict(os.environ, environment, clear=False):
            verified, _, _ = jobs._v2_verify_envelope(raw)
            self.assertEqual(verified, payload)
            envelope["payload"]["archive"]["sha256"] = "0" * 64
            with self.assertRaises(ValueError):
                jobs._v2_verify_envelope(jobs._canonical_v2(envelope).decode("utf-8"))

    def test_disabled_pre_activation_fails_closed_without_a_keyring(self):
        with patch.dict(os.environ, {jobs.CUSTODY_V2_ENABLE_ENV: ""}, clear=False):
            with self.assertRaisesRegex(ValueError, "stage77_custody_v2_disabled"):
                jobs.custody_v2_runtime_authority()

    def test_additive_v2_ledger_has_single_use_authority_boundary(self):
        conn = sqlite3.connect(":memory:")
        try:
            jobs.ensure_custody_v2_tables(conn)
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertTrue({"stage77_custody_v2_mandates", "stage77_custody_v2_attestations", "stage77_custody_v2_events"} <= tables)
            states = {row[1] for row in conn.execute("PRAGMA table_info(stage77_custody_v2_attestations)")}
            self.assertIn("consumed_job_id", states)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
