from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import sqlite3
import time
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

from api.attachments import ATTACHMENT_ROOT, list_record_attachments

router = APIRouter()

DB_PATH = Path(os.getenv("RECORDS_DB_PATH", "records.db"))

ADMIN_PASSWORD_ENV = "CDE_ADMIN_PASSWORD"
ADMIN_SESSION_SECRET_ENV = "CDE_ADMIN_SESSION_SECRET"
SESSION_COOKIE_NAME = "cde_admin_session"
SESSION_MAX_AGE_SECONDS = 3600
ATTACHMENT_MAX_BYTES_ENV = "CDE_ATTACHMENT_MAX_BYTES"
DEFAULT_ATTACHMENT_MAX_BYTES = 25 * 1024 * 1024
PDF_CONTENT_TYPE = "application/pdf"


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


def _render_admin_attachment_rows(attachments: list[dict[str, Any]]) -> str:
    if not attachments:
        return """
      <p>No attachments are currently associated with this record.</p>"""

    cards = []
    for attachment in attachments:
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
        cards.append(f"""
      <section class="attachment-card">
        <table>
          <tbody>{table_rows}</tbody>
        </table>
      </section>""")

    return "".join(cards)


def render_admin_attachments_page(
    *, reference: str, record_version: int, attachments: list[dict[str, Any]]
) -> str:
    attachment_rows = _render_admin_attachment_rows(attachments)
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
    .future-actions ul {{
      margin: 8px 0 0 20px;
      padding: 0;
    }}
    .future-actions li {{
      margin: 4px 0;
    }}
    .attachment-card {{
      border: 1px solid #e5e1d8;
      margin-top: 16px;
      overflow: hidden;
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
    <section class="management-section future-actions">
      <h2>Future management actions</h2>
      <p>Future controls planned:</p>
      <ul>
        <li>metadata correction</li>
        <li>withhold / restore</li>
        <li>soft-delete</li>
        <li>upload</li>
        <li>audit trail review</li>
      </ul>
    </section>
    <section class="management-section audit-placeholder">
      <h2>Audit trail placeholder</h2>
      <p>Audit trail display is planned for a later Stage 5B step.</p>
      <p>No audit events are displayed in Step 4A.</p>
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
            )
        )
    finally:
        conn.close()


@router.get("/records/{reference}/attachments")
def list_record_attachments_route(reference: str, request: Request):
    require_admin_session(request)
    conn = get_db()
    try:
        attachments = [
            attachment
            for attachment in list_record_attachments(conn, reference=reference)
            if attachment.get("is_deleted") != 1
        ]
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


@router.post("/records/{reference}/attachments/{attachment_id}/delete")
def delete_record_attachment_route(reference: str, attachment_id: int, request: Request):
    require_admin_session(request)
    conn = get_db()
    try:
        row = conn.execute(
            """
            SELECT * FROM record_attachments
            WHERE id = ? AND reference = ?
            """,
            (attachment_id, reference),
        ).fetchone()
        if not row:
            raise _http_error(404, "attachment_not_found")

        conn.execute(
            """
            UPDATE record_attachments
            SET is_deleted = 1
            WHERE id = ? AND reference = ?
            """,
            (attachment_id, reference),
        )
        conn.commit()
        deleted = conn.execute(
            "SELECT * FROM record_attachments WHERE id = ? AND reference = ?",
            (attachment_id, reference),
        ).fetchone()
        return JSONResponse(
            content={"attachment": _attachment_row_to_metadata(deleted)}
        )
    finally:
        conn.close()


@router.post("/records/{reference}/attachments")
async def upload_record_attachment_route(
    reference: str,
    request: Request,
    file: UploadFile = File(...),
    visibility: str = Form("private"),
    redaction_status: str = Form("none"),
    title: str | None = Form(None),
    description: str | None = Form(None),
    source_label: str | None = Form(None),
    redaction_note: str | None = Form(None),
    document_date: str | None = Form(None),
    document_date_precision: str | None = Form("unknown"),
):
    require_admin_session(request)
    data = await file.read()
    content_type = validate_pdf_attachment_upload(file.content_type, data)
    conn = get_db()
    try:
        attachment = store_attachment_bytes(
            conn,
            reference=reference,
            data=data,
            original_filename=file.filename or "attachment.pdf",
            content_type=content_type,
            visibility=visibility,
            redaction_status=redaction_status,
            title=title,
            description=description,
            source_label=source_label,
            redaction_note=redaction_note,
            document_date=document_date,
            document_date_precision=document_date_precision,
            root=Path(os.getenv("CDE_ATTACHMENT_ROOT", str(ATTACHMENT_ROOT))),
        )
        return JSONResponse(
            status_code=201,
            content={"attachment": attachment_metadata_response(attachment)},
        )
    except AttachmentRecordNotFound as exc:
        raise _http_error(404, str(exc))
    except ValueError as exc:
        raise _http_error(400, str(exc))
    finally:
        conn.close()
