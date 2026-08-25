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
shape and independently bound payload digests; current failures require the
strict `current_diagnostic_contract_v1` shape. Mixed, partial, unknown and
downgraded pairs fail closed. Historical rows are never rewritten or upgraded.
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
before the one separately governed linked retry is authorized.

Export and restore require an administrator and never run automatically during
import, startup, GET, listing, diagnostics, or worker startup. Backup creation
is not proof of successful restoration, and restoration is not approval,
publication, distribution, or printing.
