# CDE Platform Stage 39E — Attachment Governance

## Purpose

CDE Platform Stage 39E establishes extracted Outlook email attachments as
private governed evidence objects. It assigns immutable identity and provenance
without publishing attachment content or automatically creating Canonical
Records.

## Attachment Identity

An extraction worker admits attachment bytes through a bounded governance
boundary after Outlook archive inspection and message projection have completed.
The service records:

- a stable `ATT-` identifier derived deterministically from the evidence location
  and attachment digest;
- SHA-256 over the exact extracted bytes;
- byte size, original filename, and MIME type;
- extraction timestamp and hash-verification status;
- the archive, folder projection, message projection, source attachment
  identifier, extraction job, parser version, and projection version.

The private original bytes are stored separately from Canonical Records under
the governed Document Intake storage root. Files use application-generated paths
and restricted permissions. No attachment download route is exposed.

## Relationship Graph

The protected administrative attachment graph exposes deterministic nodes and
evidence-backed relationships for the originating message, archive, institution,
and message participants. It adds `Has Attachment`, `Attached To`, and `Belongs
To Archive` relationships. Institution and person relationships are emitted only
from existing archive and message metadata. No relationship is inferred by AI or
probability.

The public MBOX relationship graph and its API are unchanged.

## Attachment Inspector

Authenticated administrators can inspect the attachment identifier, filename,
MIME type, SHA-256, byte size, originating archive and message, extraction time,
promotion status, and any existing Canonical Record. The Inspector provides no
attachment rendering or download.

## Governed Promotion

`Promote Attachment` is available only when extraction completed, SHA-256 and
size verification pass, projection provenance remains valid, and no Canonical
Record already represents the same attachment digest. The administrator must
explicitly confirm promotion.

Promotion reuses the ordinary Canonical Record lifecycle. Structured provenance
permanently records:

```text
Archive
  ↓
Folder Projection
  ↓
Message Projection
  ↓
Attachment
  ↓
Canonical Record
```

The attachment identifier and SHA-256 remain unchanged after promotion. An
identical SHA-256 blocks duplicate Canonical Record creation and identifies the
existing Canonical Record for administrative review.

## Governance Boundary

The preserved PST/OST archive remains authoritative evidence. Message and folder
projections remain private, derived administrative representations. Governed
attachments remain private evidence objects. A Canonical Record is created only
through an explicit administrator decision and remains a separate governance
artefact.

Stage 39E does not change archive preservation, parser integration, extraction
jobs, the projection schema, Canonical Record lifecycle, publication workflow,
public archive behaviour, verification hashes, or the independent CREF
methodology. It introduces no dependency and no database migration.
