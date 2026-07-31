"""Resolve and validate an effective publication theme before rendering."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from pathlib import Path

from model import Manifest, ParserDiagnostic
from themes.base import EffectiveTheme, PageTheme, ResolvedAsset, Theme
from themes.registry import (
    CHAPTER_OPENING_TEMPLATES,
    TITLE_PAGE_TEMPLATES,
    VOLUME_PAGE_TEMPLATES,
    get_page_profile,
    get_publication_profile,
    get_theme,
)


HEX_COLOUR = re.compile(r"^[0-9A-Fa-f]{6}$")


@dataclass
class ThemeResolutionResult:
    effective_theme: EffectiveTheme
    diagnostics: list[ParserDiagnostic] = field(default_factory=list)


def _validate_colour(value: str, token: str) -> None:
    if not HEX_COLOUR.fullmatch(value):
        raise ValueError(f"Invalid theme colour {token}: {value!r}")


def _relative_luminance(value: str) -> float:
    channels = [int(value[index:index + 2], 16) / 255 for index in (0, 2, 4)]
    linear = [channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4 for channel in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast_ratio(foreground: str, background: str) -> float:
    light, dark = sorted((_relative_luminance(foreground), _relative_luminance(background)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def validate_theme(theme: Theme) -> None:
    required_strings = {
        "name": theme.name,
        "publication_name": theme.publication_name,
        "typography.body_font": theme.typography.body_font,
        "typography.display_font": theme.typography.display_font,
        "typography.monospace_font": theme.typography.monospace_font,
        "header_footer.header_label": theme.header_footer.header_label,
    }
    missing = [name for name, value in required_strings.items() if not value]
    if missing:
        raise ValueError(f"Missing required theme token(s): {', '.join(missing)}")

    for name, value in vars(theme.colours).items():
        _validate_colour(value, f"colours.{name}")
    for callout_name, style in theme.callouts.styles.items():
        for colour_name in ("fill", "border", "accent", "title_colour", "code_colour", "body_colour"):
            _validate_colour(getattr(style, colour_name), f"callouts.{callout_name}.{colour_name}")
    for token, value in (("body_text", theme.colours.body_text), ("hyperlink", theme.colours.hyperlink)):
        ratio = contrast_ratio(value, theme.colours.page_background)
        if ratio < 4.5:
            raise ValueError(f"Insufficient theme colour contrast for {token}: {ratio:.2f}:1")

    sizes = [
        theme.typography.body_size_pt,
        theme.typography.callout_body_size_pt,
        theme.headings.heading1.size_pt,
        theme.headings.heading2.size_pt,
        theme.headings.heading3.size_pt,
        theme.title_page.title_size_pt,
        theme.volume_page.title_size_pt,
        theme.chapter_opening.title_size_pt,
    ]
    if any(size <= 0 for size in sizes):
        raise ValueError("Theme font sizes must be positive")
    spacings = [
        theme.typography.body_space_after_pt,
        theme.title_page.space_before_pt,
        theme.volume_page.space_before_pt,
        theme.chapter_opening.space_before_pt,
    ]
    if any(value < 0 for value in spacings):
        raise ValueError("Theme spacing values cannot be negative")


def validate_page(page: PageTheme) -> None:
    dimensions = [page.width_inches, page.height_inches]
    margins = [page.margin_left_inches, page.margin_right_inches, page.margin_top_inches, page.margin_bottom_inches]
    if any(value <= 0 for value in dimensions):
        raise ValueError(f"Invalid page dimensions for profile {page.name}")
    if any(value < 0 for value in margins):
        raise ValueError(f"Invalid negative margin for profile {page.name}")
    if page.margin_left_inches + page.margin_right_inches >= page.width_inches:
        raise ValueError(f"Horizontal margins exceed page width for profile {page.name}")
    if page.margin_top_inches + page.margin_bottom_inches >= page.height_inches:
        raise ValueError(f"Vertical margins exceed page height for profile {page.name}")


def _resolve_assets(manifest: Manifest, assets_dir: Path) -> tuple[dict[str, ResolvedAsset], list[ParserDiagnostic]]:
    resolved: dict[str, ResolvedAsset] = {}
    diagnostics: list[ParserDiagnostic] = []
    root = assets_dir.resolve()
    for name, asset in manifest.assets.items():
        path = (root / asset.path).resolve()
        if root not in path.parents and path != root:
            raise ValueError(f"Asset path escapes assets directory: {asset.path}")
        if not path.exists():
            if asset.required:
                raise FileNotFoundError(f"Required publication asset is missing: {asset.path}")
            diagnostics.append(ParserDiagnostic(
                severity="WARNING",
                code="OPTIONAL_ASSET_MISSING",
                message=f"Optional publication asset is missing: {asset.path}",
                source_file=manifest.path,
            ))
            continue
        resolved[name] = ResolvedAsset(role=asset.role or name, path=path, required=asset.required)
    return resolved, diagnostics


def _chapter_template(theme: Theme, name: str, page_break_before: bool):
    base = replace(theme.chapter_opening, template=name, page_break_before=page_break_before)
    variants = {
        "standard": base,
        "display": replace(base, number_size_pt=16.0, title_size_pt=22.0, space_before_pt=28.0, show_decorative_rule=True),
        "compact": replace(base, number_size_pt=15.0, title_size_pt=16.0, space_before_pt=2.0, space_after_pt=9.0),
    }
    return variants[name]


def resolve_theme(manifest: Manifest, *, assets_dir: Path) -> ThemeResolutionResult:
    theme = get_theme(manifest.publication.theme)
    profile = get_publication_profile(manifest.output.profile)
    page = get_page_profile(manifest.layout.page_profile)
    validate_theme(theme)

    if manifest.title_page.template not in TITLE_PAGE_TEMPLATES:
        raise ValueError(f"Unknown title-page template: {manifest.title_page.template}")
    if manifest.volume_page.template not in VOLUME_PAGE_TEMPLATES:
        raise ValueError(f"Unknown volume-page template: {manifest.volume_page.template}")
    if manifest.chapter_opening.template not in CHAPTER_OPENING_TEMPLATES:
        raise ValueError(f"Unknown chapter-opening template: {manifest.chapter_opening.template}")

    adjustment = profile.margin_adjustment_inches
    page = replace(
        page,
        margin_left_inches=page.margin_left_inches + adjustment,
        margin_right_inches=page.margin_right_inches + adjustment,
    )
    validate_page(page)

    title_page = replace(
        theme.title_page,
        template=manifest.title_page.template,
        show_author=manifest.title_page.show_author,
        show_version=manifest.title_page.show_version,
        show_tagline=manifest.title_page.show_tagline,
        show_date=manifest.title_page.show_date,
    )
    volume_page = replace(
        theme.volume_page,
        template=manifest.volume_page.template,
        page_break_before=manifest.layout.volume_starts_on_new_page,
        suppress_header=manifest.volume_page.suppress_header,
        suppress_footer=manifest.volume_page.suppress_footer,
    )
    chapter_opening = _chapter_template(
        theme,
        manifest.chapter_opening.template,
        manifest.layout.chapter_starts_on_new_page,
    )
    header_footer = replace(
        theme.header_footer,
        suppress_first_page_header=manifest.layout.suppress_header_on_title_page,
        suppress_first_page_footer=manifest.layout.suppress_footer_on_title_page,
    )
    if profile.archival_footer:
        header_footer = replace(header_footer, footer_label=f"{header_footer.footer_label} · Archival edition")

    effective_base = replace(
        theme,
        page=page,
        title_page=title_page,
        volume_page=volume_page,
        chapter_opening=chapter_opening,
        header_footer=header_footer,
    )
    assets, diagnostics = _resolve_assets(manifest, assets_dir)
    return ThemeResolutionResult(
        effective_theme=EffectiveTheme(
            theme=effective_base,
            publication_profile=profile,
            page=page,
            title_page=title_page,
            volume_page=volume_page,
            chapter_opening=chapter_opening,
            assets=assets,
        ),
        diagnostics=diagnostics,
    )
