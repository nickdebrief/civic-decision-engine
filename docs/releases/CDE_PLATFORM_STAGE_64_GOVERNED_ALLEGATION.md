# CDE Platform Stage 64 — Governed Allegation

Status: Implemented · merged · deployed

Implementation PR: [#350](https://github.com/nickdebrief/civic-decision-engine/pull/350)

Canonical implementation revision: `b5e776cfe8018550f52e7158a34b35cd604a7da5`

Automatic Railway deployment: `5930384616` — successful, completed
`2026-08-16T11:17:38Z` for the production environment.

Production verification: `/` and `/records` returned HTTP 200; unauthenticated
`/admin/governed-allegations` returned HTTP 401; plausible public Stage 64
paths returned HTTP 404. No production allegation, review, supersession, or
withdrawal was created.

## Governance boundary

**ATTRIBUTION IS NOT CONFIRMATION**

The record may establish that something was said. It does not thereby establish
that what was said is true.

Stage 64 preserves a human-recorded, administrator-only proposition attributed
to an identified person, organisation, institution, document, communication, or
other governed source. An allegation is not evidence, an observation, an
inference, a finding, or a determination. Recording and reviewing an allegation
confirm attribution and faithful representation only; they do not confirm
truth, proof, corroboration, intent, motive, causation, wrongdoing, legal
significance, or established fact.

The initial categories are `reported_conduct`, `reported_omission`,
`reported_statement`, `reported_condition`, and `reported_responsibility`.
Representation is explicitly labelled `verbatim` or `faithful_paraphrase`.
Each creation requires a structured allegation qualification, explicit
limitations, source attribution, and a server-recorded human-author boundary
declaration.

## Sources and lifecycle

Every allegation has at least one `attribution_source` binding to a permitted
Published Document, Canonical Record, Record–Document Association, or accepted
Stage 62 observation. Contextual, response, contrary, and withdrawal sources
are separately labelled. Inference-to-allegation and allegation-to-allegation
bindings are rejected. Repetition is not represented as corroboration, and a
response or contrary source does not automatically resolve the allegation.

The lifecycle preserves `recorded`, `accepted_as_attributed_allegation`,
`requires_attribution_correction`, `not_accepted_as_attributed`, `superseded`,
and `withdrawn`. Reviews, supersessions, and withdrawals are append-only and
independently idempotent. Self-review is visible. Later correction, withdrawal,
or supersession never erases the original allegation, source bindings, or
history. Withdrawals explicitly distinguish `attributed_source_withdrawal`
from `administrative_attribution_correction` and require a governed withdrawal
source.

## Administrative boundary

Stage 64 provides authenticated administrative listing, inspection, creation,
review, supersession, and withdrawal surfaces only. GET inspection is
read-only and does not initialize Stage 64 persistence. There is no public
route, serializer, navigation, search exposure, export, feed, publication
eligibility, automated extraction, LLM generation, matching, truth scoring,
credibility scoring, or production allegation creation.

Stages 60–63 remain unchanged, including Stage 62's **No inference recorded**
boundary and Stage 63's separate governed-inference semantics.
