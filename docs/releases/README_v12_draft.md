# Civic Decision Engine v12 Draft README

<p align="center">
  <img src="./assets/v12-seal.png"
       alt="Civic Decision Engine v12"
       width="320">
</p>

This is a draft release README for Civic Decision Engine v12. It is preparation
material only and does not replace the repository root `README.md`.

## Overview

The Civic Decision Engine (CDE) records civic and institutional decision patterns
as structured public records. Records are intended to remain verifiable,
archivable, and machine-readable over time.

Canonical records remain the authoritative layer. Verification hashes are derived
from the canonical record fields only. Derived metadata, manifests, attachment
metadata, and semantic infrastructure do not replace or alter canonical record
verification.

## What v12 Introduces

v12 introduces attachment infrastructure for referenced evidence artifacts. The
attachment layer is additive and independent from canonical record hashing.

The current v12 work establishes:

- A `record_attachments` schema.
- Immutable local storage helpers under `/data/attachments/{reference}/...`.
- Independent SHA-256 hashing for attachment bytes.
- Admin-only upload infrastructure protected by `CDE_ADMIN_TOKEN`.
- Public manifest expansion with safe attachment metadata.
- Optional source-document date metadata.
- Upload privacy hardening before operational enablement.

## Attachment Architecture

Attachments are referenced artifacts associated with canonical records. They have
their own lifecycle metadata and independent integrity hashes.

Attachment bytes are immutable once stored. Each attachment record tracks its
filename, content type, byte size, SHA-256 hash, visibility, redaction status,
version metadata, and upload metadata. Storage paths are internal implementation
details and are not exposed in public manifests.

Attachments do not affect:

- Canonical record verification hashes.
- Canonical serialization.
- Record versioning.
- Semantic indexing.
- Public record creation behavior.

## Document Dates

v12 adds optional evidentiary date metadata for attachments:

- `document_date`
- `document_date_precision`

These fields describe the date of the source artifact itself, separate from the
record's `generated_at`, the record's `exported_at`, and the attachment's
`uploaded_at`.

Allowed precision values are:

- `day` for `YYYY-MM-DD`
- `month` for `YYYY-MM`
- `year` for `YYYY`
- `unknown` when no document date is known

Document dates are metadata only. They do not affect canonical record hashes,
attachment byte hashes, canonical serialization, or record versioning.

## Manifest Expansion

Record manifests include an `attachments` array. When no public attachments are
available, the array is present and empty.

Only latest public attachments that are not deleted and not withheld appear in
public manifests. Private, withheld, and deleted attachments are excluded.

Manifest attachment entries expose safe metadata only:

- Attachment ID and version
- Original filename
- Content type
- File size
- Independent SHA-256 hash
- Visibility and redaction status
- Title, description, and source label
- Document date metadata
- Upload timestamp
- `download_url: null`

Public attachment downloads are not implemented in the current v12 draft.

## Verification Integrity

Canonical record verification remains unchanged.

v12 attachment metadata is explicitly non-canonical. Attachment hashes are
independent SHA-256 hashes over attachment bytes only. Manifest attachment fields
do not participate in canonical record verification.

Existing recomputation instructions for record verification remain authoritative
and unchanged.

## Privacy Model

The current attachment model is conservative by default:

- Admin upload requires `CDE_ADMIN_TOKEN`.
- Admin routes remain disabled when `CDE_ADMIN_TOKEN` is unset.
- Upload requests must include `X-CDE-Admin-Token`.
- Token values must not be logged or returned in error responses.
- Public manifests exclude private, deleted, and withheld attachments.
- Public manifests do not expose `storage_path`, `stored_filename`, or raw
  filesystem paths.
- Attachment content is not publicly downloadable.
- No public upload route exists.

Upload hardening includes a configurable maximum upload size through
`CDE_ATTACHMENT_MAX_BYTES` and a conservative MIME allowlist:

- `application/pdf`
- `image/jpeg`
- `image/png`
- `text/plain`

## Continuity Preservation

v12 is designed to preserve continuity with earlier CDE records. Canonical
records remain authoritative, existing verification hashes remain valid, and
attachments are treated as referenced artifacts rather than changes to the record
itself.

The attachment layer is additive. It supports future archival and evidentiary
work without changing the meaning or integrity of existing records.

Continuity is not created by a single document.

It emerges from the relationship between records, evidence, and time.

A record may identify a condition.

Evidence may preserve the events that produced it.

Chronology preserves the sequence that connects them.

By preserving document dates independently from upload dates and record
generation dates, v12 provides a foundation for maintaining evidentiary
continuity across long-running civic records.

## Implemented v12 Stages

### Stage 1 - Attachment Schema and Storage

Implemented additive `record_attachments` schema support, attachment SHA-256
hashing, immutable storage path helpers, and path safety tests.

### Stage 2 - Admin Upload Infrastructure

Implemented admin attachment upload infrastructure, metadata insertion,
immutable file storage, byte hashing, and `CDE_ADMIN_TOKEN` authentication.

### Stage 3 - Manifest Expansion

Expanded record manifests to include safe attachment metadata while preserving
canonical record verification behavior.

### Stage 3A - Document Date Metadata

Added optional `document_date` and `document_date_precision` metadata for source
artifact dates.

### Stage 3B - Privacy Hardening

Added upload size limits, MIME allowlist validation, constant-time token
comparison, token-safe error responses, and privacy regression tests.

## Not Yet Implemented

The current v12 draft does not implement:

- Public attachment downloads
- Public attachment serving
- Attachment search
- OCR
- PDF text extraction
- Semantic indexing of attachment content
- Attachment citation changes
- Public upload UI

## Roadmap

Future v12 work may include:

- Post-deploy verification before enabling operational admin uploads.
- Public serving rules for public, non-redacted attachments.
- Manifest `download_url` population after public serving exists.
- Stronger attachment lifecycle and version-management workflows.
- Additional administrative audit logging that avoids sensitive token exposure.
- Optional malware scanning or file-type verification before public serving.

Any future serving or discovery layer should remain additive and must not alter
canonical record verification.

## Active Development Status

This document describes the current v12 release preparation state. It should be
reviewed before replacing or updating the repository root README.

Operational admin uploads should remain disabled until deployment verification is
complete and `CDE_ADMIN_TOKEN` is intentionally configured in the deployment
environment.
