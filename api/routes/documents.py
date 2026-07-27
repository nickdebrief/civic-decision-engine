from __future__ import annotations

from html import escape
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse

from api import record_document_associations as rda
from api.document_intake import (
    STATUS_LABELS,
    document_keywords_display,
    document_media_family,
    document_media_type,
    document_type_label,
    intake_root,
    is_audio_document,
    is_email_document,
    is_image_document,
    is_mailbox_document,
    is_rich_text_document,
    is_spreadsheet_document,
    list_published_documents,
    load_published_document,
    published_document_file,
)
from api.email_documents import APPLE_MAIL_GOVERNANCE_BOUNDARY
from api.email_documents import EMAIL_GOVERNANCE_BOUNDARY
from api.email_documents import MBOX_GOVERNANCE_BOUNDARY
from api.email_documents import OUTLOOK_GOVERNANCE_BOUNDARY
from api.public_navigation import (
    PUBLIC_NAVIGATION_CSS,
    archive_back_link,
    object_type_badge,
    public_breadcrumbs,
    public_primary_navigation,
    sanitize_archive_return,
)
from api.public_document_preview import render_public_document_preview


router = APIRouter()

GOVERNANCE_STATEMENT = (
    "Documents displayed in this library have been explicitly marked as Published "
    "through the administrative workflow. Publication indicates intentional public "
    "availability. Publication does not certify legal status, evidential truth, or "
    "external validation."
)


def _not_found(exc: Exception):
    raise HTTPException(status_code=404, detail="public_document_not_found") from exc


def _date(value: object) -> str:
    return str(value or "Not available").split("T", 1)[0]


def _render_library(
    documents: list[dict],
    all_documents: list[dict],
    *,
    query: str | None,
    institution: str | None,
    category: str | None,
    publication_year: str | None,
) -> str:
    institutions = sorted(
        {str(item["institution_source"]) for item in all_documents}, key=str.casefold
    )
    categories = sorted({str(item["category"]) for item in all_documents}, key=str.casefold)
    years = sorted(
        {
            _date(item.get("publication_date"))[:4]
            for item in all_documents
            if _date(item.get("publication_date"))[:4].isdigit()
        },
        reverse=True,
    )

    def options(values: list[str], selected: str | None) -> str:
        return "".join(
            f'<option value="{escape(value)}"{" selected" if value == selected else ""}>{escape(value)}</option>'
            for value in values
        )

    rows = "".join(
        f"""<tr>
          <td><a href="/documents/{escape(item['intake_id'])}">{escape(item['title'])}</a></td>
          <td>{escape(item['institution_source'])}</td>
          <td>{escape(item['category'])}</td>
          <td>{escape(_date(item.get('publication_date')))}</td>
          <td>{escape(item['description'])}</td>
          <td>{escape(str(item.get('document_identifier') or '—'))}</td>
          <td>{escape(str(item.get('reference_identifier') or '—'))}</td>
          <td class="document-preview-cell">{render_public_document_preview(item, root=intake_root())}</td>
        </tr>"""
        for item in documents
    ) or '<tr><td colspan="8">No published documents match these criteria.</td></tr>'
    active_query = urlencode(
        {
            key: value
            for key, value in {
                "q": query,
                "institution": institution,
                "category": category,
                "publication_year": publication_year,
            }.items()
            if value
        }
    )
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Public Document Library</title>
<style>*{{box-sizing:border-box}}body{{margin:0;background:#f7f7f4;color:#1f2933;font-family:system-ui,sans-serif}}main{{width:min(1240px,calc(100% - 32px));margin:32px auto 64px}}h1{{color:#143a52}}{PUBLIC_NAVIGATION_CSS}.governance{{max-width:900px;padding:16px;border-left:4px solid #2e8b9a;background:#fff}}form{{display:grid;grid-template-columns:2fr repeat(3,1fr) auto;gap:10px;margin:24px 0}}input,select,button{{min-width:0;padding:9px;border:1px solid #c9c6bd;background:#fff;font:inherit}}button{{border-color:#245d61;background:#245d61;color:#fff;cursor:pointer}}.table-wrap{{overflow-x:auto}}table{{width:100%;border-collapse:collapse;background:#fff;font-size:.9rem}}th{{background:#143a52;color:#fff;text-align:left}}th,td{{padding:10px;border:1px solid #e1dfd8;vertical-align:top;white-space:normal;overflow-wrap:break-word}}a{{color:#245d61}}.result-count{{color:#555}}.document-preview-cell{{width:150px;min-width:150px}}.public-document-preview{{display:grid;gap:6px;justify-items:start;max-width:132px}}.public-document-thumbnail{{display:block;width:112px;max-width:100%;height:84px;object-fit:contain;background:#faf9f5;border:1px solid #d8d4ca}}.preview-thumbnail-link,.preview-fallback-link{{display:inline-grid;gap:5px;text-decoration:none;color:#143a52}}.preview-thumbnail-link:focus,.preview-fallback-link:focus,.preview-action:focus{{outline:3px solid #2e8b9a;outline-offset:2px}}.preview-fallback-link{{width:118px;min-height:84px;align-content:center;justify-items:center;padding:9px;border:1px solid #d8d4ca;background:#faf9f5;text-align:center}}.preview-file-glyph{{width:28px;height:34px;border:2px solid #245d61;border-radius:2px;background:#fff;box-shadow:8px -8px 0 -6px #245d61}}.preview-media-label{{font-weight:750;color:#143a52}}.preview-action,.preview-action-text{{font-size:.8rem;color:#245d61;text-decoration:underline}}.preview-unavailable{{font-weight:650;color:#6b4f00}}@media(max-width:800px){{form{{grid-template-columns:1fr}}table{{min-width:1040px}}.document-preview-cell{{min-width:128px}}.public-document-thumbnail{{width:96px;height:72px}}}}</style></head>
<body><main>{public_primary_navigation(active="documents")}{public_breadcrumbs([("Home", "/"), ("Archive", "/archive"), ("Published Documents", None)])}<h1>Public Document Library</h1><p class="governance">{escape(GOVERNANCE_STATEMENT)}</p>
<form method="get" action="/documents"><input name="q" value="{escape(str(query or ''))}" placeholder="Search title, institution, category, or reference" aria-label="Search documents"><select name="institution" aria-label="Filter by institution"><option value="">All institutions</option>{options(institutions, institution)}</select><select name="category" aria-label="Filter by category"><option value="">All categories</option>{options(categories, category)}</select><select name="publication_year" aria-label="Filter by publication year"><option value="">All publication years</option>{options(years, publication_year)}</select><button type="submit">Search</button></form>
<p class="result-count">{len(documents)} published document{"s" if len(documents) != 1 else ""}.{f' Active query: {escape(active_query)}' if active_query else ''}</p><div class="table-wrap" role="region" aria-label="Published documents table"><table><thead><tr><th>Title</th><th>Institution / Source</th><th>Category</th><th>Publication Date</th><th>Description</th><th>Document Identifier</th><th>Optional Reference Identifier</th><th>Preview</th></tr></thead><tbody>{rows}</tbody></table></div></main></body></html>"""


def _display_value(value: object) -> str:
    if value is None or value == "":
        return "—"
    return str(value)


def _status_label(value: object) -> str:
    if value is None or value == "":
        return "Initial state"
    return STATUS_LABELS.get(str(value), str(value))


def _pathway_events(item: dict) -> list[tuple[int, dict]]:
    events = list(enumerate(item.get("status_history") or []))
    return sorted(events, key=lambda pair: (str(pair[1].get("timestamp") or ""), pair[0]))


def _first_event(item: dict, new_status: str) -> dict | None:
    for _index, event in _pathway_events(item):
        if event.get("new_status") == new_status:
            return event
    return None


def _publication_timestamp(item: dict) -> str:
    event = _first_event(item, "published")
    if event and event.get("timestamp"):
        return str(event["timestamp"])
    return str(item.get("publication_date") or "")


def _presentation_mode(item: dict) -> str:
    if is_image_document(item):
        return "Inline image view and original-file download"
    if is_audio_document(item):
        return "Inline audio playback and original-file download"
    if is_spreadsheet_document(item):
        return "Downloadable spreadsheet workbook"
    if is_rich_text_document(item):
        return "Downloadable Rich Text Format file"
    if is_mailbox_document(item):
        return "Mailbox archive metadata, paginated message inspection, safe body previews, and original-file download"
    if is_email_document(item) and document_type_label(item.get("document_type")) == "Microsoft Outlook Message":
        return "Microsoft Outlook Message metadata, safe body preview, and original-file download"
    if is_email_document(item) and document_type_label(item.get("document_type")) == "Apple Mail Message":
        return "Apple Mail Message metadata, safe body preview, and original-file download"
    if is_email_document(item):
        return "RFC 5322 Email metadata, safe body preview, and original-file download"
    return "Downloadable PDF"


def _original_download_availability(item: dict) -> str:
    if is_image_document(item):
        return "Original image download available"
    if is_audio_document(item):
        return "Original audio download available"
    if is_spreadsheet_document(item):
        return "Original spreadsheet download available"
    if is_rich_text_document(item):
        return "Original RTF download available"
    if is_mailbox_document(item):
        return "Original .mbox download available"
    if is_email_document(item) and document_type_label(item.get("document_type")) == "Microsoft Outlook Message":
        return "Original .msg download available"
    if is_email_document(item) and document_type_label(item.get("document_type")) == "Apple Mail Message":
        return "Original .emlx download available"
    if is_email_document(item):
        return "Original .eml download available"
    return "Original PDF download available"


def _media_family_label(item: dict) -> str:
    family = document_media_family(item)
    if family == "rich_text":
        return "Rich Text"
    if family == "email":
        return "Email"
    if family == "mailbox":
        return "Mailbox"
    return family.title()


def _render_publication_pathway(item: dict) -> str:
    rows = "".join(
        f"""<tr>
          <td class="publication-pathway-timestamp">{escape(_display_value(event.get('timestamp')))}</td>
          <td class="publication-pathway-previous-status">{escape(_status_label(event.get('previous_status')))}</td>
          <td class="publication-pathway-new-status">{escape(_status_label(event.get('new_status')))}</td>
          <td class="publication-pathway-actor">{escape(_display_value(event.get('actor')))}</td>
          <td class="publication-pathway-note">{escape(_display_value(event.get('note')))}</td>
        </tr>"""
        for _index, event in _pathway_events(item)
    ) or '<tr><td colspan="5">No lifecycle pathway entries are available.</td></tr>'
    return f"""<section id="publication-pathway" class="publication-pathway"><h2>Publication Pathway</h2><div class="publication-pathway-wrapper"><table class="publication-pathway-table"><thead><tr><th class="publication-pathway-timestamp">Timestamp</th><th class="publication-pathway-previous-status">Previous status</th><th class="publication-pathway-new-status">New status</th><th class="publication-pathway-actor">Actor</th><th class="publication-pathway-note">Note</th></tr></thead><tbody>{rows}</tbody></table></div><p class="provenance-boundary">Actor identifies the administrative identity recorded for the lifecycle action. It does not by itself establish authorship, factual verification, or legal responsibility for the document contents.</p></section>"""


def _render_publication_provenance(item: dict) -> str:
    review_event = _first_event(item, "under_review")
    approval_event = _first_event(item, "approved")
    publication_event = _first_event(item, "published")
    initial_event = _first_event(item, "pending")
    email_metadata = _email_metadata(item)
    intake_mode = item.get("intake_mode") or email_metadata.get("intake_mode")
    intake_mode_label = (
        "Governed Streaming Mailbox Intake"
        if intake_mode == "governed_streaming_mbox"
        else None
    )
    provenance_fields = (
        ("Intake date and time", item.get("upload_date")),
        ("Intake mode", intake_mode_label),
        ("Streaming upload started", email_metadata.get("streaming_upload_started_at") if intake_mode_label else None),
        ("Streaming upload completed", email_metadata.get("streaming_upload_completed_at") if intake_mode_label else None),
        ("Streaming validation completed", email_metadata.get("streaming_validation_completed_at") if intake_mode_label else None),
        ("Streaming finalisation timestamp", email_metadata.get("streaming_finalised_at") if intake_mode_label else None),
        ("Configured streaming limit", f"{email_metadata.get('streaming_max_upload_bytes')} bytes" if intake_mode_label and email_metadata.get("streaming_max_upload_bytes") is not None else None),
        ("Document date", item.get("document_date")),
        ("Server-detected document format", document_type_label(item.get("document_type"))),
        ("Detected MBOX variant", email_metadata.get("detected_mbox_variant") if is_mailbox_document(item) else None),
        ("MBOX message count", email_metadata.get("message_count") if is_mailbox_document(item) else None),
        ("Original filename", item.get("original_filename")),
        ("File size", f"{item.get('file_size_bytes')} bytes" if item.get("file_size_bytes") is not None else None),
        ("SHA-256 digest", item.get("sha256_hash")),
        ("Document Identifier", item.get("document_identifier")),
        ("Initial intake actor", initial_event.get("actor") if initial_event else None),
        ("Review actor", review_event.get("actor") if review_event else None),
        ("Approval actor", approval_event.get("actor") if approval_event else None),
        ("Publication actor", publication_event.get("actor") if publication_event else None),
        ("Review timestamp", review_event.get("timestamp") if review_event else None),
        ("Approval timestamp", approval_event.get("timestamp") if approval_event else None),
        ("Publication timestamp", _publication_timestamp(item)),
        ("Current lifecycle state", STATUS_LABELS.get(str(item.get("status") or ""), item.get("status"))),
        ("Optional Reference Identifier", item.get("reference_identifier")),
        ("Public presentation mode", _presentation_mode(item)),
        ("Original-file download availability", _original_download_availability(item)),
    )
    rows = "".join(
        f"""<div class="publication-provenance-row"><dt class="publication-provenance-label">{escape(label)}</dt><dd class="publication-provenance-value">{escape(_display_value(value))}</dd></div>"""
        for label, value in provenance_fields
    )
    return f"""<section id="publication-provenance" class="publication-provenance"><h2>Publication Provenance</h2><p class="provenance-boundary">Publication provenance records the administrative pathway by which this document became publicly available through CDE. It does not certify the document’s legal status, evidential truth, authorship, or external validation.</p><dl class="publication-provenance-grid">{rows}</dl><p class="provenance-boundary">The SHA-256 digest identifies the exact original bytes admitted through Document Intake. It supports byte-level comparison of the preserved file but does not independently establish authorship, factual accuracy, legal status, or external authenticity.</p></section>"""



def _render_associated_records(item: dict) -> str:
    conn = rda.get_db()
    try:
        associations = rda.public_associations_for_document(
            conn,
            item["intake_id"],
            root=intake_root(),
        )
    finally:
        conn.close()
    if not associations:
        return ""
    cards = "".join(
        f"""<article class="associated-record-card">
          <h3><a href="/verify/{escape(str(association.get('record_reference') or ''))}">{escape(str(association.get('record_reference') or ''))}</a></h3>
          <p><strong>{escape(str(association.get('public_label') or 'Related record'))}</strong></p>
          <p><a href="/associations/{escape(str(association.get('public_reference') or ''))}">View association</a> · <a href="/verify/{escape(str(association.get('record_reference') or ''))}">View linked record</a></p>
          <p>{escape(_display_value(association.get('record_title')))}</p>
          <dl><dt>Generated date</dt><dd>{escape(_date(association.get('record_generated_at')))}</dd><dt>Trajectory</dt><dd>{escape(_display_value(association.get('record_trajectory')))}</dd></dl>
        </article>"""
        for association in associations
    )
    return f"""<section id="associated-records" class="associated-records"><h2>Associated Civic Records</h2><p class="association-boundary">Association records a declared relationship between independently preserved objects. It does not by itself establish proof, sufficiency, factual truth, legal status, or external validation.</p><div class="associated-records-list">{cards}</div></section>"""


def _render_workbook_metadata(item: dict) -> str:
    metadata = item.get("workbook_metadata") if isinstance(item.get("workbook_metadata"), dict) else {}
    worksheet_names = metadata.get("worksheet_names")
    if isinstance(worksheet_names, list):
        worksheet_display = " · ".join(str(name) for name in worksheet_names if str(name).strip())
    else:
        worksheet_display = ""
    rows = (
        ("Workbook type", metadata.get("workbook_type")),
        ("Worksheet count", metadata.get("worksheet_count")),
        ("Worksheet names", worksheet_display),
        ("Calculation mode", metadata.get("calculation_mode")),
        (
            "Hidden sheets present",
            "Yes" if metadata.get("hidden_sheets_present") is True else "No" if metadata.get("hidden_sheets_present") is False else None,
        ),
    )
    rendered = "".join(
        f"<tr><th>{escape(label)}</th><td>{escape(_display_value(value))}</td></tr>"
        for label, value in rows
        if value not in (None, "", [])
    )
    if not rendered:
        rendered = '<tr><td colspan="2">No additional workbook metadata is available.</td></tr>'
    return f"""<section class="public-spreadsheet-summary"><h2>Spreadsheet Artefact</h2><p class="provenance-boundary">This spreadsheet is preserved and published as the original uploaded workbook. CDE does not execute formulas, macros, external links, data connections, scripts, or remote resources, and this page does not replace the original file.</p><table>{rendered}</table></section>"""


def _email_metadata(item: dict) -> dict:
    metadata = item.get("email_metadata")
    return metadata if isinstance(metadata, dict) else {}


def _email_join(value: object) -> str:
    if isinstance(value, list):
        return " · ".join(str(item) for item in value if item is not None and str(item).strip())
    return str(value or "")



def _message_by_index(metadata: dict, message_index: object | None) -> dict | None:
    try:
        wanted = int(message_index) if message_index is not None else 1
    except (TypeError, ValueError):
        wanted = 1
    for message in metadata.get("messages") or []:
        if isinstance(message, dict) and int(message.get("message_index") or 0) == wanted:
            return message
    messages = metadata.get("messages") or []
    return messages[0] if messages and isinstance(messages[0], dict) else None


def _render_mbox_document(item: dict, *, message_index: object | None = None, page: object | None = None) -> str:
    metadata = _email_metadata(item)
    messages = [message for message in (metadata.get("messages") or []) if isinstance(message, dict)]
    try:
        current_page = int(page or 1)
    except (TypeError, ValueError):
        current_page = 1
    current_page = current_page if current_page > 0 else 1
    page_size = 25
    start = (current_page - 1) * page_size
    visible_messages = messages[start : start + page_size]
    total_pages = max(1, (len(messages) + page_size - 1) // page_size)
    overview_fields = (
        ("Detected format", metadata.get("source_format_label") or document_type_label(item.get("document_type"))),
        ("Detected MBOX variant", metadata.get("detected_mbox_variant")),
        ("Message count", metadata.get("message_count")),
        ("Parsed message count", metadata.get("parsed_message_count")),
        ("Warning message count", metadata.get("warning_message_count")),
        ("Unparsed message count", metadata.get("unparsed_message_count")),
        ("Attachment total", metadata.get("attachment_total")),
        ("Earliest message date recorded in archive", metadata.get("earliest_message_date")),
        ("Latest message date recorded in archive", metadata.get("latest_message_date")),
        ("Message IDs present", metadata.get("message_ids_present")),
        ("Message IDs missing", metadata.get("message_ids_missing")),
        ("Exact duplicate count", metadata.get("exact_duplicate_count")),
        ("Original-file download availability", _original_download_availability(item)),
    )
    overview_rows = "".join(
        f"<tr><th>{escape(label)}</th><td>{escape(_display_value(value))}</td></tr>"
        for label, value in overview_fields
    )
    index_rows = "".join(
        f"""<tr>
          <td class="mbox-index-cell"><a href="/documents/{escape(str(item.get('intake_id') or ''))}?message={escape(str(message.get('message_index') or ''))}">{escape(_display_value(message.get('message_index')))}</a></td>
          <td class="mbox-date-cell">{escape(_display_value(message.get('date_header_parsed') or message.get('date_header_raw')))}</td>
          <td class="mbox-from-cell">{escape(_display_value(message.get('from_raw') or message.get('sender_raw')))}</td>
          <td class="mbox-subject-cell">{escape(_display_value(message.get('subject_decoded')))}</td>
          <td class="mbox-to-cell">{escape(_display_value(message.get('to_raw')))}</td>
          <td class="mbox-attachment-cell">{escape(_display_value(message.get('attachment_count') or 0))}</td>
          <td class="mbox-status-cell">{escape(_display_value(message.get('parse_status')))}</td>
          <td class="mbox-warning-cell">{'Yes' if message.get('parser_warnings') else 'No'}</td>
        </tr>"""
        for message in visible_messages
    ) or '<tr><td colspan="8">No contained message projections are available.</td></tr>'
    pagination = f'<p class="provenance-boundary">Showing messages {start + 1 if messages else 0}-{min(start + page_size, len(messages))} of {len(messages)}. Page {current_page} of {total_pages}. Public rendering is bounded to {page_size} message projections per page.</p>'
    selected = _message_by_index(metadata, message_index)
    detail = ""
    if selected:
        attachments = selected.get("attachments_metadata") or []
        attachment_rows = "".join(
            f"""<tr><td>{escape(_display_value(attachment.get('filename')))}</td><td>{escape(_display_value(attachment.get('media_type')))}</td><td>{escape(_display_value(attachment.get('byte_size')))}</td><td>{escape(_display_value(attachment.get('content_disposition')))}</td><td>{escape(_display_value(attachment.get('content_id')))}</td><td>{'Yes' if attachment.get('is_attached_message') else 'No'}</td></tr>"""
            for attachment in attachments
            if isinstance(attachment, dict)
        ) or '<tr><td colspan="6">No attachment metadata was detected for this contained message.</td></tr>'
        plain_text = str(selected.get("plain_text_preview") or "").strip()
        html_preview = str(selected.get("sanitized_html_preview") or "").strip()
        plain_block = f'<pre class="email-plain-text">{escape(plain_text)}</pre>' if plain_text else '<p class="provenance-boundary">No plain-text body was available in this contained-message projection.</p>'
        html_block = f'<details class="email-html-details"><summary>Sanitised HTML preview</summary><div class="email-html-view">{html_preview}</div></details>' if html_preview else ""
        detail_fields = (
            ("Mailbox message index", selected.get("message_index")),
            ("Message size", selected.get("message_byte_size")),
            ("Contained-message digest", selected.get("message_digest")),
            ("Source byte range", f"{selected.get('byte_start')}–{selected.get('byte_end')}"),
            ("Preview mode", selected.get("preview_mode")),
            ("Preview truncated", "Yes" if selected.get("preview_truncated") else "No"),
            ("Subject", selected.get("subject_decoded")),
            ("From", selected.get("from_raw")),
            ("Sender", selected.get("sender_raw")),
            ("Reply-To", selected.get("reply_to_raw")),
            ("To", selected.get("to_raw")),
            ("CC", selected.get("cc_raw")),
            ("Individual message date recorded in source", selected.get("date_header_parsed") or selected.get("date_header_raw")),
            ("Message-ID", selected.get("message_id")),
            ("In-Reply-To", selected.get("in_reply_to")),
            ("References", _email_join(selected.get("references"))),
            ("MIME type", selected.get("content_type")),
            ("Attachment count", selected.get("attachment_count")),
            ("Parser warnings", _email_join(selected.get("parser_warnings")) or "No parser warnings were recorded."),
        )
        detail_rows = "".join(f"<tr><th>{escape(label)}</th><td>{escape(_display_value(value))}</td></tr>" for label, value in detail_fields)
        detail = f"""<section class="public-mbox-message-detail"><h2>Message Detail</h2><table>{detail_rows}</table><h3>Message Body</h3>{plain_block}{html_block}<h3>Attachments</h3><p class="provenance-boundary">Attachments remain components of the preserved MBOX archive unless separately admitted through Document Intake.</p><div class="email-attachments-wrapper"><table><thead><tr><th>Filename</th><th>Media type</th><th>Byte size</th><th>Disposition</th><th>Content ID</th><th>Attached message</th></tr></thead><tbody>{attachment_rows}</tbody></table></div></section>"""
    warnings = metadata.get("parser_warnings") or []
    warning_text = _email_join(warnings) if warnings else "No mailbox-level parser warnings were recorded."
    return f"""<section class="public-mbox-summary"><h2>Mailbox Overview</h2><p class="provenance-boundary">{escape(MBOX_GOVERNANCE_BOUNDARY)}</p><table>{overview_rows}</table></section>
<section class="public-mbox-index"><h2>Mailbox Message Index</h2>{pagination}<div class="email-attachments-wrapper"><table class="public-mbox-message-index"><thead><tr><th>Index</th><th>Date</th><th>From</th><th>Subject</th><th>To</th><th>Attachment count</th><th>Parse status</th><th>Warning indicator</th></tr></thead><tbody>{index_rows}</tbody></table></div><p class="provenance-boundary">Parser warnings: {escape(_display_value(warning_text))}</p></section>
{detail}
<section class="public-email-boundary"><h2>Mailbox Governance Boundary</h2><p class="provenance-boundary">{escape(MBOX_GOVERNANCE_BOUNDARY)}</p></section>"""


def _render_email_document(item: dict) -> str:
    metadata = _email_metadata(item)
    is_outlook = metadata.get("source_format") == "outlook_msg"
    is_apple = metadata.get("source_format") == "apple_emlx"
    boundary = OUTLOOK_GOVERNANCE_BOUNDARY if is_outlook else APPLE_MAIL_GOVERNANCE_BOUNDARY if is_apple else EMAIL_GOVERNANCE_BOUNDARY
    message_date = metadata.get("date_header_parsed") or metadata.get("date_header_raw")
    overview_fields = [
        ("Subject", metadata.get("subject_decoded") or metadata.get("subject_raw")),
        ("Sender", metadata.get("sender_raw")),
    ]
    if is_outlook:
        overview_fields.extend(
            (
                ("Sent on behalf of", _email_join([metadata.get("sent_representing_name"), metadata.get("sent_representing_email")])),
                ("From / SMTP address", metadata.get("sender_smtp_address") or metadata.get("from_raw")),
            )
        )
    else:
        overview_fields.append(("From", metadata.get("from_raw")))
    overview_fields.extend((
        ("Reply-To", metadata.get("reply_to_raw")),
        ("To", metadata.get("to_raw")),
        ("CC", metadata.get("cc_raw")),
        ("Message sent time recorded in source" if is_outlook else "Message date recorded in source", metadata.get("client_submit_time") or message_date),
        ("Delivery time recorded in source", metadata.get("delivery_time")),
        ("Message creation time recorded in source", metadata.get("creation_time")),
        ("Last modification time recorded in source", metadata.get("last_modification_time")),
        ("Message-ID", metadata.get("message_id")),
        ("In-Reply-To", metadata.get("in_reply_to")),
        ("References", _email_join(metadata.get("references"))),
        ("Conversation topic", metadata.get("conversation_topic")),
        ("Outlook message class" if is_outlook else "MIME type", metadata.get("message_class") or metadata.get("content_type")),
        ("Attachment count", metadata.get("attachment_count")),
        ("Embedded message count", metadata.get("embedded_message_count")),
    ))
    overview_rows = "".join(
        f"<tr><th>{escape(label)}</th><td>{escape(_display_value(value))}</td></tr>"
        for label, value in overview_fields
    )
    apple_metadata = metadata.get("apple_mail_metadata_public") if isinstance(metadata.get("apple_mail_metadata_public"), dict) else {}
    apple_rows = "".join(
        f"<tr><th>{escape(str(label))}</th><td>{escape(_display_value(value))}</td></tr>"
        for label, value in apple_metadata.items()
    )
    if is_apple:
        apple_rows += f"<tr><th>Trailing Apple metadata present</th><td>{'Yes' if metadata.get('emlx_trailing_metadata_present') else 'No'}</td></tr>"
        apple_rows += f"<tr><th>Declared RFC 5322 message bytes</th><td>{escape(_display_value(metadata.get('emlx_declared_message_bytes')))}</td></tr>"
    apple_section = (
        f'<section class="public-email-apple-metadata"><h2>Apple Mail Metadata</h2><p class="provenance-boundary">Only safe Apple Mail wrapper metadata is displayed publicly. Local mailbox paths, account identifiers, and hidden plist values are excluded from public presentation and search.</p><table>{apple_rows}</table></section>'
        if is_apple
        else ""
    )
    plain_text = str(metadata.get("plain_text_body") or "").strip()
    sanitized_html = str(metadata.get("sanitized_html_body") or "").strip()
    plain_block = (
        f'<pre class="email-plain-text">{escape(plain_text)}</pre>'
        if plain_text
        else '<p class="provenance-boundary">No plain-text body was available in the parsed message projection.</p>'
    )
    html_block = (
        f'<details class="email-html-details"><summary>Sanitised HTML view</summary><div class="email-html-view">{sanitized_html}</div></details>'
        if sanitized_html
        else ""
    )
    rtf_notice = (
        '<p class="provenance-boundary">An Outlook RTF body is present in the source message. CDE Platform Stage 35B records RTF presence but does not render Outlook RTF publicly.</p>'
        if metadata.get("rtf_body_present")
        else ""
    )
    attachments = metadata.get("attachments_metadata") or []
    if attachments:
        attachment_rows = "".join(
            f"""<tr>
              <td>{escape(_display_value(attachment.get('attachment_index')))}</td>
              <td>{escape(_display_value(attachment.get('filename')))}</td>
              <td>{escape(_display_value(attachment.get('long_filename')))}</td>
              <td>{escape(_display_value(attachment.get('media_type')))}</td>
              <td>{escape(_display_value(attachment.get('byte_size')))}</td>
              <td>{escape(_display_value(attachment.get('content_disposition')))}</td>
              <td>{escape(_display_value(attachment.get('content_id')))}</td>
              <td>{escape(_display_value(attachment.get('attachment_method')))}</td>
              <td>{escape(_display_value(attachment.get('mime_tag')))}</td>
              <td>{'Yes' if attachment.get('is_attached_message') else 'No'}</td>
              <td>{'Yes' if attachment.get('filename_generated') else 'No'}</td>
            </tr>"""
            for attachment in attachments
            if isinstance(attachment, dict)
        )
    else:
        attachment_rows = '<tr><td colspan="11">No attachment metadata was detected.</td></tr>'
    warnings = metadata.get("parser_warnings") or []
    warning_text = _email_join(warnings) if warnings else "No parser warnings were recorded."
    stage_label = "CDE Platform Stage 35B" if is_outlook else "CDE Platform Stage 35C" if is_apple else "CDE Platform Stage 35A"
    return f"""<section class="public-email-summary"><h2>Email Overview</h2><p class="provenance-boundary">{escape(boundary)}</p><table>{overview_rows}</table></section>
{apple_section}
<section class="public-email-body"><h2>Message Body</h2>{plain_block}{html_block}{rtf_notice}</section>
<section class="public-email-attachments"><h2>Attachments</h2><p class="provenance-boundary">{stage_label} lists attachment metadata only. Attachments remain components of the preserved source email unless separately admitted through Document Intake.</p><div class="email-attachments-wrapper"><table><thead><tr><th>Index</th><th>Filename</th><th>Long filename</th><th>Media type</th><th>Byte size</th><th>Disposition</th><th>Content ID</th><th>Attachment method</th><th>MIME tag</th><th>Attached message</th><th>Generated filename</th></tr></thead><tbody>{attachment_rows}</tbody></table></div><p class="provenance-boundary">Parser warnings: {escape(_display_value(warning_text))}</p></section>
<section class="public-email-boundary"><h2>Email Governance Boundary</h2><p class="provenance-boundary">{escape(boundary)}</p></section>"""


def _render_document(item: dict, return_to: object | None = None, message: object | None = None, page: object | None = None) -> str:
    publication_timestamp = _publication_timestamp(item)
    archive_return = sanitize_archive_return(return_to)
    fields = [
        ("Title", item["title"]),
        ("Description", item["description"]),
        ("Institution / Source", item["institution_source"]),
        ("Category", item["category"]),
    ]
    keywords = document_keywords_display(item.get("keywords") or item.get("tags"))
    if keywords:
        fields.append(("Keywords", keywords))
    fields.extend((
        ("Publication Date", _date(publication_timestamp or item.get("publication_date"))),
        ("Document Date", item["document_date"]),
        ("Document Format", document_type_label(item.get("document_type"))),
        ("Media Type", _media_family_label(item)),
        ("SHA-256", item["sha256_hash"]),
        ("Document Identifier", item.get("document_identifier")),
        ("Optional Reference Identifier", item.get("reference_identifier") or "Not provided"),
    ))
    rows = "".join(
        f"<tr><th>{escape(label)}</th><td>{escape(str(value))}</td></tr>"
        for label, value in fields
    )
    if is_image_document(item):
        content_block = f"""<section id="document-content"><h2>Document Image</h2><div class="public-document-image-wrap"><img class="public-document-image" src="/documents/{escape(item['intake_id'])}/view" alt="{escape(str(item['title']))}"></div><a class="download" href="/documents/{escape(item['intake_id'])}/view">View image</a> <a class="download" href="/documents/{escape(item['intake_id'])}/download">Download original image</a></section>"""
    elif is_audio_document(item):
        content_block = f"""<section id="document-content"><h2>Audio Artefact</h2><div class="public-audio-wrap"><audio class="public-document-audio" controls preload="metadata"><source src="/documents/{escape(item['intake_id'])}/view" type="{escape(document_media_type(item))}">This browser may not support playback of this audio format. Download the original file to listen.</audio></div><a class="download" href="/documents/{escape(item['intake_id'])}/download">Download original audio</a></section>"""
    elif is_spreadsheet_document(item):
        content_block = f"""<section id="document-content">{_render_workbook_metadata(item)}<a class="download" href="/documents/{escape(item['intake_id'])}/download">Download original spreadsheet</a></section>"""
    elif is_rich_text_document(item):
        content_block = f"""<section id="document-content"><section class="public-rich-text-summary"><h2>Rich Text Format Artefact</h2><p class="provenance-boundary">This Rich Text Format file is preserved and published as the original uploaded artefact. CDE does not convert, execute, or render the RTF as HTML; download the original file to inspect it with appropriate local software.</p></section><a class="download" href="/documents/{escape(item['intake_id'])}/download">Download original RTF</a></section>"""
    elif is_mailbox_document(item):
        content_block = f"""<section id="document-content">{_render_mbox_document(item, message_index=message, page=page)}<a class="download" href="/documents/{escape(item['intake_id'])}/download">Download original .mbox</a></section>"""
    elif is_email_document(item):
        download_label = "Download original .msg" if document_type_label(item.get("document_type")) == "Microsoft Outlook Message" else "Download original .emlx" if document_type_label(item.get("document_type")) == "Apple Mail Message" else "Download original .eml"
        content_block = f"""<section id="document-content">{_render_email_document(item)}<a class="download" href="/documents/{escape(item['intake_id'])}/download">{download_label}</a></section>"""
    else:
        content_block = f"""<section id="document-content"><a class="download" href="/documents/{escape(item['intake_id'])}/download">Download PDF</a></section>"""
    associated_records_section = _render_associated_records(item)
    provenance_section = _render_publication_provenance(item)
    pathway_section = _render_publication_pathway(item)
    admin_actions = f"""<section class="public-document-admin-actions" aria-label="Administrative actions"><h2>Administrative Actions</h2><p>This protected administrative action opens the existing authenticated workflow for creating a distinct canonical CDE record from this Published document.</p><a class="admin-action-link" href="/admin/document-intake/{escape(item['intake_id'])}/canonical-record/new">Create canonical record from this document</a></section>"""
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>{escape(item['title'])}</title>
<style>*{{box-sizing:border-box}}body{{margin:0;background:#f7f7f4;color:#1f2933;font-family:system-ui,sans-serif}}main{{width:min(960px,calc(100% - 32px));margin:32px auto 64px}}h1,h2{{color:#143a52}}a{{color:#245d61}}{PUBLIC_NAVIGATION_CSS}.governance,.provenance-boundary{{padding:14px;border-left:4px solid #2e8b9a;background:#fff}}table{{width:100%;border-collapse:collapse;background:#fff}}th,td{{padding:10px;border:1px solid #e1dfd8;text-align:left;vertical-align:top;overflow-wrap:anywhere}}th{{width:210px;background:#faf9f5;color:#555}}.public-document-image-wrap,.public-audio-wrap,.public-spreadsheet-summary,.public-rich-text-summary,.public-email-summary,.public-email-apple-metadata,.public-email-body,.public-email-attachments,.public-email-boundary,.public-mbox-summary,.public-mbox-index,.public-mbox-message-detail{{background:#fff;border:1px solid #e1dfd8;padding:12px;margin:18px 0}}.public-spreadsheet-summary table{{margin-top:12px}}.public-document-image{{display:block;max-width:100%;width:auto;height:auto}}.public-document-audio{{display:block;width:100%;max-width:720px}}.email-plain-text{{white-space:pre-wrap;overflow-wrap:break-word;margin:0;padding:12px;background:#faf9f5;border:1px solid #e1dfd8;font:0.95rem/1.5 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}}.email-html-details{{margin-top:14px}}.email-html-view{{padding:12px;margin-top:8px;background:#faf9f5;border:1px solid #e1dfd8;overflow-wrap:break-word}}.email-attachments-wrapper{{overflow-x:auto}}.email-attachments-wrapper table{{min-width:860px}}.public-mbox-message-index{{min-width:980px;table-layout:auto}}.public-mbox-message-index th,.public-mbox-message-index td{{overflow-wrap:normal;word-break:normal}}.mbox-index-cell,.mbox-date-cell,.mbox-attachment-cell,.mbox-status-cell,.mbox-warning-cell{{white-space:nowrap}}.mbox-subject-cell,.mbox-from-cell,.mbox-to-cell{{overflow-wrap:break-word}}.download{{display:inline-block;margin:18px 0;padding:10px 14px;background:#245d61;color:#fff;text-decoration:none}}.public-document-admin-actions{{margin:24px 0;padding:14px 16px;border-left:4px solid #143a52;background:#fff}}.public-document-admin-actions h2{{margin-top:0;font-size:1.05rem}}.public-document-admin-actions p{{color:#555;line-height:1.5}}.admin-action-link{{display:inline-block;padding:9px 12px;background:#245d61;color:#fff;text-decoration:none}}.publication-provenance{{margin-top:28px}}.publication-provenance-grid{{display:grid;grid-template-columns:minmax(190px,0.42fr) minmax(0,1fr);background:#fff;border:1px solid #e1dfd8}}.publication-provenance-row{{display:contents}}.publication-provenance-label,.publication-provenance-value{{padding:10px;border-bottom:1px solid #e1dfd8;overflow-wrap:anywhere}}.publication-provenance-label{{font-weight:700;color:#555;background:#faf9f5}}.publication-provenance-value{{min-width:0}}.publication-pathway-wrapper{{overflow-x:auto}}.publication-pathway-table{{min-width:820px;table-layout:auto}}.publication-pathway-timestamp{{min-width:180px;white-space:nowrap}}.publication-pathway-previous-status,.publication-pathway-new-status{{min-width:145px;overflow-wrap:normal}}.publication-pathway-actor{{min-width:120px;overflow-wrap:anywhere}}.publication-pathway-note{{min-width:260px;width:100%}}.associated-records,.associated-documents{{margin-top:28px}}.association-boundary{{padding:14px;border-left:4px solid #2e8b9a;background:#fff}}.associated-records-list,.associated-documents-list{{display:grid;gap:12px}}.associated-record-card,.associated-document-card{{background:#fff;border:1px solid #e1dfd8;padding:14px;overflow-wrap:anywhere}}.associated-record-card h3,.associated-document-card h3{{margin:0 0 8px}}.associated-record-card dl,.associated-document-card dl{{display:grid;grid-template-columns:150px minmax(0,1fr);gap:6px 12px;margin:10px 0 0}}.associated-record-card dt,.associated-document-card dt{{font-weight:700;color:#555}}.associated-record-card dd,.associated-document-card dd{{margin:0}}@media(max-width:720px){{.publication-provenance-grid{{grid-template-columns:1fr}}.publication-provenance-label,.publication-provenance-value{{display:block}}.publication-pathway-table{{min-width:760px}}}}</style></head>
<body><main>{public_primary_navigation(active="documents")}{public_breadcrumbs([("Home", "/"), ("Archive", archive_return), ("Published Documents", "/archive?type=published_document"), (str(item["title"]), None)])}{archive_back_link(archive_return)}<p>{object_type_badge("published_document")}</p><h1>{escape(item['title'])}</h1><p class="governance">{escape(GOVERNANCE_STATEMENT)}</p><nav aria-label="Document sections"><a href="#document-metadata">Document metadata</a> · <a href="#publication-provenance">Publication provenance</a> · <a href="#publication-pathway">Publication pathway</a> · <a href="#document-content">Document content</a></nav>{admin_actions}<section id="document-metadata"><h2>Document Metadata</h2><table>{rows}</table></section>{content_block}{associated_records_section}{provenance_section}{pathway_section}</main></body></html>"""


@router.get("/documents", response_class=HTMLResponse)
def public_document_library(
    q: str | None = Query(None),
    institution: str | None = Query(None),
    category: str | None = Query(None),
    publication_year: str | None = Query(None),
):
    root = intake_root()
    all_documents = list_published_documents(root=root)
    documents = list_published_documents(
        query=q,
        institution=institution,
        category=category,
        publication_year=publication_year,
        root=root,
    )
    return HTMLResponse(
        content=_render_library(
            documents,
            all_documents,
            query=q,
            institution=institution,
            category=category,
            publication_year=publication_year,
        )
    )


@router.get("/documents/{document_id}", response_class=HTMLResponse)
def public_document_page(document_id: str, return_to: str | None = None, message: str | None = Query(None), page: str | None = Query(None)):
    try:
        item = load_published_document(document_id, root=intake_root())
    except ValueError as exc:
        _not_found(exc)
    return HTMLResponse(content=_render_document(item, return_to=return_to, message=message, page=page))


def _content_disposition(disposition: str, filename: str) -> str:
    safe_filename = str(filename or "document").replace("\\", "_").replace('"', "")
    safe_filename = Path(safe_filename).name
    return f'{disposition}; filename="{safe_filename}"'


@router.get("/documents/{document_id}/view")
def public_document_image_view(document_id: str):
    try:
        file_path, item = published_document_file(document_id, root=intake_root())
        if not (is_image_document(item) or is_audio_document(item)):
            raise ValueError("public_document_image_not_found")
    except ValueError as exc:
        _not_found(exc)
    return FileResponse(
        path=Path(file_path),
        media_type=document_media_type(item),
        headers={
            "Content-Disposition": _content_disposition(
                "inline",
                item["original_filename"],
            ),
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/documents/{document_id}/download")
def public_document_download(document_id: str):
    try:
        file_path, item = published_document_file(document_id, root=intake_root())
    except ValueError as exc:
        _not_found(exc)
    headers = None
    if is_image_document(item) or is_audio_document(item) or is_spreadsheet_document(item) or is_rich_text_document(item) or is_email_document(item) or is_mailbox_document(item):
        headers = {
            "Content-Disposition": _content_disposition(
                "attachment",
                item["original_filename"],
            ),
            "X-Content-Type-Options": "nosniff",
        }
    return FileResponse(
        path=Path(file_path),
        media_type=document_media_type(item),
        filename=item["original_filename"],
        headers=headers,
    )
