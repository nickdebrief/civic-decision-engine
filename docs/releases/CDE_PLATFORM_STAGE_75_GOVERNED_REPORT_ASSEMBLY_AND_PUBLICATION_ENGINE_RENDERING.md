# CDE Platform Stage 75 — Governed Report Assembly and Publication-Engine Rendering

## Status

Implemented · pending merge · pending deployment

Stage 75 is an authenticated, internal report-specification layer. The CDE
deliberately selects and freezes a `canonical_record_report`; the documented
Publication Engine v2.0.0 renders and validates the frozen specification. The
renderer receives no database connection and makes no content-selection or
governance decision.

## Initial Boundary

The first increment supports one report type, `canonical_record_report`, based
on one Canonical Record and deliberately selected eligible Published Documents
and record-document associations. It produces private DOCX and HTML artifacts.
PDF, public reports, Stage 73 integration, Published Document conversion,
automatic summaries, automatic relationships, queues and background workers are
out of scope.

The report specification stores canonical identities together with immutable
selected display snapshots, ordered sections, inclusion rationales, explicit
exclusions, qualifications, limitations, content types, requested formats,
engine version `2.0.0`, template/profile metadata and a SHA-256 digest. Later
source changes cannot silently alter an existing version. Duplicate selections
are rejected rather than normalised. The primary record, selected documents
and associations are re-resolved immediately before generation, including
status and hash checks.

## Governance

> A REPORT PRESENTS THE RECORD—IT DOES NOT REPLACE IT.

Inclusion is not endorsement. Exclusion is not proof of absence. A relationship
is not proof. Chronology is not causation. Attribution is not confirmation. A
summary is not original language. Printing and downloading are not publication.
Publication Engine validation is not legal validation. The record must
preserve original language; faithful paraphrases and administrative summaries
are labelled and are never rendered as quotations.

Reports require deliberate internal distribution classes (`internal_working`
or `restricted_review`), authenticated actor identity, declarations and
assembly, privacy, redaction and generation lifecycle events. Actor separation
is enforced where the current identity model can establish it; the creator may
not perform the later review stages. Generation records attempts, diagnostics,
artifact digests and authenticated downloads. Failed validation serves no
artifact.

No Stage 75 public route or navigation exists. Reports are not determinations,
Published Documents or Stage 73 publication snapshots. Stages 60–74 remain the
owners of their existing objects and relationships.

## Limitations

The current increment uses the existing typed Publication Engine renderers in
an isolated subprocess and relies on the deployment's declared renderer
dependencies. Outputs are staged in a private temporary directory, validated,
then atomically promoted without overwriting an existing artifact. Failed
generation and registration remove partial output and retain only safe
diagnostics. Artifact expiry, external distribution approval, PDF output,
physical-print detection, queued generation and broader report types require a
separate review. Generation is deliberately synchronous and bounded by a
two-minute adapter timeout.
