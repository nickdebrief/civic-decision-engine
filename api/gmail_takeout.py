from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import uuid
import zipfile
from io import BytesIO
from contextlib import contextmanager
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser
from pathlib import Path, PurePosixPath
from typing import Any, Iterator

from api.email_documents import (
    MAX_ATTACHMENT_COUNT,
    MAX_DECODED_ATTACHMENT_BYTES,
    parse_email_metadata,
)


GMAIL_TAKEOUT_SOURCE_FORMAT = "gmail_takeout"
GMAIL_TAKEOUT_PARSER_VERSION = "stage40-gmail-takeout-v1"
GMAIL_TAKEOUT_PROJECTION_VERSION = "stage40-projection-v1"
GMAIL_TAKEOUT_PROJECTION_STORE = ".gmail_takeout_projections"
MAX_GMAIL_TAKEOUT_ENTRIES = 10000
MAX_GMAIL_TAKEOUT_UNCOMPRESSED_BYTES = 1024 * 1024 * 1024
MAX_GMAIL_TAKEOUT_EXPANSION_RATIO = 100
MAX_GMAIL_LABELS = 5000
MAX_GMAIL_THREADS = 250000
MAX_GMAIL_MESSAGES = 250000
MAX_GMAIL_MESSAGE_BYTES = 128 * 1024 * 1024
MAX_GMAIL_MBOX_LINE_BYTES = 64 * 1024
MAX_GMAIL_BODY_PREVIEW_CHARS = 4000
_SAFE_ID_RE = re.compile(r"^[a-f0-9]{64}$")
_MBOX_SEPARATOR_RE = re.compile(
    br"^From [^\r\n]{1,200} (?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) "
    br"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) +\d{1,2} "
    br"\d{2}:\d{2}:\d{2}(?: [+-]\d{4})? \d{4}\r?\n?$"
)


class GmailTakeoutError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _safe_zip_path(value: str) -> bool:
    path = PurePosixPath(str(value or ""))
    return bool(value) and not path.is_absolute() and ".." not in path.parts and "\\" not in value


def _is_gmail_mbox_name(value: str) -> bool:
    parts = [part.casefold() for part in PurePosixPath(value).parts]
    return bool(parts and parts[-1].endswith(".mbox") and "mail" in parts and ("takeout" in parts or parts[0] == "mail"))


def _validate_zip(path: Path) -> list[zipfile.ZipInfo]:
    try:
        with zipfile.ZipFile(path) as package:
            infos = package.infolist()
            if not infos or len(infos) > MAX_GMAIL_TAKEOUT_ENTRIES:
                raise GmailTakeoutError("gmail_takeout_entry_limit_exceeded")
            total_uncompressed = 0
            total_compressed = 0
            mboxes: list[zipfile.ZipInfo] = []
            for info in infos:
                if not _safe_zip_path(info.filename):
                    raise GmailTakeoutError("gmail_takeout_unsafe_path")
                mode = info.external_attr >> 16
                if stat.S_ISLNK(mode):
                    raise GmailTakeoutError("gmail_takeout_symlink_not_allowed")
                if info.flag_bits & 0x1:
                    raise GmailTakeoutError("gmail_takeout_encrypted_not_allowed")
                total_uncompressed += int(info.file_size or 0)
                total_compressed += max(1, int(info.compress_size or 0))
                if _is_gmail_mbox_name(info.filename) and not info.is_dir():
                    mboxes.append(info)
            if not mboxes:
                raise GmailTakeoutError("gmail_takeout_mail_not_found")
            if total_uncompressed > MAX_GMAIL_TAKEOUT_UNCOMPRESSED_BYTES:
                raise GmailTakeoutError("gmail_takeout_uncompressed_limit_exceeded")
            if (
                total_uncompressed > 5 * 1024 * 1024
                and total_uncompressed / total_compressed > MAX_GMAIL_TAKEOUT_EXPANSION_RATIO
            ):
                raise GmailTakeoutError("gmail_takeout_expansion_ratio_exceeded")
            return mboxes
    except zipfile.BadZipFile as exc:
        raise GmailTakeoutError("gmail_takeout_invalid_zip") from exc


def validate_gmail_takeout_archive(data: bytes) -> dict[str, Any]:
    if not data:
        raise GmailTakeoutError("gmail_takeout_file_required")
    with tempfile.NamedTemporaryFile(suffix=".zip") as handle:
        handle.write(data)
        handle.flush()
        infos = _validate_zip(Path(handle.name))
    return {
        "source_format": GMAIL_TAKEOUT_SOURCE_FORMAT,
        "mailbox_count": len(infos),
        "mbox_entries": [info.filename for info in infos],
        "parser_version": GMAIL_TAKEOUT_PARSER_VERSION,
    }


def package_gmail_takeout_directory(entries: list[tuple[str, bytes]]) -> bytes:
    """Create a deterministic storage envelope without changing selected file bytes."""

    if not entries or len(entries) > MAX_GMAIL_TAKEOUT_ENTRIES:
        raise GmailTakeoutError("gmail_takeout_entry_limit_exceeded")
    normalized: list[tuple[str, bytes]] = []
    total = 0
    for name, data in entries:
        relative = str(name or "").replace("\\", "/").lstrip("/")
        if not _safe_zip_path(relative) or not isinstance(data, bytes):
            raise GmailTakeoutError("gmail_takeout_unsafe_path")
        total += len(data)
        if total > MAX_GMAIL_TAKEOUT_UNCOMPRESSED_BYTES:
            raise GmailTakeoutError("gmail_takeout_uncompressed_limit_exceeded")
        normalized.append((relative, data))
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as package:
        for relative, data in sorted(normalized, key=lambda item: item[0].casefold()):
            info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = 0o600 << 16
            package.writestr(info, data)
    packaged = buffer.getvalue()
    validate_gmail_takeout_archive(packaged)
    return packaged


def build_gmail_takeout_metadata(
    *,
    data: bytes,
    filename: str,
    content_type: str | None,
    uploaded_at: str,
    actor: str,
) -> dict[str, Any]:
    inspection = validate_gmail_takeout_archive(data)
    return {
        "source_format": GMAIL_TAKEOUT_SOURCE_FORMAT,
        "archive_type": "Gmail Takeout",
        "archive_type_label": "Google Takeout Gmail Export",
        "original_filename": filename,
        "file_size_bytes": len(data),
        "declared_mime_type": str(content_type or "").split(";", 1)[0].strip() or None,
        "upload_timestamp": uploaded_at,
        "uploader": str(actor or "admin"),
        "parser_contract": "ArchiveParser",
        "parser_available": True,
        "parser_status": "parser_available",
        "parser_status_message": "Built-in Gmail Takeout adapter available.",
        "parser_version": GMAIL_TAKEOUT_PARSER_VERSION,
        "mailbox_count": inspection["mailbox_count"],
        "mbox_entries": inspection["mbox_entries"],
        "preservation_complete": True,
        "hash_verification_status": "verified",
        "projection_state": "pending",
        "governance_boundary": (
            "The Google Takeout export is preserved unchanged as the authoritative archive. "
            "Labels, threads, messages, and attachments are private governed projections; "
            "none is published or promoted automatically."
        ),
    }


def is_gmail_takeout_document(document: dict[str, Any]) -> bool:
    return str(document.get("document_type") or "").strip().casefold() == GMAIL_TAKEOUT_SOURCE_FORMAT


def gmail_takeout_search_values(document: dict[str, Any]) -> list[Any]:
    """Return public-safe archive metadata without indexing private projections."""

    metadata = document.get("gmail_takeout_metadata")
    if not isinstance(metadata, dict):
        return []
    return [
        metadata.get("archive_type"),
        metadata.get("archive_type_label"),
        metadata.get("original_filename"),
        metadata.get("parser_status"),
        metadata.get("parser_version"),
        metadata.get("projection_state"),
    ]


def _label_id(label: str) -> str:
    return "label-" + hashlib.sha256(label.casefold().encode("utf-8")).hexdigest()[:20]


def _message_projection_id(identity: str) -> str:
    return "gmail-message-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]


def _thread_id(message: Any, message_id: str, projection_id: str) -> str:
    value = str(message.get("X-GM-THRID") or message.get("X-Gmail-Thread-ID") or "").strip()
    if value:
        return value[:240]
    references = str(message.get("References") or message.get("In-Reply-To") or "").strip()
    seed = references.split()[0] if references else (message_id or projection_id)
    return "thread-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:20]


def _labels(message: Any, fallback: str) -> list[str]:
    raw = str(message.get("X-Gmail-Labels") or "")
    values = [value.strip() for value in raw.split(",") if value.strip()]
    if fallback and fallback not in values:
        values.append(fallback)
    return sorted(set(values), key=str.casefold)


def _iter_mbox_message_bytes(path: Path) -> Iterator[bytes]:
    current: tempfile.SpooledTemporaryFile[bytes] | None = None
    count = 0
    with path.open("rb") as handle:
        for line_number, line in enumerate(handle):
            if len(line) > MAX_GMAIL_MBOX_LINE_BYTES:
                raise GmailTakeoutError("gmail_takeout_mbox_line_too_large")
            boundary = bool(_MBOX_SEPARATOR_RE.match(line))
            if line_number == 0 and line.startswith(b"From ") and not boundary:
                raise GmailTakeoutError("gmail_takeout_invalid_mbox")
            if boundary:
                if current is not None:
                    current.seek(0)
                    yield current.read()
                    current.close()
                count += 1
                if count > MAX_GMAIL_MESSAGES:
                    raise GmailTakeoutError("gmail_takeout_message_limit_exceeded")
                current = tempfile.SpooledTemporaryFile(max_size=5 * 1024 * 1024, mode="w+b")
                continue
            if current is not None:
                current.write(line)
                if current.tell() > MAX_GMAIL_MESSAGE_BYTES:
                    current.close()
                    raise GmailTakeoutError("gmail_takeout_message_too_large")
    if current is not None:
        current.seek(0)
        yield current.read()
        current.close()
    if count == 0:
        raise GmailTakeoutError("gmail_takeout_invalid_mbox")


@contextmanager
def _mailbox_paths(source: Path) -> Iterator[list[tuple[str, Path]]]:
    if source.is_dir():
        source_is_mail_directory = source.name.casefold() == "mail"
        paths = [
            (path.relative_to(source).as_posix(), path)
            for path in sorted(source.rglob("*.mbox"))
            if path.is_file()
            and (
                source_is_mail_directory
                or _is_gmail_mbox_name(path.relative_to(source).as_posix())
            )
        ]
        if not paths:
            raise GmailTakeoutError("gmail_takeout_mail_not_found")
        yield paths
        return
    infos = _validate_zip(source)
    with tempfile.TemporaryDirectory(prefix="cde-gmail-takeout-") as temporary:
        root = Path(temporary)
        materialized: list[tuple[str, Path]] = []
        with zipfile.ZipFile(source) as package:
            for index, info in enumerate(sorted(infos, key=lambda item: item.filename), start=1):
                destination = root / f"mail-{index:05d}.mbox"
                with package.open(info) as source_handle, destination.open("xb") as target:
                    shutil.copyfileobj(source_handle, target, length=1024 * 1024)
                os.chmod(destination, 0o600)
                materialized.append((info.filename, destination))
        yield materialized


class GmailTakeoutParser:
    source_format = GMAIL_TAKEOUT_SOURCE_FORMAT

    def __init__(self) -> None:
        self._attachments: list[dict[str, Any]] = []

    def supports(self, file_path: Path) -> bool:
        path = Path(file_path)
        try:
            if path.is_dir():
                with _mailbox_paths(path):
                    return True
            return path.suffix.casefold() == ".zip" and bool(_validate_zip(path))
        except (OSError, GmailTakeoutError):
            return False

    def inspect(self, file_path: Path) -> dict[str, Any]:
        with _mailbox_paths(Path(file_path)) as mailboxes:
            return {
                "archive_validity": "valid_gmail_takeout",
                "mailbox_count": len(mailboxes),
                "top_level_folder_count": len(mailboxes),
                "archive_health": "projectable",
                "parser_warnings": [],
                "parser_version": GMAIL_TAKEOUT_PARSER_VERSION,
            }

    def project(self, file_path: Path) -> dict[str, Any]:
        self._attachments = []
        projected: dict[str, dict[str, Any]] = {}
        folder_labels: set[str] = set()
        message_count = 0
        with _mailbox_paths(Path(file_path)) as mailboxes:
            for source_name, mailbox_path in mailboxes:
                fallback_label = Path(source_name).stem
                for raw in _iter_mbox_message_bytes(mailbox_path):
                    message_count += 1
                    if message_count > MAX_GMAIL_MESSAGES:
                        raise GmailTakeoutError("gmail_takeout_message_limit_exceeded")
                    message = BytesParser(policy=policy.default).parsebytes(raw)
                    parsed = parse_email_metadata(raw)
                    message_id = str(parsed.get("message_id") or "").strip()
                    raw_digest = hashlib.sha256(raw).hexdigest()
                    identity = message_id.casefold() if message_id else raw_digest
                    projection_id = _message_projection_id(identity)
                    labels = _labels(message, fallback_label)
                    folder_labels.update(labels)
                    existing = projected.get(projection_id)
                    if existing:
                        existing["labels"] = sorted(
                            set(existing.get("labels") or []).union(labels), key=str.casefold
                        )
                        existing["label_ids"] = [_label_id(label) for label in existing["labels"]]
                        continue
                    thread_id = _thread_id(message, message_id, projection_id)
                    primary_label = labels[0] if labels else fallback_label
                    attachments_metadata: list[dict[str, Any]] = []
                    attachment_index = 0
                    for part_index, part in enumerate(message.walk(), start=1):
                        filename = str(part.get_filename() or "").strip()
                        disposition = str(part.get_content_disposition() or "").strip()
                        if not filename and disposition != "attachment":
                            continue
                        attachment_index += 1
                        if attachment_index > MAX_ATTACHMENT_COUNT:
                            raise GmailTakeoutError("gmail_takeout_attachment_limit_exceeded")
                        payload = part.get_payload(decode=True) or b""
                        if len(payload) > MAX_DECODED_ATTACHMENT_BYTES:
                            raise GmailTakeoutError("gmail_takeout_attachment_too_large")
                        source_attachment_id = f"{projection_id}:part-{part_index}"
                        descriptor = {
                            "source_attachment_identifier": source_attachment_id,
                            "filename": filename or f"attachment-{attachment_index}",
                            "mime_type": part.get_content_type() or "application/octet-stream",
                            "file_size_bytes": len(payload),
                            "sha256_hash": hashlib.sha256(payload).hexdigest(),
                        }
                        attachments_metadata.append(descriptor)
                        self._attachments.append(
                            {
                                **descriptor,
                                "message_projection_id": projection_id,
                                "data": payload,
                            }
                        )
                    projected[projection_id] = {
                        "projection_id": projection_id,
                        "message_id": message_id or None,
                        "subject": parsed.get("subject_decoded"),
                        "sender": parsed.get("from_raw") or parsed.get("sender_raw"),
                        "recipients": [parsed.get("to_raw")] if parsed.get("to_raw") else [],
                        "cc": [parsed.get("cc_raw")] if parsed.get("cc_raw") else [],
                        "sent_timestamp": parsed.get("date_header_parsed") or parsed.get("date_header_raw"),
                        "received_timestamp": parsed.get("date_header_parsed") or parsed.get("date_header_raw"),
                        "message_class": "RFC5322",
                        "conversation_id": thread_id,
                        "thread_index": thread_id,
                        "thread_id": thread_id,
                        "references": parsed.get("references") or [],
                        "in_reply_to": parsed.get("in_reply_to"),
                        "labels": labels,
                        "label_ids": [_label_id(label) for label in labels],
                        "attachment_count": len(attachments_metadata),
                        "attachments_metadata": attachments_metadata,
                        "plain_text_preview": str(parsed.get("plain_text_body") or "")[:MAX_GMAIL_BODY_PREVIEW_CHARS],
                        "sanitized_html_preview": str(parsed.get("sanitized_html_body") or "")[:MAX_GMAIL_BODY_PREVIEW_CHARS],
                        "folder_id": _label_id(primary_label),
                        "folder_path": primary_label,
                        "source_identifier": message_id or raw_digest,
                        "source_mailbox": source_name,
                        "message_digest": raw_digest,
                    }
        if len(folder_labels) > MAX_GMAIL_LABELS:
            raise GmailTakeoutError("gmail_takeout_label_limit_exceeded")
        messages = sorted(projected.values(), key=lambda item: str(item["projection_id"]))
        thread_members: dict[str, list[str]] = {}
        for message in messages:
            thread_members.setdefault(str(message["thread_id"]), []).append(str(message["projection_id"]))
        if len(thread_members) > MAX_GMAIL_THREADS:
            raise GmailTakeoutError("gmail_takeout_thread_limit_exceeded")
        folders = [
            {
                "folder_id": _label_id(label),
                "name": label,
                "path": label,
                "source_identifier": label,
                "message_count": sum(label in (message.get("labels") or []) for message in messages),
                "attachment_count": sum(
                    int(message.get("attachment_count") or 0)
                    for message in messages
                    if label in (message.get("labels") or [])
                ),
            }
            for label in sorted(folder_labels, key=str.casefold)
        ]
        return {
            "source_format": GMAIL_TAKEOUT_SOURCE_FORMAT,
            "mailbox_name": "Google Takeout Gmail",
            "folders": folders,
            "messages": messages,
            "threads": [
                {"thread_id": key, "message_projection_ids": sorted(value)}
                for key, value in sorted(thread_members.items())
            ],
            "projection_warnings": [],
        }

    def iter_attachments(self) -> Iterator[dict[str, Any]]:
        yield from list(self._attachments)


def _projection_path(document_id: str, root: Path) -> Path:
    if not _SAFE_ID_RE.fullmatch(str(document_id or "")):
        raise GmailTakeoutError("gmail_takeout_projection_not_found")
    directory = root / GMAIL_TAKEOUT_PROJECTION_STORE
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    return directory / f"{document_id}.json"


def load_gmail_takeout_projection(document_id: str, *, root: Path) -> dict[str, Any]:
    path = _projection_path(document_id, root)
    if not path.is_file():
        raise GmailTakeoutError("gmail_takeout_projection_not_found")
    return json.loads(path.read_text(encoding="utf-8"))


def save_gmail_takeout_projection(
    document: dict[str, Any],
    raw_projection: dict[str, Any],
    *,
    root: Path,
    actor: str,
) -> dict[str, Any]:
    document_id = str(document.get("intake_id") or "")
    timestamp = _utc_timestamp()
    job_id = "gmail-job-" + uuid.uuid4().hex
    folders = list(raw_projection.get("folders") or [])
    folder_by_id = {str(folder.get("folder_id") or ""): folder for folder in folders}
    messages = []
    for raw in raw_projection.get("messages") or []:
        message = dict(raw)
        folder = folder_by_id.get(str(message.get("folder_id") or ""), {})
        message["provenance"] = {
            "archive_id": document_id,
            "job_id": job_id,
            "parser_version": GMAIL_TAKEOUT_PARSER_VERSION,
            "projection_timestamp": timestamp,
            "source_folder": message.get("folder_path"),
            "source_identifier": message.get("source_identifier"),
            "extraction_method": "gmail_takeout_parser_projection",
            "thread_id": message.get("thread_id"),
            "label_ids": message.get("label_ids") or [],
        }
        messages.append(message)
    normalized_folders = []
    for folder in folders:
        value = dict(folder)
        value["provenance"] = {
            "archive_id": document_id,
            "job_id": job_id,
            "parser_version": GMAIL_TAKEOUT_PARSER_VERSION,
            "projection_timestamp": timestamp,
            "source_folder": value.get("path"),
            "source_identifier": value.get("source_identifier"),
            "extraction_method": "gmail_takeout_parser_projection",
        }
        normalized_folders.append(value)
    projection = {
        "projection_version": GMAIL_TAKEOUT_PROJECTION_VERSION,
        "projection_state": "projected",
        "source_format": GMAIL_TAKEOUT_SOURCE_FORMAT,
        "archive_id": document_id,
        "document_identifier": document.get("document_identifier"),
        "job_id": job_id,
        "parser_version": GMAIL_TAKEOUT_PARSER_VERSION,
        "projection_timestamp": timestamp,
        "projection_actor": str(actor or "admin"),
        "mailbox": {"name": raw_projection.get("mailbox_name"), "archive_type": "Gmail Takeout"},
        "folders": normalized_folders,
        "messages": messages,
        "threads": list(raw_projection.get("threads") or []),
        "statistics": {
            "folder_count": len(normalized_folders),
            "message_count": len(messages),
            "thread_count": len(raw_projection.get("threads") or []),
            "attachment_count": sum(int(message.get("attachment_count") or 0) for message in messages),
        },
        "warnings": list(raw_projection.get("projection_warnings") or []),
        "governance_boundary": (
            "Gmail Takeout projections are private derived administrative representations. "
            "The preserved export remains authoritative and no contained object is published "
            "or promoted automatically."
        ),
    }
    path = _projection_path(document_id, root)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(projection, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)
    return projection


def validate_gmail_message_promotion(
    document_id: str,
    message_id: str,
    *,
    root: Path,
):
    from api.document_intake import load_pending_document
    from api.outlook_archive_promotion import (
        OutlookArchivePromotionContext,
        OutlookArchivePromotionError,
    )

    try:
        document = load_pending_document(document_id, root=root)
        projection = load_gmail_takeout_projection(document_id, root=root)
    except (ValueError, GmailTakeoutError) as exc:
        raise OutlookArchivePromotionError("archive_promotion_projection_unavailable") from exc
    if not is_gmail_takeout_document(document):
        raise OutlookArchivePromotionError("archive_promotion_archive_invalid")
    if projection.get("projection_state") not in {"projected", "rebuilt"}:
        raise OutlookArchivePromotionError("archive_promotion_projection_incomplete")
    message = next(
        (
            item
            for item in projection.get("messages") or []
            if str(item.get("projection_id") or "") == str(message_id)
        ),
        None,
    )
    if not isinstance(message, dict):
        raise OutlookArchivePromotionError("archive_promotion_message_unavailable")
    folder = next(
        (
            item
            for item in projection.get("folders") or []
            if str(item.get("folder_id") or "") == str(message.get("folder_id") or "")
        ),
        None,
    )
    provenance = message.get("provenance")
    if not isinstance(folder, dict) or not isinstance(provenance, dict):
        raise OutlookArchivePromotionError("archive_promotion_provenance_missing")
    required = (
        projection.get("projection_version"),
        projection.get("job_id"),
        provenance.get("archive_id"),
        provenance.get("source_identifier"),
        document.get("sha256_hash"),
    )
    if any(not str(value or "").strip() for value in required):
        raise OutlookArchivePromotionError("archive_promotion_provenance_missing")
    if str(provenance.get("archive_id")) != str(document_id):
        raise OutlookArchivePromotionError("archive_promotion_projection_invalid")
    job = {
        "job_id": projection["job_id"],
        "document_id": document_id,
        "status": "completed",
        "inspection": {"inspection_complete": True},
        "source_format": GMAIL_TAKEOUT_SOURCE_FORMAT,
    }
    return OutlookArchivePromotionContext(
        document=document,
        projection=projection,
        folder=folder,
        message=message,
        job=job,
    )


def project_gmail_takeout_document(
    document_id: str,
    *,
    root: Path,
    actor: str,
) -> dict[str, Any]:
    from api.document_intake import intake_document_file, load_pending_document
    from api.outlook_archive_attachments import govern_archive_attachment_bytes

    document = load_pending_document(document_id, root=root)
    if not is_gmail_takeout_document(document):
        raise GmailTakeoutError("gmail_takeout_document_invalid")
    file_path, _ = intake_document_file(document_id, metadata=document, root=root)
    parser = GmailTakeoutParser()
    if not parser.supports(file_path):
        raise GmailTakeoutError("gmail_takeout_parser_unsupported")
    inspection = parser.inspect(file_path)
    raw_projection = parser.project(file_path)
    projection = save_gmail_takeout_projection(document, raw_projection, root=root, actor=actor)
    context_by_message = {
        str(message.get("projection_id") or ""): validate_gmail_message_promotion(
            document_id, str(message.get("projection_id") or ""), root=root
        )
        for message in projection.get("messages") or []
    }
    governed = []
    for attachment in parser.iter_attachments():
        context = context_by_message[str(attachment["message_projection_id"])]
        governed.append(
            govern_archive_attachment_bytes(
                context,
                data=attachment["data"],
                filename=attachment["filename"],
                mime_type=attachment["mime_type"],
                source_attachment_id=attachment["source_attachment_identifier"],
                archive_source=GMAIL_TAKEOUT_SOURCE_FORMAT,
                extracted_at=projection["projection_timestamp"],
                root=root,
            )
        )
    metadata_path = root / document_id / "metadata.json"
    updated = json.loads(metadata_path.read_text(encoding="utf-8"))
    gmail_metadata = updated.get("gmail_takeout_metadata") or {}
    gmail_metadata.update(
        {
            "inspection_complete": True,
            "inspection_timestamp": projection["projection_timestamp"],
            "archive_health": inspection.get("archive_health"),
            "latest_archive_job_id": projection["job_id"],
            "projection_state": projection["projection_state"],
            "folder_projection_performed": True,
            "message_projection_performed": True,
            "attachment_governance_performed": bool(governed),
        }
    )
    updated["gmail_takeout_metadata"] = gmail_metadata
    temporary = metadata_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(updated, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, metadata_path)
    return {"projection": projection, "attachments": governed, "inspection": inspection}
