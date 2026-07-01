# Stage 24 - Record State Transition History

## Purpose

Stage 24 exposes how existing framework-derived administrative states relate
as a visible transition history. It answers: **What state progression is
visible from the framework outputs already present for this record?**

The layer is descriptive only. It does not reconstruct events or generate
states that are absent from the visible record-derived outputs.

## Scope

Stage 24 evaluates eleven existing outputs:

1. Evidence Readiness
2. Administrative Action
3. Workflow State
4. Administrative Disposition
5. Review Eligibility
6. Administrative Status
7. Effective State
8. Outcome Classification
9. Resolution Classification
10. Closure Classification
11. Archive Classification

Each available output becomes one stable transition entry. Stage 22 supplies
the dependency basis and Stage 23 supplies the pathway stability basis.

## Transition Entry Model

Each transition contains:

- a stable transition ID;
- source stage and output name;
- prior state;
- current state;
- transition label and basis;
- Stage 22 dependency basis;
- Stage 23 stability basis; and
- a limitation statement.

Prior states are accepted only when an existing visible framework output
provides them explicitly. Version numbers, timestamps, trajectory fields, or
other metadata are not converted into prior administrative classifications.

When no prior state is visible, Stage 24 renders:

- `prior_state: Not Available`; and
- `transition_label: Current State Only`.

This rule prevents historical inference.

## Transition Classifications

Stage 24 supports these deterministic labels:

- `Current State Only` when a current output is visible but no prior output is
  available;
- `Structural Progression Visible` when visible prior and current structural
  outputs can be compared;
- `Evidence-Sensitive Progression` when a visible progression belongs to a
  Stage 23 evidence-sensitive pathway;
- `Review-Dependent Progression` for review, administrative status, effective
  state, and outcome progression;
- `Resolution-Dependent Progression` for resolution progression;
- `Closure-Dependent Progression` for closure progression;
- `Archive-Dependent Progression` for archive progression; and
- `Transition History Not Available` when none of the declared current outputs
  is visible.

These labels classify visible framework structure only. They do not assess the
real-world meaning or correctness of a transition.

## Dependency Basis

For each transition, Stage 24 displays the existing Stage 22 mapping state and
declared upstream dependency node IDs. The 30-node Stage 22 graph is consumed
without modification.

An unavailable dependency map remains visibly unavailable. Stage 24 does not
create replacement dependencies.

## Stability Basis

Each transition is associated with one of the eight existing Stage 23
pathways. Its stability basis displays the pathway name, current stability
classification, and existing structural basis.

Stage 24 does not recalculate or alter Stage 23 stability.

## Deterministic Behaviour

Identical current outputs, prior outputs, dependency map, and stability
analysis produce identical transition dictionaries and rendered tables. Input
dictionaries are copied and never mutated.

Absent values are omitted or displayed as unavailable. No hidden event, actor,
intent, cause, state, or transition is inferred.

## Report Mode Rendering

### Executive Report

Executive mode displays the transition overview, current transition state,
counts, dependency and stability states, and key limitations. It does not
expand transition rows.

### Review Report

Review mode adds a compact transition summary table containing IDs, source
stages, output names, prior states, current states, and transition labels. It
also displays the complete Stage 24 limitations.

### Full Inspection Report

Full Inspection mode displays all transition fields, including transition,
dependency, and stability bases and the limitation for every entry. Full
Inspection remains the default Stage 21 report mode.

## Limitations

Stage 24 does not create transition history or infer missing prior states. It
does not determine truth, liability, intent, blame, factual correctness, legal
sufficiency, or real-world evidential sufficiency. It does not validate
evidence, predict future states, or forecast outcomes.

Stage 24 does not modify records or change classifications, thresholds,
dependencies, evidence relationships, or report modes.

## Preservation

Stage 21 continues to provide Executive, Review, and Full Inspection modes,
with Full Inspection as the default. Stage 22 retains all 30 deterministic
dependency nodes. Stage 23 retains all eight pathway stability entries in Full
Inspection mode.

## Schema and Interface Boundaries

Stage 24 introduces no schema changes, migrations, database writes, public API
changes, canonical hash changes, attachment hash changes, upload/download
changes, classification changes, threshold changes, dependency changes, or
evidence-relationship changes.

## Validation Results

Python compilation, whitespace, and conflict-marker checks pass. The admin test
module passes 129 tests, and the full suite passes 299 tests. Validation also
checks preservation of all 30 Stage 22 nodes and all eight Stage 23 pathways.
Desktop and mobile browser inspection covers all three report modes.

## Expected Fixture Behaviour

The current single-version fixture exposes all eleven current administrative
outputs but no explicit prior administrative output values. Stage 24 therefore
renders eleven `Current State Only` entries with `prior_state` shown as
`Not Available`, while retaining each entry's dependency and stability basis.
