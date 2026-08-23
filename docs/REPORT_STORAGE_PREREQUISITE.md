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

The storage diagnostic requires both variables explicitly, requires the exact durable paths above, rejects relative paths, traversal, `/tmp`, symlink components and overlapping paths, and verifies path metadata without opening SQLite or enumerating artifact contents. It never creates the artifact directory. Production variable configuration remains a separate Railway deployment action.

## Deployment Ordering

The Railway pre-deployment sequence is fail-fast and ordered:

1. durable governed-report storage diagnostic;
2. Stage 76 runtime PDF diagnostic;
3. low-level synthetic DOCX-to-PDF conversion;
4. governed Stage 76 adapter check.

The storage check exits non-zero before any PDF gate runs when the contract is absent or unsafe. It is invoked in explicit `durable` mode. The Uvicorn command, replica count, restart policy, Railpack packages and existing PDF gates are unchanged.

## Scope and Remaining Work

This prerequisite performs configuration and filesystem metadata validation only. It does not open the database, read records, enumerate artifacts, create files, generate reports or alter production.

No migration or deletion is required because no production governed-report artifact has been created. No Stage 77 release or Ledger entry is added. Isolated worker, restart-recovery and volume experiments remain pending. Backup guarantees remain unresolved.

## Local Evidence

The local diagnostic is expected to fail closed when the approved production variables and `/data` mount are absent. That is local configuration evidence only, not production evidence.
