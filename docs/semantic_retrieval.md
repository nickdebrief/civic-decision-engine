# Internal Semantic Retrieval

This document describes the internal semantic retrieval subsystem for the Civic
Decision Engine public record archive.

Semantic retrieval is not public-facing. It is local/admin-only tooling for
testing derived search metadata against verified public records.

## Authority Boundary

Canonical public records remain authoritative.

The semantic layer does not create, alter, verify, supersede, or interpret
canonical records. Semantic embeddings and semantic retrieval results are
derived metadata only. They may help explore structural similarity, but they do
not form part of the record itself.

Verification hashes are unchanged. The canonical verification hash is still
computed from the canonical record fields used by the public verification
system. Semantic metadata is never included in the verification hash.

## Indexed Fields

Semantic indexing uses canonical public fields only:

- `reference`
- `generated_at`
- `finding`
- `trajectory`
- `conditions`
- `system_state`
- `generated_by`

The index policy version is currently:

```text
canonical-public-v1
```

The semantic content hash is derived from these indexed fields only.

## Excluded Fields

The following fields must not be embedded, queried over, stored in
`indexed_fields_json`, or sent to any embedding provider:

- `source_narrative`
- `report_json`
- raw input or raw submitted case text

Tests assert that changes to excluded fields do not change the semantic content
hash.

## Providers

The default provider is local and deterministic:

```text
local:local-test-embedding-v0
```

This provider is intended for tests, local development, and offline-compatible
workflows. It does not call external services.

Remote provider support is optional and vendor-neutral. Remote use must be
enabled explicitly with provider flags and environment variables. Remote
provider labels use the neutral form:

```text
remote:<model-name>
```

Remote configuration uses:

```text
REMOTE_EMBEDDING_API_KEY
REMOTE_EMBEDDING_CLIENT
```

`REMOTE_EMBEDDING_CLIENT` uses the form:

```text
module:factory
```

No remote provider is required for tests.

## Backfill

Use the backfill script to populate `record_embeddings` from latest public
records:

```bash
python3 scripts/backfill_record_embeddings.py
```

Dry run:

```bash
python3 scripts/backfill_record_embeddings.py --dry-run
```

Limit records processed:

```bash
python3 scripts/backfill_record_embeddings.py --limit 10
```

Use a specific database:

```bash
python3 scripts/backfill_record_embeddings.py --db-path records.db
```

Use the default local provider explicitly:

```bash
python3 scripts/backfill_record_embeddings.py \
  --provider local \
  --model local-test-embedding-v0
```

Optional remote provider usage:

```bash
REMOTE_EMBEDDING_API_KEY=... \
REMOTE_EMBEDDING_CLIENT=package.module:create_client \
python3 scripts/backfill_record_embeddings.py \
  --provider remote \
  --model remote-model-name
```

Backfill selects only latest records:

```sql
records.is_latest = 1
```

Backfill is idempotent for a given record, provider/model label, and semantic
content hash.

## Querying

Use the query script for local/admin-only semantic retrieval against stored
embeddings:

```bash
python3 scripts/query_record_embeddings.py \
  --query "institutional delay without substantive response"
```

Limit and threshold:

```bash
python3 scripts/query_record_embeddings.py \
  --query "transfer of burden escalation" \
  --limit 5 \
  --threshold 0.25
```

Hybrid semantic/keyword experiment:

```bash
python3 scripts/query_record_embeddings.py \
  --query "procedural delay" \
  --hybrid \
  --semantic-weight 0.65 \
  --keyword-weight 0.35
```

Specific local model:

```bash
python3 scripts/query_record_embeddings.py \
  --db-path records.db \
  --provider local \
  --model local-test-embedding-v0 \
  --query "housing escalation pattern"
```

The query script returns JSON only.

Retrieval joins `record_embeddings` to `records` and requires:

```sql
records.is_latest = 1
record_embeddings.embedding_model = <selected provider/model label>
```

Hybrid retrieval is opt-in and re-ranks only records that already have matching
stored embeddings.

## Tests

Run the semantic retrieval test suite with:

```bash
python3 -m unittest discover -s tests
```

Core tests cover:

- canonical indexed-field construction
- excluded-field omission
- semantic content hash determinism
- excluded-field changes not changing semantic content hash
- embedding table creation and metadata columns
- local deterministic backfill
- remote provider credential safety
- latest-record-only retrieval
- selected model-label matching
- semantic and hybrid internal retrieval

## Current Non-Goals

The semantic subsystem currently does not provide:

- a public route
- `/records` wiring
- `/api/records/search`
- frontend or UI controls
- public semantic retrieval
- canonical record mutation
- verification hash changes

Semantic retrieval remains internal until a separate public-exposure review is
completed.
