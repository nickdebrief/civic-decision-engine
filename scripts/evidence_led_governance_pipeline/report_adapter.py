"""Render a frozen Stage 75 specification without importing CDE persistence."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from model import Book, Chapter, HtmlOutputConfig, Paragraph, Section  # noqa: E402
from renderers.docx_renderer import DocxRenderer  # noqa: E402
from renderers.html_renderer import HtmlRenderer  # noqa: E402
from themes.base import EffectiveTheme  # noqa: E402
from themes.handbook import HANDBOOK_THEME  # noqa: E402
from themes.registry import PUBLICATION_PROFILES  # noqa: E402
from output_validation import audit_html, docx_text, source_text_blocks, validate_cross_format_equivalence, validate_docx_output, validate_html_output  # noqa: E402
from renderers.pdf_renderer import PdfRenderer, discover_tool  # noqa: E402


ENGINE_VERSION = "2.0.0"
PDF_MAX_BYTES = 20 * 1024 * 1024
PDF_MAX_PAGES = 100
PDF_SUBPROCESS_TIMEOUT = 120
PDF_TOTAL_TIMEOUT = 180
PDF_FORBIDDEN_METADATA = ("/tmp", "/private/tmp", "/app", "/data", "password", "secret", "canary")
PDF_ALLOWED_METADATA_KEYS = {"/Title", "/Author", "/Subject", "/Keywords", "/Creator", "/Producer", "/CreationDate", "/ModDate"}


def ordered_content_is_preserved(book, *, docx_path: Path, html_path: Path) -> bool:
    expected = source_text_blocks(book)
    actual_values = (docx_text(docx_path)[0], audit_html(html_path).text)
    for actual in actual_values:
        cursor = -1
        for value in expected:
            position = actual.find(value, cursor + 1)
            if position <= cursor:
                return False
            cursor = position
    return True


def _run_pdf_tool(tool: str, arguments: list[str], *, timeout: int, deadline: float | None = None) -> subprocess.CompletedProcess[str]:
    path = discover_tool(tool)
    if path is None:
        raise ValueError(f"pdf_{tool}_unavailable")
    effective_timeout = timeout
    if deadline is not None:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError("pdf_total_timeout")
        effective_timeout = min(timeout, remaining)
    try:
        completed = subprocess.run([str(path), *arguments], check=False, capture_output=True, text=True, timeout=effective_timeout)
    except subprocess.TimeoutExpired:
        raise ValueError(f"pdf_{tool}_timeout") from None
    if completed.returncode != 0:
        raise ValueError(f"pdf_{tool}_failed")
    return completed


def _pdf_metadata_is_safe(reader: object, book: Book | None = None) -> bool:
    metadata = getattr(reader, "metadata", None) or {}
    for key, value in metadata.items():
        if str(key) not in PDF_ALLOWED_METADATA_KEYS:
            return False
        rendered = f"{key}={value}".lower()
        if any(token in rendered for token in PDF_FORBIDDEN_METADATA):
            return False
        if str(key) == "/Author" and str(value) != "Civic Decision Engine":
            return False
        if str(key) == "/Title" and book is not None and str(value) != book.title:
            return False
        if str(key) == "/Subject" and str(value) not in {"Internal governed report", ""}:
            return False
        if str(key) == "/Keywords" and str(value).strip():
            return False
        if str(key) == "/Creator" and str(value) not in {"Writer", "LibreOffice"} and not str(value).startswith("LibreOffice "):
            return False
        if str(key) == "/Producer" and not str(value).startswith("LibreOffice"):
            return False
    return True


def _pdf_has_unsafe_objects(reader: object) -> bool:
    dangerous = {"/Annots", "/EmbeddedFiles", "/JavaScript", "/JS", "/Launch", "/OpenAction", "/AA", "/URI", "/AcroForm"}

    def visit(value: object, seen: set[int]) -> bool:
        resolver = getattr(value, "get_object", None)
        if callable(resolver):
            try:
                value = resolver()
            except Exception:
                return True
        identity = id(value)
        if identity in seen:
            return False
        seen.add(identity)
        if isinstance(value, dict):
            for key, child in value.items():
                name = str(key)
                if name in dangerous:
                    return True
                if visit(child, seen):
                    return True
        elif isinstance(value, (list, tuple)):
            return any(visit(child, seen) for child in value)
        return False

    if visit(getattr(reader, "trailer", {}), set()):
        return True
    for page in getattr(reader, "pages", ()):
        if visit(page, set()):
            return True
    return False


def _pdf_ordered_equivalence(book: Book, pdf_text: str) -> bool:
    raw = re.sub(r"Structured\s*·\s*Traceable\s*·\s*Governed\s*·\s*\d+\s+EVIDENCE-LED GOVERNANCE", " ", pdf_text)
    allowed = (book.author, book.tagline or "", book.subtitle or "", str(book.version), "Civic Decision Engine", "A governed internal report specification")

    def only_boilerplate(value: str) -> bool:
        residue = value
        for item in allowed:
            if item:
                residue = residue.replace(item, " ")
        residue = re.sub(r"\bPage\s+\d+\b", " ", residue, flags=re.IGNORECASE)
        residue = re.sub(r"\s+", " ", residue).strip(" -·|\n\r\f")
        return not residue

    cursor = 0
    for block in source_text_blocks(book):
        pattern = re.escape(block)
        pattern = pattern.replace(r"\ ", r"\s+")
        match = re.search(pattern, raw[cursor:], flags=re.DOTALL)
        if match is None:
            return False
        if not only_boilerplate(raw[cursor:cursor + match.start()]):
            return False
        cursor += match.end()
    return only_boilerplate(raw[cursor:])


def _validate_pdf(pdf_path: Path, book: Book, *, deadline: float | None = None) -> dict[str, object]:
    if not pdf_path.is_file() or pdf_path.is_symlink() or pdf_path.stat().st_size <= 0:
        raise ValueError("pdf_output_missing_or_empty")
    size = pdf_path.stat().st_size
    if size > PDF_MAX_BYTES or pdf_path.read_bytes()[:5] != b"%PDF-":
        raise ValueError("pdf_output_size_or_header_invalid")
    try:
        import pypdf
        if getattr(pypdf, "__version__", "") != "5.9.0":
            raise ValueError("pdf_pypdf_version_invalid")
        reader = pypdf.PdfReader(str(pdf_path), strict=True)
    except ValueError:
        raise
    except ImportError:
        raise ValueError("pdf_pypdf_unavailable") from None
    except Exception:
        raise ValueError("pdf_structure_invalid") from None
    if reader.is_encrypted or not reader.pages or len(reader.pages) > PDF_MAX_PAGES:
        raise ValueError("pdf_encryption_or_page_limit_invalid")
    if not _pdf_metadata_is_safe(reader, book) or _pdf_has_unsafe_objects(reader):
        raise ValueError("pdf_metadata_or_action_invalid")
    info = _run_pdf_tool("pdfinfo", [str(pdf_path)], timeout=PDF_SUBPROCESS_TIMEOUT, deadline=deadline)
    info_values = {}
    for line in info.stdout.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            info_values[key.strip()] = value.strip()
    try:
        page_count = int(info_values.get("Pages", "0"))
    except ValueError:
        raise ValueError("pdf_page_count_invalid") from None
    if page_count != len(reader.pages) or page_count < 1 or page_count > PDF_MAX_PAGES:
        raise ValueError("pdf_page_count_invalid")
    with tempfile.TemporaryDirectory(prefix="cde-pdf-extract-") as extraction_dir:
        extracted_path = Path(extraction_dir) / "text.txt"
        _run_pdf_tool("pdftotext", ["-layout", str(pdf_path), str(extracted_path)], timeout=PDF_SUBPROCESS_TIMEOUT, deadline=deadline)
        text = extracted_path.read_text(encoding="utf-8", errors="replace")
    lowered_text = text.lower()
    if any(token in lowered_text for token in ("/tmp/", "/private/tmp/", "/app/", "/data/", "private_canary", "stage76_private")):
        raise ValueError("pdf_private_path_or_canary_detected")
    if not _pdf_ordered_equivalence(book, text):
        raise ValueError("pdf_ordered_equivalence_failed")
    version = _run_pdf_tool("pdfinfo", ["-v"], timeout=PDF_SUBPROCESS_TIMEOUT, deadline=deadline)
    return {"page_count": page_count, "size_bytes": size, "pdfinfo_version": (version.stdout or version.stderr).splitlines()[0], "ordered_content": "ok", "metadata_attachments_annotations": "ok", "pypdf_version": "5.9.0"}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def make_book(spec):
    blocks = []
    for section in spec["sections"]:
        paragraphs = []
        for block in section["blocks"]:
            label = {
                "verbatim_source": "Original wording",
                "faithful_paraphrase": "Faithful paraphrase",
                "administrative_summary": "Administrative summary",
                "qualification": "Qualification",
                "limitation": "Limitation",
                "redaction_notice": "Redaction notice",
            }[block["content_type"]]
            details = [f"{label}: {block['text']}"]
            if block.get("attribution"):
                details.append(f"Attribution: {block['attribution']}")
            details.append(f"Inclusion rationale: {block['inclusion_rationale']}")
            paragraphs.append(Paragraph(text=" — ".join(details), role="body", identifier=f"stage75-block-{section['order']}-{block['order']}"))
        blocks.append(Section(title=section["title"], number=str(section["order"] + 1), level=1, blocks=paragraphs, identifier=f"stage75-section-{section['order']}"))
    provenance = []
    for item in spec.get("selected_documents", []):
        provenance.append(Paragraph(text=f"Published document: {item['document_id']} — {item['title']} — SHA-256 {item.get('sha256')}", role="body", identifier=f"stage75-document-{item['document_id']}"))
    for item in spec.get("selected_associations", []):
        provenance.append(Paragraph(text=f"Record–document association: {item['association_id']} — {item['record_reference']} / {item['document_id']} — {item['relationship_type']}", role="body", identifier=f"stage75-association-{item['association_id']}"))
    if provenance:
        blocks.append(Section(title="Selected source provenance", number=str(len(blocks) + 1), level=1, blocks=provenance, identifier="stage75-source-provenance"))
    qualification_blocks = [Paragraph(text=f"Qualification: {value}", role="body", identifier=f"stage75-qualification-{index}") for index, value in enumerate(spec.get("qualifications", []))]
    exclusion_blocks = [Paragraph(text=f"Exclusion: {item['object_kind']}:{item['object_id']} — {item['rationale']}", role="body", identifier=f"stage75-exclusion-{index}") for index, item in enumerate(spec.get("exclusions", []))]
    if not exclusion_blocks:
        exclusion_blocks = [Paragraph(text="Exclusion: No exclusions recorded in this specification.", role="body", identifier="stage75-exclusion-none")]
    blocks.append(Section(title="Qualifications and exclusions", number=str(len(blocks) + 1), level=1, blocks=qualification_blocks + exclusion_blocks, identifier="stage75-qualifications-exclusions"))
    chapter = Chapter(title=spec["title"], number=1, blocks=blocks, identifier="stage75-canonical-record-report")
    return Book(title=spec["title"], subtitle=spec["purpose"], author="Civic Decision Engine", version=spec["specification_schema_version"], running_title=spec["title"], tagline="A governed internal report specification", blocks=[chapter], metadata={"subject": spec["BOUNDARY"] if "BOUNDARY" in spec else "Internal governed report", "edition": "Stage 75", "language": "en", "comments": "A report presents the record; it does not replace it."})


def main():
    started = __import__("time").monotonic()
    request, output = map(Path, sys.argv[1:3])
    payload = json.loads(request.read_text(encoding="utf-8"))
    spec = payload["specification"]
    digest = payload["digest"]
    if spec.get("publication_engine_version") != ENGINE_VERSION or hashlib.sha256(canonical(spec).encode()).hexdigest() != digest:
        raise ValueError("specification validation failed")
    requested = set(spec.get("requested_formats", []))
    if "pdf" in requested and not {"docx", "html"}.issubset(requested):
        raise ValueError("pdf_companion_formats_required")
    book = make_book(spec)
    effective = EffectiveTheme(theme=HANDBOOK_THEME, publication_profile=PUBLICATION_PROFILES["digital"], page=HANDBOOK_THEME.page, title_page=HANDBOOK_THEME.title_page, volume_page=HANDBOOK_THEME.volume_page, chapter_opening=HANDBOOK_THEME.chapter_opening)
    artifacts = []
    html_path = output / "report.html"
    docx_path = output / "report.docx"
    if "docx" in requested or "pdf" in requested:
        DocxRenderer(effective).render(book, docx_path)
        validation, _ = validate_docx_output(docx_path, book)
        if not validation.ok:
            raise ValueError("docx validation failed")
        artifacts.append(docx_path)
    if "html" in requested or "pdf" in requested:
        HtmlRenderer(effective, HtmlOutputConfig()).render(book, html_path)
        validation, _ = validate_html_output(html_path, "en")
        if not validation.ok:
            raise ValueError("html validation failed")
        artifacts.append(html_path)
    diagnostics = []
    if len(artifacts) == 2:
        equivalence, _ = validate_cross_format_equivalence(book, docx_path=docx_path, html_path=html_path)
        if not equivalence.ok or not ordered_content_is_preserved(book, docx_path=docx_path, html_path=html_path):
            raise ValueError("cross-format validation failed")
    if "pdf" in requested:
        if __import__("time").monotonic() - started > PDF_TOTAL_TIMEOUT:
            raise ValueError("pdf_total_timeout")
        pdf_path = output / "report.pdf"
        deadline = started + PDF_TOTAL_TIMEOUT
        renderer_result = PdfRenderer().render(docx_path, pdf_path, timeout=PDF_SUBPROCESS_TIMEOUT, deadline=deadline)
        if __import__("time").monotonic() - started > PDF_TOTAL_TIMEOUT:
            raise ValueError("pdf_total_timeout")
        pdf_diagnostics = _validate_pdf(pdf_path, book, deadline=deadline)
        pdf_diagnostics.update({"libreoffice_version": renderer_result.renderer_version, "extraction_backend": "pdftotext"})
        diagnostics.append({"format": "pdf", **pdf_diagnostics})
        artifacts.append(pdf_path)
    result = {"specification_digest": digest, "diagnostics": diagnostics, "artifacts": []}
    for path in artifacts:
        result["artifacts"].append({"format": path.suffix[1:], "path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "size_bytes": path.stat().st_size, "renderer_version": ENGINE_VERSION})
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
