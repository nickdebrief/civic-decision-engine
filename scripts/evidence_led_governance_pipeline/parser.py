"""Semantic parser for Evidence-Led Governance chapter source files."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional, Sequence

from model import (
    Book,
    BulletItem,
    BulletList,
    Callout,
    CanonicalDefinition,
    Chapter,
    ContentBlock,
    CrossReference,
    FlowDiagram,
    FlowNode,
    FrontMatter,
    GovernanceArchitecture,
    GovernancePrinciple,
    PageBreak,
    Paragraph,
    ParserDiagnostic,
    PartTitle,
    ResearchFinding,
    ResearchMethodology,
    Section,
    Subsection,
    Volume,
)


CODE_LABELS = {
    "GP": "Governance Principle",
    "RF": "Research Finding",
    "CD": "Canonical Definition",
    "GA": "Governance Architecture",
    "RM": "Research Methodology",
}

CALLOUT_TYPES = {
    "Governance Principle": GovernancePrinciple,
    "Research Finding": ResearchFinding,
    "Canonical Definition": CanonicalDefinition,
    "Governance Architecture": GovernanceArchitecture,
    "Research Methodology": ResearchMethodology,
}

SEPARATOR_LINES = {"⸻", "—", "---"}
STRUCTURAL_LABELS = set(CALLOUT_TYPES)
REF_PATTERN = re.compile(r"\[\[REF:\s*([^|\]]+?)(?:\s*\|\s*([^\]]+?))?\s*\]\]")


def _next_nonempty_index(lines: Sequence[str], start: int) -> Optional[int]:
    for index in range(start, len(lines)):
        if lines[index].strip():
            return index
    return None


def _provenance_kwargs(filepath: Path, start: int, end: int | None = None) -> dict:
    return {
        "source_file": filepath,
        "source_line_start": start,
        "source_line_end": end or start,
    }


def _canonical_label(label: str, code: str | None = None) -> str:
    cleaned = re.sub(r"\s+No\.\s+\d+$", "", label.strip(), flags=re.IGNORECASE)
    if cleaned in CALLOUT_TYPES:
        return cleaned
    if code:
        return CODE_LABELS.get(code.split("-", 1)[0].upper(), cleaned)
    return cleaned


def parse_code_title(line: str) -> tuple[str, str, str] | None:
    """Return ``(label, title, code)`` for GP/RF/CD/GA/RM lines."""
    match = re.match(
        r"^(GP|RF|CD|GA|RM)-(\d+)(?:\s*[—-]\s*|\s+)?(.*)$",
        line.strip(),
        flags=re.IGNORECASE,
    )
    if not match:
        return None

    code_prefix = match.group(1).upper()
    number = match.group(2)
    title_text = match.group(3).strip()
    code = f"{code_prefix}-{number}"
    title = code
    if title_text:
        title += f" — {title_text}"
    return CODE_LABELS[code_prefix], title, code


def parse_chapter_heading(text: str) -> tuple[Optional[int], str]:
    match = re.match(r"^Chapter\s+(\d+)\s*[—-]\s*(.+)$", text, flags=re.IGNORECASE)
    if match:
        return int(match.group(1)), match.group(2).strip()
    match = re.match(r"^Chapter\s+(\d+)$", text, flags=re.IGNORECASE)
    if match:
        return int(match.group(1)), text.strip()
    return None, text.strip()


def parse_section_heading(text: str) -> tuple[Optional[str], str]:
    match = re.match(r"^(\d+\.\d+(?:\.\d+)?)\s+(.+)$", text.strip())
    if match:
        return match.group(1), match.group(2).strip()
    return None, text.strip()


def parse_inline_references(
    text: str,
    *,
    source_file: Path,
    source_line_start: int,
    source_line_end: int,
) -> list[str | CrossReference]:
    inline: list[str | CrossReference] = []
    last = 0
    for match in REF_PATTERN.finditer(text):
        if match.start() > last:
            inline.append(text[last : match.start()])
        inline.append(
            CrossReference(
                target_query=match.group(1).strip(),
                display_label=match.group(2).strip() if match.group(2) else None,
                source_file=source_file,
                source_line_start=source_line_start,
                source_line_end=source_line_end,
            )
        )
        last = match.end()
    if last < len(text):
        inline.append(text[last:])
    return inline


def normalise_structure(lines: Sequence[str]) -> list[str]:
    """Compatibility helper retained for older imports.

    Stage 2 parses semantic structures directly so source provenance is not
    lost. Older wrapper scripts imported this helper, so it remains as a
    non-rendering source normaliser with the Stage 1 behaviour.
    """
    output: list[str] = []
    index = 0
    block_end: str | None = None

    while index < len(lines):
        raw = lines[index]
        stripped = raw.strip()

        if block_end is not None:
            output.append(raw)
            if stripped == block_end:
                block_end = None
            index += 1
            continue

        if stripped.startswith("[[CALLOUT:"):
            output.append(raw)
            block_end = "[[/CALLOUT]]"
            index += 1
            continue

        if stripped == "[[FLOW]]":
            output.append(raw)
            block_end = "[[/FLOW]]"
            index += 1
            continue

        if re.fullmatch(r"Volume\s+[IVXLC]+", stripped, flags=re.IGNORECASE):
            next_index = _next_nonempty_index(lines, index + 1)
            if next_index is not None and re.fullmatch(
                r"Chapter\s+\d+", lines[next_index].strip(), flags=re.IGNORECASE
            ):
                index += 1
                continue

        chapter_match = re.fullmatch(r"Chapter\s+(\d+)", stripped, flags=re.IGNORECASE)
        if chapter_match:
            title_index = _next_nonempty_index(lines, index + 1)
            if title_index is not None:
                title = lines[title_index].strip()
                if (
                    title
                    and title not in SEPARATOR_LINES
                    and not title.startswith("[[")
                    and not title.startswith("#")
                    and parse_code_title(title) is None
                ):
                    output.append(f"# Chapter {chapter_match.group(1)} — {title}")
                    index = title_index + 1
                    continue

        if re.match(r"^\d+\.\d+(?:\.\d+)?\s+\S", stripped):
            output.append(f"## {stripped}")
            index += 1
            continue

        if stripped.casefold() == "chapter synthesis":
            output.append("## Chapter Synthesis")
            index += 1
            continue

        if stripped in STRUCTURAL_LABELS:
            next_index = _next_nonempty_index(lines, index + 1)
            if next_index is not None and parse_code_title(lines[next_index].strip()):
                index += 1
                continue

        output.append(raw)
        index += 1

    return output


class Parser:
    def __init__(self) -> None:
        self.diagnostics: list[ParserDiagnostic] = []

    def diagnostic(
        self,
        severity: str,
        code: str,
        message: str,
        source_file: Path | None = None,
        line: int | None = None,
    ) -> None:
        self.diagnostics.append(
            ParserDiagnostic(
                severity=severity,  # type: ignore[arg-type]
                code=code,
                message=message,
                source_file=source_file,
                source_line_start=line,
                source_line_end=line,
            )
        )

    def parse_files(
        self,
        chapter_files: Sequence[Path],
        *,
        title: str,
        subtitle: str,
        author: str,
        running_title: str,
        tagline: str,
        version: str,
    ) -> Book:
        book = Book(
            title=title,
            subtitle=subtitle,
            author=author,
            running_title=running_title,
            tagline=tagline,
            version=version,
            source_files=list(chapter_files),
        )
        current_volume: Volume | None = None

        for chapter_file in chapter_files:
            parsed_blocks = self.parse_chapter_file(chapter_file)
            for block in parsed_blocks:
                if isinstance(block, PartTitle):
                    current_volume = Volume(
                        number=block.eyebrow.replace("VOLUME", "").strip(),
                        title=block.title,
                        blocks=[],
                        source_file=block.source_file,
                        source_line_start=block.source_line_start,
                        source_line_end=block.source_line_end,
                    )
                    book.volumes.append(current_volume)
                    book.blocks.append(current_volume)
                    continue

                if isinstance(block, Chapter) and block.number is None and block.title in {
                    "Preface",
                    "Statement of Method",
                }:
                    front = FrontMatter(
                        title=block.title,
                        blocks=block.blocks,
                        source_file=block.source_file or block.source_path,
                        source_line_start=block.source_line_start,
                        source_line_end=block.source_line_end,
                    )
                    book.front_matter.append(front)
                    book.blocks.append(front)
                    continue

                if current_volume is not None:
                    if isinstance(block, Chapter):
                        current_volume.chapters.append(block)
                    else:
                        current_volume.introduction.append(block)
                    current_volume.blocks.append(block)
                    continue

                if isinstance(block, Chapter):
                    book.standalone_chapters.append(block)
                book.blocks.append(block)

        book.diagnostics = list(self.diagnostics)
        return book

    def parse_chapter_file(self, filepath: Path) -> list[Volume | Chapter | Section | ContentBlock]:
        raw_lines = filepath.read_text(encoding="utf-8").splitlines()
        root_blocks: list[Volume | Chapter | Section | ContentBlock] = []
        current_chapter: Chapter | None = None
        current_section: Section | None = None
        paragraph_start: int | None = None
        body_buffer: list[tuple[int, str]] = []
        index = 0

        def append_block(block: Volume | Chapter | Section | ContentBlock) -> None:
            nonlocal current_chapter, current_section
            if isinstance(block, Chapter):
                root_blocks.append(block)
                current_chapter = block
                current_section = None
            elif isinstance(block, Section):
                if current_chapter is not None:
                    current_chapter.blocks.append(block)
                    current_chapter.sections.append(block)
                else:
                    root_blocks.append(block)
                current_section = block
            elif isinstance(block, Volume):
                root_blocks.append(block)
                current_chapter = None
                current_section = None
            else:
                if current_section is not None:
                    current_section.blocks.append(block)
                elif current_chapter is not None:
                    current_chapter.blocks.append(block)
                else:
                    root_blocks.append(block)

        def flush_body() -> None:
            nonlocal paragraph_start
            if not body_buffer:
                return
            start = body_buffer[0][0]
            end = body_buffer[-1][0]
            bullet_items: list[BulletItem] = []
            paragraph_lines: list[str] = []

            def flush_paragraph_lines() -> None:
                if not paragraph_lines:
                    return
                text = " ".join(line.strip() for line in paragraph_lines if line.strip())
                paragraph_lines.clear()
                if not text:
                    return
                bold_match = re.fullmatch(r"\*\*(.+?)\*\*", text)
                role = "bold" if bold_match else "body"
                append_block(
                    Paragraph(
                        text=bold_match.group(1) if bold_match else text,
                        role=role,
                        inline_content=parse_inline_references(
                            bold_match.group(1) if bold_match else text,
                            source_file=filepath,
                            source_line_start=start,
                            source_line_end=end,
                        ),
                        **_provenance_kwargs(filepath, start, end),
                    )
                )

            for line_no, raw in body_buffer:
                stripped = raw.strip()
                bullet_match = re.match(r"^(?:[-*])\s+(.+)$", stripped)
                if bullet_match:
                    flush_paragraph_lines()
                    bullet_items.append(
                        BulletItem(
                            text=bullet_match.group(1),
                            **_provenance_kwargs(filepath, line_no),
                        )
                    )
                    continue
                if bullet_items:
                    append_block(
                        BulletList(
                            items=bullet_items,
                            **_provenance_kwargs(
                                filepath,
                                bullet_items[0].source_line_start or start,
                                bullet_items[-1].source_line_end or end,
                            ),
                        )
                    )
                    bullet_items = []
                paragraph_lines.append(raw)

            if bullet_items:
                append_block(
                    BulletList(
                        items=bullet_items,
                        **_provenance_kwargs(
                            filepath,
                            bullet_items[0].source_line_start or start,
                            bullet_items[-1].source_line_end or end,
                        ),
                    )
                )
            flush_paragraph_lines()
            body_buffer.clear()
            paragraph_start = None

        while index < len(raw_lines):
            line_no = index + 1
            raw_line = raw_lines[index]
            stripped = raw_line.strip()

            if not stripped:
                flush_body()
                index += 1
                continue

            if stripped in SEPARATOR_LINES:
                flush_body()
                index += 1
                continue

            if re.fullmatch(r"Volume\s+[IVXLC]+", stripped, flags=re.IGNORECASE):
                next_index = _next_nonempty_index(raw_lines, index + 1)
                if next_index is not None and re.fullmatch(
                    r"Chapter\s+\d+", raw_lines[next_index].strip(), flags=re.IGNORECASE
                ):
                    index += 1
                    continue

            chapter_match = re.fullmatch(r"Chapter\s+(\d+)", stripped, flags=re.IGNORECASE)
            if chapter_match:
                title_index = _next_nonempty_index(raw_lines, index + 1)
                if title_index is not None:
                    title = raw_lines[title_index].strip()
                    if (
                        title
                        and title not in SEPARATOR_LINES
                        and not title.startswith("[[")
                        and not title.startswith("#")
                        and parse_code_title(title) is None
                    ):
                        flush_body()
                        append_block(
                            Chapter(
                                title=title,
                                number=int(chapter_match.group(1)),
                                source_path=filepath,
                                **_provenance_kwargs(filepath, line_no, title_index + 1),
                            )
                        )
                        index = title_index + 1
                        continue
                self.diagnostic(
                    "WARNING",
                    "CHAPTER_TITLE_MISSING",
                    f"Chapter {chapter_match.group(1)} has no following title line.",
                    filepath,
                    line_no,
                )

            if re.match(r"^\d+\.\d+(?:\.\d+)?\s+\S", stripped):
                flush_body()
                number, title = parse_section_heading(stripped)
                cls = Subsection if number and number.count(".") > 1 else Section
                append_block(
                    cls(
                        number=number,
                        title=title,
                        level=3 if cls is Subsection else 2,
                        **_provenance_kwargs(filepath, line_no),
                    )
                )
                index += 1
                continue

            if stripped.casefold() == "chapter synthesis":
                flush_body()
                append_block(
                    Section(
                        title=stripped,
                        level=2,
                        **_provenance_kwargs(filepath, line_no),
                    )
                )
                index += 1
                continue

            if stripped in STRUCTURAL_LABELS:
                next_index = _next_nonempty_index(raw_lines, index + 1)
                if next_index is not None and parse_code_title(raw_lines[next_index].strip()):
                    index += 1
                    continue

            if stripped.startswith("### "):
                flush_body()
                number, title = parse_section_heading(stripped[4:].strip())
                append_block(
                    Subsection(
                        number=number,
                        title=title,
                        level=3,
                        **_provenance_kwargs(filepath, line_no),
                    )
                )
                index += 1
                continue

            if stripped.startswith("## "):
                flush_body()
                number, title = parse_section_heading(stripped[3:].strip())
                append_block(
                    Section(
                        number=number,
                        title=title,
                        level=2,
                        **_provenance_kwargs(filepath, line_no),
                    )
                )
                index += 1
                continue

            if stripped.startswith("# "):
                flush_body()
                number, title = parse_chapter_heading(stripped[2:].strip())
                append_block(
                    Chapter(
                        title=title,
                        number=number,
                        source_path=filepath,
                        **_provenance_kwargs(filepath, line_no),
                    )
                )
                index += 1
                continue

            if stripped.startswith("> "):
                flush_body()
                append_block(
                    Paragraph(
                        text=stripped[2:].strip(),
                        role="emphasis",
                        inline_content=parse_inline_references(
                            stripped[2:].strip(),
                            source_file=filepath,
                            source_line_start=line_no,
                            source_line_end=line_no,
                        ),
                        **_provenance_kwargs(filepath, line_no),
                    )
                )
                index += 1
                continue

            if stripped == "[[PAGEBREAK]]":
                flush_body()
                append_block(PageBreak(**_provenance_kwargs(filepath, line_no)))
                index += 1
                continue

            if stripped.startswith("[[PARTTITLE:"):
                flush_body()
                inner = stripped[len("[[PARTTITLE:") :].rstrip("]").strip()
                eyebrow, separator, title = inner.partition("|")
                if not separator:
                    self.diagnostic(
                        "ERROR",
                        "MALFORMED_PARTTITLE",
                        "Malformed PARTTITLE block.",
                        filepath,
                        line_no,
                    )
                    index += 1
                    continue
                append_block(
                    PartTitle(
                        eyebrow=eyebrow.strip(),
                        title=title.strip(),
                        **_provenance_kwargs(filepath, line_no),
                    )
                )
                index += 1
                continue

            if stripped.startswith("[[CALLOUT:"):
                flush_body()
                header = stripped[len("[[CALLOUT:") :].rstrip("]").strip()
                label, separator, title = header.partition("|")
                if not separator:
                    self.diagnostic(
                        "ERROR",
                        "MALFORMED_CALLOUT",
                        "Malformed CALLOUT block.",
                        filepath,
                        line_no,
                    )
                    index += 1
                    continue
                body_lines: list[tuple[int, str]] = []
                block_start = line_no
                index += 1
                while index < len(raw_lines) and raw_lines[index].strip() != "[[/CALLOUT]]":
                    body_lines.append((index + 1, raw_lines[index]))
                    index += 1
                if index >= len(raw_lines):
                    self.diagnostic(
                        "ERROR",
                        "UNCLOSED_CALLOUT",
                        "Unclosed CALLOUT block.",
                        filepath,
                        block_start,
                    )
                    break
                end_line = index + 1
                code_match = parse_code_title(title.strip())
                code = code_match[2] if code_match else None
                append_block(
                    self._build_callout(
                        label.strip(),
                        title.strip(),
                        body_lines,
                        source_file=filepath,
                        source_line_start=block_start,
                        source_line_end=end_line,
                        code=code,
                    )
                )
                index += 1
                continue

            if stripped == "[[FLOW]]":
                flush_body()
                block_start = line_no
                flow_lines: list[tuple[int, str]] = []
                index += 1
                while index < len(raw_lines) and raw_lines[index].strip() != "[[/FLOW]]":
                    flow_lines.append((index + 1, raw_lines[index]))
                    index += 1
                if index >= len(raw_lines):
                    self.diagnostic(
                        "ERROR",
                        "UNCLOSED_FLOW",
                        "Unclosed FLOW block.",
                        filepath,
                        block_start,
                    )
                    break
                append_block(
                    self._build_flow(
                        flow_lines,
                        source_file=filepath,
                        source_line_start=block_start,
                        source_line_end=index + 1,
                    )
                )
                index += 1
                continue

            code = parse_code_title(stripped)
            if code is not None:
                flush_body()
                label, title, code_value = code
                next_index, body = self._collect_until_boundary(raw_lines, index + 1)
                append_block(
                    self._build_callout(
                        label,
                        title,
                        body,
                        source_file=filepath,
                        source_line_start=line_no,
                        source_line_end=body[-1][0] if body else line_no,
                        code=code_value,
                    )
                )
                index = next_index
                continue

            if paragraph_start is None:
                paragraph_start = line_no
            body_buffer.append((line_no, raw_line))
            index += 1

        flush_body()
        return root_blocks

    def _collect_until_boundary(
        self,
        lines: Sequence[str],
        start: int,
    ) -> tuple[int, list[tuple[int, str]]]:
        body: list[tuple[int, str]] = []
        index = start
        while index < len(lines):
            line = lines[index].strip()
            if (
                line in SEPARATOR_LINES
                or line.startswith("#")
                or line.startswith("[[")
                or re.match(r"^\d+\.\d+(?:\.\d+)?\s+\S", line)
                or line.casefold() == "chapter synthesis"
                or parse_code_title(line) is not None
            ):
                break
            body.append((index + 1, lines[index]))
            index += 1
        return index, body

    def _build_callout(
        self,
        label: str,
        title: str,
        body_lines: Sequence[tuple[int, str]],
        *,
        source_file: Path,
        source_line_start: int,
        source_line_end: int,
        code: str | None = None,
    ) -> Callout:
        canonical_label = _canonical_label(label, code=code)
        if code is None:
            parsed_code = parse_code_title(title)
            if parsed_code is not None:
                canonical_label = parsed_code[0]
                code = parsed_code[2]

        body: list[ContentBlock] = []
        pending: list[tuple[int, str]] = []

        def append_to_body(block: ContentBlock) -> None:
            body.append(block)

        def flush_pending() -> None:
            if not pending:
                return
            start = pending[0][0]
            end = pending[-1][0]
            text = " ".join(line.strip() for _, line in pending if line.strip())
            pending.clear()
            if not text:
                return
            bold_match = re.fullmatch(r"\*\*(.+?)\*\*", text)
            append_to_body(
                Paragraph(
                    text=bold_match.group(1) if bold_match else text,
                    role="bold" if bold_match else "body",
                    inline_content=parse_inline_references(
                        bold_match.group(1) if bold_match else text,
                        source_file=source_file,
                        source_line_start=start,
                        source_line_end=end,
                    ),
                    **_provenance_kwargs(source_file, start, end),
                )
            )

        bullet_items: list[BulletItem] = []

        def flush_bullets() -> None:
            nonlocal bullet_items
            if not bullet_items:
                return
            append_to_body(
                BulletList(
                    items=bullet_items,
                    **_provenance_kwargs(
                        source_file,
                        bullet_items[0].source_line_start or source_line_start,
                        bullet_items[-1].source_line_end or source_line_end,
                    ),
                )
            )
            bullet_items = []

        for line_no, raw in body_lines:
            line = raw.strip()
            if not line or line in SEPARATOR_LINES:
                flush_pending()
                flush_bullets()
                continue
            bullet_match = re.match(r"^(?:[-*])\s+(.+)$", line)
            if bullet_match:
                flush_pending()
                bullet_items.append(
                    BulletItem(
                        text=bullet_match.group(1),
                        **_provenance_kwargs(source_file, line_no),
                    )
                )
                continue
            flush_bullets()
            pending.append((line_no, raw))

        flush_pending()
        flush_bullets()

        cls = CALLOUT_TYPES.get(canonical_label, Callout)
        return cls(
            label=label.strip(),
            title=title,
            body=body,
            code=code,
            **_provenance_kwargs(source_file, source_line_start, source_line_end),
        )

    def _build_flow(
        self,
        flow_lines: Sequence[tuple[int, str]],
        *,
        source_file: Path,
        source_line_start: int,
        source_line_end: int,
    ) -> FlowDiagram:
        nodes: list[FlowNode] = []
        for line_no, raw in flow_lines:
            flow_line = raw.strip()
            if not flow_line or flow_line == "↓" or flow_line in SEPARATOR_LINES:
                continue
            if "|" in flow_line:
                node, _, connector = flow_line.partition("|")
                nodes.append(
                    FlowNode(
                        label=node.strip(),
                        connector=connector.strip() or None,
                        **_provenance_kwargs(source_file, line_no),
                    )
                )
            else:
                nodes.append(
                    FlowNode(
                        label=flow_line,
                        connector=None,
                        **_provenance_kwargs(source_file, line_no),
                    )
                )
        return FlowDiagram(
            nodes=nodes,
            **_provenance_kwargs(source_file, source_line_start, source_line_end),
        )
