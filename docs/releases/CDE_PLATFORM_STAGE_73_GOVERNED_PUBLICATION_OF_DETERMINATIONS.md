# CDE Platform Stage 73 — Governed Publication of Determinations

Stage 73 adds an authenticated, additive publication layer for eligible Stage 67
determinations. A determination is not public by default. Publication stores a
separate immutable representation and requires deliberate eligibility, privacy,
redaction, authority and mandate inspection, reasons status, challenge warning,
current-effect qualification, approval, and publication actions.

The public surface exposes only records in the explicit `published` lifecycle
state. Drafts, failed reviews, withdrawn records, internal sources, reviewer
metadata, and Stage 72 pathway data are not exposed. Withdrawal and supersession
preserve historical publication records and their content digests.

## Governing boundary

**A DETERMINATION MAY BE PUBLISHABLE. IT IS NOT PUBLISHED BY DEFAULT.**

**PUBLICATION MAKES A GOVERNED REPRESENTATION VISIBLE. IT DOES NOT ESTABLISH THE DETERMINATION CORRECT.**

**REASONS VISIBLE IS NOT REASONS ADEQUATE.**

**CURRENT EFFECT REPRESENTED IS NOT LEGAL EFFECT ESTABLISHED.**

**ABSENCE OF A CHALLENGE FROM THE PUBLISHED VIEW DOES NOT PROVE THAT NO CHALLENGE EXISTS.**

Stage 73 does not mutate Stage 67, validate legal authority, infer privacy
clearance, copy private sources, calculate effect, or publish automatically.
The existing handbook Publication Engine remains a document-build pipeline;
Stage 73 owns governed application publication snapshots because no existing
runtime publication object owns this workflow.

## Deliberate selection boundary

All user-selectable publication classifications begin with an explicit empty
`Choose ...` option: representation mode, reasons status, challenge-warning
status, current-effect status, and review statuses. No substantive value is
selected on the initial administrative GET. Challenge-warning text is empty
until a status is deliberately selected, and incompatible status/text pairs
are rejected server-side. Client-side clearing of dependent text is only an
interface enhancement; the server remains authoritative and rejects empty,
unknown, stale, or contradictory values.

## Validation

The implementation is registered as `Implemented · merged · deployed`. Focused persistence, administrative-boundary, public-disclosure,
immutable-history, and Stage 60–73 compatibility tests are required before
integration. The known `test_cases/test_cases.py` manual script remains excluded
because it performs an import-time request to `127.0.0.1:8000`. The seven
pre-existing raw-SQL migration files are not compiled or modified.

## Lifecycle and visibility

The publication lifecycle is:

`draft` -> `eligibility_reviewed` -> `privacy_reviewed` ->
`redaction_reviewed` -> `authority_and_mandate_inspected` -> `awaiting_approval`
-> `approved_for_publication` -> `published`.

`withdrawn_from_publication` and `superseded` are terminal historical states.
Every transition is recorded in append-only review or event history. Approval
requires eligible status, cleared privacy and redaction reviews, authority and
mandate inspection, a recorded publication-context review covering reasons,
challenge warning, current-effect qualification and limitations, and a separate
approval actor. Publication is a separate action and requires a publisher who is
not any prior review or approval actor.

Only `published` records with a valid immutable content digest appear in the
public collection. Withdrawn and superseded detail routes return safe
non-disclosure, while their administrative history remains inspectable. A
correction is a new publication version with a new identity and digest; no
published snapshot is edited in place. The public collection is available at
`/determinations` but is not added to public navigation, so an empty collection
does not imply that a determination exists or is publishable.

Authority IDs and mandate IDs are retained from the Stage 67 relationship for
inspection only. They are not legal-validity conclusions. The digest covers the
approved public snapshot fields and excludes administrative actors, idempotency
keys, review rationale, and internal sources. Public output excludes those
internal fields and all Stage 72 pathway data.

## Closure Evidence

The initial implementation was merged through [PR #383](https://github.com/nickdebrief/civic-decision-engine/pull/383)
using rebase merge. Its implementation commit was `e43365d`; the canonical
implementation revision was
`2ef01b41b03e8370c579a670062159ea8fb8e8c4`.

The deliberate-selection correction was merged through
[PR #384](https://github.com/nickdebrief/civic-decision-engine/pull/384)
using rebase merge. Its correction commit was `abebc34`; the corrected
canonical revision was
`6c5853c0b40ae748ee6d8e851133199cfdb8b757`.

The corrected revision was deployed to `precious-gentleness / production` as
Railway deployment `6004245442`, created at `2026-08-20T14:24:34Z` and reaching
successful terminal status at `2026-08-20T14:25:04Z`. GitHub recorded the
revision-specific deployment and success status. The Railway CLI remained
unauthenticated; that operational limitation is retained rather than treated
as deployment evidence.

Non-mutating production checks returned 200 for `/` and `/records`, 200 with a
safe empty state for `/determinations`, 404 for synthetic and malformed
publication details, and 401 for the protected Stage 73 administration route.
Public navigation contained no Determinations entry and no private canary was
exposed. Authenticated inspection confirmed all initial publication selectors
and text fields were empty or neutral, no substantive classification was
selected, no contradictory challenge representation remained, and no
publication snapshot existed. No form was submitted and no production data
was created or changed. Later workflow forms were not opened because no
production publication record exists; their neutral states remain covered by
local tests.

The Stage 73 Ledger status is now **Implemented · merged · deployed**.
