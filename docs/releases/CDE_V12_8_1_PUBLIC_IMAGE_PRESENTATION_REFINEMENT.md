# CDE v12.8.1 — Public Image Presentation Refinement

## Purpose

CDE v12.8.1 is a narrow presentation refinement following CDE v12.8 — Image
Document Intake. It addresses two issues observed during live validation of the
first published JPEG record:

- the public `View image` action used the same endpoint as the original-image
  download action and therefore triggered browser save/download behaviour; and
- the administrative lifecycle-history table could become too condensed,
  causing timestamp and lifecycle status values to wrap aggressively.

## Relationship to v12.8

CDE v12.8 introduced PDF, JPEG, and PNG intake through the existing governed
document lifecycle. CDE v12.8.1 does not reopen that implementation. It keeps
upload validation, byte preservation, SHA-256 provenance, lifecycle states,
actor attribution, publication boundaries, admin previews, and Public Document
Library eligibility unchanged.

## Inline Image Viewing vs Original-Image Downloading

Published JPEG and PNG records now have distinct public behaviours:

- `GET /documents/{document_id}/view` serves the original image bytes for
  inline browser viewing.
- `GET /documents/{document_id}/download` serves the original image bytes as an
  attachment for explicit download.

The public detail page uses the inline view route for the image element and
for the `View image` action. The `Download original image` action continues to
use the download route.

PDF records continue using the existing download route and are not served by
the image-view route.

## Response Behaviour

For published JPEG images:

- inline view: `Content-Type: image/jpeg`, `Content-Disposition: inline`
- download: `Content-Type: image/jpeg`, `Content-Disposition: attachment`

For published PNG images:

- inline view: `Content-Type: image/png`, `Content-Disposition: inline`
- download: `Content-Type: image/png`, `Content-Disposition: attachment`

Both routes return the exact original uploaded bytes and use server-derived
document metadata. Client-supplied MIME values do not influence public response
headers.

## Published-Only Access

Both the inline view route and the original-image download route enforce the
existing Published-only public access boundary. Pending, Under Review,
Approved, Rejected, Archived, unknown, and malformed document identifiers
remain unavailable through public image routes.

No storage path is rendered into the public HTML.

## Lifecycle-History Table Readability

The Document Intake Review status-history table now includes a responsive
wrapper and semantic column styling hooks for:

- timestamp;
- previous status;
- new status;
- actor; and
- note.

The timestamp, status, and actor columns receive practical minimum widths on
normal desktop layouts, while the note column remains flexible. On smaller
screens, the table can scroll horizontally rather than compress lifecycle
labels into unreadable fragments.

This change is limited to the existing Document Intake Review lifecycle-history
table. It does not introduce broader audit-table standardisation.

## Preserved Boundaries

CDE v12.8.1 does not change:

- supported upload formats;
- PDF/JPEG/PNG validation;
- magic-byte detection;
- extension/type correspondence;
- SHA-256 calculation;
- exact-byte preservation;
- sidecar metadata;
- upload-size limits;
- authenticated admin previews;
- lifecycle states or transitions;
- actor attribution;
- transition notes;
- authentication or session behaviour;
- signed-in identity display;
- Public Document Library listing, search, or filters;
- metadata rendering;
- provenance summaries;
- storage paths;
- public/private visibility boundaries;
- PDF download behaviour;
- database schema;
- evidence handling;
- verification logic; or
- footer navigation.

## Validation Results

Focused validation covers:

- published JPEG and PNG inline image viewing;
- inline `Content-Disposition` behaviour;
- published JPEG and PNG attachment download behaviour;
- exact-byte comparison for both view and download routes;
- Published-only access enforcement;
- archived and unpublished image denial;
- PDF exclusion from the public image-view route;
- public detail route separation;
- absence of storage paths from rendered HTML;
- lifecycle-history wrapper and semantic column hooks;
- preservation of lifecycle labels, actor values, and transition notes; and
- PDF and Public Document Library regression coverage.

Validation commands for this release:

- `python3 -m unittest tests.test_admin_document_intake`
- `python3 -m unittest tests.test_public_document_library`
- `python3 -m unittest tests.test_admin_session`
- `python3 -m unittest tests.test_admin_navigation_console`
- `python3 -m unittest tests.test_public_footer_administration_link`
- `python3 -m unittest discover -s tests`
- `git diff --check`
- conflict-marker check
- public inline-image header check
- public attachment-download header check
- unpublished image access check
- exact-byte comparison for both image routes
- PDF regression check
- lifecycle-history markup/class check
