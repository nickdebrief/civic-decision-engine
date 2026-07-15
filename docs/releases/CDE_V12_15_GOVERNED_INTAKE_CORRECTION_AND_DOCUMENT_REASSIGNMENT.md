# CDE v12.15 — Governed Intake Correction and Document Reassignment

## Purpose

CDE v12.15 introduces a governed correction and reassignment workflow for the
specific case where an archived Document Intake record preserved the correct
uploaded bytes but assigned them to incorrect metadata.

The stage provides an administrative way to create a corrected intake identity
from the same preserved bytes without rewriting the archived source intake,
weakening duplicate detection, changing SHA-256 provenance, or bypassing the
ordinary document lifecycle.

## Why It Matters

Document intake now supports PDF, JPEG, and PNG records and may be used for
large public archives. If a document is uploaded with incorrect title,
reference, institution, category, description, or notes, CDE must preserve both
facts:

- the original archived intake existed and remains part of the administrative
  record;
- the exact same uploaded bytes may need to continue under corrected metadata.

CDE v12.15 makes that correction visible, reviewable, and attributable.

## Correction Model

The new correction object is stored separately from Document Intake records in:

- `document_intake_corrections`
- `document_intake_correction_history`

Correction references are generated server-side using the format:

```text
CDE-CORR-YYYYMMDD-NNN
```

The reference is not accepted from the client and is distinct from:

- intake IDs;
- SHA-256 digests;
- record references;
- document reference identifiers;
- association references;
- collection references.

## Eligible Source Records

A correction can start only from an existing archived intake record.

The source intake must:

- exist;
- have lifecycle status `archived`;
- retain a valid SHA-256 digest;
- have its stored file present in private intake storage;
- not already have another active non-cancelled correction.

Pending, Under Review, Approved, Published, and Rejected records are not
eligible as correction sources.

## Correction Lifecycle

CDE v12.15 uses a dedicated correction lifecycle:

```text
draft
→ under_review
→ reviewed
→ authorised
→ completed
```

Cancellation is available from:

- `draft`
- `under_review`
- `reviewed`

Execution is available only after authorisation. Invalid transitions are
rejected and do not alter the source intake, destination intake, or correction
history.

## Execution Behaviour

When an authorised correction is executed, CDE creates a new corrected intake
identity from the exact same preserved uploaded bytes.

The destination intake:

- receives a new intake ID;
- preserves the source SHA-256 digest;
- stores the same original filename;
- stores the same validated document type;
- preserves exact original bytes;
- starts in ordinary `pending` state;
- records correction lineage metadata;
- enters the existing Document Intake lifecycle without automatic review,
  approval, publication, or public exposure.

The archived source intake:

- remains archived;
- retains its original metadata;
- retains its original status history;
- retains its original actor values;
- is not migrated, deleted, overwritten, or relabelled.

## Duplicate Detection

Ordinary duplicate intake detection remains unchanged.

CDE v12.15 does not weaken the existing `document_intake_duplicate` rule for
normal uploads. The governed correction execution path is the only path that may
create a second intake identity from preserved bytes already present in private
intake storage, and it does so only after the correction has been reviewed and
authorised.

## Actor Attribution

All correction actions derive actor identity from the authenticated signed
administrator session:

- correction creation;
- review start;
- reviewed state;
- authorisation;
- execution;
- completion;
- cancellation.

Actor identity is not accepted from form fields, query parameters, request
bodies, filenames, uploaded metadata, or client-supplied headers.

Historical intake actor values remain unchanged.

## Administration Console

CDE v12.15 adds an authenticated Administration Console section:

```text
/admin/intake-corrections
```

The correction pages provide:

- correction index;
- filters by correction reference, source intake, destination intake,
  correction type, correction state, actor, created date, and completed date;
- correction detail view;
- source intake context;
- proposed corrected metadata;
- destination intake context after execution;
- immutable correction pathway;
- lifecycle action forms for valid correction transitions only.

The shared Administration Console navigation now includes **Intake
Corrections**.

## Source and Destination Lineage Notices

Document Intake Review pages now display correction lineage where applicable.

Archived source intakes may display:

- a link to begin a governed correction when eligible;
- an in-progress correction notice;
- a completed correction notice linking to the correction and corrected intake.

Corrected destination intakes display that they were created through a completed
governed correction, with links back to the correction and archived source
intake.

## Archive Collection Table Refinement

CDE v12.15 also includes a narrow presentation repair for the CDE v12.14
Archive Collections administrative table.

The change:

- gives date range, visibility, and status columns practical minimum widths;
- prevents ordinary labels from collapsing into unreadable fragments;
- keeps collection history state JSON available through expandable details;
- avoids letting raw state JSON dominate the history table.

This is a presentation-only refinement. It does not change collection storage,
history, public eligibility, collection references, or public routes.

## Security Boundaries

CDE v12.15 preserves:

- named administrator authentication;
- signed-session actor attribution;
- private intake storage;
- unpublished document privacy;
- Published-only public document eligibility;
- approval/publication separation;
- exact-byte SHA-256 provenance;
- existing storage path boundaries;
- existing public/private visibility rules.

No correction route is public. Public users cannot create, inspect, execute, or
enumerate governed corrections.

## Explicit Non-Changes

CDE v12.15 does not change:

- document upload validation;
- supported file formats;
- magic-byte detection;
- extension/type matching;
- ordinary duplicate upload detection;
- source document bytes;
- destination document bytes;
- SHA-256 calculation;
- document lifecycle states;
- document lifecycle transitions;
- approval/publication separation;
- Public Document Library eligibility;
- Publication Provenance;
- Publication Pathway;
- Administrative Audit;
- record verification;
- evidence handling;
- record hashing;
- association behaviour;
- collection public behaviour;
- image view/download behaviour;
- PDF download behaviour;
- database records unrelated to the correction tables;
- public footer navigation;
- public/private visibility boundaries.

## Validation Results

Focused validation added or updated:

- governed correction schema creation and idempotency;
- archived-source eligibility;
- rejection of non-archived source records;
- correction lifecycle transitions;
- authorisation-before-execution boundary;
- exact-byte destination intake creation;
- unchanged source intake metadata and history;
- unchanged source and destination SHA-256 digest;
- ordinary duplicate detection preservation;
- session-derived correction actors;
- rejection of client-supplied actor overrides;
- source and destination lineage notices;
- correction index filters;
- Archive Collection administrative table presentation refinement.

Validation commands:

```text
python3 -m unittest tests.test_governed_intake_corrections
python3 -m unittest tests.test_admin_document_intake
python3 -m unittest tests.test_governed_archive_collections
python3 -m unittest discover -s tests
git diff --check
```

## Implementation Summary

CDE v12.15 adds a correction module, authenticated correction routes, correction
rendering helpers, focused tests, README documentation, and this release note.
It extends the existing Administration Console rather than creating a separate
administrative system.
