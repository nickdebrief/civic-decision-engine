# Stage 15F — Evidence Requirements

Status: Implemented / pending review

## Purpose

Stage 15F adds a deterministic Evidence Requirements layer to the Admin Record Evidence view.

Evidence Coverage asks whether evidence is linked. Evidence Sufficiency asks whether linked evidence is strong enough. Evidence Completeness asks whether the record is complete. Evidence Requirements identifies what evidence is still required for incomplete targets to reach sufficiency and record completeness.

## Relationship to Stage 15D

Stage 15F uses the Stage 15D sufficiency thresholds. Active `supports` relationships are the only relationships counted toward requirements:

- `Unsupported`: 0 active supports
- `Partial`: 1 active support
- `Sufficient`: 2 active supports
- `Strong`: 3 or more active supports

## Relationship to Stage 15E

Stage 15E treats targets as complete only when they are `Sufficient` or `Strong`. Stage 15F calculates the additional support required to move `Unsupported` and `Partial` targets toward the `Sufficient` threshold.

## Target Requirement Rules

A target requires additional evidence when its sufficiency is:

- `Unsupported`
- `Partial`

A target does not require additional evidence when its sufficiency is:

- `Sufficient`
- `Strong`

Minimum additional attachment requirements:

- 0 active supports: 2 additional supporting attachments required
- 1 active support: 1 additional supporting attachment required
- 2 active supports: 0 additional supporting attachments required
- 3 or more active supports: 0 additional supporting attachments required

## Group Requirement Rules

Group requirements are calculated for:

- condition targets
- signal targets
- finding targets
- record target

Group status values:

- `outstanding`: one or more targets in the group require additional supporting evidence
- `none_required`: all targets in the group are sufficient or strong
- `not_applicable`: the group contains no targets

Each group also reports its total additional attachments required.

## Overall Requirement Rules

Overall requirement status values:

- `outstanding`: one or more targets require additional evidence
- `none_required`: no targets require additional evidence

The overall summary reports:

- total targets requiring evidence
- total additional attachments required

## Admin Display

The Admin Record Evidence page now renders Evidence Requirements after Evidence Completeness, near Evidence Coverage and Evidence Sufficiency. It is included in the Stage 15A print-safe administrative section body, so browser print/PDF output retains the full requirements audit path.

## Stage 15B and Stage 15C Relationship

Stage 15F reads existing attachment relationships. It does not re-enable temporary upload.

`ADMIN_TEMP_UPLOAD_ENABLED` remains disabled by default. Existing uploaded attachments, when present, are assessed like any other active evidence relationship.

For `Strike-LA-20260710-004`, with one condition attachment and no signal, finding, or record supports:

- condition additional attachments required: 1
- signal additional attachments required: 8
- finding additional attachments required: 2
- record additional attachments required: 2
- overall requirement status: `outstanding`
- targets requiring evidence: 7
- total additional attachments required: 13

## Non-Goals

- No upload functionality
- No public file access
- No public download route
- No schema or manifest changes
- No canonical verification changes
- No public record mutation
- No Stage 11–15 deterministic progression logic changes
