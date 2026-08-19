"""Stage 70 human-recorded implementation and compliance event preservation.

Stage 70 preserves reports, submissions, verification activities and formal
determinations about a Stage 69 direction.  It never calculates compliance or
mutates the direction it concerns.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from api import record_governed_allegations as allegations
from api import record_governed_determinations as determinations
from api import record_governed_inferences as inferences
from api import record_governed_remedies as remedies

SCHEMA_VERSION = "stage70.human_governed_implementation_event.v1"
AUTHORING_MODE = "human_recorded"
EVENT_CATEGORIES = {
    "implementation_reported", "partial_implementation_reported",
    "implementation_disputed", "deadline_extension_recorded",
    "compliance_evidence_submitted", "non_compliance_alleged",
    "verification_performed", "implementation_completed_as_formally_determined",
}
EPISTEMIC_BASES = {"attributed_report", "documentary_submission", "independent_verification_record", "formal_determination"}
REPRESENTATION_MODES = {"verbatim", "faithful_paraphrase"}
BINDING_ROLES = {"event_source", "implementation_material", "verification_source", "extension_source", "contextual_source", "contrary_source"}
SOURCE_TYPES = inferences.SOURCE_TYPES
OBJECT_TYPES = {"governed_allegation": "record_governed_allegations", "governed_determination": "record_governed_determinations"}
OBJECT_ROLES = {"allegation_context", "formal_completion_determination", "verifier_capacity_context", "contrary_material"}
VERIFICATION_CONCLUSIONS = {"implementation_supported_as_reported", "partial_implementation_supported_as_reported", "implementation_not_supported_by_verification", "verification_inconclusive"}
REVIEW_DISPOSITIONS = {"accepted_as_represented_event", "requires_representation_correction", "not_accepted_as_represented_event"}
STATUSES = {"recorded", "accepted_as_represented_event", "representation_correction_required", "not_accepted_as_represented_event", "superseded"}

QUALIFICATION_BOUNDARY = "This record preserves a source-bound event concerning the represented implementation or compliance history of an identified remedy or direction. Its recording does not establish implementation, non-implementation, compliance, breach, satisfaction, sufficiency of evidence, enforceability, lawfulness or legal effect."
LIMITATIONS_BOUNDARY = "Reports, submissions, disputes, verification records and formal determinations may coexist. Absence of a later event from the governed record does not establish performance, non-performance, abandonment, breach or completion."
AUTHOR_BOUNDARY = "I confirm that this is a human-recorded, remedy-linked and source-bound event. Recording it does not convert a report, submission, allegation or verification activity into an implementation or compliance determination."
REPRESENTATION_BOUNDARY = "The selected representation mode is a human declaration and is not machine-verified."
REVIEW_BOUNDARY = "Acceptance confirms only faithful representation, attribution and source connection. It does not confirm implementation, compliance, breach or evidential sufficiency."
FORMAL_COMPLETION_BOUNDARY = "I confirm that the linked, distinct and eligible governed determination expressly represents implementation as completed. The CDE is preserving that formal determination and is not independently determining completion or compliance."
VERIFICATION_BOUNDARY = "I confirm that the identified governed source records a verification activity, including the represented verifier or verifying body, capacity, method and conclusion. Recording this activity does not mean that the CDE performed the verification or independently adopts its conclusion."
NON_COMPLIANCE_BOUNDARY = "I confirm that the linked governed allegation expressly preserves an attributed allegation of non-compliance. Recording this event does not establish breach, non-performance, wrongdoing, liability or a finding of non-compliance."
EXTENSION_BOUNDARY = "I confirm that the identified governed source expressly records the represented deadline extension. Recording the extension does not establish that it was validly authorised, legally effective, accepted or complied with."
CONDITIONAL_DECLARATION_BOUNDARIES = {
    "verification_performed": VERIFICATION_BOUNDARY,
    "implementation_completed_as_formally_determined": FORMAL_COMPLETION_BOUNDARY,
    "non_compliance_alleged": NON_COMPLIANCE_BOUNDARY,
    "deadline_extension_recorded": EXTENSION_BOUNDARY,
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


def _declaration(value: Any, error: str, boundary: str, *, category: str | None = None, required: bool = True) -> dict[str, Any]:
    if not required:
        if value is not None and value != {"acknowledged": False}:
            raise ValueError("governed_implementation_event_conditional_declaration_inapplicable")
        return {"human_recorded": True, "acknowledged": False, "boundary": "not_applicable"}
    if not isinstance(value, Mapping) or set(value) - {"acknowledged", "category"}:
        raise ValueError("governed_implementation_event_conditional_declaration_malformed")
    if value.get("acknowledged") not in (True, "1"):
        raise ValueError(error)
    submitted_category = value.get("category")
    if submitted_category is not None and submitted_category != category:
        raise ValueError("governed_implementation_event_conditional_declaration_category_mismatch")
    return {"human_recorded": True, "acknowledged": True, "boundary": boundary, "category": category}


def _qualification(value: Any, limitations: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("governed_implementation_event_qualification_contract_required")
    expected = {"epistemic_label": "implementation_or_compliance_event", "remedy_link_present": True, "source_basis_present": True, "not_implementation_verified": True, "not_compliance_status": True, "not_breach_finding": True, "not_legal_effect": True}
    if any(value.get(key) != expected_value for key, expected_value in expected.items()):
        raise ValueError("governed_implementation_event_qualification_contract_incomplete")
    result = dict(expected)
    result["limitations"] = _required(limitations, "governed_implementation_event_limitations_required")
    return result


def ensure_implementation_event_tables(conn: sqlite3.Connection) -> None:
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS record_governed_implementation_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT, idempotency_key TEXT NOT NULL UNIQUE,
      schema_version TEXT NOT NULL, authoring_mode TEXT NOT NULL, event_category TEXT NOT NULL,
      epistemic_basis TEXT NOT NULL, title_label TEXT NOT NULL, event_description TEXT NOT NULL,
      representation_mode TEXT NOT NULL, attributed_participant TEXT NOT NULL,
      represented_capacity TEXT NOT NULL, represented_event_date_or_period TEXT,
      recorded_date TEXT, represented_amount_quantity_extent TEXT,
      represented_deadline_or_extension TEXT, verification_method TEXT,
      verification_conclusion TEXT, rationale TEXT NOT NULL, qualification TEXT NOT NULL,
      limitations TEXT NOT NULL, qualification_contract_json TEXT NOT NULL,
      author_declaration_json TEXT NOT NULL, representation_declaration_json TEXT NOT NULL,
      conditional_declaration_json TEXT NOT NULL, status TEXT NOT NULL,
      created_by TEXT NOT NULL, created_by_role TEXT NOT NULL, created_at TEXT NOT NULL,
      request_payload_json TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS record_governed_implementation_event_remedy_links (
      id INTEGER PRIMARY KEY AUTOINCREMENT, event_id INTEGER NOT NULL UNIQUE, remedy_id INTEGER NOT NULL,
      FOREIGN KEY(event_id) REFERENCES record_governed_implementation_events(id)
    );
    CREATE TABLE IF NOT EXISTS record_governed_implementation_event_bindings (
      id INTEGER PRIMARY KEY AUTOINCREMENT, event_id INTEGER NOT NULL, source_type TEXT NOT NULL,
      source_id TEXT NOT NULL, binding_role TEXT NOT NULL, source_version TEXT, source_timestamp TEXT,
      UNIQUE(event_id, source_type, source_id, binding_role)
    );
    CREATE TABLE IF NOT EXISTS record_governed_implementation_event_object_links (
      id INTEGER PRIMARY KEY AUTOINCREMENT, event_id INTEGER NOT NULL, object_type TEXT NOT NULL,
      object_id INTEGER NOT NULL, relationship_role TEXT NOT NULL,
      UNIQUE(event_id, object_type, object_id, relationship_role)
    );
    CREATE TABLE IF NOT EXISTS record_governed_implementation_event_reviews (
      id INTEGER PRIMARY KEY AUTOINCREMENT, event_id INTEGER NOT NULL, disposition TEXT NOT NULL,
      reviewed_by TEXT NOT NULL, reviewed_by_role TEXT NOT NULL, rationale TEXT NOT NULL,
      boundary_declaration_json TEXT NOT NULL, is_self_review INTEGER NOT NULL,
      reviewed_at TEXT NOT NULL, idempotency_key TEXT NOT NULL UNIQUE, request_payload_json TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS record_governed_implementation_event_supersessions (
      id INTEGER PRIMARY KEY AUTOINCREMENT, event_id INTEGER NOT NULL, replacement_event_id INTEGER NOT NULL,
      rationale TEXT NOT NULL, actor TEXT NOT NULL, actor_role TEXT NOT NULL, occurred_at TEXT NOT NULL,
      idempotency_key TEXT NOT NULL UNIQUE, request_payload_json TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_stage70_event_status ON record_governed_implementation_events(status, created_at);
    """)


def _key(prefix: str, payload: Mapping[str, Any]) -> str:
    return prefix + hashlib.sha256(_json(payload).encode()).hexdigest()


def _canonical_bindings(bindings: Any, category: str) -> list[dict[str, Any]]:
    if not isinstance(bindings, (list, tuple)) or not bindings:
        raise ValueError("governed_implementation_event_binding_required")
    result = []
    for item in bindings:
        if not isinstance(item, Mapping) or set(item) - {"source_type", "source_id", "binding_role", "source_version", "source_timestamp"}:
            raise ValueError("governed_implementation_event_binding_invalid")
        source_type = _required(item.get("source_type"), "governed_implementation_event_source_type_required")
        source_id = _required(item.get("source_id"), "governed_implementation_event_source_id_required")
        role = _required(item.get("binding_role"), "governed_implementation_event_binding_role_required")
        if source_type not in SOURCE_TYPES or role not in BINDING_ROLES:
            raise ValueError("governed_implementation_event_binding_invalid")
        result.append({"source_type": source_type, "source_id": source_id, "binding_role": role, "source_version": item.get("source_version"), "source_timestamp": item.get("source_timestamp")})
    result.sort(key=lambda x: (x["source_type"], x["source_id"], x["binding_role"]))
    if len({(x["source_type"], x["source_id"], x["binding_role"]) for x in result}) != len(result):
        raise ValueError("governed_implementation_event_duplicate_binding")
    if not any(x["binding_role"] == "event_source" for x in result):
        raise ValueError("governed_implementation_event_source_required")
    if category == "verification_performed" and not any(x["binding_role"] == "verification_source" for x in result):
        raise ValueError("governed_implementation_event_verification_source_required")
    if category == "deadline_extension_recorded" and not any(x["binding_role"] == "extension_source" for x in result):
        raise ValueError("governed_implementation_event_extension_source_required")
    return result


def _validate_bindings(conn: sqlite3.Connection, bindings: Any, category: str, document_root: Path | None) -> list[dict[str, Any]]:
    return [inferences._source_binding(conn, item, document_root=document_root) for item in _canonical_bindings(bindings, category)]


def _remedy(conn: sqlite3.Connection, remedy_id: int | str) -> dict[str, Any]:
    try:
        item = remedies.get_remedy(conn, int(remedy_id))
    except (ValueError, TypeError):
        raise ValueError("governed_implementation_event_remedy_not_found") from None
    if item.get("status") not in {"recorded", "accepted_as_represented_direction"}:
        raise ValueError("governed_implementation_event_remedy_not_eligible")
    return item


def _canonical_objects(conn: sqlite3.Connection, objects: Any, category: str, remedy: Mapping[str, Any]) -> list[dict[str, Any]]:
    if objects is None:
        objects = []
    if not isinstance(objects, (list, tuple)):
        raise ValueError("governed_implementation_event_object_links_invalid")
    result = []
    for item in objects:
        if not isinstance(item, Mapping) or set(item) - {"object_type", "object_id", "relationship_role"}:
            raise ValueError("governed_implementation_event_object_link_invalid")
        object_type = _required(item.get("object_type"), "governed_implementation_event_object_type_required")
        object_id = _required(item.get("object_id"), "governed_implementation_event_object_id_required")
        role = _required(item.get("relationship_role"), "governed_implementation_event_object_role_required")
        if object_type not in OBJECT_TYPES or role not in OBJECT_ROLES:
            raise ValueError("governed_implementation_event_object_link_invalid")
        if category == "non_compliance_alleged" and object_type != "governed_allegation":
            raise ValueError("governed_implementation_event_non_compliance_object_required")
        if category == "implementation_completed_as_formally_determined" and (object_type != "governed_determination" or role != "formal_completion_determination"):
            raise ValueError("governed_implementation_event_formal_determination_required")
        table = OBJECT_TYPES[object_type]
        if not _table_exists(conn, table):
            raise ValueError("governed_implementation_event_object_not_found")
        try:
            row = conn.execute(f"SELECT * FROM {table} WHERE id=?", (int(object_id),)).fetchone()
        except (TypeError, ValueError, sqlite3.Error):
            raise ValueError("governed_implementation_event_object_not_found") from None
        if row is None:
            raise ValueError("governed_implementation_event_object_not_found")
        if object_type == "governed_allegation":
            if dict(row).get("status") not in {"recorded", "accepted_as_attributed_allegation"}:
                raise ValueError("governed_implementation_event_object_not_eligible")
        if object_type == "governed_determination":
            determination = determinations.get_determination(conn, object_id)
            if determination.get("status") != "accepted_as_attributed_determination_record":
                raise ValueError("governed_implementation_event_object_not_eligible")
            directing_id = remedy.get("determination", {}).get("determination_id")
            if category == "implementation_completed_as_formally_determined" and int(object_id) == int(directing_id):
                raise ValueError("governed_implementation_event_formal_determination_must_be_distinct")
        result.append({"object_type": object_type, "object_id": int(object_id), "relationship_role": role})
    result.sort(key=lambda x: (x["object_type"], x["object_id"], x["relationship_role"]))
    if len({(x["object_type"], x["object_id"], x["relationship_role"]) for x in result}) != len(result):
        raise ValueError("governed_implementation_event_duplicate_object_link")
    if category == "non_compliance_alleged" and not any(x["object_type"] == "governed_allegation" for x in result):
        raise ValueError("governed_implementation_event_allegation_link_required")
    if category == "implementation_completed_as_formally_determined" and not any(x["object_type"] == "governed_determination" for x in result):
        raise ValueError("governed_implementation_event_formal_determination_required")
    return result


def _row(row: sqlite3.Row | Mapping[str, Any]) -> dict[str, Any]:
    result = dict(row)
    for field in ("qualification_contract_json", "author_declaration_json", "representation_declaration_json", "conditional_declaration_json", "request_payload_json"):
        if field in result:
            result[field.removesuffix("_json")] = json.loads(result.pop(field))
    return result


def _status(conn: sqlite3.Connection, event_id: int, base: str) -> str:
    if conn.execute("SELECT 1 FROM record_governed_implementation_event_supersessions WHERE event_id=?", (event_id,)).fetchone():
        return "superseded"
    row = conn.execute("SELECT disposition FROM record_governed_implementation_event_reviews WHERE event_id=? ORDER BY id DESC LIMIT 1", (event_id,)).fetchone()
    if not row:
        return base
    return "representation_correction_required" if row[0] == "requires_representation_correction" else str(row[0])


def get_implementation_event(conn: sqlite3.Connection, event_id: int | str) -> dict[str, Any]:
    if not _table_exists(conn, "record_governed_implementation_events"):
        raise ValueError("governed_implementation_event_table_absent")
    try:
        row = conn.execute("SELECT * FROM record_governed_implementation_events WHERE id=?", (int(event_id),)).fetchone()
    except (TypeError, ValueError):
        row = None
    if row is None:
        raise ValueError("governed_implementation_event_not_found")
    result = _row(row)
    result["status"] = _status(conn, int(event_id), result["status"])
    result["remedy"] = dict(conn.execute("SELECT * FROM record_governed_implementation_event_remedy_links WHERE event_id=?", (event_id,)).fetchone())
    result["bindings"] = [dict(x) for x in conn.execute("SELECT * FROM record_governed_implementation_event_bindings WHERE event_id=? ORDER BY id", (event_id,)).fetchall()]
    result["governed_objects"] = [dict(x) for x in conn.execute("SELECT * FROM record_governed_implementation_event_object_links WHERE event_id=? ORDER BY id", (event_id,)).fetchall()]
    result["reviews"] = [dict(x) for x in conn.execute("SELECT * FROM record_governed_implementation_event_reviews WHERE event_id=? ORDER BY id", (event_id,)).fetchall()]
    result["supersessions"] = [dict(x) for x in conn.execute("SELECT * FROM record_governed_implementation_event_supersessions WHERE event_id=? ORDER BY id", (event_id,)).fetchall()]
    return result


def list_implementation_events(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    if not _table_exists(conn, "record_governed_implementation_events"):
        return []
    return [get_implementation_event(conn, row[0]) for row in conn.execute("SELECT id FROM record_governed_implementation_events ORDER BY created_at,id").fetchall()]


def read_implementation_event_diagnostic(event_id: int | str | None = None, *, db_path: str | Path) -> dict[str, Any]:
    path = Path(db_path)
    if not path.is_file():
        return {"status": "database_unavailable", "events": []}
    try:
        conn = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
    except sqlite3.Error:
        return {"status": "database_unavailable", "events": []}
    try:
        if not _table_exists(conn, "record_governed_implementation_events"):
            return {"status": "ok", "events": [], "implementation_event_table_present": False}
        if event_id is None:
            return {"status": "ok", "events": list_implementation_events(conn), "implementation_event_table_present": True}
        try:
            return {"status": "ok", "events": [get_implementation_event(conn, event_id)], "implementation_event_table_present": True}
        except ValueError:
            return {"status": "event_not_found", "events": [], "implementation_event_table_present": True}
    finally:
        conn.close()


def create_implementation_event(conn: sqlite3.Connection, *, event_category: str, epistemic_basis: str, title_label: str, event_description: str, representation_mode: str, attributed_participant: str, represented_capacity: str, represented_event_date_or_period: str | None, recorded_date: str | None, represented_amount_quantity_extent: str | None, represented_deadline_or_extension: str | None, verification_method: str | None, verification_conclusion: str | None, rationale: str, qualification: str, limitations: str, qualification_contract: Mapping[str, Any], author_declaration: Mapping[str, Any], representation_declaration: Mapping[str, Any], conditional_declaration: Mapping[str, Any] | None, remedy_id: int | str, bindings: Any, governed_objects: Any = None, actor: str, actor_role: str, idempotency_key: str | None = None, created_at: str | None = None, document_root: Path | None = None, _commit: bool = True) -> dict[str, Any]:
    category = _required(event_category, "governed_implementation_event_category_required").lower()
    basis = _required(epistemic_basis, "governed_implementation_event_epistemic_basis_required").lower()
    mode = _required(representation_mode, "governed_implementation_event_representation_mode_required").lower()
    if category not in EVENT_CATEGORIES:
        raise ValueError("governed_implementation_event_category_invalid")
    if basis not in EPISTEMIC_BASES:
        raise ValueError("governed_implementation_event_epistemic_basis_invalid")
    if mode not in REPRESENTATION_MODES:
        raise ValueError("governed_implementation_event_representation_mode_invalid")
    expected_basis = {"compliance_evidence_submitted": "documentary_submission", "verification_performed": "independent_verification_record", "implementation_completed_as_formally_determined": "formal_determination"}.get(category, "attributed_report")
    if basis != expected_basis:
        raise ValueError("governed_implementation_event_category_basis_mismatch")
    remedy = _remedy(conn, remedy_id)
    qualified = _qualification(qualification_contract, limitations)
    author = _declaration(author_declaration, "governed_implementation_event_author_declaration_required", AUTHOR_BOUNDARY)
    representation = _declaration(representation_declaration, "governed_implementation_event_representation_declaration_required", REPRESENTATION_BOUNDARY)
    representation["mode"] = mode
    conditional_error = {
        "verification_performed": "governed_implementation_event_verification_declaration_required",
        "implementation_completed_as_formally_determined": "governed_implementation_event_formal_completion_declaration_required",
        "non_compliance_alleged": "governed_implementation_event_non_compliance_declaration_required",
        "deadline_extension_recorded": "governed_implementation_event_extension_declaration_required",
    }.get(category)
    if conditional_error:
        conditional = _declaration(conditional_declaration, conditional_error, CONDITIONAL_DECLARATION_BOUNDARIES[category], category=category)
    else:
        conditional = _declaration(conditional_declaration, "", "", required=False)
    if category == "verification_performed" and not _required(represented_capacity, "governed_implementation_event_verifier_capacity_required"):
        raise ValueError("governed_implementation_event_verifier_capacity_required")
    if category == "verification_performed" and not _required(verification_method, "governed_implementation_event_verification_method_required"):
        raise ValueError("governed_implementation_event_verification_method_required")
    if verification_conclusion is not None and verification_conclusion not in VERIFICATION_CONCLUSIONS:
        raise ValueError("governed_implementation_event_verification_conclusion_invalid")
    if category == "verification_performed" and verification_conclusion is None:
        raise ValueError("governed_implementation_event_verification_conclusion_required")
    normalized = _validate_bindings(conn, bindings, category, document_root)
    objects = _canonical_objects(conn, governed_objects, category, remedy)
    payload = {"event_category": category, "epistemic_basis": basis, "title_label": _required(title_label, "governed_implementation_event_title_required"), "event_description": _required(event_description, "governed_implementation_event_description_required"), "representation_mode": mode, "attributed_participant": _required(attributed_participant, "governed_implementation_event_participant_required"), "represented_capacity": _required(represented_capacity, "governed_implementation_event_capacity_required"), "represented_event_date_or_period": represented_event_date_or_period, "recorded_date": recorded_date, "represented_amount_quantity_extent": represented_amount_quantity_extent, "represented_deadline_or_extension": represented_deadline_or_extension, "verification_method": verification_method, "verification_conclusion": verification_conclusion, "rationale": _required(rationale, "governed_implementation_event_rationale_required"), "qualification": _required(qualification, "governed_implementation_event_qualification_required"), "limitations": _required(limitations, "governed_implementation_event_limitations_required"), "qualification_contract": qualified, "author_declaration": author, "representation_declaration": representation, "conditional_declaration": conditional, "remedy_id": int(remedy["id"]), "bindings": normalized, "governed_objects": objects}
    key = str(idempotency_key or "").strip() or _key("stage70-event:", payload)
    ensure_implementation_event_tables(conn)
    payload_json = _json(payload)
    existing = conn.execute("SELECT * FROM record_governed_implementation_events WHERE idempotency_key=?", (key,)).fetchone()
    if existing is not None:
        if existing["request_payload_json"] != payload_json:
            raise ValueError("governed_implementation_event_idempotency_conflict")
        return get_implementation_event(conn, existing["id"])
    try:
        cur = conn.execute("INSERT INTO record_governed_implementation_events (idempotency_key,schema_version,authoring_mode,event_category,epistemic_basis,title_label,event_description,representation_mode,attributed_participant,represented_capacity,represented_event_date_or_period,recorded_date,represented_amount_quantity_extent,represented_deadline_or_extension,verification_method,verification_conclusion,rationale,qualification,limitations,qualification_contract_json,author_declaration_json,representation_declaration_json,conditional_declaration_json,status,created_by,created_by_role,created_at,request_payload_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (key, SCHEMA_VERSION, AUTHORING_MODE, category, basis, payload["title_label"], payload["event_description"], mode, payload["attributed_participant"], payload["represented_capacity"], represented_event_date_or_period, recorded_date, represented_amount_quantity_extent, represented_deadline_or_extension, verification_method, verification_conclusion, payload["rationale"], payload["qualification"], payload["limitations"], _json(qualified), _json(author), _json(representation), _json(conditional), "recorded", _required(actor, "governed_implementation_event_recorder_required"), _required(actor_role, "governed_implementation_event_recorder_role_required"), str(created_at or utc_now()), payload_json))
        event_id = int(cur.lastrowid)
        conn.execute("INSERT INTO record_governed_implementation_event_remedy_links (event_id,remedy_id) VALUES (?,?)", (event_id, remedy["id"]))
        conn.executemany("INSERT INTO record_governed_implementation_event_bindings (event_id,source_type,source_id,binding_role,source_version,source_timestamp) VALUES (?,?,?,?,?,?)", [(event_id, x["source_type"], x["source_id"], x["binding_role"], x["source_version"], x["source_timestamp"]) for x in normalized])
        conn.executemany("INSERT INTO record_governed_implementation_event_object_links (event_id,object_type,object_id,relationship_role) VALUES (?,?,?,?)", [(event_id, x["object_type"], x["object_id"], x["relationship_role"]) for x in objects])
        if _commit:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    return get_implementation_event(conn, event_id)


def review_implementation_event(conn: sqlite3.Connection, *, event_id: int | str, disposition: str, rationale: str, boundary_declaration: Mapping[str, Any], actor: str, actor_role: str, idempotency_key: str | None = None, reviewed_at: str | None = None, _commit: bool = True) -> dict[str, Any]:
    target = get_implementation_event(conn, event_id)
    value = _required(disposition, "governed_implementation_event_review_disposition_required").lower()
    if value not in REVIEW_DISPOSITIONS:
        raise ValueError("governed_implementation_event_review_disposition_invalid")
    declaration = _declaration(boundary_declaration, "governed_implementation_event_review_declaration_required", REVIEW_BOUNDARY)
    payload = {"event_id": int(event_id), "disposition": value, "rationale": _required(rationale, "governed_implementation_event_review_rationale_required"), "boundary_declaration": declaration, "is_self_review": _required(actor, "governed_implementation_event_reviewer_required") == str(target["created_by"])}
    key = str(idempotency_key or "").strip() or _key("stage70-review:", payload)
    ensure_implementation_event_tables(conn)
    payload_json = _json(payload)
    existing = conn.execute("SELECT * FROM record_governed_implementation_event_reviews WHERE idempotency_key=?", (key,)).fetchone()
    if existing is not None:
        if existing["request_payload_json"] != payload_json:
            raise ValueError("governed_implementation_event_review_idempotency_conflict")
        return get_implementation_event(conn, event_id)
    try:
        conn.execute("INSERT INTO record_governed_implementation_event_reviews (event_id,disposition,reviewed_by,reviewed_by_role,rationale,boundary_declaration_json,is_self_review,reviewed_at,idempotency_key,request_payload_json) VALUES (?,?,?,?,?,?,?,?,?,?)", (int(event_id), value, _required(actor, "governed_implementation_event_reviewer_required"), _required(actor_role, "governed_implementation_event_reviewer_role_required"), payload["rationale"], _json(declaration), int(payload["is_self_review"]), str(reviewed_at or utc_now()), key, payload_json))
        if _commit:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    return get_implementation_event(conn, event_id)


def supersede_implementation_event(conn: sqlite3.Connection, *, event_id: int | str, replacement_event_id: int | str, rationale: str, actor: str, actor_role: str, idempotency_key: str | None = None, occurred_at: str | None = None, _commit: bool = True) -> dict[str, Any]:
    target = get_implementation_event(conn, event_id)
    replacement = get_implementation_event(conn, replacement_event_id)
    if int(event_id) == int(replacement_event_id):
        raise ValueError("governed_implementation_event_self_supersession")
    if int(target["remedy"]["remedy_id"]) != int(replacement["remedy"]["remedy_id"]):
        raise ValueError("governed_implementation_event_supersession_remedy_mismatch")
    payload = {"event_id": int(event_id), "replacement_event_id": int(replacement_event_id), "rationale": _required(rationale, "governed_implementation_event_supersession_rationale_required"), "actor": _required(actor, "governed_implementation_event_supersession_actor_required"), "actor_role": _required(actor_role, "governed_implementation_event_supersession_actor_role_required")}
    key = str(idempotency_key or "").strip() or _key("stage70-supersession:", payload)
    ensure_implementation_event_tables(conn)
    payload_json = _json(payload)
    existing = conn.execute("SELECT * FROM record_governed_implementation_event_supersessions WHERE idempotency_key=?", (key,)).fetchone()
    if existing is not None:
        if existing["request_payload_json"] != payload_json:
            raise ValueError("governed_implementation_event_supersession_idempotency_conflict")
        return get_implementation_event(conn, event_id)
    if target["status"] == "superseded":
        raise ValueError("governed_implementation_event_already_superseded")
    seen = {int(event_id)}
    current = int(replacement_event_id)
    while True:
        row = conn.execute("SELECT replacement_event_id FROM record_governed_implementation_event_supersessions WHERE event_id=?", (current,)).fetchone()
        if row is None:
            break
        current = int(row[0])
        if current in seen:
            raise ValueError("governed_implementation_event_supersession_cycle")
        seen.add(current)
    try:
        conn.execute("INSERT INTO record_governed_implementation_event_supersessions (event_id,replacement_event_id,rationale,actor,actor_role,occurred_at,idempotency_key,request_payload_json) VALUES (?,?,?,?,?,?,?,?)", (int(event_id), int(replacement_event_id), payload["rationale"], payload["actor"], payload["actor_role"], str(occurred_at or utc_now()), key, payload_json))
        if _commit:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    return get_implementation_event(conn, event_id)
