from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from api import archive_collections as ac
from api import record_document_associations as rda
from api.document_intake import STATUS_LABELS, document_type_label, load_pending_document


MEMBERSHIP_REFERENCE_RE = re.compile(r"^CDE-MEM-\d{8}-\d{3,}$")

MEMBERSHIP_STATUSES: dict[str, str] = {
    "draft": "Draft",
    "reviewed": "Reviewed",
    "approved": "Approved",
    "active": "Active",
    "inactive": "Inactive",
}

MEMBER_TYPES: dict[str, str] = {
    "canonical_record": "Canonical Record",
    "published_document": "Published Document",
    "record_document_association": "Record-Document Association",
}

MEMBER_TYPE_ALIASES: dict[str, str] = {
    "record": "canonical_record",
    "canonical_record": "canonical_record",
    "document": "published_document",
    "published_document": "published_document",
    "association": "record_document_association",
    "record_document_association": "record_document_association",
}

RECORD_TYPE_LABELS: dict[str, str] = {
    "strike": "Strike",
    "complaint": "Complaint",
    "investigation": "Investigation",
    "decision": "Decision",
    "proceeding": "Proceeding",
    "administrative_action": "Administrative Action",
    "public_submission": "Public Submission",
    "policy_event": "Policy Event",
    "research_record": "Research Record",
}

MEMBERSHIP_ACTION_LABELS: dict[str, str] = {
    "created": "Created",
    "reviewed": "Reviewed",
    "approved": "Approved",
    "activated": "Activated",
    "deactivated": "Deactivated",
    "sequence_changed": "Sequence changed",
    "removed": "Removed",
    "restored": "Restored",
}

VALID_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"reviewed"},
    "reviewed": {"approved"},
    "approved": {"active"},
    "active": {"inactive"},
    "inactive": {"active"},
}

CONTINUITY_STATES: dict[str, str] = {
    "empty": "Empty",
    "single_member": "Single Member",
    "continuous": "Continuous",
    "gap_present": "Gap Present",
    "duplicate_position": "Duplicate Position",
    "invalid_position": "Invalid Position",
}


def ensure_membership_tables(conn: sqlite3.Connection) -> None:
    ac.ensure_collection_tables(conn)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS archive_collection_memberships (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            membership_reference TEXT NOT NULL UNIQUE,
            collection_id INTEGER NOT NULL,
            document_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            created_by TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            updated_by TEXT NOT NULL,
            membership_status TEXT NOT NULL,
            membership_note TEXT,
            display_sequence INTEGER,
            effective_from TEXT,
            effective_to TEXT,
            is_active INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY (collection_id) REFERENCES archive_collections(id)
        )
        """
    )
    columns = _membership_table_columns(conn)
    if "member_type" not in columns:
        conn.execute(
            "ALTER TABLE archive_collection_memberships ADD COLUMN member_type TEXT NOT NULL DEFAULT 'published_document'"
        )
    if "member_reference" not in columns:
        conn.execute("ALTER TABLE archive_collection_memberships ADD COLUMN member_reference TEXT")
    if "section_label" not in columns:
        conn.execute("ALTER TABLE archive_collection_memberships ADD COLUMN section_label TEXT")
    if "curator_note" not in columns:
        conn.execute("ALTER TABLE archive_collection_memberships ADD COLUMN curator_note TEXT")
    conn.execute(
        """
        UPDATE archive_collection_memberships
        SET member_type = 'published_document'
        WHERE member_type IS NULL OR TRIM(member_type) = ''
        """
    )
    conn.execute(
        """
        UPDATE archive_collection_memberships
        SET member_reference = document_id
        WHERE member_reference IS NULL OR TRIM(member_reference) = ''
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS archive_collection_membership_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            membership_id INTEGER NOT NULL,
            action_type TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            actor TEXT NOT NULL,
            previous_state_json TEXT,
            new_state_json TEXT,
            note TEXT,
            FOREIGN KEY (membership_id) REFERENCES archive_collection_memberships(id)
        )
        """
    )
    for statement in (
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_archive_collection_memberships_reference ON archive_collection_memberships(membership_reference)",
        "CREATE INDEX IF NOT EXISTS idx_archive_collection_memberships_collection ON archive_collection_memberships(collection_id)",
        "CREATE INDEX IF NOT EXISTS idx_archive_collection_memberships_document ON archive_collection_memberships(document_id)",
        "CREATE INDEX IF NOT EXISTS idx_archive_collection_memberships_status ON archive_collection_memberships(membership_status)",
        "CREATE INDEX IF NOT EXISTS idx_archive_collection_memberships_active ON archive_collection_memberships(is_active)",
        "CREATE INDEX IF NOT EXISTS idx_archive_collection_memberships_sequence ON archive_collection_memberships(display_sequence)",
        "CREATE INDEX IF NOT EXISTS idx_archive_collection_memberships_member_reference ON archive_collection_memberships(member_type, member_reference)",
        "CREATE INDEX IF NOT EXISTS idx_archive_collection_memberships_active_member ON archive_collection_memberships(collection_id, member_type, member_reference, is_active)",
        "CREATE INDEX IF NOT EXISTS idx_archive_collection_membership_history_membership ON archive_collection_membership_history(membership_id)",
    ):
        conn.execute(statement)


def _membership_table_columns(conn: sqlite3.Connection) -> set[str]:
    try:
        return {str(row[1]) for row in conn.execute("PRAGMA table_info(archive_collection_memberships)").fetchall()}
    except sqlite3.OperationalError:
        return set()


def _clean_required(value: Any, error: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        raise ValueError(error)
    return cleaned


def _clean_optional(value: Any) -> str | None:
    cleaned = str(value or "").strip()
    return cleaned or None


def normalize_member_type(value: Any) -> str:
    key = str(value or "published_document").strip().lower()
    normalized = MEMBER_TYPE_ALIASES.get(key)
    if not normalized:
        raise ValueError("collection_member_type_unsupported")
    return normalized


def member_type_label(value: Any) -> str:
    try:
        return MEMBER_TYPES[normalize_member_type(value)]
    except ValueError:
        return "Unsupported member type"


def _record_type_label(value: Any) -> str:
    record_type = str(value or "strike").strip().lower() or "strike"
    return RECORD_TYPE_LABELS.get(record_type, RECORD_TYPE_LABELS["strike"])


def _member_reference(value: Any) -> str:
    reference = str(value or "").strip()
    if not reference:
        raise ValueError("collection_member_reference_required")
    return reference


def _public_record_title(record: dict[str, Any]) -> str:
    return (
        str(record.get("title") or record.get("public_title") or record.get("record_title") or "").strip()
        or str(record.get("finding") or "").strip()
        or str(record.get("reference") or "").strip()
    )


def resolve_public_member(
    conn: sqlite3.Connection,
    member_type: Any,
    member_reference: Any,
    *,
    root: Path | None = None,
) -> dict[str, Any] | None:
    normalized_type = normalize_member_type(member_type)
    reference = _member_reference(member_reference)
    if normalized_type == "published_document":
        document = rda.published_document_context(reference, root=root)
        if not document:
            return None
        return {
            "member_type": normalized_type,
            "member_type_label": MEMBER_TYPES[normalized_type],
            "member_reference": str(document.get("intake_id") or reference),
            "member_public_reference": document.get("reference_identifier") or document.get("intake_id") or reference,
            "member_title": document.get("title") or reference,
            "member_summary": document.get("description"),
            "member_status": document.get("status"),
            "member_status_label": STATUS_LABELS.get(str(document.get("status") or ""), str(document.get("status") or "—")),
            "member_format": document_type_label(document.get("document_type")),
            "member_date": document.get("publication_date") or document.get("document_date"),
            "member_institution": document.get("institution_source"),
            "member_url": f"/documents/{document.get('intake_id') or reference}",
            "document": document,
        }
    if normalized_type == "canonical_record":
        record = rda.public_record_context(conn, reference)
        if not record:
            return None
        record_reference = str(record.get("reference") or reference)
        return {
            "member_type": normalized_type,
            "member_type_label": MEMBER_TYPES[normalized_type],
            "member_reference": record_reference,
            "member_public_reference": record_reference,
            "member_title": _public_record_title(record),
            "member_summary": record.get("summary") or record.get("public_summary") or record.get("finding"),
            "member_status": "published",
            "member_status_label": "Published",
            "member_format": _record_type_label(record.get("record_type")),
            "member_date": record.get("exported_at") or record.get("generated_at"),
            "member_institution": record.get("institution") or record.get("institution_type") or record.get("institution_source"),
            "member_url": f"/verify/{record_reference}",
            "record": record,
        }
    association = rda.get_public_association(conn, reference, root=root)
    relationship_label = rda.RELATIONSHIP_TYPES.get(
        str(association.get("relationship_type") or ""),
        str(association.get("relationship_type") or "Association"),
    )
    title = str(association.get("public_label") or relationship_label or reference)
    summary_parts = [
        association.get("public_note"),
        f"Record: {association.get('record_reference')}" if association.get("record_reference") else None,
        f"Document: {association.get('document_reference_identifier')}" if association.get("document_reference_identifier") else None,
    ]
    return {
        "member_type": normalized_type,
        "member_type_label": MEMBER_TYPES[normalized_type],
        "member_reference": str(association.get("public_reference") or reference),
        "member_public_reference": association.get("public_reference") or reference,
        "member_title": title,
        "member_summary": " · ".join(str(part) for part in summary_parts if part),
        "member_status": "active_public",
        "member_status_label": "Active public association",
        "member_format": relationship_label,
        "member_date": association.get("created_at"),
        "member_institution": association.get("document_institution_source"),
        "member_url": f"/associations/{association.get('public_reference') or reference}",
        "association": association,
    }


def _validate_public_member_reference(
    conn: sqlite3.Connection,
    member_type: Any,
    member_reference: Any,
    *,
    root: Path | None = None,
) -> str:
    normalized_type = normalize_member_type(member_type)
    reference = _member_reference(member_reference)
    if normalized_type == "published_document":
        document = _load_document(reference, root=root)
        return str(document.get("intake_id") or reference)
    try:
        resolved = resolve_public_member(conn, normalized_type, reference, root=root)
    except ValueError as exc:
        raise ValueError("collection_member_not_public") from exc
    if not resolved:
        raise ValueError("collection_member_not_public")
    return str(resolved["member_reference"])


def _reference_date(timestamp: str | None) -> str:
    raw = str(timestamp or ac.utc_now())[:10]
    digits = raw.replace("-", "")
    return digits if len(digits) == 8 and digits.isdigit() else ac.utc_now()[:10].replace("-", "")


def generate_membership_reference(conn: sqlite3.Connection, timestamp: str | None = None) -> str:
    ensure_membership_tables(conn)
    date_part = _reference_date(timestamp)
    prefix = f"CDE-MEM-{date_part}-"
    rows = conn.execute(
        "SELECT membership_reference FROM archive_collection_memberships WHERE membership_reference LIKE ?",
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


def validate_membership_reference(value: Any) -> str:
    reference = str(value or "").strip()
    if not MEMBERSHIP_REFERENCE_RE.fullmatch(reference):
        raise ValueError("membership_reference_invalid")
    return reference


def _normalize_sequence(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        parsed = int(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError("membership_display_sequence_invalid") from exc
    if parsed < 0:
        raise ValueError("membership_display_sequence_invalid")
    return parsed


def _normalize_positive_sequence(value: Any) -> int:
    if value is None or value == "":
        raise ValueError("collection_membership_sequence_required")
    try:
        parsed = int(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError("collection_membership_sequence_invalid") from exc
    if parsed <= 0:
        raise ValueError("collection_membership_sequence_invalid")
    return parsed


def _sequence_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _valid_active_sequence(value: Any) -> bool:
    parsed = _sequence_int(value)
    return parsed is not None and parsed > 0


def _membership_state(row: sqlite3.Row | dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    data = dict(row)
    return {
        "id": data.get("id"),
        "membership_reference": data.get("membership_reference"),
        "collection_id": data.get("collection_id"),
        "document_id": data.get("document_id"),
        "member_type": normalize_member_type(data.get("member_type") or "published_document"),
        "member_reference": data.get("member_reference") or data.get("document_id"),
        "created_at": data.get("created_at"),
        "created_by": data.get("created_by"),
        "updated_at": data.get("updated_at"),
        "updated_by": data.get("updated_by"),
        "membership_status": data.get("membership_status"),
        "membership_note": data.get("membership_note"),
        "section_label": data.get("section_label"),
        "curator_note": data.get("curator_note"),
        "display_sequence": data.get("display_sequence"),
        "effective_from": data.get("effective_from"),
        "effective_to": data.get("effective_to"),
        "is_active": int(data.get("is_active") or 0),
    }


def _record_history(
    conn: sqlite3.Connection,
    *,
    membership_id: int,
    action_type: str,
    actor: str,
    timestamp: str,
    previous_state: dict[str, Any] | None,
    new_state: dict[str, Any] | None,
    note: str | None,
) -> None:
    conn.execute(
        """
        INSERT INTO archive_collection_membership_history (
            membership_id, action_type, timestamp, actor,
            previous_state_json, new_state_json, note
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            int(membership_id),
            action_type,
            timestamp,
            str(actor or "").strip(),
            json.dumps(previous_state, sort_keys=True) if previous_state is not None else None,
            json.dumps(new_state, sort_keys=True) if new_state is not None else None,
            _clean_optional(note),
        ),
    )


def get_membership(conn: sqlite3.Connection, membership_id: int | str) -> dict[str, Any]:
    ensure_membership_tables(conn)
    row = conn.execute(
        "SELECT * FROM archive_collection_memberships WHERE id = ?",
        (int(membership_id),),
    ).fetchone()
    if not row:
        raise ValueError("membership_not_found")
    return dict(row)


def get_membership_by_reference(conn: sqlite3.Connection, membership_reference: str) -> dict[str, Any]:
    ensure_membership_tables(conn)
    reference = validate_membership_reference(membership_reference)
    row = conn.execute(
        "SELECT * FROM archive_collection_memberships WHERE membership_reference = ?",
        (reference,),
    ).fetchone()
    if not row:
        raise ValueError("membership_not_found")
    return dict(row)


def membership_history(conn: sqlite3.Connection, membership_id: int | str) -> list[dict[str, Any]]:
    ensure_membership_tables(conn)
    rows = conn.execute(
        """
        SELECT * FROM archive_collection_membership_history
        WHERE membership_id = ?
        ORDER BY timestamp ASC, id ASC
        """,
        (int(membership_id),),
    ).fetchall()
    return [dict(row) for row in rows]


def _load_document(document_id: str, *, root: Path | None = None) -> dict[str, Any]:
    try:
        return load_pending_document(str(document_id), root=root)
    except ValueError as exc:
        raise ValueError("membership_document_not_found") from exc


def enrich_membership(
    conn: sqlite3.Connection,
    membership: dict[str, Any],
    *,
    root: Path | None = None,
) -> dict[str, Any]:
    item = dict(membership)
    collection = ac.get_collection(conn, item["collection_id"])
    member_type = normalize_member_type(item.get("member_type") or "published_document")
    member_reference = str(item.get("member_reference") or item.get("document_id") or "").strip()
    public_member = None
    try:
        public_member = resolve_public_member(conn, member_type, member_reference, root=root)
    except ValueError:
        public_member = None
    item["collection_reference"] = collection.get("public_reference")
    item["collection_title"] = collection.get("title")
    item["collection_is_public"] = int(collection.get("is_public") or 0)
    item["collection_is_active"] = int(collection.get("is_active") or 0)
    item["member_type"] = member_type
    item["member_type_label"] = member_type_label(member_type)
    item["member_reference"] = member_reference
    item["member_public_reference"] = member_reference
    item["member_title"] = member_reference
    item["member_summary"] = None
    item["member_status_label"] = "Not publicly available"
    item["member_format"] = "—"
    item["member_url"] = ""
    item["member_publicly_eligible"] = False
    if public_member:
        for key, value in public_member.items():
            if key not in {"document", "record", "association"}:
                item[key] = value
        item["member_publicly_eligible"] = True
    document = public_member.get("document") if public_member else None
    if not document and member_type == "published_document":
        try:
            document = _load_document(member_reference, root=root)
        except ValueError:
            document = None
    item["document_title"] = (document or {}).get("title")
    item["document_reference"] = (document or {}).get("reference_identifier")
    item["document_filename"] = (document or {}).get("original_filename")
    item["document_status"] = (document or {}).get("status")
    item["document_status_label"] = STATUS_LABELS.get(str((document or {}).get("status") or ""), str((document or {}).get("status") or "—"))
    item["document_format"] = document_type_label((document or {}).get("document_type")) if document else "—"
    item["document_publicly_eligible"] = bool(document and document.get("status") == "published")
    item["publicly_eligible"] = (
        int(item.get("is_active") or 0) == 1
        and item.get("membership_status") == "active"
        and int(collection.get("is_active") or 0) == 1
        and int(collection.get("is_public") or 0) == 1
        and item.get("member_publicly_eligible")
    )
    return item


def list_collection_memberships(
    conn: sqlite3.Connection,
    collection_id: int | str,
    *,
    root: Path | None = None,
) -> list[dict[str, Any]]:
    ensure_membership_tables(conn)
    rows = [
        dict(row)
        for row in conn.execute(
            """
            SELECT * FROM archive_collection_memberships
            WHERE collection_id = ?
            ORDER BY
              CASE WHEN display_sequence IS NULL THEN 1 ELSE 0 END ASC,
              display_sequence ASC,
              created_at ASC,
              membership_reference ASC
            """,
            (int(collection_id),),
        ).fetchall()
    ]
    return [enrich_membership(conn, row, root=root) for row in rows]


def list_public_collection_memberships(
    conn: sqlite3.Connection,
    collection_id: int | str,
    *,
    root: Path | None = None,
) -> list[dict[str, Any]]:
    return [
        item
        for item in collection_sequence(conn, collection_id, root=root, public_only=True)["members"]
        if item.get("publicly_eligible")
    ]


def _active_position_conflict(
    conn: sqlite3.Connection,
    *,
    collection_id: int,
    display_sequence: int,
    exclude_id: int | None = None,
) -> dict[str, Any] | None:
    params: list[Any] = [collection_id, display_sequence]
    extra = ""
    if exclude_id is not None:
        extra = "AND id != ?"
        params.append(exclude_id)
    row = conn.execute(
        f"""
        SELECT * FROM archive_collection_memberships
        WHERE collection_id = ? AND display_sequence = ?
          AND is_active = 1 AND membership_status = 'active' {extra}
        ORDER BY created_at ASC, membership_reference ASC
        LIMIT 1
        """,
        params,
    ).fetchone()
    return dict(row) if row else None


def _sequence_sort_key(item: dict[str, Any]) -> tuple[int, int, str, str]:
    sequence = _sequence_int(item.get("display_sequence"))
    return (
        1 if sequence is None else 0,
        sequence if sequence is not None else 999999999,
        str(item.get("created_at") or ""),
        str(item.get("membership_reference") or ""),
    )


def _sequence_eligible(item: dict[str, Any], *, public_only: bool = False) -> bool:
    if int(item.get("is_active") or 0) != 1:
        return False
    if item.get("membership_status") != "active":
        return False
    if int(item.get("collection_is_active") or 0) != 1:
        return False
    if public_only and not item.get("publicly_eligible"):
        return False
    return True


def collection_sequence(
    conn: sqlite3.Connection,
    collection_id: int | str,
    *,
    root: Path | None = None,
    public_only: bool = False,
) -> dict[str, Any]:
    members = [
        item
        for item in list_collection_memberships(conn, collection_id, root=root)
        if _sequence_eligible(item, public_only=public_only)
    ]
    members = sorted(members, key=_sequence_sort_key)
    positions = [_sequence_int(item.get("display_sequence")) for item in members]
    invalid_positions = [
        item.get("membership_reference")
        for item, position in zip(members, positions)
        if position is None or position <= 0
    ]
    duplicates: list[int] = []
    seen: set[int] = set()
    for position in positions:
        if position is None or position <= 0:
            continue
        if position in seen and position not in duplicates:
            duplicates.append(position)
        seen.add(position)
    valid_positions = [position for position in positions if position is not None and position > 0]
    missing_positions: list[int] = []
    if valid_positions:
        expected = set(range(1, max(valid_positions) + 1))
        missing_positions = sorted(expected.difference(valid_positions))
    if not members:
        state = "empty"
    elif invalid_positions:
        state = "invalid_position"
    elif len(members) == 1:
        state = "single_member"
    elif duplicates:
        state = "duplicate_position"
    elif valid_positions == list(range(1, len(members) + 1)):
        state = "continuous"
    else:
        state = "gap_present"

    total = len(members)
    for index, item in enumerate(members):
        item["sequence_position"] = index + 1
        item["sequence_total"] = total
        item["previous_membership_reference"] = members[index - 1]["membership_reference"] if index > 0 else None
        item["previous_member_title"] = members[index - 1].get("member_title") if index > 0 else None
        item["previous_member_url"] = members[index - 1].get("member_url") if index > 0 else None
        item["previous_document_id"] = members[index - 1].get("document_id") if index > 0 else None
        item["previous_document_title"] = members[index - 1].get("document_title") if index > 0 else None
        item["next_membership_reference"] = members[index + 1]["membership_reference"] if index < total - 1 else None
        item["next_member_title"] = members[index + 1].get("member_title") if index < total - 1 else None
        item["next_member_url"] = members[index + 1].get("member_url") if index < total - 1 else None
        item["next_document_id"] = members[index + 1].get("document_id") if index < total - 1 else None
        item["next_document_title"] = members[index + 1].get("document_title") if index < total - 1 else None

    return {
        "state": state,
        "state_label": CONTINUITY_STATES[state],
        "active_member_count": total,
        "first_position": valid_positions[0] if valid_positions else None,
        "last_position": valid_positions[-1] if valid_positions else None,
        "missing_positions": missing_positions,
        "duplicate_positions": duplicates,
        "invalid_memberships": invalid_positions,
        "members": members,
    }


def sequence_neighbors(
    conn: sqlite3.Connection,
    membership_reference: str,
    *,
    root: Path | None = None,
    public_only: bool = False,
) -> dict[str, Any]:
    membership = get_membership_by_reference(conn, membership_reference)
    sequence = collection_sequence(conn, membership["collection_id"], root=root, public_only=public_only)
    for item in sequence["members"]:
        if item.get("membership_reference") == membership["membership_reference"]:
            return {"membership": item, "sequence": sequence}
    return {"membership": enrich_membership(conn, membership, root=root), "sequence": sequence}


def _active_duplicate_exists(
    conn: sqlite3.Connection,
    *,
    collection_id: int,
    member_type: str,
    member_reference: str,
    exclude_id: int | None = None,
) -> bool:
    params: list[Any] = [collection_id, member_type, member_reference]
    extra = ""
    if exclude_id is not None:
        extra = "AND id != ?"
        params.append(exclude_id)
    row = conn.execute(
        f"""
        SELECT id FROM archive_collection_memberships
        WHERE collection_id = ?
          AND COALESCE(NULLIF(member_type, ''), 'published_document') = ?
          AND COALESCE(NULLIF(member_reference, ''), document_id) = ?
          AND is_active = 1
          AND membership_status != 'inactive' {extra}
        LIMIT 1
        """,
        params,
    ).fetchone()
    return row is not None


def create_membership(
    conn: sqlite3.Connection,
    *,
    collection_id: int | str,
    document_id: str | None = None,
    member_type: str | None = None,
    member_reference: str | None = None,
    actor: str,
    membership_note: str | None = None,
    section_label: str | None = None,
    curator_note: str | None = None,
    display_sequence: Any = None,
    effective_from: str | None = None,
    effective_to: str | None = None,
    created_at: str | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    ensure_membership_tables(conn)
    actor_value = _clean_required(actor, "membership_actor_required")
    collection = ac.get_collection(conn, collection_id)
    normalized_member_type = normalize_member_type(member_type or "published_document")
    selected_reference = member_reference if member_reference not in (None, "") else document_id
    normalized_member_reference = _validate_public_member_reference(
        conn,
        normalized_member_type,
        selected_reference,
        root=root,
    )
    normalized_document_id = (
        normalized_member_reference
        if normalized_member_type == "published_document"
        else normalized_member_reference
    )
    collection_id_int = int(collection["id"])
    if _active_duplicate_exists(
        conn,
        collection_id=collection_id_int,
        member_type=normalized_member_type,
        member_reference=normalized_member_reference,
    ):
        raise ValueError("membership_duplicate_active")
    timestamp = created_at or ac.utc_now()
    cursor = conn.execute(
        """
        INSERT INTO archive_collection_memberships (
            membership_reference, collection_id, document_id, member_type, member_reference, created_at,
            created_by, updated_at, updated_by, membership_status,
            membership_note, section_label, curator_note, display_sequence, effective_from, effective_to, is_active
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?, ?, ?, ?, ?, 1)
        """,
        (
            generate_membership_reference(conn, timestamp),
            collection_id_int,
            normalized_document_id,
            normalized_member_type,
            normalized_member_reference,
            timestamp,
            actor_value,
            timestamp,
            actor_value,
            _clean_optional(membership_note),
            _clean_optional(section_label),
            _clean_optional(curator_note),
            _normalize_sequence(display_sequence),
            _clean_optional(effective_from),
            _clean_optional(effective_to),
        ),
    )
    membership_id = int(cursor.lastrowid)
    membership = get_membership(conn, membership_id)
    _record_history(
        conn,
        membership_id=membership_id,
        action_type="created",
        actor=actor_value,
        timestamp=timestamp,
        previous_state=None,
        new_state=_membership_state(membership),
        note=membership_note or "Collection membership created.",
    )
    conn.commit()
    return enrich_membership(conn, membership, root=root)


def transition_membership(
    conn: sqlite3.Connection,
    membership_reference: str,
    *,
    new_status: str,
    actor: str,
    note: str | None = None,
    timestamp: str | None = None,
    display_sequence: Any = None,
    root: Path | None = None,
) -> dict[str, Any]:
    ensure_membership_tables(conn)
    actor_value = _clean_required(actor, "membership_actor_required")
    status = str(new_status or "").strip().lower()
    if status not in MEMBERSHIP_STATUSES:
        raise ValueError("membership_status_invalid")
    previous = get_membership_by_reference(conn, membership_reference)
    current = str(previous.get("membership_status") or "")
    if status not in VALID_TRANSITIONS.get(current, set()):
        raise ValueError("membership_transition_invalid")
    action_type = {
        ("draft", "reviewed"): "reviewed",
        ("reviewed", "approved"): "approved",
        ("approved", "active"): "activated",
        ("active", "inactive"): "removed",
        ("inactive", "active"): "restored",
    }[(current, status)]
    now = timestamp or ac.utc_now()
    is_active = 0 if status == "inactive" else 1
    sequence = previous.get("display_sequence")
    if status == "active":
        if _active_duplicate_exists(
            conn,
            collection_id=int(previous["collection_id"]),
            member_type=normalize_member_type(previous.get("member_type") or "published_document"),
            member_reference=str(previous.get("member_reference") or previous.get("document_id") or ""),
            exclude_id=int(previous["id"]),
        ):
            raise ValueError("membership_duplicate_active")
        if display_sequence not in (None, ""):
            sequence = _normalize_positive_sequence(display_sequence)
        else:
            sequence = _normalize_positive_sequence(sequence)
        conflict = _active_position_conflict(
            conn,
            collection_id=int(previous["collection_id"]),
            display_sequence=int(sequence),
            exclude_id=int(previous["id"]),
        )
        if conflict:
            if current == "inactive":
                raise ValueError("collection_membership_restore_position_conflict")
            raise ValueError("collection_membership_sequence_conflict")
    conn.execute(
        """
        UPDATE archive_collection_memberships
        SET membership_status = ?, is_active = ?, display_sequence = ?, updated_at = ?, updated_by = ?
        WHERE id = ?
        """,
        (status, is_active, sequence, now, actor_value, int(previous["id"])),
    )
    updated = get_membership(conn, previous["id"])
    _record_history(
        conn,
        membership_id=int(previous["id"]),
        action_type=action_type,
        actor=actor_value,
        timestamp=now,
        previous_state=_membership_state(previous),
        new_state=_membership_state(updated),
        note=note or MEMBERSHIP_ACTION_LABELS[action_type],
    )
    conn.commit()
    return enrich_membership(conn, updated, root=root)


def update_sequence(
    conn: sqlite3.Connection,
    membership_reference: str,
    *,
    display_sequence: Any,
    actor: str,
    note: str | None = None,
    timestamp: str | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    ensure_membership_tables(conn)
    actor_value = _clean_required(actor, "membership_actor_required")
    note_value = _clean_required(note, "collection_membership_sequence_note_required")
    previous = get_membership_by_reference(conn, membership_reference)
    sequence = _normalize_positive_sequence(display_sequence)
    if previous.get("membership_status") == "active" and int(previous.get("is_active") or 0) == 1:
        conflict = _active_position_conflict(
            conn,
            collection_id=int(previous["collection_id"]),
            display_sequence=sequence,
            exclude_id=int(previous["id"]),
        )
        if conflict:
            raise ValueError("collection_membership_sequence_conflict")
    now = timestamp or ac.utc_now()
    conn.execute(
        """
        UPDATE archive_collection_memberships
        SET display_sequence = ?, updated_at = ?, updated_by = ?
        WHERE id = ?
        """,
        (sequence, now, actor_value, int(previous["id"])),
    )
    updated = get_membership(conn, previous["id"])
    _record_history(
        conn,
        membership_id=int(previous["id"]),
        action_type="sequence_changed",
        actor=actor_value,
        timestamp=now,
        previous_state=_membership_state(previous),
        new_state=_membership_state(updated),
        note=note_value,
    )
    conn.commit()
    return enrich_membership(conn, updated, root=root)


def status_label(value: Any) -> str:
    return MEMBERSHIP_STATUSES.get(str(value or ""), str(value or "") or "—")
