# CDE v12.13 — Public Association Index and Discovery

## Purpose

CDE v12.13 makes eligible CDE v12.12 record-document associations publicly discoverable as a governed collection. The stage adds a public index at `/associations` so users can find declared relationships without first knowing the linked civic record or Published document.

Discovery makes governed relationships findable. It does not create, infer, validate, rank, score, mutate, or certify associations.

## Relationship To v12.12

CDE v12.12 introduced stable public association references and dedicated public association pages at `/associations/{association_reference}`. CDE v12.13 preserves those pages and adds a collection-level index over the same eligibility model.

The public pathway is now:

`Public Association Index -> Public Association Record -> Civic Record / Published Document`

## Public Index Route

The public route is:

`/associations`

The route requires no authentication and displays only active, public, currently eligible associations. It does not expose administrative controls, signed-in identity, session data, storage paths, private notes, raw state JSON, credentials, environment variables, or unpublished document metadata.

## Public Eligibility

An association appears in the public index only when all conditions are true:

- the association is active;
- the association is marked public;
- the association has a stable public reference;
- the linked civic record remains publicly accessible;
- the linked document is Published and publicly accessible.

Eligibility is evaluated dynamically. If a linked record or document becomes ineligible, the association is removed from the public index and its public detail page remains unavailable under the v12.12 rules. The association, public reference, and full administrative history remain intact.

## Search Fields

The public search field matches public-safe fields only:

- public association reference;
- public relationship label;
- controlled relationship type;
- public note;
- civic-record reference;
- civic-record title or summary;
- document title;
- document reference identifier;
- document institution/source;
- document category.

Search is case-insensitive, trimmed, and applied only after public eligibility is evaluated. It does not search administrative notes, raw history JSON, storage paths, session data, private document notes, or hidden association metadata.

## Filters

The public index supports filters for:

- relationship type;
- record reference;
- document reference;
- institution/source;
- document category;
- association created year;
- document format.

Relationship types remain limited to the server-controlled association types. Document formats are limited to the public labels `PDF`, `JPEG`, and `PNG`. Invalid filter values fail safely and cannot force private, inactive, unavailable, or unpublished associations into the result set.

## Pagination

Pagination is server-side and deterministic. The default page size is 25. Supported page sizes are 10, 25, 50, and 100. Invalid page and page-size values fall back safely or clamp to valid bounds.

Previous and next links preserve active filters. Out-of-range page values clamp to the available page count without exposing hidden associations.

## Ordering

The default ordering is:

1. association creation timestamp, newest first;
2. public association reference as a deterministic tie-break;
3. internal association ID only as an internal final tie-break.

Optional sort controls are available for newest, oldest, association reference, record reference, and document title. Internal association IDs are not used in public URLs.

## Result Presentation

Each public result row presents:

- public association reference;
- public relationship label;
- public note where present;
- civic-record reference and summary;
- Published-document title and reference identifier;
- institution/source;
- category;
- document format;
- association created date;
- separate actions to view the association, civic record, and Published document.

The result table uses responsive wrapping and a horizontal wrapper on smaller screens. Long references, titles, notes, and hashes remain inspectable rather than being truncated.

## Public Navigation

The index links back to the Public Record Index and the Public Document Library. Public association detail pages include a Back to Public Association Index link.

The public index does not add administration navigation to public pages.

## Public-Safe Projection

The index uses a public-safe projection derived from the association row, linked public record context, and linked Published document context. It includes public references, relationship labels, public notes, public record context, public document context, and current eligibility.

It excludes administrative notes, deactivation notes, raw previous-state JSON, raw new-state JSON, storage paths, sidecar paths, private document metadata, unavailable linked-object metadata, session contents, credentials, secrets, and environment variables.

## Security Boundaries

The public index cannot create, update, deactivate, reactivate, delete, publish, or validate associations. Query parameters cannot alter eligibility, override association state, expose hidden objects, or mutate stored data.

Private associations, inactive associations, associations linked to unavailable records, and associations linked to unpublished documents are not enumerable through search, filters, counts, pagination, or public URLs.

## Non-Evidential Boundary

The page states that listing an association does not make a document evidence for a record, alter record verification, change document provenance or lifecycle, or independently establish evidential sufficiency, factual truth, authorship, legal status, responsibility, or external validation.

## Reusable Query Architecture

CDE v12.13 adds a reusable public association index query/projection helper in the association service layer. The helper applies the same public eligibility definition used by the v12.12 public association detail route and reciprocal public record/document rendering.

## Preserved Behaviour

CDE v12.13 does not change:

- association creation, update, deactivation, or reactivation;
- association public-reference format or immutability;
- association history;
- association actor attribution;
- duplicate active-association prevention;
- public association detail eligibility;
- Association Pathway;
- record creation, verification, hashes, versioning, lineage, or evidence;
- document intake, validation, lifecycle, exact-byte storage, or SHA-256;
- publication eligibility;
- Publication Provenance;
- Publication Pathway;
- Administrative Audit;
- Public Record Index behaviour;
- Public Document Library behaviour;
- image inline-view or download behaviour;
- PDF behaviour;
- authentication;
- footer navigation;
- public/private visibility boundaries.

## Validation Results

Validation performed for this stage:

- Focused public association index tests pass.
- Public association traceability tests pass.
- Public record-document association tests pass.
- Public Document Library tests pass.
- Administrative Audit tests pass.
- Admin Document Intake tests pass.
- Admin Session tests pass.
- Admin Navigation Console tests pass.
- Public footer tests pass.
- Full regression suite, Python compile checks, `git diff --check`, and conflict-marker checks are recorded in the completion report.
