# Stage 16C — Evidence Confidence

## Purpose

Stage 16C adds an Evidence Confidence layer to the read-only Admin Record
Evidence view. It exposes deterministic evidence confidence derived only from
existing sufficiency and completeness outputs.

This is not statistical confidence, AI confidence, probability, weighting, or a
new scoring model.

## Route Updated

- `GET /admin/records/{reference}/evidence`

## Deterministic Confidence Model

Evidence confidence is derived from the Stage 15D sufficiency value and the
Stage 15E completeness value.

| Sufficiency | Base confidence |
| --- | --- |
| Unsupported | Low Confidence |
| Partial | Limited Confidence |
| Sufficient | High Confidence |
| Strong | Very High Confidence |

## Completeness Modifier

If a target or summary is incomplete, confidence cannot exceed Limited
Confidence.

| Sufficiency | Completeness | Confidence |
| --- | --- | --- |
| Unsupported | Incomplete | Low Confidence |
| Partial | Incomplete | Limited Confidence |
| Sufficient | Incomplete | Limited Confidence |
| Strong | Incomplete | Limited Confidence |
| Sufficient | Complete | High Confidence |
| Strong | Complete | Very High Confidence |

## Relationship to Evidence Standards

Stage 16A defines the current deterministic standard used by Stage 15D through
Stage 15F. Stage 16C does not change that standard. It only applies the existing
sufficiency and completeness outputs to classify confidence.

## Relationship to Evidence Justification

Stage 16B explains why each target received its sufficiency, completeness, and
requirement values. Stage 16C adds the derived confidence value and a
deterministic reason for that confidence.

## Admin-Only Scope

Stage 16C is an administrative evidence assessment layer only. It does not add
public evidence pages, public file access, public download routes, upload
functionality, or attachment mutation.

## Canonical Verification

Stage 16C does not change canonical verification hashes, public manifests,
record versioning, schemas, or deterministic administrative progression logic.
