"""Manifest loading for Evidence-Led Governance publication builds."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Sequence

from model import Manifest, ParserDiagnostic


DEFAULT_GENERATED_FRONT_MATTER = {
    "table_of_contents": True,
    "governance_principles": True,
    "research_findings": True,
    "canonical_definitions": True,
    "governance_architectures": True,
    "research_methodologies": True,
    "semantic_index": True,
}


def discover_source_files(chapters_dir: Path) -> list[Path]:
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


def load_manifest(
    manifest_path: Path,
    *,
    chapters_dir: Path,
    fallback_files: Sequence[Path] | None = None,
) -> Manifest:
    diagnostics: list[ParserDiagnostic] = []
    if not manifest_path.exists():
        files = list(fallback_files) if fallback_files is not None else discover_source_files(chapters_dir)
        diagnostics.append(
            ParserDiagnostic(
                severity="WARNING",
                code="MANIFEST_MISSING",
                message="Manifest missing; using legacy chapter source discovery.",
                source_file=manifest_path,
            )
        )
        return Manifest(
            path=manifest_path,
            loaded=False,
            source_files=files,
            generated_front_matter=dict(DEFAULT_GENERATED_FRONT_MATTER),
            diagnostics=diagnostics,
        )

    data = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
    raw_sources = data.get("sources", [])
    if not isinstance(raw_sources, list):
        raise ValueError("book.toml: sources must be a list")

    seen: set[Path] = set()
    files: list[Path] = []
    for raw_source in raw_sources:
        if not isinstance(raw_source, str) or not raw_source.strip():
            raise ValueError("book.toml: each source must be a non-empty string")
        source_path = (manifest_path.parent / raw_source).resolve()
        if source_path in seen:
            raise ValueError(f"book.toml: duplicate source file: {raw_source}")
        if not source_path.exists():
            raise FileNotFoundError(f"book.toml: missing source file: {raw_source}")
        seen.add(source_path)
        files.append(source_path)

    generated = dict(DEFAULT_GENERATED_FRONT_MATTER)
    manifest_generated = data.get("generated_front_matter", {})
    if manifest_generated:
        if not isinstance(manifest_generated, dict):
            raise ValueError("book.toml: generated_front_matter must be a table")
        for key, value in manifest_generated.items():
            if key not in generated:
                raise ValueError(f"book.toml: unknown generated_front_matter option: {key}")
            if not isinstance(value, bool):
                raise ValueError(f"book.toml: generated_front_matter.{key} must be true or false")
            generated[key] = value

    if not files:
        raise ValueError("book.toml: no source files configured")

    return Manifest(
        path=manifest_path,
        loaded=True,
        source_files=files,
        generated_front_matter=generated,
        diagnostics=diagnostics,
    )
