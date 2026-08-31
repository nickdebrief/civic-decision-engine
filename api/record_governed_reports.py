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
from api.governed_report_diagnostics import bounded_code, combine_cleanup_status, make_diagnostic, validate_diagnostic

SCHEMA_VERSION = "stage75.governed_report.v1"
SPECIFICATION_SCHEMA_VERSION = "stage75.report_specification.v1"
PATHWAY_SPECIFICATION_SCHEMA_VERSION = "stage78.procedural_pathway_report_specification.v1"
PUBLICATION_ENGINE_VERSION = "2.0.0"
PATHWAY_PROJECTION_CONTRACT = "stage78.pathway_projection.v1"
PATHWAY_PROJECTION_VERSION = "78a2b2"
PATHWAY_REPORT_TYPE = "procedural_pathway_report"
PATHWAY_SOURCE_IDENTITY_KIND = "governed_pathway_projection"
PATHWAY_RENDERING_PROFILE = "internal_pathway_v1"
PATHWAY_TEMPLATE_VERSION = "cde-internal-pathway-v1"
PATHWAY_INCLUSION_MODE = "full_canonical_record_scope"
PATHWAY_EXCLUSION_RULE = "full_scope_no_selected_subset_or_caller_supplied_authority"
PATHWAY_RENDER_MODEL_CONTRACT = "stage78.pathway_render_model.v1"
REPORT_TYPES = {"canonical_record_report"}
_SUPPORTED_REPORT_TYPES = REPORT_TYPES | {PATHWAY_REPORT_TYPE}
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
_LOWER_SHA256 = set("0123456789abcdef")

BOUNDARY = "A REPORT PRESENTS THE RECORD—IT DOES NOT REPLACE IT. Inclusion is not endorsement. Exclusion is not proof of absence. A summary is not original language. Printing is not publication. Publication Engine validation is not legal validation."


class GovernedReportGenerationFailure(ValueError):
    """A generation failure carrying only the bounded diagnostic contract."""

    def __init__(self, diagnostic: Mapping[str, Any]) -> None:
        self.diagnostic = validate_diagnostic(diagnostic)
        self.code = self.diagnostic["failure_code"]
        display_code = "governed_report_generation_failed" if self.code == "governed_report_generation_validation_failed" else self.code
        super().__init__(display_code)


def _cleanup_generation_output(path: Path) -> str:
    try:
        if path.is_symlink() or path.is_file():
            path.unlink(missing_ok=True)
        elif path.is_dir():
            shutil.rmtree(path)
        return "passed" if not path.exists() and not path.is_symlink() else "failed"
    except OSError:
        return "failed"


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


def _assert_confined_output(root: Path, candidate: Path) -> None:
    raw_root = Path(root)
    raw_candidate = Path(candidate)
    if raw_root.exists() and raw_root.is_symlink():
        raise ValueError("governed_report_artifact_path_invalid")
    current = raw_candidate
    while current != raw_root and current != current.parent:
        if current.exists() and current.is_symlink():
            raise ValueError("governed_report_artifact_path_invalid")
        current = current.parent
    root = raw_root.resolve(strict=False)
    candidate = raw_candidate.resolve(strict=False)
    if not candidate.is_relative_to(root):
        raise ValueError("governed_report_artifact_path_invalid")


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
    columns = {row[1] for row in conn.execute("PRAGMA table_info(record_governed_report_artifacts)").fetchall()}
    for name, definition in (("qualification_id", "INTEGER"), ("qualification_digest", "TEXT"), ("disclosure_version", "TEXT")):
        if name not in columns:
            conn.execute(f"ALTER TABLE record_governed_report_artifacts ADD COLUMN {name} {definition}")
    validate_report_tables(conn)
    from api import governed_report_qualifications as qualifications
    qualifications.ensure_qualification_tables(conn)


def validate_report_tables(conn: sqlite3.Connection) -> None:
    """Validate the Stage 75-owned schema without creating or changing data."""
    required = {
        "record_governed_reports": {"id": "INTEGER", "idempotency_key": "TEXT", "lifecycle_status": "TEXT"},
        "record_governed_report_versions": {"id": "INTEGER", "report_id": "INTEGER", "version_number": "INTEGER"},
        "record_governed_report_artifacts": {"id": "INTEGER", "version_id": "INTEGER", "format": "TEXT", "storage_reference": "TEXT", "sha256": "TEXT", "size_bytes": "INTEGER", "validation_state": "TEXT"},
    }
    for table, expected_columns in required.items():
        rows = conn.execute("PRAGMA table_info(%s)" % table).fetchall()
        columns = {str(row[1]): str(row[2]).upper() for row in rows}
        if not rows or any(columns.get(name) != expected_type for name, expected_type in expected_columns.items()):
            raise ValueError("stage75_schema_incompatible")


def _record_snapshot(conn: sqlite3.Connection, reference: str) -> dict[str, Any]:
    value = None
    if _table_exists(conn, "records"):
        available_columns = {
            str(row[1])
            for row in conn.execute("PRAGMA table_info(records)").fetchall()
        }
        preferred_columns = (
            "reference", "record_type", "title", "public_title", "record_title",
            "institution", "institution_type", "institution_source", "summary",
            "public_summary", "finding", "generated_at", "exported_at", "trajectory",
            "system_state", "version", "language", "source_document_id",
            "source_document_reference", "status",
        )
        selected_columns = [column for column in preferred_columns if column in available_columns]
        if "reference" in selected_columns:
            latest_clause = " AND is_latest = 1" if "is_latest" in available_columns else ""
            order_clause = " ORDER BY version DESC" if "version" in available_columns else ""
            row = conn.execute(
                f"SELECT {', '.join(selected_columns)} FROM records WHERE reference = ?{latest_clause}{order_clause} LIMIT 1",
                (str(reference or "").strip(),),
            ).fetchone()
            value = dict(row) if row else None
    else:
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


def _formats(requested_formats: Any) -> list[str]:
    if not isinstance(requested_formats, (list, tuple)):
        raise ValueError("governed_report_output_formats_invalid")
    formats = list(requested_formats)
    if any(not isinstance(item, str) or item not in OUTPUT_FORMATS for item in formats):
        raise ValueError("governed_report_output_formats_invalid")
    if not formats or len(formats) != len(set(formats)):
        raise ValueError("governed_report_output_formats_invalid")
    if "pdf" in formats and not {"docx", "html"}.issubset(formats):
        raise ValueError("governed_report_pdf_companion_formats_required")
    return sorted(formats)


def _plain_sha256(value: Any, error: str) -> str:
    text = str(value or "")
    if text.startswith("sha256:"):
        text = text.removeprefix("sha256:")
    if len(text) != 64 or any(character not in _LOWER_SHA256 for character in text):
        raise ValueError(error)
    return text


def _required_exact_string(value: Any, error: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(error)
    return value


def _projection_module():
    from api import record_governed_pathway_projection as projection
    return projection


def _logical_identity_for_projection_row(conn: sqlite3.Connection, row: Mapping[str, Any]) -> str:
    projection = _projection_module()
    identity = projection._logical_identity(conn, str(row.get("object_kind") or ""), row.get("object_id"))  # type: ignore[attr-defined]
    if not identity:
        raise ValueError("governed_report_pathway_specification_invalid")
    return str(identity)


def _compact_pathway_row(conn: sqlite3.Connection, row: Mapping[str, Any]) -> dict[str, Any]:
    object_kind = _required(row.get("object_kind"), "governed_report_pathway_specification_invalid")
    governed_identity = _logical_identity_for_projection_row(conn, row)
    ownership_path = _required(row.get("ownership_path"), "governed_report_pathway_specification_invalid")
    source_authority_key = _required_exact_string(row.get("governed_digest"), "governed_report_pathway_specification_invalid")
    endpoints = []
    for link in row.get("object_links") or []:
        if not isinstance(link, Mapping):
            raise ValueError("governed_report_pathway_specification_invalid")
        endpoint_identity = _required(link.get("object_governed_identity"), "governed_report_pathway_specification_invalid")
        endpoints.append({
            "object_type": _required(link.get("object_type"), "governed_report_pathway_specification_invalid"),
            "object_governed_identity": endpoint_identity,
            "relationship_role": _required(link.get("relationship_role"), "governed_report_pathway_specification_invalid"),
        })
    endpoints.sort(key=lambda item: (item["object_type"], item["object_governed_identity"], item["relationship_role"]))
    compact = {
        "object_kind": object_kind,
        "governed_logical_identity": governed_identity,
        "parent_governed_identity": row.get("parent_governed_identity"),
        "endpoint_identities": endpoints,
        "status": row.get("status"),
        "source_authority_key": source_authority_key,
        "ownership_path": ownership_path,
    }
    compact["row_authority_digest"] = _row_authority_digest(compact)
    return compact


def _row_authority_payload(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "object_kind": row.get("object_kind"),
        "governed_logical_identity": row.get("governed_logical_identity"),
        "parent_governed_identity": row.get("parent_governed_identity"),
        "endpoint_identities": row.get("endpoint_identities"),
        "status": row.get("status"),
        "ownership_path": row.get("ownership_path"),
        "source_authority_key": row.get("source_authority_key"),
    }


def _row_authority_digest(row: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(_row_authority_payload(row)).encode("utf-8")).hexdigest()


def _compact_pathway_identity_from_projected(conn: sqlite3.Connection, record_reference: str, projected: Mapping[str, Any]) -> dict[str, Any]:
    if projected.get("projection_contract") != PATHWAY_PROJECTION_CONTRACT:
        raise ValueError("governed_report_pathway_projection_contract_unsupported")
    if projected.get("projection_version") != PATHWAY_PROJECTION_VERSION:
        raise ValueError("governed_report_pathway_projection_version_unsupported")
    if str(projected.get("record_reference") or "") != record_reference:
        raise ValueError("governed_report_pathway_specification_invalid")
    rows = [_compact_pathway_row(conn, row) for row in projected.get("rows") or []]
    identities = [row["governed_logical_identity"] for row in rows]
    if len(identities) != len(set(identities)):
        raise ValueError("governed_report_pathway_row_inventory_invalid")
    coverage = dict(projected.get("coverage") or {})
    gaps = [dict(item) for item in projected.get("gaps") or []]
    unavailable = sorted(
        key.removesuffix("_schema_present")
        for key, value in coverage.items()
        if key.startswith("stage") and key.endswith("_schema_present") and value is False
    )
    return {
        "source_identity": {
            "object_kind": PATHWAY_SOURCE_IDENTITY_KIND,
            "object_id": record_reference,
        },
        "canonical_record_reference": record_reference,
        "projection_contract": PATHWAY_PROJECTION_CONTRACT,
        "projection_version": PATHWAY_PROJECTION_VERSION,
        "projection_digest": _plain_sha256(projected.get("projection_digest"), "governed_report_pathway_projection_digest_invalid"),
        "inclusion_mode": PATHWAY_INCLUSION_MODE,
        "exclusion_rule": PATHWAY_EXCLUSION_RULE,
        "rows": rows,
        "coverage": coverage,
        "unavailable_families": unavailable,
        "gaps": gaps,
    }


def _compact_pathway_identity(conn: sqlite3.Connection, record_reference: str) -> dict[str, Any]:
    projection = _projection_module()
    try:
        projected = projection.project_pathway(conn, record_reference)
    except ValueError as exc:
        if str(exc).endswith("_schema_incomplete"):
            raise ValueError("governed_report_pathway_schema_incomplete") from None
        raise
    return _compact_pathway_identity_from_projected(conn, record_reference, projected)


def _validate_live_pathway_identity(conn: sqlite3.Connection, specification: Mapping[str, Any]) -> dict[str, Any]:
    validate_pathway_report_specification(conn, specification)
    current_record = _record_snapshot(conn, str(specification["primary_record"]["reference"]))
    for key in ("reference", "title", "description", "status", "version"):
        if current_record.get(key) != specification["primary_record"].get(key):
            raise ValueError("governed_report_canonical_record_changed")
    frozen = specification["pathway_projection"]
    live = _compact_pathway_identity(conn, str(specification["primary_record"]["reference"]))
    if live["projection_digest"] != frozen["projection_digest"]:
        raise ValueError("governed_report_pathway_projection_digest_drift")
    if live["rows"] != frozen["rows"]:
        raise ValueError("governed_report_pathway_row_inventory_drift")
    if (
        live["coverage"] != frozen["coverage"]
        or live["unavailable_families"] != frozen["unavailable_families"]
    ):
        raise ValueError("governed_report_pathway_coverage_drift")
    if live["gaps"] != frozen["gaps"]:
        raise ValueError("governed_report_pathway_gap_drift")
    if live != frozen:
        raise ValueError("governed_report_pathway_specification_invalid")
    return live


_PATHWAY_SECTION_MAP = {
    "governed_observation": "Observations",
    "governed_inference": "Inferences",
    "governed_allegation": "Allegations",
    "governed_response": "Responses and express declinations",
    "governed_characterisation": "Characterisations",
    "decision_authority": "Authority and mandate",
    "decision_mandate": "Authority and mandate",
    "governed_determination": "Determinations and reasons",
    "determination_effect_event": "Determinations and reasons",
    "governed_challenge": "Challenges",
    "challenge_event": "Challenges",
    "challenge_outcome": "Challenges",
    "governed_remedy": "Remedies",
    "implementation_event": "Implementation, compliance and verification",
    "formal_completion_determination": "Implementation, compliance and verification",
    "determination_publication": "Determination publications",
    "procedural_notice": "Notice and participation",
    "procedural_deadline": "Procedural chronology",
    "procedural_time_event": "Procedural chronology",
    "deadline_calculation": "Procedural chronology",
    "pathway_link": "Pathway relationships",
}
_PATHWAY_RENDER_OBJECT_KINDS = frozenset(_PATHWAY_SECTION_MAP)

_PATHWAY_SECTION_ORDER = [
    "Report identity and scope",
    "Authority and mandate",
    "Procedural chronology",
    "Notice and participation",
    "Observations",
    "Inferences",
    "Allegations",
    "Responses and express declinations",
    "Characterisations",
    "Determinations and reasons",
    "Challenges",
    "Remedies",
    "Implementation, compliance and verification",
    "Determination publications",
    "Pathway relationships",
    "Contested matters",
    "Scoped gaps",
    "Provenance and limitations",
]


def _pathway_render_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _pathway_render_value(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_pathway_render_value(item) for item in value]
    if isinstance(value, tuple):
        return [_pathway_render_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _pathway_render_governance_state(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _pathway_render_governance_state(value[key])
            for key in sorted(value)
            if str(key) not in {"actor", "actor_role", "reviewer", "reviewed_by", "reviewed_by_role"}
        }
    if isinstance(value, list):
        return [_pathway_render_governance_state(item) for item in value]
    return _pathway_render_value(value)


def _pathway_render_object_kind(value: Any) -> str:
    object_kind = _required_exact_string(value, "governed_report_pathway_render_model_invalid")
    if object_kind not in _PATHWAY_RENDER_OBJECT_KINDS:
        raise ValueError("governed_report_pathway_render_model_invalid")
    return object_kind


def _pathway_render_row(conn: sqlite3.Connection, row: Mapping[str, Any], compact: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "object_kind": _pathway_render_object_kind(row.get("object_kind")),
        "governed_logical_identity": _required(compact.get("governed_logical_identity"), "governed_report_pathway_render_model_invalid"),
        "parent_governed_identity": compact.get("parent_governed_identity"),
        "endpoint_identities": _pathway_render_value(compact.get("endpoint_identities") or []),
        "category": row.get("category"),
        "status": row.get("status"),
        "source_authority_key": _required_exact_string(compact.get("source_authority_key"), "governed_report_pathway_render_model_invalid"),
        "row_authority_digest": _plain_sha256(compact.get("row_authority_digest"), "governed_report_pathway_render_model_invalid"),
        "ownership_path": _required(compact.get("ownership_path"), "governed_report_pathway_render_model_invalid"),
        "represented_time": row.get("represented_time"),
        "recorded_at": row.get("recorded_at"),
        "chronology": {
            "basis": row.get("chronology_basis"),
            "precision": row.get("chronology_precision"),
            "lower_bound": row.get("chronology_lower_bound"),
            "upper_bound": row.get("chronology_upper_bound"),
            "ordering_relation": row.get("ordering_relation"),
        },
        "source_bindings": _pathway_render_value(row.get("source_bindings") or []),
        "object_links": _pathway_render_value([
            {key: value for key, value in dict(link).items() if key != "object_id"}
            for link in row.get("object_links") or []
            if isinstance(link, Mapping)
        ]),
        "contestation": _pathway_render_value(row.get("contestation") or {}),
        "supersession": _pathway_render_governance_state(row.get("supersession") or {}),
        "reliance": _pathway_render_value(row.get("reliance") or {"status": "unavailable"}),
        "limitations": _pathway_render_value(row.get("limitations")),
        "epistemic_label": row.get("epistemic_label"),
        "attribution": _pathway_render_value(row.get("attribution") or {}),
        "representation_mode": row.get("representation_mode"),
        "review_state": _pathway_render_governance_state(row.get("review_state") or {}),
        "contrary_sources": _pathway_render_value(row.get("contrary_sources") or []),
        "does_not_establish": _pathway_render_value(row.get("does_not_establish") or {}),
    }


def materialize_pathway_render_model(conn: sqlite3.Connection, specification: Mapping[str, Any]) -> dict[str, Any]:
    validate_pathway_report_specification(conn, specification)
    current_record = _record_snapshot(conn, str(specification["primary_record"]["reference"]))
    for key in ("reference", "title", "description", "status", "version"):
        if current_record.get(key) != specification["primary_record"].get(key):
            raise ValueError("governed_report_canonical_record_changed")
    try:
        projection = _projection_module().project_pathway(conn, str(specification["primary_record"]["reference"]))
    except ValueError as exc:
        if str(exc).endswith("_schema_incomplete"):
            raise ValueError("governed_report_pathway_schema_incomplete") from None
        raise
    live_identity = _compact_pathway_identity_from_projected(conn, str(specification["primary_record"]["reference"]), projection)
    frozen = specification["pathway_projection"]
    if live_identity["projection_digest"] != frozen["projection_digest"]:
        raise ValueError("governed_report_pathway_projection_digest_drift")
    if live_identity["rows"] != frozen["rows"]:
        raise ValueError("governed_report_pathway_row_inventory_drift")
    if (
        live_identity["coverage"] != frozen["coverage"]
        or live_identity["unavailable_families"] != frozen["unavailable_families"]
    ):
        raise ValueError("governed_report_pathway_coverage_drift")
    if live_identity["gaps"] != frozen["gaps"]:
        raise ValueError("governed_report_pathway_gap_drift")
    if live_identity != frozen:
        raise ValueError("governed_report_pathway_specification_invalid")
    compact_by_identity = {
        row["governed_logical_identity"]: row
        for row in live_identity["rows"]
    }
    rows = []
    for row in projection.get("rows") or []:
        compact_identity = _logical_identity_for_projection_row(conn, row)
        compact = compact_by_identity.get(compact_identity)
        if compact is None:
            raise ValueError("governed_report_pathway_render_model_invalid")
        rows.append(_pathway_render_row(conn, row, compact))
    sections: dict[str, list[dict[str, Any]]] = {name: [] for name in _PATHWAY_SECTION_ORDER}
    for row in rows:
        section = _PATHWAY_SECTION_MAP[row["object_kind"]]
        sections[section].append(row)
    contested = [
        {
            "governed_logical_identity": row["governed_logical_identity"],
            "object_kind": row["object_kind"],
            "category": row["category"],
            "status": row["status"],
            "contestation": row["contestation"],
            "supersession": row["supersession"],
        }
        for row in rows
        if (isinstance(row.get("contestation"), Mapping) and row["contestation"].get("status") not in {None, "not_represented"})
        or (isinstance(row.get("supersession"), Mapping) and row["supersession"].get("superseded"))
    ]
    sections["Contested matters"] = contested
    section_list = [{"title": name, "rows": sections[name]} for name in _PATHWAY_SECTION_ORDER if sections[name] or name in {"Report identity and scope", "Scoped gaps", "Provenance and limitations"}]
    return {
        "render_model_contract": PATHWAY_RENDER_MODEL_CONTRACT,
        "report_type": PATHWAY_REPORT_TYPE,
        "specification_schema_version": PATHWAY_SPECIFICATION_SCHEMA_VERSION,
        "title": specification["title"],
        "purpose": specification["purpose"],
        "intended_audience": specification["intended_audience"],
        "distribution_class": "internal_working",
        "canonical_record_reference": live_identity["canonical_record_reference"],
        "projection_contract": live_identity["projection_contract"],
        "projection_version": live_identity["projection_version"],
        "projection_digest": live_identity["projection_digest"],
        "inclusion_mode": live_identity["inclusion_mode"],
        "exclusion_rule": live_identity["exclusion_rule"],
        "coverage": _pathway_render_value(live_identity["coverage"]),
        "unavailable_families": list(live_identity["unavailable_families"]),
        "gaps": _pathway_render_value(live_identity["gaps"]),
        "sections": section_list,
        "row_count": len(rows),
        "limitations": [
            "The procedural pathway report presents governed records only.",
            "Rendering does not establish legality, truth, fairness, completeness, compliance, publication or endorsement.",
            "Scoped gaps report unavailable or absent governed records within the frozen Canonical Record scope only.",
        ],
    }


def _validate_pathway_section(section: Any, *, record_reference: str) -> dict[str, Any]:
    if not isinstance(section, Mapping):
        raise ValueError("governed_report_pathway_specification_invalid")
    expected_keys = {
        "source_identity", "canonical_record_reference", "projection_contract", "projection_version",
        "projection_digest", "inclusion_mode", "exclusion_rule", "rows", "coverage",
        "unavailable_families", "gaps",
    }
    if set(section) != expected_keys:
        raise ValueError("governed_report_pathway_specification_invalid")
    if section["canonical_record_reference"] != record_reference:
        raise ValueError("governed_report_pathway_record_mismatch")
    source_identity = section["source_identity"]
    if not isinstance(source_identity, Mapping) or set(source_identity) != {"object_kind", "object_id"}:
        raise ValueError("governed_report_pathway_specification_invalid")
    if source_identity.get("object_kind") != PATHWAY_SOURCE_IDENTITY_KIND or source_identity.get("object_id") != record_reference:
        raise ValueError("governed_report_pathway_specification_invalid")
    if section["projection_contract"] != PATHWAY_PROJECTION_CONTRACT:
        raise ValueError("governed_report_pathway_projection_contract_unsupported")
    if section["projection_version"] != PATHWAY_PROJECTION_VERSION:
        raise ValueError("governed_report_pathway_projection_version_unsupported")
    _plain_sha256(section["projection_digest"], "governed_report_pathway_projection_digest_invalid")
    if section["inclusion_mode"] != PATHWAY_INCLUSION_MODE or section["exclusion_rule"] != PATHWAY_EXCLUSION_RULE:
        raise ValueError("governed_report_pathway_specification_invalid")
    if not isinstance(section["coverage"], Mapping) or not isinstance(section["unavailable_families"], list) or not isinstance(section["gaps"], list):
        raise ValueError("governed_report_pathway_specification_invalid")
    expected_unavailable = sorted(
        key.removesuffix("_schema_present")
        for key, value in section["coverage"].items()
        if str(key).startswith("stage") and str(key).endswith("_schema_present") and value is False
    )
    if section["unavailable_families"] != expected_unavailable:
        raise ValueError("governed_report_pathway_coverage_drift")
    rows = section["rows"]
    if not isinstance(rows, list):
        raise ValueError("governed_report_pathway_specification_invalid")
    identities: set[str] = set()
    projection = _projection_module()
    recognized = set(projection.KIND_RANK)  # type: ignore[attr-defined]
    for row in rows:
        if not isinstance(row, Mapping) or set(row) != {
            "object_kind", "governed_logical_identity", "parent_governed_identity",
            "endpoint_identities", "status", "source_authority_key", "row_authority_digest",
            "ownership_path",
        }:
            raise ValueError("governed_report_pathway_specification_invalid")
        if row["object_kind"] not in recognized:
            raise ValueError("governed_report_pathway_row_inventory_invalid")
        identity = _required(row.get("governed_logical_identity"), "governed_report_pathway_specification_invalid")
        if identity in identities:
            raise ValueError("governed_report_pathway_row_inventory_invalid")
        identities.add(identity)
        _required_exact_string(row.get("source_authority_key"), "governed_report_pathway_specification_invalid")
        _required(row.get("ownership_path"), "governed_report_pathway_specification_invalid")
        digest = _plain_sha256(row.get("row_authority_digest"), "governed_report_pathway_row_authority_digest_invalid")
        if row["parent_governed_identity"] is not None and not str(row["parent_governed_identity"]):
            raise ValueError("governed_report_pathway_specification_invalid")
        endpoints = row["endpoint_identities"]
        if not isinstance(endpoints, list):
            raise ValueError("governed_report_pathway_specification_invalid")
        for endpoint in endpoints:
            if not isinstance(endpoint, Mapping) or set(endpoint) != {"object_type", "object_governed_identity", "relationship_role"}:
                raise ValueError("governed_report_pathway_specification_invalid")
            _required(endpoint.get("object_type"), "governed_report_pathway_specification_invalid")
            _required(endpoint.get("object_governed_identity"), "governed_report_pathway_specification_invalid")
            _required(endpoint.get("relationship_role"), "governed_report_pathway_specification_invalid")
        if digest != _row_authority_digest(row):
            raise ValueError("governed_report_pathway_row_authority_digest_invalid")
    return dict(section)


def _canonical_specification(*, record: Mapping[str, Any], documents: list[Mapping[str, Any]], associations: list[Mapping[str, Any]], sections: Any, exclusions: Any, title: str, purpose: str, audience: str, distribution_class: str, requested_formats: Any, rendering_profile: str, template_version: str) -> dict[str, Any]:
    if distribution_class not in DISTRIBUTION_CLASSES:
        raise ValueError("governed_report_distribution_class_invalid")
    formats = _formats(requested_formats)
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


def _pathway_specification(*, conn: sqlite3.Connection, record: Mapping[str, Any], sections: Any, exclusions: Any, document_ids: Any, association_ids: Any, title: str, purpose: str, audience: str, distribution_class: str, requested_formats: Any, rendering_profile: str, template_version: str) -> dict[str, Any]:
    if distribution_class != "internal_working":
        raise ValueError("governed_report_pathway_distribution_invalid")
    if rendering_profile != PATHWAY_RENDERING_PROFILE:
        raise ValueError("governed_report_pathway_rendering_profile_invalid")
    if template_version != PATHWAY_TEMPLATE_VERSION:
        raise ValueError("governed_report_pathway_template_version_invalid")
    if document_ids not in (None, [], ()):
        raise ValueError("governed_report_pathway_authority_caller_supplied")
    if association_ids not in (None, [], ()):
        raise ValueError("governed_report_pathway_authority_caller_supplied")
    if sections not in (None, [], ()):
        raise ValueError("governed_report_pathway_authority_caller_supplied")
    if exclusions not in (None, [], ()):
        raise ValueError("governed_report_pathway_authority_caller_supplied")
    formats = _formats(requested_formats)
    pathway = _compact_pathway_identity(conn, str(record["reference"]))
    return {
        "specification_schema_version": PATHWAY_SPECIFICATION_SCHEMA_VERSION,
        "report_type": PATHWAY_REPORT_TYPE,
        "title": _required(title, "governed_report_title_required"),
        "purpose": _required(purpose, "governed_report_purpose_required"),
        "intended_audience": _required(audience, "governed_report_audience_required"),
        "distribution_class": "internal_working",
        "primary_record": dict(record),
        "pathway_projection": pathway,
        "selected_documents": [],
        "selected_associations": [],
        "sections": [],
        "exclusions": [],
        "qualifications": [
            BOUNDARY,
            "THE PROCEDURAL PATHWAY REPORT PRESENTS GOVERNED PATHWAY RECORDS ONLY.",
            "Projection does not establish legality, truth, fairness, completeness, compliance, or publication.",
        ],
        "requested_formats": formats,
        "publication_engine_version": PUBLICATION_ENGINE_VERSION,
        "rendering_profile": PATHWAY_RENDERING_PROFILE,
        "template_version": PATHWAY_TEMPLATE_VERSION,
    }


def _acquire_pathway_freeze_write_intent(conn: sqlite3.Connection) -> None:
    try:
        conn.execute("UPDATE record_governed_reports SET id=id WHERE 0")
    except sqlite3.Error:
        raise ValueError("governed_report_pathway_freeze_transaction_unavailable") from None


def _create_pathway_report_transactionally(conn: sqlite3.Connection, *, title: str, purpose: str, audience: str, distribution_class: str, canonical_record_reference: str, document_ids: Any, association_ids: Any, sections: Any, exclusions: Any, requested_formats: Any, rendering_profile: str, template_version: str, actor: str, actor_role: str, idempotency_key: str, created_at: str | None, _commit: bool) -> dict[str, Any]:
    actor_value = _required(actor, "governed_report_actor_required")
    role_value = _required(actor_role, "governed_report_actor_role_required")
    key = _required(idempotency_key, "governed_report_idempotency_key_required")
    owns_transaction = False
    savepoint_active = False
    if conn.in_transaction:
        validate_report_tables(conn)
        from api import governed_report_qualifications as qualifications
        qualifications.validate_qualification_tables(conn)
    else:
        try:
            ensure_report_tables(conn)
        except sqlite3.Error:
            raise ValueError("governed_report_pathway_freeze_transaction_unavailable") from None
    try:
        if not conn.in_transaction:
            try:
                conn.execute("BEGIN IMMEDIATE")
            except sqlite3.Error:
                raise ValueError("governed_report_pathway_freeze_transaction_unavailable") from None
            owns_transaction = True
        conn.execute("SAVEPOINT stage75_create")
        savepoint_active = True
        _acquire_pathway_freeze_write_intent(conn)
        record = _record_snapshot(conn, canonical_record_reference)
        specification = _pathway_specification(conn=conn, record=record, sections=sections, exclusions=exclusions, document_ids=document_ids, association_ids=association_ids, title=title, purpose=purpose, audience=audience, distribution_class=distribution_class, requested_formats=requested_formats, rendering_profile=rendering_profile, template_version=template_version)
        digest = specification_digest(specification)
        payload = {"specification": specification, "actor": actor_value, "actor_role": role_value, "declaration": {"acknowledged": True}}
        existing = conn.execute("SELECT id,request_payload_json FROM record_governed_reports WHERE idempotency_key=?", (key,)).fetchone()
        if existing:
            if json.loads(existing[1]) != payload:
                raise ValueError("governed_report_idempotency_conflict")
            conn.execute("RELEASE SAVEPOINT stage75_create")
            savepoint_active = False
            if owns_transaction and _commit:
                conn.commit()
            return _row(conn, existing[0])
        now = created_at or utc_now()
        conn.execute("INSERT INTO record_governed_reports (idempotency_key,schema_version,report_type,title,purpose,intended_audience,distribution_class,created_by,created_by_role,created_at,lifecycle_status,request_payload_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (key, SCHEMA_VERSION, specification["report_type"], specification["title"], specification["purpose"], specification["intended_audience"], specification["distribution_class"], actor_value, role_value, now, "draft_specification", canonical_json(payload)))
        report_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute("INSERT INTO record_governed_report_versions (report_id,version_number,canonical_record_reference,specification_schema_version,specification_json,specification_digest,requested_formats_json,publication_engine_version,rendering_profile,template_version,created_by,created_at,lifecycle_status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (report_id, 1, record["reference"], specification["specification_schema_version"], canonical_json(specification), digest, canonical_json(specification["requested_formats"]), specification["publication_engine_version"], specification["rendering_profile"], specification["template_version"], actor_value, now, "draft_specification"))
        version_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        event_payload = {"report_id": report_id, "version_id": version_id, "event_type": "created", "resulting_status": "draft_specification", "actor": actor_value, "actor_role": role_value, "declaration": {"acknowledged": True}}
        conn.execute("INSERT INTO record_governed_report_events (report_id,version_id,event_type,resulting_status,rationale,actor,actor_role,declaration_json,occurred_at,idempotency_key,request_payload_json) VALUES (?,?,?,?,?,?,?,?,?,?,?)", (report_id, version_id, "created", "draft_specification", "Report specification created as a deliberate internal assembly.", actor_value, role_value, '{"acknowledged":true}', now, key + ":created", canonical_json(event_payload)))
        conn.execute("RELEASE SAVEPOINT stage75_create")
        savepoint_active = False
        if _commit:
            conn.commit()
    except sqlite3.Error as exc:
        if savepoint_active:
            conn.execute("ROLLBACK TO SAVEPOINT stage75_create")
            conn.execute("RELEASE SAVEPOINT stage75_create")
        if owns_transaction:
            conn.rollback()
        if "readonly" in str(exc).lower():
            raise ValueError("governed_report_pathway_freeze_transaction_unavailable") from None
        raise
    except Exception:
        if savepoint_active:
            conn.execute("ROLLBACK TO SAVEPOINT stage75_create")
            conn.execute("RELEASE SAVEPOINT stage75_create")
        if owns_transaction:
            conn.rollback()
        raise
    return _row(conn, report_id)


def validate_pathway_report_specification(conn: sqlite3.Connection, specification: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(specification, Mapping):
        raise ValueError("governed_report_pathway_specification_invalid")
    expected = {
        "specification_schema_version", "report_type", "title", "purpose", "intended_audience",
        "distribution_class", "primary_record", "pathway_projection", "selected_documents",
        "selected_associations", "sections", "exclusions", "qualifications", "requested_formats",
        "publication_engine_version", "rendering_profile", "template_version",
    }
    if set(specification) != expected:
        raise ValueError("governed_report_pathway_specification_invalid")
    if specification.get("report_type") != PATHWAY_REPORT_TYPE or specification.get("specification_schema_version") != PATHWAY_SPECIFICATION_SCHEMA_VERSION:
        raise ValueError("governed_report_pathway_specification_invalid")
    if specification.get("distribution_class") != "internal_working":
        raise ValueError("governed_report_pathway_distribution_invalid")
    if specification.get("rendering_profile") != PATHWAY_RENDERING_PROFILE:
        raise ValueError("governed_report_pathway_rendering_profile_invalid")
    if specification.get("template_version") != PATHWAY_TEMPLATE_VERSION:
        raise ValueError("governed_report_pathway_template_version_invalid")
    if specification.get("publication_engine_version") != PUBLICATION_ENGINE_VERSION:
        raise ValueError("governed_report_publication_engine_version_invalid")
    if specification.get("selected_documents") != [] or specification.get("selected_associations") != [] or specification.get("sections") != [] or specification.get("exclusions") != []:
        raise ValueError("governed_report_pathway_authority_caller_supplied")
    _formats(specification.get("requested_formats"))
    record = specification.get("primary_record")
    if not isinstance(record, Mapping) or not record.get("reference"):
        raise ValueError("governed_report_pathway_specification_invalid")
    _validate_pathway_section(specification.get("pathway_projection"), record_reference=str(record["reference"]))
    return dict(specification)


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
    result["qualifications"] = [dict(item) for item in conn.execute("SELECT * FROM record_governed_report_qualifications WHERE report_id=? ORDER BY revision_number", (int(report_id),)).fetchall()] if _table_exists(conn, "record_governed_report_qualifications") else []
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
    if specification.get("report_type") == PATHWAY_REPORT_TYPE:
        _validate_live_pathway_identity(conn, specification)
        return
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


def create_report(conn: sqlite3.Connection, *, title: str, purpose: str, audience: str, distribution_class: str, canonical_record_reference: str, document_ids: Any, association_ids: Any, sections: Any, exclusions: Any, requested_formats: Any, rendering_profile: str, template_version: str, actor: str, actor_role: str, idempotency_key: str, report_type: str = "canonical_record_report", created_at: str | None = None, _commit: bool = True) -> dict[str, Any]:
    if str(report_type or "").strip() == PATHWAY_REPORT_TYPE:
        return _create_pathway_report_transactionally(conn, title=title, purpose=purpose, audience=audience, distribution_class=distribution_class, canonical_record_reference=canonical_record_reference, document_ids=document_ids, association_ids=association_ids, sections=sections, exclusions=exclusions, requested_formats=requested_formats, rendering_profile=rendering_profile, template_version=template_version, actor=actor, actor_role=actor_role, idempotency_key=idempotency_key, created_at=created_at, _commit=_commit)
    ensure_report_tables(conn)
    actor_value = _required(actor, "governed_report_actor_required")
    role_value = _required(actor_role, "governed_report_actor_role_required")
    key = _required(idempotency_key, "governed_report_idempotency_key_required")
    report_type_value = _required(report_type, "governed_report_type_required")
    if report_type_value not in _SUPPORTED_REPORT_TYPES:
        raise ValueError("governed_report_type_invalid")
    record = _record_snapshot(conn, canonical_record_reference)
    if report_type_value == PATHWAY_REPORT_TYPE:
        specification = _pathway_specification(conn=conn, record=record, sections=sections, exclusions=exclusions, document_ids=document_ids, association_ids=association_ids, title=title, purpose=purpose, audience=audience, distribution_class=distribution_class, requested_formats=requested_formats, rendering_profile=rendering_profile, template_version=template_version)
    else:
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
        conn.execute("INSERT INTO record_governed_reports (idempotency_key,schema_version,report_type,title,purpose,intended_audience,distribution_class,created_by,created_by_role,created_at,lifecycle_status,request_payload_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (key, SCHEMA_VERSION, specification["report_type"], specification["title"], specification["purpose"], specification["intended_audience"], specification["distribution_class"], actor_value, role_value, now, "draft_specification", canonical_json(payload)))
        report_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute("INSERT INTO record_governed_report_versions (report_id,version_number,canonical_record_reference,specification_schema_version,specification_json,specification_digest,requested_formats_json,publication_engine_version,rendering_profile,template_version,created_by,created_at,lifecycle_status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (report_id, 1, record["reference"], specification["specification_schema_version"], canonical_json(specification), digest, canonical_json(specification["requested_formats"]), specification["publication_engine_version"], specification["rendering_profile"], specification["template_version"], actor_value, now, "draft_specification"))
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
    allowed = {"draft_specification": {"assembly_reviewed", "withdrawn"}, "assembly_reviewed": {"privacy_reviewed", "withdrawn"}, "privacy_reviewed": {"redaction_reviewed", "withdrawn"}, "redaction_reviewed": {"approved_for_generation", "withdrawn"}, "approved_for_generation": {"withdrawn"}, "generation_requested": {"withdrawn"}, "validation_failed": {"approved_for_generation", "withdrawn"}, "generated": {"withdrawn"}}
    actor_value = _required(actor, "governed_report_event_actor_required"); role_value = _required(actor_role, "governed_report_event_actor_role_required"); rationale_value = _required(rationale, "governed_report_event_rationale_required")
    from api import governed_report_qualifications as qualifications
    if resulting_status in qualifications.GATE_STATUS and qualifications.configured_review_mode() == qualifications.SOLE_MODE:
        raise ValueError("governed_report_sole_confirmation_required")
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
        if resulting_status in qualifications.GATE_STATUS:
            qualifications.record_gate(conn, report_id=report_id, resulting_status=resulting_status, actor=actor_value, rationale=rationale_value, declaration=declaration, idempotency_key=key + ":qualification", mode=qualifications.INDEPENDENT_MODE, event_type=qualifications.INDEPENDENT_EVENTS[qualifications.GATE_STATUS[resulting_status]])
        conn.execute("RELEASE SAVEPOINT stage75_event")
        if _commit: conn.commit()
    except Exception:
        conn.execute("ROLLBACK TO SAVEPOINT stage75_event"); conn.execute("RELEASE SAVEPOINT stage75_event"); raise
    return _row(conn, report_id)


def record_diagnostic_retry_authorization(
    conn: sqlite3.Connection,
    *,
    report_id: int | str,
    version_id: int | str,
    predecessor_job_id: int,
    actor: str,
    actor_role: str,
    rationale: str,
    declaration: Mapping[str, Any],
    idempotency_key: str,
    payload: Mapping[str, Any],
    _commit: bool = False,
) -> dict[str, Any]:
    """Record execution authorization without re-approving the report."""
    report = _row(conn, report_id)
    if report["lifecycle_status"] != "validation_failed":
        raise ValueError("governed_report_diagnostic_retry_lifecycle_invalid")
    if int(report["versions"][-1]["id"]) != int(version_id):
        raise ValueError("governed_report_diagnostic_retry_version_invalid")
    actor_value = _required(actor, "governed_report_event_actor_required")
    role_value = _required(actor_role, "governed_report_event_actor_role_required")
    rationale_value = _required(rationale, "governed_report_diagnostic_retry_rationale_required")
    if len(rationale_value) > 4000:
        raise ValueError("governed_report_diagnostic_retry_rationale_invalid")
    if not isinstance(declaration, Mapping) or declaration != {"acknowledged": True}:
        raise ValueError("governed_report_diagnostic_retry_declaration_required")
    key = _required(idempotency_key, "governed_report_event_idempotency_key_required")
    existing = conn.execute(
        "SELECT report_id,request_payload_json FROM record_governed_report_events WHERE idempotency_key=?",
        (key,),
    ).fetchone()
    if existing:
        if json.loads(existing[1]) != dict(payload):
            raise ValueError("governed_report_diagnostic_retry_idempotency_conflict")
        return _row(conn, existing[0])
    now = utc_now()
    conn.execute("UPDATE record_governed_reports SET lifecycle_status='generation_requested' WHERE id=?", (int(report_id),))
    conn.execute(
        "UPDATE record_governed_report_versions SET lifecycle_status='generation_requested' WHERE id=?",
        (int(version_id),),
    )
    conn.execute(
        "INSERT INTO record_governed_report_events (report_id,version_id,event_type,resulting_status,rationale,actor,actor_role,declaration_json,occurred_at,idempotency_key,request_payload_json) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            int(report_id),
            int(version_id),
            "diagnostic_retry_authorized",
            "generation_requested",
            rationale_value,
            actor_value,
            role_value,
            canonical_json(dict(declaration)),
            now,
            key,
            canonical_json(dict(payload)),
        ),
    )
    if _commit:
        conn.commit()
    return _row(conn, report_id)


def record_diagnostic_retry_validation_failure(
    conn: sqlite3.Connection,
    *,
    report_id: int | str,
    version_id: int | str,
    job_id: int,
    payload: Mapping[str, Any],
    _commit: bool = False,
) -> dict[str, Any]:
    """Return a linked diagnostic retry to validation_failed after revalidation failure."""
    report = _row(conn, report_id)
    if report["lifecycle_status"] != "generation_requested" or int(report["versions"][-1]["id"]) != int(version_id):
        raise ValueError("governed_report_diagnostic_retry_lifecycle_invalid")
    key = f"stage75-diagnostic-retry-{int(job_id)}:validation-failed"
    existing = conn.execute("SELECT request_payload_json FROM record_governed_report_events WHERE idempotency_key=?", (key,)).fetchone()
    if existing is not None:
        if json.loads(existing[0]) != dict(payload):
            raise ValueError("governed_report_diagnostic_retry_idempotency_conflict")
        return _row(conn, report_id)
    now = utc_now()
    conn.execute("UPDATE record_governed_reports SET lifecycle_status='validation_failed' WHERE id=?", (int(report_id),))
    conn.execute("UPDATE record_governed_report_versions SET lifecycle_status='validation_failed' WHERE id=?", (int(version_id),))
    conn.execute(
        "INSERT INTO record_governed_report_events (report_id,version_id,event_type,resulting_status,rationale,actor,actor_role,declaration_json,occurred_at,idempotency_key,request_payload_json) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (int(report_id), int(version_id), "validation_failed", "validation_failed", "Diagnostic retry failed pre-execution revalidation.", "cde-governed-report-worker", "system_worker", '{"acknowledged":true}', now, key, canonical_json(dict(payload))),
    )
    if _commit:
        conn.commit()
    return _row(conn, report_id)


def confirm_creator_gate(conn: sqlite3.Connection, *, report_id: int | str, resulting_status: str, rationale: str, actor: str, actor_role: str, acknowledged: bool, idempotency_key: str, _commit: bool = True) -> dict[str, Any]:
    """Advance one gate under explicit sole-administrator confirmation."""
    from api import governed_report_qualifications as qualifications

    if qualifications.configured_review_mode() != qualifications.SOLE_MODE:
        raise ValueError("governed_report_sole_mode_required")
    report = _row(conn, report_id)
    allowed = {"draft_specification": "assembly_reviewed", "assembly_reviewed": "privacy_reviewed", "privacy_reviewed": "redaction_reviewed", "redaction_reviewed": "approved_for_generation"}
    if str(actor or "").strip() != str(report["created_by"]):
        raise ValueError("governed_report_sole_qualifier_must_be_creator")
    if not acknowledged:
        raise ValueError("governed_report_qualification_declaration_required")
    key = _required(idempotency_key, "governed_report_event_idempotency_key_required")
    rationale_value = _required(rationale, "governed_report_qualification_rationale_invalid")
    declaration = {"acknowledged": True, "no_independent_administrator_available": True, "application_did_not_verify_declaration": True}
    payload = {"report_id": int(report_id), "resulting_status": resulting_status, "rationale": rationale_value, "actor": str(actor), "actor_role": str(actor_role), "declaration": declaration}
    existing = conn.execute("SELECT request_payload_json FROM record_governed_report_events WHERE idempotency_key=?", (key,)).fetchone()
    if existing is not None:
        if json.loads(existing[0]) != payload:
            raise ValueError("governed_report_idempotency_conflict")
        return _row(conn, report_id)
    if allowed.get(report["lifecycle_status"]) != resulting_status:
        raise ValueError("governed_report_transition_invalid")
    _validate_generation_sources(conn, report["versions"][-1]["specification"])
    conn.execute("SAVEPOINT stage75_sole_gate")
    try:
        now = utc_now()
        event_type = qualifications.SOLE_EVENTS[qualifications.GATE_STATUS[resulting_status]]
        conn.execute("UPDATE record_governed_reports SET lifecycle_status=? WHERE id=?", (resulting_status, int(report_id)))
        conn.execute("UPDATE record_governed_report_versions SET lifecycle_status=? WHERE report_id=? AND version_number=(SELECT MAX(version_number) FROM record_governed_report_versions WHERE report_id=?)", (resulting_status, int(report_id), int(report_id)))
        conn.execute("INSERT INTO record_governed_report_events (report_id,version_id,event_type,resulting_status,rationale,actor,actor_role,declaration_json,occurred_at,idempotency_key,request_payload_json) VALUES (?,?,?,?,?,?,?,?,?,?,?)", (int(report_id), report["versions"][-1]["id"], event_type, resulting_status, rationale_value, str(actor), str(actor_role), qualifications.canonical_json(declaration), now, key, qualifications.canonical_json(payload)))
        qualifications.record_gate(conn, report_id=report_id, resulting_status=resulting_status, actor=str(actor), rationale=rationale_value, declaration=declaration, idempotency_key=key + ":qualification", mode=qualifications.SOLE_MODE, event_type=event_type)
        conn.execute("RELEASE SAVEPOINT stage75_sole_gate")
        if _commit:
            conn.commit()
    except Exception:
        conn.execute("ROLLBACK TO SAVEPOINT stage75_sole_gate")
        conn.execute("RELEASE SAVEPOINT stage75_sole_gate")
        raise
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


def generate_report(conn: sqlite3.Connection, *, report_id: int | str, actor: str, actor_role: str, idempotency_key: str, _commit: bool = True, execution_guard: Any = None, output_dir: Path | None = None, promote_to: Path | None = None, finalization_transaction: bool = False, governance_qualification: Mapping[str, Any] | None = None, post_correction_authorization_id: str | None = None) -> dict[str, Any]:
    report = _row(conn, report_id)
    actor_value = _required(actor, "governed_report_generation_actor_required"); role_value = _required(actor_role, "governed_report_generation_role_required"); key = _required(idempotency_key, "governed_report_generation_idempotency_key_required")
    version = report["versions"][-1]; spec = version["specification"]
    if specification_digest(spec) != version["specification_digest"]:
        raise ValueError("governed_report_specification_digest_mismatch")
    if "qualifications" in report:
        from api import governed_report_qualifications as qualification_store
        qualification = qualification_store.latest_final(conn, report_id)
        if qualification is None:
            raise ValueError("governed_report_qualification_required")
        stored_qualification = dict(qualification["payload"])
        stored_qualification.update({"qualification_id": int(qualification["id"]), "qualification_digest": qualification["digest"], "disclosure": qualification_store.DISCLOSURE})
        if governance_qualification is not None and (governance_qualification.get("qualification_id") != stored_qualification["qualification_id"] or governance_qualification.get("qualification_digest") != stored_qualification["qualification_digest"]):
            raise ValueError("governed_report_qualification_mismatch")
        governance_qualification = stored_qualification
    if governance_qualification is not None and governance_qualification.get("review_mode") == "sole_administrator" and spec.get("distribution_class") != "internal_working":
        raise ValueError("governed_report_sole_distribution_invalid")
    request_payload = {"version_id": version["id"], "formats": spec["requested_formats"], "actor": actor_value, "actor_role": role_value, "specification_digest": version["specification_digest"], "rendering_profile": spec["rendering_profile"], "template_version": spec["template_version"], "publication_engine_version": spec["publication_engine_version"], "qualification_id": governance_qualification.get("qualification_id") if governance_qualification else None, "qualification_digest": governance_qualification.get("qualification_digest") if governance_qualification else None}
    existing = conn.execute("SELECT * FROM record_governed_report_generation_attempts WHERE idempotency_key=?", (key,)).fetchone()
    if existing:
        if json.loads(existing["request_payload_json"]) == request_payload:
            if existing["result"] == "generated":
                return _row(conn, report_id)
            raise ValueError("governed_report_generation_failed")
        raise ValueError("governed_report_generation_idempotency_conflict")
    if post_correction_authorization_id is None and report["lifecycle_status"] not in {"approved_for_generation", "generation_requested"}:
        raise ValueError("governed_report_generation_approval_required")
    if post_correction_authorization_id is not None:
        auth = conn.execute("SELECT report_id,report_version_id,state FROM stage77_post_correction_authorizations WHERE id=?", (str(post_correction_authorization_id),)).fetchone()
        link = conn.execute("SELECT job_id FROM stage77_post_correction_execution_links WHERE authorization_id=?", (str(post_correction_authorization_id),)).fetchone()
        if report["lifecycle_status"] != "validation_failed" or auth is None or auth["state"] != "authorized" or int(auth["report_id"]) != int(report_id) or int(auth["report_version_id"]) != int(version["id"]) or link is None:
            raise ValueError("governed_report_post_correction_authorization_invalid")
    _validate_generation_sources(conn, spec)
    final_dir = REPORT_ROOT / str(report_id) / str(version["version_number"])
    target_dir = Path(output_dir) if output_dir is not None else final_dir
    if promote_to is not None:
        _assert_confined_output(REPORT_ROOT, target_dir)
        _assert_confined_output(REPORT_ROOT, Path(promote_to))
    if target_dir.exists():
        raise ValueError("governed_report_artifact_directory_exists")
    now = utc_now()
    conn.execute("SAVEPOINT stage75_generation_request")
    try:
        conn.execute("INSERT INTO record_governed_report_generation_attempts (version_id,requested_formats_json,actor,actor_role,requested_at,result,diagnostics_json,request_payload_json,idempotency_key) VALUES (?,?,?,?,?,?,?,?,?)", (version["id"], canonical_json(spec["requested_formats"]), actor_value, role_value, now, "requested", "[]", canonical_json(request_payload), key))
        if post_correction_authorization_id is None:
            conn.execute("INSERT INTO record_governed_report_events (report_id,version_id,event_type,resulting_status,rationale,actor,actor_role,declaration_json,occurred_at,idempotency_key,request_payload_json) VALUES (?,?,?,?,?,?,?,?,?,?,?)", (int(report_id), version["id"], "generation_requested", "generation_requested", "Generation requested for the approved immutable report specification.", actor_value, role_value, '{"acknowledged":true}', now, key + ":requested", canonical_json(request_payload)))
            conn.execute("UPDATE record_governed_reports SET lifecycle_status='generation_requested' WHERE id=?", (int(report_id),))
            conn.execute("UPDATE record_governed_report_versions SET lifecycle_status='generation_requested' WHERE id=?", (version["id"],))
        conn.execute("RELEASE SAVEPOINT stage75_generation_request")
    except Exception:
        conn.execute("ROLLBACK TO SAVEPOINT stage75_generation_request")
        conn.execute("RELEASE SAVEPOINT stage75_generation_request")
        raise
    try:
        from api.report_rendering import AdapterFailure, render_frozen_report
        pathway_render_model = materialize_pathway_render_model(conn, spec) if spec.get("report_type") == PATHWAY_REPORT_TYPE else None
        if governance_qualification is not None and governance_qualification.get("review_mode") == "sole_administrator":
            result = render_frozen_report(spec, version["specification_digest"], target_dir, governance_qualification, pathway_render_model=pathway_render_model)
        else:
            result = render_frozen_report(spec, version["specification_digest"], target_dir, pathway_render_model=pathway_render_model)
    except Exception as exc:
        diagnostic = None
        if isinstance(exc, AdapterFailure) or callable(getattr(exc, "diagnostic_payload", None)):
            try:
                diagnostic = validate_diagnostic(exc.diagnostic_payload())
            except Exception:
                diagnostic = None
        if diagnostic is None:
            code = bounded_code(str(exc))
            if code == "unknown":
                code = "governed_report_generation_validation_failed"
            diagnostic = make_diagnostic(phase="rendering", operation="renderer_invocation", checkpoint="entered", code=code, exc=exc, cleanup_status="unknown")
        inner_cleanup_status = diagnostic["cleanup_status"]
        diagnostics = [validate_diagnostic(diagnostic)]
        cleanup_status = _cleanup_generation_output(target_dir)
        diagnostics[0] = validate_diagnostic({**diagnostics[0], "cleanup_status": combine_cleanup_status(inner_cleanup_status, cleanup_status)})
    else:
        diagnostics = None
    if diagnostics is not None:
        conn.execute("UPDATE record_governed_report_generation_attempts SET result=?,diagnostics_json=? WHERE idempotency_key=?", ("validation_failed", canonical_json(diagnostics), key))
        conn.execute("UPDATE record_governed_reports SET lifecycle_status='validation_failed' WHERE id=?", (int(report_id),))
        conn.execute("UPDATE record_governed_report_versions SET lifecycle_status='validation_failed' WHERE id=?", (version["id"],))
        conn.execute("INSERT INTO record_governed_report_events (report_id,version_id,event_type,resulting_status,rationale,actor,actor_role,declaration_json,occurred_at,idempotency_key,request_payload_json) VALUES (?,?,?,?,?,?,?,?,?,?,?)", (int(report_id), version["id"], "validation_failed", "validation_failed", "Rendering or output validation failed.", actor_value, role_value, '{"acknowledged":true}', utc_now(), key + ":failed", canonical_json({"diagnostics": diagnostics})))
        conn.commit() if _commit else None
        raise GovernedReportGenerationFailure(diagnostics[0]) from None
    if execution_guard is not None and not execution_guard():
        _cleanup_generation_output(target_dir)
        raise ValueError("governed_report_generation_cancelled")
    try:
        _validate_generation_sources(conn, spec)
    except Exception as exc:
        cleanup_status = _cleanup_generation_output(target_dir)
        raise GovernedReportGenerationFailure(make_diagnostic(phase="revalidation", operation="generation_revalidation", checkpoint="validation", code="governed_report_generation_source_changed", exc=exc, cleanup_status=cleanup_status)) from None
    if promote_to is not None:
        promoted_dir = Path(promote_to)
        if promoted_dir.exists() or promoted_dir.is_symlink():
            cleanup_status = _cleanup_generation_output(target_dir)
            raise GovernedReportGenerationFailure(make_diagnostic(phase="output_preparation", operation="artifact_promotion", checkpoint="promotion", code="governed_report_artifact_directory_exists", cleanup_status=cleanup_status)) from None
        try:
            promoted_dir.parent.mkdir(parents=True, exist_ok=True)
            os.replace(target_dir, promoted_dir)
        except OSError as exc:
            cleanup_status = _cleanup_generation_output(target_dir)
            raise GovernedReportGenerationFailure(make_diagnostic(phase="promotion", operation="artifact_promotion", checkpoint="promotion", code="governed_report_artifact_promotion_failed", exc=exc, cleanup_status=cleanup_status)) from None
        target_dir = promoted_dir
        result = dict(result)
        result["artifacts"] = [dict(item, path=str(promoted_dir / Path(item["path"]).name)) for item in result["artifacts"]]
    try:
        _validate_generation_sources(conn, spec)
    except Exception as exc:
        cleanup_status = _cleanup_generation_output(target_dir)
        raise GovernedReportGenerationFailure(make_diagnostic(phase="revalidation", operation="generation_revalidation", checkpoint="validation", code="governed_report_generation_source_changed", exc=exc, cleanup_status=cleanup_status)) from None
    if finalization_transaction:
        if execution_guard is not None and not execution_guard():
            _cleanup_generation_output(target_dir)
            raise ValueError("governed_report_generation_cancelled")
        conn.execute("BEGIN IMMEDIATE")
        try:
            _validate_generation_sources(conn, spec)
        except Exception as exc:
            conn.rollback()
            cleanup_status = _cleanup_generation_output(target_dir)
            raise GovernedReportGenerationFailure(make_diagnostic(phase="revalidation", operation="generation_revalidation", checkpoint="finalization", code="governed_report_generation_source_changed", exc=exc, cleanup_status=cleanup_status)) from None
    try:
        conn.execute("SAVEPOINT stage75_generation_db")
        for item in result["artifacts"]:
            qualification_id = governance_qualification.get("qualification_id") if governance_qualification else None
            qualification_digest = governance_qualification.get("qualification_digest") if governance_qualification else None
            disclosure_version = governance_qualification.get("disclosure_version") if governance_qualification else None
            conn.execute("INSERT INTO record_governed_report_artifacts (version_id,format,storage_reference,sha256,size_bytes,renderer_version,template_version,generated_at,validation_state,diagnostics_json,lifecycle_status,qualification_id,qualification_digest,disclosure_version) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (version["id"], item["format"], item["path"], item["sha256"], item["size_bytes"], item["renderer_version"], spec["template_version"], now, "valid", canonical_json(result["diagnostics"]), "current", qualification_id, qualification_digest, disclosure_version))
        conn.execute("UPDATE record_governed_report_generation_attempts SET result=?,diagnostics_json=? WHERE idempotency_key=?", ("generated", canonical_json(result["diagnostics"]), key))
        conn.execute("UPDATE record_governed_reports SET lifecycle_status='generated' WHERE id=?", (int(report_id),))
        conn.execute("UPDATE record_governed_report_versions SET lifecycle_status='generated' WHERE id=?", (version["id"],))
        conn.execute("RELEASE SAVEPOINT stage75_generation_db")
    except Exception as exc:
        conn.execute("ROLLBACK TO SAVEPOINT stage75_generation_db")
        conn.execute("RELEASE SAVEPOINT stage75_generation_db")
        cleanup_status = _cleanup_generation_output(target_dir)
        diagnostic = make_diagnostic(phase="registration", operation="artifact_registration", checkpoint="registration", code="governed_report_artifact_registration_failed", exc=exc, cleanup_status=cleanup_status)
        conn.execute("UPDATE record_governed_report_generation_attempts SET result=?,diagnostics_json=? WHERE idempotency_key=?", ("validation_failed", canonical_json([diagnostic]), key))
        conn.execute("UPDATE record_governed_reports SET lifecycle_status='validation_failed' WHERE id=?", (int(report_id),))
        conn.execute("UPDATE record_governed_report_versions SET lifecycle_status='validation_failed' WHERE id=?", (version["id"],))
        if _commit: conn.commit()
        raise GovernedReportGenerationFailure(diagnostic) from None
    if _commit: conn.commit()
    return _row(conn, report_id)
