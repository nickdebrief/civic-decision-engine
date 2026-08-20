"""Stage 72 governed pathway relationships and read-only projections.

This module records deliberate administrative relationships between existing
governed objects. It never infers edges, reliance, completeness, causation,
proof, or legal effect.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from api import record_governed_allegations as allegations

SCHEMA_VERSION = "stage72.human_governed_pathway_relationship.v1"
AUTHORING_MODE = "human_recorded"

OBJECT_TABLES = {
    "accepted_pattern_observation": ("record_pattern_observations", "id"),
    "governed_inference": ("record_governed_inferences", "id"),
    "governed_allegation": ("record_governed_allegations", "id"),
    "governed_response": ("record_governed_responses", "id"),
    "decision_authority": ("record_governed_decision_authorities", "id"),
    "decision_mandate": ("record_governed_decision_authority_mandates", "id"),
    "governed_determination": ("record_governed_determinations", "id"),
    "governed_challenge": ("record_governed_challenge_proceedings", "id"),
    "governed_remedy": ("record_governed_remedies", "id"),
    "governed_implementation_event": ("record_governed_implementation_events", "id"),
    "record_document_association": ("record_document_associations", "id"),
    "canonical_record": ("records", "reference"),
}

RELATIONSHIPS = {
    "evidence_to_observation": ("evidence", "accepted_pattern_observation"),
    "evidence_to_inference": ("evidence", "governed_inference"),
    "evidence_to_allegation": ("evidence", "governed_allegation"),
    "allegation_to_response": ("governed_allegation", "governed_response"),
    "authority_to_determination": ("decision_authority", "governed_determination"),
    "mandate_to_determination": ("decision_mandate", "governed_determination"),
    "observation_to_determination": ("accepted_pattern_observation", "governed_determination"),
    "inference_to_determination": ("governed_inference", "governed_determination"),
    "allegation_to_determination": ("governed_allegation", "governed_determination"),
    "response_to_determination": ("governed_response", "governed_determination"),
    "determination_to_challenge": ("governed_determination", "governed_challenge"),
    "determination_to_remedy": ("governed_determination", "governed_remedy"),
    "remedy_to_implementation": ("governed_remedy", "governed_implementation_event"),
}
RELIANCE_STATUSES = {"not_represented", "considered", "expressly_relied_upon", "expressly_not_relied_upon", "disputed"}
CONTESTATION_STATUSES = {"not_represented", "disputed_as_recorded", "contested_as_recorded"}
SUPPORTING_BINDING_ROLES = {"relationship_source", "contextual_source", "contrary_source"}
SOURCE_TYPES = {"published_document", "canonical_record", "record_document_association", "accepted_pattern_observation"}
EVIDENCE_KINDS = SOURCE_TYPES
STATUSES = {"recorded", "accepted_as_represented_pathway_relationship", "requires_pathway_correction", "not_accepted_as_represented_pathway", "superseded"}
REVIEW_DISPOSITIONS = {"accepted_as_represented_pathway", "requires_pathway_correction", "not_accepted_as_represented_pathway"}

QUALIFICATION_BOUNDARY = "A link records a represented relationship. It does not prove the relationship correct, establish causation, validate an endpoint, or assert pathway completeness."
RELIANCE_BOUNDARY = "Reliance represented is not reliance justified. Expressed reliance does not establish correctness, reasonableness, sufficiency, weight, acceptance, or determinative effect."
CHRONOLOGY_BOUNDARY = "Chronology is not causation. The pathway view preserves recorded sequence and does not establish legal effect, completeness, or priority."
LIMITATIONS_BOUNDARY = "Omitted objects may exist; contrary material, contestation, withdrawal, supersession, appeal, review, and unresolved endpoint states may coexist."


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


def ensure_pathway_tables(conn: sqlite3.Connection) -> None:
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS record_governed_pathway_links (
      id INTEGER PRIMARY KEY AUTOINCREMENT, idempotency_key TEXT NOT NULL UNIQUE,
      schema_version TEXT NOT NULL, authoring_mode TEXT NOT NULL,
      source_object_kind TEXT NOT NULL, source_object_id TEXT NOT NULL,
      target_object_kind TEXT NOT NULL, target_object_id TEXT NOT NULL,
      relationship_type TEXT NOT NULL, rationale TEXT NOT NULL,
      reliance_status TEXT NOT NULL, reliance_description TEXT,
      reliance_declaration_json TEXT NOT NULL, contestation_status TEXT NOT NULL,
      contestation_representation TEXT, limitations TEXT NOT NULL,
      qualification_contract_json TEXT NOT NULL, status TEXT NOT NULL,
      created_by TEXT NOT NULL, created_by_role TEXT NOT NULL, created_at TEXT NOT NULL,
      request_payload_json TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS record_governed_pathway_bindings (
      id INTEGER PRIMARY KEY AUTOINCREMENT, pathway_link_id INTEGER NOT NULL,
      source_type TEXT NOT NULL, source_id TEXT NOT NULL, binding_role TEXT NOT NULL,
      source_version TEXT, source_timestamp TEXT,
      UNIQUE(pathway_link_id, source_type, source_id, binding_role)
    );
    CREATE TABLE IF NOT EXISTS record_governed_pathway_reviews (
      id INTEGER PRIMARY KEY AUTOINCREMENT, pathway_link_id INTEGER NOT NULL,
      disposition TEXT NOT NULL, reviewed_by TEXT NOT NULL, reviewed_by_role TEXT NOT NULL,
      rationale TEXT NOT NULL, boundary_declaration_json TEXT NOT NULL,
      is_self_review INTEGER NOT NULL, reviewed_at TEXT NOT NULL,
      idempotency_key TEXT NOT NULL UNIQUE, request_payload_json TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS record_governed_pathway_supersessions (
      id INTEGER PRIMARY KEY AUTOINCREMENT, pathway_link_id INTEGER NOT NULL,
      replacement_link_id INTEGER NOT NULL, rationale TEXT NOT NULL,
      actor TEXT NOT NULL, actor_role TEXT NOT NULL, occurred_at TEXT NOT NULL,
      idempotency_key TEXT NOT NULL UNIQUE, request_payload_json TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_stage72_pathway_endpoints
      ON record_governed_pathway_links(source_object_kind, source_object_id, target_object_kind, target_object_id);
    CREATE INDEX IF NOT EXISTS idx_stage72_pathway_status
      ON record_governed_pathway_links(status, created_at);
    """)


def _key(prefix: str, payload: Mapping[str, Any]) -> str:
    return prefix + hashlib.sha256(_json(payload).encode()).hexdigest()


def _endpoint(conn: sqlite3.Connection, kind: str, value: Any, *, document_root: Path | None = None) -> dict[str, Any]:
    if kind in EVIDENCE_KINDS:
        try:
            return {**allegations._source_binding(conn, {"source_type": kind, "source_id": _required(value, "governed_pathway_object_id_required")}, document_root=document_root), "object_kind": kind, "object_id": str(value), "status": "recorded"}
        except (KeyError, ValueError, TypeError):
            raise ValueError("governed_pathway_endpoint_not_found") from None
    if kind not in OBJECT_TABLES:
        raise ValueError("governed_pathway_object_kind_invalid")
    table, column = OBJECT_TABLES[kind]
    identifier = _required(value, "governed_pathway_object_id_required")
    if not _table_exists(conn, table):
        raise ValueError("governed_pathway_endpoint_not_found")
    row = conn.execute(f"SELECT * FROM {table} WHERE {column}=?", (identifier,)).fetchone()
    if not row:
        raise ValueError("governed_pathway_endpoint_not_found")
    result = dict(row)
    result["object_kind"] = kind
    result["object_id"] = identifier
    result["status"] = result.get("status") or "recorded"
    return result


def _canonical_bindings(bindings: Any) -> list[dict[str, Any]]:
    if not isinstance(bindings, (list, tuple)) or not bindings:
        raise ValueError("governed_pathway_relationship_source_required")
    result = []
    for item in bindings:
        if not isinstance(item, Mapping) or set(item) - {"source_type", "source_id", "binding_role", "source_version", "source_timestamp"}:
            raise ValueError("governed_pathway_binding_invalid")
        source_type = _required(item.get("source_type"), "governed_pathway_source_type_required")
        source_id = _required(item.get("source_id"), "governed_pathway_source_id_required")
        role = _required(item.get("binding_role"), "governed_pathway_binding_role_required")
        if source_type not in SOURCE_TYPES or role not in SUPPORTING_BINDING_ROLES:
            raise ValueError("governed_pathway_binding_invalid")
        result.append({"source_type": source_type, "source_id": source_id, "binding_role": role, "source_version": item.get("source_version"), "source_timestamp": item.get("source_timestamp")})
    result.sort(key=lambda x: (x["source_type"], x["source_id"], x["binding_role"]))
    if len({(x["source_type"], x["source_id"], x["binding_role"]) for x in result}) != len(result):
        raise ValueError("governed_pathway_duplicate_binding")
    if not any(x["binding_role"] == "relationship_source" for x in result):
        raise ValueError("governed_pathway_relationship_source_required")
    return result


def _declaration(value: Any, status: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) - {"acknowledged", "status"} or value.get("acknowledged") is not True:
        raise ValueError("governed_pathway_reliance_declaration_required")
    if value.get("status") not in (None, status):
        raise ValueError("governed_pathway_reliance_declaration_mismatch")
    return {"acknowledged": True, "status": status, "boundary": RELIANCE_BOUNDARY}


def _validate_relationship(source_kind: str, target_kind: str, relationship_type: str) -> None:
    expected = RELATIONSHIPS.get(relationship_type)
    if not expected or expected[1] != target_kind or not (expected[0] == source_kind or (expected[0] == "evidence" and source_kind in EVIDENCE_KINDS)):
        raise ValueError("governed_pathway_relationship_direction_invalid")


def _row(row: sqlite3.Row | Mapping[str, Any]) -> dict[str, Any]:
    result = dict(row)
    for field in ("reliance_declaration_json", "qualification_contract_json", "request_payload_json"):
        if field in result:
            result[field.removesuffix("_json")] = json.loads(result.pop(field)) if result[field] else None
    return result


def _status(conn: sqlite3.Connection, link_id: int, base: str) -> str:
    if conn.execute("SELECT 1 FROM record_governed_pathway_supersessions WHERE pathway_link_id=?", (link_id,)).fetchone():
        return "superseded"
    row = conn.execute("SELECT disposition FROM record_governed_pathway_reviews WHERE pathway_link_id=? ORDER BY id DESC LIMIT 1", (link_id,)).fetchone()
    if row:
        return {"accepted_as_represented_pathway": "accepted_as_represented_pathway", "requires_pathway_correction": "requires_pathway_correction", "not_accepted_as_represented_pathway": "not_accepted_as_represented_pathway"}.get(row[0], base)
    return base


def get_pathway_link(conn: sqlite3.Connection, link_id: int | str) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM record_governed_pathway_links WHERE id=?", (int(link_id),)).fetchone()
    if not row:
        raise ValueError("governed_pathway_link_not_found")
    result = _row(row)
    result["status"] = _status(conn, int(link_id), result["status"])
    result["bindings"] = [dict(x) for x in conn.execute("SELECT * FROM record_governed_pathway_bindings WHERE pathway_link_id=? ORDER BY source_type, source_id, binding_role", (int(link_id),)).fetchall()]
    result["reviews"] = [dict(x) for x in conn.execute("SELECT * FROM record_governed_pathway_reviews WHERE pathway_link_id=? ORDER BY id", (int(link_id),)).fetchall()]
    return result


def list_pathway_links(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [get_pathway_link(conn, row["id"]) for row in conn.execute("SELECT id FROM record_governed_pathway_links ORDER BY created_at, id").fetchall()]


def create_pathway_link(conn: sqlite3.Connection, *, source_object_kind: str, source_object_id: Any, target_object_kind: str, target_object_id: Any, relationship_type: str, rationale: str, reliance_status: str, reliance_description: str | None, reliance_declaration: Mapping[str, Any], contestation_status: str, contestation_representation: str | None, limitations: str, bindings: Any, actor: str, actor_role: str, idempotency_key: str | None = None, created_at: str | None = None, document_root: Path | None = None, _commit: bool = True) -> dict[str, Any]:
    _validate_relationship(source_object_kind, target_object_kind, relationship_type)
    source = _endpoint(conn, source_object_kind, source_object_id, document_root=document_root)
    target = _endpoint(conn, target_object_kind, target_object_id, document_root=document_root)
    if source_object_kind == target_object_kind and str(source_object_id) == str(target_object_id):
        raise ValueError("governed_pathway_self_link_invalid")
    reliance = _required(reliance_status, "governed_pathway_reliance_status_required")
    if reliance not in RELIANCE_STATUSES:
        raise ValueError("governed_pathway_reliance_status_invalid")
    if reliance in {"considered", "expressly_relied_upon", "expressly_not_relied_upon", "disputed"} and not _required(reliance_description, "governed_pathway_reliance_description_required"):
        raise ValueError("governed_pathway_reliance_description_required")
    declaration = _declaration(reliance_declaration, reliance)
    contestation = _required(contestation_status, "governed_pathway_contestation_status_required")
    if contestation not in CONTESTATION_STATUSES:
        raise ValueError("governed_pathway_contestation_status_invalid")
    if contestation != "not_represented" and not _required(contestation_representation, "governed_pathway_contestation_representation_required"):
        raise ValueError("governed_pathway_contestation_representation_required")
    normalized = _canonical_bindings(bindings)
    for item in normalized:
        allegations._source_binding(conn, item, document_root=document_root)
    payload = {"source_object_kind": source_object_kind, "source_object_id": str(source_object_id), "target_object_kind": target_object_kind, "target_object_id": str(target_object_id), "relationship_type": relationship_type, "rationale": _required(rationale, "governed_pathway_rationale_required"), "reliance_status": reliance, "reliance_description": reliance_description, "reliance_declaration": declaration, "contestation_status": contestation, "contestation_representation": contestation_representation, "limitations": _required(limitations, "governed_pathway_limitations_required"), "bindings": normalized}
    key = str(idempotency_key or "").strip() or _key("stage72-create:", payload)
    ensure_pathway_tables(conn)
    payload_json = _json(payload)
    existing = conn.execute("SELECT * FROM record_governed_pathway_links WHERE idempotency_key=?", (key,)).fetchone()
    if existing:
        if existing["request_payload_json"] != payload_json:
            raise ValueError("governed_pathway_idempotency_conflict")
        return get_pathway_link(conn, existing["id"])
    try:
        cur = conn.execute("INSERT INTO record_governed_pathway_links (idempotency_key,schema_version,authoring_mode,source_object_kind,source_object_id,target_object_kind,target_object_id,relationship_type,rationale,reliance_status,reliance_description,reliance_declaration_json,contestation_status,contestation_representation,limitations,qualification_contract_json,status,created_by,created_by_role,created_at,request_payload_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (key, SCHEMA_VERSION, AUTHORING_MODE, source_object_kind, str(source_object_id), target_object_kind, str(target_object_id), relationship_type, payload["rationale"], reliance, reliance_description, _json(declaration), contestation, contestation_representation, payload["limitations"], _json({"epistemic_label":"pathway_relationship","not_proof":True,"not_causation":True,"not_completeness":True}), "recorded", _required(actor, "governed_pathway_creator_required"), _required(actor_role, "governed_pathway_creator_role_required"), str(created_at or utc_now()), payload_json))
        link_id = int(cur.lastrowid)
        conn.executemany("INSERT INTO record_governed_pathway_bindings (pathway_link_id,source_type,source_id,binding_role,source_version,source_timestamp) VALUES (?,?,?,?,?,?)", [(link_id, x["source_type"], x["source_id"], x["binding_role"], x["source_version"], x["source_timestamp"]) for x in normalized])
        if _commit:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    return get_pathway_link(conn, link_id)


def review_pathway_link(conn: sqlite3.Connection, *, link_id: int | str, disposition: str, rationale: str, boundary_declaration: Mapping[str, Any], actor: str, actor_role: str, idempotency_key: str | None = None, reviewed_at: str | None = None, _commit: bool = True) -> dict[str, Any]:
    link = get_pathway_link(conn, link_id)
    value = _required(disposition, "governed_pathway_review_disposition_required")
    if value not in REVIEW_DISPOSITIONS:
        raise ValueError("governed_pathway_review_disposition_invalid")
    declaration = _declaration(boundary_declaration, link["reliance_status"])
    payload = {"link_id": int(link_id), "disposition": value, "rationale": _required(rationale, "governed_pathway_review_rationale_required"), "boundary_declaration": declaration}
    key = str(idempotency_key or "").strip() or _key("stage72-review:", payload)
    ensure_pathway_tables(conn); payload_json = _json(payload)
    existing = conn.execute("SELECT * FROM record_governed_pathway_reviews WHERE idempotency_key=?", (key,)).fetchone()
    if existing:
        if existing["request_payload_json"] != payload_json: raise ValueError("governed_pathway_review_idempotency_conflict")
        return get_pathway_link(conn, link_id)
    if conn.execute("SELECT 1 FROM record_governed_pathway_supersessions WHERE pathway_link_id=?", (int(link_id),)).fetchone():
        raise ValueError("governed_pathway_link_terminal")
    conn.execute("INSERT INTO record_governed_pathway_reviews (pathway_link_id,disposition,reviewed_by,reviewed_by_role,rationale,boundary_declaration_json,is_self_review,reviewed_at,idempotency_key,request_payload_json) VALUES (?,?,?,?,?,?,?,?,?,?)", (int(link_id), value, _required(actor, "governed_pathway_reviewer_required"), _required(actor_role, "governed_pathway_reviewer_role_required"), payload["rationale"], _json(declaration), int(str(actor) == str(link["created_by"])), str(reviewed_at or utc_now()), key, payload_json))
    if _commit: conn.commit()
    return get_pathway_link(conn, link_id)


def supersede_pathway_link(conn: sqlite3.Connection, *, link_id: int | str, replacement_link_id: int | str, rationale: str, actor: str, actor_role: str, idempotency_key: str | None = None, occurred_at: str | None = None, _commit: bool = True) -> dict[str, Any]:
    link = get_pathway_link(conn, link_id); replacement = get_pathway_link(conn, replacement_link_id)
    if int(link_id) == int(replacement_link_id): raise ValueError("governed_pathway_self_supersession_invalid")
    if (link["source_object_kind"], link["source_object_id"], link["target_object_kind"], link["target_object_id"]) != (replacement["source_object_kind"], replacement["source_object_id"], replacement["target_object_kind"], replacement["target_object_id"]):
        raise ValueError("governed_pathway_supersession_endpoint_mismatch")
    payload = {"link_id": int(link_id), "replacement_link_id": int(replacement_link_id), "rationale": _required(rationale, "governed_pathway_supersession_rationale_required")}
    key = str(idempotency_key or "").strip() or _key("stage72-supersede:", payload); ensure_pathway_tables(conn); payload_json = _json(payload)
    existing = conn.execute("SELECT * FROM record_governed_pathway_supersessions WHERE idempotency_key=?", (key,)).fetchone()
    if existing:
        if existing["request_payload_json"] != payload_json: raise ValueError("governed_pathway_supersession_idempotency_conflict")
        return get_pathway_link(conn, link_id)
    if conn.execute("SELECT 1 FROM record_governed_pathway_supersessions WHERE pathway_link_id=?", (int(link_id),)).fetchone(): raise ValueError("governed_pathway_already_superseded")
    cursor = int(replacement_link_id)
    visited: set[int] = set()
    while cursor not in visited:
        visited.add(cursor)
        row = conn.execute("SELECT replacement_link_id FROM record_governed_pathway_supersessions WHERE pathway_link_id=?", (cursor,)).fetchone()
        if not row:
            break
        cursor = int(row[0])
        if cursor == int(link_id):
            raise ValueError("governed_pathway_supersession_cycle")
    conn.execute("INSERT INTO record_governed_pathway_supersessions (pathway_link_id,replacement_link_id,rationale,actor,actor_role,occurred_at,idempotency_key,request_payload_json) VALUES (?,?,?,?,?,?,?,?)", (int(link_id), int(replacement_link_id), payload["rationale"], _required(actor, "governed_pathway_actor_required"), _required(actor_role, "governed_pathway_actor_role_required"), str(occurred_at or utc_now()), key, payload_json))
    if _commit: conn.commit()
    return get_pathway_link(conn, link_id)


def read_pathway_diagnostic(*, db_path: str | Path, link_id: int | str | None = None, object_kind: str | None = None, object_id: str | None = None) -> dict[str, Any]:
    try:
        conn = sqlite3.connect(f"file:{Path(db_path).resolve()}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
    except (sqlite3.Error, OSError):
        return {"status": "database_unavailable", "links": [], "pathway_table_present": False}
    try:
        if not _table_exists(conn, "record_governed_pathway_links"):
            return {"status": "ok", "links": [], "pathway_table_present": False}
        if link_id is not None:
            try: links = [get_pathway_link(conn, link_id)]
            except ValueError: return {"status": "pathway_link_not_found", "links": [], "pathway_table_present": True}
        else:
            links = list_pathway_links(conn)
            if object_kind and object_id is not None:
                links = [x for x in links if (x["source_object_kind"] == object_kind and x["source_object_id"] == str(object_id)) or (x["target_object_kind"] == object_kind and x["target_object_id"] == str(object_id))]
        return {"status": "ok", "links": links, "pathway_table_present": True, "counts_by_relationship": {x: sum(1 for item in links if item["relationship_type"] == x) for x in sorted({item["relationship_type"] for item in links})}}
    finally:
        conn.close()


def chronological_links(*, db_path: str | Path, object_kind: str | None = None, object_id: str | None = None) -> list[dict[str, Any]]:
    diagnostic = read_pathway_diagnostic(db_path=db_path, object_kind=object_kind, object_id=object_id)
    links = diagnostic.get("links", [])
    return sorted(links, key=lambda x: (str(x.get("created_at") or ""), int(x.get("id") or 0)))


def read_candidates(*, db_path: str | Path, query: str | None = None) -> list[dict[str, Any]]:
    result = []
    try:
        conn = sqlite3.connect(f"file:{Path(db_path).resolve()}?mode=ro", uri=True); conn.row_factory = sqlite3.Row
    except (sqlite3.Error, OSError): return result
    try:
        for kind, (table, column) in OBJECT_TABLES.items():
            if not _table_exists(conn, table): continue
            rows = conn.execute(f"SELECT * FROM {table} ORDER BY {column} DESC LIMIT 100").fetchall()
            for row in rows:
                data = dict(row); ident = str(data.get(column)); label = str(data.get("title_label") or data.get("proposition") or data.get("allegation_text") or data.get("event_description") or data.get("reference") or ident); text = f"{kind} {ident} {label} {data.get('status','recorded')}"
                if not query or query.casefold() in text.casefold(): result.append({"object_kind": kind, "object_id": ident, "label": label, "status": str(data.get("status") or "recorded")})
    finally: conn.close()
    return sorted(result, key=lambda x: (x["object_kind"], x["object_id"]))[:500]


def project_canonical_relationships(*, db_path: str | Path, object_kind: str | None = None, object_id: str | None = None) -> list[dict[str, Any]]:
    """Project existing owned relationships without writing or duplicating them."""
    try:
        conn = sqlite3.connect(f"file:{Path(db_path).resolve()}?mode=ro", uri=True); conn.row_factory = sqlite3.Row
    except (sqlite3.Error, OSError): return []
    result: list[dict[str, Any]] = []
    def add(source_kind: str, source_id: Any, target_kind: str, target_id: Any, relationship: str, basis: str) -> None:
        if object_kind and object_id is not None and not ((source_kind == object_kind and str(source_id) == str(object_id)) or (target_kind == object_kind and str(target_id) == str(object_id))): return
        result.append({"source_object_kind": source_kind, "source_object_id": str(source_id), "target_object_kind": target_kind, "target_object_id": str(target_id), "relationship_type": relationship, "provenance": "canonical_existing_relationship", "basis": basis, "status": "recorded"})
    try:
        specs = [("record_governed_response_allegation_links", "response_id", "allegation_id", "governed_allegation", "governed_response", "allegation_to_response"), ("record_governed_challenge_determination_links", "challenge_id", "determination_id", "governed_determination", "governed_challenge", "determination_to_challenge"), ("record_governed_remedy_determination_links", "remedy_id", "determination_id", "governed_determination", "governed_remedy", "determination_to_remedy"), ("record_governed_implementation_event_remedy_links", "event_id", "remedy_id", "governed_remedy", "governed_implementation_event", "remedy_to_implementation")]
        for table, source_col, target_col, source_kind, target_kind, relationship in specs:
            if _table_exists(conn, table):
                for row in conn.execute(f"SELECT {source_col},{target_col} FROM {table} ORDER BY id").fetchall(): add(source_kind, row[1], target_kind, row[0], relationship, table)
        if _table_exists(conn, "record_governed_determination_authority_links"):
            for row in conn.execute("SELECT authority_id,mandate_id,determination_id FROM record_governed_determination_authority_links ORDER BY id").fetchall():
                add("decision_authority", row[0], "governed_determination", row[2], "authority_to_determination", "record_governed_determination_authority_links"); add("decision_mandate", row[1], "governed_determination", row[2], "mandate_to_determination", "record_governed_determination_authority_links")
        if _table_exists(conn, "record_governed_determination_governed_object_links"):
            for row in conn.execute("SELECT object_type,object_id,determination_id FROM record_governed_determination_governed_object_links ORDER BY id").fetchall():
                mapping = {"accepted_pattern_observation": "observation_to_determination", "governed_inference": "inference_to_determination", "governed_allegation": "allegation_to_determination", "governed_response": "response_to_determination"}
                if row[0] in mapping: add(row[0], row[1], "governed_determination", row[2], mapping[row[0]], "record_governed_determination_governed_object_links")
        return sorted(result, key=lambda x: (x["source_object_kind"], x["source_object_id"], x["target_object_kind"], x["target_object_id"], x["relationship_type"]))
    finally: conn.close()
