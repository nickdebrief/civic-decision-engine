# CDE Platform Stage 67.1 — Deliberate Determination Linking and Source Selection

**Status:** Implemented · pending merge · pending deployment

Stage 67.1 refines the authenticated Stage 67 administrative creation workflow. Its governing invariant is:

> **CONNECTION IS NOT RELIANCE**
> A determination may be connected to a governed object without establishing that the decision authority relied upon it.

Authority and mandate selection, determination-source binding, and governed-object linking begin empty and require deliberate administrator selection. Candidate enumeration is bounded, metadata-only, authenticated, and read-only. Source bindings remain structurally separate from governed-object links, and neither selection nor connection establishes consideration, reliance, acceptance, factual correctness, legal correctness, or evidential weight.

The existing Stage 67 source and object vocabularies, persistence identities, lifecycle, review, supersession, effect-event history, and idempotency contracts remain unchanged. The existing represented-time authority/mandate eligibility rule and malformed-date rejection remain enforced at final submission. A human declaration records the deliberate-linking boundary in the existing declaration payload; it does not replace structural validation.

The workflow has separate sections for determination content, authority and mandate, sources, governed-object links, qualification, declarations, and submission. Raw editable JSON is absent. Hidden payloads begin empty, selection and removal are client-side only, and final server-side validation remains authoritative with transactional rollback for invalid multi-selection requests.

Stage 67.1 remains administrator-only and non-public. It adds no public route, serializer, search, export, publication eligibility, recommendation, ranking, automation, AI/LLM integration, legal-effect calculation, migration, or production mutation. The repository’s existing signed, expiring, `HttpOnly`, `Secure`, `SameSite=Strict` administrative-session boundary remains in force; no CSRF-token or Origin/Referer protection is claimed.

Focused tests cover neutral defaults, deliberate payloads, read-only candidate enumeration, source/object separation, validation and rollback, idempotency compatibility, escaping, accessible controls, public absence, and epistemically restrained language. Production deployment remains a separately authorised operation.
