from __future__ import annotations

import hashlib
import re
import sqlite3
from pathlib import Path, PurePath


ATTACHMENT_ROOT = Path("/data/attachments")
_SAFE_REFERENCE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
_SAFE_EXTENSION_RE = re.compile(r"^\.[A-Za-z0-9]{1,12}$")


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
