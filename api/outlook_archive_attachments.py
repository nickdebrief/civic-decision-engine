from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from api.document_intake import intake_root
from api.outlook_archive_promotion import (
    OutlookArchivePromotionContext,
    OutlookArchivePromotionError,
    validate_outlook_message_promotion,
)


OUTLOOK_ATTACHMENT_GOVERNANCE_VERSION = "stage39e-attachment-v1"
DEFAULT_MAX_OUTLOOK_ATTACHMENT_BYTES = 128 * 1024 * 1024
ATTACHMENT_STORE_DIRECTORY = ".outlook_archive_attachments"
ATTACHMENT_ID_RE = re.compile(r"^ATT-[A-F0-9]{24}$")


class OutlookAttachmentGovernanceError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class OutlookAttachmentPromotionContext:
    attachment: dict[str, Any]
    message_context: OutlookArchivePromotionContext
    source_path: Path


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def max_outlook_attachment_bytes() -> int:
    raw = os.getenv("CDE_MAX_OUTLOOK_ATTACHMENT_BYTES", "").strip()
    try:
        value = int(raw) if raw else DEFAULT_MAX_OUTLOOK_ATTACHMENT_BYTES
    except ValueError as exc:
        raise OutlookAttachmentGovernanceError("outlook_attachment_limit_invalid") from exc
    if value <= 0:
        raise OutlookAttachmentGovernanceError("outlook_attachment_limit_invalid")
    return value


def _safe_component(value: Any, code: str) -> str:
    text = str(value or "").strip()
    if not text or text in {".", ".."} or Path(text).name != text:
        raise OutlookAttachmentGovernanceError(code)
    return text


def _safe_filename(value: Any) -> str:
    filename = str(value or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not filename or filename in {".", ".."}:
        raise OutlookAttachmentGovernanceError("outlook_attachment_filename_invalid")
    return filename[:512]


def _source_identifier(value: Any) -> str:
    identifier = str(value or "").strip()
    if not identifier or len(identifier) > 1024 or "\x00" in identifier:
        raise OutlookAttachmentGovernanceError("outlook_attachment_source_identifier_invalid")
    return identifier


def _store_root(root: Path | None = None) -> Path:
    path = (root or intake_root()) / ATTACHMENT_STORE_DIRECTORY
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        path.chmod(0o700)
    except OSError:
        pass
    return path


def _archive_root(document_id: str, root: Path | None = None) -> Path:
    archive_id = _safe_component(document_id, "outlook_attachment_archive_invalid")
    path = _store_root(root) / archive_id
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


def _attachment_root(document_id: str, attachment_id: str, root: Path | None = None) -> Path:
    if not ATTACHMENT_ID_RE.fullmatch(str(attachment_id or "")):
        raise OutlookAttachmentGovernanceError("outlook_attachment_id_invalid")
    return _archive_root(document_id, root) / attachment_id


def _metadata_path(document_id: str, attachment_id: str, root: Path | None = None) -> Path:
    return _attachment_root(document_id, attachment_id, root) / "metadata.json"


def _source_path(document_id: str, attachment_id: str, root: Path | None = None) -> Path:
    return _attachment_root(document_id, attachment_id, root) / "original.bin"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=".metadata-", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _attachment_id(
    *,
    archive_id: str,
    folder_id: str,
    message_id: str,
    source_attachment_id: str,
    sha256_hash: str,
) -> str:
    seed = "\0".join((archive_id, folder_id, message_id, source_attachment_id, sha256_hash))
    return "ATT-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24].upper()


def govern_outlook_attachment_bytes(
    document_id: str,
    message_id: str,
    *,
    data: bytes,
    filename: str,
    mime_type: str,
    source_attachment_id: str,
    extracted_at: str | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Admit extracted bytes into private attachment governance storage.

    The Outlook parser and message projection remain unchanged. A future extraction
    worker calls this boundary once it has extracted an attachment from the preserved
    archive and can provide the evidence-backed message and attachment identifiers.
    """

    if not isinstance(data, bytes) or not data:
        raise OutlookAttachmentGovernanceError("outlook_attachment_empty")
    maximum = max_outlook_attachment_bytes()
    if len(data) > maximum:
        raise OutlookAttachmentGovernanceError("outlook_attachment_too_large")
    safe_filename = _safe_filename(filename)
    safe_source_id = _source_identifier(source_attachment_id)
    normalized_mime = str(mime_type or "application/octet-stream").strip().lower()
    if not normalized_mime or len(normalized_mime) > 255 or any(
        character in normalized_mime for character in "\r\n"
    ):
        raise OutlookAttachmentGovernanceError("outlook_attachment_mime_type_invalid")
    try:
        context = validate_outlook_message_promotion(document_id, message_id, root=root)
    except OutlookArchivePromotionError as exc:
        raise OutlookAttachmentGovernanceError(exc.code) from exc

    digest = hashlib.sha256(data).hexdigest()
    archive_id = str(context.document["intake_id"])
    folder_id = str(context.message["folder_id"])
    projection_id = str(context.message["projection_id"])
    attachment_id = _attachment_id(
        archive_id=archive_id,
        folder_id=folder_id,
        message_id=projection_id,
        source_attachment_id=safe_source_id,
        sha256_hash=digest,
    )
    directory = _attachment_root(archive_id, attachment_id, root)
    metadata_path = directory / "metadata.json"
    content_path = directory / "original.bin"
    if metadata_path.exists() or content_path.exists():
        existing = load_outlook_attachment(archive_id, attachment_id, root=root)
        if (
            existing.get("sha256_hash") != digest
            or not content_path.is_file()
            or content_path.stat().st_size != len(data)
            or _sha256_file(content_path) != digest
        ):
            raise OutlookAttachmentGovernanceError("outlook_attachment_identity_collision")
        return existing

    directory.mkdir(mode=0o700, parents=False, exist_ok=False)
    try:
        fd = os.open(content_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if _sha256_file(content_path) != digest:
            raise OutlookAttachmentGovernanceError("outlook_attachment_hash_verification_failed")
        provenance = context.message["provenance"]
        metadata = {
            "attachment_id": attachment_id,
            "governance_version": OUTLOOK_ATTACHMENT_GOVERNANCE_VERSION,
            "filename": safe_filename,
            "mime_type": normalized_mime,
            "file_size_bytes": len(data),
            "sha256_hash": digest,
            "extraction_timestamp": str(extracted_at or _utc_now()),
            "extraction_status": "extracted",
            "hash_verification_status": "verified",
            "promotion_status": "eligible",
            "canonical_record_reference": None,
            "provenance": {
                "archive_id": archive_id,
                "document_identifier": context.document.get("document_identifier"),
                "folder_projection_id": folder_id,
                "folder_path": context.message.get("folder_path"),
                "message_projection_id": projection_id,
                "message_identifier": context.message.get("message_id"),
                "source_attachment_identifier": safe_source_id,
                "extraction_job": context.job.get("job_id"),
                "parser_version": provenance.get("parser_version"),
                "projection_version": context.projection.get("projection_version"),
                "source_archive_sha256": context.document.get("sha256_hash"),
            },
        }
        _write_json_atomic(metadata_path, metadata)
        return metadata
    except Exception:
        metadata_path.unlink(missing_ok=True)
        content_path.unlink(missing_ok=True)
        try:
            directory.rmdir()
        except OSError:
            pass
        raise


def load_outlook_attachment(
    document_id: str,
    attachment_id: str,
    *,
    root: Path | None = None,
) -> dict[str, Any]:
    path = _metadata_path(document_id, attachment_id, root)
    if not path.is_file():
        raise OutlookAttachmentGovernanceError("outlook_attachment_not_found")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OutlookAttachmentGovernanceError("outlook_attachment_metadata_invalid") from exc
    if not isinstance(value, dict) or value.get("attachment_id") != attachment_id:
        raise OutlookAttachmentGovernanceError("outlook_attachment_metadata_invalid")
    return value


def list_outlook_attachments(
    document_id: str,
    *,
    message_id: str | None = None,
    root: Path | None = None,
) -> list[dict[str, Any]]:
    archive_root = _archive_root(document_id, root)
    attachments: list[dict[str, Any]] = []
    for path in sorted(archive_root.glob("ATT-*/metadata.json")):
        attachment_id = path.parent.name
        try:
            metadata = load_outlook_attachment(document_id, attachment_id, root=root)
        except OutlookAttachmentGovernanceError:
            continue
        provenance = metadata.get("provenance") if isinstance(metadata.get("provenance"), dict) else {}
        if message_id and str(provenance.get("message_projection_id") or "") != str(message_id):
            continue
        attachments.append(metadata)
    return attachments


def validate_outlook_attachment_promotion(
    document_id: str,
    attachment_id: str,
    *,
    root: Path | None = None,
) -> OutlookAttachmentPromotionContext:
    attachment = load_outlook_attachment(document_id, attachment_id, root=root)
    provenance = attachment.get("provenance")
    if not isinstance(provenance, dict):
        raise OutlookAttachmentGovernanceError("outlook_attachment_provenance_missing")
    message_id = str(provenance.get("message_projection_id") or "")
    if not message_id:
        raise OutlookAttachmentGovernanceError("outlook_attachment_provenance_missing")
    try:
        context = validate_outlook_message_promotion(document_id, message_id, root=root)
    except OutlookArchivePromotionError as exc:
        raise OutlookAttachmentGovernanceError(exc.code) from exc
    required_matches = {
        "archive_id": context.document.get("intake_id"),
        "folder_projection_id": context.message.get("folder_id"),
        "message_projection_id": context.message.get("projection_id"),
        "extraction_job": context.job.get("job_id"),
        "projection_version": context.projection.get("projection_version"),
        "source_archive_sha256": context.document.get("sha256_hash"),
    }
    if any(str(provenance.get(key) or "") != str(value or "") for key, value in required_matches.items()):
        raise OutlookAttachmentGovernanceError("outlook_attachment_provenance_invalid")
    if attachment.get("extraction_status") != "extracted":
        raise OutlookAttachmentGovernanceError("outlook_attachment_extraction_incomplete")
    source_path = _source_path(document_id, attachment_id, root)
    if not source_path.is_file():
        raise OutlookAttachmentGovernanceError("outlook_attachment_content_unavailable")
    digest = _sha256_file(source_path)
    if digest != attachment.get("sha256_hash"):
        raise OutlookAttachmentGovernanceError("outlook_attachment_hash_verification_failed")
    if source_path.stat().st_size != int(attachment.get("file_size_bytes") or -1):
        raise OutlookAttachmentGovernanceError("outlook_attachment_size_verification_failed")
    if attachment.get("hash_verification_status") != "verified":
        raise OutlookAttachmentGovernanceError("outlook_attachment_hash_unverified")
    return OutlookAttachmentPromotionContext(
        attachment=attachment,
        message_context=context,
        source_path=source_path,
    )


def build_outlook_attachment_promotion_provenance(
    context: OutlookAttachmentPromotionContext,
    *,
    administrator: str,
    promoted_at: str | None = None,
) -> dict[str, Any]:
    administrator = str(administrator or "").strip()
    if not administrator:
        raise OutlookAttachmentGovernanceError("outlook_attachment_administrator_missing")
    provenance = context.attachment["provenance"]
    return {
        "promotion_version": OUTLOOK_ATTACHMENT_GOVERNANCE_VERSION,
        "archive_id": provenance["archive_id"],
        "folder_projection_id": provenance["folder_projection_id"],
        "message_projection_id": provenance["message_projection_id"],
        "message_identifier": provenance.get("message_identifier"),
        "attachment_id": context.attachment["attachment_id"],
        "source_attachment_identifier": provenance["source_attachment_identifier"],
        "attachment_filename": context.attachment["filename"],
        "sha256_hash": context.attachment["sha256_hash"],
        "file_size_bytes": context.attachment["file_size_bytes"],
        "mime_type": context.attachment["mime_type"],
        "extraction_job": provenance["extraction_job"],
        "extraction_timestamp": context.attachment["extraction_timestamp"],
        "promotion_timestamp": str(promoted_at or _utc_now()),
        "administrator": administrator,
        "projection_version": provenance["projection_version"],
        "source_archive_sha256": provenance["source_archive_sha256"],
        "provenance_chain": [
            provenance["archive_id"],
            provenance["folder_projection_id"],
            provenance["message_projection_id"],
            context.attachment["attachment_id"],
        ],
    }


def mark_outlook_attachment_promoted(
    document_id: str,
    attachment_id: str,
    *,
    canonical_record_reference: str,
    administrator: str,
    promoted_at: str,
    root: Path | None = None,
) -> dict[str, Any]:
    metadata = load_outlook_attachment(document_id, attachment_id, root=root)
    metadata["promotion_status"] = "promoted"
    metadata["canonical_record_reference"] = str(canonical_record_reference)
    metadata["promotion_timestamp"] = str(promoted_at)
    metadata["promotion_administrator"] = str(administrator)
    _write_json_atomic(_metadata_path(document_id, attachment_id, root), metadata)
    return metadata
