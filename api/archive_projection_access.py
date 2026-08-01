from __future__ import annotations

from pathlib import Path
from typing import Any

from api.document_intake import (
    intake_root,
    is_gmail_takeout_document,
    is_imap_acquisition_document,
    load_pending_document,
)
from api.gmail_takeout import load_gmail_takeout_projection
from api.imap_acquisition import load_imap_acquisition_projection
from api.outlook_archive_projections import load_outlook_archive_projection


def load_archive_projection(document_id: str, *, root: Path | None = None) -> dict[str, Any]:
    storage_root = root or intake_root()
    document = load_pending_document(document_id, root=storage_root)
    if is_gmail_takeout_document(document):
        return load_gmail_takeout_projection(document_id, root=storage_root)
    if is_imap_acquisition_document(document):
        return load_imap_acquisition_projection(document_id, root=storage_root)
    return load_outlook_archive_projection(document_id, root=storage_root)


def list_archive_folders(document_id: str, *, root: Path | None = None) -> list[dict[str, Any]]:
    return list(load_archive_projection(document_id, root=root).get("folders") or [])


def get_archive_folder(
    document_id: str, folder_id: str, *, root: Path | None = None
) -> dict[str, Any]:
    for folder in list_archive_folders(document_id, root=root):
        if str(folder.get("folder_id") or "") == str(folder_id):
            return folder
    raise ValueError("archive_folder_projection_not_found")


def list_archive_messages(document_id: str, *, root: Path | None = None) -> list[dict[str, Any]]:
    return list(load_archive_projection(document_id, root=root).get("messages") or [])


def get_archive_message(
    document_id: str, message_id: str, *, root: Path | None = None
) -> dict[str, Any]:
    for message in list_archive_messages(document_id, root=root):
        if str(message.get("projection_id") or "") == str(message_id):
            return message
    raise ValueError("archive_message_projection_not_found")


def archive_projection_statistics(document_id: str, *, root: Path | None = None) -> dict[str, Any]:
    return dict(load_archive_projection(document_id, root=root).get("statistics") or {})


def search_archive_projection(
    document_id: str, query: str, *, root: Path | None = None
) -> list[dict[str, Any]]:
    term = str(query or "").strip().casefold()
    if not term:
        return []
    results: list[dict[str, Any]] = []
    for folder in list_archive_folders(document_id, root=root):
        values = (folder.get("name"), folder.get("path"), folder.get("folder_path"))
        if any(term in str(value or "").casefold() for value in values):
            results.append({"type": "folder", "item": folder})
    for message in list_archive_messages(document_id, root=root):
        values = (
            message.get("subject"),
            message.get("sender"),
            message.get("recipients"),
            message.get("message_id"),
            message.get("labels"),
            message.get("thread_id"),
        )
        if any(term in str(value or "").casefold() for value in values):
            results.append({"type": "message", "item": message})
    return results[:500]


def list_archive_threads(document_id: str, *, root: Path | None = None) -> list[dict[str, Any]]:
    return list(load_archive_projection(document_id, root=root).get("threads") or [])


def get_archive_thread(
    document_id: str, thread_id: str, *, root: Path | None = None
) -> dict[str, Any]:
    for thread in list_archive_threads(document_id, root=root):
        if str(thread.get("thread_id") or "") == str(thread_id):
            return thread
    raise ValueError("archive_thread_projection_not_found")
