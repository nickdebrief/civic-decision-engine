from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DB_PATH = Path(os.getenv("RECORDS_DB_PATH", "records.db"))

COLLECTION_CATEGORIES: dict[str, str] = {
    "public_accountability_archive": "Public Accountability Archive",
    "framework_publications": "Framework Publications",
    "professional_records": "Professional Records",
    "evidence_audits": "Evidence Audits",
    "research_archive": "Research Archive",
    "procedural_archive": "Procedural Archive",
    "documentary_archive": "Documentary Archive",
    "other_governed_collection": "Other Governed Collection",
}

PUBLIC_REFERENCE_RE = re.compile(r"^CDE-COLL-\d{8}-\d{3,}$")
PUBLIC_COLLECTION_PAGE_SIZE_OPTIONS = (10, 25, 50, 100)

COLLECTION_ACTION_LABELS = {
    "created": "Created",
    "updated": "Updated",
    "visibility_changed": "Visibility changed",
    "deactivated": "Deactivated",
    "reactivated": "Reactivated",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    ensure_collection_tables(conn)
    conn.commit()
    return conn


def ensure_collection_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS archive_collections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            public_reference TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL,
            subtitle TEXT,
            institution_source TEXT NOT NULL,
            category TEXT NOT NULL,
            description TEXT NOT NULL,
            public_note TEXT,
            admin_note TEXT,
            date_from TEXT,
            date_to TEXT,
            is_active INTEGER NOT NULL DEFAULT 1,
            is_public INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            created_by TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            updated_by TEXT NOT NULL,
            deactivated_at TEXT,
            deactivated_by TEXT,
            deactivation_note TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS archive_collection_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            collection_id INTEGER NOT NULL,
            action_type TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            actor TEXT NOT NULL,
            previous_state_json TEXT,
            new_state_json TEXT,
            note TEXT,
            FOREIGN KEY (collection_id) REFERENCES archive_collections(id)
        )
        """
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_archive_collections_public_reference
        ON archive_collections(public_reference)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_archive_collections_active_public
        ON archive_collections(is_active, is_public)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_archive_collections_category
        ON archive_collections(category)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_archive_collections_created_at
        ON archive_collections(created_at)
        """
    )


def _reference_date(timestamp: str | None) -> str:
    raw = str(timestamp or utc_now())[:10]
    digits = raw.replace("-", "")
    return digits if len(digits) == 8 and digits.isdigit() else utc_now()[:10].replace("-", "")


def generate_public_reference(conn: sqlite3.Connection, timestamp: str | None = None) -> str:
    date_part = _reference_date(timestamp)
    prefix = f"CDE-COLL-{date_part}-"
    rows = conn.execute(
        "SELECT public_reference FROM archive_collections WHERE public_reference LIKE ?",
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


def validate_public_reference(value: str) -> str:
    reference = str(value or "").strip()
    if not PUBLIC_REFERENCE_RE.fullmatch(reference):
        raise ValueError("collection_public_reference_invalid")
    return reference


def validate_category(value: str) -> str:
    normalized = str(value or "").strip()
    if normalized not in COLLECTION_CATEGORIES:
        raise ValueError("collection_category_invalid")
    return normalized


def category_label(value: str | None) -> str:
    return COLLECTION_CATEGORIES.get(str(value or ""), str(value or "") or "—")


def normalize_bool(value: Any, *, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on", "public", "visible"}


def _clean_required(value: Any, error: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        raise ValueError(error)
    return cleaned


def _clean_optional(value: Any) -> str | None:
    cleaned = str(value or "").strip()
    return cleaned or None


def _validate_iso_date(value: Any, field: str) -> str | None:
    cleaned = str(value or "").strip()
    if not cleaned:
        return None
    try:
        datetime.strptime(cleaned, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError(f"collection_{field}_invalid") from exc
    return cleaned


def validate_date_range(date_from: Any, date_to: Any) -> tuple[str | None, str | None]:
    start = _validate_iso_date(date_from, "date_from")
    end = _validate_iso_date(date_to, "date_to")
    if start and end and start > end:
        raise ValueError("collection_date_range_invalid")
    return start, end


def _collection_state(row: sqlite3.Row | dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    data = dict(row)
    return {
        "id": data.get("id"),
        "public_reference": data.get("public_reference"),
        "title": data.get("title"),
        "subtitle": data.get("subtitle"),
        "institution_source": data.get("institution_source"),
        "category": data.get("category"),
        "description": data.get("description"),
        "public_note": data.get("public_note"),
        "admin_note": data.get("admin_note"),
        "date_from": data.get("date_from"),
        "date_to": data.get("date_to"),
        "is_active": int(data.get("is_active") or 0),
        "is_public": int(data.get("is_public") or 0),
        "created_at": data.get("created_at"),
        "created_by": data.get("created_by"),
        "updated_at": data.get("updated_at"),
        "updated_by": data.get("updated_by"),
        "deactivated_at": data.get("deactivated_at"),
        "deactivated_by": data.get("deactivated_by"),
        "deactivation_note": data.get("deactivation_note"),
    }


def _record_history(
    conn: sqlite3.Connection,
    *,
    collection_id: int,
    action_type: str,
    actor: str,
    timestamp: str,
    previous_state: dict[str, Any] | None,
    new_state: dict[str, Any] | None,
    note: str | None,
) -> None:
    conn.execute(
        """
        INSERT INTO archive_collection_history (
            collection_id, action_type, timestamp, actor,
            previous_state_json, new_state_json, note
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            collection_id,
            action_type,
            timestamp,
            str(actor or "").strip(),
            json.dumps(previous_state, sort_keys=True) if previous_state is not None else None,
            json.dumps(new_state, sort_keys=True) if new_state is not None else None,
            str(note or "").strip() or None,
        ),
    )


def get_collection(conn: sqlite3.Connection, collection_id: int | str) -> dict[str, Any]:
    ensure_collection_tables(conn)
    row = conn.execute("SELECT * FROM archive_collections WHERE id = ?", (int(collection_id),)).fetchone()
    if not row:
        raise ValueError("collection_not_found")
    return dict(row)


def collection_history(conn: sqlite3.Connection, collection_id: int | str) -> list[dict[str, Any]]:
    ensure_collection_tables(conn)
    rows = conn.execute(
        """
        SELECT * FROM archive_collection_history
        WHERE collection_id = ?
        ORDER BY timestamp ASC, id ASC
        """,
        (int(collection_id),),
    ).fetchall()
    return [dict(row) for row in rows]


def public_collection_is_eligible(collection: dict[str, Any]) -> bool:
    return (
        int(collection.get("is_active") or 0) == 1
        and int(collection.get("is_public") or 0) == 1
        and bool(str(collection.get("public_reference") or "").strip())
    )


def create_collection(
    conn: sqlite3.Connection,
    *,
    title: str,
    institution_source: str,
    category: str,
    description: str,
    actor: str,
    subtitle: str | None = None,
    public_note: str | None = None,
    admin_note: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    is_public: Any = False,
    created_at: str | None = None,
) -> dict[str, Any]:
    ensure_collection_tables(conn)
    actor_value = _clean_required(actor, "collection_actor_required")
    timestamp = created_at or utc_now()
    start, end = validate_date_range(date_from, date_to)
    row_values = {
        "public_reference": generate_public_reference(conn, timestamp),
        "title": _clean_required(title, "collection_title_required"),
        "subtitle": _clean_optional(subtitle),
        "institution_source": _clean_required(institution_source, "collection_institution_source_required"),
        "category": validate_category(category),
        "description": _clean_required(description, "collection_description_required"),
        "public_note": _clean_optional(public_note),
        "admin_note": _clean_optional(admin_note),
        "date_from": start,
        "date_to": end,
        "is_public": 1 if normalize_bool(is_public, default=False) else 0,
        "created_at": timestamp,
        "created_by": actor_value,
        "updated_at": timestamp,
        "updated_by": actor_value,
    }
    cursor = conn.execute(
        """
        INSERT INTO archive_collections (
            public_reference, title, subtitle, institution_source, category,
            description, public_note, admin_note, date_from, date_to,
            is_active, is_public, created_at, created_by, updated_at, updated_by
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?)
        """,
        (
            row_values["public_reference"],
            row_values["title"],
            row_values["subtitle"],
            row_values["institution_source"],
            row_values["category"],
            row_values["description"],
            row_values["public_note"],
            row_values["admin_note"],
            row_values["date_from"],
            row_values["date_to"],
            row_values["is_public"],
            row_values["created_at"],
            row_values["created_by"],
            row_values["updated_at"],
            row_values["updated_by"],
        ),
    )
    collection_id = int(cursor.lastrowid)
    row = get_collection(conn, collection_id)
    _record_history(
        conn,
        collection_id=collection_id,
        action_type="created",
        actor=actor_value,
        timestamp=timestamp,
        previous_state=None,
        new_state=_collection_state(row),
        note=admin_note or public_note or "Collection created.",
    )
    conn.commit()
    return row


def update_collection(
    conn: sqlite3.Connection,
    collection_id: int | str,
    *,
    title: str,
    institution_source: str,
    category: str,
    description: str,
    actor: str,
    subtitle: str | None = None,
    public_note: str | None = None,
    admin_note: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    is_public: Any = False,
    updated_at: str | None = None,
) -> dict[str, Any]:
    ensure_collection_tables(conn)
    actor_value = _clean_required(actor, "collection_actor_required")
    previous = get_collection(conn, collection_id)
    start, end = validate_date_range(date_from, date_to)
    public_flag = 1 if normalize_bool(is_public, default=False) else 0
    timestamp = updated_at or utc_now()
    action_type = "visibility_changed" if int(previous.get("is_public") or 0) != public_flag else "updated"
    conn.execute(
        """
        UPDATE archive_collections
        SET title = ?, subtitle = ?, institution_source = ?, category = ?,
            description = ?, public_note = ?, admin_note = ?, date_from = ?,
            date_to = ?, is_public = ?, updated_at = ?, updated_by = ?
        WHERE id = ?
        """,
        (
            _clean_required(title, "collection_title_required"),
            _clean_optional(subtitle),
            _clean_required(institution_source, "collection_institution_source_required"),
            validate_category(category),
            _clean_required(description, "collection_description_required"),
            _clean_optional(public_note),
            _clean_optional(admin_note),
            start,
            end,
            public_flag,
            timestamp,
            actor_value,
            int(collection_id),
        ),
    )
    updated = get_collection(conn, collection_id)
    _record_history(
        conn,
        collection_id=int(collection_id),
        action_type=action_type,
        actor=actor_value,
        timestamp=timestamp,
        previous_state=_collection_state(previous),
        new_state=_collection_state(updated),
        note=admin_note or "Collection updated.",
    )
    conn.commit()
    return updated


def deactivate_collection(
    conn: sqlite3.Connection,
    collection_id: int | str,
    *,
    actor: str,
    note: str,
    deactivated_at: str | None = None,
) -> dict[str, Any]:
    ensure_collection_tables(conn)
    actor_value = _clean_required(actor, "collection_actor_required")
    normalized_note = _clean_required(note, "collection_deactivation_note_required")
    previous = get_collection(conn, collection_id)
    timestamp = deactivated_at or utc_now()
    conn.execute(
        """
        UPDATE archive_collections
        SET is_active = 0, updated_at = ?, updated_by = ?,
            deactivated_at = ?, deactivated_by = ?, deactivation_note = ?
        WHERE id = ?
        """,
        (timestamp, actor_value, timestamp, actor_value, normalized_note, int(collection_id)),
    )
    updated = get_collection(conn, collection_id)
    _record_history(
        conn,
        collection_id=int(collection_id),
        action_type="deactivated",
        actor=actor_value,
        timestamp=timestamp,
        previous_state=_collection_state(previous),
        new_state=_collection_state(updated),
        note=normalized_note,
    )
    conn.commit()
    return updated


def reactivate_collection(
    conn: sqlite3.Connection,
    collection_id: int | str,
    *,
    actor: str,
    note: str | None = None,
    reactivated_at: str | None = None,
) -> dict[str, Any]:
    ensure_collection_tables(conn)
    actor_value = _clean_required(actor, "collection_actor_required")
    previous = get_collection(conn, collection_id)
    timestamp = reactivated_at or utc_now()
    conn.execute(
        """
        UPDATE archive_collections
        SET is_active = 1, updated_at = ?, updated_by = ?,
            deactivated_at = NULL, deactivated_by = NULL, deactivation_note = NULL
        WHERE id = ?
        """,
        (timestamp, actor_value, int(collection_id)),
    )
    updated = get_collection(conn, collection_id)
    _record_history(
        conn,
        collection_id=int(collection_id),
        action_type="reactivated",
        actor=actor_value,
        timestamp=timestamp,
        previous_state=_collection_state(previous),
        new_state=_collection_state(updated),
        note=note or "Collection reactivated.",
    )
    conn.commit()
    return updated


def _collection_matches(row: dict[str, Any], filters: dict[str, Any]) -> bool:
    normalized_query = str(filters.get("q") or "").strip().casefold()
    if normalized_query:
        searchable = " ".join(
            str(row.get(key) or "")
            for key in (
                "public_reference",
                "title",
                "subtitle",
                "institution_source",
                "description",
                "public_note",
                "admin_note",
            )
        ).casefold()
        if normalized_query not in searchable:
            return False
    for key, column in (
        ("public_reference", "public_reference"),
        ("title", "title"),
        ("institution_source", "institution_source"),
    ):
        value = str(filters.get(key) or "").strip().casefold()
        if value and value not in str(row.get(column) or "").casefold():
            return False
    category = str(filters.get("category") or "").strip()
    if category and row.get("category") != category:
        return False
    active_status = str(filters.get("active_status") or "").strip().lower()
    if active_status in {"active", "inactive"}:
        expected = 1 if active_status == "active" else 0
        if int(row.get("is_active") or 0) != expected:
            return False
    public_visibility = str(filters.get("public_visibility") or "").strip().lower()
    if public_visibility in {"public", "private"}:
        expected = 1 if public_visibility == "public" else 0
        if int(row.get("is_public") or 0) != expected:
            return False
    created_date = str(row.get("created_at") or "")[:10]
    date_from = str(filters.get("created_date_from") or "").strip()
    date_to = str(filters.get("created_date_to") or "").strip()
    if date_from and created_date < date_from:
        return False
    if date_to and created_date > date_to:
        return False
    return True


def list_collections(conn: sqlite3.Connection, **filters: Any) -> list[dict[str, Any]]:
    ensure_collection_tables(conn)
    rows = [
        dict(row)
        for row in conn.execute(
            """
            SELECT * FROM archive_collections
            ORDER BY created_at DESC, public_reference DESC, id DESC
            """
        ).fetchall()
    ]
    return [row for row in rows if _collection_matches(row, filters)]


def get_public_collection(conn: sqlite3.Connection, public_reference: str) -> dict[str, Any]:
    ensure_collection_tables(conn)
    reference = validate_public_reference(public_reference)
    row = conn.execute(
        "SELECT * FROM archive_collections WHERE public_reference = ?",
        (reference,),
    ).fetchone()
    if not row:
        raise ValueError("public_collection_not_found")
    collection = dict(row)
    if not public_collection_is_eligible(collection):
        raise ValueError("public_collection_not_found")
    return collection


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


def _normalize_public_page_size(value: Any) -> int:
    parsed = _parse_positive_int(value, 25, maximum=100)
    return parsed if parsed in PUBLIC_COLLECTION_PAGE_SIZE_OPTIONS else 25


def _public_projection(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "public_reference": row.get("public_reference"),
        "title": row.get("title"),
        "subtitle": row.get("subtitle"),
        "institution_source": row.get("institution_source"),
        "category": row.get("category"),
        "category_label": category_label(row.get("category")),
        "description": row.get("description"),
        "public_note": row.get("public_note"),
        "date_from": row.get("date_from"),
        "date_to": row.get("date_to"),
        "created_at": row.get("created_at"),
        "created_year": str(row.get("created_at") or "")[:4],
        "coverage_years": " ".join(
            str(value or "")[:4]
            for value in (row.get("date_from"), row.get("date_to"))
            if value
        ),
        "_internal_id": row.get("id"),
    }


def _public_index_filter_matches(row: dict[str, Any], filters: dict[str, str]) -> bool:
    query = filters["q"].casefold()
    if query:
        searchable = " ".join(
            str(row.get(key) or "")
            for key in (
                "public_reference",
                "title",
                "subtitle",
                "institution_source",
                "category",
                "category_label",
                "description",
                "public_note",
            )
        ).casefold()
        if query not in searchable:
            return False
    category = filters["category"]
    if category and row.get("category") != category:
        return False
    institution = filters["institution"].casefold()
    if institution and institution not in str(row.get("institution_source") or "").casefold():
        return False
    created_year = filters["created_year"]
    if created_year and row.get("created_year") != created_year:
        return False
    coverage_year = filters["coverage_year"]
    if coverage_year and coverage_year not in str(row.get("coverage_years") or ""):
        return False
    return True


def public_collection_index_options(rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    return {
        "institutions": sorted({str(row.get("institution_source") or "") for row in rows if row.get("institution_source")}),
        "categories": sorted({str(row.get("category") or "") for row in rows if row.get("category")}),
        "created_years": sorted({str(row.get("created_year") or "") for row in rows if row.get("created_year")}, reverse=True),
        "coverage_years": sorted({year for row in rows for year in str(row.get("coverage_years") or "").split() if year}, reverse=True),
    }


def list_public_collection_index(
    conn: sqlite3.Connection,
    *,
    q: Any = "",
    category: Any = "",
    institution: Any = "",
    created_year: Any = "",
    coverage_year: Any = "",
    page: Any = 1,
    page_size: Any = 25,
) -> dict[str, Any]:
    ensure_collection_tables(conn)
    raw_category = str(category or "").strip()
    normalized_category = raw_category if raw_category in COLLECTION_CATEGORIES else ""
    raw_year = str(created_year or "").strip()
    normalized_year = raw_year if len(raw_year) == 4 and raw_year.isdigit() else ""
    raw_coverage = str(coverage_year or "").strip()
    normalized_coverage = raw_coverage if len(raw_coverage) == 4 and raw_coverage.isdigit() else ""
    filters = {
        "q": str(q or "").strip(),
        "category": normalized_category,
        "institution": str(institution or "").strip(),
        "created_year": normalized_year,
        "coverage_year": normalized_coverage,
    }
    rows = [
        _public_projection(dict(row))
        for row in conn.execute(
            """
            SELECT * FROM archive_collections
            WHERE is_active = 1 AND is_public = 1
              AND public_reference IS NOT NULL AND public_reference != ''
            ORDER BY created_at DESC, public_reference DESC, id DESC
            """
        ).fetchall()
    ]
    options = public_collection_index_options(rows)
    filtered_rows = [row for row in rows if _public_index_filter_matches(row, filters)]
    filtered_rows.sort(
        key=lambda row: (
            str(row.get("created_at") or ""),
            str(row.get("public_reference") or ""),
            int(row.get("_internal_id") or 0),
        ),
        reverse=True,
    )
    normalized_page_size = _normalize_public_page_size(page_size)
    total = len(filtered_rows)
    page_count = max(1, (total + normalized_page_size - 1) // normalized_page_size)
    normalized_page = min(_parse_positive_int(page, 1), page_count)
    start = (normalized_page - 1) * normalized_page_size
    return {
        "rows": filtered_rows[start : start + normalized_page_size],
        "total": total,
        "page": normalized_page,
        "page_size": normalized_page_size,
        "page_count": page_count,
        "filters": filters,
        "options": options,
    }


def public_collection_history(conn: sqlite3.Connection, collection_id: int | str) -> list[dict[str, Any]]:
    collection = get_collection(conn, collection_id)
    events = collection_history(conn, collection_id)
    projected: list[dict[str, Any]] = []
    for event in events:
        action_type = str(event.get("action_type") or "")
        if action_type == "deactivated" and int(collection.get("is_active") or 0) == 0:
            continue
        projected.append(
            {
                "timestamp": event.get("timestamp"),
                "action_type": action_type,
                "action_label": COLLECTION_ACTION_LABELS.get(action_type, action_type or "Collection event"),
                "actor": event.get("actor"),
                "state_change": _public_state_change(event),
            }
        )
    return projected


def _decode_state(raw: Any) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        decoded = json.loads(str(raw))
    except json.JSONDecodeError:
        return None
    return decoded if isinstance(decoded, dict) else None


def _public_state_label(state: dict[str, Any] | None) -> str:
    if not state:
        return "—"
    active = "Active" if int(state.get("is_active") or 0) == 1 else "Inactive"
    visibility = "Public" if int(state.get("is_public") or 0) == 1 else "Private"
    return f"{active}, {visibility}"


def _public_state_change(event: dict[str, Any]) -> str:
    previous = _decode_state(event.get("previous_state_json"))
    new = _decode_state(event.get("new_state_json"))
    if not previous and new:
        return _public_state_label(new)
    return f"{_public_state_label(previous)} → {_public_state_label(new)}"
