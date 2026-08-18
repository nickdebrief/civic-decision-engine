# CDE Platform Stage 68 — Governed Appeal and Review Proceeding

**Status:** Implemented · pending merge · pending deployment

Stage 68 introduces a narrow, human-recorded, administrator-only record of an
appeal or review proceeding connected to exactly one governed Stage 67
determination. It preserves procedural challenge and review activity without
allowing the CDE to decide the challenge.

Its governing principle is:

> **CHALLENGE IS NOT REVERSAL**
> Recording an appeal or review proceeding does not reverse, suspend, vary,
> invalidate, or otherwise determine the effect of the challenged determination.

The challenge target, reviewing authority and mandate, source bindings, events,
reviews, supersessions, and outcomes are separate governed relationships.
Creation is immutable; reviews, procedural events, outcomes, and supersessions
are append-only and independently idempotent. Multiple challenges may coexist
for one determination. A recorded outcome may reference a separately governed
determination, but Stage 68 does not create or calculate that outcome and does
not mutate the challenged determination.

Challenge categories, applicant kinds, source roles, event types, statuses, and
outcome types are closed vocabularies. Sources and authority/mandate pairs are
revalidated transactionally at write time. Accepted Stage 62 observations may
provide only an eligible governed source or context under the existing rules;
silence is never synthesized into a filing, withdrawal, refusal, or outcome.

The administrative interface uses neutral selectors, escaped metadata, explicit
declarations, and read-only candidate enumeration. It has no public route,
serializer, navigation, search, export, feed, publication eligibility, public
API, automatic extraction, AI/LLM integration, merits analysis, suspension,
reversal, or legal-effect calculation. Stage 60–67.1 semantics remain
unchanged, and no production challenge is created by this implementation.

The existing signed, expiring, `HttpOnly`, `Secure`, `SameSite=Strict`
administrator-session boundary remains in force. Stage 68 does not claim
CSRF-token or Origin/Referer validation.

Focused tests cover source-bound creation, target and authority separation,
closed vocabularies, rollback, idempotency, append-only review/events/outcomes,
same-target supersession, read-only non-initializing diagnostics, and the
non-public epistemic boundary. Full validation excludes only the known
import-time manual script `test_cases/test_cases.py` when it attempts an HTTP
request to `127.0.0.1:8000` during collection; the seven raw-SQL migration files
stored with `.py` extensions remain an unrelated compilation limitation.
