# CDE v12.11 — Public Record–Document Association

## Purpose

CDE v12.11 introduces a controlled association layer between the Public Record Index and the Public Document Library. It allows authenticated administrators to declare inspectable relationships between existing public CDE records and existing Published documents while keeping records, documents, provenance, evidence status, publication status, and verification status distinct.

## Relationship To v12.9 And v12.10

CDE v12.9 created authenticated Administrative Audit traceability over Document Intake lifecycle events. CDE v12.10 expanded public publication provenance for Published documents. CDE v12.11 does not merge those histories. Association history is a separate administrative history for the record-document association object only.

## Record, Document, And Association Remain Distinct

A CDE record remains a CDE record. A Published document remains a Published document. The association is a separate governed object referencing both authoritative objects. The association does not copy record contents, duplicate document metadata, alter record hashes, alter document SHA-256 values, or make the linked document part of record evidence.

## Association Storage Model

The implementation adds two idempotently created SQLite tables:

- `record_document_associations`
- `record_document_association_history`

Associations store record reference, document ID, document reference identifier where available, relationship type, public label, public note, administrative note, active state, public visibility, creation/update/deactivation timestamps, and actor values. History entries store action type, timestamp, actor, previous state, new state, and note. No credentials, sessions, storage paths, record bodies, document bytes, or file contents are stored in association history.

## Relationship Types

The server-defined relationship types are:

- `supporting_document` — Supporting document
- `source_document` — Source document
- `related_document` — Related document
- `publication_context` — Publication context
- `preserved_visual_record` — Preserved visual record
- `methodology_reference` — Methodology reference
- `procedural_record` — Procedural record
- `evidence_audit` — Evidence audit

Arbitrary client-supplied relationship types are rejected. Relationship type does not alter findings, conditions, signals, evidence sufficiency, classification, verification, document lifecycle, or publication state.

## Creation Rules

Association creation requires an authenticated administrator session. The target record must exist in the public record store as the latest public record. The target document must exist and be currently Published through Document Intake. Duplicate active associations with the same record reference, document ID, and relationship type are rejected. Inactive historical associations remain inspectable and should be explicitly reactivated rather than silently duplicated.

## Update Rules

Administrators may update relationship type, public label, public note, administrative note, and public visibility. Record reference and document ID are immutable after creation in v12.11. If the wrong objects were linked, the incorrect association should be deactivated and a new association created. Every update records an immutable association-history event and preserves the original creation actor and timestamp.

## Deactivation And Reactivation

Associations are not permanently deleted in v12.11. Deactivation requires a note, records actor and timestamp, removes the association from public display, and preserves the association and history. Reactivation is explicit, records actor and timestamp, and restores public display only when the association is public, active, and both linked objects remain publicly eligible.

## Association Audit History

Association history is separate from Document Intake `status_history`, Administrative Audit lifecycle events, Publication Provenance, Publication Pathway, and record verification history. It is not inserted into public document Publication Pathway and does not rewrite historical actors or notes.

## Public Record Presentation

Public record detail pages include an `Associated Public Documents` section only for active, public associations where the linked document is currently Published and the record is publicly accessible. The section displays document title, reference identifier, relationship label, category, format, publication date, optional public note, and a link to the Public Document Library detail page. Administrative notes remain private.

## Public Document Presentation

Public document detail pages include an `Associated Civic Records` section only for active, public associations where the linked record remains publicly accessible. The section displays record reference, finding summary, relationship label, generated date, trajectory, and a link to the public record detail page. Publication Provenance and Publication Pathway remain unchanged.

## Public Eligibility Derivation

Public association display is derived dynamically from association active state, association public visibility, record public eligibility, and document Published status. If a linked document or record becomes ineligible, the association is hidden publicly but retained administratively. Eligibility changes do not automatically deactivate or delete associations.

## Administrative Identity

All association creation, update, deactivation, and reactivation actor values are derived only from the verified signed administrator session. Client-supplied actor, username, query parameter, form value, filename, or header values cannot override association attribution.

## Security Boundaries

Association administration requires authentication. Public users cannot create, update, deactivate, reactivate, or enumerate private associations. Public pages show only active, public, eligible associations and do not expose administrative notes, storage paths, private document metadata, credentials, environment variables, session data, or unpublished documents.

## Non-Evidential Boundary

An association records a declared relationship between independently preserved objects. It does not establish evidential sufficiency, factual verification, legal status, authorship, responsibility, endorsement, or proof of either linked object.

## Preserved Behaviour

CDE v12.11 does not change record creation, record verification, record hashes, record lineage, conditions, signals, findings, trajectories, evidence sufficiency, classifications, Public Record Index search or filters, Document Intake, PDF/JPEG/PNG validation, SHA-256 calculation, lifecycle states, lifecycle transitions, actor attribution, Administrative Audit, Publication Provenance, Publication Pathway, image view/download behaviour, PDF downloads, Public Document Library search or filters, publication eligibility, public footer navigation, or public/private visibility boundaries.

## Validation Results

Validation performed for this stage:

- Focused record-document association tests pass.
- Adjacent Public Document Library, Administrative Audit, Document Intake, Admin Session, Admin Navigation, and footer tests pass.
- Full regression suite pass is recorded in the completion report.
- `git diff --check`, conflict-marker search, and Python compile checks are recorded in the completion report.
