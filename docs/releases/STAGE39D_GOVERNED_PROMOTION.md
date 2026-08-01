# CDE Platform Stage 39D — Governed Promotion

## Purpose

CDE Platform Stage 39D introduces an explicit administrative workflow for
promoting a selected Microsoft Outlook message projection into an ordinary
Canonical Record.

Promotion is an administrative governance decision. It is never triggered by
archive intake, inspection, projection, a background job, or a bulk operation.

## Governance Boundary

The preserved PST or OST archive remains the authoritative evidence object. A
contained mailbox message remains evidence within that unchanged archive. The
Stage 39C message projection is a bounded, replaceable administrative
representation of that source evidence and does not replace it.

A Canonical Record is a separate governance artefact. Promotion crosses this
boundary only when an authenticated administrator reviews the projected message,
opens the promotion form, supplies or confirms the Canonical Record metadata,
and explicitly confirms the action.

Promotion does not alter:

- archive bytes or archive hashes;
- extraction jobs;
- folder or message projections;
- parser behavior;
- mailbox ingestion;
- public archive rendering;
- the Mailbox Relationship Graph;
- the ordinary Canonical Record lifecycle.

## Promotion Workflow

An eligible projected message exposes **Promote to Canonical Record** in the
protected administrative Message Projection view. The view separates Message,
Metadata, Relationships, Preview, Provenance, and Promotion information.

The promotion form uses the existing Canonical Record fields and creation
service. It requires an explicit confirmation checkbox. The resulting record
uses the ordinary Canonical Record verification, versioning, search, and public
verification behavior.

Promotion is rejected when:

- the Outlook archive is unavailable or invalid;
- the projection is unavailable, incomplete, or inconsistent;
- archive inspection has not completed;
- the projected folder or message cannot be resolved;
- required source provenance or the archive SHA-256 is missing;
- the message projection has already been promoted;
- the administrator does not explicitly confirm promotion.

## Provenance

Every promoted Canonical Record stores structured promotion provenance in its
record metadata:

- Archive ID;
- Folder Projection ID;
- Message Projection ID;
- Message Identifier;
- Extraction Job;
- Promotion Timestamp;
- Administrator;
- Source Hash;
- Projection Version;
- promotion metadata version.

The Canonical Record also retains the archive as its source document. The public
source narrative states the governance boundary without exposing internal
projection identifiers or administrator identity. Full structured promotion
provenance remains administrative metadata attached to the Canonical Record.

## Administrative Responsibilities

The administrator remains responsible for deciding whether promotion is
appropriate and for reviewing the proposed title, institution, event date,
summary, trajectory, system state, conditions, and signals. Projected mailbox
metadata is not treated as a verified factual finding merely because it is
available to the workflow.

The system does not extract attachment content, create attachment evidence
objects, generate Canonical Records automatically, or publish projected mailbox
content. Public users continue to see only existing public archive metadata and
ordinary Canonical Records through their established routes.
