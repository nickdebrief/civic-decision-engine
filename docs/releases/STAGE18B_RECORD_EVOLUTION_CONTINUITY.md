# Stage 18B - Record Evolution Continuity

## Purpose

Stage 18B adds a read-only Record Evolution Continuity layer to the Admin
Record Evidence view. It determines whether the record's version lineage is
continuous, partially continuous, discontinuous, or unresolved using existing
record metadata and same-reference version history only.

## Relationship To Stage 18A Record Evolution Summary

Stage 18A introduced the Record Evolution Summary and exposed the current
record version, supersession state, same-reference lineage count, and evolution
classification.

Stage 18B builds on that same metadata. It does not change Stage 18A output. It
adds continuity checks for version gaps, supersession links, reference
continuity, and lineage continuity.

## Record Evolution Chain Continuity Model

The continuity model uses existing stored fields:

- reference
- version
- supersedes
- generated_at
- exported_at
- is_latest
- trajectory
- system_state
- finding
- verification_hash

When available, same-reference version rows are read from the existing records
table. No schema fields, migrations, or new records are created.

## Version Continuity Rules

Version continuity is derived from same-reference version numbers.

- Continuous: version metadata exists and no version gaps are present.
- Gap Detected: one or more version numbers are missing between lineage rows.
- Limited: only one version is available.
- Unresolved: the record reference or current version is missing.

The Version Gap Count is deterministic and counts missing version numbers
between the earliest and latest visible same-reference version rows.

## Supersession Continuity Rules

Supersession continuity is derived from stored supersedes values and
same-reference version rows.

- Linked: supersession links exist and no broken links are detected.
- No Supersession: no supersession links exist.
- Broken Link: one or more supersedes values point to a non-discoverable or
  inconsistent version.
- Unresolved: supersession metadata is internally inconsistent.

The Supersession Link Count counts stored supersedes values. Broken
Supersession Links counts supersedes values that cannot be matched to a prior
same-reference version or point to an invalid version order.

## Reference Continuity Rules

Reference continuity is derived from the current reference and same-reference
lineage rows.

- Continuous Reference: all lineage rows share the same reference and more than
  one version is present.
- Single Reference: only one version is visible.
- Reference Conflict: lineage rows contain conflicting references.
- Unresolved: the current reference is missing.

## Classification Rules

Allowed continuity classifications are:

- Continuous Evolution
- Partial Evolution Continuity
- Evolution Discontinuity
- Unresolved Evolution Continuity

Continuous Evolution is rendered when reference, version, and same-reference
history exist, no version gaps or broken supersession links exist, and the
current record is either the latest version or a prior version with a
discoverable later version.

Partial Evolution Continuity is rendered when reference, version, and at least
one same-reference version exist, but the lineage is limited or supersession
data is absent without contradiction.

Evolution Discontinuity is rendered when version gaps, broken supersession
links, reference conflicts, ordering conflicts, or is_latest conflicts are
visible.

Unresolved Evolution Continuity is rendered when reference, version, or lineage
fields are missing or unavailable.

## Classification Evaluation Order

Continuity classification is evaluated in this order:

1. Unresolved Evolution Continuity
2. Evolution Discontinuity
3. Continuous Evolution
4. Partial Evolution Continuity

Unresolved and discontinuity states take precedence over continuous and partial
states. Partial Evolution Continuity is rendered only when unresolved,
discontinuity, and continuous criteria are not satisfied.

## Deterministic Constraints

Stage 18B derives only from existing record fields, same-reference version
records, existing supersedes values, existing is_latest values, existing
verification hashes, existing generated/exported timestamps, and the existing
record structure.

It performs no scoring, probability, prediction, forecasting, simulation, or
AI-generated assessment.

## Admin-Only Visibility

Record Evolution Continuity appears only in the Admin Record Evidence view. It
does not add public routes, public file access, upload controls, or download
controls.

## Non-Mutating Behavior

Stage 18B is visibility-only. It does not mutate records, create records,
repair lineage, alter supersession values, modify canonical verification
hashes, or change any Stage 15D through Stage 18A deterministic output.

## No Prediction Or Forecasting Behavior

Record Evolution Continuity describes only the current stored record metadata
and same-reference version history. It does not infer future versions or
forecast record changes.

## No AI-Generated Assessment Behavior

All continuity text and classifications are deterministic. No AI reasoning,
natural-language generation, or probabilistic model is used to create the
continuity result.

## No Schema Or Migration Behavior

Stage 18B does not add schema fields, migrations, new persistence, or version
records. It reads existing record fields only.

## No Governance-Output Analysis

Stage 18B does not analyze Stage 17 governance outputs. It belongs to the
Record Evolution Chain and is derived only from existing record evolution
metadata.
