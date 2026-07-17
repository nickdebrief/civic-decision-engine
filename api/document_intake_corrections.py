from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from api.document_intake import (
    DOCUMENT_TYPE_EXTENSIONS,
    STATUS_LABELS,
    document_media_type,
    normalize_document_keywords,
    document_type_label,
    intake_document_file,
    intake_root,
    load_pending_document,
)

DB_PATH = Path(os.getenv("RECORDS_DB_PATH", "records.db"))

CORRECTION_TYPES = {
    "metadata_document_mismatch": "Metadata–document mismatch",
}

CORRECTION_STATES = {
    "draft",
    "under_review",
    "reviewed",
    "authorised",
    "completed",
    "cancelled",
}

VALID_TRANSITIONS = {
    "draft": {"under_review", "cancelled"},
    "under_review": {"reviewed", "cancelled"},
    "reviewed": {"authorised", "cancelled"},
    "authorised": {"completed"},
    "completed": set(),
    "cancelled": set(),
}

ACTION_LABELS = {
    "created": "Created",
    "review_started": "Review started",
    "reviewed": "Reviewed",
    "authorised": "Authorised",
    "corrected_intake_created": "Corrected intake created",
    "completed": "Completed",
    "cancelled": "Cancelled",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    ensure_correction_tables(conn)
    conn.commit()
    return conn


def ensure_correction_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS document_intake_corrections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            correction_reference TEXT NOT NULL UNIQUE,
            source_intake_id TEXT NOT NULL,
            source_intake_reference TEXT,
            source_document_identity TEXT NOT NULL,
            source_sha256 TEXT NOT NULL,
            correction_type TEXT NOT NULL,
            correction_reason TEXT NOT NULL,
            correction_description TEXT NOT NULL,
            corrected_title TEXT NOT NULL,
            corrected_description TEXT NOT NULL,
            corrected_institution_source TEXT NOT NULL,
            corrected_category TEXT NOT NULL,
            corrected_document_date TEXT NOT NULL,
            corrected_reference_identifier TEXT,
            corrected_keywords TEXT,
            corrected_visibility TEXT NOT NULL,
            corrected_notes TEXT NOT NULL,
            correction_state TEXT NOT NULL,
            created_at TEXT NOT NULL,
            created_by TEXT NOT NULL,
            review_started_at TEXT,
            review_started_by TEXT,
            review_note TEXT,
            reviewed_at TEXT,
            reviewed_by TEXT,
            authorisation_at TEXT,
            authorised_by TEXT,
            authorisation_note TEXT,
            execution_at TEXT,
            executed_by TEXT,
            destination_intake_id TEXT,
            destination_intake_reference TEXT,
            destination_sha256 TEXT,
            completed_at TEXT,
            completed_by TEXT,
            cancellation_at TEXT,
            cancellation_by TEXT,
            cancellation_reason TEXT
        )
        """
    )
    conn.execute(
        "ALTER TABLE document_intake_corrections ADD COLUMN corrected_keywords TEXT"
    ) if "corrected_keywords" not in {
        row[1] for row in conn.execute("PRAGMA table_info(document_intake_corrections)")
    } else None
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS document_intake_correction_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            correction_id INTEGER NOT NULL,
            correction_reference TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            action TEXT NOT NULL,
            actor TEXT NOT NULL,
            note TEXT,
            previous_state TEXT,
            new_state TEXT,
            source_intake_id TEXT,
            destination_intake_id TEXT,
            FOREIGN KEY (correction_id) REFERENCES document_intake_corrections(id)
        )
        """
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_document_intake_corrections_reference
        ON document_intake_corrections(correction_reference)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_document_intake_corrections_source
        ON document_intake_corrections(source_intake_id)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_document_intake_corrections_state
        ON document_intake_corrections(correction_state)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_document_intake_corrections_created
        ON document_intake_corrections(created_at)
        """
    )


def _reference_date(timestamp: str | None) -> str:
    raw = str(timestamp or utc_now())[:10]
    digits = raw.replace("-", "")
    return digits if len(digits) == 8 and digits.isdigit() else utc_now()[:10].replace("-", "")


def generate_correction_reference(conn: sqlite3.Connection, timestamp: str | None = None) -> str:
    date_part = _reference_date(timestamp)
    prefix = f"CDE-CORR-{date_part}-"
    rows = conn.execute(
        "SELECT correction_reference FROM document_intake_corrections WHERE correction_reference LIKE ?",
        (prefix + "%",),
    ).fetchall()
    highest = 0
    for row in rows:
        try:
            highest = max(highest, int(str(row[0]).rsplit("-", 1)[1]))
        except (IndexError, ValueError):
            continue
    return f"{prefix}{highest + 1:03d}"


def _required(value: Any, error: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        raise ValueError(error)
    return cleaned


def _optional(value: Any) -> str | None:
    cleaned = str(value or "").strip()
    return cleaned or None


def _validate_date(value: Any) -> str:
    cleaned = _required(value, "intake_correction_metadata_required")
    try:
        datetime.strptime(cleaned, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError("intake_correction_document_date_invalid") from exc
    return cleaned


def validate_correction_type(value: str) -> str:
    normalized = str(value or "").strip()
    if normalized not in CORRECTION_TYPES:
        raise ValueError("intake_correction_type_invalid")
    return normalized


def correction_type_label(value: str | None) -> str:
    return CORRECTION_TYPES.get(str(value or ""), str(value or "") or "—")


def _has_active_or_completed_correction(conn: sqlite3.Connection, source_intake_id: str) -> bool:
    row = conn.execute(
        """
        SELECT id FROM document_intake_corrections
        WHERE source_intake_id = ?
          AND correction_state != 'cancelled'
        LIMIT 1
        """,
        (source_intake_id,),
    ).fetchone()
    return row is not None


def source_correction_for_intake(conn: sqlite3.Connection, intake_id: str) -> dict[str, Any] | None:
    ensure_correction_tables(conn)
    row = conn.execute(
        """
        SELECT * FROM document_intake_corrections
        WHERE source_intake_id = ? AND correction_state != 'cancelled'
        ORDER BY created_at DESC, id DESC LIMIT 1
        """,
        (str(intake_id or "").strip(),),
    ).fetchone()
    return dict(row) if row else None


def destination_correction_for_intake(conn: sqlite3.Connection, intake_id: str) -> dict[str, Any] | None:
    ensure_correction_tables(conn)
    row = conn.execute(
        """
        SELECT * FROM document_intake_corrections
        WHERE destination_intake_id = ?
        ORDER BY completed_at DESC, id DESC LIMIT 1
        """,
        (str(intake_id or "").strip(),),
    ).fetchone()
    return dict(row) if row else None


def _source_metadata(source_intake_id: str, *, root: Path | None = None) -> dict[str, Any]:
    try:
        return load_pending_document(source_intake_id, root=root or intake_root())
    except ValueError as exc:
        raise ValueError("intake_correction_source_not_found") from exc


def validate_source_eligibility(
    conn: sqlite3.Connection,
    source_intake_id: str,
    *,
    root: Path | None = None,
    allow_existing_completed: bool = False,
    current_correction_reference: str | None = None,
) -> dict[str, Any]:
    ensure_correction_tables(conn)
    source = _source_metadata(source_intake_id, root=root)
    if source.get("status") != "archived":
        raise ValueError("intake_correction_source_not_archived")
    sha = str(source.get("sha256_hash") or "").strip()
    if len(sha) != 64:
        raise ValueError("intake_correction_source_hash_missing")
    try:
        file_path, _ = intake_document_file(source["intake_id"], metadata=source, root=root or intake_root())
    except ValueError as exc:
        raise ValueError("intake_correction_source_has_no_document") from exc
    if not file_path.is_file():
        raise ValueError("intake_correction_source_has_no_document")
    existing = source_correction_for_intake(conn, source["intake_id"])
    if existing and current_correction_reference and existing.get("correction_reference") == current_correction_reference:
        existing = None
    if existing and not (allow_existing_completed and existing.get("correction_state") == "completed"):
        raise ValueError("intake_correction_already_exists")
    completed_for_hash = conn.execute(
        """
        SELECT id FROM document_intake_corrections
        WHERE source_sha256 = ? AND correction_state = 'completed'
        LIMIT 1
        """,
        (sha,),
    ).fetchone()
    if completed_for_hash and not allow_existing_completed:
        raise ValueError("intake_correction_already_completed")
    return source


def _record_history(
    conn: sqlite3.Connection,
    *,
    correction: dict[str, Any],
    action: str,
    actor: str,
    timestamp: str,
    note: str | None,
    previous_state: str | None,
    new_state: str | None,
) -> None:
    conn.execute(
        """
        INSERT INTO document_intake_correction_history (
            correction_id, correction_reference, timestamp, action, actor, note,
            previous_state, new_state, source_intake_id, destination_intake_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            correction["id"],
            correction["correction_reference"],
            timestamp,
            action,
            str(actor or "").strip(),
            str(note or "").strip() or None,
            previous_state,
            new_state,
            correction.get("source_intake_id"),
            correction.get("destination_intake_id"),
        ),
    )


def get_correction(conn: sqlite3.Connection, correction_reference: str) -> dict[str, Any]:
    ensure_correction_tables(conn)
    row = conn.execute(
        "SELECT * FROM document_intake_corrections WHERE correction_reference = ?",
        (str(correction_reference or "").strip(),),
    ).fetchone()
    if not row:
        raise ValueError("intake_correction_not_found")
    return dict(row)


def correction_history(conn: sqlite3.Connection, correction_reference: str) -> list[dict[str, Any]]:
    correction = get_correction(conn, correction_reference)
    rows = conn.execute(
        """
        SELECT * FROM document_intake_correction_history
        WHERE correction_id = ?
        ORDER BY timestamp ASC, id ASC
        """,
        (correction["id"],),
    ).fetchall()
    return [dict(row) for row in rows]


def create_correction(
    conn: sqlite3.Connection,
    *,
    source_intake_id: str,
    correction_type: str,
    correction_reason: str,
    correction_description: str,
    corrected_title: str,
    corrected_description: str,
    corrected_institution_source: str,
    corrected_category: str,
    corrected_document_date: str,
    corrected_reference_identifier: str | None,
    corrected_visibility: str,
    corrected_notes: str,
    actor: str,
    corrected_keywords: Any = None,
    created_at: str | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    ensure_correction_tables(conn)
    actor_value = _required(actor, "intake_correction_actor_required")
    reason = _required(correction_reason, "intake_correction_reason_required")
    description = _required(correction_description, "intake_correction_description_required")
    source = validate_source_eligibility(conn, source_intake_id, root=root)
    timestamp = created_at or utc_now()
    corr_type = validate_correction_type(correction_type)
    document_date = _validate_date(corrected_document_date)
    title = _required(corrected_title, "intake_correction_metadata_required")
    dest_description = _required(corrected_description, "intake_correction_metadata_required")
    institution = _required(corrected_institution_source, "intake_correction_metadata_required")
    category = _required(corrected_category, "intake_correction_metadata_required")
    visibility = _required(corrected_visibility, "intake_correction_metadata_required")
    if visibility not in {"private", "restricted"}:
        raise ValueError("intake_correction_visibility_invalid")
    notes = _required(corrected_notes, "intake_correction_metadata_required")
    reference = generate_correction_reference(conn, timestamp)
    keywords = normalize_document_keywords(corrected_keywords)
    cursor = conn.execute(
        """
        INSERT INTO document_intake_corrections (
            correction_reference, source_intake_id, source_intake_reference,
            source_document_identity, source_sha256, correction_type,
            correction_reason, correction_description, corrected_title,
            corrected_description, corrected_institution_source, corrected_category,
            corrected_document_date, corrected_reference_identifier,
            corrected_keywords, corrected_visibility, corrected_notes, correction_state,
            created_at, created_by
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?)
        """,
        (
            reference,
            source["intake_id"],
            source.get("reference_identifier"),
            source.get("stored_filename") or source.get("original_filename"),
            source["sha256_hash"],
            corr_type,
            reason,
            description,
            title,
            dest_description,
            institution,
            category,
            document_date,
            _optional(corrected_reference_identifier),
            json.dumps(keywords, ensure_ascii=False),
            visibility,
            notes,
            timestamp,
            actor_value,
        ),
    )
    correction = get_correction_by_id(conn, int(cursor.lastrowid))
    _record_history(
        conn,
        correction=correction,
        action="created",
        actor=actor_value,
        timestamp=timestamp,
        note=reason,
        previous_state=None,
        new_state="draft",
    )
    conn.commit()
    return correction


def get_correction_by_id(conn: sqlite3.Connection, correction_id: int | str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM document_intake_corrections WHERE id = ?",
        (int(correction_id),),
    ).fetchone()
    if not row:
        raise ValueError("intake_correction_not_found")
    return dict(row)


def transition_correction(
    conn: sqlite3.Connection,
    correction_reference: str,
    *,
    new_state: str,
    actor: str,
    note: str,
    changed_at: str | None = None,
) -> dict[str, Any]:
    ensure_correction_tables(conn)
    actor_value = _required(actor, "intake_correction_actor_required")
    note_value = _required(note, "intake_correction_note_required")
    correction = get_correction(conn, correction_reference)
    current = str(correction.get("correction_state") or "")
    normalized = str(new_state or "").strip()
    if normalized not in CORRECTION_STATES or normalized not in VALID_TRANSITIONS.get(current, set()):
        raise ValueError("intake_correction_invalid_transition")
    timestamp = changed_at or utc_now()
    fields: dict[str, Any] = {
        "correction_state": normalized,
    }
    action = {
        ("draft", "under_review"): "review_started",
        ("under_review", "reviewed"): "reviewed",
        ("reviewed", "authorised"): "authorised",
    }.get((current, normalized), "cancelled" if normalized == "cancelled" else normalized)
    if normalized == "under_review":
        fields.update({"review_started_at": timestamp, "review_started_by": actor_value, "review_note": note_value})
    elif normalized == "reviewed":
        fields.update({"reviewed_at": timestamp, "reviewed_by": actor_value, "review_note": note_value})
    elif normalized == "authorised":
        fields.update({"authorisation_at": timestamp, "authorised_by": actor_value, "authorisation_note": note_value})
    elif normalized == "cancelled":
        fields.update({"cancellation_at": timestamp, "cancellation_by": actor_value, "cancellation_reason": note_value})
    assignments = ", ".join(f"{key} = ?" for key in fields)
    conn.execute(
        f"UPDATE document_intake_corrections SET {assignments} WHERE id = ?",
        (*fields.values(), correction["id"]),
    )
    updated = get_correction_by_id(conn, correction["id"])
    _record_history(
        conn,
        correction=updated,
        action=action,
        actor=actor_value,
        timestamp=timestamp,
        note=note_value,
        previous_state=current,
        new_state=normalized,
    )
    conn.commit()
    return updated


def _destination_intake_id(correction_reference: str, source_sha256: str) -> str:
    return hashlib.sha256(f"{source_sha256}:{correction_reference}".encode("utf-8")).hexdigest()


def _write_corrected_intake(
    *,
    correction: dict[str, Any],
    source: dict[str, Any],
    actor: str,
    timestamp: str,
    root: Path | None = None,
) -> dict[str, Any]:
    destination_root = (root or intake_root()).resolve(strict=False)
    destination_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    source_file, _ = intake_document_file(source["intake_id"], metadata=source, root=destination_root)
    data = source_file.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != correction["source_sha256"]:
        raise ValueError("intake_correction_hash_mismatch")
    destination_id = _destination_intake_id(correction["correction_reference"], digest)
    destination_dir = destination_root / destination_id
    if destination_dir.exists():
        raise ValueError("intake_correction_destination_already_exists")
    destination_dir.mkdir(mode=0o700)
    document_type = str(source.get("document_type") or "pdf")
    stored_filename = f"pending-{digest}{DOCUMENT_TYPE_EXTENSIONS.get(document_type, '.pdf')}"
    destination_file = destination_dir / stored_filename
    metadata_path = destination_dir / "metadata.json"
    metadata = {
        "intake_id": destination_id,
        "status": "pending",
        "original_filename": source.get("original_filename"),
        "stored_filename": stored_filename,
        "content_type": document_media_type(source),
        "document_type": document_type,
        "document_format": document_type_label(document_type),
        "file_size_bytes": len(data),
        "sha256_hash": digest,
        "title": correction["corrected_title"],
        "institution_source": correction["corrected_institution_source"],
        "document_date": correction["corrected_document_date"],
        "upload_date": timestamp,
        "category": correction["corrected_category"],
        "description": correction["corrected_description"],
        "visibility": correction["corrected_visibility"],
        "notes": correction["corrected_notes"],
        "reference_identifier": correction.get("corrected_reference_identifier"),
        "keywords": normalize_document_keywords(correction.get("corrected_keywords")),
        "tags": normalize_document_keywords(correction.get("corrected_keywords")),
        "proposed_storage_location": str(destination_file),
        "public_record_mutation": False,
        "status_updated_at": timestamp,
        "created_through_correction": True,
        "correction_reference": correction["correction_reference"],
        "correction_source_intake_id": source["intake_id"],
        "correction_source_sha256": digest,
        "correction_completed_at": timestamp,
        "status_history": [
            {
                "previous_status": None,
                "new_status": "pending",
                "timestamp": timestamp,
                "actor": actor,
                "note": "Corrected intake created through governed intake correction.",
            }
        ],
    }
    try:
        shutil.copyfile(source_file, destination_file)
        os.chmod(destination_file, 0o600)
        metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.chmod(metadata_path, 0o600)
    except Exception:
        destination_file.unlink(missing_ok=True)
        metadata_path.unlink(missing_ok=True)
        try:
            destination_dir.rmdir()
        except OSError:
            pass
        raise
    return metadata


def execute_correction(
    conn: sqlite3.Connection,
    correction_reference: str,
    *,
    actor: str,
    executed_at: str | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    ensure_correction_tables(conn)
    actor_value = _required(actor, "intake_correction_actor_required")
    correction = get_correction(conn, correction_reference)
    if correction.get("correction_state") != "authorised":
        raise ValueError("intake_correction_authorisation_required")
    if correction.get("destination_intake_id"):
        raise ValueError("intake_correction_destination_already_exists")
    timestamp = executed_at or utc_now()
    source = validate_source_eligibility(
        conn,
        correction["source_intake_id"],
        root=root,
        allow_existing_completed=True,
        current_correction_reference=correction["correction_reference"],
    )
    if source.get("sha256_hash") != correction.get("source_sha256"):
        raise ValueError("intake_correction_hash_mismatch")
    destination = _write_corrected_intake(
        correction=correction,
        source=source,
        actor=actor_value,
        timestamp=timestamp,
        root=root,
    )
    try:
        conn.execute("BEGIN IMMEDIATE")
        current = get_correction(conn, correction_reference)
        if current.get("correction_state") != "authorised" or current.get("destination_intake_id"):
            raise ValueError("intake_correction_destination_already_exists")
        conn.execute(
            """
            UPDATE document_intake_corrections
            SET correction_state = 'completed',
                execution_at = ?, executed_by = ?,
                destination_intake_id = ?, destination_intake_reference = ?,
                destination_sha256 = ?, completed_at = ?, completed_by = ?
            WHERE id = ?
            """,
            (
                timestamp,
                actor_value,
                destination["intake_id"],
                destination.get("reference_identifier"),
                destination["sha256_hash"],
                timestamp,
                actor_value,
                current["id"],
            ),
        )
        completed = get_correction_by_id(conn, current["id"])
        _record_history(
            conn,
            correction=completed,
            action="corrected_intake_created",
            actor=actor_value,
            timestamp=timestamp,
            note="Corrected intake created from preserved source document.",
            previous_state="authorised",
            new_state="completed",
        )
        _record_history(
            conn,
            correction=completed,
            action="completed",
            actor=actor_value,
            timestamp=timestamp,
            note="Governed intake correction completed.",
            previous_state="authorised",
            new_state="completed",
        )
        conn.commit()
        return completed
    except Exception:
        conn.rollback()
        destination_dir = (root or intake_root()).resolve(strict=False) / destination["intake_id"]
        shutil.rmtree(destination_dir, ignore_errors=True)
        raise


def _correction_matches(row: dict[str, Any], filters: dict[str, Any]) -> bool:
    for key, column in (
        ("correction_reference", "correction_reference"),
        ("source_intake", "source_intake_id"),
        ("destination_intake", "destination_intake_id"),
        ("created_actor", "created_by"),
    ):
        value = str(filters.get(key) or "").strip().casefold()
        if value and value not in str(row.get(column) or "").casefold():
            return False
    correction_type = str(filters.get("correction_type") or "").strip()
    if correction_type and row.get("correction_type") != correction_type:
        return False
    state = str(filters.get("correction_state") or "").strip()
    if state and row.get("correction_state") != state:
        return False
    created_from = str(filters.get("created_date_from") or "").strip()
    created_to = str(filters.get("created_date_to") or "").strip()
    completed_from = str(filters.get("completed_date_from") or "").strip()
    completed_to = str(filters.get("completed_date_to") or "").strip()
    created_date = str(row.get("created_at") or "")[:10]
    completed_date = str(row.get("completed_at") or "")[:10]
    if created_from and created_date < created_from:
        return False
    if created_to and created_date > created_to:
        return False
    if completed_from and (not completed_date or completed_date < completed_from):
        return False
    if completed_to and (not completed_date or completed_date > completed_to):
        return False
    return True


def list_corrections(conn: sqlite3.Connection, **filters: Any) -> list[dict[str, Any]]:
    ensure_correction_tables(conn)
    rows = [
        dict(row)
        for row in conn.execute(
            """
            SELECT * FROM document_intake_corrections
            ORDER BY created_at DESC, correction_reference DESC, id DESC
            """
        ).fetchall()
    ]
    return [row for row in rows if _correction_matches(row, filters)]
