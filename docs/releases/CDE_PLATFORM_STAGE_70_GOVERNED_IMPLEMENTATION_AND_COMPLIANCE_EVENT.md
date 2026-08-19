# CDE Platform Stage 70 — Governed Implementation and Compliance Event

## Purpose and boundary

Stage 70 preserves what an identified person, institution, submitter,
verifier or decision authority represents happened after a Stage 69 remedy or
direction. **IMPLEMENTATION REPORTED IS NOT IMPLEMENTATION VERIFIED.** A
reported action, submitted material, verification activity and formal
determination remain distinct events. Stage 70 never calculates
implementation, compliance, breach, satisfaction, completion, enforceability
or legal effect.

Each event is human-recorded, source-bound and linked to exactly one immutable
Stage 69 remedy. The remedy relationship is separate from source bindings and
governed-object relationships. Multiple reports, disputes, submissions,
verification records and formal determinations may coexist; absence of an
event does not establish performance or non-performance.

## Event and source model

The closed event categories are `implementation_reported`,
`partial_implementation_reported`, `implementation_disputed`,
`deadline_extension_recorded`, `compliance_evidence_submitted`,
`non_compliance_alleged`, `verification_performed`, and
`implementation_completed_as_formally_determined`. Their epistemic bases are
`attributed_report`, `documentary_submission`,
`independent_verification_record`, and `formal_determination`; incompatible
pairs are rejected rather than coerced.

Every event has an `event_source`. Verification and extension events require
their respective governed source roles. Source selection is metadata-only,
authenticated, bounded and read-only on GET; it does not establish sufficiency
or proof. Object links remain separate: non-compliance may reference an
existing Stage 64 allegation, while formal completion requires a distinct
eligible Stage 67 determination and does not create or mutate that
determination.

## High-risk boundaries

`non_compliance_alleged` remains an allegation and never becomes a remedy
status or finding. `verification_performed` preserves the verifier’s method,
capacity and attributed conclusion; it does not become verified implementation.
Formal completion requires an expressly represented, distinct eligible Stage
67 determination and a human declaration. Deadline extension records preserve
what the source represents without validating authorisation. No Stage 68
challenge, Stage 69 remedy, or prior epistemic object is mutated.

Reviews and supersessions are append-only and independently idempotent.
Acceptance means faithful representation, attribution and source connection
only. Supersession preserves the original event. The only lifecycle statuses
are event-record statuses: recorded, accepted as represented event,
representation correction required, not accepted as represented event, and
superseded. There is no aggregate compliance status.

## Administrative and public boundary

The authenticated administrator-only surface is
`/admin/governed-implementation-events`, linked from shared administration as
**Implementation and Compliance Events**. All selectors begin neutral and
empty; raw JSON is transport-only. GET inspection and candidate enumeration
use read-only SQLite access and do not initialise Stage 70 tables. Stage 70 is
absent from public routes, navigation, serializers, search, exports, feeds and
publication eligibility. No monitoring, reminders, scoring, automation, AI or
LLM integration is included.

The existing request-forgery boundary remains the signed, expiring,
HttpOnly, Secure, SameSite=Strict administrative session with non-GET
mutations and server-side validation. This release does not claim CSRF-token or
Origin/Referer validation.

## Ordering-contamination audit

The Stage 60–69 ordering investigation classified the reverse-order failure as
**Classification C — Identical Pre-existing Harness Defect**. The exact command
used for both states was `.venv/bin/python -m pytest -q -x` followed by the same
15-file Stage 60–69 list, once in forward order and once in reverse order.

The clean canonical baseline at `09218526d7cc99e49dc933e9b8e4d0895a1afe1d`
and the active Stage 70 worktree both passed the forward command with `242
passed, 19 subtests passed`. Both reverse runs reproducibly passed `186` tests
and `15` subtests before failing at
`tests/test_stage62_governed_pattern_observation.py::Stage62GovernedPatternObservationTests::test_authenticated_get_route_is_observational_when_table_is_absent`.
The failure occurred during test execution, not collection, import or setup:
`AttributeError: 'HTMLResponse' object has no attribute 'content'`.

The cause is an older test module that installs a `FakeResponse` by assigning
`fastapi.responses.HTMLResponse` globally at import time without restoring it.
In the reverse sequence, `api.routes.admin_session` retains the real Starlette
`HTMLResponse` while the later stub replaces the response module's class; the
Stage 62 test then receives the real response and checks for `.content`. A
repeat of each reverse run produced the same first failure and traceback.
Including Stage 70 in the reverse sequence changed neither the first failure
nor the contaminated objects. Stage 70 does not import the affected route at
module import time, replace framework classes, mutate `sys.modules`, or add an
import-time side effect. No Stage 70 or production code was changed to conceal
this pre-existing harness defect, and the older harness remains outside this
release.

## Testing and deployment boundary

Focused tests cover event creation, remedy linkage, closed vocabularies,
declarations, source and object separation, rollback, idempotency, reviews,
supersession, read-only inspection and administrative/public boundaries.
Compatibility, ledger, platform-identity, navigation and full regression tests
cover preservation of Stages 60–69. The implementation was rebase-merged as
PR [#372](https://github.com/nickdebrief/civic-decision-engine/pull/372), with
local commit `d73d60321e6602b9319a6ffec8b52f490351316c` and canonical merge
revision `92dad4ab9669c44431af759f6791141988c74844`.

The automatic Railway deployment was recorded by GitHub as deployment
`5978226149` in `precious-gentleness / production`, created at
`2026-08-19T07:43:33Z` and reaching terminal success at
`2026-08-19T07:44:13Z` for the canonical revision. Non-mutating public smoke
checks returned 200 for `/` and `/records`, 401 for the protected Stage 70
and Stage 69 administration routes, and 404 for plausible public Stage 70
paths. Public root and records responses contained no Stage 70 content.
Authenticated inspection was unavailable; no production form was submitted.
Stage 70 is registered as **Implemented · merged · deployed**. No production
event or production mutation was created by implementation, validation or
verification.

## Local maintenance correction: conditional declarations

The deployed Stage 70 form previously used generic conditional-declaration
wording after category selection. The maintenance correction replaces that
presentation with a disabled neutral control before selection and the
server-owned, category-specific declaration after selection. The server now
rejects category mismatches, unknown declaration fields, malformed values and
inapplicable declarations, while preserving transactional creation and
idempotency. Direct submissions remain governed by the submitted event
category, independent of JavaScript.

The correction was committed locally as
`2fd4389bae3de64402718736dd5e3783e2990ed8`, merged by rebase through PR #374,
and deployed in canonical revision
`d2ccf9d6ec87b41892cc24fc540978d5809af539`. Automatic deployment `5979696698`
targeted `precious-gentleness / production`, was created at
`2026-08-19T09:28:07Z`, and reached successful terminal status at
`2026-08-19T09:28:37Z`.

Non-mutating public smoke verification passed: `/` and `/records` returned
HTTP 200; `/admin/governed-implementation-events` and
`/admin/governed-remedies` returned HTTP 401; plausible public Stage 70 paths
returned HTTP 404; and public root and records responses contained no Stage 70
content. Authenticated production inspection was unavailable. No production
form was submitted and no production event, review, supersession, source
binding, governed-object link or other data was created or changed.

The reverse-order HTMLResponse.content result remains Classification C: the
canonical baseline and Stage 70 comparison fail identically because older test
modules replace FastAPI response classes globally at import time without
restoring them. Stage 70 does not contribute to that contamination, and no
unrelated harness correction was made.
