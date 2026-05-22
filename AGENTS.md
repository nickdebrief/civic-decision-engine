# AGENTS.md

Guidance for Codex and other coding agents working on Civic Decision Engine.

## Project Rules

Canonical public records remain authoritative. Semantic embeddings, semantic
retrieval results, and experiment outputs are derived metadata only.

Do not change verification hash logic, record creation behavior, public routes,
or frontend behavior unless explicitly requested.

## Repository Layout

- `api/main.py` - FastAPI app entry point.
- `api/routes/` - API and HTML route modules.
- `api/routes/records.py` - public records, verification, archive, stats, graph, and condition views.
- `api/models.py` - request and response models.
- `api/record_indexing.py` - canonical public fields used for semantic indexing.
- `api/semantic_search.py` - internal semantic search/retrieval helpers.
- `scripts/` - local/admin tooling.
- `scripts/backfill_record_embeddings.py` - local/admin embedding backfill.
- `scripts/query_record_embeddings.py` - local/admin semantic retrieval.
- `scripts/run_semantic_experiments.py` - local/admin experiment runner.
- `tests/` - stdlib `unittest` tests.
- `docs/` - internal and public documentation.
- `schema/`, `examples/` - schemas and sample inputs.
- `outputs/` - generated outputs; do not commit generated experiment files unless requested.

## Local App

Run locally with:

```bash
python3 -m uvicorn api.main:app --reload
```

The records database defaults to `records.db`. Override with:

```bash
RECORDS_DB_PATH=/path/to/records.db python3 -m uvicorn api.main:app --reload
```

## Tests

Run all tests:

```bash
python3 -m unittest discover -s tests
```

Run semantic subsystem tests:

```bash
python3 -m unittest tests.test_record_indexing tests.test_semantic_search tests.test_backfill_record_embeddings tests.test_semantic_retrieval tests.test_query_record_embeddings tests.test_run_semantic_experiments
```

Use stdlib `unittest`, in-memory SQLite, and fake providers in tests. Do not
call external embedding providers in tests.

## Commit And Check Workflow

Preferred workflow:

1. Plan first.
2. Implement narrowly.
3. Run focused tests.
4. Run full tests.
5. Summarize changes and risks.
6. Check `git status --short`.
7. Commit only when explicitly requested.

Useful checks:

```bash
git status --short
git diff --stat
python3 -m unittest discover -s tests
```

## Public Route Restrictions

Do not add public semantic routes unless explicitly requested.

Do not:

- wire semantic tooling into `/records`
- add `/api/records/search`
- change `/api/records` behavior
- add frontend semantic search UI

## Verification Hash Protections

Do not modify verification hash logic unless explicitly requested.

Semantic metadata must never be included in verification hashes. Embeddings and
retrieval outputs must not alter canonical records, published record versions,
or version history.

## Semantic Subsystem Rules

Semantic output is derived metadata only.

Rules:

- keep `SEMANTIC_SEARCH_ENABLED=false` by default
- keep `local:local-test-embedding-v0` as the default provider/model
- preserve provider-neutral labels such as `local:*` and `remote:*`
- keep remote provider support explicit, optional, and lazy-loaded
- do not require API keys for tests
- do not introduce vendor-specific provider labels

## Canonical Indexed Fields

Semantic indexing may use only:

- `reference`
- `generated_at`
- `finding`
- `trajectory`
- `conditions`
- `system_state`
- `generated_by`

Current semantic index policy:

```text
canonical-public-v1
```

## Privacy And Excluded Fields

Never include these in semantic indexing, embeddings, retrieval outputs,
experiment outputs, or provider calls:

- `source_narrative`
- `report_json`
- raw input
- raw submitted case text

Tests should prove excluded-field changes do not change semantic content hashes.

## Generated Output Handling

Semantic experiment outputs belong under:

```text
outputs/semantic_experiments/
```

Do not commit generated files there unless explicitly requested.

Experiment JSON must include:

- `derived_metadata_only: true`
- a non-authoritative notice

Experiment JSON must not include excluded fields.

## Dependency Guidance

Prefer local/offline-compatible approaches. Avoid new dependencies unless
needed. Keep remote semantic provider integrations lazy and optional. Do not add
commercial provider SDKs to production dependencies without explicit request.

## Documentation Expectations

When semantic tooling changes, update internal docs such as:

- `docs/semantic_retrieval.md`

Do not present experimental semantic tooling as a public product feature.

## Agent Behavior Notes

Agents should:

- inspect repo state before editing
- keep changes scoped
- preserve user changes
- avoid destructive git commands
- use `rg` for search
- run relevant tests before summarizing
- report test failures or inability to run tests honestly
- never commit unless explicitly requested
