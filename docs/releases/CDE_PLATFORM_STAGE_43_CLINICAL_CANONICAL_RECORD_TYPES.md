# CDE Platform Stage 43 — Clinical Canonical Record Types

## Purpose

CDE Platform Stage 43 extends the controlled Canonical Record Type vocabulary
so medical and clinical evidence can be classified without relying on the
generic Strike type.

## Clinical Record Types

The ordered vocabulary now includes:

- Clinical Episode (`clinical_episode`);
- Medical Event (`medical_event`);
- Treatment Episode (`treatment_episode`);
- Care Episode (`care_episode`);
- Clinical Record (`clinical_record`).

All existing values remain available and retain their existing meaning. The
default remains Strike.

## Behaviour

Record Type remains semantic metadata. The new values use the ordinary
Canonical Record creation, superseding, serialization, indexing, filtering,
association, verification, publication, and audit paths. They do not introduce
a clinical workflow or object model.

The following remain unchanged:

- canonical identifiers and public URLs;
- verification-hash inputs and existing hashes;
- provenance and evidence preservation;
- publication and lifecycle behaviour;
- Record-Document Associations;
- Public Archive Explorer and Administrative Audit behaviour;
- document ingestion.

No database migration or dependency change is required.

## Administrative Workflow

Every administrator Record Type selector uses the same ordered controlled
vocabulary. Administrators may choose a clinical type during explicit creation
or when creating a superseding version of an existing record.

The **Create Canonical Record from Published Document** workflow preserves its
existing category-based suggestion and default. Clinical classification is a
manual decision; no automatic clinical inference is introduced.

## Public Presentation and Filtering

Clinical values serialize as the same `record_type` string field used by all
existing records. Their display labels participate in existing indexing and
filtering. Public presentation gains no clinical-specific workflow, claim, or
evidence treatment.

## Handbook Guidance

The next source-controlled edition of **Volume II — Platform Operations** should
list the five clinical choices in Canonical Record administration and state
that selection is explicit.

The next source-controlled edition of **Volume III — Investigator Guide** should
explain that a clinical Record Type assists classification and discovery but
does not determine clinical truth, evidential weight, provenance, or
verification. The repository currently contains published handbook PDFs rather
than editable Volume II and Volume III sources, so those binaries are not
rewritten by this implementation stage.

## Validation

Focused coverage verifies the enum values, selector ordering, record creation,
superseding updates, API serialization, public filtering, indexing labels,
legacy defaults, and unchanged verification-hash behaviour.
