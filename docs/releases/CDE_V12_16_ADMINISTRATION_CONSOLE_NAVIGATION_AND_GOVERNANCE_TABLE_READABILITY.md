# CDE v12.16 — Administration Console Navigation and Governance Table Readability

## Purpose

CDE v12.16 is a narrowly scoped Administration Console presentation stage. It
improves authenticated administrator navigation and the readability of wide
governance tables without changing any governed lifecycle, publication,
evidence, hashing, storage, database, public route, or public/private
visibility behaviour.

## Relationship to Prior Stages

CDE v12.14 introduced governed Archive Collections.

CDE v12.15 introduced governed Intake Corrections and document reassignment for
confirmed archived intake metadata-document mismatches.

CDE v12.16 does not extend either governance model. It makes the existing
administrative surfaces easier to reach and inspect.

## Dashboard Navigation Changes

The authenticated Administration Console dashboard now presents first-class
summary cards for:

- Document Intake;
- Pending Intake;
- Review Queue;
- Intake Corrections;
- Administrative Audit;
- Record-Document Associations;
- Archive Collections;
- Record Evidence;
- Public Document Library.

The Document Intake card links to:

```text
/admin/document-intake#new-intake
```

The Intake Corrections card links to:

```text
/admin/intake-corrections
```

The existing shared Administration Console navigation remains intact.

## Governance Table Readability

The stage adds shared authenticated-admin table readability classes and
responsive wrappers for wide administrative tables. These changes preserve the
existing table content while improving the desktop and narrow-screen rendering
of long identifiers, timestamps, actors, status labels, notes, and history
state values.

The updated administrative table surfaces include:

- Document Intake management;
- Document Intake status history;
- Intake Corrections index;
- Intake Correction pathway;
- Administrative Audit;
- Archive Collections index;
- Archive Collection history.

The implementation preserves existing page-specific classes while adding shared
semantic hooks such as:

- `admin-table-scroll`;
- `admin-data-table`;
- `col-reference`;
- `col-title`;
- `col-filename`;
- `col-status`;
- `col-timestamp`;
- `col-actor`;
- `col-note`;
- `col-actions`.

## Archive Collection History State Details

Archive Collection history continues to render stored previous-state and
new-state JSON as read-only administrative state details.

The visible summaries now distinguish:

- View previous state;
- View new state.

The stored state JSON is escaped and wrapped safely. It is not rewritten,
normalised, truncated, or exposed publicly.

## Correction Pathway

The Intake Correction pathway remains read-only and continues to display the
authoritative stored correction history:

- timestamp;
- action;
- actor;
- previous and new correction state;
- note;
- source intake;
- destination intake.

The stage adds table wrappers and semantic column classes only. It does not
change correction lifecycle rules, correction execution, source intake
preservation, destination intake creation, duplicate detection, or SHA-256
handling.

## Security and Governance Boundaries

CDE v12.16 does not change:

- administrator authentication;
- session validation;
- actor attribution;
- client override protections;
- Document Intake lifecycle;
- Intake Correction lifecycle;
- Archive Collection lifecycle;
- association behaviour;
- publication rules;
- Public Document Library behaviour;
- Public Record Index behaviour;
- evidence handling;
- record verification;
- SHA-256 calculation;
- exact-byte document preservation;
- storage paths;
- database schema;
- public routes;
- public footer navigation;
- public/private visibility boundaries.

No private intake records, correction records, collection history, internal
notes, storage paths, credentials, session data, or administrative state were
made public.

## Tests Added or Updated

Added focused coverage in:

```text
tests/test_admin_console_navigation_and_table_readability.py
```

The focused tests verify:

- first-class dashboard cards for Document Intake and Intake Corrections;
- authenticated access requirements for admin pages;
- shared table readability classes for intake management;
- responsive status-history hooks;
- Intake Corrections index readability;
- Correction Pathway readability;
- Archive Collections index readability;
- Archive Collection history readability;
- Administrative Audit readability;
- ordinary duplicate detection remains unchanged;
- correction destination intakes still begin as Pending Intake.

## Validation

Required validation for this stage:

```text
python3 -m unittest tests.test_admin_console_navigation_and_table_readability
python3 -m unittest tests.test_governed_intake_corrections
python3 -m unittest tests.test_governed_archive_collections
python3 -m unittest tests.test_admin_document_intake
python3 -m unittest tests.test_admin_session
python3 -m unittest tests.test_admin_navigation_console
python3 -m unittest tests.test_admin_audit_traceability
python3 -m unittest tests.test_public_document_library
python3 -m unittest tests.test_public_record_document_association
python3 -m unittest tests.test_association_public_traceability
python3 -m unittest tests.test_public_association_index
python3 -m unittest tests.test_public_footer_administration_link
python3 -m unittest discover -s tests
git diff --check
```

A conflict-marker check and Python compile check should also be completed before
merge.

## Implementation Summary

CDE v12.16 improves administrative navigation and the readability of wide
authenticated governance tables. It is a presentation-only stage and introduces
no behavioural, lifecycle, publication, evidence, verification, database,
hashing, association, collection-membership, correction-execution, or
public-visibility changes.
