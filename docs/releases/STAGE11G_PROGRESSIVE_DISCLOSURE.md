# Stage 11G — Progressive Disclosure

Status: Implemented / pending review

## Purpose

Stage 11G improves readability of the read-only Admin Record Evidence view
before Stage 12 begins. Stages 7 through 11 added a full deterministic
administrative evidence path, and the page now needs clearer navigation without
removing any audit detail.

## Route Updated

`GET /admin/records/{reference}/evidence`

## Why Progressive Disclosure Was Added

The Admin Record Evidence view preserves a complete deterministic path from
record evidence coverage through outcome target classification. Progressive
disclosure keeps current-state material visible while allowing longer reasoning
sections to be expanded when needed.

## Visible Current-State Sections

The following sections remain visible by default:

- Record summary
- Record Evidence Coverage
- Evidence Gap Summary
- Outstanding Gaps
- Stage 9E — Administrative Status Summary
- Stage 10C — Effective State
- Stage 11A — Outcome Classification
- Stage 11E — Outcome Readiness
- Stage 11F — Outcome Target

## Grouping Strategy

Longer detail sections are grouped with native HTML `<details>` and
`<summary>` elements:

- Evidence Assessment
  - Stage 7F — Evidence Sufficiency
  - Stage 7G — Evidence Readiness
- Administrative Workflow
  - Stage 8A — Administrative Action
  - Stage 8B — Action Rationale
  - Stage 8C — Completion Requirements
  - Stage 8D — Workflow State
  - Stage 8E — Transition Conditions
- Review Status
  - Stage 9A — Administrative Disposition
  - Stage 9B — Disposition Basis
  - Stage 9C — Review Eligibility
  - Stage 9D — Review Preconditions
- Implementation Path
  - Stage 10A — Implementation Action
  - Stage 10B — Implementation Basis
- Outcome Detail
  - Stage 11B — Outcome Basis
  - Stage 11C — Outcome Preconditions
  - Stage 11D — Outcome Summary
- Supporting Evidence
  - Conditions
  - Signals
  - Findings
  - Record

## Print Behavior

Print styling expands collapsed `<details>` content so browser print/PDF output
continues to include the full administrative path. The v12 administrative
watermark and print-safe presentation remain in place.

## Preservation Of Audit Path

Stage 11G changes presentation only. All deterministic Stage 7 through Stage
11F content remains present in the HTML and available for review.

## Verification Boundaries

Stage 11G introduces no mutation controls, workflow mutation, implementation
mutation, outcome mutation, schema changes, manifest changes, canonical
verification changes, public route changes, upload behavior changes, download
behavior changes, or file access changes.

## Test Result

Commands:

```bash
python3 -m unittest tests.test_admin_session
python3 -m unittest discover -s tests
```

Result: PASS.
