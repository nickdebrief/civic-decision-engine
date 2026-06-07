# Stage 6F — Guided Evidence Linking

Status: Implemented / pending review

Scope:

- relationship target key selection guided by record elements
- condition targets derived from conditions_json
- signal targets derived from signals_json
- finding target derived from finding
- record target derived from reference
- free-text target entry removed from admin relationship form
- existing relationship add/remove routes preserved
- existing backend validation preserved
- no upload/download capability
- no public file exposure
- no canonical verification changes

## Label Refinement

Guided evidence target options now display human-readable labels while
preserving canonical target values internally.

## Relationship Display Refinement

Stage 6G improves active evidence relationship review by rendering relationship
counts and clearer relationship rows/cards while preserving existing add/remove
routes and stored relationship values.

## Relationship Coverage

Stage 6H adds deterministic evidence relationship coverage visibility,
including active relationship coverage counts and coverage status derived from
current record targets. It does not create relationships automatically and does
not change existing add/remove routes.
