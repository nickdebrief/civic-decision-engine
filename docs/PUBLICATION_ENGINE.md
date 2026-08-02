# Publication Engine v2

## Purpose

Publication Engine v2 is the repository's deterministic, manifest-driven
publishing pipeline. It converts semantic chapter sources into validated DOCX,
HTML, and PDF publications without requiring format-specific markup in the
source text.

The engine is separate from the Civic Decision Engine application runtime. It
does not change CDE records, CREF methodology, document governance, or chapter
wording.

## Canonical Build

From the repository root, run:

```bash
python3 scripts/evidence_led_governance_pipeline/build.py
```

The build is non-destructive. Automatic versioning selects the next available
publication version and refuses to overwrite existing output files.

Compatibility entry points remain available:

```bash
python3 scripts/evidence_led_governance_pipeline/build_evidence_led_governance.py
```

Legacy imports through `build_v2_addendum_docx.py` delegate to the modular
engine.

## Architecture

The build follows one controlled sequence:

```text
Manifest and sources
  -> semantic parser
  -> canonical document model
  -> model validation
  -> publication enrichment
  -> theme and profile resolution
  -> DOCX, HTML, and PDF renderers
  -> output and cross-format validation
  -> checksums, report, and package manifest
```

The principal modules are:

- `book.toml`: source order, publication identity, output, layout, and generated-section configuration.
- `parser.py`: explicit and legacy source interpretation.
- `model.py`: data-only publication objects and typed manifest configuration.
- `validator.py`: model, manifest, identifier, provenance, and enrichment checks.
- `publication.py`: stable identifiers, reference resolution, generated lists, and semantic index construction.
- `theme_resolution.py`: safe resolution of themes, publication profiles, page profiles, templates, and assets.
- `renderers/docx_renderer.py`: DOCX traversal and Word structures.
- `renderers/html_renderer.py`: semantic HTML5 and deterministic theme-derived CSS.
- `renderers/pdf_renderer.py`: headless LibreOffice conversion from validated DOCX.
- `output_validation.py`: DOCX, HTML, PDF, accessibility, link, and cross-format audits.
- `packaging.py`: SHA-256 checksums, build reports, and deterministic JSON manifests.
- `build.py`: orchestration, error categories, staging, and atomic promotion.

Renderers consume the enriched model and resolved theme. They do not parse
source files or interpret manifest syntax.

## Manifest

`scripts/evidence_led_governance_pipeline/book.toml` uses schema version 1.
The manifest controls:

- ordered chapter source files;
- title, subtitle, author, language, edition, and publication identity;
- automatic or fixed publication versioning;
- requested output formats and output directory;
- publication theme and profile;
- page, title, volume, and chapter-opening templates;
- generated contents, semantic-object lists, and semantic index;
- optional publication assets;
- DOCX metadata and package behavior.

Unknown schema versions, themes, profiles, page layouts, output formats, or
unsafe output and asset paths stop the build. If the manifest is absent, the
legacy DOCX-only discovery path remains available with a warning.

## Themes and Profiles

The safe theme registry contains:

- `handbook`: the Evidence-Led Governance handbook identity;
- `cde`: Civic Decision Engine publication identity;
- `cref`: Civic Record Exchange Framework publication identity.

Publication profiles are:

- `digital`: colour callouts, visible links, bookmarks, and semantic index;
- `print`: print-safe margins and restrained link styling;
- `archive`: conservative styling, stable metadata, and archival footer.

Page profiles are `letter`, `a4`, and `book_6x9`. Title-page templates are
`institutional`, `minimal`, and `handbook`; volume-page templates use the same
names; chapter-opening templates are `standard`, `display`, and `compact`.

The theme provides visual configuration only. Semantic meaning remains in the
canonical model.

## Output Formats

### DOCX

The DOCX renderer uses `python-docx`. It creates publication styles, title and
volume pages, semantic callouts, flow diagrams, Word bookmarks, internal
hyperlinks, generated lists, and document metadata.

### HTML

The native HTML renderer emits semantic HTML5 with stable model identifiers,
embedded theme-derived CSS, internal navigation, accessible landmarks, a skip
link, semantic callouts, and validated internal links. The manifest supports a
self-contained file or a directory containing `index.html`, `styles.css`, and
assets.

### PDF

PDF is generated from the staged DOCX through LibreOffice in headless mode.
Where available, `pdfinfo` validates page count, metadata, and page dimensions.
For representative text and cross-format content equivalence, the engine uses
the first available extraction backend:

1. `pdftotext` (preferred);
2. `pypdf`;
3. `pdfminer.six`.

If none is available, PDF text equivalence is reported as unavailable and
skipped. DOCX and HTML validation, PDF generation, checksums, the package
manifest, and the build report continue normally.

LibreOffice remains the external PDF rendering tool. Poppler is preferred for
PDF inspection and text extraction but is not required for text equivalence.
`pypdf` and `pdfminer.six` are optional fallback backends, not mandatory Python
package dependencies. A requested required PDF still fails clearly when the
configured PDF renderer is unavailable.

## Validation

The release build validates:

- manifest schema and source order;
- parser diagnostics and source provenance;
- chapter, section, list, callout, and flow structure;
- semantic codes, identifiers, bookmarks, references, and generated targets;
- theme tokens, colour values, contrast, typography, margins, and assets;
- DOCX reopening, metadata, tables, bookmarks, and internal links;
- HTML parsing, language, heading hierarchy, IDs, links, and assets;
- PDF opening, page count, metadata, page profile, and expected text;
- source-derived content equivalence across DOCX, HTML, and PDF;
- unresolved reference markup in every requested format;
- source and artifact SHA-256 checksums.

The HTML checks are practical accessibility checks, not a claim of complete
WCAG conformance.

## Failure and Promotion

Rendering occurs in a private staging directory under the configured output
directory. Requested formats are validated before any artifact is promoted.
Existing output files are never overwritten. A failed build removes its
temporary staging directory and returns a non-zero category:

1. model or validation failure;
2. manifest or configuration failure;
3. rendering failure;
4. output-validation failure;
5. packaging failure.

## Publication Package

When packaging is enabled, one version produces:

```text
<basename>_v<version>.docx
<basename>_v<version>.html
<basename>_v<version>.pdf
<basename>_v<version>_build_report.txt
<basename>_v<version>_checksums.sha256
<basename>_v<version>_manifest.json
```

The JSON manifest records source files and checksums, output checksums,
renderers, theme, publication profile, page profile, Git commit available at
build time, timestamp, and validation status.

## Dependencies

Python dependencies are declared in `requirements.txt`. Publication Engine v2
requires Python 3.11 or later for `tomllib`, plus `python-docx`. The repository
test workflow uses `pytest`.

The release host must provide:

- LibreOffice for DOCX-to-PDF rendering.

For PDF text-equivalence validation, the engine selects the first available
backend: Poppler `pdftotext`, `pypdf`, then `pdfminer.six`. If none is present,
PDF equivalence is skipped while the remaining publication build completes.

## Output Retention

The current complete, validated package should remain tracked for release
review. Historical intermediate DOCX builds are useful as equivalence
baselines, but they should not accumulate indefinitely on `main`. After the
v2.0 release is published, retain the formal release package and selected
comparison baselines in Git; move superseded intermediate binaries to GitHub
Release assets or an external archive through a separate, reviewed cleanup.

Do not ignore canonical release outputs. Ignore only incomplete staging,
temporary render directories, office locks, caches, and editor files.

## Release Workflow

1. Start from a clean, current `main` branch.
2. Install the declared Python dependencies in a clean environment.
3. Confirm LibreOffice is available and note which PDF validation backend the
   build selects (`pdftotext`, `pypdf`, or `pdfminer.six`).
4. Run compilation and the full test suite.
5. Run the canonical build command.
6. Confirm zero validation errors and review warnings.
7. Verify DOCX, HTML, PDF, checksums, report, and package manifest.
8. Render representative DOCX and PDF pages and inspect layout.
9. Perform handbook, CDE, and CREF theme smoke builds without changing chapter sources.
10. Review the staged diff and exclude local tools or generated scratch files.
11. Merge the release-preparation pull request.
12. Tag and publish the release from the verified merge commit.

Recommended first formal release identifiers are documented in
`docs/releases/PUBLICATION_ENGINE_V2.md`.
