from __future__ import annotations

from html import escape
from typing import Any

from api.document_intake import (
    document_media_family,
    document_type_label,
    is_audio_document,
    is_image_document,
    is_rich_text_document,
    is_spreadsheet_document,
    published_document_file,
)


def _document_url(item: dict[str, Any]) -> str:
    return f"/documents/{escape(str(item.get('intake_id') or ''))}"


def _media_label(item: dict[str, Any]) -> str:
    raw_type = str(item.get("document_type") or "").strip().lower()
    known_types = {"pdf", "jpeg", "png", "m4a", "mp3", "wav", "xls", "xlsx", "rtf", ""}
    if raw_type not in known_types:
        return "File"
    if is_image_document(item):
        return "Image"
    if is_audio_document(item):
        return "Audio"
    if is_spreadsheet_document(item):
        return "Spreadsheet"
    if is_rich_text_document(item):
        return "Rich Text"
    try:
        label = document_type_label(item.get("document_type"))
    except Exception:
        label = "File"
    return label or "File"


def _action_label(item: dict[str, Any]) -> str:
    raw_type = str(item.get("document_type") or "").strip().lower()
    known_types = {"pdf", "jpeg", "png", "m4a", "mp3", "wav", "xls", "xlsx", "rtf", ""}
    if raw_type not in known_types:
        return "Open Published Document"
    if is_image_document(item):
        return "Preview image"
    if is_audio_document(item):
        return "Open Audio document"
    if is_spreadsheet_document(item):
        return "Open Spreadsheet document"
    if is_rich_text_document(item):
        return "Open Rich Text document"
    try:
        if document_type_label(item.get("document_type")) == "PDF":
            return "Open PDF document"
    except Exception:
        return "Open Published Document"
    return "Open Published Document"


def render_public_document_preview(item: dict[str, Any], *, root: Any = None) -> str:
    """Render a compact public preview for an existing Published Document."""
    title = str(item.get("title") or "Published document")
    document_url = _document_url(item)
    media_label = _media_label(item)
    action_label = _action_label(item)
    try:
        published_document_file(str(item.get("intake_id") or ""), root=root)
    except Exception:
        return (
            '<div class="public-document-preview public-document-preview-unavailable">'
            f'<span class="preview-media-label">{escape(media_label)}</span>'
            '<span class="preview-unavailable">Preview unavailable</span>'
            f'<a class="preview-action" href="{document_url}" aria-label="Open Published Document: {escape(title)}">'
            "Open Published Document</a></div>"
        )

    if is_image_document(item):
        image_url = f"{document_url}/view"
        return (
            '<div class="public-document-preview public-document-preview-image">'
            f'<a class="preview-thumbnail-link" href="{document_url}" aria-label="Open Published Document: {escape(title)}">'
            f'<img class="public-document-thumbnail" src="{image_url}" alt="Preview of {escape(title)}" loading="lazy">'
            "</a>"
            f'<a class="preview-action" href="{document_url}">{escape(action_label)}</a>'
            "</div>"
        )

    family = document_media_family(item)
    css_family = "".join(ch if ch.isalnum() else "-" for ch in str(family or "file").lower())
    return (
        f'<div class="public-document-preview public-document-preview-fallback public-document-preview-{escape(css_family)}">'
        f'<a class="preview-fallback-link" href="{document_url}" aria-label="{escape(action_label)}: {escape(title)}">'
        f'<span class="preview-file-glyph" aria-hidden="true"></span>'
        f'<span class="preview-media-label">{escape(media_label)}</span>'
        f'<span class="preview-action-text">{escape(action_label)}</span>'
        "</a></div>"
    )
