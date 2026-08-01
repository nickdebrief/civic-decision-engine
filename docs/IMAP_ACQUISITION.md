# Governed IMAP Acquisition

## Purpose

CDE Platform Stage 41 adds explicit administrator-controlled acquisition from
IMAP servers. It creates one bounded mailbox snapshot. It is not mailbox
synchronisation and does not schedule polling, monitoring, or automatic updates.

## Workflow

An authenticated administrator supplies an IMAP hostname, TLS mode, temporary
credentials, a governed mailbox identifier, and an explicit folder list. CDE:

1. establishes a TLS-protected IMAP session;
2. authenticates for the duration of the request;
3. enumerates available folders and verifies the requested folders;
4. selects each folder read-only;
5. records UIDVALIDITY and message UIDs;
6. retrieves exact RFC822 responses;
7. closes the selected mailbox and logs out;
8. creates an immutable governed acquisition envelope;
9. stores the envelope as ordinary Pending Intake;
10. creates private folder, thread, message, and attachment projections.

The acquisition is bounded by folder, message, message-size, attachment, and
archive-size limits. Existing synchronous Document Intake limits are unchanged.

## Evidence Envelope

The preserved ZIP envelope contains exact RFC822 message bytes and a deterministic
JSON acquisition manifest. The manifest records the acquisition identifier,
timestamp, server hostname, governed mailbox identifier, selected folders,
UIDVALIDITY values, UIDs, protocol mode, message byte counts, message hashes, and
an acquisition hash. The envelope receives the existing document SHA-256 and
SHA-512 verification values.

The envelope is the authoritative acquisition evidence. Projections are
replaceable administrative representations.

## Security

Credentials exist only in the active acquisition request. Passwords and login
usernames are never written to the evidence envelope, document metadata,
projection sidecars, attachment provenance, graph data, Canonical Records, logs,
or public pages. IMAP folders are selected read-only, and the client closes and
logs out on success or failure.

Only authenticated administrators can start or inspect acquisitions. Public
pages expose bounded acquisition metadata only. They expose no server
configuration, folder names, UIDs, messages, bodies, attachments, credentials,
promotion controls, or acquisition-envelope download.

## Projection and Governance

The adapter implements the existing `ArchiveParser` contract. Acquired content
maps into the existing source-neutral structure:

```text
IMAP Acquisition
  -> Folder
  -> Thread
  -> Message
  -> Attachment
```

Message identity is deterministic from acquisition identifier, folder, IMAP UID,
and Message-ID. Duplicate folder/UID pairs cannot create duplicate messages
within one acquisition.

Attachments reuse CDE Platform Stage 39E identifiers, SHA-256 verification,
private storage, duplicate checks, and explicit promotion. Messages reuse CDE
Platform Stage 39D promotion. Neither messages nor attachments are promoted
automatically.

## Administrative Routes

- `POST /api/admin/session/imap-acquisition` performs one explicit acquisition.
- `GET /admin/imap-acquisition/{document_id}` displays the private summary.
- `GET /api/admin/session/imap-acquisition/{document_id}` returns private status,
  hashes, provenance metadata, and statistics.
- Existing `/admin/archive/{document_id}/...` pages inspect folders, threads,
  messages, attachments, promotion eligibility, and private graph data.

Every route requires the existing authenticated administrator session.

## Relationship Graph

The private administrative graph adds IMAP Acquisition and Folder nodes and
reuses existing Thread, Email, Attachment, Person, Institution, and Intake Record
nodes. All relationships are deterministic and evidence-backed. The public graph
API and public archive presentation are unchanged.

## Intentional Exclusions

CDE Platform Stage 41 does not implement continuous synchronisation, IDLE,
scheduled polling, background monitoring, outbound email, credential storage,
OAuth provider integration, automatic publication, bulk promotion, or a new
Canonical Record type.
