# CDE Platform Stage 67.1 — Deliberate Determination Linking and Source Selection

**Status:** Implemented · merged · deployed

The implementation was merged through [PR #365](https://github.com/nickdebrief/civic-decision-engine/pull/365) using the rebase method as canonical main revision `ba47640eb78244b5404e43dd998d80add71fb41b`. Railway deployment `5946047974` for that exact revision was reported ACTIVE and successful in the Railway interface, and production inspection confirmed the deployed workflow. The GitHub deployment callback created during the documented GitHub incident remained stale at `in_progress`/pending; no replacement deployment was triggered. The accessible callback metadata does not expose a reliable Railway completion timestamp.

Stage 67.1 refines the authenticated Stage 67 administrative creation workflow. Its governing invariant is:

> **CONNECTION IS NOT RELIANCE**
> A determination may be connected to a governed object without establishing that the decision authority relied upon it.

Authority and mandate selection, determination-source binding, and governed-object linking begin empty and require deliberate administrator selection. Candidate enumeration is bounded, metadata-only, authenticated, and read-only. Source bindings remain structurally separate from governed-object links, and neither selection nor connection establishes consideration, reliance, acceptance, factual correctness, legal correctness, or evidential weight.

The existing Stage 67 source and object vocabularies, persistence identities, lifecycle, review, supersession, effect-event history, and idempotency contracts remain unchanged. The existing represented-time authority/mandate eligibility rule and malformed-date rejection remain enforced at final submission. A human declaration records the deliberate-linking boundary in the existing declaration payload; it does not replace structural validation.

The workflow has separate sections for determination content, authority and mandate, sources, governed-object links, qualification, declarations, and submission. Raw editable JSON is absent. Hidden payloads begin empty, selection and removal are client-side only, and final server-side validation remains authoritative with transactional rollback for invalid multi-selection requests.

Stage 67.1 remains administrator-only and non-public. It adds no public route, serializer, search, export, publication eligibility, recommendation, ranking, automation, AI/LLM integration, legal-effect calculation, migration, or production mutation. The repository’s existing signed, expiring, `HttpOnly`, `Secure`, `SameSite=Strict` administrative-session boundary remains in force; no CSRF-token or Origin/Referer protection is claimed.

Focused tests cover neutral defaults, deliberate payloads, read-only candidate enumeration, source/object separation, validation and rollback, idempotency compatibility, escaping, accessible controls, public absence, and epistemically restrained language. Production inspection was non-mutating: no determination was recorded and no production form was submitted. No public exposure, automated link, inferred reliance, automated determination, or production data mutation occurred.
