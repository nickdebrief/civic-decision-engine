#!/usr/bin/env python3
"""Validate the canonical CDE Platform stage ledger and release notes."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
import re
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
LEDGER_RELATIVE_PATH = Path("docs/releases/CDE_PLATFORM_STAGE_LEDGER.md")
RELEASES_RELATIVE_PATH = Path("docs/releases")
README_RELATIVE_PATH = Path("README.md")
STAGE_PATTERN = re.compile(r"^[0-9]+(?:\.[0-9]+)?$")
RELEASE_HEADING_PATTERN = re.compile(
    r"^# CDE Platform Stage (?P<stage>\S+) — (?P<title>.+)$"
)
RELEASE_LINK_PATTERN = re.compile(r"\((?P<path>[^)]+\.md)\)")
CURRENT_RELEASE_PATTERN = re.compile(
    r"^Current release: CDE Platform Stage (?P<stage>\S+) — (?P<title>.+)$",
    re.MULTILINE,
)


@dataclass(frozen=True)
class StageEntry:
    stage: str
    title: str
    capability: str
    parent: str | None
    merged: str
    merge_commit: str
    pull_request: str
    release_note: str
    status: str


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def parse_ledger(path: Path) -> list[StageEntry]:
    lines = path.read_text(encoding="utf-8").splitlines()
    header = [
        "Stage",
        "Title",
        "Capability",
        "Parent",
        "Merged",
        "Merge commit",
        "PR",
        "Release note",
        "Status",
    ]
    try:
        start = next(index for index, line in enumerate(lines) if _cells(line) == header)
    except StopIteration as exc:
        raise ValueError("stage_ledger_table_missing") from exc

    entries: list[StageEntry] = []
    for line in lines[start + 2 :]:
        if not line.startswith("|"):
            break
        cells = _cells(line)
        if len(cells) != len(header):
            raise ValueError(f"stage_ledger_row_invalid: {line}")
        release_match = RELEASE_LINK_PATTERN.search(cells[7])
        if not release_match:
            raise ValueError(f"stage_ledger_release_link_invalid: {cells[0]}")
        entries.append(
            StageEntry(
                stage=cells[0].strip("`"),
                title=cells[1],
                capability=cells[2].strip("`"),
                parent=None if cells[3] in {"", "—", "-"} else cells[3].strip("`"),
                merged=cells[4],
                merge_commit=cells[5].strip("`"),
                pull_request=cells[6],
                release_note=release_match.group("path"),
                status=cells[8],
            )
        )
    return entries


def validate_entries(entries: list[StageEntry]) -> list[str]:
    errors: list[str] = []
    seen: dict[str, StageEntry] = {}
    top_level_roots: set[int] = set()
    previous: Decimal | None = None

    if not entries:
        return ["stage_ledger_empty"]

    for entry in entries:
        if not STAGE_PATTERN.fullmatch(entry.stage):
            errors.append(f"stage_identifier_invalid: {entry.stage}")
            continue
        if entry.stage in seen:
            errors.append(f"stage_identifier_duplicate: {entry.stage}")
            if "." not in entry.stage:
                errors.append(f"stage_root_duplicate: {entry.stage}")
            continue

        value = Decimal(entry.stage)
        if previous is not None and value <= previous:
            errors.append(
                f"stage_chronology_not_monotonic: {entry.stage} follows {previous}"
            )
        previous = value

        if "." not in entry.stage:
            root = int(entry.stage)
            if root in top_level_roots:
                errors.append(f"stage_root_duplicate: {root}")
            top_level_roots.add(root)
            if entry.parent is not None:
                errors.append(f"top_level_stage_has_parent: {entry.stage}")
        else:
            expected_parent = entry.stage.split(".", 1)[0]
            if entry.parent != expected_parent:
                errors.append(
                    f"suffix_parent_invalid: {entry.stage} expected {expected_parent}"
                )
            parent = seen.get(expected_parent)
            if parent is None:
                errors.append(f"suffix_parent_missing: {entry.stage}")
            elif parent.capability != entry.capability:
                errors.append(
                    "suffix_parent_capability_mismatch: "
                    f"{entry.stage}={entry.capability}, "
                    f"{expected_parent}={parent.capability}"
                )

        if not re.fullmatch(r"[0-9a-f]{40}", entry.merge_commit):
            errors.append(f"merge_commit_invalid: {entry.stage}")
        required_statuses = ("implemented", "merged", "deployed")
        normalized_status = entry.status.casefold()
        if not all(value in normalized_status for value in required_statuses):
            errors.append(f"stage_status_incomplete: {entry.stage}")
        seen[entry.stage] = entry

    return errors


def validate_repository(repository_root: Path = REPOSITORY_ROOT) -> list[str]:
    ledger_path = repository_root / LEDGER_RELATIVE_PATH
    releases_root = repository_root / RELEASES_RELATIVE_PATH
    readme_path = repository_root / README_RELATIVE_PATH
    try:
        entries = parse_ledger(ledger_path)
    except (OSError, ValueError) as exc:
        return [str(exc)]

    errors = validate_entries(entries)
    ledger_stages = {entry.stage for entry in entries}
    documented_stages: dict[str, Path] = {}

    for release_path in sorted(releases_root.glob("*.md")):
        first_line = release_path.read_text(encoding="utf-8").splitlines()[0]
        match = RELEASE_HEADING_PATTERN.fullmatch(first_line)
        if not match:
            continue
        token = match.group("stage")
        root_match = re.match(r"^[0-9]+", token)
        if not root_match or int(root_match.group()) < 40:
            continue
        if not STAGE_PATTERN.fullmatch(token):
            errors.append(f"release_stage_identifier_invalid: {release_path.name}={token}")
            continue
        if token in documented_stages:
            errors.append(
                f"release_stage_duplicate: {token} in "
                f"{documented_stages[token].name} and {release_path.name}"
            )
        documented_stages[token] = release_path

    if set(documented_stages) != ledger_stages:
        missing = sorted(ledger_stages - set(documented_stages), key=Decimal)
        unindexed = sorted(set(documented_stages) - ledger_stages, key=Decimal)
        if missing:
            errors.append(f"ledger_release_notes_missing: {', '.join(missing)}")
        if unindexed:
            errors.append(f"release_notes_unindexed: {', '.join(unindexed)}")

    for entry in entries:
        release_path = releases_root / entry.release_note
        if not release_path.is_file():
            errors.append(f"release_note_missing: {entry.stage}={entry.release_note}")
            continue
        expected_heading = f"# CDE Platform Stage {entry.stage} — {entry.title}"
        actual_heading = release_path.read_text(encoding="utf-8").splitlines()[0]
        if actual_heading != expected_heading:
            errors.append(
                f"release_heading_mismatch: {entry.stage} expected {expected_heading!r}"
            )

    current_match = CURRENT_RELEASE_PATTERN.search(
        readme_path.read_text(encoding="utf-8")
    )
    latest = entries[-1]
    if current_match is None:
        errors.append("readme_current_release_missing")
    elif (current_match.group("stage"), current_match.group("title")) != (
        latest.stage,
        latest.title,
    ):
        errors.append(
            "readme_current_release_mismatch: "
            f"expected {latest.stage} — {latest.title}"
        )

    return errors


def main() -> int:
    errors = validate_repository()
    if errors:
        print("CDE Platform stage ledger validation: FAIL")
        for error in errors:
            print(f"- {error}")
        return 1
    print("CDE Platform stage ledger validation: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
