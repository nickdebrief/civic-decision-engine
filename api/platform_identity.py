from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PlatformIdentity:
    name: str
    short_name: str
    version: str
    version_label: str
    tagline: str


PLATFORM_IDENTITY = PlatformIdentity(
    name="Civic Decision Engine",
    short_name="CDE",
    version="13.0",
    version_label="v13.0",
    tagline="Independent · Transparent · Traceable",
)

PLATFORM_NAME = PLATFORM_IDENTITY.name
PLATFORM_SHORT_NAME = PLATFORM_IDENTITY.short_name
PLATFORM_VERSION = PLATFORM_IDENTITY.version
PLATFORM_VERSION_LABEL = PLATFORM_IDENTITY.version_label
PLATFORM_TAGLINE = PLATFORM_IDENTITY.tagline


def platform_page_title(page_title: str | None = None) -> str:
    title = str(page_title or "").strip()
    return f"{title} — {PLATFORM_NAME}" if title else PLATFORM_NAME
