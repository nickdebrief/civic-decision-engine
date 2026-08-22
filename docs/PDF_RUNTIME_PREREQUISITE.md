# Future Governed PDF Runtime Prerequisite

The first prerequisite deployment placed
`RAILPACK_DEPLOY_APT_PACKAGES` under `build.variables` in `railway.json`.
Although that variable is documented for Railpack's process environment, the
deployed image contained none of the declared system packages. That mechanism
is therefore not treated as effective repository configuration for this
service.

The corrected source-controlled configuration uses the Railpack overlay
`railpack.json` and its `deploy.aptPackages` array. The leading `"..."` keeps
Railpack's generated runtime packages while adding the packages required for
the future Stage 76 governed PDF capability:

- `libreoffice` and `soffice` for headless DOCX-to-PDF conversion;
- `poppler-utils` for `pdftotext`, `pdfinfo` and related utilities;
- `fontconfig`, `fonts-dejavu-core` and `fonts-liberation2` for deterministic
  internal-report font availability.

The pinned `pypdf` dependency is an additional structural inspection aid. It
does not replace mandatory Poppler text extraction for governed PDF output.

Run the read-only diagnostic after a fresh deployment:

```bash
python scripts/check_pdf_runtime.py
```

The diagnostic reports tool paths and versions, selected font availability,
Python and `pypdf` versions, and isolated ephemeral `/tmp` write/cleanup. It
does not import the application, access `/data`, read application records or
perform conversion. A missing mandatory prerequisite returns a non-zero exit
status.

The repository JSON and focused tests validate only the source-controlled
configuration. They do not prove that a fresh Railway build succeeded, that a
deployed final container contains the packages, or that
`check_pdf_runtime.py` has executed successfully. A local Railpack plan could
not be generated because the `railpack` CLI is not installed here. A synthetic
DOCX-to-PDF conversion is a later assurance step and is not performed by this
prerequisite or claimed here.

This is only a source-controlled runtime prerequisite. Stage 75 remains DOCX
and HTML only, and Stage 76 is not implemented or registered.
