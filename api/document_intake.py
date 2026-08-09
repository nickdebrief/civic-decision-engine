from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import sqlite3
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path, PurePath
from typing import Any
from xml.etree import ElementTree

from api.email_documents import (
    email_projection_search_values,
    parse_mbox_archive_metadata_from_file,
    validate_apple_emlx_document,
    validate_email_document,
    validate_mbox_archive_document,
    validate_outlook_msg_document,
)
from api.outlook_archives import (
    build_outlook_archive_metadata,
    outlook_archive_search_values,
)
from api.gmail_takeout import (
    GmailTakeoutError,
    build_gmail_takeout_metadata,
    gmail_takeout_search_values,
    validate_gmail_takeout_archive,
)
from api.imap_acquisition import (
    ImapAcquisitionError,
    build_imap_acquisition_metadata,
    imap_acquisition_search_values,
    is_imap_acquisition_archive,
    validate_imap_acquisition_archive,
)
from api.document_lifecycle_events import (
    lifecycle_decision_by_key,
    record_lifecycle_decision,
)


DEFAULT_INTAKE_ROOT = Path("/data/attachments/intake/pending")
DEFAULT_MAX_BYTES = 25 * 1024 * 1024
DEFAULT_STREAMING_MBOX_MAX_BYTES = 1024 * 1024 * 1024
DEFAULT_STREAMING_MBOX_CHUNK_BYTES = 1024 * 1024
DEFAULT_STREAMING_MBOX_MIN_FREE_BYTES = 128 * 1024 * 1024
DEFAULT_STREAMING_MBOX_MAX_CONCURRENT_JOBS = 1
VALID_VISIBILITY = {"private", "restricted"}
DOCUMENT_TYPE_EXTENSIONS = {
    "pdf": ".pdf",
    "jpeg": ".jpg",
    "png": ".png",
    "m4a": ".m4a",
    "mp3": ".mp3",
    "wav": ".wav",
    "xls": ".xls",
    "xlsx": ".xlsx",
    "rtf": ".rtf",
    "eml": ".eml",
    "msg": ".msg",
    "emlx": ".emlx",
    "mbox": ".mbox",
    "pst": ".pst",
    "ost": ".ost",
    "gmail_takeout": ".zip",
    "imap_acquisition": ".zip",
    "email_attachment": ".bin",
}
DOCUMENT_TYPE_MEDIA_TYPES = {
    "pdf": "application/pdf",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "m4a": "audio/mp4",
    "mp3": "audio/mpeg",
    "wav": "audio/wav",
    "xls": "application/vnd.ms-excel",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "rtf": "application/rtf",
    "eml": "message/rfc822",
    "msg": "application/vnd.ms-outlook",
    "emlx": "application/octet-stream",
    "mbox": "application/mbox",
    "pst": "application/vnd.ms-outlook-pst",
    "ost": "application/vnd.ms-outlook-ost",
    "gmail_takeout": "application/zip",
    "imap_acquisition": "application/vnd.cde.imap-acquisition+zip",
    "email_attachment": "application/octet-stream",
}
DOCUMENT_TYPE_LABELS = {
    "pdf": "PDF",
    "jpeg": "JPEG",
    "png": "PNG",
    "m4a": "M4A",
    "mp3": "MP3",
    "wav": "WAV",
    "xls": "XLS",
    "xlsx": "XLSX",
    "rtf": "RTF",
    "eml": "RFC 5322 Email",
    "msg": "Microsoft Outlook Message",
    "emlx": "Apple Mail Message",
    "mbox": "MBOX Mailbox Archive",
    "pst": "Microsoft Outlook Personal Storage Archive",
    "ost": "Microsoft Outlook Offline Storage Archive",
    "gmail_takeout": "Google Takeout Gmail Export",
    "imap_acquisition": "Governed IMAP Acquisition",
    "email_attachment": "Email Attachment",
}
DOCUMENT_TYPE_MEDIA_FAMILIES = {
    "pdf": "document",
    "jpeg": "image",
    "png": "image",
    "m4a": "audio",
    "mp3": "audio",
    "wav": "audio",
    "xls": "spreadsheet",
    "xlsx": "spreadsheet",
    "rtf": "rich_text",
    "eml": "email",
    "msg": "email",
    "emlx": "email",
    "mbox": "mailbox",
    "pst": "mailbox",
    "ost": "mailbox",
    "gmail_takeout": "mailbox",
    "imap_acquisition": "mailbox",
    "email_attachment": "attachment",
}
EXTENSION_DOCUMENT_TYPES = {
    ".pdf": "pdf",
    ".jpg": "jpeg",
    ".jpeg": "jpeg",
    ".png": "png",
    ".m4a": "m4a",
    ".mp3": "mp3",
    ".wav": "wav",
    ".xls": "xls",
    ".xlsx": "xlsx",
    ".rtf": "rtf",
    ".eml": "eml",
    ".msg": "msg",
    ".emlx": "emlx",
    ".mbox": "mbox",
    ".pst": "pst",
    ".ost": "ost",
    ".zip": "gmail_takeout",
}
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
_DOCUMENT_IDENTIFIER_RE = re.compile(r"^DOC-\d{4}-\d{6}$")
_DOCUMENT_IDENTIFIER_REGISTRY_FILENAME = ".document_identifiers.sqlite3"
_WHITESPACE_RE = re.compile(r"\s+")
_SEARCH_SPLIT_RE = re.compile(r"\s+")
_JPEG_FIRST_MARKERS = {
    0xC0,
    0xC1,
    0xC2,
    0xC3,
    0xC5,
    0xC6,
    0xC7,
    0xC9,
    0xCA,
    0xCB,
    0xCD,
    0xCE,
    0xCF,
    0xC4,
    0xDA,
    0xDB,
    0xDD,
    0xE0,
    0xE1,
    0xE2,
    0xE3,
    0xE4,
    0xE5,
    0xE6,
    0xE7,
    0xE8,
    0xE9,
    0xEA,
    0xEB,
    0xEC,
    0xED,
    0xEE,
    0xEF,
    0xFE,
}
_OLE_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_XLS_WORKBOOK_STREAM_NAMES = {"Workbook", "Book"}
_OLE_REJECTED_STREAM_NAMES = {
    "WordDocument",
    "PowerPoint Document",
    "EncryptedPackage",
    "EncryptionInfo",
    "VBA",
    "_VBA_PROJECT_CUR",
    "VBA_PROJECT",
    "Macros",
}
_ZIP_MAX_ENTRIES = 512
_ZIP_MAX_UNCOMPRESSED_BYTES = 100 * 1024 * 1024
_ZIP_MAX_EXPANSION_RATIO = 100
_XLSX_REQUIRED_ENTRIES = {"[Content_Types].xml", "xl/workbook.xml"}
_XLSX_REJECTED_SUFFIXES = (".exe", ".dll", ".js", ".vbs", ".ps1", ".bat", ".cmd")

LOGGER = logging.getLogger(__name__)


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


def streaming_mbox_max_bytes() -> int:
    raw = os.getenv("MAX_STREAMING_MBOX_UPLOAD_BYTES") or os.getenv("CDE_STREAMING_MBOX_UPLOAD_MAX_BYTES")
    if raw is None:
        return DEFAULT_STREAMING_MBOX_MAX_BYTES
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError("streaming_mbox_size_limit_invalid") from exc
    if value < 1:
        raise ValueError("streaming_mbox_size_limit_invalid")
    return value


def streaming_mbox_chunk_bytes() -> int:
    raw = os.getenv("STREAMING_MBOX_CHUNK_BYTES") or os.getenv("CDE_STREAMING_MBOX_CHUNK_BYTES")
    if raw is None:
        return DEFAULT_STREAMING_MBOX_CHUNK_BYTES
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError("streaming_mbox_chunk_size_invalid") from exc
    if value < 1024:
        raise ValueError("streaming_mbox_chunk_size_invalid")
    return value


def streaming_mbox_min_free_bytes() -> int:
    raw = os.getenv("STREAMING_MBOX_MIN_FREE_BYTES") or os.getenv("CDE_STREAMING_MBOX_MIN_FREE_BYTES")
    if raw is None:
        return DEFAULT_STREAMING_MBOX_MIN_FREE_BYTES
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError("streaming_mbox_min_free_invalid") from exc
    if value < 0:
        raise ValueError("streaming_mbox_min_free_invalid")
    return value


def streaming_mbox_max_concurrent_jobs() -> int:
    raw = os.getenv("STREAMING_MBOX_MAX_CONCURRENT_JOBS") or os.getenv("CDE_STREAMING_MBOX_MAX_CONCURRENT_JOBS")
    if raw is None:
        return DEFAULT_STREAMING_MBOX_MAX_CONCURRENT_JOBS
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError("streaming_mbox_concurrency_invalid") from exc
    if value < 1:
        raise ValueError("streaming_mbox_concurrency_invalid")
    return value


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _document_identifier_registry_path(root: Path | None = None) -> Path:
    destination_root = (root or intake_root()).resolve(strict=False)
    destination_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    return destination_root / _DOCUMENT_IDENTIFIER_REGISTRY_FILENAME


def _registered_document_identifier_read_only(
    intake_id: str, *, root: Path | None = None
) -> str | None:
    destination_root = (root or intake_root()).resolve(strict=False)
    registry_path = destination_root / _DOCUMENT_IDENTIFIER_REGISTRY_FILENAME
    if not registry_path.is_file():
        return None
    conn = sqlite3.connect(f"{registry_path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        try:
            row = conn.execute(
                "SELECT document_identifier FROM document_identifiers WHERE intake_id = ?",
                (str(intake_id),),
            ).fetchone()
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc).lower():
                return None
            raise
        return str(row[0]) if row else None
    finally:
        conn.close()


def _ensure_document_identifier_registry(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS document_identifier_sequences (
            year TEXT PRIMARY KEY,
            next_value INTEGER NOT NULL CHECK (next_value > 0)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS document_identifiers (
            document_identifier TEXT PRIMARY KEY,
            intake_id TEXT NOT NULL UNIQUE,
            assigned_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_document_identifiers_intake_id
        ON document_identifiers (intake_id)
        """
    )


def _document_identifier_year(timestamp: str | None = None) -> str:
    text = str(timestamp or "").strip()
    if re.match(r"^\d{4}-", text):
        return text[:4]
    return datetime.now(timezone.utc).strftime("%Y")


def _validate_document_identifier(value: str) -> str:
    identifier = str(value or "").strip().upper()
    if not _DOCUMENT_IDENTIFIER_RE.fullmatch(identifier):
        raise ValueError("document_identifier_invalid")
    return identifier


def assign_document_identifier(
    intake_id: str,
    *,
    assigned_at: str | None = None,
    root: Path | None = None,
    existing_identifier: str | None = None,
) -> str:
    """Assign or return the immutable CDE identifier for an intake document."""
    normalized_intake_id = str(intake_id or "").strip()
    if not _SAFE_ID_RE.fullmatch(normalized_intake_id):
        raise ValueError("document_intake_not_found")
    timestamp = assigned_at or _utc_timestamp()
    registry_path = _document_identifier_registry_path(root)
    conn = sqlite3.connect(registry_path, timeout=30)
    try:
        _ensure_document_identifier_registry(conn)
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT document_identifier FROM document_identifiers WHERE intake_id = ?",
            (normalized_intake_id,),
        ).fetchone()
        if row:
            conn.commit()
            return str(row[0])
        if existing_identifier:
            identifier = _validate_document_identifier(existing_identifier)
            try:
                conn.execute(
                    """
                    INSERT INTO document_identifiers (
                        document_identifier, intake_id, assigned_at
                    ) VALUES (?, ?, ?)
                    """,
                    (identifier, normalized_intake_id, timestamp),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("document_identifier_duplicate") from exc
            conn.commit()
            return identifier
        year = _document_identifier_year(timestamp)
        row = conn.execute(
            "SELECT next_value FROM document_identifier_sequences WHERE year = ?",
            (year,),
        ).fetchone()
        next_value = int(row[0]) if row else 1
        while True:
            identifier = f"DOC-{year}-{next_value:06d}"
            try:
                conn.execute(
                    """
                    INSERT INTO document_identifiers (
                        document_identifier, intake_id, assigned_at
                    ) VALUES (?, ?, ?)
                    """,
                    (identifier, normalized_intake_id, timestamp),
                )
            except sqlite3.IntegrityError:
                next_value += 1
                continue
            conn.execute(
                """
                INSERT INTO document_identifier_sequences (year, next_value)
                VALUES (?, ?)
                ON CONFLICT(year) DO UPDATE SET next_value = excluded.next_value
                """,
                (year, next_value + 1),
            )
            conn.commit()
            return identifier
    finally:
        conn.close()


def _ensure_document_identifier(
    metadata: dict[str, Any],
    *,
    root: Path | None = None,
    persist: bool = False,
) -> dict[str, Any]:
    intake_id = str(metadata.get("intake_id") or "").strip()
    if not _SAFE_ID_RE.fullmatch(intake_id):
        return metadata
    current_identifier = str(metadata.get("document_identifier") or "").strip()
    assigned_at = (
        str(metadata.get("upload_date") or metadata.get("status_updated_at") or "").strip()
        or None
    )
    if current_identifier:
        document_identifier = assign_document_identifier(
            intake_id,
            assigned_at=assigned_at,
            root=root,
            existing_identifier=current_identifier,
        )
    else:
        document_identifier = assign_document_identifier(
            intake_id,
            assigned_at=assigned_at,
            root=root,
        )
    changed = metadata.get("document_identifier") != document_identifier
    metadata["document_identifier"] = document_identifier
    history = metadata.get("status_history")
    if isinstance(history, list):
        for event in history:
            if (
                isinstance(event, dict)
                and event.get("new_status") == "pending"
                and not event.get("document_identifier")
            ):
                event["document_identifier"] = document_identifier
                changed = True
                break
    if persist and changed:
        _write_metadata(intake_id, metadata, root=root)
    return metadata


def backfill_document_identifiers(*, root: Path | None = None) -> dict[str, int]:
    destination_root = (root or intake_root()).resolve(strict=False)
    if not destination_root.is_dir():
        return {"scanned": 0, "assigned": 0, "preserved": 0}
    scanned = assigned = preserved = 0
    for metadata_path in destination_root.glob("*/metadata.json"):
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if metadata.get("status") not in INTAKE_STATUSES:
            continue
        scanned += 1
        before = str(metadata.get("document_identifier") or "").strip()
        _ensure_document_identifier(metadata, root=destination_root, persist=True)
        after = str(metadata.get("document_identifier") or "").strip()
        if before:
            preserved += 1
        elif after:
            assigned += 1
    return {"scanned": scanned, "assigned": assigned, "preserved": preserved}


def document_reference_matches(
    document: dict[str, Any],
    reference: str,
    *,
    include_external_reference: bool = True,
) -> bool:
    normalized = str(reference or "").strip()
    if not normalized:
        return False
    values = [document.get("intake_id"), document.get("document_identifier")]
    if include_external_reference:
        values.append(document.get("reference_identifier"))
    return any(str(value or "").strip() == normalized for value in values)


def find_document_by_reference(
    reference: str,
    *,
    root: Path | None = None,
    published_only: bool = False,
    include_external_reference: bool = True,
) -> dict[str, Any] | None:
    normalized = str(reference or "").strip()
    if not normalized:
        return None
    if _SAFE_ID_RE.fullmatch(normalized):
        try:
            document = load_pending_document(normalized, root=root)
        except ValueError:
            document = None
        if document and (not published_only or document.get("status") == "published"):
            return document
    for document in list_intake_documents(root=root):
        if published_only and document.get("status") != "published":
            continue
        if document_reference_matches(
            document,
            normalized,
            include_external_reference=include_external_reference,
        ):
            return document
    return None


def _leading_signature_hex(data: bytes, *, length: int = 16) -> str:
    return data[:length].hex()


def _unsupported_media_signature(data: bytes) -> tuple[str, str, str] | None:
    if data.startswith(b"\x00\x00\x00\x0cjP  \r\n\x87\n") or data.startswith(
        b"\xff\x4f\xff\x51"
    ):
        return "jpeg2000", "image/jp2", "JPEG 2000 (JP2)"
    if data.startswith(b"II*\x00") or data.startswith(b"MM\x00*"):
        return "tiff", "image/tiff", "TIFF"
    if len(data) >= 12 and data[4:8] == b"ftyp" and data[8:12] in {
        b"heic",
        b"heix",
        b"hevc",
        b"hevx",
        b"mif1",
        b"msf1",
    }:
        return "heic", "image/heic", "HEIC/HEIF"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp", "image/webp", "WebP"
    return None


def _uint32(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 4], "little", signed=False)


def _int32(data: bytes, offset: int) -> int:
    value = _uint32(data, offset)
    return -2 if value == 0xFFFFFFFE else -1 if value == 0xFFFFFFFF else value


def _ole_sector(data: bytes, sector_id: int, sector_size: int) -> bytes:
    start = 512 + sector_id * sector_size
    end = start + sector_size
    if sector_id < 0 or end > len(data):
        raise ValueError("document_intake_invalid_workbook")
    return data[start:end]


def _ole_directory_stream_names(data: bytes) -> list[str]:
    if len(data) < 512 or not data.startswith(_OLE_SIGNATURE):
        raise ValueError("document_intake_invalid_workbook")
    sector_shift = int.from_bytes(data[30:32], "little", signed=False)
    if sector_shift not in {9, 12}:
        raise ValueError("document_intake_invalid_workbook")
    sector_size = 1 << sector_shift
    first_directory_sector = _int32(data, 48)
    difat = [
        _uint32(data, offset)
        for offset in range(76, 512, 4)
        if _uint32(data, offset) not in {0xFFFFFFFF, 0xFFFFFFFE}
    ]
    if first_directory_sector < 0 or not difat:
        raise ValueError("document_intake_invalid_workbook")
    fat_entries: list[int] = []
    for sector_id in difat[:109]:
        sector = _ole_sector(data, sector_id, sector_size)
        fat_entries.extend(_uint32(sector, offset) for offset in range(0, sector_size, 4))
    directory_bytes = bytearray()
    sector_id = first_directory_sector
    visited: set[int] = set()
    while sector_id not in {-1, -2, 0xFFFFFFFF, 0xFFFFFFFE}:
        if sector_id in visited or sector_id >= len(fat_entries):
            raise ValueError("document_intake_invalid_workbook")
        visited.add(sector_id)
        directory_bytes.extend(_ole_sector(data, sector_id, sector_size))
        next_id = fat_entries[sector_id]
        sector_id = -2 if next_id == 0xFFFFFFFE else -1 if next_id == 0xFFFFFFFF else next_id
        if len(directory_bytes) > 1024 * 1024:
            raise ValueError("document_intake_invalid_workbook")
    names: list[str] = []
    for offset in range(0, len(directory_bytes), 128):
        entry = bytes(directory_bytes[offset : offset + 128])
        if len(entry) < 128:
            continue
        name_length = int.from_bytes(entry[64:66], "little", signed=False)
        object_type = entry[66]
        if object_type not in {1, 2, 5} or name_length < 2 or name_length > 64:
            continue
        raw_name = entry[: name_length - 2]
        try:
            name = raw_name.decode("utf-16le").strip("\x00")
        except UnicodeDecodeError:
            continue
        if name:
            names.append(name)
    return names


def _xls_workbook_metadata(data: bytes) -> dict[str, Any]:
    names = _ole_directory_stream_names(data)
    if any(name in _OLE_REJECTED_STREAM_NAMES for name in names):
        if any(name in {"EncryptedPackage", "EncryptionInfo"} for name in names):
            raise ValueError("document_intake_password_protected_workbook")
        if any(name in {"VBA", "_VBA_PROJECT_CUR", "VBA_PROJECT", "Macros"} for name in names):
            raise ValueError("document_intake_macro_enabled_workbook")
        raise ValueError("document_intake_invalid_workbook")
    if not any(name in _XLS_WORKBOOK_STREAM_NAMES for name in names):
        raise ValueError("document_intake_invalid_workbook")
    return {
        "workbook_type": "Excel 97-2003 Workbook",
        "worksheet_names": [],
        "worksheet_count": None,
        "hidden_sheets_present": None,
    }


def _zip_path_is_safe(name: str) -> bool:
    path = PurePath(str(name or ""))
    return (
        bool(name)
        and "\\" not in name
        and not str(name).startswith("/")
        and not path.is_absolute()
        and ".." not in path.parts
    )


def _xlsx_workbook_metadata(data: bytes) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(BytesIO(data)) as package:
            infos = package.infolist()
            if not infos or len(infos) > _ZIP_MAX_ENTRIES:
                raise ValueError("document_intake_invalid_workbook")
            names = {info.filename for info in infos}
            if not _XLSX_REQUIRED_ENTRIES.issubset(names):
                raise ValueError("document_intake_invalid_workbook")
            total_uncompressed = 0
            total_compressed = 0
            for info in infos:
                if not _zip_path_is_safe(info.filename):
                    raise ValueError("document_intake_unsafe_workbook_package")
                total_uncompressed += int(info.file_size or 0)
                total_compressed += max(1, int(info.compress_size or 0))
                lower_name = info.filename.lower()
                if lower_name == "xl/vbaproject.bin":
                    raise ValueError("document_intake_macro_enabled_workbook")
                if lower_name.startswith("xl/embeddings/"):
                    raise ValueError("document_intake_unsafe_workbook_package")
                if lower_name.startswith("xl/externallinks/"):
                    raise ValueError("document_intake_unsafe_workbook_package")
                if lower_name.endswith(_XLSX_REJECTED_SUFFIXES):
                    raise ValueError("document_intake_unsafe_workbook_package")
            if total_uncompressed > _ZIP_MAX_UNCOMPRESSED_BYTES:
                raise ValueError("document_intake_workbook_package_too_large")
            if total_uncompressed > 5 * 1024 * 1024 and total_uncompressed / total_compressed > _ZIP_MAX_EXPANSION_RATIO:
                raise ValueError("document_intake_workbook_package_too_large")
            content_types = package.read("[Content_Types].xml", pwd=None)
            if b"macroEnabled" in content_types or b"vnd.ms-excel.sheet.macroEnabled" in content_types:
                raise ValueError("document_intake_macro_enabled_workbook")
            if b"spreadsheetml.sheet.main+xml" not in content_types:
                raise ValueError("document_intake_invalid_workbook")
            workbook_xml = package.read("xl/workbook.xml", pwd=None)
    except zipfile.BadZipFile as exc:
        raise ValueError("document_intake_invalid_workbook") from exc
    except RuntimeError as exc:
        raise ValueError("document_intake_password_protected_workbook") from exc

    try:
        root = ElementTree.fromstring(workbook_xml)
    except ElementTree.ParseError as exc:
        raise ValueError("document_intake_invalid_workbook") from exc
    namespace = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    sheets = root.findall(".//main:sheets/main:sheet", namespace)
    worksheet_names = [
        str(sheet.attrib.get("name") or "").strip()
        for sheet in sheets
        if str(sheet.attrib.get("name") or "").strip()
    ]
    hidden = any(
        str(sheet.attrib.get("state") or "").strip().lower() in {"hidden", "veryhidden"}
        for sheet in sheets
    )
    calc_pr = root.find(".//main:calcPr", namespace)
    return {
        "workbook_type": "Excel Workbook",
        "worksheet_names": worksheet_names,
        "worksheet_count": len(worksheet_names),
        "hidden_sheets_present": hidden,
        "calculation_mode": calc_pr.attrib.get("calcMode") if calc_pr is not None else None,
    }


def spreadsheet_workbook_metadata(data: bytes, document_type: str) -> dict[str, Any]:
    normalized = str(document_type or "").strip().lower()
    if normalized == "xls":
        return _xls_workbook_metadata(data)
    if normalized == "xlsx":
        return _xlsx_workbook_metadata(data)
    return {}


def document_intake_upload_error_detail(
    code: str,
    *,
    data: bytes,
    original_filename: str,
    content_type: str | None = None,
) -> dict[str, Any] | str:
    if code not in {
        "document_intake_file_type_not_allowed",
        "document_intake_file_type_mismatch",
    }:
        return code

    filename = PurePath(str(original_filename or "").replace("\\", "/")).name
    extension = Path(filename).suffix.lower()
    expected_type = EXTENSION_DOCUMENT_TYPES.get(extension)
    expected_label = DOCUMENT_TYPE_LABELS.get(expected_type or "", "supported file")
    unsupported = _unsupported_media_signature(data)
    detected_type = None
    try:
        detected_type = _detected_document_type(data)
    except ValueError:
        detected_type = None

    if code == "document_intake_file_type_mismatch" and detected_type:
        detected_label = DOCUMENT_TYPE_LABELS.get(detected_type, detected_type.upper())
        message = (
            f"The filename extension is {expected_label}, but the server detected "
            f"{detected_label}."
        )
        detected_format = detected_type
        detected_mime_type = DOCUMENT_TYPE_MEDIA_TYPES.get(detected_type, "unknown")
    elif expected_type == "jpeg" and unsupported:
        detected_format, detected_mime_type, detected_label = unsupported
        message = (
            "The filename extension is JPEG, but the server detected "
            f"{detected_label}, which is not a supported JPEG format. Export the "
            "file explicitly as JPEG and upload the new .jpg or .jpeg file."
        )
    elif expected_type == "jpeg":
        detected_format = "unknown"
        detected_mime_type = "unknown"
        message = (
            "The uploaded file has a JPEG extension but could not be verified as "
            "a valid supported JPEG."
        )
    elif expected_type == "eml":
        detected_format = "unknown"
        detected_mime_type = "unknown"
        message = (
            "The uploaded file has an EML extension but could not be verified as "
            "a structurally recognisable RFC 5322 email message."
        )
    elif expected_type == "msg":
        detected_format = "unknown"
        detected_mime_type = "unknown"
        message = (
            "The uploaded file has a MSG extension but could not be verified as "
            "a structurally recognisable Microsoft Outlook message."
        )
    elif expected_type == "emlx":
        detected_format = "unknown"
        detected_mime_type = "unknown"
        message = (
            "The uploaded file has an EMLX extension but could not be verified as "
            "a structurally recognisable Apple Mail message."
        )
    elif expected_type == "mbox":
        detected_format = "unknown"
        detected_mime_type = "unknown"
        message = (
            "The uploaded file has an MBOX extension but could not be verified as "
            "a structurally recognisable mailbox archive."
        )
    elif unsupported:
        detected_format, detected_mime_type, detected_label = unsupported
        message = (
            f"The server detected {detected_label}, which is not a supported "
            "Document Intake format."
        )
    else:
        detected_format = "unknown"
        detected_mime_type = "unknown"
        message = "The server could not recognise the uploaded file as a supported format."

    return {
        "code": code,
        "message": message,
        "filename": filename,
        "extension": extension,
        "declared_content_type": content_type,
        "expected_format": expected_type,
        "detected_format": detected_format,
        "detected_mime_type": detected_mime_type,
    }


def document_intake_duplicate_detail(
    data: bytes,
    *,
    root: Path | None = None,
) -> dict[str, Any]:
    digest = hashlib.sha256(data).hexdigest()
    try:
        existing = load_pending_document(digest, root=root)
    except ValueError:
        existing = {
            "intake_id": digest,
            "status": "unknown",
            "title": "",
            "reference_identifier": None,
            "document_identifier": None,
        }
    lifecycle_state = str(existing.get("status") or "unknown")
    lifecycle_label = STATUS_LABELS.get(lifecycle_state, lifecycle_state.replace("_", " ").title())
    message, recommended_action, action_label = _duplicate_lifecycle_guidance(
        lifecycle_state,
        lifecycle_label,
    )
    return {
        "detail": "document_intake_duplicate",
        "code": "document_intake_duplicate",
        "message": message,
        "duplicate_reason": "sha256",
        "existing_document": {
            "id": str(existing.get("intake_id") or digest),
            "title": str(existing.get("title") or ""),
            "document_identifier": existing.get("document_identifier"),
            "reference_identifier": existing.get("reference_identifier"),
            "lifecycle_state": lifecycle_state,
            "lifecycle_label": lifecycle_label,
        },
        "recommended_action": recommended_action,
        "action_label": action_label,
        "admin_url": f"/admin/document-intake/{digest}",
    }


def _duplicate_lifecycle_guidance(
    lifecycle_state: str,
    lifecycle_label: str,
) -> tuple[str, str, str]:
    if lifecycle_state == "pending":
        return (
            "This document already exists in Pending Intake and is awaiting review.",
            "Continue review of the existing pending document.",
            "Continue review",
        )
    if lifecycle_state == "under_review":
        return (
            "This document already exists and is currently under review.",
            "Continue review of the existing document.",
            "Continue review",
        )
    if lifecycle_state == "approved":
        return (
            "This document already exists and has been approved but not yet declared published.",
            "Continue the publication workflow for the existing document.",
            "Continue publication workflow",
        )
    if lifecycle_state == "published":
        return (
            "This document has already been declared published.",
            "Open the existing published document instead of creating a duplicate intake.",
            "Open existing document",
        )
    if lifecycle_state == "rejected":
        return (
            "This document already exists in Rejected state.",
            "Review the existing rejected intake record before deciding any governed next step.",
            "Open existing intake record",
        )
    if lifecycle_state == "archived":
        return (
            "This document already exists in Archived state.",
            "Review the existing archived intake record before deciding any governed next step.",
            "Open existing intake record",
        )
    return (
        f"This document already exists in {lifecycle_label}.",
        "Review the existing intake record before continuing.",
        "Open existing intake record",
    )


def _is_supported_jpeg(data: bytes) -> bool:
    if len(data) < 6 or not data.startswith(b"\xff\xd8\xff"):
        return False
    marker = data[3]
    if marker not in _JPEG_FIRST_MARKERS:
        return False
    return b"\xff\xd9" in data[4:]


def _is_supported_rtf(data: bytes) -> bool:
    if not data:
        return False
    candidate = data
    if candidate.startswith(b"\xef\xbb\xbf"):
        candidate = candidate[3:]
    candidate = candidate.lstrip(b" \t\r\n")
    if not candidate.startswith(b"{\\rtf"):
        return False
    if len(candidate) < 6 or not bytes(candidate[5:6]).isdigit():
        return False
    if b"\x00" in candidate[:128]:
        return False
    return b"}" in candidate[6:]


def _detected_document_type(data: bytes) -> str:
    if not data:
        raise ValueError("document_intake_file_required")
    if len(data) > intake_max_bytes():
        raise ValueError("document_intake_file_too_large")
    if data.startswith(b"%PDF-"):
        return "pdf"
    if _is_supported_jpeg(data):
        return "jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if len(data) >= 12 and data[4:8] == b"ftyp" and data[8:12] == b"M4A ":
        return "m4a"
    if data.startswith(b"ID3") or (
        len(data) >= 2 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0
    ):
        return "mp3"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "wav"
    if data.startswith(_OLE_SIGNATURE):
        try:
            _xls_workbook_metadata(data)
        except ValueError:
            try:
                validate_outlook_msg_document(data)
            except ValueError as exc:
                code = str(exc)
                if code in {
                    "document_intake_file_required",
                    "document_intake_file_too_large",
                } or code.startswith("document_intake_msg_"):
                    raise
                raise ValueError("document_intake_file_type_not_allowed") from exc
            return "msg"
        return "xls"
    if data.startswith(b"PK\x03\x04"):
        _xlsx_workbook_metadata(data)
        return "xlsx"
    if _is_supported_rtf(data):
        return "rtf"
    try:
        validate_apple_emlx_document(data)
    except ValueError as exc:
        code = str(exc)
        if code in {
            "document_intake_file_required",
            "document_intake_file_too_large",
        } or code.startswith("document_intake_emlx_"):
            raise
    else:
        return "emlx"
    try:
        validate_mbox_archive_document(data)
    except ValueError as exc:
        code = str(exc)
        if code in {
            "document_intake_file_required",
            "document_intake_file_too_large",
        } or code.startswith("document_intake_mbox_"):
            raise
    else:
        return "mbox"
    try:
        validate_email_document(data)
    except ValueError as exc:
        code = str(exc)
        if code in {
            "document_intake_file_required",
            "document_intake_file_too_large",
        } or code.startswith("document_intake_email_"):
            raise
    else:
        return "eml"
    raise ValueError("document_intake_file_type_not_allowed")


def validate_document_file(
    data: bytes, original_filename: str, content_type: str | None = None
) -> tuple[str, str, str]:
    filename = PurePath(str(original_filename or "").replace("\\", "/")).name
    extension = Path(filename).suffix.lower()
    if not filename or extension not in EXTENSION_DOCUMENT_TYPES:
        raise ValueError("document_intake_file_type_not_allowed")
    expected_type = EXTENSION_DOCUMENT_TYPES[extension]
    if expected_type == "xls" and data.startswith(_OLE_SIGNATURE):
        try:
            _xls_workbook_metadata(data)
        except ValueError as workbook_exc:
            try:
                validate_outlook_msg_document(data)
            except ValueError:
                raise workbook_exc
            raise ValueError("document_intake_file_type_mismatch") from workbook_exc
        return expected_type, DOCUMENT_TYPE_MEDIA_TYPES[expected_type], filename
    if expected_type in {"pst", "ost"}:
        if not data:
            raise ValueError("document_intake_file_required")
        if len(data) > intake_max_bytes():
            raise ValueError("document_intake_file_too_large")
        return expected_type, DOCUMENT_TYPE_MEDIA_TYPES[expected_type], filename
    if expected_type == "gmail_takeout":
        if len(data) > intake_max_bytes():
            raise ValueError("document_intake_file_too_large")
        if is_imap_acquisition_archive(data):
            try:
                validate_imap_acquisition_archive(data)
            except ImapAcquisitionError as exc:
                raise ValueError(exc.code) from exc
            return (
                "imap_acquisition",
                DOCUMENT_TYPE_MEDIA_TYPES["imap_acquisition"],
                filename,
            )
        try:
            validate_gmail_takeout_archive(data)
        except GmailTakeoutError as exc:
            raise ValueError(exc.code) from exc
        return expected_type, DOCUMENT_TYPE_MEDIA_TYPES[expected_type], filename
    try:
        detected_type = _detected_document_type(data)
    except ValueError:
        unsupported = _unsupported_media_signature(data)
        detected_format = unsupported[0] if unsupported else "unknown"
        detected_mime_type = unsupported[1] if unsupported else "unknown"
        LOGGER.warning(
            "Document intake rejected unsupported media: filename=%s extension=%s declared_content_type=%s detected_format=%s detected_mime_type=%s leading_signature_hex=%s",
            filename,
            extension,
            content_type,
            detected_format,
            detected_mime_type,
            _leading_signature_hex(data),
        )
        raise
    if detected_type != expected_type:
        LOGGER.warning(
            "Document intake file type mismatch: filename=%s extension=%s declared_content_type=%s expected_format=%s detected_format=%s detected_mime_type=%s leading_signature_hex=%s",
            filename,
            extension,
            content_type,
            expected_type,
            detected_type,
            DOCUMENT_TYPE_MEDIA_TYPES.get(detected_type, "unknown"),
            _leading_signature_hex(data),
        )
        raise ValueError("document_intake_file_type_mismatch")
    return detected_type, DOCUMENT_TYPE_MEDIA_TYPES[detected_type], filename


def validate_pdf(data: bytes, content_type: str | None) -> str:
    detected_type = _detected_document_type(data)
    if detected_type != "pdf":
        raise ValueError("document_intake_invalid_pdf")
    return DOCUMENT_TYPE_MEDIA_TYPES["pdf"]


def document_type_label(document_type: str | None) -> str:
    normalized = normalized_document_type({"document_type": document_type})
    return DOCUMENT_TYPE_LABELS[normalized]


def normalized_document_type(metadata: dict[str, Any]) -> str:
    document_type = str(metadata.get("document_type") or "").strip().lower()
    if document_type in DOCUMENT_TYPE_EXTENSIONS:
        return document_type
    content_type = str(metadata.get("content_type") or "").split(";", 1)[0].lower()
    if content_type == "image/jpeg":
        return "jpeg"
    if content_type == "image/png":
        return "png"
    if content_type in {"audio/mp4", "audio/x-m4a"}:
        return "m4a"
    if content_type == "audio/mpeg":
        return "mp3"
    if content_type in {"audio/wav", "audio/x-wav", "audio/wave"}:
        return "wav"
    if content_type == "application/vnd.ms-excel":
        return "xls"
    if content_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":
        return "xlsx"
    if content_type in {"application/rtf", "text/rtf", "application/x-rtf"}:
        return "rtf"
    if content_type in {"message/rfc822", "text/rfc822", "application/eml"}:
        return "eml"
    if content_type in {"application/x-apple-mail", "message/x-emlx"}:
        return "emlx"
    if content_type in {"application/mbox", "text/mbox"}:
        return "mbox"
    if content_type in {"application/vnd.ms-outlook-pst", "application/x-pst"}:
        return "pst"
    if content_type in {"application/vnd.ms-outlook-ost", "application/x-ost"}:
        return "ost"
    if content_type in {"application/zip", "application/x-zip-compressed"}:
        return "gmail_takeout"
    if content_type == "application/vnd.cde.imap-acquisition+zip":
        return "imap_acquisition"
    if content_type in {
        "application/vnd.ms-outlook",
        "application/x-msg",
        "application/msoutlook",
    }:
        return "msg"
    return "pdf"


def document_media_type(metadata: dict[str, Any]) -> str:
    if normalized_document_type(metadata) == "email_attachment":
        return str(metadata.get("content_type") or "application/octet-stream")
    return DOCUMENT_TYPE_MEDIA_TYPES[normalized_document_type(metadata)]


def document_storage_extension(metadata: dict[str, Any]) -> str:
    if normalized_document_type(metadata) == "email_attachment":
        suffix = Path(str(metadata.get("stored_filename") or metadata.get("original_filename") or "")).suffix
        return suffix if suffix and len(suffix) <= 16 else ".bin"
    return DOCUMENT_TYPE_EXTENSIONS[normalized_document_type(metadata)]


def is_image_document(metadata: dict[str, Any]) -> bool:
    return normalized_document_type(metadata) in {"jpeg", "png"}


def is_audio_document(metadata: dict[str, Any]) -> bool:
    return normalized_document_type(metadata) in {"m4a", "mp3", "wav"}


def is_spreadsheet_document(metadata: dict[str, Any]) -> bool:
    return normalized_document_type(metadata) in {"xls", "xlsx"}


def is_rich_text_document(metadata: dict[str, Any]) -> bool:
    return normalized_document_type(metadata) == "rtf"


def is_email_document(metadata: dict[str, Any]) -> bool:
    return normalized_document_type(metadata) in {"eml", "msg", "emlx"}


def is_mailbox_document(metadata: dict[str, Any]) -> bool:
    return normalized_document_type(metadata) == "mbox"


def is_outlook_archive_document(metadata: dict[str, Any]) -> bool:
    return normalized_document_type(metadata) in {"pst", "ost"}


def is_gmail_takeout_document(metadata: dict[str, Any]) -> bool:
    return normalized_document_type(metadata) == "gmail_takeout"


def is_imap_acquisition_document(metadata: dict[str, Any]) -> bool:
    return normalized_document_type(metadata) == "imap_acquisition"


def is_governed_mail_archive_document(metadata: dict[str, Any]) -> bool:
    return (
        is_outlook_archive_document(metadata)
        or is_gmail_takeout_document(metadata)
        or is_imap_acquisition_document(metadata)
    )


def document_media_family(metadata: dict[str, Any]) -> str:
    return DOCUMENT_TYPE_MEDIA_FAMILIES[normalized_document_type(metadata)]


def normalize_document_keywords(value: Any) -> list[str]:
    """Return stable administrator-confirmed discovery keywords."""
    raw_values: list[Any] = []
    if value is None:
        raw_values = []
    elif isinstance(value, str):
        stripped = value.strip()
        if stripped[:1] in {"[", "{"}:
            try:
                parsed = json.loads(stripped)
            except (TypeError, json.JSONDecodeError):
                parsed = None
            if parsed is not None:
                raw_values.extend(normalize_document_keywords(parsed))
            else:
                raw_values.extend(stripped.split(","))
        else:
            raw_values.extend(stripped.split(","))
    elif isinstance(value, dict):
        raw_values.extend(value.values())
    elif isinstance(value, (list, tuple, set)):
        raw_values.extend(value)
    else:
        raw_values.append(value)

    keywords: list[str] = []
    seen: set[str] = set()
    for raw in raw_values:
        if isinstance(raw, (list, tuple, set, dict)):
            candidates = normalize_document_keywords(raw)
        else:
            candidates = [str(raw or "")]
        for candidate in candidates:
            normalized = _WHITESPACE_RE.sub(" ", str(candidate or "")).strip()
            if not normalized:
                continue
            parts = normalized.split(",") if "," in normalized else [normalized]
            for part in parts:
                keyword = _WHITESPACE_RE.sub(" ", part).strip()
                if not keyword:
                    continue
                key = keyword.casefold()
                if key in seen:
                    continue
                seen.add(key)
                keywords.append(keyword)
    return keywords


def document_keywords_display(value: Any, *, separator: str = " · ") -> str:
    keywords = normalize_document_keywords(value)
    return separator.join(keywords)


def document_keywords_input_value(value: Any) -> str:
    return ", ".join(normalize_document_keywords(value))


def _normalize_intake_metadata(
    *,
    title: str,
    institution_source: str,
    document_date: str,
    category: str,
    description: str,
    visibility: str,
    notes: str,
) -> dict[str, str]:
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
    return normalized


def _streaming_mbox_temp_root(root: Path | None = None) -> Path:
    destination_root = (root or intake_root()).resolve(strict=False)
    temp_root = destination_root / "_streaming_mbox_tmp"
    temp_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    return temp_root


def cleanup_stale_streaming_mbox_temporary_files(*, root: Path | None = None, max_age_seconds: int = 24 * 60 * 60) -> int:
    temp_root = _streaming_mbox_temp_root(root)
    now = datetime.now(timezone.utc).timestamp()
    removed = 0
    for candidate in temp_root.iterdir():
        if not candidate.name.startswith("streaming-mbox-"):
            continue
        try:
            age = now - candidate.stat().st_mtime
        except FileNotFoundError:
            continue
        if age < max_age_seconds:
            continue
        if candidate.is_file() or candidate.is_symlink():
            candidate.unlink(missing_ok=True)
            removed += 1
    return removed


def _streaming_mbox_lock_path(root: Path | None = None) -> Path:
    return _streaming_mbox_temp_root(root) / ".streaming-mbox.lock"


def _acquire_streaming_mbox_lock(root: Path | None = None) -> int:
    if streaming_mbox_max_concurrent_jobs() != 1:
        return -1
    lock_path = _streaming_mbox_lock_path(root)
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise ValueError("streaming_mbox_concurrent_job_limit") from exc
    os.write(fd, _utc_timestamp().encode("utf-8"))
    return fd


def _release_streaming_mbox_lock(fd: int, root: Path | None = None) -> None:
    if fd >= 0:
        os.close(fd)
        _streaming_mbox_lock_path(root).unlink(missing_ok=True)


def _ensure_streaming_mbox_disk_capacity(root: Path | None = None) -> None:
    temp_root = _streaming_mbox_temp_root(root)
    free_bytes = shutil.disk_usage(temp_root).free
    required = streaming_mbox_max_bytes() + streaming_mbox_min_free_bytes()
    if free_bytes < required:
        raise ValueError("streaming_mbox_insufficient_storage")


def _sha256_file(path: Path, *, chunk_bytes: int | None = None) -> str:
    digest = hashlib.sha256()
    chunk_size = chunk_bytes or streaming_mbox_chunk_bytes()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _safe_mbox_filename(original_filename: str) -> str:
    filename = PurePath(str(original_filename or "").replace("\\", "/")).name
    if not filename or Path(filename).suffix.lower() != ".mbox":
        raise ValueError("streaming_mbox_invalid_extension")
    return filename


def _stream_to_governed_temp_file(
    file_handle: Any,
    *,
    root: Path | None = None,
) -> tuple[Path, str, int, str, str]:
    temp_root = _streaming_mbox_temp_root(root)
    cleanup_stale_streaming_mbox_temporary_files(root=root)
    max_bytes = streaming_mbox_max_bytes()
    chunk_size = streaming_mbox_chunk_bytes()
    digest = hashlib.sha256()
    received = 0
    started_at = _utc_timestamp()
    fd, temp_name = tempfile.mkstemp(prefix=f"streaming-mbox-{uuid.uuid4().hex}-", suffix=".upload", dir=temp_root)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as output:
            while True:
                chunk = file_handle.read(chunk_size)
                if isinstance(chunk, str):
                    chunk = chunk.encode("utf-8")
                if not chunk:
                    break
                if not isinstance(chunk, bytes):
                    raise ValueError("streaming_mbox_invalid_content")
                received += len(chunk)
                if received > max_bytes:
                    raise ValueError("streaming_mbox_file_too_large")
                digest.update(chunk)
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temp_path, 0o600)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
    if received <= 0:
        temp_path.unlink(missing_ok=True)
        raise ValueError("streaming_mbox_empty")
    completed_at = _utc_timestamp()
    return temp_path, digest.hexdigest(), received, started_at, completed_at


def store_streaming_mbox_pending_document(
    *,
    file_handle: Any,
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
    keywords: Any = None,
    actor: str = "admin",
    uploaded_at: str | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    filename = _safe_mbox_filename(original_filename)
    normalized = _normalize_intake_metadata(
        title=title,
        institution_source=institution_source,
        document_date=document_date,
        category=category,
        description=description,
        visibility=visibility,
        notes=notes,
    )
    destination_root = (root or intake_root()).resolve(strict=False)
    destination_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    _ensure_streaming_mbox_disk_capacity(destination_root)
    lock_fd = _acquire_streaming_mbox_lock(destination_root)
    temp_path: Path | None = None
    try:
        if hasattr(file_handle, "seek"):
            file_handle.seek(0)
        temp_path, digest, received, started_at, completed_at = _stream_to_governed_temp_file(
            file_handle,
            root=destination_root,
        )
        email_metadata = parse_mbox_archive_metadata_from_file(
            temp_path,
            max_archive_bytes=streaming_mbox_max_bytes(),
        )
        validation_completed_at = _utc_timestamp()
        stored_digest = _sha256_file(temp_path)
        if stored_digest != digest:
            raise ValueError("streaming_mbox_finalisation_failed")
        item_dir = destination_root / digest
        if item_dir.exists():
            raise ValueError("document_intake_duplicate")
        item_dir.mkdir(mode=0o700)
        stored_filename = f"pending-{digest}{DOCUMENT_TYPE_EXTENSIONS['mbox']}"
        file_path = item_dir / stored_filename
        metadata_path = item_dir / "metadata.json"
        timestamp = uploaded_at or _utc_timestamp()
        document_identifier = assign_document_identifier(
            digest,
            assigned_at=timestamp,
            root=destination_root,
        )
        email_metadata["intake_mode"] = "governed_streaming_mbox"
        email_metadata["streaming_upload_started_at"] = started_at
        email_metadata["streaming_upload_completed_at"] = completed_at
        email_metadata["streaming_validation_completed_at"] = validation_completed_at
        email_metadata["streaming_finalised_at"] = timestamp
        email_metadata["streaming_chunk_bytes"] = streaming_mbox_chunk_bytes()
        email_metadata["streaming_max_upload_bytes"] = streaming_mbox_max_bytes()
        metadata = {
            "intake_id": digest,
            "document_identifier": document_identifier,
            "status": "pending",
            "original_filename": filename,
            "stored_filename": stored_filename,
            "content_type": DOCUMENT_TYPE_MEDIA_TYPES["mbox"],
            "document_type": "mbox",
            "document_format": document_type_label("mbox"),
            "media_family": DOCUMENT_TYPE_MEDIA_FAMILIES["mbox"],
            "file_size_bytes": received,
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
            "keywords": normalize_document_keywords(keywords),
            "tags": normalize_document_keywords(keywords),
            "proposed_storage_location": str(file_path),
            "public_record_mutation": False,
            "intake_mode": "governed_streaming_mbox",
            "status_updated_at": timestamp,
            "status_history": [
                {
                    "previous_status": None,
                    "new_status": "pending",
                    "timestamp": timestamp,
                    "actor": str(actor or "admin"),
                    "note": "Document uploaded to pending intake through Governed Streaming Mailbox Intake.",
                    "document_identifier": document_identifier,
                }
            ],
            "email_metadata": email_metadata,
        }
        try:
            temp_path.replace(file_path)
            temp_path = None
            os.chmod(file_path, 0o600)
            metadata_path.write_text(
                json.dumps(metadata, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            os.chmod(metadata_path, 0o600)
        except Exception as exc:
            file_path.unlink(missing_ok=True)
            metadata_path.unlink(missing_ok=True)
            try:
                item_dir.rmdir()
            except OSError:
                pass
            raise ValueError("streaming_mbox_finalisation_failed") from exc
        return metadata
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        _release_streaming_mbox_lock(lock_fd, destination_root)


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
    keywords: Any = None,
    actor: str = "admin",
    uploaded_at: str | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    document_type, normalized_type, filename = validate_document_file(
        data, original_filename, content_type
    )

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
    sha512_digest = hashlib.sha512(data).hexdigest()
    normalized_keywords = normalize_document_keywords(keywords)
    workbook_metadata = (
        spreadsheet_workbook_metadata(data, document_type)
        if document_type in {"xls", "xlsx"}
        else None
    )
    if document_type == "eml":
        email_metadata = validate_email_document(data)
    elif document_type == "msg":
        email_metadata = validate_outlook_msg_document(data)
    elif document_type == "emlx":
        email_metadata = validate_apple_emlx_document(data)
    elif document_type == "mbox":
        email_metadata = validate_mbox_archive_document(data)
    else:
        email_metadata = None
    destination_root = (root or intake_root()).resolve(strict=False)
    destination_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    item_dir = destination_root / digest
    if item_dir.exists():
        raise ValueError("document_intake_duplicate")
    item_dir.mkdir(mode=0o700)

    stored_filename = f"pending-{digest}{DOCUMENT_TYPE_EXTENSIONS[document_type]}"
    file_path = item_dir / stored_filename
    metadata_path = item_dir / "metadata.json"
    timestamp = uploaded_at or _utc_timestamp()
    document_identifier = assign_document_identifier(
        digest,
        assigned_at=timestamp,
        root=destination_root,
    )
    metadata = {
        "intake_id": digest,
        "document_identifier": document_identifier,
        "status": "pending",
        "original_filename": filename,
        "stored_filename": stored_filename,
        "content_type": normalized_type,
        "document_type": document_type,
        "document_format": document_type_label(document_type),
        "media_family": DOCUMENT_TYPE_MEDIA_FAMILIES[document_type],
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
        "keywords": normalized_keywords,
        "tags": normalized_keywords,
        "proposed_storage_location": str(file_path),
        "public_record_mutation": False,
        "status_updated_at": timestamp,
        "status_history": [
            {
                "previous_status": None,
                "new_status": "pending",
                "timestamp": timestamp,
                "actor": str(actor or "admin"),
                "note": "Document uploaded to pending intake.",
                "document_identifier": document_identifier,
            }
        ],
    }
    if workbook_metadata:
        metadata["workbook_metadata"] = workbook_metadata
    if email_metadata:
        metadata["email_metadata"] = email_metadata
    if document_type in {"pst", "ost"}:
        metadata["sha512_hash"] = sha512_digest
        outlook_archive_metadata = build_outlook_archive_metadata(
            data=data,
            filename=filename,
            document_type=document_type,
            content_type=content_type,
            uploaded_at=timestamp,
            actor=actor,
        )
        outlook_archive_metadata.update(
            {
                "storage_path": str(file_path),
                "preservation_timestamp": timestamp,
                "preservation_completed_at": timestamp,
                "preservation_complete": True,
                "hash_verification_status": "verified",
                "inspection_complete": False,
                "inspection_timestamp": None,
                "archive_job_id": None,
                "latest_archive_job_id": None,
            }
        )
        metadata["outlook_archive_metadata"] = outlook_archive_metadata
    elif document_type == "gmail_takeout":
        metadata["sha512_hash"] = sha512_digest
        gmail_metadata = build_gmail_takeout_metadata(
            data=data,
            filename=filename,
            content_type=content_type,
            uploaded_at=timestamp,
            actor=actor,
        )
        gmail_metadata.update(
            {
                "storage_path": str(file_path),
                "preservation_timestamp": timestamp,
                "preservation_completed_at": timestamp,
                "inspection_complete": False,
                "inspection_timestamp": None,
                "latest_archive_job_id": None,
            }
        )
        metadata["gmail_takeout_metadata"] = gmail_metadata
    elif document_type == "imap_acquisition":
        metadata["sha512_hash"] = sha512_digest
        imap_metadata = build_imap_acquisition_metadata(
            data=data,
            filename=filename,
            content_type=content_type,
            uploaded_at=timestamp,
            actor=actor,
        )
        imap_metadata.update(
            {
                "storage_path": str(file_path),
                "preservation_timestamp": timestamp,
                "preservation_completed_at": timestamp,
                "inspection_complete": False,
                "inspection_timestamp": None,
                "latest_archive_job_id": None,
                "acquisition_status": "preserved",
                "acquisition_progress": 50,
            }
        )
        metadata["imap_acquisition_metadata"] = imap_metadata
    try:
        file_path.write_bytes(data)
        os.chmod(file_path, 0o600)
        metadata_path.write_text(
            json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.chmod(metadata_path, 0o600)
        if document_type in {"eml", "msg", "emlx", "mbox"} and int(
            (email_metadata or {}).get("attachment_count") or 0
        ):
            if document_type == "eml":
                from api.email_attachment_preservation import preserve_rfc5322_attachments

                preserve_attachments = preserve_rfc5322_attachments
            elif document_type == "msg":
                from api.email_attachment_preservation import (
                    preserve_outlook_msg_attachments,
                )

                preserve_attachments = preserve_outlook_msg_attachments
            elif document_type == "emlx":
                from api.email_attachment_preservation import (
                    preserve_apple_emlx_attachments,
                )

                preserve_attachments = preserve_apple_emlx_attachments
            if document_type != "mbox":
                try:
                    relationships = preserve_attachments(
                        metadata, data, root=destination_root
                    )
                    metadata["email_attachment_preservation"] = [
                        {
                            "relationship_id": relationship.get("relationship_id"),
                            "attachment_index": relationship.get("attachment_index"),
                            "attachment_document_id": relationship.get("attachment_document_id"),
                            "relationship_type": relationship.get("relationship_type"),
                            "extraction_status": relationship.get("extraction_status"),
                            "extraction_failure_reason": relationship.get("extraction_failure_reason"),
                        }
                        for relationship in relationships
                    ]
                except Exception as exc:
                    metadata["email_attachment_preservation"] = [
                        {
                            "relationship_type": "Email attachment",
                            "extraction_status": "failed",
                            "extraction_failure_reason": str(exc),
                        }
                    ]
            else:
                # mbox: the authoritative mailbox bytes are already stored.
                # Iterate contained messages, recover each message's exact RFC
                # 5322 byte range from the preserved .mbox file, and preserve
                # attachments per message. Per-message failures are isolated so
                # one malformed message cannot discard sibling successes.
                from api.email_attachment_preservation import (
                    preserve_mbox_message_attachments,
                )

                preservation_summary: list[dict[str, Any]] = []
                for message in (email_metadata or {}).get("messages") or []:
                    if not message.get("parsed") or int(
                        message.get("attachment_count") or 0
                    ) <= 0:
                        continue
                    byte_start = int(message.get("byte_start") or 0)
                    byte_end = int(message.get("byte_end") or 0)
                    if byte_end <= byte_start:
                        continue
                    try:
                        with file_path.open("rb") as mbox_handle:
                            mbox_handle.seek(byte_start)
                            message_bytes = mbox_handle.read(byte_end - byte_start)
                        relationships = preserve_mbox_message_attachments(
                            metadata,
                            message_bytes,
                            message_index=int(message.get("message_index") or 0),
                            root=destination_root,
                        )
                    except Exception as exc:
                        preservation_summary.append(
                            {
                                "message_index": message.get("message_index"),
                                "relationship_type": "Email attachment",
                                "extraction_status": "failed",
                                "extraction_failure_reason": str(exc),
                            }
                        )
                        continue
                    preservation_summary.extend(
                        {
                            "message_index": message.get("message_index"),
                            "relationship_id": relationship.get("relationship_id"),
                            "attachment_index": relationship.get("attachment_index"),
                            "attachment_document_id": relationship.get("attachment_document_id"),
                            "relationship_type": relationship.get("relationship_type"),
                            "extraction_status": relationship.get("extraction_status"),
                            "extraction_failure_reason": relationship.get("extraction_failure_reason"),
                        }
                        for relationship in relationships
                    )
                metadata["email_attachment_preservation"] = preservation_summary
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


def store_email_attachment_document(
    *,
    source_identity: str,
    data: bytes,
    original_filename: str | None,
    display_title: str,
    content_type: str | None,
    institution_source: str,
    document_date: str,
    visibility: str,
    provenance: dict[str, Any],
    actor: str = "system:email-attachment-preservation",
    preserved_at: str | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Preserve one source attachment occurrence in the normal document lifecycle."""

    normalized_source_identity = str(source_identity or "").strip().lower()
    if not re.fullmatch(r"[a-f0-9]{64}", normalized_source_identity):
        raise ValueError("email_attachment_source_identity_invalid")
    if not isinstance(data, bytes):
        raise ValueError("email_attachment_bytes_invalid")
    if len(data) > DEFAULT_MAX_BYTES:
        raise ValueError("document_intake_file_too_large")

    intake_id = hashlib.sha256(
        f"email-attachment-document\0{normalized_source_identity}".encode("utf-8")
    ).hexdigest()
    sha256_digest = hashlib.sha256(data).hexdigest()
    sha512_digest = hashlib.sha512(data).hexdigest()
    filename_value = str(original_filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    filename_value = "".join(
        character for character in filename_value if ord(character) >= 32 and character != "\x7f"
    ).strip()
    safe_title = str(display_title or "").strip() or "Email attachment"
    suffix = Path(filename_value).suffix.lower()
    if not re.fullmatch(r"\.[a-z0-9]{1,15}", suffix):
        suffix = ".eml" if str(content_type or "").split(";", 1)[0].lower() == "message/rfc822" else ".bin"
    stored_filename = f"pending-{intake_id}{suffix}"
    timestamp = preserved_at or _utc_timestamp()
    normalized_visibility = str(visibility or "private").strip().lower()
    if normalized_visibility not in VALID_VISIBILITY:
        normalized_visibility = "private"

    destination_root = (root or intake_root()).resolve(strict=False)
    destination_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    item_dir = destination_root / intake_id
    metadata_path = item_dir / "metadata.json"
    file_path = item_dir / stored_filename
    if metadata_path.is_file():
        existing = load_pending_document(intake_id, root=destination_root)
        existing_path, _ = intake_document_file(intake_id, metadata=existing, root=destination_root)
        if (
            existing.get("sha256_hash") != sha256_digest
            or existing.get("sha512_hash") != sha512_digest
            or (existing.get("attachment_preservation_metadata") or {}).get("source_identity")
            != normalized_source_identity
            or Path(existing_path).read_bytes() != data
        ):
            raise ValueError("email_attachment_identity_collision")
        return existing
    if item_dir.exists():
        raise ValueError("email_attachment_identity_collision")

    item_dir.mkdir(mode=0o700)
    document_identifier = assign_document_identifier(
        intake_id, assigned_at=timestamp, root=destination_root
    )
    normalized_content_type = (
        str(content_type or "application/octet-stream").split(";", 1)[0].strip().lower()
        or "application/octet-stream"
    )
    attachment_metadata = dict(provenance)
    attachment_metadata.update(
        {
            "source_identity": normalized_source_identity,
            "original_filename": filename_value or None,
            "display_title": safe_title,
            "filename_generated": not bool(filename_value),
            "mime_type": normalized_content_type,
            "file_size_bytes": len(data),
            "sha256_hash": sha256_digest,
            "sha512_hash": sha512_digest,
            "preservation_timestamp": timestamp,
            "preservation_status": "preserved",
        }
    )
    metadata = {
        "intake_id": intake_id,
        "document_identifier": document_identifier,
        "status": "pending",
        "original_filename": filename_value or f"attachment-{normalized_source_identity[:12]}{suffix}",
        "stored_filename": stored_filename,
        "content_type": normalized_content_type,
        "document_type": "email_attachment",
        "document_format": DOCUMENT_TYPE_LABELS["email_attachment"],
        "media_family": DOCUMENT_TYPE_MEDIA_FAMILIES["email_attachment"],
        "file_size_bytes": len(data),
        "sha256_hash": sha256_digest,
        "sha512_hash": sha512_digest,
        "title": safe_title,
        "institution_source": str(institution_source or "Source email").strip(),
        "document_date": str(document_date or timestamp[:10]).strip(),
        "upload_date": timestamp,
        "category": "Email Attachment",
        "description": "Attachment preserved independently from its source email.",
        "visibility": normalized_visibility,
        "notes": "Created through governed email attachment preservation. No Canonical Record was created.",
        "reference_identifier": None,
        "keywords": [],
        "tags": [],
        "proposed_storage_location": str(file_path),
        "public_record_mutation": False,
        "status_updated_at": timestamp,
        "status_history": [
            {
                "previous_status": None,
                "new_status": "pending",
                "timestamp": timestamp,
                "actor": str(actor or "system:email-attachment-preservation"),
                "note": "Attachment preserved as an independent Published Document intake object.",
                "document_identifier": document_identifier,
            }
        ],
        "attachment_preservation_metadata": attachment_metadata,
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
        try:
            item_dir.rmdir()
        except OSError:
            pass
        raise
    return metadata


def _apply_loaded_document_defaults(metadata: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(metadata, dict):
        raise ValueError("document_intake_not_found")
    metadata.setdefault("document_type", normalized_document_type(metadata))
    metadata.setdefault("document_format", document_type_label(metadata["document_type"]))
    metadata.setdefault("content_type", document_media_type(metadata))
    metadata.setdefault("media_family", document_media_family(metadata))
    metadata.setdefault(
        "keywords", normalize_document_keywords(metadata.get("keywords") or metadata.get("tags"))
    )
    metadata.setdefault("tags", metadata["keywords"])
    return metadata


def load_pending_document_read_only(
    intake_id: str, *, root: Path | None = None
) -> dict[str, Any]:
    """Load existing intake metadata without assigning identifiers or persisting defaults."""

    if not _SAFE_ID_RE.fullmatch(str(intake_id or "")):
        raise ValueError("document_intake_not_found")
    destination_root = (root or intake_root()).resolve(strict=False)
    metadata_path = destination_root / intake_id / "metadata.json"
    if not metadata_path.is_file():
        raise ValueError("document_intake_not_found")
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("document_intake_not_found") from exc
    if str(metadata.get("intake_id") or "") != str(intake_id):
        raise ValueError("document_intake_not_found")
    return _apply_loaded_document_defaults(metadata)


def load_pending_document(intake_id: str, *, root: Path | None = None) -> dict[str, Any]:
    if not _SAFE_ID_RE.fullmatch(str(intake_id or "")):
        raise ValueError("document_intake_not_found")
    destination_root = (root or intake_root()).resolve(strict=False)
    metadata_path = destination_root / intake_id / "metadata.json"
    if not metadata_path.is_file():
        raise ValueError("document_intake_not_found")
    metadata = _apply_loaded_document_defaults(
        json.loads(metadata_path.read_text(encoding="utf-8"))
    )
    _ensure_document_identifier(metadata, root=destination_root, persist=True)
    return metadata


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
            metadata.setdefault("document_type", normalized_document_type(metadata))
            metadata.setdefault("document_format", document_type_label(metadata["document_type"]))
            metadata.setdefault("content_type", document_media_type(metadata))
            metadata.setdefault("media_family", document_media_family(metadata))
            metadata.setdefault("keywords", normalize_document_keywords(metadata.get("keywords") or metadata.get("tags")))
            metadata.setdefault("tags", metadata["keywords"])
            _ensure_document_identifier(metadata, root=destination_root, persist=True)
            items.append(metadata)
    return sorted(items, key=lambda item: (item.get("upload_date", ""), item["intake_id"]), reverse=True)


def list_intake_documents_read_only(*, root: Path | None = None) -> list[dict[str, Any]]:
    """List intake metadata without identifier assignment or sidecar writes."""
    destination_root = (root or intake_root()).resolve(strict=False)
    if not destination_root.is_dir():
        return []
    items: list[dict[str, Any]] = []
    for metadata_path in destination_root.glob("*/metadata.json"):
        try:
            metadata = load_pending_document_read_only(
                metadata_path.parent.name, root=destination_root
            )
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if metadata.get("status") in INTAKE_STATUSES:
            items.append(metadata)
    return sorted(
        items,
        key=lambda item: (item.get("upload_date", ""), item["intake_id"]),
        reverse=True,
    )


def list_pending_documents(*, root: Path | None = None) -> list[dict[str, Any]]:
    return [
        item for item in list_intake_documents(root=root) if item["status"] == "pending"
    ]


def _prepare_loaded_intake_status_transition(
    metadata: dict[str, Any],
    new_status: str,
    *,
    actor: str,
    actor_role: str,
    note: str | None,
    root: Path | None,
) -> dict[str, Any]:
    current_status = metadata.get("status")
    normalized_status = str(new_status or "").strip().lower()
    normalized_actor = str(actor or "").strip() or "admin"
    normalized_role = str(actor_role or "").strip() or "unavailable"
    rationale = str(note or "").strip() or None
    if current_status not in INTAKE_STATUSES:
        raise ValueError("document_intake_status_invalid")
    if normalized_status not in INTAKE_STATUSES:
        raise ValueError("document_intake_status_invalid")
    if normalized_status not in VALID_STATUS_TRANSITIONS[current_status]:
        raise ValueError("document_intake_transition_invalid")
    if rationale is not None and len(rationale) > 500:
        raise ValueError("document_intake_rationale_too_long")
    if normalized_status in {"approved", "published", "rejected", "archived"} and not rationale:
        raise ValueError("document_intake_rationale_required")

    sha256_hash = str(metadata.get("sha256_hash") or "").strip().lower() or None
    sha512_hash = str(metadata.get("sha512_hash") or "").strip().lower() or None
    if normalized_status in {"approved", "published"} and not sha256_hash:
        raise ValueError("document_intake_decision_hash_required")
    authoritative_identifier = _registered_document_identifier_read_only(
        str(metadata.get("intake_id") or ""), root=root
    )
    if authoritative_identifier:
        metadata["document_identifier"] = authoritative_identifier
    else:
        authoritative_identifier = (
            str(metadata.get("document_identifier") or "").strip() or None
        )
    return {
        "metadata": metadata,
        "intake_id": str(metadata.get("intake_id") or ""),
        "document_identifier": authoritative_identifier,
        "previous_status": str(current_status),
        "new_status": normalized_status,
        "actor": normalized_actor,
        "actor_role": normalized_role,
        "rationale": rationale,
        "sha256_hash": sha256_hash,
        "sha512_hash": sha512_hash,
    }


def prepare_intake_status_transition(
    intake_id: str,
    new_status: str,
    *,
    actor: str = "admin",
    actor_role: str = "unavailable",
    note: str | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Validate and capture a proposed lifecycle decision without writing it."""

    metadata = load_pending_document_read_only(intake_id, root=root)
    return _prepare_loaded_intake_status_transition(
        metadata,
        new_status,
        actor=actor,
        actor_role=actor_role,
        note=note,
        root=root,
    )


def update_intake_status(
    intake_id: str,
    new_status: str,
    *,
    actor: str = "admin",
    actor_role: str = "unavailable",
    note: str | None = None,
    notes: str | None = None,
    changed_at: str | None = None,
    root: Path | None = None,
    lifecycle_db_path: Path | str | None = None,
) -> dict[str, Any]:
    metadata = load_pending_document_read_only(intake_id, root=root)
    current_status = metadata.get("status")
    normalized_status = str(new_status or "").strip().lower()
    normalized_actor = str(actor or "").strip() or "admin"
    normalized_role = str(actor_role or "").strip() or "unavailable"
    rationale = str(note or "").strip() or None
    if current_status not in INTAKE_STATUSES:
        raise ValueError("document_intake_status_invalid")
    if normalized_status not in INTAKE_STATUSES:
        raise ValueError("document_intake_status_invalid")
    if lifecycle_db_path is not None:
        resolved_lifecycle_db_path = Path(lifecycle_db_path)
    elif root is not None:
        resolved_lifecycle_db_path = Path(root).resolve(strict=False).parent / "records.db"
    elif os.getenv("RECORDS_DB_PATH"):
        resolved_lifecycle_db_path = Path(str(os.environ["RECORDS_DB_PATH"]))
    else:
        resolved_lifecycle_db_path = Path("records.db")

    # An identical repeated POST after successful projection is idempotent.
    if normalized_status == current_status:
        latest_history = (metadata.get("status_history") or [])[-1:]
        decision_key = (
            str(latest_history[0].get("lifecycle_decision_key") or "").strip()
            if latest_history and isinstance(latest_history[0], dict)
            else ""
        )
        existing = (
            lifecycle_decision_by_key(decision_key, db_path=resolved_lifecycle_db_path)
            if decision_key
            else None
        )
        if existing and all(
            (
                existing.get("new_status") == normalized_status,
                existing.get("actor") == normalized_actor,
                existing.get("actor_role") == normalized_role,
                existing.get("rationale") == rationale,
                existing.get("sha256_hash")
                == (str(metadata.get("sha256_hash") or "").strip().lower() or None),
                existing.get("sha512_hash")
                == (str(metadata.get("sha512_hash") or "").strip().lower() or None),
            )
        ):
            return metadata
        raise ValueError("document_intake_transition_invalid")
    prepared = _prepare_loaded_intake_status_transition(
        metadata,
        normalized_status,
        actor=normalized_actor,
        actor_role=normalized_role,
        note=rationale,
        root=root,
    )
    metadata = prepared["metadata"]

    history = list(metadata.get("status_history") or [])
    if not history:
        history.append(
            {
                "previous_status": None,
                "new_status": current_status,
                "timestamp": metadata.get("upload_date") or changed_at or _utc_timestamp(),
                "actor": "admin",
                "note": "Existing intake state recorded.",
            }
        )
    sha256_hash = prepared["sha256_hash"]
    sha512_hash = prepared["sha512_hash"]
    authoritative_identifier = prepared["document_identifier"]
    applied_keys = {
        str(event.get("lifecycle_decision_key") or "").strip()
        for event in history
        if isinstance(event, dict) and event.get("lifecycle_decision_key")
    }
    decision, _is_retry = record_lifecycle_decision(
        intake_id=str(metadata.get("intake_id") or intake_id),
        document_identifier=authoritative_identifier,
        previous_status=str(current_status),
        new_status=normalized_status,
        actor=normalized_actor,
        actor_role=normalized_role,
        rationale=rationale,
        sha256_hash=sha256_hash,
        sha512_hash=sha512_hash,
        applied_decision_keys=applied_keys,
        decided_at=changed_at,
        db_path=resolved_lifecycle_db_path,
    )
    timestamp = str(decision["decided_at"])
    history.append(
        {
            "previous_status": current_status,
            "new_status": normalized_status,
            "timestamp": timestamp,
            "actor": normalized_actor,
            "note": rationale,
            "lifecycle_decision_key": decision["decision_key"],
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
    _write_metadata(intake_id, metadata, root=root, assign_identifier=False)
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
    intake_id: str,
    metadata: dict[str, Any],
    *,
    root: Path | None = None,
    assign_identifier: bool = True,
) -> None:
    if not _SAFE_ID_RE.fullmatch(str(intake_id or "")):
        raise ValueError("document_intake_not_found")
    destination_root = (root or intake_root()).resolve(strict=False)
    item_dir = destination_root / intake_id
    metadata_path = item_dir / "metadata.json"
    if not metadata_path.is_file():
        raise ValueError("document_intake_not_found")
    try:
        current_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        current_metadata = {}
    if assign_identifier:
        current_identifier = str(current_metadata.get("document_identifier") or "").strip()
        if current_identifier:
            metadata["document_identifier"] = assign_document_identifier(
                str(intake_id),
                assigned_at=str(
                    current_metadata.get("upload_date")
                    or current_metadata.get("status_updated_at")
                    or ""
                ).strip()
                or None,
                root=destination_root,
                existing_identifier=current_identifier,
            )
        else:
            metadata["document_identifier"] = assign_document_identifier(
                str(intake_id),
                assigned_at=str(
                    metadata.get("upload_date")
                    or metadata.get("status_updated_at")
                    or ""
                ).strip()
                or None,
                root=destination_root,
                existing_identifier=str(metadata.get("document_identifier") or "").strip() or None,
            )
    else:
        registered_identifier = _registered_document_identifier_read_only(
            str(intake_id), root=destination_root
        )
        if registered_identifier:
            metadata["document_identifier"] = registered_identifier
    temporary_path = item_dir / "metadata.json.tmp"
    try:
        temporary_path.write_text(
            json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, metadata_path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _flatten_search_value(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        values = [stripped]
        if stripped[:1] in {"[", "{"}:
            try:
                parsed = json.loads(stripped)
            except (TypeError, json.JSONDecodeError):
                parsed = None
            if parsed is not None:
                values.extend(_flatten_search_value(parsed))
        if "," in stripped:
            values.extend(part.strip() for part in stripped.split(",") if part.strip())
        return values
    if isinstance(value, dict):
        values: list[str] = []
        for key, nested in value.items():
            values.extend(_flatten_search_value(key))
            values.extend(_flatten_search_value(nested))
        return values
    if isinstance(value, (list, tuple, set)):
        values = []
        for nested in value:
            values.extend(_flatten_search_value(nested))
        return values
    return [str(value).strip()] if str(value).strip() else []


def build_document_search_text(document: dict[str, Any]) -> str:
    """Return stable derived search text without mutating document metadata."""
    field_values: list[Any] = [
        document.get("title"),
        document.get("description"),
        document.get("institution_source"),
        document.get("institution"),
        document.get("document_identifier"),
        document.get("reference_identifier"),
        document.get("document_date"),
        document.get("publication_date"),
        document.get("category"),
        document.get("original_filename"),
        document.get("filename"),
        document.get("document_type"),
        document.get("document_format"),
        document.get("media_family"),
        document.get("workbook_metadata"),
        document.get("ocr_text"),
        document.get("body_text"),
        document.get("keywords"),
        document.get("tags"),
    ]
    field_values.extend(email_projection_search_values(document))
    field_values.extend(outlook_archive_search_values(document))
    field_values.extend(gmail_takeout_search_values(document))
    field_values.extend(imap_acquisition_search_values(document))
    flattened: list[str] = []
    seen: set[str] = set()
    for value in field_values:
        for text in _flatten_search_value(value):
            normalized = _WHITESPACE_RE.sub(" ", text).strip()
            if not normalized:
                continue
            key = normalized.casefold()
            if key in seen:
                continue
            seen.add(key)
            flattened.append(normalized)
    return " ".join(flattened).casefold()


def document_search_tokens(query: str | None) -> list[str]:
    return [
        token.casefold()
        for token in _SEARCH_SPLIT_RE.split(str(query or "").strip())
        if token.strip()
    ]


def document_matches_search(document: dict[str, Any], query: str | None) -> bool:
    tokens = document_search_tokens(query)
    if not tokens:
        return True
    searchable = build_document_search_text(document)
    return all(token in searchable for token in tokens)


def document_search_index_failures(*, root: Path | None = None) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    for item in list_intake_documents(root=root):
        if item.get("status") != "published":
            continue
        try:
            build_document_search_text(item)
        except Exception as exc:  # pragma: no cover - defensive reporting path.
            LOGGER.exception(
                "Failed to derive public document search text for %s",
                item.get("intake_id"),
            )
            failures.append(
                {
                    "intake_id": item.get("intake_id"),
                    "title": item.get("title"),
                    "error": exc.__class__.__name__,
                }
            )
    return failures


def reindex_published_document_search(*, root: Path | None = None) -> dict[str, Any]:
    indexed = 0
    failures = []
    for item in list_intake_documents(root=root):
        if item.get("status") != "published":
            continue
        try:
            build_document_search_text(item)
        except Exception as exc:  # pragma: no cover - defensive reporting path.
            LOGGER.exception(
                "Failed to derive public document search text for %s",
                item.get("intake_id"),
            )
            failures.append(
                {
                    "intake_id": item.get("intake_id"),
                    "title": item.get("title"),
                    "error": exc.__class__.__name__,
                }
            )
        else:
            indexed += 1
    return {"indexed": indexed, "failures": failures}


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
    normalized_institution = str(institution or "").strip().casefold()
    normalized_category = str(category or "").strip().casefold()
    normalized_year = str(publication_year or "").strip()

    def matches(item: dict[str, Any]) -> bool:
        try:
            query_matches = document_matches_search(item, query)
        except Exception:
            LOGGER.exception(
                "Failed to derive public document search text for %s",
                item.get("intake_id"),
            )
            query_matches = False
        if not query_matches:
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
    try:
        metadata = load_pending_document(document_id, root=root)
    except ValueError:
        metadata = find_document_by_reference(
            document_id,
            root=root,
            published_only=True,
        )
        if metadata is None:
            raise ValueError("public_document_not_found") from None
    if metadata.get("status") != "published":
        raise ValueError("public_document_not_found")
    metadata["publication_date"] = _publication_date(metadata)
    return metadata


def intake_document_file(
    document_id: str,
    *,
    metadata: dict[str, Any] | None = None,
    root: Path | None = None,
) -> tuple[Path, dict[str, Any]]:
    loaded_metadata = metadata or load_pending_document(document_id, root=root)
    destination_root = (root or intake_root()).resolve(strict=False)
    stored_filename = loaded_metadata.get("stored_filename") or (
        f"pending-{document_id}{document_storage_extension(loaded_metadata)}"
    )
    file_path = (destination_root / document_id / str(stored_filename)).resolve(strict=False)
    try:
        file_path.relative_to(destination_root)
    except ValueError as exc:
        raise ValueError("public_document_not_found") from exc
    if not file_path.is_file():
        raise ValueError("public_document_not_found")
    return file_path, loaded_metadata


def published_document_file(
    document_id: str, *, root: Path | None = None
) -> tuple[Path, dict[str, Any]]:
    metadata = load_published_document(document_id, root=root)
    return intake_document_file(document_id, metadata=metadata, root=root)


def _publication_date(metadata: dict[str, Any]) -> str:
    if metadata.get("publication_date"):
        return str(metadata["publication_date"])
    for event in reversed(metadata.get("status_history") or []):
        if event.get("new_status") == "published" and event.get("timestamp"):
            return str(event["timestamp"])
    return str(metadata.get("status_updated_at") or metadata.get("upload_date") or "")
