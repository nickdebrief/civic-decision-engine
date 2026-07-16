# CDE v12.18 — Ordered Sequence and Continuity

## Purpose

CDE v12.18 makes governed Archive Collection membership sequence operationally
inspectable. It adds continuity calculation, previous/next navigation, sequence
position visibility, governed sequence changes, public collection traversal, and
public-safe continuity wording.

## Governing Principle

Sequence records order without replacing identity. A sequence orders governed
memberships. It does not merge documents, rewrite documents, create shared
document identity, infer chronology, establish causation, transfer document
history into a collection, or change public document publication history.

## Sequence Ownership

The existing `archive_collection_memberships.display_sequence` field remains
the source of truth. Sequence belongs to the membership only. It is not stored
on the document, collection, public document record, record-document
association, document metadata, or document lifecycle history.

No schema change was required for v12.18.

## Deterministic Ordering

The administrative active collection order is:

1. `display_sequence ASC`
2. `created_at ASC`
3. `membership_reference ASC`

The final tie-breakers keep ordering deterministic for legacy or manually
constructed duplicate positions.

## Continuity States

The derived continuity states are:

- Empty
- Single Member
- Continuous
- Gap Present
- Duplicate Position
- Invalid Position

Continuity is calculated from active sequence-eligible memberships. It is a
diagnostic view, not a stored lifecycle state.

## Sequence Governance

Sequence changes are explicit membership actions. A sequence change requires:

- a positive integer position;
- an administrative note;
- actor attribution from the authenticated signed admin session.

Every change appends immutable membership history with previous and new
membership state. Old history is not rewritten.

## Duplicate-Position Handling

CDE v12.18 uses explicit position assignment without automatic shifting.

If another active membership in the same collection already occupies the target
position, the operation is rejected with a bounded sequence-conflict error.
The administrator must resolve the other membership separately. The same
position may be used independently in another collection.

## Deactivation and Restoration

When a membership is removed, it leaves the active sequence and no remaining
positions are renumbered. This may produce a visible administrative gap.

When a membership is restored, its prior position is reused only if unoccupied.
If occupied, restoration requires an explicit new positive sequence position.
No membership is displaced silently.

## Previous and Next Navigation

Authenticated collection and membership views show previous and next membership
context derived from active governed collection order. First and last members
render clear boundary text rather than fake disabled links.

Public collection traversal is projected from public-eligible memberships only.
Public numbering uses the visible public sequence, such as `Member 1 of 2`,
and does not expose hidden administrative positions, private memberships,
inactive memberships, unpublished documents, or gaps caused by hidden members.

## Sequence Pathway

Membership detail pages include a Sequence Pathway derived from immutable
membership history. This remains separate from document Publication Pathway,
Publication Provenance, record verification, record-document associations, and
Administrative Audit.

## Public Boundary Wording

Public collection pages state that sequence records navigational continuity
only. Sequence does not alter document identity, provenance, lifecycle,
evidential status, factual meaning, authorship, legal status, or external
validation.

## Preservation Guarantees

CDE v12.18 does not change:

- document identity or bytes;
- document SHA-256;
- document filename, title, description, date, or reference identifier;
- document lifecycle or publication state;
- Publication Provenance or Publication Pathway;
- Public Document Library routes or content;
- record-document associations or Association Pathway;
- record evidence, lineage, verification, or hashes;
- collection identity;
- membership identity;
- authentication, session handling, or actor attribution;
- public/private visibility boundaries;
- image, PDF, search, filtering, pagination, or footer behaviour.

## Exclusions

This stage does not implement automatic grouping, inferred chronology,
date-derived ordering, OCR, AI ordering, collection versioning, nested
collections, collection inheritance, record aggregation, drag-and-drop bulk
reordering, automatic publication, or automatic membership activation.

## Validation Results

Validation covered focused ordered-sequence and continuity tests, v12.17
membership regression, Archive Collections regression, Administration Console
readability, intake corrections, document intake, admin session/navigation,
Administrative Audit, Public Document Library, record-document associations,
public association traceability/index, footer navigation, full regression,
Python compilation, whitespace checks, and conflict-marker checks.
