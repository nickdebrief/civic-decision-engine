# CDE Platform Stage 35B / CDE v13.0.6 — Microsoft Outlook .msg Ingestion

The Civic Decision Engine can now preserve native Microsoft Outlook message
files as independently governed documents.

The original `.msg` bytes remain authoritative. Extracted MAPI properties, safe
message-body presentation, conversation metadata, and attachment metadata
support inspection and discovery without replacing or rewriting the source.

## Scope

CDE Platform Stage 35B extends the existing governed Document Intake workflow to admit
Microsoft Outlook `.msg` files. A `.msg` file follows the existing lifecycle:

```text
Pending Intake -> Under Review -> Approved -> Published
```

No new lifecycle state, governed object type, transmission workflow, collection
workflow, association rule, publication rule, or public eligibility rule is
introduced.

## Dependency Choice

No new runtime dependency is introduced for CDE Platform Stage 35B. The implementation uses a
narrow, bounded, in-memory Compound File Binary reader and MAPI property
projection tailored to the fields needed by CDE public inspection. This avoids
parser behaviours that may write attachments to disk by default, and keeps the
source-file boundary explicit.

The parser is not a general-purpose Outlook forensics library. It validates and
projects the bounded metadata needed for governed intake, search, preview, and
download.

## File Validation

Validation does not trust the filename, browser-supplied MIME type, or client
metadata alone. Intake verifies that the uploaded bytes are plausibly a
Microsoft Compound File Binary object and contain Outlook MSG-style MAPI streams
or properties.

The validator rejects empty files, non-CFB files renamed as `.msg`, generic CFB
files without plausible Outlook properties, extension/content mismatches,
corrupt directory structures, cyclic stream chains, excessive stream/property
counts, oversized bodies, oversized attachments, excessive embedded-message
depth, and files that exceed bounded resource limits.

Administrative rejection messages remain bounded and do not expose filesystem
paths, stack traces, or raw message content.

## CFB and MAPI Parsing Model

CDE Platform Stage 35B parses the original upload bytes and stores a structured email
projection alongside the document metadata. The projection is derived metadata;
it is not a replacement source file.

Extracted fields include, where present:

- source format label;
- Outlook message class;
- subject;
- sender name, sender email, and sender SMTP address;
- sent-representing name and email;
- To and CC recipients;
- BCC retained internally in the projection but excluded from public search;
- Reply-To;
- Internet Message-ID, In-Reply-To, and References;
- conversation topic, index, and identifier;
- client submit, delivery, creation, and last-modification times;
- plain-text body;
- sanitised HTML body;
- RTF body presence;
- attachment metadata;
- embedded message count;
- parser warnings and defects.

Missing fields are left empty. The parser does not infer sender identity,
delivery, receipt, authorship, authenticity, or legal meaning from Outlook
properties.

## Sender and Date Boundaries

Outlook may distinguish sender, sent-on-behalf identity, and SMTP address. CDE
labels those values separately and does not treat one as proof of another.

The administrator-entered document date remains separate from the Outlook client
submit time, delivery time, message creation time, message last-modification
time, CDE intake timestamp, review timestamp, approval timestamp, and
publication timestamp. Parsed Outlook timestamps are displayed as values
recorded in the preserved source message.

## Body Handling

Plain-text body content is the primary public reading projection where present.
HTML body content is never rendered directly; it is sanitised before display and
converted to text for public-safe search. RTF body presence is recorded, but raw
Outlook RTF is not rendered publicly in CDE Platform Stage 35B.

RTF handling is deliberately bounded. CDE records presence and compressed stream
size limits, but does not execute embedded RTF objects, convert Outlook RTF to
HTML, or let RTF parsing alter source bytes or SHA-256 values.

## HTML Sanitisation

CDE Platform Stage 35B reuses the CDE Platform Stage 35A email HTML boundary. Sanitisation removes or
neutralises scripts, event handlers, iframes, forms, active objects, external
stylesheets, JavaScript URLs, unsafe data URLs, remote images, and tracking
pixels. No remote image, stylesheet, font, attachment, or linked resource is
fetched during parsing or rendering.

## Attachment and Embedded Message Treatment

Attachments remain components of the source `.msg` file unless separately
admitted through Document Intake. CDE Platform Stage 35B lists attachment metadata only:

- attachment index;
- filename and long filename where supplied;
- generated filename status;
- media type or MIME tag;
- byte size;
- content disposition;
- content ID;
- attachment method;
- embedded-message status.

Attachment bytes are not stored in metadata tables, independently downloaded,
executed, previewed, decompressed, indexed, or converted into governed objects.
Embedded `.msg` attachments are identified as embedded messages but are not
recursively published or admitted as separate documents.

## Search and Discovery

Published Outlook messages contribute public-safe extracted fields to Published
Document search, including subject, sender fields, sent-representing identity,
To and CC recipients, Reply-To, Internet Message-ID, In-Reply-To, References,
conversation topic, plain-text body, text extracted from sanitised HTML, and
attachment filenames.

BCC is excluded from public search by default. Attachment contents, hidden MAPI
properties, parser diagnostics containing message content, and temporary paths
are not indexed.

Search metadata remains discovery metadata only. It does not alter evidential
meaning, verification state, lifecycle, SHA-256, public eligibility,
associations, collection membership, or publication status.

## Public Presentation

Published `.msg` documents reuse the shared email presentation model:

- Email Overview;
- Message Body;
- Sanitised HTML view where available;
- RTF-present notice where relevant;
- Attachments metadata;
- Email Governance Boundary;
- original `.msg` download;
- Document Metadata;
- Publication Provenance;
- Publication Pathway.

The public presentation mode is `Microsoft Outlook Message metadata, safe body
preview, and original-file download`. Original-file availability is shown as
`Original .msg download available`.

Downloads serve the exact preserved bytes with `Content-Disposition: attachment`,
`X-Content-Type-Options: nosniff`, and the `application/vnd.ms-outlook` media
type. CDE never reconstructs a `.msg` file from parsed fields.

## Security Limits

CDE Platform Stage 35B applies bounded limits for:

- maximum `.msg` upload size;
- CFB directory entries;
- stream count;
- property count;
- property size;
- recipient count;
- attachment count;
- embedded-message depth;
- body size;
- HTML size;
- RTF compressed size;
- decoded attachment size;
- total decoded content size;
- search text;
- rendered output.

The parser fails closed for malformed CFB chains, cyclic streams, oversized
streams, excessive parts, path-traversal filenames, unbounded recursion, and
unsafe public presentation risks.

## Governance Boundaries

A `.msg` file is a Published Document in its own right. It retains its own
Document Identifier, SHA-256 digest, lifecycle, Publication Provenance,
Publication Pathway, public detail page, original-file download, associations,
and collection memberships.

The Outlook message is preserved as received. MAPI extraction supports
inspection; it does not replace the source.

Attachments and embedded messages are not automatically created as Document
Intake records, associations, canonical records, collections, or transmissions.

Parsed Outlook metadata reflects fields contained in the preserved source
message. It does not independently verify sender identity, delivery, receipt,
authorship, authenticity, factual accuracy, legal status, evidential sufficiency,
or external validation.

## Compatibility

CDE Platform Stage 35B preserves existing behaviour for RFC 5322 `.eml`, PDF, JPEG, PNG,
M4A, MP3, WAV, XLS, XLSX, RTF, canonical records, record-document associations,
archive collections, transmissions, corrections, audit history, verification
hashes, identifiers, and public URLs.

## Tests

Focused tests cover valid `.msg` intake, content-type variants, MAPI sender and
recipient extraction, sent-representing sender handling, Internet Message-ID,
conversation topic, source timestamps, sanitised HTML, RTF-present boundaries,
attachment metadata, embedded-message metadata, exact SHA-256 and original-byte
preservation, exact original `.msg` download, validation failures, public/private
access boundaries, public search, preview, archive filtering, and admin review
guidance.

CDE Platform Stage 35A RFC 5322 regression tests and the full regression suite were run to
confirm that existing email ingestion and other governed document behaviours were
not changed.

## Known Exclusions

CDE Platform Stage 35B does not implement `.emlx`, PST, OST, MBOX, Gmail Takeout,
mailbox-level ingestion, email sending, SMTP, IMAP, attachment extraction into
separate governed documents, independent attachment downloads, Outlook RTF
rendering, automatic transmissions, automatic collection membership, automatic
canonical records, or automatic associations.
