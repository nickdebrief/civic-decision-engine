"""Semantic parser for Evidence-Led Governance chapter source files."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional, Sequence

from model import (
    Book,
    BulletList,
    Callout,
    CanonicalDefinition,
    Chapter,
    ContentBlock,
    FlowDiagram,
    GovernanceArchitecture,
    GovernancePrinciple,
    Paragraph,
    ResearchFinding,
    ResearchMethodology,
    Section,
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


def _next_nonempty_index(lines: Sequence[str], start: int) -> Optional[int]:
    for index in range(start, len(lines)):
        if lines[index].strip():
            return index
    return None


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


def normalise_structure(lines: Sequence[str]) -> list[str]:
    """Convert legacy readable structure into semantic source events."""
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

        # Volume followed by a chapter is metadata in legacy files.
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
            chapter_files=list(chapter_files),
        )
        for chapter_file in chapter_files:
            book.blocks.extend(self.parse_chapter_file(chapter_file))
        return book

    def parse_chapter_file(self, filepath: Path) -> list[Volume | Chapter | Section | ContentBlock]:
        raw_lines = filepath.read_text(encoding="utf-8").splitlines()
        lines = normalise_structure(raw_lines)
        root_blocks: list[Volume | Chapter | Section | ContentBlock] = []
        current_chapter: Chapter | None = None
        current_section: Section | None = None
        body_buffer: list[str] = []
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
            if not body_buffer:
                return
            text = " ".join(line.strip() for line in body_buffer if line.strip())
            body_buffer.clear()
            if not text:
                return
            bold_match = re.fullmatch(r"\*\*(.+?)\*\*", text)
            if bold_match:
                append_block(Paragraph(bold_match.group(1), role="bold"))
                return
            bullet_match = re.match(r"^(?:[-*])\s+(.+)$", text)
            if bullet_match:
                append_block(BulletList([bullet_match.group(1)]))
                return
            append_block(Paragraph(text))

        while index < len(lines):
            raw_line = lines[index]
            stripped = raw_line.strip()

            if not stripped:
                flush_body()
                index += 1
                continue

            if stripped in SEPARATOR_LINES:
                flush_body()
                index += 1
                continue

            if stripped.startswith("### "):
                flush_body()
                append_block(Section(stripped[4:].strip(), level=3))
                index += 1
                continue

            if stripped.startswith("## "):
                flush_body()
                append_block(Section(stripped[3:].strip(), level=2))
                index += 1
                continue

            if stripped.startswith("# "):
                flush_body()
                number, title = parse_chapter_heading(stripped[2:].strip())
                append_block(Chapter(title=title, number=number, source_path=filepath))
                index += 1
                continue

            if stripped.startswith("> "):
                flush_body()
                append_block(Paragraph(stripped[2:].strip(), role="emphasis"))
                index += 1
                continue

            if stripped == "[[PAGEBREAK]]":
                flush_body()
                append_block(Paragraph("", role="pagebreak"))
                index += 1
                continue

            if stripped.startswith("[[PARTTITLE:"):
                flush_body()
                inner = stripped[len("[[PARTTITLE:") :].rstrip("]").strip()
                eyebrow, separator, title = inner.partition("|")
                if not separator:
                    raise ValueError(f"{filepath.name}: malformed PARTTITLE at line {index + 1}")
                append_block(Volume(eyebrow.strip(), title.strip()))
                index += 1
                continue

            if stripped.startswith("[[CALLOUT:"):
                flush_body()
                header = stripped[len("[[CALLOUT:") :].rstrip("]").strip()
                label, separator, title = header.partition("|")
                if not separator:
                    raise ValueError(f"{filepath.name}: malformed CALLOUT at line {index + 1}")
                body_lines: list[str] = []
                index += 1
                while index < len(lines) and lines[index].strip() != "[[/CALLOUT]]":
                    body_lines.append(lines[index])
                    index += 1
                if index >= len(lines):
                    raise ValueError(f"{filepath.name}: unclosed CALLOUT")
                append_block(self._build_callout(label.strip(), title.strip(), body_lines))
                index += 1
                continue

            if stripped == "[[FLOW]]":
                flush_body()
                pairs: list[tuple[str, str | None]] = []
                index += 1
                while index < len(lines) and lines[index].strip() != "[[/FLOW]]":
                    flow_line = lines[index].strip()
                    if flow_line and flow_line != "↓":
                        if "|" in flow_line:
                            node, _, connector = flow_line.partition("|")
                            pairs.append((node.strip(), connector.strip() or None))
                        else:
                            pairs.append((flow_line, None))
                    index += 1
                if index >= len(lines):
                    raise ValueError(f"{filepath.name}: unclosed FLOW")
                append_block(FlowDiagram(pairs))
                index += 1
                continue

            code = parse_code_title(stripped)
            if code is not None:
                flush_body()
                label, title, _code = code
                next_index, body = self._collect_until_boundary(lines, index + 1)
                append_block(self._build_callout(label, title, body, code=_code))
                index = next_index
                continue

            body_buffer.append(raw_line)
            index += 1

        flush_body()
        return root_blocks

    def _collect_until_boundary(self, lines: Sequence[str], start: int) -> tuple[int, list[str]]:
        body: list[str] = []
        index = start
        while index < len(lines):
            line = lines[index].strip()
            if (
                line in SEPARATOR_LINES
                or line.startswith("#")
                or line.startswith("[[")
                or parse_code_title(line) is not None
            ):
                break
            body.append(lines[index])
            index += 1
        return index, body

    def _build_callout(
        self,
        label: str,
        title: str,
        body_lines: Sequence[str],
        *,
        code: str | None = None,
    ) -> Callout:
        body: list[Paragraph | BulletList] = []
        pending: list[str] = []

        def flush_pending() -> None:
            if not pending:
                return
            text = " ".join(line.strip() for line in pending if line.strip())
            pending.clear()
            if not text:
                return
            bold_match = re.fullmatch(r"\*\*(.+?)\*\*", text)
            if bold_match:
                body.append(Paragraph(bold_match.group(1), role="bold"))
            else:
                body.append(Paragraph(text))

        for raw in body_lines:
            line = raw.strip()
            if not line or line in SEPARATOR_LINES:
                flush_pending()
                continue
            bullet_match = re.match(r"^(?:[-*])\s+(.+)$", line)
            if bullet_match:
                flush_pending()
                body.append(BulletList([bullet_match.group(1)]))
                continue
            pending.append(raw)
        flush_pending()

        cls = CALLOUT_TYPES.get(label, Callout)
        return cls(label=label, title=title, body=body, code=code)
