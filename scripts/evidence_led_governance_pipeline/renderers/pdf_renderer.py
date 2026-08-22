"""Reliable DOCX-to-PDF rendering through headless LibreOffice."""

from __future__ import annotations

import os
import signal
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path


def discover_tool(name: str) -> Path | None:
    configured = os.environ.get(name.upper())
    if configured:
        path = Path(configured).expanduser()
        return path if path.is_file() else None
    located = shutil.which(name)
    if located:
        return Path(located)
    if name == "pdftotext":
        pdfinfo = shutil.which("pdfinfo")
        if pdfinfo:
            candidates = [
                Path(pdfinfo).parent / "../../native/poppler/bin/pdftotext",
                Path(pdfinfo).parent / "../../native/poppler/poppler/bin/pdftotext",
            ]
            for candidate in candidates:
                resolved = candidate.resolve()
                if resolved.is_file():
                    return resolved
    return None


def _usable_soffice(path: Path | None) -> bool:
    if path is None or not path.is_file() or not os.access(path, os.X_OK):
        return False
    try:
        result = subprocess.run(
            [str(path), "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired, UnicodeError):
        return False
    return result.returncode == 0 and bool((result.stdout or result.stderr).strip())


def discover_soffice() -> Path | None:
    """Select the first approved LibreOffice entry point that actually runs."""
    for name in ("soffice", "libreoffice"):
        candidate = discover_tool(name)
        if _usable_soffice(candidate):
            return candidate
    return None


@dataclass(frozen=True)
class PdfRenderResult:
    path: Path
    method: str
    renderer_version: str


class PdfRenderer:
    def __init__(self, soffice_path: Path | str | None = None) -> None:
        candidate = Path(soffice_path) if soffice_path is not None else discover_soffice()
        self.soffice_path = candidate if _usable_soffice(candidate) else None

    @property
    def available(self) -> bool:
        return bool(self.soffice_path and self.soffice_path.is_file())

    def version(self, *, deadline: float | None = None) -> str:
        if not self.available:
            return "unavailable"
        timeout = 30
        if deadline is not None:
            timeout = min(timeout, max(0.001, deadline - time.monotonic()))
        completed = subprocess.run(
            [str(self.soffice_path), "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if deadline is not None and completed.returncode != 0:
            raise RuntimeError("LibreOffice version command failed")
        return (completed.stdout or completed.stderr).strip() or "unknown"

    @staticmethod
    def _terminate_process_group(process: subprocess.Popen[str]) -> None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.communicate(timeout=5)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def render(self, source_docx: Path, output_pdf: Path, *, timeout: int = 300, deadline: float | None = None) -> PdfRenderResult:
        if not self.available:
            raise RuntimeError("LibreOffice executable not found; PDF rendering is unavailable")
        if not source_docx.is_file() or source_docx.stat().st_size == 0:
            raise ValueError(f"PDF source DOCX is missing or empty: {source_docx}")
        output_pdf.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="publication-pdf-", dir=output_pdf.parent) as temp:
            temp_dir = Path(temp)
            profile = temp_dir / "libreoffice-profile"
            profile.mkdir()
            command = [
                str(self.soffice_path),
                "--headless",
                f"-env:UserInstallation={profile.resolve().as_uri()}",
                "--convert-to",
                "pdf",
                "--outdir",
                str(temp_dir),
                str(source_docx),
            ]
            conversion_timeout = timeout
            if deadline is not None:
                conversion_timeout = min(conversion_timeout, max(0.001, deadline - time.monotonic()))
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
            try:
                stdout, stderr = process.communicate(timeout=conversion_timeout)
            except subprocess.TimeoutExpired:
                self._terminate_process_group(process)
                raise
            completed = subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
            rendered = temp_dir / f"{source_docx.stem}.pdf"
            if completed.returncode != 0 or not rendered.is_file() or rendered.stat().st_size == 0:
                detail = (completed.stderr or completed.stdout).strip()
                raise RuntimeError(f"LibreOffice PDF rendering failed: {detail or 'no PDF was produced'}")
            os.replace(rendered, output_pdf)
        return PdfRenderResult(
            path=output_pdf,
            method="LibreOffice headless DOCX-to-PDF",
            renderer_version=self.version(deadline=deadline),
        )
