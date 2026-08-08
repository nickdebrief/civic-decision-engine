from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from api.document_intake import (
    intake_root,
    load_pending_document,
    store_email_attachment_document,
)
from api.email_documents import (
    extract_apple_emlx_attachment_payloads,
    extract_email_attachment_payloads,
    extract_outlook_msg_attachment_payloads,
    parse_email_metadata,
)


RELATIONSHIP_TYPE = "Email attachment"
EXTRACTOR_NAME = "CDE RFC 5322 attachment extractor"
EXTRACTOR_VERSION = "stage49-v1"
REGISTRY_FILENAME = ".email_attachment_relationships.sqlite3"


class EmailAttachmentPreservationError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _registry_path(root: Path | None = None) -> Path:
    destination = (root or intake_root()).resolve(strict=False)
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    return destination / REGISTRY_FILENAME


def _connect(root: Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(_registry_path(root), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS email_attachment_relationships (
            relationship_id TEXT PRIMARY KEY,
            source_identity TEXT NOT NULL UNIQUE,
            source_email_document_id TEXT NOT NULL,
            source_email_object_id TEXT NOT NULL,
            source_email_kind TEXT NOT NULL,
            attachment_document_id TEXT,
            relationship_type TEXT NOT NULL CHECK (relationship_type = 'Email attachment'),
            attachment_index INTEGER NOT NULL CHECK (attachment_index > 0),
            original_filename TEXT,
            display_title TEXT NOT NULL,
            mime_type TEXT,
            file_size_bytes INTEGER,
            sha256_hash TEXT,
            sha512_hash TEXT,
            content_id TEXT,
            inline_status INTEGER NOT NULL DEFAULT 0 CHECK (inline_status IN (0, 1)),
            extraction_status TEXT NOT NULL,
            extraction_warning TEXT,
            extraction_failure_reason TEXT,
            source_message_identifier TEXT,
            source_archive_identifier TEXT,
            source_folder_path TEXT,
            source_pathway TEXT NOT NULL,
            created_at TEXT NOT NULL,
            source_metadata_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_email_attachment_relationship_source
            ON email_attachment_relationships (source_email_document_id, attachment_index);
        CREATE INDEX IF NOT EXISTS idx_email_attachment_relationship_object
            ON email_attachment_relationships (source_email_object_id, attachment_index);
        CREATE INDEX IF NOT EXISTS idx_email_attachment_relationship_attachment
            ON email_attachment_relationships (attachment_document_id);
        CREATE INDEX IF NOT EXISTS idx_email_attachment_relationship_archive
            ON email_attachment_relationships (source_archive_identifier);
        CREATE INDEX IF NOT EXISTS idx_email_attachment_relationship_type
            ON email_attachment_relationships (relationship_type);
        """
    )
    return conn


def deterministic_source_identity(
    *,
    source_email_object_id: str,
    attachment_index: int,
    source_attachment_identifier: str | None,
    sha256_hash: str | None,
) -> str:
    seed = "\0".join(
        (
            str(source_email_object_id or "").strip(),
            str(int(attachment_index)),
            str(source_attachment_identifier or "").strip(),
            str(sha256_hash or "").strip().lower(),
        )
    )
    if not seed.split("\0", 1)[0]:
        raise EmailAttachmentPreservationError("email_attachment_source_missing")
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _relationship_id(source_identity: str) -> str:
    return "EAR-" + source_identity[:24].upper()


def _safe_display_filename(value: str | None, fallback: str) -> str:
    filename = str(value or "").replace("\\", "/").rsplit("/", 1)[-1]
    filename = "".join(
        character for character in filename if ord(character) >= 32 and character != "\x7f"
    ).strip()
    return filename[:512] or fallback


def _row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["inline_status"] = bool(result.get("inline_status"))
    try:
        result["source_metadata"] = json.loads(result.pop("source_metadata_json"))
    except (TypeError, json.JSONDecodeError):
        result["source_metadata"] = {}
    return result


def _record_relationship(values: dict[str, Any], *, root: Path | None = None) -> dict[str, Any]:
    conn = _connect(root)
    try:
        existing = conn.execute(
            "SELECT * FROM email_attachment_relationships WHERE source_identity = ?",
            (values["source_identity"],),
        ).fetchone()
        if existing:
            current = _row(existing)
            comparable = dict(values)
            comparable["inline_status"] = bool(comparable["inline_status"])
            comparable["source_metadata"] = json.loads(comparable.pop("source_metadata_json"))
            if (
                current.get("extraction_status") == "failed"
                and comparable.get("extraction_status") == "preserved"
            ):
                assignments = [column for column in values if column not in {"relationship_id", "source_identity"}]
                conn.execute(
                    f"UPDATE email_attachment_relationships SET "
                    + ", ".join(f"{column} = ?" for column in assignments)
                    + " WHERE source_identity = ?",
                    tuple(values[column] for column in assignments) + (values["source_identity"],),
                )
                conn.commit()
                updated = conn.execute(
                    "SELECT * FROM email_attachment_relationships WHERE source_identity = ?",
                    (values["source_identity"],),
                ).fetchone()
                return _row(updated)
            if any(current.get(key) != value for key, value in comparable.items()):
                raise EmailAttachmentPreservationError("email_attachment_source_identity_collision")
            return current
        columns = tuple(values)
        conn.execute(
            f"INSERT INTO email_attachment_relationships ({', '.join(columns)}) "
            f"VALUES ({', '.join('?' for _ in columns)})",
            tuple(values[column] for column in columns),
        )
        conn.commit()
        stored = conn.execute(
            "SELECT * FROM email_attachment_relationships WHERE source_identity = ?",
            (values["source_identity"],),
        ).fetchone()
        return _row(stored)
    finally:
        conn.close()


def preserve_attachment_bytes(
    *,
    source_document: dict[str, Any],
    source_email_object_id: str,
    source_email_kind: str,
    attachment_index: int,
    data: bytes,
    original_filename: str | None,
    display_title: str,
    mime_type: str | None,
    source_attachment_identifier: str | None = None,
    source_message_identifier: str | None = None,
    source_archive_identifier: str | None = None,
    source_folder_path: str | None = None,
    source_pathway: str,
    content_id: str | None = None,
    inline_status: bool = False,
    source_metadata: dict[str, Any] | None = None,
    extracted_at: str | None = None,
    actor: str = "system:email-attachment-preservation",
    root: Path | None = None,
) -> dict[str, Any]:
    if not isinstance(data, bytes):
        raise EmailAttachmentPreservationError("email_attachment_bytes_invalid")
    sha256_hash = hashlib.sha256(data).hexdigest()
    sha512_hash = hashlib.sha512(data).hexdigest()
    source_identity = deterministic_source_identity(
        source_email_object_id=source_email_object_id,
        attachment_index=attachment_index,
        source_attachment_identifier=source_attachment_identifier,
        sha256_hash=sha256_hash,
    )
    timestamp = extracted_at or _utc_now()
    provenance = dict(source_metadata or {})
    source_reported_filename = str(original_filename or "") or None
    safe_filename = _safe_display_filename(original_filename, f"Attachment {attachment_index}")
    safe_title = _safe_display_filename(display_title, safe_filename)
    provenance.update(
        {
            "relationship_type": RELATIONSHIP_TYPE,
            "attachment_index": int(attachment_index),
            "parent_email_preservation_identifier": source_email_object_id,
            "parent_published_document_identifier": source_document.get("document_identifier"),
            "source_message_identifier": source_message_identifier,
            "source_archive_identifier": source_archive_identifier,
            "source_folder_path": source_folder_path,
            "source_pathway": source_pathway,
            "content_id": content_id,
            "inline_status": bool(inline_status),
            "extractor_name": provenance.get("extractor_name") or EXTRACTOR_NAME,
            "extractor_version": provenance.get("extractor_version") or EXTRACTOR_VERSION,
            "extraction_timestamp": timestamp,
            "extraction_status": "preserved",
            "source_reported_original_filename": source_reported_filename,
        }
    )
    attachment_document = store_email_attachment_document(
        source_identity=source_identity,
        data=data,
        original_filename=safe_filename if source_reported_filename else None,
        display_title=safe_title,
        content_type=mime_type,
        institution_source=str(source_document.get("institution_source") or "Source email"),
        document_date=str(source_document.get("document_date") or timestamp[:10]),
        visibility=str(source_document.get("visibility") or "private"),
        provenance=provenance,
        actor=actor,
        preserved_at=timestamp,
        root=root,
    )
    metadata_json = json.dumps(provenance, sort_keys=True, separators=(",", ":"))
    values = {
        "relationship_id": _relationship_id(source_identity),
        "source_identity": source_identity,
        "source_email_document_id": str(source_document.get("intake_id") or ""),
        "source_email_object_id": str(source_email_object_id),
        "source_email_kind": str(source_email_kind),
        "attachment_document_id": attachment_document["intake_id"],
        "relationship_type": RELATIONSHIP_TYPE,
        "attachment_index": int(attachment_index),
        "original_filename": safe_filename if source_reported_filename else None,
        "display_title": safe_title,
        "mime_type": str(mime_type or "application/octet-stream"),
        "file_size_bytes": len(data),
        "sha256_hash": sha256_hash,
        "sha512_hash": sha512_hash,
        "content_id": str(content_id or "") or None,
        "inline_status": 1 if inline_status else 0,
        "extraction_status": "preserved",
        "extraction_warning": None,
        "extraction_failure_reason": None,
        "source_message_identifier": str(source_message_identifier or "") or None,
        "source_archive_identifier": str(source_archive_identifier or "") or None,
        "source_folder_path": str(source_folder_path or "") or None,
        "source_pathway": str(source_pathway),
        "created_at": timestamp,
        "source_metadata_json": metadata_json,
    }
    relationship = _record_relationship(values, root=root)
    relationship["attachment_document"] = attachment_document
    return relationship


def record_attachment_failure(
    *,
    source_document: dict[str, Any],
    source_email_object_id: str,
    source_email_kind: str,
    attachment_index: int,
    display_title: str,
    source_pathway: str,
    failure_reason: str,
    original_filename: str | None = None,
    mime_type: str | None = None,
    source_attachment_identifier: str | None = None,
    source_message_identifier: str | None = None,
    source_archive_identifier: str | None = None,
    source_folder_path: str | None = None,
    content_id: str | None = None,
    inline_status: bool = False,
    source_metadata: dict[str, Any] | None = None,
    sha256_hash: str | None = None,
    created_at: str | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    source_identity = deterministic_source_identity(
        source_email_object_id=source_email_object_id,
        attachment_index=attachment_index,
        source_attachment_identifier=source_attachment_identifier,
        sha256_hash=sha256_hash,
    )
    timestamp = created_at or _utc_now()
    metadata = dict(source_metadata or {})
    source_reported_filename = str(original_filename or "") or None
    safe_filename = _safe_display_filename(original_filename, f"Attachment {attachment_index}")
    safe_title = _safe_display_filename(display_title, safe_filename)
    metadata.update({"extractor_name": EXTRACTOR_NAME, "extractor_version": EXTRACTOR_VERSION})
    metadata["source_reported_original_filename"] = source_reported_filename
    return _record_relationship(
        {
            "relationship_id": _relationship_id(source_identity),
            "source_identity": source_identity,
            "source_email_document_id": str(source_document.get("intake_id") or ""),
            "source_email_object_id": str(source_email_object_id),
            "source_email_kind": str(source_email_kind),
            "attachment_document_id": None,
            "relationship_type": RELATIONSHIP_TYPE,
            "attachment_index": int(attachment_index),
            "original_filename": safe_filename if source_reported_filename else None,
            "display_title": safe_title,
            "mime_type": str(mime_type or "") or None,
            "file_size_bytes": None,
            "sha256_hash": None,
            "sha512_hash": None,
            "content_id": str(content_id or "") or None,
            "inline_status": 1 if inline_status else 0,
            "extraction_status": "failed",
            "extraction_warning": None,
            "extraction_failure_reason": str(failure_reason),
            "source_message_identifier": str(source_message_identifier or "") or None,
            "source_archive_identifier": str(source_archive_identifier or "") or None,
            "source_folder_path": str(source_folder_path or "") or None,
            "source_pathway": str(source_pathway),
            "created_at": timestamp,
            "source_metadata_json": json.dumps(metadata, sort_keys=True, separators=(",", ":")),
        },
        root=root,
    )


def preserve_rfc5322_attachments(
    source_document: dict[str, Any], data: bytes, *, root: Path | None = None
) -> list[dict[str, Any]]:
    message_metadata = source_document.get("email_metadata") or {}
    source_object_id = str(source_document.get("intake_id") or "")
    relationships: list[dict[str, Any]] = []
    for attachment in extract_email_attachment_payloads(data):
        payload = attachment.pop("payload")
        index = int(attachment["attachment_index"])
        source_part = f"mime-part:{attachment.get('mime_part_index')}"
        try:
            relationship = preserve_attachment_bytes(
                source_document=source_document,
                source_email_object_id=source_object_id,
                source_email_kind="published_document",
                attachment_index=index,
                data=payload,
                original_filename=attachment.get("original_filename"),
                display_title=str(attachment.get("display_title")),
                mime_type=attachment.get("mime_type"),
                source_attachment_identifier=source_part,
                source_message_identifier=message_metadata.get("message_id"),
                source_pathway="rfc5322_eml",
                content_id=attachment.get("content_id"),
                inline_status=bool(attachment.get("inline_status")),
                source_metadata=attachment,
                extracted_at=str(source_document.get("upload_date") or _utc_now()),
                root=root,
            )
        except Exception as exc:
            relationship = record_attachment_failure(
                source_document=source_document,
                source_email_object_id=source_object_id,
                source_email_kind="published_document",
                attachment_index=index,
                display_title=str(attachment.get("display_title")),
                source_pathway="rfc5322_eml",
                failure_reason=str(exc),
                original_filename=attachment.get("original_filename"),
                mime_type=attachment.get("mime_type"),
                source_attachment_identifier=source_part,
                source_message_identifier=message_metadata.get("message_id"),
                content_id=attachment.get("content_id"),
                inline_status=bool(attachment.get("inline_status")),
                source_metadata=attachment,
                created_at=str(source_document.get("upload_date") or _utc_now()),
                root=root,
            )
        relationships.append(relationship)
    return relationships


def preserve_outlook_msg_attachments(
    source_document: dict[str, Any], data: bytes, *, root: Path | None = None
) -> list[dict[str, Any]]:
    """Preserve standalone Outlook MSG attachments (CDE Platform Stage 51).

    Mirrors ``preserve_rfc5322_attachments`` for standalone ``.msg`` intake,
    reusing the existing Stage 49 preservation service unchanged. Each
    source-reported attachment occurrence remains governably represented:

    * a non-empty payload is preserved as an independent Published Document with
      an ``Email attachment`` relationship (embedded messages are preserved
      opaquely and are never recursively expanded);
    * a zero-byte occurrence cannot be admitted as a Published Document and is
      instead recorded as a failed relationship row with reason
      ``email_attachment_empty_payload`` so the source occurrence is never lost.
    """

    message_metadata = source_document.get("email_metadata") or {}
    source_object_id = str(source_document.get("intake_id") or "")
    relationships: list[dict[str, Any]] = []
    for attachment in extract_outlook_msg_attachment_payloads(data):
        payload = attachment.pop("payload")
        index = int(attachment["attachment_index"])
        source_part = f"msg-attach:{attachment.get('msg_attach_path') or index}"
        timestamp = str(source_document.get("upload_date") or _utc_now())
        if not payload:
            relationship = record_attachment_failure(
                source_document=source_document,
                source_email_object_id=source_object_id,
                source_email_kind="published_document",
                attachment_index=index,
                display_title=str(attachment.get("display_title")),
                source_pathway="outlook_msg",
                failure_reason="email_attachment_empty_payload",
                original_filename=attachment.get("original_filename"),
                mime_type=attachment.get("mime_type"),
                source_attachment_identifier=source_part,
                source_message_identifier=message_metadata.get("internet_message_id")
                or message_metadata.get("message_id"),
                content_id=attachment.get("content_id"),
                inline_status=bool(attachment.get("inline_status")),
                source_metadata=attachment,
                created_at=timestamp,
                root=root,
            )
            relationships.append(relationship)
            continue
        try:
            relationship = preserve_attachment_bytes(
                source_document=source_document,
                source_email_object_id=source_object_id,
                source_email_kind="published_document",
                attachment_index=index,
                data=payload,
                original_filename=attachment.get("original_filename"),
                display_title=str(attachment.get("display_title")),
                mime_type=attachment.get("mime_type"),
                source_attachment_identifier=source_part,
                source_message_identifier=message_metadata.get("internet_message_id")
                or message_metadata.get("message_id"),
                source_pathway="outlook_msg",
                content_id=attachment.get("content_id"),
                inline_status=bool(attachment.get("inline_status")),
                source_metadata=attachment,
                extracted_at=timestamp,
                root=root,
            )
        except Exception as exc:
            relationship = record_attachment_failure(
                source_document=source_document,
                source_email_object_id=source_object_id,
                source_email_kind="published_document",
                attachment_index=index,
                display_title=str(attachment.get("display_title")),
                source_pathway="outlook_msg",
                failure_reason=str(exc),
                original_filename=attachment.get("original_filename"),
                mime_type=attachment.get("mime_type"),
                source_attachment_identifier=source_part,
                source_message_identifier=message_metadata.get("internet_message_id")
                or message_metadata.get("message_id"),
                content_id=attachment.get("content_id"),
                inline_status=bool(attachment.get("inline_status")),
                source_metadata=attachment,
                created_at=timestamp,
                root=root,
            )
        relationships.append(relationship)
    return relationships


def preserve_apple_emlx_attachments(
    source_document: dict[str, Any], data: bytes, *, root: Path | None = None
) -> list[dict[str, Any]]:
    """Preserve standalone Apple Mail .emlx attachments (CDE Platform Stage 52).

    Recovers the authoritative RFC 5322 message bytes from the ``.emlx``
    wrapper and delegates attachment extraction to the existing RFC 5322
    extractor, then reuses the unchanged Stage 49 preservation service. Each
    source-reported attachment occurrence remains governably represented:

    * a non-empty payload is preserved as an independent Published Document with
      an ``Email attachment`` relationship (embedded messages are preserved
      opaquely and are never recursively expanded);
    * a zero-byte occurrence cannot be admitted as a Published Document and is
      instead recorded as a failed relationship row with reason
      ``email_attachment_empty_payload`` so the occurrence is never silently
      lost.

    ``source_pathway`` is ``"apple_emlx"``. The source-occurrence identifier
    reuses the RFC 5322 ``mime-part:<index>`` convention so identity stays
    deterministic and stable.
    """

    message_metadata = source_document.get("email_metadata") or {}
    source_object_id = str(source_document.get("intake_id") or "")
    relationships: list[dict[str, Any]] = []
    for attachment in extract_apple_emlx_attachment_payloads(data):
        payload = attachment.pop("payload")
        index = int(attachment["attachment_index"])
        source_part = f"mime-part:{attachment.get('mime_part_index')}"
        timestamp = str(source_document.get("upload_date") or _utc_now())
        if not payload:
            relationship = record_attachment_failure(
                source_document=source_document,
                source_email_object_id=source_object_id,
                source_email_kind="published_document",
                attachment_index=index,
                display_title=str(attachment.get("display_title")),
                source_pathway="apple_emlx",
                failure_reason="email_attachment_empty_payload",
                original_filename=attachment.get("original_filename"),
                mime_type=attachment.get("mime_type"),
                source_attachment_identifier=source_part,
                source_message_identifier=message_metadata.get("message_id"),
                content_id=attachment.get("content_id"),
                inline_status=bool(attachment.get("inline_status")),
                source_metadata=attachment,
                created_at=timestamp,
                root=root,
            )
            relationships.append(relationship)
            continue
        try:
            relationship = preserve_attachment_bytes(
                source_document=source_document,
                source_email_object_id=source_object_id,
                source_email_kind="published_document",
                attachment_index=index,
                data=payload,
                original_filename=attachment.get("original_filename"),
                display_title=str(attachment.get("display_title")),
                mime_type=attachment.get("mime_type"),
                source_attachment_identifier=source_part,
                source_message_identifier=message_metadata.get("message_id"),
                source_pathway="apple_emlx",
                content_id=attachment.get("content_id"),
                inline_status=bool(attachment.get("inline_status")),
                source_metadata=attachment,
                extracted_at=timestamp,
                root=root,
            )
        except Exception as exc:
            relationship = record_attachment_failure(
                source_document=source_document,
                source_email_object_id=source_object_id,
                source_email_kind="published_document",
                attachment_index=index,
                display_title=str(attachment.get("display_title")),
                source_pathway="apple_emlx",
                failure_reason=str(exc),
                original_filename=attachment.get("original_filename"),
                mime_type=attachment.get("mime_type"),
                source_attachment_identifier=source_part,
                source_message_identifier=message_metadata.get("message_id"),
                content_id=attachment.get("content_id"),
                inline_status=bool(attachment.get("inline_status")),
                source_metadata=attachment,
                created_at=timestamp,
                root=root,
            )
        relationships.append(relationship)
    return relationships


def preserve_mbox_message_attachments(
    source_document: dict[str, Any],
    message_bytes: bytes,
    *,
    message_index: int,
    root: Path | None = None,
) -> list[dict[str, Any]]:
    """Preserve attachments from one contained mbox message (CDE Platform Stage 53).

    The mailbox archive is the authoritative preserved source; contained
    messages are governed projections. This function recovers attachment
    payloads from one message's exact RFC 5322 bytes and preserves each through
    the unchanged Stage 49 preservation service. ``message_bytes`` must be the
    exact RFC 5322 message bytes recovered from the preserved mailbox (excluding
    the mbox ``"From "`` separator).

    Provenance hierarchy:
    * ``source_archive_identifier`` = the archive (mailbox) intake_id;
    * ``source_email_object_id`` = ``f"{intake_id}:message:{message_index}"``;
    * ``source_email_kind`` = ``"mailbox_message"``;
    * ``source_pathway`` = ``"mbox_message"``.

    Zero-byte occurrences are recorded as failed relationship rows (reason
    ``email_attachment_empty_payload``); embedded messages are preserved
    opaquely via the reused RFC 5322 extractor and are never recursively
    expanded.
    """

    archive_id = str(source_document.get("intake_id") or "")
    source_object_id = f"{archive_id}:message:{message_index}"
    message_metadata = {}
    try:
        message_metadata = parse_email_metadata(message_bytes) or {}
    except Exception:
        message_metadata = {}
    relationships: list[dict[str, Any]] = []
    for attachment in extract_email_attachment_payloads(message_bytes):
        payload = attachment.pop("payload")
        index = int(attachment["attachment_index"])
        source_part = f"mime-part:{attachment.get('mime_part_index')}"
        timestamp = str(source_document.get("upload_date") or _utc_now())
        if not payload:
            relationship = record_attachment_failure(
                source_document=source_document,
                source_email_object_id=source_object_id,
                source_email_kind="mailbox_message",
                attachment_index=index,
                display_title=str(attachment.get("display_title")),
                source_pathway="mbox_message",
                failure_reason="email_attachment_empty_payload",
                original_filename=attachment.get("original_filename"),
                mime_type=attachment.get("mime_type"),
                source_attachment_identifier=source_part,
                source_message_identifier=message_metadata.get("message_id"),
                source_archive_identifier=archive_id,
                content_id=attachment.get("content_id"),
                inline_status=bool(attachment.get("inline_status")),
                source_metadata=attachment,
                created_at=timestamp,
                root=root,
            )
            relationships.append(relationship)
            continue
        try:
            relationship = preserve_attachment_bytes(
                source_document=source_document,
                source_email_object_id=source_object_id,
                source_email_kind="mailbox_message",
                attachment_index=index,
                data=payload,
                original_filename=attachment.get("original_filename"),
                display_title=str(attachment.get("display_title")),
                mime_type=attachment.get("mime_type"),
                source_attachment_identifier=source_part,
                source_message_identifier=message_metadata.get("message_id"),
                source_archive_identifier=archive_id,
                source_pathway="mbox_message",
                content_id=attachment.get("content_id"),
                inline_status=bool(attachment.get("inline_status")),
                source_metadata=attachment,
                extracted_at=timestamp,
                root=root,
            )
        except Exception as exc:
            relationship = record_attachment_failure(
                source_document=source_document,
                source_email_object_id=source_object_id,
                source_email_kind="mailbox_message",
                attachment_index=index,
                display_title=str(attachment.get("display_title")),
                source_pathway="mbox_message",
                failure_reason=str(exc),
                original_filename=attachment.get("original_filename"),
                mime_type=attachment.get("mime_type"),
                source_attachment_identifier=source_part,
                source_message_identifier=message_metadata.get("message_id"),
                source_archive_identifier=archive_id,
                content_id=attachment.get("content_id"),
                inline_status=bool(attachment.get("inline_status")),
                source_metadata=attachment,
                created_at=timestamp,
                root=root,
            )
        relationships.append(relationship)
    return relationships


def list_source_attachments(
    source_email_object_id: str, *, root: Path | None = None
) -> list[dict[str, Any]]:
    conn = _connect(root)
    try:
        rows = conn.execute(
            """
            SELECT * FROM email_attachment_relationships
            WHERE source_email_object_id = ?
            ORDER BY attachment_index, relationship_id
            """,
            (str(source_email_object_id),),
        ).fetchall()
    finally:
        conn.close()
    results = [_row(row) for row in rows]
    for result in results:
        document_id = result.get("attachment_document_id")
        if document_id:
            try:
                result["attachment_document"] = load_pending_document(document_id, root=root)
            except ValueError:
                result["attachment_document"] = None
    return results


def list_attachment_sources(
    attachment_document_id: str, *, root: Path | None = None
) -> list[dict[str, Any]]:
    conn = _connect(root)
    try:
        rows = conn.execute(
            """
            SELECT * FROM email_attachment_relationships
            WHERE attachment_document_id = ?
            ORDER BY created_at, relationship_id
            """,
            (str(attachment_document_id),),
        ).fetchall()
    finally:
        conn.close()
    results = [_row(row) for row in rows]
    for result in results:
        source_id = result.get("source_email_document_id")
        try:
            result["source_document"] = load_pending_document(source_id, root=root)
        except ValueError:
            result["source_document"] = None
    return results


def list_archive_attachments(
    archive_id: str, *, root: Path | None = None
) -> list[dict[str, Any]]:
    """Return all attachment relationships for one archive/container (Stage 53).

    Query helper only — no schema change. Uses the existing
    ``source_archive_identifier`` index to enumerate every attachment
    relationship across all contained messages of one mbox archive. Each result
    eagerly loads its ``attachment_document`` where one exists.
    """

    conn = _connect(root)
    try:
        rows = conn.execute(
            """
            SELECT * FROM email_attachment_relationships
            WHERE source_archive_identifier = ?
            ORDER BY source_email_object_id, attachment_index, relationship_id
            """,
            (str(archive_id),),
        ).fetchall()
    finally:
        conn.close()
    results = [_row(row) for row in rows]
    for result in results:
        document_id = result.get("attachment_document_id")
        if document_id:
            try:
                result["attachment_document"] = load_pending_document(document_id, root=root)
            except ValueError:
                result["attachment_document"] = None
    return results


def get_relationship(relationship_id: str, *, root: Path | None = None) -> dict[str, Any]:
    conn = _connect(root)
    try:
        row = conn.execute(
            "SELECT * FROM email_attachment_relationships WHERE relationship_id = ?",
            (str(relationship_id),),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise EmailAttachmentPreservationError("email_attachment_relationship_not_found")
    return _row(row)
