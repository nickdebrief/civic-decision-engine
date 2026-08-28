# CDE Platform Stage 77 — Durable Governed Report Generation

## Status

Implemented · merged · deployed

Sole-administrator qualification amendment: implemented locally · pending
assurance and integration. It is not part of the historical deployed revision.

Stage 77 adds one durable operational queue and one governed-report worker to
the existing one-service, one-replica topology. A job executes an already
approved immutable Stage 75 report specification; it does not approve the
specification, alter its content, select sources, publish a determination or
distribute an artifact.

Stage 75 remains the owner of report identity, versions, lifecycle history,
specifications, artifact records and private artifact authorization. Stage 76
remains the owner of DOCX/HTML/PDF rendering, metadata/action safety and
cross-format equivalence. The Publication Engine remains persistence-free.

Stage 75 may qualify a frozen report version through either the existing
`independent_multi_administrator` pathway or an explicitly configured
`sole_administrator` operating constraint. The latter records creator
confirmation, never independent review, requires all four deliberate gates,
permits only `internal_working`, and binds its immutable qualification identity
and digest into enqueue, worker revalidation and artifact metadata. Its exact
`sole-admin-v1` limitation disclosure is controlled front matter and is
validated across every requested output format. Disabling the deployment mode
blocks new sole-administrator qualifications and enqueue requests; persisted
queued qualifications are not rewritten.

Restore targets are accepted only beneath an existing, real isolated restore
root. Lexical path components are inspected with no-follow metadata before
staging, and descriptor-anchored no-replace promotion is used where supported
by the runtime platform. Symlinked, aliased, traversing, existing or otherwise
ambiguous targets fail closed; restore staging and cleanup never follow links.
The supported deployment contract therefore requires a filesystem with
directory-descriptor and no-follow operations suitable for the running Python
platform. Restore remains an explicit governed operational action and never
overwrites a live path.

## Durable Execution

The queue uses the existing persistent SQLite database with WAL, bounded busy
timeouts, foreign keys and short `BEGIN IMMEDIATE` claim transactions. One
supervised worker uses lease tokens, UTC expiry timestamps, heartbeats and
token-checked completion. Stale workers cannot promote bytes, register
artifacts, complete jobs or override cancellation. Job coordination state and
append-only job events are isolated from Stage 75 artifact ownership.

The authenticated generation POST now enqueues and returns without rendering.
Rendering occurs only in the worker after revalidating the report lifecycle,
version digest and cancellation state. GET, import, listing, diagnostics and
terminal idempotent replay do not render. Retries are bounded and restricted
to explicitly transient infrastructure failures; validation, source, action,
equivalence, authorization and digest failures remain terminal.

### Exceptional diagnostic retry

This compatibility amendment is local-only pending independent assurance and
separate integration/deployment authorization.

The local Stage 77 diagnostic-observability amendment defines a separate,
one-time `diagnostic_retry` action for a terminal renderer failure with the
exact bounded phase and code recognized by the deployed diagnostic protocol.
It is not automatic retry, ordinary infrastructure retry, reapproval, or a
new generation declaration. The original failed job remains immutable; a
successful authorization creates one linked successor with a distinct stable
identity and records append-only report and job authorization events.

Authorization requires an authenticated administrator, a bounded rationale,
the fixed affirmative declaration, unchanged specification and final
qualification identity/digest, internal-only distribution, valid sources and
associations, no artifacts or active job, and a recovery state that permits
worker claims under the authoritative recovery-fencing contract. A completed
recovery epoch with released fencing is eligible; active, failed or otherwise
claim-blocking recovery states remain ineligible.
It moves `validation_failed` directly to `generation_requested` as execution
authorization, never as substantive reapproval. The worker revalidates the
linkage and diagnostic protocol before using the ordinary lease, rendering,
validation, promotion and registration path; it cannot authorize a retry or
create another one. A failed successor remains terminal and retains bounded
diagnostics. Historical failures created before diagnostic propagation are
selected only by the closed `legacy_pre_propagation_diagnostic_contract_v1`
shape and independently bound payload digests. The first terminal projection
defect is preserved under the exact transitional
`current_pre_terminal_projection_fix_diagnostic_contract_v1` pair, whose
payload hashes bind Job 2 without rewriting it. Future terminal events use
the strict `current_diagnostic_contract_v1` projection. Legacy, transitional
and current pairs are disjoint; mixed, partial, unknown and downgraded pairs
fail closed. Historical rows are never rewritten or upgraded.
Production use requires the separately governed Custody Point 4 precondition
described in the recovery runbook.

The runtime supervisor validates durable storage before starting exactly one
Uvicorn child and one worker child, forwards shutdown signals, drains and
reaps both children, and reports only bounded operational markers. The worker
invokes the canonical Stage 75-owned report-schema initializer, then validates
the Stage 75, Stage 77 job and recovery schemas before emitting readiness. It
uses a private readiness channel after real SQLite, job-schema and recovery
state initialization. The supervisor validates that exact token while both
children remain alive and emits the authoritative
`stage77_supervisor_attestation=ready protocol=1 application_child=alive
worker_child=ready` marker. Railway's aggregate display may interleave records
from separate processes, so relative display order is not used as causal
evidence; HTTP smoke checks establish application availability separately. No worker,
queue, public route, report type, external broker, physical-print service or
Stage 73 integration is introduced.

## Boundaries and Limitations

The worker identity is distinct from the requesting or approving actor. A job
cannot approve a report or change a frozen specification. Stage 72 remains the
relationship owner, Stage 73 remains the public determination-publication
boundary, and Stage 74 terminology remains representation rather than finding.
Reports remain internal and authenticated; no public report distribution is
introduced.

Backup and restore of the SQLite database and artifact bytes remain an
application-level operational prerequisite. Railway volume snapshots preserve
storage but do not by themselves prove a coordinated SQLite/artifact recovery
point. The explicit `scripts/manage_stage77_recovery.py` operations therefore
drain and fence the worker, take an SQLite online backup, copy and digest every
valid Stage 75 artifact, write an allow-listed canonical manifest, validate the
complete bundle, and atomically promote it. The recovery-control and event
tables record the maintenance epoch and bounded terminal outcome. Recovery
capture and validation remain schema-repair-free: missing or incompatible
Stage 75 tables fail closed with bounded diagnostics rather than creating
parallel or compatibility tables. Empty authoritative Stage 75 tables are
established only during worker startup through the Stage 75-owned initializer,
before worker readiness.

The recovery root is supplied explicitly for each governed operation. The
intended production value is `/data/cde-recovery-points`, represented by the
`CDE_RECOVERY_ROOT` deployment configuration only when separately approved.

The recovery subsystem also owns an immutable recovery-evidence authority. Its
payload is deterministically recomputed from the preserved recovery manifest
and SQLite bundle. Native capture records it before completion; a separate
authenticated historical reconstruction records evidence for an existing
bundle without creating a capture, restore, export, or custody verification.
Detached archive and receipt claims remain administrator-attested, and later
attestation and authorization bind the persisted evidence identity and digest.
It remains distinct from `RECORDS_DB_PATH` and
`CDE_REPORT_ARTIFACT_ROOT`; this change does not configure production backups
or create a recovery point.

The SQLite backup contains the recovery event bound recorded in the manifest;
the terminal completion event is written only after bundle promotion and is
therefore intentionally outside that backup. A failed capture leaves worker
claims fenced until an explicit governed abort transition releases them.
Foreign-key checks consume the complete violation result, and manifests are
strict canonical JSON with duplicate keys and reordered fields rejected.

Restore accepts only explicitly supplied empty isolated targets. It validates
the manifest, database integrity, schema and engine compatibility, artifact
digests and ownership before promoting restored files. Leased and running jobs
lose their old tokens and enter bounded retry recovery; cancellation requests
become cancelled; succeeded, failed-terminal and cancelled jobs do not
rerender. A worker remains non-claiming while recovery or restore validation is
active and resumes only after `restore_ready`.

Recovery creation and restore are governed operational actions, not startup,
import, GET, listing or diagnostic behavior. A backup is not proof that a
restore succeeded. Restoration is not approval, publication, distribution or
printing. Railway snapshots may later preserve a completed bundle, but Stage
77 remains blocked until this protocol is assured in an isolated backup/restore
verification and the separate operational backup prerequisite is resolved.

## Portable Custody

Railway native volume backups are unavailable on the current plan and are not
treated as application-consistent backups. The supported operational path is
the explicit `export` and `validate-export` commands in
`scripts/manage_stage77_recovery.py`. Export first revalidates a completed
recovery bundle, then creates a deterministic tar transport containing only
the canonical manifest, SQLite online-backup file, registered artifact bytes,
and bounded metadata. It rejects unsafe members, symlinks, traversal,
unknown files, digest mismatches, source mutation, and partial finalization.

The paired canonical custody receipt records the recovery-point identity,
manifest, database and archive digests, artifact count, job and recovery event
bounds, and schema/engine versions. It contains no paths, content, secrets,
environment values, or raw diagnostics. Safe extraction is into a new isolated
destination and is independently validated before restore. The archive is not
encrypted by the application; custody must use an independently verified
encrypted local filesystem. The operational cadence, seven-point retention,
temporary Railway transport-key controls, and first-deployment sequence are
documented in `docs/STAGE77_RECOVERY_CUSTODY_RUNBOOK.md`.

Recovery manifests and receipts use three closed generations: historical
pre-qualification, qualification-aware, and diagnostic-aware
(`stage77.diagnostic_aware.v1`). Selection is deterministic from the archived
database. Diagnostic-bearing databases must bind the selected diagnostic
contract, Stage 75 and Stage 77 evidence identities and payload digests, plus
deterministic diagnostic-evidence and retry-topology count/state digests. Raw
diagnostic payloads remain in SQLite and are not copied into custody metadata.
Older contracts cannot validate diagnostic-bearing databases, and missing,
mixed, partial, reordered, or downgraded evidence fails closed.

Custody Point 4 is the post-failure, pre-diagnostic-retry point. It must use
the diagnostic-aware contract and must be captured, exported, and validated
before the one separately governed linked retry is authorized. A later Custody
Point 5 binds the legacy Job 1 evidence and the transitional or current Job 2
evidence, their four payload hashes, and the single Job 1 to Job 2 retry link.
The transitional contract identifies the projection defect only; any renderer
correction requires separate authorization.

The adapter qualification-schema correction is a local projection-boundary
change only. The complete persisted Stage 75 qualification envelope remains
authoritative for ownership, the frozen specification digest, the four-gate
chain, authorization, recovery evidence, and artifact metadata. After those
checks, Stage 77 constructs a new immutable rendering projection containing
exactly the five Stage 76 adapter fields: `review_mode`,
`disclosure_version`, `disclosure`, `qualification_id`, and
`qualification_digest`. The adapter continues to reject the broader persisted
envelope and unknown fields. This does not rewrite Job 1 or Job 2, change their
diagnostic contracts, authorize another retry, or change rendering acceptance,
lifecycle, recovery, custody, artifact, or public-boundary semantics. Custody
Point 5 preserves the pre-correction state; integration, deployment, a later
post-correction recovery point, and any controlled generation require separate
authorization.

Export and restore require an administrator and never run automatically during
import, startup, GET, listing, diagnostics, or worker startup. Backup creation
is not proof of successful restoration, and restoration is not approval,
publication, distribution, or printing.

The controlled post-correction execution is a separate append-only Stage 77
authorization, not a retry or reapproval. It binds the unchanged report and
qualification evidence, immutable Jobs 1 and 2, the deployed correction
identity, and the completed Point 6 recovery. The archive and receipt digests
are administrator custody attestations because detached encrypted custody is
not application-readable; recovery identity, state, manifest, and database
evidence remain server-validated. Exactly one authorization-bound execution
job may be created, with no `retry_of_job_id`; a failure consumes the
authorization and leaves the report `validation_failed` permanently. Point 7
is permitted only after successful DOCX, HTML, and PDF validation, promotion,
registration, and a final recovery capture. No public route or automatic
execution is created.
### Recovery eligibility and detached custody evidence

Operational readiness is distinct from governed recovery eligibility: an empty
or readiness-only database may be valid to operate, but it cannot produce
governed recovery evidence. `stage77.post_correction_aware.v1` requires exactly
one governed report and exactly one report version owned by that report. Its
pre-authorization state forbids post-correction authorization-linked execution
jobs; it does not require the absence of inherited historical governed jobs in
states where those jobs are part of the applicable diagnostic contract. An
ambiguous or readiness-only database is never reconstructed as recovery
evidence.

Point 6 archive and receipt values are not application-derived: the production
service cannot inspect the detached encrypted custody device. A separate,
authenticated, append-only administrator attestation records those bounded
external-custody claims only after the completed Point 6 recovery evidence is
revalidated. The attestation is immutable, idempotent and distinct from the
one-time post-correction generation authorization; it does not approve,
retry, publish or create a job. Its retry-topology authority is the count and
digest already preserved by the referenced governed recovery evidence; the
current Job 1 -> Job 2 topology is recomputed and must match that captured
evidence exactly.

The `stage77.post_correction_aware.v1` recovery contract binds the attestation
schema, canonical payload digest, event evidence and authorization references.
Earlier recovery contracts remain exact and are never upgraded. Point 7 is
permitted only after successful Job 3 execution and validated registration of
the required DOCX, HTML and PDF artifacts; it has not occurred here.

The current recovery point carries its deterministic evidence payload and
payload digest in the canonical manifest. The live finalized evidence row is
appended after the validated snapshot and is not required inside its own
snapshot. This avoids the impossible cycle of storing a database digest inside
the final bytes used to compute that digest; later snapshots preserve prior
finalized evidence rows.
