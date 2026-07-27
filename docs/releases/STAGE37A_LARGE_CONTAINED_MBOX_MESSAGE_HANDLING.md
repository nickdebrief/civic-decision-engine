# Stage 37A / CDE v13.0.10 — Large Contained MBOX Message Handling

The Civic Decision Engine can now process large individual messages within streamed MBOX archives using bounded file-backed parsing.

The original mailbox remains authoritative. Large contained messages are indexed by byte range, hashed incrementally, and presented through bounded safe previews without decoding or publishing attachment payloads independently. Archive and per-message limits remain separate and explicitly enforced.

## Purpose

Stage 37 proved the large-MBOX streaming route: a real Apple Mail archive could be uploaded to protected temporary storage, hashed incrementally, and brought to validation. Validation then exposed a narrower boundary: one contained message exceeded the parser's ordinary in-memory message threshold.

Stage 37A addresses that contained-message boundary without raising the ordinary synchronous Document Intake limit, without changing the 1 GB streaming archive limit, and without turning contained messages or attachments into independent governed objects.

## Root Cause

The Stage 37 file-backed mailbox parser still accumulated the current contained message into a `bytearray` before RFC 5322 parsing. The existing per-message limit was 5 MiB and applied to raw contained-message bytes. When a genuine mailbox contained an attachment-heavy or otherwise unusually large message, the parser correctly failed closed with `document_intake_mbox_message_too_large`.

The administrative error response was also ambiguous because it reported the configured archive maximum while the failure was actually a contained-message limit.

## Limit Model

Stage 37A separates the relevant limits:

- synchronous Document Intake upload limit: 25 MB by default;
- streaming MBOX archive limit: 1 GB by default;
- ordinary MBOX in-memory contained-message threshold: 5 MiB;
- streaming hard contained-message maximum: 128 MiB;
- bounded large-message preview/index window: 512 KiB.

The synchronous MBOX parser remains conservative and uses the in-memory threshold. The streaming file-backed parser can accept a contained message above that threshold when it remains within the hard per-message maximum.

## File-Backed Parsing

For ordinary contained messages, CDE continues to use the existing in-memory RFC 5322 projection path.

For large contained messages in the streaming parser, CDE records the source file path and message byte range, then:

- computes the contained-message SHA-256 digest by reading the byte range incrementally;
- reads only a bounded prefix for header, preview, and search projection;
- preserves message index, byte start, byte end, separator offset, separator text, and raw message size;
- marks the projection with `preview_mode = file_backed_bounded`;
- records `preview_truncated = true`;
- records bounded parser warnings explaining that the projection is file-backed and preview-limited.

The complete message remains part of the authoritative MBOX archive.

## Attachment Treatment

Attachments remain metadata-only. Stage 37A does not decode or publish large attachment payloads independently, does not create governed documents for attachments, and does not add attachment download routes. Where attachment metadata can be identified from the bounded projection, it is retained for inspection and discovery.

If complete payload sizing would require unbounded decoding, the source archive remains authoritative and the bounded projection remains intentionally limited.

## Search And Preview

Search uses public-safe bounded fields:

- subject;
- From, Sender, Reply-To, To, and CC;
- Message-ID, In-Reply-To, and References;
- bounded plain-text preview;
- bounded sanitised HTML text;
- attachment filenames and media types;
- parser warnings.

Search does not index BCC, full raw headers, attachment contents, filesystem paths, raw parser internals, or unbounded message bodies.

Public mailbox message detail now exposes message size, byte range, contained-message digest, preview mode, preview truncation status, attachment count, and parser warnings. Preview truncation does not imply that source content is missing; it means the public projection is intentionally bounded.

## Error Payloads

`document_intake_mbox_message_too_large` now reports message-level details when available:

- `message_index`;
- `message_start_byte`;
- `message_size_bytes`;
- `configured_message_maximum_bytes`;
- `configured_archive_maximum_bytes`;
- `document_created = false`.

This distinguishes a contained-message failure from a full archive size failure.

## Governance Invariants

Stage 37A does not change the governed object model. The full `.mbox` remains the Document. The Document Identifier and SHA-256 belong to the full original archive. Contained-message digests are projection metadata only and do not create independent governed identities.

The release does not change lifecycle states, publication rules, associations, collections, transmissions, public eligibility, authorization, storage semantics, or existing public URLs.

## Tests

Focused tests cover large plain-text messages, large HTML messages, large attachment-heavy messages, file-backed preview mode, preview truncation, incremental contained-message digest calculation, byte-range preservation, message order, metadata-only attachments, hard per-message limit errors, corrected administrative error payloads, exact hard-limit acceptance, public message detail fields, and no document creation after failure.

Regression tests cover Stage 37 streaming ingestion, Stage 36 MBOX archive support, Stage 35A RFC 5322 `.eml`, Stage 35B Outlook `.msg`, Stage 35C Apple Mail `.emlx`, and the full test suite.

## Intentional Exclusions

Stage 37A does not implement automatic contained-message promotion, independent attachment downloads, attachment extraction, complete mboxcl `Content-Length` semantics, direct Apple Mail package upload, PST or OST support, mailbox repair, background queues, resumable uploads, or unbounded message parsing.
