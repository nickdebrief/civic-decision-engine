# CDE Platform Stage 36 / CDE v13.0.8 — Governed MBOX Archive Ingestion

The Civic Decision Engine can now preserve MBOX mailbox archives as governed container documents.

The full original MBOX remains authoritative. Contained RFC 5322 messages are parsed as bounded projections for inspection, search, and safe presentation without rewriting the mailbox, removing duplicates, changing message order, or automatically creating independent governed documents.

## Scope

CDE Platform Stage 36 extends governed Document Intake to accept `.mbox` uploads. A mailbox archive follows the existing lifecycle: Pending Intake, Under Review, Approved, Published. No lifecycle state, publication rule, provenance rule, identifier rule, association rule, collection rule, transmission rule, storage rule, or SHA-256 behaviour changes.

## MBOX Structure and Variants

The parser treats MBOX as a byte-preserved mailbox archive made of `From ` separator lines followed by RFC 5322 message bytes. It recognises conservative Unix-style separators and records a detected variant label for common mboxo, mboxrd, mboxcl, and mboxcl2 characteristics. Escaped `>From ` body lines are retained as message content and do not become boundaries.

## Boundary Detection

Boundary detection is server-side and does not trust extension, filename, browser MIME type, or client metadata alone. A candidate boundary must match a bounded `From sender weekday month day time year` separator pattern. Body lines beginning with `From ` that do not match the separator pattern remain body content. The upload must contain at least one plausible boundary and at least one parseable contained RFC 5322 message.

## Original-Byte Preservation

The governed Document is the full uploaded `.mbox` file. CDE computes SHA-256 from the complete untouched upload, including separators, line endings, message ordering, duplicate messages, malformed historical segments, and trailing bytes. The parser never reconstructs a replacement mailbox, never normalises line endings, never unescapes `>From ` lines, never removes duplicates, and never computes the governed document digest from a contained message.

Original-file download returns the exact preserved `.mbox` bytes with attachment disposition and `X-Content-Type-Options: nosniff`.

## Mailbox Versus Message Governance

The MBOX archive is the governed object. Contained messages are bounded projections of that governed object. CDE Platform Stage 36 does not automatically create Document Intake records, canonical records, associations, collection memberships, transmissions, or independent SHA-256 identities for contained messages or attachments.

## Message Indexing

Each contained-message projection records a stable message index, separator offset, message byte range, message byte size, contained-message digest, parse status, warning list, selected RFC 5322 metadata, bounded plain-text and sanitised HTML previews, attachment metadata, and duplicate-candidate status. Message ordering is preserved exactly as it appears in the source archive.

## Duplicate Handling

CDE Platform Stage 36 identifies exact-byte duplicate candidates by contained-message digest. It does not remove, collapse, reorder, or merge duplicate messages. Duplicate indicators are discovery metadata only and do not alter governance identity.

## Message Digest Boundary

The contained-message digest supports future extraction planning and inspection. It is not the governed Document SHA-256, does not replace the MBOX archive digest, and does not create an independent governed document identity.

## Attachment Treatment

Attachments remain metadata-only. CDE Platform Stage 36 records filename, media type, byte size, disposition, content ID, attached-message status, and generated filename status where available. It does not publish attachment bytes independently, execute files, unpack archives, index attachment contents, or create governed documents for attachments.

## Public Presentation

Published MBOX documents display a Mailbox Overview, bounded Mailbox Message Index, selected Message Detail, attachment metadata, parser warnings, Publication Provenance, Publication Pathway, Mailbox Governance Boundary, and original `.mbox` download. Public rendering is bounded and paginated so a large archive is not rendered as one enormous page.

## Search Behaviour

Search includes public-safe mailbox fields and contained-message projections: subject, sender, Reply-To, To, CC, Message-ID, In-Reply-To, References, bounded body text, sanitised HTML text, attachment filenames, administrator title, description, source, optional reference, category, and keywords. BCC, private lifecycle notes, filesystem paths, account identifiers, raw stack traces, unsafe URLs, and attachment contents are excluded from public search.

## Parser Warnings

Recoverable historical message issues are recorded as bounded parser warnings. Structural limit breaches fail closed. Warnings support inspection only and do not establish completeness, delivery, receipt, authenticity, legal status, factual accuracy, or evidential sufficiency.

## Security Limits

CDE Platform Stage 36 applies bounded limits for maximum MBOX upload bytes, message count, individual message bytes, separator length, line length, MIME header count and length, MIME depth and part count, attachment metadata count, decoded body bytes, decoded attachment bytes, total decoded bytes, search text, preview bytes, parser warnings, pagination size, duplicate processing, and messages processed synchronously.

CDE Platform Stage 37A keeps the synchronous CDE Platform Stage 36 path conservative: contained messages admitted through ordinary Document Intake remain bounded by the in-memory message threshold. The separate governed streaming path can handle larger contained messages through file-backed byte-range parsing and a separate hard per-message maximum.

The parser avoids unbounded recursion, network access, remote resource retrieval, active HTML rendering, attachment execution, archive unpacking, and filesystem writes based on message or attachment filenames.

## Apple Mail Export Upload Compatibility

Apple Mail exports a Finder package ending in `.mbox` that contains the actual mailbox data file named `mbox` and a separate `table_of_contents` file. CDE Platform Stage 36A keeps direct directory/package upload out of scope. Administrators should open the exported package, copy the internal `mbox` data file, rename the copy with a descriptive `.mbox` filename, and upload that copy through Document Intake. The `table_of_contents` file is not the mailbox archive and remains rejected by server-side mailbox validation.

The intake file picker now explicitly permits `.mbox`, `application/mbox`, `text/mbox`, and `application/octet-stream` so browser and Finder classifications for copied Apple Mail mailbox data do not hide an otherwise uploadable file. This picker compatibility does not weaken server-side validation: the upload must still have a supported `.mbox` filename, satisfy mailbox boundary checks, respect configured upload and parser limits, and preserve the original bytes for SHA-256 calculation.

The current governed Document Intake path is synchronous and bounded at the configured Document Intake upload limit, 25 MB by default. A 412 MB Apple Mail export exceeds that default boundary and the CDE Platform Stage 36 parser's conservative MBOX size limit; supporting archives of that size requires a separate governed streaming ingestion path rather than a silent limit increase in CDE Platform Stage 36A. CDE Platform Stage 37 adds that separate path while leaving this synchronous limit unchanged.

## Future Message Promotion

The metadata model records parent archive identity, message index, byte range, and contained-message digest so a later explicit governed workflow could promote a contained message into Document Intake. CDE Platform Stage 36 does not implement that action.

## Tests

Focused tests cover valid one-message and multi-message MBOX intake, mboxrd-style escaped `>From ` lines, body lines beginning with `From `, HTML sanitisation, attachment metadata, duplicate preservation, recoverable malformed messages, exact original-byte download, stable indexing, archive filtering, public message detail, search integration, private/public visibility, Apple Mail export picker compatibility, octet-stream classified `.mbox` uploads, `table_of_contents` rejection, validation failures, and resource-limit failures. CDE Platform Stage 35A `.eml`, CDE Platform Stage 35B `.msg`, CDE Platform Stage 35C `.emlx`, and full regression suites are run for compatibility.

## Intentional Exclusions

CDE Platform Stage 36 does not implement PST, OST, Gmail Takeout, IMAP acquisition, mailbox-level synchronisation, email sending, automatic attachment extraction, automatic message promotion, automatic transmissions, automatic records, automatic associations, automatic collections, mailbox repair, mailbox deduplication, or independent attachment downloads.
