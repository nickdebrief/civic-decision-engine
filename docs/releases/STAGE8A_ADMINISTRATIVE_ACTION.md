# Stage 8A — Administrative Action

Status:
Implemented / pending review

## Purpose

Stage 8A extends the read-only Admin Record Evidence view from deterministic
evidence readiness to deterministic administrative next-action classification.

It answers:

Given the readiness state, what administrative action should occur next?

## Route Updated

`GET /admin/records/{reference}/evidence`

## Relationship To Stage 7G

Stage 8A uses the existing Stage 7G readiness classification as its only
decision input. It does not introduce a separate evidence model, scoring system,
confidence measure, or workflow state.

## Deterministic Action Table

| Stage 7G readiness | Administrative action |
| --- | --- |
| Unsupported | Collect Initial Evidence |
| Evidence Gaps Present | Resolve Evidence Gaps |
| Partially Ready | Proceed to Administrative Review |
| Ready | Eligible for Formal Review |

## Action Basis

The Admin Record Evidence view displays a deterministic rationale for the
selected action:

- Unsupported records require initial evidence collection.
- Records with unsupported targets or evidence gaps require gap resolution.
- Partially ready records may proceed to administrative review.
- Ready records are eligible for formal review.

No AI-generated rationale, subjective assessment, confidence percentage, or
workflow mutation is used.

## Preservation

Stage 8A does not change:

- canonical verification logic
- canonical serialization
- record versioning
- relationship storage schema
- public manifests
- public evidence exposure
- attachment file access
- upload or download behavior
- relationship editing
- record mutation
- workflow mutation

## Validation

Commands:

```bash
python3 -m unittest tests.test_admin_session
python3 -m unittest discover -s tests
```

Result:

PASS
