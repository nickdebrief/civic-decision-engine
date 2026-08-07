# CDE Platform Stage 52 — Standalone Apple Mail EMLX Attachment Preservation

## Purpose

CDE Platform Stage 52 extends the Stage 49 independent attachment preservation
model to standalone Apple Mail `.emlx` intake documents. Standalone `.emlx`
documents previously stopped at the Stage 35B attachment metadata layer; they now
produce the same governed preservation outcomes already supported for RFC 5322
`.eml` and standalone Outlook `.msg` messages.

This stage is an extension of Stage 49. It reuses the existing preservation
service, relationship registry, Published Document lifecycle, identity model,
hashing model, provenance model, and verification model unchanged.

## Implementation

- A bounded Apple Mail extractor (`extract_apple_emlx_attachment_payloads`)
  recovers the authoritative RFC 5322 message bytes from the `.emlx` wrapper by
  reusing the existing Stage 35B length-prefix, message-length, and
  trailing-plist validation. It then delegates attachment-byte extraction to the
  existing RFC 5322 extractor (`extract_email_attachment_payloads`). No second
  MIME parser is introduced.
- The `.emlx` is parsed twice on purpose: the first pass
  (`parse_apple_emlx_metadata`) enforces Stage 35B validation and resource
  limits without changing the published metadata shape; the second pass
  re-derives the RFC 5322 message region so the exact bytes can be fed to the
  existing extractor. This mirrors the deliberate two-pass design used for
  standalone MSG in Stage 51.
- A new preservation entrypoint (`preserve_apple_emlx_attachments`) mirrors the
  existing `.eml`/`.msg` entrypoints and records `source_pathway = "apple_emlx"`
  with the same `mime-part:<index>` source-occurrence identifier convention as
  RFC 5322 `.eml`.
- Standalone `.emlx` intake invokes preservation automatically after successful
  document storage. RFC 5322 `.eml` and standalone `.msg` behaviour is unchanged.

## Zero-byte and Embedded-message Policy

Every source-reported attachment occurrence remains governably represented:

- a non-empty payload is preserved as an independent Published Document with an
  `Email attachment` relationship;
- an embedded `message/rfc822` attachment is preserved opaquely as its exact
  attachment bytes and is never recursively expanded in Stage 52;
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
`.emlx` intake records in addition to `.eml` and `.msg`. The Stage 51.1
`--intake-id` targeting option supports `.emlx`. Dry-run is strictly write-free
and idempotent. Historical PST/OST, Gmail, and IMAP backfill remains
intentionally non-speculative.

## Governance Statement

Objects remain independent. Relationships preserve context. This stage changes
neither Canonical Record governance nor the meaning of publication, provenance,
hashing, verification, or source-document relationships.
