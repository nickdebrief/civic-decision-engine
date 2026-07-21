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
from api import public_transmissions as trm
from api import record_document_associations as rda
from api.document_intake import (
    build_document_search_text,
    document_media_family,
    document_type_label,
    intake_root,
    list_published_documents,
)
from api.public_navigation import (
    PUBLIC_NAVIGATION_CSS,
    append_traceability_return,
    object_type_badge,
    public_breadcrumbs,
    public_primary_navigation,
)
from api.routes import records


router = APIRouter()

BOUNDARY_TEXT = (
    "The Public Traceability Map visualises declared relationships between "
    "independently governed public objects. It does not create or infer "
    "relationships, establish evidence, alter provenance, change lifecycle "
    "state, or replace the public pages of the governed objects shown."
)
DISCOVERY_BOUNDARY = (
    "The map is a discovery interface, not itself a governed object. Absence "
    "from the map does not prove that no private, administrative, historical, "
    "or unpublished relationship exists."
)
PAGE_SIZE_OPTIONS = (10, 25, 50, 100)
MEDIA_FILTERS = {
    "pdf": "PDF",
    "image": "Image",
    "audio": "Audio",
    "spreadsheet": "Spreadsheet",
    "rich_text": "Rich Text",
}
SORTS = {
    "newest": "Newest first",
    "oldest": "Oldest first",
    "record": "Canonical record",
    "document": "Published document",
    "association": "Association reference",
}
OBJECT_ACTION_LABELS = {
    "canonical_record": "Open Canonical Record",
    "published_document": "Open Published Document",
    "record_document_association": "Open Association",
    "public_collection": "Open Collection",
    "public_transmission": "Open Transmission",
}
RELATIONSHIP_LABELS = rda.RELATIONSHIP_TYPES


@dataclass(frozen=True)
class CollectionContext:
    reference: str
    title: str
    status: str
    visible_member_count: int
    url: str
    membership_reference: str
    member_type_label: str


@dataclass(frozen=True)
class TraceabilityChain:
    association_reference: str
    association_label: str
    relationship_type: str
    relationship_label: str
    association_status: str
    association_created_at: str
    association_url: str
    record_reference: str
    record_title: str
    record_type: str
    record_status: str
    record_url: str
    document_id: str
    document_reference: str
    document_title: str
    document_format: str
    document_media: str
    document_status: str
    document_date: str
    document_publication_date: str
    document_institution: str
    document_category: str
    document_url: str
    public_note: str
    collections: tuple[CollectionContext, ...]
    search_text: str


@dataclass(frozen=True)
class TransmissionLink:
    transmission_reference: str
    transmission_title: str
    transmission_status: str
    transmission_method: str
    transmission_date: str
    transmission_url: str
    object_type: str
    object_type_label: str
    object_reference: str
    object_title: str
    object_status: str
    object_url: str
    relationship_label: str
    public_note: str
    collection_contexts: tuple[CollectionContext, ...]
    search_text: str


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


def _tokens(value: Any) -> list[str]:
    return [token.casefold() for token in str(value or "").split() if token.strip()]


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


def _media_filter_value(document: dict[str, Any]) -> str:
    family = document_media_family(document)
    if family == "document" and document_type_label(document.get("document_type")) == "PDF":
        return "pdf"
    if family in MEDIA_FILTERS:
        return family
    return ""


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


def _public_collection_contexts(conn: sqlite3.Connection) -> tuple[dict[str, dict[str, Any]], dict[tuple[str, str], list[CollectionContext]]]:
    collections_by_reference: dict[str, dict[str, Any]] = {}
    memberships_by_member: dict[tuple[str, str], list[CollectionContext]] = {}
    for collection in _all_public_collections(conn):
        reference = str(collection.get("public_reference") or "")
        if not reference:
            continue
        collections_by_reference[reference] = collection
        try:
            members = acm.list_public_collection_memberships(
                conn,
                int(collection["_internal_id"]),
                root=intake_root(),
            )
        except (KeyError, TypeError, ValueError):
            members = []
        for member in members:
            member_type = str(member.get("member_type") or "")
            member_reference = str(member.get("member_public_reference") or member.get("member_reference") or "")
            if not member_type or not member_reference:
                continue
            context = CollectionContext(
                reference=reference,
                title=str(collection.get("title") or reference),
                status="Published",
                visible_member_count=len(members),
                url=f"/collections/{reference}",
                membership_reference=str(member.get("membership_reference") or ""),
                member_type_label=str(member.get("member_type_label") or member_type),
            )
            memberships_by_member.setdefault((member_type, member_reference), []).append(context)
    return collections_by_reference, memberships_by_member


def _document_contexts() -> dict[str, dict[str, Any]]:
    return {str(item.get("intake_id")): item for item in list_published_documents(root=intake_root())}


def _collection_context_for_chain(
    chain_keys: tuple[tuple[str, str], ...],
    memberships_by_member: dict[tuple[str, str], list[CollectionContext]],
) -> tuple[CollectionContext, ...]:
    seen: set[str] = set()
    contexts: list[CollectionContext] = []
    for key in chain_keys:
        for context in memberships_by_member.get(key, []):
            dedupe_key = f"{context.reference}:{context.membership_reference}"
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            contexts.append(context)
    return tuple(sorted(contexts, key=lambda item: (item.reference, item.membership_reference)))


def _build_traceability_chains() -> tuple[list[TraceabilityChain], dict[str, dict[str, Any]]]:
    documents_by_id = _document_contexts()
    conn = records.get_db()
    try:
        collections_by_reference, memberships_by_member = _public_collection_contexts(conn)
        chains: list[TraceabilityChain] = []
        for row in _all_public_associations(conn):
            document = documents_by_id.get(str(row.get("document_id") or ""))
            if not document:
                continue
            association_reference = str(row.get("public_reference") or "")
            record_reference = str(row.get("record_reference") or "")
            document_reference = str(row.get("document_reference_identifier") or document.get("reference_identifier") or row.get("document_id") or "")
            relationship_type = str(row.get("relationship_type") or "")
            relationship_label = str(RELATIONSHIP_LABELS.get(relationship_type, relationship_type))
            association_label = str(row.get("relationship_label") or relationship_label)
            media = _media_filter_value(document)
            record_title = str(row.get("record_title") or record_reference)
            document_title = str(row.get("document_title") or document.get("title") or document_reference)
            chain_collections = _collection_context_for_chain(
                (
                    ("canonical_record", record_reference),
                    ("published_document", document_reference),
                    ("record_document_association", association_reference),
                ),
                memberships_by_member,
            )
            search_text = " ".join(
                str(value or "")
                for value in (
                    association_reference,
                    relationship_type,
                    relationship_label,
                    row.get("public_note"),
                    record_reference,
                    record_title,
                    row.get("record_trajectory"),
                    document_reference,
                    document_title,
                    document.get("title"),
                    document.get("description"),
                    document.get("institution_source"),
                    document.get("category"),
                    document.get("document_date"),
                    document.get("publication_date"),
                    document.get("original_filename"),
                    document_type_label(document.get("document_type")),
                    MEDIA_FILTERS.get(media, media),
                    build_document_search_text(document),
                    " ".join(context.title for context in chain_collections),
                    " ".join(context.reference for context in chain_collections),
                )
            ).casefold()
            chains.append(
                TraceabilityChain(
                    association_reference=association_reference,
                    association_label=association_label,
                    relationship_type=relationship_type,
                    relationship_label=relationship_label,
                    association_status="Active public association",
                    association_created_at=str(row.get("created_at") or ""),
                    association_url=f"/associations/{association_reference}",
                    record_reference=record_reference,
                    record_title=record_title,
                    record_type=str(row.get("record_trajectory") or ""),
                    record_status="Published",
                    record_url=f"/verify/{record_reference}",
                    document_id=str(row.get("document_id") or document.get("intake_id") or ""),
                    document_reference=document_reference,
                    document_title=document_title,
                    document_format=document_type_label(document.get("document_type")),
                    document_media=media,
                    document_status="Published",
                    document_date=str(document.get("document_date") or ""),
                    document_publication_date=str(document.get("publication_date") or ""),
                    document_institution=str(document.get("institution_source") or row.get("document_institution_source") or ""),
                    document_category=str(document.get("category") or row.get("document_category") or ""),
                    document_url=f"/documents/{document.get('intake_id') or row.get('document_id')}",
                    public_note=str(row.get("public_note") or ""),
                    collections=chain_collections,
                    search_text=search_text,
                )
            )
    finally:
        conn.close()
    return chains, collections_by_reference


def _all_public_transmissions(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    page = 1
    while True:
        result = trm.list_public_transmission_index(conn, page=page, page_size=100, root=intake_root())
        rows.extend(result["rows"])
        if int(result["page"]) >= int(result["page_count"]):
            break
        page += 1
    return rows


def _build_transmission_links(collections_by_reference: dict[str, dict[str, Any]]) -> list[TransmissionLink]:
    conn = records.get_db()
    try:
        _, memberships_by_member = _public_collection_contexts(conn)
        links: list[TransmissionLink] = []
        for item in _all_public_transmissions(conn):
            reference = str(item.get("public_reference") or "")
            if not reference:
                continue
            try:
                transmission = trm.get_public_transmission(conn, reference)
            except ValueError:
                continue
            attachments = trm.list_transmission_attachments(
                conn,
                transmission["id"],
                public_only=True,
                root=intake_root(),
            )
            transmission_contexts = _collection_context_for_chain(
                (("public_transmission", reference),),
                memberships_by_member,
            )
            for attachment in attachments:
                object_type = str(attachment.get("object_type") or "")
                object_reference = str(attachment.get("object_public_reference") or attachment.get("object_reference") or "")
                object_contexts = _collection_context_for_chain(
                    ((object_type, object_reference),),
                    memberships_by_member,
                )
                contexts = tuple(
                    sorted(
                        {context.membership_reference: context for context in (*transmission_contexts, *object_contexts)}.values(),
                        key=lambda context: (context.reference, context.membership_reference),
                    )
                )
                search_text = " ".join(
                    str(value or "")
                    for value in (
                        reference,
                        transmission.get("title"),
                        transmission.get("summary"),
                        transmission.get("sender"),
                        transmission.get("recipient"),
                        transmission.get("subject"),
                        transmission.get("covering_message"),
                        trm.method_label(transmission.get("communication_method")),
                        object_reference,
                        attachment.get("object_title"),
                        attachment.get("relationship_label"),
                        attachment.get("public_note"),
                        " ".join(context.title for context in contexts),
                        " ".join(context.reference for context in contexts),
                    )
                ).casefold()
                links.append(
                    TransmissionLink(
                        transmission_reference=reference,
                        transmission_title=str(transmission.get("title") or reference),
                        transmission_status=trm.status_label(transmission.get("publication_status")),
                        transmission_method=trm.method_label(transmission.get("communication_method")),
                        transmission_date=str(transmission.get("published_at") or transmission.get("transmission_date") or ""),
                        transmission_url=f"/transmissions/{reference}",
                        object_type=object_type,
                        object_type_label=trm.object_type_label(object_type),
                        object_reference=object_reference,
                        object_title=str(attachment.get("object_title") or object_reference),
                        object_status=str(attachment.get("object_status_label") or "Published"),
                        object_url=str(attachment.get("object_url") or "#"),
                        relationship_label=str(attachment.get("relationship_label") or "Transmitted object"),
                        public_note=str(attachment.get("public_note") or ""),
                        collection_contexts=contexts,
                        search_text=search_text,
                    )
                )
        return links
    finally:
        conn.close()


def _matches_search(chain: TraceabilityChain, search: str) -> bool:
    tokens = _tokens(search)
    if not tokens:
        return True
    searchable = " ".join(
        (
            chain.association_reference,
            chain.relationship_label,
            chain.record_reference,
            chain.record_title,
            chain.document_reference,
            chain.document_title,
            chain.document_institution,
            chain.document_category,
            chain.public_note,
            chain.search_text,
        )
    ).casefold()
    return all(token in searchable for token in tokens)


def _apply_filters(
    chains: list[TraceabilityChain],
    *,
    search: str,
    record: str,
    document: str,
    relationship_type: str,
    collection: str,
    institution: str,
    media: str,
    year: str,
    document_year: str,
) -> list[TraceabilityChain]:
    normalized_relationship = relationship_type if relationship_type in RELATIONSHIP_LABELS else ""
    normalized_media = media if media in MEDIA_FILTERS else ""
    normalized_year = year if len(str(year or "")) == 4 and str(year).isdigit() else ""
    normalized_document_year = document_year if len(str(document_year or "")) == 4 and str(document_year).isdigit() else ""
    result: list[TraceabilityChain] = []
    for chain in chains:
        if record and chain.record_reference != record:
            continue
        if document and chain.document_reference != document:
            continue
        if normalized_relationship and chain.relationship_type != normalized_relationship:
            continue
        if collection and collection not in {context.reference for context in chain.collections}:
            continue
        if institution and institution.casefold() not in chain.document_institution.casefold():
            continue
        if normalized_media and chain.document_media != normalized_media:
            continue
        if normalized_year and _year(chain.association_created_at or chain.document_publication_date) != normalized_year:
            continue
        if normalized_document_year and _year(chain.document_date) != normalized_document_year:
            continue
        if not _matches_search(chain, search):
            continue
        result.append(chain)
    return result


def _sort_chains(chains: list[TraceabilityChain], sort: str) -> list[TraceabilityChain]:
    normalized = sort if sort in SORTS else "newest"
    if normalized == "oldest":
        return sorted(chains, key=lambda item: (item.association_created_at, item.association_reference))
    if normalized == "record":
        return sorted(chains, key=lambda item: (item.record_reference.casefold(), item.association_reference))
    if normalized == "document":
        return sorted(chains, key=lambda item: (item.document_reference.casefold(), item.association_reference))
    if normalized == "association":
        return sorted(chains, key=lambda item: item.association_reference.casefold())
    return sorted(chains, key=lambda item: (item.association_created_at, item.association_reference), reverse=True)


def _query_string(filters: dict[str, str], *, page: int | None = None, page_size: int | None = None) -> str:
    params = {key: value for key, value in filters.items() if value and not (key == "sort" and value == "newest")}
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
        for size in PAGE_SIZE_OPTIONS
    )


def _filter_display_value(key: str, value: str, *, collections: dict[str, dict[str, Any]]) -> str:
    if key == "relationship_type":
        return RELATIONSHIP_LABELS.get(value, value)
    if key == "collection":
        return str(collections.get(value, {}).get("title") or value)
    if key == "media":
        return MEDIA_FILTERS.get(value, value)
    if key == "sort":
        return SORTS.get(value, value)
    return value


def _active_filter_summary(filters: dict[str, str], *, collections: dict[str, dict[str, Any]]) -> str:
    labels = (
        ("search", "Search"),
        ("record", "Canonical Record"),
        ("document", "Published Document"),
        ("relationship_type", "Relationship type"),
        ("collection", "Collection"),
        ("institution", "Institution / source"),
        ("media", "Media type"),
        ("year", "Publication year"),
        ("document_year", "Document year"),
        ("sort", "Sort"),
    )
    active = []
    for key, label in labels:
        value = filters.get(key)
        if not value or (key == "sort" and value == "newest"):
            continue
        active.append(
            f'<span class="traceability-filter-token"><strong>{escape(label)}:</strong> '
            f'{escape(_filter_display_value(key, value, collections=collections))}</span>'
        )
    return " ".join(active) if active else '<span class="traceability-filter-token">None</span>'


def _render_pagination(filters: dict[str, str], *, page: int, page_count: int, page_size: int, total: int, label: str) -> str:
    if total == 0 or page_count <= 1:
        return ""
    previous_link = ""
    next_link = ""
    if page > 1:
        previous_link = (
            f'<a class="traceability-page-link" aria-label="{escape(label)} previous page" href="/traceability?{escape(_query_string(filters, page=page - 1, page_size=page_size))}">'
            "Previous page</a>"
        )
    if page < page_count:
        next_link = (
            f'<a class="traceability-page-link" aria-label="{escape(label)} next page" href="/traceability?{escape(_query_string(filters, page=page + 1, page_size=page_size))}">'
            "Next page</a>"
        )
    return (
        f'<nav class="traceability-pagination" aria-label="{escape(label)} pagination">'
        f'<span aria-current="page">Page {page} of {page_count}</span>{previous_link}{next_link}</nav>'
    )


def _unique_counts(chains: list[TraceabilityChain]) -> dict[str, int]:
    return {
        "records": len({chain.record_reference for chain in chains}),
        "documents": len({chain.document_reference for chain in chains}),
        "associations": len({chain.association_reference for chain in chains}),
        "collections": len({context.reference for chain in chains for context in chain.collections}),
        "chains": len(chains),
    }


def _render_summary(counts: dict[str, int]) -> str:
    labels = (
        ("Canonical Records shown", "records"),
        ("Published Documents shown", "documents"),
        ("Governed Associations shown", "associations"),
        ("Governed Public Collections shown", "collections"),
        ("Public Transmissions shown", "transmissions"),
        ("Traceability chains shown", "chains"),
    )
    cards = "".join(
        f'<div class="traceability-count-card"><span>{escape(label)}</span><strong>{counts[key]}</strong></div>'
        for label, key in labels
    )
    return f'<section class="traceability-summary" aria-labelledby="traceability-summary-heading"><h2 id="traceability-summary-heading">Traceability Summary</h2><div class="traceability-counts">{cards}</div><p>One traceability result represents one governed Association chain.</p></section>'


def _render_legend() -> str:
    entries = (
        ("Canonical Record", "Owns its own identity, provenance, lifecycle, verification and public page."),
        ("Published Document", "Owns its own content identity, file integrity, provenance, lifecycle and public page."),
        ("Governed Association", "Declares a public relationship between independently governed objects."),
        ("Governed Public Collection", "Declares governed membership without absorbing the identity of its members."),
        ("Public Transmission", "Governs communication context without absorbing the identity of transmitted objects."),
        ("Declared Relationship", "A relationship explicitly governed by CDE. It is not inferred by the Traceability Map."),
    )
    items = "".join(f"<dt>{escape(term)}</dt><dd>{escape(definition)}</dd>" for term, definition in entries)
    return f'<section class="traceability-legend" aria-labelledby="traceability-legend-heading"><h2 id="traceability-legend-heading">Legend</h2><dl>{items}</dl></section>'


def _object_action(url: str, label: str, title: str, return_to: str) -> str:
    href = append_traceability_return(url, return_to)
    return f'<a href="{escape(href)}" aria-label="{escape(label)}: {escape(title)}">{escape(label)}</a>'


def _node(kind: str, reference: str, title: str, status: str, url: str, action_label: str, return_to: str, extra: str = "") -> str:
    fields = (
        f"<p class=\"traceability-reference\">{escape(reference)}</p>"
        f"<h3>{escape(title)}</h3>"
        f"<p>Status: {escape(status)}</p>"
        f"{extra}"
        f"<p class=\"traceability-actions\">{_object_action(url, action_label, title, return_to)}</p>"
    )
    return f'<article class="traceability-node traceability-node-{escape(kind)}">{object_type_badge(kind)}{fields}</article>'


def _render_collections(chain: TraceabilityChain, return_to: str) -> str:
    if not chain.collections:
        return '<p class="traceability-collection-empty">No public collection membership is declared for this chain in the current view.</p>'
    cards = []
    for context in chain.collections:
        cards.append(
            f"""<article class="traceability-collection-card">
              {object_type_badge("public_collection")}
              <h3>{escape(context.title)}</h3>
              <p class="traceability-reference">{escape(context.reference)}</p>
              <p>Public state: {escape(context.status)}</p>
              <p>Visible member count: {context.visible_member_count}</p>
              <p>Membership reference: {escape(context.membership_reference)}</p>
              <p>This collection declares governed membership and does not own, contain, or absorb the member object.</p>
              <p class="traceability-actions">{_object_action(context.url, OBJECT_ACTION_LABELS["public_collection"], context.title, return_to)}</p>
            </article>"""
        )
    return "".join(cards)


def _render_visual_chains(chains: list[TraceabilityChain], return_to: str, *, has_any_chain: bool, has_filters: bool, disconnected_message: str = "") -> str:
    if not chains:
        if disconnected_message:
            return f'<div class="traceability-empty" role="status"><h2>Public object has no declared relationship in the selected view</h2><p>{escape(disconnected_message)}</p><p><a class="traceability-clear-link" href="/traceability">Clear filters</a></p></div>'
        if has_any_chain and has_filters:
            return '<div class="traceability-empty" role="status"><h2>No public traceability relationships matched the current filters.</h2><p>Try broader filters. This does not imply that private, administrative, historical or unpublished relationships do not exist.</p><p><a class="traceability-clear-link" href="/traceability">Clear filters</a></p></div>'
        return '<div class="traceability-empty" role="status"><h2>No publicly eligible traceability relationships are currently available.</h2><p>The map displays only active public Associations whose linked objects are publicly eligible.</p></div>'
    rendered = []
    for chain in chains:
        record_node = _node(
            "canonical_record",
            chain.record_reference,
            chain.record_title,
            chain.record_status,
            chain.record_url,
            OBJECT_ACTION_LABELS["canonical_record"],
            return_to,
        )
        association_extra = f"<p>Relationship type: {escape(chain.relationship_label)}</p>{f'<p>{escape(chain.public_note)}</p>' if chain.public_note else ''}"
        association_node = _node(
            "record_document_association",
            chain.association_reference,
            chain.association_label,
            chain.association_status,
            chain.association_url,
            OBJECT_ACTION_LABELS["record_document_association"],
            return_to,
            association_extra,
        )
        document_extra = f"<p>Format: {escape(chain.document_format)}</p><p>Institution / source: {escape(_display(chain.document_institution))}</p>"
        document_node = _node(
            "published_document",
            chain.document_reference,
            chain.document_title,
            chain.document_status,
            chain.document_url,
            OBJECT_ACTION_LABELS["published_document"],
            return_to,
            document_extra,
        )
        rendered.append(
            f"""<article class="traceability-chain" aria-labelledby="chain-{escape(chain.association_reference)}">
              <h2 id="chain-{escape(chain.association_reference)}">Traceability chain {escape(chain.association_reference)}</h2>
              <div class="traceability-chain-flow">{record_node}<div class="traceability-link-label" aria-hidden="true">declared by</div>{association_node}<div class="traceability-link-label" aria-hidden="true">links to</div>{document_node}</div>
              <section class="traceability-collections" aria-label="Collection membership context"><h3>Governed Collection Membership</h3>{_render_collections(chain, return_to)}</section>
            </article>"""
        )
    return "".join(rendered)


def _render_structured_view(chains: list[TraceabilityChain], return_to: str) -> str:
    if not chains:
        return "<p>No traceability chains are available in the current view.</p>"
    rows = []
    for chain in chains:
        collection_links = " ".join(
            _object_action(context.url, OBJECT_ACTION_LABELS["public_collection"], context.title, return_to)
            for context in chain.collections
        ) or "No public collection membership declared for this chain."
        rows.append(
            f"""<tr>
              <td><a href="{escape(append_traceability_return(chain.record_url, return_to))}">{escape(chain.record_reference)}</a><br>{escape(chain.record_title)}</td>
              <td><a href="{escape(append_traceability_return(chain.association_url, return_to))}">{escape(chain.association_reference)}</a><br>{escape(chain.relationship_label)}</td>
              <td><a href="{escape(append_traceability_return(chain.document_url, return_to))}">{escape(chain.document_reference)}</a><br>{escape(chain.document_title)}</td>
              <td>{collection_links}</td>
            </tr>"""
        )
    return f'<div class="traceability-table-wrap"><table class="traceability-structured-table"><thead><tr><th>Canonical Record</th><th>Governed Association</th><th>Published Document</th><th>Governed Public Collections</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>'


def _matches_transmission_search(link: TransmissionLink, search: str) -> bool:
    tokens = _tokens(search)
    if not tokens:
        return True
    return all(token in link.search_text for token in tokens)


def _filter_transmission_links(
    links: list[TransmissionLink],
    *,
    search: str,
    collection: str,
    year: str,
) -> list[TransmissionLink]:
    normalized_year = year if len(str(year or "")) == 4 and str(year).isdigit() else ""
    result = []
    for link in links:
        if collection and collection not in {context.reference for context in link.collection_contexts}:
            continue
        if normalized_year and _year(link.transmission_date) != normalized_year:
            continue
        if not _matches_transmission_search(link, search):
            continue
        result.append(link)
    return result


def _render_transmission_links(links: list[TransmissionLink], return_to: str) -> str:
    if not links:
        return '<div class="traceability-empty" role="status"><h2>No public Transmission relationships matched the current view.</h2><p>Transmission traceability displays only Published transmissions and public transmitted objects.</p></div>'
    cards = []
    for link in links:
        transmission_node = _node(
            "public_transmission",
            link.transmission_reference,
            link.transmission_title,
            link.transmission_status,
            link.transmission_url,
            OBJECT_ACTION_LABELS["public_transmission"],
            return_to,
            f"<p>Method: {escape(link.transmission_method)}</p><p>Date: {escape(_date(link.transmission_date))}</p>",
        )
        object_node = _node(
            link.object_type,
            link.object_reference,
            link.object_title,
            link.object_status,
            link.object_url,
            OBJECT_ACTION_LABELS.get(link.object_type, "Open governed object"),
            return_to,
            f"<p>Declared relationship: {escape(link.relationship_label)}</p>{f'<p>{escape(link.public_note)}</p>' if link.public_note else ''}",
        )
        collection_context = ""
        if link.collection_contexts:
            collection_context = '<section class="traceability-collections" aria-label="Transmission collection context"><h3>Governed Collection Membership</h3>' + "".join(
                f'<article class="traceability-collection-card">{object_type_badge("public_collection")}<h3>{escape(context.title)}</h3><p class="traceability-reference">{escape(context.reference)}</p><p>This collection references the Transmission or transmitted object without owning or containing it.</p><p class="traceability-actions">{_object_action(context.url, OBJECT_ACTION_LABELS["public_collection"], context.title, return_to)}</p></article>'
                for context in link.collection_contexts
            ) + "</section>"
        cards.append(
            f"""<article class="traceability-chain transmission-traceability-chain" aria-labelledby="transmission-link-{escape(link.transmission_reference)}-{escape(link.object_reference)}">
              <h2 id="transmission-link-{escape(link.transmission_reference)}-{escape(link.object_reference)}">Transmission traceability {escape(link.transmission_reference)} to {escape(link.object_reference)}</h2>
              <div class="traceability-chain-flow transmission-chain-flow">{transmission_node}<div class="traceability-link-label" aria-hidden="true">communicates</div>{object_node}</div>
              {collection_context}
            </article>"""
        )
    return "".join(cards)


@router.get("/traceability", response_class=HTMLResponse)
def public_traceability_map(
    search: str | None = Query(None),
    record: str | None = Query(None),
    document: str | None = Query(None),
    relationship_type: str | None = Query(None),
    collection: str | None = Query(None),
    institution: str | None = Query(None),
    media: str | None = Query(None),
    year: str | None = Query(None),
    document_year: str | None = Query(None),
    sort: str | None = Query("newest"),
    page: int | str | None = Query(1),
    page_size: int | str | None = Query(25),
):
    all_chains, collections_by_reference = _build_traceability_chains()
    all_transmission_links = _build_transmission_links(collections_by_reference)
    filters = {
        "search": str(search or "").strip(),
        "record": str(record or "").strip(),
        "document": str(document or "").strip(),
        "relationship_type": str(relationship_type or "").strip(),
        "collection": str(collection or "").strip(),
        "institution": str(institution or "").strip(),
        "media": str(media or "").strip(),
        "year": str(year or "").strip(),
        "document_year": str(document_year or "").strip(),
        "sort": str(sort or "newest").strip(),
    }
    filtered = _apply_filters(
        all_chains,
        search=filters["search"],
        record=filters["record"],
        document=filters["document"],
        relationship_type=filters["relationship_type"],
        collection=filters["collection"],
        institution=filters["institution"],
        media=filters["media"],
        year=filters["year"],
        document_year=filters["document_year"],
    )
    sorted_chains = _sort_chains(filtered, filters["sort"])
    filtered_transmission_links = _filter_transmission_links(
        all_transmission_links,
        search=filters["search"],
        collection=filters["collection"],
        year=filters["year"],
    )
    normalized_page_size = _normalize_page_size(page_size)
    total = len(sorted_chains)
    page_count = max(1, (total + normalized_page_size - 1) // normalized_page_size)
    normalized_page = min(_normalize_page(page), page_count)
    start = (normalized_page - 1) * normalized_page_size
    page_chains = sorted_chains[start : start + normalized_page_size]
    current_traceability_path = f"/traceability?{_query_string(filters, page=normalized_page, page_size=normalized_page_size)}"
    if current_traceability_path == "/traceability?":
        current_traceability_path = "/traceability"

    record_options = {chain.record_reference: f"{chain.record_reference} — {chain.record_title}" for chain in all_chains}
    document_options = {chain.document_reference: f"{chain.document_reference} — {chain.document_title}" for chain in all_chains}
    collection_options = {
        reference: str(item.get("title") or reference)
        for reference, item in collections_by_reference.items()
    }
    institutions = sorted({chain.document_institution for chain in all_chains if chain.document_institution}, key=str.casefold)
    years = sorted({_year(chain.association_created_at or chain.document_publication_date) for chain in all_chains if _year(chain.association_created_at or chain.document_publication_date)}, reverse=True)
    document_years = sorted({_year(chain.document_date) for chain in all_chains if _year(chain.document_date)}, reverse=True)
    media_options = {key: label for key, label in MEDIA_FILTERS.items() if any(chain.document_media == key for chain in all_chains)}
    relationship_options = {key: label for key, label in RELATIONSHIP_LABELS.items() if any(chain.relationship_type == key for chain in all_chains)}
    has_active_filters = any(value and not (key == "sort" and value == "newest") for key, value in filters.items())
    active_filters_html = _active_filter_summary(filters, collections=collections_by_reference)
    counts = _unique_counts(sorted_chains)
    counts["transmissions"] = len({link.transmission_reference for link in filtered_transmission_links})
    pagination_top = _render_pagination(filters, page=normalized_page, page_count=page_count, page_size=normalized_page_size, total=total, label="Top traceability results")
    pagination_bottom = _render_pagination(filters, page=normalized_page, page_count=page_count, page_size=normalized_page_size, total=total, label="Bottom traceability results")
    page_summary = f"<p><strong>Page:</strong> {normalized_page} of {page_count}</p>" if total else ""
    disconnected_message = ""
    if filters["collection"] and filters["collection"] in collections_by_reference and not sorted_chains:
        disconnected_message = (
            "This public object currently has no declared public traceability "
            "relationships in the selected view. This does not imply that "
            "private, administrative, historical or unpublished relationships do not exist."
        )

    return HTMLResponse(
        content=f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Public Traceability Map | Civic Decision Engine</title><link rel="canonical" href="/traceability"><meta name="description" content="Public traceability interface showing declared CDE relationships between independently governed public objects."><style>*{{box-sizing:border-box}}body{{margin:0;background:#f7f7f4;color:#1f2933;font-family:system-ui,sans-serif}}main.traceability-map{{width:min(1220px,calc(100% - 32px));margin:32px auto 64px}}h1,h2,h3{{color:#143a52}}a{{color:#245d61}}a:focus,input:focus,select:focus,button:focus{{outline:3px solid #2e8b9a;outline-offset:2px}}{PUBLIC_NAVIGATION_CSS}.traceability-boundary,.traceability-current-view{{padding:14px 16px;border-left:4px solid #2e8b9a;background:#fff;line-height:1.55}}.traceability-boundary{{max-width:980px}}.traceability-current-view{{border-left-color:#143a52;margin:24px 0}}.traceability-counts{{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:12px}}.traceability-count-card,.traceability-node,.traceability-collection-card,.traceability-empty{{background:#fff;border:1px solid #d8d4ca;padding:14px;overflow-wrap:anywhere}}.traceability-count-card span{{display:block;color:#555}}.traceability-count-card strong{{display:block;font-size:1.55rem;color:#143a52}}.traceability-filters{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;background:#fff;border:1px solid #d8d4ca;padding:16px}}.traceability-filters label{{display:grid;gap:6px;color:#555;font:.78rem ui-monospace,monospace;text-transform:uppercase}}.traceability-filter-help{{font:.84rem system-ui,sans-serif;text-transform:none;color:#626262;line-height:1.4}}.traceability-filters input,.traceability-filters select{{width:100%;padding:9px;border:1px solid #c9c6bd;background:#fff;font:.92rem system-ui,sans-serif}}.traceability-filters button,.traceability-filters a,.traceability-clear-link,.traceability-actions a{{width:max-content;padding:9px 12px;border:0;background:#245d61;color:#fff;cursor:pointer;text-decoration:none;display:inline-block}}.traceability-filters a,.traceability-clear-link{{background:#fff;color:#245d61;border:1px solid #245d61}}.traceability-filter-token{{display:inline-block;margin:3px 6px 3px 0}}.traceability-legend dl{{display:grid;grid-template-columns:220px minmax(0,1fr);gap:8px 14px;background:#fff;border:1px solid #d8d4ca;padding:14px}}.traceability-legend dt{{font-weight:700;color:#143a52}}.traceability-legend dd{{margin:0}}.traceability-pagination{{display:flex;gap:16px;align-items:center;flex-wrap:wrap;margin:18px 0}}.traceability-chains{{display:grid;gap:18px}}.traceability-chain{{border-top:1px solid #d8d4ca;padding-top:18px}}.traceability-chain-flow{{display:grid;grid-template-columns:minmax(0,1fr) 110px minmax(0,1fr) 90px minmax(0,1fr);gap:12px;align-items:center}}.transmission-chain-flow{{grid-template-columns:minmax(0,1fr) 120px minmax(0,1fr)}}.traceability-link-label{{text-align:center;color:#555;font-weight:700}}.traceability-reference{{font:700 .88rem ui-monospace,monospace;color:#555}}.traceability-collections{{margin-top:14px}}.traceability-collection-list{{display:grid;gap:10px}}.traceability-structured-table{{width:100%;border-collapse:collapse;background:#fff}}.traceability-structured-table th,.traceability-structured-table td{{padding:10px;border:1px solid #e1dfd8;text-align:left;vertical-align:top;overflow-wrap:anywhere}}.traceability-structured-table th{{background:#143a52;color:#fff}}.traceability-table-wrap{{overflow-x:auto}}section{{margin:28px 0}}@media(max-width:980px){{.traceability-counts{{grid-template-columns:repeat(2,minmax(0,1fr))}}.traceability-filters{{grid-template-columns:repeat(2,minmax(0,1fr))}}.traceability-chain-flow,.transmission-chain-flow{{grid-template-columns:1fr}}.traceability-link-label::after{{content:" ↓"}}.traceability-link-label{{text-align:left}}}}@media(max-width:640px){{main.traceability-map{{width:min(100% - 24px,1220px);margin-top:24px}}.traceability-counts,.traceability-filters,.traceability-legend dl{{grid-template-columns:1fr}}.traceability-filters button,.traceability-filters a,.traceability-clear-link,.traceability-actions a{{width:100%;text-align:center}}}}</style></head><body><main class="traceability-map">{public_primary_navigation(active="traceability")}{public_breadcrumbs([("Home", "/"), ("Traceability", None)])}<h1>Public Traceability Map</h1><p class="traceability-boundary">{escape(BOUNDARY_TEXT)} {escape(DISCOVERY_BOUNDARY)} Traceability reveals declared relationships without erasing the identity of the governed objects involved.</p>{_render_summary(counts)}<section class="traceability-current-view" aria-live="polite" aria-labelledby="traceability-current-heading"><h2 id="traceability-current-heading">Current Traceability View</h2><p><strong>Active filters:</strong> {active_filters_html}</p>{page_summary}<p><a class="traceability-clear-link" href="/traceability">Clear filters</a></p></section><section aria-labelledby="traceability-filters-heading"><h2 id="traceability-filters-heading">Search and Filters</h2><form class="traceability-filters" method="get" action="/traceability"><label>Search<input name="search" value="{escape(filters['search'])}" placeholder="Search references, titles, notes, institutions, formats, or collection context" autocomplete="off"><span class="traceability-filter-help">Search covers public-safe declared relationship metadata only.</span></label><label>Canonical Record<select name="record">{_option_list(record_options, filters['record'], 'Any canonical record')}</select></label><label>Published Document<select name="document">{_option_list(document_options, filters['document'], 'Any published document')}</select></label><label>Relationship type<select name="relationship_type">{_option_list(relationship_options, filters['relationship_type'], 'Any relationship type')}</select></label><label>Collection<select name="collection">{_option_list(collection_options, filters['collection'], 'Any collection')}</select></label><label>Institution / source<select name="institution">{_option_list(institutions, filters['institution'], 'Any institution or source')}</select></label><label>Media type<select name="media">{_option_list(media_options, filters['media'], 'Any media type')}</select></label><label>Publication year<select name="year">{_option_list(years, filters['year'], 'Any publication year')}</select></label><label>Document year<select name="document_year">{_option_list(document_years, filters['document_year'], 'Any document year')}</select></label><label>Sort<select name="sort">{_option_list(SORTS, filters['sort'], 'Sort order')}</select></label><label>Page size<select name="page_size">{_page_size_options(normalized_page_size)}</select></label><button type="submit">Apply filters</button><a href="/traceability">Clear filters</a></form></section>{_render_legend()}<section aria-labelledby="traceability-visual-heading"><h2 id="traceability-visual-heading">Visual Traceability View</h2>{pagination_top}<div class="traceability-chains">{_render_visual_chains(page_chains, current_traceability_path, has_any_chain=bool(all_chains), has_filters=has_active_filters, disconnected_message=disconnected_message)}</div>{pagination_bottom}</section><section aria-labelledby="transmission-traceability-heading"><h2 id="transmission-traceability-heading">Transmission Traceability View</h2><p class="traceability-boundary">A Transmission governs communication context. It is rendered as its own governed node and does not contain the transmitted object.</p><div class="traceability-chains">{_render_transmission_links(filtered_transmission_links[:normalized_page_size], current_traceability_path)}</div></section><section aria-labelledby="traceability-structured-heading"><h2 id="traceability-structured-heading">Structured Accessible View</h2>{_render_structured_view(page_chains, current_traceability_path)}</section><p><a href="/archive">Back to Public Archive Explorer</a> · <a href="/records">Public Record Index</a> · <a href="/documents">Public Document Library</a> · <a href="/transmissions">Public Transmission Library</a> · <a href="/associations">Public Association Index</a> · <a href="/collections">Public Archive Collections</a></p></main></body></html>"""
    )
