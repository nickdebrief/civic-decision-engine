"""Deterministic publication-package metadata and checksum generation."""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from model import Book, Manifest


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifact_files(path: Path) -> list[Path]:
    if path.is_dir():
        return sorted(item for item in path.rglob("*") if item.is_file())
    return [path]


def git_commit(repository: Path) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return completed.stdout.strip() if completed.returncode == 0 else ""


@dataclass(frozen=True)
class PackageResult:
    build_report: Path | None
    checksums: Path | None
    manifest: Path
    checksum_count: int
    output_file_count: int


def create_package(
    *,
    package_dir: Path,
    stem: str,
    repository: Path,
    book: Book,
    manifest: Manifest,
    artifacts: dict[str, Path],
    build_report_text: str,
    renderer_versions: dict[str, str],
    validation_status: str,
) -> PackageResult:
    package_dir.mkdir(parents=True, exist_ok=True)
    report_path = package_dir / f"{stem}_build_report.txt" if manifest.output.package.include_build_report else None
    if report_path is not None:
        report_path.write_text(build_report_text.rstrip() + "\n", encoding="utf-8", newline="\n")

    checksum_targets: list[tuple[str, Path]] = []
    for source in manifest.source_files:
        checksum_targets.append((f"source/{source.name}", source))
    if manifest.path and manifest.path.is_file():
        checksum_targets.append((manifest.path.name, manifest.path))
    for format_name, artifact in sorted(artifacts.items()):
        for path in artifact_files(artifact):
            label = path.name if artifact.is_file() else f"{artifact.name}/{path.relative_to(artifact)}"
            checksum_targets.append((label, path))
    if report_path is not None:
        checksum_targets.append((report_path.name, report_path))
    checksums = {label: sha256_file(path) for label, path in sorted(checksum_targets)}

    checksum_path = package_dir / f"{stem}_checksums.txt" if manifest.output.package.include_checksums else None
    if checksum_path is not None:
        lines = [f"{digest}  {label}" for label, digest in sorted(checksums.items())]
        checksum_path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")

    output_files = []
    for format_name, artifact in sorted(artifacts.items()):
        for path in artifact_files(artifact):
            label = path.name if artifact.is_file() else f"{artifact.name}/{path.relative_to(artifact)}"
            output_files.append(
                {
                    "format": format_name,
                    "path": label,
                    "size_bytes": path.stat().st_size,
                    "sha256": checksums[label],
                }
            )
    package_manifest = {
        "build": {
            "git_commit": git_commit(repository),
            "timestamp_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "validation_status": validation_status,
        },
        "outputs": output_files,
        "package": {
            "build_report": report_path.name if report_path else None,
            "checksums": checksum_path.name if checksum_path else None,
        },
        "publication": {
            "author": book.author,
            "page_profile": manifest.layout.page_profile,
            "profile": manifest.output.profile,
            "theme": manifest.publication.theme,
            "title": book.title,
            "version": book.version,
        },
        "renderers": dict(sorted(renderer_versions.items())),
        "schema_version": 1,
        "sources": [
            {"path": source.name, "sha256": checksums[f"source/{source.name}"]}
            for source in manifest.source_files
        ],
    }
    manifest_path = package_dir / f"{stem}_manifest.json"
    manifest_path.write_text(json.dumps(package_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return PackageResult(report_path, checksum_path, manifest_path, len(checksums), len(output_files))
