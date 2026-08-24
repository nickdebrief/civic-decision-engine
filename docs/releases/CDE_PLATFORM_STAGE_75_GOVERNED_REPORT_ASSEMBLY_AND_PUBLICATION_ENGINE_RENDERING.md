# CDE Platform Stage 75 — Governed Report Assembly and Publication-Engine Rendering

## Status

Implemented · merged · deployed

Implementation integration and deployment evidence:

- Implementation branch: `cde-platform-stage-75-governed-report-assembly`
- Implementation commit: `d1283d52cb570d09777782fbf066609989a7b7e5`
- Pull request: [#390](https://github.com/nickdebrief/civic-decision-engine/pull/390)
- Merge method: rebase
- Canonical implementation revision: `3bcc4b387d9404ce37b35cd024a2d813156c640d`
- CI/checks: none configured
- Deployment ID: `6027987948`
- Deployment revision: `3bcc4b387d9404ce37b35cd024a2d813156c640d`
- Environment: `precious-gentleness / production`
- Created: `2026-08-21T19:34:14Z`
- Successful: `2026-08-21T19:34:43Z`
- Terminal status: successful

Accepted verification evidence:

- Stage 75 focused: 37 passed, 7 subtests.
- Affected suite: 101 passed, 7 subtests.
- Publication Engine v2.0.0 plus Stage 75: 151 passed, 10 subtests.
- Canonical Stage 60–75 inventory: 23 files; forward, reverse and deterministic mixed runs each passed 353 tests with 26 subtests.
- Full applicable regression: 1,530 passed, 403 subtests. The only exclusion was `tests/test_cases/test_cases.py`, which performs a documented import-time request to `127.0.0.1:8000`.
- Stage Ledger validator, compilation, `git diff --check` and conflict scan passed.
- Public smoke checks returned 200 for `/`, `/records` and `/determinations`; synthetic and malformed determination details returned 404; protected Stage 75 routes returned 401; plausible public report paths returned 404.
- Authenticated visual verification confirmed the bounded internal interface, empty deliberate selectors, DOCX/HTML-only output, absent PDF, no JSON editor, and exactly one copper Governed Reports navigation marker.

Stage 75 remains internal and authenticated. Its initial report type is
`canonical_record_report`, with DOCX and HTML outputs only. PDF remains
excluded. Generation is not approval, printing is not publication, and a
report is not a determination. Stage 73 remains the separate public
determination-publication boundary. No public Stage 75 route, navigation or
artifact serving exists. No report or artifact was created, generated,
downloaded, distributed, printed or published during verification, and no
production data changed.

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

The local sole-administrator governance amendment adds an explicit,
deployment-configured creator-confirmation mode without changing a frozen
specification. Each gate is recorded in an immutable Stage 75 qualification
envelope and distinct append-only events. Creator confirmation is not
independent review, is restricted to `internal_working`, and carries the
controlled `sole-admin-v1` disclosure through DOCX, HTML and PDF equivalence.
Aliases, worker identities and automation do not establish independence.

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
