# Stage 16A — Evidence Standards

Status: Implemented / pending review

## Purpose

Stage 16A adds a read-only Evidence Standards layer to the Admin Record Evidence view. It makes the deterministic standard behind evidence sufficiency, completeness, and requirements visible and auditable.

## Relationship to Stage 15D Evidence Sufficiency

Stage 15D classifies target sufficiency from active `supports` relationships. Stage 16A displays the standard used for those classifications:

- `Unsupported`: 0 active supporting attachments
- `Partial`: 1 active supporting attachment
- `Sufficient`: 2 active supporting attachments
- `Strong`: 3 or more active supporting attachments

## Relationship to Stage 15E Evidence Completeness

Stage 15E treats a target as complete only when the target reaches `Sufficient` or `Strong`.

Stage 16A displays that completion threshold as:

- complete target: sufficient or strong
- incomplete target: unsupported or partial

## Relationship to Stage 15F Evidence Requirements

Stage 15F calculates additional evidence needed to reach the sufficient threshold. Stage 16A displays that requirement basis:

- unsupported target: 2 additional supporting attachments required
- partial target: 1 additional supporting attachment required
- sufficient target: 0 additional supporting attachments required
- strong target: 0 additional supporting attachments required

## Deterministic Standard

The standard is hardcoded in the admin evidence assessment layer as the current deterministic standard. It is not user-configurable.

The Admin Record Evidence view displays:

- Standard Type: Current deterministic standard
- Minimum for Partial: 1 active supporting attachment
- Minimum for Sufficient: 2 active supporting attachments
- Minimum for Strong: 3 active supporting attachments
- Completion Threshold: sufficient or strong
- Requirement Basis: additional attachments required to reach sufficient
- Relationship Scope: active supports relationships only

## Admin Display

Evidence Standards appears after Evidence Requirements inside the Evidence Governance block:

1. Evidence Coverage
2. Evidence Sufficiency
3. Evidence Completeness
4. Evidence Requirements
5. Evidence Standards

The section is included in the Stage 15A print-safe administrative section body, so browser print/PDF output retains the full standards audit path even when web sections are collapsed.

## Stage 15B and Stage 15C Relationship

Stage 16A reads no uploaded content and creates no attachment records. It does not re-enable temporary upload.

`ADMIN_TEMP_UPLOAD_ENABLED` remains disabled by default. Existing attachment relationships are assessed by earlier evidence layers and the standards layer only displays the standard used for that assessment.

## Example

For `Strike-LA-20260710-004`, one active support for `Escalation Without Response` means:

- the target is `Partial`
- the target is incomplete
- 1 additional supporting attachment is required to reach sufficient

Targets with 0 active supports require 2 additional supporting attachments. This explains the Stage 15F total of 13 additional attachments required for the seven-target test case.

## Non-Goals

- No upload functionality
- No public file access
- No public download route
- No schema or manifest changes
- No canonical verification changes
- No public record mutation
- No Stage 11–15 deterministic progression logic changes
