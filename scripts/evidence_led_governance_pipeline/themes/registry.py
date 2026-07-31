"""Safe registries for themes, publication profiles, and page profiles."""

from __future__ import annotations

from .base import PageTheme, PublicationProfile, Theme
from .cde import CDE_THEME
from .cref import CREF_THEME
from .handbook import HANDBOOK_THEME, LETTER_PAGE


THEMES: dict[str, Theme] = {
    "handbook": HANDBOOK_THEME,
    "cde": CDE_THEME,
    "cref": CREF_THEME,
}

PUBLICATION_PROFILES: dict[str, PublicationProfile] = {
    "digital": PublicationProfile("digital", True, True, True, True, True, False, 0.0),
    "print": PublicationProfile("print", True, True, False, True, False, False, 0.1),
    "archive": PublicationProfile("archive", True, True, False, True, False, True, 0.0),
}

PAGE_PROFILES: dict[str, PageTheme] = {
    "letter": LETTER_PAGE,
    "a4": PageTheme("a4", 8.2677, 11.6929, "portrait", 0.9, 0.9, 0.85, 0.8, 0.35, 0.35, 6.4677, 6.0),
    "book_6x9": PageTheme("book_6x9", 6.0, 9.0, "portrait", 0.75, 0.65, 0.7, 0.7, 0.3, 0.3, 4.6, 8.0),
}

TITLE_PAGE_TEMPLATES = {"institutional", "minimal", "handbook"}
VOLUME_PAGE_TEMPLATES = {"institutional", "minimal", "handbook"}
CHAPTER_OPENING_TEMPLATES = {"standard", "display", "compact"}


def get_theme(name: str) -> Theme:
    try:
        return THEMES[name.casefold()]
    except KeyError as exc:
        raise ValueError(f"Unknown publication theme: {name}") from exc


def get_publication_profile(name: str) -> PublicationProfile:
    try:
        return PUBLICATION_PROFILES[name.casefold()]
    except KeyError as exc:
        raise ValueError(f"Unknown publication profile: {name}") from exc


def get_page_profile(name: str) -> PageTheme:
    try:
        return PAGE_PROFILES[name.casefold()]
    except KeyError as exc:
        raise ValueError(f"Unknown page profile: {name}") from exc
