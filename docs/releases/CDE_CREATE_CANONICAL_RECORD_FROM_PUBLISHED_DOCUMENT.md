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

After creation, the document detail page replaces that action with **Canonical
Record Created**. The panel identifies the source-created record and provides
**Open Canonical Record** and **Manage Record–Document Associations** actions.
It does not infer source creation from an ordinary association.

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

The form preselects a mapped recommendation and displays **Recommended based on
Published Document category**. The selector is never locked. The administrator
may retain or replace the recommendation before creation, and the submitted
choice is authoritative.

| Published Document category | Recommended Canonical Record Type |
| --- | --- |
| Hospital Admission | Clinical Episode |
| Hospital Admission / Administrative Record | Clinical Episode |
| Admission Form | Clinical Episode |
| Consent Form | Clinical Record |
| Consent Form / Procedure Consent | Clinical Record |
| Operation Record | Treatment Episode |
| Operation Record / Procedure Record | Treatment Episode |
| Procedure Record | Treatment Episode |
| Pain Intervention Record | Medical Event |
| Pain Intervention Record / Clinical Procedure Record | Medical Event |
| Clinical Assessment | Clinical Record |
| Medical Report | Clinical Record |
| Discharge Summary | Care Episode |
| Post-Operative Instructions | Care Episode |

The pre-existing mappings for Evidence Package, Complaint, Investigation
Material, Decision, Submission, Proceeding, and Research remain unchanged. An
unmapped category retains the established default. No filename, body text, OCR,
machine learning, hidden inference, or background update contributes to the
recommendation. Composite values are mapped only when that exact normalized
category is explicitly registered; slash splitting, substring matching, and
fuzzy matching are not used.

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

The detail page and both protected creation routes check exact source linkage
using stored source document metadata. If a source-created record already
exists, the form is not rendered and POST submission cannot create another
record. The administrator is returned to an actionable existing-record panel.

If legacy data contains multiple directly source-created records, all are
listed with a warning and further creation is blocked. No record is deleted,
modified, or reconciled automatically. Fuzzy similarity and secondary
Record–Document Associations do not block creation. Exact reference reuse
remains independently blocked to avoid accidental superseding or versioning.

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
