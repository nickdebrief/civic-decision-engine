# CDE Platform Stage 62 — Governed Pattern Observation

Implemented · merged · deployed

Merged through [PR #343](https://github.com/nickdebrief/civic-decision-engine/pull/343)
at `2026-08-15T12:07:05Z` as canonical main commit
`cc69ecd19d651f899dff3e7cb26d995fa9f70319`. Railway deployment `5920254970`
completed successfully at `2026-08-15T12:07:48Z`.

## Purpose

Stage 62 makes deterministic recurrence in already governed Record–Document
Associations inspectable without converting repetition into an allegation,
finding, motive, intent, legal conclusion, risk score, or behavioural profile.

**Repetition may reveal pattern. Pattern does not automatically prove intent.**

## Narrow rule

The initial rule is `stage62.repeated_relationship_type.v1`: two or more
preserved association rows with the same exact `record_reference` and exact
`relationship_type` produce one candidate observation. The rule uses stored
association fields only. It does not use fuzzy matching, embeddings, language
model classification, titles, similarity, or inferred values.

Each observation stores the deterministic rule version, occurrence count, first
and last source timestamps, an administrative rationale, and immutable source
bindings to the underlying association IDs. Source associations, documents,
record identities, history, and decisions are not modified.

## Governed review

New observations begin as `candidate`. An authenticated administrator may
record `accepted`, `rejected`, or `deferred` review decisions. Review history
is append-only. Acceptance records only that the recurrence is observable; it
does not record or imply intent, motive, causation, wrongdoing, or legal
significance. No such fields exist in the Stage 62 persistence contract.

## Administrative boundary

Stage 62 is currently administrative-only. Its GET surfaces use a read-only
SQLite connection and do not initialize the observation tables or mutate
source evidence. Candidate creation and review require the existing admin
session boundary and explicit POST commands. No public route or serializer is
expanded by this stage.

## Provenance and correction

Observation bindings preserve the source object identity from which the
candidate was derived. Re-running the same deterministic command is
idempotent; a semantic conflict with the same key fails closed. A later source
association correction does not rewrite the observation or its historical
bindings. Future correction work must follow the existing governed correction
philosophy.

Stage 62 does not expand the Stage 60 contract, change Stage 61 relationship
authority, or alter Stage 61.1/61.2 inspection and correction semantics. No
historical backfill or production observation was performed by this
implementation.

## Deployment verification

The deployed service returned HTTP 200 for `/` and `/records`. The
administrative pattern-observation surface returned HTTP 401 without an admin
session. `/api/pattern-observations`, `/pattern-observations`, and
`/api/admin/pattern-observations` returned HTTP 404, confirming that no public
Stage 62 route was introduced. Deployment verification performed no correction,
created no pattern observation, and modified no association or other production
data. No migration or Stage 62 persistence initialization was performed.
