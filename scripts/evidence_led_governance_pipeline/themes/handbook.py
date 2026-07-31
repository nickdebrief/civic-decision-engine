"""Default Evidence-Led Governance handbook theme."""

from __future__ import annotations

from .base import (
    AssetTheme,
    CalloutStyle,
    CalloutTheme,
    ChapterOpeningTheme,
    ColourTheme,
    FlowTheme,
    GeneratedSectionTheme,
    HeaderFooterTheme,
    HeadingStyle,
    HeadingTheme,
    PageTheme,
    Theme,
    TitlePageTheme,
    TypographyTheme,
    VolumePageTheme,
)


LETTER_PAGE = PageTheme(
    name="letter",
    width_inches=8.5,
    height_inches=11.0,
    orientation="portrait",
    margin_left_inches=1.0,
    margin_right_inches=1.0,
    margin_top_inches=0.85,
    margin_bottom_inches=0.8,
    header_distance_inches=0.35,
    footer_distance_inches=0.35,
    paragraph_width_inches=6.5,
    chapter_opening_space_before_pt=6.0,
)

TYPOGRAPHY = TypographyTheme(
    body_font="Aptos",
    display_font="Aptos",
    monospace_font="Aptos Mono",
    body_size_pt=11.0,
    body_space_after_pt=10.0,
    line_spacing=1.2,
    emphasis_size_pt=12.5,
    callout_label_size_pt=9.5,
    callout_title_size_pt=13.0,
    callout_body_size_pt=11.0,
    footer_size_pt=7.5,
)

COLOURS = ColourTheme(
    primary="154B5F",
    secondary="2E8B9A",
    accent="0F5F73",
    body_text="202020",
    muted_text="5A646E",
    rule="9FC4CC",
    hyperlink="0F5F73",
    page_background="FFFFFF",
)

HEADINGS = HeadingTheme(
    heading1=HeadingStyle(18.0, COLOURS.primary, 6.0, 14.0),
    heading2=HeadingStyle(14.0, COLOURS.primary, 16.0, 8.0),
    heading3=HeadingStyle(12.0, COLOURS.secondary, 12.0, 6.0, italic=True),
    body_role_colour=COLOURS.primary,
    emphasis=HeadingStyle(12.5, COLOURS.primary, 0.0, 14.0),
    bullet_left_indent_inches=0.28,
    bullet_hanging_indent_inches=0.18,
)

CALLOUTS = CalloutTheme(
    styles={
        "Callout": CalloutStyle("Callout", "EAF4F6", "9FC4CC", "2E8B9A", "154B5F", "5A646E", "202020"),
        "Governance Principle": CalloutStyle("Governance Principle", "EAF4F6", "71A9B4", "2E8B9A", "154B5F", "46606A", "202020", "GP"),
        "Research Finding": CalloutStyle("Research Finding", "EEF3F6", "91A9B5", "557C8D", "244B5B", "526671", "202020", "RF"),
        "Canonical Definition": CalloutStyle("Canonical Definition", "F2F5F7", "A5B5BE", "607D8B", "294E5B", "566871", "202020", "CD"),
        "Governance Architecture": CalloutStyle("Governance Architecture", "EDF5F3", "88ACA4", "3F8276", "21594F", "4F6C66", "202020", "GA"),
        "Research Methodology": CalloutStyle("Research Methodology", "F1F4F2", "9AAEA3", "668477", "355C4C", "5A6B63", "202020", "RM"),
    },
    margin_top_dxa=120,
    margin_bottom_dxa=120,
    margin_start_dxa=180,
    margin_end_dxa=180,
    border_size_eighth_points=8,
    label_space_after_pt=3.0,
    title_space_after_pt=6.0,
    body_space_after_pt=4.0,
    trailing_space_after_pt=2.0,
)

HANDBOOK_THEME = Theme(
    name="handbook",
    publication_name="Evidence-Led Governance",
    typography=TYPOGRAPHY,
    colours=COLOURS,
    page=LETTER_PAGE,
    headings=HEADINGS,
    callouts=CALLOUTS,
    flow=FlowTheme("vertical", 12.0, COLOURS.primary, 10.0, COLOURS.muted_text, "↓", 2.0, 2.0, 6.0),
    header_footer=HeaderFooterTheme(
        header_label="EVIDENCE-LED GOVERNANCE",
        footer_label="Structured · Traceable · Governed",
        colour=COLOURS.muted_text,
        header_alignment="right",
        footer_alignment="center",
        show_page_number=True,
        suppress_first_page_header=True,
        suppress_first_page_footer=True,
    ),
    title_page=TitlePageTheme(
        template="handbook",
        title_size_pt=26.0,
        subtitle_size_pt=14.0,
        author_size_pt=13.0,
        metadata_size_pt=11.0,
        title_colour=COLOURS.primary,
        subtitle_colour=COLOURS.secondary,
        metadata_colour=COLOURS.muted_text,
        space_before_pt=110.0,
        title_space_after_pt=6.0,
        subtitle_space_after_pt=40.0,
        author_space_after_pt=4.0,
        metadata_space_after_pt=4.0,
        trailing_space_after_pt=200.0,
        show_author=True,
        show_version=True,
        show_tagline=True,
        show_date=False,
    ),
    volume_page=VolumePageTheme(
        template="institutional",
        eyebrow_size_pt=13.0,
        title_size_pt=22.0,
        eyebrow_colour=COLOURS.muted_text,
        title_colour=COLOURS.primary,
        space_before_pt=150.0,
        eyebrow_space_after_pt=6.0,
        title_space_after_pt=200.0,
        page_break_before=True,
        page_break_after=True,
        suppress_header=False,
        suppress_footer=False,
    ),
    chapter_opening=ChapterOpeningTheme(
        template="standard",
        number_size_pt=18.0,
        title_size_pt=18.0,
        colour=COLOURS.primary,
        rule_colour=COLOURS.rule,
        space_before_pt=6.0,
        space_after_pt=14.0,
        page_break_before=True,
        show_decorative_rule=False,
    ),
    generated_sections=GeneratedSectionTheme(18.0, COLOURS.primary, 11.0, COLOURS.body_text, 10.0, False),
    assets=AssetTheme(),
)

# Compatibility names retained for Stage 1-3 callers.
HandbookTheme = Theme
THEME = HANDBOOK_THEME
