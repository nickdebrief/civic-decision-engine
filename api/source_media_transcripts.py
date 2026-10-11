"""Private, versioned manual transcripts for Stage 80 original-source media.

This module deliberately records operator-supplied claims.  It neither
transcribes, identifies speakers, authenticates a recording, nor fetches data.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from api.document_intake import (
    intake_document_file,
    is_private_original_source_media,
    load_pending_document_read_only,
)

MAX_IMPORT_BYTES = 512 * 1024
MAX_UTTERANCES = 2_000
MAX_UTTERANCE_TEXT = 10_000
MAX_NOTE_TEXT = 2_000
MAX_TRANSCRIPT_TEXT = 100_000
SPEAKER_STATES = frozenset({"unknown", "attributed", "identified"})


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _text(value: Any, code: str, *, maximum: int = MAX_NOTE_TEXT, required: bool = False) -> str | None:
    if value is None:
        if required:
            raise ValueError(code)
        return None
    result = str(value).strip()
    if required and not result:
        raise ValueError(code)
    if not result:
        return None
    if len(result) > maximum:
        raise ValueError(code)
    return result


def ensure_transcript_tables(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS source_media_transcripts (
            id INTEGER PRIMARY KEY,
            transcript_identity TEXT NOT NULL UNIQUE,
            source_intake_id TEXT NOT NULL,
            source_sha256 TEXT NOT NULL,
            original_source_identity TEXT NOT NULL,
            version_number INTEGER NOT NULL,
            supersedes_transcript_id INTEGER,
            source_language TEXT NOT NULL,
            declared_duration_ms INTEGER,
            duration_basis TEXT NOT NULL,
            transcription_method TEXT NOT NULL,
            responsible_actor TEXT NOT NULL,
            responsible_tool TEXT,
            responsible_tool_version TEXT,
            correction_reason TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (supersedes_transcript_id) REFERENCES source_media_transcripts(id),
            UNIQUE (source_intake_id, version_number)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS source_media_transcript_utterances (
            id INTEGER PRIMARY KEY,
            transcript_id INTEGER NOT NULL,
            ordinal INTEGER NOT NULL,
            start_ms INTEGER NOT NULL,
            end_ms INTEGER NOT NULL,
            text TEXT NOT NULL,
            speaker_state TEXT NOT NULL,
            speaker_label TEXT,
            speaker_basis TEXT,
            inaudible_note TEXT,
            uncertainty_note TEXT,
            overlaps_speech INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (transcript_id) REFERENCES source_media_transcripts(id),
            UNIQUE (transcript_id, ordinal)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS source_media_transcript_translations (
            id INTEGER PRIMARY KEY,
            transcript_id INTEGER NOT NULL,
            target_language TEXT NOT NULL,
            translation_text TEXT NOT NULL,
            translation_method TEXT NOT NULL,
            translation_authority TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (transcript_id) REFERENCES source_media_transcripts(id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS source_media_transcript_audit_events (
            id INTEGER PRIMARY KEY,
            transcript_id INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            actor TEXT NOT NULL,
            event_at TEXT NOT NULL,
            detail_json TEXT NOT NULL,
            FOREIGN KEY (transcript_id) REFERENCES source_media_transcripts(id)
        )
    """)


def _source_context(source_intake_id: Any, *, root: Path | None) -> dict[str, str]:
    intake_id = _text(source_intake_id, "transcript_source_invalid", required=True)
    try:
        metadata = load_pending_document_read_only(intake_id, root=root)
    except ValueError as exc:
        raise ValueError("transcript_source_not_found") from exc
    if not is_private_original_source_media(metadata):
        raise ValueError("transcript_source_not_private_original_media")
    private = metadata["private_original_source_media"]
    expected_hash = str(metadata.get("sha256_hash") or "").lower()
    expected_identity = f"source-sha256:{expected_hash}"
    if private.get("original_source_identity") != expected_identity:
        raise ValueError("transcript_source_identity_mismatch")
    try:
        path, _ = intake_document_file(intake_id, metadata=metadata, root=root)
        actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    except (OSError, ValueError) as exc:
        raise ValueError("transcript_source_bytes_unavailable") from exc
    if actual_hash != expected_hash:
        raise ValueError("transcript_source_digest_mismatch")
    return {"intake_id": intake_id, "sha256": expected_hash, "identity": expected_identity}


def _normalise_utterances(value: Any, *, duration_ms: int | None) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value or len(value) > MAX_UTTERANCES:
        raise ValueError("transcript_utterances_invalid")
    result: list[dict[str, Any]] = []
    for ordinal, item in enumerate(value, 1):
        if not isinstance(item, Mapping):
            raise ValueError("transcript_utterance_invalid")
        try:
            start_ms, end_ms = int(item.get("start_ms")), int(item.get("end_ms"))
        except (TypeError, ValueError) as exc:
            raise ValueError("transcript_interval_invalid") from exc
        if start_ms < 0 or end_ms < start_ms or (duration_ms is not None and end_ms > duration_ms):
            raise ValueError("transcript_interval_invalid")
        state = str(item.get("speaker_state") or "unknown").strip().lower()
        if state not in SPEAKER_STATES:
            raise ValueError("transcript_speaker_state_invalid")
        label = _text(item.get("speaker_label"), "transcript_speaker_label_invalid")
        basis = _text(item.get("speaker_basis"), "transcript_speaker_basis_invalid")
        if state == "unknown" and (label or basis):
            raise ValueError("transcript_unknown_speaker_claim_invalid")
        if state in {"identified", "attributed"} and (not label or not basis):
            raise ValueError("transcript_speaker_basis_required")
        result.append({
            "ordinal": ordinal, "start_ms": start_ms, "end_ms": end_ms,
            "text": _text(item.get("text"), "transcript_utterance_text_invalid", maximum=MAX_UTTERANCE_TEXT, required=True),
            "speaker_state": state, "speaker_label": label, "speaker_basis": basis,
            "inaudible_note": _text(item.get("inaudible_note"), "transcript_inaudible_invalid"),
            "uncertainty_note": _text(item.get("uncertainty_note"), "transcript_uncertainty_invalid"),
            "overlaps_speech": bool(item.get("overlaps_speech", False)),
        })
    return result


def _normalise_translations(value: Any) -> list[dict[str, str]]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 100:
        raise ValueError("transcript_translations_invalid")
    return [{
        "target_language": _text(item.get("target_language") if isinstance(item, Mapping) else None, "transcript_translation_language_invalid", required=True),
        "translation_text": _text(item.get("translation_text") if isinstance(item, Mapping) else None, "transcript_translation_text_invalid", maximum=MAX_TRANSCRIPT_TEXT, required=True),
        "translation_method": _text(item.get("translation_method") if isinstance(item, Mapping) else None, "transcript_translation_method_invalid", required=True),
        "translation_authority": _text(item.get("translation_authority") if isinstance(item, Mapping) else None, "transcript_translation_authority_invalid", required=True),
    } for item in value]


def create_transcript_version(conn: sqlite3.Connection, *, source_intake_id: Any, payload: Mapping[str, Any], actor: str, root: Path | None = None, expected_version: int = 0) -> dict[str, Any]:
    """Append a private manual transcript, rejecting stale version requests."""
    if not isinstance(payload, Mapping):
        raise ValueError("transcript_payload_invalid")
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_IMPORT_BYTES:
        raise ValueError("transcript_import_too_large")
    source = _source_context(source_intake_id, root=root)
    method = _text(payload.get("transcription_method"), "transcript_method_invalid", required=True)
    if method not in {"manual_entry", "manual_import"}:
        raise ValueError("transcript_method_invalid")
    source_language = _text(payload.get("source_language"), "transcript_source_language_invalid", required=True)
    raw_duration = payload.get("declared_duration_ms")
    duration_ms = None if raw_duration is None else int(raw_duration)
    if duration_ms is not None and duration_ms < 0:
        raise ValueError("transcript_duration_invalid")
    duration_basis = "operator_supplied" if duration_ms is not None else "unknown"
    utterances = _normalise_utterances(payload.get("utterances"), duration_ms=duration_ms)
    translations = _normalise_translations(payload.get("translations"))
    correction_reason = _text(payload.get("correction_reason"), "transcript_correction_reason_invalid")
    tool = _text(payload.get("responsible_tool"), "transcript_tool_invalid")
    tool_version = _text(payload.get("responsible_tool_version"), "transcript_tool_version_invalid")
    actor = _text(actor, "transcript_actor_invalid", required=True)
    conn.execute("BEGIN IMMEDIATE")
    try:
        ensure_transcript_tables(conn)
        row = conn.execute("SELECT id, version_number FROM source_media_transcripts WHERE source_intake_id=? ORDER BY version_number DESC LIMIT 1", (source["intake_id"],)).fetchone()
        prior_version = int(row["version_number"]) if row else 0
        if int(expected_version) != prior_version:
            raise ValueError("transcript_version_conflict")
        if prior_version and not correction_reason:
            raise ValueError("transcript_correction_reason_required")
        version = prior_version + 1
        identity = f"transcript:{source['sha256']}:v{version}"
        now = _utc_now()
        cursor = conn.execute("""INSERT INTO source_media_transcripts (transcript_identity,source_intake_id,source_sha256,original_source_identity,version_number,supersedes_transcript_id,source_language,declared_duration_ms,duration_basis,transcription_method,responsible_actor,responsible_tool,responsible_tool_version,correction_reason,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (identity, source["intake_id"], source["sha256"], source["identity"], version, row["id"] if row else None, source_language, duration_ms, duration_basis, method, actor, tool, tool_version, correction_reason, now))
        transcript_id = int(cursor.lastrowid)
        conn.executemany("""INSERT INTO source_media_transcript_utterances (transcript_id,ordinal,start_ms,end_ms,text,speaker_state,speaker_label,speaker_basis,inaudible_note,uncertainty_note,overlaps_speech) VALUES (:transcript_id,:ordinal,:start_ms,:end_ms,:text,:speaker_state,:speaker_label,:speaker_basis,:inaudible_note,:uncertainty_note,:overlaps_speech)""", [{**item, "transcript_id": transcript_id} for item in utterances])
        conn.executemany("INSERT INTO source_media_transcript_translations (transcript_id,target_language,translation_text,translation_method,translation_authority,created_at) VALUES (?,?,?,?,?,?)", [(transcript_id, x["target_language"], x["translation_text"], x["translation_method"], x["translation_authority"], now) for x in translations])
        conn.execute("INSERT INTO source_media_transcript_audit_events (transcript_id,event_type,actor,event_at,detail_json) VALUES (?,?,?,?,?)", (transcript_id, "created" if version == 1 else "corrected", actor, now, json.dumps({"version": version, "operator_claims": True}, sort_keys=True)))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return get_transcript(conn, source_intake_id=source["intake_id"], version=version, root=root)


def get_transcript(conn: sqlite3.Connection, *, source_intake_id: Any, version: int | None = None, root: Path | None = None) -> dict[str, Any]:
    source = _source_context(source_intake_id, root=root)
    ensure_transcript_tables(conn)
    sql = "SELECT * FROM source_media_transcripts WHERE source_intake_id=?"
    args: tuple[Any, ...] = (source["intake_id"],)
    if version is not None:
        sql += " AND version_number=?"; args += (int(version),)
    sql += " ORDER BY version_number DESC LIMIT 1"
    row = conn.execute(sql, args).fetchone()
    if row is None:
        raise ValueError("transcript_not_found")
    item = dict(row)
    item["utterances"] = [dict(x) for x in conn.execute("SELECT ordinal,start_ms,end_ms,text,speaker_state,speaker_label,speaker_basis,inaudible_note,uncertainty_note,overlaps_speech FROM source_media_transcript_utterances WHERE transcript_id=? ORDER BY ordinal", (row["id"],)).fetchall()]
    item["translations"] = [dict(x) for x in conn.execute("SELECT target_language,translation_text,translation_method,translation_authority,created_at FROM source_media_transcript_translations WHERE transcript_id=? ORDER BY id", (row["id"],)).fetchall()]
    item["operator_claim_notice"] = "Speaker labels and attribution bases are operator claims, not CDE verification."
    return item
