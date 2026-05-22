from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Protocol

from api.record_indexing import (
    build_indexable_text,
    indexed_fields_hash,
    indexed_fields_json,
)
from api.semantic_search import ensure_embedding_tables


LOCAL_TEST_EMBEDDING_MODEL = "local-test-embedding-v0"
DEFAULT_DIMENSIONS = 16
DEFAULT_PROVIDER = "local"
REMOTE_DEFAULT_MODEL = "remote-embedding-model"


class EmbeddingProvider(Protocol):
    label: str

    def embed(self, text: str) -> list[float]:
        ...


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


class LocalTestEmbeddingProvider:
    def __init__(
        self,
        model: str = LOCAL_TEST_EMBEDDING_MODEL,
        dimensions: int = DEFAULT_DIMENSIONS,
    ):
        self.model = model
        self.dimensions = dimensions
        self.label = f"local:{model}"

    def embed(self, text: str) -> list[float]:
        return deterministic_local_embedding(text, dimensions=self.dimensions)


class RemoteAPIEmbeddingProvider:
    def __init__(
        self,
        model: str = REMOTE_DEFAULT_MODEL,
        api_key: str | None = None,
        client_spec: str | None = None,
    ):
        api_key = api_key or os.getenv("REMOTE_EMBEDDING_API_KEY")
        if not api_key:
            raise RuntimeError(
                "REMOTE_EMBEDDING_API_KEY is required when using --provider remote."
            )

        client_spec = client_spec or os.getenv("REMOTE_EMBEDDING_CLIENT")
        if not client_spec:
            raise RuntimeError(
                "REMOTE_EMBEDDING_CLIENT is required when using --provider remote. "
                "Use the form 'module:factory'."
            )

        module_name, separator, factory_name = client_spec.partition(":")
        if not module_name or not separator or not factory_name:
            raise RuntimeError("REMOTE_EMBEDDING_CLIENT must use the form 'module:factory'.")

        module = importlib.import_module(module_name)
        factory = getattr(module, factory_name)

        self.model = model
        self.label = f"remote:{model}"
        self.client = factory(api_key=api_key)

    def embed(self, text: str) -> list[float]:
        response = self.client.embeddings.create(model=self.model, input=text)
        return [float(value) for value in response.data[0].embedding]


class DryRunEmbeddingProvider:
    def __init__(self, label: str):
        self.label = label

    def embed(self, text: str) -> list[float]:
        raise RuntimeError("Dry-run mode must not generate embeddings.")


def provider_label(provider_name: str, model: str | None = None) -> str:
    normalized = provider_name.strip().lower()
    if normalized == "local":
        return f"local:{model or LOCAL_TEST_EMBEDDING_MODEL}"
    if normalized == "remote":
        return f"remote:{model or REMOTE_DEFAULT_MODEL}"
    raise ValueError(f"Unsupported embedding provider: {provider_name}")


def build_embedding_provider(
    provider_name: str = DEFAULT_PROVIDER,
    model: str | None = None,
    *,
    dry_run: bool = False,
) -> EmbeddingProvider | None:
    normalized = provider_name.strip().lower()
    if dry_run:
        return DryRunEmbeddingProvider(provider_label(normalized, model))

    if normalized == "local":
        return LocalTestEmbeddingProvider(model=model or LOCAL_TEST_EMBEDDING_MODEL)

    if normalized == "remote":
        return RemoteAPIEmbeddingProvider(model=model or REMOTE_DEFAULT_MODEL)

    raise ValueError(f"Unsupported embedding provider: {provider_name}")


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
    provider: EmbeddingProvider | None = None,
) -> dict[str, Any]:
    ensure_embedding_tables(conn)
    provider = provider or LocalTestEmbeddingProvider()

    records = fetch_latest_records(conn, limit=limit)
    inserted = 0
    skipped = 0
    planned = 0

    for record in records:
        text = build_indexable_text(record)
        content_hash = indexed_fields_hash(record)
        fields_json = indexed_fields_json(record)

        existing = conn.execute(
            """
            SELECT 1 FROM record_embeddings
            WHERE record_id = ? AND embedding_model = ? AND content_hash = ?
            LIMIT 1
            """,
            (record["id"], provider.label, content_hash),
        ).fetchone()

        if existing:
            skipped += 1
            continue

        planned += 1
        if dry_run:
            continue

        embedding_json = json.dumps(provider.embed(text), separators=(",", ":"))
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
                provider.label,
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
        "model": provider.label,
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
    parser.add_argument(
        "--provider",
        choices=("local", "remote"),
        default=os.getenv("EMBEDDING_PROVIDER", DEFAULT_PROVIDER),
        help="Embedding provider to use. Defaults to EMBEDDING_PROVIDER or local.",
    )
    parser.add_argument(
        "--model",
        default=os.getenv("EMBEDDING_MODEL"),
        help=(
            "Embedding model name. Defaults to local-test-embedding-v0 for local "
            "or remote-embedding-model for remote."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.limit is not None and args.limit < 1:
        raise SystemExit("--limit must be greater than zero")

    conn = connect(args.db_path)
    try:
        provider = build_embedding_provider(
            args.provider,
            args.model,
            dry_run=args.dry_run,
        )
        result = backfill_record_embeddings(
            conn,
            dry_run=args.dry_run,
            limit=args.limit,
            provider=provider,
        )
    finally:
        conn.close()

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
