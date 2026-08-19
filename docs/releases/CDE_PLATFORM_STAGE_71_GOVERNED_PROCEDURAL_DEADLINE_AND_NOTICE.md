# CDE Platform Stage 71 — Governed Procedural Deadline and Notice

## Purpose

Stage 71 preserves source-bound procedural notices, deadlines, extensions,
disputes, deterministic date calculations and links to separately governed
late-filing determinations. It is authenticated administrator-only and does
not expose procedural records publicly.

## Boundary

**TIME CALCULATED IS NOT LATENESS DETERMINED.** Notice issued is not notice
received. Dispatch, availability, silence, participation and elapsed time do
not establish receipt, valid service, waiver, abandonment, admissibility,
default, lateness, jurisdiction or legal effect.

Notice and deadline identities are distinct. Notices and deadlines are human
recorded; calculations are deterministic only when an administrator supplies
all persisted inputs, including the calculation instant. The initial
calculation modes are `explicit_deadline_comparison` and
`calendar_days_after_explicit_trigger`. Business-day, holiday, deemed-service
and jurisdiction-specific rules are unsupported.

## Architecture

The isolated persistence module uses separate notice and deadline tables,
source bindings, procedural-subject links, append-only events, calculations,
reviews and supersessions. Source bindings remain separate from governed
object links. Accepted observations are the only prior epistemic object
available through the narrow source architecture; inferences, allegations and
responses are not source evidence.

Extension requests and grants coexist with the immutable original deadline.
Late-filing allegations require an existing Stage 64 allegation. A formal
late-filing event links an existing eligible Stage 67 determination and never
creates or mutates a determination or any Stage 68–70 object.

Reviews preserve source-bound procedural representation only. Supersession is
append-only, preserves history, rejects self-reference and cycles, and is not
an extension mechanism.

## Administration and exclusions

The authenticated administration surface is `/admin/governed-procedural-time`
and is reachable from the shared administrator navigation as **Procedural
Deadlines and Notices**. GET inspection and candidate enumeration are
read-only and do not initialize Stage 71 tables. Mutations use the existing
signed, expiring, HttpOnly, Secure, SameSite=Strict admin session and
server-side validation boundary; this release does not claim CSRF-token or
Origin/Referer protection.

There are no public routes, serializers, search, exports, feeds, APIs,
publication eligibility, background monitors, reminders, notifications,
automatic receipt inference, automatic lateness classification or legal-effect
calculation. No Stage 60–70 tables or semantics are modified.

## Validation and deployment boundary

Focused tests cover the notice/deadline distinction, source and subject
validation, extensions, disputes, deterministic calculations, formal and
allegation boundaries, declarations, rollback, idempotency, review,
supersession, read-only inspection, authentication, navigation and public
absence. Compatibility, order, ledger, compilation, diff and conflict checks
are run before integration. This local implementation is registered as
## Closure evidence

Stage 71 was merged through [PR #377](https://github.com/nickdebrief/civic-decision-engine/pull/377)
using rebase merge. The canonical merged revision is
`d4e5a39d0e7e67bc03ec4297bf508d087d3e4463`.

Automatic Railway deployment `5989012391` targeted that exact revision in the
`precious-gentleness / production` environment. It was created at
`2026-08-19T18:53:41Z` and reached successful terminal status at
`2026-08-19T18:54:10Z`.

Non-mutating smoke verification returned HTTP 200 for `/` and `/records`,
HTTP 401 for unauthenticated `/admin/governed-procedural-time`, and HTTP 404
for plausible public Stage 71 paths. Public root and records responses did not
contain Stage 71 content. No authenticated production inspection was
performed, no form was submitted, and no procedural object or other production
data was created or changed.

The Stage Ledger status is now **Implemented · merged · deployed**.
