from __future__ import annotations

import hashlib
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path, PurePath
from typing import Any


ATTACHMENT_ROOT = Path("/data/attachments")
VALID_VISIBILITY = {"private", "public"}
VALID_REDACTION_STATUS = {"none", "redacted", "withheld"}
VALID_DOCUMENT_DATE_PRECISION = {"day", "month", "year", "unknown"}
_SAFE_REFERENCE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
_SAFE_EXTENSION_RE = re.compile(r"^\.[A-Za-z0-9]{1,12}$")


class AttachmentRecordNotFound(ValueError):
    pass


def ensure_attachment_tables(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS record_attachments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            reference TEXT NOT NULL,
            record_version INTEGER NOT NULL,
            attachment_version INTEGER NOT NULL DEFAULT 1,

            filename TEXT NOT NULL,
            stored_filename TEXT NOT NULL,
            storage_path TEXT NOT NULL,

            content_type TEXT NOT NULL,
            file_size_bytes INTEGER NOT NULL,
            sha256_hash TEXT NOT NULL,

            visibility TEXT NOT NULL CHECK (visibility IN ('private', 'public')),
            redaction_status TEXT NOT NULL DEFAULT 'none'
                CHECK (redaction_status IN ('none', 'redacted', 'withheld')),
            redaction_note TEXT,

            title TEXT,
            description TEXT,
            source_label TEXT,
            document_date TEXT,
            document_date_precision TEXT NOT NULL DEFAULT 'unknown',

            uploaded_at TEXT NOT NULL,
            uploaded_by TEXT,
            supersedes_attachment_id INTEGER,

            is_latest INTEGER NOT NULL DEFAULT 1,
            is_deleted INTEGER NOT NULL DEFAULT 0,

            FOREIGN KEY (reference, record_version)
                REFERENCES records(reference, version),
            FOREIGN KEY (supersedes_attachment_id)
                REFERENCES record_attachments(id)
        )
    """)
    _ensure_optional_column(conn, "record_attachments", "document_date", "TEXT")
    _ensure_optional_column(
        conn,
        "record_attachments",
        "document_date_precision",
        "TEXT NOT NULL DEFAULT 'unknown'",
    )
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_record_attachments_reference
        ON record_attachments(reference, record_version)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_record_attachments_public
        ON record_attachments(reference, visibility, redaction_status, is_latest, is_deleted)
    """)
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_record_attachments_version
        ON record_attachments(reference, record_version, filename, attachment_version)
    """)


def attachment_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def validate_document_date(
    document_date: str | None, document_date_precision: str | None
) -> tuple[str | None, str]:
    precision = document_date_precision or "unknown"
    if precision not in VALID_DOCUMENT_DATE_PRECISION:
        raise ValueError("Invalid document date precision")

    value = document_date.strip() if isinstance(document_date, str) else None
    if value == "":
        value = None

    if precision == "unknown":
        if value is not None:
            raise ValueError("Unknown document date precision requires no document date")
        return None, "unknown"

    if value is None:
        raise ValueError("Document date is required for known precision")

    if precision == "year":
        if not re.fullmatch(r"\d{4}", value):
            raise ValueError("Year precision requires YYYY document date")
        return value, precision

    if precision == "month":
        if not re.fullmatch(r"\d{4}-\d{2}", value):
            raise ValueError("Month precision requires YYYY-MM document date")
        try:
            datetime.strptime(value, "%Y-%m")
        except ValueError as exc:
            raise ValueError("Invalid document date") from exc
        return value, precision

    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("Day precision requires YYYY-MM-DD document date")
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError("Invalid document date") from exc
    return value, precision


def store_attachment_bytes(
    conn: sqlite3.Connection,
    *,
    reference: str,
    data: bytes,
    original_filename: str,
    content_type: str | None,
    visibility: str = "private",
    redaction_status: str = "none",
    title: str | None = None,
    description: str | None = None,
    source_label: str | None = None,
    redaction_note: str | None = None,
    document_date: str | None = None,
    document_date_precision: str | None = "unknown",
    uploaded_by: str | None = None,
    root: Path = ATTACHMENT_ROOT,
) -> dict[str, Any]:
    ensure_attachment_tables(conn)
    _validate_reference(reference)
    _validate_visibility(visibility)
    _validate_redaction_status(redaction_status)
    normalized_document_date, normalized_document_date_precision = validate_document_date(
        document_date, document_date_precision
    )

    cur = conn.cursor()
    record = cur.execute(
        "SELECT reference, version FROM records "
        "WHERE reference = ? AND is_latest = 1 "
        "ORDER BY version DESC LIMIT 1",
        (reference,),
    ).fetchone()
    if not record:
        raise AttachmentRecordNotFound(f"No latest record found for {reference}")

    record_version = int(record["version"])
    sha256_hash = attachment_sha256(data)
    uploaded_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    filename = PurePath(original_filename or "attachment").name or "attachment"
    detected_content_type = content_type or "application/octet-stream"

    try:
        cur.execute(
            """
            INSERT INTO record_attachments (
                reference, record_version, attachment_version,
                filename, stored_filename, storage_path,
                content_type, file_size_bytes, sha256_hash,
                visibility, redaction_status, redaction_note,
                title, description, source_label,
                document_date, document_date_precision,
                uploaded_at, uploaded_by
            )
            VALUES (?, ?, 1, ?, '', '', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                reference,
                record_version,
                filename,
                detected_content_type,
                len(data),
                sha256_hash,
                visibility,
                redaction_status,
                redaction_note,
                title,
                description,
                source_label,
                normalized_document_date,
                normalized_document_date_precision,
                uploaded_at,
                uploaded_by,
            ),
        )
        attachment_id = int(cur.lastrowid)
        storage_path = build_attachment_storage_path(
            reference=reference,
            record_version=record_version,
            attachment_id=attachment_id,
            attachment_version=1,
            sha256_hash=sha256_hash,
            original_filename=filename,
            root=root,
        )
        storage_path.parent.mkdir(parents=True, exist_ok=True)
        with storage_path.open("xb") as handle:
            handle.write(data)

        cur.execute(
            """
            UPDATE record_attachments
            SET stored_filename = ?, storage_path = ?
            WHERE id = ?
            """,
            (storage_path.name, str(storage_path), attachment_id),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        if "storage_path" in locals() and storage_path.exists():
            storage_path.unlink()
        raise

    return {
        "attachment_id": attachment_id,
        "reference": reference,
        "record_version": record_version,
        "attachment_version": 1,
        "filename": filename,
        "stored_filename": storage_path.name,
        "storage_path": str(storage_path),
        "content_type": detected_content_type,
        "file_size_bytes": len(data),
        "sha256_hash": sha256_hash,
        "visibility": visibility,
        "redaction_status": redaction_status,
        "document_date": normalized_document_date,
        "document_date_precision": normalized_document_date_precision,
        "uploaded_at": uploaded_at,
    }


def public_manifest_attachments(
    conn: sqlite3.Connection, *, reference: str, record_version: int
) -> list[dict[str, Any]]:
    ensure_attachment_tables(conn)
    rows = conn.execute(
        """
        SELECT id, attachment_version, filename, content_type, file_size_bytes,
               sha256_hash, visibility, redaction_status, title, description,
               source_label, document_date, document_date_precision, uploaded_at
        FROM record_attachments
        WHERE reference = ?
          AND record_version = ?
          AND visibility = 'public'
          AND redaction_status != 'withheld'
          AND is_latest = 1
          AND is_deleted = 0
        ORDER BY id ASC
        """,
        (reference, record_version),
    ).fetchall()

    return [
        {
            "attachment_id": row["id"],
            "attachment_version": row["attachment_version"],
            "filename": row["filename"],
            "content_type": row["content_type"],
            "file_size_bytes": row["file_size_bytes"],
            "sha256_hash": row["sha256_hash"],
            "visibility": row["visibility"],
            "redaction_status": row["redaction_status"],
            "title": row["title"],
            "description": row["description"],
            "source_label": row["source_label"],
            "document_date": row["document_date"],
            "document_date_precision": row["document_date_precision"] or "unknown",
            "uploaded_at": row["uploaded_at"],
            "download_url": None,
        }
        for row in rows
    ]


def build_attachment_storage_path(
    *,
    reference: str,
    record_version: int,
    attachment_id: int,
    attachment_version: int,
    sha256_hash: str,
    original_filename: str,
    root: Path = ATTACHMENT_ROOT,
) -> Path:
    safe_reference = _validate_reference(reference)
    safe_hash = _validate_sha256(sha256_hash)
    suffix = _safe_suffix(original_filename)
    stored_filename = (
        f"attachment-{attachment_id}-v{attachment_version}-{safe_hash[:8]}{suffix}"
    )

    root_path = root.resolve(strict=False)
    candidate = (
        root_path
        / safe_reference
        / f"v{_positive_int(record_version, 'record_version')}"
        / "attachments"
        / stored_filename
    ).resolve(strict=False)

    try:
        candidate.relative_to(root_path)
    except ValueError as exc:
        raise ValueError("Attachment storage path escaped root") from exc

    return candidate


def _validate_reference(reference: str) -> str:
    if not _SAFE_REFERENCE_RE.fullmatch(reference):
        raise ValueError("Invalid record reference for attachment storage")
    return reference


def _validate_sha256(value: str) -> str:
    normalized = value.lower()
    if not re.fullmatch(r"[0-9a-f]{64}", normalized):
        raise ValueError("Invalid attachment SHA-256 hash")
    return normalized


def _validate_visibility(value: str) -> None:
    if value not in VALID_VISIBILITY:
        raise ValueError("Invalid attachment visibility")


def _validate_redaction_status(value: str) -> None:
    if value not in VALID_REDACTION_STATUS:
        raise ValueError("Invalid attachment redaction status")


def _ensure_optional_column(
    conn: sqlite3.Connection, table: str, column: str, definition: str
) -> None:
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _positive_int(value: int, name: str) -> int:
    if not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _safe_suffix(original_filename: str) -> str:
    name = PurePath(original_filename or "").name
    suffix = Path(name).suffix.lower()
    if _SAFE_EXTENSION_RE.fullmatch(suffix):
        return suffix
    return ""
