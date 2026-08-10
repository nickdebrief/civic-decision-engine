from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


DEFAULT_DB_PATH = Path(os.getenv("RECORDS_DB_PATH", "records.db"))
LIFECYCLE_STATES = {
    "pending",
    "under_review",
    "approved",
    "published",
    "archived",
    "rejected",
}
VALID_TRANSITIONS = {
    "pending": {"under_review"},
    "under_review": {"approved", "rejected"},
    "approved": {"published", "archived"},
    "published": {"archived"},
    "rejected": {"archived"},
}
DIGEST_STATUSES = {"recorded", "unavailable"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def get_db(db_path: Path | str | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(Path(db_path or DEFAULT_DB_PATH), timeout=30)
    conn.row_factory = sqlite3.Row
    ensure_lifecycle_event_table(conn)
    conn.commit()
    return conn


def ensure_lifecycle_event_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS document_lifecycle_decision_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            decision_key TEXT NOT NULL UNIQUE CHECK (length(decision_key) = 64),
            intake_id TEXT NOT NULL CHECK (length(intake_id) = 64),
            decision_sequence INTEGER NOT NULL CHECK (decision_sequence > 0),
            document_identifier TEXT,
            previous_status TEXT NOT NULL CHECK (
                previous_status IN ('pending', 'under_review', 'approved', 'published', 'rejected')
            ),
            new_status TEXT NOT NULL CHECK (
                new_status IN ('under_review', 'approved', 'published', 'archived', 'rejected')
            ),
            decided_at TEXT NOT NULL,
            actor TEXT NOT NULL CHECK (length(trim(actor)) > 0),
            actor_role TEXT NOT NULL CHECK (length(trim(actor_role)) > 0),
            rationale TEXT CHECK (rationale IS NULL OR length(rationale) <= 500),
            sha256_hash TEXT,
            sha512_hash TEXT,
            digest_status TEXT NOT NULL CHECK (digest_status IN ('recorded', 'unavailable')),
            episode_id TEXT,
            UNIQUE (intake_id, decision_sequence),
            CHECK (sha256_hash IS NULL OR length(sha256_hash) = 64),
            CHECK (sha512_hash IS NULL OR length(sha512_hash) = 128),
            CHECK (
                (digest_status = 'recorded' AND sha256_hash IS NOT NULL)
                OR (digest_status = 'unavailable' AND sha256_hash IS NULL)
            ),
            CHECK (
                new_status = 'under_review'
                OR (rationale IS NOT NULL AND length(trim(rationale)) > 0)
            ),
            CHECK (new_status NOT IN ('approved', 'published') OR digest_status = 'recorded')
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_lifecycle_events_document_history
        ON document_lifecycle_decision_events (intake_id, decided_at, id)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_lifecycle_events_global_audit
        ON document_lifecycle_decision_events (decided_at, id)
        """
    )
    columns = {
        str(row[1]) for row in conn.execute(
            "PRAGMA table_info(document_lifecycle_decision_events)"
        ).fetchall()
    }
    if "episode_id" not in columns:
        conn.execute(
            "ALTER TABLE document_lifecycle_decision_events ADD COLUMN episode_id TEXT"
        )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_lifecycle_events_episode
        ON document_lifecycle_decision_events (intake_id, episode_id, decision_sequence)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_lifecycle_events_actor
        ON document_lifecycle_decision_events (actor, decided_at)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_lifecycle_events_new_status
        ON document_lifecycle_decision_events (new_status, decided_at)
        """
    )


def _clean_optional(value: Any) -> str | None:
    cleaned = str(value or "").strip()
    return cleaned or None


def _normalized_decision(
    *,
    intake_id: str,
    document_identifier: str | None,
    previous_status: str,
    new_status: str,
    actor: str,
    actor_role: str,
    rationale: str | None,
    sha256_hash: str | None,
    sha512_hash: str | None,
    episode_id: str | None = None,
) -> dict[str, Any]:
    decision = {
        "intake_id": str(intake_id or "").strip(),
        "document_identifier": _clean_optional(document_identifier),
        "previous_status": str(previous_status or "").strip().lower(),
        "new_status": str(new_status or "").strip().lower(),
        "actor": str(actor or "").strip(),
        "actor_role": str(actor_role or "").strip(),
        "rationale": _clean_optional(rationale),
        "sha256_hash": _clean_optional(sha256_hash),
        "sha512_hash": _clean_optional(sha512_hash),
        "episode_id": _clean_optional(episode_id),
    }
    if not decision["intake_id"]:
        raise ValueError("lifecycle_decision_intake_id_required")
    if decision["previous_status"] not in LIFECYCLE_STATES - {"archived"}:
        raise ValueError("lifecycle_decision_previous_status_invalid")
    if decision["new_status"] not in LIFECYCLE_STATES - {"pending"}:
        raise ValueError("lifecycle_decision_new_status_invalid")
    if decision["new_status"] not in VALID_TRANSITIONS[decision["previous_status"]]:
        raise ValueError("lifecycle_decision_transition_invalid")
    if not decision["actor"]:
        raise ValueError("lifecycle_decision_actor_required")
    if not decision["actor_role"]:
        raise ValueError("lifecycle_decision_actor_role_required")
    if decision["rationale"] is not None and len(decision["rationale"]) > 500:
        raise ValueError("lifecycle_decision_rationale_too_long")
    if decision["new_status"] != "under_review" and not decision["rationale"]:
        raise ValueError("lifecycle_decision_rationale_required")
    sha256 = decision["sha256_hash"]
    sha512 = decision["sha512_hash"]
    if sha256 is not None and (len(sha256) != 64 or any(c not in "0123456789abcdef" for c in sha256.lower())):
        raise ValueError("lifecycle_decision_sha256_invalid")
    if sha512 is not None and (len(sha512) != 128 or any(c not in "0123456789abcdef" for c in sha512.lower())):
        raise ValueError("lifecycle_decision_sha512_invalid")
    decision["sha256_hash"] = sha256.lower() if sha256 else None
    decision["sha512_hash"] = sha512.lower() if sha512 else None
    decision["digest_status"] = "recorded" if sha256 else "unavailable"
    if decision["new_status"] in {"approved", "published"} and not sha256:
        raise ValueError("lifecycle_decision_sha256_required")
    return decision


def _decision_key(decision: dict[str, Any], sequence: int) -> str:
    payload = {key: value for key, value in decision.items() if key != "episode_id" or value}
    payload["decision_sequence"] = sequence
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _same_decision(row: sqlite3.Row, decision: dict[str, Any]) -> bool:
    return all(row[key] == decision[key] for key in decision)


def record_lifecycle_decision(
    *,
    intake_id: str,
    document_identifier: str | None,
    previous_status: str,
    new_status: str,
    actor: str,
    actor_role: str,
    rationale: str | None,
    sha256_hash: str | None,
    sha512_hash: str | None,
    episode_id: str | None = None,
    applied_decision_keys: Iterable[str] = (),
    decided_at: str | None = None,
    db_path: Path | str | None = None,
) -> tuple[dict[str, Any], bool]:
    """Insert a decision, or return the identical unprojected retry."""
    decision = _normalized_decision(
        intake_id=intake_id,
        document_identifier=document_identifier,
        previous_status=previous_status,
        new_status=new_status,
        actor=actor,
        actor_role=actor_role,
        rationale=rationale,
        sha256_hash=sha256_hash,
        sha512_hash=sha512_hash,
        episode_id=episode_id,
    )
    applied = {str(value) for value in applied_decision_keys if value}
    conn = get_db(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        latest = conn.execute(
            """
            SELECT * FROM document_lifecycle_decision_events
            WHERE intake_id = ? ORDER BY decision_sequence DESC LIMIT 1
            """,
            (decision["intake_id"],),
        ).fetchone()
        if latest and latest["decision_key"] not in applied:
            if _same_decision(latest, decision):
                conn.commit()
                return dict(latest), True
            raise ValueError("lifecycle_decision_conflict")

        sequence = int(latest["decision_sequence"]) + 1 if latest else 1
        key = _decision_key(decision, sequence)
        cursor = conn.execute(
            """
            INSERT INTO document_lifecycle_decision_events (
                decision_key, intake_id, decision_sequence, document_identifier,
                previous_status, new_status, decided_at, actor, actor_role,
                rationale, sha256_hash, sha512_hash, digest_status, episode_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                key,
                decision["intake_id"],
                sequence,
                decision["document_identifier"],
                decision["previous_status"],
                decision["new_status"],
                decided_at or utc_now(),
                decision["actor"],
                decision["actor_role"],
                decision["rationale"],
                decision["sha256_hash"],
                decision["sha512_hash"],
                decision["digest_status"],
                decision["episode_id"],
            ),
        )
        row = conn.execute(
            "SELECT * FROM document_lifecycle_decision_events WHERE id = ?",
            (int(cursor.lastrowid),),
        ).fetchone()
        conn.commit()
        return dict(row), False
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def list_lifecycle_decisions(
    *,
    intake_id: str | None = None,
    actor: str | None = None,
    new_status: str | None = None,
    db_path: Path | str | None = None,
) -> list[dict[str, Any]]:
    path = Path(db_path or DEFAULT_DB_PATH)
    if not path.is_file():
        return []
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        clauses: list[str] = []
        values: list[Any] = []
        if intake_id:
            clauses.append("intake_id = ?")
            values.append(str(intake_id).strip())
        if actor:
            clauses.append("actor = ?")
            values.append(str(actor).strip())
        if new_status:
            clauses.append("new_status = ?")
            values.append(str(new_status).strip().lower())
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        try:
            rows = conn.execute(
                "SELECT * FROM document_lifecycle_decision_events"
                f"{where} ORDER BY decided_at ASC, id ASC",
                values,
            ).fetchall()
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc).lower():
                return []
            raise
        return [dict(row) for row in rows]
    finally:
        conn.close()


def lifecycle_decision_by_key(
    decision_key: str, *, db_path: Path | str | None = None
) -> dict[str, Any] | None:
    path = Path(db_path or DEFAULT_DB_PATH)
    if not path.is_file():
        return None
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        try:
            row = conn.execute(
                "SELECT * FROM document_lifecycle_decision_events WHERE decision_key = ?",
                (str(decision_key or "").strip(),),
            ).fetchone()
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc).lower():
                return None
            raise
        return dict(row) if row else None
    finally:
        conn.close()
