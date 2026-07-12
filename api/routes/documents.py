from __future__ import annotations

from html import escape
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse

from api.document_intake import (
    document_media_type,
    document_type_label,
    intake_root,
    is_image_document,
    list_published_documents,
    load_published_document,
    published_document_file,
)


router = APIRouter()

GOVERNANCE_STATEMENT = (
    "Documents displayed in this library have been explicitly marked as Published "
    "through the administrative workflow. Publication indicates intentional public "
    "availability. Publication does not certify legal status, evidential truth, or "
    "external validation."
)


def _not_found(exc: Exception):
    raise HTTPException(status_code=404, detail="public_document_not_found") from exc


def _date(value: object) -> str:
    return str(value or "Not available").split("T", 1)[0]


def _render_library(
    documents: list[dict],
    all_documents: list[dict],
    *,
    query: str | None,
    institution: str | None,
    category: str | None,
    publication_year: str | None,
) -> str:
    institutions = sorted(
        {str(item["institution_source"]) for item in all_documents}, key=str.casefold
    )
    categories = sorted({str(item["category"]) for item in all_documents}, key=str.casefold)
    years = sorted(
        {
            _date(item.get("publication_date"))[:4]
            for item in all_documents
            if _date(item.get("publication_date"))[:4].isdigit()
        },
        reverse=True,
    )

    def options(values: list[str], selected: str | None) -> str:
        return "".join(
            f'<option value="{escape(value)}"{" selected" if value == selected else ""}>{escape(value)}</option>'
            for value in values
        )

    rows = "".join(
        f"""<tr>
          <td><a href="/documents/{escape(item['intake_id'])}">{escape(item['title'])}</a></td>
          <td>{escape(item['institution_source'])}</td>
          <td>{escape(item['category'])}</td>
          <td>{escape(_date(item.get('publication_date')))}</td>
          <td>{escape(item['description'])}</td>
          <td>{escape(str(item.get('reference_identifier') or '—'))}</td>
        </tr>"""
        for item in documents
    ) or '<tr><td colspan="6">No published documents match these criteria.</td></tr>'
    active_query = urlencode(
        {
            key: value
            for key, value in {
                "q": query,
                "institution": institution,
                "category": category,
                "publication_year": publication_year,
            }.items()
            if value
        }
    )
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Public Document Library</title>
<style>*{{box-sizing:border-box}}body{{margin:0;background:#f7f7f4;color:#1f2933;font-family:system-ui,sans-serif}}main{{width:min(1180px,calc(100% - 32px));margin:32px auto 64px}}h1{{color:#143a52}}.governance{{max-width:900px;padding:16px;border-left:4px solid #2e8b9a;background:#fff}}form{{display:grid;grid-template-columns:2fr repeat(3,1fr) auto;gap:10px;margin:24px 0}}input,select,button{{min-width:0;padding:9px;border:1px solid #c9c6bd;background:#fff;font:inherit}}button{{border-color:#245d61;background:#245d61;color:#fff;cursor:pointer}}.table-wrap{{overflow-x:auto}}table{{width:100%;border-collapse:collapse;background:#fff;font-size:.9rem}}th{{background:#143a52;color:#fff;text-align:left}}th,td{{padding:10px;border:1px solid #e1dfd8;vertical-align:top;white-space:normal;overflow-wrap:break-word}}a{{color:#245d61}}.result-count{{color:#555}}@media(max-width:800px){{form{{grid-template-columns:1fr}}table{{min-width:900px}}}}</style></head>
<body><main><h1>Public Document Library</h1><p class="governance">{escape(GOVERNANCE_STATEMENT)}</p>
<form method="get" action="/documents"><input name="q" value="{escape(str(query or ''))}" placeholder="Search title, institution, category, or reference" aria-label="Search documents"><select name="institution" aria-label="Filter by institution"><option value="">All institutions</option>{options(institutions, institution)}</select><select name="category" aria-label="Filter by category"><option value="">All categories</option>{options(categories, category)}</select><select name="publication_year" aria-label="Filter by publication year"><option value="">All publication years</option>{options(years, publication_year)}</select><button type="submit">Search</button></form>
<p class="result-count">{len(documents)} published document{"s" if len(documents) != 1 else ""}.{f' Active query: {escape(active_query)}' if active_query else ''}</p><div class="table-wrap"><table><thead><tr><th>Title</th><th>Institution / Source</th><th>Category</th><th>Publication Date</th><th>Description</th><th>Reference Identifier</th></tr></thead><tbody>{rows}</tbody></table></div></main></body></html>"""


def _render_document(item: dict) -> str:
    provenance = (
        f"Uploaded through authenticated Admin Document Intake on {_date(item.get('upload_date'))}; "
        f"reviewed through the declared lifecycle and explicitly marked Published on "
        f"{_date(item.get('publication_date'))}. The SHA-256 digest identifies the original uploaded bytes."
    )
    fields = (
        ("Title", item["title"]),
        ("Description", item["description"]),
        ("Institution / Source", item["institution_source"]),
        ("Category", item["category"]),
        ("Publication Date", _date(item.get("publication_date"))),
        ("Document Date", item["document_date"]),
        ("Document Format", document_type_label(item.get("document_type"))),
        ("SHA-256", item["sha256_hash"]),
        ("Reference Identifier", item.get("reference_identifier") or "Not provided"),
    )
    rows = "".join(
        f"<tr><th>{escape(label)}</th><td>{escape(str(value))}</td></tr>"
        for label, value in fields
    )
    image_block = (
        f"""<h2>Document Image</h2><div class="public-document-image-wrap"><img class="public-document-image" src="/documents/{escape(item['intake_id'])}/view" alt="{escape(str(item['title']))}"></div><a class="download" href="/documents/{escape(item['intake_id'])}/view">View image</a> <a class="download" href="/documents/{escape(item['intake_id'])}/download">Download original image</a>"""
        if is_image_document(item)
        else f"""<a class="download" href="/documents/{escape(item['intake_id'])}/download">Download PDF</a>"""
    )
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>{escape(item['title'])}</title>
<style>*{{box-sizing:border-box}}body{{margin:0;background:#f7f7f4;color:#1f2933;font-family:system-ui,sans-serif}}main{{width:min(900px,calc(100% - 32px));margin:32px auto 64px}}h1,h2{{color:#143a52}}a{{color:#245d61}}.governance{{padding:14px;border-left:4px solid #2e8b9a;background:#fff}}table{{width:100%;border-collapse:collapse;background:#fff}}th,td{{padding:10px;border:1px solid #e1dfd8;text-align:left;vertical-align:top;overflow-wrap:anywhere}}th{{width:210px;background:#faf9f5;color:#555}}.public-document-image-wrap{{background:#fff;border:1px solid #e1dfd8;padding:12px;margin:18px 0}}.public-document-image{{display:block;max-width:100%;width:auto;height:auto}}.download{{display:inline-block;margin:18px 0;padding:10px 14px;background:#245d61;color:#fff;text-decoration:none}}</style></head>
<body><main><p><a href="/documents">Back to Public Document Library</a></p><h1>{escape(item['title'])}</h1><p class="governance">{escape(GOVERNANCE_STATEMENT)}</p><table>{rows}</table>{image_block}<h2>Provenance Summary</h2><p>{escape(provenance)}</p></main></body></html>"""


@router.get("/documents", response_class=HTMLResponse)
def public_document_library(
    q: str | None = Query(None),
    institution: str | None = Query(None),
    category: str | None = Query(None),
    publication_year: str | None = Query(None),
):
    root = intake_root()
    all_documents = list_published_documents(root=root)
    documents = list_published_documents(
        query=q,
        institution=institution,
        category=category,
        publication_year=publication_year,
        root=root,
    )
    return HTMLResponse(
        content=_render_library(
            documents,
            all_documents,
            query=q,
            institution=institution,
            category=category,
            publication_year=publication_year,
        )
    )


@router.get("/documents/{document_id}", response_class=HTMLResponse)
def public_document_page(document_id: str):
    try:
        item = load_published_document(document_id, root=intake_root())
    except ValueError as exc:
        _not_found(exc)
    return HTMLResponse(content=_render_document(item))


def _content_disposition(disposition: str, filename: str) -> str:
    safe_filename = str(filename or "document").replace("\\", "_").replace('"', "")
    safe_filename = Path(safe_filename).name
    return f'{disposition}; filename="{safe_filename}"'


@router.get("/documents/{document_id}/view")
def public_document_image_view(document_id: str):
    try:
        file_path, item = published_document_file(document_id, root=intake_root())
        if not is_image_document(item):
            raise ValueError("public_document_image_not_found")
    except ValueError as exc:
        _not_found(exc)
    return FileResponse(
        path=Path(file_path),
        media_type=document_media_type(item),
        headers={
            "Content-Disposition": _content_disposition(
                "inline",
                item["original_filename"],
            )
        },
    )


@router.get("/documents/{document_id}/download")
def public_document_download(document_id: str):
    try:
        file_path, item = published_document_file(document_id, root=intake_root())
    except ValueError as exc:
        _not_found(exc)
    headers = None
    if is_image_document(item):
        headers = {
            "Content-Disposition": _content_disposition(
                "attachment",
                item["original_filename"],
            )
        }
    return FileResponse(
        path=Path(file_path),
        media_type=document_media_type(item),
        filename=item["original_filename"],
        headers=headers,
    )
