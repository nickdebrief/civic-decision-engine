import importlib
import json
import os
import sqlite3
import sys
import tempfile
import types
import unittest
from pathlib import Path

from api.attachments import (
    ensure_attachment_tables,
    public_manifest_attachments,
    record_attachment_audit_event,
    sanitize_audit_metadata,
)


class FakeAPIRouter:
    def get(self, *args, **kwargs):
        return lambda func: func

    def post(self, *args, **kwargs):
        return lambda func: func


class FakeResponse:
    def __init__(self, content=None, status_code=200, media_type=None, headers=None):
        self.content = content
        self.status_code = status_code
        self.media_type = media_type
        self.headers = headers or {}


def install_fastapi_stubs():
    fastapi = types.ModuleType("fastapi")
    fastapi.APIRouter = FakeAPIRouter
    fastapi.File = lambda default=None, **kwargs: default
    fastapi.Form = lambda default=None, **kwargs: default
    fastapi.Header = lambda default=None, **kwargs: default
    fastapi.HTTPException = Exception
    fastapi.Query = lambda default=None, **kwargs: default
    fastapi.UploadFile = object

    responses = types.ModuleType("fastapi.responses")
    responses.HTMLResponse = FakeResponse
    responses.JSONResponse = FakeResponse
    responses.Response = FakeResponse

    models = types.ModuleType("api.models")
    models.RecordPayload = type("RecordPayload", (), {})
    models.RecordResponse = type("RecordResponse", (), {})

    sys.modules.setdefault("fastapi", fastapi)
    sys.modules.setdefault("fastapi.responses", responses)
    sys.modules.setdefault("api.models", models)


def make_connection():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reference TEXT NOT NULL,
            version INTEGER NOT NULL DEFAULT 1,
            verification_hash TEXT NOT NULL,
            UNIQUE(reference, version)
        )
    """)
    ensure_attachment_tables(conn)
    return conn


class AttachmentAuditEventsSchemaTests(unittest.TestCase):
    def insert_event(self, conn, **overrides):
        values = {
            "reference": "Strike-OT-20260604-001",
            "event_type": "attachment_uploaded",
            "occurred_at": "2026-06-04T12:00:00Z",
        }
        values.update(overrides)
        columns = ", ".join(values.keys())
        placeholders = ", ".join("?" for _ in values)
        conn.execute(
            f"INSERT INTO attachment_audit_events ({columns}) VALUES ({placeholders})",
            list(values.values()),
        )

    def test_migration_creates_attachment_audit_events_table(self):
        conn = make_connection()

        table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name = 'attachment_audit_events'"
        ).fetchone()
        columns = {
            row["name"]
            for row in conn.execute(
                "PRAGMA table_info(attachment_audit_events)"
            ).fetchall()
        }

        self.assertIsNotNone(table)
        self.assertEqual(
            columns,
            {
                "id",
                "attachment_id",
                "reference",
                "record_version",
                "event_type",
                "actor",
                "occurred_at",
                "metadata_json",
                "request_id",
                "ip_hash",
                "user_agent_hash",
            },
        )

    def test_required_fields_are_enforced(self):
        conn = make_connection()

        for missing_field in ("reference", "event_type", "occurred_at"):
            with self.subTest(missing_field=missing_field):
                values = {
                    "reference": "Strike-OT-20260604-001",
                    "event_type": "attachment_uploaded",
                    "occurred_at": "2026-06-04T12:00:00Z",
                }
                values.pop(missing_field)
                columns = ", ".join(values.keys())
                placeholders = ", ".join("?" for _ in values)

                with self.assertRaises(sqlite3.IntegrityError):
                    conn.execute(
                        f"INSERT INTO attachment_audit_events ({columns}) "
                        f"VALUES ({placeholders})",
                        list(values.values()),
                    )

    def test_actor_defaults_to_admin(self):
        conn = make_connection()

        self.insert_event(conn)
        row = conn.execute("SELECT actor FROM attachment_audit_events").fetchone()

        self.assertEqual(row["actor"], "admin")

    def test_nullable_fields_allow_null(self):
        conn = make_connection()

        self.insert_event(
            conn,
            attachment_id=None,
            record_version=None,
            metadata_json=None,
            request_id=None,
            ip_hash=None,
            user_agent_hash=None,
        )
        row = conn.execute("SELECT * FROM attachment_audit_events").fetchone()

        self.assertIsNone(row["attachment_id"])
        self.assertIsNone(row["record_version"])
        self.assertIsNone(row["metadata_json"])
        self.assertIsNone(row["request_id"])
        self.assertIsNone(row["ip_hash"])
        self.assertIsNone(row["user_agent_hash"])

    def test_metadata_json_can_store_json_text(self):
        conn = make_connection()
        metadata = {
            "visibility": "private",
            "redaction_status": "none",
            "filename": "synthetic.txt",
        }

        self.insert_event(conn, metadata_json=json.dumps(metadata, sort_keys=True))
        row = conn.execute("SELECT metadata_json FROM attachment_audit_events").fetchone()

        self.assertEqual(json.loads(row["metadata_json"]), metadata)

    def test_audit_helper_inserts_row_and_returns_id(self):
        conn = make_connection()

        event_id = record_attachment_audit_event(
            conn,
            event_type="attachment_reviewed",
            reference="Strike-OT-20260604-001",
            attachment_id=42,
            record_version=3,
            request_id="req-001",
            ip_hash="ip-hash",
            user_agent_hash="ua-hash",
            occurred_at="2026-06-04T12:34:56Z",
        )
        row = conn.execute(
            "SELECT * FROM attachment_audit_events WHERE id = ?",
            (event_id,),
        ).fetchone()

        self.assertEqual(row["id"], event_id)
        self.assertEqual(row["event_type"], "attachment_reviewed")
        self.assertEqual(row["reference"], "Strike-OT-20260604-001")
        self.assertEqual(row["actor"], "admin")
        self.assertEqual(row["attachment_id"], 42)
        self.assertEqual(row["record_version"], 3)
        self.assertEqual(row["request_id"], "req-001")
        self.assertEqual(row["ip_hash"], "ip-hash")
        self.assertEqual(row["user_agent_hash"], "ua-hash")
        self.assertEqual(row["occurred_at"], "2026-06-04T12:34:56Z")

    def test_audit_helper_generates_default_utc_timestamp(self):
        conn = make_connection()

        event_id = record_attachment_audit_event(
            conn,
            event_type="attachment_reviewed",
            reference="Strike-OT-20260604-001",
        )
        row = conn.execute(
            "SELECT occurred_at FROM attachment_audit_events WHERE id = ?",
            (event_id,),
        ).fetchone()

        self.assertRegex(
            row["occurred_at"],
            r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$",
        )

    def test_audit_helper_preserves_supplied_actor_and_occurred_at(self):
        conn = make_connection()

        event_id = record_attachment_audit_event(
            conn,
            event_type="attachment_reviewed",
            reference="Strike-OT-20260604-001",
            actor="reviewer",
            occurred_at="2026-06-04T09:00:00Z",
        )
        row = conn.execute(
            "SELECT actor, occurred_at FROM attachment_audit_events WHERE id = ?",
            (event_id,),
        ).fetchone()

        self.assertEqual(row["actor"], "reviewer")
        self.assertEqual(row["occurred_at"], "2026-06-04T09:00:00Z")

    def test_audit_helper_stores_stable_json_metadata(self):
        conn = make_connection()
        metadata = {"z": 2, "a": {"d": 4, "b": 1}}

        event_id = record_attachment_audit_event(
            conn,
            event_type="attachment_reviewed",
            reference="Strike-OT-20260604-001",
            metadata=metadata,
            occurred_at="2026-06-04T12:00:00Z",
        )
        row = conn.execute(
            "SELECT metadata_json FROM attachment_audit_events WHERE id = ?",
            (event_id,),
        ).fetchone()

        self.assertEqual(row["metadata_json"], '{"a":{"b":1,"d":4},"z":2}')

    def test_audit_helper_sanitizes_sensitive_metadata_before_storage(self):
        conn = make_connection()
        metadata = {
            "safe": "kept",
            "CDE_ADMIN_TOKEN": "secret-token",
            "session_secret": "secret-session",
            "password": "secret-password",
            "storage_path": "/private/path/evidence.pdf",
            "stored_filename": "internal-evidence.pdf",
            "raw_file_bytes": "raw-bytes",
            "source_narrative": "private narrative",
            "report_json": {"private": True},
            "raw_input": "private input",
            "nested": {
                "safe_nested": "kept",
                "storage_path": "/nested/private/path",
                "items": [
                    {"stored_filename": "nested-internal.pdf", "visible": "yes"}
                ],
            },
        }

        event_id = record_attachment_audit_event(
            conn,
            event_type="attachment_reviewed",
            reference="Strike-OT-20260604-001",
            metadata=metadata,
        )
        row = conn.execute(
            "SELECT metadata_json FROM attachment_audit_events WHERE id = ?",
            (event_id,),
        ).fetchone()
        serialized = row["metadata_json"]
        stored_metadata = json.loads(serialized)

        self.assertEqual(stored_metadata["safe"], "kept")
        self.assertEqual(stored_metadata["nested"]["safe_nested"], "kept")
        self.assertEqual(stored_metadata["nested"]["items"][0]["visible"], "yes")
        for forbidden in (
            "CDE_ADMIN_TOKEN",
            "secret-token",
            "session_secret",
            "secret-session",
            "password",
            "secret-password",
            "storage_path",
            "/private/path",
            "stored_filename",
            "internal-evidence.pdf",
            "raw_file_bytes",
            "raw-bytes",
            "source_narrative",
            "private narrative",
            "report_json",
            "raw_input",
            "private input",
            "/nested/private/path",
            "nested-internal.pdf",
        ):
            self.assertNotIn(forbidden, serialized)

    def test_sanitize_audit_metadata_allows_none(self):
        self.assertIsNone(sanitize_audit_metadata(None))

    def test_audit_helper_stores_null_metadata_for_none(self):
        conn = make_connection()

        event_id = record_attachment_audit_event(
            conn,
            event_type="attachment_reviewed",
            reference="Strike-OT-20260604-001",
            metadata=None,
        )
        row = conn.execute(
            "SELECT metadata_json FROM attachment_audit_events WHERE id = ?",
            (event_id,),
        ).fetchone()

        self.assertIsNone(row["metadata_json"])

    def test_audit_helper_required_fields_are_enforced(self):
        conn = make_connection()

        with self.assertRaises(sqlite3.IntegrityError):
            record_attachment_audit_event(
                conn,
                event_type="attachment_reviewed",
                reference=None,
            )
        with self.assertRaises(sqlite3.IntegrityError):
            record_attachment_audit_event(
                conn,
                event_type=None,
                reference="Strike-OT-20260604-001",
            )

    def test_audit_helper_does_not_change_public_manifest_behavior(self):
        conn = make_connection()
        conn.execute(
            """
            INSERT INTO record_attachments (
                reference, record_version, attachment_version,
                filename, stored_filename, storage_path,
                content_type, file_size_bytes, sha256_hash,
                visibility, redaction_status, title, uploaded_at
            )
            VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "Strike-OT-20260604-001",
                1,
                "public.pdf",
                "internal-public.pdf",
                "/private/path/internal-public.pdf",
                "application/pdf",
                123,
                "a" * 64,
                "public",
                "none",
                "Public attachment",
                "2026-06-04T12:00:00Z",
            ),
        )
        before = public_manifest_attachments(
            conn,
            reference="Strike-OT-20260604-001",
            record_version=1,
        )

        record_attachment_audit_event(
            conn,
            event_type="attachment_reviewed",
            reference="Strike-OT-20260604-001",
            metadata={"storage_path": "/private/path/internal-public.pdf"},
        )
        after = public_manifest_attachments(
            conn,
            reference="Strike-OT-20260604-001",
            record_version=1,
        )

        self.assertEqual(after, before)

    def test_audit_helper_does_not_add_mutation_route_names(self):
        route_source = Path("api/routes/admin_session.py").read_text()

        self.assertNotIn("record_attachment_audit_event(", route_source)
        self.assertNotIn("sanitize_audit_metadata(", route_source)

    def test_canonical_record_verification_hash_is_unchanged(self):
        install_fastapi_stubs()
        with tempfile.TemporaryDirectory() as temp_dir:
            os.environ["RECORDS_DB_PATH"] = str(Path(temp_dir) / "records.db")
            records = importlib.import_module("api.routes.records")

        actual = records.compute_verification_hash(
            reference="Strike-OT-20260604-001",
            generated_at="2026-06-04T12:00:00Z",
            finding="Attachment audit schema must not change canonical hashing.",
            trajectory="Stable",
            conditions=["Transfer of Burden", "Institutional Delay"],
            system_state="Canonical record unchanged",
            generated_by="Civic Decision Engine",
        )

        self.assertEqual(
            actual,
            "f7597d820dc0cc1f9554d83c2d8f16d7ead5a775c2347b36e9322fbc97202f5b",
        )


if __name__ == "__main__":
    unittest.main()
