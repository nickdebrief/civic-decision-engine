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
existing published-document search metadata. Search results render as a
multi-selection list, with each eligible Published Document showing:

- checkbox;
- immutable CDE Document Identifier;
- title;
- summary;
- format;
- optional reference identifier;
- publication status.

Administrators can select multiple matching Documents and use one Add Selected
Documents action to move them into the selected list. This avoids repeating the
search/add cycle for each Document.

The selected list preserves selection order. Each selected Document may carry:

- relationship label, defaulting to `Transmitted document`;
- optional public note.

A paste control also supports adding multiple existing Document Identifiers at
once, one per line. Pasted identifiers are added to the same selected list and
validated against eligible Published Documents before they are added. The
server still validates the same identifiers again when the Transmission is
created.

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

Documents already in the selected list cannot be added again. Search-result
checkboxes for selected Documents are disabled during the enhanced session, and
the server still rejects duplicate submitted identifiers.

The selected-document count is announced through a live status region and uses
singular or plural wording as the list changes.

The multiline fallback textarea is rendered only inside `noscript`. It is
therefore available when JavaScript is unavailable, but it no longer appears as
a second independent document-entry mechanism during normal enhanced use.

## Repeated Search State Preservation

The first bulk-selection implementation kept the ordered selected-Document
state only in browser memory. The search form still submitted a normal
`GET /admin/transmissions?document_search=...` request, so each additional
search reloaded the Transmission Intake page and created a new empty
`selectedDocuments` collection. Selected cards, the selected count, relationship
labels, public notes, disabled duplicate-prevention state, and hidden canonical
submission fields were therefore lost during the search.

The JavaScript-enhanced search now calls an authenticated admin search endpoint
and updates only the search-results region. Searching for another Published
Document no longer reloads the intake page, so the same ordered
`selectedDocuments` collection remains active while the administrator repeats:

```text
search -> select -> add -> search again -> select -> add
```

The search endpoint returns public-safe Published Document result markup, the
bulk-add action for matching results, and an accessible live status message. It
does not create Documents, create Transmissions, create inclusion relationships,
or alter governance state.

The enhanced page also stores the selected list in session-scoped browser
storage. If a JavaScript-enabled fallback navigation or browser refresh occurs,
the selected list is restored before rendering cards and hidden submission
fields. Relationship labels and public notes already entered on selected cards
are captured before each search and restored with the selected Document order.

The non-JavaScript fallback remains available through the `noscript` multiline
identifier field. Server-side creation remains authoritative in both enhanced
and fallback paths.

## Draft Lifecycle Persistence

The repeated-search correction introduced session-scoped draft storage, but the
initial lifecycle cleared that storage when the administrator submitted the
Create Transmission form. That was too early: if server-side validation rejected
the request, the administrator's selected Documents, relationship labels, and
public notes had already been discarded by the browser.

The intake form now persists the current selected-Document draft while the
request is submitted. Validation failures therefore leave the session-scoped
draft available for restoration when the administrator returns to the intake
form. Draft storage is cleared only after confirmed successful Transmission
creation, on the redirected Transmission Management detail page.

Relationship labels and public notes are also persisted continuously as the
administrator edits selected cards. The selected Documents, display order,
relationship labels, public notes, selected count, and hidden canonical
submission fields are restored after a refresh from the same
`selectedDocuments` collection.

Manual verification covers:

- adding two Documents and refreshing, with both selected Documents restored;
- editing a relationship label and public note, then refreshing, with both
  edits restored;
- submitting an invalid Transmission, with the draft still available after
  validation failure;
- successfully creating a Transmission, then opening a new intake form with
  zero selected Documents.

## Bulk-Control Functional Fix

The deployed bulk controls rendered correctly but did not initialize. The
rendered script contained a malformed JavaScript template literal in the
selected-card renderer, so the browser stopped evaluating the script before
attaching either the Add Selected Documents handler or the pasted-identifier
handler.

The intake page now uses one `initializeTransmissionDocumentSelection()`
initializer, runs it after the DOM is available, and keeps one ordered
`selectedDocuments` collection as the source of truth. The selected list,
selected count, disabled search-result checkboxes, remove controls, and hidden
canonical submission fields are all re-rendered from that collection.

The repaired controls are:

- `transmission-document-add-selected`, which bulk-adds checked search results
  in visible result order;
- `transmission-document-add-pasted`, which parses one pasted Document
  Identifier per line, ignores blank lines, reports duplicates, resolves
  identifiers through an authenticated Published Document lookup, and then adds
  only eligible published Documents with their metadata.

The pasted lookup does not create Documents, does not use optional external
references as the primary identity, and does not weaken server-side validation.
Manipulated requests are still checked authoritatively during Transmission
creation.

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

Bulk-selection tests cover multi-result search output, checkbox result
selection, one-action bulk addition, selected-order preservation, duplicate
prevention hooks, searching by Document Identifier, searching by title and
summary metadata, pasted identifier submission, invalid pasted identifier
handling, exact JavaScript control IDs, non-submit button types, DOM-ready
initialisation, hidden-field rendering, pasted identifier metadata lookup, and
continued compatibility with the post-creation inclusion workflow.

Repeated-search tests cover the non-reloading search endpoint, selected-state
persistence in session-scoped browser storage, restoration before card
rendering, preservation of relationship labels and public notes, hidden-field
reconstruction, selected-count reconstruction, and duplicate-prevention
resynchronisation after search results are replaced.

Draft lifecycle tests cover continuous relationship-label and public-note
persistence, submit-time draft retention for validation failure, and
success-page cleanup after confirmed Transmission creation.

Manual smoke-test coverage verifies that checking multiple search results and
using Add Selected Documents updates the selected count and hidden canonical
fields, that pasted DOC identifiers resolve to selected Document cards, that
Remove updates the same state, and that final submission creates the expected
governed inclusion relationships.

Additional repeated-search smoke testing verifies that a selected Document
remains visible after searching for another Document, that the second Document
can be added without losing the first, and that the final submitted hidden
fields preserve both selected Document Identifiers in order.
