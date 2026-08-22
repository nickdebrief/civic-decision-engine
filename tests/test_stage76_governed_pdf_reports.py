import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from api import record_governed_reports as reports

PIPELINE = Path(__file__).parents[1] / "scripts" / "evidence_led_governance_pipeline"
if str(PIPELINE) not in sys.path:
    sys.path.insert(0, str(PIPELINE))

import report_adapter  # noqa: E402


class Stage76PdfContractTests(unittest.TestCase):
    def page(self, number=1):
        class Page(dict):
            pass
        class Reference:
            def __init__(self, value):
                self.value = value
                self.idnum = number
                self.generation = 0
            def get_object(self):
                return self.value
        page = Page()
        page.indirect_reference = Reference(page)
        return page

    def specification(self, formats=None):
        return {
            "specification_schema_version": reports.SPECIFICATION_SCHEMA_VERSION,
            "report_type": "canonical_record_report",
            "title": "Internal report",
            "purpose": "Review",
            "intended_audience": "Administrators",
            "distribution_class": "internal_working",
            "primary_record": {"reference": "CR-1", "title": "Record", "description": "Original wording", "status": "recorded"},
            "selected_documents": [],
            "selected_associations": [],
            "sections": [{"order": 0, "title": "Record", "blocks": [{"order": 0, "content_type": "verbatim_source", "text": "Original wording", "source_identity": {"object_kind": "canonical_record", "object_id": "CR-1"}, "attribution": "Source A", "inclusion_rationale": "Selected deliberately."}]}],
            "exclusions": [],
            "qualifications": [reports.BOUNDARY, "THE RECORD MUST PRESERVE THE ORIGINAL LANGUAGE."],
            "requested_formats": formats or ["docx", "html", "pdf"],
            "publication_engine_version": "2.0.0",
            "rendering_profile": "internal",
            "template_version": "cde-internal-v1",
        }

    def test_pdf_requires_docx_and_html_companions(self):
        specification = self.specification(["pdf"])
        with self.assertRaisesRegex(ValueError, "companion_formats_required"):
            reports._canonical_specification(
                record=specification["primary_record"], documents=[], associations=[], sections=specification["sections"], exclusions=[],
                title=specification["title"], purpose=specification["purpose"], audience=specification["intended_audience"],
                distribution_class="internal_working", requested_formats=["pdf"], rendering_profile="internal", template_version="v1",
            )

    def test_pdf_ordered_equivalence_rejects_omission_insertion_and_reordering(self):
        book = report_adapter.make_book(self.specification())
        expected = report_adapter.source_text_blocks(book)
        self.assertTrue(report_adapter._pdf_ordered_equivalence(book, "\n".join(expected)))
        self.assertFalse(report_adapter._pdf_ordered_equivalence(book, "\n".join(expected[:-1])))
        self.assertFalse(report_adapter._pdf_ordered_equivalence(book, "\n".join(reversed(expected))))
        self.assertFalse(report_adapter._pdf_ordered_equivalence(book, "\n".join(expected + ["UNAPPROVED INSERTION"])))

    def test_pdf_metadata_annotations_and_embedded_files_fail_closed(self):
        unsafe_metadata = SimpleNamespace(metadata={"/Author": "/data/private"}, trailer={})
        self.assertFalse(report_adapter._pdf_metadata_is_safe(unsafe_metadata))
        annotated = SimpleNamespace(trailer={"/Annots": ["annotation"]})
        embedded = SimpleNamespace(trailer={"/EmbeddedFiles": ["attachment"]})
        action = SimpleNamespace(trailer={"/OpenAction": {"/URI": "https://example.invalid"}})
        self.assertTrue(report_adapter._pdf_has_unsafe_objects(annotated))
        self.assertTrue(report_adapter._pdf_has_unsafe_objects(embedded))
        self.assertTrue(report_adapter._pdf_has_unsafe_objects(action))

    def test_pdf_validation_requires_mandatory_tool_results_and_structure(self):
        book = report_adapter.make_book(self.specification())

        page = self.page()
        class Reader:
            is_encrypted = False
            pages = [page]
            metadata = {}
            trailer = {}

        fake_pypdf = SimpleNamespace(__version__="5.9.0", PdfReader=lambda _path, strict=True: Reader())
        with tempfile.TemporaryDirectory() as directory:
            pdf = Path(directory) / "report.pdf"
            pdf.write_bytes(b"%PDF-1.7\nsynthetic\n")

            def tool(tool, arguments, *, timeout, deadline=None):
                if tool == "pdfinfo" and arguments == ["-v"]:
                    return SimpleNamespace(stdout="pdfinfo version 25.03.0\n", stderr="", returncode=0)
                if tool == "pdfinfo":
                    return SimpleNamespace(stdout="Pages:           1\n", stderr="", returncode=0)
                Path(arguments[2]).write_text("\n".join(report_adapter.source_text_blocks(book)), encoding="utf-8")
                return SimpleNamespace(stdout="", stderr="", returncode=0)

            with patch.dict(sys.modules, {"pypdf": fake_pypdf}), patch.object(report_adapter, "_run_pdf_tool", side_effect=tool):
                diagnostics = report_adapter._validate_pdf(pdf, book)
            self.assertEqual(diagnostics["page_count"], 1)
            self.assertEqual(diagnostics["ordered_content"], "ok")

    def test_pdf_validation_rejects_private_path_or_canary_in_extracted_text(self):
        book = report_adapter.make_book(self.specification())

        page = self.page()
        class Reader:
            is_encrypted = False
            pages = [page]
            metadata = {}
            trailer = {}

        fake_pypdf = SimpleNamespace(__version__="5.9.0", PdfReader=lambda _path, strict=True: Reader())
        with tempfile.TemporaryDirectory() as directory:
            pdf = Path(directory) / "report.pdf"
            pdf.write_bytes(b"%PDF-1.7\n")

            def tool(tool, arguments, *, timeout, deadline=None):
                if tool == "pdfinfo" and arguments == ["-v"]:
                    return SimpleNamespace(stdout="pdfinfo version 25.03.0\n", stderr="", returncode=0)
                if tool == "pdfinfo":
                    return SimpleNamespace(stdout="Pages:           1\n", stderr="", returncode=0)
                Path(arguments[2]).write_text("/data/private_canary", encoding="utf-8")
                return SimpleNamespace(stdout="", stderr="", returncode=0)

            with patch.dict(sys.modules, {"pypdf": fake_pypdf}), patch.object(report_adapter, "_run_pdf_tool", side_effect=tool):
                with self.assertRaisesRegex(ValueError, "private_path_or_canary"):
                    report_adapter._validate_pdf(pdf, book)

    def test_pdf_validation_rejects_invalid_header_and_size(self):
        book = report_adapter.make_book(self.specification())
        with tempfile.TemporaryDirectory() as directory:
            invalid = Path(directory) / "invalid.pdf"
            invalid.write_bytes(b"not a pdf")
            with self.assertRaisesRegex(ValueError, "size_or_header_invalid"):
                report_adapter._validate_pdf(invalid, book)
            oversized = Path(directory) / "oversized.pdf"
            oversized.write_bytes(b"%PDF-1.7\n" + b"x" * (report_adapter.PDF_MAX_BYTES + 1))
            with self.assertRaisesRegex(ValueError, "size_or_header_invalid"):
                report_adapter._validate_pdf(oversized, book)

    def test_pdf_validation_rejects_encrypted_or_excessive_page_output(self):
        book = report_adapter.make_book(self.specification())
        with tempfile.TemporaryDirectory() as directory:
            pdf = Path(directory) / "report.pdf"
            pdf.write_bytes(b"%PDF-1.7\n")
            for encrypted, pages in ((True, [object()]), (False, [object()] * (report_adapter.PDF_MAX_PAGES + 1))):
                reader = SimpleNamespace(is_encrypted=encrypted, pages=pages, metadata={}, trailer={})
                fake_pypdf = SimpleNamespace(__version__="5.9.0", PdfReader=lambda _path, strict=True, reader=reader: reader)
                with patch.dict(sys.modules, {"pypdf": fake_pypdf}):
                    with self.assertRaisesRegex(ValueError, "encryption_or_page_limit_invalid"):
                        report_adapter._validate_pdf(pdf, book)

    def test_pdf_tool_timeout_and_failure_are_bounded(self):
        with patch.object(report_adapter, "discover_tool", return_value=Path("/usr/bin/tool")), patch("report_adapter.subprocess.run", side_effect=__import__("subprocess").TimeoutExpired("tool", 1)):
            with self.assertRaisesRegex(ValueError, "pdf_pdfinfo_timeout"):
                report_adapter._run_pdf_tool("pdfinfo", ["x"], timeout=1)
        failed = __import__("subprocess").CompletedProcess([], 1, stdout="", stderr="private path")
        with patch.object(report_adapter, "discover_tool", return_value=Path("/usr/bin/tool")), patch("report_adapter.subprocess.run", return_value=failed):
            with self.assertRaisesRegex(ValueError, "pdf_pdfinfo_failed"):
                report_adapter._run_pdf_tool("pdfinfo", ["x"], timeout=1)

    def test_pdf_tools_receive_only_remaining_overall_budget(self):
        completed = subprocess.CompletedProcess([], 0, stdout="Pages: 1\n", stderr="")
        with patch.object(report_adapter, "discover_tool", return_value=Path("/usr/bin/tool")), patch.object(report_adapter.time, "monotonic", return_value=100.0), patch("report_adapter.subprocess.run", return_value=completed) as run:
            report_adapter._run_pdf_tool("pdfinfo", ["x"], timeout=120, deadline=100.5)
        self.assertLessEqual(run.call_args.kwargs["timeout"], 0.5)

    def test_pdf_metadata_allowlist_rejects_unknown_and_wrong_identity(self):
        book = report_adapter.make_book(self.specification())
        self.assertTrue(report_adapter._pdf_metadata_is_safe(SimpleNamespace(metadata={"/Title": book.title, "/Author": "Civic Decision Engine"}), book))
        self.assertFalse(report_adapter._pdf_metadata_is_safe(SimpleNamespace(metadata={"/Custom": "value"}), book))
        self.assertFalse(report_adapter._pdf_metadata_is_safe(SimpleNamespace(metadata={"/Author": "reviewer"}), book))
        self.assertFalse(report_adapter._pdf_metadata_is_safe(SimpleNamespace(metadata={"/Title": "other"}), book))
        self.assertFalse(report_adapter._pdf_metadata_is_safe(SimpleNamespace(metadata={"/Producer": "untrusted renderer"}), book))
        self.assertFalse(report_adapter._pdf_metadata_is_safe(SimpleNamespace(metadata={"/Keywords": "private-canary"}), book))

    def test_realistic_libreoffice_252_metadata_is_allowed_and_optional_fields_may_be_absent(self):
        book = report_adapter.make_book(self.specification())
        metadata = {
            "/Title": book.title,
            "/Author": "Civic Decision Engine",
            "/Subject": "Internal governed report",
            "/Creator": "Writer",
            "/Producer": "LibreOffice 25.2.3.2",
            "/CreationDate": "D:20260822140000Z",
            "/ModDate": "D:20260822140000Z",
        }
        self.assertTrue(report_adapter._pdf_metadata_is_safe(SimpleNamespace(metadata=metadata), book))
        self.assertTrue(report_adapter._pdf_metadata_is_safe(SimpleNamespace(metadata={"/Title": book.title, "/Author": "Civic Decision Engine"}), book))

    def test_metadata_rejection_returns_only_bounded_field_and_reason(self):
        book = report_adapter.make_book(self.specification())
        cases = (
            ({"/Custom": "value"}, "unknown_key", "unexpected_key"),
            ({"/Title": "wrong title"}, "/Title", "identity_mismatch"),
            ({"/Author": "reviewer"}, "/Author", "identity_mismatch"),
            ({"/Producer": "private-canary"}, "/Producer", "forbidden_value"),
            ({"/Creator": 42}, "/Creator", "non_string_value"),
            ({"/Subject": "unapproved subject"}, "/Subject", "unexpected_value"),
        )
        for metadata, field, reason in cases:
            with self.subTest(field=field, reason=reason):
                failure = report_adapter._pdf_metadata_failure(SimpleNamespace(metadata=metadata), book)
                self.assertIsNotNone(failure)
                classified = report_adapter._classify_pdf_failure(failure)
                self.assertEqual((classified.phase, classified.code), ("pdf_inspection", "pdf_metadata_invalid"))
                self.assertEqual(classified.diagnostic, {"format": "pdf", "failure_field": field, "failure_reason": reason})

    def test_metadata_failure_does_not_expose_value_or_path(self):
        book = report_adapter.make_book(self.specification())
        failure = report_adapter._pdf_metadata_failure(SimpleNamespace(metadata={"/Producer": "/data/private-canary"}), book)
        classified = report_adapter._classify_pdf_failure(failure)
        self.assertEqual(classified.diagnostic, {"format": "pdf", "failure_field": "/Producer", "failure_reason": "forbidden_value"})

    def test_indirect_page_annotations_and_catalog_actions_fail_closed(self):
        class Indirect:
            def __init__(self, value):
                self.value = value
            def get_object(self):
                return self.value

        page = self.page()
        page["/Annots"] = Indirect([{ "/Subtype": "/Widget" }])
        reader = SimpleNamespace(trailer={"/Root": Indirect({"/Names": {"/EmbeddedFiles": []}})}, pages=[page])
        self.assertTrue(report_adapter._pdf_has_unsafe_objects(reader))

    def test_internal_fit_open_action_is_passive_and_structurally_confined(self):
        page = self.page()
        reader = SimpleNamespace(pages=[page], trailer={"/Root": {"/OpenAction": [page.indirect_reference, "/Fit"]}})
        self.assertFalse(report_adapter._pdf_has_unsafe_objects(reader))

    def test_action_diagnostics_distinguish_passive_destinations_from_actions(self):
        page = self.page()
        cases = (
            ({"/Root": {"/OpenAction": {"/S": "/URI", "/URI": "https://example.invalid"}}}, "catalog_open_action", "executable_action"),
            ({"/Root": {"/OpenAction": [page, "/FitH", 0]}}, "catalog_open_action", "malformed_destination"),
            ({"/Root": {"/OpenAction": [object(), "/Fit"]}}, "catalog_open_action", "unsupported_destination"),
            ({"/Root": {"/AA": {"/O": {"/S": "/JavaScript"}}}}, "catalog_additional_actions", "executable_action"),
            ({"/Root": {"/Outlines": [{"/A": {"/S": "/GoToR"}}]}}, "outline_action", "executable_action"),
        )
        for trailer, location, reason in cases:
            with self.subTest(location=location, reason=reason):
                reader = SimpleNamespace(pages=[page], trailer=trailer)
                failure = report_adapter._pdf_action_failure(reader)
                self.assertIsNotNone(failure)
                classified = report_adapter._classify_pdf_failure(failure)
                self.assertEqual(classified.diagnostic, {"format": "pdf", "failure_location": location, "failure_reason": reason})

    def test_indirect_destination_cycle_fails_closed(self):
        class Cycle:
            def get_object(self):
                return self

        page = self.page()
        reader = SimpleNamespace(pages=[page], trailer={"/Root": {"/OpenAction": Cycle()}})
        failure = report_adapter._pdf_action_failure(reader)
        self.assertEqual((failure.location, failure.reason), ("catalog_open_action", "indirect_cycle"))

    def test_all_executable_action_families_fail_closed(self):
        page = self.page()
        reader = SimpleNamespace(pages=[page], trailer={"/Root": {}})
        for key in ("/JavaScript", "/JS", "/Launch", "/URI", "/GoToR", "/SubmitForm", "/ImportData", "/Rendition", "/A"):
            with self.subTest(key=key):
                reader.trailer = {"/Root": {"/OpenAction": {"/S": key, key: "synthetic"}}}
                failure = report_adapter._pdf_action_failure(reader)
                self.assertEqual((failure.location, failure.reason), ("catalog_open_action", "executable_action"))

    def test_outline_internal_fit_destination_is_allowed_but_named_destination_is_not(self):
        page = self.page()
        valid = SimpleNamespace(pages=[page], trailer={"/Root": {"/Outlines": [{"/Dest": [page.indirect_reference, "/Fit"]}]}})
        self.assertFalse(report_adapter._pdf_has_unsafe_objects(valid))
        named = SimpleNamespace(pages=[page], trailer={"/Root": {"/OpenAction": "/FirstPage"}})
        failure = report_adapter._pdf_action_failure(named)
        self.assertEqual((failure.location, failure.reason), ("catalog_open_action", "external_destination"))

    def test_missing_pypdf_is_a_mandatory_failure(self):
        book = report_adapter.make_book(self.specification())
        with tempfile.TemporaryDirectory() as directory:
            pdf = Path(directory) / "report.pdf"
            pdf.write_bytes(b"%PDF-1.7\n")
            with patch.dict(sys.modules, {"pypdf": None}):
                with self.assertRaisesRegex(ValueError, "pdf_pypdf_unavailable"):
                    report_adapter._validate_pdf(pdf, book)


if __name__ == "__main__":
    unittest.main()
