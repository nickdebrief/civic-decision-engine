# CDE v12.26 — Public Archive UX Refinements

## Purpose

CDE v12.26 refines the Public Archive Explorer and adjacent public discovery
experience after the v12.23, v12.24, v12.24.1, and v12.25 releases established
the public governance graph and expanded supported Published Document formats.

The Archive Explorer improves discovery without changing governance.

## UX Problems Addressed

The archive was functional and architecturally coherent, but public scanning and
orientation could be improved. This release addresses:

- dense visual hierarchy;
- generic result-card action labels;
- raw active-filter values;
- repeated or low-value pagination in single-page or no-result views;
- no-result wording that did not clearly distinguish empty archives from
  over-restrictive filters;
- narrow-screen readability for filters, cards, long references, and actions;
- accessibility gaps around result navigation, status summaries, and control
  labelling.

## Archive Hierarchy Refinements

The `/archive` page now follows a clearer public reading order:

1. title and governance boundary wording;
2. public object totals;
3. current archive view and active-filter summary;
4. search and filter controls;
5. pagination where useful;
6. archive results;
7. bottom pagination where useful.

The governance boundary remains visible, but it is visually calmer than the
search and results workflow.

## Result-Card Improvements

Archive result cards now present public-safe metadata in a more consistent
shape across object types:

- governed object-type badge;
- title as the primary link;
- governed public reference;
- status;
- relevant date;
- institution/source where available;
- category where available;
- media type for Published Document and association results;
- record type for Canonical Records;
- bounded public summary text;
- object-specific action labels.

Action labels now describe the destination object type:

- Open Canonical Record;
- Open Published Document;
- Open Association;
- Open Collection.

Associations remain independently navigable public objects. Collections remain
organising public objects and do not absorb member identity.

## Filter and Active-Filter Refinements

The filter form retains existing query parameters and server-side filtering
semantics. Labels and placeholder text were clarified, and a short helper text
now states that search covers public-safe indexed metadata only.

The active-filter summary now displays human-readable labels and values, such
as `Published Document`, `Spreadsheet`, and `Alphabetical`, instead of raw query
values. Default newest-first sorting is not displayed as an active filter.

Clear Filters links return to `/archive`.

## Pagination Changes

Archive pagination is now rendered as semantic navigation only when it adds
value. Single-page and zero-result views omit meaningless pagination controls.

When pagination is needed:

- current page and total pages are displayed;
- Previous and Next links are shown only when available;
- archive search, filter, sort, and page-size query state is preserved;
- accessible labels distinguish top and bottom pagination.

Invalid or out-of-range page values continue to be normalised safely by the
existing archive route logic.

## Empty-State Changes

The archive now distinguishes:

- no eligible public objects are currently listed;
- filters returned no public matches.

Filtered no-result views provide a Clear Filters route without implying that
private or unpublished objects do not exist.

## Responsive Behaviour

The archive filter grid, object totals, result metadata, long references, and
action links have been refined for narrower screens. Filters stack logically,
metadata labels remain associated with values, action links become full-width
where appropriate, and long governed identifiers wrap safely.

## Accessibility Improvements

The refined archive uses semantic sections for counts, current view, filters,
results, and pagination. Form controls retain explicit labels, result action
links have descriptive accessible labels, pagination communicates the current
page, and visible focus styles remain intact.

Object-type badges continue to expose visible text and are not colour-only.

## Preserved Behaviour

This stage does not change:

- governance semantics;
- object identity;
- provenance;
- lifecycle states;
- publication rules;
- public eligibility;
- archive search semantics;
- Record-Document Association meaning or visibility;
- Archive Collection membership governance;
- verification hashes;
- public/private boundaries;
- existing public URLs.

The Public Archive Explorer remains a discovery interface over independently
governed public objects.

## Validation Results

Focused tests cover archive hierarchy, boundary wording, object totals,
human-readable active filters, object-specific action labels, query-preserving
pagination, no-result states, responsive/accessibility markup, and public-safe
metadata rendering. Regression tests cover the v12.23 Archive Explorer, v12.24
public navigation and information architecture, v12.25 RTF/archive integration,
public indexes, associations, collections, and the full test suite.
