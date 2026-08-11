# CDE Platform Stage 61.2 — Governed Relationship Correction

## Purpose

Stage 61.2 adds a narrow, relationship-owned correction mechanism for Record–Document Associations. A correction is a new accountable fact about an earlier accountable fact: it preserves the original association, its Stage 61 decisions, request payload, rationale, timestamps, actors, and history, while recording a later determination that the original association should no longer govern.

The implementation does not correct production Association 66. It provides the prospective mechanism and isolated verification only.

## Correction contract

The additive `record_document_association_corrections` table stores an immutable correction identity, unique relationship-domain idempotency key, original association and optional original Stage 61 decision, fixed category `erroneous_association_binding`, resolution mode (`reuse_existing` or `create_new`), private rationale, session-derived actor and role, server timestamp, canonical opaque evidence references, optional context, replacement association, and canonical request payload.

Only successfully committed corrections exist durably. There is no generic correction lifecycle and no historical backfill.

An active explicitly selected replacement may be reused. An inactive replacement, the original association, an ambiguous candidate, or an invalid binding fails closed. A new replacement is created only from an explicit validated binding. Existing association authority remains responsible for relationship legality, mutation, history, and Stage 61 decision recording.

## Atomicity and idempotency

Correction evidence, governed deactivation, legacy history, and any replacement creation and decision share one relationship-owned SQLite transaction. Child Stage 61 operations use distinct derived idempotency keys. A retry with the same key and canonical semantic payload returns the committed correction; a semantic conflict fails closed. Any failure rolls back all new consequences without changing historical evidence.

## Evidence boundary

Evidence references are opaque to Stage 60. Association 66 facts, administrative text, and repository regression evidence remain distinguishable from unproven browser-interaction inferences. The correction rationale records the administrative determination without fabricating the original browser sequence.

## Stage 60 and Stage 61.1

The correction adapter is a passive `GovernedDecision` projection with subject type `record_document_association` and the original association ID as subject. `api/governed_decisions.py` is unchanged. Stage 61 remains authoritative for association operations. Stage 61.1 remains a read-only `mode=ro` diagnostic and cannot authorize, create, repair, or execute a correction.

## Disclosure and compatibility

Correction identity, original decision identity, idempotency, actor role, rationale, evidence, context, and request payload remain administrative. No public API or public association serializer is expanded. Existing association, document, attachment, lifecycle, provenance, and identifier semantics remain unchanged. Legacy associations may be corrected only when the administrator explicitly acknowledges that no historical Stage 61 creation decision exists; no synthetic decision is created.

## Status

Implemented · pending merge · pending deployment. No production correction or production-data mutation is included.
