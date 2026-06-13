# Stage 14A — Archive Classification

Status: Implemented / pending review

## Purpose

Stage 14A begins the Archive layer by adding deterministic archive classification to the read-only Admin Record Evidence view.

It answers:

Can a completed matter be classified for long-term archival preservation?

## Route Updated

GET /admin/records/{reference}/evidence

## Relationship To Stage 13F

Stage 13F classifies whether the closure process has reached completion. Stage 14A uses closure completion with closure, resolution, outcome, administrative status, implementation action, and effective state values to classify whether the matter is not archivable, archive eligible, or archived.

## Deterministic Inputs

Archive classification is derived only from:

- closure classification
- closure completion
- closure determination
- closure readiness
- resolution classification
- resolution completion
- resolution determination
- outcome readiness
- review eligibility
- administrative status
- implementation action
- effective state

## Archive Classification Mapping

| Closure / administrative state | Archive classification |
| --- | --- |
| Closure classification is Open or closure completion is Not Complete | Not Archivable |
| Closure completion is Complete and closure has been achieved | Archive Eligible |
| Administrative status or effective state indicates archive completed | Archived |

## Render Position

Stage 14A renders immediately after Stage 13F — Closure Completion and immediately before Supporting Evidence.

The visible administrative sequence is:

1. Stage 12A — Resolution Classification
2. Stage 12B — Resolution Preconditions
3. Stage 12C — Resolution Pathway
4. Stage 12D — Resolution Readiness
5. Stage 12E — Resolution Determination
6. Stage 12F — Resolution Completion
7. Stage 13A — Closure Classification
8. Stage 13B — Closure Preconditions
9. Stage 13C — Closure Pathway
10. Stage 13D — Closure Readiness
11. Stage 13E — Closure Determination
12. Stage 13F — Closure Completion
13. Stage 14A — Archive Classification
14. Supporting Evidence

## Non-Goals

Stage 14A introduces no workflow mutation, implementation mutation, outcome mutation, resolution mutation, closure mutation, archive mutation, schema changes, manifest changes, canonical verification changes, upload/download changes, or public route changes.

No mutation, schema, manifest, or canonical verification changes are introduced.
