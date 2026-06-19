from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
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
    list_attachment_relationships,
    list_record_attachments,
    record_attachment_audit_event,
    store_attachment_bytes,
    validate_attachment_relationship,
    validate_attachment_classification,
    validate_attachment_visibility,
    validate_document_date,
    validate_publication_status,
)

router = APIRouter()

DB_PATH = Path(os.getenv("RECORDS_DB_PATH", "records.db"))

ADMIN_PASSWORD_ENV = "CDE_ADMIN_PASSWORD"
ADMIN_SESSION_SECRET_ENV = "CDE_ADMIN_SESSION_SECRET"
ADMIN_TEMP_UPLOAD_ENABLED_ENV = "ADMIN_TEMP_UPLOAD_ENABLED"
SESSION_COOKIE_NAME = "cde_admin_session"
SESSION_MAX_AGE_SECONDS = 3600
ATTACHMENT_MAX_BYTES_ENV = "CDE_ATTACHMENT_MAX_BYTES"
DEFAULT_ATTACHMENT_MAX_BYTES = 25 * 1024 * 1024
PDF_CONTENT_TYPE = "application/pdf"
ATTACHMENT_CLASSIFICATION_OPTIONS = (
    "evidence",
    "correspondence",
    "decision",
    "medical_record",
    "legal_filing",
    "photograph",
    "media",
    "research",
    "other",
)
ATTACHMENT_PUBLICATION_STATUS_OPTIONS = ("internal", "published", "withdrawn")
ATTACHMENT_VISIBILITY_OPTIONS = ("private", "public")
ATTACHMENT_RELATIONSHIP_TYPE_OPTIONS = ("supports", "contradicts", "context_for")
ATTACHMENT_RELATIONSHIP_TARGET_TYPE_OPTIONS = (
    "condition",
    "signal",
    "finding",
    "record",
)
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


def admin_temp_upload_enabled() -> bool:
    return str(os.getenv(ADMIN_TEMP_UPLOAD_ENABLED_ENV, "false")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def validate_pdf_attachment_upload(content_type: str | None, data: bytes) -> str:
    normalized_content_type = (content_type or "").split(";", 1)[0].strip().lower()
    if normalized_content_type != PDF_CONTENT_TYPE:
        raise _http_error(415, "attachment_content_type_not_allowed")
    if len(data) > attachment_max_upload_bytes():
        raise _http_error(413, "attachment_too_large")
    return normalized_content_type


def validate_temporary_attachment_upload(content_type: str | None, data: bytes) -> str:
    if not data:
        raise _http_error(400, "attachment_file_required")
    if len(data) > attachment_max_upload_bytes():
        raise _http_error(413, "attachment_too_large")
    return (content_type or "application/octet-stream").split(";", 1)[0].strip() or "application/octet-stream"


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
        "classification": row["classification"] or "other",
        "publication_status": row["publication_status"] or "internal",
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
        "classification": row["classification"] or "other",
        "publication_status": row["publication_status"] or "internal",
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
        "attachment_classification_updated": "classification updated",
        "attachment_publication_updated": "publication updated",
        "attachment_visibility_updated": "visibility updated",
        "attachment_relationship_added": "relationship added",
        "attachment_relationship_removed": "relationship removed",
    }
    event_text = str(event_type or "audit event")
    return labels.get(event_text, "audit event")


def _safe_json_for_script(value: Any) -> str:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True)
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )


def _record_relationship_target_options(record: sqlite3.Row) -> dict[str, list[str]]:
    keys = set(record.keys())
    reference = str(record["reference"]) if "reference" in keys else ""
    finding = (
        str(record["finding"]).strip()
        if "finding" in keys and record["finding"]
        else ""
    )
    return {
        "condition": _json_list_targets(
            record["conditions_json"] if "conditions_json" in keys else None
        ),
        "signal": _signal_targets(
            record["signals_json"] if "signals_json" in keys else None
        ),
        "finding": [finding] if finding else [],
        "record": [reference] if reference else [],
    }


def _record_outputs_from_record(record: sqlite3.Row) -> dict[str, str]:
    keys = set(record.keys())
    return {
        "reference": str(record["reference"]) if "reference" in keys else "",
        "trajectory": (
            str(record["trajectory"]).strip()
            if "trajectory" in keys and record["trajectory"]
            else ""
        ),
        "finding": (
            str(record["finding"]).strip()
            if "finding" in keys and record["finding"]
            else ""
        ),
        "system_state": (
            str(record["system_state"]).strip()
            if "system_state" in keys and record["system_state"]
            else ""
        ),
    }


def _resolve_record_target_key(
    record: sqlite3.Row, target_type: str, target_label: str
) -> str:
    target_options = _record_relationship_target_options(record)
    candidates = target_options.get(target_type, [])
    normalized_label = str(target_label or "").strip()
    if not normalized_label:
        raise _http_error(400, "attachment_target_label_required")

    for candidate in candidates:
        if candidate == normalized_label:
            return candidate

    folded_label = normalized_label.casefold()
    for candidate in candidates:
        if _guided_target_display_label(candidate).casefold() == folded_label:
            return candidate

    raise _http_error(400, "attachment_target_not_found")


def _json_list_targets(raw_json: Any) -> list[str]:
    if not raw_json:
        return []
    try:
        parsed = json.loads(str(raw_json))
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return _dedupe_nonblank_strings(parsed)


def _signal_targets(raw_json: Any) -> list[str]:
    if not raw_json:
        return []
    try:
        parsed = json.loads(str(raw_json))
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []

    targets = []
    for item in parsed:
        if isinstance(item, str):
            targets.append(item)
        elif isinstance(item, dict):
            for key in ("name", "title", "label", "signal", "key", "id"):
                value = item.get(key)
                if isinstance(value, str) and value.strip():
                    targets.append(value)
                    break
    return _dedupe_nonblank_strings(targets)


def _dedupe_nonblank_strings(values: list[Any]) -> list[str]:
    seen = set()
    targets = []
    for value in values:
        if not isinstance(value, str):
            continue
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        targets.append(normalized)
    return targets


def _guided_target_display_label(value: str) -> str:
    if re.fullmatch(r"[A-Z0-9]+(?:_[A-Z0-9]+)+", value):
        return value.replace("_", " ").title()
    return value


def _render_target_key_options(
    target_options: dict[str, list[str]], target_type: str
) -> str:
    values = target_options.get(target_type) or []
    if not values:
        return '<option value="" disabled selected>No available targets</option>'
    return "".join(
        f'<option value="{escape(value)}">'
        f"{escape(_guided_target_display_label(value))}</option>"
        for value in values
    )


def _relationship_coverage(
    target_options: dict[str, list[str]],
    relationships: list[dict[str, Any]],
) -> dict[str, Any]:
    available = {
        target_type: set(values) for target_type, values in target_options.items()
    }
    linked = {target_type: set() for target_type in available}
    for relationship in relationships:
        target_type = str(relationship.get("target_type") or "")
        target_key = str(relationship.get("target_key") or "")
        if target_key in available.get(target_type, set()):
            linked.setdefault(target_type, set()).add(target_key)

    counts = {}
    total_available = 0
    total_linked = 0
    for target_type in ("condition", "signal", "finding", "record"):
        available_values = available.get(target_type, set())
        linked_values = linked.get(target_type, set())
        counts[target_type] = {
            "linked": len(linked_values),
            "total": len(available_values),
            "unlinked": [
                value
                for value in target_options.get(target_type, [])
                if value not in linked_values
            ],
        }
        total_available += len(available_values)
        total_linked += len(linked_values)

    if not relationships:
        status = "Unlinked"
    elif total_available > 0 and total_linked == total_available:
        status = "Complete"
    else:
        status = "Partial"

    return {
        "status": status,
        "counts": counts,
        "total_available": total_available,
        "total_linked": total_linked,
    }


def _relationship_coverage_reason(coverage: dict[str, Any]) -> str:
    status = coverage["status"]
    counts = coverage["counts"]
    if status == "Unlinked":
        return "No active evidence relationships have been created."
    if status == "Complete":
        return "All available targets are linked."

    incomplete = [
        target_type
        for target_type in ("condition", "signal", "finding", "record")
        if counts[target_type]["linked"] < counts[target_type]["total"]
    ]
    conditions_complete = (
        counts["condition"]["total"] > 0
        and counts["condition"]["linked"] == counts["condition"]["total"]
    )
    if conditions_complete and any(
        target_type in incomplete for target_type in ("signal", "finding", "record")
    ):
        return (
            "Conditions complete. Signals, findings, or record targets remain unlinked."
        )

    reasons = {
        "condition": "Conditions remain unlinked.",
        "signal": "Signals remain unlinked.",
        "finding": "Findings remain unlinked.",
        "record": "Record targets remain unlinked.",
    }
    return " ".join(reasons[target_type] for target_type in incomplete)


def _render_relationship_coverage(
    target_options: dict[str, list[str]],
    relationships: list[dict[str, Any]],
) -> str:
    coverage = _relationship_coverage(target_options, relationships)
    reason = _relationship_coverage_reason(coverage)
    labels = {
        "condition": "Conditions",
        "signal": "Signals",
        "finding": "Findings",
        "record": "Records",
    }
    rows = []
    for target_type in ("condition", "signal", "finding", "record"):
        count = coverage["counts"][target_type]
        rows.append(
            "<tr>"
            f"<td>{labels[target_type]} linked</td>"
            f"<td>{count['linked']} / {count['total']}</td>"
            "</tr>"
        )

    unlinked_conditions = coverage["counts"]["condition"]["unlinked"]
    if unlinked_conditions:
        unlinked_items = "".join(
            f"<li>{escape(_guided_target_display_label(value))}</li>"
            for value in unlinked_conditions
        )
        unlinked_html = f"""
          <div class="coverage-unlinked">
            <h4>Unlinked Conditions</h4>
            <ul>{unlinked_items}</ul>
          </div>"""
    else:
        unlinked_html = ""

    return f"""
          <section class="relationship-coverage">
            <h4>Evidence Coverage</h4>
            <p><strong>Status:</strong> {escape(coverage["status"])}</p>
            <p><strong>Reason:</strong> {escape(reason)}</p>
            <table>
              <tbody>{"".join(rows)}</tbody>
            </table>
            {unlinked_html}
          </section>"""


def _render_admin_attachment_rows(
    attachments: list[dict[str, Any]],
    *,
    relationship_target_options: dict[str, list[str]],
) -> str:
    if not attachments:
        return """
      <p>No attachments are currently associated with this record.</p>"""

    cards = []
    for index, attachment in enumerate(attachments):
        state = _attachment_state(attachment)
        attachment_id = attachment.get("attachment_id")
        reference = attachment.get("reference")
        current_classification = attachment.get("classification") or "other"
        current_publication_status = attachment.get("publication_status") or "internal"
        current_visibility = attachment.get("visibility") or "private"
        summary_title = (
            attachment.get("title") or attachment.get("filename") or "Attachment"
        )
        summary_meta = (
            f"{current_classification} • "
            f"{state} • {current_visibility} • "
            f"{attachment.get('redaction_status') or 'unknown redaction'} • "
            f"{current_publication_status}"
        )
        summary_time = _format_admin_timestamp(attachment.get("uploaded_at"))
        rows = (
            ("Record version", attachment.get("record_version")),
            ("Title", attachment.get("title")),
            ("Description", attachment.get("description")),
            ("Source label", attachment.get("source_label")),
            ("Classification", attachment.get("classification") or "other"),
            ("Publication status", current_publication_status),
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
        classification_options = "".join(
            "<option "
            f'value="{escape(option)}"'
            f"{' selected' if option == current_classification else ''}>"
            f"{escape(option)}</option>"
            for option in ATTACHMENT_CLASSIFICATION_OPTIONS
        )
        classification_action = (
            f"/api/admin/session/records/{escape(str(reference))}/attachments/"
            f"{escape(str(attachment_id))}/classification"
        )
        publication_status_options = "".join(
            "<option "
            f'value="{escape(option)}"'
            f"{' selected' if option == current_publication_status else ''}>"
            f"{escape(option)}</option>"
            for option in ATTACHMENT_PUBLICATION_STATUS_OPTIONS
        )
        publication_action = (
            f"/api/admin/session/records/{escape(str(reference))}/attachments/"
            f"{escape(str(attachment_id))}/publication"
        )
        visibility_options = "".join(
            "<option "
            f'value="{escape(option)}"'
            f"{' selected' if option == current_visibility else ''}>"
            f"{escape(option)}</option>"
            for option in ATTACHMENT_VISIBILITY_OPTIONS
        )
        visibility_action = (
            f"/api/admin/session/records/{escape(str(reference))}/attachments/"
            f"{escape(str(attachment_id))}/visibility"
        )
        relationship_action = (
            f"/api/admin/session/records/{escape(str(reference))}/attachments/"
            f"{escape(str(attachment_id))}/relationships"
        )
        relationships = attachment.get("active_relationships") or []
        relationship_count = len(relationships)
        relationship_coverage = _render_relationship_coverage(
            relationship_target_options,
            relationships,
        )
        relationship_rows = _render_attachment_relationships(
            relationships,
            reference=str(reference),
            attachment_id=str(attachment_id),
        )
        relationship_type_options = "".join(
            f'<option value="{escape(option)}">{escape(option)}</option>'
            for option in ATTACHMENT_RELATIONSHIP_TYPE_OPTIONS
        )
        relationship_target_type_options = "".join(
            f'<option value="{escape(option)}">{escape(option)}</option>'
            for option in ATTACHMENT_RELATIONSHIP_TARGET_TYPE_OPTIONS
        )
        target_key_options = _render_target_key_options(
            relationship_target_options,
            "condition",
        )
        relationship_submit_disabled = (
            " disabled" if not relationship_target_options.get("condition") else ""
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
        <form class="attachment-metadata-update-form classification-update-form"
              data-classification-update-form
              data-json-field="classification"
              action="{classification_action}"
              method="post"
              data-method="PATCH">
          <p class="classification-update-note">
            Controlled administrative metadata action only. No upload, download, or public mutation is available here.
          </p>
          <label>
            Classification
            <select name="classification" required>
              {classification_options}
            </select>
          </label>
          <button type="submit">Update classification</button>
        </form>
        <form class="attachment-metadata-update-form publication-update-form"
              data-publication-update-form
              data-json-field="publication_status"
              action="{publication_action}"
              method="post"
              data-method="PATCH">
          <p class="publication-update-note">
            Controlled administrative metadata/publication workflow action only. No upload or download is available here.
          </p>
          <label>
            Publication status
            <select name="publication_status" required>
              {publication_status_options}
            </select>
          </label>
          <button type="submit">Update publication</button>
        </form>
        <form class="attachment-metadata-update-form visibility-update-form"
              data-visibility-update-form
              data-json-field="visibility"
              action="{visibility_action}"
              method="post"
              data-method="PATCH">
          <p class="visibility-update-note">
            Controlled administrative visibility workflow action only. No upload or download is available here.
          </p>
          <label>
            Visibility
            <select name="visibility" required>
              {visibility_options}
            </select>
          </label>
          <button type="submit">Update visibility</button>
        </form>
        <section class="evidence-relationships">
          <h3>Evidence Relationships ({relationship_count})</h3>
          {relationship_coverage}
          {relationship_rows}
          <form class="attachment-relationship-form"
                data-relationship-add-form
                action="{relationship_action}"
                method="post">
            <p class="relationship-update-note">
              Controlled administrative evidence-linking action only. No upload or download is available here.
            </p>
            <label>
              Relationship type
              <select name="relationship_type" required>
                {relationship_type_options}
              </select>
            </label>
            <label>
              Target type
              <select name="target_type" required>
                {relationship_target_type_options}
              </select>
            </label>
            <label>
              Target key
              <select name="target_key" required data-target-key-select>
                {target_key_options}
              </select>
            </label>
            <button type="submit" data-relationship-submit{relationship_submit_disabled}>Add relationship</button>
          </form>
        </section>
      </details>""")

    return "".join(cards)


def _render_attachment_relationships(
    relationships: list[dict[str, Any]], *, reference: str, attachment_id: str
) -> str:
    if not relationships:
        return (
            '<p class="relationship-empty-state">No active evidence relationships.</p>'
        )

    grouped = {
        "condition": [],
        "signal": [],
        "finding": [],
        "record": [],
    }
    for relationship in relationships:
        target_type = str(relationship.get("target_type") or "")
        grouped.setdefault(target_type, []).append(relationship)

    group_labels = {
        "condition": "Conditions",
        "signal": "Signals",
        "finding": "Findings",
        "record": "Records",
    }
    groups = []
    for target_type in ("condition", "signal", "finding", "record"):
        group_relationships = grouped.get(target_type) or []
        if not group_relationships:
            continue
        items = []
        for relationship in group_relationships:
            items.append(
                _render_attachment_relationship_card(
                    relationship,
                    reference=reference,
                    attachment_id=attachment_id,
                )
            )
        open_attr = " open" if target_type == "condition" else ""
        groups.append(f"""
          <details class="relationship-group relationship-group-{escape(target_type)}"{open_attr}>
            <summary>{group_labels[target_type]} ({len(group_relationships)})</summary>
            <ul class="relationship-list">{"".join(items)}</ul>
          </details>""")

    return "".join(groups)


def _render_attachment_relationship_card(
    relationship: dict[str, Any], *, reference: str, attachment_id: str
) -> str:
    relationship_id = relationship.get("relationship_id")
    relationship_type = str(relationship.get("relationship_type") or "")
    target_type = str(relationship.get("target_type") or "")
    target_key = str(relationship.get("target_key") or "")
    target_label = _guided_target_display_label(target_key)
    remove_action = (
        f"/api/admin/session/records/{escape(reference)}/attachments/"
        f"{escape(attachment_id)}/relationships/{escape(str(relationship_id))}/remove"
    )
    return f"""
          <li class="relationship-card"
              data-target-key="{escape(target_key)}">
            <div class="relationship-meta">
              {escape(relationship_type)} • {escape(target_type)}
            </div>
            <div class="relationship-target">
              → {escape(target_label)}
            </div>
            <form class="relationship-remove-form"
                  data-relationship-remove-form
                  data-target-key="{escape(target_key)}"
                  action="{remove_action}"
                  method="post"
                  data-method="PATCH">
              <button type="submit">Remove relationship</button>
            </form>
          </li>"""


def _attach_relationship_lineage_metadata(
    conn: sqlite3.Connection,
    *,
    reference: str,
    attachments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    for attachment in attachments:
        attachment["all_relationships"] = list_attachment_relationships(
            conn,
            reference=reference,
            attachment_id=int(attachment.get("attachment_id") or 0),
            active_only=False,
        )
    return attachments


def _record_evidence_groups(
    record: sqlite3.Row,
    attachments: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    target_options = _record_relationship_target_options(record)
    groups = {
        target_type: [
            {
                "target_key": target_key,
                "target_label": _guided_target_display_label(target_key),
                "attachments": [],
                "relationship_count": 0,
                "relationship_type_counts": {},
                "relationship_traces": [],
                "relationship_lineage_events": [],
                "_attachment_lookup": {},
            }
            for target_key in target_options.get(target_type, [])
        ]
        for target_type in ("condition", "signal", "finding", "record")
    }
    target_lookup = {
        (target_type, target["target_key"]): target
        for target_type, targets in groups.items()
        for target in targets
    }

    for attachment in attachments:
        if _attachment_state(attachment) != "active":
            continue
        supporting_attachment = _evidence_supporting_attachment_metadata(attachment)
        linked_targets = set()
        for relationship in attachment.get("active_relationships") or []:
            target_type = str(relationship.get("target_type") or "")
            target_key = str(relationship.get("target_key") or "")
            relationship_type = str(relationship.get("relationship_type") or "")
            target_identity = (target_type, target_key)
            target = target_lookup.get(target_identity)
            if not target:
                continue
            target["relationship_count"] += 1
            target["relationship_type_counts"][relationship_type] = (
                target["relationship_type_counts"].get(relationship_type, 0) + 1
            )
            target["relationship_traces"].append(
                {
                    "relationship_type": relationship_type,
                    "target_type": target_type,
                    "target_key": target_key,
                    "target_label": _guided_target_display_label(target_key),
                    "attachment_id": supporting_attachment.get("attachment_id"),
                    "attachment_title": supporting_attachment.get("title")
                    or "Untitled attachment",
                    "created_at": relationship.get("created_at"),
                    "created_by": relationship.get("created_by"),
                }
            )
            attachment_id = supporting_attachment.get("attachment_id")
            target_attachment = target["_attachment_lookup"].get(attachment_id)
            if not target_attachment:
                target_attachment = dict(supporting_attachment)
                target_attachment["relationship_type_counts"] = {}
                target["_attachment_lookup"][attachment_id] = target_attachment
                target["attachments"].append(target_attachment)
                linked_targets.add(target_identity)
            target_attachment["relationship_type_counts"][relationship_type] = (
                target_attachment["relationship_type_counts"].get(relationship_type, 0)
                + 1
            )
        for relationship in attachment.get("all_relationships") or []:
            target_type = str(relationship.get("target_type") or "")
            target_key = str(relationship.get("target_key") or "")
            relationship_type = str(relationship.get("relationship_type") or "")
            if relationship_type != "supports":
                continue
            target = target_lookup.get((target_type, target_key))
            if not target:
                continue
            is_active = int(relationship.get("is_active") or 0) == 1
            target["relationship_lineage_events"].append(
                {
                    "relationship_type": relationship_type,
                    "target_type": target_type,
                    "target_key": target_key,
                    "target_label": _guided_target_display_label(target_key),
                    "attachment_id": supporting_attachment.get("attachment_id"),
                    "attachment_title": supporting_attachment.get("title")
                    or "Untitled attachment",
                    "is_active": is_active,
                    "state": "active" if is_active else "removed",
                    "created_at": relationship.get("created_at"),
                    "created_by": relationship.get("created_by"),
                    "removed_at": relationship.get("removed_at"),
                    "removed_by": relationship.get("removed_by"),
                }
            )

    for targets in groups.values():
        for target in targets:
            target["relationship_lineage_events"].sort(
                key=lambda event: (
                    str(event.get("created_at") or ""),
                    str(event.get("attachment_id") or ""),
                    str(event.get("relationship_type") or ""),
                    str(event.get("target_key") or ""),
                )
            )
            target.pop("_attachment_lookup", None)

    return groups


def _evidence_supporting_attachment_metadata(
    attachment: dict[str, Any],
) -> dict[str, Any]:
    return {
        "attachment_id": attachment.get("attachment_id"),
        "title": attachment.get("title"),
        "classification": attachment.get("classification") or "other",
        "publication_status": attachment.get("publication_status") or "internal",
        "visibility": attachment.get("visibility"),
        "redaction_status": attachment.get("redaction_status"),
        "lifecycle_state": _attachment_state(attachment),
        "source_label": attachment.get("source_label"),
        "document_date": attachment.get("document_date"),
        "uploaded_at": attachment.get("uploaded_at"),
        "sha256_hash": attachment.get("sha256_hash"),
    }


def _render_record_evidence_groups(
    evidence_groups: dict[str, list[dict[str, Any]]],
) -> str:
    section_labels = {
        "condition": "Conditions",
        "signal": "Signals",
        "finding": "Findings",
        "record": "Record",
    }
    sections = []
    for target_type in ("condition", "signal", "finding", "record"):
        targets = evidence_groups.get(target_type) or []
        target_rows = []
        for target in targets:
            supporting_attachments = target.get("attachments") or []
            attachment_count = len(supporting_attachments)
            relationship_count = int(target.get("relationship_count") or 0)
            support_status = "Supported" if attachment_count else "Unsupported"
            evidence_gap = (
                "Yes" if attachment_count == 0 and relationship_count == 0 else "No"
            )
            if supporting_attachments:
                attachment_items = "".join(
                    _render_record_evidence_attachment(attachment)
                    for attachment in supporting_attachments
                )
                supporting_html = (
                    '<ul class="supporting-attachment-list">' f"{attachment_items}</ul>"
                )
            else:
                supporting_html = (
                    '<p class="evidence-empty-state">'
                    "No supporting attachments linked.</p>"
                )
            target_rows.append(f"""
          <details class="evidence-target evidence-target-{escape(target_type)}">
            <summary>
              <span class="summary-title">{escape(str(target["target_label"]))}</span>
              <span class="summary-meta">Evidence Gap: {evidence_gap}</span>
              <span class="summary-meta">Coverage: {support_status}</span>
              <span class="summary-meta">{attachment_count} supporting attachment{'s' if attachment_count != 1 else ''}</span>
              <span class="summary-meta">{relationship_count} supporting relationship{'s' if relationship_count != 1 else ''}</span>
            </summary>
            {_render_record_evidence_support_detail(target)}
            {supporting_html}
          </details>""")

        if not target_rows:
            target_rows.append(
                '<p class="evidence-empty-state">No record targets are available.</p>'
            )

        open_attr = " open" if target_type == "condition" else ""
        sections.append(f"""
      <details class="evidence-section evidence-section-{escape(target_type)}"{open_attr}>
        <summary>{section_labels[target_type]}</summary>
        {"".join(target_rows)}
      </details>""")

    return "".join(sections)


def _ordered_relationship_type_counts(counts: dict[str, int]) -> list[tuple[str, int]]:
    ordered = []
    seen = set()
    for relationship_type in ATTACHMENT_RELATIONSHIP_TYPE_OPTIONS:
        if relationship_type in counts:
            ordered.append((relationship_type, counts[relationship_type]))
            seen.add(relationship_type)
    for relationship_type in sorted(set(counts) - seen):
        ordered.append((relationship_type, counts[relationship_type]))
    return ordered


def _render_relationship_type_count_list(
    counts: dict[str, int],
    *,
    include_single_counts: bool,
) -> str:
    if not counts:
        return '<p class="evidence-empty-state">No active relationship types.</p>'
    items = []
    for relationship_type, count in _ordered_relationship_type_counts(counts):
        label = (
            f"{relationship_type}: {count}"
            if include_single_counts or count != 1
            else relationship_type
        )
        items.append(f"<li>{escape(label)}</li>")
    return f'<ul class="relationship-type-counts">{"".join(items)}</ul>'


def _record_evidence_rationale(target: dict[str, Any]) -> str:
    relationship_count = int(target.get("relationship_count") or 0)
    attachments = target.get("attachments") or []
    if relationship_count == 0:
        return "No active attachment relationships support this target."
    if relationship_count == 1 and len(attachments) == 1:
        return (
            f"Supported because Attachment {attachments[0].get('attachment_id')} "
            "supports this target."
        )
    relationship_label = (
        "relationship" if relationship_count == 1 else "relationships"
    )
    return (
        f"Supported because {relationship_count} active attachment "
        f"{relationship_label} support this target."
    )


def _render_record_evidence_support_detail(target: dict[str, Any]) -> str:
    if int(target.get("relationship_count") or 0) == 0:
        return """
            <section class="evidence-support-detail">
              <p><strong>Gap rationale:</strong> No active attachment relationships support this target.</p>
              <h4>Relationship Types</h4>
              <p class="evidence-empty-state">No active relationship types.</p>
            </section>"""

    return f"""
            <section class="evidence-support-detail">
              <p><strong>Coverage rationale:</strong> {escape(_record_evidence_rationale(target))}</p>
              <h4>Relationship Types</h4>
              {_render_relationship_type_count_list(
                  target.get("relationship_type_counts") or {},
                  include_single_counts=True,
              )}
              {_render_record_evidence_relationship_trace(target)}
            </section>"""


def _render_record_evidence_relationship_trace(target: dict[str, Any]) -> str:
    traces = target.get("relationship_traces") or []
    if not traces:
        return """
              <section class="relationship-trace">
                <h4>Relationship Trace</h4>
                <p class="evidence-empty-state">No active relationships support this target.</p>
              </section>"""

    items = []
    for trace in traces:
        relationship_type = str(trace.get("relationship_type") or "")
        target_type = str(trace.get("target_type") or "")
        target_key = str(trace.get("target_key") or "")
        target_label = str(trace.get("target_label") or target_key)
        attachment_id = trace.get("attachment_id")
        attachment_title = trace.get("attachment_title") or "Untitled attachment"
        items.append(f"""
                <li class="relationship-trace-entry">
                  <div class="relationship-trace-path">
                    {escape(relationship_type)} → {escape(target_type)} → {escape(target_label)}
                  </div>
                  <dl class="relationship-trace-fields">
                    <dt>Relationship Type</dt>
                    <dd>{escape(relationship_type)}</dd>
                    <dt>Target Type</dt>
                    <dd>{escape(target_type)}</dd>
                    <dt>Target Key</dt>
                    <dd>{escape(target_label)}</dd>
                    <dt>Attachment Identifier</dt>
                    <dd>{escape(str(attachment_id))}</dd>
                    <dt>Attachment Title</dt>
                    <dd>{escape(str(attachment_title))}</dd>
                  </dl>
                  <div class="relationship-trace-attachment">
                    Attachment {escape(str(attachment_id))} — {escape(str(attachment_title))}
                  </div>
                </li>""")

    return f"""
              <section class="relationship-trace">
                <h4>Relationship Trace</h4>
                <ul class="relationship-trace-list">{"".join(items)}</ul>
              </section>"""


def _target_type_display_label(target_type: str) -> str:
    labels = {
        "condition": "Condition",
        "signal": "Signal",
        "finding": "Finding",
        "record": "Record",
    }
    return labels.get(target_type, target_type.title())


def _record_evidence_gap_summary(
    evidence_groups: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    supported_targets = 0
    unsupported_targets = 0
    gap_counts = {}
    outstanding_gaps = []
    for target_type in ("condition", "signal", "finding", "record"):
        targets = evidence_groups.get(target_type) or []
        gap_count = 0
        for target in targets:
            attachment_count = len(target.get("attachments") or [])
            relationship_count = int(target.get("relationship_count") or 0)
            is_gap = attachment_count == 0 and relationship_count == 0
            if is_gap:
                unsupported_targets += 1
                gap_count += 1
                outstanding_gaps.append(
                    {
                        "target_type": target_type,
                        "target_label": target.get("target_label")
                        or target.get("target_key")
                        or "",
                    }
                )
            else:
                supported_targets += 1
        gap_counts[target_type] = gap_count

    total_targets = supported_targets + unsupported_targets
    coverage_percentage = (
        (supported_targets / total_targets) * 100 if total_targets else 0.0
    )
    return {
        "supported_targets": supported_targets,
        "unsupported_targets": unsupported_targets,
        "evidence_gap_count": unsupported_targets,
        "coverage_percentage": coverage_percentage,
        "gap_counts": gap_counts,
        "outstanding_gaps": outstanding_gaps,
    }


def _render_record_evidence_gap_summary(
    evidence_groups: dict[str, list[dict[str, Any]]],
) -> str:
    summary = _record_evidence_gap_summary(evidence_groups)
    gap_rows = (
        ("Supported Targets", summary["supported_targets"]),
        ("Unsupported Targets", summary["unsupported_targets"]),
        ("Evidence Gap Count", summary["evidence_gap_count"]),
        ("Coverage Percentage", f"{summary['coverage_percentage']:.1f}%"),
        ("Condition Gaps", summary["gap_counts"]["condition"]),
        ("Signal Gaps", summary["gap_counts"]["signal"]),
        ("Finding Gaps", summary["gap_counts"]["finding"]),
        ("Record Gaps", summary["gap_counts"]["record"]),
    )
    table_rows = "".join(
        "<tr>"
        f"<td>{escape(str(label))}</td>"
        f"<td>{escape(str(value))}</td>"
        "</tr>"
        for label, value in gap_rows
    )
    if summary["outstanding_gaps"]:
        gap_items = "".join(
            "<li>"
            f"{escape(_target_type_display_label(str(gap['target_type'])))} — "
            f"{escape(str(gap['target_label']))}"
            "</li>"
            for gap in summary["outstanding_gaps"]
        )
        outstanding_html = f"""
        <h3>Outstanding Gaps</h3>
        <ul class="outstanding-gap-list">{gap_items}</ul>"""
    else:
        outstanding_html = """
        <h3>Outstanding Gaps</h3>
        <p class="evidence-empty-state">No outstanding evidence gaps.</p>"""

    return f"""
      <section class="management-section evidence-gap-summary">
        <h2>Evidence Gap Summary</h2>
        <table>
          <tbody>{table_rows}</tbody>
        </table>
        {outstanding_html}
      </section>"""


def classify_evidence_sufficiency(
    supporting_attachment_count: int,
    supporting_relationship_count: int,
) -> str:
    if supporting_attachment_count == 0 and supporting_relationship_count == 0:
        return "Unsupported"
    if supporting_attachment_count >= 2:
        return "Corroborated"
    if supporting_attachment_count == 1 and supporting_relationship_count >= 2:
        return "Reinforced"
    if supporting_attachment_count > 0 or supporting_relationship_count > 0:
        return "Minimal"
    return "Unsupported"


def classify_evidence_readiness(
    supported_target_count: int,
    unsupported_target_count: int,
    evidence_gap_count: int,
    sufficiency_classifications: list[str],
) -> str:
    normalized = [str(value) for value in sufficiency_classifications]
    if supported_target_count == 0 and normalized and all(
        value == "Unsupported" for value in normalized
    ):
        return "Unsupported"
    if evidence_gap_count > 0 and unsupported_target_count > 0:
        return "Evidence Gaps Present"
    if (
        evidence_gap_count == 0
        and unsupported_target_count == 0
        and "Unsupported" not in normalized
        and any(value in {"Corroborated", "Reinforced"} for value in normalized)
    ):
        return "Ready"
    if (
        supported_target_count > 0
        and evidence_gap_count == 0
        and unsupported_target_count == 0
        and "Unsupported" not in normalized
    ):
        return "Partially Ready"
    if evidence_gap_count > 0:
        return "Evidence Gaps Present"
    return "Partially Ready" if supported_target_count > 0 else "Unsupported"


def _evidence_sufficiency_classifications(
    evidence_groups: dict[str, list[dict[str, Any]]],
) -> list[str]:
    classifications = []
    for target_type in ("condition", "signal", "finding", "record"):
        for target in evidence_groups.get(target_type) or []:
            classifications.append(
                classify_evidence_sufficiency(
                    len(target.get("attachments") or []),
                    int(target.get("relationship_count") or 0),
                )
            )
    return classifications


def _summarize_sufficiency_basis(classifications: list[str]) -> str:
    order = ("Unsupported", "Minimal", "Corroborated", "Reinforced")
    parts = [
        f"{classifications.count(classification)} {classification}"
        for classification in order
        if classifications.count(classification)
    ]
    return ", ".join(parts) if parts else "No record targets"


def _readiness_badge_class(readiness: str) -> str:
    return {
        "Ready": "readiness-ready",
        "Partially Ready": "readiness-partially-ready",
        "Evidence Gaps Present": "readiness-gaps-present",
        "Unsupported": "readiness-unsupported",
    }.get(readiness, "readiness-unsupported")


def classify_administrative_action(readiness_classification: str) -> str:
    return {
        "Unsupported": "Collect Initial Evidence",
        "Evidence Gaps Present": "Resolve Evidence Gaps",
        "Partially Ready": "Proceed to Administrative Review",
        "Ready": "Eligible for Formal Review",
    }.get(readiness_classification, "Resolve Evidence Gaps")


def describe_administrative_action_basis(
    readiness_classification: str,
    supported_target_count: int,
    unsupported_target_count: int,
    evidence_gap_count: int,
) -> str:
    if readiness_classification == "Unsupported":
        return (
            "Administrative action is Collect Initial Evidence because no "
            "targets are currently supported."
        )
    if readiness_classification == "Evidence Gaps Present":
        return (
            "Administrative action is Resolve Evidence Gaps because "
            "unsupported targets or evidence gaps remain."
        )
    if readiness_classification == "Partially Ready":
        return (
            "Administrative action is Proceed to Administrative Review because "
            "all targets are supported but sufficiency remains minimal."
        )
    if readiness_classification == "Ready":
        return (
            "Administrative action is Eligible for Formal Review because the "
            "record has no evidence gaps and includes corroborated or "
            "reinforced support."
        )
    if supported_target_count == 0:
        return (
            "Administrative action is Collect Initial Evidence because no "
            "targets are currently supported."
        )
    if unsupported_target_count > 0 or evidence_gap_count > 0:
        return (
            "Administrative action is Resolve Evidence Gaps because "
            "unsupported targets or evidence gaps remain."
        )
    return (
        "Administrative action is Proceed to Administrative Review because "
        "all targets are supported but sufficiency remains minimal."
    )


def build_action_rationale_trace(
    readiness_classification: str,
    administrative_action: str,
    supported_target_count: int,
    unsupported_target_count: int,
    evidence_gap_count: int,
) -> list[str]:
    if readiness_classification == "Unsupported":
        return [
            "Readiness classified as Unsupported",
            "No supported targets identified",
            f"Administrative action classified as {administrative_action}",
        ]
    if readiness_classification == "Evidence Gaps Present":
        steps = ["Readiness classified as Evidence Gaps Present"]
        if unsupported_target_count > 0:
            steps.append("Unsupported targets remain")
        if evidence_gap_count > 0:
            steps.append("Evidence gaps remain")
        steps.append(f"Administrative action classified as {administrative_action}")
        return steps
    if readiness_classification == "Partially Ready":
        return [
            "Readiness classified as Partially Ready",
            "All targets currently supported",
            "Support remains minimal",
            f"Administrative action classified as {administrative_action}",
        ]
    if readiness_classification == "Ready":
        return [
            "Readiness classified as Ready",
            "No unsupported targets remain",
            "No evidence gaps remain",
            "Corroborated or reinforced support identified",
            f"Administrative action classified as {administrative_action}",
        ]
    steps = [f"Readiness classified as {readiness_classification}"]
    if supported_target_count == 0:
        steps.append("No supported targets identified")
    if unsupported_target_count > 0:
        steps.append("Unsupported targets remain")
    if evidence_gap_count > 0:
        steps.append("Evidence gaps remain")
    steps.append(f"Administrative action classified as {administrative_action}")
    return steps


def build_completion_requirements(
    readiness_classification: str,
    administrative_action: str,
    supported_target_count: int,
    unsupported_target_count: int,
    evidence_gap_count: int,
    sufficiency_classifications: list[str],
) -> list[str]:
    if readiness_classification == "Unsupported":
        return [
            "At least one target must become supported.",
            "Evidence support must be established.",
        ]
    if readiness_classification == "Evidence Gaps Present":
        requirements = []
        if unsupported_target_count > 0:
            requirements.append("Unsupported targets must be resolved.")
        if evidence_gap_count > 0:
            requirements.append("Evidence gaps must be resolved.")
        return requirements or ["Evidence gaps must be resolved."]
    if readiness_classification == "Partially Ready":
        return [
            "At least one target must achieve corroborated or reinforced support.",
        ]
    if readiness_classification == "Ready":
        return ["No additional evidence requirements identified."]
    if supported_target_count == 0:
        return [
            "At least one target must become supported.",
            "Evidence support must be established.",
        ]
    if (
        unsupported_target_count == 0
        and evidence_gap_count == 0
        and all(value == "Minimal" for value in sufficiency_classifications)
    ):
        return [
            "At least one target must achieve corroborated or reinforced support.",
        ]
    return [
        f"Administrative action {administrative_action} must be resolved through current evidence requirements.",
    ]


def classify_workflow_state(
    readiness_classification: str,
    administrative_action: str,
) -> str:
    return {
        "Unsupported": "Evidence Collection",
        "Evidence Gaps Present": "Evidence Review",
        "Partially Ready": "Administrative Review",
        "Ready": "Formal Review Ready",
    }.get(readiness_classification, "Evidence Review")


def describe_workflow_state(workflow_state: str) -> str:
    return {
        "Evidence Collection": "Evidence support is still being established.",
        "Evidence Review": "Evidence has been collected but gaps remain.",
        "Administrative Review": (
            "Evidence support is complete but remains minimally supported."
        ),
        "Formal Review Ready": (
            "Evidence requirements have been satisfied for formal review."
        ),
    }.get(workflow_state, "Evidence has been collected but gaps remain.")


def describe_transition_target(workflow_state: str) -> str:
    return {
        "Evidence Collection": "Evidence Review",
        "Evidence Review": "Administrative Review",
        "Administrative Review": "Formal Review Ready",
        "Formal Review Ready": "No further workflow state identified",
    }.get(workflow_state, "Evidence Review")


def build_transition_conditions(
    workflow_state: str,
    readiness_classification: str,
    administrative_action: str,
    completion_requirements: list[str],
) -> list[str]:
    if workflow_state == "Evidence Collection":
        return [
            "At least one target must become supported.",
            "Evidence support must be established.",
            "Workflow state may advance to Evidence Review.",
        ]
    if workflow_state == "Evidence Review":
        conditions = [
            requirement
            for requirement in completion_requirements
            if requirement
            in {
                "Unsupported targets must be resolved.",
                "Evidence gaps must be resolved.",
            }
        ]
        if not conditions:
            conditions = [
                "Unsupported targets must be resolved.",
                "Evidence gaps must be resolved.",
            ]
        conditions.append("Workflow state may advance to Administrative Review.")
        return conditions
    if workflow_state == "Administrative Review":
        return [
            "Corroborated or reinforced support must be identified.",
            "Workflow state may advance to Formal Review Ready.",
        ]
    if workflow_state == "Formal Review Ready":
        return ["No additional workflow transition conditions identified."]
    return [
        f"Workflow state {workflow_state} must satisfy {administrative_action} requirements.",
        f"Readiness classification remains {readiness_classification}.",
    ]


def classify_administrative_disposition(workflow_state: str) -> str:
    return {
        "Evidence Collection": "Open",
        "Evidence Review": "Open",
        "Administrative Review": "Pending Review",
        "Formal Review Ready": "Ready for Review",
    }.get(workflow_state, "Open")


def describe_administrative_disposition(disposition: str) -> str:
    return {
        "Open": "The record remains within active evidence workflow.",
        "Pending Review": (
            "The record has satisfied evidence workflow requirements and "
            "awaits administrative review."
        ),
        "Ready for Review": (
            "The record satisfies current workflow requirements for formal review."
        ),
    }.get(disposition, "The record remains within active evidence workflow.")


def build_disposition_basis_trace(
    disposition: str,
    workflow_state: str,
    readiness_classification: str,
    administrative_action: str,
) -> list[str]:
    if disposition == "Pending Review":
        return [
            f"Workflow state classified as {workflow_state}.",
            "Administrative disposition classified as Pending Review.",
        ]
    if disposition == "Ready for Review":
        return [
            f"Workflow state classified as {workflow_state}.",
            "Administrative disposition classified as Ready for Review.",
        ]
    return [
        f"Workflow state classified as {workflow_state}.",
        f"Readiness classified as {readiness_classification}.",
        f"Administrative action classified as {administrative_action}.",
        "Administrative disposition classified as Open.",
    ]


def classify_review_eligibility(disposition: str) -> str:
    return {
        "Open": "Not Eligible",
        "Pending Review": "Conditionally Eligible",
        "Ready for Review": "Eligible",
    }.get(disposition, "Not Eligible")


def describe_review_eligibility(eligibility: str) -> str:
    return {
        "Not Eligible": "The record has not yet satisfied review requirements.",
        "Conditionally Eligible": (
            "The record may proceed to review subject to administrative assessment."
        ),
        "Eligible": "The record satisfies current requirements for review.",
    }.get(eligibility, "The record has not yet satisfied review requirements.")


def build_review_preconditions(
    review_eligibility: str,
    disposition: str,
    workflow_state: str,
    transition_conditions: list[str],
) -> list[str]:
    if review_eligibility == "Eligible":
        return ["No additional review preconditions identified."]
    if review_eligibility == "Conditionally Eligible":
        return [
            "Administrative review requirements must be satisfied.",
            "Review eligibility may advance to Eligible.",
        ]
    if review_eligibility == "Not Eligible":
        return [
            "Workflow transition conditions must be satisfied.",
            "Administrative disposition must advance beyond Open.",
            "Review eligibility may advance when workflow requirements are satisfied.",
        ]
    if disposition == "Ready for Review" or workflow_state == "Formal Review Ready":
        return ["No additional review preconditions identified."]
    if transition_conditions:
        return [
            "Workflow transition conditions must be satisfied.",
            "Review eligibility may advance when workflow requirements are satisfied.",
        ]
    return ["Review eligibility requirements must be satisfied."]


def describe_review_precondition_target(review_eligibility: str) -> str:
    return {
        "Not Eligible": "Conditionally Eligible",
        "Conditionally Eligible": "Eligible",
        "Eligible": "No further review eligibility state identified",
    }.get(review_eligibility, "Conditionally Eligible")


def build_administrative_status_summary(
    disposition: str,
    review_eligibility: str,
    workflow_state: str,
    readiness_classification: str,
) -> dict[str, str]:
    if disposition == "Ready for Review" or review_eligibility == "Eligible":
        return {
            "status": "Ready for Formal Review",
            "description": (
                "The record satisfies current administrative review requirements."
            ),
        }
    if (
        disposition == "Pending Review"
        or review_eligibility == "Conditionally Eligible"
    ):
        return {
            "status": "Pending Administrative Review",
            "description": (
                "The record may proceed to administrative review subject to "
                "assessment."
            ),
        }
    if (
        workflow_state == "Evidence Review"
        or readiness_classification == "Evidence Gaps Present"
    ):
        return {
            "status": "Active Evidence Review",
            "description": (
                "Evidence remains under review and review eligibility "
                "requirements have not yet been satisfied."
            ),
        }
    return {
        "status": "Active Evidence Collection",
        "description": (
            "Evidence support is still being established and review "
            "eligibility requirements have not yet been satisfied."
        ),
    }


def classify_implementation_action(administrative_status: str) -> str:
    return {
        "Active Evidence Collection": "No Implementation Action",
        "Active Evidence Review": "No Implementation Action",
        "Pending Administrative Review": "Await Review Determination",
        "Ready for Formal Review": "Prepare Formal Review Implementation",
    }.get(administrative_status, "No Implementation Action")


def describe_implementation_action(implementation_action: str) -> str:
    return {
        "No Implementation Action": (
            "No implementation action is available while evidence review "
            "remains active."
        ),
        "Await Review Determination": (
            "Implementation is deferred until administrative review produces "
            "a determination."
        ),
        "Prepare Formal Review Implementation": (
            "The record is ready for formal review implementation planning."
        ),
    }.get(
        implementation_action,
        "No implementation action is available while evidence review remains active.",
    )


def build_implementation_basis_trace(
    implementation_action: str,
    administrative_status: str,
    administrative_disposition: str,
    review_eligibility: str,
    workflow_state: str,
    readiness_classification: str,
) -> list[str]:
    return [
        f"Administrative status classified as {administrative_status}.",
        f"Administrative disposition classified as {administrative_disposition}.",
        f"Review eligibility classified as {review_eligibility}.",
        f"Workflow state classified as {workflow_state}.",
        f"Readiness classified as {readiness_classification}.",
        f"Implementation action classified as {implementation_action}.",
    ]


def classify_effective_state(
    implementation_action: str,
    administrative_status: str,
) -> str:
    if (
        implementation_action == "Prepare Formal Review Implementation"
        or administrative_status == "Ready for Formal Review"
    ):
        return "Formal Review Ready"
    if (
        implementation_action == "Await Review Determination"
        or administrative_status == "Pending Administrative Review"
    ):
        return "Administrative Review Pending"
    return "Evidence Review Continues"


def describe_effective_state(effective_state: str) -> str:
    return {
        "Evidence Review Continues": (
            "Evidence review remains active and no implementation action has "
            "been applied."
        ),
        "Administrative Review Pending": (
            "Administrative review remains pending before implementation can "
            "proceed."
        ),
        "Formal Review Ready": (
            "The record is ready for formal review implementation planning."
        ),
    }.get(
        effective_state,
        "Evidence review remains active and no implementation action has been applied.",
    )


def classify_outcome(effective_state: str) -> str:
    return {
        "Evidence Review Continues": "Ongoing Review",
        "Administrative Review Pending": "Review Awaiting Determination",
        "Formal Review Ready": "Ready For Determination",
    }.get(effective_state, "Ongoing Review")


def describe_outcome(outcome: str) -> str:
    return {
        "Ongoing Review": (
            "The record remains in ongoing review because evidence review continues."
        ),
        "Review Awaiting Determination": (
            "The record is awaiting an administrative review determination."
        ),
        "Ready For Determination": (
            "The record is ready for formal review determination."
        ),
    }.get(
        outcome,
        "The record remains in ongoing review because evidence review continues.",
    )


def build_outcome_basis_trace(
    outcome: str,
    effective_state: str,
    implementation_action: str,
    administrative_status: str,
) -> list[str]:
    return [
        f"Administrative status classified as {administrative_status}.",
        f"Implementation action classified as {implementation_action}.",
        f"Effective state classified as {effective_state}.",
        f"Outcome classified as {outcome}.",
    ]


def build_outcome_preconditions(
    outcome: str,
    effective_state: str,
    implementation_action: str,
    administrative_status: str,
    review_eligibility: str,
) -> list[str]:
    if outcome == "Ready For Determination":
        return [
            "Formal review determination may proceed.",
            "Outcome advancement depends on determination completion.",
        ]
    if outcome == "Review Awaiting Determination":
        return [
            "Administrative review determination must be completed.",
            "Outcome may advance when determination requirements are satisfied.",
        ]
    if outcome == "Ongoing Review":
        return [
            "Review eligibility requirements must be satisfied.",
            "Administrative disposition must advance beyond Open.",
            "Implementation action must advance beyond No Implementation Action.",
            "Effective state may advance when review conditions are satisfied.",
        ]
    if (
        effective_state == "Formal Review Ready"
        or implementation_action == "Prepare Formal Review Implementation"
        or administrative_status == "Ready for Formal Review"
        or review_eligibility == "Eligible"
    ):
        return [
            "Formal review determination may proceed.",
            "Outcome advancement depends on determination completion.",
        ]
    return [
        "Review eligibility requirements must be satisfied.",
        "Outcome may advance when review conditions are satisfied.",
    ]


def build_outcome_summary(
    outcome: str,
    outcome_basis: list[str],
    outcome_preconditions: list[str],
    effective_state: str,
    implementation_action: str,
    administrative_status: str,
) -> dict[str, str]:
    return {
        "outcome": outcome,
        "description": describe_outcome_summary(
            outcome,
            outcome_basis,
            outcome_preconditions,
            effective_state,
            implementation_action,
            administrative_status,
        ),
    }


def describe_outcome_summary(
    outcome: str,
    outcome_basis: list[str],
    outcome_preconditions: list[str],
    effective_state: str,
    implementation_action: str,
    administrative_status: str,
) -> str:
    if outcome == "Ready For Determination":
        return (
            "The record has satisfied review progression requirements and is "
            "ready for formal determination. Outcome advancement depends upon "
            "completion of the determination process."
        )
    if outcome == "Review Awaiting Determination":
        return (
            "The record has advanced beyond active evidence review and is "
            "awaiting administrative determination. Outcome advancement "
            "depends upon completion of the required review determination "
            "process."
        )
    if outcome == "Ongoing Review":
        return (
            "The record remains in ongoing review. Evidence review continues, "
            "no implementation action has been applied, and outcome "
            "advancement depends upon satisfaction of review eligibility and "
            "administrative progression requirements."
        )
    if (
        effective_state == "Formal Review Ready"
        or implementation_action == "Prepare Formal Review Implementation"
        or administrative_status == "Ready for Formal Review"
        or any("Formal review determination" in item for item in outcome_preconditions)
    ):
        return (
            "The record has satisfied review progression requirements and is "
            "ready for formal determination. Outcome advancement depends upon "
            "completion of the determination process."
        )
    if any("Administrative review determination" in item for item in outcome_basis):
        return (
            "The record has advanced beyond active evidence review and is "
            "awaiting administrative determination. Outcome advancement "
            "depends upon completion of the required review determination "
            "process."
        )
    return (
        "The record remains in ongoing review. Evidence review continues, no "
        "implementation action has been applied, and outcome advancement "
        "depends upon satisfaction of review eligibility and administrative "
        "progression requirements."
    )


def classify_outcome_readiness(
    outcome: str,
    outcome_preconditions: list[str],
    review_eligibility: str,
    administrative_status: str,
    effective_state: str,
) -> str:
    if outcome == "Ready For Determination" or review_eligibility == "Eligible":
        return "Ready"
    if (
        outcome == "Review Awaiting Determination"
        or review_eligibility == "Conditionally Eligible"
        or administrative_status == "Pending Administrative Review"
        or effective_state == "Administrative Review Pending"
    ):
        return "Conditionally Ready"
    if any("Formal review determination may proceed" in item for item in outcome_preconditions):
        return "Ready"
    return "Not Ready"


def describe_outcome_readiness(outcome_readiness: str) -> str:
    return {
        "Not Ready": (
            "The outcome cannot advance while review eligibility and "
            "administrative progression requirements remain unsatisfied."
        ),
        "Conditionally Ready": (
            "The outcome may advance when administrative review requirements "
            "are satisfied."
        ),
        "Ready": "The outcome is ready to proceed to determination.",
    }.get(
        outcome_readiness,
        (
            "The outcome cannot advance while review eligibility and "
            "administrative progression requirements remain unsatisfied."
        ),
    )


def classify_outcome_target(
    outcome: str,
    outcome_readiness: str,
    effective_state: str,
    review_eligibility: str,
    administrative_status: str,
) -> str:
    if outcome == "Ready For Determination" or outcome_readiness == "Ready":
        return "Determination Pending"
    if (
        outcome == "Review Awaiting Determination"
        or outcome_readiness == "Conditionally Ready"
        or review_eligibility == "Conditionally Eligible"
        or administrative_status == "Pending Administrative Review"
        or effective_state == "Administrative Review Pending"
    ):
        return "Ready For Determination"
    return "Review Awaiting Determination"


def describe_outcome_target(outcome_target: str) -> str:
    return {
        "Review Awaiting Determination": (
            "The next target outcome is administrative review awaiting "
            "determination once review eligibility and progression "
            "requirements are satisfied."
        ),
        "Ready For Determination": (
            "The next target outcome is readiness for determination once "
            "administrative review requirements are satisfied."
        ),
        "Determination Pending": (
            "The next target outcome is pending determination completion."
        ),
    }.get(
        outcome_target,
        (
            "The next target outcome is administrative review awaiting "
            "determination once review eligibility and progression "
            "requirements are satisfied."
        ),
    )


def classify_resolution(
    outcome: str,
    outcome_readiness: str,
    outcome_target: str,
    effective_state: str,
    implementation_action: str,
    administrative_status: str,
) -> str:
    resolution_failure_values = {
        "Corrective Action Reversed",
        "Implementation Failed",
    }
    if (
        outcome in resolution_failure_values
        or outcome_readiness in resolution_failure_values
        or outcome_target in resolution_failure_values
        or effective_state in resolution_failure_values
        or implementation_action in resolution_failure_values
        or administrative_status in resolution_failure_values
    ):
        return "Resolution Failed"
    if (
        outcome == "Corrective Action Implemented"
        and effective_state == "Corrective Action Effective"
    ):
        return "Resolved"
    if (
        outcome == "Determination Issued"
        and implementation_action == "Implementation Required"
    ):
        return "Conditionally Resolved"
    if (
        outcome == "Ready For Determination"
        and outcome_readiness == "Ready"
        and outcome_target == "Determination Pending"
    ):
        return "Partially Resolved"
    return "Unresolved"


def describe_resolution(resolution: str) -> str:
    return {
        "Unresolved": (
            "The matter remains unresolved because the current outcome has not "
            "reached an implemented administrative determination state."
        ),
        "Partially Resolved": (
            "The matter has advanced toward resolution but administrative "
            "determination or implementation remains incomplete."
        ),
        "Conditionally Resolved": (
            "The matter has reached a conditional resolution state, but "
            "implementation or confirmation requirements remain outstanding."
        ),
        "Resolved": (
            "The matter has reached a resolved state because the required "
            "administrative action has been implemented and is effective."
        ),
        "Resolution Failed": (
            "The matter has not resolved because the required corrective or "
            "administrative action failed, reversed, or did not take effect."
        ),
    }.get(
        resolution,
        (
            "The matter remains unresolved because the current outcome has not "
            "reached an implemented administrative determination state."
        ),
    )


def _resolution_precondition_target(resolution: str) -> str:
    return {
        "Unresolved": "Conditionally Resolved",
        "Partially Resolved": "Conditionally Resolved",
        "Conditionally Resolved": "Resolved",
        "Resolved": "No further resolution state identified",
        "Resolution Failed": "Resolution Recovery",
    }.get(resolution, "Conditionally Resolved")


def build_resolution_preconditions(
    resolution: str,
    outcome: str,
    outcome_readiness: str,
    outcome_target: str,
    effective_state: str,
    implementation_action: str,
    administrative_status: str,
    review_eligibility: str,
) -> list[str]:
    if resolution == "Resolved":
        return ["No additional resolution preconditions identified."]
    if resolution == "Resolution Failed":
        return [
            "Failed or reversed administrative action must be corrected.",
            "Resolution state must be re-established through effective action.",
        ]
    if resolution == "Conditionally Resolved":
        return [
            "Implementation requirements must be satisfied.",
            "Resolution effectiveness must be confirmed.",
        ]
    if resolution == "Partially Resolved":
        return [
            "Administrative determination must be completed.",
            "Implementation requirements must be identified.",
            "Effective state must advance beyond Formal Review Ready.",
        ]

    preconditions = []
    if review_eligibility != "Eligible":
        preconditions.append("Review eligibility requirements must be satisfied.")
    if administrative_status in {
        "Active Evidence Collection",
        "Active Evidence Review",
    }:
        preconditions.append("Administrative disposition must advance beyond Open.")
    if outcome_readiness == "Not Ready":
        preconditions.append("Outcome readiness must advance beyond Not Ready.")
    if implementation_action == "No Implementation Action":
        preconditions.append(
            "Implementation action must advance beyond No Implementation Action."
        )
    if effective_state == "Evidence Review Continues":
        preconditions.append(
            "Effective state must advance beyond Evidence Review Continues."
        )
    return preconditions or [
        "Resolution preconditions must be satisfied before resolution can occur."
    ]


def describe_resolution_preconditions(resolution: str) -> str:
    return (
        "Resolution preconditions identify the deterministic requirements that "
        f"must be satisfied before the current {resolution} state can advance."
    )

def _classify_resolution_pathway(
    *,
    resolution: str,
    resolution_preconditions: list[str],
    outcome_target: str,
    outcome_readiness: str,
    effective_state: str,
    review_eligibility: str,
    administrative_status: str,
    implementation_action: str,
) -> str:
    if resolution == "Resolved" and not resolution_preconditions:
        return "RESOLUTION PATHWAY COMPLETE"
    if resolution == "Resolved":
        return "RESOLUTION PATHWAY COMPLETE"
    if implementation_action == "Implementation Required":
        return "IMPLEMENTATION AWAITING ACTION"
    if resolution == "Conditionally Resolved":
        return "IMPLEMENTATION PATHWAY ACTIVE"
    if outcome_target == "Determination Pending":
        return "DETERMINATION PATHWAY ACTIVE"
    if review_eligibility != "Eligible":
        return "REVIEW ELIGIBILITY PENDING"
    if (
        outcome_readiness in {"Not Ready", "Conditionally Ready"}
        or effective_state == "Evidence Review Continues"
        or administrative_status in {
            "Active Evidence Collection",
            "Active Evidence Review",
        }
    ):
        return "REVIEW PATHWAY ACTIVE"
    return "REVIEW PATHWAY ACTIVE"


def _describe_resolution_pathway(pathway: str) -> str:
    return {
        "REVIEW PATHWAY ACTIVE": (
            "The current matter remains within the administrative review "
            "pathway and must satisfy review progression requirements before "
            "advancing."
        ),
        "REVIEW ELIGIBILITY PENDING": (
            "The current matter remains within the review pathway while review "
            "eligibility requirements remain pending."
        ),
        "IMPLEMENTATION PATHWAY ACTIVE": (
            "The matter has progressed beyond review and remains within the "
            "implementation pathway."
        ),
        "IMPLEMENTATION AWAITING ACTION": (
            "The matter has reached an implementation pathway state and is "
            "awaiting required implementation action."
        ),
        "DETERMINATION PATHWAY ACTIVE": (
            "The matter has reached the determination pathway and remains "
            "pending completion of administrative determination."
        ),
        "RESOLUTION PATHWAY COMPLETE": (
            "All resolution pathway requirements have been satisfied."
        ),
    }.get(
        pathway,
        (
            "The current matter remains within the administrative review "
            "pathway and must satisfy review progression requirements before "
            "advancing."
        ),
    )


def _classify_resolution_readiness(
    *,
    resolution: str,
    resolution_preconditions: list[str],
    resolution_pathway: str,
    outcome_readiness: str,
    review_eligibility: str,
    administrative_status: str,
    implementation_action: str,
    effective_state: str,
) -> str:
    if (
        resolution == "Resolved"
        and resolution_pathway == "RESOLUTION PATHWAY COMPLETE"
    ):
        return "Resolved"
    if (
        resolution == "Conditionally Resolved"
        and resolution_pathway == "IMPLEMENTATION PATHWAY ACTIVE"
    ):
        return "Ready"
    if (
        resolution == "Partially Resolved"
        and resolution_pathway == "DETERMINATION PATHWAY ACTIVE"
    ):
        return "Conditionally Ready"
    if (
        resolution == "Unresolved"
        and resolution_pathway == "REVIEW PATHWAY ACTIVE"
        and outcome_readiness != "Not Ready"
    ):
        return "Conditionally Ready"
    if (
        resolution == "Unresolved"
        and (
            resolution_pathway == "REVIEW ELIGIBILITY PENDING"
            or review_eligibility == "Not Eligible"
            or outcome_readiness == "Not Ready"
            or effective_state == "Evidence Review Continues"
            or implementation_action == "No Implementation Action"
            or administrative_status in {
                "Active Evidence Collection",
                "Active Evidence Review",
            }
            or resolution_preconditions
        )
    ):
        return "Not Ready"
    return "Conditionally Ready"


def _describe_resolution_readiness(readiness: str) -> str:
    return {
        "Not Ready": (
            "Resolution readiness has not been achieved because one or more "
            "prerequisite administrative conditions remain outstanding."
        ),
        "Conditionally Ready": (
            "Resolution readiness is partially established, but further "
            "administrative progression remains required."
        ),
        "Ready": (
            "Resolution readiness has been established and the matter may "
            "proceed toward determination, implementation, or confirmation."
        ),
        "Resolved": (
            "Resolution readiness assessment is complete because the matter "
            "has already reached a resolved administrative state."
        ),
    }.get(
        readiness,
        (
            "Resolution readiness has not been achieved because one or more "
            "prerequisite administrative conditions remain outstanding."
        ),
    )


def _classify_resolution_determination(
    *,
    resolution: str,
    resolution_preconditions: list[str],
    resolution_pathway: str,
    resolution_readiness: str,
    outcome_target: str,
    outcome_readiness: str,
    review_eligibility: str,
    administrative_status: str,
    implementation_action: str,
    effective_state: str,
) -> str:
    if (
        resolution == "Resolved"
        and resolution_pathway == "RESOLUTION PATHWAY COMPLETE"
    ):
        return "Determination Complete"
    if (
        resolution == "Conditionally Resolved"
        and resolution_pathway == "IMPLEMENTATION PATHWAY ACTIVE"
    ):
        return "Determination Issued"
    if (
        resolution == "Partially Resolved"
        and resolution_pathway == "DETERMINATION PATHWAY ACTIVE"
    ):
        return "Determination Required"
    if (
        resolution == "Unresolved"
        and resolution_readiness == "Conditionally Ready"
        and resolution_pathway == "REVIEW PATHWAY ACTIVE"
    ):
        return "Determination Pending"
    if (
        resolution == "Unresolved"
        and (
            resolution_readiness == "Not Ready"
            or resolution_pathway == "REVIEW ELIGIBILITY PENDING"
            or outcome_readiness == "Not Ready"
            or review_eligibility == "Not Eligible"
            or outcome_target == "Review Awaiting Determination"
            or effective_state == "Evidence Review Continues"
            or implementation_action == "No Implementation Action"
            or administrative_status in {
                "Active Evidence Collection",
                "Active Evidence Review",
            }
            or resolution_preconditions
        )
    ):
        return "Determination Not Available"
    return "Determination Pending"


def _describe_resolution_determination(determination: str) -> str:
    return {
        "Determination Not Available": (
            "Resolution determination is not available because prerequisite "
            "review and readiness conditions remain unsatisfied."
        ),
        "Determination Pending": (
            "Resolution determination is pending because the matter remains "
            "within the review pathway."
        ),
        "Determination Required": (
            "Resolution determination is required before the matter can "
            "advance toward implementation or completion."
        ),
        "Determination Issued": (
            "Resolution determination has been issued, but implementation or "
            "confirmation remains outstanding."
        ),
        "Determination Complete": (
            "Resolution determination is complete because the matter has "
            "reached a resolved administrative state."
        ),
    }.get(
        determination,
        (
            "Resolution determination is not available because prerequisite "
            "review and readiness conditions remain unsatisfied."
        ),
    )


def _classify_resolution_completion(
    *,
    resolution: str,
    resolution_preconditions: list[str],
    resolution_pathway: str,
    resolution_readiness: str,
    resolution_determination: str,
    outcome_target: str,
    outcome_readiness: str,
    review_eligibility: str,
    administrative_status: str,
    implementation_action: str,
    effective_state: str,
) -> str:
    if (
        resolution == "Resolved"
        and resolution_determination == "Determination Complete"
        and resolution_pathway == "RESOLUTION PATHWAY COMPLETE"
    ):
        return "Completion Confirmed"
    if (
        resolution == "Resolution Failed"
        or effective_state == "Implementation Failed"
        or implementation_action == "Implementation Failed"
    ):
        return "Completion Failed"
    if (
        resolution == "Partially Resolved"
        and resolution_determination == "Determination Required"
    ):
        return "Completion Required"
    if (
        resolution == "Conditionally Resolved"
        and resolution_determination == "Determination Issued"
    ):
        return "Completion Pending"
    if (
        resolution == "Unresolved"
        and resolution_determination == "Determination Pending"
    ):
        return "Completion Pending"
    if (
        resolution == "Unresolved"
        and (
            resolution_determination == "Determination Not Available"
            or resolution_readiness == "Not Ready"
            or resolution_pathway == "REVIEW ELIGIBILITY PENDING"
            or outcome_readiness == "Not Ready"
            or review_eligibility == "Not Eligible"
            or outcome_target == "Review Awaiting Determination"
            or effective_state == "Evidence Review Continues"
            or implementation_action == "No Implementation Action"
            or administrative_status in {
                "Active Evidence Collection",
                "Active Evidence Review",
            }
            or resolution_preconditions
        )
    ):
        return "Not Complete"
    return "Completion Pending"


def _describe_resolution_completion(completion: str) -> str:
    return {
        "Not Complete": (
            "Resolution completion has not been reached because prerequisite "
            "determination and readiness conditions remain unsatisfied."
        ),
        "Completion Pending": (
            "Resolution completion remains pending because determination, "
            "implementation, or confirmation requirements remain outstanding."
        ),
        "Completion Required": (
            "Resolution completion is required before the matter can be "
            "treated as administratively resolved."
        ),
        "Completion Confirmed": (
            "Resolution completion has been confirmed because the matter has "
            "reached a resolved administrative state."
        ),
        "Completion Failed": (
            "Resolution completion failed because the required corrective or "
            "administrative action did not take effect."
        ),
    }.get(
        completion,
        (
            "Resolution completion has not been reached because prerequisite "
            "determination and readiness conditions remain unsatisfied."
        ),
    )


def _classify_closure(
    *,
    resolution: str,
    resolution_completion: str,
    resolution_determination: str,
    resolution_readiness: str,
    resolution_pathway: str,
    outcome_target: str,
    administrative_status: str,
    implementation_action: str,
    effective_state: str,
) -> str:
    if (
        resolution == "Resolution Failed"
        or resolution_completion == "Completion Failed"
        or effective_state == "Implementation Failed"
        or implementation_action == "Implementation Failed"
    ):
        return "Closure Failed"
    if (
        resolution == "Resolved"
        and resolution_completion == "Completion Confirmed"
    ):
        return "Closed With Resolution"
    if (
        resolution == "Closed Without Resolution"
        or (
            resolution == "Unresolved"
            and resolution_completion == "Completion Confirmed"
        )
    ):
        return "Closed Without Resolution"
    if (
        resolution in {"Partially Resolved", "Conditionally Resolved"}
        and resolution_completion in {
            "Completion Required",
            "Completion Pending",
        }
    ):
        return "Pending Closure"
    if resolution == "Unresolved" and resolution_completion == "Not Complete":
        return "Open"
    if resolution_determination in {
        "Determination Required",
        "Determination Issued",
    } or resolution_readiness in {"Conditionally Ready", "Ready"}:
        return "Pending Closure"
    if (
        resolution_pathway == "REVIEW ELIGIBILITY PENDING"
        or outcome_target == "Review Awaiting Determination"
        or administrative_status == "Active Evidence Review"
        or implementation_action == "No Implementation Action"
        or effective_state == "Evidence Review Continues"
    ):
        return "Open"
    return "Pending Closure"


def _describe_closure(closure: str) -> str:
    return {
        "Open": (
            "The matter remains open because resolution completion has not "
            "been reached."
        ),
        "Pending Closure": (
            "The matter has advanced toward closure, but completion or "
            "confirmation requirements remain outstanding."
        ),
        "Closed Without Resolution": (
            "The matter has been closed without reaching a resolved "
            "administrative state."
        ),
        "Closed With Resolution": (
            "The matter has been closed after reaching a resolved "
            "administrative state."
        ),
        "Closure Failed": (
            "Closure failed because the required resolution or completion "
            "state did not take effect."
        ),
    }.get(
        closure,
        (
            "The matter remains open because resolution completion has not "
            "been reached."
        ),
    )


def _classify_closure_preconditions(
    *,
    closure: str,
    resolution: str,
    resolution_completion: str,
    resolution_determination: str,
    resolution_readiness: str,
    resolution_pathway: str,
    outcome_target: str,
    administrative_status: str,
    implementation_action: str,
    effective_state: str,
) -> str:
    if closure in {"Closed With Resolution", "Closed Without Resolution"}:
        return "Closure Ready"
    if closure == "Pending Closure":
        return "Conditionally Closable"
    if (
        closure == "Closure Failed"
        or resolution == "Resolution Failed"
        or resolution_completion == "Completion Failed"
        or effective_state == "Implementation Failed"
    ):
        return "Closure Blocked"
    if (
        closure == "Open"
        or resolution_completion == "Not Complete"
        or resolution_determination == "Determination Not Available"
        or resolution_readiness == "Not Ready"
        or resolution_pathway == "REVIEW ELIGIBILITY PENDING"
        or outcome_target == "Review Awaiting Determination"
        or administrative_status == "Active Evidence Review"
        or implementation_action == "No Implementation Action"
        or effective_state == "Evidence Review Continues"
    ):
        return "Closure Preconditions Outstanding"
    return "Conditionally Closable"


def _describe_closure_preconditions(precondition_state: str) -> str:
    return {
        "Closure Ready": (
            "All deterministic closure requirements have been satisfied."
        ),
        "Conditionally Closable": (
            "The matter is approaching closure but one or more completion "
            "requirements remain outstanding."
        ),
        "Closure Preconditions Outstanding": (
            "Closure requirements remain outstanding and must be satisfied "
            "before the matter can advance."
        ),
        "Closure Blocked": (
            "Closure cannot proceed because prerequisite completion or "
            "determination conditions have failed."
        ),
    }.get(
        precondition_state,
        (
            "Closure requirements remain outstanding and must be satisfied "
            "before the matter can advance."
        ),
    )


def _closure_precondition_items(
    *,
    closure_preconditions: str,
    resolution_completion: str,
    resolution_determination: str,
    resolution_readiness: str,
    administrative_status: str,
    effective_state: str,
) -> list[str]:
    if closure_preconditions == "Closure Ready":
        return ["No additional closure preconditions identified."]
    if closure_preconditions == "Conditionally Closable":
        return [
            "Completion or confirmation requirements must be satisfied.",
            "Closure may advance when outstanding completion requirements are resolved.",
        ]
    if closure_preconditions == "Closure Blocked":
        return [
            "Failed completion or determination conditions must be resolved.",
            "Closure cannot advance until the blocking state is cleared.",
        ]
    items = []
    if resolution_completion == "Not Complete":
        items.append("Resolution completion must advance beyond Not Complete.")
    if resolution_determination == "Determination Not Available":
        items.append("Resolution determination must become available.")
    if resolution_readiness == "Not Ready":
        items.append("Resolution readiness must advance beyond Not Ready.")
    if administrative_status == "Active Evidence Review":
        items.append("Administrative review requirements must be satisfied.")
    if effective_state == "Evidence Review Continues":
        items.append(
            "Effective state must advance beyond Evidence Review Continues."
        )
    return items or [
        "Closure requirements remain outstanding and must be satisfied."
    ]


def _classify_closure_pathway(
    *,
    closure: str,
    closure_preconditions: str,
    resolution: str,
    resolution_completion: str,
    resolution_determination: str,
    resolution_readiness: str,
    resolution_pathway: str,
    outcome_target: str,
    administrative_status: str,
    implementation_action: str,
    effective_state: str,
) -> str:
    if closure in {"Closed With Resolution", "Closed Without Resolution"}:
        return "Closure Complete"
    if (
        resolution_completion == "Completion Confirmed"
        and closure_preconditions == "Closure Ready"
    ):
        return "Closure Confirmation Pending"
    if (
        resolution_determination
        in {
            "Determination Pending",
            "Determination Required",
            "Determination Issued",
        }
        or resolution_completion == "Completion Pending"
    ):
        return "Closure Determination Pending"
    if closure == "Pending Closure" and closure_preconditions == "Conditionally Closable":
        return "Closure Readiness Pending"
    if closure == "Open" and closure_preconditions == "Closure Preconditions Outstanding":
        return "Closure Eligibility Pending"
    if (
        resolution == "Unresolved"
        or resolution_readiness == "Not Ready"
        or resolution_pathway == "REVIEW ELIGIBILITY PENDING"
        or outcome_target == "Review Awaiting Determination"
        or administrative_status == "Active Evidence Review"
        or implementation_action == "No Implementation Action"
        or effective_state == "Evidence Review Continues"
    ):
        return "Closure Eligibility Pending"
    return "Closure Readiness Pending"


def _describe_closure_pathway(pathway: str) -> str:
    return {
        "Closure Eligibility Pending": (
            "The matter remains within the closure pathway while closure "
            "eligibility requirements remain outstanding."
        ),
        "Closure Readiness Pending": (
            "The matter has advanced beyond eligibility review but closure "
            "readiness requirements remain outstanding."
        ),
        "Closure Determination Pending": (
            "The matter is awaiting closure determination following "
            "satisfaction of prerequisite readiness requirements."
        ),
        "Closure Confirmation Pending": (
            "The matter is awaiting final closure confirmation."
        ),
        "Closure Complete": "The closure pathway has completed.",
    }.get(
        pathway,
        (
            "The matter remains within the closure pathway while closure "
            "eligibility requirements remain outstanding."
        ),
    )


def _classify_closure_readiness(
    *,
    closure_classification: str,
    closure_preconditions: str,
    closure_pathway: str,
    resolution_classification: str,
    resolution_completion: str,
    resolution_determination: str,
    resolution_readiness: str,
    outcome_readiness: str,
    review_eligibility: str,
    administrative_status: str,
    implementation_action: str,
    effective_state: str,
) -> str:
    if (
        closure_classification in {
            "Closable",
            "Closed With Resolution",
            "Closed Without Resolution",
        }
        and closure_preconditions in {"Satisfied", "Closure Ready"}
        and closure_pathway in {"Closure Available", "Closure Complete"}
        and resolution_classification in {"Resolved", "Conditionally Resolved"}
        and resolution_completion in {"Complete", "Completion Confirmed"}
        and resolution_determination
        in {"Available", "Determination Complete", "Determination Issued"}
        and resolution_readiness in {"Ready", "Resolved"}
        and outcome_readiness in {"Ready", "Conditionally Ready"}
        and review_eligibility in {"Eligible", "Conditionally Eligible"}
        and administrative_status
        in {"Ready for Formal Review", "Pending Administrative Review"}
        and implementation_action != "No Implementation Action"
        and effective_state != "Evidence Review Continues"
    ):
        return "Ready"
    return "Not Ready"


def _describe_closure_readiness(readiness: str) -> str:
    return {
        "Ready": (
            "Closure readiness has been achieved because all prerequisite "
            "closure conditions have been satisfied."
        ),
        "Not Ready": (
            "Closure readiness has not been achieved because one or more "
            "prerequisite closure conditions remain outstanding."
        ),
    }.get(
        readiness,
        (
            "Closure readiness has not been achieved because one or more "
            "prerequisite closure conditions remain outstanding."
        ),
    )


def _classify_closure_determination(
    *,
    closure_classification: str,
    closure_preconditions: str,
    closure_pathway: str,
    closure_readiness: str,
    resolution_classification: str,
    resolution_completion: str,
    resolution_determination: str,
    outcome_readiness: str,
    review_eligibility: str,
    administrative_status: str,
    implementation_action: str,
    effective_state: str,
) -> str:
    if closure_classification in {
        "Closed With Resolution",
        "Closed Without Resolution",
    }:
        return "Determination Complete"
    if closure_pathway == "Closure Confirmation Pending":
        return "Determination Issued"
    if closure_pathway == "Closure Determination Pending":
        return "Determination Required"
    if (
        closure_readiness == "Ready"
        and closure_pathway == "Closure Readiness Pending"
    ):
        return "Determination Pending"
    if (
        closure_classification == "Open"
        or closure_readiness == "Not Ready"
        or closure_pathway == "Closure Eligibility Pending"
        or closure_preconditions == "Closure Preconditions Outstanding"
        or resolution_classification == "Unresolved"
        or resolution_completion == "Not Complete"
        or resolution_determination == "Determination Not Available"
        or outcome_readiness == "Not Ready"
        or review_eligibility == "Not Eligible"
        or administrative_status == "Active Evidence Review"
        or implementation_action == "No Implementation Action"
        or effective_state == "Evidence Review Continues"
    ):
        return "Determination Not Available"
    return "Determination Pending"


def _describe_closure_determination(determination: str) -> str:
    return {
        "Determination Not Available": (
            "Closure determination is not available because prerequisite "
            "closure conditions remain unsatisfied."
        ),
        "Determination Pending": (
            "Closure determination remains pending while closure readiness "
            "requirements are being satisfied."
        ),
        "Determination Required": (
            "Closure determination is required before the matter can advance "
            "toward closure confirmation."
        ),
        "Determination Issued": (
            "Closure determination has been issued and is awaiting closure "
            "confirmation."
        ),
        "Determination Complete": (
            "Closure determination is complete because the matter has reached "
            "a closure state."
        ),
    }.get(
        determination,
        (
            "Closure determination is not available because prerequisite "
            "closure conditions remain unsatisfied."
        ),
    )


def _classify_closure_completion(
    *,
    closure_classification: str,
    closure_preconditions: str,
    closure_pathway: str,
    closure_readiness: str,
    closure_determination: str,
    resolution_classification: str,
    resolution_completion: str,
    resolution_determination: str,
    outcome_readiness: str,
    review_eligibility: str,
    administrative_status: str,
    implementation_action: str,
    effective_state: str,
) -> str:
    if closure_classification in {
        "Closed With Resolution",
        "Closed Without Resolution",
    }:
        return "Complete"
    if (
        closure_determination == "Determination Issued"
        or closure_pathway == "Closure Confirmation Pending"
    ):
        return "Completion In Progress"
    if closure_determination == "Determination Pending":
        return "Completion Pending"
    if (
        closure_classification == "Open"
        or closure_readiness == "Not Ready"
        or closure_determination == "Determination Not Available"
        or closure_preconditions == "Closure Preconditions Outstanding"
        or closure_pathway == "Closure Eligibility Pending"
        or resolution_classification == "Unresolved"
        or resolution_completion == "Not Complete"
        or resolution_determination == "Determination Not Available"
        or outcome_readiness == "Not Ready"
        or review_eligibility == "Not Eligible"
        or administrative_status == "Active Evidence Review"
        or implementation_action == "No Implementation Action"
        or effective_state == "Evidence Review Continues"
    ):
        return "Not Complete"
    return "Completion Pending"


def _describe_closure_completion(completion: str) -> str:
    return {
        "Not Complete": (
            "Closure completion has not been reached because prerequisite "
            "closure determination conditions remain unsatisfied."
        ),
        "Completion Pending": (
            "Closure completion remains pending while closure determination "
            "requirements are being satisfied."
        ),
        "Completion In Progress": (
            "Closure completion is in progress pending final closure "
            "confirmation."
        ),
        "Complete": (
            "Closure completion has been achieved because the matter has "
            "reached a closure state."
        ),
    }.get(
        completion,
        (
            "Closure completion has not been reached because prerequisite "
            "closure determination conditions remain unsatisfied."
        ),
    )


def _archive_classification(
    *,
    closure_classification: str,
    closure_completion: str,
    closure_determination: str,
    closure_readiness: str,
    resolution_classification: str,
    resolution_completion: str,
    resolution_determination: str,
    outcome_readiness: str,
    review_eligibility: str,
    administrative_status: str,
    implementation_action: str,
    effective_state: str,
) -> str:
    if (
        administrative_status == "Archived"
        or effective_state == "Archived"
    ):
        return "Archived"
    if closure_completion == "Complete" and closure_classification in {
        "Closed With Resolution",
        "Closed Without Resolution",
    }:
        return "Archive Eligible"
    if (
        closure_classification == "Open"
        or closure_completion == "Not Complete"
        or closure_determination == "Determination Not Available"
        or closure_readiness == "Not Ready"
        or resolution_classification == "Unresolved"
        or resolution_completion == "Not Complete"
        or resolution_determination == "Determination Not Available"
        or outcome_readiness == "Not Ready"
        or review_eligibility == "Not Eligible"
        or implementation_action == "No Implementation Action"
        or effective_state == "Evidence Review Continues"
    ):
        return "Not Archivable"
    return "Not Archivable"


def _describe_archive_classification(classification: str) -> str:
    return {
        "Not Archivable": (
            "Archive classification has not been achieved because closure "
            "completion requirements remain unsatisfied."
        ),
        "Archive Eligible": (
            "The matter satisfies archive classification requirements and may "
            "proceed to archive evaluation."
        ),
        "Archived": "The matter has reached an archived administrative state.",
    }.get(
        classification,
        (
            "Archive classification has not been achieved because closure "
            "completion requirements remain unsatisfied."
        ),
    )


def _archive_preconditions(
    *,
    archive_classification: str,
    closure_classification: str,
    closure_completion: str,
    closure_determination: str,
    closure_readiness: str,
    resolution_classification: str,
    resolution_completion: str,
    resolution_determination: str,
    outcome_readiness: str,
    review_eligibility: str,
    administrative_status: str,
    implementation_action: str,
    effective_state: str,
) -> str:
    if archive_classification in {"Archive Eligible", "Archived"}:
        return "Archive Preconditions Satisfied"
    if (
        archive_classification == "Not Archivable"
        or closure_classification == "Open"
        or closure_completion != "Complete"
        or closure_determination == "Determination Not Available"
        or closure_readiness == "Not Ready"
        or resolution_classification == "Unresolved"
        or resolution_completion == "Not Complete"
        or resolution_determination == "Determination Not Available"
        or outcome_readiness == "Not Ready"
        or review_eligibility == "Not Eligible"
        or administrative_status == "Active Evidence Review"
        or implementation_action == "No Implementation Action"
        or effective_state == "Evidence Review Continues"
    ):
        return "Archive Preconditions Outstanding"
    return "Archive Preconditions Outstanding"


def _describe_archive_preconditions(preconditions: str) -> str:
    return {
        "Archive Preconditions Outstanding": (
            "Archive requirements remain outstanding and must be satisfied "
            "before archive progression can occur."
        ),
        "Archive Preconditions Satisfied": (
            "Archive requirements have been satisfied and archive progression "
            "may continue."
        ),
    }.get(
        preconditions,
        (
            "Archive requirements remain outstanding and must be satisfied "
            "before archive progression can occur."
        ),
    )


def _archive_precondition_items(
    *,
    archive_preconditions: str,
    closure_completion: str,
    closure_determination: str,
    closure_readiness: str,
    effective_state: str,
) -> list[str]:
    if archive_preconditions == "Archive Preconditions Satisfied":
        return ["No additional archive preconditions identified."]
    items = []
    if closure_completion == "Not Complete":
        items.append("Closure completion must advance beyond Not Complete.")
    if closure_determination == "Determination Not Available":
        items.append("Closure determination must become available.")
    if closure_readiness == "Not Ready":
        items.append("Closure readiness must advance beyond Not Ready.")
    items.append("Administrative archive requirements must be satisfied.")
    if effective_state == "Evidence Review Continues":
        items.append("Effective state must advance beyond Evidence Review Continues.")
    return items


def _archive_pathway(
    *,
    archive_classification: str,
    archive_preconditions: str,
    closure_classification: str,
    closure_completion: str,
    closure_determination: str,
    closure_readiness: str,
    resolution_classification: str,
    resolution_completion: str,
    resolution_determination: str,
    outcome_readiness: str,
    review_eligibility: str,
    administrative_status: str,
    implementation_action: str,
    effective_state: str,
) -> str:
    if archive_classification == "Archived":
        return "Archived"
    if archive_preconditions == "Archive Preconditions Outstanding":
        return "Archive Eligibility Pending"
    if (
        archive_classification == "Archive Eligible"
        and archive_preconditions == "Archive Preconditions Satisfied"
        and (
            administrative_status == "Ready for Archive Completion"
            or effective_state == "Archive Ready"
        )
    ):
        return "Archive Ready"
    if (
        archive_classification == "Archive Eligible"
        and archive_preconditions == "Archive Preconditions Satisfied"
    ):
        return "Archive Determination Pending"
    if (
        archive_preconditions == "Archive Preconditions Satisfied"
        or closure_classification in {
            "Closed With Resolution",
            "Closed Without Resolution",
        }
        or closure_completion == "Complete"
        or closure_determination == "Determination Complete"
        or closure_readiness == "Ready"
        or resolution_classification == "Resolved"
        or resolution_completion == "Completion Confirmed"
        or resolution_determination == "Determination Complete"
        or outcome_readiness == "Ready"
        or review_eligibility == "Eligible"
        or implementation_action != "No Implementation Action"
        or effective_state not in {"Evidence Review Continues", "Archived"}
    ):
        return "Archive Ready"
    return "Archive Eligibility Pending"


def _describe_archive_pathway(pathway: str) -> str:
    return {
        "Archive Eligibility Pending": (
            "The matter remains within the archive pathway while archive "
            "eligibility requirements remain outstanding."
        ),
        "Archive Determination Pending": (
            "Archive eligibility requirements have been satisfied and archive "
            "determination may proceed."
        ),
        "Archive Ready": (
            "Archive requirements have been satisfied and the matter is ready "
            "for archive completion."
        ),
        "Archived": "The matter has completed archive progression.",
    }.get(
        pathway,
        (
            "The matter remains within the archive pathway while archive "
            "eligibility requirements remain outstanding."
        ),
    )


def _archive_readiness(
    *,
    archive_classification: str,
    archive_preconditions: str,
    archive_pathway: str,
    closure_classification: str,
    closure_completion: str,
    closure_determination: str,
    closure_readiness: str,
    resolution_classification: str,
    resolution_completion: str,
    resolution_determination: str,
    outcome_readiness: str,
    review_eligibility: str,
    administrative_status: str,
    implementation_action: str,
    effective_state: str,
) -> str:
    if archive_classification == "Archived":
        return "Archived"
    if (
        archive_classification == "Not Archivable"
        or archive_preconditions == "Archive Preconditions Outstanding"
        or archive_pathway == "Archive Eligibility Pending"
        or closure_classification == "Open"
        or closure_completion == "Not Complete"
        or closure_determination == "Determination Not Available"
        or closure_readiness == "Not Ready"
        or resolution_classification == "Unresolved"
        or resolution_completion == "Not Complete"
        or resolution_determination == "Determination Not Available"
        or outcome_readiness == "Not Ready"
        or review_eligibility == "Not Eligible"
        or administrative_status == "Active Evidence Review"
        or implementation_action == "No Implementation Action"
        or effective_state == "Evidence Review Continues"
    ):
        return "Not Ready"
    if (
        archive_classification == "Archive Eligible"
        and archive_preconditions == "Archive Preconditions Satisfied"
        and archive_pathway != "Archive Eligibility Pending"
    ):
        return "Ready"
    return "Not Ready"


def _describe_archive_readiness(readiness: str) -> str:
    return {
        "Not Ready": (
            "Archive readiness has not been achieved because one or more "
            "prerequisite archive conditions remain outstanding."
        ),
        "Ready": (
            "Archive readiness has been achieved and archive determination "
            "may proceed."
        ),
        "Archived": (
            "Archive readiness has been satisfied and the matter has "
            "completed archive progression."
        ),
    }.get(
        readiness,
        (
            "Archive readiness has not been achieved because one or more "
            "prerequisite archive conditions remain outstanding."
        ),
    )


def _archive_determination(
    *,
    archive_classification: str,
    archive_preconditions: str,
    archive_pathway: str,
    archive_readiness: str,
    closure_classification: str,
    closure_completion: str,
    closure_determination: str,
    closure_readiness: str,
    resolution_classification: str,
    resolution_completion: str,
    resolution_determination: str,
    outcome_readiness: str,
    review_eligibility: str,
    administrative_status: str,
    implementation_action: str,
    effective_state: str,
) -> str:
    if archive_classification == "Archived":
        return "Archived"
    if archive_readiness == "Ready" and archive_classification != "Archived":
        return "Archive Eligible"
    if (
        archive_readiness == "Not Ready"
        or archive_preconditions == "Archive Preconditions Outstanding"
        or archive_pathway == "Archive Eligibility Pending"
        or closure_classification == "Open"
        or closure_completion == "Not Complete"
        or closure_determination == "Determination Not Available"
        or closure_readiness == "Not Ready"
        or resolution_classification == "Unresolved"
        or resolution_completion == "Not Complete"
        or resolution_determination == "Determination Not Available"
        or outcome_readiness == "Not Ready"
        or review_eligibility == "Not Eligible"
        or administrative_status == "Active Evidence Review"
        or implementation_action == "No Implementation Action"
        or effective_state == "Evidence Review Continues"
    ):
        return "Determination Not Available"
    return "Determination Not Available"


def _describe_archive_determination(determination: str) -> str:
    return {
        "Determination Not Available": (
            "Archive determination is not available because prerequisite "
            "archive conditions remain unsatisfied."
        ),
        "Archive Eligible": (
            "Archive determination confirms that archive requirements have "
            "been satisfied."
        ),
        "Archived": (
            "Archive determination confirms that archive progression has "
            "completed."
        ),
    }.get(
        determination,
        (
            "Archive determination is not available because prerequisite "
            "archive conditions remain unsatisfied."
        ),
    )


def _archive_completion(
    *,
    archive_classification: str,
    archive_preconditions: str,
    archive_pathway: str,
    archive_readiness: str,
    archive_determination: str,
    closure_classification: str,
    closure_completion: str,
    closure_determination: str,
    closure_readiness: str,
    resolution_classification: str,
    resolution_completion: str,
    resolution_determination: str,
    outcome_readiness: str,
    review_eligibility: str,
    administrative_status: str,
    implementation_action: str,
    effective_state: str,
) -> str:
    if archive_determination == "Archived":
        return "Complete"
    return "Not Complete"


def _describe_archive_completion(completion: str) -> str:
    return {
        "Not Complete": (
            "Archive completion has not been reached because prerequisite "
            "archive determination conditions remain unsatisfied."
        ),
        "Complete": (
            "Archive completion confirms that archive progression has "
            "concluded."
        ),
    }.get(
        completion,
        (
            "Archive completion has not been reached because prerequisite "
            "archive determination conditions remain unsatisfied."
        ),
    )

def _admin_action_badge_class(action: str) -> str:
    return {
        "Collect Initial Evidence": "admin-action-collect-initial-evidence",
        "Resolve Evidence Gaps": "admin-action-resolve-evidence-gaps",
        "Proceed to Administrative Review": "admin-action-proceed-review",
        "Eligible for Formal Review": "admin-action-formal-review",
    }.get(action, "admin-action-resolve-evidence-gaps")


def _workflow_state_badge_class(workflow_state: str) -> str:
    return {
        "Evidence Collection": "workflow-state-evidence-collection",
        "Evidence Review": "workflow-state-evidence-review",
        "Administrative Review": "workflow-state-administrative-review",
        "Formal Review Ready": "workflow-state-formal-review-ready",
    }.get(workflow_state, "workflow-state-evidence-review")


def _disposition_badge_class(disposition: str) -> str:
    return {
        "Open": "disposition-open",
        "Pending Review": "disposition-pending-review",
        "Ready for Review": "disposition-ready-review",
    }.get(disposition, "disposition-open")


def _eligibility_badge_class(eligibility: str) -> str:
    return {
        "Not Eligible": "eligibility-not-eligible",
        "Conditionally Eligible": "eligibility-conditionally-eligible",
        "Eligible": "eligibility-eligible",
    }.get(eligibility, "eligibility-not-eligible")


def _administrative_status_badge_class(status: str) -> str:
    return {
        "Active Evidence Collection": "administrative-status-active-collection",
        "Active Evidence Review": "administrative-status-active-review",
        "Pending Administrative Review": "administrative-status-pending-review",
        "Ready for Formal Review": "administrative-status-ready-review",
    }.get(status, "administrative-status-active-review")


def _implementation_action_badge_class(implementation_action: str) -> str:
    return {
        "No Implementation Action": "implementation-action-none",
        "Await Review Determination": "implementation-action-await-review",
        "Prepare Formal Review Implementation": "implementation-action-formal-review",
    }.get(implementation_action, "implementation-action-none")


def _effective_state_badge_class(effective_state: str) -> str:
    return {
        "Evidence Review Continues": "effective-state-evidence-review-continues",
        "Administrative Review Pending": "effective-state-administrative-review-pending",
        "Formal Review Ready": "effective-state-formal-review-ready",
    }.get(effective_state, "effective-state-evidence-review-continues")


def _outcome_badge_class(outcome: str) -> str:
    return {
        "Ongoing Review": "outcome-ongoing-review",
        "Review Awaiting Determination": "outcome-awaiting-determination",
        "Ready For Determination": "outcome-ready-determination",
    }.get(outcome, "outcome-ongoing-review")


def _outcome_readiness_badge_class(outcome_readiness: str) -> str:
    return {
        "Not Ready": "outcome-readiness-not-ready",
        "Conditionally Ready": "outcome-readiness-conditionally-ready",
        "Ready": "outcome-readiness-ready",
    }.get(outcome_readiness, "outcome-readiness-not-ready")


def _outcome_target_badge_class(outcome_target: str) -> str:
    return {
        "Review Awaiting Determination": (
            "outcome-target-review-awaiting-determination"
        ),
        "Ready For Determination": "outcome-target-ready-for-determination",
        "Determination Pending": "outcome-target-determination-pending",
    }.get(outcome_target, "outcome-target-review-awaiting-determination")


def _resolution_badge_class(resolution: str) -> str:
    return {
        "Unresolved": "resolution-unresolved",
        "Partially Resolved": "resolution-partially-resolved",
        "Conditionally Resolved": "resolution-conditionally-resolved",
        "Resolved": "resolution-resolved",
        "Resolution Failed": "resolution-failed",
    }.get(resolution, "resolution-unresolved")


def _resolution_readiness_badge_class(readiness: str) -> str:
    return {
        "Not Ready": "resolution-readiness-not-ready",
        "Conditionally Ready": "resolution-readiness-conditionally-ready",
        "Ready": "resolution-readiness-ready",
        "Resolved": "resolution-readiness-resolved",
    }.get(readiness, "resolution-readiness-not-ready")


def _resolution_determination_badge_class(determination: str) -> str:
    return {
        "Determination Not Available": (
            "resolution-determination-not-available"
        ),
        "Determination Pending": "resolution-determination-pending",
        "Determination Required": "resolution-determination-required",
        "Determination Issued": "resolution-determination-issued",
        "Determination Complete": "resolution-determination-complete",
    }.get(determination, "resolution-determination-not-available")


def _resolution_completion_badge_class(completion: str) -> str:
    return {
        "Not Complete": "resolution-completion-not-complete",
        "Completion Pending": "resolution-completion-pending",
        "Completion Required": "resolution-completion-required",
        "Completion Confirmed": "resolution-completion-confirmed",
        "Completion Failed": "resolution-completion-failed",
    }.get(completion, "resolution-completion-not-complete")


def _closure_badge_class(closure: str) -> str:
    return {
        "Open": "closure-open",
        "Pending Closure": "closure-pending",
        "Closed Without Resolution": "closure-without-resolution",
        "Closed With Resolution": "closure-with-resolution",
        "Closure Failed": "closure-failed",
    }.get(closure, "closure-open")


def _closure_precondition_badge_class(precondition_state: str) -> str:
    return {
        "Closure Ready": "closure-ready",
        "Conditionally Closable": "closure-conditional",
        "Closure Preconditions Outstanding": "closure-outstanding",
        "Closure Blocked": "closure-blocked",
    }.get(precondition_state, "closure-outstanding")


def _closure_pathway_badge_class(pathway: str) -> str:
    return {
        "Closure Eligibility Pending": "closure-eligibility-pending",
        "Closure Readiness Pending": "closure-readiness-pending",
        "Closure Determination Pending": "closure-determination-pending",
        "Closure Confirmation Pending": "closure-confirmation-pending",
        "Closure Complete": "closure-complete",
    }.get(pathway, "closure-eligibility-pending")


def _closure_readiness_badge_class(readiness: str) -> str:
    return {
        "Ready": "closure-readiness-ready",
        "Not Ready": "closure-readiness-not-ready",
    }.get(readiness, "closure-readiness-not-ready")


def _closure_determination_badge_class(determination: str) -> str:
    return {
        "Determination Not Available": (
            "closure-determination-not-available"
        ),
        "Determination Pending": "closure-determination-pending",
        "Determination Required": "closure-determination-required",
        "Determination Issued": "closure-determination-issued",
        "Determination Complete": "closure-determination-complete",
    }.get(determination, "closure-determination-not-available")


def _closure_completion_badge_class(completion: str) -> str:
    return {
        "Not Complete": "closure-completion-not-complete",
        "Completion Pending": "closure-completion-pending",
        "Completion In Progress": "closure-completion-in-progress",
        "Complete": "closure-completion-complete",
    }.get(completion, "closure-completion-not-complete")


def _archive_classification_badge_class(classification: str) -> str:
    return {
        "Not Archivable": "archive-classification-not-archivable",
        "Archive Eligible": "archive-classification-eligible",
        "Archived": "archive-classification-archived",
    }.get(classification, "archive-classification-not-archivable")


def _archive_preconditions_badge_class(preconditions: str) -> str:
    return {
        "Archive Preconditions Outstanding": (
            "archive-preconditions-outstanding"
        ),
        "Archive Preconditions Satisfied": "archive-preconditions-satisfied",
    }.get(preconditions, "archive-preconditions-outstanding")


def _archive_pathway_badge_class(pathway: str) -> str:
    return {
        "Archive Eligibility Pending": "archive-pathway-eligibility-pending",
        "Archive Determination Pending": (
            "archive-pathway-determination-pending"
        ),
        "Archive Ready": "archive-pathway-ready",
        "Archived": "archive-pathway-archived",
    }.get(pathway, "archive-pathway-eligibility-pending")


def _archive_readiness_badge_class(readiness: str) -> str:
    return {
        "Not Ready": "archive-readiness-not-ready",
        "Ready": "archive-readiness-ready",
        "Archived": "archive-readiness-archived",
    }.get(readiness, "archive-readiness-not-ready")


def _archive_determination_badge_class(determination: str) -> str:
    return {
        "Determination Not Available": (
            "archive-determination-not-available"
        ),
        "Archive Eligible": "archive-determination-eligible",
        "Archived": "archive-determination-archived",
    }.get(determination, "archive-determination-not-available")


def _archive_completion_badge_class(completion: str) -> str:
    return {
        "Not Complete": "archive-completion-not-complete",
        "Complete": "archive-completion-complete",
    }.get(completion, "archive-completion-not-complete")

def _render_record_evidence_sufficiency(
    evidence_groups: dict[str, list[dict[str, Any]]],
) -> str:
    rows = []
    for target_type in ("condition", "signal", "finding", "record"):
        for target in evidence_groups.get(target_type) or []:
            attachment_count = len(target.get("attachments") or [])
            relationship_count = int(target.get("relationship_count") or 0)
            sufficiency = classify_evidence_sufficiency(
                attachment_count,
                relationship_count,
            )
            rows.append(
                "<tr>"
                f"<td>{escape(_target_type_display_label(target_type))}</td>"
                f"<td class=\"target-cell\">{escape(str(target.get('target_label') or target.get('target_key') or ''))}</td>"
                f"<td>{attachment_count}</td>"
                f"<td>{relationship_count}</td>"
                f"<td class=\"sufficiency-cell\">{escape(sufficiency)}</td>"
                "</tr>"
            )

    if not rows:
        table_body = (
            '<tr><td colspan="5">No record targets are available.</td></tr>'
        )
    else:
        table_body = "".join(rows)

    return f"""
      <section class="management-section evidence-sufficiency">
        <h2>Stage 7F — Evidence Sufficiency</h2>
        <p class="notice">
          Sufficiency is classified deterministically from existing attachment
          and relationship counts only.
        </p>
        <table class="stage7f-sufficiency-table">
          <thead>
            <tr>
              <th>Target Type</th>
              <th>Target</th>
              <th>Supporting Attachments</th>
              <th>Supporting Relationships</th>
              <th>Sufficiency</th>
            </tr>
          </thead>
          <tbody>{table_body}</tbody>
        </table>
      </section>"""


def _record_evidence_readiness_values(
    evidence_groups: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    gap_summary = _record_evidence_gap_summary(evidence_groups)
    classifications = _evidence_sufficiency_classifications(evidence_groups)
    readiness = classify_evidence_readiness(
        int(gap_summary["supported_targets"]),
        int(gap_summary["unsupported_targets"]),
        int(gap_summary["evidence_gap_count"]),
        classifications,
    )
    return {
        "gap_summary": gap_summary,
        "classifications": classifications,
        "readiness": readiness,
    }


def _render_record_evidence_readiness(
    evidence_groups: dict[str, list[dict[str, Any]]],
) -> str:
    readiness_values = _record_evidence_readiness_values(evidence_groups)
    gap_summary = readiness_values["gap_summary"]
    classifications = readiness_values["classifications"]
    readiness = readiness_values["readiness"]
    rows = (
        ("Readiness Classification", readiness),
        ("Supported Targets", gap_summary["supported_targets"]),
        ("Unsupported Targets", gap_summary["unsupported_targets"]),
        ("Evidence Gap Count", gap_summary["evidence_gap_count"]),
        ("Coverage Percentage", f"{gap_summary['coverage_percentage']:.1f}%"),
        ("Sufficiency Basis", _summarize_sufficiency_basis(classifications)),
    )
    table_rows = []
    for label, value in rows:
        if label == "Readiness Classification":
            badge_class = _readiness_badge_class(str(value))
            value_html = (
                f'<span class="readiness-badge {badge_class}">'
                f"{escape(str(value))}</span>"
            )
        else:
            value_html = escape(str(value))
        table_rows.append(
            "<tr>"
            f"<td>{escape(str(label))}</td>"
            f"<td>{value_html}</td>"
            "</tr>"
        )
    return f"""
      <section class="management-section evidence-readiness">
        <h2>Stage 7G — Evidence Readiness</h2>
        <p class="notice">
          Readiness is classified deterministically from existing coverage,
          gap, and sufficiency values only.
        </p>
        <table>
          <tbody>{"".join(table_rows)}</tbody>
        </table>
      </section>"""


def _render_administrative_action(
    evidence_groups: dict[str, list[dict[str, Any]]],
) -> str:
    readiness_values = _record_evidence_readiness_values(evidence_groups)
    gap_summary = readiness_values["gap_summary"]
    readiness = readiness_values["readiness"]
    supported_targets = int(gap_summary["supported_targets"])
    unsupported_targets = int(gap_summary["unsupported_targets"])
    evidence_gap_count = int(gap_summary["evidence_gap_count"])
    action = classify_administrative_action(readiness)
    action_basis = describe_administrative_action_basis(
        readiness,
        supported_targets,
        unsupported_targets,
        evidence_gap_count,
    )
    action_badge = (
        f'<span class="admin-action-badge {_admin_action_badge_class(action)}">'
        f"{escape(action)}</span>"
    )
    readiness_badge = (
        f'<span class="readiness-badge {_readiness_badge_class(readiness)}">'
        f"{escape(readiness)}</span>"
    )
    rows = (
        ("Administrative Action", action_badge),
        ("Readiness Classification", readiness_badge),
        ("Supported Targets", escape(str(supported_targets))),
        ("Unsupported Targets", escape(str(unsupported_targets))),
        ("Evidence Gap Count", escape(str(evidence_gap_count))),
        ("Action Basis", escape(action_basis)),
    )
    table_rows = "".join(
        "<tr>"
        f"<td>{escape(str(label))}</td>"
        f"<td>{value}</td>"
        "</tr>"
        for label, value in rows
    )
    return f"""
      <section class="management-section administrative-action">
        <h2>Stage 8A — Administrative Action</h2>
        <p class="notice">
          Administrative action is classified deterministically from the
          current readiness state only.
        </p>
        <table>
          <tbody>{table_rows}</tbody>
        </table>
      </section>"""


def _render_action_rationale(
    evidence_groups: dict[str, list[dict[str, Any]]],
) -> str:
    readiness_values = _record_evidence_readiness_values(evidence_groups)
    gap_summary = readiness_values["gap_summary"]
    readiness = readiness_values["readiness"]
    supported_targets = int(gap_summary["supported_targets"])
    unsupported_targets = int(gap_summary["unsupported_targets"])
    evidence_gap_count = int(gap_summary["evidence_gap_count"])
    action = classify_administrative_action(readiness)
    rationale_steps = build_action_rationale_trace(
        readiness,
        action,
        supported_targets,
        unsupported_targets,
        evidence_gap_count,
    )
    rationale_items = "".join(
        f"<li>{escape(step)}</li>" for step in rationale_steps
    )
    return f"""
      <section class="management-section action-rationale">
        <h2>Stage 8B — Action Rationale</h2>
        <p class="notice">
          Action rationale is derived deterministically from readiness and
          evidence state values only.
        </p>
        <h3>Action Rationale</h3>
        <ol class="action-rationale-list">{rationale_items}</ol>
      </section>"""


def _render_completion_requirements(
    evidence_groups: dict[str, list[dict[str, Any]]],
) -> str:
    readiness_values = _record_evidence_readiness_values(evidence_groups)
    gap_summary = readiness_values["gap_summary"]
    classifications = readiness_values["classifications"]
    readiness = readiness_values["readiness"]
    supported_targets = int(gap_summary["supported_targets"])
    unsupported_targets = int(gap_summary["unsupported_targets"])
    evidence_gap_count = int(gap_summary["evidence_gap_count"])
    action = classify_administrative_action(readiness)
    requirements = build_completion_requirements(
        readiness,
        action,
        supported_targets,
        unsupported_targets,
        evidence_gap_count,
        classifications,
    )
    requirement_items = "".join(
        f"<li>{escape(requirement)}</li>" for requirement in requirements
    )
    return f"""
      <section class="management-section completion-requirements">
        <h2>Stage 8C — Completion Requirements</h2>
        <p class="notice">
          Completion requirements are derived deterministically from the current
          readiness and administrative action state only.
        </p>
        <h3>Completion Requirements</h3>
        <ol class="completion-requirements-list">{requirement_items}</ol>
      </section>"""


def _render_workflow_state(
    evidence_groups: dict[str, list[dict[str, Any]]],
) -> str:
    readiness_values = _record_evidence_readiness_values(evidence_groups)
    readiness = readiness_values["readiness"]
    action = classify_administrative_action(readiness)
    workflow_state = classify_workflow_state(readiness, action)
    workflow_badge = (
        f'<span class="workflow-state-badge {_workflow_state_badge_class(workflow_state)}">'
        f"{escape(workflow_state)}</span>"
    )
    readiness_badge = (
        f'<span class="readiness-badge {_readiness_badge_class(readiness)}">'
        f"{escape(readiness)}</span>"
    )
    action_badge = (
        f'<span class="admin-action-badge {_admin_action_badge_class(action)}">'
        f"{escape(action)}</span>"
    )
    rows = (
        ("Workflow State", workflow_badge),
        ("State Description", escape(describe_workflow_state(workflow_state))),
        ("Readiness Classification", readiness_badge),
        ("Administrative Action", action_badge),
    )
    table_rows = "".join(
        "<tr>"
        f"<td>{escape(str(label))}</td>"
        f"<td>{value}</td>"
        "</tr>"
        for label, value in rows
    )
    return f"""
      <section class="management-section workflow-state">
        <h2>Stage 8D — Workflow State</h2>
        <p class="notice">
          Workflow state is classified deterministically from readiness and
          administrative action values only.
        </p>
        <table>
          <tbody>{table_rows}</tbody>
        </table>
      </section>"""


def _render_transition_conditions(
    evidence_groups: dict[str, list[dict[str, Any]]],
) -> str:
    readiness_values = _record_evidence_readiness_values(evidence_groups)
    gap_summary = readiness_values["gap_summary"]
    classifications = readiness_values["classifications"]
    readiness = readiness_values["readiness"]
    supported_targets = int(gap_summary["supported_targets"])
    unsupported_targets = int(gap_summary["unsupported_targets"])
    evidence_gap_count = int(gap_summary["evidence_gap_count"])
    action = classify_administrative_action(readiness)
    workflow_state = classify_workflow_state(readiness, action)
    completion_requirements = build_completion_requirements(
        readiness,
        action,
        supported_targets,
        unsupported_targets,
        evidence_gap_count,
        classifications,
    )
    transition_target = describe_transition_target(workflow_state)
    conditions = build_transition_conditions(
        workflow_state,
        readiness,
        action,
        completion_requirements,
    )
    condition_items = "".join(
        f"<li>{escape(condition)}</li>" for condition in conditions
    )
    return f"""
      <section class="management-section transition-conditions">
        <h2>Stage 8E — Transition Conditions</h2>
        <p class="notice">
          Transition conditions are derived deterministically from workflow
          state and completion requirement values only.
        </p>
        <table>
          <tbody>
            <tr><td>Transition Target</td><td>{escape(transition_target)}</td></tr>
          </tbody>
        </table>
        <h3>Transition Conditions</h3>
        <ol class="transition-conditions-list">{condition_items}</ol>
      </section>"""


def _render_administrative_disposition(
    evidence_groups: dict[str, list[dict[str, Any]]],
) -> str:
    readiness_values = _record_evidence_readiness_values(evidence_groups)
    readiness = readiness_values["readiness"]
    action = classify_administrative_action(readiness)
    workflow_state = classify_workflow_state(readiness, action)
    disposition = classify_administrative_disposition(workflow_state)
    disposition_badge = (
        f'<span class="disposition-badge {_disposition_badge_class(disposition)}">'
        f"{escape(disposition)}</span>"
    )
    workflow_badge = (
        f'<span class="workflow-state-badge {_workflow_state_badge_class(workflow_state)}">'
        f"{escape(workflow_state)}</span>"
    )
    readiness_badge = (
        f'<span class="readiness-badge {_readiness_badge_class(readiness)}">'
        f"{escape(readiness)}</span>"
    )
    rows = (
        ("Administrative Disposition", disposition_badge),
        (
            "Disposition Description",
            escape(describe_administrative_disposition(disposition)),
        ),
        ("Workflow State", workflow_badge),
        ("Readiness Classification", readiness_badge),
    )
    table_rows = "".join(
        "<tr>"
        f"<td>{escape(str(label))}</td>"
        f"<td>{value}</td>"
        "</tr>"
        for label, value in rows
    )
    return f"""
      <section class="management-section administrative-disposition">
        <h2>Stage 9A — Administrative Disposition</h2>
        <p class="notice">
          Administrative disposition is classified deterministically from
          workflow state values only.
        </p>
        <table>
          <tbody>{table_rows}</tbody>
        </table>
      </section>"""


def _render_disposition_basis(
    evidence_groups: dict[str, list[dict[str, Any]]],
) -> str:
    readiness_values = _record_evidence_readiness_values(evidence_groups)
    readiness = readiness_values["readiness"]
    action = classify_administrative_action(readiness)
    workflow_state = classify_workflow_state(readiness, action)
    disposition = classify_administrative_disposition(workflow_state)
    trace_steps = build_disposition_basis_trace(
        disposition,
        workflow_state,
        readiness,
        action,
    )
    trace_items = "".join(f"<li>{escape(step)}</li>" for step in trace_steps)
    return f"""
      <section class="management-section disposition-basis">
        <h2>Stage 9B — Disposition Basis</h2>
        <p class="notice">
          Disposition basis is derived deterministically from workflow,
          readiness, and administrative action values only.
        </p>
        <h3>Disposition Basis</h3>
        <ol class="disposition-basis-list">{trace_items}</ol>
      </section>"""


def _render_review_eligibility(
    evidence_groups: dict[str, list[dict[str, Any]]],
) -> str:
    readiness_values = _record_evidence_readiness_values(evidence_groups)
    readiness = readiness_values["readiness"]
    action = classify_administrative_action(readiness)
    workflow_state = classify_workflow_state(readiness, action)
    disposition = classify_administrative_disposition(workflow_state)
    eligibility = classify_review_eligibility(disposition)
    eligibility_badge = (
        f'<span class="eligibility-badge {_eligibility_badge_class(eligibility)}">'
        f"{escape(eligibility)}</span>"
    )
    disposition_badge = (
        f'<span class="disposition-badge {_disposition_badge_class(disposition)}">'
        f"{escape(disposition)}</span>"
    )
    workflow_badge = (
        f'<span class="workflow-state-badge {_workflow_state_badge_class(workflow_state)}">'
        f"{escape(workflow_state)}</span>"
    )
    rows = (
        ("Review Eligibility", eligibility_badge),
        ("Eligibility Description", escape(describe_review_eligibility(eligibility))),
        ("Administrative Disposition", disposition_badge),
        ("Workflow State", workflow_badge),
    )
    table_rows = "".join(
        "<tr>"
        f"<td>{escape(str(label))}</td>"
        f"<td>{value}</td>"
        "</tr>"
        for label, value in rows
    )
    return f"""
      <section class="management-section review-eligibility">
        <h2>Stage 9C — Review Eligibility</h2>
        <p class="notice">
          Review eligibility is classified deterministically from
          administrative disposition values only.
        </p>
        <table>
          <tbody>{table_rows}</tbody>
        </table>
      </section>"""


def _render_review_preconditions(
    evidence_groups: dict[str, list[dict[str, Any]]],
) -> str:
    readiness_values = _record_evidence_readiness_values(evidence_groups)
    gap_summary = readiness_values["gap_summary"]
    classifications = readiness_values["classifications"]
    readiness = readiness_values["readiness"]
    supported_targets = int(gap_summary["supported_targets"])
    unsupported_targets = int(gap_summary["unsupported_targets"])
    evidence_gap_count = int(gap_summary["evidence_gap_count"])
    action = classify_administrative_action(readiness)
    workflow_state = classify_workflow_state(readiness, action)
    disposition = classify_administrative_disposition(workflow_state)
    eligibility = classify_review_eligibility(disposition)
    completion_requirements = build_completion_requirements(
        readiness,
        action,
        supported_targets,
        unsupported_targets,
        evidence_gap_count,
        classifications,
    )
    transition_conditions = build_transition_conditions(
        workflow_state,
        readiness,
        action,
        completion_requirements,
    )
    precondition_target = describe_review_precondition_target(eligibility)
    preconditions = build_review_preconditions(
        eligibility,
        disposition,
        workflow_state,
        transition_conditions,
    )
    precondition_items = "".join(
        f"<li>{escape(precondition)}</li>" for precondition in preconditions
    )
    return f"""
      <section class="management-section review-preconditions">
        <h2>Stage 9D — Review Preconditions</h2>
        <p class="notice">
          Review preconditions are derived deterministically from review
          eligibility and workflow transition values only.
        </p>
        <table>
          <tbody>
            <tr><td>Precondition Target</td><td>{escape(precondition_target)}</td></tr>
          </tbody>
        </table>
        <h3>Review Preconditions</h3>
        <ol class="review-preconditions-list">{precondition_items}</ol>
      </section>"""


def _render_administrative_status_summary(
    evidence_groups: dict[str, list[dict[str, Any]]],
) -> str:
    readiness_values = _record_evidence_readiness_values(evidence_groups)
    readiness = readiness_values["readiness"]
    action = classify_administrative_action(readiness)
    workflow_state = classify_workflow_state(readiness, action)
    disposition = classify_administrative_disposition(workflow_state)
    eligibility = classify_review_eligibility(disposition)
    status_summary = build_administrative_status_summary(
        disposition,
        eligibility,
        workflow_state,
        readiness,
    )
    status = status_summary["status"]
    status_badge = (
        f'<span class="administrative-status-badge {_administrative_status_badge_class(status)}">'
        f"{escape(status)}</span>"
    )
    disposition_badge = (
        f'<span class="disposition-badge {_disposition_badge_class(disposition)}">'
        f"{escape(disposition)}</span>"
    )
    eligibility_badge = (
        f'<span class="eligibility-badge {_eligibility_badge_class(eligibility)}">'
        f"{escape(eligibility)}</span>"
    )
    workflow_badge = (
        f'<span class="workflow-state-badge {_workflow_state_badge_class(workflow_state)}">'
        f"{escape(workflow_state)}</span>"
    )
    readiness_badge = (
        f'<span class="readiness-badge {_readiness_badge_class(readiness)}">'
        f"{escape(readiness)}</span>"
    )
    rows = (
        ("Administrative Status", status_badge),
        ("Status Description", escape(status_summary["description"])),
        ("Administrative Disposition", disposition_badge),
        ("Review Eligibility", eligibility_badge),
        ("Workflow State", workflow_badge),
        ("Readiness Classification", readiness_badge),
    )
    table_rows = "".join(
        "<tr>"
        f"<td>{escape(str(label))}</td>"
        f"<td>{value}</td>"
        "</tr>"
        for label, value in rows
    )
    return f"""
      <section class="management-section administrative-status-summary">
        <h2>Stage 9E — Administrative Status Summary</h2>
        <p class="notice">
          Administrative status is summarized deterministically from
          disposition, eligibility, workflow, and readiness values only.
        </p>
        <table>
          <tbody>{table_rows}</tbody>
        </table>
      </section>"""


def _render_implementation_action(
    evidence_groups: dict[str, list[dict[str, Any]]],
) -> str:
    readiness_values = _record_evidence_readiness_values(evidence_groups)
    readiness = readiness_values["readiness"]
    action = classify_administrative_action(readiness)
    workflow_state = classify_workflow_state(readiness, action)
    disposition = classify_administrative_disposition(workflow_state)
    eligibility = classify_review_eligibility(disposition)
    status_summary = build_administrative_status_summary(
        disposition,
        eligibility,
        workflow_state,
        readiness,
    )
    administrative_status = status_summary["status"]
    implementation_action = classify_implementation_action(
        administrative_status
    )
    implementation_badge = (
        f'<span class="implementation-action-badge {_implementation_action_badge_class(implementation_action)}">'
        f"{escape(implementation_action)}</span>"
    )
    status_badge = (
        f'<span class="administrative-status-badge {_administrative_status_badge_class(administrative_status)}">'
        f"{escape(administrative_status)}</span>"
    )
    disposition_badge = (
        f'<span class="disposition-badge {_disposition_badge_class(disposition)}">'
        f"{escape(disposition)}</span>"
    )
    eligibility_badge = (
        f'<span class="eligibility-badge {_eligibility_badge_class(eligibility)}">'
        f"{escape(eligibility)}</span>"
    )
    workflow_badge = (
        f'<span class="workflow-state-badge {_workflow_state_badge_class(workflow_state)}">'
        f"{escape(workflow_state)}</span>"
    )
    rows = (
        ("Implementation Action", implementation_badge),
        (
            "Implementation Description",
            escape(describe_implementation_action(implementation_action)),
        ),
        ("Administrative Status", status_badge),
        ("Administrative Disposition", disposition_badge),
        ("Review Eligibility", eligibility_badge),
        ("Workflow State", workflow_badge),
    )
    table_rows = "".join(
        "<tr>"
        f"<td>{escape(str(label))}</td>"
        f"<td>{value}</td>"
        "</tr>"
        for label, value in rows
    )
    return f"""
      <section class="management-section implementation-action">
        <h2>Stage 10A — Implementation Action</h2>
        <p class="notice">
          Implementation action is classified deterministically from
          administrative status values only.
        </p>
        <table>
          <tbody>{table_rows}</tbody>
        </table>
      </section>"""


def _render_implementation_basis(
    evidence_groups: dict[str, list[dict[str, Any]]],
) -> str:
    readiness_values = _record_evidence_readiness_values(evidence_groups)
    readiness = readiness_values["readiness"]
    action = classify_administrative_action(readiness)
    workflow_state = classify_workflow_state(readiness, action)
    disposition = classify_administrative_disposition(workflow_state)
    eligibility = classify_review_eligibility(disposition)
    status_summary = build_administrative_status_summary(
        disposition,
        eligibility,
        workflow_state,
        readiness,
    )
    administrative_status = status_summary["status"]
    implementation_action = classify_implementation_action(
        administrative_status
    )
    trace_steps = build_implementation_basis_trace(
        implementation_action,
        administrative_status,
        disposition,
        eligibility,
        workflow_state,
        readiness,
    )
    trace_items = "".join(f"<li>{escape(step)}</li>" for step in trace_steps)
    return f"""
      <section class="management-section implementation-basis">
        <h2>Stage 10B — Implementation Basis</h2>
        <p class="notice">
          Implementation basis is derived deterministically from
          administrative status, disposition, eligibility, workflow, and
          readiness values only.
        </p>
        <h3>Implementation Basis</h3>
        <ol class="implementation-basis-list">{trace_items}</ol>
      </section>"""


def _render_effective_state(
    evidence_groups: dict[str, list[dict[str, Any]]],
) -> str:
    readiness_values = _record_evidence_readiness_values(evidence_groups)
    readiness = readiness_values["readiness"]
    action = classify_administrative_action(readiness)
    workflow_state = classify_workflow_state(readiness, action)
    disposition = classify_administrative_disposition(workflow_state)
    eligibility = classify_review_eligibility(disposition)
    status_summary = build_administrative_status_summary(
        disposition,
        eligibility,
        workflow_state,
        readiness,
    )
    administrative_status = status_summary["status"]
    implementation_action = classify_implementation_action(
        administrative_status
    )
    effective_state = classify_effective_state(
        implementation_action,
        administrative_status,
    )
    effective_state_badge = (
        f'<span class="effective-state-badge {_effective_state_badge_class(effective_state)}">'
        f"{escape(effective_state)}</span>"
    )
    implementation_badge = (
        f'<span class="implementation-action-badge {_implementation_action_badge_class(implementation_action)}">'
        f"{escape(implementation_action)}</span>"
    )
    status_badge = (
        f'<span class="administrative-status-badge {_administrative_status_badge_class(administrative_status)}">'
        f"{escape(administrative_status)}</span>"
    )
    disposition_badge = (
        f'<span class="disposition-badge {_disposition_badge_class(disposition)}">'
        f"{escape(disposition)}</span>"
    )
    eligibility_badge = (
        f'<span class="eligibility-badge {_eligibility_badge_class(eligibility)}">'
        f"{escape(eligibility)}</span>"
    )
    rows = (
        ("Effective State", effective_state_badge),
        ("Effective Description", escape(describe_effective_state(effective_state))),
        ("Implementation Action", implementation_badge),
        ("Administrative Status", status_badge),
        ("Administrative Disposition", disposition_badge),
        ("Review Eligibility", eligibility_badge),
    )
    table_rows = "".join(
        "<tr>"
        f"<td>{escape(str(label))}</td>"
        f"<td>{value}</td>"
        "</tr>"
        for label, value in rows
    )
    return f"""
      <section class="management-section effective-state">
        <h2>Stage 10C — Effective State</h2>
        <p class="notice">
          Effective state is derived deterministically from implementation
          action and administrative status values only.
        </p>
        <table>
          <tbody>{table_rows}</tbody>
        </table>
      </section>"""


def _render_outcome_classification(
    evidence_groups: dict[str, list[dict[str, Any]]],
) -> str:
    readiness_values = _record_evidence_readiness_values(evidence_groups)
    readiness = readiness_values["readiness"]
    action = classify_administrative_action(readiness)
    workflow_state = classify_workflow_state(readiness, action)
    disposition = classify_administrative_disposition(workflow_state)
    eligibility = classify_review_eligibility(disposition)
    status_summary = build_administrative_status_summary(
        disposition,
        eligibility,
        workflow_state,
        readiness,
    )
    administrative_status = status_summary["status"]
    implementation_action = classify_implementation_action(
        administrative_status
    )
    effective_state = classify_effective_state(
        implementation_action,
        administrative_status,
    )
    outcome = classify_outcome(effective_state)
    outcome_badge = (
        f'<span class="outcome-badge {_outcome_badge_class(outcome)}">'
        f"{escape(outcome)}</span>"
    )
    effective_state_badge = (
        f'<span class="effective-state-badge {_effective_state_badge_class(effective_state)}">'
        f"{escape(effective_state)}</span>"
    )
    implementation_badge = (
        f'<span class="implementation-action-badge {_implementation_action_badge_class(implementation_action)}">'
        f"{escape(implementation_action)}</span>"
    )
    status_badge = (
        f'<span class="administrative-status-badge {_administrative_status_badge_class(administrative_status)}">'
        f"{escape(administrative_status)}</span>"
    )
    rows = (
        ("Outcome", outcome_badge),
        ("Outcome Description", escape(describe_outcome(outcome))),
        ("Effective State", effective_state_badge),
        ("Implementation Action", implementation_badge),
        ("Administrative Status", status_badge),
    )
    table_rows = "".join(
        "<tr>"
        f"<td>{escape(str(label))}</td>"
        f"<td>{value}</td>"
        "</tr>"
        for label, value in rows
    )
    return f"""
      <section class="management-section outcome-classification">
        <h2>Stage 11A — Outcome Classification</h2>
        <p class="notice">
          Outcome is classified deterministically from effective state values
          only.
        </p>
        <table>
          <tbody>{table_rows}</tbody>
        </table>
      </section>"""


def _render_outcome_basis(
    evidence_groups: dict[str, list[dict[str, Any]]],
) -> str:
    readiness_values = _record_evidence_readiness_values(evidence_groups)
    readiness = readiness_values["readiness"]
    action = classify_administrative_action(readiness)
    workflow_state = classify_workflow_state(readiness, action)
    disposition = classify_administrative_disposition(workflow_state)
    eligibility = classify_review_eligibility(disposition)
    status_summary = build_administrative_status_summary(
        disposition,
        eligibility,
        workflow_state,
        readiness,
    )
    administrative_status = status_summary["status"]
    implementation_action = classify_implementation_action(
        administrative_status
    )
    effective_state = classify_effective_state(
        implementation_action,
        administrative_status,
    )
    outcome = classify_outcome(effective_state)
    trace_steps = build_outcome_basis_trace(
        outcome,
        effective_state,
        implementation_action,
        administrative_status,
    )
    trace_items = "".join(f"<li>{escape(step)}</li>" for step in trace_steps)
    return f"""
      <section class="management-section outcome-basis">
        <h2>Stage 11B — Outcome Basis</h2>
        <p class="notice">
          Outcome basis is derived deterministically from outcome, effective
          state, implementation action, and administrative status values only.
        </p>
        <h3>Outcome Basis</h3>
        <ol class="outcome-basis-list">{trace_items}</ol>
      </section>"""


def _outcome_precondition_target(outcome: str) -> str:
    return {
        "Ongoing Review": "Review Awaiting Determination",
        "Review Awaiting Determination": "Ready For Determination",
        "Ready For Determination": "Determination Completion",
    }.get(outcome, "Review Awaiting Determination")


def _render_outcome_preconditions(
    evidence_groups: dict[str, list[dict[str, Any]]],
) -> str:
    readiness_values = _record_evidence_readiness_values(evidence_groups)
    readiness = readiness_values["readiness"]
    action = classify_administrative_action(readiness)
    workflow_state = classify_workflow_state(readiness, action)
    disposition = classify_administrative_disposition(workflow_state)
    eligibility = classify_review_eligibility(disposition)
    status_summary = build_administrative_status_summary(
        disposition,
        eligibility,
        workflow_state,
        readiness,
    )
    administrative_status = status_summary["status"]
    implementation_action = classify_implementation_action(
        administrative_status
    )
    effective_state = classify_effective_state(
        implementation_action,
        administrative_status,
    )
    outcome = classify_outcome(effective_state)
    preconditions = build_outcome_preconditions(
        outcome,
        effective_state,
        implementation_action,
        administrative_status,
        eligibility,
    )
    precondition_target = _outcome_precondition_target(outcome)
    precondition_items = "".join(
        f"<li>{escape(precondition)}</li>" for precondition in preconditions
    )
    return f"""
      <section class="management-section outcome-preconditions">
        <h2>Stage 11C — Outcome Preconditions</h2>
        <p class="notice">
          Outcome preconditions are derived deterministically from outcome,
          effective state, implementation action, administrative status, and
          review eligibility values only.
        </p>
        <table>
          <tbody>
            <tr><td>Precondition Target</td><td>{escape(precondition_target)}</td></tr>
          </tbody>
        </table>
        <h3>Outcome Preconditions</h3>
        <ol class="outcome-preconditions-list">{precondition_items}</ol>
      </section>"""


def _render_outcome_summary(
    evidence_groups: dict[str, list[dict[str, Any]]],
) -> str:
    readiness_values = _record_evidence_readiness_values(evidence_groups)
    readiness = readiness_values["readiness"]
    action = classify_administrative_action(readiness)
    workflow_state = classify_workflow_state(readiness, action)
    disposition = classify_administrative_disposition(workflow_state)
    eligibility = classify_review_eligibility(disposition)
    status_summary = build_administrative_status_summary(
        disposition,
        eligibility,
        workflow_state,
        readiness,
    )
    administrative_status = status_summary["status"]
    implementation_action = classify_implementation_action(
        administrative_status
    )
    effective_state = classify_effective_state(
        implementation_action,
        administrative_status,
    )
    outcome = classify_outcome(effective_state)
    outcome_basis = build_outcome_basis_trace(
        outcome,
        effective_state,
        implementation_action,
        administrative_status,
    )
    outcome_preconditions = build_outcome_preconditions(
        outcome,
        effective_state,
        implementation_action,
        administrative_status,
        eligibility,
    )
    summary = build_outcome_summary(
        outcome,
        outcome_basis,
        outcome_preconditions,
        effective_state,
        implementation_action,
        administrative_status,
    )
    return f"""
      <section class="management-section outcome-summary">
        <h2>Stage 11D — Outcome Summary</h2>
        <p class="notice">
          Outcome summary is derived deterministically from outcome, effective
          state, implementation action, administrative status, and outcome
          precondition values only.
        </p>
        <table>
          <tbody>
            <tr><td>Outcome Summary</td><td>{escape(summary["outcome"])}</td></tr>
            <tr><td>Summary Description</td><td>{escape(summary["description"])}</td></tr>
          </tbody>
        </table>
      </section>"""


def _render_outcome_readiness(
    evidence_groups: dict[str, list[dict[str, Any]]],
) -> str:
    readiness_values = _record_evidence_readiness_values(evidence_groups)
    readiness = readiness_values["readiness"]
    action = classify_administrative_action(readiness)
    workflow_state = classify_workflow_state(readiness, action)
    disposition = classify_administrative_disposition(workflow_state)
    eligibility = classify_review_eligibility(disposition)
    status_summary = build_administrative_status_summary(
        disposition,
        eligibility,
        workflow_state,
        readiness,
    )
    administrative_status = status_summary["status"]
    implementation_action = classify_implementation_action(
        administrative_status
    )
    effective_state = classify_effective_state(
        implementation_action,
        administrative_status,
    )
    outcome = classify_outcome(effective_state)
    outcome_preconditions = build_outcome_preconditions(
        outcome,
        effective_state,
        implementation_action,
        administrative_status,
        eligibility,
    )
    outcome_readiness = classify_outcome_readiness(
        outcome,
        outcome_preconditions,
        eligibility,
        administrative_status,
        effective_state,
    )
    outcome_readiness_badge = (
        f'<span class="outcome-readiness-badge {_outcome_readiness_badge_class(outcome_readiness)}">'
        f"{escape(outcome_readiness)}</span>"
    )
    outcome_badge = (
        f'<span class="outcome-badge {_outcome_badge_class(outcome)}">'
        f"{escape(outcome)}</span>"
    )
    eligibility_badge = (
        f'<span class="eligibility-badge {_eligibility_badge_class(eligibility)}">'
        f"{escape(eligibility)}</span>"
    )
    effective_state_badge = (
        f'<span class="effective-state-badge {_effective_state_badge_class(effective_state)}">'
        f"{escape(effective_state)}</span>"
    )
    rows = (
        ("Outcome Readiness", outcome_readiness_badge),
        (
            "Readiness Description",
            escape(describe_outcome_readiness(outcome_readiness)),
        ),
        ("Outcome", outcome_badge),
        ("Review Eligibility", eligibility_badge),
        ("Effective State", effective_state_badge),
    )
    table_rows = "".join(
        "<tr>"
        f"<td>{escape(str(label))}</td>"
        f"<td>{value}</td>"
        "</tr>"
        for label, value in rows
    )
    return f"""
      <section class="management-section outcome-readiness">
        <h2>Stage 11E — Outcome Readiness</h2>
        <p class="notice">
          Outcome readiness is classified deterministically from outcome,
          precondition, review eligibility, administrative status, and
          effective state values only.
        </p>
        <table>
          <tbody>{table_rows}</tbody>
        </table>
      </section>"""


def _render_outcome_target(
    evidence_groups: dict[str, list[dict[str, Any]]],
) -> str:
    readiness_values = _record_evidence_readiness_values(evidence_groups)
    readiness = readiness_values["readiness"]
    action = classify_administrative_action(readiness)
    workflow_state = classify_workflow_state(readiness, action)
    disposition = classify_administrative_disposition(workflow_state)
    eligibility = classify_review_eligibility(disposition)
    status_summary = build_administrative_status_summary(
        disposition,
        eligibility,
        workflow_state,
        readiness,
    )
    administrative_status = status_summary["status"]
    implementation_action = classify_implementation_action(
        administrative_status
    )
    effective_state = classify_effective_state(
        implementation_action,
        administrative_status,
    )
    outcome = classify_outcome(effective_state)
    outcome_preconditions = build_outcome_preconditions(
        outcome,
        effective_state,
        implementation_action,
        administrative_status,
        eligibility,
    )
    outcome_readiness = classify_outcome_readiness(
        outcome,
        outcome_preconditions,
        eligibility,
        administrative_status,
        effective_state,
    )
    outcome_target = classify_outcome_target(
        outcome,
        outcome_readiness,
        effective_state,
        eligibility,
        administrative_status,
    )
    outcome_target_badge = (
        f'<span class="outcome-target-badge {_outcome_target_badge_class(outcome_target)}">'
        f"{escape(outcome_target)}</span>"
    )
    outcome_badge = (
        f'<span class="outcome-badge {_outcome_badge_class(outcome)}">'
        f"{escape(outcome)}</span>"
    )
    outcome_readiness_badge = (
        f'<span class="outcome-readiness-badge {_outcome_readiness_badge_class(outcome_readiness)}">'
        f"{escape(outcome_readiness)}</span>"
    )
    effective_state_badge = (
        f'<span class="effective-state-badge {_effective_state_badge_class(effective_state)}">'
        f"{escape(effective_state)}</span>"
    )
    eligibility_badge = (
        f'<span class="eligibility-badge {_eligibility_badge_class(eligibility)}">'
        f"{escape(eligibility)}</span>"
    )
    rows = (
        ("Outcome Target", outcome_target_badge),
        (
            "Target Description",
            escape(describe_outcome_target(outcome_target)),
        ),
        ("Outcome", outcome_badge),
        ("Outcome Readiness", outcome_readiness_badge),
        ("Effective State", effective_state_badge),
        ("Review Eligibility", eligibility_badge),
    )
    table_rows = "".join(
        "<tr>"
        f"<td>{escape(str(label))}</td>"
        f"<td>{value}</td>"
        "</tr>"
        for label, value in rows
    )
    return f"""
      <section class="management-section outcome-target">
        <h2>Stage 11F — Outcome Target</h2>
        <p class="notice">
          Outcome target is classified deterministically from outcome, outcome
          readiness, effective state, review eligibility, and administrative
          status values only.
        </p>
        <table>
          <tbody>{table_rows}</tbody>
        </table>
      </section>"""


def _render_resolution_classification(
    evidence_groups: dict[str, list[dict[str, Any]]],
) -> str:
    readiness_values = _record_evidence_readiness_values(evidence_groups)
    readiness = readiness_values["readiness"]
    action = classify_administrative_action(readiness)
    workflow_state = classify_workflow_state(readiness, action)
    disposition = classify_administrative_disposition(workflow_state)
    eligibility = classify_review_eligibility(disposition)
    status_summary = build_administrative_status_summary(
        disposition,
        eligibility,
        workflow_state,
        readiness,
    )
    administrative_status = status_summary["status"]
    implementation_action = classify_implementation_action(
        administrative_status
    )
    effective_state = classify_effective_state(
        implementation_action,
        administrative_status,
    )
    outcome = classify_outcome(effective_state)
    outcome_preconditions = build_outcome_preconditions(
        outcome,
        effective_state,
        implementation_action,
        administrative_status,
        eligibility,
    )
    outcome_readiness = classify_outcome_readiness(
        outcome,
        outcome_preconditions,
        eligibility,
        administrative_status,
        effective_state,
    )
    outcome_target = classify_outcome_target(
        outcome,
        outcome_readiness,
        effective_state,
        eligibility,
        administrative_status,
    )
    resolution = classify_resolution(
        outcome,
        outcome_readiness,
        outcome_target,
        effective_state,
        implementation_action,
        administrative_status,
    )
    resolution_badge = (
        f'<span class="resolution-badge {_resolution_badge_class(resolution)}">'
        f"{escape(resolution)}</span>"
    )
    outcome_badge = (
        f'<span class="outcome-badge {_outcome_badge_class(outcome)}">'
        f"{escape(outcome)}</span>"
    )
    readiness_badge = (
        f'<span class="outcome-readiness-badge {_outcome_readiness_badge_class(outcome_readiness)}">'
        f"{escape(outcome_readiness)}</span>"
    )
    target_badge = (
        f'<span class="outcome-target-badge {_outcome_target_badge_class(outcome_target)}">'
        f"{escape(outcome_target)}</span>"
    )
    effective_state_badge = (
        f'<span class="effective-state-badge {_effective_state_badge_class(effective_state)}">'
        f"{escape(effective_state)}</span>"
    )
    implementation_badge = (
        f'<span class="implementation-action-badge {_implementation_action_badge_class(implementation_action)}">'
        f"{escape(implementation_action)}</span>"
    )
    status_badge = (
        f'<span class="administrative-status-badge {_administrative_status_badge_class(administrative_status)}">'
        f"{escape(administrative_status)}</span>"
    )
    rows = (
        ("Resolution Classification", resolution_badge),
        ("Resolution Description", escape(describe_resolution(resolution))),
        ("Outcome", outcome_badge),
        ("Outcome Readiness", readiness_badge),
        ("Outcome Target", target_badge),
        ("Effective State", effective_state_badge),
        ("Implementation Action", implementation_badge),
        ("Administrative Status", status_badge),
    )
    table_rows = "".join(
        "<tr>"
        f"<td>{escape(str(label))}</td>"
        f"<td>{value}</td>"
        "</tr>"
        for label, value in rows
    )
    return f"""
      <section class="management-section resolution-classification">
        <h2>Stage 12A — Resolution Classification</h2>
        <p class="notice">
          Resolution is classified deterministically from outcome, outcome
          readiness, outcome target, effective state, implementation action,
          and administrative status values only.
        </p>
        <table>
          <tbody>{table_rows}</tbody>
        </table>
      </section>"""

def _render_resolution_preconditions(
    evidence_groups: dict[str, list[dict[str, Any]]],
) -> str:
    readiness_values = _record_evidence_readiness_values(evidence_groups)
    readiness = readiness_values["readiness"]
    action = classify_administrative_action(readiness)
    workflow_state = classify_workflow_state(readiness, action)
    disposition = classify_administrative_disposition(workflow_state)
    eligibility = classify_review_eligibility(disposition)
    status_summary = build_administrative_status_summary(
        disposition,
        eligibility,
        workflow_state,
        readiness,
    )
    administrative_status = status_summary["status"]
    implementation_action = classify_implementation_action(
        administrative_status
    )
    effective_state = classify_effective_state(
        implementation_action,
        administrative_status,
    )
    outcome = classify_outcome(effective_state)
    outcome_preconditions = build_outcome_preconditions(
        outcome,
        effective_state,
        implementation_action,
        administrative_status,
        eligibility,
    )
    outcome_readiness = classify_outcome_readiness(
        outcome,
        outcome_preconditions,
        eligibility,
        administrative_status,
        effective_state,
    )
    outcome_target = classify_outcome_target(
        outcome,
        outcome_readiness,
        effective_state,
        eligibility,
        administrative_status,
    )
    resolution = classify_resolution(
        outcome,
        outcome_readiness,
        outcome_target,
        effective_state,
        implementation_action,
        administrative_status,
    )
    precondition_target = _resolution_precondition_target(resolution)
    preconditions = build_resolution_preconditions(
        resolution,
        outcome,
        outcome_readiness,
        outcome_target,
        effective_state,
        implementation_action,
        administrative_status,
        eligibility,
    )
    precondition_items = "".join(
        f"<li>{escape(precondition)}</li>" for precondition in preconditions
    )
    resolution_badge = (
        f'<span class="resolution-badge {_resolution_badge_class(resolution)}">'
        f"{escape(resolution)}</span>"
    )
    return f"""
      <section class="management-section resolution-preconditions">
        <h2>Stage 12B — Resolution Preconditions</h2>
        <p class="notice">
          Resolution preconditions are derived deterministically from
          resolution, outcome, readiness, target, effective state,
          implementation action, administrative status, and review eligibility
          values only.
        </p>
        <table>
          <tbody>
            <tr><td>Resolution Classification</td><td>{resolution_badge}</td></tr>
            <tr><td>Precondition Target</td><td>{escape(precondition_target)}</td></tr>
            <tr><td>Precondition Description</td><td>{escape(describe_resolution_preconditions(resolution))}</td></tr>
          </tbody>
        </table>
        <h3>Resolution Preconditions</h3>
        <ol class="resolution-preconditions-list">{precondition_items}</ol>
      </section>"""

def _render_resolution_pathway(
    evidence_groups: dict[str, list[dict[str, Any]]],
) -> str:
    readiness_values = _record_evidence_readiness_values(evidence_groups)
    readiness = readiness_values["readiness"]
    action = classify_administrative_action(readiness)
    workflow_state = classify_workflow_state(readiness, action)
    disposition = classify_administrative_disposition(workflow_state)
    eligibility = classify_review_eligibility(disposition)
    status_summary = build_administrative_status_summary(
        disposition,
        eligibility,
        workflow_state,
        readiness,
    )
    administrative_status = status_summary["status"]
    implementation_action = classify_implementation_action(
        administrative_status
    )
    effective_state = classify_effective_state(
        implementation_action,
        administrative_status,
    )
    outcome = classify_outcome(effective_state)
    outcome_preconditions = build_outcome_preconditions(
        outcome,
        effective_state,
        implementation_action,
        administrative_status,
        eligibility,
    )
    outcome_readiness = classify_outcome_readiness(
        outcome,
        outcome_preconditions,
        eligibility,
        administrative_status,
        effective_state,
    )
    outcome_target = classify_outcome_target(
        outcome,
        outcome_readiness,
        effective_state,
        eligibility,
        administrative_status,
    )
    resolution = classify_resolution(
        outcome,
        outcome_readiness,
        outcome_target,
        effective_state,
        implementation_action,
        administrative_status,
    )
    precondition_target = _resolution_precondition_target(resolution)
    resolution_preconditions = build_resolution_preconditions(
        resolution,
        outcome,
        outcome_readiness,
        outcome_target,
        effective_state,
        implementation_action,
        administrative_status,
        eligibility,
    )
    pathway = _classify_resolution_pathway(
        resolution=resolution,
        resolution_preconditions=resolution_preconditions,
        outcome_target=outcome_target,
        outcome_readiness=outcome_readiness,
        effective_state=effective_state,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
    )
    resolution_badge = (
        f'<span class="resolution-badge {_resolution_badge_class(resolution)}">'
        f"{escape(resolution)}</span>"
    )
    target_badge = (
        f'<span class="outcome-target-badge {_outcome_target_badge_class(outcome_target)}">'
        f"{escape(outcome_target)}</span>"
    )
    readiness_badge = (
        f'<span class="outcome-readiness-badge {_outcome_readiness_badge_class(outcome_readiness)}">'
        f"{escape(outcome_readiness)}</span>"
    )
    effective_state_badge = (
        f'<span class="effective-state-badge {_effective_state_badge_class(effective_state)}">'
        f"{escape(effective_state)}</span>"
    )
    eligibility_badge = (
        f'<span class="eligibility-badge {_eligibility_badge_class(eligibility)}">'
        f"{escape(eligibility)}</span>"
    )
    status_badge = (
        f'<span class="administrative-status-badge {_administrative_status_badge_class(administrative_status)}">'
        f"{escape(administrative_status)}</span>"
    )
    implementation_badge = (
        f'<span class="implementation-action-badge {_implementation_action_badge_class(implementation_action)}">'
        f"{escape(implementation_action)}</span>"
    )
    rows = (
        ("Resolution Pathway", pathway),
        ("Pathway Description", _describe_resolution_pathway(pathway)),
        ("Resolution Classification", resolution_badge),
        ("Resolution Preconditions Target", precondition_target),
        ("Outcome Target", target_badge),
        ("Administrative Status", status_badge),
        ("Review Eligibility", eligibility_badge),
        ("Implementation Action", implementation_badge),
        ("Effective State", effective_state_badge),
    )
    table_rows = "".join(
        "<tr>"
        f"<td>{escape(str(label))}</td>"
        f"<td>{value if label in {'Resolution Classification', 'Outcome Target', 'Administrative Status', 'Review Eligibility', 'Implementation Action', 'Effective State'} else escape(str(value))}</td>"
        "</tr>"
        for label, value in rows
    )
    return f"""
      <section class="management-section resolution-pathway">
        <h2>Stage 12C — Resolution Pathway</h2>
        <p class="notice">
          Resolution pathway identifies the deterministic sequence of
          administrative state transitions required before the current matter
          can advance toward resolution.
        </p>
        <table>
          <tbody>{table_rows}</tbody>
        </table>
      </section>"""

def _render_resolution_readiness(
    evidence_groups: dict[str, list[dict[str, Any]]],
) -> str:
    readiness_values = _record_evidence_readiness_values(evidence_groups)
    readiness = readiness_values["readiness"]
    action = classify_administrative_action(readiness)
    workflow_state = classify_workflow_state(readiness, action)
    disposition = classify_administrative_disposition(workflow_state)
    eligibility = classify_review_eligibility(disposition)
    status_summary = build_administrative_status_summary(
        disposition,
        eligibility,
        workflow_state,
        readiness,
    )
    administrative_status = status_summary["status"]
    implementation_action = classify_implementation_action(
        administrative_status
    )
    effective_state = classify_effective_state(
        implementation_action,
        administrative_status,
    )
    outcome = classify_outcome(effective_state)
    outcome_preconditions = build_outcome_preconditions(
        outcome,
        effective_state,
        implementation_action,
        administrative_status,
        eligibility,
    )
    outcome_readiness = classify_outcome_readiness(
        outcome,
        outcome_preconditions,
        eligibility,
        administrative_status,
        effective_state,
    )
    outcome_target = classify_outcome_target(
        outcome,
        outcome_readiness,
        effective_state,
        eligibility,
        administrative_status,
    )
    resolution = classify_resolution(
        outcome,
        outcome_readiness,
        outcome_target,
        effective_state,
        implementation_action,
        administrative_status,
    )
    resolution_preconditions = build_resolution_preconditions(
        resolution,
        outcome,
        outcome_readiness,
        outcome_target,
        effective_state,
        implementation_action,
        administrative_status,
        eligibility,
    )
    resolution_pathway = _classify_resolution_pathway(
        resolution=resolution,
        resolution_preconditions=resolution_preconditions,
        outcome_target=outcome_target,
        outcome_readiness=outcome_readiness,
        effective_state=effective_state,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
    )
    resolution_readiness = _classify_resolution_readiness(
        resolution=resolution,
        resolution_preconditions=resolution_preconditions,
        resolution_pathway=resolution_pathway,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    readiness_badge = (
        f'<span class="resolution-readiness-badge {_resolution_readiness_badge_class(resolution_readiness)}">'
        f"{escape(resolution_readiness)}</span>"
    )
    resolution_badge = (
        f'<span class="resolution-badge {_resolution_badge_class(resolution)}">'
        f"{escape(resolution)}</span>"
    )
    outcome_readiness_badge = (
        f'<span class="outcome-readiness-badge {_outcome_readiness_badge_class(outcome_readiness)}">'
        f"{escape(outcome_readiness)}</span>"
    )
    eligibility_badge = (
        f'<span class="eligibility-badge {_eligibility_badge_class(eligibility)}">'
        f"{escape(eligibility)}</span>"
    )
    status_badge = (
        f'<span class="administrative-status-badge {_administrative_status_badge_class(administrative_status)}">'
        f"{escape(administrative_status)}</span>"
    )
    implementation_badge = (
        f'<span class="implementation-action-badge {_implementation_action_badge_class(implementation_action)}">'
        f"{escape(implementation_action)}</span>"
    )
    effective_state_badge = (
        f'<span class="effective-state-badge {_effective_state_badge_class(effective_state)}">'
        f"{escape(effective_state)}</span>"
    )
    rows = (
        ("Resolution Readiness", readiness_badge),
        (
            "Readiness Description",
            escape(_describe_resolution_readiness(resolution_readiness)),
        ),
        ("Resolution Classification", resolution_badge),
        ("Resolution Pathway", resolution_pathway),
        ("Outcome Readiness", outcome_readiness_badge),
        ("Review Eligibility", eligibility_badge),
        ("Administrative Status", status_badge),
        ("Implementation Action", implementation_badge),
        ("Effective State", effective_state_badge),
    )
    badge_labels = {
        "Resolution Readiness",
        "Resolution Classification",
        "Outcome Readiness",
        "Review Eligibility",
        "Administrative Status",
        "Implementation Action",
        "Effective State",
    }
    table_rows = "".join(
        "<tr>"
        f"<td>{escape(str(label))}</td>"
        f"<td>{value if label in badge_labels else escape(str(value))}</td>"
        "</tr>"
        for label, value in rows
    )
    return f"""
      <section class="management-section resolution-readiness">
        <h2>Stage 12D — Resolution Readiness</h2>
        <p class="notice">
          Resolution readiness is classified deterministically from resolution,
          precondition, pathway, outcome readiness, review eligibility,
          administrative status, implementation action, and effective state
          values only.
        </p>
        <table>
          <tbody>{table_rows}</tbody>
        </table>
      </section>"""

def _render_resolution_determination(
    evidence_groups: dict[str, list[dict[str, Any]]],
) -> str:
    readiness_values = _record_evidence_readiness_values(evidence_groups)
    readiness = readiness_values["readiness"]
    action = classify_administrative_action(readiness)
    workflow_state = classify_workflow_state(readiness, action)
    disposition = classify_administrative_disposition(workflow_state)
    eligibility = classify_review_eligibility(disposition)
    status_summary = build_administrative_status_summary(
        disposition,
        eligibility,
        workflow_state,
        readiness,
    )
    administrative_status = status_summary["status"]
    implementation_action = classify_implementation_action(
        administrative_status
    )
    effective_state = classify_effective_state(
        implementation_action,
        administrative_status,
    )
    outcome = classify_outcome(effective_state)
    outcome_preconditions = build_outcome_preconditions(
        outcome,
        effective_state,
        implementation_action,
        administrative_status,
        eligibility,
    )
    outcome_readiness = classify_outcome_readiness(
        outcome,
        outcome_preconditions,
        eligibility,
        administrative_status,
        effective_state,
    )
    outcome_target = classify_outcome_target(
        outcome,
        outcome_readiness,
        effective_state,
        eligibility,
        administrative_status,
    )
    resolution = classify_resolution(
        outcome,
        outcome_readiness,
        outcome_target,
        effective_state,
        implementation_action,
        administrative_status,
    )
    resolution_preconditions = build_resolution_preconditions(
        resolution,
        outcome,
        outcome_readiness,
        outcome_target,
        effective_state,
        implementation_action,
        administrative_status,
        eligibility,
    )
    resolution_pathway = _classify_resolution_pathway(
        resolution=resolution,
        resolution_preconditions=resolution_preconditions,
        outcome_target=outcome_target,
        outcome_readiness=outcome_readiness,
        effective_state=effective_state,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
    )
    resolution_readiness = _classify_resolution_readiness(
        resolution=resolution,
        resolution_preconditions=resolution_preconditions,
        resolution_pathway=resolution_pathway,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    determination = _classify_resolution_determination(
        resolution=resolution,
        resolution_preconditions=resolution_preconditions,
        resolution_pathway=resolution_pathway,
        resolution_readiness=resolution_readiness,
        outcome_target=outcome_target,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    determination_badge = (
        f'<span class="resolution-determination-badge {_resolution_determination_badge_class(determination)}">'
        f"{escape(determination)}</span>"
    )
    resolution_badge = (
        f'<span class="resolution-badge {_resolution_badge_class(resolution)}">'
        f"{escape(resolution)}</span>"
    )
    readiness_badge = (
        f'<span class="resolution-readiness-badge {_resolution_readiness_badge_class(resolution_readiness)}">'
        f"{escape(resolution_readiness)}</span>"
    )
    outcome_target_badge = (
        f'<span class="outcome-target-badge {_outcome_target_badge_class(outcome_target)}">'
        f"{escape(outcome_target)}</span>"
    )
    outcome_readiness_badge = (
        f'<span class="outcome-readiness-badge {_outcome_readiness_badge_class(outcome_readiness)}">'
        f"{escape(outcome_readiness)}</span>"
    )
    eligibility_badge = (
        f'<span class="eligibility-badge {_eligibility_badge_class(eligibility)}">'
        f"{escape(eligibility)}</span>"
    )
    status_badge = (
        f'<span class="administrative-status-badge {_administrative_status_badge_class(administrative_status)}">'
        f"{escape(administrative_status)}</span>"
    )
    implementation_badge = (
        f'<span class="implementation-action-badge {_implementation_action_badge_class(implementation_action)}">'
        f"{escape(implementation_action)}</span>"
    )
    effective_state_badge = (
        f'<span class="effective-state-badge {_effective_state_badge_class(effective_state)}">'
        f"{escape(effective_state)}</span>"
    )
    rows = (
        ("Resolution Determination", determination_badge),
        (
            "Determination Description",
            escape(_describe_resolution_determination(determination)),
        ),
        ("Resolution Classification", resolution_badge),
        ("Resolution Readiness", readiness_badge),
        ("Resolution Pathway", resolution_pathway),
        ("Outcome Target", outcome_target_badge),
        ("Outcome Readiness", outcome_readiness_badge),
        ("Review Eligibility", eligibility_badge),
        ("Administrative Status", status_badge),
        ("Implementation Action", implementation_badge),
        ("Effective State", effective_state_badge),
    )
    badge_labels = {
        "Resolution Determination",
        "Resolution Classification",
        "Resolution Readiness",
        "Outcome Target",
        "Outcome Readiness",
        "Review Eligibility",
        "Administrative Status",
        "Implementation Action",
        "Effective State",
    }
    table_rows = "".join(
        "<tr>"
        f"<td>{escape(str(label))}</td>"
        f"<td>{value if label in badge_labels else escape(str(value))}</td>"
        "</tr>"
        for label, value in rows
    )
    return f"""
      <section class="management-section resolution-determination">
        <h2>Stage 12E — Resolution Determination</h2>
        <p class="notice">
          Resolution determination is classified deterministically from
          resolution, pathway, readiness, outcome, review eligibility,
          administrative status, implementation action, and effective state
          values only.
        </p>
        <table>
          <tbody>{table_rows}</tbody>
        </table>
      </section>"""

def _render_resolution_completion(
    evidence_groups: dict[str, list[dict[str, Any]]],
) -> str:
    readiness_values = _record_evidence_readiness_values(evidence_groups)
    readiness = readiness_values["readiness"]
    action = classify_administrative_action(readiness)
    workflow_state = classify_workflow_state(readiness, action)
    disposition = classify_administrative_disposition(workflow_state)
    eligibility = classify_review_eligibility(disposition)
    status_summary = build_administrative_status_summary(
        disposition,
        eligibility,
        workflow_state,
        readiness,
    )
    administrative_status = status_summary["status"]
    implementation_action = classify_implementation_action(
        administrative_status
    )
    effective_state = classify_effective_state(
        implementation_action,
        administrative_status,
    )
    outcome = classify_outcome(effective_state)
    outcome_preconditions = build_outcome_preconditions(
        outcome,
        effective_state,
        implementation_action,
        administrative_status,
        eligibility,
    )
    outcome_readiness = classify_outcome_readiness(
        outcome,
        outcome_preconditions,
        eligibility,
        administrative_status,
        effective_state,
    )
    outcome_target = classify_outcome_target(
        outcome,
        outcome_readiness,
        effective_state,
        eligibility,
        administrative_status,
    )
    resolution = classify_resolution(
        outcome,
        outcome_readiness,
        outcome_target,
        effective_state,
        implementation_action,
        administrative_status,
    )
    resolution_preconditions = build_resolution_preconditions(
        resolution,
        outcome,
        outcome_readiness,
        outcome_target,
        effective_state,
        implementation_action,
        administrative_status,
        eligibility,
    )
    resolution_pathway = _classify_resolution_pathway(
        resolution=resolution,
        resolution_preconditions=resolution_preconditions,
        outcome_target=outcome_target,
        outcome_readiness=outcome_readiness,
        effective_state=effective_state,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
    )
    resolution_readiness = _classify_resolution_readiness(
        resolution=resolution,
        resolution_preconditions=resolution_preconditions,
        resolution_pathway=resolution_pathway,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    determination = _classify_resolution_determination(
        resolution=resolution,
        resolution_preconditions=resolution_preconditions,
        resolution_pathway=resolution_pathway,
        resolution_readiness=resolution_readiness,
        outcome_target=outcome_target,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    completion = _classify_resolution_completion(
        resolution=resolution,
        resolution_preconditions=resolution_preconditions,
        resolution_pathway=resolution_pathway,
        resolution_readiness=resolution_readiness,
        resolution_determination=determination,
        outcome_target=outcome_target,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    completion_badge = (
        f'<span class="resolution-completion-badge {_resolution_completion_badge_class(completion)}">'
        f"{escape(completion)}</span>"
    )
    resolution_badge = (
        f'<span class="resolution-badge {_resolution_badge_class(resolution)}">'
        f"{escape(resolution)}</span>"
    )
    determination_badge = (
        f'<span class="resolution-determination-badge {_resolution_determination_badge_class(determination)}">'
        f"{escape(determination)}</span>"
    )
    readiness_badge = (
        f'<span class="resolution-readiness-badge {_resolution_readiness_badge_class(resolution_readiness)}">'
        f"{escape(resolution_readiness)}</span>"
    )
    outcome_target_badge = (
        f'<span class="outcome-target-badge {_outcome_target_badge_class(outcome_target)}">'
        f"{escape(outcome_target)}</span>"
    )
    outcome_readiness_badge = (
        f'<span class="outcome-readiness-badge {_outcome_readiness_badge_class(outcome_readiness)}">'
        f"{escape(outcome_readiness)}</span>"
    )
    eligibility_badge = (
        f'<span class="eligibility-badge {_eligibility_badge_class(eligibility)}">'
        f"{escape(eligibility)}</span>"
    )
    status_badge = (
        f'<span class="administrative-status-badge {_administrative_status_badge_class(administrative_status)}">'
        f"{escape(administrative_status)}</span>"
    )
    implementation_badge = (
        f'<span class="implementation-action-badge {_implementation_action_badge_class(implementation_action)}">'
        f"{escape(implementation_action)}</span>"
    )
    effective_state_badge = (
        f'<span class="effective-state-badge {_effective_state_badge_class(effective_state)}">'
        f"{escape(effective_state)}</span>"
    )
    rows = (
        ("Resolution Completion", completion_badge),
        (
            "Completion Description",
            escape(_describe_resolution_completion(completion)),
        ),
        ("Resolution Classification", resolution_badge),
        ("Resolution Determination", determination_badge),
        ("Resolution Readiness", readiness_badge),
        ("Resolution Pathway", resolution_pathway),
        ("Outcome Target", outcome_target_badge),
        ("Outcome Readiness", outcome_readiness_badge),
        ("Review Eligibility", eligibility_badge),
        ("Administrative Status", status_badge),
        ("Implementation Action", implementation_badge),
        ("Effective State", effective_state_badge),
    )
    badge_labels = {
        "Resolution Completion",
        "Resolution Classification",
        "Resolution Determination",
        "Resolution Readiness",
        "Outcome Target",
        "Outcome Readiness",
        "Review Eligibility",
        "Administrative Status",
        "Implementation Action",
        "Effective State",
    }
    table_rows = "".join(
        "<tr>"
        f"<td>{escape(str(label))}</td>"
        f"<td>{value if label in badge_labels else escape(str(value))}</td>"
        "</tr>"
        for label, value in rows
    )
    return f"""
      <section class="management-section resolution-completion">
        <h2>Stage 12F — Resolution Completion</h2>
        <p class="notice">
          Resolution completion is classified deterministically from
          resolution, precondition, pathway, readiness, determination,
          outcome, review eligibility, administrative status, implementation
          action, and effective state values only.
        </p>
        <table>
          <tbody>{table_rows}</tbody>
        </table>
      </section>"""


def _render_closure_classification(
    evidence_groups: dict[str, list[dict[str, Any]]],
) -> str:
    readiness_values = _record_evidence_readiness_values(evidence_groups)
    readiness = readiness_values["readiness"]
    action = classify_administrative_action(readiness)
    workflow_state = classify_workflow_state(readiness, action)
    disposition = classify_administrative_disposition(workflow_state)
    eligibility = classify_review_eligibility(disposition)
    status_summary = build_administrative_status_summary(
        disposition,
        eligibility,
        workflow_state,
        readiness,
    )
    administrative_status = status_summary["status"]
    implementation_action = classify_implementation_action(
        administrative_status
    )
    effective_state = classify_effective_state(
        implementation_action,
        administrative_status,
    )
    outcome = classify_outcome(effective_state)
    outcome_preconditions = build_outcome_preconditions(
        outcome,
        effective_state,
        implementation_action,
        administrative_status,
        eligibility,
    )
    outcome_readiness = classify_outcome_readiness(
        outcome,
        outcome_preconditions,
        eligibility,
        administrative_status,
        effective_state,
    )
    outcome_target = classify_outcome_target(
        outcome,
        outcome_readiness,
        effective_state,
        eligibility,
        administrative_status,
    )
    resolution = classify_resolution(
        outcome,
        outcome_readiness,
        outcome_target,
        effective_state,
        implementation_action,
        administrative_status,
    )
    resolution_preconditions = build_resolution_preconditions(
        resolution,
        outcome,
        outcome_readiness,
        outcome_target,
        effective_state,
        implementation_action,
        administrative_status,
        eligibility,
    )
    resolution_pathway = _classify_resolution_pathway(
        resolution=resolution,
        resolution_preconditions=resolution_preconditions,
        outcome_target=outcome_target,
        outcome_readiness=outcome_readiness,
        effective_state=effective_state,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
    )
    resolution_readiness = _classify_resolution_readiness(
        resolution=resolution,
        resolution_preconditions=resolution_preconditions,
        resolution_pathway=resolution_pathway,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    determination = _classify_resolution_determination(
        resolution=resolution,
        resolution_preconditions=resolution_preconditions,
        resolution_pathway=resolution_pathway,
        resolution_readiness=resolution_readiness,
        outcome_target=outcome_target,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    completion = _classify_resolution_completion(
        resolution=resolution,
        resolution_preconditions=resolution_preconditions,
        resolution_pathway=resolution_pathway,
        resolution_readiness=resolution_readiness,
        resolution_determination=determination,
        outcome_target=outcome_target,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    closure = _classify_closure(
        resolution=resolution,
        resolution_completion=completion,
        resolution_determination=determination,
        resolution_readiness=resolution_readiness,
        resolution_pathway=resolution_pathway,
        outcome_target=outcome_target,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    closure_badge = (
        f'<span class="closure-badge {_closure_badge_class(closure)}">'
        f"{escape(closure)}</span>"
    )
    resolution_badge = (
        f'<span class="resolution-badge {_resolution_badge_class(resolution)}">'
        f"{escape(resolution)}</span>"
    )
    completion_badge = (
        f'<span class="resolution-completion-badge {_resolution_completion_badge_class(completion)}">'
        f"{escape(completion)}</span>"
    )
    determination_badge = (
        f'<span class="resolution-determination-badge {_resolution_determination_badge_class(determination)}">'
        f"{escape(determination)}</span>"
    )
    readiness_badge = (
        f'<span class="resolution-readiness-badge {_resolution_readiness_badge_class(resolution_readiness)}">'
        f"{escape(resolution_readiness)}</span>"
    )
    outcome_target_badge = (
        f'<span class="outcome-target-badge {_outcome_target_badge_class(outcome_target)}">'
        f"{escape(outcome_target)}</span>"
    )
    status_badge = (
        f'<span class="administrative-status-badge {_administrative_status_badge_class(administrative_status)}">'
        f"{escape(administrative_status)}</span>"
    )
    implementation_badge = (
        f'<span class="implementation-action-badge {_implementation_action_badge_class(implementation_action)}">'
        f"{escape(implementation_action)}</span>"
    )
    effective_state_badge = (
        f'<span class="effective-state-badge {_effective_state_badge_class(effective_state)}">'
        f"{escape(effective_state)}</span>"
    )
    rows = (
        ("Closure Classification", closure_badge),
        ("Closure Description", escape(_describe_closure(closure))),
        ("Resolution Classification", resolution_badge),
        ("Resolution Completion", completion_badge),
        ("Resolution Determination", determination_badge),
        ("Resolution Readiness", readiness_badge),
        ("Resolution Pathway", resolution_pathway),
        ("Outcome Target", outcome_target_badge),
        ("Administrative Status", status_badge),
        ("Implementation Action", implementation_badge),
        ("Effective State", effective_state_badge),
    )
    badge_labels = {
        "Closure Classification",
        "Resolution Classification",
        "Resolution Completion",
        "Resolution Determination",
        "Resolution Readiness",
        "Outcome Target",
        "Administrative Status",
        "Implementation Action",
        "Effective State",
    }
    table_rows = "".join(
        "<tr>"
        f"<td>{escape(str(label))}</td>"
        f"<td>{value if label in badge_labels else escape(str(value))}</td>"
        "</tr>"
        for label, value in rows
    )
    return f"""
      <section class="management-section closure-classification">
        <h2>Stage 13A — Closure Classification</h2>
        <p class="notice">
          Closure is classified deterministically from resolution, completion,
          determination, pathway, outcome, administrative status,
          implementation action, and effective state values only.
        </p>
        <table>
          <tbody>{table_rows}</tbody>
        </table>
      </section>"""


def _render_closure_preconditions(
    evidence_groups: dict[str, list[dict[str, Any]]],
) -> str:
    readiness_values = _record_evidence_readiness_values(evidence_groups)
    readiness = readiness_values["readiness"]
    action = classify_administrative_action(readiness)
    workflow_state = classify_workflow_state(readiness, action)
    disposition = classify_administrative_disposition(workflow_state)
    eligibility = classify_review_eligibility(disposition)
    status_summary = build_administrative_status_summary(
        disposition,
        eligibility,
        workflow_state,
        readiness,
    )
    administrative_status = status_summary["status"]
    implementation_action = classify_implementation_action(
        administrative_status
    )
    effective_state = classify_effective_state(
        implementation_action,
        administrative_status,
    )
    outcome = classify_outcome(effective_state)
    outcome_preconditions = build_outcome_preconditions(
        outcome,
        effective_state,
        implementation_action,
        administrative_status,
        eligibility,
    )
    outcome_readiness = classify_outcome_readiness(
        outcome,
        outcome_preconditions,
        eligibility,
        administrative_status,
        effective_state,
    )
    outcome_target = classify_outcome_target(
        outcome,
        outcome_readiness,
        effective_state,
        eligibility,
        administrative_status,
    )
    resolution = classify_resolution(
        outcome,
        outcome_readiness,
        outcome_target,
        effective_state,
        implementation_action,
        administrative_status,
    )
    resolution_preconditions = build_resolution_preconditions(
        resolution,
        outcome,
        outcome_readiness,
        outcome_target,
        effective_state,
        implementation_action,
        administrative_status,
        eligibility,
    )
    resolution_pathway = _classify_resolution_pathway(
        resolution=resolution,
        resolution_preconditions=resolution_preconditions,
        outcome_target=outcome_target,
        outcome_readiness=outcome_readiness,
        effective_state=effective_state,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
    )
    resolution_readiness = _classify_resolution_readiness(
        resolution=resolution,
        resolution_preconditions=resolution_preconditions,
        resolution_pathway=resolution_pathway,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    determination = _classify_resolution_determination(
        resolution=resolution,
        resolution_preconditions=resolution_preconditions,
        resolution_pathway=resolution_pathway,
        resolution_readiness=resolution_readiness,
        outcome_target=outcome_target,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    completion = _classify_resolution_completion(
        resolution=resolution,
        resolution_preconditions=resolution_preconditions,
        resolution_pathway=resolution_pathway,
        resolution_readiness=resolution_readiness,
        resolution_determination=determination,
        outcome_target=outcome_target,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    closure = _classify_closure(
        resolution=resolution,
        resolution_completion=completion,
        resolution_determination=determination,
        resolution_readiness=resolution_readiness,
        resolution_pathway=resolution_pathway,
        outcome_target=outcome_target,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    closure_preconditions = _classify_closure_preconditions(
        closure=closure,
        resolution=resolution,
        resolution_completion=completion,
        resolution_determination=determination,
        resolution_readiness=resolution_readiness,
        resolution_pathway=resolution_pathway,
        outcome_target=outcome_target,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    precondition_items = _closure_precondition_items(
        closure_preconditions=closure_preconditions,
        resolution_completion=completion,
        resolution_determination=determination,
        resolution_readiness=resolution_readiness,
        administrative_status=administrative_status,
        effective_state=effective_state,
    )
    precondition_badge = (
        f'<span class="closure-precondition-badge {_closure_precondition_badge_class(closure_preconditions)}">'
        f"{escape(closure_preconditions)}</span>"
    )
    closure_badge = (
        f'<span class="closure-badge {_closure_badge_class(closure)}">'
        f"{escape(closure)}</span>"
    )
    resolution_badge = (
        f'<span class="resolution-badge {_resolution_badge_class(resolution)}">'
        f"{escape(resolution)}</span>"
    )
    completion_badge = (
        f'<span class="resolution-completion-badge {_resolution_completion_badge_class(completion)}">'
        f"{escape(completion)}</span>"
    )
    determination_badge = (
        f'<span class="resolution-determination-badge {_resolution_determination_badge_class(determination)}">'
        f"{escape(determination)}</span>"
    )
    readiness_badge = (
        f'<span class="resolution-readiness-badge {_resolution_readiness_badge_class(resolution_readiness)}">'
        f"{escape(resolution_readiness)}</span>"
    )
    outcome_target_badge = (
        f'<span class="outcome-target-badge {_outcome_target_badge_class(outcome_target)}">'
        f"{escape(outcome_target)}</span>"
    )
    status_badge = (
        f'<span class="administrative-status-badge {_administrative_status_badge_class(administrative_status)}">'
        f"{escape(administrative_status)}</span>"
    )
    implementation_badge = (
        f'<span class="implementation-action-badge {_implementation_action_badge_class(implementation_action)}">'
        f"{escape(implementation_action)}</span>"
    )
    effective_state_badge = (
        f'<span class="effective-state-badge {_effective_state_badge_class(effective_state)}">'
        f"{escape(effective_state)}</span>"
    )
    rows = (
        ("Closure Preconditions", precondition_badge),
        (
            "Precondition Description",
            escape(_describe_closure_preconditions(closure_preconditions)),
        ),
        ("Closure Classification", closure_badge),
        ("Resolution Classification", resolution_badge),
        ("Resolution Completion", completion_badge),
        ("Resolution Determination", determination_badge),
        ("Resolution Readiness", readiness_badge),
        ("Resolution Pathway", resolution_pathway),
        ("Outcome Target", outcome_target_badge),
        ("Administrative Status", status_badge),
        ("Implementation Action", implementation_badge),
        ("Effective State", effective_state_badge),
    )
    badge_labels = {
        "Closure Preconditions",
        "Closure Classification",
        "Resolution Classification",
        "Resolution Completion",
        "Resolution Determination",
        "Resolution Readiness",
        "Outcome Target",
        "Administrative Status",
        "Implementation Action",
        "Effective State",
    }
    table_rows = "".join(
        "<tr>"
        f"<td>{escape(str(label))}</td>"
        f"<td>{value if label in badge_labels else escape(str(value))}</td>"
        "</tr>"
        for label, value in rows
    )
    precondition_rows = "".join(
        f"<li>{escape(item)}</li>" for item in precondition_items
    )
    return f"""
      <section class="management-section closure-preconditions">
        <h2>Stage 13B — Closure Preconditions</h2>
        <p class="notice">
          Closure preconditions are derived deterministically from closure,
          resolution, completion, determination, pathway, outcome,
          administrative status, implementation action, and effective state
          values only.
        </p>
        <table>
          <tbody>{table_rows}</tbody>
        </table>
        <h3>Closure Preconditions</h3>
        <ol class="closure-preconditions-list">{precondition_rows}</ol>
      </section>"""


def _render_closure_pathway(
    evidence_groups: dict[str, list[dict[str, Any]]],
) -> str:
    readiness_values = _record_evidence_readiness_values(evidence_groups)
    readiness = readiness_values["readiness"]
    action = classify_administrative_action(readiness)
    workflow_state = classify_workflow_state(readiness, action)
    disposition = classify_administrative_disposition(workflow_state)
    eligibility = classify_review_eligibility(disposition)
    status_summary = build_administrative_status_summary(
        disposition,
        eligibility,
        workflow_state,
        readiness,
    )
    administrative_status = status_summary["status"]
    implementation_action = classify_implementation_action(
        administrative_status
    )
    effective_state = classify_effective_state(
        implementation_action,
        administrative_status,
    )
    outcome = classify_outcome(effective_state)
    outcome_preconditions = build_outcome_preconditions(
        outcome,
        effective_state,
        implementation_action,
        administrative_status,
        eligibility,
    )
    outcome_readiness = classify_outcome_readiness(
        outcome,
        outcome_preconditions,
        eligibility,
        administrative_status,
        effective_state,
    )
    outcome_target = classify_outcome_target(
        outcome,
        outcome_readiness,
        effective_state,
        eligibility,
        administrative_status,
    )
    resolution = classify_resolution(
        outcome,
        outcome_readiness,
        outcome_target,
        effective_state,
        implementation_action,
        administrative_status,
    )
    resolution_preconditions = build_resolution_preconditions(
        resolution,
        outcome,
        outcome_readiness,
        outcome_target,
        effective_state,
        implementation_action,
        administrative_status,
        eligibility,
    )
    resolution_pathway = _classify_resolution_pathway(
        resolution=resolution,
        resolution_preconditions=resolution_preconditions,
        outcome_target=outcome_target,
        outcome_readiness=outcome_readiness,
        effective_state=effective_state,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
    )
    resolution_readiness = _classify_resolution_readiness(
        resolution=resolution,
        resolution_preconditions=resolution_preconditions,
        resolution_pathway=resolution_pathway,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    determination = _classify_resolution_determination(
        resolution=resolution,
        resolution_preconditions=resolution_preconditions,
        resolution_pathway=resolution_pathway,
        resolution_readiness=resolution_readiness,
        outcome_target=outcome_target,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    completion = _classify_resolution_completion(
        resolution=resolution,
        resolution_preconditions=resolution_preconditions,
        resolution_pathway=resolution_pathway,
        resolution_readiness=resolution_readiness,
        resolution_determination=determination,
        outcome_target=outcome_target,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    closure = _classify_closure(
        resolution=resolution,
        resolution_completion=completion,
        resolution_determination=determination,
        resolution_readiness=resolution_readiness,
        resolution_pathway=resolution_pathway,
        outcome_target=outcome_target,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    closure_preconditions = _classify_closure_preconditions(
        closure=closure,
        resolution=resolution,
        resolution_completion=completion,
        resolution_determination=determination,
        resolution_readiness=resolution_readiness,
        resolution_pathway=resolution_pathway,
        outcome_target=outcome_target,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    closure_pathway = _classify_closure_pathway(
        closure=closure,
        closure_preconditions=closure_preconditions,
        resolution=resolution,
        resolution_completion=completion,
        resolution_determination=determination,
        resolution_readiness=resolution_readiness,
        resolution_pathway=resolution_pathway,
        outcome_target=outcome_target,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    pathway_badge = (
        f'<span class="closure-pathway-badge {_closure_pathway_badge_class(closure_pathway)}">'
        f"{escape(closure_pathway)}</span>"
    )
    closure_badge = (
        f'<span class="closure-badge {_closure_badge_class(closure)}">'
        f"{escape(closure)}</span>"
    )
    precondition_badge = (
        f'<span class="closure-precondition-badge {_closure_precondition_badge_class(closure_preconditions)}">'
        f"{escape(closure_preconditions)}</span>"
    )
    resolution_badge = (
        f'<span class="resolution-badge {_resolution_badge_class(resolution)}">'
        f"{escape(resolution)}</span>"
    )
    completion_badge = (
        f'<span class="resolution-completion-badge {_resolution_completion_badge_class(completion)}">'
        f"{escape(completion)}</span>"
    )
    determination_badge = (
        f'<span class="resolution-determination-badge {_resolution_determination_badge_class(determination)}">'
        f"{escape(determination)}</span>"
    )
    readiness_badge = (
        f'<span class="resolution-readiness-badge {_resolution_readiness_badge_class(resolution_readiness)}">'
        f"{escape(resolution_readiness)}</span>"
    )
    outcome_target_badge = (
        f'<span class="outcome-target-badge {_outcome_target_badge_class(outcome_target)}">'
        f"{escape(outcome_target)}</span>"
    )
    status_badge = (
        f'<span class="administrative-status-badge {_administrative_status_badge_class(administrative_status)}">'
        f"{escape(administrative_status)}</span>"
    )
    implementation_badge = (
        f'<span class="implementation-action-badge {_implementation_action_badge_class(implementation_action)}">'
        f"{escape(implementation_action)}</span>"
    )
    effective_state_badge = (
        f'<span class="effective-state-badge {_effective_state_badge_class(effective_state)}">'
        f"{escape(effective_state)}</span>"
    )
    rows = (
        ("Closure Pathway", pathway_badge),
        ("Pathway Description", escape(_describe_closure_pathway(closure_pathway))),
        ("Closure Classification", closure_badge),
        ("Closure Preconditions", precondition_badge),
        ("Resolution Classification", resolution_badge),
        ("Resolution Completion", completion_badge),
        ("Resolution Determination", determination_badge),
        ("Resolution Readiness", readiness_badge),
        ("Resolution Pathway", resolution_pathway),
        ("Outcome Target", outcome_target_badge),
        ("Administrative Status", status_badge),
        ("Implementation Action", implementation_badge),
        ("Effective State", effective_state_badge),
    )
    badge_labels = {
        "Closure Pathway",
        "Closure Classification",
        "Closure Preconditions",
        "Resolution Classification",
        "Resolution Completion",
        "Resolution Determination",
        "Resolution Readiness",
        "Outcome Target",
        "Administrative Status",
        "Implementation Action",
        "Effective State",
    }
    table_rows = "".join(
        "<tr>"
        f"<td>{escape(str(label))}</td>"
        f"<td>{value if label in badge_labels else escape(str(value))}</td>"
        "</tr>"
        for label, value in rows
    )
    return f"""
      <section class="management-section closure-pathway">
        <h2>Stage 13C — Closure Pathway</h2>
        <p class="notice">
          Closure pathway identifies the deterministic sequence of
          administrative closure transitions required before the matter can
          reach closure.
        </p>
        <table>
          <tbody>{table_rows}</tbody>
        </table>
      </section>"""


def _render_closure_readiness(
    evidence_groups: dict[str, list[dict[str, Any]]],
) -> str:
    readiness_values = _record_evidence_readiness_values(evidence_groups)
    readiness = readiness_values["readiness"]
    action = classify_administrative_action(readiness)
    workflow_state = classify_workflow_state(readiness, action)
    disposition = classify_administrative_disposition(workflow_state)
    eligibility = classify_review_eligibility(disposition)
    status_summary = build_administrative_status_summary(
        disposition,
        eligibility,
        workflow_state,
        readiness,
    )
    administrative_status = status_summary["status"]
    implementation_action = classify_implementation_action(
        administrative_status
    )
    effective_state = classify_effective_state(
        implementation_action,
        administrative_status,
    )
    outcome = classify_outcome(effective_state)
    outcome_preconditions = build_outcome_preconditions(
        outcome,
        effective_state,
        implementation_action,
        administrative_status,
        eligibility,
    )
    outcome_readiness = classify_outcome_readiness(
        outcome,
        outcome_preconditions,
        eligibility,
        administrative_status,
        effective_state,
    )
    outcome_target = classify_outcome_target(
        outcome,
        outcome_readiness,
        effective_state,
        eligibility,
        administrative_status,
    )
    resolution = classify_resolution(
        outcome,
        outcome_readiness,
        outcome_target,
        effective_state,
        implementation_action,
        administrative_status,
    )
    resolution_preconditions = build_resolution_preconditions(
        resolution,
        outcome,
        outcome_readiness,
        outcome_target,
        effective_state,
        implementation_action,
        administrative_status,
        eligibility,
    )
    resolution_pathway = _classify_resolution_pathway(
        resolution=resolution,
        resolution_preconditions=resolution_preconditions,
        outcome_target=outcome_target,
        outcome_readiness=outcome_readiness,
        effective_state=effective_state,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
    )
    resolution_readiness = _classify_resolution_readiness(
        resolution=resolution,
        resolution_preconditions=resolution_preconditions,
        resolution_pathway=resolution_pathway,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    determination = _classify_resolution_determination(
        resolution=resolution,
        resolution_preconditions=resolution_preconditions,
        resolution_pathway=resolution_pathway,
        resolution_readiness=resolution_readiness,
        outcome_target=outcome_target,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    completion = _classify_resolution_completion(
        resolution=resolution,
        resolution_preconditions=resolution_preconditions,
        resolution_pathway=resolution_pathway,
        resolution_readiness=resolution_readiness,
        resolution_determination=determination,
        outcome_target=outcome_target,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    closure = _classify_closure(
        resolution=resolution,
        resolution_completion=completion,
        resolution_determination=determination,
        resolution_readiness=resolution_readiness,
        resolution_pathway=resolution_pathway,
        outcome_target=outcome_target,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    closure_preconditions = _classify_closure_preconditions(
        closure=closure,
        resolution=resolution,
        resolution_completion=completion,
        resolution_determination=determination,
        resolution_readiness=resolution_readiness,
        resolution_pathway=resolution_pathway,
        outcome_target=outcome_target,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    closure_pathway = _classify_closure_pathway(
        closure=closure,
        closure_preconditions=closure_preconditions,
        resolution=resolution,
        resolution_completion=completion,
        resolution_determination=determination,
        resolution_readiness=resolution_readiness,
        resolution_pathway=resolution_pathway,
        outcome_target=outcome_target,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    closure_readiness = _classify_closure_readiness(
        closure_classification=closure,
        closure_preconditions=closure_preconditions,
        closure_pathway=closure_pathway,
        resolution_classification=resolution,
        resolution_completion=completion,
        resolution_determination=determination,
        resolution_readiness=resolution_readiness,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    closure_readiness_badge = (
        f'<span class="closure-readiness-badge {_closure_readiness_badge_class(closure_readiness)}">'
        f"{escape(closure_readiness)}</span>"
    )
    closure_badge = (
        f'<span class="closure-badge {_closure_badge_class(closure)}">'
        f"{escape(closure)}</span>"
    )
    closure_pathway_badge = (
        f'<span class="closure-pathway-badge {_closure_pathway_badge_class(closure_pathway)}">'
        f"{escape(closure_pathway)}</span>"
    )
    completion_badge = (
        f'<span class="resolution-completion-badge {_resolution_completion_badge_class(completion)}">'
        f"{escape(completion)}</span>"
    )
    determination_badge = (
        f'<span class="resolution-determination-badge {_resolution_determination_badge_class(determination)}">'
        f"{escape(determination)}</span>"
    )
    resolution_readiness_badge = (
        f'<span class="resolution-readiness-badge {_resolution_readiness_badge_class(resolution_readiness)}">'
        f"{escape(resolution_readiness)}</span>"
    )
    outcome_readiness_badge = (
        f'<span class="outcome-readiness-badge {_outcome_readiness_badge_class(outcome_readiness)}">'
        f"{escape(outcome_readiness)}</span>"
    )
    eligibility_badge = (
        f'<span class="eligibility-badge {_eligibility_badge_class(eligibility)}">'
        f"{escape(eligibility)}</span>"
    )
    status_badge = (
        f'<span class="administrative-status-badge {_administrative_status_badge_class(administrative_status)}">'
        f"{escape(administrative_status)}</span>"
    )
    implementation_badge = (
        f'<span class="implementation-action-badge {_implementation_action_badge_class(implementation_action)}">'
        f"{escape(implementation_action)}</span>"
    )
    effective_state_badge = (
        f'<span class="effective-state-badge {_effective_state_badge_class(effective_state)}">'
        f"{escape(effective_state)}</span>"
    )
    rows = (
        ("Closure Readiness", closure_readiness_badge),
        (
            "Readiness Description",
            escape(_describe_closure_readiness(closure_readiness)),
        ),
        ("Closure Classification", closure_badge),
        ("Closure Pathway", closure_pathway_badge),
        ("Resolution Completion", completion_badge),
        ("Resolution Determination", determination_badge),
        ("Resolution Readiness", resolution_readiness_badge),
        ("Outcome Readiness", outcome_readiness_badge),
        ("Review Eligibility", eligibility_badge),
        ("Administrative Status", status_badge),
        ("Implementation Action", implementation_badge),
        ("Effective State", effective_state_badge),
    )
    badge_labels = {
        "Closure Readiness",
        "Closure Classification",
        "Closure Pathway",
        "Resolution Completion",
        "Resolution Determination",
        "Resolution Readiness",
        "Outcome Readiness",
        "Review Eligibility",
        "Administrative Status",
        "Implementation Action",
        "Effective State",
    }
    table_rows = "".join(
        "<tr>"
        f"<td>{escape(str(label))}</td>"
        f"<td>{value if label in badge_labels else escape(str(value))}</td>"
        "</tr>"
        for label, value in rows
    )
    return f"""
      <section class="management-section closure-readiness">
        <h2>Stage 13D — Closure Readiness</h2>
        <p class="notice">
          Closure readiness is classified deterministically from closure,
          resolution, outcome, review eligibility, administrative status,
          implementation action, and effective state values only.
        </p>
        <table>
          <tbody>{table_rows}</tbody>
        </table>
      </section>"""


def _render_closure_determination(
    evidence_groups: dict[str, list[dict[str, Any]]],
) -> str:
    readiness_values = _record_evidence_readiness_values(evidence_groups)
    readiness = readiness_values["readiness"]
    action = classify_administrative_action(readiness)
    workflow_state = classify_workflow_state(readiness, action)
    disposition = classify_administrative_disposition(workflow_state)
    eligibility = classify_review_eligibility(disposition)
    status_summary = build_administrative_status_summary(
        disposition,
        eligibility,
        workflow_state,
        readiness,
    )
    administrative_status = status_summary["status"]
    implementation_action = classify_implementation_action(
        administrative_status
    )
    effective_state = classify_effective_state(
        implementation_action,
        administrative_status,
    )
    outcome = classify_outcome(effective_state)
    outcome_preconditions = build_outcome_preconditions(
        outcome,
        effective_state,
        implementation_action,
        administrative_status,
        eligibility,
    )
    outcome_readiness = classify_outcome_readiness(
        outcome,
        outcome_preconditions,
        eligibility,
        administrative_status,
        effective_state,
    )
    outcome_target = classify_outcome_target(
        outcome,
        outcome_readiness,
        effective_state,
        eligibility,
        administrative_status,
    )
    resolution = classify_resolution(
        outcome,
        outcome_readiness,
        outcome_target,
        effective_state,
        implementation_action,
        administrative_status,
    )
    resolution_preconditions = build_resolution_preconditions(
        resolution,
        outcome,
        outcome_readiness,
        outcome_target,
        effective_state,
        implementation_action,
        administrative_status,
        eligibility,
    )
    resolution_pathway = _classify_resolution_pathway(
        resolution=resolution,
        resolution_preconditions=resolution_preconditions,
        outcome_target=outcome_target,
        outcome_readiness=outcome_readiness,
        effective_state=effective_state,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
    )
    resolution_readiness = _classify_resolution_readiness(
        resolution=resolution,
        resolution_preconditions=resolution_preconditions,
        resolution_pathway=resolution_pathway,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    resolution_determination = _classify_resolution_determination(
        resolution=resolution,
        resolution_preconditions=resolution_preconditions,
        resolution_pathway=resolution_pathway,
        resolution_readiness=resolution_readiness,
        outcome_target=outcome_target,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    resolution_completion = _classify_resolution_completion(
        resolution=resolution,
        resolution_preconditions=resolution_preconditions,
        resolution_pathway=resolution_pathway,
        resolution_readiness=resolution_readiness,
        resolution_determination=resolution_determination,
        outcome_target=outcome_target,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    closure = _classify_closure(
        resolution=resolution,
        resolution_completion=resolution_completion,
        resolution_determination=resolution_determination,
        resolution_readiness=resolution_readiness,
        resolution_pathway=resolution_pathway,
        outcome_target=outcome_target,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    closure_preconditions = _classify_closure_preconditions(
        closure=closure,
        resolution=resolution,
        resolution_completion=resolution_completion,
        resolution_determination=resolution_determination,
        resolution_readiness=resolution_readiness,
        resolution_pathway=resolution_pathway,
        outcome_target=outcome_target,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    closure_pathway = _classify_closure_pathway(
        closure=closure,
        closure_preconditions=closure_preconditions,
        resolution=resolution,
        resolution_completion=resolution_completion,
        resolution_determination=resolution_determination,
        resolution_readiness=resolution_readiness,
        resolution_pathway=resolution_pathway,
        outcome_target=outcome_target,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    closure_readiness = _classify_closure_readiness(
        closure_classification=closure,
        closure_preconditions=closure_preconditions,
        closure_pathway=closure_pathway,
        resolution_classification=resolution,
        resolution_completion=resolution_completion,
        resolution_determination=resolution_determination,
        resolution_readiness=resolution_readiness,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    closure_determination = _classify_closure_determination(
        closure_classification=closure,
        closure_preconditions=closure_preconditions,
        closure_pathway=closure_pathway,
        closure_readiness=closure_readiness,
        resolution_classification=resolution,
        resolution_completion=resolution_completion,
        resolution_determination=resolution_determination,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    closure_determination_badge = (
        f'<span class="closure-determination-badge {_closure_determination_badge_class(closure_determination)}">'
        f"{escape(closure_determination)}</span>"
    )
    closure_badge = (
        f'<span class="closure-badge {_closure_badge_class(closure)}">'
        f"{escape(closure)}</span>"
    )
    closure_readiness_badge = (
        f'<span class="closure-readiness-badge {_closure_readiness_badge_class(closure_readiness)}">'
        f"{escape(closure_readiness)}</span>"
    )
    closure_pathway_badge = (
        f'<span class="closure-pathway-badge {_closure_pathway_badge_class(closure_pathway)}">'
        f"{escape(closure_pathway)}</span>"
    )
    resolution_badge = (
        f'<span class="resolution-badge {_resolution_badge_class(resolution)}">'
        f"{escape(resolution)}</span>"
    )
    completion_badge = (
        f'<span class="resolution-completion-badge {_resolution_completion_badge_class(resolution_completion)}">'
        f"{escape(resolution_completion)}</span>"
    )
    resolution_determination_badge = (
        f'<span class="resolution-determination-badge {_resolution_determination_badge_class(resolution_determination)}">'
        f"{escape(resolution_determination)}</span>"
    )
    outcome_readiness_badge = (
        f'<span class="outcome-readiness-badge {_outcome_readiness_badge_class(outcome_readiness)}">'
        f"{escape(outcome_readiness)}</span>"
    )
    eligibility_badge = (
        f'<span class="eligibility-badge {_eligibility_badge_class(eligibility)}">'
        f"{escape(eligibility)}</span>"
    )
    status_badge = (
        f'<span class="administrative-status-badge {_administrative_status_badge_class(administrative_status)}">'
        f"{escape(administrative_status)}</span>"
    )
    implementation_badge = (
        f'<span class="implementation-action-badge {_implementation_action_badge_class(implementation_action)}">'
        f"{escape(implementation_action)}</span>"
    )
    effective_state_badge = (
        f'<span class="effective-state-badge {_effective_state_badge_class(effective_state)}">'
        f"{escape(effective_state)}</span>"
    )
    rows = (
        ("Closure Determination", closure_determination_badge),
        (
            "Determination Description",
            escape(_describe_closure_determination(closure_determination)),
        ),
        ("Closure Classification", closure_badge),
        ("Closure Readiness", closure_readiness_badge),
        ("Closure Pathway", closure_pathway_badge),
        ("Resolution Classification", resolution_badge),
        ("Resolution Completion", completion_badge),
        ("Resolution Determination", resolution_determination_badge),
        ("Outcome Readiness", outcome_readiness_badge),
        ("Review Eligibility", eligibility_badge),
        ("Administrative Status", status_badge),
        ("Implementation Action", implementation_badge),
        ("Effective State", effective_state_badge),
    )
    badge_labels = {
        "Closure Determination",
        "Closure Classification",
        "Closure Readiness",
        "Closure Pathway",
        "Resolution Classification",
        "Resolution Completion",
        "Resolution Determination",
        "Outcome Readiness",
        "Review Eligibility",
        "Administrative Status",
        "Implementation Action",
        "Effective State",
    }
    table_rows = "".join(
        "<tr>"
        f"<td>{escape(str(label))}</td>"
        f"<td>{value if label in badge_labels else escape(str(value))}</td>"
        "</tr>"
        for label, value in rows
    )
    return f"""
      <section class="management-section closure-determination">
        <h2>Stage 13E — Closure Determination</h2>
        <p class="notice">
          Closure determination is classified deterministically from closure,
          resolution, readiness, pathway, outcome, administrative status,
          implementation action, and effective state values only.
        </p>
        <table>
          <tbody>{table_rows}</tbody>
        </table>
      </section>"""


def _render_closure_completion(
    evidence_groups: dict[str, list[dict[str, Any]]],
) -> str:
    readiness_values = _record_evidence_readiness_values(evidence_groups)
    readiness = readiness_values["readiness"]
    action = classify_administrative_action(readiness)
    workflow_state = classify_workflow_state(readiness, action)
    disposition = classify_administrative_disposition(workflow_state)
    eligibility = classify_review_eligibility(disposition)
    status_summary = build_administrative_status_summary(
        disposition,
        eligibility,
        workflow_state,
        readiness,
    )
    administrative_status = status_summary["status"]
    implementation_action = classify_implementation_action(
        administrative_status
    )
    effective_state = classify_effective_state(
        implementation_action,
        administrative_status,
    )
    outcome = classify_outcome(effective_state)
    outcome_preconditions = build_outcome_preconditions(
        outcome,
        effective_state,
        implementation_action,
        administrative_status,
        eligibility,
    )
    outcome_readiness = classify_outcome_readiness(
        outcome,
        outcome_preconditions,
        eligibility,
        administrative_status,
        effective_state,
    )
    outcome_target = classify_outcome_target(
        outcome,
        outcome_readiness,
        effective_state,
        eligibility,
        administrative_status,
    )
    resolution = classify_resolution(
        outcome,
        outcome_readiness,
        outcome_target,
        effective_state,
        implementation_action,
        administrative_status,
    )
    resolution_preconditions = build_resolution_preconditions(
        resolution,
        outcome,
        outcome_readiness,
        outcome_target,
        effective_state,
        implementation_action,
        administrative_status,
        eligibility,
    )
    resolution_pathway = _classify_resolution_pathway(
        resolution=resolution,
        resolution_preconditions=resolution_preconditions,
        outcome_target=outcome_target,
        outcome_readiness=outcome_readiness,
        effective_state=effective_state,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
    )
    resolution_readiness = _classify_resolution_readiness(
        resolution=resolution,
        resolution_preconditions=resolution_preconditions,
        resolution_pathway=resolution_pathway,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    resolution_determination = _classify_resolution_determination(
        resolution=resolution,
        resolution_preconditions=resolution_preconditions,
        resolution_pathway=resolution_pathway,
        resolution_readiness=resolution_readiness,
        outcome_target=outcome_target,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    resolution_completion = _classify_resolution_completion(
        resolution=resolution,
        resolution_preconditions=resolution_preconditions,
        resolution_pathway=resolution_pathway,
        resolution_readiness=resolution_readiness,
        resolution_determination=resolution_determination,
        outcome_target=outcome_target,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    closure = _classify_closure(
        resolution=resolution,
        resolution_completion=resolution_completion,
        resolution_determination=resolution_determination,
        resolution_readiness=resolution_readiness,
        resolution_pathway=resolution_pathway,
        outcome_target=outcome_target,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    closure_preconditions = _classify_closure_preconditions(
        closure=closure,
        resolution=resolution,
        resolution_completion=resolution_completion,
        resolution_determination=resolution_determination,
        resolution_readiness=resolution_readiness,
        resolution_pathway=resolution_pathway,
        outcome_target=outcome_target,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    closure_pathway = _classify_closure_pathway(
        closure=closure,
        closure_preconditions=closure_preconditions,
        resolution=resolution,
        resolution_completion=resolution_completion,
        resolution_determination=resolution_determination,
        resolution_readiness=resolution_readiness,
        resolution_pathway=resolution_pathway,
        outcome_target=outcome_target,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    closure_readiness = _classify_closure_readiness(
        closure_classification=closure,
        closure_preconditions=closure_preconditions,
        closure_pathway=closure_pathway,
        resolution_classification=resolution,
        resolution_completion=resolution_completion,
        resolution_determination=resolution_determination,
        resolution_readiness=resolution_readiness,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    closure_determination = _classify_closure_determination(
        closure_classification=closure,
        closure_preconditions=closure_preconditions,
        closure_pathway=closure_pathway,
        closure_readiness=closure_readiness,
        resolution_classification=resolution,
        resolution_completion=resolution_completion,
        resolution_determination=resolution_determination,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    closure_completion = _classify_closure_completion(
        closure_classification=closure,
        closure_preconditions=closure_preconditions,
        closure_pathway=closure_pathway,
        closure_readiness=closure_readiness,
        closure_determination=closure_determination,
        resolution_classification=resolution,
        resolution_completion=resolution_completion,
        resolution_determination=resolution_determination,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    closure_completion_badge = (
        f'<span class="closure-completion-badge {_closure_completion_badge_class(closure_completion)}">'
        f"{escape(closure_completion)}</span>"
    )
    closure_badge = (
        f'<span class="closure-badge {_closure_badge_class(closure)}">'
        f"{escape(closure)}</span>"
    )
    closure_determination_badge = (
        f'<span class="closure-determination-badge {_closure_determination_badge_class(closure_determination)}">'
        f"{escape(closure_determination)}</span>"
    )
    closure_readiness_badge = (
        f'<span class="closure-readiness-badge {_closure_readiness_badge_class(closure_readiness)}">'
        f"{escape(closure_readiness)}</span>"
    )
    closure_pathway_badge = (
        f'<span class="closure-pathway-badge {_closure_pathway_badge_class(closure_pathway)}">'
        f"{escape(closure_pathway)}</span>"
    )
    resolution_badge = (
        f'<span class="resolution-badge {_resolution_badge_class(resolution)}">'
        f"{escape(resolution)}</span>"
    )
    resolution_completion_badge = (
        f'<span class="resolution-completion-badge {_resolution_completion_badge_class(resolution_completion)}">'
        f"{escape(resolution_completion)}</span>"
    )
    resolution_determination_badge = (
        f'<span class="resolution-determination-badge {_resolution_determination_badge_class(resolution_determination)}">'
        f"{escape(resolution_determination)}</span>"
    )
    outcome_readiness_badge = (
        f'<span class="outcome-readiness-badge {_outcome_readiness_badge_class(outcome_readiness)}">'
        f"{escape(outcome_readiness)}</span>"
    )
    eligibility_badge = (
        f'<span class="eligibility-badge {_eligibility_badge_class(eligibility)}">'
        f"{escape(eligibility)}</span>"
    )
    status_badge = (
        f'<span class="administrative-status-badge {_administrative_status_badge_class(administrative_status)}">'
        f"{escape(administrative_status)}</span>"
    )
    implementation_badge = (
        f'<span class="implementation-action-badge {_implementation_action_badge_class(implementation_action)}">'
        f"{escape(implementation_action)}</span>"
    )
    effective_state_badge = (
        f'<span class="effective-state-badge {_effective_state_badge_class(effective_state)}">'
        f"{escape(effective_state)}</span>"
    )
    rows = (
        ("Closure Completion", closure_completion_badge),
        (
            "Completion Description",
            escape(_describe_closure_completion(closure_completion)),
        ),
        ("Closure Classification", closure_badge),
        ("Closure Determination", closure_determination_badge),
        ("Closure Readiness", closure_readiness_badge),
        ("Closure Pathway", closure_pathway_badge),
        ("Resolution Classification", resolution_badge),
        ("Resolution Completion", resolution_completion_badge),
        ("Resolution Determination", resolution_determination_badge),
        ("Outcome Readiness", outcome_readiness_badge),
        ("Review Eligibility", eligibility_badge),
        ("Administrative Status", status_badge),
        ("Implementation Action", implementation_badge),
        ("Effective State", effective_state_badge),
    )
    badge_labels = {
        "Closure Completion",
        "Closure Classification",
        "Closure Determination",
        "Closure Readiness",
        "Closure Pathway",
        "Resolution Classification",
        "Resolution Completion",
        "Resolution Determination",
        "Outcome Readiness",
        "Review Eligibility",
        "Administrative Status",
        "Implementation Action",
        "Effective State",
    }
    table_rows = "".join(
        "<tr>"
        f"<td>{escape(str(label))}</td>"
        f"<td>{value if label in badge_labels else escape(str(value))}</td>"
        "</tr>"
        for label, value in rows
    )
    return f"""
      <section class="management-section closure-completion">
        <h2>Stage 13F — Closure Completion</h2>
        <p class="notice">
          Closure completion is classified deterministically from closure,
          determination, readiness, pathway, outcome, administrative status,
          implementation action, and effective state values only.
        </p>
        <table>
          <tbody>{table_rows}</tbody>
        </table>
      </section>"""


def _render_archive_classification(
    evidence_groups: dict[str, list[dict[str, Any]]],
) -> str:
    readiness_values = _record_evidence_readiness_values(evidence_groups)
    readiness = readiness_values["readiness"]
    action = classify_administrative_action(readiness)
    workflow_state = classify_workflow_state(readiness, action)
    disposition = classify_administrative_disposition(workflow_state)
    eligibility = classify_review_eligibility(disposition)
    status_summary = build_administrative_status_summary(
        disposition,
        eligibility,
        workflow_state,
        readiness,
    )
    administrative_status = status_summary["status"]
    implementation_action = classify_implementation_action(
        administrative_status
    )
    effective_state = classify_effective_state(
        implementation_action,
        administrative_status,
    )
    outcome = classify_outcome(effective_state)
    outcome_preconditions = build_outcome_preconditions(
        outcome,
        effective_state,
        implementation_action,
        administrative_status,
        eligibility,
    )
    outcome_readiness = classify_outcome_readiness(
        outcome,
        outcome_preconditions,
        eligibility,
        administrative_status,
        effective_state,
    )
    outcome_target = classify_outcome_target(
        outcome,
        outcome_readiness,
        effective_state,
        eligibility,
        administrative_status,
    )
    resolution = classify_resolution(
        outcome,
        outcome_readiness,
        outcome_target,
        effective_state,
        implementation_action,
        administrative_status,
    )
    resolution_preconditions = build_resolution_preconditions(
        resolution,
        outcome,
        outcome_readiness,
        outcome_target,
        effective_state,
        implementation_action,
        administrative_status,
        eligibility,
    )
    resolution_pathway = _classify_resolution_pathway(
        resolution=resolution,
        resolution_preconditions=resolution_preconditions,
        outcome_target=outcome_target,
        outcome_readiness=outcome_readiness,
        effective_state=effective_state,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
    )
    resolution_readiness = _classify_resolution_readiness(
        resolution=resolution,
        resolution_preconditions=resolution_preconditions,
        resolution_pathway=resolution_pathway,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    resolution_determination = _classify_resolution_determination(
        resolution=resolution,
        resolution_preconditions=resolution_preconditions,
        resolution_pathway=resolution_pathway,
        resolution_readiness=resolution_readiness,
        outcome_target=outcome_target,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    resolution_completion = _classify_resolution_completion(
        resolution=resolution,
        resolution_preconditions=resolution_preconditions,
        resolution_pathway=resolution_pathway,
        resolution_readiness=resolution_readiness,
        resolution_determination=resolution_determination,
        outcome_target=outcome_target,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    closure = _classify_closure(
        resolution=resolution,
        resolution_completion=resolution_completion,
        resolution_determination=resolution_determination,
        resolution_readiness=resolution_readiness,
        resolution_pathway=resolution_pathway,
        outcome_target=outcome_target,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    closure_preconditions = _classify_closure_preconditions(
        closure=closure,
        resolution=resolution,
        resolution_completion=resolution_completion,
        resolution_determination=resolution_determination,
        resolution_readiness=resolution_readiness,
        resolution_pathway=resolution_pathway,
        outcome_target=outcome_target,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    closure_pathway = _classify_closure_pathway(
        closure=closure,
        closure_preconditions=closure_preconditions,
        resolution=resolution,
        resolution_completion=resolution_completion,
        resolution_determination=resolution_determination,
        resolution_readiness=resolution_readiness,
        resolution_pathway=resolution_pathway,
        outcome_target=outcome_target,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    closure_readiness = _classify_closure_readiness(
        closure_classification=closure,
        closure_preconditions=closure_preconditions,
        closure_pathway=closure_pathway,
        resolution_classification=resolution,
        resolution_completion=resolution_completion,
        resolution_determination=resolution_determination,
        resolution_readiness=resolution_readiness,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    closure_determination = _classify_closure_determination(
        closure_classification=closure,
        closure_preconditions=closure_preconditions,
        closure_pathway=closure_pathway,
        closure_readiness=closure_readiness,
        resolution_classification=resolution,
        resolution_completion=resolution_completion,
        resolution_determination=resolution_determination,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    closure_completion = _classify_closure_completion(
        closure_classification=closure,
        closure_preconditions=closure_preconditions,
        closure_pathway=closure_pathway,
        closure_readiness=closure_readiness,
        closure_determination=closure_determination,
        resolution_classification=resolution,
        resolution_completion=resolution_completion,
        resolution_determination=resolution_determination,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    archive_classification = _archive_classification(
        closure_classification=closure,
        closure_completion=closure_completion,
        closure_determination=closure_determination,
        closure_readiness=closure_readiness,
        resolution_classification=resolution,
        resolution_completion=resolution_completion,
        resolution_determination=resolution_determination,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    archive_badge = (
        f'<span class="archive-classification-badge {_archive_classification_badge_class(archive_classification)}">'
        f"{escape(archive_classification)}</span>"
    )
    closure_badge = (
        f'<span class="closure-badge {_closure_badge_class(closure)}">'
        f"{escape(closure)}</span>"
    )
    closure_completion_badge = (
        f'<span class="closure-completion-badge {_closure_completion_badge_class(closure_completion)}">'
        f"{escape(closure_completion)}</span>"
    )
    closure_determination_badge = (
        f'<span class="closure-determination-badge {_closure_determination_badge_class(closure_determination)}">'
        f"{escape(closure_determination)}</span>"
    )
    closure_readiness_badge = (
        f'<span class="closure-readiness-badge {_closure_readiness_badge_class(closure_readiness)}">'
        f"{escape(closure_readiness)}</span>"
    )
    resolution_badge = (
        f'<span class="resolution-badge {_resolution_badge_class(resolution)}">'
        f"{escape(resolution)}</span>"
    )
    resolution_completion_badge = (
        f'<span class="resolution-completion-badge {_resolution_completion_badge_class(resolution_completion)}">'
        f"{escape(resolution_completion)}</span>"
    )
    resolution_determination_badge = (
        f'<span class="resolution-determination-badge {_resolution_determination_badge_class(resolution_determination)}">'
        f"{escape(resolution_determination)}</span>"
    )
    outcome_readiness_badge = (
        f'<span class="outcome-readiness-badge {_outcome_readiness_badge_class(outcome_readiness)}">'
        f"{escape(outcome_readiness)}</span>"
    )
    eligibility_badge = (
        f'<span class="eligibility-badge {_eligibility_badge_class(eligibility)}">'
        f"{escape(eligibility)}</span>"
    )
    status_badge = (
        f'<span class="administrative-status-badge {_administrative_status_badge_class(administrative_status)}">'
        f"{escape(administrative_status)}</span>"
    )
    implementation_badge = (
        f'<span class="implementation-action-badge {_implementation_action_badge_class(implementation_action)}">'
        f"{escape(implementation_action)}</span>"
    )
    effective_state_badge = (
        f'<span class="effective-state-badge {_effective_state_badge_class(effective_state)}">'
        f"{escape(effective_state)}</span>"
    )
    rows = (
        ("Archive Classification", archive_badge),
        (
            "Description",
            escape(_describe_archive_classification(archive_classification)),
        ),
        ("Closure Classification", closure_badge),
        ("Closure Completion", closure_completion_badge),
        ("Closure Determination", closure_determination_badge),
        ("Closure Readiness", closure_readiness_badge),
        ("Resolution Classification", resolution_badge),
        ("Resolution Completion", resolution_completion_badge),
        ("Resolution Determination", resolution_determination_badge),
        ("Outcome Readiness", outcome_readiness_badge),
        ("Review Eligibility", eligibility_badge),
        ("Administrative Status", status_badge),
        ("Implementation Action", implementation_badge),
        ("Effective State", effective_state_badge),
    )
    badge_labels = {
        "Archive Classification",
        "Closure Classification",
        "Closure Completion",
        "Closure Determination",
        "Closure Readiness",
        "Resolution Classification",
        "Resolution Completion",
        "Resolution Determination",
        "Outcome Readiness",
        "Review Eligibility",
        "Administrative Status",
        "Implementation Action",
        "Effective State",
    }
    table_rows = "".join(
        "<tr>"
        f"<td>{escape(str(label))}</td>"
        f"<td>{value if label in badge_labels else escape(str(value))}</td>"
        "</tr>"
        for label, value in rows
    )
    return f"""
      <section class="management-section archive-classification">
        <h2>Stage 14A — Archive Classification</h2>
        <p class="notice">
          Archive classification is determined from closure, resolution,
          outcome, administrative status, implementation action, and effective
          state values only.
        </p>
        <table>
          <tbody>{table_rows}</tbody>
        </table>
      </section>"""


def _render_archive_preconditions(
    evidence_groups: dict[str, list[dict[str, Any]]],
) -> str:
    readiness_values = _record_evidence_readiness_values(evidence_groups)
    readiness = readiness_values["readiness"]
    action = classify_administrative_action(readiness)
    workflow_state = classify_workflow_state(readiness, action)
    disposition = classify_administrative_disposition(workflow_state)
    eligibility = classify_review_eligibility(disposition)
    status_summary = build_administrative_status_summary(
        disposition,
        eligibility,
        workflow_state,
        readiness,
    )
    administrative_status = status_summary["status"]
    implementation_action = classify_implementation_action(
        administrative_status
    )
    effective_state = classify_effective_state(
        implementation_action,
        administrative_status,
    )
    outcome = classify_outcome(effective_state)
    outcome_preconditions = build_outcome_preconditions(
        outcome,
        effective_state,
        implementation_action,
        administrative_status,
        eligibility,
    )
    outcome_readiness = classify_outcome_readiness(
        outcome,
        outcome_preconditions,
        eligibility,
        administrative_status,
        effective_state,
    )
    outcome_target = classify_outcome_target(
        outcome,
        outcome_readiness,
        effective_state,
        eligibility,
        administrative_status,
    )
    resolution = classify_resolution(
        outcome,
        outcome_readiness,
        outcome_target,
        effective_state,
        implementation_action,
        administrative_status,
    )
    resolution_preconditions = build_resolution_preconditions(
        resolution,
        outcome,
        outcome_readiness,
        outcome_target,
        effective_state,
        implementation_action,
        administrative_status,
        eligibility,
    )
    resolution_pathway = _classify_resolution_pathway(
        resolution=resolution,
        resolution_preconditions=resolution_preconditions,
        outcome_target=outcome_target,
        outcome_readiness=outcome_readiness,
        effective_state=effective_state,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
    )
    resolution_readiness = _classify_resolution_readiness(
        resolution=resolution,
        resolution_preconditions=resolution_preconditions,
        resolution_pathway=resolution_pathway,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    resolution_determination = _classify_resolution_determination(
        resolution=resolution,
        resolution_preconditions=resolution_preconditions,
        resolution_pathway=resolution_pathway,
        resolution_readiness=resolution_readiness,
        outcome_target=outcome_target,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    resolution_completion = _classify_resolution_completion(
        resolution=resolution,
        resolution_preconditions=resolution_preconditions,
        resolution_pathway=resolution_pathway,
        resolution_readiness=resolution_readiness,
        resolution_determination=resolution_determination,
        outcome_target=outcome_target,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    closure = _classify_closure(
        resolution=resolution,
        resolution_completion=resolution_completion,
        resolution_determination=resolution_determination,
        resolution_readiness=resolution_readiness,
        resolution_pathway=resolution_pathway,
        outcome_target=outcome_target,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    closure_preconditions = _classify_closure_preconditions(
        closure=closure,
        resolution=resolution,
        resolution_completion=resolution_completion,
        resolution_determination=resolution_determination,
        resolution_readiness=resolution_readiness,
        resolution_pathway=resolution_pathway,
        outcome_target=outcome_target,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    closure_pathway = _classify_closure_pathway(
        closure=closure,
        closure_preconditions=closure_preconditions,
        resolution=resolution,
        resolution_completion=resolution_completion,
        resolution_determination=resolution_determination,
        resolution_readiness=resolution_readiness,
        resolution_pathway=resolution_pathway,
        outcome_target=outcome_target,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    closure_readiness = _classify_closure_readiness(
        closure_classification=closure,
        closure_preconditions=closure_preconditions,
        closure_pathway=closure_pathway,
        resolution_classification=resolution,
        resolution_completion=resolution_completion,
        resolution_determination=resolution_determination,
        resolution_readiness=resolution_readiness,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    closure_determination = _classify_closure_determination(
        closure_classification=closure,
        closure_preconditions=closure_preconditions,
        closure_pathway=closure_pathway,
        closure_readiness=closure_readiness,
        resolution_classification=resolution,
        resolution_completion=resolution_completion,
        resolution_determination=resolution_determination,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    closure_completion = _classify_closure_completion(
        closure_classification=closure,
        closure_preconditions=closure_preconditions,
        closure_pathway=closure_pathway,
        closure_readiness=closure_readiness,
        closure_determination=closure_determination,
        resolution_classification=resolution,
        resolution_completion=resolution_completion,
        resolution_determination=resolution_determination,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    archive_classification = _archive_classification(
        closure_classification=closure,
        closure_completion=closure_completion,
        closure_determination=closure_determination,
        closure_readiness=closure_readiness,
        resolution_classification=resolution,
        resolution_completion=resolution_completion,
        resolution_determination=resolution_determination,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    archive_preconditions = _archive_preconditions(
        archive_classification=archive_classification,
        closure_classification=closure,
        closure_completion=closure_completion,
        closure_determination=closure_determination,
        closure_readiness=closure_readiness,
        resolution_classification=resolution,
        resolution_completion=resolution_completion,
        resolution_determination=resolution_determination,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    archive_precondition_items = _archive_precondition_items(
        archive_preconditions=archive_preconditions,
        closure_completion=closure_completion,
        closure_determination=closure_determination,
        closure_readiness=closure_readiness,
        effective_state=effective_state,
    )
    archive_badge = (
        f'<span class="archive-classification-badge {_archive_classification_badge_class(archive_classification)}">'
        f"{escape(archive_classification)}</span>"
    )
    archive_preconditions_badge = (
        f'<span class="archive-preconditions-badge {_archive_preconditions_badge_class(archive_preconditions)}">'
        f"{escape(archive_preconditions)}</span>"
    )
    closure_badge = (
        f'<span class="closure-badge {_closure_badge_class(closure)}">'
        f"{escape(closure)}</span>"
    )
    closure_completion_badge = (
        f'<span class="closure-completion-badge {_closure_completion_badge_class(closure_completion)}">'
        f"{escape(closure_completion)}</span>"
    )
    closure_determination_badge = (
        f'<span class="closure-determination-badge {_closure_determination_badge_class(closure_determination)}">'
        f"{escape(closure_determination)}</span>"
    )
    closure_readiness_badge = (
        f'<span class="closure-readiness-badge {_closure_readiness_badge_class(closure_readiness)}">'
        f"{escape(closure_readiness)}</span>"
    )
    resolution_badge = (
        f'<span class="resolution-badge {_resolution_badge_class(resolution)}">'
        f"{escape(resolution)}</span>"
    )
    resolution_completion_badge = (
        f'<span class="resolution-completion-badge {_resolution_completion_badge_class(resolution_completion)}">'
        f"{escape(resolution_completion)}</span>"
    )
    resolution_determination_badge = (
        f'<span class="resolution-determination-badge {_resolution_determination_badge_class(resolution_determination)}">'
        f"{escape(resolution_determination)}</span>"
    )
    outcome_readiness_badge = (
        f'<span class="outcome-readiness-badge {_outcome_readiness_badge_class(outcome_readiness)}">'
        f"{escape(outcome_readiness)}</span>"
    )
    eligibility_badge = (
        f'<span class="eligibility-badge {_eligibility_badge_class(eligibility)}">'
        f"{escape(eligibility)}</span>"
    )
    status_badge = (
        f'<span class="administrative-status-badge {_administrative_status_badge_class(administrative_status)}">'
        f"{escape(administrative_status)}</span>"
    )
    implementation_badge = (
        f'<span class="implementation-action-badge {_implementation_action_badge_class(implementation_action)}">'
        f"{escape(implementation_action)}</span>"
    )
    effective_state_badge = (
        f'<span class="effective-state-badge {_effective_state_badge_class(effective_state)}">'
        f"{escape(effective_state)}</span>"
    )
    rows = (
        ("Archive Preconditions", archive_preconditions_badge),
        (
            "Description",
            escape(_describe_archive_preconditions(archive_preconditions)),
        ),
        ("Archive Classification", archive_badge),
        ("Closure Classification", closure_badge),
        ("Closure Completion", closure_completion_badge),
        ("Closure Determination", closure_determination_badge),
        ("Closure Readiness", closure_readiness_badge),
        ("Resolution Classification", resolution_badge),
        ("Resolution Completion", resolution_completion_badge),
        ("Resolution Determination", resolution_determination_badge),
        ("Outcome Readiness", outcome_readiness_badge),
        ("Review Eligibility", eligibility_badge),
        ("Administrative Status", status_badge),
        ("Implementation Action", implementation_badge),
        ("Effective State", effective_state_badge),
    )
    badge_labels = {
        "Archive Preconditions",
        "Archive Classification",
        "Closure Classification",
        "Closure Completion",
        "Closure Determination",
        "Closure Readiness",
        "Resolution Classification",
        "Resolution Completion",
        "Resolution Determination",
        "Outcome Readiness",
        "Review Eligibility",
        "Administrative Status",
        "Implementation Action",
        "Effective State",
    }
    table_rows = "".join(
        "<tr>"
        f"<td>{escape(str(label))}</td>"
        f"<td>{value if label in badge_labels else escape(str(value))}</td>"
        "</tr>"
        for label, value in rows
    )
    precondition_rows = "".join(
        f"<li>{escape(item)}</li>" for item in archive_precondition_items
    )
    return f"""
      <section class="management-section archive-preconditions">
        <h2>Stage 14B — Archive Preconditions</h2>
        <p class="notice">
          Archive preconditions are derived deterministically from archive,
          closure, resolution, outcome, administrative status, implementation
          action, and effective state values only.
        </p>
        <table>
          <tbody>{table_rows}</tbody>
        </table>
        <h3>Archive Preconditions</h3>
        <ol class="archive-preconditions-list">{precondition_rows}</ol>
      </section>"""


def _render_archive_pathway(
    evidence_groups: dict[str, list[dict[str, Any]]],
) -> str:
    readiness_values = _record_evidence_readiness_values(evidence_groups)
    readiness = readiness_values["readiness"]
    action = classify_administrative_action(readiness)
    workflow_state = classify_workflow_state(readiness, action)
    disposition = classify_administrative_disposition(workflow_state)
    eligibility = classify_review_eligibility(disposition)
    status_summary = build_administrative_status_summary(
        disposition,
        eligibility,
        workflow_state,
        readiness,
    )
    administrative_status = status_summary["status"]
    implementation_action = classify_implementation_action(
        administrative_status
    )
    effective_state = classify_effective_state(
        implementation_action,
        administrative_status,
    )
    outcome = classify_outcome(effective_state)
    outcome_preconditions = build_outcome_preconditions(
        outcome,
        effective_state,
        implementation_action,
        administrative_status,
        eligibility,
    )
    outcome_readiness = classify_outcome_readiness(
        outcome,
        outcome_preconditions,
        eligibility,
        administrative_status,
        effective_state,
    )
    outcome_target = classify_outcome_target(
        outcome,
        outcome_readiness,
        effective_state,
        eligibility,
        administrative_status,
    )
    resolution = classify_resolution(
        outcome,
        outcome_readiness,
        outcome_target,
        effective_state,
        implementation_action,
        administrative_status,
    )
    resolution_preconditions = build_resolution_preconditions(
        resolution,
        outcome,
        outcome_readiness,
        outcome_target,
        effective_state,
        implementation_action,
        administrative_status,
        eligibility,
    )
    resolution_pathway = _classify_resolution_pathway(
        resolution=resolution,
        resolution_preconditions=resolution_preconditions,
        outcome_target=outcome_target,
        outcome_readiness=outcome_readiness,
        effective_state=effective_state,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
    )
    resolution_readiness = _classify_resolution_readiness(
        resolution=resolution,
        resolution_preconditions=resolution_preconditions,
        resolution_pathway=resolution_pathway,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    resolution_determination = _classify_resolution_determination(
        resolution=resolution,
        resolution_preconditions=resolution_preconditions,
        resolution_pathway=resolution_pathway,
        resolution_readiness=resolution_readiness,
        outcome_target=outcome_target,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    resolution_completion = _classify_resolution_completion(
        resolution=resolution,
        resolution_preconditions=resolution_preconditions,
        resolution_pathway=resolution_pathway,
        resolution_readiness=resolution_readiness,
        resolution_determination=resolution_determination,
        outcome_target=outcome_target,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    closure = _classify_closure(
        resolution=resolution,
        resolution_completion=resolution_completion,
        resolution_determination=resolution_determination,
        resolution_readiness=resolution_readiness,
        resolution_pathway=resolution_pathway,
        outcome_target=outcome_target,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    closure_preconditions = _classify_closure_preconditions(
        closure=closure,
        resolution=resolution,
        resolution_completion=resolution_completion,
        resolution_determination=resolution_determination,
        resolution_readiness=resolution_readiness,
        resolution_pathway=resolution_pathway,
        outcome_target=outcome_target,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    closure_pathway = _classify_closure_pathway(
        closure=closure,
        closure_preconditions=closure_preconditions,
        resolution=resolution,
        resolution_completion=resolution_completion,
        resolution_determination=resolution_determination,
        resolution_readiness=resolution_readiness,
        resolution_pathway=resolution_pathway,
        outcome_target=outcome_target,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    closure_readiness = _classify_closure_readiness(
        closure_classification=closure,
        closure_preconditions=closure_preconditions,
        closure_pathway=closure_pathway,
        resolution_classification=resolution,
        resolution_completion=resolution_completion,
        resolution_determination=resolution_determination,
        resolution_readiness=resolution_readiness,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    closure_determination = _classify_closure_determination(
        closure_classification=closure,
        closure_preconditions=closure_preconditions,
        closure_pathway=closure_pathway,
        closure_readiness=closure_readiness,
        resolution_classification=resolution,
        resolution_completion=resolution_completion,
        resolution_determination=resolution_determination,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    closure_completion = _classify_closure_completion(
        closure_classification=closure,
        closure_preconditions=closure_preconditions,
        closure_pathway=closure_pathway,
        closure_readiness=closure_readiness,
        closure_determination=closure_determination,
        resolution_classification=resolution,
        resolution_completion=resolution_completion,
        resolution_determination=resolution_determination,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    archive_classification = _archive_classification(
        closure_classification=closure,
        closure_completion=closure_completion,
        closure_determination=closure_determination,
        closure_readiness=closure_readiness,
        resolution_classification=resolution,
        resolution_completion=resolution_completion,
        resolution_determination=resolution_determination,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    archive_preconditions = _archive_preconditions(
        archive_classification=archive_classification,
        closure_classification=closure,
        closure_completion=closure_completion,
        closure_determination=closure_determination,
        closure_readiness=closure_readiness,
        resolution_classification=resolution,
        resolution_completion=resolution_completion,
        resolution_determination=resolution_determination,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    archive_pathway = _archive_pathway(
        archive_classification=archive_classification,
        archive_preconditions=archive_preconditions,
        closure_classification=closure,
        closure_completion=closure_completion,
        closure_determination=closure_determination,
        closure_readiness=closure_readiness,
        resolution_classification=resolution,
        resolution_completion=resolution_completion,
        resolution_determination=resolution_determination,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    archive_pathway_badge = (
        f'<span class="archive-pathway-badge {_archive_pathway_badge_class(archive_pathway)}">'
        f"{escape(archive_pathway)}</span>"
    )
    archive_badge = (
        f'<span class="archive-classification-badge {_archive_classification_badge_class(archive_classification)}">'
        f"{escape(archive_classification)}</span>"
    )
    archive_preconditions_badge = (
        f'<span class="archive-preconditions-badge {_archive_preconditions_badge_class(archive_preconditions)}">'
        f"{escape(archive_preconditions)}</span>"
    )
    closure_badge = (
        f'<span class="closure-badge {_closure_badge_class(closure)}">'
        f"{escape(closure)}</span>"
    )
    closure_completion_badge = (
        f'<span class="closure-completion-badge {_closure_completion_badge_class(closure_completion)}">'
        f"{escape(closure_completion)}</span>"
    )
    closure_determination_badge = (
        f'<span class="closure-determination-badge {_closure_determination_badge_class(closure_determination)}">'
        f"{escape(closure_determination)}</span>"
    )
    closure_readiness_badge = (
        f'<span class="closure-readiness-badge {_closure_readiness_badge_class(closure_readiness)}">'
        f"{escape(closure_readiness)}</span>"
    )
    resolution_badge = (
        f'<span class="resolution-badge {_resolution_badge_class(resolution)}">'
        f"{escape(resolution)}</span>"
    )
    resolution_completion_badge = (
        f'<span class="resolution-completion-badge {_resolution_completion_badge_class(resolution_completion)}">'
        f"{escape(resolution_completion)}</span>"
    )
    resolution_determination_badge = (
        f'<span class="resolution-determination-badge {_resolution_determination_badge_class(resolution_determination)}">'
        f"{escape(resolution_determination)}</span>"
    )
    outcome_readiness_badge = (
        f'<span class="outcome-readiness-badge {_outcome_readiness_badge_class(outcome_readiness)}">'
        f"{escape(outcome_readiness)}</span>"
    )
    eligibility_badge = (
        f'<span class="eligibility-badge {_eligibility_badge_class(eligibility)}">'
        f"{escape(eligibility)}</span>"
    )
    status_badge = (
        f'<span class="administrative-status-badge {_administrative_status_badge_class(administrative_status)}">'
        f"{escape(administrative_status)}</span>"
    )
    implementation_badge = (
        f'<span class="implementation-action-badge {_implementation_action_badge_class(implementation_action)}">'
        f"{escape(implementation_action)}</span>"
    )
    effective_state_badge = (
        f'<span class="effective-state-badge {_effective_state_badge_class(effective_state)}">'
        f"{escape(effective_state)}</span>"
    )
    rows = (
        ("Archive Pathway", archive_pathway_badge),
        ("Description", escape(_describe_archive_pathway(archive_pathway))),
        ("Archive Classification", archive_badge),
        ("Archive Preconditions", archive_preconditions_badge),
        ("Closure Classification", closure_badge),
        ("Closure Completion", closure_completion_badge),
        ("Closure Determination", closure_determination_badge),
        ("Closure Readiness", closure_readiness_badge),
        ("Resolution Classification", resolution_badge),
        ("Resolution Completion", resolution_completion_badge),
        ("Resolution Determination", resolution_determination_badge),
        ("Outcome Readiness", outcome_readiness_badge),
        ("Review Eligibility", eligibility_badge),
        ("Administrative Status", status_badge),
        ("Implementation Action", implementation_badge),
        ("Effective State", effective_state_badge),
    )
    badge_labels = {
        "Archive Pathway",
        "Archive Classification",
        "Archive Preconditions",
        "Closure Classification",
        "Closure Completion",
        "Closure Determination",
        "Closure Readiness",
        "Resolution Classification",
        "Resolution Completion",
        "Resolution Determination",
        "Outcome Readiness",
        "Review Eligibility",
        "Administrative Status",
        "Implementation Action",
        "Effective State",
    }
    table_rows = "".join(
        "<tr>"
        f"<td>{escape(str(label))}</td>"
        f"<td>{value if label in badge_labels else escape(str(value))}</td>"
        "</tr>"
        for label, value in rows
    )
    return f"""
      <section class="management-section archive-pathway">
        <h2>Stage 14C — Archive Pathway</h2>
        <p class="notice">
          Archive pathway identifies the deterministic sequence of archive
          transitions required before archive completion can occur.
        </p>
        <table>
          <tbody>{table_rows}</tbody>
        </table>
      </section>"""


def _render_archive_readiness(
    evidence_groups: dict[str, list[dict[str, Any]]],
) -> str:
    readiness_values = _record_evidence_readiness_values(evidence_groups)
    readiness = readiness_values["readiness"]
    action = classify_administrative_action(readiness)
    workflow_state = classify_workflow_state(readiness, action)
    disposition = classify_administrative_disposition(workflow_state)
    eligibility = classify_review_eligibility(disposition)
    status_summary = build_administrative_status_summary(
        disposition,
        eligibility,
        workflow_state,
        readiness,
    )
    administrative_status = status_summary["status"]
    implementation_action = classify_implementation_action(
        administrative_status
    )
    effective_state = classify_effective_state(
        implementation_action,
        administrative_status,
    )
    outcome = classify_outcome(effective_state)
    outcome_preconditions = build_outcome_preconditions(
        outcome,
        effective_state,
        implementation_action,
        administrative_status,
        eligibility,
    )
    outcome_readiness = classify_outcome_readiness(
        outcome,
        outcome_preconditions,
        eligibility,
        administrative_status,
        effective_state,
    )
    outcome_target = classify_outcome_target(
        outcome,
        outcome_readiness,
        effective_state,
        eligibility,
        administrative_status,
    )
    resolution = classify_resolution(
        outcome,
        outcome_readiness,
        outcome_target,
        effective_state,
        implementation_action,
        administrative_status,
    )
    resolution_preconditions = build_resolution_preconditions(
        resolution,
        outcome,
        outcome_readiness,
        outcome_target,
        effective_state,
        implementation_action,
        administrative_status,
        eligibility,
    )
    resolution_pathway = _classify_resolution_pathway(
        resolution=resolution,
        resolution_preconditions=resolution_preconditions,
        outcome_target=outcome_target,
        outcome_readiness=outcome_readiness,
        effective_state=effective_state,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
    )
    resolution_readiness = _classify_resolution_readiness(
        resolution=resolution,
        resolution_preconditions=resolution_preconditions,
        resolution_pathway=resolution_pathway,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    resolution_determination = _classify_resolution_determination(
        resolution=resolution,
        resolution_preconditions=resolution_preconditions,
        resolution_pathway=resolution_pathway,
        resolution_readiness=resolution_readiness,
        outcome_target=outcome_target,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    resolution_completion = _classify_resolution_completion(
        resolution=resolution,
        resolution_preconditions=resolution_preconditions,
        resolution_pathway=resolution_pathway,
        resolution_readiness=resolution_readiness,
        resolution_determination=resolution_determination,
        outcome_target=outcome_target,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    closure = _classify_closure(
        resolution=resolution,
        resolution_completion=resolution_completion,
        resolution_determination=resolution_determination,
        resolution_readiness=resolution_readiness,
        resolution_pathway=resolution_pathway,
        outcome_target=outcome_target,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    closure_preconditions = _classify_closure_preconditions(
        closure=closure,
        resolution=resolution,
        resolution_completion=resolution_completion,
        resolution_determination=resolution_determination,
        resolution_readiness=resolution_readiness,
        resolution_pathway=resolution_pathway,
        outcome_target=outcome_target,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    closure_pathway = _classify_closure_pathway(
        closure=closure,
        closure_preconditions=closure_preconditions,
        resolution=resolution,
        resolution_completion=resolution_completion,
        resolution_determination=resolution_determination,
        resolution_readiness=resolution_readiness,
        resolution_pathway=resolution_pathway,
        outcome_target=outcome_target,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    closure_readiness = _classify_closure_readiness(
        closure_classification=closure,
        closure_preconditions=closure_preconditions,
        closure_pathway=closure_pathway,
        resolution_classification=resolution,
        resolution_completion=resolution_completion,
        resolution_determination=resolution_determination,
        resolution_readiness=resolution_readiness,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    closure_determination = _classify_closure_determination(
        closure_classification=closure,
        closure_preconditions=closure_preconditions,
        closure_pathway=closure_pathway,
        closure_readiness=closure_readiness,
        resolution_classification=resolution,
        resolution_completion=resolution_completion,
        resolution_determination=resolution_determination,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    closure_completion = _classify_closure_completion(
        closure_classification=closure,
        closure_preconditions=closure_preconditions,
        closure_pathway=closure_pathway,
        closure_readiness=closure_readiness,
        closure_determination=closure_determination,
        resolution_classification=resolution,
        resolution_completion=resolution_completion,
        resolution_determination=resolution_determination,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    archive_classification = _archive_classification(
        closure_classification=closure,
        closure_completion=closure_completion,
        closure_determination=closure_determination,
        closure_readiness=closure_readiness,
        resolution_classification=resolution,
        resolution_completion=resolution_completion,
        resolution_determination=resolution_determination,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    archive_preconditions = _archive_preconditions(
        archive_classification=archive_classification,
        closure_classification=closure,
        closure_completion=closure_completion,
        closure_determination=closure_determination,
        closure_readiness=closure_readiness,
        resolution_classification=resolution,
        resolution_completion=resolution_completion,
        resolution_determination=resolution_determination,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    archive_pathway = _archive_pathway(
        archive_classification=archive_classification,
        archive_preconditions=archive_preconditions,
        closure_classification=closure,
        closure_completion=closure_completion,
        closure_determination=closure_determination,
        closure_readiness=closure_readiness,
        resolution_classification=resolution,
        resolution_completion=resolution_completion,
        resolution_determination=resolution_determination,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    archive_readiness = _archive_readiness(
        archive_classification=archive_classification,
        archive_preconditions=archive_preconditions,
        archive_pathway=archive_pathway,
        closure_classification=closure,
        closure_completion=closure_completion,
        closure_determination=closure_determination,
        closure_readiness=closure_readiness,
        resolution_classification=resolution,
        resolution_completion=resolution_completion,
        resolution_determination=resolution_determination,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    archive_readiness_badge = (
        f'<span class="archive-readiness-badge {_archive_readiness_badge_class(archive_readiness)}">'
        f"{escape(archive_readiness)}</span>"
    )
    archive_badge = (
        f'<span class="archive-classification-badge {_archive_classification_badge_class(archive_classification)}">'
        f"{escape(archive_classification)}</span>"
    )
    archive_preconditions_badge = (
        f'<span class="archive-preconditions-badge {_archive_preconditions_badge_class(archive_preconditions)}">'
        f"{escape(archive_preconditions)}</span>"
    )
    archive_pathway_badge = (
        f'<span class="archive-pathway-badge {_archive_pathway_badge_class(archive_pathway)}">'
        f"{escape(archive_pathway)}</span>"
    )
    closure_badge = (
        f'<span class="closure-badge {_closure_badge_class(closure)}">'
        f"{escape(closure)}</span>"
    )
    closure_completion_badge = (
        f'<span class="closure-completion-badge {_closure_completion_badge_class(closure_completion)}">'
        f"{escape(closure_completion)}</span>"
    )
    closure_determination_badge = (
        f'<span class="closure-determination-badge {_closure_determination_badge_class(closure_determination)}">'
        f"{escape(closure_determination)}</span>"
    )
    closure_readiness_badge = (
        f'<span class="closure-readiness-badge {_closure_readiness_badge_class(closure_readiness)}">'
        f"{escape(closure_readiness)}</span>"
    )
    resolution_badge = (
        f'<span class="resolution-badge {_resolution_badge_class(resolution)}">'
        f"{escape(resolution)}</span>"
    )
    resolution_completion_badge = (
        f'<span class="resolution-completion-badge {_resolution_completion_badge_class(resolution_completion)}">'
        f"{escape(resolution_completion)}</span>"
    )
    resolution_determination_badge = (
        f'<span class="resolution-determination-badge {_resolution_determination_badge_class(resolution_determination)}">'
        f"{escape(resolution_determination)}</span>"
    )
    outcome_readiness_badge = (
        f'<span class="outcome-readiness-badge {_outcome_readiness_badge_class(outcome_readiness)}">'
        f"{escape(outcome_readiness)}</span>"
    )
    eligibility_badge = (
        f'<span class="eligibility-badge {_eligibility_badge_class(eligibility)}">'
        f"{escape(eligibility)}</span>"
    )
    status_badge = (
        f'<span class="administrative-status-badge {_administrative_status_badge_class(administrative_status)}">'
        f"{escape(administrative_status)}</span>"
    )
    implementation_badge = (
        f'<span class="implementation-action-badge {_implementation_action_badge_class(implementation_action)}">'
        f"{escape(implementation_action)}</span>"
    )
    effective_state_badge = (
        f'<span class="effective-state-badge {_effective_state_badge_class(effective_state)}">'
        f"{escape(effective_state)}</span>"
    )
    rows = (
        ("Archive Readiness", archive_readiness_badge),
        ("Description", escape(_describe_archive_readiness(archive_readiness))),
        ("Archive Classification", archive_badge),
        ("Archive Preconditions", archive_preconditions_badge),
        ("Archive Pathway", archive_pathway_badge),
        ("Closure Classification", closure_badge),
        ("Closure Completion", closure_completion_badge),
        ("Closure Determination", closure_determination_badge),
        ("Closure Readiness", closure_readiness_badge),
        ("Resolution Classification", resolution_badge),
        ("Resolution Completion", resolution_completion_badge),
        ("Resolution Determination", resolution_determination_badge),
        ("Outcome Readiness", outcome_readiness_badge),
        ("Review Eligibility", eligibility_badge),
        ("Administrative Status", status_badge),
        ("Implementation Action", implementation_badge),
        ("Effective State", effective_state_badge),
    )
    badge_labels = {
        "Archive Readiness",
        "Archive Classification",
        "Archive Preconditions",
        "Archive Pathway",
        "Closure Classification",
        "Closure Completion",
        "Closure Determination",
        "Closure Readiness",
        "Resolution Classification",
        "Resolution Completion",
        "Resolution Determination",
        "Outcome Readiness",
        "Review Eligibility",
        "Administrative Status",
        "Implementation Action",
        "Effective State",
    }
    table_rows = "".join(
        "<tr>"
        f"<td>{escape(str(label))}</td>"
        f"<td>{value if label in badge_labels else escape(str(value))}</td>"
        "</tr>"
        for label, value in rows
    )
    return f"""
      <section class="management-section archive-readiness">
        <h2>Stage 14D — Archive Readiness</h2>
        <p class="notice">
          Archive readiness is classified deterministically from archive,
          closure, resolution, outcome, administrative status, implementation
          action, and effective state values only.
        </p>
        <table>
          <tbody>{table_rows}</tbody>
        </table>
      </section>"""


def _render_archive_determination(
    evidence_groups: dict[str, list[dict[str, Any]]],
) -> str:
    readiness_values = _record_evidence_readiness_values(evidence_groups)
    readiness = readiness_values["readiness"]
    action = classify_administrative_action(readiness)
    workflow_state = classify_workflow_state(readiness, action)
    disposition = classify_administrative_disposition(workflow_state)
    eligibility = classify_review_eligibility(disposition)
    status_summary = build_administrative_status_summary(
        disposition,
        eligibility,
        workflow_state,
        readiness,
    )
    administrative_status = status_summary["status"]
    implementation_action = classify_implementation_action(
        administrative_status
    )
    effective_state = classify_effective_state(
        implementation_action,
        administrative_status,
    )
    outcome = classify_outcome(effective_state)
    outcome_preconditions = build_outcome_preconditions(
        outcome,
        effective_state,
        implementation_action,
        administrative_status,
        eligibility,
    )
    outcome_readiness = classify_outcome_readiness(
        outcome,
        outcome_preconditions,
        eligibility,
        administrative_status,
        effective_state,
    )
    outcome_target = classify_outcome_target(
        outcome,
        outcome_readiness,
        effective_state,
        eligibility,
        administrative_status,
    )
    resolution = classify_resolution(
        outcome,
        outcome_readiness,
        outcome_target,
        effective_state,
        implementation_action,
        administrative_status,
    )
    resolution_preconditions = build_resolution_preconditions(
        resolution,
        outcome,
        outcome_readiness,
        outcome_target,
        effective_state,
        implementation_action,
        administrative_status,
        eligibility,
    )
    resolution_pathway = _classify_resolution_pathway(
        resolution=resolution,
        resolution_preconditions=resolution_preconditions,
        outcome_target=outcome_target,
        outcome_readiness=outcome_readiness,
        effective_state=effective_state,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
    )
    resolution_readiness = _classify_resolution_readiness(
        resolution=resolution,
        resolution_preconditions=resolution_preconditions,
        resolution_pathway=resolution_pathway,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    resolution_determination = _classify_resolution_determination(
        resolution=resolution,
        resolution_preconditions=resolution_preconditions,
        resolution_pathway=resolution_pathway,
        resolution_readiness=resolution_readiness,
        outcome_target=outcome_target,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    resolution_completion = _classify_resolution_completion(
        resolution=resolution,
        resolution_preconditions=resolution_preconditions,
        resolution_pathway=resolution_pathway,
        resolution_readiness=resolution_readiness,
        resolution_determination=resolution_determination,
        outcome_target=outcome_target,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    closure = _classify_closure(
        resolution=resolution,
        resolution_completion=resolution_completion,
        resolution_determination=resolution_determination,
        resolution_readiness=resolution_readiness,
        resolution_pathway=resolution_pathway,
        outcome_target=outcome_target,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    closure_preconditions = _classify_closure_preconditions(
        closure=closure,
        resolution=resolution,
        resolution_completion=resolution_completion,
        resolution_determination=resolution_determination,
        resolution_readiness=resolution_readiness,
        resolution_pathway=resolution_pathway,
        outcome_target=outcome_target,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    closure_pathway = _classify_closure_pathway(
        closure=closure,
        closure_preconditions=closure_preconditions,
        resolution=resolution,
        resolution_completion=resolution_completion,
        resolution_determination=resolution_determination,
        resolution_readiness=resolution_readiness,
        resolution_pathway=resolution_pathway,
        outcome_target=outcome_target,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    closure_readiness = _classify_closure_readiness(
        closure_classification=closure,
        closure_preconditions=closure_preconditions,
        closure_pathway=closure_pathway,
        resolution_classification=resolution,
        resolution_completion=resolution_completion,
        resolution_determination=resolution_determination,
        resolution_readiness=resolution_readiness,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    closure_determination = _classify_closure_determination(
        closure_classification=closure,
        closure_preconditions=closure_preconditions,
        closure_pathway=closure_pathway,
        closure_readiness=closure_readiness,
        resolution_classification=resolution,
        resolution_completion=resolution_completion,
        resolution_determination=resolution_determination,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    closure_completion = _classify_closure_completion(
        closure_classification=closure,
        closure_preconditions=closure_preconditions,
        closure_pathway=closure_pathway,
        closure_readiness=closure_readiness,
        closure_determination=closure_determination,
        resolution_classification=resolution,
        resolution_completion=resolution_completion,
        resolution_determination=resolution_determination,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    archive_classification = _archive_classification(
        closure_classification=closure,
        closure_completion=closure_completion,
        closure_determination=closure_determination,
        closure_readiness=closure_readiness,
        resolution_classification=resolution,
        resolution_completion=resolution_completion,
        resolution_determination=resolution_determination,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    archive_preconditions = _archive_preconditions(
        archive_classification=archive_classification,
        closure_classification=closure,
        closure_completion=closure_completion,
        closure_determination=closure_determination,
        closure_readiness=closure_readiness,
        resolution_classification=resolution,
        resolution_completion=resolution_completion,
        resolution_determination=resolution_determination,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    archive_pathway = _archive_pathway(
        archive_classification=archive_classification,
        archive_preconditions=archive_preconditions,
        closure_classification=closure,
        closure_completion=closure_completion,
        closure_determination=closure_determination,
        closure_readiness=closure_readiness,
        resolution_classification=resolution,
        resolution_completion=resolution_completion,
        resolution_determination=resolution_determination,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    archive_readiness = _archive_readiness(
        archive_classification=archive_classification,
        archive_preconditions=archive_preconditions,
        archive_pathway=archive_pathway,
        closure_classification=closure,
        closure_completion=closure_completion,
        closure_determination=closure_determination,
        closure_readiness=closure_readiness,
        resolution_classification=resolution,
        resolution_completion=resolution_completion,
        resolution_determination=resolution_determination,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    archive_determination = _archive_determination(
        archive_classification=archive_classification,
        archive_preconditions=archive_preconditions,
        archive_pathway=archive_pathway,
        archive_readiness=archive_readiness,
        closure_classification=closure,
        closure_completion=closure_completion,
        closure_determination=closure_determination,
        closure_readiness=closure_readiness,
        resolution_classification=resolution,
        resolution_completion=resolution_completion,
        resolution_determination=resolution_determination,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    archive_determination_badge = (
        f'<span class="archive-determination-badge {_archive_determination_badge_class(archive_determination)}">'
        f"{escape(archive_determination)}</span>"
    )
    archive_badge = (
        f'<span class="archive-classification-badge {_archive_classification_badge_class(archive_classification)}">'
        f"{escape(archive_classification)}</span>"
    )
    archive_preconditions_badge = (
        f'<span class="archive-preconditions-badge {_archive_preconditions_badge_class(archive_preconditions)}">'
        f"{escape(archive_preconditions)}</span>"
    )
    archive_pathway_badge = (
        f'<span class="archive-pathway-badge {_archive_pathway_badge_class(archive_pathway)}">'
        f"{escape(archive_pathway)}</span>"
    )
    archive_readiness_badge = (
        f'<span class="archive-readiness-badge {_archive_readiness_badge_class(archive_readiness)}">'
        f"{escape(archive_readiness)}</span>"
    )
    closure_badge = (
        f'<span class="closure-badge {_closure_badge_class(closure)}">'
        f"{escape(closure)}</span>"
    )
    closure_completion_badge = (
        f'<span class="closure-completion-badge {_closure_completion_badge_class(closure_completion)}">'
        f"{escape(closure_completion)}</span>"
    )
    closure_determination_badge = (
        f'<span class="closure-determination-badge {_closure_determination_badge_class(closure_determination)}">'
        f"{escape(closure_determination)}</span>"
    )
    closure_readiness_badge = (
        f'<span class="closure-readiness-badge {_closure_readiness_badge_class(closure_readiness)}">'
        f"{escape(closure_readiness)}</span>"
    )
    resolution_badge = (
        f'<span class="resolution-badge {_resolution_badge_class(resolution)}">'
        f"{escape(resolution)}</span>"
    )
    resolution_completion_badge = (
        f'<span class="resolution-completion-badge {_resolution_completion_badge_class(resolution_completion)}">'
        f"{escape(resolution_completion)}</span>"
    )
    resolution_determination_badge = (
        f'<span class="resolution-determination-badge {_resolution_determination_badge_class(resolution_determination)}">'
        f"{escape(resolution_determination)}</span>"
    )
    outcome_readiness_badge = (
        f'<span class="outcome-readiness-badge {_outcome_readiness_badge_class(outcome_readiness)}">'
        f"{escape(outcome_readiness)}</span>"
    )
    eligibility_badge = (
        f'<span class="eligibility-badge {_eligibility_badge_class(eligibility)}">'
        f"{escape(eligibility)}</span>"
    )
    status_badge = (
        f'<span class="administrative-status-badge {_administrative_status_badge_class(administrative_status)}">'
        f"{escape(administrative_status)}</span>"
    )
    implementation_badge = (
        f'<span class="implementation-action-badge {_implementation_action_badge_class(implementation_action)}">'
        f"{escape(implementation_action)}</span>"
    )
    effective_state_badge = (
        f'<span class="effective-state-badge {_effective_state_badge_class(effective_state)}">'
        f"{escape(effective_state)}</span>"
    )
    rows = (
        ("Archive Determination", archive_determination_badge),
        (
            "Description",
            escape(_describe_archive_determination(archive_determination)),
        ),
        ("Archive Classification", archive_badge),
        ("Archive Preconditions", archive_preconditions_badge),
        ("Archive Pathway", archive_pathway_badge),
        ("Archive Readiness", archive_readiness_badge),
        ("Closure Classification", closure_badge),
        ("Closure Completion", closure_completion_badge),
        ("Closure Determination", closure_determination_badge),
        ("Closure Readiness", closure_readiness_badge),
        ("Resolution Classification", resolution_badge),
        ("Resolution Completion", resolution_completion_badge),
        ("Resolution Determination", resolution_determination_badge),
        ("Outcome Readiness", outcome_readiness_badge),
        ("Review Eligibility", eligibility_badge),
        ("Administrative Status", status_badge),
        ("Implementation Action", implementation_badge),
        ("Effective State", effective_state_badge),
    )
    badge_labels = {
        "Archive Determination",
        "Archive Classification",
        "Archive Preconditions",
        "Archive Pathway",
        "Archive Readiness",
        "Closure Classification",
        "Closure Completion",
        "Closure Determination",
        "Closure Readiness",
        "Resolution Classification",
        "Resolution Completion",
        "Resolution Determination",
        "Outcome Readiness",
        "Review Eligibility",
        "Administrative Status",
        "Implementation Action",
        "Effective State",
    }
    table_rows = "".join(
        "<tr>"
        f"<td>{escape(str(label))}</td>"
        f"<td>{value if label in badge_labels else escape(str(value))}</td>"
        "</tr>"
        for label, value in rows
    )
    return f"""
      <section class="management-section archive-determination">
        <h2>Stage 14E — Archive Determination</h2>
        <p class="notice">
          Archive determination is classified deterministically from archive,
          closure, resolution, outcome, administrative status, implementation
          action, and effective state values only.
        </p>
        <table>
          <tbody>{table_rows}</tbody>
        </table>
      </section>"""


def _render_archive_completion(
    evidence_groups: dict[str, list[dict[str, Any]]],
) -> str:
    readiness_values = _record_evidence_readiness_values(evidence_groups)
    readiness = readiness_values["readiness"]
    action = classify_administrative_action(readiness)
    workflow_state = classify_workflow_state(readiness, action)
    disposition = classify_administrative_disposition(workflow_state)
    eligibility = classify_review_eligibility(disposition)
    status_summary = build_administrative_status_summary(
        disposition,
        eligibility,
        workflow_state,
        readiness,
    )
    administrative_status = status_summary["status"]
    implementation_action = classify_implementation_action(
        administrative_status
    )
    effective_state = classify_effective_state(
        implementation_action,
        administrative_status,
    )
    outcome = classify_outcome(effective_state)
    outcome_preconditions = build_outcome_preconditions(
        outcome,
        effective_state,
        implementation_action,
        administrative_status,
        eligibility,
    )
    outcome_readiness = classify_outcome_readiness(
        outcome,
        outcome_preconditions,
        eligibility,
        administrative_status,
        effective_state,
    )
    outcome_target = classify_outcome_target(
        outcome,
        outcome_readiness,
        effective_state,
        eligibility,
        administrative_status,
    )
    resolution = classify_resolution(
        outcome,
        outcome_readiness,
        outcome_target,
        effective_state,
        implementation_action,
        administrative_status,
    )
    resolution_preconditions = build_resolution_preconditions(
        resolution,
        outcome,
        outcome_readiness,
        outcome_target,
        effective_state,
        implementation_action,
        administrative_status,
        eligibility,
    )
    resolution_pathway = _classify_resolution_pathway(
        resolution=resolution,
        resolution_preconditions=resolution_preconditions,
        outcome_target=outcome_target,
        outcome_readiness=outcome_readiness,
        effective_state=effective_state,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
    )
    resolution_readiness = _classify_resolution_readiness(
        resolution=resolution,
        resolution_preconditions=resolution_preconditions,
        resolution_pathway=resolution_pathway,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    resolution_determination = _classify_resolution_determination(
        resolution=resolution,
        resolution_preconditions=resolution_preconditions,
        resolution_pathway=resolution_pathway,
        resolution_readiness=resolution_readiness,
        outcome_target=outcome_target,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    resolution_completion = _classify_resolution_completion(
        resolution=resolution,
        resolution_preconditions=resolution_preconditions,
        resolution_pathway=resolution_pathway,
        resolution_readiness=resolution_readiness,
        resolution_determination=resolution_determination,
        outcome_target=outcome_target,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    closure = _classify_closure(
        resolution=resolution,
        resolution_completion=resolution_completion,
        resolution_determination=resolution_determination,
        resolution_readiness=resolution_readiness,
        resolution_pathway=resolution_pathway,
        outcome_target=outcome_target,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    closure_preconditions = _classify_closure_preconditions(
        closure=closure,
        resolution=resolution,
        resolution_completion=resolution_completion,
        resolution_determination=resolution_determination,
        resolution_readiness=resolution_readiness,
        resolution_pathway=resolution_pathway,
        outcome_target=outcome_target,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    closure_pathway = _classify_closure_pathway(
        closure=closure,
        closure_preconditions=closure_preconditions,
        resolution=resolution,
        resolution_completion=resolution_completion,
        resolution_determination=resolution_determination,
        resolution_readiness=resolution_readiness,
        resolution_pathway=resolution_pathway,
        outcome_target=outcome_target,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    closure_readiness = _classify_closure_readiness(
        closure_classification=closure,
        closure_preconditions=closure_preconditions,
        closure_pathway=closure_pathway,
        resolution_classification=resolution,
        resolution_completion=resolution_completion,
        resolution_determination=resolution_determination,
        resolution_readiness=resolution_readiness,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    closure_determination = _classify_closure_determination(
        closure_classification=closure,
        closure_preconditions=closure_preconditions,
        closure_pathway=closure_pathway,
        closure_readiness=closure_readiness,
        resolution_classification=resolution,
        resolution_completion=resolution_completion,
        resolution_determination=resolution_determination,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    closure_completion = _classify_closure_completion(
        closure_classification=closure,
        closure_preconditions=closure_preconditions,
        closure_pathway=closure_pathway,
        closure_readiness=closure_readiness,
        closure_determination=closure_determination,
        resolution_classification=resolution,
        resolution_completion=resolution_completion,
        resolution_determination=resolution_determination,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    archive_classification = _archive_classification(
        closure_classification=closure,
        closure_completion=closure_completion,
        closure_determination=closure_determination,
        closure_readiness=closure_readiness,
        resolution_classification=resolution,
        resolution_completion=resolution_completion,
        resolution_determination=resolution_determination,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    archive_preconditions = _archive_preconditions(
        archive_classification=archive_classification,
        closure_classification=closure,
        closure_completion=closure_completion,
        closure_determination=closure_determination,
        closure_readiness=closure_readiness,
        resolution_classification=resolution,
        resolution_completion=resolution_completion,
        resolution_determination=resolution_determination,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    archive_pathway = _archive_pathway(
        archive_classification=archive_classification,
        archive_preconditions=archive_preconditions,
        closure_classification=closure,
        closure_completion=closure_completion,
        closure_determination=closure_determination,
        closure_readiness=closure_readiness,
        resolution_classification=resolution,
        resolution_completion=resolution_completion,
        resolution_determination=resolution_determination,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    archive_readiness = _archive_readiness(
        archive_classification=archive_classification,
        archive_preconditions=archive_preconditions,
        archive_pathway=archive_pathway,
        closure_classification=closure,
        closure_completion=closure_completion,
        closure_determination=closure_determination,
        closure_readiness=closure_readiness,
        resolution_classification=resolution,
        resolution_completion=resolution_completion,
        resolution_determination=resolution_determination,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    archive_determination = _archive_determination(
        archive_classification=archive_classification,
        archive_preconditions=archive_preconditions,
        archive_pathway=archive_pathway,
        archive_readiness=archive_readiness,
        closure_classification=closure,
        closure_completion=closure_completion,
        closure_determination=closure_determination,
        closure_readiness=closure_readiness,
        resolution_classification=resolution,
        resolution_completion=resolution_completion,
        resolution_determination=resolution_determination,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    archive_completion = _archive_completion(
        archive_classification=archive_classification,
        archive_preconditions=archive_preconditions,
        archive_pathway=archive_pathway,
        archive_readiness=archive_readiness,
        archive_determination=archive_determination,
        closure_classification=closure,
        closure_completion=closure_completion,
        closure_determination=closure_determination,
        closure_readiness=closure_readiness,
        resolution_classification=resolution,
        resolution_completion=resolution_completion,
        resolution_determination=resolution_determination,
        outcome_readiness=outcome_readiness,
        review_eligibility=eligibility,
        administrative_status=administrative_status,
        implementation_action=implementation_action,
        effective_state=effective_state,
    )
    archive_completion_badge = (
        f'<span class="archive-completion-badge {_archive_completion_badge_class(archive_completion)}">'
        f"{escape(archive_completion)}</span>"
    )
    archive_badge = (
        f'<span class="archive-classification-badge {_archive_classification_badge_class(archive_classification)}">'
        f"{escape(archive_classification)}</span>"
    )
    archive_determination_badge = (
        f'<span class="archive-determination-badge {_archive_determination_badge_class(archive_determination)}">'
        f"{escape(archive_determination)}</span>"
    )
    archive_readiness_badge = (
        f'<span class="archive-readiness-badge {_archive_readiness_badge_class(archive_readiness)}">'
        f"{escape(archive_readiness)}</span>"
    )
    archive_pathway_badge = (
        f'<span class="archive-pathway-badge {_archive_pathway_badge_class(archive_pathway)}">'
        f"{escape(archive_pathway)}</span>"
    )
    archive_preconditions_badge = (
        f'<span class="archive-preconditions-badge {_archive_preconditions_badge_class(archive_preconditions)}">'
        f"{escape(archive_preconditions)}</span>"
    )
    closure_badge = (
        f'<span class="closure-badge {_closure_badge_class(closure)}">'
        f"{escape(closure)}</span>"
    )
    closure_completion_badge = (
        f'<span class="closure-completion-badge {_closure_completion_badge_class(closure_completion)}">'
        f"{escape(closure_completion)}</span>"
    )
    closure_determination_badge = (
        f'<span class="closure-determination-badge {_closure_determination_badge_class(closure_determination)}">'
        f"{escape(closure_determination)}</span>"
    )
    closure_readiness_badge = (
        f'<span class="closure-readiness-badge {_closure_readiness_badge_class(closure_readiness)}">'
        f"{escape(closure_readiness)}</span>"
    )
    resolution_badge = (
        f'<span class="resolution-badge {_resolution_badge_class(resolution)}">'
        f"{escape(resolution)}</span>"
    )
    resolution_completion_badge = (
        f'<span class="resolution-completion-badge {_resolution_completion_badge_class(resolution_completion)}">'
        f"{escape(resolution_completion)}</span>"
    )
    resolution_determination_badge = (
        f'<span class="resolution-determination-badge {_resolution_determination_badge_class(resolution_determination)}">'
        f"{escape(resolution_determination)}</span>"
    )
    outcome_readiness_badge = (
        f'<span class="outcome-readiness-badge {_outcome_readiness_badge_class(outcome_readiness)}">'
        f"{escape(outcome_readiness)}</span>"
    )
    eligibility_badge = (
        f'<span class="eligibility-badge {_eligibility_badge_class(eligibility)}">'
        f"{escape(eligibility)}</span>"
    )
    status_badge = (
        f'<span class="administrative-status-badge {_administrative_status_badge_class(administrative_status)}">'
        f"{escape(administrative_status)}</span>"
    )
    implementation_badge = (
        f'<span class="implementation-action-badge {_implementation_action_badge_class(implementation_action)}">'
        f"{escape(implementation_action)}</span>"
    )
    effective_state_badge = (
        f'<span class="effective-state-badge {_effective_state_badge_class(effective_state)}">'
        f"{escape(effective_state)}</span>"
    )
    rows = (
        ("Archive Completion", archive_completion_badge),
        ("Description", escape(_describe_archive_completion(archive_completion))),
        ("Archive Classification", archive_badge),
        ("Archive Determination", archive_determination_badge),
        ("Archive Readiness", archive_readiness_badge),
        ("Archive Pathway", archive_pathway_badge),
        ("Archive Preconditions", archive_preconditions_badge),
        ("Closure Classification", closure_badge),
        ("Closure Completion", closure_completion_badge),
        ("Closure Determination", closure_determination_badge),
        ("Closure Readiness", closure_readiness_badge),
        ("Resolution Classification", resolution_badge),
        ("Resolution Completion", resolution_completion_badge),
        ("Resolution Determination", resolution_determination_badge),
        ("Outcome Readiness", outcome_readiness_badge),
        ("Review Eligibility", eligibility_badge),
        ("Administrative Status", status_badge),
        ("Implementation Action", implementation_badge),
        ("Effective State", effective_state_badge),
    )
    badge_labels = {
        "Archive Completion",
        "Archive Classification",
        "Archive Determination",
        "Archive Readiness",
        "Archive Pathway",
        "Archive Preconditions",
        "Closure Classification",
        "Closure Completion",
        "Closure Determination",
        "Closure Readiness",
        "Resolution Classification",
        "Resolution Completion",
        "Resolution Determination",
        "Outcome Readiness",
        "Review Eligibility",
        "Administrative Status",
        "Implementation Action",
        "Effective State",
    }
    table_rows = "".join(
        "<tr>"
        f"<td>{escape(str(label))}</td>"
        f"<td>{value if label in badge_labels else escape(str(value))}</td>"
        "</tr>"
        for label, value in rows
    )
    return f"""
      <section class="management-section archive-completion">
        <h2>Stage 14F — Archive Completion</h2>
        <p class="notice">
          Archive completion is classified deterministically from archive,
          closure, resolution, outcome, administrative status, implementation
          action, and effective state values only.
        </p>
        <table>
          <tbody>{table_rows}</tbody>
        </table>
      </section>"""


def _record_evidence_coverage(
    evidence_groups: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    counts = {}
    total_targets = 0
    supported_targets = 0
    for target_type in ("condition", "signal", "finding", "record"):
        targets = evidence_groups.get(target_type) or []
        target_total = len(targets)
        target_supported = sum(1 for target in targets if target.get("attachments"))
        counts[target_type] = {
            "supported": target_supported,
            "total": target_total,
        }
        total_targets += target_total
        supported_targets += target_supported

    if supported_targets == 0:
        status = "Unsupported"
    elif total_targets > 0 and supported_targets == total_targets:
        status = "Complete"
    else:
        status = "Partial"

    return {
        "status": status,
        "counts": counts,
        "supported_targets": supported_targets,
        "total_targets": total_targets,
    }


def _render_record_evidence_coverage(
    evidence_groups: dict[str, list[dict[str, Any]]],
) -> str:
    coverage = _record_evidence_coverage(evidence_groups)
    labels = {
        "condition": "Conditions Supported",
        "signal": "Signals Supported",
        "finding": "Findings Supported",
        "record": "Record Supported",
    }
    rows = []
    for target_type in ("condition", "signal", "finding", "record"):
        count = coverage["counts"][target_type]
        rows.append(
            "<tr>"
            f"<td>{labels[target_type]}</td>"
            f"<td>{count['supported']} / {count['total']}</td>"
            "</tr>"
        )
    rows.append(
        "<tr>"
        "<td>Overall Coverage</td>"
        f"<td>{escape(coverage['status'])}</td>"
        "</tr>"
    )
    return f"""
      <section class="management-section record-evidence-coverage">
        <h2>Record Evidence Coverage</h2>
        <table>
          <tbody>{"".join(rows)}</tbody>
        </table>
      </section>"""


def _stage15d_support_relationship_count(target: dict[str, Any]) -> int:
    return int((target.get("relationship_type_counts") or {}).get("supports", 0))


def _stage15d_support_attachment_count(target: dict[str, Any]) -> int:
    count = 0
    for attachment in target.get("attachments") or []:
        relationship_counts = attachment.get("relationship_type_counts") or {}
        if int(relationship_counts.get("supports", 0)) > 0:
            count += 1
    return count


def _classify_stage15d_target_sufficiency(
    support_relationship_count: int,
) -> str:
    if support_relationship_count >= 3:
        return "Strong"
    if support_relationship_count >= 2:
        return "Sufficient"
    if support_relationship_count == 1:
        return "Partial"
    return "Unsupported"


def _classify_stage15d_group_sufficiency(
    target_summaries: list[dict[str, Any]],
) -> str:
    if not target_summaries:
        return "Unsupported"
    classifications = [
        str(summary.get("sufficiency") or "Unsupported")
        for summary in target_summaries
    ]
    if all(classification == "Strong" for classification in classifications):
        return "Strong"
    if all(classification in {"Sufficient", "Strong"} for classification in classifications):
        return "Sufficient"
    if any(classification != "Unsupported" for classification in classifications):
        return "Partial"
    return "Unsupported"


def _record_stage15d_evidence_sufficiency(
    evidence_groups: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    groups: dict[str, dict[str, Any]] = {}
    total_support_relationships = 0
    required_group_summaries = []

    for target_type in ("condition", "signal", "finding", "record"):
        target_summaries = []
        for target in evidence_groups.get(target_type) or []:
            relationship_count = _stage15d_support_relationship_count(target)
            attachment_count = _stage15d_support_attachment_count(target)
            total_support_relationships += relationship_count
            target_summaries.append(
                {
                    "target_key": target.get("target_key"),
                    "target_label": target.get("target_label")
                    or target.get("target_key")
                    or "",
                    "supporting_attachment_count": attachment_count,
                    "supporting_relationship_count": relationship_count,
                    "sufficiency": _classify_stage15d_target_sufficiency(
                        relationship_count
                    ),
                }
            )

        group_sufficiency = _classify_stage15d_group_sufficiency(target_summaries)
        group_summary = {
            "sufficiency": group_sufficiency,
            "targets": target_summaries,
            "target_count": len(target_summaries),
        }
        groups[target_type] = group_summary
        if target_summaries:
            required_group_summaries.append(group_summary)

    if total_support_relationships == 0:
        overall = "Unsupported"
    elif required_group_summaries and all(
        group["sufficiency"] == "Strong" for group in required_group_summaries
    ):
        overall = "Strong"
    elif required_group_summaries and all(
        group["sufficiency"] in {"Sufficient", "Strong"}
        for group in required_group_summaries
    ):
        overall = "Sufficient"
    else:
        overall = "Partial"

    return {
        "overall": overall,
        "groups": groups,
        "supporting_relationship_count": total_support_relationships,
    }


def _supporting_attachment_label(count: int) -> str:
    return "supporting attachment" if count == 1 else "supporting attachments"


def _render_stage15d_target_sufficiency_list(
    target_type: str,
    targets: list[dict[str, Any]],
) -> str:
    if not targets:
        return (
            f"<h3>{escape(_target_type_display_label(target_type))} Sufficiency</h3>"
            '<p class="evidence-empty-state">No targets available.</p>'
        )
    items = "".join(
        "<li>"
        f"{escape(str(target['target_label']))} — "
        f"{escape(str(target['sufficiency']))} — "
        f"{int(target['supporting_attachment_count'])} "
        f"{_supporting_attachment_label(int(target['supporting_attachment_count']))}"
        "</li>"
        for target in targets
    )
    return (
        f"<h3>{escape(_target_type_display_label(target_type))} Sufficiency</h3>"
        f'<ul class="stage15d-target-sufficiency-list">{items}</ul>'
    )


def _render_stage15d_evidence_sufficiency(
    evidence_groups: dict[str, list[dict[str, Any]]],
) -> str:
    sufficiency = _record_stage15d_evidence_sufficiency(evidence_groups)
    labels = {
        "condition": "Conditions Sufficiency",
        "signal": "Signals Sufficiency",
        "finding": "Findings Sufficiency",
        "record": "Record Sufficiency",
    }
    summary_rows = []
    for target_type in ("condition", "signal", "finding", "record"):
        summary_rows.append(
            "<tr>"
            f"<td>{labels[target_type]}</td>"
            f"<td>{escape(str(sufficiency['groups'][target_type]['sufficiency']))}</td>"
            "</tr>"
        )
    summary_rows.append(
        "<tr>"
        "<td>Overall Sufficiency</td>"
        f"<td>{escape(str(sufficiency['overall']))}</td>"
        "</tr>"
    )
    target_sections = "".join(
        _render_stage15d_target_sufficiency_list(
            target_type,
            sufficiency["groups"][target_type]["targets"],
        )
        for target_type in ("condition", "signal", "finding", "record")
    )
    return f"""
      <section class="management-section stage15d-evidence-sufficiency">
        <h2>Evidence Sufficiency</h2>
        <p class="notice">
          Evidence sufficiency is classified deterministically from active
          supports relationships and target coverage only.
        </p>
        <table class="stage15d-sufficiency-summary">
          <tbody>{"".join(summary_rows)}</tbody>
        </table>
        <section class="stage15d-target-sufficiency">
          {target_sections}
        </section>
      </section>"""


def _stage15e_target_is_complete(sufficiency: str) -> bool:
    return sufficiency in {"Sufficient", "Strong"}


def _classify_stage15e_group_completeness(
    target_summaries: list[dict[str, Any]],
) -> str:
    if not target_summaries:
        return "Not Applicable"
    complete_count = sum(
        1 for summary in target_summaries if bool(summary.get("is_complete"))
    )
    if complete_count == 0:
        return "Incomplete"
    if complete_count == len(target_summaries):
        return "Complete"
    return "Partial"


def _classify_stage15e_overall_completeness(
    complete_targets: int,
    total_targets: int,
) -> str:
    if total_targets <= 0 or complete_targets == 0:
        return "Incomplete"
    if complete_targets == total_targets:
        return "Complete"
    return "Partial"


def _format_stage15e_percentage(complete_targets: int, total_targets: int) -> str:
    if total_targets <= 0:
        return "0%"
    percentage = (complete_targets / total_targets) * 100
    if percentage.is_integer():
        return f"{int(percentage)}%"
    return f"{percentage:.1f}%"


def _record_stage15e_evidence_completeness(
    evidence_groups: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    sufficiency = _record_stage15d_evidence_sufficiency(evidence_groups)
    groups: dict[str, dict[str, Any]] = {}
    complete_targets = 0
    total_targets = 0

    for target_type in ("condition", "signal", "finding", "record"):
        target_summaries = []
        for target in sufficiency["groups"][target_type]["targets"]:
            target_sufficiency = str(target["sufficiency"])
            is_complete = _stage15e_target_is_complete(target_sufficiency)
            if is_complete:
                complete_targets += 1
            total_targets += 1
            target_summaries.append(
                {
                    **target,
                    "is_complete": is_complete,
                    "completeness": "Complete" if is_complete else "Incomplete",
                }
            )
        groups[target_type] = {
            "completeness": _classify_stage15e_group_completeness(
                target_summaries
            ),
            "targets": target_summaries,
            "target_count": len(target_summaries),
        }

    incomplete_targets = max(total_targets - complete_targets, 0)
    return {
        "overall": _classify_stage15e_overall_completeness(
            complete_targets,
            total_targets,
        ),
        "groups": groups,
        "complete_targets": complete_targets,
        "incomplete_targets": incomplete_targets,
        "total_targets": total_targets,
        "percentage": _format_stage15e_percentage(complete_targets, total_targets),
    }


def _render_stage15e_target_completeness_list(
    target_type: str,
    targets: list[dict[str, Any]],
) -> str:
    if not targets:
        return (
            f"<h3>{escape(_target_type_display_label(target_type))} Completeness</h3>"
            '<p class="evidence-empty-state">No targets available.</p>'
        )
    items = "".join(
        "<li>"
        f"{escape(str(target['target_label']))} — "
        f"{escape(str(target['completeness']))} — "
        f"{escape(str(target['sufficiency']))} sufficiency — "
        f"{int(target['supporting_attachment_count'])} "
        f"{_supporting_attachment_label(int(target['supporting_attachment_count']))}"
        "</li>"
        for target in targets
    )
    return (
        f"<h3>{escape(_target_type_display_label(target_type))} Completeness</h3>"
        f'<ul class="stage15e-target-completeness-list">{items}</ul>'
    )


def _render_stage15e_evidence_completeness(
    evidence_groups: dict[str, list[dict[str, Any]]],
) -> str:
    completeness = _record_stage15e_evidence_completeness(evidence_groups)
    labels = {
        "condition": "Conditions Completeness",
        "signal": "Signals Completeness",
        "finding": "Findings Completeness",
        "record": "Record Completeness",
    }
    summary_rows = []
    for target_type in ("condition", "signal", "finding", "record"):
        summary_rows.append(
            "<tr>"
            f"<td>{labels[target_type]}</td>"
            f"<td>{escape(str(completeness['groups'][target_type]['completeness']))}</td>"
            "</tr>"
        )
    for label, value in (
        ("Overall Completeness", completeness["overall"]),
        ("Complete Targets", completeness["complete_targets"]),
        ("Incomplete Targets", completeness["incomplete_targets"]),
        ("Completeness Percentage", completeness["percentage"]),
    ):
        summary_rows.append(
            "<tr>"
            f"<td>{escape(str(label))}</td>"
            f"<td>{escape(str(value))}</td>"
            "</tr>"
        )
    target_sections = "".join(
        _render_stage15e_target_completeness_list(
            target_type,
            completeness["groups"][target_type]["targets"],
        )
        for target_type in ("condition", "signal", "finding", "record")
    )
    return f"""
      <section class="management-section stage15e-evidence-completeness">
        <h2>Evidence Completeness</h2>
        <p class="notice">
          Evidence completeness is classified deterministically from Stage 15D
          sufficiency values and required record targets only.
        </p>
        <table class="stage15e-completeness-summary">
          <tbody>{"".join(summary_rows)}</tbody>
        </table>
        <section class="stage15e-target-completeness">
          {target_sections}
        </section>
      </section>"""


def _stage15f_additional_attachments_required(
    support_relationship_count: int,
) -> int:
    return max(0, 2 - int(support_relationship_count))


def _classify_stage15f_group_requirement_status(
    target_summaries: list[dict[str, Any]],
) -> str:
    if not target_summaries:
        return "not_applicable"
    if any(int(target.get("additional_required") or 0) > 0 for target in target_summaries):
        return "outstanding"
    return "none_required"


def _classify_stage15f_overall_requirement_status(
    targets_requiring_evidence: int,
) -> str:
    return "outstanding" if int(targets_requiring_evidence) > 0 else "none_required"


def _record_stage15f_evidence_requirements(
    evidence_groups: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    sufficiency = _record_stage15d_evidence_sufficiency(evidence_groups)
    groups: dict[str, dict[str, Any]] = {}
    total_targets_requiring_evidence = 0
    total_additional_required = 0

    for target_type in ("condition", "signal", "finding", "record"):
        target_summaries = []
        for target in sufficiency["groups"][target_type]["targets"]:
            support_count = int(target["supporting_relationship_count"])
            additional_required = _stage15f_additional_attachments_required(
                support_count
            )
            if additional_required > 0:
                total_targets_requiring_evidence += 1
                total_additional_required += additional_required
            target_summaries.append(
                {
                    **target,
                    "additional_required": additional_required,
                    "requires_evidence": additional_required > 0,
                }
            )

        groups[target_type] = {
            "requirement_status": _classify_stage15f_group_requirement_status(
                target_summaries
            ),
            "targets": target_summaries,
            "target_count": len(target_summaries),
            "targets_requiring_evidence": sum(
                1 for target in target_summaries if target["requires_evidence"]
            ),
            "additional_required": sum(
                int(target["additional_required"]) for target in target_summaries
            ),
        }

    return {
        "overall_status": _classify_stage15f_overall_requirement_status(
            total_targets_requiring_evidence
        ),
        "groups": groups,
        "targets_requiring_evidence": total_targets_requiring_evidence,
        "additional_required": total_additional_required,
    }


def _stage15f_attachment_requirement_label(count: int) -> str:
    return (
        "additional supporting attachment"
        if int(count) == 1
        else "additional supporting attachments"
    )


def _render_stage15f_target_requirements_list(
    target_type: str,
    targets: list[dict[str, Any]],
) -> str:
    if not targets:
        return (
            f"<h3>{escape(_target_type_display_label(target_type))} Requirements</h3>"
            '<p class="evidence-empty-state">No targets available.</p>'
        )

    requiring_targets = [
        target for target in targets if int(target.get("additional_required") or 0) > 0
    ]
    if not requiring_targets:
        return (
            f"<h3>{escape(_target_type_display_label(target_type))} Requirements</h3>"
            '<p class="evidence-empty-state">No additional evidence required.</p>'
        )

    items = "".join(
        "<li>"
        f"{escape(str(target['target_label']))} — "
        f"{int(target['additional_required'])} "
        f"{_stage15f_attachment_requirement_label(int(target['additional_required']))} "
        "required to reach sufficient"
        "</li>"
        for target in requiring_targets
    )
    return (
        f"<h3>{escape(_target_type_display_label(target_type))} Requirements</h3>"
        f'<ul class="stage15f-target-requirements-list">{items}</ul>'
    )


def _render_stage15f_evidence_requirements(
    evidence_groups: dict[str, list[dict[str, Any]]],
) -> str:
    requirements = _record_stage15f_evidence_requirements(evidence_groups)
    labels = {
        "condition": "Conditions Requirement Status",
        "signal": "Signals Requirement Status",
        "finding": "Findings Requirement Status",
        "record": "Record Requirement Status",
    }
    summary_rows = []
    for target_type in ("condition", "signal", "finding", "record"):
        group = requirements["groups"][target_type]
        summary_rows.extend(
            (
                "<tr>"
                f"<td>{labels[target_type]}</td>"
                f"<td>{escape(str(group['requirement_status']))}</td>"
                "</tr>",
                "<tr>"
                f"<td>{escape(_target_type_display_label(target_type))} Additional Attachments Required</td>"
                f"<td>{int(group['additional_required'])}</td>"
                "</tr>",
            )
        )
    for label, value in (
        ("Overall Requirement Status", requirements["overall_status"]),
        ("Targets Requiring Evidence", requirements["targets_requiring_evidence"]),
        ("Additional Attachments Required", requirements["additional_required"]),
    ):
        summary_rows.append(
            "<tr>"
            f"<td>{escape(str(label))}</td>"
            f"<td>{escape(str(value))}</td>"
            "</tr>"
        )
    target_sections = "".join(
        _render_stage15f_target_requirements_list(
            target_type,
            requirements["groups"][target_type]["targets"],
        )
        for target_type in ("condition", "signal", "finding", "record")
    )
    return f"""
      <section class="management-section stage15f-evidence-requirements">
        <h2>Evidence Requirements</h2>
        <p class="notice">
          Evidence requirements are classified deterministically from Stage 15D
          sufficiency thresholds and active supports relationships only.
        </p>
        <table class="stage15f-requirements-summary">
          <tbody>{"".join(summary_rows)}</tbody>
        </table>
        <section class="stage15f-target-requirements">
          {target_sections}
        </section>
      </section>"""


def _render_stage16a_evidence_standards() -> str:
    summary_rows = (
        ("Standard Type", "Current deterministic standard"),
        ("Minimum for Partial", "1 active supporting attachment"),
        ("Minimum for Sufficient", "2 active supporting attachments"),
        ("Minimum for Strong", "3 active supporting attachments"),
        ("Completion Threshold", "sufficient or strong"),
        (
            "Requirement Basis",
            "additional attachments required to reach sufficient",
        ),
        ("Relationship Scope", "active supports relationships only"),
    )
    table_rows = "".join(
        "<tr>"
        f"<td>{escape(label)}</td>"
        f"<td>{escape(value)}</td>"
        "</tr>"
        for label, value in summary_rows
    )
    return f"""
      <section class="management-section stage16a-evidence-standards">
        <h2>Evidence Standards</h2>
        <p class="notice">
          Evidence standards are displayed as the current deterministic standard
          used by the admin evidence assessment layer.
        </p>
        <table class="stage16a-standards-summary">
          <tbody>{table_rows}</tbody>
        </table>
        <section class="stage16a-target-standard">
          <h3>Target Standard</h3>
          <dl>
            <dt>Unsupported</dt>
            <dd>0 active supporting attachments</dd>
            <dt>Partial</dt>
            <dd>1 active supporting attachment</dd>
            <dt>Sufficient</dt>
            <dd>2 active supporting attachments</dd>
            <dt>Strong</dt>
            <dd>3 or more active supporting attachments</dd>
          </dl>
        </section>
        <section class="stage16a-requirement-standard">
          <h3>Requirement Standard</h3>
          <p>Unsupported targets require 2 additional supporting attachments.</p>
          <p>Partial targets require 1 additional supporting attachment.</p>
          <p>Sufficient and strong targets require no additional supporting attachments.</p>
        </section>
      </section>"""


def _stage16b_standard_applied(sufficiency: str) -> str:
    return {
        "Unsupported": "Unsupported = 0 active supports; Sufficient = 2 active supports",
        "Partial": "Partial = 1 active support; Sufficient = 2 active supports",
        "Sufficient": "Sufficient = 2 active supports",
        "Strong": "Strong = 3 or more active supports",
    }.get(
        sufficiency,
        "Sufficient = 2 active supports",
    )


def _stage16b_justification_sentence(
    *,
    support_count: int,
    sufficiency: str,
    completeness: str,
    additional_required: int,
) -> str:
    support_label = "active support" if support_count == 1 else "active supports"
    sentence = (
        f"This target is classified as {sufficiency} because it has "
        f"{support_count} {support_label}. "
    )
    if completeness == "Complete":
        sentence += (
            "It is Complete because completion requires Sufficient or Strong "
            "sufficiency. "
        )
    else:
        sentence += (
            "It remains Incomplete because completion requires Sufficient or "
            "Strong sufficiency. "
        )
    if additional_required > 0:
        attachment_label = (
            "additional supporting attachment"
            if additional_required == 1
            else "additional supporting attachments"
        )
        sentence += (
            f"It requires {additional_required} {attachment_label} to reach "
            "Sufficient."
        )
    else:
        sentence += "No additional supporting attachments are required."
    return sentence


def _record_stage16b_evidence_justifications(
    evidence_groups: dict[str, list[dict[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    requirements = _record_stage15f_evidence_requirements(evidence_groups)
    justifications: dict[str, list[dict[str, Any]]] = {}
    for target_type in ("condition", "signal", "finding", "record"):
        targets = []
        for target in requirements["groups"][target_type]["targets"]:
            sufficiency = str(target["sufficiency"])
            completeness = (
                "Complete"
                if _stage15e_target_is_complete(sufficiency)
                else "Incomplete"
            )
            support_count = int(target["supporting_relationship_count"])
            additional_required = int(target["additional_required"])
            targets.append(
                {
                    "target_label": target["target_label"],
                    "active_supports": support_count,
                    "sufficiency": sufficiency,
                    "completeness": completeness,
                    "additional_required": additional_required,
                    "standard_applied": _stage16b_standard_applied(sufficiency),
                    "justification": _stage16b_justification_sentence(
                        support_count=support_count,
                        sufficiency=sufficiency,
                        completeness=completeness,
                        additional_required=additional_required,
                    ),
                }
            )
        justifications[target_type] = targets
    return justifications


def _render_stage16b_target_justifications(
    target_type: str,
    targets: list[dict[str, Any]],
) -> str:
    if not targets:
        return (
            f"<h3>{escape(_target_type_display_label(target_type))} Justification</h3>"
            '<p class="evidence-empty-state">No targets available.</p>'
        )
    cards = []
    for target in targets:
        rows = (
            ("Active supports", target["active_supports"]),
            ("Sufficiency", target["sufficiency"]),
            ("Completeness", target["completeness"]),
            ("Additional attachments required", target["additional_required"]),
            ("Standard applied", target["standard_applied"]),
            ("Justification", target["justification"]),
        )
        table_rows = "".join(
            "<tr>"
            f"<td>{escape(str(label))}</td>"
            f"<td>{escape(str(value))}</td>"
            "</tr>"
            for label, value in rows
        )
        cards.append(
            '<article class="stage16b-target-justification">'
            f"<h4>{escape(str(target['target_label']))}</h4>"
            f"<table><tbody>{table_rows}</tbody></table>"
            "</article>"
        )
    return (
        f"<h3>{escape(_target_type_display_label(target_type))} Justification</h3>"
        f"{''.join(cards)}"
    )


def _render_stage16b_evidence_justification(
    evidence_groups: dict[str, list[dict[str, Any]]],
) -> str:
    justifications = _record_stage16b_evidence_justifications(evidence_groups)
    sections = "".join(
        _render_stage16b_target_justifications(
            target_type,
            justifications[target_type],
        )
        for target_type in ("condition", "signal", "finding", "record")
    )
    return f"""
      <section class="management-section stage16b-evidence-justification">
        <h2>Evidence Justification</h2>
        <p class="notice">
          Evidence justification is derived deterministically from active
          supports, sufficiency, completeness, requirements, and standards.
        </p>
        {sections}
      </section>"""


_STAGE16C_CONFIDENCE_ORDER = {
    "Low Confidence": 0,
    "Limited Confidence": 1,
    "High Confidence": 2,
    "Very High Confidence": 3,
}


def _classify_stage16c_evidence_confidence(
    sufficiency: str,
    completeness: str,
) -> str:
    confidence = {
        "Unsupported": "Low Confidence",
        "Partial": "Limited Confidence",
        "Sufficient": "High Confidence",
        "Strong": "Very High Confidence",
    }.get(sufficiency, "Low Confidence")
    if (
        completeness != "Complete"
        and _STAGE16C_CONFIDENCE_ORDER[confidence]
        > _STAGE16C_CONFIDENCE_ORDER["Limited Confidence"]
    ):
        return "Limited Confidence"
    return confidence


def _stage16c_confidence_reason(
    sufficiency: str,
    completeness: str,
) -> str:
    if completeness == "Complete":
        return (
            f"Target has {sufficiency} sufficiency and meets the completion "
            "threshold."
        )
    return f"Target has {sufficiency} sufficiency and is not Complete."


def _record_stage16c_evidence_confidence(
    evidence_groups: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    sufficiency = _record_stage15d_evidence_sufficiency(evidence_groups)
    completeness = _record_stage15e_evidence_completeness(evidence_groups)
    groups: dict[str, dict[str, Any]] = {}

    for target_type in ("condition", "signal", "finding", "record"):
        target_summaries = []
        for target in completeness["groups"][target_type]["targets"]:
            target_sufficiency = str(target["sufficiency"])
            target_completeness = str(target["completeness"])
            target_summaries.append(
                {
                    **target,
                    "confidence": _classify_stage16c_evidence_confidence(
                        target_sufficiency,
                        target_completeness,
                    ),
                    "confidence_reason": _stage16c_confidence_reason(
                        target_sufficiency,
                        target_completeness,
                    ),
                }
            )

        group_sufficiency = str(sufficiency["groups"][target_type]["sufficiency"])
        group_completeness = str(completeness["groups"][target_type]["completeness"])
        groups[target_type] = {
            "confidence": (
                "Not Applicable"
                if group_completeness == "Not Applicable"
                else _classify_stage16c_evidence_confidence(
                    group_sufficiency,
                    group_completeness,
                )
            ),
            "targets": target_summaries,
        }

    return {
        "overall": _classify_stage16c_evidence_confidence(
            str(sufficiency["overall"]),
            str(completeness["overall"]),
        ),
        "groups": groups,
    }


def _render_stage16c_target_confidence(
    target_type: str,
    targets: list[dict[str, Any]],
) -> str:
    if not targets:
        return (
            f"<h3>{escape(_target_type_display_label(target_type))} Confidence</h3>"
            '<p class="evidence-empty-state">No targets available.</p>'
        )

    cards = []
    for target in targets:
        rows = (
            ("Sufficiency", target["sufficiency"]),
            ("Completeness", target["completeness"]),
            ("Confidence", target["confidence"]),
            ("Reason", target["confidence_reason"]),
        )
        table_rows = "".join(
            "<tr>"
            f"<td>{escape(str(label))}</td>"
            f"<td>{escape(str(value))}</td>"
            "</tr>"
            for label, value in rows
        )
        cards.append(
            '<article class="stage16c-target-confidence">'
            f"<h4>{escape(str(target['target_label']))}</h4>"
            f"<table><tbody>{table_rows}</tbody></table>"
            "</article>"
        )
    return (
        f"<h3>{escape(_target_type_display_label(target_type))} Confidence</h3>"
        f"{''.join(cards)}"
    )


def _render_stage16c_evidence_confidence(
    evidence_groups: dict[str, list[dict[str, Any]]],
) -> str:
    confidence = _record_stage16c_evidence_confidence(evidence_groups)
    labels = {
        "condition": "Conditions Confidence",
        "signal": "Signals Confidence",
        "finding": "Findings Confidence",
        "record": "Record Confidence",
    }
    summary_rows = []
    for target_type in ("condition", "signal", "finding", "record"):
        summary_rows.append(
            "<tr>"
            f"<td>{labels[target_type]}</td>"
            f"<td>{escape(str(confidence['groups'][target_type]['confidence']))}</td>"
            "</tr>"
        )
    summary_rows.append(
        "<tr>"
        "<td>Overall Confidence</td>"
        f"<td>{escape(str(confidence['overall']))}</td>"
        "</tr>"
    )
    sections = "".join(
        _render_stage16c_target_confidence(
            target_type,
            confidence["groups"][target_type]["targets"],
        )
        for target_type in ("condition", "signal", "finding", "record")
    )
    return f"""
      <section class="management-section stage16c-evidence-confidence">
        <h2>Evidence Confidence</h2>
        <p class="notice">
          Evidence confidence is deterministic and derived only from existing
          sufficiency and completeness values. It is not statistical confidence,
          AI confidence, or probability.
        </p>
        <table class="stage16c-confidence-summary">
          <tbody>{"".join(summary_rows)}</tbody>
        </table>
        <section class="stage16c-target-confidence-list">
          {sections}
        </section>
      </section>"""

def _stage16d_support_relationship_traces(target: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        trace
        for trace in target.get("relationship_traces") or []
        if str(trace.get("relationship_type") or "") == "supports"
    ]


def _stage16d_support_attachment_titles(target: dict[str, Any]) -> list[str]:
    titles: list[str] = []
    seen_attachment_ids = set()
    for attachment in target.get("attachments") or []:
        relationship_counts = attachment.get("relationship_type_counts") or {}
        if int(relationship_counts.get("supports", 0)) <= 0:
            continue
        attachment_id = attachment.get("attachment_id")
        if attachment_id in seen_attachment_ids:
            continue
        seen_attachment_ids.add(attachment_id)
        titles.append(str(attachment.get("title") or "Untitled attachment"))
    return titles


def _record_stage16d_evidence_traceability(
    evidence_groups: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    sufficiency = _record_stage15d_evidence_sufficiency(evidence_groups)
    completeness = _record_stage15e_evidence_completeness(evidence_groups)
    justifications = _record_stage16b_evidence_justifications(evidence_groups)
    confidence = _record_stage16c_evidence_confidence(evidence_groups)
    groups: dict[str, list[dict[str, Any]]] = {}
    total_traced_targets = 0
    total_traced_relationships = 0
    referenced_attachment_ids = set()

    for target_type in ("condition", "signal", "finding", "record"):
        targets = []
        for index, target in enumerate(evidence_groups.get(target_type) or []):
            support_traces = _stage16d_support_relationship_traces(target)
            support_attachment_titles = _stage16d_support_attachment_titles(target)
            relationship_types = sorted(
                {
                    str(trace.get("relationship_type") or "")
                    for trace in support_traces
                    if trace.get("relationship_type")
                }
            )
            for trace in support_traces:
                attachment_id = trace.get("attachment_id")
                if attachment_id not in (None, ""):
                    referenced_attachment_ids.add(attachment_id)

            sufficiency_target = sufficiency["groups"][target_type]["targets"][index]
            completeness_target = completeness["groups"][target_type]["targets"][index]
            justification_target = justifications[target_type][index]
            confidence_target = confidence["groups"][target_type]["targets"][index]
            total_traced_targets += 1
            total_traced_relationships += len(support_traces)
            targets.append(
                {
                    "target_name": target.get("target_label")
                    or target.get("target_key")
                    or "",
                    "active_supports": len(support_traces),
                    "supporting_attachment_titles": support_attachment_titles,
                    "relationship_types": relationship_types,
                    "sufficiency": sufficiency_target["sufficiency"],
                    "completeness": completeness_target["completeness"],
                    "confidence": confidence_target["confidence"],
                    "justification_summary": justification_target["justification"],
                }
            )
        groups[target_type] = targets

    return {
        "groups": groups,
        "summary": {
            "total_traced_targets": total_traced_targets,
            "total_traced_relationships": total_traced_relationships,
            "total_supporting_attachments_referenced": len(referenced_attachment_ids),
        },
    }


def _stage16d_traceability_value_list(values: list[str], empty_label: str) -> str:
    if not values:
        return empty_label
    return ", ".join(values)


def _render_stage16d_target_traceability(
    target_type: str,
    targets: list[dict[str, Any]],
) -> str:
    if not targets:
        return (
            f"<h3>{escape(_target_type_display_label(target_type))} Traceability</h3>"
            '<p class="evidence-empty-state">No targets available.</p>'
        )

    cards = []
    for target in targets:
        rows = (
            ("Active supports count", target["active_supports"]),
            (
                "Supporting attachment titles",
                _stage16d_traceability_value_list(
                    target["supporting_attachment_titles"],
                    "No supporting attachment titles.",
                ),
            ),
            (
                "Relationship type(s)",
                _stage16d_traceability_value_list(
                    target["relationship_types"],
                    "No active supports relationships.",
                ),
            ),
            ("Sufficiency state", target["sufficiency"]),
            ("Completeness state", target["completeness"]),
            ("Confidence state", target["confidence"]),
            ("Justification summary", target["justification_summary"]),
        )
        table_rows = "".join(
            "<tr>"
            f"<td>{escape(str(label))}</td>"
            f"<td>{escape(str(value))}</td>"
            "</tr>"
            for label, value in rows
        )
        cards.append(
            '<article class="stage16d-target-traceability">'
            f"<h4>{escape(str(target['target_name']))}</h4>"
            f"<table><tbody>{table_rows}</tbody></table>"
            "</article>"
        )
    return (
        f"<h3>{escape(_target_type_display_label(target_type))} Traceability</h3>"
        f"{''.join(cards)}"
    )


def _render_stage16d_evidence_traceability(
    evidence_groups: dict[str, list[dict[str, Any]]],
) -> str:
    traceability = _record_stage16d_evidence_traceability(evidence_groups)
    summary = traceability["summary"]
    summary_rows = (
        ("Total Traced Targets", summary["total_traced_targets"]),
        ("Total Traced Relationships", summary["total_traced_relationships"]),
        (
            "Total Supporting Attachments Referenced",
            summary["total_supporting_attachments_referenced"],
        ),
    )
    table_rows = "".join(
        "<tr>"
        f"<td>{escape(str(label))}</td>"
        f"<td>{escape(str(value))}</td>"
        "</tr>"
        for label, value in summary_rows
    )
    sections = "".join(
        _render_stage16d_target_traceability(
            target_type,
            traceability["groups"][target_type],
        )
        for target_type in ("condition", "signal", "finding", "record")
    )
    return f"""
      <section class="management-section stage16d-evidence-traceability">
        <h2>Evidence Traceability</h2>
        <p class="notice">
          Evidence traceability is derived deterministically from active supports
          relationships, linked attachment metadata, sufficiency, completeness,
          justification, and confidence outputs only.
        </p>
        <table class="stage16d-traceability-summary">
          <tbody>{table_rows}</tbody>
        </table>
        <section class="stage16d-target-traceability-list">
          {sections}
        </section>
      </section>"""


def _stage16e_active_attachment_titles(events: list[dict[str, Any]]) -> list[str]:
    titles: list[str] = []
    seen_attachment_ids = set()
    for event in events:
        if not bool(event.get("is_active")):
            continue
        attachment_id = event.get("attachment_id")
        if attachment_id in seen_attachment_ids:
            continue
        seen_attachment_ids.add(attachment_id)
        titles.append(str(event.get("attachment_title") or "Untitled attachment"))
    return titles


def _stage16e_first_created_at(events: list[dict[str, Any]]) -> str:
    created_values = sorted(str(event.get("created_at") or "") for event in events)
    created_values = [value for value in created_values if value]
    return created_values[0] if created_values else "Not recorded"


def _stage16e_latest_created_at(events: list[dict[str, Any]]) -> str:
    created_values = sorted(str(event.get("created_at") or "") for event in events)
    created_values = [value for value in created_values if value]
    return created_values[-1] if created_values else "Not recorded"


def _record_stage16e_evidence_lineage(
    evidence_groups: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    sufficiency = _record_stage15d_evidence_sufficiency(evidence_groups)
    completeness = _record_stage15e_evidence_completeness(evidence_groups)
    confidence = _record_stage16c_evidence_confidence(evidence_groups)
    groups: dict[str, list[dict[str, Any]]] = {}
    total_lineage_targets = 0
    total_relationship_events = 0
    active_support_relationships = 0
    inactive_relationships = 0
    targets_with_lineage = 0

    for target_type in ("condition", "signal", "finding", "record"):
        target_lineage = []
        for index, target in enumerate(evidence_groups.get(target_type) or []):
            events = list(target.get("relationship_lineage_events") or [])
            active_events = [event for event in events if bool(event.get("is_active"))]
            inactive_events = [
                event for event in events if not bool(event.get("is_active"))
            ]
            total_lineage_targets += 1
            total_relationship_events += len(events)
            active_support_relationships += len(active_events)
            inactive_relationships += len(inactive_events)
            if events:
                targets_with_lineage += 1

            target_lineage.append(
                {
                    "target_type": target_type,
                    "target_label": target.get("target_label")
                    or target.get("target_key")
                    or "",
                    "total_relationship_events": len(events),
                    "active_support_count": len(active_events),
                    "inactive_relationship_count": len(inactive_events),
                    "first_support_created_at": _stage16e_first_created_at(events),
                    "latest_support_created_at": _stage16e_latest_created_at(events),
                    "active_supporting_attachment_titles": (
                        _stage16e_active_attachment_titles(events)
                    ),
                    "events": events,
                    "sufficiency": sufficiency["groups"][target_type]["targets"][
                        index
                    ]["sufficiency"],
                    "completeness": completeness["groups"][target_type]["targets"][
                        index
                    ]["completeness"],
                    "confidence": confidence["groups"][target_type]["targets"][
                        index
                    ]["confidence"],
                }
            )
        groups[target_type] = target_lineage

    return {
        "groups": groups,
        "summary": {
            "total_lineage_targets": total_lineage_targets,
            "total_relationship_events": total_relationship_events,
            "active_support_relationships": active_support_relationships,
            "inactive_removed_relationships": inactive_relationships,
            "targets_with_lineage": targets_with_lineage,
            "targets_without_lineage": max(total_lineage_targets - targets_with_lineage, 0),
        },
    }


def _stage16e_lineage_event_label(event: dict[str, Any]) -> str:
    created_by = event.get("created_by") or "unknown"
    created_at = event.get("created_at") or "Not recorded"
    label = (
        f"{event.get('relationship_type') or 'relationship'} relationship created "
        f"by {created_by} at {created_at} — {event.get('state') or 'unknown'}"
    )
    if not bool(event.get("is_active")) and event.get("removed_at"):
        removed_by = event.get("removed_by") or "unknown"
        label += f" at {event.get('removed_at')} by {removed_by}"
    return label


def _render_stage16e_lineage_events(events: list[dict[str, Any]]) -> str:
    if not events:
        return '<p class="evidence-empty-state">No recorded evidence lineage events.</p>'
    items = "".join(
        "<li>"
        f"{escape(_stage16e_lineage_event_label(event))}"
        f" — Attachment {escape(str(event.get('attachment_id') or '—'))}: "
        f"{escape(str(event.get('attachment_title') or 'Untitled attachment'))}"
        "</li>"
        for event in events
    )
    return f"<ol>{items}</ol>"


def _render_stage16e_target_lineage(
    target_type: str,
    targets: list[dict[str, Any]],
) -> str:
    if not targets:
        return (
            f"<h3>{escape(_target_type_display_label(target_type))} Lineage</h3>"
            '<p class="evidence-empty-state">No targets available.</p>'
        )

    cards = []
    for target in targets:
        active_titles = _stage16d_traceability_value_list(
            target["active_supporting_attachment_titles"],
            "No active supporting attachments.",
        )
        rows = (
            ("Total relationship events", target["total_relationship_events"]),
            ("Active support relationships", target["active_support_count"]),
            (
                "Inactive / removed relationships",
                target["inactive_relationship_count"],
            ),
            ("First support created at", target["first_support_created_at"]),
            ("Latest support created at", target["latest_support_created_at"]),
            ("Active supporting attachments", active_titles),
            ("Current sufficiency", target["sufficiency"]),
            ("Current completeness", target["completeness"]),
            ("Current confidence", target["confidence"]),
        )
        table_rows = "".join(
            "<tr>"
            f"<td>{escape(str(label))}</td>"
            f"<td>{escape(str(value))}</td>"
            "</tr>"
            for label, value in rows
        )
        cards.append(
            '<article class="stage16e-target-lineage">'
            f"<h4>{escape(str(target['target_label']))}</h4>"
            f"<table><tbody>{table_rows}</tbody></table>"
            "<h5>Lineage Events</h5>"
            f"{_render_stage16e_lineage_events(target['events'])}"
            "</article>"
        )
    return (
        f"<h3>{escape(_target_type_display_label(target_type))} Lineage</h3>"
        f"{''.join(cards)}"
    )


def _render_stage16e_evidence_lineage(
    evidence_groups: dict[str, list[dict[str, Any]]],
) -> str:
    lineage = _record_stage16e_evidence_lineage(evidence_groups)
    summary = lineage["summary"]
    summary_rows = (
        ("Total Lineage Targets", summary["total_lineage_targets"]),
        ("Total Relationship Events", summary["total_relationship_events"]),
        ("Active Support Relationships", summary["active_support_relationships"]),
        (
            "Inactive / Removed Relationships",
            summary["inactive_removed_relationships"],
        ),
        ("Targets With Lineage", summary["targets_with_lineage"]),
        ("Targets Without Lineage", summary["targets_without_lineage"]),
    )
    table_rows = "".join(
        "<tr>"
        f"<td>{escape(str(label))}</td>"
        f"<td>{escape(str(value))}</td>"
        "</tr>"
        for label, value in summary_rows
    )
    sections = "".join(
        _render_stage16e_target_lineage(
            target_type,
            lineage["groups"][target_type],
        )
        for target_type in ("condition", "signal", "finding", "record")
    )
    return f"""
      <section class="management-section stage16e-evidence-lineage">
        <h2>Evidence Lineage</h2>
        <p class="notice">
          Evidence lineage is derived deterministically from existing attachment
          relationship history, safe attachment metadata, sufficiency,
          completeness, and confidence outputs only.
        </p>
        <h3>Evidence Lineage Summary</h3>
        <table class="stage16e-lineage-summary">
          <tbody>{table_rows}</tbody>
        </table>
        <section class="stage16e-target-lineage-list">
          {sections}
        </section>
      </section>"""


def _record_stage16f_evidence_provenance(
    evidence_groups: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    attachments_by_id: dict[Any, dict[str, Any]] = {}

    for target_type in ("condition", "signal", "finding", "record"):
        for target in evidence_groups.get(target_type) or []:
            attachment_lookup = {
                attachment.get("attachment_id"): attachment
                for attachment in target.get("attachments") or []
            }
            for trace in _stage16d_support_relationship_traces(target):
                attachment_id = trace.get("attachment_id")
                if attachment_id in (None, ""):
                    continue
                attachment = attachments_by_id.setdefault(
                    attachment_id,
                    {
                        "attachment_id": attachment_id,
                        "attachment_title": trace.get("attachment_title")
                        or "Untitled attachment",
                        "source_label": None,
                        "created_at": None,
                        "uploaded_at": None,
                        "current_status": None,
                        "active_relationship_count": 0,
                        "supported_targets": [],
                        "_supported_target_keys": set(),
                        "relationship_provenance": [],
                    },
                )
                metadata = attachment_lookup.get(attachment_id) or {}
                attachment["source_label"] = (
                    attachment.get("source_label") or metadata.get("source_label")
                )
                attachment["created_at"] = (
                    attachment.get("created_at") or metadata.get("document_date")
                )
                attachment["uploaded_at"] = (
                    attachment.get("uploaded_at") or metadata.get("uploaded_at")
                )
                attachment["current_status"] = (
                    attachment.get("current_status")
                    or metadata.get("lifecycle_state")
                    or "active"
                )
                attachment["active_relationship_count"] += 1
                supported_target_key = (
                    str(trace.get("target_type") or ""),
                    str(trace.get("target_key") or ""),
                )
                if supported_target_key not in attachment["_supported_target_keys"]:
                    attachment["_supported_target_keys"].add(supported_target_key)
                    attachment["supported_targets"].append(
                        trace.get("target_label")
                        or _guided_target_display_label(trace.get("target_key") or "")
                    )
                attachment["relationship_provenance"].append(
                    {
                        "relationship_created_at": trace.get("created_at")
                        or "Not recorded",
                        "relationship_type": trace.get("relationship_type")
                        or "supports",
                        "current_status": "active",
                    }
                )

    provenance_records = []
    for attachment in sorted(
        attachments_by_id.values(),
        key=lambda item: str(item.get("attachment_id") or ""),
    ):
        attachment.pop("_supported_target_keys", None)
        attachment["supported_target_count"] = len(attachment["supported_targets"])
        has_provenance = bool(
            attachment.get("source_label")
            or attachment.get("created_at")
            or attachment.get("uploaded_at")
        )
        attachment["has_provenance"] = has_provenance
        provenance_records.append(attachment)

    return {
        "attachments": provenance_records,
        "summary": {
            "total_attachments_referenced": len(provenance_records),
            "total_active_support_relationships": sum(
                int(attachment["active_relationship_count"])
                for attachment in provenance_records
            ),
            "total_provenance_records_available": sum(
                1 for attachment in provenance_records if attachment["has_provenance"]
            ),
            "attachments_with_provenance": sum(
                1 for attachment in provenance_records if attachment["has_provenance"]
            ),
            "attachments_missing_provenance": sum(
                1 for attachment in provenance_records if not attachment["has_provenance"]
            ),
        },
    }


def _render_stage16f_supported_targets(targets: list[str]) -> str:
    if not targets:
        return '<p class="evidence-empty-state">No active supported targets.</p>'
    items = "".join(f"<li>{escape(str(target))}</li>" for target in targets)
    return f"<ul>{items}</ul>"


def _render_stage16f_relationship_provenance(
    relationships: list[dict[str, Any]],
) -> str:
    if not relationships:
        return '<p class="evidence-empty-state">No active relationship provenance.</p>'
    rows = "".join(
        "<tr>"
        f"<td>{escape(str(relationship['relationship_created_at']))}</td>"
        f"<td>{escape(str(relationship['relationship_type']))}</td>"
        f"<td>{escape(str(relationship['current_status']))}</td>"
        "</tr>"
        for relationship in relationships
    )
    return f"""
        <table class="stage16f-relationship-provenance">
          <thead>
            <tr>
              <th>Relationship Created At</th>
              <th>Relationship Type</th>
              <th>Current Status</th>
            </tr>
          </thead>
          <tbody>{rows}</tbody>
        </table>"""


def _render_stage16f_attachment_provenance(
    attachment: dict[str, Any],
) -> str:
    rows = (
        ("Attachment ID", attachment.get("attachment_id")),
        ("Attachment Title", attachment.get("attachment_title")),
        ("Source Label", attachment.get("source_label") or "Not recorded"),
        ("Created At", attachment.get("created_at") or "Not recorded"),
        ("Uploaded At", attachment.get("uploaded_at") or "Not recorded"),
        ("Current Status", attachment.get("current_status") or "Not recorded"),
        ("Active Relationships", attachment.get("active_relationship_count")),
        ("Supported Targets", attachment.get("supported_target_count")),
    )
    table_rows = "".join(
        "<tr>"
        f"<td>{escape(str(label))}</td>"
        f"<td>{escape(str(value))}</td>"
        "</tr>"
        for label, value in rows
    )
    return f"""
        <article class="stage16f-attachment-provenance">
          <h3>{escape(str(attachment.get('attachment_title') or 'Untitled attachment'))}</h3>
          <table><tbody>{table_rows}</tbody></table>
          <h4>Supported Targets</h4>
          {_render_stage16f_supported_targets(attachment['supported_targets'])}
          <h4>Relationship Provenance</h4>
          {_render_stage16f_relationship_provenance(attachment['relationship_provenance'])}
        </article>"""


def _render_stage16f_evidence_provenance(
    evidence_groups: dict[str, list[dict[str, Any]]],
) -> str:
    provenance = _record_stage16f_evidence_provenance(evidence_groups)
    summary = provenance["summary"]
    summary_rows = (
        ("Total Attachments Referenced", summary["total_attachments_referenced"]),
        (
            "Total Active Support Relationships",
            summary["total_active_support_relationships"],
        ),
        (
            "Total Provenance Records Available",
            summary["total_provenance_records_available"],
        ),
        ("Attachments With Provenance", summary["attachments_with_provenance"]),
        ("Attachments Missing Provenance", summary["attachments_missing_provenance"]),
    )
    table_rows = "".join(
        "<tr>"
        f"<td>{escape(str(label))}</td>"
        f"<td>{escape(str(value))}</td>"
        "</tr>"
        for label, value in summary_rows
    )
    if provenance["attachments"]:
        attachment_sections = "".join(
            _render_stage16f_attachment_provenance(attachment)
            for attachment in provenance["attachments"]
        )
    else:
        attachment_sections = (
            '<p class="evidence-empty-state">No active evidence provenance records.</p>'
        )
    return f"""
      <section class="management-section stage16f-evidence-provenance">
        <h2>Evidence Provenance</h2>
        <p class="notice">
          Evidence provenance is derived deterministically from existing
          attachment metadata and active supports relationship records only.
        </p>
        <h3>Provenance Summary</h3>
        <table class="stage16f-provenance-summary">
          <tbody>{table_rows}</tbody>
        </table>
        <section class="stage16f-attachment-provenance-list">
          {attachment_sections}
        </section>
      </section>"""


def _stage17a_output_value(record_outputs: dict[str, Any], key: str) -> str:
    value = record_outputs.get(key)
    if value in (None, ""):
        return "Not recorded"
    return str(value)


def _stage17a_dependent_outputs(
    record_outputs: dict[str, Any],
    *,
    include_finding: bool = True,
) -> list[str]:
    outputs = [
        _stage17a_output_value(record_outputs, "reference"),
        f"Trajectory: {_stage17a_output_value(record_outputs, 'trajectory')}",
    ]
    if include_finding:
        outputs.append(f"Finding: {_stage17a_output_value(record_outputs, 'finding')}")
    return outputs


def _record_stage17a_record_dependency(
    evidence_groups: dict[str, list[dict[str, Any]]],
    record_outputs: dict[str, Any],
) -> dict[str, Any]:
    sufficiency = _record_stage15d_evidence_sufficiency(evidence_groups)
    completeness = _record_stage15e_evidence_completeness(evidence_groups)
    confidence = _record_stage16c_evidence_confidence(evidence_groups)
    groups: dict[str, list[dict[str, Any]]] = {}
    total_dependencies = 0
    supported_dependencies = 0

    for target_type in ("condition", "signal", "finding", "record"):
        rows = []
        for index, target in enumerate(evidence_groups.get(target_type) or []):
            active_supports = _stage15d_support_relationship_count(target)
            total_dependencies += 1
            if active_supports > 0:
                supported_dependencies += 1
            rows.append(
                {
                    "target_label": target.get("target_label")
                    or target.get("target_key")
                    or "",
                    "active_supports": active_supports,
                    "sufficiency": sufficiency["groups"][target_type]["targets"][
                        index
                    ]["sufficiency"],
                    "completeness": completeness["groups"][target_type]["targets"][
                        index
                    ]["completeness"],
                    "confidence": confidence["groups"][target_type]["targets"][index][
                        "confidence"
                    ],
                    "dependent_outputs": _stage17a_dependent_outputs(
                        record_outputs,
                        include_finding=(target_type != "finding"),
                    ),
                }
            )
        groups[target_type] = rows

    record_outputs_display = [
        _stage17a_output_value(record_outputs, "reference"),
        f"Trajectory: {_stage17a_output_value(record_outputs, 'trajectory')}",
        f"Finding: {_stage17a_output_value(record_outputs, 'finding')}",
    ]
    if _stage17a_output_value(record_outputs, "system_state") != "Not recorded":
        record_outputs_display.append(
            f"System state: {_stage17a_output_value(record_outputs, 'system_state')}"
        )

    return {
        "groups": groups,
        "summary": {
            "total_conditions": len(groups["condition"]),
            "total_signals": len(groups["signal"]),
            "total_findings": len(groups["finding"]),
            "total_record_outputs": len(record_outputs_display),
            "total_dependency_relationships": total_dependencies,
            "evidence_supported_dependencies": supported_dependencies,
            "unsupported_dependencies": max(total_dependencies - supported_dependencies, 0),
        },
        "record": {
            "reference": _stage17a_output_value(record_outputs, "reference"),
            "dependent_conditions": len(groups["condition"]),
            "dependent_signals": len(groups["signal"]),
            "dependent_findings": len(groups["finding"]),
            "current_trajectory": _stage17a_output_value(record_outputs, "trajectory"),
            "current_finding": _stage17a_output_value(record_outputs, "finding"),
            "record_sufficiency": (
                groups["record"][0]["sufficiency"] if groups["record"] else "Unsupported"
            ),
            "record_completeness": (
                groups["record"][0]["completeness"] if groups["record"] else "Incomplete"
            ),
            "record_confidence": (
                groups["record"][0]["confidence"] if groups["record"] else "Low Confidence"
            ),
            "record_active_supports": (
                groups["record"][0]["active_supports"] if groups["record"] else 0
            ),
        },
    }


def _render_stage17a_dependency_outputs(outputs: list[str]) -> str:
    items = "".join(f"<li>{escape(str(output))}</li>" for output in outputs)
    return f"<ul>{items}</ul>"


def _render_stage17a_target_dependencies(
    title: str,
    target_label: str,
    targets: list[dict[str, Any]],
) -> str:
    if not targets:
        return (
            f"<h3>{escape(title)}</h3>"
            '<p class="evidence-empty-state">No dependency targets available.</p>'
        )
    cards = []
    for target in targets:
        rows = (
            (target_label, target["target_label"]),
            ("Active Supports", target["active_supports"]),
            ("Sufficiency", target["sufficiency"]),
            ("Completeness", target["completeness"]),
            ("Confidence", target["confidence"]),
        )
        table_rows = "".join(
            "<tr>"
            f"<td>{escape(str(label))}</td>"
            f"<td>{escape(str(value))}</td>"
            "</tr>"
            for label, value in rows
        )
        cards.append(
            '<article class="stage17a-target-dependency">'
            f"<h4>{escape(str(target['target_label']))}</h4>"
            f"<table><tbody>{table_rows}</tbody></table>"
            "<h5>Dependent Outputs</h5>"
            f"{_render_stage17a_dependency_outputs(target['dependent_outputs'])}"
            "</article>"
        )
    return f"<h3>{escape(title)}</h3>{''.join(cards)}"


def _render_stage17a_record_dependency(
    dependency: dict[str, Any],
) -> str:
    record = dependency["record"]
    rows = (
        ("Record Reference", record["reference"]),
        ("Dependent Conditions", record["dependent_conditions"]),
        ("Dependent Signals", record["dependent_signals"]),
        ("Dependent Findings", record["dependent_findings"]),
        ("Current Trajectory", record["current_trajectory"]),
        ("Current Finding", record["current_finding"]),
        ("Record Sufficiency", record["record_sufficiency"]),
        ("Record Completeness", record["record_completeness"]),
        ("Record Confidence", record["record_confidence"]),
        ("Record Active Supports", record["record_active_supports"]),
    )
    table_rows = "".join(
        "<tr>"
        f"<td>{escape(str(label))}</td>"
        f"<td>{escape(str(value))}</td>"
        "</tr>"
        for label, value in rows
    )
    return f"""
        <section class="stage17a-record-dependencies">
          <h3>Record Dependencies</h3>
          <table><tbody>{table_rows}</tbody></table>
        </section>"""


def _render_stage17a_record_dependency_section(
    evidence_groups: dict[str, list[dict[str, Any]]],
    record_outputs: dict[str, Any],
) -> str:
    dependency = _record_stage17a_record_dependency(evidence_groups, record_outputs)
    summary = dependency["summary"]
    summary_rows = (
        ("Total Conditions", summary["total_conditions"]),
        ("Total Signals", summary["total_signals"]),
        ("Total Findings", summary["total_findings"]),
        ("Total Record Outputs", summary["total_record_outputs"]),
        ("Total Dependency Relationships", summary["total_dependency_relationships"]),
        (
            "Evidence-Supported Dependencies",
            summary["evidence_supported_dependencies"],
        ),
        ("Unsupported Dependencies", summary["unsupported_dependencies"]),
    )
    table_rows = "".join(
        "<tr>"
        f"<td>{escape(str(label))}</td>"
        f"<td>{escape(str(value))}</td>"
        "</tr>"
        for label, value in summary_rows
    )
    return f"""
      <section class="management-section stage17a-record-dependency">
        <h2>Record Dependency</h2>
        <p class="notice">
          Record dependency is derived deterministically from existing record
          structure, visible record outputs, and existing evidence target states
          only.
        </p>
        <h3>Dependency Summary</h3>
        <table class="stage17a-dependency-summary">
          <tbody>{table_rows}</tbody>
        </table>
        {_render_stage17a_target_dependencies(
            "Condition Dependencies",
            "Condition",
            dependency["groups"]["condition"],
        )}
        {_render_stage17a_target_dependencies(
            "Signal Dependencies",
            "Signal",
            dependency["groups"]["signal"],
        )}
        {_render_stage17a_target_dependencies(
            "Finding Dependencies",
            "Finding",
            dependency["groups"]["finding"],
        )}
        {_render_stage17a_record_dependency(dependency)}
      </section>"""


def _stage17b_impact_classification(sufficiency: str) -> str:
    if sufficiency in {"Sufficient", "Strong"}:
        return "Evidence-Supported Impact"
    return "Unsupported Impact"


def _record_stage17b_record_impact(
    evidence_groups: dict[str, list[dict[str, Any]]],
    record_outputs: dict[str, Any],
) -> dict[str, Any]:
    dependency = _record_stage17a_record_dependency(evidence_groups, record_outputs)
    groups: dict[str, list[dict[str, Any]]] = {}
    impacted_outputs: set[str] = set()
    supported_impacts = 0
    unsupported_impacts = 0

    for target_type in ("condition", "signal", "finding"):
        rows = []
        for target in dependency["groups"][target_type]:
            impact_classification = _stage17b_impact_classification(
                target["sufficiency"]
            )
            if impact_classification == "Evidence-Supported Impact":
                supported_impacts += 1
            else:
                unsupported_impacts += 1
            impacted_outputs.update(str(output) for output in target["dependent_outputs"])
            rows.append(
                {
                    "target_label": target["target_label"],
                    "active_supports": target["active_supports"],
                    "sufficiency": target["sufficiency"],
                    "completeness": target["completeness"],
                    "confidence": target["confidence"],
                    "impact_classification": impact_classification,
                    "impacted_outputs": target["dependent_outputs"],
                }
            )
        groups[target_type] = rows

    return {
        "groups": groups,
        "summary": {
            "total_impacted_outputs": len(impacted_outputs),
            "total_conditions_affecting_outputs": len(groups["condition"]),
            "total_signals_affecting_outputs": len(groups["signal"]),
            "total_findings_affecting_outputs": len(groups["finding"]),
            "evidence_supported_impacts": supported_impacts,
            "unsupported_impacts": unsupported_impacts,
        },
        "record": {
            "reference": dependency["record"]["reference"],
            "trajectory": dependency["record"]["current_trajectory"],
            "finding": dependency["record"]["current_finding"],
            "impacting_conditions": len(groups["condition"]),
            "impacting_signals": len(groups["signal"]),
            "impacting_findings": len(groups["finding"]),
            "evidence_supported_dependencies": supported_impacts,
            "unsupported_dependencies": unsupported_impacts,
        },
    }


def _render_stage17b_target_impacts(
    title: str,
    target_label: str,
    targets: list[dict[str, Any]],
) -> str:
    if not targets:
        return (
            f"<h3>{escape(title)}</h3>"
            '<p class="evidence-empty-state">No impact targets available.</p>'
        )
    cards = []
    for target in targets:
        rows = (
            (target_label, target["target_label"]),
            ("Active Supports", target["active_supports"]),
            ("Sufficiency", target["sufficiency"]),
            ("Completeness", target["completeness"]),
            ("Confidence", target["confidence"]),
            ("Impact Classification", target["impact_classification"]),
        )
        table_rows = "".join(
            "<tr>"
            f"<td>{escape(str(label))}</td>"
            f"<td>{escape(str(value))}</td>"
            "</tr>"
            for label, value in rows
        )
        cards.append(
            '<article class="stage17b-target-impact">'
            f"<h4>{escape(str(target['target_label']))}</h4>"
            f"<table><tbody>{table_rows}</tbody></table>"
            "<h5>Impacted Outputs</h5>"
            f"{_render_stage17a_dependency_outputs(target['impacted_outputs'])}"
            "</article>"
        )
    return f"<h3>{escape(title)}</h3>{''.join(cards)}"


def _render_stage17b_record_impact(impact: dict[str, Any]) -> str:
    record = impact["record"]
    rows = (
        ("Record Reference", record["reference"]),
        ("Trajectory", record["trajectory"]),
        ("Finding", record["finding"]),
        ("Impacting Conditions", record["impacting_conditions"]),
        ("Impacting Signals", record["impacting_signals"]),
        ("Impacting Findings", record["impacting_findings"]),
        (
            "Evidence-Supported Dependencies",
            record["evidence_supported_dependencies"],
        ),
        ("Unsupported Dependencies", record["unsupported_dependencies"]),
    )
    table_rows = "".join(
        "<tr>"
        f"<td>{escape(str(label))}</td>"
        f"<td>{escape(str(value))}</td>"
        "</tr>"
        for label, value in rows
    )
    return f"""
        <section class="stage17b-record-impact">
          <h3>Record Impact</h3>
          <table><tbody>{table_rows}</tbody></table>
        </section>"""


def _render_stage17b_record_impact_section(
    evidence_groups: dict[str, list[dict[str, Any]]],
    record_outputs: dict[str, Any],
) -> str:
    impact = _record_stage17b_record_impact(evidence_groups, record_outputs)
    summary = impact["summary"]
    summary_rows = (
        ("Total Impacted Outputs", summary["total_impacted_outputs"]),
        (
            "Total Conditions Affecting Outputs",
            summary["total_conditions_affecting_outputs"],
        ),
        (
            "Total Signals Affecting Outputs",
            summary["total_signals_affecting_outputs"],
        ),
        (
            "Total Findings Affecting Outputs",
            summary["total_findings_affecting_outputs"],
        ),
        ("Evidence-Supported Impacts", summary["evidence_supported_impacts"]),
        ("Unsupported Impacts", summary["unsupported_impacts"]),
    )
    table_rows = "".join(
        "<tr>"
        f"<td>{escape(str(label))}</td>"
        f"<td>{escape(str(value))}</td>"
        "</tr>"
        for label, value in summary_rows
    )
    return f"""
      <section class="management-section stage17b-record-impact">
        <h2>Record Impact</h2>
        <p class="notice">
          Record impact is derived deterministically from existing dependency
          mappings, visible record outputs, and existing evidence target states
          only.
        </p>
        <h3>Impact Summary</h3>
        <table class="stage17b-impact-summary">
          <tbody>{table_rows}</tbody>
        </table>
        {_render_stage17b_target_impacts(
            "Condition Impact",
            "Condition",
            impact["groups"]["condition"],
        )}
        {_render_stage17b_target_impacts(
            "Signal Impact",
            "Signal",
            impact["groups"]["signal"],
        )}
        {_render_stage17b_target_impacts(
            "Finding Impact",
            "Finding",
            impact["groups"]["finding"],
        )}
        {_render_stage17b_record_impact(impact)}
      </section>"""


def _stage17c_stability_classification(
    confidence: str,
    completeness: str,
) -> str:
    if confidence in {"High Confidence", "Very High Confidence"} and completeness == "Complete":
        return "Stable"
    if confidence == "Limited Confidence":
        return "Limited Stability"
    return "Unstable"


def _record_stage17c_record_stability(
    evidence_groups: dict[str, list[dict[str, Any]]],
    record_outputs: dict[str, Any],
) -> dict[str, Any]:
    impact = _record_stage17b_record_impact(evidence_groups, record_outputs)
    groups: dict[str, list[dict[str, Any]]] = {}
    stable_targets = 0
    limited_targets = 0
    unstable_targets = 0
    evidence_supported_targets = 0
    unsupported_targets = 0

    for target_type in ("condition", "signal", "finding"):
        rows = []
        for target in impact["groups"][target_type]:
            stability = _stage17c_stability_classification(
                target["confidence"],
                target["completeness"],
            )
            if stability == "Stable":
                stable_targets += 1
            elif stability == "Limited Stability":
                limited_targets += 1
            else:
                unstable_targets += 1
            if target["impact_classification"] == "Evidence-Supported Impact":
                evidence_supported_targets += 1
            else:
                unsupported_targets += 1
            rows.append(
                {
                    "target_label": target["target_label"],
                    "active_supports": target["active_supports"],
                    "sufficiency": target["sufficiency"],
                    "completeness": target["completeness"],
                    "confidence": target["confidence"],
                    "stability_classification": stability,
                    "affected_outputs": target["impacted_outputs"],
                }
            )
        groups[target_type] = rows

    record_dependency = _record_stage17a_record_dependency(evidence_groups, record_outputs)
    record = record_dependency["record"]
    record_stability = _stage17c_stability_classification(
        record["record_confidence"],
        record["record_completeness"],
    )

    return {
        "groups": groups,
        "summary": {
            "total_stability_targets": (
                len(groups["condition"])
                + len(groups["signal"])
                + len(groups["finding"])
            ),
            "stable_targets": stable_targets,
            "limited_stability_targets": limited_targets,
            "unstable_targets": unstable_targets,
            "evidence_supported_stability_targets": evidence_supported_targets,
            "unsupported_stability_targets": unsupported_targets,
        },
        "record": {
            "reference": record["reference"],
            "trajectory": record["current_trajectory"],
            "finding": record["current_finding"],
            "supporting_conditions": record["dependent_conditions"],
            "supporting_signals": record["dependent_signals"],
            "supporting_findings": record["dependent_findings"],
            "record_confidence": record["record_confidence"],
            "record_stability_classification": record_stability,
        },
    }


def _render_stage17c_target_stability(
    title: str,
    target_label: str,
    targets: list[dict[str, Any]],
) -> str:
    if not targets:
        return (
            f"<h3>{escape(title)}</h3>"
            '<p class="evidence-empty-state">No stability targets available.</p>'
        )
    cards = []
    for target in targets:
        rows = (
            (target_label, target["target_label"]),
            ("Active Supports", target["active_supports"]),
            ("Sufficiency", target["sufficiency"]),
            ("Completeness", target["completeness"]),
            ("Confidence", target["confidence"]),
            ("Stability Classification", target["stability_classification"]),
        )
        table_rows = "".join(
            "<tr>"
            f"<td>{escape(str(label))}</td>"
            f"<td>{escape(str(value))}</td>"
            "</tr>"
            for label, value in rows
        )
        cards.append(
            '<article class="stage17c-target-stability">'
            f"<h4>{escape(str(target['target_label']))}</h4>"
            f"<table><tbody>{table_rows}</tbody></table>"
            "<h5>Affected Outputs</h5>"
            f"{_render_stage17a_dependency_outputs(target['affected_outputs'])}"
            "</article>"
        )
    return f"<h3>{escape(title)}</h3>{''.join(cards)}"


def _render_stage17c_record_stability(stability: dict[str, Any]) -> str:
    record = stability["record"]
    rows = (
        ("Record Reference", record["reference"]),
        ("Trajectory", record["trajectory"]),
        ("Finding", record["finding"]),
        ("Supporting Conditions", record["supporting_conditions"]),
        ("Supporting Signals", record["supporting_signals"]),
        ("Supporting Findings", record["supporting_findings"]),
        ("Record Confidence", record["record_confidence"]),
        (
            "Record Stability Classification",
            record["record_stability_classification"],
        ),
    )
    table_rows = "".join(
        "<tr>"
        f"<td>{escape(str(label))}</td>"
        f"<td>{escape(str(value))}</td>"
        "</tr>"
        for label, value in rows
    )
    return f"""
        <section class="stage17c-record-stability">
          <h3>Record Stability</h3>
          <table><tbody>{table_rows}</tbody></table>
        </section>"""


def _render_stage17c_record_stability_section(
    evidence_groups: dict[str, list[dict[str, Any]]],
    record_outputs: dict[str, Any],
) -> str:
    stability = _record_stage17c_record_stability(evidence_groups, record_outputs)
    summary = stability["summary"]
    summary_rows = (
        ("Total Stability Targets", summary["total_stability_targets"]),
        ("Stable Targets", summary["stable_targets"]),
        ("Limited Stability Targets", summary["limited_stability_targets"]),
        ("Unstable Targets", summary["unstable_targets"]),
        (
            "Evidence-Supported Stability Targets",
            summary["evidence_supported_stability_targets"],
        ),
        ("Unsupported Stability Targets", summary["unsupported_stability_targets"]),
    )
    table_rows = "".join(
        "<tr>"
        f"<td>{escape(str(label))}</td>"
        f"<td>{escape(str(value))}</td>"
        "</tr>"
        for label, value in summary_rows
    )
    return f"""
      <section class="management-section stage17c-record-stability">
        <h2>Record Stability</h2>
        <p class="notice">
          Record stability is derived deterministically from existing
          dependency outputs, impact outputs, sufficiency, completeness,
          confidence, and support states only.
        </p>
        <h3>Stability Summary</h3>
        <table class="stage17c-stability-summary">
          <tbody>{table_rows}</tbody>
        </table>
        {_render_stage17c_target_stability(
            "Condition Stability",
            "Condition",
            stability["groups"]["condition"],
        )}
        {_render_stage17c_target_stability(
            "Signal Stability",
            "Signal",
            stability["groups"]["signal"],
        )}
        {_render_stage17c_target_stability(
            "Finding Stability",
            "Finding",
            stability["groups"]["finding"],
        )}
        {_render_stage17c_record_stability(stability)}
      </section>"""


def _stage17d_reproducibility_classification(
    sufficiency: str,
    completeness: str,
    confidence: str,
    stability: str,
) -> str:
    if (
        sufficiency in {"Sufficient", "Strong"}
        and completeness == "Complete"
        and confidence != "Low Confidence"
        and stability == "Stable"
    ):
        return "Reproducible"
    if (
        sufficiency == "Partial"
        and confidence == "Limited Confidence"
        and stability == "Limited Stability"
    ):
        return "Limited Reproducibility"
    return "Non-Reproducible"


def _record_stage17d_record_reproducibility(
    evidence_groups: dict[str, list[dict[str, Any]]],
    record_outputs: dict[str, Any],
) -> dict[str, Any]:
    stability = _record_stage17c_record_stability(evidence_groups, record_outputs)
    dependency = _record_stage17a_record_dependency(evidence_groups, record_outputs)
    groups: dict[str, list[dict[str, Any]]] = {}
    reproducible_targets = 0
    limited_targets = 0
    non_reproducible_targets = 0
    evidence_supported_targets = 0
    unsupported_targets = 0

    for target_type in ("condition", "signal", "finding"):
        rows = []
        for target in stability["groups"][target_type]:
            reproducibility = _stage17d_reproducibility_classification(
                target["sufficiency"],
                target["completeness"],
                target["confidence"],
                target["stability_classification"],
            )
            if reproducibility == "Reproducible":
                reproducible_targets += 1
            elif reproducibility == "Limited Reproducibility":
                limited_targets += 1
            else:
                non_reproducible_targets += 1
            if target["sufficiency"] in {"Sufficient", "Strong"}:
                evidence_supported_targets += 1
            else:
                unsupported_targets += 1
            rows.append(
                {
                    "target_label": target["target_label"],
                    "active_supports": target["active_supports"],
                    "sufficiency": target["sufficiency"],
                    "completeness": target["completeness"],
                    "confidence": target["confidence"],
                    "stability": target["stability_classification"],
                    "reproducibility_classification": reproducibility,
                    "affected_outputs": target["affected_outputs"],
                }
            )
        groups[target_type] = rows

    record = dependency["record"]
    record_stability = stability["record"]["record_stability_classification"]
    record_reproducibility = _stage17d_reproducibility_classification(
        record["record_sufficiency"],
        record["record_completeness"],
        record["record_confidence"],
        record_stability,
    )

    return {
        "groups": groups,
        "summary": {
            "total_reproducibility_targets": (
                len(groups["condition"])
                + len(groups["signal"])
                + len(groups["finding"])
            ),
            "reproducible_targets": reproducible_targets,
            "limited_reproducibility_targets": limited_targets,
            "non_reproducible_targets": non_reproducible_targets,
            "evidence_supported_targets": evidence_supported_targets,
            "unsupported_targets": unsupported_targets,
        },
        "record": {
            "reference": record["reference"],
            "trajectory": record["current_trajectory"],
            "finding": record["current_finding"],
            "supporting_conditions": record["dependent_conditions"],
            "supporting_signals": record["dependent_signals"],
            "supporting_findings": record["dependent_findings"],
            "record_confidence": record["record_confidence"],
            "record_stability": record_stability,
            "record_reproducibility_classification": record_reproducibility,
        },
    }


def _render_stage17d_target_reproducibility(
    title: str,
    target_label: str,
    targets: list[dict[str, Any]],
) -> str:
    if not targets:
        return (
            f"<h3>{escape(title)}</h3>"
            '<p class="evidence-empty-state">No reproducibility targets available.</p>'
        )
    cards = []
    for target in targets:
        rows = (
            (target_label, target["target_label"]),
            ("Active Supports", target["active_supports"]),
            ("Sufficiency", target["sufficiency"]),
            ("Completeness", target["completeness"]),
            ("Confidence", target["confidence"]),
            ("Stability", target["stability"]),
            (
                "Reproducibility Classification",
                target["reproducibility_classification"],
            ),
        )
        table_rows = "".join(
            "<tr>"
            f"<td>{escape(str(label))}</td>"
            f"<td>{escape(str(value))}</td>"
            "</tr>"
            for label, value in rows
        )
        cards.append(
            '<article class="stage17d-target-reproducibility">'
            f"<h4>{escape(str(target['target_label']))}</h4>"
            f"<table><tbody>{table_rows}</tbody></table>"
            "<h5>Affected Outputs</h5>"
            f"{_render_stage17a_dependency_outputs(target['affected_outputs'])}"
            "</article>"
        )
    return f"<h3>{escape(title)}</h3>{''.join(cards)}"


def _render_stage17d_record_reproducibility(
    reproducibility: dict[str, Any],
) -> str:
    record = reproducibility["record"]
    rows = (
        ("Record Reference", record["reference"]),
        ("Trajectory", record["trajectory"]),
        ("Finding", record["finding"]),
        ("Supporting Conditions", record["supporting_conditions"]),
        ("Supporting Signals", record["supporting_signals"]),
        ("Supporting Findings", record["supporting_findings"]),
        ("Record Confidence", record["record_confidence"]),
        ("Record Stability", record["record_stability"]),
        (
            "Record Reproducibility Classification",
            record["record_reproducibility_classification"],
        ),
    )
    table_rows = "".join(
        "<tr>"
        f"<td>{escape(str(label))}</td>"
        f"<td>{escape(str(value))}</td>"
        "</tr>"
        for label, value in rows
    )
    return f"""
        <section class="stage17d-record-reproducibility">
          <h3>Record Reproducibility</h3>
          <table><tbody>{table_rows}</tbody></table>
        </section>"""


def _render_stage17d_record_reproducibility_section(
    evidence_groups: dict[str, list[dict[str, Any]]],
    record_outputs: dict[str, Any],
) -> str:
    reproducibility = _record_stage17d_record_reproducibility(
        evidence_groups,
        record_outputs,
    )
    summary = reproducibility["summary"]
    summary_rows = (
        ("Total Reproducibility Targets", summary["total_reproducibility_targets"]),
        ("Reproducible Targets", summary["reproducible_targets"]),
        (
            "Limited Reproducibility Targets",
            summary["limited_reproducibility_targets"],
        ),
        ("Non-Reproducible Targets", summary["non_reproducible_targets"]),
        ("Evidence-Supported Targets", summary["evidence_supported_targets"]),
        ("Unsupported Targets", summary["unsupported_targets"]),
    )
    table_rows = "".join(
        "<tr>"
        f"<td>{escape(str(label))}</td>"
        f"<td>{escape(str(value))}</td>"
        "</tr>"
        for label, value in summary_rows
    )
    return f"""
      <section class="management-section stage17d-record-reproducibility">
        <h2>Record Reproducibility</h2>
        <p class="notice">
          Record reproducibility is derived deterministically from existing
          record structure, evidence relationships, governance outputs,
          dependency outputs, impact outputs, and stability outputs only.
        </p>
        <h3>Reproducibility Summary</h3>
        <table class="stage17d-reproducibility-summary">
          <tbody>{table_rows}</tbody>
        </table>
        {_render_stage17d_target_reproducibility(
            "Condition Reproducibility",
            "Condition",
            reproducibility["groups"]["condition"],
        )}
        {_render_stage17d_target_reproducibility(
            "Signal Reproducibility",
            "Signal",
            reproducibility["groups"]["signal"],
        )}
        {_render_stage17d_target_reproducibility(
            "Finding Reproducibility",
            "Finding",
            reproducibility["groups"]["finding"],
        )}
        {_render_stage17d_record_reproducibility(reproducibility)}
      </section>"""


def _stage17e_integrity_classification(
    active_supports: int,
    sufficiency: str,
    completeness: str,
    confidence: str,
    stability: str,
    reproducibility: str,
) -> str:
    if (
        active_supports == 0
        or sufficiency == "Unsupported"
        or confidence == "Low Confidence"
        or stability == "Unstable"
        or reproducibility == "Non-Reproducible"
    ):
        return "Compromised Integrity"
    if (
        active_supports > 0
        and (
            sufficiency == "Partial"
            or completeness == "Incomplete"
            or confidence == "Limited Confidence"
            or stability == "Limited Stability"
            or reproducibility == "Limited Reproducibility"
        )
    ):
        return "Limited Integrity"
    return "High Integrity"


def _record_stage17e_record_integrity(
    evidence_groups: dict[str, list[dict[str, Any]]],
    record_outputs: dict[str, Any],
) -> dict[str, Any]:
    reproducibility = _record_stage17d_record_reproducibility(
        evidence_groups,
        record_outputs,
    )
    dependency = _record_stage17a_record_dependency(evidence_groups, record_outputs)
    groups: dict[str, list[dict[str, Any]]] = {}
    high_targets = 0
    limited_targets = 0
    compromised_targets = 0
    evidence_supported_targets = 0
    unsupported_targets = 0

    for target_type in ("condition", "signal", "finding"):
        rows = []
        for target in reproducibility["groups"][target_type]:
            integrity = _stage17e_integrity_classification(
                target["active_supports"],
                target["sufficiency"],
                target["completeness"],
                target["confidence"],
                target["stability"],
                target["reproducibility_classification"],
            )
            if integrity == "High Integrity":
                high_targets += 1
            elif integrity == "Limited Integrity":
                limited_targets += 1
            else:
                compromised_targets += 1
            if target["active_supports"] > 0:
                evidence_supported_targets += 1
            else:
                unsupported_targets += 1
            rows.append(
                {
                    "target_label": target["target_label"],
                    "active_supports": target["active_supports"],
                    "sufficiency": target["sufficiency"],
                    "completeness": target["completeness"],
                    "confidence": target["confidence"],
                    "stability": target["stability"],
                    "reproducibility": target["reproducibility_classification"],
                    "integrity_classification": integrity,
                    "affected_outputs": target["affected_outputs"],
                }
            )
        groups[target_type] = rows

    record = dependency["record"]
    record_reproducibility = reproducibility["record"]
    record_integrity = _stage17e_integrity_classification(
        record["record_active_supports"],
        record["record_sufficiency"],
        record["record_completeness"],
        record["record_confidence"],
        record_reproducibility["record_stability"],
        record_reproducibility["record_reproducibility_classification"],
    )

    return {
        "groups": groups,
        "summary": {
            "total_integrity_targets": (
                len(groups["condition"])
                + len(groups["signal"])
                + len(groups["finding"])
            ),
            "high_integrity_targets": high_targets,
            "limited_integrity_targets": limited_targets,
            "compromised_integrity_targets": compromised_targets,
            "evidence_supported_integrity_targets": evidence_supported_targets,
            "unsupported_integrity_targets": unsupported_targets,
        },
        "record": {
            "reference": record["reference"],
            "trajectory": record["current_trajectory"],
            "finding": record["current_finding"],
            "supporting_conditions": record["dependent_conditions"],
            "supporting_signals": record["dependent_signals"],
            "supporting_findings": record["dependent_findings"],
            "record_confidence": record["record_confidence"],
            "record_stability": record_reproducibility["record_stability"],
            "record_reproducibility": record_reproducibility[
                "record_reproducibility_classification"
            ],
            "record_integrity_classification": record_integrity,
        },
    }


def _render_stage17e_target_integrity(
    title: str,
    target_label: str,
    targets: list[dict[str, Any]],
) -> str:
    if not targets:
        return (
            f"<h3>{escape(title)}</h3>"
            '<p class="evidence-empty-state">No integrity targets available.</p>'
        )
    cards = []
    for target in targets:
        rows = (
            (target_label, target["target_label"]),
            ("Active Supports", target["active_supports"]),
            ("Sufficiency", target["sufficiency"]),
            ("Completeness", target["completeness"]),
            ("Confidence", target["confidence"]),
            ("Stability", target["stability"]),
            ("Reproducibility", target["reproducibility"]),
            ("Integrity Classification", target["integrity_classification"]),
        )
        table_rows = "".join(
            "<tr>"
            f"<td>{escape(str(label))}</td>"
            f"<td>{escape(str(value))}</td>"
            "</tr>"
            for label, value in rows
        )
        cards.append(
            '<article class="stage17e-target-integrity">'
            f"<h4>{escape(str(target['target_label']))}</h4>"
            f"<table><tbody>{table_rows}</tbody></table>"
            "<h5>Affected Outputs</h5>"
            f"{_render_stage17a_dependency_outputs(target['affected_outputs'])}"
            "</article>"
        )
    return f"<h3>{escape(title)}</h3>{''.join(cards)}"


def _render_stage17e_record_integrity(integrity: dict[str, Any]) -> str:
    record = integrity["record"]
    rows = (
        ("Record Reference", record["reference"]),
        ("Trajectory", record["trajectory"]),
        ("Finding", record["finding"]),
        ("Supporting Conditions", record["supporting_conditions"]),
        ("Supporting Signals", record["supporting_signals"]),
        ("Supporting Findings", record["supporting_findings"]),
        ("Record Confidence", record["record_confidence"]),
        ("Record Stability", record["record_stability"]),
        ("Record Reproducibility", record["record_reproducibility"]),
        (
            "Record Integrity Classification",
            record["record_integrity_classification"],
        ),
    )
    table_rows = "".join(
        "<tr>"
        f"<td>{escape(str(label))}</td>"
        f"<td>{escape(str(value))}</td>"
        "</tr>"
        for label, value in rows
    )
    return f"""
        <section class="stage17e-record-integrity">
          <h3>Record Integrity</h3>
          <table><tbody>{table_rows}</tbody></table>
        </section>"""


def _render_stage17e_record_integrity_section(
    evidence_groups: dict[str, list[dict[str, Any]]],
    record_outputs: dict[str, Any],
) -> str:
    integrity = _record_stage17e_record_integrity(evidence_groups, record_outputs)
    summary = integrity["summary"]
    summary_rows = (
        ("Total Integrity Targets", summary["total_integrity_targets"]),
        ("High Integrity Targets", summary["high_integrity_targets"]),
        ("Limited Integrity Targets", summary["limited_integrity_targets"]),
        ("Compromised Integrity Targets", summary["compromised_integrity_targets"]),
        (
            "Evidence-Supported Integrity Targets",
            summary["evidence_supported_integrity_targets"],
        ),
        ("Unsupported Integrity Targets", summary["unsupported_integrity_targets"]),
    )
    table_rows = "".join(
        "<tr>"
        f"<td>{escape(str(label))}</td>"
        f"<td>{escape(str(value))}</td>"
        "</tr>"
        for label, value in summary_rows
    )
    return f"""
      <section class="management-section stage17e-record-integrity">
        <h2>Record Integrity</h2>
        <p class="notice">
          Record integrity is derived deterministically from existing evidence
          support counts, dependency outputs, impact outputs, stability outputs,
          reproducibility outputs, and record structure only.
        </p>
        <h3>Integrity Summary</h3>
        <table class="stage17e-integrity-summary">
          <tbody>{table_rows}</tbody>
        </table>
        {_render_stage17e_target_integrity(
            "Condition Integrity",
            "Condition",
            integrity["groups"]["condition"],
        )}
        {_render_stage17e_target_integrity(
            "Signal Integrity",
            "Signal",
            integrity["groups"]["signal"],
        )}
        {_render_stage17e_target_integrity(
            "Finding Integrity",
            "Finding",
            integrity["groups"]["finding"],
        )}
        {_render_stage17e_record_integrity(integrity)}
      </section>"""


def _render_record_evidence_attachment(attachment: dict[str, Any]) -> str:
    rows = (
        ("Attachment ID", attachment.get("attachment_id")),
        ("Title", attachment.get("title")),
        ("Classification", attachment.get("classification")),
        ("Publication status", attachment.get("publication_status")),
        ("Visibility", attachment.get("visibility")),
        ("Redaction status", attachment.get("redaction_status")),
        ("Lifecycle state", attachment.get("lifecycle_state")),
        ("Document date", attachment.get("document_date")),
        ("SHA-256 hash", attachment.get("sha256_hash")),
    )
    relationship_html = _render_record_evidence_attachment_relationships(
        attachment.get("relationship_type_counts") or {}
    )
    table_rows = "".join(
        "<tr>"
        f"<td>{escape(label)}</td>"
        f"<td>{escape(str(value)) if value not in (None, '') else '—'}</td>"
        "</tr>"
        for label, value in rows
    )
    title = attachment.get("title") or "Untitled attachment"
    return f"""
            <li class="supporting-attachment">
              <h4>Attachment {escape(str(attachment.get("attachment_id")))} — {escape(str(title))}</h4>
              {relationship_html}
              <table>
                <tbody>{table_rows}</tbody>
              </table>
            </li>"""


def _render_record_evidence_attachment_relationships(
    counts: dict[str, int],
) -> str:
    return f"""
              <section class="attachment-relationship-detail">
                <h5>Relationships</h5>
                {_render_relationship_type_count_list(counts, include_single_counts=False)}
              </section>"""


def _render_progressive_disclosure_group(
    *,
    title: str,
    description: str,
    content: str,
    class_name: str,
) -> str:
    return f"""
    <details class="progressive-disclosure-group {escape(class_name)}">
      <summary>
        <span class="summary-title">{escape(title)}</span>
        <span class="summary-meta">{escape(description)}</span>
      </summary>
      <div class="progressive-disclosure-content">
        {content}
      </div>
    </details>"""


def _render_admin_section_group(
    *,
    title: str,
    description: str,
    content: str,
    class_name: str,
    open_by_default: bool = False,
) -> str:
    open_attr = " open" if open_by_default else ""
    return f"""
    <details class="admin-section-group {escape(class_name)}"{open_attr}>
      <summary class="admin-section-summary">
        <span class="summary-title">{escape(title)}</span>
        <span class="admin-section-hint">{escape(description)}</span>
      </summary>
      <div class="admin-section-body">
        {content}
      </div>
    </details>
    <section class="print-admin-section-body {escape(class_name)}-print" aria-hidden="true">
      <h2>{escape(title)}</h2>
      <p class="admin-section-hint">{escape(description)}</p>
      {content}
    </section>"""


def render_admin_record_evidence_page(
    *,
    reference: str,
    record_version: int,
    evidence_groups: dict[str, list[dict[str, Any]]],
    record_outputs: dict[str, Any],
) -> str:
    evidence_sections = _render_record_evidence_groups(evidence_groups)
    evidence_coverage = _render_record_evidence_coverage(evidence_groups)
    stage15d_evidence_sufficiency = _render_stage15d_evidence_sufficiency(
        evidence_groups
    )
    stage15e_evidence_completeness = _render_stage15e_evidence_completeness(
        evidence_groups
    )
    stage15f_evidence_requirements = _render_stage15f_evidence_requirements(
        evidence_groups
    )
    stage16a_evidence_standards = _render_stage16a_evidence_standards()
    stage16b_evidence_justification = _render_stage16b_evidence_justification(
        evidence_groups
    )
    stage16c_evidence_confidence = _render_stage16c_evidence_confidence(
        evidence_groups
    )
    stage16d_evidence_traceability = _render_stage16d_evidence_traceability(
        evidence_groups
    )
    stage16e_evidence_lineage = _render_stage16e_evidence_lineage(evidence_groups)
    stage16f_evidence_provenance = _render_stage16f_evidence_provenance(
        evidence_groups
    )
    stage17a_record_dependency = _render_stage17a_record_dependency_section(
        evidence_groups,
        record_outputs,
    )
    stage17b_record_impact = _render_stage17b_record_impact_section(
        evidence_groups,
        record_outputs,
    )
    stage17c_record_stability = _render_stage17c_record_stability_section(
        evidence_groups,
        record_outputs,
    )
    stage17d_record_reproducibility = _render_stage17d_record_reproducibility_section(
        evidence_groups,
        record_outputs,
    )
    stage17e_record_integrity = _render_stage17e_record_integrity_section(
        evidence_groups,
        record_outputs,
    )
    evidence_gap_summary = _render_record_evidence_gap_summary(evidence_groups)
    evidence_sufficiency = _render_record_evidence_sufficiency(evidence_groups)
    evidence_readiness = _render_record_evidence_readiness(evidence_groups)
    administrative_action = _render_administrative_action(evidence_groups)
    action_rationale = _render_action_rationale(evidence_groups)
    completion_requirements = _render_completion_requirements(evidence_groups)
    workflow_state = _render_workflow_state(evidence_groups)
    transition_conditions = _render_transition_conditions(evidence_groups)
    administrative_disposition = _render_administrative_disposition(
        evidence_groups
    )
    disposition_basis = _render_disposition_basis(evidence_groups)
    review_eligibility = _render_review_eligibility(evidence_groups)
    review_preconditions = _render_review_preconditions(evidence_groups)
    administrative_status_summary = _render_administrative_status_summary(
        evidence_groups
    )
    implementation_action = _render_implementation_action(evidence_groups)
    implementation_basis = _render_implementation_basis(evidence_groups)
    effective_state = _render_effective_state(evidence_groups)
    outcome_classification = _render_outcome_classification(evidence_groups)
    outcome_basis = _render_outcome_basis(evidence_groups)
    outcome_preconditions = _render_outcome_preconditions(evidence_groups)
    outcome_summary = _render_outcome_summary(evidence_groups)
    outcome_readiness = _render_outcome_readiness(evidence_groups)
    outcome_target = _render_outcome_target(evidence_groups)
    resolution_classification = _render_resolution_classification(
        evidence_groups
    )
    resolution_preconditions = _render_resolution_preconditions(
        evidence_groups
    )
    resolution_pathway = _render_resolution_pathway(evidence_groups)
    resolution_readiness = _render_resolution_readiness(evidence_groups)
    resolution_determination = _render_resolution_determination(
        evidence_groups
    )
    resolution_completion = _render_resolution_completion(evidence_groups)
    closure_classification = _render_closure_classification(evidence_groups)
    closure_preconditions = _render_closure_preconditions(evidence_groups)
    closure_pathway = _render_closure_pathway(evidence_groups)
    closure_readiness = _render_closure_readiness(evidence_groups)
    closure_determination = _render_closure_determination(evidence_groups)
    closure_completion = _render_closure_completion(evidence_groups)
    archive_classification = _render_archive_classification(evidence_groups)
    archive_preconditions = _render_archive_preconditions(evidence_groups)
    archive_pathway = _render_archive_pathway(evidence_groups)
    archive_readiness = _render_archive_readiness(evidence_groups)
    archive_determination = _render_archive_determination(evidence_groups)
    archive_completion = _render_archive_completion(evidence_groups)
    evidence_assessment = _render_progressive_disclosure_group(
        title="Evidence Assessment",
        description="Stage 7F evidence sufficiency and Stage 7G evidence readiness.",
        content=f"{evidence_sufficiency}{evidence_readiness}",
        class_name="evidence-assessment-group",
    )
    administrative_workflow = _render_progressive_disclosure_group(
        title="Administrative Workflow",
        description="Stage 8A through Stage 8E administrative workflow reasoning.",
        content=(
            f"{administrative_action}"
            f"{action_rationale}"
            f"{completion_requirements}"
            f"{workflow_state}"
            f"{transition_conditions}"
        ),
        class_name="administrative-workflow-group",
    )
    review_status = _render_progressive_disclosure_group(
        title="Review Status",
        description="Stage 9A through Stage 9D review classification and preconditions.",
        content=(
            f"{administrative_disposition}"
            f"{disposition_basis}"
            f"{review_eligibility}"
            f"{review_preconditions}"
        ),
        class_name="review-status-group",
    )
    implementation_path = _render_progressive_disclosure_group(
        title="Implementation Path",
        description="Stage 10A implementation action and Stage 10B implementation basis.",
        content=f"{implementation_action}{implementation_basis}",
        class_name="implementation-path-group",
    )
    outcome_detail = _render_progressive_disclosure_group(
        title="Outcome Detail",
        description="Stage 11B through Stage 11D outcome basis, preconditions, and summary.",
        content=f"{outcome_basis}{outcome_preconditions}{outcome_summary}",
        class_name="outcome-detail-group",
    )
    supporting_evidence = _render_progressive_disclosure_group(
        title="Supporting Evidence",
        description="Conditions, signals, findings, and record-level supporting evidence.",
        content=(
            '<section class="management-section record-evidence">'
            "<h2>Evidence by record target</h2>"
            f"{evidence_sections}"
            "</section>"
        ),
        class_name="supporting-evidence-group",
    )
    evidence_coverage_group = _render_admin_section_group(
        title="Evidence Coverage",
        description="Current evidence coverage and outstanding gap summary.",
        content=(
            f"{evidence_coverage}"
            f"{stage15d_evidence_sufficiency}"
            f"{stage15e_evidence_completeness}"
            f"{stage15f_evidence_requirements}"
            f"{stage16a_evidence_standards}"
            f"{stage16b_evidence_justification}"
            f"{stage16c_evidence_confidence}"
            f"{stage16d_evidence_traceability}"
            f"{stage16e_evidence_lineage}"
            f"{stage16f_evidence_provenance}"
            f"{stage17a_record_dependency}"
            f"{stage17b_record_impact}"
            f"{stage17c_record_stability}"
            f"{stage17d_record_reproducibility}"
            f"{stage17e_record_integrity}"
            f"{evidence_gap_summary}"
        ),
        class_name="evidence-coverage-admin-group",
        open_by_default=True,
    )
    administrative_workflow_group = _render_admin_section_group(
        title="Administrative Workflow",
        description="Expand to inspect deterministic administrative reasoning.",
        content=(
            f"{evidence_assessment}"
            f"{administrative_workflow}"
            f"{review_status}"
            f"{administrative_status_summary}"
            f"{implementation_path}"
            f"{effective_state}"
        ),
        class_name="administrative-workflow-admin-group",
    )
    outcome_analysis_group = _render_admin_section_group(
        title="Outcome Analysis — Stages 11A–11F",
        description="Expand to inspect deterministic outcome reasoning.",
        content=(
            f"{outcome_classification}"
            f"{outcome_detail}"
            f"{outcome_readiness}"
            f"{outcome_target}"
        ),
        class_name="outcome-analysis-admin-group",
    )
    resolution_analysis_group = _render_admin_section_group(
        title="Resolution Analysis — Stages 12A–12F",
        description="Expand to inspect deterministic resolution reasoning.",
        content=(
            f"{resolution_classification}"
            f"{resolution_preconditions}"
            f"{resolution_pathway}"
            f"{resolution_readiness}"
            f"{resolution_determination}"
            f"{resolution_completion}"
        ),
        class_name="resolution-analysis-admin-group",
    )
    closure_analysis_group = _render_admin_section_group(
        title="Closure Analysis — Stages 13A–13F",
        description="Expand to inspect deterministic closure reasoning.",
        content=(
            f"{closure_classification}"
            f"{closure_preconditions}"
            f"{closure_pathway}"
            f"{closure_readiness}"
            f"{closure_determination}"
            f"{closure_completion}"
        ),
        class_name="closure-analysis-admin-group",
    )
    archive_analysis_group = _render_admin_section_group(
        title="Archive Analysis — Stages 14A–14F",
        description="Current archive layer and deterministic archive reasoning.",
        content=(
            f"{archive_classification}"
            f"{archive_preconditions}"
            f"{archive_pathway}"
            f"{archive_readiness}"
            f"{archive_determination}"
            f"{archive_completion}"
        ),
        class_name="archive-analysis-admin-group",
        open_by_default=True,
    )
    supporting_evidence_group = _render_admin_section_group(
        title="Supporting Evidence",
        description="Expand to inspect linked evidence by record target.",
        content=supporting_evidence,
        class_name="supporting-evidence-admin-group",
    )
    attachments_url = f"/admin/records/{escape(reference)}/attachments"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Admin Record Evidence - {escape(reference)}</title>
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
    .progressive-disclosure-group {{
      border: 1px solid #d8d4ca;
      margin-top: 22px;
      background: #fff;
    }}
    .progressive-disclosure-group > summary {{
      padding: 14px;
      background: #f3f1eb;
      border-bottom: 1px solid #e5e1d8;
    }}
    .progressive-disclosure-content {{
      padding: 0 14px 16px;
    }}
    .admin-section-group {{
      border: 1px solid #cdc7ba;
      margin-top: 24px;
      background: #fff;
      break-inside: avoid;
    }}
    .admin-section-summary {{
      padding: 15px 16px;
      background: #eeeae0;
      border-bottom: 1px solid #d8d4ca;
    }}
    .admin-section-body {{
      padding: 0 16px 18px;
    }}
    .print-admin-section-body {{
      display: none;
    }}
    .admin-section-hint {{
      display: block;
      color: #555;
      font-size: 0.88rem;
      font-weight: 500;
    }}
    .admin-section-count {{
      color: #666;
      font-family: ui-monospace, monospace;
      font-size: 0.78rem;
      font-weight: 700;
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }}
    details {{
      break-inside: avoid;
      border: 1px solid #e5e1d8;
      margin-top: 12px;
      overflow: hidden;
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
    .summary-meta {{
      display: block;
    }}
    .summary-meta {{
      color: #555;
      font-size: 0.88rem;
      font-weight: 500;
    }}
    .supporting-attachment-list {{
      display: grid;
      gap: 10px;
      list-style: none;
      margin: 0;
      padding: 10px;
    }}
    .supporting-attachment {{
      border: 1px solid #e3ded4;
      background: #fff;
      padding: 10px;
    }}
    .supporting-attachment h4 {{
      margin: 0 0 8px;
    }}
    .relationship-trace {{
      margin: 10px;
      padding: 10px;
      border: 1px solid #e3ded4;
      background: #fff;
    }}
    .relationship-trace h4 {{
      margin: 0 0 8px;
    }}
    .relationship-trace-list {{
      display: grid;
      gap: 8px;
      list-style: none;
      margin: 0;
      padding: 0;
    }}
    .relationship-trace-entry {{
      padding: 8px;
      border: 1px solid #eee;
      background: #fbfaf7;
    }}
    .relationship-trace-path {{
      font-weight: 650;
      margin-bottom: 6px;
    }}
    .relationship-trace-fields {{
      display: grid;
      grid-template-columns: 160px 1fr;
      gap: 4px 10px;
      margin: 0 0 6px;
      font-size: 0.86rem;
    }}
    .relationship-trace-fields dt {{
      color: #666;
      font-family: ui-monospace, monospace;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }}
    .relationship-trace-fields dd {{
      margin: 0;
      word-break: break-word;
    }}
    .relationship-trace-attachment {{
      color: #555;
      font-size: 0.9rem;
    }}
    .outstanding-gap-list {{
      margin: 8px 0 0 20px;
      padding: 0;
    }}
    .outstanding-gap-list li {{
      margin: 4px 0;
    }}
    .action-rationale-list,
    .completion-requirements-list,
    .transition-conditions-list,
    .disposition-basis-list,
    .review-preconditions-list,
    .implementation-basis-list,
    .outcome-basis-list,
    .outcome-preconditions-list,
    .resolution-preconditions-list,
    .closure-preconditions-list {{
      margin: 8px 0 0 24px;
      padding: 0;
      line-height: 1.45;
    }}
    .action-rationale-list li,
    .completion-requirements-list li,
    .transition-conditions-list li,
    .disposition-basis-list li,
    .review-preconditions-list li,
    .implementation-basis-list li,
    .outcome-basis-list li,
    .outcome-preconditions-list li,
    .resolution-preconditions-list li,
    .closure-preconditions-list li {{
      margin: 5px 0;
    }}
    .evidence-empty-state {{
      margin: 10px;
      color: #666;
    }}
    .navigation-link {{
      display: inline-block;
      margin-top: 8px;
      color: #245d61;
      font-weight: 650;
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
    .stage7f-sufficiency-table .target-cell {{
      word-break: normal;
      overflow-wrap: break-word;
      line-height: 1.3;
    }}
    .stage7f-sufficiency-table .sufficiency-cell {{
      white-space: nowrap;
      word-break: normal;
      overflow-wrap: normal;
    }}
    .stage7f-sufficiency-table th:nth-child(1) {{ width: 22%; }}
    .stage7f-sufficiency-table th:nth-child(2) {{ width: 30%; }}
    .stage7f-sufficiency-table th:nth-child(3) {{ width: 16%; }}
    .stage7f-sufficiency-table th:nth-child(4) {{ width: 16%; }}
    .stage7f-sufficiency-table th:nth-child(5) {{ width: 16%; }}
    .readiness-badge {{
      display: inline-block;
      border: 1px solid #6f6a60;
      border-radius: 999px;
      padding: 3px 9px;
      background: #fbfaf7;
      color: #1f1f1f;
      font-family: ui-monospace, monospace;
      font-size: 0.78rem;
      font-weight: 700;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      print-color-adjust: exact;
      -webkit-print-color-adjust: exact;
    }}
    .readiness-ready {{
      border-color: #2f6d4f;
      background: #eef7f1;
    }}
    .readiness-partially-ready {{
      border-color: #6f6250;
      background: #f7f2e8;
    }}
    .readiness-gaps-present {{
      border-color: #8a6a2a;
      background: #fff7df;
    }}
    .readiness-unsupported {{
      border-color: #7a4c4c;
      background: #f8eeee;
    }}
    .admin-action-badge {{
      display: inline-block;
      border: 1px solid #6f6a60;
      border-radius: 999px;
      padding: 3px 9px;
      background: #fbfaf7;
      color: #1f1f1f;
      font-family: ui-monospace, monospace;
      font-size: 0.78rem;
      font-weight: 700;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      print-color-adjust: exact;
      -webkit-print-color-adjust: exact;
    }}
    .admin-action-collect-initial-evidence {{
      border-color: #7a4c4c;
      background: #f8eeee;
    }}
    .admin-action-resolve-evidence-gaps {{
      border-color: #8a6a2a;
      background: #fff7df;
    }}
    .admin-action-proceed-review {{
      border-color: #6f6250;
      background: #f7f2e8;
    }}
    .admin-action-formal-review {{
      border-color: #2f6d4f;
      background: #eef7f1;
    }}
    .workflow-state-badge {{
      display: inline-block;
      border: 1px solid #6f6a60;
      border-radius: 999px;
      padding: 3px 9px;
      background: #fbfaf7;
      color: #1f1f1f;
      font-family: ui-monospace, monospace;
      font-size: 0.78rem;
      font-weight: 700;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      print-color-adjust: exact;
      -webkit-print-color-adjust: exact;
    }}
    .workflow-state-evidence-collection {{
      border-color: #7a4c4c;
      background: #f8eeee;
    }}
    .workflow-state-evidence-review {{
      border-color: #8a6a2a;
      background: #fff7df;
    }}
    .workflow-state-administrative-review {{
      border-color: #6f6250;
      background: #f7f2e8;
    }}
    .workflow-state-formal-review-ready {{
      border-color: #2f6d4f;
      background: #eef7f1;
    }}
    .disposition-badge {{
      display: inline-block;
      border: 1px solid #6f6a60;
      border-radius: 999px;
      padding: 3px 9px;
      background: #fbfaf7;
      color: #1f1f1f;
      font-family: ui-monospace, monospace;
      font-size: 0.78rem;
      font-weight: 700;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      print-color-adjust: exact;
      -webkit-print-color-adjust: exact;
    }}
    .disposition-open {{
      border-color: #8a6a2a;
      background: #fff7df;
    }}
    .disposition-pending-review {{
      border-color: #6f6250;
      background: #f7f2e8;
    }}
    .disposition-ready-review {{
      border-color: #2f6d4f;
      background: #eef7f1;
    }}
    .eligibility-badge {{
      display: inline-block;
      border: 1px solid #6f6a60;
      border-radius: 999px;
      padding: 3px 9px;
      background: #fbfaf7;
      color: #1f1f1f;
      font-family: ui-monospace, monospace;
      font-size: 0.78rem;
      font-weight: 700;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      print-color-adjust: exact;
      -webkit-print-color-adjust: exact;
    }}
    .eligibility-not-eligible {{
      border-color: #7a4c4c;
      background: #f8eeee;
    }}
    .eligibility-conditionally-eligible {{
      border-color: #6f6250;
      background: #f7f2e8;
    }}
    .eligibility-eligible {{
      border-color: #2f6d4f;
      background: #eef7f1;
    }}
    .administrative-status-badge {{
      display: inline-block;
      border: 1px solid #6f6a60;
      border-radius: 999px;
      padding: 3px 9px;
      background: #fbfaf7;
      color: #1f1f1f;
      font-family: ui-monospace, monospace;
      font-size: 0.78rem;
      font-weight: 700;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      print-color-adjust: exact;
      -webkit-print-color-adjust: exact;
    }}
    .administrative-status-active-collection {{
      border-color: #7a4c4c;
      background: #f8eeee;
    }}
    .administrative-status-active-review {{
      border-color: #8a6a2a;
      background: #fff7df;
    }}
    .administrative-status-pending-review {{
      border-color: #6f6250;
      background: #f7f2e8;
    }}
    .administrative-status-ready-review {{
      border-color: #2f6d4f;
      background: #eef7f1;
    }}
    .implementation-action-badge {{
      display: inline-block;
      border: 1px solid #6f6a60;
      border-radius: 999px;
      padding: 3px 9px;
      background: #fbfaf7;
      color: #1f1f1f;
      font-family: ui-monospace, monospace;
      font-size: 0.78rem;
      font-weight: 700;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      print-color-adjust: exact;
      -webkit-print-color-adjust: exact;
    }}
    .implementation-action-none {{
      border-color: #8a6a2a;
      background: #fff7df;
    }}
    .implementation-action-await-review {{
      border-color: #6f6250;
      background: #f7f2e8;
    }}
    .implementation-action-formal-review {{
      border-color: #2f6d4f;
      background: #eef7f1;
    }}
    .effective-state-badge {{
      display: inline-block;
      border: 1px solid #6f6a60;
      border-radius: 999px;
      padding: 3px 9px;
      background: #fbfaf7;
      color: #1f1f1f;
      font-family: ui-monospace, monospace;
      font-size: 0.78rem;
      font-weight: 700;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      print-color-adjust: exact;
      -webkit-print-color-adjust: exact;
    }}
    .effective-state-evidence-review-continues {{
      border-color: #8a6a2a;
      background: #fff7df;
    }}
    .effective-state-administrative-review-pending {{
      border-color: #6f6250;
      background: #f7f2e8;
    }}
    .effective-state-formal-review-ready {{
      border-color: #2f6d4f;
      background: #eef7f1;
    }}
    .outcome-badge {{
      display: inline-block;
      border: 1px solid #6f6a60;
      border-radius: 999px;
      padding: 3px 9px;
      background: #fbfaf7;
      color: #1f1f1f;
      font-family: ui-monospace, monospace;
      font-size: 0.78rem;
      font-weight: 700;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      print-color-adjust: exact;
      -webkit-print-color-adjust: exact;
    }}
    .outcome-ongoing-review {{
      border-color: #8a6a2a;
      background: #fff7df;
    }}
    .outcome-awaiting-determination {{
      border-color: #6f6250;
      background: #f7f2e8;
    }}
    .outcome-ready-determination {{
      border-color: #2f6d4f;
      background: #eef7f1;
    }}
    .outcome-readiness-badge {{
      display: inline-block;
      border: 1px solid #6f6a60;
      border-radius: 999px;
      padding: 3px 9px;
      background: #fbfaf7;
      color: #1f1f1f;
      font-family: ui-monospace, monospace;
      font-size: 0.78rem;
      font-weight: 700;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      print-color-adjust: exact;
      -webkit-print-color-adjust: exact;
    }}
    .outcome-readiness-not-ready {{
      border-color: #7a4c4c;
      background: #f8eeee;
    }}
    .outcome-readiness-conditionally-ready {{
      border-color: #6f6250;
      background: #f7f2e8;
    }}
    .outcome-readiness-ready {{
      border-color: #2f6d4f;
      background: #eef7f1;
    }}
    .outcome-target-badge {{
      display: inline-block;
      border: 1px solid #6f6a60;
      border-radius: 999px;
      padding: 3px 9px;
      background: #fbfaf7;
      color: #1f1f1f;
      font-family: ui-monospace, monospace;
      font-size: 0.78rem;
      font-weight: 700;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      print-color-adjust: exact;
      -webkit-print-color-adjust: exact;
    }}
    .outcome-target-review-awaiting-determination {{
      border-color: #7a4c4c;
      background: #f8eeee;
    }}
    .outcome-target-ready-for-determination {{
      border-color: #6f6250;
      background: #f7f2e8;
    }}
    .outcome-target-determination-pending {{
      border-color: #2f6d4f;
      background: #eef7f1;
    }}
    .resolution-badge {{
      display: inline-block;
      border: 1px solid #6f6a60;
      border-radius: 999px;
      padding: 3px 9px;
      background: #fbfaf7;
      color: #1f1f1f;
      font-family: ui-monospace, monospace;
      font-size: 0.78rem;
      font-weight: 700;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      print-color-adjust: exact;
      -webkit-print-color-adjust: exact;
    }}
    .resolution-unresolved {{
      border-color: #7a4c4c;
      background: #f8eeee;
    }}
    .resolution-partially-resolved {{
      border-color: #8a6a2a;
      background: #fff7df;
    }}
    .resolution-conditionally-resolved {{
      border-color: #6f6250;
      background: #f7f2e8;
    }}
    .resolution-resolved {{
      border-color: #2f6d4f;
      background: #eef7f1;
    }}
    .resolution-failed {{
      border-color: #6b3d3d;
      background: #f5e2e2;
    }}
    .resolution-readiness-badge {{
      display: inline-block;
      border: 1px solid #6f6a60;
      border-radius: 999px;
      padding: 3px 9px;
      background: #fbfaf7;
      color: #1f1f1f;
      font-family: ui-monospace, monospace;
      font-size: 0.78rem;
      font-weight: 700;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      print-color-adjust: exact;
      -webkit-print-color-adjust: exact;
    }}
    .resolution-readiness-not-ready {{
      border-color: #7a4c4c;
      background: #f8eeee;
    }}
    .resolution-readiness-conditionally-ready {{
      border-color: #8a6a2a;
      background: #fff7df;
    }}
    .resolution-readiness-ready {{
      border-color: #6f6250;
      background: #f7f2e8;
    }}
    .resolution-readiness-resolved {{
      border-color: #2f6d4f;
      background: #eef7f1;
    }}
    .resolution-determination-badge {{
      display: inline-block;
      border: 1px solid #6f6a60;
      border-radius: 999px;
      padding: 3px 9px;
      background: #fbfaf7;
      color: #1f1f1f;
      font-family: ui-monospace, monospace;
      font-size: 0.78rem;
      font-weight: 700;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      print-color-adjust: exact;
      -webkit-print-color-adjust: exact;
    }}
    .resolution-determination-not-available {{
      border-color: #7a4c4c;
      background: #f8eeee;
    }}
    .resolution-determination-pending {{
      border-color: #8a6a2a;
      background: #fff7df;
    }}
    .resolution-determination-required {{
      border-color: #6f6250;
      background: #f7f2e8;
    }}
    .resolution-determination-issued {{
      border-color: #245d61;
      background: #edf6f7;
    }}
    .resolution-determination-complete {{
      border-color: #2f6d4f;
      background: #eef7f1;
    }}
    .resolution-completion-badge {{
      display: inline-block;
      border: 1px solid #6f6a60;
      border-radius: 999px;
      padding: 3px 9px;
      background: #fbfaf7;
      color: #1f1f1f;
      font-family: ui-monospace, monospace;
      font-size: 0.78rem;
      font-weight: 700;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      print-color-adjust: exact;
      -webkit-print-color-adjust: exact;
    }}
    .resolution-completion-not-complete {{
      border-color: #7a4c4c;
      background: #f8eeee;
    }}
    .resolution-completion-pending {{
      border-color: #8a6a2a;
      background: #fff7df;
    }}
    .resolution-completion-required {{
      border-color: #6f6250;
      background: #f7f2e8;
    }}
    .resolution-completion-confirmed {{
      border-color: #2f6d4f;
      background: #eef7f1;
    }}
    .resolution-completion-failed {{
      border-color: #6b3d3d;
      background: #f5e2e2;
    }}
    .closure-badge {{
      display: inline-block;
      border: 1px solid #6f6a60;
      border-radius: 999px;
      padding: 3px 9px;
      background: #fbfaf7;
      color: #1f1f1f;
      font-family: ui-monospace, monospace;
      font-size: 0.78rem;
      font-weight: 700;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      print-color-adjust: exact;
      -webkit-print-color-adjust: exact;
    }}
    .closure-open {{
      border-color: #8a6a2a;
      background: #fff7df;
    }}
    .closure-pending {{
      border-color: #6f6250;
      background: #f7f2e8;
    }}
    .closure-without-resolution {{
      border-color: #7a4c4c;
      background: #f8eeee;
    }}
    .closure-with-resolution {{
      border-color: #2f6d4f;
      background: #eef7f1;
    }}
    .closure-failed {{
      border-color: #6b3d3d;
      background: #f5e2e2;
    }}
    .closure-precondition-badge {{
      display: inline-block;
      border: 1px solid #6f6a60;
      border-radius: 999px;
      padding: 3px 9px;
      background: #fbfaf7;
      color: #1f1f1f;
      font-family: ui-monospace, monospace;
      font-size: 0.78rem;
      font-weight: 700;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      print-color-adjust: exact;
      -webkit-print-color-adjust: exact;
    }}
    .closure-ready {{
      border-color: #2f6d4f;
      background: #eef7f1;
    }}
    .closure-conditional {{
      border-color: #6f6250;
      background: #f7f2e8;
    }}
    .closure-outstanding {{
      border-color: #8a6a2a;
      background: #fff7df;
    }}
    .closure-blocked {{
      border-color: #6b3d3d;
      background: #f5e2e2;
    }}
    .closure-pathway-badge {{
      display: inline-block;
      border: 1px solid #6f6a60;
      border-radius: 999px;
      padding: 3px 9px;
      background: #fbfaf7;
      color: #1f1f1f;
      font-family: ui-monospace, monospace;
      font-size: 0.78rem;
      font-weight: 700;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      print-color-adjust: exact;
      -webkit-print-color-adjust: exact;
    }}
    .closure-eligibility-pending {{
      border-color: #8a6a2a;
      background: #fff7df;
    }}
    .closure-readiness-pending {{
      border-color: #6f6250;
      background: #f7f2e8;
    }}
    .closure-determination-pending {{
      border-color: #245d61;
      background: #edf6f7;
    }}
    .closure-confirmation-pending {{
      border-color: #6f6250;
      background: #f7f2e8;
    }}
    .closure-complete {{
      border-color: #2f6d4f;
      background: #eef7f1;
    }}
    .closure-readiness-badge {{
      display: inline-block;
      border: 1px solid #6f6a60;
      border-radius: 999px;
      padding: 3px 9px;
      background: #fbfaf7;
      color: #1f1f1f;
      font-family: ui-monospace, monospace;
      font-size: 0.78rem;
      font-weight: 700;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      print-color-adjust: exact;
      -webkit-print-color-adjust: exact;
    }}
    .closure-readiness-ready {{
      border-color: #2f6d4f;
      background: #eef7f1;
    }}
    .closure-readiness-not-ready {{
      border-color: #8a6a2a;
      background: #fff7df;
    }}
    .closure-determination-badge {{
      display: inline-block;
      border: 1px solid #6f6a60;
      border-radius: 999px;
      padding: 3px 9px;
      background: #fbfaf7;
      color: #1f1f1f;
      font-family: ui-monospace, monospace;
      font-size: 0.78rem;
      font-weight: 700;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      print-color-adjust: exact;
      -webkit-print-color-adjust: exact;
    }}
    .closure-determination-not-available {{
      border-color: #7a4c4c;
      background: #f8eeee;
    }}
    .closure-determination-pending {{
      border-color: #8a6a2a;
      background: #fff7df;
    }}
    .closure-determination-required {{
      border-color: #6f6250;
      background: #f7f2e8;
    }}
    .closure-determination-issued {{
      border-color: #245d61;
      background: #edf6f7;
    }}
    .closure-determination-complete {{
      border-color: #2f6d4f;
      background: #eef7f1;
    }}
    .closure-completion-badge {{
      display: inline-block;
      border: 1px solid #6f6a60;
      border-radius: 999px;
      padding: 3px 9px;
      background: #fbfaf7;
      color: #1f1f1f;
      font-family: ui-monospace, monospace;
      font-size: 0.78rem;
      font-weight: 700;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      print-color-adjust: exact;
      -webkit-print-color-adjust: exact;
    }}
    .closure-completion-not-complete {{
      border-color: #7a4c4c;
      background: #f8eeee;
    }}
    .closure-completion-pending {{
      border-color: #8a6a2a;
      background: #fff7df;
    }}
    .closure-completion-in-progress {{
      border-color: #245d61;
      background: #edf6f7;
    }}
    .closure-completion-complete {{
      border-color: #2f6d4f;
      background: #eef7f1;
    }}
    .archive-classification-badge {{
      display: inline-block;
      border: 1px solid #6f6a60;
      border-radius: 999px;
      padding: 3px 9px;
      background: #fbfaf7;
      color: #1f1f1f;
      font-family: ui-monospace, monospace;
      font-size: 0.78rem;
      font-weight: 700;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      print-color-adjust: exact;
      -webkit-print-color-adjust: exact;
    }}
    .archive-classification-not-archivable {{
      border-color: #7a4c4c;
      background: #f8eeee;
    }}
    .archive-classification-eligible {{
      border-color: #2f6d4f;
      background: #eef7f1;
    }}
    .archive-classification-archived {{
      border-color: #245d61;
      background: #edf6f7;
    }}
    .archive-preconditions-badge {{
      display: inline-block;
      border: 1px solid #6f6a60;
      border-radius: 999px;
      padding: 3px 9px;
      background: #fbfaf7;
      color: #1f1f1f;
      font-family: ui-monospace, monospace;
      font-size: 0.78rem;
      font-weight: 700;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      print-color-adjust: exact;
      -webkit-print-color-adjust: exact;
    }}
    .archive-preconditions-outstanding {{
      border-color: #8a6a2a;
      background: #fff7df;
    }}
    .archive-preconditions-satisfied {{
      border-color: #2f6d4f;
      background: #eef7f1;
    }}
    .archive-pathway-badge {{
      display: inline-block;
      border: 1px solid #6f6a60;
      border-radius: 999px;
      padding: 3px 9px;
      background: #fbfaf7;
      color: #1f1f1f;
      font-family: ui-monospace, monospace;
      font-size: 0.78rem;
      font-weight: 700;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      print-color-adjust: exact;
      -webkit-print-color-adjust: exact;
    }}
    .archive-pathway-eligibility-pending {{
      border-color: #8a6a2a;
      background: #fff7df;
    }}
    .archive-pathway-determination-pending {{
      border-color: #6f6250;
      background: #f7f2e8;
    }}
    .archive-pathway-ready {{
      border-color: #2f6d4f;
      background: #eef7f1;
    }}
    .archive-pathway-archived {{
      border-color: #245d61;
      background: #edf6f7;
    }}
    .archive-readiness-badge {{
      display: inline-block;
      border: 1px solid #6f6a60;
      border-radius: 999px;
      padding: 3px 9px;
      background: #fbfaf7;
      color: #1f1f1f;
      font-family: ui-monospace, monospace;
      font-size: 0.78rem;
      font-weight: 700;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      print-color-adjust: exact;
      -webkit-print-color-adjust: exact;
    }}
    .archive-readiness-not-ready {{
      border-color: #8a6a2a;
      background: #fff7df;
    }}
    .archive-readiness-ready {{
      border-color: #2f6d4f;
      background: #eef7f1;
    }}
    .archive-readiness-archived {{
      border-color: #245d61;
      background: #edf6f7;
    }}
    .archive-determination-badge {{
      display: inline-block;
      border: 1px solid #6f6a60;
      border-radius: 999px;
      padding: 3px 9px;
      background: #fbfaf7;
      color: #1f1f1f;
      font-family: ui-monospace, monospace;
      font-size: 0.78rem;
      font-weight: 700;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      print-color-adjust: exact;
      -webkit-print-color-adjust: exact;
    }}
    .archive-determination-not-available {{
      border-color: #7a4c4c;
      background: #f8eeee;
    }}
    .archive-determination-eligible {{
      border-color: #2f6d4f;
      background: #eef7f1;
    }}
    .archive-determination-archived {{
      border-color: #245d61;
      background: #edf6f7;
    }}
    .archive-completion-badge {{
      display: inline-block;
      border: 1px solid #6f6a60;
      border-radius: 999px;
      padding: 3px 9px;
      background: #fbfaf7;
      color: #1f1f1f;
      font-family: ui-monospace, monospace;
      font-size: 0.78rem;
      font-weight: 700;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      print-color-adjust: exact;
      -webkit-print-color-adjust: exact;
    }}
    .archive-completion-not-complete {{
      border-color: #7a4c4c;
      background: #f8eeee;
    }}
    .archive-completion-complete {{
      border-color: #2f6d4f;
      background: #eef7f1;
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
    @media screen {{
      .print-admin-section-body {{
        display: none;
      }}
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
      details > summary {{
        display: block;
      }}
      details:not([open]) > *:not(summary) {{
        display: block;
      }}
      details.admin-section-group {{
        display: block !important;
      }}
      details.admin-section-group > summary {{
        display: block !important;
      }}
      details.admin-section-group > .admin-section-body {{
        display: none !important;
      }}
      details.admin-section-group:not([open]) > .admin-section-body {{
        display: none !important;
      }}
      .print-admin-section-body {{
        display: block !important;
        border-top: 1px solid #e5e1d8;
        margin-top: 22px;
        padding-top: 18px;
      }}
    }}
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
    <h1>Admin Record Evidence</h1>
    <p class="notice">
      This read-only administrative view inverts attachment relationships by record target.
      No upload, download, public file access, or mutation controls are available here.
    </p>
    <section class="management-section record-summary">
      <h2>Record summary</h2>
      <p><strong>Record reference:</strong> {escape(reference)}</p>
      <p><strong>Record version:</strong> {record_version}</p>
      <a class="navigation-link" href="{attachments_url}">Back to attachment management</a>
    </section>
    {administrative_workflow_group}
    {outcome_analysis_group}
    {resolution_analysis_group}
    {closure_analysis_group}
    {archive_analysis_group}
    {supporting_evidence_group}
    {evidence_coverage_group}
  </main>
</body>
</html>"""


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

    unknown_fields = (
        set(payload) - EDITABLE_ATTACHMENT_METADATA_FIELDS - IMMUTABLE_ATTACHMENT_FIELDS
    )
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


def _validate_classification_payload(payload: dict[str, Any]) -> str:
    if not isinstance(payload, dict):
        raise _http_error(400, "classification_payload_invalid")
    if set(payload.keys()) != {"classification"}:
        raise _http_error(400, "classification_payload_invalid")
    try:
        return validate_attachment_classification(payload.get("classification"))
    except ValueError as exc:
        raise _http_error(400, "classification_invalid") from exc


def _validate_publication_payload(payload: dict[str, Any]) -> str:
    if not isinstance(payload, dict):
        raise _http_error(400, "publication_payload_invalid")
    if set(payload.keys()) != {"publication_status"}:
        raise _http_error(400, "publication_payload_invalid")
    try:
        return validate_publication_status(payload.get("publication_status"))
    except ValueError as exc:
        raise _http_error(400, "publication_status_invalid") from exc


def _validate_visibility_payload(payload: dict[str, Any]) -> str:
    if not isinstance(payload, dict):
        raise _http_error(400, "visibility_payload_invalid")
    if set(payload.keys()) != {"visibility"}:
        raise _http_error(400, "visibility_payload_invalid")
    try:
        return validate_attachment_visibility(payload.get("visibility"))
    except ValueError as exc:
        raise _http_error(400, "visibility_invalid") from exc


def _validate_relationship_payload(payload: dict[str, Any]) -> tuple[str, str, str]:
    if not isinstance(payload, dict):
        raise _http_error(400, "relationship_payload_invalid")
    allowed_fields = {"relationship_type", "target_type", "target_key"}
    if set(payload.keys()) != allowed_fields:
        raise _http_error(400, "relationship_payload_invalid")
    try:
        return validate_attachment_relationship(
            payload.get("relationship_type"),
            payload.get("target_type"),
            payload.get("target_key"),
        )
    except ValueError as exc:
        raise _http_error(400, "relationship_payload_invalid") from exc


def _record_table_columns(conn: sqlite3.Connection) -> set[str]:
    return {
        str(row["name"])
        for row in conn.execute("PRAGMA table_info(records)").fetchall()
    }


def _admin_record_select_fields(conn: sqlite3.Connection) -> str:
    columns = _record_table_columns(conn)
    fields = ["reference", "version", "conditions_json", "signals_json", "finding"]
    for optional_field in ("trajectory", "system_state"):
        if optional_field in columns:
            fields.append(optional_field)
    return ", ".join(fields)


def _relationship_response(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "relationship_id": row["id"],
        "reference": row["reference"],
        "record_version": row["record_version"],
        "attachment_id": row["attachment_id"],
        "relationship_type": row["relationship_type"],
        "target_type": row["target_type"],
        "target_key": row["target_key"],
        "is_active": row["is_active"],
        "created_at": row["created_at"],
        "created_by": row["created_by"],
        "removed_at": row["removed_at"],
        "removed_by": row["removed_by"],
    }


def _render_temporary_attachment_upload_form(reference: str) -> str:
    target_type_options = "".join(
        f'<option value="{escape(value)}">{escape(value)}</option>'
        for value in ATTACHMENT_RELATIONSHIP_TARGET_TYPE_OPTIONS
    )
    return f"""
      <form class="temporary-upload-form" method="post" enctype="multipart/form-data"
            action="/api/admin/session/records/{escape(reference)}/attachments/temp-upload">
        <label>
          Record reference / target reference
          <input type="text" name="record_reference" value="{escape(reference)}" required>
        </label>
        <label>
          Target type
          <select name="target_type" required>
            {target_type_options}
          </select>
        </label>
        <label>
          Target label
          <input type="text" name="target_label" placeholder="Escalation Without Response" required>
        </label>
        <label>
          Attachment title / label
          <input type="text" name="attachment_title" placeholder="Test evidence — escalation without response" required>
        </label>
        <label>
          Optional description
          <textarea name="description"></textarea>
        </label>
        <label>
          File upload
          <input type="file" name="file" required>
        </label>
        <button type="submit">Upload attachment</button>
      </form>"""


def render_admin_attachments_page(
    *,
    reference: str,
    record_version: int,
    attachments: list[dict[str, Any]],
    audit_events: list[dict[str, Any]],
    relationship_target_options: dict[str, list[str]],
) -> str:
    attachment_rows = _render_admin_attachment_rows(
        attachments,
        relationship_target_options=relationship_target_options,
    )
    audit_rows = _render_admin_audit_events(audit_events)
    temporary_upload_enabled = admin_temp_upload_enabled()
    temporary_upload_intro = (
        "Temporary admin upload is available for evidence verification only. "
        "No public download, public file access, or canonical verification changes are introduced."
        if temporary_upload_enabled
        else "Temporary admin upload is disabled. No public download, public file access, or canonical verification changes are introduced."
    )
    temporary_upload_section = (
        f"""
    <section class="management-section temporary-upload">
      <h2>Temporary admin attachment upload</h2>
      <p class="notice">
        Temporary admin upload utility for evidence verification. Attachments do not alter canonical record verification hashes and are not publicly downloadable.
      </p>
      {_render_temporary_attachment_upload_form(reference)}
    </section>"""
        if temporary_upload_enabled
        else ""
    )
    temporary_upload_capability = (
        "<li>temporary admin upload</li>" if temporary_upload_enabled else ""
    )
    temporary_upload_governance = (
        "Temporary admin upload is available for evidence verification only. No public download or public file access is available."
        if temporary_upload_enabled
        else "Temporary admin upload is disabled. No public download or public file access is available."
    )
    relationship_target_options_json = _safe_json_for_script(
        relationship_target_options
    )
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
    .attachment-metadata-update-form {{
      border-top: 1px solid #eee;
      display: flex;
      flex-wrap: wrap;
      align-items: end;
      gap: 10px;
      padding: 10px;
      background: #fffdf8;
    }}
    .attachment-metadata-update-form label {{
      display: grid;
      gap: 4px;
      color: #555;
      font-size: 0.78rem;
      font-family: ui-monospace, monospace;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }}
    .attachment-metadata-update-form select {{
      min-width: 180px;
      padding: 7px 8px;
      border: 1px solid #d8d4ca;
      background: #fff;
      color: #222;
      font: 0.9rem system-ui, sans-serif;
      text-transform: none;
      letter-spacing: 0;
    }}
    .attachment-metadata-update-form button {{
      border: 1px solid #245d61;
      background: #245d61;
      color: #fff;
      padding: 8px 10px;
      font: 0.86rem system-ui, sans-serif;
      cursor: pointer;
    }}
    .classification-update-note,
    .publication-update-note,
    .visibility-update-note,
    .relationship-update-note {{
      flex-basis: 100%;
      margin: 0;
      color: #666;
      font-size: 0.84rem;
    }}
    .evidence-relationships {{
      border-top: 1px solid #eee;
      padding: 10px;
      background: #fbfaf7;
    }}
    .evidence-relationships h3 {{
      margin: 0 0 8px;
      color: #555;
      font-size: 0.88rem;
      font-family: ui-monospace, monospace;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }}
    .relationship-coverage {{
      display: grid;
      gap: 8px;
      margin: 0 0 12px;
      padding: 10px;
      border: 1px solid #e3ded4;
      background: #fff;
    }}
    .relationship-coverage h4,
    .coverage-unlinked h4 {{
      margin: 0;
      color: #555;
      font-size: 0.78rem;
      font-family: ui-monospace, monospace;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }}
    .relationship-coverage p {{
      margin: 0;
    }}
    .coverage-unlinked ul {{
      margin: 6px 0 0 20px;
      padding: 0;
    }}
    .relationship-group {{
      margin: 0 0 10px;
      border: 1px solid #e3ded4;
      background: #fff;
    }}
    .relationship-group summary {{
      padding: 8px 10px;
      background: #f7f4ed;
      font-size: 0.88rem;
    }}
    .relationship-list {{
      display: grid;
      gap: 8px;
      margin: 0 0 12px;
      padding: 0;
      list-style: none;
    }}
    .relationship-card {{
      display: grid;
      gap: 5px;
      padding: 10px;
      border: 1px solid #e3ded4;
      background: #fff;
    }}
    .relationship-meta {{
      color: #555;
      font-family: ui-monospace, monospace;
      font-size: 0.78rem;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }}
    .relationship-target {{
      color: #1a1a1a;
      font-weight: 650;
    }}
    .relationship-remove-form {{
      display: inline-block;
    }}
    .attachment-relationship-form {{
      display: flex;
      flex-wrap: wrap;
      align-items: end;
      gap: 10px;
      margin-top: 10px;
    }}
    .attachment-relationship-form label {{
      display: grid;
      gap: 4px;
      color: #555;
      font-size: 0.78rem;
      font-family: ui-monospace, monospace;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }}
    .attachment-relationship-form select,
    .attachment-relationship-form input {{
      min-width: 180px;
      padding: 7px 8px;
      border: 1px solid #d8d4ca;
      background: #fff;
      color: #222;
      font: 0.9rem system-ui, sans-serif;
      text-transform: none;
      letter-spacing: 0;
    }}
    .attachment-relationship-form button,
    .relationship-remove-form button {{
      border: 1px solid #245d61;
      background: #245d61;
      color: #fff;
      padding: 8px 10px;
      font: 0.86rem system-ui, sans-serif;
      cursor: pointer;
    }}
    .temporary-upload-form {{
      display: grid;
      gap: 12px;
      padding: 14px;
      border: 1px solid #d8d4ca;
      background: #fffdf8;
    }}
    .temporary-upload-form label {{
      display: grid;
      gap: 5px;
      color: #555;
      font-size: 0.78rem;
      font-family: ui-monospace, monospace;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }}
    .temporary-upload-form input,
    .temporary-upload-form select,
    .temporary-upload-form textarea {{
      width: 100%;
      padding: 8px 10px;
      border: 1px solid #d8d4ca;
      background: #fff;
      color: #222;
      font: 0.9rem system-ui, sans-serif;
      text-transform: none;
      letter-spacing: 0;
    }}
    .temporary-upload-form textarea {{
      min-height: 76px;
      resize: vertical;
    }}
    .temporary-upload-form button {{
      width: max-content;
      border: 1px solid #245d61;
      background: #245d61;
      color: #fff;
      padding: 9px 12px;
      font: 0.9rem system-ui, sans-serif;
      cursor: pointer;
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
      Administrative attachment management is controlled in this stage.
      Classification, publication status, and visibility metadata updates are available from this page.
      {escape(temporary_upload_intro)}
    </p>
    <section class="management-section record-summary">
      <h2>Record summary</h2>
      <p><strong>Record reference:</strong> {escape(reference)}</p>
      <p><strong>Record version:</strong> {record_version}</p>
      <p><a href="/admin/records/{escape(reference)}/evidence">View record evidence by target</a></p>
    </section>
    {temporary_upload_section}
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
          <li>visibility workflow</li>
          <li>publication workflow</li>
          {temporary_upload_capability}
        </ul>
      </div>
      <div class="capability-group">
        <h3>Planned</h3>
        <ul>
          <li>public file serving</li>
        </ul>
      </div>
    </section>
    <section class="management-section audit-trail">
      <h2>Audit trail</h2>
      {audit_rows}
    </section>
    <section class="management-section governance-notice">
      <h2>Governance notice</h2>
      <p>Administrative attachment management is controlled in this stage.</p>
      <p>Classification, publication status, and visibility metadata updates are available from this page.</p>
      <p>{escape(temporary_upload_governance)}</p>
    </section>
  </main>
  <script>
    const RELATIONSHIP_TARGET_OPTIONS = {relationship_target_options_json};
    const guidedTargetDisplayLabel = (value) => {{
      return /^[A-Z0-9]+(?:_[A-Z0-9]+)+$/.test(value)
        ? value
            .split("_")
            .join(" ")
            .toLowerCase()
            .replace(/\\b\\w/g, (char) => char.toUpperCase())
        : value;
    }};
    document.querySelectorAll("[data-json-field]").forEach((form) => {{
      form.addEventListener("submit", async (event) => {{
        event.preventDefault();
        const formData = new FormData(form);
        const field = form.getAttribute("data-json-field");
        const response = await fetch(form.action, {{
          method: "PATCH",
          credentials: "same-origin",
          headers: {{
            "Accept": "application/json",
            "Content-Type": "application/json"
          }},
          body: JSON.stringify({{ [field]: formData.get(field) }})
        }});
        if (response.ok) {{
          window.location.reload();
          return;
        }}
        window.alert("Classification update failed.");
      }});
    }});
    document.querySelectorAll("[data-relationship-add-form]").forEach((form) => {{
      const targetTypeSelect = form.querySelector('select[name="target_type"]');
      const targetKeySelect = form.querySelector("[data-target-key-select]");
      const submitButton = form.querySelector("[data-relationship-submit]");
      const updateTargetKeyOptions = () => {{
        const values = RELATIONSHIP_TARGET_OPTIONS[targetTypeSelect.value] || [];
        targetKeySelect.innerHTML = "";
        if (!values.length) {{
          const option = document.createElement("option");
          option.value = "";
          option.textContent = "No available targets";
          option.disabled = true;
          option.selected = true;
          targetKeySelect.appendChild(option);
          submitButton.disabled = true;
          return;
        }}
        values.forEach((value) => {{
          const option = document.createElement("option");
          option.value = value;
          option.textContent = guidedTargetDisplayLabel(value);
          targetKeySelect.appendChild(option);
        }});
        submitButton.disabled = false;
      }};
      if (targetTypeSelect && targetKeySelect && submitButton) {{
        targetTypeSelect.addEventListener("change", updateTargetKeyOptions);
        updateTargetKeyOptions();
      }}
      form.addEventListener("submit", async (event) => {{
        event.preventDefault();
        const formData = new FormData(form);
        const response = await fetch(form.action, {{
          method: "POST",
          credentials: "same-origin",
          headers: {{
            "Accept": "application/json",
            "Content-Type": "application/json"
          }},
          body: JSON.stringify({{
            relationship_type: formData.get("relationship_type"),
            target_type: formData.get("target_type"),
            target_key: formData.get("target_key")
          }})
        }});
        if (response.ok) {{
          window.location.reload();
          return;
        }}
        window.alert("Relationship update failed.");
      }});
    }});
    document.querySelectorAll("[data-relationship-remove-form]").forEach((form) => {{
      form.addEventListener("submit", async (event) => {{
        event.preventDefault();
        const response = await fetch(form.action, {{
          method: "PATCH",
          credentials: "same-origin",
          headers: {{
            "Accept": "application/json",
            "Content-Type": "application/json"
          }}
        }});
        if (response.ok) {{
          window.location.reload();
          return;
        }}
        let detail = "";
        try {{
          const payload = await response.json();
          detail = payload?.detail ? `: ${{payload.detail}}` : "";
        }} catch (_error) {{
          detail = "";
        }}
        window.alert(`Relationship removal failed (${{response.status}}${{detail}}).`);
      }});
    }});
  </script>
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
            f"SELECT {_admin_record_select_fields(conn)} FROM records "
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
                relationship_target_options=_record_relationship_target_options(record),
            )
        )
    finally:
        conn.close()


@router.get("/admin/records/{reference}/evidence", response_class=HTMLResponse)
def admin_record_evidence_page(reference: str, request: Request):
    require_admin_session(request)
    conn = get_db()
    try:
        record = conn.execute(
            f"SELECT {_admin_record_select_fields(conn)} FROM records "
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
        attachments = _attach_relationship_lineage_metadata(
            conn,
            reference=reference,
            attachments=attachments,
        )
        return HTMLResponse(
            content=render_admin_record_evidence_page(
                reference=record["reference"],
                record_version=record["version"],
                evidence_groups=_record_evidence_groups(record, attachments),
                record_outputs=_record_outputs_from_record(record),
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


@router.post("/api/admin/session/records/{reference}/attachments/temp-upload")
def temporary_admin_attachment_upload_route(
    reference: str,
    request: Request,
    record_reference: str = Form(...),
    target_type: str = Form(...),
    target_label: str = Form(...),
    attachment_title: str = Form(...),
    description: str | None = Form(None),
    file: UploadFile = File(...),
):
    require_admin_session(request)
    if not admin_temp_upload_enabled():
        raise _http_error(404, "temporary_upload_disabled")

    target_reference = str(record_reference or "").strip()
    if target_reference != reference:
        raise _http_error(400, "attachment_reference_mismatch")

    filename = getattr(file, "filename", None) or "attachment"
    content_type = getattr(file, "content_type", None)
    file_handle = getattr(file, "file", None)
    if file_handle is None or not hasattr(file_handle, "read"):
        raise _http_error(400, "attachment_file_required")
    if hasattr(file_handle, "seek"):
        file_handle.seek(0)
    data = file_handle.read()
    if isinstance(data, str):
        data = data.encode("utf-8")
    if not isinstance(data, bytes):
        raise _http_error(400, "attachment_file_required")
    normalized_content_type = validate_temporary_attachment_upload(content_type, data)

    conn = get_db()
    try:
        record = conn.execute(
            "SELECT reference, version, conditions_json, signals_json, finding FROM records "
            "WHERE reference = ? AND is_latest = 1 "
            "ORDER BY version DESC LIMIT 1",
            (reference,),
        ).fetchone()
        if not record:
            raise _http_error(404, "record_not_found")

        normalized_target_type = str(target_type or "").strip()
        target_key = _resolve_record_target_key(
            record,
            normalized_target_type,
            target_label,
        )
        relationship_type, normalized_target_type, target_key = (
            validate_attachment_relationship(
                "supports",
                normalized_target_type,
                target_key,
            )
        )

        stored_attachment = store_attachment_bytes(
            conn,
            reference=reference,
            data=data,
            original_filename=filename,
            content_type=normalized_content_type,
            visibility="private",
            redaction_status="none",
            title=str(attachment_title or "").strip(),
            description=(description.strip() if isinstance(description, str) else None),
            source_label="Temporary admin upload",
            classification="evidence",
            publication_status="internal",
            uploaded_by="admin",
            root=Path(os.getenv("CDE_ATTACHMENT_ROOT", str(ATTACHMENT_ROOT))),
        )
        attachment_id = int(stored_attachment["attachment_id"])

        attachment_created_audit_id = record_attachment_audit_event(
            conn,
            event_type="attachment_created",
            reference=reference,
            attachment_id=attachment_id,
            record_version=int(stored_attachment["record_version"]),
            metadata={
                "temporary_admin_upload": True,
                "filename": stored_attachment["filename"],
                "sha256_hash": stored_attachment["sha256_hash"],
                "file_size_bytes": stored_attachment["file_size_bytes"],
            },
        )

        created_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        cursor = conn.execute(
            """
            INSERT INTO record_attachment_relationships (
                reference, record_version, attachment_id, relationship_type,
                target_type, target_key, is_active, created_at, created_by
            )
            VALUES (?, ?, ?, ?, ?, ?, 1, ?, 'admin')
            """,
            (
                reference,
                int(stored_attachment["record_version"]),
                attachment_id,
                relationship_type,
                normalized_target_type,
                target_key,
                created_at,
            ),
        )
        relationship_id = int(cursor.lastrowid)
        relationship = conn.execute(
            "SELECT * FROM record_attachment_relationships WHERE id = ?",
            (relationship_id,),
        ).fetchone()
        relationship_audit_id = record_attachment_audit_event(
            conn,
            event_type="attachment_relationship_added",
            reference=reference,
            attachment_id=attachment_id,
            record_version=int(stored_attachment["record_version"]),
            metadata={
                "relationship_id": relationship_id,
                "relationship_type": relationship_type,
                "target_type": normalized_target_type,
                "target_key": target_key,
                "temporary_admin_upload": True,
            },
        )
        attachment = conn.execute(
            "SELECT * FROM record_attachments WHERE id = ? AND reference = ?",
            (attachment_id, reference),
        ).fetchone()
        conn.commit()
        return JSONResponse(
            content={
                "ok": True,
                "attachment_audit_event_id": attachment_created_audit_id,
                "relationship_audit_event_id": relationship_audit_id,
                "attachment": _safe_attachment_response(attachment),
                "relationship": _relationship_response(relationship),
            }
        )
    except AttachmentRecordNotFound as exc:
        conn.rollback()
        raise _http_error(404, "record_not_found") from exc
    except ValueError as exc:
        conn.rollback()
        raise _http_error(400, "attachment_upload_invalid") from exc
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.patch(
    "/api/admin/session/records/{reference}/attachments/{attachment_id}/metadata"
)
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


@router.patch(
    "/api/admin/session/records/{reference}/attachments/{attachment_id}/classification"
)
def update_attachment_classification_route(
    reference: str,
    attachment_id: int,
    request: Request,
    payload: dict[str, Any],
):
    require_admin_session(request)
    classification = _validate_classification_payload(payload)
    conn = get_db()
    try:
        current = conn.execute(
            "SELECT * FROM record_attachments WHERE id = ? AND reference = ?",
            (attachment_id, reference),
        ).fetchone()
        if not current:
            raise _http_error(404, "attachment_not_found")

        previous_classification = current["classification"] or "other"
        conn.execute(
            """
            UPDATE record_attachments
            SET classification = ?
            WHERE id = ? AND reference = ?
            """,
            (classification, attachment_id, reference),
        )
        updated = conn.execute(
            "SELECT * FROM record_attachments WHERE id = ? AND reference = ?",
            (attachment_id, reference),
        ).fetchone()
        audit_event_id = record_attachment_audit_event(
            conn,
            event_type="attachment_classification_updated",
            reference=reference,
            attachment_id=attachment_id,
            record_version=updated["record_version"],
            metadata={
                "previous_classification": previous_classification,
                "new_classification": updated["classification"],
            },
        )
        conn.commit()

        return JSONResponse(
            content={
                "ok": True,
                "audit_event_id": audit_event_id,
                "attachment": _safe_attachment_response(updated),
            }
        )
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.patch(
    "/api/admin/session/records/{reference}/attachments/{attachment_id}/publication"
)
def update_attachment_publication_route(
    reference: str,
    attachment_id: int,
    request: Request,
    payload: dict[str, Any],
):
    require_admin_session(request)
    publication_status = _validate_publication_payload(payload)
    conn = get_db()
    try:
        current = conn.execute(
            "SELECT * FROM record_attachments WHERE id = ? AND reference = ?",
            (attachment_id, reference),
        ).fetchone()
        if not current:
            raise _http_error(404, "attachment_not_found")

        previous_publication_status = current["publication_status"] or "internal"
        conn.execute(
            """
            UPDATE record_attachments
            SET publication_status = ?
            WHERE id = ? AND reference = ?
            """,
            (publication_status, attachment_id, reference),
        )
        updated = conn.execute(
            "SELECT * FROM record_attachments WHERE id = ? AND reference = ?",
            (attachment_id, reference),
        ).fetchone()
        audit_event_id = record_attachment_audit_event(
            conn,
            event_type="attachment_publication_updated",
            reference=reference,
            attachment_id=attachment_id,
            record_version=updated["record_version"],
            metadata={
                "previous_publication_status": previous_publication_status,
                "new_publication_status": updated["publication_status"],
            },
        )
        conn.commit()

        return JSONResponse(
            content={
                "ok": True,
                "audit_event_id": audit_event_id,
                "attachment": _safe_attachment_response(updated),
            }
        )
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.patch(
    "/api/admin/session/records/{reference}/attachments/{attachment_id}/visibility"
)
def update_attachment_visibility_route(
    reference: str,
    attachment_id: int,
    request: Request,
    payload: dict[str, Any],
):
    require_admin_session(request)
    visibility = _validate_visibility_payload(payload)
    conn = get_db()
    try:
        current = conn.execute(
            "SELECT * FROM record_attachments WHERE id = ? AND reference = ?",
            (attachment_id, reference),
        ).fetchone()
        if not current:
            raise _http_error(404, "attachment_not_found")

        previous_visibility = current["visibility"] or "private"
        conn.execute(
            """
            UPDATE record_attachments
            SET visibility = ?
            WHERE id = ? AND reference = ?
            """,
            (visibility, attachment_id, reference),
        )
        updated = conn.execute(
            "SELECT * FROM record_attachments WHERE id = ? AND reference = ?",
            (attachment_id, reference),
        ).fetchone()
        audit_event_id = record_attachment_audit_event(
            conn,
            event_type="attachment_visibility_updated",
            reference=reference,
            attachment_id=attachment_id,
            record_version=updated["record_version"],
            metadata={
                "previous_visibility": previous_visibility,
                "new_visibility": updated["visibility"],
            },
        )
        conn.commit()

        return JSONResponse(
            content={
                "ok": True,
                "audit_event_id": audit_event_id,
                "attachment": _safe_attachment_response(updated),
            }
        )
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.post(
    "/api/admin/session/records/{reference}/attachments/{attachment_id}/relationships"
)
def add_attachment_relationship_route(
    reference: str,
    attachment_id: int,
    request: Request,
    payload: dict[str, Any],
):
    require_admin_session(request)
    relationship_type, target_type, target_key = _validate_relationship_payload(payload)
    conn = get_db()
    try:
        attachment = conn.execute(
            "SELECT * FROM record_attachments WHERE id = ? AND reference = ?",
            (attachment_id, reference),
        ).fetchone()
        if not attachment:
            raise _http_error(404, "attachment_not_found")

        created_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        cursor = conn.execute(
            """
            INSERT INTO record_attachment_relationships (
                reference, record_version, attachment_id, relationship_type,
                target_type, target_key, is_active, created_at, created_by
            )
            VALUES (?, ?, ?, ?, ?, ?, 1, ?, 'admin')
            """,
            (
                reference,
                attachment["record_version"],
                attachment_id,
                relationship_type,
                target_type,
                target_key,
                created_at,
            ),
        )
        relationship_id = int(cursor.lastrowid)
        relationship = conn.execute(
            "SELECT * FROM record_attachment_relationships WHERE id = ?",
            (relationship_id,),
        ).fetchone()
        audit_event_id = record_attachment_audit_event(
            conn,
            event_type="attachment_relationship_added",
            reference=reference,
            attachment_id=attachment_id,
            record_version=attachment["record_version"],
            metadata={
                "relationship_id": relationship_id,
                "relationship_type": relationship_type,
                "target_type": target_type,
                "target_key": target_key,
            },
        )
        conn.commit()
        return JSONResponse(
            content={
                "ok": True,
                "audit_event_id": audit_event_id,
                "relationship": _relationship_response(relationship),
            }
        )
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.patch(
    "/api/admin/session/records/{reference}/attachments/{attachment_id}/relationships/{relationship_id}/remove"
)
def remove_attachment_relationship_route(
    reference: str,
    attachment_id: int,
    relationship_id: int,
    request: Request,
):
    require_admin_session(request)
    conn = get_db()
    try:
        relationship = conn.execute(
            """
            SELECT * FROM record_attachment_relationships
            WHERE id = ? AND reference = ? AND attachment_id = ?
            """,
            (relationship_id, reference, attachment_id),
        ).fetchone()
        if not relationship:
            raise _http_error(404, "relationship_not_found")

        removed_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        conn.execute(
            """
            UPDATE record_attachment_relationships
            SET is_active = 0, removed_at = ?, removed_by = 'admin'
            WHERE id = ? AND reference = ? AND attachment_id = ?
            """,
            (removed_at, relationship_id, reference, attachment_id),
        )
        updated = conn.execute(
            "SELECT * FROM record_attachment_relationships WHERE id = ?",
            (relationship_id,),
        ).fetchone()
        audit_event_id = record_attachment_audit_event(
            conn,
            event_type="attachment_relationship_removed",
            reference=reference,
            attachment_id=attachment_id,
            record_version=updated["record_version"],
            metadata={
                "relationship_id": updated["id"],
                "relationship_type": updated["relationship_type"],
                "target_type": updated["target_type"],
                "target_key": updated["target_key"],
            },
        )
        conn.commit()
        return JSONResponse(
            content={
                "ok": True,
                "audit_event_id": audit_event_id,
                "relationship": _relationship_response(updated),
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


@router.patch(
    "/api/admin/session/records/{reference}/attachments/{attachment_id}/withhold"
)
def withhold_attachment_route(reference: str, attachment_id: int, request: Request):
    return _apply_attachment_lifecycle_action(
        reference=reference,
        attachment_id=attachment_id,
        request=request,
        action="withhold",
        event_type="attachment_withheld",
        redaction_status="withheld",
    )


@router.patch(
    "/api/admin/session/records/{reference}/attachments/{attachment_id}/restore"
)
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


@router.patch(
    "/api/admin/session/records/{reference}/attachments/{attachment_id}/soft-delete"
)
def soft_delete_attachment_route(reference: str, attachment_id: int, request: Request):
    return _apply_attachment_lifecycle_action(
        reference=reference,
        attachment_id=attachment_id,
        request=request,
        action="soft-delete",
        event_type="attachment_soft_deleted",
        is_deleted=1,
    )
