# Governed Report Storage Prerequisite

This document records an infrastructure prerequisite for future Stage 77 work. It does not implement Stage 77 and does not change the Stage Ledger.

## Boundary

**A JOB EXECUTES AN APPROVED REPORT SPECIFICATION—IT DOES NOT ALTER OR APPROVE IT.**

Stage 75 remains the owner of governed report specifications, versions, lifecycle and private artifacts. Stage 76 remains the owner of governed PDF rendering and DOCX/HTML/PDF equivalence. No worker, queue, lease or durable job capability is introduced here.

## Approved Production Storage

The Railway production volume is mounted at `/data`. The required production values are:

```text
RECORDS_DB_PATH=/data/records.db
CDE_REPORT_ARTIFACT_ROOT=/data/cde-governed-reports
```

The attached `/data` mount must already exist as a real, non-symlinked directory. The approved artifact leaf may be absent before the first deliberate governed-report generation. The diagnostic is strictly read-only and never creates `/data/cde-governed-reports`; Stage 75 creates it only during that authorized generation path. Missing `/data`, a missing database file, or any missing nested artifact structure fails closed.

`/tmp` is suitable only for renderer staging, conversion profiles, extracted text and other temporary material. It is not suitable for final governed artifacts because it is ephemeral across container replacement and deployment.

The storage diagnostic requires both variables explicitly, requires the exact durable paths above, rejects relative paths, traversal, `/tmp`, symlink components and overlapping paths, and verifies path metadata without opening SQLite or enumerating artifact contents. It never creates the artifact directory. The first production attempt (`28d1d2b6-81c1-4bbc-a360-c279b460464e`) failed with the bounded `durable_root_missing` result because Railway does not mount volumes in pre-deploy containers; this did not disprove the storage configuration. The required production artifact variable remains configured. No manual directory provisioning is performed.

## Deployment Ordering

The Railway pre-deployment sequence remains fail-fast and ordered for the PDF toolchain:

1. Stage 76 runtime PDF diagnostic;
2. low-level synthetic DOCX-to-PDF conversion;
3. governed Stage 76 adapter check.

Durable storage validation now runs once during application-container startup, after the volume is mounted and before Uvicorn starts. `scripts/start_cde_runtime.sh` emits bounded start/pass markers, invokes the diagnostic in explicit `durable` mode, and uses `exec` for the existing Uvicorn host and port contract. Uvicorn does not start when storage validation fails. The wrapper performs no storage writes, starts no worker, and does not generate reports. The Uvicorn command is otherwise unchanged, as are the replica count, restart policy, Railpack packages and PDF gates.

Runtime validation can fail startup rather than blocking a deployment before activation, and `ON_FAILURE` restart behavior may repeat a deterministic failure. The check is therefore bounded, fast, fail-closed and side-effect-free. Railway volume deployments are not concurrently mounted to the same service, so no replica, restart or drain setting is changed here.

## Scope and Remaining Work

This prerequisite performs configuration and filesystem metadata validation only. It does not open the database, read records, enumerate artifacts, create files, generate reports or alter production.

No migration or deletion is required because no production governed-report artifact has been created, and the approved artifact directory is not manually provisioned. No Stage 77 release or Ledger entry is added. Stage 77 worker functionality is unimplemented. Isolated worker, restart-recovery, WAL and fencing experiments remain pending. Backup guarantees remain unresolved.

## Local Evidence

The local diagnostic is expected to fail closed when the approved production variables and `/data` mount are absent. That is local configuration evidence only, not production evidence.
