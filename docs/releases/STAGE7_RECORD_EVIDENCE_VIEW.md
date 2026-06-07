# Stage 7A — Record-Centric Evidence View

Status:
Implemented / pending review

## Scope

- Read-only admin evidence view.
- Condition targets mapped to supporting attachments.
- Signal targets mapped to supporting attachments.
- Finding target mapped to supporting attachments.
- Record target mapped to supporting attachments.
- Safe attachment metadata only.
- Existing attachment relationship add/remove routes preserved.
- No upload/download capability.
- No public file exposure.
- No storage paths or stored filenames exposed.
- No public manifest eligibility changes.
- No canonical verification changes.

## Purpose

Stage 7A inverts the Stage 6 attachment relationship model.

Stage 6 answers what an attachment supports. Stage 7A answers what evidence
supports each available record target.

The view derives record targets from the latest canonical record fields:

- `conditions_json`
- `signals_json`
- `finding`
- `reference`

It then groups active attachment relationships by target type and target key.
Only active relationships on active, non-deleted attachments are counted.

## Non-Goals

- No attachment upload.
- No attachment download.
- No public attachment serving.
- No file byte exposure.
- No automatic relationship creation.
- No AI relationship suggestions.
- No graph or network visualization.
- No verification hash changes.
- No record versioning changes.

## Stage 7B — Record Evidence Coverage

Stage 7B adds record-level evidence coverage metrics and target-level support
status to the read-only Admin Record Evidence view. It also applies the
standard v12 governance watermark/print presentation to the page.

Coverage is derived from active relationships on active, non-deleted
attachments. Duplicate relationships do not inflate coverage because support is
counted by unique `target_type` and `target_key` record targets.

No upload, download, mutation controls, public file access, storage paths, or
canonical verification changes are introduced.

## Stage 7C — Evidence Support Detail

Stage 7C adds deterministic relationship-level support detail to the read-only
Admin Record Evidence view. Each record target now shows supporting
relationship counts, relationship type breakdowns, attachment-level
relationship listings, and deterministic coverage rationale.

Duplicate relationships are represented in relationship counts and type
breakdowns without inflating supporting attachment counts or record coverage.

It does not change relationship storage, existing add/remove routes, public
exposure, or canonical verification.

## Stage 7D — Evidence Relationship Traceability

Stage 7D adds exact active relationship traces to the read-only Admin Record
Evidence view. Each supported record target now lists the relationship rows
that produce support, including relationship type, target type, target key,
attachment identifier, and attachment title.

Duplicate active relationships are displayed explicitly as separate trace
entries. Inactive relationships and relationships on deleted attachments remain
excluded. Coverage calculations, supporting attachment counts, relationship
storage, existing add/remove routes, public exposure, and canonical
verification remain unchanged.
