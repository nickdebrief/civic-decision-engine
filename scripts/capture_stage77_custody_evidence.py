#!/usr/bin/env python3
"""Offline fail-closed verifier for one controller-created Stage 77 source package.

Capture itself is separately governed and never initiated by this application.
This command accepts only an evidence-set identity and verifies the fixed source
layout before the recovery-management tool may copy it into the private store.
"""
from __future__ import annotations

import argparse
import os
import stat
from pathlib import Path

from api.governed_custody_evidence import ROLES, _identifier, strict_json
try:  # Supports both ``python scripts/...`` and module invocation.
    from scripts.manage_stage77_recovery import (
        EVIDENCE_AUTHORITY_FIELDS, EVIDENCE_AUTHORITY_FILENAME,
        EVIDENCE_CAPTURE_ROOT_ENV, EVIDENCE_OBJECT_FILENAMES,
    )
except ModuleNotFoundError:  # pragma: no cover - direct-script import path.
    from manage_stage77_recovery import (
        EVIDENCE_AUTHORITY_FIELDS, EVIDENCE_AUTHORITY_FILENAME,
        EVIDENCE_CAPTURE_ROOT_ENV, EVIDENCE_OBJECT_FILENAMES,
    )


def _root() -> Path:
    value = os.environ.get(EVIDENCE_CAPTURE_ROOT_ENV, "")
    if not value or not os.path.isabs(value):
        raise ValueError("stage77_custody_evidence_capture_source_unavailable")
    root = Path(value)
    if root.is_symlink() or not root.is_dir() or root.stat().st_mode & 0o077:
        raise ValueError("stage77_custody_evidence_capture_source_unavailable")
    return root


def _stable_regular(path: Path, parent: Path) -> bytes:
    if path.parent != parent or path.is_symlink() or not path.is_file():
        raise ValueError("stage77_custody_evidence_capture_object_missing")
    before = path.stat()
    if not stat.S_ISREG(before.st_mode):
        raise ValueError("stage77_custody_evidence_capture_object_missing")
    value = path.read_bytes()
    after = path.stat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        raise ValueError("stage77_custody_evidence_capture_object_changed")
    return value


def verify_capture_source(evidence_set_id: str) -> dict[str, object]:
    """Verify the exact retained-source layout without registering anything."""
    _identifier(evidence_set_id)
    root = _root()
    package = root / evidence_set_id
    if package.parent != root or package.is_symlink() or not package.is_dir():
        raise ValueError("stage77_custody_evidence_capture_source_unavailable")
    expected = {EVIDENCE_AUTHORITY_FILENAME, *EVIDENCE_OBJECT_FILENAMES.values()}
    if {item.name for item in package.iterdir()} != expected:
        raise ValueError("stage77_custody_evidence_capture_layout_invalid")
    authority = strict_json(_stable_regular(package / EVIDENCE_AUTHORITY_FILENAME, package).decode("utf-8"))
    if set(authority) != EVIDENCE_AUTHORITY_FIELDS or authority.get("id") != evidence_set_id:
        raise ValueError("stage77_custody_evidence_capture_authority_invalid")
    for role in ROLES:
        strict_json(_stable_regular(package / EVIDENCE_OBJECT_FILENAMES[role], package).decode("utf-8"))
    return {"id": evidence_set_id, "role_count": len(ROLES), "status": "source_verified"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="capture_stage77_custody_evidence")
    commands = parser.add_subparsers(dest="command", required=True)
    verify = commands.add_parser("verify-source")
    verify.add_argument("--evidence-set-id", required=True)
    args = parser.parse_args(argv)
    try:
        result = verify_capture_source(args.evidence_set_id)
    except ValueError as exc:
        print(f"stage77_custody_evidence=failed code={exc}")
        return 1
    print(f"stage77_custody_evidence={result['status']} evidence_set={result['id']} roles={result['role_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
