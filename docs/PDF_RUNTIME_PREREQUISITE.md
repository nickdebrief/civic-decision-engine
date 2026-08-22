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

Fresh deployments invoke `sh scripts/check_pdf_predeploy_gate.sh`. The
wrapper executes two fail-closed checks in this order:

1. `python scripts/check_pdf_runtime.py`
2. `python scripts/check_pdf_synthetic_conversion.py`

Railway does not start the application when either command returns non-zero.
The second checker creates a synthetic DOCX and PDF only inside an isolated
temporary directory, verifies one-page conversion, Poppler extraction,
ordered markers, metadata, attachments, annotations and cleanup, then removes
the complete directory. It never reads or writes `/data`, imports the CDE
application, invokes a route, or uses a report specification.

These are separate evidence levels: package presence in the final image;
successful execution of the runtime diagnostic; successful synthetic
conversion; and successful deployment-gate completion. A deployment that
passes the gate provides execution evidence for that exact image, but does not
make PDF an available Stage 75 format and does not implement Stage 76. Stage
76 remains blocked until a gated revision deploys successfully and receives
the later assurance required for governed PDF rendering. SSH host-key
verification is not weakened by this mechanism.

The repository JSON and focused tests validate only the source-controlled
configuration. They do not prove that a fresh Railway build succeeded, that a
deployed final container contains the packages, or that
`check_pdf_runtime.py` has executed successfully. A local Railpack plan could
not be generated because the `railpack` CLI is not installed here. The local
synthetic checker is expected to fail closed when the host lacks the required
toolchain; that result is not production evidence. A successful fresh Railway
deployment that passes both pre-deploy commands is the required execution
evidence for the exact image, but remains a runtime prerequisite rather than
Stage 76 implementation.

This is only a source-controlled runtime prerequisite. Stage 75 remains DOCX
and HTML only, and Stage 76 is not implemented or registered.
