#!/usr/bin/env python3
"""Bounded, explicit Stage 77 recovery operations.

This command never runs automatically and never imports the web application.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from api.governed_report_recovery import (
    _connect,
    abort_recovery,
    capture_recovery_point,
    export_recovery_bundle,
    restore_recovery_point,
    validate_export_archive,
    validate_recovery_bundle,
    RecoveryOperationFailure,
)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="manage_stage77_recovery")
    commands = root.add_subparsers(dest="command", required=True)

    create = commands.add_parser("create", help="capture and validate an application-consistent recovery point")
    for name in ("database", "artifact-root", "recovery-root", "actor", "action"):
        create.add_argument(f"--{name}", required=True)
    create.add_argument("--approved-root", default="/data")
    create.add_argument("--drain-timeout", type=float, default=30.0)
    create.add_argument("--idempotency-key", default="")

    validate = commands.add_parser("validate", help="validate a completed recovery bundle")
    validate.add_argument("--bundle", required=True)

    export = commands.add_parser("export", help="package a validated recovery point for encrypted local custody")
    export.add_argument("--bundle", required=True)
    export.add_argument("--output", required=True, help="absolute archive path inside --custody-root")
    export.add_argument("--receipt", required=True, help="absolute receipt path inside --custody-root")
    export.add_argument("--custody-root", required=True, help="existing restrictive non-temporary custody directory")
    export.add_argument("--reason", required=True)

    validate_export = commands.add_parser("validate-export", help="validate an exported archive and custody receipt")
    validate_export.add_argument("--archive", required=True)
    validate_export.add_argument("--receipt", required=True)
    validate_export.add_argument("--extract-to")

    abort = commands.add_parser("abort", help="explicitly release workers after a failed recovery operation")
    for name in ("database", "actor", "action"):
        abort.add_argument(f"--{name}", required=True)

    restore = commands.add_parser("restore", help="restore a bundle into empty isolated paths")
    for name in ("bundle", "restore-root", "database-target", "artifact-root-target", "live-database", "live-artifact-root", "live-recovery-root", "actor", "action", "application-version", "publication-engine-version"):
        restore.add_argument(f"--{name}", required=True)
    restore.add_argument("--approved-root", default="/data")

    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "create":
            result = capture_recovery_point(database_path=args.database, artifact_root=args.artifact_root, recovery_root=args.recovery_root, actor=args.actor, governed_action=args.action, idempotency_key=args.idempotency_key, approved_root=args.approved_root, drain_timeout=args.drain_timeout)
            print(f"stage77_recovery=completed point={result['recovery_point_id']} manifest={result['manifest_digest']}", flush=True)
        elif args.command == "validate":
            result = validate_recovery_bundle(args.bundle)
            print(f"stage77_recovery=validated point={result['recovery_point_id']} manifest={result['manifest_digest']}", flush=True)
        elif args.command == "export":
            result = export_recovery_bundle(bundle_path=args.bundle, output_archive=args.output, receipt_path=args.receipt, reason=args.reason, custody_root=args.custody_root)
            print(f"stage77_recovery=exported point={result['recovery_point_id']} archive={result['archive_digest']} manifest={result['manifest_digest']}", flush=True)
        elif args.command == "validate-export":
            result = validate_export_archive(args.archive, args.receipt, extract_to=args.extract_to)
            print(f"stage77_recovery=export_validated point={result['recovery_point_id']} archive={result['archive_digest']} manifest={result['manifest_digest']}", flush=True)
        elif args.command == "abort":
            conn = _connect(args.database)
            try:
                result = abort_recovery(conn, actor=args.actor, governed_action=args.action)
            finally:
                conn.close()
            print(f"stage77_recovery=aborted epoch={result['maintenance_epoch']}", flush=True)
        else:
            result = restore_recovery_point(bundle_path=args.bundle, restore_root=args.restore_root, database_target=args.database_target, artifact_root_target=args.artifact_root_target, live_database=args.live_database, live_artifact_root=args.live_artifact_root, live_recovery_root=args.live_recovery_root, actor=args.actor, governed_action=args.action, approved_root=args.approved_root, application_version=args.application_version, publication_engine_version=args.publication_engine_version)
            print(f"stage77_recovery=restore_ready manifest={result['manifest_digest']}", flush=True)
        return 0
    except Exception as exc:
        if isinstance(exc, RecoveryOperationFailure):
            print(f"stage77_recovery=failed phase={exc.phase} operation={exc.operation} checkpoint={exc.checkpoint} code={exc.code} cleanup={exc.cleanup_status} maintenance={exc.maintenance_status}", flush=True)
            return 1
        code = str(exc) if str(exc) in {
            "recovery_already_active", "recovery_abort_invalid", "recovery_terminal_immutable", "recovery_event_immutable", "drain_timeout", "recovery_root_invalid", "recovery_root_outside_durable_root", "recovery_root_overlap", "recovery_root_overlaps_database", "recovery_root_overlaps_artifacts", "symlink_component", "artifact_invalid", "artifact_outside_root", "artifact_digest_mismatch", "artifact_changed_during_capture", "duplicate_artifact_source", "backup_timeout", "manifest_missing", "manifest_invalid", "manifest_digest_mismatch", "bundle_file_invalid", "bundle_file_inventory_invalid", "database_digest_mismatch", "integrity_check_failed", "foreign_key_check_failed", "artifact_inventory_mismatch", "job_state_count_mismatch", "record_count_mismatch", "version_count_mismatch", "recovery_event_bound_mismatch", "schema_incompatible", "engine_incompatible", "restore_target_invalid", "restore_target_overlap", "restore_integrity_failed", "custody_root_invalid", "custody_root_permissions", "export_target_invalid", "export_target_exists", "export_reason_invalid", "export_source_invalid", "export_source_changed", "export_filesystem_mismatch", "export_archive_invalid", "export_receipt_invalid", "export_archive_digest_mismatch", "export_receipt_mismatch", "export_extract_target_invalid", "recovery_operation_failed",
    } else "recovery_operation_failed"
        print(f"stage77_recovery=failed code={code}", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
