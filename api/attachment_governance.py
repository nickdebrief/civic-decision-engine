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
    validate_archive_message_promotion,
)


ATTACHMENT_GOVERNANCE_VERSION = "stage42-unified-attachment-v1"
DEFAULT_MAX_ATTACHMENT_BYTES = 128 * 1024 * 1024
ATTACHMENT_STORE_DIRECTORY = ".governed_attachments"
LEGACY_ATTACHMENT_STORE_DIRECTORY = ".outlook_archive_attachments"
ATTACHMENT_ID_RE = re.compile(r"^ATT-[A-F0-9]{24}$")


class AttachmentGovernanceError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class AttachmentPromotionContext:
    attachment: dict[str, Any]
    message_context: OutlookArchivePromotionContext
    source_path: Path


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def max_attachment_bytes() -> int:
    raw = os.getenv("CDE_MAX_ATTACHMENT_BYTES", "").strip()
    if not raw:
        raw = os.getenv("CDE_MAX_OUTLOOK_ATTACHMENT_BYTES", "").strip()
    try:
        value = int(raw) if raw else DEFAULT_MAX_ATTACHMENT_BYTES
    except ValueError as exc:
        raise AttachmentGovernanceError("attachment_limit_invalid") from exc
    if value <= 0:
        raise AttachmentGovernanceError("attachment_limit_invalid")
    return value


def _safe_component(value: Any, code: str) -> str:
    text = str(value or "").strip()
    if not text or text in {".", ".."} or Path(text).name != text:
        raise AttachmentGovernanceError(code)
    return text


def _safe_filename(value: Any) -> str:
    filename = str(value or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not filename or filename in {".", ".."}:
        raise AttachmentGovernanceError("attachment_filename_invalid")
    return filename[:512]


def _safe_source_identifier(value: Any) -> str:
    identifier = str(value or "").strip()
    if not identifier or len(identifier) > 1024 or "\x00" in identifier:
        raise AttachmentGovernanceError("attachment_source_identifier_invalid")
    return identifier


def _store_root(root: Path | None = None) -> Path:
    path = (root or intake_root()) / ATTACHMENT_STORE_DIRECTORY
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        path.chmod(0o700)
    except OSError:
        pass
    return path


def _objects_root(root: Path | None = None) -> Path:
    path = _store_root(root) / "objects"
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


def _occurrences_root(root: Path | None = None) -> Path:
    path = _store_root(root) / "occurrences"
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


def _object_root(attachment_id: str, root: Path | None = None) -> Path:
    if not ATTACHMENT_ID_RE.fullmatch(str(attachment_id or "")):
        raise AttachmentGovernanceError("attachment_id_invalid")
    return _objects_root(root) / attachment_id


def _object_metadata_path(attachment_id: str, root: Path | None = None) -> Path:
    return _object_root(attachment_id, root) / "metadata.json"


def _object_source_path(attachment_id: str, root: Path | None = None) -> Path:
    return _object_root(attachment_id, root) / "original.bin"


def _archive_occurrence_root(document_id: str, root: Path | None = None) -> Path:
    archive_id = _safe_component(document_id, "attachment_archive_invalid")
    path = _occurrences_root(root) / archive_id
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


def _legacy_attachment_root(
    document_id: str, attachment_id: str, root: Path | None = None
) -> Path:
    archive_id = _safe_component(document_id, "attachment_archive_invalid")
    if not ATTACHMENT_ID_RE.fullmatch(str(attachment_id or "")):
        raise AttachmentGovernanceError("attachment_id_invalid")
    return (root or intake_root()) / LEGACY_ATTACHMENT_STORE_DIRECTORY / archive_id / attachment_id


def _hash_file(path: Path, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
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


def _read_json(path: Path, error_code: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AttachmentGovernanceError(error_code) from exc
    if not isinstance(value, dict):
        raise AttachmentGovernanceError(error_code)
    return value


def _attachment_id(sha256_hash: str) -> str:
    return "ATT-" + sha256_hash[:24].upper()


def _occurrence_id(provenance: dict[str, Any]) -> str:
    fields = (
        "attachment_id",
        "archive_id",
        "folder_projection_id",
        "thread_projection_id",
        "message_projection_id",
        "source_attachment_identifier",
        "acquisition_source",
    )
    seed = "\0".join(str(provenance.get(field) or "") for field in fields)
    return "OCC-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24].upper()


def _extension(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    return suffix[1:] if suffix.startswith(".") else suffix


def _occurrence_paths_for_attachment(
    attachment_id: str, root: Path | None = None
) -> list[Path]:
    return sorted(_occurrences_root(root).glob(f"*/{attachment_id}/OCC-*.json"))


def _load_occurrences(attachment_id: str, root: Path | None = None) -> list[dict[str, Any]]:
    occurrences: list[dict[str, Any]] = []
    for path in _occurrence_paths_for_attachment(attachment_id, root):
        try:
            occurrence = _read_json(path, "attachment_occurrence_metadata_invalid")
        except AttachmentGovernanceError:
            continue
        if occurrence.get("attachment_id") == attachment_id:
            occurrences.append(occurrence)
    return sorted(
        occurrences,
        key=lambda item: (
            str(item.get("archive_id") or ""),
            str(item.get("message_projection_id") or ""),
            str(item.get("source_attachment_identifier") or ""),
        ),
    )


def _decorate_attachment(
    metadata: dict[str, Any], document_id: str, root: Path | None = None
) -> dict[str, Any]:
    attachment_id = str(metadata.get("attachment_id") or "")
    occurrences = _load_occurrences(attachment_id, root)
    archive_occurrences = [
        occurrence
        for occurrence in occurrences
        if str(occurrence.get("archive_id") or "") == str(document_id)
    ]
    if not archive_occurrences:
        raise AttachmentGovernanceError("attachment_not_found")
    primary = archive_occurrences[0]
    result = dict(metadata)
    result["provenance"] = primary
    result["provenance_records"] = occurrences
    result["duplicate_references"] = [
        {
            "archive_id": occurrence.get("archive_id"),
            "folder_projection_id": occurrence.get("folder_projection_id"),
            "thread_projection_id": occurrence.get("thread_projection_id"),
            "message_projection_id": occurrence.get("message_projection_id"),
            "acquisition_source": occurrence.get("acquisition_source"),
        }
        for occurrence in occurrences
        if occurrence.get("occurrence_id") != primary.get("occurrence_id")
    ]
    result["occurrence_count"] = len(occurrences)
    result["filename"] = primary.get("filename") or result.get("filename")
    result["extension"] = _extension(str(result.get("filename") or ""))
    result["mime_type"] = primary.get("mime_type") or result.get("mime_type")
    result["extraction_timestamp"] = primary.get("extraction_timestamp")
    result["acquisition_timestamp"] = primary.get("acquisition_timestamp")
    result["acquisition_source"] = primary.get("acquisition_source")
    return result


def govern_attachment_bytes(
    context: OutlookArchivePromotionContext,
    *,
    data: bytes,
    filename: str,
    mime_type: str,
    source_attachment_id: str,
    attachment_index: int | None = None,
    content_id: str | None = None,
    inline_status: bool = False,
    source_metadata: dict[str, Any] | None = None,
    acquisition_source: str = "outlook_archive",
    extracted_at: str | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Admit bytes once and record immutable source-specific provenance separately."""

    if not isinstance(data, bytes) or not data:
        raise AttachmentGovernanceError("attachment_empty")
    if len(data) > max_attachment_bytes():
        raise AttachmentGovernanceError("attachment_too_large")
    safe_filename = _safe_filename(filename)
    safe_source_id = _safe_source_identifier(source_attachment_id)
    normalized_mime = str(mime_type or "application/octet-stream").strip().lower()
    if not normalized_mime or len(normalized_mime) > 255 or any(
        character in normalized_mime for character in "\r\n"
    ):
        raise AttachmentGovernanceError("attachment_mime_type_invalid")

    sha256_hash = hashlib.sha256(data).hexdigest()
    sha512_hash = hashlib.sha512(data).hexdigest()
    attachment_id = _attachment_id(sha256_hash)
    object_root = _object_root(attachment_id, root)
    metadata_path = object_root / "metadata.json"
    content_path = object_root / "original.bin"
    object_root.mkdir(mode=0o700, parents=True, exist_ok=True)

    if metadata_path.exists() or content_path.exists():
        metadata = _read_json(metadata_path, "attachment_metadata_invalid")
        if (
            metadata.get("attachment_id") != attachment_id
            or metadata.get("sha256_hash") != sha256_hash
            or metadata.get("sha512_hash") != sha512_hash
            or not content_path.is_file()
            or content_path.stat().st_size != len(data)
            or _hash_file(content_path, "sha256") != sha256_hash
            or _hash_file(content_path, "sha512") != sha512_hash
        ):
            raise AttachmentGovernanceError("attachment_identity_collision")
    else:
        try:
            fd = os.open(content_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            metadata = {
                "attachment_id": attachment_id,
                "governance_version": ATTACHMENT_GOVERNANCE_VERSION,
                "filename": safe_filename,
                "extension": _extension(safe_filename),
                "mime_type": normalized_mime,
                "file_size_bytes": len(data),
                "sha256_hash": sha256_hash,
                "sha512_hash": sha512_hash,
                "evidence_status": "governed_private_evidence",
                "extraction_status": "extracted",
                "hash_verification_status": "verified",
                "promotion_status": "eligible",
                "canonical_record_reference": None,
                "promotion_history": [],
            }
            _write_json_atomic(metadata_path, metadata)
        except Exception:
            metadata_path.unlink(missing_ok=True)
            content_path.unlink(missing_ok=True)
            try:
                object_root.rmdir()
            except OSError:
                pass
            raise

    message = context.message
    message_provenance = message.get("provenance")
    message_provenance = message_provenance if isinstance(message_provenance, dict) else {}
    archive_id = str(context.document.get("intake_id") or "")
    folder_id = str(message.get("folder_id") or "")
    projection_id = str(message.get("projection_id") or "")
    extracted = str(extracted_at or _utc_now())
    acquisition_timestamp = str(
        message_provenance.get("acquisition_timestamp")
        or context.document.get("upload_timestamp")
        or context.document.get("uploaded_at")
        or extracted
    )
    occurrence = {
        "attachment_id": attachment_id,
        "archive_id": archive_id,
        "document_identifier": context.document.get("document_identifier"),
        "folder_projection_id": folder_id,
        "folder_path": message.get("folder_path"),
        "thread_projection_id": message.get("thread_id") or message.get("conversation_id"),
        "message_projection_id": projection_id,
        "message_identifier": message.get("message_id"),
        "source_attachment_identifier": safe_source_id,
        "extraction_job": context.job.get("job_id"),
        "parser_version": message_provenance.get("parser_version"),
        "projection_version": context.projection.get("projection_version"),
        "source_archive_sha256": context.document.get("sha256_hash"),
        "acquisition_source": str(acquisition_source or "archive"),
        "archive_source": str(acquisition_source or "archive"),
        "acquisition_timestamp": acquisition_timestamp,
        "extraction_timestamp": extracted,
        "filename": safe_filename,
        "mime_type": normalized_mime,
        "content_id": str(content_id or "") or None,
        "inline_status": bool(inline_status),
    }
    normalized_attachment_index = int(attachment_index or 1)
    try:
        from api.email_attachment_preservation import (
            preserve_attachment_bytes,
            record_attachment_failure,
        )

        source_object_id = f"{archive_id}:message:{projection_id}"
        try:
            published_relationship = preserve_attachment_bytes(
                source_document=context.document,
                source_email_object_id=source_object_id,
                source_email_kind="projected_message",
                attachment_index=normalized_attachment_index,
                data=data,
                original_filename=safe_filename,
                display_title=safe_filename,
                mime_type=normalized_mime,
                source_attachment_identifier=safe_source_id,
                source_message_identifier=message.get("message_id"),
                source_archive_identifier=archive_id,
                source_folder_path=message.get("folder_path"),
                source_pathway=str(acquisition_source or "archive"),
                content_id=content_id,
                inline_status=inline_status,
                source_metadata={
                    "governed_attachment_id": attachment_id,
                    "folder_projection_id": folder_id,
                    "thread_projection_id": message.get("thread_id") or message.get("conversation_id"),
                    "message_projection_id": projection_id,
                    "extraction_job": context.job.get("job_id"),
                    "parser_version": message_provenance.get("parser_version"),
                    "projection_version": context.projection.get("projection_version"),
                    "source_message_identifier": message.get("source_identifier"),
                    "source_uid": message.get("source_uid"),
                    "uidvalidity": message.get("uidvalidity"),
                    "source_mailbox": message.get("source_mailbox"),
                    "outlook_entry_id": message.get("entry_id") or message.get("store_entry_id"),
                    **dict(source_metadata or {}),
                },
                extracted_at=extracted,
                root=root,
            )
        except Exception as exc:
            published_relationship = record_attachment_failure(
                source_document=context.document,
                source_email_object_id=source_object_id,
                source_email_kind="projected_message",
                attachment_index=normalized_attachment_index,
                display_title=safe_filename,
                source_pathway=str(acquisition_source or "archive"),
                failure_reason=str(exc),
                original_filename=safe_filename,
                mime_type=normalized_mime,
                source_attachment_identifier=safe_source_id,
                source_message_identifier=message.get("message_id"),
                source_archive_identifier=archive_id,
                source_folder_path=message.get("folder_path"),
                content_id=content_id,
                inline_status=inline_status,
                source_metadata={
                    "governed_attachment_id": attachment_id,
                    **dict(source_metadata or {}),
                },
                sha256_hash=sha256_hash,
                created_at=extracted,
                root=root,
            )
        occurrence["published_document_relationship_id"] = published_relationship.get("relationship_id")
        occurrence["attachment_document_id"] = published_relationship.get("attachment_document_id")
        occurrence["published_document_preservation_status"] = published_relationship.get("extraction_status")
    except Exception as exc:
        occurrence["published_document_preservation_status"] = "failed"
        occurrence["published_document_preservation_failure"] = str(exc)
    occurrence["occurrence_id"] = _occurrence_id(occurrence)
    occurrence_path = (
        _archive_occurrence_root(archive_id, root)
        / attachment_id
        / f'{occurrence["occurrence_id"]}.json'
    )
    if occurrence_path.exists():
        existing_occurrence = _read_json(
            occurrence_path, "attachment_occurrence_metadata_invalid"
        )
        if existing_occurrence != occurrence:
            raise AttachmentGovernanceError("attachment_occurrence_identity_collision")
    else:
        _write_json_atomic(occurrence_path, occurrence)
    return _decorate_attachment(metadata, archive_id, root)


def load_attachment(
    document_id: str, attachment_id: str, *, root: Path | None = None
) -> dict[str, Any]:
    metadata_path = _object_metadata_path(attachment_id, root)
    if metadata_path.is_file():
        metadata = _read_json(metadata_path, "attachment_metadata_invalid")
        if metadata.get("attachment_id") != attachment_id:
            raise AttachmentGovernanceError("attachment_metadata_invalid")
        return _decorate_attachment(metadata, document_id, root)

    legacy_root = _legacy_attachment_root(document_id, attachment_id, root)
    legacy_metadata_path = legacy_root / "metadata.json"
    if not legacy_metadata_path.is_file():
        raise AttachmentGovernanceError("attachment_not_found")
    metadata = _read_json(legacy_metadata_path, "attachment_metadata_invalid")
    if metadata.get("attachment_id") != attachment_id:
        raise AttachmentGovernanceError("attachment_metadata_invalid")
    metadata.setdefault("sha512_hash", None)
    metadata.setdefault("extension", _extension(str(metadata.get("filename") or "")))
    metadata.setdefault("evidence_status", "governed_private_evidence")
    metadata.setdefault("promotion_history", [])
    metadata.setdefault("provenance_records", [metadata.get("provenance") or {}])
    metadata.setdefault("duplicate_references", [])
    metadata.setdefault("occurrence_count", 1)
    metadata.setdefault("acquisition_source", (metadata.get("provenance") or {}).get("archive_source", "outlook_archive"))
    return metadata


def list_attachments(
    document_id: str,
    *,
    message_id: str | None = None,
    root: Path | None = None,
) -> list[dict[str, Any]]:
    archive_root = _archive_occurrence_root(document_id, root)
    attachment_ids = sorted(
        {
            path.parent.name
            for path in archive_root.glob("ATT-*/OCC-*.json")
            if ATTACHMENT_ID_RE.fullmatch(path.parent.name)
        }
    )
    attachments: list[dict[str, Any]] = []
    for attachment_id in attachment_ids:
        try:
            metadata = load_attachment(document_id, attachment_id, root=root)
        except AttachmentGovernanceError:
            continue
        occurrences = [
            occurrence
            for occurrence in metadata.get("provenance_records") or []
            if str(occurrence.get("archive_id") or "") == str(document_id)
        ]
        if message_id and not any(
            str(occurrence.get("message_projection_id") or "") == str(message_id)
            for occurrence in occurrences
        ):
            continue
        if message_id:
            metadata["provenance"] = next(
                occurrence
                for occurrence in occurrences
                if str(occurrence.get("message_projection_id") or "") == str(message_id)
            )
        attachments.append(metadata)

    legacy_archive = (root or intake_root()) / LEGACY_ATTACHMENT_STORE_DIRECTORY / str(document_id)
    if legacy_archive.is_dir():
        known = {item["attachment_id"] for item in attachments}
        for path in sorted(legacy_archive.glob("ATT-*/metadata.json")):
            if path.parent.name in known:
                continue
            try:
                metadata = load_attachment(document_id, path.parent.name, root=root)
            except AttachmentGovernanceError:
                continue
            provenance = metadata.get("provenance") or {}
            if message_id and str(provenance.get("message_projection_id") or "") != str(message_id):
                continue
            attachments.append(metadata)
    return sorted(attachments, key=lambda item: str(item.get("attachment_id") or ""))


def _source_path_for_attachment(
    document_id: str, attachment_id: str, root: Path | None = None
) -> Path:
    source_path = _object_source_path(attachment_id, root)
    if source_path.is_file():
        return source_path
    return _legacy_attachment_root(document_id, attachment_id, root) / "original.bin"


def validate_attachment_promotion(
    document_id: str, attachment_id: str, *, root: Path | None = None
) -> AttachmentPromotionContext:
    attachment = load_attachment(document_id, attachment_id, root=root)
    provenance = attachment.get("provenance")
    if not isinstance(provenance, dict):
        raise AttachmentGovernanceError("attachment_provenance_missing")
    message_id = str(provenance.get("message_projection_id") or "")
    if not message_id:
        raise AttachmentGovernanceError("attachment_provenance_missing")
    try:
        context = validate_archive_message_promotion(document_id, message_id, root=root)
    except OutlookArchivePromotionError as exc:
        raise AttachmentGovernanceError(exc.code) from exc
    required_matches = {
        "archive_id": context.document.get("intake_id"),
        "folder_projection_id": context.message.get("folder_id"),
        "message_projection_id": context.message.get("projection_id"),
        "extraction_job": context.job.get("job_id"),
        "projection_version": context.projection.get("projection_version"),
        "source_archive_sha256": context.document.get("sha256_hash"),
    }
    if any(
        str(provenance.get(key) or "") != str(value or "")
        for key, value in required_matches.items()
    ):
        raise AttachmentGovernanceError("attachment_provenance_invalid")
    source_path = _source_path_for_attachment(document_id, attachment_id, root)
    if not source_path.is_file():
        raise AttachmentGovernanceError("attachment_content_unavailable")
    if attachment.get("extraction_status") != "extracted":
        raise AttachmentGovernanceError("attachment_extraction_incomplete")
    if attachment.get("hash_verification_status") != "verified":
        raise AttachmentGovernanceError("attachment_hash_unverified")
    if _hash_file(source_path, "sha256") != attachment.get("sha256_hash"):
        raise AttachmentGovernanceError("attachment_hash_verification_failed")
    expected_sha512 = attachment.get("sha512_hash")
    if expected_sha512 and _hash_file(source_path, "sha512") != expected_sha512:
        raise AttachmentGovernanceError("attachment_hash_verification_failed")
    if source_path.stat().st_size != int(attachment.get("file_size_bytes") or -1):
        raise AttachmentGovernanceError("attachment_size_verification_failed")
    return AttachmentPromotionContext(
        attachment=attachment,
        message_context=context,
        source_path=source_path,
    )


def build_attachment_promotion_provenance(
    context: AttachmentPromotionContext,
    *,
    administrator: str,
    promoted_at: str | None = None,
) -> dict[str, Any]:
    administrator = str(administrator or "").strip()
    if not administrator:
        raise AttachmentGovernanceError("attachment_administrator_missing")
    attachment = context.attachment
    provenance = attachment["provenance"]
    return {
        "promotion_version": ATTACHMENT_GOVERNANCE_VERSION,
        "archive_id": provenance["archive_id"],
        "folder_projection_id": provenance["folder_projection_id"],
        "thread_projection_id": provenance.get("thread_projection_id"),
        "message_projection_id": provenance["message_projection_id"],
        "message_identifier": provenance.get("message_identifier"),
        "attachment_id": attachment["attachment_id"],
        "source_attachment_identifier": provenance["source_attachment_identifier"],
        "attachment_filename": attachment["filename"],
        "sha256_hash": attachment["sha256_hash"],
        "sha512_hash": attachment.get("sha512_hash"),
        "file_size_bytes": attachment["file_size_bytes"],
        "mime_type": attachment["mime_type"],
        "acquisition_source": provenance.get("acquisition_source"),
        "acquisition_timestamp": provenance.get("acquisition_timestamp"),
        "extraction_job": provenance["extraction_job"],
        "extraction_timestamp": attachment["extraction_timestamp"],
        "promotion_timestamp": str(promoted_at or _utc_now()),
        "administrator": administrator,
        "projection_version": provenance["projection_version"],
        "source_archive_sha256": provenance["source_archive_sha256"],
        "provenance_chain": [
            provenance["archive_id"],
            provenance["folder_projection_id"],
            *([str(provenance["thread_projection_id"])] if provenance.get("thread_projection_id") else []),
            provenance["message_projection_id"],
            attachment["attachment_id"],
        ],
        "attachment_provenance_records": attachment.get("provenance_records") or [provenance],
    }


def mark_attachment_promoted(
    document_id: str,
    attachment_id: str,
    *,
    canonical_record_reference: str,
    administrator: str,
    promoted_at: str,
    root: Path | None = None,
) -> dict[str, Any]:
    metadata_path = _object_metadata_path(attachment_id, root)
    if not metadata_path.is_file():
        legacy_path = _legacy_attachment_root(document_id, attachment_id, root) / "metadata.json"
        metadata = load_attachment(document_id, attachment_id, root=root)
        metadata["promotion_status"] = "promoted"
        metadata["canonical_record_reference"] = str(canonical_record_reference)
        metadata["promotion_timestamp"] = str(promoted_at)
        metadata["promotion_administrator"] = str(administrator)
        metadata.pop("provenance_records", None)
        metadata.pop("duplicate_references", None)
        metadata.pop("occurrence_count", None)
        metadata.pop("acquisition_source", None)
        _write_json_atomic(legacy_path, metadata)
        return load_attachment(document_id, attachment_id, root=root)

    metadata = _read_json(metadata_path, "attachment_metadata_invalid")
    history = list(metadata.get("promotion_history") or [])
    event = {
        "canonical_record_reference": str(canonical_record_reference),
        "administrator": str(administrator),
        "promotion_timestamp": str(promoted_at),
        "archive_id": str(document_id),
    }
    if event not in history:
        history.append(event)
    metadata["promotion_history"] = history
    metadata["promotion_status"] = "promoted"
    metadata["canonical_record_reference"] = str(canonical_record_reference)
    metadata["promotion_timestamp"] = str(promoted_at)
    metadata["promotion_administrator"] = str(administrator)
    _write_json_atomic(metadata_path, metadata)
    return load_attachment(document_id, attachment_id, root=root)
