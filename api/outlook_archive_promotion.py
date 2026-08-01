from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from api.document_intake import (
    intake_root,
    is_gmail_takeout_document,
    is_imap_acquisition_document,
    is_outlook_archive_document,
    load_pending_document,
)
from api.outlook_archive_jobs import load_archive_job
from api.outlook_archive_projections import (
    get_projection_folder,
    get_projection_message,
    load_outlook_archive_projection,
)


OUTLOOK_ARCHIVE_PROMOTION_VERSION = "stage39d-promotion-v1"
ELIGIBLE_PROJECTION_STATES = {"projected", "rebuilt"}


class OutlookArchivePromotionError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class OutlookArchivePromotionContext:
    document: dict[str, Any]
    projection: dict[str, Any]
    folder: dict[str, Any]
    message: dict[str, Any]
    job: dict[str, Any]


def _required_text(value: Any, code: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise OutlookArchivePromotionError(code)
    return text


def validate_outlook_message_promotion(
    document_id: str,
    message_id: str,
    *,
    root: Path | None = None,
) -> OutlookArchivePromotionContext:
    storage_root = root or intake_root()
    try:
        document = load_pending_document(document_id, root=storage_root)
    except ValueError as exc:
        raise OutlookArchivePromotionError("outlook_archive_promotion_archive_unavailable") from exc
    if not is_outlook_archive_document(document):
        raise OutlookArchivePromotionError("outlook_archive_promotion_archive_invalid")

    try:
        projection = load_outlook_archive_projection(document_id, root=storage_root)
    except ValueError as exc:
        raise OutlookArchivePromotionError("outlook_archive_promotion_projection_unavailable") from exc
    if str(projection.get("projection_state") or "") not in ELIGIBLE_PROJECTION_STATES:
        raise OutlookArchivePromotionError("outlook_archive_promotion_projection_incomplete")
    if str(projection.get("archive_id") or "") != str(document.get("intake_id") or ""):
        raise OutlookArchivePromotionError("outlook_archive_promotion_projection_invalid")
    _required_text(
        projection.get("projection_version"),
        "outlook_archive_promotion_provenance_missing",
    )

    try:
        message = get_projection_message(document_id, message_id, root=storage_root)
    except ValueError as exc:
        raise OutlookArchivePromotionError("outlook_archive_promotion_message_unavailable") from exc
    provenance = message.get("provenance")
    if not isinstance(provenance, dict):
        raise OutlookArchivePromotionError("outlook_archive_promotion_provenance_missing")

    projection_id = _required_text(
        message.get("projection_id"),
        "outlook_archive_promotion_provenance_missing",
    )
    if projection_id != str(message_id):
        raise OutlookArchivePromotionError("outlook_archive_promotion_projection_invalid")
    folder_id = _required_text(
        message.get("folder_id"),
        "outlook_archive_promotion_provenance_missing",
    )
    try:
        folder = get_projection_folder(document_id, folder_id, root=storage_root)
    except ValueError as exc:
        raise OutlookArchivePromotionError("outlook_archive_promotion_projection_invalid") from exc

    archive_id = _required_text(
        provenance.get("archive_id"),
        "outlook_archive_promotion_provenance_missing",
    )
    job_id = _required_text(
        provenance.get("job_id") or projection.get("job_id"),
        "outlook_archive_promotion_provenance_missing",
    )
    _required_text(
        provenance.get("source_identifier"),
        "outlook_archive_promotion_provenance_missing",
    )
    _required_text(
        provenance.get("source_folder") or message.get("folder_path"),
        "outlook_archive_promotion_provenance_missing",
    )
    if archive_id != str(document.get("intake_id") or ""):
        raise OutlookArchivePromotionError("outlook_archive_promotion_projection_invalid")
    if job_id != str(projection.get("job_id") or ""):
        raise OutlookArchivePromotionError("outlook_archive_promotion_projection_invalid")

    try:
        job = load_archive_job(job_id, root=storage_root)
    except ValueError as exc:
        raise OutlookArchivePromotionError("outlook_archive_promotion_extraction_incomplete") from exc
    if str(job.get("document_id") or "") != str(document.get("intake_id") or ""):
        raise OutlookArchivePromotionError("outlook_archive_promotion_projection_invalid")
    if str(job.get("status") or "") != "completed":
        raise OutlookArchivePromotionError("outlook_archive_promotion_extraction_incomplete")
    inspection = job.get("inspection")
    if not isinstance(inspection, dict) or not inspection.get("inspection_complete"):
        raise OutlookArchivePromotionError("outlook_archive_promotion_extraction_incomplete")

    _required_text(
        document.get("sha256_hash"),
        "outlook_archive_promotion_source_hash_missing",
    )
    return OutlookArchivePromotionContext(
        document=document,
        projection=projection,
        folder=folder,
        message=message,
        job=job,
    )


def validate_archive_message_promotion(
    document_id: str,
    message_id: str,
    *,
    root: Path | None = None,
) -> OutlookArchivePromotionContext:
    """Dispatch promotion validation without changing either source model."""

    storage_root = root or intake_root()
    try:
        document = load_pending_document(document_id, root=storage_root)
    except ValueError as exc:
        raise OutlookArchivePromotionError("archive_promotion_archive_unavailable") from exc
    if is_gmail_takeout_document(document):
        from api.gmail_takeout import validate_gmail_message_promotion

        return validate_gmail_message_promotion(document_id, message_id, root=storage_root)
    if is_imap_acquisition_document(document):
        from api.imap_acquisition import validate_imap_message_promotion

        return validate_imap_message_promotion(document_id, message_id, root=storage_root)
    return validate_outlook_message_promotion(document_id, message_id, root=storage_root)


def build_outlook_message_promotion_provenance(
    context: OutlookArchivePromotionContext,
    *,
    administrator: str,
    promoted_at: str | None = None,
) -> dict[str, Any]:
    message = context.message
    projection = context.projection
    provenance = message["provenance"]
    timestamp = promoted_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )
    result = {
        "promotion_version": OUTLOOK_ARCHIVE_PROMOTION_VERSION,
        "archive_id": str(context.document["intake_id"]),
        "folder_projection_id": str(message["folder_id"]),
        "message_projection_id": str(message["projection_id"]),
        "message_identifier": str(
            message.get("message_id") or provenance.get("source_identifier") or ""
        ),
        "extraction_job": str(context.job["job_id"]),
        "promotion_timestamp": timestamp,
        "administrator": _required_text(
            administrator,
            "outlook_archive_promotion_administrator_missing",
        ),
        "source_hash": str(context.document["sha256_hash"]),
        "projection_version": str(projection["projection_version"]),
    }
    if str(projection.get("source_format") or "") == "gmail_takeout":
        result.update(
            {
                "archive_source": "gmail_takeout",
                "label_projection_ids": list(message.get("label_ids") or []),
                "thread_identifier": message.get("thread_id"),
                "provenance_chain": [
                    str(context.document["intake_id"]),
                    *[str(value) for value in message.get("label_ids") or []],
                    str(message.get("thread_id") or ""),
                    str(message["projection_id"]),
                ],
            }
        )
    elif str(projection.get("source_format") or "") == "imap_acquisition":
        result.update(
            {
                "archive_source": "imap_acquisition",
                "acquisition_identifier": projection.get("acquisition_id"),
                "imap_uid": message.get("source_uid"),
                "uidvalidity": message.get("uidvalidity"),
                "thread_identifier": message.get("thread_id"),
                "provenance_chain": [
                    str(projection.get("acquisition_id") or ""),
                    str(message.get("folder_id") or ""),
                    str(message.get("thread_id") or ""),
                    str(message.get("projection_id") or ""),
                ],
            }
        )
    return result
