# CDE Platform Stage 44.1 — Composite Category Recommendation Coverage

## Purpose

CDE Platform Stage 44.1 completes the explicit recommendation coverage added by
CDE Platform Stage 44 for composite category values confirmed in the production
Published Document taxonomy.

## Composite Category Coverage

The centralized mapping adds these exact normalized values:

| Published Document category | Recommended Canonical Record Type |
| --- | --- |
| Hospital Admission / Administrative Record | Clinical Episode |
| Consent Form / Procedure Consent | Clinical Record |
| Operation Record / Procedure Record | Treatment Episode |
| Pain Intervention Record / Clinical Procedure Record | Medical Event |

Matching remains deterministic: string conversion, surrounding-whitespace
trimming, case folding, and exact normalized-key lookup. The implementation
does not introduce substring matching, fuzzy matching, slash splitting,
keyword inference, or category rewriting.

## Governance Boundary

The recommendation remains advisory. Administrators may select any controlled
Canonical Record Type before saving, and the submitted choice remains
authoritative. Unmapped categories retain the established Strike default and
do not display the recommendation label.

CDE Platform Stage 44.1 changes no application lifecycle, API response,
database schema, verification hash, provenance, association, permission,
indexing, or Public Archive behaviour.

## Validation

Focused coverage verifies all four confirmed composite categories,
administrator override, the unmapped fallback, and conditional advisory-label
presentation. Full regression validation confirms unchanged existing
behaviour.
