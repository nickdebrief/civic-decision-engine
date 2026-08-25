"""Bounded diagnostics shared by the Stage 75 renderer and Stage 77 worker."""

from __future__ import annotations

import hashlib
import json
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

CURRENT_DIAGNOSTIC_CONTRACT = "current_diagnostic_contract_v1"
LEGACY_DIAGNOSTIC_CONTRACT = "legacy_pre_propagation_diagnostic_contract_v1"
TRANSITIONAL_DIAGNOSTIC_CONTRACT = "current_pre_terminal_projection_fix_diagnostic_contract_v1"
LEGACY_ATTEMPT_DIAGNOSTICS = (
    "governed_report_generation_validation_failed",
    "AdapterFailure",
)
LEGACY_TERMINAL_PAYLOAD = {
    "phase": "rendering",
    "code": "governed_report_renderer_failed",
}
LEGACY_ATTEMPT_SHA256 = "f5fa57e6989a8406c99bd3c26b877694515f44af74426684fbcc18a0268abd63"
LEGACY_TERMINAL_SHA256 = "f7456646b23f037b18af45f5019d5c817b54649cf28da14eecdf838817495239"
TRANSITIONAL_ATTEMPT_SHA256 = "6f83de150d27070d4aaf1aac040e18220968f440962ab47d935d39a33dd7fc67"
TRANSITIONAL_TERMINAL_SHA256 = "d62fa6f366270dcb0f3cedf973299d55f3ae0c671b70ea63907c7e378f0b6601"
TRANSITIONAL_DIAGNOSTIC = {
    "failure_phase": "rendering",
    "failure_operation": "adapter_preparation",
    "failure_checkpoint": "starting",
    "failure_code": "adapter_input_invalid",
    "failure_exception_category": "unexpected_error",
    "cleanup_status": "unknown",
    "adapter_invocation_entered": True,
    "adapter_process_started": True,
    "adapter_result_received": True,
    "format_category": "unknown",
}


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
    if value["adapter_process_started"] and not value["adapter_invocation_entered"]:
        raise ValueError("bounded_diagnostic_contract_invalid")
    if value["adapter_result_received"] and not value["adapter_process_started"]:
        raise ValueError("bounded_diagnostic_contract_invalid")
    if value["failure_checkpoint"] == "process_started" and not value["adapter_process_started"]:
        raise ValueError("bounded_diagnostic_contract_invalid")
    if value["failure_checkpoint"] == "result_received" and not value["adapter_result_received"]:
        raise ValueError("bounded_diagnostic_contract_invalid")
    return dict(value)


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("bounded_diagnostic_contract_invalid")
        result[key] = value
    return result


def _strict_json(value: str) -> Any:
    try:
        return json.loads(value, object_pairs_hook=_reject_duplicate_json_keys)
    except (TypeError, ValueError, json.JSONDecodeError):
        raise ValueError("bounded_diagnostic_contract_invalid") from None


def _legacy_payload_is_safe(value: str) -> bool:
    lowered = value.lower()
    return not any(token in lowered for token in ("traceback", "stderr", "stdout", "command", "/data/", "/tmp/", "\\", "exception:"))


def select_diagnostic_contract(*, attempt_raw: str, terminal_raw: str) -> dict[str, Any]:
    """Select one closed diagnostic contract from both immutable payloads."""
    attempt = _strict_json(attempt_raw)
    terminal = _strict_json(terminal_raw)
    if (isinstance(attempt, list) and attempt == list(LEGACY_ATTEMPT_DIAGNOSTICS)
            and terminal == LEGACY_TERMINAL_PAYLOAD
            and hashlib.sha256(attempt_raw.encode("utf-8")).hexdigest() == LEGACY_ATTEMPT_SHA256
            and hashlib.sha256(terminal_raw.encode("utf-8")).hexdigest() == LEGACY_TERMINAL_SHA256):
        if all(_legacy_payload_is_safe(item) for item in attempt) and _legacy_payload_is_safe(terminal_raw):
            return {
                "contract_id": LEGACY_DIAGNOSTIC_CONTRACT,
                "attempt_sha256": hashlib.sha256(attempt_raw.encode("utf-8")).hexdigest(),
                "terminal_sha256": hashlib.sha256(terminal_raw.encode("utf-8")).hexdigest(),
            }
    attempt_diagnostic = attempt[0] if isinstance(attempt, list) and len(attempt) == 1 and isinstance(attempt[0], Mapping) else None
    transitional_terminal_keys = {"phase", "code", "diagnostic"} | DIAGNOSTIC_FIELDS
    if (
        isinstance(attempt_diagnostic, Mapping)
        and dict(attempt_diagnostic) == TRANSITIONAL_DIAGNOSTIC
        and isinstance(terminal, Mapping)
        and set(terminal) == transitional_terminal_keys
        and terminal["phase"] == "rendering"
        and terminal["code"] == "governed_report_renderer_failed"
        and terminal["diagnostic"] == TRANSITIONAL_DIAGNOSTIC
        and all(terminal[name] == TRANSITIONAL_DIAGNOSTIC[name] for name in DIAGNOSTIC_FIELDS)
        and hashlib.sha256(attempt_raw.encode("utf-8")).hexdigest() == TRANSITIONAL_ATTEMPT_SHA256
        and hashlib.sha256(terminal_raw.encode("utf-8")).hexdigest() == TRANSITIONAL_TERMINAL_SHA256
    ):
        return {
            "contract_id": TRANSITIONAL_DIAGNOSTIC_CONTRACT,
            "attempt_sha256": TRANSITIONAL_ATTEMPT_SHA256,
            "terminal_sha256": TRANSITIONAL_TERMINAL_SHA256,
        }
    if not isinstance(attempt, list) or len(attempt) != 1 or not isinstance(attempt[0], Mapping):
        raise ValueError("bounded_diagnostic_contract_invalid")
    diagnostic = validate_diagnostic(attempt[0])
    expected_terminal_keys = {"phase", "operation", "checkpoint", "code", "diagnostic"} | DIAGNOSTIC_FIELDS
    if not isinstance(terminal, Mapping) or set(terminal) != expected_terminal_keys:
        raise ValueError("bounded_diagnostic_contract_invalid")
    terminal_diagnostic = validate_diagnostic(terminal["diagnostic"])
    if (
        diagnostic != terminal_diagnostic
        or terminal["phase"] != diagnostic["failure_phase"]
        or terminal["operation"] != diagnostic["failure_operation"]
        or terminal["checkpoint"] != diagnostic["failure_checkpoint"]
        or terminal["code"] != diagnostic["failure_code"]
        or any(terminal[name] != diagnostic[name] for name in DIAGNOSTIC_FIELDS)
    ):
        raise ValueError("bounded_diagnostic_contract_invalid")
    return {
        "contract_id": CURRENT_DIAGNOSTIC_CONTRACT,
        "attempt_sha256": hashlib.sha256(attempt_raw.encode("utf-8")).hexdigest(),
        "terminal_sha256": hashlib.sha256(terminal_raw.encode("utf-8")).hexdigest(),
    }


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
