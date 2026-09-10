#!/usr/bin/env python3
"""Run every governed test module in a fresh launcher-contained process."""

from __future__ import annotations

import argparse
import ast
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence


CONTAINMENT_STATUS = 97
ORCHESTRATOR_STATUS = 98
CLASSIFICATIONS = frozenset({"real_asgi", "legacy_fastapi_stub", "neutral"})
FRAMEWORKS = frozenset({"unittest", "pytest"})
MODULE_RE = re.compile(r"tests(?:\.[A-Za-z_][A-Za-z0-9_]*)+")

# This is deliberately source-owned rather than discovery-owned.  Additions to
# tests/test_*.py must be classified here before the governed suite may run.
GOVERNED_TRACKED_MODULES = frozenset(
    """
tests.test_admin_audit_traceability tests.test_admin_console_navigation_and_table_readability tests.test_admin_document_intake tests.test_admin_navigation_console tests.test_admin_session tests.test_apple_emlx_support tests.test_archive_collection_membership_governance tests.test_archive_manifest tests.test_association_card_visual_refinement tests.test_association_public_traceability tests.test_attachment_audit_events tests.test_attachment_manifest tests.test_attachment_privacy tests.test_attachment_read_only_ui tests.test_attachment_upload tests.test_attachments tests.test_authoritative_source_visual_emphasis tests.test_backfill_record_embeddings tests.test_canonical_record_from_published_document tests.test_canonical_record_types tests.test_cde_platform_stage_ledger tests.test_collection_ordered_sequence_continuity tests.test_developer_database_test_launcher tests.test_document_identifier_on_intake tests.test_document_keywords tests.test_fastapi_test_order_stabilisation tests.test_gmail_takeout_support tests.test_governed_archive_collections tests.test_governed_audio_artefact_support tests.test_governed_intake_corrections tests.test_governed_public_transmissions tests.test_governed_rich_text_format_artefact_support tests.test_governed_source_relationship_selection tests.test_governed_spreadsheet_artefact_support tests.test_imap_acquisition tests.test_jpeg_variant_intake_validation tests.test_landing_page_footer_alignment tests.test_list_record_attachments tests.test_machine_discoverability tests.test_mailbox_relationship_graph tests.test_mbox_archive_support tests.test_outlook_archive_attachment_governance tests.test_outlook_archive_governed_promotion tests.test_outlook_archive_intake_boundary tests.test_outlook_archive_jobs tests.test_outlook_archive_projection tests.test_outlook_msg_support tests.test_paste_json_analysis_flow tests.test_pdf_runtime_prerequisite tests.test_pdf_synthetic_conversion tests.test_platform_identity_transition tests.test_public_archive_explorer tests.test_public_archive_ux_refinements tests.test_public_association_index tests.test_public_collection_pages tests.test_public_document_library tests.test_public_document_preview_enhancements tests.test_public_footer_administration_link tests.test_public_navigation_completion tests.test_public_navigation_information_architecture tests.test_public_record_document_association tests.test_public_traceability_map tests.test_public_transmission_ux_refinements tests.test_publication_engine_pdf_validation_fallback tests.test_publication_engine_stage2 tests.test_publication_engine_stage3 tests.test_publication_engine_stage4 tests.test_publication_engine_stage5 tests.test_query_record_embeddings tests.test_record_document_association_record_selection tests.test_record_document_association_searchable_record_selection tests.test_record_indexing tests.test_record_synthetic_attachment_audit_event tests.test_report_storage_prerequisite tests.test_rfc5322_eml_support tests.test_run_semantic_experiments tests.test_semantic_retrieval tests.test_semantic_search tests.test_stage49_email_attachment_preservation tests.test_stage51_1_backfill_intake_targeting tests.test_stage51_outlook_msg_attachment_preservation tests.test_stage52_apple_emlx_attachment_preservation tests.test_stage53_1_mailbox_attachment_relationship_navigation tests.test_stage53_mbox_attachment_preservation tests.test_stage54_apple_mail_mailbox_relationship_projection_and_navigation tests.test_stage55_attachment_published_document_source_context_and_navigation tests.test_stage56_durable_document_lifecycle_decision_record tests.test_stage57_governed_lifecycle_decision_confirmation tests.test_stage58_governed_document_reconsideration_and_lifecycle_episodes tests.test_stage59_lifecycle_episode_presentation tests.test_stage60_governed_decision_abstraction tests.test_stage61_1_relationship_decision_admin_inspection tests.test_stage61_2_relationship_corrections tests.test_stage61_relationship_domain_decisions tests.test_stage62_governed_pattern_observation tests.test_stage63_governed_inference tests.test_stage64_1_governed_allegation_source_selection tests.test_stage64_governed_allegation tests.test_stage65_governed_response tests.test_stage66_1_deliberate_authority_classification tests.test_stage66_governed_decision_authority tests.test_stage67_1_determination_linking tests.test_stage67_governed_determination tests.test_stage68_governed_challenge tests.test_stage69_governed_remedy tests.test_stage70_governed_implementation_event tests.test_stage71_1_procedural_time_ui tests.test_stage71_governed_procedural_time tests.test_stage72_1_declaration_checkbox_ui tests.test_stage72_governed_pathway tests.test_stage73_governed_determination_publication tests.test_stage74_governed_characterisations tests.test_stage75_governed_report_generation_ui tests.test_stage75_governed_report_qualifications tests.test_stage75_governed_reports tests.test_stage76_adapter_result_contract tests.test_stage76_adapter_synthetic_gate tests.test_stage76_governed_pdf_reports tests.test_stage77_diagnostic_propagation tests.test_stage77_diagnostic_retry tests.test_stage77_governed_report_jobs tests.test_stage77_post_correction_generation tests.test_stage77_recovery tests.test_stage77_runtime_start tests.test_stage78a_pathway_projection tests.test_stage78b_pathway_report_rendering tests.test_stage78b_pathway_report_specification tests.test_streaming_mbox_ingestion tests.test_streaming_mbox_large_message_support tests.test_unified_attachment_governance
""".split()
).union({
    "tests.test_canonical_public_origin",
    "tests.test_run_governed_test_suite",
    "tests.test_stage78b_pathway_output_equivalence",
})
REAL_ASGI_MODULES = frozenset({"tests.test_canonical_public_origin"})
LEGACY_FASTAPI_STUB_MODULES = frozenset(
    """
tests.test_admin_audit_traceability tests.test_admin_console_navigation_and_table_readability tests.test_admin_document_intake tests.test_admin_navigation_console tests.test_admin_session tests.test_apple_emlx_support tests.test_archive_collection_membership_governance tests.test_archive_manifest tests.test_association_card_visual_refinement tests.test_association_public_traceability tests.test_attachment_audit_events tests.test_attachment_manifest tests.test_attachment_read_only_ui tests.test_attachment_upload tests.test_attachments tests.test_authoritative_source_visual_emphasis tests.test_canonical_record_from_published_document tests.test_canonical_record_types tests.test_collection_ordered_sequence_continuity tests.test_document_keywords tests.test_gmail_takeout_support tests.test_governed_archive_collections tests.test_governed_audio_artefact_support tests.test_governed_intake_corrections tests.test_governed_public_transmissions tests.test_governed_rich_text_format_artefact_support tests.test_governed_source_relationship_selection tests.test_governed_spreadsheet_artefact_support tests.test_imap_acquisition tests.test_machine_discoverability tests.test_mailbox_relationship_graph tests.test_mbox_archive_support tests.test_outlook_archive_attachment_governance tests.test_outlook_archive_governed_promotion tests.test_outlook_archive_intake_boundary tests.test_outlook_archive_jobs tests.test_outlook_archive_projection tests.test_outlook_msg_support tests.test_paste_json_analysis_flow tests.test_platform_identity_transition tests.test_public_archive_explorer tests.test_public_archive_ux_refinements tests.test_public_association_index tests.test_public_collection_pages tests.test_public_document_library tests.test_public_document_preview_enhancements tests.test_public_footer_administration_link tests.test_public_navigation_completion tests.test_public_navigation_information_architecture tests.test_public_record_document_association tests.test_public_traceability_map tests.test_record_document_association_record_selection tests.test_record_document_association_searchable_record_selection tests.test_record_synthetic_attachment_audit_event tests.test_rfc5322_eml_support tests.test_stage49_email_attachment_preservation tests.test_stage51_outlook_msg_attachment_preservation tests.test_stage52_apple_emlx_attachment_preservation tests.test_stage53_1_mailbox_attachment_relationship_navigation tests.test_stage53_mbox_attachment_preservation tests.test_stage54_apple_mail_mailbox_relationship_projection_and_navigation tests.test_stage55_attachment_published_document_source_context_and_navigation tests.test_stage56_durable_document_lifecycle_decision_record tests.test_stage57_governed_lifecycle_decision_confirmation tests.test_stage58_governed_document_reconsideration_and_lifecycle_episodes tests.test_stage59_lifecycle_episode_presentation tests.test_stage61_1_relationship_decision_admin_inspection tests.test_stage61_2_relationship_corrections tests.test_stage62_governed_pattern_observation tests.test_stage63_governed_inference tests.test_stage64_governed_allegation tests.test_stage65_governed_response tests.test_stage72_1_declaration_checkbox_ui tests.test_stage74_governed_characterisations tests.test_stage75_governed_report_generation_ui tests.test_stage75_governed_reports tests.test_streaming_mbox_ingestion tests.test_streaming_mbox_large_message_support
""".split()
)
EXCLUDED_UNTRACKED_MODULES = frozenset()
PYTEST_MODULES = frozenset({"tests.test_stage71_1_procedural_time_ui"})


class ManifestError(RuntimeError):
    pass


@dataclass(frozen=True)
class Entry:
    module: str
    classification: str
    framework: str


def repository_root() -> Path:
    return Path(__file__).resolve().parent.parent


def module_path(root: Path, module: str) -> Path:
    if not MODULE_RE.fullmatch(module):
        raise ManifestError("manifest_module_invalid")
    path = (root / (module.replace(".", "/") + ".py")).resolve()
    try:
        path.relative_to(root.resolve() / "tests")
    except ValueError as exc:
        raise ManifestError("manifest_path_escape") from exc
    return path


def classification_for(module: str) -> str:
    if module in REAL_ASGI_MODULES:
        return "real_asgi"
    if module in LEGACY_FASTAPI_STUB_MODULES:
        return "legacy_fastapi_stub"
    return "neutral"


def framework_for(module: str) -> str:
    return "pytest" if module in PYTEST_MODULES else "unittest"


def manifest_entries(modules: Iterable[str]) -> tuple[Entry, ...]:
    entries = tuple(Entry(module, classification_for(module), framework_for(module)) for module in modules)
    names = [entry.module for entry in entries]
    if len(names) != len(set(names)):
        raise ManifestError("manifest_duplicate_module")
    if not REAL_ASGI_MODULES.isdisjoint(LEGACY_FASTAPI_STUB_MODULES):
        raise ManifestError("manifest_cross_partition_duplicate")
    if any(entry.classification not in CLASSIFICATIONS for entry in entries):
        raise ManifestError("manifest_classification_invalid")
    return tuple(sorted(entries, key=lambda entry: entry.module))


def validate_source_framework(root: Path, entry: Entry) -> None:
    source = ast.parse(module_path(root, entry.module).read_text(), filename=entry.module)
    top_level_pytest = any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_") for node in source.body)
    pytest_classes = any(
        isinstance(node, ast.ClassDef)
        and node.name.startswith("Test")
        and any(
            isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)) and method.name.startswith("test_")
            for method in node.body
        )
        for node in source.body
    )
    # A governed unittest class may inherit a repository test base rather than
    # spelling ``unittest.TestCase`` directly.  A test-bearing class with a
    # declared base is therefore a statically identifiable unittest shape;
    # base-less Test* classes remain pytest-only and are rejected above.
    unittest_classes = any(
        isinstance(node, ast.ClassDef)
        and bool(node.bases)
        and any(
            isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)) and method.name.startswith("test_")
            for method in node.body
        )
        for node in source.body
    )
    if entry.framework not in FRAMEWORKS:
        raise ManifestError(f"manifest_framework_invalid:{entry.module}")
    if (top_level_pytest or pytest_classes) and entry.framework != "pytest":
        raise ManifestError(f"manifest_framework_source_mismatch:{entry.module}")
    if entry.framework == "pytest" and not (top_level_pytest or pytest_classes):
        raise ManifestError(f"manifest_framework_source_mismatch:{entry.module}")
    if entry.framework == "unittest" and not unittest_classes:
        raise ManifestError(f"manifest_framework_no_tests:{entry.module}")


def git_test_modules(root: Path, args: Sequence[str]) -> set[str]:
    result = subprocess.run(list(args), cwd=root, shell=False, capture_output=True, text=True, check=False)
    if result.returncode:
        raise ManifestError("manifest_git_inventory_failed")
    modules = set()
    for value in result.stdout.splitlines():
        if value.startswith("tests/test_") and value.endswith(".py"):
            modules.add("tests." + value[6:-3].replace("/", "."))
    return modules


def governed_entries(root: Path, *, tracked: set[str] | None = None, untracked: set[str] | None = None) -> tuple[tuple[Entry, ...], tuple[str, ...]]:
    tracked = tracked if tracked is not None else git_test_modules(root, ["git", "ls-files", "--", "tests"])
    untracked = untracked if untracked is not None else git_test_modules(root, ["git", "ls-files", "--others", "--exclude-standard", "--", "tests"])
    expected = set(GOVERNED_TRACKED_MODULES)
    if tracked != set(GOVERNED_TRACKED_MODULES):
        raise ManifestError("manifest_tracked_inventory_mismatch")
    unknown = untracked - set(EXCLUDED_UNTRACKED_MODULES)
    if unknown:
        raise ManifestError("manifest_unclassified_untracked_test")
    modules = expected
    entries = manifest_entries(modules)
    if {entry.module for entry in entries} != modules:
        raise ManifestError("manifest_missing_entry")
    for entry in entries:
        if not module_path(root, entry.module).is_file():
            raise ManifestError("manifest_module_missing")
        validate_source_framework(root, entry)
    return entries, tuple(sorted(untracked & set(EXCLUDED_UNTRACKED_MODULES)))


def run_suite(root: Path, entries: Sequence[Entry], *, dry_run: bool, run_process: Callable[..., object] = subprocess.run, output: Callable[[str], None] = print) -> int:
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    if dry_run:
        for ordinal, entry in enumerate(entries, 1):
            target = entry.module.replace(".", "/") + ".py" if entry.framework == "pytest" else entry.module
            output(f"[{ordinal}/{len(entries)}] {entry.classification} {entry.framework} {entry.module} target={target}")
        output(f"dry-run modules={len(entries)}")
        return 0
    for ordinal, entry in enumerate(entries, 1):
        target = entry.module.replace(".", "/") + ".py" if entry.framework == "pytest" else entry.module
        command = [sys.executable, str(root / "scripts" / "run_isolated_tests.py"), entry.framework, target]
        try:
            result = run_process(command, cwd=str(root), env=environment, shell=False, check=False)
            status = getattr(result, "returncode", None)
        except BaseException:
            output(f"[{ordinal}/{len(entries)}] {entry.classification} {entry.module} status={ORCHESTRATOR_STATUS}")
            return ORCHESTRATOR_STATUS
        if not isinstance(status, int):
            output(f"[{ordinal}/{len(entries)}] {entry.classification} {entry.module} status={ORCHESTRATOR_STATUS}")
            return ORCHESTRATOR_STATUS
        output(f"[{ordinal}/{len(entries)}] {entry.classification} {entry.module} status={status}")
        if status:
            output(f"final passed_modules={ordinal - 1} failed_modules=1")
            return status if status != CONTAINMENT_STATUS else CONTAINMENT_STATUS
    output(f"final passed_modules={len(entries)} failed_modules=0")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest-check", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    options = parser.parse_args(argv)
    try:
        entries, excluded = governed_entries(repository_root())
    except ManifestError as exc:
        print(str(exc), file=sys.stderr)
        return ORCHESTRATOR_STATUS
    if options.manifest_check:
        counts = {classification: sum(entry.classification == classification for entry in entries) for classification in sorted(CLASSIFICATIONS)}
        print(
            f"manifest-check modules={len(entries)} real_asgi={counts['real_asgi']} "
            f"legacy_fastapi_stub={counts['legacy_fastapi_stub']} neutral={counts['neutral']} "
            f"excluded_untracked={len(excluded)}"
        )
        return 0
    return run_suite(repository_root(), entries, dry_run=options.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
