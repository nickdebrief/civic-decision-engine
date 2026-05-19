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
                verification_hash, exported_at, is_latest,
                source_narrative
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
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
                payload.source_narrative,
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
async def records_index(
    trajectory: str = None, institution: str = None, search: str = None, page: int = 1
):
    page = max(1, page)

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

        if search:
            conditions_parts.append(
                "(LOWER(reference) LIKE LOWER(?) OR LOWER(conditions_json) LIKE LOWER(?))"
            )

        where = " AND ".join(conditions_parts)

        PER_PAGE = 25
        offset = (page - 1) * PER_PAGE

        # Search needs its param twice (reference + conditions_json)
        count_params = params + ([f"%{search}%", f"%{search}%"] if search else [])
        records_params = params + ([f"%{search}%", f"%{search}%"] if search else [])

        # Total count for pagination
        cur.execute(f"SELECT COUNT(*) FROM records WHERE {where}", count_params)
        total_count = cur.fetchone()[0]
        total_pages = max(1, -(-total_count // PER_PAGE))

        if total_count > 0 and offset >= total_count:
            redirect_url = page_url(1)
            from fastapi.responses import RedirectResponse

            return RedirectResponse(url=redirect_url, status_code=302)

        cur.execute(
            f"SELECT reference, trajectory, system_state, conditions_json, "
            f"exported_at, language, version FROM records "
            f"WHERE {where} ORDER BY exported_at DESC "
            f"LIMIT ? OFFSET ?",
            records_params + [PER_PAGE, offset],
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

        total = total_count
        page_start = offset + 1 if total_count else 0
        page_end = min(offset + PER_PAGE, total_count)

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
        if trajectory or institution or search:
            parts = []
            if trajectory:
                parts.append(f"Trajectory: {escape(trajectory)}")
            if institution:
                parts.append(
                    f"Institution: {escape(INSTITUTION_LABELS.get(institution.upper(), institution))}"
                )
            if search:
                parts.append(f"Search: {escape(search)}")
            active_filter_note = (
                f'<p class="filter-note">Filtered by — {" · ".join(parts)}</p>'
            )
        # Build search form
        filter_base = ""
        if trajectory:
            filter_base += (
                f'<input type="hidden" name="trajectory" value="{escape(trajectory)}">'
            )
        if institution:
            filter_base += f'<input type="hidden" name="institution" value="{escape(institution)}">'

        def page_url(p: int) -> str:
            parts = []
            if trajectory:
                parts.append(f"trajectory={trajectory}")
            if institution:
                parts.append(f"institution={institution}")
            if search:
                parts.append(f"search={escape(search)}")
            if p > 1:
                parts.append(f"page={p}")
            return "/records" + (f"?{'&'.join(parts)}" if parts else "")

        prev_url = page_url(page - 1) if page > 1 else None
        next_url = page_url(page + 1) if page < total_pages else None

        pagination_html = ""
        if total_count > PER_PAGE:
            prev_btn = (
                f'<a href="{escape(prev_url)}" class="page-btn">← Previous</a>'
                if prev_url
                else '<span class="page-btn page-btn-disabled">← Previous</span>'
            )
            next_btn = (
                f'<a href="{escape(next_url)}" class="page-btn">Next →</a>'
                if next_url
                else '<span class="page-btn page-btn-disabled">Next →</span>'
            )
            pagination_html = f"""
            <div class="pagination">
              <span class="page-info">Showing {page_start}–{page_end} of {total_count} records</span>
              <div class="page-controls">
                {prev_btn}
                {next_btn}
              </div>
            </div>"""

        clear_search_url = (
            page_url(1)
            .replace(f"search={escape(search or '')}&", "")
            .replace(f"&search={escape(search or '')}", "")
            .replace(f"search={escape(search or '')}", "")
            if search
            else ""
        )

        clear_link = (
            f'<a href="{clear_search_url or "/records"}" class="search-clear">Clear</a>'
            if search
            else ""
        )

        search_form_html = f"""
        <div class="search-section">
          <form method="get" action="/records" class="search-form">
            {filter_base}
            <input
              class="search-input"
              type="text"
              name="search"
              value="{escape(search) if search else ""}"
              placeholder="Search by reference or condition..."
              autocomplete="off"
            >
            <button class="search-btn" type="submit">Search</button>
            {clear_link}
          </form>
        </div>"""

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Public Record Index — Civic Decision Engine</title>
  <link rel="canonical" href="https://civic-decision-engine-production.up.railway.app/records">
  <meta name="description" content="Public record index for the Civic Decision Engine. Verified civic records with structured references, conditions, and trajectories.">
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
   :root {{
  --teal: #2E8B9A;
  --teal-light: #4AABB8;
  --teal-faint: rgba(46,139,154,0.08);
  --teal-mid: rgba(46,139,154,0.18);
}}

    .doc-mark {{
  display: flex;
  align-items: flex-start;
  justify-content: flex-end;
  flex-shrink: 0;
  opacity: 0.92;
}}

.doc-mark svg {{
  display: block;
  width: 42px;
  height: auto;
}}

@media (max-width: 720px) {{
  .doc-mark {{
    align-self: flex-start;
  }}

  .doc-mark svg {{
    width: 34px;
  }}
}}
    .doc-engine {{
      font-family: ui-monospace, monospace;
      font-size: 0.72rem;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: #666;
    }}
    .doc-nav a {{
      font-family: ui-monospace, monospace;
      font-size: 0.68rem;
      color: #888;
      text-decoration: none;
      border-bottom: 1px solid #ddd;
      width: fit-content;
    }}

    .doc-nav a:hover {{
      color: #1a1a1a;
      border-color: #999;
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
      gap: 12px;
      margin-bottom: 18px;
    }}
    .pill {{
      font-family: ui-monospace, monospace;
      font-size: 0.78rem;
      padding: 8px 14px;
      border: 1px solid #d0cec8;
      border-radius: 24px;
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
      .document::before {{
        content: '';
        position: fixed;
        top: 50%; left: 50%;
        transform: translate(-50%, -50%);
        width: 220px; height: 280px;
        background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 512 512' fill='none'%3E%3Cellipse cx='256' cy='256' rx='230' ry='290' stroke='%232E8B9A' stroke-width='28' fill='none'/%3E%3Crect x='148' y='138' width='216' height='18' rx='9' fill='%232E8B9A'/%3E%3Crect x='168' y='170' width='176' height='14' rx='7' fill='%232E8B9A'/%3E%3Crect x='196' y='200' width='8' height='120' rx='4' fill='%232E8B9A'/%3E%3Crect x='220' y='200' width='8' height='120' rx='4' fill='%232E8B9A'/%3E%3Crect x='244' y='200' width='8' height='120' rx='4' fill='%232E8B9A'/%3E%3Crect x='268' y='200' width='8' height='120' rx='4' fill='%232E8B9A'/%3E%3Crect x='292' y='200' width='8' height='120' rx='4' fill='%232E8B9A'/%3E%3Crect x='166' y='320' width='180' height='14' rx='7' fill='%232E8B9A'/%3E%3Ctext x='256' y='388' text-anchor='middle' font-family='sans-serif' font-size='72' font-weight='600' fill='%232E8B9A'%3Ev11%3C/text%3E%3C/svg%3E");
        background-repeat: no-repeat;
        background-size: contain;
        opacity: 0.07;
        pointer-events: none;
        z-index: 0;
      }}
    }}
 <style>

.pagination {{
  margin-top: 32px;
  padding-top: 20px;
  border-top: 1px solid #f0ede8;
}}

.footer-seal {{
  margin-top: 18px;
  display: flex;
  justify-content: flex-end;
  opacity: 0.42;
  color: var(--teal);
}}

.footer-seal svg {{
  width: 28px;
  height: auto;
  display: block;
}}

.page-info {{
  font-family: ui-monospace, monospace;
}}
    .page-controls {{
      display: flex;
      gap: 8px;
    }}
    .page-btn {{
      font-family: ui-monospace, monospace;
      font-size: 0.72rem;
      color: #1a1a1a;
      text-decoration: none;
      border: 1px solid #d0cec8;
      border-radius: 4px;
      padding: 5px 12px;
      background: #f8f7f4;
      transition: all 0.15s;
    }}
    .page-btn:hover {{ background: #eee; border-color: #999; }}
    .page-btn-disabled {{
      color: #ccc;
      border-color: #e8e6e0;
      background: #faf9f7;
      cursor: default;
    }}
    .search-section {{
      margin-bottom: 20px;
    }}
    .search-form {{
      display: flex;
      gap: 8px;
      align-items: center;
    }}
    .search-input {{
      font-family: ui-monospace, monospace;
      font-size: 0.78rem;
      padding: 7px 12px;
      border: 1px solid #d0cec8;
      border-radius: 4px;
      background: #f8f7f4;
      color: #1a1a1a;
      width: 280px;
      outline: none;
      transition: border-color 0.15s;
    }}
    .search-input:focus {{ border-color: #1a1a1a; }}
    .search-input::placeholder {{ color: #bbb; }}
    .search-btn {{
      font-family: ui-monospace, monospace;
      font-size: 0.72rem;
      padding: 7px 14px;
      border: 1px solid #1a1a1a;
      border-radius: 4px;
      background: #1a1a1a;
      color: #fff;
      cursor: pointer;
      transition: background 0.15s;
    }}
    .search-btn:hover {{ background: #333; }}
    .search-clear {{
      font-family: ui-monospace, monospace;
      font-size: 0.72rem;
      color: #888;
      text-decoration: none;
      border-bottom: 1px solid #ddd;
      padding-bottom: 1px;
    }}
    .search-clear:hover {{ color: #1a1a1a; border-color: #999; }}
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
        <a href="/patterns">Condition patterns</a>
        <a href="/graph">Interactive graph</a>
      </div>
</div>
      <div>
        <div class="doc-title">Public Record Index</div>
        <div class="doc-count">{total} record{"s" if total != 1 else ""}</div>
      </div>
      
      <div class="doc-mark" aria-label="Civic Decision Engine v11">
        <svg width="42" height="52" viewBox="0 0 512 512" fill="none">
          <ellipse cx="256" cy="256" rx="230" ry="290" stroke="var(--teal)" stroke-width="28" fill="none"/>
          <rect x="148" y="138" width="216" height="18" rx="9" fill="var(--teal)"/>
          <rect x="168" y="170" width="176" height="14" rx="7" fill="var(--teal)"/>
          <rect x="196" y="200" width="8" height="120" rx="4" fill="var(--teal)"/>
          <rect x="220" y="200" width="8" height="120" rx="4" fill="var(--teal)"/>
          <rect x="244" y="200" width="8" height="120" rx="4" fill="var(--teal)"/>
          <rect x="268" y="200" width="8" height="120" rx="4" fill="var(--teal)"/>
          <rect x="292" y="200" width="8" height="120" rx="4" fill="var(--teal)"/>
          <rect x="166" y="320" width="180" height="14" rx="7" fill="var(--teal)"/>
          <text x="256" y="388" text-anchor="middle" font-family="sans-serif" font-size="72" font-weight="600" fill="var(--teal)">v11</text>
        </svg>
      </div>
    </header>

    {search_form_html}

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

    {pagination_html}

    <footer class="doc-footer">
      <div class="footer-tagline">The record does not argue.</div>

      <div class="footer-note">
        Public records are generated by the Civic Decision Engine and stored
        at the time of export. Each record is independently verifiable via its reference URL.
      </div>

      <div class="footer-seal" aria-label="Civic Decision Engine v11">
        <div class="doc-mark" aria-label="Civic Decision Engine v11">
        <svg width="42" height="52" viewBox="0 0 512 512" fill="none">
          <ellipse cx="256" cy="256" rx="230" ry="290" stroke="var(--teal)" stroke-width="28" fill="none"/>
          <rect x="148" y="138" width="216" height="18" rx="9" fill="var(--teal)"/>
          <rect x="168" y="170" width="176" height="14" rx="7" fill="var(--teal)"/>
          <rect x="196" y="200" width="8" height="120" rx="4" fill="var(--teal)"/>
          <rect x="220" y="200" width="8" height="120" rx="4" fill="var(--teal)"/>
          <rect x="244" y="200" width="8" height="120" rx="4" fill="var(--teal)"/>
          <rect x="268" y="200" width="8" height="120" rx="4" fill="var(--teal)"/>
          <rect x="292" y="200" width="8" height="120" rx="4" fill="var(--teal)"/>
          <rect x="166" y="320" width="180" height="14" rx="7" fill="var(--teal)"/>
          <text x="256" y="388" text-anchor="middle" font-family="sans-serif" font-size="72" font-weight="600" fill="var(--teal)">v11</text>
        </svg>
      </div>

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
                    "source_narrative": record["source_narrative"] or "",
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

        PER_PAGE = 25
        offset = (page - 1) * PER_PAGE

        # Total count for pagination
        cur.execute(f"SELECT COUNT(*) FROM records WHERE {where}", params)
        total_count = cur.fetchone()[0]
        total_pages = max(1, -(-total_count // PER_PAGE))  # ceiling division

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
                "source_narrative": record["source_narrative"] or "",
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
  <link rel="canonical" href="https://civic-decision-engine-production.up.railway.app/api/docs">
  <meta name="description" content="Public API documentation for the Civic Decision Engine. Machine-readable access to verified civic records, conditions, and archive statistics.">
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
    :root {
      --teal: #2E8B9A;
      --teal-light: #4AABB8;
      --teal-faint: rgba(46,139,154,0.08);
      --teal-mid: rgba(46,139,154,0.18);
    }

    .doc-mark {
      display: flex;
      align-items: flex-start;
      justify-content: flex-end;
      flex-shrink: 0;
      opacity: 0.92;
    }

    .doc-mark svg {
      display: block;
      width: 42px;
      height: auto;
    }

    @media (max-width: 720px) {
      .doc-mark {
        align-self: flex-start;
      }

      .doc-mark svg {
        width: 34px;
      }
    }
       :root {{
        --teal: #2E8B9A;
        --teal-light: #4AABB8;
        --teal-faint: rgba(46,139,154,0.08);
        --teal-mid: rgba(46,139,154,0.18);
      }}

          .doc-mark {{
        display: flex;
        align-items: flex-start;
        justify-content: flex-end;
        flex-shrink: 0;
        opacity: 0.92;
      }}

      .doc-mark svg {{
        display: block;
        width: 42px;
        height: auto;
      }}

      @media (max-width: 720px) {{
        .doc-mark {{
          align-self: flex-start;
        }}

        .doc-mark svg {{
          width: 34px;
        }}
      }}

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
    .footer-seal {
      display: flex;
      justify-content: flex-end;
      align-items: flex-end;
      opacity: 0.42;
      color: var(--teal);
    }
    .footer-seal svg { display: block; }
    @media print {
      body { background: white; padding: 0; }
      .document { border: none; box-shadow: none; padding: 32px; }
      .curl-block { background: #f0f0f0; color: #1a1a1a; }
      .document::before {
        content: '';
        position: fixed;
        top: 50%; left: 50%;
        transform: translate(-50%, -50%);
        width: 220px; height: 280px;
        background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 512 512' fill='none'%3E%3Cellipse cx='256' cy='256' rx='230' ry='290' stroke='%232E8B9A' stroke-width='28' fill='none'/%3E%3Crect x='148' y='138' width='216' height='18' rx='9' fill='%232E8B9A'/%3E%3Crect x='168' y='170' width='176' height='14' rx='7' fill='%232E8B9A'/%3E%3Crect x='196' y='200' width='8' height='120' rx='4' fill='%232E8B9A'/%3E%3Crect x='220' y='200' width='8' height='120' rx='4' fill='%232E8B9A'/%3E%3Crect x='244' y='200' width='8' height='120' rx='4' fill='%232E8B9A'/%3E%3Crect x='268' y='200' width='8' height='120' rx='4' fill='%232E8B9A'/%3E%3Crect x='292' y='200' width='8' height='120' rx='4' fill='%232E8B9A'/%3E%3Crect x='166' y='320' width='180' height='14' rx='7' fill='%232E8B9A'/%3E%3Ctext x='256' y='388' text-anchor='middle' font-family='sans-serif' font-size='72' font-weight='600' fill='%232E8B9A'%3Ev11%3C/text%3E%3C/svg%3E");
        background-repeat: no-repeat;
        background-size: contain;
        opacity: 0.07;
        pointer-events: none;
        z-index: 0;
      }
    }
  </style>
</head>
<body>
  <div class="document">

    <header class="doc-header">
      <div>
        <div class="doc-engine">Civic Decision Engine</div>
        <a href="/records" class="doc-index-link">← Public record index</a>
        &nbsp; <a href="/stats" class="doc-index-link" style="margin-top:4px;display:inline-block;">Archive statistics</a> 
      </div>
      <div>
        <div class="doc-title">Public API Documentation</div>
        <div class="doc-subtitle">Machine-readable civic record access</div>
      </div>
       <div class="doc-mark" aria-label="Civic Decision Engine v11">
        <svg width="42" height="52" viewBox="0 0 512 512" fill="none">
          <ellipse cx="256" cy="256" rx="230" ry="290" stroke="var(--teal)" stroke-width="28" fill="none"/>
          <rect x="148" y="138" width="216" height="18" rx="9" fill="var(--teal)"/>
          <rect x="168" y="170" width="176" height="14" rx="7" fill="var(--teal)"/>
          <rect x="196" y="200" width="8" height="120" rx="4" fill="var(--teal)"/>
          <rect x="220" y="200" width="8" height="120" rx="4" fill="var(--teal)"/>
          <rect x="244" y="200" width="8" height="120" rx="4" fill="var(--teal)"/>
          <rect x="268" y="200" width="8" height="120" rx="4" fill="var(--teal)"/>
          <rect x="292" y="200" width="8" height="120" rx="4" fill="var(--teal)"/>
          <rect x="166" y="320" width="180" height="14" rx="7" fill="var(--teal)"/>
          <text x="256" y="388" text-anchor="middle" font-family="sans-serif" font-size="72" font-weight="600" fill="var(--teal)">v11</text>
        </svg>
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
      <div class="footer-seal" aria-label="Civic Decision Engine v11">
        <svg width="28" height="35" viewBox="0 0 512 512" fill="none">
          <ellipse cx="256" cy="256" rx="230" ry="290" stroke="var(--teal)" stroke-width="28" fill="none"/>
          <rect x="148" y="138" width="216" height="18" rx="9" fill="var(--teal)"/>
          <rect x="168" y="170" width="176" height="14" rx="7" fill="var(--teal)"/>
          <rect x="196" y="200" width="8" height="120" rx="4" fill="var(--teal)"/>
          <rect x="220" y="200" width="8" height="120" rx="4" fill="var(--teal)"/>
          <rect x="244" y="200" width="8" height="120" rx="4" fill="var(--teal)"/>
          <rect x="268" y="200" width="8" height="120" rx="4" fill="var(--teal)"/>
          <rect x="292" y="200" width="8" height="120" rx="4" fill="var(--teal)"/>
          <rect x="166" y="320" width="180" height="14" rx="7" fill="var(--teal)"/>
          <text x="256" y="388" text-anchor="middle" font-family="sans-serif" font-size="72" font-weight="600" fill="var(--teal)">v11</text>
        </svg>
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
            <h3 class="condition-name">
              <a href="/conditions/{escape(condition['id'])}"
                 style="color:#1a1a1a;text-decoration:none;border-bottom:1px solid #ddd;">
                {escape(condition['name'])}
              </a>
            </h3>
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
  <link rel="canonical" href="https://civic-decision-engine-production.up.railway.app/conditions">
  <meta name="description" content="Canonical condition registry for the Civic Decision Engine. Formal definitions of civic observation conditions used in verified public records.">
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
      :root {{
          --teal: #2E8B9A;
          --teal-light: #4AABB8;
          --teal-faint: rgba(46,139,154,0.08);
          --teal-mid: rgba(46,139,154,0.18);
      }}

        .doc-mark {{
        display: flex;
        align-items: flex-start;
        justify-content: flex-end;
        flex-shrink: 0;
        opacity: 0.92;
      }}

      .doc-mark svg {{
        display: block;
        width: 42px;
        height: auto;
      }}

      @media (max-width: 720px) {{
        .doc-mark {{
          align-self: flex-start;
        }}

        .doc-mark svg {{
          width: 34px;
        }}
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
    .footer-seal {{
      display: flex;
      justify-content: flex-end;
      align-items: flex-end;
      opacity: 0.42;
      color: var(--teal);
    }}
    .footer-seal svg {{ display: block; }}
    @media print {{
      body {{ background: white; padding: 0; }}
      .document {{ border: none; box-shadow: none; padding: 32px; }}
      .document::before {{
        content: '';
        position: fixed;
        top: 50%; left: 50%;
        transform: translate(-50%, -50%);
        width: 220px; height: 280px;
        background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 512 512' fill='none'%3E%3Cellipse cx='256' cy='256' rx='230' ry='290' stroke='%232E8B9A' stroke-width='28' fill='none'/%3E%3Crect x='148' y='138' width='216' height='18' rx='9' fill='%232E8B9A'/%3E%3Crect x='168' y='170' width='176' height='14' rx='7' fill='%232E8B9A'/%3E%3Crect x='196' y='200' width='8' height='120' rx='4' fill='%232E8B9A'/%3E%3Crect x='220' y='200' width='8' height='120' rx='4' fill='%232E8B9A'/%3E%3Crect x='244' y='200' width='8' height='120' rx='4' fill='%232E8B9A'/%3E%3Crect x='268' y='200' width='8' height='120' rx='4' fill='%232E8B9A'/%3E%3Crect x='292' y='200' width='8' height='120' rx='4' fill='%232E8B9A'/%3E%3Crect x='166' y='320' width='180' height='14' rx='7' fill='%232E8B9A'/%3E%3Ctext x='256' y='388' text-anchor='middle' font-family='sans-serif' font-size='72' font-weight='600' fill='%232E8B9A'%3Ev11%3C/text%3E%3C/svg%3E");
        background-repeat: no-repeat;
        background-size: contain;
        opacity: 0.07;
        pointer-events: none;
        z-index: 0;
      }}
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
          <a href="/patterns">Condition patterns</a>
          <a href="/graph">Interactive graph</a>
        </div>
      </div>
      <div>
        <div class="doc-title">Condition Registry</div>
        <div class="doc-subtitle">Civic observation taxonomy</div>       
      </div>
      <div class="doc-mark" aria-label="Civic Decision Engine v11">
      <svg width="42" height="52" viewBox="0 0 512 512" fill="none">
        <ellipse cx="256" cy="256" rx="230" ry="290" stroke="var(--teal)" stroke-width="28" fill="none"/>
        <rect x="148" y="138" width="216" height="18" rx="9" fill="var(--teal)"/>
        <rect x="168" y="170" width="176" height="14" rx="7" fill="var(--teal)"/>
        <rect x="196" y="200" width="8" height="120" rx="4" fill="var(--teal)"/>
        <rect x="220" y="200" width="8" height="120" rx="4" fill="var(--teal)"/>
        <rect x="244" y="200" width="8" height="120" rx="4" fill="var(--teal)"/>
        <rect x="268" y="200" width="8" height="120" rx="4" fill="var(--teal)"/>
        <rect x="292" y="200" width="8" height="120" rx="4" fill="var(--teal)"/>
        <rect x="166" y="320" width="180" height="14" rx="7" fill="var(--teal)"/>
        <text x="256" y="388" text-anchor="middle" font-family="sans-serif" font-size="72" font-weight="600" fill="var(--teal)">v11</text>
      </svg>
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
      <div class="footer-seal" aria-label="Civic Decision Engine v11">
        <svg width="28" height="35" viewBox="0 0 512 512" fill="none">
          <ellipse cx="256" cy="256" rx="230" ry="290" stroke="var(--teal)" stroke-width="28" fill="none"/>
          <rect x="148" y="138" width="216" height="18" rx="9" fill="var(--teal)"/>
          <rect x="168" y="170" width="176" height="14" rx="7" fill="var(--teal)"/>
          <rect x="196" y="200" width="8" height="120" rx="4" fill="var(--teal)"/>
          <rect x="220" y="200" width="8" height="120" rx="4" fill="var(--teal)"/>
          <rect x="244" y="200" width="8" height="120" rx="4" fill="var(--teal)"/>
          <rect x="268" y="200" width="8" height="120" rx="4" fill="var(--teal)"/>
          <rect x="292" y="200" width="8" height="120" rx="4" fill="var(--teal)"/>
          <rect x="166" y="320" width="180" height="14" rx="7" fill="var(--teal)"/>
          <text x="256" y="388" text-anchor="middle" font-family="sans-serif" font-size="72" font-weight="600" fill="var(--teal)">v11</text>
        </svg>
      </div>
    </footer>
  </div>
</body>
</html>"""
    return HTMLResponse(content=html, status_code=200)


@router.get("/conditions/{condition_id}", response_class=HTMLResponse)
async def condition_page(condition_id: str):
    # Find condition in registry
    condition = next((c for c in CONDITION_REGISTRY if c["id"] == condition_id), None)
    if not condition:
        raise HTTPException(status_code=404, detail="Condition not found")

    conn = get_db()
    try:
        cur = conn.cursor()

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

        # Records containing this condition
        cur.execute(
            "SELECT reference, trajectory, conditions_json, exported_at, version "
            "FROM records WHERE is_latest = 1 AND "
            "LOWER(conditions_json) LIKE LOWER(?) "
            "ORDER BY exported_at DESC",
            (f"%{condition['name']}%",),
        )
        matching_records = cur.fetchall()
        occurrence_count = len(matching_records)

        # Co-occurring conditions
        cooccurrence: dict[str, int] = {}
        for rec in matching_records:
            conditions_list = json.loads(rec["conditions_json"] or "[]")
            for c in conditions_list:
                if c != condition["name"]:
                    cooccurrence[c] = cooccurrence.get(c, 0) + 1

        cooccurrence_sorted = sorted(
            cooccurrence.items(), key=lambda x: x[1], reverse=True
        )

        # Institution breakdown
        institution_counts: dict[str, int] = {}
        for rec in matching_records:
            code = extract_institution_type(rec["reference"])
            institution_counts[code] = institution_counts.get(code, 0) + 1

        institution_sorted = sorted(
            institution_counts.items(), key=lambda x: x[1], reverse=True
        )

        # Build indicators HTML
        indicators_html = "".join(
            f"<li>{escape(ind)}</li>" for ind in condition["indicators"]
        )

        # Build linked records HTML
        records_html = ""
        for rec in matching_records:
            inst_code = extract_institution_type(rec["reference"])
            inst_label = INSTITUTION_LABELS.get(inst_code, inst_code)
            exported = rec["exported_at"][:10] if rec["exported_at"] else "—"
            version_badge = (
                f' <span class="version-badge">v{rec["version"]}</span>'
                if rec["version"] > 1
                else ""
            )
            traj = escape(rec["trajectory"] or "—")
            records_html += (
                f"<tr>"
                f'<td class="rec-ref">'
                f'<a href="/verify/{escape(rec["reference"])}" class="rec-link">'
                f'{escape(rec["reference"])}{version_badge}</a></td>'
                f'<td class="rec-inst">{escape(inst_label)}</td>'
                f'<td class="rec-traj">{traj}</td>'
                f'<td class="rec-date">{escape(exported)}</td>'
                f"</tr>"
            )

        if not records_html:
            records_html = (
                '<tr><td colspan="4" class="empty-state">'
                "No records currently carry this condition.</td></tr>"
            )

        # Build co-occurrence HTML
        cooccurrence_html = ""
        for cond_name, count in cooccurrence_sorted:
            # Find the id for linking
            linked = next(
                (c for c in CONDITION_REGISTRY if c["name"] == cond_name), None
            )
            if linked:
                cooccurrence_html += (
                    f'<div class="co-item">'
                    f'<a href="/conditions/{escape(linked["id"])}" class="co-link">'
                    f"{escape(cond_name)}</a>"
                    f'<span class="co-count">{count} record{"s" if count != 1 else ""}</span>'
                    f"</div>"
                )
            else:
                cooccurrence_html += (
                    f'<div class="co-item">'
                    f'<span class="co-name">{escape(cond_name)}</span>'
                    f'<span class="co-count">{count} record{"s" if count != 1 else ""}</span>'
                    f"</div>"
                )

        if not cooccurrence_html:
            cooccurrence_html = (
                '<p class="empty-note">No co-occurring conditions recorded yet.</p>'
            )

        # Build institution breakdown HTML
        inst_html = ""
        for code, count in institution_sorted:
            label = INSTITUTION_LABELS.get(code, code)
            pct = round((count / occurrence_count) * 100) if occurrence_count else 0
            inst_html += (
                f"<tr>"
                f'<td class="stat-label">{escape(code)}</td>'
                f'<td class="stat-desc">{escape(label)}</td>'
                f'<td class="stat-count">{count}</td>'
                f'<td class="stat-bar-cell">'
                f'<div class="stat-bar" style="width:{pct}%"></div></td>'
                f"</tr>"
            )

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{escape(condition['name'])} — Condition — Civic Decision Engine</title>
  <link rel="canonical" href="https://civic-decision-engine-production.up.railway.app/conditions/{escape(condition['id'])}">
  <meta name="description" content="{escape(condition['description'][:160])}">
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
    .doc-mark {{
      margin-bottom: 10px;
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
    .condition-name {{
      font-size: 1.4rem;
      font-family: Georgia, serif;
      font-weight: bold;
      color: #1a1a1a;
      margin: 0 0 6px;
      line-height: 1.3;
    }}
    .condition-code {{
      font-family: ui-monospace, monospace;
      font-size: 0.72rem;
      color: #aaa;
      letter-spacing: 0.04em;
      margin-bottom: 20px;
      display: block;
    }}
    .condition-description {{
      font-size: 0.975rem;
      color: #333;
      line-height: 1.8;
      margin-bottom: 8px;
    }}
    .indicators-label {{
      font-family: ui-monospace, monospace;
      font-size: 0.65rem;
      text-transform: uppercase;
      letter-spacing: 0.1em;
      color: #aaa;
      margin: 20px 0 10px;
    }}
    .indicators-list {{
      margin: 0;
      padding-left: 20px;
      color: #444;
      font-size: 0.9rem;
      line-height: 1.8;
    }}
    .indicators-list li {{ margin-bottom: 6px; }}
    .occurrence-card {{
      background: #f8f7f4;
      border: 1px solid #e8e6e0;
      border-radius: 4px;
      padding: 18px 20px;
      display: flex;
      align-items: baseline;
      gap: 12px;
      margin-bottom: 8px;
    }}
    .occurrence-number {{
      font-family: ui-monospace, monospace;
      font-size: 2rem;
      font-weight: bold;
      color: #1a1a1a;
      line-height: 1;
    }}
    .occurrence-label {{
      font-family: ui-monospace, monospace;
      font-size: 0.72rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: #888;
    }}
    .records-table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.875rem;
    }}
    .records-table thead tr {{ border-bottom: 2px solid #1a1a1a; }}
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
    .records-table tbody tr {{ border-bottom: 1px solid #f0ede8; }}
    .records-table tbody tr:hover {{ background: #faf9f7; }}
    .records-table td {{
      padding: 10px 12px 10px 0;
      vertical-align: top;
      color: #333;
    }}
    .rec-ref {{ width: 220px; }}
    .rec-inst {{ width: 140px; }}
    .rec-traj {{ width: 120px; }}
    .rec-date {{ width: 90px; white-space: nowrap; }}
    .rec-link {{
      font-family: ui-monospace, monospace;
      font-size: 0.8rem;
      color: #1a1a1a;
      text-decoration: none;
      border-bottom: 1px solid #ccc;
    }}
    .rec-link:hover {{ border-color: #1a1a1a; }}
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
      padding: 24px 0;
      font-family: ui-monospace, monospace;
      font-size: 0.82rem;
    }}
    .empty-note {{
      color: #aaa;
      font-style: italic;
      font-family: ui-monospace, monospace;
      font-size: 0.82rem;
      margin: 0;
    }}
    .co-item {{
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      padding: 10px 0;
      border-bottom: 1px solid #f0ede8;
    }}
    .co-item:last-child {{ border-bottom: none; }}
    .co-link {{
      font-size: 0.9rem;
      color: #1a1a1a;
      text-decoration: none;
      border-bottom: 1px solid #ddd;
      font-family: Georgia, serif;
    }}
    .co-link:hover {{ border-color: #1a1a1a; }}
    .co-name {{ font-size: 0.9rem; color: #444; font-family: Georgia, serif; }}
    .co-count {{
      font-family: ui-monospace, monospace;
      font-size: 0.72rem;
      color: #888;
    }}
    .stat-table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.875rem;
    }}
    .stat-table tr {{ border-bottom: 1px solid #f0ede8; }}
    .stat-table tr:last-child {{ border-bottom: none; }}
    .stat-table td {{ padding: 8px 8px 8px 0; vertical-align: middle; }}
    .stat-label {{
      font-family: ui-monospace, monospace;
      font-size: 0.78rem;
      color: #1a1a1a;
      width: 48px;
    }}
    .stat-desc {{ color: #444; width: 160px; }}
    .stat-count {{
      font-family: ui-monospace, monospace;
      font-size: 0.82rem;
      color: #1a1a1a;
      text-align: right;
      width: 40px;
      padding-right: 16px;
    }}
    .stat-bar-cell {{ width: 100%; }}
    .stat-bar {{
      height: 5px;
      background: #1a1a1a;
      border-radius: 2px;
      min-width: 2px;
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
      .rec-inst, .rec-traj {{ display: none; }}
      .doc-footer {{ flex-direction: column; align-items: flex-start; }}
      .footer-note {{ text-align: left; }}
    }}
    @media print {{
      body {{ background: white; padding: 0; }}
      .document {{ border: none; box-shadow: none; padding: 32px; }}
    }}
    @media print {{
      .document::before {{
        content: "";
        position: fixed;
        top: 50%;
        left: 50%;
        transform: translate(-50%, -50%);
        width: 300px;
        height: 300px;
        background-image: url("data:image/svg+xml,%3Csvg width='512' height='512' viewBox='0 0 512 512' fill='none' xmlns='http://www.w3.org/2000/svg'%3E%3Cellipse cx='256' cy='256' rx='230' ry='290' stroke='%232E8B9A' stroke-width='28' fill='none'/%3E%3Crect x='148' y='138' width='216' height='18' rx='9' fill='%232E8B9A'/%3E%3Crect x='168' y='170' width='176' height='14' rx='7' fill='%232E8B9A'/%3E%3Crect x='196' y='200' width='8' height='120' rx='4' fill='%232E8B9A'/%3E%3Crect x='220' y='200' width='8' height='120' rx='4' fill='%232E8B9A'/%3E%3Crect x='244' y='200' width='8' height='120' rx='4' fill='%232E8B9A'/%3E%3Crect x='268' y='200' width='8' height='120' rx='4' fill='%232E8B9A'/%3E%3Crect x='292' y='200' width='8' height='120' rx='4' fill='%232E8B9A'/%3E%3Crect x='166' y='320' width='180' height='14' rx='7' fill='%232E8B9A'/%3E%3Ctext x='256' y='388' text-anchor='middle' font-family='sans-serif' font-size='72' font-weight='600' fill='%232E8B9A'%3Ev11%3C/text%3E%3C/svg%3E");
        background-repeat: no-repeat;
        background-size: contain;
        opacity: 0.07;
        pointer-events: none;
        z-index: 0;
    }}
  </style>
</head>
<body>
  <div class="document">
    <header class="doc-header">
      <div>
        <div class="doc-engine">Civic Decision Engine</div>
        <div class="doc-nav">
          <a href="/conditions">← Condition registry</a>
          <a href="/records">Public record index</a>
          <a href="/patterns">Condition patterns</a>
          <a href="/api/docs">API documentation</a>
        </div>
      </div>
      <div>
        <div style="margin-left:auto;text-align:right;display:flex;flex-direction:column;align-items:flex-end;">
        <div class="doc-mark" aria-label="Civic Decision Engine v11" style="opacity:0.82;margin-bottom:6px;">
          <svg width="42" height="52" viewBox="0 0 512 512" fill="none">
            <ellipse cx="256" cy="256" rx="230" ry="290" stroke="#2E8B9A" stroke-width="28" fill="none"/>
            <rect x="148" y="138" width="216" height="18" rx="9" fill="#2E8B9A"/>
            <rect x="168" y="170" width="176" height="14" rx="7" fill="#2E8B9A"/>
            <rect x="196" y="200" width="8" height="120" rx="4" fill="#2E8B9A"/>
            <rect x="220" y="200" width="8" height="120" rx="4" fill="#2E8B9A"/>
            <rect x="244" y="200" width="8" height="120" rx="4" fill="#2E8B9A"/>
            <rect x="268" y="200" width="8" height="120" rx="4" fill="#2E8B9A"/>
            <rect x="292" y="200" width="8" height="120" rx="4" fill="#2E8B9A"/>
            <rect x="166" y="320" width="180" height="14" rx="7" fill="#2E8B9A"/>
            <text x="256" y="388" text-anchor="middle" font-family="sans-serif" font-size="72" font-weight="600" fill="#2E8B9A">v11</text>
          </svg>
        </div>
        <div class="doc-title">Condition</div>
        <div class="doc-subtitle">Civic diagnostic unit</div>
      </div>
    </header>

    <h1 class="condition-name">{escape(condition['name'])}</h1>
    <span class="condition-code">{escape(condition['code'])}</span>
    <p class="condition-description">{escape(condition['description'])}</p>

    <div class="indicators-label">Indicators</div>
    <ul class="indicators-list">{indicators_html}</ul>

    <div class="section-header">Occurrence in archive</div>
    <div class="occurrence-card">
      <span class="occurrence-number">{occurrence_count}</span>
      <span class="occurrence-label">
        verified record{"s" if occurrence_count != 1 else ""} carry this condition
      </span>
    </div>

    <div class="section-header">By institution type</div>
    {"<table class='stat-table'><tbody>" + inst_html + "</tbody></table>"
      if inst_html else '<p class="empty-note">No institution data yet.</p>'}

    <div class="section-header">
      Associated records — {occurrence_count} total
    </div>
    <table class="records-table">
      <thead>
        <tr>
          <th>Reference</th>
          <th>Institution</th>
          <th>Trajectory</th>
          <th>Exported</th>
        </tr>
      </thead>
      <tbody>{records_html}</tbody>
    </table>

    <div class="section-header">Co-occurring conditions</div>
    <div class="co-list">{cooccurrence_html}</div>

    <div class="api-note">
      Machine-readable access:
      <a href="/api/conditions">/api/conditions</a>
      &nbsp;·&nbsp;
      Full condition registry as JSON, including this condition at
      <code>id: {escape(condition['id'])}</code>.
    </div>

    <footer class="doc-footer">
      <div class="footer-tagline">The record does not argue.</div>
      <div class="footer-note">
        This condition is part of the Civic Decision Engine diagnostic taxonomy.
        Occurrence counts reflect the current verified public archive only.
      </div>
      <div aria-hidden="true" style="opacity:0.42;flex-shrink:0;">
        <svg width="28" height="35" viewBox="0 0 512 512" fill="none">
          <ellipse cx="256" cy="256" rx="230" ry="290" stroke="#2E8B9A" stroke-width="28" fill="none"/>
          <rect x="148" y="138" width="216" height="18" rx="9" fill="#2E8B9A"/>
          <rect x="168" y="170" width="176" height="14" rx="7" fill="#2E8B9A"/>
          <rect x="196" y="200" width="8" height="120" rx="4" fill="#2E8B9A"/>
          <rect x="220" y="200" width="8" height="120" rx="4" fill="#2E8B9A"/>
          <rect x="244" y="200" width="8" height="120" rx="4" fill="#2E8B9A"/>
          <rect x="268" y="200" width="8" height="120" rx="4" fill="#2E8B9A"/>
          <rect x="292" y="200" width="8" height="120" rx="4" fill="#2E8B9A"/>
          <rect x="166" y="320" width="180" height="14" rx="7" fill="#2E8B9A"/>
          <text x="256" y="388" text-anchor="middle" font-family="sans-serif" font-size="72" font-weight="600" fill="#2E8B9A">v11</text>
        </svg>
      </div>
    </footer>
  </div>
</body>
</html>"""

        return HTMLResponse(content=html, status_code=200)

    finally:
        conn.close()


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
  <link rel="canonical" href="https://civic-decision-engine-production.up.railway.app/stats">
  <meta name="description" content="Archive statistics for the Civic Decision Engine. Record counts, condition distributions, and institutional breakdowns across the verified public record archive.">
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
       :root {{
        --teal: #2E8B9A;
        --teal-light: #4AABB8;
        --teal-faint: rgba(46,139,154,0.08);
        --teal-mid: rgba(46,139,154,0.18);
      }}

          .doc-mark {{
        display: flex;
        align-items: flex-start;
        justify-content: flex-end;
        flex-shrink: 0;
        opacity: 0.92;
      }}

      .doc-mark svg {{
        display: block;
        width: 42px;
        height: auto;
      }}

      @media (max-width: 720px) {{
        .doc-mark {{
          align-self: flex-start;
        }}

        .doc-mark svg {{
          width: 34px;
        }}
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
    .footer-seal {{
      display: flex;
      justify-content: flex-end;
      align-items: flex-end;
      opacity: 0.42;
      color: var(--teal);
    }}
    .footer-seal svg {{ display: block; }}
    @media print {{
      body {{ background: white; padding: 0; }}
      .document {{ border: none; box-shadow: none; padding: 32px; }}
      .document::before {{
        content: '';
        position: fixed;
        top: 50%; left: 50%;
        transform: translate(-50%, -50%);
        width: 220px; height: 280px;
        background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 512 512' fill='none'%3E%3Cellipse cx='256' cy='256' rx='230' ry='290' stroke='%232E8B9A' stroke-width='28' fill='none'/%3E%3Crect x='148' y='138' width='216' height='18' rx='9' fill='%232E8B9A'/%3E%3Crect x='168' y='170' width='176' height='14' rx='7' fill='%232E8B9A'/%3E%3Crect x='196' y='200' width='8' height='120' rx='4' fill='%232E8B9A'/%3E%3Crect x='220' y='200' width='8' height='120' rx='4' fill='%232E8B9A'/%3E%3Crect x='244' y='200' width='8' height='120' rx='4' fill='%232E8B9A'/%3E%3Crect x='268' y='200' width='8' height='120' rx='4' fill='%232E8B9A'/%3E%3Crect x='292' y='200' width='8' height='120' rx='4' fill='%232E8B9A'/%3E%3Crect x='166' y='320' width='180' height='14' rx='7' fill='%232E8B9A'/%3E%3Ctext x='256' y='388' text-anchor='middle' font-family='sans-serif' font-size='72' font-weight='600' fill='%232E8B9A'%3Ev11%3C/text%3E%3C/svg%3E");
        background-repeat: no-repeat;
        background-size: contain;
        opacity: 0.07;
        pointer-events: none;
        z-index: 0;
      }}
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
          <a href="/patterns">Condition patterns</a>
          <a href="/graph">Interactive graph</a>
          <a href="/stats/timeline">Archive timeline</a>
        </div>
      </div>
      <div>
        <div class="doc-title">Archive Statistics</div>
        <div class="doc-subtitle">Public record distribution</div>
      </div>
      <div class="doc-mark" aria-label="Civic Decision Engine v11">
        <svg width="42" height="52" viewBox="0 0 512 512" fill="none">
          <ellipse cx="256" cy="256" rx="230" ry="290" stroke="var(--teal)" stroke-width="28" fill="none"/>
          <rect x="148" y="138" width="216" height="18" rx="9" fill="var(--teal)"/>
          <rect x="168" y="170" width="176" height="14" rx="7" fill="var(--teal)"/>
          <rect x="196" y="200" width="8" height="120" rx="4" fill="var(--teal)"/>
          <rect x="220" y="200" width="8" height="120" rx="4" fill="var(--teal)"/>
          <rect x="244" y="200" width="8" height="120" rx="4" fill="var(--teal)"/>
          <rect x="268" y="200" width="8" height="120" rx="4" fill="var(--teal)"/>
          <rect x="292" y="200" width="8" height="120" rx="4" fill="var(--teal)"/>
          <rect x="166" y="320" width="180" height="14" rx="7" fill="var(--teal)"/>
          <text x="256" y="388" text-anchor="middle" font-family="sans-serif" font-size="72" font-weight="600" fill="var(--teal)">v11</text>
        </svg>
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
      <div class="footer-seal" aria-label="Civic Decision Engine v11">
        <svg width="28" height="35" viewBox="0 0 512 512" fill="none">
          <ellipse cx="256" cy="256" rx="230" ry="290" stroke="var(--teal)" stroke-width="28" fill="none"/>
          <rect x="148" y="138" width="216" height="18" rx="9" fill="var(--teal)"/>
          <rect x="168" y="170" width="176" height="14" rx="7" fill="var(--teal)"/>
          <rect x="196" y="200" width="8" height="120" rx="4" fill="var(--teal)"/>
          <rect x="220" y="200" width="8" height="120" rx="4" fill="var(--teal)"/>
          <rect x="244" y="200" width="8" height="120" rx="4" fill="var(--teal)"/>
          <rect x="268" y="200" width="8" height="120" rx="4" fill="var(--teal)"/>
          <rect x="292" y="200" width="8" height="120" rx="4" fill="var(--teal)"/>
          <rect x="166" y="320" width="180" height="14" rx="7" fill="var(--teal)"/>
          <text x="256" y="388" text-anchor="middle" font-family="sans-serif" font-size="72" font-weight="600" fill="var(--teal)">v11</text>
        </svg>
      </div>
    </footer>
  </div>
</body>
</html>"""

        return HTMLResponse(content=html, status_code=200)

    finally:
        conn.close()


@router.get("/stats/timeline", response_class=HTMLResponse)
async def stats_timeline():
    conn = get_db()
    try:
        cur = conn.cursor()

        # All records with timestamps — latest versions only
        cur.execute(
            "SELECT reference, conditions_json, trajectory, exported_at "
            "FROM records WHERE is_latest = 1 ORDER BY exported_at ASC"
        )
        rows = cur.fetchall()

        # ── Monthly condition frequency ───────────────────────────
        # month_conditions: { "2026-05": { "Transfer of Burden": 3, ... }, ... }
        month_conditions: dict[str, dict[str, int]] = {}
        month_record_counts: dict[str, int] = {}

        for row in rows:
            exported = row["exported_at"] or ""
            month = exported[:7]  # "YYYY-MM"
            if not month:
                continue
            conditions = json.loads(row["conditions_json"] or "[]")
            month_record_counts[month] = month_record_counts.get(month, 0) + 1
            if month not in month_conditions:
                month_conditions[month] = {}
            for c in conditions:
                month_conditions[month][c] = month_conditions[month].get(c, 0) + 1

        all_months = sorted(month_conditions.keys())

        # All condition names seen across archive
        all_condition_names: list[str] = []
        seen: set[str] = set()
        for row in rows:
            for c in json.loads(row["conditions_json"] or "[]"):
                if c not in seen:
                    all_condition_names.append(c)
                    seen.add(c)

        # ── Trajectory emergence ──────────────────────────────────
        # First time each trajectory appeared
        trajectory_first: dict[str, str] = {}
        trajectory_counts: dict[str, int] = {}
        for row in rows:
            traj = row["trajectory"] or ""
            if not traj:
                continue
            exported = row["exported_at"] or ""
            if traj not in trajectory_first:
                trajectory_first[traj] = exported[:10]
            trajectory_counts[traj] = trajectory_counts.get(traj, 0) + 1

        # ── Condition emergence ───────────────────────────────────
        # First time each condition appeared
        condition_first: dict[str, str] = {}
        for row in rows:
            exported = row["exported_at"] or ""
            conditions = json.loads(row["conditions_json"] or "[]")
            for c in conditions:
                if c not in condition_first:
                    condition_first[c] = exported[:10]

        # ── Build monthly frequency table ─────────────────────────
        if all_months and all_condition_names:
            # Header row
            month_headers = "".join(
                f'<th class="tl-month">{escape(m)}</th>' for m in all_months
            )
            freq_header = f"""
            <tr>
              <th class="tl-label">Condition</th>
              {month_headers}
              <th class="tl-total">Total</th>
            </tr>"""

            # Data rows
            freq_rows = ""
            for cond in all_condition_names:
                total = sum(
                    month_conditions.get(m, {}).get(cond, 0) for m in all_months
                )
                cells = "".join(
                    f'<td class="tl-cell">'
                    f'{"" if month_conditions.get(m, {}).get(cond, 0) == 0 else month_conditions.get(m, {}).get(cond, 0)}'
                    f"</td>"
                    for m in all_months
                )
                freq_rows += f"""
                <tr>
                  <td class="tl-cond">{escape(cond)}</td>
                  {cells}
                  <td class="tl-total-cell">{total}</td>
                </tr>"""

            # Record count row
            count_cells = "".join(
                f'<td class="tl-cell tl-count">{month_record_counts.get(m, 0)}</td>'
                for m in all_months
            )
            total_records = sum(month_record_counts.values())
            freq_rows += f"""
            <tr class="tl-records-row">
              <td class="tl-cond">Records exported</td>
              {count_cells}
              <td class="tl-total-cell">{total_records}</td>
            </tr>"""

            frequency_table = f"""
            <div class="tl-scroll">
              <table class="tl-table">
                <thead>{freq_header}</thead>
                <tbody>{freq_rows}</tbody>
              </table>
            </div>"""
        else:
            frequency_table = (
                '<p class="empty-note">No temporal data available yet.</p>'
            )

        # ── Build trajectory emergence table ──────────────────────
        traj_rows = ""
        for traj, first_date in sorted(trajectory_first.items(), key=lambda x: x[1]):
            count = trajectory_counts.get(traj, 0)
            traj_rows += (
                f"<tr>"
                f'<td class="emerge-traj">{escape(traj)}</td>'
                f'<td class="emerge-date">{escape(first_date)}</td>'
                f'<td class="emerge-count">{count} record{"s" if count != 1 else ""}</td>'
                f"</tr>"
            )

        if not traj_rows:
            traj_rows = '<tr><td colspan="3" class="empty-note">No trajectory data yet.</td></tr>'

        # ── Build condition emergence table ───────────────────────
        cond_emerge_rows = ""
        for cond, first_date in sorted(condition_first.items(), key=lambda x: x[1]):
            cond_emerge_rows += (
                f"<tr>"
                f'<td class="emerge-traj">{escape(cond)}</td>'
                f'<td class="emerge-date">{escape(first_date)}</td>'
                f"</tr>"
            )

        if not cond_emerge_rows:
            cond_emerge_rows = '<tr><td colspan="2" class="empty-note">No condition data yet.</td></tr>'

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Archive Timeline — Civic Decision Engine</title>
  <link rel="canonical" href="https://civic-decision-engine-production.up.railway.app/stats/timeline">
  <meta name="description" content="Temporal pattern analysis of the Civic Decision Engine archive. Monthly condition frequency, trajectory emergence, and archive growth over time.">
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
      max-width: 960px;
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
    .intro {{ color: #444; margin-bottom: 32px; font-size: 0.95rem; }}
    .tl-scroll {{
      overflow-x: auto;
      margin-bottom: 8px;
    }}
    .tl-table {{
      border-collapse: collapse;
      font-size: 0.78rem;
      min-width: 100%;
    }}
    .tl-table thead tr {{
      border-bottom: 2px solid #1a1a1a;
    }}
    .tl-table th {{
      font-family: ui-monospace, monospace;
      font-size: 0.65rem;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      color: #888;
      padding: 4px 12px 8px 0;
      text-align: left;
      font-weight: normal;
      white-space: nowrap;
    }}
    .tl-month {{
      text-align: center !important;
      min-width: 64px;
    }}
    .tl-total {{
      text-align: right !important;
      padding-right: 0 !important;
    }}
    .tl-table tbody tr {{
      border-bottom: 1px solid #f0ede8;
    }}
    .tl-table tbody tr:last-child {{ border-bottom: none; }}
    .tl-table td {{
      padding: 8px 12px 8px 0;
      vertical-align: middle;
    }}
    .tl-label {{
      width: 200px;
      min-width: 180px;
    }}
    .tl-cond {{
      font-size: 0.82rem;
      color: #1a1a1a;
      white-space: nowrap;
      padding-right: 20px !important;
    }}
    .tl-cell {{
      font-family: ui-monospace, monospace;
      font-size: 0.78rem;
      text-align: center;
      color: #1a1a1a;
      min-width: 64px;
    }}
    .tl-count {{ color: #888; }}
    .tl-total-cell {{
      font-family: ui-monospace, monospace;
      font-size: 0.78rem;
      font-weight: bold;
      text-align: right;
      color: #1a1a1a;
    }}
    .tl-records-row td {{
      font-family: ui-monospace, monospace;
      font-size: 0.72rem;
      color: #aaa;
      border-top: 1px solid #e8e6e0;
      padding-top: 10px;
    }}
    .emerge-table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.875rem;
    }}
    .emerge-table tr {{ border-bottom: 1px solid #f0ede8; }}
    .emerge-table tr:last-child {{ border-bottom: none; }}
    .emerge-table td {{ padding: 10px 12px 10px 0; vertical-align: top; }}
    .emerge-traj {{ color: #1a1a1a; }}
    .emerge-date {{
      font-family: ui-monospace, monospace;
      font-size: 0.78rem;
      color: #888;
      white-space: nowrap;
      width: 120px;
    }}
    .emerge-count {{
      font-family: ui-monospace, monospace;
      font-size: 0.78rem;
      color: #aaa;
      text-align: right;
      width: 120px;
    }}
    .empty-note {{
      font-family: ui-monospace, monospace;
      font-size: 0.82rem;
      color: #aaa;
      font-style: italic;
      margin: 0;
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

  .doc-header {{
    flex-direction: column;
    gap: 12px;
  }}

  .doc-title,
  .doc-subtitle {{
    text-align: left;
  }}

  .doc-footer {{
    flex-direction: column;
    align-items: flex-start;
  }}

  .footer-note {{
    text-align: left;
  }}

  .doc-mark {{
    justify-content: flex-start;
    margin-top: 10px;
  }}

  .doc-mark svg {{
    width: 54px;
  }}

  .doc-header > div:last-child {{
    flex-direction: row;
    align-items: center;
    justify-content: space-between;
    width: 100%;
  }}
}}
   @media print {{
  body {{ background: white; padding: 0; }}
  .document {{ border: none; box-shadow: none; padding: 32px; }}

  .document::before {{
  content: "";
  position: fixed;
  top: 50%;
  left: 50%;
  width: 260px;
  height: 260px;
  transform: translate(-50%, -50%);
  opacity: 0.07;
  pointer-events: none;
  z-index: 0;

  background-image: url("data:image/svg+xml,%3Csvg width='512' height='512' viewBox='0 0 512 512' fill='none' xmlns='http://www.w3.org/2000/svg'%3E%3Cellipse cx='256' cy='256' rx='230' ry='290' stroke='%232E8B9A' stroke-width='28' fill='none'/%3E%3Crect x='148' y='138' width='216' height='18' rx='9' fill='%232E8B9A'/%3E%3Crect x='168' y='170' width='176' height='14' rx='7' fill='%232E8B9A'/%3E%3Crect x='196' y='200' width='8' height='120' rx='4' fill='%232E8B9A'/%3E%3Crect x='220' y='200' width='8' height='120' rx='4' fill='%232E8B9A'/%3E%3Crect x='244' y='200' width='8' height='120' rx='4' fill='%232E8B9A'/%3E%3Crect x='268' y='200' width='8' height='120' rx='4' fill='%232E8B9A'/%3E%3Crect x='292' y='200' width='8' height='120' rx='4' fill='%232E8B9A'/%3E%3Crect x='166' y='320' width='180' height='14' rx='7' fill='%232E8B9A'/%3E%3Ctext x='256' y='388' text-anchor='middle' font-family='sans-serif' font-size='72' font-weight='600' fill='%232E8B9A'%3Ev11%3C/text%3E%3C/svg%3E");

  background-repeat: no-repeat;
  background-position: center;
  background-size: contain;
}}

.document {{
  position: relative;
  z-index: 1;
}}
  :root {{
  --teal: #2E8B9A;
}}

.doc-footer-seal {{
  display: flex;
  justify-content: flex-end;
  align-items: flex-end;
  opacity: 0.42;
  color: var(--teal);
}}

.doc-footer-seal svg {{
  display: block;
}}
.doc-mark {{
  display: flex;
  align-items: flex-start;
  justify-content: flex-end;
  flex-shrink: 0;
  opacity: 0.92;
  color: var(--teal);
}}

.doc-mark svg {{
  display: block;
  width: 42px;
  height: auto;
}}
  </style>
</head>
<body>
  <div class="document">
    <header class="doc-header">
      <div>
        <div class="doc-engine">Civic Decision Engine</div>
        <div class="doc-nav">
          <a href="/stats">← Archive statistics</a>
          <a href="/records">Public record index</a>
          <a href="/patterns">Condition patterns</a>
          <a href="/api/docs">API documentation</a>
        </div>
      </div>
      <div style="display:flex;align-items:flex-start;gap:12px;">
  <div>
      <div class="doc-title">Archive Timeline</div>
      <div class="doc-subtitle">Temporal pattern analysis</div>
    </div>

<div>
        <div class="doc-mark" aria-label="Civic Decision Engine v11" style="text-align:right;margin-bottom:6px;opacity:0.82;">
          <svg width="42" height="52" viewBox="0 0 512 512" fill="none">
            <ellipse cx="256" cy="256" rx="230" ry="290" stroke="#2E8B9A" stroke-width="28" fill="none"/>
            <rect x="148" y="138" width="216" height="18" rx="9" fill="#2E8B9A"/>
            <rect x="168" y="170" width="176" height="14" rx="7" fill="#2E8B9A"/>
            <rect x="196" y="200" width="8" height="120" rx="4" fill="#2E8B9A"/>
            <rect x="220" y="200" width="8" height="120" rx="4" fill="#2E8B9A"/>
            <rect x="244" y="200" width="8" height="120" rx="4" fill="#2E8B9A"/>
            <rect x="268" y="200" width="8" height="120" rx="4" fill="#2E8B9A"/>
            <rect x="292" y="200" width="8" height="120" rx="4" fill="#2E8B9A"/>
            <rect x="166" y="320" width="180" height="14" rx="7" fill="#2E8B9A"/>
            <text x="256" y="388" text-anchor="middle" font-family="sans-serif" font-size="72" font-weight="600" fill="#2E8B9A">v11</text>
          </svg>
        </div>
      </div>
  </div>
    </header>

    <p class="intro">
      A month-by-month view of condition frequency and trajectory emergence
      across the verified public record archive. Each row shows how often
      a condition appeared in records exported during that period.
    </p>

    <div class="section-header">Condition frequency by month</div>
    {frequency_table}

    <div class="section-header">Trajectory emergence</div>
    <table class="emerge-table">
      <tbody>{traj_rows}</tbody>
    </table>

    <div class="section-header">Condition emergence</div>
    <table class="emerge-table">
      <tbody>{cond_emerge_rows}</tbody>
    </table>

    <div class="api-note">
      Source data: <a href="/api/stats">GET /api/stats</a>
      &nbsp;·&nbsp;
      Raw records: <a href="/api/records?full=true">GET /api/records?full=true</a>
    </div>

    <footer class="doc-footer">
  <div class="footer-tagline">The record does not argue.</div>

  <div class="footer-note">
    Timeline reflects exported records only. Dates are export timestamps,
    not case origination dates. Only the latest version of each record
    is counted.
  </div>

  <div class="doc-footer-seal" aria-hidden="true">
    <svg width="28" height="35" viewBox="0 0 512 512" fill="none">
      <ellipse cx="256" cy="256" rx="230" ry="290" stroke="var(--teal, #2E8B9A)" stroke-width="28" fill="none"/>
      <rect x="148" y="138" width="216" height="18" rx="9" fill="var(--teal, #2E8B9A)"/>
      <rect x="168" y="170" width="176" height="14" rx="7" fill="var(--teal, #2E8B9A)"/>
      <rect x="196" y="200" width="8" height="120" rx="4" fill="var(--teal, #2E8B9A)"/>
      <rect x="220" y="200" width="8" height="120" rx="4" fill="var(--teal, #2E8B9A)"/>
      <rect x="244" y="200" width="8" height="120" rx="4" fill="var(--teal, #2E8B9A)"/>
      <rect x="268" y="200" width="8" height="120" rx="4" fill="var(--teal, #2E8B9A)"/>
      <rect x="292" y="200" width="8" height="120" rx="4" fill="var(--teal, #2E8B9A)"/>
      <rect x="166" y="320" width="180" height="14" rx="7" fill="var(--teal, #2E8B9A)"/>
      <text x="256" y="388" text-anchor="middle" font-family="sans-serif" font-size="72" font-weight="600" fill="var(--teal, #2E8B9A)">v11</text>
    </svg>
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


@router.get("/sitemap.xml")
async def sitemap():
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT reference, exported_at FROM records "
            "WHERE is_latest = 1 ORDER BY exported_at DESC"
        )
        records = cur.fetchall()

        base = "https://civic-decision-engine-production.up.railway.app"

        # Static routes
        static_urls = [
            {"loc": f"{base}/records", "priority": "0.9"},
            {"loc": f"{base}/conditions", "priority": "0.8"},
            {"loc": f"{base}/patterns", "priority": "0.8"},
            {"loc": f"{base}/stats", "priority": "0.7"},
            {"loc": f"{base}/stats/timeline", "priority": "0.6"},
            {"loc": f"{base}/graph", "priority": "0.6"},
            {"loc": f"{base}/api/docs", "priority": "0.5"},
        ]

        # Condition pages
        for c in CONDITION_REGISTRY:
            static_urls.append(
                {
                    "loc": f"{base}/conditions/{c['id']}",
                    "priority": "0.8",
                }
            )

        def url_entry(
            loc: str, lastmod: str | None = None, priority: str = "0.6"
        ) -> str:
            lastmod_tag = (
                f"<lastmod>{escape(lastmod[:10])}</lastmod>" if lastmod else ""
            )
            return (
                f"  <url>\n"
                f"    <loc>{escape(loc)}</loc>\n"
                f"    {lastmod_tag}\n"
                f"    <priority>{priority}</priority>\n"
                f"    <changefreq>monthly</changefreq>\n"
                f"  </url>"
            )

        entries = [url_entry(u["loc"], priority=u["priority"]) for u in static_urls]

        for rec in records:
            entries.append(
                url_entry(
                    f"{base}/verify/{rec['reference']}",
                    lastmod=rec["exported_at"],
                    priority="0.7",
                )
            )

        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            + "\n".join(entries)
            + "\n</urlset>"
        )

        from fastapi.responses import Response

        return Response(content=xml, media_type="application/xml")

    finally:
        conn.close()


@router.get("/robots.txt")
async def robots():
    from fastapi.responses import Response

    content = (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /api/\n"
        "\n"
        "Sitemap: https://civic-decision-engine-production.up.railway.app/sitemap.xml\n"
    )
    return Response(content=content, media_type="text/plain")


@router.get("/api/graph")
async def api_graph(
    institution: str = Query(
        default=None, description="Filter by institution type code"
    ),
    trajectory: str = Query(default=None, description="Filter by trajectory"),
):
    conn = get_db()
    try:
        cur = conn.cursor()

        conditions_parts = ["is_latest = 1"]
        params: list = []

        if institution:
            conditions_parts.append("reference LIKE ?")
            params.append(f"Strike-{institution.upper()}-%")
        if trajectory:
            conditions_parts.append("LOWER(trajectory) = LOWER(?)")
            params.append(trajectory)

        where = " AND ".join(conditions_parts)

        cur.execute(
            f"SELECT reference, conditions_json, trajectory, exported_at "
            f"FROM records WHERE {where} ORDER BY exported_at ASC",
            params,
        )
        rows = cur.fetchall()

        # Build nodes — one per condition
        condition_counts: dict[str, int] = {}
        condition_institutions: dict[str, dict[str, int]] = {}
        condition_trajectories: dict[str, dict[str, int]] = {}
        condition_records: dict[str, list[str]] = {}

        # Build edges — co-occurrence pairs
        edge_counts: dict[tuple[str, str], int] = {}

        for row in rows:
            conditions = json.loads(row["conditions_json"] or "[]")
            ref = row["reference"]
            traj = row["trajectory"] or ""
            inst = extract_institution_type(ref)

            for c in conditions:
                condition_counts[c] = condition_counts.get(c, 0) + 1

                if c not in condition_institutions:
                    condition_institutions[c] = {}
                condition_institutions[c][inst] = (
                    condition_institutions[c].get(inst, 0) + 1
                )

                if c not in condition_trajectories:
                    condition_trajectories[c] = {}
                condition_trajectories[c][traj] = (
                    condition_trajectories[c].get(traj, 0) + 1
                )

                if c not in condition_records:
                    condition_records[c] = []
                if ref not in condition_records[c]:
                    condition_records[c].append(ref)

            # Co-occurrence edges
            sorted_conditions = sorted(set(conditions))
            for i in range(len(sorted_conditions)):
                for j in range(i + 1, len(sorted_conditions)):
                    pair = (sorted_conditions[i], sorted_conditions[j])
                    edge_counts[pair] = edge_counts.get(pair, 0) + 1

        nodes = [
            {
                "id": cond,
                "label": cond,
                "count": count,
                "institutions": condition_institutions.get(cond, {}),
                "trajectories": condition_trajectories.get(cond, {}),
                "records": condition_records.get(cond, []),
            }
            for cond, count in sorted(
                condition_counts.items(), key=lambda x: x[1], reverse=True
            )
        ]

        edges = [
            {
                "source": pair[0],
                "target": pair[1],
                "weight": weight,
            }
            for pair, weight in sorted(
                edge_counts.items(), key=lambda x: x[1], reverse=True
            )
        ]

        return JSONResponse(
            content={
                "filters": {
                    "institution": institution,
                    "trajectory": trajectory,
                },
                "node_count": len(nodes),
                "edge_count": len(edges),
                "nodes": nodes,
                "edges": edges,
            }
        )

    finally:
        conn.close()


@router.get("/patterns", response_class=HTMLResponse)
async def patterns_page():
    conn = get_db()
    try:
        cur = conn.cursor()

        cur.execute(
            "SELECT reference, conditions_json, trajectory FROM records WHERE is_latest = 1"
        )
        rows = cur.fetchall()

        condition_counts: dict[str, int] = {}
        condition_institutions: dict[str, dict[str, int]] = {}
        condition_trajectories: dict[str, dict[str, int]] = {}
        edge_counts: dict[tuple[str, str], int] = {}

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

        for row in rows:
            conditions = json.loads(row["conditions_json"] or "[]")
            inst = extract_institution_type(row["reference"])
            traj = row["trajectory"] or ""

            for c in conditions:
                condition_counts[c] = condition_counts.get(c, 0) + 1
                if c not in condition_institutions:
                    condition_institutions[c] = {}
                condition_institutions[c][inst] = (
                    condition_institutions[c].get(inst, 0) + 1
                )
                if c not in condition_trajectories:
                    condition_trajectories[c] = {}
                condition_trajectories[c][traj] = (
                    condition_trajectories[c].get(traj, 0) + 1
                )

            sorted_conditions = sorted(set(conditions))
            for i in range(len(sorted_conditions)):
                for j in range(i + 1, len(sorted_conditions)):
                    pair = (sorted_conditions[i], sorted_conditions[j])
                    edge_counts[pair] = edge_counts.get(pair, 0) + 1

        total_records = len(rows)

        # Build condition cards
        condition_cards = ""
        for cond, count in sorted(
            condition_counts.items(), key=lambda x: x[1], reverse=True
        ):
            pct = round((count / total_records) * 100) if total_records else 0
            inst_breakdown = ", ".join(
                f"{INSTITUTION_LABELS.get(k, k)} ({v})"
                for k, v in sorted(
                    condition_institutions.get(cond, {}).items(),
                    key=lambda x: x[1],
                    reverse=True,
                )
            )
            traj_breakdown = ", ".join(
                f"{k} ({v})"
                for k, v in sorted(
                    condition_trajectories.get(cond, {}).items(),
                    key=lambda x: x[1],
                    reverse=True,
                )
            )
            condition_cards += f"""
            <div class="pattern-card">
              <div class="pattern-header">
                <span class="pattern-name">{escape(cond)}</span>
                <span class="pattern-count">{count} record{"s" if count != 1 else ""}</span>
              </div>
              <div class="pattern-bar-wrap">
                <div class="pattern-bar" style="width:{pct}%"></div>
              </div>
              <div class="pattern-meta">
                <span class="pattern-meta-label">Institutions:</span> {escape(inst_breakdown) if inst_breakdown else "—"}
              </div>
              <div class="pattern-meta">
                <span class="pattern-meta-label">Trajectory:</span> {escape(traj_breakdown) if traj_breakdown else "—"}
              </div>
              <a href="/records?condition={escape(cond)}" class="pattern-link">
                View records →
              </a>
            </div>"""

        # Build co-occurrence rows
        cooccurrence_rows = ""
        for (a, b), weight in sorted(
            edge_counts.items(), key=lambda x: x[1], reverse=True
        ):
            cooccurrence_rows += (
                f"<tr>"
                f'<td class="co-cond">{escape(a)}</td>'
                f'<td class="co-plus">+</td>'
                f'<td class="co-cond">{escape(b)}</td>'
                f'<td class="co-count">{weight}</td>'
                f"</tr>"
            )

        if not cooccurrence_rows:
            cooccurrence_rows = '<tr><td colspan="4" class="empty-state">No co-occurrences recorded yet.</td></tr>'

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Condition Patterns — Civic Decision Engine</title>
  <link rel="canonical" href="https://civic-decision-engine-production.up.railway.app/patterns">
  <meta name="description" content="Structural pattern analysis of civic conditions across verified public records. Shows condition co-occurrence, institutional clustering, and trajectory distribution.">
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
      max-width: 900px;
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
       :root {{
        --teal: #2E8B9A;
        --teal-light: #4AABB8;
        --teal-faint: rgba(46,139,154,0.08);
        --teal-mid: rgba(46,139,154,0.18);
      }}

          .doc-mark {{
        display: flex;
        align-items: flex-start;
        justify-content: flex-end;
        flex-shrink: 0;
        opacity: 0.82;
      }}

      .doc-mark svg {{
        display: block;
        width: 42px;
        height: auto;
      }}

      @media (max-width: 720px) {{
        .doc-mark {{
          align-self: flex-start;
        }}

        .doc-mark svg {{
          width: 34px;
        }}
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
      margin: 40px 0 16px;
      padding-bottom: 6px;
      border-bottom: 1px solid #e8e6e0;
    }}
    .intro {{ color: #444; margin-bottom: 8px; }}
    .graph-link-block {{
      background: #f8f7f4;
      border: 1px solid #e8e6e0;
      border-left: 3px solid #1a1a1a;
      border-radius: 4px;
      padding: 14px 20px;
      margin-bottom: 36px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
    }}
    .graph-link-block p {{
      font-family: ui-monospace, monospace;
      font-size: 0.78rem;
      color: #555;
      margin: 0;
    }}
    .graph-link-block a {{
      font-family: ui-monospace, monospace;
      font-size: 0.78rem;
      color: #1a1a1a;
      text-decoration: none;
      border-bottom: 2px solid #1a1a1a;
      white-space: nowrap;
    }}
    .pattern-grid {{
      display: grid;
      grid-template-columns: repeat(2, 1fr);
      gap: 16px;
      margin-bottom: 8px;
    }}
    .pattern-card {{
      background: #f8f7f4;
      border: 1px solid #e8e6e0;
      border-radius: 4px;
      padding: 16px 18px;
    }}
    .pattern-header {{
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      margin-bottom: 8px;
      gap: 8px;
    }}
    .pattern-name {{
      font-size: 0.9rem;
      font-weight: bold;
      color: #1a1a1a;
      font-family: Georgia, serif;
    }}
    .pattern-count {{
      font-family: ui-monospace, monospace;
      font-size: 0.7rem;
      color: #888;
      white-space: nowrap;
    }}
    .pattern-bar-wrap {{
      background: #e8e6e0;
      border-radius: 2px;
      height: 4px;
      margin-bottom: 10px;
    }}
    .pattern-bar {{
      background: #1a1a1a;
      height: 4px;
      border-radius: 2px;
      min-width: 2px;
    }}
    .pattern-meta {{
      font-size: 0.75rem;
      color: #666;
      margin-bottom: 4px;
      line-height: 1.5;
    }}
    .pattern-meta-label {{
      font-family: ui-monospace, monospace;
      font-size: 0.65rem;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      color: #aaa;
    }}
    .pattern-link {{
      display: inline-block;
      margin-top: 10px;
      font-family: ui-monospace, monospace;
      font-size: 0.68rem;
      color: #888;
      text-decoration: none;
      border-bottom: 1px solid #ddd;
    }}
    .pattern-link:hover {{ color: #1a1a1a; border-color: #999; }}
    .co-table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.875rem;
    }}
    .co-table tr {{ border-bottom: 1px solid #f0ede8; }}
    .co-table tr:last-child {{ border-bottom: none; }}
    .co-table td {{ padding: 10px 8px 10px 0; vertical-align: middle; }}
    .co-cond {{ color: #1a1a1a; }}
    .co-plus {{
      font-family: ui-monospace, monospace;
      color: #ccc;
      width: 24px;
      text-align: center;
    }}
    .co-count {{
      font-family: ui-monospace, monospace;
      font-size: 0.78rem;
      color: #888;
      text-align: right;
      width: 80px;
    }}
    .empty-state {{
      color: #aaa;
      font-style: italic;
      font-family: ui-monospace, monospace;
      font-size: 0.82rem;
      padding: 20px 0;
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
      .pattern-grid {{ grid-template-columns: 1fr; }}
      .graph-link-block {{ flex-direction: column; align-items: flex-start; }}
      .doc-footer {{ flex-direction: column; align-items: flex-start; }}
      .footer-note {{ text-align: left; }}
    }}
    .footer-seal {{
      display: flex;
      justify-content: flex-end;
      align-items: flex-end;
      opacity: 0.42;
      color: var(--teal);
    }}
    .footer-seal svg {{ display: block; }}
    @media print {{
      body {{ background: white; padding: 0; }}
      .document {{ border: none; box-shadow: none; padding: 32px; }}
      .document::before {{
        content: '';
        position: fixed;
        top: 50%; left: 50%;
        transform: translate(-50%, -50%);
        width: 220px; height: 280px;
        background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 512 512' fill='none'%3E%3Cellipse cx='256' cy='256' rx='230' ry='290' stroke='%232E8B9A' stroke-width='28' fill='none'/%3E%3Crect x='148' y='138' width='216' height='18' rx='9' fill='%232E8B9A'/%3E%3Crect x='168' y='170' width='176' height='14' rx='7' fill='%232E8B9A'/%3E%3Crect x='196' y='200' width='8' height='120' rx='4' fill='%232E8B9A'/%3E%3Crect x='220' y='200' width='8' height='120' rx='4' fill='%232E8B9A'/%3E%3Crect x='244' y='200' width='8' height='120' rx='4' fill='%232E8B9A'/%3E%3Crect x='268' y='200' width='8' height='120' rx='4' fill='%232E8B9A'/%3E%3Crect x='292' y='200' width='8' height='120' rx='4' fill='%232E8B9A'/%3E%3Crect x='166' y='320' width='180' height='14' rx='7' fill='%232E8B9A'/%3E%3Ctext x='256' y='388' text-anchor='middle' font-family='sans-serif' font-size='72' font-weight='600' fill='%232E8B9A'%3Ev11%3C/text%3E%3C/svg%3E");
        background-repeat: no-repeat;
        background-size: contain;
        opacity: 0.07;
        pointer-events: none;
        z-index: 0;
      }}
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
          <a href="/stats">Archive statistics</a>
          <a href="/api/docs">API documentation</a>
        </div>
      </div>
      <div>
        <div class="doc-title">Condition Patterns</div>
        <div class="doc-subtitle">Structural pattern analysis</div>
      </div>
      <div class="doc-mark" aria-label="Civic Decision Engine v11">
          <svg width="42" height="52" viewBox="0 0 512 512" fill="none">
            <ellipse cx="256" cy="256" rx="230" ry="290" stroke="var(--teal)" stroke-width="28" fill="none"/>
            <rect x="148" y="138" width="216" height="18" rx="9" fill="var(--teal)"/>
            <rect x="168" y="170" width="176" height="14" rx="7" fill="var(--teal)"/>
            <rect x="196" y="200" width="8" height="120" rx="4" fill="var(--teal)"/>
            <rect x="220" y="200" width="8" height="120" rx="4" fill="var(--teal)"/>
            <rect x="244" y="200" width="8" height="120" rx="4" fill="var(--teal)"/>
            <rect x="268" y="200" width="8" height="120" rx="4" fill="var(--teal)"/>
            <rect x="292" y="200" width="8" height="120" rx="4" fill="var(--teal)"/>
            <rect x="166" y="320" width="180" height="14" rx="7" fill="var(--teal)"/>
            <text x="256" y="388" text-anchor="middle" font-family="sans-serif" font-size="72" font-weight="600" fill="var(--teal)">v11</text>
          </svg>
        </div>

    </header>

    <p class="intro">
      Conditions are not isolated observations — they recur across institutions,
      trajectories, and time. This page shows how conditions cluster, co-occur,
      and distribute across the verified public record archive.
    </p>

    <div class="graph-link-block">
      <p>For interactive exploration — nodes, edges, filters, and drill-through to individual records:</p>
      <a href="/graph">Open interactive graph →</a>
    </div>

    <div class="section-header">Condition distribution — {total_records} records</div>
    <div class="pattern-grid">{condition_cards}</div>

    <div class="section-header">Condition co-occurrence</div>
    <table class="co-table">
      <tbody>{cooccurrence_rows}</tbody>
    </table>

    <div class="api-note">
      Machine-readable access: <a href="/api/graph">GET /api/graph</a>
      &nbsp;·&nbsp; Returns nodes, edges, and weights as JSON.
      Supports <code>?institution=LA</code> and <code>?trajectory=Deteriorating</code> filters.
    </div>

    <footer class="doc-footer">
      <div class="footer-tagline">The record does not argue.</div>
      <div class="footer-note">
        Patterns are derived from verified public records only.
        Each record is independently verifiable via its reference URL.
      </div>
      <div class="footer-seal" aria-label="Civic Decision Engine v11">
        <svg width="28" height="35" viewBox="0 0 512 512" fill="none">
          <ellipse cx="256" cy="256" rx="230" ry="290" stroke="var(--teal)" stroke-width="28" fill="none"/>
          <rect x="148" y="138" width="216" height="18" rx="9" fill="var(--teal)"/>
          <rect x="168" y="170" width="176" height="14" rx="7" fill="var(--teal)"/>
          <rect x="196" y="200" width="8" height="120" rx="4" fill="var(--teal)"/>
          <rect x="220" y="200" width="8" height="120" rx="4" fill="var(--teal)"/>
          <rect x="244" y="200" width="8" height="120" rx="4" fill="var(--teal)"/>
          <rect x="268" y="200" width="8" height="120" rx="4" fill="var(--teal)"/>
          <rect x="292" y="200" width="8" height="120" rx="4" fill="var(--teal)"/>
          <rect x="166" y="320" width="180" height="14" rx="7" fill="var(--teal)"/>
          <text x="256" y="388" text-anchor="middle" font-family="sans-serif" font-size="72" font-weight="600" fill="var(--teal)">v11</text>
        </svg>
      </div>
    </footer>
  </div>
</body>
</html>"""

        return HTMLResponse(content=html, status_code=200)

    finally:
        conn.close()


@router.get("/graph", response_class=HTMLResponse)
async def graph_page():
    html = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Condition Graph — Civic Decision Engine</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; }
    body {
      font-family: Georgia, 'Times New Roman', serif;
      background: #f4f4f0;
      color: #1a1a1a;
      margin: 0;
      padding: 0;
    }
    #app {
      display: grid;
      grid-template-rows: auto 1fr;
      height: 100vh;
    }
    .graph-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 16px;
      }

      .graph-header-left {
        flex-shrink: 0;
      }

      .graph-controls {
        display: flex;
        align-items: center;
        gap: 8px;
        margin-left: auto;
      }

      .doc-mark {
        display: flex;
        align-items: center;
        justify-content: center;
        flex-shrink: 0;
        color: var(--teal);
        opacity: 0.92;
        margin-left: 12px;
      }

      .doc-mark svg {
        display: block;
        width: 34px;
        height: auto;
      }

        @media (max-width: 720px) {{
          .doc-mark {{
            align-self: flex-start;
          }}

          .doc-mark svg {{
            width: 34px;
          }}
        }}

    .graph-engine {
      font-family: ui-monospace, monospace;
      font-size: 0.68rem;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: #888;
    }
    .graph-title {
      font-family: ui-monospace, monospace;
      font-size: 0.72rem;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: #1a1a1a;
      font-weight: bold;
    }
    .graph-controls {
      display: flex;
      gap: 8px;
      align-items: center;
      flex-wrap: wrap;
    }
    .graph-controls select {
      font-family: ui-monospace, monospace;
      font-size: 0.72rem;
      background: #f8f7f4;
      border: 1px solid #d0cec8;
      border-radius: 4px;
      padding: 5px 10px;
      color: #1a1a1a;
      cursor: pointer;
    }
    .graph-controls select:focus { outline: none; border-color: #1a1a1a; }
    .back-link {
      font-family: ui-monospace, monospace;
      font-size: 0.68rem;
      color: #888;
      text-decoration: none;
      border-bottom: 1px solid #ddd;
    }
    .back-link:hover { color: #1a1a1a; }
    #graph-container {
      position: relative;
      overflow: hidden;
      background: #faf9f7;
    }
    canvas {
      display: block;
      width: 100%;
      height: 100%;
    }
    #tooltip {
      position: absolute;
      background: #1a1a1a;
      color: #fff;
      font-family: ui-monospace, monospace;
      font-size: 0.72rem;
      padding: 10px 14px;
      border-radius: 4px;
      pointer-events: none;
      opacity: 0;
      transition: opacity 0.15s;
      max-width: 280px;
      line-height: 1.6;
      z-index: 10;
    }
    #panel {
      position: absolute;
      right: 20px;
      top: 20px;
      background: #ffffff;
      border: 1px solid #d0cec8;
      border-top: 3px solid #1a1a1a;
      border-radius: 4px;
      padding: 16px 18px;
      width: 260px;
      font-size: 0.82rem;
      display: none;
      box-shadow: 0 2px 12px rgba(0,0,0,0.1);
    }
    #panel h3 {
      font-size: 0.9rem;
      margin: 0 0 8px;
      font-family: Georgia, serif;
    }
    #panel .panel-meta {
      font-family: ui-monospace, monospace;
      font-size: 0.68rem;
      color: #888;
      margin-bottom: 12px;
    }
    #panel .panel-records {
      display: flex;
      flex-direction: column;
      gap: 4px;
    }
    #panel .panel-records a {
      font-family: ui-monospace, monospace;
      font-size: 0.68rem;
      color: #1a1a1a;
      text-decoration: none;
      border-bottom: 1px solid #ddd;
      width: fit-content;
    }
    #panel .panel-records a:hover { border-color: #1a1a1a; }
    #panel-close {
      position: absolute;
      top: 8px;
      right: 10px;
      background: none;
      border: none;
      cursor: pointer;
      color: #888;
      font-size: 1rem;
    }
    #status {
      position: absolute;
      bottom: 16px;
      left: 20px;
      font-family: ui-monospace, monospace;
      font-size: 0.68rem;
      color: #aaa;
    }
    :root {
      --teal: #2E8B9A;
    }

    .graph-seal {
      position: fixed;
      right: 18px;
      bottom: 18px;
      opacity: 0.18;
      pointer-events: none;
      color: var(--teal);
      z-index: 9999;
    }

    .graph-seal svg {
      display: block;
      width: 56px;
      height: auto;
    }
  </style>
</head>
<body>
  <div id="app">
    <div class="graph-header">
      <div class="graph-header-left">
        <span class="graph-engine">Civic Decision Engine</span>
        <span class="graph-title">Condition Graph</span>
      </div>
      <div class="graph-controls">
        <select id="filterInstitution">
          <option value="">All institutions</option>
          <option value="LA">Local Authority</option>
          <option value="HS">Health Service</option>
          <option value="ED">Education</option>
          <option value="HO">Housing</option>
          <option value="PL">Planning</option>
          <option value="GV">Government</option>
          <option value="FS">Fire Service</option>
          <option value="LE">Law Enforcement</option>
          <option value="LG">Legal</option>
          <option value="OT">Other</option>
        </select>
        <select id="filterTrajectory">
          <option value="">All trajectories</option>
          <option value="Deteriorating">Deteriorating</option>
          <option value="Stable">Stable</option>
          <option value="Improving">Improving</option>
        </select>
        <a href="/patterns" class="back-link">← Pattern summary</a>
      </div>
   </div>

    <div id="graph-container">
      <canvas id="canvas"></canvas>
      <div id="tooltip"></div>
      <div id="panel">
        <button id="panel-close">✕</button>
        <h3 id="panel-name"></h3>
        <div class="panel-meta" id="panel-meta"></div>
        <div class="panel-records" id="panel-records"></div>
      </div>
      <div id="status">Loading graph data...</div>
    </div>
  </div>

  <script>
    const canvas = document.getElementById("canvas");
    const ctx = canvas.getContext("2d");
    const tooltip = document.getElementById("tooltip");
    const panel = document.getElementById("panel");
    const status = document.getElementById("status");

    let nodes = [], edges = [], animFrame;
    let transform = { x: 0, y: 0, scale: 1 };
    let dragging = false, dragStart = null, lastTransform = null;
    let hoveredNode = null;

    const COLORS = [
      "#1a1a1a", "#4a4a8a", "#8a4a4a", "#4a8a4a",
      "#8a7a2a", "#2a6a8a", "#7a2a6a", "#2a8a6a"
    ];

    function resize() {
      const container = document.getElementById("graph-container");
      canvas.width  = container.clientWidth  * devicePixelRatio;
      canvas.height = container.clientHeight * devicePixelRatio;
      canvas.style.width  = container.clientWidth  + "px";
      canvas.style.height = container.clientHeight + "px";
      ctx.scale(devicePixelRatio, devicePixelRatio);
      draw();
    }

    function layoutNodes(nodeList, w, h) {
      const cx = w / 2, cy = h / 2;
      if (nodeList.length === 1) {
        nodeList[0].x = cx;
        nodeList[0].y = cy;
        return;
      }
      nodeList.forEach((n, i) => {
        const angle = (i / nodeList.length) * Math.PI * 2 - Math.PI / 2;
        const r = Math.min(w, h) * 0.38;
        n.x = cx + Math.cos(angle) * r;
        n.y = cy + Math.sin(angle) * r;
        n.vx = 0;
        n.vy = 0;
      });
    }

    function simulate() {
      const k = 180;
      const gravity = 0.008;
      const w = canvas.width / devicePixelRatio;
      const h = canvas.height / devicePixelRatio;

      nodes.forEach(n => {
        // Gravity toward center
        n.vx += (w / 2 - n.x) * gravity;
        n.vy += (h / 2 - n.y) * gravity;

        // Repulsion
        nodes.forEach(m => {
          if (m === n) return;
          const dx = n.x - m.x, dy = n.y - m.y;
          const dist = Math.sqrt(dx * dx + dy * dy) || 1;
          const force = (k * k) / dist;
          n.vx += (dx / dist) * force * 0.01;
          n.vy += (dy / dist) * force * 0.01;
        });
      });

      // Attraction along edges
      edges.forEach(e => {
        const s = nodes.find(n => n.id === e.source);
        const t = nodes.find(n => n.id === e.target);
        if (!s || !t) return;
        const dx = t.x - s.x, dy = t.y - s.y;
        const dist = Math.sqrt(dx * dx + dy * dy) || 1;
        const force = (dist * dist) / (k * 3);
        const fx = (dx / dist) * force * 0.01;
        const fy = (dy / dist) * force * 0.01;
        s.vx += fx; s.vy += fy;
        t.vx -= fx; t.vy -= fy;
      });

      nodes.forEach(n => {
        n.vx *= 0.85;
        n.vy *= 0.85;
        n.x += n.vx;
        n.y += n.vy;
      });
    }

    let simSteps = 0;
    function tick() {
      if (simSteps < 220) { simulate(); simSteps++; }
      draw();
      animFrame = requestAnimationFrame(tick);
    }

    function draw() {
      const w = canvas.width / devicePixelRatio;
      const h = canvas.height / devicePixelRatio;
      ctx.save();
      ctx.clearRect(0, 0, w, h);
      ctx.translate(transform.x, transform.y);
      ctx.scale(transform.scale, transform.scale);

      const maxWeight = Math.max(...edges.map(e => e.weight), 1);

      // Draw edges
      edges.forEach(e => {
        const s = nodes.find(n => n.id === e.source);
        const t = nodes.find(n => n.id === e.target);
        if (!s || !t) return;
        const alpha = 0.15 + (e.weight / maxWeight) * 0.5;
        ctx.beginPath();
        ctx.strokeStyle = `rgba(26,26,26,${alpha})`;
        ctx.lineWidth = 1 + (e.weight / maxWeight) * 3;
        ctx.moveTo(s.x, s.y);
        ctx.lineTo(t.x, t.y);
        ctx.stroke();
      });

      // Draw nodes
      const maxCount = Math.max(...nodes.map(n => n.count), 1);
      nodes.forEach((n, i) => {
        const r = 38 + (n.count / maxCount) * 36;
        n._r = r;
        const isHovered = n === hoveredNode;
        ctx.beginPath();
        ctx.arc(n.x, n.y, r, 0, Math.PI * 2);
        ctx.fillStyle = isHovered ? "#1a1a1a" : (COLORS[i % COLORS.length] + "cc");
        ctx.fill();
        if (isHovered) {
          ctx.strokeStyle = "#1a1a1a";
          ctx.lineWidth = 2;
          ctx.stroke();
        }
        ctx.fillStyle = "#ffffff";
        const fontSize = Math.max(11, Math.min(18, r * 0.18));
        const lineHeight = fontSize * 0.9;
        ctx.font = `bold ${fontSize}px ui-monospace, monospace`;
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        const words = n.label.split(" ");
        if (words.length > 1 && r > 20) {
          const mid = Math.ceil(words.length / 2);
          ctx.fillText(words.slice(0, mid).join(" "), n.x, n.y - lineHeight / 2);
          ctx.fillText(words.slice(mid).join(" "), n.x, n.y + lineHeight / 2);
        } else {
          ctx.fillText(n.label.length > 24 ? n.label.slice(0, 13) + "…" : n.label, n.x, n.y);
        }
      });

      ctx.restore();
    }

    function getMouseNode(mx, my) {
      const wx = (mx - transform.x) / transform.scale;
      const wy = (my - transform.y) / transform.scale;
      return nodes.find(n => {
        const dx = wx - n.x, dy = wy - n.y;
        return Math.sqrt(dx * dx + dy * dy) < (n._r || 20);
      });
    }

    canvas.addEventListener("mousemove", e => {
      const rect = canvas.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;

      if (dragging && dragStart) {
        transform.x = lastTransform.x + (e.clientX - dragStart.x);
        transform.y = lastTransform.y + (e.clientY - dragStart.y);
        draw();
        return;
      }

      const node = getMouseNode(mx, my);
      hoveredNode = node || null;
      canvas.style.cursor = node ? "pointer" : "grab";

      if (node) {
        const insts = Object.entries(node.institutions || {})
          .sort((a, b) => b[1] - a[1])
          .map(([k, v]) => `${k}: ${v}`)
          .join(", ");
        tooltip.innerHTML = `<strong>${node.label}</strong><br>${node.count} record${node.count !== 1 ? "s" : ""}<br>${insts || ""}`;
        tooltip.style.opacity = "1";
        tooltip.style.left = (mx + 14) + "px";
        tooltip.style.top  = (my - 10) + "px";
      } else {
        tooltip.style.opacity = "0";
      }
      draw();
    });

    canvas.addEventListener("mousedown", e => {
      dragging = true;
      dragStart = { x: e.clientX, y: e.clientY };
      lastTransform = { ...transform };
      canvas.style.cursor = "grabbing";
    });

    window.addEventListener("mouseup", () => {
      dragging = false;
      canvas.style.cursor = "grab";
    });

    canvas.addEventListener("click", e => {
      const rect = canvas.getBoundingClientRect();
      const node = getMouseNode(e.clientX - rect.left, e.clientY - rect.top);
      if (!node) { panel.style.display = "none"; return; }

      document.getElementById("panel-name").textContent = node.label;
      const insts = Object.entries(node.institutions || {})
        .sort((a, b) => b[1] - a[1])
        .map(([k, v]) => `${k} (${v})`)
        .join(" · ");
      const trajs = Object.entries(node.trajectories || {})
        .sort((a, b) => b[1] - a[1])
        .map(([k, v]) => `${k} (${v})`)
        .join(" · ");
      document.getElementById("panel-meta").innerHTML =
        `${node.count} record${node.count !== 1 ? "s" : ""}<br>${insts}<br>${trajs}`;
      const recordsEl = document.getElementById("panel-records");
      recordsEl.innerHTML = (node.records || []).map(ref =>
        `<a href="/verify/${encodeURIComponent(ref)}" target="_blank">${ref}</a>`
      ).join("");
      panel.style.display = "block";
    });

    canvas.addEventListener("wheel", e => {
      e.preventDefault();
      const factor = e.deltaY < 0 ? 1.1 : 0.9;
      const rect = canvas.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;
      transform.x = mx - (mx - transform.x) * factor;
      transform.y = my - (my - transform.y) * factor;
      transform.scale *= factor;
      draw();
    }, { passive: false });

    document.getElementById("panel-close").addEventListener("click", () => {
      panel.style.display = "none";
    });

    async function loadGraph() {
      const inst = document.getElementById("filterInstitution").value;
      const traj = document.getElementById("filterTrajectory").value;
      let url = "/api/graph";
      const params = [];
      if (inst) params.push(`institution=${encodeURIComponent(inst)}`);
      if (traj) params.push(`trajectory=${encodeURIComponent(traj)}`);
      if (params.length) url += "?" + params.join("&");

      status.textContent = "Loading graph data...";
      try {
        const res  = await fetch(url);
        const data = await res.json();
        nodes = data.nodes.map(n => ({ ...n, x: 0, y: 0, vx: 0, vy: 0 }));
        edges = data.edges;

        const w = canvas.width  / devicePixelRatio;
        const h = canvas.height / devicePixelRatio;
        layoutNodes(nodes, w, h);
        transform = { x: 0, y: 0, scale: 1 };
        simSteps = 0;
        panel.style.display = "none";
        status.textContent = `${data.node_count} condition${data.node_count !== 1 ? "s" : ""} · ${data.edge_count} connection${data.edge_count !== 1 ? "s" : ""}`;
      } catch(err) {
        status.textContent = "Failed to load graph data.";
        console.error(err);
      }
    }

    document.getElementById("filterInstitution").addEventListener("change", loadGraph);
    document.getElementById("filterTrajectory").addEventListener("change", loadGraph);

    window.addEventListener("resize", resize);
    resize();
    loadGraph().then(() => { cancelAnimationFrame(animFrame); tick(); });
  </script>
  <div class="graph-seal" aria-label="Civic Decision Engine v11">
      <svg width="42" height="52" viewBox="0 0 512 512" fill="none">
        <ellipse cx="256" cy="256" rx="230" ry="290" stroke="var(--teal)" stroke-width="28" fill="none"/>
        <rect x="148" y="138" width="216" height="18" rx="9" fill="var(--teal)"/>
        <rect x="168" y="170" width="176" height="14" rx="7" fill="var(--teal)"/>
        <rect x="196" y="200" width="8" height="120" rx="4" fill="var(--teal)"/>
        <rect x="220" y="200" width="8" height="120" rx="4" fill="var(--teal)"/>
        <rect x="244" y="200" width="8" height="120" rx="4" fill="var(--teal)"/>
        <rect x="268" y="200" width="8" height="120" rx="4" fill="var(--teal)"/>
        <rect x="292" y="200" width="8" height="120" rx="4" fill="var(--teal)"/>
        <rect x="166" y="320" width="180" height="14" rx="7" fill="var(--teal)"/>
        <text x="256" y="388" text-anchor="middle" font-family="sans-serif" font-size="72" font-weight="600" fill="var(--teal)">v11</text>
      </svg>
    </div>
</body>
</html>"""
    return HTMLResponse(content=html, status_code=200)


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
            "fr": {
                "page_title": "Vérification du dossier public",
                "engine": "Civic Decision Engine",
                "record_label": "DOSSIER PUBLIC VÉRIFIÉ",
                "section_finding": "Conclusion",
                "section_record": "Détails du dossier",
                "section_integrity": "Intégrité du dossier",
                "section_history": "Historique des versions",
                "field_reference": "Référence",
                "field_date": "Date",
                "field_trajectory": "Trajectoire",
                "field_conditions": "Conditions",
                "field_state": "État du système",
                "field_generated": "Généré par",
                "field_exported": "Exporté",
                "field_hash": "Hachage d'intégrité SHA-256",
                "field_version": "Version du dossier",
                "integrity_note": (
                    "Ce hachage a été calculé au moment de l'exportation à partir des "
                    "champs canoniques de ce dossier. Il peut être utilisé pour vérifier "
                    "que le contenu de ce dossier n'a pas été modifié depuis sa publication."
                ),
                "version_label": "Version",
                "current_badge": "Actuelle",
                "footer_tagline": "Le dossier ne plaide pas.",
                "footer_note": (
                    "Ce dossier a été généré par le Civic Decision Engine et conservé "
                    "au moment de l'exportation. Il constitue un document probatoire "
                    "structuré destiné aux procédures civiles, administratives ou "
                    "de plainte formelle."
                ),
            },
            "de": {
                "page_title": "Öffentliche Akte — Verifizierung",
                "engine": "Civic Decision Engine",
                "record_label": "VERIFIZIERTE ÖFFENTLICHE AKTE",
                "section_finding": "Befund",
                "section_record": "Aktendetails",
                "section_integrity": "Aktenintegrität",
                "section_history": "Versionsgeschichte",
                "field_reference": "Referenz",
                "field_date": "Datum",
                "field_trajectory": "Verlauf",
                "field_conditions": "Bedingungen",
                "field_state": "Systemzustand",
                "field_generated": "Erstellt von",
                "field_exported": "Exportiert",
                "field_hash": "SHA-256-Integritäts-Hash",
                "field_version": "Aktenversion",
                "integrity_note": (
                    "Dieser Hash wurde zum Zeitpunkt des Exports aus den kanonischen "
                    "Feldern dieser Akte berechnet. Er kann verwendet werden, um zu "
                    "überprüfen, dass der Inhalt dieser Akte seit der Veröffentlichung "
                    "nicht verändert wurde."
                ),
                "version_label": "Version",
                "current_badge": "Aktuell",
                "footer_tagline": "Die Akte argumentiert nicht.",
                "footer_note": (
                    "Diese Akte wurde vom Civic Decision Engine erstellt und zum "
                    "Zeitpunkt des Exports gespeichert. Sie stellt ein strukturiertes "
                    "Beweisdokument für den Einsatz in zivilrechtlichen, "
                    "verwaltungsrechtlichen oder formellen Beschwerdeverfahren dar."
                ),
            },
            "es": {
                "page_title": "Verificación del expediente público",
                "engine": "Civic Decision Engine",
                "record_label": "EXPEDIENTE PÚBLICO VERIFICADO",
                "section_finding": "Conclusión",
                "section_record": "Detalles del expediente",
                "section_integrity": "Integridad del expediente",
                "section_history": "Historial de versiones",
                "field_reference": "Referencia",
                "field_date": "Fecha",
                "field_trajectory": "Trayectoria",
                "field_conditions": "Condiciones",
                "field_state": "Estado del sistema",
                "field_generated": "Generado por",
                "field_exported": "Exportado",
                "field_hash": "Hash de integridad SHA-256",
                "field_version": "Versión del expediente",
                "integrity_note": (
                    "Este hash fue calculado en el momento de la exportación a partir "
                    "de los campos canónicos de este expediente. Puede utilizarse para "
                    "verificar que el contenido de este expediente no ha sido alterado "
                    "desde su publicación."
                ),
                "version_label": "Versión",
                "current_badge": "Actual",
                "footer_tagline": "El expediente no argumenta.",
                "footer_note": (
                    "Este expediente fue generado por el Civic Decision Engine y "
                    "almacenado en el momento de la exportación. Constituye un documento "
                    "probatorio estructurado para su uso en procedimientos cívicos, "
                    "administrativos o de reclamación formal."
                ),
            },
            "pl": {
                "page_title": "Weryfikacja dokumentu publicznego",
                "engine": "Civic Decision Engine",
                "record_label": "ZWERYFIKOWANY DOKUMENT PUBLICZNY",
                "section_finding": "Ustalenia",
                "section_record": "Szczegóły dokumentu",
                "section_integrity": "Integralność dokumentu",
                "section_history": "Historia wersji",
                "field_reference": "Numer referencyjny",
                "field_date": "Data",
                "field_trajectory": "Trajektoria",
                "field_conditions": "Warunki",
                "field_state": "Stan systemu",
                "field_generated": "Wygenerowano przez",
                "field_exported": "Wyeksportowano",
                "field_hash": "Skrót integralności SHA-256",
                "field_version": "Wersja dokumentu",
                "integrity_note": (
                    "Ten skrót został obliczony w momencie eksportu na podstawie "
                    "kanonicznych pól tego dokumentu. Można go użyć do weryfikacji, "
                    "że zawartość tego dokumentu nie została zmieniona od czasu "
                    "jego publikacji."
                ),
                "version_label": "Wersja",
                "current_badge": "Aktualna",
                "footer_tagline": "Dokument nie argumentuje.",
                "footer_note": (
                    "Ten dokument został wygenerowany przez Civic Decision Engine "
                    "i zapisany w momencie eksportu. Stanowi ustrukturyzowany dokument "
                    "dowodowy przeznaczony do użytku w postępowaniach obywatelskich, "
                    "administracyjnych lub formalnych skargach."
                ),
            },
            "uk": {
                "page_title": "Верифікація публічного запису",
                "engine": "Civic Decision Engine",
                "record_label": "ВЕРИФІКОВАНИЙ ПУБЛІЧНИЙ ЗАПИС",
                "section_finding": "Висновок",
                "section_record": "Деталі запису",
                "section_integrity": "Цілісність запису",
                "section_history": "Історія версій",
                "field_reference": "Референс",
                "field_date": "Дата",
                "field_trajectory": "Траєкторія",
                "field_conditions": "Умови",
                "field_state": "Стан системи",
                "field_generated": "Створено",
                "field_exported": "Експортовано",
                "field_hash": "Хеш цілісності SHA-256",
                "field_version": "Версія запису",
                "integrity_note": (
                    "Цей хеш був обчислений під час експорту з канонічних полів "
                    "цього запису. Його можна використати для перевірки того, що "
                    "вміст цього запису не був змінений з моменту публікації."
                ),
                "version_label": "Версія",
                "current_badge": "Поточна",
                "footer_tagline": "Запис не сперечається.",
                "footer_note": (
                    "Цей запис був створений Civic Decision Engine та збережений "
                    "під час експорту. Він є структурованим доказовим документом "
                    "для використання в громадських, адміністративних або формальних "
                    "скаргових провадженнях."
                ),
            },
            "ro": {
                "page_title": "Verificarea înregistrării publice",
                "engine": "Civic Decision Engine",
                "record_label": "ÎNREGISTRARE PUBLICĂ VERIFICATĂ",
                "section_finding": "Constatare",
                "section_record": "Detaliile înregistrării",
                "section_integrity": "Integritatea înregistrării",
                "section_history": "Istoricul versiunilor",
                "field_reference": "Referință",
                "field_date": "Dată",
                "field_trajectory": "Traiectorie",
                "field_conditions": "Condiții",
                "field_state": "Starea sistemului",
                "field_generated": "Generat de",
                "field_exported": "Exportat",
                "field_hash": "Hash de integritate SHA-256",
                "field_version": "Versiunea înregistrării",
                "integrity_note": (
                    "Acest hash a fost calculat la momentul exportului din câmpurile "
                    "canonice ale acestei înregistrări. Poate fi utilizat pentru a "
                    "verifica că conținutul acestei înregistrări nu a fost modificat "
                    "de la publicare."
                ),
                "version_label": "Versiune",
                "current_badge": "Curentă",
                "footer_tagline": "Înregistrarea nu argumentează.",
                "footer_note": (
                    "Această înregistrare a fost generată de Civic Decision Engine "
                    "și stocată la momentul exportului. Constituie un document "
                    "probatoriu structurat pentru utilizare în proceduri civice, "
                    "administrative sau de reclamație formală."
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

        # ── Citation data ─────────────────────────────────────────
        verify_url = f"https://civic-decision-engine-production.up.railway.app/verify/{record['reference']}"
        export_year = (record["exported_at"] or "")[:4] or "2026"
        ref_id = record["reference"].replace("-", "")

        apa = (
            f"Civic Decision Engine. ({export_year}). "
            f"{record['reference']}. "
            f"Verified civic record. {verify_url}"
        )

        mla = (
            f'Civic Decision Engine. "{record["reference"]}." '
            f"Verified Civic Record, {export_year}, {verify_url}"
        )

        bibtex = (
            f"@misc{{{ref_id},\n"
            f"  title  = {{{{{record['reference']}}}}},\n"
            f"  author = {{{{Civic Decision Engine}}}},\n"
            f"  year   = {{{export_year}}},\n"
            f"  url    = {{{verify_url}}},\n"
            f"  note   = {{Verified civic record. "
            f"SHA-256: {record['verification_hash']}}}\n"
            f"}}"
        )

        csl_json = json.dumps(
            {
                "type": "webpage",
                "title": record["reference"],
                "author": [{"literal": "Civic Decision Engine"}],
                "issued": {"date-parts": [[int(export_year)]]},
                "URL": verify_url,
                "note": f"Verified civic record. SHA-256: {record['verification_hash']}",
            },
            indent=2,
        )

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
        # ── Source narrative section ──────────────────────────────
        source_narrative = record["source_narrative"] or ""
        if source_narrative:
            narrative_section = f"""
    <section class="section">
      <h2 class="section-title">Source Narrative</h2>

      <button class="narrative-toggle" onclick="toggleNarrative()">
        Expand source narrative &darr;
      </button>

      <div id="narrative-body" class="narrative-body">{escape(source_narrative)}</div>
      <p class="narrative-note">
        Source narrative is the submitted account as entered at the time of record generation.
        It is preserved for evidentiary continuity and is not part of the canonical record hash.
      </p>
    </section>"""
        else:
            narrative_section = ""

        json_ld = json.dumps(
            {
                "@context": "https://schema.org",
                "@type": "GovernmentDocument",
                "name": record["reference"],
                "identifier": record["reference"],
                "description": (record["finding"] or "")[:200],
                "datePublished": (record["exported_at"] or "")[:10],
                "dateModified": (record["exported_at"] or "")[:10],
                "version": str(record["version"]),
                "url": verify_url,
                "author": {
                    "@type": "Organization",
                    "name": "Civic Decision Engine",
                    "url": "https://civic-decision-engine-production.up.railway.app",
                },
                "publisher": {
                    "@type": "Organization",
                    "name": "Civic Decision Engine",
                    "url": "https://civic-decision-engine-production.up.railway.app",
                },
                "keywords": ", ".join(conditions),
                "about": {
                    "@type": "Thing",
                    "name": record["trajectory"] or "",
                    "description": record["system_state"] or "",
                },
            },
            indent=2,
        )

        html = f"""<!DOCTYPE html>

<html lang="{safe['lang']}">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{s["page_title"]} — {safe['reference']}</title>
  <link rel="canonical" href="{verify_url}">
  <meta name="description" content="{escape((record['finding'] or '')[:155])}">
  <script type="application/ld+json">
  {json_ld}

  </script>

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
      .document::before {{
        content: '';
        position: fixed;
        top: 50%; left: 50%;
        transform: translate(-50%, -50%);
        width: 220px; height: 280px;
        background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 512 512' fill='none'%3E%3Cellipse cx='256' cy='256' rx='230' ry='290' stroke='%232E8B9A' stroke-width='28' fill='none'/%3E%3Crect x='148' y='138' width='216' height='18' rx='9' fill='%232E8B9A'/%3E%3Crect x='168' y='170' width='176' height='14' rx='7' fill='%232E8B9A'/%3E%3Crect x='196' y='200' width='8' height='120' rx='4' fill='%232E8B9A'/%3E%3Crect x='220' y='200' width='8' height='120' rx='4' fill='%232E8B9A'/%3E%3Crect x='244' y='200' width='8' height='120' rx='4' fill='%232E8B9A'/%3E%3Crect x='268' y='200' width='8' height='120' rx='4' fill='%232E8B9A'/%3E%3Crect x='292' y='200' width='8' height='120' rx='4' fill='%232E8B9A'/%3E%3Crect x='166' y='320' width='180' height='14' rx='7' fill='%232E8B9A'/%3E%3Ctext x='256' y='388' text-anchor='middle' font-family='sans-serif' font-size='72' font-weight='600' fill='%232E8B9A'%3Ev11%3C/text%3E%3C/svg%3E");
        background-repeat: no-repeat;
        background-size: contain;
        opacity: 0.07;
        pointer-events: none;
        z-index: 0;
      }}
    }}
    .doc-mark {{
      display: flex;
      align-items: flex-start;
      color: var(--teal, #2E8B9A);
      opacity: 0.82;
    }}
    .doc-mark svg {{ display: block; }}
    .footer-seal {{
      display: flex;
      justify-content: flex-end;
      align-items: flex-end;
      opacity: 0.42;
      color: var(--teal, #2E8B9A);
    }}
    .footer-seal svg {{ display: block; }}
    @media (max-width: 600px) {{
      .document {{ padding: 28px 20px; }}
      .doc-header {{ flex-direction: column; gap: 12px; }}
      .doc-record-label, .doc-reference {{ text-align: left; }}
      .doc-footer {{ flex-direction: column; align-items: flex-start; }}
      .footer-note {{ text-align: left; }}
      .detail-table td:first-child {{ width: 120px; }}
    }}
      .doc-nav a {{
      font-family: ui-monospace, monospace;
      font-size: 0.68rem;
      color: #888;
      text-decoration: none;
      border-bottom: 1px solid #ddd;
      width: fit-content;
    }}
      .doc-nav a:hover {{
        color: #1a1a1a;
      border-color: #999;
    }}
    .cite-section {{ margin-bottom: 36px; }}
    .cite-tabs {{
      display: flex;
      gap: 0;
      border-bottom: 1px solid #e8e6e0;
      margin-bottom: 16px;
    }}
    .cite-tab {{
      font-family: ui-monospace, monospace;
      font-size: 0.68rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: #aaa;
      padding: 6px 14px 8px;
      cursor: pointer;
      border-bottom: 2px solid transparent;
      margin-bottom: -1px;
      background: none;
      border-top: none;
      border-left: none;
      border-right: none;
      transition: color 0.15s;
    }}
    .cite-tab:hover {{ color: #1a1a1a; }}
    .cite-tab.active {{
      color: #1a1a1a;
      border-bottom-color: #1a1a1a;
    }}
    .cite-panel {{ display: none; }}
    .cite-panel.active {{ display: block; }}
    .cite-block {{
      background: #f8f7f4;
      border: 1px solid #e8e6e0;
      border-radius: 4px;
      padding: 14px 16px;
      font-family: ui-monospace, monospace;
      font-size: 0.75rem;
      line-height: 1.7;
      color: #333;
      white-space: pre-wrap;
      word-break: break-all;
      position: relative;
    }}
    .cite-copy {{
      position: absolute;
      top: 8px;
      right: 8px;
      font-family: ui-monospace, monospace;
      font-size: 0.62rem;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      background: #fff;
      border: 1px solid #e8e6e0;
      border-radius: 3px;
      padding: 3px 8px;
      cursor: pointer;
      color: #888;
    }}
    .cite-copy:hover {{ color: #1a1a1a; border-color: #999; }}
    .cite-permalink {{
      font-family: ui-monospace, monospace;
      font-size: 0.72rem;
      color: #888;
      margin-top: 12px;
      line-height: 1.6;
      font-style: italic;
    }}
    .narrative-toggle {{
      font-family: ui-monospace, monospace;
      font-size: 0.72rem;
      color: #888;
      background: none;
      border: none;
      border-bottom: 1px solid #ddd;
      padding: 0;
      cursor: pointer;
      margin-bottom: 14px;
      display: inline-block;
    }}
    .narrative-toggle:hover {{ color: #1a1a1a; border-color: #999; }}
    .narrative-body {{
      display: none;
      background: #f8f7f4;
      border: 1px solid #e8e6e0;
      border-left: 3px solid #d0cec8;
      border-radius: 4px;
      padding: 16px 18px;
      font-size: 0.875rem;
      line-height: 1.75;
      color: #444;
      white-space: pre-wrap;
      font-family: Georgia, serif;
    }}
    .narrative-note {{
      font-family: ui-monospace, monospace;
      font-size: 0.68rem;
      color: #aaa;
      margin-top: 10px;
      font-style: italic;
    }}
  </style>
</head>
<body>
<div class="document">
    <header class="doc-header">
      <div>
        <div class="doc-engine">{s["engine"]}</div>
        <div class="doc-nav">
          <a href="/records">← Public record index</a>
          <a href="/patterns">Condition patterns</a>
          <a href="/graph">Interactive graph</a>
        </div>
      </div>
      <div>
        <div class="doc-record-label">{s["record_label"]}</div>
        <div class="doc-reference">{safe['reference']}</div>
      </div>
      <div class="doc-mark" aria-label="Civic Decision Engine v11">
        <svg width="42" height="52" viewBox="0 0 512 512" fill="none">
          <ellipse cx="256" cy="256" rx="230" ry="290" stroke="var(--teal, #2E8B9A)" stroke-width="28" fill="none"/>
          <rect x="148" y="138" width="216" height="18" rx="9" fill="var(--teal, #2E8B9A)"/>
          <rect x="168" y="170" width="176" height="14" rx="7" fill="var(--teal, #2E8B9A)"/>
          <rect x="196" y="200" width="8" height="120" rx="4" fill="var(--teal, #2E8B9A)"/>
          <rect x="220" y="200" width="8" height="120" rx="4" fill="var(--teal, #2E8B9A)"/>
          <rect x="244" y="200" width="8" height="120" rx="4" fill="var(--teal, #2E8B9A)"/>
          <rect x="268" y="200" width="8" height="120" rx="4" fill="var(--teal, #2E8B9A)"/>
          <rect x="292" y="200" width="8" height="120" rx="4" fill="var(--teal, #2E8B9A)"/>
          <rect x="166" y="320" width="180" height="14" rx="7" fill="var(--teal, #2E8B9A)"/>
          <text x="256" y="388" text-anchor="middle" font-family="sans-serif" font-size="72" font-weight="600" fill="var(--teal, #2E8B9A)">v11</text>
        </svg>
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
    {narrative_section}
    <section class="section cite-section">

      <h2 class="section-title">Cite this record</h2>
      <div class="cite-tabs">
        <button class="cite-tab active" onclick="showCite('apa', this)">APA</button>
        <button class="cite-tab" onclick="showCite('mla', this)">MLA</button>
        <button class="cite-tab" onclick="showCite('bibtex', this)">BibTeX</button>
        <button class="cite-tab" onclick="showCite('csl', this)">CSL JSON</button>
      </div>

      <div id="cite-apa" class="cite-panel active">
        <div class="cite-block">{escape(apa)}<button class="cite-copy" onclick="copyCite('cite-apa')">Copy</button></div>
      </div>

      <div id="cite-mla" class="cite-panel">
        <div class="cite-block">{escape(mla)}<button class="cite-copy" onclick="copyCite('cite-mla')">Copy</button></div>
      </div>

      <div id="cite-bibtex" class="cite-panel">
        <div class="cite-block">{escape(bibtex)}<button class="cite-copy" onclick="copyCite('cite-bibtex')">Copy</button></div>
      </div>

      <div id="cite-csl" class="cite-panel">
        <div class="cite-block">{escape(csl_json)}<button class="cite-copy" onclick="copyCite('cite-csl')">Copy</button></div>
      </div>

      <p class="cite-permalink">
        Permalink snapshot: This record is versioned, hash-verified, and preserved
        as a canonical civic record. The URL above resolves permanently to the latest
        version of this reference. Version history and prior hashes are accessible
        via <a href="{verify_url}?full=true" style="color:#888;">/api/verify/{escape(record['reference'])}?full=true</a>.
      </p>
    </section>
    
    <footer class="doc-footer">
      <div class="footer-tagline">{s["footer_tagline"]}</div>
      <div class="footer-note">{s["footer_note"]}</div>
      <div class="footer-seal" aria-label="Civic Decision Engine v11">
        <svg width="28" height="35" viewBox="0 0 512 512" fill="none">
          <ellipse cx="256" cy="256" rx="230" ry="290" stroke="var(--teal, #2E8B9A)" stroke-width="28" fill="none"/>
          <rect x="148" y="138" width="216" height="18" rx="9" fill="var(--teal, #2E8B9A)"/>
          <rect x="168" y="170" width="176" height="14" rx="7" fill="var(--teal, #2E8B9A)"/>
          <rect x="196" y="200" width="8" height="120" rx="4" fill="var(--teal, #2E8B9A)"/>
          <rect x="220" y="200" width="8" height="120" rx="4" fill="var(--teal, #2E8B9A)"/>
          <rect x="244" y="200" width="8" height="120" rx="4" fill="var(--teal, #2E8B9A)"/>
          <rect x="268" y="200" width="8" height="120" rx="4" fill="var(--teal, #2E8B9A)"/>
          <rect x="292" y="200" width="8" height="120" rx="4" fill="var(--teal, #2E8B9A)"/>
          <rect x="166" y="320" width="180" height="14" rx="7" fill="var(--teal, #2E8B9A)"/>
          <text x="256" y="388" text-anchor="middle" font-family="sans-serif" font-size="72" font-weight="600" fill="var(--teal, #2E8B9A)">v11</text>
        </svg>
      </div>
    </footer>
  </div>
  <script>
function showCite(id, btn) {{
  document.querySelectorAll(".cite-panel").forEach(p => p.classList.remove("active"));
  document.querySelectorAll(".cite-tab").forEach(t => t.classList.remove("active"));
  document.getElementById("cite-" + id).classList.add("active");
  btn.classList.add("active");
}}

function copyCite(panelId) {{
  const block = document.querySelector("#" + panelId + " .cite-block");
  const text = block.childNodes[0].textContent.trim();

  navigator.clipboard.writeText(text).then(() => {{
    const btn = block.querySelector(".cite-copy");
    const orig = btn.textContent;

    btn.textContent = "Copied";

    setTimeout(() => {{
      btn.textContent = orig;
    }}, 1500);
  }});
}}

function toggleNarrative() {{
  const b = document.getElementById("narrative-body");
  const btn = document.querySelector(".narrative-toggle");

  if (!b || !btn) return;

  const expanded = b.style.display === "block";

  b.style.display = expanded ? "none" : "block";

  btn.innerHTML = expanded
    ? "Expand source narrative &darr;"
    : "Collapse narrative &uarr;";
}}
</script>
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
            "source_narrative": record["source_narrative"] or "",
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
