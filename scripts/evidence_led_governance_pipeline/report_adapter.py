"""Render a frozen Stage 75 specification without importing CDE persistence."""

from __future__ import annotations

import hashlib
import json
import sys
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


ENGINE_VERSION = "2.0.0"


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
    request, output = map(Path, sys.argv[1:3])
    payload = json.loads(request.read_text(encoding="utf-8"))
    spec = payload["specification"]
    digest = payload["digest"]
    if spec.get("publication_engine_version") != ENGINE_VERSION or hashlib.sha256(canonical(spec).encode()).hexdigest() != digest:
        raise ValueError("specification validation failed")
    book = make_book(spec)
    effective = EffectiveTheme(theme=HANDBOOK_THEME, publication_profile=PUBLICATION_PROFILES["digital"], page=HANDBOOK_THEME.page, title_page=HANDBOOK_THEME.title_page, volume_page=HANDBOOK_THEME.volume_page, chapter_opening=HANDBOOK_THEME.chapter_opening)
    artifacts = []
    html_path = output / "report.html"
    docx_path = output / "report.docx"
    if "docx" in spec["requested_formats"]:
        DocxRenderer(effective).render(book, docx_path)
        validation, _ = validate_docx_output(docx_path, book)
        if not validation.ok:
            raise ValueError("docx validation failed")
        artifacts.append(docx_path)
    if "html" in spec["requested_formats"]:
        HtmlRenderer(effective, HtmlOutputConfig()).render(book, html_path)
        validation, _ = validate_html_output(html_path, "en")
        if not validation.ok:
            raise ValueError("html validation failed")
        artifacts.append(html_path)
    if len(artifacts) == 2:
        equivalence, _ = validate_cross_format_equivalence(book, docx_path=docx_path, html_path=html_path)
        if not equivalence.ok or not ordered_content_is_preserved(book, docx_path=docx_path, html_path=html_path):
            raise ValueError("cross-format validation failed")
    result = {"specification_digest": digest, "diagnostics": [], "artifacts": []}
    for path in artifacts:
        result["artifacts"].append({"format": path.suffix[1:], "path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "size_bytes": path.stat().st_size, "renderer_version": ENGINE_VERSION})
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
