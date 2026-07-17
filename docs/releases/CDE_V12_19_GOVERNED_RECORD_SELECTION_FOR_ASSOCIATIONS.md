# CDE v12.19 — Governed Record Selection for Record–Document Associations

## Purpose

CDE v12.19 corrects a usability and validation weakness in the authenticated
Create Record–Document Association workflow. The previous interface accepted a
free-text record reference. The backend rejected invalid values, but the form
allowed administrators to submit document references, display labels, multiple
references, proposed references, or malformed text before receiving a backend
error.

This stage introduces governed record selection. It remains a guided-selection
and validation stage only.

## Problem Identified

One association connects one existing public CDE record to one existing
Published document. A free-text record field made object boundaries easy to
blur because record references, document references, and display labels could
all be typed into the same input.

The interface now makes those object boundaries explicit.

## Record and Document Reference Distinction

The create form distinguishes:

- Public CDE record
- Published document
- Relationship type
- Public label
- Public visibility
- Public note
- Administrative note

Readable option labels may include both the canonical record reference and a
record summary. The submitted value is only the canonical stored record
reference.

## Replacement of Free-Text Entry

The previous free-text `Record reference` input has been replaced by a
server-rendered `Public CDE record` selector.

The selector is populated from existing eligible public CDE records using
deterministic reference ordering. It does not expose private, superseded, or
otherwise ineligible records in the association creation form.

## Public-Record Eligibility

The selector includes only records that are currently eligible under the
existing public-record boundary:

- the record exists;
- the record has a canonical reference;
- the record is the current latest public record used by the Public Record
  Index.

Backend validation remains authoritative and confirms the submitted reference
again before creating an association.

## Exact Canonical Reference Submission

Only harmless leading or trailing whitespace is trimmed. The backend does not:

- remove display prefixes;
- split references;
- perform fuzzy matching;
- accept partial matches;
- convert document references into record references;
- silently select a first match.

The submitted record reference must exactly match one eligible stored public
record reference after trimming.

## One-Record-Per-Association Rule

The create endpoint rejects obvious multiple-reference submissions containing
commas, semicolons, newlines, or carriage returns. It does not create multiple
associations automatically.

Each association remains one governed object connecting one public CDE record
to one Published document.

## Backend Validation Retained

Server-side validation rejects:

- missing record references;
- unknown record references;
- stored but non-public record references;
- display labels submitted as values;
- prefixed labels such as `Record REC-...`;
- document references submitted as record references;
- comma-separated, semicolon-separated, newline-separated, or carriage-return
  separated references;
- partial matches.

No association is created when validation fails.

## Document Reference Misuse

When a crafted authenticated submission provides a Published document reference
identifier as the record reference, the backend returns the clearer validation
error `association_record_reference_is_document`.

This check is limited to authenticated administration and does not expose
private document information publicly.

## Empty-State Behaviour

If no eligible public CDE records exist, the create page shows:

`No eligible public CDE records are currently available for association.`

The form does not provide a misleading empty selector and does not offer to
create an arbitrary record from the association workflow.

## Accessibility

The selector uses standard HTML form controls, has an explicit label, remains
keyboard accessible, preserves focus behaviour, and does not require a new
JavaScript dependency or external UI library.

## Unchanged Association Semantics

CDE v12.19 does not change:

- association identity;
- association lifecycle;
- public association references;
- association history;
- actor attribution;
- controlled relationship types;
- duplicate-association behaviour;
- public label or public note behaviour;
- administrative note behaviour;
- record identity;
- document identity;
- record lifecycle;
- document lifecycle;
- record verification hashes;
- document SHA-256 values;
- publication behaviour;
- evidence handling;
- Public Record Index behaviour;
- Public Document Library behaviour;
- Archive Collections;
- Collection Memberships;
- ordered collection sequence;
- authentication;
- public/private visibility boundaries.

## Validation Results

Validation performed for this stage:

- Focused governed record-selection tests: 6 passed.
- Adjacent association, administration, audit, document-library, collection,
  and footer tests: 273 passed.
- Full regression suite: 513 passed.
- Python compile check: passed.
- `git diff --check`: passed.
- Conflict-marker check: passed.
