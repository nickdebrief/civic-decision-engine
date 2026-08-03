# CDE Platform Stage 45 — Canonical Record Creation State on Published Documents

## Purpose

CDE Platform Stage 45 completes the Published Document to Canonical Record
workflow by making the document detail state reflect an existing source-created
Canonical Record. The change makes the persisted provenance relationship
visible and prevents accidental repeat creation.

## Workflow State

Before source creation, the protected Published Document administration area
offers **Create canonical record from this document**. The existing editable
creation workflow and advisory Record Type recommendation remain unchanged.

After creation, the action is replaced by **Canonical Record Created** and the
resulting record's reference, type, title, institution, event date, trajectory,
and system state are shown where available. Administrators can open the record
or manage its Record–Document Associations.

## Authoritative Relationship

State is determined only from the persisted `source_document_id` and
`source_document_reference` recorded by the creation pathway. Titles, dates,
institutions, and ordinary Record–Document Associations are not used to infer
source creation. A secondary association therefore does not suppress the
creation action.

## Duplicate Protection

The protected GET and POST creation routes use the same source lookup as the
detail page. If a source-created Canonical Record already exists, the form is
not rendered and a further record is not created. The administrator receives a
clear status panel with a link to the existing record.

If legacy data contains multiple directly source-created records, all records
remain unchanged and are listed with an administrative warning. Further
creation is blocked; Stage 45 performs no automatic reconciliation.

## Governance Boundary

Stage 45 introduces no hidden automation and changes no Published Document or
Canonical Record lifecycle, hashing, verification, provenance semantics,
public URL, or Record–Document Association behaviour. It adds no database
schema or dependency. Existing records and evidence bytes remain unchanged.

## Validation

Focused tests cover empty state, populated state, record details and links,
direct GET and POST protection, secondary-association separation, legacy
multiple-record handling, authentication, and existing creation behaviour. The
stage ledger validator and full regression suite remain authoritative release
gates.
