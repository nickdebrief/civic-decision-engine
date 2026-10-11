# CDE Stage 80.1 — Governed Transcription and Speaker Attribution

Stage 80.1 adds private, append-only manual transcript versions for a Stage 80
private original-source media object. Each version binds the intake ID, verified
source bytes SHA-256, and original-source identity. The transcript describes a
recording; it does not replace, authenticate, or verify it.

Utterances use ordered millisecond intervals. Overlap, inaudibility, and
uncertainty are explicit. Speaker labels are `unknown`, `attributed`, or
`identified`; attributed and identified labels require a recorded basis and are
operator claims, not CDE verification. A declared duration is qualified as
operator-supplied; when absent, timestamp validation only establishes a
non-negative interval with end not before start.

Translations are separate, version-linked records with their own language,
method, and authority. Corrections append a new version, retain the earlier
version, require a reason, and reject stale expected-version requests.

There is no automatic transcription, voice identification, remote acquisition,
or public transcript route. Authenticated private endpoints return `no-store`.
All text is structured data and must be escaped by any future HTML renderer.
Schema creation is additive and idempotent. Stage 80's second encrypted
off-volume-copy prerequisite still applies before irreplaceable media is
admitted.
