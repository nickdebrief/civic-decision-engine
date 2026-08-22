"""Isolated Stage 75 bridge to the documented Publication Engine v2.0.0."""

from __future__ import annotations

import json
import hashlib
import os
import signal
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from api.record_governed_reports import canonical_json


ENGINE_VERSION = "2.0.0"
ADAPTER_TIMEOUT_SECONDS = 210
ADAPTER = Path(__file__).resolve().parents[1] / "scripts" / "evidence_led_governance_pipeline" / "report_adapter.py"
RESULT_SCHEMA_VERSION = "1"
RESULT_MAX_BYTES = 64 * 1024
RESULT_PHASES = {
    "input_load", "input_validation", "specification_validation", "model_adaptation",
    "docx_render", "html_render", "pdf_conversion", "pdf_inspection",
    "cross_format_equivalence", "artifact_digest", "result_serialization", "cleanup",
}
RESULT_CODES = {
    "completed",
    "adapter_input_missing", "adapter_input_invalid", "specification_digest_mismatch",
    "adapter_model_invalid", "docx_render_failed", "html_render_failed",
    "pdf_conversion_failed", "pdf_missing", "pdf_invalid", "pdf_metadata_invalid",
    "pdf_action_invalid", "pdf_attachment_invalid", "pdf_extraction_failed",
    "pdf_inspection_dependency_unavailable",
    "equivalence_failed", "artifact_digest_failed", "adapter_result_write_failed",
    "cleanup_failed", "unexpected_adapter_failure", "adapter_result_missing",
    "adapter_result_invalid", "governed_report_renderer_timeout",
}
RESULT_FIELDS = {"schema_version", "ok", "phase", "code", "cleanup", "specification_digest", "artifacts", "diagnostics"}
DIAGNOSTIC_FIELDS = {
    "format", "libreoffice_version", "pdfinfo_version", "pypdf_version",
    "extraction_backend", "page_count", "size_bytes", "ordered_content",
    "metadata_attachments_annotations", "failure_field", "failure_location", "failure_reason",
    "failure_step", "failure_structure", "failure_operand", "failure_operand_kind",
    "failure_operand_count", "failure_operand_kinds", "failure_destination_mode", "failure_trailing_kinds",
    "page_registry_state", "reference_identity_result", "resolution_result", "resolved_target_comparison", "page_reference_attribute",
    "failure_operation", "failure_exception_class",
    "inspection_step", "failure_boundary",
}
INSPECTION_STEPS = {
    "validation_entry", "input_validation", "inspection_dispatch", "inspection_result_unpack",
    "inspection_result_validation", "limit_validation", "equivalence_preparation",
    "equivalence_dispatch", "equivalence_result_validation", "artifact_digest",
    "validation_body_complete", "validation_return_enter", "validation_return_complete",
    "caller_result_received", "caller_result_validation", "caller_result_serialization",
    "validation_result_unpack", "validation_result_construction", "validation_result_validation", "validation_return",
    "reader_construction", "encryption_and_page_count", "metadata_validation",
    "catalog_acquisition", "open_action_retrieval", "page_reference_registry",
    "indirect_reference_resolution", "passive_destination_validation",
    "outlines_names_traversal", "annotation_inspection", "attachment_inspection",
    "unsafe_action_inspection", "extracted_text_handling", "ordered_equivalence_validation",
    "result_construction", "page_count_validation",
}


@dataclass(frozen=True)
class AdapterFailure(ValueError):
    phase: str
    code: str
    cleanup: str = "unknown"
    diagnostic: dict[str, Any] | None = None

    def __str__(self) -> str:
        return "governed_report_renderer_failed"


def _read_adapter_result(path: Path, staged_output: Path, digest: str, expected_formats: set[str] | None = None) -> dict[str, Any]:
    if path.is_symlink() or path.resolve().parent != path.parent.resolve() or not path.is_file():
        raise AdapterFailure("result_serialization", "adapter_result_missing")
    if path.stat().st_size > RESULT_MAX_BYTES:
        raise AdapterFailure("result_serialization", "adapter_result_invalid")
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise AdapterFailure("result_serialization", "adapter_result_invalid") from None
    if not isinstance(result, dict) or set(result) != RESULT_FIELDS:
        raise AdapterFailure("result_serialization", "adapter_result_invalid")
    if result["schema_version"] != RESULT_SCHEMA_VERSION or not isinstance(result["ok"], bool):
        raise AdapterFailure("result_serialization", "adapter_result_invalid")
    if result["phase"] not in RESULT_PHASES or result["code"] not in RESULT_CODES:
        raise AdapterFailure("result_serialization", "adapter_result_invalid")
    if result["ok"] and result["specification_digest"] != digest:
        raise AdapterFailure("specification_validation", "specification_digest_mismatch")
    if result["ok"] and result["code"] != "completed":
        raise AdapterFailure("result_serialization", "adapter_result_invalid")
    if not result["ok"] and result["code"] == "completed":
        raise AdapterFailure("result_serialization", "adapter_result_invalid")
    if result["cleanup"] not in {"passed", "failed", "unknown"}:
        raise AdapterFailure("result_serialization", "adapter_result_invalid")
    if not isinstance(result["artifacts"], list) or not isinstance(result["diagnostics"], list):
        raise AdapterFailure("result_serialization", "adapter_result_invalid")
    if result["code"] == "unexpected_adapter_failure":
        if (
            result["ok"]
            or len(result["diagnostics"]) != 1
            or set(result["diagnostics"][0]) != {"format", "failure_step", "failure_operation", "failure_exception_class", "inspection_step", "failure_boundary"}
            or result["diagnostics"][0].get("inspection_step") not in INSPECTION_STEPS
        ):
            raise AdapterFailure("result_serialization", "adapter_return_contract_invalid")
    for diagnostic in result["diagnostics"]:
        if not isinstance(diagnostic, dict) or not set(diagnostic).issubset(DIAGNOSTIC_FIELDS):
            raise AdapterFailure("result_serialization", "adapter_result_invalid")
        if diagnostic.get("format") != "pdf":
            raise AdapterFailure("result_serialization", "adapter_result_invalid")
        if "failure_field" in diagnostic:
            if set(diagnostic) != {"format", "failure_field", "failure_reason"}:
                raise AdapterFailure("result_serialization", "adapter_result_invalid")
            if diagnostic["failure_field"] not in {"/Title", "/Author", "/Subject", "/Keywords", "/Creator", "/Producer", "/CreationDate", "/ModDate", "unknown_key"}:
                raise AdapterFailure("result_serialization", "adapter_result_invalid")
            if diagnostic["failure_reason"] not in {"unexpected_key", "unexpected_value", "identity_mismatch", "non_string_value", "forbidden_value", "missing_required_key"}:
                raise AdapterFailure("result_serialization", "adapter_result_invalid")
            continue
        if "failure_location" in diagnostic or "failure_reason" in diagnostic:
            if set(diagnostic) != {"format", "failure_location", "failure_reason", "failure_step", "failure_structure", "failure_operand", "failure_operand_kind", "failure_operand_count", "failure_operand_kinds", "failure_destination_mode", "failure_trailing_kinds", "page_registry_state", "reference_identity_result", "resolution_result", "resolved_target_comparison", "page_reference_attribute"}:
                raise AdapterFailure("result_serialization", "adapter_result_invalid")
            if diagnostic["failure_location"] not in {"catalog_open_action", "catalog_additional_actions", "page_additional_actions", "annotation_action", "outline_action"}:
                raise AdapterFailure("result_serialization", "adapter_result_invalid")
            if diagnostic["failure_reason"] not in {"executable_action", "external_destination", "malformed_destination", "unsupported_destination", "indirect_cycle", "attachment_or_interactive_content"}:
                raise AdapterFailure("result_serialization", "adapter_result_invalid")
            if diagnostic["failure_step"] not in {"open_action_wrapper", "open_action_resolution", "destination_array", "page_reference_identity", "page_reference_resolution", "page_membership", "fit_validation", "recursive_action_tree"}:
                raise AdapterFailure("result_serialization", "adapter_result_invalid")
            if diagnostic["failure_structure"] not in {"direct_array", "indirect_array", "action_dictionary", "unexpected_object"}:
                raise AdapterFailure("result_serialization", "adapter_result_invalid")
            if diagnostic["failure_operand"] not in {"none", "operand_count", "operand_one", "operand_two", "operand_three", "operand_four", "operand_five"}:
                raise AdapterFailure("result_serialization", "adapter_result_invalid")
            if diagnostic["failure_operand_kind"] not in {"none", "array", "indirect_reference", "direct_dictionary", "name", "other"}:
                raise AdapterFailure("result_serialization", "adapter_result_invalid")
            if diagnostic["failure_operand_count"] not in {"not_applicable", "0", "1", "2", "3", "4", "5", "6", "many"}:
                raise AdapterFailure("result_serialization", "adapter_result_invalid")
            if not isinstance(diagnostic["failure_operand_kinds"], list) or len(diagnostic["failure_operand_kinds"]) > 6 or any(item not in {"null", "number", "indirect_reference", "name", "array", "dictionary", "other"} for item in diagnostic["failure_operand_kinds"]):
                raise AdapterFailure("result_serialization", "adapter_result_invalid")
            if diagnostic["failure_destination_mode"] not in {"not_applicable", "fit", "fit_b", "fit_h", "fit_bh", "fit_v", "fit_bv", "fit_r", "xyz", "other_name", "missing", "not_name"}:
                raise AdapterFailure("result_serialization", "adapter_result_invalid")
            if not isinstance(diagnostic["failure_trailing_kinds"], list) or len(diagnostic["failure_trailing_kinds"]) > 5 or any(item not in {"null", "number", "indirect_reference", "name", "array", "dictionary", "other"} for item in diagnostic["failure_trailing_kinds"]):
                raise AdapterFailure("result_serialization", "adapter_result_invalid")
            if diagnostic["page_registry_state"] not in {"not_applicable", "empty", "populated", "duplicate_identity"}:
                raise AdapterFailure("result_serialization", "adapter_result_invalid")
            if diagnostic["reference_identity_result"] not in {"not_applicable", "registered", "not_registered", "ambiguous"}:
                raise AdapterFailure("result_serialization", "adapter_result_invalid")
            if diagnostic["resolution_result"] not in {"not_applicable", "resolved_page", "resolved_non_page", "resolution_failed"}:
                raise AdapterFailure("result_serialization", "adapter_result_invalid")
            if diagnostic["resolved_target_comparison"] not in {"not_applicable", "same_instance", "same_indirect_identity", "different_target", "unavailable"}:
                raise AdapterFailure("result_serialization", "adapter_result_invalid")
            if diagnostic["page_reference_attribute"] not in {"none", "indirect_reference"}:
                raise AdapterFailure("result_serialization", "adapter_result_invalid")
            continue
        if "failure_operation" in diagnostic or "failure_exception_class" in diagnostic:
            if set(diagnostic) != {"format", "failure_step", "failure_operation", "failure_exception_class", "inspection_step", "failure_boundary"}:
                raise AdapterFailure("result_serialization", "adapter_result_invalid")
            if diagnostic["failure_step"] not in {"input_load", "input_validation", "specification_validation", "model_adaptation", "docx_render", "html_render", "pdf_conversion", "pdf_inspection", "cross_format_equivalence", "artifact_digest", "result_serialization", "cleanup", "page_enumeration", "page_reference_attribute", "identity_normalization", "registry_construction", "open_action_identity_lookup", "indirect_reference_resolution", "resolved_target_classification", "registered_page_comparison", "destination_acceptance", "construct_reader", "validate_page_count", "validate_metadata", "inspect_actions", "parse_pdfinfo", "read_extracted_text", "prepare_extracted_text", "validate_ordered_equivalence", "construct_inspection_result", "read_pdfinfo_version", "unpack_pdfinfo_version", "validate_inspection_result", "validate_pdf"}:
                raise AdapterFailure("result_serialization", "adapter_result_invalid")
            if diagnostic["failure_operation"] not in {"read_request", "validate_input", "validate_digest", "adapt_model", "render_docx", "render_html", "convert_pdf", "inspect_pdf", "inspect_actions", "enumerate_pages", "materialize_page", "read_indirect_reference", "read_reference_identity", "build_page_registry", "lookup_open_action_reference", "resolve_indirect_reference", "classify_resolved_target", "compare_registered_page", "accept_destination", "construct_reader", "validate_page_count", "validate_metadata", "parse_pdfinfo", "read_extracted_text", "prepare_extracted_text", "validate_ordered_equivalence", "construct_inspection_result", "read_pdfinfo_version", "unpack_pdfinfo_version", "validate_inspection_result", "validate_pdf", "write_result", "unknown"}:
                raise AdapterFailure("result_serialization", "adapter_result_invalid")
            if diagnostic["failure_exception_class"] not in {"attribute_error", "type_error", "value_error", "key_error", "index_error", "pdf_read_error", "recursion_error", "os_error", "other"}:
                raise AdapterFailure("result_serialization", "adapter_result_invalid")
            if diagnostic["inspection_step"] not in INSPECTION_STEPS:
                raise AdapterFailure("result_serialization", "adapter_result_invalid")
            if diagnostic["failure_boundary"] not in {"function_body", "return_finalization", "caller_assignment", "caller_post_return", "result_serialization"}:
                raise AdapterFailure("result_serialization", "adapter_result_invalid")
            continue
        for key in ("libreoffice_version", "pdfinfo_version", "pypdf_version", "extraction_backend", "ordered_content", "metadata_attachments_annotations"):
            if key in diagnostic and not isinstance(diagnostic[key], str):
                raise AdapterFailure("result_serialization", "adapter_result_invalid")
        for key in ("page_count", "size_bytes"):
            if key in diagnostic and (not isinstance(diagnostic[key], int) or diagnostic[key] <= 0):
                raise AdapterFailure("result_serialization", "adapter_result_invalid")
    formats = [item.get("format") for item in result["artifacts"] if isinstance(item, dict)]
    if result["ok"] and expected_formats is not None and (len(formats) != len(set(formats)) or set(formats) != expected_formats):
        raise AdapterFailure("result_serialization", "adapter_result_invalid")
    for item in result["artifacts"]:
        if not isinstance(item, dict) or set(item) != {"format", "sha256", "size_bytes", "renderer_version"}:
            raise AdapterFailure("result_serialization", "adapter_result_invalid")
        if item["format"] not in {"docx", "html", "pdf"} or not isinstance(item["sha256"], str) or len(item["sha256"]) != 64 or any(character not in "0123456789abcdef" for character in item["sha256"]):
            raise AdapterFailure("result_serialization", "adapter_result_invalid")
        if not isinstance(item["size_bytes"], int) or item["size_bytes"] <= 0 or not isinstance(item["renderer_version"], str):
            raise AdapterFailure("result_serialization", "adapter_result_invalid")
        expected = staged_output / f"report.{item['format']}"
        if expected.is_symlink() or not expected.is_file():
            raise AdapterFailure("result_serialization", "adapter_result_invalid")
        if item["size_bytes"] != expected.stat().st_size or hashlib.sha256(expected.read_bytes()).hexdigest() != item["sha256"]:
            raise AdapterFailure("artifact_digest", "artifact_digest_failed")
    return result


def _terminate_process_group(process: subprocess.Popen[str]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.communicate(timeout=5)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def render_frozen_report(specification: Mapping[str, Any], digest: str, output_dir: Path) -> dict[str, Any]:
    if specification.get("publication_engine_version") != ENGINE_VERSION:
        raise ValueError("governed_report_publication_engine_version_invalid")
    if __import__("hashlib").sha256(canonical_json(specification).encode("utf-8")).hexdigest() != digest:
        raise ValueError("governed_report_specification_digest_mismatch")
    promoted = []
    with tempfile.TemporaryDirectory(prefix="cde-stage75-") as temp:
        request = Path(temp) / "specification.json"
        staged_output = Path(temp) / "output"
        staged_output.mkdir()
        request.write_text(json.dumps({"specification": specification, "digest": digest}, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        result_path = Path(temp) / "adapter-result.json"
        command = [sys.executable, str(ADAPTER), str(request), str(staged_output), str(result_path)]
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
            env={"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(ADAPTER.parent)},
        )
        try:
            stdout, stderr = process.communicate(timeout=ADAPTER_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            _terminate_process_group(process)
            raise AdapterFailure("cleanup", "governed_report_renderer_timeout") from None
        try:
            expected_formats = set(specification["requested_formats"]) if "requested_formats" in specification else None
            result = _read_adapter_result(result_path, staged_output, digest, expected_formats)
        except AdapterFailure:
            raise
        if not result["ok"]:
            detail = result["diagnostics"][0] if result["diagnostics"] and (result["code"] == "unexpected_adapter_failure" or "failure_field" in result["diagnostics"][0] or "failure_location" in result["diagnostics"][0] or "failure_operation" in result["diagnostics"][0]) else None
            raise AdapterFailure(result["phase"], result["code"], result["cleanup"], detail)
        if process.returncode != 0:
            raise AdapterFailure(result["phase"], result["code"], result["cleanup"])
        output_dir.mkdir(parents=True, exist_ok=True)
        for item in result["artifacts"]:
            source = (staged_output / f"report.{item['format']}").resolve()
            if source.parent != staged_output.resolve() or not source.is_file():
                raise AdapterFailure("artifact_digest", "artifact_digest_failed", result["cleanup"])
            destination = output_dir / source.name
            if destination.exists() or destination.is_symlink():
                raise AdapterFailure("artifact_digest", "artifact_digest_failed", result["cleanup"])
            staged_destination = output_dir / f".{source.name}.stage75-{os.getpid()}"
            shutil.copy2(source, staged_destination)
            os.replace(staged_destination, destination)
            promoted_item = dict(item)
            promoted_item["path"] = str(destination)
            promoted_item["sha256"] = hashlib.sha256(destination.read_bytes()).hexdigest()
            promoted_item["size_bytes"] = destination.stat().st_size
            promoted.append(promoted_item)
        result["artifacts"] = promoted
    return result
