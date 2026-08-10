# CDE Platform Stage 59 — Lifecycle Episode Presentation

## Release State

Implemented · pending merge · pending deployment

## Purpose

Stage 59 makes the existing Stage 58 lifecycle-episode model understandable
across public and administrative presentation surfaces. It is a read-only
presentation stage, not a lifecycle-governance redesign.

Stage 58 makes lifecycle decisions durable. Stage 59 makes the original and
subsequent lifecycle episodes visible without presenting reconsideration as a
reversal or an `Archived -> Pending` transition.

## Presentation Model

The presentation read model groups existing durable evidence as follows:

- implicit Episode 1 from existing Stage 56 events whose `episode_id` is null;
- explicit subsequent episodes from `document_lifecycle_episodes`;
- episode-scoped durable lifecycle decisions;
- current status and current episode summary.

No Episode 1 row is created. No historical evidence is backfilled or changed.
The assembler is observational and does not resolve public eligibility,
repair metadata, reconcile projections, allocate identifiers, or write
governance evidence.

## Public Presentation

The Published Document detail pathway retains separate Original lifecycle and
Subsequent governed consideration sections. Public provenance selects review,
approval, and publication evidence from the episode responsible for the
current eligible publication rather than using flattened first-event lookup.

The Public Document Library uses a compact responsive document-row layout. It
keeps the title, Document Identifier, current Published status, publication
date, and open/preview action immediately visible. Reconsidered publications
may display the compact public-safe label `Published · Governed
reconsideration`; internal `LEP-*` identifiers and private governance
evidence are not exposed.

## Administrative Presentation

Document Status History and `/admin/audit` retain their existing evidence and
classification machinery while adding episode context. Administrators can
distinguish Episode 1 — Original consideration from subsequent governed
episodes without introducing a second audit system or durable evidence
source.

## Boundaries

Stage 59 introduces no lifecycle states or transitions, no reconsideration
semantics, no schema or migration, no episode backfill, no eligibility
resolver, no metadata mutation, and no preservation, relationship, identity,
hashing, correction, or Canonical Record change. GET rendering remains
observational. Existing fail-closed public eligibility remains authoritative.

Source emails and independently preserved attachments remain lifecycle
independent. Episode presentation is scoped to the transitioned intake.
