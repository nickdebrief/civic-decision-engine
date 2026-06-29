# Stage 21 - Report Structure & Output Modes

## Purpose

Stage 21 reorganises the Admin Record Evidence report into deterministic output
modes. The complete inspection report remains available, while shorter modes
make ordinary administrative review easier without removing underlying
framework information.

Stage 21 changes report presentation and composition only. It performs no new
analysis and does not change any existing framework output.

## Why Report Modes Were Introduced

The complete Admin Record Evidence report contains administrative lifecycle,
evidence, governance, record evolution, explainability, attribution,
certification, and framework self-description sections. That depth is useful
for full inspection but creates substantial repetition during ordinary review.

Report modes separate current-state review from methodological inspection while
preserving access to the complete report.

## Report Mode Classification

Stage 21 supports three fixed modes:

1. `Executive Report`
2. `Review Report`
3. `Full Inspection Report`

The optional admin-only query parameter is:

- `?report_mode=executive`
- `?report_mode=review`
- `?report_mode=full`

Full inspection is the default. Missing or unsupported values resolve
deterministically to `Full Inspection Report`.

## Executive Report

The Executive Report answers: **What is the current state of the record?**

It includes:

- record and report navigation summaries;
- administrative state table;
- evidence coverage, sufficiency, completeness, and requirement summary;
- progression requirements table;
- outcome, resolution, closure, and archive classifications;
- determination trace summary;
- framework limitations; and
- report-mode limitations.

It does not expand the complete rule citation layer, evidence attribution
matrix, supporting-evidence list, or framework self-description.

## Review Report

The Review Report answers: **How was the current state reached, and what
supports it?**

It includes everything in the Executive Report and adds:

- target-level evidence summary;
- evidence requirements;
- determination trace detail;
- rule citation summary;
- evidence attribution summary;
- sufficiency-boundary summary;
- counterfactual-visibility summary;
- explainability-certification summary; and
- framework self-description summary.

It summarises long attribution and citation collections rather than expanding
every row.

## Full Inspection Report

The Full Inspection Report answers: **What is everything visible in the
framework for this record?**

It preserves the pre-Stage-21 complete report groups:

- all administrative workflow sections;
- outcome, resolution, closure, and archive sections;
- full supporting evidence;
- full evidence coverage and evaluation layers;
- record governance and record evolution;
- determination trace and rule citation detail;
- evidence attribution matrix;
- sufficiency boundaries and counterfactual visibility;
- explainability certification; and
- framework self-description.

This remains the default mode.

## Report Navigation Header

Every mode displays the record reference, record version, current report mode,
available modes, report purpose, and report scope. A generated timestamp appears
only when an existing `generated_at` or `exported_at` value is already available
in record metadata. Stage 21 does not create a live timestamp.

## Report Section Index

Every mode includes a deterministic section index. The index records whether a
section is included, summarised, or fully detailed in Executive, Review, and
Full Inspection modes.

## Summary Tables

Executive and Review modes use compact deterministic tables for:

- administrative state;
- evidence state and target coverage;
- progression requirements; and
- explainability availability.

The tables display values produced by existing helpers. They do not reinterpret
or replace those values.

## Report Mode Limitations

Executive and Review modes state that they are summary views, that underlying
framework information remains available, and that full inspection remains
available in Full Inspection Report mode.

Full mode states that it preserves the complete visible framework inspection
record.

No mode changes classifications, evidence relationships, thresholds,
limitations, or framework behaviour.

## Deterministic Constraints

Stage 21 is deterministic, read-only, idempotent, admin-only, and non-mutating.
Identical visible record data, existing framework outputs, and report-mode input
produce identical report structure and content.

Stage 21 introduces no database writes, schema changes, migrations, public API
changes, external retrieval, probabilistic behaviour, AI summarisation,
canonical hash changes, attachment hash changes, upload/download changes, or
record mutations.

## Existing Behaviour Preservation

Stage 21 does not change framework reasoning, evidence evaluation,
relationships, thresholds, classifications, or source outputs. Stages 15D-20
remain unchanged in behavior. The Full Inspection Report preserves all existing
major report sections and remains the default admin view.
