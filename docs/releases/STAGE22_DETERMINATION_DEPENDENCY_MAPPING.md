# Stage 22 - Determination Dependency Mapping

## Purpose

Stage 22 makes the structural dependencies between existing CREF outputs
inspectable. It answers: **What outputs are required for this determination to
exist?**

The stage describes existing implemented dependencies only. It performs no new
record analysis and does not alter any source output.

## Why Dependency Mapping Was Introduced

CREF already exposes visible evidence, administrative states, outcomes,
record-evolution classifications, determination traces, rule citations,
evidence attribution, explainability certification, framework self-description,
and report modes. Those outputs form ordered dependency chains, but the
relationships between them were previously distributed across individual stage
implementations.

Stage 22 gathers those declared structural relationships into one deterministic
inspection model.

## Dependency Mapping State

The dependency mapping state is derived from output presence only:

- `Dependency Map Available` when every declared node is available and fully
  mapped;
- `Dependency Map Partially Available` when one or more nodes or upstream
  mappings are missing but some mapping remains visible; and
- `Dependency Map Not Available` when no declared node value is available.

These states describe map availability. They do not assess the correctness or
quality of an output.

## Dependency Nodes

Each dependency node contains:

- a stable node ID;
- output name and type;
- current visible value;
- source stage;
- dependency and mapping states;
- upstream dependency node IDs;
- downstream dependent node IDs; and
- a limitation statement.

The declared map contains 30 nodes spanning visible record context, evidence
readiness, administrative workflow, effective state, outcome, resolution,
closure, archive, Stage 19 explainability outputs, Stage 20 self-description,
and Stage 21 report mode.

## Upstream Dependencies

Upstream dependencies identify existing values used by a later output. For
example:

- Effective State depends on Implementation Action and Administrative Status.
- Outcome Classification depends on Effective State and its visible
  administrative inputs.
- Resolution Classification depends on outcome, readiness, target, effective
  state, implementation, and administrative status outputs.
- Closure Classification depends on resolution outputs and the existing
  administrative pathway.
- Archive Classification depends on closure, resolution, readiness, review,
  and administrative outputs.

The lists follow implemented helper dependencies. They do not infer hidden
causes or missing events.

## Downstream Dependents

Downstream dependents identify later declared nodes reachable from a node. They
are calculated deterministically by reversing and traversing the declared
upstream graph.

For example, Administrative Status propagates into Effective State, Outcome,
Resolution, Closure, Archive, and Report Mode outputs. This propagation is
structural only and does not imply causation outside the framework.

## Dependency Completeness

The completeness summary displays:

- total, available, and missing dependency nodes;
- fully mapped, partially mapped, and unmapped outputs; and
- dependency completeness percentage.

Classifications are evaluated in this order:

1. `Dependency Map Not Available` when no nodes are available.
2. `Complete Dependency Map` when every node and declared upstream mapping is
   available.
3. `Partial Dependency Map` when at least one fully mapped output remains but
   one or more nodes or mappings are missing.
4. `Dependency Gaps Present` when outputs are visible but none has a complete
   upstream mapping.

Completeness measures mapping availability only. It does not imply truth,
correctness, legal sufficiency, or real-world evidential sufficiency.

## Dependency Paths

Stage 22 exposes two ordered paths.

The Administrative Determination Path is:

1. Visible Record
2. Evidence Readiness
3. Administrative Status
4. Effective State
5. Outcome Classification
6. Resolution Classification
7. Closure Classification
8. Archive Classification

The Explainability and Report Path is:

1. Visible Record
2. Determination Trace
3. Rule Citation Layer
4. Evidence Attribution Matrix
5. Sufficiency Boundaries
6. Counterfactual Visibility
7. Explainability Certification
8. Framework Self-Description
9. Report Mode

Each step displays its stable node ID, current value, and availability state.

## Report Mode Integration

### Executive Report

Executive mode includes the dependency overview, completeness summary, key
administrative dependency path, and limitations. It does not expand individual
nodes or mapping tables.

### Review Report

Review mode includes the overview, completeness summary, key upstream and
downstream mappings, both dependency paths, and limitations. It does not expand
the complete 30-node table.

### Full Inspection Report

Full Inspection mode includes every dependency node, complete upstream and
downstream mapping tables, both paths, and all limitations. Full Inspection
remains the default Stage 21 report mode and preserves all earlier report
sections.

## Limitations

Dependency mapping describes structural relationships between existing
framework outputs only. It does not determine truth, liability, intent, blame,
factual correctness, legal sufficiency, or real-world evidential sufficiency.
It does not validate evidence or create evidence, rules, or conditions.

Stage 22 does not modify records, classifications, thresholds, evidence
relationships, or report modes.

## Deterministic Constraints

Stage 22 is deterministic, read-only, admin-only, visibility-only, idempotent,
and non-mutating. Identical current values and dependency definitions produce
identical dependency dictionaries and rendered views.

No database writes, schema changes, migrations, public API changes, external
retrieval, probabilistic behavior, AI summarisation, canonical hash changes,
attachment hash changes, upload/download changes, or record mutations are
introduced.

## Existing Behavior Preservation

Stage 22 consumes existing Stage 7-21 outputs and does not alter their helper
logic or stored values. Stage 21 continues to default to Full Inspection Report,
and Executive and Review modes remain admin-only presentation views.
