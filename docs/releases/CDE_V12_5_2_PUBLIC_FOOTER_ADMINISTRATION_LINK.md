# CDE v12.5.2 — Public Footer Administration Link

## Objective

CDE v12.5.2 adds a discreet public-to-administration navigation path by placing
an **Administration** link beneath the existing right-hand public footer
identity. The link points to the existing authenticated `/admin` route.

## Presentation

The public footer preserves the existing left-side content:

- copyright statement
- public attachment metadata statement
- public navigation links for Records, Conditions, Patterns, Stats, Graph, and
  API docs

The right side preserves the existing identity statement:

`Civic Decision Engine v12 — The record does not argue.`

The new **Administration** link appears directly beneath that identity statement
using the same muted footer-link typography. It remains secondary, keyboard
accessible, and responsive at the existing footer breakpoint.

## Behaviour

Selecting **Administration** navigates to `/admin`. The existing administration
system remains authoritative:

- unauthenticated users continue through the existing admin authentication
  boundary;
- authenticated administrators continue to the existing CDE Administration
  Console;
- no authentication state is exposed in the public footer;
- no conditional administrative information is rendered publicly.

## Security Boundary

This stage does not expose private intake records, review queues, lifecycle
counts, record evidence, administrative state, or private document metadata. It
does not change admin login, session cookies, authorization, document intake,
approval workflow, publication rules, archival behaviour, public records,
attachments, evidence relationships, classification logic, verification hashes,
database state, or public API behaviour.

## Tests

Focused regression coverage verifies that the public footer contains the
Administration link, the target is exactly `/admin`, the CDE v12 identity
statement remains unchanged, existing public footer navigation remains present,
private administrative lifecycle terms are not exposed in the footer, and both
unauthenticated and authenticated admin behaviour remain unchanged.

The complete regression suite remains required before release.

## Limitation

CDE v12.5.2 is a navigation-only refinement. It introduces no new admin route,
no JavaScript, no external dependency, no public/private state change, and no
new administrative capability.
