# Governed Document Keywords

## Purpose

This stage adds a governed **KEYWORDS** field to Document Intake and Published
document metadata. Keywords are administrator-entered descriptive discovery
metadata used to improve search and selection without relying only on title,
description, filename, OCR text, or body text.

## Governance Boundary

Keywords do not:

- alter original document bytes;
- alter document SHA-256 values;
- establish evidential truth;
- create findings, conditions, or signals;
- change publication status;
- automatically create Record-Document Associations;
- replace title, description, institution/source, or category;
- infer meaning from OCR or document content.

Keywords must be entered or confirmed explicitly by an administrator.

## Storage and Normalisation

The implementation stores Keywords as a normalized keyword set while preserving
compatibility with the existing `tags` search representation. Existing documents
with no Keywords remain valid and behave as having an empty keyword set.

Keyword normalisation:

- accepts comma-separated input;
- trims leading and trailing whitespace;
- ignores empty entries;
- preserves meaningful multi-word phrases;
- removes exact duplicates case-insensitively;
- handles legacy strings, JSON arrays, lists, and missing values safely.

## Administration Workflow

Admin Document Intake now includes a **KEYWORDS** input near the document
metadata fields. The review page displays the normalized keyword set before
approval and publication.

Governed intake corrections can review and change Keywords through the existing
correction pathway. Corrected intakes preserve the exact source bytes and
SHA-256 while carrying the reviewed corrected keyword metadata.

## Public Document Library

Published document detail pages display Keywords when present. Empty keyword
sets are not rendered as public placeholder rows.

The Public Document Library search includes Keywords through the existing
`build_document_search_text()` helper. Keyword-only searches therefore locate
Published documents while preserving Published-only visibility and existing
pagination, filtering, ordering, and access-control behaviour.

## Association Selection

The Published Document selector in Record-Document Association creation already
reuses `build_document_search_text()`. Keyword-only searches therefore work in
the association workflow without duplicate search logic.

## Create Canonical Record From Published Document

The source Published document context now displays Keywords. They remain source
document metadata and are not automatically copied into record title,
institution, Conditions, Signals, or findings.

## Preserved Behaviour

This stage does not change:

- document bytes or SHA-256 calculation;
- supported upload formats;
- lifecycle states or transitions;
- approval or publication rules;
- public/private visibility boundaries;
- Public Document Library eligibility;
- record verification hashes;
- record Conditions or Signals;
- evidence handling;
- association storage or lifecycle;
- authentication or session behaviour.

## Validation

Focused tests cover keyword normalisation, intake entry, publication rendering,
Public Document Library search, association selector search, legacy no-keyword
documents, and governed correction preservation.
