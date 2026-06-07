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
