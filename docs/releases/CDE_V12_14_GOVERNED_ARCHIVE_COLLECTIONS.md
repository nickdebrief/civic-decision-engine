# CDE v12.14 — Governed Archive Collections

## Purpose

CDE v12.14 introduces a first-class governed Archive Collection object for the Civic Decision Engine. A collection provides a stable public identity and governance context for a coherent body of independently preserved documents, such as a public accountability archive.

This stage establishes collection identity only. It does not merge, copy, absorb, sequence, or alter documents.

## Relationship To v12.13

CDE v12.13 made governed record-document associations discoverable through the Public Association Index. CDE v12.14 adds a separate collection layer for archive identity and context. Collections remain distinct from civic records, Published documents, record-document associations, Publication Provenance, Publication Pathway, Association Pathway, Administrative Audit, the Public Record Index, and the Public Document Library.

## Collection And Document Distinction

A collection can provide governed context without replacing the records it may later contain. Collection identity does not alter document lifecycle state, document metadata, document SHA-256 values, document publication dates, document provenance, record verification hashes, association history, or evidential meaning.

Document membership is explicitly excluded from CDE v12.14 and reserved for CDE v12.15 — Collection Membership Governance.

## Public Reference Format

Every collection receives a server-generated public collection reference:

`CDE-COLL-YYYYMMDD-NNN`

The reference is unique, immutable, URL-safe, and distinct from record references, document references, association references, and internal numeric collection IDs. It is not client-supplied and is not derived from mutable title text.

The same public reference survives metadata updates, visibility changes, deactivation, and reactivation.

## Collection Schema

CDE v12.14 adds an idempotent SQLite collection table:

- `archive_collections`

The table stores collection identity and metadata, including public reference, title, optional subtitle, institution/source, controlled category, description, public note, administrative note, optional declared date range, active state, public visibility, creation metadata, update metadata, and optional deactivation metadata.

It does not store document contents, copied document metadata, document IDs, membership rows, sequence positions, or derived document counts.

Indexes are created for public reference uniqueness, active/public filtering, category filtering, and created timestamp ordering.

## Categories

Collection category is controlled server-side. Initial categories are:

- `public_accountability_archive` — Public Accountability Archive
- `framework_publications` — Framework Publications
- `professional_records` — Professional Records
- `evidence_audits` — Evidence Audits
- `research_archive` — Research Archive
- `procedural_archive` — Procedural Archive
- `documentary_archive` — Documentary Archive
- `other_governed_collection` — Other Governed Collection

Categories do not alter document category, record classification, evidence sufficiency, publication eligibility, verification, or hashing.

## Administrative Creation

Authenticated administrators can create collections through `/admin/collections/new`.

Creation requires:

- title;
- institution/source;
- controlled category;
- description;
- public visibility value.

Optional fields include subtitle, declared date range, public note, and administrative note. Public visibility defaults safely to private. The server generates the public reference, created timestamp, created actor, active state, and initial immutable history event.

The client cannot supply internal ID, public reference, created actor, created timestamp, updated actor, history, or server-side actor attribution.

## Updates

Authenticated administrators can update collection metadata and public visibility. Updates preserve original public reference, created actor, created timestamp, and earlier history.

Each update records:

- updated timestamp;
- updated actor from the signed administrator session;
- an immutable history event.

Visibility changes are recorded as visibility-change history events.

## Deactivation And Reactivation

Deactivation requires authentication and a deactivation note. It marks the collection inactive, removes it from public eligibility, records actor and timestamp, and creates an immutable history event.

Reactivation requires authentication, restores active state, records actor and timestamp, and creates an immutable history event. It preserves the same public collection reference and restores public availability only when the collection is also marked public.

No permanent deletion control is introduced.

## Immutable History

CDE v12.14 adds a separate collection-history table:

- `archive_collection_history`

History entries record action type, timestamp, actor, previous state JSON, new state JSON, and note. Collection history is separate from document status history, Administrative Audit, Publication Pathway, Publication Provenance, Association Pathway, and record verification history.

Earlier history is not overwritten, migrated, inferred, or relabelled.

## Administrative Routes

Authenticated administrative routes:

- `/admin/collections`
- `/admin/collections/new`
- `/admin/collections/{collection_id}`
- `/admin/collections/{collection_id}/edit`
- `/api/admin/session/collections`
- `/api/admin/session/collections/{collection_id}/update`
- `/api/admin/session/collections/{collection_id}/deactivate`
- `/api/admin/session/collections/{collection_id}/reactivate`

All mutation routes require the verified signed administrator session. Actor attribution comes only from the session.

## Public Collection Detail

Public route:

- `/collections/{collection_reference}`

A public collection page is available only when the collection is active, marked public, and has a valid public reference. The page displays collection summary, governance boundary wording, an explicit no-membership notice, and a public-safe Collection Pathway.

Private, inactive, or unknown collection references return the project-standard unavailable response.

## Public Collection Index

Public route:

- `/collections`

The index displays only eligible active public collections. It supports public-safe search, category filter, institution/source filter, created-year filter, declared coverage-year filter, server-side pagination, deterministic ordering, total matching public collection counts, and safe empty states.

Hidden collection counts are not disclosed.

## Collection Pathway

The public Collection Pathway is derived from authoritative stored collection history. It exposes public-safe action labels, timestamps, actors, and active/public state changes. It does not expose administrative notes, deactivation notes, raw state JSON, internal IDs, session data, credentials, secrets, or private snapshots.

Collection Pathway remains separate from Publication Pathway, Publication Provenance, Association Pathway, Administrative Audit, and record verification history.

## Explicit Membership Exclusion

CDE v12.14 does not implement:

- adding documents to collections;
- removing documents from collections;
- collection membership references;
- collection membership history;
- sequence positions;
- previous/next document navigation;
- collection document counts;
- document-side collection cards;
- automatic Strike range extraction;
- automatic chronology;
- automatic grouping.

These are reserved for CDE v12.15 — Collection Membership Governance.

## Security Boundaries

CDE v12.14 preserves the existing security model:

- all collection mutations require authenticated administrator session;
- actor comes only from the verified signed session;
- private collections are never publicly rendered;
- inactive collections are never publicly rendered;
- administrative notes are never public;
- raw state JSON is never public;
- public users cannot mutate collections;
- query parameters cannot alter collection state;
- titles, notes, and descriptions are HTML-escaped;
- credentials, secrets, session identity, storage paths, and environment values are not rendered publicly.

## Preserved Behaviour

CDE v12.14 does not change:

- record creation, verification, hashes, evidence, or lineage;
- document intake, lifecycle, publication rules, SHA-256, or exact-byte preservation;
- Public Document Library behaviour;
- Publication Provenance or Publication Pathway;
- association creation, history, public references, Association Pathway, or Public Association Index;
- Administrative Audit;
- Public Record Index;
- image view/download;
- PDF download;
- authentication or session behaviour;
- public footer behaviour;
- existing public/private visibility rules.

## v12.15 Readiness

The collection object is designed so a later governed collection-membership layer can link independently preserved documents to collection identities without destructive schema changes. No membership table is created in v12.14.

## Validation Results

Validation performed for this stage:

- Governed Archive Collections focused tests pass.
- Public Association Index tests pass.
- Public Association Traceability tests pass.
- Public Record–Document Association tests pass.
- Public Document Library tests pass.
- Administrative Audit tests pass.
- Admin Document Intake tests pass.
- Admin Session tests pass.
- Admin Navigation Console tests pass.
- Public footer tests pass.
- Full regression suite, Python compile checks, `git diff --check`, and conflict-marker checks are recorded in the completion report.
