# CDE Platform Stage 69 — Governed Remedy and Direction

## Purpose

Stage 69 preserves a human-recorded remedy or direction expressly represented
in a governed Stage 67 determination.

**DIRECTION IS NOT IMPLEMENTATION.** The record may establish what an
authorised determination directed. It does not establish that the direction
was carried out, complied with, satisfied, enforced, lawful, valid, final or
complete.

## Boundary

Each remedy has its own identity and is linked to exactly one determination.
Direction sources are validated against the existing governed source domains;
the link to a determination is kept separate from source bindings. Categories,
direction types and representation modes are closed and begin with neutral
administrative selections. `no_remedy_directed` requires an explicit source-
backed declaration and is never inferred from silence or missing material.

Creation, review and supersession are human-recorded, administrator-only,
transactional, idempotent and append-only. Review confirms preservation and
attribution only. Supersession preserves both representations. Stage 69 adds
no implementation, compliance, enforcement, payment, deadline, legal-effect,
automatic extraction, AI or public architecture.

Authenticated GET inspection and candidate enumeration are read-only and do
not initialise Stage 69 tables. The existing administrative boundary is a
signed, expiring, HttpOnly, Secure, SameSite=Strict session with non-GET
mutations and server-side validation; the repository does not claim a CSRF
token or Origin/Referer protection.

Focused tests cover the qualification and declaration contracts, source and
determination validation, rollback, idempotency, append-only history,
no-remedy safeguards, administrative navigation and the public boundary.

Deployment remains separately governed. No production remedy is created by
Stage 69 implementation or tests.
