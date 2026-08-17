"""Stage 66 human-recorded authority and mandate governance.

This module preserves source-backed representations only. It never confers
authority, validates an appointment, or determines that an act was authorised.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from api import record_governed_allegations as allegations

SCHEMA_VERSION = "stage66.human_governed_decision_authority.v1"
AUTHORING_MODE = "human_recorded"
HOLDER_KINDS = {"institution", "office", "role", "named_person", "panel_or_body"}
MANDATE_BASIS_CATEGORIES = {
    "statutory_instrument", "regulatory_instrument", "appointment_instrument",
    "delegation_instrument", "governance_instrument", "court_or_tribunal_order",
    "contractual_instrument", "other_formal_instrument",
}
BINDING_ROLES = {
    "authority_basis_source", "appointment_source", "delegation_source",
    "scope_source", "limitation_source", "contextual_source", "contrary_source",
}
CESSATION_BINDING_ROLE = "cessation_source"
CREATION_BINDING_ROLES = BINDING_ROLES
AUTHORITY_STATUSES = {"recorded", "accepted_as_source_backed_authority_record", "requires_authority_record_correction", "not_accepted_as_source_backed", "superseded", "ceased"}
REVIEW_DISPOSITIONS = {"accepted_as_source_backed_authority_record", "requires_authority_record_correction", "not_accepted_as_source_backed"}
CESSATION_TYPES = {"expiry_recorded", "revocation_recorded", "resignation_recorded", "termination_recorded", "replacement_recorded", "other_cessation_recorded"}
DELEGATION_STATUSES = {"not_delegated", "delegated"}
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
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?", (name,)).fetchone() is not None


def _declaration(value: Any, error: str, boundary: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or value.get("acknowledged") is not True:
        raise ValueError(error)
    return {"human_recorded": True, "acknowledged": True, "boundary": boundary}


def _qualification(value: Any, limitations: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("governed_authority_qualification_contract_required")
    required = {
        "epistemic_label": "authority", "source_basis_present": True,
        "not_conferral": True, "not_appointment_validation": True,
        "not_jurisdiction": True, "not_lawfulness": True,
        "not_determination": True, "alternatives_possible": True,
    }
    if any(value.get(key) != expected for key, expected in required.items()):
        raise ValueError("governed_authority_qualification_contract_incomplete")
    result = dict(required)
    result["limitations"] = _required(limitations, "governed_authority_limitations_required")
    return result


def ensure_authority_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS record_governed_decision_authorities (
            id INTEGER PRIMARY KEY AUTOINCREMENT, idempotency_key TEXT NOT NULL UNIQUE,
            schema_version TEXT NOT NULL, authoring_mode TEXT NOT NULL, holder_kind TEXT NOT NULL,
            holder_label TEXT NOT NULL, institution_context TEXT NOT NULL, office_role_capacity TEXT NOT NULL,
            named_holder TEXT, holder_effective_period TEXT, attribution_context TEXT NOT NULL,
            rationale TEXT NOT NULL, qualification TEXT NOT NULL, limitations TEXT NOT NULL,
            qualification_contract_json TEXT NOT NULL, recorder_declaration_json TEXT NOT NULL,
            appointment_declaration_json TEXT NOT NULL,
            status TEXT NOT NULL, created_by TEXT NOT NULL, created_by_role TEXT NOT NULL,
            created_at TEXT NOT NULL, request_payload_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS record_governed_decision_authority_mandates (
            id INTEGER PRIMARY KEY AUTOINCREMENT, idempotency_key TEXT NOT NULL UNIQUE,
            authority_id INTEGER NOT NULL, schema_version TEXT NOT NULL, mandate_basis_category TEXT NOT NULL,
            title_label TEXT NOT NULL, subject_matter_scope TEXT NOT NULL, procedural_scope TEXT NOT NULL,
            territorial_organisational_scope TEXT, affected_class TEXT, effective_from TEXT, effective_to TEXT,
            express_limitations TEXT NOT NULL, conditions_prerequisites TEXT NOT NULL,
            delegation_status TEXT NOT NULL, delegating_authority_id INTEGER, delegating_mandate_id INTEGER,
            rationale TEXT NOT NULL, qualification TEXT NOT NULL, limitations TEXT NOT NULL,
            qualification_contract_json TEXT NOT NULL, recorder_declaration_json TEXT NOT NULL,
            status TEXT NOT NULL, created_by TEXT NOT NULL, created_by_role TEXT NOT NULL,
            created_at TEXT NOT NULL, request_payload_json TEXT NOT NULL,
            FOREIGN KEY(authority_id) REFERENCES record_governed_decision_authorities(id)
        );
        CREATE TABLE IF NOT EXISTS record_governed_decision_authority_bindings (
            id INTEGER PRIMARY KEY AUTOINCREMENT, object_type TEXT NOT NULL, object_id INTEGER NOT NULL,
            source_type TEXT NOT NULL, source_id TEXT NOT NULL, binding_role TEXT NOT NULL,
            source_version TEXT, source_timestamp TEXT,
            UNIQUE(object_type, object_id, source_type, source_id, binding_role)
        );
        CREATE TABLE IF NOT EXISTS record_governed_decision_authority_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT, authority_id INTEGER NOT NULL, mandate_id INTEGER,
            disposition TEXT NOT NULL, reviewed_by TEXT NOT NULL, reviewed_by_role TEXT NOT NULL,
            rationale TEXT NOT NULL, boundary_declaration_json TEXT NOT NULL, is_self_review INTEGER NOT NULL,
            reviewed_at TEXT NOT NULL, idempotency_key TEXT NOT NULL UNIQUE, request_payload_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS record_governed_decision_authority_supersessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, object_type TEXT NOT NULL, object_id INTEGER NOT NULL,
            replacement_id INTEGER NOT NULL, rationale TEXT NOT NULL, actor TEXT NOT NULL,
            actor_role TEXT NOT NULL, occurred_at TEXT NOT NULL, idempotency_key TEXT NOT NULL UNIQUE,
            request_payload_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS record_governed_decision_authority_cessations (
            id INTEGER PRIMARY KEY AUTOINCREMENT, object_type TEXT NOT NULL, object_id INTEGER NOT NULL,
            cessation_type TEXT NOT NULL, cessation_date_or_period TEXT NOT NULL, rationale TEXT NOT NULL,
            actor TEXT NOT NULL, actor_role TEXT NOT NULL, occurred_at TEXT NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE, request_payload_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_stage66_authority_status ON record_governed_decision_authorities(status, created_at);
        CREATE INDEX IF NOT EXISTS idx_stage66_mandate_status ON record_governed_decision_authority_mandates(status, created_at);
        CREATE INDEX IF NOT EXISTS idx_stage66_bindings ON record_governed_decision_authority_bindings(source_type, source_id, object_type, object_id);
        """
    )


def _bindings(bindings: Any, *, cessation: bool = False) -> list[dict[str, Any]]:
    if not isinstance(bindings, (list, tuple)) or not bindings:
        raise ValueError("governed_authority_binding_required")
    allowed = {"source_type", "source_id", "binding_role", "source_version", "source_timestamp"}
    result = []
    for item in bindings:
        if not isinstance(item, Mapping) or set(item) - allowed:
            raise ValueError("governed_authority_binding_invalid")
        source_type = _required(item.get("source_type"), "governed_authority_source_type_required")
        source_id = _required(item.get("source_id"), "governed_authority_source_id_required")
        role = _required(item.get("binding_role"), "governed_authority_binding_role_required")
        permitted = {CESSATION_BINDING_ROLE} if cessation else CREATION_BINDING_ROLES
        if source_type not in SOURCE_TYPES:
            raise ValueError("governed_authority_source_type_invalid")
        if role not in permitted:
            raise ValueError("governed_authority_binding_role_invalid")
        if role == "authority_basis_source" and source_type == "accepted_pattern_observation":
            raise ValueError("governed_authority_observation_cannot_be_sole_basis")
        result.append({"source_type": source_type, "source_id": source_id, "binding_role": role, "source_version": item.get("source_version"), "source_timestamp": item.get("source_timestamp")})
    result.sort(key=lambda x: (x["source_type"], x["source_id"], x["binding_role"]))
    if len({(x["source_type"], x["source_id"], x["binding_role"]) for x in result}) != len(result):
        raise ValueError("governed_authority_duplicate_binding")
    required = CESSATION_BINDING_ROLE if cessation else "authority_basis_source"
    if not any(item["binding_role"] == required for item in result):
        raise ValueError(f"governed_authority_{required}_required")
    return result


def _validate_sources(conn: sqlite3.Connection, bindings: Any, *, document_root: Path | None = None, cessation: bool = False) -> list[dict[str, Any]]:
    result = []
    for item in _bindings(bindings, cessation=cessation):
        result.append(allegations._source_binding(conn, item, document_root=document_root))
    return result


def _key(prefix: str, payload: Mapping[str, Any]) -> str:
    return prefix + hashlib.sha256(_json(payload).encode()).hexdigest()


def _status(conn: sqlite3.Connection, object_type: str, object_id: int, base: str) -> str:
    if conn.execute("SELECT 1 FROM record_governed_decision_authority_supersessions WHERE object_type=? AND object_id=?", (object_type, object_id)).fetchone(): return "superseded"
    if conn.execute("SELECT 1 FROM record_governed_decision_authority_cessations WHERE object_type=? AND object_id=?", (object_type, object_id)).fetchone(): return "ceased"
    row = conn.execute("SELECT disposition FROM record_governed_decision_authority_reviews WHERE " + ("authority_id=? AND mandate_id IS NULL" if object_type == "authority" else "mandate_id=?" ) + " ORDER BY id DESC LIMIT 1", (object_id,)).fetchone()
    return str(row[0]) if row else base


def _json_row(row: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(row)
    for key in ("qualification_contract_json", "recorder_declaration_json", "appointment_declaration_json", "request_payload_json"):
        if key in result:
            result[key.removesuffix("_json")] = json.loads(result.pop(key))
    return result


def get_authority(conn: sqlite3.Connection, authority_id: int | str) -> dict[str, Any]:
    if not _table_exists(conn, "record_governed_decision_authorities"): raise ValueError("governed_authority_table_absent")
    row = conn.execute("SELECT * FROM record_governed_decision_authorities WHERE id=?", (int(authority_id),)).fetchone()
    if row is None: raise ValueError("governed_authority_not_found")
    result = _json_row(row); result["status"] = _status(conn, "authority", int(authority_id), result["status"])
    result["mandates"] = [get_mandate(conn, item[0]) for item in conn.execute("SELECT id FROM record_governed_decision_authority_mandates WHERE authority_id=? ORDER BY created_at,id", (int(authority_id),)).fetchall()]
    result["bindings"] = [dict(x) for x in conn.execute("SELECT * FROM record_governed_decision_authority_bindings WHERE object_type='authority' AND object_id=? ORDER BY id", (int(authority_id),)).fetchall()]
    result["reviews"] = [dict(x) for x in conn.execute("SELECT * FROM record_governed_decision_authority_reviews WHERE authority_id=? AND mandate_id IS NULL ORDER BY id", (int(authority_id),)).fetchall()]
    result["supersessions"] = [dict(x) for x in conn.execute("SELECT * FROM record_governed_decision_authority_supersessions WHERE object_type='authority' AND object_id=? ORDER BY id", (int(authority_id),)).fetchall()]
    result["cessations"] = [dict(x) for x in conn.execute("SELECT * FROM record_governed_decision_authority_cessations WHERE object_type='authority' AND object_id=? ORDER BY id", (int(authority_id),)).fetchall()]
    return result


def get_mandate(conn: sqlite3.Connection, mandate_id: int | str) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM record_governed_decision_authority_mandates WHERE id=?", (int(mandate_id),)).fetchone()
    if row is None: raise ValueError("governed_mandate_not_found")
    result = _json_row(row); result["status"] = _status(conn, "mandate", int(mandate_id), result["status"])
    result["bindings"] = [dict(x) for x in conn.execute("SELECT * FROM record_governed_decision_authority_bindings WHERE object_type='mandate' AND object_id=? ORDER BY id", (int(mandate_id),)).fetchall()]
    result["reviews"] = [dict(x) for x in conn.execute("SELECT * FROM record_governed_decision_authority_reviews WHERE mandate_id=? ORDER BY id", (int(mandate_id),)).fetchall()]
    result["supersessions"] = [dict(x) for x in conn.execute("SELECT * FROM record_governed_decision_authority_supersessions WHERE object_type='mandate' AND object_id=? ORDER BY id", (int(mandate_id),)).fetchall()]
    result["cessations"] = [dict(x) for x in conn.execute("SELECT * FROM record_governed_decision_authority_cessations WHERE object_type='mandate' AND object_id=? ORDER BY id", (int(mandate_id),)).fetchall()]
    return result


def list_authorities(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    if not _table_exists(conn, "record_governed_decision_authorities"): return []
    return [get_authority(conn, row[0]) for row in conn.execute("SELECT id FROM record_governed_decision_authorities ORDER BY created_at,id").fetchall()]


def read_authority_diagnostic(authority_id: int | str | None = None, *, db_path: str | Path) -> dict[str, Any]:
    path = Path(db_path)
    if not path.is_file(): return {"status": "database_unavailable", "authorities": []}
    try: conn = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True); conn.row_factory = sqlite3.Row
    except sqlite3.Error: return {"status": "database_unavailable", "authorities": []}
    try:
        if not _table_exists(conn, "record_governed_decision_authorities"): return {"status":"ok","authorities":[],"authority_table_present":False}
        if authority_id is None: return {"status":"ok","authorities":list_authorities(conn),"authority_table_present":True}
        try: return {"status":"ok","authorities":[get_authority(conn, authority_id)],"authority_table_present":True}
        except ValueError: return {"status":"authority_not_found","authorities":[],"authority_table_present":True}
    finally: conn.close()


def _common_authority_fields(*, holder_kind: str, holder_label: str, institution_context: str, office_role_capacity: str, named_holder: str | None, holder_effective_period: str | None, attribution_context: str, rationale: str, qualification: str, limitations: str, qualification_contract: Mapping[str, Any], recorder_declaration: Mapping[str, Any], actor: str, actor_role: str) -> tuple[str, str, str, str, str, str, str, dict[str, Any], dict[str, Any]]:
    kind = _required(holder_kind, "governed_authority_holder_kind_required").lower()
    if kind not in HOLDER_KINDS: raise ValueError("governed_authority_holder_kind_invalid")
    label = _required(holder_label, "governed_authority_holder_label_required")
    institution = _required(institution_context, "governed_authority_institution_context_required")
    capacity = _required(office_role_capacity, "governed_authority_office_role_capacity_required")
    if kind == "named_person" and not _required(capacity, "governed_authority_office_role_required"): raise ValueError("governed_authority_office_role_required")
    if kind == "named_person" and not _required(named_holder, "governed_authority_named_holder_required"): raise ValueError("governed_authority_named_holder_required")
    if kind != "named_person" and str(named_holder or "").strip(): raise ValueError("governed_authority_named_holder_inapplicable")
    return kind, label, institution, capacity, str(named_holder).strip() if named_holder else None, _required(attribution_context, "governed_authority_attribution_context_required"), _required(rationale, "governed_authority_rationale_required"), _qualification(qualification_contract, limitations), _declaration(recorder_declaration, "governed_authority_recorder_declaration_required", "authority_not_conferred")


def create_authority(conn: sqlite3.Connection, *, holder_kind: str, holder_label: str, institution_context: str, office_role_capacity: str, named_holder: str | None, holder_effective_period: str | None, attribution_context: str, rationale: str, qualification: str, limitations: str, qualification_contract: Mapping[str, Any], recorder_declaration: Mapping[str, Any], appointment_declaration: Mapping[str, Any] | None = None, bindings: list[Mapping[str, Any]], mandate: Mapping[str, Any], actor: str, actor_role: str, idempotency_key: str | None = None, mandate_idempotency_key: str | None = None, created_at: str | None = None, document_root: Path | None = None, _commit: bool = True) -> dict[str, Any]:
    fields = _common_authority_fields(holder_kind=holder_kind, holder_label=holder_label, institution_context=institution_context, office_role_capacity=office_role_capacity, named_holder=named_holder, holder_effective_period=holder_effective_period, attribution_context=attribution_context, rationale=rationale, qualification=qualification, limitations=limitations, qualification_contract=qualification_contract, recorder_declaration=recorder_declaration, actor=actor, actor_role=actor_role)
    normalized = _validate_sources(conn, bindings, document_root=document_root)
    if fields[0] == "named_person":
        if not any(x["binding_role"] == "appointment_source" for x in normalized): raise ValueError("governed_authority_appointment_source_required")
        appointment = _declaration(appointment_declaration, "governed_authority_appointment_declaration_required", "appointment_not_machine_verified")
    else:
        if appointment_declaration is not None: raise ValueError("governed_authority_appointment_declaration_inapplicable")
        appointment = {"human_recorded": False, "acknowledged": False, "boundary": "not_applicable"}
    mandate_payload = dict(mandate); mandate_payload.setdefault("recorder_declaration", recorder_declaration); mandate_payload.setdefault("qualification_contract", qualification_contract); mandate_payload.setdefault("bindings", bindings)
    payload = {"schema_version":SCHEMA_VERSION,"authoring_mode":AUTHORING_MODE,"holder_kind":fields[0],"holder_label":fields[1],"institution_context":fields[2],"office_role_capacity":fields[3],"named_holder":fields[4],"holder_effective_period":holder_effective_period,"attribution_context":fields[5],"rationale":fields[6],"qualification":_required(qualification,"governed_authority_qualification_required"),"limitations":_required(limitations,"governed_authority_limitations_required"),"qualification_contract":fields[7],"appointment_declaration":appointment,"bindings":normalized,"mandate":mandate_payload}
    key = str(idempotency_key or "").strip() or _key("stage66-authority:", payload); ensure_authority_tables(conn); payload_json = _json(payload)
    existing = conn.execute("SELECT * FROM record_governed_decision_authorities WHERE idempotency_key=?", (key,)).fetchone()
    if existing is not None:
        if str(existing["request_payload_json"]) != payload_json: raise ValueError("governed_authority_idempotency_conflict")
        return get_authority(conn, existing["id"])
    try:
        cur = conn.execute("INSERT INTO record_governed_decision_authorities (idempotency_key,schema_version,authoring_mode,holder_kind,holder_label,institution_context,office_role_capacity,named_holder,holder_effective_period,attribution_context,rationale,qualification,limitations,qualification_contract_json,recorder_declaration_json,appointment_declaration_json,status,created_by,created_by_role,created_at,request_payload_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (key,SCHEMA_VERSION,AUTHORING_MODE,*fields[:5],holder_effective_period,fields[5],fields[6],payload["qualification"],payload["limitations"],_json(fields[7]),_json(fields[8]),_json(appointment),"recorded",_required(actor,"governed_authority_recorder_required"),_required(actor_role,"governed_authority_recorder_role_required"),str(created_at or utc_now()),payload_json))
        authority_id = int(cur.lastrowid)
        conn.executemany("INSERT INTO record_governed_decision_authority_bindings (object_type,object_id,source_type,source_id,binding_role,source_version,source_timestamp) VALUES ('authority',?,?,?,?,?,?)", [(authority_id,x["source_type"],x["source_id"],x["binding_role"],x["source_version"],x["source_timestamp"]) for x in normalized])
        create_mandate(conn, authority_id=authority_id, **mandate_payload, actor=actor, actor_role=actor_role, idempotency_key=mandate_idempotency_key, document_root=document_root, _commit=False)
        if _commit: conn.commit()
    except Exception:
        conn.rollback(); raise
    return get_authority(conn, authority_id)


def create_mandate(conn: sqlite3.Connection, *, authority_id: int | str, mandate_basis_category: str, title_label: str, subject_matter_scope: str, procedural_scope: str, territorial_organisational_scope: str | None, affected_class: str | None, effective_from: str | None, effective_to: str | None, express_limitations: str, conditions_prerequisites: str, delegation_status: str | None = None, delegating_authority_id: int | None = None, delegating_mandate_id: int | None = None, delegation_source_declaration: Mapping[str, Any] | None = None, rationale: str, qualification: str, limitations: str, qualification_contract: Mapping[str, Any], recorder_declaration: Mapping[str, Any], bindings: list[Mapping[str, Any]], actor: str, actor_role: str, idempotency_key: str | None = None, created_at: str | None = None, document_root: Path | None = None, _commit: bool = True) -> dict[str, Any]:
    authority = get_authority(conn, authority_id)
    basis = _required(mandate_basis_category,"governed_mandate_basis_category_required").lower()
    if basis not in MANDATE_BASIS_CATEGORIES: raise ValueError("governed_mandate_basis_category_invalid")
    status = _required(delegation_status, "governed_delegation_status_required").lower()
    if status not in DELEGATION_STATUSES: raise ValueError("governed_delegation_status_invalid")
    if status != "delegated" and (delegating_authority_id is not None or delegating_mandate_id is not None or delegation_source_declaration is not None): raise ValueError("governed_delegation_fields_inapplicable")
    normalized = _validate_sources(conn, bindings, document_root=document_root)
    if status == "delegated":
        if delegating_authority_id is None or delegating_mandate_id is None: raise ValueError("governed_delegation_parent_required")
        if int(delegating_authority_id) == int(authority_id): raise ValueError("governed_delegation_self_reference")
        parent = get_mandate(conn, delegating_mandate_id)
        if int(parent["authority_id"]) != int(delegating_authority_id): raise ValueError("governed_delegation_parent_mismatch")
        if parent.get("delegation_status") == "delegated": raise ValueError("governed_delegation_cycle_rejected")
        if not any(x["binding_role"] == "delegation_source" for x in normalized): raise ValueError("governed_delegation_source_required")
        _declaration(delegation_source_declaration, "governed_delegation_declaration_required", "delegation_not_verified")
    else:
        delegating_authority_id = None; delegating_mandate_id = None
    payload = {"authority_id":int(authority_id),"mandate_basis_category":basis,"title_label":_required(title_label,"governed_mandate_title_required"),"subject_matter_scope":_required(subject_matter_scope,"governed_mandate_subject_scope_required"),"procedural_scope":_required(procedural_scope,"governed_mandate_procedural_scope_required"),"territorial_organisational_scope":territorial_organisational_scope,"affected_class":affected_class,"effective_from":effective_from,"effective_to":effective_to,"express_limitations":_required(express_limitations,"governed_mandate_limitations_required"),"conditions_prerequisites":_required(conditions_prerequisites,"governed_mandate_conditions_required"),"delegation_status":status,"delegating_authority_id":delegating_authority_id,"delegating_mandate_id":delegating_mandate_id,"rationale":_required(rationale,"governed_mandate_rationale_required"),"qualification":_required(qualification,"governed_mandate_qualification_required"),"limitations":_required(limitations,"governed_mandate_limitations_required"),"qualification_contract":_qualification(qualification_contract,limitations),"recorder_declaration":_declaration(recorder_declaration,"governed_mandate_recorder_declaration_required","authority_not_conferred"),"bindings":normalized}
    key = str(idempotency_key or "").strip() or _key("stage66-mandate:",payload); ensure_authority_tables(conn); payload_json = _json(payload)
    existing = conn.execute("SELECT * FROM record_governed_decision_authority_mandates WHERE idempotency_key=?",(key,)).fetchone()
    if existing is not None:
        if str(existing["request_payload_json"]) != payload_json: raise ValueError("governed_mandate_idempotency_conflict")
        return get_mandate(conn,existing["id"])
    try:
        cur = conn.execute("INSERT INTO record_governed_decision_authority_mandates (idempotency_key,authority_id,schema_version,mandate_basis_category,title_label,subject_matter_scope,procedural_scope,territorial_organisational_scope,affected_class,effective_from,effective_to,express_limitations,conditions_prerequisites,delegation_status,delegating_authority_id,delegating_mandate_id,rationale,qualification,limitations,qualification_contract_json,recorder_declaration_json,status,created_by,created_by_role,created_at,request_payload_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(key,int(authority_id),SCHEMA_VERSION,basis,payload["title_label"],payload["subject_matter_scope"],payload["procedural_scope"],territorial_organisational_scope,affected_class,effective_from,effective_to,payload["express_limitations"],payload["conditions_prerequisites"],status,delegating_authority_id,delegating_mandate_id,payload["rationale"],payload["qualification"],payload["limitations"],_json(payload["qualification_contract"]),_json(payload["recorder_declaration"]),"recorded",_required(actor,"governed_mandate_recorder_required"),_required(actor_role,"governed_mandate_recorder_role_required"),str(created_at or utc_now()),payload_json))
        mandate_id=int(cur.lastrowid)
        conn.executemany("INSERT INTO record_governed_decision_authority_bindings (object_type,object_id,source_type,source_id,binding_role,source_version,source_timestamp) VALUES ('mandate',?,?,?,?,?,?)",[(mandate_id,x["source_type"],x["source_id"],x["binding_role"],x["source_version"],x["source_timestamp"]) for x in normalized])
        if _commit: conn.commit()
    except Exception:
        conn.rollback(); raise
    return get_mandate(conn,mandate_id)


def review_authority(conn: sqlite3.Connection, *, authority_id: int | str, mandate_id: int | None, disposition: str, rationale: str, boundary_declaration: Mapping[str, Any], actor: str, actor_role: str, reviewed_at: str | None = None, idempotency_key: str | None = None, _commit: bool = True) -> dict[str, Any]:
    target = get_authority(conn, mandate_id or authority_id) if mandate_id is None else get_mandate(conn, mandate_id)
    if mandate_id is not None and int(target["authority_id"]) != int(authority_id): raise ValueError("governed_authority_review_target_mismatch")
    value=_required(disposition,"governed_authority_review_disposition_required").lower()
    if value not in REVIEW_DISPOSITIONS: raise ValueError("governed_authority_review_disposition_invalid")
    declaration=_declaration(boundary_declaration,"governed_authority_review_declaration_required","authority_not_validated")
    payload={"authority_id":int(authority_id),"mandate_id":int(mandate_id) if mandate_id else None,"disposition":value,"rationale":_required(rationale,"governed_authority_review_rationale_required"),"is_self_review":_required(actor,"governed_authority_reviewer_required")==str(target["created_by"]),"boundary_declaration":declaration}; key=str(idempotency_key or "").strip() or _key("stage66-review:",payload); ensure_authority_tables(conn); payload_json=_json(payload)
    existing=conn.execute("SELECT * FROM record_governed_decision_authority_reviews WHERE idempotency_key=?",(key,)).fetchone()
    if existing is not None:
        if str(existing["request_payload_json"])!=payload_json: raise ValueError("governed_authority_review_idempotency_conflict")
        return get_authority(conn,authority_id)
    try:
        conn.execute("INSERT INTO record_governed_decision_authority_reviews (authority_id,mandate_id,disposition,reviewed_by,reviewed_by_role,rationale,boundary_declaration_json,is_self_review,reviewed_at,idempotency_key,request_payload_json) VALUES (?,?,?,?,?,?,?,?,?,?,?)",(int(authority_id),int(mandate_id) if mandate_id else None,value,_required(actor,"governed_authority_reviewer_required"),_required(actor_role,"governed_authority_reviewer_role_required"),payload["rationale"],_json(declaration),int(payload["is_self_review"]),str(reviewed_at or utc_now()),key,payload_json))
        if _commit: conn.commit()
    except Exception: conn.rollback(); raise
    return get_authority(conn,authority_id)


def _terminal(conn: sqlite3.Connection, object_type: str, object_id: int) -> str | None:
    if conn.execute("SELECT 1 FROM record_governed_decision_authority_supersessions WHERE object_type=? AND object_id=?",(object_type,object_id)).fetchone(): return "superseded"
    if conn.execute("SELECT 1 FROM record_governed_decision_authority_cessations WHERE object_type=? AND object_id=?",(object_type,object_id)).fetchone(): return "ceased"
    return None


def supersede_authority_record(conn: sqlite3.Connection, *, object_type: str, object_id: int | str, replacement_id: int | str, rationale: str, actor: str, actor_role: str, occurred_at: str | None = None, idempotency_key: str | None = None, _commit: bool = True) -> dict[str, Any]:
    if object_type not in {"authority","mandate"}: raise ValueError("governed_authority_object_type_invalid")
    original=get_authority(conn,object_id) if object_type=="authority" else get_mandate(conn,object_id); replacement=get_authority(conn,replacement_id) if object_type=="authority" else get_mandate(conn,replacement_id)
    if int(object_id)==int(replacement_id): raise ValueError("governed_authority_supersession_self_reference")
    if object_type=="mandate" and int(original["authority_id"]) != int(replacement["authority_id"]): raise ValueError("governed_mandate_supersession_authority_mismatch")
    seen = {int(object_id)}; cursor = int(replacement_id)
    while True:
        if cursor in seen: raise ValueError("governed_authority_supersession_cycle_rejected")
        seen.add(cursor)
        row = conn.execute("SELECT replacement_id FROM record_governed_decision_authority_supersessions WHERE object_type=? AND object_id=?", (object_type, cursor)).fetchone()
        if row is None: break
        cursor = int(row[0])
    payload={"object_type":object_type,"object_id":int(object_id),"replacement_id":int(replacement_id),"rationale":_required(rationale,"governed_authority_supersession_rationale_required")}; key=str(idempotency_key or "").strip() or _key("stage66-supersession:",payload); ensure_authority_tables(conn); payload_json=_json(payload); existing=conn.execute("SELECT * FROM record_governed_decision_authority_supersessions WHERE idempotency_key=?",(key,)).fetchone()
    if existing is not None:
        if str(existing["request_payload_json"])!=payload_json: raise ValueError("governed_authority_supersession_idempotency_conflict")
        return get_authority(conn,object_id) if object_type=="authority" else get_mandate(conn,object_id)
    if _terminal(conn,object_type,int(object_id)): raise ValueError("governed_authority_supersession_terminal")
    try:
        conn.execute("INSERT INTO record_governed_decision_authority_supersessions (object_type,object_id,replacement_id,rationale,actor,actor_role,occurred_at,idempotency_key,request_payload_json) VALUES (?,?,?,?,?,?,?,?,?)",(object_type,int(object_id),int(replacement_id),payload["rationale"],_required(actor,"governed_authority_actor_required"),_required(actor_role,"governed_authority_actor_role_required"),str(occurred_at or utc_now()),key,payload_json))
        if _commit: conn.commit()
    except Exception: conn.rollback(); raise
    return get_authority(conn,object_id) if object_type=="authority" else get_mandate(conn,object_id)


def cease_authority_record(conn: sqlite3.Connection, *, object_type: str, object_id: int | str, cessation_type: str, cessation_date_or_period: str, rationale: str, cessation_bindings: list[Mapping[str, Any]], actor: str, actor_role: str, occurred_at: str | None = None, idempotency_key: str | None = None, document_root: Path | None = None, _commit: bool = True) -> dict[str, Any]:
    target=get_authority(conn,object_id) if object_type=="authority" else get_mandate(conn,object_id)
    if object_type not in {"authority","mandate"}: raise ValueError("governed_authority_object_type_invalid")
    if cessation_type not in CESSATION_TYPES: raise ValueError("governed_authority_cessation_type_invalid")
    normalized=_validate_sources(conn,cessation_bindings,document_root=document_root,cessation=True)
    payload={"object_type":object_type,"object_id":int(object_id),"cessation_type":cessation_type,"cessation_date_or_period":_required(cessation_date_or_period,"governed_authority_cessation_date_required"),"rationale":_required(rationale,"governed_authority_cessation_rationale_required"),"bindings":normalized}; key=str(idempotency_key or "").strip() or _key("stage66-cessation:",payload); ensure_authority_tables(conn); payload_json=_json(payload); existing=conn.execute("SELECT * FROM record_governed_decision_authority_cessations WHERE idempotency_key=?",(key,)).fetchone()
    if existing is not None:
        if str(existing["request_payload_json"])!=payload_json: raise ValueError("governed_authority_cessation_idempotency_conflict")
        return get_authority(conn,object_id) if object_type=="authority" else get_mandate(conn,object_id)
    if _terminal(conn,object_type,int(object_id)): raise ValueError("governed_authority_cessation_terminal")
    try:
        conn.execute("INSERT INTO record_governed_decision_authority_cessations (object_type,object_id,cessation_type,cessation_date_or_period,rationale,actor,actor_role,occurred_at,idempotency_key,request_payload_json) VALUES (?,?,?,?,?,?,?,?,?,?)",(object_type,int(object_id),cessation_type,payload["cessation_date_or_period"],payload["rationale"],_required(actor,"governed_authority_actor_required"),_required(actor_role,"governed_authority_actor_role_required"),str(occurred_at or utc_now()),key,payload_json))
        conn.executemany("INSERT INTO record_governed_decision_authority_bindings (object_type,object_id,source_type,source_id,binding_role,source_version,source_timestamp) VALUES (?,?,?,?,?,?,?)",[(object_type,int(object_id),x["source_type"],x["source_id"],x["binding_role"],x["source_version"],x["source_timestamp"]) for x in normalized])
        if _commit: conn.commit()
    except Exception: conn.rollback(); raise
    return get_authority(conn,object_id) if object_type=="authority" else get_mandate(conn,object_id)
