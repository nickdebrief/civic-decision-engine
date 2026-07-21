# CDE v13.0.2 — Landing Page Footer Alignment

## Purpose

CDE v13.0.2 corrects an isolated presentation issue on the main public landing
page.

The landing page footer had drifted horizontally from the primary content grid
after the v13.0.1 footer refinement. Other public routes and administrative
pages already used correctly aligned wrappers and were not changed.

## Root Cause

The landing page footer sits inside the homepage-specific `.wrap` container,
which already defines the page width and horizontal padding:

```text
max-width: 1400px
padding: 40px 24px 64px
```

v13.0.1 added a second local width constraint directly on `.public-footer`.
That duplicated container logic inside the existing wrapper and caused the
footer to follow a slightly different horizontal grid than the content above it.

## Corrective Approach

The fix is local to `api/static/index.html`.

The landing page footer now inherits the horizontal grid from the parent
`.wrap` container. The footer keeps its existing content, links, typography,
spacing, and responsive flex behavior.

No shared footer helper was changed.

## Responsive Verification

The footer remains inside the landing page wrapper at desktop, tablet, and
mobile widths. The footer groups continue to wrap on narrow screens, with left
alignment restored by the existing mobile media query.

## Other Pages

The Public Archive Explorer, Public Document Library, Public Transmission
Library, Associations, Collections, Traceability, Record pages, Document pages,
and administrative pages were not altered by this release.

## Governance Invariants

This release does not change:

- object identity;
- lifecycle;
- publication;
- provenance;
- traceability;
- associations;
- collections;
- transmissions;
- SHA-256 semantics;
- storage;
- authorization;
- public eligibility;
- route semantics.

No migration is introduced. No new governed object is introduced. No derived
artefact is created.

