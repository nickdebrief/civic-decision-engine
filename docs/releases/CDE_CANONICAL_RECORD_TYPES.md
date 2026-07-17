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
| `public_submission` | Public Submission |
| `policy_event` | Policy Event |
| `research_record` | Research Record |

Unsupported values are rejected with `record_type_invalid`.

## Backward Compatibility

Existing records remain valid and unchanged in meaning. Databases without a
`record_type` column are upgraded idempotently, and records with absent, NULL,
or empty type values are interpreted as `strike`.

The migration does not rename existing references, rewrite lifecycle state,
alter findings, conditions, signals, trajectories, timestamps, public URLs,
associations, audit history, or publication state.

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

The workflow continues to preserve:

- one selected public record per association;
- Published-only document eligibility;
- signed-session actor attribution;
- relationship type controls;
- public and administrative notes;
- duplicate-association protection;
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
