"""Stage 62 governed, deterministic pattern observations.

This module observes repetition in existing Record--Document Associations.  It
does not classify conduct, infer intent, or alter any source association.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Mapping


OBSERVATION_TYPE = "repeated_relationship_type"
RULE_VERSION = "stage62.repeated_relationship_type.v1"
OBSERVATION_STATUSES = {"candidate", "accepted", "rejected", "deferred"}
REVIEW_STATUSES = {"accepted", "rejected", "deferred"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _required(value: Any, error: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise ValueError(error)
    return result


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone() is not None


def ensure_observation_tables(conn: sqlite3.Connection) -> None:
    """Create Stage 62 persistence only from an authenticated write path."""

    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS record_pattern_observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            idempotency_key TEXT NOT NULL UNIQUE,
            observation_type TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            created_by TEXT NOT NULL,
            rationale TEXT NOT NULL,
            rule_version TEXT NOT NULL,
            source_count INTEGER NOT NULL,
            first_observed_at TEXT NOT NULL,
            last_observed_at TEXT NOT NULL,
            evidence_references_json TEXT NOT NULL,
            request_payload_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS record_pattern_observation_bindings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            observation_id INTEGER NOT NULL,
            association_id INTEGER NOT NULL,
            record_reference TEXT NOT NULL,
            relationship_type TEXT NOT NULL,
            source_created_at TEXT NOT NULL,
            FOREIGN KEY (observation_id) REFERENCES record_pattern_observations(id),
            FOREIGN KEY (association_id) REFERENCES record_document_associations(id),
            UNIQUE (observation_id, association_id)
        );
        CREATE TABLE IF NOT EXISTS record_pattern_observation_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            observation_id INTEGER NOT NULL,
            status TEXT NOT NULL,
            reviewed_at TEXT NOT NULL,
            reviewed_by TEXT NOT NULL,
            rationale TEXT NOT NULL,
            FOREIGN KEY (observation_id) REFERENCES record_pattern_observations(id)
        );
        CREATE INDEX IF NOT EXISTS idx_pattern_observations_status
            ON record_pattern_observations(status, created_at);
        CREATE INDEX IF NOT EXISTS idx_pattern_observation_bindings_observation
            ON record_pattern_observation_bindings(observation_id, source_created_at, association_id);
        CREATE INDEX IF NOT EXISTS idx_pattern_observation_reviews_observation
            ON record_pattern_observation_reviews(observation_id, reviewed_at, id);
        """
    )


def _association_rows(
    conn: sqlite3.Connection,
    *,
    record_reference: str | None = None,
    relationship_type: str | None = None,
) -> list[dict[str, Any]]:
    if not _table_exists(conn, "record_document_associations"):
        return []
    clauses = []
    params: list[Any] = []
    if record_reference:
        clauses.append("record_reference = ?")
        params.append(record_reference)
    if relationship_type:
        clauses.append("relationship_type = ?")
        params.append(relationship_type)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(
        f"""
        SELECT id, record_reference, relationship_type, created_at, is_active, is_public
        FROM record_document_associations
        {where}
        ORDER BY record_reference ASC, relationship_type ASC, created_at ASC, id ASC
        """,
        params,
    ).fetchall()
    return [dict(row) for row in rows]


def recurrence_candidates(
    conn: sqlite3.Connection,
    *,
    record_reference: str | None = None,
    relationship_type: str | None = None,
) -> list[dict[str, Any]]:
    """Return exact repeated relationship groups; no inference is applied."""

    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in _association_rows(
        conn,
        record_reference=str(record_reference or "").strip() or None,
        relationship_type=str(relationship_type or "").strip() or None,
    ):
        key = (str(row["record_reference"]), str(row["relationship_type"]))
        groups.setdefault(key, []).append(row)
    candidates = []
    for (reference, rel_type), rows in sorted(groups.items()):
        if len(rows) < 2:
            continue
        candidates.append(
            {
                "record_reference": reference,
                "relationship_type": rel_type,
                "source_count": len(rows),
                "first_observed_at": str(rows[0]["created_at"]),
                "last_observed_at": str(rows[-1]["created_at"]),
                "bindings": rows,
                "rule_version": RULE_VERSION,
                "observation_type": OBSERVATION_TYPE,
                "interpretation": "No inference recorded.",
            }
        )
    return candidates


def _candidate_payload(
    candidate: Mapping[str, Any], *, actor: str, actor_role: str, rationale: str
) -> dict[str, Any]:
    return {
        "observation_type": OBSERVATION_TYPE,
        "rule_version": RULE_VERSION,
        "record_reference": candidate["record_reference"],
        "relationship_type": candidate["relationship_type"],
        "association_ids": [int(row["id"]) for row in candidate["bindings"]],
        "actor": actor,
        "actor_role": actor_role,
        "rationale": rationale,
    }


def _key(payload: Mapping[str, Any]) -> str:
    return "stage62:" + hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def create_candidate_observation(
    conn: sqlite3.Connection,
    *,
    record_reference: str,
    relationship_type: str,
    actor: str,
    actor_role: str,
    rationale: str,
    idempotency_key: str | None = None,
    created_at: str | None = None,
    _commit: bool = True,
) -> dict[str, Any]:
    reference = _required(record_reference, "pattern_observation_record_required")
    rel_type = _required(relationship_type, "pattern_observation_relationship_required")
    actor_value = _required(actor, "pattern_observation_actor_required")
    role_value = _required(actor_role, "pattern_observation_actor_role_required")
    rationale_value = _required(rationale, "pattern_observation_rationale_required")
    candidates = recurrence_candidates(
        conn, record_reference=reference, relationship_type=rel_type
    )
    if len(candidates) != 1:
        raise ValueError("pattern_observation_recurrence_not_determinable")
    candidate = candidates[0]
    payload = _candidate_payload(
        candidate,
        actor=actor_value,
        actor_role=role_value,
        rationale=rationale_value,
    )
    key = str(idempotency_key or "").strip() or _key(payload)
    ensure_observation_tables(conn)
    existing = conn.execute(
        "SELECT * FROM record_pattern_observations WHERE idempotency_key = ?",
        (key,),
    ).fetchone()
    payload_json = _canonical_json(payload)
    if existing is not None:
        if str(existing["request_payload_json"]) != payload_json:
            raise ValueError("pattern_observation_idempotency_conflict")
        return get_observation(conn, int(existing["id"]))
    timestamp = str(created_at or utc_now())
    title = f"Repeated governed relationship: {rel_type}"
    description = (
        f"The governed relationship type {rel_type!r} occurs {candidate['source_count']} "
        f"times for record {reference}. No inference is recorded."
    )
    evidence = [
        {"reference_type": "record_document_association", "reference_id": str(row["id"])}
        for row in candidate["bindings"]
    ]
    cursor = conn.execute(
        """
        INSERT INTO record_pattern_observations (
            idempotency_key, observation_type, title, description, status,
            created_at, created_by, rationale, rule_version, source_count,
            first_observed_at, last_observed_at, evidence_references_json,
            request_payload_json
        ) VALUES (?, ?, ?, ?, 'candidate', ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            key, OBSERVATION_TYPE, title, description, timestamp, actor_value,
            rationale_value, RULE_VERSION, candidate["source_count"],
            candidate["first_observed_at"], candidate["last_observed_at"],
            _canonical_json(evidence), payload_json,
        ),
    )
    observation_id = int(cursor.lastrowid)
    conn.executemany(
        """
        INSERT INTO record_pattern_observation_bindings (
            observation_id, association_id, record_reference, relationship_type,
            source_created_at
        ) VALUES (?, ?, ?, ?, ?)
        """,
        [
            (observation_id, int(row["id"]), reference, rel_type, row["created_at"])
            for row in candidate["bindings"]
        ],
    )
    if _commit:
        conn.commit()
    return get_observation(conn, observation_id)


def get_observation(conn: sqlite3.Connection, observation_id: int | str) -> dict[str, Any]:
    if not _table_exists(conn, "record_pattern_observations"):
        raise ValueError("pattern_observation_table_absent")
    row = conn.execute(
        "SELECT * FROM record_pattern_observations WHERE id = ?", (int(observation_id),)
    ).fetchone()
    if row is None:
        raise ValueError("pattern_observation_not_found")
    result = dict(row)
    result["evidence_references"] = json.loads(result.pop("evidence_references_json"))
    result["request_payload"] = json.loads(result.pop("request_payload_json"))
    result["bindings"] = [
        dict(binding)
        for binding in conn.execute(
            """SELECT * FROM record_pattern_observation_bindings
               WHERE observation_id = ? ORDER BY source_created_at, association_id""",
            (int(observation_id),),
        ).fetchall()
    ]
    result["reviews"] = [
        dict(review)
        for review in conn.execute(
            """SELECT * FROM record_pattern_observation_reviews
               WHERE observation_id = ? ORDER BY reviewed_at, id""",
            (int(observation_id),),
        ).fetchall()
    ]
    return result


def list_observations(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    if not _table_exists(conn, "record_pattern_observations"):
        return []
    return [
        get_observation(conn, int(row["id"]))
        for row in conn.execute(
            "SELECT id FROM record_pattern_observations ORDER BY created_at, id"
        ).fetchall()
    ]


def review_observation(
    conn: sqlite3.Connection,
    observation_id: int | str,
    *,
    status: str,
    actor: str,
    actor_role: str,
    rationale: str,
    reviewed_at: str | None = None,
    _commit: bool = True,
) -> dict[str, Any]:
    normalized_status = _required(status, "pattern_observation_status_required").lower()
    if normalized_status not in REVIEW_STATUSES:
        raise ValueError("pattern_observation_review_status_invalid")
    actor_value = _required(actor, "pattern_observation_actor_required")
    _required(actor_role, "pattern_observation_actor_role_required")
    rationale_value = _required(rationale, "pattern_observation_review_rationale_required")
    observation = get_observation(conn, observation_id)
    timestamp = str(reviewed_at or utc_now())
    conn.execute(
        """INSERT INTO record_pattern_observation_reviews
           (observation_id, status, reviewed_at, reviewed_by, rationale)
           VALUES (?, ?, ?, ?, ?)""",
        (int(observation["id"]), normalized_status, timestamp, actor_value, rationale_value),
    )
    conn.execute(
        "UPDATE record_pattern_observations SET status = ? WHERE id = ?",
        (normalized_status, int(observation["id"])),
    )
    if _commit:
        conn.commit()
    return get_observation(conn, observation["id"])


def read_observation_diagnostic(
    observation_id: int | str | None = None,
    *,
    db_path: str | Any,
) -> dict[str, Any]:
    """Read observations without initializing any Stage 62 persistence."""

    path = str(db_path)
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return {"status": "database_unavailable", "observations": [], "candidates": []}
    conn.row_factory = sqlite3.Row
    try:
        candidates = recurrence_candidates(conn)
        observations = []
        if _table_exists(conn, "record_pattern_observations"):
            if observation_id is None:
                observations = list_observations(conn)
            else:
                try:
                    observations = [get_observation(conn, observation_id)]
                except ValueError:
                    return {"status": "observation_not_found", "observations": [], "candidates": candidates}
        return {
            "status": "ok",
            "observations": observations,
            "candidates": candidates,
            "observation_table_present": _table_exists(conn, "record_pattern_observations"),
        }
    finally:
        conn.close()


def adapt_observation(observation: Mapping[str, Any]) -> dict[str, Any]:
    """Return a passive, non-authoritative administrative projection."""

    return {
        "observation_id": f"record-pattern-observation:{observation['id']}",
        "observation_type": observation["observation_type"],
        "status": observation["status"],
        "source_count": observation["source_count"],
        "rule_version": observation["rule_version"],
        "interpretation": "No inference recorded.",
    }
