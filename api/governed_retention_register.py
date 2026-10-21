"""Stage 84 private synthetic-only retention decision-record foundation.

There is deliberately no admission, real hold, disposal, deletion, redaction,
restoration, export, or execution capability.  Tests may seed the synthetic
fixture tables directly; service and route creation are rejected before body
content can be retained.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Mapping

from api.admin_session_verification import AdminSessionVerificationError, verify_signed_admin_session

R_VALUES = frozenset({"not_due", "due", "under_assessment", "awaiting_information", "assessed", "deferred"})
I_VALUES = frozenset({"not_started", "under_assessment", "awaiting_information", "complete_with_limits", "incomplete", "unavailable"})
E_VALUES = frozenset({"not_assessed", "under_assessment", "pending_missing_information", "eligible_current", "ineligible_current", "stale", "unavailable"})
D_VALUES = frozenset({"none", "proposed_eligible_for_future_scope", "proposed_ineligible_for_future_scope"})
A_VALUES = frozenset({"not_recorded", "approved_current", "not_approved", "stale", "unavailable"})
C_VALUES = frozenset({"not_evaluated", "current", "reassessment_required", "unavailable"})
P_VALUES = frozenset({"recorded", "under_review", "closed", "reopened"})
SUBJECT_TYPES = frozenset({"internal_object_version", "repository_commit", "pull_request", "target_bound_deployment", "retained_artifact_reference", "recovery_bundle_reference"})
COPY_CLASSES = ("primary_storage", "attachments", "backups", "replicas", "logs", "exports", "recovery_bundles")
INELIGIBLE = frozenset({"applicable_active_hold", "relevant_unresolved_obligation", "policy_scope_excludes_subject", "rule_condition_not_satisfied"})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _required(value: Any, code: str, maximum: int = 8000) -> str:
    value = str(value or "").strip()
    if not value or len(value) > maximum:
        raise ValueError(code)
    return value


def _actor(token: Any) -> str:
    try:
        session = verify_signed_admin_session(token)
    except AdminSessionVerificationError as exc:
        raise ValueError("retention_register_authenticated_actor_required") from exc
    return _required(session.get("username"), "retention_register_authenticated_actor_required", 256)


def _version(value: Any) -> int:
    try: result = int(value)
    except (TypeError, ValueError) as exc: raise ValueError("retention_register_expected_version_invalid") from exc
    if result < 0: raise ValueError("retention_register_expected_version_invalid")
    return result


def ensure_tables(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("""CREATE TABLE IF NOT EXISTS governed_retention_subjects (
      id INTEGER PRIMARY KEY, identifier TEXT UNIQUE NOT NULL, subject_type TEXT NOT NULL,
      subject_identity TEXT NOT NULL, subject_version TEXT NOT NULL, subject_revision INTEGER NOT NULL,
      subject_binding_json TEXT NOT NULL DEFAULT '{}',
      retention_review TEXT NOT NULL, inventory_state TEXT NOT NULL, eligibility_state TEXT NOT NULL,
      decision_state TEXT NOT NULL, approval_state TEXT NOT NULL, applicability_state TEXT NOT NULL,
      procedure_state TEXT NOT NULL, policy_id TEXT NOT NULL, policy_revision INTEGER NOT NULL,
      version INTEGER NOT NULL, created_at TEXT NOT NULL, created_by TEXT NOT NULL,
      updated_at TEXT NOT NULL, updated_by TEXT NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS governed_retention_policies (
      id INTEGER PRIMARY KEY, policy_id TEXT NOT NULL, revision INTEGER NOT NULL, policy_json TEXT NOT NULL,
      available INTEGER NOT NULL DEFAULT 1, UNIQUE(policy_id,revision))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS governed_retention_authorities (
      id INTEGER PRIMARY KEY, authority_id TEXT NOT NULL, revision INTEGER NOT NULL, username TEXT NOT NULL,
      role TEXT NOT NULL, available INTEGER NOT NULL DEFAULT 1, UNIQUE(authority_id,revision,role))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS governed_retention_history (
      id INTEGER PRIMARY KEY, subject_id INTEGER NOT NULL, operation_id TEXT NOT NULL, actor TEXT NOT NULL,
      reason TEXT NOT NULL, details_json TEXT NOT NULL, occurred_at TEXT NOT NULL,
      FOREIGN KEY(subject_id) REFERENCES governed_retention_subjects(id))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS governed_retention_receipts (
      id INTEGER PRIMARY KEY, subject_id INTEGER NOT NULL, idempotency_key TEXT UNIQUE NOT NULL,
      canonical_json TEXT NOT NULL, receipt_json TEXT NOT NULL, created_at TEXT NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS governed_retention_inventory_assessments (
      id INTEGER PRIMARY KEY, subject_id INTEGER NOT NULL, subject_revision INTEGER NOT NULL,
      subject_binding_json TEXT NOT NULL DEFAULT '{}',
      policy_id TEXT NOT NULL, policy_revision INTEGER NOT NULL, outcome TEXT NOT NULL,
      copies_json TEXT NOT NULL, evidence_json TEXT NOT NULL, limitations TEXT NOT NULL,
      actor TEXT NOT NULL, occurred_at TEXT NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS governed_retention_holds (
      id INTEGER PRIMARY KEY, subject_id INTEGER NOT NULL, hold_identifier TEXT NOT NULL,
      revision INTEGER NOT NULL, state TEXT NOT NULL, basis TEXT NOT NULL, evidence_json TEXT NOT NULL,
      scope TEXT NOT NULL, limitations TEXT NOT NULL, owner_fixture_id TEXT NOT NULL,
      owner_fixture_revision INTEGER NOT NULL, actor TEXT NOT NULL, occurred_at TEXT NOT NULL,
      UNIQUE(subject_id,hold_identifier,revision))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS governed_retention_assessments (
      id INTEGER PRIMARY KEY, subject_id INTEGER NOT NULL, subject_revision INTEGER NOT NULL,
      subject_binding_json TEXT NOT NULL DEFAULT '{}',
      policy_id TEXT NOT NULL, policy_revision INTEGER NOT NULL, outcome TEXT NOT NULL,
      blocker TEXT, evidence_json TEXT NOT NULL, limitations TEXT NOT NULL, next_review_json TEXT,
      actor TEXT NOT NULL, occurred_at TEXT NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS governed_retention_decisions (
      id INTEGER PRIMARY KEY, subject_id INTEGER NOT NULL, assessment_id INTEGER NOT NULL,
      revision INTEGER NOT NULL, outcome TEXT NOT NULL, bindings_json TEXT NOT NULL,
      actor TEXT NOT NULL, occurred_at TEXT NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS governed_retention_reviews (
      id INTEGER PRIMARY KEY, subject_id INTEGER NOT NULL, decision_id INTEGER, action TEXT NOT NULL,
      revision INTEGER NOT NULL, reviewer_fixture_id TEXT NOT NULL, reviewer_fixture_revision INTEGER NOT NULL,
      reviewer TEXT NOT NULL, result TEXT NOT NULL, evidence_json TEXT NOT NULL, occurred_at TEXT NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS governed_retention_approvals (
      id INTEGER PRIMARY KEY, subject_id INTEGER NOT NULL, decision_id INTEGER NOT NULL,
      revision INTEGER NOT NULL, owner_fixture_id TEXT NOT NULL, owner_fixture_revision INTEGER NOT NULL,
      actor TEXT NOT NULL, occurred_at TEXT NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS governed_retention_hold_actions (
      id INTEGER PRIMARY KEY, subject_id INTEGER NOT NULL, hold_id INTEGER NOT NULL,
      revision INTEGER NOT NULL, action TEXT NOT NULL, basis TEXT NOT NULL,
      evidence_json TEXT NOT NULL, subject_revision INTEGER NOT NULL DEFAULT 0,
      subject_binding_json TEXT NOT NULL DEFAULT '{}', policy_id TEXT NOT NULL DEFAULT '',
      policy_revision INTEGER NOT NULL DEFAULT 0, actor TEXT NOT NULL, occurred_at TEXT NOT NULL,
      UNIQUE(subject_id,hold_id,revision,action))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS governed_retention_recurring_reviews (
      id INTEGER PRIMARY KEY, subject_id INTEGER NOT NULL, outcome TEXT NOT NULL,
      procedure_state TEXT NOT NULL, state TEXT NOT NULL, policy_id TEXT NOT NULL,
      policy_revision INTEGER NOT NULL, details_json TEXT NOT NULL, actor TEXT NOT NULL,
      occurred_at TEXT NOT NULL)""")
    for table in ("governed_retention_history", "governed_retention_inventory_assessments", "governed_retention_holds", "governed_retention_assessments", "governed_retention_decisions", "governed_retention_reviews", "governed_retention_approvals", "governed_retention_hold_actions", "governed_retention_recurring_reviews"):
        conn.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_immutable_update BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT,'retention_history_immutable'); END")
        conn.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_immutable_delete BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT,'retention_history_immutable'); END")


def create_subject(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
    raise ValueError("retention_register_admission_disabled")


def _validate_subject_binding(subject: Mapping[str, Any]) -> None:
    """Validate an exact synthetic subject binding without any remote lookup."""
    if subject["subject_type"] not in SUBJECT_TYPES:
        raise ValueError("retention_subject_type_invalid")
    if not str(subject["subject_identity"]).strip() or not str(subject["subject_version"]).strip() or not isinstance(subject["subject_revision"], int) or subject["subject_revision"] < 1:
        raise ValueError("retention_subject_binding_invalid")
    try:
        binding = json.loads(subject["subject_binding_json"])
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("retention_subject_binding_invalid") from exc
    if subject["subject_type"] == "repository_commit":
        if (not isinstance(binding, Mapping)
                or set(binding) != {"repository_identity", "commit_sha"}
                or _required(binding.get("repository_identity"), "retention_subject_binding_invalid", 512) != subject["subject_identity"]
                or _required(binding.get("commit_sha"), "retention_subject_binding_invalid", 256) != subject["subject_version"]):
            raise ValueError("retention_subject_binding_invalid")
    elif subject["subject_type"] == "pull_request":
        if not isinstance(binding, Mapping) or set(binding) != {"repository_identity", "pull_request_number", "observed_head", "observed_base"}:
            raise ValueError("retention_subject_binding_invalid")
        number = binding.get("pull_request_number")
        if (not isinstance(number, int) or number < 1
                or _required(binding.get("repository_identity"), "retention_subject_binding_invalid", 512) != subject["subject_identity"]
                or str(number) != subject["subject_version"]):
            raise ValueError("retention_subject_binding_invalid")
        for key in ("observed_head", "observed_base"):
            ref = binding.get(key)
            if (not isinstance(ref, Mapping) or set(ref) != {"repository_identity", "commit_sha"}
                    or _required(ref.get("repository_identity"), "retention_subject_binding_invalid", 512) != subject["subject_identity"]
                    or not _required(ref.get("commit_sha"), "retention_subject_binding_invalid", 256)):
                raise ValueError("retention_subject_binding_invalid")


def _subject(conn: sqlite3.Connection, identifier: Any) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM governed_retention_subjects WHERE identifier=?", (_required(identifier, "retention_subject_identifier_invalid", 256),)).fetchone()
    if not row: raise ValueError("retention_subject_not_found")
    subject = dict(row)
    _validate_subject_binding(subject)
    return subject


def _validate_policy_schema(subject: Mapping[str, Any], policy: Mapping[str, Any]) -> None:
    if not isinstance(policy, Mapping):
        raise ValueError("retention_policy_schema_invalid")
    if type(policy.get("review_due_invalidates_current_reliance")) is not bool: raise ValueError("retention_policy_review_due_invalid")
    required = {"permitted_subject_types", "retention_purpose_basis", "trigger_kind", "trigger_evidence_identity", "trigger_evidence_revision", "review_points", "eligibility_conditions", "ineligibility_conditions", "owner_authority_id", "owner_authority_revision", "reviewer_authority_id", "reviewer_authority_revision", "action_review_map"}
    if not required.issubset(policy):
        raise ValueError("retention_policy_schema_invalid")
    if (not isinstance(policy["permitted_subject_types"], list)
            or subject["subject_type"] not in policy["permitted_subject_types"]
            or not _required(policy["retention_purpose_basis"], "retention_policy_schema_invalid")
            or policy["trigger_kind"] not in {"subject_created", "subject_closed", "recorded_event", "policy_review"}
            or not _required(policy["trigger_evidence_identity"], "retention_policy_schema_invalid")
            or not isinstance(policy["trigger_evidence_revision"], int)
            or policy["trigger_evidence_revision"] < 1
            or not isinstance(policy["review_points"], list) or not policy["review_points"]
            or not isinstance(policy["eligibility_conditions"], list)
            or not isinstance(policy["ineligibility_conditions"], list)
            or not _required(policy["owner_authority_id"], "retention_policy_schema_invalid")
            or not isinstance(policy["owner_authority_revision"], int)
            or not _required(policy["reviewer_authority_id"], "retention_policy_schema_invalid")
            or not isinstance(policy["reviewer_authority_revision"], int)
            or not isinstance(policy["action_review_map"], Mapping)):
        raise ValueError("retention_policy_schema_invalid")
    # These are the complete, policy-controlled action requirements approved
    # for the synthetic foundation.  A missing or alternate entry is not a
    # permissive fallback: it makes this immutable policy unusable.
    required_action_map = {
        "hold_placement": "owner_only",
        "hold_amendment": "owner_only",
        "hold_release": "owner_plus_independent_synthetic_review",
        "eligible_decision_approval": "owner_plus_independent_synthetic_review",
        "ineligible_decision_approval": "owner_plus_independent_synthetic_review",
    }
    if any(policy["action_review_map"].get(action) != requirement
           for action, requirement in required_action_map.items()):
        raise ValueError("retention_policy_schema_invalid")


def _policy(conn: sqlite3.Connection, subject: Mapping[str, Any]) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM governed_retention_policies WHERE policy_id=? AND revision=? AND available=1", (subject["policy_id"], subject["policy_revision"])).fetchone()
    if not row: raise ValueError("retention_policy_unavailable")
    try: policy = json.loads(row["policy_json"])
    except json.JSONDecodeError as exc: raise ValueError("retention_policy_invalid") from exc
    _validate_policy_schema(subject, policy)
    return policy


def _review_point_binding(subject: Mapping[str, Any], policy: Mapping[str, Any]) -> dict[str, Any]:
    """Return the only policy-bound review point that can affect currentness.

    This is deliberately independent of a caller's requested point.  It is
    used both by private retrieval and by consequential mutations, so an
    unrecorded reached point cannot leave a current approval appearing usable.
    """
    rule = policy.get("review_point_rule")
    trigger = policy.get("trigger_evidence")
    if not isinstance(rule, Mapping) or not isinstance(trigger, Mapping):
        raise ValueError("retention_policy_review_point_invalid")
    identity = _required(rule.get("identity"), "retention_policy_review_point_invalid", 256)
    revision = rule.get("revision")
    due_at = rule.get("due_at")
    if not isinstance(revision, int) or revision < 1 or not isinstance(due_at, str):
        raise ValueError("retention_policy_review_point_invalid")
    try:
        due = datetime.fromisoformat(due_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("retention_policy_review_point_invalid") from exc
    if due.tzinfo is None:
        raise ValueError("retention_policy_review_point_invalid")
    if trigger.get("subject_identity") != subject["subject_identity"] or trigger.get("subject_revision") != subject["subject_revision"]:
        raise ValueError("retention_policy_trigger_evidence_mismatch")
    return {"identity": identity, "revision": revision, "due_at": due_at, "due": due.astimezone(timezone.utc), "subject_revision": subject["subject_revision"]}


def _derived_review_point(subject: Mapping[str, Any], policy: Mapping[str, Any]) -> tuple[dict[str, Any], bool]:
    """Derive reach from the immutable fixture, never from request input."""
    binding = _review_point_binding(subject, policy)
    return binding, binding["due"] <= datetime.now(timezone.utc)


def _derive_reached_review_point(subject: Mapping[str, Any], policy: Mapping[str, Any], reached_point: Any) -> dict[str, Any]:
    """Validate immutable policy evidence before a due observation can be written."""
    binding, reached = _derived_review_point(subject, policy)
    if binding["identity"] != _required(reached_point, "retention_review_point_required", 256):
        raise ValueError("retention_policy_review_point_invalid")
    if not reached:
        raise ValueError("retention_review_point_not_reached")
    return {key: binding[key] for key in ("identity", "revision", "due_at", "subject_revision")}


def _require_not_true_due(subject: Mapping[str, Any], policy: Mapping[str, Any]) -> None:
    """Reject consequential reliance if a true point has already been reached.

    No due-observation event is required: currentness is derived from the
    immutable fixture at use time.  This helper makes no writes.
    """
    _binding, reached = _derived_review_point(subject, policy)
    if reached and policy["review_due_invalidates_current_reliance"] is True:
        raise ValueError("retention_review_due_currentness_required")


def _derived_projection(conn: sqlite3.Connection, subject: Mapping[str, Any], policy: Mapping[str, Any]) -> dict[str, Any]:
    """Private read projection with no persistence side effect."""
    result = dict(subject)
    binding, reached = _derived_review_point(subject, policy)
    result["derived_review_point"] = {key: binding[key] for key in ("identity", "revision", "due_at", "subject_revision")}
    result["derived_review_due"] = reached
    if not reached:
        return result
    # A false-policy observational completion may establish a successor
    # review basis.  It is trusted only when the immutable completion record
    # binds this exact subject, policy, and completed policy point; caller
    # supplied tuple values or a bare `next_point` cannot suppress due state.
    if policy["review_due_invalidates_current_reliance"] is False:
        completed = conn.execute(
            "SELECT * FROM governed_retention_recurring_reviews WHERE subject_id=? "
            "AND state='completed' ORDER BY id DESC LIMIT 1", (subject["id"],)
        ).fetchone()
        if completed and completed["policy_id"] == subject["policy_id"] and completed["policy_revision"] == subject["policy_revision"]:
            try:
                details = json.loads(completed["details_json"])
            except (TypeError, json.JSONDecodeError):
                details = {}
            if (details.get("subject_revision") == subject["subject_revision"]
                    and details.get("subject_binding_json") == subject["subject_binding_json"]
                    and details.get("policy_id") == subject["policy_id"]
                    and details.get("policy_revision") == subject["policy_revision"]
                    and details.get("completed_point_identity") == binding["identity"]
                    and details.get("completed_point_revision") == binding["revision"]
                    and details.get("next_point") and details.get("responsible")):
                return result
    result["retention_review"] = "due"
    if policy["review_due_invalidates_current_reliance"] is True:
        if result["eligibility_state"] in {"eligible_current", "ineligible_current"}:
            result["eligibility_state"] = "stale"
        if result["approval_state"] == "approved_current":
            result["approval_state"] = "stale"
        if result["applicability_state"] == "current":
            result["applicability_state"] = "reassessment_required"
    return result


def _unavailable_policy_projection(subject: Mapping[str, Any], error: ValueError) -> dict[str, Any]:
    """RD-12 private read: invalid/unavailable policy never looks current.

    The stored decision and procedure are historical facts; only the derived
    E/A/C values are unavailable.  This does not repair the fixture or write a
    currentness event.
    """
    result = dict(subject)
    result["eligibility_state"] = "unavailable"
    result["approval_state"] = "unavailable"
    result["applicability_state"] = "unavailable"
    result["derived_policy_unavailable"] = str(error)
    return result


def _authority(conn: sqlite3.Connection, authority_id: Any, revision: Any, actor: str, role: str) -> None:
    identity = _required(authority_id, "retention_authority_invalid", 256)
    requested = int(revision)
    latest = conn.execute("SELECT max(revision) AS revision FROM governed_retention_authorities WHERE authority_id=? AND role=?", (identity, role)).fetchone()
    row = conn.execute("SELECT username FROM governed_retention_authorities WHERE authority_id=? AND revision=? AND role=? AND available=1", (identity, requested, role)).fetchone()
    # Historical rows remain queryable and bind earlier actions, but cannot be
    # reused as current action authority after a successor fixture exists.
    if not latest or latest["revision"] != requested or not row or row["username"] != actor:
        raise ValueError("retention_authority_unavailable")


def _policy_authority(policy: Mapping[str, Any], authority_id: Any, revision: Any, role: str) -> None:
    """Bind a current action to the exact authority fixture named by policy."""
    prefix = "owner" if role == "owner" else "reviewer"
    if authority_id != policy.get(f"{prefix}_authority_id") or revision != policy.get(f"{prefix}_authority_revision"):
        raise ValueError("retention_policy_authority_binding_invalid")


def _policy_review_requirement(policy: Mapping[str, Any], action: str, requirement: str) -> None:
    """Reject a request when its exact fixture map does not authorize the path."""
    if policy.get("action_review_map", {}).get(action) != requirement:
        raise ValueError("retention_policy_action_review_invalid")


def _active_holds(conn: sqlite3.Connection, subject_id: int) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT h.* FROM governed_retention_holds h JOIN (SELECT hold_identifier,max(revision) revision FROM governed_retention_holds WHERE subject_id=? GROUP BY hold_identifier) x ON x.hold_identifier=h.hold_identifier AND x.revision=h.revision WHERE h.subject_id=? AND h.state='active'", (subject_id, subject_id)).fetchall()
    return [dict(row) for row in rows]


def _active_hold_constraints(conn: sqlite3.Connection, subject: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return active holds not currently established as not applicable.

    A bare active hold, an unavailable assessment, or an unresolved/applicable
    assessment all remain constraints.  Only a current H-02 record tied to the
    exact current hold, subject, and policy revision can establish
    `not_applicable` for the bounded eligible-assessment purpose.
    """
    constraints: list[dict[str, Any]] = []
    for hold in _active_holds(conn, int(subject["id"])):
        assessment = None
        rows = conn.execute(
            "SELECT details_json FROM governed_retention_history WHERE subject_id=? AND operation_id='H-02' ORDER BY id DESC",
            (subject["id"],),
        ).fetchall()
        for row in rows:
            try:
                payload = json.loads(row["details_json"]).get("payload", {})
            except (TypeError, json.JSONDecodeError):
                payload = {}
            if (payload.get("hold_identifier") == hold["hold_identifier"]
                    and payload.get("hold_revision") == hold["revision"]
                    and payload.get("subject_revision") == subject["subject_revision"]
                    and payload.get("subject_binding_json") == subject["subject_binding_json"]
                    and payload.get("policy_id") == subject["policy_id"]
                    and payload.get("policy_revision") == subject["policy_revision"]):
                assessment = payload.get("applicability")
                break
        if assessment != "not_applicable":
            constraints.append(hold)
    return constraints


def _has_current_applicable_hold_assessment(conn: sqlite3.Connection, subject: Mapping[str, Any]) -> bool:
    """An active label alone is not the D-02 applicability evidence."""
    for hold in _active_holds(conn, int(subject["id"])):
        rows = conn.execute("SELECT details_json FROM governed_retention_history WHERE subject_id=? AND operation_id='H-02' ORDER BY id DESC", (subject["id"],)).fetchall()
        for row in rows:
            try:
                payload = json.loads(row["details_json"]).get("payload", {})
            except (TypeError, json.JSONDecodeError):
                payload = {}
            if (payload.get("hold_identifier") == hold["hold_identifier"]
                    and payload.get("hold_revision") == hold["revision"]
                    and payload.get("applicability") == "applicable"
                    and payload.get("subject_revision") == subject["subject_revision"]
                    and payload.get("subject_binding_json") == subject["subject_binding_json"]
                    and payload.get("policy_id") == subject["policy_id"]
                    and payload.get("policy_revision") == subject["policy_revision"]):
                return True
    return False


def _current_approved_chain(conn: sqlite3.Connection, subject: Mapping[str, Any], *, allow_true_due_stale: bool = False) -> None:
    """Validate the immutable chain required by observational recurring review."""
    policy = _policy(conn, subject)
    decision = conn.execute("SELECT * FROM governed_retention_decisions WHERE subject_id=? ORDER BY id DESC LIMIT 1", (subject["id"],)).fetchone()
    if not decision:
        raise ValueError("retention_recurring_review_binding_invalid")
    review = conn.execute("SELECT * FROM governed_retention_reviews WHERE subject_id=? AND decision_id=? AND action='decision' ORDER BY id DESC LIMIT 1", (subject["id"], decision["id"])).fetchone()
    approval = conn.execute("SELECT * FROM governed_retention_approvals WHERE subject_id=? AND decision_id=? ORDER BY id DESC LIMIT 1", (subject["id"], decision["id"])).fetchone()
    if (not review or not approval or review["revision"] != decision["revision"]
            or approval["revision"] != decision["revision"] or review["result"] != "accepted"):
        raise ValueError("retention_recurring_review_binding_invalid")
    try:
        bindings = json.loads(decision["bindings_json"])
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("retention_recurring_review_binding_invalid") from exc
    if (bindings.get("subject_revision") != subject["subject_revision"]
            or bindings.get("subject_binding_json") != subject["subject_binding_json"]
            or bindings.get("policy_id") != subject["policy_id"]
            or bindings.get("policy_revision") != subject["policy_revision"]):
        raise ValueError("retention_recurring_review_binding_invalid")
    # RD/RR use the same approved decision as a consequential predecessor.
    # The proposal's inventory predecessor is therefore consequential here as
    # well: a caller cannot retain a tuple-shaped approval while discarding or
    # substituting the immutable inventory record on which it was proposed.
    try:
        _decision_inventory_binding(conn, subject, bindings)
    except ValueError as exc:
        raise ValueError("retention_recurring_review_binding_invalid") from exc
    assessment = conn.execute("SELECT * FROM governed_retention_assessments WHERE id=? AND subject_id=?", (decision["assessment_id"], subject["id"])).fetchone()
    expected = "eligible" if subject["decision_state"] == "proposed_eligible_for_future_scope" else "ineligible"
    expected_eligibility = "eligible_current" if expected == "eligible" else "ineligible_current"
    permitted_eligibility = {expected_eligibility}
    # TRD-01 deliberately follows RD-01/RD-07, whose whole purpose is to
    # retain the immutable approved chain while making its live conclusion
    # stale.  No other caller may use that historical exception.
    if allow_true_due_stale:
        permitted_eligibility = {"stale"}
    if (subject["eligibility_state"] not in permitted_eligibility
            or not assessment or decision["outcome"] != expected or assessment["outcome"] != expected
            or assessment["subject_revision"] != subject["subject_revision"]
            or assessment["subject_binding_json"] != subject["subject_binding_json"]
            or assessment["policy_id"] != subject["policy_id"]
            or assessment["policy_revision"] != subject["policy_revision"]):
        raise ValueError("retention_recurring_review_binding_invalid")
    if review["reviewer"] == assessment["actor"] or review["reviewer"] == approval["actor"]:
        raise ValueError("retention_recurring_review_binding_invalid")
    _authority(conn, review["reviewer_fixture_id"], review["reviewer_fixture_revision"], review["reviewer"], "reviewer")
    _authority(conn, approval["owner_fixture_id"], approval["owner_fixture_revision"], approval["actor"], "owner")
    _policy_authority(policy, review["reviewer_fixture_id"], review["reviewer_fixture_revision"], "reviewer")
    _policy_authority(policy, approval["owner_fixture_id"], approval["owner_fixture_revision"], "owner")


def _active_closure_history(conn: sqlite3.Connection, subject: Mapping[str, Any]) -> None:
    """Require an attributable closure not later superseded by reopening.

    The stored procedure dimension is a projection; it cannot itself invent an
    active closure. Later closed-record hold events remain compatible because
    they do not reopen the parent.
    """
    closure = conn.execute("SELECT id FROM governed_retention_history WHERE subject_id=? AND operation_id IN ('CL-01','CL-02') ORDER BY id DESC LIMIT 1", (subject["id"],)).fetchone()
    if not closure:
        raise ValueError("retention_active_closure_history_required")
    reopened = conn.execute("SELECT 1 FROM governed_retention_history WHERE subject_id=? AND operation_id='RE-01' AND id>? LIMIT 1", (subject["id"], closure["id"])).fetchone()
    if reopened:
        raise ValueError("retention_active_closure_history_required")


def _decision_inventory_binding(conn: sqlite3.Connection, subject: Mapping[str, Any], bindings: Mapping[str, Any]) -> None:
    """Require a proposal's immutable inventory predecessor at consequential use."""
    inventory_id = bindings.get("inventory_assessment_id")
    if not isinstance(inventory_id, int) or inventory_id < 1:
        raise ValueError("retention_inventory_binding_invalid")
    inventory = conn.execute("SELECT * FROM governed_retention_inventory_assessments WHERE id=? AND subject_id=?", (inventory_id, subject["id"])).fetchone()
    if (not inventory or inventory["subject_revision"] != subject["subject_revision"]
            or inventory["subject_binding_json"] != subject["subject_binding_json"]
            or inventory["policy_id"] != subject["policy_id"]
            or inventory["policy_revision"] != subject["policy_revision"]
            or inventory["outcome"] != subject["inventory_state"]):
        raise ValueError("retention_inventory_binding_invalid")


def _deferred_due_predecessor(conn: sqlite3.Connection, subject: Mapping[str, Any], reached_point: str) -> None:
    """Anchor RD-05--10 to the immutable deferral that named its point.

    A deferred projection by itself is not evidence that the supplied point was
    actually recorded.  Initial deferral is retained in history; observational
    decision deferral is retained in the recurring-review table.
    """
    if subject["decision_state"] == "none":
        row = conn.execute("SELECT details_json FROM governed_retention_history WHERE subject_id=? AND operation_id='DF-01' ORDER BY id DESC LIMIT 1", (subject["id"],)).fetchone()
        try:
            payload = json.loads(row["details_json"]).get("payload", {}) if row else {}
        except (TypeError, json.JSONDecodeError):
            payload = {}
        if (not row or payload.get("next_point") != reached_point
                or payload.get("subject_revision") != subject["subject_revision"]
                or payload.get("subject_binding_json") != subject["subject_binding_json"]
                or payload.get("policy_id") != subject["policy_id"]
                or payload.get("policy_revision") != subject["policy_revision"]):
            raise ValueError("retention_deferred_review_binding_invalid")
        return
    outcome = "E" if subject["decision_state"] == "proposed_eligible_for_future_scope" else "I"
    row = conn.execute("SELECT * FROM governed_retention_recurring_reviews WHERE subject_id=? AND outcome=? AND procedure_state=? ORDER BY id DESC LIMIT 1", (subject["id"], outcome, subject["procedure_state"])).fetchone()
    try:
        details = json.loads(row["details_json"]) if row else {}
    except (TypeError, json.JSONDecodeError):
        details = {}
    if (not row or row["state"] != "deferred" or row["policy_id"] != subject["policy_id"]
            or row["policy_revision"] != subject["policy_revision"]
            or details.get("next_point") != reached_point
            or details.get("subject_revision") != subject["subject_revision"]
            or details.get("subject_binding_json") != subject["subject_binding_json"]
            or details.get("policy_id") != subject["policy_id"]
            or details.get("policy_revision") != subject["policy_revision"]):
        raise ValueError("retention_deferred_review_binding_invalid")


def _tuple(row: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(str(row[x]) for x in ("retention_review", "inventory_state", "eligibility_state", "decision_state", "approval_state", "applicability_state", "procedure_state"))


def _event(conn: sqlite3.Connection, subject: Mapping[str, Any], operation: str, actor: str, reason: str, details: Mapping[str, Any]) -> None:
    conn.execute("INSERT INTO governed_retention_history(subject_id,operation_id,actor,reason,details_json,occurred_at) VALUES(?,?,?,?,?,?)", (subject["id"], operation, actor, reason, _json(dict(details)), _now()))


def _historical_retry(conn: sqlite3.Connection, *, identifier: Any, expected_version: Any, idempotency_key: Any, reason: Any, operation: str, payload: Mapping[str, Any]) -> dict[str, Any] | None:
    """Return only an exact prior receipt, labelled as a non-writing replay."""
    key = _required(idempotency_key, "retention_idempotency_key_required", 128)
    why = _required(reason, "retention_reason_required")
    canonical = _json({"operation": operation, "identifier": identifier, "expected_version": expected_version, "reason": why, "payload": dict(payload)})
    old = conn.execute("SELECT canonical_json,receipt_json FROM governed_retention_receipts WHERE idempotency_key=?", (key,)).fetchone()
    if not old:
        return None
    if old["canonical_json"] != canonical:
        raise ValueError("retention_idempotency_conflict")
    receipt = json.loads(old["receipt_json"])
    receipt["historical"] = True
    return receipt


def _mutate(conn: sqlite3.Connection, *, identifier: Any, token: Any, expected_version: Any, idempotency_key: Any, reason: Any, operation: str, payload: Mapping[str, Any], allowed: set[tuple[str, ...]], changes: Mapping[str, Any], details: Mapping[str, Any] | None = None, side_effect: Any = None) -> dict[str, Any]:
    actor = _actor(token); key = _required(idempotency_key, "retention_idempotency_key_required", 128); why = _required(reason, "retention_reason_required")
    canonical = _json({"operation": operation, "identifier": identifier, "expected_version": expected_version, "reason": why, "payload": dict(payload)})
    conn.execute("BEGIN IMMEDIATE")
    try:
        old = conn.execute("SELECT canonical_json,receipt_json FROM governed_retention_receipts WHERE idempotency_key=?", (key,)).fetchone()
        if old:
            if old["canonical_json"] != canonical: raise ValueError("retention_idempotency_conflict")
            # An exact retry is a read of immutable prior work, not a second
            # current mutation.  Keep the stored first-response receipt intact
            # and label only this returned projection as historical.
            receipt = json.loads(old["receipt_json"])
            receipt["historical"] = True
            conn.rollback(); return receipt
        subject = _subject(conn, identifier); expected = _version(expected_version)
        if int(subject["version"]) != expected: raise ValueError("retention_version_conflict")
        if _tuple(subject) not in allowed: raise ValueError("retention_operation_state_invalid")
        fields = dict(changes); fields["version"] = expected + 1; fields["updated_at"] = _now(); fields["updated_by"] = actor
        conn.execute("UPDATE governed_retention_subjects SET " + ",".join(f"{name}=?" for name in fields) + " WHERE id=?", (*fields.values(), subject["id"]))
        _event(conn, subject, operation, actor, why, {"payload": dict(payload), "before": _tuple(subject), "after": tuple(fields.get(x, subject[x]) for x in ("retention_review", "inventory_state", "eligibility_state", "decision_state", "approval_state", "applicability_state", "procedure_state")), **(details or {})})
        if side_effect:
            side_effect(subject, actor)
        receipt = {"operation": operation, "subject_identifier": subject["identifier"], "resulting_version": expected + 1, "historical": False}
        conn.execute("INSERT INTO governed_retention_receipts(subject_id,idempotency_key,canonical_json,receipt_json,created_at) VALUES(?,?,?,?,?)", (subject["id"], key, canonical, _json(receipt), _now()))
        conn.commit(); return receipt
    except Exception:
        conn.rollback(); raise


def start_initial_review(conn: sqlite3.Connection, *, subject_identifier: Any, actor: Any, expected_version: Any, idempotency_key: Any, reason: Any) -> dict[str, Any]:
    subject = _subject(conn, subject_identifier); _policy(conn, subject)
    return _mutate(conn, identifier=subject_identifier, token=actor, expected_version=expected_version, idempotency_key=idempotency_key, reason=reason, operation="SR-01", payload={}, allowed={("not_due","not_started","not_assessed","none","not_recorded","not_evaluated","recorded")}, changes={"retention_review":"under_assessment","inventory_state":"under_assessment","eligibility_state":"under_assessment","procedure_state":"under_review"})


def start_inventory_assessment(conn: sqlite3.Connection, *, subject_identifier: Any, actor: Any, expected_version: Any, idempotency_key: Any, reason: Any) -> dict[str, Any]:
    """INV-01: start/restart inventory only before a proposal or approval exists."""
    subject = _subject(conn, subject_identifier); _policy(conn, subject)
    if subject["procedure_state"] != "under_review" or subject["decision_state"] != "none" or subject["approval_state"] != "not_recorded" or subject["applicability_state"] != "not_evaluated" or subject["inventory_state"] not in {"not_started", "incomplete", "under_assessment"} or subject["eligibility_state"] not in {"under_assessment", "pending_missing_information"}:
        raise ValueError("retention_inventory_phase_invalid")
    return _mutate(conn, identifier=subject_identifier, token=actor, expected_version=expected_version, idempotency_key=idempotency_key, reason=reason, operation="INV-01", payload={}, allowed={_tuple(subject)}, changes={"inventory_state":"under_assessment", "eligibility_state":"under_assessment"})


def record_inventory(conn: sqlite3.Connection, *, subject_identifier: Any, outcome: str, copies: Mapping[str, Any], evidence: Any, limitations: Any, actor: Any, expected_version: Any, idempotency_key: Any, reason: Any) -> dict[str, Any]:
    if outcome not in {"complete_with_limits", "incomplete", "awaiting_information", "unavailable"}: raise ValueError("retention_inventory_outcome_invalid")
    subject = _subject(conn, subject_identifier); _policy(conn, subject)
    state = (subject["retention_review"], subject["inventory_state"], subject["eligibility_state"], subject["decision_state"], subject["approval_state"], subject["applicability_state"], subject["procedure_state"])
    # INV-02--05 all write the result of an already started inventory
    # assessment.  Awaiting/unavailable states have named recovery operations
    # (INV-06/07); they cannot be overwritten by another result write.
    if (state[3:] != ("none", "not_recorded", "not_evaluated", "under_review")
            or state[1] != "under_assessment"
            or state[2] != "under_assessment"):
        raise ValueError("retention_inventory_phase_invalid")
    if evidence is None or evidence == [] or evidence == {}:
        raise ValueError("retention_inventory_evidence_required")
    required = set(COPY_CLASSES)
    if outcome == "complete_with_limits" and set(copies) != required: raise ValueError("retention_inventory_copy_classes_incomplete")
    if outcome == "complete_with_limits": e,c = "under_assessment","not_evaluated"
    elif outcome in {"incomplete", "awaiting_information"}: e,c = "pending_missing_information","not_evaluated"
    else: e,c = "unavailable","unavailable"
    limits = _required(limitations,"retention_limitations_required")
    def insert_inventory(current: Mapping[str, Any], authenticated_actor: str) -> None:
        conn.execute("INSERT INTO governed_retention_inventory_assessments(subject_id,subject_revision,subject_binding_json,policy_id,policy_revision,outcome,copies_json,evidence_json,limitations,actor,occurred_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)", (current["id"],current["subject_revision"],current["subject_binding_json"],current["policy_id"],current["policy_revision"],outcome,_json(copies),_json(evidence),limits,authenticated_actor,_now()))
    return _mutate(conn, identifier=subject_identifier, token=actor, expected_version=expected_version, idempotency_key=idempotency_key, reason=reason, operation={"complete_with_limits":"INV-02","incomplete":"INV-03","awaiting_information":"INV-04","unavailable":"INV-05"}[outcome], payload={"copies": copies}, allowed={state}, changes={"inventory_state":outcome,"eligibility_state":e,"applicability_state":c}, side_effect=insert_inventory)


def resume_inventory(conn: sqlite3.Connection, *, subject_identifier: Any, recovered: bool, actor: Any, expected_version: Any, idempotency_key: Any, reason: Any) -> dict[str, Any]:
    """INV-06/07; recovery records no invented completeness."""
    subject = _subject(conn, subject_identifier); _policy(conn, subject)
    if subject["decision_state"] != "none" or subject["approval_state"] != "not_recorded" or subject["procedure_state"] != "under_review": raise ValueError("retention_inventory_phase_invalid")
    inventory = conn.execute("SELECT * FROM governed_retention_inventory_assessments WHERE subject_id=? ORDER BY id DESC LIMIT 1", (subject["id"],)).fetchone()
    if (not inventory or inventory["subject_revision"] != subject["subject_revision"]
            or inventory["subject_binding_json"] != subject["subject_binding_json"]
            or inventory["policy_id"] != subject["policy_id"]
            or inventory["policy_revision"] != subject["policy_revision"]
            or inventory["outcome"] != subject["inventory_state"]):
        raise ValueError("retention_inventory_binding_invalid")
    if subject["inventory_state"] == "awaiting_information": op="INV-06"
    elif subject["inventory_state"] == "unavailable" and recovered: op="INV-07"
    elif subject["inventory_state"] == "unavailable":
        return _mutate(conn, identifier=subject_identifier, token=actor, expected_version=expected_version, idempotency_key=idempotency_key, reason=reason, operation="INV-07", payload={"recovered":False}, allowed={_tuple(subject)}, changes={})
    else: raise ValueError("retention_inventory_resume_state_invalid")
    return _mutate(conn, identifier=subject_identifier, token=actor, expected_version=expected_version, idempotency_key=idempotency_key, reason=reason, operation=op, payload={"recovered":recovered}, allowed={_tuple(subject)}, changes={"inventory_state":"under_assessment","eligibility_state":"under_assessment","applicability_state":"not_evaluated"})


def assess_decision(conn: sqlite3.Connection, *, subject_identifier: Any, outcome: str, blocker: Any | None, evidence: Any, limitations: Any, next_review: Mapping[str, Any] | None, actor: Any, expected_version: Any, idempotency_key: Any, reason: Any) -> dict[str, Any]:
    if outcome not in {"eligible", "ineligible"}: raise ValueError("retention_assessment_outcome_invalid")
    subject = _subject(conn, subject_identifier); _policy(conn, subject)
    if subject["procedure_state"] == "closed": raise ValueError("retention_active_closure_requires_reopen")
    inventory = conn.execute("SELECT * FROM governed_retention_inventory_assessments WHERE subject_id=? ORDER BY id DESC LIMIT 1", (subject["id"],)).fetchone()
    if (not inventory or inventory["subject_revision"] != subject["subject_revision"]
            or inventory["subject_binding_json"] != subject["subject_binding_json"]
            or inventory["policy_id"] != subject["policy_id"]
            or inventory["policy_revision"] != subject["policy_revision"]
            or inventory["outcome"] != subject["inventory_state"]):
        raise ValueError("retention_inventory_binding_invalid")
    bound_next_review = None
    if outcome == "eligible":
        if evidence is None or evidence == [] or evidence == {}:
            raise ValueError("retention_eligibility_evidence_required")
        try:
            inventory_copies = json.loads(inventory["copies_json"])
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("retention_inventory_binding_invalid") from exc
        # A known out-of-control copy is a current unresolved constraint; a
        # complete inventory record cannot relabel it as removable.
        if (subject["inventory_state"] != "complete_with_limits"
                or inventory["outcome"] != "complete_with_limits"
                or not isinstance(inventory_copies, Mapping)
                or any(isinstance(copy, Mapping) and copy.get("control") == "out_of_control"
                       for copy in inventory_copies.values())
                or _active_hold_constraints(conn, subject)):
            raise ValueError("retention_eligibility_conditions_unsatisfied")
        e = "eligible_current"; op = "D-01"; changes = {"eligibility_state":e}
    else:
        if blocker not in INELIGIBLE: raise ValueError("retention_ineligible_blocker_invalid")
        if (not next_review or not next_review.get("point") or not next_review.get("responsible")
                or not next_review.get("reason") or not next_review.get("scope")):
            raise ValueError("retention_next_review_required")
        if evidence is None or evidence == [] or evidence == {}:
            raise ValueError("retention_ineligible_blocker_evidence_required")
        # This foundation permits attributable administrative judgments for
        # obligations and policy rules, but an asserted active-hold blocker
        # must at least bind to an actual current synthetic hold rather than a
        # caller-controlled label.
        if blocker == "applicable_active_hold" and not _has_current_applicable_hold_assessment(conn, subject):
            raise ValueError("retention_ineligible_active_hold_required")
        bound_next_review = {"point": _required(next_review["point"], "retention_next_review_required"), "responsible": _required(next_review["responsible"], "retention_next_review_required"), "reason": _required(next_review["reason"], "retention_next_review_required"), "scope": _required(next_review["scope"], "retention_next_review_required"), "subject_revision": subject["subject_revision"], "subject_binding_json": subject["subject_binding_json"], "policy_id": subject["policy_id"], "policy_revision": subject["policy_revision"]}
        e = "ineligible_current"; op = "D-02"; changes = {"eligibility_state":e}
    allowed = {("assessed", subject["inventory_state"], "under_assessment", "none", "not_recorded", "not_evaluated", "under_review")}
    # D-02 may record an independently supported blocker while unrelated
    # inventory information remains pending. D-01 may not turn that missing
    # information into a positive eligible conclusion.
    if outcome == "ineligible":
        allowed.add(("assessed", subject["inventory_state"], "pending_missing_information", "none", "not_recorded", "not_evaluated", "under_review"))
    limits = _required(limitations,"retention_limitations_required")
    def insert_assessment(current: Mapping[str, Any], authenticated_actor: str) -> None:
        conn.execute("INSERT INTO governed_retention_assessments(subject_id,subject_revision,subject_binding_json,policy_id,policy_revision,outcome,blocker,evidence_json,limitations,next_review_json,actor,occurred_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (current["id"],current["subject_revision"],current["subject_binding_json"],current["policy_id"],current["policy_revision"],outcome,blocker,_json(evidence),limits,_json(bound_next_review) if bound_next_review else None,authenticated_actor,_now()))
    return _mutate(conn, identifier=subject_identifier, token=actor, expected_version=expected_version, idempotency_key=idempotency_key, reason=reason, operation=op, payload={"outcome":outcome,"blocker":blocker,"next_review":bound_next_review}, allowed=allowed, changes=changes, side_effect=insert_assessment)


def propose_decision(conn: sqlite3.Connection, *, subject_identifier: Any, outcome: str, actor: Any, expected_version: Any, idempotency_key: Any, reason: Any) -> dict[str, Any]:
    subject = _subject(conn, subject_identifier); _policy(conn, subject)
    if outcome not in {"eligible", "ineligible"}: raise ValueError("retention_proposal_outcome_invalid")
    target = "proposed_eligible_for_future_scope" if outcome == "eligible" else "proposed_ineligible_for_future_scope"
    need = "eligible_current" if outcome == "eligible" else "ineligible_current"
    if subject["eligibility_state"] != need: raise ValueError("retention_proposal_assessment_mismatch")
    op = "D-03" if outcome == "eligible" else "D-04"
    def insert_decision(current: Mapping[str, Any], authenticated: str) -> None:
        assessment = conn.execute("SELECT * FROM governed_retention_assessments WHERE subject_id=? ORDER BY id DESC LIMIT 1", (current["id"],)).fetchone()
        if (not assessment or assessment["outcome"] != outcome
                or assessment["subject_revision"] != current["subject_revision"]
                or assessment["subject_binding_json"] != current["subject_binding_json"]
                or assessment["policy_id"] != current["policy_id"]
                or assessment["policy_revision"] != current["policy_revision"]):
            raise ValueError("retention_assessment_binding_invalid")
        if assessment["evidence_json"] in (None, "", "[]", "{}") or not assessment["limitations"]:
            raise ValueError("retention_assessment_binding_invalid")
        if outcome == "eligible":
            if assessment["blocker"] is not None or assessment["next_review_json"] is not None:
                raise ValueError("retention_assessment_binding_invalid")
        else:
            try:
                follow_up = json.loads(assessment["next_review_json"] or "")
            except (TypeError, json.JSONDecodeError) as exc:
                raise ValueError("retention_next_review_required") from exc
            if (assessment["blocker"] not in INELIGIBLE
                    or not all(follow_up.get(key) for key in ("point", "responsible", "reason", "scope"))
                    or follow_up.get("subject_revision") != current["subject_revision"]
                    or follow_up.get("subject_binding_json") != current["subject_binding_json"]
                    or follow_up.get("policy_id") != current["policy_id"]
                    or follow_up.get("policy_revision") != current["policy_revision"]):
                raise ValueError("retention_next_review_required")
        inventory = conn.execute("SELECT * FROM governed_retention_inventory_assessments WHERE subject_id=? ORDER BY id DESC LIMIT 1", (current["id"],)).fetchone()
        if (not inventory or inventory["subject_revision"] != current["subject_revision"]
                or inventory["subject_binding_json"] != current["subject_binding_json"]
                or inventory["policy_id"] != current["policy_id"]
                or inventory["policy_revision"] != current["policy_revision"]
                or inventory["outcome"] != current["inventory_state"]
                or (outcome == "eligible" and inventory["outcome"] != "complete_with_limits")):
            raise ValueError("retention_inventory_binding_invalid")
        revision = int(conn.execute("SELECT count(*) FROM governed_retention_decisions WHERE subject_id=?", (current["id"],)).fetchone()[0]) + 1
        conn.execute("INSERT INTO governed_retention_decisions(subject_id,assessment_id,revision,outcome,bindings_json,actor,occurred_at) VALUES(?,?,?,?,?,?,?)", (current["id"],assessment["id"],revision,outcome,_json({"subject_revision":current["subject_revision"],"subject_binding_json":current["subject_binding_json"],"policy_id":current["policy_id"],"policy_revision":current["policy_revision"],"inventory_assessment_id":inventory["id"]}),authenticated,_now()))
    return _mutate(conn, identifier=subject_identifier, token=actor, expected_version=expected_version, idempotency_key=idempotency_key, reason=reason, operation=op, payload={"outcome":outcome}, allowed={("assessed",subject["inventory_state"],need,"none","not_recorded","not_evaluated","under_review")}, changes={"decision_state":target}, side_effect=insert_decision)


def complete_review(conn: sqlite3.Connection, *, subject_identifier: Any, evidence: Any, limitations: Any, actor: Any, expected_version: Any, idempotency_key: Any, reason: Any) -> dict[str, Any]:
    """CR-01: complete an initial review with attributable bounded evidence."""
    subject = _subject(conn, subject_identifier); _policy(conn, subject)
    # CR-01 has one permitted phase: an open, still-under-assessment initial
    # review.  A caller-shaped assessed/deferred/due tuple must use its named
    # continuation operation rather than overwrite the review projection.
    if (subject["retention_review"] != "under_assessment"
            or subject["procedure_state"] != "under_review"
            or subject["decision_state"] != "none"
            or subject["approval_state"] != "not_recorded"):
        raise ValueError("retention_review_state_invalid")
    if evidence is None or evidence == [] or evidence == {}:
        raise ValueError("retention_review_evidence_required")
    limits = _required(limitations, "retention_limitations_required")
    return _mutate(conn, identifier=subject_identifier, token=actor, expected_version=expected_version, idempotency_key=idempotency_key, reason=reason, operation="CR-01", payload={"evidence":evidence,"limitations":limits,"subject_revision":subject["subject_revision"],"subject_binding_json":subject["subject_binding_json"],"policy_id":subject["policy_id"],"policy_revision":subject["policy_revision"]}, allowed={_tuple(subject)}, changes={"retention_review":"assessed"})


def review_information(conn: sqlite3.Connection, *, subject_identifier: Any, resume: bool, missing_information: Any, actor: Any, expected_version: Any, idempotency_key: Any, reason: Any) -> dict[str, Any]:
    """RI-01/02 with immutable reason and no decision-side effect."""
    subject = _subject(conn, subject_identifier); _policy(conn, subject)
    if resume:
        if subject["retention_review"] != "awaiting_information": raise ValueError("retention_review_resume_state_invalid")
        _required(missing_information, "retention_review_resume_evidence_required")
        prior = conn.execute("SELECT details_json FROM governed_retention_history WHERE subject_id=? AND operation_id='RI-01' ORDER BY id DESC LIMIT 1", (subject["id"],)).fetchone()
        try:
            prior_payload = json.loads(prior["details_json"]).get("payload", {}) if prior else {}
        except (TypeError, json.JSONDecodeError):
            prior_payload = {}
        if (not prior or prior_payload.get("subject_revision") != subject["subject_revision"]
                or prior_payload.get("subject_binding_json") != subject["subject_binding_json"]
                or prior_payload.get("policy_id") != subject["policy_id"]
                or prior_payload.get("policy_revision") != subject["policy_revision"]):
            raise ValueError("retention_review_resume_history_required")
        op, changes = "RI-02", {"retention_review":"under_assessment","eligibility_state":"under_assessment"}
    else:
        if subject["retention_review"] != "under_assessment": raise ValueError("retention_review_information_state_invalid")
        _required(missing_information,"retention_missing_information_required")
        op, changes = "RI-01", {"retention_review":"awaiting_information","eligibility_state":"pending_missing_information"}
    if subject["decision_state"] != "none" or subject["approval_state"] != "not_recorded" or subject["procedure_state"] != "under_review": raise ValueError("retention_review_information_phase_invalid")
    return _mutate(conn, identifier=subject_identifier, token=actor, expected_version=expected_version, idempotency_key=idempotency_key, reason=reason, operation=op, payload={"missing_information":missing_information,"resume":resume,"subject_revision":subject["subject_revision"],"subject_binding_json":subject["subject_binding_json"],"policy_id":subject["policy_id"],"policy_revision":subject["policy_revision"]}, allowed={_tuple(subject)}, changes=changes)


def defer_initial_review(conn: sqlite3.Connection, *, subject_identifier: Any, next_point: Any, responsible: Any, resume: bool, actor: Any, expected_version: Any, idempotency_key: Any, reason: Any) -> dict[str, Any]:
    subject = _subject(conn, subject_identifier); _policy(conn, subject); _required(next_point,"retention_next_review_required"); _required(responsible,"retention_next_review_responsible_required")
    if subject["decision_state"] != "none" or subject["approval_state"] != "not_recorded" or subject["procedure_state"] != "under_review": raise ValueError("retention_deferral_phase_invalid")
    if resume:
        if subject["retention_review"] not in {"deferred","due"}: raise ValueError("retention_deferral_resume_state_invalid")
        prior = conn.execute("SELECT details_json FROM governed_retention_history WHERE subject_id=? AND operation_id='DF-01' ORDER BY id DESC LIMIT 1", (subject["id"],)).fetchone()
        try:
            prior_payload = json.loads(prior["details_json"]).get("payload", {}) if prior else {}
        except (TypeError, json.JSONDecodeError):
            prior_payload = {}
        if (not prior or prior_payload.get("subject_revision") != subject["subject_revision"]
                or prior_payload.get("subject_binding_json") != subject["subject_binding_json"]
                or prior_payload.get("policy_id") != subject["policy_id"]
                or prior_payload.get("policy_revision") != subject["policy_revision"]):
            raise ValueError("retention_deferral_resume_history_required")
        op, changes="DF-02", {"retention_review":"under_assessment","eligibility_state":"under_assessment"}
    else:
        if subject["retention_review"] != "assessed": raise ValueError("retention_deferral_state_invalid")
        op, changes="DF-01", {"retention_review":"deferred"}
    return _mutate(conn, identifier=subject_identifier, token=actor, expected_version=expected_version, idempotency_key=idempotency_key, reason=reason, operation=op, payload={"next_point":next_point,"responsible":responsible,"resume":resume,"subject_revision":subject["subject_revision"],"subject_binding_json":subject["subject_binding_json"],"policy_id":subject["policy_id"],"policy_revision":subject["policy_revision"]}, allowed={_tuple(subject)}, changes=changes)


def independent_review(conn: sqlite3.Connection, *, subject_identifier: Any, reviewer_authority: Any, reviewer_revision: Any, actor: Any, expected_version: Any, idempotency_key: Any, reason: Any, evidence: Any) -> dict[str, Any]:
    """D-05-E/I: record a revision-bound reviewer decision, not approval."""
    subject = _subject(conn, subject_identifier); policy = _policy(conn, subject); reviewer = _actor(actor)
    _authority(conn, reviewer_authority, reviewer_revision, reviewer, "reviewer")
    _policy_authority(policy, reviewer_authority, reviewer_revision, "reviewer")
    if subject["decision_state"] not in {"proposed_eligible_for_future_scope", "proposed_ineligible_for_future_scope"} or subject["approval_state"] != "not_recorded" or subject["procedure_state"] != "under_review": raise ValueError("retention_review_state_invalid")
    outcome = "eligible" if subject["decision_state"].startswith("proposed_eligible") else "ineligible"
    _policy_review_requirement(policy, f"{outcome}_decision_approval", "owner_plus_independent_synthetic_review")
    decision = conn.execute("SELECT * FROM governed_retention_decisions WHERE subject_id=? ORDER BY id DESC LIMIT 1", (subject["id"],)).fetchone()
    if not decision or decision["outcome"] != outcome:
        raise ValueError("retention_proposal_missing")
    try:
        bindings = json.loads(decision["bindings_json"])
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("retention_decision_binding_invalid") from exc
    if (bindings.get("subject_revision") != subject["subject_revision"]
            or bindings.get("subject_binding_json") != subject["subject_binding_json"]
            or bindings.get("policy_id") != subject["policy_id"]
            or bindings.get("policy_revision") != subject["policy_revision"]):
        raise ValueError("retention_decision_binding_invalid")
    _decision_inventory_binding(conn, subject, bindings)
    assessment = conn.execute("SELECT * FROM governed_retention_assessments WHERE id=? AND subject_id=?", (decision["assessment_id"], subject["id"])).fetchone()
    if (not assessment or assessment["actor"] == reviewer
            or assessment["subject_revision"] != subject["subject_revision"]
            or assessment["subject_binding_json"] != subject["subject_binding_json"]
            or assessment["policy_id"] != subject["policy_id"]
            or assessment["policy_revision"] != subject["policy_revision"]
            or assessment["outcome"] != outcome):
        raise ValueError("retention_independent_review_required")
    def insert_review(current: Mapping[str, Any], authenticated: str) -> None:
        conn.execute("INSERT INTO governed_retention_reviews(subject_id,decision_id,action,revision,reviewer_fixture_id,reviewer_fixture_revision,reviewer,result,evidence_json,occurred_at) VALUES(?,?,?,?,?,?,?,?,?,?)", (current["id"], decision["id"], "decision", decision["revision"], reviewer_authority, int(reviewer_revision), authenticated, "accepted", _json(evidence), _now()))
    return _mutate(conn, identifier=subject_identifier, token=actor, expected_version=expected_version, idempotency_key=idempotency_key, reason=reason, operation="D-05-E" if outcome == "eligible" else "D-05-I", payload={"reviewer_authority":reviewer_authority,"reviewer_revision":reviewer_revision}, allowed={_tuple(subject)}, changes={}, side_effect=insert_review)


def owner_decision(conn: sqlite3.Connection, *, subject_identifier: Any, approve: bool, owner_authority: Any, owner_revision: Any, actor: Any, expected_version: Any, idempotency_key: Any, reason: Any) -> dict[str, Any]:
    """D-06/D-07: independent review is mandatory before owner action."""
    subject = _subject(conn, subject_identifier); policy = _policy(conn, subject); owner = _actor(actor)
    _authority(conn, owner_authority, owner_revision, owner, "owner")
    _policy_authority(policy, owner_authority, owner_revision, "owner")
    if subject["procedure_state"] != "under_review" or subject["approval_state"] != "not_recorded" or subject["decision_state"] not in {"proposed_eligible_for_future_scope","proposed_ineligible_for_future_scope"}: raise ValueError("retention_owner_action_state_invalid")
    decision = conn.execute("SELECT * FROM governed_retention_decisions WHERE subject_id=? ORDER BY id DESC LIMIT 1", (subject["id"],)).fetchone()
    review = conn.execute("SELECT * FROM governed_retention_reviews WHERE subject_id=? AND decision_id=? AND action='decision' ORDER BY id DESC LIMIT 1", (subject["id"], decision["id"] if decision else -1)).fetchone()
    if not decision or not review or review["reviewer"] == owner or review["revision"] != decision["revision"] or review["result"] != "accepted":
        raise ValueError("retention_independent_review_required")
    try:
        decision_bindings = json.loads(decision["bindings_json"])
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("retention_decision_binding_invalid") from exc
    if (decision_bindings.get("subject_revision") != subject["subject_revision"]
            or decision_bindings.get("subject_binding_json") != subject["subject_binding_json"]
            or decision_bindings.get("policy_id") != subject["policy_id"]
            or decision_bindings.get("policy_revision") != subject["policy_revision"]):
        raise ValueError("retention_decision_binding_invalid")
    _decision_inventory_binding(conn, subject, decision_bindings)
    assessment = conn.execute("SELECT * FROM governed_retention_assessments WHERE id=? AND subject_id=?", (decision["assessment_id"], subject["id"])).fetchone()
    if (not assessment or assessment["subject_revision"] != subject["subject_revision"]
            or assessment["subject_binding_json"] != subject["subject_binding_json"]
            or assessment["policy_id"] != subject["policy_id"]
            or assessment["policy_revision"] != subject["policy_revision"]
            or assessment["outcome"] != decision["outcome"]):
        raise ValueError("retention_assessment_binding_invalid")
    _authority(conn, review["reviewer_fixture_id"], review["reviewer_fixture_revision"], review["reviewer"], "reviewer")
    _policy_authority(policy, review["reviewer_fixture_id"], review["reviewer_fixture_revision"], "reviewer")
    _policy_review_requirement(policy, f"{decision['outcome']}_decision_approval", "owner_plus_independent_synthetic_review")
    if approve:
        # A true reached point invalidates reliance even if its observation has
        # not yet been persisted.  This check precedes _mutate, so refusal is
        # atomic and cannot add a receipt, event, version, or approval row.
        _require_not_true_due(subject, policy)
        e = subject["eligibility_state"]
        if e not in {"eligible_current","ineligible_current"}: raise ValueError("retention_decision_currentness_invalid")
        changes={"approval_state":"approved_current","applicability_state":"current"}; op="D-06-E" if e == "eligible_current" else "D-06-I"
        def side(current: Mapping[str, Any], authenticated: str) -> None:
            conn.execute("INSERT INTO governed_retention_approvals(subject_id,decision_id,revision,owner_fixture_id,owner_fixture_revision,actor,occurred_at) VALUES(?,?,?,?,?,?,?)", (current["id"],decision["id"],decision["revision"],owner_authority,int(owner_revision),authenticated,_now()))
    else:
        changes={"approval_state":"not_approved"}; op="D-07-E" if subject["decision_state"] == "proposed_eligible_for_future_scope" else "D-07-I"; side=None
    return _mutate(conn, identifier=subject_identifier, token=actor, expected_version=expected_version, idempotency_key=idempotency_key, reason=reason, operation=op, payload={"owner_authority":owner_authority,"owner_revision":owner_revision,"approve":approve,"assessment_id":assessment["id"],"decision_revision":decision["revision"],"review_revision":review["revision"],"subject_revision":subject["subject_revision"],"policy_revision":subject["policy_revision"]}, allowed={_tuple(subject)}, changes=changes, side_effect=side)


def recover_rejected_proposal(conn: sqlite3.Connection, *, subject_identifier: Any, actor: Any, expected_version: Any, idempotency_key: Any, reason: Any) -> dict[str, Any]:
    """RS-01-E/I: rejection remains history; a fresh assessment is required."""
    subject = _subject(conn, subject_identifier); policy = _policy(conn, subject)
    if subject["procedure_state"] != "under_review" or subject["approval_state"] != "not_approved": raise ValueError("retention_rejection_recovery_state_invalid")
    if subject["decision_state"] == "proposed_eligible_for_future_scope": op="RS-01-E"
    elif subject["decision_state"] == "proposed_ineligible_for_future_scope": op="RS-01-I"
    else: raise ValueError("retention_rejection_recovery_state_invalid")
    decision = conn.execute("SELECT * FROM governed_retention_decisions WHERE subject_id=? ORDER BY id DESC LIMIT 1", (subject["id"],)).fetchone()
    review = conn.execute("SELECT * FROM governed_retention_reviews WHERE subject_id=? AND decision_id=? AND action='decision' ORDER BY id DESC LIMIT 1", (subject["id"], decision["id"] if decision else -1)).fetchone()
    rejected = conn.execute("SELECT actor,details_json FROM governed_retention_history WHERE subject_id=? AND operation_id=? ORDER BY id DESC LIMIT 1", (subject["id"], "D-07-E" if op == "RS-01-E" else "D-07-I")).fetchone()
    expected_outcome = "eligible" if op == "RS-01-E" else "ineligible"
    try: rejection_payload = json.loads(rejected["details_json"]).get("payload", {}) if rejected else {}
    except (TypeError, json.JSONDecodeError): rejection_payload = {}
    if (not decision or not review or decision["outcome"] != expected_outcome
            or review["revision"] != decision["revision"] or review["result"] != "accepted"
            or rejection_payload.get("decision_revision") != decision["revision"]
            or rejection_payload.get("review_revision") != review["revision"]):
        raise ValueError("retention_rejection_recovery_binding_invalid")
    try:
        decision_bindings = json.loads(decision["bindings_json"])
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("retention_rejection_recovery_binding_invalid") from exc
    if (decision_bindings.get("subject_revision") != subject["subject_revision"]
            or decision_bindings.get("subject_binding_json") != subject["subject_binding_json"]
            or decision_bindings.get("policy_id") != subject["policy_id"]
            or decision_bindings.get("policy_revision") != subject["policy_revision"]):
        raise ValueError("retention_rejection_recovery_binding_invalid")
    _authority(conn, review["reviewer_fixture_id"], review["reviewer_fixture_revision"], review["reviewer"], "reviewer")
    _authority(conn, rejection_payload.get("owner_authority"), rejection_payload.get("owner_revision"), rejected["actor"], "owner")
    _policy_authority(policy, review["reviewer_fixture_id"], review["reviewer_fixture_revision"], "reviewer")
    _policy_authority(policy, rejection_payload.get("owner_authority"), rejection_payload.get("owner_revision"), "owner")
    return _mutate(conn, identifier=subject_identifier, token=actor, expected_version=expected_version, idempotency_key=idempotency_key, reason=reason, operation=op, payload={}, allowed={_tuple(subject)}, changes={"eligibility_state":"under_assessment","decision_state":"none","approval_state":"not_recorded","applicability_state":"not_evaluated"})


def invalidate(conn: sqlite3.Connection, *, subject_identifier: Any, unavailable: bool, basis: Any, actor: Any, expected_version: Any, idempotency_key: Any, reason: Any) -> dict[str, Any]:
    """IV-01 phase-aware invalidation; it never invents an approval or reassesses."""
    subject = _subject(conn, subject_identifier); _policy(conn, subject); _required(basis, "retention_invalidation_basis_required")
    if subject["procedure_state"] == "reopened": raise ValueError("retention_invalidation_state_invalid")
    decision, approval = subject["decision_state"], subject["approval_state"]
    repeat = subject["eligibility_state"] in {"stale", "unavailable"}
    if decision == "none": suffix="A2" if repeat else "A"; next_approval="not_recorded"
    elif approval == "not_approved": suffix="R2" if repeat else "R"; next_approval="not_approved"
    elif approval in {"approved_current", "stale", "unavailable"}: suffix="O2" if repeat else "O"; next_approval="unavailable" if unavailable else ("stale" if approval != "not_recorded" else "not_recorded")
    else: suffix="P2" if repeat else "P"; next_approval="not_recorded"
    changes={"eligibility_state":"unavailable" if unavailable else "stale", "approval_state":next_approval, "applicability_state":"unavailable" if unavailable else "reassessment_required"}
    return _mutate(conn, identifier=subject_identifier, token=actor, expected_version=expected_version, idempotency_key=idempotency_key, reason=reason, operation=f"IV-01-{suffix}", payload={"basis":basis,"unavailable":unavailable}, allowed={_tuple(subject)}, changes=changes)


def _fixture_invalidation(subject: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    """Return the phase-aware available-input invalidation result."""
    decision, approval = subject["decision_state"], subject["approval_state"]
    if decision == "none": suffix, next_approval = "A", "not_recorded"
    elif approval == "not_approved": suffix, next_approval = "R", "not_approved"
    elif approval in {"approved_current", "stale", "unavailable"}: suffix, next_approval = "O", "stale" if approval == "approved_current" else approval
    else: suffix, next_approval = "P", "not_recorded"
    if subject["eligibility_state"] == "unavailable" or subject["applicability_state"] == "unavailable":
        return f"IV-01-{suffix}", {"eligibility_state":"unavailable", "approval_state":next_approval, "applicability_state":"unavailable"}
    return f"IV-01-{suffix}", {"eligibility_state":"stale", "approval_state":next_approval, "applicability_state":"reassessment_required"}


def replace_subject_binding(conn: sqlite3.Connection, *, subject_identifier: Any, subject_identity: Any, subject_version: Any, subject_binding: Mapping[str, Any], owner_authority: Any, owner_revision: Any, actor: Any, expected_version: Any, idempotency_key: Any, reason: Any) -> dict[str, Any]:
    """Append a subject-binding successor and phase-invalidate dependent reliance.

    This is a private synthetic fixture operation.  It records both immutable
    old and new binding evidence in history; it never looks up a repository or
    rewrites an existing assessment, decision, approval, or fixture revision.
    """
    subject = _subject(conn, subject_identifier); policy = _policy(conn, subject); authenticated = _actor(actor)
    _authority(conn, owner_authority, owner_revision, authenticated, "owner")
    _policy_authority(policy, owner_authority, owner_revision, "owner")
    candidate = dict(subject)
    candidate["subject_identity"] = _required(subject_identity, "retention_subject_binding_invalid", 512)
    candidate["subject_version"] = _required(subject_version, "retention_subject_binding_invalid", 256)
    candidate["subject_revision"] = int(subject["subject_revision"]) + 1
    if not isinstance(subject_binding, Mapping):
        raise ValueError("retention_subject_binding_invalid")
    candidate["subject_binding_json"] = _json(subject_binding)
    _validate_subject_binding(candidate)
    operation, changes = _fixture_invalidation(subject)
    changes = {**changes, "subject_identity": candidate["subject_identity"], "subject_version": candidate["subject_version"], "subject_revision": candidate["subject_revision"], "subject_binding_json": candidate["subject_binding_json"]}
    payload = {"fixture":"subject_binding", "prior_subject_revision":subject["subject_revision"], "successor_subject_revision":candidate["subject_revision"], "prior_binding":subject["subject_binding_json"], "successor_binding":candidate["subject_binding_json"]}
    return _mutate(conn, identifier=subject_identifier, token=actor, expected_version=expected_version, idempotency_key=idempotency_key, reason=reason, operation=operation, payload=payload, allowed={_tuple(subject)}, changes=changes)


def replace_policy_fixture(conn: sqlite3.Connection, *, subject_identifier: Any, policy_document: Mapping[str, Any], owner_authority: Any, owner_revision: Any, actor: Any, expected_version: Any, idempotency_key: Any, reason: Any) -> dict[str, Any]:
    """Disposable-fixture successor; never rewrites its predecessor revision."""
    subject = _subject(conn, subject_identifier); policy = _policy(conn, subject); authenticated = _actor(actor)
    _authority(conn, owner_authority, owner_revision, authenticated, "owner")
    _policy_authority(policy, owner_authority, owner_revision, "owner")
    _validate_policy_schema(subject, policy_document)
    # Validate all review-point and trigger bindings against this exact subject
    # before appending an immutable successor fixture.
    _review_point_binding(subject, policy_document)
    next_revision = int(subject["policy_revision"]) + 1
    if conn.execute("SELECT 1 FROM governed_retention_policies WHERE policy_id=? AND revision=?", (subject["policy_id"], next_revision)).fetchone():
        raise ValueError("retention_policy_fixture_successor_exists")
    operation, changes = _fixture_invalidation(subject)
    changes = {**changes, "policy_revision":next_revision}
    def insert_policy(current: Mapping[str, Any], _authenticated: str) -> None:
        conn.execute("INSERT INTO governed_retention_policies(policy_id,revision,policy_json,available) VALUES(?,?,?,1)", (current["policy_id"], next_revision, _json(policy_document)))
    return _mutate(conn, identifier=subject_identifier, token=actor, expected_version=expected_version, idempotency_key=idempotency_key, reason=reason, operation=operation, payload={"fixture":"policy","policy_id":subject["policy_id"],"prior_revision":subject["policy_revision"],"successor_revision":next_revision}, allowed={_tuple(subject)}, changes=changes, side_effect=insert_policy)


def replace_authority_fixture(conn: sqlite3.Connection, *, subject_identifier: Any, authority_id: Any, role: str, successor_username: Any, owner_authority: Any, owner_revision: Any, actor: Any, expected_version: Any, idempotency_key: Any, reason: Any) -> dict[str, Any]:
    """Append a controlled synthetic authority successor and invalidate reliance."""
    if role not in {"owner", "reviewer"}: raise ValueError("retention_authority_role_invalid")
    subject = _subject(conn, subject_identifier); policy = _policy(conn, subject); authenticated = _actor(actor)
    _authority(conn, owner_authority, owner_revision, authenticated, "owner")
    _policy_authority(policy, owner_authority, owner_revision, "owner")
    target = _required(authority_id, "retention_authority_invalid", 256)
    predecessor = conn.execute("SELECT * FROM governed_retention_authorities WHERE authority_id=? AND role=? ORDER BY revision DESC LIMIT 1", (target, role)).fetchone()
    if not predecessor: raise ValueError("retention_authority_unavailable")
    next_revision = int(predecessor["revision"]) + 1
    operation, changes = _fixture_invalidation(subject)
    def insert_authority(_current: Mapping[str, Any], _authenticated: str) -> None:
        conn.execute("INSERT INTO governed_retention_authorities(authority_id,revision,username,role,available) VALUES(?,?,?,?,1)", (target, next_revision, _required(successor_username, "retention_authority_invalid", 256), role))
    return _mutate(conn, identifier=subject_identifier, token=actor, expected_version=expected_version, idempotency_key=idempotency_key, reason=reason, operation=operation, payload={"fixture":"authority","authority_id":target,"role":role,"prior_revision":predecessor["revision"],"successor_revision":next_revision}, allowed={_tuple(subject)}, changes=changes, side_effect=insert_authority)


def reassess_after_invalidation(conn: sqlite3.Connection, *, subject_identifier: Any, outcome: str, owner_authority: Any, owner_revision: Any, actor: Any, expected_version: Any, idempotency_key: Any, reason: Any) -> dict[str, Any]:
    """RS-02-E/I and RC-01: explicit open recovery only; availability never restores reliance."""
    if outcome not in {"eligible", "ineligible"}: raise ValueError("retention_reassessment_outcome_invalid")
    subject = _subject(conn, subject_identifier); policy = _policy(conn, subject); authenticated = _actor(actor)
    _authority(conn, owner_authority, owner_revision, authenticated, "owner")
    _policy_authority(policy, owner_authority, owner_revision, "owner")
    if subject["procedure_state"] != "under_review" or subject["eligibility_state"] not in {"stale", "unavailable"} or subject["applicability_state"] not in {"reassessment_required", "unavailable"}:
        raise ValueError("retention_reassessment_state_invalid")
    assessment = conn.execute("SELECT outcome FROM governed_retention_assessments WHERE subject_id=? ORDER BY id DESC LIMIT 1", (subject["id"],)).fetchone()
    if not assessment or assessment["outcome"] != outcome:
        raise ValueError("retention_reassessment_outcome_binding_invalid")
    # Recovery is only available from an actual phase-specific IV-01 event.
    # A caller cannot fabricate an invalidated tuple and use a historical
    # assessment as an implicit replacement for that immutable predecessor.
    if subject["decision_state"] == "none":
        permitted_invalidation = {"IV-01-A", "IV-01-A2"}
    elif subject["approval_state"] == "not_recorded":
        permitted_invalidation = {"IV-01-P", "IV-01-P2"}
    elif subject["approval_state"] in {"stale", "unavailable"}:
        permitted_invalidation = {"IV-01-O", "IV-01-O2"}
    else:
        raise ValueError("retention_reassessment_phase_invalid")
    invalidation = conn.execute(
        "SELECT operation_id FROM governed_retention_history WHERE subject_id=? "
        "AND operation_id LIKE 'IV-01-%' ORDER BY id DESC LIMIT 1", (subject["id"],)
    ).fetchone()
    if not invalidation or invalidation["operation_id"] not in permitted_invalidation:
        raise ValueError("retention_reassessment_invalidation_binding_invalid")
    if subject["decision_state"] != "none":
        decision = conn.execute("SELECT * FROM governed_retention_decisions WHERE subject_id=? ORDER BY id DESC LIMIT 1", (subject["id"],)).fetchone()
        if not decision or decision["assessment_id"] is None or decision["outcome"] != outcome:
            raise ValueError("retention_reassessment_decision_binding_invalid")
        if subject["approval_state"] in {"stale", "unavailable"}:
            approval = conn.execute("SELECT * FROM governed_retention_approvals WHERE subject_id=? AND decision_id=? ORDER BY id DESC LIMIT 1", (subject["id"], decision["id"])).fetchone()
            if not approval or approval["revision"] != decision["revision"]:
                raise ValueError("retention_reassessment_approval_binding_invalid")
    if subject["inventory_state"] == "unavailable":
        changes = {"decision_state":"none", "approval_state":"not_recorded", "eligibility_state":"unavailable", "applicability_state":"unavailable"}
    else:
        changes = {"decision_state":"none", "approval_state":"not_recorded", "eligibility_state":"under_assessment", "applicability_state":"not_evaluated"}
    return _mutate(conn, identifier=subject_identifier, token=actor, expected_version=expected_version, idempotency_key=idempotency_key, reason=reason, operation="RS-02-E" if outcome == "eligible" else "RS-02-I", payload={"outcome":outcome,"owner_authority":owner_authority,"owner_revision":owner_revision}, allowed={_tuple(subject)}, changes=changes)


def voluntary_reconsideration(conn: sqlite3.Connection, *, subject_identifier: Any, actor: Any, expected_version: Any, idempotency_key: Any, reason: Any) -> dict[str, Any]:
    """RC-01: a current open approval can be voluntarily reconsidered without fictional invalidation."""
    subject = _subject(conn, subject_identifier); _policy(conn, subject)
    if subject["procedure_state"] != "under_review" or subject["approval_state"] != "approved_current" or subject["applicability_state"] != "current" or subject["eligibility_state"] not in {"eligible_current", "ineligible_current"}:
        raise ValueError("retention_reconsideration_state_invalid")
    _current_approved_chain(conn, subject)
    return _mutate(conn, identifier=subject_identifier, token=actor, expected_version=expected_version, idempotency_key=idempotency_key, reason=reason, operation="RC-01", payload={}, allowed={_tuple(subject)}, changes={"eligibility_state":"under_assessment", "decision_state":"none", "approval_state":"not_recorded", "applicability_state":"not_evaluated"})


def reopen(conn: sqlite3.Connection, *, subject_identifier: Any, scope: Any, actor: Any, expected_version: Any, idempotency_key: Any, reason: Any) -> dict[str, Any]:
    """RE-01: the only ordinary way to resume a non-current active closure."""
    subject = _subject(conn, subject_identifier); _policy(conn, subject)
    if subject["procedure_state"] != "closed": raise ValueError("retention_reopen_requires_active_closure")
    _active_closure_history(conn, subject)
    named_scope = _required(scope, "retention_reopen_scope_required")
    return _mutate(conn, identifier=subject_identifier, token=actor, expected_version=expected_version, idempotency_key=idempotency_key, reason=reason, operation="RE-01", payload={"scope":named_scope}, allowed={_tuple(subject)}, changes={"eligibility_state":"under_assessment","decision_state":"none","approval_state":"not_recorded","applicability_state":"not_evaluated","procedure_state":"reopened"})


def resume_after_reopen(conn: sqlite3.Connection, *, subject_identifier: Any, actor: Any, expected_version: Any, idempotency_key: Any, reason: Any) -> dict[str, Any]:
    """RM-01: preserve only an exact immutable inventory snapshot on resume."""
    subject = _subject(conn, subject_identifier); _policy(conn, subject)
    if subject["procedure_state"] != "reopened": raise ValueError("retention_resume_requires_reopening")
    inventory = subject["inventory_state"]
    row = conn.execute("SELECT * FROM governed_retention_inventory_assessments WHERE subject_id=? ORDER BY id DESC LIMIT 1", (subject["id"],)).fetchone()
    exact = bool(row and row["subject_revision"] == subject["subject_revision"]
                 and row["subject_binding_json"] == subject["subject_binding_json"]
                 and row["policy_id"] == subject["policy_id"]
                 and row["policy_revision"] == subject["policy_revision"]
                 and row["outcome"] == inventory)
    binding_states = {"complete_with_limits", "incomplete", "awaiting_information", "unavailable"}
    if inventory in binding_states and not row:
        raise ValueError("retention_inventory_binding_missing")
    if inventory == "unavailable":
        if not exact:
            raise ValueError("retention_inventory_binding_invalid")
        changes={"procedure_state":"under_review","eligibility_state":"unavailable","applicability_state":"unavailable"}
        status="unavailable_current"
    elif inventory in binding_states and not exact:
        # A superseded snapshot is not silently preserved.  It is converted
        # to an explicit fresh inventory assessment phase; no completeness or
        # availability conclusion is inherited.
        changes={"procedure_state":"under_review","inventory_state":"under_assessment","eligibility_state":"under_assessment","applicability_state":"not_evaluated"}
        status="binding_changed"
    else:
        changes={"procedure_state":"under_review","eligibility_state":"under_assessment","applicability_state":"not_evaluated"}
        status="current" if exact else "no_inventory_snapshot_required"
    payload={"inventory_state":inventory,"inventory_assessment_id":row["id"] if row else None,"inventory_binding_status":status,"subject_revision":subject["subject_revision"],"subject_binding_json":subject["subject_binding_json"],"policy_id":subject["policy_id"],"policy_revision":subject["policy_revision"]}
    return _mutate(conn, identifier=subject_identifier, token=actor, expected_version=expected_version, idempotency_key=idempotency_key, reason=reason, operation="RM-01", payload=payload, allowed={_tuple(subject)}, changes=changes)


def close(conn: sqlite3.Connection, *, subject_identifier: Any, actor: Any, expected_version: Any, idempotency_key: Any, reason: Any) -> dict[str, Any]:
    subject = _subject(conn, subject_identifier); policy = _policy(conn, subject)
    _require_not_true_due(subject, policy)
    if subject["approval_state"] != "approved_current" or subject["applicability_state"] != "current" or subject["procedure_state"] != "under_review": raise ValueError("retention_closure_current_approval_required")
    decision = conn.execute("SELECT * FROM governed_retention_decisions WHERE subject_id=? ORDER BY id DESC LIMIT 1", (subject["id"],)).fetchone()
    if not decision: raise ValueError("retention_closure_decision_missing")
    review = conn.execute("SELECT * FROM governed_retention_reviews WHERE subject_id=? AND decision_id=? AND action='decision' ORDER BY id DESC LIMIT 1", (subject["id"], decision["id"])).fetchone()
    approval = conn.execute("SELECT * FROM governed_retention_approvals WHERE subject_id=? AND decision_id=? ORDER BY id DESC LIMIT 1", (subject["id"], decision["id"])).fetchone()
    if (not review or not approval or review["revision"] != decision["revision"]
            or approval["revision"] != decision["revision"]
            or review["result"] != "accepted" or review["reviewer"] == approval["actor"]):
        raise ValueError("retention_closure_review_approval_binding_invalid")
    try:
        bindings = json.loads(decision["bindings_json"])
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("retention_closure_decision_binding_invalid") from exc
    if (bindings.get("subject_revision") != subject["subject_revision"]
            or bindings.get("subject_binding_json") != subject["subject_binding_json"]
            or bindings.get("policy_id") != subject["policy_id"]
            or bindings.get("policy_revision") != subject["policy_revision"]):
        raise ValueError("retention_closure_decision_binding_invalid")
    _decision_inventory_binding(conn, subject, bindings)
    assessment = conn.execute("SELECT * FROM governed_retention_assessments WHERE id=? AND subject_id=?", (decision["assessment_id"], subject["id"])).fetchone()
    if (not assessment or assessment["subject_revision"] != subject["subject_revision"]
            or assessment["subject_binding_json"] != subject["subject_binding_json"]
            or assessment["policy_id"] != subject["policy_id"]
            or assessment["policy_revision"] != subject["policy_revision"]
            or assessment["outcome"] != decision["outcome"]):
        raise ValueError("retention_closure_assessment_binding_invalid")
    _authority(conn, review["reviewer_fixture_id"], review["reviewer_fixture_revision"], review["reviewer"], "reviewer")
    _authority(conn, approval["owner_fixture_id"], approval["owner_fixture_revision"], approval["actor"], "owner")
    _policy_authority(policy, review["reviewer_fixture_id"], review["reviewer_fixture_revision"], "reviewer")
    _policy_authority(policy, approval["owner_fixture_id"], approval["owner_fixture_revision"], "owner")
    expected_outcome = "eligible" if subject["eligibility_state"] == "eligible_current" else "ineligible"
    if decision["outcome"] != expected_outcome:
        raise ValueError("retention_closure_outcome_binding_invalid")
    if subject["eligibility_state"] == "eligible_current" and (subject["inventory_state"] != "complete_with_limits" or _active_holds(conn, int(subject["id"]))): raise ValueError("retention_eligible_closure_conditions_unsatisfied")
    if subject["eligibility_state"] == "eligible_current":
        searches = conn.execute("SELECT details_json FROM governed_retention_history WHERE subject_id=? AND operation_id='H-01' ORDER BY id DESC", (subject["id"],)).fetchall()
        search_current = False
        for row in searches:
            try: payload = json.loads(row["details_json"]).get("payload", {})
            except (TypeError, json.JSONDecodeError): payload = {}
            if (payload.get("subject_revision") == subject["subject_revision"]
                    and payload.get("subject_binding_json") == subject["subject_binding_json"]
                    and payload.get("policy_id") == subject["policy_id"]
                    and payload.get("policy_revision") == subject["policy_revision"]):
                search_current = True; break
        if not search_current: raise ValueError("retention_closure_hold_search_required")
    if subject["eligibility_state"] == "ineligible_current":
        if not assessment["next_review_json"]: raise ValueError("retention_next_review_required")
        try: next_review = json.loads(assessment["next_review_json"])
        except json.JSONDecodeError: next_review = {}
        if (not next_review.get("point") or not next_review.get("responsible")
                or not next_review.get("reason") or not next_review.get("scope")
                or next_review.get("subject_revision") != subject["subject_revision"]
                or next_review.get("subject_binding_json") != subject["subject_binding_json"]
                or next_review.get("policy_id") != subject["policy_id"]
                or next_review.get("policy_revision") != subject["policy_revision"]):
            raise ValueError("retention_next_review_required")
    op="CL-01" if subject["eligibility_state"] == "eligible_current" else "CL-02"
    return _mutate(conn, identifier=subject_identifier, token=actor, expected_version=expected_version, idempotency_key=idempotency_key, reason=reason, operation=op, payload={}, allowed={_tuple(subject)}, changes={"procedure_state":"closed"})


def record_hold(conn: sqlite3.Connection, *, subject_identifier: Any, operation: str, hold_identifier: Any, owner_authority: Any, owner_revision: Any, evidence: Any, scope: Any, limitations: Any, actor: Any, expected_version: Any, idempotency_key: Any, reason: Any) -> dict[str, Any]:
    """H-03/H-04/H-09/H-10 synthetic hold mutation; never touches Stage 81."""
    if operation not in {"place", "amend"}: raise ValueError("retention_hold_operation_invalid")
    subject = _subject(conn, subject_identifier); policy = _policy(conn, subject); authenticated = _actor(actor)
    if subject["procedure_state"] not in {"under_review", "closed"}: raise ValueError("retention_hold_operation_state_invalid")
    if subject["procedure_state"] == "closed":
        _active_closure_history(conn, subject)
    _authority(conn, owner_authority, owner_revision, authenticated, "owner")
    _policy_authority(policy, owner_authority, owner_revision, "owner")
    _policy_review_requirement(policy, "hold_placement" if operation == "place" else "hold_amendment", "owner_only")
    if evidence is None: raise ValueError("retention_hold_action_evidence_required")
    hid = _required(hold_identifier, "retention_hold_identifier_required", 256); limits = _required(limitations,"retention_limitations_required"); hold_scope=_required(scope,"retention_hold_scope_required")
    op = "H-03" if operation == "place" and subject["procedure_state"] != "closed" else "H-11" if operation == "place" else "H-04" if subject["procedure_state"] != "closed" else "H-09"
    payload = {"hold":hid, "operation":operation,
               "owner_authority":owner_authority, "owner_revision":owner_revision,
               "evidence":evidence, "scope":hold_scope, "limitations":limits}
    if op == "H-11":
        payload["reopen_scope"] = hold_scope
    # Placement may have made the current hold shape ineligible for a second
    # placement check.  After preserving all current authority/policy/evidence
    # gates above, still recognise an exact prior H-03/H-11 request as the
    # contract-required historical receipt rather than a duplicate mutation.
    retry = _historical_retry(conn, identifier=subject_identifier, expected_version=expected_version, idempotency_key=idempotency_key, reason=reason, operation=op, payload=payload)
    if retry:
        return retry
    latest = conn.execute("SELECT * FROM governed_retention_holds WHERE subject_id=? AND hold_identifier=? ORDER BY revision DESC LIMIT 1", (subject["id"],hid)).fetchone()
    if operation == "place" and latest: raise ValueError("retention_hold_exists")
    if operation != "place" and not latest: raise ValueError("retention_hold_not_found")
    if operation == "amend":
        review_rows = conn.execute("SELECT details_json FROM governed_retention_history WHERE subject_id=? AND operation_id='H-05' ORDER BY id DESC", (subject["id"],)).fetchall()
        reviewed = False
        for review_row in review_rows:
            try:
                payload = json.loads(review_row["details_json"]).get("payload", {})
            except (TypeError, json.JSONDecodeError):
                payload = {}
            if (payload.get("hold") == hid and payload.get("hold_revision") == latest["revision"]
                    and payload.get("subject_revision") == subject["subject_revision"]
                    and payload.get("subject_binding_json") == subject["subject_binding_json"]
                    and payload.get("policy_id") == subject["policy_id"]
                    and payload.get("policy_revision") == subject["policy_revision"]):
                reviewed = True
                break
        if not reviewed: raise ValueError("retention_hold_amendment_review_required")
    state="active"
    revision = (int(latest["revision"]) + 1) if latest else 1
    if subject["procedure_state"] == "closed" and operation == "place":
        changes={"eligibility_state":"under_assessment","decision_state":"none","approval_state":"not_recorded","applicability_state":"not_evaluated","procedure_state":"reopened"}
    else:
        # H-03/H-04 use the same phase-selected available-input invalidation
        # projection as IV-01.  It preserves real proposal/rejection/approval
        # history and never treats a stale or unavailable chain as current.
        _phase, changes = _fixture_invalidation(subject)
    def insert_hold(current: Mapping[str, Any], actor_name: str) -> None:
        conn.execute("INSERT INTO governed_retention_holds(subject_id,hold_identifier,revision,state,basis,evidence_json,scope,limitations,owner_fixture_id,owner_fixture_revision,actor,occurred_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (current["id"],hid,revision,state,_required(reason,"retention_reason_required"),_json(evidence),hold_scope,limits,owner_authority,int(owner_revision),actor_name,_now()))
    return _mutate(conn, identifier=subject_identifier, token=actor, expected_version=expected_version, idempotency_key=idempotency_key, reason=reason, operation=op, payload=payload, allowed={_tuple(subject)}, changes=changes, side_effect=insert_hold)


def propose_hold_release(conn: sqlite3.Connection, *, subject_identifier: Any, hold_identifier: Any, evidence: Any, actor: Any, expected_version: Any, idempotency_key: Any, reason: Any) -> dict[str, Any]:
    """H-06: immutable release proposal; it is neither a release nor approval."""
    subject = _subject(conn, subject_identifier); policy = _policy(conn, subject)
    _policy_review_requirement(policy, "hold_release", "owner_plus_independent_synthetic_review")
    if subject["procedure_state"] != "under_review": raise ValueError("retention_hold_release_proposal_state_invalid")
    if evidence is None: raise ValueError("retention_hold_release_evidence_required")
    hid = _required(hold_identifier, "retention_hold_identifier_required", 256)
    hold = conn.execute("SELECT * FROM governed_retention_holds WHERE subject_id=? AND hold_identifier=? ORDER BY revision DESC LIMIT 1", (subject["id"], hid)).fetchone()
    if not hold or hold["state"] != "active": raise ValueError("retention_hold_release_requires_active_hold")
    if conn.execute("SELECT 1 FROM governed_retention_hold_actions WHERE subject_id=? AND hold_id=? AND revision=? AND action='release'", (subject["id"], hold["id"], hold["revision"])).fetchone(): raise ValueError("retention_hold_release_already_proposed")
    def insert_action(current: Mapping[str, Any], authenticated: str) -> None:
        conn.execute("INSERT INTO governed_retention_hold_actions(subject_id,hold_id,revision,action,basis,evidence_json,subject_revision,subject_binding_json,policy_id,policy_revision,actor,occurred_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (current["id"], hold["id"], hold["revision"], "release", _required(reason, "retention_reason_required"), _json(evidence), current["subject_revision"], current["subject_binding_json"], current["policy_id"], current["policy_revision"], authenticated, _now()))
    return _mutate(conn, identifier=subject_identifier, token=actor, expected_version=expected_version, idempotency_key=idempotency_key, reason=reason, operation="H-06", payload={"hold":hid, "hold_revision":hold["revision"]}, allowed={_tuple(subject)}, changes={}, side_effect=insert_action)


def review_hold_release(conn: sqlite3.Connection, *, subject_identifier: Any, hold_identifier: Any, reviewer_authority: Any, reviewer_revision: Any, evidence: Any, scope: Any, limitations: Any, actor: Any, expected_version: Any, idempotency_key: Any, reason: Any) -> dict[str, Any]:
    """H-07: independently review precisely the active H-06 action revision."""
    subject = _subject(conn, subject_identifier); policy = _policy(conn, subject); reviewer = _actor(actor)
    _authority(conn, reviewer_authority, reviewer_revision, reviewer, "reviewer")
    _policy_authority(policy, reviewer_authority, reviewer_revision, "reviewer")
    _policy_review_requirement(policy, "hold_release", "owner_plus_independent_synthetic_review")
    if evidence is None: raise ValueError("retention_hold_release_evidence_required")
    review_scope = _required(scope, "retention_hold_scope_required")
    review_limits = _required(limitations, "retention_limitations_required")
    if subject["procedure_state"] != "under_review": raise ValueError("retention_hold_release_review_state_invalid")
    hid = _required(hold_identifier, "retention_hold_identifier_required", 256)
    hold = conn.execute("SELECT * FROM governed_retention_holds WHERE subject_id=? AND hold_identifier=? ORDER BY revision DESC LIMIT 1", (subject["id"], hid)).fetchone()
    action = conn.execute("SELECT * FROM governed_retention_hold_actions WHERE subject_id=? AND hold_id=? AND revision=? AND action='release'", (subject["id"], hold["id"] if hold else -1, hold["revision"] if hold else -1)).fetchone()
    if not hold or hold["state"] != "active" or not action: raise ValueError("retention_hold_release_proposal_required")
    if (action["subject_revision"] != subject["subject_revision"]
            or action["subject_binding_json"] != subject["subject_binding_json"]
            or action["policy_id"] != subject["policy_id"]
            or action["policy_revision"] != subject["policy_revision"]):
        raise ValueError("retention_hold_release_binding_invalid")
    if action["actor"] == reviewer: raise ValueError("retention_independent_review_required")
    if conn.execute("SELECT 1 FROM governed_retention_reviews WHERE subject_id=? AND decision_id=? AND action='hold_release'", (subject["id"], action["id"])).fetchone(): raise ValueError("retention_hold_release_already_reviewed")
    def insert_review(current: Mapping[str, Any], authenticated: str) -> None:
        review_evidence = {"evidence": evidence, "scope": review_scope, "limitations": review_limits}
        conn.execute("INSERT INTO governed_retention_reviews(subject_id,decision_id,action,revision,reviewer_fixture_id,reviewer_fixture_revision,reviewer,result,evidence_json,occurred_at) VALUES(?,?,?,?,?,?,?,?,?,?)", (current["id"], action["id"], "hold_release", action["revision"], reviewer_authority, int(reviewer_revision), authenticated, "accepted", _json(review_evidence), _now()))
    return _mutate(conn, identifier=subject_identifier, token=actor, expected_version=expected_version, idempotency_key=idempotency_key, reason=reason, operation="H-07", payload={"hold":hid, "action_revision":action["revision"]}, allowed={_tuple(subject)}, changes={}, side_effect=insert_review)


def release_hold(conn: sqlite3.Connection, *, subject_identifier: Any, hold_identifier: Any, owner_authority: Any, owner_revision: Any, evidence: Any, scope: Any, limitations: Any, actor: Any, expected_version: Any, idempotency_key: Any, reason: Any) -> dict[str, Any]:
    """H-08/H-10: only an owner may execute a separately reviewed synthetic release."""
    subject = _subject(conn, subject_identifier); policy = _policy(conn, subject); owner = _actor(actor)
    _authority(conn, owner_authority, owner_revision, owner, "owner")
    _policy_authority(policy, owner_authority, owner_revision, "owner")
    _policy_review_requirement(policy, "hold_release", "owner_plus_independent_synthetic_review")
    if subject["procedure_state"] not in {"under_review", "closed"}:
        raise ValueError("retention_hold_release_state_invalid")
    if subject["procedure_state"] == "closed":
        _active_closure_history(conn, subject)
    if evidence is None: raise ValueError("retention_hold_action_evidence_required")
    hid = _required(hold_identifier, "retention_hold_identifier_required", 256); limits = _required(limitations, "retention_limitations_required"); hold_scope = _required(scope, "retention_hold_scope_required")
    hold = conn.execute("SELECT * FROM governed_retention_holds WHERE subject_id=? AND hold_identifier=? ORDER BY revision DESC LIMIT 1", (subject["id"], hid)).fetchone()
    action = conn.execute("SELECT * FROM governed_retention_hold_actions WHERE subject_id=? AND hold_id=? AND revision=? AND action='release'", (subject["id"], hold["id"] if hold else -1, hold["revision"] if hold else -1)).fetchone()
    review = conn.execute("SELECT * FROM governed_retention_reviews WHERE subject_id=? AND decision_id=? AND action='hold_release' ORDER BY id DESC LIMIT 1", (subject["id"], action["id"] if action else -1)).fetchone()
    if not hold or hold["state"] != "active" or not action or not review or review["reviewer"] == owner or review["revision"] != action["revision"] or review["result"] != "accepted": raise ValueError("retention_hold_release_review_required")
    if (action["subject_revision"] != subject["subject_revision"]
            or action["subject_binding_json"] != subject["subject_binding_json"]
            or action["policy_id"] != subject["policy_id"]
            or action["policy_revision"] != subject["policy_revision"]):
        raise ValueError("retention_hold_release_binding_invalid")
    try:
        review_evidence = json.loads(review["evidence_json"])
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("retention_hold_release_review_required") from exc
    if (not isinstance(review_evidence, Mapping) or not review_evidence.get("evidence")
            or not review_evidence.get("scope") or not review_evidence.get("limitations")):
        raise ValueError("retention_hold_release_review_required")
    _authority(conn, review["reviewer_fixture_id"], review["reviewer_fixture_revision"], review["reviewer"], "reviewer")
    _policy_authority(policy, review["reviewer_fixture_id"], review["reviewer_fixture_revision"], "reviewer")
    closed = subject["procedure_state"] == "closed"
    dependent_unavailable = subject["applicability_state"] == "unavailable"
    changes = {"eligibility_state":"unavailable" if dependent_unavailable else "stale", "approval_state":"unavailable" if dependent_unavailable and subject["approval_state"] == "approved_current" else ("stale" if subject["approval_state"] == "approved_current" else subject["approval_state"]), "applicability_state":"unavailable" if dependent_unavailable else "reassessment_required"}
    def insert_release(current: Mapping[str, Any], authenticated: str) -> None:
        conn.execute("INSERT INTO governed_retention_holds(subject_id,hold_identifier,revision,state,basis,evidence_json,scope,limitations,owner_fixture_id,owner_fixture_revision,actor,occurred_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (current["id"], hid, int(hold["revision"])+1, "released", _required(reason,"retention_reason_required"), _json(evidence), hold_scope, limits, owner_authority, int(owner_revision), authenticated, _now()))
    return _mutate(conn, identifier=subject_identifier, token=actor, expected_version=expected_version, idempotency_key=idempotency_key, reason=reason, operation="H-10" if closed else "H-08", payload={"hold":hid, "hold_revision":hold["revision"], "action_revision":action["revision"]}, allowed={_tuple(subject)}, changes=changes, side_effect=insert_release)


def assess_hold_context(conn: sqlite3.Connection, *, subject_identifier: Any, hold_identifier: Any | None, applicability: Any, evidence: Any, scope: Any, limitations: Any, actor: Any, expected_version: Any, idempotency_key: Any, reason: Any) -> dict[str, Any]:
    """H-01/H-02 bounded observations; they establish neither authority nor release."""
    subject = _subject(conn, subject_identifier); _policy(conn, subject)
    if subject["procedure_state"] != "under_review": raise ValueError("retention_hold_context_state_invalid")
    bounded_scope = _required(scope, "retention_hold_search_scope_required")
    bounded_limits = _required(limitations, "retention_limitations_required")
    if evidence is None: raise ValueError("retention_hold_context_evidence_required")
    if hold_identifier is None:
        op="H-01"; payload={"bounded_search":True, "evidence":evidence, "scope":bounded_scope, "limitations":bounded_limits, "subject_revision":subject["subject_revision"], "subject_binding_json":subject["subject_binding_json"], "policy_id":subject["policy_id"], "policy_revision":subject["policy_revision"]}
    else:
        row=conn.execute("SELECT id FROM governed_retention_holds WHERE subject_id=? AND hold_identifier=? ORDER BY revision DESC LIMIT 1",(subject["id"],_required(hold_identifier,"retention_hold_identifier_required",256))).fetchone()
        if not row: raise ValueError("retention_hold_not_found")
        if applicability not in {"applicable", "not_applicable", "unresolved", "unavailable"}:
            raise ValueError("retention_hold_applicability_assessment_required")
        searches = conn.execute("SELECT details_json FROM governed_retention_history WHERE subject_id=? AND operation_id='H-01' ORDER BY id DESC", (subject["id"],)).fetchall()
        search = None
        for candidate in searches:
            try: observed = json.loads(candidate["details_json"]).get("payload", {})
            except (TypeError, json.JSONDecodeError): observed = {}
            if (observed.get("scope") == bounded_scope
                    and observed.get("subject_revision") == subject["subject_revision"]
                    and observed.get("subject_binding_json") == subject["subject_binding_json"]
                    and observed.get("policy_id") == subject["policy_id"]
                    and observed.get("policy_revision") == subject["policy_revision"]):
                search = observed; break
        if not search: raise ValueError("retention_hold_search_binding_required")
        exact_hold = conn.execute("SELECT hold_identifier,revision FROM governed_retention_holds WHERE id=?", (row["id"],)).fetchone()
        op="H-02"; payload={"hold_identifier":hold_identifier,"hold_revision":exact_hold["revision"],"applicability":applicability,"evidence":evidence,"scope":bounded_scope,"limitations":bounded_limits,"search_subject_revision":search["subject_revision"],"search_policy_revision":search["policy_revision"],"subject_revision":subject["subject_revision"],"subject_binding_json":subject["subject_binding_json"],"policy_id":subject["policy_id"],"policy_revision":subject["policy_revision"]}
    return _mutate(conn, identifier=subject_identifier, token=actor, expected_version=expected_version, idempotency_key=idempotency_key, reason=reason, operation=op, payload=payload, allowed={_tuple(subject)}, changes={})


def review_hold_observational(conn: sqlite3.Connection, *, subject_identifier: Any, hold_identifier: Any, findings: Any, next_point: Any, actor: Any, expected_version: Any, idempotency_key: Any, reason: Any) -> dict[str, Any]:
    """H-05 records observations only; it cannot amend, release, or confer authority."""
    subject = _subject(conn, subject_identifier); _policy(conn, subject)
    if subject["procedure_state"] != "under_review": raise ValueError("retention_hold_review_state_invalid")
    hid = _required(hold_identifier, "retention_hold_identifier_required", 256)
    hold = conn.execute("SELECT * FROM governed_retention_holds WHERE subject_id=? AND hold_identifier=? ORDER BY revision DESC LIMIT 1", (subject["id"], hid)).fetchone()
    if not hold: raise ValueError("retention_hold_not_found")
    finding = _required(findings, "retention_hold_review_findings_required"); point = _required(next_point, "retention_next_review_required")
    return _mutate(conn, identifier=subject_identifier, token=actor, expected_version=expected_version, idempotency_key=idempotency_key, reason=reason, operation="H-05", payload={"hold":hid,"hold_revision":hold["revision"],"findings":finding,"next_point":point,"subject_revision":subject["subject_revision"],"subject_binding_json":subject["subject_binding_json"],"policy_id":subject["policy_id"],"policy_revision":subject["policy_revision"]}, allowed={_tuple(subject)}, changes={})


def apply_review_due(conn: sqlite3.Connection, *, subject_identifier: Any, reached_point: Any, actor: Any, expected_version: Any, idempotency_key: Any, reason: Any) -> dict[str, Any]:
    """RD-01--10: exact review-point observation, never an implicit renewal."""
    # Preserve the normal historical-receipt contract even though a successful
    # first attempt necessarily changes the tuple out of the RD start shape.
    # The authenticated actor and immutable fixture are still checked before a
    # replay is returned; a different request under the same key remains a
    # conflict in _mutate.
    _actor(actor)
    subject = _subject(conn, subject_identifier); policy = _policy(conn, subject)
    due_binding = _derive_reached_review_point(subject, policy, reached_point)
    key = _required(idempotency_key, "retention_idempotency_key_required", 128)
    why = _required(reason, "retention_reason_required")
    payload = {"reached_point":due_binding["identity"],"review_point_revision":due_binding["revision"],"due_at":due_binding["due_at"],"subject_revision":due_binding["subject_revision"],"policy_revision":subject["policy_revision"]}
    # Operation ID is phase-specific, so compare the key against the existing
    # receipt after accepting any exact RD canonical variant below.
    existing = conn.execute("SELECT canonical_json,receipt_json FROM governed_retention_receipts WHERE idempotency_key=?", (key,)).fetchone()
    if existing:
        saved = json.loads(existing["canonical_json"])
        if saved.get("identifier") == subject_identifier and saved.get("expected_version") == expected_version and saved.get("reason") == why and saved.get("payload") == payload and str(saved.get("operation", "")).startswith("RD-"):
            receipt = json.loads(existing["receipt_json"]); receipt["historical"] = True; return receipt
        raise ValueError("retention_idempotency_conflict")
    true = policy["review_due_invalidates_current_reliance"]
    closed = subject["procedure_state"] == "closed"
    deferred = subject["retention_review"] == "deferred"
    if deferred:
        _deferred_due_predecessor(conn, subject, _required(reached_point, "retention_review_point_required"))
    if deferred and subject["decision_state"] == "none" and subject["approval_state"] == "not_recorded" and subject["procedure_state"] == "under_review":
        op = "RD-05" if true else "RD-06"
        changes = {"retention_review":"due"}
    elif subject["approval_state"] == "approved_current" and subject["applicability_state"] == "current" and subject["decision_state"] in {"proposed_eligible_for_future_scope", "proposed_ineligible_for_future_scope"}:
        # RD-01--04 and RD-07--10 require an actual current approved chain;
        # callers cannot manufacture a due observation from a matching tuple.
        _current_approved_chain(conn, subject)
        if true:
            if deferred: op = "RD-08" if closed else "RD-07"
            else: op = "RD-02" if closed else "RD-01"
            changes={"retention_review":"due","eligibility_state":"stale","approval_state":"stale","applicability_state":"reassessment_required"}
        else:
            if deferred: op = "RD-10" if closed else "RD-09"
            else: op = "RD-04" if closed else "RD-03"
            changes={"retention_review":"due"}
    else:
        raise ValueError("retention_review_due_current_decision_required")
    return _mutate(conn, identifier=subject_identifier, token=actor, expected_version=expected_version, idempotency_key=idempotency_key, reason=reason, operation=op, payload=payload, allowed={_tuple(subject)}, changes=changes)


def recover_true_due(conn: sqlite3.Connection, *, subject_identifier: Any, owner_authority: Any, owner_revision: Any, actor: Any, expected_version: Any, idempotency_key: Any, reason: Any) -> dict[str, Any]:
    """TRD-01-E/I: only an open true-due chain may re-enter assessment."""
    subject=_subject(conn,subject_identifier); policy=_policy(conn,subject); authenticated = _actor(actor)
    _authority(conn, owner_authority, owner_revision, authenticated, "owner")
    _policy_authority(policy, owner_authority, owner_revision, "owner")
    if policy["review_due_invalidates_current_reliance"] is not True or subject["procedure_state"] != "under_review" or subject["retention_review"] != "due" or subject["approval_state"] != "stale" or subject["applicability_state"] != "reassessment_required": raise ValueError("retention_true_due_recovery_state_invalid")
    if subject["decision_state"] == "proposed_eligible_for_future_scope": op="TRD-01-E"
    elif subject["decision_state"] == "proposed_ineligible_for_future_scope": op="TRD-01-I"
    else: raise ValueError("retention_true_due_recovery_state_invalid")
    due = conn.execute("SELECT details_json FROM governed_retention_history WHERE subject_id=? AND operation_id IN ('RD-01','RD-07') ORDER BY id DESC LIMIT 1", (subject["id"],)).fetchone()
    if not due: raise ValueError("retention_true_due_observation_required")
    try: due_payload = json.loads(due["details_json"]).get("payload", {})
    except (TypeError, json.JSONDecodeError): due_payload = {}
    binding = _review_point_binding(subject, policy)
    if (due_payload.get("policy_revision") != subject["policy_revision"]
            or due_payload.get("subject_revision") != subject["subject_revision"]
            or due_payload.get("reached_point") != binding["identity"]
            or due_payload.get("review_point_revision") != binding["revision"]
            or due_payload.get("due_at") != binding["due_at"]):
        raise ValueError("retention_true_due_observation_required")
    _current_approved_chain(conn, subject, allow_true_due_stale=True)
    return _mutate(conn,identifier=subject_identifier,token=actor,expected_version=expected_version,idempotency_key=idempotency_key,reason=reason,operation=op,payload={"owner_authority":owner_authority,"owner_revision":owner_revision,"due_observation":{"review_point":binding["identity"],"revision":binding["revision"],"due_at":binding["due_at"],"subject_revision":subject["subject_revision"],"policy_revision":subject["policy_revision"]}},allowed={_tuple(subject)},changes={"retention_review":"under_assessment","eligibility_state":"under_assessment","decision_state":"none","approval_state":"not_recorded","applicability_state":"not_evaluated"})


def recurring_review(conn: sqlite3.Connection, *, subject_identifier: Any, action: str, actor: Any, expected_version: Any, idempotency_key: Any, reason: Any, details: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """RR-E/I and RR-CE/CI 01--06, observational only under a false policy."""
    if action not in {"start", "await_information", "resume_information", "complete", "defer", "resume_deferred"}:
        raise ValueError("retention_recurring_review_action_invalid")
    subject = _subject(conn, subject_identifier); policy = _policy(conn, subject)
    if policy["review_due_invalidates_current_reliance"] is not False:
        raise ValueError("retention_recurring_review_policy_invalid")
    if subject["decision_state"] not in {"proposed_eligible_for_future_scope", "proposed_ineligible_for_future_scope"} or subject["approval_state"] != "approved_current" or subject["applicability_state"] != "current" or subject["procedure_state"] not in {"under_review", "closed"}:
        raise ValueError("retention_recurring_review_shape_invalid")
    _current_approved_chain(conn, subject)
    outcome = "E" if subject["decision_state"] == "proposed_eligible_for_future_scope" else "I"
    closed = subject["procedure_state"] == "closed"; prefix = f"RR-C{outcome}" if closed else f"RR-{outcome}"
    suffix = {"start":"01", "await_information":"02", "resume_information":"03", "complete":"04", "defer":"05", "resume_deferred":"06"}[action]
    previous = conn.execute("SELECT * FROM governed_retention_recurring_reviews WHERE subject_id=? AND outcome=? AND procedure_state=? ORDER BY id DESC LIMIT 1", (subject["id"], outcome, subject["procedure_state"])).fetchone()
    if previous and (previous["policy_id"] != subject["policy_id"]
                     or previous["policy_revision"] != subject["policy_revision"]):
        raise ValueError("retention_recurring_review_binding_invalid")
    if previous:
        try:
            previous_details = json.loads(previous["details_json"])
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("retention_recurring_review_binding_invalid") from exc
        if (previous_details.get("subject_revision") != subject["subject_revision"]
                or previous_details.get("subject_binding_json") != subject["subject_binding_json"]
                or previous_details.get("policy_id") != subject["policy_id"]
                or previous_details.get("policy_revision") != subject["policy_revision"]):
            raise ValueError("retention_recurring_review_binding_invalid")
    if action == "start":
        if subject["retention_review"] != "due" or previous: raise ValueError("retention_recurring_review_start_invalid")
        next_state, changes = "started", {}
    elif action == "await_information":
        if subject["retention_review"] != "due" or not previous or previous["state"] not in {"started", "resumed"}: raise ValueError("retention_recurring_review_await_invalid")
        if not (details or {}).get("missing_information"): raise ValueError("retention_missing_information_required")
        next_state, changes = "awaiting_information", {}
    elif action == "resume_information":
        if subject["retention_review"] != "due" or not previous or previous["state"] != "awaiting_information": raise ValueError("retention_recurring_review_resume_invalid")
        if not (details or {}).get("evidence"): raise ValueError("retention_recurring_review_evidence_required")
        next_state, changes = "resumed", {}
    elif action == "complete":
        if subject["retention_review"] != "due" or not previous or previous["state"] not in {"started", "resumed"}: raise ValueError("retention_recurring_review_complete_invalid")
        if not (details or {}).get("next_point") or not (details or {}).get("responsible"): raise ValueError("retention_next_review_required")
        next_state, changes = "completed", {"retention_review":"assessed"}
    elif action == "defer":
        if subject["retention_review"] != "due" or not previous or previous["state"] not in {"started", "resumed"}: raise ValueError("retention_recurring_review_defer_invalid")
        if not (details or {}).get("next_point") or not (details or {}).get("responsible"): raise ValueError("retention_next_review_required")
        next_state, changes = "deferred", {"retention_review":"deferred"}
    else:
        if subject["retention_review"] != "deferred" or not previous or previous["state"] != "deferred": raise ValueError("retention_recurring_review_deferred_resume_invalid")
        if not (details or {}).get("resumption_basis"): raise ValueError("retention_recurring_review_resumption_basis_required")
        deferred_details = previous_details
        if not deferred_details.get("next_point") or not deferred_details.get("responsible"):
            raise ValueError("retention_recurring_review_binding_invalid")
        next_state, changes = "resumed", {"retention_review":"due"}
    def insert_recurring(current: Mapping[str, Any], authenticated: str) -> None:
        bound_details = {**dict(details or {}), "subject_revision":current["subject_revision"], "subject_binding_json":current["subject_binding_json"], "policy_id":current["policy_id"], "policy_revision":current["policy_revision"]}
        if action == "complete":
            point = _review_point_binding(current, policy)
            bound_details.update({"completed_point_identity": point["identity"], "completed_point_revision": point["revision"]})
        conn.execute("INSERT INTO governed_retention_recurring_reviews(subject_id,outcome,procedure_state,state,policy_id,policy_revision,details_json,actor,occurred_at) VALUES(?,?,?,?,?,?,?,?,?)", (current["id"], outcome, current["procedure_state"], next_state, current["policy_id"], current["policy_revision"], _json(bound_details), authenticated, _now()))
    return _mutate(conn, identifier=subject_identifier, token=actor, expected_version=expected_version, idempotency_key=idempotency_key, reason=reason, operation=f"{prefix}-{suffix}", payload={"action":action, "details":dict(details or {})}, allowed={_tuple(subject)}, changes=changes, side_effect=insert_recurring)


def get_subject(conn: sqlite3.Connection, identifier: Any) -> dict[str, Any]:
    subject = _subject(conn, identifier)
    # Reads are private, but may still be consequential because callers use
    # this projection to decide whether an approval is current.  Deliberately
    # derive from the current immutable policy revision rather than returning
    # an unobserved reached point as a current raw tuple.
    try:
        result = _derived_projection(conn, subject, _policy(conn, subject))
    except ValueError as exc:
        if str(exc) not in {"retention_policy_unavailable", "retention_policy_invalid", "retention_policy_review_due_invalid"}:
            raise
        result = _unavailable_policy_projection(subject, exc)
    result["stored_tuple"] = _tuple(subject)
    result["tuple"] = _tuple(result)
    result["active_holds"] = _active_holds(conn, int(subject["id"]))
    result["history"] = [dict(x) for x in conn.execute("SELECT * FROM governed_retention_history WHERE subject_id=? ORDER BY id", (subject["id"],))]
    return result


def render_private_status(subject: Mapping[str, Any]) -> str:
    if subject.get("procedure_state") == "closed" and subject.get("applicability_state") != "current": return "Closed — reassessment required"
    return "Private synthetic-only decision record"
