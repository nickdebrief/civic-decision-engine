from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse

from api import record_document_associations as rda
from api.canonical_record_types import RECORD_TYPE_LABELS
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
    is_gmail_takeout_document,
    is_imap_acquisition_document,
    is_outlook_archive_document,
    is_rich_text_document,
    is_spreadsheet_document,
    list_published_documents,
    load_published_document,
    published_document_file,
)
from api.document_lifecycle_presentation import (
    active_episode_decision,
    lifecycle_presentation_for_item,
)
from api.email_documents import APPLE_MAIL_GOVERNANCE_BOUNDARY
from api.email_documents import EMAIL_GOVERNANCE_BOUNDARY
from api.email_documents import MBOX_GOVERNANCE_BOUNDARY
from api.email_documents import OUTLOOK_GOVERNANCE_BOUNDARY
from api.email_attachment_preservation import (
    RELATIONSHIP_TYPE as EMAIL_ATTACHMENT_RELATIONSHIP_TYPE,
    get_relationship as get_email_attachment_relationship,
    list_attachment_sources,
    list_source_attachments,
)
from api.outlook_archives import OUTLOOK_ARCHIVE_BOUNDARY
from api.mailbox_relationship_graph import (
    MailboxGraphFilters,
    build_mailbox_relationship_graph,
)
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

ASSOCIATION_CARD_STYLES = """
.associated-records {
  --association-accent: #245d61;
  --association-border: #d8d4ca;
  --association-surface: #ffffff;
  --association-muted-surface: #faf9f5;
  --association-muted-text: #555555;
  margin-top: 28px;
}
.association-boundary.provenance-boundary {
  color: #1f2933;
  line-height: 1.55;
}
.associated-records .associated-records-list {
  display: grid;
  gap: 16px;
}
.association-card {
  min-width: 0;
  padding: 18px;
  border: 1px solid var(--association-border);
  border-radius: 4px;
  background: var(--association-surface);
  overflow-wrap: anywhere;
}
.association-card__label {
  margin: 0 0 4px;
  color: var(--association-muted-text);
  font-size: .78rem;
  font-weight: 750;
  letter-spacing: .04em;
  text-transform: uppercase;
}
.association-card__identifier {
  margin: 0;
  font: 700 1.1rem/1.35 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  overflow-wrap: anywhere;
}
.association-card__identifier a {
  color: var(--association-accent);
}
.association-card__relationship {
  margin: 10px 0 0;
}
.association-card__badge {
  display: inline-flex;
  max-width: 100%;
  padding: 4px 9px;
  border: 1px solid var(--association-accent);
  border-radius: 999px;
  background: var(--association-accent);
  color: #ffffff;
  font-size: .82rem;
  font-weight: 700;
  line-height: 1.35;
  overflow-wrap: anywhere;
  white-space: normal;
}
.association-card__summary {
  margin-top: 16px;
  padding-top: 14px;
  border-top: 1px solid var(--association-border);
}
.association-card__summary-label {
  margin: 0 0 5px;
  color: var(--association-muted-text);
  font-size: .78rem;
  font-weight: 750;
  text-transform: uppercase;
}
.association-card__summary-text {
  margin: 0;
  line-height: 1.5;
}
.association-card__metadata {
  display: grid;
  gap: 0;
  margin: 14px 0 0;
  border: 1px solid var(--association-border);
  background: var(--association-muted-surface);
}
.association-card__metadata-row {
  display: grid;
  grid-template-columns: minmax(120px, .36fr) minmax(0, 1fr);
}
.association-card__metadata-row + .association-card__metadata-row {
  border-top: 1px solid var(--association-border);
}
.association-card__metadata dt,
.association-card__metadata dd {
  min-width: 0;
  margin: 0;
  padding: 8px 10px;
  overflow-wrap: anywhere;
}
.association-card__metadata dt {
  color: var(--association-muted-text);
  font-weight: 700;
}
.association-card__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 9px;
  margin-top: 16px;
}
.association-card .button-link {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 40px;
  padding: 8px 12px;
  border: 1px solid var(--association-accent);
  border-radius: 3px;
  background: var(--association-accent);
  color: #ffffff;
  font-weight: 700;
  line-height: 1.25;
  text-align: center;
  text-decoration: none;
}
.association-card .button-link--secondary {
  background: transparent;
  color: var(--association-accent);
}
.association-card .button-link:hover {
  text-decoration: underline;
}
.association-card a:focus-visible {
  outline: 3px solid #2e8b9a;
  outline-offset: 2px;
}
@media (max-width: 560px) {
  .association-card {
    padding: 14px;
  }
  .association-card__metadata-row {
    grid-template-columns: 1fr;
  }
  .association-card__metadata dd {
    padding-top: 0;
  }
  .association-card__actions .button-link {
    flex: 1 1 100%;
    width: 100%;
  }
}
@media (prefers-color-scheme: dark) {
  .associated-records {
    --association-accent: #8dd5dd;
    --association-border: #374151;
    --association-surface: #1f2937;
    --association-muted-surface: #111827;
    --association-muted-text: #d1d5db;
  }
  .association-boundary.provenance-boundary {
    color: #e5e7eb;
  }
  .association-card__badge {
    background: #173f42;
    color: #b9ebe7;
  }
  .association-card .button-link {
    background: #8dd5dd;
    color: #111827;
  }
  .association-card .button-link--secondary {
    background: transparent;
    color: #8dd5dd;
  }
  .association-card a:focus-visible {
    outline-color: #8dd5dd;
  }
}
"""


def _not_found(exc: Exception):
    raise HTTPException(status_code=404, detail="public_document_not_found") from exc


def _date(value: object) -> str:
    return str(value or "Not available").split("T", 1)[0]


def _public_lifecycle_presentation(item: dict) -> dict:
    return lifecycle_presentation_for_item(item)


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
        f"""<article class="library-document-row">
          <div class="library-document-primary">
            <h2><a href="/documents/{escape(item['intake_id'])}">{escape(item['title'])}</a></h2>
            <p class="library-document-identifier"><strong>Document Identifier:</strong> <span>{escape(str(item.get('document_identifier') or '—'))}</span></p>
            <p class="library-document-status"><strong>Current status:</strong> Published</p>
          </div>
          <dl class="library-document-secondary">
            <div><dt>Institution / Source</dt><dd>{escape(item['institution_source'])}</dd></div>
            <div><dt>Category</dt><dd>{escape(item['category'])}</dd></div>
            <div><dt>Publication date</dt><dd>{escape(_date(item.get('publication_date')))}</dd></div>
            <div><dt>Optional Reference Identifier</dt><dd>{escape(str(item.get('reference_identifier') or '—'))}</dd></div>
            <div><dt>Lifecycle</dt><dd>{escape(_public_lifecycle_presentation(item).get('public_lifecycle_summary') or 'Original lifecycle')}</dd></div>
          </dl>
          <div class="library-document-description"><strong>Description:</strong> {escape(item['description'])}</div>
          <div class="library-document-action">{render_public_document_preview(item, root=intake_root())}</div>
        </article>"""
        for item in documents
    ) or '<p class="library-empty">No published documents match these criteria.</p>'
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
<style>*{{box-sizing:border-box}}body{{margin:0;background:#f7f7f4;color:#1f2933;font-family:system-ui,sans-serif}}main{{width:min(1240px,calc(100% - 32px));margin:32px auto 64px}}h1,h2{{color:#143a52}}{PUBLIC_NAVIGATION_CSS}.governance{{max-width:900px;padding:16px;border-left:4px solid #2e8b9a;background:#fff}}form{{display:grid;grid-template-columns:2fr repeat(3,1fr) auto;gap:10px;margin:24px 0}}input,select,button{{min-width:0;padding:9px;border:1px solid #c9c6bd;background:#fff;font:inherit}}button{{border-color:#245d61;background:#245d61;color:#fff;cursor:pointer}}a{{color:#245d61}}.result-count{{color:#555}}.library-results{{display:grid;gap:14px}}.library-document-row{{display:grid;grid-template-columns:minmax(0,1.2fr) minmax(0,1fr) minmax(0,1fr) minmax(118px,.42fr);gap:16px;align-items:start;padding:16px;background:#fff;border:1px solid #d8d4ca}}.library-document-primary,.library-document-secondary,.library-document-description,.library-document-action{{min-width:0}}.library-document-primary h2{{margin:0 0 8px;font-size:1.08rem;overflow-wrap:anywhere}}.library-document-primary h2 a{{overflow-wrap:anywhere}}.library-document-primary p,.library-document-description{{margin:6px 0;line-height:1.45;overflow-wrap:anywhere}}.library-document-identifier span{{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;overflow-wrap:anywhere}}.library-document-status{{font-weight:600}}.library-document-secondary{{display:grid;gap:7px;margin:0}}.library-document-secondary div{{display:grid;grid-template-columns:max-content minmax(0,1fr);gap:8px}}.library-document-secondary dt{{font-weight:700;color:#555}}.library-document-secondary dd{{margin:0;overflow-wrap:anywhere}}.library-document-description{{color:#555}}.library-document-action{{min-width:0}}.library-empty{{padding:18px;background:#fff;border:1px solid #d8d4ca}}.public-document-preview{{display:grid;gap:6px;justify-items:start;max-width:132px}}.public-document-thumbnail{{display:block;width:112px;max-width:100%;height:84px;object-fit:contain;background:#faf9f5;border:1px solid #d8d4ca}}.preview-thumbnail-link,.preview-fallback-link{{display:inline-grid;gap:5px;text-decoration:none;color:#143a52}}.preview-thumbnail-link:focus,.preview-fallback-link:focus,.preview-action:focus{{outline:3px solid #2e8b9a;outline-offset:2px}}.preview-fallback-link{{width:118px;min-height:84px;align-content:center;justify-items:center;padding:9px;border:1px solid #d8d4ca;background:#faf9f5;text-align:center}}.preview-file-glyph{{width:28px;height:34px;border:2px solid #245d61;border-radius:2px;background:#fff;box-shadow:8px -8px 0 -6px #245d61}}.preview-media-label{{font-weight:750;color:#143a52}}.preview-action,.preview-action-text{{font-size:.8rem;color:#245d61;text-decoration:underline}}.preview-unavailable{{font-weight:650;color:#6b4f00}}@media(max-width:900px){{form{{grid-template-columns:1fr}}.library-document-row{{grid-template-columns:1fr 1fr}}.library-document-action{{grid-column:2;grid-row:1 / span 2}}}}@media(max-width:600px){{.library-document-row{{display:block}}.library-document-secondary{{margin:12px 0}}.library-document-secondary div{{grid-template-columns:1fr;gap:2px}}.library-document-action{{margin-top:14px}}.public-document-thumbnail{{width:96px;height:72px}}}}</style></head>
<body><main>{public_primary_navigation(active="documents")}{public_breadcrumbs([("Home", "/"), ("Archive", "/archive"), ("Published Documents", None)])}<h1>Public Document Library</h1><p class="governance">{escape(GOVERNANCE_STATEMENT)}</p>
<form method="get" action="/documents"><input name="q" value="{escape(str(query or ''))}" placeholder="Search title, institution, category, or reference" aria-label="Search documents"><select name="institution" aria-label="Filter by institution"><option value="">All institutions</option>{options(institutions, institution)}</select><select name="category" aria-label="Filter by category"><option value="">All categories</option>{options(categories, category)}</select><select name="publication_year" aria-label="Filter by publication year"><option value="">All publication years</option>{options(years, publication_year)}</select><button type="submit">Search</button></form>
<p class="result-count">{len(documents)} published document{"s" if len(documents) != 1 else ""}.{f' Active query: {escape(active_query)}' if active_query else ''}</p><section class="library-results" aria-label="Published documents">{rows}</section></main></body></html>"""


def _display_value(value: object) -> str:
    if value is None or value == "":
        return "—"
    return str(value)


_TECHNICAL_PROVENANCE_FIELDS = {
    "Document Identifier",
    "IMAP acquisition hash",
    "Optional Reference Identifier",
    "Outlook archive job identifier",
    "SHA-256 digest",
    "SHA-512 digest",
}


def _publication_provenance_value_classes(label: str, value: object) -> str:
    classes = ["publication-provenance-value"]
    displayed_value = _display_value(value).strip().casefold()
    if displayed_value in {"", "—", "not available", "not applicable", "n/a"}:
        classes.append("publication-provenance-value--empty")
    if (
        label in _TECHNICAL_PROVENANCE_FIELDS
        or "timestamp" in label.casefold()
        or label == "Intake date and time"
    ):
        classes.append("publication-provenance-value--technical")
    return " ".join(classes)


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
    presentation = _public_lifecycle_presentation(item)
    event = active_episode_decision(presentation, new_status="published") or _first_event(item, "published")
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
    if is_outlook_archive_document(item):
        return "Outlook archive metadata, parser status, verification hashes, and original-file download"
    if is_gmail_takeout_document(item):
        return "Google Takeout archive metadata only; no message, attachment, or archive download"
    if is_imap_acquisition_document(item):
        return "IMAP acquisition metadata only; no mailbox, message, attachment, configuration, or archive download"
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
    if is_outlook_archive_document(item):
        return f"Original .{str(item.get('document_type') or 'pst').lower()} download available"
    if is_gmail_takeout_document(item):
        return "Original archive download not publicly exposed"
    if is_imap_acquisition_document(item):
        return "IMAP acquisition archive download not publicly exposed"
    if is_email_document(item) and document_type_label(item.get("document_type")) == "Microsoft Outlook Message":
        return "Original .msg download available"
    if is_email_document(item) and document_type_label(item.get("document_type")) == "Apple Mail Message":
        return "Original .emlx download available"
    if is_email_document(item):
        return "Original .eml download available"
    if item.get("document_type") == "email_attachment":
        return "Original preserved attachment download available"
    return "Original PDF download available"


def _media_family_label(item: dict) -> str:
    family = document_media_family(item)
    if family == "rich_text":
        return "Rich Text"
    if family == "email":
        return "Email"
    if family == "mailbox":
        if is_outlook_archive_document(item):
            return "Outlook Archive"
        if is_gmail_takeout_document(item):
            return "Google Takeout Archive"
        if is_imap_acquisition_document(item):
            return "IMAP Acquisition"
        return "Mailbox"
    return family.title()


def _render_publication_pathway(item: dict) -> str:
    presentation = _public_lifecycle_presentation(item)
    episodes = presentation.get("episodes", [])[1:]
    pathway_events = _pathway_events(item)
    if episodes:
        pathway_events = [
            (index, event)
            for index, event in pathway_events
            if not event.get("episode_id")
        ]
    rows = "".join(
        f"""<tr>
          <td class="publication-pathway-timestamp">{escape(_display_value(event.get('timestamp')))}</td>
          <td class="publication-pathway-previous-status">{escape(_status_label(event.get('previous_status')))}</td>
          <td class="publication-pathway-new-status">{escape(_status_label(event.get('new_status')))}</td>
          <td class="publication-pathway-actor">{escape(_display_value(event.get('actor')))}</td>
          <td class="publication-pathway-note">{escape(_display_value(event.get('note')))}</td>
        </tr>"""
        for _index, event in pathway_events
    ) or '<tr><td colspan="5">No lifecycle pathway entries are available.</td></tr>'
    episode_sections = ""
    if episodes:
        sections = []
        for episode in episodes:
            episode_events = episode.get("decisions", [])
            event_rows = "".join(
                f"<tr><td>{escape(_display_value(event.get('decided_at')))}</td><td>{escape(_status_label(event.get('previous_status')))}</td><td>{escape(_status_label(event.get('new_status')))}</td><td>{escape(_display_value(event.get('actor')))}</td><td>{escape(_display_value(event.get('rationale')))}</td></tr>"
                for event in episode_events
            ) or '<tr><td colspan="5">No lifecycle decisions recorded in this episode.</td></tr>'
            sections.append(
                f'<section class="publication-episode"><h3>Subsequent governed consideration — Episode {escape(str(episode.get("sequence") or ""))}</h3><p class="provenance-boundary">Initiated {escape(_display_value(episode.get("initiated")))}. The original lifecycle remains preserved; reconsideration did not reverse or erase earlier decisions. Initial state: Pending Intake.</p><div class="publication-pathway-wrapper"><table class="publication-pathway-table"><thead><tr><th>Timestamp</th><th>Previous status</th><th>New status</th><th>Actor</th><th>Note</th></tr></thead><tbody>{event_rows}</tbody></table></div></section>'
            )
        episode_sections = "".join(sections)
    return f"""<section id="publication-pathway" class="publication-pathway"><h2>Publication Pathway</h2><h3>Original lifecycle</h3><div class="publication-pathway-wrapper"><table class="publication-pathway-table"><thead><tr><th class="publication-pathway-timestamp">Timestamp</th><th class="publication-pathway-previous-status">Previous status</th><th class="publication-pathway-new-status">New status</th><th class="publication-pathway-actor">Actor</th><th class="publication-pathway-note">Note</th></tr></thead><tbody>{rows}</tbody></table></div>{episode_sections}<p class="provenance-boundary">Actor identifies the administrative identity recorded for the lifecycle action. It does not by itself establish authorship, factual verification, or legal responsibility for the document contents.</p></section>"""


def _render_publication_provenance(item: dict) -> str:
    presentation = _public_lifecycle_presentation(item)
    review_event = active_episode_decision(presentation, new_status="under_review") or _first_event(item, "under_review")
    approval_event = active_episode_decision(presentation, new_status="approved") or _first_event(item, "approved")
    publication_event = active_episode_decision(presentation, new_status="published") or _first_event(item, "published")
    initial_event = _first_event(item, "pending")
    email_metadata = _email_metadata(item)
    outlook_archive_metadata = _outlook_archive_metadata(item)
    gmail_takeout_metadata = _gmail_takeout_metadata(item)
    imap_acquisition_metadata = _imap_acquisition_metadata(item)
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
        ("Outlook archive type", outlook_archive_metadata.get("archive_type_label") if is_outlook_archive_document(item) else None),
        ("Outlook parser status", outlook_archive_metadata.get("parser_status_message") if is_outlook_archive_document(item) else None),
        ("Outlook parser version", outlook_archive_metadata.get("parser_version") if is_outlook_archive_document(item) else None),
        ("Outlook preservation complete", outlook_archive_metadata.get("preservation_complete") if is_outlook_archive_document(item) else None),
        ("Outlook hash verification status", outlook_archive_metadata.get("hash_verification_status") if is_outlook_archive_document(item) else None),
        ("Outlook inspection complete", outlook_archive_metadata.get("inspection_complete") if is_outlook_archive_document(item) else None),
        ("Outlook inspection timestamp", outlook_archive_metadata.get("inspection_timestamp") if is_outlook_archive_document(item) else None),
        ("Outlook projection state", outlook_archive_metadata.get("projection_state") if is_outlook_archive_document(item) else None),
        ("Outlook archive job identifier", outlook_archive_metadata.get("latest_archive_job_id") if is_outlook_archive_document(item) else None),
        ("Archive source", gmail_takeout_metadata.get("archive_type_label") if is_gmail_takeout_document(item) else None),
        ("Gmail Takeout parser version", gmail_takeout_metadata.get("parser_version") if is_gmail_takeout_document(item) else None),
        ("Gmail Takeout preservation complete", gmail_takeout_metadata.get("preservation_complete") if is_gmail_takeout_document(item) else None),
        ("Gmail Takeout projection state", gmail_takeout_metadata.get("projection_state") if is_gmail_takeout_document(item) else None),
        ("Archive source", imap_acquisition_metadata.get("archive_type_label") if is_imap_acquisition_document(item) else None),
        ("IMAP acquisition timestamp", imap_acquisition_metadata.get("acquisition_timestamp") if is_imap_acquisition_document(item) else None),
        ("IMAP acquisition hash", imap_acquisition_metadata.get("acquisition_hash") if is_imap_acquisition_document(item) else None),
        ("IMAP preservation complete", imap_acquisition_metadata.get("preservation_complete") if is_imap_acquisition_document(item) else None),
        ("IMAP projection state", imap_acquisition_metadata.get("projection_state") if is_imap_acquisition_document(item) else None),
        ("Original filename", item.get("original_filename")),
        ("File size", f"{item.get('file_size_bytes')} bytes" if item.get("file_size_bytes") is not None else None),
        ("SHA-256 digest", item.get("sha256_hash")),
        ("SHA-512 digest", item.get("sha512_hash") if is_outlook_archive_document(item) or is_gmail_takeout_document(item) or is_imap_acquisition_document(item) else None),
        ("Document Identifier", item.get("document_identifier")),
        ("Current lifecycle", presentation.get("public_lifecycle_summary") or "Original lifecycle"),
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
        f"""<div class="publication-provenance-row"><dt class="publication-provenance-label">{escape(label)}</dt><dd class="{_publication_provenance_value_classes(label, value)}">{escape(_display_value(value))}</dd></div>"""
        for label, value in provenance_fields
    )
    return f"""<section id="publication-provenance" class="publication-provenance"><h2>Publication Provenance</h2><p class="provenance-boundary">Publication provenance records the administrative pathway by which this document became publicly available through CDE. It does not certify the document’s legal status, evidential truth, authorship, or external validation.</p><dl class="publication-provenance-grid">{rows}</dl><p class="provenance-boundary">The SHA-256 digest identifies the exact original bytes admitted through Document Intake. It supports byte-level comparison of the preserved file but does not independently establish authorship, factual accuracy, legal status, or external authenticity.</p></section>"""



def _render_associated_record_card(association: dict) -> str:
    record_reference = str(association.get("record_reference") or "")
    relationship_label = str(association.get("public_label") or "Related record")
    metadata_fields = (
        (
            "Generated date",
            _date(association.get("record_generated_at"))
            if association.get("record_generated_at")
            else None,
        ),
        (
            "Trajectory",
            str(association.get("record_trajectory"))
            if association.get("record_trajectory")
            else None,
        ),
    )
    metadata_rows = "".join(
        f'<div class="association-card__metadata-row"><dt>{escape(label)}</dt><dd>{escape(value)}</dd></div>'
        for label, value in metadata_fields
        if value
    )
    metadata = (
        f'<dl class="association-card__metadata">{metadata_rows}</dl>'
        if metadata_rows
        else ""
    )
    return f"""<article class="association-card" aria-label="Canonical Record {escape(record_reference)}">
      <p class="association-card__label">Canonical Record</p>
      <h3 class="association-card__identifier"><a href="/verify/{escape(record_reference)}">{escape(record_reference)}</a></h3>
      <p class="association-card__relationship"><span class="association-card__badge">{escape(relationship_label)}</span></p>
      <div class="association-card__summary"><p class="association-card__summary-label">Association summary</p><p class="association-card__summary-text">{escape(_display_value(association.get('record_title')))}</p></div>
      {metadata}
      <nav class="association-card__actions" aria-label="Actions for Canonical Record {escape(record_reference)}"><a class="button-link association-card__action association-card__action--primary" href="/verify/{escape(record_reference)}">Open Canonical Record</a><a class="button-link button-link--secondary association-card__action association-card__action--secondary" href="/associations/{escape(str(association.get('public_reference') or ''))}">View association</a></nav>
    </article>"""


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
    cards = "".join(_render_associated_record_card(association) for association in associations)
    return f"""<section id="associated-records" class="associated-records"><h2>Associated Civic Records</h2><p class="association-boundary provenance-boundary">Association records a declared relationship between independently preserved objects. It does not by itself establish proof, sufficiency, factual truth, legal status, or external validation.</p><div class="associated-records-list">{cards}</div></section>"""


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


def _outlook_archive_metadata(item: dict) -> dict:
    metadata = item.get("outlook_archive_metadata")
    return metadata if isinstance(metadata, dict) else {}


def _gmail_takeout_metadata(item: dict) -> dict:
    metadata = item.get("gmail_takeout_metadata")
    return metadata if isinstance(metadata, dict) else {}


def _imap_acquisition_metadata(item: dict) -> dict:
    metadata = item.get("imap_acquisition_metadata")
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


def _render_mbox_relationship_graph(item: dict) -> str:
    document_id = escape(str(item.get("intake_id") or ""))
    endpoint = f"/api/mailbox/graph?document={document_id}"
    return f"""<section class="public-mbox-relationship-graph" id="mailbox-relationship-graph" data-mailbox-graph-endpoint="{endpoint}">
<h2>CDE Platform Stage 38C — Live Relationship Inspector Binding</h2>
<p class="provenance-boundary">The graph is generated deterministically from published mailbox projections. CDE Platform Stage 38C binds graph-node selection to live Relationship Inspector content through one selection pathway; it does not change relationship extraction or the graph API.</p>
<fieldset class="mailbox-graph-theme-toggle" aria-label="Relationship Graph Theme">
  <legend>Relationship Graph Theme</legend>
  <label><input id="mailbox-graph-theme-standard" name="mailbox-graph-theme" type="radio" value="standard" checked> Standard</label>
  <label><input id="mailbox-graph-theme-high-contrast" name="mailbox-graph-theme" type="radio" value="high-contrast"> High Contrast</label>
</fieldset>
<form class="mailbox-graph-filters" aria-label="Mailbox relationship graph filters">
  <label>Institution <input id="mailbox-graph-filter-institution" name="institution" type="search" autocomplete="off"></label>
  <label>Person <input id="mailbox-graph-filter-person" name="person" type="search" autocomplete="off"></label>
  <label>Case <input id="mailbox-graph-filter-case" name="case" type="search" autocomplete="off"></label>
  <label>Reference Number <input id="mailbox-graph-filter-reference" name="reference" type="search" autocomplete="off"></label>
  <label>Date from <input id="mailbox-graph-filter-from" name="from" type="date"></label>
  <label>Date to <input id="mailbox-graph-filter-to" name="to" type="date"></label>
  <label>Mailbox Status <input id="mailbox-graph-filter-status" name="status" type="search" autocomplete="off"></label>
  <label>Graph search <input id="mailbox-graph-search" name="graph_search" type="search" autocomplete="off" placeholder="Person, institution, reference, subject, case"></label>
  <label class="mailbox-graph-cluster-toggle"><input id="mailbox-graph-cluster-mode" name="cluster_mode" type="checkbox"> Cluster Mode</label>
  <button id="mailbox-graph-apply-filters" type="button">Apply filters</button>
  <button id="mailbox-graph-search-button" type="button">Search graph</button>
  <button id="mailbox-graph-fit" type="button">Fit to screen</button>
  <button id="mailbox-graph-reset-layout" type="button">Reset layout</button>
  <button id="mailbox-graph-clear-selection" type="button">Clear selection</button>
</form>
<p id="mailbox-graph-status" class="provenance-boundary" role="status" aria-live="polite">Relationship Graph loading.</p>
<div class="mailbox-graph-workspace">
  <div class="mailbox-graph-shell">
    <svg id="mailbox-relationship-graph-canvas" class="mailbox-relationship-graph-canvas" role="img" aria-label="Mailbox Relationship Graph" tabindex="0"></svg>
  </div>
  <aside id="mailbox-graph-info-panel" class="mailbox-graph-info-panel relationship-inspector" aria-live="polite" aria-label="Relationship Inspector">
    <h3>Relationship Inspector</h3>
    <p>Click or search for any node to inspect it.</p>
    <p>The Inspector will display:</p>
    <ul class="relationship-inspector-empty">
      <li>relationship summary</li>
      <li>connected entities</li>
      <li>metadata</li>
      <li>available actions</li>
    </ul>
  </aside>
</div>
<div class="mailbox-graph-legend" aria-label="Mailbox Relationship Graph legend">
  <span><i class="legend-icon legend-person" aria-hidden="true">●</i> Person</span>
  <span><i class="legend-icon legend-institution" aria-hidden="true">◆</i> Institution</span>
  <span><i class="legend-icon legend-email" aria-hidden="true">✉</i> Email</span>
  <span><i class="legend-icon legend-case" aria-hidden="true">■</i> Case</span>
  <span><i class="legend-icon legend-reference" aria-hidden="true">#</i> Reference</span>
  <span><i class="legend-icon legend-attachment" aria-hidden="true">▣</i> Attachment</span>
  <span><i class="legend-icon legend-intake" aria-hidden="true">▰</i> Intake Record</span>
</div>
<style>
  #mailbox-relationship-graph .relationship-inspector-title {{font-weight:800;color:#143a52;margin:0 0 10px}}
  #mailbox-relationship-graph .relationship-inspector-empty {{margin:10px 0 0;padding-left:18px;color:#555;line-height:1.5}}
  #mailbox-relationship-graph .relationship-inspector-section {{border-top:1px solid #d8d2c4;padding-top:10px;margin-top:10px}}
  #mailbox-relationship-graph .relationship-inspector-section h4 {{margin:0 0 8px;color:#143a52;font-size:.88rem;text-transform:uppercase;letter-spacing:.04em}}
  #mailbox-relationship-graph .relationship-inspector-badges {{display:flex;flex-wrap:wrap;gap:5px}}
  #mailbox-relationship-graph .relationship-inspector-badge {{display:inline-flex;align-items:center;border:1px solid #c9c2b5;background:#fff;padding:2px 6px;border-radius:999px;font-size:.78rem;color:#4B5B6A}}
  #mailbox-relationship-graph .relationship-inspector-muted {{color:#666}}
  #mailbox-relationship-graph[data-graph-theme="high-contrast"] .relationship-inspector-title,
  #mailbox-relationship-graph[data-graph-theme="high-contrast"] .relationship-inspector-section h4 {{color:#E5E7EB}}
  #mailbox-relationship-graph[data-graph-theme="high-contrast"] .relationship-inspector-badge {{background:#0F172A;border-color:#334155;color:#E5E7EB}}
</style>
<script>
(function() {{
  function initMailboxRelationshipGraph() {{
    const section = document.getElementById("mailbox-relationship-graph");
    if (!section || section.dataset.initialized === "true") return;
    section.dataset.initialized = "true";
    const svg = document.getElementById("mailbox-relationship-graph-canvas");
    const status = document.getElementById("mailbox-graph-status");
    const fitButton = document.getElementById("mailbox-graph-fit");
    const resetButton = document.getElementById("mailbox-graph-reset-layout");
    const clearSelectionButton = document.getElementById("mailbox-graph-clear-selection");
    const applyButton = document.getElementById("mailbox-graph-apply-filters");
    const searchInput = document.getElementById("mailbox-graph-search");
    const searchButton = document.getElementById("mailbox-graph-search-button");
    const clusterToggle = document.getElementById("mailbox-graph-cluster-mode");
    const infoPanel = document.getElementById("mailbox-graph-info-panel");
    const themeInputs = Array.from(section.querySelectorAll('input[name="mailbox-graph-theme"]'));
    if (!svg || !status || !fitButton || !resetButton || !clearSelectionButton || !applyButton || !searchInput || !searchButton || !clusterToggle || !infoPanel) return;
    const namespace = "http://www.w3.org/2000/svg";
    const LABEL_ZOOM_THRESHOLD = 1.35;
    const HIGH_IMPORTANCE_COUNT = 6;
    const THEME_STORAGE_KEY = "cde-mailbox-relationship-graph-theme";
    let graph = {{nodes: [], edges: []}};
    let visibleGraph = {{nodes: [], edges: []}};
    let cachedLayoutKey = "";
    let layoutCache = new Map();
    let selectedNode = null;
    let hoveredNode = null;
    let focusedNode = null;
    let searchMatches = new Set();
    let scale = 1;
    let panX = 0;
    let panY = 0;
    let dragState = null;
    let nodeDragState = null;
    let nodeDragMoved = false;
    let suppressNextNodeClick = false;
    let canvasDragMoved = false;
    let suppressNextCanvasClick = false;
    const width = 900;
    const height = 520;
    svg.setAttribute("viewBox", "0 0 " + width + " " + height);

    function colour(type) {{
      return {{
        Person: "#0F766E",
        Institution: "#7C3AED",
        Email: "#475569",
        Case: "#B45309",
        "Reference Number": "#2563EB",
        Attachment: "#16A34A",
        "Intake Record": "#DC2626",
        Cluster: "#64748B"
      }}[type] || "#4B5B6A";
    }}
    function icon(type) {{
      return {{
        Person: "●",
        Institution: "◆",
        Email: "✉",
        Case: "■",
        "Reference Number": "#",
        Attachment: "▣",
        "Intake Record": "▰",
        Cluster: "◌"
      }}[type] || "•";
    }}
    function escapeHTML(value) {{
      return String(value == null || value === "" ? "—" : value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
    }}
    function displayType(node) {{
      return node.type === "Reference Number" ? "Reference" : node.type;
    }}
    function filters() {{
      const params = new URLSearchParams(new URL(section.dataset.mailboxGraphEndpoint, window.location.origin).search);
      const fieldMap = {{
        institution: "mailbox-graph-filter-institution",
        person: "mailbox-graph-filter-person",
        case: "mailbox-graph-filter-case",
        reference: "mailbox-graph-filter-reference",
        from: "mailbox-graph-filter-from",
        to: "mailbox-graph-filter-to",
        status: "mailbox-graph-filter-status"
      }};
      Object.keys(fieldMap).forEach((key) => {{
        const input = document.getElementById(fieldMap[key]);
        if (input && input.value.trim()) params.set(key, input.value.trim());
      }});
      return params;
    }}
    function filterKey() {{
      return filters().toString();
    }}
    function adjacent(id) {{
      const linked = new Set([id]);
      visibleGraph.edges.forEach((edge) => {{
        if (edge.source === id) linked.add(edge.target);
        if (edge.target === id) linked.add(edge.source);
      }});
      return linked;
    }}
    function relationshipCount(id) {{
      return graph.edges.filter((edge) => edge.source === id || edge.target === id).length;
    }}
    function nodeById(id) {{
      return graph.nodeMap && graph.nodeMap.get(id);
    }}
    function visibleNodeById(id) {{
      return (visibleGraph.nodeMap && visibleGraph.nodeMap.get(id)) || nodeById(id);
    }}
    function graphEdgesFor(id) {{
      return graph.edges.filter((edge) => edge.source === id || edge.target === id);
    }}
    function graphNeighbours(node) {{
      const ids = new Set();
      graphEdgesFor(node.id).forEach((edge) => {{
        ids.add(edge.source === node.id ? edge.target : edge.source);
      }});
      return Array.from(ids).map(nodeById).filter(Boolean);
    }}
    function neighboursByType(node, type) {{
      return graphNeighbours(node)
        .filter((candidate) => candidate.type === type)
        .sort((a, b) => String(a.label).localeCompare(String(b.label)))
        .slice(0, 8);
    }}
    function listLabels(nodes) {{
      return nodes.length ? nodes.map((candidate) => escapeHTML(candidate.label)).join(" · ") : "—";
    }}
    function relationshipTypes(node) {{
      const counts = new Map();
      graphEdgesFor(node.id).forEach((edge) => {{
        counts.set(edge.relationship_type, (counts.get(edge.relationship_type) || 0) + 1);
      }});
      return Array.from(counts.entries()).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
    }}
    function relationshipBadges(node) {{
      return relationshipTypes(node).map((entry) => '<span class="relationship-inspector-badge">' + escapeHTML(entry[0]) + ' ' + entry[1] + '</span>').join("") || '<span class="relationship-inspector-muted">—</span>';
    }}
    function relatedEmailNodes(node) {{
      return node.type === "Email" ? [node] : neighboursByType(node, "Email");
    }}
    function datesFor(node) {{
      return relatedEmailNodes(node)
        .map((candidate) => candidate.metadata && candidate.metadata.date)
        .filter(Boolean)
        .sort();
    }}
    function firstAppearance(node) {{
      const dates = datesFor(node);
      return dates[0] || "—";
    }}
    function latestAppearance(node) {{
      const dates = datesFor(node);
      return dates[dates.length - 1] || "—";
    }}
    function recentActivity(node) {{
      const dates = datesFor(node).reverse().slice(0, 3);
      return dates.length ? dates.map(escapeHTML).join(" · ") : "—";
    }}
    function topConnectedEntities(node) {{
      return graphNeighbours(node)
        .sort((a, b) => relationshipCount(b.id) - relationshipCount(a.id) || String(a.label).localeCompare(String(b.label)))
        .slice(0, 5)
        .map((candidate) => escapeHTML(candidate.label))
        .join(" · ") || "—";
    }}
    function importantNodes() {{
      return new Set(
        graph.nodes
          .map((node) => [node.id, relationshipCount(node.id)])
          .sort((a, b) => b[1] - a[1] || String(a[0]).localeCompare(String(b[0])))
          .slice(0, HIGH_IMPORTANCE_COUNT)
          .map((entry) => entry[0])
      );
    }}
    function applyTheme(value) {{
      const theme = value === "high-contrast" ? "high-contrast" : "standard";
      section.dataset.graphTheme = theme;
      try {{ localStorage.setItem(THEME_STORAGE_KEY, theme); }} catch (error) {{}}
      themeInputs.forEach((input) => {{ input.checked = input.value === theme; }});
    }}
    function restoreTheme() {{
      let stored = "standard";
      try {{ stored = localStorage.getItem(THEME_STORAGE_KEY) || "standard"; }} catch (error) {{}}
      applyTheme(stored);
    }}
    function currentNodeSet() {{
      if (!clusterToggle.checked) {{
        visibleGraph = graph;
        return;
      }}
      const buckets = new Map();
      graph.nodes.forEach((node) => {{
        const institution = (node.metadata && (node.metadata.institution || node.metadata.document_identifier)) || node.type;
        const key = node.type + ":" + institution;
        if (!buckets.has(key)) buckets.set(key, []);
        buckets.get(key).push(node);
      }});
      const clusteredNodes = [];
      const idMap = new Map();
      buckets.forEach((nodes, key) => {{
        if (nodes.length < 4) {{
          nodes.forEach((node) => {{
            clusteredNodes.push(node);
            idMap.set(node.id, node.id);
          }});
          return;
        }}
        const clusterId = "cluster:" + key.toLowerCase().replace(/[^a-z0-9:-]+/g, "-");
        nodes.forEach((node) => idMap.set(node.id, clusterId));
        clusteredNodes.push({{
          id: clusterId,
          type: "Cluster",
          label: nodes[0].type + " cluster (" + nodes.length + ")",
          metadata: {{
            node_count: nodes.length,
            dominant_institution: nodes[0].metadata && (nodes[0].metadata.institution || nodes[0].metadata.document_identifier),
            cluster_members: nodes.map((node) => node.id)
          }}
        }});
      }});
      const edgeMap = new Map();
      graph.edges.forEach((edge) => {{
        const source = idMap.get(edge.source);
        const target = idMap.get(edge.target);
        if (!source || !target || source === target) return;
        const key = source + "|" + target + "|" + edge.relationship_type;
        if (!edgeMap.has(key)) edgeMap.set(key, {{source, target, relationship_type: edge.relationship_type, weight: 0, evidence_metadata: {{clustered: true}}}});
        edgeMap.get(key).weight += Number(edge.weight || 1);
      }});
      visibleGraph = {{
        nodes: clusteredNodes,
        edges: Array.from(edgeMap.values())
      }};
      visibleGraph.nodeMap = new Map(visibleGraph.nodes.map((node) => [node.id, node]));
    }}
    function layout() {{
      currentNodeSet();
      const key = filterKey() + "|cluster=" + clusterToggle.checked + "|nodes=" + visibleGraph.nodes.map((node) => node.id).join(",");
      if (layoutCache.has(key)) {{
        layoutCache.get(key).forEach((position, id) => {{
          const node = visibleGraph.nodeMap.get(id);
          if (node) {{
            node.x = position.x;
            node.y = position.y;
            node.vx = 0;
            node.vy = 0;
          }}
        }});
        cachedLayoutKey = key;
        return;
      }}
      const typeOrder = ["Intake Record", "Institution", "Case", "Reference Number", "Person", "Attachment", "Email", "Cluster"];
      visibleGraph.nodes.forEach((node, index) => {{
        const ring = Math.max(1, typeOrder.indexOf(node.type) + 1);
        const angle = (index / Math.max(1, graph.nodes.length)) * Math.PI * 2;
        const radius = 80 + ring * 48 + (index % 11) * 7;
        node.x = width / 2 + Math.cos(angle) * radius;
        node.y = height / 2 + Math.sin(angle) * radius;
        node.vx = 0;
        node.vy = 0;
      }});
      for (let step = 0; step < 140; step += 1) {{
        visibleGraph.nodes.forEach((source, index) => {{
          for (let j = index + 1; j < visibleGraph.nodes.length; j += 1) {{
            const target = visibleGraph.nodes[j];
            const dx = target.x - source.x;
            const dy = target.y - source.y;
            const distance = Math.max(20, Math.hypot(dx, dy));
            const repulsion = 620 / (distance * distance);
            const fx = dx / distance * repulsion;
            const fy = dy / distance * repulsion;
            source.vx -= fx;
            source.vy -= fy;
            target.vx += fx;
            target.vy += fy;
            const collision = source.type === "Cluster" || target.type === "Cluster" ? 58 : 36;
            if (distance < collision) {{
              const push = (collision - distance) * 0.02;
              source.vx -= dx / distance * push;
              source.vy -= dy / distance * push;
              target.vx += dx / distance * push;
              target.vy += dy / distance * push;
            }}
          }}
        }});
        visibleGraph.edges.forEach((edge) => {{
          const source = visibleGraph.nodeMap.get(edge.source);
          const target = visibleGraph.nodeMap.get(edge.target);
          if (!source || !target) return;
          const dx = target.x - source.x;
          const dy = target.y - source.y;
          const distance = Math.max(24, Math.hypot(dx, dy));
          const desired = Math.max(110, 250 - Math.min(100, Number(edge.weight || 1) * 8));
          const force = (distance - desired) * 0.0035;
          const fx = dx / distance * force;
          const fy = dy / distance * force;
          source.vx += fx; source.vy += fy;
          target.vx -= fx; target.vy -= fy;
        }});
        visibleGraph.nodes.forEach((node) => {{
          node.vx += (width / 2 - node.x) * 0.00045;
          node.vy += (height / 2 - node.y) * 0.00045;
          node.x += node.vx;
          node.y += node.vy;
          node.vx *= 0.78;
          node.vy *= 0.78;
        }});
      }}
      const positions = new Map();
      visibleGraph.nodes.forEach((node) => positions.set(node.id, {{x: node.x, y: node.y}}));
      layoutCache.set(key, positions);
      cachedLayoutKey = key;
    }}
    function edgeDash(edge) {{
      return {{
        "Replies To": "6 4",
        References: "2 4",
        "Mentions Reference": "2 3",
        "Attached To": "7 3"
      }}[edge.relationship_type] || "";
    }}
    function labelVisible(node, linked, degreeLeaders) {{
      return (
        selectedNode === node.id ||
        hoveredNode === node.id ||
        focusedNode === node.id ||
        searchMatches.has(node.id) ||
        node.type === "Cluster" ||
        scale >= LABEL_ZOOM_THRESHOLD ||
        (linked && linked.has(node.id)) ||
        degreeLeaders.has(node.id)
      );
    }}
    function centeredPan(node) {{
      panX = width / 2 - node.x * scale;
      panY = height / 2 - node.y * scale;
      render();
    }}
    function clearGraphSelection(reason) {{
      selectedNode = null;
      searchMatches = new Set();
      updateInfoPanel(null);
      render();
      if (reason !== "initial") status.textContent = "Relationship Inspector selection cleared.";
    }}
    function selectGraphNode(nodeId, selectionSource, options) {{
      const settings = options || {{}};
      const resolved = visibleNodeById(nodeId);
      if (!resolved) {{
        try {{ console.warn("Relationship Inspector selection could not resolve node", nodeId); }} catch (error) {{}}
        clearGraphSelection("stale");
        return null;
      }}
      selectedNode = resolved.id;
      const highlightIds = settings.highlightIds instanceof Set ? settings.highlightIds : adjacent(resolved.id);
      searchMatches = new Set(highlightIds);
      searchMatches.add(resolved.id);
      updateInfoPanel(resolved);
      if (settings.center === true) centeredPan(resolved); else render();
      status.textContent = displayType(resolved) + " selected: " + resolved.label + ".";
      return resolved;
    }}
    function render() {{
      svg.replaceChildren();
      const root = document.createElementNS(namespace, "g");
      root.setAttribute("transform", "translate(" + panX + " " + panY + ") scale(" + scale + ")");
      svg.appendChild(root);
      const linked = selectedNode ? adjacent(selectedNode) : null;
      const degreeLeaders = importantNodes();
      visibleGraph.edges.forEach((edge) => {{
        const source = visibleGraph.nodeMap.get(edge.source);
        const target = visibleGraph.nodeMap.get(edge.target);
        if (!source || !target) return;
        const line = document.createElementNS(namespace, "line");
        const active = !linked || (linked.has(edge.source) && linked.has(edge.target));
        line.setAttribute("x1", source.x);
        line.setAttribute("y1", source.y);
        line.setAttribute("x2", target.x);
        line.setAttribute("y2", target.y);
        line.setAttribute("stroke", active ? "#3B82F6" : "#94A3B8");
        line.setAttribute("stroke-width", active ? Math.max(1.4, Math.min(4, Number(edge.weight || 1) * 0.45)) : "0.8");
        line.setAttribute("opacity", active ? "0.72" : "0.18");
        line.setAttribute("stroke-dasharray", edgeDash(edge));
        line.dataset.relationshipType = edge.relationship_type;
        line.classList.add("mailbox-graph-edge");
        root.appendChild(line);
      }});
      visibleGraph.nodes.forEach((node) => {{
        const group = document.createElementNS(namespace, "g");
        const active = !linked || linked.has(node.id);
        group.setAttribute("tabindex", "0");
        group.setAttribute("role", "button");
        group.setAttribute("aria-label", node.type + ": " + node.label);
        group.setAttribute("aria-selected", selectedNode === node.id ? "true" : "false");
        group.setAttribute("transform", "translate(" + node.x + " " + node.y + ")");
        group.setAttribute("opacity", active ? "1" : "0.22");
        group.dataset.nodeId = node.id;
        group.classList.add("mailbox-graph-node");
        const circle = document.createElementNS(namespace, "circle");
        circle.setAttribute("r", node.type === "Cluster" ? "18" : node.type === "Email" ? "10" : "12");
        circle.setAttribute("fill", colour(node.type));
        circle.setAttribute("stroke", selectedNode === node.id ? "#FFFFFF" : searchMatches.has(node.id) ? "#FDE68A" : "#fff");
        circle.setAttribute("stroke-width", selectedNode === node.id || searchMatches.has(node.id) ? "3" : "1.5");
        if (hoveredNode === node.id) circle.classList.add("mailbox-graph-hover-glow");
        const glyph = document.createElementNS(namespace, "text");
        glyph.setAttribute("class", "mailbox-graph-node-icon");
        glyph.setAttribute("text-anchor", "middle");
        glyph.setAttribute("y", "4");
        glyph.textContent = icon(node.type);
        const text = document.createElementNS(namespace, "text");
        text.setAttribute("class", "mailbox-graph-label");
        text.setAttribute("x", "15");
        text.setAttribute("y", "4");
        text.textContent = node.label.length > 42 ? node.label.slice(0, 39) + "..." : node.label;
        text.setAttribute("opacity", labelVisible(node, linked, degreeLeaders) ? "1" : "0");
        group.appendChild(circle);
        group.appendChild(glyph);
        group.appendChild(text);
        group.addEventListener("click", () => {{
          if (suppressNextNodeClick) {{
            suppressNextNodeClick = false;
            return;
          }}
          selectGraphNode(node.id, "click");
        }});
        group.addEventListener("dblclick", (event) => {{
          event.preventDefault();
          selectGraphNode(node.id, "programmatic-focus", {{center: true}});
        }});
        group.addEventListener("pointerdown", (event) => {{
          event.stopPropagation();
          nodeDragMoved = false;
          nodeDragState = {{node, x: event.clientX, y: event.clientY, startX: node.x, startY: node.y}};
          group.setPointerCapture(event.pointerId);
        }});
        group.addEventListener("pointermove", (event) => {{
          if (!nodeDragState || nodeDragState.node !== node) return;
          const dx = event.clientX - nodeDragState.x;
          const dy = event.clientY - nodeDragState.y;
          if (Math.hypot(dx, dy) > 3) nodeDragMoved = true;
          node.x = nodeDragState.startX + dx / scale;
          node.y = nodeDragState.startY + dy / scale;
          render();
        }});
        group.addEventListener("pointerup", (event) => {{
          event.stopPropagation();
          if (nodeDragMoved) {{
            suppressNextNodeClick = true;
          }} else {{
            suppressNextNodeClick = true;
            selectGraphNode(node.id, "pointerup");
          }}
          nodeDragState = null;
          nodeDragMoved = false;
        }});
        group.addEventListener("mouseenter", () => {{ hoveredNode = node.id; render(); }});
        group.addEventListener("mouseleave", () => {{ hoveredNode = null; render(); }});
        group.addEventListener("focus", () => {{ focusedNode = node.id; render(); }});
        group.addEventListener("blur", () => {{ focusedNode = null; render(); }});
        group.addEventListener("keydown", (event) => {{
          if (event.key === "Enter" || event.key === " ") {{
            event.preventDefault();
            selectGraphNode(node.id, "keyboard");
          }} else if (event.key === "Escape") {{
            event.preventDefault();
            clearGraphSelection("keyboard");
          }} else if (event.key === "ArrowRight") {{
            event.preventDefault();
            panX -= 28;
            render();
          }} else if (event.key === "ArrowLeft") {{
            event.preventDefault();
            panX += 28;
            render();
          }} else if (event.key === "ArrowDown") {{
            event.preventDefault();
            panY -= 28;
            render();
          }} else if (event.key === "ArrowUp") {{
            event.preventDefault();
            panY += 28;
            render();
          }}
        }});
        root.appendChild(group);
      }});
      status.textContent = visibleGraph.nodes.length + " nodes and " + visibleGraph.edges.length + " relationships shown.";
    }}
    function connectedValues(node, type) {{
      return neighboursByType(node, type).map((candidate) => candidate.label).join(" · ") || "—";
    }}
    function inspectorRow(label, value) {{
      return '<dt>' + escapeHTML(label) + '</dt><dd>' + escapeHTML(value) + '</dd>';
    }}
    function inspectorOptionalRow(label, value) {{
      return value === undefined || value === null || value === "" ? "" : inspectorRow(label, value);
    }}
    function inspectorListRow(label, nodes) {{
      return '<dt>' + escapeHTML(label) + '</dt><dd>' + listLabels(nodes) + '</dd>';
    }}
    function neighbourSummary(node) {{
      const neighbourTypes = new Map();
      graphNeighbours(node).forEach((candidate) => {{
        neighbourTypes.set(displayType(candidate), (neighbourTypes.get(displayType(candidate)) || 0) + 1);
      }});
      const byType = Array.from(neighbourTypes.entries())
        .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
        .map((entry) => entry[0] + " " + entry[1])
        .join(" · ") || "—";
      return '<section class="relationship-inspector-section"><h4>Relationship Summary</h4><dl>' +
        inspectorRow("Stable node ID", node.id) +
        inspectorRow("Relationship count", relationshipCount(node.id)) +
        inspectorRow("Unique neighbour count", graphNeighbours(node).length) +
        '<dt>Relationship types</dt><dd class="relationship-inspector-badges">' + relationshipBadges(node) + '</dd>' +
        inspectorRow("Neighbour types", byType) +
        inspectorRow("Top connected entities", topConnectedEntities(node)) +
        inspectorRow("Connected institutions", listLabels(neighboursByType(node, "Institution"))) +
        inspectorRow("Connected people", listLabels(neighboursByType(node, "Person"))) +
        inspectorRow("Connected cases", listLabels(neighboursByType(node, "Case"))) +
        inspectorRow("Connected references", listLabels(neighboursByType(node, "Reference Number"))) +
        inspectorRow("Connected attachments", listLabels(neighboursByType(node, "Attachment"))) +
        inspectorRow("Recent activity", recentActivity(node)) +
        '</dl></section>';
    }}
    function metadataRows(node) {{
      const metadata = node.metadata || {{}};
      const type = node.type;
      if (type === "Institution") {{
        return inspectorRow("Institution name", node.label) +
          inspectorRow("Institution type", metadata.source || "Mailbox institution") +
          inspectorRow("Relationship degree", relationshipCount(node.id)) +
          inspectorListRow("Connected emails", neighboursByType(node, "Email")) +
          inspectorListRow("Connected people", neighboursByType(node, "Person")) +
          inspectorListRow("Connected references", neighboursByType(node, "Reference Number")) +
          inspectorListRow("Connected cases", neighboursByType(node, "Case")) +
          inspectorRow("First appearance", firstAppearance(node)) +
          inspectorRow("Latest appearance", latestAppearance(node));
      }}
      if (type === "Person") {{
        return inspectorRow("Name", node.label) +
          inspectorRow("Institution", connectedValues(node, "Institution")) +
          inspectorRow("Relationship degree", relationshipCount(node.id)) +
          inspectorListRow("Emails", neighboursByType(node, "Email")) +
          inspectorListRow("Cases", neighboursByType(node, "Case")) +
          inspectorListRow("References", neighboursByType(node, "Reference Number")) +
          inspectorRow("First appearance", firstAppearance(node)) +
          inspectorRow("Latest appearance", latestAppearance(node));
      }}
      if (type === "Email") {{
        return inspectorRow("Subject", node.label) +
          inspectorRow("Date", metadata.date) +
          inspectorRow("Sender", listLabels(graph.edges.filter((edge) => edge.source === node.id && edge.relationship_type === "Sent By").map((edge) => nodeById(edge.target)).filter(Boolean))) +
          inspectorRow("Recipients", listLabels(graph.edges.filter((edge) => edge.source === node.id && edge.relationship_type === "Sent To").map((edge) => nodeById(edge.target)).filter(Boolean))) +
          inspectorRow("CC", listLabels(graph.edges.filter((edge) => edge.source === node.id && edge.relationship_type === "CC").map((edge) => nodeById(edge.target)).filter(Boolean))) +
          inspectorListRow("Attachments", neighboursByType(node, "Attachment")) +
          inspectorListRow("Reference numbers", neighboursByType(node, "Reference Number")) +
          inspectorRow("Case", connectedValues(node, "Case")) +
          inspectorRow("Verification hash", metadata.message_digest) +
          inspectorRow("Relationship degree", relationshipCount(node.id));
      }}
      if (type === "Reference Number") {{
        return inspectorRow("Reference number", node.label) +
          inspectorRow("Appears in", relatedEmailNodes(node).length + " email(s)") +
          inspectorListRow("Connected institutions", neighboursByType(node, "Institution")) +
          inspectorListRow("Connected people", neighboursByType(node, "Person")) +
          inspectorListRow("Connected cases", neighboursByType(node, "Case")) +
          inspectorListRow("Connected emails", neighboursByType(node, "Email"));
      }}
      if (type === "Case") {{
        return inspectorRow("Case identifier", node.label) +
          inspectorListRow("Connected institutions", neighboursByType(node, "Institution")) +
          inspectorListRow("Connected people", neighboursByType(node, "Person")) +
          inspectorListRow("Connected emails", neighboursByType(node, "Email")) +
          inspectorListRow("Connected references", neighboursByType(node, "Reference Number")) +
          inspectorRow("Relationship degree", relationshipCount(node.id));
      }}
      if (type === "Attachment") {{
        return inspectorRow("Filename", node.label) +
          inspectorRow("File type", metadata.media_type) +
          inspectorOptionalRow("Attachment ID", metadata.attachment_id) +
          inspectorOptionalRow("SHA-256", metadata.sha256_hash) +
          inspectorOptionalRow("File size", metadata.file_size_bytes) +
          inspectorOptionalRow("Originating archive", metadata.originating_archive) +
          inspectorOptionalRow("Originating message", metadata.originating_message) +
          inspectorOptionalRow("Extraction time", metadata.extraction_time) +
          inspectorOptionalRow("Promotion status", metadata.promotion_status) +
          inspectorOptionalRow("Existing Canonical Record", metadata.canonical_record_reference) +
          inspectorListRow("Linked emails", neighboursByType(node, "Email")) +
          inspectorListRow("Linked references", neighboursByType(node, "Reference Number")) +
          inspectorRow("Verification hash", metadata.sha256_hash || metadata.message_digest || metadata.content_id);
      }}
      if (type === "Intake Record") {{
        return inspectorRow("Record title", node.label) +
          inspectorRow("Status", metadata.status || "Published mailbox archive") +
          inspectorRow("Institution", connectedValues(node, "Institution")) +
          inspectorListRow("Connected emails", neighboursByType(node, "Email")) +
          inspectorListRow("Connected references", neighboursByType(node, "Reference Number")) +
          inspectorRow("Verification hash", metadata.document_id) +
          inspectorRow("Publication status", metadata.publication_status || "Published");
      }}
      if (type === "Cluster") {{
        const members = Array.isArray(metadata.cluster_members) ? metadata.cluster_members.map(nodeById).filter(Boolean) : [];
        const representedTypes = Array.from(new Set(members.map((member) => displayType(member)))).sort().join(" · ") || "—";
        const representativeNodes = members.slice(0, 6).map((member) => member.label).join(" · ") || "—";
        return inspectorRow("Cluster type", node.label) +
          inspectorRow("Cluster size", metadata.node_count) +
          inspectorRow("Represented node types", representedTypes) +
          inspectorRow("Dominant institution", metadata.dominant_institution) +
          inspectorRow("Total internal relationships", metadata.internal_relationships || "—") +
          inspectorRow("External relationships", relationshipCount(node.id)) +
          inspectorRow("Representative nodes", representativeNodes);
      }}
      return inspectorRow("Title", node.label) + inspectorRow("Relationship degree", relationshipCount(node.id));
    }}
    function quickActions(node) {{
      const metadata = node.metadata || {{}};
      const actions = [];
      function button(label, action, filter) {{
        actions.push('<button class="mailbox-graph-action" type="button" data-action="' + action + '"' + (filter ? ' data-filter="' + filter + '"' : '') + '>' + escapeHTML(label) + '</button>');
      }}
      if (node.type === "Email" && metadata.url) actions.push('<a class="mailbox-graph-action" href="' + escapeHTML(metadata.url) + '">Open message</a>');
      if (node.type === "Institution") {{
        button("Open related messages", "open_related_messages", "institution");
        button("Highlight neighbours", "highlight_neighbours");
        button("Focus graph", "focus_graph");
        button("Filter by institution", "filter", "institution");
        button("Collapse others", "collapse_others");
      }} else if (node.type === "Person") {{
        button("Highlight neighbours", "highlight_neighbours");
        button("Filter by person", "filter", "person");
        button("Focus graph", "focus_graph");
      }} else if (node.type === "Email") {{
        button("Highlight thread", "highlight_thread");
        button("Show reply chain", "show_reply_chain");
        button("Highlight attachments", "highlight_attachments");
        button("Focus graph", "focus_graph");
      }} else if (node.type === "Reference Number") {{
        button("Highlight all", "highlight_neighbours");
        button("Filter mailbox", "filter", "reference");
        button("Filter by reference", "filter", "reference");
        button("Focus graph", "focus_graph");
      }} else if (node.type === "Case") {{
        button("Filter mailbox", "filter", "case");
        button("Filter by case", "filter", "case");
        button("Highlight case", "highlight_neighbours");
        button("Focus graph", "focus_graph");
      }} else if (node.type === "Attachment") {{
        const related = neighboursByType(node, "Email")[0];
        if (related && related.metadata && related.metadata.url) actions.push('<a class="mailbox-graph-action" href="' + escapeHTML(related.metadata.url) + '">Open related message</a>');
        if (metadata.url) actions.push('<a class="mailbox-graph-action" href="' + escapeHTML(metadata.url) + '">Open governed attachment</a>');
        button("Highlight reuse", "highlight_neighbours");
        button("Focus graph", "focus_graph");
      }} else if (node.type === "Intake Record") {{
        if (metadata.document_id) actions.push('<a class="mailbox-graph-action" href="/documents/' + escapeHTML(metadata.document_id) + '">Open record</a>');
        button("Highlight provenance", "highlight_neighbours");
        button("Focus graph", "focus_graph");
      }} else if (node.type === "Cluster") {{
        button("Expand cluster", "expand_cluster");
        button("Focus graph", "focus_graph");
      }}
      return actions.join("");
    }}
    function bindInspectorActions(node) {{
      infoPanel.querySelectorAll('button[data-action]').forEach((button) => {{
        button.addEventListener("click", () => {{
          const action = button.dataset.action;
          if (action === "filter") {{
            const input = document.getElementById("mailbox-graph-filter-" + button.dataset.filter);
            if (input) {{
              input.value = node.label;
              loadGraph(true);
            }}
          }} else if (action === "open_related_messages") {{
            const input = document.getElementById("mailbox-graph-filter-" + button.dataset.filter);
            if (input) input.value = node.label;
            loadGraph(true);
          }} else if (action === "focus_graph") {{
            selectGraphNode(node.id, "quick-action", {{center: true}});
          }} else if (action === "collapse_others" || action === "highlight_neighbours") {{
            selectGraphNode(node.id, "quick-action", {{highlightIds: adjacent(node.id)}});
          }} else if (action === "highlight_thread" || action === "show_reply_chain") {{
            const highlightIds = new Set([node.id]);
            graphEdgesFor(node.id)
              .filter((edge) => edge.relationship_type === "Replies To" || edge.relationship_type === "References")
              .forEach((edge) => {{
                highlightIds.add(edge.source);
                highlightIds.add(edge.target);
              }});
            selectGraphNode(node.id, "quick-action", {{highlightIds}});
          }} else if (action === "highlight_attachments") {{
            const highlightIds = new Set([node.id, ...neighboursByType(node, "Attachment").map((candidate) => candidate.id)]);
            selectGraphNode(node.id, "quick-action", {{highlightIds}});
          }} else if (action === "expand_cluster") {{
            expandCluster(node);
          }}
        }});
      }});
    }}
    function updateInfoPanel(node) {{
      if (!node) {{
        infoPanel.innerHTML = '<h3>Relationship Inspector</h3><p>Click or search for any node to inspect it.</p><p>The Inspector will display:</p><ul class="relationship-inspector-empty"><li>relationship summary</li><li>connected entities</li><li>metadata</li><li>available actions</li></ul>';
        return;
      }}
      const actions = quickActions(node);
      infoPanel.innerHTML = '<h3>' + escapeHTML(displayType(node)) + '</h3>' +
        '<p class="relationship-inspector-title">' + escapeHTML(node.label) + '</p>' +
        neighbourSummary(node) +
        '<section class="relationship-inspector-section"><h4>Metadata</h4><dl>' + metadataRows(node) + '</dl></section>' +
        (actions ? '<section class="relationship-inspector-section"><h4>Available actions</h4><div class="mailbox-graph-actions">' + actions + '</div></section>' : '');
      bindInspectorActions(node);
    }}
    function fit() {{
      scale = 1;
      panX = 0;
      panY = 0;
      render();
    }}
    function resetLayout() {{
      layoutCache.delete(cachedLayoutKey);
      layout();
      fit();
    }}
    function runSearch() {{
      const query = searchInput.value.trim().toLowerCase();
      searchMatches = new Set();
      if (!query) {{
        render();
        return;
      }}
      const matches = graph.nodes.filter((node) => {{
        const metadata = JSON.stringify(node.metadata || {{}}).toLowerCase();
        return node.label.toLowerCase().includes(query) || node.type.toLowerCase().includes(query) || metadata.includes(query);
      }});
      matches.forEach((node) => searchMatches.add(node.id));
      const first = matches[0] || visibleGraph.nodes.find((node) => {{
        const metadata = JSON.stringify(node.metadata || {{}}).toLowerCase();
        return node.label.toLowerCase().includes(query) || node.type.toLowerCase().includes(query) || metadata.includes(query);
      }});
      if (first) {{
        if (!visibleGraph.nodeMap || !visibleGraph.nodeMap.has(first.id)) {{
          clusterToggle.checked = false;
          layout();
        }}
        const highlightIds = new Set(searchMatches);
        highlightIds.add(first.id);
        graphEdgesFor(first.id).forEach((edge) => {{
          highlightIds.add(edge.source);
          highlightIds.add(edge.target);
        }});
        selectGraphNode(first.id, "search", {{center: true, highlightIds}});
      }} else {{
        render();
      }}
    }}
    function expandCluster(node) {{
      if (node.type !== "Cluster") return;
      const members = node.metadata && Array.isArray(node.metadata.cluster_members) ? node.metadata.cluster_members : [];
      clusterToggle.checked = false;
      layout();
      const memberId = members.find((id) => visibleNodeById(id));
      if (memberId) {{
        selectGraphNode(memberId, "cluster-expand", {{center: true}});
      }} else {{
        clearGraphSelection("cluster-expand");
      }}
    }}
    function loadGraph(filtersChanged) {{
      status.textContent = "Relationship Graph loading.";
      const previousSelection = selectedNode;
      const url = new URL(section.dataset.mailboxGraphEndpoint, window.location.origin);
      filters().forEach((value, key) => url.searchParams.set(key, value));
      fetch(url.toString(), {{headers: {{"Accept": "application/json"}}}})
        .then((response) => {{
          if (!response.ok) throw new Error("Graph request failed");
          return response.json();
        }})
        .then((payload) => {{
          graph = {{
            nodes: Array.isArray(payload.nodes) ? payload.nodes : [],
            edges: Array.isArray(payload.edges) ? payload.edges : []
          }};
          graph.nodeMap = new Map(graph.nodes.map((node) => [node.id, node]));
          hoveredNode = null;
          focusedNode = null;
          searchMatches = new Set();
          if (filtersChanged) {{
            scale = 1;
            panX = 0;
            panY = 0;
          }}
          layout();
          if (previousSelection && graph.nodeMap.has(previousSelection)) {{
            selectGraphNode(previousSelection, filtersChanged ? "filter-preserve" : "payload-preserve");
            if (filtersChanged) fit();
          }} else {{
            selectedNode = null;
            updateInfoPanel(null);
            if (filtersChanged) fit(); else render();
          }}
        }})
        .catch(() => {{
          status.textContent = "Relationship Graph could not be loaded.";
        }});
    }}
    svg.addEventListener("wheel", (event) => {{
      event.preventDefault();
      scale = Math.max(0.35, Math.min(2.8, scale + (event.deltaY < 0 ? 0.08 : -0.08)));
      render();
    }});
    svg.addEventListener("pointerdown", (event) => {{
      if (nodeDragState) return;
      canvasDragMoved = false;
      dragState = {{x: event.clientX, y: event.clientY, panX, panY}};
      svg.setPointerCapture(event.pointerId);
    }});
    svg.addEventListener("pointermove", (event) => {{
      if (!dragState) return;
      const dx = event.clientX - dragState.x;
      const dy = event.clientY - dragState.y;
      if (Math.hypot(dx, dy) > 3) canvasDragMoved = true;
      panX = dragState.panX + dx;
      panY = dragState.panY + dy;
      render();
    }});
    svg.addEventListener("pointerup", (event) => {{
      if (event.target === svg && !canvasDragMoved) {{
        suppressNextCanvasClick = true;
        clearGraphSelection("canvas-pointerup");
      }} else if (canvasDragMoved) {{
        suppressNextCanvasClick = true;
      }}
      dragState = null;
      canvasDragMoved = false;
    }});
    svg.addEventListener("click", (event) => {{
      if (event.target === svg) {{
        if (suppressNextCanvasClick) {{
          suppressNextCanvasClick = false;
          return;
        }}
        clearGraphSelection("canvas");
      }}
    }});
    svg.addEventListener("keydown", (event) => {{
      if (event.key === "Escape") {{
        event.preventDefault();
        clearGraphSelection("keyboard");
      }}
    }});
    themeInputs.forEach((input) => input.addEventListener("change", () => applyTheme(input.value)));
    restoreTheme();
    fitButton.addEventListener("click", fit);
    resetButton.addEventListener("click", resetLayout);
    clearSelectionButton.addEventListener("click", () => clearGraphSelection("control"));
    applyButton.addEventListener("click", () => loadGraph(true));
    searchButton.addEventListener("click", runSearch);
    searchInput.addEventListener("keydown", (event) => {{
      if (event.key === "Enter") {{
        event.preventDefault();
        runSearch();
      }}
    }});
    clusterToggle.addEventListener("change", () => {{
      const previousSelection = selectedNode;
      layout();
      if (previousSelection && visibleNodeById(previousSelection)) {{
        selectGraphNode(previousSelection, "cluster-toggle");
      }} else if (previousSelection && graph.nodeMap && graph.nodeMap.has(previousSelection)) {{
        clearGraphSelection("cluster-toggle");
      }} else {{
        render();
      }}
    }});
    loadGraph(true);
  }}
  if (document.readyState === "loading") {{
    document.addEventListener("DOMContentLoaded", initMailboxRelationshipGraph);
  }} else {{
    initMailboxRelationshipGraph();
  }}
}})();
</script>
</section>"""


def _mailbox_page_link(document_id: str, page: int, label: str, *, current: bool = False) -> str:
    href = f"/documents/{escape(document_id)}?{escape(urlencode({'page': str(page)}))}#mailbox-message-index"
    current_attr = ' aria-current="page"' if current else ""
    return (
        f'<a class="mailbox-page-link" aria-label="Mailbox message index page {page}"'
        f'{current_attr} href="{href}">{escape(label)}</a>'
    )


def _render_mbox_message_pagination(
    *, document_id: str, page: int, page_count: int, page_size: int, total: int
) -> str:
    if total == 0 or page_count <= 1:
        return ""
    previous_link = ""
    next_link = ""
    if page > 1:
        previous_link = _mailbox_page_link(document_id, page - 1, "Previous page")
    if page < page_count:
        next_link = _mailbox_page_link(document_id, page + 1, "Next page")
    numbered = "".join(
        _mailbox_page_link(document_id, index, str(index), current=index == page)
        for index in range(1, page_count + 1)
    )
    return (
        '<nav class="mailbox-message-pagination" aria-label="Mailbox message index pagination">'
        f'<span>Page {page} of {page_count}</span>{previous_link}'
        f'<span class="mailbox-page-numbers">{numbered}</span>{next_link}'
        f'<span class="mailbox-page-size">Bounded to {page_size} message projections per page.</span>'
        "</nav>"
    )


def _render_mbox_document(item: dict, *, message_index: object | None = None, page: object | None = None) -> str:
    metadata = _email_metadata(item)
    messages = [message for message in (metadata.get("messages") or []) if isinstance(message, dict)]
    try:
        current_page = int(page or 1)
    except (TypeError, ValueError):
        current_page = 1
    current_page = current_page if current_page > 0 else 1
    page_size = 25
    total_pages = max(1, (len(messages) + page_size - 1) // page_size)
    current_page = min(current_page, total_pages)
    start = (current_page - 1) * page_size
    visible_messages = messages[start : start + page_size]
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
    pagination_controls = _render_mbox_message_pagination(
        document_id=str(item.get("intake_id") or ""),
        page=current_page,
        page_count=total_pages,
        page_size=page_size,
        total=len(messages),
    )
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
    graph = _render_mbox_relationship_graph(item)
    return f"""<nav class="mailbox-tabs" aria-label="Mailbox sections"><a href="#mailbox-inbox">Inbox</a><a href="#mailbox-cases">Cases</a><a href="#mailbox-timeline">Timeline</a><a href="#mailbox-relationship-graph">Relationship Graph</a></nav>
<section class="public-mbox-summary" id="mailbox-inbox"><h2>Mailbox Overview</h2><p class="provenance-boundary">{escape(MBOX_GOVERNANCE_BOUNDARY)}</p><table>{overview_rows}</table></section>
<section class="public-mbox-index" id="mailbox-message-index"><h2>Mailbox Message Index</h2>{pagination}{pagination_controls}<div class="email-attachments-wrapper"><table class="public-mbox-message-index"><thead><tr><th>Index</th><th>Date</th><th>From</th><th>Subject</th><th>To</th><th>Attachment count</th><th>Parse status</th><th>Warning indicator</th></tr></thead><tbody>{index_rows}</tbody></table></div>{pagination_controls}<p class="provenance-boundary">Parser warnings: {escape(_display_value(warning_text))}</p></section>
<section class="public-mbox-placeholder" id="mailbox-cases"><h2>Cases</h2><p class="provenance-boundary">Case relationships are represented in the Relationship Graph when case references are present in the mailbox projection.</p></section>
<section class="public-mbox-placeholder" id="mailbox-timeline"><h2>Timeline</h2><p class="provenance-boundary">Chronological access remains available through the Mailbox Message Index and message dates recorded in the preserved archive.</p></section>
{graph}
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
    preserved_attachments = _render_source_email_attachments(item)
    return f"""<section class="public-email-summary"><h2>Email Overview</h2><p class="provenance-boundary">{escape(boundary)}</p><table>{overview_rows}</table></section>
{apple_section}
<section class="public-email-body"><h2>Message Body</h2>{plain_block}{html_block}{rtf_notice}</section>
<section class="public-email-attachments"><h2>Attachments</h2><p class="provenance-boundary">{stage_label} records source attachment metadata. CDE Platform Stage 49 preserves successfully extracted attachment bytes as independent Published Document intake objects governed by their own lifecycle.</p><div class="email-attachments-wrapper"><table><thead><tr><th>Index</th><th>Filename</th><th>Long filename</th><th>Media type</th><th>Byte size</th><th>Disposition</th><th>Content ID</th><th>Attachment method</th><th>MIME tag</th><th>Attached message</th><th>Generated filename</th></tr></thead><tbody>{attachment_rows}</tbody></table></div><p class="provenance-boundary">Parser warnings: {escape(_display_value(warning_text))}</p>{preserved_attachments}</section>
<section class="public-email-boundary"><h2>Email Governance Boundary</h2><p class="provenance-boundary">{escape(boundary)}</p></section>"""


def _format_file_size(value: Any) -> str:
    try:
        size = int(value)
    except (TypeError, ValueError):
        return "Not recorded"
    if size < 1024:
        return f"{size} bytes"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def _email_attachment_metadata_rows(values: list[tuple[str, Any]]) -> str:
    return "".join(
        f'<div class="association-card__metadata-row"><dt>{escape(label)}</dt><dd>{escape(_display_value(value))}</dd></div>'
        for label, value in values
        if value not in (None, "")
    )


def _render_source_email_attachments(item: dict) -> str:
    relationships = list_source_attachments(str(item.get("intake_id") or ""), root=intake_root())
    if not relationships:
        return ""
    cards: list[str] = []
    for relationship in relationships:
        attachment = relationship.get("attachment_document") or {}
        is_public = attachment.get("status") == "published"
        identifier = attachment.get("document_identifier") or "Preservation incomplete"
        title = relationship.get("display_title") or relationship.get("original_filename") or "Attachment"
        metadata_rows = _email_attachment_metadata_rows(
            [
                ("Attachment index", relationship.get("attachment_index")),
                ("File type", relationship.get("mime_type")),
                ("File size", _format_file_size(relationship.get("file_size_bytes"))),
                ("Source status", "Inline" if relationship.get("inline_status") else "Attachment"),
                ("Preservation status", relationship.get("extraction_status")),
            ]
        )
        actions = ""
        if is_public:
            actions = f'<nav class="association-card__actions" aria-label="Actions for {escape(str(title))}"><a class="button-link association-card__action association-card__action--primary" href="/documents/{escape(str(attachment.get("intake_id")))}">Open Published Document</a><a class="button-link button-link--secondary association-card__action association-card__action--secondary" href="/email-attachment-relationships/{escape(str(relationship.get("relationship_id")))}">View relationship</a></nav>'
        elif relationship.get("extraction_status") == "failed":
            actions = '<p class="association-card__summary-text">Preservation incomplete. No attachment Published Document link was created.</p>'
        else:
            actions = '<p class="association-card__summary-text">The attachment is preserved but has not completed the Published Document lifecycle.</p>'
        cards.append(
            f'''<article class="association-card email-attachment-card" aria-label="Email attachment {escape(str(title))}"><p class="association-card__label">Attachment Published Document</p><h3 class="association-card__identifier">{escape(str(identifier))}</h3><p class="association-card__relationship"><span class="association-card__badge">{escape(EMAIL_ATTACHMENT_RELATIONSHIP_TYPE)}</span></p><div class="association-card__summary"><p class="association-card__summary-label">Attachment</p><p class="association-card__summary-text">{escape(str(title))}</p></div><dl class="association-card__metadata">{metadata_rows}</dl>{actions}</article>'''
        )
    return f'<section class="independent-email-attachments" aria-labelledby="independent-email-attachments-heading"><h3 id="independent-email-attachments-heading">Independently preserved attachments ({len(relationships)})</h3><div class="associated-records-list">{"".join(cards)}</div></section>'


def _render_attachment_source_relationships(item: dict) -> str:
    if item.get("document_type") != "email_attachment":
        return ""
    relationships = list_attachment_sources(str(item.get("intake_id") or ""), root=intake_root())
    cards: list[str] = []
    for relationship in relationships:
        source = relationship.get("source_document") or {}
        source_public = source.get("status") == "published"
        source_is_document = relationship.get("source_email_kind") == "published_document"
        source_label = source.get("document_identifier") if source_is_document else "Governed mailbox message"
        source_title = (
            (source.get("email_metadata") or {}).get("subject_decoded")
            or source.get("title")
            or "Source email"
        )
        metadata_rows = _email_attachment_metadata_rows(
            [
                ("Attachment index", relationship.get("attachment_index")),
                ("Original filename", relationship.get("original_filename") or "Not provided"),
                ("Content-ID", relationship.get("content_id") or "Not provided"),
            ]
        )
        actions = ""
        if source_is_document and source_public:
            actions = f'<nav class="association-card__actions" aria-label="Source email actions"><a class="button-link association-card__action association-card__action--primary" href="/documents/{escape(str(source.get("intake_id")))}">Open source email</a><a class="button-link button-link--secondary association-card__action association-card__action--secondary" href="/email-attachment-relationships/{escape(str(relationship.get("relationship_id")))}">View relationship</a></nav>'
        cards.append(
            f'''<article class="association-card email-attachment-source-card" aria-label="Source email"><p class="association-card__label">Source email</p><h3 class="association-card__identifier">{escape(str(source_label or "Governed source"))}</h3><p class="association-card__relationship"><span class="association-card__badge">{escape(EMAIL_ATTACHMENT_RELATIONSHIP_TYPE)}</span></p><div class="association-card__summary"><p class="association-card__summary-label">Transmission context</p><p class="association-card__summary-text">{escape(str(source_title))}</p></div><dl class="association-card__metadata">{metadata_rows}</dl>{actions}</article>'''
        )
    if not cards:
        return ""
    return f'<section class="associated-records email-attachment-sources" aria-labelledby="email-attachment-sources-heading"><h2 id="email-attachment-sources-heading">Attached to email</h2><p class="association-boundary provenance-boundary">The source email and this attachment remain independent preserved objects. The relationship records transmission context only.</p><div class="associated-records-list">{"".join(cards)}</div></section>'


def _render_outlook_archive_document(item: dict) -> str:
    metadata = _outlook_archive_metadata(item)
    rows = "".join(
        f"<tr><th>{escape(label)}</th><td>{escape(_display_value(value))}</td></tr>"
        for label, value in (
            ("Archive type", metadata.get("archive_type_label") or document_type_label(item.get("document_type"))),
            ("Original filename", metadata.get("original_filename") or item.get("original_filename")),
            ("Archive size", f"{item.get('file_size_bytes')} bytes" if item.get("file_size_bytes") is not None else None),
            ("Declared MIME type", metadata.get("declared_mime_type")),
            ("Upload timestamp", metadata.get("upload_timestamp") or item.get("upload_date")),
            ("Uploader", metadata.get("uploader")),
            ("Preservation complete", metadata.get("preservation_complete")),
            ("Preservation timestamp", metadata.get("preservation_timestamp")),
            ("Hash verification status", metadata.get("hash_verification_status")),
            ("Parser contract", metadata.get("parser_contract")),
            ("Parser status", metadata.get("parser_status_message") or metadata.get("parser_status")),
            ("Parser version", metadata.get("parser_version")),
            ("Inspection complete", metadata.get("inspection_complete")),
            ("Inspection timestamp", metadata.get("inspection_timestamp")),
            ("Projection state", metadata.get("projection_state")),
            ("Archive health", metadata.get("archive_health")),
            ("Mailbox projection", "Administrative only in CDE Platform Stage 39C"),
            ("Message body extraction", "Not performed in CDE Platform Stage 39C"),
            ("Canonical record generation", "Not performed in CDE Platform Stage 39C"),
        )
    )
    return f"""<section class="public-outlook-archive-summary"><h2>Outlook Archive Overview</h2><p class="provenance-boundary">{escape(OUTLOOK_ARCHIVE_BOUNDARY)}</p><table>{rows}</table></section>
<section class="public-email-boundary"><h2>Outlook Archive Governance Boundary</h2><p class="provenance-boundary">{escape(OUTLOOK_ARCHIVE_BOUNDARY)}</p></section>"""


def _render_gmail_takeout_document(item: dict) -> str:
    metadata = _gmail_takeout_metadata(item)
    rows = "".join(
        f"<tr><th>{escape(label)}</th><td>{escape(_display_value(value))}</td></tr>"
        for label, value in (
            ("Archive type", metadata.get("archive_type_label")),
            ("Original filename", metadata.get("original_filename") or item.get("original_filename")),
            ("Archive size", f"{item.get('file_size_bytes')} bytes" if item.get("file_size_bytes") is not None else None),
            ("Upload timestamp", metadata.get("upload_timestamp") or item.get("upload_date")),
            ("Preservation complete", metadata.get("preservation_complete")),
            ("Hash verification status", metadata.get("hash_verification_status")),
            ("Parser contract", metadata.get("parser_contract")),
            ("Parser status", metadata.get("parser_status_message") or metadata.get("parser_status")),
            ("Parser version", metadata.get("parser_version")),
            ("Projection state", metadata.get("projection_state")),
        )
    )
    boundary = (
        "The preserved Google Takeout export is authoritative. Labels, threads, messages, "
        "body projections, attachments, extraction metadata, and promotion controls remain "
        "private. This public page exposes archive metadata only and provides no archive or "
        "attachment download."
    )
    return f"""<section class="public-outlook-archive-summary"><h2>Google Takeout Archive Overview</h2><p class="provenance-boundary">{escape(boundary)}</p><table>{rows}</table></section>
<section class="public-email-boundary"><h2>Google Takeout Governance Boundary</h2><p class="provenance-boundary">{escape(boundary)}</p></section>"""


def _render_imap_acquisition_document(item: dict) -> str:
    metadata = _imap_acquisition_metadata(item)
    rows = "".join(
        f"<tr><th>{escape(label)}</th><td>{escape(_display_value(value))}</td></tr>"
        for label, value in (
            ("Archive type", metadata.get("archive_type_label")),
            ("Acquisition timestamp", metadata.get("acquisition_timestamp")),
            ("Acquisition hash", metadata.get("acquisition_hash")),
            ("Preservation complete", metadata.get("preservation_complete")),
            ("Hash verification status", metadata.get("hash_verification_status")),
            ("Parser version", metadata.get("parser_version")),
            ("Projection state", metadata.get("projection_state")),
        )
    )
    boundary = (
        "The preserved IMAP acquisition envelope is authoritative. Server configuration, "
        "folder names, UIDs, messages, body projections, attachments, credentials, and "
        "promotion controls remain private. This public page exposes acquisition metadata "
        "only and provides no archive or attachment download."
    )
    return f"""<section class="public-outlook-archive-summary"><h2>IMAP Acquisition Overview</h2><p class="provenance-boundary">{escape(boundary)}</p><table>{rows}</table></section>
<section class="public-email-boundary"><h2>IMAP Acquisition Governance Boundary</h2><p class="provenance-boundary">{escape(boundary)}</p></section>"""


def _render_canonical_record_creation_state(item: dict) -> str:
    conn = rda.get_db()
    try:
        source_records = rda.source_created_records_for_document(conn, item)
    finally:
        conn.close()

    if not source_records:
        return f"""<section class="public-document-admin-actions" aria-label="Administrative actions"><h2>Administrative Actions</h2><p>This protected administrative action opens the existing authenticated workflow for creating a distinct canonical CDE record from this Published document.</p><a class="admin-action-link" href="/admin/document-intake/{escape(item['intake_id'])}/canonical-record/new">Create canonical record from this document</a></section>"""

    multiple = len(source_records) > 1
    heading = (
        "Multiple Source-Created Canonical Records"
        if multiple
        else "Canonical Record Created"
    )
    notice = (
        "Multiple Canonical Records were created directly from this Published Document. "
        "No record has been changed, and further creation is blocked pending administrative review."
        if multiple
        else "This Published Document has already been used to create a Canonical Record."
    )
    cards: list[str] = []
    for record in source_records:
        reference = str(record.get("reference") or "")
        details = (
            ("Canonical Record reference", reference),
            (
                "Record Type",
                RECORD_TYPE_LABELS.get(
                    str(record.get("record_type") or ""),
                    str(record.get("record_type") or "—"),
                ),
            ),
            ("Title", record.get("record_title")),
            ("Institution", record.get("institution")),
            ("Event date", record.get("event_date")),
            ("Trajectory", record.get("trajectory")),
            ("System state", record.get("system_state")),
        )
        rows = "".join(
            f"<tr><th>{escape(label)}</th><td>{escape(str(value))}</td></tr>"
            for label, value in details
            if str(value or "").strip()
        )
        cards.append(
            '<article class="source-created-record">'
            f"<h3>{escape(reference)}</h3><table>{rows}</table>"
            '<p class="source-record-actions">'
            f'<a class="admin-action-link" href="/verify/{escape(reference)}">Open Canonical Record</a>'
            "</p></article>"
        )
    return (
        '<section class="public-document-admin-actions source-created-records" '
        f'aria-label="Administrative actions"><h2>{escape(heading)}</h2>'
        f'<p class="source-record-state">{escape(notice)}</p>{"".join(cards)}</section>'
    )


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
    if item.get("sha512_hash"):
        fields.insert(-2, ("SHA-512", item.get("sha512_hash")))
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
    elif is_outlook_archive_document(item):
        download_label = f"Download original .{escape(str(item.get('document_type') or '').lower())}"
        content_block = f"""<section id="document-content">{_render_outlook_archive_document(item)}<a class="download" href="/documents/{escape(item['intake_id'])}/download">{download_label}</a></section>"""
    elif is_gmail_takeout_document(item):
        content_block = f"""<section id="document-content">{_render_gmail_takeout_document(item)}</section>"""
    elif is_imap_acquisition_document(item):
        content_block = f"""<section id="document-content">{_render_imap_acquisition_document(item)}</section>"""
    elif is_email_document(item):
        download_label = "Download original .msg" if document_type_label(item.get("document_type")) == "Microsoft Outlook Message" else "Download original .emlx" if document_type_label(item.get("document_type")) == "Apple Mail Message" else "Download original .eml"
        content_block = f"""<section id="document-content">{_render_email_document(item)}<a class="download" href="/documents/{escape(item['intake_id'])}/download">{download_label}</a></section>"""
    elif item.get("document_type") == "email_attachment":
        content_block = f"""<section id="document-content"><h2>Preserved Email Attachment</h2><p class="provenance-boundary">This Published Document preserves the exact attachment byte stream extracted from its source email. The Email attachment relationship records transmission context and does not create a Canonical Record or semantic evidential classification.</p><a class="download" href="/documents/{escape(item['intake_id'])}/download">Download original attachment</a></section>"""
    else:
        content_block = f"""<section id="document-content"><a class="download" href="/documents/{escape(item['intake_id'])}/download">Download PDF</a></section>"""
    associated_records_section = _render_associated_records(item)
    attachment_sources_section = _render_attachment_source_relationships(item)
    provenance_section = _render_publication_provenance(item)
    pathway_section = _render_publication_pathway(item)
    admin_actions = _render_canonical_record_creation_state(item)
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>{escape(item['title'])}</title>
<style>{ASSOCIATION_CARD_STYLES}</style>
<style>*{{box-sizing:border-box}}body{{margin:0;background:#f7f7f4;color:#1f2933;font-family:system-ui,sans-serif}}main{{width:min(960px,calc(100% - 32px));margin:32px auto 64px}}h1,h2{{color:#143a52}}a{{color:#245d61}}{PUBLIC_NAVIGATION_CSS}.governance,.provenance-boundary{{padding:14px;border-left:4px solid #2e8b9a;background:#fff}}table{{width:100%;border-collapse:collapse;background:#fff}}th,td{{padding:10px;border:1px solid #e1dfd8;text-align:left;vertical-align:top;overflow-wrap:anywhere}}th{{width:210px;background:#faf9f5;color:#555}}.public-document-image-wrap,.public-audio-wrap,.public-spreadsheet-summary,.public-rich-text-summary,.public-email-summary,.public-email-apple-metadata,.public-email-body,.public-email-attachments,.public-email-boundary,.public-outlook-archive-summary,.public-mbox-summary,.public-mbox-index,.public-mbox-message-detail,.public-mbox-relationship-graph,.public-mbox-placeholder{{background:#fff;border:1px solid #e1dfd8;padding:12px;margin:18px 0}}.public-spreadsheet-summary table{{margin-top:12px}}.public-document-image{{display:block;max-width:100%;width:auto;height:auto}}.public-document-audio{{display:block;width:100%;max-width:720px}}.email-plain-text{{white-space:pre-wrap;overflow-wrap:break-word;margin:0;padding:12px;background:#faf9f5;border:1px solid #e1dfd8;font:0.95rem/1.5 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}}.email-html-details{{margin-top:14px}}.email-html-view{{padding:12px;margin-top:8px;background:#faf9f5;border:1px solid #e1dfd8;overflow-wrap:break-word}}.email-attachments-wrapper{{overflow-x:auto}}.email-attachments-wrapper table{{min-width:860px}}.public-mbox-message-index{{min-width:980px;table-layout:auto}}.public-mbox-message-index th,.public-mbox-message-index td{{overflow-wrap:normal;word-break:normal}}.mbox-index-cell,.mbox-date-cell,.mbox-attachment-cell,.mbox-status-cell,.mbox-warning-cell{{white-space:nowrap}}.mbox-subject-cell,.mbox-from-cell,.mbox-to-cell{{overflow-wrap:break-word}}.mailbox-tabs{{display:flex;gap:8px;flex-wrap:wrap;margin:18px 0}}.mailbox-tabs a{{padding:8px 10px;border:1px solid #d8d2c4;background:#fff;text-decoration:none}}.mailbox-graph-theme-toggle{{display:flex;gap:12px;flex-wrap:wrap;align-items:center;margin:12px 0;padding:10px;border:1px solid #d8d2c4;background:#faf9f5}}.mailbox-graph-theme-toggle legend{{font-weight:800;color:#143a52}}.mailbox-graph-theme-toggle label{{display:flex;gap:6px;align-items:center}}.mailbox-graph-filters{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:12px 0}}.mailbox-graph-filters label{{display:grid;gap:4px;font-weight:700;color:#555}}.mailbox-graph-filters input{{width:100%;padding:8px;border:1px solid #c9c2b5;background:#fff;color:#1f2933}}.mailbox-graph-filters button{{padding:9px 10px;border:0;background:#245d61;color:#fff;align-self:end}}.mailbox-graph-cluster-toggle{{align-self:end;display:flex!important;gap:7px;align-items:center;padding:8px;border:1px solid #d8d2c4;background:#faf9f5}}.mailbox-graph-workspace{{display:grid;grid-template-columns:minmax(0,1fr) minmax(240px,.34fr);gap:12px;align-items:stretch}}.mailbox-graph-shell{{height:560px;overflow:hidden;border:1px solid #d8d2c4;background:#faf9f5}}.mailbox-graph-info-panel{{min-height:560px;padding:12px;border:1px solid #d8d2c4;background:#faf9f5;overflow:auto}}.mailbox-graph-info-panel h3{{margin-top:0}}.mailbox-graph-info-panel dl{{display:grid;grid-template-columns:115px minmax(0,1fr);gap:6px 10px}}.mailbox-graph-info-panel dt{{font-weight:800;color:#555}}.mailbox-graph-info-panel dd{{margin:0;overflow-wrap:anywhere}}.mailbox-graph-actions{{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px}}.mailbox-graph-action{{padding:7px 9px;border:1px solid #245d61;background:#fff;color:#245d61;text-decoration:none;font:inherit;cursor:pointer}}.mailbox-graph-legend{{display:flex;flex-wrap:wrap;gap:8px 14px;margin:12px 0;color:#555}}.mailbox-graph-legend span{{display:inline-flex;align-items:center;gap:5px}}.legend-icon{{display:inline-flex;align-items:center;justify-content:center;width:18px;height:18px;border-radius:50%;font-size:.72rem;color:#fff}}.legend-person{{background:#0F766E}}.legend-institution{{background:#7C3AED}}.legend-email{{background:#475569}}.legend-case{{background:#B45309}}.legend-reference{{background:#2563EB}}.legend-attachment{{background:#16A34A}}.legend-intake{{background:#DC2626}}.mailbox-relationship-graph-canvas{{display:block;width:100%;height:100%;touch-action:none}}.mailbox-relationship-graph-canvas text{{font:12px system-ui,sans-serif;fill:#1f2933;paint-order:stroke;stroke:#faf9f5;stroke-width:3px;stroke-linejoin:round}}.mailbox-graph-label{{transition:opacity .18s ease}}.mailbox-graph-node:focus circle{{stroke:#111827;stroke-width:3px}}.mailbox-graph-hover-glow{{filter:drop-shadow(0 0 7px rgba(45,212,191,.65))}}.mailbox-graph-node-icon{{font-size:10px;fill:#fff;stroke:none;pointer-events:none}}.mailbox-graph-edge{{transition:opacity .16s ease,stroke-width .16s ease}}.public-mbox-relationship-graph[data-graph-theme="high-contrast"]{{background:#111827;border-color:#334155;color:#E5E7EB}}.public-mbox-relationship-graph[data-graph-theme="high-contrast"] .provenance-boundary,.public-mbox-relationship-graph[data-graph-theme="high-contrast"] .mailbox-graph-info-panel,.public-mbox-relationship-graph[data-graph-theme="high-contrast"] .mailbox-graph-theme-toggle,.public-mbox-relationship-graph[data-graph-theme="high-contrast"] .mailbox-graph-cluster-toggle{{background:#111827;border-color:#334155;color:#94A3B8}}.public-mbox-relationship-graph[data-graph-theme="high-contrast"] .mailbox-graph-shell{{background:#0F172A;border-color:#334155}}.public-mbox-relationship-graph[data-graph-theme="high-contrast"] h2,.public-mbox-relationship-graph[data-graph-theme="high-contrast"] h3,.public-mbox-relationship-graph[data-graph-theme="high-contrast"] legend,.public-mbox-relationship-graph[data-graph-theme="high-contrast"] dt{{color:#E5E7EB}}.public-mbox-relationship-graph[data-graph-theme="high-contrast"] .mailbox-relationship-graph-canvas text{{fill:#E5E7EB;stroke:#0F172A}}.public-mbox-relationship-graph[data-graph-theme="high-contrast"] .mailbox-graph-filters input{{background:#0F172A;border-color:#334155;color:#E5E7EB}}.download{{display:inline-block;margin:18px 0;padding:10px 14px;background:#245d61;color:#fff;text-decoration:none}}.public-document-admin-actions{{margin:24px 0;padding:14px 16px;border-left:4px solid #143a52;background:#fff}}.public-document-admin-actions h2{{margin-top:0;font-size:1.05rem}}.public-document-admin-actions p{{color:#555;line-height:1.5}}.admin-action-link{{display:inline-block;padding:9px 12px;background:#245d61;color:#fff;text-decoration:none}}.publication-provenance{{--publication-provenance-recorded-value:#245d61;--publication-provenance-empty-value:#6B7280;margin-top:28px}}.publication-provenance-grid{{display:grid;grid-template-columns:minmax(190px,0.42fr) minmax(0,1fr);background:#fff;border:1px solid #e1dfd8}}.publication-provenance-row{{display:contents}}.publication-provenance-label,.publication-provenance-value{{padding:10px;border-bottom:1px solid #e1dfd8;overflow-wrap:anywhere}}.publication-provenance-label{{font-weight:700;color:#555;background:#faf9f5}}.publication-provenance-value{{min-width:0;color:var(--publication-provenance-recorded-value);font-weight:600}}.publication-provenance-value--empty{{color:var(--publication-provenance-empty-value);font-weight:400}}.publication-provenance-value--technical{{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}}.publication-pathway-wrapper{{overflow-x:auto}}.publication-pathway-table{{min-width:820px;table-layout:auto}}.publication-pathway-timestamp{{min-width:180px;white-space:nowrap}}.publication-pathway-previous-status,.publication-pathway-new-status{{min-width:145px;overflow-wrap:normal}}.publication-pathway-actor{{min-width:120px;overflow-wrap:anywhere}}.publication-pathway-note{{min-width:260px;width:100%}}.associated-records,.associated-documents{{margin-top:28px}}.association-boundary{{padding:14px;border-left:4px solid #2e8b9a;background:#fff}}.associated-records-list,.associated-documents-list{{display:grid;gap:12px}}.associated-record-card,.associated-document-card{{background:#fff;border:1px solid #e1dfd8;padding:14px;overflow-wrap:anywhere}}.associated-record-card h3,.associated-document-card h3{{margin:0 0 8px}}.associated-record-card dl,.associated-document-card dl{{display:grid;grid-template-columns:150px minmax(0,1fr);gap:6px 12px;margin:10px 0 0}}.associated-record-card dt,.associated-document-card dt{{font-weight:700;color:#555}}.associated-record-card dd,.associated-document-card dd{{margin:0}}@media(max-width:720px){{.publication-provenance-grid{{grid-template-columns:1fr}}.publication-provenance-label,.publication-provenance-value{{display:block}}.publication-pathway-table{{min-width:760px}}.mailbox-graph-workspace{{grid-template-columns:1fr}}.mailbox-graph-shell{{height:420px}}.mailbox-graph-info-panel{{min-height:auto}}}}@media(prefers-color-scheme:dark){{body{{background:#111827;color:#E5E7EB}}h1,h2{{color:#8DD5DD}}.governance,.provenance-boundary,.public-document-image-wrap,.public-audio-wrap,.public-spreadsheet-summary,.public-rich-text-summary,.public-email-summary,.public-email-apple-metadata,.public-email-body,.public-email-attachments,.public-email-boundary,.public-outlook-archive-summary,.public-mbox-summary,.public-mbox-index,.public-mbox-message-detail,.public-mbox-relationship-graph,.public-mbox-placeholder,.mailbox-tabs a{{background:#1F2937;border-color:#374151}}table{{background:#1F2937}}th{{background:#111827;color:#D1D5DB}}th,td{{border-color:#374151}}.publication-provenance{{--publication-provenance-recorded-value:#8DD5DD;--publication-provenance-empty-value:#94A3B8}}.publication-provenance-grid{{background:#1F2937;border-color:#374151}}.publication-provenance-label{{background:#111827;color:#D1D5DB}}.publication-provenance-label,.publication-provenance-value{{border-color:#374151}}.mailbox-graph-shell,.email-plain-text,.email-html-view{{background:#111827;border-color:#374151}}.mailbox-relationship-graph-canvas text{{fill:#F9FAFB;stroke:#111827}}.mailbox-graph-filters input{{background:#111827;color:#F9FAFB;border-color:#4B5563}}}}</style></head>
<body><main>{public_primary_navigation(active="documents")}{public_breadcrumbs([("Home", "/"), ("Archive", archive_return), ("Published Documents", "/archive?type=published_document"), (str(item["title"]), None)])}{archive_back_link(archive_return)}<p>{object_type_badge("published_document")}</p><h1>{escape(item['title'])}</h1><p class="governance">{escape(GOVERNANCE_STATEMENT)}</p><nav aria-label="Document sections"><a href="#document-metadata">Document metadata</a> · <a href="#publication-provenance">Publication provenance</a> · <a href="#publication-pathway">Publication pathway</a> · <a href="#document-content">Document content</a></nav>{admin_actions}<section id="document-metadata"><h2>Document Metadata</h2><table>{rows}</table></section>{content_block}{attachment_sources_section}{associated_records_section}{provenance_section}{pathway_section}</main></body></html>"""


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


@router.get("/api/mailbox/graph")
def mailbox_relationship_graph(
    document: str | None = Query(None),
    institution: str | None = Query(None),
    person: str | None = Query(None),
    case_: str | None = Query(None, alias="case"),
    reference: str | None = Query(None),
    from_: str | None = Query(None, alias="from"),
    to: str | None = Query(None),
    status: str | None = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(1000, ge=1, le=5000),
):
    documents = list_published_documents(root=intake_root())
    return build_mailbox_relationship_graph(
        documents,
        filters=MailboxGraphFilters(
            document=document,
            institution=institution,
            person=person,
            case=case_,
            reference=reference,
            date_from=from_,
            date_to=to,
            status=status,
            offset=offset,
            limit=limit,
        ),
    )


@router.get("/documents/{document_id}", response_class=HTMLResponse)
def public_document_page(document_id: str, return_to: str | None = None, message: str | None = Query(None), page: str | None = Query(None)):
    try:
        item = load_published_document(document_id, root=intake_root())
    except ValueError as exc:
        _not_found(exc)
    return HTMLResponse(content=_render_document(item, return_to=return_to, message=message, page=page))


@router.get("/email-attachment-relationships/{relationship_id}", response_class=HTMLResponse)
def public_email_attachment_relationship_page(relationship_id: str):
    try:
        relationship = get_email_attachment_relationship(relationship_id, root=intake_root())
        attachment = load_published_document(
            str(relationship.get("attachment_document_id") or ""), root=intake_root()
        )
        if relationship.get("source_email_kind") != "published_document":
            raise ValueError("public_email_attachment_relationship_not_found")
        source = load_published_document(
            str(relationship.get("source_email_document_id") or ""), root=intake_root()
        )
    except ValueError as exc:
        _not_found(exc)
    rows = "".join(
        f"<tr><th>{escape(label)}</th><td>{escape(_display_value(value))}</td></tr>"
        for label, value in (
            ("Relationship type", relationship.get("relationship_type")),
            ("Source email", source.get("document_identifier")),
            ("Attachment document", attachment.get("document_identifier")),
            ("Attachment index", relationship.get("attachment_index")),
            ("Original filename", relationship.get("original_filename")),
            ("MIME type", relationship.get("mime_type")),
            ("File size", _format_file_size(relationship.get("file_size_bytes"))),
            ("Preservation timestamp", relationship.get("created_at")),
        )
    )
    return HTMLResponse(content=f'''<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Email attachment relationship</title><style>*{{box-sizing:border-box}}body{{margin:0;background:#f7f7f4;color:#1f2933;font-family:system-ui,sans-serif}}main{{width:min(900px,calc(100% - 32px));margin:32px auto 64px}}h1{{color:#143a52}}a{{color:#245d61}}table{{width:100%;border-collapse:collapse;background:#fff}}th,td{{padding:10px;border:1px solid #e1dfd8;text-align:left;vertical-align:top;overflow-wrap:anywhere}}th{{width:220px;background:#faf9f5;color:#555}}.notice{{padding:14px;border-left:4px solid #2e8b9a;background:#fff}}.actions{{display:flex;flex-wrap:wrap;gap:10px;margin-top:18px}}.actions a{{padding:9px 12px;background:#245d61;color:#fff;text-decoration:none}}</style></head><body><main>{public_primary_navigation(active="documents")}<h1>Email attachment relationship</h1><p class="notice">This governed relationship records that an independent Published Document was transmitted with an independent source email. It does not create a Canonical Record or assign an evidential role.</p><table>{rows}</table><nav class="actions" aria-label="Relationship actions"><a href="/documents/{escape(str(source.get('intake_id')))}">Open source email</a><a href="/documents/{escape(str(attachment.get('intake_id')))}">Open attachment Published Document</a></nav></main></body></html>''')


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
    if is_gmail_takeout_document(item) or is_imap_acquisition_document(item):
        raise HTTPException(status_code=404, detail="public_document_download_not_available")
    headers = None
    if is_image_document(item) or is_audio_document(item) or is_spreadsheet_document(item) or is_rich_text_document(item) or is_email_document(item) or is_mailbox_document(item) or is_outlook_archive_document(item):
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
