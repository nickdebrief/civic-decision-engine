from __future__ import annotations

from html import escape
from urllib.parse import parse_qsl, urlencode, urlsplit

from api.platform_identity import (
    PLATFORM_NAME,
    PLATFORM_SHORT_NAME,
    PLATFORM_TAGLINE,
    PLATFORM_VERSION_LABEL,
)

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
TRACEABILITY_QUERY_KEYS = {
    "search",
    "record",
    "document",
    "relationship_type",
    "collection",
    "institution",
    "media",
    "year",
    "document_year",
    "sort",
    "page",
    "page_size",
}

OBJECT_TYPE_LABELS = {
    "canonical_record": "Canonical Record",
    "published_document": "Published Document",
    "record_document_association": "Association",
    "public_collection": "Collection",
    "public_transmission": "Public Transmission",
}

PUBLIC_NAVIGATION_CSS = """
.public-site-header{display:grid;gap:10px;margin:0 0 20px}
.public-site-identity{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:10px 18px;padding:14px 0 0}
.public-site-wordmark{display:flex;align-items:center;gap:10px;color:#143a52;text-decoration:none;font-weight:800}
.public-site-shortmark{display:inline-flex;align-items:center;justify-content:center;width:42px;height:42px;border:2px solid #2e8b9a;border-radius:50%;font:800 .82rem ui-monospace,monospace;color:#2e8b9a;background:#fff;flex:0 0 auto}
.public-site-name{font-size:1.05rem;line-height:1.2}
.public-site-meta{display:flex;flex-wrap:wrap;gap:6px 10px;align-items:center;color:#555;font-size:.86rem}
.public-site-tagline{font-weight:650}
.public-site-version{font-family:ui-monospace,monospace;color:#143a52}
.public-primary-navigation{display:flex;flex-wrap:wrap;gap:8px 16px;align-items:center;padding:12px 0;border-bottom:1px solid #d8d4ca;margin:0 0 20px}
.public-primary-navigation a{color:#245d61;font-weight:650;text-decoration:none;border-bottom:2px solid transparent;padding:2px 0}
.public-primary-navigation a:hover,.public-primary-navigation a:focus{border-bottom-color:#245d61}
.public-primary-navigation a[aria-current="page"]{color:#143a52;border-bottom-color:#143a52}
.public-site-wordmark:focus-visible,.public-primary-navigation a:focus-visible,.public-footer a:focus-visible{outline:3px solid #8a6d1f;outline-offset:3px}
.public-footer{margin:40px 0 0;padding:18px 0 0;border-top:1px solid #d8d4ca;color:#555;font-size:.88rem}
.public-footer-inner{display:flex;flex-wrap:wrap;gap:10px 18px;justify-content:space-between;align-items:flex-start}
.public-footer-name{font-weight:800;color:#143a52}
.public-footer-version{font-family:ui-monospace,monospace;color:#143a52}
.public-footer-links{display:flex;flex-wrap:wrap;gap:8px 14px}
.public-footer a{color:#245d61;font-weight:650}
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
.object-type-badge-transmission{border-left-color:#9b4d2e}
@media(max-width:640px){.public-site-identity{align-items:flex-start}.public-site-meta{display:grid;gap:3px}.public-primary-navigation{gap:8px 12px}.public-breadcrumbs{font-size:.82rem}.object-type-badge{white-space:normal}}
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


def sanitize_traceability_return(value: object | None) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "/traceability"
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return "/traceability"
    if parsed.scheme or parsed.netloc or parsed.path != "/traceability":
        return "/traceability"
    params = [
        (key, item_value)
        for key, item_value in parse_qsl(parsed.query, keep_blank_values=False)
        if key in TRACEABILITY_QUERY_KEYS
    ]
    query = urlencode(params)
    return f"/traceability?{query}" if query else "/traceability"


def traceability_return_param(value: object | None) -> str:
    return urlencode({"return_to": sanitize_traceability_return(value)})


def append_traceability_return(url: str, return_to: object | None) -> str:
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}{traceability_return_param(return_to)}"


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
        "public_transmission": "transmission",
    }.get(object_type, "governed-object")
    return (
        f'<span class="object-type-badge object-type-badge-{escape(css_type)}" '
        f'aria-label="Object type: {escape(label)}"{legacy_label}>{escape(label)}</span>'
    )


def public_primary_navigation(active: str = "") -> str:
    links = (
        ("Home", "/"),
        ("Archive", "/archive"),
        ("Traceability", "/traceability"),
        ("Records", "/records"),
        ("Documents", "/documents"),
        ("Transmissions", "/transmissions"),
        ("Associations", "/associations"),
        ("Collections", "/collections"),
    )
    rendered = ""
    for label, href in links:
        current = ' aria-current="page"' if active == label.lower() else ""
        rendered += f'<a href="{href}"{current}>{escape(label)}</a>'
    identity = (
        '<div class="public-site-identity">'
        f'<a class="public-site-wordmark" href="/" aria-label="{escape(PLATFORM_NAME)} home">'
        f'<span class="public-site-shortmark" aria-hidden="true">{escape(PLATFORM_SHORT_NAME)}</span>'
        f'<span class="public-site-name">{escape(PLATFORM_NAME)}</span>'
        '</a>'
        '<div class="public-site-meta">'
        f'<span class="public-site-tagline">{escape(PLATFORM_TAGLINE)}</span>'
        f'<span class="public-site-version">Platform version {escape(PLATFORM_VERSION_LABEL)}</span>'
        '</div>'
        '</div>'
    )
    nav = f'<nav class="public-primary-navigation" aria-label="Primary public navigation">{rendered}</nav>'
    return f'<header class="public-site-header">{identity}{nav}</header>'


def public_footer() -> str:
    return (
        '<footer class="public-footer">'
        '<div class="public-footer-inner">'
        '<div>'
        f'<div class="public-footer-name">{escape(PLATFORM_NAME)}</div>'
        f'<div>{escape(PLATFORM_TAGLINE)}</div>'
        f'<div class="public-footer-version">Platform version {escape(PLATFORM_VERSION_LABEL)}</div>'
        '</div>'
        '<nav class="public-footer-links" aria-label="Public footer navigation">'
        '<a href="/archive">Archive</a>'
        '<a href="/traceability">Traceability</a>'
        '<a href="/documents">Documents</a>'
        '<a href="/records">Records</a>'
        '<a href="/transmissions">Transmissions</a>'
        '</nav>'
        '</div>'
        '</footer>'
    )


def public_breadcrumbs(items: list[tuple[str, str | None]]) -> str:
    rendered_items = []
    for index, (label, href) in enumerate(items):
        is_current = index == len(items) - 1 or not href
        if is_current:
            rendered_items.append(f'<li><span aria-current="page">{escape(label)}</span></li>')
        else:
            rendered_items.append(f'<li><a href="{escape(href)}">{escape(label)}</a></li>')
    return f'<nav class="public-breadcrumbs" aria-label="Breadcrumb"><ol>{"".join(rendered_items)}</ol></nav>'
