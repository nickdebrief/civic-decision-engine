# CDE Platform Stage 42 — Unified Attachment Governance

## Summary

CDE Platform Stage 42 consolidates attachment governance across Outlook
PST/OST, Gmail Takeout, and IMAP. Current and future archive adapters use one
source-neutral attachment service rather than source-specific identity,
storage, duplicate detection, graph, inspector, and promotion logic.

## Deterministic identity and duplicate detection

Each attachment receives an `ATT-...` identifier derived from SHA-256 and also
records SHA-512. Content-identical attachments share one protected binary
object across acquisition sources. Every source occurrence retains a separate,
immutable provenance record, so deduplication never erases evidential context.

## Normalized metadata and provenance

Governed metadata includes filename, extension, MIME type, size, both hashes,
originating archive, folder, thread and message, acquisition source and time,
and private evidence status. The source chain is retained through explicit
Canonical Record promotion and promotion history.

## Administrative graph and inspector

The private relationship graph uses source-neutral Attachment nodes and the
evidence-backed Archive, Folder, Thread, Message, Attachment, and promoted
Canonical Record chain. One Attachment Inspector shows normalized metadata,
hashes, duplicate references, provenance, promotion status, and Canonical
Record linkage for every acquisition source.

## Governance boundary

Promotion remains administrator-confirmed and reuses the existing Canonical
Record lifecycle and duplicate blocking. There is no automatic promotion,
attachment rendering, preview, independent download, or new public graph.
Public archive behavior remains metadata-only.

## Compatibility and exclusions

Stage 39E import names and stored metadata remain readable. Outlook, Gmail, and
IMAP acquisition contracts are unchanged. CDE Platform Stage 42 adds no database migration,
runtime dependency, acquisition source, parser behavior, or public API.
