# CDE v13.0.3 — Landing Page Footer Container Correction

## Purpose

CDE v13.0.3 completes the landing-page footer alignment correction after visual
verification showed that the v13.0.2 patch did not fully align the footer with
the landing-page application grid.

This is a local presentation correction for the main static landing page only.

## Confirmed Behaviour

The issue was reproducible in multiple browsers. The landing-page footer still
appeared visually detached from the constrained application layout above it:

- the footer rule appeared wider than the application content;
- footer text began too close to the viewport edge;
- the footer did not read as part of the same horizontal grid as the landing
  application panels;
- the Administration link appeared independently aligned rather than governed by
  the landing-page layout.

Other public pages and administrative pages were already correctly aligned.

## Why v13.0.2 Was Insufficient

CDE v13.0.2 removed duplicate local width rules from `.public-footer`. That was
necessary, but it only removed a nested footer constraint.

The landing page still lacked an explicit semantic application container. The
hero and application panels were direct siblings of the language bar and footer
inside `.wrap`, so tests could prove that the footer was inside `.wrap` without
proving that the footer shared the same application layout structure as the
content above it.

## Root Cause

The root cause was structural rather than a missing pixel offset.

The footer needed to be rendered as part of the same constrained homepage layout
as the landing application, without creating a second footer-specific content
grid. The homepage markup did not make that relationship explicit enough.

## Structural Correction

The landing page now uses this local structure:

```text
<div class="wrap">
  <div class="lang-bar">...</div>
  <main class="landing-application">
    <section class="hero">...</section>
    <section class="grid">...</section>
  </main>
  <footer class="public-footer">...</footer>
</div>
```

The footer remains inside the same `.wrap` container as the application and no
longer carries its own nested maximum-width or centring rules. The footer top
rule, copyright text, metadata note, footer navigation, platform identity line,
and Administration link inherit the same outer layout context as the landing
application.

No arbitrary margin, viewport-specific offset, or duplicate content grid was
introduced.

## Responsive Verification

The footer continues to use the existing responsive flex behaviour. At desktop,
tablet, and mobile widths:

- the footer remains inside the landing-page wrapper;
- horizontal padding follows the page wrapper;
- footer content wraps naturally;
- the Administration link remains accessible;
- no horizontal overflow is introduced.

The existing print selector was updated from the old direct-child hero structure
to the new `.landing-application > section.hero` structure so print behaviour is
preserved.

## Other Pages

The shared public footer helper was not changed.

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
