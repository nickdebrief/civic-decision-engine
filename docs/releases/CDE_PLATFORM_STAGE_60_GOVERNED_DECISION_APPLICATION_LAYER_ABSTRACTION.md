# CDE Platform Stage 60 — Governed Decision Application-Layer Abstraction

## Release State

Implemented · merged · deployed

## Purpose

Stage 60 introduces a passive application-layer representation of accountable
decision evidence. It establishes shared accountability without introducing a
universal lifecycle engine or replacing domain-specific authority.

The abstraction preserves the distinctions established by Stages 56–59:

- a durable decision record is evidence of what occurred;
- domain code determines whether the decision was permitted;
- reconciliation, confirmation, eligibility, and consequences remain domain-specific;
- subject identity is domain-owned and separate from presentation.

## Contract

`GovernedDecision` requires a decision identity, an opaque subject reference,
actor, actor role, and decision time. Optional fields represent domain-defined
decision type, previous/resulting state, rationale, opaque evidence references,
opaque context, and idempotency identity.

State values are not validated by the generic contract. Rationale is not
universally required. The generic contract does not authorize, reconcile,
confirm, publish, allocate identifiers, create relationships, or mutate a
subject.

## Published Document Adapter

Existing Stage 56 and Stage 58 lifecycle events are represented read-only:

- `decision_key` maps to `decision_id` and, initially, `idempotency_key`;
- `intake_id` maps to the `published_document` subject ID;
- `previous_status` and `new_status` map to optional state fields;
- actor, role, timestamp, and rationale are preserved;
- the existing decision key is exposed as an opaque evidence reference;
- `episode_id` is exposed only as optional context for explicit episodes.

The adapter does not use the DOC-* Document Identifier as subject identity.
It does not rewrite or persist events, initialize schema, backfill Episode 1,
or route any existing lifecycle writes through the abstraction.

## Cross-Domain Boundary

Lightweight contract fixtures demonstrate that hypothetical Investigation and
Evidence Relationship decisions can retain their own subjects, states,
evidence, authority, validation, reconciliation, consequences, and disclosure
rules. No second production domain is implemented by Stage 60.

The first future production proof should preferably use the Evidence
Relationship domain because it is a genuinely different governed subject while
remaining close to CDE provenance and accountability concerns.

## Compatibility and Non-Goals

Stage 60 introduces no schema, migration, historical backfill, generic decision
store, new evidence graph, lifecycle state, transition, authorization model,
confirmation behavior, reconciliation behavior, eligibility behavior,
preservation behavior, relationship behavior, or production-data change.

Existing Stage 56–59 decision keys, sequences, episode identities, document
identity, lifecycle authority, metadata projections, public eligibility, and
presentation semantics remain unchanged.
