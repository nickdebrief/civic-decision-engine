"""Typed, schema-versioned manifest loading for publication builds."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any, Sequence

from model import (
    AssetConfig,
    ChapterOpeningConfig,
    LayoutConfig,
    Manifest,
    MetadataConfig,
    OutputConfig,
    ParserDiagnostic,
    PublicationConfig,
    PublicationIdentityConfig,
    TitlePageConfig,
    VersionConfig,
    VolumePageConfig,
)


SUPPORTED_SCHEMA_VERSIONS = {1}
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
    files = sorted(path for path in chapters_dir.glob("*.txt") if not path.name.startswith(("~$", ".")))
    if not files:
        raise FileNotFoundError(f"No chapter .txt files found in {chapters_dir}")
    return files


def _table(data: dict[str, Any], name: str) -> dict[str, Any]:
    value = data.get(name, {})
    if not isinstance(value, dict):
        raise ValueError(f"book.toml: {name} must be a table")
    return value


def _string(table: dict[str, Any], name: str, default: str) -> str:
    value = table.get(name, default)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"book.toml: {name} must be a non-empty string")
    return value.strip()


def _boolean(table: dict[str, Any], name: str, default: bool) -> bool:
    value = table.get(name, default)
    if not isinstance(value, bool):
        raise ValueError(f"book.toml: {name} must be true or false")
    return value


def _load_sources(data: dict[str, Any], manifest_path: Path) -> list[Path]:
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
    if not files:
        raise ValueError("book.toml: no source files configured")
    return files


def _load_generated(data: dict[str, Any]) -> dict[str, bool]:
    generated = dict(DEFAULT_GENERATED_FRONT_MATTER)
    raw = _table(data, "generated_front_matter")
    for key, value in raw.items():
        if key not in generated:
            raise ValueError(f"book.toml: unknown generated_front_matter option: {key}")
        if not isinstance(value, bool):
            raise ValueError(f"book.toml: generated_front_matter.{key} must be true or false")
        generated[key] = value
    return generated


def _load_assets(data: dict[str, Any]) -> dict[str, AssetConfig]:
    assets: dict[str, AssetConfig] = {}
    for name, raw in _table(data, "assets").items():
        if isinstance(raw, str):
            assets[name] = AssetConfig(path=raw, role=name)
            continue
        if not isinstance(raw, dict):
            raise ValueError(f"book.toml: assets.{name} must be a string or table")
        assets[name] = AssetConfig(
            path=_string(raw, "path", ""),
            required=_boolean(raw, "required", False),
            role=_string(raw, "role", name),
        )
    return assets


def _fallback_manifest(path: Path, files: list[Path]) -> Manifest:
    diagnostic = ParserDiagnostic(
        severity="WARNING",
        code="MANIFEST_MISSING",
        message="Manifest missing; using legacy discovery and the handbook/digital/letter defaults.",
        source_file=path,
    )
    return Manifest(
        path=path,
        loaded=False,
        schema_version=1,
        source_files=files,
        generated_front_matter=dict(DEFAULT_GENERATED_FRONT_MATTER),
        diagnostics=[diagnostic],
    )


def load_manifest(
    manifest_path: Path,
    *,
    chapters_dir: Path,
    fallback_files: Sequence[Path] | None = None,
) -> Manifest:
    if not manifest_path.exists():
        files = list(fallback_files) if fallback_files is not None else discover_source_files(chapters_dir)
        return _fallback_manifest(manifest_path, files)

    data = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
    if "schema_version" not in data:
        raise ValueError("book.toml: schema_version is required")
    schema_version = data["schema_version"]
    if not isinstance(schema_version, int) or schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        raise ValueError(f"book.toml: unsupported schema_version: {schema_version!r}")

    publication_raw = _table(data, "publication")
    identity_raw = _table(publication_raw, "identity")
    publication = PublicationConfig(
        title=_string(publication_raw, "title", PublicationConfig.title),
        subtitle=_string(publication_raw, "subtitle", PublicationConfig.subtitle),
        author=_string(publication_raw, "author", PublicationConfig.author),
        language=_string(publication_raw, "language", PublicationConfig.language),
        edition=_string(publication_raw, "edition", PublicationConfig.edition),
        theme=_string(publication_raw, "theme", PublicationConfig.theme).casefold(),
        identity=PublicationIdentityConfig(
            running_title=_string(identity_raw, "running_title", PublicationIdentityConfig.running_title),
            tagline=_string(identity_raw, "tagline", PublicationIdentityConfig.tagline),
        ),
    )

    version_raw = _table(data, "version")
    version = VersionConfig(
        mode=_string(version_raw, "mode", VersionConfig.mode),
        start=_string(version_raw, "start", VersionConfig.start),
    )
    if version.mode not in {"auto", "fixed"}:
        raise ValueError("book.toml: version.mode must be 'auto' or 'fixed'")

    output_raw = _table(data, "output")
    formats = output_raw.get("formats", ["docx"])
    if not isinstance(formats, list) or not formats or not all(isinstance(item, str) for item in formats):
        raise ValueError("book.toml: output.formats must be a non-empty string list")
    if any(item.casefold() != "docx" for item in formats):
        raise ValueError(f"book.toml: unsupported output format: {formats}")
    output = OutputConfig(
        basename=_string(output_raw, "basename", OutputConfig.basename),
        directory=_string(output_raw, "directory", OutputConfig.directory),
        formats=tuple(item.casefold() for item in formats),
        profile=_string(output_raw, "profile", OutputConfig.profile).casefold(),
    )

    layout_raw = _table(data, "layout")
    layout = LayoutConfig(
        page_profile=_string(layout_raw, "page_profile", LayoutConfig.page_profile).casefold(),
        chapter_starts_on_new_page=_boolean(layout_raw, "chapter_starts_on_new_page", True),
        volume_starts_on_new_page=_boolean(layout_raw, "volume_starts_on_new_page", True),
        suppress_header_on_title_page=_boolean(layout_raw, "suppress_header_on_title_page", True),
        suppress_footer_on_title_page=_boolean(layout_raw, "suppress_footer_on_title_page", True),
    )

    title_raw = _table(data, "title_page")
    title_page = TitlePageConfig(
        template=_string(title_raw, "template", TitlePageConfig.template).casefold(),
        show_author=_boolean(title_raw, "show_author", True),
        show_version=_boolean(title_raw, "show_version", True),
        show_tagline=_boolean(title_raw, "show_tagline", True),
        show_date=_boolean(title_raw, "show_date", False),
    )
    volume_raw = _table(data, "volume_page")
    volume_page = VolumePageConfig(
        template=_string(volume_raw, "template", VolumePageConfig.template).casefold(),
        suppress_header=_boolean(volume_raw, "suppress_header", False),
        suppress_footer=_boolean(volume_raw, "suppress_footer", False),
    )
    chapter_raw = _table(data, "chapter_opening")
    chapter_opening = ChapterOpeningConfig(
        template=_string(chapter_raw, "template", ChapterOpeningConfig.template).casefold(),
    )

    metadata_raw = _table(data, "metadata")
    keywords = metadata_raw.get("keywords", [])
    if not isinstance(keywords, list) or not all(isinstance(item, str) and item.strip() for item in keywords):
        raise ValueError("book.toml: metadata.keywords must be a string list")
    metadata = MetadataConfig(
        keywords=tuple(item.strip() for item in keywords),
        comments=str(metadata_raw.get("comments", "")).strip(),
        build_identifier=str(metadata_raw.get("build_identifier", "")).strip(),
    )

    return Manifest(
        path=manifest_path,
        loaded=True,
        schema_version=schema_version,
        source_files=_load_sources(data, manifest_path),
        generated_front_matter=_load_generated(data),
        publication=publication,
        version=version,
        output=output,
        layout=layout,
        title_page=title_page,
        volume_page=volume_page,
        chapter_opening=chapter_opening,
        metadata=metadata,
        assets=_load_assets(data),
    )


def resolve_output_directory(manifest: Manifest, fallback: Path) -> Path:
    if not manifest.loaded or manifest.path is None:
        return fallback
    pipeline_root = manifest.path.parent.resolve()
    output = (pipeline_root / manifest.output.directory).resolve()
    if pipeline_root not in output.parents and output != pipeline_root:
        raise ValueError(f"book.toml: output.directory escapes the pipeline root: {manifest.output.directory}")
    return output
