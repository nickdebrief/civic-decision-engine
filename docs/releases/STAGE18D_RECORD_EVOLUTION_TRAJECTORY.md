# Stage 18D - Record Evolution Trajectory

## Purpose

Stage 18D adds a read-only Record Evolution Trajectory layer to the Admin
Record Evidence view. It describes the current direction of record evolution
across visible same-reference version history, supersession relationships,
version transitions, generated timestamps, verification hashes, and stored
record metadata.

The trajectory layer is deterministic and visibility-only. It does not predict
future evolution or alter record state.

## Relationship To Stage 18A Record Evolution Summary

Stage 18A introduced the Record Evolution Summary and exposed the current
record version, supersession state, same-reference lineage count, and evolution
classification.

Stage 18D reuses the Stage 18A evolution classification where available. It
does not change Stage 18A behavior or mutate any evolution metadata.

## Relationship To Stage 18B Record Evolution Continuity

Stage 18B introduced deterministic continuity checks for version gaps,
supersession links, reference continuity, and lineage continuity.

Stage 18D reuses the Stage 18B continuity classification, version gap count,
supersession link count, and broken supersession link count where available. It
does not change Stage 18B behavior.

## Relationship To Stage 18C Record Evolution Change Log

Stage 18C introduced deterministic change-log visibility across same-reference
version history.

Stage 18D reuses the Stage 18C change-log classification, version transition
count, changed version count, and unchanged version count where available. It
does not change Stage 18C behavior.

## Record Evolution Chain Trajectory Model

The trajectory model uses existing stored fields:

- reference
- version
- supersedes
- generated_at
- exported_at
- is_latest
- trajectory
- system_state
- finding
- conditions_json
- signals_json
- generated_by
- verification_hash

When available, same-reference version rows are read from the existing records
table. No schema fields, migrations, or new records are created.

## Version Trajectory Review Model

Version Trajectory Review displays the record reference, current version,
earliest version, latest version, total versions, version transitions, version
gap count, and deterministic trajectory state.

Version trajectory states are:

- Initial
- Progressing
- Fragmented
- Unresolved

## Supersession Trajectory Review Model

Supersession Trajectory Review displays supersedes, superseded-by,
supersession link count, broken supersession link count, and deterministic
supersession state.

Supersession states are:

- Linked
- No Supersession
- Broken
- Unresolved

## Lineage Trajectory Review Model

Lineage Trajectory Review displays the record reference, total versions,
evolution classification, continuity classification, change-log
classification, and trajectory classification.

## Timestamp Trajectory Review Model

Timestamp Trajectory Review displays the earliest version, latest version,
timestamp order state, generated timestamp, and exported timestamp.

Timestamp order is evaluated only from stored generated_at values across
visible same-reference version order.

## Verification Hash Trajectory Review Model

Verification Hash Trajectory Review displays verification hash coverage,
current verification hash, total versions, versions with hashes, and versions
missing hashes.

Verification hash coverage is visibility-only. It does not recalculate,
modify, or validate canonical record hashes.

## Timestamp Order States

Timestamp order states are:

- Ordered: generated_at timestamps are present and non-decreasing across
  version order.
- Out Of Order: generated_at timestamps decrease across version order.
- Single Timestamp: only one version exists and generated_at is present.
- Missing Timestamp: one or more generated_at values are unavailable.
- Unresolved: timestamp data is internally inconsistent or no lineage is
  available.

## Verification Hash Coverage States

Verification hash coverage states are:

- Complete: every visible lineage version has a verification_hash.
- Partial: at least one visible lineage version has a verification_hash and at
  least one visible lineage version is missing one.
- Missing: no visible lineage version has a verification_hash.
- Unresolved: verification hash data is internally inconsistent or no lineage
  is available.

## Trajectory Classification Rules

Allowed trajectory classifications are:

- Initial Evolution Trajectory
- Stable Evolution Trajectory
- Active Evolution Trajectory
- Fragmented Evolution Trajectory
- Unresolved Evolution Trajectory

Initial Evolution Trajectory is rendered when there is one visible version, no
version transitions, no recorded changes, and Stage 18A classifies the record
as Initial Record State.

Stable Evolution Trajectory is rendered when multiple versions are present,
version gaps and broken supersession links are absent, timestamps are ordered,
and no fragmentation criteria are satisfied.

Active Evolution Trajectory is rendered when multiple versions and visible
transitions are present, Stage 18C reports recorded or extensive changes, the
latest version exists, and no fragmentation criteria are satisfied.

Fragmented Evolution Trajectory is rendered when version gaps, broken
supersession links, out-of-order timestamps, inconsistent supersession, or
Stage 18B Evolution Discontinuity is visible.

Unresolved Evolution Trajectory is rendered when reference, version, lineage,
timestamp, or verification hash data is unavailable or internally
inconsistent.

## Classification Evaluation Order

Trajectory classification is evaluated in this order:

1. Unresolved Evolution Trajectory
2. Fragmented Evolution Trajectory
3. Initial Evolution Trajectory
4. Active Evolution Trajectory
5. Stable Evolution Trajectory

Unresolved and fragmented states take precedence over initial, active, and
stable states. Stable Evolution Trajectory is rendered only when unresolved,
fragmented, initial, and active criteria are not satisfied.

## Deterministic Constraints

Stage 18D derives only from existing record fields, same-reference version
records, existing supersedes values, existing is_latest values, existing
verification hashes, existing generated/exported timestamps, and existing
record structure.

It performs no scoring, probability, prediction, forecasting, simulation, or
AI-generated assessment.

## Admin-Only Visibility

Record Evolution Trajectory appears only in the Admin Record Evidence view. It
does not add public routes, public file access, upload controls, or download
controls.

## Non-Mutating Behavior

Stage 18D is visibility-only. It does not mutate records, create records,
repair lineage, alter supersession values, modify canonical verification
hashes, or change any Stage 15D through Stage 18C deterministic output.

## No Prediction Or Forecasting Behavior

Record Evolution Trajectory describes only current stored record metadata and
visible same-reference version history. It does not infer future versions,
forecast record changes, or estimate an evolution direction beyond the current
visible lineage state.

## No AI-Generated Assessment Behavior

All trajectory text and classifications are deterministic. No AI reasoning,
natural-language generation, or probabilistic model is used to create the
trajectory result.

## No Schema Or Migration Behavior

Stage 18D does not add schema fields, migrations, new persistence, or version
records. It reads existing record fields only.

## No Governance-Output Analysis

Stage 18D does not analyze Stage 17 governance outputs. It belongs to the
Record Evolution Chain and is derived only from existing record evolution
metadata.
