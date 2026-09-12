"""Trusted public-origin policy for discovery metadata and public aliases."""
from __future__ import annotations

import os
import re
from urllib.parse import urlsplit


CANONICAL_PUBLIC_ORIGIN_ENV = "CDE_CANONICAL_PUBLIC_ORIGIN"
DEFAULT_CANONICAL_PUBLIC_ORIGIN = "https://civicdecisionengine.ie"
CANONICAL_ALIAS_HOSTS = frozenset(
    {
        "www.civicdecisionengine.ie",
        "civic-decision-engine-production.up.railway.app",
    }
)
_CANONICAL_TAG = re.compile(r"\s*<link\b[^>]*\brel=[\"']canonical[\"'][^>]*>", re.I)
_GOVERNED_REPORT_PUBLICATION_PATH = re.compile(
    r"/governed-reports/gr-[1-9][0-9]*\.json\Z"
)


def canonical_public_origin() -> str:
    """Return the configured, trusted HTTPS origin without a trailing slash."""
    value = os.getenv(CANONICAL_PUBLIC_ORIGIN_ENV, DEFAULT_CANONICAL_PUBLIC_ORIGIN)
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
    ):
        raise RuntimeError("canonical_public_origin_invalid")
    return f"https://{parsed.netloc}"


def canonical_url(path: str) -> str:
    if not path.startswith("/"):
        raise ValueError("canonical_path_invalid")
    return f"{canonical_public_origin()}{path}"


def is_public_indexable_path(path: str) -> bool:
    exact = {
        "/",
        "/archive",
        "/api/docs",
        "/associations",
        "/collections",
        "/conditions",
        "/conditions/map",
        "/determinations",
        "/documents",
        "/graph",
        "/patterns",
        "/records",
        "/stats",
        "/stats/timeline",
        "/traceability",
        "/transmissions",
    }
    if path in exact:
        return True
    if _GOVERNED_REPORT_PUBLICATION_PATH.fullmatch(path):
        return True
    return path.startswith(
        (
            "/conditions/",
            "/determinations/",
            "/documents/",
            "/records/",
            "/transmissions/",
            "/verify/",
        )
    )


def public_alias_redirect_location(host: str, path: str, query: bytes) -> str | None:
    """Return a fixed-origin redirect location for approved public aliases only."""
    normalized_host = host.lower().split(":", 1)[0]
    if normalized_host not in CANONICAL_ALIAS_HOSTS:
        return None
    location = canonical_url(path)
    if query:
        location += "?" + query.decode("latin-1")
    return location


def inject_canonical_link(html: bytes, path: str) -> bytes:
    """Replace any existing canonical tag with exactly one trusted canonical link."""
    text = html.decode("utf-8")
    text = _CANONICAL_TAG.sub("", text)
    head = re.search(r"<head(?:\s[^>]*)?>", text, re.I)
    if head is None:
        return html
    link = f'<link rel="canonical" href="{canonical_url(path)}">'
    return (text[: head.end()] + link + text[head.end() :]).encode("utf-8")
