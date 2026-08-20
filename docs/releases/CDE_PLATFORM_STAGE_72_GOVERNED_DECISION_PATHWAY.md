# CDE Platform Stage 72 — Governed Decision Pathway

## Status

Implemented · pending merge · pending deployment

Stage 72 is an additive administrative relationship and inspection layer. It
does not alter the identities, schemas, lifecycle rules or meanings of the
governed objects established by Stages 60–71.

## Governing Boundary

Stage 72 records deliberate, authenticated human pathway links and projects
relationships already owned by earlier stages. A link records a represented
relationship; it does not prove the relationship correct. Reliance represented
is not reliance justified. Chronology is not causation. A pathway view is not a
completeness claim.

The feature is not an inference engine, recommendation system, evidence-weight
calculator, causal model, legal analysis, finding generator, public graph or
automatic relationship creator. No background process creates links.

## Relationship Model

The isolated `record_governed_pathway` module stores only controlled,
append-only Stage72 links that are not already canonically owned elsewhere.
Each link has stable endpoint identities, a closed relationship type, rationale,
creator, timestamp, deliberate reliance and contestation representations,
limitations, a required relationship-source binding, schema/version metadata,
idempotency and lifecycle state.

Permitted directions are evidence to observation, inference or allegation;
allegation to response; authority or mandate to determination; governed
observation, inference, allegation or response to determination; determination
to challenge or remedy; and remedy to implementation. Unsupported directions,
self-links, unknown endpoints and arbitrary object kinds are rejected.

Existing Stage65–70 owned links are projected read-only with
`canonical_existing_relationship` provenance rather than duplicated. A
supporting document or source binding remains separate from both endpoints.

## Reliance, Contestation and Chronology

Reliance is selected deliberately from a closed vocabulary and never defaults
to expressed reliance. Applicable statuses require a human description and
boundary declaration. The record preserves only that reliance was represented,
considered, disputed or expressly not represented; it does not establish
correctness, reasonableness, sufficiency, weight, acceptance or determinative
effect.

Contestation is displayed or recorded as represented. Contrary material,
appeal, review, withdrawal and supersession remain visible and do not reverse,
delete or invalidate a link automatically.

Chronology orders persisted Stage72 creation timestamps deterministically with
link identity as the tie-breaker. The view distinguishes recorded sequence
from causation, legal effect and completeness. Earlier-stage procedural dates
are not fabricated or promoted into Stage72 links.

Reviews and supersessions are append-only and independently idempotent.
Idempotency conflicts fail safely, and a superseded link remains inspectable.

## Administrative Boundary

The authenticated `/admin/governed-pathway` surface provides structured tables,
object-centred inspection and chronological inspection. Selectors are neutral
and empty by default. Candidate enumeration and diagnostics use read-only
SQLite access and do not initialise Stage72 tables. Mutations require the
existing signed, expiring administrative session boundary and server-side
endpoint, direction, source and declaration validation.

No public route, public navigation item, serializer, search, feed, export,
publication eligibility or unauthenticated candidate endpoint is added.

## Limitations and Validation

Omitted objects may exist; contrary material and unresolved endpoint states may
coexist. A pathway does not assert that all relevant objects or relationships
have been recorded. Stage72 does not calculate legal status, evidential weight,
causation, reliance justification or completeness.

Focused Stage72 tests cover isolated schema creation, controlled directions,
endpoint and binding validation, deliberate reliance, idempotency, append-only
review and supersession, canonical projection, read-only diagnostics and the
authenticated neutral administrative surface. Compatibility, public-boundary,
ledger and full applicable regression validation is performed before any merge.
