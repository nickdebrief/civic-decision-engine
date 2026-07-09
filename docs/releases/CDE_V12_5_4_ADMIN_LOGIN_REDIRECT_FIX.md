# CDE v12.5.4 — Admin Login Redirect Fix

## Objective

CDE v12.5.4 fixes the browser login flow for the Administration Console. After
CDE v12.5.3, unauthenticated `GET /admin` correctly rendered the admin login UI,
but the form posted to the JSON API login endpoint. A successful browser login
therefore displayed `{"ok":true,"role":"admin"}` instead of opening the
Administration Console.

## Fix

The admin login form now posts to a browser-facing route:

`POST /admin/login`

That route uses the same password validation and session creation logic as the
API login endpoint, sets the same signed admin session cookie, and returns a
303 redirect to `/admin`. After the redirect, the authenticated administrator
sees the existing CDE Administration Console.

## API Contract Preserved

The existing programmatic endpoint remains unchanged:

`POST /api/admin/session/login`

It continues to return the established JSON response and secure session cookie
for API/programmatic tests. Invalid passwords remain denied with the existing
unauthorized response.

## Security Boundary

This stage does not change authentication rules, authorization rules, session
contents, cookie security attributes, document intake, approval workflow,
publication behaviour, archival behaviour, public records, attachments,
evidence relationships, classification logic, verification hashes, database
state, or public API behaviour.

No private records, intake data, review queues, lifecycle information, evidence,
administrative counts, or admin session state are exposed publicly.

## Tests

Regression coverage verifies:

- unauthenticated `GET /admin` renders the login UI;
- the browser login form posts to `/admin/login`;
- valid browser login redirects to `/admin`;
- the redirected authenticated session reaches the CDE Administration Console;
- invalid browser login remains denied;
- the existing API login JSON contract still passes;
- no raw JSON is shown in the normal browser login flow.

The full regression suite remains required before release.

## Limitation

CDE v12.5.4 is a browser-flow correction only. It introduces no new
administrative capability and no public/private state change.
