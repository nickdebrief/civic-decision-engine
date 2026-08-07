# Email Attachment Preservation

## Governance Boundary

CDE Platform Stage 49 applies one rule: objects remain independent and
relationships preserve context. An email is the communication, an attachment is
the enclosed object, and `Email attachment` records that the object was
transmitted with the communication. The relationship is not an interpretation
of evidential weight and is not a Record–Document Association.

Preservation creates no Canonical Record, no semantic classification, and no
automatic publication. Every attachment enters the existing Published Document
lifecycle as `pending` and must pass the normal review, approval, and publication
steps before its public page or download becomes available.

## Preservation Architecture

The source adapters identify and decode attachment payloads. The preservation
service then:

1. retains the exact extracted byte stream;
2. calculates SHA-256 and SHA-512 from those bytes;
3. derives a deterministic source-occurrence identity;
4. creates or reuses the corresponding attachment Published Document intake;
5. records one `Email attachment` relationship; and
6. records a failed occurrence without a document link when preservation fails.

RFC 5322 MIME parts are processed in source order with bounded parser limits.
Plain-text and HTML body parts and multipart containers are excluded. Inline
parts remain explicitly marked inline. Outlook, Gmail, and IMAP adapters invoke
the same service only where their existing extraction pathway already supplies
the exact attachment bytes.

## Standalone Outlook MSG Messages

CDE Platform Stage 51 extends the same preservation model to standalone
`.msg` intake documents. A bounded MSG extractor
(`extract_outlook_msg_attachment_payloads`) reuses the existing Stage 35B
compound-file helpers to surface each attachment's exact `__substg1.0_3701`
stream bytes alongside its source-reported filename, MIME type, Content-ID, and
attachment index. The MSG is parsed twice on purpose: the first pass enforces
Stage 35B validation and resource limits without changing the published metadata
shape; the second pass re-derives the attachment groups so the exact bytes can be
preserved. This is a deliberate scope boundary, not redundant work.

The resulting occurrences are preserved through the unchanged Stage 49 service
with `source_pathway = "outlook_msg"`. Every source-reported occurrence remains
governably represented:

* a non-empty attachment payload is preserved as an independent Published
  Document with an `Email attachment` relationship;
* an embedded message (`attach_method == 5`) is preserved opaquely as its
  attachment bytes and is never recursively expanded;
* a zero-byte occurrence cannot be admitted as a Published Document and is
  instead recorded as a failed relationship row with reason
  `email_attachment_empty_payload` so the occurrence is never silently lost.

## Standalone Apple Mail EMLX Messages

CDE Platform Stage 52 extends the same preservation model to standalone `.emlx`
intake documents. A bounded Apple Mail extractor
(`extract_apple_emlx_attachment_payloads`) recovers the authoritative RFC 5322
message bytes from the `.emlx` wrapper (reusing the existing Stage 35B
length-prefix, message-length, and trailing-plist validation) and delegates
attachment-byte extraction to the existing RFC 5322 extractor
(`extract_email_attachment_payloads`). No second MIME parser is introduced.

The `.emlx` is parsed twice on purpose: the first pass (`parse_apple_emlx_metadata`)
enforces Stage 35B validation and resource limits without changing the published
metadata shape; the second pass re-derives the RFC 5322 message region so the
exact bytes can be fed to the existing extractor. This mirrors the deliberate
two-pass design used for standalone MSG in Stage 51.

The resulting occurrences are preserved through the unchanged Stage 49 service
with `source_pathway = "apple_emlx"` and the same `mime-part:<index>` source
occurrence identifier convention as RFC 5322 `.eml`. Every source-reported
occurrence remains governably represented under the same zero-byte, embedded
message, and inline policies documented above.

## Storage and Metadata

Attachment Published Documents use the existing intake directory, immutable
Document Identifier registry, status history, access controls, publication
routes, download route, and verification hashes. Structured attachment
provenance records source-reported values separately from CDE-calculated values.

The relationship registry is a narrowly scoped SQLite sidecar in the governed
intake root. It has indexed lookups for source email, source object, attachment
document, source archive, relationship type, and deterministic source identity.
It does not modify the Record–Document Association schema or semantics.

The registry never stores raw attachment bytes, credentials, passwords, tokens,
authentication headers, or hidden recipient data. Administrative metadata APIs
remain authenticated. Public views omit private archive, mailbox, UID, EntryID,
and account identifiers.

## Failure and Retry

One failed attachment does not discard successfully preserved sibling
attachments. A failure row retains the available filename, index, MIME metadata,
source identity, pathway, and failure reason, but its attachment document field
remains empty. A later successful retry upgrades that same deterministic
occurrence rather than creating a duplicate relationship.

## Existing Data Backfill

The bounded maintenance command supports authoritative RFC 5322 intake records,
standalone Outlook `.msg` intake records, and standalone Apple Mail `.emlx`
intake records. A single document can be targeted with `--intake-id`:

```bash
python scripts/backfill_email_attachment_preservation.py \
  --root /data/attachments/intake/pending \
  --limit 100 \
  --dry-run
```

Remove `--dry-run` only after reviewing counts. The command reports processed,
created, linked, already-present, skipped, ambiguous, and failed totals. It uses
the preserved `.eml`/`.msg` bytes and existing parser metadata; it never infers
an attachment from body text, upload proximity, filename, or hash alone. Dry-run
is strictly write-free: it creates no intake directories, no relationship rows,
no document identifiers, and mutates no source metadata or registry.

Historical PST/OST, Gmail, and IMAP backfill is intentionally not speculative.
New projections preserve Published Document occurrences whenever exact bytes are
available. Existing archive occurrences require a future explicit migration only
if their authoritative projection and byte sidecars can be reconciled without
ambiguity.

## Transaction and Security Notes

The source email is preserved first. Attachment occurrences are then processed
independently. A successful child is fully written before its relationship is
recorded. A failed child leaves a governed failure occurrence and never a false
document link. OCR, preview, and derivative generation are outside Stage 49 and
cannot replace the preserved original bytes.

Attachment content is never executed during preservation. No remote resources
are fetched, macros are not loaded, active HTML is not trusted, and source
filenames are sanitised for storage and display without changing the preserved
bytes.
