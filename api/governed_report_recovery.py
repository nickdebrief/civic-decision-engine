"""Stage 77 application-level recovery points.

Recovery points are coordinated bundles, not raw volume snapshots.  This
module deliberately has no route or worker-start side effects.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import sqlite3
import stat
import tarfile
import tempfile
import time
import re
from collections.abc import Mapping as ABCMapping
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from api import record_governed_reports as reports

RECOVERY_SCHEMA_VERSION = "stage77.recovery.v1"
MANIFEST_SCHEMA_VERSION = "stage77.recovery_manifest.v1"
RECOVERY_STATES = {
    "requested", "draining", "quiesced", "capturing", "validating",
    "completed", "failed", "restore_validating", "restore_ready", "restore_failed",
}
TERMINAL_STATES = {"completed", "failed", "restore_ready", "restore_failed"}
ACTIVE_STATES = {"requested", "draining", "quiesced", "capturing", "validating", "restore_validating"}
ALLOWED_MANIFEST_KEYS = {
    "manifest_schema_version", "recovery_point_id", "maintenance_epoch", "created_at",
    "source_database_identity", "sqlite_version", "application_version",
    "publication_engine_version", "stage77_schema_version", "database",
    "integrity", "job_event_bound", "recovery_event_bound", "job_state_counts", "counts", "artifacts",
    "limitations",
}
ALLOWED_ARTIFACT_KEYS = {"artifact_id", "report_id", "version_id", "format", "filename", "size_bytes", "sha256"}
MAX_MANIFEST_ARTIFACTS = 10000
MAX_MANIFEST_TEXT = 256
BACKUP_DEADLINE_SECONDS = 30.0
EXPORT_RECEIPT_SCHEMA_VERSION = "stage77.recovery_receipt.v1"
ALLOWED_RECEIPT_KEYS = {
    "receipt_schema_version", "recovery_point_id", "created_at", "recovery_reason",
    "manifest_digest", "database_digest", "archive_digest", "artifact_count",
    "recovery_event_bound", "job_event_bound", "application_version",
    "publication_engine_version", "stage77_schema_version",
}
MAX_EXPORT_REASON = 256
BOUNDED_FAILURE_CODES = {
    "artifact_digest_mismatch", "duplicate_artifact_source", "artifact_invalid",
    "artifact_outside_root", "artifact_changed_during_capture", "backup_timeout",
    "integrity_check_failed", "foreign_key_check_failed", "recovery_point_exists",
    "bundle_file_inventory_invalid", "job_state_count_mismatch", "record_count_mismatch",
    "version_count_mismatch", "recovery_event_bound_mismatch", "recovery_not_draining",
    "recovery_not_quiesced", "recovery_already_active", "recovery_terminal_immutable",
    "recovery_operation_failed", "sqlite_error", "digest_mismatch", "manifest_invalid",
    "recovery_root_invalid", "recovery_root_outside_durable_root", "recovery_root_overlap",
    "recovery_root_overlaps_database", "recovery_root_overlaps_artifacts", "symlink_component",
}
RECOVERY_DIAGNOSTIC_PHASES = {"configuration", "initialization", "maintenance", "drain", "capture", "validation", "promotion", "completion"}
RECOVERY_DIAGNOSTIC_OPERATIONS = {
    "recovery_root_validation", "connection_configuration", "job_schema", "recovery_tables",
    "maintenance_epoch_creation", "maintenance_epoch_validation", "worker_quiescence",
    "capture_state_write", "staging_directory", "wal_checkpoint", "capture_transaction_begin",
    "online_backup_destination_connection", "online_backup_source_connection", "online_backup_execution",
    "backup_completion", "database_integrity_check", "foreign_key_check", "job_event_bound_read",
    "recovery_event_bound_read", "artifact_registration_inventory_read", "artifact_copy",
    "artifact_stability_check", "manifest_database_reads", "manifest_write", "bundle_validation",
    "bundle_promotion", "completion_event_write", "completion_transaction_commit",
    "failure_event_write", "failure_transaction_commit", "capture_transaction_rollback",
}
RECOVERY_DIAGNOSTIC_CHECKPOINTS = {"starting", "waiting", "progress", "completed", "failed"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _code(exc: BaseException) -> str:
    text = str(exc).lower()
    if text in BOUNDED_FAILURE_CODES:
        return text
    if isinstance(exc, sqlite3.Error):
        return "sqlite_error"
    if "symlink" in text:
        return "symlink_component"
    if "digest" in text:
        return "digest_mismatch"
    if "manifest" in text:
        return "manifest_invalid"
    if "artifact" in text:
        return "artifact_invalid"
    return "recovery_operation_failed"


class RecoveryOperationFailure(ValueError):
    """Bounded failure context for the explicit recovery CLI."""

    def __init__(self, *, phase: str, operation: str, checkpoint: str, code: str, cleanup_status: str, maintenance_status: str) -> None:
        if phase not in RECOVERY_DIAGNOSTIC_PHASES or operation not in RECOVERY_DIAGNOSTIC_OPERATIONS or checkpoint not in RECOVERY_DIAGNOSTIC_CHECKPOINTS or code not in BOUNDED_FAILURE_CODES or cleanup_status not in {"not_required", "completed", "failed"} or maintenance_status not in {"unknown", "failed"}:
            raise ValueError("recovery_diagnostic_invalid")
        super().__init__(code)
        self.phase = phase
        self.operation = operation
        self.checkpoint = checkpoint
        self.code = code
        self.cleanup_status = cleanup_status
        self.maintenance_status = maintenance_status


def _lexical_path(path: str | os.PathLike[str], *, error: str = "restore_target_invalid") -> Path:
    raw = os.fspath(path)
    value = Path(raw)
    if not value.is_absolute() or os.path.normpath(raw) != raw or any(part in {".", ".."} for part in value.parts):
        raise ValueError(error)
    return value


def _lstat(path: Path) -> os.stat_result | None:
    try:
        return os.lstat(path)
    except FileNotFoundError:
        return None


def _assert_no_symlink_components(path: Path, *, require_directory: bool = False, allow_missing_leaf: bool = False, error: str = "restore_target_invalid") -> None:
    value = _lexical_path(path, error=error)
    current = Path(value.anchor)
    parts = value.parts[1:]
    for index, part in enumerate(parts):
        current /= part
        metadata = _lstat(current)
        if metadata is None:
            if allow_missing_leaf and index == len(parts) - 1:
                return
            raise ValueError(error)
        if stat.S_ISLNK(metadata.st_mode):
            raise ValueError(error)
        if index < len(parts) - 1 and not stat.S_ISDIR(metadata.st_mode):
            raise ValueError(error)
    if require_directory:
        metadata = _lstat(value)
        if metadata is None or not stat.S_ISDIR(metadata.st_mode):
            raise ValueError(error)


def _safe_child(root: Path, child: Path) -> Path:
    root = _lexical_path(root, error="symlink_component")
    child = _lexical_path(child, error="symlink_component")
    _assert_no_symlink_components(root, require_directory=True, error="symlink_component")
    if not child.is_relative_to(root):
        raise ValueError("path_outside_recovery_root")
    _assert_no_symlink_components(child.parent, require_directory=True, error="symlink_component")
    if _lstat(child) is not None:
        raise ValueError("symlink_component")
    if not child.resolve(strict=False).is_relative_to(root.resolve(strict=True)):
        raise ValueError("path_outside_recovery_root")
    return child


def _restore_root(path: str | os.PathLike[str], approved_root: str | os.PathLike[str]) -> Path:
    approved = _lexical_path(approved_root)
    root = _lexical_path(path)
    _assert_no_symlink_components(approved, require_directory=True)
    _assert_no_symlink_components(root, require_directory=True)
    if not root.is_relative_to(approved):
        raise ValueError("restore_target_invalid")
    return root


def _restore_target(path: str | os.PathLike[str], root: Path, live_paths: set[Path]) -> Path:
    target = _lexical_path(path)
    if not target.is_relative_to(root) or target == root:
        raise ValueError("restore_target_invalid")
    _assert_no_symlink_components(target.parent, require_directory=True)
    if _lstat(target) is not None:
        raise ValueError("restore_target_invalid")
    resolved = target.resolve(strict=False)
    if not resolved.is_relative_to(root.resolve(strict=True)) or resolved in live_paths:
        raise ValueError("restore_target_invalid")
    return target


def _open_directory_chain(root: Path, target: Path) -> tuple[int, list[int]]:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fds: list[int] = []
    try:
        root_fd = os.open(root, flags)
        fds.append(root_fd)
        for part in target.relative_to(root).parts:
            next_fd = os.open(part, flags, dir_fd=fds[-1])
            fds.append(next_fd)
        return fds[-1], fds
    except (OSError, ValueError) as exc:
        for fd in reversed(fds):
            os.close(fd)
        raise ValueError("restore_target_invalid") from exc


def _remove_tree_no_follow(path: Path) -> None:
    metadata = _lstat(path)
    if metadata is None:
        return
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        path.unlink(missing_ok=True)
        return
    for entry in os.scandir(path):
        child = Path(entry.path)
        child_metadata = _lstat(child)
        if child_metadata is not None and stat.S_ISDIR(child_metadata.st_mode) and not stat.S_ISLNK(child_metadata.st_mode):
            _remove_tree_no_follow(child)
        else:
            child.unlink(missing_ok=True)
    path.rmdir()


def _assert_bundle_tree(bundle: Path) -> None:
    metadata = _lstat(bundle)
    if metadata is None or stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ValueError("bundle_file_invalid")
    pending = [bundle]
    while pending:
        current = pending.pop()
        for entry in os.scandir(current):
            child = Path(entry.path)
            child_metadata = _lstat(child)
            if child_metadata is None or stat.S_ISLNK(child_metadata.st_mode):
                raise ValueError("bundle_file_invalid")
            if stat.S_ISDIR(child_metadata.st_mode):
                pending.append(child)
            elif not stat.S_ISREG(child_metadata.st_mode):
                raise ValueError("bundle_file_invalid")


def _copy_file_no_follow(source: Path, destination_dir_fd: int, name: str) -> None:
    source_fd = -1
    destination_fd = -1
    try:
        source_fd = os.open(source, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        destination_fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600, dir_fd=destination_dir_fd)
        while True:
            data = os.read(source_fd, 1024 * 1024)
            if not data:
                break
            os.write(destination_fd, data)
    except OSError as exc:
        raise ValueError("restore_target_invalid") from exc
    finally:
        if source_fd >= 0:
            os.close(source_fd)
        if destination_fd >= 0:
            os.close(destination_fd)


def _promote_file_no_replace(source_dir_fd: int, source_name: str, destination_dir_fd: int, destination_name: str) -> None:
    try:
        os.link(source_name, destination_name, src_dir_fd=source_dir_fd, dst_dir_fd=destination_dir_fd, follow_symlinks=False)
        os.unlink(source_name, dir_fd=source_dir_fd)
    except OSError as exc:
        raise ValueError("restore_target_invalid") from exc


def _assert_absent_at(directory_fd: int, name: str) -> None:
    try:
        os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    except OSError as exc:
        raise ValueError("restore_target_invalid") from exc
    raise ValueError("restore_target_invalid")


def _promote_directory_no_replace(source_dir_fd: int, source_name: str, destination_dir_fd: int, destination_name: str) -> None:
    try:
        os.mkdir(destination_name, 0o700, dir_fd=destination_dir_fd)
        source_fd = os.open(source_name, os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0), dir_fd=source_dir_fd)
        destination_fd = os.open(destination_name, os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0), dir_fd=destination_dir_fd)
        try:
            for entry in os.scandir(source_fd):
                if not entry.is_file(follow_symlinks=False) or entry.is_symlink():
                    raise ValueError("restore_target_invalid")
                _promote_file_no_replace(source_fd, entry.name, destination_fd, entry.name)
        finally:
            os.close(source_fd)
            os.close(destination_fd)
        os.rmdir(source_name, dir_fd=source_dir_fd)
    except OSError as exc:
        raise ValueError("restore_target_invalid") from exc


def _require_recovery_root(root: str | os.PathLike[str], *, approved_root: str | os.PathLike[str] = "/data") -> Path:
    value = Path(root)
    approved = Path(approved_root)
    if not value.is_absolute() or not approved.is_absolute():
        raise ValueError("recovery_root_invalid")
    if not approved.exists() or not approved.is_dir() or value.is_symlink() or approved.is_symlink():
        raise ValueError("symlink_component")
    current = value
    while current != approved and current != current.parent:
        if current.exists() and current.is_symlink():
            raise ValueError("symlink_component")
        current = current.parent
    resolved = value.resolve(strict=False)
    approved_resolved = approved.resolve(strict=False)
    if not resolved.is_relative_to(approved_resolved):
        raise ValueError("recovery_root_outside_durable_root")
    if Path(os.getenv("RECORDS_DB_PATH", "/data/records.db")).resolve(strict=False) == resolved:
        raise ValueError("recovery_root_overlaps_database")
    if Path(os.getenv("CDE_REPORT_ARTIFACT_ROOT", "/data/cde-governed-reports")).resolve(strict=False) == resolved:
        raise ValueError("recovery_root_overlaps_artifacts")
    return resolved


def _connect(path: str | os.PathLike[str]) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=5, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _read_connection(path: str | os.PathLike[str]) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=5, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _foreign_keys_are_clean(conn: sqlite3.Connection) -> bool:
    return not conn.execute("PRAGMA foreign_key_check").fetchall()


def ensure_recovery_tables(conn: sqlite3.Connection) -> None:
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS stage77_recovery_control (
      singleton INTEGER PRIMARY KEY CHECK(singleton=1),
      operation_id TEXT NOT NULL,
      recovery_point_id TEXT NOT NULL,
      operation_type TEXT NOT NULL,
      requested_actor TEXT NOT NULL,
      governed_action TEXT NOT NULL,
      state TEXT NOT NULL,
      maintenance_epoch INTEGER NOT NULL,
      requested_at TEXT NOT NULL,
      drain_started_at TEXT,
      quiesced_at TEXT,
      capture_started_at TEXT,
      validation_started_at TEXT,
      completed_at TEXT,
      failed_at TEXT,
      failure_phase TEXT,
      failure_code TEXT,
      schema_version TEXT NOT NULL,
      manifest_digest TEXT,
      source_database_identity TEXT,
      worker_drained INTEGER NOT NULL DEFAULT 0,
      idempotency_key TEXT NOT NULL DEFAULT '',
      restore_validation_required INTEGER NOT NULL DEFAULT 0,
      CHECK(state IN ('requested','draining','quiesced','capturing','validating','completed','failed','restore_validating','restore_ready','restore_failed'))
    );
    CREATE TABLE IF NOT EXISTS stage77_recovery_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      operation_id TEXT NOT NULL,
      recovery_point_id TEXT NOT NULL,
      event_type TEXT NOT NULL,
      resulting_state TEXT NOT NULL,
      actor TEXT NOT NULL,
      occurred_at TEXT NOT NULL,
      payload_json TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_stage77_recovery_events_point ON stage77_recovery_events(recovery_point_id,id);
    CREATE TRIGGER IF NOT EXISTS stage77_recovery_events_no_update
      BEFORE UPDATE ON stage77_recovery_events
      BEGIN SELECT RAISE(ABORT, 'recovery_event_immutable'); END;
    CREATE TRIGGER IF NOT EXISTS stage77_recovery_events_no_delete
      BEFORE DELETE ON stage77_recovery_events
      BEGIN SELECT RAISE(ABORT, 'recovery_event_immutable'); END;
    """)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(stage77_recovery_control)").fetchall()}
    if "idempotency_key" not in columns:
        conn.execute("ALTER TABLE stage77_recovery_control ADD COLUMN idempotency_key TEXT NOT NULL DEFAULT ''")


def _control(conn: sqlite3.Connection) -> sqlite3.Row | None:
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='stage77_recovery_control'").fetchone() is None:
        return None
    return conn.execute("SELECT * FROM stage77_recovery_control WHERE singleton=1").fetchone()


def recovery_status(conn: sqlite3.Connection) -> dict[str, Any]:
    row = _control(conn)
    if row is None:
        return {"state": "inactive", "maintenance_epoch": 0, "restore_validation_required": False}
    return dict(row)


def recovery_allows_claim(conn: sqlite3.Connection) -> bool:
    status = recovery_status(conn)
    if status["state"] in ACTIVE_STATES or bool(status.get("restore_validation_required")):
        return False
    if status["state"] in {"failed", "restore_failed"} and not bool(status.get("worker_drained")):
        return False
    if status["state"] == "restore_ready" and not status.get("manifest_digest"):
        return False
    if _control(conn) is not None and conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='stage77_report_jobs'").fetchone() is not None:
        maximum_epoch = conn.execute("SELECT COALESCE(MAX(maintenance_epoch),0) FROM stage77_report_jobs").fetchone()[0]
        if int(maximum_epoch) > int(status.get("maintenance_epoch", 0)):
            return False
    return True


def recovery_allows_finalize(conn: sqlite3.Connection, job_id: int, token: str, job_epoch: int) -> bool:
    status = recovery_status(conn)
    if status["state"] in ACTIVE_STATES or status["state"] in {"failed", "restore_failed"} or bool(status.get("restore_validation_required")):
        return False
    row = conn.execute("SELECT lease_token,maintenance_epoch,cancellation_requested_at,state FROM stage77_report_jobs WHERE id=?", (job_id,)).fetchone()
    return bool(row and row["lease_token"] == token and int(row["maintenance_epoch"] or 0) == int(job_epoch) and row["state"] in {"leased", "running"} and not row["cancellation_requested_at"])


def _event(conn: sqlite3.Connection, control: Mapping[str, Any], event_type: str, state: str, actor: str, payload: Mapping[str, Any] | None = None) -> None:
    conn.execute("INSERT INTO stage77_recovery_events(operation_id,recovery_point_id,event_type,resulting_state,actor,occurred_at,payload_json) VALUES(?,?,?,?,?,?,?)", (control["operation_id"], control["recovery_point_id"], event_type, state, actor, utc_now(), canonical_json(dict(payload or {}))))


def request_recovery(conn: sqlite3.Connection, *, actor: str, governed_action: str, idempotency_key: str = "") -> dict[str, Any]:
    ensure_recovery_tables(conn)
    conn.execute("BEGIN IMMEDIATE")
    try:
        old = _control(conn)
        if old and old["state"] in ACTIVE_STATES:
            raise ValueError("recovery_already_active")
        if old and old["state"] == "completed" and idempotency_key and old["idempotency_key"] == idempotency_key:
            conn.commit()
            return dict(old)
        epoch = int(old["maintenance_epoch"] if old else 0) + 1
        control = {
            "operation_id": secrets.token_hex(16),
            "recovery_point_id": secrets.token_hex(16),
            "operation_type": "capture",
            "requested_actor": str(actor),
            "governed_action": str(governed_action),
            "state": "draining",
            "maintenance_epoch": epoch,
            "requested_at": utc_now(),
            "drain_started_at": utc_now(),
        }
        conn.execute("INSERT OR REPLACE INTO stage77_recovery_control(singleton,operation_id,recovery_point_id,operation_type,requested_actor,governed_action,state,maintenance_epoch,requested_at,drain_started_at,schema_version,worker_drained,idempotency_key) VALUES(1,?,?,?,?,?,?,?,?,?,?,0,?)", (control["operation_id"], control["recovery_point_id"], control["operation_type"], control["requested_actor"], control["governed_action"], control["state"], epoch, control["requested_at"], control["drain_started_at"], RECOVERY_SCHEMA_VERSION, idempotency_key))
        row = _control(conn)
        _event(conn, row, "recovery_requested", "draining", actor, {"maintenance_epoch": epoch})
        conn.commit()
        return dict(row)
    except Exception:
        conn.rollback()
        raise


def wait_for_quiescence(conn: sqlite3.Connection, *, deadline: float) -> dict[str, Any]:
    ensure_recovery_tables(conn)
    while time.monotonic() < deadline:
        active = conn.execute("SELECT COUNT(*) FROM stage77_report_jobs WHERE state IN ('leased','running')").fetchone()[0]
        if active == 0:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = _control(conn)
                if not row or row["state"] not in {"draining", "quiesced"}:
                    raise ValueError("recovery_not_draining")
                conn.execute("UPDATE stage77_recovery_control SET state='quiesced',quiesced_at=?,worker_drained=1 WHERE singleton=1", (utc_now(),))
                updated = _control(conn)
                _event(conn, updated, "worker_drained", "quiesced", updated["requested_actor"], {})
                conn.commit()
                return dict(updated)
            except Exception:
                conn.rollback()
                raise
        time.sleep(0.01)
    fail_recovery(conn, phase="drain", code="drain_timeout")
    raise ValueError("drain_timeout")


def _set_capture_state(conn: sqlite3.Connection, state: str) -> dict[str, Any]:
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = _control(conn)
        if not row or row["state"] != "quiesced":
            raise ValueError("recovery_not_quiesced")
        timestamp = utc_now()
        column = "capture_started_at" if state == "capturing" else "validation_started_at"
        conn.execute(f"UPDATE stage77_recovery_control SET state=?,{column}=? WHERE singleton=1", (state, timestamp))
        updated = _control(conn)
        _event(conn, updated, "capture_started" if state == "capturing" else "bundle_validating", state, updated["requested_actor"], {})
        conn.commit()
        return dict(updated)
    except Exception:
        conn.rollback()
        raise


def fail_recovery(conn: sqlite3.Connection, *, phase: str, code: str) -> None:
    ensure_recovery_tables(conn)
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = _control(conn)
        if row:
            if row["state"] in TERMINAL_STATES:
                raise ValueError("recovery_terminal_immutable")
            conn.execute("UPDATE stage77_recovery_control SET state='failed',failed_at=?,failure_phase=?,failure_code=?,worker_drained=0 WHERE singleton=1", (utc_now(), phase, code))
            updated = _control(conn)
            _event(conn, updated, "recovery_failed", "failed", updated["requested_actor"], {"phase": phase, "code": code})
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def _operation_staging_path(recovery_root: str | os.PathLike[str], operation_id: str, approved_root: str | os.PathLike[str] = "/data") -> Path:
    if not re.fullmatch(r"[0-9a-f]{32}", operation_id):
        raise ValueError("recovery_abort_identity_invalid")
    root = _require_recovery_root(recovery_root, approved_root=approved_root)
    stage_root = root / ".stage"
    if stage_root.exists() and stage_root.is_symlink():
        raise ValueError("symlink_component")
    stage = stage_root / operation_id
    if stage.exists() and stage.is_symlink():
        raise ValueError("symlink_component")
    if stage.exists() and not stage.is_dir():
        raise ValueError("recovery_abort_staging_invalid")
    return stage


def abort_recovery(conn: sqlite3.Connection, *, recovery_operation_id: str, maintenance_epoch: int, recovery_root: str | os.PathLike[str], actor: str, governed_action: str, approved_root: str | os.PathLike[str] = "/data") -> dict[str, Any]:
    """Release fencing for one explicitly identified failed operation."""
    if not re.fullmatch(r"[0-9a-f]{32}", str(recovery_operation_id)):
        raise ValueError("recovery_abort_identity_invalid")
    if isinstance(maintenance_epoch, bool) or not isinstance(maintenance_epoch, int) or maintenance_epoch <= 0:
        raise ValueError("recovery_abort_epoch_invalid")
    ensure_recovery_tables(conn)
    conn.execute("BEGIN IMMEDIATE")
    prior_state = None
    try:
        row = conn.execute("SELECT * FROM stage77_recovery_control WHERE singleton=1 AND operation_id=? AND maintenance_epoch=?", (recovery_operation_id, maintenance_epoch)).fetchone()
        if row is None:
            raise ValueError("recovery_abort_identity_or_epoch_mismatch")
        prior_state = str(row["state"])
        if prior_state not in {"failed", "restore_failed"} or int(row["worker_drained"] or 0) != 0:
            raise ValueError("recovery_abort_state_mismatch")
        updated_cursor = conn.execute("UPDATE stage77_recovery_control SET worker_drained=1 WHERE singleton=1 AND operation_id=? AND maintenance_epoch=? AND state IN ('failed','restore_failed') AND worker_drained=0", (recovery_operation_id, maintenance_epoch))
        if updated_cursor.rowcount != 1:
            raise ValueError("recovery_abort_conditional_update")
        updated = _control(conn)
        _event(conn, updated, "recovery_aborted", updated["state"], actor, {"governed_action": governed_action, "operation_id": recovery_operation_id, "maintenance_epoch": maintenance_epoch, "prior_state": prior_state, "resulting_state": updated["state"]})
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    cleanup_status = "completed"
    try:
        stage = _operation_staging_path(recovery_root, recovery_operation_id, approved_root=approved_root)
        if stage.exists():
            shutil.rmtree(stage, ignore_errors=False)
    except Exception:
        cleanup_status = "failed"
    return {"operation_id": recovery_operation_id, "maintenance_epoch": maintenance_epoch, "prior_state": prior_state, "resulting_state": str(updated["state"]), "cleanup_status": cleanup_status, "maintenance_status": "released"}


def _live_artifact_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT id,version_id,format,storage_reference,sha256,size_bytes FROM record_governed_report_artifacts WHERE validation_state='valid' ORDER BY id").fetchall()


def _copy_artifact(root: Path, destination: Path, row: sqlite3.Row) -> dict[str, Any]:
    source = Path(str(row["storage_reference"]))
    if source.is_symlink() or not source.is_file():
        raise ValueError("artifact_invalid")
    current = source
    while current != root and current != current.parent:
        if current.exists() and current.is_symlink():
            raise ValueError("artifact_invalid")
        current = current.parent
    resolved_root = root.resolve(strict=False)
    resolved_source = source.resolve(strict=False)
    if not resolved_source.is_relative_to(resolved_root):
        raise ValueError("artifact_outside_root")
    data = source.read_bytes()
    digest = digest_bytes(data)
    if len(data) != int(row["size_bytes"]) or digest != str(row["sha256"]):
        raise ValueError("artifact_digest_mismatch")
    filename = f"artifact-{int(row['id'])}-{str(row['format']).lower()}"
    destination.joinpath(filename).write_bytes(data)
    return {"artifact_id": int(row["id"]), "report_id": _report_id_for_version(row), "version_id": int(row["version_id"]), "format": str(row["format"]), "filename": f"artifacts/{filename}", "size_bytes": len(data), "sha256": digest}


def _report_id_for_version(row: sqlite3.Row) -> int:
    # The report id is intentionally obtained by a bounded query at capture time.
    # This helper is replaced by the caller when a connection is available.
    return int(row.get("report_id", row["version_id"])) if isinstance(row, dict) else int(row["version_id"])


def _database_identity(path: Path, data: bytes) -> str:
    return f"sqlite:{path.stat().st_size}:{digest_bytes(data)}"


def _validate_manifest(manifest: Mapping[str, Any]) -> None:
    if set(manifest) != ALLOWED_MANIFEST_KEYS or manifest.get("manifest_schema_version") != MANIFEST_SCHEMA_VERSION:
        raise ValueError("manifest_invalid")
    if not isinstance(manifest, ABCMapping) or not isinstance(manifest.get("artifacts"), list) or not isinstance(manifest.get("limitations"), list):
        raise ValueError("manifest_invalid")
    if len(manifest["artifacts"]) > MAX_MANIFEST_ARTIFACTS or len(manifest["limitations"]) > 16:
        raise ValueError("manifest_invalid")
    if not isinstance(manifest["recovery_point_id"], str) or not manifest["recovery_point_id"] or len(manifest["recovery_point_id"]) > MAX_MANIFEST_TEXT:
        raise ValueError("manifest_invalid")
    if isinstance(manifest["maintenance_epoch"], bool) or not isinstance(manifest["maintenance_epoch"], int) or manifest["maintenance_epoch"] < 0:
        raise ValueError("manifest_invalid")
    if not isinstance(manifest["created_at"], str) or not manifest["created_at"].endswith("Z"):
        raise ValueError("manifest_invalid")
    try:
        datetime.fromisoformat(manifest["created_at"][:-1] + "+00:00")
    except (TypeError, ValueError):
        raise ValueError("manifest_invalid") from None
    for field in ("source_database_identity", "sqlite_version", "application_version", "publication_engine_version", "stage77_schema_version"):
        if not isinstance(manifest[field], str) or not manifest[field] or len(manifest[field]) > MAX_MANIFEST_TEXT:
            raise ValueError("manifest_invalid")
    if isinstance(manifest["job_event_bound"], bool) or not isinstance(manifest["job_event_bound"], int) or manifest["job_event_bound"] < 0:
        raise ValueError("manifest_invalid")
    if isinstance(manifest["recovery_event_bound"], bool) or not isinstance(manifest["recovery_event_bound"], int) or manifest["recovery_event_bound"] < 0:
        raise ValueError("manifest_invalid")
    if not isinstance(manifest.get("integrity"), ABCMapping) or set(manifest["integrity"]) != {"integrity_check", "foreign_key_check"} or manifest["integrity"] != {"integrity_check": "ok", "foreign_key_check": "ok"}:
        raise ValueError("manifest_invalid")
    if not isinstance(manifest.get("counts"), ABCMapping) or not isinstance(manifest.get("job_state_counts"), ABCMapping) or set(manifest["counts"]) != {"jobs", "reports", "versions", "artifacts"} or set(manifest["job_state_counts"]) != {"queued", "leased", "running", "retry_wait", "cancel_requested", "succeeded", "failed_terminal", "cancelled"}:
        raise ValueError("manifest_invalid")
    for value in list(manifest["counts"].values()) + list(manifest["job_state_counts"].values()):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError("manifest_invalid")
    database = manifest.get("database")
    if not isinstance(database, ABCMapping):
        raise ValueError("manifest_invalid")
    if set(database) != {"filename", "size_bytes", "sha256"} or database["filename"] != "database.sqlite3" or isinstance(database["size_bytes"], bool) or not isinstance(database["size_bytes"], int) or database["size_bytes"] < 0:
        raise ValueError("manifest_invalid")
    if not isinstance(database["sha256"], str) or len(database["sha256"]) != 64 or any(c not in "0123456789abcdef" for c in database["sha256"]):
        raise ValueError("manifest_invalid")
    if any(not isinstance(item, str) or len(item) > MAX_MANIFEST_TEXT for item in manifest["limitations"]):
        raise ValueError("manifest_invalid")
    previous = None
    for artifact in manifest["artifacts"]:
        if not isinstance(artifact, ABCMapping) or set(artifact) != ALLOWED_ARTIFACT_KEYS:
            raise ValueError("manifest_invalid")
        if any(isinstance(artifact.get(field), bool) or not isinstance(artifact.get(field), int) or artifact[field] < 0 for field in ("artifact_id", "report_id", "version_id", "size_bytes")):
            raise ValueError("manifest_invalid")
        if not isinstance(artifact["filename"], str):
            raise ValueError("manifest_invalid")
        filename = artifact["filename"]
        if not filename or "\\" in filename or Path(filename).is_absolute() or ".." in Path(filename).parts or filename != filename.replace("//", "/"):
            raise ValueError("manifest_invalid")
        if not isinstance(artifact["format"], str) or not artifact["format"] or len(artifact["format"]) > 32:
            raise ValueError("manifest_invalid")
        if not isinstance(artifact["sha256"], str) or len(artifact["sha256"]) != 64 or any(c not in "0123456789abcdef" for c in artifact["sha256"]):
            raise ValueError("manifest_invalid")
        order = (int(artifact["artifact_id"]), filename)
        if previous is not None and order <= previous:
            raise ValueError("manifest_invalid")
        previous = order
    if len({int(item["artifact_id"]) for item in manifest["artifacts"]}) != len(manifest["artifacts"]):
        raise ValueError("manifest_invalid")
    if len({str(item["filename"]) for item in manifest["artifacts"]}) != len(manifest["artifacts"]):
        raise ValueError("manifest_invalid")


def _bundle_files(bundle: Path) -> set[str]:
    files = set()
    for path in bundle.rglob("*"):
        if path.is_dir():
            continue
        if path.is_symlink() or not path.is_file():
            raise ValueError("bundle_file_invalid")
        files.add(str(path.relative_to(bundle)))
    return files


def _manifest_and_digest(bundle: Path) -> tuple[dict[str, Any], str]:
    _assert_bundle_tree(bundle)
    manifest_path = bundle / "manifest.json"
    digest_path = bundle / "manifest.sha256"
    if not manifest_path.is_file() or not digest_path.is_file():
        raise ValueError("manifest_missing")
    raw = manifest_path.read_bytes()
    digest = digest_bytes(raw)
    if digest_path.read_text(encoding="ascii").strip() != digest:
        raise ValueError("manifest_digest_mismatch")
    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("manifest_invalid")
            result[key] = value
        return result
    manifest = json.loads(raw.decode("utf-8"), object_pairs_hook=reject_duplicate_keys)
    _validate_manifest(manifest)
    if raw != canonical_json(manifest).encode("utf-8"):
        raise ValueError("manifest_invalid")
    return manifest, digest


def _verify_bundle(bundle: Path, manifest: Mapping[str, Any]) -> None:
    expected = {"database.sqlite3", "manifest.json", "manifest.sha256"} | {str(item["filename"]) for item in manifest["artifacts"]}
    if _bundle_files(bundle) != expected:
        raise ValueError("bundle_file_inventory_invalid")
    database = bundle / "database.sqlite3"
    data = database.read_bytes()
    if len(data) != int(manifest["database"]["size_bytes"]) or digest_bytes(data) != manifest["database"]["sha256"]:
        raise ValueError("database_digest_mismatch")
    conn = _read_connection(database)
    try:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        required = {"record_governed_reports", "record_governed_report_versions", "record_governed_report_artifacts", "stage77_report_jobs", "stage77_report_job_events", "stage77_recovery_control", "stage77_recovery_events"}
        if not required.issubset(tables):
            raise ValueError("schema_incompatible")
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("integrity_check_failed")
        if not _foreign_keys_are_clean(conn):
            raise ValueError("foreign_key_check_failed")
        event_bound = int(conn.execute("SELECT COALESCE(MAX(id),0) FROM stage77_recovery_events").fetchone()[0])
        if event_bound != int(manifest["recovery_event_bound"]):
            raise ValueError("recovery_event_bound_mismatch")
        rows = conn.execute("SELECT id,version_id,format,storage_reference,sha256,size_bytes FROM record_governed_report_artifacts WHERE validation_state='valid' ORDER BY id").fetchall()
        if len(rows) != len(manifest["artifacts"]):
            raise ValueError("artifact_inventory_mismatch")
        actual_job_states = {state: int(conn.execute("SELECT COUNT(*) FROM stage77_report_jobs WHERE state=?", (state,)).fetchone()[0]) for state in ("queued", "leased", "running", "retry_wait", "cancel_requested", "succeeded", "failed_terminal", "cancelled")}
        if actual_job_states != manifest["job_state_counts"] or sum(actual_job_states.values()) != int(manifest["counts"]["jobs"]):
            raise ValueError("job_state_count_mismatch")
        if int(manifest["counts"]["artifacts"]) != len(rows):
            raise ValueError("artifact_inventory_mismatch")
        if int(conn.execute("SELECT COUNT(*) FROM record_governed_reports").fetchone()[0]) != int(manifest["counts"]["reports"]):
            raise ValueError("record_count_mismatch")
        if int(conn.execute("SELECT COUNT(*) FROM record_governed_report_versions").fetchone()[0]) != int(manifest["counts"]["versions"]):
            raise ValueError("version_count_mismatch")
        by_id = {int(item["artifact_id"]): item for item in manifest["artifacts"]}
        for row in rows:
            item = by_id.get(int(row["id"]))
            if not item or int(item["report_id"]) != int(conn.execute("SELECT report_id FROM record_governed_report_versions WHERE id=?", (row["version_id"],)).fetchone()[0]) or int(item["version_id"]) != int(row["version_id"]) or str(item["format"]) != str(row["format"]) or int(item["size_bytes"]) != int(row["size_bytes"]) or str(item["sha256"]) != str(row["sha256"]):
                raise ValueError("artifact_inventory_mismatch")
    finally:
        conn.close()
    for item in manifest["artifacts"]:
        data = (bundle / str(item["filename"])).read_bytes()
        if len(data) != int(item["size_bytes"]) or digest_bytes(data) != str(item["sha256"]):
            raise ValueError("artifact_digest_mismatch")


def capture_recovery_point(*, database_path: str | os.PathLike[str], artifact_root: str | os.PathLike[str], recovery_root: str | os.PathLike[str], actor: str, governed_action: str, idempotency_key: str = "", approved_root: str | os.PathLike[str] = "/data", drain_timeout: float = 30.0, application_version: str = "unknown", publication_engine_version: str = "2.0.0") -> dict[str, Any]:
    phase = "configuration"
    operation = "recovery_root_validation"
    checkpoint = "starting"
    try:
        root = _require_recovery_root(recovery_root, approved_root=approved_root)
    except Exception as exc:
        raise RecoveryOperationFailure(phase=phase, operation=operation, checkpoint=checkpoint, code=_code(exc), cleanup_status="not_required", maintenance_status="unknown") from exc
    database = Path(database_path)
    artifacts = Path(artifact_root)
    try:
        if database.resolve(strict=False) == root or artifacts.resolve(strict=False) == root or root.is_relative_to(database.resolve(strict=False)) or root.is_relative_to(artifacts.resolve(strict=False)):
            raise ValueError("recovery_root_overlap")
        root.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        raise RecoveryOperationFailure(phase=phase, operation="recovery_root_validation", checkpoint="starting", code=_code(exc), cleanup_status="not_required", maintenance_status="unknown") from exc
    phase, operation, checkpoint = "initialization", "connection_configuration", "starting"
    try:
        conn = _connect(database)
    except Exception as exc:
        raise RecoveryOperationFailure(phase=phase, operation=operation, checkpoint=checkpoint, code=_code(exc), cleanup_status="not_required", maintenance_status="unknown") from exc
    stage: Path | None = None
    rollback_failed = False
    try:
        from api import governed_report_jobs as jobs
        phase, operation, checkpoint = "initialization", "job_schema", "starting"
        jobs.ensure_job_tables(conn)
        operation = "recovery_tables"
        ensure_recovery_tables(conn)
        phase, operation, checkpoint = "maintenance", "maintenance_epoch_creation", "starting"
        control = request_recovery(conn, actor=actor, governed_action=governed_action, idempotency_key=idempotency_key)
        if control["state"] == "completed":
            final = root / f"recovery-{control['recovery_point_id']}"
            manifest, digest = _manifest_and_digest(final)
            _verify_bundle(final, manifest)
            return {"recovery_point_id": control["recovery_point_id"], "manifest_digest": digest, "state": "completed"}
        phase, operation, checkpoint = "drain", "maintenance_epoch_validation", "starting"
        recovery_status(conn)
        phase, operation, checkpoint = "drain", "worker_quiescence", "waiting"
        wait_for_quiescence(conn, deadline=time.monotonic() + drain_timeout)
        phase, operation, checkpoint = "capture", "capture_state_write", "starting"
        control = _set_capture_state(conn, "capturing")
        phase, operation, checkpoint = "capture", "staging_directory", "creating"
        stage = root / ".stage" / control["operation_id"]
        final = root / f"recovery-{control['recovery_point_id']}"
        if final.exists() or final.is_symlink():
            raise ValueError("recovery_point_exists")
        stage.mkdir(parents=True, exist_ok=False)
        (stage / "artifacts").mkdir()
        phase, operation, checkpoint = "capture", "wal_checkpoint", "starting"
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        phase, operation, checkpoint = "capture", "capture_transaction_begin", "starting"
        conn.execute("BEGIN IMMEDIATE")
        backup_check = None
        try:
            backup_path = stage / "database.sqlite3"
            phase, operation, checkpoint = "capture", "online_backup_destination_connection", "starting"
            backup_conn = None
            backup_source = None
            try:
                backup_conn = sqlite3.connect(backup_path, isolation_level=None)
                phase, operation, checkpoint = "capture", "online_backup_source_connection", "starting"
                backup_source = _read_connection(database)
                deadline = time.monotonic() + BACKUP_DEADLINE_SECONDS
                def backup_progress(_status: int, _remaining: int, _total: int) -> None:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("backup_timeout")
                phase, operation, checkpoint = "capture", "online_backup_execution", "progress"
                backup_source.backup(backup_conn, pages=100, sleep=0.01, progress=backup_progress)
                phase, operation, checkpoint = "capture", "backup_completion", "starting"
                backup_conn.execute("PRAGMA journal_mode=DELETE")
            finally:
                if backup_source is not None:
                    backup_source.close()
                if backup_conn is not None:
                    backup_conn.close()
            backup_data = backup_path.read_bytes()
            phase, operation, checkpoint = "validation", "database_integrity_check", "starting"
            backup_check = _read_connection(backup_path)
            try:
                if backup_check.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("integrity_check_failed")
                phase, operation, checkpoint = "validation", "foreign_key_check", "starting"
                if not _foreign_keys_are_clean(backup_check):
                    raise ValueError("foreign_key_check_failed")
                job_counts = {state: int(backup_check.execute("SELECT COUNT(*) FROM stage77_report_jobs WHERE state=?", (state,)).fetchone()[0]) for state in ("queued", "leased", "running", "retry_wait", "cancel_requested", "succeeded", "failed_terminal", "cancelled")}
                phase, operation, checkpoint = "validation", "job_event_bound_read", "starting"
                max_event = int(backup_check.execute("SELECT COALESCE(MAX(id),0) FROM stage77_report_job_events").fetchone()[0])
                job_count = int(backup_check.execute("SELECT COUNT(*) FROM stage77_report_jobs").fetchone()[0])
                report_count = int(backup_check.execute("SELECT COUNT(*) FROM record_governed_reports").fetchone()[0])
                version_count = int(backup_check.execute("SELECT COUNT(*) FROM record_governed_report_versions").fetchone()[0])
                artifact_count = int(backup_check.execute("SELECT COUNT(*) FROM record_governed_report_artifacts WHERE validation_state='valid'").fetchone()[0])
                phase, operation, checkpoint = "validation", "artifact_registration_inventory_read", "starting"
                rows = backup_check.execute("SELECT id,version_id,format,storage_reference,sha256,size_bytes FROM record_governed_report_artifacts WHERE validation_state='valid' ORDER BY id").fetchall()
                inventory = []
                source_paths: set[Path] = set()
                for row in rows:
                    version = backup_check.execute("SELECT report_id FROM record_governed_report_versions WHERE id=?", (row["version_id"],)).fetchone()
                    source = Path(str(row["storage_reference"])).resolve(strict=False)
                    if source in source_paths:
                        raise ValueError("duplicate_artifact_source")
                    source_paths.add(source)
                    phase, operation, checkpoint = "validation", "artifact_copy", "starting"
                    inventory.append(_copy_artifact(artifacts, stage / "artifacts", dict(row, report_id=int(version[0]))))
                phase, operation, checkpoint = "validation", "artifact_stability_check", "starting"
                for row in rows:
                    current = Path(str(row["storage_reference"]))
                    if current.is_symlink() or not current.is_file() or current.stat().st_size != int(row["size_bytes"]) or digest_bytes(current.read_bytes()) != str(row["sha256"]):
                        raise ValueError("artifact_changed_during_capture")
                phase, operation, checkpoint = "validation", "recovery_event_bound_read", "starting"
                recovery_event_bound = int(backup_check.execute("SELECT COALESCE(MAX(id),0) FROM stage77_recovery_events").fetchone()[0])
                phase, operation, checkpoint = "validation", "manifest_database_reads", "starting"
                manifest = {"manifest_schema_version": MANIFEST_SCHEMA_VERSION, "recovery_point_id": control["recovery_point_id"], "maintenance_epoch": int(control["maintenance_epoch"]), "created_at": utc_now(), "source_database_identity": _database_identity(database, backup_data), "sqlite_version": sqlite3.sqlite_version, "application_version": application_version, "publication_engine_version": publication_engine_version, "stage77_schema_version": "stage77.governed_report_job.v1", "database": {"filename": "database.sqlite3", "size_bytes": len(backup_data), "sha256": digest_bytes(backup_data)}, "integrity": {"integrity_check": "ok", "foreign_key_check": "ok"}, "job_event_bound": max_event, "recovery_event_bound": recovery_event_bound, "job_state_counts": job_counts, "counts": {"jobs": job_count, "reports": report_count, "versions": version_count, "artifacts": artifact_count}, "artifacts": inventory, "limitations": ["integrity evidence is not proof of authorship", "restoration requires isolated target paths and validation", "completion event is recorded after the backup event bound"]}
                raw_manifest = canonical_json(manifest).encode("utf-8")
                phase, operation, checkpoint = "validation", "manifest_write", "starting"
                (stage / "manifest.json").write_bytes(raw_manifest)
                (stage / "manifest.sha256").write_text(digest_bytes(raw_manifest) + "\n", encoding="ascii")
                phase, operation, checkpoint = "validation", "bundle_validation", "starting"
                _verify_bundle(stage, manifest)
                phase, operation, checkpoint = "promotion", "bundle_promotion", "starting"
                os.replace(stage, final)
                phase, operation, checkpoint = "completion", "completion_event_write", "starting"
                conn.execute("UPDATE stage77_recovery_control SET state='completed',completed_at=?,manifest_digest=?,source_database_identity=?,worker_drained=1 WHERE singleton=1", (utc_now(), digest_bytes(raw_manifest), manifest["source_database_identity"]))
                updated = _control(conn)
                _event(conn, updated, "recovery_completed", "completed", actor, {"manifest_digest": digest_bytes(raw_manifest)})
                operation, checkpoint = "completion_transaction_commit", "starting"
                try:
                    conn.commit()
                except Exception:
                    operation, checkpoint = "completion_transaction_commit", "failed"
                    raise
                return {"recovery_point_id": control["recovery_point_id"], "manifest_digest": digest_bytes(raw_manifest), "state": "completed"}
            finally:
                if backup_check is not None:
                    backup_check.close()
        except Exception:
            failed_operation, failed_checkpoint = operation, checkpoint
            try:
                conn.rollback()
            except Exception:
                rollback_failed = True
                operation, checkpoint = "capture_transaction_rollback", "failed"
                operation, checkpoint = failed_operation, failed_checkpoint
            operation, checkpoint = failed_operation, failed_checkpoint
            raise
    except Exception as exc:
        primary_code = _code(exc)
        cleanup_status = "not_required"
        if stage is not None:
            try:
                shutil.rmtree(stage, ignore_errors=False)
                cleanup_status = "completed"
            except Exception:
                cleanup_status = "failed"
        if rollback_failed:
            cleanup_status = "failed"
        maintenance_status = "unknown"
        try:
            fail_recovery(conn, phase=phase, code=primary_code)
            maintenance_status = "failed"
        except Exception:
            maintenance_status = "unknown"
        finally:
            conn.close()
        raise RecoveryOperationFailure(phase=phase, operation=operation, checkpoint=checkpoint, code=primary_code, cleanup_status=cleanup_status, maintenance_status=maintenance_status) from exc
    finally:
        if not conn is None:
            conn.close()


def restore_recovery_point(*, bundle_path: str | os.PathLike[str], restore_root: str | os.PathLike[str], database_target: str | os.PathLike[str], artifact_root_target: str | os.PathLike[str], live_database: str | os.PathLike[str], live_artifact_root: str | os.PathLike[str], live_recovery_root: str | os.PathLike[str], actor: str, governed_action: str, approved_root: str | os.PathLike[str] = "/data", application_version: str = "unknown", publication_engine_version: str = "2.0.0") -> dict[str, Any]:
    root = _restore_root(restore_root, approved_root)
    bundle = _lexical_path(bundle_path, error="bundle_file_invalid")
    _assert_bundle_tree(bundle)
    bundle = bundle.resolve(strict=True)
    live_db = Path(live_database).resolve(strict=False)
    live_artifact = Path(live_artifact_root).resolve(strict=False)
    live_recovery = Path(live_recovery_root).resolve(strict=False)
    if root.resolve(strict=True) in {live_db, live_artifact, live_recovery} or bundle == live_recovery:
        raise ValueError("restore_target_invalid")
    db_target = _restore_target(database_target, root, {live_db, live_artifact, live_recovery})
    artifact_target = _restore_target(artifact_root_target, root, {live_db, live_artifact, live_recovery})
    if db_target.resolve(strict=False).is_relative_to(artifact_target.resolve(strict=False)) or artifact_target.resolve(strict=False).is_relative_to(db_target.resolve(strict=False)):
        raise ValueError("restore_target_overlap")
    manifest, manifest_digest = _manifest_and_digest(bundle)
    if manifest["stage77_schema_version"] != "stage77.governed_report_job.v1" or (application_version != "unknown" and manifest["application_version"] != application_version) or (publication_engine_version != "unknown" and manifest["publication_engine_version"] != publication_engine_version):
        raise ValueError("engine_incompatible")
    _verify_bundle(bundle, manifest)
    root_fd, root_fds = _open_directory_chain(root, root)
    db_parent_fd, db_parent_fds = _open_directory_chain(root, db_target.parent)
    artifact_parent_fd, artifact_parent_fds = _open_directory_chain(root, artifact_target.parent)
    if len({os.fstat(root_fd).st_dev, os.fstat(db_parent_fd).st_dev, os.fstat(artifact_parent_fd).st_dev}) != 1:
        for fds in (root_fds, db_parent_fds, artifact_parent_fds):
            for fd in reversed(fds):
                os.close(fd)
        raise ValueError("restore_target_invalid")
    stage_name = f".restore-{secrets.token_hex(8)}"
    stage = root / stage_name
    stage_fd = -1
    staged_artifacts_fd = -1
    stage_fds: list[int] = []
    staged_artifacts_fds: list[int] = []
    try:
        os.mkdir(stage_name, 0o700, dir_fd=root_fd)
        stage_fd, stage_fds = _open_directory_chain(root, stage)
        os.mkdir("artifacts", 0o700, dir_fd=stage_fd)
        staged_artifacts_fd, staged_artifacts_fds = _open_directory_chain(root, stage / "artifacts")
        _copy_file_no_follow(bundle / "database.sqlite3", stage_fd, "database.sqlite3")
        for item in manifest["artifacts"]:
            filename = Path(str(item["filename"])).name
            _safe_child(stage / "artifacts", stage / "artifacts" / filename)
            _copy_file_no_follow(bundle / str(item["filename"]), staged_artifacts_fd, filename)
        conn = _read_connection(stage / "database.sqlite3")
        try:
            ensure_recovery_tables(conn)
            conn.execute("BEGIN IMMEDIATE")
            old = _control(conn)
            epoch = int(old["maintenance_epoch"] if old else 0) + 1
            operation_id = secrets.token_hex(16)
            point_id = str(manifest["recovery_point_id"])
            conn.execute("INSERT OR REPLACE INTO stage77_recovery_control(singleton,operation_id,recovery_point_id,operation_type,requested_actor,governed_action,state,maintenance_epoch,requested_at,validation_started_at,manifest_digest,source_database_identity,schema_version,restore_validation_required,worker_drained) VALUES(1,?,?,?,?,?,?,?,?,?,?,?,?,1,1)", (operation_id, point_id, "restore", str(actor), str(governed_action), "restore_validating", epoch, utc_now(), utc_now(), manifest_digest, manifest["source_database_identity"], RECOVERY_SCHEMA_VERSION))
            row = _control(conn)
            _event(conn, row, "restore_validation_started", "restore_validating", actor, {})
            # Captured work is deterministic: interrupted work is retryable; a
            # cancellation request is terminal cancellation; terminal success is untouched.
            for job in conn.execute("SELECT id,state FROM stage77_report_jobs WHERE state IN ('leased','running','cancel_requested')").fetchall():
                if job["state"] == "cancel_requested":
                    conn.execute("UPDATE stage77_report_jobs SET state='cancelled',terminal_at=?,terminal_outcome='cancelled',lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL,heartbeat_at=NULL WHERE id=?", (utc_now(), job["id"]))
                    _event(conn, row, "job_recovered_cancelled", "restore_validating", actor, {"job_id": int(job["id"])})
                else:
                    conn.execute("UPDATE stage77_report_jobs SET state='retry_wait',next_eligible_at=?,lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL,heartbeat_at=NULL WHERE id=?", (utc_now(), job["id"]))
                    _event(conn, row, "job_recovered_retryable", "restore_validating", actor, {"job_id": int(job["id"])})
            if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise ValueError("restore_integrity_failed")
            conn.execute("UPDATE stage77_recovery_control SET state='restore_ready',restore_validation_required=0,completed_at=?,worker_drained=1 WHERE singleton=1", (utc_now(),))
            row = _control(conn)
            _event(conn, row, "restore_validation_completed", "restore_ready", actor, {})
            conn.commit()
        finally:
            conn.close()
        _assert_absent_at(db_parent_fd, db_target.name)
        _promote_file_no_replace(stage_fd, "database.sqlite3", db_parent_fd, db_target.name)
        _assert_absent_at(artifact_parent_fd, artifact_target.name)
        _promote_directory_no_replace(stage_fd, "artifacts", artifact_parent_fd, artifact_target.name)
        os.rmdir(stage_name, dir_fd=root_fd)
        return {"state": "restore_ready", "manifest_digest": manifest_digest}
    except Exception:
        _remove_tree_no_follow(stage)
        raise
    finally:
        for fds in (stage_fds, staged_artifacts_fds, root_fds, db_parent_fds, artifact_parent_fds):
            for fd in reversed(fds):
                try:
                    os.close(fd)
                except OSError:
                    pass


def validate_recovery_bundle(bundle_path: str | os.PathLike[str]) -> dict[str, Any]:
    bundle = _lexical_path(bundle_path, error="bundle_file_invalid")
    _assert_bundle_tree(bundle)
    manifest, digest = _manifest_and_digest(bundle)
    _verify_bundle(bundle, manifest)
    return {"state": "valid", "manifest_digest": digest, "recovery_point_id": str(manifest["recovery_point_id"])}


def _safe_export_destination(path: Path, *, error: str = "export_target_invalid") -> Path:
    value = _lexical_path(path, error=error)
    parent = value.parent
    _assert_no_symlink_components(parent, require_directory=True, error=error)
    if _lstat(value) is not None:
        raise ValueError("export_target_exists")
    return value


def _validate_custody_root(path: str | os.PathLike[str]) -> Path:
    root = _lexical_path(path, error="custody_root_invalid")
    _assert_no_symlink_components(root, require_directory=True, error="custody_root_invalid")
    resolved = root.resolve(strict=True)
    forbidden = {
        Path(tempfile.gettempdir()).resolve(),
        Path("/private/tmp").resolve(),
        Path("/tmp").resolve(),
        Path("/data").resolve(),
        Path(__file__).resolve().parents[1],
    }
    if any(resolved == item or resolved.is_relative_to(item) for item in forbidden):
        raise ValueError("custody_root_invalid")
    if resolved.stat().st_mode & 0o077:
        raise ValueError("custody_root_permissions")
    return resolved


def _archive_member_name(name: str) -> PurePosixPath:
    # Archive names are always POSIX-relative, even on the source platform.
    if not name or "\\" in name or name.startswith("/"):
        raise ValueError("export_archive_invalid")
    path = PurePosixPath(name)
    if any(part in {"", ".", ".."} for part in path.parts) or path.is_absolute():
        raise ValueError("export_archive_invalid")
    return path


def _receipt_from_manifest(manifest: Mapping[str, Any], *, archive_digest: str, reason: str) -> dict[str, Any]:
    if not isinstance(reason, str) or not reason or len(reason) > MAX_EXPORT_REASON or any(ord(char) < 0x20 for char in reason):
        raise ValueError("export_reason_invalid")
    return {
        "receipt_schema_version": EXPORT_RECEIPT_SCHEMA_VERSION,
        "recovery_point_id": str(manifest["recovery_point_id"]),
        "created_at": utc_now(),
        "recovery_reason": reason,
        "manifest_digest": str(manifest["_manifest_digest"]),
        "database_digest": str(manifest["database"]["sha256"]),
        "archive_digest": archive_digest,
        "artifact_count": int(manifest["counts"]["artifacts"]),
        "recovery_event_bound": int(manifest["recovery_event_bound"]),
        "job_event_bound": int(manifest["job_event_bound"]),
        "application_version": str(manifest["application_version"]),
        "publication_engine_version": str(manifest["publication_engine_version"]),
        "stage77_schema_version": str(manifest["stage77_schema_version"]),
    }


def _bundle_snapshot(bundle: Path) -> dict[str, tuple[int, str]]:
    snapshot: dict[str, tuple[int, str]] = {}
    for relative in sorted(_bundle_files(bundle)):
        source = bundle / relative
        data = source.read_bytes()
        snapshot[relative] = (len(data), digest_bytes(data))
    return snapshot


def _strict_receipt(raw: bytes) -> dict[str, Any]:
    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("export_receipt_invalid")
            result[key] = value
        return result

    try:
        receipt = json.loads(raw.decode("utf-8"), object_pairs_hook=reject_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError("export_receipt_invalid") from exc
    if not isinstance(receipt, dict) or set(receipt) != ALLOWED_RECEIPT_KEYS or raw != canonical_json(receipt).encode("utf-8"):
        raise ValueError("export_receipt_invalid")
    if receipt["receipt_schema_version"] != EXPORT_RECEIPT_SCHEMA_VERSION:
        raise ValueError("export_receipt_invalid")
    for key in ("recovery_point_id", "created_at", "recovery_reason", "manifest_digest", "database_digest", "archive_digest", "application_version", "publication_engine_version", "stage77_schema_version"):
        if not isinstance(receipt[key], str) or not receipt[key] or len(receipt[key]) > MAX_MANIFEST_TEXT:
            raise ValueError("export_receipt_invalid")
    if any(ord(char) < 0x20 for char in receipt["recovery_reason"]):
        raise ValueError("export_receipt_invalid")
    if not receipt["created_at"].endswith("Z"):
        raise ValueError("export_receipt_invalid")
    try:
        datetime.fromisoformat(receipt["created_at"][:-1] + "+00:00")
    except ValueError:
        raise ValueError("export_receipt_invalid") from None
    for key in ("manifest_digest", "database_digest", "archive_digest"):
        if len(receipt[key]) != 64 or any(char not in "0123456789abcdef" for char in receipt[key]):
            raise ValueError("export_receipt_invalid")
    for key in ("artifact_count", "recovery_event_bound", "job_event_bound"):
        if isinstance(receipt[key], bool) or not isinstance(receipt[key], int) or receipt[key] < 0:
            raise ValueError("export_receipt_invalid")
    return receipt


def _write_deterministic_archive(bundle: Path, archive_path: Path, recovery_point_id: str) -> None:
    root_name = f"recovery-{recovery_point_id}"
    with tarfile.open(archive_path, mode="w", format=tarfile.PAX_FORMAT) as archive:
        members = [bundle] + sorted(bundle.rglob("*"), key=lambda item: str(item.relative_to(bundle)))
        for source in members:
            relative = Path() if source == bundle else source.relative_to(bundle)
            member_name = root_name if not relative.parts else f"{root_name}/{PurePosixPath(*relative.parts)}"
            _archive_member_name(member_name)
            metadata = _lstat(source)
            if metadata is None or stat.S_ISLNK(metadata.st_mode) or not (stat.S_ISDIR(metadata.st_mode) or stat.S_ISREG(metadata.st_mode)):
                raise ValueError("export_source_invalid")
            info = tarfile.TarInfo(member_name)
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            info.mtime = 0
            info.pax_headers = {}
            if stat.S_ISDIR(metadata.st_mode):
                info.type = tarfile.DIRTYPE
                info.mode = 0o700
                archive.addfile(info)
            else:
                info.type = tarfile.REGTYPE
                info.mode = 0o600
                info.size = metadata.st_size
                with source.open("rb") as stream:
                    archive.addfile(info, stream)


def _extract_export_archive(archive_path: Path, destination: Path) -> Path:
    metadata = _lstat(archive_path)
    if metadata is None or stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ValueError("export_archive_invalid")
    if destination.exists() or destination.is_symlink():
        raise ValueError("export_extract_target_invalid")
    _assert_no_symlink_components(destination.parent, require_directory=True, error="export_extract_target_invalid")
    destination.mkdir(mode=0o700)
    try:
        with tarfile.open(archive_path, mode="r:*") as archive:
            members = archive.getmembers()
            names: set[str] = set()
            for member in members:
                _archive_member_name(member.name)
                if member.name in names or member.islnk() or member.issym() or member.isdev() or not (member.isdir() or member.isfile()):
                    raise ValueError("export_archive_invalid")
                names.add(member.name)
            if not members:
                raise ValueError("export_archive_invalid")
            for member in sorted(members, key=lambda item: (not item.isdir(), item.name)):
                target = destination.joinpath(*_archive_member_name(member.name).parts)
                if not target.is_relative_to(destination) or _lstat(target) is not None:
                    raise ValueError("export_archive_invalid")
                if member.isdir():
                    target.mkdir(mode=0o700)
                    continue
                if not target.parent.is_dir() or target.parent.is_symlink():
                    raise ValueError("export_archive_invalid")
                source = archive.extractfile(member)
                if source is None:
                    raise ValueError("export_archive_invalid")
                with target.open("xb") as output:
                    shutil.copyfileobj(source, output)
        roots = [item for item in destination.iterdir() if item.is_dir() and not item.is_symlink()]
        if len(roots) != 1 or any(item.is_symlink() for item in destination.iterdir()):
            raise ValueError("export_archive_invalid")
        return roots[0]
    except Exception:
        _remove_tree_no_follow(destination)
        raise


def validate_export_archive(archive_path: str | os.PathLike[str], receipt_path: str | os.PathLike[str], *, extract_to: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    archive = _lexical_path(archive_path, error="export_archive_invalid")
    receipt_file = _lexical_path(receipt_path, error="export_receipt_invalid")
    receipt = _strict_receipt(receipt_file.read_bytes())
    if digest_bytes(archive.read_bytes()) != receipt["archive_digest"]:
        raise ValueError("export_archive_digest_mismatch")
    temporary = Path(tempfile.mkdtemp(prefix="stage77-export-check-", dir=archive.parent))
    try:
        bundle = _extract_export_archive(archive, temporary / "bundle")
        result = validate_recovery_bundle(bundle)
        manifest, manifest_digest = _manifest_and_digest(bundle)
        if result["recovery_point_id"] != receipt["recovery_point_id"] or manifest_digest != receipt["manifest_digest"] or manifest["database"]["sha256"] != receipt["database_digest"] or int(manifest["counts"]["artifacts"]) != receipt["artifact_count"] or int(manifest["recovery_event_bound"]) != receipt["recovery_event_bound"] or int(manifest["job_event_bound"]) != receipt["job_event_bound"]:
            raise ValueError("export_receipt_mismatch")
        if extract_to is not None:
            extraction_target = _lexical_path(extract_to, error="export_extract_target_invalid")
            try:
                extracted = _extract_export_archive(archive, extraction_target)
                _verify_bundle(extracted, manifest)
            except Exception:
                _remove_tree_no_follow(extraction_target)
                raise
        return {"state": "valid", "recovery_point_id": result["recovery_point_id"], "manifest_digest": manifest_digest, "archive_digest": receipt["archive_digest"]}
    finally:
        _remove_tree_no_follow(temporary)


def export_recovery_bundle(*, bundle_path: str | os.PathLike[str], output_archive: str | os.PathLike[str], receipt_path: str | os.PathLike[str], reason: str, custody_root: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    bundle = _lexical_path(bundle_path, error="bundle_file_invalid")
    bundle_result = validate_recovery_bundle(bundle)
    before_snapshot = _bundle_snapshot(bundle)
    manifest, manifest_digest = _manifest_and_digest(bundle)
    manifest = dict(manifest)
    manifest["_manifest_digest"] = manifest_digest
    archive = _safe_export_destination(Path(output_archive))
    receipt_file = _safe_export_destination(Path(receipt_path))
    if archive == receipt_file or archive.parent != receipt_file.parent:
        raise ValueError("export_target_invalid")
    if custody_root is not None:
        custody = _validate_custody_root(custody_root)
        if not archive.is_relative_to(custody) or not receipt_file.is_relative_to(custody):
            raise ValueError("custody_root_invalid")
    if os.stat(bundle).st_dev != os.stat(archive.parent).st_dev:
        raise ValueError("export_filesystem_mismatch")
    stage = Path(tempfile.mkdtemp(prefix=".stage77-export-", dir=archive.parent))
    promoted_archive = False
    promoted_receipt = False
    try:
        staged_archive = stage / archive.name
        staged_receipt = stage / receipt_file.name
        _write_deterministic_archive(bundle, staged_archive, str(manifest["recovery_point_id"]))
        if _bundle_snapshot(bundle) != before_snapshot:
            raise ValueError("export_source_changed")
        archive_digest = digest_bytes(staged_archive.read_bytes())
        receipt = _receipt_from_manifest(manifest, archive_digest=archive_digest, reason=reason)
        staged_receipt.write_bytes(canonical_json(receipt).encode("utf-8"))
        validate_export_archive(staged_archive, staged_receipt)
        os.replace(staged_archive, archive)
        promoted_archive = True
        os.replace(staged_receipt, receipt_file)
        promoted_receipt = True
        result = validate_export_archive(archive, receipt_file)
        return {**result, "receipt": receipt}
    except Exception:
        if promoted_receipt:
            receipt_file.unlink(missing_ok=True)
        if promoted_archive:
            archive.unlink(missing_ok=True)
        raise
    finally:
        _remove_tree_no_follow(stage)
