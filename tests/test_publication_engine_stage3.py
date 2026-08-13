from __future__ import annotations

import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


PIPELINE_DIR = Path(__file__).resolve().parents[1] / "scripts" / "evidence_led_governance_pipeline"
sys.path.insert(0, str(PIPELINE_DIR))

from build import AUTHOR, BASENAME, RUNNING_TITLE, SUBTITLE, TAGLINE, TITLE, build_document  # noqa: E402
from manifest import load_manifest  # noqa: E402
from model import CanonicalDefinition, CrossReference, GovernancePrinciple, Paragraph, Section  # noqa: E402
from model import Book, Chapter  # noqa: E402
from parser import Parser  # noqa: E402
from publication import enrich_publication, resolve_reference_query  # noqa: E402
from renderers.docx_renderer import DocxRenderer  # noqa: E402
from validator import validate_enriched_publication  # noqa: E402


def write_source(root: Path, name: str, text: str) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")
    return path


def parse_book(paths: list[Path]):
    return Parser().parse_files(
        paths,
        title=TITLE,
        subtitle=SUBTITLE,
        author=AUTHOR,
        running_title=RUNNING_TITLE,
        tagline=TAGLINE,
        version="test",
    )


class PublicationEngineStage3Tests(unittest.TestCase):
    def test_manifest_loads_and_preserves_explicit_source_order(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            a = write_source(root, "chapters/a.txt", "# Preface\n\nA")
            b = write_source(root, "chapters/b.txt", "# Chapter 1 — One\n\nB")
            manifest = write_source(root, "book.toml", 'schema_version = 1\nsources = ["chapters/b.txt", "chapters/a.txt"]')

            loaded = load_manifest(manifest, chapters_dir=root / "chapters")

        self.assertEqual([path.name for path in loaded.source_files], [b.name, a.name])
        self.assertTrue(loaded.loaded)

    def test_missing_manifest_falls_back_to_legacy_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = write_source(root, "chapters/a.txt", "# Preface\n\nA")
            loaded = load_manifest(root / "book.toml", chapters_dir=root / "chapters")

        self.assertEqual(loaded.source_files, [source])
        self.assertFalse(loaded.loaded)
        self.assertEqual(loaded.diagnostics[0].code, "MANIFEST_MISSING")

    def test_missing_source_file_in_manifest_fails_clearly(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = write_source(root, "book.toml", 'schema_version = 1\nsources = ["chapters/missing.txt"]')
            with self.assertRaises(FileNotFoundError):
                load_manifest(manifest, chapters_dir=root / "chapters")

    def test_duplicate_source_file_in_manifest_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_source(root, "chapters/a.txt", "# Preface\n\nA")
            manifest = write_source(root, "book.toml", 'schema_version = 1\nsources = ["chapters/a.txt", "chapters/a.txt"]')
            with self.assertRaises(ValueError):
                load_manifest(manifest, chapters_dir=root / "chapters")

    def test_volume_membership_is_built_from_manifest_order(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            intro = write_source(root, "chapters/intro.txt", "[[PARTTITLE: VOLUME I | Foundations]]\n## Introduction\nIntro.")
            chapter = write_source(root, "chapters/ch1.txt", "# Chapter 1 — One\n\nBody.")
            book = parse_book([intro, chapter])
            enrich_publication(book)

        self.assertEqual(book.volumes[0].number, "I")
        self.assertEqual([chapter.number for chapter in book.volumes[0].chapters], [1])

    def test_stable_identifiers_are_assigned_deterministically(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = write_source(root, "chapter.txt", "# Chapter 3 — Method\n\n## 3.4 Six Stages\n\nGP-3 — Rule\n\nBody.")
            book = parse_book([source])
            enrich_publication(book)

        self.assertIn("chapter-3", book.reference_registry)
        self.assertIn("section-3-4", book.reference_registry)
        self.assertIn("gp-3", book.reference_registry)

    def test_explicit_codes_remain_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = write_source(Path(temp), "chapter.txt", "# Chapter 1 — One\n\nRF-5\n\nBody.")
            book = parse_book([source])
            enrich_publication(book)

        self.assertEqual(book.reference_registry["rf-5"].display_label, "RF-5")

    def test_duplicate_semantic_identifiers_fail_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = write_source(Path(temp), "chapter.txt", "# Chapter 1 — One\n\nGP-1\n\nBody.\n\nGP-1\n\nBody.")
            book = parse_book([source])
            enrichment = enrich_publication(book)

        self.assertFalse(validate_enriched_publication(book, enrichment).ok)

    def test_explicit_cross_reference_resolves(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = write_source(Path(temp), "chapter.txt", "# Chapter 1 — One\n\nGP-3 — Rule\n\nBody.\n\nAs established in [[REF: GP-3]].")
            book = parse_book([source])
            enrichment = enrich_publication(book)

        self.assertTrue(validate_enriched_publication(book, enrichment).ok)
        refs = [item for block in book.blocks for item in getattr(block, "inline_content", []) if isinstance(item, CrossReference)]
        self.assertEqual(enrichment.unresolved_reference_count, 0)

    def test_custom_reference_label_resolves(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = write_source(Path(temp), "chapter.txt", "# Chapter 1 — One\n\nCD-7 Institutional Memory\n\nBody.\n\nSee [[REF: CD-7 | the definition of Institutional Memory]].")
            book = parse_book([source])
            enrich_publication(book)
            paragraphs = [block for block in book.volumes + book.standalone_chapters + book.blocks if isinstance(block, Paragraph)]

        found = []
        for block in book.generated_sections + list(book.reference_registry.values()):
            _ = block
        for block in walk_paragraphs(book):
            found.extend(item for item in block.inline_content if isinstance(item, CrossReference))
        self.assertTrue(any(ref.render_label == "the definition of Institutional Memory" for ref in found))

    def test_unresolved_reference_fails_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = write_source(Path(temp), "chapter.txt", "# Chapter 1 — One\n\nSee [[REF: GP-99]].")
            book = parse_book([source])
            enrichment = enrich_publication(book)

        self.assertFalse(validate_enriched_publication(book, enrichment).ok)
        self.assertEqual(enrichment.unresolved_reference_count, 1)

    def test_generated_governance_principle_list_is_correct(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = write_source(Path(temp), "chapter.txt", "# Chapter 1 — One\n\nGP-1 — One\n\nBody.\n\nGP-2 — Two\n\nBody.")
            book = parse_book([source])
            enrich_publication(book, {"governance_principles": True})

        section = next(section for section in book.generated_sections if section.generation_type == "governance_principles")
        self.assertEqual([block.text for block in section.blocks], ["GP-1 — One", "GP-2 — Two"])

    def test_generated_canonical_definition_list_is_correct(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = write_source(Path(temp), "chapter.txt", "# Chapter 1 — One\n\nCD-1 Governance\n\nBody.")
            book = parse_book([source])
            enrich_publication(book)

        section = next(section for section in book.generated_sections if section.generation_type == "canonical_definitions")
        self.assertTrue(section.blocks[0].text.startswith("CD-1"))

    def test_semantic_index_is_alphabetically_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = write_source(Path(temp), "chapter.txt", "# Chapter 1 — Zebra\n\nCD-1 Alpha\n\nBody.")
            book = parse_book([source])
            enrich_publication(book)

        section = next(section for section in book.generated_sections if section.generation_type == "semantic_index")
        entries = [block.text for block in section.blocks]
        self.assertEqual(entries, sorted(entries, key=str.casefold))

    def test_table_of_contents_derives_from_canonical_headings(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = write_source(Path(temp), "chapter.txt", "# Chapter 1 — One\n\n## 1.1 Intro\n\nBody.")
            book = parse_book([source])
            enrich_publication(book)

        section = next(section for section in book.generated_sections if section.generation_type == "table_of_contents")
        self.assertTrue(any("Chapter 1" in block.text for block in section.blocks))
        self.assertTrue(any("1.1 Intro" in block.text for block in section.blocks))

    def test_table_of_contents_preserves_canonical_numeric_section_order(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = write_source(
                Path(temp),
                "chapter.txt",
                "# Chapter 1 — One\n\n## 1.1 First\n\nBody.\n\n## 1.2 Second\n\nBody.\n\n## 1.10 Tenth\n\nBody.",
            )
            book = parse_book([source])
            enrich_publication(book)

        section = next(section for section in book.generated_sections if section.generation_type == "table_of_contents")
        numbered = [block.text for block in section.blocks if block.text[:1].isdigit()]
        self.assertEqual(numbered, ["1.1 First", "1.2 Second", "1.10 Tenth"])

    def test_semantic_index_naturally_orders_hierarchical_sections(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = write_source(
                Path(temp),
                "chapter.txt",
                "# Chapter 7 — Seven\n\n## 7.1 First\n\nBody.\n\n## 7.10 Tenth\n\nBody.\n\n## 7.2 Second\n\nBody.\n\n## 7.9 Ninth\n\nBody.\n\nCD-1 Alpha\n\nBody.",
            )
            book = parse_book([source])
            enrich_publication(book)

        section = next(section for section in book.generated_sections if section.generation_type == "semantic_index")
        entries = [block.text for block in section.blocks]
        self.assertEqual(
            entries[:4],
            ["7.1 First", "7.2 Second", "7.9 Ninth", "7.10 Tenth"],
        )
        self.assertIn("CD-1 — Alpha", entries)
        self.assertEqual(entries[-2:], ["CD-1 — Alpha", "Seven — Chapter 7"])

    def test_semantic_index_naturally_orders_chapter_three_sections(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = write_source(
                Path(temp),
                "chapter.txt",
                "# Chapter 3 — Three\n\n## 3.1 First\n\nBody.\n\n## 3.10 Tenth\n\nBody.\n\n## 3.2 Second\n\nBody.",
            )
            book = parse_book([source])
            enrich_publication(book)

        section = next(section for section in book.generated_sections if section.generation_type == "semantic_index")
        numbered = [block.text for block in section.blocks if block.text[:1].isdigit()]
        self.assertEqual(numbered, ["3.1 First", "3.2 Second", "3.10 Tenth"])

    def test_contents_preserves_chapter_and_volume_order(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            intro = write_source(root, "intro.txt", "[[PARTTITLE: VOLUME I | Foundations]]\n\n## Introduction\n\nIntro.")
            ch1 = write_source(root, "ch1.txt", "# Chapter 1 — One\n\nBody.")
            ch6 = write_source(root, "ch6.txt", "# Chapter 6 — Six\n\nBody.")
            ch7 = write_source(root, "ch7.txt", "[[PARTTITLE: VOLUME II | Continuation]]\n\n# Chapter 7 — Seven\n\nBody.")
            book = parse_book([intro, ch1, ch6, ch7])
            enrich_publication(book)

        contents = next(section for section in book.generated_sections if section.generation_type == "table_of_contents")
        labels = [block.text for block in contents.blocks]
        chapter_labels = [label for label in labels if label.startswith("Chapter ")]
        self.assertEqual(chapter_labels, ["Chapter 1 — One", "Chapter 6 — Six", "Chapter 7 — Seven"])
        self.assertEqual([volume.number for volume in book.volumes], ["I", "II"])
        self.assertEqual([chapter.number for chapter in book.volumes[0].chapters], [1, 6])
        self.assertEqual([chapter.number for chapter in book.volumes[1].chapters], [7])

    def test_docx_bookmarks_are_created(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = write_source(root, "chapter.txt", "# Chapter 1 — One\n\nBody.")
            book = parse_book([source])
            enrich_publication(book)
            out = root / "out.docx"
            DocxRenderer().render(book, out)
            xml = read_docx_xml(out)

        self.assertIn('w:bookmarkStart', xml)
        self.assertIn('chapter_1', xml)

    def test_docx_internal_hyperlinks_target_valid_bookmarks(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = write_source(root, "chapter.txt", "# Chapter 1 — One\n\nSee [[REF: Chapter 1]].")
            book = parse_book([source])
            enrich_publication(book)
            out = root / "out.docx"
            DocxRenderer().render(book, out)
            xml = read_docx_xml(out)

        self.assertIn('w:hyperlink w:anchor="chapter_1"', xml)

    def test_renderer_performs_no_raw_reference_parsing(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            book = Book(
                title=TITLE,
                subtitle=SUBTITLE,
                author=AUTHOR,
                running_title=RUNNING_TITLE,
                tagline=TAGLINE,
                version="test",
                blocks=[Chapter(number=1, title="One", blocks=[Paragraph(text="[[REF: Chapter 1]]")])],
            )
            out = root / "out.docx"
            DocxRenderer().render(book, out)
            xml = read_docx_xml(out)

        self.assertIn("[[REF: Chapter 1]]", xml)

    def test_current_chapter_sources_build_without_modification(self) -> None:
        source_paths = sorted((PIPELINE_DIR / "chapters").glob("*.txt"))
        book = parse_book(source_paths)
        enrichment = enrich_publication(book)

        self.assertTrue(validate_enriched_publication(book, enrichment).ok)

    def test_compatibility_wrapper_build_document_works(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "output"
            path, version, files = build_document(
                chapters_dir=PIPELINE_DIR / "chapters",
                output_dir=output,
                basename=BASENAME,
                title=TITLE,
                subtitle=SUBTITLE,
                author=AUTHOR,
                running_title=RUNNING_TITLE,
                tagline=TAGLINE,
                start_version="1.0",
                manifest_path=root / "missing.toml",
            )
            self.assertTrue(path.exists())
            self.assertEqual(version, "1.0")
            self.assertEqual(len(files), 11)


def walk_paragraphs(book):
    stack = list(book.blocks)
    while stack:
        block = stack.pop(0)
        if isinstance(block, Paragraph):
            yield block
        for attr in ("blocks", "body"):
            stack[0:0] = list(getattr(block, attr, []))


def read_docx_xml(path: Path) -> str:
    with zipfile.ZipFile(path) as docx:
        return docx.read("word/document.xml").decode("utf-8")


if __name__ == "__main__":
    unittest.main()
