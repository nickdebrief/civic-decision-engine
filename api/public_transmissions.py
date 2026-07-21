from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from api import archive_collections as ac
from api import record_document_associations as rda
from api.document_intake import (
    build_document_search_text,
    document_type_label,
    intake_root,
)

DB_PATH = Path(os.getenv("RECORDS_DB_PATH", "records.db"))

TRANSMISSION_REFERENCE_RE = re.compile(r"^TRM-\d{4}-\d{4,}$")
ATTACHMENT_REFERENCE_RE = re.compile(r"^TRM-ATT-\d{8}-\d{3,}$")

TRANSMISSION_METHODS: dict[str, str] = {
    "email": "Email",
    "letter": "Letter",
    "portal_upload": "Portal Upload",
    "secure_exchange": "Secure Exchange",
    "court_filing": "Court Filing",
    "publication": "Publication",
    "other": "Other",
}

TRANSMISSION_STATUSES: dict[str, str] = {
    "pending": "Pending Intake",
    "review": "Review",
    "approved": "Approved",
    "published": "Published",
    "archived": "Archived",
}

VALID_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"review", "archived"},
    "review": {"approved", "archived"},
    "approved": {"published", "archived"},
    "published": {"archived"},
    "archived": set(),
}

TRANSMISSION_MEMBER_TYPES: dict[str, str] = {
    "published_document": "Published Document",
    "canonical_record": "Canonical Record",
    "record_document_association": "Association",
    "public_collection": "Collection",
}

TRANSMISSION_ACTION_LABELS: dict[str, str] = {
    "created": "Created",
    "updated": "Updated",
    "status_changed": "Status changed",
    "attachment_added": "Included governed object",
    "attachment_removed": "Removed governed object",
}

PUBLIC_TRANSMISSION_PAGE_SIZE_OPTIONS = (10, 25, 50, 100)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    ensure_transmission_tables(conn)
    conn.commit()
    return conn


def ensure_transmission_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS public_transmissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            public_reference TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL,
            summary TEXT NOT NULL,
            sender TEXT NOT NULL,
            recipient TEXT NOT NULL,
            transmission_date TEXT NOT NULL,
            communication_method TEXT NOT NULL,
            subject TEXT,
            covering_message TEXT,
            public_visibility INTEGER NOT NULL DEFAULT 0,
            publication_status TEXT NOT NULL DEFAULT 'pending',
            external_reference TEXT,
            transmission_identifier TEXT,
            admin_notes TEXT,
            created_at TEXT NOT NULL,
            created_by TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            updated_by TEXT NOT NULL,
            published_at TEXT,
            published_by TEXT,
            archived_at TEXT,
            archived_by TEXT,
            archive_note TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS public_transmission_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            transmission_id INTEGER NOT NULL,
            action_type TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            actor TEXT NOT NULL,
            previous_state_json TEXT,
            new_state_json TEXT,
            note TEXT,
            FOREIGN KEY (transmission_id) REFERENCES public_transmissions(id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS public_transmission_attachments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            attachment_reference TEXT NOT NULL UNIQUE,
            transmission_id INTEGER NOT NULL,
            object_type TEXT NOT NULL,
            object_reference TEXT NOT NULL,
            relationship_label TEXT,
            public_note TEXT,
            position INTEGER,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            created_by TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            updated_by TEXT NOT NULL,
            removed_at TEXT,
            removed_by TEXT,
            removal_note TEXT,
            FOREIGN KEY (transmission_id) REFERENCES public_transmissions(id)
        )
        """
    )
    statements = (
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_public_transmissions_reference ON public_transmissions(public_reference)",
        "CREATE INDEX IF NOT EXISTS idx_public_transmissions_public ON public_transmissions(public_visibility, publication_status)",
        "CREATE INDEX IF NOT EXISTS idx_public_transmissions_date ON public_transmissions(transmission_date)",
        "CREATE INDEX IF NOT EXISTS idx_public_transmissions_method ON public_transmissions(communication_method)",
        "CREATE INDEX IF NOT EXISTS idx_public_transmission_history_transmission ON public_transmission_history(transmission_id)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_public_transmission_attachments_reference ON public_transmission_attachments(attachment_reference)",
        "CREATE INDEX IF NOT EXISTS idx_public_transmission_attachments_transmission ON public_transmission_attachments(transmission_id)",
        "CREATE INDEX IF NOT EXISTS idx_public_transmission_attachments_object ON public_transmission_attachments(object_type, object_reference)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_public_transmission_attachments_active_unique ON public_transmission_attachments(transmission_id, object_type, object_reference) WHERE is_active = 1",
    )
    for statement in statements:
        conn.execute(statement)


def _clean_required(value: Any, error: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        raise ValueError(error)
    return cleaned


def _clean_optional(value: Any) -> str | None:
    cleaned = str(value or "").strip()
    return cleaned or None


def _validate_iso_date(value: Any, error: str) -> str:
    cleaned = _clean_required(value, error)
    try:
        datetime.strptime(cleaned, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError(error) from exc
    return cleaned


def validate_public_reference(value: Any) -> str:
    reference = str(value or "").strip()
    if not TRANSMISSION_REFERENCE_RE.fullmatch(reference):
        raise ValueError("transmission_reference_invalid")
    return reference


def validate_attachment_reference(value: Any) -> str:
    reference = str(value or "").strip()
    if not ATTACHMENT_REFERENCE_RE.fullmatch(reference):
        raise ValueError("transmission_attachment_reference_invalid")
    return reference


def validate_method(value: Any) -> str:
    method = str(value or "").strip()
    if method not in TRANSMISSION_METHODS:
        raise ValueError("transmission_method_invalid")
    return method


def validate_status(value: Any) -> str:
    status = str(value or "").strip()
    if status not in TRANSMISSION_STATUSES:
        raise ValueError("transmission_status_invalid")
    return status


def normalize_bool(value: Any, *, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on", "public", "visible"}


def method_label(value: Any) -> str:
    return TRANSMISSION_METHODS.get(str(value or ""), str(value or "") or "—")


def status_label(value: Any) -> str:
    return TRANSMISSION_STATUSES.get(str(value or ""), str(value or "") or "—")


def normalize_object_type(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    aliases = {
        "document": "published_document",
        "published_document": "published_document",
        "record": "canonical_record",
        "canonical_record": "canonical_record",
        "association": "record_document_association",
        "record_document_association": "record_document_association",
        "collection": "public_collection",
        "public_collection": "public_collection",
        "transmission": "public_transmission",
        "public_transmission": "public_transmission",
    }
    resolved = aliases.get(normalized)
    if resolved == "public_transmission":
        raise ValueError("transmission_self_attachment_unsupported")
    if resolved not in TRANSMISSION_MEMBER_TYPES:
        raise ValueError("transmission_object_type_unsupported")
    return resolved


def object_type_label(value: Any) -> str:
    try:
        return TRANSMISSION_MEMBER_TYPES[normalize_object_type(value)]
    except ValueError:
        return "Unsupported object type"


def _reference_year(timestamp: str | None = None) -> str:
    raw = str(timestamp or utc_now())[:4]
    return raw if len(raw) == 4 and raw.isdigit() else utc_now()[:4]


def generate_public_reference(conn: sqlite3.Connection, timestamp: str | None = None) -> str:
    ensure_transmission_tables(conn)
    year = _reference_year(timestamp)
    prefix = f"TRM-{year}-"
    rows = conn.execute(
        "SELECT public_reference FROM public_transmissions WHERE public_reference LIKE ?",
        (prefix + "%",),
    ).fetchall()
    highest = 0
    for row in rows:
        value = str(row[0] or "")
        try:
            highest = max(highest, int(value.rsplit("-", 1)[1]))
        except (IndexError, ValueError):
            continue
    return f"{prefix}{highest + 1:04d}"


def generate_attachment_reference(conn: sqlite3.Connection, timestamp: str | None = None) -> str:
    ensure_transmission_tables(conn)
    raw = str(timestamp or utc_now())[:10].replace("-", "")
    date_part = raw if len(raw) == 8 and raw.isdigit() else utc_now()[:10].replace("-", "")
    prefix = f"TRM-ATT-{date_part}-"
    rows = conn.execute(
        "SELECT attachment_reference FROM public_transmission_attachments WHERE attachment_reference LIKE ?",
        (prefix + "%",),
    ).fetchall()
    highest = 0
    for row in rows:
        value = str(row[0] or "")
        try:
            highest = max(highest, int(value.rsplit("-", 1)[1]))
        except (IndexError, ValueError):
            continue
    return f"{prefix}{highest + 1:03d}"


def _transmission_state(row: sqlite3.Row | dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    data = dict(row)
    return {
        "id": data.get("id"),
        "public_reference": data.get("public_reference"),
        "title": data.get("title"),
        "summary": data.get("summary"),
        "sender": data.get("sender"),
        "recipient": data.get("recipient"),
        "transmission_date": data.get("transmission_date"),
        "communication_method": data.get("communication_method"),
        "subject": data.get("subject"),
        "covering_message": data.get("covering_message"),
        "public_visibility": int(data.get("public_visibility") or 0),
        "publication_status": data.get("publication_status"),
        "external_reference": data.get("external_reference"),
        "transmission_identifier": data.get("transmission_identifier"),
        "created_at": data.get("created_at"),
        "created_by": data.get("created_by"),
        "updated_at": data.get("updated_at"),
        "updated_by": data.get("updated_by"),
        "published_at": data.get("published_at"),
        "published_by": data.get("published_by"),
        "archived_at": data.get("archived_at"),
        "archived_by": data.get("archived_by"),
    }


def _attachment_state(row: sqlite3.Row | dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    data = dict(row)
    return {
        "id": data.get("id"),
        "attachment_reference": data.get("attachment_reference"),
        "transmission_id": data.get("transmission_id"),
        "object_type": data.get("object_type"),
        "object_reference": data.get("object_reference"),
        "relationship_label": data.get("relationship_label"),
        "public_note": data.get("public_note"),
        "position": data.get("position"),
        "is_active": int(data.get("is_active") or 0),
        "created_at": data.get("created_at"),
        "created_by": data.get("created_by"),
        "updated_at": data.get("updated_at"),
        "updated_by": data.get("updated_by"),
        "removed_at": data.get("removed_at"),
        "removed_by": data.get("removed_by"),
    }


def _record_history(
    conn: sqlite3.Connection,
    *,
    transmission_id: int,
    action_type: str,
    actor: str,
    timestamp: str,
    previous_state: dict[str, Any] | None,
    new_state: dict[str, Any] | None,
    note: str | None,
) -> None:
    conn.execute(
        """
        INSERT INTO public_transmission_history (
            transmission_id, action_type, timestamp, actor,
            previous_state_json, new_state_json, note
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            int(transmission_id),
            action_type,
            timestamp,
            actor,
            json.dumps(previous_state, sort_keys=True) if previous_state is not None else None,
            json.dumps(new_state, sort_keys=True) if new_state is not None else None,
            _clean_optional(note),
        ),
    )


def get_transmission(conn: sqlite3.Connection, transmission_id: int | str) -> dict[str, Any]:
    ensure_transmission_tables(conn)
    row = conn.execute("SELECT * FROM public_transmissions WHERE id = ?", (int(transmission_id),)).fetchone()
    if not row:
        raise ValueError("transmission_not_found")
    return dict(row)


def get_transmission_by_reference(conn: sqlite3.Connection, public_reference: Any) -> dict[str, Any]:
    ensure_transmission_tables(conn)
    reference = validate_public_reference(public_reference)
    row = conn.execute("SELECT * FROM public_transmissions WHERE public_reference = ?", (reference,)).fetchone()
    if not row:
        raise ValueError("transmission_not_found")
    return dict(row)


def public_transmission_is_eligible(row: dict[str, Any]) -> bool:
    return int(row.get("public_visibility") or 0) == 1 and row.get("publication_status") == "published"


def get_public_transmission(conn: sqlite3.Connection, public_reference: Any) -> dict[str, Any]:
    transmission = get_transmission_by_reference(conn, public_reference)
    if not public_transmission_is_eligible(transmission):
        raise ValueError("public_transmission_not_found")
    return transmission


def transmission_history(conn: sqlite3.Connection, transmission_id: int | str) -> list[dict[str, Any]]:
    ensure_transmission_tables(conn)
    rows = conn.execute(
        """
        SELECT * FROM public_transmission_history
        WHERE transmission_id = ?
        ORDER BY timestamp ASC, id ASC
        """,
        (int(transmission_id),),
    ).fetchall()
    return [dict(row) for row in rows]


def create_transmission(
    conn: sqlite3.Connection,
    *,
    title: Any,
    summary: Any,
    sender: Any,
    recipient: Any,
    transmission_date: Any,
    communication_method: Any,
    subject: Any = None,
    covering_message: Any = None,
    public_visibility: Any = False,
    publication_status: Any = "pending",
    external_reference: Any = None,
    transmission_identifier: Any = None,
    admin_notes: Any = None,
    actor: Any,
    created_at: str | None = None,
) -> dict[str, Any]:
    ensure_transmission_tables(conn)
    actor_value = _clean_required(actor, "transmission_actor_required")
    status = validate_status(publication_status)
    method = validate_method(communication_method)
    timestamp = created_at or utc_now()
    published_at = timestamp if status == "published" else None
    public_reference = generate_public_reference(conn, timestamp)
    cursor = conn.execute(
        """
        INSERT INTO public_transmissions (
            public_reference, title, summary, sender, recipient, transmission_date,
            communication_method, subject, covering_message, public_visibility,
            publication_status, external_reference, transmission_identifier, admin_notes,
            created_at, created_by, updated_at, updated_by, published_at, published_by
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            public_reference,
            _clean_required(title, "transmission_title_required"),
            _clean_required(summary, "transmission_summary_required"),
            _clean_required(sender, "transmission_sender_required"),
            _clean_required(recipient, "transmission_recipient_required"),
            _validate_iso_date(transmission_date, "transmission_date_invalid"),
            method,
            _clean_optional(subject),
            _clean_optional(covering_message),
            1 if normalize_bool(public_visibility, default=False) else 0,
            status,
            _clean_optional(external_reference),
            _clean_optional(transmission_identifier),
            _clean_optional(admin_notes),
            timestamp,
            actor_value,
            timestamp,
            actor_value,
            published_at,
            actor_value if published_at else None,
        ),
    )
    transmission_id = int(cursor.lastrowid)
    row = get_transmission(conn, transmission_id)
    _record_history(
        conn,
        transmission_id=transmission_id,
        action_type="created",
        actor=actor_value,
        timestamp=timestamp,
        previous_state=None,
        new_state=_transmission_state(row),
        note=admin_notes or "Transmission created.",
    )
    conn.commit()
    return row


def update_transmission_status(
    conn: sqlite3.Connection,
    transmission_id: int | str,
    *,
    new_status: Any,
    public_visibility: Any | None = None,
    actor: Any,
    note: Any = None,
    updated_at: str | None = None,
) -> dict[str, Any]:
    ensure_transmission_tables(conn)
    actor_value = _clean_required(actor, "transmission_actor_required")
    previous = get_transmission(conn, transmission_id)
    current_status = validate_status(previous.get("publication_status"))
    next_status = validate_status(new_status)
    if next_status != current_status and next_status not in VALID_STATUS_TRANSITIONS[current_status]:
        raise ValueError("transmission_status_transition_invalid")
    timestamp = updated_at or utc_now()
    if public_visibility is None:
        public_flag = int(previous.get("public_visibility") or 0)
    else:
        public_flag = 1 if normalize_bool(public_visibility, default=bool(previous.get("public_visibility"))) else 0
    published_at = previous.get("published_at")
    published_by = previous.get("published_by")
    archived_at = previous.get("archived_at")
    archived_by = previous.get("archived_by")
    if next_status == "published" and not published_at:
        published_at = timestamp
        published_by = actor_value
    if next_status == "archived" and not archived_at:
        archived_at = timestamp
        archived_by = actor_value
    conn.execute(
        """
        UPDATE public_transmissions
        SET publication_status = ?, public_visibility = ?, updated_at = ?, updated_by = ?,
            published_at = ?, published_by = ?, archived_at = ?, archived_by = ?, archive_note = ?
        WHERE id = ?
        """,
        (
            next_status,
            public_flag,
            timestamp,
            actor_value,
            published_at,
            published_by,
            archived_at,
            archived_by,
            _clean_optional(note) if next_status == "archived" else previous.get("archive_note"),
            int(transmission_id),
        ),
    )
    row = get_transmission(conn, transmission_id)
    _record_history(
        conn,
        transmission_id=int(transmission_id),
        action_type="status_changed",
        actor=actor_value,
        timestamp=timestamp,
        previous_state=_transmission_state(previous),
        new_state=_transmission_state(row),
        note=note or f"Transmission status changed to {status_label(next_status)}.",
    )
    conn.commit()
    return row


def resolve_public_object(
    conn: sqlite3.Connection,
    object_type: Any,
    object_reference: Any,
    *,
    root: Path | None = None,
) -> dict[str, Any] | None:
    normalized_type = normalize_object_type(object_type)
    reference = _clean_required(object_reference, "transmission_object_reference_required")
    if normalized_type == "published_document":
        document = rda.published_document_context(reference, root=root)
        if not document:
            return None
        public_reference = str(document.get("document_identifier") or document.get("reference_identifier") or document.get("intake_id") or reference)
        return {
            "object_type": normalized_type,
            "object_type_label": TRANSMISSION_MEMBER_TYPES[normalized_type],
            "object_reference": str(document.get("intake_id") or reference),
            "object_public_reference": public_reference,
            "object_secondary_reference": document.get("reference_identifier"),
            "object_title": str(document.get("title") or public_reference),
            "object_summary": document.get("description"),
            "object_status_label": "Published",
            "object_format": document_type_label(document.get("document_type")),
            "object_date": document.get("publication_date") or document.get("document_date"),
            "object_url": f"/documents/{document.get('intake_id') or reference}",
            "search_text": build_document_search_text(document),
            "document": document,
        }
    if normalized_type == "canonical_record":
        record = rda.public_record_context(conn, reference)
        if not record:
            return None
        record_reference = str(record.get("reference") or reference)
        title = str(record.get("title") or record.get("record_title") or record.get("public_title") or record.get("finding") or record_reference)
        return {
            "object_type": normalized_type,
            "object_type_label": TRANSMISSION_MEMBER_TYPES[normalized_type],
            "object_reference": record_reference,
            "object_public_reference": record_reference,
            "object_title": title,
            "object_summary": record.get("summary") or record.get("public_summary") or record.get("finding"),
            "object_status_label": "Published",
            "object_format": str(record.get("record_type") or "strike"),
            "object_date": record.get("exported_at") or record.get("generated_at"),
            "object_url": f"/verify/{record_reference}",
            "search_text": " ".join(str(value or "") for value in record.values()),
            "record": record,
        }
    if normalized_type == "record_document_association":
        association = rda.get_public_association(conn, reference, root=root)
        public_reference = str(association.get("public_reference") or reference)
        relationship_label = rda.RELATIONSHIP_TYPES.get(
            str(association.get("relationship_type") or ""),
            str(association.get("relationship_type") or "Association"),
        )
        title = str(association.get("public_label") or relationship_label or public_reference)
        return {
            "object_type": normalized_type,
            "object_type_label": TRANSMISSION_MEMBER_TYPES[normalized_type],
            "object_reference": public_reference,
            "object_public_reference": public_reference,
            "object_title": title,
            "object_summary": association.get("public_note"),
            "object_status_label": "Active public association",
            "object_format": relationship_label,
            "object_date": association.get("created_at"),
            "object_url": f"/associations/{public_reference}",
            "search_text": " ".join(str(value or "") for value in association.values()),
            "association": association,
        }
    collection = ac.get_public_collection(conn, reference)
    public_reference = str(collection.get("public_reference") or reference)
    return {
        "object_type": normalized_type,
        "object_type_label": TRANSMISSION_MEMBER_TYPES[normalized_type],
        "object_reference": public_reference,
        "object_public_reference": public_reference,
        "object_title": str(collection.get("title") or public_reference),
        "object_summary": collection.get("description"),
        "object_status_label": "Published",
        "object_format": ac.category_label(collection.get("category")),
        "object_date": collection.get("created_at"),
        "object_url": f"/collections/{public_reference}",
        "search_text": " ".join(str(value or "") for value in collection.values()),
        "collection": collection,
    }


def add_transmission_attachment(
    conn: sqlite3.Connection,
    *,
    transmission_id: int | str,
    object_type: Any,
    object_reference: Any,
    relationship_label: Any = None,
    public_note: Any = None,
    position: Any = None,
    actor: Any,
    created_at: str | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    ensure_transmission_tables(conn)
    actor_value = _clean_required(actor, "transmission_actor_required")
    transmission = get_transmission(conn, transmission_id)
    normalized_type = normalize_object_type(object_type)
    resolved = resolve_public_object(conn, normalized_type, object_reference, root=root)
    if not resolved:
        raise ValueError("transmission_object_not_public")
    normalized_reference = str(resolved["object_reference"])
    existing = conn.execute(
        """
        SELECT id FROM public_transmission_attachments
        WHERE transmission_id = ? AND object_type = ? AND object_reference = ? AND is_active = 1
        LIMIT 1
        """,
        (int(transmission_id), normalized_type, normalized_reference),
    ).fetchone()
    if existing:
        raise ValueError("transmission_attachment_duplicate_active")
    if position in (None, ""):
        next_position = (
            conn.execute(
                "SELECT COALESCE(MAX(position), 0) + 1 FROM public_transmission_attachments WHERE transmission_id = ?",
                (int(transmission_id),),
            ).fetchone()[0]
            or 1
        )
    else:
        try:
            next_position = int(str(position))
        except ValueError as exc:
            raise ValueError("transmission_attachment_position_invalid") from exc
        if next_position <= 0:
            raise ValueError("transmission_attachment_position_invalid")
    timestamp = created_at or utc_now()
    cursor = conn.execute(
        """
        INSERT INTO public_transmission_attachments (
            attachment_reference, transmission_id, object_type, object_reference,
            relationship_label, public_note, position, is_active,
            created_at, created_by, updated_at, updated_by
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
        """,
        (
            generate_attachment_reference(conn, timestamp),
            int(transmission_id),
            normalized_type,
            normalized_reference,
            _clean_optional(relationship_label) or f"Transmitted {TRANSMISSION_MEMBER_TYPES[normalized_type]}",
            _clean_optional(public_note),
            next_position,
            timestamp,
            actor_value,
            timestamp,
            actor_value,
        ),
    )
    attachment_id = int(cursor.lastrowid)
    row = get_transmission_attachment(conn, attachment_id)
    _record_history(
        conn,
        transmission_id=int(transmission["id"]),
        action_type="attachment_added",
        actor=actor_value,
        timestamp=timestamp,
        previous_state=None,
        new_state=_attachment_state(row),
        note=public_note or relationship_label or "Transmission attachment added.",
    )
    conn.commit()
    return enrich_attachment(conn, row, root=root)


def get_transmission_attachment(conn: sqlite3.Connection, attachment_id: int | str) -> dict[str, Any]:
    ensure_transmission_tables(conn)
    row = conn.execute(
        "SELECT * FROM public_transmission_attachments WHERE id = ?",
        (int(attachment_id),),
    ).fetchone()
    if not row:
        raise ValueError("transmission_attachment_not_found")
    return dict(row)


def enrich_attachment(
    conn: sqlite3.Connection,
    attachment: dict[str, Any],
    *,
    root: Path | None = None,
) -> dict[str, Any]:
    item = dict(attachment)
    public_object = None
    try:
        public_object = resolve_public_object(conn, item.get("object_type"), item.get("object_reference"), root=root)
    except ValueError:
        public_object = None
    item["object_type_label"] = object_type_label(item.get("object_type"))
    item["object_public_reference"] = item.get("object_reference")
    item["object_title"] = item.get("object_reference")
    item["object_summary"] = None
    item["object_status_label"] = "Not publicly available"
    item["object_format"] = "—"
    item["object_date"] = None
    item["object_url"] = ""
    item["object_publicly_eligible"] = False
    if public_object:
        for key, value in public_object.items():
            if key not in {"document", "record", "association", "collection", "search_text"}:
                item[key] = value
        item["object_publicly_eligible"] = True
        item["object_search_text"] = public_object.get("search_text") or ""
    return item


def list_transmission_attachments(
    conn: sqlite3.Connection,
    transmission_id: int | str,
    *,
    public_only: bool = False,
    root: Path | None = None,
) -> list[dict[str, Any]]:
    ensure_transmission_tables(conn)
    rows = [
        dict(row)
        for row in conn.execute(
            """
            SELECT * FROM public_transmission_attachments
            WHERE transmission_id = ?
            ORDER BY
              CASE WHEN position IS NULL THEN 1 ELSE 0 END ASC,
              position ASC,
              created_at ASC,
              attachment_reference ASC
            """,
            (int(transmission_id),),
        ).fetchall()
    ]
    enriched = [enrich_attachment(conn, row, root=root) for row in rows]
    if public_only:
        enriched = [
            item
            for item in enriched
            if int(item.get("is_active") or 0) == 1 and item.get("object_publicly_eligible")
        ]
    return enriched


def _parse_positive_int(value: Any, default: int, *, maximum: int | None = None) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    if parsed < 1:
        parsed = default
    if maximum is not None and parsed > maximum:
        return maximum
    return parsed


def _normalize_page_size(value: Any) -> int:
    parsed = _parse_positive_int(value, 25, maximum=100)
    return parsed if parsed in PUBLIC_TRANSMISSION_PAGE_SIZE_OPTIONS else 25


def _public_projection(conn: sqlite3.Connection, row: dict[str, Any], *, root: Path | None = None) -> dict[str, Any]:
    attachments = list_transmission_attachments(conn, int(row["id"]), public_only=True, root=root)
    attached_references = " ".join(str(item.get("object_public_reference") or item.get("object_reference") or "") for item in attachments)
    attached_titles = " ".join(str(item.get("object_title") or "") for item in attachments)
    search_text = " ".join(
        str(value or "")
        for value in (
            row.get("public_reference"),
            row.get("title"),
            row.get("summary"),
            row.get("sender"),
            row.get("recipient"),
            row.get("transmission_date"),
            method_label(row.get("communication_method")),
            row.get("subject"),
            row.get("covering_message"),
            row.get("external_reference"),
            row.get("transmission_identifier"),
            attached_references,
            attached_titles,
            " ".join(str(item.get("object_search_text") or "") for item in attachments),
        )
    ).casefold()
    return {
        "id": row.get("id"),
        "public_reference": row.get("public_reference"),
        "title": row.get("title"),
        "summary": row.get("summary"),
        "sender": row.get("sender"),
        "recipient": row.get("recipient"),
        "transmission_date": row.get("transmission_date"),
        "communication_method": row.get("communication_method"),
        "communication_method_label": method_label(row.get("communication_method")),
        "subject": row.get("subject"),
        "covering_message": row.get("covering_message"),
        "publication_status": row.get("publication_status"),
        "publication_status_label": status_label(row.get("publication_status")),
        "published_at": row.get("published_at"),
        "created_at": row.get("created_at"),
        "external_reference": row.get("external_reference"),
        "transmission_identifier": row.get("transmission_identifier"),
        "attached_object_count": len(attachments),
        "attached_references": attached_references,
        "search_text": search_text,
    }


def public_transmission_index_options(rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    return {
        "senders": sorted({str(row.get("sender") or "") for row in rows if row.get("sender")}, key=str.casefold),
        "recipients": sorted({str(row.get("recipient") or "") for row in rows if row.get("recipient")}, key=str.casefold),
        "methods": sorted({str(row.get("communication_method") or "") for row in rows if row.get("communication_method")}),
        "years": sorted({str(row.get("published_at") or row.get("transmission_date") or "")[:4] for row in rows if str(row.get("published_at") or row.get("transmission_date") or "")[:4].isdigit()}, reverse=True),
    }


def _matches_public_filters(row: dict[str, Any], filters: dict[str, str]) -> bool:
    tokens = [token.casefold() for token in filters["q"].split() if token.strip()]
    if tokens and not all(token in str(row.get("search_text") or "") for token in tokens):
        return False
    if filters["sender"] and filters["sender"].casefold() not in str(row.get("sender") or "").casefold():
        return False
    if filters["recipient"] and filters["recipient"].casefold() not in str(row.get("recipient") or "").casefold():
        return False
    if filters["method"] and filters["method"] != row.get("communication_method"):
        return False
    if filters["year"]:
        year_basis = str(row.get("published_at") or row.get("transmission_date") or "")[:4]
        if year_basis != filters["year"]:
            return False
    return True


def list_public_transmission_index(
    conn: sqlite3.Connection,
    *,
    q: Any = "",
    sender: Any = "",
    recipient: Any = "",
    method: Any = "",
    year: Any = "",
    page: Any = 1,
    page_size: Any = 25,
    root: Path | None = None,
) -> dict[str, Any]:
    ensure_transmission_tables(conn)
    normalized_method = str(method or "").strip()
    normalized_method = normalized_method if normalized_method in TRANSMISSION_METHODS else ""
    raw_year = str(year or "").strip()
    normalized_year = raw_year if len(raw_year) == 4 and raw_year.isdigit() else ""
    filters = {
        "q": str(q or "").strip(),
        "sender": str(sender or "").strip(),
        "recipient": str(recipient or "").strip(),
        "method": normalized_method,
        "year": normalized_year,
    }
    rows = [
        _public_projection(conn, dict(row), root=root)
        for row in conn.execute(
            """
            SELECT * FROM public_transmissions
            WHERE public_visibility = 1 AND publication_status = 'published'
            ORDER BY COALESCE(published_at, transmission_date) DESC, public_reference DESC
            """
        ).fetchall()
    ]
    options = public_transmission_index_options(rows)
    filtered = [row for row in rows if _matches_public_filters(row, filters)]
    filtered.sort(
        key=lambda row: (
            str(row.get("published_at") or row.get("transmission_date") or ""),
            str(row.get("public_reference") or ""),
        ),
        reverse=True,
    )
    normalized_page_size = _normalize_page_size(page_size)
    total = len(filtered)
    page_count = max(1, (total + normalized_page_size - 1) // normalized_page_size)
    normalized_page = min(_parse_positive_int(page, 1), page_count)
    start = (normalized_page - 1) * normalized_page_size
    return {
        "rows": filtered[start : start + normalized_page_size],
        "total": total,
        "page": normalized_page,
        "page_size": normalized_page_size,
        "page_count": page_count,
        "filters": filters,
        "options": options,
    }


def list_transmissions(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    ensure_transmission_tables(conn)
    return [
        dict(row)
        for row in conn.execute(
            """
            SELECT * FROM public_transmissions
            ORDER BY created_at DESC, id DESC
            """
        ).fetchall()
    ]


def public_transmission_history(conn: sqlite3.Connection, transmission_id: int | str) -> list[dict[str, Any]]:
    events = transmission_history(conn, transmission_id)
    projected: list[dict[str, Any]] = []
    for event in events:
        action_type = str(event.get("action_type") or "")
        note = event.get("note")
        if action_type == "created":
            note = "Transmission created."
        elif action_type == "status_changed":
            note = f"Transmission lifecycle recorded as public-safe status: {status_label(_decode_new_status(event))}."
        projected.append(
            {
                "timestamp": event.get("timestamp"),
                "action_type": action_type,
                "action_label": TRANSMISSION_ACTION_LABELS.get(action_type, action_type or "Transmission event"),
                "actor": event.get("actor"),
                "note": note,
            }
        )
    return projected


def _decode_new_status(event: dict[str, Any]) -> str:
    raw = event.get("new_state_json")
    if not raw:
        return ""
    try:
        decoded = json.loads(str(raw))
    except json.JSONDecodeError:
        return ""
    if not isinstance(decoded, dict):
        return ""
    return str(decoded.get("publication_status") or "")
