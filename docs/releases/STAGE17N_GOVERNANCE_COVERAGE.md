# Stage 17N - Governance Coverage

## Purpose

Stage 17N adds a read-only Governance Coverage layer to the Admin Record
Evidence view. It shows which governance layers are present, populated,
missing, or unsupported across the existing governance chain.

Coverage answers whether each governance output exists and contributes to the
current governance chain. It measures presence and population, not the quality
of the governance state.

## Coverage Model

Governance Coverage is derived from existing Stage 17 governance outputs:

- Governance Summary
- Governance Continuity
- Governance Change Log
- Governance Trajectory
- Governance Pattern Detection
- Governance Consistency
- Governance Relationships
- Governance Traceability

The section renders:

- Coverage Summary
- Governance Coverage Review
- Continuity Coverage Review
- Change Coverage Review
- Trajectory Coverage Review
- Pattern Coverage Review
- Consistency Coverage Review
- Relationships Coverage Review
- Traceability Coverage Review
- Record Governance Coverage

## Coverage-Source Model

Stage 17N uses deterministic coverage source labels:

| Governance output | Coverage source |
| --- | --- |
| Governance Classification | Governance Summary |
| Continuity Classification | Governance Continuity |
| Governance Change State | Governance Change Log |
| Governance Trajectory | Governance Trajectory |
| Governance Pattern Classification | Governance Pattern Detection |
| Consistency Classification | Governance Consistency |
| Relationship Classification | Governance Relationships |
| Traceability Classification | Governance Traceability |

These labels expose existing governance outputs only. They do not generate new
governance relationships or alter any existing classification.

## Coverage State Rules

Coverage states are deterministic:

- Present: the governance output exists.
- Missing: the governance output is not available.
- Unsupported: the governance output exists but has a degraded or unsupported
  classification.

Unsupported states still count as present for coverage purposes. Coverage
therefore distinguishes availability from governance quality.

Unsupported classifications include:

- Governance Gap
- Governance Discontinuity
- Significant Change
- Governance Regression
- Recurring Governance Pattern
- Governance Inconsistency
- Governance Relationship Conflict
- Untraceable Governance

## Classification Rules

Allowed coverage classifications are:

- Full Governance Coverage
- Partial Governance Coverage
- Limited Governance Coverage
- No Governance Coverage

Full Governance Coverage is rendered when every required governance output is
present and no governance layer is missing.

Partial Governance Coverage is rendered when at least one governance layer
exists and one or more required governance outputs are missing.

Limited Governance Coverage is reserved for cases where governance outputs are
present but degraded or unsupported, and no missing layer forces partial
coverage.

No Governance Coverage is rendered when no governance outputs exist.

## Classification Evaluation Order

Governance Coverage is evaluated in this order:

1. No Governance Coverage
2. Partial Governance Coverage
3. Full Governance Coverage
4. Limited Governance Coverage

If both full and limited coverage appear possible, Full Governance Coverage is
rendered because coverage measures whether governance outputs are present, not
whether those outputs are favorable.

## Deterministic Constraints

Stage 17N derives only from:

- Governance Summary outputs
- Governance Continuity outputs
- Governance Change Log outputs
- Governance Trajectory outputs
- Governance Pattern Detection outputs
- Governance Consistency outputs
- Governance Relationships outputs
- Governance Traceability outputs
- existing classifications
- existing record structure

It performs no scoring, probability, prediction, forecasting, simulation, or
AI-generated assessment.

## Admin-Only Visibility

Governance Coverage appears only in the Admin Record Evidence view. It does
not add public routes, public file access, upload controls, or download
controls.

## Non-Mutating Behavior

Stage 17N is visibility-only. It does not mutate records, evidence,
attachments, relationships, schemas, manifests, canonical verification hashes,
or any Stage 15D through Stage 17M deterministic governance output.

## No Prediction Or Forecasting Behavior

Governance Coverage describes the current visible governance chain only. It
does not infer hidden governance states, forecast future governance movement,
or estimate risk.

## No AI-Generated Assessment Behavior

All coverage text and classifications are deterministic. No AI reasoning,
natural-language generation, or probabilistic model is used to create the
coverage result.
