"""Native semantic HTML renderer for enriched publication models."""

from __future__ import annotations

import base64
import mimetypes
import shutil
from datetime import date
from html import escape
from pathlib import Path

from model import (
    Book,
    BulletList,
    Callout,
    Chapter,
    CrossReference,
    FlowDiagram,
    FrontMatter,
    HtmlOutputConfig,
    PageBreak,
    Paragraph,
    Section,
    Volume,
)
from themes.base import EffectiveTheme


def css_identifier(value: str) -> str:
    return "".join(character.lower() if character.isalnum() else "-" for character in value).strip("-")


def generate_css(effective: EffectiveTheme) -> str:
    """Translate resolved theme tokens into deterministic CSS."""
    theme = effective.theme
    typography = theme.typography
    colours = theme.colours
    page = effective.page
    lines = [
        ":root {",
        f"  --primary: #{colours.primary};",
        f"  --secondary: #{colours.secondary};",
        f"  --accent: #{colours.accent};",
        f"  --body: #{colours.body_text};",
        f"  --muted: #{colours.muted_text};",
        f"  --rule: #{colours.rule};",
        f"  --link: #{colours.hyperlink};",
        f"  --page: #{colours.page_background};",
        "}",
        "* { box-sizing: border-box; }",
        "html { scroll-behavior: smooth; }",
        f"body {{ margin: 0; color: var(--body); background: var(--page); font-family: '{typography.body_font}', serif; font-size: {typography.body_size_pt}pt; line-height: {typography.line_spacing}; }}",
        ".skip-link { position: absolute; left: -10000px; top: 0; padding: .6rem; background: var(--primary); color: white; z-index: 10; }",
        ".skip-link:focus { left: .5rem; top: .5rem; }",
        f".publication-header, .publication-footer, main {{ max-width: {page.paragraph_width_inches}in; margin-inline: auto; padding-inline: 1rem; }}",
        ".publication-header { padding-block: 1rem; border-bottom: 1px solid var(--rule); color: var(--muted); font-size: .82rem; }",
        ".publication-footer { padding-block: 1.5rem; border-top: 1px solid var(--rule); color: var(--muted); font-size: .82rem; }",
        ".title-page, .volume-page { min-height: 78vh; display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center; }",
        f".title-page h1 {{ margin: 0 0 {effective.title_page.title_space_after_pt}pt; color: #{effective.title_page.title_colour}; font-family: '{typography.display_font}', sans-serif; font-size: {effective.title_page.title_size_pt}pt; }}",
        f".title-page .subtitle {{ color: #{effective.title_page.subtitle_colour}; font-family: '{typography.display_font}', sans-serif; font-size: {effective.title_page.subtitle_size_pt}pt; font-style: italic; }}",
        f"h1 {{ color: #{theme.headings.heading1.colour}; font: 700 {theme.headings.heading1.size_pt}pt '{typography.display_font}', sans-serif; margin: {theme.headings.heading1.space_before_pt}pt 0 {theme.headings.heading1.space_after_pt}pt; }}",
        f"h2 {{ color: #{theme.headings.heading2.colour}; font: 700 {theme.headings.heading2.size_pt}pt '{typography.display_font}', sans-serif; margin: {theme.headings.heading2.space_before_pt}pt 0 {theme.headings.heading2.space_after_pt}pt; }}",
        f"h3 {{ color: #{theme.headings.heading3.colour}; font: 700 {theme.headings.heading3.size_pt}pt '{typography.display_font}', sans-serif; margin: {theme.headings.heading3.space_before_pt}pt 0 {theme.headings.heading3.space_after_pt}pt; }}",
        "p { margin: 0 0 .75rem; }",
        "a { color: var(--link); text-underline-offset: .15em; }",
        "a:focus-visible { outline: 3px solid var(--accent); outline-offset: 3px; }",
        "nav ul, .semantic-list { list-style: none; padding-left: 0; }",
        ".primary-nav ul { display: flex; flex-wrap: wrap; gap: .5rem 1rem; }",
        ".generated-section { border-top: 1px solid var(--rule); padding-top: 1rem; }",
        ".generated-section p { font-size: .95em; }",
        ".chapter, .front-matter, .generated-section { padding-block: 1.5rem; }",
        ".chapter-nav { display: flex; justify-content: space-between; gap: 1rem; border-top: 1px solid var(--rule); padding-top: 1rem; margin-top: 2rem; }",
        ".callout { margin: 1.2rem 0; padding: 1rem 1.1rem; border: 1px solid; border-left-width: 4px; }",
        ".callout-label { margin: 0 0 .25rem; font-size: .75rem; font-weight: 700; text-transform: uppercase; letter-spacing: .04em; }",
        ".callout h3 { margin-top: 0; }",
        ".flow { margin: 1.3rem auto; padding: 1rem; text-align: center; }",
        ".flow ol { list-style: none; padding: 0; margin: 0; }",
        ".flow li { font-weight: 700; margin: .3rem 0; }",
        ".flow .connector { display: block; color: var(--muted); font-size: .9em; font-style: italic; }",
        ".flow .arrow { display: block; color: var(--muted); }",
        ".back-to-top { text-align: right; font-size: .85rem; }",
        f"@page {{ size: {page.width_inches}in {page.height_inches}in; margin: {page.margin_top_inches}in {page.margin_right_inches}in {page.margin_bottom_inches}in {page.margin_left_inches}in; }}",
        "@media print { .skip-link, .primary-nav, .back-to-top { display: none; } .title-page, .volume-page, .chapter { break-before: page; } a { color: inherit; text-decoration: none; } }",
    ]
    for name in sorted(theme.callouts.styles):
        style = theme.callouts.styles[name]
        key = css_identifier(name)
        lines.append(f".callout-{key} {{ background: #{style.fill}; border-color: #{style.border}; border-left-color: #{style.accent}; }}")
        lines.append(f".callout-{key} .callout-label {{ color: #{style.code_colour}; }}")
        lines.append(f".callout-{key} h3 {{ color: #{style.title_colour}; }}")
    return "\n".join(lines) + "\n"


class HtmlRenderer:
    def __init__(self, effective: EffectiveTheme, config: HtmlOutputConfig) -> None:
        self.effective = effective
        self.config = config
        self._chapter_links: dict[str, tuple[Chapter | None, Chapter | None]] = {}

    def render(self, book: Book, out_path: Path) -> Path:
        chapters = [block for block in self._walk(book) if isinstance(block, Chapter)]
        for index, chapter in enumerate(chapters):
            self._chapter_links[chapter.identifier or ""] = (
                chapters[index - 1] if index else None,
                chapters[index + 1] if index + 1 < len(chapters) else None,
            )
        css = generate_css(self.effective)
        if self.config.single_file:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            html = self._document(book, f"<style>\n{css}</style>", out_path.parent)
            out_path.write_text(html, encoding="utf-8", newline="\n")
            return out_path

        out_path.mkdir(parents=True, exist_ok=True)
        (out_path / "assets").mkdir(exist_ok=True)
        (out_path / "styles.css").write_text(css, encoding="utf-8", newline="\n")
        for asset in self.effective.assets.values():
            shutil.copy2(asset.path, out_path / "assets" / asset.path.name)
        html = self._document(book, '<link rel="stylesheet" href="styles.css">', out_path)
        index = out_path / "index.html"
        index.write_text(html, encoding="utf-8", newline="\n")
        return index

    def _document(self, book: Book, stylesheet: str, asset_root: Path) -> str:
        language = escape(book.metadata.get("language", "en"), quote=True)
        body = "\n".join(self._render_block(block) for block in book.blocks if self._include_block(block))
        navigation = self._navigation(book) if self.config.include_navigation else ""
        emblem = self._emblem(asset_root)
        date_line = f'<p class="date">{date.today().isoformat()}</p>' if self.effective.title_page.show_date else ""
        author = f'<p class="author">{escape(book.author)}</p>' if self.effective.title_page.show_author else ""
        version = f'<p class="version">Version {escape(book.version)}</p>' if self.effective.title_page.show_version else ""
        tagline = f'<p class="tagline">{escape(book.tagline)}</p>' if self.effective.title_page.show_tagline and book.tagline else ""
        return f'''<!doctype html>
<html lang="{language}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="author" content="{escape(book.author, quote=True)}">
<meta name="description" content="{escape(book.subtitle, quote=True)}">
<meta name="publication-version" content="{escape(book.version, quote=True)}">
<title>{escape(book.title)}</title>
{stylesheet}
</head>
<body>
<a class="skip-link" href="#main-content">Skip to main content</a>
<header class="publication-header"><span>{escape(book.running_title)}</span></header>
<header class="title-page" id="top">
{emblem}<h1>{escape(book.title)}</h1>
<p class="subtitle">{escape(book.subtitle)}</p>
{author}{version}{tagline}{date_line}
</header>
{navigation}
<main id="main-content">
{body}
</main>
<footer class="publication-footer">{escape(book.tagline or self.effective.theme.header_footer.footer_label)} · Version {escape(book.version)}</footer>
</body>
</html>
'''

    def _emblem(self, asset_root: Path) -> str:
        asset = self.effective.assets.get("emblem")
        if asset is None:
            return ""
        alt = escape(f"{self.effective.theme.publication_name} emblem", quote=True)
        if self.config.single_file:
            mime = mimetypes.guess_type(asset.path.name)[0] or "application/octet-stream"
            encoded = base64.b64encode(asset.path.read_bytes()).decode("ascii")
            source = f"data:{mime};base64,{encoded}"
        else:
            source = f"assets/{escape(asset.path.name, quote=True)}"
        return f'<img class="publication-emblem" src="{source}" alt="{alt}">'

    def _navigation(self, book: Book) -> str:
        targets = []
        for block in book.generated_sections:
            if block.identifier:
                targets.append((block.identifier, block.title))
        for volume in book.volumes:
            if volume.identifier:
                targets.append((volume.identifier, f"Volume {volume.number}"))
        items = "".join(f'<li><a href="#{escape(identifier, quote=True)}">{escape(label)}</a></li>' for identifier, label in targets)
        return f'<nav class="primary-nav" aria-label="Publication navigation"><ul>{items}</ul></nav>'

    def _include_block(self, block) -> bool:
        return not (
            isinstance(block, Section)
            and block.generated
            and block.generation_type == "semantic_index"
            and not self.config.include_semantic_index
        )

    def _render_block(self, block) -> str:
        if isinstance(block, Volume):
            body = "\n".join(self._render_block(child) for child in block.blocks if self._include_block(child))
            return f'<section class="volume" id="{escape(block.identifier or "", quote=True)}"><header class="volume-page"><p>VOLUME {escape(block.number)}</p><h1>{escape(block.title)}</h1></header>{body}</section>'
        if isinstance(block, FrontMatter):
            body = "\n".join(self._render_block(child) for child in block.blocks)
            return f'<section class="front-matter" id="{escape(block.identifier or "", quote=True)}"><h1>{escape(block.title)}</h1>{body}{self._back_to_top()}</section>'
        if isinstance(block, Chapter):
            number = f"Chapter {block.number} — " if block.number is not None else ""
            body = "\n".join(self._render_block(child) for child in block.blocks)
            return f'<article class="chapter" id="{escape(block.identifier or "", quote=True)}"><h1>{escape(number + block.title)}</h1>{body}{self._chapter_navigation(block)}{self._back_to_top()}</article>'
        if isinstance(block, Section):
            level = min(max(block.level, 2), 3)
            css_class = "generated-section" if block.generated else "section"
            body = "\n".join(self._render_block(child) for child in block.blocks)
            return f'<section class="{css_class}" id="{escape(block.identifier or "", quote=True)}"><h{level}>{escape(block.heading_text)}</h{level}>{body}</section>'
        if isinstance(block, Paragraph):
            return self._paragraph(block)
        if isinstance(block, BulletList):
            items = "".join(f"<li>{escape(item.text)}</li>" for item in block.items)
            return f"<ul>{items}</ul>"
        if isinstance(block, Callout):
            key = css_identifier(block.callout_type)
            body = "\n".join(self._render_block(child) for child in block.body)
            label = block.label or self.effective.theme.callouts.styles.get(block.callout_type, self.effective.theme.callouts.styles["Callout"]).label
            if block.identifier:
                title_id = f"{block.identifier}-title"
                identity = f' id="{escape(block.identifier, quote=True)}" aria-labelledby="{escape(title_id, quote=True)}"'
                title_identity = f' id="{escape(title_id, quote=True)}"'
            else:
                identity = f' aria-label="{escape(label, quote=True)}"'
                title_identity = ""
            return f'<aside class="callout callout-{key}"{identity}><p class="callout-label">{escape(label)}</p><h3{title_identity}>{escape(block.title)}</h3>{body}</aside>'
        if isinstance(block, FlowDiagram):
            items = []
            for index, node in enumerate(block.nodes):
                connector = f'<span class="connector">{escape(node.connector)}</span>' if node.connector else ""
                arrow = f'<span class="arrow" aria-hidden="true">{escape(self.effective.theme.flow.arrow_glyph)}</span>' if index < len(block.nodes) - 1 else ""
                items.append(f"<li>{escape(node.label)}{connector}{arrow}</li>")
            return f'<figure class="flow flow-{escape(block.direction, quote=True)}" aria-label="Flow diagram"><ol>{"".join(items)}</ol></figure>'
        if isinstance(block, PageBreak):
            return '<div class="page-break" aria-hidden="true"></div>'
        raise TypeError(f"Unsupported HTML block: {type(block)!r}")

    def _paragraph(self, paragraph: Paragraph) -> str:
        content = escape(paragraph.text)
        if paragraph.inline_content:
            chunks = []
            for item in paragraph.inline_content:
                if isinstance(item, CrossReference) and item.target_identifier:
                    chunks.append(f'<a href="#{escape(item.target_identifier, quote=True)}">{escape(item.render_label)}</a>')
                else:
                    chunks.append(escape(item.render_label if isinstance(item, CrossReference) else str(item)))
            content = "".join(chunks)
        role = escape(paragraph.role, quote=True)
        identifier = f' id="{escape(paragraph.identifier, quote=True)}"' if paragraph.identifier else ""
        return f'<p class="paragraph-{role}"{identifier}>{content}</p>'

    def _chapter_navigation(self, chapter: Chapter) -> str:
        if not self.config.include_navigation:
            return ""
        previous, following = self._chapter_links.get(chapter.identifier or "", (None, None))
        links = []
        if previous and previous.identifier:
            links.append(f'<a rel="prev" href="#{escape(previous.identifier, quote=True)}">Previous: {escape(previous.title)}</a>')
        if following and following.identifier:
            links.append(f'<a rel="next" href="#{escape(following.identifier, quote=True)}">Next: {escape(following.title)}</a>')
        return f'<nav class="chapter-nav" aria-label="Chapter navigation">{"".join(links)}</nav>' if links else ""

    @staticmethod
    def _back_to_top() -> str:
        return '<p class="back-to-top"><a href="#top">Back to top</a></p>'

    @staticmethod
    def _walk(book: Book):
        stack = list(book.blocks)
        while stack:
            block = stack.pop(0)
            yield block
            stack[0:0] = list(getattr(block, "blocks", [])) + list(getattr(block, "body", []))
