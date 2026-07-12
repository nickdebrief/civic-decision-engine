# CDE v12.8 — Image Document Intake

## Purpose

CDE v12.8 extends the existing authenticated Admin Document Intake workflow so
supported image records can enter the same controlled administrative lifecycle
already used for PDF records.

This stage supports incremental intake of image records such as the Strike
001–838 archive over time without creating a separate image-management system.

## Supported Formats

Supported upload formats are:

- PDF: `.pdf`
- JPEG: `.jpg`, `.jpeg`
- PNG: `.png`

Extension validation is case-insensitive. Unsupported extensions, missing
extensions, renamed executables, SVG, HTML, GIF, WebP, BMP, TIFF, and other
formats are rejected.

## Server-Side Type Validation

CDE v12.8 validates uploaded bytes using server-inspected file signatures:

- PDF files must begin with the PDF signature.
- JPEG files must begin with the JPEG signature.
- PNG files must begin with the PNG signature.

The detected type must match the filename extension mapping:

- `.pdf` → PDF
- `.jpg` / `.jpeg` → JPEG
- `.png` → PNG

Browser-supplied MIME types are not trusted for acceptance.

## Preservation of Original Bytes

Uploaded files are stored exactly as received. CDE v12.8 does not resize,
crop, rotate, optimise, recompress, re-encode, strip metadata, alter colour
profiles, convert formats, generate thumbnails, or create replacement source
files.

The SHA-256 digest identifies the exact original uploaded bytes.

## Document-Type Metadata

Each new intake sidecar stores server-derived document type metadata:

- `pdf`
- `jpeg`
- `png`

Existing PDF records remain readable. Records without explicit document-type
metadata are treated as PDF using the existing sidecar and storage conventions.
No database migration is required because Admin Document Intake uses
sidecar-based metadata.

## Authenticated Actor Attribution

Image upload and lifecycle actions continue to derive actor identity from the
verified signed administrator session introduced in CDE v12.7. Actor identity
is not accepted from form fields, query parameters, request bodies, filenames,
image metadata, or client-supplied headers.

The existing `Signed in as: <username>` indicator remains unchanged.

## Lifecycle Reuse

Image records use the existing lifecycle without image-specific states:

- Pending Intake
- Under Review
- Approved
- Published
- Rejected
- Archived

The document type does not alter transition rules, notes, timestamps, actor
attribution, status-history rendering, or lifecycle restrictions.

## Private/Public Boundaries

Uploading an image does not create or modify a public record. Pending,
Under Review, Approved, Rejected, and Archived images remain unavailable
through public document routes.

Only records explicitly marked Published by an authenticated administrator are
eligible for the Public Document Library.

The admin review disclaimer now states:

> This upload has not created or modified any public record. Approval does not
> publish or expose the document. Public availability occurs only after an
> authenticated administrator explicitly marks the document as Published.

## Authenticated Admin Previews

Validated JPEG and PNG records display a restrained preview on the authenticated
intake review page. Preview bytes are served only through an authenticated
admin route, preserve the original image aspect ratio, and do not expose a
public URL before publication.

PDF preview rendering is not introduced in this stage.

## Public Document Library Behaviour

Published JPEG and PNG records appear in the existing Public Document Library
alongside published PDFs. Search, filters, metadata display, provenance
summary, publication date, category, institution/source, description, and
reference identifier behaviour are shared.

Public detail pages display:

- `Document Format: PDF`
- `Document Format: JPEG`
- `Document Format: PNG`

Published image detail pages include a restrained inline image element and
links to view or download the original image. Public downloads return exact
stored bytes with server-derived media types:

- PDF: `application/pdf`
- JPEG: `image/jpeg`
- PNG: `image/png`

## Storage Behaviour

The existing SHA-256-addressed intake storage model is preserved. New files use
canonical stored extensions:

- `pending-<sha256>.pdf`
- `pending-<sha256>.jpg`
- `pending-<sha256>.png`

Pending files are not placed in public static directories. Existing PDF files
are not migrated or rewritten.

## Upload-Size Controls

CDE v12.8 preserves the existing configurable intake size limit:

- environment variable: `CDE_DOCUMENT_INTAKE_MAX_BYTES`
- default: 25 MiB

The same limit applies to PDFs, JPEGs, and PNGs. Oversized files are rejected
before intake completes.

## Exclusions

CDE v12.8 does not implement:

- bulk image upload;
- ZIP or folder import;
- automatic Strike-number extraction;
- automatic title or metadata generation;
- EXIF extraction or removal;
- OCR;
- image transcription;
- AI image analysis;
- automatic image descriptions;
- image conversion or optimisation;
- resizing, rotation, or cropping;
- thumbnails;
- galleries, albums, collections, or lightboxes;
- image-to-record conversion;
- external image hosting;
- image similarity detection;
- changes to CREF;
- changes to the `/records` archive;
- verification or evidence hash changes;
- authentication or session changes; or
- audit-table redesign.

## Validation Results

Focused validation covers:

- existing PDF intake and public download regression;
- valid JPG, JPEG, PNG, and uppercase-extension intake;
- server-side type detection and extension/type mismatch rejection;
- malformed, renamed, unsupported, empty, and oversized uploads;
- original byte preservation and exact SHA-256 verification;
- authenticated actor attribution;
- unchanged lifecycle transitions;
- private state exclusion from public routes;
- authenticated image previews;
- public image rendering and media types; and
- unchanged public footer navigation.

Validation commands for this release:

- `python3 -m unittest tests.test_admin_session`
- `python3 -m unittest tests.test_admin_document_intake`
- `python3 -m unittest tests.test_admin_navigation_console`
- `python3 -m unittest tests.test_public_document_library`
- `python3 -m unittest tests.test_public_footer_administration_link`
- `python3 -m unittest discover -s tests`
- `git diff --check`
- conflict-marker check
- unsupported-format search
- client-supplied actor-field search
- unauthenticated image-preview check
- unpublished public-image access check
- exact-byte SHA-256 verification
- public media-type verification
