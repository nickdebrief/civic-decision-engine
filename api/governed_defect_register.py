"""Private Stage 81 governed defect and correction register.

This module records private administrative register history.
It never executes a linked correction, release, deployment, publication, or
provider action.  General report admission is disabled in this delivery: test
fixtures seed disposable databases directly, rather than crossing an
application admission boundary.  This is a restricted foundation, not an
operational intake service.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping


LIFECYCLE = frozenset({"reported", "under_assessment", "action_agreed", "awaiting_verification", "closed"})
CLASSIFICATIONS = frozenset({"unassessed", "confirmed_defect", "not_reproduced_within_stated_checks", "expected_behavior", "environment_or_invocation_issue", "enhancement_request", "duplicate", "outside_scope"})
PRIORITIES = frozenset({"P0_urgent_integrity_or_security_risk", "P1_high_material_governance_or_processing_risk", "P2_normal_bounded_assessment", "P3_improvement_or_low_materiality", "unprioritised"})
IMPACT_STATUSES = frozenset({"not_performed", "no_affected_items_identified_within_stated_assessment", "items_recorded"})
IMPACT_ITEM_STATUSES = frozenset({"potentially_affected", "assessed_affected", "assessed_unaffected", "not_yet_assessed"})
REFERENCE_TYPES = frozenset({"canonical_record", "record_version", "document", "document_version", "source_intake", "transcript_version", "correction", "patch", "git_commit", "pull_request", "deployment", "validation_artifact", "release_record"})
REFERENCE_RELATIONS = frozenset({"reported_evidence", "assessment_evidence", "authority", "action_target", "execution_claim", "execution_evidence", "verification_evidence", "impact_target", "supersedes", "revalidation_evidence"})
VALIDATION_STEPS = frozenset({"syntax_validated", "target_existence_checked", "target_identity_or_content_verified", "relationship_substantiated"})
REVALIDATION_OUTCOMES = frozenset({"not_required", "open", "deferred", "awaiting_revalidation", "revalidation_passed", "revalidation_failed", "concluded_without_passing", "superseded", "reopened"})
REVALIDATION_ACTIVE_OUTCOMES = frozenset({"open", "deferred", "awaiting_revalidation", "revalidation_failed", "reopened"})
TARGET_IDENTITY_KINDS = frozenset({"exact_reference", "snapshot_digest"})
OWNER_USERNAME_ENV = "CDE_DEFECT_REGISTER_OWNER_USERNAME"
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@-]{0,255}$")
_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _timestamp(value: Any, error: str) -> datetime:
    text = _required(value, error, maximum=64)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(error) from exc
    if parsed.tzinfo is None:
        raise ValueError(error)
    return parsed.astimezone(timezone.utc)


def _timestamp_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _required(value: Any, error: str, *, maximum: int = 4000) -> str:
    result = str(value or "").strip()
    if not result:
        raise ValueError(error)
    if len(result) > maximum:
        raise ValueError(error)
    return result


def _optional(value: Any, *, maximum: int = 4000) -> str | None:
    result = str(value or "").strip()
    if len(result) > maximum:
        raise ValueError("defect_register_field_invalid")
    return result or None


def _identifier(value: Any, error: str) -> str:
    result = _required(value, error, maximum=256)
    if not _IDENTIFIER_RE.fullmatch(result):
        raise ValueError(error)
    return result


def _key(value: Any) -> str:
    result = _required(value, "defect_register_idempotency_key_required", maximum=128)
    if not _KEY_RE.fullmatch(result):
        raise ValueError("defect_register_idempotency_key_invalid")
    return result


def _actor(value: Any) -> str:
    return _required(value, "defect_register_actor_required", maximum=256)


def _expected_version(value: Any) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("defect_register_expected_version_invalid") from exc
    if result < 0:
        raise ValueError("defect_register_expected_version_invalid")
    return result


def _enum(value: Any, choices: frozenset[str], error: str) -> str:
    result = str(value or "").strip()
    if result not in choices:
        raise ValueError(error)
    return result


def _loads(value: Any, fallback: Any) -> Any:
    try:
        return json.loads(value) if value else fallback
    except (TypeError, json.JSONDecodeError):
        return fallback


def _entry_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    result = dict(row)
    for name in ("deferral", "closure", "synthetic_attestation", "preservation_hold", "retention_review", "active_action"):
        result[name] = _loads(result.pop(f"{name}_json", None), None)
    return result


def _criteria_identity(criteria: list[str]) -> str:
    """Stable identity for the exact accepted criterion list and order."""
    return hashlib.sha256(_json(criteria).encode("utf-8")).hexdigest()


def ensure_tables(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS governed_defect_register_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entry_identifier TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            affected_component TEXT NOT NULL,
            observed_behavior TEXT NOT NULL,
            expected_behavior TEXT NOT NULL,
            expectation_source TEXT NOT NULL,
            reporter_source TEXT,
            lifecycle_state TEXT NOT NULL,
            assessment_classification TEXT NOT NULL,
            priority TEXT NOT NULL,
            owner_reference TEXT,
            impact_status TEXT NOT NULL,
            deferral_json TEXT,
            closure_json TEXT,
            preservation_hold_json TEXT,
            retention_review_json TEXT,
            active_action_json TEXT,
            synthetic_attestation_json TEXT NOT NULL,
            version INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            created_by TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            updated_by TEXT NOT NULL
        )
    """)
    columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(governed_defect_register_entries)")}
    for name in ("preservation_hold_json", "retention_review_json", "active_action_json"):
        if name not in columns:
            conn.execute(f"ALTER TABLE governed_defect_register_entries ADD COLUMN {name} TEXT")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS governed_defect_register_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entry_id INTEGER NOT NULL,
            entry_identifier TEXT NOT NULL,
            event_type TEXT NOT NULL,
            actor TEXT NOT NULL,
            occurred_at TEXT NOT NULL,
            prior_version INTEGER NOT NULL,
            resulting_version INTEGER NOT NULL,
            reason TEXT NOT NULL,
            details_json TEXT NOT NULL,
            FOREIGN KEY(entry_id) REFERENCES governed_defect_register_entries(id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS governed_defect_register_references (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entry_id INTEGER NOT NULL,
            entry_identifier TEXT NOT NULL,
            reference_type TEXT NOT NULL,
            reference_value TEXT NOT NULL,
            relation TEXT NOT NULL,
            neutral_label TEXT NOT NULL,
            supplier_identity TEXT,
            validator_identity TEXT,
            validation_steps_json TEXT NOT NULL,
            verification_binding_json TEXT,
            revalidation_binding_json TEXT,
            target_binding_json TEXT,
            supersession_binding_json TEXT,
            created_at TEXT NOT NULL,
            created_by TEXT NOT NULL,
            FOREIGN KEY(entry_id) REFERENCES governed_defect_register_entries(id)
        )
    """)
    reference_columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(governed_defect_register_references)")}
    if "verification_binding_json" not in reference_columns:
        conn.execute("ALTER TABLE governed_defect_register_references ADD COLUMN verification_binding_json TEXT")
    if "revalidation_binding_json" not in reference_columns:
        conn.execute("ALTER TABLE governed_defect_register_references ADD COLUMN revalidation_binding_json TEXT")
    if "target_binding_json" not in reference_columns:
        conn.execute("ALTER TABLE governed_defect_register_references ADD COLUMN target_binding_json TEXT")
    if "supersession_binding_json" not in reference_columns:
        conn.execute("ALTER TABLE governed_defect_register_references ADD COLUMN supersession_binding_json TEXT")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS governed_defect_register_impacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entry_id INTEGER NOT NULL,
            entry_identifier TEXT NOT NULL,
            target_reference TEXT NOT NULL,
            status TEXT NOT NULL,
            assessment_basis TEXT,
            assessment_limits TEXT,
            follow_up_action TEXT,
            owner_reference TEXT,
            review_trigger TEXT,
            outcome TEXT,
            created_at TEXT NOT NULL,
            created_by TEXT NOT NULL,
            FOREIGN KEY(entry_id) REFERENCES governed_defect_register_entries(id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS governed_defect_register_receipts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            idempotency_key TEXT NOT NULL UNIQUE,
            entry_identifier TEXT NOT NULL,
            canonical_payload_json TEXT NOT NULL,
            receipt_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS governed_defect_register_revalidations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entry_id INTEGER NOT NULL,
            entry_identifier TEXT NOT NULL,
            requirement_identifier TEXT NOT NULL UNIQUE,
            predecessor_requirement_id INTEGER,
            supersession_reference_id INTEGER,
            impact_id INTEGER NOT NULL,
            origin_action_json TEXT NOT NULL,
            execution_reference_id INTEGER NOT NULL,
            target_reference_id INTEGER NOT NULL,
            target_identity_kind TEXT NOT NULL,
            target_identity TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            assessment_scope TEXT NOT NULL,
            assessment_basis TEXT NOT NULL,
            assessment_limits TEXT NOT NULL,
            criteria_json TEXT NOT NULL,
            criteria_identity TEXT NOT NULL,
            linked_workflow_requires_approval INTEGER NOT NULL,
            authority_reference_id INTEGER,
            owner_reference TEXT NOT NULL,
            due_at TEXT,
            review_trigger TEXT,
            outcome TEXT NOT NULL,
            conclusion_json TEXT,
            outcome_details_json TEXT,
            superseded_by_requirement_id INTEGER,
            version INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            created_by TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            updated_by TEXT NOT NULL,
            FOREIGN KEY(entry_id) REFERENCES governed_defect_register_entries(id),
            FOREIGN KEY(impact_id) REFERENCES governed_defect_register_impacts(id)
        )
    """)
    revalidation_columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(governed_defect_register_revalidations)")}
    if "outcome_details_json" not in revalidation_columns:
        conn.execute("ALTER TABLE governed_defect_register_revalidations ADD COLUMN outcome_details_json TEXT")
    if "supersession_reference_id" not in revalidation_columns:
        conn.execute("ALTER TABLE governed_defect_register_revalidations ADD COLUMN supersession_reference_id INTEGER")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS governed_defect_register_revalidation_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            revalidation_id INTEGER NOT NULL,
            entry_id INTEGER NOT NULL,
            entry_identifier TEXT NOT NULL,
            event_type TEXT NOT NULL,
            actor TEXT NOT NULL,
            occurred_at TEXT NOT NULL,
            prior_version INTEGER NOT NULL,
            resulting_version INTEGER NOT NULL,
            reason TEXT NOT NULL,
            details_json TEXT NOT NULL,
            FOREIGN KEY(revalidation_id) REFERENCES governed_defect_register_revalidations(id),
            FOREIGN KEY(entry_id) REFERENCES governed_defect_register_entries(id)
        )
    """)
    for table in ("governed_defect_register_events", "governed_defect_register_references", "governed_defect_register_impacts", "governed_defect_register_revalidation_events"):
        conn.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_no_update BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT, 'defect_register_history_immutable'); END")
        conn.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_no_delete BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT, 'defect_register_history_immutable'); END")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_defect_register_events_entry ON governed_defect_register_events(entry_id, id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_defect_register_refs_entry ON governed_defect_register_references(entry_id, id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_defect_register_impacts_entry ON governed_defect_register_impacts(entry_id, id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_defect_register_revalidations_entry ON governed_defect_register_revalidations(entry_id, id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_defect_register_revalidation_events_requirement ON governed_defect_register_revalidation_events(revalidation_id, id)")


def _next_identifier(conn: sqlite3.Connection, now: str) -> str:
    day = now[:10].replace("-", "")
    prefix = f"CDE-DEF-{day}-"
    rows = conn.execute("SELECT entry_identifier FROM governed_defect_register_entries WHERE entry_identifier LIKE ?", (prefix + "%",)).fetchall()
    sequence = 0
    for row in rows:
        try:
            sequence = max(sequence, int(str(row[0]).rsplit("-", 1)[1]))
        except (ValueError, IndexError):
            continue
    return f"{prefix}{sequence + 1:03d}"


def _entry(conn: sqlite3.Connection, entry_identifier: str) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM governed_defect_register_entries WHERE entry_identifier=?", (entry_identifier,)).fetchone()
    item = _entry_row(row)
    if item is None:
        raise ValueError("defect_register_not_found")
    return item


def get_entry(conn: sqlite3.Connection, entry_identifier: str) -> dict[str, Any]:
    ensure_tables(conn)
    item = _entry(conn, _identifier(entry_identifier, "defect_register_identifier_invalid"))
    item["history"] = history(conn, item["entry_identifier"])
    item["references"] = references(conn, item["entry_identifier"])
    item["impacts"] = impacts(conn, item["entry_identifier"])
    item["revalidations"] = revalidations(conn, item["entry_identifier"])
    return item


def list_entries(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    ensure_tables(conn)
    return [_entry_row(row) or {} for row in conn.execute("SELECT * FROM governed_defect_register_entries ORDER BY id DESC").fetchall()]


def history(conn: sqlite3.Connection, entry_identifier: str) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM governed_defect_register_events WHERE entry_identifier=? ORDER BY id", (_identifier(entry_identifier, "defect_register_identifier_invalid"),)).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["details"] = _loads(item.pop("details_json"), {})
        result.append(item)
    return result


def references(conn: sqlite3.Connection, entry_identifier: str) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM governed_defect_register_references WHERE entry_identifier=? ORDER BY id", (_identifier(entry_identifier, "defect_register_identifier_invalid"),)).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["validation_steps"] = _loads(item.pop("validation_steps_json"), [])
        item["verification_binding"] = _loads(item.pop("verification_binding_json", None), None)
        item["revalidation_binding"] = _loads(item.pop("revalidation_binding_json", None), None)
        item["target_binding"] = _loads(item.pop("target_binding_json", None), None)
        item["supersession_binding"] = _loads(item.pop("supersession_binding_json", None), None)
        result.append(item)
    return result


def _reference_for_entry(conn: sqlite3.Connection, item: Mapping[str, Any], reference_id: Any, *, relation: str) -> dict[str, Any]:
    try:
        identifier = int(reference_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("defect_register_reference_binding_invalid") from exc
    row = conn.execute(
        "SELECT * FROM governed_defect_register_references WHERE id=? AND entry_id=? AND relation=?",
        (identifier, int(item["id"]), relation),
    ).fetchone()
    if row is None:
        raise ValueError("defect_register_reference_binding_invalid")
    result = dict(row)
    result["validation_steps"] = _loads(result.pop("validation_steps_json"), [])
    result["verification_binding"] = _loads(result.pop("verification_binding_json", None), None)
    result["revalidation_binding"] = _loads(result.pop("revalidation_binding_json", None), None)
    result["target_binding"] = _loads(result.pop("target_binding_json", None), None)
    result["supersession_binding"] = _loads(result.pop("supersession_binding_json", None), None)
    return result


def _references_for_entry(conn: sqlite3.Connection, item: Mapping[str, Any], reference_ids: Any) -> list[int]:
    if not isinstance(reference_ids, list) or not reference_ids or len(reference_ids) > 32:
        raise ValueError("defect_register_revalidation_evidence_required")
    result: list[int] = []
    for raw in reference_ids:
        try:
            reference_id = int(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError("defect_register_revalidation_evidence_required") from exc
        row = conn.execute(
            "SELECT 1 FROM governed_defect_register_references WHERE id=? AND entry_id=?",
            (reference_id, int(item["id"])),
        ).fetchone()
        if row is None or reference_id in result:
            raise ValueError("defect_register_revalidation_evidence_required")
        result.append(reference_id)
    return result


def _reference_has_check(reference: Mapping[str, Any], step_name: str) -> bool:
    return any(
        isinstance(step, Mapping) and step.get("step") == step_name and step.get("status") == "passed"
        for step in reference.get("validation_steps", [])
    )


def _criteria(value: Any) -> list[str]:
    if not isinstance(value, list) or not value or len(value) > 32:
        raise ValueError("defect_register_acceptance_criteria_invalid")
    result = [_required(item, "defect_register_acceptance_criteria_invalid", maximum=512) for item in value]
    if len(set(result)) != len(result):
        raise ValueError("defect_register_acceptance_criteria_invalid")
    return result


def _verification_binding(value: Any, *, action: Mapping[str, Any] | None,
                          reference_type: str, reference_value: str,
                          lifecycle_state: str) -> dict[str, Any]:
    """Normalize an immutable verification-artifact binding for the active action."""
    if not isinstance(value, Mapping) or not action or lifecycle_state != "awaiting_verification":
        raise ValueError("defect_register_verification_binding_invalid")
    if action.get("execution_status") != "execution_substantiated":
        raise ValueError("defect_register_verification_binding_invalid")
    try:
        agreed_version = int(value.get("action_agreed_version"))
        execution_reference_id = int(value.get("execution_reference_id"))
    except (TypeError, ValueError) as exc:
        raise ValueError("defect_register_verification_binding_invalid") from exc
    binding = {
        "action_id": _required(value.get("action_id"), "defect_register_verification_binding_invalid", maximum=128),
        "action_agreed_version": agreed_version,
        "acceptance_criteria_identity": _required(value.get("acceptance_criteria_identity"), "defect_register_verification_binding_invalid", maximum=128),
        "execution_reference_id": execution_reference_id,
        "artifact_reference_type": _required(value.get("artifact_reference_type"), "defect_register_verification_binding_invalid", maximum=128),
        "artifact_reference_value": _identifier(value.get("artifact_reference_value"), "defect_register_verification_binding_invalid"),
    }
    if (binding["action_id"] != action.get("action_id")
            or binding["action_agreed_version"] != action.get("agreed_version")
            or binding["acceptance_criteria_identity"] != action.get("acceptance_criteria_identity")
            or binding["execution_reference_id"] != action.get("execution_reference_id")
            or binding["artifact_reference_type"] != reference_type
            or binding["artifact_reference_value"] != reference_value):
        raise ValueError("defect_register_verification_binding_mismatch")
    return binding


def _target_binding(value: Any, *, reference_type: str, reference_value: str) -> dict[str, Any]:
    """Normalize immutable target-observation evidence carried by an impact target.

    A digest is only useful here when the retained bounded reference explicitly
    identifies both its target and the observed content identity.  This function
    deliberately does not fetch content or copy it into the register.
    """
    if not isinstance(value, Mapping):
        raise ValueError("defect_register_revalidation_target_binding_invalid")
    identity_kind = _enum(value.get("identity_kind"), TARGET_IDENTITY_KINDS,
                          "defect_register_revalidation_target_binding_invalid")
    identity = _identifier(value.get("identity"), "defect_register_revalidation_target_binding_invalid")
    if identity_kind == "exact_reference" and identity != reference_value:
        raise ValueError("defect_register_revalidation_target_binding_mismatch")
    if identity_kind == "snapshot_digest" and not re.fullmatch(r"[0-9a-f]{64}", identity):
        raise ValueError("defect_register_revalidation_target_binding_invalid")
    if (_enum(value.get("target_reference_type"), REFERENCE_TYPES,
              "defect_register_revalidation_target_binding_invalid") != reference_type
            or _identifier(value.get("target_reference_value"),
                           "defect_register_revalidation_target_binding_invalid") != reference_value):
        raise ValueError("defect_register_revalidation_target_binding_mismatch")
    return {
        "target_reference_type": reference_type,
        "target_reference_value": reference_value,
        "identity_kind": identity_kind,
        "identity": identity,
        "observed_at": _timestamp_text(_timestamp(
            value.get("observed_at"), "defect_register_revalidation_observation_time_invalid")),
    }


def _supersession_binding(conn: sqlite3.Connection, item: Mapping[str, Any], value: Any,
                          *, reference_type: str, reference_value: str) -> dict[str, Any]:
    """Bind a passive later-correction reference to one exact predecessor."""
    if not isinstance(value, Mapping):
        raise ValueError("defect_register_revalidation_supersession_binding_invalid")
    predecessor = _revalidation_for_entry(conn, item, value.get("predecessor_requirement_identifier"))
    origin = predecessor["origin_action"]
    successor_origin = _origin_action(item)
    binding = {
        "predecessor_requirement_identifier": predecessor["requirement_identifier"],
        "predecessor_origin_action_id": _required(
            value.get("predecessor_origin_action_id"),
            "defect_register_revalidation_supersession_binding_invalid", maximum=128),
        "successor_origin_action_id": _required(
            value.get("successor_origin_action_id"),
            "defect_register_revalidation_supersession_binding_invalid", maximum=128),
        "later_correction_reference_type": _enum(
            value.get("later_correction_reference_type"), REFERENCE_TYPES,
            "defect_register_revalidation_supersession_binding_invalid"),
        "later_correction_reference_value": _identifier(
            value.get("later_correction_reference_value"),
            "defect_register_revalidation_supersession_binding_invalid"),
    }
    if (binding["predecessor_origin_action_id"] != origin.get("action_id")
            or binding["successor_origin_action_id"] != successor_origin.get("action_id")
            or binding["later_correction_reference_type"] != reference_type
            or binding["later_correction_reference_value"] != reference_value
            or binding["later_correction_reference_value"] == origin.get("action_id")):
        raise ValueError("defect_register_revalidation_supersession_binding_mismatch")
    return binding


def impacts(conn: sqlite3.Connection, entry_identifier: str) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute("SELECT * FROM governed_defect_register_impacts WHERE entry_identifier=? ORDER BY id", (_identifier(entry_identifier, "defect_register_identifier_invalid"),)).fetchall()]


def _revalidation_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    item = dict(row)
    item["origin_action"] = _loads(item.pop("origin_action_json"), {})
    item["criteria"] = _loads(item.pop("criteria_json"), [])
    item["conclusion"] = _loads(item.pop("conclusion_json", None), None)
    item["outcome_details"] = _loads(item.pop("outcome_details_json", None), None)
    item["linked_workflow_requires_approval"] = bool(item["linked_workflow_requires_approval"])
    return item


def revalidations(conn: sqlite3.Connection, entry_identifier: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM governed_defect_register_revalidations WHERE entry_identifier=? ORDER BY id",
        (_identifier(entry_identifier, "defect_register_identifier_invalid"),),
    ).fetchall()
    return [_revalidation_row(row) or {} for row in rows]


def revalidation_history(conn: sqlite3.Connection, requirement_identifier: Any) -> list[dict[str, Any]]:
    identifier = _identifier(requirement_identifier, "defect_register_revalidation_identifier_invalid")
    rows = conn.execute(
        "SELECT * FROM governed_defect_register_revalidation_events WHERE revalidation_id=(SELECT id FROM governed_defect_register_revalidations WHERE requirement_identifier=?) ORDER BY id",
        (identifier,),
    ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["details"] = _loads(item.pop("details_json"), {})
        result.append(item)
    return result


def _receipt(conn: sqlite3.Connection, key: str, canonical: Mapping[str, Any]) -> dict[str, Any] | None:
    row = conn.execute("SELECT canonical_payload_json, receipt_json FROM governed_defect_register_receipts WHERE idempotency_key=?", (key,)).fetchone()
    if row is None:
        return None
    if str(row[0]) != _json(canonical):
        raise ValueError("defect_register_idempotency_conflict")
    result = _loads(row[1], {})
    result["historical_receipt"] = True
    return result


def _event(conn: sqlite3.Connection, item: Mapping[str, Any], *, event_type: str, actor: str, reason: str, prior_version: int, resulting_version: int, details: Mapping[str, Any]) -> int:
    cursor = conn.execute("INSERT INTO governed_defect_register_events (entry_id,entry_identifier,event_type,actor,occurred_at,prior_version,resulting_version,reason,details_json) VALUES (?,?,?,?,?,?,?,?,?)", (int(item["id"]), item["entry_identifier"], event_type, actor, utc_now(), prior_version, resulting_version, reason, _json(details)))
    return int(cursor.lastrowid)


def _owner_actor(actor: str) -> None:
    configured = str(os.getenv(OWNER_USERNAME_ENV) or "").strip()
    if not configured:
        raise ValueError("defect_register_owner_authority_unconfigured")
    if actor != configured:
        raise ValueError("defect_register_owner_authority_required")


def create_entry(conn: sqlite3.Connection, *, title: Any, description: Any, affected_component: Any, observed_behavior: Any, expected_behavior: Any, expectation_source: Any, reporter_source: Any, actor: Any, expected_version: Any, idempotency_key: Any, synthetic_attestation: Any) -> dict[str, Any]:
    """Reject operational intake pending the approved sensitive-admission work.

    The parameters remain temporarily for a stable, explicit rejection at
    former callers.  They are not inspected, stored, or treated as a bypass.
    Synthetic coverage seeds isolated disposable databases in its test module.
    """
    del conn, title, description, affected_component, observed_behavior, expected_behavior
    del expectation_source, reporter_source, actor, expected_version, idempotency_key, synthetic_attestation
    raise ValueError("defect_register_report_admission_disabled")


def _mutate(conn: sqlite3.Connection, *, entry_identifier: Any, actor: Any, expected_version: Any, idempotency_key: Any, operation: str, reason: Any, payload: Mapping[str, Any], apply: Callable[[dict[str, Any], int], tuple[dict[str, Any], dict[str, Any]]]) -> dict[str, Any]:
    ensure_tables(conn)
    identifier = _identifier(entry_identifier, "defect_register_identifier_invalid")
    actor_value = _actor(actor)
    expected = _expected_version(expected_version)
    key = _key(idempotency_key)
    canonical = {"operation": operation, "entry_identifier": identifier, "actor": actor_value, "expected_version": expected, "reason": _required(reason, "defect_register_reason_required"), **payload}
    conn.execute("BEGIN IMMEDIATE")
    try:
        replay = _receipt(conn, key, canonical)
        if replay is not None:
            conn.rollback()
            return replay
        item = _entry(conn, identifier)
        if int(item["version"]) != expected:
            raise ValueError("defect_register_version_conflict")
        updates, details = apply(item, expected + 1)
        if not updates:
            raise ValueError("defect_register_mutation_invalid")
        columns = list(updates) + ["version", "updated_at", "updated_by"]
        values = [updates[key] for key in updates] + [expected + 1, utc_now(), actor_value, int(item["id"])]
        conn.execute(f"UPDATE governed_defect_register_entries SET {','.join(f'{column}=?' for column in columns)} WHERE id=?", values)
        event_id = _event(conn, item, event_type=operation, actor=actor_value, reason=canonical["reason"], prior_version=expected, resulting_version=expected + 1, details=details)
        receipt = {"entry_identifier": identifier, "operation": operation, "event_id": event_id, "resulting_version": expected + 1, "historical_receipt": False}
        conn.execute("INSERT INTO governed_defect_register_receipts (idempotency_key,entry_identifier,canonical_payload_json,receipt_json,created_at) VALUES (?,?,?,?,?)", (key, identifier, _json(canonical), _json(receipt), utc_now()))
        conn.commit()
        return receipt
    except Exception:
        conn.rollback()
        raise


def assess(conn: sqlite3.Connection, *, entry_identifier: Any, classification: Any, assessment_reason: Any, checked_scope: Any, limitations: Any, actor: Any, expected_version: Any, idempotency_key: Any) -> dict[str, Any]:
    value = _enum(classification, CLASSIFICATIONS - {"unassessed"}, "defect_register_classification_invalid")
    scope = _required(checked_scope, "defect_register_checked_scope_required")
    limits = _optional(limitations)
    def apply(item: dict[str, Any], _next: int):
        lifecycle = "under_assessment" if item["lifecycle_state"] == "reported" else item["lifecycle_state"]
        return {"assessment_classification": value, "lifecycle_state": lifecycle}, {"classification": value, "checked_scope": scope, "limitations": limits}
    return _mutate(conn, entry_identifier=entry_identifier, actor=actor, expected_version=expected_version, idempotency_key=idempotency_key, operation="assessment_recorded", reason=assessment_reason, payload={"classification": value, "checked_scope": scope, "limitations": limits}, apply=apply)


def set_owner_priority_deferral(conn: sqlite3.Connection, *, entry_identifier: Any, owner_reference: Any = None, priority: Any = None, deferral: Mapping[str, Any] | None = None, clear_deferral: bool = False, actor: Any, expected_version: Any, idempotency_key: Any, reason: Any) -> dict[str, Any]:
    if priority is not None:
        priority = _enum(priority, PRIORITIES, "defect_register_priority_invalid")
    owner = _optional(owner_reference, maximum=256) if owner_reference is not None else None
    normalized_deferral = None
    if deferral is not None:
        if not isinstance(deferral, Mapping): raise ValueError("defect_register_deferral_invalid")
        normalized_deferral = {"owner_reference": _required(deferral.get("owner_reference"), "defect_register_deferral_owner_required", maximum=256), "reason": _required(deferral.get("reason"), "defect_register_deferral_reason_required"), "review_on": _optional(deferral.get("review_on"), maximum=128), "review_trigger": _optional(deferral.get("review_trigger"), maximum=512)}
        if not normalized_deferral["review_on"] and not normalized_deferral["review_trigger"]: raise ValueError("defect_register_deferral_review_required")
        if normalized_deferral["review_on"]:
            normalized_deferral["review_on"] = _timestamp_text(_timestamp(normalized_deferral["review_on"], "defect_register_deferral_review_invalid"))
    if priority is None and owner_reference is None and deferral is None and not clear_deferral: raise ValueError("defect_register_mutation_invalid")
    def apply(item: dict[str, Any], _next: int):
        updates: dict[str, Any] = {}
        if priority is not None: updates["priority"] = priority
        if owner_reference is not None: updates["owner_reference"] = owner
        if deferral is not None: updates["deferral_json"] = _json(normalized_deferral)
        if clear_deferral: updates["deferral_json"] = None
        return updates, {"old_owner_reference": item.get("owner_reference"), "new_owner_reference": updates.get("owner_reference", item.get("owner_reference")), "old_priority": item.get("priority"), "new_priority": updates.get("priority", item.get("priority")), "deferral": normalized_deferral, "deferral_cleared": clear_deferral}
    return _mutate(conn, entry_identifier=entry_identifier, actor=actor, expected_version=expected_version, idempotency_key=idempotency_key, operation="ownership_priority_deferral_updated", reason=reason, payload={"owner_reference": owner, "priority": priority, "deferral": normalized_deferral, "clear_deferral": bool(clear_deferral)}, apply=apply)


_TRANSITIONS = {"reported": {"under_assessment"}, "under_assessment": {"action_agreed", "closed"}, "action_agreed": {"awaiting_verification", "under_assessment"}, "awaiting_verification": {"closed", "under_assessment"}, "closed": {"under_assessment"}}


def transition(conn: sqlite3.Connection, *, entry_identifier: Any, new_state: Any, reason: Any, actor: Any, expected_version: Any, idempotency_key: Any, action_scope: Any = None, acceptance_criteria: Any = None, action_reference_id: Any = None, execution_status: Any = None, execution_reference_id: Any = None, verification: Mapping[str, Any] | None = None, closure_outcome: Any = None) -> dict[str, Any]:
    target = _enum(new_state, LIFECYCLE, "defect_register_lifecycle_invalid")
    action_scope_value = _optional(action_scope)
    criteria = _criteria(acceptance_criteria) if acceptance_criteria is not None else None
    execution = _optional(execution_status, maximum=128)
    outcome = _optional(closure_outcome, maximum=128)
    verified = None
    if verification is not None:
        if not isinstance(verification, Mapping): raise ValueError("defect_register_verification_invalid")
        if "review_status" in verification or "reviewer_identity" in verification:
            raise ValueError("defect_register_unverified_claim_elevation_rejected")
        results = verification.get("criteria_results")
        if not isinstance(results, Mapping):
            raise ValueError("defect_register_verification_criteria_required")
        verified = {
            "action_id": _required(verification.get("action_id"), "defect_register_verification_action_required", maximum=128),
            "execution_reference_id": verification.get("execution_reference_id"),
            "artifact_reference_id": verification.get("artifact_reference_id"),
            "criteria_results": {str(key): value for key, value in results.items()},
            "limitations": _optional(verification.get("limitations")),
            "review_claim_unverified": _optional(verification.get("review_claim_unverified"), maximum=256),
        }
    def apply(item: dict[str, Any], _next: int):
        current = item["lifecycle_state"]
        if target not in _TRANSITIONS.get(current, set()): raise ValueError("defect_register_transition_invalid")
        details: dict[str, Any] = {"prior_state": current, "new_state": target, "action_scope": action_scope_value, "acceptance_criteria": criteria, "action_reference_id": action_reference_id, "execution_status": execution, "execution_reference_id": execution_reference_id, "verification": verified, "closure_outcome": outcome}
        if target == "action_agreed":
            if item["assessment_classification"] == "unassessed" or not action_scope_value or not criteria:
                raise ValueError("defect_register_action_agreed_requirements_missing")
            action_ref = _reference_for_entry(conn, item, action_reference_id, relation="action_target")
            if not _reference_has_check(action_ref, "relationship_substantiated"):
                raise ValueError("defect_register_action_reference_unsubstantiated")
            action = {"action_id": f"action-v{_next}", "scope": action_scope_value, "acceptance_criteria": criteria,
                      "acceptance_criteria_identity": _criteria_identity(criteria),
                      "action_reference_id": int(action_ref["id"]), "agreed_version": _next}
        else:
            action = item.get("active_action")
        if target == "awaiting_verification":
            if execution not in {"execution_reported", "execution_substantiated"} or not action:
                raise ValueError("defect_register_execution_status_invalid")
            execution_ref = _reference_for_entry(conn, item, execution_reference_id, relation="execution_evidence")
            if execution == "execution_substantiated" and not _reference_has_check(execution_ref, "relationship_substantiated"):
                raise ValueError("defect_register_execution_reference_unsubstantiated")
            action = {**action, "execution_reference_id": int(execution_ref["id"]), "execution_status": execution}
        updates: dict[str, Any] = {"lifecycle_state": target}
        if target == "closed":
            if not outcome: raise ValueError("defect_register_closure_outcome_required")
            if outcome == "correction_verified":
                if (execution != "execution_substantiated" or not verified or not action
                        or action.get("execution_status") != "execution_substantiated"):
                    raise ValueError("defect_register_verified_closure_requirements_missing")
                if verified["action_id"] != action["action_id"]:
                    raise ValueError("defect_register_verification_action_stale")
                if verified["execution_reference_id"] != action.get("execution_reference_id"):
                    raise ValueError("defect_register_verification_execution_mismatch")
                execution_ref = _reference_for_entry(conn, item, verified["execution_reference_id"], relation="execution_evidence")
                artifact_ref = _reference_for_entry(conn, item, verified["artifact_reference_id"], relation="verification_evidence")
                if not _reference_has_check(execution_ref, "relationship_substantiated") or not _reference_has_check(artifact_ref, "target_identity_or_content_verified") or not _reference_has_check(artifact_ref, "relationship_substantiated"):
                    raise ValueError("defect_register_verified_closure_requirements_missing")
                binding = artifact_ref.get("verification_binding")
                if not isinstance(binding, Mapping) or (
                        binding.get("action_id") != action.get("action_id")
                        or binding.get("action_agreed_version") != action.get("agreed_version")
                        or binding.get("acceptance_criteria_identity") != action.get("acceptance_criteria_identity")
                        or binding.get("execution_reference_id") != action.get("execution_reference_id")
                        or binding.get("artifact_reference_type") != artifact_ref.get("reference_type")
                        or binding.get("artifact_reference_value") != artifact_ref.get("reference_value")):
                    raise ValueError("defect_register_verification_binding_mismatch")
                if set(verified["criteria_results"]) != set(action["acceptance_criteria"]) or any(value != "passed" for value in verified["criteria_results"].values()):
                    raise ValueError("defect_register_verification_criteria_incomplete")
            if current == "under_assessment" and item["assessment_classification"] == "unassessed": raise ValueError("defect_register_closure_assessment_required")
            updates["closure_json"] = _json({"outcome": outcome, "verification": verified, "execution_status": execution, "closed_at": utc_now()})
            updates["deferral_json"] = None
        if target in {"action_agreed", "awaiting_verification"}: updates["active_action_json"] = _json(action)
        if target == "under_assessment" and current in {"closed", "action_agreed", "awaiting_verification"}:
            updates["active_action_json"] = None
        return updates, details
    return _mutate(conn, entry_identifier=entry_identifier, actor=actor, expected_version=expected_version, idempotency_key=idempotency_key, operation="lifecycle_transition", reason=reason, payload={"new_state": target, "action_scope": action_scope_value, "acceptance_criteria": criteria, "action_reference_id": action_reference_id, "execution_status": execution, "execution_reference_id": execution_reference_id, "verification": verified, "closure_outcome": outcome}, apply=apply)


def add_reference(conn: sqlite3.Connection, *, entry_identifier: Any, reference_type: Any, reference_value: Any, relation: Any, neutral_label: Any, supplier_identity: Any, validation_steps: Any, actor: Any, expected_version: Any, idempotency_key: Any, reason: Any, verification_binding: Mapping[str, Any] | None = None, revalidation_binding: Mapping[str, Any] | None = None, target_binding: Mapping[str, Any] | None = None, supersession_binding: Mapping[str, Any] | None = None) -> dict[str, Any]:
    ref_type = _enum(reference_type, REFERENCE_TYPES, "defect_register_reference_type_invalid")
    relation_value = _enum(relation, REFERENCE_RELATIONS, "defect_register_reference_relation_invalid")
    value = _identifier(reference_value, "defect_register_reference_value_invalid")
    label = _required(neutral_label, "defect_register_reference_label_required", maximum=256)
    supplied = _optional(supplier_identity, maximum=256)
    if relation_value != "verification_evidence" and verification_binding is not None:
        raise ValueError("defect_register_verification_binding_invalid")
    if relation_value == "verification_evidence" and not isinstance(verification_binding, Mapping):
        raise ValueError("defect_register_verification_binding_invalid")
    if relation_value != "revalidation_evidence" and revalidation_binding is not None:
        raise ValueError("defect_register_revalidation_binding_invalid")
    if relation_value == "revalidation_evidence" and not isinstance(revalidation_binding, Mapping):
        raise ValueError("defect_register_revalidation_binding_invalid")
    if relation_value != "impact_target" and target_binding is not None:
        raise ValueError("defect_register_revalidation_target_binding_invalid")
    if relation_value == "impact_target" and not isinstance(target_binding, Mapping):
        raise ValueError("defect_register_revalidation_target_binding_invalid")
    if relation_value != "supersedes" and supersession_binding is not None:
        raise ValueError("defect_register_revalidation_supersession_binding_invalid")
    if relation_value == "supersedes" and not isinstance(supersession_binding, Mapping):
        raise ValueError("defect_register_revalidation_supersession_binding_invalid")
    if not isinstance(validation_steps, list): raise ValueError("defect_register_validation_steps_invalid")
    steps = []
    for raw in validation_steps:
        if not isinstance(raw, Mapping): raise ValueError("defect_register_validation_steps_invalid")
        if "validator_identity" in raw or "validator_status" in raw:
            raise ValueError("defect_register_unverified_claim_elevation_rejected")
        step = _enum(raw.get("step"), VALIDATION_STEPS, "defect_register_validation_step_invalid")
        status = _enum(raw.get("status"), frozenset({"passed", "failed", "not_performed"}), "defect_register_validation_status_invalid")
        steps.append({"step": step, "status": status,
                      "validator_claim_unverified": _optional(raw.get("validator_claim_unverified"), maximum=256),
                      "validated_at": _timestamp_text(_timestamp(raw.get("validated_at"), "defect_register_validation_time_required")),
                      "limits": _optional(raw.get("limits"))})
    # References are children but still need an attributable parent version/event.
    return _mutate_reference(conn, entry_identifier=entry_identifier, actor=actor, expected_version=expected_version, idempotency_key=idempotency_key, reason=reason, payload={"reference_type": ref_type, "reference_value": value, "relation": relation_value, "neutral_label": label, "supplier_identity": supplied, "validation_steps": steps, "verification_binding": dict(verification_binding) if verification_binding is not None else None, "revalidation_binding": dict(revalidation_binding) if revalidation_binding is not None else None, "target_binding": dict(target_binding) if target_binding is not None else None, "supersession_binding": dict(supersession_binding) if supersession_binding is not None else None})


def _mutate_reference(conn: sqlite3.Connection, *, entry_identifier: Any, actor: Any, expected_version: Any, idempotency_key: Any, reason: Any, payload: Mapping[str, Any]) -> dict[str, Any]:
    # Separate implementation because child write precedes parent event in one transaction.
    ensure_tables(conn); identifier = _identifier(entry_identifier, "defect_register_identifier_invalid"); actor_value = _actor(actor); expected = _expected_version(expected_version); key = _key(idempotency_key)
    canonical = {"operation": "reference_added", "entry_identifier": identifier, "actor": actor_value, "expected_version": expected, "reason": _required(reason, "defect_register_reason_required"), **payload}
    conn.execute("BEGIN IMMEDIATE")
    try:
        replay = _receipt(conn, key, canonical)
        if replay is not None: conn.rollback(); return replay
        item = _entry(conn, identifier)
        if int(item["version"]) != expected: raise ValueError("defect_register_version_conflict")
        steps = [{**step, "recorded_by_actor": actor_value} for step in payload["validation_steps"]]
        binding = None
        if payload["relation"] == "verification_evidence":
            binding = _verification_binding(payload["verification_binding"], action=item.get("active_action"),
                                            reference_type=payload["reference_type"], reference_value=payload["reference_value"],
                                            lifecycle_state=item["lifecycle_state"])
        revalidation_binding = None
        if payload["relation"] == "revalidation_evidence":
            revalidation_binding = _revalidation_binding(conn, item, payload["revalidation_binding"], payload["reference_type"], payload["reference_value"])
        target_binding = None
        if payload["relation"] == "impact_target":
            target_binding = _target_binding(payload["target_binding"], reference_type=payload["reference_type"], reference_value=payload["reference_value"])
        supersession_binding = None
        if payload["relation"] == "supersedes":
            supersession_binding = _supersession_binding(conn, item, payload["supersession_binding"], reference_type=payload["reference_type"], reference_value=payload["reference_value"])
        cursor = conn.execute("INSERT INTO governed_defect_register_references (entry_id,entry_identifier,reference_type,reference_value,relation,neutral_label,supplier_identity,validator_identity,validation_steps_json,verification_binding_json,revalidation_binding_json,target_binding_json,supersession_binding_json,created_at,created_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (int(item["id"]), identifier, payload["reference_type"], payload["reference_value"], payload["relation"], payload["neutral_label"], payload["supplier_identity"], None, _json(steps), _json(binding) if binding is not None else None, _json(revalidation_binding) if revalidation_binding is not None else None, _json(target_binding) if target_binding is not None else None, _json(supersession_binding) if supersession_binding is not None else None, utc_now(), actor_value))
        conn.execute("UPDATE governed_defect_register_entries SET version=?,updated_at=?,updated_by=? WHERE id=?", (expected + 1, utc_now(), actor_value, int(item["id"])))
        event_id = _event(conn, item, event_type="reference_added", actor=actor_value, reason=canonical["reason"], prior_version=expected, resulting_version=expected + 1, details={"reference_id": int(cursor.lastrowid), "relation": payload["relation"], "validation_steps": steps, "verification_binding": binding, "revalidation_binding": revalidation_binding, "target_binding": target_binding, "supersession_binding": supersession_binding})
        receipt = {"entry_identifier": identifier, "operation": "reference_added", "event_id": event_id, "resulting_version": expected + 1, "historical_receipt": False}
        conn.execute("INSERT INTO governed_defect_register_receipts (idempotency_key,entry_identifier,canonical_payload_json,receipt_json,created_at) VALUES (?,?,?,?,?)", (key, identifier, _json(canonical), _json(receipt), utc_now()))
        conn.commit(); return receipt
    except Exception:
        conn.rollback(); raise


def add_impact(conn: sqlite3.Connection, *, entry_identifier: Any, target_reference: Any, status: Any, assessment_basis: Any = None, assessment_limits: Any = None, follow_up_action: Any = None, owner_reference: Any = None, review_trigger: Any = None, actor: Any, expected_version: Any, idempotency_key: Any, reason: Any) -> dict[str, Any]:
    state = _enum(status, IMPACT_ITEM_STATUSES, "defect_register_impact_status_invalid")
    target = _identifier(target_reference, "defect_register_impact_target_invalid")
    basis, limits = _optional(assessment_basis), _optional(assessment_limits)
    follow_up, owner, trigger = _optional(follow_up_action), _optional(owner_reference, maximum=256), _optional(review_trigger, maximum=512)
    if state == "assessed_unaffected" and (not basis or not limits):
        raise ValueError("defect_register_impact_basis_and_limits_required")
    needed = state in {"potentially_affected", "assessed_affected"}
    if needed and (not follow_up or not owner or not trigger): raise ValueError("defect_register_impact_follow_up_required")
    payload = {"target_reference": target, "status": state, "assessment_basis": basis, "assessment_limits": limits, "follow_up_action": follow_up, "owner_reference": owner, "review_trigger": trigger}
    return _mutate_impact(conn, entry_identifier=entry_identifier, actor=actor, expected_version=expected_version, idempotency_key=idempotency_key, reason=reason, payload=payload)


def _mutate_impact(conn: sqlite3.Connection, *, entry_identifier: Any, actor: Any, expected_version: Any, idempotency_key: Any, reason: Any, payload: Mapping[str, Any]) -> dict[str, Any]:
    ensure_tables(conn); identifier = _identifier(entry_identifier, "defect_register_identifier_invalid"); actor_value = _actor(actor); expected = _expected_version(expected_version); key = _key(idempotency_key)
    canonical = {"operation": "impact_recorded", "entry_identifier": identifier, "actor": actor_value, "expected_version": expected, "reason": _required(reason, "defect_register_reason_required"), **payload}
    conn.execute("BEGIN IMMEDIATE")
    try:
        replay = _receipt(conn, key, canonical)
        if replay is not None: conn.rollback(); return replay
        item = _entry(conn, identifier)
        if int(item["version"]) != expected: raise ValueError("defect_register_version_conflict")
        cursor = conn.execute("INSERT INTO governed_defect_register_impacts (entry_id,entry_identifier,target_reference,status,assessment_basis,assessment_limits,follow_up_action,owner_reference,review_trigger,outcome,created_at,created_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (int(item["id"]), identifier, payload["target_reference"], payload["status"], payload["assessment_basis"], payload["assessment_limits"], payload["follow_up_action"], payload["owner_reference"], payload["review_trigger"], None, utc_now(), actor_value))
        conn.execute("UPDATE governed_defect_register_entries SET version=?,impact_status=?,updated_at=?,updated_by=? WHERE id=?", (expected + 1, "items_recorded", utc_now(), actor_value, int(item["id"])))
        event_id = _event(conn, item, event_type="impact_recorded", actor=actor_value, reason=canonical["reason"], prior_version=expected, resulting_version=expected + 1, details={"impact_id": int(cursor.lastrowid), "status": payload["status"]})
        receipt = {"entry_identifier": identifier, "operation": "impact_recorded", "event_id": event_id, "resulting_version": expected + 1, "historical_receipt": False}
        conn.execute("INSERT INTO governed_defect_register_receipts (idempotency_key,entry_identifier,canonical_payload_json,receipt_json,created_at) VALUES (?,?,?,?,?)", (key, identifier, _json(canonical), _json(receipt), utc_now()))
        conn.commit(); return receipt
    except Exception:
        conn.rollback(); raise


def set_hold(conn: sqlite3.Connection, *, entry_identifier: Any, active: bool, scope: Any, review_date: Any, reason: Any, actor: Any, expected_version: Any, idempotency_key: Any) -> dict[str, Any]:
    _owner_actor(_actor(actor))
    hold = {"active": bool(active), "scope": _required(scope, "defect_register_hold_scope_required", maximum=512), "review_date": _required(review_date, "defect_register_hold_review_required", maximum=64)}
    def apply(item: dict[str, Any], _next: int):
        return {"preservation_hold_json": _json(hold)}, {"hold": hold}
    return _mutate(conn, entry_identifier=entry_identifier, actor=actor, expected_version=expected_version, idempotency_key=idempotency_key, operation="preservation_hold_placed" if active else "preservation_hold_released", reason=reason, payload={"hold": hold}, apply=apply)


def set_impact_assessment_status(conn: sqlite3.Connection, *, entry_identifier: Any, status: Any, assessment_basis: Any = None, assessment_limits: Any = None, actor: Any, expected_version: Any, idempotency_key: Any, reason: Any) -> dict[str, Any]:
    """Record entry-level impact status without inventing a child target."""
    value = _enum(status, IMPACT_STATUSES, "defect_register_impact_status_invalid")
    basis = _optional(assessment_basis)
    limits = _optional(assessment_limits)
    if value == "no_affected_items_identified_within_stated_assessment" and (not basis or not limits):
        raise ValueError("defect_register_impact_basis_and_limits_required")

    def apply(_item: dict[str, Any], _next: int):
        return {"impact_status": value}, {"impact_status": value, "assessment_basis": basis, "assessment_limits": limits}

    return _mutate(conn, entry_identifier=entry_identifier, actor=actor, expected_version=expected_version,
                   idempotency_key=idempotency_key, operation="impact_assessment_status_recorded", reason=reason,
                   payload={"impact_status": value, "assessment_basis": basis, "assessment_limits": limits}, apply=apply)


def _retention_due(item: Mapping[str, Any], now: datetime) -> tuple[datetime, str | None]:
    """Return the enforced policy due date and any active deferral trigger."""
    closed = item["lifecycle_state"] == "closed"
    prior = item.get("retention_review") or {}
    if prior.get("reviewed_at"):
        anchor = _timestamp(prior["reviewed_at"], "defect_register_retention_history_invalid")
    elif closed:
        closure = item.get("closure") or {}
        anchor = _timestamp(closure.get("closed_at"), "defect_register_closure_history_invalid")
    else:
        anchor = _timestamp(item["created_at"], "defect_register_created_history_invalid")
    due = anchor + timedelta(days=365 if closed else 90)
    deferral = item.get("deferral") or {}
    review_on = deferral.get("review_on")
    if review_on:
        deferred_due = _timestamp(review_on, "defect_register_deferral_review_invalid")
        if deferred_due < due:
            due = deferred_due
    return due, deferral.get("review_trigger")


def record_retention_review(conn: sqlite3.Connection, *, entry_identifier: Any, what_remains_necessary: Any, actor: Any, expected_version: Any, idempotency_key: Any, reason: Any) -> dict[str, Any]:
    """Record an enforced review point; it never disposes material or releases a hold."""
    necessary = _required(what_remains_necessary, "defect_register_retention_reason_required")

    def apply(item: dict[str, Any], _next: int):
        reviewed_at = _timestamp(utc_now(), "defect_register_retention_time_invalid")
        due, trigger = _retention_due(item, reviewed_at)
        if reviewed_at < due:
            raise ValueError("defect_register_retention_review_not_due")
        next_due = reviewed_at + timedelta(days=365 if item["lifecycle_state"] == "closed" else 90)
        deferral = item.get("deferral") or {}
        if deferral.get("review_on"):
            deferral_due = _timestamp(deferral["review_on"], "defect_register_deferral_review_invalid")
            if deferral_due > reviewed_at and deferral_due < next_due:
                next_due = deferral_due
        recorded = {"what_remains_necessary": necessary, "reviewed_at": _timestamp_text(reviewed_at),
                    "next_review_date": _timestamp_text(next_due), "policy": "closed_annual" if item["lifecycle_state"] == "closed" else "open_90_days",
                    "active_deferral_trigger": trigger, "hold_active": bool((item.get("preservation_hold") or {}).get("active"))}
        return {"retention_review_json": _json(recorded)}, {"retention_review": recorded}

    return _mutate(conn, entry_identifier=entry_identifier, actor=actor, expected_version=expected_version,
                   idempotency_key=idempotency_key, operation="retention_review_recorded", reason=reason,
                   payload={"what_remains_necessary": necessary}, apply=apply)


# Stage 81.1: private, passive downstream impact/revalidation tracking.  These
# records are not a workflow executor; all cited material remains a bounded
# reference and all current-state changes are accompanied by immutable events.
def _revalidation_for_entry(conn: sqlite3.Connection, item: Mapping[str, Any], requirement_identifier: Any) -> dict[str, Any]:
    identifier = _identifier(requirement_identifier, "defect_register_revalidation_identifier_invalid")
    row = conn.execute(
        "SELECT * FROM governed_defect_register_revalidations WHERE requirement_identifier=? AND entry_id=?",
        (identifier, int(item["id"])),
    ).fetchone()
    result = _revalidation_row(row)
    if result is None:
        raise ValueError("defect_register_revalidation_not_found")
    return result


def _revalidation_event(conn: sqlite3.Connection, requirement: Mapping[str, Any], item: Mapping[str, Any], *, event_type: str, actor: str, reason: str, prior_version: int, resulting_version: int, details: Mapping[str, Any]) -> int:
    cursor = conn.execute(
        "INSERT INTO governed_defect_register_revalidation_events (revalidation_id,entry_id,entry_identifier,event_type,actor,occurred_at,prior_version,resulting_version,reason,details_json) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (int(requirement["id"]), int(item["id"]), item["entry_identifier"], event_type, actor, utc_now(), prior_version, resulting_version, reason, _json(details)),
    )
    return int(cursor.lastrowid)


def _next_revalidation_identifier(conn: sqlite3.Connection, entry_identifier: str) -> str:
    count = conn.execute(
        "SELECT count(*) FROM governed_defect_register_revalidations WHERE entry_identifier=?",
        (entry_identifier,),
    ).fetchone()[0]
    return f"{entry_identifier}:RV-{int(count) + 1:03d}"


def _bound_reference(conn: sqlite3.Connection, item: Mapping[str, Any], reference_id: Any, relation: str, *, checks: tuple[str, ...] = ()) -> dict[str, Any]:
    reference = _reference_for_entry(conn, item, reference_id, relation=relation)
    if any(not _reference_has_check(reference, check) for check in checks):
        raise ValueError("defect_register_revalidation_reference_unsubstantiated")
    return reference


def _target_identity(kind: Any, value: Any, reference: Mapping[str, Any], observed_at: str) -> tuple[str, str]:
    identity_kind = _enum(kind, TARGET_IDENTITY_KINDS, "defect_register_revalidation_target_identity_invalid")
    identity = _identifier(value, "defect_register_revalidation_target_identity_invalid")
    binding = reference.get("target_binding")
    if not isinstance(binding, Mapping):
        raise ValueError("defect_register_revalidation_target_binding_invalid")
    if (binding.get("identity_kind") != identity_kind
            or binding.get("identity") != identity
            or binding.get("observed_at") != observed_at
            or binding.get("target_reference_type") != reference.get("reference_type")
            or binding.get("target_reference_value") != reference.get("reference_value")):
        raise ValueError("defect_register_revalidation_target_binding_mismatch")
    return identity_kind, identity


def _bound_supersession_reference(conn: sqlite3.Connection, item: Mapping[str, Any],
                                  predecessor: Mapping[str, Any], reference_id: Any) -> dict[str, Any]:
    reference = _bound_reference(conn, item, reference_id, "supersedes",
                                 checks=("relationship_substantiated",))
    binding = reference.get("supersession_binding")
    origin = predecessor["origin_action"]
    successor_origin = _origin_action(item)
    if (not isinstance(binding, Mapping)
            or binding.get("predecessor_requirement_identifier") != predecessor["requirement_identifier"]
            or binding.get("predecessor_origin_action_id") != origin.get("action_id")
            or binding.get("successor_origin_action_id") != successor_origin.get("action_id")
            or binding.get("later_correction_reference_type") != reference.get("reference_type")
            or binding.get("later_correction_reference_value") != reference.get("reference_value")):
        raise ValueError("defect_register_revalidation_supersession_binding_mismatch")
    already_used = conn.execute(
        "SELECT 1 FROM governed_defect_register_revalidations WHERE supersession_reference_id=?",
        (int(reference["id"]),),
    ).fetchone()
    if already_used is not None:
        raise ValueError("defect_register_revalidation_supersession_reused")
    return reference


def _require_timing(due_at: Any, review_trigger: Any) -> tuple[str | None, str | None]:
    due = _optional(due_at, maximum=64)
    trigger = _optional(review_trigger, maximum=512)
    if not due and not trigger:
        raise ValueError("defect_register_revalidation_timing_required")
    if due:
        due = _timestamp_text(_timestamp(due, "defect_register_revalidation_due_invalid"))
    return due, trigger


def _origin_action(item: Mapping[str, Any]) -> dict[str, Any]:
    action = item.get("active_action")
    if not isinstance(action, Mapping) or action.get("execution_status") != "execution_substantiated":
        raise ValueError("defect_register_revalidation_origin_action_invalid")
    required = ("action_id", "agreed_version", "acceptance_criteria_identity", "execution_reference_id")
    if any(action.get(name) in (None, "") for name in required):
        raise ValueError("defect_register_revalidation_origin_action_invalid")
    return {
        "action_id": str(action["action_id"]),
        "agreed_version": int(action["agreed_version"]),
        "acceptance_criteria_identity": str(action["acceptance_criteria_identity"]),
        "execution_reference_id": int(action["execution_reference_id"]),
    }


def _revalidation_binding(conn: sqlite3.Connection, item: Mapping[str, Any], value: Any, reference_type: str, reference_value: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("defect_register_revalidation_binding_invalid")
    requirement = _revalidation_for_entry(conn, item, value.get("requirement_identifier"))
    if requirement["outcome"] not in {"awaiting_revalidation", "revalidation_failed"}:
        raise ValueError("defect_register_revalidation_binding_invalid")
    origin = requirement["origin_action"]
    try:
        execution_id = int(value.get("execution_reference_id"))
        target_id = int(value.get("target_reference_id"))
    except (TypeError, ValueError) as exc:
        raise ValueError("defect_register_revalidation_binding_invalid") from exc
    binding = {
        "requirement_identifier": requirement["requirement_identifier"],
        "origin_action_id": _required(value.get("origin_action_id"), "defect_register_revalidation_binding_invalid", maximum=128),
        "origin_action_agreed_version": int(value.get("origin_action_agreed_version")),
        "origin_acceptance_criteria_identity": _required(value.get("origin_acceptance_criteria_identity"), "defect_register_revalidation_binding_invalid", maximum=128),
        "execution_reference_id": execution_id,
        "target_reference_id": target_id,
        "target_identity": _identifier(value.get("target_identity"), "defect_register_revalidation_binding_invalid"),
        "criteria_identity": _required(value.get("criteria_identity"), "defect_register_revalidation_binding_invalid", maximum=128),
        "artifact_reference_type": reference_type,
        "artifact_reference_value": reference_value,
    }
    if (binding["origin_action_id"] != origin["action_id"]
            or binding["origin_action_agreed_version"] != origin["agreed_version"]
            or binding["origin_acceptance_criteria_identity"] != origin["acceptance_criteria_identity"]
            or binding["execution_reference_id"] != requirement["execution_reference_id"]
            or binding["target_reference_id"] != requirement["target_reference_id"]
            or binding["target_identity"] != requirement["target_identity"]
            or binding["criteria_identity"] != requirement["criteria_identity"]):
        raise ValueError("defect_register_revalidation_binding_mismatch")
    return binding


def _bound_revalidation_artifact(conn: sqlite3.Connection, item: Mapping[str, Any], requirement: Mapping[str, Any], verification: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    artifact = _reference_for_entry(conn, item, verification.get("artifact_reference_id"), relation="revalidation_evidence")
    origin = requirement["origin_action"]
    expected_binding = {"requirement_identifier": requirement["requirement_identifier"], "origin_action_id": origin["action_id"], "origin_action_agreed_version": origin["agreed_version"], "origin_acceptance_criteria_identity": origin["acceptance_criteria_identity"], "execution_reference_id": requirement["execution_reference_id"], "target_reference_id": requirement["target_reference_id"], "target_identity": requirement["target_identity"], "criteria_identity": requirement["criteria_identity"], "artifact_reference_type": artifact["reference_type"], "artifact_reference_value": artifact["reference_value"]}
    if artifact.get("revalidation_binding") != expected_binding:
        raise ValueError("defect_register_revalidation_binding_mismatch")
    if (not _reference_has_check(artifact, "relationship_substantiated")
            or not _reference_has_check(artifact, "target_identity_or_content_verified")):
        raise ValueError("defect_register_revalidation_verification_unsubstantiated")
    results = verification.get("criteria_results")
    if not isinstance(results, Mapping) or set(results) != set(requirement["criteria"]):
        raise ValueError("defect_register_revalidation_criteria_incomplete")
    return artifact, {str(key): str(value) for key, value in results.items()}


def _mutate_revalidation(conn: sqlite3.Connection, *, entry_identifier: Any, requirement_identifier: Any, actor: Any, expected_version: Any, idempotency_key: Any, operation: str, reason: Any, payload: Mapping[str, Any], apply: Callable[[dict[str, Any], dict[str, Any], int], tuple[dict[str, Any], dict[str, Any]]]) -> dict[str, Any]:
    ensure_tables(conn)
    identifier = _identifier(entry_identifier, "defect_register_identifier_invalid")
    requirement_id = _identifier(requirement_identifier, "defect_register_revalidation_identifier_invalid")
    actor_value, expected, key = _actor(actor), _expected_version(expected_version), _key(idempotency_key)
    canonical = {"operation": operation, "entry_identifier": identifier, "requirement_identifier": requirement_id, "actor": actor_value, "expected_version": expected, "reason": _required(reason, "defect_register_reason_required"), **payload}
    conn.execute("BEGIN IMMEDIATE")
    try:
        replay = _receipt(conn, key, canonical)
        if replay is not None:
            conn.rollback()
            return replay
        item = _entry(conn, identifier)
        if int(item["version"]) != expected:
            raise ValueError("defect_register_version_conflict")
        requirement = _revalidation_for_entry(conn, item, requirement_id)
        updates, details = apply(item, requirement, expected + 1)
        if not updates:
            raise ValueError("defect_register_revalidation_mutation_invalid")
        columns = list(updates) + ["version", "updated_at", "updated_by"]
        values = [updates[name] for name in updates] + [int(requirement["version"]) + 1, utc_now(), actor_value, int(requirement["id"])]
        conn.execute(f"UPDATE governed_defect_register_revalidations SET {','.join(f'{name}=?' for name in columns)} WHERE id=?", values)
        conn.execute("UPDATE governed_defect_register_entries SET version=?,updated_at=?,updated_by=? WHERE id=?", (expected + 1, utc_now(), actor_value, int(item["id"])))
        event_id = _revalidation_event(conn, requirement, item, event_type=operation, actor=actor_value, reason=canonical["reason"], prior_version=int(requirement["version"]), resulting_version=int(requirement["version"]) + 1, details=details)
        _event(conn, item, event_type=operation, actor=actor_value, reason=canonical["reason"], prior_version=expected, resulting_version=expected + 1, details={"requirement_identifier": requirement_id, **details})
        receipt = {"entry_identifier": identifier, "requirement_identifier": requirement_id, "operation": operation, "event_id": event_id, "resulting_version": expected + 1, "historical_receipt": False}
        conn.execute("INSERT INTO governed_defect_register_receipts (idempotency_key,entry_identifier,canonical_payload_json,receipt_json,created_at) VALUES (?,?,?,?,?)", (key, identifier, _json(canonical), _json(receipt), utc_now()))
        conn.commit()
        return receipt
    except Exception:
        conn.rollback()
        raise


def create_revalidation_requirement(conn: sqlite3.Connection, *, entry_identifier: Any, impact_id: Any, target_reference_id: Any, target_identity_kind: Any, target_identity: Any, observed_at: Any, assessment_scope: Any, assessment_basis: Any, assessment_limits: Any, acceptance_criteria: Any, owner_reference: Any, due_at: Any = None, review_trigger: Any = None, linked_workflow_requires_approval: bool = False, authority_reference_id: Any = None, predecessor_requirement_identifier: Any = None, supersession_reference_id: Any = None, actor: Any, expected_version: Any, idempotency_key: Any, reason: Any) -> dict[str, Any]:
    criteria = _criteria(acceptance_criteria)
    owner = _required(owner_reference, "defect_register_revalidation_owner_required", maximum=256)
    due, trigger = _require_timing(due_at, review_trigger)
    scope = _required(assessment_scope, "defect_register_revalidation_scope_required")
    basis = _required(assessment_basis, "defect_register_revalidation_basis_required")
    limits = _required(assessment_limits, "defect_register_revalidation_limits_required")
    if not isinstance(linked_workflow_requires_approval, bool):
        raise ValueError("defect_register_revalidation_authority_requirement_invalid")
    requires_approval = linked_workflow_requires_approval
    conn.execute("BEGIN IMMEDIATE")
    try:
        identifier = _identifier(entry_identifier, "defect_register_identifier_invalid")
        actor_value, expected, key = _actor(actor), _expected_version(expected_version), _key(idempotency_key)
        payload = {"impact_id": impact_id, "target_reference_id": target_reference_id, "target_identity_kind": target_identity_kind, "target_identity": target_identity, "observed_at": observed_at, "assessment_scope": scope, "assessment_basis": basis, "assessment_limits": limits, "acceptance_criteria": criteria, "owner_reference": owner, "due_at": due, "review_trigger": trigger, "linked_workflow_requires_approval": requires_approval, "authority_reference_id": authority_reference_id, "predecessor_requirement_identifier": predecessor_requirement_identifier, "supersession_reference_id": supersession_reference_id}
        canonical = {"operation": "revalidation_requirement_created", "entry_identifier": identifier, "actor": actor_value, "expected_version": expected, "reason": _required(reason, "defect_register_reason_required"), **payload}
        replay = _receipt(conn, key, canonical)
        if replay is not None:
            conn.rollback()
            return replay
        item = _entry(conn, identifier)
        if int(item["version"]) != expected:
            raise ValueError("defect_register_version_conflict")
        action = _origin_action(item)
        execution_ref = _bound_reference(conn, item, action["execution_reference_id"], "execution_evidence", checks=("relationship_substantiated",))
        del execution_ref
        try:
            impact_numeric = int(impact_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("defect_register_revalidation_impact_invalid") from exc
        impact = conn.execute("SELECT * FROM governed_defect_register_impacts WHERE id=? AND entry_id=?", (impact_numeric, int(item["id"]))).fetchone()
        if impact is None or str(impact["status"]) not in {"potentially_affected", "assessed_affected"}:
            raise ValueError("defect_register_revalidation_impact_invalid")
        observed = _timestamp_text(_timestamp(observed_at, "defect_register_revalidation_observation_time_invalid"))
        target_ref = _bound_reference(conn, item, target_reference_id, "impact_target", checks=("relationship_substantiated", "target_identity_or_content_verified"))
        identity_kind, identity = _target_identity(target_identity_kind, target_identity, target_ref, observed)
        authority_id = None
        if requires_approval:
            authority_ref = _bound_reference(conn, item, authority_reference_id, "authority", checks=("relationship_substantiated",))
            authority_id = int(authority_ref["id"])
        elif authority_reference_id is not None:
            raise ValueError("defect_register_revalidation_authority_unexpected")
        predecessor = None
        supersession = None
        if predecessor_requirement_identifier is not None:
            predecessor = _revalidation_for_entry(conn, item, predecessor_requirement_identifier)
            supersession = _bound_supersession_reference(conn, item, predecessor, supersession_reference_id)
            unchanged_target_and_criteria = (predecessor["target_identity"] == identity
                                             and predecessor["criteria_identity"] == _criteria_identity(criteria))
            if unchanged_target_and_criteria and predecessor["origin_action"] == action:
                raise ValueError("defect_register_revalidation_successor_unchanged")
        requirement_identifier = _next_revalidation_identifier(conn, identifier)
        now = utc_now()
        cursor = conn.execute("INSERT INTO governed_defect_register_revalidations (entry_id,entry_identifier,requirement_identifier,predecessor_requirement_id,supersession_reference_id,impact_id,origin_action_json,execution_reference_id,target_reference_id,target_identity_kind,target_identity,observed_at,assessment_scope,assessment_basis,assessment_limits,criteria_json,criteria_identity,linked_workflow_requires_approval,authority_reference_id,owner_reference,due_at,review_trigger,outcome,conclusion_json,outcome_details_json,superseded_by_requirement_id,version,created_at,created_by,updated_at,updated_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (int(item["id"]), identifier, requirement_identifier, int(predecessor["id"]) if predecessor else None, int(supersession["id"]) if supersession else None, impact_numeric, _json(action), action["execution_reference_id"], int(target_ref["id"]), identity_kind, identity, observed, scope, basis, limits, _json(criteria), _criteria_identity(criteria), 1 if requires_approval else 0, authority_id, owner, due, trigger, "open", None, None, None, 1, now, actor_value, now, actor_value))
        requirement = {"id": int(cursor.lastrowid), "requirement_identifier": requirement_identifier, "version": 1}
        if predecessor:
            conn.execute("UPDATE governed_defect_register_revalidations SET outcome=?,superseded_by_requirement_id=?,version=?,updated_at=?,updated_by=? WHERE id=?", ("superseded", int(requirement["id"]), int(predecessor["version"]) + 1, now, actor_value, int(predecessor["id"])))
            _revalidation_event(conn, predecessor, item, event_type="revalidation_superseded", actor=actor_value, reason=canonical["reason"], prior_version=int(predecessor["version"]), resulting_version=int(predecessor["version"]) + 1, details={"successor_requirement_identifier": requirement_identifier, "supersession_reference_id": int(supersession["id"])})
        conn.execute("UPDATE governed_defect_register_entries SET version=?,impact_status=?,updated_at=?,updated_by=? WHERE id=?", (expected + 1, "items_recorded", now, actor_value, int(item["id"])))
        event_id = _revalidation_event(conn, requirement, item, event_type="revalidation_requirement_created", actor=actor_value, reason=canonical["reason"], prior_version=0, resulting_version=1, details={"target_reference_id": int(target_ref["id"]), "target_identity": identity, "criteria_identity": _criteria_identity(criteria), "predecessor_requirement_identifier": predecessor_requirement_identifier, "supersession_reference_id": int(supersession["id"]) if supersession else None})
        _event(conn, item, event_type="revalidation_requirement_created", actor=actor_value, reason=canonical["reason"], prior_version=expected, resulting_version=expected + 1, details={"requirement_identifier": requirement_identifier, "event_id": event_id})
        receipt = {"entry_identifier": identifier, "requirement_identifier": requirement_identifier, "operation": "revalidation_requirement_created", "event_id": event_id, "resulting_version": expected + 1, "historical_receipt": False}
        conn.execute("INSERT INTO governed_defect_register_receipts (idempotency_key,entry_identifier,canonical_payload_json,receipt_json,created_at) VALUES (?,?,?,?,?)", (key, identifier, _json(canonical), _json(receipt), now))
        conn.commit()
        return receipt
    except Exception:
        conn.rollback()
        raise


def transition_revalidation(conn: sqlite3.Connection, *, entry_identifier: Any, requirement_identifier: Any, outcome: Any, actor: Any, expected_version: Any, idempotency_key: Any, reason: Any, verification: Mapping[str, Any] | None = None, conclusion: Mapping[str, Any] | None = None, due_at: Any = None, review_trigger: Any = None) -> dict[str, Any]:
    target = _enum(outcome, REVALIDATION_OUTCOMES, "defect_register_revalidation_outcome_invalid")
    timing = (None, None) if due_at is None and review_trigger is None else _require_timing(due_at, review_trigger)
    if verification is not None and not isinstance(verification, Mapping):
        raise ValueError("defect_register_revalidation_verification_invalid")
    if conclusion is not None and not isinstance(conclusion, Mapping):
        raise ValueError("defect_register_revalidation_conclusion_invalid")

    def apply(item: dict[str, Any], requirement: dict[str, Any], _next: int):
        current = requirement["outcome"]
        allowed = {
            "open": {"deferred", "awaiting_revalidation", "concluded_without_passing", "not_required"},
            "deferred": {"open", "awaiting_revalidation", "concluded_without_passing"},
            "awaiting_revalidation": {"revalidation_passed", "revalidation_failed", "concluded_without_passing"},
            "revalidation_failed": {"awaiting_revalidation", "concluded_without_passing"},
            "not_required": {"reopened"}, "revalidation_passed": {"reopened"}, "concluded_without_passing": {"reopened"}, "superseded": {"reopened"}, "reopened": {"open", "awaiting_revalidation", "concluded_without_passing"},
        }
        if target not in allowed.get(current, set()):
            raise ValueError("defect_register_revalidation_transition_invalid")
        updates: dict[str, Any] = {"outcome": target}
        details: dict[str, Any] = {"prior_outcome": current, "new_outcome": target}
        if timing != (None, None):
            updates["due_at"], updates["review_trigger"] = timing
            details["due_at"], details["review_trigger"] = timing
        if target in {"revalidation_passed", "revalidation_failed"}:
            if not verification:
                raise ValueError("defect_register_revalidation_verification_required")
            artifact, results = _bound_revalidation_artifact(conn, item, requirement, verification)
            if target == "revalidation_passed" and any(value != "passed" for value in results.values()):
                raise ValueError("defect_register_revalidation_criteria_incomplete")
            if target == "revalidation_failed" and all(value == "passed" for value in results.values()):
                raise ValueError("defect_register_revalidation_criteria_incomplete")
            details["verification"] = {"artifact_reference_id": int(artifact["id"]), "criteria_results": results}
            if target == "revalidation_failed":
                if not conclusion:
                    raise ValueError("defect_register_revalidation_failure_details_required")
                limits = _required(conclusion.get("assessment_limitations"), "defect_register_revalidation_conclusion_limits_required")
                consequences = _required(conclusion.get("unresolved_consequences"), "defect_register_revalidation_conclusion_consequences_required")
                disposition = conclusion.get("follow_up_disposition")
                if not isinstance(disposition, Mapping) or disposition.get("work_remains") is not True:
                    raise ValueError("defect_register_revalidation_follow_up_required")
                owner = _required(disposition.get("owner_reference"), "defect_register_revalidation_follow_up_required", maximum=256)
                due, trigger = _require_timing(disposition.get("due_at"), disposition.get("review_trigger"))
                record = {"assessment_limitations": limits, "unresolved_consequences": consequences, "follow_up_disposition": {"work_remains": True, "description": _required(disposition.get("description"), "defect_register_revalidation_follow_up_required"), "owner_reference": owner, "due_at": due, "review_trigger": trigger}, "artifact_reference_id": int(artifact["id"]), "recorded_at": utc_now()}
                updates["outcome_details_json"] = _json(record)
                details["failure"] = record
        if target == "concluded_without_passing":
            if bool(requirement["linked_workflow_requires_approval"]):
                raise ValueError("defect_register_revalidation_linked_approval_required")
            if not conclusion:
                raise ValueError("defect_register_revalidation_conclusion_required")
            limits = _required(conclusion.get("assessment_limitations"), "defect_register_revalidation_conclusion_limits_required")
            consequences = _required(conclusion.get("unresolved_consequences"), "defect_register_revalidation_conclusion_consequences_required")
            evidence_ids = _references_for_entry(conn, item, conclusion.get("evidence_reference_ids"))
            disposition = conclusion.get("follow_up_disposition")
            if not isinstance(disposition, Mapping):
                raise ValueError("defect_register_revalidation_follow_up_required")
            work_remains = disposition.get("work_remains")
            if not isinstance(work_remains, bool):
                raise ValueError("defect_register_revalidation_follow_up_required")
            stored_disposition = {"work_remains": work_remains, "description": _required(disposition.get("description"), "defect_register_revalidation_follow_up_required")}
            if work_remains:
                stored_disposition["owner_reference"] = _required(disposition.get("owner_reference"), "defect_register_revalidation_follow_up_required", maximum=256)
                stored_disposition["due_at"], stored_disposition["review_trigger"] = _require_timing(disposition.get("due_at"), disposition.get("review_trigger"))
            else:
                stored_disposition["reason_no_work_remains"] = _required(disposition.get("reason_no_work_remains"), "defect_register_revalidation_follow_up_required")
            record = {"assessment_limitations": limits, "unresolved_consequences": consequences, "evidence_reference_ids": evidence_ids, "follow_up_disposition": stored_disposition, "recorded_at": utc_now()}
            updates["conclusion_json"] = _json(record)
            details["conclusion"] = record
        if target in {"deferred", "open", "awaiting_revalidation", "reopened"} and timing == (None, None) and not (requirement.get("due_at") or requirement.get("review_trigger")):
            raise ValueError("defect_register_revalidation_timing_required")
        return updates, details

    return _mutate_revalidation(conn, entry_identifier=entry_identifier, requirement_identifier=requirement_identifier, actor=actor, expected_version=expected_version, idempotency_key=idempotency_key, operation="revalidation_transition", reason=reason, payload={"outcome": target, "verification": dict(verification) if verification else None, "conclusion": dict(conclusion) if conclusion else None, "due_at": timing[0], "review_trigger": timing[1]}, apply=apply)


def revalidation_has_outstanding_obligation(requirement: Mapping[str, Any]) -> bool:
    """Return whether the current row carries active downstream work.

    Superseded rows and an assessed ``not_required`` result remain preserved
    history, but are not current obligations.  A non-passing conclusion only
    remains outstanding when its recorded disposition says work remains.
    """
    outcome = requirement.get("outcome")
    if outcome in REVALIDATION_ACTIVE_OUTCOMES:
        return True
    if outcome == "concluded_without_passing":
        disposition = (requirement.get("conclusion") or {}).get("follow_up_disposition")
        return isinstance(disposition, Mapping) and disposition.get("work_remains") is True
    return False


def downstream_work_outstanding(conn: sqlite3.Connection, entry_identifier: Any) -> bool:
    rows = revalidations(conn, _identifier(entry_identifier, "defect_register_identifier_invalid"))
    return any(revalidation_has_outstanding_obligation(row) for row in rows)
