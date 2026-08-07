# CDE Platform Stage 51 — Standalone Outlook MSG Attachment Preservation

## Purpose

CDE Platform Stage 51 extends the Stage 49 independent attachment preservation
model to standalone Microsoft Outlook `.msg` intake documents. Standalone
`.msg` documents previously stopped at the Stage 35B attachment metadata layer;
they now produce the same governed preservation outcomes already supported for
RFC 5322 `.eml` messages.

This stage is an extension of Stage 49. It reuses the existing preservation
service, relationship registry, Published Document lifecycle, identity model,
hashing model, provenance model, and verification model unchanged.

## Implementation

- A bounded MSG attachment extractor
  (`extract_outlook_msg_attachment_payloads`) reuses the existing Stage 35B
  compound-file helpers to surface each attachment's exact
  `__substg1.0_3701` stream bytes alongside its source-reported filename, MIME
  type, Content-ID, attachment index, and inline state.
- The MSG is parsed twice on purpose: the first pass (`parse_outlook_msg_metadata`)
  enforces Stage 35B validation and resource limits without changing the
  published metadata shape; the second pass re-derives the attachment groups so
  the exact bytes can be preserved. This is a deliberate scope boundary, not
  redundant work.
- A new preservation entrypoint (`preserve_outlook_msg_attachments`) mirrors
  `preserve_rfc5322_attachments` and records `source_pathway = "outlook_msg"`.
- Standalone `.msg` intake invokes preservation automatically after successful
  document storage. RFC 5322 `.eml` behaviour is unchanged.

## Zero-byte and Embedded-message Policy

Every source-reported attachment occurrence remains governably represented:

- a non-empty payload is preserved as an independent Published Document with an
  `Email attachment` relationship;
- an embedded message (`attach_method == 5`) is preserved opaquely as its
  attachment bytes and is never recursively expanded in Stage 51;
- a zero-byte occurrence cannot be admitted as a Published Document and is
  instead recorded as a failed relationship row with reason
  `email_attachment_empty_payload` so the occurrence is never silently lost.

## Lifecycle and Public Boundary

Every preserved attachment starts in the existing Published Document lifecycle
as `pending`. No child is automatically approved or published. No Canonical
Record is created. No semantic role or evidential classification is inferred.

Stage 50 administrative and public navigation lights up automatically once
relationship rows exist; no navigation model change is required.

## Backfill

`scripts/backfill_email_attachment_preservation.py` now supports standalone
`.msg` intake records in addition to RFC 5322 `.eml` records. Dry-run is
strictly write-free and idempotent. Historical PST/OST, Gmail, and IMAP backfill
remains intentionally non-speculative.

## Governance Statement

Objects remain independent. Relationships preserve context. This stage changes
neither Canonical Record governance nor the meaning of publication, provenance,
hashing, verification, or source-document relationships.
