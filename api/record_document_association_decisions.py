"""Relationship-owned decision evidence for Record-Document Associations.

This module records prospective relationship decisions only.  It does not
validate, authorize, mutate, or publish associations; those responsibilities
remain in ``record_document_associations``.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any, Mapping

from api.governed_decisions import (
    GovernedDecision,
    GovernedEvidenceReference,
    GovernedSubjectReference,
)


SUBJECT_TYPE = "record_document_association"
GOVERNED_DECISION_TYPES = frozenset(
    {
        "association_created",
        "relationship_reclassified",
        "association_deactivated",
        "association_reactivated",
    }
)


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def ensure_decision_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS record_document_association_decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            association_id INTEGER NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE,
            decision_type TEXT NOT NULL,
            previous_state_json TEXT,
            resulting_state_json TEXT,
            actor TEXT NOT NULL,
            actor_role TEXT NOT NULL,
            decided_at TEXT NOT NULL,
            rationale TEXT NOT NULL,
            evidence_references_json TEXT NOT NULL DEFAULT '[]',
            context_reference TEXT,
            request_payload_json TEXT NOT NULL,
            FOREIGN KEY (association_id)
                REFERENCES record_document_associations(id)
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_association_decisions_subject
        ON record_document_association_decisions(association_id, id)
        """
    )


def _row(row: sqlite3.Row | Mapping[str, Any]) -> dict[str, Any]:
    result = dict(row)
    try:
        result["previous_state"] = json.loads(result.pop("previous_state_json"))
    except (TypeError, json.JSONDecodeError):
        result["previous_state"] = None
    try:
        result["resulting_state"] = json.loads(result.pop("resulting_state_json"))
    except (TypeError, json.JSONDecodeError):
        result["resulting_state"] = None
    try:
        result["evidence_references"] = json.loads(
            result.pop("evidence_references_json")
        )
    except (TypeError, json.JSONDecodeError):
        result["evidence_references"] = []
    try:
        result["request_payload"] = json.loads(result.pop("request_payload_json"))
    except (TypeError, json.JSONDecodeError):
        result["request_payload"] = None
    return result


def get_decision_by_idempotency_key(
    conn: sqlite3.Connection, idempotency_key: str
) -> dict[str, Any] | None:
    """Read an existing decision without creating schema or writing state."""

    try:
        row = conn.execute(
            """
            SELECT * FROM record_document_association_decisions
            WHERE idempotency_key = ?
            """,
            (str(idempotency_key or "").strip(),),
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    return _row(row) if row else None


def resolve_idempotency_key(
    supplied: str | None, request_payload: Mapping[str, Any]
) -> str:
    normalized = str(supplied or "").strip()
    if normalized:
        return normalized
    digest = hashlib.sha256(_json(dict(request_payload)).encode("utf-8")).hexdigest()
    return f"rda-{digest}"


def _assert_retry_matches(
    existing: dict[str, Any] | None,
    request_payload: Mapping[str, Any],
) -> dict[str, Any] | None:
    if existing is None:
        return None
    if existing.get("request_payload") != dict(request_payload):
        raise ValueError("association_decision_idempotency_conflict")
    return existing


def existing_for_request(
    conn: sqlite3.Connection,
    *,
    idempotency_key: str,
    request_payload: Mapping[str, Any],
) -> dict[str, Any] | None:
    return _assert_retry_matches(
        get_decision_by_idempotency_key(conn, idempotency_key), request_payload
    )


def record_decision(
    conn: sqlite3.Connection,
    *,
    association_id: int,
    idempotency_key: str,
    decision_type: str,
    previous_state: Mapping[str, Any] | None,
    resulting_state: Mapping[str, Any] | None,
    actor: str,
    actor_role: str,
    decided_at: str,
    rationale: str,
    request_payload: Mapping[str, Any],
    evidence_references: list[Mapping[str, str]] | None = None,
    context_reference: str | None = None,
) -> dict[str, Any]:
    if decision_type not in GOVERNED_DECISION_TYPES:
        raise ValueError("association_decision_type_invalid")
    if not str(idempotency_key or "").strip():
        raise ValueError("association_decision_idempotency_key_required")
    if not str(actor or "").strip() or not str(actor_role or "").strip():
        raise ValueError("association_decision_actor_required")
    if not str(rationale or "").strip():
        raise ValueError("association_decision_rationale_required")

    ensure_decision_table(conn)
    existing = get_decision_by_idempotency_key(conn, idempotency_key)
    retry = _assert_retry_matches(existing, request_payload)
    if retry is not None:
        return retry

    cursor = conn.execute(
        """
        INSERT INTO record_document_association_decisions (
            association_id, idempotency_key, decision_type,
            previous_state_json, resulting_state_json, actor, actor_role,
            decided_at, rationale, evidence_references_json, context_reference,
            request_payload_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            int(association_id),
            str(idempotency_key).strip(),
            decision_type,
            _json(previous_state) if previous_state is not None else None,
            _json(resulting_state) if resulting_state is not None else None,
            str(actor).strip(),
            str(actor_role).strip(),
            str(decided_at).strip(),
            str(rationale).strip(),
            _json(evidence_references or []),
            str(context_reference or "").strip() or None,
            _json(dict(request_payload)),
        ),
    )
    row = conn.execute(
        "SELECT * FROM record_document_association_decisions WHERE id = ?",
        (int(cursor.lastrowid),),
    ).fetchone()
    return _row(row)


def list_decisions(conn: sqlite3.Connection, association_id: int) -> list[dict[str, Any]]:
    try:
        rows = conn.execute(
            """
            SELECT * FROM record_document_association_decisions
            WHERE association_id = ? ORDER BY id ASC
            """,
            (int(association_id),),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    return [_row(row) for row in rows]


def adapt_decision(decision: Mapping[str, Any]) -> GovernedDecision:
    evidence = tuple(
        GovernedEvidenceReference(
            str(reference.get("reference_type") or "relationship_evidence"),
            str(reference.get("reference_id") or ""),
        )
        for reference in decision.get("evidence_references") or []
    )
    return GovernedDecision(
        decision_id=(
            f"record-document-association-decision:{decision.get('id')}"
            if decision.get("id") is not None
            else ""
        ),
        subject=GovernedSubjectReference(
            SUBJECT_TYPE,
            str(decision.get("association_id") or ""),
        ),
        decision_type=str(decision.get("decision_type") or "") or None,
        previous_state=_state_value(decision.get("previous_state")),
        resulting_state=_state_value(decision.get("resulting_state")),
        actor=str(decision.get("actor") or ""),
        actor_role=str(decision.get("actor_role") or ""),
        decided_at=str(decision.get("decided_at") or ""),
        rationale=str(decision.get("rationale") or ""),
        evidence_references=evidence,
        context_reference=str(decision.get("context_reference") or "") or None,
        idempotency_key=str(decision.get("idempotency_key") or "") or None,
    )


def _state_value(value: Any) -> str | None:
    if not isinstance(value, Mapping):
        return None
    if "relationship_type" in value:
        active = "active" if bool(value.get("is_active")) else "inactive"
        return f"{active}:{value.get('relationship_type')}"
    if "is_active" in value:
        return "active" if bool(value.get("is_active")) else "inactive"
    return None
