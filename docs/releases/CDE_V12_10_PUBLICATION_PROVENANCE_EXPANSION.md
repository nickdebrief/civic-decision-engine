# CDE v12.10 — Publication Provenance Expansion

## Purpose

CDE v12.10 expands the Public Document Library detail page so each Published document presents a fuller public provenance account. The page now shows how the document entered CDE, what server-detected format was admitted, when intake occurred, which lifecycle transitions were recorded, who performed those administrative transitions, when approval and publication occurred, which SHA-256 digest identifies the original uploaded bytes, and how the public presentation relates to the preserved original file.

This is a public provenance presentation and derivation stage. It is not a new evidence verification system, lifecycle model, publication rule, authentication layer, or public audit endpoint.

## Relationship to v12.8, v12.8.1, and v12.9

CDE v12.8 added PDF, JPEG, and PNG intake through the existing authenticated lifecycle while preserving exact uploaded bytes. CDE v12.8.1 separated inline image viewing from original-image downloading. CDE v12.9 added an authenticated Administrative Audit page for cross-record lifecycle traceability.

CDE v12.10 keeps the Administrative Audit separate and expands only the public detail page for documents already eligible under Public Document Library rules.

## Administrative Audit vs Public Provenance

Administrative Audit is an authenticated consolidated inspection table across intake records. Public provenance is a document-specific public explanation shown only on a Published document detail page.

Public provenance does not expose private audit surfaces, unpublished document histories, private notes, storage paths, session identity, credentials, or administrative routes.

## Authoritative Provenance Sources

The public provenance view is derived from existing stored values:

- document metadata;
- server-derived document format;
- original filename;
- file size;
- SHA-256 digest;
- current lifecycle status;
- stored `status_history` entries;
- publication timestamp derived from lifecycle history.

No duplicate authoritative provenance storage is introduced.

## Publication Timestamp Derivation Rule

The displayed publication timestamp is the earliest stored lifecycle event whose new status is `published`. If older metadata lacks such an event but contains an existing publication timestamp, that stored metadata value is used as a conservative compatibility fallback.

If multiple Published transitions exist due to historical irregularity, all stored transitions remain visible in the Publication Pathway. The displayed publication timestamp continues to use the earliest stored transition into Published.

## Historical Actor Preservation

Recorded administrative actors are displayed exactly as stored. Historical `admin` values remain `admin`; named actors such as `nick` remain unchanged. The public page does not infer authorship, responsibility, verification, or legal certification from actor names.

## Lifecycle Pathway Rendering

The Publication Pathway table displays one row per stored lifecycle event for the published document. Columns are:

- Timestamp;
- Previous status;
- New status;
- Actor;
- Note.

Rows are rendered chronologically from earliest to latest. Missing fields render with a neutral dash. No synthetic lifecycle events are created.

## Exact-Byte SHA-256 Wording

The public page states that the SHA-256 digest identifies the exact original bytes admitted through Document Intake. The wording clarifies that this supports byte-level comparison of the preserved file but does not independently establish authorship, factual accuracy, legal status, or external authenticity.

The digest is not described as a digital signature, proof of ownership, or proof of truth.

## Presentation-Mode Derivation

Presentation mode is derived from server-detected document format:

- PDF: Downloadable PDF.
- JPEG and PNG: Inline image view and original-file download.

CDE v12.10 does not alter Content-Disposition behaviour, image rendering, original-file download behaviour, PDF download behaviour, or preserved uploaded bytes.

## Backward Compatibility

Existing published records remain readable, including older PDF records without explicit document-format metadata, records with historical `admin` actors, empty transition notes, missing optional reference identifiers, and incomplete lifecycle history.

Missing optional or historical fields render neutrally rather than being inferred from current session state, filesystem metadata, deployment time, or the current date.

## Public Security Boundaries

Public provenance does not expose:

- private notes;
- proposed storage locations;
- internal file paths;
- sidecar paths;
- session identity;
- session cookies;
- session secrets;
- configured environment variables;
- credentials;
- unpublished document metadata;
- rejected or archived document history;
- other documents’ audit entries;
- authenticated-only routes.

The provenance section is available only through the existing public detail route for documents already marked Published under current rules.

## Preserved Behaviour

CDE v12.10 does not change:

- document lifecycle behaviour;
- publication rules;
- actor attribution;
- stored lifecycle history;
- exact-byte preservation;
- SHA-256 calculation;
- access controls;
- Public Document Library eligibility;
- public/private boundaries;
- PDF/JPEG/PNG validation;
- image view/download behaviour;
- PDF download behaviour;
- storage paths;
- document intake;
- Administrative Audit;
- evidence handling;
- verification;
- hashing;
- database schema;
- Public Record Index;
- public footer navigation;
- Public Document Library search or filters.

## Validation Results

Validation includes focused Public Document Library tests, admin document intake tests, Administrative Audit tests, admin session tests, admin navigation tests, public footer tests, the full regression suite, Python compile checks, `git diff --check`, and conflict-marker scanning.

The tests confirm provenance rendering for published PDF, JPEG, and PNG records; unpublished/private/rejected/archived access boundaries; exact lifecycle event preservation; historical actor preservation; earliest Published transition derivation; neutral missing-field rendering; malicious metadata escaping; no storage path or private-note exposure; unchanged image inline/download behaviour; unchanged PDF download behaviour; unchanged Public Document Library search and filters; and authenticated-only Administrative Audit access.
