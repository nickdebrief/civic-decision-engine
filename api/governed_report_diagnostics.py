"""Bounded diagnostics shared by the Stage 75 renderer and Stage 77 worker."""

from __future__ import annotations

import sqlite3
from typing import Any, Mapping


DIAGNOSTIC_FIELDS = {
    "failure_phase",
    "failure_operation",
    "failure_checkpoint",
    "failure_code",
    "failure_exception_category",
    "cleanup_status",
    "adapter_invocation_entered",
    "adapter_process_started",
    "adapter_result_received",
    "format_category",
}

FAILURE_PHASES = {
    "revalidation",
    "attempt_initialization",
    "output_preparation",
    "rendering",
    "validation",
    "promotion",
    "registration",
    "finalization",
    "cleanup",
    "job",
    "unknown",
}

FAILURE_OPERATIONS = {
    "generation_revalidation",
    "attempt_initialization",
    "output_preparation",
    "renderer_invocation",
    "adapter_preparation",
    "adapter_launch",
    "adapter_execution",
    "adapter_result_read",
    "adapter_result_validation",
    "docx_validation",
    "html_validation",
    "pdf_validation",
    "format_equivalence",
    "artifact_integrity",
    "artifact_staging",
    "artifact_promotion",
    "artifact_registration",
    "lifecycle_finalization",
    "job_result_serialization",
    "unknown",
}

FAILURE_CHECKPOINTS = {
    "starting",
    "entered",
    "process_started",
    "result_received",
    "validation",
    "staging",
    "promotion",
    "registration",
    "finalization",
    "cleanup",
    "unknown",
}

EXCEPTION_CATEGORIES = {
    "timeout",
    "value_error",
    "type_error",
    "os_error",
    "sqlite_error",
    "contract_error",
    "validation_error",
    "unexpected_error",
}

CLEANUP_STATUSES = {"passed", "failed", "unknown", "not_required"}
FORMAT_CATEGORIES = {"docx", "html", "pdf", "multiple", "none", "unknown"}


def combine_cleanup_status(inner: str, outer: str) -> str:
    statuses = {inner, outer}
    if "failed" in statuses:
        return "failed"
    if "unknown" in statuses:
        return "unknown"
    if "passed" in statuses:
        return "passed"
    return "not_required"

# This is deliberately a union of the existing Stage 75/76/77 bounded codes.
FAILURE_CODES = {
    "unknown",
    "governed_report_renderer_failed",
    "governed_report_renderer_timeout",
    "governed_report_generation_validation_failed",
    "governed_report_generation_source_changed",
    "governed_report_artifact_registration_failed",
    "governed_report_generation_cancelled",
    "governed_report_specification_digest_mismatch",
    "governed_report_qualification_required",
    "governed_report_qualification_mismatch",
    "governed_report_sole_distribution_invalid",
    "governed_report_publication_engine_version_invalid",
    "governed_report_qualification_disclosure_invalid",
    "governed_report_generation_approval_required",
    "governed_report_artifact_directory_exists",
    "governed_report_artifact_promotion_failed",
    "artifact_path_invalid",
    "artifact_integrity_failed",
    "qualification_invalid",
    "qualification_specification_mismatch",
    "qualification_distribution_invalid",
    "qualification_mode_invalid",
    "report_lifecycle_invalid",
    "report_version_superseded",
    "cancelled",
    "canonical_record_changed",
    "published_document_ineligible",
    "source_changed_or_hash_mismatch",
    "association_not_found",
    "association_ineligible",
    "association_changed",
    "attempt_initialization_failed",
    "output_preparation_failed",
    "lifecycle_finalization_failed",
    "adapter_input_missing",
    "adapter_input_invalid",
    "specification_digest_mismatch",
    "adapter_model_invalid",
    "docx_render_failed",
    "html_render_failed",
    "pdf_conversion_failed",
    "pdf_missing",
    "pdf_invalid",
    "pdf_metadata_invalid",
    "pdf_action_invalid",
    "pdf_attachment_invalid",
    "pdf_extraction_failed",
    "pdf_inspection_dependency_unavailable",
    "equivalence_failed",
    "artifact_digest_failed",
    "adapter_result_write_failed",
    "cleanup_failed",
    "unexpected_adapter_failure",
    "adapter_result_missing",
    "adapter_result_invalid",
    "adapter_return_contract_invalid",
}


def exception_category(exc: BaseException | None) -> str:
    if exc is None:
        return "unexpected_error"
    name = exc.__class__.__name__
    if name == "TimeoutExpired":
        return "timeout"
    if isinstance(exc, ValueError):
        return "value_error"
    if isinstance(exc, TypeError):
        return "type_error"
    if isinstance(exc, OSError):
        return "os_error"
    if isinstance(exc, sqlite3.Error):
        return "sqlite_error"
    return "unexpected_error"


def bounded_code(value: Any) -> str:
    return value if isinstance(value, str) and value in FAILURE_CODES else "unknown"


def make_diagnostic(
    *,
    phase: str = "unknown",
    operation: str = "unknown",
    checkpoint: str = "unknown",
    code: str = "unknown",
    exc: BaseException | None = None,
    exception_category_value: str | None = None,
    cleanup_status: str = "unknown",
    adapter_invocation_entered: bool = False,
    adapter_process_started: bool = False,
    adapter_result_received: bool = False,
    format_category: str = "unknown",
) -> dict[str, Any]:
    value = {
        "failure_phase": phase if phase in FAILURE_PHASES else "unknown",
        "failure_operation": operation if operation in FAILURE_OPERATIONS else "unknown",
        "failure_checkpoint": checkpoint if checkpoint in FAILURE_CHECKPOINTS else "unknown",
        "failure_code": bounded_code(code),
        "failure_exception_category": exception_category_value if exception_category_value in EXCEPTION_CATEGORIES else exception_category(exc),
        "cleanup_status": cleanup_status if cleanup_status in CLEANUP_STATUSES else "unknown",
        "adapter_invocation_entered": bool(adapter_invocation_entered),
        "adapter_process_started": bool(adapter_process_started),
        "adapter_result_received": bool(adapter_result_received),
        "format_category": format_category if format_category in FORMAT_CATEGORIES else "unknown",
    }
    return validate_diagnostic(value)


def validate_diagnostic(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != DIAGNOSTIC_FIELDS:
        raise ValueError("bounded_diagnostic_contract_invalid")
    if any(not isinstance(value[name], str) for name in ("failure_phase", "failure_operation", "failure_checkpoint", "failure_code", "failure_exception_category", "cleanup_status", "format_category")):
        raise ValueError("bounded_diagnostic_contract_invalid")
    if value["failure_phase"] not in FAILURE_PHASES or value["failure_operation"] not in FAILURE_OPERATIONS or value["failure_checkpoint"] not in FAILURE_CHECKPOINTS or value["failure_code"] not in FAILURE_CODES or value["failure_exception_category"] not in EXCEPTION_CATEGORIES or value["cleanup_status"] not in CLEANUP_STATUSES or value["format_category"] not in FORMAT_CATEGORIES:
        raise ValueError("bounded_diagnostic_contract_invalid")
    if any(not isinstance(value[name], bool) for name in ("adapter_invocation_entered", "adapter_process_started", "adapter_result_received")):
        raise ValueError("bounded_diagnostic_contract_invalid")
    return dict(value)


def adapter_mapping(phase: str, code: str) -> tuple[str, str, str]:
    if phase in {"input_load", "input_validation", "specification_validation", "model_adaptation"}:
        return "adapter_preparation", "starting", "rendering"
    if phase == "docx_render":
        return "docx_validation", "validation", "validation"
    if phase == "html_render":
        return "html_validation", "validation", "validation"
    if phase in {"pdf_conversion", "pdf_inspection"}:
        return "pdf_validation", "validation", "validation"
    if phase == "cross_format_equivalence":
        return "format_equivalence", "validation", "validation"
    if phase == "artifact_digest":
        return "artifact_integrity", "validation", "validation"
    if phase == "result_serialization":
        return "adapter_result_validation", "result_received", "validation"
    if phase == "cleanup":
        return "renderer_invocation", "cleanup", "cleanup"
    return "unknown", "unknown", "unknown"
