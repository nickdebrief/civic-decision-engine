# Governed Audio Artefact Support

## Purpose

This stage extends the existing governed Document Intake and publication
workflow to support original audio artefacts as first-class published files.
The immediate acceptance case is `AUD-20190719-WA0012.m4a`.

Supported audio formats:

- M4A;
- MP3;
- WAV.

Existing PDF, JPEG, and PNG support is preserved.

## Governance Boundary

An audio recording is treated as an independently preserved public artefact. It
retains its own original bytes, SHA-256 digest, original filename, detected
format, detected MIME type, metadata, lifecycle history, and publication
provenance.

Audio support does not:

- convert audio into PDF, image, transcript, or another surrogate format;
- transcode, compress, re-encode, crop, or otherwise modify bytes;
- perform speech recognition or AI analysis;
- infer findings, Conditions, Signals, record claims, or evidential truth;
- automatically create Record-Document Associations;
- automatically create canonical records;
- alter linked canonical records or record verification hashes.

## Validation and Storage

Audio uploads use the same intake route and validation boundary as PDF, JPEG,
and PNG uploads. The server validates the filename extension and detects the
file type from uploaded bytes before deriving the stored MIME type.

Accepted mappings:

- `.m4a` -> M4A, `audio/mp4`;
- `.mp3` -> MP3, `audio/mpeg`;
- `.wav` -> WAV, `audio/wav`.

Extension/type mismatches are rejected. Browser-supplied MIME values do not
override server detection. Files continue to use safe generated storage names
based on the existing SHA-256-addressed intake model.

## Administration Workflow

Administrators upload audio through the existing Admin Document Intake form,
which now lists:

`Supported formats: PDF, JPEG, PNG, M4A, MP3, and WAV.`

Audio artefacts retain all existing metadata fields:

- title;
- institution/source;
- document date;
- category;
- Keywords;
- description;
- internal notes;
- reference identifier;
- visibility;
- original filename;
- file size;
- SHA-256;
- detected format and MIME type.

Audio artefacts pass through the existing lifecycle:

Pending Intake -> Under Review -> Approved -> Published

with the same authenticated actor attribution, transition notes, correction
workflow, audit trail, and private/public visibility boundaries as existing
files.

## Public Document Library

Published audio artefacts appear in the existing Public Document Library. They
are searchable through the existing `build_document_search_text()` helper by
title, institution/source, category, Keywords, description, reference
identifier, original filename, and any available extracted-content fields.

No transcript is required for search or publication.

## Public Playback and Download

Published audio detail pages display governed metadata, Publication Provenance,
Publication Pathway, SHA-256, and an HTML5 audio player:

```html
<audio controls preload="metadata">
  <source src="/documents/{document_id}/view" type="audio/mp4">
</audio>
```

The player uses the original published file. No preview, derivative, waveform,
or transcoded file is created. The public page also retains an original-file
download action.

The inline `/documents/{document_id}/view` route remains Published-only and now
serves images and audio with `Content-Disposition: inline`. The download route
continues to return the exact original bytes and uses attachment behaviour for
image and audio artefacts.

## Record-Document Associations

Published audio artefacts remain ordinary eligible objects for the existing
Record-Document Association workflow. The association object model, controlled
relationship types, public/admin notes, visibility, history, and disclaimers are
unchanged.

Audio associations render through the same public record, public document,
public association, and administrative association views as existing published
files. The displayed document format identifies the audio format, such as M4A.

## Preserved Behaviour

This stage does not change:

- document lifecycle states or transitions;
- approval/publication separation;
- document SHA-256 semantics;
- original-byte preservation;
- Public Document Library routes, search, filters, or ordering;
- Public Record Index behaviour;
- canonical record verification hashes;
- record evidence, Conditions, Signals, or findings;
- association storage or lifecycle;
- authentication and signed-session behaviour;
- public/private visibility boundaries.

## Validation

Focused tests cover M4A, MP3, and WAV intake; unsupported and mismatched media
rejection; PDF/JPEG/PNG regression; original-byte and SHA-256 preservation;
audio lifecycle publication; public playback and download headers; metadata and
Keyword search; private-audio public denial; and Record-Document Association
selection and creation with an audio artefact.
