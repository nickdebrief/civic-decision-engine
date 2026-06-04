# Civic Decision Engine v12.1

## Stage 5A - Read-Only Attachment Management

Stage 5A makes v12 attachment metadata visible on public verification pages
without adding upload, edit, delete, download, or public file-serving behavior.

## Purpose

The purpose of Stage 5A is to let readers see which public evidence artifacts
are associated with a civic record while preserving the existing v12 attachment
privacy model and canonical verification behavior.

Attachments remain referenced evidence artifacts. Attachment hashes are
independent of canonical record hashes. Attachments do not alter the canonical
record verification hash.

## Scope

The public verification page displays attachment metadata already exposed by the
record manifest at:

```text
/verify/{reference}/manifest
```

No new public attachment route is introduced.

## Displayed Metadata

For each public manifest attachment, the verification page displays:

- Title
- Description
- Source label
- Filename
- Content type
- File size
- SHA-256 hash
- Visibility
- Redaction status
- Document date
- Document date precision
- Uploaded at
- Download status

When `download_url` is `null`, the page displays:

```text
Download not available in v12.1
```

If no public attachments are listed for the record, the page displays:

```text
No public attachments are listed for this record.
```

## Privacy Boundaries

The read-only attachment panel displays public manifest attachments only.

It does not expose:

- Private attachments
- Withheld attachments
- Deleted attachments
- `storage_path`
- `stored_filename`
- Raw filesystem paths
- Private file metadata not already present in the public manifest

## Explicit Non-Goals

Stage 5A does not implement:

- Upload UI
- Edit UI
- Delete UI
- Replace UI
- Redaction UI
- Restore UI
- Download buttons
- Public attachment downloads
- Public attachment serving
- OCR
- PDF text extraction
- Attachment search
- Semantic indexing of attachment content

## Relationship To v12

Stage 5A is additive to the v12 attachment infrastructure. It uses the existing
manifest-backed attachment metadata and preserves:

- Canonical record verification hashes
- Canonical serialization
- Record versioning
- Manifest recomputation instructions
- Existing record export behavior
