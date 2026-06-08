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

    for targets in groups.values():
        for target in targets:
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
        "document_date": attachment.get("document_date"),
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


def render_admin_record_evidence_page(
    *,
    reference: str,
    record_version: int,
    evidence_groups: dict[str, list[dict[str, Any]]],
) -> str:
    evidence_sections = _render_record_evidence_groups(evidence_groups)
    evidence_coverage = _render_record_evidence_coverage(evidence_groups)
    evidence_gap_summary = _render_record_evidence_gap_summary(evidence_groups)
    evidence_sufficiency = _render_record_evidence_sufficiency(evidence_groups)
    evidence_readiness = _render_record_evidence_readiness(evidence_groups)
    administrative_action = _render_administrative_action(evidence_groups)
    action_rationale = _render_action_rationale(evidence_groups)
    completion_requirements = _render_completion_requirements(evidence_groups)
    workflow_state = _render_workflow_state(evidence_groups)
    transition_conditions = _render_transition_conditions(evidence_groups)
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
    .transition-conditions-list {{
      margin: 8px 0 0 24px;
      padding: 0;
      line-height: 1.45;
    }}
    .action-rationale-list li,
    .completion-requirements-list li,
    .transition-conditions-list li {{
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
    {evidence_coverage}
    {evidence_gap_summary}
    {evidence_sufficiency}
    {evidence_readiness}
    {administrative_action}
    {action_rationale}
    {completion_requirements}
    {workflow_state}
    {transition_conditions}
    <section class="management-section record-evidence">
      <h2>Evidence by record target</h2>
      {evidence_sections}
    </section>
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
      No upload, edit, delete, restore, withhold, publish, correction, or download actions are available.
    </p>
    <section class="management-section record-summary">
      <h2>Record summary</h2>
      <p><strong>Record reference:</strong> {escape(reference)}</p>
      <p><strong>Record version:</strong> {record_version}</p>
      <p><a href="/admin/records/{escape(reference)}/evidence">View record evidence by target</a></p>
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
          <li>visibility workflow</li>
          <li>publication workflow</li>
        </ul>
      </div>
      <div class="capability-group">
        <h3>Planned</h3>
        <ul>
          <li>upload</li>
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
      <p>No upload, edit, delete, restore, withhold, publish, correction, or download actions are available.</p>
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
            "SELECT reference, version, conditions_json, signals_json, finding FROM records "
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
            "SELECT reference, version, conditions_json, signals_json, finding FROM records "
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
            content=render_admin_record_evidence_page(
                reference=record["reference"],
                record_version=record["version"],
                evidence_groups=_record_evidence_groups(record, attachments),
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
