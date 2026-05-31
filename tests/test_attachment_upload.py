import asyncio
import hashlib
import importlib
import json
import os
import sqlite3
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


class FakeAPIRouter:
    def get(self, *args, **kwargs):
        return lambda func: func

    def post(self, *args, **kwargs):
        return lambda func: func


class FakeHTTPException(Exception):
    def __init__(self, status_code=None, detail=None):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


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
    fastapi.HTTPException = FakeHTTPException
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


class FakeUploadFile:
    def __init__(self, filename, content_type, data):
        self.filename = filename
        self.content_type = content_type
        self._data = data
        self.read_called = False

    async def read(self):
        self.read_called = True
        return self._data


class AttachmentUploadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        install_fastapi_stubs()
        cls.import_temp_dir = tempfile.TemporaryDirectory()
        os.environ["RECORDS_DB_PATH"] = str(
            Path(cls.import_temp_dir.name) / "import-records.db"
        )
        cls.records = importlib.import_module("api.routes.records")

    @classmethod
    def tearDownClass(cls):
        cls.import_temp_dir.cleanup()

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "records.db"
        self.attachment_root = Path(self.temp_dir.name) / "attachments"
        self.original_db_path = self.records.DB_PATH
        self.records.DB_PATH = self.db_path
        self.records.init_db()
        self.reference = "Strike-LA-20260529-001"
        self.verification_hash = self.insert_record(self.reference)

    def tearDown(self):
        self.records.DB_PATH = self.original_db_path
        self.temp_dir.cleanup()

    def insert_record(self, reference):
        conditions = ["Institutional Delay", "Transfer of Burden"]
        generated_at = "2026-05-29T09:00:00Z"
        finding = "Attachment upload must not change canonical record hashing."
        trajectory = "Stable"
        system_state = "Canonical record unchanged"
        generated_by = "Civic Decision Engine"
        verification_hash = self.records.compute_verification_hash(
            reference=reference,
            generated_at=generated_at,
            finding=finding,
            trajectory=trajectory,
            conditions=conditions,
            system_state=system_state,
            generated_by=generated_by,
        )

        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                """
                INSERT INTO records (
                    reference, version, supersedes, generated_at, trajectory,
                    system_state, conditions_json, signals_json, finding,
                    report_json, language, generated_by, verification_hash,
                    exported_at, is_latest, source_narrative
                )
                VALUES (?, 1, NULL, ?, ?, ?, ?, '[]', ?, ?, 'en', ?, ?, ?, 1, NULL)
                """,
                (
                    reference,
                    generated_at,
                    trajectory,
                    system_state,
                    json.dumps(conditions),
                    finding,
                    "{}",
                    generated_by,
                    verification_hash,
                    "2026-05-29T09:05:00Z",
                ),
            )
            conn.commit()
        finally:
            conn.close()

        return verification_hash

    def upload(
        self,
        *,
        token="secret-token",
        filename="evidence.pdf",
        data=b"evidence",
        document_date=None,
        document_date_precision="unknown",
    ):
        with patch.dict(
            os.environ,
            {
                "CDE_ADMIN_TOKEN": "secret-token",
                "CDE_ATTACHMENT_ROOT": str(self.attachment_root),
            },
            clear=False,
        ):
            return asyncio.run(
                self.records.admin_upload_record_attachment(
                    self.reference,
                    file=FakeUploadFile(filename, "application/pdf", data),
                    visibility="private",
                    redaction_status="none",
                    title="Evidence",
                    description="Admin uploaded evidence.",
                    source_label="Test source",
                    redaction_note=None,
                    document_date=document_date,
                    document_date_precision=document_date_precision,
                    x_cde_admin_token=token,
                )
            )

    def fetch_attachment_row(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            return conn.execute("SELECT * FROM record_attachments").fetchone()
        finally:
            conn.close()

    def test_valid_upload_stores_file_and_metadata(self):
        data = b"attachment bytes"

        response = self.upload(data=data)
        row = self.fetch_attachment_row()
        stored_path = Path(row["storage_path"])

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.content["attachment"]["reference"], self.reference)
        self.assertEqual(row["reference"], self.reference)
        self.assertEqual(row["record_version"], 1)
        self.assertEqual(row["filename"], "evidence.pdf")
        self.assertEqual(row["content_type"], "application/pdf")
        self.assertEqual(row["visibility"], "private")
        self.assertEqual(row["redaction_status"], "none")
        self.assertIsNone(row["document_date"])
        self.assertEqual(row["document_date_precision"], "unknown")
        self.assertEqual(stored_path.read_bytes(), data)
        self.assertTrue(stored_path.is_file())

    def test_invalid_token_is_rejected(self):
        with self.assertRaises(Exception) as ctx:
            self.upload(token="wrong-token")

        self.assertEqual(getattr(ctx.exception, "status_code", None), 403)
        self.assertEqual(self.fetch_attachment_row(), None)

    def test_missing_token_is_rejected(self):
        with self.assertRaises(Exception) as ctx:
            self.upload(token=None)

        self.assertEqual(getattr(ctx.exception, "status_code", None), 401)
        self.assertEqual(self.fetch_attachment_row(), None)

    def test_admin_route_disabled_when_env_token_unset(self):
        with patch.dict(
            os.environ,
            {"CDE_ATTACHMENT_ROOT": str(self.attachment_root)},
            clear=False,
        ):
            os.environ.pop("CDE_ADMIN_TOKEN", None)
            with self.assertRaises(Exception) as ctx:
                asyncio.run(
                    self.records.admin_upload_record_attachment(
                        self.reference,
                        file=FakeUploadFile("evidence.pdf", "application/pdf", b"x"),
                        x_cde_admin_token="secret-token",
                    )
                )

        self.assertEqual(getattr(ctx.exception, "status_code", None), 503)

    def test_missing_record_is_rejected(self):
        with patch.dict(
            os.environ,
            {
                "CDE_ADMIN_TOKEN": "secret-token",
                "CDE_ATTACHMENT_ROOT": str(self.attachment_root),
            },
            clear=False,
        ):
            with self.assertRaises(Exception) as ctx:
                asyncio.run(
                    self.records.admin_upload_record_attachment(
                        "Strike-LA-20990101-404",
                        file=FakeUploadFile("evidence.pdf", "application/pdf", b"x"),
                        x_cde_admin_token="secret-token",
                    )
                )

        self.assertEqual(getattr(ctx.exception, "status_code", None), 404)

    def test_path_traversal_filename_is_stored_safely_under_root(self):
        self.upload(filename="../../private/secret.PDF", data=b"safe")

        row = self.fetch_attachment_row()
        stored_path = Path(row["storage_path"])

        self.assertEqual(row["filename"], "secret.PDF")
        self.assertEqual(stored_path.name, f"attachment-{row['id']}-v1-{row['sha256_hash'][:8]}.pdf")
        self.assertEqual(
            stored_path.parent,
            self.attachment_root.resolve() / self.reference / "v1" / "attachments",
        )
        self.assertNotIn("..", stored_path.parts)

    def test_hash_generation_uses_uploaded_bytes(self):
        data = b"raw upload bytes\x00not decoded text"

        self.upload(data=data)
        row = self.fetch_attachment_row()

        self.assertEqual(row["sha256_hash"], hashlib.sha256(data).hexdigest())
        self.assertEqual(row["file_size_bytes"], len(data))

    def test_metadata_persistence(self):
        self.upload(document_date="2026-05-29", document_date_precision="day")

        row = self.fetch_attachment_row()

        self.assertEqual(row["title"], "Evidence")
        self.assertEqual(row["description"], "Admin uploaded evidence.")
        self.assertEqual(row["source_label"], "Test source")
        self.assertEqual(row["document_date"], "2026-05-29")
        self.assertEqual(row["document_date_precision"], "day")
        self.assertEqual(row["attachment_version"], 1)
        self.assertEqual(row["is_latest"], 1)
        self.assertEqual(row["is_deleted"], 0)

    def test_invalid_document_date_is_rejected(self):
        with self.assertRaises(Exception) as ctx:
            self.upload(document_date="29/05/2026", document_date_precision="day")

        self.assertEqual(getattr(ctx.exception, "status_code", None), 400)
        self.assertEqual(self.fetch_attachment_row(), None)

    def test_canonical_verification_hash_unchanged_after_upload(self):
        self.upload(data=b"attachment bytes")
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT verification_hash FROM records WHERE reference = ?",
                (self.reference,),
            ).fetchone()
        finally:
            conn.close()

        self.assertEqual(row["verification_hash"], self.verification_hash)


if __name__ == "__main__":
    unittest.main()
