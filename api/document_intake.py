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


def list_pending_documents(*, root: Path | None = None) -> list[dict[str, Any]]:
    destination_root = (root or intake_root()).resolve(strict=False)
    if not destination_root.is_dir():
        return []
    items = []
    for metadata_path in destination_root.glob("*/metadata.json"):
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if metadata.get("status") == "pending":
            items.append(metadata)
    return sorted(items, key=lambda item: (item.get("upload_date", ""), item["intake_id"]), reverse=True)
