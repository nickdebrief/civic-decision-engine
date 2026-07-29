# CDE Platform Stage 39A — PST/OST Parser & Intake Boundary

## Purpose

CDE Platform Stage 39A introduces a conservative governed intake boundary for Microsoft Outlook Personal Storage (`.pst`) and Offline Storage (`.ost`) archives.

The archive is evidence. The uploaded bytes remain authoritative. CDE Platform Stage 39A does not extract mailbox folders, messages, attachments, contacts, calendar items, or canonical records.

## Scope

CDE Platform Stage 39A adds `.pst` and `.ost` to Document Intake as preserved archive artefacts. Accepted Outlook archives receive the same document lifecycle as other governed documents:

Pending Intake → Under Review → Approved → Published

The stage records archive-level metadata only:

- archive type: PST or OST
- original filename
- file size
- declared MIME type
- upload timestamp
- uploader
- parser status
- parser version when configured
- SHA-256 digest
- SHA-512 digest

## Parser Boundary

The platform now defines an `OutlookArchiveParser` contract for future PST/OST extraction stages:

- `supports(file_path)`
- `inspect(file_path)`

No concrete parser dependency is required in CDE Platform Stage 39A. If no parser is configured, archive intake succeeds and records:

`Parser not configured.`

This keeps the platform operational while preserving a stable integration boundary for later parser-backed stages.

## Validation Model

CDE Platform Stage 39A validates:

- recognized `.pst` or `.ost` extension
- non-empty uploaded bytes
- existing synchronous Document Intake size limit
- successful SHA-256 and SHA-512 generation
- successful storage of the original archive bytes

The browser-supplied MIME type is not treated as authoritative. Server-side extension handling remains authoritative for CDE Platform Stage 39A, and the parser-unavailable state does not reject the upload.

## Original-Byte Preservation

The original archive is stored exactly as uploaded.

CDE does not:

- rewrite the archive
- decompress it
- repair it
- normalize it
- optimize it
- extract contained messages
- promote attachments or messages into separate governed objects

The SHA-256 and SHA-512 digests are calculated over the untouched upload bytes.

## Public Presentation

Published PST/OST documents show standard public document metadata, publication provenance, lifecycle pathway, archive-level parser status, SHA-256, SHA-512, and original-file download.

No mailbox contents are displayed. No folder names, messages, attachment lists, or extracted Outlook properties are exposed publicly in CDE Platform Stage 39A.

## Archive Metadata API

CDE Platform Stage 39A adds read-only archive metadata endpoints for published PST/OST documents:

- `GET /archive/{id}`
- `GET /archive/{id}/status`

The responses include archive metadata and parser status only. No extraction endpoints are introduced.

## Governance Boundary

Microsoft Outlook PST and OST archives are preserved as original bytes. CDE Platform Stage 39A records archive-level metadata and parser readiness only; it does not discover folders, extract messages, publish mailbox contents, or promote contained items into separate governed records.

## Regression Safety

CDE Platform Stage 39A does not change:

- RFC 5322 `.eml` support
- Microsoft Outlook `.msg` support
- Apple Mail `.emlx` support
- governed MBOX archive support
- streaming MBOX intake
- Mailbox Relationship Graph behaviour
- canonical records
- verification hashes for existing formats
- publication workflow
- CREF methodology
- database schema

## Tests

Focused tests cover:

- PST and OST intake recognition
- original-byte preservation
- SHA-256 and SHA-512 calculation
- parser-not-configured metadata
- no email or mailbox projection creation
- admin intake accept values and review display
- public archive overview and provenance display
- read-only archive metadata/status endpoints
- public preview labels
- search indexing of safe archive-boundary metadata

## Future Extensions

Future CDE Platform stages may add parser-backed preservation and extraction jobs, folder and message projections, governed message promotion, and attachment governance. Those stages must preserve the CDE Platform Stage 39A original-byte boundary.
