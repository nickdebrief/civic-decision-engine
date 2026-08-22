"""Stage 75 governed internal report specifications and artifacts.

The CDE owns selection, qualification and lifecycle.  The Publication Engine
receives only a frozen, digest-verified specification and never reads CDE data.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from api import record_document_associations as rda

SCHEMA_VERSION = "stage75.governed_report.v1"
SPECIFICATION_SCHEMA_VERSION = "stage75.report_specification.v1"
PUBLICATION_ENGINE_VERSION = "2.0.0"
REPORT_TYPES = {"canonical_record_report"}
DISTRIBUTION_CLASSES = {"internal_working", "restricted_review"}
OUTPUT_FORMATS = {"docx", "html", "pdf"}
CONTENT_TYPES = {"verbatim_source", "faithful_paraphrase", "administrative_summary", "qualification", "limitation", "redaction_notice"}
LIFECYCLE = {"draft_specification", "assembly_reviewed", "privacy_reviewed", "redaction_reviewed", "approved_for_generation", "generation_requested", "generated", "validation_failed", "withdrawn", "superseded"}
TERMINAL = {"withdrawn", "superseded"}
REPORT_ROOT = Path(os.getenv("CDE_REPORT_ARTIFACT_ROOT", "/tmp/cde-governed-reports"))
MAX_REPORT_TEXT = 1_000_000
MAX_SECTIONS = 50
MAX_BLOCKS = 500
MAX_SELECTED_OBJECTS = 100

BOUNDARY = "A REPORT PRESENTS THE RECORD—IT DOES NOT REPLACE IT. Inclusion is not endorsement. Exclusion is not proof of absence. A summary is not original language. Printing is not publication. Publication Engine validation is not legal validation."


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def specification_digest(specification: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(specification).encode("utf-8")).hexdigest()


def _required(value: Any, error: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise ValueError(error)
    return result


def _unique_values(values: Any, error: str) -> list[str]:
    if values is None:
        return []
    if isinstance(values, (str, bytes)) or not isinstance(values, (list, tuple)):
        raise ValueError(error)
    result = [str(value).strip() for value in values]
    if any(not value for value in result) or len(result) != len(set(result)):
        raise ValueError(error)
    return result


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def ensure_report_tables(conn: sqlite3.Connection) -> None:
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS record_governed_reports (
      id INTEGER PRIMARY KEY AUTOINCREMENT, idempotency_key TEXT NOT NULL UNIQUE,
      schema_version TEXT NOT NULL, report_type TEXT NOT NULL, title TEXT NOT NULL,
      purpose TEXT NOT NULL, intended_audience TEXT NOT NULL, distribution_class TEXT NOT NULL,
      created_by TEXT NOT NULL, created_by_role TEXT NOT NULL, created_at TEXT NOT NULL,
      lifecycle_status TEXT NOT NULL, request_payload_json TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS record_governed_report_versions (
      id INTEGER PRIMARY KEY AUTOINCREMENT, report_id INTEGER NOT NULL,
      version_number INTEGER NOT NULL, canonical_record_reference TEXT NOT NULL,
      specification_schema_version TEXT NOT NULL, specification_json TEXT NOT NULL,
      specification_digest TEXT NOT NULL, requested_formats_json TEXT NOT NULL,
      publication_engine_version TEXT NOT NULL, rendering_profile TEXT NOT NULL,
      template_version TEXT NOT NULL, created_by TEXT NOT NULL, created_at TEXT NOT NULL,
      lifecycle_status TEXT NOT NULL, UNIQUE(report_id, version_number),
      FOREIGN KEY(report_id) REFERENCES record_governed_reports(id)
    );
    CREATE TABLE IF NOT EXISTS record_governed_report_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT, report_id INTEGER NOT NULL, version_id INTEGER,
      event_type TEXT NOT NULL, resulting_status TEXT NOT NULL, rationale TEXT NOT NULL,
      actor TEXT NOT NULL, actor_role TEXT NOT NULL, declaration_json TEXT NOT NULL,
      occurred_at TEXT NOT NULL, idempotency_key TEXT NOT NULL UNIQUE,
      request_payload_json TEXT NOT NULL, FOREIGN KEY(report_id) REFERENCES record_governed_reports(id)
    );
    CREATE TABLE IF NOT EXISTS record_governed_report_generation_attempts (
      id INTEGER PRIMARY KEY AUTOINCREMENT, version_id INTEGER NOT NULL,
      requested_formats_json TEXT NOT NULL, actor TEXT NOT NULL, actor_role TEXT NOT NULL,
      requested_at TEXT NOT NULL, result TEXT NOT NULL, diagnostics_json TEXT NOT NULL,
      request_payload_json TEXT NOT NULL,
      idempotency_key TEXT NOT NULL UNIQUE, FOREIGN KEY(version_id) REFERENCES record_governed_report_versions(id)
    );
    CREATE TABLE IF NOT EXISTS record_governed_report_artifacts (
      id INTEGER PRIMARY KEY AUTOINCREMENT, version_id INTEGER NOT NULL, format TEXT NOT NULL,
      storage_reference TEXT NOT NULL, sha256 TEXT NOT NULL, size_bytes INTEGER NOT NULL,
      renderer_version TEXT NOT NULL, template_version TEXT NOT NULL, generated_at TEXT NOT NULL,
      validation_state TEXT NOT NULL, diagnostics_json TEXT NOT NULL, lifecycle_status TEXT NOT NULL,
      FOREIGN KEY(version_id) REFERENCES record_governed_report_versions(id), UNIQUE(version_id, format)
    );
    CREATE INDEX IF NOT EXISTS idx_stage75_report_status ON record_governed_reports(lifecycle_status, created_at);
    CREATE INDEX IF NOT EXISTS idx_stage75_version_report ON record_governed_report_versions(report_id, version_number);
    """)


def _record_snapshot(conn: sqlite3.Connection, reference: str) -> dict[str, Any]:
    value = rda.record_context(conn, reference)
    if not value:
        raise ValueError("governed_report_canonical_record_not_found")
    if str(value.get("status") or "").lower() in {"withdrawn", "superseded", "inactive"}:
        raise ValueError("governed_report_canonical_record_ineligible")
    return {"reference": str(reference), "title": str(value.get("title") or value.get("record_title") or reference), "description": str(value.get("finding") or value.get("description") or ""), "version": value.get("version"), "status": value.get("status") or "recorded"}


def _document_snapshot(document_id: str, *, root: Path | None = None) -> dict[str, Any]:
    value = rda.published_document_context(document_id, root=root)
    if not value or value.get("status") != "published":
        raise ValueError("governed_report_published_document_ineligible")
    digest = value.get("sha256_hash") or value.get("sha256") or value.get("hash")
    if not digest:
        raise ValueError("governed_report_published_document_digest_required")
    return {"document_id": str(document_id), "title": str(value.get("title") or value.get("document_identifier") or document_id), "status": value.get("status"), "sha256": digest, "document_identifier": value.get("document_identifier")}


def _association_snapshot(conn: sqlite3.Connection, association_id: Any, *, root: Path | None = None) -> dict[str, Any]:
    try:
        value = rda.get_association(conn, int(association_id))
    except (ValueError, TypeError, sqlite3.Error):
        raise ValueError("governed_report_association_not_found") from None
    if not value.get("is_active"):
        raise ValueError("governed_report_association_ineligible")
    document = _document_snapshot(str(value.get("document_id") or ""), root=root)
    return {"association_id": int(value["id"]), "record_reference": str(value.get("record_reference") or ""), "document_id": document["document_id"], "relationship_type": str(value.get("relationship_type") or ""), "document_sha256": document.get("sha256")}


def _blocks(blocks: Any, *, record: Mapping[str, Any], documents: list[Mapping[str, Any]], associations: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if blocks is None:
        blocks = [{"content_type": "verbatim_source", "text": record.get("description", ""), "source_identity": {"object_kind": "canonical_record", "object_id": record["reference"]}, "inclusion_rationale": "Primary record description deliberately selected for the report."}]
    if not isinstance(blocks, list) or not blocks:
        raise ValueError("governed_report_sections_required")
    result = []
    for index, block in enumerate(blocks):
        if not isinstance(block, Mapping) or set(block) - {"content_type", "text", "source_identity", "attribution", "inclusion_rationale"}:
            raise ValueError("governed_report_block_invalid")
        content_type = _required(block.get("content_type"), "governed_report_content_type_required")
        if content_type not in CONTENT_TYPES:
            raise ValueError("governed_report_content_type_invalid")
        text = _required(block.get("text"), "governed_report_block_text_required")
        if len(text) > MAX_REPORT_TEXT:
            raise ValueError("governed_report_block_too_large")
        rationale = _required(block.get("inclusion_rationale"), "governed_report_inclusion_rationale_required")
        source = block.get("source_identity")
        if not isinstance(source, Mapping) or set(source) != {"object_kind", "object_id"}:
            raise ValueError("governed_report_block_source_invalid")
        source_kind = _required(source.get("object_kind"), "governed_report_block_source_invalid")
        source_id = _required(source.get("object_id"), "governed_report_block_source_invalid")
        allowed_sources = {("canonical_record", record["reference"])}
        allowed_sources.update(("published_document", str(item["document_id"])) for item in documents)
        allowed_sources.update(("record_document_association", str(item["association_id"])) for item in associations)
        if (source_kind, source_id) not in allowed_sources:
            raise ValueError("governed_report_block_source_mismatch")
        result.append({"order": index, "content_type": content_type, "text": text, "source_identity": {"object_kind": source_kind, "object_id": source_id}, "attribution": str(block.get("attribution") or ""), "inclusion_rationale": rationale})
    return result


def _canonical_specification(*, record: Mapping[str, Any], documents: list[Mapping[str, Any]], associations: list[Mapping[str, Any]], sections: Any, exclusions: Any, title: str, purpose: str, audience: str, distribution_class: str, requested_formats: Any, rendering_profile: str, template_version: str) -> dict[str, Any]:
    if distribution_class not in DISTRIBUTION_CLASSES:
        raise ValueError("governed_report_distribution_class_invalid")
    if not isinstance(requested_formats, (list, tuple)):
        raise ValueError("governed_report_output_formats_invalid")
    formats = list(requested_formats)
    if any(not isinstance(item, str) or item not in OUTPUT_FORMATS for item in formats):
        raise ValueError("governed_report_output_formats_invalid")
    if not formats or len(formats) != len(set(formats)):
        raise ValueError("governed_report_output_formats_invalid")
    if "pdf" in formats and not {"docx", "html"}.issubset(formats):
        raise ValueError("governed_report_pdf_companion_formats_required")
    formats = sorted(formats)
    if not isinstance(sections, list) or not sections or len(sections) > MAX_SECTIONS:
        raise ValueError("governed_report_sections_required")
    normalized_sections = []
    block_count = 0
    for index, section in enumerate(sections):
        if not isinstance(section, Mapping) or set(section) - {"title", "blocks"}:
            raise ValueError("governed_report_section_invalid")
        normalized_sections.append({"order": index, "title": _required(section.get("title"), "governed_report_section_title_required"), "blocks": _blocks(section.get("blocks"), record=record, documents=documents, associations=associations)})
        block_count += len(normalized_sections[-1]["blocks"])
    if block_count > MAX_BLOCKS:
        raise ValueError("governed_report_blocks_too_many")
    normalized_exclusions = []
    for item in exclusions or []:
        if not isinstance(item, Mapping) or set(item) != {"object_kind", "object_id", "rationale"}:
            raise ValueError("governed_report_exclusion_invalid")
        normalized_exclusions.append({"object_kind": _required(item.get("object_kind"), "governed_report_exclusion_kind_required"), "object_id": _required(item.get("object_id"), "governed_report_exclusion_id_required"), "rationale": _required(item.get("rationale"), "governed_report_exclusion_rationale_required")})
    if len(normalized_exclusions) != len({(item["object_kind"], item["object_id"]) for item in normalized_exclusions}):
        raise ValueError("governed_report_exclusions_duplicate")
    return {"specification_schema_version": SPECIFICATION_SCHEMA_VERSION, "report_type": "canonical_record_report", "title": _required(title, "governed_report_title_required"), "purpose": _required(purpose, "governed_report_purpose_required"), "intended_audience": _required(audience, "governed_report_audience_required"), "distribution_class": distribution_class, "primary_record": dict(record), "selected_documents": sorted(documents, key=lambda x: str(x["document_id"])), "selected_associations": sorted(associations, key=lambda x: int(x["association_id"])), "sections": normalized_sections, "exclusions": sorted(normalized_exclusions, key=lambda x: (x["object_kind"], x["object_id"])), "qualifications": [BOUNDARY, "THE RECORD MUST PRESERVE THE ORIGINAL LANGUAGE."], "requested_formats": formats, "publication_engine_version": PUBLICATION_ENGINE_VERSION, "rendering_profile": _required(rendering_profile, "governed_report_rendering_profile_required"), "template_version": _required(template_version, "governed_report_template_version_required")}


def _row(conn: sqlite3.Connection, report_id: int | str) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM record_governed_reports WHERE id=?", (int(report_id),)).fetchone()
    if row is None:
        raise ValueError("governed_report_not_found")
    result = dict(row)
    result["request_payload"] = json.loads(result.pop("request_payload_json"))
    result["versions"] = []
    for version in conn.execute("SELECT * FROM record_governed_report_versions WHERE report_id=? ORDER BY version_number", (int(report_id),)).fetchall():
        item = dict(version); item["specification"] = json.loads(item.pop("specification_json")); item["requested_formats"] = json.loads(item.pop("requested_formats_json")); result["versions"].append(item)
    result["events"] = [dict(item) for item in conn.execute("SELECT * FROM record_governed_report_events WHERE report_id=? ORDER BY occurred_at,id", (int(report_id),)).fetchall()]
    result["artifacts"] = []
    for version in result["versions"]:
        result["artifacts"].extend(dict(item) for item in conn.execute("SELECT * FROM record_governed_report_artifacts WHERE version_id=? ORDER BY id", (version["id"],)).fetchall())
    return result


def get_report(conn: sqlite3.Connection, report_id: int | str) -> dict[str, Any]:
    return _row(conn, report_id)


def list_reports(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    if not _table_exists(conn, "record_governed_reports"):
        return []
    return [_row(conn, row[0]) for row in conn.execute("SELECT id FROM record_governed_reports ORDER BY created_at,id")]


def read_candidates(conn: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
    records = []
    if _table_exists(conn, "records"):
        columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(records)")}
        if "reference" in columns:
            label_column = "title" if "title" in columns else "reference"
            latest_clause = " WHERE is_latest=1" if "is_latest" in columns else ""
            records = [{"reference": str(item[0]), "label": str(item[1] or item[0])} for item in conn.execute(f"SELECT reference,{label_column} FROM records{latest_clause} ORDER BY reference")]
    documents = []
    for item in rda.list_published_document_options():
        documents.append({"document_id": str(item.get("document_id") or item.get("intake_id") or ""), "label": str(item.get("title") or item.get("document_identifier") or item.get("document_id") or "")})
    associations = []
    if _table_exists(conn, "record_document_associations"):
        for item in conn.execute("SELECT id,record_reference,document_id,relationship_type,is_active FROM record_document_associations WHERE is_active=1 ORDER BY record_reference,id").fetchall():
            associations.append({"id": str(item[0]), "label": f"{item[1]} — {item[2]} ({item[3] or 'association'})", "record_reference": str(item[1]), "document_id": str(item[2])})
    return {"records": records[:MAX_SELECTED_OBJECTS], "documents": sorted(documents, key=lambda x: x["document_id"])[:MAX_SELECTED_OBJECTS], "associations": associations[:MAX_SELECTED_OBJECTS]}


def _validate_generation_sources(conn: sqlite3.Connection, specification: Mapping[str, Any]) -> None:
    current_record = _record_snapshot(conn, str(specification["primary_record"]["reference"]))
    for key in ("reference", "title", "description", "status", "version"):
        if current_record.get(key) != specification["primary_record"].get(key):
            raise ValueError("governed_report_canonical_record_changed")
    for selected in specification.get("selected_documents", []):
        current = _document_snapshot(str(selected["document_id"]))
        if current.get("status") != selected.get("status") or current.get("sha256") != selected.get("sha256"):
            raise ValueError("governed_report_source_changed_or_hash_mismatch")
    for selected in specification.get("selected_associations", []):
        current = _association_snapshot(conn, selected["association_id"])
        if current != selected:
            raise ValueError("governed_report_association_changed")


def create_report(conn: sqlite3.Connection, *, title: str, purpose: str, audience: str, distribution_class: str, canonical_record_reference: str, document_ids: Any, association_ids: Any, sections: Any, exclusions: Any, requested_formats: Any, rendering_profile: str, template_version: str, actor: str, actor_role: str, idempotency_key: str, created_at: str | None = None, _commit: bool = True) -> dict[str, Any]:
    ensure_report_tables(conn)
    actor_value = _required(actor, "governed_report_actor_required")
    role_value = _required(actor_role, "governed_report_actor_role_required")
    key = _required(idempotency_key, "governed_report_idempotency_key_required")
    record = _record_snapshot(conn, canonical_record_reference)
    document_values = _unique_values(document_ids, "governed_report_document_selection_invalid")
    association_values = _unique_values(association_ids, "governed_report_association_selection_invalid")
    if len(document_values) > MAX_SELECTED_OBJECTS or len(association_values) > MAX_SELECTED_OBJECTS:
        raise ValueError("governed_report_selected_objects_too_many")
    documents = [_document_snapshot(value) for value in document_values]
    associations = [_association_snapshot(conn, value) for value in association_values]
    if any(item["record_reference"] != record["reference"] for item in associations):
        raise ValueError("governed_report_association_record_mismatch")
    specification = _canonical_specification(record=record, documents=documents, associations=associations, sections=sections, exclusions=exclusions, title=title, purpose=purpose, audience=audience, distribution_class=distribution_class, requested_formats=requested_formats, rendering_profile=rendering_profile, template_version=template_version)
    digest = specification_digest(specification)
    payload = {"specification": specification, "actor": actor_value, "actor_role": role_value, "declaration": {"acknowledged": True}}
    existing = conn.execute("SELECT id,request_payload_json FROM record_governed_reports WHERE idempotency_key=?", (key,)).fetchone()
    if existing:
        if json.loads(existing[1]) != payload:
            raise ValueError("governed_report_idempotency_conflict")
        return _row(conn, existing[0])
    now = created_at or utc_now()
    conn.execute("SAVEPOINT stage75_create")
    try:
        conn.execute("INSERT INTO record_governed_reports (idempotency_key,schema_version,report_type,title,purpose,intended_audience,distribution_class,created_by,created_by_role,created_at,lifecycle_status,request_payload_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (key, SCHEMA_VERSION, "canonical_record_report", specification["title"], specification["purpose"], specification["intended_audience"], distribution_class, actor_value, role_value, now, "draft_specification", canonical_json(payload)))
        report_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute("INSERT INTO record_governed_report_versions (report_id,version_number,canonical_record_reference,specification_schema_version,specification_json,specification_digest,requested_formats_json,publication_engine_version,rendering_profile,template_version,created_by,created_at,lifecycle_status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (report_id, 1, record["reference"], SPECIFICATION_SCHEMA_VERSION, canonical_json(specification), digest, canonical_json(specification["requested_formats"]), PUBLICATION_ENGINE_VERSION, specification["rendering_profile"], specification["template_version"], actor_value, now, "draft_specification"))
        version_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        event_payload = {"report_id": report_id, "version_id": version_id, "event_type": "created", "resulting_status": "draft_specification", "actor": actor_value, "actor_role": role_value, "declaration": {"acknowledged": True}}
        conn.execute("INSERT INTO record_governed_report_events (report_id,version_id,event_type,resulting_status,rationale,actor,actor_role,declaration_json,occurred_at,idempotency_key,request_payload_json) VALUES (?,?,?,?,?,?,?,?,?,?,?)", (report_id, version_id, "created", "draft_specification", "Report specification created as a deliberate internal assembly.", actor_value, role_value, '{"acknowledged":true}', now, key + ":created", canonical_json(event_payload)))
        conn.execute("RELEASE SAVEPOINT stage75_create")
        if _commit: conn.commit()
    except Exception:
        conn.execute("ROLLBACK TO SAVEPOINT stage75_create"); conn.execute("RELEASE SAVEPOINT stage75_create"); raise
    return _row(conn, report_id)


def transition_report(conn: sqlite3.Connection, *, report_id: int | str, resulting_status: str, rationale: str, actor: str, actor_role: str, declaration: Mapping[str, Any], idempotency_key: str, _commit: bool = True) -> dict[str, Any]:
    report = _row(conn, report_id); current = report["lifecycle_status"]
    if resulting_status not in LIFECYCLE: raise ValueError("governed_report_status_invalid")
    allowed = {"draft_specification": {"assembly_reviewed", "withdrawn"}, "assembly_reviewed": {"privacy_reviewed", "withdrawn"}, "privacy_reviewed": {"redaction_reviewed", "withdrawn"}, "redaction_reviewed": {"approved_for_generation", "withdrawn"}, "approved_for_generation": {"withdrawn"}, "validation_failed": {"approved_for_generation", "withdrawn"}, "generated": {"withdrawn"}}
    actor_value = _required(actor, "governed_report_event_actor_required"); role_value = _required(actor_role, "governed_report_event_actor_role_required"); rationale_value = _required(rationale, "governed_report_event_rationale_required")
    if resulting_status in {"assembly_reviewed", "privacy_reviewed", "redaction_reviewed", "approved_for_generation"} and actor_value == report["created_by"]:
        raise ValueError("governed_report_review_actor_must_differ_from_creator")
    if not isinstance(declaration, Mapping) or declaration != {"acknowledged": True}: raise ValueError("governed_report_event_declaration_required")
    key = _required(idempotency_key, "governed_report_event_idempotency_key_required")
    payload = {"report_id": int(report_id), "resulting_status": resulting_status, "rationale": rationale_value, "actor": actor_value, "actor_role": role_value, "declaration": dict(declaration)}
    existing = conn.execute("SELECT report_id,request_payload_json FROM record_governed_report_events WHERE idempotency_key=?", (key,)).fetchone()
    if existing:
        if json.loads(existing[1]) != payload: raise ValueError("governed_report_idempotency_conflict")
        return _row(conn, existing[0])
    if resulting_status not in allowed.get(current, set()): raise ValueError("governed_report_transition_invalid")
    now = utc_now(); conn.execute("SAVEPOINT stage75_event")
    try:
        conn.execute("UPDATE record_governed_reports SET lifecycle_status=? WHERE id=?", (resulting_status, int(report_id)))
        conn.execute("UPDATE record_governed_report_versions SET lifecycle_status=? WHERE report_id=? AND version_number=(SELECT MAX(version_number) FROM record_governed_report_versions WHERE report_id=?)", (resulting_status, int(report_id), int(report_id)))
        conn.execute("INSERT INTO record_governed_report_events (report_id,version_id,event_type,resulting_status,rationale,actor,actor_role,declaration_json,occurred_at,idempotency_key,request_payload_json) VALUES (?,?,?,?,?,?,?,?,?,?,?)", (int(report_id), report["versions"][-1]["id"], resulting_status, resulting_status, rationale_value, actor_value, role_value, canonical_json(declaration), now, key, canonical_json(payload)))
        conn.execute("RELEASE SAVEPOINT stage75_event")
        if _commit: conn.commit()
    except Exception:
        conn.execute("ROLLBACK TO SAVEPOINT stage75_event"); conn.execute("RELEASE SAVEPOINT stage75_event"); raise
    return _row(conn, report_id)


def supersede_report(conn: sqlite3.Connection, *, report_id: int | str, replacement_report_id: int | str, rationale: str, actor: str, actor_role: str, declaration: Mapping[str, Any], idempotency_key: str, _commit: bool = True) -> dict[str, Any]:
    source = _row(conn, report_id)
    replacement = _row(conn, replacement_report_id)
    if int(report_id) == int(replacement_report_id) or source["report_type"] != replacement["report_type"]:
        raise ValueError("governed_report_supersession_target_invalid")
    if source["versions"][-1]["canonical_record_reference"] != replacement["versions"][-1]["canonical_record_reference"]:
        raise ValueError("governed_report_supersession_record_mismatch")
    actor_value = _required(actor, "governed_report_event_actor_required"); role_value = _required(actor_role, "governed_report_event_actor_role_required"); rationale_value = _required(rationale, "governed_report_event_rationale_required")
    if not isinstance(declaration, Mapping) or declaration != {"acknowledged": True}:
        raise ValueError("governed_report_event_declaration_required")
    key = _required(idempotency_key, "governed_report_event_idempotency_key_required")
    payload = {"report_id": int(report_id), "replacement_report_id": int(replacement_report_id), "rationale": rationale_value, "actor": actor_value, "actor_role": role_value, "declaration": dict(declaration)}
    existing = conn.execute("SELECT report_id,request_payload_json FROM record_governed_report_events WHERE idempotency_key=?", (key,)).fetchone()
    if existing:
        if json.loads(existing[1]) != payload:
            raise ValueError("governed_report_idempotency_conflict")
        return _row(conn, existing[0])
    if source["lifecycle_status"] in TERMINAL or replacement["lifecycle_status"] in TERMINAL:
        raise ValueError("governed_report_supersession_terminal")
    current = int(replacement_report_id)
    visited = set()
    while current not in visited:
        visited.add(current)
        row = conn.execute("SELECT request_payload_json FROM record_governed_report_events WHERE report_id=? AND event_type='superseded' ORDER BY id DESC LIMIT 1", (current,)).fetchone()
        if not row:
            break
        current = int(json.loads(row[0])["replacement_report_id"])
        if current == int(report_id):
            raise ValueError("governed_report_supersession_cycle")
    now = utc_now()
    conn.execute("SAVEPOINT stage75_supersede")
    try:
        conn.execute("UPDATE record_governed_reports SET lifecycle_status='superseded' WHERE id=?", (int(report_id),))
        conn.execute("UPDATE record_governed_report_versions SET lifecycle_status='superseded' WHERE report_id=?", (int(report_id),))
        conn.execute("INSERT INTO record_governed_report_events (report_id,version_id,event_type,resulting_status,rationale,actor,actor_role,declaration_json,occurred_at,idempotency_key,request_payload_json) VALUES (?,?,?,?,?,?,?,?,?,?,?)", (int(report_id), source["versions"][-1]["id"], "superseded", "superseded", rationale_value, actor_value, role_value, canonical_json(declaration), now, key, canonical_json(payload)))
        conn.execute("RELEASE SAVEPOINT stage75_supersede")
        if _commit: conn.commit()
    except Exception:
        conn.execute("ROLLBACK TO SAVEPOINT stage75_supersede"); conn.execute("RELEASE SAVEPOINT stage75_supersede"); raise
    return _row(conn, report_id)


def generate_report(conn: sqlite3.Connection, *, report_id: int | str, actor: str, actor_role: str, idempotency_key: str, _commit: bool = True) -> dict[str, Any]:
    report = _row(conn, report_id)
    actor_value = _required(actor, "governed_report_generation_actor_required"); role_value = _required(actor_role, "governed_report_generation_role_required"); key = _required(idempotency_key, "governed_report_generation_idempotency_key_required")
    version = report["versions"][-1]; spec = version["specification"]
    if specification_digest(spec) != version["specification_digest"]:
        raise ValueError("governed_report_specification_digest_mismatch")
    request_payload = {"version_id": version["id"], "formats": spec["requested_formats"], "actor": actor_value, "actor_role": role_value, "specification_digest": version["specification_digest"], "rendering_profile": spec["rendering_profile"], "template_version": spec["template_version"], "publication_engine_version": spec["publication_engine_version"]}
    existing = conn.execute("SELECT * FROM record_governed_report_generation_attempts WHERE idempotency_key=?", (key,)).fetchone()
    if existing:
        if json.loads(existing["request_payload_json"]) == request_payload:
            if existing["result"] == "generated":
                return _row(conn, report_id)
            raise ValueError("governed_report_generation_failed")
        raise ValueError("governed_report_generation_idempotency_conflict")
    if report["lifecycle_status"] != "approved_for_generation": raise ValueError("governed_report_generation_approval_required")
    _validate_generation_sources(conn, spec)
    target_dir = REPORT_ROOT / str(report_id) / str(version["version_number"])
    if target_dir.exists():
        raise ValueError("governed_report_artifact_directory_exists")
    now = utc_now()
    conn.execute("SAVEPOINT stage75_generation_request")
    try:
        conn.execute("INSERT INTO record_governed_report_generation_attempts (version_id,requested_formats_json,actor,actor_role,requested_at,result,diagnostics_json,request_payload_json,idempotency_key) VALUES (?,?,?,?,?,?,?,?,?)", (version["id"], canonical_json(spec["requested_formats"]), actor_value, role_value, now, "requested", "[]", canonical_json(request_payload), key))
        conn.execute("INSERT INTO record_governed_report_events (report_id,version_id,event_type,resulting_status,rationale,actor,actor_role,declaration_json,occurred_at,idempotency_key,request_payload_json) VALUES (?,?,?,?,?,?,?,?,?,?,?)", (int(report_id), version["id"], "generation_requested", "generation_requested", "Generation requested for the approved immutable report specification.", actor_value, role_value, '{"acknowledged":true}', now, key + ":requested", canonical_json(request_payload)))
        conn.execute("UPDATE record_governed_reports SET lifecycle_status='generation_requested' WHERE id=?", (int(report_id),))
        conn.execute("UPDATE record_governed_report_versions SET lifecycle_status='generation_requested' WHERE id=?", (version["id"],))
        conn.execute("RELEASE SAVEPOINT stage75_generation_request")
    except Exception:
        conn.execute("ROLLBACK TO SAVEPOINT stage75_generation_request")
        conn.execute("RELEASE SAVEPOINT stage75_generation_request")
        raise
    try:
        from api.report_rendering import render_frozen_report
        result = render_frozen_report(spec, version["specification_digest"], REPORT_ROOT / str(report_id) / str(version["version_number"]))
    except Exception as exc:
        diagnostics = ["governed_report_generation_validation_failed", type(exc).__name__]
        conn.execute("UPDATE record_governed_report_generation_attempts SET result=?,diagnostics_json=? WHERE idempotency_key=?", ("validation_failed", canonical_json(diagnostics), key))
        conn.execute("UPDATE record_governed_reports SET lifecycle_status='validation_failed' WHERE id=?", (int(report_id),))
        conn.execute("UPDATE record_governed_report_versions SET lifecycle_status='validation_failed' WHERE id=?", (version["id"],))
        conn.execute("INSERT INTO record_governed_report_events (report_id,version_id,event_type,resulting_status,rationale,actor,actor_role,declaration_json,occurred_at,idempotency_key,request_payload_json) VALUES (?,?,?,?,?,?,?,?,?,?,?)", (int(report_id), version["id"], "validation_failed", "validation_failed", "Rendering or output validation failed.", actor_value, role_value, '{"acknowledged":true}', utc_now(), key + ":failed", canonical_json({"diagnostics": diagnostics})))
        shutil.rmtree(target_dir.parent, ignore_errors=True)
        conn.commit() if _commit else None
        raise ValueError("governed_report_generation_failed") from None
    try:
        conn.execute("SAVEPOINT stage75_generation_db")
        for item in result["artifacts"]:
            conn.execute("INSERT INTO record_governed_report_artifacts (version_id,format,storage_reference,sha256,size_bytes,renderer_version,template_version,generated_at,validation_state,diagnostics_json,lifecycle_status) VALUES (?,?,?,?,?,?,?,?,?,?,?)", (version["id"], item["format"], item["path"], item["sha256"], item["size_bytes"], item["renderer_version"], spec["template_version"], now, "valid", canonical_json(result["diagnostics"]), "current"))
        conn.execute("UPDATE record_governed_report_generation_attempts SET result=?,diagnostics_json=? WHERE idempotency_key=?", ("generated", canonical_json(result["diagnostics"]), key))
        conn.execute("UPDATE record_governed_reports SET lifecycle_status='generated' WHERE id=?", (int(report_id),))
        conn.execute("UPDATE record_governed_report_versions SET lifecycle_status='generated' WHERE id=?", (version["id"],))
        conn.execute("RELEASE SAVEPOINT stage75_generation_db")
    except Exception:
        conn.execute("ROLLBACK TO SAVEPOINT stage75_generation_db")
        conn.execute("RELEASE SAVEPOINT stage75_generation_db")
        shutil.rmtree(target_dir.parent, ignore_errors=True)
        conn.execute("UPDATE record_governed_report_generation_attempts SET result=?,diagnostics_json=? WHERE idempotency_key=?", ("validation_failed", canonical_json(["artifact registration failed"]), key))
        conn.execute("UPDATE record_governed_reports SET lifecycle_status='validation_failed' WHERE id=?", (int(report_id),))
        conn.execute("UPDATE record_governed_report_versions SET lifecycle_status='validation_failed' WHERE id=?", (version["id"],))
        if _commit: conn.commit()
        raise ValueError("governed_report_artifact_registration_failed") from None
    if _commit: conn.commit()
    return _row(conn, report_id)
