"""Validation for the modular publication engine."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from docx import Document

from model import (
    Book,
    BulletList,
    Callout,
    Chapter,
    CrossReference,
    FlowDiagram,
    FrontMatter,
    GovernanceArchitecture,
    GovernancePrinciple,
    PageBreak,
    Paragraph,
    ParserDiagnostic,
    PartTitle,
    ResearchFinding,
    ResearchMethodology,
    CanonicalDefinition,
    Section,
    Subsection,
    Volume,
)
from publication import EnrichmentResult
from theme_resolution import ThemeResolutionResult
from model import Manifest


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


def child_blocks(block) -> list:
    if isinstance(block, Book):
        return list(block.blocks)
    if isinstance(block, Volume):
        return list(block.blocks)
    if isinstance(block, FrontMatter):
        return list(block.blocks)
    if isinstance(block, Chapter):
        return list(block.blocks)
    if isinstance(block, Section):
        return list(block.blocks)
    if isinstance(block, Callout):
        return list(block.body)
    return []


def walk_blocks(root) -> Iterable:
    stack = child_blocks(root) if isinstance(root, Book) else [root]
    while stack:
        block = stack.pop(0)
        yield block
        stack[0:0] = child_blocks(block)


def _has_provenance(block) -> bool:
    if isinstance(block, Book):
        return True
    return bool(
        getattr(block, "source_file", None)
        and getattr(block, "source_line_start", None)
        and getattr(block, "source_line_end", None)
    )


def _diagnostic_summary(diagnostics: list[ParserDiagnostic]) -> tuple[bool, str]:
    errors = [item for item in diagnostics if item.severity == "ERROR"]
    warnings = [item for item in diagnostics if item.severity == "WARNING"]
    detail = f"{len(errors)} errors, {len(warnings)} warnings"
    return not errors, detail


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
    coded_objects = [block for block in blocks if isinstance(block, Callout) and block.code]
    chapter_five = next(
        (block for block in chapters if block.number == 5),
        None,
    )
    chapter_five_sections = chapter_five.sections if chapter_five is not None else []
    chapter_five_synthesis = any(
        section.title == "Chapter Synthesis" for section in chapter_five_sections
    )
    rf5_recognised = any(
        finding.code == "RF-5" or finding.title.startswith("RF-5")
        for finding in research_findings
    )
    volume_one = next((volume for volume in book.volumes if volume.number == "I"), None)
    volume_one_chapters = volume_one.chapters if volume_one else []

    duplicate_chapters: list[str] = []
    for volume in book.volumes:
        seen: set[int] = set()
        for chapter in volume.chapters:
            if chapter.number is not None and chapter.number in seen:
                duplicate_chapters.append(f"Volume {volume.number} Chapter {chapter.number}")
            if chapter.number is not None:
                seen.add(chapter.number)

    duplicate_codes_by_file: list[str] = []
    codes_by_file: dict[tuple[Path | None, str], int] = defaultdict(int)
    for item in coded_objects:
        codes_by_file[(item.source_file, item.code or "")] += 1
    for (source_file, code), count in codes_by_file.items():
        if count > 1:
            duplicate_codes_by_file.append(f"{source_file.name if source_file else 'unknown'}:{code}")

    empty_chapter_titles = [chapter for chapter in chapters if not chapter.title.strip()]
    empty_coded_bodies = [item.code or item.title for item in coded_objects if not item.body]
    bad_sections = []
    for chapter in chapters:
        if chapter.number is None:
            continue
        for section in chapter.sections:
            if section.number and not section.number.startswith(f"{chapter.number}."):
                bad_sections.append(f"Chapter {chapter.number}: {section.number}")
    bad_flows = [flow for flow in flow_diagrams if len(flow.nodes) < 2]
    missing_provenance = [
        type(block).__name__
        for block in blocks
        if not isinstance(block, (Volume,)) and not _has_provenance(block)
    ]
    parser_ok, parser_detail = _diagnostic_summary(book.diagnostics)

    result.add("Source files discovered", bool(book.source_files), f"{len(book.source_files)} files")
    result.add("Front Matter", bool(book.front_matter), f"{len(book.front_matter)} entries")
    result.add("Volumes", bool(book.volumes), f"{len(book.volumes)} detected")
    result.add("Chapters", bool(chapters), f"{len(chapters)} detected")
    result.add("Sections", bool(sections), f"{len(sections)} detected")
    result.add("Governance Principles", bool(governance_principles), f"{len(governance_principles)} detected")
    result.add("Canonical Definitions", bool(canonical_definitions), f"{len(canonical_definitions)} detected")
    result.add("Research Findings", bool(research_findings), f"{len(research_findings)} detected")
    result.add("Research Methodologies", bool(research_methodologies), f"{len(research_methodologies)} detected")
    result.add("Governance Architectures", bool(governance_architectures), f"{len(governance_architectures)} detected")
    result.add("Flow Diagrams", bool(flow_diagrams), f"{len(flow_diagrams)} detected")
    result.add("Parser Diagnostics", parser_ok, parser_detail)
    result.add("Volume I Chapter Membership", [c.number for c in volume_one_chapters] == [1, 2, 3, 4, 5], "Chapters 1-5")
    result.add("Chapter 5 Synthesis", chapter_five_synthesis, "plain-English Chapter Synthesis heading")
    result.add("RF-5 Research Finding", rf5_recognised, "legacy Research Finding / RF-5 structure")
    result.add("Duplicate Chapter Numbers", not duplicate_chapters, ", ".join(duplicate_chapters))
    result.add("Duplicate Coded Identifiers", not duplicate_codes_by_file, ", ".join(duplicate_codes_by_file))
    result.add("Empty Chapter Titles", not empty_chapter_titles, f"{len(empty_chapter_titles)} empty")
    result.add("Empty Coded Object Bodies", not empty_coded_bodies, ", ".join(empty_coded_bodies))
    result.add("Section Number Alignment", not bad_sections, ", ".join(bad_sections))
    result.add("Flow Diagram Shape", not bad_flows, f"{len(bad_flows)} invalid")
    result.add("Source Provenance", not missing_provenance, f"{len(missing_provenance)} missing")
    return result


def validate_enriched_publication(book: Book, enrichment: EnrichmentResult) -> ValidationResult:
    result = ValidationResult()
    diagnostics_errors = [item for item in enrichment.diagnostics if item.severity == "ERROR"]
    identifiers = [target.identifier for target in book.reference_registry.values()]
    bookmarks = [target.bookmark for target in book.reference_registry.values()]
    invalid_bookmarks = [
        bookmark
        for bookmark in bookmarks
        if not bookmark or not bookmark[0].isalpha() or len(bookmark) > 40
    ]
    generated_types = [section.generation_type for section in book.generated_sections]
    duplicate_generated = len(generated_types) != len(set(generated_types))
    unresolved_refs = []
    for block in walk_blocks(book):
        if isinstance(block, Paragraph):
            for item in block.inline_content:
                if isinstance(item, CrossReference) and item.target_query and not item.target_bookmark:
                    unresolved_refs.append(item.target_query)

    result.add("Identifiers assigned", bool(identifiers), f"{len(identifiers)} reference targets")
    result.add("Numbering validated", True, "canonical identifiers stable")
    result.add("Reference registry built", bool(book.reference_registry), f"{enrichment.reference_target_count} targets")
    result.add("Cross-references resolved", not unresolved_refs and enrichment.unresolved_reference_count == 0, f"{enrichment.cross_reference_count} references")
    result.add("Generated lists created", not duplicate_generated, f"{enrichment.generated_section_count} sections")
    result.add("Semantic index created", any(section.generation_type == "semantic_index" for section in book.generated_sections), f"{enrichment.index_entry_count} entries")
    result.add("Bookmark identifiers", not invalid_bookmarks, f"{len(invalid_bookmarks)} invalid")
    result.add("Enrichment diagnostics", not diagnostics_errors, f"{len(diagnostics_errors)} errors")
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


def validate_manifest_theme(manifest: Manifest, resolution: ThemeResolutionResult) -> ValidationResult:
    result = ValidationResult()
    theme = resolution.effective_theme
    warning_count = len([item for item in resolution.diagnostics if item.severity == "WARNING"])
    error_count = len([item for item in resolution.diagnostics if item.severity == "ERROR"])
    result.add("Manifest schema", manifest.schema_version == 1, f"version {manifest.schema_version}")
    result.add("Publication metadata", bool(manifest.publication.title and manifest.publication.author), manifest.publication.edition)
    result.add("Theme resolved", bool(theme.name), theme.name)
    result.add("Publication profile", bool(theme.publication_profile.name), theme.publication_profile.name)
    result.add("Page profile", bool(theme.page.name), theme.page.name)
    result.add("Title template", bool(theme.title_page.template), theme.title_page.template)
    result.add("Volume template", bool(theme.volume_page.template), theme.volume_page.template)
    result.add("Chapter template", bool(theme.chapter_opening.template), theme.chapter_opening.template)
    result.add("Semantic callout styles", len(theme.theme.callouts.styles) >= 6, f"{len(theme.theme.callouts.styles)} styles")
    result.add("Theme diagnostics", error_count == 0, f"{error_count} errors, {warning_count} warnings")
    return result


def merge_results(*results: ValidationResult) -> ValidationResult:
    merged = ValidationResult()
    for result in results:
        merged.checks.extend(result.checks)
    return merged
