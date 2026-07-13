# CDE v12.9 — Administrative Audit Traceability

## Purpose

CDE v12.9 introduces a dedicated authenticated Administrative Audit view for inspecting Document Intake lifecycle actions across records. The audit page answers what administrative action occurred, when it occurred, who performed it, which document record it affected, what lifecycle transition occurred, and what transition note accompanied the action.

This stage is an inspection layer over existing administrative lifecycle history. It does not validate evidence, determine truth, establish legal status, alter public visibility, create lifecycle states, or modify document records.

## Relationship to v12.7, v12.8, and v12.8.1

CDE v12.7 introduced signed-session administrator identity display and named actor attribution for new lifecycle events. CDE v12.8 extended authenticated Document Intake to PDF, JPEG, and PNG records while preserving exact bytes and lifecycle boundaries. CDE v12.8.1 separated inline public image viewing from original-image downloading and improved the existing lifecycle-history table presentation.

CDE v12.9 builds on those stages by making the already-recorded lifecycle-history entries inspectable across intake records in one administrative table.

## Authoritative Audit Source

Audit rows are derived from the authoritative `status_history` entries stored with Document Intake metadata sidecars. Each row preserves the stored event timestamp, previous status, new status, actor, transition note, document identity, and current document status.

No synthetic historical events are generated. Historical `admin` actor values remain unchanged. Named actor values such as `nick` remain displayed exactly as stored. Missing fields are displayed with a neutral dash rather than invented values.

## Audit Columns

The Administrative Audit table includes:

- Timestamp
- Document title
- Reference identifier
- Filename
- Previous status
- New status
- Actor
- Note
- Current document status
- Actions

The action link opens the existing authenticated Document Intake Review page for the affected document. The audit table itself contains no edit, delete, archive, publication, approval, or lifecycle-transition controls.

## Filtering

The page supports conservative server-side filters for:

- free-text search;
- actor;
- previous status;
- new status;
- current document status;
- document format;
- date from;
- date to.

Free-text search covers document title, filename, reference identifier, actor, transition note, and institution/source. Filters use AND semantics and do not alter stored data.

## Pagination and Ordering

Audit events are ordered newest first by default with deterministic tie-breaking. Server-side pagination uses a sensible default page size and a bounded maximum page size. Pagination links preserve active filters.

Invalid page values are safely normalised. The page displays total matching audit events, total affected documents, current page, and page count.

## Authenticated Access

The audit page is available only at `/admin/audit` and requires the existing verified signed administrator session. It uses the shared Administration Console navigation and displays the signed-in administrator identity through the existing session-derived identity indicator.

The page does not read identity from query parameters, form fields, hidden inputs, client-supplied actor values, or unverified cookies.

## Historical Actor Preservation

Historical actor values are displayed exactly as stored. Earlier generic `admin` entries remain `admin`. Newer named entries remain the authenticated username recorded at the time of the lifecycle action. CDE v12.9 does not migrate, normalise, relabel, or reinterpret historical actors.

## Read-Only Nature

The Administrative Audit view is read-only. It does not provide inline lifecycle transitions, mutation forms, bulk actions, deletion controls, audit editing, exports, charts, rankings, personnel assessment, or analytics scoring.

Lifecycle changes continue to occur only through the existing authenticated Document Intake Review page.

## Responsive Presentation

The audit table uses semantic classes and a responsive horizontal-scroll wrapper. Timestamp, lifecycle-status, actor, reference, document, note, and action columns have readable minimum widths. Notes and actor values are not truncated.

## Security Boundaries

The audit page does not expose plaintext credentials, session secrets, storage paths, private file locations, public/private visibility controls, or public document publication internals. Query parameters filter the read-only view only; they cannot mutate audit history or override actor attribution.

No audit content appears on public pages, and public users cannot enumerate private or unpublished documents through audit routes.

## Preserved Behaviour

CDE v12.9 does not change:

- supported upload formats;
- PDF/JPEG/PNG validation;
- magic-byte detection;
- extension/type matching;
- exact-byte preservation;
- SHA-256 calculation;
- sidecar metadata;
- upload-size limits;
- image preview behaviour;
- public image-view behaviour;
- original-image download behaviour;
- PDF behaviour;
- lifecycle states;
- lifecycle transition rules;
- approval/publication separation;
- actor attribution;
- transition-note storage;
- internal notes;
- authentication;
- session signing;
- session expiry;
- document storage;
- database schema;
- evidence handling;
- verification logic;
- record hashing;
- classification;
- Public Record Index;
- Public Document Library listing;
- Public Document Library search or filters;
- publication provenance summary;
- public footer navigation;
- public/private visibility boundaries.

## Validation Results

Validation performed for this stage includes focused Administrative Audit tests, existing admin session tests, admin navigation tests, document intake tests, Public Document Library tests, public footer tests, the full regression suite, `git diff --check`, and a conflict-marker check.

The audit tests confirm authenticated access, stored lifecycle-history preservation, exact actor display, historical actor preservation, current document status display, missing-reference handling, newest-first ordering, deterministic tie-breaking, bounded pagination, filter preservation, AND filter semantics, read-only table behaviour, semantic responsive presentation, absence of storage paths, unchanged Public Document Library behaviour, unchanged public image view/download behaviour, and unchanged private/public visibility boundaries.
