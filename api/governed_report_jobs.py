"""Stage 77 durable operational queue for existing governed reports.

This module owns scheduling, leases and bounded execution state. Stage 75
continues to own report specifications, lifecycle and artifact records.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from api import record_governed_reports as reports
from api.governed_report_diagnostics import (
    bounded_code,
    make_diagnostic,
    select_diagnostic_contract,
    validate_diagnostic,
)

JOB_SCHEMA_VERSION = "stage77.governed_report_job.v1"
WORKER_IDENTITY = "cde-governed-report-worker"
JOB_STATES = {"queued", "leased", "running", "retry_wait", "cancel_requested", "succeeded", "failed_terminal", "cancelled"}
TERMINAL_STATES = {"succeeded", "failed_terminal", "cancelled"}
RETRYABLE_CODES = {"sqlite_busy", "worker_interrupted"}
MAX_ATTEMPTS = 3
LEASE_SECONDS = 180
HEARTBEAT_SECONDS = 20
BUSY_TIMEOUT_MS = 5000

DIAGNOSTIC_RETRY_KIND = "diagnostic_retry"
DIAGNOSTIC_RETRY_ACTION = "authorize_diagnostic_retry"
DIAGNOSTIC_RETRY_EVENT = "diagnostic_retry_enqueued"
DIAGNOSTIC_RETRY_REPORT_EVENT = "diagnostic_retry_authorized"
DIAGNOSTIC_RETRY_PROTOCOL_VERSION = "stage77-bounded-diagnostics-v1"
DIAGNOSTIC_RETRY_DECLARATION_VERSION = "stage77-diagnostic-retry-v1"
DIAGNOSTIC_RETRY_DECLARATION = (
    "I confirm that this action authorizes one diagnostic retry of the preserved "
    "failed generation job. It does not reapprove or alter the frozen report "
    "specification, does not erase the original failure, does not publish the "
    "report, and does not permit an additional retry."
)
DIAGNOSTIC_RETRY_FAILURE_CODE = "governed_report_renderer_failed"
POST_CORRECTION_ACTION = "post_correction_generation"
POST_CORRECTION_EVENT = "post_correction_generation_enqueued"
POST_CORRECTION_AUTH_EVENT = "post_correction_generation_authorized"
POST_CORRECTION_CONTRACT = "stage77.post_correction_generation_authorization.v1"
POST_CORRECTION_MAX_RATIONALE = 4000
POST_CORRECTION_DECLARATION = (
    "I authorize one execution of the unchanged frozen specification under the "
    "deployed adapter correction. Jobs 1 and 2 remain immutable. I attest to the "
    "external Custody Point 6 archive and receipt digests. This action is not "
    "approval or publication and permits no further retry or execution."
)
POST_CORRECTION_REVISION = "fc9af82946905ea93b26d9d6291c8160b23b9d1d"
POST_CORRECTION_DEPLOYMENT = "3ee7e469-cb77-4d42-9d74-540ba4b25b46"
POST_CORRECTION_RECOVERY_POINT = "71f4471e987ef38d1bdbd1b64dd7557b"
POST_CORRECTION_RECOVERY_CONTRACT = "stage77.diagnostic_aware.v1"
POST_CORRECTION_MANIFEST_DIGEST = "bddaa565d774188e89c3911f44dcdda615a04b302b744a266cf291189f4a1a1d"
POST_CORRECTION_DATABASE_DIGEST = "93d8ece126d9f1410b7fc5e888710c93575299d18ef1724c72534228185407b8"
POST_CORRECTION_ARCHIVE_DIGEST = "961991089f669ae28bfa974e69181788ced54e24f419229b0428ab0185fbc35b"
POST_CORRECTION_RECEIPT_DIGEST = "6026b9907a6c7ae71957208db0f5b38aab0a6cbc66ea1ea73c0a60384b1c82e8"
DIAGNOSTIC_RETRY_MAX_RATIONALE = 4000
NON_ADMIN_IDENTITIES = {WORKER_IDENTITY, "automation", "codex", "system", "system_worker", "worker"}


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
      post_correction_authorization_id TEXT,
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
    CREATE UNIQUE INDEX IF NOT EXISTS idx_stage77_jobs_retry_predecessor
        ON stage77_report_jobs(retry_of_job_id) WHERE retry_of_job_id IS NOT NULL;
    """)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(stage77_report_jobs)").fetchall()}
    if "maintenance_epoch" not in columns:
        conn.execute("ALTER TABLE stage77_report_jobs ADD COLUMN maintenance_epoch INTEGER NOT NULL DEFAULT 0")
    if "qualification_id" not in columns:
        conn.execute("ALTER TABLE stage77_report_jobs ADD COLUMN qualification_id INTEGER")
    if "qualification_digest" not in columns:
        conn.execute("ALTER TABLE stage77_report_jobs ADD COLUMN qualification_digest TEXT")
    if "post_correction_authorization_id" not in columns:
        conn.execute("ALTER TABLE stage77_report_jobs ADD COLUMN post_correction_authorization_id TEXT")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_stage77_jobs_post_correction_authorization ON stage77_report_jobs(post_correction_authorization_id) WHERE post_correction_authorization_id IS NOT NULL")


def ensure_post_correction_tables(conn: sqlite3.Connection) -> None:
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS stage77_post_correction_authorizations (
      id TEXT PRIMARY KEY,
      report_id INTEGER NOT NULL,
      report_version_id INTEGER NOT NULL,
      qualification_id INTEGER NOT NULL,
      job1_id INTEGER NOT NULL,
      job2_id INTEGER NOT NULL,
      state TEXT NOT NULL CHECK(state IN ('authorized','consumed')),
      idempotency_key TEXT NOT NULL UNIQUE,
      payload_json TEXT NOT NULL,
      authorization_digest TEXT NOT NULL,
      created_at TEXT NOT NULL,
      consumed_at TEXT,
      FOREIGN KEY(report_id) REFERENCES record_governed_reports(id),
      FOREIGN KEY(report_version_id) REFERENCES record_governed_report_versions(id),
      FOREIGN KEY(qualification_id) REFERENCES record_governed_report_qualifications(id),
      FOREIGN KEY(job1_id) REFERENCES stage77_report_jobs(id),
      FOREIGN KEY(job2_id) REFERENCES stage77_report_jobs(id)
    );
    CREATE UNIQUE INDEX IF NOT EXISTS idx_stage77_post_correction_report
      ON stage77_post_correction_authorizations(report_id, report_version_id);
    CREATE UNIQUE INDEX IF NOT EXISTS idx_stage77_post_correction_idempotency
      ON stage77_post_correction_authorizations(idempotency_key);
    CREATE TABLE IF NOT EXISTS stage77_post_correction_execution_links (
      authorization_id TEXT PRIMARY KEY,
      job_id INTEGER NOT NULL UNIQUE,
      created_at TEXT NOT NULL,
      FOREIGN KEY(authorization_id) REFERENCES stage77_post_correction_authorizations(id),
      FOREIGN KEY(job_id) REFERENCES stage77_report_jobs(id)
    );
    CREATE UNIQUE INDEX IF NOT EXISTS idx_stage77_post_correction_job
      ON stage77_post_correction_execution_links(job_id);
    """)


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
    if original.get("retry_of_job_id") is not None or original.get("post_correction_authorization_id") is not None:
        raise ValueError("governed_report_job_retry_of_retry_forbidden")
    return enqueue_generation(conn, report_id=original["report_id"], actor=actor, governed_action="retry_generation", idempotency_key=f"stage77-retry-{int(job_id)}", retry_of_job_id=int(job_id))


def _post_correction_runtime_identity() -> tuple[str, str]:
    revision = str(os.getenv("RAILWAY_GIT_COMMIT_SHA") or os.getenv("CDE_DEPLOYED_REVISION") or "").strip()
    deployment = str(os.getenv("RAILWAY_DEPLOYMENT_ID") or os.getenv("CDE_DEPLOYMENT_ID") or "").strip()
    if not re.fullmatch(r"[0-9a-f]{40}", revision) or not re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", deployment):
        raise ValueError("governed_report_post_correction_runtime_identity_invalid")
    if revision != POST_CORRECTION_REVISION or deployment != POST_CORRECTION_DEPLOYMENT:
        raise ValueError("governed_report_post_correction_runtime_identity_mismatch")
    return revision, deployment


def _post_correction_sha(value: Any, code: str) -> str:
    value = str(value or "")
    if not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError(code)
    return value


def _post_correction_authorization_payload(*, report, qualification, job1, job2, execution_job_id, evidence1, evidence2, topology_digest, actor, rationale, declaration, idempotency_key, custody_archive_digest, custody_receipt_digest, created_at):
    revision, deployment = _post_correction_runtime_identity()
    version = report["versions"][-1]
    payload = {
        "authorization_contract": POST_CORRECTION_CONTRACT,
        "report_id": int(report["id"]), "report_version_id": int(version["id"]),
        "specification_digest": str(version["specification_digest"]),
        "qualification_id": int(qualification["id"]), "qualification_digest": str(qualification["digest"]),
        "qualification_chain_digest": str(qualification.get("chain_digest") or qualification["digest"]),
        "review_mode": str(qualification["payload"]["review_mode"]),
        "disclosure_version": str(qualification["payload"]["disclosure_version"]),
        "distribution_restriction": str(qualification["payload"]["distribution_restriction"]),
        "job1_id": int(job1["id"]), "job1_state": str(job1["state"]), "job1_contract": str(evidence1["contract_id"]),
        "job1_stage75_sha256": str(evidence1["attempt_sha256"]), "job1_stage77_sha256": str(evidence1["terminal_sha256"]),
        "job2_id": int(job2["id"]), "job2_state": str(job2["state"]), "job2_contract": str(evidence2["contract_id"]),
        "job2_stage75_sha256": str(evidence2["attempt_sha256"]), "job2_stage77_sha256": str(evidence2["terminal_sha256"]),
        "execution_job_id": int(execution_job_id),
        "retry_topology": {"successor_job_id": int(job2["id"]), "predecessor_job_id": int(job1["id"])},
        "retry_topology_digest": str(topology_digest),
        "correction_revision": revision, "correction_deployment": deployment,
        "recovery_point_id": POST_CORRECTION_RECOVERY_POINT, "recovery_contract": POST_CORRECTION_RECOVERY_CONTRACT,
        "recovery_manifest_digest": POST_CORRECTION_MANIFEST_DIGEST, "recovery_database_digest": POST_CORRECTION_DATABASE_DIGEST,
        "custody_archive_digest": _post_correction_sha(custody_archive_digest, "governed_report_post_correction_archive_digest_invalid"),
        "custody_receipt_digest": _post_correction_sha(custody_receipt_digest, "governed_report_post_correction_receipt_digest_invalid"),
        "requesting_actor": str(actor), "rationale": str(rationale), "declaration": dict(declaration),
        "idempotency_key": str(idempotency_key), "created_at": str(created_at),
    }
    payload["authorization_digest"] = hashlib.sha256(reports.canonical_json(payload).encode()).hexdigest()
    return payload


def _post_correction_topology(conn: sqlite3.Connection, report_id: int, version_id: int):
    rows = conn.execute("SELECT * FROM stage77_report_jobs WHERE report_id=? AND report_version_id=? ORDER BY id", (report_id, version_id)).fetchall()
    if len(rows) != 2:
        raise ValueError("governed_report_post_correction_job_topology_invalid")
    jobs = [dict(row) for row in rows]
    predecessors = [row for row in jobs if row["retry_of_job_id"] is None]
    successors = [row for row in jobs if row["retry_of_job_id"] is not None]
    if len(predecessors) != 1 or len(successors) != 1 or int(successors[0]["retry_of_job_id"]) != int(predecessors[0]["id"]):
        raise ValueError("governed_report_post_correction_job_topology_invalid")
    if any(row["state"] != "failed_terminal" for row in jobs) or successors[0]["governed_action"] != DIAGNOSTIC_RETRY_ACTION:
        raise ValueError("governed_report_post_correction_job_state_invalid")
    topology = reports.canonical_json({"report_id": report_id, "report_version_id": version_id, "links": [{"predecessor_job_id": int(predecessors[0]["id"]), "successor_job_id": int(successors[0]["id"])}]})
    return predecessors[0], successors[0], hashlib.sha256(topology.encode()).hexdigest()


def authorize_post_correction_generation(conn: sqlite3.Connection, *, report_id: int | str, actor: str, actor_role: str, rationale: str, acknowledged: bool, custody_archive_digest: str, custody_receipt_digest: str, idempotency_key: str) -> dict[str, Any]:
    reports.ensure_report_tables(conn); ensure_job_tables(conn); ensure_post_correction_tables(conn)
    if str(actor_role) != "admin" or str(actor).strip() in NON_ADMIN_IDENTITIES:
        raise ValueError("governed_report_post_correction_actor_invalid")
    rationale = str(rationale or "").strip(); key = str(idempotency_key or "").strip()
    if not rationale or len(rationale) > POST_CORRECTION_MAX_RATIONALE: raise ValueError("governed_report_post_correction_rationale_invalid")
    if acknowledged is not True: raise ValueError("governed_report_post_correction_declaration_required")
    if not key: raise ValueError("governed_report_post_correction_idempotency_required")
    declaration = {"acknowledged": True, "version": 1, "text": POST_CORRECTION_DECLARATION}
    conn.execute("BEGIN IMMEDIATE")
    try:
        existing = conn.execute("SELECT * FROM stage77_post_correction_authorizations WHERE idempotency_key=?", (key,)).fetchone()
        if existing:
            if existing["state"] != "authorized": raise ValueError("governed_report_post_correction_already_consumed")
            payload = json.loads(existing["payload_json"])
            if payload.get("rationale") != rationale or payload.get("custody_archive_digest") != custody_archive_digest or payload.get("custody_receipt_digest") != custody_receipt_digest:
                raise ValueError("governed_report_post_correction_idempotency_conflict")
            linked = conn.execute("SELECT job_id FROM stage77_post_correction_execution_links WHERE authorization_id=?", (existing["id"],)).fetchone()
            conn.commit(); return _job(conn, int(linked[0])) if linked else dict(existing)
        report = reports.get_report(conn, report_id)
        if report["lifecycle_status"] != "validation_failed": raise ValueError("governed_report_post_correction_lifecycle_invalid")
        version = report["versions"][-1]
        from api import governed_report_qualifications as qualification_store
        qualification = qualification_store.latest_final(conn, report_id)
        if qualification is None or qualification["payload"].get("review_mode") != qualification_store.SOLE_MODE or qualification["payload"].get("disclosure_version") != qualification_store.DISCLOSURE_VERSION or qualification["payload"].get("distribution_restriction") != "internal_working":
            raise ValueError("governed_report_post_correction_qualification_invalid")
        chain = qualification_store.validate_qualification_chain(conn, int(version["id"]))
        qualification = dict(qualification); qualification["chain"] = chain; qualification["chain_digest"] = hashlib.sha256(reports.canonical_json([dict(item) for item in chain]).encode()).hexdigest()
        if reports.specification_digest(version["specification"]) != version["specification_digest"]: raise ValueError("governed_report_post_correction_specification_invalid")
        from api.governed_report_recovery import recovery_allows_claim, recovery_status
        status = recovery_status(conn)
        if status.get("state") != "completed" or status.get("recovery_point_id") != POST_CORRECTION_RECOVERY_POINT or status.get("manifest_digest") != POST_CORRECTION_MANIFEST_DIGEST or not recovery_allows_claim(conn): raise ValueError("governed_report_post_correction_recovery_invalid")
        job1, job2, topology_digest = _post_correction_topology(conn, int(report["id"]), int(version["id"]))
        evidence1 = _validate_diagnostic_retry_predecessor_evidence(conn, job1)
        evidence2 = _validate_diagnostic_retry_predecessor_evidence(conn, job2)
        if evidence1["contract_id"] != "legacy_pre_propagation_diagnostic_contract_v1" or evidence2["contract_id"] != "current_pre_terminal_projection_fix_diagnostic_contract_v1": raise ValueError("governed_report_post_correction_diagnostic_invalid")
        if (evidence1["attempt_sha256"], evidence1["terminal_sha256"], evidence2["attempt_sha256"], evidence2["terminal_sha256"]) != ("f5fa57e6989a8406c99bd3c26b877694515f44af74426684fbcc18a0268abd63", "f7456646b23f037b18af45f5019d5c817b54649cf28da14eecdf838817495239", "6f83de150d27070d4aaf1aac040e18220968f440962ab47d935d39a33dd7fc67", "d62fa6f366270dcb0f3cedf973299d55f3ae0c671b70ea63907c7e378f0b6601"):
            raise ValueError("governed_report_post_correction_diagnostic_hash_invalid")
        if custody_archive_digest != POST_CORRECTION_ARCHIVE_DIGEST or custody_receipt_digest != POST_CORRECTION_RECEIPT_DIGEST:
            raise ValueError("governed_report_post_correction_custody_attestation_invalid")
        if conn.execute("SELECT COUNT(*) FROM stage77_report_jobs WHERE state IN ('queued','leased','running','retry_wait','cancel_requested')").fetchone()[0] != 0 or conn.execute("SELECT COUNT(*) FROM record_governed_report_artifacts WHERE version_id=?", (version["id"],)).fetchone()[0] != 0: raise ValueError("governed_report_post_correction_active_work_exists")
        now = utc_now()
        auth_id = secrets.token_hex(16)
        cur = conn.execute("INSERT INTO stage77_report_jobs(report_id,report_version_id,specification_digest,requested_formats_json,rendering_profile,template_version,publication_engine_version,requesting_actor,governed_action,qualification_id,qualification_digest,requested_at,state,attempt_count,max_attempts,next_eligible_at,idempotency_key,retry_of_job_id,post_correction_authorization_id,maintenance_epoch,schema_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (int(report["id"]), int(version["id"]), version["specification_digest"], reports.canonical_json(version["specification"]["requested_formats"]), version["specification"]["rendering_profile"], version["specification"]["template_version"], version["specification"]["publication_engine_version"], actor, POST_CORRECTION_ACTION, qualification["id"], qualification["digest"], now, "queued", 0, MAX_ATTEMPTS, now, "stage77-post-correction-" + auth_id, None, auth_id, int(status.get("maintenance_epoch", 0)), JOB_SCHEMA_VERSION))
        job_id = int(cur.lastrowid)
        payload = _post_correction_authorization_payload(report=report, qualification=qualification, job1=job1, job2=job2, execution_job_id=job_id, evidence1=evidence1, evidence2=evidence2, topology_digest=topology_digest, actor=actor, rationale=rationale, declaration=declaration, idempotency_key=key, custody_archive_digest=custody_archive_digest, custody_receipt_digest=custody_receipt_digest, created_at=now)
        conn.execute("INSERT INTO stage77_post_correction_authorizations(id,report_id,report_version_id,qualification_id,job1_id,job2_id,state,idempotency_key,payload_json,authorization_digest,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)", (auth_id, int(report["id"]), int(version["id"]), int(qualification["id"]), int(job1["id"]), int(job2["id"]), "authorized", key, reports.canonical_json(payload), payload["authorization_digest"], now))
        conn.execute("INSERT INTO stage77_post_correction_execution_links(authorization_id,job_id,created_at) VALUES(?,?,?)", (auth_id, job_id, now))
        _event(conn, job_id, POST_CORRECTION_EVENT, "queued", actor, payload)
        conn.execute("INSERT INTO record_governed_report_events(report_id,version_id,event_type,resulting_status,rationale,actor,actor_role,declaration_json,occurred_at,idempotency_key,request_payload_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)", (int(report["id"]), int(version["id"]), POST_CORRECTION_AUTH_EVENT, "validation_failed", rationale, actor, actor_role, reports.canonical_json(declaration), now, key + ":report", reports.canonical_json(payload)))
        conn.commit()
    except Exception:
        conn.rollback(); raise
    return _job(conn, job_id)


def _revalidate_post_correction_job(conn: sqlite3.Connection, job: Mapping[str, Any], report: Mapping[str, Any]) -> None:
    if job.get("governed_action") != POST_CORRECTION_ACTION or not job.get("post_correction_authorization_id") or job.get("retry_of_job_id") is not None:
        raise ValueError("governed_report_post_correction_job_invalid")
    row = conn.execute("SELECT * FROM stage77_post_correction_authorizations WHERE id=?", (job["post_correction_authorization_id"],)).fetchone()
    link = conn.execute("SELECT job_id FROM stage77_post_correction_execution_links WHERE authorization_id=?", (job["post_correction_authorization_id"],)).fetchone()
    if row is None or link is None or int(link[0]) != int(job["id"]) or row["state"] != "authorized": raise ValueError("governed_report_post_correction_authorization_invalid")
    payload = json.loads(row["payload_json"])
    if hashlib.sha256(reports.canonical_json({k: v for k, v in payload.items() if k != "authorization_digest"}).encode()).hexdigest() != row["authorization_digest"] or payload.get("authorization_digest") != row["authorization_digest"]:
        raise ValueError("governed_report_post_correction_authorization_digest_invalid")
    if payload.get("declaration") != {"acknowledged": True, "version": 1, "text": POST_CORRECTION_DECLARATION} or payload.get("correction_revision") != POST_CORRECTION_REVISION or payload.get("correction_deployment") != POST_CORRECTION_DEPLOYMENT or payload.get("recovery_point_id") != POST_CORRECTION_RECOVERY_POINT or payload.get("recovery_contract") != POST_CORRECTION_RECOVERY_CONTRACT: raise ValueError("governed_report_post_correction_revalidation_invalid")
    if payload.get("execution_job_id") != int(job["id"]): raise ValueError("governed_report_post_correction_revalidation_invalid")
    if report["lifecycle_status"] != "validation_failed" or int(payload["report_version_id"]) != int(job["report_version_id"]) or payload["specification_digest"] != job["specification_digest"] or payload.get("qualification_id") != int(job["qualification_id"]) or payload.get("qualification_digest") != job["qualification_digest"]: raise ValueError("governed_report_post_correction_revalidation_invalid")
    from api.governed_report_recovery import recovery_allows_claim
    if not recovery_allows_claim(conn): raise ValueError("governed_report_post_correction_maintenance_active")


def _diagnostic_retry_payload(
    *,
    predecessor: Mapping[str, Any],
    report: Mapping[str, Any],
    qualification: Mapping[str, Any],
    actor: str,
    rationale: str,
    diagnostic_contract: Mapping[str, Any],
    authorized_at: str | None = None,
    successor_job_id: int | None = None,
) -> dict[str, Any]:
    version = report["versions"][-1]
    return {
        "retry_kind": DIAGNOSTIC_RETRY_KIND,
        "predecessor_job_id": int(predecessor["id"]),
        "successor_job_id": None if successor_job_id is None else int(successor_job_id),
        "report_id": int(report["id"]),
        "report_version_id": int(version["id"]),
        "specification_digest": str(version["specification_digest"]),
        "qualification_id": int(qualification["id"]),
        "qualification_digest": str(qualification["digest"]),
        "requesting_actor": str(actor),
        "governed_action": DIAGNOSTIC_RETRY_ACTION,
        "diagnostic_protocol_version": DIAGNOSTIC_RETRY_PROTOCOL_VERSION,
        "declaration_version": DIAGNOSTIC_RETRY_DECLARATION_VERSION,
        "declaration": DIAGNOSTIC_RETRY_DECLARATION,
        "rationale": str(rationale),
        "predecessor_failure_phase": str(predecessor["failure_phase"]),
        "predecessor_failure_code": str(predecessor["failure_code"]),
        "diagnostic_contract_id": str(diagnostic_contract["contract_id"]),
        "predecessor_attempt_diagnostic_sha256": str(diagnostic_contract["attempt_sha256"]),
        "predecessor_terminal_diagnostic_sha256": str(diagnostic_contract["terminal_sha256"]),
        "authorized_at": authorized_at,
    }


def _validate_diagnostic_retry_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    expected = {
        "retry_kind", "predecessor_job_id", "successor_job_id", "report_id", "report_version_id",
        "specification_digest", "qualification_id", "qualification_digest", "requesting_actor",
        "governed_action", "diagnostic_protocol_version", "declaration_version", "declaration",
        "rationale", "predecessor_failure_phase", "predecessor_failure_code", "authorized_at",
        "diagnostic_contract_id", "predecessor_attempt_diagnostic_sha256", "predecessor_terminal_diagnostic_sha256",
    }
    if not isinstance(payload, Mapping) or set(payload) != expected:
        raise ValueError("governed_report_diagnostic_retry_contract_invalid")
    if payload["retry_kind"] != DIAGNOSTIC_RETRY_KIND or payload["governed_action"] != DIAGNOSTIC_RETRY_ACTION:
        raise ValueError("governed_report_diagnostic_retry_contract_invalid")
    if payload["diagnostic_protocol_version"] != DIAGNOSTIC_RETRY_PROTOCOL_VERSION or payload["declaration_version"] != DIAGNOSTIC_RETRY_DECLARATION_VERSION:
        raise ValueError("governed_report_diagnostic_retry_protocol_invalid")
    if payload["declaration"] != DIAGNOSTIC_RETRY_DECLARATION or not isinstance(payload["rationale"], str) or not payload["rationale"].strip() or len(payload["rationale"]) > DIAGNOSTIC_RETRY_MAX_RATIONALE:
        raise ValueError("governed_report_diagnostic_retry_declaration_invalid")
    for name in ("predecessor_job_id", "report_id", "report_version_id", "qualification_id"):
        if isinstance(payload[name], bool) or not isinstance(payload[name], int) or payload[name] <= 0:
            raise ValueError("governed_report_diagnostic_retry_contract_invalid")
    if payload["successor_job_id"] is not None and (isinstance(payload["successor_job_id"], bool) or not isinstance(payload["successor_job_id"], int) or payload["successor_job_id"] <= 0):
        raise ValueError("governed_report_diagnostic_retry_contract_invalid")
    for name in ("specification_digest", "qualification_digest", "requesting_actor", "authorized_at"):
        if not isinstance(payload[name], str) or not payload[name].strip():
            raise ValueError("governed_report_diagnostic_retry_contract_invalid")
    if payload["diagnostic_contract_id"] not in {
        "current_diagnostic_contract_v1",
        "legacy_pre_propagation_diagnostic_contract_v1",
    }:
        raise ValueError("governed_report_diagnostic_retry_contract_invalid")
    for name in ("predecessor_attempt_diagnostic_sha256", "predecessor_terminal_diagnostic_sha256"):
        if not isinstance(payload[name], str) or not re.fullmatch(r"[0-9a-f]{64}", payload[name]):
            raise ValueError("governed_report_diagnostic_retry_contract_invalid")
    if payload["predecessor_failure_phase"] != "rendering" or payload["predecessor_failure_code"] != DIAGNOSTIC_RETRY_FAILURE_CODE:
        raise ValueError("governed_report_diagnostic_retry_predecessor_invalid")
    return dict(payload)


def _diagnostic_retry_identity(payload: Mapping[str, Any]) -> dict[str, Any]:
    value = dict(payload)
    value.pop("authorized_at", None)
    value.pop("successor_job_id", None)
    return value


def _diagnostic_retry_event_payload(conn: sqlite3.Connection, job_id: int) -> dict[str, Any]:
    row = conn.execute(
        "SELECT payload_json FROM stage77_report_job_events WHERE job_id=? AND event_type=? ORDER BY id DESC LIMIT 1",
        (int(job_id), DIAGNOSTIC_RETRY_EVENT),
    ).fetchone()
    if row is None:
        raise ValueError("governed_report_diagnostic_retry_event_missing")
    try:
        payload = json.loads(row[0])
    except (TypeError, ValueError, json.JSONDecodeError):
        raise ValueError("governed_report_diagnostic_retry_contract_invalid") from None
    return _validate_diagnostic_retry_payload(payload)


def _validate_diagnostic_retry_predecessor_evidence(conn: sqlite3.Connection, predecessor: Mapping[str, Any]) -> dict[str, Any]:
    """Require the complete Stage 75 and Stage 77 bounded failure evidence."""
    attempt = conn.execute(
        "SELECT result,diagnostics_json FROM record_governed_report_generation_attempts "
        "WHERE version_id=? AND idempotency_key=? ORDER BY id DESC LIMIT 1",
        (int(predecessor["report_version_id"]), f"stage77-job-{int(predecessor['id'])}"),
    ).fetchone()
    if attempt is None or attempt["result"] != "validation_failed":
        raise ValueError("governed_report_diagnostic_retry_predecessor_invalid")
    terminal = conn.execute(
        "SELECT payload_json FROM stage77_report_job_events "
        "WHERE job_id=? AND event_type='terminal' AND resulting_state='failed_terminal' "
        "ORDER BY id DESC LIMIT 1",
        (int(predecessor["id"]),),
    ).fetchone()
    if terminal is None:
        raise ValueError("governed_report_diagnostic_retry_predecessor_invalid")
    try:
        contract = select_diagnostic_contract(
            attempt_raw=str(attempt["diagnostics_json"]),
            terminal_raw=str(terminal["payload_json"]),
        )
    except (TypeError, ValueError, json.JSONDecodeError):
        raise ValueError("governed_report_diagnostic_retry_diagnostic_invalid") from None
    if contract["contract_id"] == "current_diagnostic_contract_v1":
        terminal_payload = json.loads(terminal["payload_json"])
        if terminal_payload.get("phase") != "rendering" or terminal_payload.get("code") != DIAGNOSTIC_RETRY_FAILURE_CODE:
            raise ValueError("governed_report_diagnostic_retry_diagnostic_mismatch")
    return contract


def _diagnostic_retry_report_and_qualification(conn: sqlite3.Connection, predecessor: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    report = reports.get_report(conn, int(predecessor["report_id"]))
    if report["lifecycle_status"] != "validation_failed":
        raise ValueError("governed_report_diagnostic_retry_lifecycle_invalid")
    version = report["versions"][-1]
    if int(version["id"]) != int(predecessor["report_version_id"]):
        raise ValueError("governed_report_diagnostic_retry_version_invalid")
    if version["specification_digest"] != predecessor["specification_digest"] or reports.specification_digest(version["specification"]) != predecessor["specification_digest"]:
        raise ValueError("governed_report_diagnostic_retry_specification_invalid")
    if version["specification"].get("distribution_class") != "internal_working":
        raise ValueError("governed_report_diagnostic_retry_distribution_invalid")
    if (list(predecessor["requested_formats"]) != list(version["requested_formats"])
            or predecessor["rendering_profile"] != version["rendering_profile"]
            or predecessor["template_version"] != version["template_version"]
            or predecessor["publication_engine_version"] != version["publication_engine_version"]):
        raise ValueError("governed_report_diagnostic_retry_contract_invalid")
    from api import governed_report_qualifications as qualification_store
    qualification = qualification_store.latest_final(conn, int(predecessor["report_id"]))
    if qualification is None or int(qualification["id"]) != int(predecessor["qualification_id"] or 0) or qualification["digest"] != predecessor["qualification_digest"]:
        raise ValueError("governed_report_diagnostic_retry_qualification_invalid")
    qualification_payload = qualification["payload"]
    if (qualification_payload.get("review_mode") != qualification_store.SOLE_MODE
            or qualification_payload.get("distribution_restriction") != "internal_working"
            or qualification_payload.get("disclosure_version") != qualification_store.DISCLOSURE_VERSION):
        raise ValueError("governed_report_diagnostic_retry_qualification_invalid")
    reports._validate_generation_sources(conn, version["specification"])
    if report["artifacts"]:
        raise ValueError("governed_report_diagnostic_retry_artifacts_exist")
    promoted_root = reports.REPORT_ROOT / str(report["id"]) / str(version["version_number"])
    reports._assert_confined_output(reports.REPORT_ROOT, promoted_root)
    if promoted_root.exists():
        raise ValueError("governed_report_diagnostic_retry_promoted_output_exists")
    return report, qualification


def _eligible_diagnostic_retry(conn: sqlite3.Connection, predecessor_job_id: int, actor: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    if not str(actor or "").strip() or str(actor).strip().lower() in NON_ADMIN_IDENTITIES:
        raise ValueError("governed_report_diagnostic_retry_actor_invalid")
    predecessor = _job(conn, int(predecessor_job_id))
    if predecessor["state"] != "failed_terminal" or predecessor.get("retry_of_job_id") is not None or predecessor.get("governed_action") != "enqueue_generation":
        raise ValueError("governed_report_diagnostic_retry_predecessor_invalid")
    if predecessor.get("failure_phase") != "rendering" or predecessor.get("failure_code") != DIAGNOSTIC_RETRY_FAILURE_CODE or predecessor.get("failure_code") in RETRYABLE_CODES:
        raise ValueError("governed_report_diagnostic_retry_predecessor_invalid")
    diagnostic_contract = _validate_diagnostic_retry_predecessor_evidence(conn, predecessor)
    if conn.execute("SELECT 1 FROM stage77_report_jobs WHERE retry_of_job_id=?", (int(predecessor_job_id),)).fetchone() is not None:
        raise ValueError("governed_report_diagnostic_retry_successor_exists")
    active = conn.execute("SELECT 1 FROM stage77_report_jobs WHERE report_id=? AND report_version_id=? AND state IN ('queued','leased','running','retry_wait','cancel_requested')", (int(predecessor["report_id"]), int(predecessor["report_version_id"]))).fetchone()
    if active is not None:
        raise ValueError("governed_report_diagnostic_retry_active_job_exists")
    from api import governed_report_recovery as recovery
    if not recovery.recovery_allows_claim(conn):
        raise ValueError("governed_report_diagnostic_retry_maintenance_active")
    report, qualification = _diagnostic_retry_report_and_qualification(conn, predecessor)
    return predecessor, report, qualification, diagnostic_contract


def diagnostic_retry_candidate(conn: sqlite3.Connection, report_id: int | str, actor: str) -> dict[str, Any] | None:
    """Return only bounded UI evidence when the full retry contract is eligible."""
    for row in conn.execute("SELECT id FROM stage77_report_jobs WHERE report_id=? ORDER BY id", (int(report_id),)).fetchall():
        try:
            predecessor, _, _, _ = _eligible_diagnostic_retry(conn, int(row[0]), actor)
        except (ValueError, TypeError, sqlite3.Error):
            continue
        return {"job_id": int(predecessor["id"]), "failure_phase": predecessor["failure_phase"], "failure_code": predecessor["failure_code"], "attempt_count": int(predecessor["attempt_count"]), "max_attempts": int(predecessor["max_attempts"]), "artifact_count": 0}
    return None


def authorize_diagnostic_retry(conn: sqlite3.Connection, *, predecessor_job_id: int | str, actor: str, actor_role: str, rationale: str, acknowledged: bool) -> dict[str, Any]:
    ensure_job_tables(conn)
    if str(actor_role or "").strip() != "admin":
        raise ValueError("governed_report_diagnostic_retry_actor_invalid")
    rationale_value = str(rationale or "").strip()
    if not rationale_value or len(rationale_value) > DIAGNOSTIC_RETRY_MAX_RATIONALE:
        raise ValueError("governed_report_diagnostic_retry_rationale_invalid")
    if acknowledged is not True:
        raise ValueError("governed_report_diagnostic_retry_declaration_required")
    conn.execute("BEGIN IMMEDIATE")
    try:
        key = f"stage77-diagnostic-retry-{int(predecessor_job_id)}"
        existing = conn.execute("SELECT id FROM stage77_report_jobs WHERE idempotency_key=?", (key,)).fetchone()
        if existing is not None:
            predecessor = _job(conn, int(predecessor_job_id))
            report = reports.get_report(conn, int(predecessor["report_id"]))
            from api import governed_report_qualifications as qualification_store
            qualification = qualification_store.latest_final(conn, int(predecessor["report_id"]))
            if qualification is None:
                raise ValueError("governed_report_diagnostic_retry_qualification_invalid")
            diagnostic_contract = _validate_diagnostic_retry_predecessor_evidence(conn, predecessor)
            existing_payload = _diagnostic_retry_event_payload(conn, int(existing[0]))
            requested = _diagnostic_retry_payload(predecessor=predecessor, report=report, qualification=qualification, actor=actor, rationale=rationale_value, diagnostic_contract=diagnostic_contract, authorized_at=existing_payload["authorized_at"], successor_job_id=int(existing[0]))
            if _diagnostic_retry_identity(existing_payload) != _diagnostic_retry_identity(requested):
                raise ValueError("governed_report_diagnostic_retry_idempotency_conflict")
            conn.commit()
            return _job(conn, int(existing[0]))
        predecessor, report, qualification, diagnostic_contract = _eligible_diagnostic_retry(conn, int(predecessor_job_id), actor)
        now = utc_now()
        report_payload = _diagnostic_retry_payload(predecessor=predecessor, report=report, qualification=qualification, actor=actor, rationale=rationale_value, diagnostic_contract=diagnostic_contract, authorized_at=now)
        version = report["versions"][-1]
        cur = conn.execute("INSERT INTO stage77_report_jobs(report_id,report_version_id,specification_digest,requested_formats_json,rendering_profile,template_version,publication_engine_version,requesting_actor,governed_action,qualification_id,qualification_digest,requested_at,state,attempt_count,max_attempts,next_eligible_at,idempotency_key,retry_of_job_id,maintenance_epoch,schema_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (int(report["id"]), int(version["id"]), version["specification_digest"], reports.canonical_json(version["requested_formats"]), version["rendering_profile"], version["template_version"], version["publication_engine_version"], actor, DIAGNOSTIC_RETRY_ACTION, int(qualification["id"]), qualification["digest"], now, "queued", 0, MAX_ATTEMPTS, now, key, int(predecessor_job_id), 0, JOB_SCHEMA_VERSION))
        successor_id = int(cur.lastrowid)
        report_payload["successor_job_id"] = successor_id
        report_payload = _validate_diagnostic_retry_payload(report_payload)
        reports.record_diagnostic_retry_authorization(conn, report_id=report["id"], version_id=version["id"], predecessor_job_id=int(predecessor_job_id), actor=actor, actor_role=actor_role, rationale=rationale_value, declaration={"acknowledged": True}, idempotency_key=f"stage75-diagnostic-retry-{int(predecessor_job_id)}", payload=report_payload, _commit=False)
        _event(conn, successor_id, DIAGNOSTIC_RETRY_EVENT, "queued", actor, report_payload)
        conn.commit()
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        if "retry_predecessor" in str(exc) or "retry_of_job_id" in str(exc):
            raise ValueError("governed_report_diagnostic_retry_successor_exists") from None
        raise
    except Exception:
        conn.rollback()
        raise
    return _job(conn, successor_id)


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


def _revalidate_diagnostic_retry_job(conn: sqlite3.Connection, job: Mapping[str, Any], report: Mapping[str, Any]) -> None:
    if job.get("governed_action") != DIAGNOSTIC_RETRY_ACTION or job.get("retry_of_job_id") is None:
        raise ValueError("governed_report_diagnostic_retry_contract_invalid")
    payload = _diagnostic_retry_event_payload(conn, int(job["id"]))
    if payload["successor_job_id"] != int(job["id"]) or payload["predecessor_job_id"] != int(job["retry_of_job_id"]):
        raise ValueError("governed_report_diagnostic_retry_link_invalid")
    predecessor = _job(conn, int(job["retry_of_job_id"]))
    if predecessor["state"] != "failed_terminal" or predecessor.get("retry_of_job_id") is not None or predecessor.get("failure_phase") != "rendering" or predecessor.get("failure_code") != DIAGNOSTIC_RETRY_FAILURE_CODE:
        raise ValueError("governed_report_diagnostic_retry_predecessor_invalid")
    diagnostic_contract = _validate_diagnostic_retry_predecessor_evidence(conn, predecessor)
    if (payload["diagnostic_contract_id"] != diagnostic_contract["contract_id"]
            or payload["predecessor_attempt_diagnostic_sha256"] != diagnostic_contract["attempt_sha256"]
            or payload["predecessor_terminal_diagnostic_sha256"] != diagnostic_contract["terminal_sha256"]):
        raise ValueError("governed_report_diagnostic_retry_diagnostic_mismatch")
    if conn.execute("SELECT COUNT(*) FROM stage77_report_jobs WHERE retry_of_job_id=?", (int(predecessor["id"]),)).fetchone()[0] != 1:
        raise ValueError("governed_report_diagnostic_retry_successor_invalid")
    if report["lifecycle_status"] != "generation_requested" or int(report["id"]) != payload["report_id"]:
        raise ValueError("governed_report_diagnostic_retry_lifecycle_invalid")
    version = report["versions"][-1]
    if int(version["id"]) != payload["report_version_id"] or version["specification_digest"] != payload["specification_digest"] or reports.specification_digest(version["specification"]) != payload["specification_digest"]:
        raise ValueError("governed_report_diagnostic_retry_specification_invalid")
    if (list(job["requested_formats"]) != list(version["requested_formats"])
            or job["rendering_profile"] != version["rendering_profile"]
            or job["template_version"] != version["template_version"]
            or job["publication_engine_version"] != version["publication_engine_version"]):
        raise ValueError("governed_report_diagnostic_retry_contract_invalid")
    if version["specification"].get("distribution_class") != "internal_working":
        raise ValueError("governed_report_diagnostic_retry_distribution_invalid")
    from api import governed_report_qualifications as qualification_store
    qualification = qualification_store.latest_final(conn, int(report["id"]))
    if qualification is None or int(qualification["id"]) != payload["qualification_id"] or qualification["digest"] != payload["qualification_digest"]:
        raise ValueError("governed_report_diagnostic_retry_qualification_invalid")
    qualification_payload = qualification["payload"]
    if (qualification_payload.get("review_mode") != qualification_store.SOLE_MODE
            or qualification_payload.get("distribution_restriction") != "internal_working"
            or qualification_payload.get("disclosure_version") != qualification_store.DISCLOSURE_VERSION):
        raise ValueError("governed_report_diagnostic_retry_qualification_invalid")
    reports._validate_generation_sources(conn, version["specification"])
    from api import governed_report_recovery as recovery
    if not recovery.recovery_allows_claim(conn):
        raise ValueError("governed_report_diagnostic_retry_maintenance_active")


def _terminal_diagnostic_retry_revalidation_failure(conn: sqlite3.Connection, job: Mapping[str, Any], token: str) -> bool:
    diagnostic = make_diagnostic(phase="revalidation", operation="generation_revalidation", checkpoint="validation", code="qualification_invalid")
    conn.execute("BEGIN IMMEDIATE")
    try:
        reports.record_diagnostic_retry_validation_failure(conn, report_id=int(job["report_id"]), version_id=int(job["report_version_id"]), job_id=int(job["id"]), payload=diagnostic, _commit=False)
        cur = conn.execute("UPDATE stage77_report_jobs SET state='failed_terminal',terminal_at=?,terminal_outcome='qualification_invalid',failure_phase='revalidation',failure_code='qualification_invalid' WHERE id=? AND lease_token=? AND state IN ('leased','running')", (utc_now(), int(job["id"]), token))
        if cur.rowcount != 1:
            conn.rollback()
            return False
        _event(conn, int(job["id"]), "terminal", "failed_terminal", WORKER_IDENTITY, _terminal_payload(phase="revalidation", code="qualification_invalid", diagnostic=diagnostic))
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise


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


def _terminal_payload(*, phase: str | None, code: str | None, diagnostic: Mapping[str, Any] | None) -> dict[str, Any]:
    payload: dict[str, Any] = {"phase": phase, "code": code}
    if diagnostic is not None:
        payload["diagnostic"] = validate_diagnostic(diagnostic)
        payload["phase"] = payload["diagnostic"]["failure_phase"]
        payload["operation"] = payload["diagnostic"]["failure_operation"]
        payload["checkpoint"] = payload["diagnostic"]["failure_checkpoint"]
        payload["code"] = payload["diagnostic"]["failure_code"]
        payload.update(payload["diagnostic"])
    return payload


def _terminal(conn, job_id: int, token: str, state: str, actor: str, *, phase: str | None = None, code: str | None = None, diagnostic: Mapping[str, Any] | None = None) -> bool:
    allowed_states = "'cancel_requested'" if state == "cancelled" else "'leased','running'"
    cur = conn.execute(f"UPDATE stage77_report_jobs SET state=?,terminal_at=?,terminal_outcome=?,failure_phase=?,failure_code=? WHERE id=? AND lease_token=? AND state IN ({allowed_states})", (state, utc_now(), code or state, phase, code, job_id, token))
    if cur.rowcount != 1:
        conn.commit(); return False
    payload = _terminal_payload(phase=phase, code=code, diagnostic=diagnostic)
    _event(conn, job_id, "terminal", state, actor, payload)
    auth = conn.execute("SELECT post_correction_authorization_id FROM stage77_report_jobs WHERE id=?", (job_id,)).fetchone()
    if auth and auth[0]:
        conn.execute("UPDATE stage77_post_correction_authorizations SET state='consumed',consumed_at=? WHERE id=? AND state='authorized'", (utc_now(), auth[0]))
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
        if job.get("governed_action") == DIAGNOSTIC_RETRY_ACTION:
            try:
                _revalidate_diagnostic_retry_job(conn, job, report)
            except (ValueError, TypeError, sqlite3.Error):
                _terminal_diagnostic_retry_revalidation_failure(conn, job, token)
                return
        if job.get("governed_action") == POST_CORRECTION_ACTION:
            try:
                _revalidate_post_correction_job(conn, job, report)
            except (ValueError, TypeError, sqlite3.Error):
                _terminal(conn, job["id"], token, "failed_terminal", WORKER_IDENTITY, phase="revalidation", code="governed_report_post_correction_revalidation_failed", diagnostic=make_diagnostic(phase="revalidation", operation="post_correction_authorization", checkpoint="validation", code="governed_report_post_correction_revalidation_failed"))
                return
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
        if report["lifecycle_status"] not in ({"approved_for_generation", "generation_requested"} | ({"validation_failed"} if job.get("governed_action") == POST_CORRECTION_ACTION else set())):
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
                governance_qualification = qualification_store.rendering_projection(
                    conn,
                    report_id=job["report_id"],
                    report_version_id=job["report_version_id"],
                    specification_digest=job["specification_digest"],
                    qualification_id=job["qualification_id"],
                    qualification_digest=job["qualification_digest"],
                )
            reports.generate_report(conn, report_id=job["report_id"], actor=WORKER_IDENTITY, actor_role="system_worker", idempotency_key=f"stage77-job-{job['id']}", execution_guard=execution_guard, output_dir=staging_dir, promote_to=promoted_dir, _commit=False, finalization_transaction=True, governance_qualification=governance_qualification, post_correction_authorization_id=job.get("post_correction_authorization_id"))
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
                ensure_post_correction_tables(startup_conn)
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
