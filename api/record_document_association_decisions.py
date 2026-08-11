"""Relationship-owned decision evidence for Record-Document Associations.

This module records prospective relationship decisions only.  It does not
validate, authorize, mutate, or publish associations; those responsibilities
remain in ``record_document_associations``.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Mapping

from api.governed_decisions import (
    GovernedDecision,
    GovernedEvidenceReference,
    GovernedSubjectReference,
)


SUBJECT_TYPE = "record_document_association"
DEFAULT_DB_PATH = Path(os.getenv("RECORDS_DB_PATH", "records.db"))
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


def _diagnostic_json(value: Any, *, field_name: str, warnings: list[str]) -> Any:
    if value in (None, ""):
        return None
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except (TypeError, json.JSONDecodeError):
        warnings.append(f"Malformed {field_name}")
        return None
    if field_name == "request payload" and not isinstance(parsed, dict):
        warnings.append("Malformed request payload")
        return None
    return parsed


def _redact_payload(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "<redacted>" if key in {"idempotency_key", "idempotency"} else _redact_payload(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_payload(item) for item in value]
    return value


def _redacted_idempotency_key(value: Any) -> str | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    if len(normalized) <= 16:
        return f"{normalized[:4]}…{normalized[-4:]}"
    return f"{normalized[:8]}…{normalized[-8:]}"


def _resolve_document_for_diagnostic(raw_value: Any, *, root: Path | None) -> dict[str, Any]:
    raw = str(raw_value or "").strip()
    result = {
        "raw_value": raw or None,
        "resolved": False,
        "intake_id": None,
        "title": None,
        "document_identifier": None,
    }
    if not raw:
        return result
    try:
        from api.document_intake import load_pending_document_read_only

        candidates = [load_pending_document_read_only(raw, root=root)]
    except (ImportError, OSError, ValueError):
        try:
            from api.document_intake import list_intake_documents_read_only

            candidates = list_intake_documents_read_only(root=root)
        except (ImportError, OSError, ValueError):
            candidates = []
    for document in candidates:
        values = {
            str(document.get("intake_id") or "").strip(),
            str(document.get("document_identifier") or "").strip(),
            str(document.get("reference_identifier") or "").strip(),
        }
        if raw not in values or str(document.get("status") or "") != "published":
            continue
        result.update(
            resolved=True,
            intake_id=document.get("intake_id"),
            title=document.get("title"),
            document_identifier=document.get("document_identifier"),
        )
        return result
    return result


def read_association_decision_diagnostic(
    association_id: int | str,
    *,
    db_path: Path | str | None = None,
    document_root: Path | None = None,
) -> dict[str, Any]:
    """Read relationship decision evidence without initializing persistence."""

    path = Path(db_path or os.getenv("RECORDS_DB_PATH") or DEFAULT_DB_PATH)
    result: dict[str, Any] = {
        "status": "ok",
        "association": None,
        "decisions": [],
        "warnings": [],
        "decision_table_present": False,
        "comparison": {"state": "NOT DETERMINABLE"},
    }
    if not path.is_file():
        result["status"] = "database_unavailable"
        result["warnings"].append("Relationship database is not present")
        return result

    try:
        conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
    except (OSError, sqlite3.Error):
        result["status"] = "database_unavailable"
        result["warnings"].append("Relationship database could not be opened read-only")
        return result

    try:
        association_table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            ("record_document_associations",),
        ).fetchone()
        if association_table is None:
            result["status"] = "association_table_absent"
            result["warnings"].append("Association persistence is not present")
            return result
        association = conn.execute(
            "SELECT * FROM record_document_associations WHERE id = ?",
            (int(association_id),),
        ).fetchone()
        if association is None:
            result["status"] = "association_not_found"
            result["warnings"].append("Association does not exist")
            return result
        association_data = dict(association)
        result["association"] = association_data
        association_document = _resolve_document_for_diagnostic(
            association["document_id"], root=document_root
        )
        result["association_document"] = association_document
        if not association_document["resolved"]:
            result["warnings"].append("Persisted association document could not be resolved")

        decision_table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            ("record_document_association_decisions",),
        ).fetchone()
        if decision_table is None:
            result["decision_table_present"] = False
            result["warnings"].append("Stage 61 decision persistence is not present")
            return result
        result["decision_table_present"] = True
        rows = conn.execute(
            """
            SELECT * FROM record_document_association_decisions
            WHERE association_id = ?
            ORDER BY decided_at ASC, id ASC
            """,
            (int(association_id),),
        ).fetchall()
        if not rows:
            result["warnings"].append("No Stage 61 decisions exist for this association")

        creation_count = 0
        creation_payloads: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            warnings: list[str] = []
            item["previous_state"] = _diagnostic_json(
                item.get("previous_state_json"), field_name="previous state", warnings=warnings
            )
            item["resulting_state"] = _diagnostic_json(
                item.get("resulting_state_json"), field_name="resulting state", warnings=warnings
            )
            item["evidence_references"] = _diagnostic_json(
                item.get("evidence_references_json"), field_name="evidence references", warnings=warnings
            ) or []
            item["request_payload"] = _diagnostic_json(
                item.get("request_payload_json"), field_name="request payload", warnings=warnings
            )
            item["request_payload"] = _redact_payload(item["request_payload"])
            item["idempotency_key_present"] = bool(str(item.get("idempotency_key") or "").strip())
            item["idempotency_key_fingerprint"] = _redacted_idempotency_key(item.get("idempotency_key"))
            item["warnings"] = warnings
            if warnings:
                result["warnings"].extend(warnings)
            if item.get("decision_type") not in GOVERNED_DECISION_TYPES:
                result["warnings"].append(f"Unknown decision type: {item.get('decision_type')}")
            if item.get("decision_type") == "association_created":
                creation_count += 1
                if isinstance(item.get("request_payload"), dict):
                    creation_payloads.append(item["request_payload"])
            try:
                projection = adapt_decision(item).as_dict()
                projection["idempotency_key"] = item["idempotency_key_fingerprint"]
                item["stage60_projection"] = projection
            except (TypeError, ValueError, KeyError) as exc:
                item["stage60_projection"] = None
                result["warnings"].append(f"Stage 60 projection unavailable: {exc.__class__.__name__}")
            result["decisions"].append(item)

        if creation_count > 1:
            result["warnings"].append("Multiple association_created decisions exist")
        if creation_count == 1:
            payload_document = creation_payloads[0].get("document_id") if creation_payloads else None
            stored_document = association_data.get("document_id")
            if payload_document and stored_document:
                result["comparison"] = {
                    "state": "YES" if str(payload_document) == str(stored_document) else "NO",
                    "request_document_id": payload_document,
                    "association_document_id": stored_document,
                    "request_document": _resolve_document_for_diagnostic(payload_document, root=document_root),
                    "association_document": association_document,
                }
                if result["comparison"]["state"] == "NO":
                    result["warnings"].append("Creation payload document does not match association document")
            else:
                result["warnings"].append("Creation payload document comparison is not determinable")
        elif creation_count > 1:
            result["comparison"] = {"state": "NOT DETERMINABLE"}
        return result
    finally:
        conn.close()


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
