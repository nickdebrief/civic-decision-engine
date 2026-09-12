"""Stage 78E internal publication-review authority for governed reports.

This module deliberately stops at eligibility.  It creates no public artifact,
URL, representation, or discovery signal.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

SCHEMA_VERSION = "stage78e.governed_report_publication_review.v1"
OUTCOMES = {"eligible", "ineligible", "deferred"}
ASSESSMENTS = {"cleared", "not_cleared", "deferred"}
ACTIVE_STATES = {"open", "privacy_redaction_reviewed", "eligible", "ineligible", "deferred"}
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _required(value: Any, code: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise ValueError(code)
    return result


def _declaration(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or value.get("acknowledged") is not True:
        raise ValueError("governed_report_publication_review_declaration_required")
    if set(value) - {"acknowledged", "human_recorded", "boundary"}:
        raise ValueError("governed_report_publication_review_declaration_invalid")
    return {"acknowledged": True, "human_recorded": bool(value.get("human_recorded", True)), "boundary": "publication_eligibility_not_publication"}


def ensure_publication_review_tables(conn: sqlite3.Connection) -> None:
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS record_governed_report_publication_reviews (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      schema_version TEXT NOT NULL, report_id INTEGER NOT NULL, report_version_id INTEGER NOT NULL,
      governed_job_id INTEGER NOT NULL, governed_attempt_count INTEGER NOT NULL,
      artifact_set_digest TEXT NOT NULL, artifact_set_json TEXT NOT NULL,
      lifecycle_status TEXT NOT NULL, privacy_redaction_status TEXT NOT NULL,
      eligibility_outcome TEXT, created_by TEXT NOT NULL, created_by_role TEXT NOT NULL,
      created_at TEXT NOT NULL, withdrawn_at TEXT, superseded_by_review_id INTEGER,
      request_payload_json TEXT NOT NULL, idempotency_key TEXT NOT NULL UNIQUE,
      UNIQUE(report_version_id, artifact_set_digest),
      FOREIGN KEY(report_id) REFERENCES record_governed_reports(id),
      FOREIGN KEY(report_version_id) REFERENCES record_governed_report_versions(id)
    );
    CREATE TABLE IF NOT EXISTS record_governed_report_publication_review_artifacts (
      review_id INTEGER NOT NULL, artifact_id INTEGER NOT NULL, format TEXT NOT NULL,
      sha256 TEXT NOT NULL, size_bytes INTEGER NOT NULL, validation_state TEXT NOT NULL,
      lifecycle_status TEXT NOT NULL, report_version_id INTEGER NOT NULL,
      governed_job_id INTEGER NOT NULL, governed_attempt_count INTEGER NOT NULL,
      pdf_conversion_authority_digest TEXT,
      PRIMARY KEY(review_id, artifact_id), UNIQUE(review_id, format),
      FOREIGN KEY(review_id) REFERENCES record_governed_report_publication_reviews(id),
      FOREIGN KEY(artifact_id) REFERENCES record_governed_report_artifacts(id)
    );
    CREATE TABLE IF NOT EXISTS record_governed_report_publication_review_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT, review_id INTEGER NOT NULL, event_type TEXT NOT NULL,
      resulting_status TEXT NOT NULL, outcome TEXT, rationale TEXT NOT NULL,
      actor TEXT NOT NULL, actor_role TEXT NOT NULL, declaration_json TEXT NOT NULL,
      occurred_at TEXT NOT NULL, idempotency_key TEXT NOT NULL UNIQUE,
      request_payload_json TEXT NOT NULL,
      FOREIGN KEY(review_id) REFERENCES record_governed_report_publication_reviews(id)
    );
    CREATE INDEX IF NOT EXISTS idx_stage78e_review_version ON record_governed_report_publication_reviews(report_version_id, lifecycle_status);
    CREATE INDEX IF NOT EXISTS idx_stage78e_review_artifact ON record_governed_report_publication_review_artifacts(artifact_id);
    """)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(record_governed_report_publication_review_artifacts)").fetchall()}
    if "pdf_conversion_authority_digest" not in columns:
        conn.execute("ALTER TABLE record_governed_report_publication_review_artifacts ADD COLUMN pdf_conversion_authority_digest TEXT")


def _registered_artifacts(conn: sqlite3.Connection, report_id: int, version_id: int, artifact_ids: Sequence[int], *, expected_job_id: int | None = None, expected_attempt: int | None = None) -> list[dict[str, Any]]:
    """Resolve the live registered set; both opening and handoff use this boundary."""
    if not isinstance(artifact_ids, Sequence) or isinstance(artifact_ids, (str, bytes)) or not artifact_ids:
        raise ValueError("governed_report_publication_review_artifacts_required")
    try:
        ids = [int(item) for item in artifact_ids]
    except (TypeError, ValueError):
        raise ValueError("governed_report_publication_review_artifact_invalid") from None
    if len(ids) != len(set(ids)):
        raise ValueError("governed_report_publication_review_artifact_duplicate")
    placeholders = ",".join("?" for _ in ids)
    rows = conn.execute(
        "SELECT a.id,a.version_id,a.format,a.sha256,a.size_bytes,a.validation_state,a.lifecycle_status,"
        "a.governed_job_id,a.governed_attempt_count,a.pdf_conversion_authority_digest,"
        "a.qualification_id,a.qualification_digest,v.report_id "
        "FROM record_governed_report_artifacts a JOIN record_governed_report_versions v ON v.id=a.version_id "
        f"WHERE a.id IN ({placeholders}) ORDER BY a.format,a.id", ids,
    ).fetchall()
    if len(rows) != len(ids):
        raise ValueError("governed_report_publication_review_artifact_not_found")
    values = [dict(row) for row in rows]
    if any(int(row["version_id"]) != version_id or int(row["report_id"]) != report_id for row in values):
        raise ValueError("governed_report_publication_review_cross_version_artifact")
    if any(row["validation_state"] != "valid" or row["lifecycle_status"] != "current" for row in values):
        raise ValueError("governed_report_publication_review_artifact_unregistered")
    jobs = {(row["governed_job_id"], row["governed_attempt_count"]) for row in values}
    if len(jobs) != 1:
        raise ValueError("governed_report_publication_review_cross_attempt_artifact")
    job_id, attempt = next(iter(jobs))
    if job_id is None or attempt is None:
        raise ValueError("governed_report_publication_review_cross_attempt_artifact")
    try:
        job_id, attempt = int(job_id), int(attempt)
    except (TypeError, ValueError):
        raise ValueError("governed_report_publication_review_cross_attempt_artifact") from None
    if expected_job_id is not None and job_id != int(expected_job_id):
        raise ValueError("governed_report_publication_review_current_artifact_mismatch")
    if expected_attempt is not None and attempt != int(expected_attempt):
        raise ValueError("governed_report_publication_review_current_artifact_mismatch")
    if len({row["format"] for row in values}) != len(values):
        raise ValueError("governed_report_publication_review_format_duplicate")
    expected = conn.execute(
        "SELECT id,report_id,report_version_id,state,attempt_count,requested_formats_json,"
        "qualification_id,qualification_digest "
        "FROM stage77_report_jobs WHERE id=?", (job_id,),
    ).fetchone()
    if expected is None or expected["state"] != "succeeded":
        raise ValueError("governed_report_publication_review_job_ineligible")
    try:
        job_matches = (
            int(expected["report_id"]) == int(report_id)
            and int(expected["report_version_id"]) == int(version_id)
            and int(expected["attempt_count"]) == attempt
        )
    except (TypeError, ValueError):
        job_matches = False
    if not job_matches:
        raise ValueError("governed_report_publication_review_job_binding_invalid")
    try:
        qualification_id = int(expected["qualification_id"])
    except (TypeError, ValueError):
        raise ValueError("governed_report_publication_review_qualification_invalid") from None
    qualification_digest = expected["qualification_digest"]
    if qualification_id <= 0 or not isinstance(qualification_digest, str) or _SHA256.fullmatch(qualification_digest) is None:
        raise ValueError("governed_report_publication_review_qualification_invalid")
    qualifications = {
        (row["qualification_id"], row["qualification_digest"])
        for row in values
    }
    if qualifications != {(qualification_id, qualification_digest)}:
        raise ValueError("governed_report_publication_review_qualification_mismatch")
    try:
        requested = sorted(str(x) for x in json.loads(str(expected["requested_formats_json"])))
    except (TypeError, ValueError, json.JSONDecodeError):
        requested = []
    if requested != sorted(str(row["format"]) for row in values):
        raise ValueError("governed_report_publication_review_artifact_set_incomplete")
    return values


def _artifact_set(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {key: row[key] for key in ("id", "format", "sha256", "size_bytes", "validation_state", "lifecycle_status", "version_id", "governed_job_id", "governed_attempt_count", "pdf_conversion_authority_digest", "qualification_id", "qualification_digest")}
        for row in sorted(rows, key=lambda row: (str(row["format"]), int(row["id"])))
    ]


def _event(conn: sqlite3.Connection, review_id: int, event_type: str, status: str, outcome: str | None, rationale: str, actor: str, actor_role: str, declaration: Mapping[str, Any], idempotency_key: str, payload: Mapping[str, Any]) -> None:
    conn.execute("INSERT INTO record_governed_report_publication_review_events (review_id,event_type,resulting_status,outcome,rationale,actor,actor_role,declaration_json,occurred_at,idempotency_key,request_payload_json) VALUES (?,?,?,?,?,?,?,?,?,?,?)", (review_id, event_type, status, outcome, rationale, actor, actor_role, canonical_json(declaration), utc_now(), idempotency_key, canonical_json(payload)))


def open_review(conn: sqlite3.Connection, *, report_id: int, report_version_id: int, artifact_ids: Sequence[int], actor: str, actor_role: str, rationale: str, declaration: Mapping[str, Any], idempotency_key: str) -> dict[str, Any]:
    ensure_publication_review_tables(conn)
    actor, actor_role, rationale, key = _required(actor, "governed_report_publication_review_actor_required"), _required(actor_role, "governed_report_publication_review_role_required"), _required(rationale, "governed_report_publication_review_rationale_required"), _required(idempotency_key, "governed_report_publication_review_idempotency_required")
    declared = _declaration(declaration)
    report = conn.execute("SELECT id,lifecycle_status FROM record_governed_reports WHERE id=?", (int(report_id),)).fetchone()
    version = conn.execute("SELECT id,report_id,lifecycle_status FROM record_governed_report_versions WHERE id=?", (int(report_version_id),)).fetchone()
    if report is None or version is None or int(version["report_id"]) != int(report_id) or report["lifecycle_status"] != "generated" or version["lifecycle_status"] != "generated":
        raise ValueError("governed_report_publication_review_version_ineligible")
    rows = _registered_artifacts(conn, int(report_id), int(report_version_id), artifact_ids)
    frozen = _artifact_set(rows); frozen_digest = digest(frozen)
    payload = {"report_id": int(report_id), "report_version_id": int(report_version_id), "artifact_set": frozen, "rationale": rationale, "declaration": declared}
    prior = conn.execute("SELECT id,request_payload_json FROM record_governed_report_publication_reviews WHERE idempotency_key=?", (key,)).fetchone()
    if prior:
        if str(prior["request_payload_json"]) != canonical_json(payload): raise ValueError("governed_report_publication_review_idempotency_conflict")
        return get_review(conn, int(prior["id"]))
    existing = conn.execute("SELECT id FROM record_governed_report_publication_reviews WHERE report_version_id=? AND artifact_set_digest=?", (int(report_version_id), frozen_digest)).fetchone()
    if existing: raise ValueError("governed_report_publication_review_artifact_set_already_reviewed")
    job_id, attempt = int(rows[0]["governed_job_id"]), int(rows[0]["governed_attempt_count"])
    cursor = conn.execute("INSERT INTO record_governed_report_publication_reviews (schema_version,report_id,report_version_id,governed_job_id,governed_attempt_count,artifact_set_digest,artifact_set_json,lifecycle_status,privacy_redaction_status,created_by,created_by_role,created_at,request_payload_json,idempotency_key) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (SCHEMA_VERSION, int(report_id), int(report_version_id), job_id, attempt, frozen_digest, canonical_json(frozen), "open", "not_reviewed", actor, actor_role, utc_now(), canonical_json(payload), key))
    review_id = int(cursor.lastrowid)
    for row in frozen:
        conn.execute("INSERT INTO record_governed_report_publication_review_artifacts (review_id,artifact_id,format,sha256,size_bytes,validation_state,lifecycle_status,report_version_id,governed_job_id,governed_attempt_count,pdf_conversion_authority_digest) VALUES (?,?,?,?,?,?,?,?,?,?,?)", (review_id, row["id"], row["format"], row["sha256"], row["size_bytes"], row["validation_state"], row["lifecycle_status"], row["version_id"], row["governed_job_id"], row["governed_attempt_count"], row["pdf_conversion_authority_digest"]))
    _event(conn, review_id, "review_opened", "open", None, rationale, actor, actor_role, declared, key + ":event", payload)
    return get_review(conn, review_id)


def record_privacy_redaction(conn: sqlite3.Connection, *, review_id: int, status: str, actor: str, actor_role: str, rationale: str, declaration: Mapping[str, Any], idempotency_key: str) -> dict[str, Any]:
    if status not in ASSESSMENTS: raise ValueError("governed_report_publication_review_assessment_invalid")
    review = get_review(conn, review_id)
    if review["lifecycle_status"] != "open": raise ValueError("governed_report_publication_review_transition_invalid")
    declared = _declaration(declaration); actor, actor_role, rationale, key = _required(actor, "governed_report_publication_review_actor_required"), _required(actor_role, "governed_report_publication_review_role_required"), _required(rationale, "governed_report_publication_review_rationale_required"), _required(idempotency_key, "governed_report_publication_review_idempotency_required")
    payload = {"review_id": int(review_id), "status": status, "rationale": rationale, "declaration": declared}
    existing = conn.execute("SELECT request_payload_json FROM record_governed_report_publication_review_events WHERE idempotency_key=?", (key,)).fetchone()
    if existing:
        if str(existing[0]) != canonical_json(payload): raise ValueError("governed_report_publication_review_idempotency_conflict")
        return get_review(conn, review_id)
    conn.execute("UPDATE record_governed_report_publication_reviews SET privacy_redaction_status=?,lifecycle_status='privacy_redaction_reviewed' WHERE id=?", (status, int(review_id)))
    _event(conn, int(review_id), "privacy_redaction_assessed", "privacy_redaction_reviewed", status, rationale, actor, actor_role, declared, key, payload)
    return get_review(conn, review_id)


def determine_eligibility(conn: sqlite3.Connection, *, review_id: int, outcome: str, actor: str, actor_role: str, rationale: str, declaration: Mapping[str, Any], idempotency_key: str) -> dict[str, Any]:
    if outcome not in OUTCOMES: raise ValueError("governed_report_publication_review_outcome_invalid")
    review = get_review(conn, review_id)
    if review["lifecycle_status"] != "privacy_redaction_reviewed" or (outcome == "eligible" and review["privacy_redaction_status"] != "cleared"):
        raise ValueError("governed_report_publication_review_prerequisite_unsatisfied")
    declared = _declaration(declaration); actor, actor_role, rationale, key = _required(actor, "governed_report_publication_review_actor_required"), _required(actor_role, "governed_report_publication_review_role_required"), _required(rationale, "governed_report_publication_review_rationale_required"), _required(idempotency_key, "governed_report_publication_review_idempotency_required")
    payload = {"review_id": int(review_id), "outcome": outcome, "rationale": rationale, "declaration": declared}
    existing = conn.execute("SELECT request_payload_json FROM record_governed_report_publication_review_events WHERE idempotency_key=?", (key,)).fetchone()
    if existing:
        if str(existing[0]) != canonical_json(payload): raise ValueError("governed_report_publication_review_idempotency_conflict")
        return get_review(conn, review_id)
    conn.execute("UPDATE record_governed_report_publication_reviews SET lifecycle_status=?,eligibility_outcome=? WHERE id=?", (outcome, outcome, int(review_id)))
    _event(conn, int(review_id), "eligibility_determined", outcome, outcome, rationale, actor, actor_role, declared, key, payload)
    return get_review(conn, review_id)


def withdraw_review(conn: sqlite3.Connection, *, review_id: int, actor: str, actor_role: str, rationale: str, declaration: Mapping[str, Any], idempotency_key: str, replacement_review_id: int | None = None) -> dict[str, Any]:
    """Retire current authority without deleting the review or its decisions."""
    review = get_review(conn, review_id)
    if review["lifecycle_status"] in {"withdrawn", "superseded"}:
        raise ValueError("governed_report_publication_review_transition_invalid")
    declared = _declaration(declaration); actor, actor_role, rationale, key = _required(actor, "governed_report_publication_review_actor_required"), _required(actor_role, "governed_report_publication_review_role_required"), _required(rationale, "governed_report_publication_review_rationale_required"), _required(idempotency_key, "governed_report_publication_review_idempotency_required")
    status = "superseded" if replacement_review_id is not None else "withdrawn"
    if replacement_review_id is not None:
        replacement = get_review(conn, int(replacement_review_id))
        if int(replacement["report_id"]) != int(review["report_id"]) or int(replacement["id"]) == int(review_id) or replacement["lifecycle_status"] in {"withdrawn", "superseded"}:
            raise ValueError("governed_report_publication_review_supersession_invalid")
    payload = {"review_id": int(review_id), "replacement_review_id": replacement_review_id, "rationale": rationale, "declaration": declared}
    existing = conn.execute("SELECT request_payload_json FROM record_governed_report_publication_review_events WHERE idempotency_key=?", (key,)).fetchone()
    if existing:
        if str(existing[0]) != canonical_json(payload): raise ValueError("governed_report_publication_review_idempotency_conflict")
        return get_review(conn, review_id)
    conn.execute("UPDATE record_governed_report_publication_reviews SET lifecycle_status=?,withdrawn_at=?,superseded_by_review_id=? WHERE id=?", (status, utc_now(), replacement_review_id, int(review_id)))
    _event(conn, int(review_id), status, status, None, rationale, actor, actor_role, declared, key, payload)
    return get_review(conn, review_id)


def get_review(conn: sqlite3.Connection, review_id: int) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM record_governed_report_publication_reviews WHERE id=?", (int(review_id),)).fetchone()
    if row is None: raise ValueError("governed_report_publication_review_not_found")
    result = dict(row); result["artifact_set"] = json.loads(result.pop("artifact_set_json")); result["request_payload"] = json.loads(result.pop("request_payload_json"))
    result["artifacts"] = [dict(x) for x in conn.execute("SELECT * FROM record_governed_report_publication_review_artifacts WHERE review_id=? ORDER BY format,artifact_id", (int(review_id),)).fetchall()]
    result["events"] = [dict(x) for x in conn.execute("SELECT * FROM record_governed_report_publication_review_events WHERE review_id=? ORDER BY id", (int(review_id),)).fetchall()]
    return result


def current_eligibility(conn: sqlite3.Connection, *, report_version_id: int, artifact_set_digest: str) -> dict[str, Any]:
    row = conn.execute("SELECT id FROM record_governed_report_publication_reviews WHERE report_version_id=? AND artifact_set_digest=? AND lifecycle_status='eligible' AND withdrawn_at IS NULL AND superseded_by_review_id IS NULL", (int(report_version_id), _required(artifact_set_digest, "governed_report_publication_review_digest_required"))).fetchone()
    if row is None: raise ValueError("governed_report_publication_review_eligibility_absent")
    review = get_review(conn, int(row[0]))
    frozen = review["artifact_set"]
    if not isinstance(frozen, list) or not frozen:
        raise ValueError("governed_report_publication_review_current_artifact_mismatch")
    try:
        artifact_ids = [int(item["id"]) for item in frozen]
        current = _artifact_set(_registered_artifacts(
            conn, int(review["report_id"]), int(review["report_version_id"]), artifact_ids,
            expected_job_id=int(review["governed_job_id"]),
            expected_attempt=int(review["governed_attempt_count"]),
        ))
    except (KeyError, TypeError, ValueError):
        raise ValueError("governed_report_publication_review_current_artifact_mismatch") from None
    if current != frozen or digest(current) != str(review["artifact_set_digest"]):
        raise ValueError("governed_report_publication_review_current_artifact_mismatch")
    return review


def verify_preserved_review_history(conn: sqlite3.Connection) -> None:
    """Verify persisted review authority during recovery without recreating it."""
    for row in conn.execute("SELECT id FROM record_governed_report_publication_reviews ORDER BY id").fetchall():
        review = get_review(conn, int(row[0]))
        if review["schema_version"] != SCHEMA_VERSION or digest(review["artifact_set"]) != review["artifact_set_digest"]:
            raise ValueError("governed_report_publication_review_history_invalid")
        if review["lifecycle_status"] not in ACTIVE_STATES | {"withdrawn", "superseded"}:
            raise ValueError("governed_report_publication_review_history_invalid")
        if review["lifecycle_status"] == "eligible" and review["privacy_redaction_status"] != "cleared":
            raise ValueError("governed_report_publication_review_history_invalid")
        if len(review["artifacts"]) != len(review["artifact_set"]):
            raise ValueError("governed_report_publication_review_history_invalid")
        for frozen, stored in zip(review["artifact_set"], review["artifacts"]):
            if any(frozen[key] != stored[{"id": "artifact_id"}.get(key, key)] for key in frozen):
                raise ValueError("governed_report_publication_review_history_invalid")
