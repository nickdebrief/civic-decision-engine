# CDE Platform Stage 39B — Archive Preservation & Extraction Jobs

## Purpose

CDE Platform Stage 39B extends the PST/OST intake boundary introduced in CDE Platform Stage 39A with a durable archive preservation and inspection job framework.

The archive remains the authoritative record. Job processing verifies preservation and parser readiness, but it does not publish mailbox contents, extract messages, create Canonical Records, or turn derived inspection metadata into evidence objects.

## Architecture

Outlook archive jobs are stored as local JSON sidecars under the protected Document Intake storage root:

`<document-intake-root>/.outlook_archive_jobs/`

The sidecar model avoids a database migration and keeps job state restart-survivable. Each job is linked to the existing governed document intake record by intake identifier and document identifier.

## Job Lifecycle

The Stage 39B job model supports:

- Uploaded
- Queued
- Hashing
- Preparing
- Waiting for Parser
- Inspecting
- Completed
- Failed
- Cancelled

The states are operational processing metadata. They do not replace or modify the governed document lifecycle:

Pending Intake → Under Review → Approved → Published

Administrative inspection requests create a durable queued job and start a bounded in-process worker. The worker entrypoint can also be invoked directly for recovery or maintenance after restart because the job state is persisted before processing begins.

## Preservation Behaviour

Stage 39B records:

- storage path
- preservation timestamp
- preservation completion
- archive size
- SHA-256 verification status
- SHA-512 verification status
- latest archive job identifier

Hashes are recalculated from the preserved original file in fixed 1 MiB chunks. The original archive bytes are never rewritten, repaired, normalised, decompressed, or replaced.

## Parser Boundary

Stage 39B reuses the `OutlookArchiveParser` contract:

- `supports(file_path)`
- `inspect(file_path)`

A parser may be configured with:

- `CDE_OUTLOOK_ARCHIVE_PARSER_MODULE`
- `CDE_OUTLOOK_ARCHIVE_PARSER_CLASS`
- `CDE_OUTLOOK_ARCHIVE_PARSER_VERSION`

Validation environments may set `CDE_OUTLOOK_ARCHIVE_JOB_RUN_MODE=inline` to execute the bounded worker synchronously for deterministic tests.

No parser dependency is introduced by this stage. If no parser is configured, the job completes safely and records:

`Parser not configured.`

If a parser is configured, Stage 39B permits lightweight archive inspection only:

- archive validity
- mailbox count
- top-level folder count
- archive health
- parser version
- bounded parser warnings

Mailbox contents, folder trees, messages, contacts, calendar entries, attachment bytes, and Canonical Records are not extracted or exposed.

## Administrative UI

The Document Intake administration page now includes an Archive Jobs section showing:

- job identifier
- source document
- archive filename
- status
- phase
- progress
- parser status
- created timestamp
- completed timestamp
- warnings

PST/OST review pages include a metadata-only archive inspection action. Job detail pages expose structured operational logs without raw mailbox contents.

## APIs

Stage 39B adds protected administrative job endpoints:

- `POST /api/admin/session/archive/{document_id}/inspect`
- `GET /api/admin/session/archive/jobs`
- `GET /api/admin/session/archive/jobs/{job_id}`
- `GET /api/admin/session/archive/jobs/{job_id}/status`
- `GET /api/admin/session/archive/jobs/{job_id}/logs`
- `POST /api/admin/session/archive/jobs/{job_id}/retry`
- `POST /api/admin/session/archive/jobs/{job_id}/cancel`

Published archive metadata endpoints continue to expose archive-level status only:

- `GET /archive/{id}`
- `GET /archive/{id}/status`

Public responses include preservation and inspection completion flags, hash verification status, parser status, and parser version. They do not include mailbox contents or folder/message projections.

## Provenance

Public document provenance for PST/OST documents now includes:

- archive type
- parser status
- parser version
- preservation completion
- hash verification status
- inspection completion
- inspection timestamp
- archive job identifier
- SHA-256
- SHA-512

Verification continues to refer to the original uploaded archive only.

## Error Handling

Jobs fail closed for:

- hash mismatch
- unsupported configured parser
- parser initialisation failure
- unexpected parser exceptions
- missing or non-Outlook source documents

Failures do not remove or compromise the preserved archive. Error messages are bounded and do not expose filesystem internals, raw mailbox contents, or parser tracebacks.

## Security

Stage 39B preserves the Stage 39A governance boundary:

- no mailbox data is published
- no folder tree is exposed
- no messages are extracted
- no attachments are extracted
- no Canonical Records are generated
- no parser dependency is required
- no database migration is introduced

Job logs are administrative operational metadata only.

## Tests

Focused tests cover:

- preservation metadata on intake
- durable archive job creation
- queued state
- parser-unavailable completion
- configured-parser lightweight inspection
- progress and status payloads
- retry and cancellation
- structured logs
- admin job dashboard and detail pages
- protected API responses
- public metadata boundary
- hash mismatch failure
- deterministic job listing

Existing email, MBOX, public-document, and full regression tests remain required.

## Intentional Exclusions

CDE Platform Stage 39B does not implement:

- mailbox discovery publication
- folder tree extraction
- message extraction
- attachment extraction
- Canonical Record generation
- public mailbox contents
- PST/OST relationship graph expansion
- background distributed queues
- new database schema
- new parser dependency
