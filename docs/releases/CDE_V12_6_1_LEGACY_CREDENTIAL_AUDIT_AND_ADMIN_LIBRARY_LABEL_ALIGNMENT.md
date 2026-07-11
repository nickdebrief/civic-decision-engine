# CDE v12.6.1 — Legacy Credential Audit and Admin Library Label Alignment

## Purpose

CDE v12.6.1 is a tightly scoped maintenance audit after named administrator
authentication. It verifies whether the legacy `CDE_ADMIN_PASSWORD` deployment
variable remains referenced in the current repository and aligns active
Administration Console labels with the canonical **Public Document Library**
feature name.

## Credential Variable Audit

The current active administrator credential variables are:

- `ADMIN_USERNAME`
- `ADMIN_PASSWORD`

Repository-wide search found no active runtime use of `CDE_ADMIN_PASSWORD`.
Remaining occurrences are documentation or test assertions for this audit. The
legacy variable is therefore not an active runtime dependency for:

- admin login;
- API login;
- session creation;
- admin-route protection;
- document intake;
- approval workflow;
- publication workflow;
- internal admin helpers;
- Public Document Library routes; or
- public/private visibility checks.

Because no active runtime dependency remains, the legacy Railway variable
`CDE_ADMIN_PASSWORD` can be removed from Railway configuration after operational
confirmation. This release does not remove the Railway variable and does not
introduce a fallback from `ADMIN_PASSWORD` to `CDE_ADMIN_PASSWORD`.

## Admin-Console Label Alignment

Active Administration Console labels that referred to the published document
library as **Public Library** now use **Public Document Library**:

- shared admin-console navigation link;
- dashboard summary-card heading; and
- dashboard summary-card action link.

All affected links continue to target exactly `/documents`.

Historical release documentation that accurately describes earlier stage labels
is preserved as release history.

## Behavioural Boundaries

This stage changes terminology and documents the credential audit result only.
It does not change:

- authentication requirements;
- username/password validation;
- signed-session structure;
- session expiry;
- logout behaviour;
- actor attribution;
- lifecycle states or transitions;
- document intake, review, approval, rejection, publication, or archiving;
- public verification;
- SHA-256 hashing;
- storage paths;
- non-mutation controls;
- database schema or contents;
- record, attachment, evidence, or classification behaviour;
- public API behaviour;
- public footer navigation;
- Public Document Library functionality; or
- public/private visibility boundaries.

Private and unpublished intake documents remain protected. Approval remains
separate from publication.

## Tests

Focused tests verify:

- active runtime code does not read `CDE_ADMIN_PASSWORD`;
- admin authentication still requires `ADMIN_USERNAME` and `ADMIN_PASSWORD`;
- missing `ADMIN_PASSWORD` fails closed;
- password-only authentication remains impossible;
- active admin-console labels use **Public Document Library**;
- the admin-console link target remains `/documents`;
- public footer navigation remains unchanged;
- Public Document Library behaviour remains unchanged; and
- private and unpublished document protection remains unchanged.

## Validation

Validation for this stage should include:

- `python3 -m unittest tests.test_admin_session`
- `python3 -m unittest tests.test_admin_navigation_console`
- `python3 -m unittest tests.test_admin_document_intake`
- `python3 -m unittest tests.test_public_document_library`
- `python3 -m unittest tests.test_public_footer_administration_link`
- `python3 -m unittest discover -s tests`
- `git diff --check`
- repository-wide search for `CDE_ADMIN_PASSWORD`
- repository-wide search for active visible `Public Library` labels
- conflict-marker check
