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
        cur.execute(
            "SELECT * FROM records WHERE reference = ? AND is_latest = 1",
            (reference,),
        )
        record = cur.fetchone()

        if not record:
            raise HTTPException(status_code=404, detail="Record not found")

        conditions = json.loads(record["conditions_json"] or "[]")
        conditions_text = ", ".join(conditions) if conditions else "—"

        safe_language = escape(record["language"] or "en")
        safe_reference = escape(record["reference"] or "")
        safe_finding = escape(record["finding"] or "")
        safe_generated_at = escape(record["generated_at"] or "")
        safe_trajectory = escape(record["trajectory"] or "")
        safe_conditions = escape(conditions_text)
        safe_system_state = escape(record["system_state"] or "")
        safe_generated_by = escape(record["generated_by"] or "")
        safe_hash = escape(record["verification_hash"] or "")

        version_note = f"Version {record['version']}" if record["version"] > 1 else ""
        supersedes_note = (
            f'<p class="supersedes">Supersedes: {escape(record["supersedes"])}</p>'
            if record["supersedes"]
            else ""
        )

        html = f"""<!DOCTYPE html>
<html lang="{safe_language}">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Public Record — {safe_reference}</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; }}
    body {{ font-family: Georgia, serif; background: #f9f9f9; color: #111; margin: 0; padding: 40px 24px; }}
    .card {{ max-width: 600px; margin: 0 auto; background: #fff; border: 1px solid #e0e0e0; border-radius: 12px; padding: 40px; }}
    .label {{ font-size: 0.7rem; letter-spacing: 0.12em; text-transform: uppercase; color: #888; margin: 0 0 24px; font-family: ui-monospace, monospace; }}
    hr {{ border: none; border-top: 2px solid #111; margin: 0 0 24px; }}
    .finding {{ font-size: 1rem; line-height: 1.7; white-space: pre-wrap; margin: 0 0 24px; }}
    .meta {{ font-family: ui-monospace, monospace; font-size: 0.78rem; color: #444; line-height: 1.9; border-top: 1px solid #ccc; padding-top: 16px; margin-bottom: 16px; white-space: pre-wrap; }}
    .hash {{ font-family: ui-monospace, monospace; font-size: 0.68rem; color: #999; word-break: break-all; margin-top: 16px; border-top: 1px solid #eee; padding-top: 12px; }}
    .supersedes {{ font-size: 0.78rem; color: #888; font-family: ui-monospace, monospace; margin-top: 8px; }}
    .version {{ font-size: 0.72rem; color: #aaa; text-align: right; margin-top: 16px; }}
    .footer {{ font-size: 0.68rem; color: #bbb; text-transform: uppercase; letter-spacing: 0.05em; margin-top: 24px; border-top: 1px solid #f0f0f0; padding-top: 12px; }}
  </style>
</head>
<body>
  <div class="card">
    <p class="label">Public Record — Civic Decision Engine</p>
    <hr>
    <div class="finding">{safe_finding}</div>
    <div class="meta">Reference:    {safe_reference}
Date:         {safe_generated_at}
Trajectory:   {safe_trajectory}
Conditions:   {safe_conditions}
System state: {safe_system_state}
Generated by: {safe_generated_by}</div>
    {supersedes_note}
    <div class="hash">SHA-256: {safe_hash}</div>
    {f'<p class="version">{version_note}</p>' if version_note else ''}
    <p class="footer">Civic Decision Engine — The record does not argue.</p>
  </div>
</body>
</html>"""

        return HTMLResponse(content=html, status_code=200)

    finally:
        conn.close()
