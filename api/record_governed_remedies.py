"""Stage 69 human-recorded, determination-linked remedy preservation.

This module records a remedy or direction as represented in a Stage 67
determination.  It never records implementation, compliance, enforcement or
legal effect.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from api import record_governed_determinations as determinations
from api import record_governed_inferences as inferences

SCHEMA_VERSION = "stage69.human_governed_remedy.v1"
AUTHORING_MODE = "human_recorded"
REMEDY_CATEGORIES = {"payment_or_compensation", "reconsideration", "record_correction", "disclosure", "cessation_of_conduct", "procedural_rehearing", "institutional_action", "declaratory_relief", "no_remedy_directed"}
DIRECTION_TYPES = {"mandatory_direction", "recommendation", "declaration", "conditional_direction", "no_direction"}
REPRESENTATION_MODES = {"verbatim", "faithful_paraphrase"}
BINDING_ROLES = {"direction_source", "reasons_source", "contextual_source", "conditions_source", "contrary_source"}
SOURCE_TYPES = {"published_document", "canonical_record", "record_document_association", "accepted_pattern_observation"}
REVIEW_DISPOSITIONS = {"accepted_as_represented_direction", "requires_representation_correction", "not_accepted_as_represented_direction"}
STATUSES = {"recorded", "accepted_as_represented_direction", "representation_correction_required", "not_accepted_as_represented_direction", "superseded"}

QUALIFICATION_BOUNDARY = "This record preserves a remedy, direction or required action as represented in the identified governed determination. Its recording does not establish implementation, compliance, satisfaction, enforcement, lawfulness, validity, finality, entitlement, practical effect or completion."
LIMITATIONS_BOUNDARY = "The represented direction may be conditional, contested, stayed, varied, superseded, revoked, unimplemented, partially implemented or subject to later proceedings. Absence of later implementation evidence from the governed record does not establish non-compliance or non-performance."
AUTHOR_BOUNDARY = "I confirm that this is a human-recorded, determination-linked and source-bound representation of a remedy or direction. Recording it does not establish that the direction was implemented, complied with, enforced or legally effective."
REPRESENTATION_BOUNDARY = "The selected representation mode is a human declaration and is not machine-verified."
NO_REMEDY_BOUNDARY = "I confirm that the selected governed source expressly represents that no remedy or direction was made. This status is not inferred from silence, omission or missing material."
REVIEW_BOUNDARY = "Acceptance confirms only that the remedy or direction is appropriately preserved and attributed to the identified determination and source. It does not confirm implementation, compliance, enforceability, validity, entitlement or legal effect."

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

def _required(value: Any, error: str) -> str:
    result = str(value or "").strip()
    if not result: raise ValueError(error)
    return result

def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None

def _declaration(value: Any, error: str, boundary: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or value.get("acknowledged") is not True: raise ValueError(error)
    return {"human_recorded": True, "acknowledged": True, "boundary": boundary}

def _qualification(value: Any, limitations: str) -> dict[str, Any]:
    if not isinstance(value, Mapping): raise ValueError("governed_remedy_qualification_contract_required")
    expected = {"epistemic_label": "remedy_or_direction", "determination_link_present": True, "source_basis_present": True, "not_implementation": True, "not_compliance": True, "not_enforcement": True, "not_legal_effect": True}
    if any(value.get(k) != v for k, v in expected.items()): raise ValueError("governed_remedy_qualification_contract_incomplete")
    result = dict(expected); result["limitations"] = _required(limitations, "governed_remedy_limitations_required"); return result

def ensure_remedy_tables(conn: sqlite3.Connection) -> None:
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS record_governed_remedies (
      id INTEGER PRIMARY KEY AUTOINCREMENT, idempotency_key TEXT NOT NULL UNIQUE,
      schema_version TEXT NOT NULL, authoring_mode TEXT NOT NULL, remedy_category TEXT NOT NULL,
      direction_type TEXT NOT NULL, title_label TEXT NOT NULL, remedy_text TEXT NOT NULL,
      representation_mode TEXT NOT NULL, beneficiary_or_affected_party TEXT, obligated_party TEXT,
      amount TEXT, currency TEXT, performance_period_or_deadline TEXT, conditions_prerequisites TEXT,
      scope TEXT, limitations TEXT NOT NULL, implementation_description TEXT, rationale TEXT NOT NULL,
      qualification TEXT NOT NULL, qualification_contract_json TEXT NOT NULL,
      author_declaration_json TEXT NOT NULL, representation_declaration_json TEXT NOT NULL,
      no_remedy_declaration_json TEXT, status TEXT NOT NULL, created_by TEXT NOT NULL,
      created_by_role TEXT NOT NULL, created_at TEXT NOT NULL, request_payload_json TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS record_governed_remedy_determination_links (
      id INTEGER PRIMARY KEY AUTOINCREMENT, remedy_id INTEGER NOT NULL, determination_id INTEGER NOT NULL,
      UNIQUE(remedy_id), FOREIGN KEY(remedy_id) REFERENCES record_governed_remedies(id)
    );
    CREATE TABLE IF NOT EXISTS record_governed_remedy_bindings (
      id INTEGER PRIMARY KEY AUTOINCREMENT, remedy_id INTEGER NOT NULL, source_type TEXT NOT NULL,
      source_id TEXT NOT NULL, binding_role TEXT NOT NULL, source_version TEXT, source_timestamp TEXT,
      UNIQUE(remedy_id, source_type, source_id, binding_role)
    );
    CREATE TABLE IF NOT EXISTS record_governed_remedy_reviews (
      id INTEGER PRIMARY KEY AUTOINCREMENT, remedy_id INTEGER NOT NULL, disposition TEXT NOT NULL,
      reviewed_by TEXT NOT NULL, reviewed_by_role TEXT NOT NULL, rationale TEXT NOT NULL,
      boundary_declaration_json TEXT NOT NULL, is_self_review INTEGER NOT NULL, reviewed_at TEXT NOT NULL,
      idempotency_key TEXT NOT NULL UNIQUE, request_payload_json TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS record_governed_remedy_supersessions (
      id INTEGER PRIMARY KEY AUTOINCREMENT, remedy_id INTEGER NOT NULL, replacement_remedy_id INTEGER NOT NULL,
      rationale TEXT NOT NULL, actor TEXT NOT NULL, actor_role TEXT NOT NULL, occurred_at TEXT NOT NULL,
      idempotency_key TEXT NOT NULL UNIQUE, request_payload_json TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_stage69_remedy_status ON record_governed_remedies(status, created_at);
    """)

def _key(prefix: str, payload: Mapping[str, Any]) -> str:
    return prefix + hashlib.sha256(_json(payload).encode()).hexdigest()

def _canonical_bindings(bindings: Any) -> list[dict[str, Any]]:
    if not isinstance(bindings, (list, tuple)) or not bindings: raise ValueError("governed_remedy_binding_required")
    result = []
    for item in bindings:
        if not isinstance(item, Mapping) or set(item) - {"source_type", "source_id", "binding_role", "source_version", "source_timestamp"}: raise ValueError("governed_remedy_binding_invalid")
        source_type = _required(item.get("source_type"), "governed_remedy_source_type_required")
        source_id = _required(item.get("source_id"), "governed_remedy_source_id_required")
        role = _required(item.get("binding_role"), "governed_remedy_binding_role_required")
        if source_type not in SOURCE_TYPES or role not in BINDING_ROLES: raise ValueError("governed_remedy_binding_invalid")
        result.append({"source_type": source_type, "source_id": source_id, "binding_role": role, "source_version": item.get("source_version"), "source_timestamp": item.get("source_timestamp")})
    result.sort(key=lambda x: (x["source_type"], x["source_id"], x["binding_role"]))
    if len({(x["source_type"], x["source_id"], x["binding_role"]) for x in result}) != len(result): raise ValueError("governed_remedy_duplicate_binding")
    if not any(x["binding_role"] == "direction_source" for x in result): raise ValueError("governed_remedy_direction_source_required")
    return result

def _validate_bindings(conn: sqlite3.Connection, bindings: Any, document_root: Path | None = None) -> list[dict[str, Any]]:
    result = []
    for item in _canonical_bindings(bindings):
        result.append(inferences._source_binding(conn, item, document_root=document_root))
    return result

def _determination(conn: sqlite3.Connection, value: int | str) -> dict[str, Any]:
    try: item = determinations.get_determination(conn, int(value))
    except (ValueError, TypeError): raise ValueError("governed_remedy_determination_not_found") from None
    if item.get("status") != "accepted_as_attributed_determination_record": raise ValueError("governed_remedy_determination_not_eligible")
    return item

def _row(row: sqlite3.Row | Mapping[str, Any]) -> dict[str, Any]:
    result = dict(row)
    for field in ("qualification_contract_json", "author_declaration_json", "representation_declaration_json", "no_remedy_declaration_json", "request_payload_json"):
        if field in result: result[field.removesuffix("_json")] = json.loads(result.pop(field)) if result[field] else None
    return result

def _status(conn: sqlite3.Connection, remedy_id: int, base: str) -> str:
    if conn.execute("SELECT 1 FROM record_governed_remedy_supersessions WHERE remedy_id=?", (remedy_id,)).fetchone(): return "superseded"
    row = conn.execute("SELECT disposition FROM record_governed_remedy_reviews WHERE remedy_id=? ORDER BY id DESC LIMIT 1", (remedy_id,)).fetchone()
    if not row: return base
    return "representation_correction_required" if str(row[0]) == "requires_representation_correction" else str(row[0])

def get_remedy(conn: sqlite3.Connection, remedy_id: int | str) -> dict[str, Any]:
    if not _table_exists(conn, "record_governed_remedies"): raise ValueError("governed_remedy_table_absent")
    row = conn.execute("SELECT * FROM record_governed_remedies WHERE id=?", (int(remedy_id),)).fetchone()
    if row is None: raise ValueError("governed_remedy_not_found")
    result = _row(row); result["status"] = _status(conn, int(remedy_id), result["status"])
    result["determination"] = dict(conn.execute("SELECT * FROM record_governed_remedy_determination_links WHERE remedy_id=?", (int(remedy_id),)).fetchone())
    result["bindings"] = [dict(x) for x in conn.execute("SELECT * FROM record_governed_remedy_bindings WHERE remedy_id=? ORDER BY id", (int(remedy_id),)).fetchall()]
    result["reviews"] = [dict(x) for x in conn.execute("SELECT * FROM record_governed_remedy_reviews WHERE remedy_id=? ORDER BY id", (int(remedy_id),)).fetchall()]
    result["supersessions"] = [dict(x) for x in conn.execute("SELECT * FROM record_governed_remedy_supersessions WHERE remedy_id=? ORDER BY id", (int(remedy_id),)).fetchall()]
    return result

def list_remedies(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    if not _table_exists(conn, "record_governed_remedies"): return []
    return [get_remedy(conn, row[0]) for row in conn.execute("SELECT id FROM record_governed_remedies ORDER BY created_at,id").fetchall()]

def read_remedy_diagnostic(remedy_id: int | str | None = None, *, db_path: str | Path) -> dict[str, Any]:
    path = Path(db_path)
    if not path.is_file(): return {"status": "database_unavailable", "remedies": []}
    try:
        conn = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True); conn.row_factory = sqlite3.Row
    except sqlite3.Error: return {"status": "database_unavailable", "remedies": []}
    try:
        if not _table_exists(conn, "record_governed_remedies"): return {"status": "ok", "remedies": [], "remedy_table_present": False}
        if remedy_id is None: return {"status": "ok", "remedies": list_remedies(conn), "remedy_table_present": True}
        try: return {"status": "ok", "remedies": [get_remedy(conn, remedy_id)], "remedy_table_present": True}
        except ValueError: return {"status": "remedy_not_found", "remedies": [], "remedy_table_present": True}
    finally: conn.close()

def create_remedy(conn: sqlite3.Connection, *, remedy_category: str, direction_type: str, title_label: str, remedy_text: str, representation_mode: str, beneficiary_or_affected_party: str | None, obligated_party: str | None, amount: str | None, currency: str | None, performance_period_or_deadline: str | None, conditions_prerequisites: str | None, scope: str | None, limitations: str, implementation_description: str | None, rationale: str, qualification: str, determination_id: int | str, qualification_contract: Mapping[str, Any], author_declaration: Mapping[str, Any], representation_declaration: Mapping[str, Any], no_remedy_declaration: Mapping[str, Any] | None, bindings: Any, actor: str, actor_role: str, idempotency_key: str | None = None, created_at: str | None = None, document_root: Path | None = None, _commit: bool = True) -> dict[str, Any]:
    category = _required(remedy_category, "governed_remedy_category_required").lower(); direction = _required(direction_type, "governed_remedy_direction_type_required").lower(); mode = _required(representation_mode, "governed_remedy_representation_mode_required").lower()
    if category not in REMEDY_CATEGORIES: raise ValueError("governed_remedy_category_invalid")
    if direction not in DIRECTION_TYPES: raise ValueError("governed_remedy_direction_type_invalid")
    if mode not in REPRESENTATION_MODES: raise ValueError("governed_remedy_representation_mode_invalid")
    if (direction == "no_direction") != (category == "no_remedy_directed"): raise ValueError("governed_remedy_direction_category_mismatch")
    if category == "no_remedy_directed" and any(str(x or "").strip() for x in (remedy_text, beneficiary_or_affected_party, obligated_party, amount, currency, performance_period_or_deadline, conditions_prerequisites, scope, implementation_description)): raise ValueError("governed_remedy_no_remedy_affirmative_fields")
    if category != "no_remedy_directed": _required(remedy_text, "governed_remedy_text_required")
    determination = _determination(conn, determination_id)
    qualified = _qualification(qualification_contract, limitations)
    author = _declaration(author_declaration, "governed_remedy_author_declaration_required", AUTHOR_BOUNDARY)
    representation = _declaration(representation_declaration, "governed_remedy_representation_declaration_required", REPRESENTATION_BOUNDARY); representation["mode"] = mode
    no_remedy = None
    if category == "no_remedy_directed": no_remedy = _declaration(no_remedy_declaration, "governed_remedy_no_remedy_declaration_required", NO_REMEDY_BOUNDARY)
    elif no_remedy_declaration is not None and isinstance(no_remedy_declaration, Mapping) and no_remedy_declaration.get("acknowledged") is True: raise ValueError("governed_remedy_no_remedy_declaration_inapplicable")
    normalized = _validate_bindings(conn, bindings, document_root=document_root)
    payload = {"remedy_category":category,"direction_type":direction,"title_label":_required(title_label,"governed_remedy_title_required"),"remedy_text":str(remedy_text or "").strip(),"representation_mode":mode,"beneficiary_or_affected_party":beneficiary_or_affected_party,"obligated_party":obligated_party,"amount":amount,"currency":currency,"performance_period_or_deadline":performance_period_or_deadline,"conditions_prerequisites":conditions_prerequisites,"scope":scope,"limitations":_required(limitations,"governed_remedy_limitations_required"),"implementation_description":implementation_description,"rationale":_required(rationale,"governed_remedy_rationale_required"),"qualification":_required(qualification,"governed_remedy_qualification_required"),"determination_id":int(determination["id"]),"qualification_contract":qualified,"author_declaration":author,"representation_declaration":representation,"no_remedy_declaration":no_remedy,"bindings":normalized}
    key = str(idempotency_key or "").strip() or _key("stage69-remedy:", payload); ensure_remedy_tables(conn); payload_json = _json(payload)
    existing = conn.execute("SELECT * FROM record_governed_remedies WHERE idempotency_key=?", (key,)).fetchone()
    if existing is not None:
        if existing["request_payload_json"] != payload_json: raise ValueError("governed_remedy_idempotency_conflict")
        return get_remedy(conn, existing["id"])
    try:
        cur = conn.execute("INSERT INTO record_governed_remedies (idempotency_key,schema_version,authoring_mode,remedy_category,direction_type,title_label,remedy_text,representation_mode,beneficiary_or_affected_party,obligated_party,amount,currency,performance_period_or_deadline,conditions_prerequisites,scope,limitations,implementation_description,rationale,qualification,qualification_contract_json,author_declaration_json,representation_declaration_json,no_remedy_declaration_json,status,created_by,created_by_role,created_at,request_payload_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (key,SCHEMA_VERSION,AUTHORING_MODE,category,direction,payload["title_label"],payload["remedy_text"],mode,beneficiary_or_affected_party,obligated_party,amount,currency,performance_period_or_deadline,conditions_prerequisites,scope,payload["limitations"],implementation_description,payload["rationale"],payload["qualification"],_json(qualified),_json(author),_json(representation),_json(no_remedy),"recorded",_required(actor,"governed_remedy_recorder_required"),_required(actor_role,"governed_remedy_recorder_role_required"),str(created_at or utc_now()),payload_json))
        remedy_id = int(cur.lastrowid); conn.execute("INSERT INTO record_governed_remedy_determination_links (remedy_id,determination_id) VALUES (?,?)", (remedy_id, determination["id"])); conn.executemany("INSERT INTO record_governed_remedy_bindings (remedy_id,source_type,source_id,binding_role,source_version,source_timestamp) VALUES (?,?,?,?,?,?)", [(remedy_id,x["source_type"],x["source_id"],x["binding_role"],x["source_version"],x["source_timestamp"]) for x in normalized])
        if _commit: conn.commit()
    except Exception: conn.rollback(); raise
    return get_remedy(conn, remedy_id)

def review_remedy(conn: sqlite3.Connection, *, remedy_id: int | str, disposition: str, rationale: str, boundary_declaration: Mapping[str, Any], actor: str, actor_role: str, idempotency_key: str | None = None, reviewed_at: str | None = None, _commit: bool = True) -> dict[str, Any]:
    target = get_remedy(conn, remedy_id); value = _required(disposition,"governed_remedy_review_disposition_required").lower()
    if value not in REVIEW_DISPOSITIONS: raise ValueError("governed_remedy_review_disposition_invalid")
    declaration = _declaration(boundary_declaration,"governed_remedy_review_declaration_required",REVIEW_BOUNDARY); payload = {"remedy_id":int(remedy_id),"disposition":value,"rationale":_required(rationale,"governed_remedy_review_rationale_required"),"boundary_declaration":declaration,"is_self_review":_required(actor,"governed_remedy_reviewer_required") == str(target["created_by"])}
    key = str(idempotency_key or "").strip() or _key("stage69-review:",payload); ensure_remedy_tables(conn); payload_json = _json(payload); existing = conn.execute("SELECT * FROM record_governed_remedy_reviews WHERE idempotency_key=?",(key,)).fetchone()
    if existing is not None:
        if existing["request_payload_json"] != payload_json: raise ValueError("governed_remedy_review_idempotency_conflict")
        return get_remedy(conn, remedy_id)
    try:
        conn.execute("INSERT INTO record_governed_remedy_reviews (remedy_id,disposition,reviewed_by,reviewed_by_role,rationale,boundary_declaration_json,is_self_review,reviewed_at,idempotency_key,request_payload_json) VALUES (?,?,?,?,?,?,?,?,?,?)",(int(remedy_id),value,_required(actor,"governed_remedy_reviewer_required"),_required(actor_role,"governed_remedy_reviewer_role_required"),payload["rationale"],_json(declaration),int(payload["is_self_review"]),str(reviewed_at or utc_now()),key,payload_json));
        if _commit: conn.commit()
    except Exception: conn.rollback(); raise
    return get_remedy(conn, remedy_id)

def supersede_remedy(conn: sqlite3.Connection, *, remedy_id: int | str, replacement_remedy_id: int | str, rationale: str, actor: str, actor_role: str, idempotency_key: str | None = None, occurred_at: str | None = None, _commit: bool = True) -> dict[str, Any]:
    original = get_remedy(conn, remedy_id); replacement = get_remedy(conn, replacement_remedy_id)
    if int(remedy_id) == int(replacement_remedy_id): raise ValueError("governed_remedy_supersession_self_reference")
    if int(original["determination"]["determination_id"]) != int(replacement["determination"]["determination_id"]): raise ValueError("governed_remedy_supersession_determination_mismatch")
    payload = {"remedy_id":int(remedy_id),"replacement_remedy_id":int(replacement_remedy_id),"rationale":_required(rationale,"governed_remedy_supersession_rationale_required")}; key = str(idempotency_key or "").strip() or _key("stage69-supersession:",payload); ensure_remedy_tables(conn); payload_json = _json(payload); existing = conn.execute("SELECT * FROM record_governed_remedy_supersessions WHERE idempotency_key=?",(key,)).fetchone()
    if existing is not None:
        if existing["request_payload_json"] != payload_json: raise ValueError("governed_remedy_supersession_idempotency_conflict")
        return get_remedy(conn, remedy_id)
    seen={int(remedy_id)}; cursor=int(replacement_remedy_id)
    while True:
        if cursor in seen: raise ValueError("governed_remedy_supersession_cycle_rejected")
        seen.add(cursor); row=conn.execute("SELECT replacement_remedy_id FROM record_governed_remedy_supersessions WHERE remedy_id=?",(cursor,)).fetchone()
        if row is None: break
        cursor=int(row[0])
    if conn.execute("SELECT 1 FROM record_governed_remedy_supersessions WHERE remedy_id=?",(remedy_id,)).fetchone(): raise ValueError("governed_remedy_already_superseded")
    try:
        conn.execute("INSERT INTO record_governed_remedy_supersessions (remedy_id,replacement_remedy_id,rationale,actor,actor_role,occurred_at,idempotency_key,request_payload_json) VALUES (?,?,?,?,?,?,?,?)",(int(remedy_id),int(replacement_remedy_id),payload["rationale"],_required(actor,"governed_remedy_actor_required"),_required(actor_role,"governed_remedy_actor_role_required"),str(occurred_at or utc_now()),key,payload_json));
        if _commit: conn.commit()
    except Exception: conn.rollback(); raise
    return get_remedy(conn, remedy_id)
