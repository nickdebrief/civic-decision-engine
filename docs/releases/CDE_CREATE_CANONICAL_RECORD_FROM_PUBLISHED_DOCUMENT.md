# Create Canonical Record from Published Document

## Purpose

This stage adds an authenticated administrative workflow for cases where a
Published document already exists in the Public Document Library but no
corresponding canonical CDE record exists in the Public Record Index.

The workflow supports explicit administrator-controlled creation of a canonical
record from Published document context while preserving the distinction between:

- document: a published evidential artefact;
- record: a canonical civic or administrative event;
- association: an explicit governed relationship between them.

## Workflow

The Published document admin detail page now includes a **Canonical record**
section. When no source-linked canonical record exists, administrators can open:

`Create canonical record from this document`

The form is prefilled from safe Published document metadata and remains fully
editable before submission.

## Metadata Mapping

Where available, the workflow proposes:

- document title to record title;
- document description to record summary;
- institution/source to record institution, with specific extraction where the
  document title or description clearly identifies the public institution;
- document date to event date;
- category to a governed suggested record type;
- reference identifier to source-document provenance only.

For the Medical Council acceptance case, an Evidence Package document titled
`Initial Complaint Evidence Package - Medical Council of Ireland` proposes a
Complaint record with:

- title: `Initial Complaint to the Medical Council of Ireland`;
- institution: `Medical Council of Ireland`;
- event date: `2019-12-02`;
- summary describing the formal complaint and initial evidence package.

## Record Type Suggestion

Record type suggestion is governed by explicit category mapping. It does not use
semantic classification, OCR, body text interpretation, or AI inference.

The administrator must confirm or edit the proposed type before creation.

## Provenance

Created records store source-document provenance in record metadata:

- source document intake ID;
- source document reference identifier;
- source narrative noting creation from a Published document;
- source document SHA-256 as provenance text only.

The document SHA-256 is not reused as the record verification hash. The record
verification hash remains derived from the established canonical record inputs.

## Optional Association

The form offers an explicit **Create association to source document** option.
When selected, the workflow calls the existing Record-Document Association
creation path using:

- relationship type: `supporting_document`;
- the selected source Published document;
- the newly created canonical record;
- signed-session actor attribution.

Existing association validation remains authoritative. The workflow does not
bypass Published-only document eligibility, public-record eligibility,
duplicate-association prevention, lifecycle rules, access control, or public
visibility controls.

If the option is not selected, the record and document remain unassociated.

## Duplicate Safeguards

The form checks for exact source-linked records using stored source document
metadata. If a record may already exist for the Published document, the form
displays a warning. Fuzzy similarity does not block creation. Exact reference
reuse is blocked to avoid accidental superseding/versioning through this
workflow.

## Preserved Boundaries

This stage does not:

- automatically convert documents into records;
- publish documents or alter document lifecycle;
- copy document bytes into records;
- derive findings, conditions, or signals from OCR/body text;
- alter document SHA-256 values;
- alter record verification-hash semantics;
- rewrite existing references;
- merge document and record lifecycle state;
- create associations silently.

## Validation

Focused regression coverage confirms that:

- a Published document can open the canonical-record creation workflow;
- Medical Council evidence-package metadata is prefilled as a Complaint record;
- record type suggestion is governed and editable;
- created records receive their own canonical reference;
- source document reference is preserved as provenance only;
- document SHA-256 is not reused as the record verification hash;
- declining association creation leaves objects unassociated;
- optional association creation uses existing association validation;
- exact source-linked duplicate warnings are displayed;
- created Complaint records appear in the Public Record Index and association
  selector;
- existing Published document metadata and SHA-256 remain unchanged.
