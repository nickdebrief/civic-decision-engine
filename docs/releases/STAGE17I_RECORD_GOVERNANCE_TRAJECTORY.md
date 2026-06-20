# Stage 17I - Record Governance Trajectory

## Purpose

Stage 17I adds a read-only Record Governance Trajectory section to the Admin Record Evidence view. It extends Stage 17H Record Governance Change Log by showing the current visible direction of governance based only on the existing governance chain.

The section answers:

- Is governance progressing?
- Is governance persistent?
- Is governance regressing?
- Which governance outputs determine the current trajectory?
- What trajectory state is visible from the current governance chain?

## Governance Trajectory Model

The trajectory layer is derived only from existing governance outputs:

- Stage 17A Record Dependency
- Stage 17B Record Impact
- Stage 17C Record Stability
- Stage 17D Record Reproducibility
- Stage 17E Record Integrity
- Stage 17F Record Governance Summary
- Stage 17G Record Governance Continuity
- Stage 17H Record Governance Change Log

The summary renders:

- Total Trajectory Layers
- Progression Layers
- Persistent Layers
- Regression Layers
- Current Governance Classification
- Current Continuity Classification
- Current Change State
- Governance Trajectory

Each governance layer also receives a deterministic trajectory review, and the record-level trajectory table repeats the currently recorded governance classifications for audit visibility.

## Classification Rules

Allowed governance trajectory classifications are:

- Governance Progression
- Governance Persistence
- Governance Regression

Governance Regression applies when any of the following are present:

- Governance Gap
- Governance Discontinuity
- Significant Change
- Compromised Integrity
- Non-Reproducible
- Unstable

Governance Progression applies when all of the following are present:

- Governance Classification is Governed
- Continuity Classification is Continuous Governance
- Governance Change State is No Recorded Change or Limited Change
- No Governance Gap, Governance Discontinuity, Significant Change, Compromised Integrity, Non-Reproducible, or Unstable state exists

Governance Persistence applies only when Governance Regression does not apply and Governance Progression does not apply. Persistence includes partially governed, partial continuity, limited change, limited stability, limited reproducibility, limited integrity, limited confidence, and partial sufficiency states.

## Evaluation Order

Governance Trajectory is evaluated deterministically in this order:

1. Governance Regression
2. Governance Progression
3. Governance Persistence

If Governance Regression criteria are satisfied, Governance Regression is rendered regardless of any persistence or progression state.

## Deterministic Constraints

Stage 17I does not infer, estimate, predict, forecast, score, rank, repair, create evidence, create relationships, alter classifications, or mutate records. It displays existing governance outputs and simple deterministic trajectory states derived from those outputs.

## Admin-Only Visibility

Record Governance Trajectory is rendered only in the admin record evidence route:

`GET /admin/records/{reference}/evidence`

No public route is added.

## Non-Mutating Behavior

Stage 17I introduces no mutation behavior. It does not change records, attachments, relationships, schemas, public routes, upload or download behavior, canonical verification hashes, databases, or prior Stage 15D through Stage 17H logic.

## No Prediction Or Forecasting

The word trajectory describes the current visible governance direction implied by already recorded classifications. It is not a forecast, probability, risk score, simulation, or prediction of future governance state.
