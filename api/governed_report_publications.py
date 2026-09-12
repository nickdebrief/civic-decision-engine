"""Stage 79 immutable machine-readable publication authority."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from typing import Any, Mapping

from api import governed_report_publication_reviews as reviews
from api.public_origin import canonical_url

SCHEMA_VERSION = "stage79.governed_report_publication.v1"
SERIALIZER_VERSION = "stage79.canonical-json.v1"
PUBLICATION_DECLARATION = "publication_is_deliberate_not_endorsement"
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _required(value: Any, code: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise ValueError(code)
    return result


def _declaration(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or value.get("acknowledged") is not True or set(value) != {"acknowledged", "boundary"} or value.get("boundary") != PUBLICATION_DECLARATION:
        raise ValueError("governed_report_publication_declaration_required")
    return {"acknowledged": True, "boundary": PUBLICATION_DECLARATION}


def ensure_publication_tables(conn: sqlite3.Connection) -> None:
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS record_governed_report_publications (
      id INTEGER PRIMARY KEY AUTOINCREMENT, schema_version TEXT NOT NULL,
      serializer_version TEXT NOT NULL, public_identifier TEXT NOT NULL UNIQUE,
      report_id INTEGER NOT NULL, report_version_id INTEGER NOT NULL,
      eligibility_review_id INTEGER NOT NULL, eligibility_review_digest TEXT NOT NULL,
      governed_job_id INTEGER NOT NULL, governed_attempt_count INTEGER NOT NULL,
      artifact_set_digest TEXT NOT NULL, snapshot_json TEXT NOT NULL,
      snapshot_digest TEXT NOT NULL, canonical_url TEXT NOT NULL UNIQUE,
      lifecycle_status TEXT NOT NULL, created_by TEXT NOT NULL, created_by_role TEXT NOT NULL,
      rationale TEXT NOT NULL, declaration_json TEXT NOT NULL, represented_published_at TEXT NOT NULL,
      created_at TEXT NOT NULL, withdrawn_at TEXT, superseded_by_publication_id INTEGER,
      idempotency_key TEXT NOT NULL UNIQUE, request_payload_json TEXT NOT NULL,
      FOREIGN KEY(report_id) REFERENCES record_governed_reports(id),
      FOREIGN KEY(report_version_id) REFERENCES record_governed_report_versions(id),
      FOREIGN KEY(eligibility_review_id) REFERENCES record_governed_report_publication_reviews(id)
    );
    CREATE UNIQUE INDEX IF NOT EXISTS idx_stage79_one_current_version
      ON record_governed_report_publications(report_version_id)
      WHERE lifecycle_status='published';
    CREATE TABLE IF NOT EXISTS record_governed_report_publication_artifacts (
      publication_id INTEGER NOT NULL, artifact_id INTEGER NOT NULL, format TEXT NOT NULL,
      sha256 TEXT NOT NULL, size_bytes INTEGER NOT NULL, validation_state TEXT NOT NULL,
      lifecycle_status TEXT NOT NULL, governed_job_id INTEGER NOT NULL, governed_attempt_count INTEGER NOT NULL,
      PRIMARY KEY(publication_id, artifact_id), UNIQUE(publication_id, format),
      FOREIGN KEY(publication_id) REFERENCES record_governed_report_publications(id),
      FOREIGN KEY(artifact_id) REFERENCES record_governed_report_artifacts(id)
    );
    CREATE TABLE IF NOT EXISTS record_governed_report_publication_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT, publication_id INTEGER NOT NULL, event_type TEXT NOT NULL,
      resulting_status TEXT NOT NULL, rationale TEXT NOT NULL, actor TEXT NOT NULL, actor_role TEXT NOT NULL,
      declaration_json TEXT NOT NULL, occurred_at TEXT NOT NULL, idempotency_key TEXT NOT NULL UNIQUE,
      request_payload_json TEXT NOT NULL, FOREIGN KEY(publication_id) REFERENCES record_governed_report_publications(id)
    );
    CREATE TABLE IF NOT EXISTS record_governed_report_publication_supersessions (
      publication_id INTEGER PRIMARY KEY, replacement_publication_id INTEGER NOT NULL UNIQUE,
      rationale TEXT NOT NULL, actor TEXT NOT NULL, actor_role TEXT NOT NULL, occurred_at TEXT NOT NULL,
      idempotency_key TEXT NOT NULL UNIQUE, request_payload_json TEXT NOT NULL,
      FOREIGN KEY(publication_id) REFERENCES record_governed_report_publications(id),
      FOREIGN KEY(replacement_publication_id) REFERENCES record_governed_report_publications(id)
    );
    """)


def _public_representation(value: Mapping[str, Any]) -> dict[str, str]:
    allowed = {"title", "summary", "language", "limitations", "epistemic_classification"}
    if not isinstance(value, Mapping) or set(value) != allowed:
        raise ValueError("governed_report_publication_representation_invalid")
    result = {key: _required(value[key], "governed_report_publication_representation_invalid") for key in sorted(allowed)}
    if any(key in canonical_json(result).lower() for key in ("storage_reference", "diagnostics", "password", "token")):
        raise ValueError("governed_report_publication_representation_invalid")
    return result


def _current_review(conn: sqlite3.Connection, report_version_id: int) -> dict[str, Any]:
    rows = conn.execute("SELECT id,artifact_set_digest FROM record_governed_report_publication_reviews WHERE report_version_id=? AND lifecycle_status='eligible' AND withdrawn_at IS NULL AND superseded_by_review_id IS NULL ORDER BY id", (int(report_version_id),)).fetchall()
    found = []
    for row in rows:
        try:
            found.append(reviews.current_eligibility(conn, report_version_id=int(report_version_id), artifact_set_digest=str(row["artifact_set_digest"])))
        except ValueError:
            continue
    if len(found) != 1:
        raise ValueError("governed_report_publication_eligibility_absent")
    review = found[0]
    if review["privacy_redaction_status"] != "cleared":
        raise ValueError("governed_report_publication_privacy_required")
    return review


def _qualification_authority(artifact_set: Any) -> dict[str, Any]:
    """Require the qualification authority frozen by the shared resolver."""
    if not isinstance(artifact_set, list) or not artifact_set:
        raise ValueError("governed_report_publication_qualification_invalid")
    try:
        authority_id = int(artifact_set[0]["qualification_id"])
        authority_digest = artifact_set[0]["qualification_digest"]
    except (KeyError, TypeError, ValueError):
        raise ValueError("governed_report_publication_qualification_invalid") from None
    if authority_id <= 0 or not isinstance(authority_digest, str) or _SHA256.fullmatch(authority_digest) is None:
        raise ValueError("governed_report_publication_qualification_invalid")
    for artifact in artifact_set:
        try:
            if int(artifact["qualification_id"]) != authority_id or artifact["qualification_digest"] != authority_digest:
                raise ValueError("governed_report_publication_qualification_mismatch")
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, ValueError) and str(exc) == "governed_report_publication_qualification_mismatch":
                raise
            raise ValueError("governed_report_publication_qualification_invalid") from None
    return {"id": authority_id, "digest": authority_digest}


def _snapshot(*, publication_id: int, report: Mapping[str, Any], version: Mapping[str, Any], review: Mapping[str, Any], representation: Mapping[str, Any], actor: str, actor_role: str, rationale: str, declaration: Mapping[str, Any], published_at: str) -> dict[str, Any]:
    artifacts = [{key: item[key] for key in ("id", "format", "sha256", "size_bytes", "validation_state", "lifecycle_status", "governed_job_id", "governed_attempt_count", "pdf_conversion_authority_digest")} for item in review["artifact_set"]]
    qualification_authority = _qualification_authority(review["artifact_set"])
    identifier = f"gr-{publication_id}"
    return {
        "schema_version": SCHEMA_VERSION, "serializer_version": SERIALIZER_VERSION,
        "publication_id": publication_id, "public_identifier": identifier,
        "canonical_url": canonical_url(f"/governed-reports/{identifier}.json"),
        "report_id": int(review["report_id"]), "report_version_id": int(review["report_version_id"]),
        "eligibility_review_id": int(review["id"]), "eligibility_review_digest": str(review["artifact_set_digest"]),
        "governed_job_id": int(review["governed_job_id"]), "governed_attempt_count": int(review["governed_attempt_count"]),
        "artifact_set_digest": str(review["artifact_set_digest"]), "artifacts": artifacts,
        "specification_digest": str(version["specification_digest"]),
        "qualification_authority": qualification_authority,
        "privacy_redaction_status": str(review["privacy_redaction_status"]),
        "publication": {"actor": actor, "actor_role": actor_role, "rationale": rationale, "declaration": dict(declaration), "represented_published_at": published_at},
        "representation": dict(representation), "publication_status": "published",
        "notice": "Published is not endorsed. Machine-readable representation is not source evidence.",
    }


def _row(conn: sqlite3.Connection, publication_id: int) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM record_governed_report_publications WHERE id=?", (int(publication_id),)).fetchone()
    if row is None: raise ValueError("governed_report_publication_not_found")
    value = dict(row); value["snapshot"] = json.loads(value.pop("snapshot_json")); value["request_payload"] = json.loads(value.pop("request_payload_json"))
    value["events"] = [dict(x) for x in conn.execute("SELECT * FROM record_governed_report_publication_events WHERE publication_id=? ORDER BY id", (int(publication_id),)).fetchall()]
    return value


def publish(conn: sqlite3.Connection, *, report_id: int, report_version_id: int, representation: Mapping[str, Any], actor: str, actor_role: str, rationale: str, declaration: Mapping[str, Any], idempotency_key: str) -> dict[str, Any]:
    ensure_publication_tables(conn)
    actor, actor_role, rationale, key = _required(actor, "governed_report_publication_actor_required"), _required(actor_role, "governed_report_publication_role_required"), _required(rationale, "governed_report_publication_rationale_required"), _required(idempotency_key, "governed_report_publication_idempotency_required")
    declared, rendered = _declaration(declaration), _public_representation(representation)
    payload = {"report_id": int(report_id), "report_version_id": int(report_version_id), "representation": rendered, "rationale": rationale, "declaration": declared}
    conn.execute("BEGIN IMMEDIATE")
    try:
        existing = conn.execute("SELECT id,request_payload_json FROM record_governed_report_publications WHERE idempotency_key=?", (key,)).fetchone()
        if existing:
            if str(existing["request_payload_json"]) != canonical_json(payload): raise ValueError("governed_report_publication_idempotency_conflict")
            conn.commit(); return _row(conn, int(existing["id"]))
        version = conn.execute("SELECT * FROM record_governed_report_versions WHERE id=? AND report_id=?", (int(report_version_id), int(report_id))).fetchone()
        report = conn.execute("SELECT * FROM record_governed_reports WHERE id=?", (int(report_id),)).fetchone()
        if version is None or report is None: raise ValueError("governed_report_publication_version_invalid")
        review = _current_review(conn, int(report_version_id))
        now = utc_now()
        cursor = conn.execute("INSERT INTO record_governed_report_publications(schema_version,serializer_version,public_identifier,report_id,report_version_id,eligibility_review_id,eligibility_review_digest,governed_job_id,governed_attempt_count,artifact_set_digest,snapshot_json,snapshot_digest,canonical_url,lifecycle_status,created_by,created_by_role,rationale,declaration_json,represented_published_at,created_at,idempotency_key,request_payload_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (SCHEMA_VERSION,SERIALIZER_VERSION,"pending",int(report_id),int(report_version_id),int(review["id"]),str(review["artifact_set_digest"]),int(review["governed_job_id"]),int(review["governed_attempt_count"]),str(review["artifact_set_digest"]),"{}","", "pending", "published",actor,actor_role,rationale,canonical_json(declared),now,now,key,canonical_json(payload)))
        publication_id = int(cursor.lastrowid)
        snapshot = _snapshot(publication_id=publication_id, report=dict(report), version=dict(version), review=review, representation=rendered, actor=actor, actor_role=actor_role, rationale=rationale, declaration=declared, published_at=now)
        snapshot_digest = digest(snapshot); identifier = snapshot["public_identifier"]; url = snapshot["canonical_url"]
        conn.execute("UPDATE record_governed_report_publications SET public_identifier=?,snapshot_json=?,snapshot_digest=?,canonical_url=? WHERE id=?", (identifier,canonical_json(snapshot),snapshot_digest,url,publication_id))
        for item in snapshot["artifacts"]:
            conn.execute("INSERT INTO record_governed_report_publication_artifacts(publication_id,artifact_id,format,sha256,size_bytes,validation_state,lifecycle_status,governed_job_id,governed_attempt_count) VALUES(?,?,?,?,?,?,?,?,?)", (publication_id,item["id"],item["format"],item["sha256"],item["size_bytes"],item["validation_state"],item["lifecycle_status"],item["governed_job_id"],item["governed_attempt_count"]))
        conn.execute("INSERT INTO record_governed_report_publication_events(publication_id,event_type,resulting_status,rationale,actor,actor_role,declaration_json,occurred_at,idempotency_key,request_payload_json) VALUES(?,?,?,?,?,?,?,?,?,?)", (publication_id,"published","published",rationale,actor,actor_role,canonical_json(declared),now,key+":event",canonical_json(payload)))
        conn.commit(); return _row(conn, publication_id)
    except Exception:
        conn.rollback(); raise


def _lifecycle(conn: sqlite3.Connection, publication_id: int, event: str, *, actor: str, actor_role: str, rationale: str, declaration: Mapping[str, Any], idempotency_key: str, replacement_id: int | None = None) -> dict[str, Any]:
    item = _row(conn, publication_id); declared = _declaration(declaration); key = _required(idempotency_key, "governed_report_publication_idempotency_required")
    payload = {"publication_id": int(publication_id), "event": event, "replacement_id": replacement_id, "rationale": _required(rationale, "governed_report_publication_rationale_required"), "declaration": declared}
    existing = conn.execute("SELECT id,request_payload_json FROM record_governed_report_publication_events WHERE idempotency_key=?", (key,)).fetchone()
    if existing:
        if str(existing["request_payload_json"]) != canonical_json(payload): raise ValueError("governed_report_publication_idempotency_conflict")
        return item
    if item["lifecycle_status"] != "published": raise ValueError("governed_report_publication_transition_invalid")
    now=utc_now()
    if event == "superseded":
        replacement=_row(conn, int(replacement_id or 0))
        if replacement["lifecycle_status"] != "published" or int(replacement["report_id"]) != int(item["report_id"]) or int(replacement["id"]) == int(item["id"]): raise ValueError("governed_report_publication_supersession_invalid")
        conn.execute("INSERT INTO record_governed_report_publication_supersessions(publication_id,replacement_publication_id,rationale,actor,actor_role,occurred_at,idempotency_key,request_payload_json) VALUES(?,?,?,?,?,?,?,?)", (publication_id,int(replacement_id),payload["rationale"],actor,actor_role,now,key,canonical_json(payload)))
        conn.execute("UPDATE record_governed_report_publications SET lifecycle_status='superseded',superseded_by_publication_id=? WHERE id=?", (int(replacement_id),publication_id))
    else:
        conn.execute("UPDATE record_governed_report_publications SET lifecycle_status='withdrawn',withdrawn_at=? WHERE id=?", (now,publication_id))
    conn.execute("INSERT INTO record_governed_report_publication_events(publication_id,event_type,resulting_status,rationale,actor,actor_role,declaration_json,occurred_at,idempotency_key,request_payload_json) VALUES(?,?,?,?,?,?,?,?,?,?)", (publication_id,event,event,payload["rationale"],actor,actor_role,canonical_json(declared),now,key,canonical_json(payload)))
    return _row(conn, publication_id)


def withdraw(conn: sqlite3.Connection, publication_id: int, **kwargs: Any) -> dict[str, Any]: return _lifecycle(conn, publication_id, "withdrawn", **kwargs)
def supersede(conn: sqlite3.Connection, publication_id: int, replacement_id: int, **kwargs: Any) -> dict[str, Any]: return _lifecycle(conn, publication_id, "superseded", replacement_id=replacement_id, **kwargs)


def public_publication(conn: sqlite3.Connection, public_identifier: str) -> dict[str, Any]:
    row = conn.execute("SELECT id,lifecycle_status,snapshot_json,snapshot_digest FROM record_governed_report_publications WHERE public_identifier=?", (_required(public_identifier,"governed_report_publication_not_found"),)).fetchone()
    if row is None: raise ValueError("governed_report_publication_not_found")
    if row["lifecycle_status"] == "withdrawn": return {"tombstone": True, "publication_id": int(row["id"]), "public_identifier": public_identifier, "publication_status": "withdrawn"}
    if row["lifecycle_status"] != "published": raise ValueError("governed_report_publication_not_found")
    snapshot=json.loads(str(row["snapshot_json"]))
    if digest(snapshot) != str(row["snapshot_digest"]) or snapshot.get("public_identifier") != public_identifier: raise ValueError("governed_report_publication_digest_invalid")
    return snapshot


def verify_preserved_publication_history(conn: sqlite3.Connection) -> None:
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='record_governed_report_publications'").fetchone() is None: return
    for row in conn.execute("SELECT id,public_identifier,snapshot_json,snapshot_digest,lifecycle_status FROM record_governed_report_publications ORDER BY id"):
        try: snapshot=json.loads(str(row["snapshot_json"]))
        except json.JSONDecodeError: raise ValueError("governed_report_publication_history_invalid") from None
        if snapshot.get("schema_version") != SCHEMA_VERSION or snapshot.get("public_identifier") != row["public_identifier"] or digest(snapshot) != row["snapshot_digest"] or row["lifecycle_status"] not in {"published","withdrawn","superseded"}:
            raise ValueError("governed_report_publication_history_invalid")
