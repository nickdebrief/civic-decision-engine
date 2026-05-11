from __future__ import annotations

import json
import sqlite3
import hashlib
import os
from html import escape
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse

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


def extract_institution_type(reference: str) -> str:
    """Extract institution type code from structured reference e.g. Strike-LA-20260508-001 → LA"""
    parts = reference.split("-")
    if len(parts) >= 2:
        return parts[1].upper()
    return "OT"


CONDITION_REGISTRY = [
    {
        "id": "transfer_of_burden",
        "name": "Transfer of Burden",
        "code": "TRANSFER_OF_BURDEN",
        "description": (
            "A condition in which responsibility for progression, clarification, "
            "or resolution is shifted away from the institution and onto the person "
            "seeking remedy. The institution remains nominally engaged while "
            "substantive movement depends entirely on continued effort from the complainant."
        ),
        "indicators": [
            "Repeated requests for restatement of previously submitted information",
            "Unresolved procedural loops requiring re-entry at earlier stages",
            "Responsibility for follow-up displaced onto the complainant",
            "Absence of substantive institutional movement between contacts",
            "Requests for documentation already held by the institution",
        ],
    },
    {
        "id": "escalation_without_response",
        "name": "Escalation Without Response",
        "code": "ESCALATION_WITHOUT_RESPONSE",
        "description": (
            "A condition in which the severity or urgency of a case has increased "
            "over time, but institutional engagement has not adjusted to reflect that "
            "change. Earlier delay has developed into active escalation without a "
            "corresponding substantive response from the institution."
        ),
        "indicators": [
            "Case severity or urgency has increased since initial submission",
            "Institutional response pattern unchanged despite escalating conditions",
            "No acknowledgement of changed circumstances by the institution",
            "Escalation documented but not addressed in correspondence",
            "Timeline extended beyond reasonable expectation without explanation",
        ],
    },
    {
        "id": "institutional_delay",
        "name": "Institutional Delay",
        "code": "INSTITUTIONAL_DELAY",
        "description": (
            "A condition in which the institution has failed to progress a case "
            "within a timeframe that can be considered reasonable given the nature "
            "of the submission. Delay is recorded as a structural observation, not "
            "an attribution of intent."
        ),
        "indicators": [
            "Response or progression has not occurred within expected timeframes",
            "No substantive update provided during the delay period",
            "Deadlines, statutory or otherwise, have passed without action",
            "Acknowledgement received but no progression recorded",
            "Pattern of delay consistent across multiple contact points",
        ],
    },
    {
        "id": "procedural_deflection",
        "name": "Procedural Deflection",
        "code": "PROCEDURAL_DEFLECTION",
        "description": (
            "A condition in which procedural mechanisms are invoked by the institution "
            "in a manner that redirects engagement without addressing substantive issues. "
            "Process is used as a substitute for response rather than a pathway to resolution."
        ),
        "indicators": [
            "Case redirected to alternative process without substantive engagement",
            "Procedural requirements cited that were not previously communicated",
            "Form, format, or channel requirements used to delay substantive response",
            "Multiple procedural stages invoked sequentially without resolution",
            "Referral to another body without facilitation or continuity",
        ],
    },
    {
        "id": "repeated_contact_without_resolution",
        "name": "Repeated Contact Without Resolution",
        "code": "REPEATED_CONTACT_WITHOUT_RESOLUTION",
        "description": (
            "A condition in which the person seeking remedy has made multiple contacts "
            "across an extended period without achieving substantive progress. Each "
            "contact restarts engagement without building on previous exchanges."
        ),
        "indicators": [
            "Three or more contacts recorded without substantive progression",
            "Each contact treated as a new submission rather than continuation",
            "No accumulated institutional understanding across contact history",
            "Repeated acknowledgement without action",
            "Contact history not referenced or incorporated in responses",
        ],
    },
]


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


@router.get("/records", response_class=HTMLResponse)
async def records_index(trajectory: str = None, institution: str = None):
    conn = get_db()
    try:
        cur = conn.cursor()

        # Build filtered query
        conditions_parts = ["is_latest = 1"]
        params = []

        if trajectory:
            conditions_parts.append("LOWER(trajectory) = LOWER(?)")
            params.append(trajectory)

        if institution:
            conditions_parts.append("reference LIKE ?")
            params.append(f"Strike-{institution.upper()}-%")

        where = " AND ".join(conditions_parts)

        cur.execute(
            f"SELECT reference, trajectory, system_state, conditions_json, "
            f"exported_at, language, version FROM records "
            f"WHERE {where} ORDER BY exported_at DESC",
            params,
        )
        records = cur.fetchall()

        # Get distinct trajectories and institution types for filters
        cur.execute(
            "SELECT DISTINCT trajectory FROM records WHERE is_latest = 1 AND trajectory != '' ORDER BY trajectory"
        )
        trajectories = [r["trajectory"] for r in cur.fetchall()]

        cur.execute("SELECT DISTINCT reference FROM records WHERE is_latest = 1")
        all_refs = cur.fetchall()
        institution_types = sorted(
            set(extract_institution_type(r["reference"]) for r in all_refs)
        )

        INSTITUTION_LABELS = {
            "LA": "Local Authority",
            "HS": "Health Service",
            "ED": "Education",
            "HO": "Housing",
            "PL": "Planning",
            "GV": "Government",
            "FS": "Financial Services",
            "LE": "Law Enforcement",
            "LG": "Legal",
            "OT": "Other",
        }

        total = len(records)

        # Build filter pills HTML
        def filter_pill(label, param, value, current):
            active = current == value
            base_url = "/records"
            other_param = "institution" if param == "trajectory" else "trajectory"
            other_value = institution if param == "trajectory" else trajectory
            if active:
                href = (
                    f"{base_url}?{other_param}={other_value}"
                    if other_value
                    else base_url
                )
                cls = "pill pill-active"
            else:
                href = f"{base_url}?{param}={value}"
                if other_value:
                    href += f"&{other_param}={other_value}"
                cls = "pill"
            return f'<a href="{escape(href)}" class="{cls}">{escape(label)}</a>'

        traj_pills = '<a href="/records{}" class="pill {}">All</a>'.format(
            f"?institution={institution}" if institution else "",
            "pill-active" if not trajectory else "",
        )
        for t in trajectories:
            traj_pills += filter_pill(t, "trajectory", t, trajectory)

        inst_pills = '<a href="/records{}" class="pill {}">All</a>'.format(
            f"?trajectory={trajectory}" if trajectory else "",
            "pill-active" if not institution else "",
        )
        for code in institution_types:
            label = INSTITUTION_LABELS.get(code, code)
            inst_pills += filter_pill(
                f"{code} — {label}", "institution", code, institution
            )

        # Build record rows
        rows_html = ""
        if not records:
            rows_html = '<tr><td colspan="5" class="empty-state">No records match the current filters.</td></tr>'
        else:
            for rec in records:
                conditions = json.loads(rec["conditions_json"] or "[]")
                cond_text = ", ".join(conditions) if conditions else "—"
                inst_code = extract_institution_type(rec["reference"])
                inst_label = INSTITUTION_LABELS.get(inst_code, inst_code)
                exported = rec["exported_at"][:10] if rec["exported_at"] else "—"
                version_badge = (
                    f' <span class="version-badge">v{rec["version"]}</span>'
                    if rec["version"] > 1
                    else ""
                )
                rows_html += f"""
                <tr>
                  <td class="col-ref">
                    <a href="/verify/{escape(rec['reference'])}" class="ref-link">
                      {escape(rec['reference'])}{version_badge}
                    </a>
                  </td>
                  <td class="col-inst">{escape(inst_label)}</td>
                  <td class="col-traj">{escape(rec['trajectory'] or '—')}</td>
                  <td class="col-cond">{escape(cond_text)}</td>
                  <td class="col-date">{escape(exported)}</td>
                </tr>"""

        active_filter_note = ""
        if trajectory or institution:
            parts = []
            if trajectory:
                parts.append(f"Trajectory: {escape(trajectory)}")
            if institution:
                parts.append(
                    f"Institution: {escape(INSTITUTION_LABELS.get(institution.upper(), institution))}"
                )
            active_filter_note = (
                f'<p class="filter-note">Filtered by — {" · ".join(parts)}</p>'
            )

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Public Record Index — Civic Decision Engine</title>
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
      max-width: 960px;
      margin: 0 auto;
      background: #ffffff;
      border: 1px solid #d0cec8;
      border-top: 4px solid #1a1a1a;
      padding: 48px 56px;
      box-shadow: 0 2px 12px rgba(0,0,0,0.08);
    }}
    .doc-header {{
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      border-bottom: 1px solid #1a1a1a;
      padding-bottom: 20px;
      margin-bottom: 36px;
    }}
    .doc-engine {{
      font-family: ui-monospace, monospace;
      font-size: 0.72rem;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: #666;
    }}
    .doc-title {{
      font-family: ui-monospace, monospace;
      font-size: 0.68rem;
      letter-spacing: 0.1em;
      text-transform: uppercase;
      color: #1a1a1a;
      font-weight: bold;
      text-align: right;
    }}
    .doc-count {{
      font-family: ui-monospace, monospace;
      font-size: 0.78rem;
      color: #888;
      text-align: right;
      margin-top: 4px;
    }}
    .filter-section {{
      margin-bottom: 28px;
    }}
    .filter-label {{
      font-family: ui-monospace, monospace;
      font-size: 0.65rem;
      text-transform: uppercase;
      letter-spacing: 0.1em;
      color: #aaa;
      margin: 0 0 8px;
    }}
    .pill-group {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin-bottom: 12px;
    }}
    .pill {{
      font-family: ui-monospace, monospace;
      font-size: 0.72rem;
      padding: 4px 10px;
      border: 1px solid #d0cec8;
      border-radius: 20px;
      color: #555;
      text-decoration: none;
      background: #f8f7f4;
      transition: all 0.15s;
    }}
    .pill:hover {{ background: #eee; color: #1a1a1a; border-color: #999; }}
    .pill-active {{
      background: #1a1a1a;
      color: #fff;
      border-color: #1a1a1a;
    }}
    .pill-active:hover {{ background: #333; }}
    .filter-note {{
      font-family: ui-monospace, monospace;
      font-size: 0.72rem;
      color: #888;
      margin: 0 0 20px;
    }}
    .records-table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.875rem;
    }}
    .records-table thead tr {{
      border-bottom: 2px solid #1a1a1a;
    }}
    .records-table th {{
      font-family: ui-monospace, monospace;
      font-size: 0.65rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: #888;
      padding: 0 12px 10px 0;
      text-align: left;
      font-weight: normal;
    }}
    .records-table tbody tr {{
      border-bottom: 1px solid #f0ede8;
    }}
    .records-table tbody tr:hover {{ background: #faf9f7; }}
    .records-table td {{
      padding: 12px 12px 12px 0;
      vertical-align: top;
      color: #333;
    }}
    .col-ref {{ width: 220px; }}
    .col-inst {{ width: 140px; }}
    .col-traj {{ width: 130px; }}
    .col-cond {{ }}
    .col-date {{ width: 100px; white-space: nowrap; }}
    .ref-link {{
      font-family: ui-monospace, monospace;
      font-size: 0.8rem;
      color: #1a1a1a;
      text-decoration: none;
      border-bottom: 1px solid #ccc;
    }}
    .ref-link:hover {{ border-color: #1a1a1a; }}
    .version-badge {{
      display: inline-block;
      font-size: 0.6rem;
      background: #eee;
      color: #666;
      padding: 1px 5px;
      border-radius: 3px;
      margin-left: 4px;
      vertical-align: middle;
    }}
    .empty-state {{
      text-align: center;
      color: #aaa;
      font-style: italic;
      padding: 40px 0;
      font-family: ui-monospace, monospace;
      font-size: 0.82rem;
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
      max-width: 400px;
      text-align: right;
    }}
    @media (max-width: 700px) {{
      .document {{ padding: 28px 20px; }}
      .doc-header {{ flex-direction: column; gap: 12px; }}
      .doc-title, .doc-count {{ text-align: left; }}
      .col-cond, .col-inst {{ display: none; }}
      .doc-footer {{ flex-direction: column; }}
      .footer-note {{ text-align: left; }}
    }}
    @media print {{
      body {{ background: white; padding: 0; }}
      .document {{ border: none; box-shadow: none; }}
    }}
  </style>
</head>
<body>
  <div class="document">
    <header class="doc-header">
    <div>
      <div class="doc-engine">Civic Decision Engine</div>
      <div class="doc-nav" style="display:flex;flex-direction:column;gap:4px;margin-top:6px;">
        <a href="/api/docs" style="font-family:ui-monospace,monospace;font-size:0.68rem;color:#888;text-decoration:none;border-bottom:1px solid #ddd;width:fit-content;">API documentation</a>
        <a href="/stats" style="font-family:ui-monospace,monospace;font-size:0.68rem;color:#888;text-decoration:none;border-bottom:1px solid #ddd;width:fit-content;">Archive statistics</a>
      </div>
</div>
      <div>
        <div class="doc-title">Public Record Index</div>
        <div class="doc-count">{total} record{"s" if total != 1 else ""}</div>
      </div>
    </header>

    <div class="filter-section">
      <p class="filter-label">Trajectory</p>
      <div class="pill-group">{traj_pills}</div>
      <p class="filter-label">Institution type</p>
      <div class="pill-group">{inst_pills}</div>
    </div>

    {active_filter_note}

    <table class="records-table">
      <thead>
        <tr>
          <th>Reference</th>
          <th>Institution</th>
          <th>Trajectory</th>
          <th>Conditions</th>
          <th>Exported</th>
        </tr>
      </thead>
      <tbody>{rows_html}</tbody>
    </table>

    <footer class="doc-footer">
      <div class="footer-tagline">The record does not argue.</div>
      <div class="footer-note">
        Public records are generated by the Civic Decision Engine and stored
        at the time of export. Each record is independently verifiable via its reference URL.
      </div>
    </footer>
  </div>
</body>
</html>"""

        return HTMLResponse(content=html, status_code=200)

    finally:
        conn.close()


@router.get("/api/verify/{reference}")
async def api_verify_record(
    reference: str,
    full: bool = Query(
        default=False,
        description="Return full record including metadata and version history",
    ),
):
    conn = get_db()
    try:
        cur = conn.cursor()

        cur.execute(
            "SELECT * FROM records WHERE reference = ? AND is_latest = 1",
            (reference,),
        )
        record = cur.fetchone()

        if not record:
            return JSONResponse(
                status_code=404,
                content={
                    "error": "not_found",
                    "message": f"No public record found for reference: {reference}",
                },
            )

        conditions = json.loads(record["conditions_json"] or "[]")

        # Minimal response — always returned
        response: dict = {
            "reference": record["reference"],
            "finding": record["finding"] or "",
            "trajectory": record["trajectory"] or "",
            "conditions": conditions,
            "system_state": record["system_state"] or "",
            "verification_hash": record["verification_hash"],
            "version": record["version"],
        }

        if full:
            # Fetch version history
            cur.execute(
                "SELECT version, exported_at, verification_hash FROM records "
                "WHERE reference = ? ORDER BY version ASC",
                (reference,),
            )
            history = [
                {
                    "version": row["version"],
                    "exported_at": row["exported_at"],
                    "verification_hash": row["verification_hash"],
                }
                for row in cur.fetchall()
            ]

            response.update(
                {
                    "generated_at": record["generated_at"] or "",
                    "exported_at": record["exported_at"] or "",
                    "language": record["language"] or "en",
                    "supersedes": record["supersedes"],
                    "generated_by": record["generated_by"] or "",
                    "version_history": history,
                }
            )

        return JSONResponse(content=response)

    finally:
        conn.close()


@router.get("/api/records")
async def api_records_index(
    trajectory: str = Query(default=None, description="Filter by trajectory"),
    institution: str = Query(
        default=None, description="Filter by institution type code e.g. LA, HS, ED"
    ),
    limit: int = Query(default=50, le=200, description="Maximum records to return"),
    offset: int = Query(default=0, description="Pagination offset"),
    full: bool = Query(default=False, description="Include full fields per record"),
):
    conn = get_db()
    try:
        cur = conn.cursor()

        conditions_parts = ["is_latest = 1"]
        params: list = []

        if trajectory:
            conditions_parts.append("LOWER(trajectory) = LOWER(?)")
            params.append(trajectory)

        if institution:
            conditions_parts.append("reference LIKE ?")
            params.append(f"Strike-{institution.upper()}-%")

        where = " AND ".join(conditions_parts)

        # Total count
        cur.execute(f"SELECT COUNT(*) FROM records WHERE {where}", params)
        total = cur.fetchone()[0]

        # Paginated results
        cur.execute(
            f"SELECT * FROM records WHERE {where} "
            f"ORDER BY exported_at DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        )
        rows = cur.fetchall()

        records_out = []
        for rec in rows:
            conditions = json.loads(rec["conditions_json"] or "[]")
            item: dict = {
                "reference": rec["reference"],
                "trajectory": rec["trajectory"] or "",
                "conditions": conditions,
                "system_state": rec["system_state"] or "",
                "institution_type": extract_institution_type(rec["reference"]),
                "exported_at": rec["exported_at"] or "",
                "version": rec["version"],
                "verification_hash": rec["verification_hash"],
            }
            if full:
                item.update(
                    {
                        "finding": rec["finding"] or "",
                        "generated_at": rec["generated_at"] or "",
                        "language": rec["language"] or "en",
                        "supersedes": rec["supersedes"],
                        "generated_by": rec["generated_by"] or "",
                    }
                )
            records_out.append(item)

        return JSONResponse(
            content={
                "total": total,
                "offset": offset,
                "limit": limit,
                "filters": {
                    "trajectory": trajectory,
                    "institution": institution,
                },
                "records": records_out,
            }
        )

    finally:
        conn.close()


@router.get("/api/docs", response_class=HTMLResponse)
async def api_docs():
    html = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Public API Documentation — Civic Decision Engine</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; }
    body {
      font-family: Georgia, 'Times New Roman', serif;
      background: #f4f4f0;
      color: #1a1a1a;
      margin: 0;
      padding: 40px 20px 80px;
      font-size: 16px;
      line-height: 1.7;
    }
    .document {
      max-width: 820px;
      margin: 0 auto;
      background: #ffffff;
      border: 1px solid #d0cec8;
      border-top: 4px solid #1a1a1a;
      padding: 56px 64px 56px;
      box-shadow: 0 2px 12px rgba(0,0,0,0.08);
    }
    .doc-header {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      border-bottom: 1px solid #1a1a1a;
      padding-bottom: 20px;
      margin-bottom: 40px;
    }
    .doc-engine {
      font-family: ui-monospace, monospace;
      font-size: 0.72rem;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: #666;
    }
    .doc-index-link {
      font-family: ui-monospace, monospace;
      font-size: 0.68rem;
      color: #888;
      text-decoration: none;
      border-bottom: 1px solid #ddd;
      margin-top: 6px;
      display: inline-block;
    }
    .doc-index-link:hover { color: #1a1a1a; border-color: #999; }
    .doc-title {
      font-family: ui-monospace, monospace;
      font-size: 0.68rem;
      letter-spacing: 0.1em;
      text-transform: uppercase;
      color: #1a1a1a;
      font-weight: bold;
      text-align: right;
    }
    .doc-subtitle {
      font-family: ui-monospace, monospace;
      font-size: 0.72rem;
      color: #888;
      text-align: right;
      margin-top: 4px;
    }
    h2 {
      font-size: 0.68rem;
      font-family: ui-monospace, monospace;
      text-transform: uppercase;
      letter-spacing: 0.12em;
      color: #888;
      margin: 40px 0 14px;
      padding-bottom: 6px;
      border-bottom: 1px solid #e8e6e0;
    }
    h3 {
      font-size: 1rem;
      font-family: Georgia, serif;
      font-weight: bold;
      margin: 28px 0 8px;
      color: #1a1a1a;
    }
    p { margin: 0 0 16px; color: #333; }
    ul { margin: 0 0 16px; padding-left: 20px; color: #333; }
    li { margin-bottom: 6px; }
    code {
      font-family: ui-monospace, monospace;
      font-size: 0.85em;
      background: #f0ede8;
      padding: 1px 5px;
      border-radius: 3px;
    }
    .endpoint {
      background: #f8f7f4;
      border: 1px solid #e8e6e0;
      border-left: 3px solid #1a1a1a;
      border-radius: 4px;
      padding: 16px 20px;
      margin: 16px 0 24px;
      font-family: ui-monospace, monospace;
      font-size: 0.85rem;
    }
    .method {
      display: inline-block;
      font-size: 0.7rem;
      font-weight: bold;
      letter-spacing: 0.06em;
      background: #1a1a1a;
      color: #fff;
      padding: 2px 8px;
      border-radius: 3px;
      margin-right: 10px;
      vertical-align: middle;
    }
    .path { color: #1a1a1a; vertical-align: middle; }
    .param-table {
      width: 100%;
      border-collapse: collapse;
      font-size: 0.82rem;
      margin: 12px 0 20px;
    }
    .param-table th {
      font-family: ui-monospace, monospace;
      font-size: 0.65rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: #888;
      text-align: left;
      padding: 4px 12px 8px 0;
      border-bottom: 1px solid #e8e6e0;
      font-weight: normal;
    }
    .param-table td {
      padding: 8px 12px 8px 0;
      border-bottom: 1px solid #f4f2ee;
      vertical-align: top;
      color: #333;
    }
    .param-table td:first-child {
      font-family: ui-monospace, monospace;
      font-size: 0.78rem;
      color: #1a1a1a;
      width: 160px;
    }
    .param-table td:nth-child(2) {
      font-family: ui-monospace, monospace;
      font-size: 0.72rem;
      color: #888;
      width: 80px;
    }
    .code-block {
      background: #f8f7f4;
      border: 1px solid #e8e6e0;
      border-radius: 4px;
      padding: 16px 18px;
      font-family: ui-monospace, monospace;
      font-size: 0.78rem;
      line-height: 1.6;
      color: #333;
      overflow-x: auto;
      margin: 12px 0 24px;
      white-space: pre;
    }
    .curl-block {
      background: #1a1a1a;
      border-radius: 4px;
      padding: 14px 18px;
      font-family: ui-monospace, monospace;
      font-size: 0.78rem;
      line-height: 1.6;
      color: #e8e6e0;
      overflow-x: auto;
      margin: 12px 0 24px;
      white-space: pre;
    }
    .curl-label {
      font-family: ui-monospace, monospace;
      font-size: 0.65rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: #aaa;
      margin-bottom: 6px;
    }
    .hash-note {
      background: #faf9f7;
      border: 1px solid #e8e6e0;
      border-left: 3px solid #888;
      border-radius: 4px;
      padding: 14px 18px;
      font-size: 0.875rem;
      color: #444;
      margin: 16px 0;
      font-style: italic;
      line-height: 1.65;
    }
    .ref-anatomy {
      background: #f8f7f4;
      border: 1px solid #e8e6e0;
      border-radius: 4px;
      padding: 20px 24px;
      margin: 16px 0 24px;
      font-family: ui-monospace, monospace;
    }
    .ref-example {
      font-size: 1.1rem;
      letter-spacing: 0.06em;
      color: #1a1a1a;
      margin-bottom: 16px;
    }
    .ref-parts {
      display: flex;
      gap: 0;
      margin-bottom: 16px;
    }
    .ref-part {
      text-align: center;
      padding: 6px 12px;
      font-size: 0.72rem;
    }
    .ref-part-value {
      font-size: 0.95rem;
      font-weight: bold;
      color: #1a1a1a;
      border-bottom: 2px solid #1a1a1a;
      padding-bottom: 4px;
      margin-bottom: 4px;
    }
    .ref-part-label {
      font-size: 0.62rem;
      color: #888;
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }
    .status-table {
      width: 100%;
      border-collapse: collapse;
      font-size: 0.82rem;
      margin: 12px 0 20px;
    }
    .status-table td {
      padding: 8px 12px 8px 0;
      border-bottom: 1px solid #f4f2ee;
      vertical-align: top;
    }
    .status-table td:first-child {
      font-family: ui-monospace, monospace;
      font-size: 0.78rem;
      color: #1a1a1a;
      width: 80px;
    }
    .status-table td:last-child { color: #555; }
    .version-note {
      font-family: ui-monospace, monospace;
      font-size: 0.72rem;
      color: #aaa;
      margin-top: 6px;
    }
    .doc-footer {
      margin-top: 56px;
      padding-top: 20px;
      border-top: 1px solid #1a1a1a;
      display: flex;
      justify-content: space-between;
      align-items: flex-end;
      gap: 24px;
    }
    .footer-tagline {
      font-size: 0.72rem;
      text-transform: uppercase;
      letter-spacing: 0.1em;
      color: #1a1a1a;
      font-family: ui-monospace, monospace;
    }
    .footer-note {
      font-size: 0.72rem;
      color: #999;
      line-height: 1.6;
      max-width: 400px;
      text-align: right;
    }
    @media (max-width: 640px) {
      .document { padding: 28px 20px; }
      .doc-header { flex-direction: column; gap: 12px; }
      .doc-title, .doc-subtitle { text-align: left; }
      .doc-footer { flex-direction: column; align-items: flex-start; }
      .footer-note { text-align: left; }
      .ref-parts { flex-wrap: wrap; }
    }
    @media print {
      body { background: white; padding: 0; }
      .document { border: none; box-shadow: none; padding: 32px; }
      .curl-block { background: #f0f0f0; color: #1a1a1a; }
    }
  </style>
</head>
<body>
  <div class="document">

    <header class="doc-header">
      <div>
        <div class="doc-engine">Civic Decision Engine</div>
        <a href="/records" class="doc-index-link">← Public record index</a>
        <a href="/stats" class="doc-index-link" style="margin-top:4px;display:inline-block;">Archive statistics</a> 
      </div>
      <div>
        <div class="doc-title">Public API Documentation</div>
        <div class="doc-subtitle">Machine-readable civic record access</div>
      </div>
    </header>

    <h2>Overview</h2>
    <p>The Civic Decision Engine exposes a public read API for accessing verified civic records. These endpoints allow journalists, researchers, advocacy organisations, and automated systems to retrieve, verify, and archive structured civic evidence programmatically.</p>
    <p>All endpoints return JSON. All records exposed through this API are the same records accessible via the public verification pages — this is not a separate dataset.</p>

    <h2>Authentication</h2>
    <p>No authentication is required for read operations. These records are intentionally public — they are generated and published by consent at the point of export. Write operations (record creation, superseding) are not exposed through this API.</p>

    <h2>Base URL</h2>
    <div class="code-block">https://civic-decision-engine-production.up.railway.app</div>



    <h2>Canonical Reference Format</h2>
    <p>Every public record carries a structured reference that encodes its origin. The format is:</p>
    <div class="ref-anatomy">
      <div class="ref-example">Strike-LA-20260508-001</div>
      <div class="ref-parts">
        <div class="ref-part">
          <div class="ref-part-value">Strike</div>
          <div class="ref-part-label">System prefix</div>
        </div>
        <div class="ref-part" style="padding: 6px 4px; color:#ccc; font-size:1.2rem; align-self:flex-start; padding-top:10px;">—</div>
        <div class="ref-part">
          <div class="ref-part-value">LA</div>
          <div class="ref-part-label">Institution type</div>
        </div>
        <div class="ref-part" style="padding: 6px 4px; color:#ccc; font-size:1.2rem; align-self:flex-start; padding-top:10px;">—</div>
        <div class="ref-part">
          <div class="ref-part-value">20260508</div>
          <div class="ref-part-label">Export date (YYYYMMDD)</div>
        </div>
        <div class="ref-part" style="padding: 6px 4px; color:#ccc; font-size:1.2rem; align-self:flex-start; padding-top:10px;">—</div>
        <div class="ref-part">
          <div class="ref-part-value">001</div>
          <div class="ref-part-label">Sequence number</div>
        </div>
      </div>
      <p style="margin:0; font-size:0.78rem; color:#666;">References are case-sensitive. Institution type codes are always two uppercase letters. Sequence numbers are zero-padded to three digits. The same reference may have multiple versions — the API always returns the latest unless version history is requested via <code>?full=true</code>.</p>
    </div>

    <h2>Endpoints</h2>

    <h3>Retrieve a single record</h3>
    <div class="endpoint">
      <span class="method">GET</span>
      <span class="path">/api/verify/{reference}</span>
    </div>
    <p>Returns the latest version of a public record by its structured reference. The minimal response includes the fields necessary to verify, cite, and archive the record.</p>

    <table class="param-table">
      <thead>
        <tr><th>Parameter</th><th>Type</th><th>Description</th></tr>
      </thead>
      <tbody>
        <tr>
          <td>reference</td>
          <td>path</td>
          <td>Structured reference identifier, e.g. <code>Strike-LA-20260508-001</code></td>
        </tr>
        <tr>
          <td>full</td>
          <td>query</td>
          <td>Optional. Pass <code>?full=true</code> to include complete metadata and version history.</td>
        </tr>
      </tbody>
    </table>

    <p>Minimal response (default):</p>
    <div class="code-block">{
  "reference": "Strike-LA-20260508-001",
  "finding": "The sequence has transitioned into escalation.\\n\\nEarlier delay has developed into escalation without response.",
  "trajectory": "Deteriorating",
  "conditions": [
    "Transfer of Burden",
    "Escalation Without Response"
  ],
  "system_state": "Transition to Escalation",
  "verification_hash": "935e0a79c9f9283e8a03cfa1d3e8e3d5ff4aea7bc01cef8b3ea64ec0d510b1ff",
  "version": 1
}</div>

    <p>Full response (<code>?full=true</code>) additionally includes:</p>
    <div class="code-block">{
  "generated_at": "2026-05-08T12:58:54.870Z",
  "exported_at": "2026-05-08T12:59:04.562034+00:00",
  "language": "en",
  "supersedes": null,
  "generated_by": "Civic Decision Engine",
  "version_history": [
    {
      "version": 1,
      "exported_at": "2026-05-08T12:59:04.562034+00:00",
      "verification_hash": "935e0a79c9f9283e8a03cfa1d3e8e3d5ff4aea7bc01cef8b3ea64ec0d510b1ff"
    }
  ]
}</div>

    <div class="curl-label">Example request</div>
    <div class="curl-block">curl https://civic-decision-engine-production.up.railway.app/api/verify/Strike-LA-20260508-001</div>

    <h3>Retrieve archive statistics</h3>
    <div class="endpoint">
      <span class="method">GET</span>
      <span class="path">/api/stats</span>
    </div>
    <p>Returns a summary of the public record archive — total records, superseded versions, and distributions by institution type, trajectory, and condition. Statistics reflect only the latest version of each record.</p>

    <div class="code-block">{
      "total_records": 22,
      "total_superseded": 18,
      "latest_export": "2026-05-09T17:24:27.559+00:00",
      "by_institution": {
        "OT": 3,
        "GV": 3,
        "PL": 3,
        "HO": 3,
        "ED": 3,
        "LG": 3,
        "LE": 3,
        "FS": 2,
        "HS": 2,
        "LA": 1
      },
      "by_trajectory": {
        "Deteriorating": 22
      },
      "by_condition": {
        "Transfer of Burden": 22,
        "Escalation Without Response": 22
      }
    }</div>

        <div class="curl-label">Example request</div>
        <div class="curl-block">curl https://civic-decision-engine-production.up.railway.app/api/stats</div>

    <h3>Retrieve the record index</h3>
    <div class="endpoint">
      <span class="method">GET</span>
      <span class="path">/api/records</span>
    </div>
    <p>Returns a paginated list of the latest version of all public records, most recent first. Supports filtering by trajectory and institution type.</p>

    <table class="param-table">
      <thead>
        <tr><th>Parameter</th><th>Type</th><th>Description</th></tr>
      </thead>
      <tbody>
        <tr>
          <td>trajectory</td>
          <td>query</td>
          <td>Filter by trajectory value, e.g. <code>Deteriorating</code></td>
        </tr>
        <tr>
          <td>institution</td>
          <td>query</td>
          <td>Filter by institution type code, e.g. <code>LA</code>, <code>HS</code>, <code>ED</code></td>
        </tr>
        <tr>
          <td>limit</td>
          <td>query</td>
          <td>Maximum records to return. Default 50, maximum 200.</td>
        </tr>
        <tr>
          <td>offset</td>
          <td>query</td>
          <td>Pagination offset. Default 0.</td>
        </tr>
        <tr>
          <td>full</td>
          <td>query</td>
          <td>Pass <code>?full=true</code> to include finding, language, and supersedes per record.</td>
        </tr>
      </tbody>
    </table>

    <div class="code-block">{
  "total": 12,
  "offset": 0,
  "limit": 50,
  "filters": {
    "trajectory": null,
    "institution": null
  },
  "records": [
    {
      "reference": "Strike-LA-20260508-001",
      "trajectory": "Deteriorating",
      "conditions": ["Transfer of Burden", "Escalation Without Response"],
      "system_state": "Transition to Escalation",
      "institution_type": "LA",
      "exported_at": "2026-05-08T12:59:04.562034+00:00",
      "version": 1,
      "verification_hash": "935e0a79..."
    }
  ]
}</div>

    <div class="curl-label">Example requests</div>
    <div class="curl-block">curl https://civic-decision-engine-production.up.railway.app/api/records

curl https://civic-decision-engine-production.up.railway.app/api/records?trajectory=Deteriorating

curl https://civic-decision-engine-production.up.railway.app/api/records?institution=LA&limit=10</div>

    <h3>Retrieve the condition registry</h3>
    <div class="endpoint">
      <span class="method">GET</span>
      <span class="path">/api/conditions</span>
    </div>
    <p>Returns the canonical condition registry — the civic observation taxonomy used to classify case sequences. Each entry includes the condition name, internal code, formal description, and detection indicators.</p>

    <div class="curl-label">Example request</div>
    <div class="curl-block">curl https://civic-decision-engine-production.up.railway.app/api/conditions</div>

    <h3>Download verification manifest</h3>
    <div class="endpoint">
      <span class="method">GET</span>
      <span class="path">/verify/{reference}/manifest</span>
    </div>
    <p>Returns a downloadable JSON manifest for a public record. The manifest contains all canonical fields, the verification hash, and a recomputation instruction that allows independent offline verification of record integrity.</p>

    <div class="code-block">{
  "manifest_version": "1.0",
  "manifest_type": "civic_decision_engine_record",
  "reference": "Strike-LA-20260508-001",
  "version": 1,
  "supersedes": null,
  "generated_at": "2026-05-08T12:58:54.870Z",
  "exported_at": "2026-05-08T12:59:04.562034+00:00",
  "language": "en",
  "generated_by": "Civic Decision Engine",
  "finding": "The sequence has transitioned into escalation...",
  "trajectory": "Deteriorating",
  "conditions": ["Escalation Without Response", "Transfer of Burden"],
  "system_state": "Transition to Escalation",
  "verification_hash": "935e0a79...",
  "canonical_fields": {
    "conditions": ["Escalation Without Response", "Transfer of Burden"],
    "finding": "The sequence has transitioned into escalation...",
    "generated_at": "2026-05-08T12:58:54.870Z",
    "generated_by": "Civic Decision Engine",
    "reference": "Strike-LA-20260508-001",
    "system_state": "Transition to Escalation",
    "trajectory": "Deteriorating"
  },
  "recomputation_instruction": {
    "algorithm": "SHA-256",
    "method": "Serialize canonical_fields as JSON with keys in sorted order, no spaces, and conditions sorted alphabetically. Compute SHA-256 of the UTF-8 encoded string. The result must match verification_hash.",
    "canonical_serialization": "{\"conditions\":[...],\"finding\":\"...\"}",
    "verify_url": "https://civic-decision-engine-production.up.railway.app/verify/Strike-LA-20260508-001"
  }
}</div>

    <div class="curl-label">Example request</div>
    <div class="curl-block">curl -O https://civic-decision-engine-production.up.railway.app/verify/Strike-LA-20260508-001/manifest</div>

    <h2>Verification Integrity</h2>
    <div class="hash-note">
      Verification hashes are computed from canonical record fields at the time of export using SHA-256. The canonical fields are: reference, generated_at, finding, trajectory, conditions, system_state, and generated_by. Any alteration to those fields after export will produce a different hash. The hash displayed on the verification page and returned by this API can be independently recomputed to confirm the record has not been altered since publication.
    </div>

    <h2>Response Formats</h2>
    <p>All responses are <code>application/json</code>. All timestamps are ISO 8601. Conditions are returned as human-readable label arrays.</p>

    <h2>Status Codes</h2>
    <table class="status-table">
      <tbody>
        <tr>
          <td>200</td>
          <td>OK — record found and returned successfully.</td>
        </tr>
        <tr>
          <td>404</td>
          <td>Not Found — no record exists for the given reference. Returns a structured error body.</td>
        </tr>
        <tr>
          <td>422</td>
          <td>Unprocessable — query parameters are malformed or out of range.</td>
        </tr>
      </tbody>
    </table>

    <p>404 error body:</p>
    <div class="code-block">{
  "error": "not_found",
  "message": "No public record found for reference: Strike-XX-00000000-000"
}</div>

    <h2>Versioning</h2>
    <p>All endpoints return the latest version of each record by default. When a record is superseded, the previous version is preserved and remains accessible via <code>?full=true</code>. The <code>version</code> field indicates which version is currently returned. The <code>supersedes</code> field identifies the prior version reference when applicable.</p>
    <p>Published record versions remain preserved once exported. Corrections or amendments result in a new version, with all prior versions retained in the version history.</p>
    <p class="version-note">API version: v1 — stable. No breaking changes will be made without a version increment.</p>

    <h2>Institution Type Codes</h2>
    <table class="param-table">
      <thead>
        <tr><th>Code</th><th></th><th>Institution type</th></tr>
      </thead>
      <tbody>
        <tr><td>LA</td><td></td><td>Local Authority</td></tr>
        <tr><td>HS</td><td></td><td>Health Service</td></tr>
        <tr><td>ED</td><td></td><td>Education</td></tr>
        <tr><td>HO</td><td></td><td>Housing</td></tr>
        <tr><td>PL</td><td></td><td>Planning</td></tr>
        <tr><td>GV</td><td></td><td>Government</td></tr>
        <tr><td>FS</td><td></td><td>Financial Services</td></tr>
        <tr><td>LE</td><td></td><td>Law Enforcement</td></tr>
        <tr><td>LG</td><td></td><td>Legal</td></tr>
        <tr><td>OT</td><td></td><td>Other</td></tr>
      </tbody>
    </table>

    <h2>Notes on Public Records</h2>
    <p>Records accessible through this API are structured evidentiary documents generated by the Civic Decision Engine at the time of export. Published record versions remain preserved once exported. Corrections or amendments result in a new version, with the original preserved in the version history.</p>
    <p>These records are designed for use in civic, administrative, and formal complaint proceedings. They are not legal advice and do not constitute official determinations by any public body. They are observation instruments — structured accounts of institutional behaviour as experienced and recorded by the person submitting the case.</p>

    <footer class="doc-footer">
      <div class="footer-tagline">The record does not argue.</div>
      <div class="footer-note">
        Civic Decision Engine public API — open access, read only.
        For the human-readable record index, see
        <a href="/records" style="color:#888;">civic-decision-engine-production.up.railway.app/records</a>
      </div>
    </footer>

  </div>
</body>
</html>"""
    return HTMLResponse(content=html, status_code=200)


@router.get("/conditions", response_class=HTMLResponse)
async def conditions_registry():
    entries_html = ""
    for condition in CONDITION_REGISTRY:
        indicators_html = "".join(
            f"<li>{escape(ind)}</li>" for ind in condition["indicators"]
        )
        entries_html += f"""
        <section class="condition-entry" id="{escape(condition['id'])}">
          <div class="condition-header">
            <h3 class="condition-name">{escape(condition['name'])}</h3>
            <span class="condition-code">{escape(condition['code'])}</span>
          </div>
          <p class="condition-description">{escape(condition['description'])}</p>
          <div class="indicators-label">Indicators</div>
          <ul class="indicators-list">{indicators_html}</ul>
        </section>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Condition Registry — Civic Decision Engine</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; }}
    body {{
      font-family: Georgia, 'Times New Roman', serif;
      background: #f4f4f0;
      color: #1a1a1a;
      margin: 0;
      padding: 40px 20px 80px;
      font-size: 16px;
      line-height: 1.7;
    }}
    .document {{
      max-width: 820px;
      margin: 0 auto;
      background: #ffffff;
      border: 1px solid #d0cec8;
      border-top: 4px solid #1a1a1a;
      padding: 56px 64px 56px;
      box-shadow: 0 2px 12px rgba(0,0,0,0.08);
    }}
    .doc-header {{
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      border-bottom: 1px solid #1a1a1a;
      padding-bottom: 20px;
      margin-bottom: 40px;
    }}
    .doc-engine {{
      font-family: ui-monospace, monospace;
      font-size: 0.72rem;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: #666;
    }}
    .doc-nav {{
      display: flex;
      flex-direction: column;
      gap: 4px;
      margin-top: 6px;
    }}
    .doc-nav a {{
      font-family: ui-monospace, monospace;
      font-size: 0.68rem;
      color: #888;
      text-decoration: none;
      border-bottom: 1px solid #ddd;
      display: inline-block;
      width: fit-content;
    }}
    .doc-nav a:hover {{ color: #1a1a1a; border-color: #999; }}
    .doc-title {{
      font-family: ui-monospace, monospace;
      font-size: 0.68rem;
      letter-spacing: 0.1em;
      text-transform: uppercase;
      color: #1a1a1a;
      font-weight: bold;
      text-align: right;
    }}
    .doc-subtitle {{
      font-family: ui-monospace, monospace;
      font-size: 0.72rem;
      color: #888;
      text-align: right;
      margin-top: 4px;
    }}
    .section-header {{
      font-size: 0.68rem;
      font-family: ui-monospace, monospace;
      text-transform: uppercase;
      letter-spacing: 0.12em;
      color: #888;
      margin: 40px 0 14px;
      padding-bottom: 6px;
      border-bottom: 1px solid #e8e6e0;
    }}
    .intro {{ margin-bottom: 36px; color: #444; }}
    .condition-entry {{
      margin-bottom: 48px;
      padding-bottom: 48px;
      border-bottom: 1px solid #e8e6e0;
    }}
    .condition-entry:last-child {{
      border-bottom: none;
      margin-bottom: 0;
      padding-bottom: 0;
    }}
    .condition-header {{
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      margin-bottom: 12px;
      gap: 16px;
    }}
    .condition-name {{
      font-size: 1.1rem;
      font-family: Georgia, serif;
      font-weight: bold;
      margin: 0;
      color: #1a1a1a;
    }}
    .condition-code {{
      font-family: ui-monospace, monospace;
      font-size: 0.68rem;
      color: #aaa;
      letter-spacing: 0.04em;
      white-space: nowrap;
    }}
    .condition-description {{
      font-size: 0.95rem;
      color: #333;
      line-height: 1.75;
      margin: 0 0 20px;
    }}
    .indicators-label {{
      font-family: ui-monospace, monospace;
      font-size: 0.65rem;
      text-transform: uppercase;
      letter-spacing: 0.1em;
      color: #aaa;
      margin-bottom: 10px;
    }}
    .indicators-list {{
      margin: 0;
      padding-left: 20px;
      color: #444;
      font-size: 0.9rem;
      line-height: 1.75;
    }}
    .indicators-list li {{ margin-bottom: 6px; }}
    .api-note {{
      background: #f8f7f4;
      border: 1px solid #e8e6e0;
      border-left: 3px solid #888;
      border-radius: 4px;
      padding: 14px 18px;
      font-family: ui-monospace, monospace;
      font-size: 0.78rem;
      color: #666;
      margin: 40px 0 0;
      line-height: 1.6;
    }}
    .api-note a {{ color: #444; }}
    .doc-footer {{
      margin-top: 56px;
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
      max-width: 400px;
      text-align: right;
    }}
    @media (max-width: 640px) {{
      .document {{ padding: 28px 20px; }}
      .doc-header {{ flex-direction: column; gap: 12px; }}
      .doc-title, .doc-subtitle {{ text-align: left; }}
      .condition-header {{ flex-direction: column; gap: 4px; }}
      .doc-footer {{ flex-direction: column; align-items: flex-start; }}
      .footer-note {{ text-align: left; }}
    }}
    @media print {{
      body {{ background: white; padding: 0; }}
      .document {{ border: none; box-shadow: none; padding: 32px; }}
    }}
  </style>
</head>
<body>
  <div class="document">
    <header class="doc-header">
      <div>
        <div class="doc-engine">Civic Decision Engine</div>
        <div class="doc-nav">
          <a href="/records">← Public record index</a>
          <a href="/api/docs">API documentation</a>
        </div>
      </div>
      <div>
        <div class="doc-title">Condition Registry</div>
        <div class="doc-subtitle">Civic observation taxonomy</div>
      </div>
    </header>

    <p class="intro">
      Conditions are structured civic observation categories assigned to cases by the
      Civic Decision Engine. Each condition represents a documented pattern of
      institutional behaviour observable across a case sequence. Conditions are not
      attributions of intent — they are structural observations derived from the
      submitted record.
    </p>

    <div class="section-header">Conditions — {len(CONDITION_REGISTRY)} defined</div>

    {entries_html}

    <div class="api-note">
      Machine-readable access: <a href="/api/conditions">GET /api/conditions</a>
      &nbsp;·&nbsp; Returns this registry as JSON for programmatic use.
    </div>

    <footer class="doc-footer">
      <div class="footer-tagline">The record does not argue.</div>
      <div class="footer-note">
        Conditions are versioned alongside the engine. This registry reflects
        the current active taxonomy. Earlier records may reference condition
        codes from prior versions.
      </div>
    </footer>
  </div>
</body>
</html>"""
    return HTMLResponse(content=html, status_code=200)


@router.get("/api/conditions")
async def api_conditions():
    return JSONResponse(
        content={
            "version": "v1",
            "count": len(CONDITION_REGISTRY),
            "conditions": [
                {
                    "id": c["id"],
                    "name": c["name"],
                    "code": c["code"],
                    "description": c["description"],
                    "indicators": c["indicators"],
                }
                for c in CONDITION_REGISTRY
            ],
        }
    )


@router.get("/stats", response_class=HTMLResponse)
async def stats_page():
    conn = get_db()
    try:
        cur = conn.cursor()

        # Total records (latest versions only)
        cur.execute("SELECT COUNT(*) FROM records WHERE is_latest = 1")
        total_records = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM records")
        total_versions = cur.fetchone()[0]

        # Superseded records
        cur.execute("SELECT COUNT(*) FROM records WHERE is_latest = 0")
        total_superseded = cur.fetchone()[0]

        # Latest export date
        cur.execute(
            "SELECT exported_at FROM records WHERE is_latest = 1 ORDER BY exported_at DESC LIMIT 1"
        )
        row = cur.fetchone()
        latest_export = row["exported_at"][:10] if row else "—"

        # By institution type
        cur.execute("SELECT reference FROM records WHERE is_latest = 1")
        all_refs = cur.fetchall()
        institution_counts: dict[str, int] = {}
        for r in all_refs:
            code = extract_institution_type(r["reference"])
            institution_counts[code] = institution_counts.get(code, 0) + 1

        INSTITUTION_LABELS = {
            "LA": "Local Authority",
            "HS": "Health Service",
            "ED": "Education",
            "HO": "Housing",
            "PL": "Planning",
            "GV": "Government",
            "FS": "Financial Services",
            "LE": "Law Enforcement",
            "LG": "Legal",
            "OT": "Other",
        }

        # By trajectory
        cur.execute(
            "SELECT trajectory, COUNT(*) as count FROM records "
            "WHERE is_latest = 1 AND trajectory != '' "
            "GROUP BY trajectory ORDER BY count DESC"
        )
        trajectory_counts = [(r["trajectory"], r["count"]) for r in cur.fetchall()]

        # By condition
        cur.execute("SELECT conditions_json FROM records WHERE is_latest = 1")
        condition_counts: dict[str, int] = {}
        for r in cur.fetchall():
            conditions = json.loads(r["conditions_json"] or "[]")
            for c in conditions:
                condition_counts[c] = condition_counts.get(c, 0) + 1
        condition_counts_sorted = sorted(
            condition_counts.items(), key=lambda x: x[1], reverse=True
        )

        # Build institution rows
        inst_rows = ""
        for code, count in sorted(
            institution_counts.items(), key=lambda x: x[1], reverse=True
        ):
            label = INSTITUTION_LABELS.get(code, code)
            pct = round((count / total_records) * 100) if total_records else 0
            inst_rows += (
                f"<tr>"
                f'<td class="stat-label">{escape(code)}</td>'
                f'<td class="stat-desc">{escape(label)}</td>'
                f'<td class="stat-count">{count}</td>'
                f'<td class="stat-bar-cell"><div class="stat-bar" style="width:{pct}%"></div></td>'
                f"</tr>"
            )

        # Build trajectory rows
        traj_rows = ""
        for traj, count in trajectory_counts:
            pct = round((count / total_records) * 100) if total_records else 0
            traj_rows += (
                f"<tr>"
                f'<td class="stat-label" colspan="2">{escape(traj)}</td>'
                f'<td class="stat-count">{count}</td>'
                f'<td class="stat-bar-cell"><div class="stat-bar" style="width:{pct}%"></div></td>'
                f"</tr>"
            )

        # Build condition rows
        cond_rows = ""
        for cond, count in condition_counts_sorted:
            pct = round((count / total_records) * 100) if total_records else 0
            cond_rows += (
                f"<tr>"
                f'<td class="stat-label" colspan="2">{escape(cond)}</td>'
                f'<td class="stat-count">{count}</td>'
                f'<td class="stat-bar-cell"><div class="stat-bar" style="width:{pct}%"></div></td>'
                f"</tr>"
            )

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Archive Statistics — Civic Decision Engine</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; }}
    body {{
      font-family: Georgia, 'Times New Roman', serif;
      background: #f4f4f0;
      color: #1a1a1a;
      margin: 0;
      padding: 40px 20px 80px;
      font-size: 16px;
      line-height: 1.7;
    }}
    .document {{
      max-width: 820px;
      margin: 0 auto;
      background: #ffffff;
      border: 1px solid #d0cec8;
      border-top: 4px solid #1a1a1a;
      padding: 56px 64px 56px;
      box-shadow: 0 2px 12px rgba(0,0,0,0.08);
    }}
    .doc-header {{
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      border-bottom: 1px solid #1a1a1a;
      padding-bottom: 20px;
      margin-bottom: 40px;
    }}
    .doc-engine {{
      font-family: ui-monospace, monospace;
      font-size: 0.72rem;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: #666;
    }}
    .doc-nav {{
      display: flex;
      flex-direction: column;
      gap: 4px;
      margin-top: 6px;
    }}
    .doc-nav a {{
      font-family: ui-monospace, monospace;
      font-size: 0.68rem;
      color: #888;
      text-decoration: none;
      border-bottom: 1px solid #ddd;
      display: inline-block;
      width: fit-content;
    }}
    .doc-nav a:hover {{ color: #1a1a1a; border-color: #999; }}
    .doc-title {{
      font-family: ui-monospace, monospace;
      font-size: 0.68rem;
      letter-spacing: 0.1em;
      text-transform: uppercase;
      color: #1a1a1a;
      font-weight: bold;
      text-align: right;
    }}
    .doc-subtitle {{
      font-family: ui-monospace, monospace;
      font-size: 0.72rem;
      color: #888;
      text-align: right;
      margin-top: 4px;
    }}
    .section-header {{
      font-size: 0.68rem;
      font-family: ui-monospace, monospace;
      text-transform: uppercase;
      letter-spacing: 0.12em;
      color: #888;
      margin: 40px 0 14px;
      padding-bottom: 6px;
      border-bottom: 1px solid #e8e6e0;
    }}
    .summary-grid {{
      display: grid;
      grid-template-columns: repeat(3, 1fr);
    }}
    .summary-card {{
      background: #f8f7f4;
      border: 1px solid #e8e6e0;
      border-radius: 4px;
      padding: 18px 20px;
    }}
    .summary-value {{
      font-family: ui-monospace, monospace;
      font-size: 1.8rem;
      font-weight: bold;
      color: #1a1a1a;
      line-height: 1;
      margin-bottom: 6px;
    }}
    .summary-label {{
      font-family: ui-monospace, monospace;
      font-size: 0.65rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: #888;
    }}
    .stat-table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.875rem;
      margin-bottom: 8px;
    }}
    .stat-table tr {{ border-bottom: 1px solid #f0ede8; }}
    .stat-table tr:last-child {{ border-bottom: none; }}
    .stat-table td {{ padding: 10px 8px 10px 0; vertical-align: middle; }}
    .stat-label {{
      font-family: ui-monospace, monospace;
      font-size: 0.78rem;
      color: #1a1a1a;
      width: 56px;
    }}
    .stat-desc {{
      color: #444;
      width: 180px;
    }}
    .stat-count {{
      font-family: ui-monospace, monospace;
      font-size: 0.85rem;
      color: #1a1a1a;
      text-align: right;
      width: 40px;
      padding-right: 16px;
    }}
    .stat-bar-cell {{ width: 100%; }}
    .stat-bar {{
      height: 6px;
      background: #1a1a1a;
      border-radius: 2px;
      min-width: 2px;
      transition: width 0.3s ease;
    }}
    .api-note {{
      background: #f8f7f4;
      border: 1px solid #e8e6e0;
      border-left: 3px solid #888;
      border-radius: 4px;
      padding: 14px 18px;
      font-family: ui-monospace, monospace;
      font-size: 0.78rem;
      color: #666;
      margin-top: 40px;
      line-height: 1.6;
    }}
    .api-note a {{ color: #444; }}
    .doc-footer {{
      margin-top: 56px;
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
      max-width: 400px;
      text-align: right;
    }}
    @media (max-width: 640px) {{
      .document {{ padding: 28px 20px; }}
      .doc-header {{ flex-direction: column; gap: 12px; }}
      .doc-title, .doc-subtitle {{ text-align: left; }}
      .summary-grid {{ grid-template-columns: repeat(2, 1fr); }}
      .doc-footer {{ flex-direction: column; align-items: flex-start; }}
      .footer-note {{ text-align: left; }}
      .stat-desc {{ display: none; }}
    }}
    @media print {{
      body {{ background: white; padding: 0; }}
      .document {{ border: none; box-shadow: none; padding: 32px; }}
    }}
  </style>
</head>
<body>
  <div class="document">
    <header class="doc-header">
      <div>
        <div class="doc-engine">Civic Decision Engine</div>
        <div class="doc-nav">
          <a href="/records">← Public record index</a>
          <a href="/conditions">Condition registry</a>
          <a href="/api/docs">API documentation</a>
        </div>
      </div>
      <div>
        <div class="doc-title">Archive Statistics</div>
        <div class="doc-subtitle">Public record distribution</div>
      </div>
    </header>

    <div class="section-header">Summary</div>
    <div class="summary-grid">
      <div class="summary-card">
        <div class="summary-value">{total_records}</div>
        <div class="summary-label">Public records</div>
      </div>
      <div class="summary-card">
        <div class="summary-value">{total_superseded}</div>
        <div class="summary-label">Superseded versions</div>
      </div>
      <div class="summary-card">
        <div class="summary-value">{latest_export}</div>
        <div class="summary-label">Latest export</div>
      </div>
      <div class="summary-card">
        <div class="summary-value">{total_versions}</div>
        <div class="summary-label">Total versions written</div>
      </div>
    </div>

    <div class="section-header">By institution type</div>
    <table class="stat-table">
      <tbody>{inst_rows}</tbody>
    </table>

    <div class="section-header">By trajectory</div>
    <table class="stat-table">
      <tbody>{traj_rows}</tbody>
    </table>

    <div class="section-header">By condition</div>
    <table class="stat-table">
      <tbody>{cond_rows}</tbody>
    </table>

    <div class="api-note">
      Machine-readable access: <a href="/api/stats">GET /api/stats</a>
      &nbsp;·&nbsp; Returns these metrics as JSON.
    </div>

    <footer class="doc-footer">
      <div class="footer-tagline">The record does not argue.</div>
      <div class="footer-note">
        Statistics reflect the current state of the public archive.
        Only the latest version of each record is counted.
      </div>
    </footer>
  </div>
</body>
</html>"""

        return HTMLResponse(content=html, status_code=200)

    finally:
        conn.close()


@router.get("/api/stats")
async def api_stats():
    conn = get_db()
    try:
        cur = conn.cursor()

        cur.execute("SELECT COUNT(*) FROM records WHERE is_latest = 1")
        total_records = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM records WHERE is_latest = 0")
        total_superseded = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM records")
        total_versions = cur.fetchone()[0]

        cur.execute(
            "SELECT exported_at FROM records WHERE is_latest = 1 "
            "ORDER BY exported_at DESC LIMIT 1"
        )
        row = cur.fetchone()
        latest_export = row["exported_at"] if row else None

        cur.execute("SELECT reference FROM records WHERE is_latest = 1")
        all_refs = cur.fetchall()
        institution_counts: dict[str, int] = {}
        for r in all_refs:
            code = extract_institution_type(r["reference"])
            institution_counts[code] = institution_counts.get(code, 0) + 1

        cur.execute(
            "SELECT trajectory, COUNT(*) as count FROM records "
            "WHERE is_latest = 1 AND trajectory != '' "
            "GROUP BY trajectory ORDER BY count DESC"
        )
        trajectory_counts = {r["trajectory"]: r["count"] for r in cur.fetchall()}

        cur.execute("SELECT conditions_json FROM records WHERE is_latest = 1")
        condition_counts: dict[str, int] = {}
        for r in cur.fetchall():
            conditions = json.loads(r["conditions_json"] or "[]")
            for c in conditions:
                condition_counts[c] = condition_counts.get(c, 0) + 1
        condition_counts_sorted = dict(
            sorted(condition_counts.items(), key=lambda x: x[1], reverse=True)
        )

        return JSONResponse(
            content={
                "total_records": total_records,
                "total_superseded": total_superseded,
                "total_versions": total_versions,
                "latest_export": latest_export,
                "by_institution": dict(
                    sorted(institution_counts.items(), key=lambda x: x[1], reverse=True)
                ),
                "by_trajectory": trajectory_counts,
                "by_condition": condition_counts_sorted,
            }
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
      <div>
  <div class="doc-engine">{s["engine"]}</div>
  <a href="/records" style="font-family:ui-monospace,monospace;font-size:0.68rem;color:#888;text-decoration:none;border-bottom:1px solid #ddd;">
    ← Public record index
  </a>
</div>
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
    <a href="/verify/{safe['reference']}/manifest"
       download
       style="font-family:ui-monospace,monospace;font-size:0.72rem;color:#888;
              text-decoration:none;border-bottom:1px solid #ddd;display:inline-block;
              margin-top:10px;">
      Download verification manifest (.json)
    </a>
    
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


@router.get("/verify/{reference}/manifest")
async def record_manifest(reference: str):
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM records WHERE reference = ? AND is_latest = 1",
            (reference,),
        )
        record = cur.fetchone()

        if not record:
            return JSONResponse(
                status_code=404,
                content={
                    "error": "not_found",
                    "message": f"No public record found for reference: {reference}",
                },
            )

        conditions = json.loads(record["conditions_json"] or "[]")

        canonical_fields = {
            "reference": record["reference"],
            "generated_at": record["generated_at"] or "",
            "finding": record["finding"] or "",
            "trajectory": record["trajectory"] or "",
            "conditions": sorted(conditions),
            "system_state": record["system_state"] or "",
            "generated_by": record["generated_by"] or "Civic Decision Engine",
        }

        manifest = {
            "manifest_version": "1.0",
            "manifest_type": "civic_decision_engine_record",
            "reference": record["reference"],
            "version": record["version"],
            "supersedes": record["supersedes"],
            "generated_at": record["generated_at"] or "",
            "exported_at": record["exported_at"] or "",
            "language": record["language"] or "en",
            "generated_by": record["generated_by"] or "",
            "finding": record["finding"] or "",
            "trajectory": record["trajectory"] or "",
            "conditions": conditions,
            "system_state": record["system_state"] or "",
            "verification_hash": record["verification_hash"],
            "canonical_fields": canonical_fields,
            "recomputation_instruction": {
                "algorithm": "SHA-256",
                "method": (
                    "Serialize canonical_fields as JSON with keys in sorted order, "
                    "no spaces, and conditions sorted alphabetically. "
                    "Compute SHA-256 of the UTF-8 encoded string. "
                    "The result must match verification_hash."
                ),
                "canonical_serialization": json.dumps(
                    canonical_fields, separators=(",", ":"), sort_keys=True
                ),
                "verify_url": f"https://civic-decision-engine-production.up.railway.app/verify/{record['reference']}",
            },
        }

        filename = f"manifest-{record['reference']}-v{record['version']}.json"

        return JSONResponse(
            content=manifest,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Content-Type": "application/json",
            },
        )

    finally:
        conn.close()
