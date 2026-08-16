"""Stage 64 human-recorded, governed allegation persistence.

An allegation records an attributed proposition.  It does not establish that
the proposition is true and never mutates the governed source material.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = "stage64.human_governed_allegation.v1"
AUTHORING_MODE = "human_recorded"
ALLEGATION_CATEGORIES = {
    "reported_conduct",
    "reported_omission",
    "reported_statement",
    "reported_condition",
    "reported_responsibility",
}
REPRESENTATION_MODES = {"verbatim", "faithful_paraphrase"}
REVIEW_DISPOSITIONS = {
    "accepted_as_attributed_allegation",
    "requires_attribution_correction",
    "not_accepted_as_attributed",
}
ALLEGATION_STATUSES = {
    "recorded",
    *REVIEW_DISPOSITIONS,
    "superseded",
    "withdrawn",
}
SOURCE_TYPES = {
    "published_document",
    "canonical_record",
    "record_document_association",
    "accepted_pattern_observation",
}
BINDING_ROLES = {
    "attribution_source",
    "contextual_source",
    "response_source",
    "contrary_source",
    "withdrawal_source",
}
WITHDRAWAL_TYPES = {
    "attributed_source_withdrawal",
    "administrative_attribution_correction",
}
CREATION_BINDING_ROLES = BINDING_ROLES - {"withdrawal_source"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _required(value: Any, error: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(error)
    return normalized


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?", (table_name,)
    ).fetchone() is not None


def _canonical_bindings(bindings: Any, *, creation: bool = True) -> list[dict[str, Any]]:
    if not isinstance(bindings, (list, tuple)) or not bindings:
        raise ValueError("governed_allegation_binding_required")
    result: list[dict[str, Any]] = []
    for item in bindings:
        if not isinstance(item, Mapping):
            raise ValueError("governed_allegation_binding_invalid")
        source_type = _required(item.get("source_type"), "governed_allegation_source_type_required")
        if source_type not in SOURCE_TYPES:
            raise ValueError("governed_allegation_source_type_invalid")
        source_id = _required(item.get("source_id"), "governed_allegation_source_id_required")
        role = _required(item.get("binding_role"), "governed_allegation_binding_role_required")
        if role not in BINDING_ROLES:
            raise ValueError("governed_allegation_binding_role_invalid")
        if creation and role not in CREATION_BINDING_ROLES:
            raise ValueError("governed_allegation_withdrawal_source_creation_invalid")
        result.append(
            {
                "source_type": source_type,
                "source_id": source_id,
                "binding_role": role,
                "source_version": (
                    str(item["source_version"]).strip()
                    if item.get("source_version") is not None
                    else None
                ),
                "source_timestamp": (
                    str(item["source_timestamp"]).strip()
                    if item.get("source_timestamp") is not None
                    else None
                ),
            }
        )
    result.sort(key=lambda item: (item["source_type"], item["source_id"], item["binding_role"]))
    identities = {(item["source_type"], item["source_id"], item["binding_role"]) for item in result}
    if len(identities) != len(result):
        raise ValueError("governed_allegation_duplicate_binding")
    return result


def _qualification_contract(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("governed_allegation_qualification_contract_required")
    expected = {
        "epistemic_label": "allegation",
        "attribution_present": True,
        "source_basis_present": True,
        "not_evidence": True,
        "not_observation": True,
        "not_inference": True,
        "not_determination": True,
        "not_confirmation": True,
        "alternatives_possible": True,
    }
    for key, expected_value in expected.items():
        if value.get(key) != expected_value:
            raise ValueError("governed_allegation_qualification_contract_incomplete")
    result = dict(expected)
    result["limitations"] = _required(
        value.get("limitations"), "governed_allegation_limitations_required"
    )
    return result


def _author_declaration(value: Any, *, actor: str, role: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or value.get("acknowledged") is not True:
        raise ValueError("governed_allegation_author_boundary_declaration_required")
    return {
        "authoring_mode": AUTHORING_MODE,
        "human_recorded": True,
        "attributed_source_identified": True,
        "no_truth_assertion": True,
        "acknowledged": True,
        "recorded_by": actor,
        "recorded_by_role": role,
    }


def _review_declaration(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or value.get("acknowledged") is not True:
        raise ValueError("governed_allegation_review_boundary_declaration_required")
    return {
        "attribution_reviewed": True,
        "faithful_representation_reviewed": True,
        "truth_not_confirmed": True,
        "acknowledged": True,
    }


def ensure_allegation_tables(conn: sqlite3.Connection) -> None:
    """Initialize Stage 64 only from an authenticated write path."""

    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS record_governed_allegations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            idempotency_key TEXT NOT NULL UNIQUE,
            schema_version TEXT NOT NULL,
            authoring_mode TEXT NOT NULL,
            allegation_category TEXT NOT NULL,
            allegation_text TEXT NOT NULL,
            representation_mode TEXT NOT NULL,
            representation_contract_json TEXT NOT NULL,
            attributed_source_label TEXT NOT NULL,
            attribution_context TEXT NOT NULL,
            subject_label TEXT NOT NULL,
            alleged_period TEXT,
            made_or_recorded_at TEXT,
            rationale TEXT NOT NULL,
            qualification TEXT NOT NULL,
            limitations TEXT NOT NULL,
            qualification_contract_json TEXT NOT NULL,
            author_boundary_declaration_json TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            created_by TEXT NOT NULL,
            created_by_role TEXT NOT NULL,
            request_payload_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS record_governed_allegation_bindings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            allegation_id INTEGER NOT NULL,
            source_type TEXT NOT NULL,
            source_id TEXT NOT NULL,
            binding_role TEXT NOT NULL,
            source_version TEXT,
            source_timestamp TEXT,
            FOREIGN KEY (allegation_id) REFERENCES record_governed_allegations(id),
            UNIQUE (allegation_id, source_type, source_id, binding_role)
        );
        CREATE TABLE IF NOT EXISTS record_governed_allegation_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            allegation_id INTEGER NOT NULL,
            disposition TEXT NOT NULL,
            reviewed_by TEXT NOT NULL,
            reviewed_by_role TEXT NOT NULL,
            rationale TEXT NOT NULL,
            boundary_declaration_json TEXT NOT NULL,
            is_self_review INTEGER NOT NULL,
            reviewed_at TEXT NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE,
            request_payload_json TEXT NOT NULL,
            FOREIGN KEY (allegation_id) REFERENCES record_governed_allegations(id)
        );
        CREATE TABLE IF NOT EXISTS record_governed_allegation_supersessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            allegation_id INTEGER NOT NULL,
            replacement_allegation_id INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            rationale TEXT NOT NULL,
            actor TEXT NOT NULL,
            actor_role TEXT NOT NULL,
            occurred_at TEXT NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE,
            request_payload_json TEXT NOT NULL,
            FOREIGN KEY (allegation_id) REFERENCES record_governed_allegations(id),
            FOREIGN KEY (replacement_allegation_id) REFERENCES record_governed_allegations(id)
        );
        CREATE TABLE IF NOT EXISTS record_governed_allegation_withdrawals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            allegation_id INTEGER NOT NULL,
            withdrawal_type TEXT NOT NULL,
            rationale TEXT NOT NULL,
            actor TEXT NOT NULL,
            actor_role TEXT NOT NULL,
            occurred_at TEXT NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE,
            request_payload_json TEXT NOT NULL,
            FOREIGN KEY (allegation_id) REFERENCES record_governed_allegations(id)
        );
        CREATE INDEX IF NOT EXISTS idx_governed_allegations_status
            ON record_governed_allegations(status, created_at);
        CREATE INDEX IF NOT EXISTS idx_governed_allegation_bindings_source
            ON record_governed_allegation_bindings(source_type, source_id, allegation_id);
        CREATE INDEX IF NOT EXISTS idx_governed_allegation_reviews_allegation
            ON record_governed_allegation_reviews(allegation_id, reviewed_at, id);
        CREATE INDEX IF NOT EXISTS idx_governed_allegation_supersessions_allegation
            ON record_governed_allegation_supersessions(allegation_id, occurred_at, id);
        CREATE INDEX IF NOT EXISTS idx_governed_allegation_withdrawals_allegation
            ON record_governed_allegation_withdrawals(allegation_id, occurred_at, id);
        """
    )


def _source_binding(
    conn: sqlite3.Connection,
    binding: Mapping[str, Any],
    *,
    document_root: Path | None = None,
) -> dict[str, Any]:
    source_type = str(binding["source_type"])
    source_id = str(binding["source_id"])
    version = binding.get("source_version")
    timestamp = binding.get("source_timestamp")
    if source_type == "record_document_association":
        from api.record_document_associations import get_association

        try:
            row = get_association(conn, int(source_id))
        except (ValueError, TypeError):
            raise ValueError("governed_allegation_source_not_found") from None
        timestamp = timestamp or row.get("created_at")
    elif source_type == "canonical_record":
        if not _table_exists(conn, "records"):
            raise ValueError("governed_allegation_source_not_found")
        row = conn.execute("SELECT * FROM records WHERE reference = ?", (source_id,)).fetchone()
        if row is None:
            raise ValueError("governed_allegation_source_not_found")
        version = version or (row["version"] if "version" in row.keys() else None)
        timestamp = timestamp or (row["generated_at"] if "generated_at" in row.keys() else None)
    elif source_type == "published_document":
        from api.document_intake import intake_root, load_published_document

        document = load_published_document(source_id, root=document_root or intake_root())
        if document is None:
            raise ValueError("governed_allegation_source_not_found")
        version = version or document.get("version")
        timestamp = timestamp or document.get("created_at") or document.get("published_at")
    elif source_type == "accepted_pattern_observation":
        if not _table_exists(conn, "record_pattern_observations"):
            raise ValueError("governed_allegation_source_not_found")
        row = conn.execute(
            "SELECT * FROM record_pattern_observations WHERE id = ?", (int(source_id),)
        ).fetchone()
        if row is None:
            raise ValueError("governed_allegation_source_not_found")
        if str(row["status"]) != "accepted":
            raise ValueError("governed_allegation_observation_not_accepted")
        timestamp = timestamp or row["created_at"]
    return {
        **dict(binding),
        "source_version": str(version).strip() if version not in (None, "") else None,
        "source_timestamp": str(timestamp).strip() if timestamp not in (None, "") else None,
    }


def _key(prefix: str, payload: Mapping[str, Any]) -> str:
    return prefix + hashlib.sha256(_json(payload).encode("utf-8")).hexdigest()


def _row(row: sqlite3.Row | Mapping[str, Any]) -> dict[str, Any]:
    result = dict(row)
    for field in (
        "representation_contract_json",
        "qualification_contract_json",
        "author_boundary_declaration_json",
        "request_payload_json",
    ):
        result[field] = json.loads(result[field]) if result.get(field) else None
    return result


def _event_status(conn: sqlite3.Connection, allegation_id: int, base: str) -> str:
    events: list[tuple[str, int, str]] = []
    for table, time_field, status_expression in (
        ("record_governed_allegation_reviews", "reviewed_at", "disposition"),
        ("record_governed_allegation_supersessions", "occurred_at", "'superseded'"),
        ("record_governed_allegation_withdrawals", "occurred_at", "'withdrawn'"),
    ):
        rows = conn.execute(
            f"SELECT id, {time_field}, {status_expression} FROM {table} WHERE allegation_id = ?",
            (allegation_id,),
        ).fetchall()
        events.extend((str(row[1]), int(row[0]), str(row[2])) for row in rows)
    if not events:
        return base
    events.sort(key=lambda item: (item[0], item[1], item[2]))
    return events[-1][2]


def _supersession_would_cycle(conn: sqlite3.Connection, allegation_id: int, replacement_id: int) -> bool:
    current = replacement_id
    seen: set[int] = set()
    while current not in seen:
        if current == allegation_id:
            return True
        seen.add(current)
        row = conn.execute(
            "SELECT replacement_allegation_id FROM record_governed_allegation_supersessions WHERE allegation_id = ? ORDER BY id DESC LIMIT 1",
            (current,),
        ).fetchone()
        if row is None:
            return False
        current = int(row[0])
    return False


def get_allegation(conn: sqlite3.Connection, allegation_id: int | str) -> dict[str, Any]:
    if not _table_exists(conn, "record_governed_allegations"):
        raise ValueError("governed_allegation_table_absent")
    row = conn.execute(
        "SELECT * FROM record_governed_allegations WHERE id = ?", (int(allegation_id),)
    ).fetchone()
    if row is None:
        raise ValueError("governed_allegation_not_found")
    result = _row(row)
    result["status"] = _event_status(conn, int(allegation_id), str(result["status"]))
    result["representation_contract"] = result.pop("representation_contract_json")
    result["qualification_contract"] = result.pop("qualification_contract_json")
    result["author_boundary_declaration"] = result.pop("author_boundary_declaration_json")
    result["request_payload"] = result.pop("request_payload_json")
    result["bindings"] = [dict(item) for item in conn.execute(
        "SELECT * FROM record_governed_allegation_bindings WHERE allegation_id = ? ORDER BY id",
        (int(allegation_id),),
    ).fetchall()]
    result["reviews"] = []
    for item in conn.execute(
        "SELECT * FROM record_governed_allegation_reviews WHERE allegation_id = ? ORDER BY id",
        (int(allegation_id),),
    ).fetchall():
        review = dict(item)
        review["boundary_declaration"] = json.loads(review.pop("boundary_declaration_json"))
        review["request_payload"] = json.loads(review.pop("request_payload_json"))
        result["reviews"].append(review)
    result["supersessions"] = [dict(item) for item in conn.execute(
        "SELECT * FROM record_governed_allegation_supersessions WHERE allegation_id = ? ORDER BY id",
        (int(allegation_id),),
    ).fetchall()]
    result["withdrawals"] = [dict(item) for item in conn.execute(
        "SELECT * FROM record_governed_allegation_withdrawals WHERE allegation_id = ? ORDER BY id",
        (int(allegation_id),),
    ).fetchall()]
    return result


def list_allegations(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    if not _table_exists(conn, "record_governed_allegations"):
        return []
    return [get_allegation(conn, row[0]) for row in conn.execute(
        "SELECT id FROM record_governed_allegations ORDER BY created_at, id"
    ).fetchall()]


def read_allegation_diagnostic(
    allegation_id: int | str | None = None, *, db_path: str | Path
) -> dict[str, Any]:
    """Read Stage 64 without creating tables or changing any persistence."""

    path = Path(db_path)
    if not path.is_file():
        return {"status": "database_unavailable", "allegations": []}
    try:
        conn = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    except sqlite3.Error:
        return {"status": "database_unavailable", "allegations": []}
    conn.row_factory = sqlite3.Row
    try:
        if not _table_exists(conn, "record_governed_allegations"):
            return {"status": "ok", "allegations": [], "allegation_table_present": False}
        if allegation_id is None:
            return {"status": "ok", "allegations": list_allegations(conn), "allegation_table_present": True}
        try:
            return {"status": "ok", "allegations": [get_allegation(conn, allegation_id)], "allegation_table_present": True}
        except ValueError:
            return {"status": "allegation_not_found", "allegations": [], "allegation_table_present": True}
    finally:
        conn.close()


def create_allegation(
    conn: sqlite3.Connection,
    *,
    allegation_category: str,
    allegation_text: str,
    representation_mode: str,
    representation_contract: Mapping[str, Any],
    attributed_source_label: str,
    attribution_context: str,
    subject_label: str,
    alleged_period: str | None,
    made_or_recorded_at: str | None,
    rationale: str,
    qualification: str,
    limitations: str,
    qualification_contract: Mapping[str, Any],
    bindings: list[Mapping[str, Any]],
    actor: str,
    actor_role: str,
    author_declaration: Mapping[str, Any],
    idempotency_key: str | None = None,
    created_at: str | None = None,
    document_root: Path | None = None,
    _commit: bool = True,
) -> dict[str, Any]:
    category = _required(allegation_category, "governed_allegation_category_required").lower()
    if category not in ALLEGATION_CATEGORIES:
        raise ValueError("governed_allegation_category_invalid")
    text = _required(allegation_text, "governed_allegation_text_required")
    mode = _required(representation_mode, "governed_allegation_representation_mode_required").lower()
    if mode not in REPRESENTATION_MODES:
        raise ValueError("governed_allegation_representation_mode_invalid")
    if not isinstance(representation_contract, Mapping) or representation_contract.get("human_verified") is not True:
        raise ValueError("governed_allegation_representation_contract_incomplete")
    if mode == "verbatim" and representation_contract.get("exact_source_wording") is not True:
        raise ValueError("governed_allegation_exact_wording_required")
    if mode == "faithful_paraphrase" and representation_contract.get("faithful_representation") is not True:
        raise ValueError("governed_allegation_faithful_representation_required")
    rep_contract = {
        "human_verified": True,
        "exact_source_wording": mode == "verbatim",
        "faithful_representation": mode == "faithful_paraphrase",
    }
    source_label = _required(attributed_source_label, "governed_allegation_attributed_source_required")
    context = _required(attribution_context, "governed_allegation_attribution_context_required")
    subject = _required(subject_label, "governed_allegation_subject_required")
    rationale_value = _required(rationale, "governed_allegation_rationale_required")
    qualification_value = _required(qualification, "governed_allegation_qualification_required")
    limitations_value = _required(limitations, "governed_allegation_limitations_required")
    actor_value = _required(actor, "governed_allegation_author_required")
    role_value = _required(actor_role, "governed_allegation_author_role_required")
    if not isinstance(qualification_contract, Mapping):
        raise ValueError("governed_allegation_qualification_contract_required")
    contract = _qualification_contract({**qualification_contract, "limitations": limitations_value})
    declaration = _author_declaration(author_declaration, actor=actor_value, role=role_value)
    normalized = [_source_binding(conn, item, document_root=document_root) for item in _canonical_bindings(bindings)]
    if not any(item["binding_role"] == "attribution_source" for item in normalized):
        raise ValueError("governed_allegation_attribution_source_required")
    payload = {
        "schema_version": SCHEMA_VERSION,
        "authoring_mode": AUTHORING_MODE,
        "allegation_category": category,
        "allegation_text": text,
        "representation_mode": mode,
        "representation_contract": rep_contract,
        "attributed_source_label": source_label,
        "attribution_context": context,
        "subject_label": subject,
        "alleged_period": str(alleged_period).strip() if alleged_period else None,
        "made_or_recorded_at": str(made_or_recorded_at).strip() if made_or_recorded_at else None,
        "rationale": rationale_value,
        "qualification": qualification_value,
        "limitations": limitations_value,
        "qualification_contract": contract,
        "bindings": normalized,
        "author_boundary_declaration": declaration,
    }
    key = str(idempotency_key or "").strip() or _key("stage64-allegation:", payload)
    ensure_allegation_tables(conn)
    existing = conn.execute(
        "SELECT * FROM record_governed_allegations WHERE idempotency_key = ?", (key,)
    ).fetchone()
    payload_json = _json(payload)
    if existing is not None:
        if str(existing["request_payload_json"]) != payload_json:
            raise ValueError("governed_allegation_idempotency_conflict")
        return get_allegation(conn, existing["id"])
    try:
        cursor = conn.execute(
            """INSERT INTO record_governed_allegations
            (idempotency_key, schema_version, authoring_mode, allegation_category,
             allegation_text, representation_mode, representation_contract_json,
             attributed_source_label, attribution_context, subject_label,
             alleged_period, made_or_recorded_at, rationale, qualification,
             limitations, qualification_contract_json, author_boundary_declaration_json,
             status, created_at, created_by, created_by_role, request_payload_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'recorded', ?, ?, ?, ?)""",
            (key, SCHEMA_VERSION, AUTHORING_MODE, category, text, mode, _json(rep_contract),
             source_label, context, subject, payload["alleged_period"], payload["made_or_recorded_at"],
             rationale_value, qualification_value, limitations_value, _json(contract),
             _json(declaration), str(created_at or utc_now()), actor_value, role_value, payload_json),
        )
        allegation_id = int(cursor.lastrowid)
        conn.executemany(
            """INSERT INTO record_governed_allegation_bindings
            (allegation_id, source_type, source_id, binding_role, source_version, source_timestamp)
            VALUES (?, ?, ?, ?, ?, ?)""",
            [(allegation_id, item["source_type"], item["source_id"], item["binding_role"], item["source_version"], item["source_timestamp"]) for item in normalized],
        )
        if _commit:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    return get_allegation(conn, allegation_id)


def review_allegation(
    conn: sqlite3.Connection,
    allegation_id: int | str,
    *,
    disposition: str,
    rationale: str,
    boundary_declaration: Mapping[str, Any],
    actor: str,
    actor_role: str,
    reviewed_at: str | None = None,
    idempotency_key: str | None = None,
    _commit: bool = True,
) -> dict[str, Any]:
    disposition_value = _required(disposition, "governed_allegation_review_disposition_required").lower()
    if disposition_value not in REVIEW_DISPOSITIONS:
        raise ValueError("governed_allegation_review_disposition_invalid")
    actor_value = _required(actor, "governed_allegation_reviewer_required")
    role_value = _required(actor_role, "governed_allegation_reviewer_role_required")
    rationale_value = _required(rationale, "governed_allegation_review_rationale_required")
    declaration = _review_declaration(boundary_declaration)
    allegation = get_allegation(conn, allegation_id)
    self_review = int(actor_value == str(allegation["created_by"]))
    payload = {
        "allegation_id": int(allegation_id),
        "disposition": disposition_value,
        "rationale": rationale_value,
        "boundary_declaration": declaration,
        "is_self_review": bool(self_review),
    }
    key = str(idempotency_key or "").strip() or _key("stage64-review:", payload)
    ensure_allegation_tables(conn)
    existing = conn.execute(
        "SELECT * FROM record_governed_allegation_reviews WHERE idempotency_key = ?", (key,)
    ).fetchone()
    payload_json = _json(payload)
    if existing is not None:
        if str(existing["request_payload_json"]) != payload_json:
            raise ValueError("governed_allegation_review_idempotency_conflict")
        return get_allegation(conn, allegation_id)
    if allegation["status"] in {"superseded", "withdrawn"}:
        raise ValueError("governed_allegation_review_terminal")
    try:
        conn.execute(
            """INSERT INTO record_governed_allegation_reviews
            (allegation_id, disposition, reviewed_by, reviewed_by_role, rationale,
             boundary_declaration_json, is_self_review, reviewed_at, idempotency_key,
             request_payload_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (int(allegation_id), disposition_value, actor_value, role_value, rationale_value,
             _json(declaration), self_review, str(reviewed_at or utc_now()), key, payload_json),
        )
        conn.execute(
            "UPDATE record_governed_allegations SET status = ? WHERE id = ?",
            (disposition_value, int(allegation_id)),
        )
        if _commit:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    return get_allegation(conn, allegation_id)


def supersede_allegation(
    conn: sqlite3.Connection,
    allegation_id: int | str,
    *,
    replacement_allegation_id: int | str,
    rationale: str,
    actor: str,
    actor_role: str,
    occurred_at: str | None = None,
    idempotency_key: str | None = None,
    _commit: bool = True,
) -> dict[str, Any]:
    original = get_allegation(conn, allegation_id)
    replacement_id = int(replacement_allegation_id)
    if int(allegation_id) == replacement_id:
        raise ValueError("governed_allegation_supersession_self_reference")
    replacement = get_allegation(conn, replacement_id)
    rationale_value = _required(rationale, "governed_allegation_supersession_rationale_required")
    actor_value = _required(actor, "governed_allegation_supersession_actor_required")
    role_value = _required(actor_role, "governed_allegation_supersession_role_required")
    payload = {
        "allegation_id": int(allegation_id),
        "replacement_allegation_id": int(replacement["id"]),
        "rationale": rationale_value,
    }
    key = str(idempotency_key or "").strip() or _key("stage64-supersession:", payload)
    ensure_allegation_tables(conn)
    existing = conn.execute(
        "SELECT * FROM record_governed_allegation_supersessions WHERE idempotency_key = ?", (key,)
    ).fetchone()
    payload_json = _json(payload)
    if existing is not None:
        if str(existing["request_payload_json"]) != payload_json:
            raise ValueError("governed_allegation_supersession_idempotency_conflict")
        return get_allegation(conn, allegation_id)
    if original["status"] in {"superseded", "withdrawn"}:
        raise ValueError("governed_allegation_supersession_terminal")
    if _supersession_would_cycle(conn, int(allegation_id), replacement_id):
        raise ValueError("governed_allegation_supersession_cycle")
    try:
        conn.execute(
            """INSERT INTO record_governed_allegation_supersessions
            (allegation_id, replacement_allegation_id, event_type, rationale, actor,
             actor_role, occurred_at, idempotency_key, request_payload_json)
            VALUES (?, ?, 'superseded', ?, ?, ?, ?, ?, ?)""",
            (int(allegation_id), replacement_id, rationale_value, actor_value, role_value,
             str(occurred_at or utc_now()), key, payload_json),
        )
        conn.execute(
            "UPDATE record_governed_allegations SET status = 'superseded' WHERE id = ?",
            (int(allegation_id),),
        )
        if _commit:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    return get_allegation(conn, allegation_id)


def withdraw_allegation(
    conn: sqlite3.Connection,
    allegation_id: int | str,
    *,
    withdrawal_type: str,
    rationale: str,
    withdrawal_bindings: list[Mapping[str, Any]],
    actor: str,
    actor_role: str,
    occurred_at: str | None = None,
    idempotency_key: str | None = None,
    _commit: bool = True,
    document_root: Path | None = None,
) -> dict[str, Any]:
    allegation = get_allegation(conn, allegation_id)
    withdrawal_type_value = _required(withdrawal_type, "governed_allegation_withdrawal_type_required").lower()
    if withdrawal_type_value not in WITHDRAWAL_TYPES:
        raise ValueError("governed_allegation_withdrawal_type_invalid")
    normalized = [_source_binding(conn, item, document_root=document_root) for item in _canonical_bindings(withdrawal_bindings, creation=False)]
    if not normalized or not all(item["binding_role"] == "withdrawal_source" for item in normalized):
        raise ValueError("governed_allegation_withdrawal_source_required")
    rationale_value = _required(rationale, "governed_allegation_withdrawal_rationale_required")
    actor_value = _required(actor, "governed_allegation_withdrawal_actor_required")
    role_value = _required(actor_role, "governed_allegation_withdrawal_role_required")
    payload = {
        "allegation_id": int(allegation_id),
        "withdrawal_type": withdrawal_type_value,
        "rationale": rationale_value,
        "withdrawal_bindings": normalized,
    }
    key = str(idempotency_key or "").strip() or _key("stage64-withdrawal:", payload)
    ensure_allegation_tables(conn)
    existing = conn.execute(
        "SELECT * FROM record_governed_allegation_withdrawals WHERE idempotency_key = ?", (key,)
    ).fetchone()
    payload_json = _json(payload)
    if existing is not None:
        if str(existing["request_payload_json"]) != payload_json:
            raise ValueError("governed_allegation_withdrawal_idempotency_conflict")
        return get_allegation(conn, allegation_id)
    if allegation["status"] in {"superseded", "withdrawn"}:
        raise ValueError("governed_allegation_withdrawal_terminal")
    try:
        conn.execute(
            """INSERT INTO record_governed_allegation_withdrawals
            (allegation_id, withdrawal_type, rationale, actor, actor_role, occurred_at,
             idempotency_key, request_payload_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (int(allegation_id), withdrawal_type_value, rationale_value, actor_value, role_value,
             str(occurred_at or utc_now()), key, payload_json),
        )
        conn.executemany(
            """INSERT INTO record_governed_allegation_bindings
            (allegation_id, source_type, source_id, binding_role, source_version, source_timestamp)
            VALUES (?, ?, ?, ?, ?, ?)""",
            [(int(allegation_id), item["source_type"], item["source_id"], item["binding_role"], item["source_version"], item["source_timestamp"]) for item in normalized],
        )
        conn.execute(
            "UPDATE record_governed_allegations SET status = 'withdrawn' WHERE id = ?",
            (int(allegation_id),),
        )
        if _commit:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    return get_allegation(conn, allegation_id)
