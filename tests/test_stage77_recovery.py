import json
import io
import os
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from api import governed_report_jobs as jobs
from api import governed_report_recovery as recovery
from api import governed_report_qualifications as qualifications
from api import record_governed_reports as reports


class Stage77RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir="/private/tmp")
        self.root = Path(self.temp.name)
        self.db = self.root / "records.db"
        self.artifacts = self.root / "artifacts"
        self.artifacts.mkdir()
        self.recovery_root = self.root / "recovery"
        self.conn = sqlite3.connect(self.db, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript("""
        CREATE TABLE record_governed_reports(id INTEGER PRIMARY KEY, lifecycle_status TEXT NOT NULL);
        CREATE TABLE record_governed_report_versions(id INTEGER PRIMARY KEY, report_id INTEGER NOT NULL, lifecycle_status TEXT NOT NULL, FOREIGN KEY(report_id) REFERENCES record_governed_reports(id));
        CREATE TABLE record_governed_report_artifacts(id INTEGER PRIMARY KEY, version_id INTEGER NOT NULL, format TEXT NOT NULL, storage_reference TEXT NOT NULL, sha256 TEXT NOT NULL, size_bytes INTEGER NOT NULL, validation_state TEXT NOT NULL, FOREIGN KEY(version_id) REFERENCES record_governed_report_versions(id));
        """)
        self.conn.execute("INSERT INTO record_governed_reports VALUES(7,'generated')")
        self.conn.execute("INSERT INTO record_governed_report_versions VALUES(11,7,'generated')")
        self.conn.execute("ALTER TABLE record_governed_report_versions ADD COLUMN specification_json TEXT")
        self.conn.execute("ALTER TABLE record_governed_report_versions ADD COLUMN specification_digest TEXT")
        specification = recovery.canonical_json({"fixture": "stage77"})
        self.conn.execute("UPDATE record_governed_report_versions SET specification_json=?, specification_digest=? WHERE id=11", (specification, recovery.digest_bytes(specification.encode("utf-8"))))
        self.bytes = b"synthetic governed artifact"
        self.artifact = self.artifacts / "server-generated.docx"
        self.artifact.write_bytes(self.bytes)
        self.conn.execute("INSERT INTO record_governed_report_artifacts VALUES(3,11,'docx',?,?,?,'valid')", (str(self.artifact), recovery.digest_bytes(self.bytes), len(self.bytes)))
        jobs.ensure_job_tables(self.conn)
        qualifications.ensure_qualification_tables(self.conn)

    def tearDown(self):
        self.conn.close()
        self.temp.cleanup()

    def _bundle(self):
        result = recovery.capture_recovery_point(database_path=self.db, artifact_root=self.artifacts, recovery_root=self.recovery_root, approved_root=self.root, actor="admin", governed_action="capture")
        return self.recovery_root / f"recovery-{result['recovery_point_id']}"

    def _producer_modern_fixture(self, name, *, caller_format_order=False, template_version=None, publication_engine_version=None):
        from tests.test_stage77_diagnostic_retry import DiagnosticRetryTests
        fixture = DiagnosticRetryTests()
        if caller_format_order or template_version is not None or publication_engine_version is not None:
            original_create_report = reports.create_report
            with patch.object(reports, "create_report") as create_report:
                def reordered_create_report(conn, **kwargs):
                    if caller_format_order:
                        kwargs["requested_formats"] = ["pdf", "docx", "html"]
                    if template_version is not None:
                        kwargs["template_version"] = template_version
                    return original_create_report(conn, **kwargs)
                create_report.side_effect = reordered_create_report
                if publication_engine_version is None:
                    fixture.setUp()
                else:
                    with patch.object(reports, "PUBLICATION_ENGINE_VERSION", publication_engine_version):
                        fixture.setUp()
        else:
            fixture.setUp()
        successor = fixture.authorize()
        leased = jobs.claim_one(fixture.connection)
        self.assertEqual(leased["id"], successor["id"])
        reports.record_diagnostic_retry_validation_failure(
            fixture.connection,
            report_id=successor["report_id"],
            version_id=successor["report_version_id"],
            job_id=successor["id"],
            payload={"reason": "non-rendering fixture transition"},
            _commit=False,
        )
        self.assertTrue(jobs._terminal(fixture.connection, successor["id"], leased["lease_token"], "failed_terminal", jobs.WORKER_IDENTITY, phase="revalidation", code="qualification_invalid"))
        root = self.root / name
        root.mkdir()
        database = root / "database.sqlite3"
        copied = sqlite3.connect(database)
        try:
            fixture.connection.backup(copied)
        finally:
            copied.close()
            fixture.tearDown()
        artifact_root = root / "artifacts"
        artifact_root.mkdir()
        recovery_root = root / "recovery"
        captured = recovery.capture_recovery_point(database_path=database, artifact_root=artifact_root, recovery_root=recovery_root, approved_root=root, actor="admin", governed_action="capture")
        bundle = recovery_root / f"recovery-{captured['recovery_point_id']}"
        live_db = self.root / f"{name}-live.sqlite3"
        live = sqlite3.connect(live_db)
        recovery.ensure_recovery_tables(live)
        live.close()
        archived = sqlite3.connect(bundle / "database.sqlite3")
        job_ids = [int(row[0]) for row in archived.execute("SELECT id FROM stage77_report_jobs ORDER BY id").fetchall()]
        archived.close()
        return bundle, live_db, captured["recovery_point_id"], job_ids

    def test_batch3b4b3a4a2_producer_rejects_second_final_for_same_version(self):
        from tests.test_stage77_diagnostic_retry import DiagnosticRetryTests
        fixture = DiagnosticRetryTests()
        fixture.setUp()
        fixture_closed = False
        try:
            with self.assertRaisesRegex(ValueError, "governed_report_qualification_gate_order_invalid"):
                qualifications.record_gate(
                    fixture.connection,
                    report_id=fixture.report["id"],
                    resulting_status="assembly_reviewed",
                    actor="nick",
                    rationale="prohibited second finalized qualification",
                    declaration={"acknowledged": True, "no_independent_administrator_available": True, "application_did_not_verify_declaration": True},
                    idempotency_key="prohibited-second-final",
                )
        finally:
            fixture.tearDown()

    def test_batch3b4b3a4a2_alternate_ownership_is_capture_inapplicable(self):
        from tests.test_stage77_diagnostic_retry import DiagnosticRetryTests
        fixture = DiagnosticRetryTests()
        fixture.setUp()
        try:
            alternate = reports.create_report(
                fixture.connection,
                title="Alternate internal report",
                purpose="Alternate qualification ownership fixture",
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
                idempotency_key="alternate-qualification-report",
            )
            declaration = {"acknowledged": True, "no_independent_administrator_available": True, "application_did_not_verify_declaration": True}
            for status, key in (("assembly_reviewed", "alternate-assembly"), ("privacy_reviewed", "alternate-privacy"), ("redaction_reviewed", "alternate-redaction"), ("approved_for_generation", "alternate-approval")):
                alternate = reports.confirm_creator_gate(fixture.connection, report_id=alternate["id"], resulting_status=status, rationale="Alternate qualification fixture confirmation", actor="nick", actor_role="administrator", acknowledged=True, idempotency_key=key)
            alternate_qualification = qualifications.latest_final(fixture.connection, alternate["id"])
            self.assertIsNotNone(alternate_qualification)
            root = self.root / "qualification-owner-inapplicable"
            root.mkdir()
            database = root / "database.sqlite3"
            copied = sqlite3.connect(database)
            try:
                fixture.connection.backup(copied)
            finally:
                copied.close()
                fixture.tearDown()
                fixture_closed = True
            (root / "artifacts").mkdir()
            with self.assertRaisesRegex(recovery.RecoveryOperationFailure, "record_count_mismatch"):
                recovery.capture_recovery_point(database_path=database, artifact_root=root / "artifacts", recovery_root=root / "recovery", approved_root=root, actor="admin", governed_action="capture")
        finally:
            if not fixture_closed:
                fixture.tearDown()

    def _create_alternate_qualification(self, fixture):
        alternate = reports.create_report(
            fixture.connection,
            title="Alternate internal report",
            purpose="Alternate qualification ownership fixture",
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
            idempotency_key="alternate-qualification-report-direct",
        )
        declaration = {"acknowledged": True, "no_independent_administrator_available": True, "application_did_not_verify_declaration": True}
        for status, key in (("assembly_reviewed", "alternate-direct-assembly"), ("privacy_reviewed", "alternate-direct-privacy"), ("redaction_reviewed", "alternate-direct-redaction"), ("approved_for_generation", "alternate-direct-approval")):
            alternate = reports.confirm_creator_gate(fixture.connection, report_id=alternate["id"], resulting_status=status, rationale="Alternate qualification fixture confirmation", actor="nick", actor_role="administrator", acknowledged=True, idempotency_key=key)
        return qualifications.latest_final(fixture.connection, alternate["id"])

    def test_batch3b4b3a4a2_job_bound_alternate_ownership_matrix(self):
        from tests.test_stage77_diagnostic_retry import DiagnosticRetryTests
        for name, targets in (("job1", (0,)), ("job2", (1,)), ("both", (0, 1))):
            with self.subTest(case=name):
                fixture = DiagnosticRetryTests()
                fixture.setUp()
                try:
                    alternate = self._create_alternate_qualification(fixture)
                    fixture.authorize()
                    job_rows = [dict(row) for row in fixture.connection.execute("SELECT id FROM stage77_report_jobs ORDER BY id").fetchall()]
                    for target in targets:
                        fixture.connection.execute("UPDATE stage77_report_jobs SET qualification_id=?, qualification_digest=? WHERE id=?", (alternate["id"], alternate["digest"], job_rows[target]["id"]))
                    with self.assertRaisesRegex(ValueError, "job_qualification_binding_mismatch"):
                        recovery._validate_archived_job_qualification_binding(fixture.connection, contract="diagnostic_aware")
                    self.assertEqual(fixture.connection.execute("SELECT COUNT(*) FROM stage77_report_job_events").fetchone()[0], 3)
                finally:
                    fixture.tearDown()

    def test_batch3b4b3a4b_qualification_chain_recovery_consumption(self):
        def remove_event(conn, qualification_id):
            conn.execute("PRAGMA foreign_keys=OFF")
            conn.execute("DELETE FROM record_governed_report_qualification_events WHERE qualification_id=?", (qualification_id,))

        def duplicate_event(conn, qualification_id):
            row = conn.execute("SELECT report_id,report_version_id,event_type,actor,occurred_at,payload_json FROM record_governed_report_qualification_events WHERE qualification_id=?", (qualification_id,)).fetchone()
            conn.execute("INSERT INTO record_governed_report_qualification_events(qualification_id,report_id,report_version_id,event_type,actor,occurred_at,idempotency_key,payload_json) VALUES(?,?,?,?,?,?,?,?)", (qualification_id, row[0], row[1], row[2], row[3], row[4], "duplicate-chain-event", row[5]))

        def mutate_chain(conn, qualification_id, *, gate=None, state=None):
            payload = json.loads(conn.execute("SELECT qualification_payload_json FROM record_governed_report_qualifications WHERE id=?", (qualification_id,)).fetchone()[0])
            if gate is not None:
                payload["completed_gate"] = gate
            if state is not None:
                conn.execute("PRAGMA ignore_check_constraints=ON")
            digest = qualifications._payload_digest(payload)
            conn.execute("UPDATE record_governed_report_qualifications SET completed_gate=COALESCE(?,completed_gate), qualification_state=COALESCE(?,qualification_state), qualification_payload_json=?, qualification_digest=? WHERE id=?", (gate, state, qualifications.canonical_json(payload), digest, qualification_id))

        cases = [
            ("missing_intermediate_event", lambda c: remove_event(c, 2), "governed_report_qualification_event_invalid"),
            ("duplicate_final_event", lambda c: duplicate_event(c, 4), "governed_report_qualification_event_invalid"),
            ("wrong_gate_order", lambda c: mutate_chain(c, 2, gate="assembly"), "governed_report_qualification_gate_order_invalid"),
            ("non_final_chain", lambda c: mutate_chain(c, 4, state="draft"), "integrity_check_failed"),
            ("digest_recomputed_invalid_chain", lambda c: mutate_chain(c, 3, gate="assembly"), "governed_report_qualification_gate_order_invalid"),
            ("wrong_report_ownership", lambda c: (c.execute("PRAGMA foreign_keys=OFF"), c.execute("UPDATE record_governed_report_qualifications SET report_id=999 WHERE id=2")), "foreign_key_check_failed"),
            ("wrong_version_ownership", lambda c: (c.execute("PRAGMA foreign_keys=OFF"), c.execute("UPDATE record_governed_report_qualifications SET report_version_id=999 WHERE id=2")), "foreign_key_check_failed"),
        ]
        for index, (name, mutation, expected) in enumerate(cases):
            with self.subTest(case=name):
                bundle, live_db, point_id, _job_ids = self._producer_modern_fixture(f"qualification-chain-{index}")
                archived = sqlite3.connect(bundle / "database.sqlite3")
                mutation(archived)
                archived.commit()
                archived.close()
                manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
                self._refresh_archived_database_binding(bundle, manifest)
                with self.assertRaisesRegex(ValueError, expected):
                    recovery.reconstruct_recovery_point_evidence(database_path=live_db, recovery_root=bundle.parent, recovery_point_id=point_id, actor="admin", rationale="qualification chain mutation", acknowledged=True, idempotency_key=f"qualification-chain-{index}", approved_root=bundle.parent.parent)

    def test_batch3b4b3a4c_joint_qualification_job_and_manifest_authority(self):
        def mutate_job_digests(conn, job_ids):
            conn.execute("UPDATE stage77_report_jobs SET qualification_digest=? WHERE id IN (?,?)", ("b" * 64, job_ids[0], job_ids[1]))

        def mutate_qualification_digest(conn, job_ids):
            conn.execute("UPDATE record_governed_report_qualifications SET qualification_digest=? WHERE id=4", ("c" * 64,))

        def remove_event(conn, job_ids):
            conn.execute("DELETE FROM record_governed_report_qualification_events WHERE qualification_id=4")

        def duplicate_event(conn, job_ids):
            row = conn.execute("SELECT qualification_id,report_id,report_version_id,event_type,actor,occurred_at,payload_json FROM record_governed_report_qualification_events WHERE qualification_id=4").fetchone()
            conn.execute("INSERT INTO record_governed_report_qualification_events(qualification_id,report_id,report_version_id,event_type,actor,occurred_at,idempotency_key,payload_json) VALUES(?,?,?,?,?,?,?,?)", (*row[:6], "joint-duplicate-event", row[6]))

        cases = [
            ("both_job_bindings", mutate_job_digests, "job_qualification_binding_mismatch"),
            ("qualification_digest", mutate_qualification_digest, "governed_report_qualification_digest_mismatch"),
            ("missing_final_event", remove_event, "governed_report_qualification_event_invalid"),
            ("duplicate_final_event", duplicate_event, "governed_report_qualification_event_invalid"),
        ]
        for index, (name, mutation, expected) in enumerate(cases):
            with self.subTest(case=name):
                bundle, live_db, point_id, job_ids = self._producer_modern_fixture(f"qualification-joint-{index}")
                archived = sqlite3.connect(bundle / "database.sqlite3")
                mutation(archived, job_ids)
                archived.commit()
                archived.close()
                manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
                self._refresh_archived_database_binding(bundle, manifest)
                for attempt in range(2):
                    with self.assertRaisesRegex(ValueError, expected):
                        recovery.reconstruct_recovery_point_evidence(database_path=live_db, recovery_root=bundle.parent, recovery_point_id=point_id, actor="admin", rationale="joint qualification mutation", acknowledged=True, idempotency_key=f"qualification-joint-{index}", approved_root=bundle.parent.parent)
                check = sqlite3.connect(live_db)
                self.assertEqual(check.execute("SELECT COUNT(*) FROM stage77_recovery_point_evidence").fetchone()[0], 0)
                self.assertEqual(check.execute("SELECT COUNT(*) FROM stage77_recovery_point_evidence_events").fetchone()[0], 0)
                check.close()

    def test_batch3b4b3a4c_consistent_live_qualification_rewrite_limit(self):
        bundle, live_db, point_id, job_ids = self._producer_modern_fixture("qualification-live-rewrite-limit")
        archived = sqlite3.connect(bundle / "database.sqlite3")
        payload = json.loads(archived.execute("SELECT qualification_payload_json FROM record_governed_report_qualifications WHERE id=4").fetchone()[0])
        payload["rationale"] = "post-capture internally consistent rewrite"
        digest = qualifications._payload_digest(payload)
        encoded = qualifications.canonical_json(payload)
        archived.execute("UPDATE record_governed_report_qualifications SET rationale=?,qualification_payload_json=?,qualification_digest=? WHERE id=4", (payload["rationale"], encoded, digest))
        archived.execute("UPDATE record_governed_report_qualification_events SET payload_json=? WHERE qualification_id=4", (encoded,))
        archived.execute("UPDATE stage77_report_jobs SET qualification_digest=? WHERE id IN (?,?)", (digest, job_ids[0], job_ids[1]))
        archived.commit()
        archived.close()
        manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
        self._refresh_archived_database_binding(bundle, manifest)
        result = recovery.reconstruct_recovery_point_evidence(database_path=live_db, recovery_root=bundle.parent, recovery_point_id=point_id, actor="admin", rationale="joint live rewrite limit", acknowledged=True, idempotency_key="qualification-live-rewrite-limit", approved_root=bundle.parent.parent)
        self.assertEqual(result["state"], "finalized")

    def test_batch3b4b3a4c_physical_storage_rewrite_keeps_qualification_evidence_canonical(self):
        bundle, _live_db, _point_id, _job_ids = self._producer_modern_fixture("qualification-physical-order")
        before = sqlite3.connect(bundle / "database.sqlite3")
        before.row_factory = sqlite3.Row
        before_digest = qualifications.state_snapshot(before)["digest"]
        before.execute("VACUUM")
        after_digest = qualifications.state_snapshot(before)["digest"]
        before.close()
        self.assertEqual(after_digest, before_digest)
        manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
        self._refresh_archived_database_binding(bundle, manifest)
        self.assertEqual(recovery.validate_recovery_bundle(bundle)["state"], "valid")

    def test_batch3b4b3a5_action_role_mutation_matrix(self):
        cases = [
            ("job1_retry_action", "UPDATE stage77_report_jobs SET governed_action=? WHERE id=?", (jobs.DIAGNOSTIC_RETRY_ACTION,), 0, "diagnostic_evidence_invalid"),
            ("job1_post_correction_action", "UPDATE stage77_report_jobs SET governed_action=? WHERE id=?", (jobs.POST_CORRECTION_ACTION,), 0, "diagnostic_evidence_invalid"),
            ("job1_unknown_action", "UPDATE stage77_report_jobs SET governed_action=? WHERE id=?", ("unknown_action",), 0, "diagnostic_evidence_invalid"),
            ("job1_blank_action", "UPDATE stage77_report_jobs SET governed_action=? WHERE id=?", ("",), 0, "diagnostic_evidence_invalid"),
            ("job2_generation_action", "UPDATE stage77_report_jobs SET governed_action=? WHERE id=?", ("enqueue_generation",), 1, "diagnostic_evidence_invalid"),
            ("job2_post_correction_action", "UPDATE stage77_report_jobs SET governed_action=? WHERE id=?", (jobs.POST_CORRECTION_ACTION,), 1, "diagnostic_evidence_invalid"),
            ("job2_unknown_action", "UPDATE stage77_report_jobs SET governed_action=? WHERE id=?", ("unknown_action",), 1, "diagnostic_evidence_invalid"),
            ("swapped_actions", "UPDATE stage77_report_jobs SET governed_action=? WHERE id=?", (jobs.DIAGNOSTIC_RETRY_ACTION,), 0, "diagnostic_evidence_invalid"),
            ("both_generation_actions", "UPDATE stage77_report_jobs SET governed_action='enqueue_generation'", (), 0, "diagnostic_evidence_invalid"),
            ("correct_action_missing_retry_link", "UPDATE stage77_report_jobs SET retry_of_job_id=NULL WHERE id=?", (), 1, "diagnostic_evidence_invalid"),
            ("self_retry_link", "UPDATE stage77_report_jobs SET retry_of_job_id=id WHERE id=?", (), 1, "retry_topology_invalid"),
        ]
        for index, (name, sql, values, target, expected) in enumerate(cases):
            with self.subTest(case=name):
                bundle, live_db, point_id, job_ids = self._producer_modern_fixture(f"action-role-{index}")
                archived = sqlite3.connect(bundle / "database.sqlite3")
                params = values + ((job_ids[target],) if "WHERE id=?" in sql else ())
                archived.execute(sql, params)
                if name == "swapped_actions":
                    archived.execute("UPDATE stage77_report_jobs SET governed_action='enqueue_generation' WHERE id=?", (job_ids[1],))
                archived.commit()
                archived.close()
                manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
                self._refresh_archived_database_binding(bundle, manifest)
                for attempt in range(2):
                    with self.assertRaisesRegex(ValueError, expected):
                        recovery.reconstruct_recovery_point_evidence(database_path=live_db, recovery_root=bundle.parent, recovery_point_id=point_id, actor="admin", rationale="action role mutation", acknowledged=True, idempotency_key=f"action-role-{index}", approved_root=bundle.parent.parent)
                check = sqlite3.connect(live_db)
                self.assertEqual(check.execute("SELECT COUNT(*) FROM stage77_recovery_point_evidence").fetchone()[0], 0)
                self.assertEqual(check.execute("SELECT COUNT(*) FROM stage77_recovery_point_evidence_events").fetchone()[0], 0)
                check.close()

    def test_batch3b4b3a5_null_action_is_schema_enforced(self):
        bundle, _live_db, _point_id, job_ids = self._producer_modern_fixture("action-null")
        archived = sqlite3.connect(bundle / "database.sqlite3")
        with self.assertRaises(sqlite3.IntegrityError):
            archived.execute("UPDATE stage77_report_jobs SET governed_action=NULL WHERE id=?", (job_ids[0],))
        archived.rollback()
        self.assertEqual(archived.execute("SELECT governed_action FROM stage77_report_jobs WHERE id=?", (job_ids[0],)).fetchone()[0], "enqueue_generation")
        archived.close()

    def test_batch3b4b3a6_cancellation_state_and_event_matrix(self):
        cases = [
            ("failed_with_request", "UPDATE stage77_report_jobs SET cancellation_requested_at='2026-01-01T00:00:00Z' WHERE id=?", "job_cancellation_evidence_invalid"),
            ("failed_with_cancel_event", "INSERT INTO stage77_report_job_events(job_id,event_type,resulting_state,actor,occurred_at,payload_json) VALUES(?, 'cancel_requested', 'failed_terminal', 'admin', '2026-01-01T00:00:00Z', '{}')", "job_cancellation_evidence_invalid"),
            ("malformed_request_time", "UPDATE stage77_report_jobs SET cancellation_requested_at='not-a-time' WHERE id=?", "job_cancellation_evidence_invalid"),
            ("request_after_terminal", "UPDATE stage77_report_jobs SET cancellation_requested_at='2099-01-01T00:00:00Z' WHERE id=?", "job_cancellation_evidence_invalid"),
            ("wrong_event_state", "UPDATE stage77_report_jobs SET state='cancelled',cancellation_requested_at='2026-01-01T00:00:00Z' WHERE id=?", "retry_topology_invalid"),
        ]
        for index, (name, sql, expected) in enumerate(cases):
            with self.subTest(case=name):
                bundle, live_db, point_id, job_ids = self._producer_modern_fixture(f"cancellation-{index}")
                archived = sqlite3.connect(bundle / "database.sqlite3")
                if sql.startswith("INSERT"):
                    archived.execute(sql, (job_ids[0],))
                else:
                    archived.execute(sql, (job_ids[0],))
                if name == "wrong_event_state":
                    archived.execute("INSERT INTO stage77_report_job_events(job_id,event_type,resulting_state,actor,occurred_at,payload_json) VALUES(?, 'cancel_requested', 'cancelled', 'admin', '2026-01-01T00:00:01Z', '{}')", (job_ids[0],))
                archived.commit()
                archived.close()
                manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
                self._refresh_archived_database_binding(bundle, manifest)
                for attempt in range(2):
                    with self.assertRaisesRegex(ValueError, expected):
                        recovery.reconstruct_recovery_point_evidence(database_path=live_db, recovery_root=bundle.parent, recovery_point_id=point_id, actor="admin", rationale="cancellation mutation", acknowledged=True, idempotency_key=f"cancellation-{index}", approved_root=bundle.parent.parent)
                check = sqlite3.connect(live_db)
                self.assertEqual(check.execute("SELECT COUNT(*) FROM stage77_recovery_point_evidence").fetchone()[0], 0)
                self.assertEqual(check.execute("SELECT COUNT(*) FROM stage77_recovery_point_evidence_events").fetchone()[0], 0)
                check.close()

    def test_batch3b4b3a6_producer_cancelled_and_schema_applicability(self):
        self._insert_unrelated_job(self.conn)
        job_id = self.conn.execute("SELECT id FROM stage77_report_jobs ORDER BY id LIMIT 1").fetchone()[0]
        self.conn.execute("UPDATE stage77_report_jobs SET state='cancelled',cancellation_requested_at='2026-01-01T00:00:00Z',terminal_at=NULL WHERE id=?", (job_id,))
        self.conn.execute("INSERT INTO stage77_report_job_events(job_id,event_type,resulting_state,actor,occurred_at,payload_json) VALUES(?, 'cancel_requested', 'cancelled', 'admin', '2026-01-01T00:00:01Z', '{}')", (job_id,))
        recovery._validate_archived_job_cancellation(self.conn, contract="current")
        recovery._validate_archived_job_cancellation(self.conn, contract="legacy")
        self.conn.execute("DROP TABLE stage77_report_job_events")
        with self.assertRaisesRegex(ValueError, "schema_incompatible"):
            recovery._validate_archived_job_cancellation(self.conn, contract="current")

    def test_batch3b4b3a7_terminal_metadata_and_event_matrix(self):
        cases = [
            ("failed_valid", None, None),
            ("successful_valid", "success_shape", None),
            ("failed_diagnostic_job1", None, None),
            ("failed_diagnostic_job2", "job2", None),
            ("idempotent_terminal_replay", None, None),
            ("conflicting_terminal_replay", "wrong_code", "job_terminal_evidence_invalid"),
            ("failed_event_missing", "delete_event", "schema_incompatible"),
            ("successful_event_missing", "success_missing_event", "retry_topology_invalid"),
            ("failed_event_duplicate", "duplicate_event", "diagnostic_evidence_mismatch"),
            ("successful_event_duplicate", "success_duplicate_event", "retry_topology_invalid"),
            ("two_terminal_event_shapes", "wrong_state", "schema_incompatible"),
            ("contradictory_later_terminal", "duplicate_wrong_code", "diagnostic_evidence_invalid"),
            ("failed_with_success_event", "wrong_state", "schema_incompatible"),
            ("success_with_failure_event", "success_failure_payload", "retry_topology_invalid"),
            ("nonterminal_with_terminal_event", "queued_with_event", "retry_topology_invalid"),
            ("terminal_timestamp_missing", "null_terminal_at", "job_terminal_evidence_invalid"),
            ("event_timestamp_mismatch", "early_event", "job_terminal_evidence_invalid"),
            ("terminal_phase_code_mismatch", "wrong_code", "job_terminal_evidence_invalid"),
            ("event_other_job", "event_other_job", "schema_incompatible"),
            ("malformed_terminal_payload", "malformed_payload", "diagnostic_evidence_invalid"),
        ]
        for index, (name, mutation, expected) in enumerate(cases):
            with self.subTest(case=name):
                bundle, live_db, point_id, job_ids = self._producer_modern_fixture(f"terminal-matrix-{index}")
                archived = sqlite3.connect(bundle / "database.sqlite3")
                archived.row_factory = sqlite3.Row
                job_id = job_ids[0]
                terminal = archived.execute("SELECT * FROM stage77_report_job_events WHERE job_id=? AND event_type='terminal' ORDER BY id LIMIT 1", (job_id,)).fetchone()
                if mutation is None:
                    if name == "failed_valid":
                        recovery._validate_archived_job_terminal_evidence(archived, contract="diagnostic_aware")
                    elif name == "job2":
                        job_id = job_ids[1]
                        recovery._validate_archived_job_terminal_evidence(archived, contract="diagnostic_aware")
                    else:
                        recovery._validate_archived_job_terminal_evidence(archived, contract="diagnostic_aware")
                    archived.close()
                    continue
                if mutation == "success_shape":
                    payload = recovery.canonical_json({"phase": "rendering", "code": "completed"})
                    archived.execute("UPDATE stage77_report_jobs SET state='succeeded',terminal_outcome='completed',failure_phase='rendering',failure_code='completed' WHERE id=?", (job_id,))
                    archived.execute("UPDATE stage77_report_job_events SET resulting_state='succeeded',payload_json=? WHERE id=?", (payload, terminal["id"]))
                elif mutation == "success_missing_event":
                    payload = recovery.canonical_json({"phase": "rendering", "code": "completed"})
                    archived.execute("UPDATE stage77_report_jobs SET state='succeeded',terminal_outcome='completed',failure_phase='rendering',failure_code='completed' WHERE id=?", (job_id,))
                    archived.execute("UPDATE stage77_report_job_events SET resulting_state='succeeded',payload_json=? WHERE id=?", (payload, terminal["id"]))
                    archived.execute("DELETE FROM stage77_report_job_events WHERE id=?", (terminal["id"],))
                elif mutation == "success_duplicate_event":
                    payload = recovery.canonical_json({"phase": "rendering", "code": "completed"})
                    archived.execute("UPDATE stage77_report_jobs SET state='succeeded',terminal_outcome='completed',failure_phase='rendering',failure_code='completed' WHERE id=?", (job_id,))
                    archived.execute("UPDATE stage77_report_job_events SET resulting_state='succeeded',payload_json=? WHERE id=?", (payload, terminal["id"]))
                    archived.execute("INSERT INTO stage77_report_job_events(job_id,event_type,resulting_state,actor,occurred_at,payload_json) SELECT job_id,event_type,resulting_state,actor,occurred_at,payload_json FROM stage77_report_job_events WHERE id=?", (terminal["id"],))
                elif mutation == "success_failure_payload":
                    archived.execute("UPDATE stage77_report_jobs SET state='succeeded',terminal_outcome='completed',failure_phase='rendering',failure_code='completed' WHERE id=?", (job_id,))
                    archived.execute("UPDATE stage77_report_job_events SET resulting_state='succeeded' WHERE id=?", (terminal["id"],))
                elif mutation == "delete_event":
                    archived.execute("DELETE FROM stage77_report_job_events WHERE id=?", (terminal["id"],))
                elif mutation == "duplicate_event":
                    archived.execute("INSERT INTO stage77_report_job_events(job_id,event_type,resulting_state,actor,occurred_at,payload_json) SELECT job_id,event_type,resulting_state,actor,occurred_at,payload_json FROM stage77_report_job_events WHERE id=?", (terminal["id"],))
                elif mutation == "duplicate_wrong_code":
                    archived.execute("UPDATE stage77_report_job_events SET payload_json=? WHERE id=?", (recovery.canonical_json({"phase": "revalidation", "code": "other"}), terminal["id"]))
                    archived.execute("INSERT INTO stage77_report_job_events(job_id,event_type,resulting_state,actor,occurred_at,payload_json) SELECT job_id,event_type,resulting_state,actor,occurred_at,payload_json FROM stage77_report_job_events WHERE id=?", (terminal["id"],))
                elif mutation == "wrong_state":
                    archived.execute("UPDATE stage77_report_job_events SET resulting_state='succeeded' WHERE id=?", (terminal["id"],))
                elif mutation == "queued_with_event":
                    archived.execute("UPDATE stage77_report_jobs SET state='queued' WHERE id=?", (job_id,))
                elif mutation == "null_terminal_at":
                    archived.execute("UPDATE stage77_report_jobs SET terminal_at=NULL WHERE id=?", (job_id,))
                elif mutation == "early_event":
                    archived.execute("UPDATE stage77_report_job_events SET occurred_at='2000-01-01T00:00:00Z' WHERE id=?", (terminal["id"],))
                elif mutation == "wrong_code":
                    archived.execute("UPDATE stage77_report_jobs SET terminal_outcome='other',failure_code='other' WHERE id=?", (job_id,))
                elif mutation == "event_other_job":
                    archived.execute("UPDATE stage77_report_job_events SET job_id=? WHERE id=?", (job_ids[1], terminal["id"]))
                elif mutation == "malformed_payload":
                    archived.execute("UPDATE stage77_report_job_events SET payload_json='not-json' WHERE id=?", (terminal["id"],))
                archived.commit(); archived.close()
                manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
                self._refresh_archived_database_binding(bundle, manifest)
                if expected is None:
                    continue
                for attempt in range(2):
                    with self.assertRaisesRegex(ValueError, expected):
                        recovery.reconstruct_recovery_point_evidence(database_path=live_db, recovery_root=bundle.parent, recovery_point_id=point_id, actor="admin", rationale="terminal matrix", acknowledged=True, idempotency_key=f"terminal-matrix-{index}", approved_root=bundle.parent.parent)
                check = sqlite3.connect(live_db)
                self.assertEqual(check.execute("SELECT COUNT(*) FROM stage77_recovery_point_evidence").fetchone()[0], 0)
                self.assertEqual(check.execute("SELECT COUNT(*) FROM stage77_recovery_point_evidence_events").fetchone()[0], 0)
                check.close()

    def test_batch3b4b3a3a1_producer_valid_format_profile_matrix(self):
        cases = [
            ("valid_canonical_formats", "formats", None, None),
            ("producer_caller_order_control", "formats", None, None),
            ("missing_format", "formats", ["docx", "html"], "job_rendering_binding_mismatch"),
            ("extra_recognized_format", "formats", ["docx", "html", "pdf", "txt"], "job_rendering_binding_mismatch"),
            ("unknown_format", "formats", ["docx", "html", "txt"], "job_rendering_binding_mismatch"),
            ("duplicate_format", "formats", ["docx", "html", "html", "pdf"], "job_rendering_binding_mismatch"),
            ("empty_format_list", "formats", [], "job_rendering_binding_mismatch"),
            ("null_format_schema_enforced", "null_formats", None, "sqlite_error"),
            ("malformed_format_json", "malformed_formats", None, "job_rendering_binding_mismatch"),
            ("format_drift", "formats", ["docx", "html"], "job_rendering_binding_mismatch"),
            ("valid_profile", "profile", None, None),
            ("recognized_profile_drift", "profile", "external", "job_rendering_binding_mismatch"),
            ("unknown_profile", "profile", "unknown-profile", "job_rendering_binding_mismatch"),
            ("blank_profile", "profile", "", "job_rendering_binding_mismatch"),
            ("null_profile_schema_enforced", "null_profile", None, "sqlite_error"),
            ("profile_drift", "profile", "different-profile", "job_rendering_binding_mismatch"),
        ]
        for index, (name, kind, value, expected) in enumerate(cases):
            with self.subTest(case=name):
                bundle, live_db, point_id, job_ids = self._producer_modern_fixture(f"modern-config-{index}", caller_format_order=name == "producer_caller_order_control")
                manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
                if name == "producer_caller_order_control":
                    ordered = sqlite3.connect(bundle / "database.sqlite3")
                    try:
                        stored_formats = ordered.execute("SELECT requested_formats_json FROM record_governed_report_versions LIMIT 1").fetchone()[0]
                    finally:
                        ordered.close()
                    self.assertEqual(json.loads(stored_formats), ["docx", "html", "pdf"])
                    continue
                archived = sqlite3.connect(bundle / "database.sqlite3")
                try:
                    if kind == "formats" and value is not None:
                        archived.execute("UPDATE stage77_report_jobs SET requested_formats_json=? WHERE id=?", (reports.canonical_json(value), job_ids[0]))
                    elif kind == "malformed_formats":
                        archived.execute("UPDATE stage77_report_jobs SET requested_formats_json='not-json' WHERE id=?", (job_ids[0],))
                    elif kind == "null_formats":
                        with self.assertRaises(sqlite3.IntegrityError):
                            archived.execute("UPDATE stage77_report_jobs SET requested_formats_json=NULL WHERE id=?", (job_ids[0],))
                    elif kind == "profile" and expected is not None:
                        archived.execute("UPDATE stage77_report_jobs SET rendering_profile=? WHERE id=?", (value, job_ids[0]))
                    elif kind == "null_profile":
                        with self.assertRaises(sqlite3.IntegrityError):
                            archived.execute("UPDATE stage77_report_jobs SET rendering_profile=NULL WHERE id=?", (job_ids[0],))
                    archived.commit()
                finally:
                    archived.close()
                self._refresh_archived_database_binding(bundle, manifest)
                if expected is None:
                    recovery.validate_recovery_bundle(bundle)
                elif expected != "sqlite_error":
                    with self.assertRaisesRegex(ValueError, expected):
                        recovery.reconstruct_recovery_point_evidence(database_path=live_db, recovery_root=bundle.parent, recovery_point_id=point_id, actor="admin", rationale="configuration mutation", acknowledged=True, idempotency_key=f"modern-config-{index}", approved_root=bundle.parent.parent)
                    with self.assertRaisesRegex(ValueError, expected):
                        recovery.reconstruct_recovery_point_evidence(database_path=live_db, recovery_root=bundle.parent, recovery_point_id=point_id, actor="admin", rationale="configuration mutation", acknowledged=True, idempotency_key=f"modern-config-{index}", approved_root=bundle.parent.parent)
                    check = sqlite3.connect(live_db)
                    self.assertEqual(check.execute("SELECT COUNT(*) FROM stage77_recovery_point_evidence").fetchone()[0], 0)
                    self.assertEqual(check.execute("SELECT COUNT(*) FROM stage77_recovery_point_evidence_events").fetchone()[0], 0)
                    check.close()

    def test_batch3b4b3a3a1_job_version_configuration_parity(self):
        cases = [
            ("job1_format_drift", lambda c, ids: c.execute("UPDATE stage77_report_jobs SET requested_formats_json='[\"docx\",\"html\"]' WHERE id=?", (ids[0],))),
            ("job2_format_drift", lambda c, ids: c.execute("UPDATE stage77_report_jobs SET requested_formats_json='[\"docx\",\"html\"]' WHERE id=?", (ids[1],))),
            ("job_format_parity", lambda c, ids: c.execute("UPDATE stage77_report_jobs SET requested_formats_json='[\"docx\",\"html\"]' WHERE id IN (?,?)", ids)),
            ("job1_profile_drift", lambda c, ids: c.execute("UPDATE stage77_report_jobs SET rendering_profile='other' WHERE id=?", (ids[0],))),
            ("job2_profile_drift", lambda c, ids: c.execute("UPDATE stage77_report_jobs SET rendering_profile='other' WHERE id=?", (ids[1],))),
            ("job_profile_parity", lambda c, ids: c.execute("UPDATE stage77_report_jobs SET rendering_profile='other' WHERE id IN (?,?)", ids)),
            ("both_snapshots_drift", lambda c, ids: c.execute("UPDATE stage77_report_jobs SET rendering_profile='other',requested_formats_json='[\"docx\",\"html\"]' WHERE id IN (?,?)", ids)),
            ("version_format_drift", lambda c, ids: c.execute("UPDATE record_governed_report_versions SET requested_formats_json='[\"docx\",\"html\"]'")),
            ("version_profile_drift", lambda c, ids: c.execute("UPDATE record_governed_report_versions SET rendering_profile='other'")),
        ]
        for index, (name, mutation) in enumerate(cases):
            with self.subTest(case=name):
                bundle, live_db, point_id, job_ids = self._producer_modern_fixture(f"modern-parity-{index}")
                archived = sqlite3.connect(bundle / "database.sqlite3")
                mutation(archived, job_ids); archived.commit(); archived.close()
                manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
                self._refresh_archived_database_binding(bundle, manifest)
                for attempt in range(2):
                    with self.assertRaisesRegex(ValueError, "job_rendering_binding_mismatch"):
                        recovery.reconstruct_recovery_point_evidence(database_path=live_db, recovery_root=bundle.parent, recovery_point_id=point_id, actor="admin", rationale="parity mutation", acknowledged=True, idempotency_key=f"modern-parity-{index}", approved_root=bundle.parent.parent)
                check = sqlite3.connect(live_db)
                self.assertEqual(check.execute("SELECT COUNT(*) FROM stage77_recovery_point_evidence").fetchone()[0], 0)
                self.assertEqual(check.execute("SELECT COUNT(*) FROM stage77_recovery_point_evidence_events").fetchone()[0], 0)
                check.close()

    def test_batch3b4b3a3a1_positive_reconstruction_replay(self):
        bundle, live_db, point_id, job_ids = self._producer_modern_fixture("modern-positive-replay")
        first = recovery.reconstruct_recovery_point_evidence(database_path=live_db, recovery_root=bundle.parent, recovery_point_id=point_id, actor="admin", rationale="producer-valid configuration", acknowledged=True, idempotency_key="modern-positive", approved_root=bundle.parent.parent)
        replay = recovery.reconstruct_recovery_point_evidence(database_path=live_db, recovery_root=bundle.parent, recovery_point_id=point_id, actor="admin", rationale="producer-valid configuration", acknowledged=True, idempotency_key="modern-positive", approved_root=bundle.parent.parent)
        self.assertEqual(first["id"], replay["id"])
        check = sqlite3.connect(live_db)
        self.assertEqual(check.execute("SELECT COUNT(*) FROM stage77_recovery_point_evidence").fetchone()[0], 1)
        self.assertEqual(check.execute("SELECT COUNT(*) FROM stage77_recovery_point_evidence_events").fetchone()[0], 1)
        check.close()

    def test_batch3b4b3a3b_template_and_publication_engine_matrix(self):
        cases = [
            ("valid_template", "template_version", "cde-internal-v1", None),
            ("wrong_template", "template_version", "cde-historical-v0", "job_rendering_binding_mismatch"),
            ("blank_template", "template_version", "", "job_rendering_binding_mismatch"),
            ("valid_publication_engine", "publication_engine_version", "2.0.0", None),
            ("wrong_publication_engine", "publication_engine_version", "1.9.0", "job_rendering_binding_mismatch"),
            ("blank_publication_engine", "publication_engine_version", "", "job_rendering_binding_mismatch"),
        ]
        for index, (name, column, value, expected) in enumerate(cases):
            with self.subTest(case=name):
                bundle, live_db, point_id, job_ids = self._producer_modern_fixture(f"modern-version-{index}")
                archived = sqlite3.connect(bundle / "database.sqlite3")
                archived.execute(f"UPDATE stage77_report_jobs SET {column}=? WHERE id=?", (value, job_ids[0]))
                archived.commit()
                archived.close()
                manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
                self._refresh_archived_database_binding(bundle, manifest)
                if expected is None:
                    recovery.validate_recovery_bundle(bundle)
                else:
                    with self.assertRaisesRegex(ValueError, expected):
                        recovery.reconstruct_recovery_point_evidence(database_path=live_db, recovery_root=bundle.parent, recovery_point_id=point_id, actor="admin", rationale="version mutation", acknowledged=True, idempotency_key=f"modern-version-{index}", approved_root=bundle.parent.parent)

    def test_batch3b4b3a3b_retry_version_parity(self):
        cases = [
            ("job1_template", "template_version", 0),
            ("job2_template", "template_version", 1),
            ("both_template", "template_version", 2),
            ("job1_engine", "publication_engine_version", 0),
            ("job2_engine", "publication_engine_version", 1),
            ("both_engine", "publication_engine_version", 2),
            ("version_template", "version_template", 0),
            ("version_engine", "version_engine", 0),
        ]
        for index, (name, kind, target) in enumerate(cases):
            with self.subTest(case=name):
                bundle, live_db, point_id, job_ids = self._producer_modern_fixture(f"modern-version-parity-{index}")
                archived = sqlite3.connect(bundle / "database.sqlite3")
                if kind == "version_template":
                    archived.execute("UPDATE record_governed_report_versions SET template_version='cde-historical-v0'")
                elif kind == "version_engine":
                    archived.execute("UPDATE record_governed_report_versions SET publication_engine_version='1.9.0'")
                else:
                    column = "template_version" if "template" in kind else "publication_engine_version"
                    if target == 2:
                        archived.execute(f"UPDATE stage77_report_jobs SET {column}='cde-historical-v0' WHERE id IN (?,?)" if column == "template_version" else f"UPDATE stage77_report_jobs SET {column}='1.9.0' WHERE id IN (?,?)", (job_ids[0], job_ids[1]))
                    else:
                        archived.execute(f"UPDATE stage77_report_jobs SET {column}=? WHERE id=?", ("cde-historical-v0" if column == "template_version" else "1.9.0", job_ids[target]))
                archived.commit()
                archived.close()
                manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
                self._refresh_archived_database_binding(bundle, manifest)
                with self.assertRaisesRegex(ValueError, "job_rendering_binding_mismatch"):
                    recovery.reconstruct_recovery_point_evidence(database_path=live_db, recovery_root=bundle.parent, recovery_point_id=point_id, actor="admin", rationale="version parity mutation", acknowledged=True, idempotency_key=f"modern-version-parity-{index}", approved_root=bundle.parent.parent)

    def test_batch3b4b3a3b_historical_versions_are_archived_authority(self):
        cases = [
            ("historical_template", {"template_version": "cde-internal-v0"}),
            ("historical_publication_engine", {"publication_engine_version": "1.9.0"}),
        ]
        for index, (name, options) in enumerate(cases):
            with self.subTest(case=name):
                bundle, _live_db, _point_id, _job_ids = self._producer_modern_fixture(f"modern-historical-{index}", **options)
                archived = sqlite3.connect(bundle / "database.sqlite3")
                version = archived.execute("SELECT template_version,publication_engine_version FROM record_governed_report_versions").fetchone()
                job = archived.execute("SELECT template_version,publication_engine_version FROM stage77_report_jobs ORDER BY id LIMIT 1").fetchone()
                archived.close()
                self.assertEqual(tuple(version), tuple(job))
                self.assertEqual(recovery.validate_recovery_bundle(bundle)["state"], "valid")

    def test_batch3b4b3a3c_specification_identity_digest_matrix(self):
        cases = [
            ("exact_identity_and_digest", "valid", None),
            ("wrong_identity_fk", "job_version_id", "foreign_key_enforced"),
            ("job1_digest", "job_digest", "job_specification_binding_mismatch"),
            ("job2_digest", "job2_digest", "job_specification_binding_mismatch"),
            ("blank_digest", "blank_digest", "job_specification_binding_mismatch"),
            ("malformed_digest_length", "bad_digest", "job_specification_binding_mismatch"),
            ("malformed_digest_hex", "bad_digest_hex", "job_specification_binding_mismatch"),
            ("malformed_digest_case", "uppercase_digest", "job_specification_binding_mismatch"),
            ("malformed_digest_whitespace", "whitespace_digest", "job_specification_binding_mismatch"),
            ("altered_content_recomputed_digest", "version_content_digest", "job_specification_binding_mismatch"),
            ("altered_content_stale_digest", "version_content_stale", "specification_digest_mismatch"),
            ("canonical_equivalent_json", "canonical_equivalent", None),
        ]
        for index, (name, kind, expected) in enumerate(cases):
            with self.subTest(case=name):
                bundle, live_db, point_id, job_ids = self._producer_modern_fixture(f"modern-spec-{index}")
                archived = sqlite3.connect(bundle / "database.sqlite3")
                archived.execute("PRAGMA foreign_keys=ON")
                version = archived.execute("SELECT specification_json,specification_digest FROM record_governed_report_versions LIMIT 1").fetchone()
                original_digest = str(version[1])
                if kind == "job_version_id":
                    with self.assertRaises(sqlite3.IntegrityError):
                        archived.execute("UPDATE stage77_report_jobs SET report_version_id=999999 WHERE id=?", (job_ids[0],))
                    archived.rollback()
                elif kind == "job_digest":
                    archived.execute("UPDATE stage77_report_jobs SET specification_digest=? WHERE id=?", ("b" * 64, job_ids[0]))
                elif kind == "job2_digest":
                    archived.execute("UPDATE stage77_report_jobs SET specification_digest=? WHERE id=?", ("b" * 64, job_ids[1]))
                elif kind == "blank_digest":
                    archived.execute("UPDATE stage77_report_jobs SET specification_digest='' WHERE id=?", (job_ids[0],))
                elif kind == "bad_digest":
                    archived.execute("UPDATE stage77_report_jobs SET specification_digest='abc' WHERE id=?", (job_ids[0],))
                elif kind == "bad_digest_hex":
                    archived.execute("UPDATE stage77_report_jobs SET specification_digest=? WHERE id=?", ("g" * 64, job_ids[0]))
                elif kind == "uppercase_digest":
                    archived.execute("UPDATE stage77_report_jobs SET specification_digest=? WHERE id=?", (original_digest.upper(), job_ids[0]))
                elif kind == "whitespace_digest":
                    archived.execute("UPDATE stage77_report_jobs SET specification_digest=? WHERE id=?", (f" {original_digest} ", job_ids[0]))
                elif kind in {"version_content_digest", "version_content_stale", "canonical_equivalent"}:
                    specification = json.loads(version[0])
                    if kind == "version_content_digest":
                        specification["purpose"] = "Altered governed purpose"
                        altered = recovery.canonical_json(specification)
                        archived.execute("UPDATE record_governed_report_versions SET specification_json=?,specification_digest=?", (altered, recovery.digest_bytes(altered.encode("utf-8"))))
                    elif kind == "version_content_stale":
                        specification["purpose"] = "Altered governed purpose"
                        archived.execute("UPDATE record_governed_report_versions SET specification_json=?", (json.dumps(specification, indent=2),))
                    else:
                        reordered = {key: specification[key] for key in reversed(list(specification))}
                        archived.execute("UPDATE record_governed_report_versions SET specification_json=?", (json.dumps(reordered, indent=2, ensure_ascii=False),))
                archived.commit()
                archived.close()
                if kind == "job_version_id":
                    continue
                manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
                self._refresh_archived_database_binding(bundle, manifest)
                if expected is None:
                    self.assertEqual(recovery.reconstruct_recovery_point_evidence(database_path=live_db, recovery_root=bundle.parent, recovery_point_id=point_id, actor="admin", rationale="specification control", acknowledged=True, idempotency_key=f"modern-spec-{index}", approved_root=bundle.parent.parent)["state"], "finalized")
                else:
                    with self.assertRaisesRegex(ValueError, expected):
                        recovery.reconstruct_recovery_point_evidence(database_path=live_db, recovery_root=bundle.parent, recovery_point_id=point_id, actor="admin", rationale="specification mutation", acknowledged=True, idempotency_key=f"modern-spec-{index}", approved_root=bundle.parent.parent)

    def test_batch3b4b3a3c_schema_and_zero_job_controls(self):
        self.assertEqual(recovery.validate_recovery_bundle(self._bundle())["state"], "valid")
        bundle, live_db, point_id = self._historical_reconstruction_fixture(post_correction=True)
        self.assertEqual(recovery.validate_recovery_bundle(bundle)["state"], "valid")
        self.assertEqual(recovery.reconstruct_recovery_point_evidence(database_path=live_db, recovery_root=bundle.parent, recovery_point_id=point_id, actor="admin", rationale="post correction zero job", acknowledged=True, idempotency_key="post-correction-zero-job", approved_root=bundle.parent.parent)["state"], "finalized")

    def test_batch3b4b3a3c_joint_digest_count_and_schema_boundaries(self):
        cases = [
            ("both_job_digests", "UPDATE stage77_report_jobs SET specification_digest='b' || printf('%063d', 0)", "job_specification_binding_mismatch"),
            ("version_digest", "UPDATE record_governed_report_versions SET specification_digest='b' || printf('%063d', 0)", "job_specification_binding_mismatch"),
            ("partial_job_schema", "ALTER TABLE stage77_report_jobs DROP COLUMN template_version", "schema_incompatible"),
            ("mixed_version_schema", "ALTER TABLE record_governed_report_versions DROP COLUMN template_version", "schema_incompatible"),
            ("accurate_counts_invalid_digest", "UPDATE stage77_report_jobs SET specification_digest='b' || printf('%063d', 0)", "job_specification_binding_mismatch"),
        ]
        for index, (name, sql, expected) in enumerate(cases):
            with self.subTest(case=name):
                bundle, live_db, point_id, job_ids = self._producer_modern_fixture(f"modern-spec-boundary-{index}")
                archived = sqlite3.connect(bundle / "database.sqlite3")
                archived.execute("PRAGMA foreign_keys=ON")
                archived.execute(sql)
                archived.commit()
                archived.close()
                manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
                self._refresh_archived_database_binding(bundle, manifest)
                with self.assertRaisesRegex(ValueError, expected):
                    recovery.reconstruct_recovery_point_evidence(database_path=live_db, recovery_root=bundle.parent, recovery_point_id=point_id, actor="admin", rationale="specification boundary", acknowledged=True, idempotency_key=f"modern-spec-boundary-{index}", approved_root=bundle.parent.parent)

    def test_batch3b4b3a4_qualification_binding_core_controls(self):
        cases = [("job1", 0), ("job2", 1), ("both", None)]
        for index, (name, target) in enumerate(cases):
            with self.subTest(case=name):
                bundle, live_db, point_id, job_ids = self._producer_modern_fixture(f"modern-qualification-core-{index}")
                archived = sqlite3.connect(bundle / "database.sqlite3")
                if target is None:
                    archived.execute("UPDATE stage77_report_jobs SET qualification_digest='b' || printf('%063d', 0)")
                else:
                    archived.execute("UPDATE stage77_report_jobs SET qualification_digest='b' || printf('%063d', 0) WHERE id=?", (job_ids[target],))
                archived.commit()
                archived.close()
                manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
                self._refresh_archived_database_binding(bundle, manifest)
                with self.assertRaisesRegex(ValueError, "job_qualification_binding_mismatch"):
                    recovery.reconstruct_recovery_point_evidence(database_path=live_db, recovery_root=bundle.parent, recovery_point_id=point_id, actor="admin", rationale="qualification binding", acknowledged=True, idempotency_key=f"modern-qualification-core-{index}", approved_root=bundle.parent.parent)

    def test_batch3b4b3a4a1_identity_and_schema_group_matrix(self):
        cases = [
            ("job1_exact", None, None),
            ("job2_exact", None, None),
            ("job_parity", None, None),
            ("job1_unknown_identity", "UPDATE stage77_report_jobs SET qualification_id=999999 WHERE id=?", "foreign_key_check_failed"),
            ("job2_unknown_identity", "UPDATE stage77_report_jobs SET qualification_id=999999 WHERE id=?", "foreign_key_check_failed"),
            ("job1_blank_identity", "UPDATE stage77_report_jobs SET qualification_id='' WHERE id=?", "foreign_key_check_failed"),
            ("job2_blank_identity", "UPDATE stage77_report_jobs SET qualification_id='' WHERE id=?", "foreign_key_check_failed"),
            ("job1_null_identity", "UPDATE stage77_report_jobs SET qualification_id=NULL WHERE id=?", "job_qualification_binding_mismatch"),
            ("job2_null_identity", "UPDATE stage77_report_jobs SET qualification_id=NULL WHERE id=?", "job_qualification_binding_mismatch"),
            ("job1_identity_original_digest", "UPDATE stage77_report_jobs SET qualification_id=999999 WHERE id=?", "foreign_key_check_failed"),
            ("job2_identity_unrelated_digest", "UPDATE stage77_report_jobs SET qualification_id=999999,qualification_digest='b' || printf('%063d', 0) WHERE id=?", "foreign_key_check_failed"),
        ]
        for index, (name, sql, expected) in enumerate(cases):
            with self.subTest(case=name):
                if expected is None:
                    bundle, _live_db, _point_id, _job_ids = self._producer_modern_fixture(f"qualification-positive-{index}")
                    self.assertEqual(recovery.validate_recovery_bundle(bundle)["state"], "valid")
                    continue
                bundle, live_db, point_id, job_ids = self._producer_modern_fixture(f"qualification-identity-{index}")
                archived = sqlite3.connect(bundle / "database.sqlite3")
                archived.execute("PRAGMA foreign_keys=ON")
                target = job_ids[0] if "job1" in name else job_ids[1]
                try:
                    archived.execute(sql, (target,))
                    archived.commit()
                except sqlite3.IntegrityError:
                    archived.rollback()
                    self.assertEqual(expected, "foreign_key_check_failed")
                finally:
                    archived.close()
                if expected == "foreign_key_check_failed":
                    continue
                manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
                self._refresh_archived_database_binding(bundle, manifest)
                with self.assertRaisesRegex(ValueError, expected):
                    recovery.reconstruct_recovery_point_evidence(database_path=live_db, recovery_root=bundle.parent, recovery_point_id=point_id, actor="admin", rationale="qualification identity", acknowledged=True, idempotency_key=f"qualification-identity-{index}", approved_root=bundle.parent.parent)

    def test_batch3b4b3a4a1_schema_controls_and_zero_job_binding(self):
        self.assertEqual(recovery.validate_recovery_bundle(self._bundle())["state"], "valid")
        bundle, live_db, point_id = self._historical_reconstruction_fixture(post_correction=True)
        self.assertEqual(recovery.validate_recovery_bundle(bundle)["state"], "valid")
        self.assertEqual(recovery.reconstruct_recovery_point_evidence(database_path=live_db, recovery_root=bundle.parent, recovery_point_id=point_id, actor="admin", rationale="zero job qualification control", acknowledged=True, idempotency_key="qualification-zero-job", approved_root=bundle.parent.parent)["state"], "finalized")
        for index, column in enumerate(("qualification_id", "qualification_digest")):
            with self.subTest(schema="partial", column=column):
                modern, live_modern, modern_id, _job_ids = self._producer_modern_fixture(f"qualification-partial-{index}")
                archived = sqlite3.connect(modern / "database.sqlite3")
                archived.execute(f"ALTER TABLE stage77_report_jobs DROP COLUMN {column}")
                archived.commit()
                archived.close()
                manifest = json.loads((modern / "manifest.json").read_text(encoding="utf-8"))
                self._refresh_archived_database_binding(modern, manifest)
                with self.assertRaisesRegex(ValueError, "schema_incompatible"):
                    recovery.reconstruct_recovery_point_evidence(database_path=live_modern, recovery_root=modern.parent, recovery_point_id=modern_id, actor="admin", rationale="partial qualification schema", acknowledged=True, idempotency_key=f"qualification-partial-{index}", approved_root=modern.parent.parent)

    def _restore(self, bundle, database_target, artifact_target, restore_root=None):
        root = restore_root or self.root / "restore"
        root.mkdir(exist_ok=True)
        return recovery.restore_recovery_point(bundle_path=bundle, restore_root=root, database_target=database_target, artifact_root_target=artifact_target, live_database=self.db, live_artifact_root=self.artifacts, live_recovery_root=self.recovery_root, actor="admin", governed_action="restore", approved_root=self.root)

    def test_post_correction_schema_selects_fourth_contract_even_when_empty(self):
        jobs.ensure_post_correction_tables(self.conn)
        contract, _evidence, _evidence_digest, _links, _links_digest = recovery._database_contract(self.conn)
        self.assertEqual(contract, "post_correction_aware")
        self.conn.execute("DROP TABLE stage77_post_correction_execution_links")
        with self.assertRaisesRegex(ValueError, "post_correction_schema_incompatible"):
            recovery._database_contract(self.conn)

    def _add_diagnostic_evidence(self, *, linked_successor=False):
        from api import governed_report_diagnostics as diagnostics
        self.conn.executescript("""
        CREATE TABLE record_governed_report_generation_attempts (
          id INTEGER PRIMARY KEY AUTOINCREMENT, version_id INTEGER NOT NULL,
          requested_formats_json TEXT NOT NULL, actor TEXT NOT NULL, actor_role TEXT NOT NULL,
          requested_at TEXT NOT NULL, result TEXT NOT NULL, diagnostics_json TEXT NOT NULL,
          request_payload_json TEXT NOT NULL, idempotency_key TEXT NOT NULL UNIQUE
        );
        """)
        diagnostic = jobs.make_diagnostic(phase="rendering", operation="renderer_invocation", checkpoint="entered", code=jobs.DIAGNOSTIC_RETRY_FAILURE_CODE, format_category="multiple")
        attempt_raw = recovery.canonical_json([diagnostic])
        terminal_raw = recovery.canonical_json({"phase": "rendering", "operation": "renderer_invocation", "checkpoint": "entered", "code": jobs.DIAGNOSTIC_RETRY_FAILURE_CODE, "diagnostic": diagnostic, **diagnostic})
        self.conn.execute(
            "INSERT INTO record_governed_report_generation_attempts (version_id,requested_formats_json,actor,actor_role,requested_at,result,diagnostics_json,request_payload_json,idempotency_key) VALUES(?,?,?,?,?,?,?,?,?)",
            (11, '["docx","html","pdf"]', jobs.WORKER_IDENTITY, "system_worker", "2026-01-01T00:00:00Z", "validation_failed", attempt_raw, "{}", "stage77-job-1"),
        )
        self.conn.execute(
            "INSERT INTO stage77_report_jobs (report_id,report_version_id,specification_digest,requested_formats_json,rendering_profile,template_version,publication_engine_version,requesting_actor,governed_action,requested_at,state,attempt_count,max_attempts,next_eligible_at,idempotency_key,retry_of_job_id,maintenance_epoch,schema_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (7, 11, "a" * 64, '["docx","html","pdf"]', "internal", "cde-internal-v1", "2.0.0", "nick", "enqueue_generation", "2026-01-01T00:00:00Z", "failed_terminal", 1, 3, "2026-01-01T00:00:00Z", "stage77-job-1", None, 0, jobs.JOB_SCHEMA_VERSION),
        )
        job_id = self.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        terminal_raw = terminal_raw.replace('"code":"governed_report_renderer_failed"', '"code":"governed_report_renderer_failed"')
        self.conn.execute(
            "INSERT INTO stage77_report_job_events (job_id,event_type,resulting_state,actor,occurred_at,payload_json) VALUES(?,?,?,?,?,?)",
            (job_id, "terminal", "failed_terminal", jobs.WORKER_IDENTITY, "2026-01-01T00:00:01Z", terminal_raw),
        )
        if linked_successor:
            self.conn.execute(
                "INSERT INTO stage77_report_jobs (report_id,report_version_id,specification_digest,requested_formats_json,rendering_profile,template_version,publication_engine_version,requesting_actor,governed_action,requested_at,state,attempt_count,max_attempts,next_eligible_at,idempotency_key,retry_of_job_id,maintenance_epoch,schema_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (7, 11, "a" * 64, '["docx","html","pdf"]', "internal", "cde-internal-v1", "2.0.0", "nick", "authorize_diagnostic_retry", "2026-01-01T00:00:02Z", "queued", 0, 3, "2026-01-01T00:00:02Z", "stage77-diagnostic-retry-1", job_id, 0, jobs.JOB_SCHEMA_VERSION),
            )

    def test_diagnostic_aware_manifest_binds_evidence_and_retry_topology(self):
        self._add_diagnostic_evidence(linked_successor=True)
        result = recovery.capture_recovery_point(database_path=self.db, artifact_root=self.artifacts, recovery_root=self.recovery_root, approved_root=self.root, actor="admin", governed_action="capture")
        bundle = self.recovery_root / f"recovery-{result['recovery_point_id']}"
        manifest = json.loads((bundle / "manifest.json").read_text())
        self.assertEqual(recovery._manifest_contract(manifest), "diagnostic_aware")
        self.assertEqual(manifest["diagnostic_contract_version"], "stage77.diagnostic_aware.v1")
        self.assertEqual(manifest["diagnostic_evidence_count"], 1)
        self.assertEqual(manifest["retry_link_count"], 1)
        self.assertEqual(recovery.validate_recovery_bundle(bundle)["manifest_digest"], result["manifest_digest"])
        exports = self.root / "exports"
        exports.mkdir()
        recovery.export_recovery_bundle(bundle_path=bundle, output_archive=exports / "point4.tar", receipt_path=exports / "point4.json", reason="diagnostic-aware pre-retry state")
        self.assertEqual(recovery.validate_export_archive(exports / "point4.tar", exports / "point4.json")["state"], "valid")

    def test_diagnostic_aware_manifest_binds_legacy_and_transitional_evidence(self):
        from api import governed_report_diagnostics as diagnostics
        self._add_diagnostic_evidence(linked_successor=True)
        transitional = diagnostics.TRANSITIONAL_DIAGNOSTIC
        attempt_raw = recovery.canonical_json([transitional])
        terminal_raw = recovery.canonical_json({
            "phase": "rendering",
            "code": "governed_report_renderer_failed",
            "diagnostic": transitional,
            **transitional,
        })
        self.conn.execute(
            "INSERT INTO record_governed_report_generation_attempts (version_id,requested_formats_json,actor,actor_role,requested_at,result,diagnostics_json,request_payload_json,idempotency_key) VALUES(?,?,?,?,?,?,?,?,?)",
            (11, '["docx","html","pdf"]', jobs.WORKER_IDENTITY, "system_worker", "2026-01-01T00:00:02Z", "validation_failed", attempt_raw, "{}", "stage77-job-2"),
        )
        predecessor = self.conn.execute("SELECT id FROM stage77_report_jobs WHERE retry_of_job_id IS NULL").fetchone()[0]
        successor = self.conn.execute("SELECT id FROM stage77_report_jobs WHERE retry_of_job_id=?", (predecessor,)).fetchone()[0]
        self.conn.execute("UPDATE stage77_report_jobs SET state='failed_terminal',attempt_count=1,failure_phase='rendering',failure_code='governed_report_renderer_failed' WHERE id=?", (successor,))
        self.conn.execute(
            "INSERT INTO stage77_report_job_events (job_id,event_type,resulting_state,actor,occurred_at,payload_json) VALUES(?,?,?,?,?,?)",
            (successor, "terminal", "failed_terminal", jobs.WORKER_IDENTITY, "2026-01-01T00:00:03Z", terminal_raw),
        )
        self.conn.commit()
        result = recovery.capture_recovery_point(database_path=self.db, artifact_root=self.artifacts, recovery_root=self.recovery_root, approved_root=self.root, actor="admin", governed_action="capture")
        bundle = self.recovery_root / f"recovery-{result['recovery_point_id']}"
        manifest = json.loads((bundle / "manifest.json").read_text())
        self.assertEqual(manifest["diagnostic_evidence_count"], 2)
        self.assertEqual([item["diagnostic_contract_version"] for item in manifest["diagnostic_evidence"]], [diagnostics.CURRENT_DIAGNOSTIC_CONTRACT, diagnostics.TRANSITIONAL_DIAGNOSTIC_CONTRACT])
        self.assertEqual(recovery.validate_recovery_bundle(bundle)["manifest_digest"], result["manifest_digest"])

    def test_diagnostic_database_rejects_older_manifest_shape(self):
        self._add_diagnostic_evidence()
        result = recovery.capture_recovery_point(database_path=self.db, artifact_root=self.artifacts, recovery_root=self.recovery_root, approved_root=self.root, actor="admin", governed_action="capture")
        bundle = self.recovery_root / f"recovery-{result['recovery_point_id']}"
        manifest = json.loads((bundle / "manifest.json").read_text())
        for key in ("diagnostic_contract_version", "diagnostic_evidence", "diagnostic_evidence_count", "diagnostic_evidence_state_digest", "retry_link_count", "retry_link_state_digest"):
            manifest.pop(key)
        raw = recovery.canonical_json(manifest).encode()
        (bundle / "manifest.json").write_bytes(raw)
        (bundle / "manifest.sha256").write_text(recovery.digest_bytes(raw) + "\n")
        with self.assertRaisesRegex(ValueError, "schema_incompatible"):
            recovery.validate_recovery_bundle(bundle)

    def test_retry_topology_rejects_retry_of_retry_even_without_manifest_trust(self):
        self._add_diagnostic_evidence(linked_successor=True)
        predecessor = 1
        self.conn.execute(
            "INSERT INTO stage77_report_jobs (report_id,report_version_id,specification_digest,requested_formats_json,rendering_profile,template_version,publication_engine_version,requesting_actor,governed_action,requested_at,state,attempt_count,max_attempts,next_eligible_at,idempotency_key,retry_of_job_id,maintenance_epoch,schema_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (7, 11, "a" * 64, '["docx","html","pdf"]', "internal", "cde-internal-v1", "2.0.0", "nick", "authorize_diagnostic_retry", "2026-01-01T00:00:03Z", "queued", 0, 3, "2026-01-01T00:00:03Z", "stage77-diagnostic-retry-2", 2, 0, jobs.JOB_SCHEMA_VERSION),
        )
        with self.assertRaisesRegex(ValueError, "retry_topology_invalid"):
            recovery._retry_topology_snapshot(self.conn)

    def test_capture_uses_online_backup_and_exact_artifact_manifest(self):
        result = recovery.capture_recovery_point(database_path=self.db, artifact_root=self.artifacts, recovery_root=self.recovery_root, approved_root=self.root, actor="admin", governed_action="capture", idempotency_key="point-1")
        bundle = self.recovery_root / f"recovery-{result['recovery_point_id']}"
        self.assertEqual(recovery.validate_recovery_bundle(bundle)["manifest_digest"], result["manifest_digest"])
        manifest = json.loads((bundle / "manifest.json").read_text())
        self.assertEqual(manifest["artifacts"][0]["filename"], "artifacts/artifact-3-docx")
        self.assertEqual(manifest["job_event_bound"], 0)
        self.assertNotIn(str(self.db), (bundle / "manifest.json").read_text())
        self.assertFalse((bundle / "database.sqlite3-wal").exists())

    def test_capture_rejects_missing_authoritative_schema_before_maintenance(self):
        temp = tempfile.TemporaryDirectory(dir="/private/tmp")
        try:
            root = Path(temp.name)
            db = root / "records.db"
            artifacts = root / "artifacts"
            artifacts.mkdir()
            recovery_root = root / "recovery"
            conn = sqlite3.connect(db, isolation_level=None)
            jobs.ensure_job_tables(conn)
            conn.close()
            with self.assertRaises(recovery.RecoveryOperationFailure) as raised:
                recovery.capture_recovery_point(database_path=db, artifact_root=artifacts, recovery_root=recovery_root, approved_root=root, actor="admin", governed_action="capture")
            failure = raised.exception
            self.assertEqual((failure.phase, failure.operation, failure.checkpoint, failure.code), ("initialization", "schema_validation", "starting", "schema_incompatible"))
            check = sqlite3.connect(db)
            self.assertEqual(check.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='stage77_recovery_control'").fetchone()[0], 1)
            self.assertEqual(check.execute("SELECT COUNT(*) FROM stage77_recovery_control").fetchone()[0], 0)
            check.close()
        finally:
            temp.cleanup()

    def test_capture_rejects_incompatible_job_event_schema_before_maintenance(self):
        conn = sqlite3.connect(":memory:")
        conn.executescript("""
        CREATE TABLE record_governed_reports(id INTEGER PRIMARY KEY);
        CREATE TABLE record_governed_report_versions(id INTEGER PRIMARY KEY, report_id INTEGER);
        CREATE TABLE record_governed_report_artifacts(id INTEGER PRIMARY KEY, version_id INTEGER, format TEXT, storage_reference TEXT, sha256 TEXT, size_bytes INTEGER, validation_state TEXT);
        CREATE TABLE stage77_report_jobs(id INTEGER, state TEXT, maintenance_epoch INTEGER);
        CREATE TABLE stage77_report_job_events(id TEXT, job_id INTEGER);
        CREATE TABLE stage77_recovery_control(singleton INTEGER, operation_id TEXT, maintenance_epoch INTEGER, state TEXT);
        CREATE TABLE stage77_recovery_events(id INTEGER, operation_id TEXT);
        """)
        with self.assertRaisesRegex(ValueError, "schema_incompatible"):
            recovery._validate_capture_schema(conn)
        conn.close()

    def test_capture_rejects_changed_artifact_and_records_failure(self):
        self.artifact.write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "artifact_digest_mismatch"):
            recovery.capture_recovery_point(database_path=self.db, artifact_root=self.artifacts, recovery_root=self.recovery_root, approved_root=self.root, actor="admin", governed_action="capture")
        self.assertEqual(recovery.recovery_status(self.conn)["state"], "failed")
        self.assertFalse((self.recovery_root / ".stage").exists() and any((self.recovery_root / ".stage").iterdir()))

    def test_recovery_blocks_claims_and_stale_epoch_cannot_finalize(self):
        self.conn.execute("INSERT INTO stage77_report_jobs(report_id,report_version_id,specification_digest,requested_formats_json,rendering_profile,template_version,publication_engine_version,requesting_actor,governed_action,requested_at,state,attempt_count,max_attempts,next_eligible_at,lease_token,maintenance_epoch,idempotency_key,schema_version) VALUES(7,11,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", ("a" * 64, "[]", "internal", "v1", "2.0.0", "admin", "capture", "now", "running", 1, 3, "now", "old-token", 0, "epoch-job", jobs.JOB_SCHEMA_VERSION))
        item = {"id": self.conn.execute("SELECT last_insert_rowid()").fetchone()[0]}
        recovery.request_recovery(self.conn, actor="admin", governed_action="capture")
        self.assertFalse(recovery.recovery_allows_claim(self.conn))
        self.assertFalse(recovery.recovery_allows_finalize(self.conn, item["id"], "old-token", 0))
        recovery.fail_recovery(self.conn, phase="test", code="aborted")
        self.assertFalse(recovery.recovery_allows_claim(self.conn))
        control = recovery.recovery_status(self.conn)
        recovery.abort_recovery(self.conn, recovery_operation_id=control["operation_id"], maintenance_epoch=control["maintenance_epoch"], recovery_root=self.recovery_root, approved_root=self.root, actor="admin", governed_action="abort")
        self.assertTrue(recovery.recovery_allows_claim(self.conn))

    def _failed_recovery(self):
        recovery.request_recovery(self.conn, actor="admin", governed_action="capture")
        recovery.fail_recovery(self.conn, phase="capture", code="sqlite_error")
        return recovery.recovery_status(self.conn)

    def test_abort_requires_exact_operation_and_epoch_and_releases_only_that_failure(self):
        control = self._failed_recovery()
        stage = self.recovery_root / ".stage" / control["operation_id"]
        other = self.recovery_root / ".stage" / ("f" * 32)
        stage.mkdir(parents=True)
        other.mkdir(parents=True)
        result = recovery.abort_recovery(self.conn, recovery_operation_id=control["operation_id"], maintenance_epoch=control["maintenance_epoch"], recovery_root=self.recovery_root, approved_root=self.root, actor="admin", governed_action="abort")
        self.assertEqual(result["operation_id"], control["operation_id"])
        self.assertEqual(result["maintenance_epoch"], 1)
        self.assertEqual(result["prior_state"], "failed")
        self.assertEqual(result["resulting_state"], "failed")
        self.assertEqual(result["cleanup_status"], "completed")
        self.assertEqual(result["maintenance_status"], "released")
        self.assertFalse(stage.exists())
        self.assertTrue(other.exists())
        self.assertTrue(recovery.recovery_allows_claim(self.conn))
        event = self.conn.execute("SELECT event_type,payload_json FROM stage77_recovery_events WHERE event_type='recovery_aborted'").fetchone()
        self.assertEqual(event[0], "recovery_aborted")
        payload = json.loads(event[1])
        self.assertEqual(payload["operation_id"], control["operation_id"])
        self.assertEqual(payload["maintenance_epoch"], 1)

    def test_abort_rejects_identity_epoch_and_state_mismatches_without_mutation(self):
        control = self._failed_recovery()
        for operation_id, epoch, expected in (("0" * 32, 1, "recovery_abort_identity_or_epoch_mismatch"), (control["operation_id"], 2, "recovery_abort_identity_or_epoch_mismatch")):
            with self.assertRaisesRegex(ValueError, expected):
                recovery.abort_recovery(self.conn, recovery_operation_id=operation_id, maintenance_epoch=epoch, recovery_root=self.recovery_root, approved_root=self.root, actor="admin", governed_action="abort")
            self.assertEqual(recovery.recovery_status(self.conn)["worker_drained"], 0)
        with self.assertRaisesRegex(ValueError, "recovery_abort_identity_invalid"):
            recovery.abort_recovery(self.conn, recovery_operation_id="not-an-id", maintenance_epoch=1, recovery_root=self.recovery_root, approved_root=self.root, actor="admin", governed_action="abort")
        with self.assertRaisesRegex(ValueError, "recovery_abort_epoch_invalid"):
            recovery.abort_recovery(self.conn, recovery_operation_id=control["operation_id"], maintenance_epoch=0, recovery_root=self.recovery_root, approved_root=self.root, actor="admin", governed_action="abort")
        recovery.abort_recovery(self.conn, recovery_operation_id=control["operation_id"], maintenance_epoch=1, recovery_root=self.recovery_root, approved_root=self.root, actor="admin", governed_action="abort")
        with self.assertRaisesRegex(ValueError, "recovery_abort_state_mismatch"):
            recovery.abort_recovery(self.conn, recovery_operation_id=control["operation_id"], maintenance_epoch=1, recovery_root=self.recovery_root, approved_root=self.root, actor="admin", governed_action="abort")

    def test_abort_cleanup_failure_is_reported_after_committed_release(self):
        control = self._failed_recovery()
        stage_root = self.recovery_root / ".stage"
        stage_root.mkdir(parents=True)
        outside = self.root / "outside"
        outside.mkdir()
        (stage_root / control["operation_id"]).symlink_to(outside, target_is_directory=True)
        result = recovery.abort_recovery(self.conn, recovery_operation_id=control["operation_id"], maintenance_epoch=1, recovery_root=self.recovery_root, approved_root=self.root, actor="admin", governed_action="abort")
        self.assertEqual(result["cleanup_status"], "failed")
        self.assertEqual(recovery.recovery_status(self.conn)["worker_drained"], 1)
        self.assertTrue(outside.exists())

    def test_abort_event_write_failure_rolls_back_release(self):
        control = self._failed_recovery()
        original_event = recovery._event
        recovery._event = lambda *_args, **_kwargs: (_ for _ in ()).throw(sqlite3.OperationalError("event write failed"))
        try:
            with self.assertRaises(sqlite3.OperationalError):
                recovery.abort_recovery(self.conn, recovery_operation_id=control["operation_id"], maintenance_epoch=1, recovery_root=self.recovery_root, approved_root=self.root, actor="admin", governed_action="abort")
        finally:
            recovery._event = original_event
        self.assertEqual(recovery.recovery_status(self.conn)["worker_drained"], 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM stage77_recovery_events WHERE event_type='recovery_aborted'").fetchone()[0], 0)

    def test_abort_cli_requires_identity_and_epoch(self):
        from scripts import manage_stage77_recovery as cli
        with self.assertRaises(SystemExit):
            cli.parser().parse_args(["abort", "--database", str(self.db), "--recovery-root", str(self.recovery_root), "--actor", "admin", "--action", "abort"])
        with self.assertRaises(SystemExit):
            cli.parser().parse_args(["abort", "--database", str(self.db), "--recovery-root", str(self.recovery_root), "--recovery-operation-id", "0" * 32, "--maintenance-epoch", " 1", "--actor", "admin", "--action", "abort"])

    def test_abort_cli_direct_invocation_returns_bounded_confirmation(self):
        self._failed_recovery()
        control = recovery.recovery_status(self.conn)
        completed = subprocess.run([sys.executable, "scripts/manage_stage77_recovery.py", "abort", "--database", str(self.db), "--recovery-root", str(self.recovery_root), "--approved-root", str(self.root), "--recovery-operation-id", control["operation_id"], "--maintenance-epoch", str(control["maintenance_epoch"]), "--actor", "admin", "--action", "abort"], cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, check=False)
        self.assertEqual(completed.returncode, 0)
        self.assertRegex(completed.stdout.strip(), r"^stage77_recovery=aborted operation=[0-9a-f]{32} epoch=1 prior_state=failed resulting_state=failed cleanup=completed maintenance=released$")
        self.assertNotIn(str(self.root), completed.stdout)
        self.assertNotIn("Traceback", completed.stderr)

    def test_heartbeat_is_fenced_after_maintenance_epoch_changes(self):
        self.conn.execute("INSERT INTO stage77_report_jobs(report_id,report_version_id,specification_digest,requested_formats_json,rendering_profile,template_version,publication_engine_version,requesting_actor,governed_action,requested_at,state,attempt_count,max_attempts,next_eligible_at,lease_token,maintenance_epoch,idempotency_key,schema_version) VALUES(7,11,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", ("a" * 64, "[]", "internal", "v1", "2.0.0", "admin", "capture", "now", "running", 1, 3, "now", "old-token", 0, "epoch-heartbeat", jobs.JOB_SCHEMA_VERSION))
        job_id = self.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        recovery.request_recovery(self.conn, actor="admin", governed_action="capture")
        self.assertFalse(jobs.heartbeat(self.conn, job_id, "old-token"))

    def test_duplicate_registered_source_is_rejected(self):
        self.conn.execute("INSERT INTO record_governed_report_artifacts VALUES(4,11,'html',?,?,?,'valid')", (str(self.artifact), recovery.digest_bytes(self.bytes), len(self.bytes)))
        with self.assertRaisesRegex(ValueError, "duplicate_artifact_source"):
            recovery.capture_recovery_point(database_path=self.db, artifact_root=self.artifacts, recovery_root=self.recovery_root, approved_root=self.root, actor="admin", governed_action="capture")

    def test_foreign_key_check_consumes_all_violations(self):
        conn = sqlite3.connect(":memory:")
        conn.executescript("CREATE TABLE parent(id INTEGER PRIMARY KEY); CREATE TABLE child(id INTEGER PRIMARY KEY, parent_id INTEGER REFERENCES parent(id)); PRAGMA foreign_keys=OFF; INSERT INTO child VALUES(1,10),(2,20);")
        self.assertFalse(recovery._foreign_keys_are_clean(conn))
        conn.close()

    def test_restore_rejects_live_recovery_root(self):
        result = recovery.capture_recovery_point(database_path=self.db, artifact_root=self.artifacts, recovery_root=self.recovery_root, approved_root=self.root, actor="admin", governed_action="capture")
        bundle = self.recovery_root / f"recovery-{result['recovery_point_id']}"
        with self.assertRaisesRegex(ValueError, "restore_target_invalid"):
            recovery.restore_recovery_point(bundle_path=bundle, restore_root=self.recovery_root, database_target=self.root / "restored.db", artifact_root_target=self.root / "restored-artifacts", live_database=self.db, live_artifact_root=self.artifacts, live_recovery_root=self.recovery_root, actor="admin", governed_action="restore", approved_root=self.root)

    def test_restore_rejects_live_and_nonempty_targets(self):
        result = recovery.capture_recovery_point(database_path=self.db, artifact_root=self.artifacts, recovery_root=self.recovery_root, approved_root=self.root, actor="admin", governed_action="capture")
        bundle = self.recovery_root / f"recovery-{result['recovery_point_id']}"
        with self.assertRaisesRegex(ValueError, "restore_target_invalid"):
            recovery.restore_recovery_point(bundle_path=bundle, restore_root=self.root / "restore", database_target=self.db, artifact_root_target=self.root / "restore-artifacts", live_database=self.db, live_artifact_root=self.artifacts, live_recovery_root=self.recovery_root, actor="admin", governed_action="restore", approved_root=self.root)
        restore_root = self.root / "restore"
        restore_root.mkdir()
        nonempty = restore_root / "records.db"
        nonempty.write_bytes(b"occupied")
        with self.assertRaisesRegex(ValueError, "restore_target_invalid"):
            recovery.restore_recovery_point(bundle_path=bundle, restore_root=restore_root, database_target=nonempty, artifact_root_target=restore_root / "artifacts", live_database=self.db, live_artifact_root=self.artifacts, live_recovery_root=self.recovery_root, actor="admin", governed_action="restore", approved_root=self.root)

    def test_isolated_restore_invalidates_leases_and_replays_terminal_success(self):
        result = recovery.capture_recovery_point(database_path=self.db, artifact_root=self.artifacts, recovery_root=self.recovery_root, approved_root=self.root, actor="admin", governed_action="capture")
        bundle = self.recovery_root / f"recovery-{result['recovery_point_id']}"
        restored = self.root / "restored"
        restored.mkdir()
        output = recovery.restore_recovery_point(bundle_path=bundle, restore_root=restored, database_target=restored / "records.db", artifact_root_target=restored / "artifacts", live_database=self.db, live_artifact_root=self.artifacts, live_recovery_root=self.recovery_root, actor="admin", governed_action="restore", approved_root=self.root)
        self.assertEqual(output["state"], "restore_ready")
        conn = sqlite3.connect(restored / "records.db")
        conn.row_factory = sqlite3.Row
        self.assertEqual(recovery.recovery_status(conn)["state"], "restore_ready")
        self.assertTrue(recovery.recovery_allows_claim(conn))
        self.assertEqual((restored / "artifacts" / "artifact-3-docx").read_bytes(), self.bytes)
        conn.close()

    def test_manifest_tampering_and_extra_files_fail_closed(self):
        result = recovery.capture_recovery_point(database_path=self.db, artifact_root=self.artifacts, recovery_root=self.recovery_root, approved_root=self.root, actor="admin", governed_action="capture")
        bundle = self.recovery_root / f"recovery-{result['recovery_point_id']}"
        (bundle / "unexpected").write_bytes(b"x")
        with self.assertRaisesRegex(ValueError, "bundle_file_inventory_invalid"):
            recovery.validate_recovery_bundle(bundle)

    def test_manifest_must_be_canonical_and_duplicate_keys_are_rejected(self):
        result = recovery.capture_recovery_point(database_path=self.db, artifact_root=self.artifacts, recovery_root=self.recovery_root, approved_root=self.root, actor="admin", governed_action="capture")
        bundle = self.recovery_root / f"recovery-{result['recovery_point_id']}"
        manifest_path = bundle / "manifest.json"
        raw = manifest_path.read_text().rstrip("\n")
        manifest_path.write_text(raw[:-1] + ',"manifest_schema_version":"duplicate"}')
        (bundle / "manifest.sha256").write_text(recovery.digest_bytes(manifest_path.read_bytes()) + "\n")
        with self.assertRaisesRegex(ValueError, "manifest_invalid"):
            recovery.validate_recovery_bundle(bundle)

    def test_recovery_events_are_append_only(self):
        recovery.request_recovery(self.conn, actor="admin", governed_action="capture")
        event_id = self.conn.execute("SELECT id FROM stage77_recovery_events").fetchone()[0]
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("UPDATE stage77_recovery_events SET actor='changed' WHERE id=?", (event_id,))
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("DELETE FROM stage77_recovery_events WHERE id=?", (event_id,))

    def test_capture_replay_is_idempotent_and_manifest_has_no_raw_paths(self):
        first = recovery.capture_recovery_point(database_path=self.db, artifact_root=self.artifacts, recovery_root=self.recovery_root, approved_root=self.root, actor="admin", governed_action="capture", idempotency_key="same-point")
        second = recovery.capture_recovery_point(database_path=self.db, artifact_root=self.artifacts, recovery_root=self.recovery_root, approved_root=self.root, actor="admin", governed_action="capture", idempotency_key="same-point")
        self.assertEqual(first, second)
        raw = (self.recovery_root / f"recovery-{first['recovery_point_id']}" / "manifest.json").read_text()
        self.assertNotIn(str(self.root), raw)
        self.assertNotIn("traceback", raw.lower())

    def test_post_restore_materializes_current_evidence_after_bundle_validation(self):
        jobs.ensure_post_correction_tables(self.conn)
        result = recovery.capture_recovery_point(database_path=self.db, artifact_root=self.artifacts, recovery_root=self.recovery_root, approved_root=self.root, actor="admin", governed_action="capture")
        bundle = self.recovery_root / f"recovery-{result['recovery_point_id']}"
        before_database = recovery.digest_bytes((bundle / "database.sqlite3").read_bytes())
        archived = sqlite3.connect(bundle / "database.sqlite3")
        try:
            self.assertEqual(archived.execute("SELECT COUNT(*) FROM stage77_recovery_point_evidence").fetchone()[0], 0)
        finally:
            archived.close()
        self.assertEqual(recovery.validate_recovery_bundle(bundle)["state"], "valid")
        self.assertEqual(recovery.digest_bytes((bundle / "database.sqlite3").read_bytes()), before_database)
        manifest = json.loads((bundle / "manifest.json").read_text())
        payload = manifest["current_recovery_manifest_evidence"]
        self.assertNotIn("manifest_digest", payload)
        self.assertNotIn("archive_digest", payload)
        self.assertNotIn("receipt_digest", payload)
        self.assertNotIn("custody_directory_identity", payload)
        restore_root = self.root / "post-restore"
        restore_root.mkdir()
        output = recovery.restore_recovery_point(bundle_path=bundle, restore_root=restore_root, database_target=restore_root / "records.db", artifact_root_target=restore_root / "artifacts", live_database=self.db, live_artifact_root=self.artifacts, live_recovery_root=self.recovery_root, actor="admin", governed_action="restore", approved_root=self.root)
        self.assertEqual(output["state"], "restore_ready")
        restored = sqlite3.connect(restore_root / "records.db")
        try:
            self.assertEqual(restored.execute("SELECT COUNT(*) FROM stage77_recovery_point_evidence").fetchone()[0], 1)
            self.assertEqual(restored.execute("SELECT COUNT(*) FROM stage77_recovery_point_evidence_events").fetchone()[0], 1)
        finally:
            restored.close()

    def test_interrupted_recovery_reconciliation_is_explicit_and_idempotent(self):
        result = recovery.capture_recovery_point(database_path=self.db, artifact_root=self.artifacts, recovery_root=self.recovery_root, approved_root=self.root, actor="admin", governed_action="capture")
        self.conn.execute("UPDATE stage77_recovery_control SET state='capturing',worker_drained=1 WHERE singleton=1")
        self.conn.commit()
        reconciled = recovery.reconcile_interrupted_recovery(database_path=self.db, recovery_root=self.recovery_root, approved_root=self.root, actor="admin")
        self.assertEqual(reconciled["recovery_point_id"], result["recovery_point_id"])
        self.assertEqual(reconciled["state"], "completed")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM stage77_recovery_point_evidence").fetchone()[0], 1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM stage77_recovery_point_evidence_events").fetchone()[0], 1)

    def test_recovery_evidence_and_events_are_immutable(self):
        result = recovery.capture_recovery_point(database_path=self.db, artifact_root=self.artifacts, recovery_root=self.recovery_root, approved_root=self.root, actor="admin", governed_action="capture")
        evidence_id = self.conn.execute("SELECT id FROM stage77_recovery_point_evidence WHERE recovery_point_id=?", (result["recovery_point_id"],)).fetchone()[0]
        event_id = self.conn.execute("SELECT id FROM stage77_recovery_point_evidence_events WHERE evidence_id=?", (evidence_id,)).fetchone()[0]
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("UPDATE stage77_recovery_point_evidence SET actor='changed' WHERE id=?", (evidence_id,))
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("DELETE FROM stage77_recovery_point_evidence WHERE id=?", (evidence_id,))
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("UPDATE stage77_recovery_point_evidence_events SET actor='changed' WHERE id=?", (event_id,))
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("DELETE FROM stage77_recovery_point_evidence_events WHERE id=?", (event_id,))

    def test_historical_reconstruction_uses_unchanged_bundle_and_separate_live_store(self):
        self._add_diagnostic_evidence(linked_successor=True)
        result = recovery.capture_recovery_point(database_path=self.db, artifact_root=self.artifacts, recovery_root=self.recovery_root, approved_root=self.root, actor="admin", governed_action="capture")
        bundle = self.recovery_root / f"recovery-{result['recovery_point_id']}"
        manifest_before = (bundle / "manifest.json").read_bytes()
        database_before = (bundle / "database.sqlite3").read_bytes()
        live_db = self.root / "historical-live.db"
        live = sqlite3.connect(live_db)
        try:
            live.row_factory = sqlite3.Row
            recovery.ensure_recovery_tables(live)
            live.commit()
        finally:
            live.close()
        reconstructed = recovery.reconstruct_recovery_point_evidence(database_path=live_db, recovery_root=self.recovery_root, recovery_point_id=result["recovery_point_id"], actor="admin", rationale="historical evidence reconstruction", acknowledged=True, idempotency_key="historical-1", approved_root=self.root)
        self.assertEqual(reconstructed["state"], "finalized")
        self.assertEqual(reconstructed["payload"]["evidence_source_mode"], "historical_reconstruction")
        replay = recovery.reconstruct_recovery_point_evidence(database_path=live_db, recovery_root=self.recovery_root, recovery_point_id=result["recovery_point_id"], actor="admin", rationale="historical evidence reconstruction", acknowledged=True, idempotency_key="historical-1", approved_root=self.root)
        self.assertEqual(replay["id"], reconstructed["id"])
        self.assertEqual((bundle / "manifest.json").read_bytes(), manifest_before)
        self.assertEqual((bundle / "database.sqlite3").read_bytes(), database_before)

    def _add_valid_qualification_chain(self):
        specification_digest = self.conn.execute("SELECT specification_digest FROM record_governed_report_versions WHERE id=11").fetchone()[0]
        previous = None
        for revision, gate in enumerate(qualifications.GATES, 1):
            payload = {
                "report_id": 7, "report_version_id": 11, "specification_digest": specification_digest,
                "revision_number": revision, "previous_qualification_id": previous, "completed_gate": gate,
                "review_mode": qualifications.INDEPENDENT_MODE, "operating_constraint": "two-person review",
                "creator_actor": "creator", "qualifier_actor": "qualifier", "rationale": "bounded qualification",
                "declaration": {"acknowledged": True}, "disclosure_version": "standard-v1",
                "distribution_restriction": "internal_working",
            }
            digest = qualifications._payload_digest(payload)
            cursor = self.conn.execute(
                "INSERT INTO record_governed_report_qualifications (report_id,report_version_id,specification_digest,revision_number,previous_qualification_id,completed_gate,review_mode,operating_constraint,creator_actor,qualifier_actor,rationale,declaration_json,disclosure_version,distribution_restriction,qualification_payload_json,qualification_digest,qualification_state,created_at,finalized_at,idempotency_key) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (7, 11, specification_digest, revision, previous, gate, qualifications.INDEPENDENT_MODE, "two-person review", "creator", "qualifier", "bounded qualification", qualifications.canonical_json(payload["declaration"]), "standard-v1", "internal_working", qualifications.canonical_json(payload), digest, "final", f"2026-01-01T00:00:0{revision}Z", f"2026-01-01T00:00:0{revision}Z", f"qualification-{revision}"),
            )
            qualification_id = int(cursor.lastrowid)
            self.conn.execute(
                "INSERT INTO record_governed_report_qualification_events (qualification_id,report_id,report_version_id,event_type,actor,occurred_at,idempotency_key,payload_json) VALUES (?,?,?,?,?,?,?,?)",
                (qualification_id, 7, 11, qualifications.INDEPENDENT_EVENTS[gate], "qualifier", f"2026-01-01T00:00:0{revision}Z", f"qualification-{revision}", qualifications.canonical_json(payload)),
            )
            previous = qualification_id
        self.conn.commit()

    def _historical_reconstruction_fixture(self, post_correction=False, with_qualifications=False):
        if not post_correction:
            self._add_diagnostic_evidence(linked_successor=True)
        from api import governed_report_diagnostics as diagnostics
        if not post_correction:
            transitional = diagnostics.TRANSITIONAL_DIAGNOSTIC
            attempt_raw = recovery.canonical_json([transitional])
            terminal_raw = recovery.canonical_json({"phase": "rendering", "code": "governed_report_renderer_failed", "diagnostic": transitional, **transitional})
            self.conn.execute(
                "INSERT INTO record_governed_report_generation_attempts (version_id,requested_formats_json,actor,actor_role,requested_at,result,diagnostics_json,request_payload_json,idempotency_key) VALUES(?,?,?,?,?,?,?,?,?)",
                (11, '["docx","html","pdf"]', jobs.WORKER_IDENTITY, "system_worker", "2026-01-01T00:00:02Z", "validation_failed", attempt_raw, "{}", "stage77-job-2"),
            )
            successor = self.conn.execute("SELECT id FROM stage77_report_jobs WHERE retry_of_job_id IS NOT NULL").fetchone()[0]
            self.conn.execute("UPDATE stage77_report_jobs SET state='failed_terminal',attempt_count=1,failure_phase='rendering',failure_code='governed_report_renderer_failed' WHERE id=?", (successor,))
            self.conn.execute(
                "INSERT INTO stage77_report_job_events (job_id,event_type,resulting_state,actor,occurred_at,payload_json) VALUES(?,?,?,?,?,?)",
                (successor, "terminal", "failed_terminal", jobs.WORKER_IDENTITY, "2026-01-01T00:00:03Z", terminal_raw),
            )
        self.conn.commit()
        if with_qualifications:
            self._add_valid_qualification_chain()
        if post_correction:
            jobs.ensure_post_correction_tables(self.conn)
        result = recovery.capture_recovery_point(database_path=self.db, artifact_root=self.artifacts, recovery_root=self.recovery_root, approved_root=self.root, actor="admin", governed_action="capture")
        bundle = self.recovery_root / f"recovery-{result['recovery_point_id']}"
        live_db = self.root / "historical-live.db"
        live = sqlite3.connect(live_db)
        live.row_factory = sqlite3.Row
        recovery.ensure_recovery_tables(live)
        live.close()
        return bundle, live_db, result["recovery_point_id"]

    def _assert_historical_rejection(self, mutate, expected_code):
        bundle, live_db, point_id = self._historical_reconstruction_fixture()
        manifest_path = bundle / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        mutate(bundle, manifest)
        with self.assertRaisesRegex(ValueError, expected_code):
            recovery.reconstruct_recovery_point_evidence(database_path=live_db, recovery_root=self.recovery_root, recovery_point_id=point_id, actor="admin", rationale="bounded reconstruction", acknowledged=True, idempotency_key="batch3a", approved_root=self.root)
        with self.assertRaisesRegex(ValueError, expected_code):
            recovery.reconstruct_recovery_point_evidence(database_path=live_db, recovery_root=self.recovery_root, recovery_point_id=point_id, actor="admin", rationale="bounded reconstruction", acknowledged=True, idempotency_key="batch3a", approved_root=self.root)
        check = sqlite3.connect(live_db)
        self.assertEqual(check.execute("SELECT COUNT(*) FROM stage77_recovery_point_evidence").fetchone()[0], 0)
        self.assertEqual(check.execute("SELECT COUNT(*) FROM stage77_recovery_point_evidence_events").fetchone()[0], 0)
        check.close()

    @staticmethod
    def _rewrite_manifest(bundle, manifest):
        raw = recovery.canonical_json(manifest).encode("utf-8")
        (bundle / "manifest.json").write_bytes(raw)
        (bundle / "manifest.sha256").write_text(recovery.digest_bytes(raw) + "\n", encoding="ascii")

    @staticmethod
    def _append_bytes(path, value):
        with path.open("ab") as stream:
            stream.write(value)

    def _refresh_archived_database_binding(self, bundle, manifest):
        data = (bundle / "database.sqlite3").read_bytes()
        manifest["database"] = {"filename": "database.sqlite3", "size_bytes": len(data), "sha256": recovery.digest_bytes(data)}
        self._rewrite_manifest(bundle, manifest)

    def _mutate_archived_database(self, bundle, manifest, mutation):
        conn = sqlite3.connect(bundle / "database.sqlite3")
        conn.row_factory = sqlite3.Row
        mutation(conn, manifest)
        conn.commit()
        conn.close()
        self._refresh_archived_database_binding(bundle, manifest)

    def test_batch3b1_case_13_diagnostic_count_mismatch(self):
        cases = [
            ("lower", lambda b, m: (m.__setitem__("diagnostic_evidence", m["diagnostic_evidence"][:1]), m.__setitem__("diagnostic_evidence_count", 1), m.__setitem__("diagnostic_evidence_state_digest", recovery.digest_bytes(recovery.canonical_json(m["diagnostic_evidence"]).encode())), self._rewrite_manifest(b, m)), "diagnostic_evidence_mismatch"),
            ("higher", lambda b, m: (m["diagnostic_evidence"].append({**m["diagnostic_evidence"][-1], "job_id": 999999}), m.__setitem__("diagnostic_evidence_count", 3), m.__setitem__("diagnostic_evidence_state_digest", recovery.digest_bytes(recovery.canonical_json(m["diagnostic_evidence"]).encode())), self._rewrite_manifest(b, m)), "diagnostic_evidence_mismatch"),
            ("string", lambda b, m: (m.__setitem__("diagnostic_evidence_count", "2"), self._rewrite_manifest(b, m)), "manifest_invalid"),
            ("boolean", lambda b, m: (m.__setitem__("diagnostic_evidence_count", True), self._rewrite_manifest(b, m)), "manifest_invalid"),
            ("negative", lambda b, m: (m.__setitem__("diagnostic_evidence_count", -1), self._rewrite_manifest(b, m)), "diagnostic_evidence_count_mismatch"),
            ("omitted", lambda b, m: (m.pop("diagnostic_evidence_count"), self._rewrite_manifest(b, m)), "manifest_invalid"),
            ("extra_sqlite_evidence", lambda b, m: (m.__setitem__("diagnostic_evidence", m["diagnostic_evidence"][:1]), m.__setitem__("diagnostic_evidence_count", 1), m.__setitem__("diagnostic_evidence_state_digest", recovery.digest_bytes(recovery.canonical_json(m["diagnostic_evidence"]).encode())), self._rewrite_manifest(b, m)), "diagnostic_evidence_mismatch"),
        ]
        for name, mutate, expected in cases:
            with self.subTest(case=name):
                self.tearDown()
                self.setUp()
                self._assert_historical_rejection(mutate, expected)

    def test_batch3b1_case_14_diagnostic_state_digest_mismatch(self):
        cases = [
            ("changed_hex", lambda b, m: (m["diagnostic_evidence"][0].__setitem__("attempt_id", 999999), m.__setitem__("diagnostic_evidence_state_digest", recovery.digest_bytes(recovery.canonical_json(m["diagnostic_evidence"]).encode())), self._rewrite_manifest(b, m)), "diagnostic_evidence_mismatch"),
            ("uppercase", lambda b, m: (m.__setitem__("diagnostic_evidence_state_digest", m["diagnostic_evidence_state_digest"].upper()), self._rewrite_manifest(b, m)), "diagnostic_evidence_digest_mismatch"),
            ("truncated", lambda b, m: (m.__setitem__("diagnostic_evidence_state_digest", m["diagnostic_evidence_state_digest"][:-1]), self._rewrite_manifest(b, m)), "diagnostic_evidence_digest_mismatch"),
            ("overlength", lambda b, m: (m.__setitem__("diagnostic_evidence_state_digest", m["diagnostic_evidence_state_digest"] + "0"), self._rewrite_manifest(b, m)), "diagnostic_evidence_digest_mismatch"),
            ("nonhex", lambda b, m: (m.__setitem__("diagnostic_evidence_state_digest", "g" * 64), self._rewrite_manifest(b, m)), "diagnostic_evidence_digest_mismatch"),
            ("wrong_type", lambda b, m: (m.__setitem__("diagnostic_evidence_state_digest", 7), self._rewrite_manifest(b, m)), "diagnostic_evidence_digest_mismatch"),
            ("omitted", lambda b, m: (m.pop("diagnostic_evidence_state_digest"), self._rewrite_manifest(b, m)), "manifest_invalid"),
            ("unrelated_sha256", lambda b, m: (m.__setitem__("diagnostic_evidence_state_digest", recovery.digest_bytes(b"unrelated")), self._rewrite_manifest(b, m)), "diagnostic_evidence_digest_mismatch"),
        ]
        for name, mutate, expected in cases:
            with self.subTest(case=name):
                self.tearDown()
                self.setUp()
                self._assert_historical_rejection(mutate, expected)

    def test_batch3b1_case_14_physical_row_order_is_canonical(self):
        bundle, live_db, point_id = self._historical_reconstruction_fixture()
        archived = sqlite3.connect(bundle / "database.sqlite3")
        archived.execute("VACUUM")
        archived.close()
        manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
        self._refresh_archived_database_binding(bundle, manifest)
        reconstructed = recovery.reconstruct_recovery_point_evidence(database_path=live_db, recovery_root=self.recovery_root, recovery_point_id=point_id, actor="admin", rationale="bounded reconstruction", acknowledged=True, idempotency_key="batch3b1-order", approved_root=self.root)
        self.assertEqual(reconstructed["state"], "finalized")

    def test_batch3b1_case_15_job1_incomplete_diagnostic_pair(self):
        def update_attempt(conn, _manifest):
            conn.execute("UPDATE record_governed_report_generation_attempts SET diagnostics_json='[]' WHERE id=(SELECT id FROM record_governed_report_generation_attempts ORDER BY id LIMIT 1)")

        def update_terminal(conn, _manifest):
            conn.execute("UPDATE stage77_report_job_events SET payload_json='{}' WHERE job_id=(SELECT id FROM stage77_report_jobs WHERE state='failed_terminal' ORDER BY id LIMIT 1) AND event_type='terminal'")

        def update_both(conn, manifest):
            update_attempt(conn, manifest)
            update_terminal(conn, manifest)

        def move_attempt(conn, _manifest):
            conn.execute("UPDATE record_governed_report_generation_attempts SET idempotency_key='wrong-attempt' WHERE id=(SELECT id FROM record_governed_report_generation_attempts ORDER BY id LIMIT 1)")

        def move_terminal(conn, _manifest):
            conn.execute("UPDATE stage77_report_job_events SET event_type='other' WHERE job_id=(SELECT id FROM stage77_report_jobs WHERE state='failed_terminal' ORDER BY id LIMIT 1) AND event_type='terminal'")

        def wrong_version(conn, _manifest):
            conn.execute("UPDATE record_governed_report_generation_attempts SET version_id=999 WHERE id=(SELECT id FROM record_governed_report_generation_attempts ORDER BY id LIMIT 1)")

        def wrong_job_event(conn, _manifest):
            conn.execute("UPDATE stage77_report_job_events SET job_id=(SELECT MAX(id) FROM stage77_report_jobs) WHERE job_id=(SELECT MIN(id) FROM stage77_report_jobs) AND event_type='terminal'")

        def nonterminal(conn, _manifest):
            conn.execute("UPDATE stage77_report_jobs SET state='queued' WHERE state='failed_terminal'")

        def unrelated_missing(conn, _manifest):
            conn.execute("UPDATE record_governed_report_generation_attempts SET diagnostics_json='[]' WHERE id=(SELECT id FROM record_governed_report_generation_attempts ORDER BY id LIMIT 1)")
            conn.execute("UPDATE stage77_report_jobs SET state='queued' WHERE state='failed_terminal'")

        cases = [("missing_attempt", update_attempt, "diagnostic_evidence_invalid"), ("missing_terminal", update_terminal, "diagnostic_evidence_invalid"), ("missing_both", update_both, "diagnostic_evidence_mismatch"), ("wrong_attempt", move_attempt, "diagnostic_evidence_invalid"), ("wrong_terminal", move_terminal, "diagnostic_evidence_mismatch"), ("wrong_attempt_version", wrong_version, "diagnostic_evidence_invalid"), ("wrong_report_version_owner", wrong_version, "diagnostic_evidence_invalid"), ("wrong_terminal_job", wrong_job_event, "diagnostic_evidence_mismatch"), ("nonterminal", nonterminal, "retry_topology_invalid"), ("unrelated_job", unrelated_missing, "retry_topology_invalid")]
        for name, mutation, expected in cases:
            with self.subTest(case=name):
                self.tearDown()
                self.setUp()
                def mutate(bundle, manifest):
                    self._mutate_archived_database(bundle, manifest, mutation)
                self._assert_historical_rejection(mutate, expected)

    def _job2_pair_mutation(self, conn, attempt_raw=None, terminal_raw=None):
        job_id = conn.execute("SELECT id FROM stage77_report_jobs WHERE retry_of_job_id IS NOT NULL").fetchone()[0]
        if attempt_raw is not None:
            conn.execute("UPDATE record_governed_report_generation_attempts SET diagnostics_json=? WHERE idempotency_key='stage77-job-2'", (attempt_raw,))
        if terminal_raw is not None:
            conn.execute("UPDATE stage77_report_job_events SET payload_json=? WHERE job_id=? AND event_type='terminal'", (terminal_raw, job_id))

    def _contract_pair(self, contract, *, current_diagnostic=None):
        from api import governed_report_diagnostics as diagnostics
        if contract == "legacy":
            return recovery.canonical_json(list(diagnostics.LEGACY_ATTEMPT_DIAGNOSTICS)), recovery.canonical_json(diagnostics.LEGACY_TERMINAL_PAYLOAD)
        if contract == "transitional":
            value = diagnostics.TRANSITIONAL_DIAGNOSTIC
            return recovery.canonical_json([value]), recovery.canonical_json({"phase": "rendering", "code": "governed_report_renderer_failed", "diagnostic": value, **value})
        value = current_diagnostic or jobs.make_diagnostic(phase="rendering", operation="renderer_invocation", checkpoint="entered", code=jobs.DIAGNOSTIC_RETRY_FAILURE_CODE, format_category="multiple")
        return recovery.canonical_json([value]), recovery.canonical_json({"phase": value["failure_phase"], "operation": value["failure_operation"], "checkpoint": value["failure_checkpoint"], "code": value["failure_code"], "diagnostic": value, **value})

    def test_batch3b2_case_16_job2_diagnostic_pair_ownership(self):
        from api import governed_report_diagnostics as diagnostics
        legacy_attempt, legacy_terminal = self._contract_pair("legacy")
        transitional_attempt, transitional_terminal = self._contract_pair("transitional")
        cases = [
            ("missing_attempt", lambda c, _m: self._job2_pair_mutation(c, attempt_raw="[]"), "diagnostic_evidence_invalid"),
            ("missing_terminal", lambda c, _m: self._job2_pair_mutation(c, terminal_raw="{}"), "diagnostic_evidence_invalid"),
            ("missing_both", lambda c, _m: self._job2_pair_mutation(c, attempt_raw="[]", terminal_raw="{}"), "diagnostic_evidence_mismatch"),
            ("wrong_attempt", lambda c, _m: c.execute("UPDATE record_governed_report_generation_attempts SET idempotency_key='wrong-job2-attempt' WHERE idempotency_key='stage77-job-2'"), "diagnostic_evidence_invalid"),
            ("wrong_terminal", lambda c, _m: c.execute("UPDATE stage77_report_job_events SET event_type='other' WHERE job_id=(SELECT id FROM stage77_report_jobs WHERE retry_of_job_id IS NOT NULL) AND event_type='terminal'"), "diagnostic_evidence_mismatch"),
            ("attempt_belongs_job1", lambda c, _m: c.execute("UPDATE record_governed_report_generation_attempts SET version_id=999 WHERE idempotency_key='stage77-job-2'"), "diagnostic_evidence_invalid"),
            ("terminal_belongs_job1", lambda c, _m: c.execute("UPDATE stage77_report_job_events SET job_id=(SELECT MIN(id) FROM stage77_report_jobs) WHERE job_id=(SELECT id FROM stage77_report_jobs WHERE retry_of_job_id IS NOT NULL) AND event_type='terminal'"), "diagnostic_evidence_invalid"),
            ("report_ownership", lambda c, _m: c.execute("UPDATE stage77_report_jobs SET report_id=999 WHERE retry_of_job_id IS NOT NULL"), "diagnostic_evidence_invalid"),
            ("version_ownership", lambda c, _m: c.execute("UPDATE stage77_report_jobs SET report_version_id=999 WHERE retry_of_job_id IS NOT NULL"), "diagnostic_evidence_invalid"),
            ("nonterminal", lambda c, _m: c.execute("UPDATE stage77_report_jobs SET state='queued' WHERE retry_of_job_id IS NOT NULL"), "diagnostic_evidence_mismatch"),
            ("wrong_action", lambda c, m: c.execute("UPDATE stage77_report_jobs SET governed_action='enqueue_generation' WHERE retry_of_job_id IS NOT NULL"), "diagnostic_evidence_invalid"),
            ("unrelated_payload", lambda c, _m: self._job2_pair_mutation(c, attempt_raw="[]"), "diagnostic_evidence_invalid"),
        ]
        for name, mutation, expected in cases:
            with self.subTest(case=name):
                self.tearDown(); self.setUp()
                def mutate(bundle, manifest):
                    self._mutate_archived_database(bundle, manifest, mutation)
                self._assert_historical_rejection(mutate, expected)

    def test_batch3b2_case_17_mixed_diagnostic_contracts(self):
        pairs = {name: self._contract_pair(name) for name in ("legacy", "transitional", "current")}
        cases = [
            ("job1_legacy_transitional", "job1", "legacy", "transitional"),
            ("job1_transitional_legacy", "job1", "transitional", "legacy"),
            ("job2_transitional_legacy", "job2", "transitional", "legacy"),
            ("job2_legacy_transitional", "job2", "legacy", "transitional"),
            ("legacy_current", "job1", "legacy", "current"),
            ("current_legacy", "job1", "current", "legacy"),
            ("transitional_current", "job2", "transitional", "current"),
            ("current_transitional", "job2", "current", "transitional"),
        ]
        for name, target, attempt_contract, terminal_contract in cases:
            with self.subTest(case=name):
                self.tearDown(); self.setUp()
                def mutate(bundle, manifest, target=target, attempt_contract=attempt_contract, terminal_contract=terminal_contract):
                    def change(conn, _manifest):
                        job_id = conn.execute("SELECT id FROM stage77_report_jobs WHERE retry_of_job_id IS NOT NULL").fetchone()[0] if target == "job2" else conn.execute("SELECT MIN(id) FROM stage77_report_jobs").fetchone()[0]
                        attempt_key = "stage77-job-2" if target == "job2" else "stage77-job-1"
                        attempt_raw, _ = pairs[attempt_contract]
                        _, terminal_raw = pairs[terminal_contract]
                        conn.execute("UPDATE record_governed_report_generation_attempts SET diagnostics_json=? WHERE idempotency_key=?", (attempt_raw, attempt_key))
                        conn.execute("UPDATE stage77_report_job_events SET payload_json=? WHERE job_id=? AND event_type='terminal'", (terminal_raw, job_id))
                    self._mutate_archived_database(bundle, manifest, change)
                self._assert_historical_rejection(mutate, "diagnostic_evidence_invalid")
        for name, target, contract in (("legacy_mislabeled", "job1", "legacy"), ("transitional_mislabeled", "job2", "transitional"), ("swapped_identities", "job1", "legacy"), ("manifest_contract_mismatch", "job2", "transitional")):
            with self.subTest(case=name):
                self.tearDown(); self.setUp()
                def mutate(bundle, manifest, name=name, target=target, contract=contract):
                    if name == "manifest_contract_mismatch":
                        manifest["diagnostic_contract_version"] = "current_diagnostic_contract_v1"
                    elif name == "swapped_identities":
                        manifest["diagnostic_evidence"][0]["job_id"], manifest["diagnostic_evidence"][1]["job_id"] = manifest["diagnostic_evidence"][1]["job_id"], manifest["diagnostic_evidence"][0]["job_id"]
                    else:
                        index = 0 if target == "job1" else 1
                        manifest["diagnostic_evidence"][index]["diagnostic_contract_version"] = "current_diagnostic_contract_v1" if name == "transitional_mislabeled" else "legacy_pre_propagation_diagnostic_contract_v1"
                    if name in {"legacy_mislabeled", "transitional_mislabeled"}:
                        manifest["diagnostic_evidence_state_digest"] = recovery.digest_bytes(recovery.canonical_json(manifest["diagnostic_evidence"]).encode())
                    self._rewrite_manifest(bundle, manifest)
                expected = "manifest_invalid" if name in {"swapped_identities", "manifest_contract_mismatch"} else "diagnostic_evidence_mismatch"
                self._assert_historical_rejection(mutate, expected)

    def test_batch3b2_case_18_unknown_partial_malformed_and_unsafe_contracts(self):
        def job2_attempt(mutator):
            def mutate(bundle, manifest):
                def change(conn, _manifest):
                    raw = conn.execute("SELECT diagnostics_json FROM record_governed_report_generation_attempts WHERE idempotency_key='stage77-job-2'").fetchone()[0]
                    mutator(raw, conn)
                self._mutate_archived_database(bundle, manifest, change)
            return mutate
        def replace(raw, value):
            return lambda _raw, conn: conn.execute("UPDATE record_governed_report_generation_attempts SET diagnostics_json=? WHERE idempotency_key='stage77-job-2'", (value,))
        from api import governed_report_diagnostics as diagnostics
        current_attempt, current_terminal = self._contract_pair("current")
        malformed = [
            ("unknown_identifier", lambda raw, c: c.execute("UPDATE stage77_report_jobs SET governed_action='unknown' WHERE retry_of_job_id IS NOT NULL"), "diagnostic_evidence_invalid"),
            ("blank_identifier", replace("", ""), "diagnostic_evidence_invalid"),
            ("wrong_identifier_type", replace("", "7"), "diagnostic_evidence_invalid"),
            ("unknown_field", replace("", "[{\"failure_phase\":\"rendering\",\"unknown\":true}]"), "diagnostic_evidence_invalid"),
            ("missing_field", replace("", "[{}]"), "diagnostic_evidence_invalid"),
            ("extra_field", replace("", "[{\"failure_phase\":\"rendering\",\"extra\":true}]"), "diagnostic_evidence_invalid"),
            ("duplicate_key", replace("", "[{\"x\":1,\"x\":2}]"), "diagnostic_evidence_invalid"),
            ("wrong_top_level", replace("", "{}"), "diagnostic_evidence_invalid"),
            ("raw_exception", replace("", "[\"Traceback: secret\"]"), "diagnostic_evidence_invalid"),
            ("traceback_field", replace("", "[{\"traceback\":\"secret\"}]"), "diagnostic_evidence_invalid"),
            ("path_field", replace("", "[{\"path\":\"/private\"}]"), "diagnostic_evidence_invalid"),
            ("command_field", replace("", "[{\"command\":\"secret\"}]"), "diagnostic_evidence_invalid"),
            ("private_field", replace("", "[{\"private_content\":\"secret\"}]"), "diagnostic_evidence_invalid"),
            ("invalid_phase", replace("", "[{\"failure_phase\":\"bad\"}]"), "diagnostic_evidence_invalid"),
            ("invalid_operation", replace("", "[{\"failure_operation\":\"bad\"}]"), "diagnostic_evidence_invalid"),
            ("invalid_checkpoint", replace("", "[{\"failure_checkpoint\":\"bad\"}]"), "diagnostic_evidence_invalid"),
            ("invalid_code", replace("", "[{\"failure_code\":\"bad\"}]"), "diagnostic_evidence_invalid"),
            ("invalid_exception", replace("", "[{\"failure_exception_category\":\"bad\"}]"), "diagnostic_evidence_invalid"),
            ("invalid_cleanup", replace("", "[{\"cleanup_status\":\"bad\"}]"), "diagnostic_evidence_invalid"),
            ("invalid_format", replace("", "[{\"format_category\":\"bad\"}]"), "diagnostic_evidence_invalid"),
            ("progress_type", replace("", "[{\"adapter_invocation_entered\":1}]"), "diagnostic_evidence_invalid"),
            ("nested_parity", lambda raw, c: c.execute("UPDATE stage77_report_job_events SET payload_json='{}' WHERE job_id=(SELECT id FROM stage77_report_jobs WHERE retry_of_job_id IS NOT NULL) AND event_type='terminal'"), "diagnostic_evidence_invalid"),
            ("missing_operation", replace("", "[{\"failure_phase\":\"rendering\"}]"), "diagnostic_evidence_invalid"),
            ("non_monotonic", replace("", "[{\"failure_phase\":\"rendering\",\"failure_operation\":\"renderer_invocation\",\"failure_checkpoint\":\"entered\",\"failure_code\":\"governed_report_renderer_failed\",\"failure_exception_category\":\"unexpected_error\",\"cleanup_status\":\"unknown\",\"adapter_invocation_entered\":true,\"adapter_process_started\":false,\"adapter_result_received\":true,\"format_category\":\"multiple\"}]"), "diagnostic_evidence_invalid"),
            ("partial_transitional", replace("", "[{\"failure_phase\":\"rendering\"}]"), "diagnostic_evidence_invalid"),
            ("partial_legacy", replace("", "[\"governed_report_generation_validation_failed\"]"), "diagnostic_evidence_invalid"),
            ("current_as_transitional", replace("", current_attempt), "diagnostic_evidence_invalid"),
            ("transitional_as_current", replace("", recovery.canonical_json([{**diagnostics.TRANSITIONAL_DIAGNOSTIC, "failure_operation": "adapter_launch"}])), "diagnostic_evidence_invalid"),
        ]
        for name, mutator, expected in malformed:
            with self.subTest(case=name):
                self.tearDown(); self.setUp()
                self._assert_historical_rejection(job2_attempt(mutator), expected)

    def test_batch3b2_positive_strict_current_contract(self):
        bundle, live_db, point_id = self._historical_reconstruction_fixture()
        manifest = json.loads((bundle / "manifest.json").read_text())
        self.assertEqual(manifest["diagnostic_evidence"][0]["diagnostic_contract_version"], "current_diagnostic_contract_v1")
        result = recovery.reconstruct_recovery_point_evidence(database_path=live_db, recovery_root=self.recovery_root, recovery_point_id=point_id, actor="admin", rationale="bounded reconstruction", acknowledged=True, idempotency_key="batch3b2-current", approved_root=self.root)
        replay = recovery.reconstruct_recovery_point_evidence(database_path=live_db, recovery_root=self.recovery_root, recovery_point_id=point_id, actor="admin", rationale="bounded reconstruction", acknowledged=True, idempotency_key="batch3b2-current", approved_root=self.root)
        self.assertEqual(result["id"], replay["id"])

    def _topology_rejection(self, mutate, expected="retry_topology_mismatch"):
        bundle, live_db, point_id = self._historical_reconstruction_fixture()
        manifest = json.loads((bundle / "manifest.json").read_text())
        self._mutate_archived_database(bundle, manifest, mutate)
        with self.assertRaisesRegex(ValueError, expected):
            recovery.reconstruct_recovery_point_evidence(database_path=live_db, recovery_root=self.recovery_root, recovery_point_id=point_id, actor="admin", rationale="bounded reconstruction", acknowledged=True, idempotency_key="batch3b3-topology", approved_root=self.root)
        with self.assertRaisesRegex(ValueError, expected):
            recovery.reconstruct_recovery_point_evidence(database_path=live_db, recovery_root=self.recovery_root, recovery_point_id=point_id, actor="admin", rationale="bounded reconstruction", acknowledged=True, idempotency_key="batch3b3-topology", approved_root=self.root)

    @staticmethod
    def _successor_id(conn):
        return int(conn.execute("SELECT id FROM stage77_report_jobs WHERE retry_of_job_id IS NOT NULL").fetchone()[0])

    def test_batch3b3_case_19_retry_link_count_mismatch(self):
        cases = [
            ("zero", lambda c, m: m.__setitem__("retry_link_count", 0)),
            ("two", lambda c, m: m.__setitem__("retry_link_count", 2)),
            ("omitted", lambda c, m: m.pop("retry_link_count")),
            ("string", lambda c, m: m.__setitem__("retry_link_count", "1")),
            ("boolean", lambda c, m: m.__setitem__("retry_link_count", True)),
            ("negative", lambda c, m: m.__setitem__("retry_link_count", -1)),
            ("numeric_string", lambda c, m: m.__setitem__("retry_link_count", "01")),
            ("removed_link", lambda c, m: c.execute("UPDATE stage77_report_jobs SET retry_of_job_id=NULL WHERE retry_of_job_id IS NOT NULL")),
            ("additional_claim", lambda c, m: m.__setitem__("retry_link_count", 2)),
        ]
        for name, mutation in cases:
            with self.subTest(case=name):
                self.tearDown(); self.setUp()
                expected = "manifest_invalid" if name in {"omitted", "string", "boolean", "negative", "numeric_string"} else ("diagnostic_evidence_invalid" if name == "removed_link" else "retry_topology_mismatch")
                self._topology_rejection(mutation, expected)

    def test_batch3b3_case_20_retry_topology_digest_mismatch(self):
        cases = [
            ("changed_hex", lambda c, m: m.__setitem__("retry_link_state_digest", "0" + m["retry_link_state_digest"][1:])),
            ("uppercase", lambda c, m: m.__setitem__("retry_link_state_digest", m["retry_link_state_digest"].upper())),
            ("truncated", lambda c, m: m.__setitem__("retry_link_state_digest", m["retry_link_state_digest"][:-1])),
            ("overlength", lambda c, m: m.__setitem__("retry_link_state_digest", m["retry_link_state_digest"] + "0")),
            ("nonhex", lambda c, m: m.__setitem__("retry_link_state_digest", "g" * 64)),
            ("wrong_type", lambda c, m: m.__setitem__("retry_link_state_digest", 7)),
            ("omitted", lambda c, m: m.pop("retry_link_state_digest")),
            ("unrelated", lambda c, m: m.__setitem__("retry_link_state_digest", recovery.digest_bytes(b"unrelated"))),
            ("physical_order", lambda c, m: c.execute("VACUUM")),
            ("semantic_change", lambda c, m: c.execute("UPDATE stage77_report_jobs SET governed_action='enqueue_generation' WHERE retry_of_job_id IS NOT NULL")),
        ]
        for name, mutation in cases:
            with self.subTest(case=name):
                self.tearDown(); self.setUp()
                if name == "physical_order":
                    bundle, live_db, point_id = self._historical_reconstruction_fixture()
                    archived = sqlite3.connect(bundle / "database.sqlite3")
                    archived.execute("VACUUM")
                    archived.close()
                    manifest = json.loads((bundle / "manifest.json").read_text())
                    self._refresh_archived_database_binding(bundle, manifest)
                    result = recovery.reconstruct_recovery_point_evidence(database_path=live_db, recovery_root=self.recovery_root, recovery_point_id=point_id, actor="admin", rationale="bounded reconstruction", acknowledged=True, idempotency_key="batch3b3-order", approved_root=self.root)
                    self.assertEqual(result["state"], "finalized")
                else:
                    expected = "manifest_invalid" if name in {"uppercase", "truncated", "overlength", "nonhex", "wrong_type", "omitted"} else ("retry_topology_mismatch" if name in {"changed_hex", "unrelated"} else "diagnostic_evidence_invalid")
                    self._topology_rejection(mutation, expected)

    def test_batch3b3_case_21_orphan_or_invalid_link_identity(self):
        cases = [
            ("missing_predecessor", lambda c, m: c.execute("UPDATE stage77_report_jobs SET retry_of_job_id=999 WHERE retry_of_job_id IS NOT NULL"), "retry_topology_invalid"),
            ("missing_successor", lambda c, m: c.execute("DELETE FROM stage77_report_jobs WHERE retry_of_job_id IS NOT NULL"), "foreign_key_check_failed"),
            ("null_predecessor", lambda c, m: c.execute("UPDATE stage77_report_jobs SET retry_of_job_id=NULL WHERE retry_of_job_id IS NOT NULL"), "diagnostic_evidence_invalid"),
            ("null_successor_reference", lambda c, m: c.execute("UPDATE stage77_report_jobs SET retry_of_job_id=NULL WHERE retry_of_job_id IS NOT NULL"), "diagnostic_evidence_invalid"),
            ("self_link", lambda c, m: c.execute("UPDATE stage77_report_jobs SET retry_of_job_id=id WHERE retry_of_job_id IS NOT NULL"), "retry_topology_invalid"),
            ("nonexistent_id", lambda c, m: c.execute("UPDATE stage77_report_jobs SET retry_of_job_id=999 WHERE retry_of_job_id IS NOT NULL"), "retry_topology_invalid"),
            ("deleted_predecessor", lambda c, m: c.execute("DELETE FROM stage77_report_jobs WHERE retry_of_job_id IS NULL"), "retry_topology_invalid"),
            ("manifest_only", lambda c, m: m.__setitem__("retry_link_count", 2), "retry_topology_mismatch"),
            ("unlinked_successor", lambda c, m: c.execute("UPDATE stage77_report_jobs SET governed_action='authorize_diagnostic_retry',retry_of_job_id=NULL WHERE retry_of_job_id IS NOT NULL"), "diagnostic_evidence_invalid"),
            ("separate_evidence_disagrees", lambda c, m: c.execute("UPDATE stage77_report_jobs SET retry_of_job_id=999 WHERE retry_of_job_id IS NOT NULL"), "retry_topology_invalid"),
        ]
        for name, mutation, expected in cases:
            with self.subTest(case=name):
                self.tearDown(); self.setUp(); self._topology_rejection(mutation, expected)

    def _insert_chain_job(self, conn, retry_of):
        conn.execute("INSERT INTO stage77_report_jobs (report_id,report_version_id,specification_digest,requested_formats_json,rendering_profile,template_version,publication_engine_version,requesting_actor,governed_action,requested_at,state,attempt_count,max_attempts,next_eligible_at,idempotency_key,retry_of_job_id,maintenance_epoch,schema_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (7, 11, "a" * 64, '["docx","html","pdf"]', "internal", "cde-internal-v1", "2.0.0", "nick", "authorize_diagnostic_retry", "2026-01-01T00:00:04Z", "failed_terminal", 1, 3, "2026-01-01T00:00:04Z", "stage77-chain", retry_of, 0, jobs.JOB_SCHEMA_VERSION))

    def test_batch3b3_case_22_retry_of_retry_chain(self):
        cases = [
            ("job3_to_job2", lambda c, m: self._insert_chain_job(c, self._successor_id(c))),
            ("job2_predecessor_has_predecessor", lambda c, m: c.execute("UPDATE stage77_report_jobs SET retry_of_job_id=2 WHERE id=(SELECT id FROM stage77_report_jobs WHERE retry_of_job_id IS NOT NULL)")),
            ("three_job_chain", lambda c, m: self._insert_chain_job(c, self._successor_id(c))),
            ("dual_role", lambda c, m: self._insert_chain_job(c, self._successor_id(c))),
            ("manifest_one_link", lambda c, m: (self._insert_chain_job(c, self._successor_id(c)), m.__setitem__("retry_link_count", 1))),
            ("recomputed_claim", lambda c, m: self._insert_chain_job(c, self._successor_id(c))),
        ]
        for name, mutation in cases:
            with self.subTest(case=name):
                self.tearDown(); self.setUp(); self._topology_rejection(mutation, "retry_topology_invalid")

    def test_batch3b3_case_23_multiple_successors(self):
        def add_successor(conn, _manifest):
            conn.execute("DROP INDEX idx_stage77_jobs_retry_predecessor")
            predecessor = conn.execute("SELECT id FROM stage77_report_jobs WHERE retry_of_job_id IS NULL").fetchone()[0]
            self._insert_chain_job(conn, predecessor)
        cases = [("two_successors", add_successor), ("alternate_key", add_successor), ("different_action", add_successor), ("terminal", add_successor), ("queued", add_successor), ("accurate_claim", add_successor), ("reverse_order", add_successor), ("duplicate_logical", add_successor)]
        for name, mutation in cases:
            with self.subTest(case=name):
                self.tearDown(); self.setUp(); self._topology_rejection(mutation, "retry_topology_invalid")

    def test_batch3b3_case_24_ownership_state_action_mismatch(self):
        cases = [
            ("successor_report", lambda c, m: c.execute("UPDATE stage77_report_jobs SET report_id=999 WHERE retry_of_job_id IS NOT NULL")),
            ("successor_version", lambda c, m: c.execute("UPDATE stage77_report_jobs SET report_version_id=999 WHERE retry_of_job_id IS NOT NULL")),
            ("predecessor_report", lambda c, m: c.execute("UPDATE stage77_report_jobs SET report_id=999 WHERE retry_of_job_id IS NULL")),
            ("predecessor_version", lambda c, m: c.execute("UPDATE stage77_report_jobs SET report_version_id=999 WHERE retry_of_job_id IS NULL")),
            ("predecessor_nonterminal", lambda c, m: c.execute("UPDATE stage77_report_jobs SET state='queued' WHERE retry_of_job_id IS NULL")),
            ("predecessor_wrong_terminal", lambda c, m: c.execute("UPDATE stage77_report_jobs SET state='cancelled' WHERE retry_of_job_id IS NULL")),
            ("successor_action", lambda c, m: c.execute("UPDATE stage77_report_jobs SET governed_action='enqueue_generation' WHERE retry_of_job_id IS NOT NULL")),
            ("successor_state", lambda c, m: c.execute("UPDATE stage77_report_jobs SET state='queued' WHERE retry_of_job_id IS NOT NULL")),
            ("diagnostic_ownership", lambda c, m: c.execute("UPDATE record_governed_report_generation_attempts SET version_id=999 WHERE idempotency_key='stage77-job-2'")),
            ("swapped_ownership", lambda c, m: c.execute("UPDATE stage77_report_jobs SET report_id=999,report_version_id=999 WHERE retry_of_job_id IS NOT NULL")),
            ("unchanged_manifest", lambda c, m: c.execute("UPDATE stage77_report_jobs SET governed_action='enqueue_generation' WHERE retry_of_job_id IS NOT NULL")),
            ("accurate_invalid_claim", lambda c, m: c.execute("UPDATE stage77_report_jobs SET governed_action='enqueue_generation' WHERE retry_of_job_id IS NOT NULL")),
        ]
        for name, mutation in cases:
            with self.subTest(case=name):
                expected = "diagnostic_evidence_mismatch" if name == "successor_state" else ("retry_topology_invalid" if name in {"predecessor_nonterminal", "predecessor_wrong_terminal"} else "diagnostic_evidence_invalid")
                self.tearDown(); self.setUp(); self._topology_rejection(mutation, expected)

    def test_batch3a_historical_negative_cases_1_to_12(self):
        cases = [
            ("unknown_contract", lambda b, m: (m.__setitem__("diagnostic_contract_version", "unknown"), self._rewrite_manifest(b, m)), "manifest_invalid"),
            ("missing_field", lambda b, m: (m.pop("diagnostic_evidence"), self._rewrite_manifest(b, m)), "manifest_invalid"),
            ("extra_field", lambda b, m: (m.__setitem__("unknown", True), self._rewrite_manifest(b, m)), "manifest_invalid"),
            ("duplicate_key", lambda b, m: ((b / "manifest.json").write_bytes(b'{"created_at":"a","created_at":"b"}'), (b / "manifest.sha256").write_text(recovery.digest_bytes(b'{"created_at":"a","created_at":"b"}') + "\n", encoding="ascii")), "manifest_invalid"),
            ("noncanonical", lambda b, m: ((b / "manifest.json").write_text(json.dumps(m, indent=2), encoding="utf-8"), (b / "manifest.sha256").write_text(recovery.digest_bytes((b / "manifest.json").read_bytes()) + "\n", encoding="ascii")), "manifest_invalid"),
            ("identity_mismatch", lambda b, m: (m.__setitem__("recovery_point_id", "0" * 32), self._rewrite_manifest(b, m)), "recovery_evidence_identity_invalid"),
            ("epoch_invalid", lambda b, m: (m.__setitem__("maintenance_epoch", True), self._rewrite_manifest(b, m)), "manifest_invalid"),
            ("manifest_digest", lambda b, m: (b / "manifest.sha256").write_text("0" * 64 + "\n", encoding="ascii"), "manifest_digest_mismatch"),
            ("database_digest", lambda b, m: self._append_bytes(b / "database.sqlite3", b"conflict"), "database_digest_mismatch"),
            ("integrity_failure", lambda b, m: ((b / "database.sqlite3").write_bytes(b"not-a-sqlite-database"), m.__setitem__("database", {"filename": "database.sqlite3", "size_bytes": len(b"not-a-sqlite-database"), "sha256": recovery.digest_bytes(b"not-a-sqlite-database")}), self._rewrite_manifest(b, m)), "sqlite_error"),
        ]
        for name, mutate, expected in cases:
            with self.subTest(case=name):
                self.tearDown()
                self.setUp()
                self._assert_historical_rejection(mutate, expected)

    def test_batch3a_historical_negative_case_11_foreign_key_failure(self):
        def mutate(bundle, manifest):
            database = bundle / "database.sqlite3"
            conn = sqlite3.connect(database)
            conn.execute("PRAGMA foreign_keys=OFF")
            conn.execute("INSERT INTO record_governed_report_versions(id,report_id,lifecycle_status) VALUES(9999,9999,'generated')")
            conn.commit()
            conn.close()
            data = database.read_bytes()
            manifest["database"] = {"filename": "database.sqlite3", "size_bytes": len(data), "sha256": recovery.digest_bytes(data)}
            self._rewrite_manifest(bundle, manifest)
        self._assert_historical_rejection(mutate, "foreign_key_check_failed")

    def test_batch3a_historical_negative_case_12_own_live_evidence_row(self):
        bundle, live_db, point_id = self._historical_reconstruction_fixture()
        source = sqlite3.connect(self.db)
        source.row_factory = sqlite3.Row
        evidence = source.execute("SELECT * FROM stage77_recovery_point_evidence WHERE recovery_point_id=?", (point_id,)).fetchone()
        event = source.execute("SELECT * FROM stage77_recovery_point_evidence_events WHERE evidence_id=?", (evidence["id"],)).fetchone()
        source.close()
        archived = sqlite3.connect(bundle / "database.sqlite3")
        columns = [row[1] for row in archived.execute("PRAGMA table_info(stage77_recovery_point_evidence)")]
        archived.execute("INSERT INTO stage77_recovery_point_evidence (%s) VALUES (%s)" % (", ".join(columns), ", ".join("?" for _ in columns)), tuple(evidence[column] for column in columns))
        event_columns = [row[1] for row in archived.execute("PRAGMA table_info(stage77_recovery_point_evidence_events)")]
        archived.execute("INSERT INTO stage77_recovery_point_evidence_events (%s) VALUES (%s)" % (", ".join(event_columns), ", ".join("?" for _ in event_columns)), tuple(event[column] for column in event_columns))
        archived.commit()
        archived.close()
        data = (bundle / "database.sqlite3").read_bytes()
        manifest = json.loads((bundle / "manifest.json").read_text())
        manifest["database"] = {"filename": "database.sqlite3", "size_bytes": len(data), "sha256": recovery.digest_bytes(data)}
        self._rewrite_manifest(bundle, manifest)
        with self.assertRaisesRegex(ValueError, "recovery_evidence_conflict"):
            recovery.reconstruct_recovery_point_evidence(database_path=live_db, recovery_root=self.recovery_root, recovery_point_id=point_id, actor="admin", rationale="bounded reconstruction", acknowledged=True, idempotency_key="batch3a-own", approved_root=self.root)

    def test_batch3a_conflicting_replay_is_rejected_without_mutation(self):
        _bundle, live_db, point_id = self._historical_reconstruction_fixture()
        first = recovery.reconstruct_recovery_point_evidence(database_path=live_db, recovery_root=self.recovery_root, recovery_point_id=point_id, actor="admin", rationale="bounded reconstruction", acknowledged=True, idempotency_key="batch3a-replay", approved_root=self.root)
        with self.assertRaisesRegex(ValueError, "recovery_evidence_conflict"):
            recovery.reconstruct_recovery_point_evidence(database_path=live_db, recovery_root=self.recovery_root, recovery_point_id=point_id, actor="admin", rationale="different bounded rationale", acknowledged=True, idempotency_key="batch3a-other", approved_root=self.root)
        check = sqlite3.connect(live_db)
        self.assertEqual(check.execute("SELECT COUNT(*) FROM stage77_recovery_point_evidence").fetchone()[0], 1)
        self.assertEqual(check.execute("SELECT COUNT(*) FROM stage77_recovery_point_evidence_events").fetchone()[0], 1)
        self.assertEqual(check.execute("SELECT id FROM stage77_recovery_point_evidence").fetchone()[0], first["id"])
        check.close()

    def test_batch3a_event_failure_rolls_back_recovery_evidence_row(self):
        _bundle, live_db, point_id = self._historical_reconstruction_fixture()
        live = sqlite3.connect(live_db)
        live.execute("CREATE TRIGGER fail_recovery_evidence_event BEFORE INSERT ON stage77_recovery_point_evidence_events BEGIN SELECT RAISE(ABORT, 'event_failure'); END")
        live.commit()
        live.close()
        with self.assertRaisesRegex(ValueError, "sqlite_error"):
            recovery.reconstruct_recovery_point_evidence(database_path=live_db, recovery_root=self.recovery_root, recovery_point_id=point_id, actor="admin", rationale="bounded reconstruction", acknowledged=True, idempotency_key="batch3a-event-failure", approved_root=self.root)
        check = sqlite3.connect(live_db)
        self.assertEqual(check.execute("SELECT COUNT(*) FROM stage77_recovery_point_evidence").fetchone()[0], 0)
        check.close()

    def test_later_post_snapshot_contains_prior_evidence_once(self):
        jobs.ensure_post_correction_tables(self.conn)
        first = recovery.capture_recovery_point(database_path=self.db, artifact_root=self.artifacts, recovery_root=self.recovery_root, approved_root=self.root, actor="admin", governed_action="capture", idempotency_key="point-1")
        second = recovery.capture_recovery_point(database_path=self.db, artifact_root=self.artifacts, recovery_root=self.recovery_root, approved_root=self.root, actor="admin", governed_action="capture", idempotency_key="point-2")
        self.assertNotEqual(first["recovery_point_id"], second["recovery_point_id"])
        manifest = json.loads((self.recovery_root / f"recovery-{second['recovery_point_id']}" / "manifest.json").read_text())
        self.assertEqual(len(manifest["persisted_prior_recovery_evidence"]), 1)
        self.assertEqual(manifest["persisted_prior_recovery_evidence"][0]["recovery_point_id"], first["recovery_point_id"])

    def test_capture_failure_after_evidence_validation_does_not_complete_or_persist(self):
        original = recovery._insert_recovery_evidence
        with patch.object(recovery, "_insert_recovery_evidence", side_effect=ValueError("recovery_evidence_conflict")):
            with self.assertRaisesRegex(recovery.RecoveryOperationFailure, "recovery_evidence_conflict") as raised:
                recovery.capture_recovery_point(database_path=self.db, artifact_root=self.artifacts, recovery_root=self.recovery_root, approved_root=self.root, actor="admin", governed_action="capture")
        self.assertEqual(raised.exception.phase, "validation")
        self.assertEqual(raised.exception.operation, "recovery_evidence_persistence")
        self.assertEqual(raised.exception.checkpoint, "starting")
        self.assertEqual(self.conn.execute("SELECT state FROM stage77_recovery_control WHERE singleton=1").fetchone()[0], "failed")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM stage77_recovery_point_evidence").fetchone()[0], 0)
        recovery._insert_recovery_evidence = original

    def _assert_first_capture_fault(self, checkpoint_name, expected_operation, expected_checkpoint, cleanup_failure=False):
        injector = recovery.CaptureFaultInjector(checkpoint_name)
        if cleanup_failure:
            cleanup_context = patch.object(recovery.shutil, "rmtree", side_effect=OSError("cleanup failure"))
        else:
            cleanup_context = None
        with (cleanup_context or patch.object(recovery.shutil, "rmtree", wraps=recovery.shutil.rmtree)):
            with self.assertRaises(recovery.RecoveryOperationFailure) as raised:
                recovery.capture_recovery_point(database_path=self.db, artifact_root=self.artifacts, recovery_root=self.root / "recovery", approved_root=self.root, actor="admin", governed_action="capture", fault_injector=injector)
        failure = raised.exception
        ordered = ["before_snapshot_creation", "during_snapshot_creation", "after_snapshot_before_database_digest", "during_sqlite_integrity_validation", "during_sqlite_foreign_key_validation", "after_current_evidence_before_manifest", "during_canonical_manifest_creation", "after_manifest_before_bundle_validation", "after_bundle_validation_before_live_evidence", "after_evidence_row_before_event", "after_evidence_event_before_completion", "during_final_staging_cleanup"]
        self.assertEqual(injector.entered, ordered[:ordered.index(checkpoint_name) + 1])
        self.assertEqual((failure.phase, failure.operation, failure.checkpoint, failure.code), ("capture" if checkpoint_name in {"before_snapshot_creation", "during_snapshot_creation"} else "validation", expected_operation, expected_checkpoint, "native_capture_fault_injected"))
        self.assertEqual(failure.cleanup_status, "failed" if cleanup_failure else "completed")
        self.assertEqual(failure.maintenance_status, "failed")
        self.conn.close()
        self.conn = sqlite3.connect(self.db)
        self.conn.row_factory = sqlite3.Row
        self.assertEqual(self.conn.execute("SELECT state FROM stage77_recovery_control WHERE singleton=1").fetchone()[0], "failed")
        self.assertFalse(recovery.recovery_allows_claim(self.conn))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM stage77_recovery_point_evidence").fetchone()[0], 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM stage77_recovery_point_evidence_events").fetchone()[0], 0)
        self.assertFalse(any(self.recovery_root.glob("recovery-*")))
        stage_root = self.root / "recovery" / ".stage"
        if not cleanup_failure:
            self.assertFalse(stage_root.exists() and any(stage_root.iterdir()))

    def test_capture_fault_before_snapshot_creation(self):
        self._assert_first_capture_fault("before_snapshot_creation", "staging_directory", "creating")

    def test_capture_fault_during_snapshot_creation(self):
        self._assert_first_capture_fault("during_snapshot_creation", "online_backup_execution", "progress")

    def test_capture_fault_after_snapshot_before_database_digest(self):
        self._assert_first_capture_fault("after_snapshot_before_database_digest", "database_integrity_check", "starting")

    def test_capture_fault_during_sqlite_integrity_validation(self):
        self._assert_first_capture_fault("during_sqlite_integrity_validation", "database_integrity_check", "starting")

    def test_capture_fault_during_sqlite_foreign_key_validation(self):
        self._assert_first_capture_fault("during_sqlite_foreign_key_validation", "foreign_key_check", "starting")

    def test_capture_fault_after_current_evidence_before_manifest(self):
        jobs.ensure_post_correction_tables(self.conn)
        self._assert_first_capture_fault("after_current_evidence_before_manifest", "manifest_database_reads", "starting")

    def test_capture_fault_during_canonical_manifest_creation(self):
        jobs.ensure_post_correction_tables(self.conn)
        self._assert_first_capture_fault("during_canonical_manifest_creation", "manifest_write", "starting")

    def test_capture_fault_after_manifest_before_bundle_validation(self):
        jobs.ensure_post_correction_tables(self.conn)
        self._assert_first_capture_fault("after_manifest_before_bundle_validation", "bundle_validation", "starting")

    def _assert_early_capture_restart(self, checkpoint_name, expected_operation, expected_checkpoint):
        jobs.ensure_post_correction_tables(self.conn)
        sentinel = self.root / "unrelated-sentinel.txt"
        sentinel.write_text("preserve", encoding="ascii")
        injector = recovery.CaptureFaultInjector(checkpoint_name)
        with self.assertRaises(recovery.RecoveryOperationFailure) as raised:
            recovery.capture_recovery_point(
                database_path=self.db,
                artifact_root=self.artifacts,
                recovery_root=self.recovery_root,
                approved_root=self.root,
                actor="admin",
                governed_action="capture",
                fault_injector=injector,
            )
        failure = raised.exception
        order = [
            "before_snapshot_creation",
            "during_snapshot_creation",
            "after_snapshot_before_database_digest",
            "during_sqlite_integrity_validation",
            "during_sqlite_foreign_key_validation",
            "after_current_evidence_before_manifest",
            "during_canonical_manifest_creation",
            "after_manifest_before_bundle_validation",
        ]
        self.assertEqual(injector.entered, order[:order.index(checkpoint_name) + 1])
        self.assertEqual(
            (failure.phase, failure.operation, failure.checkpoint, failure.code),
            ("capture" if checkpoint_name in {"before_snapshot_creation", "during_snapshot_creation"} else "validation", expected_operation, expected_checkpoint, "native_capture_fault_injected"),
        )
        self.assertEqual(failure.cleanup_status, "completed")
        self.assertEqual(failure.maintenance_status, "failed")
        self.assertEqual(sentinel.read_text(encoding="ascii"), "preserve")
        self.assertFalse(any(self.recovery_root.glob("recovery-*")))
        stage_root = self.recovery_root / ".stage"
        self.assertFalse(stage_root.exists() and any(stage_root.iterdir()))
        recovery_event_count = self.conn.execute("SELECT COUNT(*) FROM stage77_recovery_events").fetchone()[0]
        self.assertGreaterEqual(recovery_event_count, 1)

        # Fresh-process simulation: initialization is allowed to check schema,
        # but must not resume or normalize a failed capture.
        self.conn.close()
        self.conn = sqlite3.connect(self.db)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        jobs.ensure_job_tables(self.conn)
        recovery.ensure_recovery_tables(self.conn)
        state = self.conn.execute("SELECT state, worker_drained FROM stage77_recovery_control WHERE singleton=1").fetchone()
        self.assertEqual(tuple(state), ("failed", 0))
        self.assertFalse(recovery.recovery_allows_claim(self.conn))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM stage77_recovery_point_evidence").fetchone()[0], 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM stage77_recovery_point_evidence_events").fetchone()[0], 0)
        self.assertEqual(self.conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        self.assertEqual(self.conn.execute("PRAGMA foreign_key_check").fetchall(), [])
        # A second reopen must produce the same bounded durable result and no
        # implicit event, evidence insertion, or unsafe reconciliation.
        self.conn.close()
        self.conn = sqlite3.connect(self.db)
        self.conn.row_factory = sqlite3.Row
        state_again = self.conn.execute("SELECT state, worker_drained FROM stage77_recovery_control WHERE singleton=1").fetchone()
        self.assertEqual(tuple(state_again), ("failed", 0))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM stage77_recovery_events").fetchone()[0], recovery_event_count)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM stage77_recovery_point_evidence").fetchone()[0], 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM stage77_recovery_point_evidence_events").fetchone()[0], 0)
        self.assertEqual(sentinel.read_text(encoding="ascii"), "preserve")

    def test_restart_case_1_before_snapshot_creation(self):
        self._assert_early_capture_restart("before_snapshot_creation", "staging_directory", "creating")

    def test_restart_case_2_during_snapshot_creation(self):
        self._assert_early_capture_restart("during_snapshot_creation", "online_backup_execution", "progress")

    def test_restart_case_3_after_snapshot_before_database_digest(self):
        self._assert_early_capture_restart("after_snapshot_before_database_digest", "database_integrity_check", "starting")

    def test_restart_case_4_during_sqlite_integrity_validation(self):
        self._assert_early_capture_restart("during_sqlite_integrity_validation", "database_integrity_check", "starting")

    def test_restart_case_5_during_sqlite_foreign_key_validation(self):
        self._assert_early_capture_restart("during_sqlite_foreign_key_validation", "foreign_key_check", "starting")

    def test_restart_case_6_after_current_evidence_before_manifest(self):
        self._assert_early_capture_restart("after_current_evidence_before_manifest", "manifest_database_reads", "starting")

    def test_restart_case_7_during_canonical_manifest_creation(self):
        self._assert_early_capture_restart("during_canonical_manifest_creation", "manifest_write", "starting")

    def test_restart_case_8_after_manifest_before_bundle_validation(self):
        self._assert_early_capture_restart("after_manifest_before_bundle_validation", "bundle_validation", "starting")

    def test_capture_fault_after_bundle_validation_before_live_evidence(self):
        jobs.ensure_post_correction_tables(self.conn)
        self._assert_first_capture_fault("after_bundle_validation_before_live_evidence", "recovery_evidence_persistence", "starting")

    def test_capture_fault_after_evidence_row_before_event_is_atomic(self):
        jobs.ensure_post_correction_tables(self.conn)
        self._assert_first_capture_fault("after_evidence_row_before_event", "recovery_evidence_persistence", "starting")

    def _assert_durable_capture_fault(self, checkpoint_name):
        jobs.ensure_post_correction_tables(self.conn)
        injector = recovery.CaptureFaultInjector(checkpoint_name)
        with self.assertRaises(recovery.RecoveryOperationFailure) as raised:
            recovery.capture_recovery_point(database_path=self.db, artifact_root=self.artifacts, recovery_root=self.recovery_root, approved_root=self.root, actor="admin", governed_action="capture", fault_injector=injector)
        failure = raised.exception
        ordered = ["before_snapshot_creation", "during_snapshot_creation", "after_snapshot_before_database_digest", "during_sqlite_integrity_validation", "during_sqlite_foreign_key_validation", "after_current_evidence_before_manifest", "during_canonical_manifest_creation", "after_manifest_before_bundle_validation", "after_bundle_validation_before_live_evidence", "after_evidence_row_before_event", "after_evidence_event_before_completion", "during_final_staging_cleanup"]
        self.assertEqual(injector.entered, ordered[:ordered.index(checkpoint_name) + 1])
        expected_operation = "staging_directory" if checkpoint_name == "during_final_staging_cleanup" else "completion_event_write"
        self.assertEqual((failure.phase, failure.operation, failure.checkpoint, failure.code), ("completion", expected_operation, "starting", "native_capture_fault_injected"))
        self.assertEqual(failure.maintenance_status, "unknown")
        self.conn.close()
        self.conn = sqlite3.connect(self.db)
        self.conn.row_factory = sqlite3.Row
        self.assertEqual(self.conn.execute("SELECT state FROM stage77_recovery_control WHERE singleton=1").fetchone()[0], "capturing")
        self.assertFalse(recovery.recovery_allows_claim(self.conn))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM stage77_recovery_point_evidence").fetchone()[0], 1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM stage77_recovery_point_evidence_events").fetchone()[0], 1)
        reconciled = recovery.reconcile_interrupted_recovery(database_path=self.db, recovery_root=self.recovery_root, approved_root=self.root, actor="admin")
        self.assertEqual(reconciled["state"], "completed")
        repeated = recovery.reconcile_interrupted_recovery(database_path=self.db, recovery_root=self.recovery_root, approved_root=self.root, actor="admin")
        self.assertEqual(repeated, reconciled)
        self.assertTrue(recovery.recovery_allows_claim(self.conn))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM stage77_recovery_point_evidence").fetchone()[0], 1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM stage77_recovery_point_evidence_events").fetchone()[0], 1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM stage77_recovery_events WHERE event_type='recovery_reconciled_completed'").fetchone()[0], 1)
        self.assertFalse((self.recovery_root / ".stage").exists())

    def test_capture_fault_after_evidence_event_reconciles_once(self):
        self._assert_durable_capture_fault("after_evidence_event_before_completion")

    def test_capture_fault_during_final_staging_cleanup_reconciles_once(self):
        self._assert_durable_capture_fault("during_final_staging_cleanup")

    def test_conflicting_bundle_blocks_durable_reconciliation(self):
        jobs.ensure_post_correction_tables(self.conn)
        injector = recovery.CaptureFaultInjector("after_evidence_event_before_completion")
        with self.assertRaises(recovery.RecoveryOperationFailure):
            recovery.capture_recovery_point(database_path=self.db, artifact_root=self.artifacts, recovery_root=self.recovery_root, approved_root=self.root, actor="admin", governed_action="capture", fault_injector=injector)
        bundle = next(self.recovery_root.glob("recovery-*"))
        (bundle / "manifest.sha256").write_text("0" * 64 + "\n")
        with self.assertRaisesRegex(ValueError, "manifest_digest_mismatch"):
            recovery.reconcile_interrupted_recovery(database_path=self.db, recovery_root=self.recovery_root, approved_root=self.root, actor="admin")
        self.assertEqual(self.conn.execute("SELECT state FROM stage77_recovery_control WHERE singleton=1").fetchone()[0], "capturing")

    def test_restart_case_9_validated_bundle_without_live_evidence_remains_fenced(self):
        jobs.ensure_post_correction_tables(self.conn)
        self._assert_first_capture_fault("after_bundle_validation_before_live_evidence", "recovery_evidence_persistence", "starting")
        self.assertFalse(recovery.recovery_allows_claim(self.conn))
        self.assertEqual(self.conn.execute("SELECT state FROM stage77_recovery_control WHERE singleton=1").fetchone()[0], "failed")

    def test_restart_case_10_row_before_event_rolls_back_before_reopen(self):
        jobs.ensure_post_correction_tables(self.conn)
        self._assert_first_capture_fault("after_evidence_row_before_event", "recovery_evidence_persistence", "starting")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM stage77_recovery_point_evidence_events").fetchone()[0], 0)

    def _create_durable_restart_boundary(self):
        jobs.ensure_post_correction_tables(self.conn)
        injector = recovery.CaptureFaultInjector("after_evidence_event_before_completion")
        with self.assertRaises(recovery.RecoveryOperationFailure):
            recovery.capture_recovery_point(database_path=self.db, artifact_root=self.artifacts, recovery_root=self.recovery_root, approved_root=self.root, actor="admin", governed_action="capture", fault_injector=injector)
        bundle = next(self.recovery_root.glob("recovery-*"))
        self.conn.close()
        self.conn = sqlite3.connect(self.db)
        self.conn.row_factory = sqlite3.Row
        return bundle

    def test_restart_case_11_durable_row_event_reconciles_once_after_reopen(self):
        self._assert_durable_capture_fault("after_evidence_event_before_completion")

    def test_restart_case_12_cleanup_interruption_reconciles_once_after_reopen(self):
        self._assert_durable_capture_fault("during_final_staging_cleanup")

    def test_restart_case_13_conflicting_durable_evidence_remains_fenced(self):
        for mutation, expected_code in (("manifest", "manifest_digest_mismatch"), ("database", "database_digest_mismatch"), ("event", "recovery_evidence_event_invalid")):
            with self.subTest(mutation=mutation):
                self.tearDown()
                self.setUp()
                bundle = self._create_durable_restart_boundary()
                if mutation == "manifest":
                    (bundle / "manifest.sha256").write_text("0" * 64 + "\n", encoding="ascii")
                elif mutation == "database":
                    with (bundle / "database.sqlite3").open("ab") as stream:
                        stream.write(b"conflict")
                else:
                    self.conn.execute("DROP TRIGGER stage77_recovery_evidence_events_no_update")
                    self.conn.execute("UPDATE stage77_recovery_point_evidence_events SET payload_json='{}'")
                    self.conn.commit()
                with self.assertRaisesRegex(ValueError, expected_code):
                    recovery.reconcile_interrupted_recovery(database_path=self.db, recovery_root=self.recovery_root, approved_root=self.root, actor="admin")
                self.assertEqual(self.conn.execute("SELECT state FROM stage77_recovery_control WHERE singleton=1").fetchone()[0], "capturing")
                self.assertFalse(recovery.recovery_allows_claim(self.conn))
                self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM stage77_recovery_point_evidence").fetchone()[0], 1)
                self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM stage77_recovery_point_evidence_events").fetchone()[0], 1)

    def test_restart_case_14_two_restarts_do_not_advance_durable_state(self):
        bundle = self._create_durable_restart_boundary()
        before = tuple(self.conn.execute("SELECT state, maintenance_epoch FROM stage77_recovery_control WHERE singleton=1").fetchone())
        counts = tuple(self.conn.execute("SELECT (SELECT COUNT(*) FROM stage77_recovery_point_evidence), (SELECT COUNT(*) FROM stage77_recovery_point_evidence_events), (SELECT COUNT(*) FROM stage77_recovery_events)").fetchone())
        self.conn.close()
        self.conn = sqlite3.connect(self.db)
        self.conn.row_factory = sqlite3.Row
        recovery.ensure_recovery_tables(self.conn)
        self.conn.close()
        self.conn = sqlite3.connect(self.db)
        self.conn.row_factory = sqlite3.Row
        recovery.ensure_recovery_tables(self.conn)
        self.assertEqual(tuple(self.conn.execute("SELECT state, maintenance_epoch FROM stage77_recovery_control WHERE singleton=1").fetchone()), before)
        self.assertEqual(tuple(self.conn.execute("SELECT (SELECT COUNT(*) FROM stage77_recovery_point_evidence), (SELECT COUNT(*) FROM stage77_recovery_point_evidence_events), (SELECT COUNT(*) FROM stage77_recovery_events)").fetchone()), counts)
        self.assertFalse(recovery.recovery_allows_claim(self.conn))
        self.assertTrue(bundle.exists())

    def test_restart_case_15_valid_reconciliation_is_idempotent(self):
        bundle = self._create_durable_restart_boundary()
        first = recovery.reconcile_interrupted_recovery(database_path=self.db, recovery_root=self.recovery_root, approved_root=self.root, actor="admin")
        event_count = self.conn.execute("SELECT COUNT(*) FROM stage77_recovery_events").fetchone()[0]
        second = recovery.reconcile_interrupted_recovery(database_path=self.db, recovery_root=self.recovery_root, approved_root=self.root, actor="admin")
        self.assertEqual(second, first)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM stage77_recovery_events").fetchone()[0], event_count)
        self.assertEqual(self.conn.execute("SELECT state FROM stage77_recovery_control WHERE singleton=1").fetchone()[0], "completed")
        self.assertTrue(recovery.recovery_allows_claim(self.conn))
        self.assertTrue(bundle.exists())

    def test_restart_case_16_completed_reopen_is_readiness_noop(self):
        jobs.ensure_post_correction_tables(self.conn)
        result = recovery.capture_recovery_point(database_path=self.db, artifact_root=self.artifacts, recovery_root=self.recovery_root, approved_root=self.root, actor="admin", governed_action="capture")
        event_count = self.conn.execute("SELECT COUNT(*) FROM stage77_recovery_events").fetchone()[0]
        self.conn.close()
        self.conn = sqlite3.connect(self.db)
        self.conn.row_factory = sqlite3.Row
        recovery.ensure_recovery_tables(self.conn)
        self.conn.close()
        self.conn = sqlite3.connect(self.db)
        self.conn.row_factory = sqlite3.Row
        recovery.ensure_recovery_tables(self.conn)
        repeated = recovery.reconcile_interrupted_recovery(database_path=self.db, recovery_root=self.recovery_root, approved_root=self.root, actor="admin")
        self.assertEqual(repeated["state"], "completed")
        self.assertEqual(repeated["recovery_point_id"], result["recovery_point_id"])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM stage77_recovery_events").fetchone()[0], event_count)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM stage77_recovery_point_evidence").fetchone()[0], 1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM stage77_recovery_point_evidence_events").fetchone()[0], 1)
        self.assertFalse((self.recovery_root / ".stage").exists())
        self.assertTrue(recovery.recovery_allows_claim(self.conn))

    def test_new_capture_faults_preserve_primary_failure_when_cleanup_fails(self):
        for checkpoint_name, expected_operation, expected_checkpoint in (
            ("during_sqlite_foreign_key_validation", "foreign_key_check", "starting"),
            ("after_current_evidence_before_manifest", "manifest_database_reads", "starting"),
            ("during_canonical_manifest_creation", "manifest_write", "starting"),
            ("after_manifest_before_bundle_validation", "bundle_validation", "starting"),
        ):
            with self.subTest(checkpoint=checkpoint_name):
                # Each subcase gets a fresh fixture so cleanup failure cannot
                # contaminate the next checkpoint assertion.
                self.tearDown()
                self.setUp()
                jobs.ensure_post_correction_tables(self.conn)
                self._assert_first_capture_fault(checkpoint_name, expected_operation, expected_checkpoint, cleanup_failure=True)

    def test_capture_fault_positive_control_traverses_all_twelve_checkpoints(self):
        jobs.ensure_post_correction_tables(self.conn)
        injector = recovery.CaptureFaultInjector()
        result = recovery.capture_recovery_point(database_path=self.db, artifact_root=self.artifacts, recovery_root=self.recovery_root, approved_root=self.root, actor="admin", governed_action="capture", fault_injector=injector)
        self.assertEqual(injector.entered, ["before_snapshot_creation", "during_snapshot_creation", "after_snapshot_before_database_digest", "during_sqlite_integrity_validation", "during_sqlite_foreign_key_validation", "after_current_evidence_before_manifest", "during_canonical_manifest_creation", "after_manifest_before_bundle_validation", "after_bundle_validation_before_live_evidence", "after_evidence_row_before_event", "after_evidence_event_before_completion", "during_final_staging_cleanup"])
        self.assertEqual(result["state"], "completed")
        self.assertTrue(recovery.recovery_allows_claim(self.conn))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM stage77_recovery_point_evidence").fetchone()[0], 1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM stage77_recovery_point_evidence_events").fetchone()[0], 1)
        bundle = self.recovery_root / f"recovery-{result['recovery_point_id']}"
        manifest = json.loads((bundle / "manifest.json").read_text())
        self.assertIn("current_recovery_manifest_evidence", manifest)
        self.assertEqual(recovery.validate_recovery_bundle(bundle)["state"], "valid")

    def test_symlink_artifact_fails_closed(self):
        self.artifact.unlink()
        self.artifact.symlink_to(self.root / "outside")
        (self.root / "outside").write_bytes(self.bytes)
        with self.assertRaisesRegex(ValueError, "artifact_invalid"):
            recovery.capture_recovery_point(database_path=self.db, artifact_root=self.artifacts, recovery_root=self.recovery_root, approved_root=self.root, actor="admin", governed_action="capture")

    def test_restore_rejects_symlinked_approved_root_and_restore_root(self):
        bundle = self._bundle()
        real = self.root / "real-restore"
        real.mkdir()
        alias = self.root / "restore-alias"
        alias.symlink_to(real, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "restore_target_invalid"):
            self._restore(bundle, real / "records.db", real / "artifacts", restore_root=alias)
        with self.assertRaisesRegex(ValueError, "restore_target_invalid"):
            recovery.restore_recovery_point(bundle_path=bundle, restore_root=real, database_target=real / "records.db", artifact_root_target=real / "artifacts", live_database=self.db, live_artifact_root=self.artifacts, live_recovery_root=self.recovery_root, actor="admin", governed_action="restore", approved_root=alias)

    def test_restore_rejects_resolving_and_dangling_symlink_leaves(self):
        bundle = self._bundle()
        restore = self.root / "restore"
        restore.mkdir()
        outside = self.root / "outside.db"
        outside.write_bytes(b"outside")
        resolving = restore / "records.db"
        resolving.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "restore_target_invalid"):
            self._restore(bundle, resolving, restore / "artifacts")
        resolving.unlink()
        resolving.symlink_to(restore / "missing.db")
        with self.assertRaisesRegex(ValueError, "restore_target_invalid"):
            self._restore(bundle, resolving, restore / "artifacts")

    def test_restore_rejects_symlinked_intermediate_parent_and_chain(self):
        bundle = self._bundle()
        restore = self.root / "restore"
        restore.mkdir()
        real_parent = self.root / "real-parent"
        real_parent.mkdir()
        parent = restore / "parent"
        parent.symlink_to(real_parent, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "restore_target_invalid"):
            self._restore(bundle, parent / "records.db", restore / "artifacts")
        chain = restore / "chain"
        chain.symlink_to(parent, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "restore_target_invalid"):
            self._restore(bundle, restore / "records2.db", chain / "artifacts")

    def test_restore_rejects_relative_traversal_and_normalization_variants(self):
        bundle = self._bundle()
        restore = self.root / "restore"
        restore.mkdir()
        with self.assertRaisesRegex(ValueError, "restore_target_invalid"):
            self._restore(bundle, "records.db", restore / "artifacts")
        with self.assertRaisesRegex(ValueError, "restore_target_invalid"):
            self._restore(bundle, str(restore) + "/../records.db", restore / "artifacts")
        with self.assertRaisesRegex(ValueError, "restore_target_invalid"):
            self._restore(bundle, str(restore) + "//records.db", restore / "artifacts")

    def test_restore_rejects_live_aliases_overlap_hardlinks_and_wrong_types(self):
        bundle = self._bundle()
        restore = self.root / "restore"
        restore.mkdir()
        live_alias = restore / "live-alias"
        live_alias.symlink_to(self.db)
        with self.assertRaisesRegex(ValueError, "restore_target_invalid"):
            self._restore(bundle, live_alias, restore / "artifacts")
        live_artifact_alias = restore / "artifact-alias"
        live_artifact_alias.symlink_to(self.artifacts, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "restore_target_invalid"):
            self._restore(bundle, restore / "records.db", live_artifact_alias)
        with self.assertRaises((ValueError, OSError)):
            self._restore(bundle, restore / "records.db", restore / "records.db" / "artifacts")
        hardlink = restore / "hardlink.db"
        os.link(self.db, hardlink)
        with self.assertRaisesRegex(ValueError, "restore_target_invalid"):
            self._restore(bundle, hardlink, restore / "artifacts")
        wrong_type = restore / "wrong-type"
        wrong_type.mkdir()
        with self.assertRaisesRegex(ValueError, "restore_target_invalid"):
            self._restore(bundle, wrong_type, restore / "artifacts2")

    def test_restore_revalidates_a_target_replaced_after_initial_validation(self):
        bundle = self._bundle()
        restore = self.root / "restore"
        restore.mkdir()
        target = restore / "records.db"
        recovery._restore_target(target, restore, {self.db.resolve(), self.artifacts.resolve(), self.recovery_root.resolve()})
        target.symlink_to(self.db)
        with self.assertRaisesRegex(ValueError, "restore_target_invalid"):
            recovery._restore_target(target, restore, {self.db.resolve(), self.artifacts.resolve(), self.recovery_root.resolve()})
        target.unlink()
        self.assertEqual(self._restore(bundle, target, restore / "artifacts")['state'], "restore_ready")

    def test_restore_rejects_parent_swap_before_promotion(self):
        bundle = self._bundle()
        restore = self.root / "restore"
        restore.mkdir()
        parent = restore / "parent"
        parent.mkdir()
        target = parent / "records.db"
        recovery._restore_target(target, restore, {self.db.resolve(), self.artifacts.resolve(), self.recovery_root.resolve()})
        parent.rename(restore / "parent-old")
        parent.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "restore_target_invalid"):
            self._restore(bundle, target, restore / "artifacts")

    def test_restore_promotion_does_not_overwrite_a_leaf_created_after_validation(self):
        bundle = self._bundle()
        restore = self.root / "restore"
        restore.mkdir()
        target = restore / "records.db"
        target.write_bytes(b"unrelated")
        with self.assertRaisesRegex(ValueError, "restore_target_invalid"):
            self._restore(bundle, target, restore / "artifacts")
        self.assertEqual(target.read_bytes(), b"unrelated")

    def test_restore_cleanup_does_not_follow_symlinks(self):
        owned = self.root / "owned-cleanup"
        owned.mkdir()
        outside = self.root / "outside-cleanup.txt"
        outside.write_bytes(b"preserve")
        (owned / "redirect").symlink_to(outside)
        recovery._remove_tree_no_follow(owned)
        self.assertEqual(outside.read_bytes(), b"preserve")

    def test_restore_rejects_symlinked_bundle_tree(self):
        bundle = self._bundle()
        alias = self.root / "bundle-alias"
        alias.symlink_to(bundle, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "bundle_file_invalid"):
            recovery.validate_recovery_bundle(alias)

    def test_import_has_no_recovery_side_effect(self):
        self.assertFalse((self.root / "recovery").exists())
        self.assertEqual(recovery.recovery_status(self.conn)["state"], "inactive")

    def test_recovery_cli_help_is_directly_invocable_without_side_effects(self):
        script = Path(__file__).parents[1] / "scripts" / "manage_stage77_recovery.py"
        result = subprocess.run([sys.executable, str(script), "--help"], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0)
        self.assertIn("create", result.stdout)
        self.assertNotIn("Traceback", result.stderr)

    def test_capture_failure_preserves_bounded_phase_and_cleanup_status(self):
        original = recovery._read_connection

        def fail_read(_path):
            raise sqlite3.OperationalError("database is locked")

        recovery._read_connection = fail_read
        try:
            with self.assertRaises(recovery.RecoveryOperationFailure) as raised:
                recovery.capture_recovery_point(
                    database_path=self.db,
                    artifact_root=self.artifacts,
                    recovery_root=self.recovery_root,
                    approved_root=self.root,
                    actor="admin",
                    governed_action="capture",
                )
        finally:
            recovery._read_connection = original
        failure = raised.exception
        self.assertEqual(failure.phase, "capture")
        self.assertEqual(failure.operation, "online_backup_source_connection")
        self.assertEqual(failure.checkpoint, "starting")
        self.assertEqual(failure.code, "sqlite_error")
        self.assertEqual(failure.cleanup_status, "completed")
        self.assertEqual(failure.maintenance_status, "failed")

    def test_capture_failure_does_not_mask_primary_failure_when_failure_recording_fails(self):
        original_read = recovery._read_connection
        original_fail = recovery.fail_recovery

        def fail_read(_path):
            raise sqlite3.OperationalError("database is locked")

        def fail_record(*_args, **_kwargs):
            raise sqlite3.OperationalError("state recording unavailable")

        recovery._read_connection = fail_read
        recovery.fail_recovery = fail_record
        try:
            with self.assertRaises(recovery.RecoveryOperationFailure) as raised:
                recovery.capture_recovery_point(
                    database_path=self.db,
                    artifact_root=self.artifacts,
                    recovery_root=self.recovery_root,
                    approved_root=self.root,
                    actor="admin",
                    governed_action="capture",
                )
        finally:
            recovery._read_connection = original_read
            recovery.fail_recovery = original_fail
        failure = raised.exception
        self.assertEqual(failure.code, "sqlite_error")
        self.assertEqual(failure.maintenance_status, "unknown")

    def test_capture_failure_does_not_mask_primary_failure_when_rollback_fails(self):
        original_read = recovery._read_connection
        original_connect = recovery._connect

        def fail_read(_path):
            raise sqlite3.OperationalError("database is locked")

        class RollbackFailingConnection:
            def __init__(self, wrapped):
                self._wrapped = wrapped

            def __getattr__(self, name):
                return getattr(self._wrapped, name)

            def rollback(self):
                raise sqlite3.OperationalError("rollback unavailable")

        def connect_with_failing_rollback(path):
            return RollbackFailingConnection(original_connect(path))

        recovery._read_connection = fail_read
        recovery._connect = connect_with_failing_rollback
        try:
            with self.assertRaises(recovery.RecoveryOperationFailure) as raised:
                recovery.capture_recovery_point(
                    database_path=self.db,
                    artifact_root=self.artifacts,
                    recovery_root=self.recovery_root,
                    approved_root=self.root,
                    actor="admin",
                    governed_action="capture",
                )
        finally:
            recovery._read_connection = original_read
            recovery._connect = original_connect
        failure = raised.exception
        self.assertEqual(failure.code, "sqlite_error")
        self.assertEqual(failure.operation, "online_backup_source_connection")
        self.assertEqual(failure.cleanup_status, "failed")

    def test_source_connection_failure_closes_backup_destination(self):
        original_read = recovery._read_connection
        original_connect = sqlite3.connect
        backup_connections = []

        def fail_read(_path):
            raise sqlite3.OperationalError("database is locked")

        def tracking_connect(*args, **kwargs):
            connection = original_connect(*args, **kwargs)
            if args and str(args[0]).endswith("database.sqlite3"):
                backup_connections.append(connection)
            return connection

        recovery._read_connection = fail_read
        recovery.sqlite3.connect = tracking_connect
        try:
            with self.assertRaises(recovery.RecoveryOperationFailure):
                recovery.capture_recovery_point(
                    database_path=self.db,
                    artifact_root=self.artifacts,
                    recovery_root=self.recovery_root,
                    approved_root=self.root,
                    actor="admin",
                    governed_action="capture",
                )
        finally:
            recovery._read_connection = original_read
            recovery.sqlite3.connect = original_connect
        self.assertTrue(backup_connections)
        with self.assertRaises(sqlite3.ProgrammingError):
            backup_connections[-1].execute("SELECT 1")

    def test_recovery_cli_serializes_only_bounded_failure_context(self):
        from scripts import manage_stage77_recovery as cli
        from contextlib import redirect_stdout

        output = io.StringIO()
        failure = recovery.RecoveryOperationFailure(
            phase="capture",
            operation="online_backup_source_connection",
            checkpoint="starting",
            code="sqlite_error",
            cleanup_status="completed",
            maintenance_status="failed",
        )
        with patch.object(cli, "capture_recovery_point", side_effect=failure), redirect_stdout(output):
            self.assertEqual(cli.main(["create", "--database", str(self.db), "--artifact-root", str(self.artifacts), "--recovery-root", str(self.recovery_root), "--actor", "admin", "--action", "capture"]), 1)
        self.assertEqual(output.getvalue().strip(), "stage77_recovery=failed phase=capture operation=online_backup_source_connection checkpoint=starting code=sqlite_error cleanup=completed maintenance=failed")
        self.assertNotIn(str(self.root), output.getvalue())

    def test_portable_export_is_deterministic_and_receipt_validates(self):
        bundle = self._bundle()
        exports = self.root / "exports"
        exports.mkdir()
        first = recovery.export_recovery_bundle(
            bundle_path=bundle,
            output_archive=exports / "first.tar",
            receipt_path=exports / "first.json",
            reason="before persistence deployment",
        )
        second = recovery.export_recovery_bundle(
            bundle_path=bundle,
            output_archive=exports / "second.tar",
            receipt_path=exports / "second.json",
            reason="before persistence deployment",
        )
        self.assertEqual(first["archive_digest"], second["archive_digest"])
        self.assertEqual(first["manifest_digest"], second["manifest_digest"])
        self.assertEqual(
            recovery.validate_export_archive(exports / "first.tar", exports / "first.json")["recovery_point_id"],
            recovery.validate_recovery_bundle(bundle)["recovery_point_id"],
        )
        extracted = self.root / "extracted"
        recovery.validate_export_archive(exports / "first.tar", exports / "first.json", extract_to=extracted)
        self.assertTrue(next(extracted.iterdir()).joinpath("database.sqlite3").exists())

    def test_historical_receipt_contract_validates_only_with_legacy_bundle_schema(self):
        legacy = self.root / "legacy-bundle"
        legacy.mkdir()
        database = legacy / "database.sqlite3"
        conn = sqlite3.connect(database)
        conn.executescript("""
        CREATE TABLE record_governed_reports(id INTEGER PRIMARY KEY);
        CREATE TABLE record_governed_report_versions(id INTEGER PRIMARY KEY, report_id INTEGER NOT NULL,
          FOREIGN KEY(report_id) REFERENCES record_governed_reports(id));
        CREATE TABLE record_governed_report_artifacts(id INTEGER PRIMARY KEY, version_id INTEGER NOT NULL,
          format TEXT, storage_reference TEXT, sha256 TEXT, size_bytes INTEGER, validation_state TEXT,
          FOREIGN KEY(version_id) REFERENCES record_governed_report_versions(id));
        CREATE TABLE stage77_report_jobs(id INTEGER PRIMARY KEY, state TEXT);
        CREATE TABLE stage77_report_job_events(id INTEGER PRIMARY KEY);
        CREATE TABLE stage77_recovery_control(singleton INTEGER, operation_id TEXT, maintenance_epoch INTEGER, state TEXT);
        CREATE TABLE stage77_recovery_events(id INTEGER PRIMARY KEY, operation_id TEXT);
        """)
        conn.commit()
        conn.close()
        database_digest = recovery.digest_bytes(database.read_bytes())
        manifest = {
            "manifest_schema_version": recovery.MANIFEST_SCHEMA_VERSION,
            "recovery_point_id": "a" * 32,
            "maintenance_epoch": 1,
            "created_at": "2026-01-01T00:00:00Z",
            "source_database_identity": f"sqlite:{database.stat().st_size}:{database_digest}",
            "sqlite_version": sqlite3.sqlite_version,
            "application_version": "unknown",
            "publication_engine_version": "2.0.0",
            "stage77_schema_version": "stage77.governed_report_job.v1",
            "database": {"filename": "database.sqlite3", "size_bytes": database.stat().st_size, "sha256": database_digest},
            "integrity": {"integrity_check": "ok", "foreign_key_check": "ok"},
            "job_event_bound": 0,
            "recovery_event_bound": 0,
            "job_state_counts": {state: 0 for state in ("queued", "leased", "running", "retry_wait", "cancel_requested", "succeeded", "failed_terminal", "cancelled")},
            "counts": {"jobs": 0, "reports": 0, "versions": 0, "artifacts": 0},
            "artifacts": [],
            "limitations": ["historical pre-qualification fixture"],
        }
        raw_manifest = recovery.canonical_json(manifest).encode("utf-8")
        (legacy / "manifest.json").write_bytes(raw_manifest)
        (legacy / "manifest.sha256").write_text(recovery.digest_bytes(raw_manifest) + "\n", encoding="ascii")
        archive = self.root / "legacy.tar"
        recovery._write_deterministic_archive(legacy, archive, manifest["recovery_point_id"])
        receipt = {
            "receipt_schema_version": recovery.EXPORT_RECEIPT_SCHEMA_VERSION,
            "recovery_point_id": manifest["recovery_point_id"],
            "created_at": "2026-01-01T00:00:00Z",
            "recovery_reason": "historical pre-qualification fixture",
            "manifest_digest": recovery.digest_bytes(raw_manifest),
            "database_digest": database_digest,
            "archive_digest": recovery.digest_bytes(archive.read_bytes()),
            "artifact_count": 0,
            "recovery_event_bound": 0,
            "job_event_bound": 0,
            "application_version": "unknown",
            "publication_engine_version": "2.0.0",
            "stage77_schema_version": "stage77.governed_report_job.v1",
        }
        receipt_path = self.root / "legacy.receipt.json"
        receipt_path.write_bytes(recovery.canonical_json(receipt).encode("utf-8"))
        result = recovery.validate_export_archive(archive, receipt_path)
        self.assertEqual(result["recovery_point_id"], manifest["recovery_point_id"])

    def test_current_receipt_cannot_downgrade_or_accept_legacy_shape(self):
        bundle = self._bundle()
        exports = self.root / "exports"
        exports.mkdir()
        archive = exports / "current.tar"
        receipt_path = exports / "current.json"
        recovery.export_recovery_bundle(bundle_path=bundle, output_archive=archive, receipt_path=receipt_path, reason="current")
        receipt = json.loads(receipt_path.read_text())
        for field in ("qualification_count", "qualification_event_bound", "qualification_state_digest"):
            receipt.pop(field)
        receipt_path.write_text(recovery.canonical_json(receipt), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "export_receipt_mismatch"):
            recovery.validate_export_archive(archive, receipt_path)

    def test_unknown_receipt_version_and_mixed_contracts_fail_closed(self):
        bundle = self._bundle()
        exports = self.root / "exports"
        exports.mkdir()
        archive = exports / "current.tar"
        receipt_path = exports / "current.json"
        recovery.export_recovery_bundle(bundle_path=bundle, output_archive=archive, receipt_path=receipt_path, reason="current")
        receipt = json.loads(receipt_path.read_text())
        receipt["receipt_schema_version"] = "stage77.recovery_receipt.unknown"
        receipt_path.write_text(recovery.canonical_json(receipt), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "export_receipt_invalid"):
            recovery.validate_export_archive(archive, receipt_path)

    def test_portable_export_rejects_existing_targets_and_unsafe_custody_root(self):
        bundle = self._bundle()
        exports = self.root / "exports"
        exports.mkdir()
        archive = exports / "recovery.tar"
        receipt = exports / "recovery.json"
        recovery.export_recovery_bundle(bundle_path=bundle, output_archive=archive, receipt_path=receipt, reason="test")
        with self.assertRaisesRegex(ValueError, "export_target_exists"):
            recovery.export_recovery_bundle(bundle_path=bundle, output_archive=archive, receipt_path=self.root / "other.json", reason="test")
        with self.assertRaisesRegex(ValueError, "custody_root_invalid"):
            recovery.export_recovery_bundle(bundle_path=bundle, output_archive=self.root / "custody.tar", receipt_path=self.root / "custody.json", reason="test", custody_root=self.root)

    def test_portable_export_rejects_archive_traversal_and_symlink_members(self):
        archive = self.root / "bad.tar"
        receipt = self.root / "bad.json"
        with tarfile.open(archive, "w") as stream:
            info = tarfile.TarInfo("../outside")
            info.size = 1
            stream.addfile(info, __import__("io").BytesIO(b"x"))
        with self.assertRaisesRegex(ValueError, "export_archive_invalid"):
            recovery._extract_export_archive(archive, self.root / "bad-extracted")

    def test_portable_export_rejects_source_mutation_during_packaging(self):
        bundle = self._bundle()
        exports = self.root / "exports"
        exports.mkdir()
        original = recovery._write_deterministic_archive

        def mutate_after_archive(source, destination, recovery_point_id):
            original(source, destination, recovery_point_id)
            (source / "manifest.json").write_bytes((source / "manifest.json").read_bytes() + b" ")

        recovery._write_deterministic_archive = mutate_after_archive
        try:
            with self.assertRaisesRegex(ValueError, "export_source_changed"):
                recovery.export_recovery_bundle(bundle_path=bundle, output_archive=exports / "recovery.tar", receipt_path=exports / "recovery.json", reason="test")
        finally:
            recovery._write_deterministic_archive = original
        self.assertFalse((exports / "recovery.tar").exists())
        self.assertFalse((exports / "recovery.json").exists())

    def test_recovery_cli_exposes_export_and_validate_export_without_import_side_effects(self):
        script = Path(__file__).parents[1] / "scripts" / "manage_stage77_recovery.py"
        result = subprocess.run([sys.executable, str(script), "--help"], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0)
        self.assertIn("export", result.stdout)
        self.assertIn("validate-export", result.stdout)
        self.assertNotIn("Traceback", result.stderr)

    def test_batch3b4a_report_event_bound_provenance_matrix(self):
        bundle, _live_db, _point_id = self._historical_reconstruction_fixture()
        manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
        payload = recovery._recovery_evidence_payload(
            manifest, source_mode="historical_reconstruction", actor="admin",
            rationale="bounded reconstruction", declaration={"acknowledged": True},
            idempotency_key="b3b4a", created_at="2026-01-01T00:00:00Z",
        )
        self.assertEqual(recovery._manifest_contract(manifest), "diagnostic_aware")
        self.assertEqual(payload["report_event_bound_status"], "not_bound_by_source_contract")
        self.assertIsNone(payload["report_event_bound"])
        self.assertNotEqual(payload["report_event_bound"], 0)
        self.assertNotEqual(payload["report_event_bound"], 10)
        digest = recovery.digest_bytes(recovery.canonical_json(payload).encode("utf-8"))
        reordered = {key: payload[key] for key in reversed(list(payload))}
        self.assertEqual(digest, recovery.digest_bytes(recovery.canonical_json(reordered).encode("utf-8")))

        cases = [
            ("unavailable_null", {"report_event_bound_status": "not_bound_by_source_contract", "report_event_bound": None}, None, True),
            ("bound_valid", {"report_event_bound_status": "bound", "report_event_bound": 10}, None, True),
            ("missing_status", {"report_event_bound": None}, "recovery_evidence_report_event_bound_invalid", False),
            ("unknown_status", {"report_event_bound_status": "observed", "report_event_bound": None}, "recovery_evidence_report_event_bound_invalid", False),
            ("unavailable_with_value", {"report_event_bound_status": "not_bound_by_source_contract", "report_event_bound": 10}, "recovery_evidence_report_event_bound_invalid", False),
            ("bound_null", {"report_event_bound_status": "bound", "report_event_bound": None}, "recovery_evidence_report_event_bound_invalid", False),
            ("bound_missing", {"report_event_bound_status": "bound"}, "recovery_evidence_report_event_bound_invalid", False),
            ("bound_boolean", {"report_event_bound_status": "bound", "report_event_bound": True}, "recovery_evidence_report_event_bound_invalid", False),
            ("bound_negative", {"report_event_bound_status": "bound", "report_event_bound": -1}, "recovery_evidence_report_event_bound_invalid", False),
        ]
        for name, candidate, expected, valid in cases:
            with self.subTest(name=name):
                if expected:
                    with self.assertRaisesRegex(ValueError, expected):
                        recovery._validate_report_event_binding(candidate)
                else:
                    recovery._validate_report_event_binding(candidate)
                    self.assertTrue(valid)

        diagnostic_with_value = dict(manifest)
        with self.assertRaisesRegex(ValueError, "recovery_evidence_report_event_bound_invalid"):
            recovery._recovery_evidence_payload(
                diagnostic_with_value, source_mode="historical_reconstruction", actor="admin",
                rationale="bounded reconstruction", declaration={}, idempotency_key="b3b4b-int",
                created_at="2026-01-01T00:00:00Z", report_event_bound=10,
            )
        post_payload = recovery._recovery_evidence_payload(
            manifest, source_mode="native_capture", actor="", rationale="", declaration={},
            idempotency_key="", created_at="", report_event_bound=10,
            contract_name="post_correction_aware",
        )
        recovery._validate_report_event_binding(post_payload, require_bound=True)
        with self.assertRaisesRegex(ValueError, "recovery_evidence_report_event_bound_unavailable"):
            recovery._validate_report_event_binding(payload, require_bound=True)

        expected_keys = set(payload)
        self.assertIn("report_event_bound_status", expected_keys)
        self.assertIn("report_event_bound", expected_keys)
        row = dict(payload)
        row["report_event_bound_status"] = "bound"
        with self.assertRaisesRegex(ValueError, "recovery_evidence_report_event_bound_invalid"):
            recovery._validate_report_event_binding(row)

        result = recovery.capture_recovery_point(
            database_path=self.db, artifact_root=self.artifacts,
            recovery_root=self.recovery_root, approved_root=self.root,
            actor="admin", governed_action="capture",
        )
        evidence = self.conn.execute(
            "SELECT * FROM stage77_recovery_point_evidence WHERE recovery_point_id=?",
            (result["recovery_point_id"],),
        ).fetchone()
        stored_payload = json.loads(evidence["evidence_payload_json"])
        self.assertEqual(stored_payload["report_event_bound_status"], "not_bound_by_source_contract")
        self.assertIsNone(stored_payload["report_event_bound"])
        self.assertEqual(evidence["report_event_bound_status"], "not_bound_by_source_contract")
        self.assertIsNone(evidence["report_event_bound"])
        event = self.conn.execute(
            "SELECT payload_json FROM stage77_recovery_point_evidence_events WHERE evidence_id=?",
            (evidence["id"],),
        ).fetchone()
        self.assertEqual(json.loads(event[0]), stored_payload)
        with self.subTest(name="row_status_mismatch"):
            self.conn.execute("DROP TRIGGER stage77_recovery_evidence_no_update")
            self.conn.execute("UPDATE stage77_recovery_point_evidence SET report_event_bound_status='bound' WHERE id=?", (evidence["id"],))
            with self.assertRaisesRegex(ValueError, "recovery_evidence_invalid"):
                recovery.recovery_evidence_for_point(self.conn, result["recovery_point_id"])
        with self.subTest(name="row_value_mismatch"):
            self.conn.execute("UPDATE stage77_recovery_point_evidence SET report_event_bound_status='not_bound_by_source_contract', report_event_bound=10 WHERE id=?", (evidence["id"],))
            with self.assertRaisesRegex(ValueError, "recovery_evidence_invalid"):
                recovery.recovery_evidence_for_point(self.conn, result["recovery_point_id"])
        with self.subTest(name="event_payload_mismatch"):
            self.conn.execute("UPDATE stage77_recovery_point_evidence SET report_event_bound=NULL WHERE id=?", (evidence["id"],))
            self.conn.execute("DROP TRIGGER stage77_recovery_evidence_events_no_update")
            self.conn.execute("UPDATE stage77_recovery_point_evidence_events SET payload_json=? WHERE evidence_id=?", (recovery.canonical_json({"report_event_bound_status": "bound", "report_event_bound": 10}), evidence["id"]))
            with self.assertRaisesRegex(ValueError, "recovery_evidence_event_invalid"):
                recovery.recovery_evidence_for_point(self.conn, result["recovery_point_id"])
        with self.subTest(name="read_only_validation_has_no_schema_side_effect"):
            before = {row[0] for row in self.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            recovery.validate_recovery_bundle(bundle)
            after = {row[0] for row in self.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertEqual(before, after)

    def test_batch3b4b_manifest_claim_matrix_for_governed_counts(self):
        fields = {
            "reports": ("record_count_mismatch", 1),
            "versions": ("version_count_mismatch", 1),
            "qualifications": ("qualification_count_mismatch", 4),
            "jobs": ("job_state_count_mismatch", 2),
            "artifacts": ("artifact_inventory_mismatch", 0),
        }
        malformed = [
            ("wrong_type", "one"), ("boolean", True), ("negative", -1),
            ("numeric_string", "1"), ("float", 1.0),
        ]
        subcases = 0
        for field, (mismatch_code, correct) in fields.items():
            for label, value in (("correct", correct), ("lower", correct - 1), ("higher", correct + 1),
                                 *malformed, ("unrelated_large", 999999)):
                subcases += 1
                with self.subTest(field=field, value=label):
                    self.tearDown()
                    self.setUp()
                    self.conn.execute("DELETE FROM record_governed_report_artifacts")
                    self.artifact.unlink()
                    self.conn.commit()
                    bundle, live_db, point_id = self._historical_reconstruction_fixture()
                    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
                    if label == "missing":
                        manifest["counts"].pop(field)
                    else:
                        manifest["counts"][field] = value
                    if label == "correct":
                        recovery.validate_recovery_bundle(bundle)
                        continue
                    self._rewrite_manifest(bundle, manifest)
                    expected_code = mismatch_code if label in {"lower", "higher", "unrelated_large"} and not (field == "artifacts" and label == "lower") else "manifest_invalid"
                    with self.assertRaisesRegex(ValueError, expected_code):
                        recovery.reconstruct_recovery_point_evidence(
                            database_path=live_db, recovery_root=self.recovery_root,
                            recovery_point_id=point_id, actor="admin", rationale="bounded count test",
                            acknowledged=True, idempotency_key=f"count-{field}-{label}", approved_root=self.root,
                        )
                    check = sqlite3.connect(live_db)
                    self.assertEqual(check.execute("SELECT COUNT(*) FROM stage77_recovery_point_evidence").fetchone()[0], 0)
                    self.assertEqual(check.execute("SELECT COUNT(*) FROM stage77_recovery_point_evidence_events").fetchone()[0], 0)
                    check.close()
            subcases += 1
            with self.subTest(field=field, value="missing"):
                self.tearDown()
                self.setUp()
                self.conn.execute("DELETE FROM record_governed_report_artifacts")
                self.artifact.unlink()
                self.conn.commit()
                bundle, live_db, point_id = self._historical_reconstruction_fixture()
                manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
                manifest["counts"].pop(field)
                self._rewrite_manifest(bundle, manifest)
                with self.assertRaisesRegex(ValueError, "manifest_invalid"):
                    recovery.reconstruct_recovery_point_evidence(
                        database_path=live_db, recovery_root=self.recovery_root,
                        recovery_point_id=point_id, actor="admin", rationale="bounded count test",
                        acknowledged=True, idempotency_key=f"count-{field}-missing", approved_root=self.root,
                    )
        self.assertEqual(subcases, 50)

    def test_batch3b4b_post_correction_zero_authorization_counts(self):
        self.conn.execute("DELETE FROM record_governed_report_artifacts")
        self.artifact.unlink()
        self.conn.commit()
        jobs.ensure_post_correction_tables(self.conn)
        result = recovery.capture_recovery_point(
            database_path=self.db, artifact_root=self.artifacts,
            recovery_root=self.recovery_root, approved_root=self.root,
            actor="admin", governed_action="capture",
        )
        bundle = self.recovery_root / f"recovery-{result['recovery_point_id']}"
        manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["counts"], {"jobs": 0, "reports": 1, "versions": 1, "artifacts": 0, "qualifications": 0})
        self.assertEqual(recovery.validate_recovery_bundle(bundle)["state"], "valid")

    def _zero_artifact_historical_fixture(self, *, linked_successor=True, post_correction=False):
        self.conn.execute("DELETE FROM record_governed_report_artifacts")
        if self.artifact.exists():
            self.artifact.unlink()
        self.conn.commit()
        return self._historical_reconstruction_fixture(post_correction=post_correction) if linked_successor or post_correction else self._zero_link_reconstruction_fixture()

    def _zero_link_reconstruction_fixture(self):
        self._add_diagnostic_evidence(linked_successor=False)
        result = recovery.capture_recovery_point(database_path=self.db, artifact_root=self.artifacts, recovery_root=self.recovery_root, approved_root=self.root, actor="admin", governed_action="capture")
        bundle = self.recovery_root / f"recovery-{result['recovery_point_id']}"
        live_db = self.root / "zero-link-live.db"
        live = sqlite3.connect(live_db)
        recovery.ensure_recovery_tables(live)
        live.close()
        return bundle, live_db, result["recovery_point_id"]

    def _legacy_zero_artifact_bundle(self, name="legacy-zero-artifact"):
        point_id = recovery.digest_bytes(name.encode("utf-8"))[:32]
        root = self.root / f"recovery-{point_id}"
        root.mkdir()
        database = root / "database.sqlite3"
        conn = sqlite3.connect(database)
        conn.executescript("""
        CREATE TABLE record_governed_reports(id INTEGER PRIMARY KEY);
        CREATE TABLE record_governed_report_versions(id INTEGER PRIMARY KEY, report_id INTEGER NOT NULL,
          FOREIGN KEY(report_id) REFERENCES record_governed_reports(id));
        CREATE TABLE record_governed_report_artifacts(id INTEGER PRIMARY KEY, version_id INTEGER NOT NULL,
          format TEXT, storage_reference TEXT, sha256 TEXT, size_bytes INTEGER, validation_state TEXT,
          FOREIGN KEY(version_id) REFERENCES record_governed_report_versions(id));
        CREATE TABLE stage77_report_jobs(id INTEGER PRIMARY KEY, state TEXT);
        CREATE TABLE stage77_report_job_events(id INTEGER PRIMARY KEY);
        CREATE TABLE stage77_recovery_control(singleton INTEGER, operation_id TEXT, maintenance_epoch INTEGER, state TEXT);
        CREATE TABLE stage77_recovery_events(id INTEGER PRIMARY KEY, operation_id TEXT);
        """)
        conn.commit()
        conn.close()
        database_digest = recovery.digest_bytes(database.read_bytes())
        manifest = {
            "manifest_schema_version": recovery.MANIFEST_SCHEMA_VERSION,
            "recovery_point_id": point_id,
            "maintenance_epoch": 1,
            "created_at": "2026-01-01T00:00:00Z",
            "source_database_identity": f"sqlite:{database.stat().st_size}:{database_digest}",
            "sqlite_version": sqlite3.sqlite_version,
            "application_version": "unknown",
            "publication_engine_version": "2.0.0",
            "stage77_schema_version": "stage77.governed_report_job.v1",
            "database": {"filename": "database.sqlite3", "size_bytes": database.stat().st_size, "sha256": database_digest},
            "integrity": {"integrity_check": "ok", "foreign_key_check": "ok"},
            "job_event_bound": 0,
            "recovery_event_bound": 0,
            "job_state_counts": {state: 0 for state in ("queued", "leased", "running", "retry_wait", "cancel_requested", "succeeded", "failed_terminal", "cancelled")},
            "counts": {"jobs": 0, "reports": 0, "versions": 0, "artifacts": 0},
            "artifacts": [],
            "limitations": ["historical pre-qualification fixture"],
        }
        self._rewrite_manifest(root, manifest)
        live_db = self.root / f"{name}-live.sqlite3"
        live = sqlite3.connect(live_db)
        recovery.ensure_recovery_tables(live)
        live.close()
        return root, live_db, point_id

    def _insert_archived_artifact_row(self, conn, *, artifact_id=900, version_id=None, fmt="docx", state="valid", sha=None, size=123, storage=None):
        version_id = version_id if version_id is not None else int(conn.execute("SELECT id FROM record_governed_report_versions ORDER BY id LIMIT 1").fetchone()[0])
        sha = sha if sha is not None else "a" * 64
        storage = storage if storage is not None else str(self.root / "artifacts" / f"nonexistent-{artifact_id}-{fmt}")
        columns = [row[1] for row in conn.execute("PRAGMA table_info(record_governed_report_artifacts)").fetchall()]
        values = {
            "id": artifact_id,
            "version_id": version_id,
            "format": fmt,
            "storage_reference": storage,
            "sha256": sha,
            "size_bytes": size,
            "renderer_version": "2.0.0",
            "template_version": "cde-internal-v1",
            "generated_at": "2026-01-01T00:00:09Z",
            "validation_state": state,
            "diagnostics_json": "{}",
            "lifecycle_status": "current",
            "qualification_id": None,
            "qualification_digest": None,
            "disclosure_version": "standard-v1",
        }
        selected = [column for column in columns if column in values]
        conn.execute(
            f"INSERT INTO record_governed_report_artifacts({','.join(selected)}) VALUES({','.join('?' for _ in selected)})",
            tuple(values[column] for column in selected),
        )

    def _assert_zero_artifact_rejection(self, bundle, live_db, point_id, expected, *, key, manifest_mutation=None):
        manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
        self._refresh_archived_database_binding(bundle, manifest)
        if manifest_mutation is not None:
            manifest_mutation(manifest)
            self._rewrite_manifest(bundle, manifest)
        before = sqlite3.connect(bundle / "database.sqlite3")
        artifact_rows = before.execute("SELECT COUNT(*) FROM record_governed_report_artifacts").fetchone()[0]
        before.close()
        for attempt in range(2):
            with self.assertRaisesRegex(ValueError, expected):
                recovery.reconstruct_recovery_point_evidence(database_path=live_db, recovery_root=bundle.parent, recovery_point_id=point_id, actor="admin", rationale="zero accepted artifact mutation", acknowledged=True, idempotency_key=key, approved_root=bundle.parent.parent)
        check = sqlite3.connect(live_db)
        self.assertEqual(check.execute("SELECT COUNT(*) FROM stage77_recovery_point_evidence").fetchone()[0], 0)
        self.assertEqual(check.execute("SELECT COUNT(*) FROM stage77_recovery_point_evidence_events").fetchone()[0], 0)
        check.close()
        after = sqlite3.connect(bundle / "database.sqlite3")
        self.assertEqual(after.execute("SELECT COUNT(*) FROM record_governed_report_artifacts").fetchone()[0], artifact_rows)
        after.close()

    def _successful_artifact_fixture(self, name, *, requested_formats=None, capture=True):
        requested_formats = list(requested_formats or ["docx", "html", "pdf"])
        root = self.root / name
        root.mkdir()
        database = root / "records.sqlite3"
        artifact_root = root / "artifacts"
        recovery_root = root / "recovery"
        artifact_root.mkdir()
        original_report_root = reports.REPORT_ROOT
        conn = sqlite3.connect(database)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        record = {"reference": "CR-1", "title": "Canonical record", "finding": "Original wording", "status": "recorded", "version": 1}

        def fake_render(specification, digest, output_dir, *_args, **_kwargs):
            self.assertEqual(reports.specification_digest(specification), digest)
            output_dir = Path(output_dir)
            self.assertTrue(output_dir.resolve(strict=False).is_relative_to(artifact_root.resolve(strict=False)))
            output_dir.mkdir(parents=True, exist_ok=False)
            artifacts = []
            for format_name in specification["requested_formats"]:
                path = output_dir / f"report.{format_name}"
                payload = f"{format_name}:{digest}:producer-success\n".encode("utf-8")
                path.write_bytes(payload)
                artifacts.append({
                    "format": format_name,
                    "path": str(path),
                    "sha256": recovery.digest_bytes(payload),
                    "size_bytes": len(payload),
                    "renderer_version": specification["publication_engine_version"],
                })
            return {"artifacts": artifacts, "diagnostics": []}

        try:
            reports.REPORT_ROOT = artifact_root
            reports.ensure_report_tables(conn)
            qualifications.ensure_qualification_tables(conn)
            jobs.ensure_job_tables(conn)
            recovery.ensure_recovery_tables(conn)
            with patch.object(reports.rda, "record_context", return_value=record), patch.dict(os.environ, {qualifications.REVIEW_MODE_ENV: qualifications.SOLE_MODE}):
                report = reports.create_report(
                    conn,
                    title="Internal report",
                    purpose="Review selected record",
                    audience="Administrators",
                    distribution_class="internal_working",
                    canonical_record_reference="CR-1",
                    document_ids=[],
                    association_ids=[],
                    sections=[{"title": "Record", "blocks": [{"content_type": "verbatim_source", "text": "Original wording", "source_identity": {"object_kind": "canonical_record", "object_id": "CR-1"}, "inclusion_rationale": "Deliberately selected."}]}],
                    exclusions=[],
                    requested_formats=requested_formats,
                    rendering_profile="internal",
                    template_version="cde-internal-v1",
                    actor="nick",
                    actor_role="administrator",
                    idempotency_key=f"{name}-report",
                )
                for status, suffix in (("assembly_reviewed", "assembly"), ("privacy_reviewed", "privacy"), ("redaction_reviewed", "redaction"), ("approved_for_generation", "approval")):
                    report = reports.confirm_creator_gate(conn, report_id=report["id"], resulting_status=status, rationale="Sole administrator producer fixture", actor="nick", actor_role="administrator", acknowledged=True, idempotency_key=f"{name}-{suffix}")
                version_id = int(report["versions"][-1]["id"])
                self.assertEqual([item["completed_gate"] for item in qualifications.validate_complete_chain(conn, version_id)], ["assembly", "privacy", "redaction", "approval"])
                job = jobs.enqueue_generation(conn, report_id=report["id"], actor="nick", governed_action="enqueue_generation", idempotency_key=f"{name}-job")
                claimed = jobs.claim_one(conn)
                self.assertEqual(claimed["id"], job["id"])
                conn.close()
                with patch("api.report_rendering.render_frozen_report", side_effect=fake_render) as renderer:
                    jobs.execute_job(str(database), claimed)
                self.assertEqual(renderer.call_count, 1)
        finally:
            reports.REPORT_ROOT = original_report_root
            try:
                conn.close()
            except sqlite3.Error:
                pass

        source = sqlite3.connect(database)
        source.row_factory = sqlite3.Row
        try:
            final_job = jobs.get_job(source, job["id"])
            self.assertEqual(final_job["state"], "succeeded")
            rows = [dict(row) for row in source.execute("SELECT * FROM record_governed_report_artifacts WHERE validation_state='valid' ORDER BY id").fetchall()]
            self.assertEqual({row["format"] for row in rows}, set(requested_formats))
            source_files = {row["format"]: recovery.digest_bytes(Path(row["storage_reference"]).read_bytes()) for row in rows}
        finally:
            source.close()

        if not capture:
            return {
                "root": root,
                "database": database,
                "artifact_root": artifact_root,
                "recovery_root": recovery_root,
                "job_id": job["id"],
                "version_id": rows[0]["version_id"],
                "artifact_rows": rows,
                "source_files": source_files,
            }

        captured = recovery.capture_recovery_point(database_path=database, artifact_root=artifact_root, recovery_root=recovery_root, approved_root=root, actor="admin", governed_action="capture", idempotency_key=f"{name}-capture")
        bundle = recovery_root / f"recovery-{captured['recovery_point_id']}"
        manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
        live_db = root / "live.sqlite3"
        live = sqlite3.connect(live_db)
        recovery.ensure_recovery_tables(live)
        live.close()
        bundle_files = {item["format"]: recovery.digest_bytes((bundle / item["filename"]).read_bytes()) for item in manifest["artifacts"]}
        return {
            "root": root,
            "database": database,
            "artifact_root": artifact_root,
            "recovery_root": recovery_root,
            "bundle": bundle,
            "live_db": live_db,
            "point_id": captured["recovery_point_id"],
            "manifest": manifest,
            "job_id": job["id"],
            "version_id": rows[0]["version_id"],
            "artifact_rows": rows,
            "source_files": source_files,
            "bundle_files": bundle_files,
        }

    def _artifact_manifest_from_archive(self, bundle):
        conn = sqlite3.connect(bundle / "database.sqlite3")
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT a.id,a.version_id,a.format,a.sha256,a.size_bytes,v.report_id "
                "FROM record_governed_report_artifacts a JOIN record_governed_report_versions v ON v.id=a.version_id "
                "WHERE a.validation_state='valid' ORDER BY a.id"
            ).fetchall()
            return [
                {
                    "artifact_id": int(row["id"]),
                    "report_id": int(row["report_id"]),
                    "version_id": int(row["version_id"]),
                    "format": str(row["format"]),
                    "filename": f"artifacts/artifact-{int(row['id'])}-{str(row['format']).lower()}",
                    "size_bytes": int(row["size_bytes"]),
                    "sha256": str(row["sha256"]),
                }
                for row in rows
            ]
        finally:
            conn.close()

    def _rewrite_artifact_manifest_from_archive(self, bundle, manifest):
        manifest["artifacts"] = self._artifact_manifest_from_archive(bundle)
        manifest["counts"]["artifacts"] = len(manifest["artifacts"])
        self._rewrite_manifest(bundle, manifest)

    def _assert_success_artifact_rejection(self, fixture, expected, *, key, update_database=True, update_artifacts=False):
        bundle = fixture["bundle"]
        manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
        if update_database:
            self._refresh_archived_database_binding(bundle, manifest)
        if update_artifacts:
            self._rewrite_artifact_manifest_from_archive(bundle, manifest)
            manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
            if update_database:
                self._refresh_archived_database_binding(bundle, manifest)
        database_before = (bundle / "database.sqlite3").read_bytes()
        manifest_before = (bundle / "manifest.json").read_bytes()
        bundle_file_hashes = {
            item["filename"]: recovery.digest_bytes((bundle / item["filename"]).read_bytes())
            for item in json.loads(manifest_before.decode("utf-8"))["artifacts"]
            if (bundle / item["filename"]).is_file()
        }
        for attempt in range(2):
            with self.assertRaisesRegex(ValueError, expected):
                recovery.reconstruct_recovery_point_evidence(
                    database_path=fixture["live_db"],
                    recovery_root=fixture["recovery_root"],
                    recovery_point_id=fixture["point_id"],
                    actor="admin",
                    rationale="successful artifact mutation",
                    acknowledged=True,
                    idempotency_key=key,
                    approved_root=fixture["root"],
                )
        live = sqlite3.connect(fixture["live_db"])
        try:
            self.assertEqual(live.execute("SELECT COUNT(*) FROM stage77_recovery_point_evidence").fetchone()[0], 0)
            self.assertEqual(live.execute("SELECT COUNT(*) FROM stage77_recovery_point_evidence_events").fetchone()[0], 0)
        finally:
            live.close()
        self.assertEqual((bundle / "database.sqlite3").read_bytes(), database_before)
        self.assertEqual((bundle / "manifest.json").read_bytes(), manifest_before)
        for filename, digest in bundle_file_hashes.items():
            self.assertEqual(recovery.digest_bytes((bundle / filename).read_bytes()), digest)

    def _artifact_manifest_item(self, fixture, fmt):
        return next(item for item in json.loads((fixture["bundle"] / "manifest.json").read_text(encoding="utf-8"))["artifacts"] if item["format"] == fmt)

    def _artifact_bundle_file(self, fixture, fmt):
        return fixture["bundle"] / self._artifact_manifest_item(fixture, fmt)["filename"]

    def _mutate_bundle_file(self, fixture, fmt, data):
        path = self._artifact_bundle_file(fixture, fmt)
        path.write_bytes(data(path.read_bytes()))

    def _assert_success_artifact_accepts_limitation(self, fixture, *, key):
        result = recovery.reconstruct_recovery_point_evidence(
            database_path=fixture["live_db"],
            recovery_root=fixture["recovery_root"],
            recovery_point_id=fixture["point_id"],
            actor="admin",
            rationale="successful artifact closed contract limitation",
            acknowledged=True,
            idempotency_key=key,
            approved_root=fixture["root"],
        )
        self.assertEqual(result["state"], "finalized")

    def _assert_zero_artifact_schema_rejection(self, bundle, live_db, point_id, expected, *, key):
        manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
        self._refresh_archived_database_binding(bundle, manifest)
        for attempt in range(2):
            with self.assertRaisesRegex(ValueError, expected):
                recovery.reconstruct_recovery_point_evidence(database_path=live_db, recovery_root=bundle.parent, recovery_point_id=point_id, actor="admin", rationale="zero artifact schema mutation", acknowledged=True, idempotency_key=key, approved_root=bundle.parent.parent)
        check = sqlite3.connect(live_db)
        self.assertEqual(check.execute("SELECT COUNT(*) FROM stage77_recovery_point_evidence").fetchone()[0], 0)
        self.assertEqual(check.execute("SELECT COUNT(*) FROM stage77_recovery_point_evidence_events").fetchone()[0], 0)
        check.close()

    def test_batch3b4b4a1_zero_artifact_positive_controls(self):
        controls = [
            ("legacy_table_present", lambda: self._legacy_zero_artifact_bundle()),
            ("diagnostic_zero_link", lambda: self._zero_artifact_historical_fixture(linked_successor=False)),
            ("point6_job1_job2", lambda: self._zero_artifact_historical_fixture()),
            ("post_correction_pre_authorization", lambda: self._zero_artifact_historical_fixture(post_correction=True)),
            ("producer_modern_point6", lambda: self._producer_modern_fixture("zero-artifact-producer")[:3]),
        ]
        for name, fixture in controls:
            with self.subTest(control=name):
                self.tearDown()
                self.setUp()
                bundle, live_db, point_id = fixture()
                manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
                self.assertEqual(manifest["counts"]["artifacts"], 0)
                self.assertEqual(manifest["artifacts"], [])
                self.assertEqual(recovery.validate_recovery_bundle(bundle)["state"], "valid")
                result = recovery.reconstruct_recovery_point_evidence(database_path=live_db, recovery_root=bundle.parent, recovery_point_id=point_id, actor="admin", rationale="zero artifact positive", acknowledged=True, idempotency_key=f"zero-artifact-positive-{name}", approved_root=bundle.parent.parent)
                self.assertEqual(result["state"], "finalized")
                replay = recovery.reconstruct_recovery_point_evidence(database_path=live_db, recovery_root=bundle.parent, recovery_point_id=point_id, actor="admin", rationale="zero artifact positive", acknowledged=True, idempotency_key=f"zero-artifact-positive-{name}", approved_root=bundle.parent.parent)
                self.assertEqual(replay["state"], "finalized")
                archived = sqlite3.connect(bundle / "database.sqlite3")
                self.assertEqual(archived.execute("SELECT COUNT(*) FROM record_governed_report_artifacts WHERE validation_state='valid'").fetchone()[0], 0)
                archived.close()

    def test_batch3b4b4a1_artifact_schema_presence_and_partial_groups(self):
        def replace_artifact_table(conn, columns):
            conn.execute("DROP TABLE record_governed_report_artifacts")
            conn.execute("CREATE TABLE record_governed_report_artifacts(" + ",".join(columns) + ")")

        partial_columns = {
            "missing_validation_state": ["id INTEGER PRIMARY KEY", "version_id INTEGER", "format TEXT", "storage_reference TEXT", "sha256 TEXT", "size_bytes INTEGER"],
            "missing_version_id": ["id INTEGER PRIMARY KEY", "format TEXT", "storage_reference TEXT", "sha256 TEXT", "size_bytes INTEGER", "validation_state TEXT"],
            "missing_format": ["id INTEGER PRIMARY KEY", "version_id INTEGER", "storage_reference TEXT", "sha256 TEXT", "size_bytes INTEGER", "validation_state TEXT"],
            "missing_storage": ["id INTEGER PRIMARY KEY", "version_id INTEGER", "format TEXT", "sha256 TEXT", "size_bytes INTEGER", "validation_state TEXT"],
            "missing_sha": ["id INTEGER PRIMARY KEY", "version_id INTEGER", "format TEXT", "storage_reference TEXT", "size_bytes INTEGER", "validation_state TEXT"],
            "missing_size": ["id INTEGER PRIMARY KEY", "version_id INTEGER", "format TEXT", "storage_reference TEXT", "sha256 TEXT", "validation_state TEXT"],
        }
        cases = [("table_absent", lambda c: c.execute("DROP TABLE record_governed_report_artifacts"))]
        cases.extend((name, lambda c, cols=columns: replace_artifact_table(c, cols)) for name, columns in partial_columns.items())
        cases.append(("mixed_schema_generation", lambda c: replace_artifact_table(c, ["id INTEGER PRIMARY KEY", "version_id INTEGER", "format TEXT", "storage_reference TEXT", "sha256 TEXT", "validation_state TEXT", "renderer_version TEXT"])))
        for index, (name, mutation) in enumerate(cases):
            with self.subTest(case=name):
                self.tearDown()
                self.setUp()
                bundle, live_db, point_id = self._zero_artifact_historical_fixture()
                archived = sqlite3.connect(bundle / "database.sqlite3")
                mutation(archived)
                archived.commit()
                archived.close()
                self._assert_zero_artifact_schema_rejection(bundle, live_db, point_id, "schema_incompatible", key=f"zero-artifact-schema-{index}")
        self.tearDown()
        self.setUp()
        bundle, _live_db, _point_id = self._zero_artifact_historical_fixture()
        self.assertEqual(recovery.validate_recovery_bundle(bundle)["state"], "valid")

    def test_batch3b4b4a1_artifact_sqlite_constraints_classify_impossible_rows(self):
        bundle, _live_db, _point_id, _job_ids = self._producer_modern_fixture("zero-artifact-constraints")
        archived = sqlite3.connect(bundle / "database.sqlite3")
        archived.execute("PRAGMA foreign_keys=ON")
        version_id = int(archived.execute("SELECT id FROM record_governed_report_versions ORDER BY id LIMIT 1").fetchone()[0])
        row_values = {
            "version_id": version_id,
            "format": "docx",
            "storage_reference": str(self.root / "artifacts" / "nonexistent-constraint"),
            "sha256": "a" * 64,
            "size_bytes": 123,
            "renderer_version": "2.0.0",
            "template_version": "cde-internal-v1",
            "generated_at": "2026-01-01T00:00:09Z",
            "validation_state": "valid",
            "diagnostics_json": "{}",
            "lifecycle_status": "current",
        }
        columns = [row[1] for row in archived.execute("PRAGMA table_info(record_governed_report_artifacts)").fetchall() if row[1] in row_values]

        def insert(values):
            archived.execute(
                f"INSERT INTO record_governed_report_artifacts({','.join(columns)}) VALUES({','.join('?' for _ in columns)})",
                tuple(values[column] for column in columns),
            )

        insert(row_values)
        with self.assertRaises(sqlite3.IntegrityError):
            insert(dict(row_values, storage_reference=str(self.root / "artifacts" / "duplicate-format")))
        archived.rollback()
        for column in columns:
            with self.subTest(null_column=column):
                values = dict(row_values)
                values[column] = None
                with self.assertRaises(sqlite3.IntegrityError):
                    insert(values)
                archived.rollback()
        with self.assertRaises(sqlite3.IntegrityError):
            insert(dict(row_values, version_id=999999))
        self.assertEqual(archived.execute("SELECT COUNT(*) FROM record_governed_report_artifacts").fetchone()[0], 0)
        archived.close()

    def test_batch3b4b4a1_injected_accepted_artifact_rows_reject_zero_artifact_states(self):
        cases = [
            ("single_stale_count", lambda c: self._insert_archived_artifact_row(c), None, "artifact_inventory_mismatch"),
            ("single_accurate_count", lambda c: self._insert_archived_artifact_row(c), lambda m: m["counts"].__setitem__("artifacts", 1), "artifact_inventory_mismatch"),
            ("multiple_stale_count", lambda c: (self._insert_archived_artifact_row(c, artifact_id=901, fmt="docx"), self._insert_archived_artifact_row(c, artifact_id=902, fmt="html")), None, "artifact_inventory_mismatch"),
            ("multiple_accurate_count", lambda c: (self._insert_archived_artifact_row(c, artifact_id=903, fmt="docx"), self._insert_archived_artifact_row(c, artifact_id=904, fmt="html")), lambda m: m["counts"].__setitem__("artifacts", 2), "artifact_inventory_mismatch"),
            ("valid_state_perfect_metadata", lambda c: self._insert_archived_artifact_row(c, artifact_id=905, fmt="pdf", sha="b" * 64, size=456), None, "artifact_inventory_mismatch"),
            ("manifest_inventory_rewritten_without_file", lambda c: self._insert_archived_artifact_row(c, artifact_id=906, fmt="docx"), lambda m: (m["counts"].__setitem__("artifacts", 1), m["artifacts"].append({"artifact_id": 906, "report_id": 7, "version_id": 11, "format": "docx", "filename": "artifacts/artifact-906-docx", "size_bytes": 123, "sha256": "a" * 64})), "bundle_file_inventory_invalid"),
        ]
        for index, (name, mutation, manifest_mutation, expected) in enumerate(cases):
            with self.subTest(case=name):
                self.tearDown()
                self.setUp()
                bundle, live_db, point_id = self._zero_artifact_historical_fixture()
                archived = sqlite3.connect(bundle / "database.sqlite3")
                mutation(archived)
                archived.commit()
                archived.close()
                self._assert_zero_artifact_rejection(bundle, live_db, point_id, expected, key=f"zero-artifact-injected-{index}", manifest_mutation=manifest_mutation)

    def test_batch3b4b4a1_blank_and_malformed_valid_artifact_rows_reject_before_file_access(self):
        cases = [
            ("blank_format", {"fmt": ""}),
            ("unknown_format", {"fmt": "unknown"}),
            ("blank_storage", {"storage": ""}),
            ("malformed_sha", {"sha": "not-a-digest"}),
            ("blank_sha", {"sha": ""}),
            ("negative_size", {"size": -1}),
            ("blank_renderer", {"renderer_version": ""}),
            ("blank_template", {"template_version": ""}),
            ("malformed_generated_at", {"generated_at": "not-a-time"}),
            ("malformed_diagnostics", {"diagnostics_json": "{not-json"}),
            ("blank_lifecycle", {"lifecycle_status": ""}),
            ("unknown_lifecycle", {"lifecycle_status": "unknown"}),
        ]
        for index, (name, overrides) in enumerate(cases):
            with self.subTest(case=name):
                self.tearDown()
                self.setUp()
                bundle, live_db, point_id, _job_ids = self._producer_modern_fixture(f"zero-artifact-malformed-{index}")
                archived = sqlite3.connect(bundle / "database.sqlite3")
                columns = [row[1] for row in archived.execute("PRAGMA table_info(record_governed_report_artifacts)").fetchall()]
                version_id = int(archived.execute("SELECT id FROM record_governed_report_versions ORDER BY id LIMIT 1").fetchone()[0])
                values = {
                    "id": 950 + index,
                    "version_id": version_id,
                    "format": overrides.get("fmt", "docx"),
                    "storage_reference": overrides.get("storage", str(self.root / "artifacts" / f"nonexistent-malformed-{index}")),
                    "sha256": overrides.get("sha", "a" * 64),
                    "size_bytes": overrides.get("size", 123),
                    "renderer_version": overrides.get("renderer_version", "2.0.0"),
                    "template_version": overrides.get("template_version", "cde-internal-v1"),
                    "generated_at": overrides.get("generated_at", "2026-01-01T00:00:09Z"),
                    "validation_state": "valid",
                    "diagnostics_json": overrides.get("diagnostics_json", "{}"),
                    "lifecycle_status": overrides.get("lifecycle_status", "current"),
                    "qualification_id": None,
                    "qualification_digest": None,
                    "disclosure_version": "standard-v1",
                }
                selected = [column for column in columns if column in values]
                archived.execute(
                    f"INSERT INTO record_governed_report_artifacts({','.join(selected)}) VALUES({','.join('?' for _ in selected)})",
                    tuple(values[column] for column in selected),
                )
                archived.commit()
                archived.close()
                self._assert_zero_artifact_rejection(bundle, live_db, point_id, "artifact_inventory_mismatch", key=f"zero-artifact-malformed-{index}")

    def test_batch3b4b4a1_non_valid_artifact_rows_are_not_accepted_authority(self):
        for state in ("invalid", "pending", "staged", "validation_failed"):
            with self.subTest(state=state):
                self.tearDown()
                self.setUp()
                bundle, live_db, point_id = self._zero_artifact_historical_fixture()
                archived = sqlite3.connect(bundle / "database.sqlite3")
                self._insert_archived_artifact_row(archived, artifact_id=920, state=state)
                archived.commit()
                archived.close()
                manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
                self._refresh_archived_database_binding(bundle, manifest)
                self.assertEqual(manifest["counts"]["artifacts"], 0)
                result = recovery.reconstruct_recovery_point_evidence(database_path=live_db, recovery_root=bundle.parent, recovery_point_id=point_id, actor="admin", rationale="non-valid artifact row", acknowledged=True, idempotency_key=f"zero-artifact-nonvalid-{state}", approved_root=bundle.parent.parent)
                self.assertEqual(result["state"], "finalized")

    def test_batch3b4b4a1_artifact_ownership_and_row_integrity_boundaries(self):
        cases = [
            ("other_version_same_report", lambda c: (c.execute("INSERT INTO record_governed_report_versions(id,report_id,lifecycle_status,specification_json,specification_digest) VALUES(99,7,'generated','{}',?)", (recovery.digest_bytes(b"{}"),)), self._insert_archived_artifact_row(c, artifact_id=930, version_id=99)), "artifact_inventory_mismatch"),
            ("other_report_version", lambda c: (c.execute("INSERT INTO record_governed_reports(id,lifecycle_status) VALUES(99,'generated')"), c.execute("INSERT INTO record_governed_report_versions(id,report_id,lifecycle_status,specification_json,specification_digest) VALUES(100,99,'generated','{}',?)", (recovery.digest_bytes(b"{}"),)), self._insert_archived_artifact_row(c, artifact_id=931, version_id=100)), "artifact_inventory_mismatch"),
            ("unknown_format", lambda c: self._insert_archived_artifact_row(c, artifact_id=932, fmt="unknown"), "artifact_inventory_mismatch"),
            ("malformed_sha", lambda c: self._insert_archived_artifact_row(c, artifact_id=933, sha="not-a-digest"), "artifact_inventory_mismatch"),
            ("negative_size", lambda c: self._insert_archived_artifact_row(c, artifact_id=934, size=-1), "artifact_inventory_mismatch"),
            ("blank_storage", lambda c: self._insert_archived_artifact_row(c, artifact_id=935, storage=""), "artifact_inventory_mismatch"),
        ]
        for index, (name, mutation, expected) in enumerate(cases):
            with self.subTest(case=name):
                self.tearDown()
                self.setUp()
                bundle, live_db, point_id = self._zero_artifact_historical_fixture()
                archived = sqlite3.connect(bundle / "database.sqlite3")
                mutation(archived)
                archived.commit()
                archived.close()
                self._assert_zero_artifact_rejection(bundle, live_db, point_id, expected, key=f"zero-artifact-row-{index}")

    def test_batch3b4b4b0_producer_successful_artifact_recovery_fixture(self):
        temp_name = None
        with tempfile.TemporaryDirectory(dir="/private/tmp", prefix="stage77-success-artifact-") as directory:
            temp_name = directory
            root = Path(directory)
            database = root / "records.sqlite3"
            artifact_root = root / "artifacts"
            recovery_root = root / "recovery"
            restore_root = root / "restore"
            artifact_root.mkdir()
            original_report_root = reports.REPORT_ROOT
            conn = sqlite3.connect(database)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys=ON")
            record = {"reference": "CR-1", "title": "Canonical record", "finding": "Original wording", "status": "recorded", "version": 1}

            def fake_render(specification, digest, output_dir, *_args, **_kwargs):
                self.assertEqual(reports.specification_digest(specification), digest)
                output_dir = Path(output_dir)
                self.assertTrue(output_dir.resolve(strict=False).is_relative_to(artifact_root.resolve(strict=False)))
                output_dir.mkdir(parents=True, exist_ok=False)
                artifacts = []
                for format_name in specification["requested_formats"]:
                    path = output_dir / f"report.{format_name}"
                    payload = f"{format_name}:{digest}:producer-success\n".encode("utf-8")
                    path.write_bytes(payload)
                    artifacts.append({
                        "format": format_name,
                        "path": str(path),
                        "sha256": recovery.digest_bytes(payload),
                        "size_bytes": len(payload),
                        "renderer_version": specification["publication_engine_version"],
                    })
                return {"artifacts": artifacts, "diagnostics": []}

            try:
                reports.REPORT_ROOT = artifact_root
                reports.ensure_report_tables(conn)
                qualifications.ensure_qualification_tables(conn)
                jobs.ensure_job_tables(conn)
                recovery.ensure_recovery_tables(conn)
                with patch.object(reports.rda, "record_context", return_value=record), patch.dict(os.environ, {qualifications.REVIEW_MODE_ENV: qualifications.SOLE_MODE}):
                    report = reports.create_report(
                        conn,
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
                        idempotency_key="successful-artifact-report",
                    )
                    for status, key in (("assembly_reviewed", "success-assembly"), ("privacy_reviewed", "success-privacy"), ("redaction_reviewed", "success-redaction"), ("approved_for_generation", "success-approval")):
                        report = reports.confirm_creator_gate(conn, report_id=report["id"], resulting_status=status, rationale="Sole administrator producer fixture", actor="nick", actor_role="administrator", acknowledged=True, idempotency_key=key)
                    version_id = int(report["versions"][-1]["id"])
                    chain = qualifications.validate_complete_chain(conn, version_id)
                    self.assertEqual([item["completed_gate"] for item in chain], ["assembly", "privacy", "redaction", "approval"])
                    job = jobs.enqueue_generation(conn, report_id=report["id"], actor="nick", governed_action="enqueue_generation", idempotency_key="successful-artifact-job")
                    claimed = jobs.claim_one(conn)
                    self.assertEqual(claimed["id"], job["id"])
                    conn.close()
                    with patch("api.report_rendering.render_frozen_report", side_effect=fake_render) as renderer:
                        jobs.execute_job(str(database), claimed)
                    self.assertEqual(renderer.call_count, 1)
            finally:
                reports.REPORT_ROOT = original_report_root
                try:
                    conn.close()
                except sqlite3.Error:
                    pass

            source = sqlite3.connect(database)
            source.row_factory = sqlite3.Row
            try:
                final_job = jobs.get_job(source, job["id"])
                self.assertEqual(final_job["state"], "succeeded")
                self.assertIsNone(final_job["retry_of_job_id"])
                self.assertEqual(source.execute("SELECT COUNT(*) FROM stage77_report_job_events WHERE job_id=? AND event_type='terminal' AND resulting_state='succeeded'", (job["id"],)).fetchone()[0], 1)
                artifact_rows = source.execute("SELECT * FROM record_governed_report_artifacts WHERE validation_state='valid' ORDER BY format").fetchall()
                expected_formats = list(final_job["requested_formats"])
                self.assertEqual([row["format"] for row in artifact_rows], expected_formats)
                self.assertEqual(len(artifact_rows), len(expected_formats))
                for row in artifact_rows:
                    path = Path(row["storage_reference"])
                    self.assertTrue(path.resolve(strict=False).is_relative_to(artifact_root.resolve(strict=False)))
                    self.assertTrue(path.is_file())
                    data = path.read_bytes()
                    self.assertEqual(len(data), row["size_bytes"])
                    self.assertEqual(recovery.digest_bytes(data), row["sha256"])
                    self.assertRegex(row["sha256"], r"^[0-9a-f]{64}$")
                    self.assertEqual(row["renderer_version"], "2.0.0")
                    self.assertEqual(row["template_version"], "cde-internal-v1")
                    self.assertEqual(row["validation_state"], "valid")
                    self.assertEqual(row["lifecycle_status"], "current")
                    self.assertEqual(row["qualification_id"], final_job["qualification_id"])
                    self.assertEqual(row["qualification_digest"], final_job["qualification_digest"])
                with self.assertRaises(sqlite3.IntegrityError):
                    source.execute(
                        "INSERT INTO record_governed_report_artifacts(version_id,format,storage_reference,sha256,size_bytes,renderer_version,template_version,generated_at,validation_state,diagnostics_json,lifecycle_status) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                        (version_id, expected_formats[0], str(artifact_root / "duplicate"), "0" * 64, 1, "2.0.0", "cde-internal-v1", "2026-01-01T00:00:00Z", "valid", "[]", "current"),
                    )
                source.rollback()
            finally:
                source.close()

            captured = recovery.capture_recovery_point(database_path=database, artifact_root=artifact_root, recovery_root=recovery_root, approved_root=root, actor="admin", governed_action="capture", idempotency_key="successful-artifact-capture")
            bundle = recovery_root / f"recovery-{captured['recovery_point_id']}"
            manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["counts"]["reports"], 1)
            self.assertEqual(manifest["counts"]["versions"], 1)
            self.assertEqual(manifest["counts"]["jobs"], 1)
            self.assertEqual(manifest["job_state_counts"]["succeeded"], 1)
            self.assertEqual(manifest["counts"]["artifacts"], 3)
            self.assertEqual({item["format"] for item in manifest["artifacts"]}, {"docx", "html", "pdf"})
            self.assertEqual(recovery.validate_recovery_bundle(bundle)["state"], "valid")

            archived = sqlite3.connect(bundle / "database.sqlite3")
            archived.row_factory = sqlite3.Row
            try:
                archived_rows = archived.execute("SELECT id,version_id,format,storage_reference,sha256,size_bytes FROM record_governed_report_artifacts WHERE validation_state='valid' ORDER BY id").fetchall()
                manifest_by_id = {item["artifact_id"]: item for item in manifest["artifacts"]}
                self.assertEqual(len(archived_rows), len(manifest_by_id))
                for row in archived_rows:
                    item = manifest_by_id[row["id"]]
                    bundle_file = bundle / item["filename"]
                    data = bundle_file.read_bytes()
                    self.assertEqual(item["version_id"], row["version_id"])
                    self.assertEqual(item["format"], row["format"])
                    self.assertEqual(item["size_bytes"], row["size_bytes"])
                    self.assertEqual(item["sha256"], row["sha256"])
                    self.assertEqual(len(data), item["size_bytes"])
                    self.assertEqual(recovery.digest_bytes(data), item["sha256"])
            finally:
                archived.close()

            live_db = root / "live.sqlite3"
            live = sqlite3.connect(live_db)
            recovery.ensure_recovery_tables(live)
            live.close()
            first = recovery.reconstruct_recovery_point_evidence(database_path=live_db, recovery_root=recovery_root, recovery_point_id=captured["recovery_point_id"], actor="admin", rationale="successful artifact fixture", acknowledged=True, idempotency_key="successful-artifact-evidence", approved_root=root)
            replay = recovery.reconstruct_recovery_point_evidence(database_path=live_db, recovery_root=recovery_root, recovery_point_id=captured["recovery_point_id"], actor="admin", rationale="successful artifact fixture", acknowledged=True, idempotency_key="successful-artifact-evidence", approved_root=root)
            self.assertEqual(replay["id"], first["id"])
            self.assertEqual(first["payload"]["artifact_count"], 3)
            with self.assertRaisesRegex(ValueError, "recovery_evidence_conflict"):
                recovery.reconstruct_recovery_point_evidence(database_path=live_db, recovery_root=recovery_root, recovery_point_id=captured["recovery_point_id"], actor="admin", rationale="successful artifact fixture conflict", acknowledged=True, idempotency_key="successful-artifact-evidence-conflict", approved_root=root)

            restore_root.mkdir()
            restored = recovery.restore_recovery_point(bundle_path=bundle, restore_root=restore_root, database_target=restore_root / "records.sqlite3", artifact_root_target=restore_root / "artifacts", live_database=database, live_artifact_root=artifact_root, live_recovery_root=recovery_root, actor="admin", governed_action="restore", approved_root=root)
            self.assertEqual(restored["state"], "restore_ready")
            for item in manifest["artifacts"]:
                restored_file = restore_root / "artifacts" / Path(item["filename"]).name
                self.assertTrue(restored_file.is_file())
                data = restored_file.read_bytes()
                self.assertEqual(len(data), item["size_bytes"])
                self.assertEqual(recovery.digest_bytes(data), item["sha256"])
        self.assertIsNotNone(temp_name)
        self.assertFalse(Path(temp_name).exists())

    def test_batch3b4b4b1_group_a_accepted_inventory_mutations(self):
        def delete_format(fmt):
            return lambda c, f: c.execute("DELETE FROM record_governed_report_artifacts WHERE format=?", (fmt,))

        def insert_artifact(fmt, *, version_id=None, artifact_id=900, state="valid"):
            def mutate(conn, fixture):
                base = fixture["artifact_rows"][0]
                conn.execute(
                    "INSERT INTO record_governed_report_artifacts(id,version_id,format,storage_reference,sha256,size_bytes,renderer_version,template_version,generated_at,validation_state,diagnostics_json,lifecycle_status,qualification_id,qualification_digest,disclosure_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        artifact_id,
                        version_id if version_id is not None else base["version_id"],
                        fmt,
                        base["storage_reference"],
                        base["sha256"],
                        base["size_bytes"],
                        base["renderer_version"],
                        base["template_version"],
                        base["generated_at"],
                        state,
                        base["diagnostics_json"],
                        base["lifecycle_status"],
                        base["qualification_id"],
                        base["qualification_digest"],
                        base["disclosure_version"],
                    ),
                )
            return mutate

        def clone_current_version(conn, fixture, version_id, *, report_id=None):
            source = dict(conn.execute("SELECT * FROM record_governed_report_versions WHERE id=?", (fixture["version_id"],)).fetchone())
            source["id"] = version_id
            source["version_number"] = version_id
            if report_id is not None:
                source["report_id"] = report_id
            columns = list(source)
            conn.execute(
                f"INSERT INTO record_governed_report_versions({','.join(columns)}) VALUES({','.join('?' for _ in columns)})",
                tuple(source[column] for column in columns),
            )

        def clone_current_report(conn, report_id):
            source = dict(conn.execute("SELECT * FROM record_governed_reports ORDER BY id LIMIT 1").fetchone())
            source["id"] = report_id
            if "idempotency_key" in source:
                source["idempotency_key"] = f"other-report-{report_id}"
            columns = list(source)
            conn.execute(
                f"INSERT INTO record_governed_reports({','.join(columns)}) VALUES({','.join('?' for _ in columns)})",
                tuple(source[column] for column in columns),
            )

        def duplicate_without_unique(conn, fixture):
            rows = [dict(row) for row in conn.execute("SELECT * FROM record_governed_report_artifacts ORDER BY id").fetchall()]
            columns = list(rows[0])
            declarations = []
            for info in conn.execute("PRAGMA table_info(record_governed_report_artifacts)").fetchall():
                name = info[1]
                column_type = info[2] or "TEXT"
                declaration = f"{name} {column_type}"
                if name == "id":
                    declaration += " PRIMARY KEY"
                declarations.append(declaration)
            conn.execute("DROP TABLE record_governed_report_artifacts")
            conn.execute("CREATE TABLE record_governed_report_artifacts(" + ",".join(declarations) + ")")
            for item in rows:
                conn.execute(
                    f"INSERT INTO record_governed_report_artifacts({','.join(columns)}) VALUES({','.join('?' for _ in columns)})",
                    tuple(item[column] for column in columns),
                )
            duplicate = dict(rows[0])
            duplicate["id"] = 990
            conn.execute(
                f"INSERT INTO record_governed_report_artifacts({','.join(columns)}) VALUES({','.join('?' for _ in columns)})",
                tuple(duplicate[column] for column in columns),
            )

        cases = [
            ("missing_docx", ["docx", "html", "pdf"], delete_format("docx"), "artifact_inventory_mismatch"),
            ("missing_html", ["docx", "html", "pdf"], delete_format("html"), "artifact_inventory_mismatch"),
            ("missing_pdf", ["docx", "html", "pdf"], delete_format("pdf"), "artifact_inventory_mismatch"),
            ("two_removed", ["docx", "html", "pdf"], lambda c, f: c.execute("DELETE FROM record_governed_report_artifacts WHERE format IN ('docx','html')"), "artifact_inventory_mismatch"),
            ("all_removed", ["docx", "html", "pdf"], lambda c, f: c.execute("DELETE FROM record_governed_report_artifacts"), "artifact_inventory_mismatch"),
            ("extra_recognized_unrequested", ["docx", "html"], insert_artifact("pdf", artifact_id=901), "artifact_inventory_mismatch"),
            ("extra_unknown", ["docx", "html", "pdf"], insert_artifact("xml", artifact_id=902), "artifact_inventory_mismatch"),
            ("extra_other_version", ["docx", "html", "pdf"], lambda c, f: (clone_current_version(c, f, 99), insert_artifact("docx", version_id=99, artifact_id=903)(c, f)), "artifact_inventory_mismatch"),
            ("extra_other_report", ["docx", "html", "pdf"], lambda c, f: (clone_current_report(c, 99), clone_current_version(c, f, 100, report_id=99), insert_artifact("docx", version_id=100, artifact_id=904)(c, f)), "artifact_inventory_mismatch"),
            ("wrong_format_set_same_count", ["docx", "html", "pdf"], lambda c, f: c.execute("UPDATE record_governed_report_artifacts SET format='xml' WHERE format='docx'"), "artifact_inventory_mismatch"),
            ("duplicate_without_unique_schema", ["docx", "html", "pdf"], duplicate_without_unique, "artifact_inventory_mismatch"),
            ("reclassified_to_non_valid", ["docx", "html", "pdf"], lambda c, f: c.execute("UPDATE record_governed_report_artifacts SET validation_state='invalid' WHERE format='docx'"), "artifact_inventory_mismatch"),
            ("residue_reclassified_valid", ["docx", "html", "pdf"], lambda c, f: (insert_artifact("xml", artifact_id=905, state="invalid")(c, f), c.execute("UPDATE record_governed_report_artifacts SET validation_state='valid' WHERE id=905")), "artifact_inventory_mismatch"),
        ]
        for index, (name, formats, mutation, expected) in enumerate(cases):
            with self.subTest(case=name):
                self.tearDown(); self.setUp()
                fixture = self._successful_artifact_fixture(f"artifact-a-{index}", requested_formats=formats)
                archived = sqlite3.connect(fixture["bundle"] / "database.sqlite3")
                archived.row_factory = sqlite3.Row
                mutation(archived, fixture)
                archived.commit(); archived.close()
                self._assert_success_artifact_rejection(fixture, expected, key=f"artifact-a-{index}", update_database=True)

        self.tearDown(); self.setUp()
        fixture = self._successful_artifact_fixture("artifact-a-duplicate-real")
        archived = sqlite3.connect(fixture["bundle"] / "database.sqlite3")
        archived.row_factory = sqlite3.Row
        with self.assertRaises(sqlite3.IntegrityError):
            insert_artifact("docx", artifact_id=999)(archived, fixture)
        archived.rollback()
        self.assertEqual(archived.execute("SELECT COUNT(*) FROM record_governed_report_artifacts WHERE format='docx'").fetchone()[0], 1)
        archived.close()

    def test_batch3b4b4b1_groups_b_c_d_bound_row_manifest_and_file_identity(self):
        def row(fmt, fixture):
            return next(item for item in fixture["artifact_rows"] if item["format"] == fmt)

        def mutate_manifest_artifact_id(manifest, old_id, new_id):
            for item in manifest["artifacts"]:
                if item["artifact_id"] == old_id:
                    item["artifact_id"] = new_id
                    return

        cases = [
            ("manifest_unknown_id", lambda c, f, m: mutate_manifest_artifact_id(m, row("docx", f)["id"], 9999), "manifest_invalid", False, False),
            ("row_id_changed_stale_manifest", lambda c, f, m: c.execute("UPDATE record_governed_report_artifacts SET id=999 WHERE format='docx'"), "artifact_inventory_mismatch", True, False),
            ("row_and_manifest_id_changed_consistent", lambda c, f, m: (c.execute("UPDATE record_governed_report_artifacts SET id=998 WHERE format='docx'"), mutate_manifest_artifact_id(m, row("docx", f)["id"], 998)), "manifest_invalid", False, False),
            ("version_changed_unknown", lambda c, f, m: (c.execute("PRAGMA foreign_keys=OFF"), c.execute("UPDATE record_governed_report_artifacts SET version_id=999 WHERE format='docx'")), "foreign_key_check_failed", True, False),
            ("two_ids_swapped", lambda c, f, m: (c.execute("UPDATE record_governed_report_artifacts SET id=1000 WHERE format='docx'"), c.execute("UPDATE record_governed_report_artifacts SET id=? WHERE format='html'", (row("docx", f)["id"],)), c.execute("UPDATE record_governed_report_artifacts SET id=? WHERE id=1000", (row("html", f)["id"],))), "artifact_inventory_mismatch", True, False),
            ("html_relabelled_unknown", lambda c, f, m: c.execute("UPDATE record_governed_report_artifacts SET format='xml' WHERE format='html'"), "artifact_inventory_mismatch", True, False),
            ("unknown_format", lambda c, f, m: c.execute("UPDATE record_governed_report_artifacts SET format='xml' WHERE format='docx'"), "artifact_inventory_mismatch", True, False),
            ("blank_format", lambda c, f, m: c.execute("UPDATE record_governed_report_artifacts SET format='' WHERE format='docx'"), "artifact_inventory_mismatch", True, False),
            ("case_variant_format", lambda c, f, m: c.execute("UPDATE record_governed_report_artifacts SET format='DOCX' WHERE format='docx'"), "artifact_inventory_mismatch", True, False),
            ("padded_format", lambda c, f, m: c.execute("UPDATE record_governed_report_artifacts SET format=' docx ' WHERE format='docx'"), "artifact_inventory_mismatch", True, False),
            ("row_manifest_format_changed", lambda c, f, m: (c.execute("UPDATE record_governed_report_artifacts SET format='xml' WHERE format='docx'"), [item.update({"format": "xml"}) for item in m["artifacts"] if item["artifact_id"] == row("docx", f)["id"]]), "artifact_inventory_mismatch", True, False),
            ("row_size_small", lambda c, f, m: c.execute("UPDATE record_governed_report_artifacts SET size_bytes=size_bytes-1 WHERE format='docx'"), "artifact_inventory_mismatch", True, False),
            ("row_size_large", lambda c, f, m: c.execute("UPDATE record_governed_report_artifacts SET size_bytes=size_bytes+1 WHERE format='html'"), "artifact_inventory_mismatch", True, False),
            ("row_size_zero", lambda c, f, m: c.execute("UPDATE record_governed_report_artifacts SET size_bytes=0 WHERE format='pdf'"), "artifact_inventory_mismatch", True, False),
            ("row_size_negative", lambda c, f, m: c.execute("UPDATE record_governed_report_artifacts SET size_bytes=-1 WHERE format='docx'"), "artifact_inventory_mismatch", True, False),
            ("row_sha_valid_other", lambda c, f, m: c.execute("UPDATE record_governed_report_artifacts SET sha256=? WHERE format='docx'", ("b" * 64,)), "artifact_inventory_mismatch", True, False),
            ("row_sha_malformed", lambda c, f, m: c.execute("UPDATE record_governed_report_artifacts SET sha256='not-a-digest' WHERE format='html'"), "artifact_inventory_mismatch", True, False),
            ("row_sha_uppercase", lambda c, f, m: c.execute("UPDATE record_governed_report_artifacts SET sha256=? WHERE format='pdf'", (row("pdf", f)["sha256"].upper(),)), "artifact_inventory_mismatch", True, False),
            ("row_sha_blank", lambda c, f, m: c.execute("UPDATE record_governed_report_artifacts SET sha256='' WHERE format='docx'"), "artifact_inventory_mismatch", True, False),
            ("manifest_matches_false_size", lambda c, f, m: (c.execute("UPDATE record_governed_report_artifacts SET size_bytes=size_bytes+1 WHERE format='docx'"), [item.update({"size_bytes": item["size_bytes"] + 1}) for item in m["artifacts"] if item["format"] == "docx"]), "artifact_digest_mismatch", True, False),
            ("manifest_matches_false_sha", lambda c, f, m: (c.execute("UPDATE record_governed_report_artifacts SET sha256=? WHERE format='html'", ("c" * 64,)), [item.update({"sha256": "c" * 64}) for item in m["artifacts"] if item["format"] == "html"]), "artifact_digest_mismatch", True, False),
            ("database_digest_stale", lambda c, f, m: c.execute("UPDATE record_governed_report_artifacts SET sha256=? WHERE format='docx'", ("d" * 64,)), "database_digest_mismatch", False, False),
            ("row_manifest_database_recomputed", lambda c, f, m: (c.execute("UPDATE record_governed_report_artifacts SET sha256=? WHERE format='pdf'", ("e" * 64,)), [item.update({"sha256": "e" * 64}) for item in m["artifacts"] if item["format"] == "pdf"]), "artifact_digest_mismatch", True, False),
            ("sha_values_swapped", lambda c, f, m: c.execute("UPDATE record_governed_report_artifacts SET sha256=CASE format WHEN 'docx' THEN ? WHEN 'html' THEN ? ELSE sha256 END", (row("html", f)["sha256"], row("docx", f)["sha256"])), "artifact_inventory_mismatch", True, False),
            ("all_row_digests_replaced", lambda c, f, m: c.execute("UPDATE record_governed_report_artifacts SET sha256=?", ("f" * 64,)), "artifact_inventory_mismatch", True, False),
        ]
        for index, (name, mutation, expected, update_database, update_artifacts) in enumerate(cases):
            with self.subTest(case=name):
                self.tearDown(); self.setUp()
                fixture = self._successful_artifact_fixture(f"artifact-bcd-{index}")
                manifest = json.loads((fixture["bundle"] / "manifest.json").read_text(encoding="utf-8"))
                archived = sqlite3.connect(fixture["bundle"] / "database.sqlite3")
                archived.row_factory = sqlite3.Row
                mutation(archived, fixture, manifest)
                archived.commit(); archived.close()
                self._rewrite_manifest(fixture["bundle"], manifest)
                self._assert_success_artifact_rejection(fixture, expected, key=f"artifact-bcd-{index}", update_database=update_database, update_artifacts=update_artifacts)

    def test_batch3b4b4b1_storage_and_database_only_metadata_boundaries(self):
        accepted_limitations = [
            ("blank_storage_reference", lambda c, f: c.execute("UPDATE record_governed_report_artifacts SET storage_reference='' WHERE format='docx'")),
            ("external_storage_reference", lambda c, f: c.execute("UPDATE record_governed_report_artifacts SET storage_reference='/outside/report.docx' WHERE format='docx'")),
            ("parent_traversal_reference", lambda c, f: c.execute("UPDATE record_governed_report_artifacts SET storage_reference='../report.docx' WHERE format='docx'")),
            ("path_to_other_accepted_format", lambda c, f: c.execute("UPDATE record_governed_report_artifacts SET storage_reference=(SELECT storage_reference FROM record_governed_report_artifacts WHERE format='html') WHERE format='docx'")),
            ("missing_sibling_reference", lambda c, f: c.execute("UPDATE record_governed_report_artifacts SET storage_reference=? WHERE format='docx'", (str(f["artifact_root"] / "missing.docx"),))),
            ("padded_storage_reference", lambda c, f: c.execute("UPDATE record_governed_report_artifacts SET storage_reference='  report.docx  ' WHERE format='docx'")),
            ("storage_references_swapped", lambda c, f: c.execute("UPDATE record_governed_report_artifacts SET storage_reference=CASE format WHEN 'docx' THEN (SELECT storage_reference FROM record_governed_report_artifacts WHERE format='html') WHEN 'html' THEN (SELECT storage_reference FROM record_governed_report_artifacts WHERE format='docx') ELSE storage_reference END")),
            ("renderer_version_drift", lambda c, f: c.execute("UPDATE record_governed_report_artifacts SET renderer_version='9.9.9' WHERE format='docx'")),
            ("blank_renderer_version", lambda c, f: c.execute("UPDATE record_governed_report_artifacts SET renderer_version='' WHERE format='docx'")),
            ("template_version_drift", lambda c, f: c.execute("UPDATE record_governed_report_artifacts SET template_version='other-template' WHERE format='docx'")),
            ("blank_template_version", lambda c, f: c.execute("UPDATE record_governed_report_artifacts SET template_version='' WHERE format='docx'")),
            ("generated_timestamp_malformed", lambda c, f: c.execute("UPDATE record_governed_report_artifacts SET generated_at='not-a-time' WHERE format='docx'")),
            ("generated_before_job", lambda c, f: c.execute("UPDATE record_governed_report_artifacts SET generated_at='2000-01-01T00:00:00Z' WHERE format='docx'")),
            ("generated_after_success", lambda c, f: c.execute("UPDATE record_governed_report_artifacts SET generated_at='2999-01-01T00:00:00Z' WHERE format='docx'")),
            ("diagnostics_json_malformed", lambda c, f: c.execute("UPDATE record_governed_report_artifacts SET diagnostics_json='{not-json' WHERE format='docx'")),
            ("diagnostics_json_changed", lambda c, f: c.execute("UPDATE record_governed_report_artifacts SET diagnostics_json=? WHERE format='docx'", (reports.canonical_json({"changed": True}),))),
            ("lifecycle_status_changed", lambda c, f: c.execute("UPDATE record_governed_report_artifacts SET lifecycle_status='changed' WHERE format='docx'")),
            ("blank_lifecycle_status", lambda c, f: c.execute("UPDATE record_governed_report_artifacts SET lifecycle_status='' WHERE format='docx'")),
            ("qualification_identity_changed", lambda c, f: c.execute("UPDATE record_governed_report_artifacts SET qualification_id=999 WHERE format='docx'")),
            ("qualification_digest_changed", lambda c, f: c.execute("UPDATE record_governed_report_artifacts SET qualification_digest=? WHERE format='docx'", ("a" * 64,))),
            ("qualification_identity_digest_joint", lambda c, f: c.execute("UPDATE record_governed_report_artifacts SET qualification_id=qualification_id, qualification_digest=? WHERE format='docx'", ("b" * 64,))),
            ("disclosure_version_changed", lambda c, f: c.execute("UPDATE record_governed_report_artifacts SET disclosure_version='other-disclosure' WHERE format='docx'")),
            ("disclosure_version_removed", lambda c, f: c.execute("UPDATE record_governed_report_artifacts SET disclosure_version=NULL WHERE format='docx'")),
        ]
        for index, (name, mutation) in enumerate(accepted_limitations):
            with self.subTest(case=name):
                self.tearDown(); self.setUp()
                fixture = self._successful_artifact_fixture(f"artifact-db-only-{index}")
                archived = sqlite3.connect(fixture["bundle"] / "database.sqlite3")
                archived.row_factory = sqlite3.Row
                mutation(archived, fixture)
                archived.commit(); archived.close()
                manifest = json.loads((fixture["bundle"] / "manifest.json").read_text(encoding="utf-8"))
                self._refresh_archived_database_binding(fixture["bundle"], manifest)
                result = recovery.reconstruct_recovery_point_evidence(database_path=fixture["live_db"], recovery_root=fixture["recovery_root"], recovery_point_id=fixture["point_id"], actor="admin", rationale="database-only artifact limitation", acknowledged=True, idempotency_key=f"artifact-db-only-{index}", approved_root=fixture["root"])
                self.assertEqual(result["state"], "finalized")

    def test_batch3b4b4b1_positive_order_and_sparse_identity_controls(self):
        fixture = self._successful_artifact_fixture("artifact-positive-order")
        first = recovery.reconstruct_recovery_point_evidence(database_path=fixture["live_db"], recovery_root=fixture["recovery_root"], recovery_point_id=fixture["point_id"], actor="admin", rationale="successful artifact positive", acknowledged=True, idempotency_key="artifact-positive-order", approved_root=fixture["root"])
        replay = recovery.reconstruct_recovery_point_evidence(database_path=fixture["live_db"], recovery_root=fixture["recovery_root"], recovery_point_id=fixture["point_id"], actor="admin", rationale="successful artifact positive", acknowledged=True, idempotency_key="artifact-positive-order", approved_root=fixture["root"])
        self.assertEqual(first["id"], replay["id"])
        self.assertEqual(first["payload"]["artifact_count"], 3)
        archived = sqlite3.connect(fixture["bundle"] / "database.sqlite3")
        archived.row_factory = sqlite3.Row
        before_digest = recovery.digest_bytes((fixture["bundle"] / "database.sqlite3").read_bytes())
        self.assertEqual([row[0] for row in archived.execute("SELECT format FROM record_governed_report_artifacts ORDER BY format").fetchall()], ["docx", "html", "pdf"])
        archived.close()
        self.assertEqual(before_digest, recovery.digest_bytes((fixture["bundle"] / "database.sqlite3").read_bytes()))
        self.tearDown(); self.setUp()
        ordered = self._successful_artifact_fixture("artifact-physical-order")
        archived = sqlite3.connect(ordered["bundle"] / "database.sqlite3")
        archived.row_factory = sqlite3.Row
        rows = [dict(row) for row in archived.execute("SELECT * FROM record_governed_report_artifacts ORDER BY id").fetchall()]
        columns = list(rows[0])
        archived.execute("DELETE FROM record_governed_report_artifacts")
        for row in reversed(rows):
            archived.execute(
                f"INSERT INTO record_governed_report_artifacts({','.join(columns)}) VALUES({','.join('?' for _ in columns)})",
                tuple(row[column] for column in columns),
            )
        archived.commit(); archived.close()
        manifest = json.loads((ordered["bundle"] / "manifest.json").read_text(encoding="utf-8"))
        self._refresh_archived_database_binding(ordered["bundle"], manifest)
        result = recovery.reconstruct_recovery_point_evidence(database_path=ordered["live_db"], recovery_root=ordered["recovery_root"], recovery_point_id=ordered["point_id"], actor="admin", rationale="physical artifact order", acknowledged=True, idempotency_key="artifact-physical-order", approved_root=ordered["root"])
        self.assertEqual(result["state"], "finalized")

    def test_batch3b4b4b2_group_a_bundle_inventory_mutations(self):
        def remove(fmt):
            return lambda f: self._artifact_bundle_file(f, fmt).unlink()

        def rename(fmt, suffix):
            return lambda f: self._artifact_bundle_file(f, fmt).rename(self._artifact_bundle_file(f, fmt).with_name(self._artifact_bundle_file(f, fmt).name + suffix))

        cases = [
            ("missing_docx", remove("docx"), "bundle_file_inventory_invalid"),
            ("missing_html", remove("html"), "bundle_file_inventory_invalid"),
            ("missing_pdf", remove("pdf"), "bundle_file_inventory_invalid"),
            ("missing_two", lambda f: (self._artifact_bundle_file(f, "docx").unlink(), self._artifact_bundle_file(f, "html").unlink()), "bundle_file_inventory_invalid"),
            ("missing_all", lambda f: [self._artifact_bundle_file(f, fmt).unlink() for fmt in ("docx", "html", "pdf")], "bundle_file_inventory_invalid"),
            ("extra_regular", lambda f: (f["bundle"] / "artifacts" / "extra.bin").write_bytes(b"extra"), "bundle_file_inventory_invalid"),
            ("extra_accepted_name", lambda f: (f["bundle"] / "artifacts" / "artifact-999-docx").write_bytes(b"extra"), "bundle_file_inventory_invalid"),
            ("duplicate_copy", lambda f: (f["bundle"] / "artifacts" / "copy-docx").write_bytes(self._artifact_bundle_file(f, "docx").read_bytes()), "bundle_file_inventory_invalid"),
            ("rename_docx", rename("docx", ".renamed"), "bundle_file_inventory_invalid"),
            ("rename_html", rename("html", ".renamed"), "bundle_file_inventory_invalid"),
            ("rename_pdf", rename("pdf", ".renamed"), "bundle_file_inventory_invalid"),
            ("swap_two_names", lambda f: (self._artifact_bundle_file(f, "docx").rename(f["bundle"] / "artifacts" / "tmp-swap"), self._artifact_bundle_file(f, "html").rename(self._artifact_bundle_file(f, "docx")), (f["bundle"] / "artifacts" / "tmp-swap").rename(self._artifact_bundle_file(f, "html"))), "artifact_digest_mismatch"),
            ("cycle_names", lambda f: (self._artifact_bundle_file(f, "docx").rename(f["bundle"] / "artifacts" / "tmp-cycle"), self._artifact_bundle_file(f, "html").rename(self._artifact_bundle_file(f, "docx")), self._artifact_bundle_file(f, "pdf").rename(self._artifact_bundle_file(f, "html")), (f["bundle"] / "artifacts" / "tmp-cycle").rename(self._artifact_bundle_file(f, "pdf"))), "artifact_digest_mismatch"),
            ("unexpected_nested_file", lambda f: ((f["bundle"] / "artifacts" / "nested").mkdir(), (f["bundle"] / "artifacts" / "nested" / "artifact").write_bytes(b"extra")), "bundle_file_inventory_invalid"),
            ("non_empty_unexpected_dir", lambda f: ((f["bundle"] / "unexpected").mkdir(), (f["bundle"] / "unexpected" / "file").write_bytes(b"extra")), "bundle_file_inventory_invalid"),
        ]
        for index, (name, mutation, expected) in enumerate(cases):
            with self.subTest(case=name):
                self.tearDown(); self.setUp()
                fixture = self._successful_artifact_fixture(f"artifact-b2-a-{index}")
                mutation(fixture)
                self._assert_success_artifact_rejection(fixture, expected, key=f"artifact-b2-a-{index}", update_database=False)

        self.tearDown(); self.setUp()
        fixture = self._successful_artifact_fixture("artifact-b2-a-empty-dir")
        (fixture["bundle"] / "artifacts" / "empty").mkdir()
        self._assert_success_artifact_accepts_limitation(fixture, key="artifact-b2-a-empty-dir")

    def test_batch3b4b4b2_group_b_stale_file_byte_mutations(self):
        replacements = [
            ("empty", "docx", lambda b: b""),
            ("truncate_one", "html", lambda b: b[:-1]),
            ("truncate_many", "pdf", lambda b: b[:5]),
            ("append_one", "docx", lambda b: b + b"!"),
            ("append_many", "html", lambda b: b + b"changed"),
            ("first_byte", "pdf", lambda b: bytes([(b[0] + 1) % 255]) + b[1:]),
            ("middle_byte", "docx", lambda b: b[: len(b)//2] + bytes([(b[len(b)//2] + 1) % 255]) + b[len(b)//2 + 1:]),
            ("last_byte", "html", lambda b: b[:-1] + bytes([(b[-1] + 1) % 255])),
            ("replace_shorter", "pdf", lambda b: b"short"),
            ("replace_longer", "docx", lambda b: b + b"-longer-replacement"),
            ("replace_equal", "html", lambda b: b"X" * len(b)),
        ]
        for index, (name, fmt, mutate) in enumerate(replacements):
            with self.subTest(case=name, format=fmt):
                self.tearDown(); self.setUp()
                fixture = self._successful_artifact_fixture(f"artifact-b2-b-{index}")
                self._mutate_bundle_file(fixture, fmt, mutate)
                self._assert_success_artifact_rejection(fixture, "artifact_digest_mismatch", key=f"artifact-b2-b-{index}", update_database=False)

        swaps = [
            ("docx_html_bytes", ("docx", "html")),
            ("html_pdf_bytes", ("html", "pdf")),
            ("pdf_docx_bytes", ("pdf", "docx")),
        ]
        for index, (name, (target, source)) in enumerate(swaps, start=len(replacements)):
            with self.subTest(case=name):
                self.tearDown(); self.setUp()
                fixture = self._successful_artifact_fixture(f"artifact-b2-b-{index}")
                self._artifact_bundle_file(fixture, target).write_bytes(self._artifact_bundle_file(fixture, source).read_bytes())
                self._assert_success_artifact_rejection(fixture, "artifact_digest_mismatch", key=f"artifact-b2-b-{index}", update_database=False)

        self.tearDown(); self.setUp()
        fixture = self._successful_artifact_fixture("artifact-b2-b-swap-two")
        docx = self._artifact_bundle_file(fixture, "docx").read_bytes()
        html = self._artifact_bundle_file(fixture, "html").read_bytes()
        self._artifact_bundle_file(fixture, "docx").write_bytes(html)
        self._artifact_bundle_file(fixture, "html").write_bytes(docx)
        self._assert_success_artifact_rejection(fixture, "artifact_digest_mismatch", key="artifact-b2-b-swap-two", update_database=False)

        self.tearDown(); self.setUp()
        fixture = self._successful_artifact_fixture("artifact-b2-b-swap-all")
        data = {fmt: self._artifact_bundle_file(fixture, fmt).read_bytes() for fmt in ("docx", "html", "pdf")}
        self._artifact_bundle_file(fixture, "docx").write_bytes(data["html"])
        self._artifact_bundle_file(fixture, "html").write_bytes(data["pdf"])
        self._artifact_bundle_file(fixture, "pdf").write_bytes(data["docx"])
        self._assert_success_artifact_rejection(fixture, "artifact_digest_mismatch", key="artifact-b2-b-swap-all", update_database=False)

    def test_batch3b4b4b2_group_c_recomputed_claims_and_closed_contract_limit(self):
        def set_manifest_claim(manifest, fmt, *, data=None, size=None, sha=None):
            item = next(item for item in manifest["artifacts"] if item["format"] == fmt)
            if data is not None:
                item["size_bytes"] = len(data)
                item["sha256"] = recovery.digest_bytes(data)
            if size is not None:
                item["size_bytes"] = size
            if sha is not None:
                item["sha256"] = sha

        def set_row_claim(bundle, fmt, data):
            conn = sqlite3.connect(bundle / "database.sqlite3")
            try:
                conn.execute(
                    "UPDATE record_governed_report_artifacts SET size_bytes=?, sha256=? WHERE format=?",
                    (len(data), recovery.digest_bytes(data), fmt),
                )
                conn.commit()
            finally:
                conn.close()

        rejected = [
            ("manifest_size_only", lambda f, m, d: set_manifest_claim(m, "docx", size=len(d) + 1), "artifact_inventory_mismatch", True),
            ("manifest_sha_only", lambda f, m, d: set_manifest_claim(m, "html", sha="a" * 64), "artifact_inventory_mismatch", True),
            ("manifest_size_sha_only", lambda f, m, d: set_manifest_claim(m, "pdf", data=d), "artifact_inventory_mismatch", True),
            ("row_size_sha_only", lambda f, m, d: set_row_claim(f["bundle"], "docx", d), "artifact_inventory_mismatch", True),
            ("row_manifest_database_stale", lambda f, m, d: (set_row_claim(f["bundle"], "html", d), set_manifest_claim(m, "html", data=d)), "database_digest_mismatch", False),
            ("all_files_rows_manifest_stale_db", lambda f, m, d: (set_row_claim(f["bundle"], "docx", d), set_manifest_claim(m, "docx", data=d)), "database_digest_mismatch", False),
        ]
        for index, (name, mutation, expected, refresh_db) in enumerate(rejected):
            with self.subTest(case=name):
                self.tearDown(); self.setUp()
                fixture = self._successful_artifact_fixture(f"artifact-b2-c-{index}")
                path = self._artifact_bundle_file(fixture, "docx" if "docx" in name else "html" if "html" in name else "pdf")
                data = path.read_bytes() + b"-changed"
                path.write_bytes(data)
                manifest = json.loads((fixture["bundle"] / "manifest.json").read_text(encoding="utf-8"))
                mutation(fixture, manifest, data)
                self._rewrite_manifest(fixture["bundle"], manifest)
                self._assert_success_artifact_rejection(fixture, expected, key=f"artifact-b2-c-{index}", update_database=refresh_db)

        accepted = [
            ("file_row_manifest_database_consistent", ("docx",)),
            ("all_files_rows_manifest_database_consistent", ("docx", "html", "pdf")),
        ]
        for index, (name, formats) in enumerate(accepted, start=len(rejected)):
            with self.subTest(case=name):
                self.tearDown(); self.setUp()
                fixture = self._successful_artifact_fixture(f"artifact-b2-c-{index}")
                manifest = json.loads((fixture["bundle"] / "manifest.json").read_text(encoding="utf-8"))
                for fmt in formats:
                    data = self._artifact_bundle_file(fixture, fmt).read_bytes() + f"-{name}".encode("ascii")
                    self._artifact_bundle_file(fixture, fmt).write_bytes(data)
                    set_row_claim(fixture["bundle"], fmt, data)
                    set_manifest_claim(manifest, fmt, data=data)
                self._rewrite_manifest(fixture["bundle"], manifest)
                self._refresh_archived_database_binding(fixture["bundle"], manifest)
                self._assert_success_artifact_accepts_limitation(fixture, key=f"artifact-b2-c-{index}")

    def test_batch3b4b4b2_group_d_source_capture_confinement(self):
        def source_row(fixture, fmt="docx"):
            return next(row for row in fixture["artifact_rows"] if row["format"] == fmt)

        def capture_with_storage(name, storage_reference, *, expected=None):
            fixture = self._successful_artifact_fixture(name, capture=False)
            if callable(storage_reference):
                storage_reference = storage_reference(fixture)
            conn = sqlite3.connect(fixture["database"])
            try:
                conn.execute("UPDATE record_governed_report_artifacts SET storage_reference=? WHERE format='docx'", (str(storage_reference),))
                conn.commit()
            finally:
                conn.close()
            if expected is None:
                captured = recovery.capture_recovery_point(database_path=fixture["database"], artifact_root=fixture["artifact_root"], recovery_root=fixture["recovery_root"], approved_root=fixture["root"], actor="admin", governed_action="capture", idempotency_key=f"{name}-capture")
                self.assertEqual(captured["state"], "completed")
                return
            with self.assertRaisesRegex(recovery.RecoveryOperationFailure, expected):
                recovery.capture_recovery_point(database_path=fixture["database"], artifact_root=fixture["artifact_root"], recovery_root=fixture["recovery_root"], approved_root=fixture["root"], actor="admin", governed_action="capture", idempotency_key=f"{name}-capture")
            stage_root = fixture["recovery_root"] / ".stage"
            if stage_root.exists():
                self.assertEqual(list(stage_root.iterdir()), [])

        self.tearDown(); self.setUp()
        valid = self._successful_artifact_fixture("artifact-b2-d-valid", capture=False)
        captured = recovery.capture_recovery_point(database_path=valid["database"], artifact_root=valid["artifact_root"], recovery_root=valid["recovery_root"], approved_root=valid["root"], actor="admin", governed_action="capture", idempotency_key="artifact-b2-d-valid-capture")
        self.assertEqual(captured["state"], "completed")

        def original_path(fixture):
            return Path(source_row(fixture)["storage_reference"])

        def sibling_path(fixture):
            original = original_path(fixture)
            sibling = fixture["root"] / "sibling.docx"
            sibling.write_bytes(original.read_bytes())
            return sibling

        def outside_path(fixture):
            original = original_path(fixture)
            outside = fixture["root"] / "outer" / "outside.docx"
            outside.parent.mkdir()
            outside.write_bytes(original.read_bytes())
            return outside

        def dotdot_inside(fixture):
            original = original_path(fixture)
            sub = original.parent / "sub"
            sub.mkdir(exist_ok=True)
            return sub / ".." / original.name

        def directory_source(fixture):
            directory = fixture["artifact_root"] / "directory-source"
            directory.mkdir()
            return directory

        def inside_symlink(fixture):
            link = fixture["artifact_root"] / "inside-link.docx"
            link.symlink_to(original_path(fixture))
            return link

        def outside_symlink(fixture):
            link = fixture["artifact_root"] / "outside-link.docx"
            link.symlink_to(sibling_path(fixture))
            return link

        def broken_symlink(fixture):
            link = fixture["artifact_root"] / "broken-link.docx"
            link.symlink_to(fixture["artifact_root"] / "does-not-exist.docx")
            return link

        def other_accepted_source(fixture):
            return next(row for row in fixture["artifact_rows"] if row["format"] == "html")["storage_reference"]

        def intermediate_symlink_escape(fixture):
            original = original_path(fixture)
            outside_dir = fixture["root"] / "outside-source-dir"
            outside_dir.mkdir()
            outside_file = outside_dir / original.name
            outside_file.write_bytes(original.read_bytes())
            link_dir = fixture["artifact_root"] / "linked-dir"
            link_dir.symlink_to(outside_dir, target_is_directory=True)
            return link_dir / original.name

        def symlink_loop(fixture):
            link = fixture["artifact_root"] / "loop.docx"
            link.symlink_to(link)
            return link

        cases = []
        cases.extend([
            ("absolute_outside_artifact_root", outside_path, "artifact_outside_root"),
            ("sibling_outside_artifact_root", sibling_path, "artifact_outside_root"),
            ("parent_traversal_outside", lambda f: f["artifact_root"] / ".." / "sibling.docx", "artifact_invalid|artifact_outside_root"),
            ("redundant_dot_inside", lambda f: original_path(f).parent / "." / original_path(f).name, None),
            ("dotdot_resolves_inside", dotdot_inside, None),
            ("missing_file", lambda f: f["artifact_root"] / "missing.docx", "artifact_invalid"),
            ("directory_source", directory_source, "artifact_invalid"),
            ("source_is_symlink_inside", inside_symlink, "artifact_invalid"),
            ("source_is_symlink_outside", outside_symlink, "artifact_invalid"),
            ("source_resolves_to_other_artifact", other_accepted_source, "duplicate_artifact_source|artifact_digest_mismatch"),
            ("intermediate_directory_symlink_escape", intermediate_symlink_escape, "artifact_invalid"),
            ("broken_symlink", broken_symlink, "artifact_invalid"),
            ("symlink_loop", symlink_loop, "artifact_invalid"),
            ("blank_storage", "", "artifact_invalid"),
            ("padded_storage", lambda f: f" {original_path(f)} ", "artifact_invalid"),
        ])
        if hasattr(os, "mkfifo"):
            def fifo_source(fixture):
                fifo = fixture["artifact_root"] / "fifo-source"
                os.mkfifo(fifo)
                return fifo
            cases.append(("fifo_source", fifo_source, "artifact_invalid"))
        for index, (case, storage, expected) in enumerate(cases):
            with self.subTest(case=case):
                self.tearDown(); self.setUp()
                capture_with_storage(f"artifact-b2-d-{index}", storage, expected=expected)

    def test_batch3b4b4b2_groups_e_f_manifest_paths_and_bundle_special_files(self):
        manifest_cases = [
            ("blank_filename", lambda f, m: next(item for item in m["artifacts"] if item["format"] == "docx").update({"filename": ""}), "manifest_invalid"),
            ("absolute_filename", lambda f, m: next(item for item in m["artifacts"] if item["format"] == "docx").update({"filename": str(f["root"] / "outside")}), "manifest_invalid"),
            ("parent_traversal_filename", lambda f, m: next(item for item in m["artifacts"] if item["format"] == "docx").update({"filename": "../outside"}), "manifest_invalid"),
            ("nested_filename", lambda f, m: next(item for item in m["artifacts"] if item["format"] == "docx").update({"filename": "artifacts/nested/docx"}), "bundle_file_inventory_invalid"),
            ("points_to_other_artifact", lambda f, m: next(item for item in m["artifacts"] if item["format"] == "docx").update({"filename": self._artifact_manifest_item(f, "html")["filename"]}), "manifest_invalid"),
            ("duplicate_filename", lambda f, m: next(item for item in m["artifacts"] if item["format"] == "pdf").update({"filename": self._artifact_manifest_item(f, "html")["filename"]}), "manifest_invalid"),
            ("leading_whitespace", lambda f, m: next(item for item in m["artifacts"] if item["format"] == "docx").update({"filename": " " + self._artifact_manifest_item(f, "docx")["filename"]}), "bundle_file_inventory_invalid"),
            ("trailing_whitespace", lambda f, m: next(item for item in m["artifacts"] if item["format"] == "html").update({"filename": self._artifact_manifest_item(f, "html")["filename"] + " "}), "bundle_file_inventory_invalid"),
            ("unicode_distinct", lambda f, m: next(item for item in m["artifacts"] if item["format"] == "pdf").update({"filename": self._artifact_manifest_item(f, "pdf")["filename"] + "é"}), "bundle_file_inventory_invalid"),
        ]
        for index, (name, mutation, expected) in enumerate(manifest_cases):
            with self.subTest(case=name):
                self.tearDown(); self.setUp()
                fixture = self._successful_artifact_fixture(f"artifact-b2-e-{index}")
                manifest = json.loads((fixture["bundle"] / "manifest.json").read_text(encoding="utf-8"))
                mutation(fixture, manifest)
                self._rewrite_manifest(fixture["bundle"], manifest)
                self._assert_success_artifact_rejection(fixture, expected, key=f"artifact-b2-e-{index}", update_database=False)

        self.tearDown(); self.setUp()
        fixture = self._successful_artifact_fixture("artifact-b2-e-renamed-consistent")
        manifest = json.loads((fixture["bundle"] / "manifest.json").read_text(encoding="utf-8"))
        item = next(item for item in manifest["artifacts"] if item["format"] == "docx")
        old = fixture["bundle"] / item["filename"]
        item["filename"] = "artifacts/renamed-docx"
        old.rename(fixture["bundle"] / item["filename"])
        self._rewrite_manifest(fixture["bundle"], manifest)
        self._assert_success_artifact_accepts_limitation(fixture, key="artifact-b2-e-renamed-consistent")

        special_cases = [
            ("symlink_to_other_artifact", lambda f, p: (p.unlink(), p.symlink_to(self._artifact_bundle_file(f, "html"))), "bundle_file_invalid"),
            ("symlink_to_unlisted", lambda f, p: (p.unlink(), (f["bundle"] / "unlisted").write_bytes(b"unlisted"), p.symlink_to(f["bundle"] / "unlisted")), "bundle_file_invalid"),
            ("symlink_to_outside_bundle", lambda f, p: (p.unlink(), (f["root"] / "outside-bundle-file").write_bytes(b"outside"), p.symlink_to(f["root"] / "outside-bundle-file")), "bundle_file_invalid"),
            ("broken_symlink", lambda f, p: (p.unlink(), p.symlink_to(f["bundle"] / "missing")), "bundle_file_invalid"),
            ("intermediate_directory_symlink", lambda f, p: ((f["root"] / "outside-bundle-dir").mkdir(), (f["bundle"] / "artifacts" / "linked").symlink_to(f["root"] / "outside-bundle-dir", target_is_directory=True)), "bundle_file_invalid"),
            ("directory_at_filename", lambda f, p: (p.unlink(), p.mkdir()), "bundle_file_inventory_invalid"),
        ]
        if hasattr(os, "mkfifo"):
            special_cases.append(("fifo_at_filename", lambda f, p: (p.unlink(), os.mkfifo(p)), "bundle_file_invalid|bundle_file_inventory_invalid"))
        for index, (name, mutation, expected) in enumerate(special_cases):
            with self.subTest(case=name):
                self.tearDown(); self.setUp()
                fixture = self._successful_artifact_fixture(f"artifact-b2-f-{index}")
                path = self._artifact_bundle_file(fixture, "docx")
                mutation(fixture, path)
                self._assert_success_artifact_rejection(fixture, expected, key=f"artifact-b2-f-{index}", update_database=False)

        self.tearDown(); self.setUp()
        fixture = self._successful_artifact_fixture("artifact-b2-f-hardlink")
        target = self._artifact_bundle_file(fixture, "docx")
        target.unlink()
        os.link(self._artifact_bundle_file(fixture, "html"), target)
        self._assert_success_artifact_rejection(fixture, "artifact_digest_mismatch", key="artifact-b2-f-hardlink", update_database=False)

        self.tearDown(); self.setUp()
        fixture = self._successful_artifact_fixture("artifact-b2-f-hardlink-same-bytes")
        target = self._artifact_bundle_file(fixture, "docx")
        data = target.read_bytes()
        unlisted = fixture["root"] / "unlisted-same-bytes"
        unlisted.write_bytes(data)
        target.unlink()
        os.link(unlisted, target)
        self._assert_success_artifact_accepts_limitation(fixture, key="artifact-b2-f-hardlink-same-bytes")

    def test_batch3b4b4b2_group_g_rejected_paths_remain_non_mutating_and_clean(self):
        fixture = self._successful_artifact_fixture("artifact-b2-g-repeated")
        self._mutate_bundle_file(fixture, "docx", lambda b: b + b"corrupt")
        self._assert_success_artifact_rejection(fixture, "artifact_digest_mismatch", key="artifact-b2-g-repeated", update_database=False)
        self.assertTrue(fixture["root"].exists())
        self.assertFalse((fixture["recovery_root"] / ".stage").exists())

        self.tearDown(); self.setUp()
        source = self._successful_artifact_fixture("artifact-b2-g-capture-failure", capture=False)
        conn = sqlite3.connect(source["database"])
        try:
            conn.execute("UPDATE record_governed_report_artifacts SET storage_reference=? WHERE format='docx'", (str(source["artifact_root"] / "missing-after-render.docx"),))
            conn.commit()
        finally:
            conn.close()
        with self.assertRaisesRegex(recovery.RecoveryOperationFailure, "artifact_invalid"):
            recovery.capture_recovery_point(database_path=source["database"], artifact_root=source["artifact_root"], recovery_root=source["recovery_root"], approved_root=source["root"], actor="admin", governed_action="capture", idempotency_key="artifact-b2-g-capture-failure")
        stage_root = source["recovery_root"] / ".stage"
        if stage_root.exists():
            self.assertEqual(list(stage_root.iterdir()), [])
        check = sqlite3.connect(source["database"])
        check.row_factory = sqlite3.Row
        try:
            self.assertEqual(check.execute("SELECT COUNT(*) FROM record_governed_report_artifacts WHERE validation_state='valid'").fetchone()[0], 3)
            self.assertEqual(jobs.get_job(check, source["job_id"])["state"], "succeeded")
        finally:
            check.close()

    def _run_batch3b4b1_report_and_version_row_mutations(self, post_correction=False):
        cases = [
            ("extra_report_stale", "reports", False, lambda c: c.execute("INSERT INTO record_governed_reports(id,lifecycle_status) VALUES(99,'generated')"), "record_count_mismatch"),
            ("extra_report_accurate", "reports", True, lambda c: c.execute("INSERT INTO record_governed_reports(id,lifecycle_status) VALUES(99,'generated')"), "record_count_mismatch"),
            ("missing_report", "reports", False, lambda c: (c.execute("PRAGMA foreign_keys=OFF"), c.execute("DELETE FROM record_governed_reports WHERE id=7")), "foreign_key_check_failed"),
            ("unexpected_lifecycle", "reports", False, lambda c: c.execute("UPDATE record_governed_reports SET lifecycle_status='draft' WHERE id=7"), "report_lifecycle_invalid"),
            ("report_version_ownership", "reports", False, lambda c: (c.execute("INSERT INTO record_governed_reports(id,lifecycle_status) VALUES(99,'generated')"), c.execute("UPDATE record_governed_report_versions SET report_id=99 WHERE id=11")), "diagnostic_evidence_invalid"),
            ("unrelated_source_report", "reports", False, lambda c: c.execute("INSERT INTO record_governed_reports(id,lifecycle_status) VALUES(100,'generated')"), "record_count_mismatch"),
            ("extra_version_stale", "versions", False, lambda c: c.execute("INSERT INTO record_governed_report_versions(id,report_id,lifecycle_status) VALUES(99,7,'generated')"), "version_count_mismatch"),
            ("extra_version_accurate", "versions", True, lambda c: c.execute("INSERT INTO record_governed_report_versions(id,report_id,lifecycle_status) VALUES(99,7,'generated')"), "version_count_mismatch"),
            ("extra_version_other_report", "versions", False, lambda c: (c.execute("INSERT INTO record_governed_reports(id,lifecycle_status) VALUES(99,'generated')"), c.execute("INSERT INTO record_governed_report_versions(id,report_id,lifecycle_status) VALUES(98,99,'generated')")), "record_count_mismatch"),
            ("missing_version", "versions", False, lambda c: (c.execute("PRAGMA foreign_keys=OFF"), c.execute("DELETE FROM record_governed_report_versions WHERE id=11")), "diagnostic_evidence_invalid"),
            ("version_wrong_report", "versions", False, lambda c: (c.execute("INSERT INTO record_governed_reports(id,lifecycle_status) VALUES(99,'generated')"), c.execute("UPDATE record_governed_report_versions SET report_id=99 WHERE id=11")), "diagnostic_evidence_invalid"),
            ("specification_digest_frozen", "versions", False, lambda c: c.execute("UPDATE record_governed_report_versions SET specification_digest=? WHERE id=11", ("0" * 64,)), "specification_digest_mismatch"),
            ("version_identity_ownership", "versions", True, lambda c: c.execute("INSERT INTO record_governed_report_versions(id,report_id,lifecycle_status) VALUES(99,7,'generated')"), "version_count_mismatch"),
            ("version_physical_order", "versions", False, lambda c: None, None),
            ("valid_report_version_controls", "versions", False, lambda c: None, None),
        ]
        executed = 0
        for name, family, accurate, mutation, expected in cases:
            with self.subTest(case=name):
                self.tearDown()
                self.setUp()
                self.conn.execute("DELETE FROM record_governed_report_artifacts")
                self.artifact.unlink()
                self.conn.commit()
                bundle, _live_db, point_id = self._historical_reconstruction_fixture(post_correction=post_correction)
                manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
                archived = sqlite3.connect(bundle / "database.sqlite3")
                mutation(archived)
                archived.commit()
                archived.close()
                self._refresh_archived_database_binding(bundle, manifest)
                if accurate and family == "reports":
                    manifest["counts"]["reports"] += 1
                if accurate and family == "versions":
                    manifest["counts"]["versions"] += 1
                if post_correction:
                    base_manifest = {key: manifest[key] for key in recovery.DIAGNOSTIC_MANIFEST_KEYS}
                    current = recovery._recovery_evidence_payload(
                        base_manifest, source_mode="native_capture", actor="", rationale="",
                        declaration={}, idempotency_key="", created_at="", report_event_bound=0,
                        contract_name="post_correction_aware",
                    )
                    manifest["current_recovery_manifest_evidence"] = current
                    manifest["current_recovery_manifest_evidence_digest"] = recovery.digest_bytes(recovery.canonical_json(current).encode("utf-8"))
                if post_correction or (accurate and family in {"reports", "versions"}):
                    self._rewrite_manifest(bundle, manifest)
                effective_expected = expected
                if post_correction:
                    effective_expected = {
                        "extra_report_accurate": "recovery_state_ineligible",
                        "report_version_ownership": "record_count_mismatch",
                        "extra_version_accurate": "recovery_state_ineligible",
                        "missing_version": "version_count_mismatch",
                        "version_wrong_report": "record_count_mismatch",
                        "version_identity_ownership": "recovery_state_ineligible",
                    }.get(name, expected)
                if expected is None:
                    recovery.validate_recovery_bundle(bundle)
                else:
                    with self.assertRaisesRegex(ValueError, effective_expected):
                        recovery.validate_recovery_bundle(bundle)
                executed += 1
        self.assertEqual(executed, 15)

    def test_batch3b4b1_report_and_version_row_mutations_diagnostic_aware(self):
        self._run_batch3b4b1_report_and_version_row_mutations()

    def test_batch3b4b1_report_and_version_row_mutations_post_correction_aware(self):
        self._run_batch3b4b1_report_and_version_row_mutations(post_correction=True)

    def _run_batch3b4b2_qualification_mutations(self, post_correction=False):
        cases = [
            ("missing_assembly", False, lambda c: self._remove_qualification(c, 1), "foreign_key_check_failed"),
            ("missing_assembly_accurate", True, lambda c: self._remove_qualification(c, 1), "foreign_key_check_failed"),
            ("missing_privacy", False, lambda c: self._remove_qualification(c, 2), "foreign_key_check_failed"),
            ("missing_privacy_accurate", True, lambda c: self._remove_qualification(c, 2), "foreign_key_check_failed"),
            ("missing_redaction", False, lambda c: self._remove_qualification(c, 3), "foreign_key_check_failed"),
            ("missing_redaction_accurate", True, lambda c: self._remove_qualification(c, 3), "foreign_key_check_failed"),
            ("missing_approval", False, lambda c: self._remove_qualification(c, 4), "qualification_count_mismatch"),
            ("missing_approval_accurate", True, lambda c: self._remove_qualification(c, 4), "governed_report_qualification_gate_order_invalid"),
            ("extra_revision", False, lambda c: self._clone_qualification(c, 4, "approval"), "qualification_count_mismatch"),
            ("extra_revision_accurate", True, lambda c: self._clone_qualification(c, 4, "approval"), "governed_report_qualification_gate_order_invalid"),
            ("duplicate_assembly", False, lambda c: self._clone_qualification(c, 1, "assembly"), "qualification_count_mismatch"),
            ("duplicate_assembly_accurate", True, lambda c: self._clone_qualification(c, 1, "assembly"), "governed_report_qualification_gate_order_invalid"),
            ("duplicate_privacy", False, lambda c: self._clone_qualification(c, 2, "privacy"), "qualification_count_mismatch"),
            ("duplicate_privacy_accurate", True, lambda c: self._clone_qualification(c, 2, "privacy"), "governed_report_qualification_gate_order_invalid"),
            ("duplicate_redaction", False, lambda c: self._clone_qualification(c, 3, "redaction"), "qualification_count_mismatch"),
            ("duplicate_redaction_accurate", True, lambda c: self._clone_qualification(c, 3, "redaction"), "governed_report_qualification_gate_order_invalid"),
            ("duplicate_approval", False, lambda c: self._clone_qualification(c, 4, "approval"), "qualification_count_mismatch"),
            ("duplicate_approval_accurate", True, lambda c: self._clone_qualification(c, 4, "approval"), "governed_report_qualification_gate_order_invalid"),
            ("non_final", True, lambda c: (c.execute("PRAGMA ignore_check_constraints=ON"), c.execute("UPDATE record_governed_report_qualifications SET qualification_state='draft' WHERE id=2")), "integrity_check_failed"),
            ("wrong_report", True, lambda c: c.execute("UPDATE record_governed_report_qualifications SET report_id=99 WHERE id=2"), "governed_report_qualification_chain_invalid"),
            ("wrong_version", True, lambda c: c.execute("UPDATE record_governed_report_qualifications SET report_version_id=99 WHERE id=2"), "governed_report_qualification_chain_invalid"),
            ("broken_previous", True, lambda c: c.execute("UPDATE record_governed_report_qualifications SET previous_qualification_id=4 WHERE id=2"), "governed_report_qualification_chain_invalid"),
            ("altered_digest", True, lambda c: c.execute("UPDATE record_governed_report_qualifications SET qualification_digest=? WHERE id=2", ("0" * 64,)), "governed_report_qualification_digest_mismatch"),
            ("first_revision_predecessor", True, lambda c: c.execute("UPDATE record_governed_report_qualifications SET previous_qualification_id=4 WHERE id=1"), "governed_report_qualification_chain_invalid"),
            ("later_revision_null_predecessor", True, lambda c: c.execute("UPDATE record_governed_report_qualifications SET previous_qualification_id=NULL WHERE id=2"), "governed_report_qualification_chain_invalid"),
            ("predecessor_forward", True, lambda c: c.execute("UPDATE record_governed_report_qualifications SET previous_qualification_id=4 WHERE id=2"), "governed_report_qualification_chain_invalid"),
            ("self_reference", True, lambda c: c.execute("UPDATE record_governed_report_qualifications SET previous_qualification_id=2 WHERE id=2"), "governed_report_qualification_chain_invalid"),
            ("cycle", True, lambda c: c.execute("UPDATE record_governed_report_qualifications SET previous_qualification_id=4 WHERE id=1"), "governed_report_qualification_chain_invalid"),
            ("revision_skip", True, lambda c: c.execute("UPDATE record_governed_report_qualifications SET revision_number=5 WHERE id=2"), "governed_report_qualification_chain_invalid"),
            ("blank_actor", True, lambda c: c.execute("UPDATE record_governed_report_qualifications SET qualifier_actor='' WHERE id=2"), "governed_report_qualification_chain_invalid"),
            ("review_mode_changed", True, lambda c: c.execute("UPDATE record_governed_report_qualifications SET review_mode='sole_administrator' WHERE id=2"), "governed_report_qualification_chain_invalid"),
            ("operating_constraint_changed", True, lambda c: c.execute("UPDATE record_governed_report_qualifications SET operating_constraint='changed' WHERE id=2"), "governed_report_qualification_chain_invalid"),
            ("disclosure_changed", True, lambda c: c.execute("UPDATE record_governed_report_qualifications SET disclosure_version='changed' WHERE id=2"), "governed_report_qualification_chain_invalid"),
            ("distribution_changed", True, lambda c: c.execute("UPDATE record_governed_report_qualifications SET distribution_restriction='external' WHERE id=2"), "governed_report_qualification_chain_invalid"),
            ("declaration_changed", True, lambda c: c.execute("UPDATE record_governed_report_qualifications SET declaration_json='{}' WHERE id=2"), "governed_report_qualification_chain_invalid"),
            ("rationale_empty", True, lambda c: c.execute("UPDATE record_governed_report_qualifications SET rationale='' WHERE id=2"), "governed_report_qualification_chain_invalid"),
            ("specification_changed", True, lambda c: c.execute("UPDATE record_governed_report_qualifications SET specification_digest=? WHERE id=2", ("1" * 64,)), "governed_report_qualification_chain_invalid"),
            ("payload_digest_mismatch", True, lambda c: c.execute("UPDATE record_governed_report_qualifications SET qualification_payload_json='{}' WHERE id=2"), "governed_report_qualification_digest_mismatch"),
        ]
        for name, accurate, mutation, expected in cases:
            with self.subTest(contract="post_correction_aware" if post_correction else "diagnostic_aware", case=name):
                self.tearDown(); self.setUp()
                self.conn.execute("DELETE FROM record_governed_report_artifacts")
                self.artifact.unlink(); self.conn.commit()
                self._add_valid_qualification_chain()
                if not post_correction:
                    self._add_diagnostic_evidence(linked_successor=True)
                if post_correction:
                    jobs.ensure_post_correction_tables(self.conn)
                result = recovery.capture_recovery_point(database_path=self.db, artifact_root=self.artifacts, recovery_root=self.recovery_root, approved_root=self.root, actor="admin", governed_action="capture")
                bundle = self.recovery_root / f"recovery-{result['recovery_point_id']}"
                manifest = json.loads((bundle / "manifest.json").read_text())
                archived = sqlite3.connect(bundle / "database.sqlite3")
                archived.row_factory = sqlite3.Row
                if name in {"wrong_report", "wrong_version"}:
                    archived.execute("INSERT INTO record_governed_reports(id,lifecycle_status) VALUES(99,'generated')")
                    archived.execute("INSERT INTO record_governed_report_versions(id,report_id,lifecycle_status,specification_json,specification_digest) VALUES(99,99,'generated','{}',?)", (recovery.digest_bytes(b"{}"),))
                mutation(archived); archived.commit(); archived.close()
                self._refresh_archived_database_binding(bundle, manifest)
                if name in {"wrong_report", "wrong_version"}:
                    manifest["counts"]["reports"] += 1
                    manifest["counts"]["versions"] += 1
                if accurate:
                    probe = sqlite3.connect(bundle / "database.sqlite3"); probe.row_factory = sqlite3.Row
                    state = qualifications.state_snapshot(probe); probe.close()
                    manifest["counts"]["qualifications"] = state["count"]
                if post_correction:
                    base = {key: manifest[key] for key in recovery.DIAGNOSTIC_MANIFEST_KEYS}
                    current = recovery._recovery_evidence_payload(base, source_mode="native_capture", actor="", rationale="", declaration={}, idempotency_key="", created_at="", report_event_bound=0, contract_name="post_correction_aware")
                    manifest["current_recovery_manifest_evidence"] = current
                    manifest["current_recovery_manifest_evidence_digest"] = recovery.digest_bytes(recovery.canonical_json(current).encode())
                self._rewrite_manifest(bundle, manifest)
                with self.assertRaisesRegex(ValueError, expected):
                    recovery.validate_recovery_bundle(bundle)

    def _remove_qualification(self, conn, qualification_id):
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("DELETE FROM record_governed_report_qualification_events WHERE qualification_id=?", (qualification_id,))
        conn.execute("DELETE FROM record_governed_report_qualifications WHERE id=?", (qualification_id,))

    def _clone_qualification(self, conn, source_id, gate):
        row = dict(conn.execute("SELECT * FROM record_governed_report_qualifications WHERE id=?", (source_id,)).fetchone())
        payload = json.loads(row["qualification_payload_json"])
        payload.update({"revision_number": 5, "previous_qualification_id": 4, "completed_gate": gate})
        digest = qualifications._payload_digest(payload)
        cur = conn.execute("INSERT INTO record_governed_report_qualifications (report_id,report_version_id,specification_digest,revision_number,previous_qualification_id,completed_gate,review_mode,operating_constraint,creator_actor,qualifier_actor,rationale,declaration_json,disclosure_version,distribution_restriction,qualification_payload_json,qualification_digest,qualification_state,created_at,finalized_at,idempotency_key) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (7,11,row["specification_digest"],5,4,gate,row["review_mode"],row["operating_constraint"],row["creator_actor"],row["qualifier_actor"],row["rationale"],row["declaration_json"],row["disclosure_version"],row["distribution_restriction"],qualifications.canonical_json(payload),digest,"final",row["created_at"],row["finalized_at"],"qualification-extra"))
        conn.execute("INSERT INTO record_governed_report_qualification_events (qualification_id,report_id,report_version_id,event_type,actor,occurred_at,idempotency_key,payload_json) VALUES (?,?,?,?,?,?,?,?)", (cur.lastrowid,7,11,qualifications.INDEPENDENT_EVENTS[gate],row["qualifier_actor"],row["created_at"],"qualification-extra",qualifications.canonical_json(payload)))

    def test_batch3b4b2_qualification_row_mutations_diagnostic_aware(self):
        self._run_batch3b4b2_qualification_mutations()

    def test_batch3b4b2_qualification_row_mutations_post_correction_aware(self):
        self._run_batch3b4b2_qualification_mutations(post_correction=True)

    def _insert_unrelated_job(self, conn, state="failed_terminal", action="enqueue_generation", retry_of=None):
        attempt_count = 0 if state == "queued" else 1
        conn.execute("INSERT INTO stage77_report_jobs (report_id,report_version_id,specification_digest,requested_formats_json,rendering_profile,template_version,publication_engine_version,requesting_actor,governed_action,requested_at,state,attempt_count,max_attempts,next_eligible_at,idempotency_key,retry_of_job_id,maintenance_epoch,schema_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (7, 11, "a" * 64, '["docx","html","pdf"]', "internal", "cde-internal-v1", "2.0.0", "other", action, "2026-01-01T00:00:04Z", state, attempt_count, 3, "2026-01-01T00:00:04Z", "unrelated-job", retry_of, 0, jobs.JOB_SCHEMA_VERSION))

    def _run_batch3b4b3_job_mutations(self, post_correction=False):
        cases = [
            ("extra_terminal_stale", lambda c: self._insert_unrelated_job(c), "job_state_count_mismatch"),
            ("extra_terminal_accurate", lambda c: self._insert_unrelated_job(c), "job_state_count_mismatch"),
            ("extra_queued", lambda c: self._insert_unrelated_job(c, state="queued"), "job_state_count_mismatch"),
            ("extra_leased", lambda c: self._insert_unrelated_job(c, state="leased"), "job_state_count_mismatch"),
            ("extra_running", lambda c: self._insert_unrelated_job(c, state="running"), "job_state_count_mismatch"),
            ("missing_job1", lambda c: (c.execute("PRAGMA foreign_keys=OFF"), c.execute("DELETE FROM stage77_report_jobs WHERE retry_of_job_id IS NULL")), "retry_topology_invalid"),
            ("missing_job2", lambda c: (c.execute("PRAGMA foreign_keys=OFF"), c.execute("DELETE FROM stage77_report_jobs WHERE retry_of_job_id IS NOT NULL")), "foreign_key_check_failed"),
            ("job_report_ownership", lambda c: c.execute("UPDATE stage77_report_jobs SET report_id=999 WHERE id=(SELECT MIN(id) FROM stage77_report_jobs)"), "diagnostic_evidence_invalid"),
            ("job_version_ownership", lambda c: c.execute("UPDATE stage77_report_jobs SET report_version_id=999 WHERE id=(SELECT MIN(id) FROM stage77_report_jobs)"), "diagnostic_evidence_invalid"),
            ("retry_link_removed", lambda c: c.execute("UPDATE stage77_report_jobs SET retry_of_job_id=NULL WHERE retry_of_job_id IS NOT NULL"), "diagnostic_evidence_invalid"),
            ("wrong_job_action", lambda c: c.execute("UPDATE stage77_report_jobs SET governed_action='unknown_action' WHERE id=(SELECT MIN(id) FROM stage77_report_jobs)"), "diagnostic_evidence_invalid"),
        ]
        for name, mutation, expected in cases:
            with self.subTest(contract="post_correction_aware" if post_correction else "diagnostic_aware", case=name):
                if post_correction and name in {"missing_job1", "missing_job2", "job_report_ownership", "job_version_ownership", "retry_link_removed", "wrong_job_action"}:
                    self.assertTrue(True, "inapplicable: zero-authorization post-correction state has no Job 1/Job 2 diagnostic inventory")
                    continue
                self.tearDown(); self.setUp()
                self.conn.execute("DELETE FROM record_governed_report_artifacts"); self.artifact.unlink(); self.conn.commit()
                if post_correction:
                    jobs.ensure_post_correction_tables(self.conn)
                    result = recovery.capture_recovery_point(database_path=self.db, artifact_root=self.artifacts, recovery_root=self.recovery_root, approved_root=self.root, actor="admin", governed_action="capture")
                else:
                    bundle, _live, point_id = self._historical_reconstruction_fixture()
                    result = {"recovery_point_id": point_id}
                bundle = self.recovery_root / f"recovery-{result['recovery_point_id']}"
                manifest = json.loads((bundle / "manifest.json").read_text())
                archived = sqlite3.connect(bundle / "database.sqlite3"); archived.row_factory = sqlite3.Row
                mutation(archived); archived.commit(); archived.close()
                self._refresh_archived_database_binding(bundle, manifest)
                if name == "extra_terminal_accurate":
                    manifest["counts"]["jobs"] += 1
                    manifest["job_state_counts"]["failed_terminal"] += 1
                if post_correction:
                    base = {key: manifest[key] for key in recovery.DIAGNOSTIC_MANIFEST_KEYS}
                    current = recovery._recovery_evidence_payload(base, source_mode="native_capture", actor="", rationale="", declaration={}, idempotency_key="", created_at="", report_event_bound=0, contract_name="post_correction_aware")
                    manifest["current_recovery_manifest_evidence"] = current
                    manifest["current_recovery_manifest_evidence_digest"] = recovery.digest_bytes(recovery.canonical_json(current).encode())
                self._rewrite_manifest(bundle, manifest)
                with self.assertRaisesRegex(ValueError, expected):
                    recovery.validate_recovery_bundle(bundle)

    def test_batch3b4b3_job_row_mutations_diagnostic_aware(self):
        self._run_batch3b4b3_job_mutations()

    def test_batch3b4b3_job_row_mutations_post_correction_aware(self):
        self._run_batch3b4b3_job_mutations(post_correction=True)

    def _runtime_metadata_connection(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript("CREATE TABLE record_governed_reports(id INTEGER PRIMARY KEY); CREATE TABLE record_governed_report_versions(id INTEGER PRIMARY KEY, report_id INTEGER REFERENCES record_governed_reports(id)); INSERT INTO record_governed_reports VALUES(1); INSERT INTO record_governed_report_versions VALUES(1,1);")
        jobs.ensure_job_tables(conn)
        recovery.ensure_recovery_tables(conn)
        return conn

    def _runtime_job(self, conn, **overrides):
        values = {
            "state": "queued", "attempt_count": 0, "max_attempts": 3,
            "lease_owner": None, "lease_token": None, "lease_acquired_at": None,
            "lease_expires_at": None, "heartbeat_at": None, "maintenance_epoch": 0,
        }
        values.update(overrides)
        conn.execute("INSERT INTO stage77_report_jobs(report_id,report_version_id,specification_digest,requested_formats_json,rendering_profile,template_version,publication_engine_version,requesting_actor,governed_action,requested_at,state,attempt_count,max_attempts,next_eligible_at,lease_owner,lease_token,lease_acquired_at,lease_expires_at,heartbeat_at,idempotency_key,maintenance_epoch,schema_version) VALUES(1,1,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", ("a" * 64, "[]", "internal", "v1", "2.0.0", "admin", "capture", "now", values["state"], values["attempt_count"], values["max_attempts"], "now", values["lease_owner"], values["lease_token"], values["lease_acquired_at"], values["lease_expires_at"], values["heartbeat_at"], "runtime-" + str(conn.total_changes), values["maintenance_epoch"], jobs.JOB_SCHEMA_VERSION))
        conn.commit()

    def test_batch3b4b3a2_runtime_metadata_schema_and_sqlite_boundaries(self):
        valid = {"lease_owner": "worker", "lease_token": "token", "lease_acquired_at": "2026-01-01T00:00:00Z", "lease_expires_at": "2026-01-01T00:03:00Z", "heartbeat_at": "2026-01-01T00:01:00Z", "state": "leased", "attempt_count": 1}
        cases = [
            ("valid_terminal", {}, None),
            ("numeric_string_normalized", {"attempt_count": "1", "max_attempts": "3"}, None),
            ("boolean_normalized", {"attempt_count": True, "max_attempts": True}, None),
            ("negative_attempt", {"attempt_count": -1}, "job_attempt_metadata_invalid"),
            ("attempt_over_bound", {"attempt_count": 4}, "job_attempt_metadata_invalid"),
            ("zero_maximum", {"max_attempts": 0}, "job_attempt_metadata_invalid"),
            ("real_attempt", {"attempt_count": 1.5}, "job_attempt_metadata_invalid"),
            ("queued_partial_lease", {"lease_token": "unexpected"}, "job_lease_metadata_invalid"),
            ("leased_coherent", valid, None),
            ("leased_missing_owner", {**valid, "lease_owner": None}, "job_lease_metadata_invalid"),
            ("leased_bad_expiry", {**valid, "lease_expires_at": "bad"}, "job_lease_metadata_invalid"),
            ("leased_expiry_before_acquisition", {**valid, "lease_expires_at": "2025-12-31T23:59:00Z"}, "job_lease_metadata_invalid"),
            ("terminal_stale_tuple", {"lease_owner": "worker", "lease_token": "token", "lease_acquired_at": "2025-12-31T23:00:00Z", "lease_expires_at": "2025-12-31T23:59:00Z", "heartbeat_at": "2025-12-31T23:30:00Z", "state": "failed_terminal", "attempt_count": 1}, None),
            ("epoch_zero_legacy", {"maintenance_epoch": "0"}, None),
            ("epoch_negative", {"maintenance_epoch": -1}, "job_maintenance_epoch_mismatch"),
            ("epoch_real", {"maintenance_epoch": 1.5}, "job_maintenance_epoch_mismatch"),
        ]
        for name, overrides, expected in cases:
            with self.subTest(case=name):
                conn = self._runtime_metadata_connection()
                self._runtime_job(conn, **overrides)
                stored = conn.execute("SELECT typeof(attempt_count),typeof(max_attempts),typeof(maintenance_epoch) FROM stage77_report_jobs").fetchone()
                if name in {"numeric_string_normalized", "boolean_normalized", "epoch_zero_legacy"}:
                    self.assertEqual(stored[0], "integer")
                    self.assertEqual(stored[1], "integer")
                    self.assertEqual(stored[2], "integer")
                if expected is None:
                    recovery._validate_archived_job_runtime_metadata(conn, contract="diagnostic_aware")
                else:
                    with self.assertRaisesRegex(ValueError, expected):
                        recovery._validate_archived_job_runtime_metadata(conn, contract="diagnostic_aware")
                conn.close()

    def test_batch3b4b3a2_runtime_schema_selection_preserves_reduced_history(self):
        reduced = sqlite3.connect(":memory:")
        reduced.execute("CREATE TABLE stage77_report_jobs(id INTEGER PRIMARY KEY, state TEXT NOT NULL)")
        reduced.execute("INSERT INTO stage77_report_jobs VALUES(1,'queued')")
        recovery._validate_archived_job_runtime_metadata(reduced, contract="legacy")
        reduced.close()
        partial = sqlite3.connect(":memory:")
        partial.execute("CREATE TABLE stage77_report_jobs(id INTEGER PRIMARY KEY, state TEXT NOT NULL, attempt_count INTEGER NOT NULL)")
        partial.execute("INSERT INTO stage77_report_jobs VALUES(1,'queued',0)")
        with self.assertRaisesRegex(ValueError, "schema_incompatible"):
            recovery._validate_archived_job_runtime_metadata(partial, contract="diagnostic_aware")
        partial.close()

    def test_batch3b4b3a2a_attempt_metadata_matrix(self):
        """Exercise the producer's job-local attempt domain across supported schemas."""
        cases = [
            ("valid_job_1", {"state": "failed_terminal", "attempt_count": 1, "max_attempts": 3}, None),
            ("valid_job_2", {"state": "failed_terminal", "attempt_count": 1, "max_attempts": 3}, None),
            ("queued_zero", {"state": "queued", "attempt_count": 0, "max_attempts": 3}, None),
            ("terminal_at_max", {"state": "failed_terminal", "attempt_count": 3, "max_attempts": 3}, None),
            ("queued_valid", {"state": "queued", "attempt_count": 0, "max_attempts": 3}, None),
            ("terminal_valid", {"state": "failed_terminal", "attempt_count": 1, "max_attempts": 3}, None),
            ("negative_attempt", {"attempt_count": -1}, "job_attempt_metadata_invalid"),
            ("attempt_over_max", {"attempt_count": 4}, "job_attempt_metadata_invalid"),
            ("zero_maximum", {"max_attempts": 0}, "job_attempt_metadata_invalid"),
            ("negative_maximum", {"max_attempts": -1}, "job_attempt_metadata_invalid"),
            ("null_attempt", {"attempt_count": None}, "job_attempt_metadata_invalid"),
            ("null_maximum", {"max_attempts": None}, "job_attempt_metadata_invalid"),
            ("real_attempt", {"attempt_count": 1.5}, "job_attempt_metadata_invalid"),
            ("real_maximum", {"max_attempts": 3.5}, "job_attempt_metadata_invalid"),
            ("text_attempt", {"attempt_count": "not-a-number"}, "job_attempt_metadata_invalid"),
            ("numeric_string_attempt", {"attempt_count": "1"}, None),
            ("numeric_string_maximum", {"max_attempts": "3"}, None),
            ("boolean_attempt", {"attempt_count": True}, None),
            ("reduced_schema", None, None),
            ("partial_modern_schema", None, "schema_incompatible"),
        ]
        for name, overrides, expected in cases:
            with self.subTest(case=name):
                if name == "reduced_schema":
                    conn = sqlite3.connect(":memory:")
                    conn.execute("CREATE TABLE stage77_report_jobs(id INTEGER PRIMARY KEY, state TEXT NOT NULL)")
                    conn.execute("INSERT INTO stage77_report_jobs VALUES(1,'queued')")
                    recovery._validate_archived_job_runtime_metadata(conn, contract="diagnostic_aware")
                    conn.close()
                    continue
                if name == "partial_modern_schema":
                    conn = sqlite3.connect(":memory:")
                    conn.execute("CREATE TABLE stage77_report_jobs(id INTEGER PRIMARY KEY, state TEXT NOT NULL, attempt_count INTEGER)")
                    conn.execute("INSERT INTO stage77_report_jobs VALUES(1,'queued',0)")
                    with self.assertRaisesRegex(ValueError, expected):
                        recovery._validate_archived_job_runtime_metadata(conn, contract="diagnostic_aware")
                    conn.close()
                    continue
                if name in {"null_attempt", "null_maximum"}:
                    conn = sqlite3.connect(":memory:")
                    conn.row_factory = sqlite3.Row
                    conn.execute("CREATE TABLE stage77_report_jobs(id INTEGER PRIMARY KEY, state TEXT NOT NULL, attempt_count INTEGER, max_attempts INTEGER)")
                    values = {"state": "queued", "attempt_count": 0, "max_attempts": 3}
                    values.update(overrides)
                    conn.execute("INSERT INTO stage77_report_jobs(state,attempt_count,max_attempts) VALUES(?,?,?)", (values["state"], values["attempt_count"], values["max_attempts"]))
                    with self.assertRaisesRegex(ValueError, expected):
                        recovery._validate_archived_job_runtime_metadata(conn, contract="diagnostic_aware")
                    conn.close()
                    continue
                conn = self._runtime_metadata_connection()
                self._runtime_job(conn, **(overrides or {}))
                stored = conn.execute("SELECT attempt_count,max_attempts,typeof(attempt_count),typeof(max_attempts) FROM stage77_report_jobs").fetchone()
                if name == "numeric_string_attempt":
                    self.assertEqual((stored[0], stored[2]), (1, "integer"))
                if name == "numeric_string_maximum":
                    self.assertEqual((stored[1], stored[3]), (3, "integer"))
                if name == "boolean_attempt":
                    self.assertEqual((stored[0], stored[2]), (1, "integer"))
                if expected is None:
                    recovery._validate_archived_job_runtime_metadata(conn, contract="diagnostic_aware")
                else:
                    with self.assertRaisesRegex(ValueError, expected):
                        recovery._validate_archived_job_runtime_metadata(conn, contract="diagnostic_aware")
                conn.close()

    def test_batch3b4b3a2a_attempt_lifecycle_parameterizations(self):
        cases = [
            ("queued_after_attempt_started", {"state": "queued", "attempt_count": 1}, None),
            ("terminal_before_attempt_started", {"state": "failed_terminal", "attempt_count": 0}, "job_attempt_metadata_invalid"),
        ]
        for name, overrides, expected in cases:
            with self.subTest(case=name):
                conn = self._runtime_metadata_connection()
                self._runtime_job(conn, **overrides)
                if expected is None:
                    recovery._validate_archived_job_runtime_metadata(conn, contract="diagnostic_aware")
                else:
                    with self.assertRaisesRegex(ValueError, expected):
                        recovery._validate_archived_job_runtime_metadata(conn, contract="diagnostic_aware")
                conn.close()

    def test_batch3b4b3a2a_contract_selector_rejects_unknown_contract(self):
        conn = self._runtime_metadata_connection()
        self._runtime_job(conn)
        with self.assertRaisesRegex(ValueError, "schema_incompatible"):
            recovery._validate_archived_job_runtime_metadata(conn, contract="unknown_contract")
        conn.close()

    def test_batch3b4b3a2b_lease_heartbeat_matrix(self):
        coherent = {
            "lease_owner": "worker", "lease_token": "token",
            "lease_acquired_at": "2026-01-01T00:00:00Z",
            "lease_expires_at": "2026-01-01T00:03:00Z",
            "heartbeat_at": "2026-01-01T00:01:00Z", "attempt_count": 1,
        }
        cases = [
            ("queued_null", {"state": "queued"}, None),
            ("leased_coherent", {**coherent, "state": "leased"}, None),
            ("running_coherent", {**coherent, "state": "running"}, None),
            ("terminal_null", {"state": "failed_terminal", "attempt_count": 1}, None),
            ("terminal_expired_stale", {**coherent, "state": "failed_terminal", "lease_acquired_at": "2025-12-31T23:00:00Z", "lease_expires_at": "2025-12-31T23:03:00Z", "heartbeat_at": "2025-12-31T23:01:00Z"}, None),
            ("terminal_nonexpired_stale", {**coherent, "state": "failed_terminal"}, None),
            ("leased_missing_owner", {**coherent, "state": "leased", "lease_owner": None}, "job_lease_metadata_invalid"),
            ("leased_blank_owner", {**coherent, "state": "leased", "lease_owner": ""}, "job_lease_metadata_invalid"),
            ("leased_missing_token", {**coherent, "state": "leased", "lease_token": None}, "job_lease_metadata_invalid"),
            ("leased_blank_token", {**coherent, "state": "leased", "lease_token": ""}, "job_lease_metadata_invalid"),
            ("running_missing_identity", {**coherent, "state": "running", "lease_token": None}, "job_lease_metadata_invalid"),
            ("active_missing_acquisition", {**coherent, "state": "leased", "lease_acquired_at": None}, "job_lease_metadata_invalid"),
            ("active_missing_expiry", {**coherent, "state": "leased", "lease_expires_at": None}, "job_lease_metadata_invalid"),
            ("active_missing_heartbeat", {**coherent, "state": "leased", "heartbeat_at": None}, "job_lease_metadata_invalid"),
            ("active_only_token", {"state": "leased", "attempt_count": 1, "lease_token": "token"}, "job_lease_metadata_invalid"),
            ("terminal_partial_stale", {"state": "failed_terminal", "attempt_count": 1, "lease_token": "token"}, "job_lease_metadata_invalid"),
            ("queued_unexpected_lease", {"state": "queued", "lease_token": "token"}, "job_lease_metadata_invalid"),
            ("expiry_before_acquisition", {**coherent, "state": "leased", "lease_expires_at": "2025-12-31T23:59:00Z"}, "job_lease_metadata_invalid"),
            ("expiry_equal_acquisition", {**coherent, "state": "leased", "lease_expires_at": "2026-01-01T00:00:00Z"}, "job_lease_metadata_invalid"),
            ("heartbeat_before_acquisition", {**coherent, "state": "leased", "heartbeat_at": "2025-12-31T23:59:00Z"}, "job_lease_metadata_invalid"),
            ("heartbeat_after_expiry", {**coherent, "state": "leased", "heartbeat_at": "2026-01-01T00:04:00Z"}, "job_lease_metadata_invalid"),
            ("malformed_timestamp", {**coherent, "state": "leased", "lease_expires_at": "not-a-timestamp"}, "job_lease_metadata_invalid"),
            ("reduced_schema", None, None),
            ("partial_modern_schema", None, "schema_incompatible"),
        ]
        for name, overrides, expected in cases:
            with self.subTest(case=name):
                if name == "reduced_schema":
                    conn = sqlite3.connect(":memory:")
                    conn.execute("CREATE TABLE stage77_report_jobs(id INTEGER PRIMARY KEY, state TEXT NOT NULL)")
                    conn.execute("INSERT INTO stage77_report_jobs VALUES(1,'queued')")
                    recovery._validate_archived_job_runtime_metadata(conn, contract="diagnostic_aware")
                    conn.close()
                    continue
                if name == "partial_modern_schema":
                    conn = sqlite3.connect(":memory:")
                    conn.execute("CREATE TABLE stage77_report_jobs(id INTEGER PRIMARY KEY, state TEXT NOT NULL, lease_token TEXT)")
                    conn.execute("INSERT INTO stage77_report_jobs VALUES(1,'queued','token')")
                    with self.assertRaisesRegex(ValueError, expected):
                        recovery._validate_archived_job_runtime_metadata(conn, contract="diagnostic_aware")
                    conn.close()
                    continue
                conn = self._runtime_metadata_connection()
                self._runtime_job(conn, **overrides)
                if expected is None:
                    recovery._validate_archived_job_runtime_metadata(conn, contract="diagnostic_aware")
                else:
                    with self.assertRaisesRegex(ValueError, expected):
                        recovery._validate_archived_job_runtime_metadata(conn, contract="diagnostic_aware")
                conn.close()

    def test_batch3b4b3a2b_lease_additional_state_parameterizations(self):
        cases = [
            ("leased_expired_active", {"state": "leased", "attempt_count": 1, "lease_owner": "worker", "lease_token": "token", "lease_acquired_at": "2025-12-31T23:00:00Z", "lease_expires_at": "2025-12-31T23:03:00Z", "heartbeat_at": "2025-12-31T23:01:00Z"}, None),
            ("running_expired_active", {"state": "running", "attempt_count": 1, "lease_owner": "worker", "lease_token": "token", "lease_acquired_at": "2025-12-31T23:00:00Z", "lease_expires_at": "2025-12-31T23:03:00Z", "heartbeat_at": "2025-12-31T23:01:00Z"}, None),
            ("retry_wait_partial_lease", {"state": "retry_wait", "attempt_count": 1, "lease_token": "token"}, "job_lease_metadata_invalid"),
        ]
        for name, overrides, expected in cases:
            with self.subTest(case=name):
                conn = self._runtime_metadata_connection()
                self._runtime_job(conn, **overrides)
                if expected is None:
                    recovery._validate_archived_job_runtime_metadata(conn, contract="diagnostic_aware")
                else:
                    with self.assertRaisesRegex(ValueError, expected):
                        recovery._validate_archived_job_runtime_metadata(conn, contract="diagnostic_aware")
                conn.close()

    def test_batch3b4b3a2b_supported_contract_selector_profiles(self):
        for contract in ("legacy", "current", "diagnostic_aware", "post_correction_aware"):
            with self.subTest(contract=contract):
                conn = self._runtime_metadata_connection()
                self._runtime_job(conn, state="queued", attempt_count=0, max_attempts=3)
                recovery._validate_archived_job_runtime_metadata(conn, contract=contract)
                conn.close()

if __name__ == "__main__":
    unittest.main()
