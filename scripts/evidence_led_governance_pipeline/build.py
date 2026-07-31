#!/usr/bin/env python3
"""Build the Evidence-Led Governance handbook through the modular engine."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Sequence

from manifest import discover_source_files, load_manifest
from parser import Parser
from publication import enrich_publication
from renderers.docx_renderer import DocxRenderer
from validator import merge_results, validate_book, validate_enriched_publication, validate_output


PIPELINE_DIR = Path(__file__).resolve().parent
CHAPTERS_DIR = PIPELINE_DIR / "chapters"
OUTPUT_DIR = PIPELINE_DIR / "Output"
MANIFEST_PATH = PIPELINE_DIR / "book.toml"

TITLE = "Evidence-Led Governance"
SUBTITLE = "A Research Methodology for Analysing Statutory Administration"
AUTHOR = "Nick Moloney"
RUNNING_TITLE = "EVIDENCE-LED GOVERNANCE"
TAGLINE = "Structured · Traceable · Governed"
BASENAME = "Evidence-Led_Governance"


def next_version(output_dir: Path, basename: str, start: str = "1.0") -> str:
    output_dir.mkdir(parents=True, exist_ok=True)
    versions: list[tuple[int, int]] = []
    for path in output_dir.glob(f"{basename}_v*.docx"):
        match = re.search(r"_v(\d+)\.(\d+)\.docx$", path.name)
        if match:
            versions.append((int(match.group(1)), int(match.group(2))))
    if not versions:
        return start
    major, minor = max(versions)
    return f"{major}.{minor + 1}"


def chapter_files(chapters_dir: Path) -> list[Path]:
    return discover_source_files(chapters_dir)


def build_document(
    *,
    chapters_dir,
    output_dir,
    basename: str,
    title: str,
    subtitle: str,
    author: str,
    running_title: str,
    tagline: str | None = None,
    start_version: str = "1.0",
    manifest_path: Path | None = None,
):
    chapters_path = Path(chapters_dir)
    output_path = Path(output_dir)
    manifest = load_manifest(
        Path(manifest_path) if manifest_path else MANIFEST_PATH,
        chapters_dir=chapters_path,
        fallback_files=chapter_files(chapters_path),
    )
    files = manifest.source_files
    version = next_version(output_path, basename, start=start_version)
    parser = Parser()
    book = parser.parse_files(
        files,
        title=title,
        subtitle=subtitle,
        author=author,
        running_title=running_title,
        tagline=tagline or "",
        version=version,
    )
    book.diagnostics.extend(manifest.diagnostics)
    book.metadata["manifest_loaded"] = "true" if manifest.loaded else "false"
    book.metadata["manifest_path"] = str(manifest.path or "")

    model_validation = validate_book(book)
    enrichment = enrich_publication(book, manifest.generated_front_matter)
    enrichment_validation = validate_enriched_publication(book, enrichment)
    out_path = output_path / f"{basename}_v{version}.docx"
    preflight_validation = merge_results(model_validation, enrichment_validation)
    if preflight_validation.ok:
        DocxRenderer().render(book, out_path)
    output_validation = validate_output(out_path) if out_path.exists() else validate_output(out_path)
    validation = merge_results(model_validation, enrichment_validation, output_validation)
    print(validation.render())
    if not validation.ok:
        raise RuntimeError("publication validation failed")
    print("")
    print("Build Summary")
    print(f"Manifest loaded: {'yes' if manifest.loaded else 'no'}")
    print(f"Source files resolved: {len(files)}")
    print(f"Reference targets: {enrichment.reference_target_count}")
    print(f"Cross-references: {enrichment.cross_reference_count}")
    print(f"Generated sections: {enrichment.generated_section_count}")
    print(f"Index entries: {enrichment.index_entry_count}")
    print(f"Bookmarks: {enrichment.bookmark_count}")
    print(f"Internal links: {enrichment.hyperlink_count}")
    print(f"Unresolved references: {enrichment.unresolved_reference_count}")
    return out_path, version, files


def main() -> int:
    out_path, version, files = build_document(
        chapters_dir=CHAPTERS_DIR,
        output_dir=OUTPUT_DIR,
        basename=BASENAME,
        title=TITLE,
        subtitle=SUBTITLE,
        author=AUTHOR,
        running_title=RUNNING_TITLE,
        tagline=TAGLINE,
        start_version="1.0",
    )
    print("")
    print(f"Built version {version}")
    print(f"Chapters included: {len(files)}")
    for chapter in files:
        print(f"  - {chapter.name}")
    print(f"Saved to: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
