from __future__ import annotations

from html import escape
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

from api import archive_collections as ac

router = APIRouter()

BOUNDARY_TEXT = (
    "This collection provides governed context for independently preserved documents. "
    "Collection identity does not merge document contents, alter document provenance "
    "or lifecycle, establish evidential sufficiency, or make the collection proof of "
    "any shared claim."
)


def _not_found(exc: Exception):
    raise HTTPException(status_code=404, detail="public_collection_not_found") from exc


def _display(value: object) -> str:
    if value is None or value == "":
        return "—"
    return str(value)


def _date(value: object) -> str:
    return _display(value).split("T", 1)[0]


def _visibility_label(value: object) -> str:
    return "Public" if int(value or 0) == 1 else "Private"


def _active_label(value: object) -> str:
    return "Active" if int(value or 0) == 1 else "Inactive"


def _date_range(item: dict) -> str:
    start = item.get("date_from")
    end = item.get("date_to")
    if start and end:
        return f"{start} to {end}"
    if start:
        return f"From {start}"
    if end:
        return f"To {end}"
    return "—"


def _query_string(filters: dict[str, object], *, page: int | None = None, page_size: int | None = None) -> str:
    params: dict[str, object] = {}
    for key in ("q", "category", "institution", "created_year", "coverage_year"):
        value = filters.get(key)
        if value:
            params[key] = value
    if page is not None:
        params["page"] = page
    if page_size is not None:
        params["page_size"] = page_size
    return urlencode(params)


def _option_list(options: list[str], selected: str, *, blank_label: str, labels: dict[str, str] | None = None) -> str:
    rendered = [f'<option value="">{escape(blank_label)}</option>']
    label_map = labels or {}
    for option in options:
        rendered.append(
            f'<option value="{escape(option)}"{" selected" if selected == option else ""}>{escape(label_map.get(option, option))}</option>'
        )
    return "".join(rendered)


def _page_size_options(selected: int) -> str:
    return "".join(
        f'<option value="{size}"{" selected" if selected == size else ""}>{size}</option>'
        for size in ac.PUBLIC_COLLECTION_PAGE_SIZE_OPTIONS
    )


def _active_filter_summary(filters: dict[str, object]) -> str:
    labels = {
        "q": "Search",
        "category": "Category",
        "institution": "Institution / source",
        "created_year": "Created year",
        "coverage_year": "Declared coverage year",
    }
    active = [
        f"{labels[key]}: {filters[key]}"
        for key in labels
        if filters.get(key)
    ]
    return "; ".join(str(item) for item in active) if active else "None"


def _render_collection_index_rows(rows: list[dict]) -> str:
    rendered = []
    for item in rows:
        reference = str(item.get("public_reference") or "")
        rendered.append(
            f"""<tr>
              <td class="public-collection-reference"><a href="/collections/{escape(reference)}">{escape(reference)}</a></td>
              <td class="public-collection-title"><strong>{escape(_display(item.get('title')))}</strong>{f'<p>{escape(str(item.get("subtitle") or ""))}</p>' if item.get("subtitle") else ''}</td>
              <td class="public-collection-source">{escape(_display(item.get('institution_source')))}</td>
              <td class="public-collection-category">{escape(ac.category_label(item.get('category')))}</td>
              <td class="public-collection-date-range">{escape(_date_range(item))}</td>
              <td class="public-collection-created">{escape(_date(item.get('created_at')))}</td>
              <td class="public-collection-actions"><a href="/collections/{escape(reference)}">View collection</a></td>
            </tr>"""
        )
    return "".join(rendered)


@router.get("/collections", response_class=HTMLResponse)
def public_collection_index(
    q: str | None = None,
    category: str | None = None,
    institution: str | None = None,
    created_year: str | None = None,
    coverage_year: str | None = None,
    page: int | str | None = 1,
    page_size: int | str | None = 25,
):
    conn = ac.get_db()
    try:
        result = ac.list_public_collection_index(
            conn,
            q=q,
            category=category,
            institution=institution,
            created_year=created_year,
            coverage_year=coverage_year,
            page=page,
            page_size=page_size,
        )
    finally:
        conn.close()
    filters = result["filters"]
    rows_html = _render_collection_index_rows(result["rows"])
    if rows_html:
        body_rows = rows_html
    elif _active_filter_summary(filters) == "None":
        body_rows = '<tr><td class="public-collection-empty" colspan="7">No eligible public archive collections are currently listed.</td></tr>'
    else:
        body_rows = '<tr><td class="public-collection-empty" colspan="7">No public archive collections match the selected filters.</td></tr>'
    previous_link = ""
    next_link = ""
    if result["page"] > 1:
        previous_link = f'<a href="/collections?{escape(_query_string(filters, page=result["page"] - 1, page_size=result["page_size"]))}">Previous page</a>'
    if result["page"] < result["page_count"]:
        next_link = f'<a href="/collections?{escape(_query_string(filters, page=result["page"] + 1, page_size=result["page_size"]))}">Next page</a>'
    options = result["options"]
    return HTMLResponse(content=f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Public Archive Collections | Civic Decision Engine</title><link rel="canonical" href="/collections"><meta name="description" content="Public index of governed archive collection identities in the Civic Decision Engine."><style>*{{box-sizing:border-box}}body{{margin:0;background:#f7f7f4;color:#1f2933;font-family:system-ui,sans-serif}}main.public-collection-index{{width:min(1180px,calc(100% - 32px));margin:32px auto 64px}}h1,h2{{color:#143a52}}a{{color:#245d61}}.public-collection-boundary,.public-collection-summary{{padding:14px 16px;border-left:4px solid #2e8b9a;background:#fff;line-height:1.55}}.public-collection-summary{{margin:18px 0;border-left-color:#143a52}}.public-collection-filters{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;background:#fff;border:1px solid #d8d4ca;padding:16px;margin:22px 0}}.public-collection-filters label{{display:grid;gap:6px;color:#555;font:.78rem ui-monospace,monospace;text-transform:uppercase}}.public-collection-filters input,.public-collection-filters select{{width:100%;padding:9px;border:1px solid #c9c6bd;background:#fff;font:.92rem system-ui,sans-serif}}.public-collection-filters button,.public-collection-filters a{{width:max-content;padding:9px 12px;border:0;background:#245d61;color:#fff;cursor:pointer;text-decoration:none;display:inline-block}}.public-collection-results{{overflow-x:auto}}.public-collection-table{{width:100%;min-width:980px;border-collapse:collapse;background:#fff;font-size:.9rem;table-layout:auto}}.public-collection-table th{{background:#143a52;color:#fff;text-align:left}}.public-collection-table th,.public-collection-table td{{padding:10px;border:1px solid #e1dfd8;vertical-align:top;overflow-wrap:anywhere}}.public-collection-reference{{min-width:200px;font-family:ui-monospace,monospace}}.public-collection-title{{min-width:220px}}.public-collection-source,.public-collection-category{{min-width:170px}}.public-collection-actions{{min-width:140px}}.public-collection-empty{{text-align:center;color:#555;padding:18px}}.public-collection-pagination{{display:flex;gap:16px;align-items:center;flex-wrap:wrap;margin:18px 0}}@media(max-width:760px){{.public-collection-filters{{grid-template-columns:1fr}}}}</style></head><body><main class="public-collection-index"><p><a href="/records">Public Record Index</a> · <a href="/documents">Public Document Library</a> · <a href="/associations">Public Association Index</a></p><h1>Public Archive Collections</h1><p class="public-collection-boundary">{escape(BOUNDARY_TEXT)} Public collection listing does not imply document membership, evidential sufficiency, factual truth, authorship, legal status, responsibility, or external validation.</p><section class="public-collection-summary"><p><strong>Total matching public collections:</strong> {int(result['total'])}</p><p><strong>Active filters:</strong> {escape(_active_filter_summary(filters))}</p><p><strong>Page:</strong> {int(result['page'])} of {int(result['page_count'])}</p></section><form class="public-collection-filters" method="get" action="/collections"><label>Search<input name="q" value="{escape(str(filters['q']))}" placeholder="Reference, title, source, category, or public note"></label><label>Category<select name="category">{_option_list(options['categories'], str(filters['category']), blank_label='Any category', labels=ac.COLLECTION_CATEGORIES)}</select></label><label>Institution / source<select name="institution">{_option_list(options['institutions'], str(filters['institution']), blank_label='Any institution / source')}</select></label><label>Created year<select name="created_year">{_option_list(options['created_years'], str(filters['created_year']), blank_label='Any created year')}</select></label><label>Declared coverage year<select name="coverage_year">{_option_list(options['coverage_years'], str(filters['coverage_year']), blank_label='Any coverage year')}</select></label><label>Page size<select name="page_size">{_page_size_options(int(result['page_size']))}</select></label><button type="submit">Apply filters</button><a href="/collections">Clear filters</a></form><div class="public-collection-pagination"><span>Page {int(result['page'])} of {int(result['page_count'])}</span>{previous_link}{next_link}</div><div class="public-collection-results"><table class="public-collection-table"><thead><tr><th class="public-collection-reference">Public collection reference</th><th class="public-collection-title">Collection</th><th class="public-collection-source">Institution / source</th><th class="public-collection-category">Category</th><th class="public-collection-date-range">Declared date range</th><th class="public-collection-created">Created date</th><th class="public-collection-actions">Actions</th></tr></thead><tbody>{body_rows}</tbody></table></div><div class="public-collection-pagination"><span>Page {int(result['page'])} of {int(result['page_count'])}</span>{previous_link}{next_link}</div></main></body></html>""")


def _render_collection_pathway(events: list[dict]) -> str:
    rows = "".join(
        f"""<tr>
          <td class="public-collection-pathway-timestamp">{escape(_display(event.get('timestamp')))}</td>
          <td class="public-collection-pathway-action">{escape(_display(event.get('action_label')))}</td>
          <td class="public-collection-pathway-actor">{escape(_display(event.get('actor')))}</td>
          <td class="public-collection-pathway-state">{escape(_display(event.get('state_change')))}</td>
        </tr>"""
        for event in events
    ) or '<tr><td colspan="4">No public-safe collection pathway entries are available.</td></tr>'
    return f"""<section class="public-collection-pathway"><h2>Collection Pathway</h2><p class="public-collection-boundary">Collection Pathway is a public-safe projection of the collection history. It remains separate from document Publication Pathway, Publication Provenance, Association Pathway, Administrative Audit, and record verification history.</p><div class="public-collection-pathway-wrapper"><table class="public-collection-pathway-table"><thead><tr><th class="public-collection-pathway-timestamp">Timestamp</th><th class="public-collection-pathway-action">Action</th><th class="public-collection-pathway-actor">Recorded actor</th><th class="public-collection-pathway-state">Public-safe state change</th></tr></thead><tbody>{rows}</tbody></table></div></section>"""


@router.get("/collections/{collection_reference}", response_class=HTMLResponse)
def public_collection_page(collection_reference: str):
    conn = ac.get_db()
    try:
        collection = ac.get_public_collection(conn, collection_reference)
        pathway = ac.public_collection_history(conn, collection["id"])
    except ValueError as exc:
        _not_found(exc)
    finally:
        conn.close()

    reference = str(collection.get("public_reference") or "")
    canonical = f"/collections/{escape(reference)}"
    fields = (
        ("Public collection reference", reference),
        ("Title", collection.get("title")),
        ("Subtitle", collection.get("subtitle")),
        ("Institution / source", collection.get("institution_source")),
        ("Category", ac.category_label(collection.get("category"))),
        ("Description", collection.get("description")),
        ("Public note", collection.get("public_note")),
        ("Declared date range", _date_range(collection)),
        ("Created date", collection.get("created_at")),
        ("Current state", _active_label(collection.get("is_active"))),
        ("Public visibility", _visibility_label(collection.get("is_public"))),
    )
    rows = "".join(
        f"<tr><th>{escape(label)}</th><td>{escape(_display(value))}</td></tr>"
        for label, value in fields
    )
    pathway_html = _render_collection_pathway(pathway)
    return HTMLResponse(content=f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>{escape(_display(collection.get('title')))} | Public Archive Collection</title><link rel="canonical" href="{canonical}"><meta name="description" content="Public archive collection {escape(reference)}: {escape(_display(collection.get('title')))}."><style>*{{box-sizing:border-box}}body{{margin:0;background:#f7f7f4;color:#1f2933;font-family:system-ui,sans-serif}}main{{width:min(1040px,calc(100% - 32px));margin:32px auto 64px}}h1,h2{{color:#143a52}}a{{color:#245d61}}.public-collection-reference{{font:700 .9rem ui-monospace,monospace;letter-spacing:.03em;color:#555}}.public-collection-boundary{{padding:14px;border-left:4px solid #2e8b9a;background:#fff;line-height:1.55}}table{{width:100%;border-collapse:collapse;background:#fff}}th,td{{padding:10px;border:1px solid #e1dfd8;text-align:left;vertical-align:top;overflow-wrap:anywhere}}th{{width:230px;background:#faf9f5;color:#555}}.public-collection-pathway-wrapper{{overflow-x:auto}}.public-collection-pathway-table{{min-width:820px;table-layout:auto}}.public-collection-pathway-timestamp{{min-width:180px;white-space:nowrap}}.public-collection-pathway-action,.public-collection-pathway-actor{{min-width:150px}}.public-collection-pathway-state{{min-width:260px;width:100%}}.public-collection-empty{{padding:14px;background:#fff;border:1px solid #e1dfd8}}</style></head><body><main class="public-collection-detail"><p><a href="/collections">Back to Public Archive Collections</a> · <a href="/documents">Public Document Library</a> · <a href="/associations">Public Association Index</a> · <a href="/records">Public Record Index</a></p><p class="public-collection-reference">{escape(reference)}</p><h1>Public Archive Collection</h1><section class="public-collection-summary"><h2>Collection Summary</h2><table>{rows}</table></section><section><h2>Collection Governance Boundary</h2><p class="public-collection-boundary">{escape(BOUNDARY_TEXT)}</p></section><section><h2>Documents in This Collection</h2><p class="public-collection-empty">No governed document memberships are currently recorded. Collection membership will be introduced through a separate governed stage.</p></section>{pathway_html}</main></body></html>""")
