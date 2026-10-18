"""Stage 83 private, synthetic-only access-decision register foundation.

It deliberately has no admission, material, package, release, delivery,
redaction, export, or execution capability.  Disposable tests seed synthetic
rows directly; production routes/services reject creation before body content
is retained.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from api.admin_session_verification import AdminSessionVerificationError, verify_signed_admin_session
from api import governed_defect_register as defect_register
from api import governed_challenge_register as challenge_register

ASSESSMENTS = frozenset({"unassessed", "under_assessment", "awaiting_information", "assessment_complete"})
APPROVALS = frozenset({"not_recorded", "pending", "approved_current", "not_approved", "stale", "unavailable"})
OUTCOMES = frozenset({"none", "proposed_allow", "proposed_allow_with_conditions", "withhold", "decline", "withdrawn", "superseded"})
APPLICABILITY = frozenset({"not_evaluated", "current", "stale", "review_due", "expired", "blocked_hold_relevance", "unavailable"})
FINAL_OUTCOMES = OUTCOMES - {"none"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _loads(value: Any, default: Any) -> Any:
    try: return json.loads(value) if value else default
    except (TypeError, json.JSONDecodeError): return default


def _required(value: Any, code: str, maximum: int = 8000) -> str:
    value = str(value or "").strip()
    if not value or len(value) > maximum: raise ValueError(code)
    return value


def _actor(token: Any) -> str:
    try: session = verify_signed_admin_session(token)
    except AdminSessionVerificationError as exc: raise ValueError("disclosure_register_authenticated_actor_required") from exc
    return _required(session.get("username"), "disclosure_register_authenticated_actor_required", 256)


def _version(value: Any) -> int:
    try: value = int(value)
    except (TypeError, ValueError) as exc: raise ValueError("disclosure_register_expected_version_invalid") from exc
    if value < 0: raise ValueError("disclosure_register_expected_version_invalid")
    return value


def _key(value: Any) -> str:
    return _required(value, "disclosure_register_idempotency_key_required", 128)


def ensure_tables(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("""CREATE TABLE IF NOT EXISTS governed_disclosure_requests (
      id INTEGER PRIMARY KEY, request_identifier TEXT UNIQUE NOT NULL,
      request_revision INTEGER NOT NULL, procedural_state TEXT NOT NULL,
      version INTEGER NOT NULL, created_at TEXT NOT NULL, created_by TEXT NOT NULL,
      updated_at TEXT NOT NULL, updated_by TEXT NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS governed_disclosure_items (
      id INTEGER PRIMARY KEY, request_id INTEGER NOT NULL, item_identifier TEXT NOT NULL,
      object_type TEXT NOT NULL, object_identity TEXT NOT NULL, object_version TEXT NOT NULL,
      item_revision INTEGER NOT NULL, assessment_state TEXT NOT NULL, approval_state TEXT NOT NULL,
      outcome TEXT NOT NULL, applicability_state TEXT NOT NULL, conditions_json TEXT NOT NULL,
      hold_json TEXT NOT NULL, version INTEGER NOT NULL, UNIQUE(request_id,item_identifier),
      FOREIGN KEY(request_id) REFERENCES governed_disclosure_requests(id))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS governed_disclosure_history (
      id INTEGER PRIMARY KEY, request_id INTEGER NOT NULL, item_id INTEGER,
      event_type TEXT NOT NULL, revision INTEGER NOT NULL, actor TEXT NOT NULL,
      occurred_at TEXT NOT NULL, reason TEXT NOT NULL, details_json TEXT NOT NULL,
      FOREIGN KEY(request_id) REFERENCES governed_disclosure_requests(id))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS governed_disclosure_assessments (
      id INTEGER PRIMARY KEY, request_id INTEGER NOT NULL, item_id INTEGER NOT NULL,
      request_revision INTEGER NOT NULL, item_revision INTEGER NOT NULL,
      basis TEXT NOT NULL, evidence_json TEXT NOT NULL, limitations TEXT NOT NULL,
      rule_identity TEXT NOT NULL, authority_identity TEXT NOT NULL, actor TEXT NOT NULL,
      recorded_at TEXT NOT NULL, FOREIGN KEY(item_id) REFERENCES governed_disclosure_items(id))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS governed_disclosure_outcomes (
      id INTEGER PRIMARY KEY, request_id INTEGER NOT NULL, item_id INTEGER NOT NULL,
      assessment_id INTEGER NOT NULL, outcome TEXT NOT NULL, outcome_revision INTEGER NOT NULL,
      details_json TEXT NOT NULL, actor TEXT NOT NULL, recorded_at TEXT NOT NULL,
      FOREIGN KEY(assessment_id) REFERENCES governed_disclosure_assessments(id))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS governed_disclosure_approvals (
      id INTEGER PRIMARY KEY, request_id INTEGER NOT NULL, item_id INTEGER NOT NULL,
      outcome_id INTEGER NOT NULL, outcome_revision INTEGER NOT NULL, assessment_id INTEGER NOT NULL,
      rule_identity TEXT NOT NULL, authority_identity TEXT NOT NULL, actor TEXT NOT NULL,
      recorded_at TEXT NOT NULL, FOREIGN KEY(outcome_id) REFERENCES governed_disclosure_outcomes(id))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS governed_disclosure_receipts (
      id INTEGER PRIMARY KEY, idempotency_key TEXT UNIQUE NOT NULL, request_identifier TEXT NOT NULL,
      canonical_json TEXT NOT NULL, receipt_json TEXT NOT NULL, created_at TEXT NOT NULL)""")
    # Fixture-only authority source. No production route/service can create
    # one; a caller's string is merely a claim until this source resolves it.
    conn.execute("""CREATE TABLE IF NOT EXISTS governed_disclosure_synthetic_authorities (
      id INTEGER PRIMARY KEY, rule_identity TEXT NOT NULL, authority_identity TEXT NOT NULL,
      approver_username TEXT NOT NULL, revision INTEGER NOT NULL, requires_review INTEGER NOT NULL DEFAULT 0,
      available INTEGER NOT NULL DEFAULT 1, UNIQUE(rule_identity,authority_identity,revision))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS governed_disclosure_applicability_events (
      id INTEGER PRIMARY KEY, request_id INTEGER NOT NULL, item_id INTEGER NOT NULL,
      condition TEXT NOT NULL, basis TEXT NOT NULL, actor TEXT NOT NULL, occurred_at TEXT NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS governed_disclosure_relationships (
      id INTEGER PRIMARY KEY, request_id INTEGER NOT NULL, predecessor_item_id INTEGER NOT NULL,
      successor_item_id INTEGER NOT NULL, predecessor_revision INTEGER NOT NULL,
      successor_revision INTEGER NOT NULL, basis TEXT NOT NULL, limitations TEXT NOT NULL,
      actor TEXT NOT NULL, recorded_at TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
      UNIQUE(request_id,predecessor_item_id,successor_item_id))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS governed_disclosure_obligations (
      id INTEGER PRIMARY KEY, request_id INTEGER NOT NULL, item_id INTEGER NOT NULL,
      outcome_assessment_id INTEGER,
      description TEXT NOT NULL, owner TEXT NOT NULL, status TEXT NOT NULL,
      created_at TEXT NOT NULL, created_by TEXT NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS governed_disclosure_outcome_assessments (
      id INTEGER PRIMARY KEY, request_id INTEGER NOT NULL, item_id INTEGER NOT NULL,
      request_revision INTEGER NOT NULL, item_revision INTEGER NOT NULL,
      proposed_outcome TEXT NOT NULL, basis TEXT NOT NULL, evidence_json TEXT NOT NULL,
      validation_scope TEXT NOT NULL, assessment_scope TEXT NOT NULL,
      limitations TEXT NOT NULL, obligations_json TEXT NOT NULL,
      successor_item_id INTEGER, successor_request_revision INTEGER,
      successor_item_revision INTEGER, assessment_id INTEGER NOT NULL,
      authority_fixture_id INTEGER NOT NULL, authority_fixture_revision INTEGER NOT NULL,
      actor TEXT NOT NULL, recorded_at TEXT NOT NULL,
      FOREIGN KEY(item_id) REFERENCES governed_disclosure_items(id))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS governed_disclosure_workflow_links (
      id INTEGER PRIMARY KEY, request_id INTEGER NOT NULL, item_id INTEGER NOT NULL,
      request_revision INTEGER NOT NULL, item_revision INTEGER NOT NULL,
      workflow_kind TEXT NOT NULL, target_identifier TEXT NOT NULL,
      target_revision INTEGER NOT NULL, requirement_identifier TEXT,
      issue_identifier TEXT, relationship_purpose TEXT NOT NULL DEFAULT 'context',
      assessment_id INTEGER, target_binding_json TEXT NOT NULL DEFAULT '{}',
      relationship_scope TEXT NOT NULL, basis TEXT NOT NULL,
      limitations TEXT NOT NULL, actor TEXT NOT NULL, recorded_at TEXT NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS governed_disclosure_outcome_relationship_bindings (
      id INTEGER PRIMARY KEY, request_id INTEGER NOT NULL, item_id INTEGER NOT NULL,
      outcome_id INTEGER NOT NULL, outcome_revision INTEGER NOT NULL,
      relationship_id INTEGER NOT NULL, purpose TEXT NOT NULL,
      actor TEXT NOT NULL, recorded_at TEXT NOT NULL,
      UNIQUE(outcome_id, relationship_id),
      FOREIGN KEY(outcome_id) REFERENCES governed_disclosure_outcomes(id),
      FOREIGN KEY(relationship_id) REFERENCES governed_disclosure_workflow_links(id))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS governed_disclosure_synthetic_reviews (
      id INTEGER PRIMARY KEY, outcome_id INTEGER NOT NULL UNIQUE,
      authority_fixture_id INTEGER NOT NULL, authority_fixture_revision INTEGER NOT NULL,
      reviewer_username TEXT NOT NULL, recorded_at TEXT NOT NULL)""")
    # Additive migration for worktrees created from an earlier Stage 83 patch.
    for table, column, definition in (
        ("governed_disclosure_assessments", "authority_fixture_id", "INTEGER"),
        ("governed_disclosure_assessments", "authority_fixture_revision", "INTEGER"),
        ("governed_disclosure_outcomes", "rule_identity", "TEXT"),
        ("governed_disclosure_outcomes", "authority_fixture_id", "INTEGER"),
        ("governed_disclosure_outcomes", "authority_fixture_revision", "INTEGER"),
        ("governed_disclosure_approvals", "authority_fixture_id", "INTEGER"),
        ("governed_disclosure_approvals", "authority_fixture_revision", "INTEGER"),
    ):
        columns = {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    workflow_columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(governed_disclosure_workflow_links)")}
    for column, definition in (
        ("relationship_purpose", "TEXT NOT NULL DEFAULT 'context'"),
        ("assessment_id", "INTEGER"),
        ("target_binding_json", "TEXT NOT NULL DEFAULT '{}'"),
    ):
        if column not in workflow_columns:
            conn.execute(f"ALTER TABLE governed_disclosure_workflow_links ADD COLUMN {column} {definition}")
    obligation_columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(governed_disclosure_obligations)")}
    if "outcome_assessment_id" not in obligation_columns:
        conn.execute("ALTER TABLE governed_disclosure_obligations ADD COLUMN outcome_assessment_id INTEGER")
    for table in ("governed_disclosure_history", "governed_disclosure_assessments", "governed_disclosure_outcomes", "governed_disclosure_approvals", "governed_disclosure_applicability_events", "governed_disclosure_relationships", "governed_disclosure_obligations", "governed_disclosure_outcome_assessments", "governed_disclosure_workflow_links", "governed_disclosure_outcome_relationship_bindings", "governed_disclosure_synthetic_reviews"):
        conn.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_immutable_update BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT,'disclosure_register_history_immutable'); END")
        conn.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_immutable_delete BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT,'disclosure_register_history_immutable'); END")


def create_request(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
    raise ValueError("disclosure_register_admission_disabled")


def _request(conn: sqlite3.Connection, identifier: Any) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM governed_disclosure_requests WHERE request_identifier=?", (_required(identifier, "disclosure_register_identifier_invalid", 256),)).fetchone()
    if not row: raise ValueError("disclosure_register_not_found")
    return dict(row)


def _item(conn: sqlite3.Connection, request: Mapping[str, Any], identifier: Any) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM governed_disclosure_items WHERE request_id=? AND item_identifier=?", (request["id"], _required(identifier, "disclosure_register_item_identifier_invalid", 256))).fetchone()
    if not row: raise ValueError("disclosure_register_item_not_found")
    return dict(row)


def _current_authority_fixture(conn: sqlite3.Connection, *, rule: str, authority: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM governed_disclosure_synthetic_authorities WHERE rule_identity=? AND authority_identity=? ORDER BY revision DESC LIMIT 1", (rule, authority)).fetchone()
    return dict(row) if row is not None and int(row["available"]) == 1 else None


def _fixture_current(conn: sqlite3.Connection, assessment: Mapping[str, Any]) -> bool:
    fixture_id, revision = assessment.get("authority_fixture_id"), assessment.get("authority_fixture_revision")
    if fixture_id is None or revision is None:
        return False
    fixture = _current_authority_fixture(conn, rule=str(assessment["rule_identity"]), authority=str(assessment["authority_identity"]))
    return bool(fixture and int(fixture["id"]) == int(fixture_id) and int(fixture["revision"]) == int(revision))


def _current_assessment(conn: sqlite3.Connection, request: Mapping[str, Any], item: Mapping[str, Any]) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM governed_disclosure_assessments WHERE item_id=? ORDER BY id DESC LIMIT 1", (item["id"],)).fetchone()
    if not row: return None
    row = dict(row)
    return row if (row["request_revision"] == request["request_revision"]
                   and row["item_revision"] == item["item_revision"]
                   and _fixture_current(conn, row)) else None


def _authority_fixture(conn: sqlite3.Connection, *, rule: str, authority: str, actor: str) -> dict[str, Any]:
    item = _current_authority_fixture(conn, rule=rule, authority=authority)
    if not item or str(item["approver_username"]) != actor:
        raise ValueError("disclosure_register_authority_unavailable")
    return item


def _review_current(conn: sqlite3.Connection, *, outcome_id: int, fixture: Mapping[str, Any]) -> bool:
    row = conn.execute("SELECT * FROM governed_disclosure_synthetic_reviews WHERE outcome_id=?", (outcome_id,)).fetchone()
    return bool(row and int(row["authority_fixture_id"]) == int(fixture["id"]) and int(row["authority_fixture_revision"]) == int(fixture["revision"]))


def _item_by_id(conn: sqlite3.Connection, request: Mapping[str, Any], item_id: int) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM governed_disclosure_items WHERE request_id=? AND id=?", (request["id"], item_id)).fetchone()
    if row is None:
        raise ValueError("disclosure_register_successor_binding_mismatch")
    return dict(row)


def _current_outcome_assessment(conn: sqlite3.Connection, request: Mapping[str, Any], item: Mapping[str, Any], outcome: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM governed_disclosure_outcome_assessments WHERE request_id=? AND item_id=? AND proposed_outcome=? ORDER BY id DESC LIMIT 1", (request["id"], item["id"], outcome)).fetchone()
    if row is None:
        return None
    assessment = dict(row)
    if (assessment["request_revision"] != request["request_revision"]
            or assessment["item_revision"] != item["item_revision"]):
        return None
    standard = conn.execute("SELECT * FROM governed_disclosure_assessments WHERE id=?", (assessment["assessment_id"],)).fetchone()
    if standard is None or not _fixture_current(conn, dict(standard)):
        return None
    if int(assessment["authority_fixture_id"]) != int(standard["authority_fixture_id"]) or int(assessment["authority_fixture_revision"]) != int(standard["authority_fixture_revision"]):
        return None
    if outcome == "superseded":
        if assessment["successor_item_id"] is None:
            return None
        successor = _item_by_id(conn, request, int(assessment["successor_item_id"]))
        if (assessment["successor_request_revision"] != request["request_revision"]
                or assessment["successor_item_revision"] != successor["item_revision"]
                or not _current_assessment(conn, request, successor)):
            return None
    return assessment


def _active_obligations(conn: sqlite3.Connection, request: Mapping[str, Any], item: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM governed_disclosure_obligations WHERE request_id=? AND item_id=? ORDER BY id", (request["id"], item["id"])).fetchall()
    result = []
    for row in rows:
        value = dict(row)
        value["active"] = value["status"] not in {"completed", "superseded", "cancelled"}
        if value.get("outcome_assessment_id") is not None:
            source = conn.execute("SELECT proposed_outcome FROM governed_disclosure_outcome_assessments WHERE id=?", (value["outcome_assessment_id"],)).fetchone()
            current = source is not None and _current_outcome_assessment(conn, request, item, str(source["proposed_outcome"])) is not None
            value["source_state"] = "current" if current else "requires_reassessment"
        else:
            value["source_state"] = "unknown"
        result.append(value)
    return result


def _workflow_state(conn: sqlite3.Connection, link: Mapping[str, Any]) -> dict[str, Any]:
    """Resolve a bounded local relationship without executing another workflow.

    A ``context`` link establishes only that a stated local target/version was
    available when recorded.  A ``required`` link additionally records the
    authoritative chain consumed by the current decision.  The latter must
    reproduce exactly at every consequential use; a target identifier or a
    same-entry requirement never establishes that chain by itself.
    """
    try:
        kind = str(link["workflow_kind"])
        required = str(link.get("relationship_purpose") or "context") == "required"
        stored = _loads(link.get("target_binding_json"), {})
        if kind in {"stage81", "stage81_1"}:
            entry = defect_register.get_entry(conn, str(link["target_identifier"]))
            if int(entry.get("version", -1)) != int(link["target_revision"]):
                return {"status": "stale"}
            if not required:
                return {"status": "current"}
            # Stage 82 already owns the approved exact Stage 81/81.1 chain
            # resolver.  Consuming it preserves the source workflow's
            # verification semantics without granting Stage 83 any execution
            # authority.
            if kind == "stage81":
                chain = challenge_register._stage81_verified_chain(conn, str(link["target_identifier"]))
            else:
                chain = challenge_register._stage811_requirement_chain(
                    conn, str(link["target_identifier"]), str(link.get("requirement_identifier") or "")
                )
            if chain != stored:
                return {"status": "stale"}
            return {"status": "current", "chain": chain}
        if kind == "stage82":
            challenge = challenge_register.get_challenge(conn, str(link["target_identifier"]))
            if int(challenge.get("version", -1)) != int(link["target_revision"]):
                return {"status": "stale"}
            issue = next((i for i in challenge.get("issues", []) if i.get("issue_identifier") == link.get("issue_identifier")), None)
            if issue is None:
                return {"status": "unknown"}
            if not required:
                return {"status": "current"}
            chain = {
                "challenge_identifier": challenge["challenge_identifier"],
                "challenge_version": challenge["version"],
                "issue_identifier": issue["issue_identifier"],
                "issue_version": issue["version"],
                "subject_identity": challenge["subject_identity"],
                "issue_state": issue["issue_state"],
            }
            if chain != stored:
                return {"status": "stale"}
            return {"status": "current", "chain": chain}
    except (ValueError, sqlite3.Error):
        return {"status": "unknown"}
    return {"status": "unknown"}


def _relationship_current(conn: sqlite3.Connection, request: Mapping[str, Any], item: Mapping[str, Any], link: Mapping[str, Any], assessment: Mapping[str, Any]) -> bool:
    """Check immutable relationship assessment bindings at a consequential use."""
    if (link.get("request_revision") != request["request_revision"]
            or link.get("item_revision") != item["item_revision"]
            or int(link.get("assessment_id") or -1) != int(assessment["id"])):
        return False
    return _workflow_state(conn, link).get("status") == "current"


def _required_relationships_current(conn: sqlite3.Connection, request: Mapping[str, Any], item: Mapping[str, Any], outcome: Mapping[str, Any], assessment: Mapping[str, Any]) -> bool:
    rows = conn.execute("""SELECT l.* FROM governed_disclosure_outcome_relationship_bindings b
                           JOIN governed_disclosure_workflow_links l ON l.id=b.relationship_id
                           WHERE b.outcome_id=? AND b.purpose='required' ORDER BY b.id""", (outcome["id"],)).fetchall()
    return all(_relationship_current(conn, request, item, dict(row), assessment) for row in rows)


def _mark_noncurrent(conn: sqlite3.Connection, request: Mapping[str, Any], item: Mapping[str, Any], condition: str, basis: str, actor: str) -> None:
    if condition not in APPLICABILITY - {"current", "not_evaluated"}:
        raise ValueError("disclosure_register_applicability_invalid")
    conn.execute("UPDATE governed_disclosure_items SET approval_state=CASE WHEN approval_state='approved_current' THEN 'stale' ELSE approval_state END, applicability_state=?,version=version+1 WHERE id=?", (condition, item["id"]))
    conn.execute("INSERT INTO governed_disclosure_applicability_events(request_id,item_id,condition,basis,actor,occurred_at) VALUES(?,?,?,?,?,?)", (request["id"], item["id"], condition, basis, actor, _now()))


def _event(conn: sqlite3.Connection, request: Mapping[str, Any], item: Mapping[str, Any] | None, event: str, actor: str, reason: str, details: Mapping[str, Any]) -> None:
    conn.execute("INSERT INTO governed_disclosure_history(request_id,item_id,event_type,revision,actor,occurred_at,reason,details_json) VALUES(?,?,?,?,?,?,?,?)",
                 (request["id"], item and item["id"], event, request["version"] + 1, actor, _now(), reason, _json(details)))


def _summary(items: list[dict[str, Any]], closed: bool) -> dict[str, Any]:
    blocking = [i["item_identifier"] for i in items if i["assessment_state"] == "awaiting_information"]
    stale = [i["item_identifier"] for i in items if i["applicability_state"] != "current"]
    if closed and stale: state = "closed_reassessment_required"
    elif closed: state = "closed"
    elif all(i["assessment_state"] == "unassessed" for i in items): state = "recorded"
    elif blocking: state = "awaiting_information"
    elif any(i["assessment_state"] in {"unassessed", "under_assessment"} for i in items): state = "under_assessment"
    elif all(i["assessment_state"] == "assessment_complete" for i in items): state = "decided" if not stale else "decision_pending"
    else: state = "under_assessment"
    return {"state": state, "blocking_items": blocking, "noncurrent_items": stale}


def _closure_item_eligible(conn: sqlite3.Connection, request: Mapping[str, Any], item: Mapping[str, Any]) -> bool:
    assessment = _current_assessment(conn, request, item)
    if (not assessment or item["assessment_state"] != "assessment_complete"
            or item["approval_state"] != "approved_current"
            or item["outcome"] not in FINAL_OUTCOMES
            or item["applicability_state"] != "current"):
        return False
    outcome = conn.execute("SELECT * FROM governed_disclosure_outcomes WHERE item_id=? ORDER BY id DESC LIMIT 1", (item["id"],)).fetchone()
    approval = conn.execute("SELECT * FROM governed_disclosure_approvals WHERE item_id=? ORDER BY id DESC LIMIT 1", (item["id"],)).fetchone()
    if outcome is None or approval is None:
        return False
    if (int(outcome["assessment_id"]) != int(assessment["id"])
            or int(approval["outcome_id"]) != int(outcome["id"])
            or int(approval["assessment_id"]) != int(assessment["id"])
            or int(approval["authority_fixture_id"] or -1) != int(assessment["authority_fixture_id"])
            or int(approval["authority_fixture_revision"] or -1) != int(assessment["authority_fixture_revision"])):
        return False
    if not _required_relationships_current(conn, request, item, dict(outcome), assessment):
        return False
    if item["outcome"] in {"withdrawn", "superseded"} and _current_outcome_assessment(conn, request, item, item["outcome"]) is None:
        return False
    return True


def get_request(conn: sqlite3.Connection, identifier: Any) -> dict[str, Any]:
    request = _request(conn, identifier)
    items = [dict(row) for row in conn.execute("SELECT * FROM governed_disclosure_items WHERE request_id=? ORDER BY id", (request["id"],))]
    workflow_links, obligations = [], []
    for item in items:
        # A stored projection never outranks its immutable binding.
        assessment = _current_assessment(conn, request, item)
        special_current = item["outcome"] not in {"withdrawn", "superseded"} or _current_outcome_assessment(conn, request, item, item["outcome"]) is not None
        outcome = conn.execute("SELECT * FROM governed_disclosure_outcomes WHERE item_id=? ORDER BY id DESC LIMIT 1", (item["id"],)).fetchone()
        relationships_current = bool(outcome is not None and assessment is not None and _required_relationships_current(conn, request, item, dict(outcome), assessment))
        if item["applicability_state"] == "current" and (not assessment or not special_current or not relationships_current):
            item["approval_state"], item["applicability_state"] = "stale", "stale"
        item["obligations"] = _active_obligations(conn, request, item)
        obligations.extend({"item_identifier": item["item_identifier"], **value} for value in item["obligations"])
        item_links = []
        for row in conn.execute("SELECT * FROM governed_disclosure_workflow_links WHERE request_id=? AND item_id=? ORDER BY id", (request["id"], item["id"])).fetchall():
            link = dict(row)
            if link["request_revision"] != request["request_revision"] or link["item_revision"] != item["item_revision"]:
                state = {"status": "stale"}
            else:
                state = _workflow_state(conn, link)
            link["state"] = state["status"]
            link["target_binding"] = _loads(link.get("target_binding_json"), {})
            item_links.append(link); workflow_links.append({"item_identifier": item["item_identifier"], **link})
        item["workflow_links"] = item_links
        item["conditions"] = _loads(item.pop("conditions_json"), {})
        item["hold"] = _loads(item.pop("hold_json"), {})
    history = [dict(row) for row in conn.execute("SELECT * FROM governed_disclosure_history WHERE request_id=? ORDER BY id", (request["id"],))]
    request["items"], request["history"] = items, history
    request["workflow_links"] = workflow_links
    request["obligations"] = obligations
    request["active_obligations"] = [value for value in obligations if value["active"]]
    request["summary"] = _summary(items, request["procedural_state"] == "closed")
    return request


def _mutation(conn: sqlite3.Connection, *, request_identifier: Any, actor: Any, expected_version: Any, idempotency_key: Any, reason: Any, operation: str, payload: Mapping[str, Any], apply: Callable[[dict[str, Any], str], None]) -> dict[str, Any]:
    identity, expected, key, why = _actor(actor), _version(expected_version), _key(idempotency_key), _required(reason, "disclosure_register_reason_required")
    rid = _required(request_identifier, "disclosure_register_identifier_invalid", 256)
    canonical = _json({"request_identifier": rid, "actor": identity, "expected_version": expected, "reason": why, "operation": operation, **payload})
    with conn:
        old = conn.execute("SELECT canonical_json,receipt_json FROM governed_disclosure_receipts WHERE idempotency_key=?", (key,)).fetchone()
        if old:
            if old[0] != canonical: raise ValueError("disclosure_register_idempotency_conflict")
            receipt = _loads(old[1], {}); receipt["historical_receipt"] = True; return receipt
        request = _request(conn, rid)
        if request["version"] != expected: raise ValueError("disclosure_register_version_conflict")
        apply(request, identity)
        conn.execute("UPDATE governed_disclosure_requests SET version=?,updated_at=?,updated_by=? WHERE id=?", (expected + 1, _now(), identity, request["id"]))
        receipt = {"request_identifier": rid, "operation": operation, "resulting_version": expected + 1, "historical_receipt": False}
        conn.execute("INSERT INTO governed_disclosure_receipts(idempotency_key,request_identifier,canonical_json,receipt_json,created_at) VALUES(?,?,?,?,?)", (key, rid, canonical, _json(receipt), _now()))
        return receipt


def begin_assessment(conn: sqlite3.Connection, *, request_identifier: Any, item_identifier: Any, actor: Any, expected_version: Any, idempotency_key: Any, reason: Any) -> dict[str, Any]:
    def apply(req, identity):
        item = _item(conn, req, item_identifier)
        if item["assessment_state"] not in {"unassessed", "awaiting_information"}: raise ValueError("disclosure_register_transition_invalid")
        conn.execute("UPDATE governed_disclosure_items SET assessment_state='under_assessment',version=version+1 WHERE id=?", (item["id"],))
        _event(conn, req, item, "assessment_started", identity, _required(reason, "disclosure_register_reason_required"), {})
    return _mutation(conn, request_identifier=request_identifier, actor=actor, expected_version=expected_version, idempotency_key=idempotency_key, reason=reason, operation="assessment_started", payload={"item": item_identifier}, apply=apply)


def request_information(conn: sqlite3.Connection, *, request_identifier: Any, item_identifier: Any, missing_information: Any, review_point: Any, actor: Any, expected_version: Any, idempotency_key: Any, reason: Any) -> dict[str, Any]:
    missing, review = _required(missing_information, "disclosure_register_information_required"), _required(review_point, "disclosure_register_review_required")
    def apply(req, identity):
        item = _item(conn, req, item_identifier)
        if item["assessment_state"] != "under_assessment": raise ValueError("disclosure_register_transition_invalid")
        conn.execute("UPDATE governed_disclosure_items SET assessment_state='awaiting_information',version=version+1 WHERE id=?", (item["id"],))
        _event(conn, req, item, "information_requested", identity, _required(reason, "disclosure_register_reason_required"), {"missing_information": missing, "review_point": review})
    return _mutation(conn, request_identifier=request_identifier, actor=actor, expected_version=expected_version, idempotency_key=idempotency_key, reason=reason, operation="information_requested", payload={"item": item_identifier, "missing": missing, "review": review}, apply=apply)


def complete_assessment(conn: sqlite3.Connection, *, request_identifier: Any, item_identifier: Any, basis: Any, evidence: Any, limitations: Any, rule_identity: Any, authority_identity: Any, actor: Any, expected_version: Any, idempotency_key: Any, reason: Any) -> dict[str, Any]:
    basis, limitations, rule, authority = _required(basis, "disclosure_register_basis_required"), _required(limitations, "disclosure_register_limitations_required"), _required(rule_identity, "disclosure_register_rule_required", 256), _required(authority_identity, "disclosure_register_authority_required", 256)
    if not isinstance(evidence, list) or not evidence: raise ValueError("disclosure_register_evidence_required")
    def apply(req, identity):
        item = _item(conn, req, item_identifier)
        if item["assessment_state"] != "under_assessment": raise ValueError("disclosure_register_transition_invalid")
        fixture = _authority_fixture(conn, rule=rule, authority=authority, actor=identity)
        cur = conn.execute("INSERT INTO governed_disclosure_assessments(request_id,item_id,request_revision,item_revision,basis,evidence_json,limitations,rule_identity,authority_identity,actor,recorded_at,authority_fixture_id,authority_fixture_revision) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                           (req["id"], item["id"], req["request_revision"], item["item_revision"], basis, _json(evidence), limitations, rule, authority, identity, _now(), fixture["id"], fixture["revision"]))
        conn.execute("UPDATE governed_disclosure_items SET assessment_state='assessment_complete',approval_state='not_recorded',outcome='none',applicability_state='not_evaluated',version=version+1 WHERE id=?", (item["id"],))
        _event(conn, req, item, "assessment_completed", identity, _required(reason, "disclosure_register_reason_required"), {"assessment_id": cur.lastrowid})
    return _mutation(conn, request_identifier=request_identifier, actor=actor, expected_version=expected_version, idempotency_key=idempotency_key, reason=reason, operation="assessment_completed", payload={"item": item_identifier, "rule": rule, "authority": authority}, apply=apply)


def record_outcome_assessment(conn: sqlite3.Connection, *, request_identifier: Any, item_identifier: Any,
                              proposed_outcome: Any, basis: Any, evidence: Any, validation_scope: Any,
                              assessment_scope: Any, limitations: Any, obligations: Any,
                              successor_item_identifier: Any = None, actor: Any,
                              expected_version: Any, idempotency_key: Any, reason: Any) -> dict[str, Any]:
    outcome = str(proposed_outcome or "")
    if outcome not in {"withdrawn", "superseded"}:
        raise ValueError("disclosure_register_outcome_assessment_outcome_invalid")
    basis_text = _required(basis, "disclosure_register_outcome_assessment_basis_required")
    scope = _required(assessment_scope, "disclosure_register_outcome_assessment_scope_required")
    validation = _required(validation_scope, "disclosure_register_outcome_assessment_validation_scope_required")
    limits = _required(limitations, "disclosure_register_outcome_assessment_limits_required")
    if not isinstance(evidence, list) or not evidence or not isinstance(obligations, list):
        raise ValueError("disclosure_register_outcome_assessment_evidence_required")
    def apply(req, identity):
        item = _item(conn, req, item_identifier)
        standard = _current_assessment(conn, req, item)
        if item["assessment_state"] != "assessment_complete" or item["approval_state"] != "not_recorded" or item["outcome"] != "none" or not standard:
            raise ValueError("disclosure_register_assessment_stale")
        successor = None
        if outcome == "superseded":
            successor = _item(conn, req, successor_item_identifier)
            if successor["id"] == item["id"] or not _current_assessment(conn, req, successor):
                raise ValueError("disclosure_register_successor_binding_mismatch")
        cur = conn.execute("INSERT INTO governed_disclosure_outcome_assessments(request_id,item_id,request_revision,item_revision,proposed_outcome,basis,evidence_json,validation_scope,assessment_scope,limitations,obligations_json,successor_item_id,successor_request_revision,successor_item_revision,assessment_id,authority_fixture_id,authority_fixture_revision,actor,recorded_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (req["id"], item["id"], req["request_revision"], item["item_revision"], outcome, basis_text, _json(evidence), validation, scope, limits, _json(obligations), successor and successor["id"], successor and req["request_revision"], successor and successor["item_revision"], standard["id"], standard["authority_fixture_id"], standard["authority_fixture_revision"], identity, _now()))
        for obligation in obligations:
            if not isinstance(obligation, Mapping):
                raise ValueError("disclosure_register_obligation_invalid")
            description = _required(obligation.get("description"), "disclosure_register_obligation_invalid")
            owner = _required(obligation.get("owner"), "disclosure_register_obligation_invalid", 256)
            status = _required(obligation.get("status"), "disclosure_register_obligation_invalid", 64)
            conn.execute("INSERT INTO governed_disclosure_obligations(request_id,item_id,outcome_assessment_id,description,owner,status,created_at,created_by) VALUES(?,?,?,?,?,?,?,?)", (req["id"], item["id"], cur.lastrowid, description, owner, status, _now(), identity))
        _event(conn, req, item, "outcome_assessment_recorded", identity, _required(reason, "disclosure_register_reason_required"), {"outcome_assessment_id": cur.lastrowid, "proposed_outcome": outcome})
    return _mutation(conn, request_identifier=request_identifier, actor=actor, expected_version=expected_version, idempotency_key=idempotency_key, reason=reason, operation="outcome_assessment_recorded", payload={"item": item_identifier, "outcome": outcome, "successor": successor_item_identifier}, apply=apply)


def link_passive_workflow(conn: sqlite3.Connection, *, request_identifier: Any, item_identifier: Any,
                          workflow_kind: Any, target_identifier: Any, target_revision: Any,
                          relationship_scope: Any, basis: Any, limitations: Any,
                          requirement_identifier: Any = None, issue_identifier: Any = None,
                          relationship_purpose: Any = "context",
                          actor: Any, expected_version: Any, idempotency_key: Any, reason: Any) -> dict[str, Any]:
    kind = str(workflow_kind or "")
    if kind not in {"stage81", "stage81_1", "stage82"}:
        raise ValueError("disclosure_register_workflow_kind_invalid")
    purpose = str(relationship_purpose or "")
    if purpose not in {"context", "required"}:
        raise ValueError("disclosure_register_relationship_purpose_invalid")
    target = _required(target_identifier, "disclosure_register_workflow_target_invalid", 256)
    scope, basis_text, limits = (_required(relationship_scope, "disclosure_register_workflow_scope_required"), _required(basis, "disclosure_register_workflow_basis_required"), _required(limitations, "disclosure_register_workflow_limits_required"))
    try: revision = int(target_revision)
    except (TypeError, ValueError) as exc: raise ValueError("disclosure_register_workflow_target_invalid") from exc
    def apply(req, identity):
        item = _item(conn, req, item_identifier)
        assessment = _current_assessment(conn, req, item)
        if not assessment:
            raise ValueError("disclosure_register_assessment_stale")
        record = {"workflow_kind": kind, "target_identifier": target, "target_revision": revision,
                  "requirement_identifier": requirement_identifier, "issue_identifier": issue_identifier,
                  "relationship_purpose": purpose, "target_binding_json": "{}"}
        # Resolve exact local source state first.  A required relationship stores
        # that chain as an immutable structural binding; context intentionally
        # carries no decision dependency.
        if purpose == "required":
            if kind == "stage81":
                binding = challenge_register._stage81_verified_chain(conn, target)
            elif kind == "stage81_1":
                binding = challenge_register._stage811_requirement_chain(conn, target, requirement_identifier)
            else:
                challenge = challenge_register.get_challenge(conn, target)
                issue = next((i for i in challenge.get("issues", []) if i.get("issue_identifier") == issue_identifier), None)
                if not issue or int(challenge.get("version", -1)) != revision:
                    raise ValueError("disclosure_register_workflow_binding_unavailable")
                binding = {"challenge_identifier": challenge["challenge_identifier"], "challenge_version": challenge["version"],
                           "issue_identifier": issue["issue_identifier"], "issue_version": issue["version"],
                           "subject_identity": challenge["subject_identity"], "issue_state": issue["issue_state"]}
            record["target_binding_json"] = _json(binding)
        else:
            binding = {}
        if _workflow_state(conn, record).get("status") != "current":
            raise ValueError("disclosure_register_workflow_binding_unavailable")
        conn.execute("INSERT INTO governed_disclosure_workflow_links(request_id,item_id,request_revision,item_revision,workflow_kind,target_identifier,target_revision,requirement_identifier,issue_identifier,relationship_purpose,assessment_id,target_binding_json,relationship_scope,basis,limitations,actor,recorded_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (req["id"], item["id"], req["request_revision"], item["item_revision"], kind, target, revision, requirement_identifier, issue_identifier, purpose, assessment["id"], _json(binding), scope, basis_text, limits, identity, _now()))
        _event(conn, req, item, "passive_workflow_linked", identity, _required(reason, "disclosure_register_reason_required"), {"workflow_kind": kind, "target_identifier": target, "purpose": purpose})
    return _mutation(conn, request_identifier=request_identifier, actor=actor, expected_version=expected_version, idempotency_key=idempotency_key, reason=reason, operation="passive_workflow_linked", payload={"item": item_identifier, "workflow": kind, "target": target, "purpose": purpose}, apply=apply)


def record_outcome(conn: sqlite3.Connection, *, request_identifier: Any, item_identifier: Any, outcome: Any, details: Any, actor: Any, expected_version: Any, idempotency_key: Any, reason: Any, required_relationship_ids: Any = None) -> dict[str, Any]:
    state = str(outcome or "")
    if state not in FINAL_OUTCOMES: raise ValueError("disclosure_register_outcome_invalid")
    if not isinstance(details, Mapping): raise ValueError("disclosure_register_outcome_details_invalid")
    relationship_ids = [] if required_relationship_ids is None else required_relationship_ids
    if not isinstance(relationship_ids, list) or len({str(value) for value in relationship_ids}) != len(relationship_ids):
        raise ValueError("disclosure_register_relationship_binding_invalid")
    def apply(req, identity):
        item = _item(conn, req, item_identifier); assessment = _current_assessment(conn, req, item)
        if item["assessment_state"] != "assessment_complete" or item["approval_state"] not in {"not_recorded", "pending"} or item["outcome"] != "none" or not assessment: raise ValueError("disclosure_register_assessment_stale")
        revision = int(conn.execute("SELECT count(*) FROM governed_disclosure_outcomes WHERE item_id=?", (item["id"],)).fetchone()[0]) + 1
        special = _current_outcome_assessment(conn, req, item, state)
        if state in {"withdrawn", "superseded"} and special is None:
            raise ValueError("disclosure_register_outcome_assessment_required")
        links = []
        for value in relationship_ids:
            try: relationship_id = int(value)
            except (TypeError, ValueError) as exc: raise ValueError("disclosure_register_relationship_binding_invalid") from exc
            row = conn.execute("SELECT * FROM governed_disclosure_workflow_links WHERE id=? AND request_id=? AND item_id=? AND relationship_purpose='required'", (relationship_id, req["id"], item["id"])).fetchone()
            if row is None or not _relationship_current(conn, req, item, dict(row), assessment):
                raise ValueError("disclosure_register_relationship_binding_unavailable")
            links.append(dict(row))
        cur = conn.execute("INSERT INTO governed_disclosure_outcomes(request_id,item_id,assessment_id,outcome,outcome_revision,details_json,actor,recorded_at,rule_identity,authority_fixture_id,authority_fixture_revision) VALUES(?,?,?,?,?,?,?,?,?,?,?)", (req["id"], item["id"], assessment["id"], state, revision, _json(dict(details)), identity, _now(), assessment["rule_identity"], assessment["authority_fixture_id"], assessment["authority_fixture_revision"]))
        for link in links:
            conn.execute("INSERT INTO governed_disclosure_outcome_relationship_bindings(request_id,item_id,outcome_id,outcome_revision,relationship_id,purpose,actor,recorded_at) VALUES(?,?,?,?,?,?,?,?)", (req["id"], item["id"], cur.lastrowid, revision, link["id"], "required", identity, _now()))
        if special is not None and state == "superseded":
            successor = _item_by_id(conn, req, int(special["successor_item_id"]))
            conn.execute("INSERT INTO governed_disclosure_relationships(request_id,predecessor_item_id,successor_item_id,predecessor_revision,successor_revision,basis,limitations,actor,recorded_at) VALUES(?,?,?,?,?,?,?,?,?)", (req["id"], item["id"], successor["id"], item["item_revision"], successor["item_revision"], special["basis"], special["limitations"], identity, _now()))
        conn.execute("UPDATE governed_disclosure_items SET outcome=?,approval_state='pending',applicability_state='not_evaluated',version=version+1 WHERE id=?", (state, item["id"]))
        _event(conn, req, item, "outcome_recorded", identity, _required(reason, "disclosure_register_reason_required"), {"outcome_id": cur.lastrowid, "outcome_revision": revision})
    return _mutation(conn, request_identifier=request_identifier, actor=actor, expected_version=expected_version, idempotency_key=idempotency_key, reason=reason, operation="outcome_recorded", payload={"item": item_identifier, "outcome": state, "required_relationship_ids": relationship_ids}, apply=apply)


def approve_outcome(conn: sqlite3.Connection, *, request_identifier: Any, item_identifier: Any, outcome_revision: Any, synthetic_rule_authority: Any, actor: Any, expected_version: Any, idempotency_key: Any, reason: Any) -> dict[str, Any]:
    # A synthetic fixture is explicit and confined to disposable test storage;
    # the authenticated actor merely records its supplied fixture identity.
    authority = _required(synthetic_rule_authority, "disclosure_register_synthetic_authority_required", 256)
    try: revision = int(outcome_revision)
    except (TypeError, ValueError) as exc: raise ValueError("disclosure_register_outcome_revision_invalid") from exc
    def apply(req, identity):
        item = _item(conn, req, item_identifier); assessment = _current_assessment(conn, req, item)
        row = conn.execute("SELECT * FROM governed_disclosure_outcomes WHERE item_id=? AND outcome_revision=? ORDER BY id DESC LIMIT 1", (item["id"], revision)).fetchone()
        if not assessment or not row or item["assessment_state"] != "assessment_complete" or item["approval_state"] != "pending" or item["applicability_state"] != "not_evaluated" or int(row["assessment_id"]) != assessment["id"] or row["outcome"] != item["outcome"] or authority != assessment["authority_identity"] or int(row["authority_fixture_id"] or -1) != int(assessment["authority_fixture_id"]) or int(row["authority_fixture_revision"] or -1) != int(assessment["authority_fixture_revision"]) or not _required_relationships_current(conn, req, item, dict(row), assessment): raise ValueError("disclosure_register_approval_binding_mismatch")
        fixture = _authority_fixture(conn, rule=str(assessment["rule_identity"]), authority=authority, actor=identity)
        if fixture["requires_review"] and not _review_current(conn, outcome_id=int(row["id"]), fixture=fixture):
            raise ValueError("disclosure_register_required_review_unavailable")
        conn.execute("INSERT INTO governed_disclosure_approvals(request_id,item_id,outcome_id,outcome_revision,assessment_id,rule_identity,authority_identity,actor,recorded_at,authority_fixture_id,authority_fixture_revision) VALUES(?,?,?,?,?,?,?,?,?,?,?)", (req["id"], item["id"], row["id"], revision, assessment["id"], assessment["rule_identity"], authority, identity, _now(), fixture["id"], fixture["revision"]))
        conn.execute("UPDATE governed_disclosure_items SET approval_state='approved_current',applicability_state='current',version=version+1 WHERE id=?", (item["id"],))
        _event(conn, req, item, "outcome_approved", identity, _required(reason, "disclosure_register_reason_required"), {"outcome_revision": revision})
    return _mutation(conn, request_identifier=request_identifier, actor=actor, expected_version=expected_version, idempotency_key=idempotency_key, reason=reason, operation="outcome_approved", payload={"item": item_identifier, "outcome_revision": revision, "authority": authority}, apply=apply)


def reconsider(conn: sqlite3.Connection, *, request_identifier: Any, item_identifier: Any, actor: Any, expected_version: Any, idempotency_key: Any, reason: Any) -> dict[str, Any]:
    def apply(req, identity):
        if req["procedural_state"] == "closed":
            raise ValueError("disclosure_register_reopening_required")
        item = _item(conn, req, item_identifier)
        if item["assessment_state"] != "assessment_complete" or item["approval_state"] != "approved_current" or item["applicability_state"] != "current": raise ValueError("disclosure_register_transition_invalid")
        conn.execute("UPDATE governed_disclosure_items SET assessment_state='under_assessment',approval_state='not_recorded',outcome='none',applicability_state='not_evaluated',version=version+1 WHERE id=?", (item["id"],))
        _event(conn, req, item, "voluntary_reconsideration", identity, _required(reason, "disclosure_register_reason_required"), {})
    return _mutation(conn, request_identifier=request_identifier, actor=actor, expected_version=expected_version, idempotency_key=idempotency_key, reason=reason, operation="reconsidered", payload={"item": item_identifier}, apply=apply)


def amend_item(conn: sqlite3.Connection, *, request_identifier: Any, item_identifier: Any, object_version: Any, actor: Any, expected_version: Any, idempotency_key: Any, reason: Any) -> dict[str, Any]:
    version = _required(object_version, "disclosure_register_object_version_required", 256)
    def apply(req, identity):
        item = _item(conn, req, item_identifier)
        if req["procedural_state"] == "closed":
            conn.execute("UPDATE governed_disclosure_requests SET procedural_state='reopened' WHERE id=?", (req["id"],)); _event(conn, req, None, "reopened", identity, _required(reason, "disclosure_register_reason_required"), {"for": "amendment"})
        # Request revision is a consequential shared binding. Conservatively
        # reset every inventory item rather than silently reusing an approval.
        conn.execute("UPDATE governed_disclosure_items SET assessment_state='under_assessment',approval_state='not_recorded',outcome='none',applicability_state='not_evaluated',version=version+1 WHERE request_id=?", (req["id"],))
        conn.execute("UPDATE governed_disclosure_items SET object_version=?,item_revision=item_revision+1 WHERE id=?", (version, item["id"]))
        conn.execute("UPDATE governed_disclosure_requests SET request_revision=request_revision+1 WHERE id=?", (req["id"],))
        _event(conn, req, item, "item_amended", identity, _required(reason, "disclosure_register_reason_required"), {"object_version": version})
    return _mutation(conn, request_identifier=request_identifier, actor=actor, expected_version=expected_version, idempotency_key=idempotency_key, reason=reason, operation="item_amended", payload={"item": item_identifier, "object_version": version}, apply=apply)


def close_request(conn: sqlite3.Connection, *, request_identifier: Any, actor: Any, expected_version: Any, idempotency_key: Any, reason: Any) -> dict[str, Any]:
    def apply(req, identity):
        items = [dict(row) for row in conn.execute("SELECT * FROM governed_disclosure_items WHERE request_id=?", (req["id"],))]
        if not items or any(not _closure_item_eligible(conn, req, i) for i in items): raise ValueError("disclosure_register_closure_incomplete")
        conn.execute("UPDATE governed_disclosure_requests SET procedural_state='closed' WHERE id=?", (req["id"],))
        _event(conn, req, None, "closed", identity, _required(reason, "disclosure_register_reason_required"), {"items": [i["item_identifier"] for i in items]})
    return _mutation(conn, request_identifier=request_identifier, actor=actor, expected_version=expected_version, idempotency_key=idempotency_key, reason=reason, operation="request_closed", payload={}, apply=apply)


def reject_approval(conn: sqlite3.Connection, *, request_identifier: Any, item_identifier: Any, rejection_reason: Any, actor: Any, expected_version: Any, idempotency_key: Any, reason: Any) -> dict[str, Any]:
    rejected = _required(rejection_reason, "disclosure_register_rejection_reason_required")
    def apply(req, identity):
        item = _item(conn, req, item_identifier)
        if item["assessment_state"] != "assessment_complete" or item["approval_state"] != "pending" or item["outcome"] == "none": raise ValueError("disclosure_register_transition_invalid")
        conn.execute("UPDATE governed_disclosure_items SET approval_state='not_approved',applicability_state='not_evaluated',version=version+1 WHERE id=?", (item["id"],))
        _event(conn, req, item, "approval_rejected", identity, _required(reason, "disclosure_register_reason_required"), {"rejection_reason": rejected})
    return _mutation(conn, request_identifier=request_identifier, actor=actor, expected_version=expected_version, idempotency_key=idempotency_key, reason=reason, operation="approval_rejected", payload={"item": item_identifier, "rejection": rejected}, apply=apply)


def reassess(conn: sqlite3.Connection, *, request_identifier: Any, item_identifier: Any, actor: Any, expected_version: Any, idempotency_key: Any, reason: Any) -> dict[str, Any]:
    def apply(req, identity):
        if req["procedural_state"] == "closed":
            raise ValueError("disclosure_register_reopening_required")
        item = _item(conn, req, item_identifier)
        stale_pending = item["approval_state"] == "pending" and _current_assessment(conn, req, item) is None
        if item["assessment_state"] != "assessment_complete" or (item["approval_state"] not in {"not_approved", "stale", "unavailable", "approved_current"} and not stale_pending): raise ValueError("disclosure_register_transition_invalid")
        if item["approval_state"] == "approved_current" and item["applicability_state"] != "current": raise ValueError("disclosure_register_transition_invalid")
        conn.execute("UPDATE governed_disclosure_items SET assessment_state='under_assessment',approval_state='not_recorded',outcome='none',applicability_state='not_evaluated',version=version+1 WHERE id=?", (item["id"],))
        _event(conn, req, item, "reassessment_started", identity, _required(reason, "disclosure_register_reason_required"), {})
    return _mutation(conn, request_identifier=request_identifier, actor=actor, expected_version=expected_version, idempotency_key=idempotency_key, reason=reason, operation="reassessment_started", payload={"item": item_identifier}, apply=apply)


def reopen_request(conn: sqlite3.Connection, *, request_identifier: Any, item_identifiers: Any,
                   actor: Any, expected_version: Any, idempotency_key: Any, reason: Any) -> dict[str, Any]:
    """End active closure and reset explicitly named items in one transaction.

    Earlier closure/outcome/approval records remain immutable history.  The
    caller cannot smuggle reopening into reassessment or reconsideration.
    """
    if not isinstance(item_identifiers, list) or not item_identifiers or len({str(value) for value in item_identifiers}) != len(item_identifiers):
        raise ValueError("disclosure_register_reopen_items_required")
    names = [_required(value, "disclosure_register_item_identifier_invalid", 256) for value in item_identifiers]
    def apply(req, identity):
        if req["procedural_state"] != "closed":
            raise ValueError("disclosure_register_reopening_invalid")
        items = [_item(conn, req, name) for name in names]
        conn.execute("UPDATE governed_disclosure_requests SET procedural_state='reopened' WHERE id=?", (req["id"],))
        for item in items:
            conn.execute("UPDATE governed_disclosure_items SET assessment_state='under_assessment',approval_state='not_recorded',outcome='none',applicability_state='not_evaluated',version=version+1 WHERE id=?", (item["id"],))
        _event(conn, req, None, "reopened", identity, _required(reason, "disclosure_register_reason_required"), {"affected_items": names})
    return _mutation(conn, request_identifier=request_identifier, actor=actor, expected_version=expected_version, idempotency_key=idempotency_key, reason=reason, operation="request_reopened", payload={"items": names}, apply=apply)


def record_applicability_condition(conn: sqlite3.Connection, *, request_identifier: Any, item_identifier: Any, condition: Any, basis: Any, actor: Any, expected_version: Any, idempotency_key: Any, reason: Any) -> dict[str, Any]:
    state, why = str(condition or ""), _required(basis, "disclosure_register_applicability_basis_required")
    def apply(req, identity):
        item = _item(conn, req, item_identifier)
        _mark_noncurrent(conn, req, item, state, why, identity)
        _event(conn, req, item, "applicability_changed", identity, _required(reason, "disclosure_register_reason_required"), {"condition": state, "basis": why})
    return _mutation(conn, request_identifier=request_identifier, actor=actor, expected_version=expected_version, idempotency_key=idempotency_key, reason=reason, operation="applicability_changed", payload={"item": item_identifier, "condition": state}, apply=apply)


def add_obligation(conn: sqlite3.Connection, *, request_identifier: Any, item_identifier: Any, description: Any, owner: Any, status: Any, actor: Any, expected_version: Any, idempotency_key: Any, reason: Any) -> dict[str, Any]:
    # Continuing obligations are part of the immutable withdrawal/supersession
    # assessment.  A free-standing caller summary cannot become authoritative
    # downstream work merely by being recorded here.
    del conn, request_identifier, item_identifier, description, owner, status, actor, expected_version, idempotency_key, reason
    raise ValueError("disclosure_register_obligation_assessment_required")


def link_successor(conn: sqlite3.Connection, *, request_identifier: Any, predecessor_item_identifier: Any, successor_item_identifier: Any, basis: Any, limitations: Any, actor: Any, expected_version: Any, idempotency_key: Any, reason: Any) -> dict[str, Any]:
    # A generic relationship is not the approved supersession route.  The
    # reasoned outcome assessment and superseded outcome operation above bind
    # both items, their revisions, evidence, authority fixture, and outcome.
    del conn, request_identifier, predecessor_item_identifier, successor_item_identifier, basis, limitations, actor, expected_version, idempotency_key, reason
    raise ValueError("disclosure_register_successor_assessment_required")


def render_private_status(request: Mapping[str, Any]) -> str:
    state = request.get("summary", {}).get("state")
    return "Closed — reassessment required" if state == "closed_reassessment_required" else str(state or "recorded")
