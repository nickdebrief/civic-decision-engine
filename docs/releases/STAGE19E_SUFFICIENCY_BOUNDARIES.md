# Stage 19E - Sufficiency Boundaries

## Purpose

Stage 19E identifies the boundary between what existing visible record-derived
outputs support inside the framework and where that visible support ends. It
maps existing Stage 19C attribution states into supported, partially supported,
and unsupported boundary categories.

Stage 19E does not determine real-world evidential sufficiency, legal
sufficiency, truth, or factual correctness.

## Relationship to CREF Methodology

CREF separates what a visible record can support from claims that require
information beyond the record. Stage 19E makes that separation explicit by
describing only the support represented in existing framework outputs.

## Relationship to Stage 19A

Stage 19A provides the Determination Trace. Stage 19C may attribute visible
evidence to those trace steps, and Stage 19E reports the resulting attribution
boundary without changing the trace.

## Relationship to Stage 19B

Stage 19B provides the Rule Citation Layer. Stage 19C may attribute visible
evidence to those citations. Stage 19E maps the existing attribution states and
does not create or alter rule citations.

## Relationship to Stage 19C

Stage 19C is the source layer for Stage 19E. Its `Attributed`, `Partially
Attributed`, and `No Visible Evidence Attributed` states are mapped directly to
the three boundary output categories. Unsupported outputs are not treated as
false or invalid.

## Relationship to Stage 19D

Stage 19D assembles and describes existing framework outputs. Stage 19E follows
that report in the Admin Record Evidence view and adds a visibility-boundary
description. It does not change the report or generate a new conclusion from
it.

## Sufficiency Boundary Model

The model returns a boundary state, summary counts, three ordered output
categories, a five-step boundary path, and fixed limitations. Each mapped output
retains its visible output identity and attributed evidence identifiers while
adding a descriptive boundary label and basis.

The model evaluates support inside CREF only. It does not evaluate the evidence
outside the visible attribution matrix.

## Boundary States

- `Sufficiency Boundaries Available` is rendered when an Evidence Attribution
  Matrix exists and at least one output has an `Attributed` state.
- `Partial Sufficiency Boundaries` is rendered when the matrix exists but only
  partial or unsupported mappings are present.
- `Sufficiency Boundaries Unavailable` is rendered when no matrix exists.

## Output Categories

- `Attributed` maps to `Supported` and `Visible Support Present`.
- `Partially Attributed` maps to `Partially Supported` and `Partial Visible
  Support`.
- `No Visible Evidence Attributed` maps to `Unsupported Within Visible
  Attribution` and `No Visible Support Attributed`.

Unsupported means only that Stage 19C attributed no visible evidence source to
the output. It does not mean false, invalid, disproven, or insufficient in the
real world.

## Boundary Path

The deterministic path is:

1. Evidence Attribution Matrix
2. Attributed Outputs
3. Partially Attributed Outputs
4. Unsupported Outputs
5. Sufficiency Boundary Classification

Each path entry contains a step number, label, input, and descriptive output.

## Limitations

Stage 19E does not determine truth, liability, intent, blame, factual
correctness, legal sufficiency, or evidential sufficiency in the real world. It
does not validate evidence or create evidence, rules, conditions,
classifications, findings, conclusions, recommendations, or predictions.

## Deterministic Constraints

Stage 19E is deterministic, read-only, visibility-only, idempotent, and
non-mutating. Identical Stage 19C inputs produce identical boundary dictionaries.
No external source or external data retrieval is used.

It introduces no database writes, schema changes, migrations, background jobs,
public route changes, upload/download changes, canonical hash changes,
attachment hash changes, evidence validation, recommendations, or predictions.

## Admin-Only Visibility

Sufficiency Boundaries render only in the Admin Record Evidence view after the
Stage 19D Determination Report. Stage 19E adds no public endpoint and changes no
public visibility.

## Non-Mutating Behavior

Stage 19E reads the existing Evidence Attribution Matrix and returns a new
boundary dictionary. It does not modify the matrix, records, versions,
attachments, evidence, classifications, hashes, or canonical serialization.

## Expected Fixture Behavior

Current admin fixtures include attributed Stage 19C outputs and therefore
render `Sufficiency Boundaries Available`. Supported, partially supported, and
unsupported counts are derived directly from existing attribution states. A
direct helper call without an attribution matrix returns `Sufficiency Boundaries
Unavailable`.
