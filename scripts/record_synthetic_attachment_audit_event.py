from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from api.attachments import record_attachment_audit_event, sanitize_audit_metadata


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def parse_metadata_json(raw_value: str | None) -> dict[str, Any] | None:
    if raw_value is None:
        return None
    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError as exc:
        raise ValueError("metadata-json must be valid JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError("metadata-json must decode to a JSON object")
    return parsed


def build_event_preview(args: argparse.Namespace) -> dict[str, Any]:
    metadata = parse_metadata_json(args.metadata_json)
    return {
        "event_type": args.event_type,
        "reference": args.reference,
        "record_version": args.record_version,
        "attachment_id": args.attachment_id,
        "actor": args.actor,
        "request_id": args.request_id,
        "metadata": sanitize_audit_metadata(metadata),
        "dry_run": bool(args.dry_run),
    }


def record_synthetic_event(args: argparse.Namespace) -> dict[str, Any]:
    event = build_event_preview(args)
    if args.dry_run:
        return {
            "ok": True,
            "inserted": False,
            "event_id": None,
            "event": event,
        }

    conn = connect(Path(args.db_path))
    try:
        event_id = record_attachment_audit_event(
            conn,
            event_type=args.event_type,
            reference=args.reference,
            actor=args.actor,
            attachment_id=args.attachment_id,
            record_version=args.record_version,
            metadata=event["metadata"],
            request_id=args.request_id,
        )
        conn.commit()
    finally:
        conn.close()

    return {
        "ok": True,
        "inserted": True,
        "event_id": event_id,
        "event": event,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Record a synthetic CDE attachment audit event locally."
    )
    parser.add_argument("--db-path", required=True)
    parser.add_argument("--reference", required=True)
    parser.add_argument("--record-version", required=True, type=int)
    parser.add_argument("--event-type", required=True)
    parser.add_argument("--attachment-id", type=int)
    parser.add_argument("--actor", default="admin")
    parser.add_argument("--request-id")
    parser.add_argument("--metadata-json")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        payload = record_synthetic_event(args)
    except ValueError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2

    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
