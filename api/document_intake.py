from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path, PurePath
from typing import Any


DEFAULT_INTAKE_ROOT = Path("/data/attachments/intake/pending")
DEFAULT_MAX_BYTES = 25 * 1024 * 1024
VALID_VISIBILITY = {"private", "restricted"}
INTAKE_STATUSES = {
    "pending",
    "under_review",
    "approved",
    "published",
    "archived",
    "rejected",
}
STATUS_LABELS = {
    "pending": "Pending Intake",
    "under_review": "Under Review",
    "approved": "Approved",
    "published": "Published",
    "archived": "Archived",
    "rejected": "Rejected",
}
VALID_STATUS_TRANSITIONS = {
    "pending": {"under_review"},
    "under_review": {"approved", "rejected"},
    "approved": {"published", "archived"},
    "published": {"archived"},
    "rejected": {"archived"},
    "archived": set(),
}
_SAFE_ID_RE = re.compile(r"^[a-f0-9]{64}$")


def intake_root() -> Path:
    return Path(os.getenv("CDE_DOCUMENT_INTAKE_ROOT", str(DEFAULT_INTAKE_ROOT)))


def intake_max_bytes() -> int:
    raw = os.getenv("CDE_DOCUMENT_INTAKE_MAX_BYTES")
    if raw is None:
        return DEFAULT_MAX_BYTES
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError("document_intake_size_limit_invalid") from exc
    if value < 1:
        raise ValueError("document_intake_size_limit_invalid")
    return value


def validate_pdf(data: bytes, content_type: str | None) -> str:
    normalized = (content_type or "").split(";", 1)[0].strip().lower()
    if normalized != "application/pdf":
        raise ValueError("document_intake_file_type_not_allowed")
    if not data:
        raise ValueError("document_intake_file_required")
    if len(data) > intake_max_bytes():
        raise ValueError("document_intake_file_too_large")
    if not data.startswith(b"%PDF-"):
        raise ValueError("document_intake_invalid_pdf")
    return normalized


def store_pending_document(
    *,
    data: bytes,
    original_filename: str,
    content_type: str | None,
    title: str,
    institution_source: str,
    document_date: str,
    category: str,
    description: str,
    visibility: str,
    notes: str,
    reference_identifier: str | None = None,
    uploaded_at: str | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    normalized_type = validate_pdf(data, content_type)
    filename = PurePath(original_filename or "document.pdf").name
    if not filename.lower().endswith(".pdf"):
        raise ValueError("document_intake_file_type_not_allowed")

    required = {
        "title": title,
        "institution_source": institution_source,
        "document_date": document_date,
        "category": category,
        "description": description,
        "visibility": visibility,
        "notes": notes,
    }
    normalized = {key: str(value or "").strip() for key, value in required.items()}
    if any(not value for value in normalized.values()):
        raise ValueError("document_intake_metadata_required")
    if normalized["visibility"] not in VALID_VISIBILITY:
        raise ValueError("document_intake_visibility_invalid")
    try:
        datetime.strptime(normalized["document_date"], "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError("document_intake_document_date_invalid") from exc

    digest = hashlib.sha256(data).hexdigest()
    destination_root = (root or intake_root()).resolve(strict=False)
    destination_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    item_dir = destination_root / digest
    if item_dir.exists():
        raise ValueError("document_intake_duplicate")
    item_dir.mkdir(mode=0o700)

    stored_filename = f"pending-{digest}.pdf"
    file_path = item_dir / stored_filename
    metadata_path = item_dir / "metadata.json"
    timestamp = uploaded_at or datetime.now(timezone.utc).isoformat().replace(
        "+00:00", "Z"
    )
    metadata = {
        "intake_id": digest,
        "status": "pending",
        "original_filename": filename,
        "stored_filename": stored_filename,
        "content_type": normalized_type,
        "file_size_bytes": len(data),
        "sha256_hash": digest,
        "title": normalized["title"],
        "institution_source": normalized["institution_source"],
        "document_date": normalized["document_date"],
        "upload_date": timestamp,
        "category": normalized["category"],
        "description": normalized["description"],
        "visibility": normalized["visibility"],
        "notes": normalized["notes"],
        "reference_identifier": str(reference_identifier or "").strip() or None,
        "proposed_storage_location": str(file_path),
        "public_record_mutation": False,
        "status_updated_at": timestamp,
        "status_history": [
            {
                "previous_status": None,
                "new_status": "pending",
                "timestamp": timestamp,
                "actor": "admin",
                "note": "Document uploaded to pending intake.",
            }
        ],
    }
    try:
        file_path.write_bytes(data)
        os.chmod(file_path, 0o600)
        metadata_path.write_text(
            json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.chmod(metadata_path, 0o600)
    except Exception:
        file_path.unlink(missing_ok=True)
        metadata_path.unlink(missing_ok=True)
        item_dir.rmdir()
        raise
    return metadata


def load_pending_document(intake_id: str, *, root: Path | None = None) -> dict[str, Any]:
    if not _SAFE_ID_RE.fullmatch(str(intake_id or "")):
        raise ValueError("document_intake_not_found")
    destination_root = (root or intake_root()).resolve(strict=False)
    metadata_path = destination_root / intake_id / "metadata.json"
    if not metadata_path.is_file():
        raise ValueError("document_intake_not_found")
    return json.loads(metadata_path.read_text(encoding="utf-8"))


def list_intake_documents(*, root: Path | None = None) -> list[dict[str, Any]]:
    destination_root = (root or intake_root()).resolve(strict=False)
    if not destination_root.is_dir():
        return []
    items = []
    for metadata_path in destination_root.glob("*/metadata.json"):
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if metadata.get("status") in INTAKE_STATUSES:
            items.append(metadata)
    return sorted(items, key=lambda item: (item.get("upload_date", ""), item["intake_id"]), reverse=True)


def list_pending_documents(*, root: Path | None = None) -> list[dict[str, Any]]:
    return [
        item for item in list_intake_documents(root=root) if item["status"] == "pending"
    ]


def update_intake_status(
    intake_id: str,
    new_status: str,
    *,
    actor: str = "admin",
    note: str | None = None,
    notes: str | None = None,
    changed_at: str | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    metadata = load_pending_document(intake_id, root=root)
    current_status = metadata.get("status")
    normalized_status = str(new_status or "").strip().lower()
    if current_status not in INTAKE_STATUSES:
        raise ValueError("document_intake_status_invalid")
    if normalized_status not in INTAKE_STATUSES:
        raise ValueError("document_intake_status_invalid")
    if normalized_status not in VALID_STATUS_TRANSITIONS[current_status]:
        raise ValueError("document_intake_transition_invalid")

    timestamp = changed_at or datetime.now(timezone.utc).isoformat().replace(
        "+00:00", "Z"
    )
    history = list(metadata.get("status_history") or [])
    if not history:
        history.append(
            {
                "previous_status": None,
                "new_status": current_status,
                "timestamp": metadata.get("upload_date", timestamp),
                "actor": "admin",
                "note": "Existing intake state recorded.",
            }
        )
    history.append(
        {
            "previous_status": current_status,
            "new_status": normalized_status,
            "timestamp": timestamp,
            "actor": str(actor or "admin"),
            "note": str(note or "").strip() or None,
        }
    )
    metadata["status"] = normalized_status
    metadata["status_updated_at"] = timestamp
    metadata["status_history"] = history
    metadata["public_record_mutation"] = False
    if normalized_status == "published":
        metadata["publication_date"] = timestamp
    if notes is not None:
        metadata["notes"] = str(notes).strip()
    _write_metadata(intake_id, metadata, root=root)
    return metadata


def update_intake_notes(
    intake_id: str,
    notes: str,
    *,
    updated_at: str | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    metadata = load_pending_document(intake_id, root=root)
    metadata["notes"] = str(notes or "").strip()
    metadata["notes_updated_at"] = updated_at or datetime.now(
        timezone.utc
    ).isoformat().replace("+00:00", "Z")
    metadata["public_record_mutation"] = False
    _write_metadata(intake_id, metadata, root=root)
    return metadata


def _write_metadata(
    intake_id: str, metadata: dict[str, Any], *, root: Path | None = None
) -> None:
    if not _SAFE_ID_RE.fullmatch(str(intake_id or "")):
        raise ValueError("document_intake_not_found")
    destination_root = (root or intake_root()).resolve(strict=False)
    item_dir = destination_root / intake_id
    metadata_path = item_dir / "metadata.json"
    if not metadata_path.is_file():
        raise ValueError("document_intake_not_found")
    temporary_path = item_dir / "metadata.json.tmp"
    try:
        temporary_path.write_text(
            json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, metadata_path)
    finally:
        temporary_path.unlink(missing_ok=True)


def list_published_documents(
    *,
    query: str | None = None,
    institution: str | None = None,
    category: str | None = None,
    publication_year: str | None = None,
    root: Path | None = None,
) -> list[dict[str, Any]]:
    documents = []
    for item in list_intake_documents(root=root):
        if item["status"] != "published":
            continue
        normalized_item = dict(item)
        normalized_item["publication_date"] = _publication_date(item)
        documents.append(normalized_item)
    normalized_query = str(query or "").strip().casefold()
    normalized_institution = str(institution or "").strip().casefold()
    normalized_category = str(category or "").strip().casefold()
    normalized_year = str(publication_year or "").strip()

    def matches(item: dict[str, Any]) -> bool:
        searchable = " ".join(
            str(item.get(key) or "")
            for key in ("title", "institution_source", "category", "reference_identifier")
        ).casefold()
        if normalized_query and normalized_query not in searchable:
            return False
        if normalized_institution and str(item.get("institution_source") or "").casefold() != normalized_institution:
            return False
        if normalized_category and str(item.get("category") or "").casefold() != normalized_category:
            return False
        if normalized_year and not str(item.get("publication_date") or "").startswith(
            f"{normalized_year}-"
        ):
            return False
        return True

    return sorted(
        (item for item in documents if matches(item)),
        key=lambda item: (item.get("publication_date", ""), item["intake_id"]),
        reverse=True,
    )


def load_published_document(
    document_id: str, *, root: Path | None = None
) -> dict[str, Any]:
    metadata = load_pending_document(document_id, root=root)
    if metadata.get("status") != "published":
        raise ValueError("public_document_not_found")
    metadata["publication_date"] = _publication_date(metadata)
    return metadata


def published_document_file(
    document_id: str, *, root: Path | None = None
) -> tuple[Path, dict[str, Any]]:
    metadata = load_published_document(document_id, root=root)
    destination_root = (root or intake_root()).resolve(strict=False)
    file_path = (destination_root / document_id / f"pending-{document_id}.pdf").resolve(
        strict=False
    )
    try:
        file_path.relative_to(destination_root)
    except ValueError as exc:
        raise ValueError("public_document_not_found") from exc
    if not file_path.is_file():
        raise ValueError("public_document_not_found")
    return file_path, metadata


def _publication_date(metadata: dict[str, Any]) -> str:
    if metadata.get("publication_date"):
        return str(metadata["publication_date"])
    for event in reversed(metadata.get("status_history") or []):
        if event.get("new_status") == "published" and event.get("timestamp"):
            return str(event["timestamp"])
    return str(metadata.get("status_updated_at") or metadata.get("upload_date") or "")
