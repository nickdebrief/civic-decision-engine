"""Durable lifecycle episode initiation records for Stage 58.

Episode rows are application-level append-only governance evidence.  Existing
Stage 56 events remain the implicit original episode and are never backfilled.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from pathlib import Path
from typing import Any

from api.document_lifecycle_events import ensure_lifecycle_event_table, utc_now


DEFAULT_DB_PATH = Path(os.getenv("RECORDS_DB_PATH", "records.db"))
EPISODE_TYPE_RECONSIDERATION = "reconsideration"
EPISODE_INITIAL_STATUS = "pending"


def _db_path(db_path: Path | str | None = None) -> Path:
    return Path(db_path or DEFAULT_DB_PATH)


def ensure_lifecycle_episode_table(conn: sqlite3.Connection) -> None:
    """Create the Stage 58 schema without creating historical episode rows."""

    ensure_lifecycle_event_table(conn)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS document_lifecycle_episodes (
            episode_id TEXT PRIMARY KEY CHECK (length(episode_id) = 68),
            intake_id TEXT NOT NULL CHECK (length(intake_id) = 64),
            document_identifier TEXT NOT NULL CHECK (length(trim(document_identifier)) > 0),
            episode_sequence INTEGER NOT NULL CHECK (episode_sequence > 0),
            episode_type TEXT NOT NULL CHECK (episode_type = 'reconsideration'),
            prior_episode_id TEXT,
            prior_terminal_status TEXT NOT NULL CHECK (prior_terminal_status = 'archived'),
            prior_terminal_decision_key TEXT NOT NULL CHECK (length(prior_terminal_decision_key) = 64),
            initial_status TEXT NOT NULL CHECK (initial_status = 'pending'),
            sha256_hash TEXT NOT NULL CHECK (length(sha256_hash) = 64),
            sha512_hash TEXT CHECK (sha512_hash IS NULL OR length(sha512_hash) = 128),
            initiated_at TEXT NOT NULL,
            initiating_actor TEXT NOT NULL CHECK (length(trim(initiating_actor)) > 0),
            initiating_actor_role TEXT NOT NULL CHECK (length(trim(initiating_actor_role)) > 0),
            rationale TEXT NOT NULL CHECK (
                length(trim(rationale)) > 0 AND length(rationale) <= 500
            ),
            UNIQUE (intake_id, episode_sequence),
            UNIQUE (intake_id, prior_terminal_decision_key)
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_lifecycle_episodes_document
        ON document_lifecycle_episodes (intake_id, episode_sequence)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_lifecycle_episodes_prior_decision
        ON document_lifecycle_episodes (prior_terminal_decision_key)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_lifecycle_episodes_initiated
        ON document_lifecycle_episodes (initiated_at, episode_id)
        """
    )


def _read_only_connection(db_path: Path | str | None = None) -> sqlite3.Connection | None:
    path = _db_path(db_path).resolve(strict=False)
    if not path.is_file():
        return None
    conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row else None


def episode_id_for_reconsideration(
    *, intake_id: str, prior_terminal_decision_key: str, episode_type: str = EPISODE_TYPE_RECONSIDERATION
) -> str:
    payload = {
        "schema_version": "stage58-v1",
        "intake_id": str(intake_id).strip(),
        "prior_terminal_decision_key": str(prior_terminal_decision_key).strip(),
        "episode_type": str(episode_type).strip().lower(),
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return f"LEP-{digest}"


def list_lifecycle_episodes(
    *, intake_id: str | None = None, db_path: Path | str | None = None
) -> list[dict[str, Any]]:
    conn = _read_only_connection(db_path)
    if conn is None:
        return []
    try:
        try:
            if intake_id:
                rows = conn.execute(
                    "SELECT * FROM document_lifecycle_episodes WHERE intake_id = ? "
                    "ORDER BY episode_sequence ASC",
                    (str(intake_id).strip(),),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM document_lifecycle_episodes "
                    "ORDER BY initiated_at ASC, episode_id ASC"
                ).fetchall()
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc).lower():
                return []
            raise
        return [dict(row) for row in rows]
    finally:
        conn.close()


def lifecycle_episode_by_id(
    episode_id: str, *, db_path: Path | str | None = None
) -> dict[str, Any] | None:
    conn = _read_only_connection(db_path)
    if conn is None:
        return None
    try:
        try:
            return _row(
                conn.execute(
                    "SELECT * FROM document_lifecycle_episodes WHERE episode_id = ?",
                    (str(episode_id).strip(),),
                ).fetchone()
            )
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc).lower():
                return None
            raise
    finally:
        conn.close()


def create_reconsideration_episode(
    *,
    intake_id: str,
    document_identifier: str,
    sha256_hash: str,
    sha512_hash: str | None,
    prior_terminal_decision_key: str,
    actor: str,
    actor_role: str,
    rationale: str,
    db_path: Path | str | None = None,
    initiated_at: str | None = None,
) -> tuple[dict[str, Any], bool]:
    """Insert one episode, or return the identical deterministic retry."""

    values = {
        "intake_id": str(intake_id or "").strip(),
        "document_identifier": str(document_identifier or "").strip(),
        "sha256_hash": str(sha256_hash or "").strip().lower(),
        "sha512_hash": str(sha512_hash or "").strip().lower() or None,
        "prior_terminal_decision_key": str(prior_terminal_decision_key or "").strip(),
        "actor": str(actor or "").strip(),
        "actor_role": str(actor_role or "").strip(),
        "rationale": str(rationale or "").strip(),
    }
    if len(values["intake_id"]) != 64:
        raise ValueError("lifecycle_episode_intake_id_invalid")
    if not values["document_identifier"]:
        raise ValueError("lifecycle_episode_document_identifier_required")
    if len(values["sha256_hash"]) != 64:
        raise ValueError("lifecycle_episode_sha256_required")
    if values["sha512_hash"] and len(values["sha512_hash"]) != 128:
        raise ValueError("lifecycle_episode_sha512_invalid")
    if len(values["prior_terminal_decision_key"]) != 64:
        raise ValueError("lifecycle_episode_prior_decision_invalid")
    if not values["actor"] or not values["actor_role"]:
        raise ValueError("lifecycle_episode_actor_required")
    if not values["rationale"]:
        raise ValueError("lifecycle_episode_rationale_required")
    if len(values["rationale"]) > 500:
        raise ValueError("lifecycle_episode_rationale_too_long")

    path = _db_path(db_path)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        ensure_lifecycle_episode_table(conn)
        conn.execute("BEGIN IMMEDIATE")
        terminal = conn.execute(
            "SELECT * FROM document_lifecycle_decision_events "
            "WHERE intake_id = ? ORDER BY decision_sequence DESC LIMIT 1",
            (values["intake_id"],),
        ).fetchone()
        if not terminal or terminal["decision_key"] != values["prior_terminal_decision_key"]:
            raise ValueError("lifecycle_episode_prior_decision_stale")
        if terminal["new_status"] != "archived":
            raise ValueError("lifecycle_episode_prior_status_invalid")
        if terminal["document_identifier"] != values["document_identifier"]:
            raise ValueError("lifecycle_episode_document_identifier_mismatch")
        if terminal["sha256_hash"] != values["sha256_hash"]:
            raise ValueError("lifecycle_episode_sha256_mismatch")
        if terminal["sha512_hash"] != values["sha512_hash"]:
            raise ValueError("lifecycle_episode_sha512_mismatch")

        episodes = conn.execute(
            "SELECT * FROM document_lifecycle_episodes WHERE intake_id = ? "
            "ORDER BY episode_sequence DESC",
            (values["intake_id"],),
        ).fetchall()
        existing = conn.execute(
            "SELECT * FROM document_lifecycle_episodes WHERE intake_id = ? "
            "AND prior_terminal_decision_key = ?",
            (values["intake_id"], values["prior_terminal_decision_key"]),
        ).fetchone()
        if existing:
            same = all(
                existing[key] == values[value]
                for key, value in (
                    ("document_identifier", "document_identifier"),
                    ("sha256_hash", "sha256_hash"),
                    ("sha512_hash", "sha512_hash"),
                    ("initiating_actor", "actor"),
                    ("initiating_actor_role", "actor_role"),
                    ("rationale", "rationale"),
                )
            )
            if not same:
                raise ValueError("lifecycle_episode_conflict")
            conn.commit()
            return dict(existing), True
        for existing_episode in episodes:
            latest = conn.execute(
                "SELECT new_status FROM document_lifecycle_decision_events "
                "WHERE intake_id = ? AND episode_id = ? "
                "ORDER BY decision_sequence DESC LIMIT 1",
                (values["intake_id"], existing_episode["episode_id"]),
            ).fetchone()
            if not latest or latest["new_status"] != "archived":
                raise ValueError("lifecycle_episode_active_exists")

        # Stage 56 history is the implicit original Episode 1; explicit
        # reconsideration episodes therefore begin at Episode 2.
        sequence = max((int(row["episode_sequence"]) for row in episodes), default=1) + 1
        episode_id = episode_id_for_reconsideration(
            intake_id=values["intake_id"],
            prior_terminal_decision_key=values["prior_terminal_decision_key"],
        )
        timestamp = initiated_at or utc_now()
        conn.execute(
            """
            INSERT INTO document_lifecycle_episodes (
                episode_id, intake_id, document_identifier, episode_sequence,
                episode_type, prior_episode_id, prior_terminal_status,
                prior_terminal_decision_key, initial_status, sha256_hash,
                sha512_hash, initiated_at, initiating_actor,
                initiating_actor_role, rationale
            ) VALUES (?, ?, ?, ?, 'reconsideration', ?, 'archived', ?, 'pending', ?, ?, ?, ?, ?, ?)
            """,
            (
                episode_id,
                values["intake_id"],
                values["document_identifier"],
                sequence,
                episodes[0]["episode_id"] if episodes else None,
                values["prior_terminal_decision_key"],
                values["sha256_hash"],
                values["sha512_hash"],
                timestamp,
                values["actor"],
                values["actor_role"],
                values["rationale"],
            ),
        )
        row = conn.execute(
            "SELECT * FROM document_lifecycle_episodes WHERE episode_id = ?",
            (episode_id,),
        ).fetchone()
        conn.commit()
        return dict(row), False
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def episode_current_status(
    episode: dict[str, Any], decisions: list[dict[str, Any]]
) -> str:
    episode_id = str(episode.get("episode_id") or "")
    scoped = [row for row in decisions if str(row.get("episode_id") or "") == episode_id]
    if not scoped:
        return str(episode.get("initial_status") or "pending")
    return str(max(scoped, key=lambda row: int(row.get("decision_sequence") or 0))["new_status"])
