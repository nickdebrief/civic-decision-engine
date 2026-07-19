from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from html import escape
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse

from api import archive_collection_memberships as acm
from api import archive_collections as ac
from api import record_document_associations as rda
from api.document_intake import (
    build_document_search_text,
    document_keywords_display,
    document_media_family,
    document_type_label,
    intake_root,
    list_published_documents,
)
from api.public_navigation import (
    PUBLIC_NAVIGATION_CSS,
    append_archive_return,
    object_type_badge,
    public_breadcrumbs,
    public_primary_navigation,
)
from api.routes import records

router = APIRouter()

OBJECT_TYPES = {
    "canonical_record": "Canonical Record",
    "published_document": "Published Document",
    "record_document_association": "Record-Document Association",
    "public_collection": "Governed Public Collection",
}
OBJECT_TYPE_COUNT_LABELS = {
    "canonical_record": "Canonical Records",
    "published_document": "Published Documents",
    "record_document_association": "Record-Document Associations",
    "public_collection": "Governed Public Collections",
}
MEDIA_FILTERS = {
    "pdf": "PDF",
    "image": "Image",
    "audio": "Audio",
    "spreadsheet": "Spreadsheet",
}
SORTS = {
    "newest": "Newest first",
    "oldest": "Oldest first",
    "alphabetical": "Alphabetical",
    "reference": "Reference",
}
PAGE_SIZE_OPTIONS = (10, 25, 50, 100)
BOUNDARY_TEXT = (
    "The Public Archive Explorer is a discovery interface over existing governed "
    "public objects. It does not create a new governance object, duplicate "
    "provenance, alter lifecycle state, or replace canonical record, document, "
    "association, or collection pages."
)


@dataclass(frozen=True)
class ArchiveResult:
    object_type: str
    title: str
    reference: str
    status: str
    publication_date: str
    summary: str
    url: str
    keywords: str = ""
    media_type: str = ""
    record_type: str = ""
    collection_references: tuple[str, ...] = ()
    search_text: str = ""


def _display(value: object) -> str:
    if value is None or value == "":
        return "-"
    return str(value)


def _date(value: object) -> str:
    text = _display(value)
    return text.split("T", 1)[0] if text != "-" else text


def _year(value: object) -> str:
    text = str(value or "")
    return text[:4] if len(text) >= 4 and text[:4].isdigit() else ""


def _normalize_page(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 1
    return parsed if parsed > 0 else 1


def _normalize_page_size(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = 25
    return parsed if parsed in PAGE_SIZE_OPTIONS else 25


def _tokens(value: Any) -> list[str]:
    return [token.casefold() for token in str(value or "").split() if token.strip()]


def _media_filter_value(document: dict[str, Any]) -> str:
    family = document_media_family(document)
    if family == "document" and document_type_label(document.get("document_type")) == "PDF":
        return "pdf"
    if family in {"image", "audio", "spreadsheet"}:
        return family
    return ""


def _record_title(row: sqlite3.Row | dict[str, Any]) -> str:
    return (
        str(row["record_title"] if "record_title" in row.keys() else "").strip()
        or str(row["title"] if "title" in row.keys() else "").strip()
        or str(row["summary"] if "summary" in row.keys() else "").strip()
        or str(row["finding"] if "finding" in row.keys() else "").strip()
        or str(row["reference"]).strip()
    )


def _record_results(conn: sqlite3.Connection) -> list[ArchiveResult]:
    record_type_expr = records.record_type_sql_expression(conn)
    record_title_expr = records.optional_record_text_expression(conn, "record_title")
    legacy_title_expr = records.optional_record_text_expression(conn, "title")
    institution_expr = records.optional_record_text_expression(conn, "institution")
    event_date_expr = records.optional_record_text_expression(conn, "event_date")
    summary_expr = records.optional_record_text_expression(conn, "summary")
    conditions_expr = records.optional_record_text_expression(conn, "conditions_json")
    rows = conn.execute(
        f"""
        SELECT reference, {record_type_expr} AS record_type,
               {record_title_expr} AS record_title, {legacy_title_expr} AS title,
               {institution_expr} AS institution, {event_date_expr} AS event_date,
               {summary_expr} AS summary, {conditions_expr} AS conditions_json,
               trajectory, system_state, finding, generated_at, exported_at
        FROM records
        WHERE is_latest = 1
        ORDER BY exported_at DESC, reference DESC
        """
    ).fetchall()
    results: list[ArchiveResult] = []
    for row in rows:
        title = _record_title(row)
        record_type = records.normalize_record_type(row["record_type"])
        record_type_label = records.record_type_label(record_type)
        summary = str(row["summary"] or row["finding"] or row["system_state"] or "")
        searchable = " ".join(
            str(value or "")
            for value in (
                row["reference"],
                title,
                record_type,
                record_type_label,
                row["institution"],
                row["event_date"],
                row["summary"],
                row["finding"],
                row["system_state"],
                row["trajectory"],
                row["conditions_json"],
                row["generated_at"],
                row["exported_at"],
            )
        ).casefold()
        results.append(
            ArchiveResult(
                object_type="canonical_record",
                title=title,
                reference=str(row["reference"] or ""),
                status="Published",
                publication_date=str(row["exported_at"] or row["generated_at"] or ""),
                summary=summary,
                url=f"/verify/{row['reference']}",
                keywords=record_type_label,
                record_type=record_type,
                search_text=searchable,
            )
        )
    return results


def _document_results() -> list[ArchiveResult]:
    results: list[ArchiveResult] = []
    for item in list_published_documents(root=intake_root()):
        media = _media_filter_value(item)
        reference = str(item.get("reference_identifier") or item.get("intake_id") or "")
        workbook_names = ""
        metadata = item.get("workbook_metadata")
        if isinstance(metadata, dict) and isinstance(metadata.get("worksheet_names"), list):
            workbook_names = " ".join(str(name) for name in metadata["worksheet_names"])
        search_text = " ".join(
            part
            for part in (
                build_document_search_text(item),
                document_type_label(item.get("document_type")),
                MEDIA_FILTERS.get(media, media),
                workbook_names,
            )
            if part
        ).casefold()
        results.append(
            ArchiveResult(
                object_type="published_document",
                title=str(item.get("title") or reference),
                reference=reference,
                status="Published",
                publication_date=str(item.get("publication_date") or item.get("document_date") or ""),
                summary=str(item.get("description") or ""),
                url=f"/documents/{item.get('intake_id')}",
                keywords=document_keywords_display(item.get("keywords") or item.get("tags")),
                media_type=media,
                search_text=search_text,
            )
        )
    return results


def _all_public_associations(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    page = 1
    while True:
        result = rda.list_public_association_index(
            conn,
            root=intake_root(),
            page=page,
            page_size=100,
            sort="newest",
        )
        rows.extend(result["rows"])
        if int(result["page"]) >= int(result["page_count"]):
            break
        page += 1
    return rows


def _association_results(conn: sqlite3.Connection) -> list[ArchiveResult]:
    results: list[ArchiveResult] = []
    for item in _all_public_associations(conn):
        reference = str(item.get("public_reference") or "")
        document_format = str(item.get("document_format") or "")
        media = {
            "PDF": "pdf",
            "JPEG": "image",
            "PNG": "image",
            "M4A": "audio",
            "MP3": "audio",
            "WAV": "audio",
            "XLS": "spreadsheet",
            "XLSX": "spreadsheet",
        }.get(document_format, "")
        title = str(item.get("relationship_label") or item.get("public_label") or reference)
        summary = " · ".join(
            str(part)
            for part in (
                item.get("public_note"),
                item.get("record_reference"),
                item.get("document_title"),
                item.get("document_reference_identifier"),
            )
            if part
        )
        searchable = " ".join(
            str(item.get(key) or "")
            for key in (
                "public_reference",
                "relationship_type",
                "relationship_label",
                "public_note",
                "record_reference",
                "record_title",
                "document_title",
                "document_reference_identifier",
                "document_institution_source",
                "document_category",
                "document_format",
            )
        ).casefold()
        results.append(
            ArchiveResult(
                object_type="record_document_association",
                title=title,
                reference=reference,
                status="Active public association",
                publication_date=str(item.get("created_at") or ""),
                summary=summary,
                url=f"/associations/{reference}",
                media_type=media,
                search_text=searchable,
            )
        )
    return results


def _all_public_collections(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    page = 1
    while True:
        result = ac.list_public_collection_index(conn, page=page, page_size=100)
        rows.extend(result["rows"])
        if int(result["page"]) >= int(result["page_count"]):
            break
        page += 1
    return rows


def _collection_results(conn: sqlite3.Connection) -> list[ArchiveResult]:
    results: list[ArchiveResult] = []
    for item in _all_public_collections(conn):
        reference = str(item.get("public_reference") or "")
        title = str(item.get("title") or reference)
        summary = " ".join(str(part) for part in (item.get("subtitle"), item.get("description"), item.get("public_note")) if part)
        searchable = " ".join(
            str(item.get(key) or "")
            for key in (
                "public_reference",
                "title",
                "subtitle",
                "institution_source",
                "category",
                "category_label",
                "description",
                "public_note",
                "date_from",
                "date_to",
            )
        ).casefold()
        results.append(
            ArchiveResult(
                object_type="public_collection",
                title=title,
                reference=reference,
                status="Published",
                publication_date=str(item.get("created_at") or ""),
                summary=summary,
                url=f"/collections/{reference}",
                keywords=str(item.get("category_label") or ""),
                collection_references=(reference,),
                search_text=searchable,
            )
        )
    return results


def _collection_member_keys(conn: sqlite3.Connection, collection_reference: str) -> set[tuple[str, str]]:
    reference = str(collection_reference or "").strip()
    if not reference:
        return set()
    try:
        collection = ac.get_public_collection(conn, reference)
    except ValueError:
        return set()
    keys = {("public_collection", str(collection.get("public_reference") or reference))}
    for member in acm.list_public_collection_memberships(conn, collection["id"], root=intake_root()):
        member_type = str(member.get("member_type") or "")
        object_type = {
            "canonical_record": "canonical_record",
            "published_document": "published_document",
            "record_document_association": "record_document_association",
        }.get(member_type)
        member_reference = str(member.get("member_public_reference") or member.get("member_reference") or "")
        if object_type and member_reference:
            keys.add((object_type, member_reference))
    return keys


def _build_archive_results() -> tuple[list[ArchiveResult], dict[str, int]]:
    conn = records.get_db()
    try:
        all_results = (
            _record_results(conn)
            + _document_results()
            + _association_results(conn)
            + _collection_results(conn)
        )
    finally:
        conn.close()
    counts = {key: 0 for key in OBJECT_TYPES}
    for item in all_results:
        counts[item.object_type] += 1
    return all_results, counts


def _matches_search(item: ArchiveResult, search: str) -> bool:
    tokens = _tokens(search)
    if not tokens:
        return True
    searchable = " ".join(
        (
            item.title,
            item.reference,
            OBJECT_TYPES.get(item.object_type, item.object_type),
            item.status,
            item.summary,
            item.keywords,
            item.media_type,
            item.record_type,
            item.search_text,
        )
    ).casefold()
    return all(token in searchable for token in tokens)


def _apply_filters(
    rows: list[ArchiveResult],
    *,
    search: str,
    object_type: str,
    status: str,
    year: str,
    document_year: str,
    record_type: str,
    collection: str,
    media: str,
) -> list[ArchiveResult]:
    normalized_type = object_type if object_type in OBJECT_TYPES else ""
    normalized_status = str(status or "").strip().casefold()
    normalized_year = year if len(str(year or "")) == 4 and str(year).isdigit() else ""
    normalized_document_year = document_year if len(str(document_year or "")) == 4 and str(document_year).isdigit() else ""
    normalized_record_type = str(record_type or "").strip().lower()
    normalized_media = media if media in MEDIA_FILTERS else ""
    collection_keys: set[tuple[str, str]] = set()
    if collection:
        conn = records.get_db()
        try:
            collection_keys = _collection_member_keys(conn, collection)
        finally:
            conn.close()
    filtered: list[ArchiveResult] = []
    for item in rows:
        if normalized_type and item.object_type != normalized_type:
            continue
        if normalized_status and normalized_status not in item.status.casefold():
            continue
        if normalized_year and _year(item.publication_date) != normalized_year:
            continue
        if normalized_document_year:
            if item.object_type != "published_document" or normalized_document_year not in item.search_text:
                continue
        if normalized_record_type and item.record_type != normalized_record_type:
            continue
        if normalized_media and item.media_type != normalized_media:
            continue
        if collection and (item.object_type, item.reference) not in collection_keys:
            continue
        if not _matches_search(item, search):
            continue
        filtered.append(item)
    return filtered


def _sort_rows(rows: list[ArchiveResult], sort: str) -> list[ArchiveResult]:
    normalized = sort if sort in SORTS else "newest"
    if normalized == "oldest":
        return sorted(rows, key=lambda item: (item.publication_date, item.reference, item.object_type))
    if normalized == "alphabetical":
        return sorted(rows, key=lambda item: (item.title.casefold(), item.reference, item.object_type))
    if normalized == "reference":
        return sorted(rows, key=lambda item: (item.reference.casefold(), item.object_type, item.title.casefold()))
    return sorted(rows, key=lambda item: (item.publication_date, item.reference, item.object_type), reverse=True)


def _query_string(filters: dict[str, str], *, page: int | None = None, page_size: int | None = None) -> str:
    params = {key: value for key, value in filters.items() if value and not (key == "sort" and value == "newest")}
    if page is not None:
        params["page"] = str(page)
    if page_size is not None:
        params["page_size"] = str(page_size)
    return urlencode(params)


def _option_list(options: dict[str, str] | list[str], selected: str, blank_label: str) -> str:
    rendered = [f'<option value="">{escape(blank_label)}</option>']
    if isinstance(options, dict):
        iterable = options.items()
    else:
        iterable = ((value, value) for value in options)
    for value, label in iterable:
        rendered.append(
            f'<option value="{escape(str(value))}"{" selected" if selected == value else ""}>{escape(str(label))}</option>'
        )
    return "".join(rendered)


def _page_size_options(selected: int) -> str:
    return "".join(
        f'<option value="{size}"{" selected" if selected == size else ""}>{size}</option>'
        for size in PAGE_SIZE_OPTIONS
    )


def _active_filter_summary(filters: dict[str, str]) -> str:
    labels = {
        "search": "Search",
        "type": "Object type",
        "status": "Publication status",
        "year": "Publication year",
        "document_year": "Document year",
        "record_type": "Record type",
        "collection": "Collection",
        "media": "Media type",
        "sort": "Sort",
    }
    active = []
    for key, label in labels.items():
        value = filters.get(key)
        if not value or (key == "sort" and value == "newest"):
            continue
        active.append(f"{label}: {value}")
    return "; ".join(active) if active else "None"


def _render_stats(counts: dict[str, int]) -> str:
    cards = "".join(
        f"""<a class="archive-stat-card" href="/archive?type={escape(key)}">
          <span>{escape(OBJECT_TYPE_COUNT_LABELS.get(key, label))}</span>
          <strong>{int(counts.get(key, 0))}</strong>
        </a>"""
        for key, label in OBJECT_TYPES.items()
    )
    return f'<section class="archive-stats" aria-label="Archive counts">{cards}</section>'


def _render_result_cards(rows: list[ArchiveResult], archive_return: str) -> str:
    if not rows:
        return '<p class="archive-empty">No public archive objects match these criteria.</p>'
    cards = []
    for item in rows:
        object_label = OBJECT_TYPES.get(item.object_type, item.object_type)
        media = MEDIA_FILTERS.get(item.media_type, item.media_type.title()) if item.media_type else ""
        item_url = append_archive_return(item.url, archive_return)
        metadata = [
            ("Reference", item.reference),
            ("Status", item.status),
            ("Publication date", _date(item.publication_date)),
            ("Media type", media),
            ("Record type", records.record_type_label(item.record_type) if item.record_type else ""),
            ("Keywords", item.keywords),
        ]
        metadata_html = "".join(
            f"<dt>{escape(label)}</dt><dd>{escape(_display(value))}</dd>"
            for label, value in metadata
            if value
        )
        cards.append(
            f"""<article class="archive-result-card">
              <p class="archive-breadcrumb">Archive / {escape(object_label)}{f' / {escape(media)}' if media else ''}</p>
              <p>{object_type_badge(item.object_type)}</p>
              <h2><a href="{escape(item_url)}">{escape(item.title)}</a></h2>
              <p class="archive-reference">{escape(item.reference)}</p>
              <p>{escape(item.summary or 'Governed public object with an independent public page.')}</p>
              <dl>{metadata_html}</dl>
              <p class="archive-actions"><a href="{escape(item_url)}">Open governed object</a></p>
            </article>"""
        )
    return "".join(cards)


@router.get("/archive", response_class=HTMLResponse)
def public_archive_explorer(
    search: str | None = Query(None),
    type: str | None = Query(None),
    status: str | None = Query(None),
    year: str | None = Query(None),
    document_year: str | None = Query(None),
    record_type: str | None = Query(None),
    collection: str | None = Query(None),
    media: str | None = Query(None),
    sort: str | None = Query("newest"),
    page: int | str | None = Query(1),
    page_size: int | str | None = Query(25),
):
    all_rows, counts = _build_archive_results()
    filters = {
        "search": str(search or "").strip(),
        "type": str(type or "").strip(),
        "status": str(status or "").strip(),
        "year": str(year or "").strip(),
        "document_year": str(document_year or "").strip(),
        "record_type": str(record_type or "").strip(),
        "collection": str(collection or "").strip(),
        "media": str(media or "").strip(),
        "sort": str(sort or "newest").strip(),
    }
    filtered = _apply_filters(
        all_rows,
        search=filters["search"],
        object_type=filters["type"],
        status=filters["status"],
        year=filters["year"],
        document_year=filters["document_year"],
        record_type=filters["record_type"],
        collection=filters["collection"],
        media=filters["media"],
    )
    sorted_rows = _sort_rows(filtered, filters["sort"])
    normalized_page_size = _normalize_page_size(page_size)
    total = len(sorted_rows)
    page_count = max(1, (total + normalized_page_size - 1) // normalized_page_size)
    normalized_page = min(_normalize_page(page), page_count)
    start = (normalized_page - 1) * normalized_page_size
    page_rows = sorted_rows[start : start + normalized_page_size]

    years = sorted({_year(item.publication_date) for item in all_rows if _year(item.publication_date)}, reverse=True)
    document_years = sorted(
        {
            token
            for item in all_rows
            if item.object_type == "published_document"
            for token in item.search_text.split()
            if len(token) == 4 and token.isdigit()
        },
        reverse=True,
    )
    record_types = {
        value: records.record_type_label(value)
        for value in sorted({item.record_type for item in all_rows if item.record_type})
    }
    collection_options = {
        item.reference: item.title
        for item in all_rows
        if item.object_type == "public_collection"
    }
    previous_link = ""
    next_link = ""
    if normalized_page > 1:
        previous_link = f'<a href="/archive?{escape(_query_string(filters, page=normalized_page - 1, page_size=normalized_page_size))}">Previous page</a>'
    if normalized_page < page_count:
        next_link = f'<a href="/archive?{escape(_query_string(filters, page=normalized_page + 1, page_size=normalized_page_size))}">Next page</a>'
    current_archive_path = f"/archive?{_query_string(filters, page=normalized_page, page_size=normalized_page_size)}"
    if current_archive_path == "/archive?":
        current_archive_path = "/archive"

    return HTMLResponse(
        content=f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Public Archive Explorer | Civic Decision Engine</title><link rel="canonical" href="/archive"><meta name="description" content="Unified public discovery interface for Civic Decision Engine records, documents, associations, and collections."><style>*{{box-sizing:border-box}}body{{margin:0;background:#f7f7f4;color:#1f2933;font-family:system-ui,sans-serif}}main.archive-explorer{{width:min(1220px,calc(100% - 32px));margin:32px auto 64px}}h1,h2{{color:#143a52}}a{{color:#245d61}}a:focus,input:focus,select:focus,button:focus{{outline:3px solid #2e8b9a;outline-offset:2px}}{PUBLIC_NAVIGATION_CSS}.archive-boundary,.archive-summary{{padding:14px 16px;border-left:4px solid #2e8b9a;background:#fff;line-height:1.55}}.archive-summary{{margin:18px 0;border-left-color:#143a52}}.archive-stats{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:22px 0}}.archive-stat-card{{display:block;background:#fff;border:1px solid #d8d4ca;padding:14px;text-decoration:none;color:#1f2933}}.archive-stat-card span{{display:block;color:#555}}.archive-stat-card strong{{display:block;font-size:1.7rem;color:#143a52}}.archive-filters{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;background:#fff;border:1px solid #d8d4ca;padding:16px;margin:22px 0}}.archive-filters label{{display:grid;gap:6px;color:#555;font:.78rem ui-monospace,monospace;text-transform:uppercase}}.archive-filters input,.archive-filters select{{width:100%;padding:9px;border:1px solid #c9c6bd;background:#fff;font:.92rem system-ui,sans-serif}}.archive-filters button,.archive-filters a{{width:max-content;padding:9px 12px;border:0;background:#245d61;color:#fff;cursor:pointer;text-decoration:none;display:inline-block}}.archive-pagination{{display:flex;gap:16px;align-items:center;flex-wrap:wrap;margin:18px 0}}.archive-results{{display:grid;gap:14px}}.archive-result-card{{background:#fff;border:1px solid #d8d4ca;padding:16px;overflow-wrap:anywhere}}.archive-result-card h2{{margin:.25rem 0}}.archive-breadcrumb,.archive-reference{{color:#555;margin:.2rem 0}}.archive-reference{{font:700 .9rem ui-monospace,monospace}}.archive-result-card dl{{display:grid;grid-template-columns:150px minmax(0,1fr);gap:6px 12px;margin:12px 0}}.archive-result-card dt{{font-weight:700;color:#555}}.archive-result-card dd{{margin:0}}.archive-actions a{{display:inline-block;padding:9px 12px;background:#245d61;color:#fff;text-decoration:none}}.archive-empty{{padding:18px;background:#fff;border:1px solid #d8d4ca}}@media(max-width:980px){{.archive-stats{{grid-template-columns:repeat(2,minmax(0,1fr))}}.archive-filters{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}@media(max-width:640px){{.archive-stats,.archive-filters{{grid-template-columns:1fr}}.archive-result-card dl{{grid-template-columns:1fr}}}}</style></head><body><main class="archive-explorer">{public_primary_navigation(active="archive")}{public_breadcrumbs([("Home", "/"), ("Archive", None)])}<h1>Public Archive Explorer</h1><p class="archive-boundary">{escape(BOUNDARY_TEXT)} Every result links to the governed object that owns its identity, provenance, lifecycle, verification, and public page.</p>{_render_stats(counts)}<section class="archive-summary" aria-live="polite"><p><strong>Total matching public objects:</strong> {total}</p><p><strong>Active filters:</strong> {escape(_active_filter_summary(filters))}</p><p><strong>Page:</strong> {normalized_page} of {page_count}</p></section><form class="archive-filters" method="get" action="/archive"><label>Search<input name="search" value="{escape(filters['search'])}" placeholder="Title, reference, summary, keywords, filename, media, or worksheet" autocomplete="off"></label><label>Object type<select name="type">{_option_list(OBJECT_TYPES, filters['type'], 'Any object type')}</select></label><label>Publication status<input name="status" value="{escape(filters['status'])}" placeholder="Published or active public"></label><label>Publication year<select name="year">{_option_list(years, filters['year'], 'Any publication year')}</select></label><label>Document year<select name="document_year">{_option_list(document_years, filters['document_year'], 'Any document year')}</select></label><label>Record type<select name="record_type">{_option_list(record_types, filters['record_type'], 'Any record type')}</select></label><label>Collection<select name="collection">{_option_list(collection_options, filters['collection'], 'Any collection')}</select></label><label>Media type<select name="media">{_option_list(MEDIA_FILTERS, filters['media'], 'Any media type')}</select></label><label>Sort<select name="sort">{_option_list(SORTS, filters['sort'], 'Sort order')}</select></label><label>Page size<select name="page_size">{_page_size_options(normalized_page_size)}</select></label><button type="submit">Apply filters</button><a href="/archive">Clear filters</a></form><div class="archive-pagination"><span>Page {normalized_page} of {page_count}</span>{previous_link}{next_link}</div><section class="archive-results" aria-label="Archive explorer results">{_render_result_cards(page_rows, current_archive_path)}</section><div class="archive-pagination"><span>Page {normalized_page} of {page_count}</span>{previous_link}{next_link}</div><p><a href="/records">Public Record Index</a> · <a href="/documents">Public Document Library</a> · <a href="/associations">Public Association Index</a> · <a href="/collections">Public Archive Collections</a></p></main></body></html>"""
    )
