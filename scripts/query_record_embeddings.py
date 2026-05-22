from __future__ import annotations

import argparse
import json
import os
import sqlite3
from pathlib import Path
from typing import Any

from api.semantic_search import hybrid_retrieve_records, semantic_retrieve_records
from scripts.backfill_record_embeddings import (
    DEFAULT_PROVIDER,
    EmbeddingProvider,
    build_embedding_provider,
    connect,
)


def query_record_embeddings(
    conn: sqlite3.Connection,
    query: str,
    *,
    provider: EmbeddingProvider,
    limit: int = 10,
    threshold: float = 0.0,
    hybrid: bool = False,
    semantic_weight: float = 0.65,
    keyword_weight: float = 0.35,
    trajectory: str | None = None,
    institution: str | None = None,
) -> dict[str, Any]:
    query_text = query.strip()
    if not query_text:
        return {
            "query": query,
            "mode": "empty",
            "embedding_model": provider.label,
            "threshold": threshold,
            "total": 0,
            "limit": limit,
            "records": [],
        }

    query_embedding = provider.embed(query_text)

    if hybrid:
        result = hybrid_retrieve_records(
            conn,
            query_text,
            query_embedding,
            embedding_model=provider.label,
            limit=limit,
            threshold=threshold,
            semantic_weight=semantic_weight,
            keyword_weight=keyword_weight,
            trajectory=trajectory,
            institution=institution,
        )
    else:
        result = semantic_retrieve_records(
            conn,
            query_embedding,
            embedding_model=provider.label,
            limit=limit,
            threshold=threshold,
            trajectory=trajectory,
            institution=institution,
        )

    result["query"] = query_text
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Query stored record_embeddings for local/admin semantic retrieval."
    )
    parser.add_argument(
        "--db-path",
        default=os.getenv("RECORDS_DB_PATH", "records.db"),
        help="Path to records SQLite database. Defaults to RECORDS_DB_PATH or records.db.",
    )
    parser.add_argument("--query", required=True, help="Query text to embed and compare.")
    parser.add_argument(
        "--provider",
        choices=("local", "remote"),
        default=os.getenv("EMBEDDING_PROVIDER", DEFAULT_PROVIDER),
        help="Embedding provider to use. Defaults to EMBEDDING_PROVIDER or local.",
    )
    parser.add_argument(
        "--model",
        default=os.getenv("EMBEDDING_MODEL"),
        help="Embedding model name. Defaults depend on the selected provider.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum ranked records to return.",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.0,
        help="Minimum cosine similarity for semantic candidates.",
    )
    parser.add_argument(
        "--hybrid",
        action="store_true",
        help="Blend semantic similarity with keyword fallback scores.",
    )
    parser.add_argument(
        "--semantic-weight",
        type=float,
        default=0.65,
        help="Hybrid semantic score weight.",
    )
    parser.add_argument(
        "--keyword-weight",
        type=float,
        default=0.35,
        help="Hybrid keyword score weight.",
    )
    parser.add_argument("--trajectory", default=None, help="Optional trajectory filter.")
    parser.add_argument(
        "--institution",
        default=None,
        help="Optional institution code filter such as LA, HS, or ED.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.limit < 1:
        raise SystemExit("--limit must be greater than zero")
    if args.semantic_weight < 0 or args.keyword_weight < 0:
        raise SystemExit("--semantic-weight and --keyword-weight must be non-negative")

    provider = build_embedding_provider(args.provider, args.model)
    conn = connect(Path(args.db_path))
    try:
        result = query_record_embeddings(
            conn,
            args.query,
            provider=provider,
            limit=args.limit,
            threshold=args.threshold,
            hybrid=args.hybrid,
            semantic_weight=args.semantic_weight,
            keyword_weight=args.keyword_weight,
            trajectory=args.trajectory,
            institution=args.institution,
        )
    finally:
        conn.close()

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
