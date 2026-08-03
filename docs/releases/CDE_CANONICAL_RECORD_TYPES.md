# Canonical Record Types

## Purpose

This stage expands the Civic Decision Engine public record model beyond
Strike-only records by introducing a governed canonical `record_type` field.
Published documents can now be associated with the public CDE record that
accurately represents the civic or administrative event they belong to, such as
a Complaint record for an initial complaint evidence package.

## Controlled Vocabulary

The initial governed vocabulary uses stable machine values and public display
labels:

| Machine value | Display label |
| --- | --- |
| `strike` | Strike |
| `complaint` | Complaint |
| `investigation` | Investigation |
| `decision` | Decision |
| `proceeding` | Proceeding |
| `administrative_action` | Administrative Action |
| `clinical_episode` | Clinical Episode |
| `medical_event` | Medical Event |
| `treatment_episode` | Treatment Episode |
| `care_episode` | Care Episode |
| `clinical_record` | Clinical Record |
| `public_submission` | Public Submission |
| `policy_event` | Policy Event |
| `research_record` | Research Record |

Unsupported values are rejected with `record_type_invalid`.

The ordering above is used by administrator Record Type selectors. The five
clinical values are available through the same creation and superseding paths
as every existing type.

## Semantic Classification Boundary

Record Type describes the meaning assigned to a Canonical Record. It does not
change how that record is governed. Selecting a clinical type does not alter:

- publication workflow or lifecycle transitions;
- provenance or evidence preservation;
- verification or hashing;
- Record-Document Associations;
- Public Archive Explorer presentation or filtering semantics;
- Administrative Audit;
- canonical identifiers or public URLs.

No clinical meaning is inferred from document content. During explicit creation
from a Published Document, its governed category may preselect a clinical type
from the centralized recommendation mapping. This is an editable advisory
default only; the administrator's submitted selection remains authoritative.

## Backward Compatibility

Existing records remain valid and unchanged in meaning. Databases without a
`record_type` column are upgraded idempotently, and records with absent, NULL,
or empty type values are interpreted as `strike`.

The migration does not rename existing references, rewrite lifecycle state,
alter findings, conditions, signals, trajectories, timestamps, public URLs,
associations, audit history, or publication state.

No migration is required for the additional controlled-vocabulary values.
Existing values and the default `strike` behaviour remain unchanged.

## Administrator Guidance

Choose the narrowest type supported by the governed record context:

- **Clinical Episode** for a bounded period of clinical activity;
- **Medical Event** for a discrete medically relevant occurrence;
- **Treatment Episode** for a bounded course of treatment;
- **Care Episode** for a bounded period of care delivery;
- **Clinical Record** for a clinical record that is not more accurately
  represented by one of the episode or event classifications.

Record Type remains editable only through an explicit administrative creation
or superseding action. Changing it does not convert evidence, rewrite source
documents, or alter the established verification hash inputs.

The **Create Canonical Record from Published Document** form displays
**Recommended based on Published Document category** when an explicit category
mapping exists. Unmapped categories preserve the established default. The
recommendation does not inspect document bytes, OCR, filenames, free text, or
relationships, and it does not save or create a record automatically.

Once the administrator creates the record, the source Published Document shows
the resulting Canonical Record instead of continuing to offer the creation
action. This state uses persisted source-document provenance only. Secondary
Record–Document Associations remain separate and do not imply that the record
was created from the document.

## Handbook Alignment

For **Volume II — Platform Operations**, the administrator workflow should
describe these values as explicit choices in Canonical Record creation and
superseding, and explain that a category-based recommendation remains freely
editable before saving.

For **Volume III — Investigator Guide**, investigators should interpret Record
Type as navigational and semantic metadata. A clinical label does not establish
clinical truth, change evidential weight, or replace review of provenance and
the underlying governed evidence. A recommendation records no independent
finding and does not displace administrator judgment.

## Verification Hash Treatment

`record_type` is not added to the existing canonical verification-hash input
set. Legacy records therefore continue to verify against their previously
issued hashes. The canonical hash remains derived from the established record
fields:

- reference;
- generated timestamp;
- finding;
- trajectory;
- conditions;
- system state;
- generated-by value.

Future verification semantics can evolve through an explicit versioned hashing
strategy if required.

## Reference Behaviour

Existing Strike references remain unchanged. This stage stores and displays the
record type independently from the canonical reference. Suggested future
non-Strike prefixes, such as `CMP`, `INV`, and `DEC`, are compatible with the
model but no existing public references are migrated or renamed by this stage.

## Public Presentation

Public record and verification views display the canonical record type as
additional semantics while preserving the generic public record terminology.
The Public Record Index can search and filter by record type.

## Record-Document Associations

The governed Record-Document Association workflow now carries record type
metadata into the public CDE record selector. Complaint and other non-Strike
records can be selected as parent records when they are public and eligible.
The submitted association value remains the exact canonical record reference.

A Canonical Record created from a Published Document retains that document as
its authoritative source through the record's persisted source provenance. The
association workflow displays the source and prevents a different Published
Document from being assigned a second `Source document` relationship. Further
documents should use an appropriate governed relationship such as Supporting
document or Related document. A record without persisted source provenance may
still receive a Source document association through the existing workflow.

The workflow continues to preserve:

- one selected public record per association;
- Published-only document eligibility;
- signed-session actor attribution;
- relationship type controls;
- public and administrative notes;
- duplicate-association protection;
- one authoritative source Published Document where source provenance exists;
- record verification hashes;
- document SHA-256 values.

## Post-Publication Governance

Changing the type of a Published canonical record would alter its public
meaning. This stage does not introduce silent in-place public type mutation.
Any later change to a published record type should use a governed correction or
versioning pathway rather than rewriting historical meaning.

## Preserved Boundaries

This stage does not change document publication semantics, document lifecycle,
record lifecycle, evidence handling, record verification, document hashing,
association lifecycle, archive collections, collection membership, public
footer navigation, authentication, authorization, or public/private visibility
boundaries.

## Validation

Focused regression coverage confirms that:

- legacy records without `record_type` behave as Strike records;
- a Complaint record can be created;
- unsupported record types are rejected;
- record type is displayed, searchable, and filterable;
- Complaint records appear in the Record-Document Association selector;
- a Published document can be associated with a Complaint record;
- verification hashes remain based on the established canonical inputs.
