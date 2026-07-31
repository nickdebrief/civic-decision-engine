"""Publication enrichment for the Evidence-Led Governance document model."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from model import (
    Book,
    Callout,
    CanonicalDefinition,
    Chapter,
    CrossReference,
    FlowDiagram,
    FrontMatter,
    GovernanceArchitecture,
    GovernancePrinciple,
    Paragraph,
    ParserDiagnostic,
    ReferenceTarget,
    ResearchFinding,
    ResearchMethodology,
    Section,
    Volume,
)


@dataclass
class EnrichmentResult:
    diagnostics: list[ParserDiagnostic] = field(default_factory=list)
    reference_target_count: int = 0
    cross_reference_count: int = 0
    generated_section_count: int = 0
    index_entry_count: int = 0
    bookmark_count: int = 0
    hyperlink_count: int = 0
    unresolved_reference_count: int = 0

    @property
    def ok(self) -> bool:
        return not any(item.severity == "ERROR" for item in self.diagnostics)


def slugify(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "item"


def word_safe_bookmark(identifier: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_]", "_", identifier)
    if not value or not value[0].isalpha():
        value = f"b_{value}"
    return value[:40]


def object_title(block) -> str:
    if isinstance(block, Volume):
        return block.title
    if isinstance(block, FrontMatter):
        return block.title
    if isinstance(block, Chapter):
        return block.title
    if isinstance(block, Section):
        return block.heading_text
    if isinstance(block, Callout):
        return block.title
    return ""


def display_label(block) -> str:
    if isinstance(block, Volume):
        return f"Volume {block.number}"
    if isinstance(block, FrontMatter):
        return block.title
    if isinstance(block, Chapter):
        return f"Chapter {block.number}" if block.number else block.title
    if isinstance(block, Section):
        return block.heading_text
    if isinstance(block, Callout):
        return block.code or block.title
    return object_title(block)


def object_type(block) -> str:
    if isinstance(block, Volume):
        return "Volume"
    if isinstance(block, FrontMatter):
        return "Front Matter"
    if isinstance(block, Chapter):
        return "Chapter"
    if isinstance(block, Section):
        return "Section"
    if isinstance(block, Callout):
        return block.callout_type
    return type(block).__name__


def children(block) -> list:
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


def walk(block) -> Iterable:
    stack = children(block) if isinstance(block, Book) else [block]
    while stack:
        item = stack.pop(0)
        yield item
        stack[0:0] = children(item)


def cross_references(book: Book) -> Iterable[CrossReference]:
    for block in walk(book):
        if isinstance(block, Paragraph):
            for item in block.inline_content:
                if isinstance(item, CrossReference):
                    yield item
        elif isinstance(block, CrossReference):
            yield block


def target_blocks(book: Book) -> list:
    return [
        block
        for block in walk(book)
        if isinstance(
            block,
            (
                Volume,
                FrontMatter,
                Chapter,
                Section,
                GovernancePrinciple,
                ResearchFinding,
                CanonicalDefinition,
                GovernanceArchitecture,
                ResearchMethodology,
            ),
        )
        and not (isinstance(block, Section) and block.generated)
    ]


def target_blocks_with_parent(book: Book) -> list[tuple[object, object | None]]:
    items: list[tuple[object, object | None]] = []

    def visit(block, parent=None) -> None:
        if isinstance(
            block,
            (
                Volume,
                FrontMatter,
                Chapter,
                Section,
                GovernancePrinciple,
                ResearchFinding,
                CanonicalDefinition,
                GovernanceArchitecture,
                ResearchMethodology,
            ),
        ) and not (isinstance(block, Section) and block.generated):
            items.append((block, parent))
        for child in children(block):
            visit(child, block)

    for child in children(book):
        visit(child, book)
    return items


def assign_identifier(block, counters: dict[str, int], parent=None) -> str:
    if isinstance(block, Volume):
        return f"volume-{slugify(block.number)}"
    if isinstance(block, FrontMatter):
        return f"frontmatter-{slugify(block.title)}"
    if isinstance(block, Chapter):
        return f"chapter-{block.number}" if block.number is not None else f"chapter-{slugify(block.title)}"
    if isinstance(block, Section):
        if block.number and isinstance(parent, FrontMatter):
            return f"section-{slugify(parent.title)}-{block.number.replace('.', '-')}"
        return f"section-{block.number.replace('.', '-')}" if block.number else f"section-{slugify(block.title)}"
    if isinstance(block, Callout) and block.code:
        return block.code.lower()

    base = slugify(object_title(block) or object_type(block))
    counters[base] += 1
    return f"{base}-{counters[base]}"


def build_reference_registry(book: Book, result: EnrichmentResult) -> dict[str, ReferenceTarget]:
    registry: dict[str, ReferenceTarget] = {}
    counters: dict[str, int] = defaultdict(int)
    seen_identifiers: dict[str, ReferenceTarget] = {}
    for block, parent in target_blocks_with_parent(book):
        identifier = assign_identifier(block, counters, parent)
        block.identifier = identifier
        block.bookmark = word_safe_bookmark(identifier)
        target = ReferenceTarget(
            identifier=identifier,
            display_label=display_label(block),
            object_type=object_type(block),
            title=object_title(block),
            source_file=getattr(block, "source_file", None) or getattr(block, "source_path", None),
            source_line_start=getattr(block, "source_line_start", None),
            source_line_end=getattr(block, "source_line_end", None),
            bookmark=block.bookmark,
        )
        if identifier in seen_identifiers:
            previous = seen_identifiers[identifier]
            if previous.source_file == target.source_file:
                result.diagnostics.append(
                    ParserDiagnostic(
                        severity="ERROR",
                        code="DUPLICATE_SEMANTIC_IDENTIFIER",
                        message=f"Duplicate semantic identifier: {identifier}",
                        source_file=target.source_file,
                        source_line_start=target.source_line_start,
                        source_line_end=target.source_line_end,
                    )
                )
                continue
            counters[identifier] += 1
            identifier = f"{identifier}-{counters[identifier] + 1}"
            block.identifier = identifier
            block.bookmark = word_safe_bookmark(identifier)
            target.identifier = identifier
            target.bookmark = block.bookmark
        if identifier in registry:
            result.diagnostics.append(
                ParserDiagnostic(
                    severity="ERROR",
                    code="DUPLICATE_SEMANTIC_IDENTIFIER",
                    message=f"Duplicate semantic identifier: {identifier}",
                    source_file=target.source_file,
                    source_line_start=target.source_line_start,
                    source_line_end=target.source_line_end,
                )
            )
            continue
        seen_identifiers[identifier] = target
        registry[identifier] = target

    for target in list(registry.values()):
        registry.setdefault(target.display_label.lower(), target)
        if target.object_type == "Chapter":
            registry.setdefault(target.display_label.lower().replace(" ", "-"), target)
        if target.object_type == "Section" and target.identifier.startswith("section-"):
            registry.setdefault(target.display_label.lower(), target)
    result.reference_target_count = len({target.identifier for target in registry.values()})
    result.bookmark_count = result.reference_target_count
    return registry


def resolve_reference_query(query: str, registry: dict[str, ReferenceTarget]) -> ReferenceTarget | None:
    normalized = query.strip().lower()
    normalized = re.sub(r"\s+", " ", normalized)
    candidates = [
        normalized,
        normalized.replace(" ", "-"),
        normalized.replace(".", "-").replace(" ", "-"),
    ]
    match = re.match(r"^(gp|rf|cd|ga|rm)-(\d+)$", normalized)
    if match:
        candidates.insert(0, f"{match.group(1)}-{match.group(2)}")
    match = re.match(r"^chapter\s+(\d+)$", normalized)
    if match:
        candidates.insert(0, f"chapter-{match.group(1)}")
    match = re.match(r"^section\s+(\d+(?:\.\d+)*)$", normalized)
    if match:
        candidates.insert(0, f"section-{match.group(1).replace('.', '-')}")
    for candidate in candidates:
        if candidate in registry:
            return registry[candidate]
    return None


def resolve_cross_references(book: Book, registry: dict[str, ReferenceTarget], result: EnrichmentResult) -> None:
    count = 0
    unresolved = 0
    for ref in cross_references(book):
        count += 1
        target = resolve_reference_query(ref.target_query, registry)
        if target is None:
            unresolved += 1
            result.diagnostics.append(
                ParserDiagnostic(
                    severity="ERROR",
                    code="UNRESOLVED_CROSS_REFERENCE",
                    message=f"Unresolved cross-reference: {ref.target_query}",
                    source_file=ref.source_file,
                    source_line_start=ref.source_line_start,
                    source_line_end=ref.source_line_end,
                )
            )
            continue
        ref.target_identifier = target.identifier
        ref.target_bookmark = target.bookmark
        ref.resolved_label = ref.display_label or target.display_label
    result.cross_reference_count = count
    result.hyperlink_count = count - unresolved
    result.unresolved_reference_count = unresolved


def reference_paragraph(target: ReferenceTarget, label: str | None = None) -> Paragraph:
    if label:
        text = label
    elif target.title.startswith(target.display_label):
        text = target.title
    elif target.title:
        text = f"{target.display_label} — {target.title}"
    else:
        text = target.display_label
    ref = CrossReference(
        target_query=target.identifier,
        display_label=text,
        target_identifier=target.identifier,
        target_bookmark=target.bookmark,
        resolved_label=text,
    )
    return Paragraph(text=text, inline_content=[ref])


def targets_by_type(registry: dict[str, ReferenceTarget], object_type: str) -> list[ReferenceTarget]:
    unique = {target.identifier: target for target in registry.values() if target.object_type == object_type}
    return sorted(unique.values(), key=lambda item: item.identifier)


def generated_section(title: str, generation_type: str, blocks: list[Paragraph]) -> Section:
    identifier = f"generated-{slugify(generation_type)}"
    return Section(
        title=title,
        generated=True,
        generation_type=generation_type,
        blocks=blocks,
        identifier=identifier,
        bookmark=word_safe_bookmark(identifier),
    )


def build_contents(registry: dict[str, ReferenceTarget]) -> Section:
    targets = [
        target
        for target in {item.identifier: item for item in registry.values()}.values()
        if target.object_type in {"Front Matter", "Volume", "Chapter", "Section"}
    ]
    order = {"Front Matter": 0, "Volume": 1, "Chapter": 2, "Section": 3}
    targets.sort(key=lambda item: (order.get(item.object_type, 99), item.identifier))
    return generated_section(
        "Contents",
        "table_of_contents",
        [reference_paragraph(target) for target in targets],
    )


def build_object_list(title: str, generation_type: str, registry: dict[str, ReferenceTarget], object_type: str) -> Section:
    return generated_section(
        title,
        generation_type,
        [reference_paragraph(target) for target in targets_by_type(registry, object_type)],
    )


def build_semantic_index(registry: dict[str, ReferenceTarget]) -> Section:
    unique = {target.identifier: target for target in registry.values()}.values()
    def index_label(target: ReferenceTarget) -> str:
        if target.title.startswith(target.display_label):
            return target.title
        return f"{target.title or target.display_label} — {target.display_label}"

    entries = [
        reference_paragraph(target, index_label(target))
        for target in unique
        if target.title and target.object_type in {
            "Chapter",
            "Section",
            "Governance Principle",
            "Research Finding",
            "Canonical Definition",
            "Governance Architecture",
            "Research Methodology",
        }
    ]
    entries.sort(key=lambda paragraph: paragraph.text.casefold())
    return generated_section("Semantic Index", "semantic_index", entries)


def generate_sections(book: Book, registry: dict[str, ReferenceTarget], enabled: dict[str, bool]) -> list[Section]:
    sections: list[Section] = []
    if enabled.get("table_of_contents", True):
        sections.append(build_contents(registry))
    if enabled.get("governance_principles", True):
        sections.append(build_object_list("List of Governance Principles", "governance_principles", registry, "Governance Principle"))
    if enabled.get("research_findings", True):
        sections.append(build_object_list("List of Research Findings", "research_findings", registry, "Research Finding"))
    if enabled.get("canonical_definitions", True):
        sections.append(build_object_list("List of Canonical Definitions", "canonical_definitions", registry, "Canonical Definition"))
    if enabled.get("governance_architectures", True):
        sections.append(build_object_list("List of Governance Architectures", "governance_architectures", registry, "Governance Architecture"))
    if enabled.get("research_methodologies", True):
        sections.append(build_object_list("List of Research Methodologies", "research_methodologies", registry, "Research Methodology"))
    if enabled.get("semantic_index", True):
        sections.append(build_semantic_index(registry))
    return sections


def enrich_publication(book: Book, generated_front_matter: dict[str, bool] | None = None) -> EnrichmentResult:
    result = EnrichmentResult()
    original_blocks = [block for block in book.blocks if not (isinstance(block, Section) and block.generated)]
    book.blocks = original_blocks
    registry = build_reference_registry(book, result)
    book.reference_registry = {target.identifier: target for target in registry.values()}
    resolve_cross_references(book, registry, result)
    generated_sections = generate_sections(book, registry, generated_front_matter or {})
    book.generated_sections = generated_sections
    book.blocks = generated_sections + original_blocks
    result.generated_section_count = len(generated_sections)
    result.index_entry_count = len(generated_sections[-1].blocks) if generated_sections else 0
    result.hyperlink_count += sum(len(section.blocks) for section in generated_sections)
    return result
