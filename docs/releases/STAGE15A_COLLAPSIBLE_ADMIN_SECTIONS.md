# Stage 15A — Collapsible Administrative Sections

Status:
Implemented / pending review

Purpose:
Stage 15A improves navigation of the Admin Record Evidence page by grouping
the deterministic administrative reasoning chain into collapsible sections.
This is a UI-only enhancement.

Route updated:

- `GET /admin/records/{reference}/evidence`

Web UI grouping:

- Evidence Coverage
- Administrative Workflow
- Outcome Analysis — Stages 11A-11F
- Resolution Analysis — Stages 12A-12F
- Closure Analysis — Stages 13A-13F
- Archive Analysis — Stages 14A-14F
- Supporting Evidence

Default state:

- Evidence Coverage: open
- Administrative Workflow: collapsed
- Outcome Analysis: collapsed
- Resolution Analysis: collapsed
- Closure Analysis: collapsed
- Archive Analysis: open
- Supporting Evidence: collapsed

PDF/print preservation:
Print CSS forces closed `details` content to render as visible block content so
PDF/export output continues to include the complete deterministic audit trail.
Printed output does not depend on the user's browser expansion state.

Relationship to Stage 12-14 growth:
Stages 12, 13, and 14 added the full Resolution, Closure, and Archive chains.
Stage 15A preserves those chains in raw HTML and print output while making the
web page easier to scan.

No logic changes:

- No classification helper changes
- No evidence logic changes
- No workflow logic changes
- No implementation logic changes
- No outcome logic changes
- No resolution logic changes
- No closure logic changes
- No archive logic changes
- No schema changes
- No manifest changes
- No canonical verification changes
- No upload or download changes
- No public route changes

Verification:
Pending review.
