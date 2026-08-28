# Stage 77 Recovery Custody Runbook

This runbook governs application-level recovery custody for Stage 77. Railway
native volume backups are unavailable on the current plan and are not treated
as application-consistent backups. A completed, validated Stage 77 recovery
bundle and its portable export are the authoritative recovery artifacts.

Governance qualification is separate from recovery custody. A sole-
administrator-qualified report is not independently reviewed: it is explicitly
confirmed by its creator under the configured `sole_administrator` operating
constraint, remains `internal_working`, and carries the controlled disclosure
version `sole-admin-v1`. Recovery and the durable worker revalidate that
qualification; neither can create or broaden it.

## Recovery cadence

Create and validate a recovery point immediately before any production
deployment affecting the database schema, Stage 75 artifact ownership, Stage
76 rendering or equivalence, or Stage 77 jobs, workers, leases, recovery, or
supervision. Also create one after the first successful governed generation,
after a significant governed-artifact batch, at least every seven days while
job, event, or artifact state changes, before destructive maintenance or a
volume migration, and after incident recovery before normal worker processing
resumes.

Perform an isolated restore exercise at least quarterly, after every recovery
format or restore-code change, and after any failed or uncertain recovery
attempt. A restore exercise never overwrites production.

Retain the seven newest validated recovery points. Rotation is an operator
custody action, not an application authority over arbitrary local files. Never
delete the sole known-good recovery point; rotate only after a newer export
passes independent validation. Record deletion as a bounded operational
custody event.

## Create and export

Recovery creation and export are explicit governed operations. They never run
on import, startup, GET, listing, diagnostics, or ordinary worker startup.
First create a completed recovery point with the configured recovery command,
then export it only after bundle validation succeeds:

```sh
.venv/bin/python scripts/manage_stage77_recovery.py export \
  --bundle /data/cde-recovery-points/recovery-<id> \
  --output /secure-custody/stage77-recovery-<id>.tar \
  --receipt /secure-custody/stage77-recovery-<id>.json \
  --custody-root /secure-custody \
  --reason "before persistence deployment"

.venv/bin/python scripts/manage_stage77_recovery.py validate-export \
  --archive /secure-custody/stage77-recovery-<id>.tar \
  --receipt /secure-custody/stage77-recovery-<id>.json \
  --extract-to /secure-isolated-restore/stage77-<id>
```

The export is a deterministic, unencrypted tar transport containing only the
validated recovery bundle. The application creates no encryption scheme or
key material. The custody filesystem must provide the approved encryption.
The receipt contains only bounded identifiers, digests, counts, event bounds,
and schema/engine versions. It is integrity evidence, not proof of authorship.

Historical receipts are immutable evidence. Export validation selects the
closed receipt and manifest contract recorded by the bundle: pre-qualification
bundles are checked without qualification fields only when their archived
database proves that the qualification schema did not yet exist; current
qualification-aware bundles must contain and validate qualification counts,
event bounds, and the qualification-state digest, including legitimate zero
values. Later requirements are never imposed retrospectively, and no unknown,
mixed, or ambiguous receipt shape is accepted. Historical validation does not
claim current-contract compliance.

Stage 77 now has three closed recovery-contract generations: the historical
pre-qualification contract, the qualification-aware contract, and the
diagnostic-aware contract (`stage77.diagnostic_aware.v1`). Contract selection
is derived from the archived database. A database with governed terminal
diagnostic evidence must use the diagnostic-aware field set and cannot validate
under either older contract. That contract binds a deterministic inventory of
job, Stage 75 attempt, and Stage 77 terminal-event identities, selected
diagnostic contract identifiers, both payload SHA-256 values, and count/state
digests for diagnostic evidence and retry links. Raw diagnostic payloads remain
only in the SQLite backup; manifests and receipts contain no raw exceptions or
private content. Missing, mixed, reordered, unknown, or downgraded evidence
fails closed.

## Custody controls

The operator must select a canonical absolute custody directory outside the
repository, `/tmp`, `/private/tmp`, Railway volumes, live artifact roots,
recovery working roots, and publicly shared or automatically published
folders. The device or filesystem must be independently verified as encrypted
before export. The directory must be administrator-controlled, non-symlinked,
restrictively permissioned, and contain no executable recovery tooling.

Keep the archive and receipt together. Verify the archive SHA-256, run
`validate-export`, and compare the receipt with the governed capture output
before deleting any transport material. Plaintext archives must never be
emailed, committed to Git, uploaded to public storage, placed in the
repository, retained in a temporary directory, or copied to an unverified
device. A custody or digest failure blocks the affected deployment or
recovery operation. A failed new export does not invalidate earlier points.

Railway transport, when required, uses one uniquely named temporary SSH
Ed25519 key with canonical absolute paths, normal host verification, no
existing-key fallback, and mandatory removal of the Railway registration and
both local key files after transfer.

## Restore and first deployment

Restore is an explicit administrator action into new isolated storage. It
validates the manifest, database, SQLite integrity, foreign keys, artifact
digests, event bounds, schema, and engine before the worker can claim. Old
lease tokens are fenced and interrupted jobs follow the documented recovery
state policy. Restoration is not approval, publication, distribution, or
printing.

The first production deployment sequence is:

1. Complete code review and validation, then merge through one reviewed PR.
2. Observe the exact Railway revision and existing Stage 76 gates.
3. Confirm storage validation, Uvicorn, and exactly one worker are supervised.
4. Run non-mutating smoke checks only; do not submit a generation request.
5. Create a governed production recovery point through an authorized
   administrative execution mechanism. Startup side effects, public routes,
   and automatic generation are not substitutes.
6. Export, transfer with the temporary SSH key, and validate in the approved
   encrypted custody directory. Record the recovery and digest receipt.
7. Remove transport material and the temporary Railway key registration only
   after custody verification.
8. Submit at most one deliberately selected internal generation request.
9. Verify lifecycle, DOCX/HTML/PDF artifacts, digests, authorization, and
   private download.
10. Create and retain a post-generation recovery point.
11. Close Stage 77 only after pre-generation and post-generation custody
    evidence exists.

If production recovery cannot be invoked through a controlled administrative
execution mechanism, deployment remains blocked.

## Exceptional diagnostic-retry sequencing

The exceptional diagnostic retry is a separate governed action for the
recognized terminal renderer failure. It is not an automatic retry, ordinary
infrastructure retry, reapproval, or reuse of the generation declaration.
Job 1 and its events remain immutable, and only one linked successor may be
authorized.

For a failed pre-generation report, the required operational order is:

1. Implement and independently assure the bounded diagnostic contract.
2. Integrate and deploy the exact reviewed revision; verify worker readiness.
3. Capture a new recovery point preserving `validation_failed`, the immutable
   failed predecessor, zero artifacts, and no successor job.
4. Export and validate that bundle as encrypted Custody Point 4 without
   altering Custody Points 1–3.
5. Only after Custody Point 4 validation, use the authenticated diagnostic-
   retry form once with a bounded rationale and fixed declaration.
6. If the linked successor succeeds, capture the generated state separately
   as Custody Point 5. If it fails, stop and preserve its bounded diagnostics;
   any custody of that failed state requires separate authorization.

The retry must revalidate the frozen specification, final qualification,
source and association hashes, internal distribution, recovery state and
predecessor linkage. No second diagnostic retry, direct database mutation,
GET-triggered action, or worker-authorized retry is permitted. This sequencing
does not renumber or modify Custody Points 1–3.

The full persisted qualification envelope remains the governance and custody
source of truth. Immediately before adapter invocation, the worker projects
that already revalidated envelope into exactly the five-field Stage 76
rendering contract: `review_mode`, `disclosure_version`, `disclosure`,
`qualification_id`, and `qualification_digest`. The adapter remains strict and
continues to reject the persisted envelope itself. This projection does not
create a replacement qualification digest, alter sole-admin-v1 disclosure, or
rewrite either terminal job. Custody Point 5 therefore preserves the complete
pre-correction evidence; a post-correction recovery capture and any later
controlled generation require separate authorization.

Diagnostic evidence is versioned and immutable. A pre-propagation failure is
accepted only under the exact closed legacy pair recorded by its historical
Stage 75 producer and Stage 77 terminal producer, with independently checked
payload hashes and ownership state. The first terminal projection producer
also has a closed transitional contract,
`current_pre_terminal_projection_fix_diagnostic_contract_v1`, bound to its
exact Stage 75 and Stage 77 hashes; those rows are never rewritten or relabeled
as current. Future terminal events use the complete
`current_diagnostic_contract_v1` projection, including operation and
checkpoint. Mixed, partial, unknown, or downgraded pairs fail closed; progress
flags are monotonic and historical transitional flags are preserved as-is.
The diagnostic-aware recovery contract is required for any custody point whose
database contains such evidence, including Custody Point 4. A later Custody
Point 5 may bind both the immutable legacy predecessor and the single
transitional/current successor evidence entry plus the one retry link. No
additional retry is permitted, and no renderer correction is implied by the
transitional classification. No diagnostic retry may occur until the required
custody point has been captured, exported, and validated.

The post-correction execution is a distinct one-time authorization. It is not
a retry, a retry-of-retry, ordinary generation, reapproval, or lifecycle
reset. The authorization binds the unchanged Report 1 version and qualification
chain, Jobs 1 and 2, the deployed correction identity, and the completed Point
6 recovery. Point 6 archive and receipt digests are recorded as explicit
administrator custody attestations; the application validates the recovery
identity, state, manifest, and database evidence but cannot inspect detached
encrypted custody bytes. One authorization-bound job is created atomically
with its immutable link and event. Report 1 remains `validation_failed` while
queued and running. A terminal failure consumes the authorization and permits
no further retry. Point 7 is allowed only after successful validation and
registration of all requested artifacts followed by a final recovery capture
and deterministic custody export. No public or GET action is available.
### Point 6 custody attestation

The detached Point 6 archive and receipt are not readable by the production
service. Before the one-time post-correction authorization, an authenticated
administrator records one immutable `stage77.post_correction_custody_attestation.v1`
row. It binds the completed recovery identity and server-derived recovery,
diagnostic, topology, report, qualification, job and artifact evidence, while
the archive digest, receipt digest, archive size and custody-directory identity
remain explicitly administrator-attested external-custody claims. The
application records but does not independently verify those detached bytes.
The retry topology expected by the attestation is the count and digest already
preserved by the referenced governed recovery-evidence row; the application
recomputes the live Job 1 -> Job 2 topology and requires exact agreement rather
than trusting an unexplained hard-coded topology digest or accepting any
valid-looking current topology.

The attestation is a separate POST-only action. It is not generation, approval,
retry, recovery, publication or authorization of Job 3. Its finalized identity
and digest are the only Point 6 custody source accepted by the later
post-correction authorization and by the post-correction-aware recovery
contract. Existing custody points and their closed contracts are unchanged.
On databases created before this attestation field existed, the authorization
reference is validated transactionally against the attestation table because
SQLite cannot add that foreign key in place; newly created schemas retain the
explicit foreign key.

### Recovery evidence authority

An empty or readiness-only database can be operationally valid without being
eligible for governed recovery evidence. The
`stage77.post_correction_aware.v1` contract requires exactly one governed
report and one owned governed report version before evidence can be captured or
reconstructed. Pre-authorization means that no post-correction
authorization-linked execution exists; it does not by itself require the
absence of all historical governed jobs. No evidence is reconstructed from an
ambiguous or readiness-only state.

The recovery subsystem persists immutable deterministic evidence in
`stage77_recovery_point_evidence` and its append-only event table. Native
capture derives it from the captured manifest and SQLite state before recovery
completion is committed. A separate authenticated POST-only reconstruction can
record evidence from a preserved canonical bundle; it is not a capture,
restore, export, or custody verification. Detached archive and receipt claims,
archive size, and custody identity remain administrator-attested claims.

The current point's evidence is carried by its manifest, not by a row inside
the same database snapshot. A database digest cannot be stored in the final
bytes it digests without a self-referential cycle. The finalized live evidence
row is appended only after manifest validation; later snapshots carry prior
finalized evidence rows.
