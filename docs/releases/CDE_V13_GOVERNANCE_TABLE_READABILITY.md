# CDE v13 — Governance Table Readability

This release standardises readability treatment for dense governance tables
across the Civic Decision Engine.

The correction follows the Public Transmission Included Governed Objects table
refinement and generalises the same principle: structured governance values and
human-readable governed text need different wrapping behaviour.

## Root Cause

Several dense public and administrative tables inherited generic table rules
that allowed every cell to wrap aggressively. That was acceptable for long prose,
but fragile for structured governance values such as `DOC-...`, `TRM-...`,
`TRM-ATT-...`, lifecycle states, visibility labels, timestamps, positions, and
short relationship labels.

The result could be character-by-character wrapping in columns that should have
remained compact and legible.

## Affected Views

The implementation inspected dense governance tables in:

- Transmission Management;
- Public Transmission Library;
- Public Transmission detail;
- Collection Management;
- Public Collection Library;
- Public Collection detail;
- Administrative history and provenance tables already using the shared admin
  table pattern;
- public collection and transmission provenance/pathway tables.

Simple key-value metadata tables were intentionally left as ordinary metadata
tables unless they formed part of a dense governance listing.

## Shared Table Pattern

The shared pattern now distinguishes:

- structured values, using compact or identifier cells that avoid arbitrary
  breaking;
- human-readable content, using content cells that wrap normally;
- notes and public prose, using note cells that preserve complete governed
  content;
- actions, timestamps, labels, and statuses, using compact cells.

Public pages use the reusable `governance-table-wrap`, `governance-table`, and
`table-cell--...` classes. Administrative pages reuse the existing
`admin-table-scroll` and `admin-data-table` pattern with the same semantic cell
classes.

## Wrapping Rules

Structured values are kept on one line where practical and no longer rely on
character-by-character wrapping.

Human-readable titles, summaries, sender and recipient names, public notes, and
history notes continue to wrap normally. Governed public content is not
truncated or hidden.

The implementation does not introduce `word-break: break-all`.

## Responsive Strategy

Dense tables remain semantic HTML tables inside horizontally scrollable
contained wrappers. Narrow viewports can reach every column without forcing the
page body itself to overflow.

Column sizing remains table-specific. The release does not impose one universal
percentage grid on every table.

## Accessibility

The correction preserves:

- semantic `<table>` markup;
- column header scope where updated;
- labelled scroll regions for dense tables;
- visible links and existing focus styles;
- complete text for identifiers, notes, and governed public content.

No governed content is hidden solely for layout.

## Manual Verification

Manual review covered representative public and administrative table layouts:

- Transmission Management;
- Public Transmission detail;
- Collection Management;
- Public Collection detail;
- narrow viewport behaviour;
- browser zoom behaviour.

The Public Transmission detail table remains suitable for public milestone
screenshots: Position and Inclusion reference headings no longer collide,
relationship labels remain legible, Public Note text wraps naturally, and the
Object column remains visually prominent.

## Automated Tests

Focused tests assert the shared wrappers and semantic cell classes on:

- Transmission Management;
- Public Transmission Library;
- Public Transmission detail;
- Public Collection Library;
- Public Collection detail;
- collection and transmission provenance/history tables.

Regression tests continue to confirm that identifiers, Public Notes, table
headings, and governed links are not removed or truncated.

## Governance Invariants

This is a presentation and accessibility correction only.

It does not change object identity, lifecycle state, publication state,
provenance, traceability, associations, collections, transmissions, SHA-256
semantics, authorization, storage, public eligibility, route semantics, or any
governed object relationship.
