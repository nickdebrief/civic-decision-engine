# CDE v12.20 — Searchable and Readable Record Selection

## Purpose

CDE v12.20 improves the administrator experience introduced in CDE v12.19.
The governed public-record selector correctly limited association creation to
eligible public CDE records, but native option labels became difficult to scan
as the archive grew. Many records share similar generated findings, and long
option text can hide the distinguishing reference, institution, or trajectory.

This stage improves readability and discoverability without changing the
governed association model.

## Usability Problem Identified

The v12.19 selector used long labels derived from generated findings. That made
the dropdown repetitive and hard to search with native browser behaviour.
Distinguishing information often appeared late in the option text.

CDE v12.20 keeps the canonical record reference visible first and moves richer
context into safe metadata and a read-only selected-record panel.

## Searchable Governed Record Selection

The create-association page now includes a visible search field:

`Search public CDE records`

The search filters the existing server-rendered eligible record options using
lightweight native JavaScript. It is case-insensitive and uses simple substring
matching only. No external dependency, fuzzy matching, semantic search, ranking
model, typo correction, or automatic selection is introduced.

The original `<select name="record_reference">` remains the form control used
for submission.

## Compact Option Labels

Record option labels now use a compact deterministic format:

`<canonical reference> — <institution code> — <trajectory>`

Examples:

- `Strike-LA-20260606-038 — LA — Stable`
- `Strike-ED-20260510-006 — ED — Deteriorating`
- `REC-2026-001`

Where an explicit concise title exists in the record mapping, the label may use:

`<canonical reference> — <title> — <trajectory>`

The full generated finding is no longer used as the native option label.

## Canonical Reference-First Display

The canonical record reference always appears first. Display labels are
presentation only. The submitted value remains exactly the stored canonical
record reference.

## Search Metadata

Each eligible record option includes safe public metadata for filtering:

- canonical record reference;
- institution code derived from the public reference format;
- trajectory;
- public system state;
- public finding text;
- any explicit public title already present in the record mapping.

The search metadata does not include document references, private notes,
administrative notes, unpublished metadata, storage paths, credentials, session
data, or hidden records.

## Selected-Record Context Panel

The form includes a read-only `Selected record` panel. When JavaScript is
available, selecting a record displays public context:

- Reference;
- Institution;
- Trajectory;
- System state;
- Finding summary;
- public record link.

The panel is informational only. It does not change the selected value, create
or edit a record, or alter association creation behaviour.

## Explicit No-Default-Selection Behaviour

The record selector now starts with an explicit disabled placeholder:

`Select a public CDE record`

No eligible record is selected automatically. Administrators must deliberately
choose the public CDE record to associate with the selected Published document.

## No-Results and Clear-Search Behaviour

When filtering hides every eligible option, the page displays:

`No eligible public CDE records match this search.`

The `Clear search` control restores the full eligible option list. Filtering
does not alter underlying eligibility and does not expose private or ineligible
record counts.

## Accessibility and Progressive Enhancement

The search field has an explicit label, uses `type="search"`, disables browser
autocomplete, and provides an accessible live status region for result counts
and no-results feedback. The selector remains a normal keyboard-accessible
HTML select. JavaScript enhances filtering and context display but is not
required for basic form submission.

## Backend Validation Preserved

CDE v12.20 does not weaken CDE v12.19 backend validation. The create endpoint
still requires exactly one canonical public record reference, trims only outer
whitespace, rejects multiple references, rejects display labels and prefixes,
rejects document references used as record references, rejects private or
superseded records, and creates an association only after all validation
succeeds.

Search text, display labels, data attributes, and selected-record context
content never influence backend lookup.

## Governance Boundaries Preserved

CDE v12.20 does not change:

- association identity;
- association lifecycle;
- association history;
- public association references;
- actor attribution;
- relationship types;
- public/private association behaviour;
- record identity;
- document identity;
- record lifecycle;
- document lifecycle;
- record verification hashes;
- document SHA-256 values;
- evidence;
- publication behaviour;
- Publication Provenance;
- Public Record Index behaviour;
- Public Document Library behaviour;
- Archive Collections;
- Collection Memberships;
- ordered collection sequence;
- authentication;
- footer navigation;
- public/private visibility boundaries;
- database schema.

## Validation Results

Validation performed for this stage:

- Focused searchable record-selection and v12.19 selector tests: 14 passed.
- Requested focused and adjacent test modules: 281 passed.
- Full regression suite: 521 passed.
- Python compile check: passed.
- `git diff --check`: passed.
- Conflict-marker check: passed.
