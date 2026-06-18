# Stage 17B — Record Impact

## Purpose

Stage 17B adds a deterministic Record Impact layer to the Admin Record Evidence
view. It shows how existing record outputs are affected by the current state of
their dependent conditions, signals, findings, and evidence-supported targets.

This is an admin-only, read-only, visibility-only assessment.

## Route Updated

`GET /admin/records/{reference}/evidence`

## Deterministic Derivation Rules

Record Impact is derived only from existing values already visible in the Admin
Record Evidence view:

- existing conditions
- existing signals
- existing findings
- existing record outputs
- existing active support counts
- existing sufficiency states
- existing completeness states
- existing confidence states
- existing Stage 17A dependency mappings

No predictions, risk scores, probabilities, AI reasoning, weighting, ranking, or
new evidence scoring models are introduced.

## Impact Summary

The Record Impact section renders:

- Total Impacted Outputs
- Total Conditions Affecting Outputs
- Total Signals Affecting Outputs
- Total Findings Affecting Outputs
- Evidence-Supported Impacts
- Unsupported Impacts

Impact classification is deterministic:

- `Evidence-Supported Impact` when the dependency has `Sufficient` or `Strong`
  sufficiency.
- `Unsupported Impact` when the dependency has `Unsupported` or `Partial`
  sufficiency.

## Condition Impact

Each condition impact row displays:

- Active Supports
- Sufficiency
- Completeness
- Confidence
- Impact Classification
- Impacted Outputs

## Signal Impact

Each signal impact row displays the same deterministic state fields as condition
impact rows and lists the record outputs affected by that signal.

## Finding Impact

Each finding impact row displays the same deterministic state fields and lists
the record outputs affected by that finding.

## Record Impact

The record-level impact table displays:

- Record Reference
- Trajectory
- Finding
- Impacting Conditions
- Impacting Signals
- Impacting Findings
- Evidence-Supported Dependencies
- Unsupported Dependencies

## Safety Guarantees

Stage 17B does not modify:

- Stage 11-15 deterministic progression logic
- Stage 16A Evidence Standards
- Stage 16B Evidence Justification
- Stage 16C Evidence Confidence
- Stage 16D Evidence Traceability
- Stage 16E Evidence Lineage
- Stage 16F Evidence Provenance
- Stage 17A Record Dependency
- canonical verification hashes
- public routes
- upload/download behavior
- database schema
- `ADMIN_TEMP_UPLOAD_ENABLED` default behavior
