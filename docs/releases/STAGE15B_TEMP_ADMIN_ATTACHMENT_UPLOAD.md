# Stage 15B — Temporary Admin Attachment Upload

Status: Implemented / pending review

## Purpose

Stage 15B adds a temporary admin-only attachment upload utility for evidence verification. It allows administrators to create an attachment and link it to an existing record target without manual database insertion.

## Scope

- Admin attachment management page only
- Temporary/test-support utility
- Existing attachment storage and metadata tables
- Existing SHA-256 attachment hashing
- Existing evidence relationship model
- No public file access
- No public attachment browsing
- No public download route
- No canonical verification hash mutation

## How To Use

Open:

`/admin/records/Strike-LA-20260710-004/attachments`

Use the temporary upload form with:

- record reference: `Strike-LA-20260710-004`
- target type: `condition`
- target label: `Escalation Without Response`
- attachment title: `Test evidence — escalation without response`
- file upload: any small verification file

The upload stores attachment metadata, computes an independent attachment SHA-256 hash, and creates a `supports` relationship to the supplied record target.

## Expected Verification Result

After upload, the Admin Record Evidence view should show:

- Conditions Supported changes from `0 / 1` to `1 / 1`
- Overall Coverage changes from `Unsupported` to `Partial`

## Non-Goals

- No public download capability
- No public file serving
- No public attachment browsing
- No schema changes
- No canonical verification changes
- No Stage 11–15 deterministic logic changes
- No workflow, implementation, outcome, resolution, closure, or archive mutation

## Hash Boundary

Uploaded attachment bytes produce an attachment SHA-256 hash. That hash remains independent from the canonical public record verification hash. Attachments do not alter canonical record verification hashes.

## Tests

Run:

`python3 -m unittest tests.test_admin_session`

`python3 -m unittest discover -s tests`
