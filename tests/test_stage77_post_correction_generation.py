import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from api import governed_report_jobs as jobs
from api import governed_report_recovery as recovery


class PostCorrectionGenerationContractTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(
            """
            CREATE TABLE record_governed_reports (id INTEGER PRIMARY KEY, lifecycle_status TEXT);
            CREATE TABLE record_governed_report_versions (id INTEGER PRIMARY KEY, report_id INTEGER);
            """
        )
        jobs.ensure_job_tables(self.conn)
        jobs.ensure_post_correction_tables(self.conn)

    def tearDown(self):
        self.conn.close()

    def _point6_custody_prerequisite(self):
        from tests.test_stage77_diagnostic_retry import DiagnosticRetryTests

        fixture = DiagnosticRetryTests()
        fixture.setUp()
        successor = fixture.authorize()
        claimed = jobs.claim_one(fixture.connection)
        self.assertEqual(claimed["id"], successor["id"])
        jobs.reports.record_diagnostic_retry_validation_failure(
            fixture.connection,
            report_id=successor["report_id"],
            version_id=successor["report_version_id"],
            job_id=successor["id"],
            payload={"reason": "custody attestation prerequisite"},
            _commit=False,
        )
        self.assertTrue(jobs._terminal(fixture.connection, successor["id"], claimed["lease_token"], "failed_terminal", jobs.WORKER_IDENTITY, phase="revalidation", code="qualification_invalid"))
        from api import governed_report_diagnostics as diagnostics
        fixture.connection.execute(
            "UPDATE record_governed_report_generation_attempts SET diagnostics_json=? WHERE idempotency_key=?",
            (recovery.canonical_json(list(diagnostics.LEGACY_ATTEMPT_DIAGNOSTICS)), f"stage77-job-{fixture.original_job['id']}"),
        )
        fixture.connection.execute(
            "UPDATE stage77_report_job_events SET payload_json=? WHERE job_id=? AND event_type='terminal'",
            (recovery.canonical_json(diagnostics.LEGACY_TERMINAL_PAYLOAD), fixture.original_job["id"]),
        )
        transitional = diagnostics.TRANSITIONAL_DIAGNOSTIC
        fixture.connection.execute(
            "INSERT INTO record_governed_report_generation_attempts (version_id,requested_formats_json,actor,actor_role,requested_at,result,diagnostics_json,request_payload_json,idempotency_key) VALUES(?,?,?,?,?,?,?,?,?)",
            (successor["report_version_id"], '["docx", "html", "pdf"]', jobs.WORKER_IDENTITY, "system_worker", "2026-01-01T00:00:02Z", "validation_failed", recovery.canonical_json([transitional]), "{}", f"stage77-job-{successor['id']}"),
        )
        fixture.connection.execute(
            "UPDATE record_governed_report_generation_attempts SET diagnostics_json=? WHERE idempotency_key=?",
            (recovery.canonical_json([transitional]), f"stage77-job-{successor['id']}"),
        )
        fixture.connection.execute(
            "UPDATE stage77_report_jobs SET terminal_outcome='validation_failed',failure_phase='rendering',failure_code=? WHERE id=?",
            (jobs.DIAGNOSTIC_RETRY_FAILURE_CODE, successor["id"]),
        )
        fixture.connection.execute(
            "UPDATE stage77_report_job_events SET payload_json=? WHERE job_id=? AND event_type='terminal'",
            (recovery.canonical_json({"phase": "rendering", "code": jobs.DIAGNOSTIC_RETRY_FAILURE_CODE, "diagnostic": transitional, **transitional}), successor["id"]),
        )
        fixture.connection.commit()
        temp = tempfile.TemporaryDirectory(dir="/private/tmp")
        self.addCleanup(temp.cleanup)
        from pathlib import Path
        root = Path(temp.name)
        database = root / "records.db"
        copied = sqlite3.connect(database)
        copied.row_factory = sqlite3.Row
        try:
            fixture.connection.backup(copied)
        finally:
            copied.close()
        fixture.tearDown()
        fixture.connection = sqlite3.connect(database, isolation_level=None)
        fixture.connection.row_factory = sqlite3.Row
        self.addCleanup(fixture.connection.close)
        recovery.ensure_recovery_tables(fixture.connection)
        fixture.connection.execute("DELETE FROM stage77_recovery_control")
        fixture.connection.execute(
            "INSERT INTO stage77_recovery_control(singleton,operation_id,recovery_point_id,operation_type,requested_actor,governed_action,state,maintenance_epoch,requested_at,completed_at,schema_version,worker_drained,manifest_digest,idempotency_key) VALUES(1,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("previous-operation", "previous-point", "capture", "admin", "capture", "completed", jobs.POST_CORRECTION_RECOVERY_EPOCH - 1, "2026-01-01T00:00:00Z", "2026-01-01T00:00:01Z", recovery.RECOVERY_SCHEMA_VERSION, 1, "0" * 64, "previous-point"),
        )
        recovery_root = root / "recovery"
        artifact_root = root / "artifacts"
        artifact_root.mkdir()
        token_values = iter(["operation-point6".ljust(32, "0"), jobs.POST_CORRECTION_RECOVERY_POINT, "evidence-point6".ljust(32, "0")])
        with patch.object(recovery.secrets, "token_hex", side_effect=lambda _size: next(token_values)):
            recovery.capture_recovery_point(
                database_path=database,
                artifact_root=artifact_root,
                recovery_root=recovery_root,
                approved_root=root,
                actor="admin",
                governed_action="capture",
                idempotency_key="point6-custody-prerequisite",
            )
        return fixture

    def test_authorization_tables_and_one_to_one_indexes_exist(self):
        tables = {row[0] for row in self.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertIn("stage77_post_correction_authorizations", tables)
        self.assertIn("stage77_post_correction_execution_links", tables)
        indexes = {row[1] for row in self.conn.execute("PRAGMA index_list(stage77_report_jobs)")}
        self.assertIn("idx_stage77_jobs_post_correction_authorization", indexes)
        self.assertIn("stage77_post_correction_custody_attestations", tables)
        self.assertIn("stage77_post_correction_custody_attestation_events", tables)

    def test_custody_attestation_contract_is_distinct_and_finalized(self):
        columns = {row[1] for row in self.conn.execute("PRAGMA table_info(stage77_post_correction_custody_attestations)")}
        self.assertEqual(jobs.POST_CORRECTION_CUSTODY_ATTESTATION_CONTRACT, "stage77.post_correction_custody_attestation.v1")
        self.assertIn("attestation_digest", columns)
        self.assertIn("custody_directory_identity", columns)
        self.assertIn("declaration_json", columns)

    def test_custody_attestation_and_event_rows_are_immutable(self):
        trigger_names = {row[0] for row in self.conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
        self.assertIn("stage77_custody_attestation_no_update", trigger_names)
        self.assertIn("stage77_custody_attestation_no_delete", trigger_names)
        self.assertIn("stage77_custody_attestation_events_no_update", trigger_names)
        self.assertIn("stage77_custody_attestation_events_no_delete", trigger_names)

    def test_canonical_custody_identity_records_attestation_without_authorizing_generation(self):
        fixture = self._point6_custody_prerequisite()
        result = jobs.record_post_correction_custody_attestation(
            fixture.connection,
            report_id=fixture.report["id"],
            actor="admin",
            actor_role="admin",
            rationale="Point 6 custody export was validated offline.",
            acknowledged=True,
            archive_digest=jobs.POST_CORRECTION_ARCHIVE_DIGEST,
            receipt_digest=jobs.POST_CORRECTION_RECEIPT_DIGEST,
            archive_size_bytes=jobs.POST_CORRECTION_POINT6_ARCHIVE_SIZE,
            custody_directory_identity=jobs.POST_CORRECTION_POINT6_CUSTODY_ID,
            idempotency_key="canonical-custody-attestation",
        )
        self.assertEqual(result["state"], "finalized")
        row = fixture.connection.execute("SELECT * FROM stage77_post_correction_custody_attestations").fetchone()
        self.assertEqual(row["custody_directory_identity"], jobs.POST_CORRECTION_POINT6_CUSTODY_ID)
        self.assertEqual(row["report_id"], fixture.report["id"])
        self.assertEqual(row["recovery_point_id"], jobs.POST_CORRECTION_RECOVERY_POINT)
        self.assertEqual(row["archive_digest"], jobs.POST_CORRECTION_ARCHIVE_DIGEST)
        self.assertEqual(row["receipt_digest"], jobs.POST_CORRECTION_RECEIPT_DIGEST)
        evidence = recovery.recovery_evidence_for_point(fixture.connection, jobs.POST_CORRECTION_RECOVERY_POINT)
        links, digest = recovery._retry_topology_snapshot(fixture.connection)
        self.assertEqual(evidence["retry_link_count"], 1)
        self.assertEqual(evidence["retry_topology_digest"], digest)
        self.assertEqual(row["recovery_evidence_id"], evidence["id"])
        self.assertEqual(row["retry_topology_digest"], evidence["retry_topology_digest"])
        self.assertEqual(len(links), 1)
        self.assertEqual(fixture.connection.execute("SELECT COUNT(*) FROM stage77_post_correction_authorizations").fetchone()[0], 0)
        self.assertEqual(fixture.connection.execute("SELECT COUNT(*) FROM stage77_post_correction_execution_links").fetchone()[0], 0)
        self.assertEqual(fixture.connection.execute("SELECT COUNT(*) FROM stage77_report_jobs WHERE governed_action=?", (jobs.POST_CORRECTION_ACTION,)).fetchone()[0], 0)
        replay = jobs.record_post_correction_custody_attestation(
            fixture.connection,
            report_id=fixture.report["id"],
            actor="admin",
            actor_role="admin",
            rationale="Point 6 custody export was validated offline.",
            acknowledged=True,
            archive_digest=jobs.POST_CORRECTION_ARCHIVE_DIGEST,
            receipt_digest=jobs.POST_CORRECTION_RECEIPT_DIGEST,
            archive_size_bytes=jobs.POST_CORRECTION_POINT6_ARCHIVE_SIZE,
            custody_directory_identity=jobs.POST_CORRECTION_POINT6_CUSTODY_ID,
            idempotency_key="canonical-custody-attestation",
        )
        self.assertEqual(replay["id"], row["id"])

    def test_custody_identity_shape_and_exact_value_are_independently_enforced(self):
        invalid_values = [
            "123456",
            "",
            "2026-08-25T195900Z_71f4471e987ef38d1bdbd1b64dd7557c",
            "2026-08-25T195900Z_71F4471E987EF38D1BDBD1B64DD7557B",
            "2026-08-25T195900Z_71f4471e987ef38d1bdbd1b64dd7557",
            "2026-08-25T195900Z_71f4471e987ef38d1bdbd1b64dd7557b0",
            "2026-08-25 195900Z_71f4471e987ef38d1bdbd1b64dd7557b",
            " 2026-08-25T195900Z_71f4471e987ef38d1bdbd1b64dd7557b",
            "2026-08-25T195900Z_71f4471e987ef38d1bdbd1b64dd7557b ",
            "not-a-custody-identity",
        ]
        for index, value in enumerate(invalid_values):
            with self.subTest(identity=value):
                fixture = self._point6_custody_prerequisite()
                expected = "governed_report_custody_attestation_evidence_mismatch" if index == 2 else "governed_report_custody_attestation_identity_invalid"
                for attempt in range(2):
                    with self.assertRaisesRegex(ValueError, expected):
                        jobs.record_post_correction_custody_attestation(
                            fixture.connection,
                            report_id=fixture.report["id"],
                            actor="admin",
                            actor_role="admin",
                            rationale="Point 6 custody export was validated offline.",
                            acknowledged=True,
                            archive_digest=jobs.POST_CORRECTION_ARCHIVE_DIGEST,
                            receipt_digest=jobs.POST_CORRECTION_RECEIPT_DIGEST,
                            archive_size_bytes=jobs.POST_CORRECTION_POINT6_ARCHIVE_SIZE,
                            custody_directory_identity=value,
                            idempotency_key=f"invalid-custody-attestation-{index}",
                        )
                self.assertEqual(fixture.connection.execute("SELECT COUNT(*) FROM stage77_post_correction_custody_attestations").fetchone()[0], 0)
                self.assertEqual(fixture.connection.execute("SELECT COUNT(*) FROM stage77_post_correction_authorizations").fetchone()[0], 0)
                self.assertEqual(fixture.connection.execute("SELECT COUNT(*) FROM stage77_post_correction_execution_links").fetchone()[0], 0)

    def test_custody_attestation_rejects_topology_drift_after_recovery_capture(self):
        cases = [
            ("removed_retry_link", lambda conn: conn.execute("UPDATE stage77_report_jobs SET retry_of_job_id=NULL WHERE retry_of_job_id IS NOT NULL"), "governed_report_post_correction_job_topology_invalid"),
            ("changed_predecessor_identity", lambda conn: conn.execute("UPDATE stage77_report_jobs SET retry_of_job_id=999 WHERE retry_of_job_id IS NOT NULL"), "governed_report_post_correction_job_topology_invalid"),
            ("changed_successor_identity", lambda conn: conn.execute("UPDATE stage77_report_jobs SET id=99 WHERE retry_of_job_id IS NOT NULL"), "governed_report_diagnostic_retry_predecessor_invalid"),
            ("changed_predecessor_action", lambda conn: conn.execute("UPDATE stage77_report_jobs SET governed_action='authorize_diagnostic_retry' WHERE retry_of_job_id IS NULL"), "retry_topology_invalid"),
            (
                "structurally_valid_physical_identity_drift",
                lambda conn: (
                    conn.execute("UPDATE stage77_report_jobs SET id=101 WHERE id=1"),
                    conn.execute("UPDATE stage77_report_jobs SET id=205,retry_of_job_id=101 WHERE id=2"),
                    conn.execute("UPDATE stage77_report_job_events SET job_id=101 WHERE job_id=1"),
                    conn.execute("UPDATE stage77_report_job_events SET job_id=205 WHERE job_id=2"),
                    conn.execute("UPDATE record_governed_report_generation_attempts SET idempotency_key='stage77-job-101' WHERE idempotency_key='stage77-job-1'"),
                    conn.execute("UPDATE record_governed_report_generation_attempts SET idempotency_key='stage77-job-205' WHERE idempotency_key='stage77-job-2'"),
                ),
                "governed_report_custody_attestation_diagnostic_invalid",
            ),
        ]
        for name, mutate, expected in cases:
            with self.subTest(case=name):
                fixture = self._point6_custody_prerequisite()
                jobs.ensure_post_correction_tables(fixture.connection)
                before = fixture.connection.execute("SELECT COUNT(*) FROM stage77_post_correction_custody_attestations").fetchone()[0]
                fixture.connection.execute("PRAGMA foreign_keys=OFF")
                mutate(fixture.connection)
                fixture.connection.execute("PRAGMA foreign_keys=ON")
                with self.assertRaisesRegex(ValueError, expected):
                    jobs.record_post_correction_custody_attestation(
                        fixture.connection,
                        report_id=fixture.report["id"],
                        actor="admin",
                        actor_role="admin",
                        rationale="Point 6 custody export was validated offline.",
                        acknowledged=True,
                        archive_digest=jobs.POST_CORRECTION_ARCHIVE_DIGEST,
                        receipt_digest=jobs.POST_CORRECTION_RECEIPT_DIGEST,
                        archive_size_bytes=jobs.POST_CORRECTION_POINT6_ARCHIVE_SIZE,
                        custody_directory_identity=jobs.POST_CORRECTION_POINT6_CUSTODY_ID,
                        idempotency_key=f"topology-drift-{name}",
                    )
                self.assertEqual(fixture.connection.execute("SELECT COUNT(*) FROM stage77_post_correction_custody_attestations").fetchone()[0], before)
                self.assertEqual(fixture.connection.execute("SELECT COUNT(*) FROM stage77_post_correction_authorizations").fetchone()[0], 0)
                self.assertEqual(fixture.connection.execute("SELECT COUNT(*) FROM stage77_post_correction_execution_links").fetchone()[0], 0)

    def test_referenced_recovery_evidence_topology_cannot_be_rewritten_for_attestation(self):
        fixture = self._point6_custody_prerequisite()
        jobs.ensure_post_correction_tables(fixture.connection)
        evidence = recovery.recovery_evidence_for_point(fixture.connection, jobs.POST_CORRECTION_RECOVERY_POINT)
        for sql in (
            "UPDATE stage77_recovery_point_evidence SET retry_link_count=0 WHERE id=?",
            "UPDATE stage77_recovery_point_evidence SET retry_topology_digest=? WHERE id=?",
            "UPDATE stage77_recovery_point_evidence SET evidence_digest=? WHERE id=?",
        ):
            with self.subTest(sql=sql):
                if sql.count("?") == 1:
                    params = (evidence["id"],)
                else:
                    params = ("0" * 64, evidence["id"])
                with self.assertRaises(sqlite3.IntegrityError):
                    fixture.connection.execute(sql, params)
                fixture.connection.rollback()
        self.assertEqual(fixture.connection.execute("SELECT COUNT(*) FROM stage77_post_correction_custody_attestations").fetchone()[0], 0)
        self.assertEqual(fixture.connection.execute("SELECT COUNT(*) FROM stage77_post_correction_authorizations").fetchone()[0], 0)
        self.assertEqual(fixture.connection.execute("SELECT COUNT(*) FROM stage77_post_correction_execution_links").fetchone()[0], 0)

    def test_exact_post_correction_schema_selects_new_contract_with_zero_rows(self):
        contract, _evidence, _evidence_digest, _links, _links_digest = recovery._database_contract(self.conn)
        self.assertEqual(contract, "post_correction_aware")

    def test_partial_post_correction_schema_fails_closed(self):
        self.conn.execute("DROP TABLE stage77_post_correction_execution_links")
        with self.assertRaisesRegex(ValueError, "post_correction_schema_incompatible"):
            recovery._database_contract(self.conn)

    def test_generic_retry_rejects_a_retry_predecessor(self):
        self.conn.execute("INSERT INTO record_governed_reports VALUES(1,'validation_failed')")
        self.conn.execute("INSERT INTO record_governed_report_versions VALUES(1,1)")
        self.conn.execute(
            "INSERT INTO stage77_report_jobs(report_id,report_version_id,specification_digest,requested_formats_json,rendering_profile,template_version,publication_engine_version,requesting_actor,governed_action,requested_at,state,attempt_count,max_attempts,next_eligible_at,idempotency_key,retry_of_job_id,schema_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (1, 1, "a" * 64, "[]", "internal", "cde-internal-v1", "2.0.0", "nick", jobs.DIAGNOSTIC_RETRY_ACTION, jobs.utc_now(), "failed_terminal", 1, 3, jobs.utc_now(), "job-2", 1, jobs.JOB_SCHEMA_VERSION),
        )
        self.conn.commit()
        with self.assertRaisesRegex(ValueError, "retry_of_retry_forbidden"):
            jobs.retry_job(self.conn, 1, "nick")

    def test_post_correction_action_is_not_a_retry(self):
        self.assertNotEqual(jobs.POST_CORRECTION_ACTION, jobs.DIAGNOSTIC_RETRY_ACTION)
        self.assertEqual(jobs.POST_CORRECTION_ACTION.find("retry"), -1)


if __name__ == "__main__":
    unittest.main()
