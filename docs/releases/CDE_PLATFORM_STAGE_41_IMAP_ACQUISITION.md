# CDE Platform Stage 41 — IMAP Acquisition

## Purpose

CDE Platform Stage 41 introduces explicit administrator-controlled acquisition
from IMAP servers through the existing governed archive architecture. It is an
acquisition milestone, not a synchronisation service.

## Architecture

The implementation uses Python's standard-library `imaplib` client and a new
adapter implementing the existing source-neutral `ArchiveParser` contract. No
runtime dependency or database migration is introduced.

One administrative action opens a TLS-protected, read-only IMAP session,
enumerates folders, acquires explicitly selected folders by UID, retrieves exact
RFC822 bytes, creates an immutable evidence envelope, and closes the session.
There is no scheduled polling, continuous monitoring, or automatic update.

## Provenance

The acquisition manifest records:

- acquisition identifier and timestamp;
- server hostname and governed mailbox identifier;
- selected folders;
- UIDVALIDITY values and UIDs;
- bounded protocol metadata;
- exact message sizes and SHA-256 values;
- the deterministic acquisition hash.

The preserved envelope also receives document SHA-256 and SHA-512 values. Every
folder, thread, message, and attachment projection remains traceable to the
acquisition and preserved archive.

## Security and Governance Boundary

Credentials are request-scoped only. Passwords and login usernames are not
stored in archives, metadata, projections, graph nodes, provenance, Canonical
Records, logs, or public output. Sessions close and log out on success and
failure.

The archive remains authoritative. Projections remain private administrative
representations. Message and attachment promotion remains an explicit existing
governance action. No Canonical Record is generated automatically.

## Integration

- folder and message projection reuse the Stage 39C model;
- message promotion reuses CDE Platform Stage 39D;
- attachment identity, hashing, and promotion reuse CDE Platform Stage 39E;
- private relationship graphs add acquisition, folder, thread, message, and
  attachment relationships without changing the public graph;
- public pages remain metadata-only and provide no acquisition archive download.

## Intentional Exclusions

CDE Platform Stage 41 does not implement mailbox synchronisation, IMAP IDLE,
scheduled polling, OAuth provider integrations, sending email, public mailbox
browsing, public message bodies, public attachments, or automatic promotion.
