# CDE v12.28 — Public Document Preview Enhancements

## Purpose

CDE v12.28 adds compact previews to the Public Document Library so public users
can recognise published artefacts before opening each detail page.

A preview helps users recognise a governed document without becoming a new
governed object.

The preview is a presentation of an existing governed document, not a new
governed artefact.

## Supported Preview Types

The initial preview component supports:

- image thumbnails for published JPEG and PNG documents;
- fallback preview cards for PDF documents;
- fallback preview cards for Rich Text Format documents;
- fallback preview cards for spreadsheet artefacts;
- fallback preview cards for audio artefacts;
- a generic file fallback for unknown legacy metadata.

The helper is presentation-only and uses existing Published Document metadata,
media helpers, and public document routes.

## Image Thumbnail Behaviour

Published image documents render a compact thumbnail in the Public Document
Library Preview column. The thumbnail uses the existing public file-view route
and links back to the Published Document detail page, preserving the document
page as the primary governance context.

The thumbnail is constrained with fixed maximum display dimensions, preserves
aspect ratio, uses `object-fit: contain`, and does not create derived files,
background jobs, thumbnail storage, or alternate SHA-256 values.

## Fallback Behaviour

Non-image media render a compact visible fallback with media text and a
descriptive action link:

- Open PDF document;
- Open Rich Text document;
- Open Spreadsheet document;
- Open Audio document;
- Open Published Document.

Fallbacks do not attempt to render PDF pages, RTF content, spreadsheet cells, or
audio waveforms inline.

## Link Behaviour

Every preview links to the existing Published Document detail page. Preview
links are generated from internal document identifiers and do not expose storage
paths, accept user-supplied return URLs, or introduce a new download route.

Existing public document detail, view, and download routes remain unchanged.

## Accessibility

Image thumbnails include document-specific alt text such as `Preview of ...`.
Fallback cards expose visible media labels and descriptive action text. The
Preview column has a semantic table header, focus styles remain visible, and
the table remains keyboard navigable through native HTML.

## Responsive Design

The Public Document Library retains its server-rendered table with deliberate
horizontal scrolling on narrow screens. Preview cells use bounded dimensions so
long titles, references, and descriptions remain readable without overlap.

## Error Handling

If an otherwise public document cannot resolve its file for preview, the library
renders `Preview unavailable` and still links to the Published Document page.
One failed preview does not break the table and internal filesystem paths are
not exposed.

## Performance Limitation

This release uses constrained browser rendering for image thumbnails. It does
not introduce image-processing dependencies, generated thumbnails, derived-file
storage, thumbnail cache invalidation, external media services, or asynchronous
preview jobs.

## Reuse Strategy

The preview renderer lives in a small shared helper so it can later be reused by
the Public Archive Explorer, Public Traceability Map, Association pages,
Collection pages, or future governed public transmission views without
duplicating media mapping logic.

## Preserved Behaviour

This release does not change:

- document identity;
- provenance;
- lifecycle states;
- publication rules;
- public eligibility;
- storage;
- download behaviour;
- file integrity;
- SHA-256 semantics;
- verification behaviour;
- existing public URLs;
- governance semantics.

No derived governed artefact is created.

## Validation Results

Focused tests cover the Preview column, preserved Reference Identifier column,
image thumbnails for JPEG and PNG, fallback previews for PDF, Rich Text,
Spreadsheet, Audio, and generic File metadata, missing-file fallback behaviour,
accessibility and responsive markup, and confirmation that preview rendering
does not mutate lifecycle, reference, SHA-256, or status history.

Regression tests cover the Public Document Library, public document detail and
download routes, RTF support, spreadsheet support, audio support, v12.26 Archive
UX tests, v12.27 Traceability tests, and the full test suite.
