# CDE Stage 80 — Private Original-Source Media

## Contract

Stage 80 introduces the `private_original_source_media` intake subtype for
operator-supplied original audio or video source material. It uses the existing
pending-document storage, records the exact supplied bytes and SHA-256, and
assigns an immutable `original_source_identity` derived from that digest. That
identity identifies this preserved original object; it does not claim authorship,
authenticity, source-platform identity, or describe a future derivative.

The subtype preserves operator-supplied source platform, account, URL,
source-publication date, operator capture date, date precision/uncertainty, and
`complete`, `excerpt`, or `unknown` completeness. Unknown values are stored
explicitly. The existing server intake timestamp remains distinct from both
operator-supplied dates.

Supported initial types are M4A, MP3, WAV, and MP4. MP4 acceptance checks only a
narrow leading `ftyp` container-brand signature; it is not full media validation,
malware scanning, authentication, or proof that the bytes are playable or
complete. The existing 25 MiB intake limit remains in effect.

## Private lifecycle boundary

Private original-source media is forced to `private`, cannot transition to
`published`, is excluded from public document listing and public association
selection, and is rejected by public page, inline player/view, and download
paths even if a malformed sidecar represents it as published. Existing generic
document and audio lifecycles are unchanged.

## Admission prerequisite

This local increment does not authorise admission of irreplaceable media. Before
such material is accepted, a separately verified second encrypted off-volume
copy with matching hash and receipt is required. Stage 79.1 and held analytics
and recovery candidates remain outside this change.
