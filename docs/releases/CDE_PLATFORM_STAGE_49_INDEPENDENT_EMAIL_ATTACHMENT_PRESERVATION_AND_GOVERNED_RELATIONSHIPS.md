# CDE Platform Stage 49 — Independent Email Attachment Preservation and Governed Relationships

## Purpose

CDE Platform Stage 49 preserves successfully extracted email attachments as
independently addressable Published Document intake objects while retaining the
source email as a separate preserved communication.

## Implementation

- RFC 5322 MIME attachments are extracted in source order through existing
  bounded parser protections.
- Outlook, Gmail, and IMAP projection paths use the same preservation service
  where exact attachment bytes are already available.
- Each source occurrence receives a deterministic identity independent from its
  SHA-256 content hash.
- Exact bytes, SHA-256, SHA-512, MIME metadata, filename state, attachment index,
  inline state, source identifiers, extraction pathway, timestamp, and parser
  provenance are retained.
- Missing filenames receive a neutral deterministic display title without being
  represented as an original filename.
- Zero-byte attachments, inline parts, duplicate filenames, and embedded message
  payloads retain explicit source state.
- Failed occurrences remain visible without creating a false attachment
  Published Document link.

## Governed Relationship

The dedicated relationship type is `Email attachment`. It records:

```text
Email preservation object -> has attachment -> Published Document
```

The inverse public view is derived from the same row. The implementation does
not use or modify Record–Document Associations and does not reinterpret
`Supporting document`, `Source document`, or any Canonical Record relationship.

## Lifecycle and Public Boundary

Every attachment starts in the existing Published Document lifecycle as
`pending`. No child is automatically approved or published. Public source-email
links appear only after the attachment independently reaches `published`.
Administrative inspection remains authenticated and metadata-only.

No Canonical Record is created automatically. No semantic role, evidence status,
clinical type, investigative meaning, or authority is inferred from the
transmission relationship.

## APIs

Stage 49 adds authenticated metadata reads:

- `GET /api/admin/session/documents/{document_id}/email-attachments`
- `GET /api/admin/session/email-attachment-relationships/{relationship_id}`

The public relationship page is available only when both independent Published
Documents are public:

- `GET /email-attachment-relationships/{relationship_id}`

No metadata endpoint returns raw attachment bytes. Existing Published Document
download controls continue to govern file access.

## Backfill

`scripts/backfill_email_attachment_preservation.py` provides bounded, dry-run,
idempotent backfill for authoritative preserved RFC 5322 source bytes. Existing
archive relationships are not inferred speculatively.

## Data Change

Stage 49 introduces one narrowly scoped SQLite sidecar table for
Published-Document-to-email-preservation relationships. It is indexed by source,
attachment document, archive, relationship type, and source identity. No existing
table, migration history, Record–Document Association, Canonical Record, or
Published Document lifecycle row is rewritten.

## Governance Statement

Objects remain independent. Relationships preserve context. This stage changes
neither Canonical Record governance nor the meaning of publication, provenance,
hashing, verification, or source-document relationships.
