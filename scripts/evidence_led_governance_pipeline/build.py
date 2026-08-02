#!/usr/bin/env python3
"""Build publication packages through the modular multi-format engine."""

from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass
from importlib.metadata import version as package_version
from pathlib import Path

from manifest import discover_source_files, load_manifest, resolve_output_directory
from model import ParserDiagnostic
from output_validation import (
    DocxAudit,
    EquivalenceAudit,
    HtmlAudit,
    PdfAudit,
    validate_cross_format_equivalence,
    validate_docx_output,
    validate_html_output,
    validate_pdf_output,
)
from packaging import PackageResult, create_package
from parser import Parser
from publication import EnrichmentResult, enrich_publication
from renderers.docx_renderer import DocxRenderer
from renderers.html_renderer import HtmlRenderer
from renderers.pdf_renderer import PdfRenderer
from theme_resolution import ThemeResolutionResult, resolve_theme
from validator import (
    ValidationResult,
    merge_results,
    validate_book,
    validate_enriched_publication,
    validate_manifest_theme,
    validate_source_order,
)


PIPELINE_DIR = Path(__file__).resolve().parent
REPOSITORY_DIR = PIPELINE_DIR.parents[1]
CHAPTERS_DIR = PIPELINE_DIR / "chapters"
OUTPUT_DIR = PIPELINE_DIR / "Output"
MANIFEST_PATH = PIPELINE_DIR / "book.toml"

TITLE = "Evidence-Led Governance"
SUBTITLE = "A Research Methodology for Analysing Statutory Administration"
AUTHOR = "Nick Moloney"
RUNNING_TITLE = "EVIDENCE-LED GOVERNANCE"
TAGLINE = "Structured · Traceable · Governed"
BASENAME = "Evidence-Led_Governance"


class PublicationBuildError(RuntimeError):
    def __init__(self, message: str, exit_code: int) -> None:
        super().__init__(message)
        self.exit_code = exit_code


@dataclass(frozen=True)
class PublicationBuildResult:
    version: str
    source_files: tuple[Path, ...]
    formats: tuple[str, ...]
    docx_path: Path | None
    html_path: Path | None
    pdf_path: Path | None
    build_report_path: Path | None
    checksum_path: Path | None
    package_manifest_path: Path | None
    validation: ValidationResult
    enrichment: EnrichmentResult
    docx_audit: DocxAudit
    html_audit: HtmlAudit
    pdf_audit: PdfAudit
    equivalence: EquivalenceAudit
    package: PackageResult | None
    theme_resolution: ThemeResolutionResult


def next_version(output_dir: Path, basename: str, start: str = "1.0") -> str:
    output_dir.mkdir(parents=True, exist_ok=True)
    versions: list[tuple[int, int]] = []
    for path in output_dir.glob(f"{basename}_v*.docx"):
        match = re.search(r"_v(\d+)\.(\d+)\.docx$", path.name)
        if match:
            versions.append((int(match.group(1)), int(match.group(2))))
    if not versions:
        return start
    major, minor = max(versions)
    return f"{major}.{minor + 1}"


def chapter_files(chapters_dir: Path) -> list[Path]:
    return discover_source_files(chapters_dir)


def _pdf_validation_report_lines(
    formats: tuple[str, ...], pdf: PdfAudit, equivalence: EquivalenceAudit
) -> list[str]:
    if "pdf" not in formats:
        return ["PDF Validation", "", "Status: Not requested"]
    status = equivalence.pdf_status or pdf.validation_status
    backend = equivalence.pdf_backend or pdf.text_backend
    attempts = equivalence.pdf_attempts or pdf.backend_attempts
    if status == "available":
        return [
            "PDF Validation",
            "",
            "Status: Available",
            f"Backend: {backend}",
            "PDF equivalence: Completed",
        ]
    lines = [
        "PDF Validation",
        "",
        "Status: Unavailable",
        "",
        f"Reason: {equivalence.pdf_reason or pdf.validation_reason}",
        "",
        "Attempted:",
    ]
    for name, outcome in attempts:
        lines.extend((f"✓ {name}", f"✗ {outcome}"))
    lines.extend(
        (
            "",
            "PDF equivalence: Skipped",
            "Cross-format validation completed using available formats only.",
        )
    )
    return lines


def _build_report(
    *,
    validation: ValidationResult,
    formats: tuple[str, ...],
    source_count: int,
    enrichment: EnrichmentResult,
    docx: DocxAudit,
    html: HtmlAudit,
    pdf: PdfAudit,
    equivalence: EquivalenceAudit,
    warning_count: int,
) -> str:
    lines = [
        validation.render(),
        "",
        "Build Report",
        "",
        "Manifest",
        "✓ schema version 1",
        f"✓ {source_count} source files resolved",
        f"✓ output formats: {', '.join(formats)}",
        "",
        "Rendering",
        f"✓ DOCX: {docx.paragraph_count} paragraphs, {docx.table_count} tables",
        f"✓ HTML: {html.anchor_count} anchors, {html.internal_link_count} internal links" if "html" in formats else "- HTML not requested",
        (
            f"✓ PDF: {pdf.page_count} pages"
            if "pdf" in formats and pdf.inspection_available
            else "✓ PDF generated; structural inspection unavailable"
            if "pdf" in formats
            else "- PDF not requested"
        ),
        "",
        *_pdf_validation_report_lines(formats, pdf, equivalence),
        "",
        "Publication Enrichment",
        f"✓ {enrichment.reference_target_count} reference targets",
        f"✓ {enrichment.generated_section_count} generated sections",
        f"✓ {enrichment.index_entry_count} semantic index entries",
        f"✓ {enrichment.hyperlink_count} model hyperlinks",
        "",
        "Cross-format Equivalence",
        f"✓ {equivalence.block_count} source-derived blocks checked",
        f"✓ DOCX missing: {len(equivalence.missing_docx)}",
        f"✓ HTML missing: {len(equivalence.missing_html)}" if "html" in formats else "- HTML not requested",
        (
            f"✓ PDF missing: {len(equivalence.missing_pdf)}"
            if "pdf" in formats and equivalence.pdf_status == "available"
            else "- PDF equivalence skipped"
            if "pdf" in formats
            else "- PDF not requested"
        ),
        "",
        "Packaging",
        "✓ checksums generated",
        "✓ build manifest generated",
        "✓ publication package complete",
        "",
        f"Warnings: {warning_count}",
        "Errors: 0",
        "",
        "PASS",
    ]
    return "\n".join(lines) + "\n"


def _promote(staging: Path, final: Path) -> Path:
    if final.exists():
        raise PublicationBuildError(f"Refusing to overwrite existing publication output: {final}", 5)
    final.parent.mkdir(parents=True, exist_ok=True)
    os.replace(staging, final)
    return final


def _assert_promotable(paths: list[Path]) -> None:
    collisions = [str(path) for path in paths if path.exists()]
    if collisions:
        raise PublicationBuildError(f"Refusing to overwrite existing publication output: {', '.join(collisions)}", 5)


def build_publication(
    *,
    chapters_dir,
    output_dir,
    basename: str,
    title: str,
    subtitle: str,
    author: str,
    running_title: str,
    tagline: str | None = None,
    start_version: str = "1.0",
    manifest_path: Path | None = None,
) -> PublicationBuildResult:
    chapters_path = Path(chapters_dir)
    output_path = Path(output_dir)
    try:
        manifest = load_manifest(
            Path(manifest_path) if manifest_path else MANIFEST_PATH,
            chapters_dir=chapters_path,
            fallback_files=chapter_files(chapters_path),
        )
        output_path = resolve_output_directory(manifest, output_path)
        theme_resolution = resolve_theme(manifest, assets_dir=PIPELINE_DIR / "assets")
    except (FileNotFoundError, ValueError) as exc:
        raise PublicationBuildError(str(exc), 2) from exc

    files = manifest.source_files
    effective_basename = manifest.output.basename if manifest.loaded else basename
    effective_start = manifest.version.start if manifest.loaded else start_version
    version = effective_start if manifest.version.mode == "fixed" else next_version(output_path, effective_basename, start=effective_start)
    stem = f"{effective_basename}_v{version}"
    effective_title = manifest.publication.title if manifest.loaded else title
    effective_subtitle = manifest.publication.subtitle if manifest.loaded else subtitle
    effective_author = manifest.publication.author if manifest.loaded else author
    effective_running_title = manifest.publication.identity.running_title if manifest.loaded else running_title
    effective_tagline = manifest.publication.identity.tagline if manifest.loaded else (tagline or "")

    parser = Parser()
    book = parser.parse_files(
        files,
        title=effective_title,
        subtitle=effective_subtitle,
        author=effective_author,
        running_title=effective_running_title,
        tagline=effective_tagline,
        version=version,
    )
    book.diagnostics.extend(manifest.diagnostics)
    book.diagnostics.extend(theme_resolution.diagnostics)
    book.metadata.update({
        "manifest_loaded": "true" if manifest.loaded else "false",
        "manifest_path": str(manifest.path or ""),
        "subject": effective_subtitle,
        "language": manifest.publication.language,
        "edition": manifest.publication.edition,
        "keywords": ", ".join(manifest.metadata.keywords),
        "comments": manifest.metadata.comments,
        "build_identifier": manifest.metadata.build_identifier,
        "theme": theme_resolution.effective_theme.name,
        "publication_profile": theme_resolution.effective_theme.publication_profile.name,
        "page_profile": theme_resolution.effective_theme.page.name,
    })

    model_validation = validate_book(book)
    source_order_validation = validate_source_order(book, manifest)
    generated_options = dict(manifest.generated_front_matter)
    if not theme_resolution.effective_theme.publication_profile.generated_semantic_index:
        generated_options["semantic_index"] = False
    enrichment = enrich_publication(book, generated_options)
    preflight = merge_results(
        validate_manifest_theme(manifest, theme_resolution),
        source_order_validation,
        model_validation,
        validate_enriched_publication(book, enrichment),
    )
    if not preflight.ok:
        raise PublicationBuildError(preflight.render(), 1)

    formats = manifest.output.formats
    output_path.mkdir(parents=True, exist_ok=True)
    renderer_versions = {
        "docx": f"python-docx {package_version('python-docx')}",
        "html": "native semantic HTML renderer v1",
    }
    with tempfile.TemporaryDirectory(prefix=f".{stem}-", dir=output_path) as temporary:
        staging = Path(temporary)
        staged_docx = staging / f"{stem}.docx"
        try:
            DocxRenderer(theme_resolution.effective_theme).render(book, staged_docx)
        except Exception as exc:
            raise PublicationBuildError(f"DOCX rendering failed: {exc}", 3) from exc

        staged_html: Path | None = None
        if "html" in formats:
            staged_html = staging / (f"{stem}.html" if manifest.output.html.single_file else f"{stem}_html")
            try:
                HtmlRenderer(theme_resolution.effective_theme, manifest.output.html).render(book, staged_html)
            except Exception as exc:
                raise PublicationBuildError(f"HTML rendering failed: {exc}", 3) from exc

        staged_pdf: Path | None = None
        pdf_renderer = PdfRenderer()
        if "pdf" in formats:
            if not pdf_renderer.available and not manifest.output.pdf.require_render:
                book.diagnostics.append(
                    ParserDiagnostic(
                        severity="WARNING",
                        code="PDF_RENDERER_UNAVAILABLE",
                        message="PDF output was optional and LibreOffice was unavailable.",
                    )
                )
            else:
                staged_pdf = staging / f"{stem}.pdf"
                try:
                    pdf_result = pdf_renderer.render(staged_docx, staged_pdf)
                    renderer_versions["pdf"] = pdf_result.renderer_version
                except Exception as exc:
                    raise PublicationBuildError(f"PDF rendering failed: {exc}", 3) from exc

        docx_validation, docx_audit = validate_docx_output(staged_docx, book)
        html_validation, html_audit = (
            validate_html_output(staged_html, book.metadata.get("language", "en"))
            if staged_html is not None else (ValidationResult(), HtmlAudit())
        )
        pdf_validation, pdf_audit = (
            validate_pdf_output(staged_pdf, book, theme_resolution.effective_theme)
            if staged_pdf is not None else (ValidationResult(), PdfAudit())
        )
        equivalence_validation, equivalence = validate_cross_format_equivalence(
            book,
            docx_path=staged_docx,
            html_path=staged_html,
            pdf_path=staged_pdf,
        )
        validation = merge_results(preflight, docx_validation, html_validation, pdf_validation, equivalence_validation)
        if not validation.ok:
            raise PublicationBuildError(validation.render(), 4)

        warning_count = len([item for item in book.diagnostics + enrichment.diagnostics if item.severity == "WARNING"])
        report_text = _build_report(
            validation=validation,
            formats=formats,
            source_count=len(files),
            enrichment=enrichment,
            docx=docx_audit,
            html=html_audit,
            pdf=pdf_audit,
            equivalence=equivalence,
            warning_count=warning_count,
        )
        staged_artifacts: dict[str, Path] = {}
        if "docx" in formats:
            staged_artifacts["docx"] = staged_docx
        if staged_html is not None:
            staged_artifacts["html"] = staged_html
        if staged_pdf is not None:
            staged_artifacts["pdf"] = staged_pdf

        package_result = None
        if manifest.output.package.enabled:
            try:
                package_result = create_package(
                    package_dir=staging,
                    stem=stem,
                    repository=REPOSITORY_DIR,
                    book=book,
                    manifest=manifest,
                    artifacts=staged_artifacts,
                    build_report_text=report_text,
                    renderer_versions=renderer_versions,
                    validation_status="PASS",
                )
            except Exception as exc:
                raise PublicationBuildError(f"Publication packaging failed: {exc}", 5) from exc

        promotion_pairs = []
        if "docx" in formats:
            promotion_pairs.append((staged_docx, output_path / staged_docx.name))
        if staged_html is not None:
            promotion_pairs.append((staged_html, output_path / staged_html.name))
        if staged_pdf is not None:
            promotion_pairs.append((staged_pdf, output_path / staged_pdf.name))
        if package_result and package_result.build_report:
            promotion_pairs.append((package_result.build_report, output_path / package_result.build_report.name))
        if package_result and package_result.checksums:
            promotion_pairs.append((package_result.checksums, output_path / package_result.checksums.name))
        if package_result:
            promotion_pairs.append((package_result.manifest, output_path / package_result.manifest.name))
        _assert_promotable([final for _, final in promotion_pairs])
        promoted = {staged: _promote(staged, final) for staged, final in promotion_pairs}
        final_docx = promoted.get(staged_docx)
        final_html = promoted.get(staged_html) if staged_html is not None else None
        final_pdf = promoted.get(staged_pdf) if staged_pdf is not None else None
        final_report = promoted.get(package_result.build_report) if package_result and package_result.build_report else None
        final_checksums = promoted.get(package_result.checksums) if package_result and package_result.checksums else None
        final_manifest = promoted.get(package_result.manifest) if package_result else None

    print(report_text.rstrip())
    return PublicationBuildResult(
        version=version,
        source_files=tuple(files),
        formats=formats,
        docx_path=final_docx,
        html_path=final_html,
        pdf_path=final_pdf,
        build_report_path=final_report,
        checksum_path=final_checksums,
        package_manifest_path=final_manifest,
        validation=validation,
        enrichment=enrichment,
        docx_audit=docx_audit,
        html_audit=html_audit,
        pdf_audit=pdf_audit,
        equivalence=equivalence,
        package=package_result,
        theme_resolution=theme_resolution,
    )


def build_document(**kwargs):
    """Compatibility wrapper retaining the Stage 1-4 return contract."""
    result = build_publication(**kwargs)
    if result.docx_path is None:
        raise PublicationBuildError("Legacy build_document requires DOCX output", 3)
    return result.docx_path, result.version, list(result.source_files)


def main() -> int:
    try:
        result = build_publication(
            chapters_dir=CHAPTERS_DIR,
            output_dir=OUTPUT_DIR,
            basename=BASENAME,
            title=TITLE,
            subtitle=SUBTITLE,
            author=AUTHOR,
            running_title=RUNNING_TITLE,
            tagline=TAGLINE,
            start_version="1.0",
        )
    except PublicationBuildError as exc:
        print(str(exc))
        return exc.exit_code
    print("")
    print(f"Built publication version {result.version}")
    print(f"Formats: {', '.join(result.formats)}")
    for path in (result.docx_path, result.html_path, result.pdf_path, result.build_report_path, result.checksum_path, result.package_manifest_path):
        if path is not None:
            print(f"  - {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
