# Publication Engine v2

## Purpose

Publication Engine v2 is the first formal release of the repository's modular,
semantic, multi-format publishing pipeline.

It preserves chapter wording while separating source interpretation,
publication structure, visual configuration, rendering, validation, and
packaging into explicit stages.

## Architecture Evolution

### Publication Engine Stage 1 - Modular Foundation

Stage 1 separated the original builder into parser, data model, validator,
theme, renderer, and orchestration modules. It retained legacy chapter-source
compatibility and non-destructive publication versioning.

### Publication Engine Stage 2 - Canonical Document Model

Stage 2 introduced explicit front matter, volumes, chapters, sections,
subsections, paragraphs, lists, coded semantic objects, flows, source
provenance, parser diagnostics, and model invariants. The DOCX renderer became
a model-only consumer.

### Publication Engine Stage 3 - Publication Enrichment

Stage 3 added manifest-driven source order, stable identifiers, a publication
reference registry, explicit cross-references, generated contents and semantic
lists, a deterministic semantic index, Word bookmarks, and internal links.

### Publication Engine Stage 4 - Themes and Profiles

Stage 4 formalised typed theme configuration and safe registries. It added the
handbook, CDE, and CREF themes; digital, print, and archive profiles; Letter,
A4, and 6x9 page profiles; configurable title, volume, and chapter templates;
semantic callout theming; and manifest-driven document metadata.

### Publication Engine Stage 5 - Multi-format Publication

Stage 5 added native semantic HTML, LibreOffice-backed PDF generation,
format-specific output validation, cross-format content equivalence, internal
link audits, transactional output promotion, SHA-256 checksums, build reports,
and deterministic package manifests.

## Supported Publication Configuration

Publication Engine v2 supports:

- outputs: DOCX, single-file or directory HTML, and PDF;
- themes: `handbook`, `cde`, and `cref`;
- publication profiles: `digital`, `print`, and `archive`;
- page profiles: `letter`, `a4`, and `book_6x9`;
- title and volume templates: `institutional`, `minimal`, and `handbook`;
- chapter openings: `standard`, `display`, and `compact`;
- generated contents, semantic-object lists, and semantic index;
- stable bookmarks, internal links, and explicit cross-references;
- checksummed publication packages with machine-readable manifests.

## Canonical Build

Run from the repository root:

```bash
python3 scripts/evidence_led_governance_pipeline/build.py
```

The current canonical package is Evidence-Led Governance v1.19. Its tracked
release-candidate artifacts include DOCX, HTML, PDF, a build report, SHA-256
checksums, and a JSON package manifest.

## Release Validation Baseline

The Stage 5 certification baseline recorded:

- 8 source files;
- 2 front-matter entries;
- 1 volume and 5 chapters;
- 69 sections;
- 11 Governance Principles;
- 14 Canonical Definitions;
- 4 Research Findings;
- 5 Research Methodology objects;
- 2 Governance Architectures;
- 6 flow diagrams;
- 868 source-derived blocks present in DOCX, HTML, and PDF;
- 934 DOCX paragraphs and 36 tables;
- 120 DOCX bookmarks and 223 internal hyperlinks;
- 158 HTML anchors and 247 internal links;
- 52 PDF pages;
- zero broken DOCX or HTML internal links;
- zero parser, model, renderer, or package errors.

The release-preparation branch reruns compilation, the full repository tests,
the canonical multi-format build, checksum verification, cross-format
equivalence, theme smoke builds, and representative LibreOffice rendering.

## Release-preparation Verification

The release-preparation audit completed successfully on 31 July 2026:

- Python compilation completed without errors;
- 875 repository tests and 297 subtests passed;
- the canonical command generated a non-destructive v1.20 verification package;
- DOCX, HTML, PDF, build report, checksums, and package manifest were generated;
- all 13 recorded source, manifest, output, and report checksums matched;
- 868 of 868 source-derived blocks appeared in DOCX, HTML, and PDF;
- v1.20 and tracked v1.19 contained the same 1,139 normalized substantive DOCX blocks after excluding their generated version labels;
- handbook, CDE, and CREF multi-format smoke builds passed;
- representative title, volume, callout, and final DOCX/PDF pages rendered cleanly;
- HTML language, heading, identifier, asset, and internal-link audits passed;
- no chapter source or semantic model file changed.

The v1.20 verification artifacts were not added to Git because release
preparation changed documentation and dependency declarations only. The
tracked v1.19 package remains the canonical binary baseline for this pull
request.

## Repository and Output Audit

The v1.19 package is a complete validation baseline and should remain tracked
for the v2.0 release review. Earlier tracked DOCX files from v1.0 through v1.17
are intermediate development and equivalence baselines. They are not removed
in release preparation because binary-history removal requires a separate,
explicit retention decision.

Recommended post-release policy:

1. keep each formal release package in GitHub Release assets;
2. keep the latest canonical package and selected equivalence baselines in Git;
3. remove superseded intermediate binaries from `main` only through a separate reviewed cleanup;
4. never ignore canonical release outputs;
5. ignore only transient staging, caches, locks, and local render products.

The untracked `scripts/generate_initial_chapters.py` is a one-time migration
utility. It uses hard-coded source-document paragraph indexes, writes directly
to chapter files, covers only the initial source range, and is not part of the
current build. It should not be committed to the active pipeline. The
recommended action is to archive it with the original source conversion notes
outside the runtime path, then delete the local working copy after its
historical provenance has been confirmed.

## Dependency Audit

The Python implementation otherwise uses the standard library and
`python-docx`. The repository test process uses `pytest`. PDF generation and
validation depend on externally installed LibreOffice and Poppler tools; these
are documented system prerequisites rather than Python dependencies.

No new Publication Engine runtime capability or third-party parser is added by
release preparation.

## Reproducibility

The engine:

- reads an explicitly ordered TOML manifest;
- records source and output SHA-256 checksums;
- refuses to overwrite existing versions;
- validates all requested formats before atomic promotion;
- records renderer versions and build metadata;
- separates source-derived equivalence from generated publication text;
- preserves compatibility entry points;
- leaves chapter source wording unchanged.

The package timestamp and automatic publication version are intentionally
build-specific. LibreOffice version and platform font availability may produce
formatting or binary-level differences even when extracted substantive text is
equivalent.

## Known Limitations

- PDF production requires LibreOffice; PDF validation requires Poppler tools.
- PDF outlines depend on the conversion toolchain and are not guaranteed on every host.
- HTML accessibility checks are practical structural checks, not full WCAG certification.
- Word fields such as page numbers may require updating in a desktop Word processor.
- Exact DOCX/PDF binary reproducibility is not guaranteed across office-suite or font versions.
- Directory HTML is supported, but chapter-per-file HTML remains deferred.
- Historical intermediate DOCX retention still requires a post-release policy decision.

## Future Roadmap

Potential future work, outside the v2.0 release boundary, includes:

- automated CI publication builds with pinned office-suite images;
- chapter-per-file HTML output;
- stronger PDF outline preservation;
- formal accessibility testing with dedicated tooling;
- signed release manifests and provenance attestations;
- a documented retention workflow for historical binary baselines.

## Release Recommendation

Use distinct release identifiers so the engine release is not confused with
the Evidence-Led Governance manuscript version or the CDE application version:

- Publication Engine version: `2.0.0`;
- repository release label: `Publication Engine v2.0.0`;
- Git tag: `publication-engine-v2.0.0`;
- GitHub Release title: `Publication Engine v2.0.0`.

Do not create the tag or GitHub Release until this release-preparation pull
request is reviewed and merged and the release build is reproduced from its
merge commit.
