"""Stage 65 human-recorded governed responses.

A response records participation attributed to a source in relation to one
Stage 64 allegation.  It does not resolve the allegation or establish that
the response is true, false, adequate, or legally effective.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from api import record_governed_allegations as allegations

SCHEMA_VERSION = "stage65.human_governed_response.v1"
AUTHORING_MODE = "human_recorded"
RESPONSE_CATEGORIES = {
    "substantive_response", "partial_response", "contextual_response",
    "procedural_objection", "request_for_particulars", "correction_of_attribution",
    "express_declination",
}
REPRESENTATION_MODES = {"verbatim", "faithful_paraphrase"}
REVIEW_DISPOSITIONS = {
    "accepted_as_attributed_response", "requires_attribution_correction",
    "not_accepted_as_attributed",
}
RESPONSE_STATUSES = {"recorded", *REVIEW_DISPOSITIONS, "superseded", "withdrawn"}
CREATION_BINDING_ROLES = {
    "response_source", "notice_source", "contextual_source", "contrary_source",
}
WITHDRAWAL_BINDING_ROLE = "withdrawal_source"
SOURCE_TYPES = allegations.SOURCE_TYPES


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _required(value: Any, error: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise ValueError(error)
    return result


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?", (name,)
    ).fetchone() is not None


def _qualification_contract(value: Any, limitations: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("governed_response_qualification_contract_required")
    expected = {
        "epistemic_label": "response", "attribution_present": True,
        "source_basis_present": True, "not_evidence": True,
        "not_observation": True, "not_inference": True,
        "not_determination": True, "not_confirmation": True,
        "not_resolution": True, "not_admission": True,
        "alternatives_possible": True,
    }
    if any(value.get(k) != v for k, v in expected.items()):
        raise ValueError("governed_response_qualification_contract_incomplete")
    result = dict(expected)
    result["limitations"] = _required(limitations, "governed_response_limitations_required")
    return result


def _declaration(value: Any, error: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or value.get("acknowledged") is not True:
        raise ValueError(error)
    return {"human_recorded": True, "acknowledged": True, "boundary": "response_not_resolution"}


def ensure_response_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS record_governed_responses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            idempotency_key TEXT NOT NULL UNIQUE, schema_version TEXT NOT NULL,
            authoring_mode TEXT NOT NULL, response_category TEXT NOT NULL,
            response_text TEXT NOT NULL, representation_mode TEXT NOT NULL,
            representation_contract_json TEXT NOT NULL,
            attributed_respondent_label TEXT NOT NULL, attribution_context TEXT NOT NULL,
            subject_label TEXT NOT NULL, respondent_capacity TEXT NOT NULL,
            response_period TEXT, recorded_at TEXT, notice_details TEXT,
            rationale TEXT NOT NULL, qualification TEXT NOT NULL, limitations TEXT NOT NULL,
            qualification_contract_json TEXT NOT NULL, recorder_declaration_json TEXT NOT NULL,
            status TEXT NOT NULL, created_at TEXT NOT NULL, created_by TEXT NOT NULL,
            created_by_role TEXT NOT NULL, request_payload_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS record_governed_response_allegation_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT, response_id INTEGER NOT NULL,
            allegation_id INTEGER NOT NULL, created_at TEXT NOT NULL,
            UNIQUE(response_id), FOREIGN KEY(response_id) REFERENCES record_governed_responses(id),
            FOREIGN KEY(allegation_id) REFERENCES record_governed_allegations(id)
        );
        CREATE TABLE IF NOT EXISTS record_governed_response_bindings (
            id INTEGER PRIMARY KEY AUTOINCREMENT, response_id INTEGER NOT NULL,
            source_type TEXT NOT NULL, source_id TEXT NOT NULL, binding_role TEXT NOT NULL,
            source_version TEXT, source_timestamp TEXT,
            UNIQUE(response_id, source_type, source_id, binding_role),
            FOREIGN KEY(response_id) REFERENCES record_governed_responses(id)
        );
        CREATE TABLE IF NOT EXISTS record_governed_response_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT, response_id INTEGER NOT NULL,
            disposition TEXT NOT NULL, reviewed_by TEXT NOT NULL, reviewed_by_role TEXT NOT NULL,
            rationale TEXT NOT NULL, boundary_declaration_json TEXT NOT NULL,
            is_self_review INTEGER NOT NULL, reviewed_at TEXT NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE, request_payload_json TEXT NOT NULL,
            FOREIGN KEY(response_id) REFERENCES record_governed_responses(id)
        );
        CREATE TABLE IF NOT EXISTS record_governed_response_supersessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, response_id INTEGER NOT NULL,
            replacement_response_id INTEGER NOT NULL, rationale TEXT NOT NULL,
            actor TEXT NOT NULL, actor_role TEXT NOT NULL, occurred_at TEXT NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE, request_payload_json TEXT NOT NULL,
            FOREIGN KEY(response_id) REFERENCES record_governed_responses(id),
            FOREIGN KEY(replacement_response_id) REFERENCES record_governed_responses(id)
        );
        CREATE TABLE IF NOT EXISTS record_governed_response_withdrawals (
            id INTEGER PRIMARY KEY AUTOINCREMENT, response_id INTEGER NOT NULL,
            withdrawal_type TEXT NOT NULL, rationale TEXT NOT NULL, actor TEXT NOT NULL,
            actor_role TEXT NOT NULL, occurred_at TEXT NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE, request_payload_json TEXT NOT NULL,
            FOREIGN KEY(response_id) REFERENCES record_governed_responses(id)
        );
        CREATE INDEX IF NOT EXISTS idx_governed_responses_created
            ON record_governed_responses(created_at, id);
        CREATE INDEX IF NOT EXISTS idx_governed_response_bindings_source
            ON record_governed_response_bindings(source_type, source_id, response_id);
        """
    )


def _canonical_bindings(bindings: Any, *, withdrawal: bool = False) -> list[dict[str, Any]]:
    if not isinstance(bindings, (list, tuple)) or not bindings:
        raise ValueError("governed_response_binding_required")
    allowed = {"source_type", "source_id", "binding_role", "source_version", "source_timestamp"}
    result = []
    for item in bindings:
        if not isinstance(item, Mapping) or set(item) - allowed:
            raise ValueError("governed_response_binding_invalid")
        source_type = _required(item.get("source_type"), "governed_response_source_type_required")
        source_id = _required(item.get("source_id"), "governed_response_source_id_required")
        role = _required(item.get("binding_role"), "governed_response_binding_role_required")
        if source_type not in SOURCE_TYPES:
            raise ValueError("governed_response_source_type_invalid")
        permitted = {WITHDRAWAL_BINDING_ROLE} if withdrawal else CREATION_BINDING_ROLES
        if role not in permitted:
            raise ValueError("governed_response_binding_role_invalid")
        result.append({
            "source_type": source_type, "source_id": source_id, "binding_role": role,
            "source_version": item.get("source_version"), "source_timestamp": item.get("source_timestamp"),
        })
    result.sort(key=lambda x: (x["source_type"], x["source_id"], x["binding_role"]))
    if len({(x["source_type"], x["source_id"], x["binding_role"]) for x in result}) != len(result):
        raise ValueError("governed_response_duplicate_binding")
    return result


def _validated_sources(conn: sqlite3.Connection, bindings: Any, *, document_root: Path | None = None, withdrawal: bool = False) -> list[dict[str, Any]]:
    normalized = []
    for item in _canonical_bindings(bindings, withdrawal=withdrawal):
        source = allegations._source_binding(conn, item, document_root=document_root)
        normalized.append(source)
    required_role = WITHDRAWAL_BINDING_ROLE if withdrawal else "response_source"
    if not any(item["binding_role"] == required_role for item in normalized):
        raise ValueError(f"governed_response_{required_role}_required")
    return normalized


def _key(prefix: str, payload: Mapping[str, Any]) -> str:
    return prefix + hashlib.sha256(_json(payload).encode()).hexdigest()


def _status(conn: sqlite3.Connection, response_id: int, base: str) -> str:
    if conn.execute("SELECT 1 FROM record_governed_response_supersessions WHERE response_id = ?", (response_id,)).fetchone():
        return "superseded"
    if conn.execute("SELECT 1 FROM record_governed_response_withdrawals WHERE response_id = ?", (response_id,)).fetchone():
        return "withdrawn"
    row = conn.execute("SELECT disposition FROM record_governed_response_reviews WHERE response_id = ? ORDER BY id DESC LIMIT 1", (response_id,)).fetchone()
    return str(row[0]) if row else base


def _row_json(row: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(row)
    for key in ("representation_contract_json", "qualification_contract_json", "recorder_declaration_json", "request_payload_json"):
        result[key.removesuffix("_json")] = json.loads(result.pop(key))
    return result


def get_response(conn: sqlite3.Connection, response_id: int | str) -> dict[str, Any]:
    if not _table_exists(conn, "record_governed_responses"):
        raise ValueError("governed_response_table_absent")
    row = conn.execute("SELECT * FROM record_governed_responses WHERE id = ?", (int(response_id),)).fetchone()
    if row is None:
        raise ValueError("governed_response_not_found")
    result = _row_json(row)
    result["status"] = _status(conn, int(response_id), str(result["status"]))
    link = conn.execute("SELECT allegation_id FROM record_governed_response_allegation_links WHERE response_id = ?", (int(response_id),)).fetchone()
    result["allegation_id"] = int(link[0]) if link else None
    result["bindings"] = [dict(x) for x in conn.execute("SELECT * FROM record_governed_response_bindings WHERE response_id = ? ORDER BY id", (int(response_id),)).fetchall()]
    result["reviews"] = []
    for review in conn.execute("SELECT * FROM record_governed_response_reviews WHERE response_id = ? ORDER BY id", (int(response_id),)).fetchall():
        item = dict(review); item["boundary_declaration"] = json.loads(item.pop("boundary_declaration_json")); item["request_payload"] = json.loads(item.pop("request_payload_json")); result["reviews"].append(item)
    result["supersessions"] = [dict(x) for x in conn.execute("SELECT * FROM record_governed_response_supersessions WHERE response_id = ? ORDER BY id", (int(response_id),)).fetchall()]
    result["withdrawals"] = [dict(x) for x in conn.execute("SELECT * FROM record_governed_response_withdrawals WHERE response_id = ? ORDER BY id", (int(response_id),)).fetchall()]
    result["allegation"] = allegations.get_allegation(conn, result["allegation_id"])
    return result


def list_responses(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    if not _table_exists(conn, "record_governed_responses"):
        return []
    return [get_response(conn, row[0]) for row in conn.execute("SELECT id FROM record_governed_responses ORDER BY created_at, id").fetchall()]


def read_response_diagnostic(response_id: int | str | None = None, *, db_path: str | Path) -> dict[str, Any]:
    path = Path(db_path)
    if not path.is_file():
        return {"status": "database_unavailable", "responses": []}
    try:
        conn = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True); conn.row_factory = sqlite3.Row
    except sqlite3.Error:
        return {"status": "database_unavailable", "responses": []}
    try:
        if not _table_exists(conn, "record_governed_responses"):
            return {"status": "ok", "responses": [], "response_table_present": False}
        if response_id is None:
            return {"status": "ok", "responses": list_responses(conn), "response_table_present": True}
        try:
            return {"status": "ok", "responses": [get_response(conn, response_id)], "response_table_present": True}
        except (ValueError, TypeError):
            return {"status": "response_not_found", "responses": [], "response_table_present": True}
    finally:
        conn.close()


def create_response(conn: sqlite3.Connection, *, allegation_id: int | str, response_category: str,
                    response_text: str, representation_mode: str, representation_contract: Mapping[str, Any],
                    attributed_respondent_label: str, attribution_context: str, subject_label: str,
                    respondent_capacity: str, response_period: str | None, recorded_at: str | None,
                    notice_details: str | None, rationale: str, qualification: str, limitations: str,
                    qualification_contract: Mapping[str, Any], bindings: list[Mapping[str, Any]],
                    recorder_declaration: Mapping[str, Any], actor: str, actor_role: str,
                    idempotency_key: str | None = None, created_at: str | None = None,
                    document_root: Path | None = None, _commit: bool = True) -> dict[str, Any]:
    category = _required(response_category, "governed_response_category_required").lower()
    if category not in RESPONSE_CATEGORIES: raise ValueError("governed_response_category_invalid")
    text = _required(response_text, "governed_response_text_required")
    mode = _required(representation_mode, "governed_response_representation_mode_required").lower()
    if mode not in REPRESENTATION_MODES: raise ValueError("governed_response_representation_mode_invalid")
    if not isinstance(representation_contract, Mapping) or representation_contract.get("human_verified") is not True:
        raise ValueError("governed_response_representation_contract_incomplete")
    if mode == "verbatim" and representation_contract.get("exact_source_wording") is not True:
        raise ValueError("governed_response_exact_wording_required")
    if mode == "faithful_paraphrase" and representation_contract.get("faithful_representation") is not True:
        raise ValueError("governed_response_faithful_representation_required")
    allegation_id_value = int(allegation_id)
    target = allegations.get_allegation(conn, allegation_id_value)
    source_label = _required(attributed_respondent_label, "governed_response_attributed_respondent_required")
    context = _required(attribution_context, "governed_response_attribution_context_required")
    subject = _required(subject_label, "governed_response_subject_required")
    capacity = _required(respondent_capacity, "governed_response_capacity_required")
    rationale_value = _required(rationale, "governed_response_rationale_required")
    qualification_value = _required(qualification, "governed_response_qualification_required")
    limitations_value = _required(limitations, "governed_response_limitations_required")
    notice_value = str(notice_details or "").strip() or None
    normalized = _validated_sources(conn, bindings, document_root=document_root)
    if category == "express_declination" and representation_contract.get("express_declination_source") is not True:
        raise ValueError("governed_response_express_declination_source_declaration_required")
    if notice_value and not any(x["binding_role"] == "notice_source" for x in normalized):
        raise ValueError("governed_response_notice_source_required")
    contract = _qualification_contract(qualification_contract, limitations_value)
    declaration = _declaration(recorder_declaration, "governed_response_recorder_boundary_declaration_required")
    payload = {"schema_version": SCHEMA_VERSION, "authoring_mode": AUTHORING_MODE, "allegation_id": allegation_id_value, "response_category": category, "response_text": text, "representation_mode": mode, "representation_contract": {"human_verified": True, "exact_source_wording": mode == "verbatim", "faithful_representation": mode == "faithful_paraphrase"}, "attributed_respondent_label": source_label, "attribution_context": context, "subject_label": subject, "respondent_capacity": capacity, "response_period": str(response_period).strip() if response_period else None, "recorded_at": str(recorded_at).strip() if recorded_at else None, "notice_details": notice_value, "rationale": rationale_value, "qualification": qualification_value, "limitations": limitations_value, "qualification_contract": contract, "bindings": normalized, "recorder_declaration": declaration}
    key = str(idempotency_key or "").strip() or _key("stage65-response:", payload)
    ensure_response_tables(conn)
    payload_json = _json(payload)
    existing = conn.execute("SELECT * FROM record_governed_responses WHERE idempotency_key = ?", (key,)).fetchone()
    if existing is not None:
        if str(existing["request_payload_json"]) != payload_json: raise ValueError("governed_response_idempotency_conflict")
        return get_response(conn, existing["id"])
    try:
        cursor = conn.execute("""INSERT INTO record_governed_responses
            (idempotency_key,schema_version,authoring_mode,response_category,response_text,representation_mode,representation_contract_json,attributed_respondent_label,attribution_context,subject_label,respondent_capacity,response_period,recorded_at,notice_details,rationale,qualification,limitations,qualification_contract_json,recorder_declaration_json,status,created_at,created_by,created_by_role,request_payload_json)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (key, SCHEMA_VERSION, AUTHORING_MODE, category, text, mode, _json(payload["representation_contract"]), source_label, context, subject, capacity, payload["response_period"], payload["recorded_at"], notice_value, rationale_value, qualification_value, limitations_value, _json(contract), _json(declaration), "recorded", str(created_at or utc_now()), _required(actor, "governed_response_recorder_required"), _required(actor_role, "governed_response_recorder_role_required"), payload_json))
        response_id = int(cursor.lastrowid)
        conn.execute("INSERT INTO record_governed_response_allegation_links (response_id,allegation_id,created_at) VALUES (?,?,?)", (response_id, allegation_id_value, str(created_at or utc_now())))
        conn.executemany("INSERT INTO record_governed_response_bindings (response_id,source_type,source_id,binding_role,source_version,source_timestamp) VALUES (?,?,?,?,?,?)", [(response_id, x["source_type"], x["source_id"], x["binding_role"], x["source_version"], x["source_timestamp"]) for x in normalized])
        if _commit: conn.commit()
    except Exception:
        conn.rollback(); raise
    return get_response(conn, response_id)


def review_response(conn: sqlite3.Connection, response_id: int | str, *, disposition: str, rationale: str,
                    boundary_declaration: Mapping[str, Any], actor: str, actor_role: str,
                    reviewed_at: str | None = None, idempotency_key: str | None = None, _commit: bool = True) -> dict[str, Any]:
    response = get_response(conn, response_id); value = _required(disposition, "governed_response_review_disposition_required").lower()
    if value not in REVIEW_DISPOSITIONS: raise ValueError("governed_response_review_disposition_invalid")
    actor_value = _required(actor, "governed_response_reviewer_required"); role_value = _required(actor_role, "governed_response_reviewer_role_required"); rationale_value = _required(rationale, "governed_response_review_rationale_required")
    declaration = _declaration(boundary_declaration, "governed_response_review_boundary_declaration_required")
    payload = {"response_id": int(response_id), "disposition": value, "rationale": rationale_value, "boundary_declaration": declaration, "is_self_review": actor_value == str(response["created_by"])}
    key = str(idempotency_key or "").strip() or _key("stage65-review:", payload); ensure_response_tables(conn); payload_json = _json(payload)
    existing = conn.execute("SELECT * FROM record_governed_response_reviews WHERE idempotency_key = ?", (key,)).fetchone()
    if existing is not None:
        if str(existing["request_payload_json"]) != payload_json: raise ValueError("governed_response_review_idempotency_conflict")
        return get_response(conn, response_id)
    if response["status"] in {"superseded", "withdrawn"}: raise ValueError("governed_response_review_terminal")
    try:
        conn.execute("INSERT INTO record_governed_response_reviews (response_id,disposition,reviewed_by,reviewed_by_role,rationale,boundary_declaration_json,is_self_review,reviewed_at,idempotency_key,request_payload_json) VALUES (?,?,?,?,?,?,?,?,?,?)", (int(response_id), value, actor_value, role_value, rationale_value, _json(declaration), int(payload["is_self_review"]), str(reviewed_at or utc_now()), key, payload_json))
        if _commit: conn.commit()
    except Exception:
        conn.rollback(); raise
    return get_response(conn, response_id)


def _supersession_cycle(conn: sqlite3.Connection, response_id: int, replacement_id: int) -> bool:
    current, seen = replacement_id, set()
    while current not in seen:
        if current == response_id: return True
        seen.add(current)
        row = conn.execute("SELECT replacement_response_id FROM record_governed_response_supersessions WHERE response_id = ? ORDER BY id DESC LIMIT 1", (current,)).fetchone()
        if row is None: return False
        current = int(row[0])
    return False


def supersede_response(conn: sqlite3.Connection, response_id: int | str, *, replacement_response_id: int | str, rationale: str, actor: str, actor_role: str, occurred_at: str | None = None, idempotency_key: str | None = None, _commit: bool = True) -> dict[str, Any]:
    original = get_response(conn, response_id); replacement = get_response(conn, replacement_response_id)
    if int(response_id) == int(replacement_response_id): raise ValueError("governed_response_supersession_self_reference")
    if int(original["allegation_id"]) != int(replacement["allegation_id"]): raise ValueError("governed_response_supersession_target_mismatch")
    if _supersession_cycle(conn, int(response_id), int(replacement_response_id)): raise ValueError("governed_response_supersession_cycle")
    payload = {"response_id": int(response_id), "replacement_response_id": int(replacement_response_id), "rationale": _required(rationale, "governed_response_supersession_rationale_required")}; key = str(idempotency_key or "").strip() or _key("stage65-supersession:", payload); ensure_response_tables(conn); payload_json = _json(payload)
    existing = conn.execute("SELECT * FROM record_governed_response_supersessions WHERE idempotency_key = ?", (key,)).fetchone()
    if existing is not None:
        if str(existing["request_payload_json"]) != payload_json: raise ValueError("governed_response_supersession_idempotency_conflict")
        return get_response(conn, response_id)
    if original["status"] in {"superseded", "withdrawn"}: raise ValueError("governed_response_supersession_terminal")
    try:
        conn.execute("INSERT INTO record_governed_response_supersessions (response_id,replacement_response_id,rationale,actor,actor_role,occurred_at,idempotency_key,request_payload_json) VALUES (?,?,?,?,?,?,?,?)", (int(response_id), int(replacement_response_id), payload["rationale"], _required(actor, "governed_response_supersession_actor_required"), _required(actor_role, "governed_response_supersession_role_required"), str(occurred_at or utc_now()), key, payload_json))
        if _commit: conn.commit()
    except Exception:
        conn.rollback(); raise
    return get_response(conn, response_id)


def withdraw_response(conn: sqlite3.Connection, response_id: int | str, *, withdrawal_type: str, rationale: str, withdrawal_bindings: list[Mapping[str, Any]], actor: str, actor_role: str, occurred_at: str | None = None, idempotency_key: str | None = None, document_root: Path | None = None, _commit: bool = True) -> dict[str, Any]:
    response = get_response(conn, response_id)
    if withdrawal_type not in {"attributed_respondent_withdrawal", "administrative_attribution_correction"}: raise ValueError("governed_response_withdrawal_type_invalid")
    normalized = _validated_sources(conn, withdrawal_bindings, document_root=document_root, withdrawal=True)
    payload = {"response_id": int(response_id), "withdrawal_type": withdrawal_type, "rationale": _required(rationale, "governed_response_withdrawal_rationale_required"), "withdrawal_bindings": normalized}; key = str(idempotency_key or "").strip() or _key("stage65-withdrawal:", payload); ensure_response_tables(conn); payload_json = _json(payload)
    existing = conn.execute("SELECT * FROM record_governed_response_withdrawals WHERE idempotency_key = ?", (key,)).fetchone()
    if existing is not None:
        if str(existing["request_payload_json"]) != payload_json: raise ValueError("governed_response_withdrawal_idempotency_conflict")
        return get_response(conn, response_id)
    if response["status"] in {"superseded", "withdrawn"}: raise ValueError("governed_response_withdrawal_terminal")
    try:
        conn.execute("INSERT INTO record_governed_response_withdrawals (response_id,withdrawal_type,rationale,actor,actor_role,occurred_at,idempotency_key,request_payload_json) VALUES (?,?,?,?,?,?,?,?)", (int(response_id), withdrawal_type, payload["rationale"], _required(actor, "governed_response_withdrawal_actor_required"), _required(actor_role, "governed_response_withdrawal_role_required"), str(occurred_at or utc_now()), key, payload_json))
        conn.executemany("INSERT INTO record_governed_response_bindings (response_id,source_type,source_id,binding_role,source_version,source_timestamp) VALUES (?,?,?,?,?,?)", [(int(response_id), x["source_type"], x["source_id"], x["binding_role"], x["source_version"], x["source_timestamp"]) for x in normalized])
        if _commit: conn.commit()
    except Exception:
        conn.rollback(); raise
    return get_response(conn, response_id)
