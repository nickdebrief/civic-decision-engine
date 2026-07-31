"""Semantic document model for the Evidence-Led Governance publication engine.

The classes in this module contain data only. They deliberately know nothing
about Word, python-docx, visual styles, file discovery, or source-file parsing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional


DiagnosticSeverity = Literal["INFO", "WARNING", "ERROR"]


@dataclass
class SourceProvenance:
    source_file: Optional[Path] = None
    source_line_start: Optional[int] = None
    source_line_end: Optional[int] = None


@dataclass
class ParserDiagnostic(SourceProvenance):
    severity: DiagnosticSeverity = "INFO"
    code: str = ""
    message: str = ""


@dataclass
class Paragraph(SourceProvenance):
    text: str = ""
    role: str = "body"


@dataclass
class Emphasis(Paragraph):
    role: str = "emphasis"


@dataclass
class BulletItem(SourceProvenance):
    text: str = ""


@dataclass
class BulletList(SourceProvenance):
    items: list[BulletItem] = field(default_factory=list)


@dataclass
class PageBreak(SourceProvenance):
    pass


@dataclass
class PartTitle(SourceProvenance):
    eyebrow: str = ""
    title: str = ""


@dataclass
class Callout(SourceProvenance):
    label: str = ""
    title: str = ""
    body: list["ContentBlock"] = field(default_factory=list)
    code: Optional[str] = None
    callout_type: str = "Callout"


@dataclass
class ResearchFinding(Callout):
    callout_type: str = "Research Finding"


@dataclass
class GovernancePrinciple(Callout):
    callout_type: str = "Governance Principle"


@dataclass
class CanonicalDefinition(Callout):
    callout_type: str = "Canonical Definition"


@dataclass
class GovernanceArchitecture(Callout):
    callout_type: str = "Governance Architecture"


@dataclass
class ResearchMethodology(Callout):
    callout_type: str = "Research Methodology"


@dataclass
class FlowNode(SourceProvenance):
    label: str = ""
    connector: Optional[str] = None


@dataclass
class FlowDiagram(SourceProvenance):
    nodes: list[FlowNode] = field(default_factory=list)
    direction: str = "vertical"

    @property
    def pairs(self) -> list[tuple[str, Optional[str]]]:
        """Compatibility view for the Stage 1 renderer contract."""
        return [(node.label, node.connector) for node in self.nodes]


ContentBlock = (
    Paragraph
    | Emphasis
    | BulletList
    | Callout
    | ResearchFinding
    | GovernancePrinciple
    | CanonicalDefinition
    | GovernanceArchitecture
    | ResearchMethodology
    | FlowDiagram
    | PageBreak
    | PartTitle
)


@dataclass
class Section(SourceProvenance):
    title: str = ""
    number: Optional[str] = None
    level: int = 2
    blocks: list[ContentBlock | "Subsection"] = field(default_factory=list)

    @property
    def heading_text(self) -> str:
        return f"{self.number} {self.title}".strip() if self.number else self.title


@dataclass
class Subsection(Section):
    level: int = 3


@dataclass
class Chapter(SourceProvenance):
    title: str = ""
    number: Optional[int] = None
    sections: list[Section] = field(default_factory=list)
    blocks: list[ContentBlock | Section] = field(default_factory=list)
    source_path: Optional[Path] = None


@dataclass
class FrontMatter(SourceProvenance):
    title: str = ""
    blocks: list[ContentBlock | Section] = field(default_factory=list)
    source_file: Optional[Path] = None


@dataclass
class Volume(SourceProvenance):
    number: str = ""
    title: str = ""
    introduction: list[Section | ContentBlock] = field(default_factory=list)
    chapters: list[Chapter] = field(default_factory=list)
    blocks: list[Chapter | Section | ContentBlock] = field(default_factory=list)
    source_file: Optional[Path] = None

    @property
    def subtitle(self) -> str:
        """Compatibility alias for the Stage 1 renderer."""
        return self.title


@dataclass
class Book(SourceProvenance):
    title: str = ""
    subtitle: str = ""
    author: str = ""
    running_title: str = ""
    tagline: str = ""
    version: str = ""
    front_matter: list[FrontMatter] = field(default_factory=list)
    volumes: list[Volume] = field(default_factory=list)
    standalone_chapters: list[Chapter] = field(default_factory=list)
    source_files: list[Path] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)
    diagnostics: list[ParserDiagnostic] = field(default_factory=list)
    blocks: list[Volume | FrontMatter | Chapter | Section | ContentBlock] = field(default_factory=list)

    @property
    def chapter_files(self) -> list[Path]:
        """Compatibility alias retained for legacy callers."""
        return self.source_files
