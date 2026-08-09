# CDE Platform Stage 57 — Governed Lifecycle Decision Confirmation

## Purpose

Stage 57 is an authenticated administrative UX and governance-boundary refinement. It arose from a production UX observation: an administrator intended to approve a document but selected Reject. Stage 56 correctly recorded the submitted `Under Review -> Rejected` decision and preserved its rationale; Stage 56 evidence integrity was not defective.

Stage 56 makes lifecycle decisions durable. Stage 57 makes committing a durable lifecycle decision deliberate.

## Confirmation Boundary

Lifecycle action selection now produces a server-rendered proposed decision before the durable transition is committed. The confirmation view shows the available Document Identifier, document title or filename, current state, proposed state, authenticated actor and role, the normalized rationale, and the recorded SHA-256 where available. Its final control names the consequence explicitly, such as `Confirm Approval`, `Confirm Rejection`, `Confirm Publication`, or `Confirm Archival`.

The proposal is carried in a short-lived, HMAC-signed server token containing the complete decision evidence. The confirmation request revalidates the token, authenticated session identity, current lifecycle state, and freshly prepared decision before invoking the existing `update_intake_status(...)` coordinator. Tampering or a stale state fails safely. Cancel performs no lifecycle write.

## Stage 56 Boundary

Stage 56 remains the sole normal lifecycle coordinator and remains authoritative for transition validation, rationale rules, identifier resolution, digest requirements, actor and role binding, durable event recording, idempotency, event-first ordering, and projection handling. Stage 57 does not create a second decision store or persistence mechanism.

GET rendering remains observational. Confirmation adds no lifecycle states, Published Document identities, relationship types, hashes, public routes, public disclosure rules, correction or reversal model, migration, backfill, or production-data change. Existing publication and rationale disclosure semantics remain unchanged.

## Scope

This stage changes only the authenticated administrative decision workflow and its focused regression/documentation coverage. Email attachment documents remain independent lifecycle objects; no relationship traversal or lifecycle propagation is introduced.
