# Stage 17C — Record Stability

## Purpose

Stage 17C adds a deterministic Record Stability layer to the Admin Record
Evidence view. It describes how stable the record's current outputs are when
the existing supporting state remains unchanged.

This stage is admin-only, read-only, deterministic, and visibility-only.

## Relationship to Stage 17A Record Dependency

Stage 17A identifies which record outputs depend on existing record components
and evidence-supported targets. Stage 17C uses those existing dependency outputs
as the affected-output context for stability display.

Stage 17C does not create new dependency mappings and does not alter Stage 17A
dependency behavior.

## Relationship to Stage 17B Record Impact

Stage 17B exposes deterministic impact visibility from existing dependencies,
record outputs, sufficiency, completeness, confidence, and support states. Stage
17C uses those existing impact outputs and target states to classify present
stability.

Stage 17C does not change impact counts, impact classifications, or Stage 17B
rendering.

## Stability Summary

The Record Stability section renders a deterministic summary of current target
stability:

- Total Stability Targets
- Stable Targets
- Limited Stability Targets
- Unstable Targets
- Evidence-Supported Stability Targets
- Unsupported Stability Targets

These values are counts only. They are not scores, percentages, probabilities,
or risk indicators.

## Condition Stability

Each condition target displays:

- Condition
- Active Supports
- Sufficiency
- Completeness
- Confidence
- Stability Classification
- Affected Outputs

Affected outputs are taken from existing dependency and impact outputs only.

## Signal Stability

Each signal target displays:

- Signal
- Active Supports
- Sufficiency
- Completeness
- Confidence
- Stability Classification
- Affected Outputs

No new signal analysis is performed.

## Finding Stability

Each finding target displays:

- Finding
- Active Supports
- Sufficiency
- Completeness
- Confidence
- Stability Classification
- Affected Outputs

The section reflects the current visible finding dependency state only.

## Record Stability

The record-level stability table displays:

- Record Reference
- Trajectory
- Finding
- Supporting Conditions
- Supporting Signals
- Supporting Findings
- Record Confidence
- Record Stability Classification

Record-level stability is derived from existing record confidence and
completeness values. It does not change record trajectory, finding, or evidence
relationships.

## Stability Classification Rules

Stability is classified deterministically from existing confidence and
completeness values only:

- `Stable`: confidence is `High Confidence` or `Very High Confidence` and
  completeness is `Complete`.
- `Limited Stability`: confidence is `Limited Confidence`.
- `Unstable`: confidence is `Low Confidence`.

No weighting, scoring, percentages, probabilities, forecasts, or simulations are
used.

## Stability Definitions

### Stable

The target has complete evidence support and high or very high deterministic
evidence confidence.

### Limited Stability

The target has limited deterministic evidence confidence. This usually reflects
partial support or incomplete completion state.

### Unstable

The target has low deterministic evidence confidence. This reflects the current
visible state only and is not a prediction of future change.

## Deterministic Visibility-Only Behavior

Record Stability answers:

> How stable are the current outputs if the existing supporting state remains
> unchanged?

It displays only the present state implied by existing record structure,
dependency outputs, impact outputs, sufficiency, completeness, confidence, and
support values.

Stage 17C does not:

- predict future outcomes
- estimate risk
- calculate probability
- simulate changes
- use AI reasoning
- mutate records
- alter evidence relationships
- change record outputs

## Admin-Only Scope

The Record Stability section is rendered only in the admin Record Evidence view:

`GET /admin/records/{reference}/evidence`

No public route is added.

## Non-Changes

Stage 17C introduces no:

- schema changes
- public route changes
- canonical hash mutation
- upload/download behavior changes
- workflow mutation
- implementation mutation
- evidence mutation
- record state mutation

## Example: Strike-LA-20260710-004

For `Strike-LA-20260710-004`, the existing evidence state includes one active
support for the condition target `Escalation Without Response`.

That produces:

- condition confidence: `Limited Confidence`
- condition completeness: `Incomplete`
- condition stability: `Limited Stability`

Targets without active support remain:

- confidence: `Low Confidence`
- completeness: `Incomplete`
- stability: `Unstable`

The record-level stability remains `Unstable` while the record target itself has
low confidence and incomplete support.
