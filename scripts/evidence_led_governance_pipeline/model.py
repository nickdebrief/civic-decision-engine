"""Semantic document model for the Evidence-Led Governance publication engine.

The classes in this module contain data only. They deliberately know nothing
about Word, python-docx, visual styles, or source-file parsing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class Paragraph:
    text: str
    role: str = "body"


@dataclass
class BulletList:
    items: list[str] = field(default_factory=list)


@dataclass
class Callout:
    label: str
    title: str
    body: list[Paragraph | BulletList] = field(default_factory=list)
    code: Optional[str] = None


@dataclass
class ResearchFinding(Callout):
    pass


@dataclass
class GovernancePrinciple(Callout):
    pass


@dataclass
class CanonicalDefinition(Callout):
    pass


@dataclass
class GovernanceArchitecture(Callout):
    pass


@dataclass
class ResearchMethodology(Callout):
    pass


@dataclass
class FlowDiagram:
    pairs: list[tuple[str, Optional[str]]] = field(default_factory=list)


ContentBlock = (
    Paragraph
    | BulletList
    | Callout
    | ResearchFinding
    | GovernancePrinciple
    | CanonicalDefinition
    | GovernanceArchitecture
    | ResearchMethodology
    | FlowDiagram
)


@dataclass
class Section:
    title: str
    level: int = 2
    blocks: list[ContentBlock] = field(default_factory=list)


@dataclass
class Chapter:
    title: str
    number: Optional[int] = None
    blocks: list[ContentBlock | Section] = field(default_factory=list)
    source_path: Optional[Path] = None


@dataclass
class Volume:
    title: str
    subtitle: str = ""
    blocks: list[Chapter | Section | ContentBlock] = field(default_factory=list)


@dataclass
class Book:
    title: str
    subtitle: str
    author: str
    running_title: str
    tagline: str = ""
    version: str = ""
    blocks: list[Volume | Chapter | Section | ContentBlock] = field(default_factory=list)
    chapter_files: list[Path] = field(default_factory=list)
