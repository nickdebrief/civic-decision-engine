"""Bounded diagnostics shared by the Stage 75 renderer and Stage 77 worker."""

from __future__ import annotations

import hashlib
import json
import errno as errno_module
import re
import sqlite3
from copy import deepcopy
from datetime import datetime
from typing import Any, Mapping


DIAGNOSTIC_FIELDS_V1 = {
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
FAILURE_RECORD_FIELDS = {"schema_version", "failure_event_id", "run_identifier", "attempt_identifier", "process_identifier", "supervisor_identifier", "operation_identifier", "native_errno", "native_errno_name", "exception_type", "diagnostic_message", "observed_at", "persisted_at", "lifecycle_event", "reconciliation_status"}
FAILURE_RECORD_FIELDS_V2 = FAILURE_RECORD_FIELDS | {"affected_target_state", "affected_target_class", "cleanup_relationship"}
DIAGNOSTIC_FIELDS = DIAGNOSTIC_FIELDS_V1 | {"failure_record"}

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
STRUCTURED_FAILURE_DIAGNOSTIC_CONTRACT = "structured_failure_diagnostic_contract_v2"
STRUCTURED_FAILURE_SCHEMA_VERSION = "structured_failure_attribution.v1"
STRUCTURED_FAILURE_SCHEMA_VERSION_V2 = "structured_failure_attribution.v2"
AFFECTED_TARGET_STATES_V2 = {"known", "absent", "unknown"}
AFFECTED_TARGET_CLASSES_V2 = {"governed_report", "report_artifact", "document_association"}
LEGACY_UNSPECIFIED = "legacy_unspecified"
CLEANUP_RELATIONSHIPS_V2 = {"not_required_after_primary": "not_required", "completed_after_primary": "passed", "failed_after_primary": "failed", "unknown_after_primary": "unknown"}
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

def _identifier(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None

def make_failure_record(*, operation: str, exc: BaseException | None = None, failure_event_id: str | None = None, run_identifier: str | None = None, attempt_identifier: str | None = None, process_identifier: str | None = None, supervisor_identifier: str | None = None, observed_at: str | None = None, lifecycle_event: str | None = None, reconciliation_status: str = "recorded", schema_version: str = STRUCTURED_FAILURE_SCHEMA_VERSION, affected_target_state: str | None = None, affected_target_class: str | None = None, cleanup_relationship: str | None = None, cleanup_status: str = "unknown") -> dict[str, Any]:
    native_errno = exc.errno if isinstance(exc, OSError) and isinstance(exc.errno, int) else None
    if schema_version not in {STRUCTURED_FAILURE_SCHEMA_VERSION, STRUCTURED_FAILURE_SCHEMA_VERSION_V2}: raise ValueError("bounded_failure_record_invalid")
    record = {"schema_version": schema_version, "failure_event_id": _identifier(failure_event_id), "run_identifier": _identifier(run_identifier), "attempt_identifier": _identifier(attempt_identifier), "process_identifier": _identifier(process_identifier), "supervisor_identifier": _identifier(supervisor_identifier), "operation_identifier": operation if operation in FAILURE_OPERATIONS else "unknown", "native_errno": native_errno, "native_errno_name": errno_module.errorcode.get(native_errno) if native_errno is not None else None, "exception_type": exc.__class__.__name__ if exc is not None else None, "diagnostic_message": "native_os_error" if native_errno is not None else None, "observed_at": _identifier(observed_at), "persisted_at": None, "lifecycle_event": _identifier(lifecycle_event), "reconciliation_status": reconciliation_status}
    if schema_version == STRUCTURED_FAILURE_SCHEMA_VERSION_V2:
        state = affected_target_state if affected_target_state is not None else "unknown"
        relationship = cleanup_relationship or next((name for name, status in CLEANUP_RELATIONSHIPS_V2.items() if status == cleanup_status), None)
        if relationship not in CLEANUP_RELATIONSHIPS_V2 or CLEANUP_RELATIONSHIPS_V2[relationship] != cleanup_status: raise ValueError("bounded_failure_record_invalid")
        record.update({"affected_target_state": state, "affected_target_class": affected_target_class, "cleanup_relationship": relationship})
    return validate_failure_record(record)

def validate_failure_record(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping): raise ValueError("bounded_failure_record_invalid")
    schema_version = value.get("schema_version")
    expected = FAILURE_RECORD_FIELDS_V2 if schema_version == STRUCTURED_FAILURE_SCHEMA_VERSION_V2 else FAILURE_RECORD_FIELDS
    if set(value) != expected or schema_version not in {STRUCTURED_FAILURE_SCHEMA_VERSION, STRUCTURED_FAILURE_SCHEMA_VERSION_V2}: raise ValueError("bounded_failure_record_invalid")
    if value.get("reconciliation_status") not in {"recorded", "reconciliation_required"}: raise ValueError("bounded_failure_record_invalid")
    for name in ("failure_event_id", "run_identifier", "attempt_identifier", "process_identifier", "supervisor_identifier", "exception_type", "diagnostic_message", "observed_at", "persisted_at", "lifecycle_event"):
        if value[name] is not None and (not isinstance(value[name], str) or not value[name]): raise ValueError("bounded_failure_record_invalid")
    native_errno = value["native_errno"]
    if native_errno is not None and (isinstance(native_errno, bool) or not isinstance(native_errno, int)): raise ValueError("bounded_failure_record_invalid")
    if value["native_errno_name"] != (errno_module.errorcode.get(native_errno) if native_errno is not None else None) or value["operation_identifier"] not in FAILURE_OPERATIONS: raise ValueError("bounded_failure_record_invalid")
    if schema_version == STRUCTURED_FAILURE_SCHEMA_VERSION_V2:
        state, target_class, relationship = value["affected_target_state"], value["affected_target_class"], value["cleanup_relationship"]
        if state not in AFFECTED_TARGET_STATES_V2 or relationship not in CLEANUP_RELATIONSHIPS_V2 or (state == "known" and target_class not in AFFECTED_TARGET_CLASSES_V2) or (state != "known" and target_class is not None): raise ValueError("bounded_failure_record_invalid")
    return dict(value)

def decode_failure_record(value: Mapping[str, Any]) -> dict[str, Any]:
    record = validate_failure_record(value)
    return {**record, "affected_target_state": LEGACY_UNSPECIFIED, "affected_target_class": None, "cleanup_relationship": LEGACY_UNSPECIFIED} if record["schema_version"] == STRUCTURED_FAILURE_SCHEMA_VERSION else record


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
    format_category: str = "unknown", failure_context: Mapping[str, Any] | None = None,
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
    context = dict(failure_context or {})
    if context.get("schema_version") == STRUCTURED_FAILURE_SCHEMA_VERSION_V2: context.setdefault("cleanup_status", value["cleanup_status"])
    value["failure_record"] = make_failure_record(operation=value["failure_operation"], exc=exc, **context)
    return validate_diagnostic(value)


def validate_diagnostic(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) not in {frozenset(DIAGNOSTIC_FIELDS_V1), frozenset(DIAGNOSTIC_FIELDS)}:
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
    if "failure_record" in value:
        record = validate_failure_record(value["failure_record"])
        if record["schema_version"] == STRUCTURED_FAILURE_SCHEMA_VERSION_V2 and CLEANUP_RELATIONSHIPS_V2[record["cleanup_relationship"]] != value["cleanup_status"]: raise ValueError("bounded_diagnostic_contract_invalid")
    return dict(value)

def with_persisted_at(value: Mapping[str, Any], *, persisted_at: str) -> dict[str, Any]:
    diagnostic = validate_diagnostic(value)
    if "failure_record" not in diagnostic: return diagnostic
    if not isinstance(persisted_at, str) or not persisted_at: raise ValueError("bounded_failure_record_invalid")
    record = dict(diagnostic["failure_record"])
    if record["persisted_at"] is not None: raise ValueError("bounded_failure_record_already_persisted")
    record["persisted_at"] = persisted_at
    return validate_diagnostic({**diagnostic, "failure_record": validate_failure_record(record)})


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
    transitional_terminal_keys = {"phase", "code", "diagnostic"} | DIAGNOSTIC_FIELDS_V1
    if (
        isinstance(attempt_diagnostic, Mapping)
        and dict(attempt_diagnostic) == TRANSITIONAL_DIAGNOSTIC
        and isinstance(terminal, Mapping)
        and set(terminal) == transitional_terminal_keys
        and terminal["phase"] == "rendering"
        and terminal["code"] == "governed_report_renderer_failed"
        and terminal["diagnostic"] == TRANSITIONAL_DIAGNOSTIC
        and all(terminal[name] == TRANSITIONAL_DIAGNOSTIC[name] for name in DIAGNOSTIC_FIELDS_V1)
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
    expected_terminal_keys = {"phase", "operation", "checkpoint", "code", "diagnostic"} | set(diagnostic)
    if not isinstance(terminal, Mapping) or set(terminal) != expected_terminal_keys:
        raise ValueError("bounded_diagnostic_contract_invalid")
    terminal_diagnostic = validate_diagnostic(terminal["diagnostic"])
    if (
        diagnostic != terminal_diagnostic
        or terminal["phase"] != diagnostic["failure_phase"]
        or terminal["operation"] != diagnostic["failure_operation"]
        or terminal["checkpoint"] != diagnostic["failure_checkpoint"]
        or terminal["code"] != diagnostic["failure_code"]
        or any(terminal[name] != diagnostic[name] for name in diagnostic)
    ):
        raise ValueError("bounded_diagnostic_contract_invalid")
    return {
        "contract_id": STRUCTURED_FAILURE_DIAGNOSTIC_CONTRACT if "failure_record" in diagnostic else CURRENT_DIAGNOSTIC_CONTRACT,
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


# CF36 canonical external failure-event contract.  It is deliberately separate
# from the existing Stage 77 internal diagnostic representation: introducing
# the external v1 schema must not rewrite historic diagnostic payloads.
CANONICAL_FAILURE_EVENT_SCHEMA_VERSION = "cde.n07.failure-event.v1"
CANONICAL_FAILURE_EVENT_FIELDS = frozenset({
    "schema_version", "failure_event_id", "operation", "phase", "checkpoint",
    "category", "attribution", "observed_at", "persisted_at", "terminal_outcome",
    "reconciliation_status", "provenance",
})
CANONICAL_ATTRIBUTION_FIELDS = frozenset({"run_id", "attempt_id", "process_id", "supervisor_id"})
CANONICAL_PROVENANCE_FIELDS = frozenset({"source_identity", "schema_manifest_id"})
CANONICAL_TERMINAL_OUTCOMES = frozenset({"failed", "not_completed"})
CANONICAL_RECONCILIATION_STATUSES = frozenset({"recorded", "reconciliation_required"})
CANONICAL_CATEGORIES = frozenset(EXCEPTION_CATEGORIES)
CANONICAL_OPERATIONS = frozenset(FAILURE_OPERATIONS | {"rendering"})
LEGACY_MIGRATION_STATES = frozenset({"legacy_unmapped", "adapted", "canonical", "rejected", "reconciliation_required"})
LEGACY_SUPPORT_MILESTONES = frozenset({
    "consumer_compatibility_evidenced", "migration_readiness_evidenced",
    "rollback_readiness_evidenced", "governance_approval",
})


def _canonical_error() -> ValueError:
    """A bounded public validation failure; never interpolate caller input."""
    return ValueError("canonical_failure_event_invalid")


_RFC3339_DATETIME = re.compile(
    r"^\d{4}-\d{2}-\d{2}T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d"
    r"(?:\.\d+)?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)$"
)


def _optional_rfc3339(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not _RFC3339_DATETIME.fullmatch(value):
        raise _canonical_error()
    try:
        datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        raise _canonical_error() from None
    return value


def _validate_attribution(value: Any) -> dict[str, str | None]:
    if not isinstance(value, Mapping) or set(value) != CANONICAL_ATTRIBUTION_FIELDS:
        raise _canonical_error()
    result: dict[str, str | None] = {}
    for key in CANONICAL_ATTRIBUTION_FIELDS:
        item = value[key]
        if item is not None and not _public_opaque_identifier(item):
            raise _canonical_error()
        result[key] = item
    return result


def _validate_provenance(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping) or set(value) != CANONICAL_PROVENANCE_FIELDS:
        raise _canonical_error()
    if any(not _public_opaque_identifier(value[key]) for key in CANONICAL_PROVENANCE_FIELDS):
        raise _canonical_error()
    return {key: value[key] for key in sorted(CANONICAL_PROVENANCE_FIELDS)}


def _public_opaque_identifier(value: Any) -> bool:
    """Accept bounded opaque identifiers, never arbitrary diagnostic content."""
    allowed = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-")
    return (
        isinstance(value, str)
        and bool(value)
        and len(value) <= 256
        and all(character in allowed for character in value)
    )


def validate_failure_event_v1(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the closed, privacy-bounded `cde.n07.failure-event.v1` shape."""
    if not isinstance(value, Mapping) or set(value) != CANONICAL_FAILURE_EVENT_FIELDS:
        raise _canonical_error()
    if value["schema_version"] != CANONICAL_FAILURE_EVENT_SCHEMA_VERSION:
        raise ValueError("unsupported_failure_event_schema_version")
    if not _public_opaque_identifier(value["failure_event_id"]):
        raise _canonical_error()
    if (
        not isinstance(value["operation"], str)
        or value["operation"] not in CANONICAL_OPERATIONS
        or not isinstance(value["phase"], str)
        or value["phase"] not in FAILURE_PHASES
    ):
        raise _canonical_error()
    checkpoint = value["checkpoint"]
    if checkpoint is not None and (
        not isinstance(checkpoint, str) or checkpoint not in FAILURE_CHECKPOINTS
    ):
        raise _canonical_error()
    if not isinstance(value["category"], str) or value["category"] not in CANONICAL_CATEGORIES:
        raise _canonical_error()
    if (
        not isinstance(value["terminal_outcome"], str)
        or value["terminal_outcome"] not in CANONICAL_TERMINAL_OUTCOMES
        or not isinstance(value["reconciliation_status"], str)
        or value["reconciliation_status"] not in CANONICAL_RECONCILIATION_STATUSES
    ):
        raise _canonical_error()
    return {
        "schema_version": CANONICAL_FAILURE_EVENT_SCHEMA_VERSION,
        "failure_event_id": value["failure_event_id"],
        "operation": value["operation"],
        "phase": value["phase"],
        "checkpoint": checkpoint,
        "category": value["category"],
        "attribution": _validate_attribution(value["attribution"]),
        "observed_at": _optional_rfc3339(value["observed_at"]),
        "persisted_at": _optional_rfc3339(value["persisted_at"]),
        "terminal_outcome": value["terminal_outcome"],
        "reconciliation_status": value["reconciliation_status"],
        "provenance": _validate_provenance(value["provenance"]),
    }


def make_failure_event_v1(*, failure_event_id: str, operation: str, phase: str, category: str,
                          checkpoint: str | None = None, attribution: Mapping[str, Any] | None = None,
                          observed_at: str | None = None, persisted_at: str | None = None,
                          terminal_outcome: str = "failed", reconciliation_status: str = "recorded",
                          source_identity: str = "pending", schema_manifest_id: str = "pending",
                          exception_message: str | None = None) -> dict[str, Any]:
    """Create a canonical event while intentionally discarding raw exception text."""
    del exception_message
    return validate_failure_event_v1({
        "schema_version": CANONICAL_FAILURE_EVENT_SCHEMA_VERSION,
        "failure_event_id": failure_event_id, "operation": operation, "phase": phase,
        "checkpoint": checkpoint, "category": category,
        "attribution": attribution if attribution is not None else {key: None for key in CANONICAL_ATTRIBUTION_FIELDS},
        "observed_at": observed_at, "persisted_at": persisted_at,
        "terminal_outcome": terminal_outcome, "reconciliation_status": reconciliation_status,
        "provenance": {"source_identity": source_identity, "schema_manifest_id": schema_manifest_id},
    })


def serialize_failure_event_v1(value: Mapping[str, Any]) -> str:
    """Deterministic external JSON serialization after closed-schema validation."""
    return json.dumps(validate_failure_event_v1(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def adapt_legacy_failure_event(legacy_record: Mapping[str, Any], *, source_identity: str,
                               schema_manifest_id: str, adapter_enabled: bool = True) -> dict[str, Any]:
    """Read-time-only legacy adapter; it never mutates the supplied source record."""
    if not isinstance(legacy_record, Mapping) or not adapter_enabled:
        raise ValueError("legacy_failure_event_adapter_unavailable")
    return make_failure_event_v1(
        failure_event_id=legacy_record.get("failure_event_id", legacy_record.get("id", "")),
        operation=legacy_record.get("operation", legacy_record.get("failure_operation", "unknown")),
        phase=legacy_record.get("phase", legacy_record.get("failure_phase", "unknown")),
        checkpoint=legacy_record.get("checkpoint", legacy_record.get("failure_checkpoint")),
        category=legacy_record.get("category", legacy_record.get("failure_exception_category", "unexpected_error")),
        attribution=legacy_record.get("attribution") or {key: legacy_record.get(key) for key in CANONICAL_ATTRIBUTION_FIELDS},
        observed_at=legacy_record.get("observed_at"), persisted_at=legacy_record.get("persisted_at"),
        terminal_outcome=legacy_record.get("terminal_outcome", "failed"),
        reconciliation_status=legacy_record.get("reconciliation_status", "recorded"),
        source_identity=source_identity, schema_manifest_id=schema_manifest_id,
    )


def rollback_failure_event(*, legacy_record: Mapping[str, Any]) -> dict[str, Any]:
    """Disable the adapter by returning a detached legacy representation unchanged."""
    if not isinstance(legacy_record, Mapping):
        raise ValueError("legacy_failure_event_invalid")
    try:
        return deepcopy(dict(legacy_record))
    except (TypeError, ValueError):
        raise ValueError("legacy_failure_event_invalid") from None


def consumer_version_status(schema_version: str) -> str:
    if schema_version == CANONICAL_FAILURE_EVENT_SCHEMA_VERSION:
        return "accepted"
    if schema_version in {CURRENT_DIAGNOSTIC_CONTRACT, LEGACY_DIAGNOSTIC_CONTRACT, TRANSITIONAL_DIAGNOSTIC_CONTRACT}:
        return "legacy_adapter_required"
    raise ValueError("unsupported_failure_event_schema_version")


def legacy_retirement_eligible(milestones: Mapping[str, bool]) -> bool:
    """Milestone based only: no timestamp or automatic retirement path exists."""
    if not isinstance(milestones, Mapping) or set(milestones) != LEGACY_SUPPORT_MILESTONES:
        raise ValueError("legacy_support_milestones_invalid")
    if any(type(milestones[key]) is not bool for key in LEGACY_SUPPORT_MILESTONES):
        raise ValueError("legacy_support_milestones_invalid")
    return all(milestones.values())
