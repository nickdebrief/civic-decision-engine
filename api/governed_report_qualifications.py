"""Immutable Stage 75 governance qualifications for report versions."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Mapping

REVIEW_MODE_ENV = "CDE_GOVERNED_REPORT_REVIEW_MODE"
INDEPENDENT_MODE = "independent_multi_administrator"
SOLE_MODE = "sole_administrator"
MODES = {INDEPENDENT_MODE, SOLE_MODE}
DISCLOSURE_VERSION = "sole-admin-v1"
DISCLOSURE = (
    "Independent administrator review did not occur. This report was confirmed "
    "and approved by its creator under the declared sole-administrator operating "
    "constraint. It remains restricted to authorised internal use."
)
GATES = ("assembly", "privacy", "redaction", "approval")
PERSISTED_QUALIFICATION_FIELDS = frozenset({
    "report_id", "report_version_id", "specification_digest", "revision_number",
    "previous_qualification_id", "completed_gate", "review_mode",
    "operating_constraint", "creator_actor", "qualifier_actor", "rationale",
    "declaration", "disclosure_version", "distribution_restriction",
})
RENDERING_QUALIFICATION_FIELDS = frozenset({
    "review_mode", "disclosure_version", "disclosure", "qualification_id",
    "qualification_digest",
})
GATE_STATUS = {
    "assembly_reviewed": "assembly",
    "privacy_reviewed": "privacy",
    "redaction_reviewed": "redaction",
    "approved_for_generation": "approval",
}
SOLE_EVENTS = {
    "assembly": "creator_assembly_confirmed",
    "privacy": "creator_privacy_confirmed",
    "redaction": "creator_redaction_confirmed",
    "approval": "creator_generation_approved_with_limitation",
}
INDEPENDENT_EVENTS = {
    "assembly": "assembly_reviewed",
    "privacy": "privacy_reviewed",
    "redaction": "redaction_reviewed",
    "approval": "approved_for_generation",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def configured_review_mode() -> str:
    raw = os.getenv(REVIEW_MODE_ENV)
    if raw is None:
        return INDEPENDENT_MODE
    if not raw or raw != raw.strip() or raw not in MODES:
        raise ValueError("governed_report_review_mode_invalid")
    return raw


def ensure_qualification_tables(conn: sqlite3.Connection) -> None:
    existing = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name IN ('record_governed_report_qualifications','record_governed_report_qualification_events')").fetchone()[0]
    if int(existing) == 2:
        validate_qualification_tables(conn)
        return
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS record_governed_report_qualifications (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          report_id INTEGER NOT NULL,
          report_version_id INTEGER NOT NULL,
          specification_digest TEXT NOT NULL,
          revision_number INTEGER NOT NULL,
          previous_qualification_id INTEGER,
          completed_gate TEXT NOT NULL CHECK(completed_gate IN ('assembly','privacy','redaction','approval')),
          review_mode TEXT NOT NULL CHECK(review_mode IN ('independent_multi_administrator','sole_administrator')),
          operating_constraint TEXT NOT NULL,
          creator_actor TEXT NOT NULL,
          qualifier_actor TEXT NOT NULL,
          rationale TEXT NOT NULL,
          declaration_json TEXT NOT NULL,
          disclosure_version TEXT NOT NULL,
          distribution_restriction TEXT NOT NULL,
          qualification_payload_json TEXT NOT NULL,
          qualification_digest TEXT NOT NULL UNIQUE,
          qualification_state TEXT NOT NULL CHECK(qualification_state='final'),
          created_at TEXT NOT NULL,
          finalized_at TEXT NOT NULL,
          idempotency_key TEXT NOT NULL UNIQUE,
          FOREIGN KEY(report_id) REFERENCES record_governed_reports(id),
          FOREIGN KEY(report_version_id) REFERENCES record_governed_report_versions(id),
          FOREIGN KEY(previous_qualification_id) REFERENCES record_governed_report_qualifications(id),
          UNIQUE(report_version_id, revision_number)
        );
        CREATE TABLE IF NOT EXISTS record_governed_report_qualification_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          qualification_id INTEGER NOT NULL,
          report_id INTEGER NOT NULL,
          report_version_id INTEGER NOT NULL,
          event_type TEXT NOT NULL,
          actor TEXT NOT NULL,
          occurred_at TEXT NOT NULL,
          idempotency_key TEXT NOT NULL UNIQUE,
          payload_json TEXT NOT NULL,
          FOREIGN KEY(qualification_id) REFERENCES record_governed_report_qualifications(id)
        );
        CREATE INDEX IF NOT EXISTS idx_stage75_qualification_version
          ON record_governed_report_qualifications(report_version_id, revision_number);
        """
    )
    validate_qualification_tables(conn)


def validate_qualification_tables(conn: sqlite3.Connection) -> None:
    required = {
        "record_governed_report_qualifications": {
            "id": "INTEGER", "report_id": "INTEGER", "report_version_id": "INTEGER",
            "specification_digest": "TEXT", "revision_number": "INTEGER", "completed_gate": "TEXT",
            "previous_qualification_id": "INTEGER", "review_mode": "TEXT", "operating_constraint": "TEXT",
            "creator_actor": "TEXT", "qualifier_actor": "TEXT", "rationale": "TEXT", "declaration_json": "TEXT",
            "disclosure_version": "TEXT", "distribution_restriction": "TEXT", "qualification_payload_json": "TEXT",
            "qualification_digest": "TEXT", "qualification_state": "TEXT", "created_at": "TEXT", "finalized_at": "TEXT",
            "idempotency_key": "TEXT",
        },
        "record_governed_report_qualification_events": {
            "id": "INTEGER", "qualification_id": "INTEGER", "report_id": "INTEGER",
            "report_version_id": "INTEGER", "event_type": "TEXT", "actor": "TEXT", "occurred_at": "TEXT",
            "idempotency_key": "TEXT", "payload_json": "TEXT",
        },
    }
    for table, expected in required.items():
        rows = conn.execute("PRAGMA table_info(%s)" % table).fetchall()
        columns = {str(row[1]): (str(row[2]).upper(), int(row[3])) for row in rows}
        if not rows or any(columns.get(name, (None, None))[0] != type_name for name, type_name in expected.items()):
            raise ValueError("stage75_qualification_schema_incompatible")
        nullable = {"previous_qualification_id"}
        if any(columns[name][1] != 1 for name in expected if name not in nullable and name not in {"id"}):
            raise ValueError("stage75_qualification_schema_incompatible")
    foreign_keys = conn.execute("PRAGMA foreign_key_list(record_governed_report_qualifications)").fetchall()
    required_foreign_keys = {
        (str(row[3]), str(row[2]), str(row[4]))
        for row in foreign_keys
    }
    if {
        ("report_id", "record_governed_reports", "id"),
        ("report_version_id", "record_governed_report_versions", "id"),
        ("previous_qualification_id", "record_governed_report_qualifications", "id"),
    } - required_foreign_keys:
        raise ValueError("stage75_qualification_schema_incompatible")
    event_foreign_keys = conn.execute("PRAGMA foreign_key_list(record_governed_report_qualification_events)").fetchall()
    if ("qualification_id", "record_governed_report_qualifications", "id") not in {
        (str(row[3]), str(row[2]), str(row[4])) for row in event_foreign_keys
    }:
        raise ValueError("stage75_qualification_schema_incompatible")


def _row_value(row: Any, key: str, index: int) -> Any:
    try:
        return row[key]
    except (IndexError, KeyError, TypeError):
        return row[index]


def _report_version(conn: sqlite3.Connection, report_id: int | str) -> tuple[Any, Any]:
    report = conn.execute(
        "SELECT id,created_by,distribution_class,lifecycle_status FROM record_governed_reports WHERE id=?",
        (int(report_id),),
    ).fetchone()
    if report is None:
        raise ValueError("governed_report_not_found")
    version = conn.execute(
        "SELECT id,specification_digest,specification_json FROM record_governed_report_versions WHERE report_id=? ORDER BY version_number DESC LIMIT 1",
        (int(report_id),),
    ).fetchone()
    if version is None:
        raise ValueError("governed_report_version_not_found")
    return report, version


def _latest(conn: sqlite3.Connection, version_id: int) -> Any | None:
    return conn.execute(
        "SELECT * FROM record_governed_report_qualifications WHERE report_version_id=? ORDER BY revision_number DESC LIMIT 1",
        (int(version_id),),
    ).fetchone()


def _payload_digest(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def state_snapshot(conn: sqlite3.Connection) -> dict[str, Any]:
    """Return bounded, content-free identity evidence for recovery manifests."""
    validate_qualification_tables(conn)
    qualifications = [dict(row) for row in conn.execute("SELECT * FROM record_governed_report_qualifications ORDER BY id").fetchall()]
    events = [dict(row) for row in conn.execute("SELECT * FROM record_governed_report_qualification_events ORDER BY id").fetchall()]
    material = canonical_json({"qualifications": qualifications, "events": events}).encode("utf-8")
    return {
        "count": len(qualifications),
        "event_bound": int(conn.execute("SELECT COALESCE(MAX(id),0) FROM record_governed_report_qualification_events").fetchone()[0]),
        "digest": hashlib.sha256(material).hexdigest(),
    }


def validate_chain(conn: sqlite3.Connection, version_id: int) -> list[dict[str, Any]]:
    """Validate the complete immutable qualification chain for one version."""
    validate_qualification_tables(conn)
    version_owner = conn.execute(
        "SELECT report_id FROM record_governed_report_versions WHERE id=?",
        (int(version_id),),
    ).fetchone()
    if version_owner is None:
        raise ValueError("governed_report_version_not_found")
    expected_report_id = int(version_owner[0])
    rows = conn.execute("SELECT * FROM record_governed_report_qualifications WHERE report_version_id=? ORDER BY revision_number", (int(version_id),)).fetchall()
    chain: list[dict[str, Any]] = []
    previous_id = None
    previous_mode = None
    for expected_revision, row in enumerate(rows, 1):
        value = dict(row)
        if int(value["report_id"]) != expected_report_id or int(value["report_version_id"]) != int(version_id) or int(value["revision_number"]) != expected_revision or value["previous_qualification_id"] != previous_id or value["qualification_state"] != "final":
            raise ValueError("governed_report_qualification_chain_invalid")
        try:
            payload = json.loads(value["qualification_payload_json"])
        except (TypeError, ValueError, json.JSONDecodeError):
            raise ValueError("governed_report_qualification_chain_invalid") from None
        if _payload_digest(payload) != value["qualification_digest"]:
            raise ValueError("governed_report_qualification_digest_mismatch")
        if not isinstance(payload, dict) or canonical_json(payload) != value["qualification_payload_json"]:
            raise ValueError("governed_report_qualification_chain_invalid")
        for field in ("report_id", "report_version_id", "specification_digest", "revision_number", "completed_gate", "review_mode", "operating_constraint", "creator_actor", "qualifier_actor", "rationale", "disclosure_version", "distribution_restriction"):
            if field in payload and str(payload[field]) != str(value[field]):
                raise ValueError("governed_report_qualification_chain_invalid")
        try:
            declaration = json.loads(value["declaration_json"])
        except (TypeError, ValueError, json.JSONDecodeError):
            raise ValueError("governed_report_qualification_chain_invalid") from None
        if canonical_json(declaration) != canonical_json(payload.get("declaration")):
            raise ValueError("governed_report_qualification_chain_invalid")
        if previous_mode is not None and value["review_mode"] != previous_mode:
            raise ValueError("governed_report_qualification_mode_changed")
        if expected_revision == 1 and value["completed_gate"] != "assembly":
            raise ValueError("governed_report_qualification_gate_order_invalid")
        if expected_revision > 1 and GATES.index(value["completed_gate"]) != GATES.index(chain[-1]["completed_gate"]) + 1:
            raise ValueError("governed_report_qualification_gate_order_invalid")
        expected_event = SOLE_EVENTS[value["completed_gate"]] if value["review_mode"] == SOLE_MODE else INDEPENDENT_EVENTS[value["completed_gate"]]
        event_rows = conn.execute("SELECT * FROM record_governed_report_qualification_events WHERE qualification_id=?", (value["id"],)).fetchall()
        event = event_rows[0] if len(event_rows) == 1 else None
        if event is None or event["event_type"] != expected_event or event["actor"] != value["qualifier_actor"] or event["idempotency_key"] != value["idempotency_key"] or event["report_id"] != value["report_id"] or event["report_version_id"] != value["report_version_id"]:
            raise ValueError("governed_report_qualification_event_invalid")
        try:
            event_payload = json.loads(event["payload_json"])
        except (TypeError, ValueError, json.JSONDecodeError):
            raise ValueError("governed_report_qualification_event_invalid") from None
        if not isinstance(event_payload, dict) or canonical_json(event_payload) != event["payload_json"] or event_payload != payload:
            raise ValueError("governed_report_qualification_event_invalid")
        chain.append(value)
        previous_id = value["id"]
        previous_mode = value["review_mode"]
    return chain


def record_gate(
    conn: sqlite3.Connection,
    *,
    report_id: int | str,
    resulting_status: str,
    actor: str,
    rationale: str,
    declaration: Mapping[str, Any],
    idempotency_key: str,
    mode: str | None = None,
    event_type: str | None = None,
) -> dict[str, Any]:
    ensure_qualification_tables(conn)
    selected_mode = mode or configured_review_mode()
    if selected_mode not in MODES:
        raise ValueError("governed_report_review_mode_invalid")
    gate = GATE_STATUS.get(resulting_status)
    if gate is None:
        raise ValueError("governed_report_qualification_gate_invalid")
    actor_value = str(actor or "").strip()
    rationale_value = str(rationale or "").strip()
    key = str(idempotency_key or "").strip()
    if not actor_value:
        raise ValueError("governed_report_qualifier_required")
    if not rationale_value or len(rationale_value) > 4000:
        raise ValueError("governed_report_qualification_rationale_invalid")
    if not isinstance(declaration, Mapping) or declaration.get("acknowledged") is not True:
        raise ValueError("governed_report_qualification_declaration_required")
    if not key:
        raise ValueError("governed_report_qualification_idempotency_key_required")
    report, version = _report_version(conn, report_id)
    specification = json.loads(_row_value(version, "specification_json", 2))
    expected_specification_digest = hashlib.sha256(canonical_json(specification).encode("utf-8")).hexdigest()
    if expected_specification_digest != str(_row_value(version, "specification_digest", 1)):
        raise ValueError("governed_report_specification_digest_mismatch")
    creator = str(_row_value(report, "created_by", 1))
    if selected_mode == SOLE_MODE:
        if str(os.getenv(REVIEW_MODE_ENV) or "") != SOLE_MODE:
            raise ValueError("governed_report_sole_mode_required")
        if actor_value != creator:
            raise ValueError("governed_report_sole_qualifier_must_be_creator")
        if str(_row_value(report, "distribution_class", 2)) != "internal_working":
            raise ValueError("governed_report_sole_distribution_invalid")
        if declaration.get("no_independent_administrator_available") is not True:
            raise ValueError("governed_report_sole_constraint_declaration_required")
        if declaration.get("application_did_not_verify_declaration") is not True:
            raise ValueError("governed_report_sole_verification_boundary_required")
        disclosure = DISCLOSURE_VERSION
        operating_constraint = "no_independent_administrator_available"
        event_name = event_type or SOLE_EVENTS[gate]
    else:
        if actor_value == creator:
            raise ValueError("governed_report_review_actor_must_differ_from_creator")
        disclosure = "none"
        operating_constraint = "independent_actor_separation"
        event_name = event_type or INDEPENDENT_EVENTS[gate]
    existing_event = conn.execute(
        "SELECT qualification_id,payload_json FROM record_governed_report_qualification_events WHERE idempotency_key=?",
        (key,),
    ).fetchone()
    if existing_event is not None:
        existing_payload = json.loads(_row_value(existing_event, "payload_json", 1))
        if existing_payload.get("report_id") != int(_row_value(report, "id", 0)) or existing_payload.get("report_version_id") != int(_row_value(version, "id", 0)) or existing_payload.get("completed_gate") != gate or existing_payload.get("review_mode") != selected_mode or existing_payload.get("qualifier_actor") != actor_value or existing_payload.get("rationale") != rationale_value or existing_payload.get("declaration") != dict(declaration):
            raise ValueError("governed_report_qualification_idempotency_conflict")
        return {"id": int(_row_value(existing_event, "qualification_id", 0)), "replayed": True}
    latest = _latest(conn, int(_row_value(version, "id", 0)))
    previous_gate = None if latest is None else str(_row_value(latest, "completed_gate", 6))
    if latest is not None and GATES.index(gate) != GATES.index(previous_gate) + 1:
        raise ValueError("governed_report_qualification_gate_order_invalid")
    if latest is None and gate != "assembly":
        raise ValueError("governed_report_qualification_gate_order_invalid")
    revision = 1 if latest is None else int(_row_value(latest, "revision_number", 4)) + 1
    payload = {
        "report_id": int(_row_value(report, "id", 0)),
        "report_version_id": int(_row_value(version, "id", 0)),
        "specification_digest": str(_row_value(version, "specification_digest", 1)),
        "revision_number": revision,
        "previous_qualification_id": None if latest is None else int(_row_value(latest, "id", 0)),
        "completed_gate": gate,
        "review_mode": selected_mode,
        "operating_constraint": operating_constraint,
        "creator_actor": creator,
        "qualifier_actor": actor_value,
        "rationale": rationale_value,
        "declaration": dict(declaration),
        "disclosure_version": disclosure,
        "distribution_restriction": "internal_working" if selected_mode == SOLE_MODE else str(_row_value(report, "distribution_class", 2)),
    }
    digest = _payload_digest(payload)
    now = utc_now()
    cur = conn.execute(
        "INSERT INTO record_governed_report_qualifications (report_id,report_version_id,specification_digest,revision_number,previous_qualification_id,completed_gate,review_mode,operating_constraint,creator_actor,qualifier_actor,rationale,declaration_json,disclosure_version,distribution_restriction,qualification_payload_json,qualification_digest,qualification_state,created_at,finalized_at,idempotency_key) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (payload["report_id"], payload["report_version_id"], payload["specification_digest"], revision, payload["previous_qualification_id"], gate, selected_mode, operating_constraint, creator, actor_value, rationale_value, canonical_json(dict(declaration)), disclosure, payload["distribution_restriction"], canonical_json(payload), digest, "final", now, now, key),
    )
    qualification_id = int(cur.lastrowid)
    conn.execute(
        "INSERT INTO record_governed_report_qualification_events (qualification_id,report_id,report_version_id,event_type,actor,occurred_at,idempotency_key,payload_json) VALUES (?,?,?,?,?,?,?,?)",
        (qualification_id, payload["report_id"], payload["report_version_id"], event_name, actor_value, now, key, canonical_json(payload)),
    )
    return {"id": qualification_id, "digest": digest, "payload": payload, "replayed": False}


def latest_final(conn: sqlite3.Connection, report_id: int | str) -> dict[str, Any] | None:
    ensure_qualification_tables(conn)
    _, version = _report_version(conn, report_id)
    version_id = int(_row_value(version, "id", 0))
    chain = validate_chain(conn, version_id)
    row = chain[-1] if chain else None
    if row is None or str(_row_value(row, "completed_gate", 6)) != "approval":
        return None
    payload = json.loads(row["qualification_payload_json"])
    if str(_row_value(row, "qualification_state", 17)) != "final":
        raise ValueError("governed_report_qualification_not_final")
    return {"id": int(row["id"]), "digest": str(row["qualification_digest"]), "payload": payload, "row": row}


def rendering_projection(
    conn: sqlite3.Connection,
    *,
    report_id: int | str,
    report_version_id: int | str,
    specification_digest: str,
    qualification_id: int | str,
    qualification_digest: str,
) -> dict[str, Any]:
    """Project a validated persisted envelope into the exact adapter contract."""
    report = conn.execute(
        "SELECT id,distribution_class,lifecycle_status FROM record_governed_reports WHERE id=?",
        (int(report_id),),
    ).fetchone()
    version = conn.execute(
        "SELECT id,report_id,specification_digest,specification_json FROM record_governed_report_versions WHERE id=?",
        (int(report_version_id),),
    ).fetchone()
    if report is None or version is None or int(version["report_id"]) != int(report["id"]):
        raise ValueError("governed_report_rendering_qualification_ownership_invalid")
    if str(version["specification_digest"]) != str(specification_digest):
        raise ValueError("governed_report_rendering_qualification_specification_invalid")
    try:
        specification = json.loads(version["specification_json"])
    except (TypeError, ValueError, json.JSONDecodeError):
        raise ValueError("governed_report_rendering_qualification_specification_invalid") from None
    if not isinstance(specification, dict) or _payload_digest(specification) != str(specification_digest):
        raise ValueError("governed_report_rendering_qualification_specification_invalid")
    if report["lifecycle_status"] not in {"approved_for_generation", "generation_requested"}:
        raise ValueError("governed_report_rendering_qualification_lifecycle_invalid")
    if report["distribution_class"] != "internal_working" or specification.get("distribution_class") != "internal_working":
        raise ValueError("governed_report_rendering_qualification_distribution_invalid")
    chain = validate_chain(conn, int(version["id"]))
    if len(chain) != len(GATES) or not chain or chain[-1]["completed_gate"] != "approval":
        raise ValueError("governed_report_rendering_qualification_chain_invalid")
    final_row = chain[-1]
    try:
        final_payload = json.loads(final_row["qualification_payload_json"])
    except (TypeError, ValueError, json.JSONDecodeError):
        raise ValueError("governed_report_rendering_qualification_envelope_invalid") from None
    qualification = {"id": int(final_row["id"]), "digest": str(final_row["qualification_digest"]), "payload": final_payload}
    if qualification["id"] != int(qualification_id) or qualification["digest"] != str(qualification_digest):
        raise ValueError("governed_report_rendering_qualification_identity_invalid")
    payload = qualification["payload"]
    if not isinstance(payload, dict) or set(payload) != PERSISTED_QUALIFICATION_FIELDS:
        raise ValueError("governed_report_rendering_qualification_envelope_invalid")
    digest = payload["specification_digest"]
    digest_valid = isinstance(digest, str) and len(digest) == 64 and digest == digest.lower() and all(char in "0123456789abcdef" for char in digest)
    declaration = payload["declaration"]
    if (
        type(payload["report_id"]) is not int
        or type(payload["report_version_id"]) is not int
        or type(payload["revision_number"]) is not int
        or (payload["previous_qualification_id"] is not None and type(payload["previous_qualification_id"]) is not int)
        or not isinstance(payload["specification_digest"], str)
        or not digest_valid
        or payload["report_id"] != int(report["id"])
        or payload["report_version_id"] != int(version["id"])
        or payload["specification_digest"] != str(specification_digest)
        or payload["revision_number"] != 4
        or payload["completed_gate"] != "approval"
        or payload["review_mode"] != SOLE_MODE
        or payload["operating_constraint"] != "no_independent_administrator_available"
        or not isinstance(payload["creator_actor"], str) or not payload["creator_actor"].strip()
        or not isinstance(payload["qualifier_actor"], str) or payload["qualifier_actor"] != payload["creator_actor"]
        or not isinstance(payload["rationale"], str) or not payload["rationale"].strip() or len(payload["rationale"]) > 4000
        or payload["disclosure_version"] != DISCLOSURE_VERSION
        or payload["distribution_restriction"] != "internal_working"
    ):
        raise ValueError("governed_report_rendering_qualification_envelope_invalid")
    if not isinstance(declaration, dict) or set(declaration) != {"acknowledged", "no_independent_administrator_available", "application_did_not_verify_declaration"} or any(value is not True for value in declaration.values()):
        raise ValueError("governed_report_rendering_qualification_envelope_invalid")
    projection = {
        "review_mode": SOLE_MODE,
        "disclosure_version": DISCLOSURE_VERSION,
        "disclosure": DISCLOSURE,
        "qualification_id": int(qualification["id"]),
        "qualification_digest": str(qualification["digest"]),
    }
    if set(projection) != RENDERING_QUALIFICATION_FIELDS:
        raise ValueError("governed_report_rendering_qualification_projection_invalid")
    return projection
