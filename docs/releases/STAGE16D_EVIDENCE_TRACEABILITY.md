# Stage 16D — Evidence Traceability

## Purpose

Stage 16D adds an Evidence Traceability section to the read-only Admin Record
Evidence view. It shows the deterministic relationship path behind each
evidence target using existing evidence relationships and safe attachment
metadata.

## Route Updated

- `GET /admin/records/{reference}/evidence`

## Deterministic Inputs

Evidence Traceability is derived only from:

- active `supports` relationships
- linked attachment metadata already safe for admin evidence display
- Stage 15D sufficiency outputs
- Stage 15E completeness outputs
- Stage 16B justification outputs
- Stage 16C confidence outputs

No AI reasoning, probability, statistical confidence, weighting, or manual
scoring is introduced.

## Rendered Detail

The section renders:

- Condition Traceability
- Signal Traceability
- Finding Traceability
- Record Traceability

Each target displays:

- target name
- active supports count
- supporting attachment titles
- relationship type(s)
- sufficiency state
- completeness state
- confidence state
- justification summary

## Traceability Summary

Stage 16D also renders deterministic summary counts:

- total traced targets
- total traced relationships
- total supporting attachments referenced

Inactive relationships, deleted attachments, and non-`supports` relationships do
not contribute to these counts.

## Admin-Only Scope

Stage 16D is an admin-only read-only evidence assessment layer. It does not add
upload functionality, download functionality, public file access, public routes,
or mutation controls.

## Verification Boundaries

Stage 16D does not change database schemas, canonical verification hashes,
public manifests, record versioning, attachment relationship storage, or any
Stage 15/16 evidence calculations.
