import hashlib
import importlib
import os
import sqlite3
import sys
import tempfile
import types
import unittest
from pathlib import Path

from api.attachments import (
    attachment_sha256,
    build_attachment_storage_path,
    ensure_attachment_tables,
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
    fastapi.HTTPException = Exception
    fastapi.Query = lambda default=None, **kwargs: default

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
    return conn


def insert_attachment(conn, **overrides):
    values = {
        "reference": "Strike-LA-20260528-001",
        "record_version": 1,
        "attachment_version": 1,
        "filename": "evidence.pdf",
        "stored_filename": "attachment-1-v1-abcd1234.pdf",
        "storage_path": "/data/attachments/Strike-LA-20260528-001/v1/attachments/attachment-1-v1-abcd1234.pdf",
        "content_type": "application/pdf",
        "file_size_bytes": 12,
        "sha256_hash": "abcd" * 16,
        "visibility": "private",
        "redaction_status": "none",
        "uploaded_at": "2026-05-28T09:00:00Z",
    }
    values.update(overrides)
    columns = ", ".join(values.keys())
    placeholders = ", ".join("?" for _ in values)
    conn.execute(
        f"INSERT INTO record_attachments ({columns}) VALUES ({placeholders})",
        list(values.values()),
    )


class AttachmentInfrastructureTests(unittest.TestCase):
    def test_ensure_attachment_tables_creates_table_and_indexes(self):
        conn = make_connection()

        ensure_attachment_tables(conn)

        table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name = 'record_attachments'"
        ).fetchone()
        indexes = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            ).fetchall()
        }
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(record_attachments)").fetchall()
        }

        self.assertIsNotNone(table)
        self.assertIn("idx_record_attachments_reference", indexes)
        self.assertIn("idx_record_attachments_public", indexes)
        self.assertIn("idx_record_attachments_version", indexes)
        self.assertIn("sha256_hash", columns)
        self.assertIn("visibility", columns)
        self.assertIn("redaction_status", columns)

    def test_invalid_visibility_and_redaction_values_are_rejected(self):
        conn = make_connection()
        ensure_attachment_tables(conn)

        with self.assertRaises(sqlite3.IntegrityError):
            insert_attachment(conn, visibility="shared")

        with self.assertRaises(sqlite3.IntegrityError):
            insert_attachment(conn, redaction_status="partially_hidden")

    def test_init_db_creates_record_attachments_table(self):
        install_fastapi_stubs()
        with tempfile.TemporaryDirectory() as temp_dir:
            os.environ["RECORDS_DB_PATH"] = str(Path(temp_dir) / "records.db")
            records = importlib.import_module("api.routes.records")
            original_db_path = records.DB_PATH
            records.DB_PATH = Path(temp_dir) / "records.db"
            try:
                records.init_db()
                conn = sqlite3.connect(records.DB_PATH)
                try:
                    table = conn.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table' "
                        "AND name = 'record_attachments'"
                    ).fetchone()
                finally:
                    conn.close()
            finally:
                records.DB_PATH = original_db_path

        self.assertIsNotNone(table)

    def test_attachment_sha256_uses_raw_bytes(self):
        data = b"CDE attachment bytes\x00with binary content"

        self.assertEqual(attachment_sha256(data), hashlib.sha256(data).hexdigest())

    def test_storage_path_generates_safe_filename_under_root(self):
        root = Path(tempfile.mkdtemp())
        sha256_hash = "0123456789abcdef" * 4

        path = build_attachment_storage_path(
            reference="Strike-LA-20260528-001",
            record_version=1,
            attachment_id=42,
            attachment_version=3,
            sha256_hash=sha256_hash,
            original_filename="../../private/Evidence.PDF",
            root=root,
        )

        self.assertEqual(
            path.name,
            "attachment-42-v3-01234567.pdf",
        )
        self.assertEqual(
            path.parent,
            root.resolve() / "Strike-LA-20260528-001" / "v1" / "attachments",
        )
        self.assertNotIn("..", path.parts)

    def test_path_traversal_reference_cannot_escape_attachment_root(self):
        root = Path(tempfile.mkdtemp())
        sha256_hash = "0123456789abcdef" * 4

        with self.assertRaises(ValueError):
            build_attachment_storage_path(
                reference="../Strike-LA-20260528-001",
                record_version=1,
                attachment_id=1,
                attachment_version=1,
                sha256_hash=sha256_hash,
                original_filename="evidence.pdf",
                root=root,
            )

    def test_canonical_record_verification_hash_is_unchanged(self):
        install_fastapi_stubs()
        with tempfile.TemporaryDirectory() as temp_dir:
            os.environ["RECORDS_DB_PATH"] = str(Path(temp_dir) / "records.db")
            records = importlib.import_module("api.routes.records")

        actual = records.compute_verification_hash(
            reference="Strike-LA-20260528-001",
            generated_at="2026-05-28T09:00:00Z",
            finding="Attachment support must not change canonical record hashing.",
            trajectory="Stable",
            conditions=["Transfer of Burden", "Institutional Delay"],
            system_state="Canonical record unchanged",
            generated_by="Civic Decision Engine",
        )

        self.assertEqual(
            actual,
            "f20e2c41ec9712d5a204d7147666ab3a371336bf6be27790d4fce3c01738eeb6",
        )


if __name__ == "__main__":
    unittest.main()
