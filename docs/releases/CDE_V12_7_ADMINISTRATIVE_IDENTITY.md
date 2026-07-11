# CDE v12.7 — Administrative Identity

## Purpose

CDE v12.7 makes the authenticated administrator identity visible inside the
Administration Console and improves readability of the existing document
lifecycle-history Actor column.

This stage follows CDE v12.6, which introduced named administrator
authentication using `ADMIN_USERNAME` and `ADMIN_PASSWORD`, and CDE v12.6.1,
which confirmed that the legacy `CDE_ADMIN_PASSWORD` variable has no active
runtime dependency and aligned active Administration Console terminology with
Public Document Library.

## Authenticated Identity Display

Authenticated Administration Console pages now show a restrained identity
indicator:

`Signed in as: <authenticated username>`

The username is rendered only after successful authentication. It is derived
from the signed server-side administrator session and is not taken from query
parameters, request bodies, form fields, headers, or client-supplied actor
values.

The unauthenticated login page does not expose the configured administrator
username, password, tokens, environment configuration, or session contents.

## Session-Derived Identity

The identity display uses the same protected administrator-session mechanism as
new lifecycle actor attribution. The plaintext password is never stored in the
session and credential values are not rendered into HTML.

## Actor Attribution Integrity

New document-intake and lifecycle-history events continue to use the
authenticated administrator username from the signed session. Administrative
forms do not include an editable actor field, and client-supplied actor or
username values cannot override attribution.

## Historical Actor Preservation

Historical lifecycle entries are preserved exactly as recorded. Earlier generic
actor values such as `admin` are not migrated, normalised, relabelled, or
reinterpreted. Newer entries continue to reflect the authenticated username
held in the signed session.

## Actor-Column Readability

The active document lifecycle-history table now includes semantic styling hooks
for the Actor and Note columns. The Actor column receives a sensible minimum
width so the Actor heading and ordinary values such as `admin` and named
administrator usernames remain readable under normal desktop layouts.

Longer actor identifiers are allowed to wrap safely rather than overflow the
page, and note text remains visible without truncation.

## v12.8 Boundary

CDE v12.7 does not implement the broader audit-table standardisation planned
for CDE v12.8 — Administrative Audit Traceability. It does not add an audit
log page, event search, filtering, exports, pagination, actor profiles, roles,
or multiple administrator accounts.

## Security and Governance Boundaries Preserved

CDE v12.7 does not change:

- `ADMIN_USERNAME` or `ADMIN_PASSWORD` handling;
- credential validation;
- fail-closed configuration behaviour;
- session signing or logout semantics;
- lifecycle states or valid transitions;
- intake, review, approval, rejection, publication, or archiving behaviour;
- approval/publication separation;
- Public Document Library behaviour;
- public document search, detail pages, PDF downloads, or public provenance;
- public verification;
- SHA-256 hashing;
- storage paths;
- non-mutation controls;
- document metadata;
- database schema or database behaviour;
- record, attachment, or classification behaviour;
- public API behaviour;
- public footer navigation; or
- public/private visibility boundaries.

Private and unpublished documents remain protected, and public routes do not
expose internal administrative actor data.

## Tests and Validation

Focused tests cover:

- signed-in identity display on authenticated Administration Console pages;
- absence of configured usernames and secrets on the unauthenticated login
  page;
- identity derivation from the signed session rather than client-supplied
  values;
- logout clearing authenticated identity state;
- lifecycle actor attribution from the authenticated session;
- preservation of historical actor values;
- Actor-column styling hooks and readable table structure;
- safe display of longer actor identifiers;
- unchanged lifecycle behaviour;
- approval/publication separation;
- unchanged Public Document Library behaviour;
- protected private and unpublished documents; and
- unchanged public footer navigation.

Validation run for this release:

- `python3 -m unittest tests.test_admin_session`
- `python3 -m unittest tests.test_admin_navigation_console`
- `python3 -m unittest tests.test_admin_document_intake`
- `python3 -m unittest tests.test_public_document_library`
- `python3 -m unittest tests.test_public_footer_administration_link`
- `python3 -m unittest discover -s tests`
- `git diff --check`
- repository conflict-marker check
- repository checks for client-supplied actor fields and unauthenticated
  `ADMIN_USERNAME` rendering
