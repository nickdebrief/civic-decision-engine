# Stage 16F — Evidence Provenance

## Purpose

Stage 16F adds an Evidence Provenance layer to the read-only Admin Record
Evidence view. It describes the origin and source metadata of evidence
attachments currently linked to record targets by active `supports`
relationships.

## Relationship to Stage 16D and Stage 16E

Stage 16D Evidence Traceability answers which active evidence relationships
currently support each target.

Stage 16E Evidence Lineage answers how each target's evidence support history
developed over time.

Stage 16F Evidence Provenance answers where each currently referenced
attachment came from, when it was recorded or uploaded, and which targets
currently depend on it.

## Provenance Summary Fields

The Evidence Provenance summary displays:

- Total Attachments Referenced
- Total Active Support Relationships
- Total Provenance Records Available
- Attachments With Provenance
- Attachments Missing Provenance

## Attachment Provenance Fields

For each attachment referenced by active `supports` relationships, Stage 16F
displays:

- Attachment ID
- Attachment Title
- Source Label
- Created At
- Uploaded At
- Current Status
- Active Relationships
- Supported Targets

The current implementation uses existing safe metadata only. `Created At`
reflects the stored document date when present. `Uploaded At` reflects the
stored attachment upload timestamp.

## Supported Target Handling

Supported targets are listed from active `supports` relationships only.
Duplicate relationship rows may increase the active relationship count, while
the supported target list is de-duplicated by target identity.

## Active Relationship Rules

Active relationship counts include active `supports` relationships only.
Inactive, removed, deleted, or non-`supports` relationship rows do not
contribute to active provenance counts.

## Deleted and Inactive Handling

Deleted attachments are not treated as active support. Inactive relationships
are excluded from active provenance counts. Stage 16F does not expose file
contents, storage paths, stored filenames, or download links.

## Admin-Only Scope

Stage 16F is an admin-only evidence assessment layer. It does not add upload
functionality, public file access, public download routes, public evidence
pages, or mutation controls.

## Canonical Verification

Stage 16F does not change canonical verification hashes, public manifests,
schemas, record versioning, attachment storage, relationship storage, or Stage
11-15 deterministic progression logic.

## Example

For `Strike-LA-20260710-004`, an attachment supporting `Escalation Without
Response` is shown with its attachment ID, title, source label, stored document
date, upload timestamp, active relationship count, and supported target list.
