from __future__ import annotations

import hashlib
import imaplib
import json
import os
import re
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, Iterator

from api.email_documents import (
    MAX_ATTACHMENT_COUNT,
    MAX_DECODED_ATTACHMENT_BYTES,
    parse_email_metadata,
)


IMAP_SOURCE_FORMAT = "imap_acquisition"
IMAP_PARSER_VERSION = "stage41-imap-acquisition-v1"
IMAP_PROJECTION_VERSION = "stage41-projection-v1"
IMAP_MANIFEST_PATH = "acquisition/manifest.json"
IMAP_PROJECTION_STORE = ".imap_acquisition_projections"
MAX_IMAP_FOLDERS = 5000
MAX_IMAP_MESSAGES = 250000
MAX_IMAP_MESSAGE_BYTES = 128 * 1024 * 1024
MAX_IMAP_ARCHIVE_BYTES = 1024 * 1024 * 1024
MAX_IMAP_BODY_PREVIEW_CHARS = 4000
IMAP_CONNECT_TIMEOUT_SECONDS = 30
_SAFE_ID_RE = re.compile(r"^[a-f0-9]{64}$")
_SAFE_HOST_RE = re.compile(r"^(?=.{1,253}$)[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?$")
_SAFE_ACQUISITION_RE = re.compile(r"^IMAP-[A-F0-9]{24}$")
_CREDENTIAL_KEYS = {"password", "credential", "credentials", "secret", "token", "username"}


class ImapAcquisitionError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ImapAcquisitionSettings:
    hostname: str
    username: str = field(repr=False)
    password: str = field(repr=False)
    mailbox_identifier: str
    selected_folders: tuple[str, ...]
    port: int = 993
    tls_mode: str = "ssl"


@dataclass(frozen=True)
class ImapAcquisitionResult:
    archive_bytes: bytes
    manifest: dict[str, Any]


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _folder_id(acquisition_id: str, folder: str) -> str:
    seed = f"{acquisition_id}\0{folder}".encode("utf-8")
    return "imap-folder-" + hashlib.sha256(seed).hexdigest()[:20]


def _message_projection_id(
    acquisition_id: str, folder: str, uid: str, message_id: str
) -> str:
    seed = "\0".join((acquisition_id, folder, uid, message_id.casefold())).encode("utf-8")
    return "imap-message-" + hashlib.sha256(seed).hexdigest()[:24]


def _thread_id(message: Any, message_id: str, projection_id: str) -> str:
    references = str(message.get("References") or message.get("In-Reply-To") or "").strip()
    seed = references.split()[0] if references else (message_id or projection_id)
    return "imap-thread-" + hashlib.sha256(seed.casefold().encode("utf-8")).hexdigest()[:20]


def _validate_settings(settings: ImapAcquisitionSettings) -> None:
    if not _SAFE_HOST_RE.fullmatch(str(settings.hostname or "").strip()):
        raise ImapAcquisitionError("imap_acquisition_hostname_invalid")
    if not 1 <= int(settings.port) <= 65535:
        raise ImapAcquisitionError("imap_acquisition_port_invalid")
    if settings.tls_mode not in {"ssl", "starttls"}:
        raise ImapAcquisitionError("imap_acquisition_tls_mode_invalid")
    if not str(settings.username or "").strip() or not str(settings.password or ""):
        raise ImapAcquisitionError("imap_acquisition_credentials_required")
    mailbox_identifier = str(settings.mailbox_identifier or "").strip()
    if not mailbox_identifier or len(mailbox_identifier) > 240 or any(
        character in mailbox_identifier for character in "\r\n"
    ):
        raise ImapAcquisitionError("imap_acquisition_mailbox_identifier_invalid")
    if mailbox_identifier.casefold() == str(settings.username).strip().casefold():
        raise ImapAcquisitionError("imap_acquisition_mailbox_identifier_is_credential")
    folders = tuple(str(value or "").strip() for value in settings.selected_folders)
    if not folders or len(folders) > MAX_IMAP_FOLDERS:
        raise ImapAcquisitionError("imap_acquisition_folders_required")
    if any(not value or len(value) > 1000 or "\x00" in value for value in folders):
        raise ImapAcquisitionError("imap_acquisition_folder_invalid")
    if len({value.casefold() for value in folders}) != len(folders):
        raise ImapAcquisitionError("imap_acquisition_duplicate_folder")


def _folder_name(value: bytes | str) -> str:
    text = value.decode("utf-8", "replace") if isinstance(value, bytes) else str(value)
    match = re.search(r'(?:^|\s)"((?:[^"\\]|\\.)*)"\s*$', text)
    if match:
        return match.group(1).replace(r"\"", '"').replace(r"\\", "\\")
    tail = text.rsplit(" ", 1)[-1].strip()
    return tail.strip('"')


def _imap_mailbox_argument(folder: str) -> str:
    return '"' + folder.replace("\\", "\\\\").replace('"', r'\"') + '"'


def _response_ok(response: Any) -> bool:
    return isinstance(response, tuple) and str(response[0]).upper() == "OK"


def _uidvalidity(client: Any) -> str:
    try:
        response = client.response("UIDVALIDITY")
    except Exception:
        return "unknown"
    values = response[1] if isinstance(response, tuple) and len(response) > 1 else None
    if isinstance(values, (list, tuple)) and values:
        value = values[0]
    else:
        value = values
    if isinstance(value, bytes):
        value = value.decode("ascii", "replace")
    normalized = str(value or "").strip()
    return normalized if normalized.isdigit() else "unknown"


def _uids(response: Any) -> list[str]:
    if not _response_ok(response):
        raise ImapAcquisitionError("imap_acquisition_message_enumeration_failed")
    payload = response[1]
    values: list[str] = []
    for item in payload if isinstance(payload, (list, tuple)) else [payload]:
        text = item.decode("ascii", "replace") if isinstance(item, bytes) else str(item or "")
        values.extend(value for value in text.split() if value.isdigit())
    if len(values) > MAX_IMAP_MESSAGES:
        raise ImapAcquisitionError("imap_acquisition_message_limit_exceeded")
    return sorted(set(values), key=lambda value: int(value))


def _fetched_rfc822(response: Any) -> bytes:
    if not _response_ok(response):
        raise ImapAcquisitionError("imap_acquisition_message_fetch_failed")
    payload = response[1]
    for item in payload if isinstance(payload, (list, tuple)) else [payload]:
        if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], bytes):
            data = item[1]
            if not data or len(data) > MAX_IMAP_MESSAGE_BYTES:
                raise ImapAcquisitionError("imap_acquisition_message_size_invalid")
            return data
    raise ImapAcquisitionError("imap_acquisition_message_fetch_failed")


def _default_client(settings: ImapAcquisitionSettings) -> Any:
    if settings.tls_mode == "ssl":
        return imaplib.IMAP4_SSL(
            settings.hostname,
            settings.port,
            timeout=IMAP_CONNECT_TIMEOUT_SECONDS,
        )
    client = imaplib.IMAP4(
        settings.hostname,
        settings.port,
        timeout=IMAP_CONNECT_TIMEOUT_SECONDS,
    )
    if not _response_ok(client.starttls()):
        raise ImapAcquisitionError("imap_acquisition_starttls_failed")
    return client


def _available_folders(client: Any) -> list[str]:
    response = client.list()
    if not _response_ok(response):
        raise ImapAcquisitionError("imap_acquisition_folder_discovery_failed")
    payload = response[1]
    folders = sorted(
        {
            _folder_name(value)
            for value in (payload if isinstance(payload, (list, tuple)) else [payload])
            if value is not None and _folder_name(value)
        },
        key=str.casefold,
    )
    if not folders or len(folders) > MAX_IMAP_FOLDERS:
        raise ImapAcquisitionError("imap_acquisition_folder_discovery_failed")
    return folders


def _archive_bytes(manifest: dict[str, Any], messages: dict[str, bytes]) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as package:
        for path, data in sorted(messages.items()):
            info = zipfile.ZipInfo(path, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = 0o600 << 16
            package.writestr(info, data)
        info = zipfile.ZipInfo(IMAP_MANIFEST_PATH, date_time=(1980, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_STORED
        info.external_attr = 0o600 << 16
        package.writestr(info, _canonical_json(manifest))
    data = buffer.getvalue()
    if len(data) > MAX_IMAP_ARCHIVE_BYTES:
        raise ImapAcquisitionError("imap_acquisition_archive_too_large")
    return data


def acquire_imap_archive(
    settings: ImapAcquisitionSettings,
    *,
    client_factory: Callable[[ImapAcquisitionSettings], Any] | None = None,
    acquired_at: str | None = None,
    acquisition_id: str | None = None,
) -> ImapAcquisitionResult:
    """Acquire one immutable, bounded IMAP snapshot; never retain credentials."""

    _validate_settings(settings)
    identifier = acquisition_id or ("IMAP-" + uuid.uuid4().hex[:24].upper())
    if not _SAFE_ACQUISITION_RE.fullmatch(identifier):
        raise ImapAcquisitionError("imap_acquisition_identifier_invalid")
    timestamp = acquired_at or _utc_timestamp()
    client = None
    selected = False
    messages: dict[str, bytes] = {}
    folder_records: list[dict[str, Any]] = []
    manifest_messages: list[dict[str, Any]] = []
    total_messages = 0
    try:
        client = (client_factory or _default_client)(settings)
        try:
            login_response = client.login(settings.username, settings.password)
        except Exception as exc:
            raise ImapAcquisitionError("imap_acquisition_authentication_failed") from exc
        if not _response_ok(login_response):
            raise ImapAcquisitionError("imap_acquisition_authentication_failed")
        available = _available_folders(client)
        by_name = {value.casefold(): value for value in available}
        selected_folders: list[str] = []
        for requested in settings.selected_folders:
            resolved = by_name.get(str(requested).casefold())
            if not resolved:
                raise ImapAcquisitionError("imap_acquisition_selected_folder_unavailable")
            selected_folders.append(resolved)
        for folder in selected_folders:
            if not _response_ok(client.select(_imap_mailbox_argument(folder), readonly=True)):
                raise ImapAcquisitionError("imap_acquisition_folder_select_failed")
            selected = True
            validity = _uidvalidity(client)
            folder_uids = _uids(client.uid("search", None, "ALL"))
            folder_identifier = _folder_id(identifier, folder)
            folder_records.append(
                {
                    "folder_id": folder_identifier,
                    "name": folder,
                    "uidvalidity": validity,
                    "uids": folder_uids,
                }
            )
            seen: set[str] = set()
            for uid in folder_uids:
                key = f"{folder_identifier}:{uid}"
                if key in seen:
                    raise ImapAcquisitionError("imap_acquisition_duplicate_message")
                seen.add(key)
                total_messages += 1
                if total_messages > MAX_IMAP_MESSAGES:
                    raise ImapAcquisitionError("imap_acquisition_message_limit_exceeded")
                raw = _fetched_rfc822(client.uid("fetch", uid, "(UID RFC822)"))
                path = f"messages/{folder_identifier}/{int(uid):020d}.eml"
                digest = hashlib.sha256(raw).hexdigest()
                parsed = BytesParser(policy=policy.default).parsebytes(raw, headersonly=True)
                manifest_messages.append(
                    {
                        "folder_id": folder_identifier,
                        "folder": folder,
                        "uidvalidity": validity,
                        "uid": uid,
                        "path": path,
                        "size": len(raw),
                        "sha256": digest,
                        "message_id": str(parsed.get("Message-ID") or "").strip() or None,
                    }
                )
                messages[path] = raw
            try:
                client.close()
            finally:
                selected = False
    except ImapAcquisitionError:
        raise
    except Exception as exc:
        raise ImapAcquisitionError("imap_acquisition_failed") from exc
    finally:
        if client is not None:
            if selected:
                try:
                    client.close()
                except Exception:
                    pass
            try:
                client.logout()
            except Exception:
                pass

    protocol_metadata = {
        "protocol": "IMAP4rev1",
        "transport": "implicit_tls" if settings.tls_mode == "ssl" else "starttls",
        "port": int(settings.port),
        "read_only": True,
        "acquisition_mode": "explicit_snapshot",
    }
    manifest_core = {
        "schema_version": 1,
        "source_format": IMAP_SOURCE_FORMAT,
        "acquisition_id": identifier,
        "acquisition_timestamp": timestamp,
        "server_hostname": settings.hostname,
        "mailbox_identifier": settings.mailbox_identifier,
        "selected_folders": folder_records,
        "protocol_metadata": protocol_metadata,
        "messages": sorted(
            manifest_messages,
            key=lambda item: (str(item["folder"]).casefold(), int(str(item["uid"]))),
        ),
    }
    manifest = dict(manifest_core)
    manifest["acquisition_hash"] = hashlib.sha256(_canonical_json(manifest_core)).hexdigest()
    archive = _archive_bytes(manifest, messages)
    validate_imap_acquisition_archive(archive)
    return ImapAcquisitionResult(archive_bytes=archive, manifest=manifest)


def _contains_credential_key(value: Any) -> bool:
    if isinstance(value, dict):
        return any(
            str(key).casefold() in _CREDENTIAL_KEYS or _contains_credential_key(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_credential_key(item) for item in value)
    return False


def is_imap_acquisition_archive(data: bytes) -> bool:
    try:
        with zipfile.ZipFile(BytesIO(data)) as package:
            return IMAP_MANIFEST_PATH in package.namelist()
    except (OSError, zipfile.BadZipFile):
        return False


def validate_imap_acquisition_archive(data: bytes) -> dict[str, Any]:
    if not data or len(data) > MAX_IMAP_ARCHIVE_BYTES:
        raise ImapAcquisitionError("imap_acquisition_archive_size_invalid")
    try:
        with zipfile.ZipFile(BytesIO(data)) as package:
            names = package.namelist()
            if len(names) > MAX_IMAP_MESSAGES + 1 or len(names) != len(set(names)):
                raise ImapAcquisitionError("imap_acquisition_archive_entries_invalid")
            if IMAP_MANIFEST_PATH not in names:
                raise ImapAcquisitionError("imap_acquisition_manifest_missing")
            for name in names:
                path = PurePosixPath(name)
                if path.is_absolute() or ".." in path.parts or "\\" in name:
                    raise ImapAcquisitionError("imap_acquisition_archive_path_invalid")
            manifest = json.loads(package.read(IMAP_MANIFEST_PATH).decode("utf-8"))
            if not isinstance(manifest, dict) or _contains_credential_key(manifest):
                raise ImapAcquisitionError("imap_acquisition_manifest_invalid")
            if manifest.get("source_format") != IMAP_SOURCE_FORMAT:
                raise ImapAcquisitionError("imap_acquisition_manifest_invalid")
            if not _SAFE_ACQUISITION_RE.fullmatch(str(manifest.get("acquisition_id") or "")):
                raise ImapAcquisitionError("imap_acquisition_manifest_invalid")
            messages = manifest.get("messages")
            folders = manifest.get("selected_folders")
            if not isinstance(messages, list) or not isinstance(folders, list) or not folders:
                raise ImapAcquisitionError("imap_acquisition_manifest_invalid")
            seen: set[tuple[str, str]] = set()
            for message in messages:
                if not isinstance(message, dict):
                    raise ImapAcquisitionError("imap_acquisition_manifest_invalid")
                key = (str(message.get("folder_id") or ""), str(message.get("uid") or ""))
                if not key[0] or not key[1].isdigit() or key in seen:
                    raise ImapAcquisitionError("imap_acquisition_duplicate_message")
                seen.add(key)
                path = str(message.get("path") or "")
                if path not in names or not path.startswith(f"messages/{key[0]}/"):
                    raise ImapAcquisitionError("imap_acquisition_message_missing")
                raw = package.read(path)
                if len(raw) != int(message.get("size") or -1):
                    raise ImapAcquisitionError("imap_acquisition_message_size_invalid")
                if hashlib.sha256(raw).hexdigest() != str(message.get("sha256") or ""):
                    raise ImapAcquisitionError("imap_acquisition_message_hash_invalid")
            core = dict(manifest)
            expected_hash = str(core.pop("acquisition_hash", ""))
            if hashlib.sha256(_canonical_json(core)).hexdigest() != expected_hash:
                raise ImapAcquisitionError("imap_acquisition_hash_invalid")
            return manifest
    except (zipfile.BadZipFile, json.JSONDecodeError, UnicodeDecodeError, KeyError) as exc:
        raise ImapAcquisitionError("imap_acquisition_archive_invalid") from exc


def build_imap_acquisition_metadata(
    *, data: bytes, filename: str, content_type: str | None, uploaded_at: str, actor: str
) -> dict[str, Any]:
    manifest = validate_imap_acquisition_archive(data)
    return {
        "source_format": IMAP_SOURCE_FORMAT,
        "archive_type": "IMAP Acquisition",
        "archive_type_label": "Governed IMAP Acquisition",
        "original_filename": filename,
        "file_size_bytes": len(data),
        "declared_mime_type": str(content_type or "").split(";", 1)[0].strip() or None,
        "upload_timestamp": uploaded_at,
        "uploader": str(actor or "admin"),
        "parser_contract": "ArchiveParser",
        "parser_available": True,
        "parser_status": "parser_available",
        "parser_status_message": "Built-in IMAP acquisition adapter available.",
        "parser_version": IMAP_PARSER_VERSION,
        "preservation_complete": True,
        "hash_verification_status": "verified",
        "projection_state": "pending",
        "acquisition_id": manifest["acquisition_id"],
        "acquisition_timestamp": manifest["acquisition_timestamp"],
        "acquisition_hash": manifest["acquisition_hash"],
        "server_hostname": manifest["server_hostname"],
        "mailbox_identifier": manifest["mailbox_identifier"],
        "selected_folders": [folder["name"] for folder in manifest["selected_folders"]],
        "folder_count": len(manifest["selected_folders"]),
        "message_count": len(manifest["messages"]),
        "protocol_metadata": manifest["protocol_metadata"],
        "governance_boundary": (
            "The IMAP acquisition envelope is preserved as authoritative acquisition evidence. "
            "Folders, threads, messages, and attachments are private governed projections; "
            "none is published or promoted automatically."
        ),
    }


def is_imap_acquisition_document(document: dict[str, Any]) -> bool:
    return str(document.get("document_type") or "").strip().casefold() == IMAP_SOURCE_FORMAT


def imap_acquisition_search_values(document: dict[str, Any]) -> list[Any]:
    metadata = document.get("imap_acquisition_metadata")
    if not isinstance(metadata, dict):
        return []
    return [
        metadata.get("archive_type"),
        metadata.get("archive_type_label"),
        metadata.get("mailbox_identifier"),
        metadata.get("parser_status"),
        metadata.get("projection_state"),
    ]


def _archive_manifest(path: Path) -> tuple[dict[str, Any], dict[str, bytes]]:
    data = path.read_bytes()
    manifest = validate_imap_acquisition_archive(data)
    with zipfile.ZipFile(BytesIO(data)) as package:
        messages = {
            str(item["path"]): package.read(str(item["path"]))
            for item in manifest.get("messages") or []
        }
    return manifest, messages


class ImapAcquisitionParser:
    source_format = IMAP_SOURCE_FORMAT

    def __init__(self) -> None:
        self._attachments: list[dict[str, Any]] = []

    def supports(self, file_path: Path) -> bool:
        try:
            validate_imap_acquisition_archive(Path(file_path).read_bytes())
            return True
        except (OSError, ImapAcquisitionError):
            return False

    def inspect(self, file_path: Path) -> dict[str, Any]:
        manifest, _ = _archive_manifest(Path(file_path))
        return {
            "archive_validity": "valid_imap_acquisition",
            "mailbox_count": 1,
            "top_level_folder_count": len(manifest["selected_folders"]),
            "archive_health": "projectable",
            "parser_warnings": [],
            "parser_version": IMAP_PARSER_VERSION,
        }

    def project(self, file_path: Path) -> dict[str, Any]:
        self._attachments = []
        manifest, archive_messages = _archive_manifest(Path(file_path))
        folders = [
            {
                "folder_id": item["folder_id"],
                "name": item["name"],
                "path": item["name"],
                "folder_path": item["name"],
                "source_identifier": item["name"],
                "uidvalidity": item["uidvalidity"],
                "uids": list(item["uids"]),
                "message_count": len(item["uids"]),
                "attachment_count": 0,
            }
            for item in manifest["selected_folders"]
        ]
        folder_by_id = {str(item["folder_id"]): item for item in folders}
        messages: list[dict[str, Any]] = []
        thread_members: dict[str, list[str]] = {}
        for source in manifest["messages"]:
            raw = archive_messages[str(source["path"])]
            email = BytesParser(policy=policy.default).parsebytes(raw)
            parsed = parse_email_metadata(raw)
            message_id = str(parsed.get("message_id") or source.get("message_id") or "").strip()
            projection_id = _message_projection_id(
                manifest["acquisition_id"], source["folder"], source["uid"], message_id
            )
            thread_id = _thread_id(email, message_id, projection_id)
            attachment_descriptors: list[dict[str, Any]] = []
            attachment_index = 0
            for part_index, part in enumerate(email.walk(), start=1):
                filename = str(part.get_filename() or "").strip()
                disposition = str(part.get_content_disposition() or "").strip()
                if not filename and disposition != "attachment":
                    continue
                attachment_index += 1
                if attachment_index > MAX_ATTACHMENT_COUNT:
                    raise ImapAcquisitionError("imap_acquisition_attachment_limit_exceeded")
                payload = part.get_payload(decode=True) or b""
                if len(payload) > MAX_DECODED_ATTACHMENT_BYTES:
                    raise ImapAcquisitionError("imap_acquisition_attachment_too_large")
                source_attachment_id = f"{source['folder_id']}:{source['uid']}:part-{part_index}"
                descriptor = {
                    "source_attachment_identifier": source_attachment_id,
                    "filename": filename or f"attachment-{attachment_index}",
                    "mime_type": part.get_content_type() or "application/octet-stream",
                    "file_size_bytes": len(payload),
                    "sha256_hash": hashlib.sha256(payload).hexdigest(),
                }
                attachment_descriptors.append(descriptor)
                self._attachments.append(
                    {
                        **descriptor,
                        "message_projection_id": projection_id,
                        "data": payload,
                    }
                )
            folder_by_id[str(source["folder_id"])]["attachment_count"] += len(
                attachment_descriptors
            )
            message = {
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
                "attachment_count": len(attachment_descriptors),
                "attachments_metadata": attachment_descriptors,
                "plain_text_preview": str(parsed.get("plain_text_body") or "")[
                    :MAX_IMAP_BODY_PREVIEW_CHARS
                ],
                "sanitized_html_preview": str(parsed.get("sanitized_html_body") or "")[
                    :MAX_IMAP_BODY_PREVIEW_CHARS
                ],
                "folder_id": source["folder_id"],
                "folder_path": source["folder"],
                "source_identifier": f"{source['folder']}:{source['uid']}",
                "source_uid": source["uid"],
                "uidvalidity": source["uidvalidity"],
                "message_digest": source["sha256"],
            }
            messages.append(message)
            thread_members.setdefault(thread_id, []).append(projection_id)
        return {
            "source_format": IMAP_SOURCE_FORMAT,
            "acquisition_id": manifest["acquisition_id"],
            "mailbox_name": manifest["mailbox_identifier"],
            "folders": sorted(folders, key=lambda item: str(item["name"]).casefold()),
            "messages": sorted(messages, key=lambda item: str(item["projection_id"])),
            "threads": [
                {"thread_id": key, "message_projection_ids": sorted(value)}
                for key, value in sorted(thread_members.items())
            ],
            "projection_warnings": [],
        }

    def iter_attachments(self) -> Iterable[dict[str, Any]]:
        yield from list(self._attachments)


def _projection_path(document_id: str, root: Path) -> Path:
    if not _SAFE_ID_RE.fullmatch(str(document_id or "")):
        raise ImapAcquisitionError("imap_acquisition_projection_not_found")
    directory = root / IMAP_PROJECTION_STORE
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    return directory / f"{document_id}.json"


def load_imap_acquisition_projection(document_id: str, *, root: Path) -> dict[str, Any]:
    path = _projection_path(document_id, root)
    if not path.is_file():
        raise ImapAcquisitionError("imap_acquisition_projection_not_found")
    return json.loads(path.read_text(encoding="utf-8"))


def save_imap_acquisition_projection(
    document: dict[str, Any], raw_projection: dict[str, Any], *, root: Path, actor: str
) -> dict[str, Any]:
    document_id = str(document.get("intake_id") or "")
    timestamp = _utc_timestamp()
    job_id = "imap-job-" + hashlib.sha256(
        f"{document_id}\0{raw_projection['acquisition_id']}".encode("utf-8")
    ).hexdigest()[:24]
    folders: list[dict[str, Any]] = []
    for raw in raw_projection.get("folders") or []:
        folder = dict(raw)
        folder["provenance"] = {
            "archive_id": document_id,
            "job_id": job_id,
            "parser_version": IMAP_PARSER_VERSION,
            "projection_timestamp": timestamp,
            "source_folder": folder.get("path"),
            "source_identifier": folder.get("source_identifier"),
            "extraction_method": "imap_explicit_acquisition_projection",
            "acquisition_id": raw_projection["acquisition_id"],
            "uidvalidity": folder.get("uidvalidity"),
        }
        folders.append(folder)
    messages: list[dict[str, Any]] = []
    for raw in raw_projection.get("messages") or []:
        message = dict(raw)
        message["provenance"] = {
            "archive_id": document_id,
            "job_id": job_id,
            "parser_version": IMAP_PARSER_VERSION,
            "projection_timestamp": timestamp,
            "source_folder": message.get("folder_path"),
            "source_identifier": message.get("source_identifier"),
            "extraction_method": "imap_explicit_acquisition_projection",
            "acquisition_id": raw_projection["acquisition_id"],
            "imap_uid": message.get("source_uid"),
            "uidvalidity": message.get("uidvalidity"),
            "thread_id": message.get("thread_id"),
        }
        messages.append(message)
    projection = {
        "projection_version": IMAP_PROJECTION_VERSION,
        "projection_state": "projected",
        "source_format": IMAP_SOURCE_FORMAT,
        "archive_id": document_id,
        "document_identifier": document.get("document_identifier"),
        "acquisition_id": raw_projection["acquisition_id"],
        "job_id": job_id,
        "parser_version": IMAP_PARSER_VERSION,
        "projection_timestamp": timestamp,
        "projection_actor": str(actor or "admin"),
        "mailbox": {"name": raw_projection.get("mailbox_name"), "archive_type": "IMAP"},
        "folders": folders,
        "messages": messages,
        "threads": list(raw_projection.get("threads") or []),
        "statistics": {
            "folder_count": len(folders),
            "message_count": len(messages),
            "thread_count": len(raw_projection.get("threads") or []),
            "attachment_count": sum(int(item.get("attachment_count") or 0) for item in messages),
        },
        "warnings": list(raw_projection.get("projection_warnings") or []),
        "governance_boundary": (
            "IMAP projections are private derived administrative representations. The "
            "preserved acquisition envelope remains authoritative and no contained object "
            "is published or promoted automatically."
        ),
    }
    path = _projection_path(document_id, root)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(projection, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)
    return projection


def validate_imap_message_promotion(document_id: str, message_id: str, *, root: Path):
    from api.document_intake import load_pending_document
    from api.outlook_archive_promotion import (
        OutlookArchivePromotionContext,
        OutlookArchivePromotionError,
    )

    try:
        document = load_pending_document(document_id, root=root)
        projection = load_imap_acquisition_projection(document_id, root=root)
    except (ValueError, ImapAcquisitionError) as exc:
        raise OutlookArchivePromotionError("archive_promotion_projection_unavailable") from exc
    if not is_imap_acquisition_document(document):
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
        provenance.get("imap_uid"),
        provenance.get("uidvalidity"),
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
        "source_format": IMAP_SOURCE_FORMAT,
    }
    return OutlookArchivePromotionContext(
        document=document,
        projection=projection,
        folder=folder,
        message=message,
        job=job,
    )


def project_imap_acquisition_document(
    document_id: str, *, root: Path, actor: str
) -> dict[str, Any]:
    from api.document_intake import intake_document_file, load_pending_document
    from api.attachment_governance import govern_attachment_bytes

    document = load_pending_document(document_id, root=root)
    if not is_imap_acquisition_document(document):
        raise ImapAcquisitionError("imap_acquisition_document_invalid")
    file_path, _ = intake_document_file(document_id, metadata=document, root=root)
    parser = ImapAcquisitionParser()
    inspection = parser.inspect(file_path)
    raw_projection = parser.project(file_path)
    projection = save_imap_acquisition_projection(document, raw_projection, root=root, actor=actor)
    context_by_message = {
        str(message["projection_id"]): validate_imap_message_promotion(
            document_id, str(message["projection_id"]), root=root
        )
        for message in projection.get("messages") or []
    }
    governed = []
    for attachment in parser.iter_attachments():
        context = context_by_message[str(attachment["message_projection_id"])]
        governed.append(
            govern_attachment_bytes(
                context,
                data=attachment["data"],
                filename=attachment["filename"],
                mime_type=attachment["mime_type"],
                source_attachment_id=attachment["source_attachment_identifier"],
                acquisition_source=IMAP_SOURCE_FORMAT,
                extracted_at=projection["projection_timestamp"],
                root=root,
            )
        )
    metadata_path = root / document_id / "metadata.json"
    updated = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata = updated.get("imap_acquisition_metadata") or {}
    metadata.update(
        {
            "inspection_complete": True,
            "inspection_timestamp": projection["projection_timestamp"],
            "archive_health": inspection.get("archive_health"),
            "latest_archive_job_id": projection["job_id"],
            "projection_state": projection["projection_state"],
            "folder_projection_performed": True,
            "message_projection_performed": True,
            "attachment_governance_performed": bool(governed),
            "acquisition_status": "completed",
            "acquisition_progress": 100,
        }
    )
    updated["imap_acquisition_metadata"] = metadata
    temporary = metadata_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(updated, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, metadata_path)
    return {"projection": projection, "attachments": governed, "inspection": inspection}


def acquire_imap_document(
    settings: ImapAcquisitionSettings,
    *,
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
    root: Path,
    client_factory: Callable[[ImapAcquisitionSettings], Any] | None = None,
    acquired_at: str | None = None,
    acquisition_id: str | None = None,
) -> dict[str, Any]:
    from api.document_intake import store_pending_document

    acquired = acquire_imap_archive(
        settings,
        client_factory=client_factory,
        acquired_at=acquired_at,
        acquisition_id=acquisition_id,
    )
    item = store_pending_document(
        data=acquired.archive_bytes,
        original_filename=f"{acquired.manifest['acquisition_id']}.imap.zip",
        content_type="application/vnd.cde.imap-acquisition+zip",
        title=title,
        institution_source=institution_source,
        document_date=document_date,
        category=category,
        description=description,
        visibility=visibility,
        notes=notes,
        reference_identifier=reference_identifier,
        keywords=keywords,
        actor=actor,
        uploaded_at=acquired.manifest["acquisition_timestamp"],
        root=root,
    )
    projected = project_imap_acquisition_document(
        str(item["intake_id"]), root=root, actor=actor
    )
    return {"document": item, "manifest": acquired.manifest, **projected}
