"""Format-specific output, link, accessibility, and equivalence validation."""

from __future__ import annotations

import importlib
import hashlib
import json
import re
import subprocess
import zipfile
from datetime import datetime, timezone
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree
from typing import Any, Mapping

from docx import Document

from model import Book, BulletList, Callout, Chapter, FlowDiagram, FrontMatter, Paragraph, Section, Volume
from renderers.pdf_renderer import discover_tool
from themes.base import EffectiveTheme
from validator import ValidationResult


WORD_NAMESPACE = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
VALID_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")
PATHWAY_OUTPUT_EQUIVALENCE_CONTRACT = "stage78.pathway_output_equivalence.v1"
PATHWAY_OUTPUT_EQUIVALENCE_ERROR = "governed_report_pathway_output_equivalence_failed"
PATHWAY_DOCX_STRUCTURAL_FRAME_CONTRACT = "stage78.docx_structural_frame.v1"
PATHWAY_DOCX_VISIBLE_UNIT_FRAME_CONTRACT = "stage78.docx_visible_unit_frame.v1"
PATHWAY_TRUSTED_PDF_CONVERSION_CONTRACT = "stage78.trusted_pdf_conversion_authority.v2"
PATHWAY_RENDER_MODEL_BINDING_CONTRACT = "stage78.pathway_render_model_binding.v1"
PATHWAY_GOVERNANCE_QUALIFICATION_BINDING_CONTRACT = "stage78.governance_qualification_binding.v1"
PATHWAY_DOCX_STRUCTURAL_PREFIX = "s78c_"
PATHWAY_DOCX_VISIBLE_PREFIX = "s78u_"
PATHWAY_STAGE77_JOB_PREFIX = "stage77-report-job:"


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _pathway_canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _pathway_sha256(value: Any) -> str:
    return hashlib.sha256(_pathway_canonical(value).encode("utf-8")).hexdigest()


def _pathway_binding_sha256(contract: str, value: Any) -> str:
    return _pathway_sha256({"contract": contract, "value": value})


def _pathway_valid_governed_job_id(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def pathway_governed_job_identity(governed_job_id: int) -> str:
    if not _pathway_valid_governed_job_id(governed_job_id):
        raise ValueError("invalid_governed_job_id")
    return f"{PATHWAY_STAGE77_JOB_PREFIX}{governed_job_id}"


def _pathway_text(value: Any) -> str:
    if value is None:
        return "not recorded"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (str, int, float)):
        text = str(value)
    else:
        text = _pathway_canonical(value)
    return normalize_text(text)


def _pathway_docx_token(prefix: str, payload: Mapping[str, Any]) -> str:
    digest = hashlib.sha256(_pathway_canonical(payload).encode("utf-8")).hexdigest()
    token = prefix + digest[:35]
    if len(token) > 40 or not token[0].isalpha() or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", token):
        raise ValueError("invalid_docx_frame_token")
    return token


def _pathway_docx_container_paths(units: list["PathwayVisibleUnit"]) -> dict[str, str]:
    paths: dict[str, str] = {}
    current_section = ""
    for unit in units:
        if unit.unit_kind == "heading" and unit.field_identity == "chapter":
            current_section = ""
            path = "body/p:chapter"
        elif unit.unit_kind == "heading" and unit.field_identity == "section":
            current_section = unit.framing_identity
            path = f"body/p:section:{unit.ordinal}"
        else:
            if not current_section:
                raise ValueError("invalid_docx_frame_authority")
            path = f"body/p:section:{current_section}:paragraph"
        paths[unit.framing_identity] = path
    return paths


def pathway_docx_frame_contract(units: list["PathwayVisibleUnit"]) -> dict[str, dict[str, Any]]:
    """Return deterministic DOCX bookmark authority for Stage 78 visible units."""

    container_paths = _pathway_docx_container_paths(units)
    unit_by_frame: dict[str, PathwayVisibleUnit] = {}
    unit_by_token: dict[str, PathwayVisibleUnit] = {}
    unit_token_by_frame: dict[str, str] = {}
    structural_token_by_frame: dict[str, str] = {}
    all_tokens: set[str] = set()
    for unit in units:
        if unit.framing_identity in unit_by_frame:
            raise ValueError("duplicate_docx_frame_identity")
        unit_by_frame[unit.framing_identity] = unit
        token = _pathway_docx_token(PATHWAY_DOCX_VISIBLE_PREFIX, {
            "contract": PATHWAY_DOCX_VISIBLE_UNIT_FRAME_CONTRACT,
            "record_identity": unit.record_identity,
            "unit_kind": unit.unit_kind,
            "field_identity": unit.field_identity,
            "ordinal": unit.ordinal,
            "framing_identity": unit.framing_identity,
            "sequence_position": unit.sequence_position,
            "expected_container_path": container_paths[unit.framing_identity],
        })
        if token in all_tokens:
            raise ValueError("duplicate_docx_frame_token")
        all_tokens.add(token)
        unit_token_by_frame[unit.framing_identity] = token
        unit_by_token[token] = unit
        if unit.unit_kind == "heading" and unit.field_identity in {"chapter", "section"}:
            anchor = _pathway_docx_token(PATHWAY_DOCX_STRUCTURAL_PREFIX, {
                "contract": PATHWAY_DOCX_STRUCTURAL_FRAME_CONTRACT,
                "frame_kind": unit.field_identity,
                "framing_identity": unit.framing_identity,
                "ordinal": unit.ordinal,
                "sequence_position": unit.sequence_position,
                "expected_container_path": container_paths[unit.framing_identity],
            })
            if anchor in all_tokens:
                raise ValueError("duplicate_docx_frame_token")
            all_tokens.add(anchor)
            structural_token_by_frame[unit.framing_identity] = anchor
    return {
        "container_by_frame": container_paths,
        "unit_by_frame": unit_by_frame,
        "unit_by_token": unit_by_token,
        "unit_token_by_frame": unit_token_by_frame,
        "structural_token_by_frame": structural_token_by_frame,
        "all_tokens": all_tokens,
    }


class _VisibleHtmlTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text_parts: list[str] = []
        self._hidden_depth = 0

    @staticmethod
    def _is_hidden(tag: str, attrs: Mapping[str, str]) -> bool:
        style = attrs.get("style", "").replace(" ", "").lower()
        return (
            tag in {"script", "style", "noscript"}
            or "hidden" in attrs
            or attrs.get("aria-hidden", "").lower() == "true"
            or "display:none" in style
            or "visibility:hidden" in style
        )

    def handle_starttag(self, tag: str, attrs) -> None:
        if self._hidden_depth:
            self._hidden_depth += 1
            return
        if self._is_hidden(tag, dict(attrs)):
            self._hidden_depth = 1

    def handle_endtag(self, tag: str) -> None:
        if self._hidden_depth:
            self._hidden_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._hidden_depth:
            self.text_parts.append(data)

    @property
    def text(self) -> str:
        return normalize_text(" ".join(self.text_parts))


def visible_html_text(path: Path) -> str:
    html_path = path / "index.html" if path.is_dir() else path
    parser = _VisibleHtmlTextParser()
    parser.feed(html_path.read_text(encoding="utf-8"))
    return parser.text


def source_text_blocks(book: Book) -> list[str]:
    """Return source-derived semantic text, excluding generated publication sections."""
    values: list[str] = []

    def visit(block) -> None:
        if isinstance(block, Section) and block.generated:
            return
        if isinstance(block, Volume):
            values.append(block.title)
        elif isinstance(block, FrontMatter):
            values.append(block.title)
        elif isinstance(block, Chapter):
            values.append(block.title)
        elif isinstance(block, Section):
            values.append(block.heading_text)
        elif isinstance(block, Callout):
            values.extend(part for part in (block.code or "", block.title) if part)
        elif isinstance(block, Paragraph):
            values.append(block.text)
        elif isinstance(block, BulletList):
            values.extend(item.text for item in block.items)
        elif isinstance(block, FlowDiagram):
            for node in block.nodes:
                values.append(node.label)
                if node.connector:
                    values.append(node.connector)
        for child in list(getattr(block, "blocks", [])) + list(getattr(block, "body", [])):
            visit(child)

    for root in book.blocks:
        visit(root)
    return [normalized for value in values if (normalized := normalize_text(value))]


def docx_text(path: Path) -> tuple[str, int, int]:
    document = Document(path)
    values = [paragraph.text for paragraph in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                values.extend(paragraph.text for paragraph in cell.paragraphs)
    return normalize_text("\n".join(values)), len(document.paragraphs), len(document.tables)


@dataclass
class DocxAudit:
    paragraph_count: int = 0
    table_count: int = 0
    bookmark_count: int = 0
    hyperlink_count: int = 0
    duplicate_bookmarks: list[str] = field(default_factory=list)
    broken_links: list[str] = field(default_factory=list)


def audit_docx(path: Path) -> DocxAudit:
    _, paragraphs, tables = docx_text(path)
    with zipfile.ZipFile(path) as package:
        root = ElementTree.fromstring(package.read("word/document.xml"))
    names = [node.attrib.get(f"{{{WORD_NAMESPACE}}}name", "") for node in root.findall(f".//{{{WORD_NAMESPACE}}}bookmarkStart")]
    anchors = [node.attrib.get(f"{{{WORD_NAMESPACE}}}anchor", "") for node in root.findall(f".//{{{WORD_NAMESPACE}}}hyperlink") if node.attrib.get(f"{{{WORD_NAMESPACE}}}anchor")]
    duplicates = sorted({name for name in names if name and names.count(name) > 1})
    broken = sorted({anchor for anchor in anchors if anchor not in set(names)})
    return DocxAudit(paragraphs, tables, len(names), len(anchors), duplicates, broken)


def validate_docx_output(path: Path, book: Book) -> tuple[ValidationResult, DocxAudit]:
    result = ValidationResult()
    exists = path.is_file() and path.stat().st_size > 0
    result.add("DOCX generated", exists, str(path))
    if not exists:
        return result, DocxAudit()
    try:
        text, _, _ = docx_text(path)
        audit = audit_docx(path)
        properties = Document(path).core_properties
    except Exception as exc:
        result.add("DOCX reopened", False, str(exc))
        return result, DocxAudit()
    result.add("DOCX reopened", True, f"{audit.paragraph_count} paragraphs, {audit.table_count} tables")
    expected_tables = sum(isinstance(block, Callout) for block in _walk_model(book))
    result.add("DOCX structure", audit.paragraph_count > 0 and audit.table_count == expected_tables, f"{expected_tables} expected tables")
    result.add("DOCX metadata", bool(properties.title and properties.author and properties.language), properties.title or "missing")
    result.add("DOCX bookmarks unique", not audit.duplicate_bookmarks, ", ".join(audit.duplicate_bookmarks))
    result.add("DOCX internal links", not audit.broken_links, f"{audit.hyperlink_count} links, {len(audit.broken_links)} broken")
    result.add("DOCX unresolved markup", "[[REF:" not in text, "none" if "[[REF:" not in text else "found")
    return result, audit


def _walk_model(book: Book):
    stack = list(book.blocks)
    while stack:
        block = stack.pop(0)
        yield block
        stack[0:0] = list(getattr(block, "blocks", [])) + list(getattr(block, "body", []))


class HtmlAuditParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.language = ""
        self.ids: list[str] = []
        self.hrefs: list[str] = []
        self.asset_links: list[str] = []
        self.headings: list[tuple[int, str]] = []
        self.text_parts: list[str] = []
        self._heading_level: int | None = None
        self._heading_text: list[str] = []
        self._link_text_stack: list[list[str]] = []
        self.empty_links = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        attributes = dict(attrs)
        if tag == "html":
            self.language = attributes.get("lang", "")
        identifier = attributes.get("id")
        if identifier is not None:
            self.ids.append(identifier)
        if tag == "a":
            href = attributes.get("href", "")
            self.hrefs.append(href)
            self._link_text_stack.append([])
        if tag in {"img", "link", "script"}:
            target = attributes.get("src") or attributes.get("href")
            if target:
                self.asset_links.append(target)
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._heading_level = int(tag[1])
            self._heading_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._link_text_stack:
            if not normalize_text("".join(self._link_text_stack.pop())):
                self.empty_links += 1
        if self._heading_level is not None and tag == f"h{self._heading_level}":
            self.headings.append((self._heading_level, normalize_text("".join(self._heading_text))))
            self._heading_level = None
            self._heading_text = []

    def handle_data(self, data: str) -> None:
        self.text_parts.append(data)
        if self._heading_level is not None:
            self._heading_text.append(data)
        if self._link_text_stack:
            self._link_text_stack[-1].append(data)

    @property
    def text(self) -> str:
        return normalize_text(" ".join(self.text_parts))


@dataclass
class HtmlAudit:
    anchor_count: int = 0
    internal_link_count: int = 0
    duplicate_ids: list[str] = field(default_factory=list)
    broken_links: list[str] = field(default_factory=list)
    invalid_ids: list[str] = field(default_factory=list)
    empty_headings: int = 0
    heading_gaps: list[str] = field(default_factory=list)
    empty_links: int = 0
    broken_assets: list[str] = field(default_factory=list)
    language: str = ""
    text: str = ""


def parse_html_output(path: Path) -> tuple[HtmlAuditParser, Path]:
    html_path = path / "index.html" if path.is_dir() else path
    parser = HtmlAuditParser()
    parser.feed(html_path.read_text(encoding="utf-8"))
    return parser, html_path


def audit_html(path: Path) -> HtmlAudit:
    parser, html_path = parse_html_output(path)
    duplicates = sorted({identifier for identifier in parser.ids if parser.ids.count(identifier) > 1})
    internal = [href[1:] for href in parser.hrefs if href.startswith("#")]
    broken = sorted({target for target in internal if target not in set(parser.ids)})
    invalid = sorted({identifier for identifier in parser.ids if not VALID_IDENTIFIER.fullmatch(identifier)})
    empty_headings = sum(not text for _, text in parser.headings)
    gaps = []
    previous = None
    for level, text in parser.headings:
        if previous is not None and level > previous + 1:
            gaps.append(text)
        previous = level
    broken_assets = []
    for target in parser.asset_links:
        if target.startswith(("data:", "http://", "https://", "#")):
            continue
        if not (html_path.parent / target).is_file():
            broken_assets.append(target)
    return HtmlAudit(
        anchor_count=len(parser.ids),
        internal_link_count=len(internal),
        duplicate_ids=duplicates,
        broken_links=broken,
        invalid_ids=invalid,
        empty_headings=empty_headings,
        heading_gaps=gaps,
        empty_links=parser.empty_links,
        broken_assets=broken_assets,
        language=parser.language,
        text=parser.text,
    )


def validate_html_output(path: Path, language: str) -> tuple[ValidationResult, HtmlAudit]:
    result = ValidationResult()
    html_path = path / "index.html" if path.is_dir() else path
    exists = html_path.is_file() and html_path.stat().st_size > 0
    result.add("HTML generated", exists, str(html_path))
    if not exists:
        return result, HtmlAudit()
    try:
        audit = audit_html(path)
    except Exception as exc:
        result.add("HTML parsed", False, str(exc))
        return result, HtmlAudit()
    result.add("HTML parsed", True, f"{audit.anchor_count} anchors, {audit.internal_link_count} internal links")
    result.add("HTML language", audit.language == language, audit.language or "missing")
    result.add("HTML identifiers", not audit.duplicate_ids and not audit.invalid_ids, f"{len(audit.duplicate_ids)} duplicate, {len(audit.invalid_ids)} invalid")
    result.add("HTML internal links", not audit.broken_links and audit.empty_links == 0, f"{len(audit.broken_links)} broken, {audit.empty_links} empty")
    result.add("HTML assets", not audit.broken_assets, ", ".join(audit.broken_assets))
    result.add("HTML heading hierarchy", audit.empty_headings == 0 and not audit.heading_gaps, f"{audit.empty_headings} empty, {len(audit.heading_gaps)} gaps")
    result.add("HTML unresolved markup", "[[REF:" not in audit.text, "none" if "[[REF:" not in audit.text else "found")
    return result, audit


@dataclass(frozen=True)
class PdfTextExtraction:
    text: str = ""
    raw_text: str = ""
    status: str = "unavailable"
    backend: str = ""
    reason: str = "No supported PDF text extraction backend was available."
    attempts: tuple[tuple[str, str], ...] = ()
    page_count: int = 0
    width_points: float = 0.0
    height_points: float = 0.0
    title: str = ""

    @property
    def available(self) -> bool:
        return self.status == "available"


def _pypdf_metadata(reader, pages) -> tuple[int, float, float, str]:
    width = float(pages[0].mediabox.width) if pages else 0.0
    height = float(pages[0].mediabox.height) if pages else 0.0
    metadata = reader.metadata or {}
    title = getattr(metadata, "title", None)
    if not title and hasattr(metadata, "get"):
        title = metadata.get("/Title", "")
    return len(pages), width, height, str(title or "")


def extract_pdf_text_result(path: Path) -> PdfTextExtraction:
    """Extract PDF text with deterministic, ordered optional backends."""

    attempts: list[tuple[str, str]] = []
    tool = discover_tool("pdftotext")
    if tool is not None:
        completed = subprocess.run(
            [str(tool), "-layout", str(path), "-"],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if completed.returncode != 0:
            raise RuntimeError(f"PDF text extraction failed: {completed.stderr.strip()}")
        attempts.append(("pdftotext", "available"))
        return PdfTextExtraction(
            text=normalize_text(completed.stdout),
            raw_text=completed.stdout,
            status="available",
            backend="pdftotext",
            reason="",
            attempts=tuple(attempts),
        )
    attempts.append(("pdftotext", "not found"))

    try:
        pypdf = importlib.import_module("pypdf")
    except ImportError:
        attempts.append(("pypdf", "module unavailable"))
    else:
        try:
            reader = pypdf.PdfReader(str(path))
            pages = list(reader.pages)
            text = normalize_text("\n".join(page.extract_text() or "" for page in pages))
            page_count, width, height, title = _pypdf_metadata(reader, pages)
        except Exception as exc:
            attempts.append(("pypdf", f"extraction failed: {type(exc).__name__}"))
        else:
            attempts.append(("pypdf", "available"))
            return PdfTextExtraction(
                text=text,
                raw_text="\n".join(page.extract_text() or "" for page in pages),
                status="available",
                backend="pypdf",
                reason="",
                attempts=tuple(attempts),
                page_count=page_count,
                width_points=width,
                height_points=height,
                title=title,
            )

    try:
        pdfminer = importlib.import_module("pdfminer.high_level")
    except ImportError:
        attempts.append(("pdfminer.six", "module unavailable"))
    else:
        try:
            text = normalize_text(str(pdfminer.extract_text(str(path)) or ""))
        except Exception as exc:
            attempts.append(("pdfminer.six", f"extraction failed: {type(exc).__name__}"))
        else:
            attempts.append(("pdfminer.six", "available"))
            return PdfTextExtraction(
                text=text,
                raw_text=str(pdfminer.extract_text(str(path)) or ""),
                status="available",
                backend="pdfminer.six",
                reason="",
                attempts=tuple(attempts),
            )

    return PdfTextExtraction(attempts=tuple(attempts))


def extract_pdf_text(path: Path) -> str:
    """Compatibility API returning text only; unavailable extraction is empty."""

    return extract_pdf_text_result(path).text


PDF_RUNNING_HEADER = re.compile(
    r"Structured\s*·\s*Traceable\s*·\s*Governed\s*·\s*\d+\s+EVIDENCE-LED GOVERNANCE"
)


def _pdf_equivalence_pattern(block: str) -> re.Pattern[str]:
    """Build a strict pattern for PDF line-wrap representation artifacts."""
    escaped = re.escape(block)
    escaped = escaped.replace(r"\ ", r"\s+")
    escaped = re.sub(
        r"\\-(?=[A-Za-z])",
        lambda _match: r"(?:-\s*|[\r\n\f]\s*)",
        escaped,
    )
    return re.compile(escaped, re.DOTALL)


def pdf_block_matches(block: str, extraction: PdfTextExtraction) -> bool:
    """Match source text while accounting only for proven PDF representation artifacts."""
    if block in extraction.text:
        return True
    raw = extraction.raw_text or extraction.text
    raw = PDF_RUNNING_HEADER.sub(" ", raw)
    return _pdf_equivalence_pattern(block).search(raw) is not None


def _pdf_pathway_visible_lines(extraction: PdfTextExtraction) -> list[str]:
    lines: list[str] = []
    for line in (extraction.raw_text or extraction.text).replace("\f", "\n").splitlines():
        value = normalize_text(line)
        if not value:
            continue
        if PDF_RUNNING_HEADER.fullmatch(value):
            continue
        lines.append(value)
    return lines


def _pdf_pathway_stream(extraction: PdfTextExtraction) -> str:
    return "\n".join(_pdf_pathway_visible_lines(extraction))


def _pdf_layout_break_pattern() -> str:
    return r"(?:[ \t]*[\r\n\f]+[ \t]*)"


def _pdf_pathway_unit_pattern(value: str) -> re.Pattern[str]:
    """Return a current-cursor PDF pattern for one canonical logical unit."""

    normalized = normalize_text(value)
    parts: list[str] = []
    index = 0
    while index < len(normalized):
        character = normalized[index]
        if character.isspace():
            while index < len(normalized) and normalized[index].isspace():
                index += 1
            parts.append(r"\s+")
            continue
        if character == "-" and index + 1 < len(normalized) and normalized[index + 1].isalpha():
            parts.append(r"(?:-\s*|" + _pdf_layout_break_pattern() + r")")
        else:
            parts.append(re.escape(character))
        index += 1
        if index < len(normalized) and not normalized[index].isspace():
            parts.append(_pdf_layout_break_pattern() + "*")
    return re.compile("".join(parts))


def _pdf_consume_layout_separator(stream: str, cursor: int) -> int:
    match = re.compile(r"[ \t\r\n\f]*").match(stream, cursor)
    return match.end() if match else cursor


@dataclass
class PdfAudit:
    page_count: int = 0
    width_points: float = 0.0
    height_points: float = 0.0
    title: str = ""
    text: str = ""
    inspection_available: bool = False
    validation_status: str = "unavailable"
    text_backend: str = ""
    validation_reason: str = "No supported PDF text extraction backend was available."
    backend_attempts: tuple[tuple[str, str], ...] = ()


def audit_pdf(path: Path) -> PdfAudit:
    extraction = extract_pdf_text_result(path)
    values: dict[str, str] = {}
    pdfinfo = discover_tool("pdfinfo")
    if pdfinfo is not None:
        completed = subprocess.run(
            [str(pdfinfo), str(path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if completed.returncode != 0:
            raise RuntimeError(f"PDF inspection failed: {completed.stderr.strip()}")
        for line in completed.stdout.splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                values[key.strip()] = value.strip()
    size = re.search(r"([0-9.]+)\s+x\s+([0-9.]+)\s+pts", values.get("Page size", ""))
    page_count = int(values.get("Pages", "0")) if values else extraction.page_count
    width = float(size.group(1)) if size else extraction.width_points
    height = float(size.group(2)) if size else extraction.height_points
    title = values.get("Title", "") if values else extraction.title
    return PdfAudit(
        page_count=page_count,
        width_points=width,
        height_points=height,
        title=title,
        text=extraction.text,
        inspection_available=bool(values) or extraction.page_count > 0,
        validation_status=extraction.status,
        text_backend=extraction.backend,
        validation_reason=extraction.reason,
        backend_attempts=extraction.attempts,
    )


def validate_pdf_output(path: Path, book: Book, effective: EffectiveTheme) -> tuple[ValidationResult, PdfAudit]:
    result = ValidationResult()
    exists = path.is_file() and path.stat().st_size > 0
    result.add("PDF generated", exists, str(path))
    if not exists:
        return result, PdfAudit()
    try:
        audit = audit_pdf(path)
    except Exception as exc:
        result.add("PDF opened", False, str(exc))
        return result, PdfAudit()
    if audit.inspection_available:
        expected_width = effective.page.width_inches * 72
        expected_height = effective.page.height_inches * 72
        dimensions_match = abs(audit.width_points - expected_width) <= 2 and abs(audit.height_points - expected_height) <= 2
        result.add("PDF opened", audit.page_count > 0, f"{audit.page_count} pages")
        result.add("PDF metadata", bool(audit.title), audit.title or "missing title")
        result.add("PDF page profile", dimensions_match, f"{audit.width_points:g} x {audit.height_points:g} pt")
    else:
        result.add("PDF structural validation", True, "Skipped: no supported inspection backend was available")
    if audit.validation_status == "available":
        result.add("PDF expected text", book.title in audit.text and book.author in audit.text, book.title)
    else:
        result.add("PDF expected text", True, f"Skipped: {audit.validation_reason}")
    return result, audit


@dataclass
class EquivalenceAudit:
    block_count: int = 0
    missing_docx: list[str] = field(default_factory=list)
    missing_html: list[str] = field(default_factory=list)
    missing_pdf: list[str] = field(default_factory=list)
    pdf_status: str = "not requested"
    pdf_backend: str = ""
    pdf_reason: str = ""
    pdf_attempts: tuple[tuple[str, str], ...] = ()


def validate_cross_format_equivalence(
    book: Book,
    *,
    docx_path: Path,
    html_path: Path | None = None,
    pdf_path: Path | None = None,
) -> tuple[ValidationResult, EquivalenceAudit]:
    result = ValidationResult()
    blocks = source_text_blocks(book)
    docx_value, _, _ = docx_text(docx_path)
    html_value = audit_html(html_path).text if html_path is not None else ""
    pdf_extraction = extract_pdf_text_result(pdf_path) if pdf_path is not None else None
    pdf_value = pdf_extraction.text if pdf_extraction is not None else ""
    missing_docx = [block for block in blocks if block not in docx_value]
    missing_html = [block for block in blocks if html_path is not None and block not in html_value]
    missing_pdf = [
        block
        for block in blocks
        if pdf_extraction is not None
        and pdf_extraction.available
        and not pdf_block_matches(block, pdf_extraction)
    ]
    result.add("DOCX source equivalence", not missing_docx, f"{len(blocks) - len(missing_docx)}/{len(blocks)} blocks")
    if html_path is not None:
        result.add("HTML source equivalence", not missing_html, f"{len(blocks) - len(missing_html)}/{len(blocks)} blocks")
    if pdf_extraction is not None:
        if pdf_extraction.available:
            result.add("PDF source equivalence", not missing_pdf, f"{len(blocks) - len(missing_pdf)}/{len(blocks)} blocks")
        else:
            result.add("PDF source equivalence", True, f"Skipped: {pdf_extraction.reason}")
    return result, EquivalenceAudit(
        len(blocks),
        missing_docx,
        missing_html,
        missing_pdf,
        pdf_status=(pdf_extraction.status if pdf_extraction is not None else "not requested"),
        pdf_backend=(pdf_extraction.backend if pdf_extraction is not None else ""),
        pdf_reason=(pdf_extraction.reason if pdf_extraction is not None else ""),
        pdf_attempts=(pdf_extraction.attempts if pdf_extraction is not None else ()),
    )


@dataclass
class PathwayOutputEquivalenceAudit:
    contract: str = PATHWAY_OUTPUT_EQUIVALENCE_CONTRACT
    unit_count: int = 0
    failures: list[dict[str, str]] = field(default_factory=list)
    pdf_claim: str = ""


@dataclass(frozen=True)
class PathwayVisibleUnit:
    record_identity: str
    unit_kind: str
    field_identity: str
    ordinal: int
    value: str
    framing_identity: str
    sequence_position: int


@dataclass(frozen=True)
class PathwayTrustedPdfConversion:
    conversion_contract: str
    job_identity: str
    specification_identity: str
    specification_sha256: str
    render_model_identity: str
    render_model_sha256: str
    governance_qualification_identity: str
    governance_qualification_sha256: str
    source_docx_sha256: str
    pdf_sha256: str
    rendering_profile: str
    converter: str
    attempt_identity: str = ""
    conversion_record_digest: str = ""


@dataclass(frozen=True)
class _PathwayHtmlCandidate:
    frame: str
    unit_kind: str
    value: str
    chapter_frame: str
    section_frame: str
    container: str
    position: int


def _pathway_failure(format_name: str, field: str, reason: str) -> dict[str, str]:
    return {"format": format_name, "field": field, "reason": reason}


def pathway_trusted_pdf_conversion_binding(
    model: Mapping[str, Any],
    specification: Mapping[str, Any],
    governance_qualification: Mapping[str, Any] | None = None,
    *,
    governed_job_id: int | None = None,
    governed_attempt_count: int | None = None,
    retry_of_job_id: int | None = None,
) -> dict[str, str]:
    if not isinstance(model, Mapping) or not isinstance(specification, Mapping):
        raise ValueError("invalid_canonical_authority_input")
    job_identity = pathway_governed_job_identity(governed_job_id)
    if not isinstance(governed_attempt_count, int) or isinstance(governed_attempt_count, bool) or governed_attempt_count <= 0:
        raise ValueError("invalid_governed_attempt_identity")
    if retry_of_job_id is not None and not _pathway_valid_governed_job_id(retry_of_job_id):
        raise ValueError("invalid_governed_retry_identity")
    specification_identity = _pathway_text(specification.get("specification_schema_version"))
    render_model_identity = _pathway_text(model.get("render_model_contract"))
    if not specification_identity or specification_identity == "not recorded" or not render_model_identity or render_model_identity == "not recorded":
        raise ValueError("invalid_canonical_authority_input")
    if governance_qualification is None:
        qualification_identity = "none"
        qualification_digest = _pathway_binding_sha256(PATHWAY_GOVERNANCE_QUALIFICATION_BINDING_CONTRACT, None)
    else:
        if not isinstance(governance_qualification, Mapping) or "qualification_id" not in governance_qualification:
            raise ValueError("invalid_canonical_authority_input")
        qualification_identity = _pathway_text(governance_qualification.get("qualification_id"))
        if not qualification_identity or qualification_identity == "not recorded":
            raise ValueError("invalid_canonical_authority_input")
        qualification_digest = _pathway_binding_sha256(PATHWAY_GOVERNANCE_QUALIFICATION_BINDING_CONTRACT, governance_qualification)
    specification_digest = _pathway_sha256(specification)
    return {
        "conversion_contract": PATHWAY_TRUSTED_PDF_CONVERSION_CONTRACT,
        "job_identity": job_identity,
        "specification_identity": specification_identity,
        "specification_sha256": specification_digest,
        "render_model_identity": render_model_identity,
        "render_model_sha256": _pathway_binding_sha256(PATHWAY_RENDER_MODEL_BINDING_CONTRACT, model),
        "governance_qualification_identity": qualification_identity,
        "governance_qualification_sha256": qualification_digest,
        "attempt_identity": f"{job_identity}:attempt:{governed_attempt_count}",
        "retry_predecessor_identity": "none" if retry_of_job_id is None else pathway_governed_job_identity(retry_of_job_id),
    }


_PDF_CONVERSION_AUTHORITY_FIELDS = {
    "conversion_contract", "job_identity", "attempt_identity", "retry_predecessor_identity",
    "specification_identity", "specification_sha256", "render_model_identity", "render_model_sha256",
    "governance_qualification_identity", "governance_qualification_sha256", "gate_chain_identity",
    "source_docx_artifact_identity", "source_docx_sha256", "pdf_artifact_identity", "pdf_sha256",
    "converter_identity", "converter_version", "conversion_profile", "template_version",
    "publication_engine_version", "created_at", "conversion_record_digest",
}


def pathway_pdf_conversion_authority_record(
    model: Mapping[str, Any], specification: Mapping[str, Any], governance_qualification: Mapping[str, Any] | None,
    *, governed_job_id: int, governed_attempt_count: int, retry_of_job_id: int | None,
    docx_sha256: str, pdf_sha256: str, converter_identity: str, converter_version: str,
    created_at: str | None = None,
) -> dict[str, str]:
    """Construct the one canonical, byte-bound Stage 78 PDF authority record."""
    binding = pathway_trusted_pdf_conversion_binding(
        model, specification, governance_qualification, governed_job_id=governed_job_id,
        governed_attempt_count=governed_attempt_count, retry_of_job_id=retry_of_job_id,
    )
    if any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value) for value in (docx_sha256, pdf_sha256)):
        raise ValueError("invalid_conversion_artifact_digest")
    if not isinstance(converter_identity, str) or not converter_identity.strip() or not isinstance(converter_version, str) or not converter_version.strip():
        raise ValueError("invalid_conversion_authority")
    stamp = created_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    if not isinstance(stamp, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[^\n]+Z", stamp):
        raise ValueError("invalid_conversion_timestamp")
    attempt = binding["attempt_identity"]
    record = {
        **binding,
        "gate_chain_identity": binding["governance_qualification_identity"],
        "source_docx_artifact_identity": f"stage78-docx:{attempt}",
        "source_docx_sha256": docx_sha256,
        "pdf_artifact_identity": f"stage78-pdf:{attempt}",
        "pdf_sha256": pdf_sha256,
        "converter_identity": converter_identity.strip(),
        "converter_version": converter_version.strip(),
        "conversion_profile": _pathway_text(specification.get("rendering_profile")),
        "template_version": _pathway_text(specification.get("template_version")),
        "publication_engine_version": _pathway_text(specification.get("publication_engine_version")),
        "created_at": stamp,
    }
    record["conversion_record_digest"] = _pathway_sha256(record)
    return record


def _pathway_public_detail(failures: list[dict[str, str]]) -> str:
    if not failures:
        return "all canonical pathway units matched"
    counts: dict[str, int] = {}
    for failure in failures:
        counts[failure["reason"]] = counts.get(failure["reason"], 0) + 1
    return ", ".join(f"{key}:{value}" for key, value in sorted(counts.items()))


def _pathway_row_text(row: Mapping[str, Any]) -> str:
    chronology = row.get("chronology") if isinstance(row.get("chronology"), Mapping) else {}
    represented = _pathway_text(row.get("represented_time"))
    if represented == "not recorded":
        represented = "represented time not recorded; temporal ordering indeterminate"
    details = [
        f"Kind: {_pathway_text(row.get('object_kind'))}",
        f"Identity: {_pathway_text(row.get('governed_logical_identity'))}",
        f"Category: {_pathway_text(row.get('category'))}",
        f"Status: {_pathway_text(row.get('status'))}",
        f"Represented time: {represented}",
        f"Recording time: {_pathway_text(row.get('recorded_at'))}",
        f"Chronology: {_pathway_text(chronology.get('basis'))} / {_pathway_text(chronology.get('precision'))} / {_pathway_text(chronology.get('ordering_relation'))}",
        f"Ownership path: {_pathway_text(row.get('ownership_path'))}",
        f"Source authority: {_pathway_text(row.get('source_authority_key'))}",
        f"Row authority digest: {_pathway_text(row.get('row_authority_digest'))}",
    ]
    optional_fields = (
        ("parent_governed_identity", "Parent"),
        ("endpoint_identities", "Endpoints"),
        ("contestation", "Contestation"),
        ("supersession", "Historical state"),
        ("reliance", "Reliance"),
        ("does_not_establish", "Epistemic boundary"),
        ("limitations", "Limitations"),
    )
    for key, label in optional_fields:
        if row.get(key):
            details.append(f"{label}: {_pathway_text(row.get(key))}")
    return " — ".join(details)


def _pathway_contested_text(row: Mapping[str, Any]) -> str:
    return (
        f"Contested or historical governed row: {_pathway_text(row.get('object_kind'))} — "
        f"{_pathway_text(row.get('governed_logical_identity'))} — "
        f"status {_pathway_text(row.get('status'))} — "
        f"contestation {_pathway_text(row.get('contestation'))} — "
        f"historical state {_pathway_text(row.get('supersession'))}"
    )


def canonical_pathway_units(
    model: Mapping[str, Any],
    specification: Mapping[str, Any],
    governance_qualification: Mapping[str, Any] | None = None,
) -> list[PathwayVisibleUnit]:
    """Derive ordered visible pathway units from frozen authority, never artifacts."""

    if not isinstance(model, Mapping) or not isinstance(specification, Mapping):
        raise ValueError("invalid_canonical_authority_input")
    if specification.get("report_type") != "procedural_pathway_report":
        raise ValueError("invalid_canonical_authority_input")
    pathway = specification.get("pathway_projection")
    if not isinstance(pathway, Mapping):
        raise ValueError("invalid_canonical_authority_input")
    parity = (
        "canonical_record_reference", "projection_contract", "projection_version", "projection_digest",
        "inclusion_mode", "exclusion_rule", "coverage", "unavailable_families", "gaps",
    )
    for key in parity:
        if model.get(key) != pathway.get(key):
            raise ValueError("invalid_canonical_authority_input")

    rows = [
        row
        for section in model.get("sections") or []
        if isinstance(section, Mapping)
        for row in section.get("rows") or []
        if isinstance(row, Mapping) and "source_authority_key" in row
    ]
    record_identity = _pathway_text(model.get("canonical_record_reference"))
    units: list[PathwayVisibleUnit] = []

    def add(unit_kind: str, field_identity: str, ordinal: int, value: str, framing_identity: str) -> None:
        normalized = normalize_text(value)
        if not normalized:
            raise ValueError("invalid_canonical_authority_input")
        units.append(PathwayVisibleUnit(
            record_identity=record_identity,
            unit_kind=unit_kind,
            field_identity=field_identity,
            ordinal=ordinal,
            value=normalized,
            framing_identity=framing_identity,
            sequence_position=len(units),
        ))

    title = _pathway_text(specification.get("title"))
    add("heading", "chapter", 0, f"Chapter 1 — {title}", "stage78-procedural-pathway-report")
    add("heading", "section", 0, "1 Report identity and scope", "stage78-section-identity-scope")
    identity_values = [
        ("equivalence_contract", f"Pathway output equivalence: {PATHWAY_OUTPUT_EQUIVALENCE_CONTRACT}", "stage78-pathway-output-equivalence"),
        ("render_authority", f"Report type: {_pathway_text(model.get('report_type'))} — Distribution: {_pathway_text(model.get('distribution_class'))} — Render model: {_pathway_text(model.get('render_model_contract'))}", "stage78-pathway-render-authority"),
        ("canonical_record_reference", f"Canonical Record: {record_identity}", "stage78-pathway-scope-record"),
        ("projection_identity", f"Projection: {_pathway_text(model.get('projection_contract'))} / {_pathway_text(model.get('projection_version'))} / {_pathway_text(model.get('projection_digest'))}", "stage78-pathway-scope-projection"),
        ("scope_rules", f"Inclusion: {_pathway_text(model.get('inclusion_mode'))} — Exclusion rule: {_pathway_text(model.get('exclusion_rule'))}", "stage78-pathway-scope-rules"),
        ("row_count", f"Governed pathway rows: {len(rows)}", "stage78-pathway-row-count"),
    ]
    for ordinal, (field, value, frame) in enumerate(identity_values):
        add("body", field, ordinal, value, frame)
    section_number = 2
    for section in model.get("sections") or []:
        if not isinstance(section, Mapping):
            raise ValueError("invalid_canonical_authority_input")
        title = _pathway_text(section.get("title"))
        if title in {"Report identity and scope", "Provenance and limitations"}:
            continue
        add("heading", "section", section_number, f"{section_number} {title}", f"stage78-section-{section_number}")
        if title == "Scoped gaps":
            gaps = model.get("gaps") if isinstance(model.get("gaps"), list) else []
            if gaps:
                for index, gap in enumerate(gaps):
                    if not isinstance(gap, Mapping):
                        raise ValueError("invalid_canonical_authority_input")
                    add("body", "gap", index, f"Scoped gap: {_pathway_text(gap.get('statement'))} Binding: {_pathway_text(gap.get('binding_mechanism'))}.", f"stage78-gap-{index}")
            else:
                add("body", "gap", 0, "Scoped gap: no scoped gaps recorded in the frozen pathway projection.", "stage78-gap-none")
        elif title == "Contested matters":
            for index, row in enumerate(section.get("rows") or []):
                if not isinstance(row, Mapping):
                    raise ValueError("invalid_canonical_authority_input")
                add("body", "contested_row", index, _pathway_contested_text(row), f"stage78-contested-{index}")
        else:
            for index, row in enumerate(section.get("rows") or []):
                if not isinstance(row, Mapping):
                    raise ValueError("invalid_canonical_authority_input")
                add("body", "pathway_row", index, _pathway_row_text(row), f"stage78-pathway-row-{section_number}-{index}")
        section_number += 1
    add("heading", "section", section_number, f"{section_number} Provenance and limitations", "stage78-section-provenance-limitations")
    provenance = [
        ("coverage", f"Coverage: {_pathway_text(model.get('coverage'))}", "stage78-provenance-coverage"),
        ("unavailable_families", f"Unavailable families: {_pathway_text(model.get('unavailable_families'))}", "stage78-provenance-unavailable"),
    ]
    for ordinal, (field, value, frame) in enumerate(provenance):
        add("body", field, ordinal, value, frame)
    for index, limitation in enumerate(model.get("limitations") or []):
        add("body", "limitation", index, f"Limitation: {_pathway_text(limitation)}", f"stage78-provenance-limitation-{index}")
    for index, value in enumerate(specification.get("qualifications", []) or []):
        add("body", "qualification", index, f"Qualification: {_pathway_text(value)}", f"stage78-provenance-qualification-{index}")
    if governance_qualification is not None:
        if not isinstance(governance_qualification, Mapping) or set(governance_qualification) != {"review_mode", "disclosure_version", "disclosure", "qualification_id", "qualification_digest"}:
            raise ValueError("invalid_canonical_authority_input")
        add("body", "qualification_disclosure", 0, f"Qualification disclosure: {_pathway_text(governance_qualification['disclosure'])}", "stage78-provenance-qualification-disclosure")
    return units


def pathway_output_semantic_inventory(model: Mapping[str, Any]) -> list[dict[str, str]]:
    """Compatibility view of canonical Stage 78 units."""

    specification = {
        "report_type": "procedural_pathway_report",
        "title": model.get("title") if isinstance(model, Mapping) else None,
        "pathway_projection": {key: model.get(key) for key in (
            "canonical_record_reference", "projection_contract", "projection_version", "projection_digest",
            "inclusion_mode", "exclusion_rule", "coverage", "unavailable_families", "gaps",
        )} if isinstance(model, Mapping) else {},
    }
    return [{"field": unit.field_identity, "text": unit.value} for unit in canonical_pathway_units(model, specification)]


def _field_from_frame(frame: str) -> str:
    known = {
        "stage78-procedural-pathway-report": "chapter",
        "stage78-section-identity-scope": "section",
        "stage78-pathway-output-equivalence": "equivalence_contract",
        "stage78-pathway-render-authority": "render_authority",
        "stage78-pathway-scope-record": "canonical_record_reference",
        "stage78-pathway-scope-projection": "projection_identity",
        "stage78-pathway-scope-rules": "scope_rules",
        "stage78-pathway-row-count": "row_count",
        "stage78-provenance-coverage": "coverage",
        "stage78-provenance-unavailable": "unavailable_families",
        "stage78-provenance-qualification-disclosure": "qualification_disclosure",
    }
    if frame in known:
        return known[frame]
    if frame.startswith("stage78-section-"):
        return "section"
    if frame.startswith("stage78-pathway-row-"):
        return "pathway_row"
    if frame.startswith("stage78-gap-"):
        return "gap"
    if frame.startswith("stage78-contested-"):
        return "contested_row"
    if frame.startswith("stage78-provenance-limitation-"):
        return "limitation"
    if frame.startswith("stage78-provenance-qualification-"):
        return "qualification"
    return "unknown"


def _compare_pathway_units(expected: list[PathwayVisibleUnit], actual: list[PathwayVisibleUnit], *, format_name: str) -> list[dict[str, str]]:
    failures: list[dict[str, str]] = []
    if len(actual) < len(expected):
        failures.append(_pathway_failure(format_name, "unit_count", "missing_unit"))
    if len(actual) > len(expected):
        failures.append(_pathway_failure(format_name, "unit_count", "extra_unit"))
    seen: set[tuple[str, str, str, str]] = set()
    for unit in actual:
        key = (unit.framing_identity, unit.unit_kind, unit.field_identity, unit.value)
        if key in seen:
            failures.append(_pathway_failure(format_name, unit.field_identity, "duplicate_unit"))
        seen.add(key)
    for index, expected_unit in enumerate(expected):
        if index >= len(actual):
            failures.append(_pathway_failure(format_name, expected_unit.field_identity, "missing_unit"))
            continue
        actual_unit = actual[index]
        if actual_unit.framing_identity != expected_unit.framing_identity or actual_unit.unit_kind != expected_unit.unit_kind or actual_unit.field_identity != expected_unit.field_identity:
            failures.append(_pathway_failure(format_name, expected_unit.field_identity, "framing_mismatch"))
        if actual_unit.value != expected_unit.value:
            same_value_later = any(unit.value == expected_unit.value for unit in actual[index + 1:])
            failures.append(_pathway_failure(format_name, expected_unit.field_identity, "reordered_unit" if same_value_later else "value_mismatch"))
    expected_multiplicity: dict[tuple[str, str, str], int] = {}
    actual_multiplicity: dict[tuple[str, str, str], int] = {}
    for unit in expected:
        key = (unit.unit_kind, unit.field_identity, unit.value)
        expected_multiplicity[key] = expected_multiplicity.get(key, 0) + 1
    for unit in actual:
        key = (unit.unit_kind, unit.field_identity, unit.value)
        actual_multiplicity[key] = actual_multiplicity.get(key, 0) + 1
    for key, count in expected_multiplicity.items():
        if actual_multiplicity.get(key, 0) != count:
            failures.append(_pathway_failure(format_name, key[1], "multiplicity_mismatch"))
    return failures


def _units_from_triplets(triplets: list[tuple[str, str, str]], expected: list[PathwayVisibleUnit]) -> list[PathwayVisibleUnit]:
    units: list[PathwayVisibleUnit] = []
    for index, (frame, unit_kind, value) in enumerate(triplets):
        template = expected[index] if index < len(expected) else PathwayVisibleUnit("", unit_kind, _field_from_frame(frame), index, "", frame, index)
        units.append(PathwayVisibleUnit(
            record_identity=template.record_identity,
            unit_kind=unit_kind,
            field_identity=_field_from_frame(frame),
            ordinal=template.ordinal,
            value=normalize_text(value),
            framing_identity=frame,
            sequence_position=index,
        ))
    return units


def _html_expected_containers(expected: list[PathwayVisibleUnit]) -> dict[str, dict[str, str]]:
    containers: dict[str, dict[str, str]] = {}
    current_section = ""
    for unit in expected:
        if unit.unit_kind == "heading" and unit.field_identity == "chapter":
            current_section = ""
            containers[unit.framing_identity] = {"chapter": unit.framing_identity, "section": "", "container": "article/h1"}
        elif unit.unit_kind == "heading" and unit.field_identity == "section":
            current_section = unit.framing_identity
            containers[unit.framing_identity] = {"chapter": "stage78-procedural-pathway-report", "section": unit.framing_identity, "container": "article/section/h2"}
        else:
            if not current_section:
                raise ValueError("invalid_html_frame_authority")
            containers[unit.framing_identity] = {"chapter": "stage78-procedural-pathway-report", "section": current_section, "container": "article/section/p"}
    return containers


class _PathwayHtmlUnitParser(HTMLParser):
    _unit_tags = {"h1", "h2", "p"}
    _excluded_tags = {"head", "script", "style", "template", "noscript"}
    _void_tags = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.candidates: list[_PathwayHtmlCandidate] = []
        self.unframed_texts: list[str] = []
        self.malformed = False
        self._hidden_depth = 0
        self._stack: list[dict[str, str | bool]] = []
        self._current: dict[str, Any] | None = None

    @staticmethod
    def _hidden(attrs: Mapping[str, str]) -> bool:
        style = attrs.get("style", "").replace(" ", "").lower()
        return "hidden" in attrs or attrs.get("aria-hidden", "").lower() == "true" or "display:none" in style or "visibility:hidden" in style

    def handle_starttag(self, tag: str, attrs) -> None:
        attributes = dict(attrs)
        if self._hidden_depth:
            if tag not in self._void_tags:
                self._hidden_depth += 1
            return
        if tag in self._excluded_tags or self._hidden(attributes):
            self._hidden_depth = 1
            return
        identifier = attributes.get("id", "")
        parent = self._stack[-1] if self._stack else {"chapter": "", "section": "", "frame": "", "stage78": False}
        chapter = str(parent["chapter"])
        section = str(parent["section"])
        stage78 = bool(parent["stage78"])
        if tag == "article" and identifier.startswith("stage78-"):
            chapter = identifier
            section = ""
            stage78 = True
        elif tag == "section" and identifier.startswith("stage78-"):
            if not chapter:
                self.malformed = True
            section = identifier
            stage78 = True
        elif identifier.startswith("stage78-"):
            stage78 = True
        self._stack.append({"tag": tag, "frame": identifier, "chapter": chapter, "section": section, "stage78": stage78})
        is_unit = (
            (tag == "h1" and bool(chapter) and not section)
            or (tag == "h2" and bool(section))
            or (tag == "p" and identifier.startswith("stage78-"))
        )
        if stage78 and is_unit:
            if self._current is not None:
                self.malformed = True
            frame = identifier
            if not frame and tag == "h1":
                frame = chapter
            elif not frame and tag == "h2":
                frame = section
            if not frame:
                self.malformed = True
            self._current = {
                "frame": frame,
                "kind": "heading" if tag.startswith("h") else "body",
                "chapter": chapter,
                "section": section,
                "container": "article/h1" if tag == "h1" else "article/section/h2" if tag == "h2" else "article/section/p",
                "parts": [],
            }
        elif stage78 and tag in self._unit_tags:
            self._current = {"frame": "", "kind": "", "chapter": "", "section": "", "container": "", "parts": [], "unframed": True}

    def handle_endtag(self, tag: str) -> None:
        if self._hidden_depth:
            self._hidden_depth -= 1
            return
        if self._current is not None and tag in self._unit_tags:
            value = normalize_text("".join(self._current["parts"]))
            if self._current.get("unframed"):
                if value:
                    self.unframed_texts.append(value)
            elif value:
                self.candidates.append(_PathwayHtmlCandidate(
                    frame=self._current["frame"],
                    unit_kind=self._current["kind"],
                    value=value,
                    chapter_frame=self._current["chapter"],
                    section_frame=self._current["section"],
                    container=self._current["container"],
                    position=len(self.candidates),
                ))
            else:
                self.malformed = True
            self._current = None
        if not self._stack or self._stack[-1]["tag"] != tag:
            if tag in {"article", "section"} or any(bool(item["stage78"]) for item in self._stack):
                self.malformed = True
            return
        self._stack.pop()

    def handle_data(self, data: str) -> None:
        if self._hidden_depth or self._current is None:
            return
        self._current["parts"].append(data)


def _html_pathway_units(path: Path, expected: list[PathwayVisibleUnit]) -> tuple[list[PathwayVisibleUnit], list[dict[str, str]]]:
    html_path = path / "index.html" if path.is_dir() else path
    expected_by_frame = {unit.framing_identity: unit for unit in expected}
    if len(expected_by_frame) != len(expected):
        return [], [_pathway_failure("html", "artifact_structure", "duplicate_unit")]
    try:
        expected_containers = _html_expected_containers(expected)
    except Exception:
        return [], [_pathway_failure("html", "artifact_structure", "invalid_canonical_authority_input")]
    parser = _PathwayHtmlUnitParser()
    parser.feed(html_path.read_text(encoding="utf-8"))
    if parser.malformed:
        return [], [_pathway_failure("html", "artifact_structure", "malformed_artifact_structure")]
    for text in parser.unframed_texts:
        if any(text == unit.value for unit in expected):
            return [], [_pathway_failure("html", "artifact_structure", "missing_unit")]
    units: list[PathwayVisibleUnit] = []
    failures: list[dict[str, str]] = []
    seen_frames: set[str] = set()
    for candidate in parser.candidates:
        if candidate.frame in seen_frames:
            failures.append(_pathway_failure("html", "artifact_structure", "duplicate_unit"))
        seen_frames.add(candidate.frame)
        expected_unit = expected_by_frame.get(candidate.frame)
        if expected_unit is None:
            if candidate.frame.startswith("stage78-"):
                failures.append(_pathway_failure("html", "artifact_structure", "extra_unit"))
            continue
        expected_container = expected_containers[expected_unit.framing_identity]
        if (
            candidate.chapter_frame != expected_container["chapter"]
            or candidate.section_frame != expected_container["section"]
            or candidate.container != expected_container["container"]
            or candidate.unit_kind != expected_unit.unit_kind
        ):
            failures.append(_pathway_failure("html", expected_unit.field_identity, "framing_mismatch"))
        units.append(PathwayVisibleUnit(
            record_identity=expected_unit.record_identity,
            unit_kind=candidate.unit_kind,
            field_identity=expected_unit.field_identity,
            ordinal=expected_unit.ordinal,
            value=normalize_text(candidate.value),
            framing_identity=candidate.frame,
            sequence_position=candidate.position,
        ))
    missing = set(expected_by_frame) - seen_frames
    if missing:
        failures.append(_pathway_failure("html", "artifact_structure", "missing_unit"))
    return units, failures


_DOCX_VISIBLE_CONTAINERS = {
    "hyperlink", "smartTag", "customXml", "sdt", "sdtContent", "ins", "moveTo",
}
_DOCX_METADATA_CONTAINERS = {
    "pPr", "rPr", "bookmarkStart", "bookmarkEnd", "proofErr", "permStart", "permEnd",
    "commentRangeStart", "commentRangeEnd", "moveFromRangeStart", "moveFromRangeEnd",
    "moveToRangeStart", "moveToRangeEnd",
}
_DOCX_EXCLUDED_CONTAINERS = {"del", "moveFrom", "fldSimple"}
_DOCX_UNSUPPORTED_TEXT_CONTAINERS = {
    "AlternateContent", "Choice", "Fallback", "drawing", "pict", "txbxContent", "textbox",
}
_DOCX_TEXT_NODES = {"t", "tab", "br", "cr", "delText", "instrText"}
_DOCX_BOOKMARK_ID = re.compile(r"^[0-9]+$")


def _docx_local_name(node) -> str:
    return node.tag.rsplit("}", 1)[-1]


def _docx_subtree_has_text(node) -> bool:
    return any(_docx_local_name(descendant) in _DOCX_TEXT_NODES for descendant in node.iter())


def _docx_run_is_hidden(run) -> bool:
    properties = run.find(f"{{{WORD_NAMESPACE}}}rPr")
    return properties is not None and (
        properties.find(f"{{{WORD_NAMESPACE}}}vanish") is not None
        or properties.find(f"{{{WORD_NAMESPACE}}}webHidden") is not None
    )


def _docx_paragraph_text(paragraph, *, bookmark_id: str | None = None) -> tuple[str, str | None]:
    parts: list[str] = []
    failure: str | None = None

    def collecting(active_bookmark_depth: int) -> bool:
        return bookmark_id is None or active_bookmark_depth > 0

    def visit_children(children, *, active_bookmark_depth: int, excluded_depth: int, unsupported_depth: int, hidden_depth: int) -> int:
        nonlocal failure
        for child in children:
            tag = _docx_local_name(child)
            if tag == "bookmarkStart":
                if bookmark_id is not None and child.attrib.get(f"{{{WORD_NAMESPACE}}}id", "") == bookmark_id:
                    active_bookmark_depth += 1
                continue
            if tag == "bookmarkEnd":
                if bookmark_id is not None and child.attrib.get(f"{{{WORD_NAMESPACE}}}id", "") == bookmark_id:
                    active_bookmark_depth = max(0, active_bookmark_depth - 1)
                continue
            visit_node(
                child,
                active_bookmark_depth=active_bookmark_depth,
                excluded_depth=excluded_depth,
                unsupported_depth=unsupported_depth,
                hidden_depth=hidden_depth,
            )
        return active_bookmark_depth

    def visit_node(node, *, active_bookmark_depth: int, excluded_depth: int, unsupported_depth: int, hidden_depth: int) -> None:
        nonlocal failure
        tag = _docx_local_name(node)
        if tag in {"delText", "instrText"}:
            return
        if tag == "t":
            if collecting(active_bookmark_depth):
                if unsupported_depth:
                    failure = failure or "unsupported_text_container"
                elif not excluded_depth and not hidden_depth:
                    parts.append(node.text or "")
            return
        if tag == "tab":
            if collecting(active_bookmark_depth) and not excluded_depth and not hidden_depth:
                if unsupported_depth:
                    failure = failure or "unsupported_text_container"
                else:
                    parts.append("\t")
            return
        if tag in {"br", "cr"}:
            if collecting(active_bookmark_depth) and not excluded_depth and not hidden_depth:
                if unsupported_depth:
                    failure = failure or "unsupported_text_container"
                else:
                    parts.append("\n")
            return
        if tag == "r":
            visit_children(
                list(node),
                active_bookmark_depth=active_bookmark_depth,
                excluded_depth=excluded_depth,
                unsupported_depth=unsupported_depth,
                hidden_depth=hidden_depth + (1 if _docx_run_is_hidden(node) else 0),
            )
            return
        if tag in _DOCX_METADATA_CONTAINERS:
            return
        next_excluded = excluded_depth + (1 if tag in _DOCX_EXCLUDED_CONTAINERS else 0)
        unsupported = tag in _DOCX_UNSUPPORTED_TEXT_CONTAINERS or (
            tag not in _DOCX_VISIBLE_CONTAINERS
            and tag not in _DOCX_EXCLUDED_CONTAINERS
            and _docx_subtree_has_text(node)
        )
        next_unsupported = unsupported_depth + (1 if unsupported else 0)
        visit_children(
            list(node),
            active_bookmark_depth=active_bookmark_depth,
            excluded_depth=next_excluded,
            unsupported_depth=next_unsupported,
            hidden_depth=hidden_depth,
        )

    final_depth = visit_children(list(paragraph), active_bookmark_depth=0, excluded_depth=0, unsupported_depth=0, hidden_depth=0)
    if bookmark_id is not None and final_depth:
        failure = failure or "malformed_artifact_structure"
    return normalize_text("".join(parts)), failure


def _docx_paragraphs_in_order(node, *, in_table: bool = False, paragraphs: list[tuple[Any, bool]] | None = None) -> list[tuple[Any, bool]]:
    if paragraphs is None:
        paragraphs = []
    for child in list(node):
        tag = child.tag.rsplit("}", 1)[-1]
        child_in_table = in_table or tag in {"tbl", "tr", "tc"}
        if tag == "p":
            paragraphs.append((child, in_table))
        else:
            _docx_paragraphs_in_order(child, in_table=child_in_table, paragraphs=paragraphs)
    return paragraphs


def _docx_bookmarks(paragraph) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    starts: list[tuple[str, str]] = []
    ends: list[tuple[str, str]] = []
    for node in paragraph.iter():
        tag = node.tag.rsplit("}", 1)[-1]
        if tag == "bookmarkStart":
            name = node.attrib.get(f"{{{WORD_NAMESPACE}}}name", "")
            identifier = node.attrib.get(f"{{{WORD_NAMESPACE}}}id", "")
            if name.startswith((PATHWAY_DOCX_STRUCTURAL_PREFIX, PATHWAY_DOCX_VISIBLE_PREFIX)):
                starts.append((identifier, name))
        elif tag == "bookmarkEnd":
            identifier = node.attrib.get(f"{{{WORD_NAMESPACE}}}id", "")
            ends.append((identifier, ""))
    return starts, ends


def _docx_document_bookmark_graph_valid(root) -> bool:
    """Validate the complete document.xml bookmark graph before text extraction.

    Bookmark IDs are document-global ownership keys.  Every start and end must
    therefore be a distinct decimal identifier, occur exactly once, and form a
    properly nested start/end range.  A Stage 78-named start cannot share that
    key with any non-Stage-78 start.
    """

    starts: dict[str, bool] = {}
    ends: set[str] = set()
    stack: list[str] = []
    for node in root.iter():
        tag = _docx_local_name(node)
        if tag not in {"bookmarkStart", "bookmarkEnd"}:
            continue
        identifier = node.attrib.get(f"{{{WORD_NAMESPACE}}}id", "")
        if not _DOCX_BOOKMARK_ID.fullmatch(identifier):
            return False
        if tag == "bookmarkStart":
            is_stage78 = node.attrib.get(f"{{{WORD_NAMESPACE}}}name", "").startswith(
                (PATHWAY_DOCX_STRUCTURAL_PREFIX, PATHWAY_DOCX_VISIBLE_PREFIX)
            )
            if identifier in starts:
                return False
            starts[identifier] = is_stage78
            stack.append(identifier)
            continue
        if identifier in ends or identifier not in starts or not stack or stack[-1] != identifier:
            return False
        ends.add(identifier)
        stack.pop()
    return not stack and set(starts) == ends


def _docx_body_units(path: Path, expected: list[PathwayVisibleUnit]) -> tuple[list[PathwayVisibleUnit], list[dict[str, str]]]:
    with zipfile.ZipFile(path) as package:
        root = ElementTree.fromstring(package.read("word/document.xml"))
    body = root.find(f"{{{WORD_NAMESPACE}}}body")
    if body is None or not _docx_document_bookmark_graph_valid(root):
        return [], [_pathway_failure("docx", "artifact_structure", "malformed_artifact_structure")]
    contract = pathway_docx_frame_contract(expected)
    all_expected_tokens = contract["all_tokens"]
    structural_by_token = {token: frame for frame, token in contract["structural_token_by_frame"].items()}
    units: list[PathwayVisibleUnit] = []
    failures: list[dict[str, str]] = []
    seen_names: set[str] = set()
    seen_ids: set[str] = set()
    current_chapter = ""
    current_section = ""
    paragraph_by_bookmark_id: dict[str, int] = {}
    end_by_bookmark_id: dict[str, int] = {}
    paragraphs = _docx_paragraphs_in_order(body)
    for paragraph_index, (paragraph, in_table) in enumerate(paragraphs):
        starts, ends = _docx_bookmarks(paragraph)
        end_ids = {identifier for identifier, _ in ends}
        for identifier, _ in ends:
            if identifier:
                end_by_bookmark_id[identifier] = paragraph_index
        stage78_starts = [(identifier, name) for identifier, name in starts if name.startswith((PATHWAY_DOCX_STRUCTURAL_PREFIX, PATHWAY_DOCX_VISIBLE_PREFIX))]
        if len([name for _, name in stage78_starts if name.startswith(PATHWAY_DOCX_VISIBLE_PREFIX)]) > 1:
            failures.append(_pathway_failure("docx", "artifact_structure", "malformed_artifact_structure"))
        for identifier, name in stage78_starts:
            if not identifier or identifier in seen_ids or name in seen_names:
                failures.append(_pathway_failure("docx", "artifact_structure", "duplicate_unit"))
            seen_ids.add(identifier)
            seen_names.add(name)
            paragraph_by_bookmark_id[identifier] = paragraph_index
            if identifier not in end_ids:
                failures.append(_pathway_failure("docx", "artifact_structure", "malformed_artifact_structure"))
            if name not in all_expected_tokens:
                failures.append(_pathway_failure("docx", "artifact_structure", "extra_unit"))
        structural_tokens = [name for _, name in stage78_starts if name.startswith(PATHWAY_DOCX_STRUCTURAL_PREFIX)]
        visible_tokens = [name for _, name in stage78_starts if name.startswith(PATHWAY_DOCX_VISIBLE_PREFIX)]
        for token in structural_tokens:
            frame = structural_by_token.get(token, "")
            if frame == "stage78-procedural-pathway-report":
                current_chapter = frame
                current_section = ""
            elif frame.startswith("stage78-section-"):
                current_section = frame
        if not visible_tokens:
            text, text_failure = _docx_paragraph_text(paragraph)
            if text_failure:
                failures.append(_pathway_failure("docx", "artifact_structure", text_failure))
            if text and any(text == unit.value for unit in expected):
                failures.append(_pathway_failure("docx", "artifact_structure", "missing_unit"))
            continue
        visible_bookmark_ids = [identifier for identifier, name in stage78_starts if name.startswith(PATHWAY_DOCX_VISIBLE_PREFIX)]
        bookmark_id = visible_bookmark_ids[0]
        token = visible_tokens[0]
        unit = contract["unit_by_token"].get(token)
        text, text_failure = _docx_paragraph_text(paragraph, bookmark_id=bookmark_id)
        if text_failure:
            failures.append(_pathway_failure("docx", unit.field_identity if unit is not None else "artifact_structure", text_failure))
        if unit is None:
            failures.append(_pathway_failure("docx", "artifact_structure", "extra_unit"))
            continue
        if not text:
            failures.append(_pathway_failure("docx", unit.field_identity, "missing_unit"))
            continue
        expected_container = contract["container_by_frame"][unit.framing_identity]
        if in_table or not expected_container.startswith("body/p"):
            failures.append(_pathway_failure("docx", unit.field_identity, "framing_mismatch"))
        if unit.unit_kind != "heading" and f"section:{current_section}:" not in expected_container:
            failures.append(_pathway_failure("docx", unit.field_identity, "framing_mismatch"))
        if unit.unit_kind == "heading" and unit.field_identity == "chapter" and current_chapter != unit.framing_identity:
            failures.append(_pathway_failure("docx", unit.field_identity, "framing_mismatch"))
        units.append(PathwayVisibleUnit(
            record_identity=unit.record_identity,
            unit_kind=unit.unit_kind,
            field_identity=unit.field_identity,
            ordinal=unit.ordinal,
            value=normalize_text(text),
            framing_identity=unit.framing_identity,
            sequence_position=len(units),
        ))
    for identifier, start_index in paragraph_by_bookmark_id.items():
        if end_by_bookmark_id.get(identifier) != start_index:
            failures.append(_pathway_failure("docx", "artifact_structure", "malformed_artifact_structure"))
    missing = set(all_expected_tokens) - seen_names
    if missing:
        failures.append(_pathway_failure("docx", "artifact_structure", "missing_unit"))
    return units, failures


def _pdf_body_units(extraction: PdfTextExtraction, expected: list[PathwayVisibleUnit]) -> tuple[list[PathwayVisibleUnit], list[dict[str, str]]]:
    stream = _pdf_pathway_stream(extraction)
    if not expected or not stream:
        return [], [_pathway_failure("pdf", "chapter", "missing_unit")]
    cursor = 0
    units: list[PathwayVisibleUnit] = []
    for expected_unit in expected:
        match = _pdf_pathway_unit_pattern(expected_unit.value).match(stream, cursor)
        if match is None:
            reason = "precanonical_content" if expected_unit.sequence_position == 0 else "value_mismatch"
            return [], [_pathway_failure("pdf", expected_unit.field_identity, reason)]
        units.append(PathwayVisibleUnit(
            record_identity=expected_unit.record_identity,
            unit_kind=expected_unit.unit_kind,
            field_identity=expected_unit.field_identity,
            ordinal=expected_unit.ordinal,
            value=expected_unit.value,
            framing_identity=expected_unit.framing_identity,
            sequence_position=expected_unit.sequence_position,
        ))
        cursor = _pdf_consume_layout_separator(stream, match.end())
    if cursor != len(stream):
        return [], [_pathway_failure("pdf", "unit_count", "extra_unit")]
    return units, []


def _validate_trusted_pdf_conversion(
    conversion: PathwayTrustedPdfConversion | Mapping[str, Any] | None,
    *,
    docx_path: Path | None,
    pdf_path: Path,
    specification: Mapping[str, Any],
    model: Mapping[str, Any],
    governance_qualification: Mapping[str, Any] | None,
    governed_job_id: int | None,
    governed_attempt_count: int | None = None,
    retry_of_job_id: int | None = None,
) -> list[dict[str, str]]:
    if conversion is None or docx_path is None or not docx_path.is_file() or not pdf_path.is_file():
        return [_pathway_failure("pdf", "trusted_conversion", "trusted_conversion_binding_failure")]
    if not isinstance(conversion, Mapping) or set(conversion) != _PDF_CONVERSION_AUTHORITY_FIELDS:
        return [_pathway_failure("pdf", "trusted_conversion", "trusted_conversion_binding_failure")]
    if any(not isinstance(conversion.get(field), str) or not conversion[field].strip() for field in _PDF_CONVERSION_AUTHORITY_FIELDS):
        return [_pathway_failure("pdf", "trusted_conversion", "trusted_conversion_binding_failure")]
    try:
        expected = pathway_pdf_conversion_authority_record(
            model,
            specification,
            governance_qualification,
            governed_job_id=governed_job_id,
            governed_attempt_count=governed_attempt_count,
            retry_of_job_id=retry_of_job_id,
            docx_sha256=hashlib.sha256(docx_path.read_bytes()).hexdigest(),
            pdf_sha256=hashlib.sha256(pdf_path.read_bytes()).hexdigest(),
            converter_identity=conversion["converter_identity"],
            converter_version=conversion["converter_version"],
            created_at=conversion["created_at"],
        )
    except Exception:
        return [_pathway_failure("pdf", "job_identity", "trusted_conversion_binding_failure")]
    failures: list[dict[str, str]] = []
    for field in (
        "specification_sha256",
        "render_model_sha256",
        "governance_qualification_sha256",
        "source_docx_sha256",
        "pdf_sha256",
    ):
        value = conversion[field]
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            failures.append(_pathway_failure("pdf", field, "trusted_conversion_binding_failure"))
    if conversion["job_identity"] != expected["job_identity"]:
        failures.append(_pathway_failure("pdf", "job_identity", "trusted_conversion_binding_failure"))
    if not re.fullmatch(r"stage77-report-job:[1-9][0-9]*", conversion["job_identity"]):
        failures.append(_pathway_failure("pdf", "job_identity", "trusted_conversion_binding_failure"))
    for field, expected_value in expected.items():
        if conversion[field] != expected_value:
            failures.append(_pathway_failure("pdf", field, "trusted_conversion_binding_failure"))
    if conversion["conversion_record_digest"] != _pathway_sha256({key: value for key, value in conversion.items() if key != "conversion_record_digest"}):
        failures.append(_pathway_failure("pdf", "conversion_record_digest", "trusted_conversion_binding_failure"))
    return failures


def verify_pathway_pdf_conversion_event(
    conversion: Mapping[str, Any] | None,
    *,
    docx_path: Path,
    pdf_path: Path,
    specification: Mapping[str, Any],
    model: Mapping[str, Any],
    governance_qualification: Mapping[str, Any] | None,
    governed_job_id: int | None,
    governed_attempt_count: int | None,
    retry_of_job_id: int | None,
    registered_event: bool = False,
    historical_authority: Mapping[str, str] | None = None,
) -> None:
    """Strict post-execution verification of a byte-bound conversion event.

    Controller facts are independently rebuilt from the frozen report authority;
    execution observations are verified against the exact promoted bytes.
    """
    if registered_event:
        # Recovery cannot re-observe the child process.  A successfully
        # registered event is nevertheless only useful if its immutable
        # record, the independently persisted job facts, and the restored
        # artifact bytes still agree.  Fields which are event observations
        # remain protected by the canonical event digest.
        if conversion is None or not isinstance(conversion, Mapping) or set(conversion) != _PDF_CONVERSION_AUTHORITY_FIELDS:
            raise ValueError("invalid_pdf_conversion_event")
        if any(not isinstance(conversion.get(field), str) or not conversion[field].strip() for field in _PDF_CONVERSION_AUTHORITY_FIELDS):
            raise ValueError("invalid_pdf_conversion_event")
        if not docx_path.is_file() or not pdf_path.is_file():
            raise ValueError("invalid_pdf_conversion_event")
        digest = _pathway_sha256({key: value for key, value in conversion.items() if key != "conversion_record_digest"})
        if conversion["conversion_record_digest"] != digest:
            raise ValueError("invalid_pdf_conversion_event")
        job_identity = pathway_governed_job_identity(governed_job_id) if governed_job_id is not None else ""
        expected = {
            "job_identity": job_identity,
            "attempt_identity": f"{job_identity}:attempt:{governed_attempt_count}",
            "retry_predecessor_identity": "none" if retry_of_job_id is None else pathway_governed_job_identity(retry_of_job_id),
            "source_docx_artifact_identity": f"stage78-docx:{job_identity}:attempt:{governed_attempt_count}",
            "pdf_artifact_identity": f"stage78-pdf:{job_identity}:attempt:{governed_attempt_count}",
            "source_docx_sha256": hashlib.sha256(docx_path.read_bytes()).hexdigest(),
            "pdf_sha256": hashlib.sha256(pdf_path.read_bytes()).hexdigest(),
        }
        if not job_identity or any(conversion[key] != value for key, value in expected.items()):
            raise ValueError("invalid_pdf_conversion_event")
        for key, value in (historical_authority or {}).items():
            if key not in _PDF_CONVERSION_AUTHORITY_FIELDS or not isinstance(value, str) or conversion.get(key) != value:
                raise ValueError("invalid_pdf_conversion_event")
        if not re.fullmatch(r"[0-9a-f]{64}", conversion["source_docx_sha256"]) or not re.fullmatch(r"[0-9a-f]{64}", conversion["pdf_sha256"]):
            raise ValueError("invalid_pdf_conversion_event")
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[^\n]+Z", conversion["created_at"]):
            raise ValueError("invalid_pdf_conversion_event")
        return
    failures = _validate_trusted_pdf_conversion(
        conversion,
        docx_path=docx_path,
        pdf_path=pdf_path,
        specification=specification,
        model=model,
        governance_qualification=governance_qualification,
        governed_job_id=governed_job_id,
        governed_attempt_count=governed_attempt_count,
        retry_of_job_id=retry_of_job_id,
    )
    if failures:
        raise ValueError("invalid_pdf_conversion_event")


def validate_pathway_output_equivalence(
    model: Mapping[str, Any],
    *,
    specification: Mapping[str, Any] | None = None,
    governance_qualification: Mapping[str, Any] | None = None,
    docx_path: Path | None = None,
    html_path: Path | None = None,
    pdf_path: Path | None = None,
    trusted_pdf_conversion: PathwayTrustedPdfConversion | Mapping[str, Any] | None = None,
    governed_job_id: int | None = None,
    governed_attempt_count: int | None = None,
    retry_of_job_id: int | None = None,
) -> tuple[ValidationResult, PathwayOutputEquivalenceAudit]:
    """Validate rendered Stage 78 artifacts against the bounded pathway render model."""

    result = ValidationResult()
    if specification is None:
        specification = {
            "report_type": "procedural_pathway_report",
            "title": model.get("title") if isinstance(model, Mapping) else None,
            "rendering_profile": "internal_pathway_v1",
            "pathway_projection": {key: model.get(key) for key in (
                "canonical_record_reference", "projection_contract", "projection_version", "projection_digest",
                "inclusion_mode", "exclusion_rule", "coverage", "unavailable_families", "gaps",
            )} if isinstance(model, Mapping) else {},
        }
    try:
        expected = canonical_pathway_units(model, specification, governance_qualification)
    except Exception:
        result.add("Stage 78 pathway canonical authority", False, "invalid canonical authority input")
        return result, PathwayOutputEquivalenceAudit(failures=[_pathway_failure("authority", "canonical", "invalid_canonical_authority_input")])
    result.add("Stage 78 pathway canonical authority", True, f"{len(expected)} canonical units")
    failures: list[dict[str, str]] = []
    if docx_path is not None:
        try:
            docx_units, docx_failures = _docx_body_units(docx_path, expected)
            if not docx_failures:
                docx_failures.extend(_compare_pathway_units(expected, docx_units, format_name="docx"))
        except Exception:
            docx_failures = [_pathway_failure("docx", "artifact_structure", "malformed_artifact_structure")]
        failures.extend(docx_failures)
        result.add("Stage 78 DOCX pathway visible-unit equivalence", not docx_failures, _pathway_public_detail(docx_failures))
    if html_path is not None:
        try:
            html_units, html_failures = _html_pathway_units(html_path, expected)
            html_failures.extend(_compare_pathway_units(expected, html_units, format_name="html"))
        except Exception:
            html_failures = [_pathway_failure("html", "artifact_structure", "malformed_artifact_structure")]
        failures.extend(html_failures)
        result.add("Stage 78 HTML pathway visible-unit equivalence", not html_failures, _pathway_public_detail(html_failures))
    pdf_claim = ""
    if pdf_path is not None:
        pdf_binding_failures = _validate_trusted_pdf_conversion(
            trusted_pdf_conversion,
            docx_path=docx_path,
            pdf_path=pdf_path,
            specification=specification,
            model=model,
            governance_qualification=governance_qualification,
            governed_job_id=governed_job_id,
            governed_attempt_count=governed_attempt_count,
            retry_of_job_id=retry_of_job_id,
        )
        failures.extend(pdf_binding_failures)
        extraction = extract_pdf_text_result(pdf_path)
        if extraction.available and not pdf_binding_failures:
            pdf_units, pdf_failures = _pdf_body_units(extraction, expected)
            pdf_failures.extend(_compare_pathway_units(expected, pdf_units, format_name="pdf"))
            failures.extend(pdf_failures)
            pdf_claim = "PDF extracted page semantics match the canonical sequence under trusted pinned DOCX conversion; pixel-level semantic visibility is not independently proven."
            result.add("Stage 78 PDF trusted-conversion pathway equivalence", not pdf_failures, _pathway_public_detail(pdf_failures) if pdf_failures else pdf_claim)
        else:
            if not extraction.available:
                failures.append(_pathway_failure("pdf", "pdf_text_extraction", "pdf_extraction_backend_unavailable"))
            result.add("Stage 78 PDF trusted-conversion pathway equivalence", False, _pathway_public_detail(pdf_binding_failures) if pdf_binding_failures else extraction.reason)
    return result, PathwayOutputEquivalenceAudit(unit_count=len(expected), failures=failures, pdf_claim=pdf_claim)
