"""Stage 67 human-recorded, source-bound determination preservation.

This module records formal conclusions attributed to an accepted Stage 66
authority/mandate representation. It never makes, validates, or evaluates a
determination and never calculates legal effect.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from api import record_governed_decision_authorities as authorities
from api import record_governed_inferences as inferences

SCHEMA_VERSION = "stage67.human_governed_determination.v1"
AUTHORING_MODE = "human_recorded"
DETERMINATION_CATEGORIES = {
    "procedural_determination", "jurisdictional_determination", "evidential_determination",
    "merits_determination", "remedial_determination", "administrative_disposition",
    "status_determination",
}
REPRESENTATION_MODES = {"verbatim", "faithful_paraphrase"}
BINDING_ROLES = {
    "determination_source", "reasons_source", "evidence_considered_source",
    "procedural_record_source", "notice_or_service_source", "implementation_source",
    "contrary_or_challenge_source",
}
EFFECT_BINDING_ROLE = "effect_event_source"
SOURCE_TYPES = inferences.SOURCE_TYPES
DETERMINATION_SOURCE_TYPES = {"published_document", "canonical_record", "record_document_association"}
OBJECT_ROLES = {
    "observation_considered", "inference_considered", "allegation_considered",
    "response_considered", "authority_context", "contrary_material_considered",
}
OBJECT_TYPES = {
    "accepted_pattern_observation": "record_pattern_observations",
    "governed_inference": "record_governed_inferences",
    "governed_allegation": "record_governed_allegations",
    "governed_response": "record_governed_responses",
    "decision_authority": "record_governed_decision_authorities",
}
STATUSES = {
    "recorded", "accepted_as_attributed_determination_record",
    "requires_determination_record_correction", "not_accepted_as_attributed", "superseded",
}
REVIEW_DISPOSITIONS = {
    "accepted_as_attributed_determination_record",
    "requires_determination_record_correction", "not_accepted_as_attributed",
}
EFFECT_EVENT_TYPES = {
    "appeal_recorded", "review_proceeding_recorded", "variation_recorded", "stay_recorded",
    "revocation_recorded", "set_aside_recorded", "implementation_recorded", "replacement_recorded",
}


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
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def _declaration(value: Any, error: str, boundary: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or value.get("acknowledged") is not True:
        raise ValueError(error)
    return {"human_recorded": True, "acknowledged": True, "boundary": boundary}


def _qualification(value: Any, limitations: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("governed_determination_qualification_contract_required")
    expected = {
        "epistemic_label": "determination", "source_basis_present": True,
        "not_validation": True, "not_jurisdiction": True, "not_lawfulness": True,
        "not_correctness": True, "not_enforceability": True, "not_finality": True,
    }
    if any(value.get(key) != expected_value for key, expected_value in expected.items()):
        raise ValueError("governed_determination_qualification_contract_incomplete")
    result = dict(expected)
    result["limitations"] = _required(limitations, "governed_determination_limitations_required")
    return result


def _canonical_bindings(bindings: Any, *, effect: bool = False) -> list[dict[str, Any]]:
    if not isinstance(bindings, (list, tuple)) or not bindings:
        raise ValueError("governed_determination_binding_required")
    allowed = {EFFECT_BINDING_ROLE} if effect else BINDING_ROLES
    result = []
    for item in bindings:
        if not isinstance(item, Mapping) or set(item) - {"source_type", "source_id", "binding_role", "source_version", "source_timestamp"}:
            raise ValueError("governed_determination_binding_invalid")
        source_type = _required(item.get("source_type"), "governed_determination_source_type_required")
        source_id = _required(item.get("source_id"), "governed_determination_source_id_required")
        role = _required(item.get("binding_role"), "governed_determination_binding_role_required")
        if source_type not in SOURCE_TYPES or role not in allowed:
            raise ValueError("governed_determination_binding_invalid")
        result.append({"source_type": source_type, "source_id": source_id, "binding_role": role,
                       "source_version": item.get("source_version"), "source_timestamp": item.get("source_timestamp")})
    result.sort(key=lambda item: (item["source_type"], item["source_id"], item["binding_role"]))
    if len({(x["source_type"], x["source_id"], x["binding_role"]) for x in result}) != len(result):
        raise ValueError("governed_determination_duplicate_binding")
    required = EFFECT_BINDING_ROLE if effect else "determination_source"
    if not any(item["binding_role"] == required for item in result):
        raise ValueError(f"governed_determination_{required}_required")
    if not effect and any(item["binding_role"] == required and item["source_type"] not in DETERMINATION_SOURCE_TYPES for item in result):
        raise ValueError("governed_determination_source_type_invalid")
    return result


def _validate_bindings(conn: sqlite3.Connection, bindings: Any, *, document_root: Path | None = None, effect: bool = False) -> list[dict[str, Any]]:
    result = []
    for item in _canonical_bindings(bindings, effect=effect):
        result.append(inferences._source_binding(conn, item, document_root=document_root))
    return result


def _canonical_objects(conn: sqlite3.Connection, links: Any) -> list[dict[str, Any]]:
    if links is None:
        return []
    if not isinstance(links, (list, tuple)):
        raise ValueError("governed_determination_object_links_invalid")
    result = []
    for item in links:
        if not isinstance(item, Mapping) or set(item) - {"object_type", "object_id", "relationship_role"}:
            raise ValueError("governed_determination_object_link_invalid")
        object_type = _required(item.get("object_type"), "governed_determination_object_type_required")
        object_id = _required(item.get("object_id"), "governed_determination_object_id_required")
        role = _required(item.get("relationship_role"), "governed_determination_object_role_required")
        if object_type not in OBJECT_TYPES or role not in OBJECT_ROLES:
            raise ValueError("governed_determination_object_link_invalid")
        if object_type == "accepted_pattern_observation" and role not in {"observation_considered", "contrary_material_considered"}:
            raise ValueError("governed_determination_object_role_mismatch")
        table = OBJECT_TYPES[object_type]
        if not _table_exists(conn, table):
            raise ValueError("governed_determination_object_not_found")
        row = conn.execute(f"SELECT id FROM {table} WHERE id=?", (int(object_id),)).fetchone()
        if row is None:
            raise ValueError("governed_determination_object_not_found")
        result.append({"object_type": object_type, "object_id": int(object_id), "relationship_role": role})
    result.sort(key=lambda item: (item["object_type"], item["object_id"], item["relationship_role"]))
    if len({(x["object_type"], x["object_id"], x["relationship_role"]) for x in result}) != len(result):
        raise ValueError("governed_determination_duplicate_object_link")
    return result


def ensure_determination_tables(conn: sqlite3.Connection) -> None:
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS record_governed_determinations (
      id INTEGER PRIMARY KEY AUTOINCREMENT, idempotency_key TEXT NOT NULL UNIQUE,
      schema_version TEXT NOT NULL, authoring_mode TEXT NOT NULL, determination_category TEXT NOT NULL,
      title_label TEXT NOT NULL, formal_outcome TEXT NOT NULL, representation_mode TEXT NOT NULL,
      issues_determined TEXT NOT NULL, reasons TEXT NOT NULL, reasons_status TEXT NOT NULL,
      decision_date_or_period TEXT, recorded_date TEXT, affected_subject_or_class TEXT NOT NULL,
      finality_description TEXT, implementation_or_remedy TEXT, qualification TEXT NOT NULL,
      limitations TEXT NOT NULL, qualification_contract_json TEXT NOT NULL,
      representation_declaration_json TEXT NOT NULL, authority_mandate_declaration_json TEXT NOT NULL,
      scope_declaration_json TEXT NOT NULL, recorder_declaration_json TEXT NOT NULL,
      status TEXT NOT NULL, created_by TEXT NOT NULL, created_by_role TEXT NOT NULL,
      created_at TEXT NOT NULL, request_payload_json TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS record_governed_determination_authority_links (
      id INTEGER PRIMARY KEY AUTOINCREMENT, determination_id INTEGER NOT NULL,
      authority_id INTEGER NOT NULL, mandate_id INTEGER NOT NULL,
      FOREIGN KEY(determination_id) REFERENCES record_governed_determinations(id)
    );
    CREATE TABLE IF NOT EXISTS record_governed_determination_bindings (
      id INTEGER PRIMARY KEY AUTOINCREMENT, determination_id INTEGER NOT NULL,
      source_type TEXT NOT NULL, source_id TEXT NOT NULL, binding_role TEXT NOT NULL,
      source_version TEXT, source_timestamp TEXT,
      UNIQUE(determination_id, source_type, source_id, binding_role)
    );
    CREATE TABLE IF NOT EXISTS record_governed_determination_governed_object_links (
      id INTEGER PRIMARY KEY AUTOINCREMENT, determination_id INTEGER NOT NULL,
      object_type TEXT NOT NULL, object_id INTEGER NOT NULL, relationship_role TEXT NOT NULL,
      UNIQUE(determination_id, object_type, object_id, relationship_role)
    );
    CREATE TABLE IF NOT EXISTS record_governed_determination_reviews (
      id INTEGER PRIMARY KEY AUTOINCREMENT, determination_id INTEGER NOT NULL,
      disposition TEXT NOT NULL, reviewed_by TEXT NOT NULL, reviewed_by_role TEXT NOT NULL,
      rationale TEXT NOT NULL, boundary_declaration_json TEXT NOT NULL,
      is_self_review INTEGER NOT NULL, reviewed_at TEXT NOT NULL,
      idempotency_key TEXT NOT NULL UNIQUE, request_payload_json TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS record_governed_determination_supersessions (
      id INTEGER PRIMARY KEY AUTOINCREMENT, determination_id INTEGER NOT NULL,
      replacement_determination_id INTEGER NOT NULL, rationale TEXT NOT NULL,
      actor TEXT NOT NULL, actor_role TEXT NOT NULL, occurred_at TEXT NOT NULL,
      idempotency_key TEXT NOT NULL UNIQUE, request_payload_json TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS record_governed_determination_effect_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT, determination_id INTEGER NOT NULL,
      event_type TEXT NOT NULL, represented_date_or_period TEXT NOT NULL,
      rationale TEXT NOT NULL, qualification TEXT NOT NULL, actor TEXT NOT NULL,
      actor_role TEXT NOT NULL, occurred_at TEXT NOT NULL, idempotency_key TEXT NOT NULL UNIQUE,
      request_payload_json TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_stage67_status ON record_governed_determinations(status, created_at);
    CREATE INDEX IF NOT EXISTS idx_stage67_bindings ON record_governed_determination_bindings(source_type, source_id, determination_id);
    """)


def _key(prefix: str, payload: Mapping[str, Any]) -> str:
    return prefix + hashlib.sha256(_json(payload).encode()).hexdigest()


def _date(value: Any) -> datetime.date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        if "T" in text:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
        return datetime.strptime(text, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _terminal_event_is_after(event: Mapping[str, Any], determination_date: str | None, scope_declaration: Mapping[str, Any]) -> bool:
    date = _date(determination_date)
    event_value = event.get("cessation_date_or_period") or event.get("occurred_at")
    event_date = _date(event_value)
    if date is None or event_date is None:
        if (determination_date or event_value) and scope_declaration.get("incomplete_dates_qualified") is not True:
            raise ValueError("governed_determination_temporal_qualification_required")
        return date is not None and event_date is not None and event_date > date
    return event_date > date


def _eligible_authority_as_of(record: Mapping[str, Any], determination_date: str | None, scope_declaration: Mapping[str, Any]) -> bool:
    if record.get("status") == "accepted_as_source_backed_authority_record":
        return True
    if record.get("status") not in {"ceased", "superseded"}:
        return False
    events = [*record.get("cessations", []), *record.get("supersessions", [])]
    return bool(events) and all(_terminal_event_is_after(event, determination_date, scope_declaration) for event in events)


def _authority_mandate(conn: sqlite3.Connection, authority_id: int | str, mandate_id: int | str, determination_date: str | None, scope_declaration: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    authority = authorities.get_authority(conn, authority_id)
    mandate = authorities.get_mandate(conn, mandate_id)
    if int(mandate["authority_id"]) != int(authority["id"]):
        raise ValueError("governed_determination_authority_mandate_mismatch")
    if not _eligible_authority_as_of(authority, determination_date, scope_declaration) or not _eligible_authority_as_of(mandate, determination_date, scope_declaration):
        raise ValueError("governed_determination_authority_mandate_not_accepted")
    return authority, mandate


def _temporal_check(determination_date: str | None, mandate: Mapping[str, Any], scope_declaration: Mapping[str, Any]) -> None:
    date = _date(determination_date)
    if determination_date and date is None:
        if scope_declaration.get("incomplete_dates_qualified") is not True:
            raise ValueError("governed_determination_temporal_qualification_required")
        return
    if date is None:
        return
    start, end = _date(mandate.get("effective_from")), _date(mandate.get("effective_to"))
    if mandate.get("effective_from") and start is None or mandate.get("effective_to") and end is None:
        if scope_declaration.get("incomplete_dates_qualified") is not True:
            raise ValueError("governed_determination_temporal_qualification_required")
        return
    if start and date < start:
        raise ValueError("governed_determination_before_mandate_period")
    if end and date > end:
        raise ValueError("governed_determination_after_mandate_period")


def _status(conn: sqlite3.Connection, determination_id: int, base: str) -> str:
    if conn.execute("SELECT 1 FROM record_governed_determination_supersessions WHERE determination_id=?", (determination_id,)).fetchone():
        return "superseded"
    row = conn.execute("SELECT disposition FROM record_governed_determination_reviews WHERE determination_id=? ORDER BY id DESC LIMIT 1", (determination_id,)).fetchone()
    return str(row[0]) if row else base


def _row(row: sqlite3.Row | Mapping[str, Any]) -> dict[str, Any]:
    result = dict(row)
    for field in ("qualification_contract_json", "representation_declaration_json", "authority_mandate_declaration_json", "scope_declaration_json", "recorder_declaration_json", "request_payload_json"):
        if field in result:
            result[field.removesuffix("_json")] = json.loads(result.pop(field))
    return result


def get_determination(conn: sqlite3.Connection, determination_id: int | str) -> dict[str, Any]:
    if not _table_exists(conn, "record_governed_determinations"):
        raise ValueError("governed_determination_table_absent")
    row = conn.execute("SELECT * FROM record_governed_determinations WHERE id=?", (int(determination_id),)).fetchone()
    if row is None:
        raise ValueError("governed_determination_not_found")
    result = _row(row)
    result["status"] = _status(conn, int(determination_id), result["status"])
    result["authority_mandate"] = dict(conn.execute("SELECT * FROM record_governed_determination_authority_links WHERE determination_id=?", (int(determination_id),)).fetchone())
    result["bindings"] = [dict(x) for x in conn.execute("SELECT * FROM record_governed_determination_bindings WHERE determination_id=? ORDER BY id", (int(determination_id),)).fetchall()]
    result["governed_objects"] = [dict(x) for x in conn.execute("SELECT * FROM record_governed_determination_governed_object_links WHERE determination_id=? ORDER BY id", (int(determination_id),)).fetchall()]
    result["reviews"] = [dict(x) for x in conn.execute("SELECT * FROM record_governed_determination_reviews WHERE determination_id=? ORDER BY id", (int(determination_id),)).fetchall()]
    result["supersessions"] = [dict(x) for x in conn.execute("SELECT * FROM record_governed_determination_supersessions WHERE determination_id=? ORDER BY id", (int(determination_id),)).fetchall()]
    result["effect_events"] = [dict(x) for x in conn.execute("SELECT * FROM record_governed_determination_effect_events WHERE determination_id=? ORDER BY id", (int(determination_id),)).fetchall()]
    return result


def list_determinations(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    if not _table_exists(conn, "record_governed_determinations"):
        return []
    return [get_determination(conn, row[0]) for row in conn.execute("SELECT id FROM record_governed_determinations ORDER BY created_at,id").fetchall()]


def read_determination_diagnostic(determination_id: int | str | None = None, *, db_path: str | Path) -> dict[str, Any]:
    path = Path(db_path)
    if not path.is_file():
        return {"status": "database_unavailable", "determinations": []}
    try:
        conn = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
    except sqlite3.Error:
        return {"status": "database_unavailable", "determinations": []}
    try:
        if not _table_exists(conn, "record_governed_determinations"):
            return {"status": "ok", "determinations": [], "determination_table_present": False}
        if determination_id is None:
            return {"status": "ok", "determinations": list_determinations(conn), "determination_table_present": True}
        try:
            return {"status": "ok", "determinations": [get_determination(conn, determination_id)], "determination_table_present": True}
        except ValueError:
            return {"status": "determination_not_found", "determinations": [], "determination_table_present": True}
    finally:
        conn.close()


def create_determination(conn: sqlite3.Connection, *, determination_category: str, title_label: str, formal_outcome: str, representation_mode: str, issues_determined: str, reasons: str, reasons_status: str, decision_date_or_period: str | None, recorded_date: str | None, affected_subject_or_class: str, finality_description: str | None, implementation_or_remedy: str | None, qualification: str, limitations: str, qualification_contract: Mapping[str, Any], authority_id: int | str, mandate_id: int | str, authority_mandate_declaration: Mapping[str, Any], scope_declaration: Mapping[str, Any], representation_declaration: Mapping[str, Any], recorder_declaration: Mapping[str, Any], bindings: list[Mapping[str, Any]], governed_objects: list[Mapping[str, Any]] | None, actor: str, actor_role: str, idempotency_key: str | None = None, created_at: str | None = None, document_root: Path | None = None, _commit: bool = True) -> dict[str, Any]:
    category = _required(determination_category, "governed_determination_category_required").lower()
    if category not in DETERMINATION_CATEGORIES: raise ValueError("governed_determination_category_invalid")
    mode = _required(representation_mode, "governed_determination_representation_mode_required").lower()
    if mode not in REPRESENTATION_MODES: raise ValueError("governed_determination_representation_mode_invalid")
    if reasons_status not in {"reasons_recorded", "no_reasons_recorded_in_source"}: raise ValueError("governed_determination_reasons_status_invalid")
    if reasons_status == "reasons_recorded": _required(reasons, "governed_determination_reasons_required")
    else:
        if str(reasons or "").strip() or not isinstance(authority_mandate_declaration, Mapping) or authority_mandate_declaration.get("no_reasons_acknowledged") is not True: raise ValueError("governed_determination_no_reasons_declaration_required")
    authority_decl = _declaration(authority_mandate_declaration, "governed_determination_authority_mandate_declaration_required", "authority_mandate_not_legally_validated")
    scope_decl = _declaration(scope_declaration, "governed_determination_scope_declaration_required", "scope_not_legally_validated")
    authority, mandate = _authority_mandate(conn, authority_id, mandate_id, decision_date_or_period, scope_decl)
    representation_decl = _declaration(representation_declaration, "governed_determination_representation_declaration_required", "representation_not_machine_verified")
    recorder_decl = _declaration(recorder_declaration, "governed_determination_recorder_declaration_required", "determination_not_made_by_cde")
    qualified = _qualification(qualification_contract, limitations)
    normalized = _validate_bindings(conn, bindings, document_root=document_root)
    objects = _canonical_objects(conn, governed_objects)
    if scope_declaration.get("incomplete_dates_qualified") is not True and any(not isinstance(x, str) for x in (decision_date_or_period, recorded_date) if x is not None): raise ValueError("governed_determination_date_invalid")
    _temporal_check(decision_date_or_period, mandate, scope_declaration)
    if representation_decl.get("mode") not in (None, mode): raise ValueError("governed_determination_representation_declaration_mismatch")
    payload = {"determination_category":category,"title_label":_required(title_label,"governed_determination_title_required"),"formal_outcome":_required(formal_outcome,"governed_determination_outcome_required"),"representation_mode":mode,"issues_determined":_required(issues_determined,"governed_determination_issues_required"),"reasons":str(reasons or "").strip(),"reasons_status":reasons_status,"decision_date_or_period":decision_date_or_period,"recorded_date":recorded_date,"affected_subject_or_class":_required(affected_subject_or_class,"governed_determination_affected_class_required"),"finality_description":finality_description,"implementation_or_remedy":implementation_or_remedy,"qualification":_required(qualification,"governed_determination_qualification_required"),"limitations":_required(limitations,"governed_determination_limitations_required"),"qualification_contract":qualified,"authority_id":int(authority["id"]),"mandate_id":int(mandate["id"]),"authority_mandate_declaration":authority_decl,"scope_declaration":scope_decl,"representation_declaration":representation_decl,"recorder_declaration":recorder_decl,"bindings":normalized,"governed_objects":objects}
    key = str(idempotency_key or "").strip() or _key("stage67-determination:", payload)
    ensure_determination_tables(conn); payload_json = _json(payload)
    existing = conn.execute("SELECT * FROM record_governed_determinations WHERE idempotency_key=?", (key,)).fetchone()
    if existing is not None:
        if existing["request_payload_json"] != payload_json: raise ValueError("governed_determination_idempotency_conflict")
        return get_determination(conn, existing["id"])
    try:
        cur = conn.execute("INSERT INTO record_governed_determinations (idempotency_key,schema_version,authoring_mode,determination_category,title_label,formal_outcome,representation_mode,issues_determined,reasons,reasons_status,decision_date_or_period,recorded_date,affected_subject_or_class,finality_description,implementation_or_remedy,qualification,limitations,qualification_contract_json,representation_declaration_json,authority_mandate_declaration_json,scope_declaration_json,recorder_declaration_json,status,created_by,created_by_role,created_at,request_payload_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (key,SCHEMA_VERSION,AUTHORING_MODE,payload["determination_category"],payload["title_label"],payload["formal_outcome"],mode,payload["issues_determined"],payload["reasons"],reasons_status,decision_date_or_period,recorded_date,payload["affected_subject_or_class"],finality_description,implementation_or_remedy,payload["qualification"],payload["limitations"],_json(qualified),_json(representation_decl),_json(authority_decl),_json(scope_decl),_json(recorder_decl),"recorded",_required(actor,"governed_determination_recorder_required"),_required(actor_role,"governed_determination_recorder_role_required"),str(created_at or utc_now()),payload_json))
        determination_id = int(cur.lastrowid)
        conn.execute("INSERT INTO record_governed_determination_authority_links (determination_id,authority_id,mandate_id) VALUES (?,?,?)", (determination_id,authority["id"],mandate["id"]))
        conn.executemany("INSERT INTO record_governed_determination_bindings (determination_id,source_type,source_id,binding_role,source_version,source_timestamp) VALUES (?,?,?,?,?,?)", [(determination_id,x["source_type"],x["source_id"],x["binding_role"],x["source_version"],x["source_timestamp"]) for x in normalized])
        conn.executemany("INSERT INTO record_governed_determination_governed_object_links (determination_id,object_type,object_id,relationship_role) VALUES (?,?,?,?)", [(determination_id,x["object_type"],x["object_id"],x["relationship_role"]) for x in objects])
        if _commit: conn.commit()
    except Exception:
        conn.rollback(); raise
    return get_determination(conn, determination_id)


def review_determination(conn: sqlite3.Connection, *, determination_id: int | str, disposition: str, rationale: str, boundary_declaration: Mapping[str, Any], actor: str, actor_role: str, idempotency_key: str | None = None, reviewed_at: str | None = None, _commit: bool = True) -> dict[str, Any]:
    target = get_determination(conn, determination_id)
    value = _required(disposition, "governed_determination_review_disposition_required").lower()
    if value not in REVIEW_DISPOSITIONS: raise ValueError("governed_determination_review_disposition_invalid")
    declaration = _declaration(boundary_declaration, "governed_determination_review_declaration_required", "review_not_merits_validation")
    payload = {"determination_id":int(determination_id),"disposition":value,"rationale":_required(rationale,"governed_determination_review_rationale_required"),"boundary_declaration":declaration,"is_self_review":_required(actor,"governed_determination_reviewer_required") == str(target["created_by"])}
    key = str(idempotency_key or "").strip() or _key("stage67-review:", payload); ensure_determination_tables(conn); payload_json = _json(payload)
    existing = conn.execute("SELECT * FROM record_governed_determination_reviews WHERE idempotency_key=?", (key,)).fetchone()
    if existing is not None:
        if existing["request_payload_json"] != payload_json: raise ValueError("governed_determination_review_idempotency_conflict")
        return get_determination(conn, determination_id)
    try:
        conn.execute("INSERT INTO record_governed_determination_reviews (determination_id,disposition,reviewed_by,reviewed_by_role,rationale,boundary_declaration_json,is_self_review,reviewed_at,idempotency_key,request_payload_json) VALUES (?,?,?,?,?,?,?,?,?,?)", (int(determination_id),value,_required(actor,"governed_determination_reviewer_required"),_required(actor_role,"governed_determination_reviewer_role_required"),payload["rationale"],_json(declaration),int(payload["is_self_review"]),str(reviewed_at or utc_now()),key,payload_json))
        if _commit: conn.commit()
    except Exception: conn.rollback(); raise
    return get_determination(conn, determination_id)


def supersede_determination(conn: sqlite3.Connection, *, determination_id: int | str, replacement_determination_id: int | str, rationale: str, actor: str, actor_role: str, idempotency_key: str | None = None, occurred_at: str | None = None, _commit: bool = True) -> dict[str, Any]:
    original = get_determination(conn, determination_id); replacement = get_determination(conn, replacement_determination_id)
    if int(determination_id) == int(replacement_determination_id): raise ValueError("governed_determination_supersession_self_reference")
    if original["affected_subject_or_class"] != replacement["affected_subject_or_class"]: raise ValueError("governed_determination_supersession_context_mismatch")
    payload = {"determination_id":int(determination_id),"replacement_determination_id":int(replacement_determination_id),"rationale":_required(rationale,"governed_determination_supersession_rationale_required")}; key = str(idempotency_key or "").strip() or _key("stage67-supersession:", payload); ensure_determination_tables(conn); payload_json = _json(payload)
    existing = conn.execute("SELECT * FROM record_governed_determination_supersessions WHERE idempotency_key=?", (key,)).fetchone()
    if existing is not None:
        if existing["request_payload_json"] != payload_json: raise ValueError("governed_determination_supersession_idempotency_conflict")
        return original
    seen = {int(determination_id)}; cursor = int(replacement_determination_id)
    while True:
        if cursor in seen: raise ValueError("governed_determination_supersession_cycle_rejected")
        seen.add(cursor); row = conn.execute("SELECT replacement_determination_id FROM record_governed_determination_supersessions WHERE determination_id=?", (cursor,)).fetchone()
        if row is None: break
        cursor = int(row[0])
    if conn.execute("SELECT 1 FROM record_governed_determination_supersessions WHERE determination_id=?", (int(determination_id),)).fetchone(): raise ValueError("governed_determination_supersession_terminal")
    try:
        conn.execute("INSERT INTO record_governed_determination_supersessions (determination_id,replacement_determination_id,rationale,actor,actor_role,occurred_at,idempotency_key,request_payload_json) VALUES (?,?,?,?,?,?,?,?)", (int(determination_id),int(replacement_determination_id),payload["rationale"],_required(actor,"governed_determination_actor_required"),_required(actor_role,"governed_determination_actor_role_required"),str(occurred_at or utc_now()),key,payload_json))
        if _commit: conn.commit()
    except Exception: conn.rollback(); raise
    return get_determination(conn, determination_id)


def record_effect_event(conn: sqlite3.Connection, *, determination_id: int | str, event_type: str, represented_date_or_period: str, rationale: str, qualification: str, effect_bindings: list[Mapping[str, Any]], actor: str, actor_role: str, idempotency_key: str | None = None, occurred_at: str | None = None, document_root: Path | None = None, _commit: bool = True) -> dict[str, Any]:
    target = get_determination(conn, determination_id)
    if event_type not in EFFECT_EVENT_TYPES: raise ValueError("governed_determination_effect_event_type_invalid")
    normalized = _validate_bindings(conn, effect_bindings, document_root=document_root, effect=True)
    payload = {"determination_id":int(determination_id),"event_type":event_type,"represented_date_or_period":_required(represented_date_or_period,"governed_determination_effect_event_date_required"),"rationale":_required(rationale,"governed_determination_effect_event_rationale_required"),"qualification":_required(qualification,"governed_determination_effect_event_qualification_required"),"bindings":normalized}; key = str(idempotency_key or "").strip() or _key("stage67-effect:", payload); ensure_determination_tables(conn); payload_json = _json(payload)
    existing = conn.execute("SELECT * FROM record_governed_determination_effect_events WHERE idempotency_key=?", (key,)).fetchone()
    if existing is not None:
        if existing["request_payload_json"] != payload_json: raise ValueError("governed_determination_effect_idempotency_conflict")
        return target
    try:
        conn.execute("INSERT INTO record_governed_determination_effect_events (determination_id,event_type,represented_date_or_period,rationale,qualification,actor,actor_role,occurred_at,idempotency_key,request_payload_json) VALUES (?,?,?,?,?,?,?,?,?,?)", (int(determination_id),event_type,payload["represented_date_or_period"],payload["rationale"],payload["qualification"],_required(actor,"governed_determination_actor_required"),_required(actor_role,"governed_determination_actor_role_required"),str(occurred_at or utc_now()),key,payload_json))
        if _commit: conn.commit()
    except Exception: conn.rollback(); raise
    return get_determination(conn, determination_id)
