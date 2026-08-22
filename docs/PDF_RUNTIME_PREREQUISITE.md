# Future Governed PDF Runtime Prerequisite

This repository declares the system packages required for the future Stage 76
governed PDF capability through Railpack's supported
`RAILPACK_DEPLOY_APT_PACKAGES` build variable in `railway.json`:

- `libreoffice` and `soffice` for headless DOCX-to-PDF conversion;
- `poppler-utils` for `pdftotext`, `pdfinfo` and related utilities;
- `fontconfig`, `fonts-dejavu-core` and `fonts-liberation2` for deterministic
  internal-report font availability.

The pinned `pypdf` dependency is an additional structural inspection aid. It
does not replace mandatory Poppler text extraction for governed PDF output.

Run the read-only diagnostic after a deployment:

```bash
python scripts/check_pdf_runtime.py
```

The diagnostic reports tool paths and versions, selected font availability,
Python and `pypdf` versions, and isolated ephemeral `/tmp` write/cleanup. It
does not import the application, access `/data`, read application records or
perform conversion. A missing mandatory prerequisite returns a non-zero exit
status.

This is only a source-controlled runtime prerequisite. Stage 75 remains DOCX
and HTML only, and Stage 76 is not implemented or registered.
