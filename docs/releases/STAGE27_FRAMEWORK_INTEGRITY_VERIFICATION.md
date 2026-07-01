# Stage 27 — Framework Integrity Verification

## Purpose

Stage 27 adds deterministic integrity verification to the Admin Record Evidence
report. It checks whether the visible framework inspection stack preserves its
declared structure, counts, replay coverage, limitations, and methodological
boundaries across Stages 21 through 26.

This is framework-structure verification. It is not evidence validation, legal
evaluation, prediction, reclassification, or truth determination.

## Scope

The builder uses existing Stage 21 report-mode state, Stage 22 dependency
mapping, Stage 23 pathway stability, Stage 24 transition history, Stage 25
output provenance, Stage 26 deterministic replay, current administrative
outputs, and declared methodological limitations. No external or hidden input
is used.

Each check records a stable identifier, name and category, expected and
observed states, verification result and basis, affected stage or output, and a
limitation statement.

## Deterministic Behaviour

Identical visible framework outputs produce identical integrity checks and
summary counts. The supported verification results are `Verified`, `Verified
With Limitation`, `Not Available`, and `Integrity Gap Detected`.

Summary state evaluation is ordered as follows:

1. Any integrity gap produces `Framework Integrity Gap Detected`.
2. Otherwise, unavailable checks produce `Framework Integrity Not Fully Available`.
3. Otherwise, limited checks produce `Framework Integrity Verified With Limitations`.
4. Otherwise, the state is `Framework Integrity Verified`.

Declarative non-mutation and public-API boundaries are deliberately reported as
verified with limitation. Their visible declaration can be checked, but Stage
27 does not claim to provide external runtime monitoring.

## Integrity Checks

Stage 27 verifies:

* Full Inspection remains the default Stage 21 report mode;
* all three Stage 21 report modes remain available;
* Stage 22 retains 30 dependency nodes;
* Stage 23 retains eight pathways;
* Stage 24 retains 11 transition entries;
* Stage 25 retains 14 provenance entries;
* Stage 26 retains 15 replay steps;
* replayable outputs equal the total replay steps;
* non-replayable outputs remain zero;
* the eleven current administrative outputs remain available;
* Stage 21–26 limitation sets remain visible;
* report modes declare that classifications are unchanged;
* record-mutation and public-API boundaries remain declared.

Count preservation confirms structural availability only. It does not establish
truth, correctness, legal sufficiency, or evidential validity.

## Report Mode Rendering

* Executive Report shows integrity state, total and verified checks, gaps,
  preservation counts, and concise limitations.
* Review Report adds the integrity summary table and complete limitations.
* Full Inspection Report exposes every expected state, observed state,
  verification result, verification basis, affected output, and limitation.

Full Inspection remains the default report mode.

## Limitations

Stage 27 does not validate evidence, determine truth or liability, infer intent
or hidden inputs, assign blame, or create evidence. It does not modify records,
classifications, thresholds, dependencies, evidence relationships, transition
history, provenance, replay outputs, or report modes. It does not write to the
database or alter public API behaviour. It verifies framework structure only.

## Validation Results

Validation covers deterministic output and input non-mutation, required check
structure, summary counts, gap and unavailable states, report-mode rendering,
full-mode default behaviour, prior-stage preservation, compilation, whitespace,
conflict markers, focused admin tests, the complete test suite, and desktop and
mobile browser rendering.

No schema, migration, database, canonical hash, attachment hash,
upload/download, public API, classification, threshold, dependency,
transition-history, provenance, replay, mutation, or evidence-relationship
change is introduced.
