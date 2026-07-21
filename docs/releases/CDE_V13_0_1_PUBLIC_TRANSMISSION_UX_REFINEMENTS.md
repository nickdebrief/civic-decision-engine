# CDE v13.0.1 — Public Transmission UX Refinements

## Purpose

CDE v13.0.1 refines the visible presentation of Governed Public
Transmissions after the first integrated v13.0 review.

Refinement improves clarity without changing governance.

This release does not introduce a new governed object type, migration, lifecycle
state, publication rule, association rule, collection rule, traceability rule, or
storage model.

## Version Identity Update

The active platform identity now consistently renders:

```text
Platform version v13.0
```

Historical v13.A documentation remains historically accurate. The v13.A release
continues to describe the platform identity transition that prepared the Civic
Decision Engine for v13.0.

## Footer Alignment Restoration

The public footer alignment was restored to match the primary content
container. The footer keeps the same maximum width, horizontal alignment,
padding behavior, and responsive wrapping as the page content.

No footer navigation semantics changed.

## Dashboard Wording Refinement

The Administration Console dashboard card title was refined from:

```text
Public Transmissions
```

to:

```text
Transmissions
```

The shorter title is consistent with the existing administration card language,
including Document Intake, Record Evidence, Archive Collections, and
Administrative Audit. Action wording such as `Open Transmission Intake` remains
explicit.

## Governance Language Audit

Transmission UI wording now prefers:

- included governed objects;
- referenced governed objects;
- governed objects included.

The wording avoids suggesting that a Transmission owns, contains, bundles, or
absorbs the governed objects communicated through it.

Documents preserve content. Transmissions preserve context.

## Responsive Review

The footer, public Transmission Library, public Transmission detail page,
Administration Console dashboard, shared navigation, and generated identity
surfaces were reviewed for narrow-screen behavior. The refinement keeps
wrapping, focus visibility, and content alignment intact without redesigning the
layout.

## Workflow Verification

The v13.0 workflow was reviewed end to end:

```text
Create Transmission
Review
Approve
Publish
Public representation
Traceability
Collection membership
Navigation
Administrative audit
```

The review confirmed that the Transmission lifecycle remains independent and
that included governed objects retain their own identities, lifecycles,
provenance, verification, and public pages.

## Governance Invariants

This release does not change:

- object identity;
- publication semantics;
- provenance;
- traceability;
- SHA-256 semantics;
- collections;
- associations;
- transmissions;
- documents;
- records;
- authorization;
- storage;
- database semantics.

No new governed artefacts are created. No derived objects are created. No
migration is introduced.

