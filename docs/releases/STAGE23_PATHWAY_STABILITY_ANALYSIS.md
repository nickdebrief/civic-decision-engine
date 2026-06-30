# Stage 23 - Pathway Stability Analysis

## Purpose

Stage 23 makes the structural stability of existing CREF determination pathways
inspectable. It answers: **How stable is the current determination pathway?**

The stage evaluates only visible framework outputs, Stage 22 dependency
availability, existing evidence states, and administrative readiness outputs.
It does not perform new factual analysis or alter any source classification.

## Why Pathway Stability Analysis Was Introduced

Stage 22 exposes which outputs depend on which upstream nodes. Stage 23 uses
that declared dependency structure to distinguish pathways whose required
nodes are available from pathways affected by missing dependencies, open
readiness conditions, or visible evidence gaps.

This is structural inspection. Stability does not mean that a record is true,
correct, lawful, or sufficient in the real world.

## Stability States

Stage 23 supports five deterministic states, evaluated in this order:

1. `Stability Not Available` when dependency inputs are unavailable.
2. `Unstable Pathway` when a required dependency node or current pathway state
   is unavailable.
3. `Evidence-Sensitive Pathway` when the pathway is structurally available but
   existing evidence outputs expose gaps, partial sufficiency, incomplete
   coverage, unsupported targets, or additional attachment requirements.
4. `Partially Stable Pathway` when the pathway is structurally available but a
   visible administrative or readiness condition remains open.
5. `Stable Pathway` when required nodes and the current pathway state are
   available without visible evidence-sensitivity or blocking conditions.

The overall state follows the most restrictive visible pathway state. No
probability, forecast, hypothetical outcome, or hidden fact is introduced.

## Stability Inputs

The input summary displays existing values only:

- Stage 22 dependency completeness and missing-node count;
- evidence readiness, sufficiency, and completeness;
- unsupported and incomplete target counts;
- additional attachment requirements;
- administrative status, effective state, and review eligibility;
- outcome and resolution classifications and readiness;
- closure classification and readiness; and
- archive classification and readiness.

Missing values remain missing. Stage 23 does not repair or infer them.

## Pathway Model

Eight pathways are inspected:

1. Administrative Determination Path
2. Evidence Review Path
3. Outcome Path
4. Resolution Path
5. Closure Path
6. Archive Path
7. Explainability Path
8. Report Mode Path

Each entry contains a stable pathway ID, current state, stability
classification, required, available, and missing node IDs, visible sensitivity
indicators, blocking conditions, stability basis, and limitation statement.
The Stage 22 node definitions and dependencies are consumed without change.

## Evidence Sensitivity Indicators

Indicators are presence-based descriptions of existing outputs. They include:

- evidence gaps;
- partial or unsupported evidence sufficiency;
- partial or incomplete evidence completeness;
- unsupported or incomplete targets;
- additional attachment requirements;
- unsatisfied review eligibility; and
- resolution, closure, or archive readiness that has not been reached.

An indicator describes structural sensitivity only. It does not predict that
additional evidence will change an outcome or classification.

## Stability Paths

The Administrative Stability Path follows visible record context through
evidence readiness, administrative status, effective state, outcome,
resolution, closure, and archive.

The Explainability Stability Path follows visible record context through the
determination trace, rule citation, evidence attribution, sufficiency
boundaries, counterfactual visibility, explainability certification, framework
self-description, and report mode.

Each path step displays the existing Stage 22 node ID, current value, and
dependency state.

## Report Mode Integration

### Executive Report

Executive mode includes the stability overview, primary visible sensitivity
indicator, administrative stability path, and limitations.

### Review Report

Review mode adds the stability input summary, pathway summary, key pathway
classifications, all visible sensitivity indicators, and both stability paths.

### Full Inspection Report

Full Inspection mode includes all eight pathway entries, all indicators, both
paths, and all limitations. Full Inspection remains the default Stage 21 mode
and preserves all prior report sections.

## Limitations

Pathway stability analysis does not determine truth, liability, intent, blame,
factual correctness, legal sufficiency, or real-world evidential sufficiency.
It does not validate evidence, predict outcomes, forecast future states, or
determine whether additional evidence will change a classification.

Stage 23 does not create evidence, rules, conditions, or classifications. It
does not modify records, thresholds, dependencies, evidence relationships, or
report modes.

## Deterministic Constraints

Stage 23 is deterministic, read-only, admin-only, visibility-only, idempotent,
and non-mutating. Identical dependency maps and evidence-state inputs produce
identical stability dictionaries and rendered output.

No schema changes, migrations, database writes, public API changes, external
retrieval, probabilistic behavior, AI summarisation, canonical hash changes,
attachment hash changes, upload/download changes, or record mutations are
introduced.

## Existing Behavior Preservation

Stage 23 consumes Stage 15 evidence states, existing administrative outputs,
Stage 21 report modes, and the Stage 22 dependency map without modifying them.
All earlier deterministic values remain unchanged.

## Expected Fixture Behavior

A single-version fixture with a complete dependency map but unsupported or
incomplete evidence renders `Evidence-Sensitive Pathway`. Its administrative
path remains structurally visible, while the existing evidence gaps are shown
as sensitivity indicators. Explainability and report-mode paths may remain
stable when their required nodes are available.
