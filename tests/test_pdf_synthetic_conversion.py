import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_pdf_synthetic_conversion.py"


def load_checker():
    spec = importlib.util.spec_from_file_location("check_pdf_synthetic_conversion", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class PdfSyntheticConversionTests(unittest.TestCase):
    def test_config_runs_diagnostic_then_synthetic_checker(self):
        config = json.loads((ROOT / "railway.json").read_text(encoding="utf-8"))
        self.assertEqual(config["deploy"]["preDeployCommand"], [
            "python scripts/check_pdf_runtime.py",
            "python scripts/check_pdf_synthetic_conversion.py",
        ])

    def test_marker_validation_rejects_omission_reordering_relabeling_and_extra_text(self):
        checker = load_checker()
        valid = "\n".join(checker.EXPECTED_MARKERS)
        checker.validate_extracted_text(valid)
        cases = {
            "omitted": valid.replace(checker.EXPECTED_MARKERS[2], ""),
            "reordered": "\n".join(reversed(checker.EXPECTED_MARKERS)),
            "changed_original_label": valid.replace("ORIGINAL_LANGUAGE:", "SOURCE_LANGUAGE:"),
            "changed_summary_label": valid.replace("ADMINISTRATIVE_SUMMARY:", "SUMMARY:"),
            "missing_qualification": valid.replace(checker.EXPECTED_MARKERS[3], ""),
            "unexpected_text": valid + "\nUNAPPROVED_TEXT",
        }
        for name, text in cases.items():
            with self.subTest(case=name):
                with self.assertRaises(checker.SyntheticCheckError):
                    checker.validate_extracted_text(text)

    def test_structure_rejects_missing_and_corrupt_pdf(self):
        checker = load_checker()
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp).resolve()
            with self.assertRaises(checker.SyntheticCheckError):
                checker.validate_pdf_structure(directory / "missing.pdf", temporary_directory=directory)
            corrupt = directory / "corrupt.pdf"
            corrupt.write_bytes(b"not pdf")
            with self.assertRaisesRegex(checker.SyntheticCheckError, "invalid_pdf_header"):
                checker.validate_pdf_structure(corrupt, temporary_directory=directory)

    def test_structure_rejects_zero_page_encrypted_oversized_and_symlinked_pdf(self):
        checker = load_checker()
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp).resolve()
            pdf = directory / "synthetic.pdf"
            pdf.write_bytes(b"%PDF-1.7\n")
            fake = SimpleNamespace(is_encrypted=False, pages=[], attachments={}, metadata={})
            with patch.dict(sys.modules, {"pypdf": SimpleNamespace(PdfReader=lambda *_args, **_kwargs: fake)}):
                with self.assertRaisesRegex(checker.SyntheticCheckError, "unexpected_page_count"):
                    checker.validate_pdf_structure(pdf, temporary_directory=directory)
                fake.is_encrypted = True
                fake.pages = [SimpleNamespace(get=lambda _key: None)]
                with self.assertRaisesRegex(checker.SyntheticCheckError, "encrypted_pdf"):
                    checker.validate_pdf_structure(pdf, temporary_directory=directory)
            oversized = directory / "oversized.pdf"
            with oversized.open("wb") as handle:
                handle.truncate(checker.MAX_PDF_BYTES + 1)
            with self.assertRaisesRegex(checker.SyntheticCheckError, "pdf_size_out_of_bounds"):
                checker.validate_pdf_structure(oversized, temporary_directory=directory)
            target = directory / "target.pdf"
            target.write_bytes(b"%PDF-1.7\n")
            link = directory / "link.pdf"
            link.symlink_to(target)
            with self.assertRaisesRegex(checker.SyntheticCheckError, "pdf_missing_or_symlinked"):
                checker.validate_pdf_structure(link, temporary_directory=directory)

    def test_structure_rejects_metadata_paths_attachments_annotations_and_outside_output(self):
        checker = load_checker()

        class Page:
            def __init__(self, annotations=None):
                self.annotations = annotations

            def get(self, key):
                return self.annotations if key == "/Annots" else None

        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp).resolve()
            pdf = directory / "synthetic.pdf"
            pdf.write_bytes(b"%PDF-1.7\n")
            fake_reader = SimpleNamespace(is_encrypted=False, pages=[Page()], attachments={}, metadata={"/Title": "/data/private"})
            with patch.dict(sys.modules, {"pypdf": SimpleNamespace(PdfReader=lambda *_args, **_kwargs: fake_reader)}):
                with self.assertRaisesRegex(checker.SyntheticCheckError, "private_metadata_detected"):
                    checker.validate_pdf_structure(pdf, temporary_directory=directory)
                fake_reader.metadata = {}
                fake_reader.attachments = {"secret": [b"x"]}
                with self.assertRaisesRegex(checker.SyntheticCheckError, "unexpected_attachment_or_annotation"):
                    checker.validate_pdf_structure(pdf, temporary_directory=directory)
                fake_reader.attachments = {}
                fake_reader.pages = [Page(annotations=["annotation"])]
                with self.assertRaisesRegex(checker.SyntheticCheckError, "unexpected_attachment_or_annotation"):
                    checker.validate_pdf_structure(pdf, temporary_directory=directory)
                outside = Path(tempfile.mkdtemp()) / "outside.pdf"
                outside.write_bytes(b"%PDF-1.7\n")
                try:
                    with self.assertRaisesRegex(checker.SyntheticCheckError, "pdf_outside_temporary_directory"):
                        checker.validate_pdf_structure(outside, temporary_directory=directory)
                finally:
                    outside.unlink()
                    outside.parent.rmdir()

    def test_missing_tools_and_wrong_pypdf_fail_closed(self):
        checker = load_checker()
        with patch.object(checker.shutil, "which", return_value=None):
            with self.assertRaisesRegex(checker.SyntheticCheckError, "libreoffice_missing"):
                checker.run_check()
        with patch.object(checker.shutil, "which", side_effect=lambda command: "/usr/bin/" + command):
            with patch.object(checker, "_version", return_value="version"):
                with patch.dict(sys.modules, {"pypdf": type("Pypdf", (), {"__version__": "wrong"})()}):
                    with self.assertRaisesRegex(checker.SyntheticCheckError, "pypdf_version_mismatch"):
                        checker.run_check()

    def test_missing_poppler_tools_fail_closed(self):
        checker = load_checker()
        for missing in ("pdfinfo", "pdftotext"):
            with self.subTest(missing=missing):
                def locate(command, missing=missing):
                    return None if command == missing else "/usr/bin/" + command

                with patch.object(checker.shutil, "which", side_effect=locate):
                    with patch.object(checker, "_version", return_value="version"):
                        with patch.dict(sys.modules, {"pypdf": SimpleNamespace(__version__="5.9.0")}):
                            with self.assertRaisesRegex(checker.SyntheticCheckError, missing + "_missing"):
                                checker.run_check()

    def test_libreoffice_version_failure_is_fail_closed(self):
        checker = load_checker()
        with patch.object(checker.shutil, "which", side_effect=lambda command: "/usr/bin/" + command):
            with patch.object(checker, "_version", side_effect=checker.SyntheticCheckError("version_failed:libreoffice")):
                with self.assertRaisesRegex(checker.SyntheticCheckError, "version_failed"):
                    checker.run_check()

    def test_command_failures_and_timeouts_are_safe(self):
        checker = load_checker()
        with patch.object(checker.subprocess, "run", side_effect=subprocess.TimeoutExpired("tool", 1)):
            with self.assertRaisesRegex(checker.SyntheticCheckError, "command_failed"):
                checker._run(["tool"])
        with patch.object(checker.subprocess, "run", return_value=type("Result", (), {"returncode": 1, "stdout": "", "stderr": "failure"})()):
            with self.assertRaisesRegex(checker.SyntheticCheckError, "version_failed"):
                checker._version("tool")

    def test_total_deadline_is_enforced(self):
        checker = load_checker()
        with self.assertRaisesRegex(checker.SyntheticCheckError, "total_timeout"):
            checker._run(["tool"], deadline=0)

    def test_conversion_failure_cleans_the_temporary_directory(self):
        checker = load_checker()
        holder, directory = checker._temporary_directory()
        try:
            with patch.object(checker.shutil, "which", side_effect=lambda command: "/usr/bin/" + command):
                with patch.object(checker, "_version", return_value="version"):
                    with patch.object(checker, "_temporary_directory", return_value=(holder, directory)):
                        with patch.object(checker, "_create_docx"):
                            with patch.object(checker, "_run", return_value=SimpleNamespace(returncode=1, stdout="", stderr="")):
                                with patch.dict(sys.modules, {"pypdf": SimpleNamespace(__version__="5.9.0")}):
                                    with self.assertRaisesRegex(checker.SyntheticCheckError, "conversion_failed"):
                                        checker.run_check()
            self.assertFalse(directory.exists())
        finally:
            if directory.exists():
                holder.cleanup()

    def test_read_only_application_paths_do_not_import_or_execute_checker(self):
        main_source = (ROOT / "api" / "main.py").read_text(encoding="utf-8")
        route_source = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "api" / "routes").glob("*.py"))
        self.assertNotIn("check_pdf_synthetic_conversion", main_source)
        self.assertNotIn("check_pdf_synthetic_conversion", route_source)

    def test_script_does_not_import_application_or_read_data(self):
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("api.main", source)
        self.assertNotIn("sqlite3", source)
        self.assertNotIn("RECORDS_DB_PATH", source)
        self.assertNotIn('Path("/data").read', source)

    def test_local_checker_fails_closed_without_claiming_success(self):
        completed = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True, check=False)
        if completed.returncode != 0:
            report = json.loads(completed.stdout)
            self.assertEqual(report["checker"], "failed")
        else:
            self.assertIn('"checker": "ok"', completed.stdout)


if __name__ == "__main__":
    unittest.main()
