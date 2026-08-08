# CDE Platform Stage 53 — Apple Mail Mailbox (.mbox) Authoritative Mailbox Preservation

## Purpose

CDE Platform Stage 53 introduces authoritative preservation of Apple Mail
mailbox archives (`.mbox`) while reusing the existing governed preservation
architecture. The mailbox archive itself remains the authoritative preserved
source; contained messages are governed projections derived from the preserved
mailbox bytes. Attachments of contained messages are preserved through the
existing Stage 49 preservation architecture.

This stage extends Stage 49. It reuses the existing preservation service,
relationship registry, Published Document lifecycle, identity model, hashing
model, provenance model, and verification model unchanged.

## Implementation

- The mailbox archive is already preserved byte-for-byte as a Published
  Document. Stage 53 extends the intake preservation gate to `.mbox`
  containers: after the mailbox is stored, each parsed message with attachments
  has its exact RFC 5322 byte range recovered from the preserved `.mbox` file
  (the mbox `"From "` separator is excluded).
- Each message's attachment payloads are extracted via the existing
  `extract_email_attachment_payloads` extractor (no second MIME parser).
- Each attachment occurrence is preserved through the unchanged Stage 49
  `preserve_attachment_bytes` / `record_attachment_failure` primitives.
- A new `preserve_mbox_message_attachments` function handles one contained
  message; the intake gate iterates messages and isolates per-message failures
  so one malformed message does not discard siblings.
- A new `list_archive_attachments` query helper enables archive-level
  relationship enumeration (via the existing `source_archive_identifier` index)
  for the Stage 50 administrative navigation.

## Provenance Hierarchy

- `source_archive_identifier` = archive (mailbox) intake_id;
- `source_email_object_id` = `f"{archive_intake_id}:message:{message_index}"`;
- `source_email_kind` = `"mailbox_message"`;
- `source_pathway` = `"mbox_message"`;
- `source_attachment_identifier` = `f"mime-part:{mime_part_index}"`;
- `source_message_identifier` = RFC 5322 Message-ID where present.

The same attachment bytes in two different mailbox messages remain distinct
source occurrences because the identity seed incorporates the per-message
`source_email_object_id`.

## Zero-byte and Embedded-message Policy

Every source-reported attachment occurrence remains governably represented:

- a non-empty payload is preserved as an independent Published Document;
- an embedded `message/rfc822` attachment is preserved opaquely as exact bytes;
- a zero-byte occurrence is recorded as a failed relationship row with reason
  `email_attachment_empty_payload`.

## Lifecycle and Public Boundary

Every preserved attachment starts in `pending`. No auto-publish. No Canonical
Record. No semantic classification.

Stage 50 administrative navigation lights up for mbox containers via the
archive-level enumeration. No public-route changes.

## Backfill

`scripts/backfill_email_attachment_preservation.py` now supports `.mbox`
containers via `--intake-id` targeting, using per-message byte-range recovery
and the archive-level idempotency check. Dry-run is strictly write-free.

## Governance Statement

Objects remain independent. Relationships preserve context. This stage changes
neither Canonical Record governance nor the meaning of publication, provenance,
hashing, verification, or source-document relationships.
