# CDE Platform Stage 61.1 — Relationship Governed Decision Administrative Inspection

## Release State

Implemented · pending merge · pending deployment

## Purpose

Stage 61.1 adds an authenticated administrative diagnostic for inspecting
already persisted Record–Document Association governed-decision evidence. It
is an observability surface only; it does not create, repair, reconcile,
backfill, or otherwise modify association, history, or decision data.

## Observational Boundary

The diagnostic reader opens the relationship database in SQLite read-only mode,
checks for the Stage 61 decision table without creating it, and queries the
association and decision records directly. Decisions are ordered by their
recorded timestamp and identity. Missing tables, missing decisions, malformed
payloads, unresolved documents, unknown decision types, and inconsistent
creation evidence are reported as warnings without repair or initialization.

Raw stored identifiers remain separate from resolved presentation labels. The
diagnostic compares the raw persisted association document identifier with the
raw `association_created` request payload and reports `YES`, `NO`, or
`NOT DETERMINABLE` without comparing titles or public identifiers.

## Administrative and Stage 60 Boundaries

The route is protected by the existing authenticated administrator session and
is not public. Internal decision data, request payloads, rationale, actor role,
evidence, context, and idempotency identities remain administrative. Complete
idempotency keys are not displayed; only presence and a redacted fingerprint
are shown.

The Stage 60 `GovernedDecision` projection is displayed only as a passive view
of relationship-owned evidence. Stage 61.1 introduces no generic authority,
lifecycle engine, transition validation, evidence sufficiency rule, subject
resolution, persistence service, public decision API, historical backfill, or
production correction. Association 66 is a verification target only and is not
hard-coded into the diagnostic.

Existing Stage 56–61 authority, identity, history, relationship semantics,
public projections, lifecycle behavior, preservation, provenance, and
production data remain unchanged.
