# Stage 15C — Gate Temporary Admin Attachment Upload

Status: Implemented / pending review

## Purpose

Stage 15C gates the Stage 15B temporary admin attachment upload utility behind an explicit environment flag.

## Environment Flag

`ADMIN_TEMP_UPLOAD_ENABLED=false`

The default is disabled.

## Disabled Behaviour

When `ADMIN_TEMP_UPLOAD_ENABLED` is unset or false:

- the temporary upload form is not rendered
- the temporary upload POST route returns `404`
- existing attachment listings still render
- existing Admin Record Evidence pages still render
- existing attachments, metadata, and relationships remain available

## Enabled Behaviour

When `ADMIN_TEMP_UPLOAD_ENABLED=true`:

- the Stage 15B temporary upload form renders on the admin attachment management page
- the Stage 15B temporary upload POST route stores attachment metadata
- uploaded attachment bytes receive an independent SHA-256 hash
- a `supports` relationship is created for the supplied record target

## Non-Goals

- No public download route
- No public file access
- No schema changes
- No canonical verification hash changes
- No Stage 11–15 deterministic logic changes
- No workflow, implementation, outcome, resolution, closure, archive, or public route mutation

## Tests

Run:

`python3 -m unittest tests.test_admin_session`

`python3 -m unittest discover -s tests`
