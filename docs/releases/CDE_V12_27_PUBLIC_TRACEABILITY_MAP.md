# CDE v12.27 — Public Traceability Map

## Purpose

CDE v12.27 introduces `/traceability`, a public traceability interface over the
existing public governance graph.

Traceability reveals declared relationships without erasing the identity of the
governed objects involved.

The Traceability Map is a discovery interface over the public governance graph.
It is not itself a governed object.

## Governance Boundary

The Public Traceability Map visualises declared relationships between
independently governed public objects. It does not create or infer
relationships, establish evidence, alter provenance, change lifecycle state, or
replace the public pages of the governed objects shown.

Absence from the map does not prove that no private, administrative,
historical, or unpublished relationship exists. The map renders only
publicly eligible relationships and objects under existing public visibility
rules.

## Supported Governed Object Types

The initial traceability release supports:

- Canonical Records;
- Published Documents;
- governed Record-Document Associations;
- Governed Public Collections.

No new governance object type is introduced.

## Association-Chain Rendering Unit

One traceability result represents one governed Association chain:

```text
Canonical Record
        |
        | declared by
        v
Governed Association
        |
        | links to
        v
Published Document
```

Associations remain visible, labelled, and independently navigable public
objects. Distinct Associations between the same Record and Document remain
distinct traceability chains.

## Collections

Governed Public Collections are shown as collection-membership context where
applicable. The page uses non-containment language: collections declare governed
membership without owning, containing, or absorbing their member objects.

Collection links open the collection's own public page. Member Records,
Documents, and Associations retain their own links and references.

## Visual and Structured Views

The route is server-rendered and dependency-light. The visual view uses semantic
cards connected by text labels so the governed Association is not collapsed into
a decorative edge.

A mandatory structured accessible view provides equivalent information in a
table. Every visible object links to its own public page with descriptive action
labels.

## Filtering and Pagination

The Traceability Map supports public-safe filters for:

- search;
- Canonical Record;
- Published Document;
- Association relationship type;
- Collection;
- institution/source;
- media type;
- publication year;
- document year;
- sort order;
- page size.

Filters are reflected in query parameters, preserved through pagination, and
summarised using human-readable labels. Unsupported parameters are ignored
safely.

Rendering is bounded by paginating Association chains. Pagination uses
deterministic ordering and preserves supported query state.

## Unique Count Semantics

The traceability summary deduplicates unique Canonical Records, Published
Documents, and Governed Public Collections by governed reference. Governed
Associations are counted distinctly, and the chain count follows the documented
Association-chain rendering unit.

Repeated appearance of the same Record or Document across multiple chains does
not inflate its unique object count.

## Empty and Disconnected States

The page distinguishes:

- no publicly eligible traceability relationships are currently available;
- filters returned no matching public relationships;
- a selected public collection currently has no declared relationship in the
  selected view.

No empty state implies that private, administrative, historical, or unpublished
relationships do not exist.

## Accessibility Design

The page uses semantic navigation, headings, forms, sections, cards, tables, and
pagination. Filter controls have visible labels, object nodes have visible
object-type labels, action links are descriptive, and colour is not the sole
means of conveying meaning.

The structured view is the textual equivalent of the visual map and remains
usable without JavaScript.

## Safe Return State

Traceability result links include a validated `/traceability` return state.
The helper accepts only internal `/traceability` URLs and supported query
parameters. It rejects external URLs, protocol-relative URLs, malformed values,
and non-traceability internal paths to prevent open redirects.

## Preserved Behaviour

This release does not change:

- governance semantics;
- object identity;
- provenance;
- lifecycle states;
- publication rules;
- public eligibility;
- Record-Document Association meaning or lifecycle;
- collection membership governance;
- verification hashes;
- public/private boundaries;
- existing public URLs.

The map shows declared public relationships only. It does not infer evidence,
truth, ownership, containment, authorship, responsibility, legal significance,
or external validation.

## Validation Results

Focused tests cover route availability, primary public navigation, governance
boundary wording, Association nodes as governed objects, collection membership
language, public eligibility filtering, filters, active-filter summaries,
unique counts, pagination state, empty and disconnected states, structured
accessible output, and safe return-state validation.

Regression tests cover the Public Archive Explorer, public navigation, RTF and
archive integration, public Records, Documents, Associations, Collections, and
the full test suite.
