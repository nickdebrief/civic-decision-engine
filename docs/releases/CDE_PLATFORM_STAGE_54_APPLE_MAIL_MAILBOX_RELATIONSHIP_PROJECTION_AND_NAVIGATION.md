# CDE Platform Stage 54 — Apple Mail Mailbox Relationship Projection and Navigation

## Purpose

CDE Platform Stage 54 makes the authoritative Apple Mail mailbox, its existing
contained-message projections, governed Email attachment relationships, and
independently preserved attachment Published Documents directly navigable in
the authenticated administrative interface.

This is a projection and navigation refinement only. The authoritative MBOX
remains the preserved evidence object, and contained messages remain bounded,
deterministic projections of that source.

## Deterministic projection identity

Contained messages continue to use the existing Stage 53 identity:

```text
{archive_intake_id}:message:{positive_message_index}
```

Message-ID is displayed only as source provenance because it may be absent or
duplicated. No second message identity, message Published Document, relationship
row, relationship type, or database schema is introduced.

## Administrative navigation

Matched Stage 53.1 message groups link to the existing authenticated archive
message route. The route resolves exactly one stored MBOX message projection by
positive numeric `message_index` and displays source-derived metadata,
structural parse status, digest, byte range, authoritative mailbox reference,
and only that message's governed attachment relationships.

The view does not render message bodies, HTML or plain-text previews, BCC, or
promotion controls. Unparsed projections remain navigable through verified
structural metadata and parser warnings; no missing headers are fabricated.

Attachment source rows can link back to a contained-message projection only
when existing relationship provenance has the exact mailbox-message identity.
Malformed or unresolved provenance is never matched heuristically.

## Read-only and bounded access

Administrative GET rendering reads the existing `metadata.json` without
assigning identifiers or persisting defaults. Attachment relationships are
queried through the existing indexed `source_email_object_id` lookup. Only the
selected message's attachment Published Document metadata is hydrated.

The authoritative MBOX bytes are not opened or reparsed. Viewing the projection
does not change metadata, registries, directories, lifecycle state, Published
Documents, Canonical Records, or relationships.

## Governance boundary

Stage 54 adds no public route and changes no publication behaviour. It does not
alter Stage 49 preservation, Stage 50 relationship semantics, Stage 53 identity,
Stage 53.1 grouping or pagination, hashes, verification, provenance, lifecycle,
backfill, Gmail, IMAP, PST/OST, or standalone `.eml`, `.msg`, and `.emlx`
behaviour.
