#!/usr/bin/env python3
"""Bounded, idempotent email attachment preservation backfill.

Supports authoritative RFC 5322 (``.eml``), standalone Outlook (``.msg``),
standalone Apple Mail (``.emlx``), and Apple Mail mailbox (``.mbox``) intake
records. By default the command scans eligible candidates up to ``--limit``.
When ``--intake-id`` is supplied it targets exactly one existing intake document
and ignores ``--limit`` for candidate selection. Dry-run is strictly write-free
in both modes.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from api.document_intake import intake_document_file, list_intake_documents, load_pending_document
from api.email_attachment_preservation import (
    REGISTRY_FILENAME,
    list_archive_attachments,
    list_source_attachments,
    preserve_apple_emlx_attachments,
    preserve_mbox_message_attachments,
    preserve_outlook_msg_attachments,
    preserve_rfc5322_attachments,
)


SUPPORTED_TARGET_TYPES = {"eml", "msg", "emlx", "mbox"}


def _empty_counts() -> dict[str, int]:
    return {
        "processed": 0,
        "created": 0,
        "linked": 0,
        "already_present": 0,
        "skipped": 0,
        "ambiguous": 0,
        "failed": 0,
    }


def _select_targeted_document(intake_id: str, *, root: Path) -> tuple[dict | None, str | None]:
    """Load one intake document and validate it is a preservation candidate.

    Returns ``(document, None)`` when the document is an eligible candidate, or
    ``(None, reason)`` when it must be skipped. Performs no writes.
    """

    try:
        document = load_pending_document(intake_id, root=root)
    except ValueError:
        return None, "intake_not_found"
    if document.get("document_type") not in SUPPORTED_TARGET_TYPES:
        return None, "unsupported_document_type"
    if int((document.get("email_metadata") or {}).get("attachment_count") or 0) <= 0:
        return None, "no_attachments"
    return document, None


def _process_document(document: dict, *, root: Path, dry_run: bool, counts: dict[str, int]) -> None:
    """Process one candidate document, updating ``counts`` in place.

    Shared by the default scan and the targeted path so idempotency, dry-run,
    and counting semantics stay identical. mbox containers are handled as a
    distinct per-message path: the archive-level query (source_archive_identifier)
    is used for the already_present check, and each parsed message's exact RFC
    5322 byte range is recovered from the preserved mailbox file.
    """

    counts["processed"] += 1
    is_mbox = document.get("document_type") == "mbox"
    if is_mbox:
        existing = (
            list_archive_attachments(str(document.get("intake_id") or ""), root=root)
            if (root / REGISTRY_FILENAME).exists()
            else []
        )
    else:
        existing = (
            list_source_attachments(str(document.get("intake_id") or ""), root=root)
            if (root / REGISTRY_FILENAME).exists()
            else []
        )
    if existing:
        counts["already_present"] += len(existing)
        return
    if dry_run:
        # Dry-run uses the authoritative parsed mailbox metadata attachment
        # total. For mbox this counts all source-reported attachment
        # occurrences across contained messages; actual preservation results
        # may differ (e.g. zero-byte occurrences become failed rows rather
        # than Published Documents).
        counts["created"] += int(
            (document.get("email_metadata") or {}).get("attachment_count") or 0
        )
        return
    try:
        file_path, _ = intake_document_file(
            str(document.get("intake_id") or ""), metadata=document, root=root
        )
        if is_mbox:
            mbox_relationships = []
            for message in (document.get("email_metadata") or {}).get("messages") or []:
                if not message.get("parsed") or int(
                    message.get("attachment_count") or 0
                ) <= 0:
                    continue
                byte_start = int(message.get("byte_start") or 0)
                byte_end = int(message.get("byte_end") or 0)
                if byte_end <= byte_start:
                    continue
                with Path(file_path).open("rb") as mbox_handle:
                    mbox_handle.seek(byte_start)
                    message_bytes = mbox_handle.read(byte_end - byte_start)
                mbox_relationships.extend(
                    preserve_mbox_message_attachments(
                        document,
                        message_bytes,
                        message_index=int(message.get("message_index") or 0),
                        root=root,
                    )
                )
            relationships = mbox_relationships
        else:
            preserve_attachments = {
                "msg": preserve_outlook_msg_attachments,
                "emlx": preserve_apple_emlx_attachments,
            }.get(document.get("document_type"), preserve_rfc5322_attachments)
            relationships = preserve_attachments(
                document, Path(file_path).read_bytes(), root=root
            )
    except Exception:
        counts["failed"] += 1
        return
    counts["linked"] += len(relationships)
    counts["created"] += sum(
        1 for relationship in relationships if relationship.get("attachment_document_id")
    )


def run(
    *,
    root: Path,
    limit: int,
    dry_run: bool,
    intake_id: str | None = None,
) -> dict[str, object]:
    """Run the backfill, optionally targeting a single intake document.

    Returns a counts dict. Integer keys are always present. When ``intake_id``
    targets a document that is missing, unsupported, or has no attachments, the
    result additionally includes ``skip_reason`` (one of ``intake_not_found``,
    ``unsupported_document_type``, ``no_attachments``) and performs no writes.
    """

    counts: dict[str, int] = _empty_counts()
    if intake_id:
        document, reason = _select_targeted_document(intake_id, root=root)
        if document is None:
            result: dict[str, object] = dict(counts)
            result["skipped"] = 1
            result["skip_reason"] = reason
            return result
        _process_document(document, root=root, dry_run=dry_run, counts=counts)
        return dict(counts)
    candidates = [
        item
        for item in list_intake_documents(root=root)
        if item.get("document_type") in SUPPORTED_TARGET_TYPES
        and int((item.get("email_metadata") or {}).get("attachment_count") or 0) > 0
    ][:limit]
    for document in candidates:
        _process_document(document, root=root, dry_run=dry_run, counts=counts)
    return dict(counts)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--intake-id",
        default=None,
        help=(
            "Target exactly one existing intake document by intake_id. When "
            "supplied, --limit is ignored for candidate selection and no other "
            "intake is processed."
        ),
    )
    args = parser.parse_args()
    if not args.intake_id and args.limit <= 0:
        parser.error("--limit must be greater than zero")
    result = run(
        root=args.root,
        limit=args.limit,
        dry_run=args.dry_run,
        intake_id=args.intake_id,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
