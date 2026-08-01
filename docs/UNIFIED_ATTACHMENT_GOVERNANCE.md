# Unified Attachment Governance

## Purpose

CDE Platform Stage 42 provides one private attachment-governance layer for
Outlook PST/OST, Gmail Takeout, IMAP, and future archive adapters. It does not
add acquisition capabilities or alter the Canonical Record lifecycle.

## Identity and storage

An attachment's stable `ATT-...` identifier is derived from its SHA-256 digest.
The protected attachment store retains one binary object for identical content,
independent of filename, mailbox, or acquisition source. The object metadata
records SHA-256, SHA-512, size, filename, extension, MIME type, evidence status,
hash-verification status, and promotion history.

Every acquisition creates a separate immutable occurrence record. Occurrence
metadata records the originating archive, folder, thread, message, source
attachment identifier, acquisition source and time, extraction job, parser and
projection versions, and source archive digest. Duplicate storage is avoided;
duplicate provenance is not discarded.

Existing Stage 39E attachment stores remain readable. Existing Python imports
and administrative routes remain compatible while current acquisition adapters
write through the unified service.

## Relationship graph and inspector

The private administrative graph represents only evidenced relationships:

```text
Archive -> Folder -> Thread -> Message -> Attachment -> Canonical Record
```

The final relationship exists only after explicit promotion. The unified
Attachment Inspector shows normalized metadata, both hashes, provenance,
duplicate occurrences, promotion status, and Canonical Record linkage. It does
not render attachment content or expose a download.

## Promotion governance

Promotion reuses the established governed workflow. It requires an
administrator session and explicit confirmation, re-verifies stored size and
hashes, blocks duplicate Canonical Record creation, records the administrator
and timestamp, and preserves the complete source chain. No attachment is
promoted automatically or in bulk.

## Evidence boundary

Attachments remain private governed evidence objects. Public pages do not show
attachment content, previews, downloads, private graph nodes, or promotion
controls. Stage 42 introduces no schema migration, parser change, acquisition
workflow change, runtime dependency, or public evidence-boundary change.
