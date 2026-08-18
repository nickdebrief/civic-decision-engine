"""Stage 68 human-recorded, source-bound challenge proceedings.

This module preserves a represented appeal or review pathway.  It never
suspends, reverses, validates, or changes the Stage 67 determination targeted
by a challenge.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from api import record_governed_allegations as allegations
from api import record_governed_decision_authorities as authorities
from api import record_governed_determinations as determinations

SCHEMA_VERSION = "stage68.human_governed_challenge_proceeding.v1"
AUTHORING_MODE = "human_recorded"
CHALLENGE_FORMS = {"appeal", "internal_review", "administrative_review", "statutory_review", "judicial_review_application", "reconsideration_request"}
APPLICANT_KINDS = {"natural_person", "organisation", "institution", "public_body", "representative", "other_identified_source"}
BINDING_ROLES = {"initiation_source", "filing_source", "acknowledgement_source", "grounds_source", "authority_source", "procedural_event_source", "outcome_source", "withdrawal_source", "contextual_source", "contrary_source"}
SOURCE_TYPES = {"published_document", "canonical_record", "record_document_association", "accepted_pattern_observation"}
EVENT_TYPES = {"filing_recorded", "acknowledgement_recorded", "permission_requested", "permission_granted_as_recorded", "permission_refused_as_recorded", "admissibility_accepted_as_recorded", "inadmissibility_recorded", "submissions_invited", "hearing_scheduled", "review_commenced_as_recorded", "withdrawal_recorded", "discontinuance_recorded", "outcome_recorded", "closure_recorded"}
EVENT_SOURCE_ROLES = {"procedural_event_source", "acknowledgement_source", "outcome_source", "withdrawal_source"}
OUTCOME_TYPES = {"allowed_as_recorded", "dismissed_as_recorded", "varied_as_recorded", "remitted_as_recorded", "set_aside_as_recorded", "withdrawn_as_recorded", "discontinued_as_recorded", "other_outcome_as_recorded"}
REVIEW_DISPOSITIONS = {"accepted_as_governed_challenge_record", "requires_procedural_correction", "not_accepted_as_governed_challenge_record"}
STATUSES = {"initiated", "acknowledged", "permission_pending", "permission_event_recorded", "admissibility_event_recorded", "under_review_as_recorded", "withdrawn_as_recorded", "discontinued_as_recorded", "outcome_recorded", "closed_as_recorded", "superseded"}
TERMINAL_EVENTS = {"withdrawal_recorded", "discontinuance_recorded", "outcome_recorded", "closure_recorded"}


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


def _date(value: Any) -> datetime.date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        if "T" in text:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
        return datetime.strptime(text, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        raise ValueError("governed_challenge_date_invalid") from None


def _declaration(value: Any, error: str, boundary: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or value.get("acknowledged") is not True:
        raise ValueError(error)
    return {"human_recorded": True, "acknowledged": True, "boundary": boundary}


def _qualification(value: Any, limitations: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("governed_challenge_qualification_contract_required")
    expected = {"epistemic_label": "challenge_proceeding", "source_basis_present": True, "target_determination_present": True, "not_suspension": True, "not_reversal": True, "not_legal_effect": True}
    if any(value.get(k) != v for k, v in expected.items()):
        raise ValueError("governed_challenge_qualification_contract_incomplete")
    result = dict(expected)
    result["limitations"] = _required(limitations, "governed_challenge_limitations_required")
    return result


def ensure_challenge_tables(conn: sqlite3.Connection) -> None:
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS record_governed_challenge_proceedings (
      id INTEGER PRIMARY KEY AUTOINCREMENT, idempotency_key TEXT NOT NULL UNIQUE,
      schema_version TEXT NOT NULL, authoring_mode TEXT NOT NULL, challenge_form TEXT NOT NULL,
      title_label TEXT NOT NULL, applicant_label TEXT NOT NULL, applicant_kind TEXT NOT NULL,
      applicant_capacity TEXT, reviewing_forum_label TEXT NOT NULL, grounds TEXT NOT NULL,
      filing_date_or_period TEXT, recorded_date TEXT, affected_subject_or_proceeding TEXT NOT NULL,
      procedural_status_at_creation TEXT NOT NULL, rationale TEXT NOT NULL, qualification TEXT NOT NULL,
      limitations TEXT NOT NULL, qualification_contract_json TEXT NOT NULL,
      recorder_declaration_json TEXT NOT NULL, status TEXT NOT NULL, created_by TEXT NOT NULL,
      created_by_role TEXT NOT NULL, created_at TEXT NOT NULL, request_payload_json TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS record_governed_challenge_determination_links (
      id INTEGER PRIMARY KEY AUTOINCREMENT, challenge_id INTEGER NOT NULL, determination_id INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS record_governed_challenge_authority_links (
      id INTEGER PRIMARY KEY AUTOINCREMENT, challenge_id INTEGER NOT NULL, authority_id INTEGER NOT NULL, mandate_id INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS record_governed_challenge_bindings (
      id INTEGER PRIMARY KEY AUTOINCREMENT, challenge_id INTEGER NOT NULL, source_type TEXT NOT NULL, source_id TEXT NOT NULL,
      binding_role TEXT NOT NULL, source_version TEXT, source_timestamp TEXT,
      UNIQUE(challenge_id, source_type, source_id, binding_role)
    );
    CREATE TABLE IF NOT EXISTS record_governed_challenge_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT, challenge_id INTEGER NOT NULL, event_type TEXT NOT NULL,
      event_description TEXT NOT NULL, event_date_or_period TEXT, actor TEXT NOT NULL, actor_role TEXT NOT NULL,
      rationale TEXT NOT NULL, source_type TEXT NOT NULL, source_id TEXT NOT NULL, boundary_declaration_json TEXT NOT NULL,
      occurred_at TEXT NOT NULL, idempotency_key TEXT NOT NULL UNIQUE, request_payload_json TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS record_governed_challenge_reviews (
      id INTEGER PRIMARY KEY AUTOINCREMENT, challenge_id INTEGER NOT NULL, disposition TEXT NOT NULL,
      reviewed_by TEXT NOT NULL, reviewed_by_role TEXT NOT NULL, rationale TEXT NOT NULL,
      boundary_declaration_json TEXT NOT NULL, is_self_review INTEGER NOT NULL, reviewed_at TEXT NOT NULL,
      idempotency_key TEXT NOT NULL UNIQUE, request_payload_json TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS record_governed_challenge_supersessions (
      id INTEGER PRIMARY KEY AUTOINCREMENT, challenge_id INTEGER NOT NULL, replacement_challenge_id INTEGER NOT NULL,
      rationale TEXT NOT NULL, actor TEXT NOT NULL, actor_role TEXT NOT NULL, occurred_at TEXT NOT NULL,
      idempotency_key TEXT NOT NULL UNIQUE, request_payload_json TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS record_governed_challenge_outcomes (
      id INTEGER PRIMARY KEY AUTOINCREMENT, challenge_id INTEGER NOT NULL, outcome_type TEXT NOT NULL,
      outcome_text TEXT NOT NULL, outcome_date_or_period TEXT, source_type TEXT NOT NULL, source_id TEXT NOT NULL,
      outcome_determination_id INTEGER, actor TEXT NOT NULL, actor_role TEXT NOT NULL, rationale TEXT NOT NULL,
      boundary_declaration_json TEXT NOT NULL, recorded_at TEXT NOT NULL, idempotency_key TEXT NOT NULL UNIQUE,
      request_payload_json TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_stage68_challenge_status ON record_governed_challenge_proceedings(status, created_at);
    CREATE INDEX IF NOT EXISTS idx_stage68_challenge_bindings ON record_governed_challenge_bindings(source_type, source_id, challenge_id);
    """)


def _key(prefix: str, payload: Mapping[str, Any]) -> str:
    return prefix + hashlib.sha256(_json(payload).encode()).hexdigest()


def _target(conn: sqlite3.Connection, determination_id: int | str) -> dict[str, Any]:
    try:
        return determinations.get_determination(conn, int(determination_id))
    except (ValueError, TypeError):
        raise ValueError("governed_challenge_target_determination_not_found") from None


def _authority_pair(conn: sqlite3.Connection, authority_id: int | str, mandate_id: int | str, represented_date: str | None) -> tuple[dict[str, Any], dict[str, Any]]:
    authority = authorities.get_authority(conn, int(authority_id))
    mandate = authorities.get_mandate(conn, int(mandate_id))
    if int(mandate["authority_id"]) != int(authority["id"]):
        raise ValueError("governed_challenge_authority_mandate_mismatch")
    date = _date(represented_date)
    for record in (authority, mandate):
        status = record.get("status")
        if status == "accepted_as_source_backed_authority_record":
            continue
        if status not in {"ceased", "superseded"}:
            raise ValueError("governed_challenge_authority_mandate_not_eligible")
        events = [*record.get("cessations", []), *record.get("supersessions", [])]
        if date is None:
            raise ValueError("governed_challenge_temporal_qualification_required")
        for event in events:
            event_date = _date(event.get("cessation_date_or_period") or event.get("occurred_at"))
            if event_date is None or event_date <= date:
                raise ValueError("governed_challenge_authority_mandate_not_eligible")
    return authority, mandate


def _bindings(conn: sqlite3.Connection, value: Any, *, event: bool = False) -> list[dict[str, Any]]:
    if not isinstance(value, (list, tuple)) or not value:
        raise ValueError("governed_challenge_binding_required")
    allowed = EVENT_SOURCE_ROLES if event else BINDING_ROLES
    result = []
    for item in value:
        if not isinstance(item, Mapping) or set(item) - {"source_type", "source_id", "binding_role", "source_version", "source_timestamp"}:
            raise ValueError("governed_challenge_binding_invalid")
        source_type = _required(item.get("source_type"), "governed_challenge_source_type_required")
        source_id = _required(item.get("source_id"), "governed_challenge_source_id_required")
        role = _required(item.get("binding_role"), "governed_challenge_binding_role_required")
        if source_type not in SOURCE_TYPES or role not in allowed:
            raise ValueError("governed_challenge_binding_invalid")
        result.append({"source_type": source_type, "source_id": source_id, "binding_role": role, "source_version": item.get("source_version"), "source_timestamp": item.get("source_timestamp")})
    result.sort(key=lambda x: (x["source_type"], x["source_id"], x["binding_role"]))
    if len({(x["source_type"], x["source_id"], x["binding_role"]) for x in result}) != len(result):
        raise ValueError("governed_challenge_duplicate_binding")
    if not event and not any(x["binding_role"] in {"initiation_source", "filing_source"} for x in result):
        raise ValueError("governed_challenge_initiation_source_required")
    if event and len(result) != 1:
        raise ValueError("governed_challenge_event_source_count_invalid")
    normalized = []
    for item in result:
        normalized.append(allegations._source_binding(conn, item))
    return normalized


def _status(conn: sqlite3.Connection, challenge_id: int, base: str) -> str:
    if conn.execute("SELECT 1 FROM record_governed_challenge_supersessions WHERE challenge_id=?", (challenge_id,)).fetchone():
        return "superseded"
    events = [str(row[0]) for row in conn.execute("SELECT event_type FROM record_governed_challenge_events WHERE challenge_id=? ORDER BY id", (challenge_id,)).fetchall()]
    if "closure_recorded" in events: return "closed_as_recorded"
    if "outcome_recorded" in events or conn.execute("SELECT 1 FROM record_governed_challenge_outcomes WHERE challenge_id=?", (challenge_id,)).fetchone(): return "outcome_recorded"
    if "discontinuance_recorded" in events: return "discontinued_as_recorded"
    if "withdrawal_recorded" in events: return "withdrawn_as_recorded"
    if "review_commenced_as_recorded" in events or "submissions_invited" in events or "hearing_scheduled" in events: return "under_review_as_recorded"
    if "admissibility_accepted_as_recorded" in events or "inadmissibility_recorded" in events: return "admissibility_event_recorded"
    if any(x in events for x in {"permission_granted_as_recorded", "permission_refused_as_recorded"}): return "permission_event_recorded"
    if "permission_requested" in events: return "permission_pending"
    if "acknowledgement_recorded" in events: return "acknowledged"
    row = conn.execute("SELECT disposition FROM record_governed_challenge_reviews WHERE challenge_id=? ORDER BY id DESC LIMIT 1", (challenge_id,)).fetchone()
    return str(row[0]) if row else base


def get_challenge(conn: sqlite3.Connection, challenge_id: int | str) -> dict[str, Any]:
    if not _table_exists(conn, "record_governed_challenge_proceedings"):
        raise ValueError("governed_challenge_table_absent")
    row = conn.execute("SELECT * FROM record_governed_challenge_proceedings WHERE id=?", (int(challenge_id),)).fetchone()
    if row is None: raise ValueError("governed_challenge_not_found")
    result = dict(row)
    for field in ("qualification_contract_json", "recorder_declaration_json", "request_payload_json"):
        result[field.removesuffix("_json")] = json.loads(result.pop(field))
    result["status"] = _status(conn, int(challenge_id), result["status"])
    result["target_determination"] = dict(conn.execute("SELECT * FROM record_governed_challenge_determination_links WHERE challenge_id=?", (int(challenge_id),)).fetchone())
    result["reviewing_authority"] = dict(conn.execute("SELECT * FROM record_governed_challenge_authority_links WHERE challenge_id=?", (int(challenge_id),)).fetchone())
    result["bindings"] = [dict(x) for x in conn.execute("SELECT * FROM record_governed_challenge_bindings WHERE challenge_id=? ORDER BY id", (int(challenge_id),)).fetchall()]
    result["events"] = [dict(x) for x in conn.execute("SELECT * FROM record_governed_challenge_events WHERE challenge_id=? ORDER BY id", (int(challenge_id),)).fetchall()]
    result["reviews"] = [dict(x) for x in conn.execute("SELECT * FROM record_governed_challenge_reviews WHERE challenge_id=? ORDER BY id", (int(challenge_id),)).fetchall()]
    result["supersessions"] = [dict(x) for x in conn.execute("SELECT * FROM record_governed_challenge_supersessions WHERE challenge_id=? ORDER BY id", (int(challenge_id),)).fetchall()]
    result["outcomes"] = [dict(x) for x in conn.execute("SELECT * FROM record_governed_challenge_outcomes WHERE challenge_id=? ORDER BY id", (int(challenge_id),)).fetchall()]
    return result


def list_challenges(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    if not _table_exists(conn, "record_governed_challenge_proceedings"): return []
    return [get_challenge(conn, row[0]) for row in conn.execute("SELECT id FROM record_governed_challenge_proceedings ORDER BY created_at,id").fetchall()]


def read_challenge_diagnostic(challenge_id: int | str | None = None, *, db_path: str | Path) -> dict[str, Any]:
    path = Path(db_path)
    if not path.is_file(): return {"status": "database_unavailable", "challenges": []}
    try:
        conn = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True); conn.row_factory = sqlite3.Row
    except sqlite3.Error: return {"status": "database_unavailable", "challenges": []}
    try:
        if not _table_exists(conn, "record_governed_challenge_proceedings"):
            return {"status": "ok", "challenges": [], "challenge_table_present": False}
        if challenge_id is None: return {"status": "ok", "challenges": list_challenges(conn), "challenge_table_present": True}
        try: return {"status": "ok", "challenges": [get_challenge(conn, challenge_id)], "challenge_table_present": True}
        except ValueError: return {"status": "challenge_not_found", "challenges": [], "challenge_table_present": True}
    finally: conn.close()


def create_challenge(conn: sqlite3.Connection, *, challenge_form: str, title_label: str, target_determination_id: int | str, applicant_label: str, applicant_kind: str, applicant_capacity: str | None, reviewing_forum_label: str, reviewing_authority_id: int | str, reviewing_mandate_id: int | str, grounds: str, filing_date_or_period: str | None, recorded_date: str | None, affected_subject_or_proceeding: str, procedural_status_at_creation: str, rationale: str, limitations: str, qualification_contract: Mapping[str, Any], recorder_declaration: Mapping[str, Any], bindings: Any, actor: str, actor_role: str, idempotency_key: str | None = None, created_at: str | None = None, document_root: Path | None = None, _commit: bool = True) -> dict[str, Any]:
    form = _required(challenge_form, "governed_challenge_form_required").lower()
    if form not in CHALLENGE_FORMS: raise ValueError("governed_challenge_form_invalid")
    kind = _required(applicant_kind, "governed_challenge_applicant_kind_required").lower()
    if kind not in APPLICANT_KINDS: raise ValueError("governed_challenge_applicant_kind_invalid")
    target = _target(conn, target_determination_id)
    authority, mandate = _authority_pair(conn, reviewing_authority_id, reviewing_mandate_id, filing_date_or_period)
    if filing_date_or_period: _date(filing_date_or_period)
    if recorded_date: _date(recorded_date)
    normalized = _bindings(conn, bindings, event=False)
    qualification = _qualification(qualification_contract, limitations)
    recorder = _declaration(recorder_declaration, "governed_challenge_recorder_declaration_required", "challenge_not_reversal")
    payload = {"challenge_form": form, "title_label": _required(title_label, "governed_challenge_title_required"), "target_determination_id": int(target["id"]), "applicant_label": _required(applicant_label, "governed_challenge_applicant_required"), "applicant_kind": kind, "applicant_capacity": applicant_capacity, "reviewing_forum_label": _required(reviewing_forum_label, "governed_challenge_forum_required"), "reviewing_authority_id": int(authority["id"]), "reviewing_mandate_id": int(mandate["id"]), "grounds": _required(grounds, "governed_challenge_grounds_required"), "filing_date_or_period": filing_date_or_period, "recorded_date": recorded_date, "affected_subject_or_proceeding": _required(affected_subject_or_proceeding, "governed_challenge_subject_required"), "procedural_status_at_creation": _required(procedural_status_at_creation, "governed_challenge_procedural_status_required"), "rationale": _required(rationale, "governed_challenge_rationale_required"), "qualification": qualification, "recorder_declaration": recorder, "bindings": normalized}
    key = str(idempotency_key or "").strip() or _key("stage68-create:", payload); ensure_challenge_tables(conn); payload_json = _json(payload)
    existing = conn.execute("SELECT id,request_payload_json FROM record_governed_challenge_proceedings WHERE idempotency_key=?", (key,)).fetchone()
    if existing is not None:
        if str(existing["request_payload_json"]) != payload_json: raise ValueError("governed_challenge_idempotency_conflict")
        return get_challenge(conn, existing["id"])
    try:
        cur = conn.execute("INSERT INTO record_governed_challenge_proceedings (idempotency_key,schema_version,authoring_mode,challenge_form,title_label,applicant_label,applicant_kind,applicant_capacity,reviewing_forum_label,grounds,filing_date_or_period,recorded_date,affected_subject_or_proceeding,procedural_status_at_creation,rationale,qualification,limitations,qualification_contract_json,recorder_declaration_json,status,created_by,created_by_role,created_at,request_payload_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (key, SCHEMA_VERSION, AUTHORING_MODE, form, payload["title_label"], payload["applicant_label"], kind, applicant_capacity, payload["reviewing_forum_label"], payload["grounds"], filing_date_or_period, recorded_date, payload["affected_subject_or_proceeding"], payload["procedural_status_at_creation"], payload["rationale"], "Source-bound challenge proceeding", limitations, _json(qualification), _json(recorder), "initiated", _required(actor, "governed_challenge_recorder_required"), _required(actor_role, "governed_challenge_recorder_role_required"), str(created_at or utc_now()), payload_json))
        challenge_id = int(cur.lastrowid)
        conn.execute("INSERT INTO record_governed_challenge_determination_links (challenge_id,determination_id) VALUES (?,?)", (challenge_id, int(target["id"])))
        conn.execute("INSERT INTO record_governed_challenge_authority_links (challenge_id,authority_id,mandate_id) VALUES (?,?,?)", (challenge_id, int(authority["id"]), int(mandate["id"])))
        conn.executemany("INSERT INTO record_governed_challenge_bindings (challenge_id,source_type,source_id,binding_role,source_version,source_timestamp) VALUES (?,?,?,?,?,?)", [(challenge_id, x["source_type"], x["source_id"], x["binding_role"], x.get("source_version"), x.get("source_timestamp")) for x in normalized])
        if _commit: conn.commit()
    except Exception:
        conn.rollback(); raise
    return get_challenge(conn, challenge_id)


def _event(conn: sqlite3.Connection, challenge_id: int, event_type: str, description: str, event_date_or_period: str | None, rationale: str, bindings: Any, actor: str, actor_role: str, boundary_declaration: Mapping[str, Any], idempotency_key: str | None, _commit: bool) -> dict[str, Any]:
    challenge = get_challenge(conn, challenge_id)
    if event_type not in EVENT_TYPES: raise ValueError("governed_challenge_event_type_invalid")
    if event_date_or_period: _date(event_date_or_period)
    normalized = _bindings(conn, bindings, event=True)
    if normalized[0]["binding_role"] not in ({"outcome_source"} if event_type == "outcome_recorded" else {"withdrawal_source"} if event_type == "withdrawal_recorded" else EVENT_SOURCE_ROLES): raise ValueError("governed_challenge_event_source_role_invalid")
    declaration = _declaration(boundary_declaration, "governed_challenge_event_declaration_required", "event_not_legal_effect")
    payload = {"challenge_id": int(challenge_id), "event_type": event_type, "event_description": _required(description, "governed_challenge_event_description_required"), "event_date_or_period": event_date_or_period, "rationale": _required(rationale, "governed_challenge_event_rationale_required"), "source": normalized[0], "boundary_declaration": declaration}
    key = str(idempotency_key or "").strip() or _key("stage68-event:", payload); ensure_challenge_tables(conn); payload_json = _json(payload)
    existing = conn.execute("SELECT * FROM record_governed_challenge_events WHERE idempotency_key=?", (key,)).fetchone()
    if existing is not None:
        if str(existing["request_payload_json"]) != payload_json: raise ValueError("governed_challenge_event_idempotency_conflict")
        return challenge
    if challenge["status"] == "superseded" or challenge["status"] in {"withdrawn_as_recorded", "discontinued_as_recorded", "outcome_recorded", "closed_as_recorded"}:
        raise ValueError("governed_challenge_terminal_state")
    try:
        conn.execute("INSERT INTO record_governed_challenge_events (challenge_id,event_type,event_description,event_date_or_period,actor,actor_role,rationale,source_type,source_id,boundary_declaration_json,occurred_at,idempotency_key,request_payload_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (int(challenge_id), event_type, payload["event_description"], event_date_or_period, _required(actor,"governed_challenge_event_actor_required"), _required(actor_role,"governed_challenge_event_actor_role_required"), payload["rationale"], normalized[0]["source_type"], normalized[0]["source_id"], _json(declaration), utc_now(), key, payload_json))
        if _commit: conn.commit()
    except Exception:
        conn.rollback(); raise
    return get_challenge(conn, challenge_id)


def record_event(conn: sqlite3.Connection, **kwargs: Any) -> dict[str, Any]:
    return _event(conn, _int(kwargs.pop("challenge_id")), kwargs.pop("event_type"), kwargs.pop("event_description"), kwargs.pop("event_date_or_period", None), kwargs.pop("rationale"), kwargs.pop("event_bindings"), kwargs.pop("actor"), kwargs.pop("actor_role"), kwargs.pop("boundary_declaration"), kwargs.pop("idempotency_key", None), kwargs.pop("_commit", True))


def _int(value: Any) -> int:
    try: return int(value)
    except (ValueError, TypeError): raise ValueError("governed_challenge_id_invalid") from None


def review_challenge(conn: sqlite3.Connection, *, challenge_id: int | str, disposition: str, rationale: str, boundary_declaration: Mapping[str, Any], actor: str, actor_role: str, idempotency_key: str | None = None, _commit: bool = True) -> dict[str, Any]:
    challenge = get_challenge(conn, _int(challenge_id)); value = _required(disposition, "governed_challenge_review_disposition_required").lower()
    if value not in REVIEW_DISPOSITIONS: raise ValueError("governed_challenge_review_disposition_invalid")
    declaration = _declaration(boundary_declaration, "governed_challenge_review_declaration_required", "review_not_reversal")
    payload = {"challenge_id": int(challenge_id), "disposition": value, "rationale": _required(rationale, "governed_challenge_review_rationale_required"), "boundary_declaration": declaration, "is_self_review": _required(actor,"governed_challenge_reviewer_required") == str(challenge["created_by"])}
    key = str(idempotency_key or "").strip() or _key("stage68-review:", payload); ensure_challenge_tables(conn); payload_json = _json(payload)
    existing = conn.execute("SELECT * FROM record_governed_challenge_reviews WHERE idempotency_key=?", (key,)).fetchone()
    if existing is not None:
        if str(existing["request_payload_json"]) != payload_json: raise ValueError("governed_challenge_review_idempotency_conflict")
        return challenge
    try:
        conn.execute("INSERT INTO record_governed_challenge_reviews (challenge_id,disposition,reviewed_by,reviewed_by_role,rationale,boundary_declaration_json,is_self_review,reviewed_at,idempotency_key,request_payload_json) VALUES (?,?,?,?,?,?,?,?,?,?)", (int(challenge_id), value, _required(actor,"governed_challenge_reviewer_required"), _required(actor_role,"governed_challenge_reviewer_role_required"), payload["rationale"], _json(declaration), int(payload["is_self_review"]), utc_now(), key, payload_json))
        if _commit: conn.commit()
    except Exception:
        conn.rollback(); raise
    return get_challenge(conn, challenge_id)


def supersede_challenge(conn: sqlite3.Connection, *, challenge_id: int | str, replacement_challenge_id: int | str, rationale: str, actor: str, actor_role: str, idempotency_key: str | None = None, _commit: bool = True) -> dict[str, Any]:
    challenge = get_challenge(conn, _int(challenge_id)); replacement = get_challenge(conn, _int(replacement_challenge_id))
    if int(challenge_id) == int(replacement_challenge_id): raise ValueError("governed_challenge_supersession_self_reference")
    if int(challenge["target_determination"]["determination_id"]) != int(replacement["target_determination"]["determination_id"]): raise ValueError("governed_challenge_supersession_target_mismatch")
    seen = {int(challenge_id)}; cursor = int(replacement_challenge_id)
    while True:
        if cursor in seen: raise ValueError("governed_challenge_supersession_cycle_rejected")
        seen.add(cursor)
        row = conn.execute("SELECT replacement_challenge_id FROM record_governed_challenge_supersessions WHERE challenge_id=?", (cursor,)).fetchone()
        if row is None: break
        cursor = int(row[0])
    payload = {"challenge_id": int(challenge_id), "replacement_challenge_id": int(replacement_challenge_id), "rationale": _required(rationale,"governed_challenge_supersession_rationale_required")}
    key = str(idempotency_key or "").strip() or _key("stage68-supersession:", payload); ensure_challenge_tables(conn); payload_json = _json(payload)
    existing = conn.execute("SELECT * FROM record_governed_challenge_supersessions WHERE idempotency_key=?", (key,)).fetchone()
    if existing is not None:
        if str(existing["request_payload_json"]) != payload_json: raise ValueError("governed_challenge_supersession_idempotency_conflict")
        return challenge
    if challenge["status"] in {"superseded", "withdrawn_as_recorded", "discontinued_as_recorded", "outcome_recorded", "closed_as_recorded"}: raise ValueError("governed_challenge_terminal_state")
    try:
        conn.execute("INSERT INTO record_governed_challenge_supersessions (challenge_id,replacement_challenge_id,rationale,actor,actor_role,occurred_at,idempotency_key,request_payload_json) VALUES (?,?,?,?,?,?,?,?)", (int(challenge_id), int(replacement_challenge_id), payload["rationale"], _required(actor,"governed_challenge_actor_required"), _required(actor_role,"governed_challenge_actor_role_required"), utc_now(), key, payload_json))
        if _commit: conn.commit()
    except Exception: conn.rollback(); raise
    return get_challenge(conn, challenge_id)


def record_outcome(conn: sqlite3.Connection, *, challenge_id: int | str, outcome_type: str, outcome_text: str, outcome_date_or_period: str | None, outcome_source: Mapping[str, Any], outcome_determination_id: int | None, rationale: str, boundary_declaration: Mapping[str, Any], actor: str, actor_role: str, idempotency_key: str | None = None, _commit: bool = True) -> dict[str, Any]:
    challenge = get_challenge(conn, _int(challenge_id)); value = _required(outcome_type,"governed_challenge_outcome_type_required").lower()
    if value not in OUTCOME_TYPES: raise ValueError("governed_challenge_outcome_type_invalid")
    normalized = _bindings(conn, [dict(outcome_source, binding_role="outcome_source")], event=True)[0]
    if outcome_date_or_period: _date(outcome_date_or_period)
    if outcome_determination_id is not None:
        outcome_determination = _target(conn, outcome_determination_id)
        target_id = int(challenge["target_determination"]["determination_id"])
        if int(outcome_determination["id"]) == target_id:
            raise ValueError("governed_challenge_outcome_determination_must_be_distinct")
        represented = challenge["reviewing_authority"]
        outcome_authority = outcome_determination.get("authority_mandate") or {}
        if (int(outcome_authority.get("authority_id", -1)), int(outcome_authority.get("mandate_id", -1))) != (int(represented["authority_id"]), int(represented["mandate_id"])):
            raise ValueError("governed_challenge_outcome_authority_mandate_mismatch")
    declaration = _declaration(boundary_declaration, "governed_challenge_outcome_declaration_required", "outcome_not_determination")
    payload = {"challenge_id": int(challenge_id), "outcome_type": value, "outcome_text": _required(outcome_text,"governed_challenge_outcome_text_required"), "outcome_date_or_period": outcome_date_or_period, "outcome_source": normalized, "outcome_determination_id": outcome_determination_id, "rationale": _required(rationale,"governed_challenge_outcome_rationale_required"), "boundary_declaration": declaration}
    key = str(idempotency_key or "").strip() or _key("stage68-outcome:", payload); ensure_challenge_tables(conn); payload_json = _json(payload)
    existing = conn.execute("SELECT * FROM record_governed_challenge_outcomes WHERE idempotency_key=?", (key,)).fetchone()
    if existing is not None:
        if str(existing["request_payload_json"]) != payload_json: raise ValueError("governed_challenge_outcome_idempotency_conflict")
        return challenge
    if challenge["status"] in {"superseded", "withdrawn_as_recorded", "discontinued_as_recorded", "outcome_recorded", "closed_as_recorded"}: raise ValueError("governed_challenge_terminal_state")
    try:
        conn.execute("INSERT INTO record_governed_challenge_outcomes (challenge_id,outcome_type,outcome_text,outcome_date_or_period,source_type,source_id,outcome_determination_id,actor,actor_role,rationale,boundary_declaration_json,recorded_at,idempotency_key,request_payload_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (int(challenge_id), value, payload["outcome_text"], outcome_date_or_period, normalized["source_type"], normalized["source_id"], outcome_determination_id, _required(actor,"governed_challenge_actor_required"), _required(actor_role,"governed_challenge_actor_role_required"), payload["rationale"], _json(declaration), utc_now(), key, payload_json))
        if _commit: conn.commit()
    except Exception: conn.rollback(); raise
    return get_challenge(conn, challenge_id)
