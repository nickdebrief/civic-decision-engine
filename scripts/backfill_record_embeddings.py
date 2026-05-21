from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
from pathlib import Path
from typing import Any

from api.record_indexing import (
    build_indexable_text,
    indexed_fields_hash,
    indexed_fields_json,
)
from api.semantic_search import ensure_embedding_tables


LOCAL_TEST_EMBEDDING_MODEL = "local-test-embedding-v0"
DEFAULT_DIMENSIONS = 16


def deterministic_local_embedding(text: str, dimensions: int = DEFAULT_DIMENSIONS) -> list[float]:
    """Return a stable local-only embedding for test/admin backfill workflows."""
    values: list[float] = []
    seed = text.encode("utf-8")

    for index in range(dimensions):
        digest = hashlib.sha256(seed + index.to_bytes(2, "big")).digest()
        integer = int.from_bytes(digest[:8], "big")
        normalized = (integer / ((1 << 64) - 1)) * 2.0 - 1.0
        values.append(round(normalized, 8))

    return values


def connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def fetch_latest_records(conn: sqlite3.Connection, limit: int | None = None) -> list[sqlite3.Row]:
    sql = "SELECT * FROM records WHERE is_latest = 1 ORDER BY exported_at ASC, id ASC"
    params: list[Any] = []
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    return conn.execute(sql, params).fetchall()


def backfill_record_embeddings(
    conn: sqlite3.Connection,
    *,
    dry_run: bool = False,
    limit: int | None = None,
    model: str = LOCAL_TEST_EMBEDDING_MODEL,
) -> dict[str, Any]:
    ensure_embedding_tables(conn)

    records = fetch_latest_records(conn, limit=limit)
    inserted = 0
    skipped = 0
    planned = 0

    for record in records:
        text = build_indexable_text(record)
        content_hash = indexed_fields_hash(record)
        fields_json = indexed_fields_json(record)
        embedding_json = json.dumps(
            deterministic_local_embedding(text), separators=(",", ":")
        )

        existing = conn.execute(
            """
            SELECT 1 FROM record_embeddings
            WHERE record_id = ? AND embedding_model = ? AND content_hash = ?
            LIMIT 1
            """,
            (record["id"], model, content_hash),
        ).fetchone()

        if existing:
            skipped += 1
            continue

        planned += 1
        if dry_run:
            continue

        cur = conn.execute(
            """
            INSERT OR IGNORE INTO record_embeddings (
                record_id, reference, version, content_hash,
                embedding_model, embedding_json, indexed_fields_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["id"],
                record["reference"],
                record["version"],
                content_hash,
                model,
                embedding_json,
                fields_json,
            ),
        )
        if cur.rowcount:
            inserted += 1
        else:
            skipped += 1

    if not dry_run:
        conn.commit()

    return {
        "model": model,
        "dry_run": dry_run,
        "selected": len(records),
        "planned": planned,
        "inserted": inserted,
        "skipped": skipped,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Populate record_embeddings for latest public records using "
            "deterministic local test embeddings."
        )
    )
    parser.add_argument(
        "--db-path",
        default=os.getenv("RECORDS_DB_PATH", "records.db"),
        help="Path to records SQLite database. Defaults to RECORDS_DB_PATH or records.db.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report planned inserts without writing embeddings.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum latest records to process.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.limit is not None and args.limit < 1:
        raise SystemExit("--limit must be greater than zero")

    conn = connect(args.db_path)
    try:
        result = backfill_record_embeddings(
            conn,
            dry_run=args.dry_run,
            limit=args.limit,
            model=LOCAL_TEST_EMBEDDING_MODEL,
        )
    finally:
        conn.close()

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
