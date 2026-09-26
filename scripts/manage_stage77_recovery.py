#!/usr/bin/env python3
"""Bounded, explicit Stage 77 recovery operations.

This command never runs automatically and never imports the web application.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import stat
import tempfile
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
from api.governed_report_jobs import CUSTODY_V2_DOMAIN, _canonical_v2, _v2_validate_payload
from api.governed_custody_evidence import ROLES, _identifier, canonical, evidence_root, strict_json


EVIDENCE_CAPTURE_ROOT_ENV = "CDE_STAGE77_CUSTODY_CAPTURE_SOURCE_ROOT"
EVIDENCE_AUTHORITY_FILENAME = "registry-authority.json"
EVIDENCE_MANIFEST_FILENAME = "manifest.json"
EVIDENCE_OBJECT_FILENAMES = {role: f"{role}.json" for role in ROLES}
EVIDENCE_MANIFEST_FIELDS = {
    "id", "mandate_id", "mandate_digest", "mandate_idempotency_key",
    "report_id", "report_version_id", "job1_id", "job2_id", "runtime",
    "capture_completed_at", "objects", "idempotency_key",
    "specification_digest", "qualification_id", "qualification_digest",
    "declaration", "rationale", "facts",
}
EVIDENCE_AUTHORITY_FIELDS = EVIDENCE_MANIFEST_FIELDS - {"objects", "facts"}


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
    for name in ("database", "recovery-root", "actor", "action"):
        abort.add_argument(f"--{name}", required=True)
    abort.add_argument("--recovery-operation-id", required=True, type=_operation_id)
    abort.add_argument("--approved-root", default="/data")
    abort.add_argument("--maintenance-epoch", required=True, type=_positive_epoch)

    restore = commands.add_parser("restore", help="restore a bundle into empty isolated paths")
    for name in ("bundle", "restore-root", "database-target", "artifact-root-target", "live-database", "live-artifact-root", "live-recovery-root", "actor", "action", "application-version", "publication-engine-version"):
        restore.add_argument(f"--{name}", required=True)
    restore.add_argument("--approved-root", default="/data")

    v2_sign = commands.add_parser("v2-envelope-sign", help="offline deterministic test-or-custody envelope signing")
    v2_sign.add_argument("--payload", required=True, help="canonical JSON payload path")
    v2_sign.add_argument("--output", required=True, help="new output envelope path")
    v2_sign.add_argument("--v2-private-key-file", required=True)
    v2_verify = commands.add_parser("v2-envelope-verify", help="verify a v2 envelope with explicit public authority")
    v2_verify.add_argument("--envelope", required=True)
    v2_verify.add_argument("--public-key-b64", required=True)

    prepare = commands.add_parser("prepare-evidence-store", help="offline-copy one fixed controller capture package into the private evidence store")
    prepare.add_argument("--evidence-set-id", required=True, type=_evidence_set_id)

    return root


def _positive_epoch(value: str) -> int:
    if not value or value != value.strip() or not value.isascii() or not value.isdecimal() or int(value) <= 0:
        raise argparse.ArgumentTypeError("recovery_abort_epoch_invalid")
    return int(value)


def _operation_id(value: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{32}", value or ""):
        raise argparse.ArgumentTypeError("recovery_abort_identity_invalid")
    return value


def _evidence_set_id(value: str) -> str:
    try:
        return _identifier(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("stage77_custody_evidence_identifier_invalid") from exc


def _private_directory(path: Path, *, code: str) -> Path:
    if path.is_symlink() or not path.is_dir():
        raise ValueError(code)
    if path.stat().st_mode & 0o022:
        raise ValueError(code)
    return path


def _capture_source_root() -> Path:
    raw = os.environ.get(EVIDENCE_CAPTURE_ROOT_ENV, "")
    if not raw or not os.path.isabs(raw):
        raise ValueError("stage77_custody_evidence_capture_source_unavailable")
    return _private_directory(Path(raw), code="stage77_custody_evidence_capture_source_unavailable")


def _regular_child(root: Path, name: str, *, code: str) -> Path:
    if not isinstance(name, str) or name in {"", ".", ".."} or "/" in name or "\\" in name:
        raise ValueError(code)
    path = root / name
    if path.is_symlink() or not path.is_file() or path.parent != root:
        raise ValueError(code)
    return path


def _read_stable_bytes(path: Path, *, code: str) -> bytes:
    before = path.stat()
    if not stat.S_ISREG(before.st_mode):
        raise ValueError(code)
    data = path.read_bytes()
    after = path.stat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        raise ValueError(code)
    return data


def _write_private_bytes(path: Path, data: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        try:
            path.unlink()
        except OSError:
            pass
        raise


def _verify_prepared_store(package: Path, evidence_set_id: str) -> tuple[dict, str, dict[str, tuple[int, str]]]:
    manifest_path = _regular_child(package, EVIDENCE_MANIFEST_FILENAME, code="stage77_custody_evidence_manifest_missing")
    manifest_bytes = _read_stable_bytes(manifest_path, code="stage77_custody_evidence_manifest_changed")
    try:
        manifest = strict_json(manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise ValueError("stage77_custody_evidence_manifest_invalid") from None
    if set(manifest) != EVIDENCE_MANIFEST_FIELDS or manifest.get("id") != evidence_set_id:
        raise ValueError("stage77_custody_evidence_manifest_invalid")
    items = manifest.get("objects")
    if not isinstance(items, list) or len(items) != len(ROLES):
        raise ValueError("stage77_custody_evidence_roles_invalid")
    roles, facts, measurements = set(), {}, {}
    for item in items:
        if not isinstance(item, dict) or set(item) != {"role", "filename", "media_type"}:
            raise ValueError("stage77_custody_evidence_roles_invalid")
        role = item["role"]
        if role not in ROLES or role in roles or item["filename"] != EVIDENCE_OBJECT_FILENAMES[role] or item["media_type"] != "application/json":
            raise ValueError("stage77_custody_evidence_roles_invalid")
        roles.add(role)
        object_bytes = _read_stable_bytes(_regular_child(package, item["filename"], code="stage77_custody_evidence_object_missing"), code="stage77_custody_evidence_object_changed")
        try:
            facts[role] = strict_json(object_bytes.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise ValueError("stage77_custody_evidence_retained_fact_invalid") from None
        measurements[role] = (len(object_bytes), hashlib.sha256(object_bytes).hexdigest())
    if roles != set(ROLES) or manifest.get("facts") != facts:
        raise ValueError("stage77_custody_evidence_retained_fact_mismatch")
    expected = {EVIDENCE_MANIFEST_FILENAME, *EVIDENCE_OBJECT_FILENAMES.values()}
    if {entry.name for entry in package.iterdir()} != expected:
        raise ValueError("stage77_custody_evidence_store_layout_invalid")
    return manifest, hashlib.sha256(manifest_bytes).hexdigest(), measurements


def prepare_evidence_store(evidence_set_id: str) -> dict[str, object]:
    """Copy one fixed controller capture package into the configured private store.

    This is intentionally preparation only: it never opens the application
    database, invokes registration, or creates an attestation or job.
    """
    _identifier(evidence_set_id)
    source_root = _capture_source_root()
    store_root = _private_directory(evidence_root(), code="stage77_custody_evidence_store_unavailable")
    source_package = source_root / evidence_set_id
    if source_package.is_symlink() or not source_package.is_dir() or source_package.parent != source_root:
        raise ValueError("stage77_custody_evidence_capture_source_unavailable")
    authority_bytes = _read_stable_bytes(_regular_child(source_package, EVIDENCE_AUTHORITY_FILENAME, code="stage77_custody_evidence_capture_authority_missing"), code="stage77_custody_evidence_capture_authority_changed")
    try:
        authority = strict_json(authority_bytes.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise ValueError("stage77_custody_evidence_capture_authority_invalid") from None
    if set(authority) != EVIDENCE_AUTHORITY_FIELDS or authority.get("id") != evidence_set_id:
        raise ValueError("stage77_custody_evidence_capture_authority_invalid")
    facts, object_bytes, source_measurements = {}, {}, {}
    for role in ROLES:
        source = _regular_child(source_package, EVIDENCE_OBJECT_FILENAMES[role], code="stage77_custody_evidence_capture_object_missing")
        data = _read_stable_bytes(source, code="stage77_custody_evidence_capture_object_changed")
        try:
            facts[role] = strict_json(data.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise ValueError("stage77_custody_evidence_retained_fact_invalid") from None
        object_bytes[role] = data
        source_measurements[role] = (len(data), hashlib.sha256(data).hexdigest())
    if {entry.name for entry in source_package.iterdir()} != {EVIDENCE_AUTHORITY_FILENAME, *EVIDENCE_OBJECT_FILENAMES.values()}:
        raise ValueError("stage77_custody_evidence_capture_layout_invalid")
    manifest = dict(authority)
    manifest["objects"] = [{"role": role, "filename": EVIDENCE_OBJECT_FILENAMES[role], "media_type": "application/json"} for role in ROLES]
    manifest["facts"] = facts
    manifest_bytes = canonical(manifest)
    destination = store_root / evidence_set_id
    if destination.exists() or destination.is_symlink():
        if destination.is_symlink() or not destination.is_dir():
            raise ValueError("stage77_custody_evidence_destination_exists")
        existing, existing_digest, existing_measurements = _verify_prepared_store(destination, evidence_set_id)
        if canonical(existing) != manifest_bytes or existing_measurements != source_measurements:
            raise ValueError("stage77_custody_evidence_destination_conflict")
        return {"id": evidence_set_id, "manifest_digest": existing_digest, "role_count": len(ROLES), "status": "already_prepared"}
    temporary = Path(tempfile.mkdtemp(prefix=f".{evidence_set_id}.", dir=store_root))
    try:
        os.chmod(temporary, 0o700)
        for role in ROLES:
            _write_private_bytes(temporary / EVIDENCE_OBJECT_FILENAMES[role], object_bytes[role])
        _write_private_bytes(temporary / EVIDENCE_MANIFEST_FILENAME, manifest_bytes)
        verified, manifest_digest, destination_measurements = _verify_prepared_store(temporary, evidence_set_id)
        if canonical(verified) != manifest_bytes or destination_measurements != source_measurements:
            raise ValueError("stage77_custody_evidence_store_verification_invalid")
        os.replace(temporary, destination)
        temporary = None
    finally:
        if temporary is not None:
            for child in temporary.iterdir():
                child.unlink()
            temporary.rmdir()
    return {"id": evidence_set_id, "manifest_digest": manifest_digest, "role_count": len(ROLES), "status": "prepared"}


def _read_v2_private_key(path_text: str) -> bytes:
    path = Path(path_text)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_mode & 0o077:
        raise ValueError("stage77_custody_v2_private_key_file_invalid")
    raw = path.read_bytes()
    if len(raw) != 32:
        raise ValueError("stage77_custody_v2_private_key_invalid")
    return raw


def _load_canonical_payload(path_text: str) -> dict:
    raw = Path(path_text).read_text(encoding="utf-8")
    value = json.loads(raw)
    value = _v2_validate_payload(value)
    if _canonical_v2(value).decode("utf-8") != raw:
        raise ValueError("stage77_custody_v2_payload_noncanonical")
    return value


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
                result = abort_recovery(conn, recovery_operation_id=args.recovery_operation_id, maintenance_epoch=args.maintenance_epoch, recovery_root=args.recovery_root, actor=args.actor, governed_action=args.action, approved_root=args.approved_root)
            finally:
                conn.close()
            print(f"stage77_recovery=aborted operation={result['operation_id']} epoch={result['maintenance_epoch']} prior_state={result['prior_state']} resulting_state={result['resulting_state']} cleanup={result['cleanup_status']} maintenance={result['maintenance_status']}", flush=True)
        elif args.command == "v2-envelope-sign":
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
            payload = _load_canonical_payload(args.payload)
            private_key = Ed25519PrivateKey.from_private_bytes(_read_v2_private_key(args.v2_private_key_file))
            signature = private_key.sign(CUSTODY_V2_DOMAIN + _canonical_v2(payload))
            envelope = {"payload": payload, "signature": base64.b64encode(signature).decode("ascii")}
            encoded = _canonical_v2(envelope)
            output = Path(args.output)
            if output.exists():
                raise ValueError("stage77_custody_v2_output_exists")
            output.write_bytes(encoded)
            print(f"stage77_custody_v2=created envelope_sha256={hashlib.sha256(encoded).hexdigest()}", flush=True)
        elif args.command == "v2-envelope-verify":
            from cryptography.exceptions import InvalidSignature
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
            envelope = json.loads(Path(args.envelope).read_text(encoding="utf-8"))
            if not isinstance(envelope, dict) or set(envelope) != {"payload", "signature"}:
                raise ValueError("stage77_custody_v2_envelope_invalid")
            payload = _v2_validate_payload(envelope["payload"])
            signature = base64.b64decode(envelope["signature"], validate=True)
            public_key = base64.b64decode(args.public_key_b64, validate=True)
            if len(public_key) != 32 or len(signature) != 64:
                raise ValueError("stage77_custody_v2_signature_invalid")
            try:
                Ed25519PublicKey.from_public_bytes(public_key).verify(signature, CUSTODY_V2_DOMAIN + _canonical_v2(payload))
            except InvalidSignature:
                raise ValueError("stage77_custody_v2_signature_invalid") from None
            print(f"stage77_custody_v2=verified envelope_sha256={hashlib.sha256(_canonical_v2(envelope)).hexdigest()}", flush=True)
        elif args.command == "prepare-evidence-store":
            result = prepare_evidence_store(args.evidence_set_id)
            print(f"stage77_custody_evidence={result['status']} evidence_set={result['id']} manifest={result['manifest_digest']} roles={result['role_count']}", flush=True)
        else:
            result = restore_recovery_point(bundle_path=args.bundle, restore_root=args.restore_root, database_target=args.database_target, artifact_root_target=args.artifact_root_target, live_database=args.live_database, live_artifact_root=args.live_artifact_root, live_recovery_root=args.live_recovery_root, actor=args.actor, governed_action=args.action, approved_root=args.approved_root, application_version=args.application_version, publication_engine_version=args.publication_engine_version)
            print(f"stage77_recovery=restore_ready manifest={result['manifest_digest']}", flush=True)
        return 0
    except Exception as exc:
        if isinstance(exc, RecoveryOperationFailure):
            print(f"stage77_recovery=failed phase={exc.phase} operation={exc.operation} checkpoint={exc.checkpoint} code={exc.code} cleanup={exc.cleanup_status} maintenance={exc.maintenance_status}", flush=True)
            return 1
        code = str(exc) if str(exc) in {
            "recovery_already_active", "recovery_abort_invalid", "recovery_abort_identity_invalid", "recovery_abort_epoch_invalid", "recovery_abort_identity_or_epoch_mismatch", "recovery_abort_state_mismatch", "recovery_abort_conditional_update", "recovery_abort_staging_invalid", "recovery_terminal_immutable", "recovery_event_immutable", "drain_timeout", "recovery_root_invalid", "recovery_root_outside_durable_root", "recovery_root_overlap", "recovery_root_overlaps_database", "recovery_root_overlaps_artifacts", "symlink_component", "artifact_invalid", "artifact_outside_root", "artifact_digest_mismatch", "artifact_changed_during_capture", "duplicate_artifact_source", "backup_timeout", "manifest_missing", "manifest_invalid", "manifest_digest_mismatch", "bundle_file_invalid", "bundle_file_inventory_invalid", "database_digest_mismatch", "integrity_check_failed", "foreign_key_check_failed", "artifact_inventory_mismatch", "job_state_count_mismatch", "record_count_mismatch", "recovery_event_bound_mismatch", "schema_incompatible", "engine_incompatible", "restore_target_invalid", "restore_target_overlap", "restore_integrity_failed", "custody_root_invalid", "custody_root_permissions", "export_target_invalid", "export_target_exists", "export_reason_invalid", "export_source_invalid", "export_source_changed", "export_filesystem_mismatch", "export_archive_invalid", "export_receipt_invalid", "export_archive_digest_mismatch", "export_receipt_mismatch", "export_extract_target_invalid", "stage77_custody_evidence_identifier_invalid", "stage77_custody_evidence_capture_source_unavailable", "stage77_custody_evidence_capture_authority_missing", "stage77_custody_evidence_capture_authority_changed", "stage77_custody_evidence_capture_authority_invalid", "stage77_custody_evidence_capture_object_missing", "stage77_custody_evidence_capture_object_changed", "stage77_custody_evidence_capture_layout_invalid", "stage77_custody_evidence_store_unavailable", "stage77_custody_evidence_destination_exists", "stage77_custody_evidence_destination_conflict", "stage77_custody_evidence_store_layout_invalid", "stage77_custody_evidence_store_verification_invalid", "stage77_custody_evidence_manifest_missing", "stage77_custody_evidence_manifest_changed", "stage77_custody_evidence_manifest_invalid", "stage77_custody_evidence_roles_invalid", "stage77_custody_evidence_retained_fact_invalid", "stage77_custody_evidence_retained_fact_mismatch", "recovery_operation_failed",
    } else "recovery_operation_failed"
        print(f"stage77_recovery=failed code={code}", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
