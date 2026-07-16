# CDE v12.17 — Collection Membership Governance

## Purpose

CDE v12.17 introduces governed membership for Archive Collections. A membership
is a separate administrative object that references an existing independently
preserved document from within a collection without copying, moving, publishing,
or modifying the document.

## Governed Membership Object

The stage adds `archive_collection_memberships` with immutable references using:

`CDE-MEM-YYYYMMDD-NNN`

Each membership records the collection, document, creation actor, lifecycle
state, display sequence, effective dates, notes, and active state. Membership
identity remains distinct from collection identity, document identity, record
identity, document references, and public collection references.

## Membership History

The stage adds `archive_collection_membership_history` for immutable membership
events:

- Created
- Reviewed
- Approved
- Activated
- Removed
- Restored
- Sequence changed

History records preserve timestamps, actors, notes, and previous/new state
snapshots for the membership object only.

## Lifecycle

Memberships use the governed lifecycle:

`Draft → Reviewed → Approved → Active`

Removal is represented as:

`Active → Inactive`

Memberships are never deleted. Inactive memberships can be restored without
issuing a new membership reference.

## Display Sequence

Display sequence belongs to the membership, not the document and not the
collection. Sequence changes create immutable membership-history entries and
preserve the previous value in the history record.

## Administration Console

Archive Collection detail pages now include a Collection Members section showing:

- Sequence
- Membership reference
- Document title
- Document reference
- Publication status
- Membership status
- Created actor and timestamp
- Membership actions

Administrators can add an existing document, review the membership, approve it,
activate it, remove it, restore it, and update its display sequence. The actor
for each action is derived from the authenticated signed admin session.

## Public Collection Pages

Public collection pages at `/collections/{collection_reference}` now display
ordered governed member documents only when:

- the collection is active and public;
- the membership is active;
- the membership lifecycle state is Active;
- the referenced document is Published and publicly accessible.

Each public member row links to the existing Public Document Library detail page.
The collection presents governed memberships and does not duplicate document
content.

## Preservation Guarantees

CDE v12.17 does not change:

- document identity;
- record identity;
- document lifecycle;
- publication behaviour;
- document provenance;
- document SHA-256 values;
- evidence handling;
- verification behaviour;
- public eligibility rules;
- archive collection identity;
- document intake;
- governed intake corrections;
- record-document associations;
- Publication Provenance;
- Administrative Audit;
- Public Record Index;
- Public Document Library behaviour;
- authentication or authorization;
- public/private visibility boundaries.

## Explicit Exclusions

This stage does not implement collection versioning, nested collections,
inheritance, bulk operations, automatic grouping, automatic sequence generation,
record aggregation, search redesign, public editing, or permission changes.

## Validation Results

Validation completed for focused membership governance, existing archive
collection behaviour, public collection rendering, document intake adjacency,
admin session and navigation adjacency, public document library behaviour, full
regression coverage, Python compilation, whitespace checks, and conflict-marker
checks.

## Implementation Summary

The implementation adds a membership storage module, admin membership workflow
routes, Collection Members presentation on Archive Collection admin pages,
public member rendering on public collection pages, focused tests, README
documentation, and this release note.
