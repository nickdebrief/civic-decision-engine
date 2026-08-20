"""Stage 73 governed publication snapshots for Stage 67 determinations.

This module owns publication identity and immutable public content. It never
mutates a determination or decides authority, reasons, challenge, or effect.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Mapping

from api import record_governed_determinations as determinations

SCHEMA_VERSION = "stage73.governed_determination_publication.v1"
REPRESENTATION_MODES = {"verbatim", "faithful_paraphrase", "approved_summary", "redacted_representation"}
ELIGIBILITY_STATUSES = {"not_assessed", "eligible_for_review", "not_eligible", "eligibility_deferred"}
PRIVACY_STATUSES = {"not_reviewed", "review_required", "cleared_for_publication", "not_cleared"}
REDACTION_STATUSES = {"not_reviewed", "review_required", "redactions_required", "cleared_for_publication", "not_cleared"}
AUTHORITY_STATUSES = {"not_inspected", "recorded_and_current", "recorded_with_qualification", "disputed", "ceased_or_superseded", "inspection_inconclusive"}
REASONS_STATUSES = {"reasons_included", "reasons_referenced_not_reproduced", "reasons_not_provided", "reasons_status_disputed", "reasons_status_unknown_or_incomplete", "reasons_abridged_or_redacted"}
CHALLENGE_STATUSES = {"no_linked_challenge_shown_in_snapshot", "challenge_pending", "permission_or_admissibility_pending", "review_in_progress", "challenge_determined", "challenge_withdrawn", "challenge_status_disputed", "challenge_information_withheld"}
EFFECT_STATUSES = {"effect_not_assessed", "represented_as_current", "represented_as_suspended", "represented_as_ceased", "represented_as_superseded", "effect_disputed", "effect_uncertain"}
NO_LINKED_CHALLENGE_TEXT = "No linked challenge is represented in this publication snapshot."
LIFECYCLE = {"draft", "eligibility_reviewed", "privacy_reviewed", "redaction_reviewed", "authority_and_mandate_inspected", "awaiting_approval", "approved_for_publication", "published", "withdrawn_from_publication", "superseded"}
REVIEW_TYPES = {"eligibility", "privacy", "redaction", "authority", "mandate", "publication_context", "publication_approval"}
EVENT_TYPES = {"created", "eligibility_reviewed", "privacy_reviewed", "redaction_reviewed", "authority_inspected", "mandate_inspected", "publication_context_recorded", "approved_for_publication", "published", "withdrawn_from_publication", "superseded"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _required(value: Any, error: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise ValueError(error)
    return result


def _validate_challenge_warning(status: str, text: Any) -> str:
    value = _required(text, "governed_publication_challenge_warning_text_required")
    lowered = value.casefold()
    if status == "no_linked_challenge_shown_in_snapshot" and value != NO_LINKED_CHALLENGE_TEXT:
        raise ValueError("governed_publication_challenge_warning_text_incompatible")
    incompatible = {
        "challenge_determined": ("no linked challenge is represented", "pending", "withdrawn"),
        "challenge_pending": ("no linked challenge is represented", "determined", "withdrawn"),
        "permission_or_admissibility_pending": ("no linked challenge is represented", "determined", "withdrawn"),
        "review_in_progress": ("no linked challenge is represented", "determined", "withdrawn"),
        "challenge_withdrawn": ("no linked challenge is represented", "pending", "determined"),
    }
    if any(marker in lowered for marker in incompatible.get(status, ())):
        raise ValueError("governed_publication_challenge_warning_text_incompatible")
    return value


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def _unknown_fields(value: Mapping[str, Any], allowed: set[str], error: str) -> None:
    if not isinstance(value, Mapping) or set(value) - allowed:
        raise ValueError(error)


def _declaration(value: Any, error: str, boundary: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or value.get("acknowledged") is not True:
        raise ValueError(error)
    _unknown_fields(value, {"acknowledged", "human_recorded", "boundary"}, error)
    return {"acknowledged": True, "human_recorded": True, "boundary": boundary}


def _review_representation(review_type: str, value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or value.get("acknowledged") is not True:
        raise ValueError("governed_publication_review_declaration_required")
    allowed = {"acknowledged", "human_recorded", "boundary"}
    if review_type in {"authority", "mandate"}:
        allowed.add("representation")
    if review_type == "publication_context":
        allowed.update({"reasons_status", "challenge_warning_status", "challenge_warning_text", "current_effect_status", "current_effect_rationale", "effect_as_of", "supersession_representation", "limitations", "redaction_notice"})
    if review_type == "publication_approval":
        allowed.add("approved")
    _unknown_fields(value, allowed, "governed_publication_review_representation_invalid")
    return dict(value)


def _supporting_sources(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise ValueError("governed_publication_supporting_sources_invalid")
    allowed = {"source_type", "source_id", "binding_role", "source_version", "source_timestamp"}
    result = []
    for source in value:
        if not isinstance(source, Mapping) or set(source) - allowed:
            raise ValueError("governed_publication_supporting_source_invalid")
        if not all(str(source.get(key) or "").strip() for key in ("source_type", "source_id", "binding_role")):
            raise ValueError("governed_publication_supporting_source_invalid")
        result.append({key: source.get(key) for key in sorted(allowed) if key in source})
    result.sort(key=lambda item: (item["source_type"], item["source_id"], item["binding_role"]))
    if len({(x["source_type"], x["source_id"], x["binding_role"]) for x in result}) != len(result):
        raise ValueError("governed_publication_duplicate_supporting_source")
    return result


def _determination(conn: sqlite3.Connection, value: int | str) -> dict[str, Any]:
    try:
        result = determinations.get_determination(conn, int(value))
    except (TypeError, ValueError, sqlite3.Error) as exc:
        raise ValueError("governed_publication_determination_not_found") from exc
    if result.get("status") != "accepted_as_attributed_determination_record":
        raise ValueError("governed_publication_determination_not_eligible")
    return result


def _snapshot_digest(snapshot: Mapping[str, Any]) -> str:
    return hashlib.sha256(_json(snapshot).encode("utf-8")).hexdigest()


def _snapshot(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "publication_id": int(row["id"]),
        "determination_id": int(row["determination_id"]),
        "publication_version": int(row["publication_version"]),
        "representation_mode": row["representation_mode"],
        "public_title": row["public_title"],
        "public_representation": row["public_representation"],
        "authority_representation": row["authority_representation"],
        "mandate_representation": row["mandate_representation"],
        "reasons_status": row["reasons_status"],
        "challenge_warning_status": row["challenge_warning_status"],
        "challenge_warning_text": row["challenge_warning_text"],
        "current_effect_status": row["current_effect_status"],
        "current_effect_rationale": row["current_effect_rationale"],
        "effect_as_of": row["effect_as_of"],
        "redaction_notice": row["redaction_notice"],
        "supersession_representation": row["supersession_representation"],
        "limitations": row["limitations"],
        "created_at": row["created_at"],
    }


def _refresh_digest(conn: sqlite3.Connection, publication_id: int) -> None:
    row = conn.execute("SELECT * FROM record_governed_determination_publications WHERE id=?", (publication_id,)).fetchone()
    conn.execute("UPDATE record_governed_determination_publications SET content_digest=? WHERE id=?", (_snapshot_digest(_snapshot(dict(row))), publication_id))


def ensure_publication_tables(conn: sqlite3.Connection) -> None:
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS record_governed_determination_publications (
      id INTEGER PRIMARY KEY AUTOINCREMENT, idempotency_key TEXT NOT NULL UNIQUE, request_payload_json TEXT NOT NULL,
      schema_version TEXT NOT NULL, determination_id INTEGER NOT NULL, authority_id INTEGER NOT NULL, mandate_id INTEGER NOT NULL, publication_version INTEGER NOT NULL,
      representation_mode TEXT NOT NULL, public_title TEXT NOT NULL, public_representation TEXT NOT NULL,
      eligibility_status TEXT NOT NULL, eligibility_rationale TEXT,
      privacy_status TEXT NOT NULL, privacy_rationale TEXT,
      redaction_status TEXT NOT NULL, redaction_rationale TEXT, redaction_notice TEXT NOT NULL,
      reasons_status TEXT NOT NULL, authority_representation TEXT NOT NULL, mandate_representation TEXT NOT NULL,
      authority_inspection_status TEXT NOT NULL, mandate_inspection_status TEXT NOT NULL,
      challenge_warning_status TEXT NOT NULL, challenge_warning_text TEXT NOT NULL,
      current_effect_status TEXT NOT NULL, current_effect_rationale TEXT NOT NULL, effect_as_of TEXT NOT NULL,
      supersession_representation TEXT NOT NULL, limitations TEXT NOT NULL,
      lifecycle_status TEXT NOT NULL, content_digest TEXT NOT NULL,
      created_by TEXT NOT NULL, created_by_role TEXT NOT NULL, created_at TEXT NOT NULL,
      reviewer TEXT, publisher TEXT, approved_at TEXT, published_at TEXT,
      UNIQUE(determination_id, publication_version)
    );
    CREATE TABLE IF NOT EXISTS record_governed_determination_publication_reviews (
      id INTEGER PRIMARY KEY AUTOINCREMENT, publication_id INTEGER NOT NULL, review_type TEXT NOT NULL,
      status TEXT NOT NULL, rationale TEXT NOT NULL, representation_json TEXT NOT NULL,
      supporting_sources_json TEXT NOT NULL, reviewer TEXT NOT NULL, reviewer_role TEXT NOT NULL,
      reviewed_at TEXT NOT NULL, idempotency_key TEXT NOT NULL UNIQUE, request_payload_json TEXT NOT NULL,
      FOREIGN KEY(publication_id) REFERENCES record_governed_determination_publications(id)
    );
    CREATE TABLE IF NOT EXISTS record_governed_determination_publication_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT, publication_id INTEGER NOT NULL, event_type TEXT NOT NULL,
      lifecycle_status TEXT NOT NULL, rationale TEXT NOT NULL, actor TEXT NOT NULL, actor_role TEXT NOT NULL,
      occurred_at TEXT NOT NULL, idempotency_key TEXT NOT NULL UNIQUE, request_payload_json TEXT NOT NULL,
      FOREIGN KEY(publication_id) REFERENCES record_governed_determination_publications(id)
    );
    CREATE TABLE IF NOT EXISTS record_governed_determination_publication_supersessions (
      id INTEGER PRIMARY KEY AUTOINCREMENT, publication_id INTEGER NOT NULL,
      replacement_publication_id INTEGER NOT NULL, rationale TEXT NOT NULL,
      actor TEXT NOT NULL, actor_role TEXT NOT NULL, occurred_at TEXT NOT NULL,
      idempotency_key TEXT NOT NULL UNIQUE, request_payload_json TEXT NOT NULL,
      FOREIGN KEY(publication_id) REFERENCES record_governed_determination_publications(id)
    );
    CREATE INDEX IF NOT EXISTS idx_stage73_public_status ON record_governed_determination_publications(lifecycle_status, published_at);
    CREATE INDEX IF NOT EXISTS idx_stage73_public_determination ON record_governed_determination_publications(determination_id, publication_version);
    """)


def _row(row: sqlite3.Row | Mapping[str, Any]) -> dict[str, Any]:
    result = dict(row)
    for field in ("request_payload_json",):
        if field in result:
            result[field.removesuffix("_json")] = json.loads(result.pop(field))
    return result


def get_publication(conn: sqlite3.Connection, publication_id: int | str) -> dict[str, Any]:
    if not _table_exists(conn, "record_governed_determination_publications"):
        raise ValueError("governed_publication_table_absent")
    row = conn.execute("SELECT * FROM record_governed_determination_publications WHERE id=?", (int(publication_id),)).fetchone()
    if row is None:
        raise ValueError("governed_publication_not_found")
    result = _row(row)
    result["reviews"] = [dict(x) for x in conn.execute("SELECT * FROM record_governed_determination_publication_reviews WHERE publication_id=? ORDER BY id", (int(publication_id),)).fetchall()]
    result["events"] = [dict(x) for x in conn.execute("SELECT * FROM record_governed_determination_publication_events WHERE publication_id=? ORDER BY id", (int(publication_id),)).fetchall()]
    result["supersessions"] = [dict(x) for x in conn.execute("SELECT * FROM record_governed_determination_publication_supersessions WHERE publication_id=? ORDER BY id", (int(publication_id),)).fetchall()]
    result["content_digest_valid"] = result["content_digest"] == _snapshot_digest(_snapshot(result))
    return result


def list_publications(conn: sqlite3.Connection, *, public_only: bool = False) -> list[dict[str, Any]]:
    if not _table_exists(conn, "record_governed_determination_publications"):
        return []
    query = "SELECT id FROM record_governed_determination_publications"
    params: tuple[Any, ...] = ()
    if public_only:
        query += " WHERE lifecycle_status='published'"
    query += " ORDER BY COALESCE(published_at, created_at), id"
    result = []
    for row in conn.execute(query, params).fetchall():
        item = get_publication(conn, row[0])
        if public_only and not item["content_digest_valid"]:
            continue
        result.append(item)
    return result


def read_publication_diagnostic(publication_id: int | str | None = None, *, db_path: str) -> dict[str, Any]:
    path = str(db_path)
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
    except sqlite3.Error:
        return {"status": "database_unavailable", "publications": [], "publication_table_present": False}
    try:
        if not _table_exists(conn, "record_governed_determination_publications"):
            return {"status": "ok", "publications": [], "publication_table_present": False}
        if publication_id is None:
            return {"status": "ok", "publications": list_publications(conn), "publication_table_present": True}
        try:
            return {"status": "ok", "publications": [get_publication(conn, publication_id)], "publication_table_present": True}
        except ValueError:
            return {"status": "publication_not_found", "publications": [], "publication_table_present": True}
    finally:
        conn.close()


def _existing_idempotent(conn: sqlite3.Connection, table: str, key: str, payload: Mapping[str, Any]) -> dict[str, Any] | None:
    row = conn.execute(f"SELECT * FROM {table} WHERE idempotency_key=?", (key,)).fetchone()
    if row is None:
        return None
    existing = dict(row)
    if existing.get("request_payload_json") and json.loads(existing["request_payload_json"]) != dict(payload):
        raise ValueError("governed_publication_idempotency_conflict")
    if table.endswith("publications"):
        return get_publication(conn, existing["id"])
    return existing


def create_publication(conn: sqlite3.Connection, *, determination_id: int | str, representation_mode: str, public_title: str, public_representation: str, authority_representation: str, mandate_representation: str, reasons_status: str, challenge_warning_status: str, challenge_warning_text: str, current_effect_status: str, current_effect_rationale: str, effect_as_of: str, supersession_representation: str, limitations: str, redaction_notice: str = "", actor: str, actor_role: str, idempotency_key: str, _commit: bool = True) -> dict[str, Any]:
    determination = _determination(conn, determination_id)
    authority_mandate = determination.get("authority_mandate") or {}
    try:
        authority_id = int(authority_mandate["authority_id"])
        mandate_id = int(authority_mandate["mandate_id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("governed_publication_determination_authority_mandate_missing") from exc
    mode = _required(representation_mode, "governed_publication_representation_mode_required")
    if mode not in REPRESENTATION_MODES: raise ValueError("governed_publication_representation_mode_invalid")
    if reasons_status not in REASONS_STATUSES: raise ValueError("governed_publication_reasons_status_invalid")
    if challenge_warning_status not in CHALLENGE_STATUSES: raise ValueError("governed_publication_challenge_warning_status_invalid")
    if current_effect_status not in EFFECT_STATUSES: raise ValueError("governed_publication_current_effect_status_invalid")
    challenge_warning_text = _validate_challenge_warning(challenge_warning_status, challenge_warning_text)
    for value, error in ((public_title, "governed_publication_public_title_required"), (public_representation, "governed_publication_public_representation_required"), (authority_representation, "governed_publication_authority_representation_required"), (mandate_representation, "governed_publication_mandate_representation_required"), (current_effect_rationale, "governed_publication_current_effect_rationale_required"), (effect_as_of, "governed_publication_effect_as_of_required"), (supersession_representation, "governed_publication_supersession_representation_required"), (limitations, "governed_publication_limitations_required"), (actor, "governed_publication_actor_required"), (actor_role, "governed_publication_actor_role_required"), (idempotency_key, "governed_publication_idempotency_key_required")):
        _required(value, error)
    payload = {"determination_id": int(determination_id), "representation_mode": mode, "public_title": public_title, "public_representation": public_representation, "authority_representation": authority_representation, "mandate_representation": mandate_representation, "reasons_status": reasons_status, "challenge_warning_status": challenge_warning_status, "challenge_warning_text": challenge_warning_text, "current_effect_status": current_effect_status, "current_effect_rationale": current_effect_rationale, "effect_as_of": effect_as_of, "supersession_representation": supersession_representation, "limitations": limitations, "redaction_notice": redaction_notice}
    existing = _existing_idempotent(conn, "record_governed_determination_publications", idempotency_key, payload)
    if existing: return existing
    version = int(conn.execute("SELECT COALESCE(MAX(publication_version),0)+1 FROM record_governed_determination_publications WHERE determination_id=?", (int(determination_id),)).fetchone()[0])
    now = utc_now()
    values = (idempotency_key, _json(payload), SCHEMA_VERSION, int(determination_id), authority_id, mandate_id, version, mode, public_title, public_representation, "not_assessed", "not_reviewed", "not_reviewed", redaction_notice, reasons_status, authority_representation, mandate_representation, "not_inspected", "not_inspected", challenge_warning_status, challenge_warning_text, current_effect_status, current_effect_rationale, effect_as_of, supersession_representation, limitations, "draft", "", actor, actor_role, now)
    columns = "idempotency_key,request_payload_json,schema_version,determination_id,authority_id,mandate_id,publication_version,representation_mode,public_title,public_representation,eligibility_status,privacy_status,redaction_status,redaction_notice,reasons_status,authority_representation,mandate_representation,authority_inspection_status,mandate_inspection_status,challenge_warning_status,challenge_warning_text,current_effect_status,current_effect_rationale,effect_as_of,supersession_representation,limitations,lifecycle_status,content_digest,created_by,created_by_role,created_at"
    conn.execute(f"INSERT INTO record_governed_determination_publications ({columns}) VALUES ({','.join('?' for _ in values)})", values)
    publication_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    digest = _snapshot_digest(_snapshot(dict(conn.execute("SELECT * FROM record_governed_determination_publications WHERE id=?", (publication_id,)).fetchone())))
    conn.execute("UPDATE record_governed_determination_publications SET content_digest=? WHERE id=?", (digest, publication_id))
    event_key = idempotency_key + ":created"
    created_payload = {"publication_id": publication_id, "event_type": "created", "rationale": "Publication draft created; no public availability is implied."}
    conn.execute("INSERT INTO record_governed_determination_publication_events (publication_id,event_type,lifecycle_status,rationale,actor,actor_role,occurred_at,idempotency_key,request_payload_json) VALUES (?,?,?,?,?,?,?,?,?)", (publication_id, "created", "draft", created_payload["rationale"], actor, actor_role, now, event_key, _json(created_payload)))
    if _commit: conn.commit()
    return get_publication(conn, publication_id)


def _review(conn: sqlite3.Connection, *, publication_id: int | str, review_type: str, status: str, rationale: str, representation: Mapping[str, Any], supporting_sources: list[Mapping[str, Any]] | None, reviewer: str, reviewer_role: str, idempotency_key: str, _commit: bool = True) -> dict[str, Any]:
    publication = get_publication(conn, publication_id)
    if review_type not in REVIEW_TYPES: raise ValueError("governed_publication_review_type_invalid")
    _required(rationale, "governed_publication_review_rationale_required")
    _required(reviewer, "governed_publication_reviewer_required")
    _required(reviewer_role, "governed_publication_reviewer_role_required")
    representation = _review_representation(review_type, representation)
    supporting_sources = _supporting_sources(supporting_sources)
    payload = {"publication_id": int(publication_id), "review_type": review_type, "status": status, "rationale": rationale, "representation": representation, "supporting_sources": supporting_sources}
    existing = _existing_idempotent(conn, "record_governed_determination_publication_reviews", idempotency_key, payload)
    if existing: return get_publication(conn, publication_id)
    if publication["lifecycle_status"] in {"published", "withdrawn_from_publication", "superseded"}:
        raise ValueError("governed_publication_terminal")
    allowed = {"eligibility": ELIGIBILITY_STATUSES, "privacy": PRIVACY_STATUSES, "redaction": REDACTION_STATUSES, "authority": AUTHORITY_STATUSES, "mandate": AUTHORITY_STATUSES, "publication_context": {"recorded"}, "publication_approval": {"approved_for_publication", "approval_deferred", "not_approved"}}[review_type]
    if status not in allowed: raise ValueError("governed_publication_review_status_invalid")
    now = utc_now()
    conn.execute("INSERT INTO record_governed_determination_publication_reviews (publication_id,review_type,status,rationale,representation_json,supporting_sources_json,reviewer,reviewer_role,reviewed_at,idempotency_key,request_payload_json) VALUES (?,?,?,?,?,?,?,?,?,?,?)", (int(publication_id), review_type, status, rationale, _json(dict(representation)), _json(supporting_sources or []), reviewer, reviewer_role, now, idempotency_key, _json(payload)))
    field = {"eligibility": "eligibility_status", "privacy": "privacy_status", "redaction": "redaction_status", "authority": "authority_inspection_status", "mandate": "mandate_inspection_status"}.get(review_type)
    updates: list[tuple[str, Any]] = []
    if field:
        updates.append((field, status))
    rationale_field = {"eligibility": "eligibility_rationale", "privacy": "privacy_rationale", "redaction": "redaction_rationale"}.get(review_type)
    if rationale_field:
        updates.append((rationale_field, rationale))
    if review_type == "authority" and representation.get("representation") is not None:
        updates.append(("authority_representation", _required(representation["representation"], "governed_publication_authority_representation_required")))
    if review_type == "mandate" and representation.get("representation") is not None:
        updates.append(("mandate_representation", _required(representation["representation"], "governed_publication_mandate_representation_required")))
    if review_type == "publication_context":
        for field_name in ("reasons_status", "challenge_warning_status", "challenge_warning_text", "current_effect_status", "current_effect_rationale", "effect_as_of", "supersession_representation", "limitations", "redaction_notice"):
            if field_name in representation:
                value = representation[field_name]
                if field_name.endswith("_status") and value not in (REASONS_STATUSES | CHALLENGE_STATUSES | EFFECT_STATUSES):
                    raise ValueError("governed_publication_context_status_invalid")
                if field_name == "challenge_warning_text":
                    value = _validate_challenge_warning(representation.get("challenge_warning_status", ""), value)
                updates.append((field_name, _required(value, f"governed_publication_{field_name}_required") if field_name not in {"redaction_notice"} else str(value or "")))
    if updates:
        conn.execute(f"UPDATE record_governed_determination_publications SET {', '.join(f'{field}=?' for field, _ in updates)} WHERE id=?", tuple(value for _, value in updates) + (int(publication_id),))
        _refresh_digest(conn, int(publication_id))
    lifecycle = {"eligibility": "eligibility_reviewed", "privacy": "privacy_reviewed", "redaction": "redaction_reviewed", "authority": "authority_and_mandate_inspected", "mandate": "authority_and_mandate_inspected", "publication_context": "awaiting_approval", "publication_approval": "approved_for_publication"}.get(review_type)
    if lifecycle and status not in {"not_eligible", "not_cleared", "not_approved", "approval_deferred", "redactions_required", "review_required"}:
        conn.execute("UPDATE record_governed_determination_publications SET lifecycle_status=?, reviewer=?, approved_at=CASE WHEN ?='approved_for_publication' THEN ? ELSE approved_at END WHERE id=?", (lifecycle, reviewer, status, now, int(publication_id)))
    event_type = {"eligibility": "eligibility_reviewed", "privacy": "privacy_reviewed", "redaction": "redaction_reviewed", "authority": "authority_inspected", "mandate": "mandate_inspected", "publication_context": "publication_context_recorded", "publication_approval": "approved_for_publication"}[review_type]
    event_key = idempotency_key + ":event"
    event_payload = {"publication_id": int(publication_id), "event_type": event_type, "rationale": rationale, "representation": dict(representation), "supporting_sources": supporting_sources or []}
    current_lifecycle = conn.execute("SELECT lifecycle_status FROM record_governed_determination_publications WHERE id=?", (int(publication_id),)).fetchone()[0]
    conn.execute("INSERT INTO record_governed_determination_publication_events (publication_id,event_type,lifecycle_status,rationale,actor,actor_role,occurred_at,idempotency_key,request_payload_json) VALUES (?,?,?,?,?,?,?,?,?)", (int(publication_id), event_type, current_lifecycle, rationale, reviewer, reviewer_role, now, event_key, _json(event_payload)))
    if _commit: conn.commit()
    return get_publication(conn, publication_id)


def review_eligibility(conn: sqlite3.Connection, **kwargs: Any) -> dict[str, Any]: return _review(conn, review_type="eligibility", **kwargs)
def review_privacy(conn: sqlite3.Connection, **kwargs: Any) -> dict[str, Any]: return _review(conn, review_type="privacy", **kwargs)
def review_redaction(conn: sqlite3.Connection, **kwargs: Any) -> dict[str, Any]: return _review(conn, review_type="redaction", **kwargs)
def inspect_authority(conn: sqlite3.Connection, **kwargs: Any) -> dict[str, Any]: return _review(conn, review_type="authority", **kwargs)
def inspect_mandate(conn: sqlite3.Connection, **kwargs: Any) -> dict[str, Any]: return _review(conn, review_type="mandate", **kwargs)
def record_publication_context(conn: sqlite3.Connection, **kwargs: Any) -> dict[str, Any]: return _review(conn, review_type="publication_context", **kwargs)


def approve_publication(conn: sqlite3.Connection, *, publication_id: int | str, rationale: str, actor: str, actor_role: str, idempotency_key: str, _commit: bool = True) -> dict[str, Any]:
    publication = get_publication(conn, publication_id)
    if publication["eligibility_status"] != "eligible_for_review": raise ValueError("governed_publication_eligibility_required")
    if publication["privacy_status"] != "cleared_for_publication": raise ValueError("governed_publication_privacy_review_required")
    if publication["redaction_status"] != "cleared_for_publication": raise ValueError("governed_publication_redaction_review_required")
    if publication["authority_inspection_status"] == "not_inspected" or publication["mandate_inspection_status"] == "not_inspected": raise ValueError("governed_publication_authority_mandate_inspection_required")
    if publication["current_effect_status"] == "effect_not_assessed": raise ValueError("governed_publication_current_effect_qualification_required")
    if not any(review["review_type"] == "publication_context" and review["status"] == "recorded" for review in publication["reviews"]): raise ValueError("governed_publication_context_review_required")
    if actor in {review["reviewer"] for review in publication["reviews"]}: raise ValueError("governed_publication_approver_must_be_separate")
    if publication["lifecycle_status"] in {"published", "withdrawn_from_publication", "superseded"}: raise ValueError("governed_publication_terminal")
    return _review(conn, publication_id=publication_id, review_type="publication_approval", status="approved_for_publication", rationale=rationale, representation={"acknowledged": True, "human_recorded": True, "boundary": "approval_is_not_determination", "approved": True}, supporting_sources=[], reviewer=actor, reviewer_role=actor_role, idempotency_key=idempotency_key, _commit=_commit)


def publish_publication(conn: sqlite3.Connection, *, publication_id: int | str, rationale: str, actor: str, actor_role: str, idempotency_key: str, _commit: bool = True) -> dict[str, Any]:
    publication = get_publication(conn, publication_id)
    payload = {"publication_id": int(publication_id), "event_type": "published", "rationale": rationale}
    existing = _existing_idempotent(conn, "record_governed_determination_publication_events", idempotency_key, payload)
    if existing: return get_publication(conn, publication_id)
    if publication["lifecycle_status"] != "approved_for_publication": raise ValueError("governed_publication_approval_required")
    if actor in {review["reviewer"] for review in publication["reviews"]}: raise ValueError("governed_publication_publisher_must_be_separate")
    now = utc_now()
    conn.execute("UPDATE record_governed_determination_publications SET lifecycle_status='published',publisher=?,published_at=? WHERE id=?", (actor, now, int(publication_id)))
    payload = {"publication_id": int(publication_id), "event_type": "published", "rationale": rationale}
    conn.execute("INSERT INTO record_governed_determination_publication_events (publication_id,event_type,lifecycle_status,rationale,actor,actor_role,occurred_at,idempotency_key,request_payload_json) VALUES (?,?,?,?,?,?,?,?,?)", (int(publication_id), "published", "published", rationale, actor, actor_role, now, idempotency_key, _json(payload)))
    if _commit: conn.commit()
    return get_publication(conn, publication_id)


def withdraw_publication(conn: sqlite3.Connection, *, publication_id: int | str, rationale: str, actor: str, actor_role: str, idempotency_key: str, _commit: bool = True) -> dict[str, Any]:
    publication = get_publication(conn, publication_id)
    payload = {"publication_id": int(publication_id), "event_type": "withdrawn_from_publication", "rationale": rationale}
    existing = _existing_idempotent(conn, "record_governed_determination_publication_events", idempotency_key, payload)
    if existing: return get_publication(conn, publication_id)
    if publication["lifecycle_status"] != "published": raise ValueError("governed_publication_not_published")
    now = utc_now()
    conn.execute("UPDATE record_governed_determination_publications SET lifecycle_status='withdrawn_from_publication' WHERE id=?", (int(publication_id),))
    payload = {"publication_id": int(publication_id), "event_type": "withdrawn_from_publication", "rationale": rationale}
    conn.execute("INSERT INTO record_governed_determination_publication_events (publication_id,event_type,lifecycle_status,rationale,actor,actor_role,occurred_at,idempotency_key,request_payload_json) VALUES (?,?,?,?,?,?,?,?,?)", (int(publication_id), "withdrawn_from_publication", "withdrawn_from_publication", rationale, actor, actor_role, now, idempotency_key, _json(payload)))
    if _commit: conn.commit()
    return get_publication(conn, publication_id)


def supersede_publication(conn: sqlite3.Connection, *, publication_id: int | str, replacement_publication_id: int | str, rationale: str, actor: str, actor_role: str, idempotency_key: str, _commit: bool = True) -> dict[str, Any]:
    publication = get_publication(conn, publication_id)
    replacement = get_publication(conn, replacement_publication_id)
    payload = {"publication_id": int(publication_id), "replacement_publication_id": int(replacement_publication_id), "rationale": rationale}
    existing = _existing_idempotent(conn, "record_governed_determination_publication_supersessions", idempotency_key, payload)
    if existing: return get_publication(conn, publication_id)
    if int(publication_id) == int(replacement_publication_id): raise ValueError("governed_publication_self_supersession")
    if int(publication["determination_id"]) != int(replacement["determination_id"]): raise ValueError("governed_publication_supersession_determination_mismatch")
    if publication["lifecycle_status"] != "published" or replacement["lifecycle_status"] != "published": raise ValueError("governed_publication_supersession_requires_published_versions")
    if conn.execute("SELECT 1 FROM record_governed_determination_publication_supersessions WHERE publication_id=?", (int(replacement_publication_id),)).fetchone(): raise ValueError("governed_publication_supersession_cycle")
    now = utc_now()
    conn.execute("INSERT INTO record_governed_determination_publication_supersessions (publication_id,replacement_publication_id,rationale,actor,actor_role,occurred_at,idempotency_key,request_payload_json) VALUES (?,?,?,?,?,?,?,?)", (int(publication_id), int(replacement_publication_id), rationale, actor, actor_role, now, idempotency_key, _json(payload)))
    conn.execute("UPDATE record_governed_determination_publications SET lifecycle_status='superseded' WHERE id=?", (int(publication_id),))
    payload = {"publication_id": int(publication_id), "event_type": "superseded", "rationale": rationale, "replacement_publication_id": int(replacement_publication_id)}
    conn.execute("INSERT INTO record_governed_determination_publication_events (publication_id,event_type,lifecycle_status,rationale,actor,actor_role,occurred_at,idempotency_key,request_payload_json) VALUES (?,?,?,?,?,?,?,?,?)", (int(publication_id), "superseded", "superseded", rationale, actor, actor_role, now, idempotency_key + ":event", _json(payload)))
    if _commit: conn.commit()
    return get_publication(conn, publication_id)


def public_publication(conn: sqlite3.Connection, publication_id: int | str) -> dict[str, Any]:
    item = get_publication(conn, publication_id)
    if item["lifecycle_status"] != "published": raise ValueError("governed_publication_not_public")
    if not item["content_digest_valid"]: raise ValueError("governed_publication_digest_mismatch")
    result = _snapshot(item)
    result.update({"content_digest": item["content_digest"], "publication_status": item["lifecycle_status"], "published_at": item["published_at"], "redaction_notice": item["redaction_notice"], "limitations": item["limitations"]})
    return result
