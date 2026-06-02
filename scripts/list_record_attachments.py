from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from api.attachments import ATTACHMENT_ROOT, list_record_attachments


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def build_attachment_listing(
    conn: sqlite3.Connection,
    *,
    reference: str,
    verify_files: bool = False,
    attachment_root: Path = ATTACHMENT_ROOT,
) -> dict[str, Any]:
    attachments = list_record_attachments(
        conn,
        reference=reference,
        verify_files=verify_files,
        attachment_root=attachment_root,
    )
    return {
        "reference": reference,
        "attachment_count": len(attachments),
        "verified_files": verify_files,
        "attachments": attachments,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="List local/admin attachment metadata for a CDE record."
    )
    parser.add_argument("--reference", required=True)
    parser.add_argument(
        "--db-path",
        default=os.getenv("RECORDS_DB_PATH", "records.db"),
    )
    parser.add_argument(
        "--attachment-root",
        default=os.getenv("CDE_ATTACHMENT_ROOT", str(ATTACHMENT_ROOT)),
    )
    parser.add_argument("--verify-files", action="store_true")
    parser.add_argument("--pretty", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    conn = connect(Path(args.db_path))
    try:
        payload = build_attachment_listing(
            conn,
            reference=args.reference,
            verify_files=args.verify_files,
            attachment_root=Path(args.attachment_root),
        )
    finally:
        conn.close()

    indent = 2 if args.pretty else None
    print(json.dumps(payload, indent=indent, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
