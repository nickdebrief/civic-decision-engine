"""Relationship-owned correction evidence for Record-Document Associations.

Corrections add accountable evidence about an earlier association decision.
They never rewrite the original association, history, or Stage 61 decision.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Mapping

from api import record_document_association_decisions as rdd
from api import record_document_associations as rda
from api.governed_decisions import (
    GovernedDecision,
    GovernedEvidenceReference,
    GovernedSubjectReference,
)


DEFAULT_DB_PATH = Path(os.getenv("RECORDS_DB_PATH", "records.db"))
SUBJECT_TYPE = "record_document_association"
CORRECTION_CATEGORY = "erroneous_association_binding"
CORRECTION_CATEGORIES = frozenset({CORRECTION_CATEGORY})
RESOLUTION_MODES = frozenset({"reuse_existing", "create_new"})


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _row(row: sqlite3.Row | Mapping[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    result = dict(row)
    for field in ("evidence_references", "request_payload"):
        raw = result.pop(f"{field}_json", None)
        try:
            result[field] = json.loads(raw) if raw else ([] if field == "evidence_references" else {})
        except (TypeError, json.JSONDecodeError):
            result[field] = [] if field == "evidence_references" else None
    return result


def ensure_correction_tables(conn: sqlite3.Connection) -> None:
    """Create only additive correction persistence on a governed write path."""

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS record_document_association_corrections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            idempotency_key TEXT NOT NULL UNIQUE,
            original_association_id INTEGER NOT NULL,
            original_decision_id INTEGER,
            correction_category TEXT NOT NULL,
            resolution_mode TEXT NOT NULL,
            rationale TEXT NOT NULL,
            actor TEXT NOT NULL,
            actor_role TEXT NOT NULL,
            decided_at TEXT NOT NULL,
            evidence_references_json TEXT NOT NULL DEFAULT '[]',
            context_reference TEXT,
            replacement_association_id INTEGER,
            request_payload_json TEXT NOT NULL,
            FOREIGN KEY (original_association_id)
                REFERENCES record_document_associations(id),
            FOREIGN KEY (original_decision_id)
                REFERENCES record_document_association_decisions(id),
            FOREIGN KEY (replacement_association_id)
                REFERENCES record_document_associations(id)
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_association_corrections_original
        ON record_document_association_corrections(original_association_id, id)
        """
    )


def _required(value: Any, error: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(error)
    return normalized


def _evidence(value: Any) -> list[dict[str, str]]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise ValueError("association_correction_evidence_invalid")
    normalized: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise ValueError("association_correction_evidence_invalid")
        reference_type = _required(
            item.get("reference_type"),
            "association_correction_evidence_type_required",
        )
        reference_id = _required(
            item.get("reference_id"),
            "association_correction_evidence_id_required",
        )
        normalized.append(
            {"reference_type": reference_type, "reference_id": reference_id}
        )
    return sorted(normalized, key=lambda item: (item["reference_type"], item["reference_id"]))


def _canonical_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    result["evidence_references"] = _evidence(result.get("evidence_references"))
    if result.get("context_reference") is not None:
        result["context_reference"] = str(result["context_reference"]).strip() or None
    return result


def resolve_idempotency_key(supplied: str | None, payload: Mapping[str, Any]) -> str:
    normalized = str(supplied or "").strip()
    if normalized:
        return normalized
    return "rda-correction-" + hashlib.sha256(_json(payload).encode("utf-8")).hexdigest()


def _get_by_key(conn: sqlite3.Connection, key: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM record_document_association_corrections WHERE idempotency_key = ?",
        (key,),
    ).fetchone()
    return _row(row)


def get_correction(conn: sqlite3.Connection, correction_id: int | str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM record_document_association_corrections WHERE id = ?",
        (int(correction_id),),
    ).fetchone()
    if row is None:
        raise ValueError("association_correction_not_found")
    return _row(row) or {}


def list_corrections(conn: sqlite3.Connection, association_id: int | str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT * FROM record_document_association_corrections
        WHERE original_association_id = ?
        ORDER BY decided_at ASC, id ASC
        """,
        (int(association_id),),
    ).fetchall()
    return [_row(row) or {} for row in rows]


def _original_decision(
    conn: sqlite3.Connection,
    association_id: int,
    *,
    legacy_evidence_acknowledged: bool,
) -> dict[str, Any] | None:
    decisions = rdd.list_decisions(conn, association_id)
    creation = [item for item in decisions if item.get("decision_type") == "association_created"]
    if len(creation) > 1:
        raise ValueError("association_correction_multiple_creation_decisions")
    if creation:
        return creation[0]
    if not legacy_evidence_acknowledged:
        raise ValueError("association_correction_original_decision_missing")
    return None


def _active_replacement(
    conn: sqlite3.Connection,
    original: Mapping[str, Any],
    replacement_id: int | str,
) -> dict[str, Any]:
    replacement = rda.get_association(conn, replacement_id)
    if int(replacement["id"]) == int(original["id"]):
        raise ValueError("association_correction_replacement_is_original")
    if str(replacement.get("record_reference") or "") != str(original.get("record_reference") or ""):
        raise ValueError("association_correction_replacement_incompatible")
    if int(replacement.get("is_active") or 0) != 1:
        raise ValueError("association_correction_replacement_inactive")
    return replacement


def _new_target(
    conn: sqlite3.Connection,
    original: Mapping[str, Any],
    *,
    record_reference: str,
    document_id: str,
    relationship_type: str,
    root: Path | None,
    reject_active_duplicate: bool = True,
) -> dict[str, Any]:
    reference = rda.validate_public_record_reference(conn, record_reference)
    if reference != str(original.get("record_reference") or ""):
        raise ValueError("association_correction_replacement_incompatible")
    document = rda.published_document_context(document_id, root=root)
    if document is None:
        raise ValueError("association_correction_replacement_document_invalid")
    relationship = rda.validate_relationship_type(relationship_type)
    if reject_active_duplicate:
        duplicate = conn.execute(
            """
            SELECT id FROM record_document_associations
            WHERE record_reference = ? AND document_id = ?
              AND relationship_type = ? AND is_active = 1
            LIMIT 1
            """,
            (reference, document["intake_id"], relationship),
        ).fetchone()
        if duplicate is not None:
            raise ValueError("association_correction_replacement_already_exists")
    return {
        "record_reference": reference,
        "document_id": document["intake_id"],
        "relationship_type": relationship,
    }


def _insert_correction(
    conn: sqlite3.Connection,
    *,
    key: str,
    original_association_id: int,
    original_decision_id: int | None,
    correction_category: str,
    resolution_mode: str,
    rationale: str,
    actor: str,
    actor_role: str,
    decided_at: str,
    evidence_references: list[dict[str, str]],
    context_reference: str | None,
    request_payload: Mapping[str, Any],
) -> dict[str, Any]:
    cursor = conn.execute(
        """
        INSERT INTO record_document_association_corrections (
            idempotency_key, original_association_id, original_decision_id,
            correction_category, resolution_mode, rationale, actor, actor_role,
            decided_at, evidence_references_json, context_reference,
            request_payload_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            key,
            original_association_id,
            original_decision_id,
            correction_category,
            resolution_mode,
            rationale,
            actor,
            actor_role,
            decided_at,
            _json(evidence_references),
            context_reference,
            _json(request_payload),
        ),
    )
    return get_correction(conn, int(cursor.lastrowid))


def correct_association(
    conn: sqlite3.Connection,
    *,
    original_association_id: int | str,
    resolution_mode: str,
    replacement_association_id: int | str | None = None,
    replacement_record_reference: str | None = None,
    replacement_document_id: str | None = None,
    replacement_relationship_type: str | None = None,
    rationale: str,
    actor: str,
    actor_role: str,
    evidence_references: list[Mapping[str, str]] | None = None,
    context_reference: str | None = None,
    idempotency_key: str | None = None,
    decided_at: str | None = None,
    root: Path | None = None,
    legacy_evidence_acknowledged: bool = False,
    _commit: bool = True,
) -> dict[str, Any]:
    try:
        rda.ensure_association_tables(conn)
        rdd.ensure_decision_table(conn)
        ensure_correction_tables(conn)
        original = rda.get_association(conn, original_association_id)
        original_id = int(original["id"])
        original_decision = _original_decision(
            conn,
            original_id,
            legacy_evidence_acknowledged=legacy_evidence_acknowledged,
        )
        category = CORRECTION_CATEGORY
        mode = _required(resolution_mode, "association_correction_resolution_mode_required")
        if mode not in RESOLUTION_MODES:
            raise ValueError("association_correction_resolution_mode_invalid")
        actor_value = _required(actor, "association_correction_actor_required")
        role_value = _required(actor_role, "association_correction_actor_role_required")
        rationale_value = _required(rationale, "association_correction_rationale_required")
        evidence = _evidence(evidence_references)
        context = str(context_reference or "").strip() or None

        replacement = None
        target = None
        if mode == "reuse_existing":
            if replacement_association_id is None:
                raise ValueError("association_correction_replacement_required")
            replacement = _active_replacement(conn, original, replacement_association_id)
        else:
            if replacement_association_id is not None:
                raise ValueError("association_correction_replacement_id_not_allowed")
            target = _new_target(
                conn,
                original,
                record_reference=_required(
                    replacement_record_reference,
                    "association_correction_replacement_record_required",
                ),
                document_id=_required(
                    replacement_document_id,
                    "association_correction_replacement_document_required",
                ),
                relationship_type=_required(
                    replacement_relationship_type,
                    "association_correction_replacement_relationship_required",
                ),
                root=root,
                reject_active_duplicate=False,
            )

        payload = _canonical_payload(
            {
                "original_association_id": original_id,
                "original_decision_id": original_decision.get("id") if original_decision else None,
                "correction_category": category,
                "resolution_mode": mode,
                "replacement_association_id": int(replacement["id"]) if replacement else None,
                "replacement_target": target,
                "rationale": rationale_value,
                "actor": actor_value,
                "actor_role": role_value,
                "evidence_references": evidence,
                "context_reference": context,
            }
        )
        key = resolve_idempotency_key(idempotency_key, payload)
        existing = _get_by_key(conn, key)
        if existing is not None:
            if existing.get("request_payload") != payload:
                raise ValueError("association_correction_idempotency_conflict")
            return existing
        if int(original.get("is_active") or 0) != 1:
            raise ValueError("association_correction_original_inactive")
        if target is not None:
            duplicate = conn.execute(
                """
                SELECT id FROM record_document_associations
                WHERE record_reference = ? AND document_id = ?
                  AND relationship_type = ? AND is_active = 1
                LIMIT 1
                """,
                (target["record_reference"], target["document_id"], target["relationship_type"]),
            ).fetchone()
            if duplicate is not None:
                raise ValueError("association_correction_replacement_already_exists")

        correction = _insert_correction(
            conn,
            key=key,
            original_association_id=original_id,
            original_decision_id=int(original_decision["id"]) if original_decision else None,
            correction_category=category,
            resolution_mode=mode,
            rationale=rationale_value,
            actor=actor_value,
            actor_role=role_value,
            decided_at=decided_at or rda.utc_now(),
            evidence_references=evidence,
            context_reference=context,
            request_payload=payload,
        )

        child_deactivation_key = f"{key}:deactivation"
        rda.deactivate_association(
            conn,
            original_id,
            actor=actor_value,
            actor_role=role_value,
            note="Association deactivated through governed correction.",
            rationale=rationale_value,
            idempotency_key=child_deactivation_key,
            deactivated_at=decided_at,
            _commit=False,
        )

        if mode == "create_new":
            assert target is not None
            replacement = rda.create_association(
                conn,
                record_reference=target["record_reference"],
                document_id=target["document_id"],
                relationship_type=target["relationship_type"],
                public_label=None,
                public_note=None,
                admin_note=f"Created through correction of association {original_id}.",
                is_public=original.get("is_public"),
                actor=actor_value,
                actor_role=role_value,
                rationale=rationale_value,
                idempotency_key=f"{key}:creation",
                created_at=decided_at,
                root=root,
                _commit=False,
            )
        assert replacement is not None
        conn.execute(
            """
            UPDATE record_document_association_corrections
            SET replacement_association_id = ?
            WHERE id = ?
            """,
            (int(replacement["id"]), int(correction["id"])),
        )
        result = get_correction(conn, int(correction["id"]))
        if _commit:
            conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise


def adapt_correction(correction: Mapping[str, Any]) -> GovernedDecision:
    evidence = tuple(
        GovernedEvidenceReference(
            str(reference.get("reference_type") or ""),
            str(reference.get("reference_id") or ""),
        )
        for reference in correction.get("evidence_references") or []
    )
    return GovernedDecision(
        decision_id=f"record-document-association-correction:{correction.get('id')}",
        subject=GovernedSubjectReference(
            SUBJECT_TYPE,
            str(correction.get("original_association_id") or ""),
        ),
        decision_type="association_corrected",
        previous_state="active",
        resulting_state="inactive",
        actor=str(correction.get("actor") or ""),
        actor_role=str(correction.get("actor_role") or ""),
        decided_at=str(correction.get("decided_at") or ""),
        rationale=str(correction.get("rationale") or ""),
        evidence_references=evidence,
        context_reference=str(correction.get("context_reference") or "") or None,
        idempotency_key=str(correction.get("idempotency_key") or "") or None,
    )


def read_correction_preview(
    association_id: int | str,
    *,
    db_path: Path | str | None = None,
) -> dict[str, Any]:
    """Read correction context without initializing any persistence."""

    path = Path(db_path or os.getenv("RECORDS_DB_PATH") or DEFAULT_DB_PATH)
    result: dict[str, Any] = {
        "status": "ok",
        "association": None,
        "corrections": [],
        "candidates": [],
        "correction_table_present": False,
    }
    if not path.is_file():
        result["status"] = "database_unavailable"
        return result
    try:
        conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
    except sqlite3.Error:
        result["status"] = "database_unavailable"
        return result
    try:
        association_table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            ("record_document_associations",),
        ).fetchone()
        if association_table is None:
            result["status"] = "association_table_absent"
            return result
        association = conn.execute(
            "SELECT * FROM record_document_associations WHERE id = ?",
            (int(association_id),),
        ).fetchone()
        if association is None:
            result["status"] = "association_not_found"
            return result
        result["association"] = dict(association)
        result["candidates"] = [
            dict(row)
            for row in conn.execute(
                """
                SELECT * FROM record_document_associations
                WHERE record_reference = ? AND is_active = 1 AND id != ?
                ORDER BY id ASC
                """,
                (association["record_reference"], int(association_id)),
            ).fetchall()
        ]
        correction_table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            ("record_document_association_corrections",),
        ).fetchone()
        if correction_table is None:
            return result
        result["correction_table_present"] = True
        result["corrections"] = [
            _row(row) or {}
            for row in conn.execute(
                """
                SELECT * FROM record_document_association_corrections
                WHERE original_association_id = ? ORDER BY decided_at ASC, id ASC
                """,
                (int(association_id),),
            ).fetchall()
        ]
        return result
    finally:
        conn.close()
