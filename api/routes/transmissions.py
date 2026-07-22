from __future__ import annotations

from html import escape
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

from api import public_transmissions as trm
from api.document_intake import intake_root
from api.public_navigation import (
    PUBLIC_NAVIGATION_CSS,
    archive_back_link,
    object_type_badge,
    public_breadcrumbs,
    public_primary_navigation,
    sanitize_archive_return,
)

router = APIRouter()

BOUNDARY_TEXT = (
    "Documents preserve content. Transmissions preserve context. A Transmission "
    "governs communication; it does not govern, duplicate, absorb, or alter the "
    "objects communicated."
)


def _display(value: object) -> str:
    if value is None or value == "":
        return "—"
    return str(value)


def _date(value: object) -> str:
    text = _display(value)
    return text.split("T", 1)[0] if text != "—" else text


def _query_string(filters: dict[str, str], *, page: int | None = None, page_size: int | None = None) -> str:
    params = {key: value for key, value in filters.items() if value}
    if page is not None:
        params["page"] = str(page)
    if page_size is not None:
        params["page_size"] = str(page_size)
    return urlencode(params)


def _option_list(options: dict[str, str] | list[str], selected: str, blank_label: str) -> str:
    rendered = [f'<option value="">{escape(blank_label)}</option>']
    iterable = options.items() if isinstance(options, dict) else ((value, value) for value in options)
    for value, label in iterable:
        rendered.append(
            f'<option value="{escape(str(value))}"{" selected" if selected == value else ""}>{escape(str(label))}</option>'
        )
    return "".join(rendered)


def _page_size_options(selected: int) -> str:
    return "".join(
        f'<option value="{size}"{" selected" if selected == size else ""}>{size}</option>'
        for size in trm.PUBLIC_TRANSMISSION_PAGE_SIZE_OPTIONS
    )


def _active_filter_summary(filters: dict[str, str]) -> str:
    labels = (
        ("q", "Search"),
        ("sender", "Sender"),
        ("recipient", "Recipient"),
        ("method", "Communication method"),
        ("year", "Publication year"),
    )
    active = []
    for key, label in labels:
        value = filters.get(key)
        if not value:
            continue
        display = trm.method_label(value) if key == "method" else value
        active.append(f"{label}: {display}")
    return "; ".join(active) if active else "None"


def _render_index_rows(rows: list[dict]) -> str:
    rendered = []
    for item in rows:
        reference = str(item.get("public_reference") or "")
        rendered.append(
            f"""<tr>
              <td class="transmission-reference"><a href="/transmissions/{escape(reference)}">{escape(reference)}</a></td>
              <td class="transmission-title"><strong>{escape(_display(item.get('title')))}</strong><p>{escape(_display(item.get('summary')))}</p></td>
              <td class="transmission-sender">{escape(_display(item.get('sender')))}</td>
              <td class="transmission-recipient">{escape(_display(item.get('recipient')))}</td>
              <td class="transmission-method">{escape(_display(item.get('communication_method_label')))}</td>
              <td class="transmission-publication">{escape(_date(item.get('published_at') or item.get('transmission_date')))}</td>
              <td class="transmission-count">{int(item.get('attached_object_count') or 0)}</td>
              <td class="transmission-actions"><a href="/transmissions/{escape(reference)}">Open Transmission</a></td>
            </tr>"""
        )
    return "".join(rendered)


@router.get("/transmissions", response_class=HTMLResponse)
def public_transmission_library(
    q: str | None = None,
    sender: str | None = None,
    recipient: str | None = None,
    method: str | None = None,
    year: str | None = None,
    page: int | str | None = 1,
    page_size: int | str | None = 25,
):
    conn = trm.get_db()
    try:
        result = trm.list_public_transmission_index(
            conn,
            q=q,
            sender=sender,
            recipient=recipient,
            method=method,
            year=year,
            page=page,
            page_size=page_size,
            root=intake_root(),
        )
    finally:
        conn.close()
    filters = result["filters"]
    rows_html = _render_index_rows(result["rows"])
    if rows_html:
        body_rows = rows_html
    elif _active_filter_summary(filters) == "None":
        body_rows = '<tr><td class="transmission-empty" colspan="8">No eligible Public Transmissions are currently listed.</td></tr>'
    else:
        body_rows = '<tr><td class="transmission-empty" colspan="8">No Public Transmissions match the selected filters.</td></tr>'
    previous_link = ""
    next_link = ""
    if result["page"] > 1:
        previous_link = f'<a href="/transmissions?{escape(_query_string(filters, page=result["page"] - 1, page_size=result["page_size"]))}">Previous page</a>'
    if result["page"] < result["page_count"]:
        next_link = f'<a href="/transmissions?{escape(_query_string(filters, page=result["page"] + 1, page_size=result["page_size"]))}">Next page</a>'
    options = result["options"]
    method_options = {
        value: trm.method_label(value)
        for value in options["methods"]
    }
    return HTMLResponse(content=f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Public Transmission Library | Civic Decision Engine</title><link rel="canonical" href="/transmissions"><meta name="description" content="Public index of governed communication-context transmissions in the Civic Decision Engine."><style>*{{box-sizing:border-box}}body{{margin:0;background:#f7f7f4;color:#1f2933;font-family:system-ui,sans-serif}}main{{width:min(1180px,calc(100% - 32px));margin:32px auto 64px}}h1,h2{{color:#143a52}}a{{color:#245d61}}{PUBLIC_NAVIGATION_CSS}.transmission-boundary,.transmission-summary{{padding:14px 16px;border-left:4px solid #2e8b9a;background:#fff;line-height:1.55}}.transmission-summary{{margin:18px 0;border-left-color:#143a52}}.transmission-filters{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;background:#fff;border:1px solid #d8d4ca;padding:16px;margin:22px 0}}.transmission-filters label{{display:grid;gap:6px;color:#555;font:.78rem ui-monospace,monospace;text-transform:uppercase}}.transmission-filters input,.transmission-filters select{{width:100%;padding:9px;border:1px solid #c9c6bd;background:#fff;font:.92rem system-ui,sans-serif}}.transmission-filters button,.transmission-filters a{{width:max-content;padding:9px 12px;border:0;background:#245d61;color:#fff;cursor:pointer;text-decoration:none;display:inline-block}}.transmission-results{{overflow-x:auto}}.transmission-table{{width:100%;min-width:1040px;border-collapse:collapse;background:#fff;font-size:.9rem;table-layout:auto}}.transmission-table th{{background:#143a52;color:#fff;text-align:left}}.transmission-table th,.transmission-table td{{padding:10px;border:1px solid #e1dfd8;vertical-align:top;overflow-wrap:anywhere}}.transmission-reference{{min-width:140px;font-family:ui-monospace,monospace}}.transmission-title{{min-width:260px}}.transmission-sender,.transmission-recipient{{min-width:170px}}.transmission-count,.transmission-method{{white-space:nowrap}}.transmission-empty{{text-align:center;color:#555;padding:18px}}.transmission-pagination{{display:flex;gap:16px;align-items:center;flex-wrap:wrap;margin:18px 0}}@media(max-width:760px){{.transmission-filters{{grid-template-columns:1fr}}}}</style></head><body><main>{public_primary_navigation(active="transmissions")}{public_breadcrumbs([("Home", "/"), ("Archive", "/archive"), ("Transmissions", None)])}<h1>Public Transmission Library</h1><p>{object_type_badge("public_transmission")}</p><p class="transmission-boundary">{escape(BOUNDARY_TEXT)} This library shows only Published transmissions that are public.</p><section class="transmission-summary"><p><strong>Total matching Public Transmissions:</strong> {int(result['total'])}</p><p><strong>Active filters:</strong> {escape(_active_filter_summary(filters))}</p><p><strong>Page:</strong> {int(result['page'])} of {int(result['page_count'])}</p></section><form class="transmission-filters" method="get" action="/transmissions"><label>Search<input name="q" value="{escape(str(filters['q']))}" placeholder="Reference, sender, recipient, subject, title, or included object reference"></label><label>Sender<select name="sender">{_option_list(options['senders'], str(filters['sender']), 'Any sender')}</select></label><label>Recipient<select name="recipient">{_option_list(options['recipients'], str(filters['recipient']), 'Any recipient')}</select></label><label>Communication method<select name="method">{_option_list(method_options, str(filters['method']), 'Any method')}</select></label><label>Publication year<select name="year">{_option_list(options['years'], str(filters['year']), 'Any year')}</select></label><label>Page size<select name="page_size">{_page_size_options(int(result['page_size']))}</select></label><button type="submit">Apply filters</button><a href="/transmissions">Clear filters</a></form><div class="transmission-pagination"><span>Page {int(result['page'])} of {int(result['page_count'])}</span>{previous_link}{next_link}</div><div class="transmission-results"><table class="transmission-table"><thead><tr><th>Reference</th><th>Title and summary</th><th>Sender</th><th>Recipient</th><th>Method</th><th>Publication</th><th>Included governed objects</th><th>Actions</th></tr></thead><tbody>{body_rows}</tbody></table></div><div class="transmission-pagination"><span>Page {int(result['page'])} of {int(result['page_count'])}</span>{previous_link}{next_link}</div></main></body></html>""")


def _render_attachments(attachments: list[dict]) -> str:
    rows = "".join(
        f"""<tr>
          <td class="transmission-attachment-position">{escape(_display(item.get('position')))}</td>
          <td class="transmission-attachment-reference">{escape(_display(item.get('attachment_reference')))}</td>
          <td class="transmission-attachment-type">{object_type_badge(str(item.get('object_type') or ''))}</td>
          <td class="transmission-attachment-object"><a href="{escape(str(item.get('object_url') or '#'))}">{escape(_display(item.get('object_title')))}</a>{f'<p>{escape(str(item.get("object_summary") or ""))}</p>' if item.get('object_summary') else ''}</td>
          <td class="transmission-attachment-object-reference">{escape(_display(item.get('object_public_reference')))}{f'<br><span>Optional Reference Identifier: {escape(str(item.get("object_secondary_reference") or ""))}</span>' if item.get('object_secondary_reference') else ''}</td>
          <td class="transmission-attachment-relationship">{escape(_display(item.get('relationship_label')))}</td>
          <td class="transmission-attachment-note">{escape(_display(item.get('public_note')))}</td>
        </tr>"""
        for item in attachments
    )
    if not rows:
        rows = '<tr><td colspan="7" class="transmission-empty">No included governed public objects are visible for this Transmission.</td></tr>'
    return f"""<section><h2>Included Governed Objects</h2><p class="transmission-boundary">Each referenced object keeps its own identity, lifecycle, provenance, verification, and public page. The Transmission preserves communication context only.</p><div class="transmission-results transmission-attachments-wrapper" role="region" aria-label="Included Governed Objects table"><table class="transmission-table transmission-attachments-table"><colgroup><col class="transmission-attachment-position-col"><col class="transmission-attachment-reference-col"><col class="transmission-attachment-type-col"><col class="transmission-attachment-object-col"><col class="transmission-attachment-object-reference-col"><col class="transmission-attachment-relationship-col"><col class="transmission-attachment-note-col"></colgroup><thead><tr><th scope="col">Position</th><th scope="col">Inclusion reference</th><th scope="col">Object type</th><th scope="col">Object</th><th scope="col">Object reference</th><th scope="col">Relationship</th><th scope="col">Public note</th></tr></thead><tbody>{rows}</tbody></table></div></section>"""


def _render_pathway(events: list[dict]) -> str:
    rows = "".join(
        f"<tr><td>{escape(_display(event.get('timestamp')))}</td><td>{escape(_display(event.get('action_label')))}</td><td>{escape(_display(event.get('actor')))}</td><td>{escape(_display(event.get('note')))}</td></tr>"
        for event in events
    ) or '<tr><td colspan="4">No public-safe Transmission pathway entries are available.</td></tr>'
    return f'<section><h2>Transmission Publication Provenance</h2><table class="metadata"><thead><tr><th>Timestamp</th><th>Action</th><th>Actor</th><th>Note</th></tr></thead><tbody>{rows}</tbody></table></section>'


@router.get("/transmissions/{transmission_reference}", response_class=HTMLResponse)
def public_transmission_page(transmission_reference: str, return_to: str | None = None):
    conn = trm.get_db()
    try:
        transmission = trm.get_public_transmission(conn, transmission_reference)
        attachments = trm.list_transmission_attachments(conn, transmission["id"], public_only=True, root=intake_root())
        pathway = trm.public_transmission_history(conn, transmission["id"])
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="public_transmission_not_found") from exc
    finally:
        conn.close()
    reference = str(transmission.get("public_reference") or "")
    archive_return = sanitize_archive_return(return_to)
    fields = (
        ("Reference", reference),
        ("Title", transmission.get("title")),
        ("Summary", transmission.get("summary")),
        ("Sender", transmission.get("sender")),
        ("Recipient", transmission.get("recipient")),
        ("Transmission date", transmission.get("transmission_date")),
        ("Communication method", trm.method_label(transmission.get("communication_method"))),
        ("Subject", transmission.get("subject")),
        ("External reference", transmission.get("external_reference")),
        ("Transmission identifier", transmission.get("transmission_identifier")),
        ("Publication status", trm.status_label(transmission.get("publication_status"))),
        ("Published at", transmission.get("published_at")),
        ("Included governed objects", len(attachments)),
    )
    rows = "".join(f"<tr><th>{escape(label)}</th><td>{escape(_display(value))}</td></tr>" for label, value in fields)
    covering_message = _display(transmission.get("covering_message"))
    return HTMLResponse(content=f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>{escape(_display(transmission.get('title')))} | Public Transmission</title><link rel="canonical" href="/transmissions/{escape(reference)}"><meta name="description" content="Public Transmission {escape(reference)} in the Civic Decision Engine."><style>*{{box-sizing:border-box}}body{{margin:0;background:#f7f7f4;color:#1f2933;font-family:system-ui,sans-serif}}main{{width:min(1280px,calc(100% - 32px));margin:32px auto 64px}}h1,h2{{color:#143a52}}a{{color:#245d61}}{PUBLIC_NAVIGATION_CSS}.transmission-boundary{{padding:14px 16px;border-left:4px solid #2e8b9a;background:#fff;line-height:1.55}}.transmission-reference{{font:700 .9rem ui-monospace,monospace;letter-spacing:.03em;color:#555}}table{{width:100%;border-collapse:collapse;background:#fff}}th,td{{padding:10px;border:1px solid #e1dfd8;text-align:left;vertical-align:top;overflow-wrap:anywhere}}th{{background:#faf9f5;color:#555}}.metadata th{{width:230px}}.transmission-results{{overflow-x:auto}}.transmission-table{{min-width:980px;table-layout:auto}}.transmission-table th{{background:#143a52;color:#fff;width:auto}}.transmission-attachments-wrapper{{max-width:100%;overflow-x:auto}}.transmission-attachments-table{{min-width:1240px;table-layout:fixed}}.transmission-attachments-table th,.transmission-attachments-table td{{overflow-wrap:normal;word-break:normal}}.transmission-attachments-table th{{white-space:nowrap}}.transmission-attachment-position-col{{width:4%}}.transmission-attachment-reference-col{{width:17%}}.transmission-attachment-type-col{{width:14%}}.transmission-attachment-object-col{{width:24%}}.transmission-attachment-object-reference-col{{width:16%}}.transmission-attachment-relationship-col{{width:15%}}.transmission-attachment-note-col{{width:10%}}.transmission-attachment-position{{text-align:center;white-space:nowrap}}.transmission-attachment-reference,.transmission-attachment-object-reference{{font-family:ui-monospace,monospace;white-space:nowrap}}.transmission-attachment-type{{white-space:nowrap}}.transmission-attachment-object,.transmission-attachment-note{{overflow-wrap:break-word}}.transmission-attachment-object p{{margin:.4rem 0 0;line-height:1.45;color:#555}}.transmission-attachment-object-reference span{{display:block;margin-top:.35rem;white-space:normal;overflow-wrap:break-word;color:#555}}.transmission-attachment-relationship{{white-space:nowrap}}.transmission-attachment-note{{color:#555}}.covering-message{{white-space:pre-wrap;background:#fff;border:1px solid #e1dfd8;padding:14px;line-height:1.55}}</style></head><body><main>{public_primary_navigation(active="transmissions")}{public_breadcrumbs([("Home", "/"), ("Archive", archive_return), ("Transmissions", "/archive?type=public_transmission"), (_display(transmission.get("title")), None)])}{archive_back_link(archive_return)}<p>{object_type_badge("public_transmission")}</p><p class="transmission-reference">{escape(reference)}</p><h1>{escape(_display(transmission.get('title')))}</h1><p class="transmission-boundary">{escape(BOUNDARY_TEXT)} Included governed objects remain independently governed and independently addressable.</p><section><h2>Transmission Metadata</h2><table class="metadata"><tbody>{rows}</tbody></table></section><section><h2>Covering Communication</h2><p class="transmission-boundary">The covering communication is governed text belonging to this Transmission. It is not a document and does not replace any included governed object.</p><div class="covering-message">{escape(covering_message)}</div></section>{_render_attachments(attachments)}{_render_pathway(pathway)}<p><a href="/traceability?search={escape(reference)}">Open in Public Traceability Map</a> · <a href="/transmissions">Back to Public Transmission Library</a></p></main></body></html>""")
