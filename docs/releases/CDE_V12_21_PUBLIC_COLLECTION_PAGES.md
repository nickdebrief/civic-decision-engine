# CDE v12.21 — Public Collection Pages

## Purpose

CDE v12.21 introduces public collection pages as a curated discovery and presentation layer over independently governed public CDE objects.

A collection does not merge, copy, convert, or replace the objects it presents. Canonical Records, Published Documents, and governed Record-Document Associations keep their own public identifiers, lifecycle, provenance, public pages, governance state, and relationships.

## Relationship to Earlier Stages

This stage extends the existing governed Archive Collection and Collection Membership architecture introduced in v12.14, v12.17, and v12.18. It preserves the document membership lifecycle and sequence model while adding typed collection membership for:

- Canonical Records
- Published Documents
- Record-Document Associations

It does not change Document Intake, Publication Provenance, Publication Pathway, Association Pathway, Administrative Audit, verification hashes, evidence, or public/private visibility rules.

## Routes

- `/collections`
- `/collections/{collection_reference}`

The public index lists eligible public collections only. The public detail route resolves collections by stable public collection reference and uses the existing public not-found behaviour for missing or inaccessible collections.

## Collection Membership Source

The authoritative membership source remains `archive_collection_memberships`.

The schema now stores a typed member reference:

- `member_type`
- `member_reference`
- `section_label`
- `curator_note`

Existing document memberships remain valid through an idempotent compatibility path:

- legacy rows default to `published_document`
- legacy `document_id` values backfill `member_reference`
- membership references and history are not rewritten

## Supported Member Types

### Canonical Record

Public rendering shows the record title, public reference, record type, summary where available, public status, and a link to the independent public record page.

### Published Document

Public rendering shows the document title, reference identifier, format, publication status, summary where available, and a link to the independent public document page.

### Record-Document Association

Public rendering shows the public association reference, relationship label, linked record/document context, public association status, public note where available, and a link to the independent public association page.

## Visibility and Eligibility

Public collection pages resolve member eligibility dynamically at render time.

A member is shown publicly only when:

- the collection is active and public
- the membership is active
- the membership lifecycle status is `Active`
- the referenced member object is currently eligible for public display

Unavailable members are omitted from public collection pages without deleting membership rows or rewriting membership history.

## Ordering

Members render in governed sequence order:

1. `display_sequence`
2. `created_at`
3. `membership_reference`

Sequence remains navigational context only. It does not establish causation, chronology, evidential sufficiency, authorship, legal status, or factual truth.

## Public Presentation

Public collection pages display:

- collection title
- stable public collection reference
- summary metadata
- visible member count
- governance boundary wording
- ordered governed collection members
- independent public links for each visible member
- public-safe collection pathway

The page states that each item remains independently governed with its own identity, provenance, lifecycle, relationships, and public page.

## Administration

The authenticated Archive Collection membership workflow now supports adding:

- Published Document memberships
- Canonical Record memberships
- Record-Document Association memberships

Membership creation remains authenticated and actor-attributed through the signed admin session. The existing membership lifecycle is unchanged:

Draft → Reviewed → Approved → Active → Inactive

## Security Boundaries

Public collection pages do not expose:

- private notes
- curator notes
- administrative notes
- raw history JSON
- storage paths
- sidecar paths
- session identity
- credentials
- secrets
- hidden member metadata

Server-side validation rejects unsupported member types, invalid references, unavailable public members for record and association member types, and duplicate active memberships.

## Preserved Behaviour

CDE v12.21 does not change:

- record identity
- document identity
- association identity
- lifecycle states or transitions
- publication eligibility
- document bytes or SHA-256
- record verification hashes
- evidence handling
- public/private visibility boundaries
- Public Record Index behaviour
- Public Document Library behaviour
- Public Association Index behaviour
- Administrative Audit
- Document Intake

## Validation

Validation added for v12.21 covers typed membership schema compatibility, public rendering for records/documents/associations, dynamic hidden-member omission, duplicate active-membership rejection, unsupported member-type rejection, admin add-member rendering, and authentication boundaries.
