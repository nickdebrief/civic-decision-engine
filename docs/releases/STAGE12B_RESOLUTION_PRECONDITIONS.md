# Stage 12B — Resolution Preconditions

Status: Implemented / pending review

## Purpose

Stage 12B extends the read-only Admin Record Evidence view from resolution
classification to deterministic resolution precondition identification.

Stage 12A answers:

Has the matter reached a resolution state?

Stage 12B answers:

What must be satisfied before resolution can occur?

## Route Updated

`GET /admin/records/{reference}/evidence`

## Relationship To Stage 12A

Stage 12A classifies the current resolution state. Stage 12B uses that
resolution classification with the outcome, outcome readiness, outcome target,
effective state, implementation action, administrative status, and review
eligibility values to identify deterministic preconditions before resolution
can occur.

## Deterministic Derivation Rules

Resolution preconditions are derived deterministically from:

- resolution classification
- outcome
- outcome readiness
- outcome target
- effective state
- implementation action
- administrative status
- review eligibility

No AI-generated assessment, subjective scoring, operator input, workflow
mutation, implementation mutation, outcome mutation, or resolution mutation is
used.

## Current Unresolved-State Path

For the current unresolved evidence-review state, Stage 12B renders:

Precondition target:

`Conditionally Resolved`

Resolution preconditions:

1. Review eligibility requirements must be satisfied.
2. Administrative disposition must advance beyond Open.
3. Outcome readiness must advance beyond Not Ready.
4. Implementation action must advance beyond No Implementation Action.
5. Effective state must advance beyond Evidence Review Continues.

## Resolution State Paths

| Resolution classification | Precondition target | Precondition path |
| --- | --- | --- |
| Unresolved | Conditionally Resolved | Review eligibility, administrative progression, outcome readiness, implementation action, and effective state must advance. |
| Partially Resolved | Conditionally Resolved | Administrative determination and implementation requirements must be completed or identified. |
| Conditionally Resolved | Resolved | Implementation requirements and resolution effectiveness must be confirmed. |
| Resolved | No further resolution state identified | No additional resolution preconditions are identified. |
| Resolution Failed | Resolution Recovery | Failed or reversed action must be corrected and resolution state re-established. |

## Preservation Of Read-Only Behavior

Stage 12B adds display-only administrative preconditions. It does not add:

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

Stage 12B introduces no schema changes, manifest changes, record versioning
changes, canonical verification changes, upload/download behavior changes, or
public route changes.

## Test Result

Commands:

```bash
python3 -m unittest tests.test_admin_session
python3 -m unittest discover -s tests
```

Result: PASS.
