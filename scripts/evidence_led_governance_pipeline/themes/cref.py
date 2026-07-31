"""Civic Record Exchange Framework publication theme profile."""

from dataclasses import replace

from .base import ColourTheme
from .handbook import HANDBOOK_THEME


_COLOURS = ColourTheme(
    primary="263B5A",
    secondary="527A6A",
    accent="3F6F60",
    body_text="24282D",
    muted_text="626A72",
    rule="A7B8B1",
    hyperlink="315F72",
    page_background="FFFFFF",
)

CREF_THEME = replace(
    HANDBOOK_THEME,
    name="cref",
    publication_name="Civic Record Exchange Framework",
    colours=_COLOURS,
    headings=replace(
        HANDBOOK_THEME.headings,
        heading1=replace(HANDBOOK_THEME.headings.heading1, colour=_COLOURS.primary),
        heading2=replace(HANDBOOK_THEME.headings.heading2, colour=_COLOURS.primary),
        heading3=replace(HANDBOOK_THEME.headings.heading3, colour=_COLOURS.secondary),
        body_role_colour=_COLOURS.primary,
    ),
    header_footer=replace(HANDBOOK_THEME.header_footer, header_label="CIVIC RECORD EXCHANGE FRAMEWORK", colour=_COLOURS.muted_text),
    title_page=replace(HANDBOOK_THEME.title_page, title_colour=_COLOURS.primary, subtitle_colour=_COLOURS.secondary),
    volume_page=replace(HANDBOOK_THEME.volume_page, title_colour=_COLOURS.primary),
    chapter_opening=replace(HANDBOOK_THEME.chapter_opening, colour=_COLOURS.primary, rule_colour=_COLOURS.rule),
    generated_sections=replace(HANDBOOK_THEME.generated_sections, heading_colour=_COLOURS.primary),
)
