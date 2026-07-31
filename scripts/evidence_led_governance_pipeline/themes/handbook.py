"""Handbook theme tokens for the DOCX renderer."""

from __future__ import annotations

from dataclasses import dataclass

from docx.shared import RGBColor


@dataclass(frozen=True)
class HandbookTheme:
    body_font: str = "Aptos"
    page_width_inches: float = 8.5
    page_height_inches: float = 11.0
    margin_left_inches: float = 1.0
    margin_right_inches: float = 1.0
    margin_top_inches: float = 0.85
    margin_bottom_inches: float = 0.8
    header_distance_inches: float = 0.35
    footer_distance_inches: float = 0.35
    normal_size_pt: float = 11
    normal_space_after_pt: float = 10
    normal_line_spacing: float = 1.2
    heading1_size_pt: float = 18
    heading2_size_pt: float = 14
    heading3_size_pt: float = 12
    header_footer_size_pt: float = 7.5
    title_size_pt: float = 26
    subtitle_size_pt: float = 14
    author_size_pt: float = 13
    callout_label_size_pt: float = 9.5
    callout_title_size_pt: float = 13
    callout_body_size_pt: float = 11
    flow_node_size_pt: float = 12
    flow_connector_size_pt: float = 10
    title_space_before_pt: float = 110
    part_title_space_before_pt: float = 150
    part_title_space_after_pt: float = 200
    callout_cell_margin_top_dxa: int = 120
    callout_cell_margin_bottom_dxa: int = 120
    callout_cell_margin_start_dxa: int = 180
    callout_cell_margin_end_dxa: int = 180
    heading_teal: RGBColor = RGBColor(0x15, 0x4B, 0x5F)
    eyebrow_teal: RGBColor = RGBColor(0x2E, 0x8B, 0x9A)
    grey: RGBColor = RGBColor(0x5A, 0x64, 0x6E)
    darkgrey: RGBColor = RGBColor(0x46, 0x50, 0x5A)
    black: RGBColor = RGBColor(0x20, 0x20, 0x20)
    note_fill: str = "EAF4F6"
    table_header_fill: str = "DDECEF"
    rule_color: str = "9FC4CC"
    footer_default_tagline: str = "Structured · Traceable · Governed"


THEME = HandbookTheme()
