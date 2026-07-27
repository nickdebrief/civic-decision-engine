# CDE Platform Stage 35A / CDE v13.0.5 — RFC 5322 .eml Ingestion

The Civic Decision Engine can now preserve native RFC 5322 email files as
independently governed documents.

The original message bytes remain authoritative. Parsed headers, body content,
MIME structure, and attachment metadata support inspection and discovery without
replacing or rewriting the source.

## Scope

CDE Platform Stage 35A extends the existing governed Document Intake workflow to accept
`.eml` files. An admitted email follows the existing lifecycle:

Pending Intake -> Under Review -> Approved -> Published

No new lifecycle state, governed object type, publication rule, provenance rule,
association rule, collection rule, transmission rule, or SHA-256 rule is added.

## Validation Model

The intake validator recognises `.eml` as a supported Published Document format
only when the original bytes are plausibly an RFC 5322 message. Validation uses
server-side inspection and Python's standard-library email parser. Browser MIME
headers and filename extensions are treated as supporting information only.

Recognised upload MIME variants include:

- `message/rfc822`;
- `text/rfc822`;
- `application/eml`.

The canonical stored media type is `message/rfc822`, and the public document
format label is `RFC 5322 Email`.

Validation rejects empty files, non-email files renamed as `.eml`, extension and
content mismatches, malformed messages without a header/body boundary, and
messages that exceed bounded parsing limits.

## Parsing Model

Parsing operates on the uploaded bytes with:

`email.parser.BytesParser(policy=email.policy.default)`

The parsed message is never serialised back to disk as a replacement source.
The projection is stored separately in Document Intake metadata under
`email_metadata` and remains presentation and discovery metadata only.

Extracted fields include:

- Message-ID;
- raw and parsed Date header;
- From, Sender, Reply-To, To, CC, and BCC raw header values;
- decoded address display values for public-safe recipient fields;
- raw and decoded Subject;
- In-Reply-To and References;
- MIME version, content type, transfer encoding, and multipart state;
- plain-text body;
- sanitised HTML body where present;
- bounded body search text;
- attachment metadata;
- parser warnings and defects.

BCC is retained only as source metadata in the preserved projection. It is not
included in public document search text.

## Preserved-Byte Boundary

The email is preserved as received. Parsing improves inspection; it does not
rewrite the source.

CDE calculates SHA-256 from the original uploaded `.eml` bytes and stores those
same bytes as the authoritative governed artefact. The parser does not normalise
line endings, repair headers, convert encodings, reconstruct MIME parts, or
replace the stored file.

## HTML Sanitisation

Original email HTML is never rendered directly. CDE Platform Stage 35A uses a restrained
allowlist sanitizer for the public HTML projection.

The sanitizer removes or neutralises active and remote content, including:

- scripts;
- styles and external stylesheets;
- iframes, forms, objects, embeds, frames, and metadata redirects;
- event-handler attributes;
- remote images and tracking pixels;
- `javascript:`, `data:`, `vbscript:`, `file:`, and remote HTTP(S) links.

Plain text remains the primary reading view where it exists. Sanitised HTML is
shown as an optional presentation projection.

## Attachment Treatment

CDE Platform Stage 35A extracts attachment metadata only. Public pages list, where available:

- filename;
- media type;
- byte size;
- content disposition;
- content ID;
- whether the part is an attached RFC 822 message;
- whether the filename was generated because none was supplied.

Attachments are not automatically published as separate CDE documents. They do
not receive Document Identifiers, associations, collection memberships, or
transmission relationships unless separately admitted through existing governed
workflows.

CDE Platform Stage 35A does not add independent public attachment download routes.

## Search Behaviour

Published email documents participate in the existing Public Document Library
and Archive Explorer search paths. Searchable email fields include decoded
subject, From, Sender, Reply-To, To, CC, Message-ID, In-Reply-To, References,
plain-text body text, text derived from sanitised HTML, and attachment filenames
and metadata.

Search metadata is discovery metadata only. It does not alter evidential meaning,
verification state, lifecycle, SHA-256, associations, collection membership,
transmission inclusion, or publication eligibility.

## Public Presentation

Published `.eml` documents display the existing Document Metadata, Publication
Provenance, Publication Pathway, SHA-256 digest, Document Identifier, public
navigation, archive return links, and original-file download.

The email-specific public section adds:

- Email Overview;
- Message Body;
- Attachments;
- Email Governance Boundary.

The public page states that parsed email metadata reflects fields contained in
the preserved source message and does not independently verify sender identity,
delivery, receipt, authorship, authenticity, factual accuracy, legal status,
evidential sufficiency, or external validation.

## Download Behaviour

Published `.eml` documents can be downloaded as the original uploaded file.
Downloads use:

- media type `message/rfc822`;
- `Content-Disposition: attachment`;
- `X-Content-Type-Options: nosniff`;
- the existing public published-document eligibility checks.

CDE does not reconstruct the message from parsed fields.

## Security Limits

CDE Platform Stage 35A applies bounded parser limits for:

- maximum `.eml` upload size;
- maximum header count;
- maximum individual header length;
- maximum MIME nesting depth;
- maximum MIME part count;
- maximum attachment count;
- maximum decoded body size;
- maximum decoded attachment size;
- maximum total decoded MIME size;
- maximum indexed text;
- maximum rendered HTML projection.

The implementation fails closed when limits are exceeded. It performs no remote
content retrieval, does not invoke local mail clients or word processors, does
not execute embedded content, and does not trust client-supplied MIME headers.

## Governance Boundaries

An `.eml` file is a Published Document in its own right. It retains its own:

- Document Identifier;
- SHA-256 digest;
- lifecycle;
- publication provenance;
- publication pathway;
- public detail page;
- original-file download;
- associations and collection memberships.

An email attachment is not automatically a separate governed document. Parsed
headers and body projections are not independent evidence of sender
authenticity, delivery, receipt, authorship, truth, or legal status.

## Known Exclusions

CDE Platform Stage 35A does not implement:

- Outlook `.msg` support;
- PST, MBOX, Gmail Takeout, Apple Mail package, Exchange archive, or mailbox
  ingestion;
- email sending, IMAP, SMTP, reply threading, or messaging;
- automatic creation of Documents, Records, Associations, Collections, or
  Transmissions from email headers or attachments;
- attachment content indexing;
- independent attachment download routes;
- automatic verification of sender identity, delivery, receipt, authorship, or
  factual accuracy.

## Tests

Focused tests cover valid plain-text, HTML-only, multipart alternative,
multipart mixed, attachment metadata, encoded headers, Message-ID and References
extraction, SHA-256 and original-byte preservation, invalid masquerades,
extension/content mismatch rejection, parser resource limits, HTML sanitisation,
pending/private access boundaries, public page rendering, preview fallback,
search, archive filtering, and exact original `.eml` download.

The focused test module is:

`tests/test_rfc5322_eml_support.py`

Full regression remains required before release.
