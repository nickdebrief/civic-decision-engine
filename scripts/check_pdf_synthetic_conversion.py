#!/usr/bin/env python3
"""Fail-closed synthetic PDF capability check for Railway pre-deploy."""

from __future__ import annotations

import json
import getpass
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


MAX_PDF_BYTES = 10 * 1024 * 1024
COMMAND_TIMEOUT_SECONDS = 60
TOTAL_TIMEOUT_SECONDS = 180
EXPECTED_MARKERS = (
    "STAGE76_SYNTHETIC_BEGIN",
    "ORIGINAL_LANGUAGE: This is synthetic capability-test wording.",
    "ADMINISTRATIVE_SUMMARY: This summary is synthetic and separately labelled.",
    "QUALIFICATION: Generation is not publication.",
    "LIMITATION: This synthetic check does not establish Stage 76 readiness.",
    "STAGE76_SYNTHETIC_END",
)


class SyntheticCheckError(RuntimeError):
    """A safe, non-sensitive synthetic capability failure."""


def _run(command: list[str], *, timeout: int = COMMAND_TIMEOUT_SECONDS, deadline: float | None = None) -> subprocess.CompletedProcess[str]:
    if deadline is not None and deadline <= time.monotonic():
        raise SyntheticCheckError("total_timeout")
    if deadline is not None:
        timeout = min(timeout, max(1, int(deadline - time.monotonic())))
    try:
        return subprocess.run(command, check=False, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired, UnicodeError) as exc:
        raise SyntheticCheckError(f"command_failed:{type(exc).__name__}") from None


def _version(command: str, argument: str = "--version", *, deadline: float | None = None) -> str:
    result = _run([command, argument], deadline=deadline)
    if result.returncode != 0:
        raise SyntheticCheckError(f"version_failed:{command}")
    output = (result.stdout or result.stderr).strip()
    if not output:
        raise SyntheticCheckError(f"version_empty:{command}")
    return output.splitlines()[0][:512]


def _temporary_directory() -> tuple[tempfile.TemporaryDirectory[str], Path]:
    root = Path(tempfile.gettempdir()).resolve()
    data_root = Path("/data").resolve()
    if data_root.exists() and (root == data_root or root in data_root.parents or data_root in root.parents):
        raise SyntheticCheckError("temporary_root_overlaps_data")
    holder = tempfile.TemporaryDirectory(prefix="stage76-synthetic-pdf-")
    try:
        directory = Path(holder.name)
        resolved = directory.resolve()
        if directory.is_symlink() or resolved.parent != root:
            raise SyntheticCheckError("temporary_directory_not_confined")
        if resolved in {Path("/"), root, Path.home().resolve(), Path.cwd().resolve()}:
            raise SyntheticCheckError("unsafe_temporary_directory")
        if any(resolved.iterdir()):
            raise SyntheticCheckError("temporary_directory_not_empty")
        return holder, resolved
    except Exception:
        holder.cleanup()
        raise


def _create_docx(path: Path) -> None:
    try:
        from docx import Document
    except Exception:
        raise SyntheticCheckError("python_docx_unavailable") from None
    document = Document()
    for marker in EXPECTED_MARKERS:
        document.add_paragraph(marker)
    document.core_properties.title = "Stage 76 synthetic capability check"
    document.core_properties.author = "CDE runtime check"
    document.save(path)


def validate_extracted_text(text: str) -> None:
    positions: list[int] = []
    for marker in EXPECTED_MARKERS:
        if text.count(marker) != 1:
            raise SyntheticCheckError("ordered_content_mismatch")
        positions.append(text.index(marker))
    if positions != sorted(positions):
        raise SyntheticCheckError("ordered_content_mismatch")
    nonempty_lines = [line.strip() for line in text.splitlines() if line.strip()]
    if nonempty_lines != list(EXPECTED_MARKERS):
        raise SyntheticCheckError("unexpected_text")


def _metadata_text(reader: Any) -> str:
    metadata = reader.metadata
    if not metadata:
        return ""
    return "\n".join(f"{key}={value}" for key, value in metadata.items())


def validate_pdf_structure(pdf_path: Path, *, temporary_directory: Path) -> int:
    # This gate validates the toolchain on its own synthetic output; the governed
    # adapter owns the complete action-tree policy for report PDFs.
    if not pdf_path.is_file() or pdf_path.is_symlink():
        raise SyntheticCheckError("pdf_missing_or_symlinked")
    if pdf_path.resolve().parent != temporary_directory:
        raise SyntheticCheckError("pdf_outside_temporary_directory")
    size = pdf_path.stat().st_size
    if size <= 0 or size > MAX_PDF_BYTES:
        raise SyntheticCheckError("pdf_size_out_of_bounds")
    if pdf_path.read_bytes()[:5] != b"%PDF-":
        raise SyntheticCheckError("invalid_pdf_header")
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(pdf_path), strict=True)
    except Exception:
        raise SyntheticCheckError("pdf_parse_failed") from None
    if reader.is_encrypted:
        raise SyntheticCheckError("encrypted_pdf")
    if len(reader.pages) != 1:
        raise SyntheticCheckError("unexpected_page_count")
    if getattr(reader, "attachments", {}) or any(page.get("/Annots") for page in reader.pages):
        raise SyntheticCheckError("unexpected_attachment_or_annotation")
    metadata = _metadata_text(reader)
    forbidden = (str(temporary_directory), "/app", "/data", str(Path.home()), getpass.getuser(), socket.gethostname(), "PRIVATE_CANARY", "SECRET")
    if any(value and value.lower() in metadata.lower() for value in forbidden):
        raise SyntheticCheckError("private_metadata_detected")
    return size


def _pdfinfo_page_count(output: str) -> int:
    match = re.search(r"^Pages:\s*(\d+)\s*$", output, re.MULTILINE)
    if not match:
        raise SyntheticCheckError("pdfinfo_page_count_missing")
    return int(match.group(1))


def run_check() -> dict[str, Any]:
    deadline = time.monotonic() + TOTAL_TIMEOUT_SECONDS
    libreoffice = shutil.which("libreoffice") or shutil.which("soffice")
    if not libreoffice:
        raise SyntheticCheckError("libreoffice_missing")
    libreoffice_version = _version(libreoffice, deadline=deadline)
    pdfinfo = shutil.which("pdfinfo")
    pdftotext = shutil.which("pdftotext")
    if not pdfinfo:
        raise SyntheticCheckError("pdfinfo_missing")
    if not pdftotext:
        raise SyntheticCheckError("pdftotext_missing")
    pdfinfo_version = _version(pdfinfo, "-v", deadline=deadline)
    pdftotext_version = _version(pdftotext, "-v", deadline=deadline)
    try:
        import pypdf
    except Exception:
        raise SyntheticCheckError("pypdf_missing") from None
    if getattr(pypdf, "__version__", None) != "5.9.0":
        raise SyntheticCheckError("pypdf_version_mismatch")

    holder, directory = _temporary_directory()
    try:
        docx_path = directory / "stage76_synthetic.docx"
        pdf_path = directory / "stage76_synthetic.pdf"
        text_path = directory / "stage76_synthetic.txt"
        _create_docx(docx_path)
        if time.monotonic() >= deadline:
            raise SyntheticCheckError("total_timeout")
        converted = _run([libreoffice, "--headless", "--convert-to", "pdf", "--outdir", str(directory), str(docx_path)], deadline=deadline)
        if converted.returncode != 0 or not pdf_path.is_file():
            raise SyntheticCheckError("conversion_failed")
        extracted = _run([pdftotext, "-layout", str(pdf_path), str(text_path)], deadline=deadline)
        if extracted.returncode != 0 or not text_path.is_file():
            raise SyntheticCheckError("extraction_failed")
        validate_extracted_text(text_path.read_text(encoding="utf-8"))
        size = validate_pdf_structure(pdf_path, temporary_directory=directory)
        info = _run([pdfinfo, str(pdf_path)], deadline=deadline)
        if info.returncode != 0:
            raise SyntheticCheckError("pdfinfo_failed")
        pages = _pdfinfo_page_count(info.stdout)
        if pages != 1:
            raise SyntheticCheckError("unexpected_page_count")
        return {
            "checker": "ok",
            "python": sys.version.split()[0],
            "libreoffice_executable": Path(libreoffice).name,
            "libreoffice_version": libreoffice_version,
            "pdfinfo_version": pdfinfo_version,
            "pdftotext_version": pdftotext_version,
            "pypdf_version": pypdf.__version__,
            "page_count": pages,
            "pdf_bytes": size,
            "ordered_content": "ok",
            "metadata_attachments_annotations": "ok",
            "cleanup": "pending",
        }
    finally:
        holder.cleanup()
        if directory.exists():
            raise SyntheticCheckError("temporary_cleanup_failed")


def main() -> int:
    try:
        result = run_check()
        result["cleanup"] = "ok"
        print(json.dumps(result, sort_keys=True))
        return 0
    except SyntheticCheckError as exc:
        print(json.dumps({"checker": "failed", "reason": str(exc)}, sort_keys=True))
        return 1
    except Exception:
        print(json.dumps({"checker": "failed", "reason": "unexpected_failure"}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
