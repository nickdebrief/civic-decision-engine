# Stage 17E — Record Integrity

## Purpose

Stage 17E adds a deterministic Record Integrity layer to the Admin Record
Evidence view. It describes the structural integrity of a record using existing
governance outputs, evidence relationships, dependency outputs, impact outputs,
stability outputs, reproducibility outputs, and record structure.

This stage is admin-only, read-only, deterministic, and visibility-only.

## Integrity Model

Record Integrity answers:

- Does the record remain internally consistent?
- Are dependencies present?
- Are impacted outputs still visible?
- Are stability outputs available?
- Are reproducibility outputs available?
- Does the record contain broken governance relationships?

The integrity model inspects only existing stored values and rendered governance
outputs. It does not repair, infer, regenerate, or mutate any record or
relationship.

## Classification Rules

Integrity is classified deterministically for each condition, signal, finding,
and record-level target.

### High Integrity

Rendered when:

- Active supports are greater than zero.
- Sufficiency is not `Unsupported`.
- Completeness is not `Incomplete`.
- Confidence is not `Low Confidence`.
- Stability is not `Unstable`.
- Reproducibility is not `Non-Reproducible`.

### Limited Integrity

Rendered when supporting governance exists and active supports are greater than
zero, but one or more of the current states remains limited:

- `Partial`
- `Incomplete`
- `Limited Confidence`
- `Limited Stability`
- `Limited Reproducibility`

### Compromised Integrity

Rendered when any structural support condition is broken or unavailable:

- Active supports equal zero.
- Sufficiency is `Unsupported`.
- Confidence is `Low Confidence`.
- Stability is `Unstable`.
- Reproducibility is `Non-Reproducible`.

## Integrity Summary

The Record Integrity section renders:

- Total Integrity Targets
- High Integrity Targets
- Limited Integrity Targets
- Compromised Integrity Targets
- Evidence-Supported Integrity Targets
- Unsupported Integrity Targets

These values are deterministic counts only. They are not scores,
probabilities, risk indicators, or confidence percentages.

## Condition Integrity

Each condition target displays:

- Condition
- Active Supports
- Sufficiency
- Completeness
- Confidence
- Stability
- Reproducibility
- Integrity Classification
- Affected Outputs

Affected outputs are taken from existing dependency and impact outputs only.

## Signal Integrity

Each signal target displays the same deterministic state fields as condition
targets. No signal is reanalyzed, inferred, repaired, or regenerated.

## Finding Integrity

Each finding target displays the same deterministic state fields as condition
and signal targets. The section reflects the current visible finding dependency
state only.

## Record Integrity

The record-level integrity table displays:

- Record Reference
- Trajectory
- Finding
- Supporting Conditions
- Supporting Signals
- Supporting Findings
- Record Confidence
- Record Stability
- Record Reproducibility
- Record Integrity Classification

Record-level integrity is derived from existing record support, sufficiency,
completeness, confidence, stability, and reproducibility values.

## Deterministic Constraints

Stage 17E derives only from:

- existing evidence support counts
- existing dependency outputs
- existing impact outputs
- existing stability outputs
- existing reproducibility outputs
- existing record structure

Stage 17E does not:

- infer
- estimate
- predict
- score
- use AI reasoning
- modify records
- create relationships
- repair relationships
- mutate evidence

## Admin-Only Visibility

The Record Integrity section is rendered only in the admin Record Evidence view:

`GET /admin/records/{reference}/evidence`

No public route is added.

## Non-Mutating Behavior

Stage 17E introduces no:

- schema changes
- public route changes
- canonical hash mutation
- upload/download behavior changes
- database changes
- workflow mutation
- evidence mutation
- record mutation

## Example: Strike-LA-20260710-004

For `Strike-LA-20260710-004`, the existing evidence state includes one active
support for the condition target `Escalation Without Response`.

That produces:

- condition sufficiency: `Partial`
- condition completeness: `Incomplete`
- condition confidence: `Limited Confidence`
- condition stability: `Limited Stability`
- condition reproducibility: `Limited Reproducibility`
- condition integrity: `Limited Integrity`

Targets without active support remain:

- sufficiency: `Unsupported`
- confidence: `Low Confidence`
- stability: `Unstable`
- reproducibility: `Non-Reproducible`
- integrity: `Compromised Integrity`

The record-level integrity remains `Compromised Integrity` while the record
target itself has incomplete support, low confidence, unstable record stability,
and non-reproducible record state.
