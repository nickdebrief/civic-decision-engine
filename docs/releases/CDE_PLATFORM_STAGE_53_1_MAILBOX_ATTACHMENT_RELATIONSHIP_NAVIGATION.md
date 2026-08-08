# CDE Platform Stage 53.1 — Mailbox Attachment Relationship Navigation

## Purpose

CDE Platform Stage 53.1 makes governed attachment relationships navigable at
mailbox scale. Stage 53 established authoritative Apple Mail `.mbox`
preservation and reused the existing governed relationship model for every
contained attachment occurrence. This stage changes the authenticated
administrative presentation only; it does not change preservation or evidence.

## Mailbox-aware navigation

For an MBOX Published Document, the administrative Governed Email Attachment
Relationships section now projects the existing relationship provenance into
message groups. A relationship is matched only when its
`source_email_object_id` has the exact form
`{archive_intake_id}:message:{positive_message_index}` and that index identifies
one existing mailbox message projection. No subject, Message-ID, filename, or
other heuristic matching is performed.

Matched groups display the existing message index, decoded subject, sender and
date metadata, plus the governed attachment relationship count. Native HTML
`details` and `summary` elements provide keyboard-accessible, no-JavaScript
progressive disclosure. Message bodies are not displayed.

Relationships that cannot be matched safely remain visible in a deterministic
**Unresolved message relationship** group. Failed preservation relationships
also remain visible and continue to omit false Published Document links.

## Ordering, pagination and loading

- Message groups are ordered by numeric `message_index`.
- Relationships within each group are ordered by numeric `attachment_index`,
  then `relationship_id`.
- The unresolved group follows matched messages.
- Pagination keeps each message and all of its attachment relationships
  together. It defaults to 25 message groups and is bounded at 100.
- The archive relationship query first returns lightweight relationship rows.
  Only attachment documents belonging to groups on the visible page are loaded,
  using read-only metadata access.

Standalone `.eml`, `.msg`, and `.emlx` evidence continues to use the unchanged
Stage 50 flat administrative presentation.

## Governance boundary

Stage 53.1 is a presentation/navigation refinement only. It introduces no
schema, migration, backfill, relationship, identity, hashing, provenance,
verification, lifecycle, Canonical Record, publication, parser, or public-route
change. Existing Stage 53 relationships work without modification, and viewing
the administrative page does not mutate relationship or source metadata.
