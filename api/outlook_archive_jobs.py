from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from api.document_intake import (
    intake_document_file,
    intake_root,
    is_outlook_archive_document,
    load_pending_document,
)
from api.outlook_archives import (
    configured_outlook_archive_parser,
    outlook_archive_parser_status,
)
from api.outlook_archive_projections import build_outlook_archive_projection


ARCHIVE_JOB_STORE = ".outlook_archive_jobs"
ARCHIVE_JOB_CHUNK_BYTES = 1024 * 1024
TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
RETRYABLE_STATUSES = {"failed", "cancelled"}


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _job_root(root: Path | None = None) -> Path:
    path = (root or intake_root()).resolve(strict=False) / ARCHIVE_JOB_STORE
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def _job_path(job_id: str, *, root: Path | None = None) -> Path:
    safe_id = _validate_job_id(job_id)
    return _job_root(root) / f"{safe_id}.json"


def _metadata_path(document_id: str, *, root: Path | None = None) -> Path:
    destination_root = (root or intake_root()).resolve(strict=False)
    return destination_root / str(document_id) / "metadata.json"


def _validate_job_id(value: str) -> str:
    text = str(value or "").strip()
    if not text.startswith("outlook-job-"):
        raise ValueError("archive_job_not_found")
    suffix = text.removeprefix("outlook-job-")
    if len(suffix) != 32 or any(char not in "0123456789abcdef" for char in suffix):
        raise ValueError("archive_job_not_found")
    return text


def _save_json(path: Path, payload: dict[str, Any]) -> None:
    temporary_path = path.with_suffix(".tmp")
    temporary_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.chmod(temporary_path, 0o600)
    os.replace(temporary_path, path)
    os.chmod(path, 0o600)


def _save_job(job: dict[str, Any], *, root: Path | None = None) -> dict[str, Any]:
    job["updated_at"] = _utc_timestamp()
    _save_json(_job_path(str(job["job_id"]), root=root), job)
    return job


def load_archive_job(job_id: str, *, root: Path | None = None) -> dict[str, Any]:
    path = _job_path(job_id, root=root)
    if not path.is_file():
        raise ValueError("archive_job_not_found")
    return json.loads(path.read_text(encoding="utf-8"))


def list_archive_jobs(*, root: Path | None = None) -> list[dict[str, Any]]:
    path = _job_root(root)
    jobs: list[dict[str, Any]] = []
    for job_file in path.glob("outlook-job-*.json"):
        try:
            jobs.append(json.loads(job_file.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return sorted(
        jobs,
        key=lambda job: (str(job.get("created_at") or ""), str(job.get("job_id") or "")),
        reverse=True,
    )


def _append_history(job: dict[str, Any], status: str, phase: str, message: str) -> None:
    timestamp = _utc_timestamp()
    job["status"] = status
    job["phase"] = phase
    job["updated_at"] = timestamp
    job.setdefault("history", []).append(
        {
            "timestamp": timestamp,
            "status": status,
            "phase": phase,
            "message": message,
        }
    )
    job.setdefault("logs", []).append(
        {
            "timestamp": timestamp,
            "level": "info",
            "event": phase.lower().replace(" ", "_"),
            "message": message,
        }
    )


def _append_warning(job: dict[str, Any], message: str) -> None:
    timestamp = _utc_timestamp()
    job.setdefault("warnings", []).append(message)
    job.setdefault("logs", []).append(
        {
            "timestamp": timestamp,
            "level": "warning",
            "event": "archive_warning",
            "message": message,
        }
    )


def _append_failure(job: dict[str, Any], code: str, message: str) -> None:
    timestamp = _utc_timestamp()
    job["status"] = "failed"
    job["phase"] = "Failed"
    job["error_code"] = code
    job["error_message"] = message
    job["completed_at"] = timestamp
    job["progress_percent"] = 100
    job.setdefault("history", []).append(
        {
            "timestamp": timestamp,
            "status": "failed",
            "phase": "Failed",
            "message": message,
        }
    )
    job.setdefault("logs", []).append(
        {
            "timestamp": timestamp,
            "level": "error",
            "event": code,
            "message": message,
        }
    )


def _streaming_hashes(path: Path) -> tuple[str, str, int]:
    sha256 = hashlib.sha256()
    sha512 = hashlib.sha512()
    total = 0
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(ARCHIVE_JOB_CHUNK_BYTES)
            if not chunk:
                break
            total += len(chunk)
            sha256.update(chunk)
            sha512.update(chunk)
    return sha256.hexdigest(), sha512.hexdigest(), total


def _load_document_for_job(document_id: str, *, root: Path | None = None) -> dict[str, Any]:
    document = load_pending_document(document_id, root=root)
    if not is_outlook_archive_document(document):
        raise ValueError("archive_job_document_not_outlook_archive")
    return document


def _update_document_archive_metadata(
    document_id: str,
    updates: dict[str, Any],
    *,
    root: Path | None = None,
) -> dict[str, Any]:
    metadata_file = _metadata_path(document_id, root=root)
    if not metadata_file.is_file():
        raise ValueError("document_intake_not_found")
    metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
    archive_metadata = metadata.get("outlook_archive_metadata")
    if not isinstance(archive_metadata, dict):
        archive_metadata = {}
    archive_metadata.update(updates)
    metadata["outlook_archive_metadata"] = archive_metadata
    _save_json(metadata_file, metadata)
    return metadata


def create_archive_inspection_job(
    document_id: str,
    *,
    actor: str = "admin",
    root: Path | None = None,
) -> dict[str, Any]:
    document = _load_document_for_job(document_id, root=root)
    file_path, _metadata = intake_document_file(document_id, metadata=document, root=root)
    timestamp = _utc_timestamp()
    job_id = f"outlook-job-{uuid.uuid4().hex}"
    archive_metadata = (
        document.get("outlook_archive_metadata")
        if isinstance(document.get("outlook_archive_metadata"), dict)
        else {}
    )
    job = {
        "job_id": job_id,
        "document_id": document.get("intake_id"),
        "document_identifier": document.get("document_identifier"),
        "archive_type": archive_metadata.get("archive_type") or document.get("document_type"),
        "archive_filename": document.get("original_filename"),
        "archive_size_bytes": document.get("file_size_bytes"),
        "status": "queued",
        "phase": "Queued",
        "progress_percent": 0,
        "created_at": timestamp,
        "updated_at": timestamp,
        "started_at": None,
        "completed_at": None,
        "actor": str(actor or "admin"),
        "retry_count": 0,
        "cancel_requested": False,
        "storage_path": str(file_path),
        "preservation": {
            "storage_path": str(file_path),
            "preservation_timestamp": archive_metadata.get("preservation_timestamp")
            or document.get("upload_date"),
            "archive_size_bytes": document.get("file_size_bytes"),
            "hash_verification_status": archive_metadata.get("hash_verification_status")
            or "pending",
            "preservation_complete": archive_metadata.get("preservation_complete", True),
        },
        "parser": outlook_archive_parser_status(),
        "inspection": {},
        "warnings": [],
        "logs": [],
        "history": [],
    }
    _append_history(job, "uploaded", "Uploaded", "Archive bytes were already preserved by Document Intake.")
    _append_history(job, "queued", "Queued", "Archive inspection job queued.")
    _save_job(job, root=root)
    _update_document_archive_metadata(
        str(document["intake_id"]),
        {
            "archive_job_id": job_id,
            "latest_archive_job_id": job_id,
            "preservation_complete": True,
            "preservation_timestamp": archive_metadata.get("preservation_timestamp")
            or document.get("upload_date"),
            "preservation_completed_at": archive_metadata.get("preservation_completed_at")
            or document.get("upload_date"),
            "storage_path": str(file_path),
            "hash_verification_status": archive_metadata.get("hash_verification_status")
            or "pending",
        },
        root=root,
    )
    return job


def run_archive_inspection_job(job_id: str, *, root: Path | None = None) -> dict[str, Any]:
    job = load_archive_job(job_id, root=root)
    if job.get("status") == "cancelled":
        return job
    if job.get("status") == "completed":
        return job
    try:
        document = _load_document_for_job(str(job["document_id"]), root=root)
        file_path, _metadata = intake_document_file(
            str(job["document_id"]),
            metadata=document,
            root=root,
        )
        job["started_at"] = job.get("started_at") or _utc_timestamp()
        job["progress_percent"] = 15
        _append_history(job, "hashing", "Hashing", "Verifying preserved archive hashes.")
        sha256, sha512, size = _streaming_hashes(file_path)
        expected_sha256 = str(document.get("sha256_hash") or "")
        expected_sha512 = str(document.get("sha512_hash") or "")
        if sha256 != expected_sha256 or (expected_sha512 and sha512 != expected_sha512):
            _append_failure(
                job,
                "archive_job_checksum_mismatch",
                "Preserved archive hash verification failed.",
            )
            _save_job(job, root=root)
            _update_document_archive_metadata(
                str(job["document_id"]),
                {
                    "hash_verification_status": "failed",
                    "latest_archive_job_id": job["job_id"],
                },
                root=root,
            )
            return job
        job["progress_percent"] = 40
        _append_history(job, "preparing", "Preparing", "Preserved archive hashes verified.")
        parser_status = outlook_archive_parser_status()
        job["parser"] = parser_status
        if not parser_status.get("parser_available"):
            job["progress_percent"] = 70
            _append_history(
                job,
                "waiting_for_parser",
                "Waiting for Parser",
                parser_status.get("parser_status_message") or "Parser not configured.",
            )
            job["progress_percent"] = 100
            job["completed_at"] = _utc_timestamp()
            _append_history(
                job,
                "completed",
                "Completed",
                "Archive preservation is complete; no parser inspection was performed.",
            )
            job["inspection"] = {
                "inspection_complete": False,
                "inspection_timestamp": None,
                "archive_validity": "not_inspected",
                "mailbox_count": None,
                "top_level_folder_count": None,
                "archive_health": "parser_not_configured",
                "parser_warnings": [],
            }
            _save_job(job, root=root)
            _update_document_archive_metadata(
                str(job["document_id"]),
                {
                    "latest_archive_job_id": job["job_id"],
                    "preservation_complete": True,
                    "preservation_completed_at": job["completed_at"],
                    "hash_verification_status": "verified",
                    "parser_available": False,
                    "parser_status": parser_status.get("parser_status"),
                    "parser_status_message": parser_status.get("parser_status_message"),
                    "parser_version": parser_status.get("parser_version"),
                    "inspection_complete": False,
                    "inspection_timestamp": None,
                    "archive_health": "parser_not_configured",
                    "job_history": job.get("history", []),
                },
                root=root,
            )
            return job

        job["progress_percent"] = 65
        _append_history(job, "inspecting", "Inspecting", "Parser inspection started.")
        parser = configured_outlook_archive_parser()
        if parser is None or not parser.supports(file_path):
            _append_failure(
                job,
                "archive_job_parser_unsupported",
                "Configured parser does not support this archive.",
            )
            _save_job(job, root=root)
            return job
        inspection = parser.inspect(file_path)
        warnings = [
            str(value)
            for value in inspection.get("parser_warnings", [])
            if str(value).strip()
        ][:25]
        for warning in warnings:
            _append_warning(job, warning)
        timestamp = _utc_timestamp()
        job["inspection"] = {
            "inspection_complete": True,
            "inspection_timestamp": timestamp,
            "archive_validity": inspection.get("archive_validity") or "plausible",
            "mailbox_count": inspection.get("mailbox_count"),
            "top_level_folder_count": inspection.get("top_level_folder_count"),
            "archive_health": inspection.get("archive_health") or "inspected",
            "parser_warnings": warnings,
        }
        projection = None
        if callable(getattr(parser, "project", None)):
            job["progress_percent"] = 85
            _append_history(
                job,
                "projecting",
                "Projecting",
                "Administrative folder and message metadata projection started.",
            )
            projection = build_outlook_archive_projection(
                document=document,
                job=job,
                file_path=file_path,
                parser=parser,
                root=root,
            )
        job["progress_percent"] = 100
        job["completed_at"] = timestamp
        _append_history(job, "completed", "Completed", "Archive inspection completed.")
        _save_job(job, root=root)
        _update_document_archive_metadata(
            str(job["document_id"]),
            {
                "latest_archive_job_id": job["job_id"],
                "preservation_complete": True,
                "preservation_completed_at": job["completed_at"],
                "hash_verification_status": "verified",
                "parser_available": True,
                "parser_status": parser_status.get("parser_status"),
                "parser_status_message": parser_status.get("parser_status_message"),
                "parser_version": parser_status.get("parser_version"),
                "inspection_complete": True,
                "inspection_timestamp": timestamp,
                "archive_validity": job["inspection"]["archive_validity"],
                "mailbox_count": job["inspection"]["mailbox_count"],
                "top_level_folder_count": job["inspection"]["top_level_folder_count"],
                "archive_health": job["inspection"]["archive_health"],
                "parser_warnings": warnings,
                "projection_state": projection.get("projection_state") if projection else "pending",
                "projection_timestamp": projection.get("projection_timestamp") if projection else None,
                "projection_job_id": job["job_id"] if projection else None,
                "folder_projection_performed": bool(projection),
                "message_projection_performed": bool(projection),
                "projected_folder_count": (
                    projection.get("statistics", {}).get("folder_count") if projection else None
                ),
                "projected_message_count": (
                    projection.get("statistics", {}).get("message_count") if projection else None
                ),
                "job_history": job.get("history", []),
            },
            root=root,
        )
        return job
    except Exception:
        _append_failure(
            job,
            "archive_job_unexpected_failure",
            "Archive inspection failed without compromising preserved evidence.",
        )
        _save_job(job, root=root)
        try:
            _update_document_archive_metadata(
                str(job.get("document_id") or ""),
                {
                    "latest_archive_job_id": job.get("job_id"),
                    "archive_job_failed": True,
                    "archive_job_error": job.get("error_code"),
                },
                root=root,
            )
        except Exception:
            pass
        return job


def retry_archive_job(
    job_id: str,
    *,
    actor: str = "admin",
    root: Path | None = None,
) -> dict[str, Any]:
    job = load_archive_job(job_id, root=root)
    if job.get("status") not in RETRYABLE_STATUSES:
        return job
    retry_count = int(job.get("retry_count") or 0) + 1
    job.update(
        {
            "status": "queued",
            "phase": "Queued",
            "progress_percent": 0,
            "completed_at": None,
            "error_code": None,
            "error_message": None,
            "cancel_requested": False,
            "retry_count": retry_count,
            "retry_actor": str(actor or "admin"),
        }
    )
    _append_history(job, "queued", "Queued", "Archive inspection job queued for retry.")
    _save_job(job, root=root)
    return run_archive_inspection_job(str(job["job_id"]), root=root)


def cancel_archive_job(
    job_id: str,
    *,
    actor: str = "admin",
    root: Path | None = None,
) -> dict[str, Any]:
    job = load_archive_job(job_id, root=root)
    if job.get("status") in TERMINAL_STATUSES:
        return job
    job["cancel_requested"] = True
    job["cancelled_by"] = str(actor or "admin")
    job["completed_at"] = _utc_timestamp()
    job["progress_percent"] = 100
    _append_history(job, "cancelled", "Cancelled", "Archive inspection job cancelled.")
    return _save_job(job, root=root)


def archive_job_status(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "job_id": job.get("job_id"),
        "document_id": job.get("document_id"),
        "document_identifier": job.get("document_identifier"),
        "archive_filename": job.get("archive_filename"),
        "archive_type": job.get("archive_type"),
        "status": job.get("status"),
        "phase": job.get("phase"),
        "progress_percent": job.get("progress_percent"),
        "created_at": job.get("created_at"),
        "started_at": job.get("started_at"),
        "completed_at": job.get("completed_at"),
        "updated_at": job.get("updated_at"),
        "retry_count": job.get("retry_count"),
        "parser": job.get("parser"),
        "inspection": job.get("inspection"),
        "warnings": job.get("warnings", []),
        "error_code": job.get("error_code"),
        "error_message": job.get("error_message"),
    }
