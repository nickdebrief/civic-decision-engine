# CDE v13.0.4 — Restore Two-Column Landing Page Footer Layout

## Purpose

CDE v13.0.4 restores the static landing-page footer's deliberate two-column
composition after the v13 footer alignment corrections.

This is a local presentation refinement. It does not change platform identity,
footer destinations, governance semantics, public routes, administrative routes,
or any governed object.

## Previous Two-Region Design

The landing-page footer historically used two visual regions:

- a left information region for copyright, public metadata notice, and footer
  navigation;
- a right identity region for platform identity, platform statement, version,
  and Administration access.

That composition made the Administration link visually subordinate to the
platform identity rather than part of the general public navigation.

## Root Cause

The v13 footer was structurally contained correctly after v13.0.3, but its
composition still relied on a generic wrapping footer flow. The platform
identity was rendered as a single line and the Administration link could read as
independently positioned rather than as part of the same identity block.

This weakened the semantic relationship between the active platform identity and
the administrative entry point.

## Restored Composition

The static landing-page footer now has two explicit DOM regions:

```text
<footer class="public-footer">
  <div class="public-footer__primary">
    copyright
    metadata notice
    footer navigation
  </div>

  <div class="public-footer__identity">
    Civic Decision Engine
    Independent · Transparent · Traceable
    Platform version v13.0
    Administration
  </div>
</footer>
```

The Administration link is grouped inside the right identity region. It no
longer appears as a standalone footer element or as part of the left navigation
group.

## Active v13 Identity

The restored identity block uses the current platform identity:

```text
Civic Decision Engine
Independent · Transparent · Traceable
Platform version v13.0
Administration
```

Obsolete v12 footer wording was not restored.

## Layout

The static landing-page footer uses a local CSS Grid layout:

```text
grid-template-columns: minmax(0, 1fr) minmax(220px, auto)
```

The left region expands to carry public footer information. The right region
aligns to the right edge of the constrained footer container and keeps platform
identity, version, and Administration together.

No absolute positioning, fixed pixel offsets, or duplicate nested footer
container was introduced.

## Responsive Behaviour

At narrow widths, the footer collapses to one column. Reading order remains:

1. copyright;
2. metadata notice;
3. footer navigation;
4. platform identity;
5. tagline;
6. platform version;
7. Administration.

The mobile layout uses left alignment so the Administration link remains
associated with the identity block without creating an independently centred
element.

## Accessibility

The footer remains a semantic `<footer>`. Footer navigation remains inside a
labelled `<nav>`, visible text identifies all links, and the Administration link
uses the same focus-visible treatment as the other landing-page footer links.

The visual grouping now matches DOM grouping, so assistive technology reads the
footer in the same relationship expressed visually.

## Shared Pages

The shared public footer helper was not changed.

The Public Archive Explorer, Public Document Library, Public Transmission
Library, Associations, Collections, Traceability, Record pages, Document pages,
administrative templates, and administrative navigation were not altered by this
release.

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
artefact is created. No workflow changes are introduced.
