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
