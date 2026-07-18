# CDE v12.22 — Governed Spreadsheet Artefact Support

## Purpose

CDE v12.22 extends the existing governed Document Intake and publication
workflow to support original spreadsheet artefacts as first-class Published
Documents. The primary acceptance case is
`Nick_Moloney_Member_Usage_Woodstock_2019.xls`.

Supported spreadsheet formats:

- XLS, Excel 97-2003 Workbook;
- XLSX, Excel Workbook.

Existing PDF, JPEG, PNG, M4A, MP3, and WAV support is preserved.

## Governance Boundary

A spreadsheet is an independently preserved public artefact with its own
identity, original bytes, SHA-256 digest, original filename, detected format,
detected MIME type, metadata, lifecycle history, publication provenance, and
public download route.

Spreadsheet support does not:

- convert the workbook to PDF, screenshot, CSV, or another surrogate format;
- execute formulas or macros;
- recalculate workbook contents;
- follow external workbook links, data connections, templates, images, scripts,
  or remote resources;
- automatically create Record-Document Associations;
- automatically create canonical records;
- alter linked canonical records, record verification hashes, archive
  collections, or collection memberships.

## Validation

Spreadsheet uploads use the same intake route and trust boundary as existing
published files. The server validates filename extension and byte/internal
structure before deriving the stored MIME type.

Accepted mappings:

- `.xls` -> XLS, `application/vnd.ms-excel`;
- `.xlsx` -> XLSX,
  `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`.

Legacy `.xls` files must be OLE Compound File containers with a plausible Excel
workbook stream and without rejected encrypted, macro, Word, or PowerPoint
streams. `.xlsx` files must be valid Office Open XML ZIP packages with workbook
entries, safe package paths, expected content types, bounded decompression
characteristics, and no macro project, embedded object package, external link,
or executable package part.

Browser-supplied MIME values do not override server-side detection. Extension
and detected format mismatches remain rejected.

## Metadata

Spreadsheet artefacts preserve the same governed metadata as other Published
Documents:

- title;
- institution/source;
- document date;
- category;
- Keywords;
- description;
- internal notes;
- reference identifier;
- visibility;
- original filename;
- file size;
- SHA-256;
- detected format and MIME type;
- lifecycle status and history.

Where safely obtainable, CDE records descriptive workbook metadata such as
workbook type, worksheet names, worksheet count, calculation mode, and hidden
sheet presence. This metadata is non-authoritative discovery context only and
does not overwrite administrator-entered metadata.

## Public Presentation and Download

Published spreadsheet detail pages display governed metadata, Publication
Provenance, Publication Pathway, SHA-256, workbook metadata where available, and
an explicit original-file download action.

CDE does not embed or preview Excel content in this stage. Downloads use the
original preserved bytes, server-derived MIME type, `Content-Disposition:
attachment`, and `X-Content-Type-Options: nosniff`.

## Search, Associations, and Collections

Spreadsheet artefacts are searchable through the existing
`build_document_search_text()` helper by governed metadata, Keywords, reference
identifier, original filename, detected format, media family, and safely
extracted worksheet names.

Published spreadsheets remain ordinary Published Documents for governed
Record-Document Associations and Archive Collection memberships. They are not
absorbed into canonical records, public associations, or collections.

## Preserved Behaviour

This stage does not change:

- document lifecycle states or transitions;
- approval/publication separation;
- original-byte preservation;
- SHA-256 semantics;
- PDF, JPEG, PNG, M4A, MP3, or WAV validation;
- Public Document Library routes, search, filters, or ordering;
- Publication Provenance or Publication Pathway semantics;
- canonical record verification hashes;
- record evidence, Conditions, Signals, or findings;
- Record-Document Association storage, lifecycle, or visibility;
- Archive Collection or membership governance;
- authentication and signed-session behaviour;
- public/private visibility boundaries.

## Validation Results

Focused tests cover valid XLS and XLSX intake, MIME and extension recognition,
exact-byte and SHA-256 preservation, lifecycle publication, public page
rendering, attachment download headers, public search by spreadsheet metadata,
Record-Document Association compatibility, Archive Collection membership
compatibility, invalid workbook rejection, macro/encrypted/unsafe package
rejection, and regression coverage for PDF, JPEG, PNG, M4A, MP3, and WAV intake.
