from __future__ import annotations

from html import escape
from urllib.parse import parse_qsl, urlencode, urlsplit

ARCHIVE_QUERY_KEYS = {
    "search",
    "type",
    "status",
    "year",
    "document_year",
    "record_type",
    "collection",
    "media",
    "sort",
    "page",
    "page_size",
}

OBJECT_TYPE_LABELS = {
    "canonical_record": "Canonical Record",
    "published_document": "Published Document",
    "record_document_association": "Association",
    "public_collection": "Collection",
}

PUBLIC_NAVIGATION_CSS = """
.public-primary-navigation{display:flex;flex-wrap:wrap;gap:8px 16px;align-items:center;padding:12px 0;border-bottom:1px solid #d8d4ca;margin:0 0 20px}
.public-primary-navigation a{color:#245d61;font-weight:650;text-decoration:none;border-bottom:2px solid transparent;padding:2px 0}
.public-primary-navigation a:hover,.public-primary-navigation a:focus{border-bottom-color:#245d61}
.public-primary-navigation a[aria-current="page"]{color:#143a52;border-bottom-color:#143a52}
.public-breadcrumbs{font-size:.88rem;margin:0 0 14px;color:#555}
.public-breadcrumbs ol{display:flex;flex-wrap:wrap;gap:6px;list-style:none;padding:0;margin:0}
.public-breadcrumbs li:not(:last-child)::after{content:"/";margin-left:6px;color:#8a867c}
.public-breadcrumbs a{color:#245d61}
.archive-return-link{display:inline-block;margin:0 0 14px;color:#245d61;font-weight:650}
.object-type-badge{display:inline-block;margin:.2rem 0;padding:4px 8px;border:1px solid #143a52;border-left-width:5px;background:#fff;color:#143a52;font:700 .72rem ui-monospace,monospace;letter-spacing:.03em;text-transform:uppercase;white-space:nowrap}
.object-type-badge-canonical-record{border-left-color:#143a52}
.object-type-badge-published-document{border-left-color:#2e8b9a}
.object-type-badge-association{border-left-color:#8a6d1f}
.object-type-badge-collection{border-left-color:#5b5f97}
@media(max-width:640px){.public-primary-navigation{gap:8px 12px}.public-breadcrumbs{font-size:.82rem}.object-type-badge{white-space:normal}}
"""


def sanitize_archive_return(value: object | None) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "/archive"
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return "/archive"
    if parsed.scheme or parsed.netloc or parsed.path != "/archive":
        return "/archive"
    params = [
        (key, item_value)
        for key, item_value in parse_qsl(parsed.query, keep_blank_values=False)
        if key in ARCHIVE_QUERY_KEYS
    ]
    query = urlencode(params)
    return f"/archive?{query}" if query else "/archive"


def archive_return_param(value: object | None) -> str:
    return urlencode({"return_to": sanitize_archive_return(value)})


def append_archive_return(url: str, return_to: object | None) -> str:
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}{archive_return_param(return_to)}"


def archive_back_link(return_to: object | None) -> str:
    return f'<a class="archive-return-link" href="{escape(sanitize_archive_return(return_to))}">Back to Archive Explorer</a>'


def object_type_badge(object_type: str) -> str:
    label = OBJECT_TYPE_LABELS.get(object_type, str(object_type or "Governed Object"))
    legacy_label = (
        ' data-legacy-label="Record-Document Association"'
        if object_type == "record_document_association"
        else ""
    )
    css_type = {
        "canonical_record": "canonical-record",
        "published_document": "published-document",
        "record_document_association": "association",
        "public_collection": "collection",
    }.get(object_type, "governed-object")
    return (
        f'<span class="object-type-badge object-type-badge-{escape(css_type)}" '
        f'aria-label="Object type: {escape(label)}"{legacy_label}>{escape(label)}</span>'
    )


def public_primary_navigation(active: str = "") -> str:
    links = (
        ("Home", "/"),
        ("Archive", "/archive"),
        ("Records", "/records"),
        ("Documents", "/documents"),
        ("Associations", "/associations"),
        ("Collections", "/collections"),
    )
    rendered = ""
    for label, href in links:
        current = ' aria-current="page"' if active == label.lower() else ""
        rendered += f'<a href="{href}"{current}>{escape(label)}</a>'
    return f'<nav class="public-primary-navigation" aria-label="Primary public navigation">{rendered}</nav>'


def public_breadcrumbs(items: list[tuple[str, str | None]]) -> str:
    rendered_items = []
    for index, (label, href) in enumerate(items):
        is_current = index == len(items) - 1 or not href
        if is_current:
            rendered_items.append(f'<li><span aria-current="page">{escape(label)}</span></li>')
        else:
            rendered_items.append(f'<li><a href="{escape(href)}">{escape(label)}</a></li>')
    return f'<nav class="public-breadcrumbs" aria-label="Breadcrumb"><ol>{"".join(rendered_items)}</ol></nav>'
