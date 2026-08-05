"""Backward-compatible Stage 39E facade for unified attachment governance."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from api.attachment_governance import (
    ATTACHMENT_GOVERNANCE_VERSION,
    ATTACHMENT_ID_RE,
    DEFAULT_MAX_ATTACHMENT_BYTES,
    LEGACY_ATTACHMENT_STORE_DIRECTORY,
    AttachmentGovernanceError,
    AttachmentPromotionContext,
    build_attachment_promotion_provenance,
    govern_attachment_bytes,
    list_attachments,
    load_attachment,
    mark_attachment_promoted,
    max_attachment_bytes,
    validate_attachment_promotion,
)
from api.outlook_archive_promotion import (
    OutlookArchivePromotionError,
    validate_outlook_message_promotion,
)


OUTLOOK_ATTACHMENT_GOVERNANCE_VERSION = ATTACHMENT_GOVERNANCE_VERSION
DEFAULT_MAX_OUTLOOK_ATTACHMENT_BYTES = DEFAULT_MAX_ATTACHMENT_BYTES
ATTACHMENT_STORE_DIRECTORY = LEGACY_ATTACHMENT_STORE_DIRECTORY
OutlookAttachmentGovernanceError = AttachmentGovernanceError
OutlookAttachmentPromotionContext = AttachmentPromotionContext


def _raise_legacy_error(exc: AttachmentGovernanceError) -> None:
    code = exc.code
    if code.startswith("attachment_"):
        code = "outlook_" + code
    raise AttachmentGovernanceError(code) from exc


def max_outlook_attachment_bytes() -> int:
    try:
        return max_attachment_bytes()
    except AttachmentGovernanceError as exc:
        _raise_legacy_error(exc)


def govern_archive_attachment_bytes(
    context,
    *,
    data: bytes,
    filename: str,
    mime_type: str,
    source_attachment_id: str,
    attachment_index: int | None = None,
    content_id: str | None = None,
    inline_status: bool = False,
    source_metadata: dict[str, Any] | None = None,
    archive_source: str = "outlook_archive",
    extracted_at: str | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    try:
        return govern_attachment_bytes(
            context,
            data=data,
            filename=filename,
            mime_type=mime_type,
            source_attachment_id=source_attachment_id,
            attachment_index=attachment_index,
            content_id=content_id,
            inline_status=inline_status,
            source_metadata=source_metadata,
            acquisition_source=archive_source,
            extracted_at=extracted_at,
            root=root,
        )
    except AttachmentGovernanceError as exc:
        _raise_legacy_error(exc)


def govern_outlook_attachment_bytes(
    document_id: str,
    message_id: str,
    *,
    data: bytes,
    filename: str,
    mime_type: str,
    source_attachment_id: str,
    attachment_index: int | None = None,
    content_id: str | None = None,
    inline_status: bool = False,
    source_metadata: dict[str, Any] | None = None,
    extracted_at: str | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    try:
        context = validate_outlook_message_promotion(document_id, message_id, root=root)
    except OutlookArchivePromotionError as exc:
        raise AttachmentGovernanceError(exc.code) from exc
    try:
        return govern_attachment_bytes(
            context,
            data=data,
            filename=filename,
            mime_type=mime_type,
            source_attachment_id=source_attachment_id,
            attachment_index=attachment_index,
            content_id=content_id,
            inline_status=inline_status,
            source_metadata=source_metadata,
            acquisition_source="outlook_archive",
            extracted_at=extracted_at,
            root=root,
        )
    except AttachmentGovernanceError as exc:
        _raise_legacy_error(exc)


load_outlook_attachment = load_attachment
list_outlook_attachments = list_attachments


def validate_outlook_attachment_promotion(
    document_id: str, attachment_id: str, *, root: Path | None = None
) -> AttachmentPromotionContext:
    try:
        return validate_attachment_promotion(document_id, attachment_id, root=root)
    except AttachmentGovernanceError as exc:
        _raise_legacy_error(exc)


validate_archive_attachment_promotion = validate_attachment_promotion
build_outlook_attachment_promotion_provenance = build_attachment_promotion_provenance
mark_outlook_attachment_promoted = mark_attachment_promoted


__all__ = [
    "ATTACHMENT_ID_RE",
    "ATTACHMENT_STORE_DIRECTORY",
    "DEFAULT_MAX_OUTLOOK_ATTACHMENT_BYTES",
    "OUTLOOK_ATTACHMENT_GOVERNANCE_VERSION",
    "OutlookAttachmentGovernanceError",
    "OutlookAttachmentPromotionContext",
    "build_outlook_attachment_promotion_provenance",
    "govern_archive_attachment_bytes",
    "govern_outlook_attachment_bytes",
    "list_outlook_attachments",
    "load_outlook_attachment",
    "mark_outlook_attachment_promoted",
    "max_outlook_attachment_bytes",
    "validate_archive_attachment_promotion",
    "validate_outlook_attachment_promotion",
]
