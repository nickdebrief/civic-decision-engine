from __future__ import annotations

from html import escape
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse

from api import record_document_associations as rda
from api.document_intake import (
    STATUS_LABELS,
    document_media_type,
    document_type_label,
    intake_root,
    is_image_document,
    list_published_documents,
    load_published_document,
    published_document_file,
)


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
          <td>{escape(str(item.get('reference_identifier') or '—'))}</td>
        </tr>"""
        for item in documents
    ) or '<tr><td colspan="6">No published documents match these criteria.</td></tr>'
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
<style>*{{box-sizing:border-box}}body{{margin:0;background:#f7f7f4;color:#1f2933;font-family:system-ui,sans-serif}}main{{width:min(1180px,calc(100% - 32px));margin:32px auto 64px}}h1{{color:#143a52}}.governance{{max-width:900px;padding:16px;border-left:4px solid #2e8b9a;background:#fff}}form{{display:grid;grid-template-columns:2fr repeat(3,1fr) auto;gap:10px;margin:24px 0}}input,select,button{{min-width:0;padding:9px;border:1px solid #c9c6bd;background:#fff;font:inherit}}button{{border-color:#245d61;background:#245d61;color:#fff;cursor:pointer}}.table-wrap{{overflow-x:auto}}table{{width:100%;border-collapse:collapse;background:#fff;font-size:.9rem}}th{{background:#143a52;color:#fff;text-align:left}}th,td{{padding:10px;border:1px solid #e1dfd8;vertical-align:top;white-space:normal;overflow-wrap:break-word}}a{{color:#245d61}}.result-count{{color:#555}}@media(max-width:800px){{form{{grid-template-columns:1fr}}table{{min-width:900px}}}}</style></head>
<body><main><h1>Public Document Library</h1><p class="governance">{escape(GOVERNANCE_STATEMENT)}</p>
<form method="get" action="/documents"><input name="q" value="{escape(str(query or ''))}" placeholder="Search title, institution, category, or reference" aria-label="Search documents"><select name="institution" aria-label="Filter by institution"><option value="">All institutions</option>{options(institutions, institution)}</select><select name="category" aria-label="Filter by category"><option value="">All categories</option>{options(categories, category)}</select><select name="publication_year" aria-label="Filter by publication year"><option value="">All publication years</option>{options(years, publication_year)}</select><button type="submit">Search</button></form>
<p class="result-count">{len(documents)} published document{"s" if len(documents) != 1 else ""}.{f' Active query: {escape(active_query)}' if active_query else ''}</p><div class="table-wrap"><table><thead><tr><th>Title</th><th>Institution / Source</th><th>Category</th><th>Publication Date</th><th>Description</th><th>Reference Identifier</th></tr></thead><tbody>{rows}</tbody></table></div></main></body></html>"""


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
    return "Downloadable PDF"


def _original_download_availability(item: dict) -> str:
    if is_image_document(item):
        return "Original image download available"
    return "Original PDF download available"


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
    provenance_fields = (
        ("Intake date and time", item.get("upload_date")),
        ("Document date", item.get("document_date")),
        ("Server-detected document format", document_type_label(item.get("document_type"))),
        ("Original filename", item.get("original_filename")),
        ("File size", f"{item.get('file_size_bytes')} bytes" if item.get("file_size_bytes") is not None else None),
        ("SHA-256 digest", item.get("sha256_hash")),
        ("Initial intake actor", initial_event.get("actor") if initial_event else None),
        ("Review actor", review_event.get("actor") if review_event else None),
        ("Approval actor", approval_event.get("actor") if approval_event else None),
        ("Publication actor", publication_event.get("actor") if publication_event else None),
        ("Review timestamp", review_event.get("timestamp") if review_event else None),
        ("Approval timestamp", approval_event.get("timestamp") if approval_event else None),
        ("Publication timestamp", _publication_timestamp(item)),
        ("Current lifecycle state", STATUS_LABELS.get(str(item.get("status") or ""), item.get("status"))),
        ("Public reference identifier", item.get("reference_identifier")),
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

def _render_document(item: dict) -> str:
    publication_timestamp = _publication_timestamp(item)
    fields = (
        ("Title", item["title"]),
        ("Description", item["description"]),
        ("Institution / Source", item["institution_source"]),
        ("Category", item["category"]),
        ("Publication Date", _date(publication_timestamp or item.get("publication_date"))),
        ("Document Date", item["document_date"]),
        ("Document Format", document_type_label(item.get("document_type"))),
        ("SHA-256", item["sha256_hash"]),
        ("Reference Identifier", item.get("reference_identifier") or "Not provided"),
    )
    rows = "".join(
        f"<tr><th>{escape(label)}</th><td>{escape(str(value))}</td></tr>"
        for label, value in fields
    )
    image_block = (
        f"""<section id="document-content"><h2>Document Image</h2><div class="public-document-image-wrap"><img class="public-document-image" src="/documents/{escape(item['intake_id'])}/view" alt="{escape(str(item['title']))}"></div><a class="download" href="/documents/{escape(item['intake_id'])}/view">View image</a> <a class="download" href="/documents/{escape(item['intake_id'])}/download">Download original image</a></section>"""
        if is_image_document(item)
        else f"""<section id="document-content"><a class="download" href="/documents/{escape(item['intake_id'])}/download">Download PDF</a></section>"""
    )
    associated_records_section = _render_associated_records(item)
    provenance_section = _render_publication_provenance(item)
    pathway_section = _render_publication_pathway(item)
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>{escape(item['title'])}</title>
<style>*{{box-sizing:border-box}}body{{margin:0;background:#f7f7f4;color:#1f2933;font-family:system-ui,sans-serif}}main{{width:min(960px,calc(100% - 32px));margin:32px auto 64px}}h1,h2{{color:#143a52}}a{{color:#245d61}}.governance,.provenance-boundary{{padding:14px;border-left:4px solid #2e8b9a;background:#fff}}table{{width:100%;border-collapse:collapse;background:#fff}}th,td{{padding:10px;border:1px solid #e1dfd8;text-align:left;vertical-align:top;overflow-wrap:anywhere}}th{{width:210px;background:#faf9f5;color:#555}}.public-document-image-wrap{{background:#fff;border:1px solid #e1dfd8;padding:12px;margin:18px 0}}.public-document-image{{display:block;max-width:100%;width:auto;height:auto}}.download{{display:inline-block;margin:18px 0;padding:10px 14px;background:#245d61;color:#fff;text-decoration:none}}.publication-provenance{{margin-top:28px}}.publication-provenance-grid{{display:grid;grid-template-columns:minmax(190px,0.42fr) minmax(0,1fr);background:#fff;border:1px solid #e1dfd8}}.publication-provenance-row{{display:contents}}.publication-provenance-label,.publication-provenance-value{{padding:10px;border-bottom:1px solid #e1dfd8;overflow-wrap:anywhere}}.publication-provenance-label{{font-weight:700;color:#555;background:#faf9f5}}.publication-provenance-value{{min-width:0}}.publication-pathway-wrapper{{overflow-x:auto}}.publication-pathway-table{{min-width:820px;table-layout:auto}}.publication-pathway-timestamp{{min-width:180px;white-space:nowrap}}.publication-pathway-previous-status,.publication-pathway-new-status{{min-width:145px;overflow-wrap:normal}}.publication-pathway-actor{{min-width:120px;overflow-wrap:anywhere}}.publication-pathway-note{{min-width:260px;width:100%}}.associated-records,.associated-documents{{margin-top:28px}}.association-boundary{{padding:14px;border-left:4px solid #2e8b9a;background:#fff}}.associated-records-list,.associated-documents-list{{display:grid;gap:12px}}.associated-record-card,.associated-document-card{{background:#fff;border:1px solid #e1dfd8;padding:14px;overflow-wrap:anywhere}}.associated-record-card h3,.associated-document-card h3{{margin:0 0 8px}}.associated-record-card dl,.associated-document-card dl{{display:grid;grid-template-columns:150px minmax(0,1fr);gap:6px 12px;margin:10px 0 0}}.associated-record-card dt,.associated-document-card dt{{font-weight:700;color:#555}}.associated-record-card dd,.associated-document-card dd{{margin:0}}@media(max-width:720px){{.publication-provenance-grid{{grid-template-columns:1fr}}.publication-provenance-label,.publication-provenance-value{{display:block}}.publication-pathway-table{{min-width:760px}}}}</style></head>
<body><main><p><a href="/documents">Back to Public Document Library</a></p><h1>{escape(item['title'])}</h1><p class="governance">{escape(GOVERNANCE_STATEMENT)}</p><nav aria-label="Document sections"><a href="#document-metadata">Document metadata</a> · <a href="#publication-provenance">Publication provenance</a> · <a href="#publication-pathway">Publication pathway</a> · <a href="#document-content">Document content</a></nav><section id="document-metadata"><h2>Document Metadata</h2><table>{rows}</table></section>{image_block}{associated_records_section}{provenance_section}{pathway_section}</main></body></html>"""


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
def public_document_page(document_id: str):
    try:
        item = load_published_document(document_id, root=intake_root())
    except ValueError as exc:
        _not_found(exc)
    return HTMLResponse(content=_render_document(item))


def _content_disposition(disposition: str, filename: str) -> str:
    safe_filename = str(filename or "document").replace("\\", "_").replace('"', "")
    safe_filename = Path(safe_filename).name
    return f'{disposition}; filename="{safe_filename}"'


@router.get("/documents/{document_id}/view")
def public_document_image_view(document_id: str):
    try:
        file_path, item = published_document_file(document_id, root=intake_root())
        if not is_image_document(item):
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
            )
        },
    )


@router.get("/documents/{document_id}/download")
def public_document_download(document_id: str):
    try:
        file_path, item = published_document_file(document_id, root=intake_root())
    except ValueError as exc:
        _not_found(exc)
    headers = None
    if is_image_document(item):
        headers = {
            "Content-Disposition": _content_disposition(
                "attachment",
                item["original_filename"],
            )
        }
    return FileResponse(
        path=Path(file_path),
        media_type=document_media_type(item),
        filename=item["original_filename"],
        headers=headers,
    )
