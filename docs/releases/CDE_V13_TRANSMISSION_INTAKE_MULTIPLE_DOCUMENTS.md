# CDE v13 — Transmission Intake Multiple Governed Documents

## Purpose

This release improves Public Transmission Intake so administrators can select
multiple existing governed Documents while creating a new Transmission.

The previous workflow required administrators to create the Transmission first,
open Transmission Management, include one Document, and repeat the inclusion
step for every additional Document.

The improved workflow is:

```text
Enter communication metadata
  -> search existing Published Documents
  -> select one or more governed Documents
  -> review the selected Documents
  -> create the Transmission and all inclusion relationships together
```

## Governance Model

The governance model is unchanged.

A Transmission governs communication context. A Document preserves content.
Each included Document remains an independently governed public object with its
own identity, lifecycle, provenance, verification hash, and public page.

The Transmission stores one governed inclusion relationship for each selected
Document. It does not duplicate, alter, publish, or create Document identities.

## Document Selection

The Create Public Transmission page now includes an Included Governed Documents
section. Administrators can search existing Published Documents using the
existing published-document search metadata and add Documents by their immutable
CDE Document Identifier.

The selected list preserves selection order. Each selected Document may carry:

- relationship label, defaulting to `Transmitted document`;
- optional public note.

A non-JavaScript fallback allows one Document Identifier per line. Per-document
labels and notes can still be adjusted after creation through the existing
post-creation inclusion workflow.

## Selected-Document Synchronisation

The JavaScript-enhanced intake interface uses the visible Selected Documents
list as the administrator-facing source of truth. Adding a Document creates the
submitted hidden identifier, relationship label, and public note fields for that
same list item. Removing a Document removes those submitted fields as well, so
stale identifiers cannot remain in the request after the visible item is
removed.

The selected-document count is announced through a live status region and uses
singular or plural wording as the list changes.

The multiline fallback textarea is rendered only inside `noscript`. It is
therefore available when JavaScript is unavailable, but it no longer appears as
a second independent document-entry mechanism during normal enhanced use.

## Persistence and Validation

Submission validates all selected Documents before creating anything. If any
selected Document is duplicated, unknown, unpublished, or otherwise ineligible,
the submission is rejected and no partial Transmission inclusion set is created.

The server parses one canonical ordered list. If enhanced selected-list fields
are submitted, they are authoritative and fallback textarea values are ignored.
If no enhanced selected-list fields are submitted, the server accepts the
non-JavaScript fallback list, one existing Published Document Identifier per
line. In both paths, duplicate, unknown, unpublished, or otherwise ineligible
Documents are rejected server-side.

When validation succeeds, CDE creates:

- the Transmission;
- the normal Transmission reference;
- the initial Transmission lifecycle event;
- one inclusion relationship per selected Document;
- one generated inclusion reference per relationship;
- one Transmission history entry per inclusion.

The selected display order is preserved in the inclusion positions.

## Compatibility

The existing post-creation Include governed object workflow remains available
for later corrections and additions.

No changes were made to:

- Document identity;
- Transmission identity;
- publication semantics;
- Record-Document Associations;
- Public Collections;
- SHA-256 behaviour;
- public eligibility;
- authorization.

## Tests

Focused tests cover creating Transmissions with one selected Document, multiple
selected Documents, order preservation, generated inclusion references,
inclusion history entries, duplicate rejection, unknown and unpublished document
rejection, zero-document creation, and continued support for the existing
post-creation inclusion workflow.

Additional synchronisation tests cover the canonical selected-list parser,
stale fallback identifiers being ignored during JavaScript-enhanced submission,
non-JavaScript multiline fallback creation, fallback validation failure,
selected-document count wording, and the generated HTML structure for the
`noscript` fallback.
