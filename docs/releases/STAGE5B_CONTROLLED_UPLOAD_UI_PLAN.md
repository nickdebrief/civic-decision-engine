# Stage 5B - Controlled Upload UI

This document is a governance and architecture plan for a possible Stage 5B
Controlled Upload UI. It is planning material only. It does not implement upload
UI, public serving, route changes, schema changes, or runtime behavior changes.

## Purpose

Stage 5B would introduce a controlled administrative upload interface for
evidence attachments.

The upload interface is an administrative evidence-management tool, not a public
file-sharing system. It is intended to help an authenticated administrator attach
referenced evidence artifacts to existing civic records while preserving the v12
rules that attachments are additive, independently hashed, and non-canonical.

## Scope

The intended Stage 5B scope is:

- Admin-only upload UI.
- Authenticated admin session.
- Server-side authorization.
- Existing attachment infrastructure reused.
- No public upload capability.

The public verification page remains read-only. Public users, record submitters,
and people with only a record or verification link must not be able to upload
attachments.

## Architecture

```text
Browser
↓
Authenticated Admin Session
↓
Backend
↓
Internal Authorization Validation
↓
Attachment Operation
```

Core architecture rules:

- `CDE_ADMIN_TOKEN` remains server-side only.
- The browser never receives `CDE_ADMIN_TOKEN`.
- Uploads remain additive and non-canonical.
- Attachment metadata does not alter canonical record verification hashes.
- Attachment metadata does not alter canonical serialization.
- Attachment operations do not change record versioning.

## Authentication Model

Stage 5B should use admin session authentication separate from the existing
server-side `CDE_ADMIN_TOKEN` mechanism.

The recommended browser-facing session model includes:

- Admin login.
- Server-issued session cookie.
- `HttpOnly` cookie.
- `Secure` cookie.
- `SameSite=Strict` cookie.
- Session expiration.
- No token exposure in HTML, JavaScript, local storage, session storage, hidden
  form fields, URLs, or API responses.

The browser should authenticate with a session cookie. It should not submit
`CDE_ADMIN_TOKEN` directly.

## Authorization Model

Allowed actor:

- Authenticated administrator with a valid admin session.

Prohibited actors:

- Public users.
- Record submitters.
- Users with only `/records` access.
- Users with only `/verify/{reference}` access.
- Users with only `/verify/{reference}/manifest` access.
- Users with only `/api/verify/{reference}` access.
- Any browser request attempting to provide or receive `CDE_ADMIN_TOKEN`.

Authorization must be checked server-side before any attachment operation.

## Upload Workflow

Proposed lifecycle:

1. Administrator logs in.
2. Backend creates a short-lived admin session.
3. Administrator opens an admin-only attachment page for a record reference.
4. Backend confirms the record exists and resolves the latest record version.
5. UI displays current attachment metadata for the record in admin context.
6. Administrator selects a file and enters metadata.
7. UI requires explicit confirmation of visibility and redaction status.
8. Backend validates session authorization.
9. Backend validates metadata and file constraints.
10. Backend computes SHA-256 from raw attachment bytes.
11. Backend stores immutable attachment bytes.
12. Backend inserts attachment metadata.
13. Backend records an audit event.
14. Public manifest projection continues to show only eligible public metadata.

Canonical record hashes, canonical serialization, and record versioning remain
unchanged throughout the workflow.

## Metadata Requirements

Required metadata:

- File.
- `visibility`.
- `redaction_status`.
- `title`.
- `source_label`.
- `document_date_precision`.

Optional metadata:

- `description`.
- `redaction_note`.
- `document_date`, required only when precision is `day`, `month`, or `year`.

Allowed document date combinations:

- `YYYY-MM-DD` with `day`.
- `YYYY-MM` with `month`.
- `YYYY` with `year`.
- `null` with `unknown`.

## Validation Rules

Stage 5B should preserve existing backend validation and add UI-level
confirmation where appropriate.

Required validation:

- MIME/content-type allowlist.
- Configurable upload size limit.
- Document date validation.
- Visibility validation.
- Redaction status validation.
- Filename sanitization.
- Path traversal protection.
- Latest-record lookup.
- SHA-256 hashing from raw bytes.
- Rejected uploads must not create DB rows.
- Rejected uploads must not leave stored files.

Current conservative MIME allowlist:

- `application/pdf`
- `image/jpeg`
- `image/png`
- `text/plain`

Public visibility should require explicit confirmation before submission.

## Privacy And Redaction Rules

Manifest behavior remains unchanged:

- Public, latest, non-deleted, non-withheld attachment metadata may appear in
  public manifests and read-only public verification pages.
- Private attachments must not appear in public manifests.
- Withheld attachments must not appear in public manifests.
- Deleted attachments must not appear in public manifests.
- `storage_path` must not appear in public output.
- `stored_filename` must not appear in public output.
- Raw filesystem paths must not appear in public output.
- Attachment bytes must not be publicly served.

The UI should clearly distinguish public metadata visibility from public file
download availability. Public serving remains out of scope.

## Mistake Reversal Strategy

Initial Stage 5B should be upload-only if implemented, but routine real evidence
uploads should wait for a correction policy.

Recommended future controls:

- Admin-only metadata correction.
- Admin-only soft-delete.
- Admin-only withheld/redaction update.
- Preservation of immutable attachment bytes.
- Audit event for every correction or state change.

Bytes should remain immutable. Mistakes should be handled through metadata state,
soft deletion, or superseding versions rather than destructive file removal.

## Audit Trail Requirements

Before a browser upload UI is operationally used, an audit trail should be
defined.

Proposed table:

```text
attachment_audit_events
```

Proposed fields:

- `id`
- `attachment_id`
- `reference`
- `record_version`
- `event_type`
- `actor`
- `occurred_at`
- `metadata_json`
- `request_id`
- `ip_hash` or coarse source marker
- `user_agent_hash`

Proposed event types:

- `admin_login_success`
- `admin_login_failed`
- `admin_logout`
- `attachment_uploaded`
- `attachment_visibility_set`
- `attachment_withheld`
- `attachment_soft_deleted`
- `attachment_metadata_corrected`
- `attachment_version_created`

Audit logs must not include:

- `CDE_ADMIN_TOKEN`
- Session secrets
- Raw file bytes
- Raw private narratives
- Raw filesystem paths in public-facing logs or responses

## Failure Modes

Expected failure scenarios:

- Unauthenticated admin page access.
- Expired admin session.
- Invalid session signature.
- Missing file.
- Oversized file.
- Disallowed MIME/content type.
- Invalid document date.
- Invalid visibility.
- Invalid redaction status.
- Missing latest record.
- Storage write failure.
- Database insert failure.
- Duplicate version or filename constraint.
- Path traversal filename.
- Service restart during upload.

Required protections:

- No partial DB row after failed validation.
- No orphaned file after failed persistence.
- No token exposure in errors.
- No public metadata leakage.
- No canonical hash changes.
- No canonical serialization changes.
- No record versioning changes.

## Security Considerations

Stage 5B security considerations include:

- CSRF protection for admin form submissions.
- Session fixation prevention.
- Short session lifetime.
- Strong session signing secret.
- Secure cookie configuration.
- `CDE_ADMIN_TOKEN` exposure prevention.
- Upload abuse and oversized file attempts.
- MIME spoofing and file-type mismatch.
- Metadata leakage through public manifests.
- Accidental public visibility selection.
- Lack of malware scanning.
- Audit trail completeness.
- Login throttling or rate limiting.

The admin upload UI should never be reachable as a public or record-submitter
workflow.

## Suggested Route Design

Admin session routes:

```text
GET  /admin/login
POST /api/admin/session/login
POST /api/admin/session/logout
```

Admin attachment routes:

```text
GET  /admin/records/{reference}/attachments
POST /api/admin/session/records/{reference}/attachments
```

The existing CLI/curl upload route may remain:

```text
POST /api/admin/records/{reference}/attachments
```

The browser UI should not call the existing token-protected route with
`X-CDE-Admin-Token`. Browser upload requests should be authorized through the
admin session.

## Suggested Test Plan

Authentication tests:

- Unauthenticated admin page access is denied.
- Valid login creates a secure, `HttpOnly`, `SameSite=Strict` session.
- Invalid login is denied.
- Expired sessions are denied.
- Browser responses never include `CDE_ADMIN_TOKEN`.

Authorization tests:

- Public users cannot upload.
- Record submitters cannot upload.
- Verification-page users cannot upload.
- Session is required for UI upload route.

Upload tests:

- Valid admin upload succeeds.
- Missing file is rejected.
- Oversized upload is rejected.
- Disallowed MIME type is rejected.
- Invalid document date is rejected.
- Invalid visibility is rejected.
- Invalid redaction status is rejected.
- Path traversal filename is sanitized.
- Rejected uploads create no DB row.
- Rejected uploads create no stored file.

Privacy tests:

- Private uploads remain hidden from public manifests.
- Withheld uploads remain hidden from public manifests.
- Deleted uploads remain hidden from public manifests.
- Public uploads appear as metadata only.
- Public output exposes no `storage_path`.
- Public output exposes no `stored_filename`.
- Public output exposes no raw filesystem paths.
- No public download link is created.

Integrity tests:

- Canonical verification hash remains unchanged.
- Canonical serialization remains unchanged.
- Record version remains unchanged.
- Attachment SHA-256 is computed from raw bytes.

Audit tests:

- Upload event is recorded.
- Failed login event is recorded.
- Metadata correction event is recorded when that feature exists.
- No token or session secret appears in audit output.

## Documentation Requirements

Future implementation should update:

- `docs/releases/README_v12_1.md`
- `docs/attachments_v12.md`
- Admin operations documentation
- Deployment environment variable documentation
- Privacy and redaction guidance
- Audit trail policy
- Mistake correction policy

Documentation should clearly state that Stage 5B is admin-only and does not
create public uploads, downloads, or file serving.

## Explicit Non-Goals

Stage 5B does not include:

- Public uploads
- Public downloads
- Public file serving
- OCR
- PDF extraction
- Attachment search
- Semantic indexing
- Exposure of private files
- Exposure of `CDE_ADMIN_TOKEN`
- Changes to canonical verification hashes
- Changes to canonical serialization
- Changes to record versioning

## Open Governance Questions

Questions to settle before implementation:

- Who is authorized to be an attachment administrator?
- Is one administrator account sufficient?
- Should public visibility require second confirmation or review?
- Should real evidence uploads wait for soft-delete and correction controls?
- What is the retention policy for mistaken uploads?
- What is the audit retention policy?
- Should metadata changes require a reason field?
- Should public metadata publication require review?
- Should malware scanning be required before any real evidence upload?
- Should file signatures be validated beyond submitted MIME type?
- What is the policy for uncertain document dates?
- How are admin credentials rotated?
- How are admin sessions revoked?

## Recommendation

Implement a Stage 5B foundation before implementing the upload UI itself.

Recommended foundation:

- Admin session/auth scaffold.
- Audit-event schema.
- Admin-only attachment listing page.

Defer upload UI implementation until correction and audit policies are
established. This preserves the current v12 posture: attachment capabilities can
grow while canonical records, verification hashes, and public privacy boundaries
remain protected.

## Implementation Status

### Stage 5B Step 2 - Admin Session Scaffold

Status:

```text
Implemented / pending review
```

Scope:

- Admin session scaffold only.

## Implementation Status

### Stage 5B Step 1 - Attachment Audit Events Schema

Status:

Implemented

Scope:

- Attachment audit events schema only.
- No admin session requirement.
- No upload UI.
- No upload route.
- No attachment mutation.

### Stage 5B Step 3 - Admin Attachment Listing Page

Status:

```text
Implemented / pending review
```

Scope:

- Authenticated admin visibility only.
- Read-only attachment listing.
- No upload capability.
- No mutation capability.

### Stage 5B Step 4A - Admin Attachment Management Page Layout

Status:

```text
Implemented / pending review
```

Scope:

- Read-only admin management layout.
- Current attachment visibility preserved.
- Future action areas shown as informational placeholders only.
- No upload or mutation capability.

### Stage 5B Step 4B - Audit Trail Display

Status:

```text
Implemented / pending review
```

Scope:

- Read-only audit trail display.
- Record-scoped audit events only.
- No upload capability.
- No mutation capability.
- No public page or manifest changes.

### Stage 5B Step 4C - Audit Event Writing Helpers

Status:

```text
Implemented / pending review
```

Scope:

- Backend helper functions for writing audit events.
- Metadata sanitization before audit storage.
- No upload capability.
- No mutation routes.
- No public page or manifest changes.

### Stage 5B Step 4D - Synthetic Audit Event Verification

Status:

```text
Implemented / pending review
```

Scope:

- Local verification script only.
- Writes synthetic audit events for testing/admin verification.
- No upload capability.
- No attachment mutation.
- No web route.
- No public page or manifest changes.

### Stage 5B Step 5C - Metadata Correction Foundation

Status:

```text
Implemented / pending review
```

Scope:

- Admin-session protected metadata correction backend.
- Allowed metadata fields only.
- Immutable attachment fields protected.
- Audit event written for corrections.
- No browser form yet.
- No upload/delete/restore/withhold/publish/download capability.
- No canonical verification changes.

### Stage 5B Step 5D - Withhold / Soft-delete / Restore Foundation

Status:

```text
Implemented / pending review
```

Scope:

- Admin-session protected lifecycle backend routes.
- Withhold, restore, and soft-delete state changes.
- Audit event written for each lifecycle action.
- File bytes remain immutable.
- No browser controls yet.
- No upload/download capability.
- No canonical verification changes.

### Stage 5B Step 2 - Admin Session Scaffold

Status:

Implemented

Scope:

- Admin session scaffold only.
- No upload UI.
- No upload route.
- No attachment mutation.
