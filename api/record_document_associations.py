from __future__ import annotations

import json
import os
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
    return conn


def ensure_association_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS record_document_associations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
    return dict(row) if row else None


def record_exists(conn: sqlite3.Connection, reference: str) -> bool:
    return record_context(conn, reference) is not None


def public_record_context(conn: sqlite3.Connection, reference: str) -> dict[str, Any] | None:
    return record_context(conn, reference)


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
    reference = str(record_reference or "").strip()
    if not record_exists(conn, reference):
        raise ValueError("association_record_not_found")
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
    label = relationship_label(rel_type, public_label)
    public_flag = 1 if normalize_bool(is_public, default=True) else 0
    cursor = conn.execute(
        """
        INSERT INTO record_document_associations (
            record_reference, document_id, document_reference_identifier,
            relationship_type, public_label, public_note, admin_note,
            is_active, is_public, created_at, created_by, updated_at, updated_by
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?)
        """,
        (
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
    row["document_category"] = (document or {}).get("category")
    row["document_format"] = document_type_label((document or {}).get("document_type")) if document else "—"
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
