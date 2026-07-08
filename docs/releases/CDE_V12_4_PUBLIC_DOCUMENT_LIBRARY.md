# CDE v12.4 — Public Document Library & Controlled Publication

## Objective

CDE v12.4 introduces the governed public visibility layer for documents that
have explicitly reached the Published lifecycle state. It extends the existing
Admin Document Intake and Approval Workflow; it does not replace or weaken
their authentication, private storage, transition, or audit boundaries.

## Publication Boundary

Administrative approval and public publication remain separate decisions.
Only a document whose **current** sidecar status is `published` is eligible for
the public library, detail page, or PDF download.

The following states remain private:

- Pending Intake;
- Under Review;
- Approved;
- Archived; and
- Rejected.

When a Published document is moved to Archived through the existing admin
workflow, it immediately ceases to be publicly listable, viewable, or
downloadable. The private artefact and lifecycle history remain retained.

## Public Routes

- `GET /documents` renders the Public Document Library.
- `GET /documents/{document_id}` renders published metadata, SHA-256,
  provenance, and download access.
- `GET /documents/{document_id}/download` serves the original PDF filename only
  after rechecking current Published status.

No public JSON API or private intake listing is introduced.

## Search

The `q` query parameter performs case-insensitive search across:

- title;
- institution/source;
- category; and
- reference identifier.

Search is applied only after private lifecycle states have been excluded.

## Filtering

The library supports exact, case-insensitive filters for institution and
category and a publication-year filter derived from the Published transition
timestamp. Filter options themselves are built only from Published documents,
so private metadata cannot leak through option lists.

## Individual Document Page

The detail page displays title, description, institution/source, category,
publication date, document date, SHA-256, optional reference identifier,
download action, and a concise provenance summary linking authenticated intake
to the explicit Published transition.

Internal notes, storage paths, status history, and private administrative
metadata are not rendered publicly.

## Download Security

Downloads do not trust the absolute path stored in metadata. The server
validates the SHA-256-shaped document identifier, verifies current Published
status, reconstructs the path beneath `CDE_DOCUMENT_INTAKE_ROOT`, confirms the
resolved path remains within that root, and verifies the PDF exists before
serving it.

Private, malformed, unknown, archived, and missing documents return the same
`public_document_not_found` response. No route serves files from non-Published
states.

## Governance Statement

The library and each document page state:

> Documents displayed in this library have been explicitly marked as Published
> through the administrative workflow. Publication indicates intentional public
> availability. Publication does not certify legal status, evidential truth, or
> external validation.

## Limitations

Publication provides controlled document visibility only. It does not validate
content, certify legal status or evidential truth, create or modify public
records, establish evidence relationships, change classifications, perform OCR
or indexing, or alter CREF methodology and governance outputs.

## Tests

Tests create fixtures in every lifecycle state and verify that only Published
documents appear in the library. They cover search across all declared fields,
institution/category/year filtering, detail rendering, provenance, publication
date, PDF download and filename, unknown identifiers, and page/download denial
for Pending Intake, Under Review, Approved, Archived, and Rejected documents.
Existing intake, upload, admin, and full regression suites remain mandatory.

## Preserved Behaviour

This stage changes no CREF or CREF 3.1 content, schema, migration, database
record, canonical verification hash, attachment hash, classification threshold,
evidence relationship, evaluation logic, governance methodology, or existing
record verification behavior. It introduces public visibility only for the
explicit Published lifecycle state.
