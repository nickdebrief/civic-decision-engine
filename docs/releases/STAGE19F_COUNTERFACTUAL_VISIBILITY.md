# Stage 19F - Counterfactual Visibility

## Purpose

Stage 19F makes visible which framework layers and evidence categories are
represented in the current record-derived outputs and which are not. It
describes absence without assigning meaning to that absence.

Counterfactual Visibility does not generate hypothetical scenarios, predict
outcomes, determine truth, infer intent, validate evidence, or perform new
analysis.

## Relationship to CREF Methodology

CREF limits analysis to visible record information. Stage 19F extends that
principle by making the boundary of visible representation inspectable. It
shows where the current framework pathway contains outputs and where no visible
representation is present.

## Relationship to Stages 19A-19E

Stage 19F reads existing outputs from:

- Stage 19A Determination Trace
- Stage 19B Rule Citation Layer
- Stage 19C Evidence Attribution Matrix
- Stage 19D Determination Report
- Stage 19E Sufficiency Boundaries

It does not alter or recompute the meaning of those outputs. Stage 19C supplies
visible evidence elements and support states. Stages 19D and 19E provide visible
report and boundary-layer representation.

## Counterfactual Visibility Model

The model evaluates a fixed registry of ten framework layers:

1. Visible Record
2. Conditions
3. Trajectory
4. Administrative Outputs
5. Record Evolution
6. Determination Trace
7. Rule Citation Layer
8. Evidence Attribution Matrix
9. Determination Report
10. Sufficiency Boundaries

A layer is visible when an existing output represents it. Supporting evidence
identifiers and source support states are retained where Stage 19C provides
them. A layer is non-visible only when no supplied record-derived output
represents it.

## Visibility States

- `Counterfactual Visibility Available` means an Evidence Attribution Matrix is
  available for deterministic layer and evidence visibility review.
- `Partial Counterfactual Visibility` means one or more earlier framework
  outputs are visible but no Evidence Attribution Matrix is available.
- `Counterfactual Visibility Unavailable` means no supplied Stage 19 output is
  available.

These states describe framework availability only. They are not findings about
the record or underlying events.

## Visible and Non-Visible Layers

Visible layer entries identify layer type, layer name, visibility state, source
support state, supporting evidence IDs, visibility label, basis, and
limitations.

Non-visible layer entries identify the declared layer and state that no visible
representation is present. Absence does not imply that an event, record,
condition, or fact does not exist outside the supplied framework outputs.

## Evidence Visibility

Visible evidence elements are copied from existing Stage 19C evidence sources.
Stage 19F does not create or renumber evidence IDs.

Non-visible evidence elements use a fixed registry of evidence categories that
Stage 19C can represent. They do not invent missing evidence IDs or assert that
evidence should exist. They state only that no visible Stage 19C source of that
category is represented in the current record.

## Counterfactual Path

The deterministic path is:

1. Visible Record
2. Framework Layers Evaluated
3. Visible Layers
4. Non-Visible Layers
5. Evidence Visibility
6. Counterfactual Visibility Classification

Each step contains a step number, label, input, and descriptive output.

## Limitations

Stage 19F does not determine truth, liability, intent, blame, factual
correctness, legal sufficiency, or evidential sufficiency. It does not validate
evidence, predict outcomes, generate hypothetical scenarios, or create
evidence, rules, conditions, or classifications. It assigns no meaning to an
absence and does not modify the record.

## Deterministic Constraints

Stage 19F is deterministic, read-only, visibility-only, idempotent, and
non-mutating. Identical visible inputs produce identical visibility
dictionaries. No external source or external data retrieval is used.

It introduces no database writes, schema changes, migrations, background jobs,
public route changes, upload/download changes, canonical hash changes,
attachment hash changes, evidence validation, recommendations, or predictions.

## Admin-Only Visibility

Counterfactual Visibility renders only in the Admin Record Evidence view after
Stage 19E Sufficiency Boundaries. Stage 19F adds no public endpoint and changes
no public visibility.

## Non-Mutating Behavior

Stage 19F copies existing visible values into a new descriptive dictionary. It
does not alter Stage 19A-19E outputs, records, versions, attachments, evidence,
classifications, hashes, or canonical serialization.

## Expected Fixture Behavior

Current admin fixtures contain an Evidence Attribution Matrix and render
`Counterfactual Visibility Available`. Visible layers and evidence elements are
listed from existing outputs. Unrepresented framework layers and evidence
categories remain visible as descriptive absence entries. A direct helper call
without Stage 19 inputs renders `Counterfactual Visibility Unavailable`.
