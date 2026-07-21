# CDE v13 — Document Identifier Intake Correction

## Purpose

This focused v13 correction ensures that every governed Document receives a
Civic Decision Engine Document Identifier when the New Document Intake record is
first created. The identifier is assigned before the initial Pending Intake
lifecycle event is recorded, so every later governance action can refer to the
same independently governed Document identity.

## Identity Model

Document Identifier is CDE-assigned, mandatory, immutable, and generated
automatically. It is the internal governed identity for the Document across
intake, review, approval, publication, associations, transmissions, collections,
search, and public document views.

Optional Reference Identifier remains external, optional, and descriptive. It
may record a source-system reference, archive reference, receipt reference,
Message-ID, case reference, or other pre-existing identifier. It never replaces
and is never used as a fallback for the CDE Document Identifier.

## Identifier Assignment

Successful New Document Intake now assigns a human-readable identifier such as
`DOC-2026-000001` after file validation and SHA-256 calculation, and before the
initial Pending Intake lifecycle event is persisted. The identifier is written
to document metadata and included in the first lifecycle event.

Identifier allocation is backed by a small SQLite registry under the governed
intake root. The registry enforces uniqueness for both the generated Document
Identifier and the associated intake id. Allocation uses an immediate database
transaction so concurrent document creation cannot reuse the same identifier.

## Backward Compatibility

Existing document metadata that lacks a Document Identifier is backfilled safely
when loaded, listed, or explicitly backfilled. Existing identifiers are
preserved. The correction does not alter source bytes, stored filenames,
SHA-256 values, lifecycle history, publication status, associations,
transmissions, collection memberships, or public eligibility.

## Immutability

Metadata updates, notes updates, lifecycle transitions, publication, correction
workflows, association creation, and transmission inclusion do not regenerate or
replace the Document Identifier. Later metadata writes preserve the existing
identifier even if submitted metadata omits or attempts to alter it.

## Associations and Transmissions

Record-Document Associations and Public Transmissions can resolve Published
Documents by the CDE Document Identifier while continuing to store and route to
the existing governed document object. Including a Document in a Transmission
does not create a new Document Identifier, duplicate the Document, replace the
original bytes, or change the Document SHA-256.

## User Interface

Administrative and public views now distinguish:

- Document Identifier: CDE-assigned, permanent, immutable.
- Optional Reference Identifier: external identifier, when available.

The Document Identifier appears in Document Intake Review, Intake Management,
public Published Document views, Record-Document Association interfaces,
Collection member selectors, and Transmission governed-object inclusion views.

## Governance Invariants

This correction does not redesign transmissions, records, associations,
collections, publication rules, lifecycle states, storage, file validation,
provenance, or SHA-256 semantics. It only makes the Document's intrinsic CDE
identity explicit from the moment the Document enters governed intake.
