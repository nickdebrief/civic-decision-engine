# Stage 26 — Deterministic Replay Mode

## Purpose

Stage 26 adds a deterministic, read-only replay view to the Admin Record
Evidence report. It demonstrates that existing visible output values and their
declared production bases can be assembled in the same stable sequence from
the same visible framework state.

Replay is descriptive. It is not simulation, prediction, reclassification, or
mutation.

## Scope

The replay sequence uses existing outputs from evidence readiness through
archive classification, together with Stage 22 dependency mapping, Stage 23
pathway stability, Stage 24 transition history, and Stage 25 output provenance.
It does not invoke the producing helpers or recalculate those outputs.

Each replay entry contains a stable replay identifier and step, output name and
value, producing stage and declared helper, visible input basis, dependency
basis, stability basis, transition basis, provenance basis, replay result,
replay label, and limitation statement. A helper that is not deterministically
exposed remains `Not Available`.

## Deterministic Behaviour

Replay entries preserve the order of the Stage 25 provenance entries and append
the Stage 25 provenance layer state. Identical inputs therefore produce an
identical replay dictionary and sequence.

The supported states are:

* `Deterministic Replay Available` when every visible replay entry has a
  declared replay basis.
* `Partial Replay Available` when some, but not all, entries have a declared
  replay basis.
* `Replay Basis Not Available` when no replay entries can be assembled.

Replay labels distinguish direct framework, dependency-derived,
stability-derived, transition-derived, and provenance-derived outputs. Missing
bases remain visibly labelled `Replay Basis Not Available`.

## Report Mode Rendering

* Executive Report shows the replay overview, state, counts, and concise key
  limitations.
* Review Report adds the replay summary table and complete replay limitations.
* Full Inspection Report shows all replay entries and all visible input,
  dependency, stability, transition, provenance, result, and limitation fields.

Full Inspection remains the default report mode.

## Limitations

Stage 26 does not simulate alternate outcomes, predict future states, infer
hidden inputs, create or validate evidence, determine truth or liability, infer
intent, assign blame, or modify records. It does not change classifications,
thresholds, dependencies, evidence relationships, transition history,
provenance, or report modes. It does not write to the database or alter public
API behaviour.

## Preservation

Stage 26 preserves Stage 21 report modes, the Stage 22 30-node dependency map,
the Stage 23 eight-pathway stability analysis, all Stage 24 transition entries,
and all Stage 25 provenance entries. No schema, migration, database, canonical
hash, attachment hash, upload/download, public API, classification, threshold,
dependency, transition-history, provenance, or evidence-relationship change is
introduced.

## Validation Results

Validation covers deterministic builder output, stable entry structure,
missing-helper handling, replay state counts, report-mode depth, full-mode
default behaviour, prior-stage preservation, compilation, conflict markers,
the focused admin suite, the complete test suite, and desktop/mobile browser
rendering.
