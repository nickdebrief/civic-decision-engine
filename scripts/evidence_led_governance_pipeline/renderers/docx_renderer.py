"""DOCX renderer for the Evidence-Led Governance semantic model."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from docx import Document
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt

from model import (
    Book,
    BulletList,
    Callout,
    Chapter,
    FlowDiagram,
    Paragraph,
    Section,
    Volume,
)
from themes.handbook import HandbookTheme, THEME


def set_repeat_table_header(row) -> None:
    tr_pr = row._tr.get_or_add_trPr()
    tbl_header = OxmlElement("w:tblHeader")
    tbl_header.set(qn("w:val"), "true")
    tr_pr.append(tbl_header)


def set_cell_shading(cell, fill: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = tc_pr.find(qn("w:shd"))
    if shd is None:
        shd = OxmlElement("w:shd")
        tc_pr.append(shd)
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)


def set_cell_border(cell, color: str, size: str = "8") -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    borders = tc_pr.find(qn("w:tcBorders"))
    if borders is None:
        borders = OxmlElement("w:tcBorders")
        tc_pr.append(borders)
    for side in ("top", "left", "bottom", "right"):
        node = borders.find(qn(f"w:{side}"))
        if node is None:
            node = OxmlElement(f"w:{side}")
            borders.append(node)
        node.set(qn("w:val"), "single")
        node.set(qn("w:sz"), size)
        node.set(qn("w:space"), "0")
        node.set(qn("w:color"), color)


def set_cell_margins(
    cell,
    *,
    top: int,
    bottom: int,
    start: int,
    end: int,
) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    margins = tc_pr.find(qn("w:tcMar"))
    if margins is None:
        margins = OxmlElement("w:tcMar")
        tc_pr.append(margins)
    for side, value in (("top", top), ("bottom", bottom), ("start", start), ("end", end)):
        node = margins.find(qn(f"w:{side}"))
        if node is None:
            node = OxmlElement(f"w:{side}")
            margins.append(node)
        node.set(qn("w:w"), str(value))
        node.set(qn("w:type"), "dxa")


def keep_with_next(paragraph) -> None:
    p_pr = paragraph._p.get_or_add_pPr()
    if p_pr.find(qn("w:keepNext")) is None:
        p_pr.append(OxmlElement("w:keepNext"))


def add_page_number(paragraph) -> None:
    run = paragraph.add_run()
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instruction = OxmlElement("w:instrText")
    instruction.set(qn("xml:space"), "preserve")
    instruction.text = "PAGE"
    separate = OxmlElement("w:fldChar")
    separate.set(qn("w:fldCharType"), "separate")
    text = OxmlElement("w:t")
    text.text = "1"
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    run._r.extend([begin, instruction, separate, text, end])


class DocxRenderer:
    def __init__(self, theme: HandbookTheme = THEME) -> None:
        self.theme = theme

    def render(self, book: Book, out_path: Path) -> Path:
        doc = Document()
        self.setup_styles(doc)
        self.add_header_footer(doc, book.running_title, book.tagline)
        self.title_page(doc, book)

        for block in book.blocks:
            self.render_block(doc, block)

        props = doc.core_properties
        props.title = book.title
        props.subject = book.subtitle
        props.author = book.author
        props.comments = f"Generated manuscript version {book.version}"

        out_path.parent.mkdir(parents=True, exist_ok=True)
        doc.save(out_path)
        Document(out_path)
        return out_path

    def setup_styles(self, doc) -> None:
        theme = self.theme
        normal = doc.styles["Normal"]
        normal.font.name = theme.body_font
        normal.font.size = Pt(theme.normal_size_pt)
        normal.font.color.rgb = theme.black
        normal.paragraph_format.space_after = Pt(theme.normal_space_after_pt)
        normal.paragraph_format.line_spacing = theme.normal_line_spacing
        normal.paragraph_format.widow_control = True

        heading_specs = {
            "Heading 1": (theme.heading1_size_pt, theme.heading_teal, 6, 14),
            "Heading 2": (theme.heading2_size_pt, theme.heading_teal, 16, 8),
            "Heading 3": (theme.heading3_size_pt, theme.eyebrow_teal, 12, 6),
        }
        for style_name, (size, colour, before, after) in heading_specs.items():
            style = doc.styles[style_name]
            style.font.name = theme.body_font
            style.font.size = Pt(size)
            style.font.bold = True
            style.font.color.rgb = colour
            style.paragraph_format.space_before = Pt(before)
            style.paragraph_format.space_after = Pt(after)
            style.paragraph_format.keep_with_next = True
            style.paragraph_format.widow_control = True
        doc.styles["Heading 3"].font.italic = True

        section = doc.sections[0]
        section.page_width = Inches(theme.page_width_inches)
        section.page_height = Inches(theme.page_height_inches)
        section.left_margin = Inches(theme.margin_left_inches)
        section.right_margin = Inches(theme.margin_right_inches)
        section.top_margin = Inches(theme.margin_top_inches)
        section.bottom_margin = Inches(theme.margin_bottom_inches)
        section.header_distance = Inches(theme.header_distance_inches)
        section.footer_distance = Inches(theme.footer_distance_inches)

    def add_header_footer(self, doc, running_title: str, tagline: str | None = None) -> None:
        theme = self.theme
        for section in doc.sections:
            hp = section.header.paragraphs[0]
            hp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            hr = hp.add_run(running_title)
            hr.font.name = theme.body_font
            hr.font.size = Pt(theme.header_footer_size_pt)
            hr.font.color.rgb = theme.grey

            fp = section.footer.paragraphs[0]
            fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
            footer_text = tagline or theme.footer_default_tagline
            fr = fp.add_run(f"{footer_text}  ·  ")
            fr.font.name = theme.body_font
            fr.font.size = Pt(theme.header_footer_size_pt)
            fr.font.color.rgb = theme.grey
            add_page_number(fp)

    def para(
        self,
        doc,
        text: str,
        *,
        align=None,
        italic=False,
        bold=False,
        size=None,
        color=None,
        space_after=None,
        style=None,
    ):
        theme = self.theme
        p = doc.add_paragraph(style=style)
        if align is not None:
            p.alignment = align
        run = p.add_run(text)
        run.font.name = theme.body_font
        run.italic = italic
        run.bold = bold
        if size is not None:
            run.font.size = Pt(size)
        if color is not None:
            run.font.color.rgb = color
        if space_after is not None:
            p.paragraph_format.space_after = Pt(space_after)
        return p

    def title_page(self, doc, book: Book) -> None:
        theme = self.theme
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(theme.title_space_before_pt)
        run = p.add_run(book.title)
        run.font.name = theme.body_font
        run.bold = True
        run.font.size = Pt(theme.title_size_pt)
        run.font.color.rgb = theme.heading_teal
        p.paragraph_format.space_after = Pt(6)

        p2 = doc.add_paragraph()
        p2.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r2 = p2.add_run(book.subtitle)
        r2.font.name = theme.body_font
        r2.italic = True
        r2.font.size = Pt(theme.subtitle_size_pt)
        r2.font.color.rgb = theme.eyebrow_teal
        p2.paragraph_format.space_after = Pt(40)

        self.para(doc, book.author, align=WD_ALIGN_PARAGRAPH.CENTER, bold=True, size=theme.author_size_pt, color=theme.heading_teal, space_after=4)
        self.para(doc, f"Version {book.version}", align=WD_ALIGN_PARAGRAPH.CENTER, size=11, color=theme.grey, space_after=4)
        if book.tagline:
            self.para(doc, book.tagline, align=WD_ALIGN_PARAGRAPH.CENTER, italic=True, size=11, color=theme.darkgrey, space_after=200)
        doc.add_page_break()

    def render_block(self, doc, block) -> None:
        if isinstance(block, Volume):
            self.part_title_page(doc, block.title, block.subtitle)
            for child in block.blocks:
                self.render_block(doc, child)
        elif isinstance(block, Chapter):
            heading_text = f"Chapter {block.number} — {block.title}" if block.number else block.title
            heading = doc.add_heading(heading_text, level=1)
            keep_with_next(heading)
            for child in block.blocks:
                self.render_block(doc, child)
        elif isinstance(block, Section):
            heading = doc.add_heading(block.title, level=min(max(block.level, 2), 3))
            keep_with_next(heading)
            for child in block.blocks:
                self.render_block(doc, child)
        elif isinstance(block, Paragraph):
            self.render_paragraph(doc, block)
        elif isinstance(block, BulletList):
            for item in block.items:
                self.para(doc, item, style="List Bullet")
        elif isinstance(block, FlowDiagram):
            self.flow_diagram(doc, block.pairs)
        elif isinstance(block, Callout):
            self.callout_box(doc, block.label, block.title, block.body)
        else:
            raise TypeError(f"Unsupported block: {type(block)!r}")

    def render_paragraph(self, doc, paragraph: Paragraph) -> None:
        theme = self.theme
        if paragraph.role == "pagebreak":
            doc.add_page_break()
        elif paragraph.role == "emphasis":
            self.para(doc, paragraph.text, align=WD_ALIGN_PARAGRAPH.CENTER, bold=True, color=theme.heading_teal, size=12.5, space_after=14)
        elif paragraph.role == "bold":
            self.para(doc, paragraph.text, bold=True, color=theme.heading_teal)
        else:
            self.para(doc, paragraph.text)

    def callout_box(self, doc, label: str, title: str, body_blocks: Sequence[Paragraph | BulletList]) -> None:
        theme = self.theme
        table = doc.add_table(rows=1, cols=1)
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        table.autofit = True

        cell = table.rows[0].cells[0]
        cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        set_cell_shading(cell, theme.note_fill)
        set_cell_border(cell, theme.rule_color)
        set_cell_margins(
            cell,
            top=theme.callout_cell_margin_top_dxa,
            bottom=theme.callout_cell_margin_bottom_dxa,
            start=theme.callout_cell_margin_start_dxa,
            end=theme.callout_cell_margin_end_dxa,
        )

        row_pr = table.rows[0]._tr.get_or_add_trPr()
        row_pr.append(OxmlElement("w:cantSplit"))

        cell.text = ""
        label_p = cell.paragraphs[0]
        label_p.paragraph_format.space_after = Pt(3)
        label_run = label_p.add_run(label.upper())
        label_run.font.name = theme.body_font
        label_run.bold = True
        label_run.font.size = Pt(theme.callout_label_size_pt)
        label_run.font.color.rgb = theme.grey

        title_p = cell.add_paragraph()
        title_p.paragraph_format.space_after = Pt(6)
        title_run = title_p.add_run(title)
        title_run.font.name = theme.body_font
        title_run.bold = True
        title_run.font.size = Pt(theme.callout_title_size_pt)
        title_run.font.color.rgb = theme.heading_teal

        for block in body_blocks:
            if isinstance(block, BulletList):
                for item in block.items:
                    p = cell.add_paragraph(style="List Bullet")
                    r = p.add_run(item)
                    r.font.name = theme.body_font
                    r.font.size = Pt(theme.callout_body_size_pt)
                    r.font.color.rgb = theme.black
                continue

            p = cell.add_paragraph()
            p.paragraph_format.space_after = Pt(4)
            r = p.add_run(block.text)
            r.font.name = theme.body_font
            r.font.size = Pt(theme.callout_body_size_pt)
            r.font.color.rgb = theme.black
            if block.role == "bold":
                r.bold = True
                r.font.color.rgb = theme.heading_teal

        doc.add_paragraph().paragraph_format.space_after = Pt(2)

    def flow_diagram(self, doc, pairs: Sequence[tuple[str, str | None]]) -> None:
        theme = self.theme
        for index, (node, connector) in enumerate(pairs):
            self.para(doc, node, align=WD_ALIGN_PARAGRAPH.CENTER, bold=True, color=theme.heading_teal, size=theme.flow_node_size_pt, space_after=2)
            if connector:
                self.para(doc, connector, align=WD_ALIGN_PARAGRAPH.CENTER, italic=True, color=theme.grey, size=theme.flow_connector_size_pt, space_after=2)
            if index < len(pairs) - 1:
                self.para(doc, "↓", align=WD_ALIGN_PARAGRAPH.CENTER, color=theme.grey, size=theme.flow_connector_size_pt, space_after=6)

    def part_title_page(self, doc, eyebrow: str, title: str) -> None:
        theme = self.theme
        p = self.para(doc, eyebrow, align=WD_ALIGN_PARAGRAPH.CENTER, bold=True, size=13, color=theme.grey, space_after=6)
        p.paragraph_format.space_before = Pt(theme.part_title_space_before_pt)
        self.para(doc, title, align=WD_ALIGN_PARAGRAPH.CENTER, bold=True, size=22, color=theme.heading_teal, space_after=theme.part_title_space_after_pt)
        doc.add_page_break()
