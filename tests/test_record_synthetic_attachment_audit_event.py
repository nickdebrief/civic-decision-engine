import importlib
import json
import os
import sqlite3
import sys
import tempfile
import types
import unittest
from pathlib import Path

from api.attachments import ensure_attachment_tables
from scripts import record_synthetic_attachment_audit_event as script


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


def make_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
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
    conn.execute(
        """
        INSERT INTO records (reference, version, verification_hash)
        VALUES (?, ?, ?)
        """,
        ("Strike-OT-20260604-001", 1, "a" * 64),
    )
    conn.execute(
        """
        INSERT INTO records (reference, version, verification_hash)
        VALUES (?, ?, ?)
        """,
        ("Strike-OT-20260604-OTHER", 1, "b" * 64),
    )
    ensure_attachment_tables(conn)
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
            "c" * 64,
            "public",
            "none",
            "Public attachment",
            "2026-06-04T12:00:00Z",
        ),
    )
    conn.commit()
    return conn


def table_snapshot(conn: sqlite3.Connection, table: str) -> list[dict]:
    rows = conn.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
    return [dict(row) for row in rows]


class SyntheticAttachmentAuditEventScriptTests(unittest.TestCase):
    def args(self, db_path: Path, *extra: str):
        return script.parse_args(
            [
                "--db-path",
                str(db_path),
                "--reference",
                "Strike-OT-20260604-001",
                "--record-version",
                "1",
                "--event-type",
                "synthetic_audit_verification",
                *extra,
            ]
        )

    def test_dry_run_does_not_insert(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "records.db"
            conn = make_db(db_path)
            before = conn.execute("SELECT COUNT(*) FROM attachment_audit_events").fetchone()[0]

            payload = script.record_synthetic_event(
                self.args(
                    db_path,
                    "--metadata-json",
                    '{"safe":"yes","CDE_ADMIN_TOKEN":"secret-token"}',
                    "--dry-run",
                )
            )
            after = conn.execute("SELECT COUNT(*) FROM attachment_audit_events").fetchone()[0]
            conn.close()

        serialized = json.dumps(payload, sort_keys=True)

        self.assertTrue(payload["ok"])
        self.assertFalse(payload["inserted"])
        self.assertIsNone(payload["event_id"])
        self.assertEqual(after, before)
        self.assertIn('"safe": "yes"', serialized)
        self.assertNotIn("CDE_ADMIN_TOKEN", serialized)
        self.assertNotIn("secret-token", serialized)

    def test_normal_run_inserts_one_audit_event_for_reference(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "records.db"
            conn = make_db(db_path)
            conn.close()

            payload = script.record_synthetic_event(
                self.args(
                    db_path,
                    "--attachment-id",
                    "7",
                    "--actor",
                    "admin",
                    "--request-id",
                    "req-synthetic-001",
                    "--metadata-json",
                    '{"purpose":"display verification"}',
                )
            )

            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM attachment_audit_events").fetchone()
            other_count = conn.execute(
                "SELECT COUNT(*) FROM attachment_audit_events WHERE reference = ?",
                ("Strike-OT-20260604-OTHER",),
            ).fetchone()[0]
            conn.close()

        self.assertTrue(payload["inserted"])
        self.assertEqual(payload["event_id"], row["id"])
        self.assertEqual(row["reference"], "Strike-OT-20260604-001")
        self.assertEqual(row["record_version"], 1)
        self.assertEqual(row["attachment_id"], 7)
        self.assertEqual(row["actor"], "admin")
        self.assertEqual(row["request_id"], "req-synthetic-001")
        self.assertEqual(json.loads(row["metadata_json"]), {"purpose": "display verification"})
        self.assertEqual(other_count, 0)

    def test_metadata_json_is_sanitized_through_helper(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "records.db"
            conn = make_db(db_path)
            conn.close()

            script.record_synthetic_event(
                self.args(
                    db_path,
                    "--metadata-json",
                    json.dumps(
                        {
                            "safe": "kept",
                            "CDE_ADMIN_TOKEN": "secret-token",
                            "storage_path": "/private/path/internal-public.pdf",
                            "nested": {
                                "stored_filename": "internal.pdf",
                                "visible": "yes",
                            },
                        }
                    ),
                )
            )

            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            metadata_json = conn.execute(
                "SELECT metadata_json FROM attachment_audit_events"
            ).fetchone()["metadata_json"]
            conn.close()

        self.assertEqual(
            json.loads(metadata_json),
            {"nested": {"visible": "yes"}, "safe": "kept"},
        )
        self.assertNotIn("CDE_ADMIN_TOKEN", metadata_json)
        self.assertNotIn("secret-token", metadata_json)
        self.assertNotIn("storage_path", metadata_json)
        self.assertNotIn("stored_filename", metadata_json)
        self.assertNotIn("/private/path", metadata_json)

    def test_invalid_metadata_json_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "records.db"
            make_db(db_path).close()

            with self.assertRaises(ValueError):
                script.record_synthetic_event(
                    self.args(db_path, "--metadata-json", "{not-json")
                )

            conn = sqlite3.connect(db_path)
            count = conn.execute("SELECT COUNT(*) FROM attachment_audit_events").fetchone()[0]
            conn.close()

        self.assertEqual(count, 0)

    def test_no_attachment_or_record_rows_are_created_or_modified(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "records.db"
            conn = make_db(db_path)
            before_records = table_snapshot(conn, "records")
            before_attachments = table_snapshot(conn, "record_attachments")
            conn.close()

            script.record_synthetic_event(self.args(db_path))

            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            after_records = table_snapshot(conn, "records")
            after_attachments = table_snapshot(conn, "record_attachments")
            conn.close()

        self.assertEqual(after_records, before_records)
        self.assertEqual(after_attachments, before_attachments)

    def test_canonical_verification_behavior_is_unchanged(self):
        install_fastapi_stubs()
        with tempfile.TemporaryDirectory() as temp_dir:
            os.environ["RECORDS_DB_PATH"] = str(Path(temp_dir) / "records.db")
            records = importlib.import_module("api.routes.records")

        actual = records.compute_verification_hash(
            reference="Strike-OT-20260604-001",
            generated_at="2026-06-04T12:00:00Z",
            finding="Synthetic audit verification must not change canonical hashing.",
            trajectory="Stable",
            conditions=["Transfer of Burden", "Institutional Delay"],
            system_state="Canonical record unchanged",
            generated_by="Civic Decision Engine",
        )

        self.assertEqual(
            actual,
            "09c1ff61995dd188250049935f6aac4c4297020a5a370d1dfaa9698e636a5d1a",
        )


if __name__ == "__main__":
    unittest.main()
