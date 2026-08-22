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
RESULT_SCHEMA_VERSION = "1"


class AdapterFailure(RuntimeError):
    def __init__(self, phase: str, code: str, diagnostic: dict | None = None) -> None:
        self.phase = phase
        self.code = code
        self.diagnostic = diagnostic


class PdfMetadataError(ValueError):
    def __init__(self, field: str, reason: str) -> None:
        self.field = field if field in PDF_ALLOWED_METADATA_KEYS else "unknown_key"
        self.reason = reason
        super().__init__("pdf_metadata_invalid")


class PdfActionError(ValueError):
    def __init__(self, location: str, reason: str, *, failure_step: str = "recursive_action_tree", failure_structure: str = "unexpected_object") -> None:
        self.location = location
        self.reason = reason
        self.failure_step = failure_step
        self.failure_structure = failure_structure
        super().__init__("pdf_action_invalid")


def _write_result(path: Path, result: dict) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")), encoding="utf-8")
        os.replace(temporary, path)
    except Exception:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise AdapterFailure("result_serialization", "adapter_result_write_failed") from None


def _run_phase(phase: str, code: str, operation):
    try:
        return operation()
    except AdapterFailure:
        raise
    except Exception:
        raise AdapterFailure(phase, code) from None


def _classify_pdf_failure(exc: Exception) -> AdapterFailure:
    if isinstance(exc, PdfMetadataError):
        return AdapterFailure(
            "pdf_inspection",
            "pdf_metadata_invalid",
            {"format": "pdf", "failure_field": exc.field, "failure_reason": exc.reason},
        )
    if isinstance(exc, PdfActionError):
        return AdapterFailure(
            "pdf_inspection",
            "pdf_action_invalid",
            {
                "format": "pdf",
                "failure_location": exc.location,
                "failure_reason": exc.reason,
                "failure_step": exc.failure_step,
                "failure_structure": exc.failure_structure,
            },
        )
    code = str(exc)
    if "pypdf" in code or "unavailable" in code:
        return AdapterFailure("pdf_inspection", "pdf_inspection_dependency_unavailable")
    if "metadata" in code:
        return AdapterFailure("pdf_inspection", "pdf_metadata_invalid")
    if "action" in code:
        return AdapterFailure("pdf_inspection", "pdf_action_invalid")
    if "attachment" in code or "annotation" in code:
        return AdapterFailure("pdf_inspection", "pdf_attachment_invalid")
    if "extract" in code or "pdftotext" in code:
        return AdapterFailure("pdf_inspection", "pdf_extraction_failed")
    if "missing" in code:
        return AdapterFailure("pdf_inspection", "pdf_missing")
    if "invalid" in code or "header" in code or "page" in code:
        return AdapterFailure("pdf_inspection", "pdf_invalid")
    return AdapterFailure("pdf_inspection", "unexpected_adapter_failure")


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


def _pdf_metadata_failure(reader: object, book: Book | None = None) -> PdfMetadataError | None:
    metadata = getattr(reader, "metadata", None) or {}
    if not hasattr(metadata, "items"):
        return PdfMetadataError("unknown_key", "unexpected_value")
    for key, value in metadata.items():
        field = str(key)
        if field not in PDF_ALLOWED_METADATA_KEYS:
            return PdfMetadataError(field, "unexpected_key")
        if not isinstance(value, str):
            return PdfMetadataError(field, "non_string_value")
        rendered = f"{field}={value}".lower()
        if any(token in rendered for token in PDF_FORBIDDEN_METADATA):
            return PdfMetadataError(field, "forbidden_value")
        if field == "/Author" and value != "Civic Decision Engine":
            return PdfMetadataError(field, "identity_mismatch")
        if field == "/Title" and book is not None and value != book.title:
            return PdfMetadataError(field, "identity_mismatch")
        if field == "/Subject" and value not in {"Internal governed report", ""}:
            return PdfMetadataError(field, "unexpected_value")
        if field == "/Keywords" and value.strip():
            return PdfMetadataError(field, "unexpected_value")
        if field == "/Creator" and value not in {"Writer", "LibreOffice"} and not value.startswith("LibreOffice "):
            return PdfMetadataError(field, "unexpected_value")
        if field == "/Producer" and not value.startswith("LibreOffice"):
            return PdfMetadataError(field, "unexpected_value")
    return None


def _pdf_metadata_is_safe(reader: object, book: Book | None = None) -> bool:
    return _pdf_metadata_failure(reader, book) is None


def _pdf_action_failure(reader: object) -> PdfActionError | None:
    try:
        page_objects = {}
        for page in reader.pages:
            reference = getattr(page, "indirect_reference", None)
            identity = (getattr(reference, "idnum", None), getattr(reference, "generation", None))
            if not all(isinstance(item, int) for item in identity):
                return PdfActionError("catalog_open_action", "malformed_destination")
            page_objects[identity] = page
    except Exception:
        return PdfActionError("catalog_open_action", "malformed_destination")

    def reference_identity(value: object) -> tuple[int, int] | None:
        idnum = getattr(value, "idnum", None)
        generation = getattr(value, "generation", None)
        if isinstance(idnum, int) and isinstance(generation, int):
            return idnum, generation
        return None

    def resolve_chain(value: object, active: set[tuple[int, int]], location: str, *, failure_step: str = "recursive_action_tree") -> object:
        resolver = getattr(value, "get_object", None)
        identity = reference_identity(value)
        # pypdf containers expose get_object() as an identity operation. Only
        # indirect references participate in cycle detection or resolution.
        if identity is None or not callable(resolver):
            return value
        if identity in active:
            raise PdfActionError(location, "indirect_cycle", failure_step=failure_step, failure_structure="indirect_array")
        active.add(identity)
        try:
            resolved = resolver()
            if resolved is value:
                raise PdfActionError(location, "indirect_cycle", failure_step=failure_step, failure_structure="indirect_array")
            return resolve_chain(resolved, active, location, failure_step=failure_step)
        except PdfActionError:
            raise
        except Exception:
            raise PdfActionError(location, "malformed_destination", failure_step=failure_step) from None
        finally:
            active.remove(identity)

    def internal_destination(value: object, location: str) -> None:
        structure = "indirect_array" if reference_identity(value) is not None else "direct_array"
        value = resolve_chain(value, set(), location, failure_step="open_action_wrapper")
        if isinstance(value, dict) and "/S" in value:
            raise PdfActionError(location, "executable_action", failure_step="open_action_resolution", failure_structure="action_dictionary")
        if isinstance(value, str):
            raise PdfActionError(location, "external_destination", failure_step="open_action_resolution", failure_structure="unexpected_object")
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            raise PdfActionError(location, "malformed_destination", failure_step="destination_array", failure_structure=structure)
        page_reference = value[0]
        identity = reference_identity(page_reference)
        if identity is None:
            raise PdfActionError(location, "unsupported_destination", failure_step="page_reference_identity", failure_structure=structure)
        if identity not in page_objects:
            raise PdfActionError(location, "unsupported_destination", failure_step="page_membership", failure_structure=structure)
        try:
            if page_reference.get_object() is not page_objects[identity]:
                raise PdfActionError(location, "unsupported_destination", failure_step="page_reference_resolution", failure_structure=structure)
        except PdfActionError:
            raise
        except Exception:
            raise PdfActionError(location, "malformed_destination", failure_step="page_reference_resolution", failure_structure=structure) from None
        mode = value[1]
        if mode != "/Fit":
            raise PdfActionError(location, "unsupported_destination", failure_step="fit_validation", failure_structure=structure)

    def inspect_outline(value: object, active: set[int]) -> None:
        value = resolve_chain(value, active, "outline_action", failure_step="recursive_action_tree")
        if isinstance(value, (list, tuple)):
            for child in value:
                inspect_outline(child, active)
            return
        if not isinstance(value, dict):
            raise PdfActionError("outline_action", "malformed_destination")
        identity = id(value)
        if identity in active:
            raise PdfActionError("outline_action", "indirect_cycle")
        active.add(identity)
        try:
            if "/A" in value or "/AA" in value:
                raise PdfActionError("outline_action", "executable_action")
            if "/Dest" in value:
                internal_destination(value["/Dest"], "outline_action")
            if "/First" in value:
                inspect_outline(value["/First"], active)
            if "/Next" in value:
                inspect_outline(value["/Next"], active)
        finally:
            active.remove(identity)

    def inspect_names(value: object, active: set[int]) -> None:
        value = resolve_chain(value, active, "catalog_open_action", failure_step="recursive_action_tree")
        if not isinstance(value, dict):
            return
        identity = id(value)
        if identity in active:
            raise PdfActionError("catalog_open_action", "indirect_cycle")
        active.add(identity)
        try:
            if "/EmbeddedFiles" in value:
                raise PdfActionError("catalog_open_action", "attachment_or_interactive_content")
            for child in value.get("/Kids", []):
                inspect_names(child, active)
        finally:
            active.remove(identity)

    def inspect_page(page: object) -> None:
        if not isinstance(page, dict):
            return
        if "/AA" in page:
            raise PdfActionError("page_additional_actions", "executable_action")
        if "/Annots" in page:
            raise PdfActionError("annotation_action", "executable_action")
        if any(key in page for key in ("/EmbeddedFiles", "/Filespec", "/EF", "/AF", "/AcroForm")):
            raise PdfActionError("page_additional_actions", "attachment_or_interactive_content")

    trailer = getattr(reader, "trailer", {})
    try:
        root = trailer.get("/Root", trailer) if isinstance(trailer, dict) else trailer
        root = resolve_chain(root, set(), "catalog_open_action", failure_step="open_action_resolution")
        if not isinstance(root, dict):
            raise PdfActionError("catalog_open_action", "malformed_destination")
        if "/OpenAction" in root:
            internal_destination(root["/OpenAction"], "catalog_open_action")
        if "/AA" in root:
            raise PdfActionError("catalog_additional_actions", "executable_action")
        if "/Annots" in root:
            raise PdfActionError("annotation_action", "executable_action")
        if any(key in root for key in ("/EmbeddedFiles", "/Filespec", "/EF", "/AF", "/AcroForm")):
            raise PdfActionError("catalog_open_action", "attachment_or_interactive_content")
        if "/Names" in root:
            inspect_names(root["/Names"], set())
        if "/Outlines" in root:
            inspect_outline(root["/Outlines"], set())
        for page in reader.pages:
            page_object = page.get_object() if callable(getattr(page, "get_object", None)) else page
            inspect_page(page_object)
    except PdfActionError as exc:
        return exc
    except Exception:
        return PdfActionError("catalog_open_action", "malformed_destination")
    return None


def _pdf_has_unsafe_objects(reader: object) -> bool:
    return _pdf_action_failure(reader) is not None


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
    metadata_failure = _pdf_metadata_failure(reader, book)
    if metadata_failure is not None:
        raise metadata_failure
    action_failure = _pdf_action_failure(reader)
    if action_failure is not None:
        raise action_failure
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
    started = time.monotonic()
    if len(sys.argv) != 4:
        raise AdapterFailure("input_validation", "adapter_input_invalid")
    request, output, result_path = map(Path, sys.argv[1:4])
    try:
        payload = json.loads(request.read_text(encoding="utf-8"))
        spec = payload["specification"]
        digest = payload["digest"]
    except Exception:
        raise AdapterFailure("input_load", "adapter_input_invalid") from None
    if not isinstance(spec, dict) or not isinstance(digest, str):
        raise AdapterFailure("input_validation", "adapter_input_invalid")
    if spec.get("publication_engine_version") != ENGINE_VERSION or hashlib.sha256(canonical(spec).encode()).hexdigest() != digest:
        raise AdapterFailure("specification_validation", "specification_digest_mismatch")
    requested = set(spec.get("requested_formats", []))
    if "pdf" in requested and not {"docx", "html"}.issubset(requested):
        raise AdapterFailure("specification_validation", "adapter_input_invalid")
    book = _run_phase("model_adaptation", "adapter_model_invalid", lambda: make_book(spec))
    effective = EffectiveTheme(theme=HANDBOOK_THEME, publication_profile=PUBLICATION_PROFILES["digital"], page=HANDBOOK_THEME.page, title_page=HANDBOOK_THEME.title_page, volume_page=HANDBOOK_THEME.volume_page, chapter_opening=HANDBOOK_THEME.chapter_opening)
    artifacts = []
    html_path = output / "report.html"
    docx_path = output / "report.docx"
    if "docx" in requested or "pdf" in requested:
        def render_docx():
            DocxRenderer(effective).render(book, docx_path)
            validation, _ = validate_docx_output(docx_path, book)
            if not validation.ok:
                raise RuntimeError("docx validation failed")
            return docx_path
        artifacts.append(_run_phase("docx_render", "docx_render_failed", render_docx))
    if "html" in requested or "pdf" in requested:
        def render_html():
            HtmlRenderer(effective, HtmlOutputConfig()).render(book, html_path)
            validation, _ = validate_html_output(html_path, "en")
            if not validation.ok:
                raise RuntimeError("html validation failed")
            return html_path
        artifacts.append(_run_phase("html_render", "html_render_failed", render_html))
    diagnostics = []
    if len(artifacts) == 2:
        def check_equivalence():
            equivalence, _ = validate_cross_format_equivalence(book, docx_path=docx_path, html_path=html_path)
            if not equivalence.ok or not ordered_content_is_preserved(book, docx_path=docx_path, html_path=html_path):
                raise RuntimeError("cross-format validation failed")
        _run_phase("cross_format_equivalence", "equivalence_failed", check_equivalence)
    if "pdf" in requested:
        if time.monotonic() - started > PDF_TOTAL_TIMEOUT:
            raise AdapterFailure("pdf_conversion", "pdf_conversion_failed")
        pdf_path = output / "report.pdf"
        deadline = started + PDF_TOTAL_TIMEOUT
        try:
            renderer_result = PdfRenderer().render(docx_path, pdf_path, timeout=PDF_SUBPROCESS_TIMEOUT, deadline=deadline)
        except AdapterFailure:
            raise
        except Exception:
            raise AdapterFailure("pdf_conversion", "pdf_conversion_failed") from None
        if time.monotonic() - started > PDF_TOTAL_TIMEOUT:
            raise AdapterFailure("pdf_conversion", "pdf_conversion_failed")
        try:
            pdf_diagnostics = _validate_pdf(pdf_path, book, deadline=deadline)
        except Exception as exc:
            raise _classify_pdf_failure(exc) from None
        pdf_diagnostics.update({"libreoffice_version": renderer_result.renderer_version, "extraction_backend": "pdftotext"})
        diagnostics.append({"format": "pdf", **pdf_diagnostics})
        artifacts.append(pdf_path)
    descriptors = []
    try:
        for path in artifacts:
            descriptors.append({"format": path.suffix[1:], "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "size_bytes": path.stat().st_size, "renderer_version": ENGINE_VERSION})
    except Exception:
        raise AdapterFailure("artifact_digest", "artifact_digest_failed") from None
    result = {"schema_version": RESULT_SCHEMA_VERSION, "ok": True, "phase": "result_serialization", "code": "completed", "cleanup": "passed", "specification_digest": digest, "diagnostics": diagnostics, "artifacts": descriptors}
    _write_result(result_path, result)


if __name__ == "__main__":
    result_path = Path(sys.argv[3]) if len(sys.argv) == 4 else None
    try:
        main()
    except AdapterFailure as exc:
        if result_path is not None:
            try:
                _write_result(result_path, {"schema_version": RESULT_SCHEMA_VERSION, "ok": False, "phase": exc.phase, "code": exc.code, "cleanup": "unknown", "specification_digest": "", "diagnostics": [exc.diagnostic] if exc.diagnostic else [], "artifacts": []})
            except AdapterFailure:
                pass
        raise SystemExit(1)
    except Exception:
        if result_path is not None:
            try:
                _write_result(result_path, {"schema_version": RESULT_SCHEMA_VERSION, "ok": False, "phase": "result_serialization", "code": "unexpected_adapter_failure", "cleanup": "unknown", "specification_digest": "", "diagnostics": [], "artifacts": []})
            except AdapterFailure:
                pass
        raise SystemExit(1)
