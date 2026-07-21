# CDE v13.0.5 — Document Identifier on Intake

## Purpose

CDE v13.0.5 corrects the timing of governed Document identity assignment.
Every Document created through New Document Intake now receives a CDE-managed
Document Identifier before the first lifecycle event is recorded.

Identity must precede governance.

## Document Identifier

The Document Identifier is assigned by the Civic Decision Engine. It is:

- mandatory;
- immutable;
- generated automatically during successful intake persistence;
- stored on the Document metadata immediately;
- preserved through review, approval, publication, correction, association, and
  transmission inclusion.

Identifiers use the form:

```text
DOC-YYYY-NNNNNN
```

The sequence is backed by a small SQLite registry in the intake root. The
registry enforces uniqueness for both Document Identifier and intake identity,
and allocation is performed inside an immediate transaction so concurrent
document creation cannot reuse the same identifier.

## Optional Reference Identifier

The Optional Reference Identifier remains an external identifier supplied by an
administrator or source system. It may contain case references, receipt
references, archive references, message identifiers, or other pre-existing
labels.

It is not the governed Document identity and is not used as a fallback when
blank. A Document with no Optional Reference Identifier still has its own CDE
Document Identifier.

## Lifecycle Ordering

New Document Intake now follows this order:

```text
New Document Intake
  -> assign immutable Document Identifier
  -> record Pending Intake lifecycle event
  -> Under Review
  -> Approved
  -> Published
```

The initial Pending Intake event records the same Document Identifier that is
stored on the Document metadata.

## Legacy Backfill

Existing metadata that lacks a Document Identifier is backfilled safely when
documents are loaded, listed, or explicitly backfilled. Existing identifiers are
preserved and registered rather than replaced.

Backfill does not change:

- original file bytes;
- SHA-256 values;
- lifecycle state;
- lifecycle history except adding the missing identifier to the initial pending
  event;
- publication status;
- associations;
- transmissions;
- archive collection memberships;
- provenance fields unrelated to the missing identifier.

## Public and Administrative Surfaces

The Document Identifier is surfaced across:

- New Document Intake confirmation and review;
- Intake Management;
- Document Management;
- Public Document Library and public document detail pages;
- Record-Document Association selection and management;
- Public Transmission inclusion;
- Archive Collection member selection and presentation;
- Archive Explorer search and collection filtering.

The Optional Reference Identifier is labelled separately where displayed.

## Transmission Behaviour

Public Transmissions reference existing governed Documents. Transmission intake
accepts the existing Document Identifier for published documents, resolves it to
the existing Document object, and stores the existing relationship target. It
does not generate a new Document Identifier, duplicate document bytes, replace
the Document, or create a new governed Document identity.

## Governance Invariants

This correction does not change:

- document bytes;
- SHA-256 semantics;
- lifecycle states;
- publication rules;
- public eligibility;
- Record-Document Association semantics;
- Public Transmission identity;
- Canonical Record identity;
- Public Collection identity;
- storage filenames;
- authentication or authorization.

The change ensures that every later governance action references the same
independently governed Document identity that was assigned at intake.
