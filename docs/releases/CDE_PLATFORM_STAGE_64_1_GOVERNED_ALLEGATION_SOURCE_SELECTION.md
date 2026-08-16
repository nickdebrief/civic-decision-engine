# CDE Platform Stage 64.1 — Governed Allegation Source Selection

Status: Implemented · merged · deployed

Implementation PR: [#352](https://github.com/nickdebrief/civic-decision-engine/pull/352)

Canonical implementation and deployed revision: `3a6ed578e3e8ff366f845ea60aa9f89c1d965b88`

Railway deployment: `5930698486`

Deployment started: `2026-08-16T11:58:01Z`

Deployment completed successfully: `2026-08-16T11:58:30Z`

Production verification confirmed `/` and `/records` returned HTTP 200,
unauthenticated `/admin/governed-allegations` returned HTTP 401, and
plausible public Stage 64 endpoints returned HTTP 404 without Stage 64
content. No production allegation, binding, review, supersession, withdrawal,
or other production-data mutation was performed.

## Source-integrity boundary

**SOURCE BINDING REQUIRES DELIBERATE SELECTION**

A governed allegation must not inherit, assume, or silently receive its source.
Stage 64.1 removes the raw and pre-populated source-binding JSON control from
the administrator-facing creation form. No source is selected when the form
loads.

Administrators select an eligible governed source, inspect restrained metadata,
choose an explicit binding role, add it to the pending selection, review the
selected list, and may remove a selection before submission. The browser sends
structured selection data; the server revalidates every source, type, role,
eligibility state, and attribution-source requirement transactionally.

Eligible sources remain the Stage 64 vocabulary: governed or Published
Documents, Canonical Records, governed Record–Document Associations, and
accepted Stage 62 observations. Inference and allegation objects, arbitrary
URLs, free-text identifiers, unsupported objects, and ineligible observations
are rejected.

Creation offers only `attribution_source`, `contextual_source`,
`response_source`, and `contrary_source`. A withdrawal source is available
only in the separate withdrawal workflow and is never offered on creation.
Attribution identifies where an allegation was made or preserved; it does not
confirm truth. Context, responses, and contrary material do not automatically
resolve the allegation.

## Operational boundary

Source lookup and inspection are authenticated, read-only, and do not
initialize Stage 64 storage, create records, mutate source objects, or record a
selection. Existing Stage 64 persistence, identities, lifecycle, idempotency,
review, supersession, withdrawal, and public-boundary behavior are unchanged.
No source recommendation, matching, extraction, OCR, LLM/AI behavior,
corroboration, truth scoring, public route, serializer, search exposure,
publication eligibility, migration, or production mutation is introduced.

The selector follows existing administrative source-selection conventions for
search, metadata display, escaping, keyboard-labelled controls, and deliberate
add/remove interaction. Validation coverage includes eligible source types,
role requirements, stale and tampered selections, rollback, withdrawal-source
separation, and compatibility with Stages 60–64.
