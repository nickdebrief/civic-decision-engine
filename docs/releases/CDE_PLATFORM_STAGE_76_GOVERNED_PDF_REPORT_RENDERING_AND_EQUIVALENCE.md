# CDE Platform Stage 76 — Governed PDF Report Rendering and Equivalence

Status: **Implemented · pending merge · pending deployment**

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
`1868c12b044a9cf9a36d7a31f41feffde39861f0`; that evidence is not Stage 76
implementation or deployment evidence. No production report was created.
