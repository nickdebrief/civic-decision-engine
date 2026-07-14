from __future__ import annotations

from html import escape

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse

from api import record_document_associations as rda
from api.document_intake import intake_root

router = APIRouter()

BOUNDARY_TEXT = (
    "This association records a declared and governed relationship between "
    "independently preserved public objects. It does not make the linked document "
    "evidence for the record, alter record verification, change document provenance "
    "or lifecycle, or independently establish evidential sufficiency, factual truth, "
    "authorship, legal status, responsibility, or external validation."
)


def _not_found(exc: Exception):
    raise HTTPException(status_code=404, detail="public_association_not_found") from exc


def _display(value: object) -> str:
    if value is None or value == "":
        return "—"
    return str(value)


def _date(value: object) -> str:
    return _display(value).split("T", 1)[0]


def _active_label(value: object) -> str:
    return "Active" if int(value or 0) == 1 else "Inactive"


def _visibility_label(value: object) -> str:
    return "Public" if int(value or 0) == 1 else "Private"


def _relationship_label(item: dict) -> str:
    return str(item.get("public_label") or rda.RELATIONSHIP_TYPES.get(str(item.get("relationship_type") or ""), item.get("relationship_type") or "—"))


def _render_pathway(events: list[dict]) -> str:
    rows = "".join(
        f"""<tr>
          <td class="association-pathway-timestamp">{escape(_display(event.get('timestamp')))}</td>
          <td class="association-pathway-action">{escape(_display(event.get('action_label')))}</td>
          <td class="association-pathway-actor">{escape(_display(event.get('actor')))}</td>
          <td class="association-pathway-state">{escape(_display(event.get('previous_state')))}</td>
          <td class="association-pathway-state">{escape(_display(event.get('new_state')))}</td>
          <td class="association-pathway-note">{escape(_display(event.get('note')))}</td>
        </tr>"""
        for event in events
    ) or '<tr><td colspan="6">No public-safe association pathway entries are available.</td></tr>'
    return f"""<section class="association-pathway"><h2>Association Pathway</h2><p class="association-governance-boundary">Association pathway is a public-safe projection of the association's administrative history. It is separate from record verification history, document Publication Pathway, Publication Provenance, Administrative Audit, and Document Intake lifecycle history.</p><div class="association-pathway-wrapper"><table class="association-pathway-table"><thead><tr><th class="association-pathway-timestamp">Timestamp</th><th class="association-pathway-action">Action</th><th class="association-pathway-actor">Recorded actor</th><th class="association-pathway-state">Previous active/public state</th><th class="association-pathway-state">New active/public state</th><th class="association-pathway-note">Public-safe note</th></tr></thead><tbody>{rows}</tbody></table></div></section>"""


def _render_association_page(item: dict, pathway: list[dict]) -> str:
    reference = str(item.get("public_reference") or "")
    canonical = f"/associations/{escape(reference)}"
    summary_fields = (
        ("Public association reference", reference),
        ("Relationship type", rda.RELATIONSHIP_TYPES.get(str(item.get("relationship_type") or ""), item.get("relationship_type"))),
        ("Public label", _relationship_label(item)),
        ("Public note", item.get("public_note")),
        ("Created timestamp", item.get("created_at")),
        ("Created actor", item.get("created_by")),
        ("Current association state", _active_label(item.get("is_active"))),
        ("Public visibility", _visibility_label(item.get("is_public"))),
        ("Linked-object eligibility", "Record and document are publicly eligible"),
    )
    record_fields = (
        ("Record reference", item.get("record_reference")),
        ("Record title or summary", item.get("record_title")),
        ("Generated date", item.get("record_generated_at")),
        ("Trajectory", item.get("record_trajectory")),
        ("Record version", item.get("record_version")),
    )
    document_fields = (
        ("Document title", item.get("document_title")),
        ("Document reference identifier", item.get("document_reference_identifier")),
        ("Institution / source", item.get("document_institution_source")),
        ("Category", item.get("document_category")),
        ("Document format", item.get("document_format")),
        ("Document date", item.get("document_date")),
        ("Publication date", item.get("document_publication_date")),
    )

    def rows(fields: tuple[tuple[str, object], ...]) -> str:
        return "".join(
            f"<tr><th>{escape(label)}</th><td>{escape(_display(value))}</td></tr>"
            for label, value in fields
        )

    pathway_html = _render_pathway(pathway)
    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Record–Document Association — {escape(reference)}</title><link rel="canonical" href="{canonical}"><meta name="description" content="Public record-document association {escape(reference)} linking {escape(str(item.get('record_reference') or ''))} and {escape(str(item.get('document_title') or ''))} without asserting evidential sufficiency or legal status."><style>*{{box-sizing:border-box}}body{{margin:0;background:#f7f7f4;color:#1f2933;font-family:system-ui,sans-serif}}main{{width:min(1040px,calc(100% - 32px));margin:32px auto 64px}}h1,h2{{color:#143a52}}a{{color:#245d61}}.association-reference{{font:700 .9rem ui-monospace,monospace;letter-spacing:.03em;color:#555}}.association-governance-boundary{{padding:14px;border-left:4px solid #2e8b9a;background:#fff;line-height:1.55}}.association-summary,.association-linked-record,.association-linked-document{{margin-top:26px}}table{{width:100%;border-collapse:collapse;background:#fff}}th,td{{padding:10px;border:1px solid #e1dfd8;text-align:left;vertical-align:top;overflow-wrap:anywhere}}th{{width:230px;background:#faf9f5;color:#555}}.association-linked-objects{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}.association-actions{{display:flex;flex-wrap:wrap;gap:12px;margin:18px 0}}.association-actions a{{display:inline-block;padding:10px 14px;background:#245d61;color:#fff;text-decoration:none}}.association-pathway-wrapper{{overflow-x:auto}}.association-pathway-table{{min-width:940px;table-layout:auto}}.association-pathway-timestamp{{min-width:180px;white-space:nowrap}}.association-pathway-action,.association-pathway-actor{{min-width:130px}}.association-pathway-state{{min-width:170px}}.association-pathway-note{{min-width:240px;width:100%}}@media(max-width:760px){{.association-linked-objects{{grid-template-columns:1fr}}.association-pathway-table{{min-width:880px}}}}</style></head><body><main class="public-association"><p><a href="/records">Back to Public Record Index</a> · <a href="/documents">Back to Public Document Library</a></p><p class="association-reference">{escape(reference)}</p><h1>Public Record–Document Association</h1><p class="association-governance-boundary">{escape(BOUNDARY_TEXT)}</p><section class="association-summary"><h2>Association Summary</h2><table>{rows(summary_fields)}</table></section><div class="association-actions"><a href="/verify/{escape(str(item.get('record_reference') or ''))}">View civic record</a><a href="/documents/{escape(str(item.get('document_id') or ''))}">View published document</a></div><div class="association-linked-objects"><section class="association-linked-record"><h2>Associated Civic Record</h2><table>{rows(record_fields)}</table></section><section class="association-linked-document"><h2>Associated Public Document</h2><table>{rows(document_fields)}</table></section></div>{pathway_html}</main></body></html>"""


@router.get("/associations/{association_reference}", response_class=HTMLResponse)
def public_association_page(association_reference: str):
    conn = rda.get_db()
    try:
        item = rda.get_public_association(conn, association_reference, root=intake_root())
        pathway = rda.public_association_history(conn, item["id"])
    except ValueError as exc:
        _not_found(exc)
    finally:
        conn.close()
    return HTMLResponse(content=_render_association_page(item, pathway))


@router.get("/associations", response_class=HTMLResponse)
def public_association_index(q: str | None = Query(None), relationship_type: str | None = Query(None)):
    conn = rda.get_db()
    try:
        items = [
            item
            for item in rda.list_associations(conn, root=intake_root(), q=q, relationship_type=relationship_type)
            if rda.public_association_is_eligible(item)
        ]
    finally:
        conn.close()
    rows = "".join(
        f"""<tr><td>{escape(str(item.get('public_reference') or ''))}</td><td>{escape(str(item.get('record_reference') or ''))}</td><td>{escape(str(item.get('document_title') or ''))}</td><td>{escape(str(item.get('document_reference_identifier') or '—'))}</td><td>{escape(_relationship_label(item))}</td><td>{escape(_date(item.get('created_at')))}</td><td><a href="/associations/{escape(str(item.get('public_reference') or ''))}">View association</a> · <a href="/verify/{escape(str(item.get('record_reference') or ''))}">View record</a> · <a href="/documents/{escape(str(item.get('document_id') or ''))}">View document</a></td></tr>"""
        for item in items
    ) or '<tr><td colspan="7">No public record-document associations match these criteria.</td></tr>'
    return HTMLResponse(content=f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Public Record–Document Associations</title><style>*{{box-sizing:border-box}}body{{margin:0;background:#f7f7f4;color:#1f2933;font-family:system-ui,sans-serif}}main{{width:min(1180px,calc(100% - 32px));margin:32px auto 64px}}h1{{color:#143a52}}a{{color:#245d61}}.governance{{padding:14px;border-left:4px solid #2e8b9a;background:#fff}}form{{display:flex;gap:10px;flex-wrap:wrap;margin:22px 0}}input,select,button{{padding:9px;border:1px solid #c9c6bd;background:#fff;font:inherit}}button{{background:#245d61;color:#fff}}.table-wrap{{overflow-x:auto}}table{{width:100%;min-width:980px;border-collapse:collapse;background:#fff}}th,td{{padding:10px;border:1px solid #e1dfd8;text-align:left;vertical-align:top;overflow-wrap:anywhere}}th{{background:#143a52;color:#fff}}</style></head><body><main><h1>Public Record–Document Associations</h1><p class="governance">Public associations are shown only when the association is active, public, and both linked public objects remain eligible. Association visibility does not establish evidential sufficiency, factual truth, legal status, authorship, or external validation.</p><form method="get" action="/associations"><input name="q" value="{escape(str(q or ''))}" placeholder="Search association, record, document, or note"><select name="relationship_type"><option value="">Any relationship type</option>{''.join(f'<option value="{escape(value)}"{" selected" if relationship_type == value else ""}>{escape(label)}</option>' for value, label in rda.RELATIONSHIP_TYPES.items())}</select><button type="submit">Search</button></form><div class="table-wrap"><table><thead><tr><th>Association reference</th><th>Record reference</th><th>Document title</th><th>Document reference</th><th>Relationship label</th><th>Created date</th><th>Actions</th></tr></thead><tbody>{rows}</tbody></table></div></main></body></html>""")
