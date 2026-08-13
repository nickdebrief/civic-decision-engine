from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


PIPELINE_DIR = Path(__file__).resolve().parents[1] / "scripts" / "evidence_led_governance_pipeline"
sys.path.insert(0, str(PIPELINE_DIR))

from build import _pdf_validation_report_lines  # noqa: E402
from model import Book  # noqa: E402
from output_validation import (  # noqa: E402
    EquivalenceAudit,
    PdfAudit,
    audit_pdf,
    extract_pdf_text,
    extract_pdf_text_result,
    normalize_text,
    pdf_block_matches,
    PdfTextExtraction,
    validate_cross_format_equivalence,
    validate_pdf_output,
)


class FakePage:
    mediabox = SimpleNamespace(width=612, height=792)

    def __init__(self, text: str) -> None:
        self.text = text

    def extract_text(self) -> str:
        return self.text


def unavailable_import(_name: str):
    raise ModuleNotFoundError


class PortablePdfValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.pdf = Path(self.temporary.name) / "publication.pdf"
        self.pdf.write_bytes(b"%PDF-1.4\nportable validation fixture\n%%EOF\n")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def pdf_extraction(raw: str) -> PdfTextExtraction:
        return PdfTextExtraction(
            text=normalize_text(raw),
            raw_text=raw,
            status="available",
            backend="fixture",
        )

    def test_pdf_equivalence_removes_generated_running_header(self) -> None:
        block = "The paragraph continues across a page boundary."
        raw = "The paragraph continues across a page boundary."
        with_header = raw.replace(
            "across",
            "across\nStructured · Traceable · Governed · 77 EVIDENCE-LED GOVERNANCE\n",
        )
        self.assertTrue(pdf_block_matches(block, self.pdf_extraction(with_header)))

    def test_pdf_equivalence_reconstructs_line_break_hyphenation(self) -> None:
        block = "The complaint-investigation record remains traceable."
        raw = "The complaint-\ninvestigation record remains traceable."
        self.assertTrue(pdf_block_matches(block, self.pdf_extraction(raw)))

    def test_pdf_equivalence_handles_header_and_hyphenation_together(self) -> None:
        block = "The complaint-investigation record remains traceable."
        raw = "The complaint-\nStructured · Traceable · Governed · 77 EVIDENCE-LED GOVERNANCE\ninvestigation record remains traceable."
        self.assertTrue(pdf_block_matches(block, self.pdf_extraction(raw)))

    def test_pdf_equivalence_rejects_missing_changed_and_inserted_text(self) -> None:
        block = "The complaint-investigation record remains traceable."
        cases = (
            "The complaint-investigation record remains.",
            "The complaint-review record remains traceable.",
            "The complaint-investigation unrelated record remains traceable.",
        )
        for raw in cases:
            with self.subTest(raw=raw):
                self.assertFalse(pdf_block_matches(block, self.pdf_extraction(raw)))

    def test_pdftotext_remains_the_preferred_backend(self) -> None:
        completed = subprocess.CompletedProcess([], 0, stdout="Preferred PDF text", stderr="")
        with (
            patch("output_validation.discover_tool", return_value=Path("/usr/bin/pdftotext")),
            patch("output_validation.subprocess.run", return_value=completed) as run,
            patch("output_validation.importlib.import_module") as import_module,
        ):
            extraction = extract_pdf_text_result(self.pdf)
        self.assertEqual(extraction.backend, "pdftotext")
        self.assertEqual(extraction.text, "Preferred PDF text")
        run.assert_called_once()
        self.assertIn("-layout", run.call_args.args[0])
        import_module.assert_not_called()

    def test_available_pdftotext_failure_preserves_existing_error_behaviour(self) -> None:
        completed = subprocess.CompletedProcess([], 1, stdout="", stderr="damaged PDF")
        with (
            patch("output_validation.discover_tool", return_value=Path("/usr/bin/pdftotext")),
            patch("output_validation.subprocess.run", return_value=completed),
        ):
            with self.assertRaisesRegex(RuntimeError, "damaged PDF"):
                extract_pdf_text_result(self.pdf)

    def test_pypdf_is_used_when_pdftotext_is_unavailable(self) -> None:
        reader = SimpleNamespace(
            pages=[FakePage("Portable pypdf text")],
            metadata=SimpleNamespace(title="Portable publication"),
        )
        pypdf = SimpleNamespace(PdfReader=lambda _path: reader)
        with (
            patch("output_validation.discover_tool", return_value=None),
            patch("output_validation.importlib.import_module", return_value=pypdf) as importer,
        ):
            extraction = extract_pdf_text_result(self.pdf)
        self.assertEqual(extraction.backend, "pypdf")
        self.assertEqual(extraction.text, "Portable pypdf text")
        self.assertEqual(extraction.page_count, 1)
        self.assertEqual(extraction.title, "Portable publication")
        importer.assert_called_once_with("pypdf")

    def test_pypdf_also_supplies_portable_structural_metadata(self) -> None:
        reader = SimpleNamespace(
            pages=[FakePage("Portable pypdf text")],
            metadata=SimpleNamespace(title="Portable publication"),
        )
        pypdf = SimpleNamespace(PdfReader=lambda _path: reader)
        with (
            patch("output_validation.discover_tool", return_value=None),
            patch("output_validation.importlib.import_module", return_value=pypdf),
        ):
            audit = audit_pdf(self.pdf)
        self.assertTrue(audit.inspection_available)
        self.assertEqual(audit.page_count, 1)
        self.assertEqual((audit.width_points, audit.height_points), (612, 792))
        self.assertEqual(audit.title, "Portable publication")

    def test_pdfminer_is_used_after_pypdf_is_unavailable(self) -> None:
        pdfminer = SimpleNamespace(extract_text=lambda _path: "Portable pdfminer text")

        def modules(name: str):
            if name == "pypdf":
                raise ModuleNotFoundError
            if name == "pdfminer.high_level":
                return pdfminer
            raise AssertionError(name)

        with (
            patch("output_validation.discover_tool", return_value=None),
            patch("output_validation.importlib.import_module", side_effect=modules),
        ):
            extraction = extract_pdf_text_result(self.pdf)
        self.assertEqual(extraction.backend, "pdfminer.six")
        self.assertEqual(extraction.text, "Portable pdfminer text")
        self.assertEqual(
            extraction.attempts,
            (
                ("pdftotext", "not found"),
                ("pypdf", "module unavailable"),
                ("pdfminer.six", "available"),
            ),
        )

    def test_no_backend_returns_empty_unavailable_result(self) -> None:
        with (
            patch("output_validation.discover_tool", return_value=None),
            patch("output_validation.importlib.import_module", side_effect=unavailable_import),
        ):
            extraction = extract_pdf_text_result(self.pdf)
            text = extract_pdf_text(self.pdf)
        self.assertFalse(extraction.available)
        self.assertEqual(extraction.text, "")
        self.assertEqual(text, "")
        self.assertEqual(
            extraction.reason,
            "No supported PDF text extraction backend was available.",
        )

    def test_unavailable_pdf_validation_and_equivalence_are_skipped(self) -> None:
        book = Book(title="Publication", author="Researcher")
        effective = SimpleNamespace(
            page=SimpleNamespace(width_inches=8.5, height_inches=11)
        )
        with (
            patch("output_validation.discover_tool", return_value=None),
            patch("output_validation.importlib.import_module", side_effect=unavailable_import),
        ):
            pdf_validation, pdf_audit = validate_pdf_output(self.pdf, book, effective)
        self.assertTrue(pdf_validation.ok)
        self.assertEqual(pdf_audit.validation_status, "unavailable")

        with (
            patch("output_validation.docx_text", return_value=("Body evidence", 1, 0)),
            patch("output_validation.source_text_blocks", return_value=["Body evidence"]),
            patch("output_validation.discover_tool", return_value=None),
            patch("output_validation.importlib.import_module", side_effect=unavailable_import),
        ):
            result, audit = validate_cross_format_equivalence(
                book,
                docx_path=Path("publication.docx"),
                pdf_path=self.pdf,
            )
        self.assertTrue(result.ok)
        self.assertEqual(audit.pdf_status, "unavailable")
        self.assertEqual(audit.missing_pdf, [])

    def test_build_report_explains_unavailable_backend(self) -> None:
        attempts = (
            ("pdftotext", "not found"),
            ("pypdf", "module unavailable"),
            ("pdfminer.six", "module unavailable"),
        )
        pdf = PdfAudit(backend_attempts=attempts)
        equivalence = EquivalenceAudit(
            pdf_status="unavailable",
            pdf_reason="No supported PDF text extraction backend was available.",
            pdf_attempts=attempts,
        )
        report = "\n".join(_pdf_validation_report_lines(("docx", "pdf", "html"), pdf, equivalence))
        self.assertIn("PDF Validation", report)
        self.assertIn("Status: Unavailable", report)
        self.assertIn("✓ pdftotext\n✗ not found", report)
        self.assertIn("✓ pypdf\n✗ module unavailable", report)
        self.assertIn("✓ pdfminer.six\n✗ module unavailable", report)
        self.assertIn("PDF equivalence: Skipped", report)
        self.assertIn("Cross-format validation completed using available formats only.", report)


if __name__ == "__main__":
    unittest.main()
