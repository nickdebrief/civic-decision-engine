# CDE Platform Stage 48 — Association Card Visual Refinement and Scalable Relationship Presentation

## Purpose

CDE Platform Stage 48 improves the Published Document presentation of governed
Canonical Record associations. Stage 47.1 was already merged and deployed
before this work began. Stage 48 is a separate presentation refinement and does
not amend the Authoritative source panel introduced in that earlier stage.

## Association Notice

The association governance notice reuses the established Publication
Provenance notice treatment. Its wording is unchanged, and it remains
explanatory and subordinate to the association cards. Dedicated standard- and
dark-mode colours prevent the notice text from inheriting a low-contrast muted
treatment.

## Reusable Association Card

Each association supplied by the authoritative backend renders through one
server-side card helper in this semantic order:

1. Canonical Record label;
2. Canonical Record identifier;
3. exact persisted relationship label in a CDE teal badge;
4. association summary;
5. available metadata;
6. navigation actions.

The renderer supports zero, one, or multiple associations without duplicate
HTML identifiers. It preserves backend order and does not introduce sorting,
grouping, filtering, pagination, search, or client-side state.

## Metadata and Actions

Generated date and trajectory are grouped in a semantic definition list when
available. Empty optional rows are omitted rather than inferred. Open Canonical
Record remains the primary navigation action, while View association uses the
established secondary outlined treatment. Both retain their existing routes and
link semantics.

## Accessibility and Responsive Behaviour

The relationship meaning is explicit text and does not depend on colour. Cards
use semantic headings, definition-list metadata, labelled action navigation,
safe wrapping for long identifiers and relationship labels, and visible
keyboard focus. Metadata stacks and actions become full-width at narrow mobile
sizes. Standard and dark-mode badge combinations measure approximately 7.46:1
and 8.82:1 contrast respectively, exceeding the WCAG AA threshold for normal
text.

## Governance Boundary

CDE Platform Stage 48 changes presentation and the minimum reusable template
structure only. It does not change association semantics, persistence,
creation, deletion, amendment, ordering, lifecycle, provenance, identifiers,
hashes, verification, source-record logic, Canonical Records, Published
Documents, routes, permissions, authentication, APIs, database schema,
migrations, or persisted data.
