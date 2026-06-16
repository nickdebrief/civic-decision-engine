# Stage 15D — Evidence Sufficiency

Status: Implemented / pending review

## Purpose

Stage 15D adds a deterministic evidence sufficiency layer to the Admin Record Evidence view. It distinguishes evidence that is merely present from evidence that has enough active support relationships to meet a sufficiency threshold.

## Scope

- Admin-only evidence assessment
- Read-only display
- Existing attachment relationships only
- No public file access
- No public download route
- No canonical verification hash mutation

## Deterministic Rules

Target-level sufficiency uses active `supports` relationships only:

- `Unsupported`: no active `supports` relationship exists for the target
- `Partial`: one active `supports` relationship exists for the target
- `Sufficient`: two or more active `supports` relationships exist for the target
- `Strong`: three or more active `supports` relationships exist for the target

Group-level sufficiency is derived from the targets in each target group:

- `Unsupported`: no targets in the group are supported
- `Partial`: at least one target is supported, but the group is not sufficient
- `Sufficient`: all targets in the group are at least sufficient
- `Strong`: all targets in the group are strong

Overall sufficiency is derived from required groups:

- `Unsupported`: no active supporting evidence exists
- `Partial`: some supporting evidence exists, but one or more required groups remain below sufficient
- `Sufficient`: all required groups are at least sufficient
- `Strong`: all required groups are strong

## Admin Display

The Admin Record Evidence page now renders an Evidence Sufficiency section near Record Evidence Coverage. It shows:

- Conditions Sufficiency
- Signals Sufficiency
- Findings Sufficiency
- Record Sufficiency
- Overall Sufficiency
- target-level sufficiency details

The section is included in the Stage 15A print-safe administrative section body, so browser print/PDF output retains the full audit trail.

## Stage 15B and Stage 15C Relationship

Stage 15D reads existing attachment metadata and active relationships. It does not re-enable the temporary upload utility.

`ADMIN_TEMP_UPLOAD_ENABLED` remains disabled by default. Existing uploaded attachments, when present, are assessed like any other attachment relationship.

For `Strike-LA-20260710-004`, a single uploaded attachment linked to the `Escalation Without Response` condition produces:

- condition target sufficiency: `Partial`
- conditions group sufficiency: `Partial`
- overall sufficiency: `Partial`
- signal, finding, and record sufficiency: `Unsupported`

## Non-Goals

- No upload functionality
- No public file access
- No public download route
- No schema or manifest changes
- No canonical verification changes
- No public record mutation
- No Stage 11–15 deterministic progression logic changes
