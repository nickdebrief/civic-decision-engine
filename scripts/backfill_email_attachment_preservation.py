#!/usr/bin/env python3
"""Bounded, idempotent Stage 49 backfill for authoritative RFC 5322 intake metadata."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from api.document_intake import intake_document_file, list_intake_documents
from api.email_attachment_preservation import (
    REGISTRY_FILENAME,
    list_source_attachments,
    preserve_outlook_msg_attachments,
    preserve_rfc5322_attachments,
)


def run(*, root: Path, limit: int, dry_run: bool) -> dict[str, int]:
    counts = {
        "processed": 0,
        "created": 0,
        "linked": 0,
        "already_present": 0,
        "skipped": 0,
        "ambiguous": 0,
        "failed": 0,
    }
    candidates = [
        item
        for item in list_intake_documents(root=root)
        if item.get("document_type") in {"eml", "msg"}
        and int((item.get("email_metadata") or {}).get("attachment_count") or 0) > 0
    ][:limit]
    for document in candidates:
        counts["processed"] += 1
        existing = (
            list_source_attachments(str(document.get("intake_id") or ""), root=root)
            if (root / REGISTRY_FILENAME).exists()
            else []
        )
        if existing:
            counts["already_present"] += len(existing)
            continue
        if dry_run:
            counts["created"] += int(
                (document.get("email_metadata") or {}).get("attachment_count") or 0
            )
            continue
        try:
            file_path, _ = intake_document_file(
                str(document.get("intake_id") or ""), metadata=document, root=root
            )
            preserve_attachments = (
                preserve_outlook_msg_attachments
                if document.get("document_type") == "msg"
                else preserve_rfc5322_attachments
            )
            relationships = preserve_attachments(
                document, Path(file_path).read_bytes(), root=root
            )
        except Exception:
            counts["failed"] += 1
            continue
        counts["linked"] += len(relationships)
        counts["created"] += sum(
            1 for relationship in relationships if relationship.get("attachment_document_id")
        )
    return counts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.limit <= 0:
        parser.error("--limit must be greater than zero")
    print(json.dumps(run(root=args.root, limit=args.limit, dry_run=args.dry_run), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
