# Stage 12A — Resolution Classification

Status: Implemented / pending review

## Purpose

Stage 12A begins the Resolution layer after completion of the Stage 11 Outcome
layer. It extends the read-only Admin Record Evidence view with deterministic
resolution classification.

Stage 12A answers:

Has the matter reached a resolution state?

## Route Updated

`GET /admin/records/{reference}/evidence`

## Relationship To Stage 11F

Stage 11F identifies the next target outcome if the outcome advances. Stage 12A
uses the current outcome, outcome readiness, outcome target, effective state,
implementation action, and administrative status to classify whether the matter
has reached a resolution state.

## Resolution Mapping

| Outcome | Additional state | Resolution classification |
| --- | --- | --- |
| Ongoing Review | Not Ready / Review Awaiting Determination | Unresolved |
| Review Awaiting Determination | Conditionally Ready / Ready For Determination | Unresolved |
| Ready For Determination | Ready / Determination Pending | Partially Resolved |
| Determination Issued | Implementation Required | Conditionally Resolved |
| Corrective Action Implemented | Corrective Action Effective | Resolved |
| Corrective Action Reversed | Any state | Resolution Failed |
| Implementation Failed | Any state | Resolution Failed |

## Descriptions

| Resolution classification | Description |
| --- | --- |
| Unresolved | The matter remains unresolved because the current outcome has not reached an implemented administrative determination state. |
| Partially Resolved | The matter has advanced toward resolution but administrative determination or implementation remains incomplete. |
| Conditionally Resolved | The matter has reached a conditional resolution state, but implementation or confirmation requirements remain outstanding. |
| Resolved | The matter has reached a resolved state because the required administrative action has been implemented and is effective. |
| Resolution Failed | The matter has not resolved because the required corrective or administrative action failed, reversed, or did not take effect. |

## Deterministic Derivation Rules

Resolution classification is derived deterministically from:

- outcome
- outcome readiness
- outcome target
- effective state
- implementation action
- administrative status

No AI-generated assessment, subjective scoring, operator input, workflow
mutation, implementation mutation, outcome mutation, or resolution mutation is
used.

## Preservation Of Read-Only Behavior

Stage 12A adds display-only administrative classification. It does not add:

- mutation controls
- workflow mutation
- implementation mutation
- outcome mutation
- resolution mutation
- upload capability
- download capability
- file access
- public route changes

## Verification Boundaries

Stage 12A introduces no schema changes, manifest changes, record versioning
changes, canonical verification changes, upload/download behavior changes, or
public route changes.

## Test Result

Commands:

```bash
python3 -m unittest tests.test_admin_session
python3 -m unittest discover -s tests
```

Result: PASS.
