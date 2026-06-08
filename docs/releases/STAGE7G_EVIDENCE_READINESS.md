# Stage 7G — Evidence Readiness

Status:
Implemented / pending review

## Purpose

Stage 7G extends the read-only Admin Record Evidence view from per-target
evidence sufficiency to deterministic record-level evidence readiness.

It answers:

Can this record proceed without additional evidence work?

## Route Updated

`GET /admin/records/{reference}/evidence`

## Deterministic Readiness Classification

Readiness is classified only from existing Stage 7 derived values:

- supported target count
- unsupported target count
- evidence gap count
- coverage percentage
- Stage 7F sufficiency classifications

No AI-generated assessment, subjective scoring, confidence percentage, graph
analysis, or evidence weighting is used.

| Classification | Deterministic rule |
| --- | --- |
| Unsupported | No targets are supported and all targets are classified as Unsupported. |
| Evidence Gaps Present | One or more evidence gaps or unsupported targets remain. |
| Partially Ready | All targets have support, but support is only Minimal. |
| Ready | No evidence gaps remain and at least one target is Corroborated or Reinforced. |

The precedence order is:

1. Unsupported
2. Evidence Gaps Present
3. Ready
4. Partially Ready

## Admin Display

The Admin Record Evidence page now includes:

- readiness classification
- supported targets
- unsupported targets
- evidence gap count
- coverage percentage
- sufficiency basis summary

The display is read-only and uses only existing Stage 7 coverage, gap, and
sufficiency values.

## Preservation

Stage 7G does not change:

- canonical verification logic
- canonical serialization
- record versioning
- relationship storage schema
- public manifests
- public evidence exposure
- attachment file access
- upload or download behavior
- mutation controls

## Validation

Commands:

```bash
python3 -m unittest tests.test_admin_session
python3 -m unittest discover -s tests
```

Result:

PASS
