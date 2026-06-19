# Stage 17F - Record Governance Summary

## Purpose

Stage 17F adds a read-only Record Governance Summary section to the Admin Record Evidence view. It consolidates the existing record governance outputs from Stage 17A through Stage 17E into a single deterministic snapshot of the current record governance state.

The section answers:

- What governance layers exist?
- Which governance layers are supported or unsupported?
- What classification applies to dependency, impact, stability, reproducibility, and integrity?
- What is the current consolidated governance classification?

## Governance Model

The summary is derived only from existing governance outputs:

- Stage 17A Record Dependency
- Stage 17B Record Impact
- Stage 17C Record Stability
- Stage 17D Record Reproducibility
- Stage 17E Record Integrity

The section renders:

- Total Governance Layers
- Supported Governance Layers
- Unsupported Governance Layers
- Dependency Classification
- Impact Classification
- Stability Classification
- Reproducibility Classification
- Integrity Classification
- Governance Classification

It also includes deterministic review tables for dependency, impact, stability, reproducibility, and integrity, plus a record-level governance summary for the current record reference, trajectory, and finding.

## Classification Rules

Allowed governance classifications are:

- Governed
- Partially Governed
- Governance Gap

Governance Gap applies when any of the following are present:

- Unsupported dependency
- Unsupported impact
- Unstable stability classification
- Non-Reproducible reproducibility classification
- Compromised Integrity classification

Governed applies when all governance layers are supported:

- Dependency is Supported
- Impact is Evidence-Supported Impact
- Stability is Stable
- Reproducibility is Reproducible
- Integrity is High Integrity

Partially Governed applies only when Governance Gap does not apply and the record is not fully Governed.

## Evaluation Order

Governance classification is evaluated deterministically in this order:

1. Governance Gap
2. Governed
3. Partially Governed

If Governance Gap criteria are satisfied, Governance Gap is rendered regardless of any other governance state.

## Deterministic Constraints

Stage 17F does not infer, estimate, predict, score, rank, repair, create evidence, create relationships, or alter classifications. It displays only the current outputs produced by the existing governance layers and simple deterministic counts derived from those outputs.

## Admin-Only Visibility

The Record Governance Summary is rendered only in the admin record evidence route:

`GET /admin/records/{reference}/evidence`

No public route is added.

## Non-Mutating Behavior

Stage 17F introduces no mutation behavior. It does not change records, attachments, relationships, schemas, public routes, upload or download behavior, canonical verification hashes, or prior Stage 15D through Stage 17E logic.
