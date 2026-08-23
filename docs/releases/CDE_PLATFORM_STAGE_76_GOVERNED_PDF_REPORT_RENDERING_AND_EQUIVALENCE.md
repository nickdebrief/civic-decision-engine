# CDE Platform Stage 76 — Governed PDF Report Rendering and Equivalence

Status: **Implemented · merged · deployed**

Stage 76 extends the internal Stage 75 `canonical_record_report` with private
PDF artifacts. The CDE remains the owner of the frozen report specification,
selected governed material, lifecycle, authorization and artifact records.
Publication Engine v2.0.0 remains a renderer and validator; it does not query
CDE persistence, select content, determine truth, approve distribution or
publish a report.

## Format contract

PDF is available only when DOCX and HTML are requested as companion formats.
DOCX is rendered first, HTML is rendered independently, and PDF is converted
from the staged DOCX with the verified headless LibreOffice toolchain. All
three outputs must pass strict ordered equivalence before any artifact is
promoted. PDF-only generation is rejected.

PDF validation requires LibreOffice conversion, `pdfinfo`, `pdftotext`,
`pypdf==5.9.0`, valid structure, bounded size and page count, ordered content,
safe metadata, no annotations, no embedded files and no unsafe actions.
Synchronous limits are 100 pages, 20 MiB per PDF, 120 seconds per subprocess
and 180 seconds for the PDF portion of an attempt. Failure cleans staged
outputs and records only bounded diagnostics.

## Boundaries

**A PDF PRESENTS THE APPROVED REPORT SPECIFICATION—IT DOES NOT ALTER IT.**

PDF rendering is not approval. Format equivalence is not legal validation.
Printing is not publication. Inclusion is not endorsement. Exclusion is not
proof of absence. A summary is not original language. A report is not a
determination. No public route, public artifact serving, external distribution,
Stage 73 integration, queue, print service or new report type is introduced.

The runtime prerequisite was separately verified on canonical revision
`1868c12b044a9cf9a36d7a31f41feffde39861f0`. Stage 76 was merged in PR #416
and deployed on canonical revision
`975cab0d95d03d074be51f9418f8896b635ee966` to production as deployment
`2dea23cf-8ad8-4fcc-a366-e29553f928c4` (created
`2026-08-23T05:54:16.401Z`, terminal success, final gate completion
`2026-08-23T05:55:02.880Z`). The exact revision matched. The runtime
diagnostic, low-level synthetic conversion, governed Stage 76 adapter and
independent cleanup gate all passed in order, followed by non-mutating smoke
checks. No production report, artifact or data was created or changed.

## Closure Evidence

The production adapter executed against the synthetic frozen specification
and validated DOCX, HTML and PDF output with strict ordered equivalence and
cleanup. PDF remains available only for the existing `canonical_record_report`
and requires DOCX and HTML companion validation. PDF rendering is not
approval, printing is not publication, and Publication Engine validation is
not legal validation.

Stage 75 remains the owner of report specifications, lifecycle, generation
requests, authorization and private artifacts. Publication Engine v2.0.0
remains a renderer and validator. Stage 73 public determination publication
is unchanged. No public Stage 76 route, external distribution, print service,
queue or new report type was introduced. Stage 76 remains internal,
authenticated and non-public.
