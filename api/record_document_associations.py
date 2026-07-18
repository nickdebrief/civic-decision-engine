from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from api.document_intake import (
    document_type_label,
    intake_root,
    list_published_documents,
    load_pending_document,
    load_published_document,
)

DB_PATH = Path(os.getenv("RECORDS_DB_PATH", "records.db"))

RELATIONSHIP_TYPES: dict[str, str] = {
    "supporting_document": "Supporting document",
    "source_document": "Source document",
    "related_document": "Related document",
    "publication_context": "Publication context",
    "preserved_visual_record": "Preserved visual record",
    "methodology_reference": "Methodology reference",
    "procedural_record": "Procedural record",
    "evidence_audit": "Evidence audit",
}

PUBLIC_REFERENCE_RE = re.compile(r"^CDE-ASSOC-\d{8}-\d{3,}$")
MULTIPLE_RECORD_REFERENCE_RE = re.compile(r"[,;\r\n]")

ASSOCIATION_ACTION_LABELS = {
    "created": "Created",
    "updated": "Updated",
    "deactivated": "Deactivated",
    "reactivated": "Reactivated",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    ensure_association_tables(conn)
    conn.commit()
    return conn


def ensure_association_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS record_document_associations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            public_reference TEXT,
            record_reference TEXT NOT NULL,
            document_id TEXT NOT NULL,
            document_reference_identifier TEXT,
            relationship_type TEXT NOT NULL,
            public_label TEXT NOT NULL,
            public_note TEXT,
            admin_note TEXT,
            is_active INTEGER NOT NULL DEFAULT 1,
            is_public INTEGER NOT NULL DEFAULT 1,
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
    columns = {row[1] for row in conn.execute("PRAGMA table_info(record_document_associations)")}
    if "public_reference" not in columns:
        conn.execute("ALTER TABLE record_document_associations ADD COLUMN public_reference TEXT")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS record_document_association_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            association_id INTEGER NOT NULL,
            action_type TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            actor TEXT NOT NULL,
            previous_state_json TEXT,
            new_state_json TEXT,
            note TEXT,
            FOREIGN KEY (association_id) REFERENCES record_document_associations(id)
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_associations_record_reference
        ON record_document_associations(record_reference)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_associations_document_id
        ON record_document_associations(document_id)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_associations_active_public
        ON record_document_associations(is_active, is_public)
        """
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_associations_active_unique
        ON record_document_associations(record_reference, document_id, relationship_type)
        WHERE is_active = 1
        """
    )
    backfill_public_references(conn)
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_record_document_associations_public_reference
        ON record_document_associations(public_reference)
        """
    )


def _reference_date(timestamp: str | None) -> str:
    raw = str(timestamp or utc_now())[:10]
    digits = raw.replace("-", "")
    return digits if len(digits) == 8 and digits.isdigit() else utc_now()[:10].replace("-", "")


def generate_public_reference(conn: sqlite3.Connection, timestamp: str | None = None) -> str:
    date_part = _reference_date(timestamp)
    prefix = f"CDE-ASSOC-{date_part}-"
    rows = conn.execute(
        "SELECT public_reference FROM record_document_associations WHERE public_reference LIKE ?",
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


def backfill_public_references(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        SELECT id, created_at FROM record_document_associations
        WHERE public_reference IS NULL OR public_reference = ''
        ORDER BY created_at ASC, id ASC
        """
    ).fetchall()
    for row in rows:
        conn.execute(
            "UPDATE record_document_associations SET public_reference = ? WHERE id = ?",
            (generate_public_reference(conn, row["created_at"]), row["id"]),
        )


def validate_public_reference(value: str) -> str:
    reference = str(value or "").strip()
    if not PUBLIC_REFERENCE_RE.fullmatch(reference):
        raise ValueError("association_public_reference_invalid")
    return reference


def normalize_bool(value: Any, *, default: bool = True) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on", "public", "visible"}


def validate_relationship_type(value: str) -> str:
    normalized = str(value or "").strip()
    if normalized not in RELATIONSHIP_TYPES:
        raise ValueError("association_relationship_type_invalid")
    return normalized


def relationship_label(relationship_type: str, public_label: str | None = None) -> str:
    custom = str(public_label or "").strip()
    if custom:
        return custom[:160]
    return RELATIONSHIP_TYPES[validate_relationship_type(relationship_type)]


def record_context(conn: sqlite3.Connection, reference: str) -> dict[str, Any] | None:
    ensure_association_tables(conn)
    try:
        row = conn.execute(
            """
            SELECT reference, finding, generated_at, exported_at, trajectory,
                   system_state, version, language
            FROM records
            WHERE reference = ? AND is_latest = 1
            ORDER BY version DESC
            LIMIT 1
            """,
            (str(reference or "").strip(),),
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    return dict(row) if row else None


def record_exists(conn: sqlite3.Connection, reference: str) -> bool:
    return record_context(conn, reference) is not None


def public_record_context(conn: sqlite3.Connection, reference: str) -> dict[str, Any] | None:
    return record_context(conn, reference)


def _record_reference_exists_any_version(conn: sqlite3.Connection, reference: str) -> bool:
    try:
        row = conn.execute(
            "SELECT 1 FROM records WHERE reference = ? LIMIT 1",
            (str(reference or "").strip(),),
        ).fetchone()
    except sqlite3.OperationalError:
        return False
    return row is not None


def normalize_selected_record_reference(value: Any) -> str:
    reference = str(value or "").strip()
    if not reference:
        raise ValueError("association_record_required")
    if MULTIPLE_RECORD_REFERENCE_RE.search(reference):
        raise ValueError("association_record_multiple_not_allowed")
    return reference


def list_public_record_options(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    ensure_association_tables(conn)
    preferred_columns = (
        "reference",
        "record_type",
        "title",
        "public_title",
        "record_title",
        "institution",
        "institution_type",
        "institution_source",
        "trajectory",
        "finding",
        "system_state",
        "conditions_json",
        "signals_json",
        "tags",
        "summary",
        "public_summary",
        "report_json",
        "source_narrative",
        "generated_at",
        "exported_at",
        "version",
    )
    try:
        available_columns = {
            str(row[1])
            for row in conn.execute("PRAGMA table_info(records)").fetchall()
        }
        selected_columns = [
            column for column in preferred_columns if column in available_columns
        ]
        if "reference" not in selected_columns:
            return []
        rows = conn.execute(
            f"""
            SELECT {", ".join(selected_columns)}
            FROM records
            WHERE is_latest = 1 AND reference IS NOT NULL AND TRIM(reference) != ''
            ORDER BY reference ASC
            """
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    return [dict(row) for row in rows]


def _document_reference_matches_published_document(
    value: str,
    *,
    root: Path | None = None,
) -> bool:
    reference = str(value or "").strip()
    if not reference:
        return False
    for document in list_published_document_options(root=root):
        if str(document.get("reference_identifier") or "").strip() == reference:
            return True
    return False


def validate_public_record_reference(
    conn: sqlite3.Connection,
    value: Any,
    *,
    root: Path | None = None,
) -> str:
    reference = normalize_selected_record_reference(value)
    if public_record_context(conn, reference) is not None:
        return reference
    if _record_reference_exists_any_version(conn, reference):
        raise ValueError("association_record_not_public")
    if _document_reference_matches_published_document(reference, root=root):
        raise ValueError("association_record_reference_is_document")
    raise ValueError("association_record_not_found")


def published_document_context(document_id: str, *, root: Path | None = None) -> dict[str, Any] | None:
    try:
        return load_published_document(document_id, root=root or intake_root())
    except ValueError:
        return None


def document_context(document_id: str, *, root: Path | None = None) -> dict[str, Any] | None:
    try:
        return load_pending_document(document_id, root=root or intake_root())
    except ValueError:
        return None


def list_published_document_options(*, root: Path | None = None) -> list[dict[str, Any]]:
    return list_published_documents(root=root or intake_root())


def _association_state(row: sqlite3.Row | dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    data = dict(row)
    return {
        "id": data.get("id"),
        "public_reference": data.get("public_reference"),
        "record_reference": data.get("record_reference"),
        "document_id": data.get("document_id"),
        "document_reference_identifier": data.get("document_reference_identifier"),
        "relationship_type": data.get("relationship_type"),
        "public_label": data.get("public_label"),
        "public_note": data.get("public_note"),
        "admin_note": data.get("admin_note"),
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
    association_id: int,
    action_type: str,
    actor: str,
    timestamp: str,
    previous_state: dict[str, Any] | None,
    new_state: dict[str, Any] | None,
    note: str | None,
) -> None:
    conn.execute(
        """
        INSERT INTO record_document_association_history (
            association_id, action_type, timestamp, actor,
            previous_state_json, new_state_json, note
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            association_id,
            action_type,
            timestamp,
            str(actor or "").strip(),
            json.dumps(previous_state, sort_keys=True) if previous_state is not None else None,
            json.dumps(new_state, sort_keys=True) if new_state is not None else None,
            str(note or "").strip() or None,
        ),
    )


def get_association(conn: sqlite3.Connection, association_id: int | str) -> dict[str, Any]:
    ensure_association_tables(conn)
    row = conn.execute(
        "SELECT * FROM record_document_associations WHERE id = ?",
        (int(association_id),),
    ).fetchone()
    if not row:
        raise ValueError("association_not_found")
    return dict(row)


def association_history(conn: sqlite3.Connection, association_id: int | str) -> list[dict[str, Any]]:
    ensure_association_tables(conn)
    rows = conn.execute(
        """
        SELECT * FROM record_document_association_history
        WHERE association_id = ?
        ORDER BY timestamp ASC, id ASC
        """,
        (int(association_id),),
    ).fetchall()
    return [dict(row) for row in rows]


def create_association(
    conn: sqlite3.Connection,
    *,
    record_reference: str,
    document_id: str,
    relationship_type: str,
    public_label: str | None = None,
    public_note: str | None = None,
    admin_note: str | None = None,
    is_public: Any = True,
    actor: str,
    created_at: str | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    ensure_association_tables(conn)
    actor_value = str(actor or "").strip()
    if not actor_value:
        raise ValueError("association_actor_required")
    reference = validate_public_record_reference(conn, record_reference, root=root)
    document = published_document_context(str(document_id or "").strip(), root=root)
    if document is None:
        raise ValueError("association_document_not_published")
    rel_type = validate_relationship_type(relationship_type)
    existing = conn.execute(
        """
        SELECT id, is_active FROM record_document_associations
        WHERE record_reference = ? AND document_id = ? AND relationship_type = ?
        ORDER BY id DESC LIMIT 1
        """,
        (reference, document["intake_id"], rel_type),
    ).fetchone()
    if existing and int(existing["is_active"] or 0) == 1:
        raise ValueError("association_duplicate_active")
    if existing:
        raise ValueError("association_inactive_duplicate_exists")
    timestamp = created_at or utc_now()
    public_reference = generate_public_reference(conn, timestamp)
    label = relationship_label(rel_type, public_label)
    public_flag = 1 if normalize_bool(is_public, default=True) else 0
    cursor = conn.execute(
        """
        INSERT INTO record_document_associations (
            public_reference, record_reference, document_id, document_reference_identifier,
            relationship_type, public_label, public_note, admin_note,
            is_active, is_public, created_at, created_by, updated_at, updated_by
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?)
        """,
        (
            public_reference,
            reference,
            document["intake_id"],
            document.get("reference_identifier"),
            rel_type,
            label,
            str(public_note or "").strip() or None,
            str(admin_note or "").strip() or None,
            public_flag,
            timestamp,
            actor_value,
            timestamp,
            actor_value,
        ),
    )
    association_id = int(cursor.lastrowid)
    row = get_association(conn, association_id)
    _record_history(
        conn,
        association_id=association_id,
        action_type="created",
        actor=actor_value,
        timestamp=timestamp,
        previous_state=None,
        new_state=_association_state(row),
        note=admin_note or public_note or "Association created.",
    )
    conn.commit()
    return row


def update_association(
    conn: sqlite3.Connection,
    association_id: int | str,
    *,
    relationship_type: str,
    public_label: str | None,
    public_note: str | None,
    admin_note: str | None,
    is_public: Any,
    actor: str,
    updated_at: str | None = None,
) -> dict[str, Any]:
    ensure_association_tables(conn)
    actor_value = str(actor or "").strip()
    if not actor_value:
        raise ValueError("association_actor_required")
    previous = get_association(conn, association_id)
    rel_type = validate_relationship_type(relationship_type)
    label = relationship_label(rel_type, public_label)
    public_flag = 1 if normalize_bool(is_public, default=True) else 0
    timestamp = updated_at or utc_now()
    conn.execute(
        """
        UPDATE record_document_associations
        SET relationship_type = ?, public_label = ?, public_note = ?, admin_note = ?,
            is_public = ?, updated_at = ?, updated_by = ?
        WHERE id = ?
        """,
        (
            rel_type,
            label,
            str(public_note or "").strip() or None,
            str(admin_note or "").strip() or None,
            public_flag,
            timestamp,
            actor_value,
            int(association_id),
        ),
    )
    updated = get_association(conn, association_id)
    _record_history(
        conn,
        association_id=int(association_id),
        action_type="updated",
        actor=actor_value,
        timestamp=timestamp,
        previous_state=_association_state(previous),
        new_state=_association_state(updated),
        note=admin_note or "Association updated.",
    )
    conn.commit()
    return updated


def deactivate_association(
    conn: sqlite3.Connection,
    association_id: int | str,
    *,
    actor: str,
    note: str,
    deactivated_at: str | None = None,
) -> dict[str, Any]:
    ensure_association_tables(conn)
    actor_value = str(actor or "").strip()
    normalized_note = str(note or "").strip()
    if not actor_value:
        raise ValueError("association_actor_required")
    if not normalized_note:
        raise ValueError("association_deactivation_note_required")
    previous = get_association(conn, association_id)
    timestamp = deactivated_at or utc_now()
    conn.execute(
        """
        UPDATE record_document_associations
        SET is_active = 0, updated_at = ?, updated_by = ?,
            deactivated_at = ?, deactivated_by = ?, deactivation_note = ?
        WHERE id = ?
        """,
        (timestamp, actor_value, timestamp, actor_value, normalized_note, int(association_id)),
    )
    updated = get_association(conn, association_id)
    _record_history(
        conn,
        association_id=int(association_id),
        action_type="deactivated",
        actor=actor_value,
        timestamp=timestamp,
        previous_state=_association_state(previous),
        new_state=_association_state(updated),
        note=normalized_note,
    )
    conn.commit()
    return updated


def reactivate_association(
    conn: sqlite3.Connection,
    association_id: int | str,
    *,
    actor: str,
    note: str | None = None,
    reactivated_at: str | None = None,
) -> dict[str, Any]:
    ensure_association_tables(conn)
    actor_value = str(actor or "").strip()
    if not actor_value:
        raise ValueError("association_actor_required")
    previous = get_association(conn, association_id)
    if int(previous.get("is_active") or 0) == 1:
        raise ValueError("association_already_active")
    timestamp = reactivated_at or utc_now()
    try:
        conn.execute(
            """
            UPDATE record_document_associations
            SET is_active = 1, updated_at = ?, updated_by = ?,
                deactivated_at = NULL, deactivated_by = NULL, deactivation_note = NULL
            WHERE id = ?
            """,
            (timestamp, actor_value, int(association_id)),
        )
    except sqlite3.IntegrityError as exc:
        raise ValueError("association_duplicate_active") from exc
    updated = get_association(conn, association_id)
    _record_history(
        conn,
        association_id=int(association_id),
        action_type="reactivated",
        actor=actor_value,
        timestamp=timestamp,
        previous_state=_association_state(previous),
        new_state=_association_state(updated),
        note=note or "Association reactivated.",
    )
    conn.commit()
    return updated


def _association_matches(row: dict[str, Any], filters: dict[str, Any]) -> bool:
    normalized_query = str(filters.get("q") or "").strip().casefold()
    if normalized_query:
        searchable = " ".join(
            str(row.get(key) or "")
            for key in (
                "public_reference",
                "record_reference",
                "document_id",
                "document_reference_identifier",
                "relationship_type",
                "public_label",
                "public_note",
                "admin_note",
                "created_by",
                "updated_by",
                "document_title",
                "record_title",
            )
        ).casefold()
        if normalized_query not in searchable:
            return False
    for key, column in (
        ("record_reference", "record_reference"),
        ("document_reference", "document_reference_identifier"),
        ("relationship_type", "relationship_type"),
        ("actor", "created_by"),
    ):
        value = str(filters.get(key) or "").strip().casefold()
        if value and value not in str(row.get(column) or "").casefold():
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
    date_from = str(filters.get("date_from") or "").strip()
    date_to = str(filters.get("date_to") or "").strip()
    if date_from and created_date < date_from:
        return False
    if date_to and created_date > date_to:
        return False
    return True


def list_associations(
    conn: sqlite3.Connection,
    *,
    root: Path | None = None,
    **filters: Any,
) -> list[dict[str, Any]]:
    ensure_association_tables(conn)
    rows = [
        dict(row)
        for row in conn.execute(
            "SELECT * FROM record_document_associations ORDER BY created_at DESC, id DESC"
        ).fetchall()
    ]
    enriched = [enrich_association(conn, row, root=root) for row in rows]
    return [row for row in enriched if _association_matches(row, filters)]


def enrich_association(
    conn: sqlite3.Connection,
    association: dict[str, Any],
    *,
    root: Path | None = None,
) -> dict[str, Any]:
    row = dict(association)
    record = record_context(conn, row.get("record_reference"))
    document = document_context(row.get("document_id"), root=root)
    row["record_title"] = (record or {}).get("finding") or row.get("record_reference")
    row["record_generated_at"] = (record or {}).get("generated_at")
    row["record_exported_at"] = (record or {}).get("exported_at")
    row["record_trajectory"] = (record or {}).get("trajectory")
    row["record_version"] = (record or {}).get("version")
    row["record_publicly_eligible"] = record is not None
    row["document_title"] = (document or {}).get("title") or row.get("document_id")
    row["document_reference_identifier"] = (
        (document or {}).get("reference_identifier") or row.get("document_reference_identifier")
    )
    row["document_institution_source"] = (document or {}).get("institution_source")
    row["document_category"] = (document or {}).get("category")
    row["document_format"] = document_type_label((document or {}).get("document_type")) if document else "—"
    row["document_date"] = (document or {}).get("document_date")
    row["document_publication_date"] = (document or {}).get("publication_date")
    row["document_status"] = (document or {}).get("status")
    row["document_publicly_eligible"] = bool(document and document.get("status") == "published")
    return row


def public_associations_for_record(
    conn: sqlite3.Connection,
    record_reference: str,
    *,
    root: Path | None = None,
) -> list[dict[str, Any]]:
    ensure_association_tables(conn)
    if public_record_context(conn, record_reference) is None:
        return []
    rows = conn.execute(
        """
        SELECT * FROM record_document_associations
        WHERE record_reference = ? AND is_active = 1 AND is_public = 1
        ORDER BY created_at DESC, id DESC
        """,
        (record_reference,),
    ).fetchall()
    associations = []
    for row in rows:
        enriched = enrich_association(conn, dict(row), root=root)
        if enriched.get("document_publicly_eligible"):
            associations.append(enriched)
    return associations


def public_associations_for_document(
    conn: sqlite3.Connection,
    document_id: str,
    *,
    root: Path | None = None,
) -> list[dict[str, Any]]:
    ensure_association_tables(conn)
    if published_document_context(document_id, root=root) is None:
        return []
    rows = conn.execute(
        """
        SELECT * FROM record_document_associations
        WHERE document_id = ? AND is_active = 1 AND is_public = 1
        ORDER BY created_at DESC, id DESC
        """,
        (document_id,),
    ).fetchall()
    associations = []
    for row in rows:
        enriched = enrich_association(conn, dict(row), root=root)
        if enriched.get("record_publicly_eligible"):
            associations.append(enriched)
    return associations



def get_public_association(
    conn: sqlite3.Connection,
    public_reference: str,
    *,
    root: Path | None = None,
) -> dict[str, Any]:
    ensure_association_tables(conn)
    reference = validate_public_reference(public_reference)
    row = conn.execute(
        "SELECT * FROM record_document_associations WHERE public_reference = ?",
        (reference,),
    ).fetchone()
    if not row:
        raise ValueError("public_association_not_found")
    enriched = enrich_association(conn, dict(row), root=root)
    if not public_association_is_eligible(enriched):
        raise ValueError("public_association_not_found")
    return enriched


def public_association_is_eligible(association: dict[str, Any]) -> bool:
    return (
        int(association.get("is_active") or 0) == 1
        and int(association.get("is_public") or 0) == 1
        and bool(association.get("record_publicly_eligible"))
        and bool(association.get("document_publicly_eligible"))
    )


PUBLIC_ASSOCIATION_PAGE_SIZE_OPTIONS = (10, 25, 50, 100)
PUBLIC_ASSOCIATION_FORMATS = {"PDF", "JPEG", "PNG", "M4A", "MP3", "WAV", "XLS", "XLSX"}
PUBLIC_ASSOCIATION_SORTS = {"newest", "oldest", "association_reference", "record_reference", "document_title"}


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
    return parsed if parsed in PUBLIC_ASSOCIATION_PAGE_SIZE_OPTIONS else 25


def _public_association_projection(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "public_reference": row.get("public_reference"),
        "relationship_type": row.get("relationship_type"),
        "relationship_label": relationship_label(str(row.get("relationship_type") or ""), row.get("public_label")),
        "public_note": row.get("public_note"),
        "created_at": row.get("created_at"),
        "created_year": str(row.get("created_at") or "")[:4],
        "record_reference": row.get("record_reference"),
        "record_title": row.get("record_title"),
        "record_generated_at": row.get("record_generated_at"),
        "record_trajectory": row.get("record_trajectory"),
        "document_id": row.get("document_id"),
        "document_title": row.get("document_title"),
        "document_reference_identifier": row.get("document_reference_identifier"),
        "document_institution_source": row.get("document_institution_source"),
        "document_category": row.get("document_category"),
        "document_format": row.get("document_format"),
        "_internal_id": row.get("id"),
    }


def _public_index_search_matches(row: dict[str, Any], query: str) -> bool:
    if not query:
        return True
    searchable = " ".join(
        str(row.get(key) or "")
        for key in (
            "public_reference",
            "relationship_label",
            "relationship_type",
            "public_note",
            "record_reference",
            "record_title",
            "document_title",
            "document_reference_identifier",
            "document_institution_source",
            "document_category",
        )
    ).casefold()
    return query.casefold() in searchable


def _public_index_filter_matches(row: dict[str, Any], filters: dict[str, str]) -> bool:
    if not _public_index_search_matches(row, filters["q"]):
        return False
    relationship_type = filters["relationship_type"]
    if relationship_type and row.get("relationship_type") != relationship_type:
        return False
    for filter_key, row_key in (
        ("record_reference", "record_reference"),
        ("document_reference", "document_reference_identifier"),
        ("institution", "document_institution_source"),
        ("category", "document_category"),
    ):
        value = filters[filter_key].casefold()
        if value and value not in str(row.get(row_key) or "").casefold():
            return False
    created_year = filters["created_year"]
    if created_year and row.get("created_year") != created_year:
        return False
    document_format = filters["document_format"]
    if document_format and row.get("document_format") != document_format:
        return False
    return True


def _public_index_sort_key(row: dict[str, Any], sort: str) -> tuple[Any, ...]:
    if sort == "oldest":
        return (str(row.get("created_at") or ""), str(row.get("public_reference") or ""), int(row.get("_internal_id") or 0))
    if sort == "association_reference":
        return (str(row.get("public_reference") or ""), int(row.get("_internal_id") or 0))
    if sort == "record_reference":
        return (str(row.get("record_reference") or "").casefold(), str(row.get("public_reference") or ""), int(row.get("_internal_id") or 0))
    if sort == "document_title":
        return (str(row.get("document_title") or "").casefold(), str(row.get("public_reference") or ""), int(row.get("_internal_id") or 0))
    return (str(row.get("created_at") or ""), str(row.get("public_reference") or ""), int(row.get("_internal_id") or 0))


def public_association_index_options(rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    return {
        "institutions": sorted({str(row.get("document_institution_source") or "") for row in rows if row.get("document_institution_source")}),
        "categories": sorted({str(row.get("document_category") or "") for row in rows if row.get("document_category")}),
        "created_years": sorted({str(row.get("created_year") or "") for row in rows if row.get("created_year")}, reverse=True),
        "document_formats": [
            fmt
            for fmt in ("PDF", "JPEG", "PNG", "M4A", "MP3", "WAV", "XLS", "XLSX")
            if any(row.get("document_format") == fmt for row in rows)
        ],
    }


def list_public_association_index(
    conn: sqlite3.Connection,
    *,
    root: Path | None = None,
    q: Any = "",
    relationship_type: Any = "",
    record_reference: Any = "",
    document_reference: Any = "",
    institution: Any = "",
    category: Any = "",
    created_year: Any = "",
    document_format: Any = "",
    page: Any = 1,
    page_size: Any = 25,
    sort: Any = "newest",
) -> dict[str, Any]:
    ensure_association_tables(conn)
    raw_relationship_type = str(relationship_type or "").strip()
    normalized_relationship_type = raw_relationship_type if raw_relationship_type in RELATIONSHIP_TYPES else ""
    raw_format = str(document_format or "").strip().upper()
    normalized_format = raw_format if raw_format in PUBLIC_ASSOCIATION_FORMATS else ""
    raw_year = str(created_year or "").strip()
    normalized_year = raw_year if len(raw_year) == 4 and raw_year.isdigit() else ""
    normalized_sort = str(sort or "newest").strip()
    if normalized_sort not in PUBLIC_ASSOCIATION_SORTS:
        normalized_sort = "newest"
    filters = {
        "q": str(q or "").strip(),
        "relationship_type": normalized_relationship_type,
        "record_reference": str(record_reference or "").strip(),
        "document_reference": str(document_reference or "").strip(),
        "institution": str(institution or "").strip(),
        "category": str(category or "").strip(),
        "created_year": normalized_year,
        "document_format": normalized_format,
        "sort": normalized_sort,
    }
    rows = [
        dict(row)
        for row in conn.execute(
            """
            SELECT * FROM record_document_associations
            WHERE is_active = 1 AND is_public = 1
              AND public_reference IS NOT NULL AND public_reference != ''
            ORDER BY created_at DESC, public_reference DESC, id DESC
            """
        ).fetchall()
    ]
    eligible_rows = [
        _public_association_projection(enriched)
        for enriched in (enrich_association(conn, row, root=root) for row in rows)
        if public_association_is_eligible(enriched)
    ]
    options = public_association_index_options(eligible_rows)
    filtered_rows = [row for row in eligible_rows if _public_index_filter_matches(row, filters)]
    reverse = normalized_sort == "newest"
    filtered_rows.sort(key=lambda row: _public_index_sort_key(row, normalized_sort), reverse=reverse)
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


def public_association_history(conn: sqlite3.Connection, association_id: int | str) -> list[dict[str, Any]]:
    association = get_association(conn, association_id)
    events = association_history(conn, association_id)
    projected: list[dict[str, Any]] = []
    for event in events:
        action_type = str(event.get("action_type") or "")
        previous_state = _decode_state(event.get("previous_state_json"))
        new_state = _decode_state(event.get("new_state_json"))
        if action_type == "updated" and not _public_fields_changed(previous_state, new_state):
            continue
        if action_type == "deactivated" and int(association.get("is_active") or 0) == 0:
            continue
        projected.append(
            {
                "timestamp": event.get("timestamp"),
                "action_type": action_type,
                "action_label": ASSOCIATION_ACTION_LABELS.get(action_type, action_type or "Association event"),
                "actor": event.get("actor"),
                "previous_state": _public_state_label(previous_state),
                "new_state": _public_state_label(new_state),
                "note": _public_history_note(action_type, previous_state, new_state),
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


def _public_fields_changed(previous: dict[str, Any] | None, new: dict[str, Any] | None) -> bool:
    if previous is None or new is None:
        return True
    public_fields = ("relationship_type", "public_label", "public_note", "is_active", "is_public")
    return any(previous.get(field) != new.get(field) for field in public_fields)


def _public_state_label(state: dict[str, Any] | None) -> str:
    if not state:
        return "—"
    active = "Active" if int(state.get("is_active") or 0) == 1 else "Inactive"
    visibility = "Public" if int(state.get("is_public") or 0) == 1 else "Private"
    return f"{active}, {visibility}"


def _public_history_note(
    action_type: str,
    previous: dict[str, Any] | None,
    new: dict[str, Any] | None,
) -> str:
    if action_type == "created":
        return "Association created."
    if action_type == "reactivated":
        return "Association reactivated."
    if action_type == "deactivated":
        return "Association deactivated."
    if action_type == "updated":
        changes = []
        labels = {
            "relationship_type": "relationship type",
            "public_label": "public label",
            "public_note": "public note",
            "is_public": "public visibility",
            "is_active": "active state",
        }
        for field, label in labels.items():
            if (previous or {}).get(field) != (new or {}).get(field):
                changes.append(label)
        return "Public association fields updated: " + ", ".join(changes) if changes else "Association updated."
    return "Association event recorded."
