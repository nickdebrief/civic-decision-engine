"""Private Stage 82 challenge register; real challenge admission is disabled.

This restricted foundation keeps synthetic test fixtures below the application
boundary.  It stores no operational submissions and never executes a linked
Stage 81/81.1 workflow.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Mapping, Callable

from api import governed_defect_register as gdr81
from api.admin_session_verification import AdminSessionVerificationError, verify_signed_admin_session

PROCEDURAL_STATES = frozenset({"received", "procedurally_accepted", "under_assessment", "response_in_preparation", "responded", "closed", "reopened"})
ISSUE_STATES = frozenset({"unassessed", "awaiting_information", "under_assessment", "answered", "linked_to_follow_through", "declined_with_reasons", "withdrawn", "outside_scope", "duplicate"})
TERMINAL_ISSUE_STATES = frozenset({"answered", "declined_with_reasons", "withdrawn", "outside_scope", "duplicate"})
SUBJECT_TYPES = gdr81.REFERENCE_TYPES
MAX_ISSUES, MAX_AMENDMENTS, MAX_REFERENCES, MAX_TEXT = 20, 20, 20, 8000
# Compatibility name only. It is never accepted as proof: closure assessment
# truth is represented by bounded basis/scope/limits and current completeness.
CLOSURE_NO_INDEPENDENT_ISSUE = "administrative_judgment"

# All mutating operations take a signed session token and independently verify
# it.  A mapping, a caller-created capability object, or an exported sentinel
# is never an actor boundary.  This protects ordinary service callers; code
# already executing with access to the process secret is in the trusted
# process and outside this service-layer boundary.


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _loads(value: Any, fallback: Any = None) -> Any:
    try:
        return json.loads(value) if value else fallback
    except (TypeError, json.JSONDecodeError):
        return fallback


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _required(value: Any, code: str, maximum: int = MAX_TEXT) -> str:
    text = str(value or "").strip()
    if not text or len(text) > maximum:
        raise ValueError(code)
    return text


def _identifier(value: Any, code: str) -> str:
    return gdr81._identifier(value, code)


def _actor(value: Any) -> str:
    try:
        session = verify_signed_admin_session(value)
    except AdminSessionVerificationError as exc:
        raise ValueError("challenge_register_authenticated_actor_required") from exc
    identity = session.get("username")
    if not isinstance(identity, str) or not identity.strip():
        raise ValueError("challenge_register_authenticated_actor_required")
    return identity.strip()


def _version(value: Any) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("challenge_register_expected_version_invalid") from exc
    if result < 0:
        raise ValueError("challenge_register_expected_version_invalid")
    return result


def _key(value: Any) -> str:
    return gdr81._key(value)


def ensure_tables(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("""CREATE TABLE IF NOT EXISTS governed_challenge_entries (
        id INTEGER PRIMARY KEY AUTOINCREMENT, challenge_identifier TEXT NOT NULL UNIQUE,
        subject_type TEXT NOT NULL, subject_value TEXT NOT NULL, subject_identity TEXT NOT NULL,
        procedural_state TEXT NOT NULL, recipient_identity TEXT, recipient_basis TEXT,
        recipient_claim TEXT, version INTEGER NOT NULL, created_at TEXT NOT NULL,
        created_by TEXT NOT NULL, updated_at TEXT NOT NULL, updated_by TEXT NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS governed_challenge_issues (
        id INTEGER PRIMARY KEY AUTOINCREMENT, entry_id INTEGER NOT NULL, issue_identifier TEXT NOT NULL UNIQUE,
        grounds TEXT NOT NULL, reasons TEXT NOT NULL, requested_outcomes_json TEXT NOT NULL,
        issue_state TEXT NOT NULL, response_json TEXT, disposition_json TEXT, information_json TEXT, deferral_json TEXT,
        duplicate_issue_id INTEGER, reopened_duplicate_disposition_id INTEGER,
        successor_issue_id INTEGER, version INTEGER NOT NULL,
        created_at TEXT NOT NULL, created_by TEXT NOT NULL, updated_at TEXT NOT NULL, updated_by TEXT NOT NULL,
        FOREIGN KEY(entry_id) REFERENCES governed_challenge_entries(id))""")
    # This compatibility change is only for disposable local databases created
    # while developing the foundation; it is not a production migration.
    issue_columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(governed_challenge_issues)").fetchall()}
    if "information_json" not in issue_columns:
        conn.execute("ALTER TABLE governed_challenge_issues ADD COLUMN information_json TEXT")
    if "reopened_duplicate_disposition_id" not in issue_columns:
        conn.execute("ALTER TABLE governed_challenge_issues ADD COLUMN reopened_duplicate_disposition_id INTEGER")
    conn.execute("""CREATE TABLE IF NOT EXISTS governed_challenge_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT, entry_id INTEGER NOT NULL, issue_id INTEGER,
        event_type TEXT NOT NULL, actor TEXT NOT NULL, occurred_at TEXT NOT NULL,
        prior_entry_version INTEGER NOT NULL, resulting_entry_version INTEGER NOT NULL,
        reason TEXT NOT NULL, details_json TEXT NOT NULL, FOREIGN KEY(entry_id) REFERENCES governed_challenge_entries(id))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS governed_challenge_amendments (
        id INTEGER PRIMARY KEY AUTOINCREMENT, entry_id INTEGER NOT NULL, issue_id INTEGER,
        changed_material TEXT NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL, created_by TEXT NOT NULL,
        FOREIGN KEY(entry_id) REFERENCES governed_challenge_entries(id))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS governed_challenge_evidence (
        id INTEGER PRIMARY KEY AUTOINCREMENT, entry_id INTEGER NOT NULL, issue_id INTEGER,
        reference_type TEXT NOT NULL, reference_value TEXT NOT NULL, subject_identity TEXT NOT NULL,
        relation TEXT NOT NULL, validation_steps_json TEXT NOT NULL, supplied_identity_claim TEXT,
        validated_by TEXT NOT NULL, created_at TEXT NOT NULL, created_by TEXT NOT NULL,
        FOREIGN KEY(entry_id) REFERENCES governed_challenge_entries(id))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS governed_challenge_validation_assessments (
        id INTEGER PRIMARY KEY AUTOINCREMENT, entry_id INTEGER NOT NULL, issue_id INTEGER NOT NULL,
        evidence_id INTEGER NOT NULL UNIQUE, subject_identity TEXT NOT NULL, relation TEXT NOT NULL,
        checked_context_json TEXT NOT NULL, limits TEXT NOT NULL, validated_by TEXT NOT NULL,
        validated_at TEXT NOT NULL, FOREIGN KEY(entry_id) REFERENCES governed_challenge_entries(id))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS governed_challenge_closure_assessments (
        id INTEGER PRIMARY KEY AUTOINCREMENT, entry_id INTEGER NOT NULL, issue_id INTEGER NOT NULL,
        grounds_digest TEXT NOT NULL, related_issue_id INTEGER, related_grounds_digest TEXT,
        disposition_state TEXT NOT NULL, evidence_id INTEGER NOT NULL,
        assessment_scope TEXT NOT NULL, basis TEXT NOT NULL, limitations TEXT NOT NULL,
        recorded_by TEXT NOT NULL, recorded_at TEXT NOT NULL,
        FOREIGN KEY(entry_id) REFERENCES governed_challenge_entries(id))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS governed_challenge_applicability_assessments (
        id INTEGER PRIMARY KEY AUTOINCREMENT, entry_id INTEGER NOT NULL,
        predecessor_issue_id INTEGER NOT NULL, successor_issue_id INTEGER NOT NULL,
        predecessor_grounds_digest TEXT NOT NULL, old_subject_identity TEXT NOT NULL,
        new_subject_identity TEXT, change_kind TEXT NOT NULL,
        source_entry_identifier TEXT, source_action_id TEXT,
        source_action_agreed_version INTEGER, source_criteria_identity TEXT,
        source_execution_reference_id INTEGER, source_artifact_reference_id INTEGER,
        material_evidence_id INTEGER,
        supporting_evidence_ids_json TEXT NOT NULL, basis TEXT NOT NULL,
        assessment_scope TEXT NOT NULL, limitations TEXT NOT NULL,
        review_reference_id INTEGER, recorded_by TEXT NOT NULL, recorded_at TEXT NOT NULL,
        FOREIGN KEY(entry_id) REFERENCES governed_challenge_entries(id))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS governed_challenge_successor_relationships (
        id INTEGER PRIMARY KEY AUTOINCREMENT, entry_id INTEGER NOT NULL, predecessor_issue_id INTEGER NOT NULL UNIQUE,
        successor_issue_id INTEGER NOT NULL, evidence_id INTEGER UNIQUE, change_kind TEXT NOT NULL,
        relationship_json TEXT NOT NULL, authoritative_source_identifier TEXT,
        applicability_assessment_id INTEGER NOT NULL,
        recorded_by TEXT NOT NULL, recorded_at TEXT NOT NULL,
        FOREIGN KEY(entry_id) REFERENCES governed_challenge_entries(id))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS governed_challenge_successor_reassessments (
        id INTEGER PRIMARY KEY AUTOINCREMENT, entry_id INTEGER NOT NULL,
        relationship_id INTEGER NOT NULL, applicability_assessment_id INTEGER NOT NULL UNIQUE,
        recorded_by TEXT NOT NULL, recorded_at TEXT NOT NULL,
        FOREIGN KEY(entry_id) REFERENCES governed_challenge_entries(id))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS governed_challenge_links (
        id INTEGER PRIMARY KEY AUTOINCREMENT, entry_id INTEGER NOT NULL, issue_id INTEGER NOT NULL,
        workflow_kind TEXT NOT NULL, workflow_identifier TEXT NOT NULL, evidence_id INTEGER NOT NULL,
        chain_json TEXT NOT NULL DEFAULT '{}',
        obligation_state TEXT NOT NULL DEFAULT 'unverified', created_at TEXT NOT NULL, created_by TEXT NOT NULL,
        FOREIGN KEY(entry_id) REFERENCES governed_challenge_entries(id))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS governed_challenge_response_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT, entry_id INTEGER NOT NULL, issue_id INTEGER NOT NULL,
        response_json TEXT NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL, created_by TEXT NOT NULL,
        FOREIGN KEY(entry_id) REFERENCES governed_challenge_entries(id))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS governed_challenge_disposition_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT, entry_id INTEGER NOT NULL, issue_id INTEGER NOT NULL,
        disposition_state TEXT NOT NULL, disposition_json TEXT NOT NULL, reason TEXT NOT NULL,
        created_at TEXT NOT NULL, created_by TEXT NOT NULL, FOREIGN KEY(entry_id) REFERENCES governed_challenge_entries(id))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS governed_challenge_receipts (
        id INTEGER PRIMARY KEY AUTOINCREMENT, idempotency_key TEXT NOT NULL UNIQUE,
        challenge_identifier TEXT NOT NULL, canonical_payload_json TEXT NOT NULL,
        receipt_json TEXT NOT NULL, created_at TEXT NOT NULL)""")
    link_columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(governed_challenge_links)").fetchall()}
    if "obligation_state" not in link_columns:
        conn.execute("ALTER TABLE governed_challenge_links ADD COLUMN obligation_state TEXT NOT NULL DEFAULT 'unverified'")
    successor_columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(governed_challenge_successor_relationships)").fetchall()}
    if "authoritative_source_identifier" not in successor_columns:
        conn.execute("ALTER TABLE governed_challenge_successor_relationships ADD COLUMN authoritative_source_identifier TEXT")
    if "applicability_assessment_id" not in successor_columns:
        conn.execute("ALTER TABLE governed_challenge_successor_relationships ADD COLUMN applicability_assessment_id INTEGER")
    if "chain_json" not in link_columns:
        conn.execute("ALTER TABLE governed_challenge_links ADD COLUMN chain_json TEXT NOT NULL DEFAULT '{}'")
    applicability_columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(governed_challenge_applicability_assessments)").fetchall()}
    for column, declaration in (
        ("successor_grounds_digest", "TEXT"),
        ("source_action_agreed_version", "INTEGER"),
        ("source_criteria_identity", "TEXT"),
        ("source_artifact_reference_id", "INTEGER"),
    ):
        if column not in applicability_columns:
            conn.execute(f"ALTER TABLE governed_challenge_applicability_assessments ADD COLUMN {column} {declaration}")
    closure_columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(governed_challenge_closure_assessments)").fetchall()}
    for column, declaration in (("related_issue_id", "INTEGER"), ("related_grounds_digest", "TEXT")):
        if column not in closure_columns:
            conn.execute(f"ALTER TABLE governed_challenge_closure_assessments ADD COLUMN {column} {declaration}")
    # A particular authoritative relationship source cannot silently be
    # repurposed as proof for a second successor.  Earlier relationships stay
    # immutable history; a later independent source is required instead.
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_challenge_successor_authoritative_source ON governed_challenge_successor_relationships(authoritative_source_identifier) WHERE authoritative_source_identifier IS NOT NULL")
    for table in ("governed_challenge_events", "governed_challenge_amendments", "governed_challenge_evidence", "governed_challenge_validation_assessments", "governed_challenge_closure_assessments", "governed_challenge_applicability_assessments", "governed_challenge_successor_relationships", "governed_challenge_successor_reassessments", "governed_challenge_links", "governed_challenge_response_history", "governed_challenge_disposition_history"):
        conn.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_no_update BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT, 'challenge_register_history_immutable'); END")
        conn.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_no_delete BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT, 'challenge_register_history_immutable'); END")


def _entry(conn: sqlite3.Connection, identifier: Any) -> dict[str, Any]:
    key = _identifier(identifier, "challenge_register_identifier_invalid")
    row = conn.execute("SELECT * FROM governed_challenge_entries WHERE challenge_identifier=?", (key,)).fetchone()
    if row is None:
        raise ValueError("challenge_register_not_found")
    return dict(row)


def _issue(conn: sqlite3.Connection, item: Mapping[str, Any], issue_identifier: Any) -> dict[str, Any]:
    key = _identifier(issue_identifier, "challenge_register_issue_identifier_invalid")
    row = conn.execute("SELECT * FROM governed_challenge_issues WHERE entry_id=? AND issue_identifier=?", (item["id"], key)).fetchone()
    if row is None:
        raise ValueError("challenge_register_issue_not_found")
    return dict(row)


def _event(conn: sqlite3.Connection, item: Mapping[str, Any], issue_id: int | None, event: str, actor: str, prior: int, resulting: int, reason: str, details: Mapping[str, Any]) -> int:
    cursor = conn.execute("INSERT INTO governed_challenge_events (entry_id,issue_id,event_type,actor,occurred_at,prior_entry_version,resulting_entry_version,reason,details_json) VALUES (?,?,?,?,?,?,?,?,?)", (item["id"], issue_id, event, actor, now(), prior, resulting, reason, _json(details)))
    return int(cursor.lastrowid)


def _receipt(conn: sqlite3.Connection, key: str, canonical: Mapping[str, Any]) -> dict[str, Any] | None:
    row = conn.execute("SELECT canonical_payload_json,receipt_json FROM governed_challenge_receipts WHERE idempotency_key=?", (key,)).fetchone()
    if row is None:
        return None
    if str(row[0]) != _json(canonical):
        raise ValueError("challenge_register_idempotency_conflict")
    result = _loads(row[1], {})
    result["historical_receipt"] = True
    return result


def _grounds_digest(grounds: str) -> str:
    import hashlib
    return hashlib.sha256(grounds.encode("utf-8")).hexdigest()


def _grounds_revision_digest(conn: sqlite3.Connection, issue: Mapping[str, Any]) -> str:
    """Identify the immutable original grounds together with recorded amendments.

    The original grounds column is intentionally never overwritten.  An
    assessment that has a consequence must nevertheless be tied to the
    currently recorded grounds context, rather than silently surviving a
    later clarification.
    """
    amendments = [str(row[0]) for row in conn.execute(
        "SELECT changed_material FROM governed_challenge_amendments WHERE issue_id=? ORDER BY id",
        (issue["id"],),
    ).fetchall()]
    return _grounds_digest(_json({"original": issue["grounds"], "amendments": amendments}))


def _validated_evidence(conn: sqlite3.Connection, item: Mapping[str, Any], issue: Mapping[str, Any], evidence: Mapping[str, Any], relation: str) -> dict[str, Any]:
    """Return an immutable authorised validation, not a caller-supplied flag.

    The checks are deliberately bounded to local permitted facts: exact entry,
    issue, subject identity, reference and relationship.  They do not claim to
    fetch or prove restricted external content.
    """
    row = conn.execute("SELECT * FROM governed_challenge_validation_assessments WHERE evidence_id=? AND entry_id=? AND issue_id=? AND subject_identity=? AND relation=?", (evidence["id"], item["id"], issue["id"], item["subject_identity"], relation)).fetchone()
    if row is None:
        raise ValueError("challenge_register_evidence_unsubstantiated")
    result = dict(row)
    context = _loads(result["checked_context_json"], {})
    expected = {"reference_type": evidence["reference_type"], "reference_value": evidence["reference_value"], "subject_identity": item["subject_identity"], "issue_identifier": issue["issue_identifier"], "relation": relation}
    if any(context.get(key) != value for key, value in expected.items()):
        raise ValueError("challenge_register_evidence_unsubstantiated")
    return result


def _has_substantiated_check(reference: Mapping[str, Any]) -> bool:
    return any(
        isinstance(step, Mapping)
        and step.get("step") == "relationship_substantiated"
        and step.get("status") == "passed"
        for step in reference.get("validation_steps", [])
    )


def _authoritative_stage81_entry(conn: sqlite3.Connection, identifier: Any, *, require_verified: bool) -> dict[str, Any]:
    """Read a Stage 81 entry through its service, never from a local claim.

    The challenge register has no power to validate a correction itself.  It
    only consumes the established Stage 81 projection, and fails closed when
    the exact entry is unavailable or no longer applicable.
    """
    try:
        entry = gdr81.get_entry(conn, _identifier(identifier, "challenge_register_authoritative_reference_invalid"))
    except (ValueError, sqlite3.Error) as exc:
        raise ValueError("challenge_register_authoritative_reference_unavailable") from exc
    if require_verified:
        closure = entry.get("closure")
        action = entry.get("active_action")
        if not (
            entry.get("lifecycle_state") == "closed"
            and isinstance(closure, Mapping)
            and closure.get("outcome") == "correction_verified"
            and isinstance(action, Mapping)
            and action.get("execution_status") == "execution_substantiated"
            and action.get("action_id")
            and action.get("execution_reference_id") is not None
        ):
            raise ValueError("challenge_register_authoritative_reference_unsubstantiated")
    return entry


def _authoritative_targets(entry: Mapping[str, Any]) -> set[str]:
    return {
        str(reference["reference_value"])
        for reference in entry.get("references", [])
        if reference.get("relation") == "action_target" and _has_substantiated_check(reference)
    }


def _stage81_verified_chain(conn: sqlite3.Connection, identifier: Any) -> dict[str, Any]:
    """Resolve the immutable Stage 81 correction chain used by a passive link."""
    entry = _authoritative_stage81_entry(conn, identifier, require_verified=True)
    action, closure = entry.get("active_action"), entry.get("closure")
    verification = closure.get("verification") if isinstance(closure, Mapping) else None
    if not isinstance(action, Mapping) or not isinstance(verification, Mapping):
        raise ValueError("challenge_register_authoritative_reference_unsubstantiated")
    try:
        execution_id, artifact_id = int(action["execution_reference_id"]), int(verification["artifact_reference_id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("challenge_register_authoritative_reference_unsubstantiated") from exc
    if verification.get("action_id") != action.get("action_id") or verification.get("execution_reference_id") != execution_id:
        raise ValueError("challenge_register_authoritative_reference_unsubstantiated")
    refs = {int(ref["id"]): ref for ref in entry.get("references", [])}
    execution, artifact = refs.get(execution_id), refs.get(artifact_id)
    binding = artifact.get("verification_binding") if isinstance(artifact, Mapping) else None
    if not (isinstance(execution, Mapping) and isinstance(artifact, Mapping) and isinstance(binding, Mapping)
            and _has_substantiated_check(execution) and _has_substantiated_check(artifact)
            and binding.get("action_id") == action.get("action_id")
            and binding.get("execution_reference_id") == execution_id
            and binding.get("acceptance_criteria_identity") == action.get("acceptance_criteria_identity")):
        raise ValueError("challenge_register_authoritative_reference_unsubstantiated")
    return {"entry_identifier": entry["entry_identifier"], "action_id": action["action_id"],
            "action_agreed_version": action["agreed_version"],
            "acceptance_criteria_identity": action["acceptance_criteria_identity"],
            "execution_reference_id": execution_id, "artifact_reference_id": artifact_id}


def _stage811_requirement_chain(conn: sqlite3.Connection, identifier: Any, requirement_identifier: Any) -> dict[str, Any]:
    """Resolve one current Stage 81.1 obligation from its source correction."""
    correction = _stage81_verified_chain(conn, identifier)
    entry = gdr81.get_entry(conn, correction["entry_identifier"])
    requirement = next((row for row in entry.get("revalidations", [])
                        if row.get("requirement_identifier") == _identifier(requirement_identifier, "challenge_register_follow_through_binding_mismatch")), None)
    origin = requirement.get("origin_action") if isinstance(requirement, Mapping) else None
    if not (isinstance(origin, Mapping)
            and origin.get("action_id") == correction["action_id"]
            and origin.get("agreed_version") == correction["action_agreed_version"]
            and origin.get("acceptance_criteria_identity") == correction["acceptance_criteria_identity"]
            and requirement.get("execution_reference_id") == correction["execution_reference_id"]):
        raise ValueError("challenge_register_follow_through_binding_mismatch")
    return {**correction, "requirement_identifier": requirement["requirement_identifier"],
            "requirement_version": requirement["version"], "target_identity": requirement["target_identity"],
            "criteria_identity": requirement["criteria_identity"],
            "obligation_outstanding": gdr81.revalidation_has_outstanding_obligation(requirement)}


def _substantiate_successor_source(conn: sqlite3.Connection, item: Mapping[str, Any], predecessor: Mapping[str, Any], successor: Mapping[str, Any], evidence: Mapping[str, Any]) -> tuple[str, str, dict[str, Any]]:
    """Return a checked immutable relationship source for one successor.

    All caller-provided context is treated as a locator for the authorised
    Stage 81 record.  It cannot itself establish a later correction, changed
    target, or material change.
    """
    validation = _validated_evidence(conn, item, predecessor, evidence, "successor_relationship")
    context = _loads(validation["checked_context_json"], {}).get("relationship_context")
    if not isinstance(context, Mapping):
        raise ValueError("challenge_register_successor_binding_mismatch")
    kind = context.get("change_kind")
    if kind not in {"subject_version", "later_correction", "material_change"}:
        raise ValueError("challenge_register_successor_binding_mismatch")
    if context.get("predecessor_issue_identifier") != predecessor["issue_identifier"] or context.get("successor_issue_identifier") != successor["issue_identifier"]:
        raise ValueError("challenge_register_successor_binding_mismatch")
    source_identifier = _identifier(context.get("authoritative_entry_identifier"), "challenge_register_successor_binding_mismatch")
    if evidence["reference_value"] != source_identifier:
        raise ValueError("challenge_register_successor_binding_mismatch")
    source = _authoritative_stage81_entry(conn, source_identifier, require_verified=True)
    targets = _authoritative_targets(source)
    if kind == "later_correction":
        # This supports a later correction even where the challenge subject and
        # criteria remain unchanged: the verified later correction must itself
        # have a substantiated action target for this exact subject.
        if item["subject_identity"] not in targets:
            raise ValueError("challenge_register_successor_binding_mismatch")
    elif kind == "subject_version":
        old_identity = _identifier(context.get("predecessor_subject_identity"), "challenge_register_successor_binding_mismatch")
        new_identity = _identifier(context.get("successor_subject_identity"), "challenge_register_successor_binding_mismatch")
        if old_identity != item["subject_identity"] or old_identity == new_identity or not {old_identity, new_identity}.issubset(targets):
            raise ValueError("challenge_register_successor_binding_mismatch")
    else:
        try:
            material_reference_id = int(context.get("material_change_reference_id"))
        except (TypeError, ValueError) as exc:
            raise ValueError("challenge_register_successor_binding_mismatch") from exc
        source_references = {int(reference["id"]): reference for reference in source.get("references", [])}
        material_reference = source_references.get(material_reference_id)
        if material_reference is None or not _has_substantiated_check(material_reference) or item["subject_identity"] not in targets:
            raise ValueError("challenge_register_successor_binding_mismatch")
    return source_identifier, str(kind), dict(context)


def _linked_workflow_state(conn: sqlite3.Connection, item: Mapping[str, Any], issue: Mapping[str, Any], link: Mapping[str, Any]) -> str:
    """Return current authoritative state for one passive workflow link.

    This is used both for display and closure eligibility so a state observed
    while linking cannot be reused after the linked record becomes unavailable
    or inapplicable.
    """
    evidence = dict(conn.execute("SELECT * FROM governed_challenge_evidence WHERE id=?", (link["evidence_id"],)).fetchone() or {})
    if not evidence or evidence.get("reference_value") != link["workflow_identifier"]:
        raise ValueError("challenge_register_follow_through_binding_mismatch")
    _validated_evidence(conn, item, issue, evidence, "follow_through_relationship")
    chain = _loads(link.get("chain_json"), {})
    if link["workflow_kind"] == "stage81":
        current = _stage81_verified_chain(conn, link["workflow_identifier"])
        if any(chain.get(key) != current.get(key) for key in ("entry_identifier", "action_id", "action_agreed_version", "acceptance_criteria_identity", "execution_reference_id", "artifact_reference_id")):
            raise ValueError("challenge_register_follow_through_binding_mismatch")
        return "correction_verified"
    if link["workflow_kind"] == "stage81_1":
        current = _stage811_requirement_chain(conn, link["workflow_identifier"], chain.get("requirement_identifier"))
        if any(chain.get(key) != current.get(key) for key in ("entry_identifier", "action_id", "action_agreed_version", "acceptance_criteria_identity", "execution_reference_id", "artifact_reference_id", "requirement_identifier", "target_identity", "criteria_identity")):
            raise ValueError("challenge_register_follow_through_binding_mismatch")
        return "downstream_outstanding" if current["obligation_outstanding"] else "downstream_not_outstanding"
    raise ValueError("challenge_register_follow_through_binding_mismatch")


def _mutation(conn: sqlite3.Connection, *, identifier: Any, actor: Any, expected_version: Any, idempotency_key: Any, operation: str, reason: Any, payload: Mapping[str, Any], apply: Callable[[dict[str, Any], int], tuple[dict[str, Any], int | None, dict[str, Any]]]) -> dict[str, Any]:
    ensure_tables(conn)
    challenge_id, actor_value, expected, key = _identifier(identifier, "challenge_register_identifier_invalid"), _actor(actor), _version(expected_version), _key(idempotency_key)
    why = _required(reason, "challenge_register_reason_required")
    canonical = {"operation": operation, "challenge_identifier": challenge_id, "actor": actor_value, "expected_version": expected, "reason": why, **payload}
    conn.execute("BEGIN IMMEDIATE")
    try:
        replay = _receipt(conn, key, canonical)
        if replay is not None:
            conn.rollback(); return replay
        item = _entry(conn, challenge_id)
        if int(item["version"]) != expected:
            raise ValueError("challenge_register_version_conflict")
        updates, issue_id, details = apply(item, expected + 1)
        columns = list(updates) + ["version", "updated_at", "updated_by"]
        values = [updates[name] for name in updates] + [expected + 1, now(), actor_value, item["id"]]
        conn.execute(f"UPDATE governed_challenge_entries SET {','.join(f'{name}=?' for name in columns)} WHERE id=?", values)
        event_id = _event(conn, item, issue_id, operation, actor_value, expected, expected + 1, why, details)
        receipt = {"challenge_identifier": challenge_id, "operation": operation, "event_id": event_id, "resulting_version": expected + 1, "historical_receipt": False}
        conn.execute("INSERT INTO governed_challenge_receipts (idempotency_key,challenge_identifier,canonical_payload_json,receipt_json,created_at) VALUES (?,?,?,?,?)", (key, challenge_id, _json(canonical), _json(receipt), now()))
        conn.commit(); return receipt
    except Exception:
        conn.rollback(); raise


def create_challenge(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
    """Operational intake is intentionally unavailable and data is not inspected."""
    raise ValueError("challenge_register_admission_disabled")


def accept(conn: sqlite3.Connection, *, challenge_identifier: Any, recipient_identity: Any = None, recipient_basis: Any = None, actor: Any, expected_version: Any, idempotency_key: Any, reason: Any, assignment_claim: Any = None) -> dict[str, Any]:
    actor_value = _actor(actor)
    # The current authenticated administrator is the only recipient whose
    # authority can be established here.  A supplied name remains a claim.
    recipient = actor_value
    basis = "verified_signed_administrator_session"
    claim = _required(assignment_claim, "challenge_register_assignment_claim_invalid", 256) if assignment_claim is not None else None
    def apply(item: dict[str, Any], _next: int):
        if item["procedural_state"] != "received": raise ValueError("challenge_register_transition_invalid")
        if item["subject_type"] not in SUBJECT_TYPES or item["subject_value"] != item["subject_identity"]:
            raise ValueError("challenge_register_subject_binding_invalid")
        issue_count = conn.execute("SELECT count(*) FROM governed_challenge_issues WHERE entry_id=?", (item["id"],)).fetchone()[0]
        if not 1 <= int(issue_count) <= MAX_ISSUES:
            raise ValueError("challenge_register_issue_limit_exceeded")
        return {"procedural_state": "procedurally_accepted", "recipient_identity": recipient, "recipient_basis": basis, "recipient_claim": claim}, None, {"recipient_identity": recipient, "recipient_basis": basis, "recipient_claim_unverified": claim}
    return _mutation(conn, identifier=challenge_identifier, actor=actor, expected_version=expected_version, idempotency_key=idempotency_key, operation="challenge_accepted", reason=reason, payload={"recipient_identity": recipient, "recipient_basis": basis, "assignment_claim": claim}, apply=apply)


def begin_assessment(conn: sqlite3.Connection, *, challenge_identifier: Any, actor: Any, expected_version: Any, idempotency_key: Any, reason: Any) -> dict[str, Any]:
    def apply(item: dict[str, Any], _next: int):
        if item["procedural_state"] not in {"procedurally_accepted", "reopened"}: raise ValueError("challenge_register_acceptance_required")
        if not item.get("recipient_identity") or not item.get("recipient_basis"): raise ValueError("challenge_register_recipient_unsubstantiated")
        cursor = conn.execute("UPDATE governed_challenge_issues SET issue_state=?,version=version+1,updated_at=?,updated_by=? WHERE entry_id=? AND issue_state=?", ("under_assessment", now(), _actor(actor), item["id"], "unassessed"))
        return {"procedural_state": "under_assessment"}, None, {"accepted_recipient": item["recipient_identity"], "issues_started": int(cursor.rowcount)}
    return _mutation(conn, identifier=challenge_identifier, actor=actor, expected_version=expected_version, idempotency_key=idempotency_key, operation="challenge_assessment_started", reason=reason, payload={}, apply=apply)


def prepare_response(conn: sqlite3.Connection, *, challenge_identifier: Any, actor: Any, expected_version: Any, idempotency_key: Any, reason: Any) -> dict[str, Any]:
    """Record response preparation separately from assessment and closure."""
    def apply(item: dict[str, Any], _next: int):
        if item["procedural_state"] not in {"under_assessment", "reopened"}:
            raise ValueError("challenge_register_transition_invalid")
        return {"procedural_state": "response_in_preparation"}, None, {"response_preparation": True}
    return _mutation(conn, identifier=challenge_identifier, actor=actor, expected_version=expected_version, idempotency_key=idempotency_key, operation="challenge_response_prepared", reason=reason, payload={}, apply=apply)


def mark_responded(conn: sqlite3.Connection, *, challenge_identifier: Any, actor: Any, expected_version: Any, idempotency_key: Any, reason: Any) -> dict[str, Any]:
    """Mark a completed procedural response without calling it closure."""
    def apply(item: dict[str, Any], _next: int):
        if item["procedural_state"] != "response_in_preparation":
            raise ValueError("challenge_register_transition_invalid")
        issues = [dict(row) for row in conn.execute("SELECT * FROM governed_challenge_issues WHERE entry_id=?", (item["id"],)).fetchall()]
        # A procedural response may be recorded while an issue remains open;
        # closure, not this state, enforces every issue's final eligibility.
        return {"procedural_state": "responded"}, None, {"issue_count": len(issues), "response_sent": True}
    return _mutation(conn, identifier=challenge_identifier, actor=actor, expected_version=expected_version, idempotency_key=idempotency_key, operation="challenge_responded", reason=reason, payload={}, apply=apply)


def add_evidence(conn: sqlite3.Connection, *, challenge_identifier: Any, issue_identifier: Any, reference_type: Any, reference_value: Any, relation: Any, validation_basis: Any, actor: Any, expected_version: Any, idempotency_key: Any, reason: Any, supplied_identity_claim: Any = None, validation_receipt: Any = None, validation_steps: Any = None, relationship_context: Any = None) -> dict[str, Any]:
    typ = str(reference_type or "").strip()
    if typ not in SUBJECT_TYPES: raise ValueError("challenge_register_reference_type_invalid")
    value, rel = _identifier(reference_value, "challenge_register_reference_invalid"), _required(relation, "challenge_register_relation_invalid", 128)
    claim = _required(supplied_identity_claim, "challenge_register_identity_claim_invalid", 256) if supplied_identity_claim is not None else None
    if validation_steps is not None or validation_receipt is not None:
        # Caller-provided validation flags have no authority in this register.
        raise ValueError("challenge_register_validation_claim_rejected")
    limits = _required(validation_basis, "challenge_register_validation_basis_required")
    if relationship_context is not None and not isinstance(relationship_context, Mapping):
        raise ValueError("challenge_register_validation_binding_mismatch")
    def apply(item: dict[str, Any], _next: int):
        issue = _issue(conn, item, issue_identifier)
        count = conn.execute("SELECT count(*) FROM governed_challenge_evidence WHERE entry_id=? AND issue_id=?", (item["id"], issue["id"])).fetchone()[0]
        if count >= MAX_REFERENCES: raise ValueError("challenge_register_reference_limit_exceeded")
        actor_value = _actor(actor)
        context = {"reference_type": typ, "reference_value": value, "subject_identity": item["subject_identity"], "issue_identifier": issue["issue_identifier"], "relation": rel}
        # Structured successor applicability is the only supplemental context;
        # its exact values are checked again when the successor is linked.
        if relationship_context is not None:
            context["relationship_context"] = dict(relationship_context)
        cursor = conn.execute("INSERT INTO governed_challenge_evidence (entry_id,issue_id,reference_type,reference_value,subject_identity,relation,validation_steps_json,supplied_identity_claim,validated_by,created_at,created_by) VALUES (?,?,?,?,?,?,?,?,?,?,?)", (item["id"], issue["id"], typ, value, item["subject_identity"], rel, _json([]), claim, actor_value, now(), actor_value))
        evidence_id = int(cursor.lastrowid)
        conn.execute("INSERT INTO governed_challenge_validation_assessments (entry_id,issue_id,evidence_id,subject_identity,relation,checked_context_json,limits,validated_by,validated_at) VALUES (?,?,?,?,?,?,?,?,?)", (item["id"], issue["id"], evidence_id, item["subject_identity"], rel, _json(context), limits, actor_value, now()))
        return {}, int(issue["id"]), {"evidence_id": evidence_id, "issue_identifier": issue["issue_identifier"], "relation": rel, "validation": "authorised_local_binding_check"}
    return _mutation(conn, identifier=challenge_identifier, actor=actor, expected_version=expected_version, idempotency_key=idempotency_key, operation="challenge_evidence_recorded", reason=reason, payload={"issue_identifier": _identifier(issue_identifier, "challenge_register_issue_identifier_invalid"), "reference_type": typ, "reference_value": value, "relation": rel, "validation_basis": limits}, apply=apply)


def _evidence(conn: sqlite3.Connection, item: Mapping[str, Any], issue: Mapping[str, Any], evidence_id: Any, relation: str) -> dict[str, Any]:
    try: numeric = int(evidence_id)
    except (TypeError, ValueError) as exc: raise ValueError("challenge_register_evidence_invalid") from exc
    row = conn.execute("SELECT * FROM governed_challenge_evidence WHERE id=? AND entry_id=? AND issue_id=? AND relation=?", (numeric, item["id"], issue["id"], relation)).fetchone()
    if row is None: raise ValueError("challenge_register_evidence_binding_mismatch")
    result = dict(row)
    if result["subject_identity"] != item["subject_identity"]:
        raise ValueError("challenge_register_evidence_unsubstantiated")
    _validated_evidence(conn, item, issue, result, relation)
    return result


def amend(conn: sqlite3.Connection, *, challenge_identifier: Any, issue_identifier: Any, changed_material: Any, actor: Any, expected_version: Any, idempotency_key: Any, reason: Any) -> dict[str, Any]:
    material = _required(changed_material, "challenge_register_amendment_invalid")
    def apply(item: dict[str, Any], _next: int):
        issue = _issue(conn, item, issue_identifier)
        count = conn.execute("SELECT count(*) FROM governed_challenge_amendments WHERE entry_id=?", (item["id"],)).fetchone()[0]
        if count >= MAX_AMENDMENTS: raise ValueError("challenge_register_amendment_limit_exceeded")
        conn.execute("INSERT INTO governed_challenge_amendments (entry_id,issue_id,changed_material,reason,created_at,created_by) VALUES (?,?,?,?,?,?)", (item["id"], issue["id"], material, _required(reason, "challenge_register_reason_required"), now(), _actor(actor)))
        return {}, int(issue["id"]), {"issue_identifier": issue["issue_identifier"], "amendment_recorded": True}
    return _mutation(conn, identifier=challenge_identifier, actor=actor, expected_version=expected_version, idempotency_key=idempotency_key, operation="challenge_amended", reason=reason, payload={"issue_identifier": _identifier(issue_identifier, "challenge_register_issue_identifier_invalid"), "changed_material": material}, apply=apply)


def request_information(conn: sqlite3.Connection, *, challenge_identifier: Any, issue_identifier: Any, missing_information: Any, responsible_actor: Any, review_on: Any = None, review_trigger: Any = None, actor: Any, expected_version: Any, idempotency_key: Any, reason: Any) -> dict[str, Any]:
    """Record why an issue remains open and who owns its review."""
    missing, responsible = _required(missing_information, "challenge_register_missing_information_required"), _actor(responsible_actor)
    due, trigger = (str(review_on or "").strip() or None, str(review_trigger or "").strip() or None)
    if not due and not trigger:
        raise ValueError("challenge_register_information_review_required")
    def apply(item: dict[str, Any], _next: int):
        issue = _issue(conn, item, issue_identifier)
        if issue["issue_state"] != "unassessed":
            raise ValueError("challenge_register_issue_transition_invalid")
        record = {"missing_information": missing, "responsible_actor": responsible, "reason": _required(reason, "challenge_register_reason_required"), "review_on": due, "review_trigger": trigger, "recorded_by": _actor(actor), "recorded_at": now()}
        conn.execute("UPDATE governed_challenge_issues SET issue_state=?,information_json=?,version=version+1,updated_at=?,updated_by=? WHERE id=?", ("awaiting_information", _json(record), now(), _actor(actor), issue["id"]))
        return {}, int(issue["id"]), {"issue_identifier": issue["issue_identifier"], "new_state": "awaiting_information", "information": record}
    return _mutation(conn, identifier=challenge_identifier, actor=actor, expected_version=expected_version, idempotency_key=idempotency_key, operation="issue_information_requested", reason=reason, payload={"issue_identifier": _identifier(issue_identifier, "challenge_register_issue_identifier_invalid"), "missing_information": missing, "responsible_actor": responsible, "review_on": due, "review_trigger": trigger}, apply=apply)


def resume_issue_assessment(conn: sqlite3.Connection, *, challenge_identifier: Any, issue_identifier: Any, actor: Any, expected_version: Any, idempotency_key: Any, reason: Any) -> dict[str, Any]:
    """The explicit approved transition from awaiting information to assessment."""
    def apply(item: dict[str, Any], _next: int):
        issue = _issue(conn, item, issue_identifier)
        if issue["issue_state"] != "awaiting_information":
            raise ValueError("challenge_register_issue_transition_invalid")
        conn.execute("UPDATE governed_challenge_issues SET issue_state=?,version=version+1,updated_at=?,updated_by=? WHERE id=?", ("under_assessment", now(), _actor(actor), issue["id"]))
        return {}, int(issue["id"]), {"issue_identifier": issue["issue_identifier"], "new_state": "under_assessment"}
    return _mutation(conn, identifier=challenge_identifier, actor=actor, expected_version=expected_version, idempotency_key=idempotency_key, operation="issue_assessment_resumed", reason=reason, payload={"issue_identifier": _identifier(issue_identifier, "challenge_register_issue_identifier_invalid")}, apply=apply)


def respond(conn: sqlite3.Connection, *, challenge_identifier: Any, issue_identifier: Any, answer: Any, evidence_ids: Any, limitations: Any, actor: Any, expected_version: Any, idempotency_key: Any, reason: Any) -> dict[str, Any]:
    text, limits = _required(answer, "challenge_register_response_required"), _required(limitations, "challenge_register_response_limits_required")
    if not isinstance(evidence_ids, list) or not evidence_ids or len(evidence_ids) > MAX_REFERENCES: raise ValueError("challenge_register_response_evidence_invalid")
    def apply(item: dict[str, Any], _next: int):
        issue = _issue(conn, item, issue_identifier)
        if issue["issue_state"] != "under_assessment": raise ValueError("challenge_register_issue_transition_invalid")
        refs = [_evidence(conn, item, issue, evidence_id, "response_evidence") for evidence_id in evidence_ids]
        response = {"answer": text, "evidence_ids": [ref["id"] for ref in refs], "limitations": limits, "actor": _actor(actor), "recorded_at": now()}
        conn.execute("UPDATE governed_challenge_issues SET issue_state=?,response_json=?,version=version+1,updated_at=?,updated_by=? WHERE id=?", ("answered", _json(response), now(), _actor(actor), issue["id"]))
        conn.execute("INSERT INTO governed_challenge_response_history (entry_id,issue_id,response_json,reason,created_at,created_by) VALUES (?,?,?,?,?,?)", (item["id"], issue["id"], _json(response), _required(reason, "challenge_register_reason_required"), now(), _actor(actor)))
        return {}, int(issue["id"]), {"issue_identifier": issue["issue_identifier"], "new_state": "answered"}
    return _mutation(conn, identifier=challenge_identifier, actor=actor, expected_version=expected_version, idempotency_key=idempotency_key, operation="issue_answered", reason=reason, payload={"issue_identifier": _identifier(issue_identifier, "challenge_register_issue_identifier_invalid"), "answer": text, "evidence_ids": evidence_ids, "limitations": limits}, apply=apply)


def record_closure_assessment(conn: sqlite3.Connection, *, challenge_identifier: Any, issue_identifier: Any, disposition: Any, evidence_id: Any, assessment_scope: Any, basis: Any, limitations: Any, actor: Any, expected_version: Any, idempotency_key: Any, reason: Any, related_issue_identifier: Any = None) -> dict[str, Any]:
    """Record an attributable administrative, not externally-proven, judgment."""
    state = str(disposition or "").strip()
    if state not in {"withdrawn", "outside_scope", "duplicate"}:
        raise ValueError("challenge_register_disposition_invalid")
    scope = _required(assessment_scope, "challenge_register_closure_assessment_scope_required")
    basis_text = _required(basis, "challenge_register_disposition_basis_required")
    limits = _required(limitations, "challenge_register_disposition_limits_required")
    def apply(item: dict[str, Any], _next: int):
        issue = _issue(conn, item, issue_identifier)
        relation = "duplicate_evidence" if state == "duplicate" else "disposition_evidence"
        evidence = _evidence(conn, item, issue, evidence_id, relation)
        related = None
        if state == "duplicate":
            related = _issue(conn, item, related_issue_identifier)
            if related["id"] == issue["id"] or related["grounds"] != issue["grounds"] or evidence["reference_value"] != related["issue_identifier"]:
                raise ValueError("challenge_register_duplicate_binding_mismatch")
        elif related_issue_identifier is not None:
            raise ValueError("challenge_register_duplicate_binding_mismatch")
        cursor = conn.execute("INSERT INTO governed_challenge_closure_assessments (entry_id,issue_id,grounds_digest,related_issue_id,related_grounds_digest,disposition_state,evidence_id,assessment_scope,basis,limitations,recorded_by,recorded_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (item["id"], issue["id"], _grounds_revision_digest(conn, issue), related["id"] if related else None, _grounds_revision_digest(conn, related) if related else None, state, evidence["id"], scope, basis_text, limits, _actor(actor), now()))
        return {}, int(issue["id"]), {"assessment_id": int(cursor.lastrowid), "issue_identifier": issue["issue_identifier"], "disposition": state, "assessment_kind": "administrative_judgment"}
    return _mutation(conn, identifier=challenge_identifier, actor=actor, expected_version=expected_version, idempotency_key=idempotency_key, operation="issue_closure_assessment_recorded", reason=reason, payload={"issue_identifier": _identifier(issue_identifier, "challenge_register_issue_identifier_invalid"), "disposition": state, "evidence_id": evidence_id, "assessment_scope": scope, "basis": basis_text, "limitations": limits, "related_issue_identifier": related_issue_identifier}, apply=apply)


def record_independent_issue_assessment(conn: sqlite3.Connection, *, conclusion: Any = None, assessment_scope: Any = None, basis: Any = None, **kwargs: Any) -> dict[str, Any]:
    """Deprecated name retained for local callers; supplied conclusion is not proof."""
    del conclusion
    return record_closure_assessment(conn, assessment_scope=assessment_scope or "registered challenge issues", basis=basis or kwargs.get("reason"), **kwargs)


def set_disposition(conn: sqlite3.Connection, *, challenge_identifier: Any, issue_identifier: Any, disposition: Any, basis: Any, limitations: Any, evidence_id: Any, actor: Any, expected_version: Any, idempotency_key: Any, reason: Any, duplicate_issue_identifier: Any = None, closure_assessment_id: Any = None, independent_assessment_id: Any = None, no_independent_issue_unanswered: Any = None) -> dict[str, Any]:
    state = str(disposition or "").strip()
    if state not in {"declined_with_reasons", "withdrawn", "outside_scope", "duplicate"}: raise ValueError("challenge_register_disposition_invalid")
    basis_text, limits = _required(basis, "challenge_register_disposition_basis_required"), _required(limitations, "challenge_register_disposition_limits_required")
    if no_independent_issue_unanswered is not None:
        raise ValueError("challenge_register_validation_claim_rejected")
    if closure_assessment_id is None:
        closure_assessment_id = independent_assessment_id
    def apply(item: dict[str, Any], _next: int):
        issue = _issue(conn, item, issue_identifier)
        allowed = {"unassessed", "under_assessment", "answered"} if state == "declined_with_reasons" else {"unassessed", "awaiting_information"}
        if state == "duplicate" and issue["issue_state"] == "under_assessment":
            reopened_disposition_id = issue.get("reopened_duplicate_disposition_id")
            reopened = conn.execute("SELECT id FROM governed_challenge_disposition_history WHERE id=? AND entry_id=? AND issue_id=? AND disposition_state='duplicate'", (reopened_disposition_id, item["id"], issue["id"])).fetchone()
            if reopened is not None:
                allowed = set(allowed) | {"under_assessment"}
        if issue["issue_state"] not in allowed: raise ValueError("challenge_register_issue_transition_invalid")
        relation = "duplicate_evidence" if state == "duplicate" else "disposition_evidence"
        evidence = _evidence(conn, item, issue, evidence_id, relation)
        assessment_id = None
        if state in {"withdrawn", "outside_scope", "duplicate"}:
            try: assessment_id = int(closure_assessment_id)
            except (TypeError, ValueError) as exc: raise ValueError("challenge_register_closure_assessment_required") from exc
            assessment = conn.execute("SELECT * FROM governed_challenge_closure_assessments WHERE id=? AND entry_id=? AND issue_id=?", (assessment_id, item["id"], issue["id"])).fetchone()
            if (assessment is None or assessment["grounds_digest"] != _grounds_revision_digest(conn, issue)
                    or assessment["disposition_state"] != state
                    or int(assessment["evidence_id"]) != int(evidence["id"])
                    or not assessment["assessment_scope"] or not assessment["basis"] or not assessment["limitations"]):
                raise ValueError("challenge_register_closure_assessment_required")
        duplicate_id = None
        if state == "duplicate":
            duplicate = _issue(conn, item, duplicate_issue_identifier)
            if (duplicate["id"] == issue["id"] or duplicate["grounds"] != issue["grounds"]
                    or assessment["related_issue_id"] != duplicate["id"]
                    or assessment["related_grounds_digest"] != _grounds_revision_digest(conn, duplicate)):
                raise ValueError("challenge_register_duplicate_binding_mismatch")
            if evidence["reference_value"] != duplicate["issue_identifier"]:
                raise ValueError("challenge_register_duplicate_binding_mismatch")
            duplicate_id = int(duplicate["id"])
        record = {"basis": basis_text, "limitations": limits, "evidence_id": evidence["id"], "actor": _actor(actor), "recorded_at": now(), "duplicate_issue_identifier": duplicate_issue_identifier if state == "duplicate" else None, "closure_assessment_id": assessment_id}
        conn.execute("UPDATE governed_challenge_issues SET issue_state=?,disposition_json=?,duplicate_issue_id=?,reopened_duplicate_disposition_id=NULL,version=version+1,updated_at=?,updated_by=? WHERE id=?", (state, _json(record), duplicate_id, now(), _actor(actor), issue["id"]))
        conn.execute("INSERT INTO governed_challenge_disposition_history (entry_id,issue_id,disposition_state,disposition_json,reason,created_at,created_by) VALUES (?,?,?,?,?,?,?)", (item["id"], issue["id"], state, _json(record), _required(reason, "challenge_register_reason_required"), now(), _actor(actor)))
        return {}, int(issue["id"]), {"issue_identifier": issue["issue_identifier"], "new_state": state, "evidence_id": evidence["id"]}
    return _mutation(conn, identifier=challenge_identifier, actor=actor, expected_version=expected_version, idempotency_key=idempotency_key, operation="issue_disposed", reason=reason, payload={"issue_identifier": _identifier(issue_identifier, "challenge_register_issue_identifier_invalid"), "disposition": state, "basis": basis_text, "limitations": limits, "evidence_id": evidence_id, "duplicate_issue_identifier": duplicate_issue_identifier, "closure_assessment_id": closure_assessment_id}, apply=apply)


def defer_issue(conn: sqlite3.Connection, *, challenge_identifier: Any, issue_identifier: Any, owner: Any, review_on: Any = None, review_trigger: Any = None, actor: Any, expected_version: Any, idempotency_key: Any, reason: Any) -> dict[str, Any]:
    owner_value = _actor(owner); due, trigger = (str(review_on or "").strip() or None, str(review_trigger or "").strip() or None)
    if not due and not trigger: raise ValueError("challenge_register_deferral_review_required")
    def apply(item: dict[str, Any], _next: int):
        issue = _issue(conn, item, issue_identifier)
        if issue["issue_state"] not in {"unassessed", "awaiting_information", "under_assessment", "answered", "linked_to_follow_through"}: raise ValueError("challenge_register_issue_transition_invalid")
        record = {"owner": owner_value, "reason": _required(reason, "challenge_register_reason_required"), "review_on": due, "review_trigger": trigger, "recorded_by": _actor(actor), "recorded_at": now()}
        conn.execute("UPDATE governed_challenge_issues SET deferral_json=?,version=version+1,updated_at=?,updated_by=? WHERE id=?", (_json(record), now(), _actor(actor), issue["id"]))
        return {}, int(issue["id"]), {"issue_identifier": issue["issue_identifier"], "underlying_state": issue["issue_state"], "deferral": record}
    return _mutation(conn, identifier=challenge_identifier, actor=actor, expected_version=expected_version, idempotency_key=idempotency_key, operation="issue_deferred", reason=reason, payload={"issue_identifier": _identifier(issue_identifier, "challenge_register_issue_identifier_invalid"), "owner": owner_value, "review_on": due, "review_trigger": trigger}, apply=apply)


def link_follow_through(conn: sqlite3.Connection, *, challenge_identifier: Any, issue_identifier: Any, workflow_kind: Any, workflow_identifier: Any, evidence_id: Any, substantive_response: Any, actor: Any, expected_version: Any, idempotency_key: Any, reason: Any, requirement_identifier: Any = None) -> dict[str, Any]:
    kind, target, response = _required(workflow_kind, "challenge_register_follow_through_invalid", 64), _identifier(workflow_identifier, "challenge_register_follow_through_invalid"), _required(substantive_response, "challenge_register_follow_through_response_required")
    if kind not in {"stage81", "stage81_1"}: raise ValueError("challenge_register_follow_through_invalid")
    def apply(item: dict[str, Any], _next: int):
        issue = _issue(conn, item, issue_identifier)
        if issue["issue_state"] not in {"under_assessment", "answered"}:
            raise ValueError("challenge_register_issue_transition_invalid")
        evidence = _evidence(conn, item, issue, evidence_id, "follow_through_relationship")
        if evidence["reference_value"] != target:
            raise ValueError("challenge_register_follow_through_binding_mismatch")
        # A passive link is never a claim by itself.  It records the exact
        # authorised current chain and is checked again whenever it is used.
        chain = (_stage81_verified_chain(conn, target) if kind == "stage81"
                 else _stage811_requirement_chain(conn, target, requirement_identifier))
        conn.execute("INSERT INTO governed_challenge_links (entry_id,issue_id,workflow_kind,workflow_identifier,evidence_id,chain_json,created_at,created_by) VALUES (?,?,?,?,?,?,?,?)", (item["id"], issue["id"], kind, target, evidence["id"], _json(chain), now(), _actor(actor)))
        record = {"answer": response, "evidence_ids": [evidence["id"]], "limitations": "passive link only", "actor": _actor(actor), "recorded_at": now()}
        conn.execute("UPDATE governed_challenge_issues SET issue_state=?,response_json=?,version=version+1,updated_at=?,updated_by=? WHERE id=?", ("linked_to_follow_through", _json(record), now(), _actor(actor), issue["id"]))
        conn.execute("INSERT INTO governed_challenge_response_history (entry_id,issue_id,response_json,reason,created_at,created_by) VALUES (?,?,?,?,?,?)", (item["id"], issue["id"], _json(record), _required(reason, "challenge_register_reason_required"), now(), _actor(actor)))
        return {}, int(issue["id"]), {"issue_identifier": issue["issue_identifier"], "workflow_kind": kind, "workflow_identifier": target, "requirement_identifier": chain.get("requirement_identifier"), "evidence_id": evidence["id"]}
    return _mutation(conn, identifier=challenge_identifier, actor=actor, expected_version=expected_version, idempotency_key=idempotency_key, operation="issue_follow_through_linked", reason=reason, payload={"issue_identifier": _identifier(issue_identifier, "challenge_register_issue_identifier_invalid"), "workflow_kind": kind, "workflow_identifier": target, "requirement_identifier": requirement_identifier, "evidence_id": evidence_id, "substantive_response": response}, apply=apply)


def record_applicability_assessment(conn: sqlite3.Connection, *, challenge_identifier: Any,
                                    predecessor_issue_identifier: Any, successor_issue_identifier: Any,
                                    change_kind: Any, source_entry_identifier: Any = None,
                                    source_action_id: Any = None, source_execution_reference_id: Any = None,
                                    material_evidence_id: Any = None, supporting_evidence_ids: Any = None,
                                    old_subject_identity: Any = None, new_subject_identity: Any = None,
                                    basis: Any = None, assessment_scope: Any = None, limitations: Any = None,
                                    review_reference_id: Any = None, actor: Any = None,
                                    expected_version: Any = None, idempotency_key: Any = None, reason: Any = None) -> dict[str, Any]:
    """Record the approved bounded administrative applicability judgment."""
    kind = str(change_kind or "").strip()
    if kind not in {"subject_version", "later_correction", "material_change"}:
        raise ValueError("challenge_register_applicability_change_kind_invalid")
    scope, basis_text, limits = (_required(assessment_scope, "challenge_register_applicability_scope_required"),
                                 _required(basis, "challenge_register_applicability_basis_required"),
                                 _required(limitations, "challenge_register_applicability_limits_required"))
    if not isinstance(supporting_evidence_ids, list) or not supporting_evidence_ids or len(supporting_evidence_ids) > MAX_REFERENCES:
        raise ValueError("challenge_register_applicability_evidence_required")
    def apply(item: dict[str, Any], _next: int):
        predecessor = _issue(conn, item, predecessor_issue_identifier)
        successor = _issue(conn, item, successor_issue_identifier)
        if predecessor["id"] == successor["id"]:
            raise ValueError("challenge_register_applicability_binding_mismatch")
        old_identity = _identifier(old_subject_identity or item["subject_identity"], "challenge_register_applicability_binding_mismatch")
        new_identity = _identifier(new_subject_identity or old_identity, "challenge_register_applicability_binding_mismatch")
        if old_identity != item["subject_identity"] or (kind == "subject_version" and old_identity == new_identity):
            raise ValueError("challenge_register_applicability_binding_mismatch")
        supporting = []
        for raw in supporting_evidence_ids:
            evidence = _evidence(conn, item, predecessor, raw, "applicability_evidence")
            if evidence["id"] in supporting:
                raise ValueError("challenge_register_applicability_evidence_required")
            supporting.append(evidence["id"])
        source_identifier = action_id = action_version = criteria_identity = execution_id = artifact_id = None
        material_id = None
        if kind in {"later_correction", "subject_version"}:
            source = _stage81_verified_chain(conn, source_entry_identifier)
            source_identifier, action_id = source["entry_identifier"], source["action_id"]
            action_version, criteria_identity = source["action_agreed_version"], source["acceptance_criteria_identity"]
            execution_id, artifact_id = source["execution_reference_id"], source["artifact_reference_id"]
            if source_action_id != action_id or source_execution_reference_id != execution_id:
                raise ValueError("challenge_register_applicability_binding_mismatch")
            targets = _authoritative_targets(gdr81.get_entry(conn, source_identifier))
            required = {old_identity} if kind == "later_correction" else {old_identity, new_identity}
            if not required.issubset(targets):
                raise ValueError("challenge_register_applicability_binding_mismatch")
        else:
            evidence = _evidence(conn, item, predecessor, material_evidence_id, "material_change_evidence")
            material_id = evidence["id"]
            if source_entry_identifier is not None or source_action_id is not None or source_execution_reference_id is not None:
                raise ValueError("challenge_register_applicability_binding_mismatch")
        review_id = None
        if review_reference_id is not None:
            # A review is only a reference to an existing workflow standard;
            # it never elevates a supplied reviewer name.
            review = _evidence(conn, item, predecessor, review_reference_id, "workflow_review_evidence")
            review_id = review["id"]
        cursor = conn.execute("INSERT INTO governed_challenge_applicability_assessments (entry_id,predecessor_issue_id,successor_issue_id,predecessor_grounds_digest,successor_grounds_digest,old_subject_identity,new_subject_identity,change_kind,source_entry_identifier,source_action_id,source_action_agreed_version,source_criteria_identity,source_execution_reference_id,source_artifact_reference_id,material_evidence_id,supporting_evidence_ids_json,basis,assessment_scope,limitations,review_reference_id,recorded_by,recorded_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (item["id"], predecessor["id"], successor["id"], _grounds_revision_digest(conn, predecessor), _grounds_revision_digest(conn, successor), old_identity, new_identity, kind, source_identifier, action_id, action_version, criteria_identity, execution_id, artifact_id, material_id, _json(supporting), basis_text, scope, limits, review_id, _actor(actor), now()))
        return {}, int(predecessor["id"]), {"assessment_id": int(cursor.lastrowid), "assessment_kind": "administrative_applicability_judgment", "predecessor_issue_identifier": predecessor["issue_identifier"], "successor_issue_identifier": successor["issue_identifier"], "change_kind": kind}
    return _mutation(conn, identifier=challenge_identifier, actor=actor, expected_version=expected_version, idempotency_key=idempotency_key, operation="applicability_assessment_recorded", reason=reason, payload={"predecessor_issue_identifier": _identifier(predecessor_issue_identifier, "challenge_register_issue_identifier_invalid"), "successor_issue_identifier": _identifier(successor_issue_identifier, "challenge_register_issue_identifier_invalid"), "change_kind": kind, "source_entry_identifier": source_entry_identifier, "source_action_id": source_action_id, "source_execution_reference_id": source_execution_reference_id, "material_evidence_id": material_evidence_id, "supporting_evidence_ids": supporting_evidence_ids, "old_subject_identity": old_subject_identity, "new_subject_identity": new_subject_identity, "basis": basis_text, "assessment_scope": scope, "limitations": limits, "review_reference_id": review_reference_id}, apply=apply)


def _applicability_assessment(conn: sqlite3.Connection, item: Mapping[str, Any], predecessor: Mapping[str, Any], successor: Mapping[str, Any], assessment_id: Any) -> dict[str, Any]:
    try:
        numeric = int(assessment_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("challenge_register_applicability_assessment_required") from exc
    row = conn.execute("SELECT * FROM governed_challenge_applicability_assessments WHERE id=? AND entry_id=? AND predecessor_issue_id=? AND successor_issue_id=?", (numeric, item["id"], predecessor["id"], successor["id"])).fetchone()
    if row is None:
        raise ValueError("challenge_register_applicability_assessment_required")
    assessment = dict(row)
    if (assessment["predecessor_grounds_digest"] != _grounds_revision_digest(conn, predecessor)
            or assessment.get("successor_grounds_digest") != _grounds_revision_digest(conn, successor)):
        raise ValueError("challenge_register_applicability_stale")
    supporting = _loads(assessment["supporting_evidence_ids_json"], [])
    if not isinstance(supporting, list) or not supporting:
        raise ValueError("challenge_register_applicability_binding_mismatch")
    for evidence_id in supporting:
        _evidence(conn, item, predecessor, evidence_id, "applicability_evidence")
    kind = assessment["change_kind"]
    if kind in {"later_correction", "subject_version"}:
        source = _stage81_verified_chain(conn, assessment["source_entry_identifier"])
        if any(source[key] != assessment[column] for key, column in (
            ("action_id", "source_action_id"),
            ("action_agreed_version", "source_action_agreed_version"),
            ("acceptance_criteria_identity", "source_criteria_identity"),
            ("execution_reference_id", "source_execution_reference_id"),
            ("artifact_reference_id", "source_artifact_reference_id"),
        )):
            raise ValueError("challenge_register_applicability_stale")
        targets = _authoritative_targets(gdr81.get_entry(conn, source["entry_identifier"]))
        expected = {assessment["old_subject_identity"]} if kind == "later_correction" else {assessment["old_subject_identity"], assessment["new_subject_identity"]}
        if not expected.issubset(targets):
            raise ValueError("challenge_register_applicability_stale")
    elif kind == "material_change":
        _evidence(conn, item, predecessor, assessment["material_evidence_id"], "material_change_evidence")
    else:
        raise ValueError("challenge_register_applicability_binding_mismatch")
    if assessment["review_reference_id"] is not None:
        _evidence(conn, item, predecessor, assessment["review_reference_id"], "workflow_review_evidence")
    return assessment


def _successor_relationship_state(conn: sqlite3.Connection, item: Mapping[str, Any], predecessor: Mapping[str, Any]) -> dict[str, Any] | None:
    """Derive current applicability without altering immutable relationship history."""
    relationship_row = conn.execute("SELECT * FROM governed_challenge_successor_relationships WHERE entry_id=? AND predecessor_issue_id=?", (item["id"], predecessor["id"])).fetchone()
    if relationship_row is None:
        return None
    relationship = dict(relationship_row)
    successor_row = conn.execute("SELECT * FROM governed_challenge_issues WHERE id=? AND entry_id=?", (relationship["successor_issue_id"], item["id"])).fetchone()
    if successor_row is None:
        return {"status": "requires_reassessment", "relationship": relationship, "reason": "successor_unavailable"}
    successor = dict(successor_row)
    reassessment = conn.execute("SELECT * FROM governed_challenge_successor_reassessments WHERE relationship_id=? ORDER BY id DESC LIMIT 1", (relationship["id"],)).fetchone()
    assessment_id = reassessment["applicability_assessment_id"] if reassessment is not None else relationship["applicability_assessment_id"]
    try:
        assessment = _applicability_assessment(conn, item, predecessor, successor, assessment_id)
    except ValueError:
        return {"status": "requires_reassessment", "relationship": relationship, "successor": successor, "assessment_id": assessment_id}
    return {"status": "current", "relationship": relationship, "successor": successor, "assessment": assessment, "assessment_id": assessment_id}


def link_successor(conn: sqlite3.Connection, *, challenge_identifier: Any, predecessor_issue_identifier: Any, successor_issue_identifier: Any, applicability_assessment_id: Any, actor: Any, expected_version: Any, idempotency_key: Any, reason: Any) -> dict[str, Any]:
    """Record a passive relationship only from the approved applicability judgment."""
    def apply(item: dict[str, Any], _next: int):
        predecessor = _issue(conn, item, predecessor_issue_identifier)
        successor = _issue(conn, item, successor_issue_identifier)
        if predecessor["id"] == successor["id"]:
            raise ValueError("challenge_register_successor_binding_mismatch")
        assessment = _applicability_assessment(conn, item, predecessor, successor, applicability_assessment_id)
        existing = _successor_relationship_state(conn, item, predecessor)
        assessment_reused = conn.execute("SELECT 1 FROM governed_challenge_successor_relationships WHERE applicability_assessment_id=? UNION SELECT 1 FROM governed_challenge_successor_reassessments WHERE applicability_assessment_id=?", (assessment["id"], assessment["id"])).fetchone()
        if assessment_reused is not None:
            raise ValueError("challenge_register_successor_binding_mismatch")
        if existing is not None:
            relationship = existing["relationship"]
            if relationship["successor_issue_id"] != successor["id"] or existing["status"] == "current":
                raise ValueError("challenge_register_successor_binding_mismatch")
            cursor = conn.execute("INSERT INTO governed_challenge_successor_reassessments (entry_id,relationship_id,applicability_assessment_id,recorded_by,recorded_at) VALUES (?,?,?,?,?)", (item["id"], relationship["id"], assessment["id"], _actor(actor), now()))
            return {}, int(predecessor["id"]), {"predecessor_issue_identifier": predecessor["issue_identifier"], "successor_issue_identifier": successor["issue_identifier"], "applicability_assessment_id": assessment["id"], "reassessment_id": int(cursor.lastrowid), "current_applicability_reestablished": True}
        if predecessor.get("successor_issue_id") is not None:
            raise ValueError("challenge_register_successor_binding_mismatch")
        conn.execute("UPDATE governed_challenge_issues SET successor_issue_id=?,version=version+1,updated_at=?,updated_by=? WHERE id=?", (successor["id"], now(), _actor(actor), predecessor["id"]))
        relationship = {"assessment_scope": assessment["assessment_scope"], "basis": assessment["basis"], "limitations": assessment["limitations"], "old_subject_identity": assessment["old_subject_identity"], "new_subject_identity": assessment["new_subject_identity"]}
        conn.execute("INSERT INTO governed_challenge_successor_relationships (entry_id,predecessor_issue_id,successor_issue_id,evidence_id,change_kind,relationship_json,authoritative_source_identifier,applicability_assessment_id,recorded_by,recorded_at) VALUES (?,?,?,?,?,?,?,?,?,?)", (item["id"], predecessor["id"], successor["id"], None, assessment["change_kind"], _json(relationship), assessment["source_entry_identifier"], assessment["id"], _actor(actor), now()))
        return {}, int(predecessor["id"]), {"predecessor_issue_identifier": predecessor["issue_identifier"], "successor_issue_identifier": successor["issue_identifier"], "applicability_assessment_id": assessment["id"], "change_kind": assessment["change_kind"], "authoritative_source_identifier": assessment["source_entry_identifier"]}
    return _mutation(conn, identifier=challenge_identifier, actor=actor, expected_version=expected_version, idempotency_key=idempotency_key, operation="issue_successor_linked", reason=reason, payload={"predecessor_issue_identifier": _identifier(predecessor_issue_identifier, "challenge_register_issue_identifier_invalid"), "successor_issue_identifier": _identifier(successor_issue_identifier, "challenge_register_issue_identifier_invalid"), "applicability_assessment_id": applicability_assessment_id}, apply=apply)


def _eligible(conn: sqlite3.Connection, item: Mapping[str, Any], issue: Mapping[str, Any]) -> bool:
    if issue.get("successor_issue_id") is not None:
        relationship = _successor_relationship_state(conn, item, issue)
        if relationship is None or relationship["status"] != "current":
            return False
    state = issue["issue_state"]
    if state == "linked_to_follow_through":
        response = _loads(issue.get("response_json"), {})
        links = conn.execute("SELECT * FROM governed_challenge_links WHERE entry_id=? AND issue_id=? AND obligation_state='unverified'", (item["id"], issue["id"])).fetchall()
        if not (response.get("answer") and response.get("evidence_ids") and links):
            return False
        for link in links:
            try:
                _linked_workflow_state(conn, item, issue, dict(link))
            except ValueError:
                return False
        return True
    if state == "answered":
        response = _loads(issue.get("response_json"), {})
        return bool(response.get("answer")) and bool(response.get("evidence_ids")) and bool(response.get("limitations"))
    if state in {"declined_with_reasons", "withdrawn", "outside_scope", "duplicate"}:
        result = _loads(issue.get("disposition_json"), {})
        if not (result.get("basis") and result.get("limitations") and result.get("evidence_id")):
            return False
        if state in {"withdrawn", "outside_scope", "duplicate"}:
            assessment_id = result.get("closure_assessment_id")
            assessment = conn.execute("SELECT * FROM governed_challenge_closure_assessments WHERE id=? AND entry_id=? AND issue_id=?", (assessment_id, item["id"], issue["id"])).fetchone()
            if (assessment is None or assessment["grounds_digest"] != _grounds_revision_digest(conn, issue)
                    or assessment["disposition_state"] != state
                    or int(assessment["evidence_id"]) != int(result["evidence_id"])
                    or not assessment["assessment_scope"] or not assessment["basis"] or not assessment["limitations"]):
                return False
        if state == "duplicate":
            if issue.get("duplicate_issue_id") is None:
                return False
            duplicate = conn.execute("SELECT * FROM governed_challenge_issues WHERE id=? AND entry_id=?", (issue["duplicate_issue_id"], item["id"])).fetchone()
            if (duplicate is None or duplicate["grounds"] != issue["grounds"]
                    or assessment["related_issue_id"] != duplicate["id"]
                    or assessment["related_grounds_digest"] != _grounds_revision_digest(conn, dict(duplicate))):
                return False
            evidence = _evidence(conn, item, issue, result["evidence_id"], "duplicate_evidence")
            _validated_evidence(conn, item, issue, evidence, "duplicate_evidence")
            return evidence["reference_value"] == duplicate["issue_identifier"]
        evidence = _evidence(conn, item, issue, result["evidence_id"], "disposition_evidence")
        _validated_evidence(conn, item, issue, evidence, "disposition_evidence")
        return True
    return False


def close(conn: sqlite3.Connection, *, challenge_identifier: Any, actor: Any, expected_version: Any, idempotency_key: Any, reason: Any) -> dict[str, Any]:
    def apply(item: dict[str, Any], _next: int):
        if item["procedural_state"] not in {"responded", "under_assessment"}: raise ValueError("challenge_register_transition_invalid")
        issues = [dict(row) for row in conn.execute("SELECT * FROM governed_challenge_issues WHERE entry_id=? ORDER BY id", (item["id"],)).fetchall()]
        if not issues or any(not _eligible(conn, item, issue) for issue in issues): raise ValueError("challenge_register_closure_incomplete")
        return {"procedural_state": "closed"}, None, {"issue_count": len(issues), "closure_eligible": True}
    return _mutation(conn, identifier=challenge_identifier, actor=actor, expected_version=expected_version, idempotency_key=idempotency_key, operation="challenge_closed", reason=reason, payload={}, apply=apply)


def reopen_issue(conn: sqlite3.Connection, *, challenge_identifier: Any, issue_identifier: Any, actor: Any, expected_version: Any, idempotency_key: Any, reason: Any) -> dict[str, Any]:
    def apply(item: dict[str, Any], _next: int):
        issue = _issue(conn, item, issue_identifier)
        if issue["issue_state"] not in TERMINAL_ISSUE_STATES: raise ValueError("challenge_register_issue_transition_invalid")
        prior_duplicate_id = None
        if issue["issue_state"] == "duplicate":
            prior = conn.execute("SELECT id FROM governed_challenge_disposition_history WHERE entry_id=? AND issue_id=? AND disposition_state='duplicate' ORDER BY id DESC LIMIT 1", (item["id"], issue["id"])).fetchone()
            if prior is None:
                raise ValueError("challenge_register_duplicate_reopen_history_missing")
            prior_duplicate_id = int(prior["id"])
        conn.execute("UPDATE governed_challenge_issues SET issue_state=?,reopened_duplicate_disposition_id=?,version=version+1,updated_at=?,updated_by=? WHERE id=?", ("under_assessment", prior_duplicate_id, now(), _actor(actor), issue["id"]))
        updates = {"procedural_state": "reopened" if item["procedural_state"] == "closed" else item["procedural_state"]}
        return updates, int(issue["id"]), {"issue_identifier": issue["issue_identifier"], "new_state": "under_assessment", "parent_reopened": item["procedural_state"] == "closed", "reopened_duplicate_disposition_id": prior_duplicate_id}
    return _mutation(conn, identifier=challenge_identifier, actor=actor, expected_version=expected_version, idempotency_key=idempotency_key, operation="issue_reopened", reason=reason, payload={"issue_identifier": _identifier(issue_identifier, "challenge_register_issue_identifier_invalid")}, apply=apply)


def get_challenge(conn: sqlite3.Connection, challenge_identifier: Any) -> dict[str, Any]:
    ensure_tables(conn); item = _entry(conn, challenge_identifier)
    issues = []
    for row in conn.execute("SELECT * FROM governed_challenge_issues WHERE entry_id=? ORDER BY id", (item["id"],)).fetchall():
        issue = dict(row)
        for name in ("requested_outcomes", "response", "disposition", "information", "deferral"):
            issue[name] = _loads(issue.pop(f"{name}_json", None), None)
        issues.append(issue)
    item["issues"] = issues
    item["history"] = [{**dict(row), "details": _loads(row["details_json"], {})} for row in conn.execute("SELECT * FROM governed_challenge_events WHERE entry_id=? ORDER BY id", (item["id"],)).fetchall()]
    item["response_history"] = [{**dict(row), "response": _loads(row["response_json"], {})} for row in conn.execute("SELECT * FROM governed_challenge_response_history WHERE entry_id=? ORDER BY id", (item["id"],)).fetchall()]
    item["disposition_history"] = [{**dict(row), "disposition": _loads(row["disposition_json"], {})} for row in conn.execute("SELECT * FROM governed_challenge_disposition_history WHERE entry_id=? ORDER BY id", (item["id"],)).fetchall()]
    item["closure_assessments"] = [dict(row) for row in conn.execute("SELECT * FROM governed_challenge_closure_assessments WHERE entry_id=? ORDER BY id", (item["id"],)).fetchall()]
    item["applicability_assessments"] = [dict(row) for row in conn.execute("SELECT * FROM governed_challenge_applicability_assessments WHERE entry_id=? ORDER BY id", (item["id"],)).fetchall()]
    item["successor_reassessments"] = [dict(row) for row in conn.execute("SELECT * FROM governed_challenge_successor_reassessments WHERE entry_id=? ORDER BY id", (item["id"],)).fetchall()]
    successor_states: dict[int, dict[str, Any]] = {}
    successor_applicability, successor_reassessment_required = [], []
    for issue in issues:
        if issue.get("successor_issue_id") is None:
            continue
        state = _successor_relationship_state(conn, item, issue)
        if state is None:
            state = {"status": "requires_reassessment"}
        successor_states[int(issue["id"])] = state
        projection = {"issue_identifier": issue["issue_identifier"], "status": state["status"]}
        if state.get("relationship") is not None:
            projection["relationship_id"] = state["relationship"]["id"]
        successor_applicability.append(projection)
        if state["status"] != "current":
            successor_reassessment_required.append(projection)
    item["successor_applicability"] = successor_applicability
    item["successor_relationships_requiring_reassessment"] = successor_reassessment_required
    active, correction_verification, linked_state_unknown = [], [], []
    for row in conn.execute("""SELECT l.*, i.issue_identifier, i.successor_issue_id FROM governed_challenge_links l
                               JOIN governed_challenge_issues i ON i.id=l.issue_id
                               WHERE l.entry_id=? AND l.obligation_state='unverified' ORDER BY l.id""", (item["id"],)).fetchall():
        link = dict(row)
        link["chain"] = _loads(link.get("chain_json"), {})
        # A successor preserves the predecessor link as history but not as a
        # current obligation.  A locally valid challenge link is not a claim
        # that the linked workflow is currently verified or complete.
        successor_state = successor_states.get(int(link["issue_id"]))
        if successor_state is not None and successor_state["status"] == "current":
            continue
        if successor_state is not None:
            linked_state_unknown.append({"issue_identifier": link["issue_identifier"], "workflow_kind": link["workflow_kind"], "workflow_identifier": link["workflow_identifier"], "status": "successor_relationship_requires_reassessment"})
        issue = {"id": link["issue_id"], "issue_identifier": link["issue_identifier"]}
        evidence = dict(conn.execute("SELECT * FROM governed_challenge_evidence WHERE id=?", (link["evidence_id"],)).fetchone())
        try:
            state = _linked_workflow_state(conn, item, issue, link)
        except ValueError:
            linked_state_unknown.append({"issue_identifier": link["issue_identifier"], "workflow_kind": link["workflow_kind"], "workflow_identifier": link["workflow_identifier"], "status": "relationship_unverified"})
            continue
        if link["workflow_kind"] == "stage81":
            correction_verification.append({"workflow_identifier": link["workflow_identifier"], "status": state, "chain": link["chain"]})
        elif link["workflow_kind"] == "stage81_1":
            # Stage 81.1 is a passive current-state projection.  A link is not
            # an obligation by itself: only the authoritative requirement
            # state can make it outstanding.
            if state == "downstream_outstanding":
                active.append({"issue_identifier": link["issue_identifier"], "workflow_kind": link["workflow_kind"], "workflow_identifier": link["workflow_identifier"], "status": "outstanding_authoritative", "chain": link["chain"]})
    item["outstanding_linked_work"] = active
    item["original_correction_verification"] = correction_verification
    item["linked_workflow_state_unknown"] = linked_state_unknown
    verified_keys = {(row["chain"].get("entry_identifier"), row["chain"].get("action_id"), row["chain"].get("execution_reference_id")) for row in correction_verification}
    applicable = [row for row in active if (row["chain"].get("entry_identifier"), row["chain"].get("action_id"), row["chain"].get("execution_reference_id")) in verified_keys]
    item["original_correction_verified_downstream_work_outstanding"] = bool(applicable)
    item["applicable_outstanding_linked_work"] = applicable
    return item


def render_private_status(item: Mapping[str, Any]) -> str:
    """Bounded private display text; no linked workflow is executed here."""
    obligations = item.get("outstanding_linked_work") or []
    if item.get("original_correction_verified_downstream_work_outstanding"):
        return "Original correction verified — downstream work outstanding."
    if item.get("successor_relationships_requiring_reassessment"):
        return "Successor relationship requires reassessment; linked work remains visible."
    if obligations:
        return "Linked downstream work is outstanding; original correction verification is unavailable or unverified."
    if item.get("linked_workflow_state_unknown"):
        return "Linked workflow state is unavailable or unverified; no completion is implied."
    if item.get("original_correction_verification"):
        return "Original correction verification is recorded; no active downstream work is recorded."
    return "No active linked downstream work is recorded."
