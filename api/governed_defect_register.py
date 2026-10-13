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
REFERENCE_RELATIONS = frozenset({"reported_evidence", "assessment_evidence", "authority", "action_target", "execution_claim", "execution_evidence", "verification_evidence", "impact_target", "supersedes"})
VALIDATION_STEPS = frozenset({"syntax_validated", "target_existence_checked", "target_identity_or_content_verified", "relationship_substantiated"})
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
            created_at TEXT NOT NULL,
            created_by TEXT NOT NULL,
            FOREIGN KEY(entry_id) REFERENCES governed_defect_register_entries(id)
        )
    """)
    reference_columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(governed_defect_register_references)")}
    if "verification_binding_json" not in reference_columns:
        conn.execute("ALTER TABLE governed_defect_register_references ADD COLUMN verification_binding_json TEXT")
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
    for table in ("governed_defect_register_events", "governed_defect_register_references", "governed_defect_register_impacts"):
        conn.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_no_update BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT, 'defect_register_history_immutable'); END")
        conn.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_no_delete BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT, 'defect_register_history_immutable'); END")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_defect_register_events_entry ON governed_defect_register_events(entry_id, id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_defect_register_refs_entry ON governed_defect_register_references(entry_id, id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_defect_register_impacts_entry ON governed_defect_register_impacts(entry_id, id)")


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


def impacts(conn: sqlite3.Connection, entry_identifier: str) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute("SELECT * FROM governed_defect_register_impacts WHERE entry_identifier=? ORDER BY id", (_identifier(entry_identifier, "defect_register_identifier_invalid"),)).fetchall()]


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


def add_reference(conn: sqlite3.Connection, *, entry_identifier: Any, reference_type: Any, reference_value: Any, relation: Any, neutral_label: Any, supplier_identity: Any, validation_steps: Any, actor: Any, expected_version: Any, idempotency_key: Any, reason: Any, verification_binding: Mapping[str, Any] | None = None) -> dict[str, Any]:
    ref_type = _enum(reference_type, REFERENCE_TYPES, "defect_register_reference_type_invalid")
    relation_value = _enum(relation, REFERENCE_RELATIONS, "defect_register_reference_relation_invalid")
    value = _identifier(reference_value, "defect_register_reference_value_invalid")
    label = _required(neutral_label, "defect_register_reference_label_required", maximum=256)
    supplied = _optional(supplier_identity, maximum=256)
    if relation_value != "verification_evidence" and verification_binding is not None:
        raise ValueError("defect_register_verification_binding_invalid")
    if relation_value == "verification_evidence" and not isinstance(verification_binding, Mapping):
        raise ValueError("defect_register_verification_binding_invalid")
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
    return _mutate_reference(conn, entry_identifier=entry_identifier, actor=actor, expected_version=expected_version, idempotency_key=idempotency_key, reason=reason, payload={"reference_type": ref_type, "reference_value": value, "relation": relation_value, "neutral_label": label, "supplier_identity": supplied, "validation_steps": steps, "verification_binding": dict(verification_binding) if verification_binding is not None else None})


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
        cursor = conn.execute("INSERT INTO governed_defect_register_references (entry_id,entry_identifier,reference_type,reference_value,relation,neutral_label,supplier_identity,validator_identity,validation_steps_json,verification_binding_json,created_at,created_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (int(item["id"]), identifier, payload["reference_type"], payload["reference_value"], payload["relation"], payload["neutral_label"], payload["supplier_identity"], None, _json(steps), _json(binding) if binding is not None else None, utc_now(), actor_value))
        conn.execute("UPDATE governed_defect_register_entries SET version=?,updated_at=?,updated_by=? WHERE id=?", (expected + 1, utc_now(), actor_value, int(item["id"])))
        event_id = _event(conn, item, event_type="reference_added", actor=actor_value, reason=canonical["reason"], prior_version=expected, resulting_version=expected + 1, details={"reference_id": int(cursor.lastrowid), "relation": payload["relation"], "validation_steps": steps, "verification_binding": binding})
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
