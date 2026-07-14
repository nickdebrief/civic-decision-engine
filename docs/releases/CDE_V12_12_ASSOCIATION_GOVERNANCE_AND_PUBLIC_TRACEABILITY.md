# CDE v12.12 — Association Governance and Public Traceability

## Purpose

CDE v12.12 expands the CDE v12.11 Public Record–Document Association layer with stable public association references and a public traceability page for eligible associations. The stage makes each active, public, eligible association inspectable as its own governed object without changing record verification, document lifecycle, document publication, association history, Publication Provenance, Administrative Audit, evidence handling, or public/private visibility rules.

## Relationship To v12.11

CDE v12.11 introduced governed administrative associations between existing public CDE records and existing Published documents. CDE v12.12 does not create a new association model. It adds public reference identifiers, public routing, public-safe association history projection, and public/admin navigation refinements on top of the v12.11 association tables.

## Public Association Reference

Each association has a server-generated public reference using the format:

`CDE-ASSOC-YYYYMMDD-NNN`

The date component is derived from the association creation timestamp. The sequence is deterministic per date. Existing v12.11 associations without a public reference are backfilled idempotently in creation order without changing original creation timestamps, creation actors, update timestamps, update actors, active state, public visibility, notes, relationship type, linked record, linked document, or stored association history.

Public references are not accepted from client forms, query parameters, request bodies, filenames, headers, or uploaded metadata.

## Public Route

CDE v12.12 adds:

`/associations/{association_reference}`

The route displays only associations that are:

- active;
- marked public;
- linked to a public eligible CDE record;
- linked to a Published document in the Public Document Library.

Invalid references, inactive associations, private associations, associations linked to non-public records, and associations linked to unpublished or unavailable documents return the same public not-found behaviour.

## Public Page Structure

The public association page contains:

- Association summary
- Associated Civic Record
- Associated Public Document
- Association Pathway
- Governance Boundary
- direct links to the linked record and linked document

The page does not expose administrative notes, raw state JSON, internal storage paths, sidecar paths, session state, credentials, configured environment variables, unpublished document metadata, or mutation controls.

## Association Pathway

The Association Pathway is derived from authoritative `record_document_association_history` entries. It presents public-safe event information including timestamp, action, actor, public state summary, and public-safe event note. It does not expose administrative notes or raw previous/new state JSON.

The pathway is separate from:

- Document Intake lifecycle history;
- Administrative Audit;
- Publication Provenance;
- Publication Pathway;
- record verification history.

It does not rewrite historical actors, infer missing actors, generate synthetic events, or migrate history.

## Public Record And Public Document Links

Public record detail pages retain direct links to associated Published documents and add a `View association` link for each eligible association. Public document detail pages retain direct links to associated civic records and add a `View association` link for each eligible association.

These links are rendered only for active, public, eligible associations. The `/documents` route and record verification routes remain unchanged.

## Administrative Refinements

The authenticated association index now displays the public association reference. The association detail page displays the public association reference, public URL, and an `Open public association` action when the association is currently publicly eligible.

Administrative creation, update, deactivation, and reactivation still occur only through authenticated administrator routes. Actor attribution remains derived from the verified signed administrator session.

## Eligibility Rules

Public association traceability is dynamically derived from:

- association active state;
- association public visibility;
- linked record public eligibility;
- linked document Published status.

If any required condition becomes false, the public association page and reciprocal public links become unavailable while the association remains inspectable to authenticated administrators.

## Non-Evidential Boundary

An association records a declared relationship between a public CDE record and a Published document. It does not make the document part of the record's evidence, change evidence sufficiency, certify factual truth, certify legal status, establish authorship, assign responsibility, prove endorsement, alter classifications, or modify record verification.

## Security Boundaries

CDE v12.12 preserves authenticated administration, signed session handling, named actor attribution, public/private document visibility, Published-only document eligibility, and public record eligibility. Public users cannot create, update, deactivate, reactivate, or enumerate private associations through the new public route.

The implementation does not expose private notes, storage paths, unpublished documents, rejected or archived document metadata, credentials, secrets, session contents, or administrator-only routes.

## Preserved Behaviour

CDE v12.12 does not change:

- record creation or verification;
- record hashes;
- public record search or filtering;
- document intake;
- PDF/JPEG/PNG validation;
- magic-byte checks;
- extension/type matching;
- document SHA-256 calculation;
- exact-byte storage;
- document lifecycle states;
- lifecycle transition rules;
- approval/publication separation;
- actor attribution;
- Administrative Audit;
- Publication Provenance;
- Publication Pathway;
- image view/download behaviour;
- PDF download behaviour;
- Public Document Library listing, search, or filtering;
- public footer navigation;
- database schema beyond the backward-compatible association-reference column and index;
- public/private visibility boundaries.

## Validation Results

Validation performed for this stage:

- Focused association public traceability tests pass.
- Existing public record-document association tests pass.
- Public Document Library tests pass.
- Administrative Audit tests pass.
- Admin Document Intake tests pass.
- Admin Session tests pass.
- Admin Navigation Console tests pass.
- Public footer tests pass.
- Full regression suite, `git diff --check`, conflict-marker search, and Python compile checks are recorded in the completion report.
