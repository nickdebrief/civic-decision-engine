# CDE Platform Stage 55 — Attachment Published Document Source Context and Navigation

## Purpose

CDE Platform Stage 55 completes the attachment-document side of the governed
relationship navigation. When an administrator views an independently preserved
attachment Published Document, the interface now makes its source context
immediately understandable and navigable.

This is a **presentation/navigation refinement only**. It does not change the
evidence model, preservation architecture, relationship schema, hashing,
verification, provenance, lifecycle, publication semantics, or Canonical Record
behaviour.

## Implementation

- The admin intake review page for `document_type == "email_attachment"` now
  renders a **Source Context** section instead of the pre-Stage-50 raw
  relationship table.
- Each governed source relationship is rendered as a compact source-context
  card showing verified provenance: relationship type, source type/pathway,
  source document identifier, attachment index, extraction status, and where
  applicable, contained message index and subject.
- Navigation actions derive **strictly from exact governed identifiers** — never
  from heuristics (filename, subject, sender, hashes, or Message-ID alone).
- Source documents are hydrated **read-only** via `load_pending_document_read_only`,
  ensuring the admin GET never triggers identifier assignment or metadata writes.
- `list_attachment_sources` gains backward-compatible `load_documents` and
  `read_only` opt-in parameters (mirroring the pattern established by
  `list_archive_attachments` and `hydrate_attachment_documents`).

## Source-Type Navigation

- **Standalone EML/MSG/EMLX** (`published_document`): "Open source document" →
  `/admin/document-intake/{source_email_document_id}`.
- **MBOX contained message** (`mailbox_message`): "Open message projection" via
  the existing Stage 54 helper, plus "Open authoritative mailbox" →
  `/admin/document-intake/{source_archive_identifier}`.
- **Gmail/IMAP/PST/OST** (`projected_message`): "Open message projection" using
  the existing archive message-projection route when the
  `{archive_id}:message:{projection_id}` format matches safely.

## Public Boundary

Stage 55 is **admin-only**. The public attachment Published Document page is
unchanged. No private source-email or mailbox context is exposed publicly.

## Governance Statement

Objects remain independent. Relationships preserve context. This stage changes
neither Canonical Record governance nor the meaning of publication, provenance,
hashing, verification, or source-document relationships.
