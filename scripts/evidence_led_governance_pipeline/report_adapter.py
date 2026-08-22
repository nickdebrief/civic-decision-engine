"""Render a frozen Stage 75 specification without importing CDE persistence."""

from __future__ import annotations

import hashlib
import json
import math
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
    def __init__(self, location: str, reason: str, *, failure_step: str = "recursive_action_tree", failure_structure: str = "unexpected_object", failure_operand: str = "none", failure_operand_kind: str = "none", failure_operand_count: str = "not_applicable", failure_operand_kinds: list[str] | None = None, failure_destination_mode: str = "not_applicable", failure_trailing_kinds: list[str] | None = None, page_registry_state: str = "not_applicable", reference_identity_result: str = "not_applicable", resolution_result: str = "not_applicable", resolved_target_comparison: str = "not_applicable", page_reference_attribute: str = "none") -> None:
        self.location = location
        self.reason = reason
        self.failure_step = failure_step
        self.failure_structure = failure_structure
        self.failure_operand = failure_operand
        self.failure_operand_kind = failure_operand_kind
        self.failure_operand_count = failure_operand_count
        self.failure_operand_kinds = list(failure_operand_kinds or [])[:6]
        self.failure_destination_mode = failure_destination_mode
        self.failure_trailing_kinds = list(failure_trailing_kinds or [])[:5]
        self.page_registry_state = page_registry_state
        self.reference_identity_result = reference_identity_result
        self.resolution_result = resolution_result
        self.resolved_target_comparison = resolved_target_comparison
        self.page_reference_attribute = page_reference_attribute
        super().__init__("pdf_action_invalid")


class UnexpectedPdfInspectionError(ValueError):
    def __init__(self, failure_step: str, failure_operation: str, failure_exception_class: str, inspection_step: str = "unknown") -> None:
        self.failure_step = failure_step
        self.failure_operation = failure_operation
        self.failure_exception_class = failure_exception_class
        self.inspection_step = inspection_step
        super().__init__("unexpected_adapter_failure")


def _exception_class(exc: Exception) -> str:
    if isinstance(exc, AttributeError):
        return "attribute_error"
    if isinstance(exc, TypeError):
        return "type_error"
    if isinstance(exc, ValueError):
        return "value_error"
    if isinstance(exc, KeyError):
        return "key_error"
    if isinstance(exc, IndexError):
        return "index_error"
    if isinstance(exc, RecursionError):
        return "recursion_error"
    if isinstance(exc, OSError):
        return "os_error"
    if exc.__class__.__module__.startswith("pypdf") and exc.__class__.__name__ == "PdfReadError":
        return "pdf_read_error"
    return "other"


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
    if isinstance(exc, UnexpectedPdfInspectionError):
        return AdapterFailure(
            "pdf_inspection",
            "unexpected_adapter_failure",
            {"format": "pdf", "failure_step": exc.failure_step, "failure_operation": exc.failure_operation, "failure_exception_class": exc.failure_exception_class, "inspection_step": exc.inspection_step},
        )
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
                "failure_operand": exc.failure_operand,
                "failure_operand_kind": exc.failure_operand_kind,
                "failure_operand_count": exc.failure_operand_count,
                "failure_operand_kinds": exc.failure_operand_kinds,
                "failure_destination_mode": exc.failure_destination_mode,
                "failure_trailing_kinds": exc.failure_trailing_kinds,
                "page_registry_state": exc.page_registry_state,
                "reference_identity_result": exc.reference_identity_result,
                "resolution_result": exc.resolution_result,
                "resolved_target_comparison": exc.resolved_target_comparison,
                "page_reference_attribute": exc.page_reference_attribute,
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
    return AdapterFailure(
        "pdf_inspection",
        "unexpected_adapter_failure",
        {"format": "pdf", "failure_step": "pdf_inspection", "failure_operation": "inspect_pdf", "failure_exception_class": _exception_class(exc), "inspection_step": "unknown"},
    )


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
        try:
            pages = getattr(reader, "pages", ())
            iterator = iter(pages)
        except Exception as exc:
            raise UnexpectedPdfInspectionError("page_enumeration", "enumerate_pages", _exception_class(exc), "page_enumeration") from None
        while True:
            try:
                page = next(iterator)
            except StopIteration:
                break
            except Exception as exc:
                raise UnexpectedPdfInspectionError("page_enumeration", "materialize_page", _exception_class(exc), "page_enumeration") from None
            try:
                reference = getattr(page, "indirect_reference", None)
            except Exception as exc:
                raise UnexpectedPdfInspectionError("page_reference_attribute", "read_indirect_reference", _exception_class(exc), "page_reference_registry") from None
            if reference is None:
                return PdfActionError("catalog_open_action", "malformed_destination", page_registry_state="empty", page_reference_attribute="indirect_reference")
            try:
                identity = (getattr(reference, "idnum", None), getattr(reference, "generation", None))
            except Exception as exc:
                raise UnexpectedPdfInspectionError("identity_normalization", "read_reference_identity", _exception_class(exc), "page_reference_registry") from None
            if not all(isinstance(item, int) for item in identity):
                return PdfActionError("catalog_open_action", "malformed_destination", page_registry_state="empty", page_reference_attribute="indirect_reference")
            if identity in page_objects:
                return PdfActionError("catalog_open_action", "malformed_destination", failure_step="page_membership", failure_structure="unexpected_object", page_registry_state="duplicate_identity", reference_identity_result="ambiguous", page_reference_attribute="indirect_reference")
            page_objects[identity] = page
    except UnexpectedPdfInspectionError:
        raise
    except Exception as exc:
        raise UnexpectedPdfInspectionError("registry_construction", "build_page_registry", _exception_class(exc), "page_reference_registry") from None
        return PdfActionError("catalog_open_action", "malformed_destination", page_registry_state="empty", page_reference_attribute="indirect_reference")
    page_registry_state = "populated" if page_objects else "empty"

    def reference_identity(value: object) -> tuple[int, int] | None:
        try:
            idnum = getattr(value, "idnum", None)
            generation = getattr(value, "generation", None)
        except Exception as exc:
            raise UnexpectedPdfInspectionError("identity_normalization", "read_reference_identity", _exception_class(exc), "page_reference_registry") from None
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
        if not isinstance(value, (list, tuple)):
            raise PdfActionError(location, "malformed_destination", failure_step="destination_array", failure_structure=structure, failure_operand="operand_count", failure_operand_kind="other")
        def is_pdf_null(item: object) -> bool:
            item_type = type(item)
            return item is None or (item_type.__name__ == "NullObject" and item_type.__module__.startswith("pypdf."))

        def operand_kind(item: object) -> str:
            if is_pdf_null(item):
                return "null"
            if reference_identity(item) is not None:
                return "indirect_reference"
            if isinstance(item, bool) or isinstance(item, (int, float)):
                return "number"
            if isinstance(item, str):
                return "name" if item.startswith("/") else "other"
            if isinstance(item, (list, tuple)):
                return "array"
            if isinstance(item, dict):
                return "dictionary"
            return "other"

        def count_bucket(count: int) -> str:
            return str(count) if count <= 6 else "many"

        def destination_mode(items: list | tuple) -> str:
            if len(items) < 2:
                return "missing"
            mode = items[1]
            if not isinstance(mode, str):
                return "not_name"
            return {
                "/Fit": "fit", "/FitB": "fit_b", "/FitH": "fit_h", "/FitBH": "fit_bh",
                "/FitV": "fit_v", "/FitBV": "fit_bv", "/FitR": "fit_r", "/XYZ": "xyz",
            }.get(mode, "other_name")

        operand_kinds = [operand_kind(item) for item in value[:6]]
        trailing_kinds = [operand_kind(item) for item in value[2:7]]
        count = count_bucket(len(value))
        mode = destination_mode(value)
        if len(value) != 2 and not (len(value) == 5 and mode == "xyz"):
            raise PdfActionError(location, "malformed_destination", failure_step="destination_array", failure_structure=structure, failure_operand="operand_count", failure_operand_kind="array", failure_operand_count=count, failure_operand_kinds=operand_kinds, failure_destination_mode=mode, failure_trailing_kinds=trailing_kinds)
        page_reference = value[0]
        identity = reference_identity(page_reference)
        if identity is None:
            kind = "direct_dictionary" if isinstance(page_reference, dict) else "name" if isinstance(page_reference, str) else "other"
            raise PdfActionError(location, "unsupported_destination", failure_step="page_reference_identity", failure_structure=structure, failure_operand="operand_one", failure_operand_kind=kind, failure_operand_count=count, failure_operand_kinds=operand_kinds, failure_destination_mode=mode, failure_trailing_kinds=trailing_kinds, page_registry_state=page_registry_state, reference_identity_result="not_registered", page_reference_attribute="indirect_reference")
        if identity not in page_objects:
            raise PdfActionError(location, "unsupported_destination", failure_step="page_membership", failure_structure=structure, failure_operand="operand_one", failure_operand_kind="indirect_reference", failure_operand_count=count, failure_operand_kinds=operand_kinds, failure_destination_mode=mode, failure_trailing_kinds=trailing_kinds, page_registry_state=page_registry_state, reference_identity_result="not_registered", page_reference_attribute="indirect_reference")
        try:
            resolved_page = page_reference.get_object()
            if resolved_page is page_objects[identity]:
                comparison = "same_instance"
            else:
                resolved_reference = getattr(resolved_page, "indirect_reference", None)
                resolved_identity = reference_identity(resolved_reference)
                if resolved_identity == identity:
                    comparison = "same_indirect_identity"
                elif resolved_identity is None:
                    comparison = "unavailable"
                else:
                    comparison = "different_target"
            if comparison not in {"same_instance", "same_indirect_identity"}:
                raise PdfActionError(location, "unsupported_destination", failure_step="page_reference_resolution", failure_structure=structure, failure_operand="operand_one", failure_operand_kind="indirect_reference", failure_operand_count=count, failure_operand_kinds=operand_kinds, failure_destination_mode=mode, failure_trailing_kinds=trailing_kinds, page_registry_state=page_registry_state, reference_identity_result="registered", resolution_result="resolved_non_page" if comparison == "different_target" else "resolution_failed", resolved_target_comparison=comparison, page_reference_attribute="indirect_reference")
        except PdfActionError:
            raise
        except Exception:
            raise PdfActionError(location, "malformed_destination", failure_step="page_reference_resolution", failure_structure=structure, failure_operand="operand_one", failure_operand_kind="indirect_reference", failure_operand_count=count, failure_operand_kinds=operand_kinds, failure_destination_mode=mode, failure_trailing_kinds=trailing_kinds, page_registry_state=page_registry_state, reference_identity_result="registered", resolution_result="resolution_failed", resolved_target_comparison="unavailable", page_reference_attribute="indirect_reference") from None
        mode_name = value[1]
        if mode_name == "/Fit":
            return
        if mode_name == "/XYZ" and len(value) == 5:
            def valid_scalar(item: object, *, non_negative: bool = False) -> bool:
                if is_pdf_null(item) or isinstance(item, bool) or not isinstance(item, (int, float)):
                    return is_pdf_null(item)
                try:
                    finite = math.isfinite(float(item))
                except (OverflowError, TypeError, ValueError):
                    return False
                return finite and (not non_negative or item >= 0)

            for index, item in enumerate(value[2:], start=3):
                if not valid_scalar(item, non_negative=index == 5):
                    operand = {3: "operand_three", 4: "operand_four", 5: "operand_five"}[index]
                    raise PdfActionError(location, "unsupported_destination", failure_step="fit_validation", failure_structure=structure, failure_operand=operand, failure_operand_kind=operand_kind(item), failure_operand_count=count, failure_operand_kinds=operand_kinds, failure_destination_mode=mode, failure_trailing_kinds=trailing_kinds)
            return
        kind = "name" if isinstance(mode_name, str) else "other"
        raise PdfActionError(location, "unsupported_destination", failure_step="fit_validation", failure_structure=structure, failure_operand="operand_two", failure_operand_kind=kind, failure_operand_count=count, failure_operand_kinds=operand_kinds, failure_destination_mode=mode, failure_trailing_kinds=trailing_kinds)

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
    except ValueError as exc:
        if str(exc) in {"pdf_pypdf_version_invalid", "pdf_pypdf_unavailable"}:
            raise
        raise UnexpectedPdfInspectionError("pdf_inspection", "construct_reader", _exception_class(exc), "reader_construction") from None
    except ImportError:
        raise ValueError("pdf_pypdf_unavailable") from None
    except Exception:
        raise ValueError("pdf_structure_invalid") from None
    try:
        encrypted = reader.is_encrypted
        pages = reader.pages
        page_count = len(pages)
    except Exception as exc:
        raise UnexpectedPdfInspectionError("pdf_inspection", "validate_page_count", _exception_class(exc), "encryption_and_page_count") from None
    if encrypted or not pages or page_count > PDF_MAX_PAGES:
        raise ValueError("pdf_encryption_or_page_limit_invalid")
    try:
        metadata_failure = _pdf_metadata_failure(reader, book)
    except Exception as exc:
        raise UnexpectedPdfInspectionError("pdf_inspection", "validate_metadata", _exception_class(exc), "metadata_validation") from None
    if metadata_failure is not None:
        raise metadata_failure
    try:
        action_failure = _pdf_action_failure(reader)
    except (PdfActionError, UnexpectedPdfInspectionError):
        raise
    except Exception as exc:
        raise UnexpectedPdfInspectionError("pdf_inspection", "inspect_actions", _exception_class(exc), "unsafe_action_inspection") from None
    if action_failure is not None:
        raise action_failure
    info = _run_pdf_tool("pdfinfo", [str(pdf_path)], timeout=PDF_SUBPROCESS_TIMEOUT, deadline=deadline)
    try:
        info_values = {}
        for line in info.stdout.splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                info_values[key.strip()] = value.strip()
    except Exception as exc:
        raise UnexpectedPdfInspectionError("pdf_inspection", "parse_pdfinfo", _exception_class(exc), "page_count_validation") from None
    try:
        page_count = int(info_values.get("Pages", "0"))
    except ValueError:
        raise ValueError("pdf_page_count_invalid") from None
    if page_count != len(reader.pages) or page_count < 1 or page_count > PDF_MAX_PAGES:
        raise ValueError("pdf_page_count_invalid")
    with tempfile.TemporaryDirectory(prefix="cde-pdf-extract-") as extraction_dir:
        extracted_path = Path(extraction_dir) / "text.txt"
        _run_pdf_tool("pdftotext", ["-layout", str(pdf_path), str(extracted_path)], timeout=PDF_SUBPROCESS_TIMEOUT, deadline=deadline)
        try:
            text = extracted_path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            raise UnexpectedPdfInspectionError("pdf_inspection", "read_extracted_text", _exception_class(exc), "extracted_text_handling") from None
    lowered_text = text.lower()
    if any(token in lowered_text for token in ("/tmp/", "/private/tmp/", "/app/", "/data/", "private_canary", "stage76_private")):
        raise ValueError("pdf_private_path_or_canary_detected")
    try:
        equivalent = _pdf_ordered_equivalence(book, text)
    except Exception as exc:
        raise UnexpectedPdfInspectionError("pdf_inspection", "validate_ordered_equivalence", _exception_class(exc), "ordered_equivalence_validation") from None
    if not equivalent:
        raise ValueError("pdf_ordered_equivalence_failed")
    version = _run_pdf_tool("pdfinfo", ["-v"], timeout=PDF_SUBPROCESS_TIMEOUT, deadline=deadline)
    try:
        pdfinfo_version = (version.stdout or version.stderr).splitlines()[0]
        return {"page_count": page_count, "size_bytes": size, "pdfinfo_version": pdfinfo_version, "ordered_content": "ok", "metadata_attachments_annotations": "ok", "pypdf_version": "5.9.0"}
    except Exception as exc:
        raise UnexpectedPdfInspectionError("pdf_inspection", "construct_inspection_result", _exception_class(exc), "result_construction") from None


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
