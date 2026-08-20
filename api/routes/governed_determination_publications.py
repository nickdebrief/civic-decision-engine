"""Public inspection of explicitly published Stage 73 representations only."""

from __future__ import annotations

import os
import sqlite3
from html import escape
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

from api import record_governed_determination_publications as rg73

router = APIRouter()
DB_PATH = Path(os.getenv("RECORDS_DB_PATH", "records.db"))


def _read_publication(publication_id: int | None = None) -> list[dict]:
    if not DB_PATH.is_file():
        return []
    try:
        conn = sqlite3.connect(f"{DB_PATH.resolve().as_uri()}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
    except sqlite3.Error:
        return []
    try:
        if publication_id is None:
            return rg73.list_publications(conn, public_only=True)
        return [rg73.public_publication(conn, publication_id)]
    except (ValueError, sqlite3.Error, KeyError, TypeError):
        return []
    finally:
        conn.close()


def _page(items: list[dict], *, detail: bool = False) -> str:
    esc = lambda value: escape(str(value if value is not None else ""))
    if not items and detail:
        raise HTTPException(status_code=404, detail="published_determination_not_found")
    rows = "".join(f'<li><a href="/determinations/{esc(x["publication_id"])}">{esc(x["public_title"])}</a> · publication {esc(x["publication_id"])} · version {esc(x["publication_version"])}</li>' for x in items)
    body = rows or "<li>No published determinations are currently available.</li>"
    if detail:
        x = items[0]
        body = f'''<article><h1>{esc(x["public_title"])}</h1><p>{esc(x["public_representation"])}</p><dl><dt>Publication identity</dt><dd>{esc(x["publication_id"])}</dd><dt>Determination reference</dt><dd>{esc(x["determination_id"])}</dd><dt>Publication version</dt><dd>{esc(x["publication_version"])}</dd><dt>Reasons status</dt><dd>{esc(x["reasons_status"])}. Reasons visible is not reasons adequate.</dd><dt>Challenge warning</dt><dd>{esc(x["challenge_warning_text"])} Absence of a challenge from this view does not prove that no challenge exists.</dd><dt>Current effect</dt><dd>{esc(x["current_effect_status"])} as of {esc(x["effect_as_of"])}. Current effect represented is not legal effect established.</dd><dt>Authority</dt><dd>{esc(x["authority_representation"])}</dd><dt>Mandate</dt><dd>{esc(x["mandate_representation"])}</dd><dt>Limitations</dt><dd>{esc(x["limitations"])}</dd><dt>Redaction</dt><dd>{esc(x["redaction_notice"])}</dd><dt>Integrity digest</dt><dd><code>{esc(x["content_digest"])}</code></dd></dl><p>Publication makes a governed representation visible. It does not establish the determination correct.</p></article>'''
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Published Determinations</title><style>*{{box-sizing:border-box}}body{{margin:0;background:#f4f3ef;color:#222;font-family:system-ui,sans-serif}}main{{width:min(900px,calc(100% - 32px));margin:40px auto}}article,section{{background:#fff;border:1px solid #d8d4ca;padding:20px}}h1{{color:#143a52}}dt{{font-weight:700;margin-top:14px}}dd{{margin:4px 0;overflow-wrap:anywhere}}a{{color:#245d61}}</style></head><body><main><section><h1>Published Determinations</h1><p>No determination is public by default. This collection contains only governed publication snapshots explicitly made publicly available.</p><ul>{body}</ul></section></main></body></html>'''


@router.get("/determinations", response_class=HTMLResponse)
def published_determinations():
    return HTMLResponse(content=_page(_read_publication()))


@router.get("/determinations/{publication_id}", response_class=HTMLResponse)
def published_determination(publication_id: str):
    return HTMLResponse(content=_page(_read_publication(publication_id), detail=True))
