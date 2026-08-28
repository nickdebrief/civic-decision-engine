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
from api import governed_report_qualifications as qualifications
from api import governed_report_diagnostics as diagnostics

RECOVERY_SCHEMA_VERSION = "stage77.recovery.v1"
RECOVERY_EVIDENCE_CONTRACT = "stage77.recovery_point_evidence.v1"
REPORT_EVENT_BOUND_STATUSES = {"bound", "not_bound_by_source_contract"}
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
    "integrity", "job_event_bound", "recovery_event_bound", "qualification_event_bound", "qualification_state_digest", "job_state_counts", "counts", "artifacts",
    "limitations",
}
LEGACY_MANIFEST_KEYS = ALLOWED_MANIFEST_KEYS - {"qualification_event_bound", "qualification_state_digest"}
CURRENT_MANIFEST_KEYS = ALLOWED_MANIFEST_KEYS
DIAGNOSTIC_MANIFEST_KEYS = CURRENT_MANIFEST_KEYS | {
    "diagnostic_contract_version", "diagnostic_evidence", "diagnostic_evidence_count",
    "diagnostic_evidence_state_digest", "retry_link_count", "retry_link_state_digest",
}
POST_CORRECTION_MANIFEST_KEYS = DIAGNOSTIC_MANIFEST_KEYS | {
    "current_recovery_manifest_evidence", "current_recovery_manifest_evidence_digest",
    "persisted_prior_recovery_evidence", "persisted_prior_recovery_evidence_state_digest", "persisted_prior_recovery_evidence_event_bound",
    "post_correction_authorization",
    "post_correction_authorization_state_digest",
    "post_correction_authorization_event_bound",
    "post_correction_custody_attestation",
    "post_correction_custody_attestation_state_digest",
    "post_correction_custody_attestation_event_bound",
}
ALLOWED_ARTIFACT_KEYS = {"artifact_id", "report_id", "version_id", "format", "filename", "size_bytes", "sha256"}
MAX_MANIFEST_ARTIFACTS = 10000
MAX_MANIFEST_TEXT = 256
BACKUP_DEADLINE_SECONDS = 30.0
EXPORT_RECEIPT_SCHEMA_VERSION = "stage77.recovery_receipt.v1"
ALLOWED_RECEIPT_KEYS = {
    "receipt_schema_version", "recovery_point_id", "created_at", "recovery_reason",
    "manifest_digest", "database_digest", "archive_digest", "artifact_count", "qualification_count", "qualification_event_bound", "qualification_state_digest",
    "recovery_event_bound", "job_event_bound", "application_version",
    "publication_engine_version", "stage77_schema_version",
}
LEGACY_RECEIPT_KEYS = ALLOWED_RECEIPT_KEYS - {"qualification_count", "qualification_event_bound", "qualification_state_digest"}
CURRENT_RECEIPT_KEYS = ALLOWED_RECEIPT_KEYS
DIAGNOSTIC_RECEIPT_KEYS = CURRENT_RECEIPT_KEYS | {
    "diagnostic_contract_version", "diagnostic_evidence_count", "diagnostic_evidence_state_digest",
    "retry_link_count", "retry_link_state_digest",
}
POST_CORRECTION_RECEIPT_KEYS = DIAGNOSTIC_RECEIPT_KEYS | {
    "post_correction_authorization_state_digest",
    "post_correction_authorization_event_bound",
    "post_correction_custody_attestation_state_digest",
    "post_correction_custody_attestation_event_bound",
}
MAX_EXPORT_REASON = 256
BOUNDED_FAILURE_CODES = {
    "artifact_digest_mismatch", "duplicate_artifact_source", "artifact_invalid",
    "artifact_outside_root", "artifact_changed_during_capture", "backup_timeout",
    "integrity_check_failed", "foreign_key_check_failed", "recovery_point_exists",
    "bundle_file_inventory_invalid", "job_state_count_mismatch", "record_count_mismatch", "qualification_count_mismatch",
    "version_count_mismatch", "report_lifecycle_invalid", "recovery_event_bound_mismatch", "recovery_not_draining",
    "recovery_not_quiesced", "recovery_already_active", "recovery_terminal_immutable",
    "recovery_operation_failed", "schema_incompatible", "sqlite_error", "digest_mismatch", "manifest_invalid",
    "recovery_root_invalid", "recovery_root_outside_durable_root", "recovery_root_overlap",
    "recovery_root_overlaps_database", "recovery_root_overlaps_artifacts", "symlink_component",
    "recovery_evidence_conflict", "recovery_state_ineligible", "diagnostic_evidence_count_mismatch", "diagnostic_evidence_digest_mismatch",
    "specification_digest_mismatch", "governed_report_qualification_chain_invalid",
    "governed_report_qualification_digest_mismatch", "governed_report_qualification_event_invalid",
    "governed_report_qualification_mode_changed", "governed_report_qualification_gate_order_invalid",
    "job_attempt_metadata_invalid", "job_lease_metadata_invalid", "job_maintenance_epoch_mismatch",
    "job_rendering_binding_mismatch", "job_specification_binding_mismatch",
    "job_cancellation_evidence_invalid",
    "job_terminal_evidence_invalid",
    "job_rendering_binding_mismatch", "job_specification_binding_mismatch",
    "native_capture_fault_injected",
}
RECOVERY_DIAGNOSTIC_PHASES = {"configuration", "initialization", "maintenance", "drain", "capture", "validation", "promotion", "completion"}
RECOVERY_DIAGNOSTIC_OPERATIONS = {
    "recovery_root_validation", "connection_configuration", "job_schema", "recovery_tables",
    "schema_validation",
    "maintenance_epoch_creation", "maintenance_epoch_validation", "worker_quiescence",
    "capture_state_write", "staging_directory", "wal_checkpoint", "capture_transaction_begin",
    "online_backup_destination_connection", "online_backup_source_connection", "online_backup_execution",
    "backup_completion", "database_integrity_check", "foreign_key_check", "job_event_bound_read",
    "job_count_read", "report_count_read", "version_count_read", "artifact_count_read",
    "recovery_event_bound_read", "artifact_registration_inventory_read", "artifact_copy",
    "artifact_stability_check", "manifest_database_reads", "manifest_write", "bundle_validation",
    "recovery_evidence_persistence",
    "bundle_promotion", "completion_event_write", "completion_transaction_commit",
    "failure_event_write", "failure_transaction_commit", "capture_transaction_rollback",
}
RECOVERY_DIAGNOSTIC_CHECKPOINTS = {"starting", "waiting", "progress", "creating", "completed", "failed"}
NATIVE_CAPTURE_CHECKPOINTS = {
    "before_snapshot_creation", "during_snapshot_creation",
    "after_snapshot_before_database_digest", "during_sqlite_integrity_validation",
    "during_sqlite_foreign_key_validation", "after_current_evidence_before_manifest",
    "during_canonical_manifest_creation", "after_manifest_before_bundle_validation",
    "after_bundle_validation_before_live_evidence", "after_evidence_row_before_event",
    "after_evidence_event_before_completion", "during_final_staging_cleanup",
}


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


class CaptureFaultInjector:
    """Private deterministic test hook; production callers leave this unset."""

    def __init__(self, fail_at: str | None = None) -> None:
        self.fail_at = fail_at
        self.entered: list[str] = []
        self.triggered_failure: str | None = None

    def checkpoint(self, name: str) -> None:
        if name not in NATIVE_CAPTURE_CHECKPOINTS:
            raise ValueError("native_capture_checkpoint_invalid")
        self.entered.append(name)
        if self.fail_at == name:
            self.triggered_failure = name
            raise ValueError("native_capture_fault_injected")


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
        with os.scandir(current) as entries:
            for entry in entries:
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
    ensure_recovery_evidence_tables(conn)


def ensure_recovery_evidence_tables(conn: sqlite3.Connection) -> None:
    """Initialize the immutable recovery-evidence authority without side effects."""
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS stage77_recovery_point_evidence (
      id TEXT PRIMARY KEY,
      recovery_point_id TEXT NOT NULL UNIQUE,
      recovery_contract TEXT NOT NULL,
      maintenance_epoch INTEGER NOT NULL,
      manifest_digest TEXT NOT NULL,
      database_digest TEXT NOT NULL,
      diagnostic_count INTEGER NOT NULL,
      diagnostic_state_digest TEXT NOT NULL,
      retry_link_count INTEGER NOT NULL,
      retry_topology_digest TEXT NOT NULL,
      report_count INTEGER NOT NULL,
      version_count INTEGER NOT NULL,
      report_event_bound_status TEXT NOT NULL,
      report_event_bound INTEGER,
      qualification_count INTEGER NOT NULL,
      qualification_event_bound INTEGER NOT NULL,
      job_count INTEGER NOT NULL,
      job_event_bound INTEGER NOT NULL,
      artifact_count INTEGER NOT NULL,
      recovery_event_bound INTEGER NOT NULL,
      sqlite_integrity TEXT NOT NULL,
      foreign_key_violation_count INTEGER NOT NULL,
      evidence_payload_json TEXT NOT NULL,
      evidence_digest TEXT NOT NULL UNIQUE,
      evidence_source_mode TEXT NOT NULL,
      evidence_contract TEXT NOT NULL,
      state TEXT NOT NULL CHECK(state='finalized'),
      actor TEXT NOT NULL,
      rationale TEXT NOT NULL,
      declaration_json TEXT NOT NULL,
      idempotency_key TEXT NOT NULL UNIQUE,
      canonical_bundle_identity TEXT NOT NULL,
      created_at TEXT NOT NULL,
      CHECK(evidence_contract='stage77.recovery_point_evidence.v1'),
      CHECK(evidence_source_mode IN ('native_capture','historical_reconstruction'))
    );
    CREATE TABLE IF NOT EXISTS stage77_recovery_point_evidence_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      evidence_id TEXT NOT NULL,
      event_type TEXT NOT NULL,
      actor TEXT NOT NULL,
      occurred_at TEXT NOT NULL,
      payload_json TEXT NOT NULL,
      FOREIGN KEY(evidence_id) REFERENCES stage77_recovery_point_evidence(id)
    );
    CREATE UNIQUE INDEX IF NOT EXISTS idx_stage77_recovery_evidence_point
      ON stage77_recovery_point_evidence(recovery_point_id);
    CREATE UNIQUE INDEX IF NOT EXISTS idx_stage77_recovery_evidence_idempotency
      ON stage77_recovery_point_evidence(idempotency_key);
    CREATE INDEX IF NOT EXISTS idx_stage77_recovery_evidence_events
      ON stage77_recovery_point_evidence_events(evidence_id,id);
    CREATE TRIGGER IF NOT EXISTS stage77_recovery_evidence_no_update
      BEFORE UPDATE ON stage77_recovery_point_evidence
      BEGIN SELECT RAISE(ABORT, 'recovery_evidence_immutable'); END;
    CREATE TRIGGER IF NOT EXISTS stage77_recovery_evidence_no_delete
      BEFORE DELETE ON stage77_recovery_point_evidence
      BEGIN SELECT RAISE(ABORT, 'recovery_evidence_immutable'); END;
    CREATE TRIGGER IF NOT EXISTS stage77_recovery_evidence_events_no_update
      BEFORE UPDATE ON stage77_recovery_point_evidence_events
      BEGIN SELECT RAISE(ABORT, 'recovery_evidence_event_immutable'); END;
    CREATE TRIGGER IF NOT EXISTS stage77_recovery_evidence_events_no_delete
      BEFORE DELETE ON stage77_recovery_point_evidence_events
      BEGIN SELECT RAISE(ABORT, 'recovery_evidence_event_immutable'); END;
    """)


def _recovery_evidence_payload(manifest: Mapping[str, Any], *, source_mode: str,
                               actor: str, rationale: str, declaration: Mapping[str, Any],
                               idempotency_key: str, created_at: str,
                               report_event_bound: int | None = None,
                               contract_name: str | None = None) -> dict[str, Any]:
    """Project already-validated bundle evidence into the durable evidence contract."""
    contract = contract_name or _manifest_contract(manifest)
    if contract not in {"legacy", "current", "diagnostic_aware", "post_correction_aware"}:
        raise ValueError("recovery_evidence_contract_invalid")
    counts = manifest.get("counts")
    if not isinstance(counts, ABCMapping):
        raise ValueError("recovery_evidence_manifest_invalid")
    integrity = manifest.get("integrity")
    if integrity != {"integrity_check": "ok", "foreign_key_check": "ok"}:
        raise ValueError("recovery_evidence_integrity_invalid")
    if contract == "post_correction_aware":
        if isinstance(report_event_bound, bool) or not isinstance(report_event_bound, int) or report_event_bound < 0:
            raise ValueError("recovery_evidence_report_event_bound_invalid")
        report_event_binding = {"report_event_bound_status": "bound", "report_event_bound": report_event_bound}
    else:
        if report_event_bound is not None:
            raise ValueError("recovery_evidence_report_event_bound_invalid")
        report_event_binding = {"report_event_bound_status": "not_bound_by_source_contract", "report_event_bound": None}
    payload = {
        "evidence_contract": RECOVERY_EVIDENCE_CONTRACT,
        "evidence_source_mode": source_mode,
        "recovery_point_id": str(manifest["recovery_point_id"]),
        "recovery_contract": {"legacy": "stage77.recovery.v1", "current": "stage77.recovery.v1", "diagnostic_aware": "stage77.diagnostic_aware.v1", "post_correction_aware": "stage77.post_correction_aware.v1"}[contract],
        "maintenance_epoch": int(manifest["maintenance_epoch"]),
        "database_digest": str(manifest["database"]["sha256"]),
        "diagnostic_count": int(manifest.get("diagnostic_evidence_count", 0)),
        "diagnostic_state_digest": str(manifest.get("diagnostic_evidence_state_digest", digest_bytes(b"[]"))),
        "retry_link_count": int(manifest.get("retry_link_count", 0)),
        "retry_topology_digest": str(manifest.get("retry_link_state_digest", digest_bytes(b"[]"))),
        "report_count": int(counts["reports"]), "version_count": int(counts["versions"]),
        "qualification_count": int(counts.get("qualifications", 0)),
        "qualification_event_bound": int(manifest.get("qualification_event_bound", 0)),
        "job_count": int(counts["jobs"]), "job_event_bound": int(manifest["job_event_bound"]),
        "artifact_count": int(counts["artifacts"]),
        "recovery_event_bound": int(manifest["recovery_event_bound"]),
        "sqlite_integrity": str(integrity["integrity_check"]),
        "foreign_key_violation_count": 0,
        "evidence_contract_version": RECOVERY_EVIDENCE_CONTRACT,
    }
    payload.update(report_event_binding)
    return payload


def _validate_report_event_binding(payload: Mapping[str, Any], *, require_bound: bool = False) -> None:
    status = payload.get("report_event_bound_status")
    value = payload.get("report_event_bound")
    if status not in REPORT_EVENT_BOUND_STATUSES:
        raise ValueError("recovery_evidence_report_event_bound_invalid")
    if status == "bound":
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError("recovery_evidence_report_event_bound_invalid")
    elif value is not None:
        raise ValueError("recovery_evidence_report_event_bound_invalid")
    if require_bound and status != "bound":
        raise ValueError("recovery_evidence_report_event_bound_unavailable")


def _insert_recovery_evidence(conn: sqlite3.Connection, manifest: Mapping[str, Any], *,
                              source_mode: str, actor: str, rationale: str,
                              declaration: Mapping[str, Any], idempotency_key: str,
                              created_at: str, final_manifest_digest: str | None = None,
                              fault_injector: CaptureFaultInjector | None = None) -> dict[str, Any]:
    if source_mode == "native_capture":
        payload = dict(manifest.get("current_recovery_manifest_evidence") or {})
        if payload:
            if manifest.get("current_recovery_manifest_evidence_digest") != digest_bytes(canonical_json(payload).encode("utf-8")):
                raise ValueError("recovery_evidence_manifest_invalid")
        else:
            payload = _recovery_evidence_payload(manifest, source_mode=source_mode, actor=actor,
                                                 rationale=rationale, declaration=declaration,
                                                 idempotency_key=idempotency_key, created_at=created_at)
    else:
        report_event_bound = None
        captured = manifest.get("current_recovery_manifest_evidence")
        if isinstance(captured, ABCMapping) and captured.get("recovery_contract") == "stage77.post_correction_aware.v1" and captured.get("report_event_bound_status") == "bound":
            report_event_bound = captured.get("report_event_bound")
        payload = _recovery_evidence_payload(manifest, source_mode=source_mode, actor=actor,
                                             rationale=rationale, declaration=declaration,
                                             idempotency_key=idempotency_key, created_at=created_at,
                                             report_event_bound=report_event_bound)
    digest = digest_bytes(canonical_json(payload).encode("utf-8"))
    _validate_report_event_binding(payload, require_bound=payload.get("recovery_contract") == "stage77.post_correction_aware.v1")
    existing = conn.execute("SELECT * FROM stage77_recovery_point_evidence WHERE recovery_point_id=?", (payload["recovery_point_id"],)).fetchone()
    if existing:
        if str(existing["evidence_digest"]) != digest or str(existing["idempotency_key"]) != str(idempotency_key):
            raise ValueError("recovery_evidence_conflict")
        return dict(existing)
    evidence_id = secrets.token_hex(16)
    conn.execute("""INSERT INTO stage77_recovery_point_evidence
      (id,recovery_point_id,recovery_contract,maintenance_epoch,manifest_digest,database_digest,
       diagnostic_count,diagnostic_state_digest,retry_link_count,retry_topology_digest,
       report_count,version_count,report_event_bound_status,report_event_bound,qualification_count,qualification_event_bound,
       job_count,job_event_bound,artifact_count,recovery_event_bound,sqlite_integrity,
       foreign_key_violation_count,evidence_payload_json,evidence_digest,evidence_source_mode,
       evidence_contract,state,actor,rationale,declaration_json,idempotency_key,canonical_bundle_identity,created_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
      (evidence_id, payload["recovery_point_id"], payload["recovery_contract"], payload["maintenance_epoch"],
       final_manifest_digest or str(manifest.get("_manifest_digest") or ""), payload["database_digest"], payload["diagnostic_count"],
       payload["diagnostic_state_digest"], payload["retry_link_count"], payload["retry_topology_digest"],
       payload["report_count"], payload["version_count"], payload["report_event_bound_status"], payload["report_event_bound"],
       payload["qualification_count"], payload["qualification_event_bound"], payload["job_count"],
       payload["job_event_bound"], payload["artifact_count"], payload["recovery_event_bound"],
       payload["sqlite_integrity"], payload["foreign_key_violation_count"], canonical_json(payload), digest,
       source_mode, RECOVERY_EVIDENCE_CONTRACT, "finalized", actor, rationale,
       canonical_json(dict(declaration)), idempotency_key, str(payload["recovery_point_id"]), created_at))
    if fault_injector is not None:
        fault_injector.checkpoint("after_evidence_row_before_event")
    conn.execute("INSERT INTO stage77_recovery_point_evidence_events(evidence_id,event_type,actor,occurred_at,payload_json) VALUES(?,?,?,?,?)",
                 (evidence_id, "recovery_evidence_finalized", actor, created_at, canonical_json(payload)))
    return {"id": evidence_id, "evidence_digest": digest, "payload": payload, "state": "finalized"}


def recovery_evidence_for_point(conn: sqlite3.Connection, recovery_point_id: str) -> dict[str, Any]:
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='stage77_recovery_point_evidence'").fetchone() is None:
        raise ValueError("recovery_evidence_required")
    rows = conn.execute("SELECT * FROM stage77_recovery_point_evidence WHERE recovery_point_id=? ORDER BY id", (str(recovery_point_id),)).fetchall()
    if len(rows) != 1:
        raise ValueError("recovery_evidence_required")
    row = dict(rows[0])
    payload = _strict_json_object(row["evidence_payload_json"], "recovery_evidence_invalid")
    if digest_bytes(canonical_json(payload).encode("utf-8")) != row["evidence_digest"] or row["state"] != "finalized":
        raise ValueError("recovery_evidence_invalid")
    if payload.get("recovery_point_id") != str(recovery_point_id) or payload.get("evidence_contract") != RECOVERY_EVIDENCE_CONTRACT:
        raise ValueError("recovery_evidence_invalid")
    _validate_report_event_binding(payload, require_bound=payload.get("recovery_contract") == "stage77.post_correction_aware.v1")
    if row.get("report_event_bound_status") != payload["report_event_bound_status"] or row.get("report_event_bound") != payload["report_event_bound"]:
        raise ValueError("recovery_evidence_invalid")
    events = conn.execute("SELECT event_type,payload_json FROM stage77_recovery_point_evidence_events WHERE evidence_id=? ORDER BY id", (row["id"],)).fetchall()
    if len(events) != 1 or events[0]["event_type"] != "recovery_evidence_finalized":
        raise ValueError("recovery_evidence_event_invalid")
    event_payload = _strict_json_object(events[0]["payload_json"], "recovery_evidence_event_invalid")
    if event_payload != payload:
        raise ValueError("recovery_evidence_event_invalid")
    return row | {"payload": payload}


def _recovery_evidence_snapshot(conn: sqlite3.Connection) -> tuple[list[dict[str, Any]], str, int]:
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='stage77_recovery_point_evidence'").fetchone() is None:
        raise ValueError("recovery_evidence_required")
    rows = conn.execute("SELECT id,recovery_point_id,evidence_digest,state,evidence_payload_json FROM stage77_recovery_point_evidence ORDER BY id").fetchall()
    snapshot = []
    for row in rows:
        payload = _strict_json_object(row["evidence_payload_json"], "recovery_evidence_invalid")
        if row["state"] != "finalized" or digest_bytes(canonical_json(payload).encode("utf-8")) != str(row["evidence_digest"]):
            raise ValueError("recovery_evidence_invalid")
        _validate_report_event_binding(payload, require_bound=payload.get("recovery_contract") == "stage77.post_correction_aware.v1")
        snapshot.append({"evidence_id": str(row["id"]), "recovery_point_id": str(row["recovery_point_id"]), "evidence_digest": str(row["evidence_digest"]), "state": str(row["state"]), "payload": payload})
    event_bound = int(conn.execute("SELECT COALESCE(MAX(id),0) FROM stage77_recovery_point_evidence_events").fetchone()[0])
    digest = digest_bytes(canonical_json(snapshot).encode("utf-8"))
    return snapshot, digest, event_bound


def _validate_capture_schema(conn: sqlite3.Connection) -> None:
    required = {
        "record_governed_reports": {"id": "INTEGER"},
        "record_governed_report_versions": {"id": "INTEGER", "report_id": "INTEGER"},
        "record_governed_report_artifacts": {"id": "INTEGER", "version_id": "INTEGER", "format": "TEXT", "storage_reference": "TEXT", "sha256": "TEXT", "size_bytes": "INTEGER", "validation_state": "TEXT"},
        "stage77_report_jobs": {"id": "INTEGER", "state": "TEXT", "maintenance_epoch": "INTEGER"},
        "stage77_report_job_events": {"id": "INTEGER", "job_id": "INTEGER"},
        "stage77_recovery_control": {"singleton": "INTEGER", "operation_id": "TEXT", "maintenance_epoch": "INTEGER", "state": "TEXT"},
        "stage77_recovery_events": {"id": "INTEGER", "operation_id": "TEXT"},
    }
    for table, expected_columns in required.items():
        rows = conn.execute("PRAGMA table_info(%s)" % table).fetchall()
        columns = {str(row[1]): str(row[2]).upper() for row in rows}
        if not rows or any(columns.get(name) != expected_type for name, expected_type in expected_columns.items()):
            raise ValueError("schema_incompatible")
    from api import governed_report_qualifications as qualifications
    try:
        qualifications.validate_qualification_tables(conn)
    except ValueError:
        raise ValueError("schema_incompatible") from None


def _validate_post_correction_recovery_eligibility(conn: sqlite3.Connection, *, report_count: int, version_count: int) -> None:
    """Require the governed Report 1/version target before post recovery evidence."""
    if report_count != 1 or version_count != 1:
        raise ValueError("recovery_state_ineligible")
    report = conn.execute("SELECT id,lifecycle_status FROM record_governed_reports ORDER BY id").fetchone()
    version_columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(record_governed_report_versions)").fetchall()}
    required = {"report_id", "lifecycle_status", "specification_json", "specification_digest"}
    if not required.issubset(version_columns):
        raise ValueError("schema_incompatible")
    version_fields = ["report_id"]
    if "version_number" in version_columns:
        version_fields.append("version_number")
    version_fields.extend(("lifecycle_status", "specification_json", "specification_digest"))
    version = conn.execute("SELECT " + ",".join(version_fields) + " FROM record_governed_report_versions ORDER BY id").fetchone()
    if report is None or version is None or int(version[0]) != int(report[0]):
        raise ValueError("recovery_state_ineligible")
    version_number = version[1] if "version_number" in version_columns else None
    lifecycle_index = 2 if version_number is not None else 1
    if str(report[1]) not in {"generated", "validation_failed"} or str(version[lifecycle_index]) != str(report[1]):
        raise ValueError("report_lifecycle_invalid")
    if version_number is not None and int(version_number) != 1:
        raise ValueError("version_count_mismatch")
    specification_index = lifecycle_index + 1
    digest_index = specification_index + 1
    try:
        specification = _strict_payload(str(version[specification_index]))
        if not isinstance(specification, ABCMapping) or canonical_json(specification) != str(version[specification_index]):
            raise ValueError
        expected_digest = digest_bytes(canonical_json(specification).encode("utf-8"))
    except (TypeError, ValueError, json.JSONDecodeError):
        raise ValueError("specification_digest_mismatch") from None
    if expected_digest != str(version[digest_index]):
        raise ValueError("specification_digest_mismatch")


def _validate_archived_job_runtime_metadata(conn: sqlite3.Connection, *, contract: str) -> None:
    """Validate only runtime fields actually bound by the archived job schema."""
    if contract not in {"legacy", "current", "diagnostic_aware", "post_correction_aware"}:
        raise ValueError("schema_incompatible")
    columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(stage77_report_jobs)").fetchall()}
    attempt_fields = {"attempt_count", "max_attempts"}
    lease_fields = {"lease_owner", "lease_token", "lease_acquired_at", "lease_expires_at", "heartbeat_at"}
    if attempt_fields & columns and not attempt_fields <= columns:
        raise ValueError("schema_incompatible")
    if lease_fields & columns and not lease_fields <= columns:
        raise ValueError("schema_incompatible")
    if not attempt_fields <= columns:
        return
    epoch_bound = "maintenance_epoch" in columns
    control = None
    if epoch_bound and conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='stage77_recovery_control'").fetchone():
        control = conn.execute("SELECT state,maintenance_epoch FROM stage77_recovery_control WHERE singleton=1").fetchone()
    if not epoch_bound and control is not None:
        return
    select_fields = ["id", "state", "attempt_count", "max_attempts"]
    if lease_fields <= columns:
        select_fields.extend(sorted(lease_fields))
    if epoch_bound:
        select_fields.append("maintenance_epoch")
    for row in conn.execute("SELECT " + ",".join(select_fields) + " FROM stage77_report_jobs ORDER BY id").fetchall():
        attempt_count = row["attempt_count"]
        max_attempts = row["max_attempts"]
        if isinstance(attempt_count, bool) or not isinstance(attempt_count, int) or attempt_count < 0:
            raise ValueError("job_attempt_metadata_invalid")
        if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or max_attempts <= 0 or attempt_count > max_attempts:
            raise ValueError("job_attempt_metadata_invalid")
        state = str(row["state"])
        if state in {"leased", "running", "retry_wait", "cancel_requested", "succeeded", "failed_terminal", "cancelled"} and attempt_count < 1:
            raise ValueError("job_attempt_metadata_invalid")
        if lease_fields <= columns:
            lease = {name: row[name] for name in lease_fields}
            present = {name for name, value in lease.items() if value is not None and str(value) != ""}
            active = state in {"leased", "running"}
            if active and present != lease_fields:
                raise ValueError("job_lease_metadata_invalid")
            if not active and present and present != lease_fields:
                raise ValueError("job_lease_metadata_invalid")
            if present == lease_fields:
                try:
                    acquired = datetime.fromisoformat(str(lease["lease_acquired_at"]).replace("Z", "+00:00"))
                    expires = datetime.fromisoformat(str(lease["lease_expires_at"]).replace("Z", "+00:00"))
                    heartbeat = datetime.fromisoformat(str(lease["heartbeat_at"]).replace("Z", "+00:00"))
                except (TypeError, ValueError, OverflowError):
                    raise ValueError("job_lease_metadata_invalid") from None
                if expires <= acquired or heartbeat < acquired or (active and heartbeat >= expires):
                    raise ValueError("job_lease_metadata_invalid")
        if epoch_bound:
            epoch = row["maintenance_epoch"]
            if isinstance(epoch, bool) or not isinstance(epoch, int) or epoch < 0:
                raise ValueError("job_maintenance_epoch_mismatch")
            if control is not None and epoch and int(epoch) != int(control["maintenance_epoch"]):
                raise ValueError("job_maintenance_epoch_mismatch")


def _validate_archived_job_cancellation(conn: sqlite3.Connection, *, contract: str) -> None:
    """Validate only cancellation evidence bound by the archived job schema."""
    if contract not in {"current", "diagnostic_aware", "post_correction_aware"}:
        return
    columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(stage77_report_jobs)").fetchall()}
    if "cancellation_requested_at" not in columns:
        return
    event_table = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='stage77_report_job_events'").fetchone()
    if event_table is None:
        raise ValueError("schema_incompatible")
    rows = conn.execute("SELECT id,state,cancellation_requested_at,terminal_at,terminal_outcome FROM stage77_report_jobs ORDER BY id").fetchall()
    for row in rows:
        state = str(row["state"])
        requested = row["cancellation_requested_at"]
        events = conn.execute(
            "SELECT resulting_state,occurred_at FROM stage77_report_job_events WHERE job_id=? AND event_type='cancel_requested' ORDER BY id",
            (int(row["id"]),),
        ).fetchall()
        if requested is not None and not str(requested).strip():
            raise ValueError("job_cancellation_evidence_invalid")
        if requested is None and events:
            raise ValueError("job_cancellation_evidence_invalid")
        if state in {"cancel_requested", "cancelled"}:
            if requested is None or len(events) != 1 or str(events[0]["resulting_state"]) not in {"cancel_requested", "cancelled"}:
                raise ValueError("job_cancellation_evidence_invalid")
            try:
                requested_at = datetime.fromisoformat(str(requested).replace("Z", "+00:00"))
                event_at = datetime.fromisoformat(str(events[0]["occurred_at"]).replace("Z", "+00:00"))
                terminal_at = None if row["terminal_at"] is None else datetime.fromisoformat(str(row["terminal_at"]).replace("Z", "+00:00"))
            except (TypeError, ValueError, OverflowError):
                raise ValueError("job_cancellation_evidence_invalid") from None
            if event_at < requested_at or (terminal_at is not None and terminal_at < requested_at):
                raise ValueError("job_cancellation_evidence_invalid")
            if state == "cancel_requested" and terminal_at is not None:
                raise ValueError("job_cancellation_evidence_invalid")
            if state == "cancelled" and row["terminal_outcome"] not in {None, "cancelled"}:
                raise ValueError("job_cancellation_evidence_invalid")
        elif requested is not None or events:
            raise ValueError("job_cancellation_evidence_invalid")


def _validate_archived_job_terminal_evidence(conn: sqlite3.Connection, *, contract: str) -> None:
    """Validate failed/succeeded terminal metadata without changing cancellation rules."""
    if contract not in {"current", "diagnostic_aware", "post_correction_aware"}:
        return
    columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(stage77_report_jobs)").fetchall()}
    terminal_fields = {"terminal_at", "terminal_outcome", "failure_phase", "failure_code"}
    present = columns & terminal_fields
    if not present:
        return
    if present != terminal_fields:
        raise ValueError("schema_incompatible")
    event_table = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='stage77_report_job_events'").fetchone()
    if event_table is None:
        raise ValueError("schema_incompatible")
    for row in conn.execute("SELECT id,state,terminal_at,terminal_outcome,failure_phase,failure_code FROM stage77_report_jobs ORDER BY id").fetchall():
        state = str(row["state"])
        if state == "cancelled":
            continue
        events = conn.execute(
            "SELECT resulting_state,occurred_at,payload_json FROM stage77_report_job_events WHERE job_id=? AND event_type='terminal' ORDER BY id",
            (int(row["id"]),),
        ).fetchall()
        if row["terminal_at"] is None and row["terminal_outcome"] is None:
            # Older diagnostic archives may retain only the terminal event.
            continue
        if state in {"failed_terminal", "succeeded"}:
            if row["terminal_at"] is None or row["terminal_outcome"] is None or len(events) != 1:
                raise ValueError("job_terminal_evidence_invalid")
            try:
                terminal_at = datetime.fromisoformat(str(row["terminal_at"]).replace("Z", "+00:00"))
                event_at = datetime.fromisoformat(str(events[0]["occurred_at"]).replace("Z", "+00:00"))
                payload = json.loads(events[0]["payload_json"])
            except (TypeError, ValueError, OverflowError, json.JSONDecodeError):
                raise ValueError("job_terminal_evidence_invalid") from None
            if event_at < terminal_at or events[0]["resulting_state"] != state or not isinstance(payload, Mapping):
                raise ValueError("job_terminal_evidence_invalid")
            if state == "failed_terminal" and (not row["failure_phase"] or not row["failure_code"] or payload.get("phase") != row["failure_phase"] or payload.get("code") != row["failure_code"]):
                raise ValueError("job_terminal_evidence_invalid")
            if state == "succeeded" and (payload.get("code") != row["failure_code"] or (row["failure_phase"] is not None and payload.get("phase") != row["failure_phase"])):
                raise ValueError("job_terminal_evidence_invalid")
        elif events or row["terminal_at"] is not None or row["terminal_outcome"] is not None or row["failure_phase"] is not None or row["failure_code"] is not None:
            raise ValueError("job_terminal_evidence_invalid")


def _validate_archived_job_generation_configuration(conn: sqlite3.Connection, *, contract: str) -> None:
    """Bind archived job configuration to its immutable report-version snapshot."""
    if contract not in {"legacy", "current", "diagnostic_aware", "post_correction_aware"}:
        raise ValueError("schema_incompatible")
    job_columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(stage77_report_jobs)").fetchall()}
    bound_fields = {
        "specification_digest", "requested_formats_json", "rendering_profile",
        "template_version", "publication_engine_version",
    }
    present = job_columns & bound_fields
    if not present:
        return
    if present != bound_fields:
        raise ValueError("schema_incompatible")
    rows = conn.execute(
        "SELECT report_version_id,specification_digest,requested_formats_json,rendering_profile,"
        "template_version,publication_engine_version FROM stage77_report_jobs ORDER BY id"
    ).fetchall()
    if not rows:
        return
    version_columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(record_governed_report_versions)").fetchall()}
    version_configuration_fields = {
        "requested_formats_json", "rendering_profile", "template_version",
        "publication_engine_version",
    }
    present_version = version_columns & version_configuration_fields
    if not present_version:
        return
    if present_version != version_configuration_fields or "specification_digest" not in version_columns:
        raise ValueError("schema_incompatible")
    placeholders = ",".join("?" for _ in rows)
    versions = conn.execute(
        "SELECT id,specification_digest,requested_formats_json,rendering_profile,template_version,"
        "publication_engine_version FROM record_governed_report_versions WHERE id IN (" + placeholders + ")",
        [int(row[0]) for row in rows],
    ).fetchall()
    by_id = {int(row[0]): row for row in versions}
    for job in rows:
        version = by_id.get(int(job[0]))
        if version is None or str(job[1]) != str(version[1]):
            raise ValueError("job_specification_binding_mismatch")
        try:
            job_formats = json.loads(str(job[2]))
            version_formats = json.loads(str(version[2]))
        except (TypeError, ValueError, json.JSONDecodeError):
            raise ValueError("job_rendering_binding_mismatch") from None
        if (not isinstance(job_formats, list) or not isinstance(version_formats, list)
                or any(not isinstance(item, str) for item in job_formats + version_formats)
                or not job_formats or len(job_formats) != len(set(job_formats))
                or any(item not in reports.OUTPUT_FORMATS for item in job_formats)
                or job_formats != version_formats
                or str(job[2]) != canonical_json(job_formats)
                or str(version[2]) != canonical_json(version_formats)):
            raise ValueError("job_rendering_binding_mismatch")
        if any(str(job[index]) != str(version[index]) for index in (3, 4, 5)):
            raise ValueError("job_rendering_binding_mismatch")


def _validate_archived_job_qualification_binding(conn: sqlite3.Connection, *, contract: str) -> None:
    """Bind persisted job qualification snapshots to the finalized chain."""
    if contract not in {"current", "diagnostic_aware", "post_correction_aware"}:
        return
    columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(stage77_report_jobs)").fetchall()}
    qualification_fields = {"qualification_id", "qualification_digest"}
    present = columns & qualification_fields
    if not present:
        return
    if present != qualification_fields:
        raise ValueError("schema_incompatible")
    rows = conn.execute("SELECT id,report_id,report_version_id,qualification_id,qualification_digest FROM stage77_report_jobs ORDER BY id").fetchall()
    if not rows or all(row[3] is None and row[4] is None for row in rows):
        return
    from api import governed_report_qualifications as qualification_store
    for row in rows:
        if row[3] is None or row[4] is None:
            raise ValueError("job_qualification_binding_mismatch")
        qualification = conn.execute(
            "SELECT id,report_id,report_version_id,qualification_digest FROM record_governed_report_qualifications WHERE id=?",
            (int(row[3]),),
        ).fetchone()
        if (qualification is None or int(qualification["report_id"]) != int(row[1])
                or int(qualification["report_version_id"]) != int(row[2])
                or str(qualification["qualification_digest"]) != str(row[4])):
            raise ValueError("job_qualification_binding_mismatch")
        try:
            qualification_store.validate_complete_chain(conn, int(row[2]))
        except (TypeError, ValueError, sqlite3.Error):
            raise ValueError("job_qualification_binding_mismatch") from None


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
    control = _control(conn)
    state = status.get("state")
    if not isinstance(state, str) or state not in RECOVERY_STATES | {"inactive"}:
        return False
    raw_epoch = status.get("maintenance_epoch")
    if isinstance(raw_epoch, bool) or not isinstance(raw_epoch, int) or raw_epoch < 0:
        return False
    maintenance_epoch = raw_epoch
    if control is None:
        if state != "inactive" or maintenance_epoch != 0:
            return False
    elif state == "inactive" or maintenance_epoch <= 0:
        return False
    if control is not None and not {"restore_validation_required", "worker_drained"}.issubset(status):
        return False
    if state in ACTIVE_STATES or bool(status.get("restore_validation_required")):
        return False
    if state in {"failed", "restore_failed"} and not bool(status.get("worker_drained")):
        return False
    if state == "restore_ready" and not status.get("manifest_digest"):
        return False
    if control is not None and conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='stage77_report_jobs'").fetchone() is not None:
        maximum_epoch = conn.execute("SELECT COALESCE(MAX(maintenance_epoch),0) FROM stage77_report_jobs").fetchone()[0]
        if isinstance(maximum_epoch, bool) or not isinstance(maximum_epoch, int) or maximum_epoch < 0:
            return False
        if maximum_epoch > maintenance_epoch:
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


def _strict_payload(raw: str) -> Any:
    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("diagnostic_evidence_invalid")
            result[key] = value
        return result
    try:
        return json.loads(raw, object_pairs_hook=reject_duplicate_keys)
    except (TypeError, ValueError, json.JSONDecodeError):
        raise ValueError("diagnostic_evidence_invalid") from None


def _retry_topology_snapshot(conn: sqlite3.Connection) -> tuple[list[dict[str, Any]], str]:
    columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(stage77_report_jobs)").fetchall()}
    if "retry_of_job_id" not in columns:
        return [], digest_bytes(canonical_json([]).encode("utf-8"))
    rows = conn.execute(
        "SELECT id,retry_of_job_id,report_id,report_version_id,state,governed_action "
        "FROM stage77_report_jobs WHERE retry_of_job_id IS NOT NULL ORDER BY id"
    ).fetchall()
    jobs = {
        int(row["id"]): row
        for row in conn.execute("SELECT id,report_id,report_version_id,state,governed_action,retry_of_job_id FROM stage77_report_jobs")
    }
    inventory = []
    for row in rows:
        predecessor = jobs.get(int(row["retry_of_job_id"]))
        if predecessor is None:
            raise ValueError("retry_topology_invalid")
        if predecessor["retry_of_job_id"] is not None:
            raise ValueError("retry_topology_invalid")
        if predecessor["state"] != "failed_terminal" or predecessor["governed_action"] != "enqueue_generation":
            raise ValueError("retry_topology_invalid")
        if row["governed_action"] != "authorize_diagnostic_retry":
            raise ValueError("retry_topology_invalid")
        if int(predecessor["report_id"]) != int(row["report_id"]) or int(predecessor["report_version_id"]) != int(row["report_version_id"]):
            raise ValueError("retry_topology_invalid")
        inventory.append({
            "predecessor_job_id": int(predecessor["id"]),
            "successor_job_id": int(row["id"]),
            "predecessor_retry_of_job_id": predecessor["retry_of_job_id"],
            "successor_retry_of_job_id": int(row["retry_of_job_id"]),
            "report_id": int(row["report_id"]),
            "report_version_id": int(row["report_version_id"]),
            "predecessor_state": str(predecessor["state"]),
            "successor_state": str(row["state"]),
            "predecessor_governed_action": str(predecessor["governed_action"]),
            "successor_governed_action": str(row["governed_action"]),
        })
    if any(item["predecessor_job_id"] == item["successor_job_id"] for item in inventory):
        raise ValueError("retry_topology_invalid")
    children: dict[int, int] = {}
    for item in inventory:
        predecessor = jobs.get(item["predecessor_job_id"])
        successor = jobs.get(item["successor_job_id"])
        if predecessor is None or successor is None:
            raise ValueError("retry_topology_invalid")
        if item["predecessor_retry_of_job_id"] is not None or item["successor_retry_of_job_id"] != item["predecessor_job_id"]:
            raise ValueError("retry_topology_invalid")
        children[item["predecessor_job_id"]] = children.get(item["predecessor_job_id"], 0) + 1
        if children[item["predecessor_job_id"]] > 1:
            raise ValueError("retry_topology_invalid")
    raw = canonical_json(inventory).encode("utf-8")
    return inventory, digest_bytes(raw)


def _diagnostic_evidence_snapshot(conn: sqlite3.Connection) -> tuple[list[dict[str, Any]], str]:
    """Classify every terminal governed diagnostic pair without copying payloads."""
    attempt_table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='record_governed_report_generation_attempts'"
    ).fetchone()
    if attempt_table is None:
        empty = canonical_json([]).encode("utf-8")
        return [], digest_bytes(empty)
    rows = conn.execute(
        "SELECT id,report_version_id,state,attempt_count,governed_action,retry_of_job_id FROM stage77_report_jobs "
        "WHERE state='failed_terminal' ORDER BY id"
    ).fetchall()
    inventory: list[dict[str, Any]] = []
    for job in rows:
        ownership = conn.execute(
            "SELECT v.report_id FROM record_governed_report_versions v "
            "JOIN stage77_report_jobs j ON j.report_version_id=v.id AND j.report_id=v.report_id "
            "WHERE j.id=?",
            (int(job["id"]),),
        ).fetchone()
        if ownership is None:
            raise ValueError("diagnostic_evidence_invalid")
        expected_action = "authorize_diagnostic_retry" if job["retry_of_job_id"] is not None else "enqueue_generation"
        if job["governed_action"] != expected_action:
            raise ValueError("diagnostic_evidence_invalid")
        terminal_rows = conn.execute(
            "SELECT id,payload_json FROM stage77_report_job_events "
            "WHERE job_id=? AND event_type='terminal' AND resulting_state='failed_terminal' ORDER BY id DESC LIMIT 1",
            (int(job["id"]),),
        ).fetchall()
        if not terminal_rows:
            continue
        terminal_raw = str(terminal_rows[0]["payload_json"])
        terminal_value = _strict_payload(terminal_raw)
        diagnostic_marker = isinstance(terminal_value, Mapping) and (
            "diagnostic" in terminal_value or terminal_value.get("phase") == "rendering"
        )
        attempt = conn.execute(
            "SELECT id,result,diagnostics_json FROM record_governed_report_generation_attempts "
            "WHERE version_id=? AND idempotency_key=? ORDER BY id DESC LIMIT 1",
            (int(job["report_version_id"]), f"stage77-job-{int(job['id'])}"),
        ).fetchone()
        if attempt is None:
            if diagnostic_marker:
                raise ValueError("diagnostic_evidence_invalid")
            continue
        if attempt["result"] != "validation_failed":
            if diagnostic_marker:
                raise ValueError("diagnostic_evidence_invalid")
            continue
        attempt_raw = str(attempt["diagnostics_json"])
        attempt_value = _strict_payload(attempt_raw)
        if not diagnostic_marker and not (
            isinstance(attempt_value, list) and attempt_value and isinstance(attempt_value[0], Mapping)
        ):
            continue
        try:
            selected = diagnostics.select_diagnostic_contract(attempt_raw=attempt_raw, terminal_raw=terminal_raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            raise ValueError("diagnostic_evidence_invalid") from None
        inventory.append({
            "job_id": int(job["id"]),
            "attempt_id": int(attempt["id"]),
            "terminal_event_id": int(terminal_rows[0]["id"]),
            "diagnostic_contract_version": str(selected["contract_id"]),
            "attempt_diagnostic_sha256": str(selected["attempt_sha256"]),
            "terminal_diagnostic_sha256": str(selected["terminal_sha256"]),
        })
    raw = canonical_json(inventory).encode("utf-8")
    return inventory, digest_bytes(raw)


def _database_contract(conn: sqlite3.Connection) -> tuple[str, list[dict[str, Any]], str, list[dict[str, Any]], str]:
    tables = {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    qualification_tables = {"record_governed_report_qualifications", "record_governed_report_qualification_events"}
    evidence, evidence_digest = _diagnostic_evidence_snapshot(conn)
    post_schema = _post_correction_schema_present(conn)
    links, links_digest = _retry_topology_snapshot(conn)
    if not (qualification_tables & tables):
        if post_schema:
            return "post_correction_aware", evidence, evidence_digest, [], digest_bytes(canonical_json([]).encode("utf-8"))
        if evidence:
            raise ValueError("diagnostic_evidence_invalid")
        return "legacy", [], digest_bytes(canonical_json([]).encode("utf-8")), [], digest_bytes(canonical_json([]).encode("utf-8"))
    if post_schema:
        return "post_correction_aware", evidence, evidence_digest, links, links_digest
    if evidence:
        return "diagnostic_aware", evidence, evidence_digest, links, links_digest
    return "current", [], evidence_digest, links, links_digest


def _post_correction_schema_present(conn: sqlite3.Connection) -> bool:
    names = {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    auth_name = "stage77_post_correction_authorizations"
    link_name = "stage77_post_correction_execution_links"
    attestation_name = "stage77_post_correction_custody_attestations"
    event_name = "stage77_post_correction_custody_attestation_events"
    evidence_name = "stage77_recovery_point_evidence"
    evidence_event_name = "stage77_recovery_point_evidence_events"
    if auth_name not in names and link_name not in names and attestation_name not in names and event_name not in names:
        return False
    if {auth_name, link_name, attestation_name, event_name, evidence_name, evidence_event_name} - names:
        raise ValueError("post_correction_schema_incompatible")
    expected_auth = {"id": "TEXT", "report_id": "INTEGER", "report_version_id": "INTEGER", "qualification_id": "INTEGER", "job1_id": "INTEGER", "job2_id": "INTEGER", "state": "TEXT", "idempotency_key": "TEXT", "payload_json": "TEXT", "authorization_digest": "TEXT", "created_at": "TEXT", "consumed_at": "TEXT"}
    expected_link = {"authorization_id": "TEXT", "job_id": "INTEGER", "created_at": "TEXT"}
    expected_attestation = {"id": "TEXT", "report_id": "INTEGER", "report_version_id": "INTEGER", "specification_digest": "TEXT", "recovery_evidence_id": "TEXT", "recovery_evidence_digest": "TEXT", "recovery_point_id": "TEXT", "recovery_contract": "TEXT", "maintenance_epoch": "INTEGER", "manifest_digest": "TEXT", "database_digest": "TEXT", "archive_digest": "TEXT", "receipt_digest": "TEXT", "diagnostic_count": "INTEGER", "diagnostic_state_digest": "TEXT", "retry_link_count": "INTEGER", "retry_topology_digest": "TEXT", "report_count": "INTEGER", "version_count": "INTEGER", "qualification_count": "INTEGER", "job_count": "INTEGER", "artifact_count": "INTEGER", "archive_size_bytes": "INTEGER", "custody_directory_identity": "TEXT", "correction_revision": "TEXT", "correction_deployment": "TEXT", "actor": "TEXT", "rationale": "TEXT", "declaration_json": "TEXT", "contract_version": "TEXT", "idempotency_key": "TEXT", "payload_json": "TEXT", "attestation_digest": "TEXT", "state": "TEXT", "created_at": "TEXT"}
    expected_event = {"id": "INTEGER", "attestation_id": "TEXT", "event_type": "TEXT", "actor": "TEXT", "occurred_at": "TEXT", "payload_json": "TEXT"}
    binding_name = "stage77_post_correction_authorization_custody_bindings"
    expected_binding = {"authorization_id": "TEXT", "custody_attestation_id": "TEXT", "authorization_digest": "TEXT", "created_at": "TEXT"}
    expected_evidence = {"id": "TEXT", "recovery_point_id": "TEXT", "recovery_contract": "TEXT", "maintenance_epoch": "INTEGER", "manifest_digest": "TEXT", "database_digest": "TEXT", "diagnostic_count": "INTEGER", "diagnostic_state_digest": "TEXT", "retry_link_count": "INTEGER", "retry_topology_digest": "TEXT", "report_count": "INTEGER", "version_count": "INTEGER", "report_event_bound_status": "TEXT", "report_event_bound": "INTEGER", "qualification_count": "INTEGER", "qualification_event_bound": "INTEGER", "job_count": "INTEGER", "job_event_bound": "INTEGER", "artifact_count": "INTEGER", "recovery_event_bound": "INTEGER", "sqlite_integrity": "TEXT", "foreign_key_violation_count": "INTEGER", "evidence_payload_json": "TEXT", "evidence_digest": "TEXT", "evidence_source_mode": "TEXT", "evidence_contract": "TEXT", "state": "TEXT", "actor": "TEXT", "rationale": "TEXT", "declaration_json": "TEXT", "idempotency_key": "TEXT", "canonical_bundle_identity": "TEXT", "created_at": "TEXT"}
    expected_evidence_event = {"id": "INTEGER", "evidence_id": "TEXT", "event_type": "TEXT", "actor": "TEXT", "occurred_at": "TEXT", "payload_json": "TEXT"}
    if binding_name not in names:
        raise ValueError("post_correction_schema_incompatible")
    for table, expected in ((auth_name, expected_auth), (link_name, expected_link), (attestation_name, expected_attestation), (event_name, expected_event), (binding_name, expected_binding), (evidence_name, expected_evidence), (evidence_event_name, expected_evidence_event)):
        rows = conn.execute("PRAGMA table_info(%s)" % table).fetchall()
        actual = {str(row[1]): str(row[2]).upper() for row in rows}
        if actual != expected or not rows or int(rows[0][5]) != 1:
            raise ValueError("post_correction_schema_incompatible")
    auth_indexes = {str(row[1]) for row in conn.execute("PRAGMA index_list(%s)" % auth_name).fetchall()}
    link_indexes = {str(row[1]) for row in conn.execute("PRAGMA index_list(%s)" % link_name).fetchall()}
    if not any("idempotency" in name for name in auth_indexes) or not any("report" in name for name in auth_indexes) or not any("job" in name for name in link_indexes):
        raise ValueError("post_correction_schema_incompatible")
    auth_fks = {(str(row[2]), str(row[3]), str(row[4])) for row in conn.execute("PRAGMA foreign_key_list(%s)" % auth_name).fetchall()}
    link_fks = {(str(row[2]), str(row[3]), str(row[4])) for row in conn.execute("PRAGMA foreign_key_list(%s)" % link_name).fetchall()}
    if {("record_governed_reports", "report_id", "id"), ("record_governed_report_versions", "report_version_id", "id"), ("record_governed_report_qualifications", "qualification_id", "id"), ("stage77_report_jobs", "job1_id", "id"), ("stage77_report_jobs", "job2_id", "id")} - auth_fks:
        raise ValueError("post_correction_schema_incompatible")
    if {("stage77_post_correction_authorizations", "authorization_id", "id"), ("stage77_report_jobs", "job_id", "id")} - link_fks:
        raise ValueError("post_correction_schema_incompatible")
    attestation_fks = {(str(row[2]), str(row[3]), str(row[4])) for row in conn.execute("PRAGMA foreign_key_list(%s)" % attestation_name).fetchall()}
    event_fks = {(str(row[2]), str(row[3]), str(row[4])) for row in conn.execute("PRAGMA foreign_key_list(%s)" % event_name).fetchall()}
    binding_fks = {(str(row[2]), str(row[3]), str(row[4])) for row in conn.execute("PRAGMA foreign_key_list(%s)" % binding_name).fetchall()}
    evidence_event_fks = {(str(row[2]), str(row[3]), str(row[4])) for row in conn.execute("PRAGMA foreign_key_list(%s)" % evidence_event_name).fetchall()}
    if {("record_governed_reports", "report_id", "id"), ("record_governed_report_versions", "report_version_id", "id"), (evidence_name, "recovery_evidence_id", "id")} - attestation_fks or (attestation_name, "attestation_id", "id") not in event_fks or {(auth_name, "authorization_id", "id"), (attestation_name, "custody_attestation_id", "id")} - binding_fks or (evidence_name, "evidence_id", "id") not in evidence_event_fks:
        raise ValueError("post_correction_schema_incompatible")
    return True


def _strict_json_object(raw: Any, code: str) -> dict[str, Any]:
    def reject(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(code)
            result[key] = value
        return result
    try:
        value = json.loads(str(raw), object_pairs_hook=reject)
    except (TypeError, ValueError, json.JSONDecodeError):
        raise ValueError(code) from None
    if not isinstance(value, dict) or canonical_json(value) != str(raw):
        raise ValueError(code)
    return value


def _post_correction_snapshot(conn: sqlite3.Connection) -> tuple[list[dict[str, Any]], str, int]:
    _post_correction_schema_present(conn)
    auth_rows = conn.execute("SELECT * FROM stage77_post_correction_authorizations ORDER BY id").fetchall()
    links = conn.execute("SELECT l.authorization_id,l.job_id,l.created_at,j.report_id,j.report_version_id,j.governed_action,j.retry_of_job_id FROM stage77_post_correction_execution_links l JOIN stage77_report_jobs j ON j.id=l.job_id ORDER BY l.authorization_id").fetchall()
    link_by_auth = {str(row["authorization_id"]): dict(row) for row in links}
    snapshot: list[dict[str, Any]] = []
    for row in auth_rows:
        payload = _strict_json_object(row["payload_json"], "post_correction_authorization_invalid")
        expected_payload_keys = {
            "authorization_contract", "report_id", "report_version_id", "specification_digest", "qualification_id", "qualification_digest", "qualification_chain_digest", "review_mode", "disclosure_version", "distribution_restriction", "job1_id", "job1_state", "job1_contract", "job1_stage75_sha256", "job1_stage77_sha256", "job2_id", "job2_state", "job2_contract", "job2_stage75_sha256", "job2_stage77_sha256", "execution_job_id", "retry_topology", "retry_topology_digest", "correction_revision", "correction_deployment", "recovery_evidence_id", "recovery_evidence_digest", "recovery_point_id", "recovery_contract", "recovery_manifest_digest", "recovery_database_digest", "custody_archive_digest", "custody_receipt_digest", "custody_attestation_id", "custody_attestation_digest", "requesting_actor", "rationale", "declaration", "idempotency_key", "created_at", "authorization_digest",
        }
        link = link_by_auth.get(str(row["id"]))
        binding = conn.execute("SELECT custody_attestation_id,authorization_digest FROM stage77_post_correction_authorization_custody_bindings WHERE authorization_id=?", (row["id"],)).fetchone()
        attestation = conn.execute("SELECT id,attestation_digest,state,recovery_evidence_id FROM stage77_post_correction_custody_attestations WHERE id=?", (binding["custody_attestation_id"],)).fetchone() if binding else None
        if set(payload) != expected_payload_keys or payload.get("authorization_contract") != "stage77.post_correction_generation_authorization.v1":
            raise ValueError("post_correction_authorization_invalid")
        for digest_key in ("specification_digest", "qualification_digest", "qualification_chain_digest", "job1_stage75_sha256", "job1_stage77_sha256", "job2_stage75_sha256", "job2_stage77_sha256", "retry_topology_digest", "recovery_manifest_digest", "recovery_database_digest", "custody_archive_digest", "custody_receipt_digest", "authorization_digest"):
            if not isinstance(payload.get(digest_key), str) or not re.fullmatch(r"[0-9a-f]{64}", payload[digest_key]):
                raise ValueError("post_correction_authorization_invalid")
        if (not binding or str(binding["authorization_digest"]) != str(row["authorization_digest"]) or str(binding["custody_attestation_id"]) != str(payload.get("custody_attestation_id")) or attestation is None or str(attestation["recovery_evidence_id"]) != str(payload.get("recovery_evidence_id")) or int(row["qualification_id"]) != int(payload["qualification_id"]) or int(row["job1_id"]) != int(payload["job1_id"]) or int(row["job2_id"]) != int(payload["job2_id"]) or int(row["report_id"]) != int(payload["report_id"]) or int(row["report_version_id"]) != int(payload["report_version_id"]) or payload.get("execution_job_id") in {payload.get("job1_id"), payload.get("job2_id")} or payload.get("review_mode") != "sole_administrator" or payload.get("disclosure_version") != "sole-admin-v1" or payload.get("distribution_restriction") != "internal_working" or payload.get("job1_state") != "failed_terminal" or payload.get("job2_state") != "failed_terminal" or payload.get("retry_topology") != {"successor_job_id": payload.get("job2_id"), "predecessor_job_id": payload.get("job1_id")}):
            raise ValueError("post_correction_authorization_invalid")
        digest = hashlib.sha256(canonical_json({key: value for key, value in payload.items() if key != "authorization_digest"}).encode()).hexdigest()
        if payload.get("authorization_digest") != str(row["authorization_digest"]) or digest != str(row["authorization_digest"]):
            raise ValueError("post_correction_authorization_digest_invalid")
        if attestation is None or attestation["state"] != "finalized" or str(attestation["attestation_digest"]) != str(payload["custody_attestation_digest"]):
            raise ValueError("post_correction_authorization_attestation_invalid")
        if link is None or int(link["job_id"]) != int(payload["execution_job_id"]) or int(link["report_id"]) != int(row["report_id"]) or int(link["report_version_id"]) != int(row["report_version_id"]):
            raise ValueError("post_correction_authorization_link_invalid")
        if link["governed_action"] != "post_correction_generation" or link["retry_of_job_id"] is not None:
            raise ValueError("post_correction_authorization_job_invalid")
        snapshot.append({"authorization_id": str(row["id"]), "custody_attestation_id": str(binding["custody_attestation_id"]), "custody_attestation_digest": str(payload["custody_attestation_digest"]), "recovery_evidence_id": str(payload["recovery_evidence_id"]), "recovery_evidence_digest": str(payload["recovery_evidence_digest"]), "report_id": int(row["report_id"]), "report_version_id": int(row["report_version_id"]), "state": str(row["state"]), "payload": payload, "authorization_digest": str(row["authorization_digest"]), "execution_job_id": int(link["job_id"]), "execution_link_created_at": str(link["created_at"])})
    raw = canonical_json(snapshot).encode("utf-8")
    event_table = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='record_governed_report_events'").fetchone()
    if auth_rows and event_table is None:
        raise ValueError("post_correction_authorization_event_invalid")
    event_bound = int(conn.execute("SELECT COALESCE(MAX(id),0) FROM record_governed_report_events WHERE event_type='post_correction_generation_authorized'").fetchone()[0]) if event_table else 0
    return snapshot, digest_bytes(raw), event_bound


def _post_correction_custody_snapshot(conn: sqlite3.Connection) -> tuple[list[dict[str, Any]], str, int]:
    _post_correction_schema_present(conn)
    rows = conn.execute("SELECT * FROM stage77_post_correction_custody_attestations ORDER BY id").fetchall()
    snapshot = []
    for row in rows:
        payload = _strict_json_object(row["payload_json"], "post_correction_custody_attestation_invalid")
        if payload.get("attestation_contract") != "stage77.post_correction_custody_attestation.v1" or row["state"] != "finalized":
            raise ValueError("post_correction_custody_attestation_invalid")
        if set(payload) != {"attestation_contract", "report_id", "report_version_id", "specification_digest", "recovery_evidence_id", "recovery_evidence_digest", "recovery_point_id", "recovery_contract", "maintenance_epoch", "manifest_digest", "database_digest", "archive_digest", "receipt_digest", "diagnostic_count", "diagnostic_state_digest", "retry_link_count", "retry_topology_digest", "report_count", "version_count", "qualification_count", "job_count", "artifact_count", "archive_size_bytes", "custody_directory_identity", "correction_revision", "correction_deployment", "actor", "rationale", "declaration", "idempotency_key", "created_at"}:
            raise ValueError("post_correction_custody_attestation_invalid")
        digest = digest_bytes(canonical_json(payload).encode("utf-8"))
        if digest != str(row["attestation_digest"]):
            raise ValueError("post_correction_custody_attestation_digest_invalid")
        snapshot.append({"attestation_id": str(row["id"]), "report_id": int(row["report_id"]), "report_version_id": int(row["report_version_id"]), "state": str(row["state"]), "attestation_digest": digest, "payload": payload})
    raw = canonical_json(snapshot).encode("utf-8")
    event_bound = int(conn.execute("SELECT COALESCE(MAX(id),0) FROM stage77_post_correction_custody_attestation_events").fetchone()[0])
    return snapshot, digest_bytes(raw), event_bound


def _manifest_contract(manifest: Mapping[str, Any]) -> str:
    if not isinstance(manifest, ABCMapping):
        raise ValueError("manifest_invalid")
    fields = set(manifest)
    if fields == LEGACY_MANIFEST_KEYS:
        return "legacy"
    if fields == CURRENT_MANIFEST_KEYS:
        return "current"
    if fields == DIAGNOSTIC_MANIFEST_KEYS:
        return "diagnostic_aware"
    if fields == POST_CORRECTION_MANIFEST_KEYS:
        return "post_correction_aware"
    raise ValueError("manifest_invalid")


def _receipt_contract(receipt: Mapping[str, Any]) -> str:
    if not isinstance(receipt, ABCMapping):
        raise ValueError("export_receipt_invalid")
    fields = set(receipt)
    if fields == LEGACY_RECEIPT_KEYS:
        return "legacy"
    if fields == CURRENT_RECEIPT_KEYS:
        return "current"
    if fields == DIAGNOSTIC_RECEIPT_KEYS:
        return "diagnostic_aware"
    if fields == POST_CORRECTION_RECEIPT_KEYS:
        return "post_correction_aware"
    raise ValueError("export_receipt_invalid")


def _validate_manifest(manifest: Mapping[str, Any]) -> None:
    contract = _manifest_contract(manifest)
    if manifest.get("manifest_schema_version") != MANIFEST_SCHEMA_VERSION:
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
    if contract in {"current", "diagnostic_aware", "post_correction_aware"}:
        if isinstance(manifest["qualification_event_bound"], bool) or not isinstance(manifest["qualification_event_bound"], int) or manifest["qualification_event_bound"] < 0:
            raise ValueError("manifest_invalid")
        if not isinstance(manifest["qualification_state_digest"], str) or len(manifest["qualification_state_digest"]) != 64 or any(c not in "0123456789abcdef" for c in manifest["qualification_state_digest"]):
            raise ValueError("manifest_invalid")
    if contract in {"diagnostic_aware", "post_correction_aware"}:
        if manifest["diagnostic_contract_version"] != "stage77.diagnostic_aware.v1":
            raise ValueError("manifest_invalid")
        if not isinstance(manifest["diagnostic_evidence"], list) or len(manifest["diagnostic_evidence"]) > MAX_MANIFEST_ARTIFACTS:
            raise ValueError("manifest_invalid")
        expected_evidence_keys = {"job_id", "attempt_id", "terminal_event_id", "diagnostic_contract_version", "attempt_diagnostic_sha256", "terminal_diagnostic_sha256"}
        previous = None
        for item in manifest["diagnostic_evidence"]:
            if not isinstance(item, ABCMapping) or set(item) != expected_evidence_keys:
                raise ValueError("manifest_invalid")
            if any(isinstance(item[name], bool) or not isinstance(item[name], int) or item[name] < 0 for name in ("job_id", "attempt_id", "terminal_event_id")):
                raise ValueError("manifest_invalid")
            if item["diagnostic_contract_version"] not in {diagnostics.CURRENT_DIAGNOSTIC_CONTRACT, diagnostics.TRANSITIONAL_DIAGNOSTIC_CONTRACT, diagnostics.LEGACY_DIAGNOSTIC_CONTRACT}:
                raise ValueError("manifest_invalid")
            for name in ("attempt_diagnostic_sha256", "terminal_diagnostic_sha256"):
                if not isinstance(item[name], str) or len(item[name]) != 64 or any(c not in "0123456789abcdef" for c in item[name]):
                    raise ValueError("manifest_invalid")
            if previous is not None and int(item["job_id"]) <= previous:
                raise ValueError("manifest_invalid")
            previous = int(item["job_id"])
        if isinstance(manifest["diagnostic_evidence_count"], bool) or not isinstance(manifest["diagnostic_evidence_count"], int):
            raise ValueError("manifest_invalid")
        if manifest["diagnostic_evidence_count"] != len(manifest["diagnostic_evidence"]):
            raise ValueError("diagnostic_evidence_count_mismatch")
        evidence_digest = digest_bytes(canonical_json(manifest["diagnostic_evidence"]).encode("utf-8"))
        if manifest["diagnostic_evidence_state_digest"] != evidence_digest:
            raise ValueError("diagnostic_evidence_digest_mismatch")
        if isinstance(manifest["retry_link_count"], bool) or not isinstance(manifest["retry_link_count"], int) or manifest["retry_link_count"] < 0:
            raise ValueError("manifest_invalid")
        if not isinstance(manifest["retry_link_state_digest"], str) or len(manifest["retry_link_state_digest"]) != 64 or any(c not in "0123456789abcdef" for c in manifest["retry_link_state_digest"]):
            raise ValueError("manifest_invalid")
        if contract == "post_correction_aware":
            current_evidence = manifest.get("current_recovery_manifest_evidence")
            if not isinstance(current_evidence, ABCMapping) or manifest.get("current_recovery_manifest_evidence_digest") != digest_bytes(canonical_json(dict(current_evidence)).encode("utf-8")):
                raise ValueError("manifest_invalid")
            if set(current_evidence) != {"evidence_contract", "evidence_source_mode", "recovery_point_id", "recovery_contract", "maintenance_epoch", "database_digest", "diagnostic_count", "diagnostic_state_digest", "retry_link_count", "retry_topology_digest", "report_count", "version_count", "report_event_bound_status", "report_event_bound", "qualification_count", "qualification_event_bound", "job_count", "job_event_bound", "artifact_count", "recovery_event_bound", "sqlite_integrity", "foreign_key_violation_count", "evidence_contract_version"} or current_evidence.get("evidence_source_mode") != "native_capture" or current_evidence.get("evidence_contract") != RECOVERY_EVIDENCE_CONTRACT:
                raise ValueError("manifest_invalid")
            _validate_report_event_binding(current_evidence, require_bound=True)
            prior = manifest.get("persisted_prior_recovery_evidence")
            if not isinstance(prior, list) or manifest.get("persisted_prior_recovery_evidence_state_digest") != digest_bytes(canonical_json(prior).encode("utf-8")) or isinstance(manifest.get("persisted_prior_recovery_evidence_event_bound"), bool) or not isinstance(manifest.get("persisted_prior_recovery_evidence_event_bound"), int) or manifest["persisted_prior_recovery_evidence_event_bound"] < 0:
                raise ValueError("manifest_invalid")
            auth_snapshot = manifest.get("post_correction_authorization")
            if not isinstance(auth_snapshot, list) or any(not isinstance(item, ABCMapping) for item in auth_snapshot):
                raise ValueError("manifest_invalid")
            if manifest.get("post_correction_authorization_state_digest") != digest_bytes(canonical_json(auth_snapshot).encode("utf-8")):
                raise ValueError("manifest_invalid")
            if isinstance(manifest.get("post_correction_authorization_event_bound"), bool) or not isinstance(manifest.get("post_correction_authorization_event_bound"), int) or manifest["post_correction_authorization_event_bound"] < 0:
                raise ValueError("manifest_invalid")
    if not isinstance(manifest.get("integrity"), ABCMapping) or set(manifest["integrity"]) != {"integrity_check", "foreign_key_check"} or manifest["integrity"] != {"integrity_check": "ok", "foreign_key_check": "ok"}:
        raise ValueError("manifest_invalid")
    expected_counts = {"jobs", "reports", "versions", "artifacts"}
    if contract in {"current", "diagnostic_aware", "post_correction_aware"}:
        expected_counts.add("qualifications")
    if not isinstance(manifest.get("counts"), ABCMapping) or not isinstance(manifest.get("job_state_counts"), ABCMapping) or set(manifest["counts"]) != expected_counts or set(manifest["job_state_counts"]) != {"queued", "leased", "running", "retry_wait", "cancel_requested", "succeeded", "failed_terminal", "cancelled"}:
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
    contract = _manifest_contract(manifest)
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
        artifact_columns = {str(row[1]): str(row[2]).upper() for row in conn.execute("PRAGMA table_info(record_governed_report_artifacts)").fetchall()}
        required_artifact_columns = {"id": "INTEGER", "version_id": "INTEGER", "format": "TEXT", "storage_reference": "TEXT", "sha256": "TEXT", "size_bytes": "INTEGER", "validation_state": "TEXT"}
        if any(artifact_columns.get(name) != expected_type for name, expected_type in required_artifact_columns.items()):
            raise ValueError("schema_incompatible")
        database_contract, evidence, evidence_digest, retry_links, retry_links_digest = _database_contract(conn)
        if database_contract != contract:
            raise ValueError("schema_incompatible")
        if contract in {"current", "diagnostic_aware", "post_correction_aware"}:
            from api import governed_report_qualifications as qualifications
            try:
                qualifications.validate_qualification_tables(conn)
            except ValueError:
                raise ValueError("schema_incompatible") from None
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("integrity_check_failed")
        if not _foreign_keys_are_clean(conn):
            raise ValueError("foreign_key_check_failed")
        event_bound = int(conn.execute("SELECT COALESCE(MAX(id),0) FROM stage77_recovery_events").fetchone()[0])
        if event_bound != int(manifest["recovery_event_bound"]):
            raise ValueError("recovery_event_bound_mismatch")
        if contract in {"current", "diagnostic_aware", "post_correction_aware"}:
            qualification_state = qualifications.state_snapshot(conn)
            if qualification_state["count"] != int(manifest["counts"].get("qualifications", 0)):
                raise ValueError("qualification_count_mismatch")
            version_ids = [int(row[0]) for row in conn.execute("SELECT DISTINCT report_version_id FROM record_governed_report_qualifications ORDER BY report_version_id").fetchall()]
            for version_id in version_ids:
                qualifications.validate_complete_chain(conn, version_id)
            if contract == "current" and (qualification_state["event_bound"] != int(manifest["qualification_event_bound"]) or qualification_state["digest"] != manifest["qualification_state_digest"]):
                raise ValueError("qualification_state_mismatch")
        if contract in {"diagnostic_aware", "post_correction_aware"}:
            if evidence != manifest["diagnostic_evidence"] or evidence_digest != manifest["diagnostic_evidence_state_digest"] or int(manifest["diagnostic_evidence_count"]) != len(evidence):
                raise ValueError("diagnostic_evidence_mismatch")
            if retry_links_digest != manifest["retry_link_state_digest"] or int(manifest["retry_link_count"]) != len(retry_links):
                raise ValueError("retry_topology_mismatch")
        if contract == "post_correction_aware":
            base_manifest = {key: manifest[key] for key in DIAGNOSTIC_MANIFEST_KEYS}
            report_event_bound = int(conn.execute("SELECT COALESCE(MAX(id),0) FROM record_governed_report_events").fetchone()[0]) if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='record_governed_report_events'").fetchone() else 0
            expected_current = _recovery_evidence_payload(base_manifest, source_mode="native_capture", actor="", rationale="", declaration={}, idempotency_key="", created_at="", report_event_bound=report_event_bound, contract_name="post_correction_aware")
            if expected_current != manifest["current_recovery_manifest_evidence"]:
                raise ValueError("recovery_evidence_mismatch")
            evidence_snapshot, evidence_snapshot_digest, evidence_event_bound = _recovery_evidence_snapshot(conn)
            if evidence_snapshot != manifest["persisted_prior_recovery_evidence"] or evidence_snapshot_digest != manifest["persisted_prior_recovery_evidence_state_digest"] or evidence_event_bound != int(manifest["persisted_prior_recovery_evidence_event_bound"]):
                raise ValueError("recovery_evidence_mismatch")
            snapshot, snapshot_digest, event_bound = _post_correction_snapshot(conn)
            if snapshot != manifest["post_correction_authorization"] or snapshot_digest != manifest["post_correction_authorization_state_digest"] or event_bound != int(manifest["post_correction_authorization_event_bound"]):
                raise ValueError("post_correction_evidence_mismatch")
        rows = conn.execute("SELECT id,version_id,format,storage_reference,sha256,size_bytes FROM record_governed_report_artifacts WHERE validation_state='valid' ORDER BY id").fetchall()
        if len(rows) != len(manifest["artifacts"]):
            raise ValueError("artifact_inventory_mismatch")
        actual_job_states = {state: int(conn.execute("SELECT COUNT(*) FROM stage77_report_jobs WHERE state=?", (state,)).fetchone()[0]) for state in ("queued", "leased", "running", "retry_wait", "cancel_requested", "succeeded", "failed_terminal", "cancelled")}
        if actual_job_states != manifest["job_state_counts"] or sum(actual_job_states.values()) != int(manifest["counts"]["jobs"]):
            raise ValueError("job_state_count_mismatch")
        _validate_archived_job_runtime_metadata(conn, contract=contract)
        _validate_archived_job_cancellation(conn, contract=contract)
        _validate_archived_job_terminal_evidence(conn, contract=contract)
        _validate_archived_job_generation_configuration(conn, contract=contract)
        _validate_archived_job_qualification_binding(conn, contract=contract)
        total_jobs = sum(actual_job_states.values())
        if contract == "diagnostic_aware" and int(manifest["retry_link_count"]) == 1 and total_jobs != 2:
            raise ValueError("job_state_count_mismatch")
        if contract == "post_correction_aware":
            authorization_count = int(conn.execute("SELECT COUNT(*) FROM stage77_post_correction_authorizations").fetchone()[0])
            if authorization_count == 0 and total_jobs != 0:
                raise ValueError("job_state_count_mismatch")
        if int(manifest["counts"]["artifacts"]) != len(rows):
            raise ValueError("artifact_inventory_mismatch")
        if int(conn.execute("SELECT COUNT(*) FROM record_governed_reports").fetchone()[0]) != int(manifest["counts"]["reports"]):
            raise ValueError("record_count_mismatch")
        if int(conn.execute("SELECT COUNT(*) FROM record_governed_report_versions").fetchone()[0]) != int(manifest["counts"]["versions"]):
            raise ValueError("version_count_mismatch")
        if contract == "post_correction_aware":
            _validate_post_correction_recovery_eligibility(
                conn,
                report_count=int(conn.execute("SELECT COUNT(*) FROM record_governed_reports").fetchone()[0]),
                version_count=int(conn.execute("SELECT COUNT(*) FROM record_governed_report_versions").fetchone()[0]),
            )
        if contract == "diagnostic_aware":
            if int(manifest["counts"]["reports"]) != 1:
                raise ValueError("record_count_mismatch")
            if int(manifest["counts"]["versions"]) != 1:
                raise ValueError("version_count_mismatch")
            lifecycle_rows = conn.execute("SELECT lifecycle_status FROM record_governed_reports ORDER BY id").fetchall()
            if any(str(row[0]) not in {"generated", "validation_failed"} for row in lifecycle_rows):
                raise ValueError("report_lifecycle_invalid")
            version_columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(record_governed_report_versions)").fetchall()}
            if {"specification_json", "specification_digest"}.issubset(version_columns):
                for version in conn.execute("SELECT specification_json,specification_digest FROM record_governed_report_versions ORDER BY id").fetchall():
                    try:
                        specification = _strict_payload(str(version[0]))
                        expected_digest = digest_bytes(canonical_json(specification).encode("utf-8"))
                    except (TypeError, ValueError, json.JSONDecodeError):
                        raise ValueError("specification_digest_mismatch") from None
                    if not isinstance(specification, Mapping) or expected_digest != str(version[1]):
                        raise ValueError("specification_digest_mismatch")
        by_id = {int(item["artifact_id"]): item for item in manifest["artifacts"]}
        for row in rows:
            item = by_id.get(int(row["id"]))
            if not item or int(item["report_id"]) != int(conn.execute("SELECT report_id FROM record_governed_report_versions WHERE id=?", (row["version_id"],)).fetchone()[0]) or int(item["version_id"]) != int(row["version_id"]) or str(item["format"]) != str(row["format"]) or int(item["size_bytes"]) != int(row["size_bytes"]) or str(item["sha256"]) != str(row["sha256"]):
                raise ValueError("artifact_inventory_mismatch")
        job_columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(stage77_report_jobs)").fetchall()}
        if {"state", "report_version_id", "requested_formats_json"}.issubset(job_columns):
            succeeded = conn.execute("SELECT id,report_version_id,requested_formats_json FROM stage77_report_jobs WHERE state='succeeded' ORDER BY id").fetchall()
            succeeded_versions = {int(row["report_version_id"]) for row in succeeded}
            if succeeded_versions:
                artifact_versions = {int(row["version_id"]) for row in rows}
                if not artifact_versions.issubset(succeeded_versions):
                    raise ValueError("artifact_inventory_mismatch")
            for job in succeeded:
                try:
                    expected_formats = _strict_payload(str(job["requested_formats_json"]))
                except (TypeError, ValueError, json.JSONDecodeError):
                    raise ValueError("artifact_inventory_mismatch") from None
                actual_formats = [
                    str(row["format"])
                    for row in conn.execute(
                        "SELECT format FROM record_governed_report_artifacts WHERE version_id=? AND validation_state='valid' ORDER BY format",
                        (int(job["report_version_id"]),),
                    ).fetchall()
                ]
                if not isinstance(expected_formats, list) or sorted(str(item) for item in expected_formats) != actual_formats:
                    raise ValueError("artifact_inventory_mismatch")
    finally:
        conn.close()
    for item in manifest["artifacts"]:
        data = (bundle / str(item["filename"])).read_bytes()
        if len(data) != int(item["size_bytes"]) or digest_bytes(data) != str(item["sha256"]):
            raise ValueError("artifact_digest_mismatch")


def capture_recovery_point(*, database_path: str | os.PathLike[str], artifact_root: str | os.PathLike[str], recovery_root: str | os.PathLike[str], actor: str, governed_action: str, idempotency_key: str = "", approved_root: str | os.PathLike[str] = "/data", drain_timeout: float = 30.0, application_version: str = "unknown", publication_engine_version: str = "2.0.0", fault_injector: CaptureFaultInjector | None = None) -> dict[str, Any]:
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
        phase, operation, checkpoint = "initialization", "schema_validation", "starting"
        _validate_capture_schema(conn)
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
        if fault_injector is not None:
            fault_injector.checkpoint("before_snapshot_creation")
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
                if fault_injector is not None:
                    fault_injector.checkpoint("during_snapshot_creation")
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
            if fault_injector is not None:
                fault_injector.checkpoint("after_snapshot_before_database_digest")
            backup_check = _read_connection(backup_path)
            try:
                if fault_injector is not None:
                    fault_injector.checkpoint("during_sqlite_integrity_validation")
                if backup_check.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("integrity_check_failed")
                phase, operation, checkpoint = "validation", "foreign_key_check", "starting"
                if fault_injector is not None:
                    fault_injector.checkpoint("during_sqlite_foreign_key_validation")
                if not _foreign_keys_are_clean(backup_check):
                    raise ValueError("foreign_key_check_failed")
                job_counts = {state: int(backup_check.execute("SELECT COUNT(*) FROM stage77_report_jobs WHERE state=?", (state,)).fetchone()[0]) for state in ("queued", "leased", "running", "retry_wait", "cancel_requested", "succeeded", "failed_terminal", "cancelled")}
                phase, operation, checkpoint = "validation", "job_event_bound_read", "starting"
                max_event = int(backup_check.execute("SELECT COALESCE(MAX(id),0) FROM stage77_report_job_events").fetchone()[0])
                phase, operation, checkpoint = "validation", "job_count_read", "starting"
                job_count = int(backup_check.execute("SELECT COUNT(*) FROM stage77_report_jobs").fetchone()[0])
                phase, operation, checkpoint = "validation", "report_count_read", "starting"
                report_count = int(backup_check.execute("SELECT COUNT(*) FROM record_governed_reports").fetchone()[0])
                phase, operation, checkpoint = "validation", "version_count_read", "starting"
                version_count = int(backup_check.execute("SELECT COUNT(*) FROM record_governed_report_versions").fetchone()[0])
                phase, operation, checkpoint = "validation", "artifact_count_read", "starting"
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
                database_contract, diagnostic_evidence, diagnostic_evidence_digest, retry_links, retry_links_digest = _database_contract(backup_check)
                _validate_archived_job_runtime_metadata(backup_check, contract=database_contract)
                if database_contract == "post_correction_aware":
                    _validate_post_correction_recovery_eligibility(backup_check, report_count=report_count, version_count=version_count)
                qualification_state = qualifications.state_snapshot(backup_check)
                phase, operation, checkpoint = "validation", "manifest_database_reads", "starting"
                manifest = {"manifest_schema_version": MANIFEST_SCHEMA_VERSION, "recovery_point_id": control["recovery_point_id"], "maintenance_epoch": int(control["maintenance_epoch"]), "created_at": utc_now(), "source_database_identity": _database_identity(database, backup_data), "sqlite_version": sqlite3.sqlite_version, "application_version": application_version, "publication_engine_version": publication_engine_version, "stage77_schema_version": "stage77.governed_report_job.v1", "database": {"filename": "database.sqlite3", "size_bytes": len(backup_data), "sha256": digest_bytes(backup_data)}, "integrity": {"integrity_check": "ok", "foreign_key_check": "ok"}, "job_event_bound": max_event, "recovery_event_bound": recovery_event_bound, "qualification_event_bound": qualification_state["event_bound"], "qualification_state_digest": qualification_state["digest"], "job_state_counts": job_counts, "counts": {"jobs": job_count, "reports": report_count, "versions": version_count, "artifacts": artifact_count, "qualifications": qualification_state["count"]}, "artifacts": inventory, "limitations": ["integrity evidence is not proof of authorship", "restoration requires isolated target paths and validation", "completion event is recorded after the backup event bound"]}
                if database_contract == "diagnostic_aware":
                    manifest.update({
                        "diagnostic_contract_version": "stage77.diagnostic_aware.v1",
                        "diagnostic_evidence": diagnostic_evidence,
                        "diagnostic_evidence_count": len(diagnostic_evidence),
                        "diagnostic_evidence_state_digest": diagnostic_evidence_digest,
                        "retry_link_count": len(retry_links),
                        "retry_link_state_digest": retry_links_digest,
                    })
                if database_contract == "post_correction_aware":
                    post_snapshot, post_digest, post_event_bound = _post_correction_snapshot(backup_check)
                    custody_snapshot, custody_digest, custody_event_bound = _post_correction_custody_snapshot(backup_check)
                    evidence_snapshot, evidence_digest, evidence_event_bound = _recovery_evidence_snapshot(backup_check)
                    manifest.update({
                        "diagnostic_contract_version": "stage77.diagnostic_aware.v1",
                        "diagnostic_evidence": diagnostic_evidence,
                        "diagnostic_evidence_count": len(diagnostic_evidence),
                        "diagnostic_evidence_state_digest": diagnostic_evidence_digest,
                        "retry_link_count": len(retry_links),
                        "retry_link_state_digest": retry_links_digest,
                    })
                    report_event_bound = int(backup_check.execute("SELECT COALESCE(MAX(id),0) FROM record_governed_report_events").fetchone()[0]) if backup_check.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='record_governed_report_events'").fetchone() else 0
                    current_evidence = _recovery_evidence_payload(manifest, source_mode="native_capture", actor="", rationale="", declaration={}, idempotency_key="", created_at="", report_event_bound=report_event_bound, contract_name="post_correction_aware")
                    current_evidence_digest = digest_bytes(canonical_json(current_evidence).encode("utf-8"))
                    if fault_injector is not None:
                        fault_injector.checkpoint("after_current_evidence_before_manifest")
                    manifest.update({
                        "diagnostic_contract_version": "stage77.diagnostic_aware.v1",
                        "diagnostic_evidence": diagnostic_evidence,
                        "diagnostic_evidence_count": len(diagnostic_evidence),
                        "diagnostic_evidence_state_digest": diagnostic_evidence_digest,
                        "retry_link_count": len(retry_links),
                        "retry_link_state_digest": retry_links_digest,
                        "post_correction_authorization": post_snapshot,
                        "post_correction_authorization_state_digest": post_digest,
                        "post_correction_authorization_event_bound": post_event_bound,
                        "post_correction_custody_attestation": custody_snapshot,
                        "post_correction_custody_attestation_state_digest": custody_digest,
                        "post_correction_custody_attestation_event_bound": custody_event_bound,
                        "current_recovery_manifest_evidence": current_evidence,
                        "current_recovery_manifest_evidence_digest": current_evidence_digest,
                        "persisted_prior_recovery_evidence": evidence_snapshot,
                        "persisted_prior_recovery_evidence_state_digest": evidence_digest,
                        "persisted_prior_recovery_evidence_event_bound": evidence_event_bound,
                    })
                phase, operation, checkpoint = "validation", "manifest_write", "starting"
                if fault_injector is not None:
                    fault_injector.checkpoint("during_canonical_manifest_creation")
                raw_manifest = canonical_json(manifest).encode("utf-8")
                (stage / "manifest.json").write_bytes(raw_manifest)
                (stage / "manifest.sha256").write_text(digest_bytes(raw_manifest) + "\n", encoding="ascii")
                phase, operation, checkpoint = "validation", "bundle_validation", "starting"
                if fault_injector is not None:
                    fault_injector.checkpoint("after_manifest_before_bundle_validation")
                _verify_bundle(stage, manifest)
                phase, operation, checkpoint = "validation", "recovery_evidence_persistence", "starting"
                if fault_injector is not None:
                    fault_injector.checkpoint("after_bundle_validation_before_live_evidence")
                _insert_recovery_evidence(conn, manifest, source_mode="native_capture", actor=actor,
                                          rationale="native recovery capture", declaration={"acknowledged": True, "version": 1},
                                          idempotency_key=f"native-{control['recovery_point_id']}", created_at=manifest["created_at"],
                                          final_manifest_digest=digest_bytes(raw_manifest), fault_injector=fault_injector)
                conn.commit()
                phase, operation, checkpoint = "promotion", "bundle_promotion", "starting"
                os.replace(stage, final)
                phase, operation, checkpoint = "completion", "completion_event_write", "starting"
                if fault_injector is not None:
                    fault_injector.checkpoint("after_evidence_event_before_completion")
                stage_parent = stage.parent
                if stage_parent.exists() and not any(stage_parent.iterdir()):
                    phase, operation, checkpoint = "completion", "staging_directory", "starting"
                    if fault_injector is not None:
                        fault_injector.checkpoint("during_final_staging_cleanup")
                    stage_parent.rmdir()
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
                if stage.exists():
                    shutil.rmtree(stage, ignore_errors=False)
                cleanup_status = "completed"
            except Exception:
                cleanup_status = "failed"
        if rollback_failed:
            cleanup_status = "failed"
        maintenance_status = "unknown"
        durable_interruption = fault_injector is not None and fault_injector.triggered_failure in {
            "after_evidence_event_before_completion", "during_final_staging_cleanup",
        }
        if not durable_interruption:
            try:
                fail_recovery(conn, phase=phase, code=primary_code)
                maintenance_status = "failed"
            except Exception:
                maintenance_status = "unknown"
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
            if _manifest_contract(manifest) == "post_correction_aware":
                _insert_recovery_evidence(
                    conn, manifest, source_mode="native_capture", actor=actor,
                    rationale="restored from validated recovery manifest",
                    declaration={"acknowledged": True, "version": 1},
                    idempotency_key=f"restore-{point_id}", created_at=utc_now(),
                    final_manifest_digest=manifest_digest,
                )
                if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or not _foreign_keys_are_clean(conn):
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


def reconcile_interrupted_recovery(*, database_path: str | os.PathLike[str], recovery_root: str | os.PathLike[str], actor: str, approved_root: str | os.PathLike[str] = "/data") -> dict[str, Any]:
    """Explicitly reconcile a promoted bundle left before completion commit."""
    root = _require_recovery_root(recovery_root, approved_root=approved_root)
    conn = _connect(database_path)
    try:
        ensure_recovery_tables(conn)
        control = _control(conn)
        if control is None:
            raise ValueError("recovery_reconciliation_not_interrupted")
        bundle = root / f"recovery-{control['recovery_point_id']}"
        manifest, manifest_digest = _manifest_and_digest(bundle)
        _verify_bundle(bundle, manifest)
        if control["state"] == "completed":
            evidence = recovery_evidence_for_point(conn, str(control["recovery_point_id"]))
            if str(evidence.get("manifest_digest")) != manifest_digest:
                raise ValueError("recovery_reconciliation_conflict")
            return {"recovery_point_id": str(control["recovery_point_id"]), "manifest_digest": manifest_digest, "state": "completed"}
        if control["state"] not in {"capturing", "validating"}:
            raise ValueError("recovery_reconciliation_not_interrupted")
        conn.execute("BEGIN IMMEDIATE")
        try:
            current = _control(conn)
            if current is None or current["operation_id"] != control["operation_id"] or current["state"] not in {"capturing", "validating"}:
                raise ValueError("recovery_reconciliation_conflict")
            stage_parent = root / ".stage"
            stage_metadata = _lstat(stage_parent)
            if stage_metadata is not None:
                if stat.S_ISLNK(stage_metadata.st_mode) or not stat.S_ISDIR(stage_metadata.st_mode) or any(stage_parent.iterdir()):
                    raise ValueError("recovery_reconciliation_conflict")
                try:
                    stage_parent.rmdir()
                except OSError:
                    raise ValueError("recovery_operation_failed") from None
            _insert_recovery_evidence(
                conn, manifest, source_mode="native_capture", actor=actor,
                rationale="explicit interrupted recovery reconciliation",
                declaration={"acknowledged": True, "version": 1},
                idempotency_key=f"native-{control['recovery_point_id']}",
                created_at=manifest["created_at"], final_manifest_digest=manifest_digest,
            )
            recovery_evidence_for_point(conn, str(control["recovery_point_id"]))
            conn.execute("UPDATE stage77_recovery_control SET state='completed',completed_at=?,manifest_digest=?,source_database_identity=?,worker_drained=1 WHERE singleton=1", (utc_now(), manifest_digest, manifest["source_database_identity"]))
            updated = _control(conn)
            _event(conn, updated, "recovery_reconciled_completed", "completed", actor, {"manifest_digest": manifest_digest})
            conn.commit()
            return {"recovery_point_id": str(control["recovery_point_id"]), "manifest_digest": manifest_digest, "state": "completed"}
        except Exception:
            conn.rollback()
            raise
    finally:
        conn.close()


def validate_recovery_bundle(bundle_path: str | os.PathLike[str]) -> dict[str, Any]:
    bundle = _lexical_path(bundle_path, error="bundle_file_invalid")
    _assert_bundle_tree(bundle)
    manifest, digest = _manifest_and_digest(bundle)
    _verify_bundle(bundle, manifest)
    return {"state": "valid", "manifest_digest": digest, "recovery_point_id": str(manifest["recovery_point_id"])}


def reconstruct_recovery_point_evidence(*, database_path: str | os.PathLike[str], recovery_root: str | os.PathLike[str], recovery_point_id: str, actor: str, rationale: str, acknowledged: bool, idempotency_key: str, approved_root: str | os.PathLike[str] = "/data") -> dict[str, Any]:
    """Record deterministic evidence for one preserved bundle; never changes the bundle."""
    if not str(actor).strip() or not str(rationale).strip() or len(str(rationale).strip()) > 4000 or acknowledged is not True or not str(idempotency_key).strip():
        raise ValueError("recovery_evidence_reconstruction_input_invalid")
    if not re.fullmatch(r"[0-9a-f]{32}", str(recovery_point_id)):
        raise ValueError("recovery_evidence_identity_invalid")
    root = _require_recovery_root(recovery_root, approved_root=approved_root)
    bundle = _lexical_path(root / f"recovery-{recovery_point_id}", error="bundle_file_invalid")
    if not bundle.is_relative_to(root) or bundle.is_symlink():
        raise ValueError("path_outside_recovery_root")
    _assert_no_symlink_components(bundle.parent, require_directory=True, error="symlink_component")
    manifest, _manifest_digest = _manifest_and_digest(bundle)
    if str(manifest["recovery_point_id"]) != str(recovery_point_id):
        raise ValueError("recovery_evidence_identity_invalid")
    try:
        _verify_bundle(bundle, manifest)
    except sqlite3.Error:
        raise ValueError("sqlite_error") from None
    archived = _read_connection(bundle / "database.sqlite3")
    try:
        if archived.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='stage77_recovery_point_evidence'").fetchone() is not None and archived.execute("SELECT COUNT(*) FROM stage77_recovery_point_evidence WHERE recovery_point_id=?", (str(recovery_point_id),)).fetchone()[0]:
            raise ValueError("recovery_evidence_conflict")
    finally:
        archived.close()
    conn = _connect(database_path)
    try:
        ensure_recovery_tables(conn)
        conn.execute("BEGIN IMMEDIATE")
        try:
            existing = conn.execute("SELECT * FROM stage77_recovery_point_evidence WHERE recovery_point_id=?", (str(recovery_point_id),)).fetchone()
            declaration = {"acknowledged": True, "version": 1, "text": "I confirm this is a reconstruction of deterministic recovery evidence from the preserved canonical production recovery bundle; it is not a new capture, restore, export or custody verification."}
            if existing:
                if str(existing["idempotency_key"]) != str(idempotency_key):
                    raise ValueError("recovery_evidence_conflict")
                conn.commit()
                return dict(existing)
            try:
                result = _insert_recovery_evidence(conn, manifest, source_mode="historical_reconstruction", actor=str(actor), rationale=str(rationale).strip(), declaration=declaration, idempotency_key=str(idempotency_key).strip(), created_at=utc_now(), final_manifest_digest=_manifest_digest)
            except sqlite3.Error:
                raise ValueError("sqlite_error") from None
            conn.commit()
            return result
        except Exception:
            conn.rollback()
            raise
    finally:
        conn.close()


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
    receipt = {
        "receipt_schema_version": EXPORT_RECEIPT_SCHEMA_VERSION,
        "recovery_point_id": str(manifest["recovery_point_id"]),
        "created_at": utc_now(),
        "recovery_reason": reason,
        "manifest_digest": str(manifest["_manifest_digest"]),
        "database_digest": str(manifest["database"]["sha256"]),
        "archive_digest": archive_digest,
        "artifact_count": int(manifest["counts"]["artifacts"]),
        "qualification_count": int(manifest["counts"]["qualifications"]),
        "qualification_event_bound": int(manifest["qualification_event_bound"]),
        "qualification_state_digest": str(manifest["qualification_state_digest"]),
        "recovery_event_bound": int(manifest["recovery_event_bound"]),
        "job_event_bound": int(manifest["job_event_bound"]),
        "application_version": str(manifest["application_version"]),
        "publication_engine_version": str(manifest["publication_engine_version"]),
        "stage77_schema_version": str(manifest["stage77_schema_version"]),
    }
    if manifest.get("diagnostic_contract_version") == "stage77.diagnostic_aware.v1":
        receipt.update({
            "diagnostic_contract_version": str(manifest["diagnostic_contract_version"]),
            "diagnostic_evidence_count": int(manifest["diagnostic_evidence_count"]),
            "diagnostic_evidence_state_digest": str(manifest["diagnostic_evidence_state_digest"]),
            "retry_link_count": int(manifest["retry_link_count"]),
            "retry_link_state_digest": str(manifest["retry_link_state_digest"]),
        })
    if "post_correction_authorization_state_digest" in manifest:
        receipt.update({
            "post_correction_authorization_state_digest": str(manifest["post_correction_authorization_state_digest"]),
            "post_correction_authorization_event_bound": int(manifest["post_correction_authorization_event_bound"]),
        })
    if "post_correction_custody_attestation_state_digest" in manifest:
        receipt.update({
            "post_correction_custody_attestation_state_digest": str(manifest["post_correction_custody_attestation_state_digest"]),
            "post_correction_custody_attestation_event_bound": int(manifest["post_correction_custody_attestation_event_bound"]),
        })
    return receipt


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
    if not isinstance(receipt, dict) or raw != canonical_json(receipt).encode("utf-8"):
        raise ValueError("export_receipt_invalid")
    _receipt_contract(receipt)
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
    if _receipt_contract(receipt) in {"current", "diagnostic_aware", "post_correction_aware"} and (len(receipt["qualification_state_digest"]) != 64 or any(char not in "0123456789abcdef" for char in receipt["qualification_state_digest"])):
        raise ValueError("export_receipt_invalid")
    numeric_fields = ["artifact_count", "recovery_event_bound", "job_event_bound"]
    if _receipt_contract(receipt) in {"current", "diagnostic_aware", "post_correction_aware"}:
        numeric_fields.extend(("qualification_count", "qualification_event_bound"))
    if _receipt_contract(receipt) in {"diagnostic_aware", "post_correction_aware"}:
        if receipt["diagnostic_contract_version"] != "stage77.diagnostic_aware.v1":
            raise ValueError("export_receipt_invalid")
        for key in ("diagnostic_evidence_state_digest", "retry_link_state_digest"):
            if not isinstance(receipt[key], str) or len(receipt[key]) != 64 or any(char not in "0123456789abcdef" for char in receipt[key]):
                raise ValueError("export_receipt_invalid")
        numeric_fields.extend(("diagnostic_evidence_count", "retry_link_count"))
    if _receipt_contract(receipt) == "post_correction_aware":
        if len(receipt["post_correction_authorization_state_digest"]) != 64 or any(char not in "0123456789abcdef" for char in receipt["post_correction_authorization_state_digest"]):
            raise ValueError("export_receipt_invalid")
        if isinstance(receipt["post_correction_authorization_event_bound"], bool) or not isinstance(receipt["post_correction_authorization_event_bound"], int) or receipt["post_correction_authorization_event_bound"] < 0:
            raise ValueError("export_receipt_invalid")
    for key in numeric_fields:
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
    receipt_contract = _receipt_contract(receipt)
    if digest_bytes(archive.read_bytes()) != receipt["archive_digest"]:
        raise ValueError("export_archive_digest_mismatch")
    temporary = Path(tempfile.mkdtemp(prefix="stage77-export-check-", dir=archive.parent))
    try:
        bundle = _extract_export_archive(archive, temporary / "bundle")
        result = validate_recovery_bundle(bundle)
        manifest, manifest_digest = _manifest_and_digest(bundle)
        manifest_contract = _manifest_contract(manifest)
        if receipt_contract != manifest_contract:
            raise ValueError("export_receipt_mismatch")
        common_mismatch = result["recovery_point_id"] != receipt["recovery_point_id"] or manifest_digest != receipt["manifest_digest"] or manifest["database"]["sha256"] != receipt["database_digest"] or int(manifest["counts"]["artifacts"]) != receipt["artifact_count"] or int(manifest["recovery_event_bound"]) != receipt["recovery_event_bound"] or int(manifest["job_event_bound"]) != receipt["job_event_bound"]
        qualification_mismatch = manifest_contract in {"current", "diagnostic_aware", "post_correction_aware"} and (int(manifest["counts"]["qualifications"]) != receipt["qualification_count"] or int(manifest["qualification_event_bound"]) != receipt["qualification_event_bound"] or manifest["qualification_state_digest"] != receipt["qualification_state_digest"])
        diagnostic_mismatch = manifest_contract in {"diagnostic_aware", "post_correction_aware"} and (
            receipt.get("diagnostic_contract_version") != manifest["diagnostic_contract_version"]
            or int(receipt.get("diagnostic_evidence_count", -1)) != int(manifest["diagnostic_evidence_count"])
            or receipt.get("diagnostic_evidence_state_digest") != manifest["diagnostic_evidence_state_digest"]
            or int(receipt.get("retry_link_count", -1)) != int(manifest["retry_link_count"])
            or receipt.get("retry_link_state_digest") != manifest["retry_link_state_digest"]
        )
        post_correction_mismatch = manifest_contract == "post_correction_aware" and (
            receipt.get("post_correction_authorization_state_digest") != manifest.get("post_correction_authorization_state_digest")
            or int(receipt.get("post_correction_authorization_event_bound", -1)) != int(manifest.get("post_correction_authorization_event_bound", -2))
            or receipt.get("post_correction_custody_attestation_state_digest") != manifest.get("post_correction_custody_attestation_state_digest")
            or int(receipt.get("post_correction_custody_attestation_event_bound", -1)) != int(manifest.get("post_correction_custody_attestation_event_bound", -2))
        )
        if common_mismatch or qualification_mismatch or diagnostic_mismatch or post_correction_mismatch:
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
    if _manifest_contract(manifest) not in {"current", "diagnostic_aware", "post_correction_aware"}:
        raise ValueError("export_source_contract_unsupported")
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
