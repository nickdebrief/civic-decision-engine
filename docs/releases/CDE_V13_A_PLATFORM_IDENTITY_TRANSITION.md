# CDE v13.A — Platform Identity Transition

## Purpose

CDE v13.A completes a controlled platform identity transition across the Civic
Decision Engine after completion of the v12 series.

Platform identity should reflect the governance architecture without changing it.

This release updates visible platform identity, version references, public and
administrative presentation, watermarks, browser titles, and documentation so
the platform is coherent before v13.0 planning begins.

v13.A prepares the Civic Decision Engine for the v13 era. It does not introduce Governed Public Transmissions.

## Canonical Identity

The active platform identity is:

- platform name: Civic Decision Engine;
- short name: CDE;
- platform version: v13.A;
- tagline: Independent · Transparent · Traceable.

The platform name is used where the full identity matters. `CDE` remains the
short form where brevity is appropriate, including administration labels and
release names.

## Version Convention

The public-facing version label is `v13.A`. It refers only to the current
software/platform identity. It does not alter governed object versions,
document lifecycle states, record lifecycle states, publication declarations, or
historic release references.

Historical v12 release documentation remains historically accurate and is not
rewritten as v13 documentation.

## Public Interface

Public pages that use the shared public navigation now expose a consistent text
wordmark, the canonical tagline, and the current platform version. Browser and
API metadata use the canonical platform name.

The public homepage footer now presents:

```text
Civic Decision Engine — Independent · Transparent · Traceable — Platform version v13.A
```

The public navigation remains functionally unchanged. Existing public routes,
breadcrumbs, Archive Explorer return links, Traceability views, object badges,
document previews, and public object pages continue to resolve through their
existing URLs.

## Administrative Interface

The Administration Console retains its existing operational navigation and
management workflows. A shared administrative identity band now displays the
canonical platform name, tagline, and current platform version alongside the
existing authenticated administrator identity.

The console remains an authenticated governance workspace. This release does
not add admin workflows, remove admin links, change permissions, or alter the
document intake, audit, correction, association, collection, or record evidence
tools.

## Logo and Wordmark Treatment

No new logo design is introduced. Existing seal-style marks remain
presentational and are updated where they visibly displayed the active platform
version. Text wordmarks provide the accessible platform identity so the
interface does not depend on image-only branding.

Logo and mark usage remains bounded, responsive, and presentational.

## Watermark Treatment

Render-time watermarks and generated public-record presentation marks now use
the v13.A identity. They remain presentational only.

Watermarks do not:

- alter governed content;
- alter provenance;
- change source-file hashes;
- modify uploaded artefacts;
- create new governed files;
- imply evidential certification.

## Accessibility and Responsive Behaviour

The identity transition keeps text available when marks fail to load, preserves
semantic navigation labels, maintains meaningful browser titles, and avoids
image-only platform identification.

Public and administrative identity elements wrap on narrow screens and preserve
existing focus behaviour, navigation labels, and page headings.

## Governance Invariants

This release does not change:

- governed object identity;
- lifecycle states;
- publication rules;
- provenance;
- associations;
- collection membership;
- traceability;
- SHA-256 semantics;
- public eligibility;
- authorization;
- storage;
- existing public URLs;
- API behaviour beyond current platform metadata;
- original uploaded artefacts.

No governed object is created or modified by the identity transition.

## Intentional Limitations

This release does not implement Governed Public Transmissions, sender or
recipient models, transmission objects, email ingestion, attachment-to-message
governance, or v13.0 domain workflows.

It also does not replace historical v12 release records, introduce a new
frontend framework, redesign every page, add unapproved external links, or make
new legal, evidential, or certification claims.
