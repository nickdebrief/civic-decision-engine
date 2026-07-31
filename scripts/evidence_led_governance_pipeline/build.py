#!/usr/bin/env python3
"""Build the Evidence-Led Governance handbook through the modular engine."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Sequence

from parser import Parser
from renderers.docx_renderer import DocxRenderer
from validator import merge_results, validate_book, validate_output


PIPELINE_DIR = Path(__file__).resolve().parent
CHAPTERS_DIR = PIPELINE_DIR / "chapters"
OUTPUT_DIR = PIPELINE_DIR / "Output"

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
    if not chapters_dir.exists():
        raise FileNotFoundError(f"Chapter directory not found: {chapters_dir}")
    files = sorted(
        path
        for path in chapters_dir.glob("*.txt")
        if not path.name.startswith(("~$", "."))
    )
    if not files:
        raise FileNotFoundError(f"No chapter .txt files found in {chapters_dir}")
    return files


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
):
    chapters_path = Path(chapters_dir)
    output_path = Path(output_dir)
    files = chapter_files(chapters_path)
    version = next_version(output_path, basename, start=start_version)
    book = Parser().parse_files(
        files,
        title=title,
        subtitle=subtitle,
        author=author,
        running_title=running_title,
        tagline=tagline or "",
        version=version,
    )

    model_validation = validate_book(book)
    out_path = output_path / f"{basename}_v{version}.docx"
    if model_validation.ok:
        DocxRenderer().render(book, out_path)
    output_validation = validate_output(out_path) if out_path.exists() else validate_output(out_path)
    validation = merge_results(model_validation, output_validation)
    print(validation.render())
    if not validation.ok:
        raise RuntimeError("publication validation failed")
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
