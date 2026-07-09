# CDE v12.5.3 — Footer Administration Link UI Fix

## Objective

CDE v12.5.3 corrects the public footer Administration link introduced in
CDE v12.5.2. The correction keeps the link discreet, opens the existing
authenticated administration entry point in a new tab, and ensures normal
browser users see the existing admin login UI rather than raw unauthorized
JSON.

## Issues Fixed

- The Administration footer link now uses the same `public-footer-link` visual
  treatment and footer-scale text size as the existing public footer links.
- The link remains directly beneath the right-hand footer identity statement:
  `Civic Decision Engine v12 — The record does not argue.`
- The link opens `/admin` with `target="_blank"` and
  `rel="noopener noreferrer"`.
- Unauthenticated browser access to `GET /admin` renders the existing admin
  login page instead of `{"detail":"admin_session_unauthorized"}`.

## Admin Login UI Behaviour

`GET /admin` still checks the existing signed admin session. If a valid session
is present, the route renders the CDE Administration Console. If no valid
session is present, the browser-facing route renders the same login UI exposed
at `GET /admin/login`.

The lower-level authentication helper and API/session routes retain their
existing unauthorized behavior.

## Security Boundary

This stage does not change authentication, authorization, session cookies,
admin credentials, document intake, approval workflow, publication rules,
archival behaviour, public records, attachments, evidence relationships,
classification logic, verification hashes, database state, or public API
behaviour.

The public footer does not expose private records, intake data, review queues,
lifecycle information, evidence, administrative counts, or admin session state.

## Tests

Focused tests verify:

- the Administration footer link targets `/admin`;
- the link includes `target="_blank"`;
- the link includes `rel="noopener noreferrer"`;
- the link uses existing footer-link styling;
- unauthenticated browser access to the linked route renders login UI rather
  than raw JSON;
- authenticated administrators still reach the CDE Administration Console;
- no private administrative state appears in the public footer.

The full regression suite remains required before release.

## Limitation

CDE v12.5.3 is a UI and browser-entry correction only. It introduces no new
administration capability and no public/private state change.
