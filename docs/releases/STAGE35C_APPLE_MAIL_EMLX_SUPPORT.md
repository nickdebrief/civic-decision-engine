# Stage 35C / CDE v13.0.7 — Apple Mail .emlx Ingestion

The Civic Decision Engine can now preserve native Apple Mail `.emlx` files as independently governed documents.

The full original `.emlx` remains authoritative. The embedded RFC 5322 message and bounded Apple Mail metadata are parsed only to support inspection, safe presentation, and discovery without replacing or rewriting the source.

## Scope

Stage 35C extends governed Document Intake to accept Apple Mail `.emlx` uploads. The document follows the existing lifecycle: Pending Intake, Under Review, Approved, Published. No lifecycle state, publication rule, provenance rule, identifier rule, association rule, collection rule, transmission rule, or SHA-256 behaviour changes.

The stage does not implement MBOX, PST, OST, Gmail Takeout, IMAP acquisition, mailbox-level import, email sending, or automatic creation of governed documents from attachments.

## EMLX Structure

An Apple Mail `.emlx` source is treated as a wrapper containing:

- a bounded ASCII decimal byte-count line;
- exactly that many RFC 5322 message bytes;
- optional trailing Apple metadata, usually plist data.

CDE validates the wrapper before accepting the upload. The byte-count line must be present, numeric, positive, bounded, and satisfied by the remaining file bytes. The embedded message must parse as a plausible RFC 5322 message.

## Original-Byte Boundary

The governed Document is the full uploaded `.emlx` file. CDE computes SHA-256 from the complete untouched upload, including the byte-count line and trailing metadata. The parser never reconstructs a replacement `.emlx`, never normalises the source message, and never computes the governed document digest from only the embedded RFC 5322 bytes.

Original-file download returns the exact preserved `.emlx` bytes with attachment disposition and `X-Content-Type-Options: nosniff`.

## RFC 5322 Reuse

The embedded message bytes are parsed through the Stage 35A RFC 5322/MIME parser. This preserves shared behaviour for subject, From, Sender, Reply-To, To, CC, internal BCC handling, message date, Message-ID, In-Reply-To, References, MIME type, plain-text body, sanitised HTML body, attachment metadata, parser warnings, and search text.

The `.emlx` wrapper does not silently overwrite RFC 5322 fields. Where Apple metadata and RFC 5322 metadata differ, they remain separately labelled presentation fields.

## Plist Parsing

Trailing Apple metadata is parsed only after the declared RFC 5322 byte range. XML and binary plist data are handled with Python `plistlib` under bounded limits for metadata size, nesting depth, item count, and string length. Malformed plist-like metadata is rejected; non-plist trailing bytes are preserved and recorded as bounded parser warnings where safe.

The parser does not execute plist values, dereference paths or URLs, fetch remote resources, or trust embedded filenames or account data.

## Apple Metadata Classification

Safe public Apple Mail metadata is limited to useful source-recorded state such as flags, read state, replied state, forwarded state, flagged state, received date, trailing metadata presence, trailing metadata byte count, and declared embedded message byte count.

Internal or search-excluded metadata includes local mailbox paths, local account identifiers, filesystem paths, private account IDs, hidden plist values, BCC, parser diagnostics containing message content, and attachment contents. These values are not presented publicly by default.

## Public Presentation

Published `.emlx` documents reuse the shared email layout:

- Email Overview;
- Apple Mail Metadata;
- Message Body;
- sanitised HTML view where available;
- Attachments metadata;
- Email Governance Boundary;
- Publication Provenance;
- Publication Pathway;
- Document Identifier;
- SHA-256 digest;
- original `.emlx` download.

The public presentation mode is `Apple Mail Message metadata, safe body preview, and original-file download`. Original-file availability is `Original .emlx download available`.

The public boundary states that parsed Apple Mail and RFC 5322 metadata reflects fields contained in the preserved source message and does not independently verify sender identity, delivery, receipt, authorship, authenticity, factual accuracy, legal status, evidential sufficiency, or external validation.

## Attachments

Attachments remain components of the preserved `.emlx` source unless separately admitted through Document Intake. Stage 35C lists attachment metadata only: filename, media type, byte size, disposition, content ID, attached-message status, and generated filename status where available. It does not create governed documents, publish attachment bytes independently, execute attachment content, decompress archives, or create associations.

## Search and Archive Discovery

Published Apple Mail messages contribute public-safe fields to document search: subject, sender, recipients, Message-ID, In-Reply-To, References, plain-text body, text extracted from sanitised HTML, attachment filenames, administrator metadata, and selected safe Apple state fields. BCC, local paths, account identifiers, hidden plist values, parser diagnostics containing message content, and attachment contents remain excluded.

The existing Archive media filter treats `.emlx` as Email alongside `.eml` and `.msg`.

## Security Limits

Stage 35C applies bounded limits for maximum `.emlx` upload size, first-line length, declared embedded message bytes, trailing metadata bytes, plist depth, plist item count, plist string length, RFC 5322 header count and length, MIME depth and part count, decoded body size, HTML render size, attachment count, decoded attachment size, total decoded size, search text, and rendered output.

The implementation fails closed for malicious declared lengths, truncated files, oversized metadata, plist bombs, MIME bombs, unsafe HTML, remote-resource references, unsafe URLs, and extension/content mismatches. No network request is made during parsing or rendering.

## Governance Invariants

An `.emlx` file is a Published Document in its own right. It retains its own Document Identifier, SHA-256 digest, lifecycle, Publication Provenance, Publication Pathway, public detail page, original-file download, associations, collection memberships, and transmission relationships.

Attachments do not automatically become governed Documents. Embedded RFC 5322 parsing does not alter the source digest, lifecycle, publication state, provenance, associations, collections, transmissions, or public eligibility.

## Tests

Focused tests cover valid `.emlx` intake, plain text messages, HTML-only messages, multipart messages, attachment metadata, XML and binary plist metadata, Apple flags extraction, original SHA-256 preservation, exact original `.emlx` download, public/private visibility, search, archive Email filtering, preview labels, validation failures, HTML sanitisation, and Stage 35A/35B regression compatibility.

## Intentional Exclusions

Stage 35C does not implement MBOX, PST, OST, Gmail Takeout, IMAP acquisition, mailbox-level import, email sending, independent attachment download, automatic attachment ingestion, automatic transmission creation, automatic association creation, or automatic collection membership.
