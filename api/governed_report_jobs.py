"""Stage 77 durable operational queue for existing governed reports.

This module owns scheduling, leases and bounded execution state. Stage 75
continues to own report specifications, lifecycle and artifact records.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from api import record_governed_reports as reports
from api.governed_report_diagnostics import bounded_code, make_diagnostic, validate_diagnostic

JOB_SCHEMA_VERSION = "stage77.governed_report_job.v1"
WORKER_IDENTITY = "cde-governed-report-worker"
JOB_STATES = {"queued", "leased", "running", "retry_wait", "cancel_requested", "succeeded", "failed_terminal", "cancelled"}
TERMINAL_STATES = {"succeeded", "failed_terminal", "cancelled"}
RETRYABLE_CODES = {"sqlite_busy", "worker_interrupted"}
MAX_ATTEMPTS = 3
LEASE_SECONDS = 180
HEARTBEAT_SECONDS = 20
BUSY_TIMEOUT_MS = 5000


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def configure_connection(conn: sqlite3.Connection, *, require_wal: bool = False) -> sqlite3.Connection:
    conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    for attempt in range(3):
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            break
        except sqlite3.OperationalError as exc:
            locked = "locked" in str(exc).lower() or "busy" in str(exc).lower()
            if not require_wal or not locked or attempt == 2:
                raise
            time.sleep(0.05 * (attempt + 1))
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _connect(path: str | os.PathLike[str]) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=BUSY_TIMEOUT_MS / 1000, isolation_level=None)
    conn.row_factory = sqlite3.Row
    return configure_connection(conn, require_wal=True)


def ensure_job_tables(conn: sqlite3.Connection) -> None:
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS stage77_report_jobs (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      report_id INTEGER NOT NULL,
      report_version_id INTEGER NOT NULL,
      specification_digest TEXT NOT NULL,
      requested_formats_json TEXT NOT NULL,
      rendering_profile TEXT NOT NULL,
      template_version TEXT NOT NULL,
      publication_engine_version TEXT NOT NULL,
      requesting_actor TEXT NOT NULL,
      governed_action TEXT NOT NULL,
      requested_at TEXT NOT NULL,
      state TEXT NOT NULL,
      attempt_count INTEGER NOT NULL DEFAULT 0,
      max_attempts INTEGER NOT NULL,
      next_eligible_at TEXT NOT NULL,
      lease_owner TEXT,
      lease_token TEXT,
      lease_acquired_at TEXT,
      lease_expires_at TEXT,
      heartbeat_at TEXT,
      cancellation_requested_at TEXT,
      terminal_at TEXT,
      terminal_outcome TEXT,
      failure_phase TEXT,
      failure_code TEXT,
      idempotency_key TEXT NOT NULL UNIQUE,
      retry_of_job_id INTEGER,
      qualification_id INTEGER,
      qualification_digest TEXT,
      maintenance_epoch INTEGER NOT NULL DEFAULT 0,
      schema_version TEXT NOT NULL,
      FOREIGN KEY(report_id) REFERENCES record_governed_reports(id),
      FOREIGN KEY(report_version_id) REFERENCES record_governed_report_versions(id),
      FOREIGN KEY(retry_of_job_id) REFERENCES stage77_report_jobs(id),
      CHECK(state IN ('queued','leased','running','retry_wait','cancel_requested','succeeded','failed_terminal','cancelled'))
    );
    CREATE TABLE IF NOT EXISTS stage77_report_job_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      job_id INTEGER NOT NULL,
      event_type TEXT NOT NULL,
      resulting_state TEXT NOT NULL,
      actor TEXT NOT NULL,
      occurred_at TEXT NOT NULL,
      payload_json TEXT NOT NULL,
      FOREIGN KEY(job_id) REFERENCES stage77_report_jobs(id)
    );
    CREATE INDEX IF NOT EXISTS idx_stage77_jobs_eligible ON stage77_report_jobs(state,next_eligible_at);
    CREATE INDEX IF NOT EXISTS idx_stage77_jobs_report ON stage77_report_jobs(report_id,report_version_id);
    CREATE INDEX IF NOT EXISTS idx_stage77_events_job ON stage77_report_job_events(job_id,id);
    """)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(stage77_report_jobs)").fetchall()}
    if "maintenance_epoch" not in columns:
        conn.execute("ALTER TABLE stage77_report_jobs ADD COLUMN maintenance_epoch INTEGER NOT NULL DEFAULT 0")
    if "qualification_id" not in columns:
        conn.execute("ALTER TABLE stage77_report_jobs ADD COLUMN qualification_id INTEGER")
    if "qualification_digest" not in columns:
        conn.execute("ALTER TABLE stage77_report_jobs ADD COLUMN qualification_digest TEXT")


def _payload(report: Mapping[str, Any], actor: str, action: str) -> dict[str, Any]:
    version = report["versions"][-1]
    spec = version["specification"]
    qualification = report.get("_qualification")
    return {
        "report_id": int(report["id"]),
        "report_version_id": int(version["id"]),
        "specification_digest": str(version["specification_digest"]),
        "requested_formats": list(spec["requested_formats"]),
        "rendering_profile": str(spec["rendering_profile"]),
        "template_version": str(spec["template_version"]),
        "publication_engine_version": str(spec["publication_engine_version"]),
        "actor": str(actor),
        "action": str(action),
        "qualification_id": None if qualification is None else int(qualification["id"]),
        "qualification_digest": None if qualification is None else str(qualification["digest"]),
    }


def _event(conn: sqlite3.Connection, job_id: int, event_type: str, state: str, actor: str, payload: Mapping[str, Any] | None = None) -> None:
    conn.execute("INSERT INTO stage77_report_job_events(job_id,event_type,resulting_state,actor,occurred_at,payload_json) VALUES(?,?,?,?,?,?)", (job_id, event_type, state, actor, utc_now(), reports.canonical_json(dict(payload or {}))))


def _job(conn: sqlite3.Connection, job_id: int) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM stage77_report_jobs WHERE id=?", (int(job_id),)).fetchone()
    if row is None:
        raise ValueError("governed_report_job_not_found")
    value = dict(row)
    value["requested_formats"] = json.loads(value.pop("requested_formats_json"))
    value["events"] = [dict(item) for item in conn.execute("SELECT * FROM stage77_report_job_events WHERE job_id=? ORDER BY id", (int(job_id),)).fetchall()]
    return value


def _job_table_exists(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='stage77_report_jobs'").fetchone() is not None


def get_job(conn: sqlite3.Connection, job_id: int | str) -> dict[str, Any]:
    return _job(conn, int(job_id))


def list_jobs(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    if not _job_table_exists(conn):
        return []
    return [_job(conn, row[0]) for row in conn.execute("SELECT id FROM stage77_report_jobs ORDER BY requested_at,id").fetchall()]


def enqueue_generation(conn: sqlite3.Connection, *, report_id: int | str, actor: str, governed_action: str, idempotency_key: str, retry_of_job_id: int | None = None) -> dict[str, Any]:
    reports.ensure_report_tables(conn)
    ensure_job_tables(conn)
    key = str(idempotency_key or "").strip()
    if not key:
        raise ValueError("governed_report_generation_idempotency_key_required")
    existing = conn.execute("SELECT * FROM stage77_report_jobs WHERE idempotency_key=?", (key,)).fetchone()
    if existing:
        existing_payload = {k: existing[k] for k in ("report_id", "report_version_id", "specification_digest", "rendering_profile", "template_version", "publication_engine_version", "requesting_actor", "governed_action", "qualification_id", "qualification_digest")}
        existing_payload["requested_formats"] = json.loads(existing["requested_formats_json"])
        report = reports.get_report(conn, report_id)
        if "qualifications" in report:
            from api import governed_report_qualifications as qualification_store
            qualification = qualification_store.latest_final(conn, report_id)
            if qualification is None:
                raise ValueError("governed_report_qualification_required")
            report = dict(report)
            report["_qualification"] = qualification
        expected_payload = _payload(report, actor, governed_action)
        expected_payload["requesting_actor"] = expected_payload.pop("actor")
        expected_payload["governed_action"] = expected_payload.pop("action")
        if reports.canonical_json(existing_payload) != reports.canonical_json(expected_payload):
            raise ValueError("governed_report_generation_idempotency_conflict")
        return _job(conn, existing["id"])
    report = reports.get_report(conn, report_id)
    if "qualifications" in report:
        from api import governed_report_qualifications as qualification_store
        qualification = qualification_store.latest_final(conn, report_id)
        if qualification is None:
            raise ValueError("governed_report_qualification_required")
        if qualification["payload"]["review_mode"] == qualification_store.SOLE_MODE and qualification_store.configured_review_mode() != qualification_store.SOLE_MODE:
            raise ValueError("governed_report_sole_mode_disabled")
        report = dict(report)
        report["_qualification"] = qualification
    if report["lifecycle_status"] != "approved_for_generation":
        raise ValueError("governed_report_generation_approval_required")
    payload = _payload(report, actor, governed_action)
    if reports.specification_digest(report["versions"][-1]["specification"]) != payload["specification_digest"]:
        raise ValueError("governed_report_specification_digest_mismatch")
    now = utc_now()
    conn.execute("BEGIN IMMEDIATE")
    try:
        cur = conn.execute("INSERT INTO stage77_report_jobs(report_id,report_version_id,specification_digest,requested_formats_json,rendering_profile,template_version,publication_engine_version,requesting_actor,governed_action,qualification_id,qualification_digest,requested_at,state,attempt_count,max_attempts,next_eligible_at,idempotency_key,retry_of_job_id,maintenance_epoch,schema_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (payload["report_id"], payload["report_version_id"], payload["specification_digest"], reports.canonical_json(payload["requested_formats"]), payload["rendering_profile"], payload["template_version"], payload["publication_engine_version"], payload["actor"], payload["action"], payload["qualification_id"], payload["qualification_digest"], now, "queued", 0, MAX_ATTEMPTS, now, key, retry_of_job_id, 0, JOB_SCHEMA_VERSION))
        job_id = int(cur.lastrowid)
        _event(conn, job_id, "enqueued", "queued", actor, payload)
        conn.execute("UPDATE record_governed_reports SET lifecycle_status='generation_requested' WHERE id=?", (int(report_id),))
        conn.execute("UPDATE record_governed_report_versions SET lifecycle_status='generation_requested' WHERE id=?", (payload["report_version_id"],))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return _job(conn, job_id)


def retry_job(conn: sqlite3.Connection, job_id: int | str, actor: str) -> dict[str, Any]:
    original = _job(conn, int(job_id))
    if original["state"] != "failed_terminal":
        raise ValueError("governed_report_job_retry_ineligible")
    return enqueue_generation(conn, report_id=original["report_id"], actor=actor, governed_action="retry_generation", idempotency_key=f"stage77-retry-{int(job_id)}", retry_of_job_id=int(job_id))


def request_cancel(conn: sqlite3.Connection, job_id: int | str, actor: str) -> dict[str, Any]:
    ensure_job_tables(conn)
    conn.execute("BEGIN IMMEDIATE")
    row = conn.execute("SELECT state FROM stage77_report_jobs WHERE id=?", (int(job_id),)).fetchone()
    if row is None: conn.rollback(); raise ValueError("governed_report_job_not_found")
    if row[0] in TERMINAL_STATES: conn.rollback(); raise ValueError("governed_report_job_terminal")
    state = "cancelled" if row[0] == "queued" else "cancel_requested"
    conn.execute("UPDATE stage77_report_jobs SET state=?,cancellation_requested_at=? WHERE id=? AND state NOT IN ('succeeded','failed_terminal','cancelled')", (state, utc_now(), int(job_id)))
    _event(conn, int(job_id), "cancel_requested", state, actor)
    conn.commit()
    return _job(conn, job_id)


def claim_one(conn: sqlite3.Connection, owner: str = WORKER_IDENTITY) -> dict[str, Any] | None:
    ensure_job_tables(conn)
    from api.governed_report_recovery import recovery_allows_claim, recovery_status
    if not recovery_allows_claim(conn):
        return None
    now = utc_now()
    conn.execute("BEGIN IMMEDIATE")
    if not recovery_allows_claim(conn):
        conn.rollback()
        return None
    maintenance_epoch = int(recovery_status(conn).get("maintenance_epoch", 0))
    row = conn.execute("SELECT * FROM stage77_report_jobs WHERE (state IN ('queued','retry_wait') AND next_eligible_at<=?) OR (state IN ('leased','running') AND lease_expires_at<?) ORDER BY requested_at,id LIMIT 1", (now, now)).fetchone()
    if row is None:
        conn.commit(); return None
    token = secrets.token_hex(24)
    cur = conn.execute("UPDATE stage77_report_jobs SET state='leased',attempt_count=attempt_count+1,lease_owner=?,lease_token=?,lease_acquired_at=?,lease_expires_at=?,heartbeat_at=?,maintenance_epoch=? WHERE id=? AND ((state IN ('queued','retry_wait') AND next_eligible_at<=?) OR (state IN ('leased','running') AND lease_expires_at<?))", (owner, token, now, _future(LEASE_SECONDS), now, maintenance_epoch, row["id"], now, now))
    if cur.rowcount != 1:
        conn.rollback(); return None
    event_type = "reclaimed" if row["state"] in {"leased", "running"} else "claimed"
    _event(conn, row["id"], event_type, "leased", owner, {"attempt": int(row["attempt_count"]) + 1})
    conn.commit()
    return _job(conn, row["id"])


def _future(seconds: int | float) -> str:
    return datetime.fromtimestamp(time.time() + seconds, timezone.utc).isoformat().replace("+00:00", "Z")


def heartbeat(conn, job_id: int | str, token: str) -> bool:
    from api.governed_report_recovery import recovery_status
    current = conn.execute("SELECT maintenance_epoch FROM stage77_report_jobs WHERE id=?", (int(job_id),)).fetchone()
    status = recovery_status(conn)
    if current is None or int(current[0] or 0) != int(status.get("maintenance_epoch", 0)) or bool(status.get("restore_validation_required")):
        conn.commit()
        return False
    cur = conn.execute("UPDATE stage77_report_jobs SET heartbeat_at=?,lease_expires_at=? WHERE id=? AND lease_token=? AND state IN ('leased','running')", (utc_now(), _future(LEASE_SECONDS), int(job_id), token))
    if cur.rowcount == 1:
        row = conn.execute("SELECT state FROM stage77_report_jobs WHERE id=?", (int(job_id),)).fetchone()
        _event(conn, int(job_id), "heartbeat", row[0], WORKER_IDENTITY)
    conn.commit()
    return cur.rowcount == 1


def _artifact_rows_valid(conn: sqlite3.Connection, version_id: int) -> bool:
    rows = conn.execute("SELECT storage_reference,sha256,size_bytes FROM record_governed_report_artifacts WHERE version_id=? AND validation_state='valid'", (version_id,)).fetchall()
    if not rows:
        return False
    for row in rows:
        path = Path(str(row["storage_reference"]))
        try:
            reports._assert_confined_output(reports.REPORT_ROOT, path)
        except (OSError, ValueError):
            return False
        if path.is_symlink() or not path.is_file():
            return False
        if path.stat().st_size != int(row["size_bytes"]):
            return False
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != row["sha256"]:
            return False
    return True


def reconcile_job_storage(conn: sqlite3.Connection, job: Mapping[str, Any]) -> bool:
    """Remove only attempt-owned staging and unregistered promoted output."""
    attempt_root = reports.REPORT_ROOT / ".stage77" / str(job["id"])
    try:
        reports._assert_confined_output(reports.REPORT_ROOT, attempt_root)
    except (OSError, ValueError):
        return False
    if attempt_root.is_symlink():
        return False
    if attempt_root.exists():
        for child in attempt_root.iterdir():
            if child.is_symlink():
                return False
            if child.is_dir():
                import shutil
                shutil.rmtree(child, ignore_errors=True)
    if job["state"] == "succeeded":
        return True
    version_id = int(job["report_version_id"])
    if conn.execute("SELECT 1 FROM record_governed_report_artifacts WHERE version_id=?", (version_id,)).fetchone():
        return True
    final_root = reports.REPORT_ROOT / str(job["report_id"])
    try:
        reports._assert_confined_output(reports.REPORT_ROOT, final_root)
    except (OSError, ValueError):
        return False
    if not final_root.exists():
        return True
    if final_root.is_symlink():
        return False
    for version_root in final_root.iterdir():
        if version_root.is_symlink():
            return False
        if not version_root.is_dir():
            continue
        for promoted in version_root.glob(f"job-{int(job['id'])}-attempt-*"):
            if promoted.is_symlink():
                return False
            if promoted.is_dir():
                import shutil
                shutil.rmtree(promoted, ignore_errors=True)
    return True


def _terminal(conn, job_id: int, token: str, state: str, actor: str, *, phase: str | None = None, code: str | None = None, diagnostic: Mapping[str, Any] | None = None) -> bool:
    allowed_states = "'cancel_requested'" if state == "cancelled" else "'leased','running'"
    cur = conn.execute(f"UPDATE stage77_report_jobs SET state=?,terminal_at=?,terminal_outcome=?,failure_phase=?,failure_code=? WHERE id=? AND lease_token=? AND state IN ({allowed_states})", (state, utc_now(), code or state, phase, code, job_id, token))
    if cur.rowcount != 1:
        conn.commit(); return False
    payload: dict[str, Any] = {"phase": phase, "code": code}
    if diagnostic is not None:
        payload["diagnostic"] = validate_diagnostic(diagnostic)
        payload.update(payload["diagnostic"])
    _event(conn, job_id, "terminal", state, actor, payload)
    conn.commit(); return True


def execute_job(db_path: str, job: Mapping[str, Any]) -> None:
    token = str(job["lease_token"])
    conn = _connect(db_path)
    heartbeat_stop = threading.Event()
    heartbeat_failed = threading.Event()

    def heartbeat_loop() -> None:
        while not heartbeat_stop.wait(HEARTBEAT_SECONDS):
            pulse = _connect(db_path)
            try:
                if not heartbeat(pulse, job["id"], token):
                    heartbeat_failed.set()
                    return
            finally:
                pulse.close()

    def execution_guard() -> bool:
        if heartbeat_failed.is_set():
            return False
        current = _connect(db_path)
        try:
            row = current.execute("SELECT state,cancellation_requested_at,lease_token FROM stage77_report_jobs WHERE id=?", (job["id"],)).fetchone()
            from api.governed_report_recovery import recovery_allows_finalize
            return bool(row and row["lease_token"] == token and row["state"] in {"leased", "running"} and not row["cancellation_requested_at"] and recovery_allows_finalize(current, int(job["id"]), token, int(job.get("maintenance_epoch", 0))))
        finally:
            current.close()

    heartbeat_thread = threading.Thread(target=heartbeat_loop, name="stage77-heartbeat", daemon=True)
    try:
        if not reconcile_job_storage(conn, job):
            _terminal(conn, job["id"], token, "failed_terminal", WORKER_IDENTITY, phase="revalidation", code="artifact_path_invalid", diagnostic=make_diagnostic(phase="revalidation", operation="generation_revalidation", checkpoint="starting", code="artifact_path_invalid"))
            return
        if not heartbeat(conn, job["id"], token): return
        cur = conn.execute("UPDATE stage77_report_jobs SET state='running' WHERE id=? AND lease_token=? AND state='leased'", (job["id"], token))
        if cur.rowcount != 1:
            conn.commit()
            return
        _event(conn, job["id"], "started", "running", WORKER_IDENTITY)
        conn.commit()
        heartbeat_thread.start()
        report = reports.get_report(conn, job["report_id"])
        if job.get("qualification_id") is not None:
            from api import governed_report_qualifications as qualification_store
            qualification = qualification_store.latest_final(conn, job["report_id"])
            if qualification is None or int(qualification["id"]) != int(job["qualification_id"]) or qualification["digest"] != job.get("qualification_digest"):
                _terminal(conn, job["id"], token, "failed_terminal", WORKER_IDENTITY, phase="revalidation", code="qualification_invalid", diagnostic=make_diagnostic(phase="revalidation", operation="generation_revalidation", checkpoint="validation", code="qualification_invalid"))
                return
            qualification_payload = qualification["payload"]
            if qualification_payload.get("specification_digest") != report["versions"][-1]["specification_digest"]:
                _terminal(conn, job["id"], token, "failed_terminal", WORKER_IDENTITY, phase="revalidation", code="qualification_specification_mismatch", diagnostic=make_diagnostic(phase="revalidation", operation="generation_revalidation", checkpoint="validation", code="qualification_specification_mismatch"))
                return
            if qualification_payload.get("review_mode") == qualification_store.SOLE_MODE:
                if qualification_payload.get("distribution_restriction") != "internal_working" or qualification_payload.get("disclosure_version") != qualification_store.DISCLOSURE_VERSION:
                    _terminal(conn, job["id"], token, "failed_terminal", WORKER_IDENTITY, phase="revalidation", code="qualification_distribution_invalid", diagnostic=make_diagnostic(phase="revalidation", operation="generation_revalidation", checkpoint="validation", code="qualification_distribution_invalid"))
                    return
            elif qualification_payload.get("review_mode") != qualification_store.INDEPENDENT_MODE or qualification_payload.get("disclosure_version") != "none":
                _terminal(conn, job["id"], token, "failed_terminal", WORKER_IDENTITY, phase="revalidation", code="qualification_mode_invalid", diagnostic=make_diagnostic(phase="revalidation", operation="generation_revalidation", checkpoint="validation", code="qualification_mode_invalid"))
                return
        if report["lifecycle_status"] not in {"approved_for_generation", "generation_requested"}:
            _terminal(conn, job["id"], token, "failed_terminal", WORKER_IDENTITY, phase="revalidation", code="report_lifecycle_invalid", diagnostic=make_diagnostic(phase="revalidation", operation="generation_revalidation", checkpoint="validation", code="report_lifecycle_invalid")); return
        version = report["versions"][-1]
        if int(version["id"]) != int(job["report_version_id"]):
            _terminal(conn, job["id"], token, "failed_terminal", WORKER_IDENTITY, phase="revalidation", code="report_version_superseded", diagnostic=make_diagnostic(phase="revalidation", operation="generation_revalidation", checkpoint="validation", code="report_version_superseded")); return
        if version["specification_digest"] != job["specification_digest"] or reports.specification_digest(version["specification"]) != job["specification_digest"]:
            _terminal(conn, job["id"], token, "failed_terminal", WORKER_IDENTITY, phase="revalidation", code="specification_digest_mismatch", diagnostic=make_diagnostic(phase="revalidation", operation="generation_revalidation", checkpoint="validation", code="specification_digest_mismatch")); return
        if conn.execute("SELECT cancellation_requested_at FROM stage77_report_jobs WHERE id=?", (job["id"],)).fetchone()[0]:
            _terminal(conn, job["id"], token, "cancelled", WORKER_IDENTITY, phase="cancellation", code="cancelled"); return
        attempt = int(job["attempt_count"])
        staging_dir = reports.REPORT_ROOT / ".stage77" / str(job["id"]) / str(attempt) / token
        promoted_dir = reports.REPORT_ROOT / str(job["report_id"]) / str(version["version_number"]) / f"job-{job['id']}-attempt-{attempt}"
        try:
            governance_qualification = None
            if job.get("qualification_id") is not None:
                from api import governed_report_qualifications as qualification_store
                qualification = qualification_store.latest_final(conn, job["report_id"])
                governance_qualification = dict(qualification["payload"])
                governance_qualification.update({"qualification_id": int(qualification["id"]), "qualification_digest": qualification["digest"], "disclosure": qualification_store.DISCLOSURE})
            reports.generate_report(conn, report_id=job["report_id"], actor=WORKER_IDENTITY, actor_role="system_worker", idempotency_key=f"stage77-job-{job['id']}", execution_guard=execution_guard, output_dir=staging_dir, promote_to=promoted_dir, _commit=False, finalization_transaction=True, governance_qualification=governance_qualification)
        except Exception as exc:
            if str(exc) == "governed_report_generation_cancelled":
                _terminal(conn, job["id"], token, "cancelled", WORKER_IDENTITY, phase="cancellation", code="cancelled")
                return
            if isinstance(exc, reports.GovernedReportGenerationFailure):
                diagnostic = exc.diagnostic
            elif callable(getattr(exc, "diagnostic_payload", None)):
                try:
                    diagnostic = validate_diagnostic(exc.diagnostic_payload())
                except Exception:
                    diagnostic = make_diagnostic(phase="job", operation="job_result_serialization", checkpoint="validation", code="adapter_return_contract_invalid", exception_category_value="contract_error")
            else:
                code = bounded_code(str(exc))
                if code == "unknown":
                    code = "governed_report_renderer_failed"
                diagnostic = make_diagnostic(phase="rendering", operation="renderer_invocation", checkpoint="entered", code=code, exc=exc)
            code = "governed_report_renderer_timeout" if diagnostic["failure_code"] == "governed_report_renderer_timeout" else "governed_report_renderer_failed"
            attempt = int(job["attempt_count"])
            if code in RETRYABLE_CODES and attempt < int(job["max_attempts"]):
                from api.governed_report_recovery import recovery_allows_finalize
                if recovery_allows_finalize(conn, int(job["id"]), token, int(job.get("maintenance_epoch", 0))):
                    conn.execute("UPDATE stage77_report_jobs SET state='retry_wait',next_eligible_at=?,failure_phase='rendering',failure_code=? WHERE id=? AND lease_token=?", (_future(2 ** attempt), code, job["id"], token)); _event(conn, job["id"], "retry_scheduled", "retry_wait", WORKER_IDENTITY, {"code": code, "diagnostic": validate_diagnostic(diagnostic)}); conn.commit()
                else:
                    conn.rollback()
            else:
                _terminal(conn, job["id"], token, "failed_terminal", WORKER_IDENTITY, phase="rendering", code=code, diagnostic=diagnostic)
            return
        if not _artifact_rows_valid(conn, int(job["report_version_id"])):
            _terminal(conn, job["id"], token, "failed_terminal", WORKER_IDENTITY, phase="validation", code="artifact_integrity_failed", diagnostic=make_diagnostic(phase="validation", operation="artifact_integrity", checkpoint="validation", code="artifact_integrity_failed"))
            return
        _terminal(conn, job["id"], token, "succeeded", WORKER_IDENTITY, phase="rendering", code="completed")
    finally:
        heartbeat_stop.set()
        if heartbeat_thread.is_alive():
            heartbeat_thread.join(timeout=2)
        conn.close()


def worker_loop(db_path: str, stop_event, on_ready=None) -> int:
    startup_conn = None
    try:
        last_error = None
        for attempt in range(5):
            try:
                startup_conn = _connect(db_path)
                ensure_job_tables(startup_conn)
                reports.ensure_report_tables(startup_conn)
                from api.governed_report_recovery import ensure_recovery_tables, recovery_status
                ensure_recovery_tables(startup_conn)
                recovery_status(startup_conn)
                last_error = None
                break
            except Exception as exc:
                last_error = exc
                if attempt == 4:
                    raise
                if startup_conn is not None:
                    startup_conn.close()
                    startup_conn = None
                time.sleep(0.05 * (attempt + 1))
        if last_error is not None:
            raise last_error
        if on_ready is not None:
            on_ready()
    except ValueError as exc:
        code = "stage75_schema_incompatible" if str(exc) == "stage75_schema_incompatible" else "initialization_failed"
        print(f"stage77_worker=startup_failure code={code}", flush=True)
        return 1
    except Exception:
        print("stage77_worker=startup_failure code=initialization_failed", flush=True)
        return 1
    finally:
        if startup_conn is not None:
            startup_conn.close()
    while not stop_event.is_set():
        conn = _connect(db_path)
        try:
            job = claim_one(conn)
        except sqlite3.OperationalError as exc:
            if "locked" in str(exc).lower() or "busy" in str(exc).lower():
                job = None
            else:
                print("stage77_worker=database_unavailable", flush=True)
                return 1
        finally:
            conn.close()
        if job:
            try:
                execute_job(db_path, job)
            except Exception:
                print("stage77_worker=execution_failure", flush=True)
                return 1
        else:
            stop_event.wait(1)
    return 0
