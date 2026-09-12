"""Public read-only Stage 79 machine-readable snapshots."""
from __future__ import annotations
import os
import sqlite3
from pathlib import Path
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from api import governed_report_publications as publications

router = APIRouter()
DB_PATH = Path(os.getenv("RECORDS_DB_PATH", "records.db"))

@router.get("/governed-reports/{publication_id}.json")
def public_governed_report(publication_id: str):
    try:
        conn = sqlite3.connect(f"{DB_PATH.resolve().as_uri()}?mode=ro", uri=True); conn.row_factory = sqlite3.Row
    except sqlite3.Error:
        raise HTTPException(status_code=404, detail="governed_report_publication_not_found") from None
    try:
        item = publications.public_publication(conn, publication_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="governed_report_publication_not_found") from None
    finally:
        conn.close()
    if item.get("tombstone"):
        return JSONResponse(item, status_code=410, headers={"Cache-Control": "no-store"})
    return JSONResponse(item, media_type="application/json", headers={"ETag": '"' + publications.digest(item) + '"', "Cache-Control": "public, max-age=86400, immutable"})
