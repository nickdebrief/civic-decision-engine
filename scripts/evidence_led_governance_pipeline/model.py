"""Semantic document model for the Evidence-Led Governance publication engine.

The classes in this module contain data only. They deliberately know nothing
about Word, python-docx, visual styles, file discovery, or source-file parsing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Optional


DiagnosticSeverity = Literal["INFO", "WARNING", "ERROR"]


@dataclass
class SourceProvenance:
    source_file: Optional[Path] = None
    source_line_start: Optional[int] = None
    source_line_end: Optional[int] = None
    identifier: Optional[str] = None
    bookmark: Optional[str] = None


@dataclass
class ParserDiagnostic(SourceProvenance):
    severity: DiagnosticSeverity = "INFO"
    code: str = ""
    message: str = ""


@dataclass
class Paragraph(SourceProvenance):
    text: str = ""
    role: str = "body"
    inline_content: list["InlineContent"] = field(default_factory=list)


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
class CrossReference(SourceProvenance):
    target_query: str = ""
    display_label: Optional[str] = None
    target_identifier: Optional[str] = None
    target_bookmark: Optional[str] = None
    resolved_label: Optional[str] = None

    @property
    def render_label(self) -> str:
        return self.display_label or self.resolved_label or self.target_query


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
    | CrossReference
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

InlineContent = str | CrossReference


@dataclass
class Section(SourceProvenance):
    title: str = ""
    number: Optional[str] = None
    level: int = 2
    generated: bool = False
    generation_type: Optional[str] = None
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
    reference_registry: dict[str, "ReferenceTarget"] = field(default_factory=dict)
    generated_sections: list[Section] = field(default_factory=list)
    blocks: list[Volume | FrontMatter | Chapter | Section | ContentBlock] = field(default_factory=list)

    @property
    def chapter_files(self) -> list[Path]:
        """Compatibility alias retained for legacy callers."""
        return self.source_files


@dataclass
class ReferenceTarget(SourceProvenance):
    identifier: str = ""
    display_label: str = ""
    object_type: str = ""
    title: str = ""
    bookmark: str = ""


@dataclass
class Manifest:
    path: Optional[Path] = None
    loaded: bool = False
    schema_version: int = 1
    source_files: list[Path] = field(default_factory=list)
    generated_front_matter: dict[str, bool] = field(default_factory=dict)
    publication: "PublicationConfig" = field(default_factory=lambda: PublicationConfig())
    version: "VersionConfig" = field(default_factory=lambda: VersionConfig())
    output: "OutputConfig" = field(default_factory=lambda: OutputConfig())
    layout: "LayoutConfig" = field(default_factory=lambda: LayoutConfig())
    title_page: "TitlePageConfig" = field(default_factory=lambda: TitlePageConfig())
    volume_page: "VolumePageConfig" = field(default_factory=lambda: VolumePageConfig())
    chapter_opening: "ChapterOpeningConfig" = field(default_factory=lambda: ChapterOpeningConfig())
    metadata: "MetadataConfig" = field(default_factory=lambda: MetadataConfig())
    assets: dict[str, "AssetConfig"] = field(default_factory=dict)
    diagnostics: list[ParserDiagnostic] = field(default_factory=list)


@dataclass(frozen=True)
class PublicationIdentityConfig:
    running_title: str = "EVIDENCE-LED GOVERNANCE"
    tagline: str = "Structured · Traceable · Governed"


@dataclass(frozen=True)
class PublicationConfig:
    title: str = "Evidence-Led Governance"
    subtitle: str = "A Research Methodology for Analysing Statutory Administration"
    author: str = "Nick Moloney"
    language: str = "en"
    edition: str = "Working Manuscript"
    theme: str = "handbook"
    identity: PublicationIdentityConfig = field(default_factory=PublicationIdentityConfig)


@dataclass(frozen=True)
class VersionConfig:
    mode: str = "auto"
    start: str = "1.0"


@dataclass(frozen=True)
class OutputConfig:
    basename: str = "Evidence-Led_Governance"
    directory: str = "output"
    formats: tuple[str, ...] = ("docx",)
    profile: str = "digital"
    html: "HtmlOutputConfig" = field(default_factory=lambda: HtmlOutputConfig())
    pdf: "PdfOutputConfig" = field(default_factory=lambda: PdfOutputConfig())
    package: "PackageOutputConfig" = field(default_factory=lambda: PackageOutputConfig())


@dataclass(frozen=True)
class HtmlOutputConfig:
    single_file: bool = True
    include_navigation: bool = True
    include_semantic_index: bool = True
    embed_css: bool = True


@dataclass(frozen=True)
class PdfOutputConfig:
    source: str = "docx"
    require_render: bool = True
    preserve_bookmarks: bool = True


@dataclass(frozen=True)
class PackageOutputConfig:
    enabled: bool = False
    include_checksums: bool = True
    include_build_report: bool = True


@dataclass(frozen=True)
class LayoutConfig:
    page_profile: str = "letter"
    chapter_starts_on_new_page: bool = True
    volume_starts_on_new_page: bool = True
    suppress_header_on_title_page: bool = True
    suppress_footer_on_title_page: bool = True


@dataclass(frozen=True)
class TitlePageConfig:
    template: str = "handbook"
    show_author: bool = True
    show_version: bool = True
    show_tagline: bool = True
    show_date: bool = False


@dataclass(frozen=True)
class VolumePageConfig:
    template: str = "institutional"
    suppress_header: bool = False
    suppress_footer: bool = False


@dataclass(frozen=True)
class ChapterOpeningConfig:
    template: str = "standard"


@dataclass(frozen=True)
class MetadataConfig:
    keywords: tuple[str, ...] = ()
    comments: str = ""
    build_identifier: str = ""


@dataclass(frozen=True)
class AssetConfig:
    path: str
    required: bool = False
    role: str = ""


ManifestValue = str | int | float | bool | tuple[str, ...] | dict[str, Any]
