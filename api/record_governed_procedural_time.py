"""Stage 71 source-bound procedural notices, deadlines and time events.

This module records procedural time as represented or deterministically
calculated from explicit inputs.  It never infers receipt, lateness, waiver,
admissibility, default or legal effect.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from api import record_governed_inferences as inferences

SCHEMA_VERSION_NOTICE = "stage71.human_governed_procedural_notice.v1"
SCHEMA_VERSION_DEADLINE = "stage71.human_governed_procedural_deadline.v1"
SCHEMA_VERSION_CALCULATION = "stage71.deterministic_deadline_calculation.v1"
HUMAN_RECORDED = "human_recorded"
DETERMINISTICALLY_CALCULATED = "deterministically_calculated"

NOTICE_CATEGORIES = {"notice_issued", "notice_dispatched", "notice_made_available", "notice_received_as_evidenced", "receipt_disputed", "notice_adequacy_disputed"}
DEADLINE_CATEGORIES = {"response_deadline", "appeal_deadline", "review_application_deadline", "submission_deadline", "compliance_deadline", "procedural_hearing_deadline", "other_stated_procedural_deadline"}
DATE_PRECISIONS = {"date", "month", "period", "timestamp"}
EVENT_CATEGORIES = {"extension_requested", "extension_granted", "extension_refused_as_represented", "deadline_corrected", "deadline_disputed", "trigger_disputed", "receipt_disputed", "calculation_recorded", "calculated_expiry_recorded", "late_filing_alleged", "formal_late_filing_determination_linked"}
CALCULATION_MODES = {"explicit_deadline_comparison", "calendar_days_after_explicit_trigger"}
SOURCE_TYPES = {"published_document", "canonical_record", "record_document_association", "accepted_pattern_observation"}
NOTICE_BINDING_ROLES = {"notice_source", "dispatch_source", "receipt_source", "deadline_source", "trigger_source", "extension_request_source", "extension_grant_source", "dispute_source", "calculation_basis_source", "determination_source", "contextual_source", "contrary_source"}
OBJECT_ROLES = {"notice_concerns", "deadline_applies_to", "deadline_triggered_by", "extension_relates_to", "dispute_concerns", "calculation_concerns", "determination_addresses"}
OBJECT_TABLES = {"governed_allegation": ("record_governed_allegations", "id"), "governed_response": ("record_governed_responses", "id"), "governed_determination": ("record_governed_determinations", "id"), "governed_challenge": ("record_governed_challenges", "id"), "governed_remedy": ("record_governed_remedies", "id"), "governed_implementation_event": ("record_governed_implementation_events", "id"), "canonical_record": ("records", "reference")}
REVIEW_DISPOSITIONS = {"accepted_as_source_bound_procedural_record", "requires_procedural_correction", "not_accepted_as_procedural_record"}
STATUSES = {"recorded", "accepted_procedural_record", "procedural_correction_required", "not_accepted_as_procedural_record", "superseded"}
RESULT_CATEGORIES = {"deadline_not_reached_as_calculated", "deadline_reached_as_calculated", "deadline_passed_as_calculated", "calculation_not_supported"}

NOTICE_BOUNDARY = "This record preserves a notice event as represented in an identified governed source. Recording issuance, dispatch, availability or evidenced receipt does not establish valid service, actual knowledge, adequacy of notice, waiver, participation, jurisdiction or legal effect."
DEADLINE_BOUNDARY = "This record preserves a procedural deadline as stated or deterministically calculated from explicit governed inputs. Its recording does not establish validity, applicability, expiry as a legal conclusion, lateness, default, inadmissibility, waiver, abandonment, breach or legal effect."
CALCULATION_BOUNDARY = "This calculation applies the recorded calculation mode to explicit persisted inputs as of the recorded calculation instant. It is a reproducible date calculation only. It is not a determination that any act was late, invalid, inadmissible, waived, abandoned or legally ineffective."
FORMAL_LINK_BOUNDARY = "This record links an existing governed determination that addresses a procedural-time question. The CDE does not make, validate or calculate the legal effect of that determination."
LIMITATIONS_BOUNDARY = "Additional notices or extensions may exist; receipt may remain disputed; calculation inputs may be incomplete or contested; legal rules may differ from the represented calculation; later determinations may coexist; and absence from the governed record proves none of those events absent."
DECLARATIONS = {
    "notice_received_as_evidenced": "I confirm that the selected governed source expressly represents receipt by the identified recipient. Receipt is not inferred from issue, dispatch, availability, silence or later participation.",
    "extension_granted": "I confirm that the selected source represents an extension granted by the identified person, institution or authority. A request for extension is not being recorded as a grant.",
    "calculated_expiry_recorded": "I confirm that this is a deterministic calculation from the displayed persisted inputs and calculation instant. It is not a legal determination of lateness, default or inadmissibility.",
    "late_filing_alleged": "I confirm that this event links an existing governed allegation of late filing. Recording the allegation does not establish that the filing was late.",
    "formal_late_filing_determination_linked": "I confirm that this event links an existing governed determination expressly addressing the procedural-time question. The CDE is not making or validating that determination.",
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


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None


def ensure_procedural_time_tables(conn: sqlite3.Connection) -> None:
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS record_governed_procedural_notices (
      id INTEGER PRIMARY KEY AUTOINCREMENT, idempotency_key TEXT NOT NULL UNIQUE,
      schema_version TEXT NOT NULL, authoring_mode TEXT NOT NULL, notice_category TEXT NOT NULL,
      title_label TEXT NOT NULL, notice_description TEXT NOT NULL, issuing_label TEXT NOT NULL,
      issuing_capacity TEXT NOT NULL, intended_recipient TEXT NOT NULL, issue_date_or_period TEXT,
      dispatch_method TEXT, procedural_subject TEXT NOT NULL, rationale TEXT NOT NULL,
      qualification TEXT NOT NULL, limitations TEXT NOT NULL, qualification_contract_json TEXT NOT NULL,
      declaration_json TEXT NOT NULL, created_by TEXT NOT NULL, created_by_role TEXT NOT NULL,
      created_at TEXT NOT NULL, status TEXT NOT NULL, request_payload_json TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS record_governed_procedural_deadlines (
      id INTEGER PRIMARY KEY AUTOINCREMENT, idempotency_key TEXT NOT NULL UNIQUE,
      schema_version TEXT NOT NULL, authoring_mode TEXT NOT NULL, deadline_category TEXT NOT NULL,
      title_label TEXT NOT NULL, procedural_subject TEXT NOT NULL, trigger_event TEXT NOT NULL,
      trigger_date_or_period TEXT, deadline_date_or_period TEXT, date_precision TEXT NOT NULL,
      time_precision TEXT, time_zone TEXT, calculation_rule TEXT, counting_convention TEXT,
      inclusivity TEXT, conditions TEXT, affected_participant TEXT, rationale TEXT NOT NULL,
      qualification TEXT NOT NULL, limitations TEXT NOT NULL, qualification_contract_json TEXT NOT NULL,
      declaration_json TEXT NOT NULL, created_by TEXT NOT NULL, created_by_role TEXT NOT NULL,
      created_at TEXT NOT NULL, status TEXT NOT NULL, request_payload_json TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS record_governed_procedural_time_bindings (
      id INTEGER PRIMARY KEY AUTOINCREMENT, record_kind TEXT NOT NULL, record_id INTEGER NOT NULL,
      source_type TEXT NOT NULL, source_id TEXT NOT NULL, binding_role TEXT NOT NULL,
      source_version TEXT, source_timestamp TEXT,
      UNIQUE(record_kind, record_id, source_type, source_id, binding_role)
    );
    CREATE TABLE IF NOT EXISTS record_governed_procedural_time_object_links (
      id INTEGER PRIMARY KEY AUTOINCREMENT, record_kind TEXT NOT NULL, record_id INTEGER NOT NULL,
      object_type TEXT NOT NULL, object_id TEXT NOT NULL, relationship_role TEXT NOT NULL,
      UNIQUE(record_kind, record_id, object_type, object_id, relationship_role)
    );
    CREATE TABLE IF NOT EXISTS record_governed_procedural_time_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT, idempotency_key TEXT NOT NULL UNIQUE,
      parent_kind TEXT NOT NULL, parent_id INTEGER NOT NULL, event_category TEXT NOT NULL,
      actor_label TEXT NOT NULL, actor_capacity TEXT NOT NULL, represented_date_or_period TEXT,
      represented_value TEXT, rationale TEXT NOT NULL, qualification TEXT NOT NULL,
      limitations TEXT NOT NULL, declaration_json TEXT NOT NULL, created_by TEXT NOT NULL,
      created_by_role TEXT NOT NULL, created_at TEXT NOT NULL, status TEXT NOT NULL,
      request_payload_json TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS record_governed_deadline_calculations (
      id INTEGER PRIMARY KEY AUTOINCREMENT, idempotency_key TEXT NOT NULL UNIQUE,
      deadline_id INTEGER NOT NULL, calculation_mode TEXT NOT NULL, trigger_input TEXT NOT NULL,
      interval_days INTEGER, inclusivity TEXT NOT NULL, calculated_deadline TEXT NOT NULL,
      calculated_as_of TEXT NOT NULL, time_zone TEXT NOT NULL, normalized_inputs_json TEXT NOT NULL,
      calculation_trace TEXT NOT NULL, result_category TEXT NOT NULL, algorithm_version TEXT NOT NULL,
      requested_by TEXT NOT NULL, calculated_at TEXT NOT NULL, request_payload_json TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS record_governed_procedural_time_reviews (
      id INTEGER PRIMARY KEY AUTOINCREMENT, target_kind TEXT NOT NULL, target_id INTEGER NOT NULL,
      disposition TEXT NOT NULL, reviewer TEXT NOT NULL, reviewer_role TEXT NOT NULL,
      rationale TEXT NOT NULL, boundary_declaration_json TEXT NOT NULL, is_self_review INTEGER NOT NULL,
      reviewed_at TEXT NOT NULL, idempotency_key TEXT NOT NULL UNIQUE, request_payload_json TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS record_governed_procedural_time_supersessions (
      id INTEGER PRIMARY KEY AUTOINCREMENT, target_kind TEXT NOT NULL, target_id INTEGER NOT NULL,
      replacement_kind TEXT NOT NULL, replacement_id INTEGER NOT NULL, rationale TEXT NOT NULL,
      actor TEXT NOT NULL, actor_role TEXT NOT NULL, occurred_at TEXT NOT NULL,
      idempotency_key TEXT NOT NULL UNIQUE, request_payload_json TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_stage71_notice_status ON record_governed_procedural_notices(status, created_at);
    CREATE INDEX IF NOT EXISTS idx_stage71_deadline_status ON record_governed_procedural_deadlines(status, created_at);
    """)


def _key(prefix: str, payload: Mapping[str, Any]) -> str:
    return prefix + hashlib.sha256(_json(payload).encode()).hexdigest()


def _iso(value: Any, error: str, *, allow_period: bool = True) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    try:
        if len(text) == 10:
            date.fromisoformat(text)
        else:
            datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        if allow_period and "/" in text:
            parts = [x.strip() for x in text.split("/", 1)]
            if len(parts) == 2:
                _iso(parts[0], error, allow_period=False); _iso(parts[1], error, allow_period=False)
            else:
                raise ValueError(error)
        else:
            raise ValueError(error)
    return text


def _declaration(value: Any, category: str, required: bool) -> dict[str, Any]:
    if not required:
        if value not in (None, {}, {"acknowledged": False}):
            raise ValueError("governed_procedural_time_declaration_inapplicable")
        return {"acknowledged": False, "category": None, "boundary": "not_applicable"}
    if value is None:
        raise ValueError("governed_procedural_time_declaration_required")
    if not isinstance(value, Mapping) or set(value) - {"acknowledged", "category"}:
        raise ValueError("governed_procedural_time_declaration_malformed")
    if value.get("acknowledged") not in (True, "1"):
        raise ValueError("governed_procedural_time_declaration_required")
    if value.get("category") not in (None, category):
        raise ValueError("governed_procedural_time_declaration_category_mismatch")
    return {"acknowledged": True, "category": category, "boundary": DECLARATIONS[category]}


def _contract(value: Any, kind: str, limitations: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) - {"epistemic_label", "source_bound", "not_legal_effect", "limitations"}:
        raise ValueError("governed_procedural_time_qualification_contract_required")
    expected = {"epistemic_label": kind, "source_bound": True, "not_legal_effect": True}
    if any(value.get(key) != expected_value for key, expected_value in expected.items()):
        raise ValueError("governed_procedural_time_qualification_contract_incomplete")
    return {**expected, "limitations": _required(limitations, "governed_procedural_time_limitations_required")}


def _canonical_bindings(bindings: Any, primary: str, *, allowed: set[str] = NOTICE_BINDING_ROLES) -> list[dict[str, Any]]:
    if not isinstance(bindings, (list, tuple)) or not bindings:
        raise ValueError("governed_procedural_time_binding_required")
    result = []
    for item in bindings:
        if not isinstance(item, Mapping) or set(item) - {"source_type", "source_id", "binding_role", "source_version", "source_timestamp"}:
            raise ValueError("governed_procedural_time_binding_invalid")
        source_type = _required(item.get("source_type"), "governed_procedural_time_source_type_required")
        source_id = _required(item.get("source_id"), "governed_procedural_time_source_id_required")
        role = _required(item.get("binding_role"), "governed_procedural_time_binding_role_required")
        if source_type not in SOURCE_TYPES or role not in allowed:
            raise ValueError("governed_procedural_time_binding_invalid")
        result.append({"source_type": source_type, "source_id": source_id, "binding_role": role, "source_version": item.get("source_version"), "source_timestamp": item.get("source_timestamp")})
    result.sort(key=lambda x: (x["source_type"], x["source_id"], x["binding_role"]))
    if len({(x["source_type"], x["source_id"], x["binding_role"]) for x in result}) != len(result):
        raise ValueError("governed_procedural_time_duplicate_binding")
    if not any(x["binding_role"] == primary for x in result):
        raise ValueError("governed_procedural_time_primary_source_required")
    return result


def _validate_bindings(conn: sqlite3.Connection, bindings: Any, primary: str, document_root: Path | None) -> list[dict[str, Any]]:
    normalized = _canonical_bindings(bindings, primary)
    return [inferences._source_binding(conn, item, document_root=document_root) for item in normalized]


def _objects(conn: sqlite3.Connection, links: Any, required_role: str) -> list[dict[str, Any]]:
    if not isinstance(links, (list, tuple)) or not links:
        raise ValueError("governed_procedural_time_subject_required")
    result = []
    for item in links:
        if not isinstance(item, Mapping) or set(item) - {"object_type", "object_id", "relationship_role"}:
            raise ValueError("governed_procedural_time_object_link_invalid")
        kind = _required(item.get("object_type"), "governed_procedural_time_object_type_required")
        object_id = _required(item.get("object_id"), "governed_procedural_time_object_id_required")
        role = _required(item.get("relationship_role"), "governed_procedural_time_object_role_required")
        if kind not in OBJECT_TABLES or role not in OBJECT_ROLES:
            raise ValueError("governed_procedural_time_object_link_invalid")
        table, column = OBJECT_TABLES[kind]
        if not _table_exists(conn, table):
            raise ValueError("governed_procedural_time_object_not_found")
        row = conn.execute(f"SELECT * FROM {table} WHERE {column}=?", (int(object_id) if column == "id" else object_id,)).fetchone()
        if row is None:
            raise ValueError("governed_procedural_time_object_not_found")
        status = str(dict(row).get("status", "recorded"))
        if kind == "governed_allegation" and status not in {"recorded", "accepted_as_attributed_allegation"}:
            raise ValueError("governed_procedural_time_allegation_not_eligible")
        if kind == "governed_determination" and status != "accepted_as_attributed_determination_record":
            raise ValueError("governed_procedural_time_determination_not_eligible")
        result.append({"object_type": kind, "object_id": object_id, "relationship_role": role})
    result.sort(key=lambda x: (x["object_type"], x["object_id"], x["relationship_role"]))
    if not any(x["relationship_role"] == required_role for x in result):
        raise ValueError("governed_procedural_time_subject_required")
    if len({(x["object_type"], x["object_id"], x["relationship_role"]) for x in result}) != len(result):
        raise ValueError("governed_procedural_time_duplicate_object_link")
    return result


def _status(conn: sqlite3.Connection, kind: str, ident: int, base: str) -> str:
    if conn.execute("SELECT 1 FROM record_governed_procedural_time_supersessions WHERE target_kind=? AND target_id=?", (kind, ident)).fetchone():
        return "superseded"
    row = conn.execute("SELECT disposition FROM record_governed_procedural_time_reviews WHERE target_kind=? AND target_id=? ORDER BY id DESC LIMIT 1", (kind, ident)).fetchone()
    if row:
        return {"requires_procedural_correction": "procedural_correction_required", "accepted_as_source_bound_procedural_record": "accepted_procedural_record"}.get(row[0], row[0])
    return base


def _record(conn: sqlite3.Connection, kind: str, ident: int) -> dict[str, Any]:
    table = "record_governed_procedural_notices" if kind == "notice" else "record_governed_procedural_deadlines"
    row = conn.execute(f"SELECT * FROM {table} WHERE id=?", (ident,)).fetchone()
    if row is None:
        raise ValueError("governed_procedural_time_record_not_found")
    result = dict(row)
    for field in ("qualification_contract_json", "declaration_json", "request_payload_json"):
        if field in result:
            result[field.removesuffix("_json")] = json.loads(result.pop(field))
    result["status"] = _status(conn, kind, ident, result["status"])
    result["record_kind"] = kind
    result["bindings"] = [dict(x) for x in conn.execute("SELECT * FROM record_governed_procedural_time_bindings WHERE record_kind=? AND record_id=? ORDER BY id", (kind, ident)).fetchall()]
    result["subject_links"] = [dict(x) for x in conn.execute("SELECT * FROM record_governed_procedural_time_object_links WHERE record_kind=? AND record_id=? ORDER BY id", (kind, ident)).fetchall()]
    result["events"] = [dict(x) for x in conn.execute("SELECT * FROM record_governed_procedural_time_events WHERE parent_kind=? AND parent_id=? ORDER BY id", (kind, ident)).fetchall()]
    result["calculations"] = [dict(x) for x in conn.execute("SELECT * FROM record_governed_deadline_calculations WHERE deadline_id=? ORDER BY id", (ident,)).fetchall()] if kind == "deadline" else []
    result["reviews"] = [dict(x) for x in conn.execute("SELECT * FROM record_governed_procedural_time_reviews WHERE target_kind=? AND target_id=? ORDER BY id", (kind, ident)).fetchall()]
    result["supersessions"] = [dict(x) for x in conn.execute("SELECT * FROM record_governed_procedural_time_supersessions WHERE target_kind=? AND target_id=? ORDER BY id", (kind, ident)).fetchall()]
    return result


def get_notice(conn: sqlite3.Connection, notice_id: int | str) -> dict[str, Any]:
    if not _table_exists(conn, "record_governed_procedural_notices"):
        raise ValueError("governed_procedural_notice_table_absent")
    return _record(conn, "notice", int(notice_id))


def get_deadline(conn: sqlite3.Connection, deadline_id: int | str) -> dict[str, Any]:
    if not _table_exists(conn, "record_governed_procedural_deadlines"):
        raise ValueError("governed_procedural_deadline_table_absent")
    return _record(conn, "deadline", int(deadline_id))


def list_procedural_time_records(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    result = []
    if _table_exists(conn, "record_governed_procedural_notices"):
        result += [get_notice(conn, row[0]) for row in conn.execute("SELECT id FROM record_governed_procedural_notices ORDER BY created_at,id")]
    if _table_exists(conn, "record_governed_procedural_deadlines"):
        result += [get_deadline(conn, row[0]) for row in conn.execute("SELECT id FROM record_governed_procedural_deadlines ORDER BY created_at,id")]
    return result


def read_procedural_time_diagnostic(*, db_path: str | Path, record_kind: str | None = None, record_id: int | None = None) -> dict[str, Any]:
    path = Path(db_path)
    if not path.is_file():
        return {"status": "database_unavailable", "records": []}
    conn = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True); conn.row_factory = sqlite3.Row
    try:
        if record_kind and record_id:
            try: records = [_record(conn, record_kind, int(record_id))]
            except ValueError: records = []
        else: records = list_procedural_time_records(conn)
        return {"status": "ok", "records": records, "notice_table_present": _table_exists(conn, "record_governed_procedural_notices"), "deadline_table_present": _table_exists(conn, "record_governed_procedural_deadlines")}
    finally: conn.close()


def _create(conn: sqlite3.Connection, *, kind: str, values: Mapping[str, Any], bindings: Any, subject_links: Any, actor: str, actor_role: str, idempotency_key: str | None, created_at: str | None, document_root: Path | None) -> dict[str, Any]:
    category = _required(values.get("category"), "governed_procedural_time_category_required").lower()
    allowed = NOTICE_CATEGORIES if kind == "notice" else DEADLINE_CATEGORIES
    if category not in allowed: raise ValueError("governed_procedural_time_category_invalid")
    declaration = _declaration(values.get("declaration"), category, category == "notice_received_as_evidenced") if kind == "notice" else {"acknowledged": False, "category": None, "boundary": "not_applicable"}
    date_value = _iso(values.get("date_or_period"), "governed_procedural_time_date_invalid")
    if kind == "notice" and category == "notice_received_as_evidenced":
        if not str(values.get("recipient") or "").strip(): raise ValueError("governed_procedural_time_recipient_required")
        if not date_value: raise ValueError("governed_procedural_time_receipt_date_required")
    if kind == "deadline" and values.get("date_precision") not in DATE_PRECISIONS:
        raise ValueError("governed_procedural_time_date_precision_invalid")
    primary = "receipt_source" if category == "notice_received_as_evidenced" else "notice_source" if kind == "notice" else "deadline_source"
    normalized = _validate_bindings(conn, bindings, primary, document_root)
    links = _objects(conn, subject_links, "notice_concerns" if kind == "notice" else "deadline_applies_to")
    payload = dict(values); payload.update({"kind": kind, "category": category, "date_or_period": date_value, "bindings": normalized, "subject_links": links, "actor": actor, "actor_role": actor_role})
    key = str(idempotency_key or "").strip() or _key("stage71-" + kind + ":", payload)
    ensure_procedural_time_tables(conn)
    table = "record_governed_procedural_notices" if kind == "notice" else "record_governed_procedural_deadlines"
    existing = conn.execute(f"SELECT * FROM {table} WHERE idempotency_key=?", (key,)).fetchone()
    payload_json = _json(payload)
    if existing:
        if existing["request_payload_json"] != payload_json: raise ValueError("governed_procedural_time_idempotency_conflict")
        return _record(conn, kind, existing["id"])
    try:
        if kind == "notice":
            cur = conn.execute("INSERT INTO record_governed_procedural_notices (idempotency_key,schema_version,authoring_mode,notice_category,title_label,notice_description,issuing_label,issuing_capacity,intended_recipient,issue_date_or_period,dispatch_method,procedural_subject,rationale,qualification,limitations,qualification_contract_json,declaration_json,created_by,created_by_role,created_at,status,request_payload_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (key, SCHEMA_VERSION_NOTICE, HUMAN_RECORDED, category, _required(values.get("title_label"), "governed_procedural_time_title_required"), _required(values.get("description"), "governed_procedural_time_description_required"), _required(values.get("issuing_label"), "governed_procedural_time_issuer_required"), _required(values.get("issuing_capacity"), "governed_procedural_time_capacity_required"), _required(values.get("recipient"), "governed_procedural_time_recipient_required"), date_value, values.get("dispatch_method"), _required(values.get("procedural_subject"), "governed_procedural_time_subject_label_required"), _required(values.get("rationale"), "governed_procedural_time_rationale_required"), _required(values.get("qualification"), "governed_procedural_time_qualification_required"), _required(values.get("limitations"), "governed_procedural_time_limitations_required"), _json(values["qualification_contract"]), _json(declaration), _required(actor, "governed_procedural_time_recorder_required"), _required(actor_role, "governed_procedural_time_recorder_role_required"), str(created_at or utc_now()), "recorded", payload_json))
        else:
            cur = conn.execute("INSERT INTO record_governed_procedural_deadlines (idempotency_key,schema_version,authoring_mode,deadline_category,title_label,procedural_subject,trigger_event,trigger_date_or_period,deadline_date_or_period,date_precision,time_precision,time_zone,calculation_rule,counting_convention,inclusivity,conditions,affected_participant,rationale,qualification,limitations,qualification_contract_json,declaration_json,created_by,created_by_role,created_at,status,request_payload_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (key, SCHEMA_VERSION_DEADLINE, HUMAN_RECORDED, category, _required(values.get("title_label"), "governed_procedural_time_title_required"), _required(values.get("procedural_subject"), "governed_procedural_time_subject_label_required"), _required(values.get("trigger_event"), "governed_procedural_time_trigger_required"), _iso(values.get("trigger_date_or_period"), "governed_procedural_time_trigger_date_invalid"), date_value, _required(values.get("date_precision"), "governed_procedural_time_date_precision_required"), values.get("time_precision"), values.get("time_zone"), values.get("calculation_rule"), values.get("counting_convention"), values.get("inclusivity"), values.get("conditions"), values.get("affected_participant"), _required(values.get("rationale"), "governed_procedural_time_rationale_required"), _required(values.get("qualification"), "governed_procedural_time_qualification_required"), _required(values.get("limitations"), "governed_procedural_time_limitations_required"), _json(values["qualification_contract"]), _json(declaration), _required(actor, "governed_procedural_time_recorder_required"), _required(actor_role, "governed_procedural_time_recorder_role_required"), str(created_at or utc_now()), "recorded", payload_json))
        ident = int(cur.lastrowid)
        conn.executemany("INSERT INTO record_governed_procedural_time_bindings (record_kind,record_id,source_type,source_id,binding_role,source_version,source_timestamp) VALUES (?,?,?,?,?,?,?)", [(kind, ident, x["source_type"], x["source_id"], x["binding_role"], x.get("source_version"), x.get("source_timestamp")) for x in normalized])
        conn.executemany("INSERT INTO record_governed_procedural_time_object_links (record_kind,record_id,object_type,object_id,relationship_role) VALUES (?,?,?,?,?)", [(kind, ident, x["object_type"], x["object_id"], x["relationship_role"]) for x in links])
        conn.commit()
    except Exception:
        conn.rollback(); raise
    return _record(conn, kind, ident)


def create_notice(conn: sqlite3.Connection, *, notice_category: str, title_label: str, notice_description: str, issuing_label: str, issuing_capacity: str, intended_recipient: str, issue_date_or_period: str | None, dispatch_method: str | None, procedural_subject: str, rationale: str, qualification: str = NOTICE_BOUNDARY, limitations: str = LIMITATIONS_BOUNDARY, qualification_contract: Mapping[str, Any], declaration: Mapping[str, Any] | None, bindings: Any, subject_links: Any, actor: str, actor_role: str, idempotency_key: str | None = None, created_at: str | None = None, document_root: Path | None = None) -> dict[str, Any]:
    return _create(conn, kind="notice", values={"category": notice_category, "title_label": title_label, "description": notice_description, "issuing_label": issuing_label, "issuing_capacity": issuing_capacity, "recipient": intended_recipient, "date_or_period": issue_date_or_period, "dispatch_method": dispatch_method, "procedural_subject": procedural_subject, "rationale": rationale, "qualification": qualification, "limitations": limitations, "qualification_contract": _contract(qualification_contract, "notice", limitations), "declaration": declaration}, bindings=bindings, subject_links=subject_links, actor=actor, actor_role=actor_role, idempotency_key=idempotency_key, created_at=created_at, document_root=document_root)


def create_deadline(conn: sqlite3.Connection, *, deadline_category: str, title_label: str, procedural_subject: str, trigger_event: str, trigger_date_or_period: str | None, deadline_date_or_period: str | None, date_precision: str, time_precision: str | None, time_zone: str | None, calculation_rule: str | None, counting_convention: str | None, inclusivity: str | None, conditions: str | None, affected_participant: str | None, rationale: str, qualification: str = DEADLINE_BOUNDARY, limitations: str = LIMITATIONS_BOUNDARY, qualification_contract: Mapping[str, Any], bindings: Any, subject_links: Any, actor: str, actor_role: str, idempotency_key: str | None = None, created_at: str | None = None, document_root: Path | None = None) -> dict[str, Any]:
    return _create(conn, kind="deadline", values={"category": deadline_category, "title_label": title_label, "procedural_subject": procedural_subject, "trigger_event": trigger_event, "trigger_date_or_period": trigger_date_or_period, "date_or_period": deadline_date_or_period, "date_precision": date_precision, "time_precision": time_precision, "time_zone": time_zone, "calculation_rule": calculation_rule, "counting_convention": counting_convention, "inclusivity": inclusivity, "conditions": conditions, "affected_participant": affected_participant, "rationale": rationale, "qualification": qualification, "limitations": limitations, "qualification_contract": _contract(qualification_contract, "deadline", limitations), "declaration": None}, bindings=bindings, subject_links=subject_links, actor=actor, actor_role=actor_role, idempotency_key=idempotency_key, created_at=created_at, document_root=document_root)


def record_event(conn: sqlite3.Connection, *, parent_kind: str, parent_id: int, event_category: str, actor_label: str, actor_capacity: str, represented_date_or_period: str | None, represented_value: str | None, rationale: str, qualification: str, limitations: str, declaration: Mapping[str, Any] | None, bindings: Any, subject_links: Any = None, actor: str, actor_role: str, idempotency_key: str | None = None, created_at: str | None = None, document_root: Path | None = None) -> dict[str, Any]:
    if parent_kind not in {"notice", "deadline"} or event_category not in EVENT_CATEGORIES: raise ValueError("governed_procedural_time_event_invalid")
    parent = get_notice(conn, parent_id) if parent_kind == "notice" else get_deadline(conn, parent_id)
    primary = {"extension_requested": "extension_request_source", "extension_granted": "extension_grant_source", "late_filing_alleged": "determination_source", "formal_late_filing_determination_linked": "determination_source", "calculation_recorded": "calculation_basis_source", "calculated_expiry_recorded": "calculation_basis_source"}.get(event_category, "dispute_source" if "disputed" in event_category else "notice_source")
    normalized = _validate_bindings(conn, bindings, primary, document_root)
    declaration_value = _declaration(declaration, event_category, event_category in DECLARATIONS)
    if event_category in {"extension_granted", "calculated_expiry_recorded", "late_filing_alleged", "formal_late_filing_determination_linked"} and not str(represented_value or "").strip(): raise ValueError("governed_procedural_time_event_value_required")
    links = _objects(conn, subject_links, "notice_concerns" if parent_kind == "notice" else "deadline_applies_to") if subject_links is not None else parent["subject_links"]
    if event_category == "late_filing_alleged" and not any(x["object_type"] == "governed_allegation" for x in links): raise ValueError("governed_procedural_time_allegation_required")
    if event_category == "formal_late_filing_determination_linked" and not any(x["object_type"] == "governed_determination" for x in links): raise ValueError("governed_procedural_time_determination_required")
    if event_category == "late_filing_alleged" and not any(x["object_type"] == "governed_allegation" and x["relationship_role"] == "dispute_concerns" for x in links): raise ValueError("governed_procedural_time_allegation_relationship_required")
    if event_category == "formal_late_filing_determination_linked" and not any(x["object_type"] == "governed_determination" and x["relationship_role"] == "determination_addresses" for x in links): raise ValueError("governed_procedural_time_determination_relationship_required")
    payload = {"parent_kind": parent_kind, "parent_id": int(parent_id), "event_category": event_category, "actor_label": actor_label, "actor_capacity": actor_capacity, "represented_date_or_period": represented_date_or_period, "represented_value": represented_value, "rationale": rationale, "qualification": qualification, "limitations": limitations, "declaration": declaration_value, "bindings": normalized, "subject_links": links}
    key = str(idempotency_key or "").strip() or _key("stage71-event:", payload); ensure_procedural_time_tables(conn); payload_json = _json(payload)
    existing = conn.execute("SELECT * FROM record_governed_procedural_time_events WHERE idempotency_key=?", (key,)).fetchone()
    if existing:
        if existing["request_payload_json"] != payload_json: raise ValueError("governed_procedural_time_event_idempotency_conflict")
        return {"id": existing["id"], "event_category": existing["event_category"], "status": existing["status"]}
    try:
        cur = conn.execute("INSERT INTO record_governed_procedural_time_events (idempotency_key,parent_kind,parent_id,event_category,actor_label,actor_capacity,represented_date_or_period,represented_value,rationale,qualification,limitations,declaration_json,created_by,created_by_role,created_at,status,request_payload_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (key, parent_kind, int(parent_id), event_category, _required(actor_label, "governed_procedural_time_event_actor_required"), _required(actor_capacity, "governed_procedural_time_event_capacity_required"), _iso(represented_date_or_period, "governed_procedural_time_event_date_invalid"), represented_value, _required(rationale, "governed_procedural_time_event_rationale_required"), _required(qualification, "governed_procedural_time_event_qualification_required"), _required(limitations, "governed_procedural_time_event_limitations_required"), _json(declaration_value), _required(actor, "governed_procedural_time_recorder_required"), _required(actor_role, "governed_procedural_time_recorder_role_required"), str(created_at or utc_now()), "recorded", payload_json))
        ident = int(cur.lastrowid)
        conn.executemany("INSERT INTO record_governed_procedural_time_bindings (record_kind,record_id,source_type,source_id,binding_role,source_version,source_timestamp) VALUES (?,?,?,?,?,?,?)", [("event", ident, x["source_type"], x["source_id"], x["binding_role"], x.get("source_version"), x.get("source_timestamp")) for x in normalized])
        conn.commit()
    except Exception:
        conn.rollback(); raise
    return {"id": ident, "event_category": event_category, "parent_kind": parent_kind, "parent_id": int(parent_id), "status": "recorded", "declaration": declaration_value}


def calculate_deadline(conn: sqlite3.Connection, *, deadline_id: int | str, calculation_mode: str, trigger_input: str, interval_days: int | None, inclusivity: str, calculated_as_of: str, time_zone: str, requested_by: str, idempotency_key: str | None = None, calculated_at: str | None = None) -> dict[str, Any]:
    deadline = get_deadline(conn, deadline_id)
    if calculation_mode not in CALCULATION_MODES: raise ValueError("governed_deadline_calculation_mode_unsupported")
    trigger = _iso(trigger_input, "governed_deadline_calculation_trigger_invalid", allow_period=False)
    as_of = _iso(calculated_as_of, "governed_deadline_calculation_as_of_invalid", allow_period=False)
    if not trigger or not as_of: raise ValueError("governed_deadline_calculation_input_required")
    if calculation_mode == "calendar_days_after_explicit_trigger":
        if not isinstance(interval_days, int) or interval_days < 0: raise ValueError("governed_deadline_calculation_interval_invalid")
        calculated = (date.fromisoformat(trigger[:10]) + timedelta(days=interval_days + (1 if inclusivity == "exclusive" else 0))).isoformat()
    else:
        calculated = date.fromisoformat(deadline["deadline_date_or_period"][:10]).isoformat() if deadline.get("deadline_date_or_period") else None
        if not calculated: raise ValueError("governed_deadline_calculation_deadline_input_required")
        interval_days = None
    if inclusivity not in {"inclusive", "exclusive"}: raise ValueError("governed_deadline_calculation_inclusivity_invalid")
    result = "deadline_not_reached_as_calculated" if as_of[:10] < calculated else "deadline_reached_as_calculated" if as_of[:10] == calculated else "deadline_passed_as_calculated"
    payload = {"deadline_id": int(deadline_id), "calculation_mode": calculation_mode, "trigger_input": trigger, "interval_days": interval_days, "inclusivity": inclusivity, "calculated_deadline": calculated, "calculated_as_of": as_of, "time_zone": _required(time_zone, "governed_deadline_calculation_timezone_required"), "requested_by": _required(requested_by, "governed_deadline_calculation_actor_required")}
    key = str(idempotency_key or "").strip() or _key("stage71-calculation:", payload); ensure_procedural_time_tables(conn); payload_json = _json(payload)
    old = conn.execute("SELECT * FROM record_governed_deadline_calculations WHERE idempotency_key=?", (key,)).fetchone()
    if old:
        if old["request_payload_json"] != payload_json: raise ValueError("governed_deadline_calculation_idempotency_conflict")
        return dict(old)
    trace = f"mode={calculation_mode}; trigger={trigger}; interval_days={interval_days}; inclusivity={inclusivity}; calculated_as_of={as_of}; result={result}"
    cur = conn.execute("INSERT INTO record_governed_deadline_calculations (idempotency_key,deadline_id,calculation_mode,trigger_input,interval_days,inclusivity,calculated_deadline,calculated_as_of,time_zone,normalized_inputs_json,calculation_trace,result_category,algorithm_version,requested_by,calculated_at,request_payload_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (key, int(deadline_id), calculation_mode, trigger, interval_days, inclusivity, calculated, as_of, time_zone, _json(payload), trace, result, SCHEMA_VERSION_CALCULATION, requested_by, str(calculated_at or utc_now()), payload_json))
    conn.commit(); return {"id": int(cur.lastrowid), **payload, "calculated_deadline": calculated, "result_category": result, "calculation_trace": trace}


def review_procedural_time(conn: sqlite3.Connection, *, target_kind: str, target_id: int, disposition: str, rationale: str, boundary_declaration: Mapping[str, Any], actor: str, actor_role: str, idempotency_key: str | None = None, reviewed_at: str | None = None) -> dict[str, Any]:
    target = get_notice(conn, target_id) if target_kind == "notice" else get_deadline(conn, target_id)
    if disposition not in REVIEW_DISPOSITIONS: raise ValueError("governed_procedural_time_review_disposition_invalid")
    if not isinstance(boundary_declaration, Mapping) or boundary_declaration.get("acknowledged") not in (True, "1"): raise ValueError("governed_procedural_time_review_declaration_required")
    payload = {"target_kind": target_kind, "target_id": int(target_id), "disposition": disposition, "rationale": _required(rationale, "governed_procedural_time_review_rationale_required"), "actor": _required(actor, "governed_procedural_time_reviewer_required"), "actor_role": _required(actor_role, "governed_procedural_time_reviewer_role_required")}; key = str(idempotency_key or "").strip() or _key("stage71-review:", payload); ensure_procedural_time_tables(conn); payload_json = _json(payload)
    old = conn.execute("SELECT * FROM record_governed_procedural_time_reviews WHERE idempotency_key=?", (key,)).fetchone()
    if old:
        if old["request_payload_json"] != payload_json: raise ValueError("governed_procedural_time_review_idempotency_conflict")
        return target
    conn.execute("INSERT INTO record_governed_procedural_time_reviews (target_kind,target_id,disposition,reviewer,reviewer_role,rationale,boundary_declaration_json,is_self_review,reviewed_at,idempotency_key,request_payload_json) VALUES (?,?,?,?,?,?,?,?,?,?,?)", (target_kind, int(target_id), disposition, payload["actor"], payload["actor_role"], payload["rationale"], _json(dict(boundary_declaration)), int(payload["actor"] == str(target["created_by"])), str(reviewed_at or utc_now()), key, payload_json)); conn.commit(); return get_notice(conn, target_id) if target_kind == "notice" else get_deadline(conn, target_id)


def supersede_procedural_time(conn: sqlite3.Connection, *, target_kind: str, target_id: int, replacement_kind: str, replacement_id: int, rationale: str, actor: str, actor_role: str, idempotency_key: str | None = None, occurred_at: str | None = None) -> dict[str, Any]:
    if target_kind != replacement_kind or target_kind not in {"notice", "deadline"}: raise ValueError("governed_procedural_time_supersession_kind_mismatch")
    target = get_notice(conn, target_id) if target_kind == "notice" else get_deadline(conn, target_id); replacement = get_notice(conn, replacement_id) if target_kind == "notice" else get_deadline(conn, replacement_id)
    if target_id == replacement_id: raise ValueError("governed_procedural_time_self_supersession")
    if not target["subject_links"] or not replacement["subject_links"] or {x["object_id"] for x in target["subject_links"]} .isdisjoint({x["object_id"] for x in replacement["subject_links"]}): raise ValueError("governed_procedural_time_supersession_subject_mismatch")
    payload = {"target_kind": target_kind, "target_id": int(target_id), "replacement_kind": replacement_kind, "replacement_id": int(replacement_id), "rationale": _required(rationale, "governed_procedural_time_supersession_rationale_required"), "actor": _required(actor, "governed_procedural_time_supersession_actor_required"), "actor_role": _required(actor_role, "governed_procedural_time_supersession_actor_role_required")}; key = str(idempotency_key or "").strip() or _key("stage71-supersession:", payload); ensure_procedural_time_tables(conn); payload_json = _json(payload)
    old = conn.execute("SELECT * FROM record_governed_procedural_time_supersessions WHERE idempotency_key=?", (key,)).fetchone()
    if old:
        if old["request_payload_json"] != payload_json: raise ValueError("governed_procedural_time_supersession_idempotency_conflict")
        return target
    if target["status"] == "superseded": raise ValueError("governed_procedural_time_already_superseded")
    current = int(replacement_id); seen = {int(target_id)}
    while True:
        row = conn.execute("SELECT replacement_id FROM record_governed_procedural_time_supersessions WHERE target_kind=? AND target_id=?", (target_kind, current)).fetchone()
        if not row: break
        current = int(row[0])
        if current in seen: raise ValueError("governed_procedural_time_supersession_cycle")
        seen.add(current)
    conn.execute("INSERT INTO record_governed_procedural_time_supersessions (target_kind,target_id,replacement_kind,replacement_id,rationale,actor,actor_role,occurred_at,idempotency_key,request_payload_json) VALUES (?,?,?,?,?,?,?,?,?,?)", (target_kind, int(target_id), replacement_kind, int(replacement_id), payload["rationale"], payload["actor"], payload["actor_role"], str(occurred_at or utc_now()), key, payload_json)); conn.commit(); return get_notice(conn, target_id) if target_kind == "notice" else get_deadline(conn, target_id)
