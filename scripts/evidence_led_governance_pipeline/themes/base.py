"""Data-only publication theme contracts and resolved configuration."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class TypographyTheme:
    body_font: str
    display_font: str
    monospace_font: str
    body_size_pt: float
    body_space_after_pt: float
    line_spacing: float
    emphasis_size_pt: float
    callout_label_size_pt: float
    callout_title_size_pt: float
    callout_body_size_pt: float
    footer_size_pt: float


@dataclass(frozen=True)
class ColourTheme:
    primary: str
    secondary: str
    accent: str
    body_text: str
    muted_text: str
    rule: str
    hyperlink: str
    page_background: str


@dataclass(frozen=True)
class PageTheme:
    name: str
    width_inches: float
    height_inches: float
    orientation: str
    margin_left_inches: float
    margin_right_inches: float
    margin_top_inches: float
    margin_bottom_inches: float
    header_distance_inches: float
    footer_distance_inches: float
    paragraph_width_inches: float
    chapter_opening_space_before_pt: float
    mirrored_margins: bool = False


@dataclass(frozen=True)
class HeadingStyle:
    size_pt: float
    colour: str
    space_before_pt: float
    space_after_pt: float
    bold: bool = True
    italic: bool = False


@dataclass(frozen=True)
class HeadingTheme:
    heading1: HeadingStyle
    heading2: HeadingStyle
    heading3: HeadingStyle
    body_role_colour: str
    emphasis: HeadingStyle
    bullet_left_indent_inches: float
    bullet_hanging_indent_inches: float


@dataclass(frozen=True)
class CalloutStyle:
    label: str
    fill: str
    border: str
    accent: str
    title_colour: str
    code_colour: str
    body_colour: str
    icon: str = ""


@dataclass(frozen=True)
class CalloutTheme:
    styles: Mapping[str, CalloutStyle]
    margin_top_dxa: int
    margin_bottom_dxa: int
    margin_start_dxa: int
    margin_end_dxa: int
    border_size_eighth_points: int
    label_space_after_pt: float
    title_space_after_pt: float
    body_space_after_pt: float
    trailing_space_after_pt: float


@dataclass(frozen=True)
class FlowTheme:
    default_direction: str
    node_size_pt: float
    node_colour: str
    connector_size_pt: float
    connector_colour: str
    arrow_glyph: str
    node_space_after_pt: float
    connector_space_after_pt: float
    arrow_space_after_pt: float
    panel_fill: str = ""
    panel_border: str = ""


@dataclass(frozen=True)
class HeaderFooterTheme:
    header_label: str
    footer_label: str
    colour: str
    header_alignment: str
    footer_alignment: str
    show_page_number: bool
    suppress_first_page_header: bool
    suppress_first_page_footer: bool


@dataclass(frozen=True)
class TitlePageTheme:
    template: str
    title_size_pt: float
    subtitle_size_pt: float
    author_size_pt: float
    metadata_size_pt: float
    title_colour: str
    subtitle_colour: str
    metadata_colour: str
    space_before_pt: float
    title_space_after_pt: float
    subtitle_space_after_pt: float
    author_space_after_pt: float
    metadata_space_after_pt: float
    trailing_space_after_pt: float
    show_author: bool
    show_version: bool
    show_tagline: bool
    show_date: bool


@dataclass(frozen=True)
class VolumePageTheme:
    template: str
    eyebrow_size_pt: float
    title_size_pt: float
    eyebrow_colour: str
    title_colour: str
    space_before_pt: float
    eyebrow_space_after_pt: float
    title_space_after_pt: float
    page_break_before: bool
    page_break_after: bool
    suppress_header: bool
    suppress_footer: bool


@dataclass(frozen=True)
class ChapterOpeningTheme:
    template: str
    number_size_pt: float
    title_size_pt: float
    colour: str
    rule_colour: str
    space_before_pt: float
    space_after_pt: float
    page_break_before: bool
    show_decorative_rule: bool


@dataclass(frozen=True)
class GeneratedSectionTheme:
    heading_size_pt: float
    heading_colour: str
    entry_size_pt: float
    entry_colour: str
    entry_space_after_pt: float
    page_break_before: bool


@dataclass(frozen=True)
class AssetTheme:
    emblem: str = ""
    cover_mark: str = ""
    divider_ornament: str = ""


@dataclass(frozen=True)
class Theme:
    name: str
    publication_name: str
    typography: TypographyTheme
    colours: ColourTheme
    page: PageTheme
    headings: HeadingTheme
    callouts: CalloutTheme
    flow: FlowTheme
    header_footer: HeaderFooterTheme
    title_page: TitlePageTheme
    volume_page: VolumePageTheme
    chapter_opening: ChapterOpeningTheme
    generated_sections: GeneratedSectionTheme
    assets: AssetTheme = field(default_factory=AssetTheme)


@dataclass(frozen=True)
class PublicationProfile:
    name: str
    hyperlinks_enabled: bool
    bookmarks_enabled: bool
    colour_callouts: bool
    generated_semantic_index: bool
    visible_hyperlink_style: bool
    archival_footer: bool
    margin_adjustment_inches: float = 0.0


@dataclass(frozen=True)
class ResolvedAsset:
    role: str
    path: Path
    required: bool


@dataclass(frozen=True)
class EffectiveTheme:
    theme: Theme
    publication_profile: PublicationProfile
    page: PageTheme
    title_page: TitlePageTheme
    volume_page: VolumePageTheme
    chapter_opening: ChapterOpeningTheme
    assets: Mapping[str, ResolvedAsset] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return self.theme.name


def with_page(theme: Theme, page: PageTheme) -> Theme:
    return replace(theme, page=page)
