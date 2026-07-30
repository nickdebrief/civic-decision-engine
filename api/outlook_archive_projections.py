from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from api.document_intake import intake_root


OUTLOOK_ARCHIVE_PROJECTION_STORE = ".outlook_archive_projections"
OUTLOOK_ARCHIVE_PROJECTION_VERSION = "stage39c-projection-v1"
PROJECTION_STATES = {"pending", "projecting", "projected", "superseded", "rebuilt"}
MAX_PROJECTED_FOLDERS = 200000
MAX_PROJECTED_MESSAGES = 250000
MAX_PROJECTION_WARNINGS = 100
_SAFE_DOCUMENT_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]+$")


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _projection_root(root: Path | None = None) -> Path:
    path = (root or intake_root()).resolve(strict=False) / OUTLOOK_ARCHIVE_PROJECTION_STORE
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def _validate_document_id(document_id: str) -> str:
    text = str(document_id or "").strip()
    if not text or not _SAFE_DOCUMENT_ID_RE.fullmatch(text):
        raise ValueError("outlook_archive_projection_not_found")
    return text


def projection_path(document_id: str, *, root: Path | None = None) -> Path:
    return _projection_root(root) / f"{_validate_document_id(document_id)}.json"


def _save_projection(path: Path, payload: dict[str, Any]) -> None:
    temporary_path = path.with_suffix(".tmp")
    temporary_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.chmod(temporary_path, 0o600)
    os.replace(temporary_path, path)
    os.chmod(path, 0o600)


def load_outlook_archive_projection(
    document_id: str,
    *,
    root: Path | None = None,
) -> dict[str, Any]:
    path = projection_path(document_id, root=root)
    if not path.is_file():
        raise ValueError("outlook_archive_projection_not_found")
    return json.loads(path.read_text(encoding="utf-8"))


def projection_exists(document_id: str, *, root: Path | None = None) -> bool:
    return projection_path(document_id, root=root).is_file()


def _bounded_text(value: Any, *, limit: int = 500) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return text[:limit]


def _bounded_list(values: Any, *, limit: int = 50) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        candidates = [values]
    else:
        try:
            candidates = list(values)
        except TypeError:
            candidates = [values]
    result = []
    for value in candidates:
        text = _bounded_text(value, limit=240)
        if text:
            result.append(text)
        if len(result) >= limit:
            break
    return result


def _folder_id(folder: dict[str, Any], index: int) -> str:
    return _bounded_text(folder.get("folder_id") or folder.get("id"), limit=160) or f"folder-{index:06d}"


def _message_id(message: dict[str, Any], index: int) -> str:
    return _bounded_text(message.get("projection_id") or message.get("id"), limit=160) or f"message-{index:06d}"


def _normalise_folder(
    raw: dict[str, Any],
    *,
    index: int,
    document_id: str,
    job_id: str,
    parser_version: str | None,
    projection_timestamp: str,
) -> dict[str, Any]:
    folder_id = _folder_id(raw, index)
    parent_id = _bounded_text(raw.get("parent_id") or raw.get("parent_folder_id"), limit=160)
    folder_path = _bounded_text(raw.get("path") or raw.get("folder_path") or raw.get("name"), limit=1000)
    return {
        "folder_id": folder_id,
        "name": _bounded_text(raw.get("name") or raw.get("display_name"), limit=240) or folder_id,
        "parent_id": parent_id,
        "folder_path": folder_path or folder_id,
        "source_identifier": _bounded_text(raw.get("source_identifier") or raw.get("entry_id") or folder_id, limit=240),
        "message_count": int(raw.get("message_count") or 0),
        "subfolder_count": int(raw.get("subfolder_count") or 0),
        "attachment_count": int(raw.get("attachment_count") or 0),
        "projected_size_bytes": int(raw.get("projected_size_bytes") or 0),
        "provenance": {
            "archive_id": document_id,
            "job_id": job_id,
            "parser_version": parser_version,
            "projection_timestamp": projection_timestamp,
            "source_folder": folder_path or folder_id,
            "source_identifier": _bounded_text(raw.get("source_identifier") or raw.get("entry_id") or folder_id, limit=240),
            "extraction_method": "outlook_archive_parser_projection",
        },
    }


def _normalise_message(
    raw: dict[str, Any],
    *,
    index: int,
    document_id: str,
    job_id: str,
    parser_version: str | None,
    projection_timestamp: str,
) -> dict[str, Any]:
    message_id = _message_id(raw, index)
    folder_id = _bounded_text(raw.get("folder_id") or raw.get("source_folder_id"), limit=160)
    folder_path = _bounded_text(raw.get("folder_path") or raw.get("source_folder"), limit=1000)
    attachment_count = int(raw.get("attachment_count") or 0)
    return {
        "projection_id": message_id,
        "message_id": _bounded_text(raw.get("message_id") or raw.get("internet_message_id"), limit=500),
        "subject": _bounded_text(raw.get("subject"), limit=500),
        "sender": _bounded_text(raw.get("sender"), limit=500),
        "recipients": _bounded_list(raw.get("recipients") or raw.get("to"), limit=100),
        "cc": _bounded_list(raw.get("cc"), limit=100),
        "sent_timestamp": _bounded_text(raw.get("sent_timestamp") or raw.get("sent_time"), limit=80),
        "received_timestamp": _bounded_text(raw.get("received_timestamp") or raw.get("received_time"), limit=80),
        "message_class": _bounded_text(raw.get("message_class"), limit=120),
        "conversation_id": _bounded_text(raw.get("conversation_id"), limit=240),
        "thread_index": _bounded_text(raw.get("thread_index"), limit=500),
        "attachment_count": attachment_count,
        "read_status": _bounded_text(raw.get("read_status"), limit=80),
        "importance": _bounded_text(raw.get("importance"), limit=80),
        "categories": _bounded_list(raw.get("categories"), limit=50),
        "folder_id": folder_id,
        "folder_path": folder_path,
        "provenance": {
            "archive_id": document_id,
            "job_id": job_id,
            "parser_version": parser_version,
            "projection_timestamp": projection_timestamp,
            "source_folder": folder_path,
            "source_identifier": _bounded_text(
                raw.get("source_identifier")
                or raw.get("entry_id")
                or raw.get("message_id")
                or message_id,
                limit=500,
            ),
            "extraction_method": "outlook_archive_parser_projection",
        },
    }


def _statistics(folders: list[dict[str, Any]], messages: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "folder_count": len(folders),
        "message_count": len(messages),
        "subfolder_count": sum(1 for folder in folders if folder.get("parent_id")),
        "attachment_count": sum(int(message.get("attachment_count") or 0) for message in messages),
        "projected_size_bytes": sum(int(folder.get("projected_size_bytes") or 0) for folder in folders),
    }


def _parser_projection(parser: Any, file_path: Path) -> dict[str, Any] | None:
    project = getattr(parser, "project", None)
    if callable(project):
        payload = project(file_path)
        return payload if isinstance(payload, dict) else {}
    return None


def build_outlook_archive_projection(
    *,
    document: dict[str, Any],
    job: dict[str, Any],
    file_path: Path,
    parser: Any,
    root: Path | None = None,
    rebuild: bool = False,
) -> dict[str, Any] | None:
    raw_projection = _parser_projection(parser, file_path)
    if raw_projection is None:
        return None

    document_id = str(document.get("intake_id") or "")
    job_id = str(job.get("job_id") or "")
    parser_payload = job.get("parser") if isinstance(job.get("parser"), dict) else {}
    parser_version = parser_payload.get("parser_version")
    timestamp = _utc_timestamp()
    path = projection_path(document_id, root=root)
    previous_projection = None
    if path.exists():
        try:
            previous_projection = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            previous_projection = None

    raw_folders = raw_projection.get("folders") or []
    raw_messages = raw_projection.get("messages") or []
    if len(raw_folders) > MAX_PROJECTED_FOLDERS:
        raise ValueError("outlook_archive_projection_folder_limit_exceeded")
    if len(raw_messages) > MAX_PROJECTED_MESSAGES:
        raise ValueError("outlook_archive_projection_message_limit_exceeded")

    folders = [
        _normalise_folder(
            folder if isinstance(folder, dict) else {},
            index=index,
            document_id=document_id,
            job_id=job_id,
            parser_version=parser_version,
            projection_timestamp=timestamp,
        )
        for index, folder in enumerate(raw_folders, start=1)
    ]
    messages = [
        _normalise_message(
            message if isinstance(message, dict) else {},
            index=index,
            document_id=document_id,
            job_id=job_id,
            parser_version=parser_version,
            projection_timestamp=timestamp,
        )
        for index, message in enumerate(raw_messages, start=1)
    ]
    warnings = [
        str(value)
        for value in raw_projection.get("projection_warnings", [])
        if str(value).strip()
    ][:MAX_PROJECTION_WARNINGS]
    state = "rebuilt" if rebuild and previous_projection else "projected"
    projection = {
        "projection_version": OUTLOOK_ARCHIVE_PROJECTION_VERSION,
        "projection_state": state,
        "archive_id": document_id,
        "document_identifier": document.get("document_identifier"),
        "job_id": job_id,
        "parser_version": parser_version,
        "projection_timestamp": timestamp,
        "mailbox": {
            "name": _bounded_text(raw_projection.get("mailbox_name"), limit=240)
            or str(document.get("title") or "Outlook archive"),
            "archive_type": job.get("archive_type"),
        },
        "folders": folders,
        "messages": messages,
        "statistics": _statistics(folders, messages),
        "warnings": warnings,
        "governance_boundary": (
            "Outlook archive projections are administrative metadata derived "
            "from the preserved archive. They are replaceable operational "
            "representations and are not public evidence objects."
        ),
    }
    if previous_projection:
        projection["previous_projection_state"] = previous_projection.get("projection_state")
        projection["previous_projection_timestamp"] = previous_projection.get("projection_timestamp")
    _save_projection(path, projection)
    return projection


def list_projection_folders(document_id: str, *, root: Path | None = None) -> list[dict[str, Any]]:
    return list(load_outlook_archive_projection(document_id, root=root).get("folders") or [])


def get_projection_folder(
    document_id: str,
    folder_id: str,
    *,
    root: Path | None = None,
) -> dict[str, Any]:
    for folder in list_projection_folders(document_id, root=root):
        if str(folder.get("folder_id") or "") == str(folder_id):
            return folder
    raise ValueError("outlook_archive_folder_projection_not_found")


def list_projection_messages(document_id: str, *, root: Path | None = None) -> list[dict[str, Any]]:
    return list(load_outlook_archive_projection(document_id, root=root).get("messages") or [])


def get_projection_message(
    document_id: str,
    message_id: str,
    *,
    root: Path | None = None,
) -> dict[str, Any]:
    for message in list_projection_messages(document_id, root=root):
        if str(message.get("projection_id") or "") == str(message_id):
            return message
    raise ValueError("outlook_archive_message_projection_not_found")


def projection_statistics(document_id: str, *, root: Path | None = None) -> dict[str, Any]:
    return dict(load_outlook_archive_projection(document_id, root=root).get("statistics") or {})


def search_projection_metadata(
    document_id: str,
    query: str,
    *,
    root: Path | None = None,
) -> list[dict[str, Any]]:
    term = str(query or "").strip().casefold()
    if not term:
        return []
    projection = load_outlook_archive_projection(document_id, root=root)
    results: list[dict[str, Any]] = []
    for folder in projection.get("folders") or []:
        haystack = " ".join(
            str(folder.get(key) or "")
            for key in ("name", "folder_path", "source_identifier")
        ).casefold()
        if term in haystack:
            results.append({"type": "folder", "item": folder})
    for message in projection.get("messages") or []:
        haystack_values = [
            message.get("message_id"),
            message.get("subject"),
            message.get("sender"),
            message.get("sent_timestamp"),
            message.get("received_timestamp"),
            message.get("message_class"),
            message.get("conversation_id"),
            message.get("thread_index"),
            message.get("read_status"),
            message.get("importance"),
            message.get("folder_path"),
        ]
        haystack_values.extend(message.get("recipients") or [])
        haystack_values.extend(message.get("cc") or [])
        haystack_values.extend(message.get("categories") or [])
        if term in " ".join(str(value or "") for value in haystack_values).casefold():
            results.append({"type": "message", "item": message})
    return results
