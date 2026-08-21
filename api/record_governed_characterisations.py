"""Stage 74 governed terminology representations.

This module records deliberate human uses of controlled terminology. A record
preserves a representation and its provenance; it is never a finding, proof,
legal classification, or determination.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Mapping

SCHEMA_VERSION = "stage74.governed_terminology_representation.v1"
VOCABULARY_VERSION = "1.0"
AUTHORING_MODE = "human_recorded"

TERMS = {
    "victimisation": ("Victimisation", "A represented term describing alleged adverse treatment after a relevant act or participation.", "Use only when the wording or source supports the represented term; do not infer motive or legal applicability.", "Meaning may vary by jurisdiction; selection is not a finding."),
    "retaliation": ("Retaliation", "A represented term describing alleged adverse response to a relevant act, report or participation.", "Preserve the attributed wording and temporal context without inferring causation.", "Meaning may vary by jurisdiction; selection is not a finding."),
    "harassment": ("Harassment", "A represented term used to characterise reported conduct or communications.", "Retain the represented context and contrary material.", "Meaning may vary by jurisdiction; selection is not a finding."),
    "intimidation": ("Intimidation", "A represented term used to characterise reported conduct or communications.", "Do not infer intent or effect beyond the represented record.", "Meaning may vary by jurisdiction; selection is not a finding."),
    "coercion": ("Coercion", "A represented term used to characterise reported pressure, conduct or circumstances.", "Preserve the source wording, context and limitations.", "Meaning may vary by jurisdiction; selection is not a finding."),
    "control": ("Control", "A represented term used to describe an asserted pattern or condition.", "Control may be legitimate; do not infer coercion or wrongdoing.", "Meaning is context-dependent; selection is not a finding."),
    "procedural_obstruction": ("Procedural obstruction", "A represented term used to describe an asserted procedural condition or conduct.", "Preserve the procedural context and any contrary response.", "Selection does not establish obstruction or legal effect."),
    "reframing": ("Reframing", "A represented term describing a changed representation of an issue, event or account.", "Preserve both the earlier and later wording where available.", "Do not infer intent, manipulation or deception."),
    "institutional_silence": ("Institutional silence", "A represented term describing an asserted absence or lack of response in a defined context.", "Record the relevant expected response and time context where represented.", "Absence does not automatically mean agreement, refusal, knowledge, concealment or wrongdoing."),
    "repeated_contact_without_resolution": ("Repeated contact without resolution", "A represented term describing repeated contact and an asserted unresolved position.", "Preserve contact sequence and the represented resolution status.", "Repetition is not corroboration, proof or unreasonable conduct."),
}

REPRESENTATION_MODES = {"verbatim", "faithful_paraphrase"}
ATTRIBUTION_KINDS = {"identified_person", "identified_institution", "governed_source", "external_source_as_represented"}
EPISTEMIC_BASIS = {"attributed_source_language", "complaint_or_submission_terminology", "proposed_human_characterisation", "disputed_terminology", "terminology_considered_during_administrative_review"}
REFERENCE_ROLES = {"contextual_object", "attributed_representation", "response_or_contestation", "contrary_material", "procedural_history", "authority_or_mandate_context", "separately_governed_determination", "later_review_or_supersession_context"}
REFERENCE_ROLE_OBJECTS: dict[str, set[str]] = {}
BINDING_ROLES = {"supporting_source", "contextual_source", "attribution_source", "response_source", "contrary_source"}
SOURCE_TYPES = {"published_document", "canonical_record", "record_document_association", "accepted_pattern_observation"}
LIFECYCLE = {"recorded_as_represented", "proposed_as_characterisation", "disputed", "reviewed_as_qualified_representation", "rejected_as_representation", "unresolved", "withdrawn", "superseded"}
REVIEW_OUTCOMES = {"reviewed_as_qualified_representation", "rejected_as_representation", "unresolved"}
TERMINAL = {"withdrawn", "superseded"}
PRIMARY_OBJECTS = {
    "canonical_record": ("records", "reference"),
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
}
REFERENCE_OBJECTS = {**PRIMARY_OBJECTS, "governed_characterisation": ("record_governed_characterisations", "id")}
# Keep procedural references explicit even when a neighbouring stage has not
# initialized one of these tables in the current database.
REFERENCE_ROLE_OBJECTS["contextual_object"] = set(REFERENCE_OBJECTS)
REFERENCE_ROLE_OBJECTS.update({
    "attributed_representation": {"governed_characterisation"},
    "response_or_contestation": {"governed_response", "governed_challenge"},
    "contrary_material": {"governed_response", "governed_challenge", "governed_allegation", "governed_inference"},
    "procedural_history": set(),
    "authority_or_mandate_context": {"decision_authority", "decision_mandate"},
    "separately_governed_determination": {"governed_determination"},
    "later_review_or_supersession_context": {"governed_challenge", "governed_determination", "governed_characterisation"},
})

QUALIFICATION = "A term names the question. Recording terminology preserves a represented use of language; it does not establish fact, proof, corroboration, legal classification, finding, liability, wrongdoing or legal effect."


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


def ensure_characterisation_tables(conn: sqlite3.Connection) -> None:
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS record_governed_characterisations (
      id INTEGER PRIMARY KEY AUTOINCREMENT, idempotency_key TEXT NOT NULL UNIQUE,
      schema_version TEXT NOT NULL, authoring_mode TEXT NOT NULL,
      term_code TEXT NOT NULL, vocabulary_version TEXT NOT NULL,
      representation_mode TEXT NOT NULL, represented_wording TEXT NOT NULL,
      attribution_kind TEXT NOT NULL, attributed_label TEXT, attribution_source_type TEXT,
      attribution_source_id TEXT, external_source_description TEXT,
      epistemic_basis TEXT NOT NULL, rationale TEXT NOT NULL, limitations TEXT NOT NULL,
      jurisdictional_context TEXT, primary_object_kind TEXT NOT NULL, primary_object_id TEXT NOT NULL,
      created_by TEXT NOT NULL, created_by_role TEXT NOT NULL, created_at TEXT NOT NULL,
      lifecycle_status TEXT NOT NULL, request_payload_json TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS record_governed_characterisation_bindings (
      id INTEGER PRIMARY KEY AUTOINCREMENT, characterisation_id INTEGER NOT NULL,
      source_type TEXT NOT NULL, source_id TEXT NOT NULL, binding_role TEXT NOT NULL,
      source_version TEXT, source_timestamp TEXT,
      UNIQUE(characterisation_id, source_type, source_id, binding_role)
    );
    CREATE TABLE IF NOT EXISTS record_governed_characterisation_references (
      id INTEGER PRIMARY KEY AUTOINCREMENT, characterisation_id INTEGER NOT NULL,
      object_kind TEXT NOT NULL, object_id TEXT NOT NULL, relationship_role TEXT NOT NULL,
      UNIQUE(characterisation_id, object_kind, object_id, relationship_role)
    );
    CREATE TABLE IF NOT EXISTS record_governed_characterisation_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT, characterisation_id INTEGER NOT NULL,
      event_type TEXT NOT NULL, resulting_status TEXT NOT NULL, rationale TEXT NOT NULL,
      declaration_json TEXT NOT NULL, actor TEXT NOT NULL, actor_role TEXT NOT NULL,
      occurred_at TEXT NOT NULL, idempotency_key TEXT NOT NULL UNIQUE,
      replacement_id INTEGER, request_payload_json TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_stage74_status ON record_governed_characterisations(lifecycle_status, created_at);
    """)


def vocabulary(term_code: str, vocabulary_version: str = VOCABULARY_VERSION) -> dict[str, str]:
    if vocabulary_version != VOCABULARY_VERSION or term_code not in TERMS:
        raise ValueError("governed_characterisation_term_version_invalid")
    label, description, inclusion, limitation = TERMS[term_code]
    return {"term_code": term_code, "vocabulary_version": vocabulary_version, "display_label": label, "neutral_editorial_description": description, "inclusion_guidance": inclusion, "exclusion_or_limitation_guidance": limitation}


def vocabulary_metadata() -> list[dict[str, str]]:
    return [vocabulary(code) for code in sorted(TERMS)]


def _endpoint(conn: sqlite3.Connection, kind: str, identifier: Any) -> dict[str, Any]:
    if kind not in REFERENCE_OBJECTS:
        raise ValueError("governed_characterisation_primary_object_kind_invalid")
    table, column = REFERENCE_OBJECTS[kind]
    value = _required(identifier, "governed_characterisation_primary_object_id_required")
    if not _table_exists(conn, table):
        raise ValueError("governed_characterisation_primary_object_not_found")
    row = conn.execute(f"SELECT * FROM {table} WHERE {column}=?", (value,)).fetchone()
    if not row:
        raise ValueError("governed_characterisation_primary_object_not_found")
    data = dict(row)
    if str(data.get("status") or "").lower() in {"withdrawn", "superseded", "rejected", "inactive", "ceased"}:
        raise ValueError("governed_characterisation_primary_object_ineligible")
    return {"object_kind": kind, "object_id": value, "label": str(data.get("title") or data.get("reference") or data.get("name") or f"{kind} {value}"), "status": data.get("status") or "recorded"}


def _canonical_bindings(conn: sqlite3.Connection, bindings: Any) -> list[dict[str, Any]]:
    if bindings is None:
        return []
    if not isinstance(bindings, list):
        raise ValueError("governed_characterisation_bindings_invalid")
    result = []
    for item in bindings:
        if not isinstance(item, Mapping) or set(item) - {"source_type", "source_id", "binding_role", "source_version", "source_timestamp"}:
            raise ValueError("governed_characterisation_binding_invalid")
        source_type = _required(item.get("source_type"), "governed_characterisation_source_type_required")
        source_id = _required(item.get("source_id"), "governed_characterisation_source_id_required")
        role = _required(item.get("binding_role"), "governed_characterisation_binding_role_required")
        if source_type not in SOURCE_TYPES or role not in BINDING_ROLES:
            raise ValueError("governed_characterisation_binding_invalid")
        # Binding shape alone is insufficient: the source must exist and be
        # eligible in its canonical owning stage.
        from api import record_governed_allegations as allegations

        try:
            resolved = allegations._source_binding(
                conn,
                {"source_type": source_type, "source_id": source_id,
                 "binding_role": role, "source_version": item.get("source_version"),
                 "source_timestamp": item.get("source_timestamp")},
            )
        except (ValueError, TypeError, OSError):
            raise ValueError("governed_characterisation_source_not_found") from None
        result.append({"source_type": source_type, "source_id": source_id, "binding_role": role, "source_version": resolved.get("source_version"), "source_timestamp": resolved.get("source_timestamp")})
    result.sort(key=lambda x: (x["source_type"], x["source_id"], x["binding_role"]))
    if len({(x["source_type"], x["source_id"], x["binding_role"]) for x in result}) != len(result):
        raise ValueError("governed_characterisation_duplicate_binding")
    return result


def _canonical_references(conn: sqlite3.Connection, references: Any, characterisation_id: str | None = None) -> list[dict[str, str]]:
    if references is None:
        return []
    if not isinstance(references, list):
        raise ValueError("governed_characterisation_references_invalid")
    result = []
    for item in references:
        if not isinstance(item, Mapping) or set(item) != {"object_kind", "object_id", "relationship_role"}:
            raise ValueError("governed_characterisation_reference_invalid")
        kind = _required(item.get("object_kind"), "governed_characterisation_reference_kind_required")
        identifier = _required(item.get("object_id"), "governed_characterisation_reference_id_required")
        role = _required(item.get("relationship_role"), "governed_characterisation_reference_role_required")
        if kind not in REFERENCE_OBJECTS or role not in REFERENCE_ROLES or kind not in REFERENCE_ROLE_OBJECTS[role]:
            raise ValueError("governed_characterisation_reference_invalid")
        _endpoint(conn, kind, identifier)
        if characterisation_id and kind == "governed_characterisation" and identifier == characterisation_id:
            raise ValueError("governed_characterisation_self_reference")
        result.append({"object_kind": kind, "object_id": identifier, "relationship_role": role})
    result.sort(key=lambda x: (x["object_kind"], x["object_id"], x["relationship_role"]))
    if len({(x["object_kind"], x["object_id"], x["relationship_role"]) for x in result}) != len(result):
        raise ValueError("governed_characterisation_duplicate_reference")
    return result


def _attribution(conn: sqlite3.Connection, kind: str, label: Any, source_type: Any, source_id: Any, external_description: Any) -> dict[str, Any]:
    if kind not in ATTRIBUTION_KINDS:
        raise ValueError("governed_characterisation_attribution_kind_invalid")
    label_value = str(label or "").strip() or None
    source_type_value = str(source_type or "").strip() or None
    source_id_value = str(source_id or "").strip() or None
    external_value = str(external_description or "").strip() or None
    if kind in {"identified_person", "identified_institution"}:
        if not label_value:
            raise ValueError("governed_characterisation_attributed_label_required")
        if source_type_value or source_id_value or external_value:
            raise ValueError("governed_characterisation_attribution_fields_not_applicable")
    elif kind == "governed_source":
        if source_type_value not in SOURCE_TYPES or not source_id_value:
            raise ValueError("governed_characterisation_attribution_source_required")
        from api import record_governed_allegations as allegations
        try:
            allegations._source_binding(conn, {"source_type": source_type_value, "source_id": source_id_value})
        except (ValueError, TypeError, OSError):
            raise ValueError("governed_characterisation_attribution_source_not_found") from None
        if label_value or external_value:
            raise ValueError("governed_characterisation_attribution_fields_not_applicable")
    else:
        if not external_value:
            raise ValueError("governed_characterisation_external_source_required")
        if label_value or source_type_value or source_id_value:
            raise ValueError("governed_characterisation_attribution_fields_not_applicable")
    return {"attribution_kind": kind, "attributed_label": label_value, "attribution_source_type": source_type_value, "attribution_source_id": source_id_value, "external_source_description": external_value}


def _row(conn: sqlite3.Connection, identifier: int | str) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM record_governed_characterisations WHERE id=?", (identifier,)).fetchone()
    if not row:
        raise ValueError("governed_characterisation_not_found")
    item = dict(row)
    item["vocabulary"] = vocabulary(item["term_code"], item["vocabulary_version"])
    item["bindings"] = [dict(x) for x in conn.execute("SELECT source_type,source_id,binding_role,source_version,source_timestamp FROM record_governed_characterisation_bindings WHERE characterisation_id=? ORDER BY source_type,source_id,binding_role", (item["id"],))]
    item["references"] = [dict(x) for x in conn.execute("SELECT object_kind,object_id,relationship_role FROM record_governed_characterisation_references WHERE characterisation_id=? ORDER BY object_kind,object_id,relationship_role", (item["id"],))]
    item["history"] = [dict(x) for x in conn.execute("SELECT * FROM record_governed_characterisation_events WHERE characterisation_id=? ORDER BY occurred_at,id", (item["id"],))]
    return item


def get_characterisation(conn: sqlite3.Connection, representation_id: int | str) -> dict[str, Any]:
    return _row(conn, representation_id)


def list_characterisations(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    if not _table_exists(conn, "record_governed_characterisations"):
        return []
    return [_row(conn, row[0]) for row in conn.execute("SELECT id FROM record_governed_characterisations ORDER BY created_at,id")]


def read_candidates(conn: sqlite3.Connection) -> list[dict[str, str]]:
    result = []
    for kind, (table, column) in PRIMARY_OBJECTS.items():
        if not _table_exists(conn, table):
            continue
        for row in conn.execute(f"SELECT * FROM {table} ORDER BY {column}"):
            data = dict(row)
            if str(data.get("status") or "").lower() in {"withdrawn", "superseded", "rejected", "inactive", "ceased"}:
                continue
            identifier = str(data[column])
            result.append({"object_kind": kind, "object_id": identifier, "label": str(data.get("title") or data.get("reference") or data.get("name") or f"{kind} {identifier}"), "status": data.get("status") or "recorded"})
    return result


def create_characterisation(conn: sqlite3.Connection, *, term_code: str, vocabulary_version: str, representation_mode: str, represented_wording: str, attribution_kind: str, attributed_label: str | None, attribution_source_type: str | None, attribution_source_id: str | None, external_source_description: str | None, epistemic_basis: str, rationale: str, limitations: str, jurisdictional_context: str | None, primary_object_kind: str, primary_object_id: str, bindings: Any, references: Any, actor: str, actor_role: str, declaration: Mapping[str, Any], idempotency_key: str, created_at: str | None = None, _commit: bool = True) -> dict[str, Any]:
    ensure_characterisation_tables(conn)
    if vocabulary_version != VOCABULARY_VERSION or term_code not in TERMS:
        raise ValueError("governed_characterisation_term_version_invalid")
    if representation_mode not in REPRESENTATION_MODES:
        raise ValueError("governed_characterisation_representation_mode_invalid")
    wording = _required(represented_wording, "governed_characterisation_wording_required")
    if epistemic_basis not in EPISTEMIC_BASIS:
        raise ValueError("governed_characterisation_epistemic_basis_invalid")
    rationale_value = _required(rationale, "governed_characterisation_rationale_required")
    limitations_value = _required(limitations, "governed_characterisation_limitations_required")
    actor_value = _required(actor, "governed_characterisation_actor_required")
    key = _required(idempotency_key, "governed_characterisation_idempotency_key_required")
    if not isinstance(declaration, Mapping) or set(declaration) != {"acknowledged"} or declaration.get("acknowledged") is not True:
        raise ValueError("governed_characterisation_creation_declaration_required")
    primary = _endpoint(conn, primary_object_kind, primary_object_id)
    attribution = _attribution(conn, attribution_kind, attributed_label, attribution_source_type, attribution_source_id, external_source_description)
    canonical_bindings = _canonical_bindings(conn, bindings)
    canonical_references = _canonical_references(conn, references)
    actor_role_value = _required(actor_role, "governed_characterisation_actor_role_required")
    payload = {"term_code": term_code, "vocabulary_version": vocabulary_version, "representation_mode": representation_mode, "represented_wording": wording, **attribution, "epistemic_basis": epistemic_basis, "rationale": rationale_value, "limitations": limitations_value, "jurisdictional_context": str(jurisdictional_context or "").strip() or None, "primary_object_kind": primary["object_kind"], "primary_object_id": primary["object_id"], "bindings": canonical_bindings, "references": canonical_references, "actor": actor_value, "actor_role": actor_role_value, "declaration": dict(declaration)}
    existing = conn.execute("SELECT id,request_payload_json FROM record_governed_characterisations WHERE idempotency_key=?", (key,)).fetchone()
    if existing:
        if json.loads(existing[1]) != payload:
            raise ValueError("governed_characterisation_idempotency_conflict")
        return _row(conn, existing[0])
    now = created_at or utc_now()
    conn.execute("SAVEPOINT stage74_create")
    try:
        conn.execute("INSERT INTO record_governed_characterisations (idempotency_key,schema_version,authoring_mode,term_code,vocabulary_version,representation_mode,represented_wording,attribution_kind,attributed_label,attribution_source_type,attribution_source_id,external_source_description,epistemic_basis,rationale,limitations,jurisdictional_context,primary_object_kind,primary_object_id,created_by,created_by_role,created_at,lifecycle_status,request_payload_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (key, SCHEMA_VERSION, AUTHORING_MODE, term_code, vocabulary_version, representation_mode, wording, attribution["attribution_kind"], attribution["attributed_label"], attribution["attribution_source_type"], attribution["attribution_source_id"], attribution["external_source_description"], epistemic_basis, rationale_value, limitations_value, payload["jurisdictional_context"], primary["object_kind"], primary["object_id"], actor_value, actor_role_value, now, "recorded_as_represented", _json(payload)))
        identifier = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        for binding in canonical_bindings:
            conn.execute("INSERT INTO record_governed_characterisation_bindings (characterisation_id,source_type,source_id,binding_role,source_version,source_timestamp) VALUES (?,?,?,?,?,?)", (identifier, binding["source_type"], binding["source_id"], binding["binding_role"], binding["source_version"], binding["source_timestamp"]))
        for reference in canonical_references:
            conn.execute("INSERT INTO record_governed_characterisation_references (characterisation_id,object_kind,object_id,relationship_role) VALUES (?,?,?,?)", (identifier, reference["object_kind"], reference["object_id"], reference["relationship_role"]))
        conn.execute("INSERT INTO record_governed_characterisation_events (characterisation_id,event_type,resulting_status,rationale,declaration_json,actor,actor_role,occurred_at,idempotency_key,replacement_id,request_payload_json) VALUES (?,?,?,?,?,?,?,?,?,?,?)", (identifier, "created", "recorded_as_represented", rationale_value, _json(declaration), actor_value, actor_role_value, now, key + ":created", None, _json(payload)))
        conn.execute("RELEASE SAVEPOINT stage74_create")
        if _commit: conn.commit()
    except Exception:
        conn.execute("ROLLBACK TO SAVEPOINT stage74_create")
        conn.execute("RELEASE SAVEPOINT stage74_create")
        raise
    return _row(conn, identifier)


def _event(conn: sqlite3.Connection, *, identifier: int | str, event_type: str, resulting_status: str, rationale: str, declaration: Mapping[str, Any], actor: str, actor_role: str, idempotency_key: str, replacement_id: int | None = None, _commit: bool = True) -> dict[str, Any]:
    item = _row(conn, identifier)
    rationale_value = _required(rationale, "governed_characterisation_event_rationale_required")
    actor_value = _required(actor, "governed_characterisation_event_actor_required")
    actor_role_value = _required(actor_role, "governed_characterisation_event_actor_role_required")
    if not isinstance(declaration, Mapping) or set(declaration) != {"acknowledged"} or declaration.get("acknowledged") is not True:
        raise ValueError("governed_characterisation_event_declaration_required")
    key = _required(idempotency_key, "governed_characterisation_event_idempotency_key_required")
    payload = {"characterisation_id": int(identifier), "event_type": event_type, "resulting_status": resulting_status, "rationale": rationale_value, "actor": actor_value, "actor_role": actor_role_value, "declaration": dict(declaration), "replacement_id": replacement_id}
    existing = conn.execute("SELECT characterisation_id,request_payload_json FROM record_governed_characterisation_events WHERE idempotency_key=?", (key,)).fetchone()
    if existing:
        if json.loads(existing[1]) != payload:
            raise ValueError("governed_characterisation_idempotency_conflict")
        return _row(conn, existing[0])
    if item["lifecycle_status"] in TERMINAL:
        raise ValueError("governed_characterisation_terminal_state")
    allowed = {
        "recorded_as_represented": {"proposed", "disputed", "withdrawn", "superseded"},
        "proposed_as_characterisation": {"disputed", "review", "withdrawn", "superseded"},
        "disputed": {"review", "withdrawn", "superseded"},
        "reviewed_as_qualified_representation": {"disputed", "withdrawn", "superseded"},
        "rejected_as_representation": {"disputed", "withdrawn", "superseded"},
        "unresolved": {"disputed", "withdrawn", "superseded"},
    }
    if event_type not in allowed.get(item["lifecycle_status"], set()):
        raise ValueError("governed_characterisation_transition_invalid")
    if event_type == "review" and actor_value == item["created_by"]:
        raise ValueError("governed_characterisation_reviewer_must_differ")
    now = utc_now()
    conn.execute("SAVEPOINT stage74_event")
    try:
        conn.execute("INSERT INTO record_governed_characterisation_events (characterisation_id,event_type,resulting_status,rationale,declaration_json,actor,actor_role,occurred_at,idempotency_key,replacement_id,request_payload_json) VALUES (?,?,?,?,?,?,?,?,?,?,?)", (int(identifier), event_type, resulting_status, rationale_value, _json(declaration), actor_value, actor_role_value, now, key, replacement_id, _json(payload)))
        conn.execute("UPDATE record_governed_characterisations SET lifecycle_status=? WHERE id=?", (resulting_status, int(identifier)))
        conn.execute("RELEASE SAVEPOINT stage74_event")
        if _commit: conn.commit()
    except Exception:
        conn.execute("ROLLBACK TO SAVEPOINT stage74_event")
        conn.execute("RELEASE SAVEPOINT stage74_event")
        raise
    return _row(conn, identifier)


def propose_characterisation(conn: sqlite3.Connection, **kwargs: Any) -> dict[str, Any]:
    return _event(conn, resulting_status="proposed_as_characterisation", event_type="proposed", **kwargs)


def dispute_characterisation(conn: sqlite3.Connection, **kwargs: Any) -> dict[str, Any]:
    return _event(conn, resulting_status="disputed", event_type="disputed", **kwargs)


def review_characterisation(conn: sqlite3.Connection, *, outcome: str, **kwargs: Any) -> dict[str, Any]:
    if outcome not in REVIEW_OUTCOMES:
        raise ValueError("governed_characterisation_review_outcome_invalid")
    return _event(conn, resulting_status=outcome, event_type="review", **kwargs)


def withdraw_characterisation(conn: sqlite3.Connection, **kwargs: Any) -> dict[str, Any]:
    return _event(conn, resulting_status="withdrawn", event_type="withdrawn", **kwargs)


def supersede_characterisation(conn: sqlite3.Connection, *, replacement_id: int | str, **kwargs: Any) -> dict[str, Any]:
    item = _row(conn, kwargs["identifier"])
    replacement = _row(conn, replacement_id)
    if int(item["id"]) == int(replacement["id"]):
        raise ValueError("governed_characterisation_self_supersession")
    if item["term_code"] != replacement["term_code"] or item["vocabulary_version"] != replacement["vocabulary_version"]:
        raise ValueError("governed_characterisation_supersession_term_mismatch")
    if (item["primary_object_kind"], item["primary_object_id"]) != (replacement["primary_object_kind"], replacement["primary_object_id"]):
        raise ValueError("governed_characterisation_supersession_primary_object_mismatch")
    if replacement["lifecycle_status"] in TERMINAL:
        raise ValueError("governed_characterisation_replacement_terminal")
    cursor = replacement
    seen = {int(item["id"])}
    while cursor["lifecycle_status"] == "superseded":
        next_ids = [x.get("replacement_id") for x in cursor["history"] if x.get("event_type") == "superseded" and x.get("replacement_id")]
        if not next_ids or int(next_ids[-1]) in seen:
            raise ValueError("governed_characterisation_supersession_cycle")
        seen.add(int(next_ids[-1])); cursor = _row(conn, next_ids[-1])
    return _event(conn, resulting_status="superseded", event_type="superseded", replacement_id=int(replacement_id), **kwargs)


def read_diagnostic(conn: sqlite3.Connection) -> dict[str, Any]:
    present = _table_exists(conn, "record_governed_characterisations")
    return {"characterisation_table_present": present, "count": conn.execute("SELECT COUNT(*) FROM record_governed_characterisations").fetchone()[0] if present else 0, "vocabulary_version": VOCABULARY_VERSION, "lifecycle_statuses": sorted(LIFECYCLE)}
