# Stage 4 Attachment Activation Checklist

This document prepares the first controlled synthetic attachment activation test
for Civic Decision Engine v12. It is an operational checklist only. It does not
enable uploads, add public serving, or change application behavior.

## Operational Readiness Status

- Architecture complete.
- Privacy hardening complete.
- Synthetic activation pending.
- Real evidence uploads not yet approved.

## Activation Prerequisites

- Stage 1 attachment schema and storage support is deployed.
- Stage 2 admin upload infrastructure is deployed.
- Stage 3 manifest expansion is deployed.
- Stage 3A document date metadata is deployed.
- Stage 3B privacy hardening is deployed.
- Full test suite passes locally and in the deployment workflow.
- Public verification routes are operational.
- Record manifests are operational.
- No public attachment serving route exists.
- No attachment search exists.
- No OCR or PDF text extraction exists.
- `CDE_ADMIN_TOKEN` remains unset until the activation test begins.

## Railway Environment Variables

Set these only when beginning the controlled synthetic activation test:

```text
CDE_ADMIN_TOKEN=<long-random-secret>
CDE_ATTACHMENT_MAX_BYTES=10485760
```

`CDE_ADMIN_TOKEN` must be a long random value and must not be logged, committed,
shared in chat, or included in screenshots.

`CDE_ATTACHMENT_MAX_BYTES` is optional in code, but setting it explicitly keeps
the operational policy visible. The suggested initial value is 10 MB.

After setting or unsetting either variable, restart or redeploy the Railway
service before testing.

## Synthetic Test Record Strategy

Use only synthetic, non-sensitive records and attachments during Stage 4.

Recommended reference:

```text
Strike-OT-20260602-ATTACH-TEST
```

The record should be clearly identifiable as an operational test record. It
should not contain real personal information, real evidence, private narrative
material, or live case data.

Before uploading an attachment, capture the record verification hash:

```bash
curl -s \
  "https://civic-decision-engine-production.up.railway.app/api/verify/Strike-OT-20260602-ATTACH-TEST" \
  | jq '.verification_hash'
```

## Synthetic Attachment Examples

Private day-precision text artifact:

```text
filename: synthetic-notice.txt
content_type: text/plain
visibility: private
redaction_status: none
document_date: 2026-06-02
document_date_precision: day
```

Public month-precision PDF metadata test:

```text
filename: synthetic-letter.pdf
content_type: application/pdf
visibility: public
redaction_status: none
document_date: 2026-06
document_date_precision: month
```

Private unknown-date artifact:

```text
filename: synthetic-undated-note.txt
content_type: text/plain
visibility: private
redaction_status: none
document_date: null
document_date_precision: unknown
```

## Reusable Testing Commands

### Upload Curl Examples

Private text upload:

```bash
curl -i -X POST \
  "https://civic-decision-engine-production.up.railway.app/api/admin/records/Strike-OT-20260602-ATTACH-TEST/attachments" \
  -H "X-CDE-Admin-Token: $CDE_ADMIN_TOKEN" \
  -F "file=@synthetic-notice.txt;type=text/plain" \
  -F "visibility=private" \
  -F "redaction_status=none" \
  -F "title=Synthetic notice" \
  -F "description=Operational upload test artifact" \
  -F "source_label=Stage 4 test" \
  -F "document_date=2026-06-02" \
  -F "document_date_precision=day"
```

Public manifest-visible test upload:

```bash
curl -i -X POST \
  "https://civic-decision-engine-production.up.railway.app/api/admin/records/Strike-OT-20260602-ATTACH-TEST/attachments" \
  -H "X-CDE-Admin-Token: $CDE_ADMIN_TOKEN" \
  -F "file=@synthetic-letter.pdf;type=application/pdf" \
  -F "visibility=public" \
  -F "redaction_status=none" \
  -F "title=Synthetic public attachment" \
  -F "description=Public manifest metadata test only" \
  -F "source_label=Stage 4 test" \
  -F "document_date=2026-06" \
  -F "document_date_precision=month"
```

Unknown-date private upload:

```bash
curl -i -X POST \
  "https://civic-decision-engine-production.up.railway.app/api/admin/records/Strike-OT-20260602-ATTACH-TEST/attachments" \
  -H "X-CDE-Admin-Token: $CDE_ADMIN_TOKEN" \
  -F "file=@synthetic-undated-note.txt;type=text/plain" \
  -F "visibility=private" \
  -F "redaction_status=none" \
  -F "title=Synthetic undated note" \
  -F "source_label=Stage 4 test" \
  -F "document_date_precision=unknown"
```

### Expected Success Response

Expected status: `201 Created`.

Expected response shape:

```json
{
  "attachment": {
    "attachment_id": 1,
    "reference": "Strike-OT-20260602-ATTACH-TEST",
    "record_version": 1,
    "attachment_version": 1,
    "filename": "synthetic-notice.txt",
    "content_type": "text/plain",
    "file_size_bytes": 123,
    "sha256_hash": "...",
    "visibility": "private",
    "redaction_status": "none",
    "document_date": "2026-06-02",
    "document_date_precision": "day",
    "uploaded_at": "..."
  }
}
```

The response must not include:

```text
storage_path
stored_filename
/data/attachments
raw filesystem paths
CDE_ADMIN_TOKEN
```

### Expected Failure Responses

Missing admin token:

```bash
curl -i -X POST \
  "https://civic-decision-engine-production.up.railway.app/api/admin/records/Strike-OT-20260602-ATTACH-TEST/attachments" \
  -F "file=@synthetic-notice.txt;type=text/plain"
```

Expected: `401`.

Invalid admin token:

```bash
curl -i -X POST \
  "https://civic-decision-engine-production.up.railway.app/api/admin/records/Strike-OT-20260602-ATTACH-TEST/attachments" \
  -H "X-CDE-Admin-Token: wrong-token" \
  -F "file=@synthetic-notice.txt;type=text/plain"
```

Expected: `403`. The response must not echo either the configured token or the
submitted token.

Uploads disabled:

```bash
curl -i -X POST \
  "https://civic-decision-engine-production.up.railway.app/api/admin/records/Strike-OT-20260602-ATTACH-TEST/attachments" \
  -H "X-CDE-Admin-Token: any-token" \
  -F "file=@synthetic-notice.txt;type=text/plain"
```

Expected when `CDE_ADMIN_TOKEN` is unset: `503`.

Disallowed MIME type:

```bash
curl -i -X POST \
  "https://civic-decision-engine-production.up.railway.app/api/admin/records/Strike-OT-20260602-ATTACH-TEST/attachments" \
  -H "X-CDE-Admin-Token: $CDE_ADMIN_TOKEN" \
  -F "file=@synthetic.html;type=text/html"
```

Expected: `415`.

Oversized upload:

```bash
curl -i -X POST \
  "https://civic-decision-engine-production.up.railway.app/api/admin/records/Strike-OT-20260602-ATTACH-TEST/attachments" \
  -H "X-CDE-Admin-Token: $CDE_ADMIN_TOKEN" \
  -F "file=@oversized.pdf;type=application/pdf"
```

Expected: `413`.

Missing record:

```bash
curl -i -X POST \
  "https://civic-decision-engine-production.up.railway.app/api/admin/records/Strike-OT-20990101-MISSING/attachments" \
  -H "X-CDE-Admin-Token: $CDE_ADMIN_TOKEN" \
  -F "file=@synthetic-notice.txt;type=text/plain"
```

Expected: `404`.

## Manifest Verification Workflow

Fetch the record manifest:

```bash
curl -s \
  "https://civic-decision-engine-production.up.railway.app/verify/Strike-OT-20260602-ATTACH-TEST/manifest" \
  | jq .
```

Expected:

- `attachments` exists.
- Private attachments are absent.
- Public, latest, non-deleted, non-withheld attachments are present.
- `download_url` is `null`.
- `attachment_integrity_note.canonical_record_hash_unchanged` is `true`.
- `attachment_integrity_note.attachment_hashes_independent` is `true`.

The manifest must not contain:

```text
storage_path
stored_filename
/data/attachments
raw filesystem paths
CDE_ADMIN_TOKEN
source_narrative
report_json
raw input
semantic fields
```

## Canonical Hash Stability Verification

Capture the hash before upload:

```bash
BEFORE_HASH=$(curl -s \
  "https://civic-decision-engine-production.up.railway.app/api/verify/Strike-OT-20260602-ATTACH-TEST" \
  | jq -r '.verification_hash')
```

Capture the hash after upload:

```bash
AFTER_HASH=$(curl -s \
  "https://civic-decision-engine-production.up.railway.app/api/verify/Strike-OT-20260602-ATTACH-TEST" \
  | jq -r '.verification_hash')
```

Compare:

```bash
test "$BEFORE_HASH" = "$AFTER_HASH" && echo "canonical hash unchanged"
```

The canonical verification hash must remain unchanged after attachment upload.

## Privacy Verification Checklist

- Missing token cannot upload.
- Invalid token cannot upload.
- Disabled admin route returns `503` when `CDE_ADMIN_TOKEN` is unset.
- Error responses do not contain token values.
- Private attachments do not appear in public manifests.
- Withheld attachments do not appear in public manifests.
- Deleted attachments do not appear in public manifests.
- Manifest does not expose `storage_path`.
- Manifest does not expose `stored_filename`.
- Manifest does not expose raw filesystem paths.
- Upload response does not expose `storage_path`.
- Upload response does not expose `stored_filename`.
- Attachment content is not publicly downloadable.
- No public upload route exists.
- No `/api/records/search` route exists.
- No semantic indexing of attachments exists.
- No OCR or PDF text extraction exists.

## Route Absence Verification Commands

Guessed public attachment retrieval URLs:

```bash
curl -i "https://civic-decision-engine-production.up.railway.app/attachments/1"
curl -i "https://civic-decision-engine-production.up.railway.app/api/attachments/1"
curl -i "https://civic-decision-engine-production.up.railway.app/records/Strike-OT-20260602-ATTACH-TEST/attachments/1"
```

Expected: `404` or route-not-found behavior.

Attachment search route:

```bash
curl -i "https://civic-decision-engine-production.up.railway.app/api/records/search"
```

Expected: `404` or route-not-found behavior.

## Rollback Procedure

1. Unset `CDE_ADMIN_TOKEN` in Railway.
2. Restart or redeploy the service.
3. Confirm upload route is disabled:

```bash
curl -i -X POST \
  "https://civic-decision-engine-production.up.railway.app/api/admin/records/Strike-OT-20260602-ATTACH-TEST/attachments" \
  -H "X-CDE-Admin-Token: old-token" \
  -F "file=@synthetic-notice.txt;type=text/plain"
```

Expected: `503`.

Existing synthetic attachment metadata may remain in the archive database, but no
new admin uploads should be possible while `CDE_ADMIN_TOKEN` is unset.

## Operational Risks

- The admin upload route becomes reachable to anyone with the token.
- Token exposure through shell history, screenshots, logs, or shared terminals
  would compromise the admin upload route.
- MIME validation is based on submitted content type, not full file inspection.
- Malware scanning is not implemented.
- Public attachment serving is not implemented, so file retrieval cannot yet be
  verified through a public CDE URL.
- Persistent storage depends on Railway volume configuration for
  `/data/attachments`.
- Real evidence uploads carry privacy and retention obligations that are not part
  of the synthetic activation test.

## Success Criteria

- Synthetic upload succeeds with a valid admin token.
- Missing and invalid tokens fail.
- Oversized and disallowed MIME uploads fail.
- Rejected uploads do not create public exposure.
- Manifest metadata appears only for public, latest, non-deleted, non-withheld
  attachments.
- Private attachment metadata remains absent from public manifests.
- Canonical verification hash remains unchanged.
- No public attachment retrieval route exists.
- No attachment search route exists.
- Rollback disables admin uploads.

## Stage 4 Exit Criteria

- Synthetic upload successful.
- Manifest metadata verified.
- Canonical hash unchanged.
- No public attachment retrieval.
- Rollback tested.
- Admin token handling verified.

Real evidence uploads are not approved until all Stage 4 exit criteria are met
and separately reviewed.
