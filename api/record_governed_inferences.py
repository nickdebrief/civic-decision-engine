"""Stage 63 human-authored, governed inference persistence.

Inference is a qualified interpretation of governed sources.  This module is
deliberately independent from Stage 60 decision representation and Stage 62
observation authority.  It never mutates a bound source object.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


METHOD_VERSION = "stage63.human_governed_inference.v1"
AUTHORING_MODE = "human_authored"
INFERENCE_TYPES = {"contextual", "temporal", "relational", "procedural"}
INFERENCE_STATUSES = {
    "proposed",
    "accepted_as_inference",
    "rejected",
    "deferred",
    "superseded",
}
REVIEW_STATUSES = {"accepted_as_inference", "rejected", "deferred"}
BINDING_ROLES = {
    "primary_support",
    "contextual_support",
    "qualifying_evidence",
    "contrary_evidence",
}
SOURCE_TYPES = {
    "published_document",
    "canonical_record",
    "record_document_association",
    "accepted_pattern_observation",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _required(value: Any, error: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(error)
    return normalized


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?", (table_name,)
    ).fetchone() is not None


def _canonical_bindings(bindings: Any) -> list[dict[str, Any]]:
    if not isinstance(bindings, (list, tuple)) or not bindings:
        raise ValueError("governed_inference_binding_required")
    result = []
    for item in bindings:
        if not isinstance(item, Mapping):
            raise ValueError("governed_inference_binding_invalid")
        source_type = _required(item.get("source_type"), "governed_inference_source_type_required")
        if source_type not in SOURCE_TYPES:
            raise ValueError("governed_inference_source_type_invalid")
        source_id = _required(item.get("source_id"), "governed_inference_source_id_required")
        binding_role = _required(item.get("binding_role"), "governed_inference_binding_role_required")
        if binding_role not in BINDING_ROLES:
            raise ValueError("governed_inference_binding_role_invalid")
        result.append(
            {
                "source_type": source_type,
                "source_id": source_id,
                "binding_role": binding_role,
                "source_version": (
                    str(item["source_version"]).strip()
                    if item.get("source_version") is not None
                    else None
                ),
                "source_timestamp": (
                    str(item["source_timestamp"]).strip()
                    if item.get("source_timestamp") is not None
                    else None
                ),
            }
        )
    result.sort(key=lambda item: (item["source_type"], item["source_id"], item["binding_role"]))
    if len({(item["source_type"], item["source_id"], item["binding_role"]) for item in result}) != len(result):
        raise ValueError("governed_inference_duplicate_binding")
    return result


def _qualification_contract(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("governed_inference_qualification_contract_required")
    expected = {
        "epistemic_label": "inference",
        "source_basis_present": True,
        "alternatives_possible": True,
        "not_evidence": True,
        "not_determination": True,
    }
    for key, expected_value in expected.items():
        if value.get(key) != expected_value:
            raise ValueError("governed_inference_qualification_contract_incomplete")
    limitations = _required(value.get("limitations"), "governed_inference_limitations_required")
    result = dict(expected)
    result["limitations"] = limitations
    return result


def _author_declaration(value: Any, *, actor: str, role: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or value.get("acknowledged") is not True:
        raise ValueError("governed_inference_author_boundary_declaration_required")
    return {
        "authoring_mode": AUTHORING_MODE,
        "permitted_stage63_type": True,
        "no_prohibited_class_asserted": True,
        "acknowledged": True,
        "recorded_by": actor,
        "recorded_by_role": role,
    }


def _review_assessment(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("governed_inference_review_assessment_required")
    required = {
        "within_stage63_boundary": True,
        "qualification_adequate": True,
        "no_prohibited_class_asserted": True,
    }
    for key, expected in required.items():
        if value.get(key) != expected:
            raise ValueError("governed_inference_review_assessment_incomplete")
    return dict(required)


def ensure_inference_tables(conn: sqlite3.Connection) -> None:
    """Create Stage 63 persistence only from an authenticated write path."""

    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS record_governed_inferences (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            idempotency_key TEXT NOT NULL UNIQUE,
            inference_type TEXT NOT NULL,
            proposition TEXT NOT NULL,
            rationale TEXT NOT NULL,
            qualification TEXT NOT NULL,
            qualification_contract_json TEXT NOT NULL,
            authoring_mode TEXT NOT NULL,
            method_version TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            created_by TEXT NOT NULL,
            created_by_role TEXT NOT NULL,
            author_boundary_declaration_json TEXT NOT NULL,
            request_payload_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS record_governed_inference_bindings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            inference_id INTEGER NOT NULL,
            source_type TEXT NOT NULL,
            source_id TEXT NOT NULL,
            binding_role TEXT NOT NULL,
            source_version TEXT,
            source_timestamp TEXT,
            FOREIGN KEY (inference_id) REFERENCES record_governed_inferences(id),
            UNIQUE (inference_id, source_type, source_id, binding_role)
        );
        CREATE TABLE IF NOT EXISTS record_governed_inference_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            inference_id INTEGER NOT NULL,
            status TEXT NOT NULL,
            reviewed_at TEXT NOT NULL,
            reviewed_by TEXT NOT NULL,
            reviewed_by_role TEXT NOT NULL,
            rationale TEXT NOT NULL,
            qualification_assessment_json TEXT NOT NULL,
            prohibited_class_assessment_json TEXT NOT NULL,
            contrary_evidence_note TEXT NOT NULL,
            is_self_review INTEGER NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE,
            request_payload_json TEXT NOT NULL,
            FOREIGN KEY (inference_id) REFERENCES record_governed_inferences(id)
        );
        CREATE TABLE IF NOT EXISTS record_governed_inference_supersessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            inference_id INTEGER NOT NULL,
            replacement_inference_id INTEGER,
            event_type TEXT NOT NULL,
            rationale TEXT NOT NULL,
            actor TEXT NOT NULL,
            actor_role TEXT NOT NULL,
            occurred_at TEXT NOT NULL,
            evidence_references_json TEXT NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE,
            request_payload_json TEXT NOT NULL,
            FOREIGN KEY (inference_id) REFERENCES record_governed_inferences(id),
            FOREIGN KEY (replacement_inference_id) REFERENCES record_governed_inferences(id)
        );
        CREATE INDEX IF NOT EXISTS idx_governed_inferences_status
            ON record_governed_inferences(status, created_at);
        CREATE INDEX IF NOT EXISTS idx_governed_inference_bindings_source
            ON record_governed_inference_bindings(source_type, source_id, inference_id);
        CREATE INDEX IF NOT EXISTS idx_governed_inference_reviews_inference
            ON record_governed_inference_reviews(inference_id, reviewed_at, id);
        CREATE INDEX IF NOT EXISTS idx_governed_inference_supersessions_inference
            ON record_governed_inference_supersessions(inference_id, occurred_at, id);
        """
    )


def _source_binding(
    conn: sqlite3.Connection, binding: Mapping[str, Any], *, document_root: Path | None = None
) -> dict[str, Any]:
    source_type = str(binding["source_type"])
    source_id = str(binding["source_id"])
    version = binding.get("source_version")
    timestamp = binding.get("source_timestamp")
    if source_type == "record_document_association":
        from api.record_document_associations import get_association

        try:
            row = get_association(conn, int(source_id))
        except (ValueError, TypeError) as exc:
            raise ValueError("governed_inference_source_not_found") from exc
        timestamp = timestamp or row.get("created_at")
    elif source_type == "canonical_record":
        if not _table_exists(conn, "records"):
            raise ValueError("governed_inference_source_not_found")
        row = conn.execute("SELECT * FROM records WHERE reference = ?", (source_id,)).fetchone()
        if row is None:
            raise ValueError("governed_inference_source_not_found")
        version = version or (row["version"] if "version" in row.keys() else None)
        timestamp = timestamp or (row["generated_at"] if "generated_at" in row.keys() else None)
    elif source_type == "published_document":
        from api.document_intake import intake_root, load_published_document

        document = load_published_document(source_id, root=document_root or intake_root())
        if document is None:
            raise ValueError("governed_inference_source_not_found")
        version = version or document.get("version")
        timestamp = timestamp or document.get("created_at") or document.get("published_at")
    elif source_type == "accepted_pattern_observation":
        if not _table_exists(conn, "record_pattern_observations"):
            raise ValueError("governed_inference_source_not_found")
        row = conn.execute(
            "SELECT * FROM record_pattern_observations WHERE id = ?", (int(source_id),)
        ).fetchone()
        if row is None or str(row["status"]) != "accepted":
            raise ValueError("governed_inference_observation_not_accepted")
        timestamp = timestamp or row["created_at"]
    return {
        **dict(binding),
        "source_version": str(version).strip() if version not in (None, "") else None,
        "source_timestamp": str(timestamp).strip() if timestamp not in (None, "") else None,
    }


def _key(prefix: str, payload: Mapping[str, Any]) -> str:
    return prefix + hashlib.sha256(_json(payload).encode("utf-8")).hexdigest()


def _row(row: sqlite3.Row | Mapping[str, Any]) -> dict[str, Any]:
    result = dict(row)
    for field in ("qualification_contract_json", "author_boundary_declaration_json", "request_payload_json"):
        result[field] = json.loads(result[field]) if result.get(field) else None
    return result


def _current_status(conn: sqlite3.Connection, inference_id: int, base: str) -> str:
    supersession = conn.execute(
        "SELECT 1 FROM record_governed_inference_supersessions WHERE inference_id = ? ORDER BY id DESC LIMIT 1",
        (inference_id,),
    ).fetchone()
    if supersession is not None:
        return "superseded"
    review = conn.execute(
        "SELECT status FROM record_governed_inference_reviews WHERE inference_id = ? ORDER BY id DESC LIMIT 1",
        (inference_id,),
    ).fetchone()
    return str(review[0]) if review is not None else base


def get_inference(conn: sqlite3.Connection, inference_id: int | str) -> dict[str, Any]:
    if not _table_exists(conn, "record_governed_inferences"):
        raise ValueError("governed_inference_table_absent")
    row = conn.execute("SELECT * FROM record_governed_inferences WHERE id = ?", (int(inference_id),)).fetchone()
    if row is None:
        raise ValueError("governed_inference_not_found")
    result = _row(row)
    result["status"] = _current_status(conn, int(inference_id), str(result["status"]))
    result["qualification_contract"] = result.pop("qualification_contract_json")
    result["author_boundary_declaration"] = result.pop("author_boundary_declaration_json")
    result["request_payload"] = result.pop("request_payload_json")
    result["bindings"] = [dict(item) for item in conn.execute(
        "SELECT * FROM record_governed_inference_bindings WHERE inference_id = ? ORDER BY id",
        (int(inference_id),),
    ).fetchall()]
    result["reviews"] = []
    for item in conn.execute(
        "SELECT * FROM record_governed_inference_reviews WHERE inference_id = ? ORDER BY id",
        (int(inference_id),),
    ).fetchall():
        review = dict(item)
        review["qualification_assessment"] = json.loads(review.pop("qualification_assessment_json"))
        review["prohibited_class_assessment"] = json.loads(review.pop("prohibited_class_assessment_json"))
        review["request_payload"] = json.loads(review.pop("request_payload_json"))
        result["reviews"].append(review)
    result["supersessions"] = []
    for item in conn.execute(
        "SELECT * FROM record_governed_inference_supersessions WHERE inference_id = ? ORDER BY id",
        (int(inference_id),),
    ).fetchall():
        event = dict(item)
        event["evidence_references"] = json.loads(event.pop("evidence_references_json"))
        event["request_payload"] = json.loads(event.pop("request_payload_json"))
        result["supersessions"].append(event)
    return result


def list_inferences(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    if not _table_exists(conn, "record_governed_inferences"):
        return []
    return [get_inference(conn, row[0]) for row in conn.execute(
        "SELECT id FROM record_governed_inferences ORDER BY created_at, id"
    ).fetchall()]


def read_inference_diagnostic(inference_id: int | str | None = None, *, db_path: str | Path) -> dict[str, Any]:
    """Read Stage 63 without creating its tables or any other persistence."""

    path = Path(db_path)
    if not path.is_file():
        return {"status": "database_unavailable", "inferences": []}
    try:
        conn = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    except sqlite3.Error:
        return {"status": "database_unavailable", "inferences": []}
    conn.row_factory = sqlite3.Row
    try:
        if not _table_exists(conn, "record_governed_inferences"):
            return {"status": "ok", "inferences": [], "inference_table_present": False}
        if inference_id is None:
            return {"status": "ok", "inferences": list_inferences(conn), "inference_table_present": True}
        try:
            return {"status": "ok", "inferences": [get_inference(conn, inference_id)], "inference_table_present": True}
        except ValueError:
            return {"status": "inference_not_found", "inferences": [], "inference_table_present": True}
    finally:
        conn.close()


def create_inference(
    conn: sqlite3.Connection,
    *,
    inference_type: str,
    proposition: str,
    rationale: str,
    qualification: str,
    qualification_contract: Mapping[str, Any],
    bindings: list[Mapping[str, Any]],
    actor: str,
    actor_role: str,
    author_declaration: Mapping[str, Any],
    authoring_mode: str = AUTHORING_MODE,
    idempotency_key: str | None = None,
    created_at: str | None = None,
    document_root: Path | None = None,
    _commit: bool = True,
) -> dict[str, Any]:
    if str(authoring_mode or "").strip() != AUTHORING_MODE:
        raise ValueError("governed_inference_authoring_mode_invalid")
    type_value = _required(inference_type, "governed_inference_type_required").lower()
    if type_value not in INFERENCE_TYPES:
        raise ValueError("governed_inference_type_invalid")
    proposition_value = _required(proposition, "governed_inference_proposition_required")
    rationale_value = _required(rationale, "governed_inference_rationale_required")
    qualification_value = _required(qualification, "governed_inference_qualification_required")
    actor_value = _required(actor, "governed_inference_author_required")
    role_value = _required(actor_role, "governed_inference_author_role_required")
    contract = _qualification_contract(qualification_contract)
    declaration = _author_declaration(author_declaration, actor=actor_value, role=role_value)
    normalized = [_source_binding(conn, item, document_root=document_root) for item in _canonical_bindings(bindings)]
    payload = {
        "inference_type": type_value,
        "proposition": proposition_value,
        "rationale": rationale_value,
        "qualification": qualification_value,
        "qualification_contract": contract,
        "authoring_mode": AUTHORING_MODE,
        "method_version": METHOD_VERSION,
        "bindings": normalized,
        "author_boundary_declaration": declaration,
    }
    key = str(idempotency_key or "").strip() or _key("stage63-inference:", payload)
    ensure_inference_tables(conn)
    existing = conn.execute("SELECT * FROM record_governed_inferences WHERE idempotency_key = ?", (key,)).fetchone()
    payload_json = _json(payload)
    if existing is not None:
        if str(existing["request_payload_json"]) != payload_json:
            raise ValueError("governed_inference_idempotency_conflict")
        return get_inference(conn, existing["id"])
    timestamp = str(created_at or utc_now())
    cursor = conn.execute(
        """INSERT INTO record_governed_inferences
        (idempotency_key, inference_type, proposition, rationale, qualification,
         qualification_contract_json, authoring_mode, method_version, status,
         created_at, created_by, created_by_role, author_boundary_declaration_json,
         request_payload_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'proposed', ?, ?, ?, ?, ?)""",
        (key, type_value, proposition_value, rationale_value, qualification_value,
         _json(contract), AUTHORING_MODE, METHOD_VERSION, timestamp, actor_value,
         role_value, _json(declaration), payload_json),
    )
    inference_id = int(cursor.lastrowid)
    conn.executemany(
        """INSERT INTO record_governed_inference_bindings
        (inference_id, source_type, source_id, binding_role, source_version, source_timestamp)
        VALUES (?, ?, ?, ?, ?, ?)""",
        [(inference_id, item["source_type"], item["source_id"], item["binding_role"], item["source_version"], item["source_timestamp"]) for item in normalized],
    )
    if _commit:
        conn.commit()
    return get_inference(conn, inference_id)


def review_inference(
    conn: sqlite3.Connection,
    inference_id: int | str,
    *,
    status: str,
    rationale: str,
    qualification_assessment: Mapping[str, Any],
    prohibited_class_assessment: Mapping[str, Any],
    contrary_evidence_note: str,
    actor: str,
    actor_role: str,
    reviewed_at: str | None = None,
    idempotency_key: str | None = None,
    _commit: bool = True,
) -> dict[str, Any]:
    normalized_status = _required(status, "governed_inference_review_status_required").lower()
    if normalized_status not in REVIEW_STATUSES:
        raise ValueError("governed_inference_review_status_invalid")
    actor_value = _required(actor, "governed_inference_reviewer_required")
    role_value = _required(actor_role, "governed_inference_reviewer_role_required")
    rationale_value = _required(rationale, "governed_inference_review_rationale_required")
    qualification_value = _review_assessment(qualification_assessment)
    prohibited_value = _review_assessment(prohibited_class_assessment)
    contrary_value = str(contrary_evidence_note or "").strip()
    self_review = int(actor_value == str(get_inference(conn, inference_id)["created_by"]))
    payload = {
        "inference_id": int(inference_id),
        "status": normalized_status,
        "rationale": rationale_value,
        "qualification_assessment": qualification_value,
        "prohibited_class_assessment": prohibited_value,
        "contrary_evidence_note": contrary_value,
        "is_self_review": bool(self_review),
    }
    key = str(idempotency_key or "").strip() or _key("stage63-review:", payload)
    ensure_inference_tables(conn)
    existing = conn.execute("SELECT * FROM record_governed_inference_reviews WHERE idempotency_key = ?", (key,)).fetchone()
    payload_json = _json(payload)
    if existing is not None:
        if str(existing["request_payload_json"]) != payload_json:
            raise ValueError("governed_inference_review_idempotency_conflict")
        return get_inference(conn, inference_id)
    inference = get_inference(conn, inference_id)
    if inference["status"] in {"rejected", "superseded"}:
        raise ValueError("governed_inference_review_terminal")
    if normalized_status == "accepted_as_inference" and inference["status"] not in {"proposed", "deferred", "accepted_as_inference"}:
        raise ValueError("governed_inference_review_transition_invalid")
    conn.execute(
        """INSERT INTO record_governed_inference_reviews
        (inference_id, status, reviewed_at, reviewed_by, reviewed_by_role, rationale,
         qualification_assessment_json, prohibited_class_assessment_json,
         contrary_evidence_note, is_self_review, idempotency_key, request_payload_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (int(inference_id), normalized_status, str(reviewed_at or utc_now()), actor_value,
         role_value, rationale_value, _json(qualification_value), _json(prohibited_value),
         contrary_value, self_review, key, payload_json),
    )
    conn.execute("UPDATE record_governed_inferences SET status = ? WHERE id = ?", (normalized_status, int(inference_id)))
    if _commit:
        conn.commit()
    return get_inference(conn, inference_id)


def supersede_inference(
    conn: sqlite3.Connection,
    inference_id: int | str,
    *,
    replacement_inference_id: int | str | None,
    rationale: str,
    actor: str,
    actor_role: str,
    evidence_references: list[Mapping[str, Any]] | None = None,
    occurred_at: str | None = None,
    idempotency_key: str | None = None,
    _commit: bool = True,
) -> dict[str, Any]:
    actor_value = _required(actor, "governed_inference_supersession_actor_required")
    role_value = _required(actor_role, "governed_inference_supersession_role_required")
    rationale_value = _required(rationale, "governed_inference_supersession_rationale_required")
    refs = []
    for item in evidence_references or []:
        if not isinstance(item, Mapping):
            raise ValueError("governed_inference_supersession_evidence_invalid")
        refs.append({"reference_type": _required(item.get("reference_type"), "governed_inference_supersession_evidence_invalid"), "reference_id": _required(item.get("reference_id"), "governed_inference_supersession_evidence_invalid")})
    refs.sort(key=lambda item: (item["reference_type"], item["reference_id"]))
    payload = {"inference_id": int(inference_id), "replacement_inference_id": int(replacement_inference_id) if replacement_inference_id is not None else None, "rationale": rationale_value, "evidence_references": refs}
    key = str(idempotency_key or "").strip() or _key("stage63-supersession:", payload)
    ensure_inference_tables(conn)
    existing = conn.execute("SELECT * FROM record_governed_inference_supersessions WHERE idempotency_key = ?", (key,)).fetchone()
    payload_json = _json(payload)
    if existing is not None:
        if str(existing["request_payload_json"]) != payload_json:
            raise ValueError("governed_inference_supersession_idempotency_conflict")
        return get_inference(conn, inference_id)
    inference = get_inference(conn, inference_id)
    if inference["status"] != "accepted_as_inference":
        raise ValueError("governed_inference_supersession_terminal")
    replacement = None
    if replacement_inference_id is not None:
        replacement = get_inference(conn, replacement_inference_id)
        if int(replacement["id"]) == int(inference_id):
            raise ValueError("governed_inference_supersession_self_reference")
    payload["replacement_inference_id"] = int(replacement["id"]) if replacement else None
    payload_json = _json(payload)
    conn.execute(
        """INSERT INTO record_governed_inference_supersessions
        (inference_id, replacement_inference_id, event_type, rationale, actor,
         actor_role, occurred_at, evidence_references_json, idempotency_key, request_payload_json)
        VALUES (?, ?, 'superseded', ?, ?, ?, ?, ?, ?, ?)""",
        (int(inference_id), int(replacement["id"]) if replacement else None, rationale_value,
         actor_value, role_value, str(occurred_at or utc_now()), _json(refs), key, payload_json),
    )
    conn.execute("UPDATE record_governed_inferences SET status = 'superseded' WHERE id = ?", (int(inference_id),))
    if _commit:
        conn.commit()
    return get_inference(conn, inference_id)
