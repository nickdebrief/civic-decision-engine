# CDE v12.23 — Public Archive Explorer

## Purpose

CDE v12.23 adds a unified public Archive Explorer at `/archive`. The Explorer is
a discovery interface over existing governed public objects:

- Canonical Records;
- Published Documents;
- governed Record-Document Associations;
- Governed Public Collections.

It is not a new governance object, collection, repository, provenance layer, or
publication workflow.

## Architecture

The Explorer derives public cards from existing public-safe projections and
eligibility rules:

- latest public canonical records from the Public Record Index data;
- Published Documents from the Public Document Library;
- active, public, dynamically eligible associations from the public association
  index helper;
- active, public governed collections from the public collection index helper;
- collection filtering from public-only collection membership resolution.

Each result links directly to the governed object page that owns the object's
identity, provenance, lifecycle, verification, and public presentation.

## Navigation

The public route is:

`/archive`

The page includes links back to:

- `/records`;
- `/documents`;
- `/associations`;
- `/collections`.

Public record, document, association, and collection detail pages now include a
`Back to Archive Explorer` link. Breadcrumb text identifies the Archive context
without replacing object-specific navigation.

## Search and Filters

The Explorer supports server-rendered query-parameter state for:

- search;
- object type;
- publication status;
- publication year;
- document year;
- record type;
- collection;
- media type;
- sort;
- page;
- page size.

Search uses existing indexed or derived metadata. Document search reuses
`build_document_search_text()`, so titles, descriptions, Keywords, filenames,
media format, and safely extracted workbook worksheet names remain consistent
with the Public Document Library and association document selector.

Media filters support:

- PDF;
- Image;
- Audio;
- Spreadsheet.

Sorting supports newest first, oldest first, alphabetical, and reference order.
Pagination uses bounded public page sizes of 10, 25, 50, and 100.

## Governed Object Boundaries

The Explorer does not:

- duplicate object records;
- create collection memberships;
- mutate lifecycle status;
- alter publication eligibility;
- rewrite provenance;
- change verification hashes;
- expose private notes, administrative notes, storage paths, sessions, secrets,
  or hidden objects;
- replace canonical record, document, association, or collection pages.

Collections remain governed collections. The Archive Explorer is only the public
doorway into the existing archive.

## Validation Results

Focused tests cover the archive landing page, counts, search, object filters,
status/year/document-year filters, record-type filtering, collection filtering,
media filtering, spreadsheet visibility, association and collection visibility,
sorting, pagination, query persistence, breadcrumbs, and back links from public
object detail pages.
