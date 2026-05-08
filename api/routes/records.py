from __future__ import annotations

import json
import sqlite3
import hashlib
import os
from html import escape
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

from api.models import RecordPayload, RecordResponse

router = APIRouter()

DB_PATH = Path(os.getenv("RECORDS_DB_PATH", "records.db"))


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS records (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            reference         TEXT NOT NULL,
            version           INTEGER NOT NULL DEFAULT 1,
            supersedes        TEXT,
            generated_at      TEXT NOT NULL,
            trajectory        TEXT,
            system_state      TEXT,
            conditions_json   TEXT,
            signals_json      TEXT,
            finding           TEXT,
            report_json       TEXT,
            language          TEXT NOT NULL DEFAULT 'en',
            generated_by      TEXT NOT NULL DEFAULT 'Civic Decision Engine',
            verification_hash TEXT NOT NULL,
            exported_at       TEXT NOT NULL,
            is_latest         INTEGER NOT NULL DEFAULT 1
        )
    """)
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_records_reference_version
        ON records(reference, version)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_records_reference_latest
        ON records(reference, is_latest)
    """)
    conn.commit()
    conn.close()


init_db()


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def compute_verification_hash(
    reference: str,
    generated_at: str,
    finding: str,
    trajectory: str,
    conditions: list[str],
    system_state: str,
    generated_by: str = "Civic Decision Engine",
) -> str:
    canonical = {
        "reference": reference,
        "generated_at": generated_at,
        "finding": finding,
        "trajectory": trajectory,
        "conditions": sorted(conditions),
        "system_state": system_state,
        "generated_by": generated_by,
    }
    payload = json.dumps(canonical, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@router.post("/records", response_model=RecordResponse)
async def create_record(payload: RecordPayload):
    conn = get_db()
    try:
        cur = conn.cursor()

        cur.execute(
            "SELECT version FROM records WHERE reference = ? ORDER BY version DESC LIMIT 1",
            (payload.reference,),
        )

        existing = cur.fetchone()
        new_version = existing["version"] + 1 if existing else 1
        is_superseding = existing is not None
        supersedes = (
            f"{payload.reference}:v{new_version - 1}" if is_superseding else None
        )

        if is_superseding:
            cur.execute(
                "UPDATE records SET is_latest = 0 WHERE reference = ?",
                (payload.reference,),
            )

        verification_hash = compute_verification_hash(
            reference=payload.reference,
            generated_at=payload.generated_at,
            finding=payload.finding,
            trajectory=payload.trajectory,
            conditions=payload.conditions,
            system_state=payload.system_state,
        )

        exported_at = datetime.now(timezone.utc).isoformat()

        cur.execute(
            """
            INSERT INTO records (
                reference, version, supersedes, generated_at,
                trajectory, system_state, conditions_json,
                signals_json, finding, report_json, language,
                verification_hash, exported_at, is_latest
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (
                payload.reference,
                new_version,
                supersedes,
                payload.generated_at,
                payload.trajectory,
                payload.system_state,
                json.dumps(payload.conditions),
                json.dumps(payload.signals),
                payload.finding,
                json.dumps(payload.report),
                payload.language,
                verification_hash,
                exported_at,
            ),
        )

        conn.commit()

        verify_url = f"https://civic-decision-engine-production.up.railway.app/verify/{payload.reference}"

        return RecordResponse(
            reference=payload.reference,
            version=new_version,
            verification_hash=verification_hash,
            verify_url=verify_url,
            is_superseding=is_superseding,
        )

    finally:
        conn.close()


@router.get("/verify/{reference}", response_class=HTMLResponse)
async def verify_record(reference: str):
    conn = get_db()
    try:
        cur = conn.cursor()

        # Fetch latest version
        cur.execute(
            "SELECT * FROM records WHERE reference = ? AND is_latest = 1",
            (reference,),
        )
        record = cur.fetchone()

        if not record:
            raise HTTPException(status_code=404, detail="Record not found")

        # Fetch full version history (oldest first)
        cur.execute(
            "SELECT version, exported_at, verification_hash FROM records "
            "WHERE reference = ? ORDER BY version ASC",
            (reference,),
        )
        history = cur.fetchall()

        conditions = json.loads(record["conditions_json"] or "[]")
        conditions_text = ", ".join(conditions) if conditions else "—"
        lang = record["language"] or "en"

        # ── Language strings ──────────────────────────────────────
        strings = {
            "en": {
                "page_title": "Public Record Verification",
                "engine": "Civic Decision Engine",
                "record_label": "VERIFIED PUBLIC RECORD",
                "section_finding": "Finding",
                "section_record": "Record Details",
                "section_integrity": "Record Integrity",
                "section_history": "Version History",
                "field_reference": "Reference",
                "field_date": "Date",
                "field_trajectory": "Trajectory",
                "field_conditions": "Conditions",
                "field_state": "System State",
                "field_generated": "Generated By",
                "field_exported": "Exported",
                "field_hash": "SHA-256 Integrity Hash",
                "field_version": "Record Version",
                "integrity_note": (
                    "This hash was computed at the time of export from the canonical "
                    "fields of this record. It can be used to verify that the content "
                    "of this record has not been altered since publication."
                ),
                "version_label": "Version",
                "current_badge": "Current",
                "footer_tagline": "The record does not argue.",
                "footer_note": (
                    "This record was generated by the Civic Decision Engine and "
                    "stored at the time of export. It constitutes a structured "
                    "evidentiary document for use in civic, administrative, or "
                    "formal complaint proceedings."
                ),
            },
            "ga": {
                "page_title": "Fíorú Taifid Phoiblí",
                "engine": "Inneall Cinnteoireachta Sibhialta",
                "record_label": "TAIFEAD POIBLÍ FÍORAITHE",
                "section_finding": "Toradh",
                "section_record": "Sonraí an Taifid",
                "section_integrity": "Sláine an Taifid",
                "section_history": "Stair na Leaganacha",
                "field_reference": "Tagairt",
                "field_date": "Dáta",
                "field_trajectory": "Treocht",
                "field_conditions": "Coinníollacha",
                "field_state": "Staid an Chórais",
                "field_generated": "Ginte ag",
                "field_exported": "Easpórtáilte",
                "field_hash": "Hais Sláine SHA-256",
                "field_version": "Leagan Taifid",
                "integrity_note": (
                    "Ríomhadh an hais seo ag am na heaspórtála ó réimsí canónacha "
                    "an taifid seo. Is féidir é a úsáid chun a fhíorú nár athraíodh "
                    "ábhar an taifid seo ó foilsíodh é."
                ),
                "version_label": "Leagan",
                "current_badge": "Reatha",
                "footer_tagline": "Ní áitíonn an taifead.",
                "footer_note": (
                    "Gineadh an taifead seo ag an Inneall Cinnteoireachta Sibhialta "
                    "agus stóráladh é ag am na heaspórtála. Tá sé ina dhoiciméad "
                    "fianaisíoch struchtúrtha le húsáid in imeachtaí sibhialta, "
                    "riaracháin nó gearáin fhoirmiúla."
                ),
            },
        }

        s = strings.get(lang, strings["en"])

        # ── Escape all user-derived fields ────────────────────────
        safe = {
            "lang": escape(lang),
            "reference": escape(record["reference"] or ""),
            "finding": escape(record["finding"] or ""),
            "generated_at": escape(record["generated_at"] or ""),
            "exported_at": escape(record["exported_at"] or ""),
            "trajectory": escape(record["trajectory"] or ""),
            "conditions": escape(conditions_text),
            "system_state": escape(record["system_state"] or ""),
            "generated_by": escape(record["generated_by"] or ""),
            "hash": escape(record["verification_hash"] or ""),
            "version": str(record["version"]),
        }

        # ── Version history rows ──────────────────────────────────
        history_rows = ""
        if len(history) > 1:
            for row in history:
                is_current = row["version"] == record["version"]
                badge = (
                    f'<span class="badge-current">{s["current_badge"]}</span>'
                    if is_current
                    else ""
                )
                row_class = "row-current" if is_current else ""
                history_rows += (
                    f'<tr class="{row_class}">'
                    f'<td>{s["version_label"]} {row["version"]} {badge}</td>'
                    f'<td>{escape(row["exported_at"] or "")}</td>'
                    f'<td class="hash-cell">{escape(row["verification_hash"] or "")}</td>'
                    f"</tr>"
                )

        history_section = ""
        if len(history) > 1:
            history_section = (
                f'<section class="section">'
                f'<h2 class="section-title">{s["section_history"]}</h2>'
                f'<table class="history-table">'
                f"<thead><tr>"
                f'<th>{s["version_label"]}</th>'
                f'<th>{s["field_exported"]}</th>'
                f'<th>{s["field_hash"]}</th>'
                f"</tr></thead>"
                f"<tbody>{history_rows}</tbody>"
                f"</table></section>"
            )

        html = f"""<!DOCTYPE html>
<html lang="{safe['lang']}">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{s["page_title"]} — {safe['reference']}</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; }}
    body {{
      font-family: Georgia, 'Times New Roman', serif;
      background: #f4f4f0;
      color: #1a1a1a;
      margin: 0;
      padding: 40px 20px 80px;
      font-size: 16px;
      line-height: 1.6;
    }}
    .document {{
      max-width: 720px;
      margin: 0 auto;
      background: #ffffff;
      border: 1px solid #d0cec8;
      border-top: 4px solid #1a1a1a;
      padding: 56px 56px 48px;
      box-shadow: 0 2px 12px rgba(0,0,0,0.08);
    }}
    .doc-header {{
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      border-bottom: 1px solid #1a1a1a;
      padding-bottom: 20px;
      margin-bottom: 32px;
    }}
    .doc-engine {{
      font-family: ui-monospace, monospace;
      font-size: 0.72rem;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: #666;
    }}
    .doc-record-label {{
      font-family: ui-monospace, monospace;
      font-size: 0.68rem;
      letter-spacing: 0.1em;
      text-transform: uppercase;
      color: #1a1a1a;
      font-weight: bold;
      text-align: right;
    }}
    .doc-reference {{
      font-family: ui-monospace, monospace;
      font-size: 0.78rem;
      color: #444;
      text-align: right;
      margin-top: 4px;
    }}
    .section {{ margin-bottom: 36px; }}
    .section-title {{
      font-size: 0.68rem;
      font-family: ui-monospace, monospace;
      text-transform: uppercase;
      letter-spacing: 0.12em;
      color: #888;
      margin: 0 0 14px;
      padding-bottom: 6px;
      border-bottom: 1px solid #e8e6e0;
    }}
    .finding {{
      font-size: 1.05rem;
      line-height: 1.75;
      white-space: pre-wrap;
      color: #1a1a1a;
    }}
    .detail-table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.875rem;
    }}
    .detail-table tr {{ border-bottom: 1px solid #f0ede8; }}
    .detail-table tr:last-child {{ border-bottom: none; }}
    .detail-table td {{ padding: 8px 0; vertical-align: top; }}
    .detail-table td:first-child {{
      font-family: ui-monospace, monospace;
      font-size: 0.78rem;
      color: #888;
      width: 160px;
      padding-right: 16px;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      padding-top: 10px;
    }}
    .detail-table td:last-child {{ color: #1a1a1a; }}
    .hash-block {{
      font-family: ui-monospace, monospace;
      font-size: 0.72rem;
      color: #444;
      word-break: break-all;
      background: #f8f7f4;
      border: 1px solid #e8e6e0;
      padding: 12px 14px;
      border-radius: 4px;
      margin-bottom: 12px;
    }}
    .integrity-note {{
      font-size: 0.8rem;
      color: #777;
      line-height: 1.6;
      font-style: italic;
    }}
    .history-table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.78rem;
      font-family: ui-monospace, monospace;
    }}
    .history-table th {{
      text-align: left;
      font-size: 0.68rem;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      color: #888;
      padding: 6px 8px 6px 0;
      border-bottom: 1px solid #e8e6e0;
    }}
    .history-table td {{
      padding: 8px 8px 8px 0;
      border-bottom: 1px solid #f4f2ee;
      color: #444;
      vertical-align: top;
    }}
    .history-table .hash-cell {{
      font-size: 0.65rem;
      color: #999;
      word-break: break-all;
      max-width: 280px;
    }}
    .history-table .row-current td {{
      color: #1a1a1a;
      font-weight: 600;
    }}
    .badge-current {{
      display: inline-block;
      font-size: 0.6rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      background: #1a1a1a;
      color: #fff;
      padding: 2px 6px;
      border-radius: 3px;
      margin-left: 6px;
      vertical-align: middle;
      font-weight: normal;
    }}
    .doc-footer {{
      margin-top: 48px;
      padding-top: 20px;
      border-top: 1px solid #1a1a1a;
      display: flex;
      justify-content: space-between;
      align-items: flex-end;
      gap: 24px;
    }}
    .footer-tagline {{
      font-size: 0.72rem;
      text-transform: uppercase;
      letter-spacing: 0.1em;
      color: #1a1a1a;
      font-family: ui-monospace, monospace;
    }}
    .footer-note {{
      font-size: 0.72rem;
      color: #999;
      line-height: 1.6;
      max-width: 420px;
      text-align: right;
    }}
    @media print {{
      body {{ background: white; padding: 0; }}
      .document {{ border: none; box-shadow: none; padding: 32px; }}
    }}
    @media (max-width: 600px) {{
      .document {{ padding: 28px 20px; }}
      .doc-header {{ flex-direction: column; gap: 12px; }}
      .doc-record-label, .doc-reference {{ text-align: left; }}
      .doc-footer {{ flex-direction: column; align-items: flex-start; }}
      .footer-note {{ text-align: left; }}
      .detail-table td:first-child {{ width: 120px; }}
    }}
  </style>
</head>
<body>
  <div class="document">
    <header class="doc-header">
      <div><div class="doc-engine">{s["engine"]}</div></div>
      <div>
        <div class="doc-record-label">{s["record_label"]}</div>
        <div class="doc-reference">{safe['reference']}</div>
      </div>
    </header>
    <section class="section">
      <h2 class="section-title">{s["section_finding"]}</h2>
      <div class="finding">{safe['finding']}</div>
    </section>
    <section class="section">
      <h2 class="section-title">{s["section_record"]}</h2>
      <table class="detail-table">
        <tbody>
          <tr><td>{s["field_reference"]}</td><td>{safe['reference']}</td></tr>
          <tr><td>{s["field_date"]}</td><td>{safe['generated_at']}</td></tr>
          <tr><td>{s["field_exported"]}</td><td>{safe['exported_at']}</td></tr>
          <tr><td>{s["field_trajectory"]}</td><td>{safe['trajectory']}</td></tr>
          <tr><td>{s["field_conditions"]}</td><td>{safe['conditions']}</td></tr>
          <tr><td>{s["field_state"]}</td><td>{safe['system_state']}</td></tr>
          <tr><td>{s["field_generated"]}</td><td>{safe['generated_by']}</td></tr>
          <tr><td>{s["field_version"]}</td><td>{safe['version']}</td></tr>
        </tbody>
      </table>
    </section>
    <section class="section">
      <h2 class="section-title">{s["section_integrity"]}</h2>
      <div class="hash-block">SHA-256: {safe['hash']}</div>
      <p class="integrity-note">{s["integrity_note"]}</p>
    </section>
    {history_section}
    <footer class="doc-footer">
      <div class="footer-tagline">{s["footer_tagline"]}</div>
      <div class="footer-note">{s["footer_note"]}</div>
    </footer>
  </div>
</body>
</html>"""

        return HTMLResponse(content=html, status_code=200)

    finally:
        conn.close()
