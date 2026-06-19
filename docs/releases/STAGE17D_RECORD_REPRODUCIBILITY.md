# Stage 17D — Record Reproducibility

## Purpose

Stage 17D adds a deterministic Record Reproducibility layer to the Admin Record
Evidence view. It describes whether current record outputs are reproducible from
the currently recorded structure, evidence relationships, evidence governance
outputs, and record governance outputs.

This stage is admin-only, read-only, deterministic, and visibility-only.

## Relationship to Stage 17A Record Dependency

Stage 17A identifies the visible dependencies between record components and
record outputs. Stage 17D uses those existing dependency outputs as the affected
outputs shown for reproducibility.

Stage 17D does not create new dependencies and does not alter Stage 17A
dependency behavior.

## Relationship to Stage 17B Record Impact

Stage 17B identifies current impact visibility from existing dependencies and
evidence target states. Stage 17D uses the same existing target state values and
affected outputs, but it does not change impact counts or impact
classifications.

## Relationship to Stage 17C Record Stability

Stage 17C classifies current output stability from existing sufficiency,
completeness, confidence, dependency, impact, and support states. Stage 17D uses
those stability classifications as part of its deterministic reproducibility
classification.

Stage 17D does not change stability classification or Stage 17C rendering.

## Reproducibility Summary

The Record Reproducibility section renders:

- Total Reproducibility Targets
- Reproducible Targets
- Limited Reproducibility Targets
- Non-Reproducible Targets
- Evidence-Supported Targets
- Unsupported Targets

These are deterministic counts only. They are not scores, probabilities,
confidence percentages, or risk indicators.

## Condition Reproducibility

Each condition target displays:

- Condition
- Active Supports
- Sufficiency
- Completeness
- Confidence
- Stability
- Reproducibility Classification
- Affected Outputs

Affected outputs are taken from existing dependency and impact outputs only.

## Signal Reproducibility

Each signal target displays the same deterministic state fields as condition
targets. No signal is reanalyzed or regenerated.

## Finding Reproducibility

Each finding target displays the same deterministic state fields as condition
and signal targets. The section reflects the currently recorded finding
dependency state only.

## Record Reproducibility

The record-level reproducibility table displays:

- Record Reference
- Trajectory
- Finding
- Supporting Conditions
- Supporting Signals
- Supporting Findings
- Record Confidence
- Record Stability
- Record Reproducibility Classification

Record-level reproducibility is derived from existing record sufficiency,
completeness, confidence, and stability values.

## Classification Rules

Reproducibility is classified deterministically:

- `Reproducible`: support is `Sufficient` or `Strong`, completeness is
  `Complete`, confidence is not `Low Confidence`, and stability is `Stable`.
- `Limited Reproducibility`: support is `Partial`, confidence is
  `Limited Confidence`, and stability is `Limited Stability`.
- `Non-Reproducible`: the target remains unsupported, incomplete, low
  confidence, unstable, or otherwise outside the reproducible and limited
  reproducibility rules.

No weighting, scoring, percentages, probabilities, forecasts, simulations, or
AI reasoning are used.

## Deterministic Visibility-Only Behavior

Record Reproducibility answers:

> Can this output be reproduced from the currently recorded structure?

It displays only the present state implied by existing record structure,
evidence relationships, governance outputs, dependency outputs, impact outputs,
stability outputs, and active support counts.

Stage 17D does not:

- regenerate records
- replay records
- infer outcomes
- estimate outcomes
- predict outcomes
- simulate changes
- score reproducibility
- use AI reasoning
- mutate records
- modify evidence

## Admin-Only Scope

The Record Reproducibility section is rendered only in the admin Record Evidence
view:

`GET /admin/records/{reference}/evidence`

No public route is added.

## Non-Changes

Stage 17D introduces no:

- schema changes
- public route changes
- canonical hash mutation
- upload/download behavior changes
- workflow mutation
- evidence mutation
- record mutation
- canonical verification changes

## Example: Strike-LA-20260710-004

For `Strike-LA-20260710-004`, the existing evidence state includes one active
support for the condition target `Escalation Without Response`.

That produces:

- condition sufficiency: `Partial`
- condition confidence: `Limited Confidence`
- condition stability: `Limited Stability`
- condition reproducibility: `Limited Reproducibility`

Targets without active support remain:

- sufficiency: `Unsupported`
- confidence: `Low Confidence`
- stability: `Unstable`
- reproducibility: `Non-Reproducible`

The record-level reproducibility remains `Non-Reproducible` while the record
target itself has incomplete support, low confidence, and unstable record
stability.
