# Stage 9C — Review Eligibility

Status:
Implemented / pending review

## Purpose

Stage 9C extends the read-only Admin Record Evidence view with deterministic
review eligibility classification.

Stage 9B explains why the current administrative disposition applies. Stage 9C
classifies whether the record is currently eligible for review.

## Route Updated

`GET /admin/records/{reference}/evidence`

## Eligibility Mapping

Review eligibility is derived deterministically from administrative disposition
values only.

| Administrative Disposition | Review Eligibility |
| --- | --- |
| Open | Not Eligible |
| Pending Review | Conditionally Eligible |
| Ready for Review | Eligible |

## Eligibility Descriptions

| Review Eligibility | Description |
| --- | --- |
| Not Eligible | The record has not yet satisfied review requirements. |
| Conditionally Eligible | The record may proceed to review subject to administrative assessment. |
| Eligible | The record satisfies current requirements for review. |

## Scope

- Read-only administrative display.
- Deterministic review eligibility helper functions.
- Eligibility badge rendering in the Admin Record Evidence view.
- No upload or download capability.
- No file access.
- No workflow mutation.
- No record mutation.
- No relationship editing.
- No schema changes.
- No public manifest changes.
- No canonical verification changes.

## Validation

Commands:

```bash
python3 -m unittest tests.test_admin_session
python3 -m unittest discover -s tests
```

Result:
PASS
