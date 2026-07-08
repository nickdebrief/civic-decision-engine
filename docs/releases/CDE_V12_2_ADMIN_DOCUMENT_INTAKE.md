# CDE v12.2 — Admin Document Intake

## Purpose

CDE v12.2 adds secure PDF intake to the existing authenticated administrative
interface. It gives administrators a private holding area in which source
documents and descriptive metadata can be collected and inspected before any
future approval decision.

## Workflow

1. An administrator signs in through the existing admin login and session.
2. The administrator opens **Admin Document Intake**.
3. A PDF and its title, institution/source, document date, category,
   description, visibility, notes, and optional reference identifier are
   submitted.
4. CDE verifies the MIME type, `.pdf` extension, PDF signature, and configured
   size limit.
5. CDE computes SHA-256 over the original bytes and stores the PDF with a
   deterministic private filename beside a JSON metadata sidecar.
6. The upload remains `pending` and a metadata preview is displayed.

The preview includes the original filename, byte size, SHA-256 digest,
metadata, proposed private storage location, and pending state. It also states:
"This upload has not created or modified any public record."

## Storage Model

Pending documents are stored beneath `CDE_DOCUMENT_INTAKE_ROOT`, defaulting to
`/data/attachments/intake/pending`. Each SHA-256 identifier receives a private
directory containing the PDF and a stable, sorted JSON metadata sidecar.
Directories use owner-only permissions where supported, and files use
owner-read/write permissions.

The intake store is independent of `records`, `record_attachments`, attachment
relationships, public manifests, and canonical serialization. No migration or
schema change is introduced.

## Security Model

- Every intake page and endpoint requires the existing signed admin session.
- No second login, token, or administration system is introduced.
- Unauthenticated requests receive an authorization error.
- Only PDF uploads are accepted, with MIME, extension, signature, and size
  checks.
- Original filenames are retained as metadata after path components are
  removed.
- Intake files have no public serving or download route.
- Proposed private paths are visible only in authenticated admin previews.

## Pending Behaviour

All uploads have status `pending`. CDE v12.2 provides no approval, publication,
record-creation, evidence-linking, or attachment-activation operation. A
pending document cannot affect a public record, public attachment manifest,
classification, threshold, or evidence relationship.

## Limitations

CDE v12.2 does not perform OCR, text extraction, malware analysis, evidence
validation, content classification, publication, or approval. It does not
determine truth or relevance and does not infer a target public record.
Duplicate document bytes are rejected within the pending store rather than
silently overwritten.

## Testing Summary

Tests cover existing-session authentication, unauthenticated denial, valid PDF
acceptance, invalid type/signature/extension rejection, file-size enforcement,
filename safety, SHA-256 generation, metadata sidecar persistence, pending
status, authenticated preview rendering, absence of public file serving, and
database/public-record immutability. Existing admin and full regression suites
remain part of release validation.

## Preserved Behaviour

This stage changes no CREF methodology, public API contract, public record
lifecycle, verification hash behaviour, attachment hash behaviour, evidence
relationship, classification rule, threshold, upload/download publication
behaviour, or canonical serialization. It extends the existing administrative
interface only.
