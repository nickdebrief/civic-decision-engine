# Stage 7F — Evidence Sufficiency

Status:
Implemented / pending review

## Purpose

Stage 7F extends the read-only Admin Record Evidence view from evidence-gap
reporting to deterministic evidence sufficiency classification.

It answers:

How sufficient is the current support?

## Route Updated

- `GET /admin/records/{reference}/evidence`

## Deterministic Classification

Sufficiency is classified from existing supporting attachment and relationship
counts only.

| Classification | Rule |
| --- | --- |
| Unsupported | 0 supporting attachments and 0 supporting relationships |
| Minimal | 1 supporting attachment and 1 supporting relationship |
| Corroborated | 2 or more unique supporting attachments |
| Reinforced | 1 supporting attachment and 2 or more supporting relationships |

Precedence:

1. Unsupported
2. Corroborated
3. Reinforced
4. Minimal

If support exists but does not match a more specific class, the view falls back
to `Minimal`.

## Scope

- Read-only admin UI only.
- No attachment upload or download.
- No public evidence pages.
- No relationship editing.
- No file access.
- No schema changes.
- No manifest behavior changes.
- No canonical verification changes.

## Test Commands

- `python3 -m unittest tests.test_admin_session`
- `python3 -m unittest tests.test_paste_json_analysis_flow`
- `python3 -m unittest discover -s tests`

Result:
Passed.
