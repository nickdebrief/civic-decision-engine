from __future__ import annotations

import json
import math
import os
import sqlite3
from collections.abc import Sequence
from typing import Any

from api.record_indexing import build_indexable_text, build_snippet


SEMANTIC_SEARCH_ENV = "SEMANTIC_SEARCH_ENABLED"
DEFAULT_SEARCH_LIMIT = 50
MAX_SEARCH_LIMIT = 200


def semantic_search_enabled() -> bool:
    value = os.getenv(SEMANTIC_SEARCH_ENV, "false")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def ensure_embedding_tables(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS record_embeddings (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            record_id           INTEGER NOT NULL,
            reference           TEXT NOT NULL,
            version             INTEGER NOT NULL,
            content_hash        TEXT NOT NULL,
            embedding_model     TEXT NOT NULL,
            embedding_json      TEXT NOT NULL,
            indexed_fields_json TEXT NOT NULL,
            created_at          TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY(record_id) REFERENCES records(id),
            UNIQUE(record_id, embedding_model, content_hash)
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_record_embeddings_ref_version
        ON record_embeddings(reference, version)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_record_embeddings_record_model
        ON record_embeddings(record_id, embedding_model)
    """)


def search_records(
    conn: sqlite3.Connection,
    query: str,
    *,
    trajectory: str | None = None,
    institution: str | None = None,
    limit: int = DEFAULT_SEARCH_LIMIT,
    offset: int = 0,
) -> dict[str, Any]:
    """Search latest public records.

    Semantic ranking remains behind SEMANTIC_SEARCH_ENABLED. Until embeddings are
    explicitly enabled and generated, this function returns keyword fallback
    results over canonical public record fields only.
    """
    normalized_query = query.strip()
    limit = min(max(1, limit), MAX_SEARCH_LIMIT)
    offset = max(0, offset)

    if not normalized_query:
        return {
            "query": query,
            "mode": "empty",
            "total": 0,
            "offset": offset,
            "limit": limit,
            "records": [],
        }

    if not semantic_search_enabled():
        return keyword_search_records(
            conn,
            normalized_query,
            trajectory=trajectory,
            institution=institution,
            limit=limit,
            offset=offset,
            mode="keyword_fallback",
        )

    semantic_results = semantic_search_records(
        conn,
        normalized_query,
        trajectory=trajectory,
        institution=institution,
        limit=limit,
        offset=offset,
    )
    if semantic_results["records"]:
        return semantic_results

    return keyword_search_records(
        conn,
        normalized_query,
        trajectory=trajectory,
        institution=institution,
        limit=limit,
        offset=offset,
        mode="keyword_fallback",
    )


def keyword_search_records(
    conn: sqlite3.Connection,
    query: str,
    *,
    trajectory: str | None = None,
    institution: str | None = None,
    limit: int = DEFAULT_SEARCH_LIMIT,
    offset: int = 0,
    mode: str = "keyword",
) -> dict[str, Any]:
    where_parts = ["is_latest = 1"]
    params: list[Any] = []

    if trajectory:
        where_parts.append("LOWER(trajectory) = LOWER(?)")
        params.append(trajectory)

    if institution:
        where_parts.append("reference LIKE ?")
        params.append(f"Strike-{institution.upper()}-%")

    like = f"%{query}%"
    where_parts.append(
        "("
        "LOWER(reference) LIKE LOWER(?) OR "
        "LOWER(generated_at) LIKE LOWER(?) OR "
        "LOWER(finding) LIKE LOWER(?) OR "
        "LOWER(trajectory) LIKE LOWER(?) OR "
        "LOWER(conditions_json) LIKE LOWER(?) OR "
        "LOWER(system_state) LIKE LOWER(?) OR "
        "LOWER(generated_by) LIKE LOWER(?)"
        ")"
    )
    params.extend([like] * 7)
    where = " AND ".join(where_parts)

    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) FROM records WHERE {where}", params)
    total = cur.fetchone()[0]

    cur.execute(
        f"SELECT * FROM records WHERE {where} "
        "ORDER BY exported_at DESC LIMIT ? OFFSET ?",
        params + [limit, offset],
    )
    rows = cur.fetchall()

    scored = [_keyword_result(row, query) for row in rows]
    scored.sort(key=lambda item: (item["score"], item["exported_at"]), reverse=True)

    return {
        "query": query,
        "mode": mode,
        "total": total,
        "offset": offset,
        "limit": limit,
        "records": scored,
    }


def semantic_search_records(
    conn: sqlite3.Connection,
    query: str,
    *,
    trajectory: str | None = None,
    institution: str | None = None,
    limit: int = DEFAULT_SEARCH_LIMIT,
    offset: int = 0,
) -> dict[str, Any]:
    # Stage 1 intentionally does not call an embedding provider. This reads the
    # table shape and falls back when no generated query embedding is available.
    ensure_embedding_tables(conn)
    return {
        "query": query,
        "mode": "semantic",
        "total": 0,
        "offset": offset,
        "limit": limit,
        "records": [],
        "filters": {
            "trajectory": trajectory,
            "institution": institution,
        },
    }


def semantic_retrieve_records(
    conn: sqlite3.Connection,
    query_embedding: Sequence[float],
    *,
    embedding_model: str,
    limit: int = 10,
    threshold: float = 0.0,
    trajectory: str | None = None,
    institution: str | None = None,
) -> dict[str, Any]:
    ensure_embedding_tables(conn)

    limit = min(max(1, limit), MAX_SEARCH_LIMIT)
    where_parts = ["r.is_latest = 1", "e.embedding_model = ?"]
    params: list[Any] = [embedding_model]

    if trajectory:
        where_parts.append("LOWER(r.trajectory) = LOWER(?)")
        params.append(trajectory)

    if institution:
        where_parts.append("r.reference LIKE ?")
        params.append(f"Strike-{institution.upper()}-%")

    where = " AND ".join(where_parts)
    rows = conn.execute(
        f"""
        SELECT
            r.reference,
            r.version,
            r.trajectory,
            r.conditions_json,
            r.system_state,
            r.exported_at,
            r.verification_hash,
            r.finding,
            r.generated_at,
            r.generated_by,
            e.embedding_json,
            e.embedding_model
        FROM record_embeddings e
        JOIN records r ON r.id = e.record_id
        WHERE {where}
        """,
        params,
    ).fetchall()

    results = []
    for row in rows:
        stored_embedding = parse_embedding(row["embedding_json"])
        score = cosine_similarity(query_embedding, stored_embedding)
        if score < threshold:
            continue

        results.append(
            {
                "reference": row["reference"],
                "version": row["version"],
                "trajectory": row["trajectory"] or "",
                "conditions": _load_conditions(row["conditions_json"]),
                "system_state": row["system_state"] or "",
                "exported_at": row["exported_at"] or "",
                "verification_hash": row["verification_hash"],
                "score": score,
                "semantic_score": score,
                "match_type": "semantic",
                "embedding_model": row["embedding_model"],
            }
        )

    results.sort(key=lambda item: (item["semantic_score"], item["exported_at"]), reverse=True)

    return {
        "mode": "semantic",
        "embedding_model": embedding_model,
        "threshold": threshold,
        "total": len(results),
        "limit": limit,
        "filters": {
            "trajectory": trajectory,
            "institution": institution,
        },
        "records": results[:limit],
    }


def hybrid_retrieve_records(
    conn: sqlite3.Connection,
    query: str,
    query_embedding: Sequence[float],
    *,
    embedding_model: str,
    limit: int = 10,
    threshold: float = 0.0,
    semantic_weight: float = 0.65,
    keyword_weight: float = 0.35,
    trajectory: str | None = None,
    institution: str | None = None,
) -> dict[str, Any]:
    semantic = semantic_retrieve_records(
        conn,
        query_embedding,
        embedding_model=embedding_model,
        limit=MAX_SEARCH_LIMIT,
        threshold=threshold,
        trajectory=trajectory,
        institution=institution,
    )
    keyword = keyword_search_records(
        conn,
        query,
        trajectory=trajectory,
        institution=institution,
        limit=MAX_SEARCH_LIMIT,
        offset=0,
        mode="keyword",
    )

    semantic_by_ref = {item["reference"]: item for item in semantic["records"]}
    keyword_by_ref = {item["reference"]: item for item in keyword["records"]}
    max_keyword_score = max(
        (item["score"] for item in keyword["records"]),
        default=0.0,
    )
    references = set(semantic_by_ref)

    results = []
    for reference in references:
        semantic_item = semantic_by_ref.get(reference)
        keyword_item = keyword_by_ref.get(reference)
        base = semantic_item or keyword_item
        semantic_score = (
            float(semantic_item["semantic_score"]) if semantic_item else 0.0
        )
        raw_keyword_score = float(keyword_item["score"]) if keyword_item else 0.0
        keyword_score = (
            raw_keyword_score / max_keyword_score if max_keyword_score > 0 else 0.0
        )
        combined = (semantic_weight * semantic_score) + (keyword_weight * keyword_score)

        result = {
            "reference": base["reference"],
            "version": base["version"],
            "trajectory": base["trajectory"],
            "conditions": base["conditions"],
            "system_state": base["system_state"],
            "exported_at": base["exported_at"],
            "verification_hash": base["verification_hash"],
            "score": combined,
            "semantic_score": semantic_score,
            "keyword_score": keyword_score,
            "match_type": "hybrid",
            "embedding_model": embedding_model,
        }
        if keyword_item and keyword_item.get("snippet"):
            result["snippet"] = keyword_item["snippet"]
        results.append(result)

    results.sort(key=lambda item: (item["score"], item["exported_at"]), reverse=True)

    return {
        "mode": "hybrid",
        "embedding_model": embedding_model,
        "threshold": threshold,
        "semantic_weight": semantic_weight,
        "keyword_weight": keyword_weight,
        "total": len(results),
        "limit": limit,
        "filters": {
            "trajectory": trajectory,
            "institution": institution,
        },
        "records": results[: min(max(1, limit), MAX_SEARCH_LIMIT)],
    }


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0

    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0

    return dot / (left_norm * right_norm)


def parse_embedding(raw: str) -> list[float]:
    try:
        parsed = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return []

    if not isinstance(parsed, list):
        return []

    values: list[float] = []
    for item in parsed:
        try:
            values.append(float(item))
        except (TypeError, ValueError):
            return []
    return values


def _keyword_result(record: sqlite3.Row, query: str) -> dict[str, Any]:
    text = build_indexable_text(record)
    normalized_query = query.lower()
    normalized_text = text.lower()
    exact_reference = normalized_query == str(record["reference"]).lower()
    phrase_count = normalized_text.count(normalized_query)

    score = float(phrase_count)
    if exact_reference:
        score += 100.0
    elif normalized_query in str(record["reference"]).lower():
        score += 25.0

    return {
        "reference": record["reference"],
        "version": record["version"],
        "trajectory": record["trajectory"] or "",
        "conditions": _load_conditions(record["conditions_json"]),
        "system_state": record["system_state"] or "",
        "exported_at": record["exported_at"] or "",
        "verification_hash": record["verification_hash"],
        "score": score,
        "match_type": "keyword",
        "snippet": build_snippet(record, query),
    }


def _load_conditions(raw: str | None) -> list[str]:
    try:
        parsed = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if item]
