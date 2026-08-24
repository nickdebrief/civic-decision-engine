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

    def _restore(self, bundle, database_target, artifact_target, restore_root=None):
        root = restore_root or self.root / "restore"
        root.mkdir(exist_ok=True)
        return recovery.restore_recovery_point(bundle_path=bundle, restore_root=root, database_target=database_target, artifact_root_target=artifact_target, live_database=self.db, live_artifact_root=self.artifacts, live_recovery_root=self.recovery_root, actor="admin", governed_action="restore", approved_root=self.root)

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


if __name__ == "__main__":
    unittest.main()
