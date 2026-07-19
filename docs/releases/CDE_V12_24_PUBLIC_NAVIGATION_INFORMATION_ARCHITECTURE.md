# CDE v12.24 — Public Navigation & Information Architecture

## Purpose

CDE v12.24 makes the Public Archive Explorer discoverable from public pages and
standardises public navigation across governed public objects.

This is a navigation and presentation stage only. It does not create a new
governance object, change object identity, alter lifecycle state, rewrite
provenance, modify publication eligibility, or change access-control rules.

## Architectural Position

CDE v12.24 is not a navigation release in the conventional sense. It is the
release in which the Civic Decision Engine's governance model is expressed
through a coherent public information architecture.

Previous releases established independently governed public objects with their
own identities, provenance, publication lifecycles, and public addresses.
Version 12.24 connects those public objects through consistent navigation,
breadcrumbs, governed object badges, safe archive return links, and cross-object
navigation while preserving their independent identities and governance
semantics.

The result is not a hierarchy of pages, but a navigable public governance graph.
Navigation exposes governed relationships without implying ownership,
containment, or absorption. Associations remain independently governed public
objects. Collections organise public objects without absorbing identity. Each
governed object remains independently addressable through its own public route.

Public information is not organised by containment. It is organised by
governance.

## Relationship to v12.23

CDE v12.23 introduced `/archive` as a unified discovery interface over existing
governed public objects:

- Canonical Records
- Published Documents
- Record–Document Associations
- Governed Public Collections

CDE v12.24 keeps `/archive` as that doorway and makes it reachable from public
navigation and from governed object detail pages.

## v12.24.1 Navigation Completion

CDE v12.24.1 completes the navigation symmetry introduced in v12.24.

Canonical Record pages participate in the same public information architecture
as Published Documents, Associations, and Collections. They use the shared
primary public navigation, semantic breadcrumbs, the reusable `Canonical Record`
object-type badge, and the validated `Back to Archive Explorer` return-link
behaviour. Valid `/archive` query state is preserved where supplied, and unsafe
return destinations fall back to `/archive`.

The shared Administration Console navigation now includes a direct
`Public Archive Explorer` link to `/archive` while retaining the existing
`Public Document Library` link. The Administration Console manages governance;
the Public Archive Explorer exposes governance for public verification.

This is a navigation-only completion. It does not change governance semantics,
object identity, lifecycle state, publication eligibility, provenance,
identifiers, search behaviour, association logic, collection membership, or
public/private access boundaries.

## Public Navigation

Public pages now include an Archive link in the primary public navigation. The
Archive link points to `/archive` and receives an active state on archive pages.
The static public footer also includes an Archive link.

Administration Console navigation remains separate and is not exposed through
public navigation.

## Breadcrumbs

Governed public object pages now render semantic breadcrumb navigation with an
accessible `Breadcrumb` label.

Patterns:

- Home / Archive
- Home / Archive / Canonical Records / current record
- Home / Archive / Published Documents / current document
- Home / Archive / Associations / current association
- Home / Archive / Collections / current collection

The current page is rendered as text rather than as a clickable link. Object-type
breadcrumbs link back to `/archive` with the relevant archive type filter instead
of introducing duplicate index routes.

## Back to Archive Explorer

Archive result links carry a validated archive return state. Governed object
pages render a `Back to Archive Explorer` link that returns to the preserved
archive query where available.

The return-path helper accepts only internal `/archive` paths and known archive
query parameters. It rejects absolute URLs, protocol-relative URLs, non-archive
internal paths, and malformed values, falling back to `/archive`.

## Governed Object Badges

CDE v12.24 adds reusable public badges for:

- Canonical Record
- Published Document
- Association
- Collection

Badges are text-bearing and visually distinct without relying on colour alone.
They appear in Archive Explorer results and governed object detail pages, and in
collection member listings where member type is shown.

Spreadsheet artefacts remain governed Published Documents. Their spreadsheet
format continues to be represented as media/document metadata, not as a new
governance type.

## Cross-Object Navigation

The release preserves existing public cross-links and improves orientation:

- Canonical Record pages retain associated Published Document and Association
  links.
- Published Document pages retain associated Canonical Record and Association
  links.
- Association pages identify both governed endpoints as independent public
  objects.
- Collection pages show governed member badges and links to each member's own
  public page.

No relationship is inferred from matching titles, filenames, references, or
metadata. Only existing governed public relationships are rendered.

## Security Boundaries

CDE v12.24 does not expose private or unpublished objects. Public pages continue
to resolve related objects through existing public eligibility rules.

The archive-return helper prevents open redirects by accepting only `/archive`
return paths. External URLs, protocol-relative URLs, non-archive paths, and
unknown return destinations are rejected.

## Preserved Behaviour

This stage does not change:

- Canonical Record identity, hashes, lifecycle, or verification
- Published Document lifecycle, SHA-256, provenance, bytes, or media behaviour
- Record–Document Association identity, lifecycle, eligibility, or history
- Governed Public Collection identity, membership rules, sequence, or public
  eligibility
- Public Archive Explorer filtering, sorting, pagination, and counts
- Public Document Library behaviour
- Public Record Index behaviour
- Administration Console navigation or authentication

## Validation

Validation for this stage covers focused public navigation tests, v12.23 archive
regression tests, public document/association/collection tests, association
selector tests, admin navigation/footer tests, full regression, Python compile,
`git diff --check`, and an anchored conflict-marker scan.
