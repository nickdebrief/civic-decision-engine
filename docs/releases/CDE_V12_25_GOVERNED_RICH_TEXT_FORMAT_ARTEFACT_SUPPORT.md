# CDE v12.25 — Governed Rich Text Format Artefact Support

## Purpose

CDE v12.25 extends the existing governed Document Intake and publication
workflow to support original Rich Text Format artefacts as first-class
Published Documents.

Supported Rich Text format:

- RTF, Rich Text Format.

Existing PDF, JPEG, PNG, M4A, MP3, WAV, XLS, and XLSX support is preserved.

## Governance Boundary

An RTF file is an independently preserved public artefact with its own identity,
original bytes, SHA-256 digest, original filename, detected format, detected
MIME type, metadata, lifecycle history, publication provenance, and public
download route.

RTF support does not:

- convert the source file to PDF, HTML, DOCX, plain text, or another surrogate
  format;
- render RTF directly into public HTML;
- execute embedded content or invoke a local word processor;
- extract or index full RTF text;
- automatically create Record-Document Associations;
- automatically create canonical records;
- alter linked canonical records, record verification hashes, archive
  collections, or collection memberships.

## Validation

RTF uploads use the same intake route and trust boundary as existing published
files. The server validates filename extension and byte structure before
deriving the stored MIME type.

Accepted mapping:

- `.rtf` -> RTF, `application/rtf`.

Recognised client MIME variants:

- `application/rtf`;
- `text/rtf`;
- `application/x-rtf`.

Browser-supplied MIME values do not override server-side detection. The RTF
detector inspects the original bytes, tolerates a UTF-8 byte-order mark and
benign leading whitespace, confirms the expected `{\rtf` control header, rejects
empty files, rejects obvious binary masquerades, and requires a recognisable RTF
structure. Extension and detected format mismatches remain rejected.

## Original-Byte Preservation

The uploaded RTF remains the authoritative governed artefact. CDE calculates
SHA-256 from the original uploaded bytes, stores the original bytes unchanged,
and preserves the original filename according to existing filename-safety
policy.

No preview, conversion, normalisation, or text extraction replaces the original
artefact.

## Metadata and Public Presentation

RTF artefacts preserve the same governed metadata as other Published Documents:

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

Published RTF detail pages identify the artefact as Rich Text, display governed
metadata, Publication Provenance, Publication Pathway, SHA-256, and an explicit
original-file download action.

CDE does not attempt to render RTF as HTML in this stage. Downloads use the
original preserved bytes, server-derived MIME type, `Content-Disposition:
attachment`, and `X-Content-Type-Options: nosniff`.

## Search, Archive, Associations, and Collections

RTF artefacts are searchable through the existing
`build_document_search_text()` helper by governed metadata, Keywords, reference
identifier, original filename, detected format, and media family. No full RTF
content extraction is introduced.

Published RTF files appear in the Public Document Library and Public Archive
Explorer, including the Rich Text media filter. They remain ordinary Published
Documents for governed Record-Document Associations and Archive Collection
memberships.

## Preserved Behaviour

This stage does not change:

- document lifecycle states or transitions;
- approval/publication separation;
- original-byte preservation;
- SHA-256 semantics;
- PDF, JPEG, PNG, M4A, MP3, WAV, XLS, or XLSX validation;
- Public Document Library routes, search, filters, or ordering beyond adding
  the RTF format;
- Publication Provenance or Publication Pathway semantics;
- canonical record verification hashes;
- record evidence, Conditions, Signals, or findings;
- Record-Document Association storage, lifecycle, or visibility;
- Archive Collection or membership governance;
- authentication and signed-session behaviour;
- public/private visibility boundaries.

## Validation Results

Focused tests cover valid RTF intake, recognised MIME variants, exact-byte and
SHA-256 preservation, lifecycle publication, public page rendering, attachment
download headers, public search and Archive Explorer visibility, Record-Document
Association compatibility, Archive Collection membership compatibility, invalid
RTF masquerade rejection, extension/type mismatch rejection, unpublished access
boundaries, and regression coverage for PDF, JPEG, PNG, M4A, MP3, and WAV
intake.
