# Stage 37 / CDE v13.0.9 — Governed Streaming MBOX Ingestion

The Civic Decision Engine can now admit large MBOX mailbox archives through a dedicated governed streaming pathway.

Mailbox bytes are written incrementally to protected temporary storage while SHA-256 and size are calculated continuously. The archive is validated and indexed before atomic finalisation into ordinary Pending Intake. The existing 25 MB synchronous Document Intake limit remains unchanged.

## Purpose

Stage 36 introduced governed MBOX archive ingestion through the ordinary synchronous Document Intake route. That route remains intentionally bounded at the configured Document Intake upload limit, 25 MB by default. Real-world Apple Mail exports may be substantially larger, including the validated 412 MB export that motivated this stage.

Stage 37 adds a separate authenticated administrative path: Governed Streaming Mailbox Intake. It is not a general upload-limit increase and does not route ordinary small files through the streaming path.

## Governance Boundary

Large archives must be admitted through a bounded, traceable streaming process rather than by bypassing established limits.

The complete original MBOX remains authoritative. Contained messages remain derived projections of the preserved archive unless separately admitted through a later governed workflow.

The resulting document follows the existing lifecycle:

Pending Intake → Under Review → Approved → Published

No new public lifecycle state is introduced.

## When The Streaming Path Is Used

Administrators use the ordinary Document Intake form for ordinary documents and MBOX archives at or below the synchronous limit. The separate Governed Streaming Mailbox Intake form is used for large `.mbox` archives that exceed that limit.

The streaming route still requires:

- a `.mbox` filename;
- plausible MBOX content;
- at least one valid message boundary;
- at least one parseable RFC 5322 message;
- no parser, message, decoded-content, attachment, disk-space, concurrency, or configured-size limit breach.

The server remains authoritative. A browser classification such as `application/octet-stream` only affects file-picker compatibility and does not make arbitrary files acceptable.

## Configuration

The synchronous Document Intake limit remains controlled by `CDE_DOCUMENT_INTAKE_MAX_BYTES`, defaulting to 25 MB.

Streaming MBOX ingestion uses separate configuration:

- `MAX_STREAMING_MBOX_UPLOAD_BYTES` or `CDE_STREAMING_MBOX_UPLOAD_MAX_BYTES`: maximum streamed MBOX archive size. Default: 1 GB.
- `STREAMING_MBOX_CHUNK_BYTES` or `CDE_STREAMING_MBOX_CHUNK_BYTES`: upload read size. Default: 1 MiB.
- `STREAMING_MBOX_MIN_FREE_BYTES` or `CDE_STREAMING_MBOX_MIN_FREE_BYTES`: minimum disk-space reserve. Default: 128 MB.
- `STREAMING_MBOX_MAX_CONCURRENT_JOBS` or `CDE_STREAMING_MBOX_MAX_CONCURRENT_JOBS`: local process concurrency guard. Default: 1.

The default supports a 412 MB Apple Mail archive while still failing closed for unbounded or unexpectedly large uploads.

## Streaming And Hashing

The upload request body is not read into a single bytes object. The route reads from the uploaded file handle in bounded chunks, writes each chunk to a protected temporary file, updates SHA-256 incrementally, and tracks received bytes continuously.

If the configured streaming limit is exceeded, ingestion stops and the temporary file is removed. No governed document is created.

After validation, CDE verifies the stored temporary file digest before atomic finalisation.

## Temporary Storage And Cleanup

Temporary files are created under the Document Intake root in:

`_streaming_mbox_tmp/`

Temporary filenames are generated with unpredictable UUID-based names and are not derived from user-supplied filenames. Temporary files use restricted permissions and are never placed under a public static directory.

Cleanup occurs on:

- empty upload;
- size-limit breach;
- parser failure;
- finalisation failure;
- successful atomic promotion;
- stale temporary-file sweep at the start of each streaming intake.

Stale cleanup is limited to files with the Stage 37 streaming prefix inside the protected temporary directory.

## Disk Space And Concurrency

Before accepting a streaming upload, CDE checks available storage for the configured maximum archive size plus the configured reserve. If the filesystem cannot safely hold the operation, ingestion fails with a bounded administrative error and no document is created.

The local process uses a lock file to prevent unlimited simultaneous streaming MBOX jobs. This is intentionally conservative for the current deployment model and may be replaced by a distributed job coordinator in a future stage if deployment architecture requires it.

## Validation And Sequential Parsing

After upload, CDE validates the temporary file using a file-backed MBOX parser. The parser processes the archive sequentially, detects conservative `From ` separators, keeps message order stable, preserves duplicates, records byte ranges and contained-message digests, and only holds the current bounded message bytes while parsing.

Stage 36 projection behaviour is reused:

- mailbox statistics;
- stable message index;
- byte ranges;
- contained-message SHA-256 digests;
- public-safe header fields;
- bounded text and HTML previews;
- attachment metadata only;
- parser warnings;
- bounded search text.

Contained messages and attachments are not automatically promoted into separate governed documents.

## Operational Status Model

The implementation is synchronous at the HTTP route level but uses internal operational stages:

- receiving;
- validating;
- indexing;
- finalising;
- completed or failed.

These are processing states only. They do not replace Pending Intake, Under Review, Approved, or Published.

The successful result is the ordinary Document Intake Review page for the new Pending Intake document. Failures return bounded administrative error codes and messages without raw tracebacks, filesystem paths, message content, or temporary filenames.

## Error Codes

Stage 37 may return bounded errors such as:

- `streaming_mbox_empty`;
- `streaming_mbox_file_too_large`;
- `streaming_mbox_invalid_extension`;
- `streaming_mbox_invalid_content`;
- `streaming_mbox_insufficient_storage`;
- `streaming_mbox_concurrent_job_limit`;
- `streaming_mbox_finalisation_failed`;
- existing MBOX validation errors such as `document_intake_invalid_mbox`, `document_intake_mbox_too_many_messages`, `document_intake_mbox_message_too_large`, `document_intake_mbox_line_too_large`, `document_intake_mbox_decoded_content_too_large`, and `document_intake_mbox_too_many_attachments`.

Every failure keeps temporary data out of governed storage and creates no public document.

## Atomic Finalisation

Only after upload completion, size validation, MBOX structural validation, projection generation, SHA-256 finalisation, digest verification, and metadata validation does CDE create an ordinary Pending Intake record.

The temporary archive is atomically moved into the existing Document Intake storage layout as `pending-<sha256>.mbox`. Metadata is stored in the existing `metadata.json` sidecar, including:

- `intake_mode = governed_streaming_mbox`;
- streaming start and completion timestamps;
- validation completion timestamp;
- finalisation timestamp;
- streaming chunk size;
- configured streaming maximum;
- parser version;
- the ordinary Document Identifier, SHA-256, lifecycle, status history, provenance, and mailbox projection fields.

## Public Presentation And Search

After publication, streaming-ingested MBOX archives reuse Stage 36 public behaviour:

- Mailbox Overview;
- mailbox statistics;
- paginated Message Index;
- Message Detail;
- safe body previews;
- attachment metadata;
- Mailbox Governance Boundary;
- Publication Provenance;
- Publication Pathway;
- original `.mbox` download;
- Archive Explorer Mailbox Archive filtering;
- public document search over bounded mailbox projection fields.

Search and public presentation are indistinguishable from an MBOX admitted through the synchronous path.

## Deployment Considerations

The default streaming maximum is 1 GB and the default chunk size is 1 MiB. Railway or other deployment environments must provide persistent storage with enough free space for the temporary file, final governed object, metadata projection, and configured reserve. Operators should tune `MAX_STREAMING_MBOX_UPLOAD_BYTES`, `STREAMING_MBOX_MIN_FREE_BYTES`, and `STREAMING_MBOX_MAX_CONCURRENT_JOBS` to match the available volume and request-time budget.

Stage 37 does not add a background distributed queue. If deployment request timeouts make very large archives impractical, a future stage should add a resumable or queued upload model rather than weakening validation or raising the synchronous intake limit.

## Tests

Focused tests cover chunked upload, incremental SHA-256 equality, exact original-byte preservation, message order, pending lifecycle creation, streaming provenance, synchronous-limit preservation, empty uploads, exact-limit acceptance, size-limit rejection, parser failure cleanup, invalid extension rejection, fake-content rejection, duplicate rejection, disk-space rejection, concurrency rejection, authenticated route access, UI rendering, no public access before publication, and Stage 35/36 regressions.

## Intentional Exclusions

Stage 37 does not implement PST, OST, Gmail Takeout, IMAP acquisition, mailbox-level acquisition, resumable browser-restart uploads, automatic contained-message promotion, automatic attachment extraction, independent attachment downloads, direct Apple Mail package-directory upload, background distributed queues, or a generic unlimited upload endpoint.
