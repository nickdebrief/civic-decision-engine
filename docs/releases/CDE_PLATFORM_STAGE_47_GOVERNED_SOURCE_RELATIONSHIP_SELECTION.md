# CDE Platform Stage 47 — Governed Source Relationship Selection

## Purpose

CDE Platform Stage 47 makes the existing authoritative-source governance rule
explicit in the Record–Document Association workflow. Administrators can see
when a Canonical Record already has a source Published Document and are guided
toward an appropriate additional relationship.

## One Authoritative Source

A Canonical Record's persisted `source_document_id` and
`source_document_reference` fields identify the Published Document from which
the record was created. When either value is present, the association workflow:

- displays the authoritative source title and Document Identifier;
- links to the available Published Document;
- identifies Source document as already established;
- prevents a different document from receiving another Source document
  relationship;
- leaves Supporting document, Related document, and the other controlled
  relationship types available.

Records without persisted source provenance retain the existing Source document
option and behavior. The rule does not infer provenance from titles, dates,
institutions, or ordinary associations.

## Enforcement

The administrative form provides explanatory guidance and disables the Source
document option when the selected record already has an authoritative source.
The association service independently rejects direct create or update requests
that would establish a second source. Existing Source document associations are
not rewritten or disabled, and all existing associations remain unchanged.

## Governance Boundary

Stage 47 changes no Canonical Record or Published Document lifecycle, hashing,
verification, provenance meaning, association model, public URL, schema, or
public presentation. It adds no automation and assigns no relationship without
an explicit administrator action. It makes the established governance visible
and prevents accidental misuse of the authoritative source relationship.
