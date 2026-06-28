# Stage 19G - Explainability Certification

## Purpose

Stage 19G provides a deterministic certification-style summary of whether the
required Stage 19 explainability components are visibly available and
inspectable for a record.

Explainability Certification is internal to the framework. It does not certify
truth, legal correctness, factual correctness, or real-world evidential
sufficiency.

## Relationship to CREF Methodology

CREF requires record-derived analysis to remain visible, reproducible, and
bounded. Stage 19G makes the availability of that explanation structure
explicit through declared component checks. Certification means only that the
framework's own explainability outputs are present and inspectable.

## Relationship to Stage 19A

Stage 19A supplies the Determination Trace. Stage 19G treats it as available
when visible record context and an ordered trace path are present, partially
available when a trace output exists without both, and unavailable when absent.

## Relationship to Stage 19B

Stage 19B supplies the Rule Citation Layer. Its existing citation state maps
directly to available, partially available, or unavailable component status.
Stage 19G does not create or alter citations.

## Relationship to Stage 19C

Stage 19C supplies the Evidence Attribution Matrix. Stage 19G reads the existing
attribution state only. It does not validate evidence or change attribution.

## Relationship to Stage 19D

Stage 19D supplies the Determination Report. The existing report state determines
whether that component is available or unavailable.

## Relationship to Stage 19E

Stage 19E supplies Sufficiency Boundaries. Its available, partial, or unavailable
boundary state maps directly to the component certification category.

## Relationship to Stage 19F

Stage 19F supplies Counterfactual Visibility. Its available, partial, or
unavailable visibility state maps directly to the component certification
category.

## Explainability Certification Model

The model evaluates six required components in a fixed order. Every component
entry contains its name, source stage, availability state, certification state,
certification label, basis, and limitations.

The model certifies component availability only. It does not assess the truth,
quality, correctness, or legal meaning of component content.

## Certification States

- `Explainability Certified` means all six required components are available.
- `Explainability Partially Certified` means at least one required component is
  available or partially available, but not all six are available.
- `Explainability Not Certified` means no required component is available or
  partially available.

## Required Explainability Components

The required components are:

1. Determination Trace
2. Rule Citation Layer
3. Evidence Attribution Matrix
4. Determination Report
5. Sufficiency Boundaries
6. Counterfactual Visibility

## Certified Components

An available component maps to `Certified`, `Explainability Component Present`,
and a basis stating that the existing framework output is available and
inspectable for the record.

## Partially Certified Components

A partially available component maps to `Partially Certified` and
`Explainability Component Partially Present`. This status describes incomplete
framework availability only and is not a judgment about underlying facts.

## Uncertified Components

An unavailable component maps to `Not Certified` and `Explainability Component
Not Present`. Missing component output does not imply that an underlying event,
fact, record, or explanation does not exist elsewhere.

## Certification Path

The deterministic path is:

1. Determination Trace
2. Rule Citation Layer
3. Evidence Attribution Matrix
4. Determination Report
5. Sufficiency Boundaries
6. Counterfactual Visibility
7. Explainability Certification

Each step contains a step number, label, input, and descriptive availability
output.

## Limitations

Stage 19G does not determine truth, liability, intent, blame, factual
correctness, legal sufficiency, or evidential sufficiency in the real world. It
does not validate evidence or certify factual truth, legal correctness, or
real-world evidence sufficiency. It does not create evidence, rules, conditions,
classifications, findings, conclusions, recommendations, or predictions.

## Deterministic Constraints

Stage 19G is deterministic, read-only, visibility-only, idempotent, and
non-mutating. Identical Stage 19A-19F inputs produce identical certification
dictionaries. No external source or external data retrieval is used.

It introduces no database writes, schema changes, migrations, background jobs,
public route changes, upload/download changes, canonical hash changes,
attachment hash changes, evidence validation, recommendations, or predictions.

## Admin-Only Visibility

Explainability Certification renders only in the Admin Record Evidence view
after Stage 19F Counterfactual Visibility. Stage 19G adds no public endpoint and
changes no public visibility.

## Non-Mutating Behavior

Stage 19G reads existing Stage 19A-19F output dictionaries and returns a new
certification dictionary. It does not modify those outputs, records, versions,
attachments, evidence, classifications, hashes, or canonical serialization.

## Expected Fixture Behavior

Current admin fixtures contain all six required explainability components and
therefore render `Explainability Certified`, six certified components, no
partially certified components, and no uncertified components. A direct helper
call without Stage 19 inputs renders `Explainability Not Certified`.
