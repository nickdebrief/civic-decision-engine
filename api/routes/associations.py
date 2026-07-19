from __future__ import annotations

from html import escape
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

from api import record_document_associations as rda
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
    "This association records a declared and governed relationship between "
    "independently preserved public objects. It does not make the linked document "
    "evidence for the record, alter record verification, change document provenance "
    "or lifecycle, or independently establish evidential sufficiency, factual truth, "
    "authorship, legal status, responsibility, or external validation."
)


def _not_found(exc: Exception):
    raise HTTPException(status_code=404, detail="public_association_not_found") from exc


def _display(value: object) -> str:
    if value is None or value == "":
        return "—"
    return str(value)


def _date(value: object) -> str:
    return _display(value).split("T", 1)[0]


def _active_label(value: object) -> str:
    return "Active" if int(value or 0) == 1 else "Inactive"


def _visibility_label(value: object) -> str:
    return "Public" if int(value or 0) == 1 else "Private"


def _relationship_label(item: dict) -> str:
    return str(item.get("public_label") or item.get("relationship_label") or rda.RELATIONSHIP_TYPES.get(str(item.get("relationship_type") or ""), item.get("relationship_type") or "—"))


def _render_pathway(events: list[dict]) -> str:
    rows = "".join(
        f"""<tr>
          <td class="association-pathway-timestamp">{escape(_display(event.get('timestamp')))}</td>
          <td class="association-pathway-action">{escape(_display(event.get('action_label')))}</td>
          <td class="association-pathway-actor">{escape(_display(event.get('actor')))}</td>
          <td class="association-pathway-state">{escape(_display(event.get('previous_state')))}</td>
          <td class="association-pathway-state">{escape(_display(event.get('new_state')))}</td>
          <td class="association-pathway-note">{escape(_display(event.get('note')))}</td>
        </tr>"""
        for event in events
    ) or '<tr><td colspan="6">No public-safe association pathway entries are available.</td></tr>'
    return f"""<section class="association-pathway"><h2>Association Pathway</h2><p class="association-governance-boundary">Association pathway is a public-safe projection of the association's administrative history. It is separate from record verification history, document Publication Pathway, Publication Provenance, Administrative Audit, and Document Intake lifecycle history.</p><div class="association-pathway-wrapper"><table class="association-pathway-table"><thead><tr><th class="association-pathway-timestamp">Timestamp</th><th class="association-pathway-action">Action</th><th class="association-pathway-actor">Recorded actor</th><th class="association-pathway-state">Previous active/public state</th><th class="association-pathway-state">New active/public state</th><th class="association-pathway-note">Public-safe note</th></tr></thead><tbody>{rows}</tbody></table></div></section>"""


def _render_association_page(item: dict, pathway: list[dict], return_to: object | None = None) -> str:
    reference = str(item.get("public_reference") or "")
    archive_return = sanitize_archive_return(return_to)
    canonical = f"/associations/{escape(reference)}"
    summary_fields = (
        ("Public association reference", reference),
        ("Relationship type", rda.RELATIONSHIP_TYPES.get(str(item.get("relationship_type") or ""), item.get("relationship_type"))),
        ("Public label", _relationship_label(item)),
        ("Public note", item.get("public_note")),
        ("Created timestamp", item.get("created_at")),
        ("Created actor", item.get("created_by")),
        ("Current association state", _active_label(item.get("is_active"))),
        ("Public visibility", _visibility_label(item.get("is_public"))),
        ("Linked-object eligibility", "Record and document are publicly eligible"),
    )
    record_fields = (
        ("Record reference", item.get("record_reference")),
        ("Record title or summary", item.get("record_title")),
        ("Generated date", item.get("record_generated_at")),
        ("Trajectory", item.get("record_trajectory")),
        ("Record version", item.get("record_version")),
    )
    document_fields = (
        ("Document title", item.get("document_title")),
        ("Document reference identifier", item.get("document_reference_identifier")),
        ("Institution / source", item.get("document_institution_source")),
        ("Category", item.get("document_category")),
        ("Document format", item.get("document_format")),
        ("Document date", item.get("document_date")),
        ("Publication date", item.get("document_publication_date")),
    )

    def rows(fields: tuple[tuple[str, object], ...]) -> str:
        return "".join(
            f"<tr><th>{escape(label)}</th><td>{escape(_display(value))}</td></tr>"
            for label, value in fields
        )

    pathway_html = _render_pathway(pathway)
    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Record–Document Association — {escape(reference)}</title><link rel="canonical" href="{canonical}"><meta name="description" content="Public record-document association {escape(reference)} linking {escape(str(item.get('record_reference') or ''))} and {escape(str(item.get('document_title') or ''))} without asserting evidential sufficiency or legal status."><style>*{{box-sizing:border-box}}body{{margin:0;background:#f7f7f4;color:#1f2933;font-family:system-ui,sans-serif}}main{{width:min(1040px,calc(100% - 32px));margin:32px auto 64px}}h1,h2{{color:#143a52}}a{{color:#245d61}}{PUBLIC_NAVIGATION_CSS}.association-reference{{font:700 .9rem ui-monospace,monospace;letter-spacing:.03em;color:#555}}.association-governance-boundary{{padding:14px;border-left:4px solid #2e8b9a;background:#fff;line-height:1.55}}.association-summary,.association-linked-record,.association-linked-document{{margin-top:26px}}table{{width:100%;border-collapse:collapse;background:#fff}}th,td{{padding:10px;border:1px solid #e1dfd8;text-align:left;vertical-align:top;overflow-wrap:anywhere}}th{{width:230px;background:#faf9f5;color:#555}}.association-linked-objects{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}.association-actions{{display:flex;flex-wrap:wrap;gap:12px;margin:18px 0}}.association-actions a{{display:inline-block;padding:10px 14px;background:#245d61;color:#fff;text-decoration:none}}.association-pathway-wrapper{{overflow-x:auto}}.association-pathway-table{{min-width:940px;table-layout:auto}}.association-pathway-timestamp{{min-width:180px;white-space:nowrap}}.association-pathway-action,.association-pathway-actor{{min-width:130px}}.association-pathway-state{{min-width:170px}}.association-pathway-note{{min-width:240px;width:100%}}@media(max-width:760px){{.association-linked-objects{{grid-template-columns:1fr}}.association-pathway-table{{min-width:880px}}}}</style></head><body><main class="public-association">{public_primary_navigation(active="associations")}{public_breadcrumbs([("Home", "/"), ("Archive", archive_return), ("Associations", "/archive?type=record_document_association"), (_relationship_label(item) or reference, None)])}{archive_back_link(archive_return)}<p><a href="/associations">Back to Public Association Index</a> · <a href="/records">Back to Public Record Index</a> · <a href="/documents">Back to Public Document Library</a></p><p>{object_type_badge("record_document_association")}</p><p class="association-reference">{escape(reference)}</p><h1>Public Record–Document Association</h1><p class="association-governance-boundary">{escape(BOUNDARY_TEXT)}</p><section class="association-summary"><h2>Association Summary</h2><table>{rows(summary_fields)}</table></section><div class="association-actions"><a href="/verify/{escape(str(item.get('record_reference') or ''))}">View civic record</a><a href="/documents/{escape(str(item.get('document_id') or ''))}">View published document</a></div><div class="association-linked-objects"><section class="association-linked-record"><h2>Associated Civic Record</h2><p>{object_type_badge("canonical_record")}</p><table>{rows(record_fields)}</table></section><section class="association-linked-document"><h2>Associated Public Document</h2><p>{object_type_badge("published_document")}</p><table>{rows(document_fields)}</table></section></div>{pathway_html}</main></body></html>"""


@router.get("/associations/{association_reference}", response_class=HTMLResponse)
def public_association_page(association_reference: str, return_to: str | None = None):
    conn = rda.get_db()
    try:
        item = rda.get_public_association(conn, association_reference, root=intake_root())
        pathway = rda.public_association_history(conn, item["id"])
    except ValueError as exc:
        _not_found(exc)
    finally:
        conn.close()
    return HTMLResponse(content=_render_association_page(item, pathway, return_to=return_to))


def _query_string(filters: dict[str, object], *, page: int | None = None, page_size: int | None = None) -> str:
    params: dict[str, object] = {}
    for key in (
        "q",
        "relationship_type",
        "record_reference",
        "document_reference",
        "institution",
        "category",
        "created_year",
        "document_format",
        "sort",
    ):
        value = filters.get(key)
        if value:
            params[key] = value
    if page is not None:
        params["page"] = page
    if page_size is not None:
        params["page_size"] = page_size
    return urlencode(params)


def _option_list(options: list[str], selected: str, *, blank_label: str) -> str:
    rendered = [f'<option value="">{escape(blank_label)}</option>']
    for option in options:
        rendered.append(
            f'<option value="{escape(option)}"{" selected" if selected == option else ""}>{escape(option)}</option>'
        )
    return "".join(rendered)


def _relationship_options(selected: str) -> str:
    rendered = ['<option value="">Any relationship type</option>']
    for value, label in rda.RELATIONSHIP_TYPES.items():
        rendered.append(
            f'<option value="{escape(value)}"{" selected" if selected == value else ""}>{escape(label)}</option>'
        )
    return "".join(rendered)


def _page_size_options(selected: int) -> str:
    return "".join(
        f'<option value="{size}"{" selected" if selected == size else ""}>{size}</option>'
        for size in rda.PUBLIC_ASSOCIATION_PAGE_SIZE_OPTIONS
    )


def _sort_options(selected: str) -> str:
    labels = {
        "newest": "Newest first",
        "oldest": "Oldest first",
        "association_reference": "Association reference",
        "record_reference": "Record reference",
        "document_title": "Document title",
    }
    return "".join(
        f'<option value="{escape(value)}"{" selected" if selected == value else ""}>{escape(label)}</option>'
        for value, label in labels.items()
    )


def _active_filter_summary(filters: dict[str, object]) -> str:
    labels = {
        "q": "Search",
        "relationship_type": "Relationship type",
        "record_reference": "Record reference",
        "document_reference": "Document reference",
        "institution": "Institution / source",
        "category": "Category",
        "created_year": "Created year",
        "document_format": "Document format",
        "sort": "Sort",
    }
    active = [
        f"{labels[key]}: {filters[key]}"
        for key in labels
        if filters.get(key) and not (key == "sort" and filters.get(key) == "newest")
    ]
    return "; ".join(str(item) for item in active) if active else "None"


def _render_index_rows(rows: list[dict]) -> str:
    if not rows:
        return ""
    rendered = []
    for item in rows:
        reference = str(item.get("public_reference") or "")
        record_reference = str(item.get("record_reference") or "")
        document_id = str(item.get("document_id") or "")
        rendered.append(
            f"""<tr>
              <td class="association-index-reference"><a href="/associations/{escape(reference)}">{escape(reference)}</a></td>
              <td class="association-index-relationship"><strong>{escape(_relationship_label(item))}</strong>{f'<p>{escape(str(item.get("public_note") or ""))}</p>' if item.get("public_note") else ''}</td>
              <td class="association-index-record"><a href="/verify/{escape(record_reference)}">{escape(record_reference)}</a><p>{escape(_display(item.get('record_title')))}</p><small>{escape(_date(item.get('record_generated_at')))} · {escape(_display(item.get('record_trajectory')))}</small></td>
              <td class="association-index-document"><a href="/documents/{escape(document_id)}">{escape(_display(item.get('document_title')))}</a><p>{escape(_display(item.get('document_reference_identifier')))}</p><small>{escape(_display(item.get('document_format')))}</small></td>
              <td class="association-index-source">{escape(_display(item.get('document_institution_source')))}</td>
              <td class="association-index-category">{escape(_display(item.get('document_category')))}</td>
              <td class="association-index-created">{escape(_date(item.get('created_at')))}</td>
              <td class="association-index-actions"><a href="/associations/{escape(reference)}">View association</a><a href="/verify/{escape(record_reference)}" aria-label="View record">View civic record</a><a href="/documents/{escape(document_id)}" aria-label="View document">View published document</a></td>
            </tr>"""
        )
    return "".join(rendered)


@router.get("/associations", response_class=HTMLResponse)
def public_association_index(
    q: str | None = None,
    relationship_type: str | None = None,
    record_reference: str | None = None,
    document_reference: str | None = None,
    institution: str | None = None,
    category: str | None = None,
    created_year: str | None = None,
    document_format: str | None = None,
    page: int | str | None = 1,
    page_size: int | str | None = 25,
    sort: str | None = "newest",
):
    conn = rda.get_db()
    try:
        result = rda.list_public_association_index(
            conn,
            root=intake_root(),
            q=q,
            relationship_type=relationship_type,
            record_reference=record_reference,
            document_reference=document_reference,
            institution=institution,
            category=category,
            created_year=created_year,
            document_format=document_format,
            page=page,
            page_size=page_size,
            sort=sort,
        )
    finally:
        conn.close()
    filters = result["filters"]
    options = result["options"]
    rows_html = _render_index_rows(result["rows"])
    if rows_html:
        body_rows = rows_html
    elif _active_filter_summary(filters) == "None":
        body_rows = '<tr><td class="association-index-empty" colspan="8">No eligible public associations are currently listed.</td></tr>'
    else:
        body_rows = '<tr><td class="association-index-empty" colspan="8">No public record-document associations match the selected filters. No public associations match the selected filters.</td></tr>'
    previous_link = ""
    next_link = ""
    if result["page"] > 1:
        previous_link = f'<a href="/associations?{escape(_query_string(filters, page=result["page"] - 1, page_size=result["page_size"]))}">Previous page</a>'
    if result["page"] < result["page_count"]:
        next_link = f'<a href="/associations?{escape(_query_string(filters, page=result["page"] + 1, page_size=result["page_size"]))}">Next page</a>'
    return HTMLResponse(content=f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Public Record–Document Associations | Civic Decision Engine</title><link rel="canonical" href="/associations"><meta name="description" content="Public index of declared and governed relationships between independently preserved public civic records and published documents."><style>*{{box-sizing:border-box}}body{{margin:0;background:#f7f7f4;color:#1f2933;font-family:system-ui,sans-serif}}main.public-association-index{{width:min(1280px,calc(100% - 32px));margin:32px auto 64px}}h1,h2{{color:#143a52}}a{{color:#245d61}}{PUBLIC_NAVIGATION_CSS}.public-association-index-boundary,.public-association-index-summary{{padding:14px 16px;border-left:4px solid #2e8b9a;background:#fff;line-height:1.55}}.public-association-index-summary{{margin:18px 0;border-left-color:#143a52}}.public-association-filters{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;background:#fff;border:1px solid #d8d4ca;padding:16px;margin:22px 0}}.public-association-filters label{{display:grid;gap:6px;color:#555;font:.78rem ui-monospace,monospace;text-transform:uppercase}}.public-association-filters input,.public-association-filters select{{width:100%;padding:9px;border:1px solid #c9c6bd;background:#fff;font:.92rem system-ui,sans-serif}}.public-association-filters button,.public-association-filters a{{width:max-content;padding:9px 12px;border:0;background:#245d61;color:#fff;cursor:pointer;text-decoration:none;display:inline-block}}.public-association-results-wrapper{{overflow-x:auto}}.public-association-results-table{{width:100%;min-width:1180px;border-collapse:collapse;background:#fff;font-size:.9rem;table-layout:auto}}.public-association-results-table th{{background:#143a52;color:#fff;text-align:left}}.public-association-results-table th,.public-association-results-table td{{padding:10px;border:1px solid #e1dfd8;vertical-align:top;overflow-wrap:anywhere}}.association-index-reference{{min-width:210px;font-family:ui-monospace,monospace}}.association-index-relationship{{min-width:200px}}.association-index-record,.association-index-document{{min-width:230px}}.association-index-source,.association-index-category{{min-width:150px}}.association-index-created{{min-width:120px}}.association-index-actions{{min-width:170px}}.association-index-actions a{{display:block;margin-bottom:6px}}.association-index-empty{{text-align:center;color:#555;padding:18px}}.association-index-pagination{{display:flex;gap:16px;align-items:center;flex-wrap:wrap;margin:18px 0}}@media(max-width:980px){{.public-association-filters{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}@media(max-width:640px){{.public-association-filters{{grid-template-columns:1fr}}}}</style></head><body><main class="public-association-index">{public_primary_navigation(active="associations")}{public_breadcrumbs([("Home", "/"), ("Archive", "/archive"), ("Associations", None)])}<h1>Public Record–Document Associations</h1><p class="public-association-index-boundary">This index lists declared and governed relationships between independently preserved public civic records and published documents. Listing an association does not make a document evidence for a record, alter record verification, change document provenance or lifecycle, or independently establish evidential sufficiency, factual truth, authorship, legal status, responsibility, or external validation.</p><section class="public-association-index-summary"><p><strong>Total matching public associations:</strong> {int(result['total'])}</p><p><strong>Active filters:</strong> {escape(_active_filter_summary(filters))}</p><p><strong>Page:</strong> {int(result['page'])} of {int(result['page_count'])}</p></section><form class="public-association-filters" method="get" action="/associations"><label>Search<input name="q" value="{escape(str(filters['q']))}" placeholder="Association, record, document, note, source, or category"></label><label>Relationship type<select name="relationship_type">{_relationship_options(str(filters['relationship_type']))}</select></label><label>Record reference<input name="record_reference" value="{escape(str(filters['record_reference']))}"></label><label>Document reference<input name="document_reference" value="{escape(str(filters['document_reference']))}"></label><label>Institution / source<select name="institution">{_option_list(options['institutions'], str(filters['institution']), blank_label='Any institution / source')}</select></label><label>Category<select name="category">{_option_list(options['categories'], str(filters['category']), blank_label='Any category')}</select></label><label>Created year<select name="created_year">{_option_list(options['created_years'], str(filters['created_year']), blank_label='Any created year')}</select></label><label>Document format<select name="document_format">{_option_list(options['document_formats'], str(filters['document_format']), blank_label='Any document format')}</select></label><label>Sort<select name="sort">{_sort_options(str(filters['sort']))}</select></label><label>Page size<select name="page_size">{_page_size_options(int(result['page_size']))}</select></label><button type="submit">Apply filters</button><a href="/associations">Clear filters</a></form><div class="association-index-pagination"><span>Page {int(result['page'])} of {int(result['page_count'])}</span>{previous_link}{next_link}</div><div class="public-association-results-wrapper"><table class="public-association-results-table"><thead><tr><th class="association-index-reference">Public association reference</th><th class="association-index-relationship">Relationship</th><th class="association-index-record">Civic record</th><th class="association-index-document">Published document</th><th class="association-index-source">Institution / source</th><th class="association-index-category">Category</th><th class="association-index-created">Created date</th><th class="association-index-actions">Actions</th></tr></thead><tbody>{body_rows}</tbody></table></div><div class="association-index-pagination"><span>Page {int(result['page'])} of {int(result['page_count'])}</span>{previous_link}{next_link}</div></main></body></html>""")
