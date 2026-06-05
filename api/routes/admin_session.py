from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import sqlite3
import time
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

try:
    from fastapi import File, Form, Request, UploadFile
except ImportError:

    def File(default=None, **_kwargs):
        return default

    from fastapi import Form, Request
except ImportError:

    def Form(default=None, **_kwargs):
        return default

    class Request:  # pragma: no cover - used only when FastAPI is stubbed.
        pass

    class UploadFile:  # pragma: no cover - used only when FastAPI is stubbed.
        pass


from fastapi.responses import HTMLResponse, JSONResponse

from api.attachments import (
    ATTACHMENT_ROOT,
    AttachmentRecordNotFound,
    list_record_attachments,
    store_attachment_bytes,
)
from fastapi.responses import HTMLResponse, JSONResponse

from api.attachments import (
    ATTACHMENT_ROOT,
    list_record_attachments,
    record_attachment_audit_event,
    validate_document_date,
)

router = APIRouter()

DB_PATH = Path(os.getenv("RECORDS_DB_PATH", "records.db"))

ADMIN_PASSWORD_ENV = "CDE_ADMIN_PASSWORD"
ADMIN_SESSION_SECRET_ENV = "CDE_ADMIN_SESSION_SECRET"
SESSION_COOKIE_NAME = "cde_admin_session"
SESSION_MAX_AGE_SECONDS = 3600
ATTACHMENT_MAX_BYTES_ENV = "CDE_ATTACHMENT_MAX_BYTES"
DEFAULT_ATTACHMENT_MAX_BYTES = 25 * 1024 * 1024
PDF_CONTENT_TYPE = "application/pdf"
EDITABLE_ATTACHMENT_METADATA_FIELDS = {
    "title",
    "description",
    "source_label",
    "document_date",
    "document_date_precision",
    "redaction_note",
}
IMMUTABLE_ATTACHMENT_FIELDS = {
    "reference",
    "record_version",
    "attachment_version",
    "filename",
    "stored_filename",
    "storage_path",
    "content_type",
    "file_size_bytes",
    "sha256_hash",
    "visibility",
    "redaction_status",
    "is_latest",
    "is_deleted",
    "uploaded_at",
}


def _http_error(status_code: int, detail: str):
    try:
        return HTTPException(status_code=status_code, detail=detail)
    except TypeError:
        exc = HTTPException(detail)
        setattr(exc, "status_code", status_code)
        setattr(exc, "detail", detail)
        return exc


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode((data + padding).encode("ascii"))


def _session_secret() -> str | None:
    return os.getenv(ADMIN_SESSION_SECRET_ENV)


def _sign(payload: str, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), payload.encode("ascii"), hashlib.sha256)
    return _b64encode(digest.digest())


def create_admin_session(now: int | None = None) -> str:
    secret = _session_secret()
    if not secret:
        raise _http_error(401, "admin_session_unauthorized")

    issued_at = int(now if now is not None else time.time())
    payload = {
        "role": "admin",
        "issued_at": issued_at,
        "expires_at": issued_at + SESSION_MAX_AGE_SECONDS,
    }
    payload_json = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    payload_b64 = _b64encode(payload_json.encode("utf-8"))
    signature = _sign(payload_b64, secret)
    return f"{payload_b64}.{signature}"


def verify_admin_session(session: str, now: int | None = None) -> dict[str, Any]:
    secret = _session_secret()
    if not secret:
        raise _http_error(401, "admin_session_unauthorized")

    try:
        payload_b64, signature = session.split(".", 1)
    except ValueError as exc:
        raise _http_error(401, "admin_session_unauthorized") from exc

    expected_signature = _sign(payload_b64, secret)
    if not hmac.compare_digest(signature, expected_signature):
        raise _http_error(401, "admin_session_unauthorized")

    try:
        payload = json.loads(_b64decode(payload_b64).decode("utf-8"))
    except (ValueError, json.JSONDecodeError) as exc:
        raise _http_error(401, "admin_session_unauthorized") from exc

    allowed_keys = {"role", "issued_at", "expires_at"}
    if set(payload.keys()) != allowed_keys or payload.get("role") != "admin":
        raise _http_error(401, "admin_session_unauthorized")

    expires_at = payload.get("expires_at")
    if not isinstance(expires_at, int):
        raise _http_error(401, "admin_session_unauthorized")

    current_time = int(now if now is not None else time.time())
    if expires_at <= current_time:
        raise _http_error(401, "admin_session_unauthorized")

    return payload


def require_admin_session(request) -> dict[str, Any]:
    cookies = getattr(request, "cookies", {}) or {}
    session = cookies.get(SESSION_COOKIE_NAME)
    if not session:
        raise _http_error(401, "admin_session_unauthorized")
    return verify_admin_session(session)


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def attachment_max_upload_bytes() -> int:
    raw_value = os.getenv(ATTACHMENT_MAX_BYTES_ENV)
    if raw_value is None:
        return DEFAULT_ATTACHMENT_MAX_BYTES
    try:
        parsed = int(raw_value)
    except ValueError as exc:
        raise _http_error(500, "admin_attachment_size_limit_invalid") from exc
    if parsed < 1:
        raise _http_error(500, "admin_attachment_size_limit_invalid")
    return parsed


def validate_pdf_attachment_upload(content_type: str | None, data: bytes) -> str:
    normalized_content_type = (content_type or "").split(";", 1)[0].strip().lower()
    if normalized_content_type != PDF_CONTENT_TYPE:
        raise _http_error(415, "attachment_content_type_not_allowed")
    if len(data) > attachment_max_upload_bytes():
        raise _http_error(413, "attachment_too_large")
    return normalized_content_type


def attachment_metadata_response(attachment: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in attachment.items()
        if key
        not in {
            "storage_path",
            "stored_filename",
            "file_exists",
            "file_sha256_matches",
        }
    }


def _safe_attachment_response(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "attachment_id": row["id"],
        "reference": row["reference"],
        "record_version": row["record_version"],
        "attachment_version": row["attachment_version"],
        "filename": row["filename"],
        "content_type": row["content_type"],
        "file_size_bytes": row["file_size_bytes"],
        "sha256_hash": row["sha256_hash"],
        "visibility": row["visibility"],
        "redaction_status": row["redaction_status"],
        "title": row["title"],
        "description": row["description"],
        "source_label": row["source_label"],
        "document_date": row["document_date"],
        "document_date_precision": row["document_date_precision"] or "unknown",
        "redaction_note": row["redaction_note"],
        "uploaded_at": row["uploaded_at"],
        "is_latest": row["is_latest"],
        "is_deleted": row["is_deleted"],
    }


def _attachment_row_to_metadata(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "attachment_id": row["id"],
        "reference": row["reference"],
        "record_version": row["record_version"],
        "attachment_version": row["attachment_version"],
        "filename": row["filename"],
        "content_type": row["content_type"],
        "file_size_bytes": row["file_size_bytes"],
        "sha256_hash": row["sha256_hash"],
        "visibility": row["visibility"],
        "redaction_status": row["redaction_status"],
        "title": row["title"],
        "description": row["description"],
        "source_label": row["source_label"],
        "document_date": row["document_date"],
        "document_date_precision": row["document_date_precision"] or "unknown",
        "uploaded_at": row["uploaded_at"],
        "is_latest": row["is_latest"],
        "is_deleted": row["is_deleted"],
        "appears_in_public_manifest": (
            row["visibility"] == "public"
            and row["redaction_status"] != "withheld"
            and row["is_latest"] == 1
            and row["is_deleted"] == 0
        ),
    }


def _set_session_cookie(response, session: str) -> None:
    if hasattr(response, "set_cookie"):
        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=session,
            max_age=SESSION_MAX_AGE_SECONDS,
            httponly=True,
            secure=True,
            samesite="strict",
        )
        return

    response.headers["Set-Cookie"] = (
        f"{SESSION_COOKIE_NAME}={session}; Max-Age={SESSION_MAX_AGE_SECONDS}; "
        "HttpOnly; Secure; SameSite=Strict"
    )


def _clear_session_cookie(response) -> None:
    if hasattr(response, "delete_cookie"):
        response.delete_cookie(
            key=SESSION_COOKIE_NAME,
            httponly=True,
            secure=True,
            samesite="strict",
        )
        return

    response.headers["Set-Cookie"] = (
        f"{SESSION_COOKIE_NAME}=; Max-Age=0; HttpOnly; Secure; SameSite=Strict"
    )


def _attachment_state(attachment: dict[str, Any]) -> str:
    if attachment.get("is_deleted") == 1:
        return "deleted"
    if attachment.get("redaction_status") == "withheld":
        return "withheld"
    return "active"


def _format_admin_timestamp(value: Any) -> str:
    if value in (None, ""):
        return "unknown time"
    raw_value = str(value)
    try:
        parsed = datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
    except ValueError:
        return raw_value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    parsed = parsed.astimezone(timezone.utc)
    return parsed.strftime("%Y-%m-%d %H:%M UTC")


def _audit_event_badge_label(event_type: Any) -> str:
    labels = {
        "attachment_metadata_corrected": "metadata corrected",
        "synthetic_audit_verification": "synthetic verification",
        "attachment_withheld": "withheld",
        "attachment_restored": "restored",
        "attachment_soft_deleted": "soft deleted",
    }
    event_text = str(event_type or "audit event")
    return labels.get(event_text, "audit event")


def _render_admin_attachment_rows(attachments: list[dict[str, Any]]) -> str:
    if not attachments:
        return """
      <p>No attachments are currently associated with this record.</p>"""

    cards = []
    for index, attachment in enumerate(attachments):
        state = _attachment_state(attachment)
        summary_title = attachment.get("title") or attachment.get("filename") or "Attachment"
        summary_meta = (
            f"{state} • {attachment.get('visibility') or 'unknown visibility'} • "
            f"{attachment.get('redaction_status') or 'unknown redaction'}"
        )
        summary_time = _format_admin_timestamp(attachment.get("uploaded_at"))
        rows = (
            ("Record version", attachment.get("record_version")),
            ("Title", attachment.get("title")),
            ("Description", attachment.get("description")),
            ("Source label", attachment.get("source_label")),
            ("Filename", attachment.get("filename")),
            ("Content type", attachment.get("content_type")),
            ("File size", attachment.get("file_size_bytes")),
            ("SHA-256 hash", attachment.get("sha256_hash")),
            ("Visibility", attachment.get("visibility")),
            ("Redaction status", attachment.get("redaction_status")),
            ("Lifecycle state", _attachment_state(attachment)),
            ("Document date", attachment.get("document_date")),
            ("Document date precision", attachment.get("document_date_precision")),
            ("Uploaded at", attachment.get("uploaded_at")),
        )
        table_rows = "".join(
            "<tr>"
            f"<td>{escape(label)}</td>"
            f"<td>{escape(str(value)) if value not in (None, '') else '—'}</td>"
            "</tr>"
            for label, value in rows
        )
        open_attr = " open" if index == 0 else ""
        cards.append(f"""
      <details class="attachment-card"{open_attr}>
        <summary>
          <span class="summary-title">{escape(str(summary_title))}</span>
          <span class="summary-meta">{escape(summary_meta)}</span>
          <span class="summary-time">{escape(summary_time)}</span>
        </summary>
        <table>
          <tbody>{table_rows}</tbody>
        </table>
      </details>""")

    return "".join(cards)


def list_attachment_audit_events(
    conn: sqlite3.Connection, *, reference: str
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
            attachment_id,
            reference,
            record_version,
            event_type,
            actor,
            occurred_at,
            metadata_json,
            request_id
        FROM attachment_audit_events
        WHERE reference = ?
        ORDER BY occurred_at DESC, id DESC
        """,
        (reference,),
    ).fetchall()
    return [dict(row) for row in rows]


SENSITIVE_AUDIT_METADATA_KEYS = {
    "storage_path",
    "stored_filename",
    "source_narrative",
    "report_json",
    "raw_input",
    "raw_file_content",
}


def _redact_audit_metadata(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _redact_audit_metadata(item)
            for key, item in value.items()
            if key not in SENSITIVE_AUDIT_METADATA_KEYS
        }
    if isinstance(value, list):
        return [_redact_audit_metadata(item) for item in value]
    return value


def _render_audit_metadata_json(metadata_json: Any) -> str:
    if metadata_json in (None, ""):
        return ""
    try:
        parsed = json.loads(str(metadata_json))
    except json.JSONDecodeError:
        rendered = str(metadata_json)
    else:
        rendered = json.dumps(
            _redact_audit_metadata(parsed),
            indent=2,
            sort_keys=True,
        )
    return (
        '<div class="audit-metadata">'
        "<h3>metadata_json</h3>"
        f"<pre>{escape(rendered)}</pre>"
        "</div>"
    )


def _render_admin_audit_events(audit_events: list[dict[str, Any]]) -> str:
    if not audit_events:
        return """
      <p>No audit events are currently recorded for this record.</p>"""

    cards = []
    for index, event in enumerate(audit_events):
        event_type = event.get("event_type") or "audit event"
        actor = event.get("actor") or "unknown actor"
        attachment_id = event.get("attachment_id")
        attachment_fragment = (
            f"Attachment {attachment_id} • " if attachment_id not in (None, "") else ""
        )
        summary_meta = (
            f"{attachment_fragment}{actor} • "
            f"{_format_admin_timestamp(event.get('occurred_at'))}"
        )
        badge_label = _audit_event_badge_label(event_type)
        rows = (
            ("Occurred at", event.get("occurred_at")),
            ("Event type", event.get("event_type")),
            ("Actor", event.get("actor")),
            ("Attachment ID", event.get("attachment_id")),
            ("Record version", event.get("record_version")),
            ("Request ID", event.get("request_id")),
        )
        table_rows = "".join(
            "<tr>"
            f"<td>{escape(label)}</td>"
            f"<td>{escape(str(value)) if value not in (None, '') else '—'}</td>"
            "</tr>"
            for label, value in rows
        )
        metadata_block = _render_audit_metadata_json(event.get("metadata_json"))
        open_attr = " open" if index == 0 else ""
        cards.append(f"""
      <details class="audit-event"{open_attr}>
        <summary>
          <span class="event-badge">[{escape(badge_label)}]</span>
          <span class="summary-title">{escape(str(event_type))}</span>
          <span class="summary-meta">{escape(summary_meta)}</span>
        </summary>
        <table>
          <tbody>{table_rows}</tbody>
        </table>
        {metadata_block}
      </details>""")

    return "".join(cards)


def _normalize_optional_metadata_value(value: Any) -> Any:
    if value == "":
        return None
    return value


def _validate_metadata_correction_payload(
    payload: dict[str, Any], current: sqlite3.Row
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise _http_error(400, "metadata_payload_invalid")

    unknown_fields = set(payload) - EDITABLE_ATTACHMENT_METADATA_FIELDS - IMMUTABLE_ATTACHMENT_FIELDS
    if unknown_fields:
        raise _http_error(400, "metadata_field_unknown")

    immutable_fields = set(payload) & IMMUTABLE_ATTACHMENT_FIELDS
    if immutable_fields:
        raise _http_error(400, "metadata_field_immutable")

    updates = {
        key: _normalize_optional_metadata_value(value)
        for key, value in payload.items()
        if key in EDITABLE_ATTACHMENT_METADATA_FIELDS
    }
    if not updates:
        raise _http_error(400, "metadata_no_editable_fields")

    if "document_date" in updates or "document_date_precision" in updates:
        document_date = updates.get("document_date", current["document_date"])
        document_date_precision = updates.get(
            "document_date_precision",
            current["document_date_precision"] or "unknown",
        )
        try:
            normalized_date, normalized_precision = validate_document_date(
                document_date,
                document_date_precision,
            )
        except ValueError as exc:
            raise _http_error(400, "document_date_invalid") from exc
        updates["document_date"] = normalized_date
        updates["document_date_precision"] = normalized_precision

    return updates


def render_admin_attachments_page(
    *,
    reference: str,
    record_version: int,
    attachments: list[dict[str, Any]],
    audit_events: list[dict[str, Any]],
) -> str:
    attachment_rows = _render_admin_attachment_rows(attachments)
    audit_rows = _render_admin_audit_events(audit_events)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Admin Attachments - {escape(reference)}</title>
  <style>
    body {{
      font-family: system-ui, sans-serif;
      margin: 0;
      padding: 32px;
      background: #f7f7f4;
      color: #1a1a1a;
    }}
    main {{
      max-width: 920px;
      margin: 0 auto;
      background: #fff;
      border: 1px solid #ddd;
      padding: 28px;
      position: relative;
      overflow: hidden;
    }}
    .admin-watermark {{
      position: fixed;
      top: 50%;
      left: 50%;
      width: min(60vw, 520px);
      max-width: 82%;
      transform: translate(-50%, -50%);
      opacity: 0.045;
      pointer-events: none;
      z-index: 0;
      print-color-adjust: exact;
      -webkit-print-color-adjust: exact;
    }}
    main > *:not(.admin-watermark) {{
      position: relative;
      z-index: 1;
    }}
    @media print {{
      body {{
        background: #fff;
      }}
      main {{
        border: none;
      }}
      .admin-watermark {{
        opacity: 0.06;
      }}
      details {{
        display: block;
        break-inside: avoid;
      }}
      details > * {{
        display: block;
      }}
    }}
    .notice {{
      border: 1px solid #d8d4ca;
      background: #faf9f5;
      padding: 12px 14px;
      margin: 18px 0 24px;
      color: #555;
    }}
    .management-section {{
      border-top: 1px solid #e5e1d8;
      padding-top: 18px;
      margin-top: 22px;
    }}
    .management-section h2 {{
      font-size: 1.05rem;
      margin: 0 0 10px;
    }}
    .administrative-capabilities ul {{
      margin: 8px 0 0 20px;
      padding: 0;
    }}
    .administrative-capabilities li {{
      margin: 4px 0;
    }}
    .capability-group {{
      margin-top: 12px;
    }}
    .capability-group h3 {{
      margin: 0 0 6px;
      color: #555;
      font-size: 0.9rem;
      font-family: ui-monospace, monospace;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }}
    details {{
      break-inside: avoid;
    }}
    summary {{
      display: grid;
      gap: 3px;
      cursor: pointer;
      padding: 10px;
      background: #faf9f5;
      color: #333;
      font-weight: 600;
      word-break: break-word;
    }}
    .summary-title,
    .summary-meta,
    .summary-time {{
      display: block;
    }}
    .summary-title {{
      font-weight: 700;
    }}
    .summary-meta,
    .summary-time {{
      color: #555;
      font-size: 0.88rem;
      font-weight: 500;
    }}
    .event-badge {{
      display: inline-block;
      width: max-content;
      border: 1px solid #c9ddd8;
      background: #eef8f6;
      color: #245d61;
      padding: 2px 6px;
      font-family: ui-monospace, monospace;
      font-size: 0.72rem;
      font-weight: 700;
      text-transform: lowercase;
    }}
    .attachment-card {{
      border: 1px solid #e5e1d8;
      margin-top: 16px;
      overflow: hidden;
    }}
    .audit-event {{
      border: 1px solid #e5e1d8;
      margin-top: 16px;
      overflow: hidden;
    }}
    .audit-metadata {{
      border-top: 1px solid #eee;
      padding: 10px;
      background: #fbfaf7;
    }}
    .audit-metadata h3 {{
      margin: 0 0 8px;
      font-size: 0.78rem;
      color: #666;
      font-family: ui-monospace, monospace;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }}
    .audit-metadata pre {{
      margin: 0;
      white-space: pre-wrap;
      word-break: break-word;
      font-family: ui-monospace, monospace;
      font-size: 0.86rem;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.9rem;
    }}
    tr {{ border-bottom: 1px solid #eee; }}
    tr:last-child {{ border-bottom: none; }}
    td {{
      padding: 8px 10px;
      vertical-align: top;
      word-break: break-word;
    }}
    td:first-child {{
      width: 190px;
      background: #faf9f5;
      color: #666;
      font-family: ui-monospace, monospace;
      font-size: 0.78rem;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }}
    td:last-child {{ font-family: ui-monospace, monospace; }}
  </style>
</head>
<body>
  <main>
    <svg class="admin-watermark print-watermark" viewBox="0 0 512 512" aria-hidden="true" focusable="false">
      <ellipse cx="256" cy="256" rx="230" ry="290" stroke="#2E8B9A" stroke-width="28" fill="none"></ellipse>
      <rect x="148" y="138" width="216" height="18" rx="9" fill="#2E8B9A"></rect>
      <rect x="168" y="170" width="176" height="14" rx="7" fill="#2E8B9A"></rect>
      <rect x="196" y="200" width="8" height="120" rx="4" fill="#2E8B9A"></rect>
      <rect x="220" y="200" width="8" height="120" rx="4" fill="#2E8B9A"></rect>
      <rect x="244" y="200" width="8" height="120" rx="4" fill="#2E8B9A"></rect>
      <rect x="268" y="200" width="8" height="120" rx="4" fill="#2E8B9A"></rect>
      <rect x="292" y="200" width="8" height="120" rx="4" fill="#2E8B9A"></rect>
      <rect x="166" y="320" width="180" height="14" rx="7" fill="#2E8B9A"></rect>
      <text x="256" y="388" text-anchor="middle" font-family="sans-serif" font-size="72" font-weight="600" fill="#2E8B9A">v12</text>
    </svg>
    <h1>Admin Attachment Management</h1>
    <p class="notice">
      Administrative attachment management is read-only in this stage.
      No upload, edit, delete, restore, withhold, publish, correction, or download actions are available.
    </p>
    <section class="management-section record-summary">
      <h2>Record summary</h2>
      <p><strong>Record reference:</strong> {escape(reference)}</p>
      <p><strong>Record version:</strong> {record_version}</p>
    </section>
    <section class="management-section current-attachments">
      <h2>Current attachments</h2>
      {attachment_rows}
    </section>
    <section class="management-section administrative-capabilities">
      <h2>Administrative capabilities</h2>
      <div class="capability-group">
        <h3>Implemented</h3>
        <ul>
          <li>metadata correction</li>
          <li>withhold / restore</li>
          <li>soft-delete</li>
          <li>audit trail review</li>
        </ul>
      </div>
      <div class="capability-group">
        <h3>Planned</h3>
        <ul>
          <li>upload</li>
          <li>publication workflow</li>
        </ul>
      </div>
    </section>
    <section class="management-section audit-trail">
      <h2>Audit trail</h2>
      {audit_rows}
    </section>
    <section class="management-section governance-notice">
      <h2>Governance notice</h2>
      <p>Administrative attachment management is read-only in this stage.</p>
      <p>No upload, edit, delete, restore, withhold, publish, correction, or download actions are available.</p>
    </section>
  </main>
</body>
</html>"""


@router.get("/admin/login", response_class=HTMLResponse)
def admin_login_page():
    html = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>CDE Admin Login</title>
</head>
<body>
  <main>
    <h1>Civic Decision Engine Admin</h1>
    <form method="post" action="/api/admin/session/login">
      <label for="password">Admin password</label>
      <input id="password" name="password" type="password" autocomplete="current-password" required>
      <button type="submit">Sign in</button>
    </form>
  </main>
</body>
</html>
"""
    return HTMLResponse(content=html)


@router.post("/api/admin/session/login")
def admin_session_login(password: str = Form(...)):
    expected_password = os.getenv(ADMIN_PASSWORD_ENV)
    if not expected_password or not _session_secret():
        raise _http_error(401, "admin_session_unauthorized")
    if not hmac.compare_digest(str(password), expected_password):
        raise _http_error(401, "admin_session_unauthorized")

    session = create_admin_session()
    response = JSONResponse(content={"ok": True, "role": "admin"})
    _set_session_cookie(response, session)
    return response


@router.post("/api/admin/session/logout")
def admin_session_logout():
    response = JSONResponse(content={"ok": True})
    _clear_session_cookie(response)
    return response


@router.get("/admin/records/{reference}/attachments", response_class=HTMLResponse)
def admin_record_attachments_page(reference: str, request: Request):
    require_admin_session(request)
    conn = get_db()
    try:
        record = conn.execute(
            "SELECT reference, version FROM records "
            "WHERE reference = ? AND is_latest = 1 "
            "ORDER BY version DESC LIMIT 1",
            (reference,),
        ).fetchone()
        if not record:
            raise _http_error(404, "record_not_found")

        attachments = list_record_attachments(
            conn,
            reference=reference,
            verify_files=False,
            attachment_root=Path(
                os.getenv("CDE_ATTACHMENT_ROOT", str(ATTACHMENT_ROOT))
            ),
        )
        return HTMLResponse(
            content=render_admin_attachments_page(
                reference=record["reference"],
                record_version=record["version"],
                attachments=attachments,
                audit_events=list_attachment_audit_events(
                    conn, reference=record["reference"]
                ),
            )
        )
    finally:
        conn.close()


@router.get("/records/{reference}/attachments")
def list_record_attachments_route(reference: str, request: Request):
    require_admin_session(request)
    conn = get_db()
    try:
        attachments = list_record_attachments(conn, reference=reference)
        return JSONResponse(
            content={
                "reference": reference,
                "attachment_count": len(attachments),
                "attachments": [
                    attachment_metadata_response(attachment)
                    for attachment in attachments
                ],
            }
        )
    finally:
        conn.close()


@router.patch("/api/admin/session/records/{reference}/attachments/{attachment_id}/metadata")
def correct_attachment_metadata_route(
    reference: str,
    attachment_id: int,
    request: Request,
    payload: dict[str, Any],
):
    require_admin_session(request)
    conn = get_db()
    try:
        current = conn.execute(
            "SELECT * FROM record_attachments WHERE id = ? AND reference = ?",
            (attachment_id, reference),
        ).fetchone()
        if not current:
            raise _http_error(404, "attachment_not_found")

        updates = _validate_metadata_correction_payload(payload, current)
        previous_values = {field: current[field] for field in updates}
        changed_fields = [
            field for field, value in updates.items() if previous_values[field] != value
        ]

        if changed_fields:
            set_clause = ", ".join(f"{field} = ?" for field in changed_fields)
            values = [updates[field] for field in changed_fields]
            values.extend([attachment_id, reference])
            conn.execute(
                f"UPDATE record_attachments SET {set_clause} WHERE id = ? AND reference = ?",
                values,
            )

        updated = conn.execute(
            "SELECT * FROM record_attachments WHERE id = ? AND reference = ?",
            (attachment_id, reference),
        ).fetchone()
        audit_event_id = record_attachment_audit_event(
            conn,
            event_type="attachment_metadata_corrected",
            reference=reference,
            attachment_id=attachment_id,
            record_version=updated["record_version"],
            metadata={
                "changed_fields": changed_fields,
                "previous_values": {
                    field: previous_values[field] for field in changed_fields
                },
                "new_values": {field: updated[field] for field in changed_fields},
            },
        )
        conn.commit()

        return JSONResponse(
            content={
                "ok": True,
                "audit_event_id": audit_event_id,
                "changed_fields": changed_fields,
                "attachment": _safe_attachment_response(updated),
            }
        )
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _apply_attachment_lifecycle_action(
    *,
    reference: str,
    attachment_id: int,
    request: Request,
    action: str,
    event_type: str,
    redaction_status: str | None = None,
    is_deleted: int | None = None,
):
    require_admin_session(request)
    conn = get_db()
    try:
        current = conn.execute(
            "SELECT * FROM record_attachments WHERE id = ? AND reference = ?",
            (attachment_id, reference),
        ).fetchone()
        if not current:
            raise _http_error(404, "attachment_not_found")

        previous_redaction_status = current["redaction_status"]
        previous_is_deleted = current["is_deleted"]
        new_redaction_status = (
            previous_redaction_status if redaction_status is None else redaction_status
        )
        new_is_deleted = previous_is_deleted if is_deleted is None else is_deleted

        conn.execute(
            """
            UPDATE record_attachments
            SET redaction_status = ?, is_deleted = ?
            WHERE id = ? AND reference = ?
            """,
            (new_redaction_status, new_is_deleted, attachment_id, reference),
        )
        updated = conn.execute(
            "SELECT * FROM record_attachments WHERE id = ? AND reference = ?",
            (attachment_id, reference),
        ).fetchone()
        audit_event_id = record_attachment_audit_event(
            conn,
            event_type=event_type,
            reference=reference,
            attachment_id=attachment_id,
            record_version=updated["record_version"],
            metadata={
                "action": action,
                "previous_redaction_status": previous_redaction_status,
                "new_redaction_status": updated["redaction_status"],
                "previous_is_deleted": previous_is_deleted,
                "new_is_deleted": updated["is_deleted"],
            },
        )
        conn.commit()

        return JSONResponse(
            content={
                "ok": True,
                "action": action,
                "audit_event_id": audit_event_id,
                "attachment": _safe_attachment_response(updated),
            }
        )
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.patch("/api/admin/session/records/{reference}/attachments/{attachment_id}/withhold")
def withhold_attachment_route(reference: str, attachment_id: int, request: Request):
    return _apply_attachment_lifecycle_action(
        reference=reference,
        attachment_id=attachment_id,
        request=request,
        action="withhold",
        event_type="attachment_withheld",
        redaction_status="withheld",
    )


@router.patch("/api/admin/session/records/{reference}/attachments/{attachment_id}/restore")
def restore_attachment_route(reference: str, attachment_id: int, request: Request):
    return _apply_attachment_lifecycle_action(
        reference=reference,
        attachment_id=attachment_id,
        request=request,
        action="restore",
        event_type="attachment_restored",
        redaction_status="none",
        is_deleted=0,
    )


@router.patch("/api/admin/session/records/{reference}/attachments/{attachment_id}/soft-delete")
def soft_delete_attachment_route(reference: str, attachment_id: int, request: Request):
    return _apply_attachment_lifecycle_action(
        reference=reference,
        attachment_id=attachment_id,
        request=request,
        action="soft-delete",
        event_type="attachment_soft_deleted",
        is_deleted=1,
    )
