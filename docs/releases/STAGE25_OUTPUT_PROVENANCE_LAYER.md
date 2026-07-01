# Stage 25 - Output Provenance Layer

## Purpose

Stage 25 makes the production provenance of visible CREF outputs inspectable.
It answers: **Which implemented stage produced this output, which visible
inputs support it, and which methodological boundaries apply?**

The layer describes declared framework production only. It does not validate
the resulting output or infer hidden implementation details.

## Scope

Stage 25 provides provenance for fourteen outputs:

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
12. Determination Dependency Mapping
13. Pathway Stability Analysis
14. Record State Transition History

The first eleven entries describe existing administrative outputs. The final
three describe the inspection layers introduced by Stages 22, 23, and 24.

## Provenance Entry Model

Each entry contains:

- a stable provenance ID;
- output name and current value;
- producing stage;
- producing function or helper where deterministically declared;
- visible input basis;
- Stage 22 dependency basis;
- Stage 23 stability basis;
- Stage 24 transition basis;
- provenance label; and
- limitation statement.

When a producing helper is not declared by the visible implementation metadata,
Stage 25 renders `Not Available`. It does not infer a likely helper name.

## Producing Stages and Helpers

Producing helpers are declared from the implemented call path. Examples include
`classify_evidence_readiness`, `classify_administrative_action`,
`classify_effective_state`, `classify_outcome`, `classify_resolution`,
`_classify_closure`, and `_archive_classification`.

The inspection-layer entries cite `build_determination_dependency_map`,
`build_pathway_stability_analysis`, and
`build_record_state_transition_history`.

These names identify implemented production points only. They do not certify
the correctness of an output.

## Visible Input Basis

Administrative provenance lists the visible current values of declared Stage
22 upstream dependency nodes. Stage 22 provenance describes its declared node
set; Stage 23 provenance describes its visible stability inputs and dependency
map; Stage 24 provenance describes its visible transition entries.

Absent inputs remain absent. Stage 25 does not recover hidden parameters,
undocumented data, or unavailable historical values.

## Provenance Labels

Stage 25 supports these deterministic labels:

- `Direct Framework Output` for a visible output with a declared producing
  helper and no declared upstream dependency;
- `Dependency-Derived Output` for outputs whose declared production depends on
  visible upstream values, including the Stage 22 map;
- `Stability-Derived Output` for the Stage 23 stability analysis;
- `Transition-Derived Output` for the Stage 24 transition history;
- `Current-State Output` when Stage 24 exposes only the current state and no
  prior state; and
- `Provenance Not Available` when no visible output or production basis is
  available.

Labels describe framework provenance categories only. They do not create or
alter the underlying classifications.

## Dependency, Stability, and Transition Bases

The dependency basis reuses Stage 22 mapping states and upstream node IDs. The
stability basis reuses the matching Stage 23 pathway classification and basis.
The transition basis reuses the corresponding Stage 24 transition entry where
one exists.

Later layers are cited as inspection context and do not become the producer of
earlier administrative outputs. Stages 22, 23, and 24 remain unchanged.

## Deterministic Behaviour

Identical visible outputs, dependency map, stability analysis, transition
history, and declared helper metadata produce identical provenance dictionaries
and rendered tables. Input dictionaries are copied and never mutated.

No external retrieval, probabilistic inference, AI summarisation, or hidden
input reconstruction is used.

## Report Mode Rendering

### Executive Report

Executive mode displays the provenance overview, current provenance state,
entry and helper counts, inherited Stage 22-24 states, and key limitations. It
does not expand provenance rows.

### Review Report

Review mode adds a compact provenance table containing IDs, outputs, values,
producing stages and helpers, and provenance labels. It also displays all Stage
25 limitations.

### Full Inspection Report

Full Inspection mode displays every provenance field, including visible input,
dependency, stability, transition, and limitation bases. Full Inspection
remains the default Stage 21 report mode.

## Limitations

Stage 25 does not create provenance, infer hidden inputs, or infer missing
helper functions. It does not determine truth, liability, intent, blame,
factual correctness, legal sufficiency, or real-world evidential sufficiency.
It does not validate evidence or predict outcomes.

Stage 25 does not modify records or change classifications, thresholds,
dependencies, evidence relationships, transition history, or report modes.

## Preservation

Stage 21 retains all three report modes with Full Inspection as the default.
Stage 22 retains all 30 dependency nodes. Stage 23 retains all eight pathways.
Stage 24 retains all eleven transition history entries for the current fixture.

## Schema and Interface Boundaries

Stage 25 introduces no schema changes, migrations, database writes, public API
changes, canonical hash changes, attachment hash changes, upload/download
changes, classification changes, threshold changes, dependency changes,
transition-history changes, or evidence-relationship changes.

## Validation Results

Python compilation, whitespace, and conflict-marker checks pass. The admin test
module passes 132 tests, and the full suite passes 302 tests. Validation also
checks preservation of all 30 Stage 22 nodes, all eight Stage 23 pathways, and
all eleven Stage 24 fixture transitions. Desktop and mobile browser inspection
covers all three report modes.

## Expected Fixture Behaviour

The current fixture exposes fourteen provenance entries. Its eleven
administrative entries are `Current-State Output` because Stage 24 has no
explicit prior administrative states. The Stage 22, Stage 23, and Stage 24
entries render `Dependency-Derived Output`, `Stability-Derived Output`, and
`Transition-Derived Output` respectively.
