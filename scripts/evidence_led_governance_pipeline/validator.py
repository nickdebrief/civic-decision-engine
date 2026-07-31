"""Validation for the modular publication engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from docx import Document

from model import (
    Book,
    Callout,
    Chapter,
    FlowDiagram,
    GovernanceArchitecture,
    GovernancePrinciple,
    ResearchFinding,
    ResearchMethodology,
    CanonicalDefinition,
    Section,
    Volume,
)


@dataclass
class ValidationResult:
    checks: list[tuple[str, bool, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(ok for _, ok, _ in self.checks)

    def add(self, name: str, ok: bool, detail: str = "") -> None:
        self.checks.append((name, ok, detail))

    def render(self) -> str:
        lines = ["Publication Validation", ""]
        for name, ok, detail in self.checks:
            status = "✓" if ok else "✗"
            suffix = f" — {detail}" if detail else ""
            lines.append(f"{status} {name}{suffix}")
        lines.extend(["", "PASS" if self.ok else "FAIL"])
        return "\n".join(lines)


def walk_blocks(book: Book):
    stack = list(book.blocks)
    while stack:
        block = stack.pop(0)
        yield block
        if isinstance(block, Volume):
            stack[0:0] = block.blocks
        elif isinstance(block, Chapter):
            stack[0:0] = block.blocks
        elif isinstance(block, Section):
            stack[0:0] = block.blocks


def validate_book(book: Book) -> ValidationResult:
    result = ValidationResult()
    blocks = list(walk_blocks(book))
    chapters = [block for block in blocks if isinstance(block, Chapter)]
    sections = [block for block in blocks if isinstance(block, Section)]
    governance_principles = [block for block in blocks if isinstance(block, GovernancePrinciple)]
    canonical_definitions = [block for block in blocks if isinstance(block, CanonicalDefinition)]
    research_findings = [block for block in blocks if isinstance(block, ResearchFinding)]
    research_methodologies = [block for block in blocks if isinstance(block, ResearchMethodology)]
    governance_architectures = [block for block in blocks if isinstance(block, GovernanceArchitecture)]
    flow_diagrams = [block for block in blocks if isinstance(block, FlowDiagram)]
    chapter_five = next(
        (block for block in blocks if isinstance(block, Chapter) and block.number == 5),
        None,
    )
    chapter_five_sections = []
    if chapter_five is not None:
        chapter_five_sections = [
            block for block in chapter_five.blocks if isinstance(block, Section)
        ]
    chapter_five_synthesis = any(
        section.title == "Chapter Synthesis" for section in chapter_five_sections
    )
    rf5_recognised = any(
        finding.code == "RF-5" or finding.title.startswith("RF-5")
        for finding in research_findings
    )

    result.add("Chapters", bool(chapters), f"{len(chapters)} detected")
    result.add("Sections", bool(sections), f"{len(sections)} detected")
    result.add("Governance Principles", bool(governance_principles), f"{len(governance_principles)} detected")
    result.add("Canonical Definitions", bool(canonical_definitions), f"{len(canonical_definitions)} detected")
    result.add("Research Findings", bool(research_findings), f"{len(research_findings)} detected")
    result.add("Research Methodologies", bool(research_methodologies), f"{len(research_methodologies)} detected")
    result.add("Governance Architectures", bool(governance_architectures), f"{len(governance_architectures)} detected")
    result.add("Flow Diagrams", bool(flow_diagrams), f"{len(flow_diagrams)} detected")
    result.add("Chapter 5 Synthesis", chapter_five_synthesis, "plain-English Chapter Synthesis heading")
    result.add("RF-5 Research Finding", rf5_recognised, "legacy Research Finding / RF-5 structure")
    return result


def validate_output(path: Path) -> ValidationResult:
    result = ValidationResult()
    exists = path.exists() and path.stat().st_size > 0
    reopened = False
    if exists:
        Document(path)
        reopened = True
    result.add("Output generated", exists and reopened, str(path))
    return result


def merge_results(*results: ValidationResult) -> ValidationResult:
    merged = ValidationResult()
    for result in results:
        merged.checks.extend(result.checks)
    return merged
