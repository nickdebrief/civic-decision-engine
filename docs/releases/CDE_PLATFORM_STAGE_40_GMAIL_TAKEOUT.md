# CDE Platform Stage 40 — Gmail Takeout

## Purpose

CDE Platform Stage 40 admits Google Takeout Gmail exports through the existing
evidence-first archive architecture. It adds another archive source, not another
governance model.

## Intake and Preservation

Administrator intake supports validated Takeout ZIP exports and extracted
Takeout directories. Uploaded ZIP bytes are preserved exactly and receive
SHA-256 and SHA-512. Directory selections are stored in a deterministic,
uncompressed governed envelope that retains each selected file byte-for-byte.
Unsafe paths, symlinks, encrypted entries, generic ZIP files, excessive archive
expansion, and configured resource-limit breaches are rejected.

The existing synchronous Document Intake maximum remains unchanged.
CDE Platform Stage 40 does not introduce Gmail API access or an unlimited upload route.

## Adapter Architecture

The source-neutral `ArchiveParser` contract is implemented by the built-in
`GmailTakeoutParser`. Gmail-specific parsing remains inside that adapter. The
adapter projects labels, threads, RFC 5322 message fields, bounded plain-text and
sanitised HTML views, and attachment metadata into the existing projection
shape. Existing Outlook parser behavior is unchanged.

## Identity and Relationships

One exported message retains one stable identity even when it appears under
multiple labels. Deterministic relationships connect:

```text
Archive -> Labels -> Threads -> Messages -> Attachments
```

The private relationship graph also reuses existing Person and Institution
nodes. Relationship generation is evidence-backed and deterministic; it adds no
inferred relationships and changes no public graph API semantics.

## Attachment and Promotion Reuse

Gmail attachments reuse CDE Platform Stage 39E attachment identity, SHA-256,
private storage, duplicate checks, inspection, and promotion eligibility.
Messages reuse CDE Platform Stage 39D governed promotion. Both workflows require
an authenticated administrator and explicit confirmation. No contained message
or attachment creates a Canonical Record automatically.

Promotion provenance retains the archive, labels, thread, message, attachment
where applicable, projection version, source hash, administrator, and promotion
timestamp. Canonical Records continue to use the ordinary lifecycle.

## Administrative Interfaces

Protected interfaces provide archive, label, thread, message, and attachment
inspection, metadata search, projection initiation, graph data, and eligible
promotion actions. Message body views are bounded projections. Attachment bytes
are not rendered or independently downloadable.

## Public Boundary

Public pages expose archive metadata only. They expose no Gmail labels, threads,
subjects, participants, message bodies, attachment data, private projection
APIs, promotion tools, or Takeout download. The preserved export remains the
authoritative evidence object.

## Compatibility

CDE Platform Stage 40 does not modify the Canonical Record lifecycle, Outlook
archive behavior, MBOX behavior, public publication workflow, verification
hashes, CREF methodology, or database schema. It adds no runtime dependency.
