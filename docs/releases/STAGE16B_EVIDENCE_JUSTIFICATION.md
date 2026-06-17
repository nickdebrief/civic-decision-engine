# Stage 16B — Evidence Justification

Status: Implemented / pending review

## Purpose

Stage 16B adds a read-only Evidence Justification layer to the Admin Record Evidence view. It explains why each record target received its current sufficiency, completeness, and evidence requirement result.

## Relationship to Stage 15D Evidence Sufficiency

Stage 16B uses the Stage 15D sufficiency thresholds:

- `Unsupported`: 0 active supports
- `Partial`: 1 active support
- `Sufficient`: 2 active supports
- `Strong`: 3 or more active supports

Each target justification displays the active support count and the resulting sufficiency classification.

## Relationship to Stage 15E Evidence Completeness

Stage 16B explains target completeness using the Stage 15E rule:

- complete: sufficiency is `Sufficient` or `Strong`
- incomplete: sufficiency is `Unsupported` or `Partial`

## Relationship to Stage 15F Evidence Requirements

Stage 16B displays the additional evidence required under the Stage 15F rules:

- unsupported target: 2 additional supporting attachments required
- partial target: 1 additional supporting attachment required
- sufficient target: 0 additional supporting attachments required
- strong target: 0 additional supporting attachments required

## Relationship to Stage 16A Evidence Standards

Stage 16B includes the standard applied for each target, using the current deterministic standard displayed in Stage 16A.

## Deterministic Justification Rules

For each target, the Admin Record Evidence view displays:

- target label
- active supports count
- sufficiency result
- completeness result
- additional attachments required
- standard applied
- deterministic justification sentence

The justification sentence is generated only from counts, sufficiency, completeness, requirements, and standards. No AI-generated text or user-entered explanation is used.

## Active Supports Scope

Only active `supports` relationships are counted. Inactive, removed, deleted, or non-`supports` relationships do not determine evidence justification.

## Admin Display

Evidence Justification appears after Evidence Standards inside the Evidence Governance block:

1. Evidence Coverage
2. Evidence Sufficiency
3. Evidence Completeness
4. Evidence Requirements
5. Evidence Standards
6. Evidence Justification

The section is included in the Stage 15A print-safe administrative section body, so browser print/PDF output retains the full justification audit path even when web sections are collapsed.

## Example

For `Strike-LA-20260710-004`, one active support for `Escalation Without Response` produces:

- Active supports: 1
- Sufficiency: Partial
- Completeness: Incomplete
- Additional attachments required: 1
- Standard applied: Partial = 1 active support; Sufficient = 2 active supports

The deterministic justification explains that the target is Partial because it has one active support, remains Incomplete because completion requires Sufficient or Strong sufficiency, and requires one additional supporting attachment to reach Sufficient.

## Non-Goals

- No upload functionality
- No public file access
- No public download route
- No schema or manifest changes
- No canonical verification changes
- No public record mutation
- No Stage 11–15 deterministic progression logic changes
