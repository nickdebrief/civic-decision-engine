from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


PIPELINE_DIR = Path(__file__).resolve().parents[1] / "scripts" / "evidence_led_governance_pipeline"
sys.path.insert(0, str(PIPELINE_DIR))

from model import (  # noqa: E402
    Book,
    BulletList,
    CanonicalDefinition,
    Chapter,
    FlowDiagram,
    FrontMatter,
    GovernancePrinciple,
    Paragraph,
    ResearchFinding,
    Section,
    Volume,
)
from parser import Parser  # noqa: E402
from renderers.docx_renderer import DocxRenderer  # noqa: E402
from validator import validate_book, walk_blocks  # noqa: E402


def write_source(root: Path, name: str, text: str) -> Path:
    path = root / name
    path.write_text(text.strip() + "\n", encoding="utf-8")
    return path


def parse_sources(paths: list[Path]) -> Book:
    return Parser().parse_files(
        paths,
        title="Evidence-Led Governance",
        subtitle="A Research Methodology",
        author="Nick Moloney",
        running_title="EVIDENCE-LED GOVERNANCE",
        tagline="Structured · Traceable · Governed",
        version="test",
    )


class PublicationEngineStage2Tests(unittest.TestCase):
    def test_explicit_chapter_markup_parses_into_chapter(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = write_source(Path(temp), "chapter.txt", "# Chapter 3 — Method\n\nBody.")
            book = parse_sources([path])

        chapters = [block for block in walk_blocks(book) if isinstance(block, Chapter)]
        self.assertEqual(chapters[0].number, 3)
        self.assertEqual(chapters[0].title, "Method")

    def test_legacy_chapter_five_structure_parses_into_one_chapter(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = write_source(
                Path(temp),
                "chapter5.txt",
                """
                Volume I

                Chapter 5

                Canonical Definitions

                5.1 Introduction
                Body.
                """,
            )
            book = parse_sources([path])

        chapters = [block for block in walk_blocks(book) if isinstance(block, Chapter)]
        self.assertEqual(len(chapters), 1)
        self.assertEqual(chapters[0].number, 5)
        self.assertEqual(chapters[0].title, "Canonical Definitions")

    def test_front_matter_does_not_count_as_numbered_chapter(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            preface = write_source(root, "00.txt", "# Preface\n\nOpening.")
            chapter = write_source(root, "01.txt", "# Chapter 1 — First\n\nBody.")
            book = parse_sources([preface, chapter])

        self.assertEqual([item.title for item in book.front_matter], ["Preface"])
        numbered = [block for block in walk_blocks(book) if isinstance(block, Chapter) and block.number]
        self.assertEqual(len(numbered), 1)

    def test_volume_one_contains_chapters_one_to_five(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            intro = write_source(root, "00.txt", "[[PARTTITLE: VOLUME I | Foundations]]\n## Introduction to Volume I\nIntro.")
            chapters = [
                write_source(root, f"0{number}.txt", f"# Chapter {number} — Title {number}\n\nBody.")
                for number in range(1, 6)
            ]
            book = parse_sources([intro, *chapters])

        self.assertEqual(len(book.volumes), 1)
        self.assertEqual([chapter.number for chapter in book.volumes[0].chapters], [1, 2, 3, 4, 5])

    def test_chapter_synthesis_becomes_section(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = write_source(Path(temp), "chapter.txt", "# Chapter 5 — Definitions\n\nChapter Synthesis\n\nClosing.")
            book = parse_sources([path])

        sections = [block for block in walk_blocks(book) if isinstance(block, Section)]
        self.assertEqual(sections[0].title, "Chapter Synthesis")

    def test_research_finding_followed_by_rf5_becomes_research_finding(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = write_source(
                Path(temp),
                "chapter.txt",
                "# Chapter 5 — Definitions\n\nResearch Finding\n\nRF-5\n\nFinding body.",
            )
            book = parse_sources([path])

        findings = [block for block in walk_blocks(book) if isinstance(block, ResearchFinding)]
        self.assertEqual(findings[0].code, "RF-5")
        self.assertEqual(findings[0].title, "RF-5")

    def test_cd1_governance_becomes_canonical_definition(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = write_source(Path(temp), "chapter.txt", "# Chapter 1 — First\n\nCD-1 Governance\n\nDefinition body.")
            book = parse_sources([path])

        definitions = [block for block in walk_blocks(book) if isinstance(block, CanonicalDefinition)]
        self.assertEqual(definitions[0].code, "CD-1")
        self.assertEqual(definitions[0].title, "CD-1 — Governance")

    def test_explicit_and_legacy_callouts_produce_equivalent_objects(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            explicit = write_source(
                root,
                "explicit.txt",
                "# Chapter 1 — First\n\n[[CALLOUT: Governance Principle | GP-4 — The Law Creates the Obligation]]\nBody.\n[[/CALLOUT]]",
            )
            legacy = write_source(root, "legacy.txt", "# Chapter 2 — Second\n\nGP-4 — The Law Creates the Obligation\n\nBody.")
            explicit_book = parse_sources([explicit])
            legacy_book = parse_sources([legacy])

        explicit_gp = [block for block in walk_blocks(explicit_book) if isinstance(block, GovernancePrinciple)][0]
        legacy_gp = [block for block in walk_blocks(legacy_book) if isinstance(block, GovernancePrinciple)][0]
        self.assertEqual((explicit_gp.code, explicit_gp.title), (legacy_gp.code, legacy_gp.title))

    def test_markdown_bullets_become_bullet_list(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = write_source(Path(temp), "chapter.txt", "# Chapter 1 — First\n\n- one\n- two")
            book = parse_sources([path])

        lists = [block for block in walk_blocks(book) if isinstance(block, BulletList)]
        self.assertEqual([item.text for item in lists[0].items], ["one", "two"])

    def test_flow_syntax_becomes_flow_nodes_and_ignores_literal_arrows(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = write_source(
                Path(temp),
                "chapter.txt",
                "# Chapter 1 — First\n\n[[FLOW]]\nLaw | creates\n↓\nAuthority | confers\nInstitutions\n[[/FLOW]]",
            )
            book = parse_sources([path])

        flows = [block for block in walk_blocks(book) if isinstance(block, FlowDiagram)]
        self.assertEqual([(node.label, node.connector) for node in flows[0].nodes], [
            ("Law", "creates"),
            ("Authority", "confers"),
            ("Institutions", None),
        ])

    def test_separator_lines_never_appear_in_model_content(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = write_source(Path(temp), "chapter.txt", "# Chapter 1 — First\n\nBefore.\n\n⸻\n—\n---\n\nAfter.")
            book = parse_sources([path])

        paragraphs = [block.text for block in walk_blocks(book) if isinstance(block, Paragraph)]
        self.assertNotIn("⸻", paragraphs)
        self.assertNotIn("—", paragraphs)
        self.assertNotIn("---", paragraphs)

    def test_duplicate_codes_in_same_source_fail_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = write_source(Path(temp), "chapter.txt", "# Chapter 1 — First\n\nCD-1 One\n\nBody.\n\nCD-1 Two\n\nBody.")
            book = parse_sources([path])

        self.assertFalse(validate_book(book).ok)

    def test_unclosed_callout_produces_parser_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = write_source(Path(temp), "chapter.txt", "# Chapter 1 — First\n\n[[CALLOUT: Research Finding | RF-9]]\nBody.")
            book = parse_sources([path])

        self.assertTrue(any(diagnostic.code == "UNCLOSED_CALLOUT" for diagnostic in book.diagnostics))
        self.assertFalse(validate_book(book).ok)

    def test_every_model_object_carries_source_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = write_source(Path(temp), "chapter.txt", "# Chapter 1 — First\n\n## 1.1 Intro\n\nRF-1\n\nBody.")
            book = parse_sources([path])

        for block in walk_blocks(book):
            self.assertIsNotNone(getattr(block, "source_file", None))
            self.assertIsNotNone(getattr(block, "source_line_start", None))
            self.assertIsNotNone(getattr(block, "source_line_end", None))

    def test_renderer_consumes_model_objects_without_raw_source_parsing(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "rendered.docx"
            book = Book(
                title="Evidence-Led Governance",
                subtitle="A Research Methodology",
                author="Nick Moloney",
                running_title="EVIDENCE-LED GOVERNANCE",
                version="test",
                blocks=[
                    FrontMatter(title="Preface", blocks=[Paragraph(text="Opening.")]),
                    Volume(
                        number="I",
                        title="Foundations",
                        blocks=[
                            Chapter(
                                number=1,
                                title="First",
                                blocks=[
                                    Section(title="Introduction", blocks=[Paragraph(text="Body.")]),
                                    FlowDiagram(nodes=[]),
                                ],
                            )
                        ],
                    ),
                ],
            )

            DocxRenderer().render(book, out)
            self.assertTrue(out.exists())


if __name__ == "__main__":
    unittest.main()
