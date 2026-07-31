"""Civic Decision Engine publication theme profile."""

from dataclasses import replace

from .base import ColourTheme
from .handbook import HANDBOOK_THEME


_COLOURS = ColourTheme(
    primary="12344D",
    secondary="287C87",
    accent="1D6F7A",
    body_text="1F2933",
    muted_text="5B6770",
    rule="9EB8C2",
    hyperlink="176B78",
    page_background="FFFFFF",
)

CDE_THEME = replace(
    HANDBOOK_THEME,
    name="cde",
    publication_name="Civic Decision Engine",
    colours=_COLOURS,
    headings=replace(
        HANDBOOK_THEME.headings,
        heading1=replace(HANDBOOK_THEME.headings.heading1, colour=_COLOURS.primary),
        heading2=replace(HANDBOOK_THEME.headings.heading2, colour=_COLOURS.primary),
        heading3=replace(HANDBOOK_THEME.headings.heading3, colour=_COLOURS.secondary),
        body_role_colour=_COLOURS.primary,
    ),
    header_footer=replace(HANDBOOK_THEME.header_footer, header_label="CIVIC DECISION ENGINE", colour=_COLOURS.muted_text),
    title_page=replace(HANDBOOK_THEME.title_page, title_colour=_COLOURS.primary, subtitle_colour=_COLOURS.secondary),
    volume_page=replace(HANDBOOK_THEME.volume_page, title_colour=_COLOURS.primary),
    chapter_opening=replace(HANDBOOK_THEME.chapter_opening, colour=_COLOURS.primary, rule_colour=_COLOURS.rule),
    generated_sections=replace(HANDBOOK_THEME.generated_sections, heading_colour=_COLOURS.primary),
)
