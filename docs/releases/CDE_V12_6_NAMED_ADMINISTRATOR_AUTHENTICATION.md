# CDE v12.6 — Named Administrator Authentication

## Purpose

CDE v12.6 aligns Administration Console authentication with named administrative
attribution. The Administration Console now requires both a configured username
and a configured password before protected administrative access is granted.

This stage supports governed document intake, review, approval, controlled
publication, archiving, internal notes, and lifecycle history by retaining the
authenticated administrator username in the protected session and using that
username for newly created administrative actor fields.

## Previous Model

Earlier CDE administration used password-only authentication for the unified
Administration Console. Administrative lifecycle entries created through the
authenticated workflow used a generic actor value.

## Configuration

CDE v12.6 reads administrative credentials from environment variables:

- `ADMIN_USERNAME`
- `ADMIN_PASSWORD`

Both variables are required. If either variable is absent or empty,
administrative authentication fails closed. CDE does not provide default
credentials and does not retain a password-only fallback.

The environment variable names are documented for deployment configuration only.
Credential values must not be committed, logged, rendered, or exposed through
HTML, URLs, cookies, responses, documentation, or test output.

## Login Behaviour

The browser-facing Administration Console login form now contains:

- a required username field using `autocomplete="username"`; and
- a required password field using `autocomplete="current-password"`.

Authentication succeeds only when both submitted values match the configured
environment variables. Incorrect username, incorrect password, missing username,
missing password, and missing configuration all fail with a generic error. The
login flow does not disclose which credential was incorrect.

The existing API login endpoint remains available for programmatic callers, but
it now requires both username and password. Password-only authentication no
longer succeeds.

## Session Handling

Successful authentication stores administrator state using the existing signed
session cookie architecture. The signed session payload contains the
administrator role, the authenticated username, and the existing issue/expiry
timestamps.

The plaintext password is not stored in the session. Credentials are not placed
in URLs, query parameters, client-editable form fields, or public output.

## Named Administrative Attribution

New administrative document-intake and lifecycle-history entries created after
v12.6 use the authenticated username from the protected server-side session as
the actor value.

Actor identity is not accepted from client-submitted form fields. Historical
records that already contain the previous generic actor value are preserved and
are not rewritten or migrated.

## Security And Compatibility Boundaries

CDE v12.6 does not change:

- document intake storage;
- review, approval, rejection, publication, or archive lifecycle rules;
- the separation between approval and publication;
- public/private visibility boundaries;
- Public Document Library behaviour;
- public document search, filtering, detail pages, or PDF downloads;
- SHA-256 hashing or verification;
- path-based private storage;
- record, attachment, evidence, relationship, classification, or database
  behaviour;
- public API behaviour; or
- public footer navigation.

Private and unpublished intake documents remain protected. Only documents whose
lifecycle state is Published remain eligible for the Public Document Library.

## Tests

Focused tests cover:

- username and password fields on the login page;
- required autocomplete attributes;
- correct username/password authentication;
- rejection of all incorrect, missing, empty, password-only, or default
  credential attempts;
- fail-closed behaviour when credential variables are absent or empty;
- generic failed-login output;
- signed session username retention;
- absence of plaintext password from the session;
- logout and protected-route behaviour;
- named actor attribution for new lifecycle entries;
- preservation of historical generic actor values;
- rejection of client-supplied actor override attempts;
- document lifecycle compatibility;
- Public Document Library compatibility; and
- public footer navigation compatibility.

## Validation Results

Validation for this stage should include:

- focused authentication tests;
- Admin Document Intake tests;
- Public Document Library tests;
- public footer-navigation tests;
- full regression suite;
- `git diff --check`; and
- conflict-marker check.

No schema, database, hash, evidence, lifecycle, publication, record, attachment,
classification, API, or public/private visibility behaviour is changed by this
stage beyond named administrator authentication and named actor attribution for
new administrative history entries.
