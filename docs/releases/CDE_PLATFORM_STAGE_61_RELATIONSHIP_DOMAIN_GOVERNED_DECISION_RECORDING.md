# CDE Platform Stage 61 — Relationship-Domain Governed Decision Recording

## Release State

Implemented · pending merge · pending deployment

## Purpose

Stage 61 adds prospective, relationship-owned governed decision evidence for
Record–Document Associations. The association remains the governed subject
and the relationship domain remains authoritative for validation,
authorization, mutation, public/private policy, and consequences.

## Governed Operations

The relationship domain records four semantic operations:

- `association_created`
- `relationship_reclassified`
- `association_deactivated`
- `association_reactivated`

Each prospective operation requires explicit private rationale, authenticated
actor attribution, the actor role at decision time, a durable relationship
decision identity, and a unique relationship-owned idempotency key. The
association mutation, existing CRUD history row, and governed decision row
commit atomically or roll back together.

Commands may supply an idempotency key. When omitted, the relationship domain
derives an `rda-` key from a canonical semantic request payload containing the
association subject or source/target binding, operation type, governed
relationship state, actor, role, and rationale. Presentation-only labels,
notes, and visibility values are excluded from conflict identity. An explicit
key is required when a caller needs retry reuse across independently submitted
requests; a reused key with a different semantic payload fails closed.

Note-only changes, visibility-only changes, and non-semantic administrative
metadata corrections remain ordinary audit mutations. Duplicate attempts and
other requests rejected before authoritative mutation do not create fictional
decisions. Existing association history remains historical CRUD/audit
evidence and is not backfilled or reclassified.

## Stage 60 Boundary

The new relationship decision record is adapted passively to the Stage 60
`GovernedDecision` contract using the existing internal association database
ID as the opaque subject identity under
`record_document_association`. The public `CDE-ASSOC-*` reference remains
unchanged and distinct from decision identity. `api/governed_decisions.py`
requires no semantic expansion.

Stage 61 introduces no generic writer, lifecycle engine, authorization,
transition validator, evidence sufficiency rule, subject resolver, public
decision API, or cross-domain persistence service. Evidence and context
references remain relationship-owned and opaque to Stage 60.

## Compatibility and Non-Goals

Stage 61 is prospective only. It introduces one additive relationship-owned
decision table and no historical migration or backfill. Existing association
identifiers, relationship types, history, Canonical Record behavior, Published
Document lifecycle decisions, lifecycle episodes, confirmation,
reconciliation, publication eligibility, DOC-* identity, EAR-* identity,
attachment preservation, provenance, public disclosure, and production data
remain unchanged.

GET/read paths remain observational with respect to decision evidence. Email
Attachment relationships, Record Attachment relationships, and the Mailbox
Relationship Graph are outside this stage. Stage 61 establishes the first
prospective non-document adoption of the passive Stage 60 contract; it does
not generalize the relationship domain or claim a universal governance
authority.
