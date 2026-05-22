from __future__ import annotations

import argparse
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from api.semantic_search import INDEX_POLICY_VERSION
from scripts.backfill_record_embeddings import (
    DEFAULT_PROVIDER,
    EmbeddingProvider,
    backfill_record_embeddings,
    build_embedding_provider,
    connect,
)
from scripts.query_record_embeddings import query_record_embeddings


DEFAULT_OUTPUT_DIR = Path("outputs/semantic_experiments")
NON_AUTHORITATIVE_NOTICE = (
    "Semantic results are derived metadata only. They do not alter canonical "
    "records, verification hashes, or public archive behavior."
)
EXPERIMENTS = (
    "condition-proximity",
    "institutional-recurrence",
    "trajectory-similarity",
    "multilingual-alignment",
)


DEFAULT_QUERY_SETS: dict[str, list[dict[str, Any]]] = {
    "condition-proximity": [
        {
            "id": "institutional_delay",
            "query": "institutional delay without substantive response",
        },
        {
            "id": "transfer_of_burden",
            "query": "transfer of burden repeated contact without resolution",
        },
        {
            "id": "escalation_without_response",
            "query": "escalation without response",
        },
    ],
    "institutional-recurrence": [
        {
            "id": "local_authority_delay",
            "query": "delay escalation transfer of burden",
            "institution": "LA",
        },
        {
            "id": "health_service_deflection",
            "query": "procedural deflection repeated contact",
            "institution": "HS",
        },
        {
            "id": "education_delay",
            "query": "institutional delay no substantive progress",
            "institution": "ED",
        },
    ],
    "trajectory-similarity": [
        {
            "id": "deteriorating_escalation",
            "query": "transition to escalation deteriorating",
            "trajectory": "Deteriorating",
        },
        {
            "id": "stable_containment",
            "query": "stable trajectory procedural containment",
            "trajectory": "Stable",
        },
    ],
    "multilingual-alignment": [
        {
            "id": "delay_alignment",
            "queries": {
                "en": "institutional delay without response",
                "ga": "moill institiuideach gan freagra",
                "fr": "retard institutionnel sans reponse substantielle",
                "de": "institutionelle verzoegerung ohne substanzielle antwort",
            },
        }
    ],
}


def selected_experiments(values: list[str] | None) -> list[str]:
    if not values or "all" in values:
        return list(EXPERIMENTS)
    return values


def load_query_sets(path: str | None) -> dict[str, list[dict[str, Any]]]:
    if not path:
        return DEFAULT_QUERY_SETS
    with open(path, "r", encoding="utf-8") as handle:
        loaded = json.load(handle)
    return loaded


def run_semantic_experiments(
    conn: sqlite3.Connection,
    *,
    provider: EmbeddingProvider,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    run_id: str | None = None,
    experiments: list[str] | None = None,
    query_sets: dict[str, list[dict[str, Any]]] | None = None,
    threshold: float = 0.0,
    limit: int = 10,
    hybrid: bool = False,
    semantic_weight: float = 0.65,
    keyword_weight: float = 0.35,
    overwrite: bool = False,
) -> dict[str, Any]:
    run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    query_sets = query_sets or DEFAULT_QUERY_SETS
    experiments_to_run = selected_experiments(experiments)
    generated_at = datetime.now(timezone.utc).isoformat()

    written_files: list[str] = []
    experiment_summaries: list[dict[str, Any]] = []

    for experiment in experiments_to_run:
        if experiment not in EXPERIMENTS:
            raise ValueError(f"Unsupported experiment: {experiment}")
        payload = build_experiment_output(
            conn,
            provider=provider,
            experiment=experiment,
            queries=query_sets.get(experiment, []),
            run_id=run_id,
            generated_at=generated_at,
            threshold=threshold,
            limit=limit,
            hybrid=hybrid,
            semantic_weight=semantic_weight,
            keyword_weight=keyword_weight,
        )
        ensure_no_excluded_fields(payload)
        destination = output_path / f"{run_id}_{experiment.replace('-', '_')}.json"
        write_json(destination, payload, overwrite=overwrite)
        written_files.append(str(destination))
        experiment_summaries.append(
            {
                "experiment": experiment,
                "query_count": len(payload["queries"]),
                "file": str(destination),
            }
        )

    summary = {
        "run_id": run_id,
        "generated_at": generated_at,
        "derived_metadata_only": True,
        "non_authoritative_notice": NON_AUTHORITATIVE_NOTICE,
        "embedding_model": provider.label,
        "index_policy_version": INDEX_POLICY_VERSION,
        "output_dir": str(output_path),
        "experiments": experiment_summaries,
        "files": written_files,
    }
    ensure_no_excluded_fields(summary)
    summary_path = output_path / f"{run_id}_summary.json"
    write_json(summary_path, summary, overwrite=overwrite)
    summary["files"].append(str(summary_path))
    return summary


def build_experiment_output(
    conn: sqlite3.Connection,
    *,
    provider: EmbeddingProvider,
    experiment: str,
    queries: list[dict[str, Any]],
    run_id: str,
    generated_at: str,
    threshold: float,
    limit: int,
    hybrid: bool,
    semantic_weight: float,
    keyword_weight: float,
) -> dict[str, Any]:
    results = []
    if experiment == "multilingual-alignment":
        for item in queries:
            language_results = {}
            for language, query in item.get("queries", {}).items():
                language_results[language] = query_record_embeddings(
                    conn,
                    query,
                    provider=provider,
                    limit=limit,
                    threshold=threshold,
                    hybrid=hybrid,
                    semantic_weight=semantic_weight,
                    keyword_weight=keyword_weight,
                )
            results.append(
                {
                    "id": item.get("id", ""),
                    "languages": language_results,
                    "overlap": multilingual_overlap(language_results),
                    "caution": (
                        "Alignment quality depends on the selected embedding model. "
                        "The local deterministic provider is for repeatable plumbing "
                        "tests, not multilingual semantic quality."
                    ),
                }
            )
    else:
        for item in queries:
            result = query_record_embeddings(
                conn,
                item.get("query", ""),
                provider=provider,
                limit=limit,
                threshold=threshold,
                hybrid=hybrid,
                semantic_weight=semantic_weight,
                keyword_weight=keyword_weight,
                trajectory=item.get("trajectory"),
                institution=item.get("institution"),
            )
            results.append(
                {
                    "id": item.get("id", ""),
                    "query": item.get("query", ""),
                    "institution": item.get("institution"),
                    "trajectory": item.get("trajectory"),
                    "result": result,
                    "observations": summarize_result(result),
                }
            )

    return {
        "run_id": run_id,
        "generated_at": generated_at,
        "derived_metadata_only": True,
        "non_authoritative_notice": NON_AUTHORITATIVE_NOTICE,
        "experiment": experiment,
        "embedding_model": provider.label,
        "index_policy_version": INDEX_POLICY_VERSION,
        "parameters": {
            "limit": limit,
            "threshold": threshold,
            "hybrid": hybrid,
            "semantic_weight": semantic_weight,
            "keyword_weight": keyword_weight,
        },
        "queries": results,
    }


def summarize_result(result: dict[str, Any]) -> dict[str, Any]:
    records = result.get("records", [])
    condition_counts: dict[str, int] = {}
    trajectory_counts: dict[str, int] = {}
    for record in records:
        trajectory = record.get("trajectory") or ""
        if trajectory:
            trajectory_counts[trajectory] = trajectory_counts.get(trajectory, 0) + 1
        for condition in record.get("conditions", []):
            condition_counts[condition] = condition_counts.get(condition, 0) + 1
    return {
        "result_count": len(records),
        "condition_counts": condition_counts,
        "trajectory_counts": trajectory_counts,
    }


def multilingual_overlap(language_results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    references_by_language = {
        language: [
            record["reference"] for record in result.get("records", [])
        ]
        for language, result in language_results.items()
    }
    sets = {
        language: set(references)
        for language, references in references_by_language.items()
    }
    all_refs = set().union(*sets.values()) if sets else set()
    shared_refs = set.intersection(*sets.values()) if sets else set()
    return {
        "references_by_language": references_by_language,
        "shared_references": sorted(shared_refs),
        "shared_count": len(shared_refs),
        "union_count": len(all_refs),
        "jaccard": (len(shared_refs) / len(all_refs)) if all_refs else 0.0,
    }


def ensure_no_excluded_fields(payload: Any) -> None:
    serialized = json.dumps(payload, sort_keys=True)
    excluded = (
        "source_narrative",
        "report_json",
        "raw_input",
        "raw submitted",
        "private narrative",
        "raw input",
    )
    found = [term for term in excluded if term in serialized]
    if found:
        raise ValueError(f"Experiment output contains excluded field content: {found}")


def write_json(path: Path, payload: dict[str, Any], *, overwrite: bool = False) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(f"Refusing to overwrite existing output: {path}")
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run local/admin-only semantic retrieval experiments."
    )
    parser.add_argument(
        "--db-path",
        default=os.getenv("RECORDS_DB_PATH", "records.db"),
        help="Path to records SQLite database. Defaults to RECORDS_DB_PATH or records.db.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Directory for JSON experiment outputs.",
    )
    parser.add_argument("--run-id", default=None, help="Stable run identifier.")
    parser.add_argument(
        "--experiment",
        action="append",
        choices=(*EXPERIMENTS, "all"),
        default=None,
        help="Experiment to run. Repeat for multiple experiments. Defaults to all.",
    )
    parser.add_argument(
        "--queries-file",
        default=None,
        help="Optional JSON query set file.",
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
        help="Embedding model name. Defaults depend on selected provider.",
    )
    parser.add_argument("--threshold", type=float, default=0.0)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--hybrid", action="store_true")
    parser.add_argument("--semantic-weight", type=float, default=0.65)
    parser.add_argument("--keyword-weight", type=float, default=0.35)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--backfill",
        action="store_true",
        help="Backfill embeddings before running experiments.",
    )
    parser.add_argument(
        "--backfill-limit",
        type=int,
        default=None,
        help="Maximum latest records to backfill when --backfill is set.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.limit < 1:
        raise SystemExit("--limit must be greater than zero")
    if args.semantic_weight < 0 or args.keyword_weight < 0:
        raise SystemExit("--semantic-weight and --keyword-weight must be non-negative")
    if args.backfill_limit is not None and args.backfill_limit < 1:
        raise SystemExit("--backfill-limit must be greater than zero")

    provider = build_embedding_provider(args.provider, args.model)
    conn = connect(Path(args.db_path))
    try:
        backfill_summary = None
        if args.backfill:
            backfill_summary = backfill_record_embeddings(
                conn, limit=args.backfill_limit, provider=provider
            )
        summary = run_semantic_experiments(
            conn,
            provider=provider,
            output_dir=args.output_dir,
            run_id=args.run_id,
            experiments=args.experiment,
            query_sets=load_query_sets(args.queries_file),
            threshold=args.threshold,
            limit=args.limit,
            hybrid=args.hybrid,
            semantic_weight=args.semantic_weight,
            keyword_weight=args.keyword_weight,
            overwrite=args.overwrite,
        )
        if backfill_summary is not None:
            summary["backfill"] = backfill_summary
    finally:
        conn.close()

    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
