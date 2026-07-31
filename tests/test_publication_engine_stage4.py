from __future__ import annotations

import re
import sys
import tempfile
import unittest
import zipfile
from dataclasses import replace
from pathlib import Path

from docx import Document


PIPELINE_DIR = Path(__file__).resolve().parents[1] / "scripts" / "evidence_led_governance_pipeline"
sys.path.insert(0, str(PIPELINE_DIR))

from manifest import load_manifest, resolve_output_directory  # noqa: E402
from model import AssetConfig, Book, Chapter, Manifest, Paragraph, PublicationConfig  # noqa: E402
from parser import Parser  # noqa: E402
from publication import enrich_publication  # noqa: E402
from renderers.docx_renderer import DocxRenderer  # noqa: E402
from theme_resolution import resolve_theme, validate_page, validate_theme  # noqa: E402
from themes.handbook import HANDBOOK_THEME  # noqa: E402
from themes.registry import get_page_profile, get_publication_profile, get_theme  # noqa: E402


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")
    return path


def manifest_text(*, theme: str = "handbook", profile: str = "digital", page: str = "letter", extra: str = "") -> str:
    return f'''\
schema_version = 1
sources = ["chapters/chapter.txt"]

[publication]
title = "Test Book"
subtitle = "Test Subtitle"
author = "Test Author"
language = "en"
edition = "Test Edition"
theme = "{theme}"

[output]
basename = "Test_Book"
directory = "output"
formats = ["docx"]
profile = "{profile}"

[layout]
page_profile = "{page}"

{extra}
'''


def fixture_manifest(root: Path, **kwargs) -> Manifest:
    write(root / "chapters" / "chapter.txt", "# Chapter 1 — Test\n\nBody.")
    path = write(root / "book.toml", manifest_text(**kwargs))
    return load_manifest(path, chapters_dir=root / "chapters")


def minimal_book() -> Book:
    book = Book(
        title="Test Book",
        subtitle="Test Subtitle",
        author="Test Author",
        running_title="TEST BOOK",
        tagline="Structured · Traceable · Governed",
        version="1.0",
        metadata={
            "language": "en",
            "edition": "Test Edition",
            "keywords": "governance, evidence",
            "comments": "Stage 4 test",
            "build_identifier": "test-build",
        },
        blocks=[Chapter(number=1, title="Test", blocks=[Paragraph(text="Body.")])],
    )
    enrich_publication(book, {"semantic_index": True})
    return book


class PublicationEngineStage4Tests(unittest.TestCase):
    def test_manifest_schema_version_loads(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            manifest = fixture_manifest(Path(temp))
        self.assertEqual(manifest.schema_version, 1)

    def test_unsupported_schema_version_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write(root / "chapters" / "chapter.txt", "# Chapter 1 — Test")
            path = write(root / "book.toml", 'schema_version = 2\nsources = ["chapters/chapter.txt"]')
            with self.assertRaisesRegex(ValueError, "unsupported schema_version"):
                load_manifest(path, chapters_dir=root / "chapters")

    def test_missing_schema_version_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write(root / "chapters" / "chapter.txt", "# Chapter 1 — Test")
            path = write(root / "book.toml", 'sources = ["chapters/chapter.txt"]')
            with self.assertRaisesRegex(ValueError, "schema_version is required"):
                load_manifest(path, chapters_dir=root / "chapters")

    def test_handbook_theme_resolves(self) -> None:
        self.assertEqual(get_theme("handbook").name, "handbook")

    def test_unknown_theme_fails(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unknown publication theme"):
            get_theme("unknown")

    def test_cde_theme_resolves(self) -> None:
        self.assertEqual(get_theme("cde").publication_name, "Civic Decision Engine")

    def test_cref_theme_resolves(self) -> None:
        self.assertEqual(get_theme("cref").publication_name, "Civic Record Exchange Framework")

    def test_publication_profiles_resolve(self) -> None:
        self.assertEqual([get_publication_profile(name).name for name in ("digital", "print", "archive")], ["digital", "print", "archive"])

    def test_page_profiles_resolve(self) -> None:
        self.assertEqual([get_page_profile(name).name for name in ("letter", "a4", "book_6x9")], ["letter", "a4", "book_6x9"])

    def test_missing_theme_token_fails_validation(self) -> None:
        broken = replace(HANDBOOK_THEME, typography=replace(HANDBOOK_THEME.typography, body_font=""))
        with self.assertRaisesRegex(ValueError, "Missing required theme token"):
            validate_theme(broken)

    def test_invalid_colour_fails_validation(self) -> None:
        broken = replace(HANDBOOK_THEME, colours=replace(HANDBOOK_THEME.colours, primary="navy"))
        with self.assertRaisesRegex(ValueError, "Invalid theme colour"):
            validate_theme(broken)

    def test_invalid_margins_fail_validation(self) -> None:
        page = replace(get_page_profile("letter"), margin_left_inches=5.0, margin_right_inches=5.0)
        with self.assertRaisesRegex(ValueError, "margins exceed"):
            validate_page(page)

    def test_templates_resolve(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = fixture_manifest(root, extra='''
[title_page]
template = "minimal"
[volume_page]
template = "handbook"
[chapter_opening]
template = "display"
''')
            effective = resolve_theme(manifest, assets_dir=root / "assets").effective_theme
        self.assertEqual((effective.title_page.template, effective.volume_page.template, effective.chapter_opening.template), ("minimal", "handbook", "display"))

    def test_semantic_callout_types_receive_distinct_styles(self) -> None:
        styles = HANDBOOK_THEME.callouts.styles
        semantic = [styles[name] for name in ("Governance Principle", "Research Finding", "Canonical Definition", "Governance Architecture", "Research Methodology")]
        self.assertEqual(len({style.fill for style in semantic}), len(semantic))

    def test_renderer_contains_no_hard_coded_handbook_colours_or_fonts(self) -> None:
        source = (PIPELINE_DIR / "renderers" / "docx_renderer.py").read_text(encoding="utf-8")
        self.assertNotIn("0F5F73", source)
        self.assertNotIn("Aptos", source)
        self.assertIsNone(re.search(r'RGBColor\(0x[0-9A-Fa-f]+', source))

    def test_manifest_metadata_populates_docx_properties(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "metadata.docx"
            DocxRenderer().render(minimal_book(), out)
            props = Document(out).core_properties
        self.assertEqual(props.title, "Test Book")
        self.assertEqual(props.category, "Test Edition")
        self.assertEqual(props.keywords, "governance, evidence")
        self.assertEqual(props.language, "en")

    def test_missing_optional_asset_produces_warning(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = fixture_manifest(root)
            manifest.assets["emblem"] = AssetConfig("missing.png", False, "emblem")
            result = resolve_theme(manifest, assets_dir=root / "assets")
        self.assertEqual(result.diagnostics[0].code, "OPTIONAL_ASSET_MISSING")

    def test_missing_required_asset_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = fixture_manifest(root)
            manifest.assets["emblem"] = AssetConfig("missing.png", True, "emblem")
            with self.assertRaises(FileNotFoundError):
                resolve_theme(manifest, assets_dir=root / "assets")

    def test_output_path_cannot_escape_pipeline_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = fixture_manifest(root)
            manifest.output = replace(manifest.output, directory="../outside")
            with self.assertRaisesRegex(ValueError, "escapes"):
                resolve_output_directory(manifest, root / "fallback")

    def test_compatibility_renderer_defaults_to_handbook(self) -> None:
        self.assertEqual(DocxRenderer().effective.name, "handbook")

    def test_existing_chapter_sources_build_unchanged(self) -> None:
        sources = sorted((PIPELINE_DIR / "chapters").glob("*.txt"))
        before = {path: path.read_bytes() for path in sources}
        book = Parser().parse_files(sources, title="Evidence-Led Governance", subtitle="Method", author="Nick Moloney", running_title="EVIDENCE-LED GOVERNANCE", tagline="", version="test")
        enrich_publication(book)
        self.assertEqual(before, {path: path.read_bytes() for path in sources})

    def test_current_handbook_preserves_source_paragraph_text(self) -> None:
        sources = sorted((PIPELINE_DIR / "chapters").glob("*.txt"))
        book = Parser().parse_files(sources, title="Evidence-Led Governance", subtitle="Method", author="Nick Moloney", running_title="EVIDENCE-LED GOVERNANCE", tagline="", version="test")
        rendered_text = "\n".join(block.text for block in walk(book) if isinstance(block, Paragraph))
        self.assertIn("Evidence-Led Governance", rendered_text)
        self.assertIn("Chapter Synthesis", "\n".join(getattr(block, "title", "") for block in walk(book)))

    def test_cde_and_cref_theme_smoke_builds_succeed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ("cde", "cref"):
                manifest = Manifest(publication=PublicationConfig(theme=name))
                effective = resolve_theme(manifest, assets_dir=root / "assets").effective_theme
                out = root / f"{name}.docx"
                DocxRenderer(effective).render(minimal_book(), out)
                self.assertGreater(out.stat().st_size, 0)

    def test_theme_resolution_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = fixture_manifest(root)
            first = resolve_theme(manifest, assets_dir=root / "assets").effective_theme
            second = resolve_theme(manifest, assets_dir=root / "assets").effective_theme
        self.assertEqual(first, second)

    def test_bookmarks_and_hyperlinks_remain_in_digital_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "links.docx"
            DocxRenderer().render(minimal_book(), out)
            with zipfile.ZipFile(out) as package:
                xml = package.read("word/document.xml").decode("utf-8")
        self.assertIn("w:bookmarkStart", xml)
        self.assertIn("w:hyperlink", xml)


def walk(root):
    stack = list(getattr(root, "blocks", []))
    while stack:
        block = stack.pop(0)
        yield block
        stack[0:0] = list(getattr(block, "blocks", [])) + list(getattr(block, "body", []))


if __name__ == "__main__":
    unittest.main()
