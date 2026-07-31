"""Reliable DOCX-to-PDF rendering through headless LibreOffice."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
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


@dataclass(frozen=True)
class PdfRenderResult:
    path: Path
    method: str
    renderer_version: str


class PdfRenderer:
    def __init__(self, soffice_path: Path | str | None = None) -> None:
        self.soffice_path = Path(soffice_path) if soffice_path is not None else discover_tool("soffice")

    @property
    def available(self) -> bool:
        return bool(self.soffice_path and self.soffice_path.is_file())

    def version(self) -> str:
        if not self.available:
            return "unavailable"
        completed = subprocess.run(
            [str(self.soffice_path), "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return (completed.stdout or completed.stderr).strip() or "unknown"

    def render(self, source_docx: Path, output_pdf: Path) -> PdfRenderResult:
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
            completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=300)
            rendered = temp_dir / f"{source_docx.stem}.pdf"
            if completed.returncode != 0 or not rendered.is_file() or rendered.stat().st_size == 0:
                detail = (completed.stderr or completed.stdout).strip()
                raise RuntimeError(f"LibreOffice PDF rendering failed: {detail or 'no PDF was produced'}")
            os.replace(rendered, output_pdf)
        return PdfRenderResult(
            path=output_pdf,
            method="LibreOffice headless DOCX-to-PDF",
            renderer_version=self.version(),
        )
