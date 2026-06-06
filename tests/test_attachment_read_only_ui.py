import asyncio
import importlib
import json
import os
import sqlite3
import sys
import tempfile
import types
import unittest
from pathlib import Path


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


class AttachmentReadOnlyUITests(unittest.TestCase):
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
        self.original_db_path = self.records.DB_PATH
        self.records.DB_PATH = self.db_path
        self.records.init_db()
        self.reference = "Strike-LA-20260604-001"
        self.verification_hash = self.insert_record(self.reference)

    def tearDown(self):
        self.records.DB_PATH = self.original_db_path
        self.temp_dir.cleanup()

    def insert_record(self, reference):
        conditions = ["Institutional Delay", "Transfer of Burden"]
        generated_at = "2026-06-04T09:00:00Z"
        finding = "Read-only attachment display must not change canonical hashing."
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
                    "2026-06-04T09:05:00Z",
                ),
            )
            conn.commit()
        finally:
            conn.close()

        return verification_hash

    def insert_attachment(
        self,
        *,
        visibility="public",
        redaction_status="none",
        is_latest=1,
        is_deleted=0,
        filename="example.pdf",
        title="Attachment title",
        publication_status="published",
    ):
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                """
                INSERT INTO record_attachments (
                    reference, record_version, attachment_version,
                    filename, stored_filename, storage_path,
                    content_type, file_size_bytes, sha256_hash,
                    visibility, redaction_status, title, description,
                    source_label, document_date, document_date_precision,
                    publication_status,
                    uploaded_at, is_latest, is_deleted
                )
                VALUES (?, 1, 1, ?, 'stored.pdf', '/private/path/stored.pdf',
                        'application/pdf', 12345, ?, ?, ?, ?, ?, ?,
                        '2026-06-04', 'day', ?, '2026-06-04T10:00:00Z', ?, ?)
                """,
                (
                    self.reference,
                    filename,
                    "b" * 64,
                    visibility,
                    redaction_status,
                    title,
                    "Attachment description",
                    "Attachment source",
                    publication_status,
                    is_latest,
                    is_deleted,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def verify_html(self):
        return asyncio.run(self.records.verify_record(self.reference)).content

    def test_public_non_withheld_attachment_appears_in_read_only_ui(self):
        self.insert_attachment()

        content = self.verify_html()

        self.assertIn("<h2 class=\"section-title\">Attachments</h2>", content)
        self.assertIn("Attachments are referenced evidence artifacts.", content)
        self.assertIn("Attachment hashes are independent of canonical record hashes.", content)
        self.assertIn("Attachments do not alter the canonical record verification hash.", content)
        self.assertIn("Attachment title", content)
        self.assertIn("Attachment description", content)
        self.assertIn("Attachment source", content)
        self.assertIn("example.pdf", content)
        self.assertIn("application/pdf", content)
        self.assertIn("12345", content)
        self.assertIn("b" * 64, content)
        self.assertIn("public", content)
        self.assertIn("none", content)
        self.assertIn("2026-06-04", content)
        self.assertIn("day", content)
        self.assertIn("2026-06-04T10:00:00Z", content)
        self.assertIn("Download not available in v12.1", content)

    def test_empty_state_appears_when_no_public_attachments_exist(self):
        content = self.verify_html()

        self.assertIn("No public attachments are listed for this record.", content)

    def test_private_withheld_deleted_and_non_latest_attachments_do_not_appear(self):
        self.insert_attachment(
            visibility="private",
            filename="private.pdf",
            title="Private attachment",
            publication_status="published",
        )
        self.insert_attachment(
            redaction_status="withheld",
            filename="withheld.pdf",
            title="Withheld attachment",
            publication_status="published",
        )
        self.insert_attachment(
            is_deleted=1,
            filename="deleted.pdf",
            title="Deleted attachment",
            publication_status="published",
        )
        self.insert_attachment(
            is_latest=0,
            filename="old.pdf",
            title="Old attachment",
            publication_status="published",
        )
        self.insert_attachment(
            filename="internal.pdf",
            title="Internal attachment",
            publication_status="internal",
        )
        self.insert_attachment(
            filename="withdrawn.pdf",
            title="Withdrawn attachment",
            publication_status="withdrawn",
        )

        content = self.verify_html()

        self.assertIn("No public attachments are listed for this record.", content)
        self.assertNotIn("Private attachment", content)
        self.assertNotIn("Withheld attachment", content)
        self.assertNotIn("Deleted attachment", content)
        self.assertNotIn("Old attachment", content)
        self.assertNotIn("Internal attachment", content)
        self.assertNotIn("Withdrawn attachment", content)
        self.assertNotIn("private.pdf", content)
        self.assertNotIn("withheld.pdf", content)
        self.assertNotIn("deleted.pdf", content)
        self.assertNotIn("old.pdf", content)

    def test_internal_storage_fields_and_download_controls_are_not_exposed(self):
        self.insert_attachment()

        content = self.verify_html()

        self.assertNotIn("storage_path", content)
        self.assertNotIn("stored_filename", content)
        self.assertNotIn("/private/path", content)
        self.assertNotIn("/attachments/", content)
        self.assertNotIn("Upload attachment", content)
        self.assertNotIn("Edit attachment", content)
        self.assertNotIn("Delete attachment", content)
        self.assertNotIn("Replace attachment", content)
        self.assertNotIn("Redact attachment", content)
        self.assertNotIn("Restore attachment", content)
        self.assertNotIn("Download attachment", content)

    def test_canonical_verification_hash_remains_unchanged(self):
        before = asyncio.run(self.records.record_manifest(self.reference)).content
        before_hash = before["verification_hash"]

        self.insert_attachment()
        content = self.verify_html()
        after = asyncio.run(self.records.record_manifest(self.reference)).content

        self.assertEqual(after["verification_hash"], before_hash)
        self.assertEqual(after["verification_hash"], self.verification_hash)
        self.assertIn(self.verification_hash, content)


if __name__ == "__main__":
    unittest.main()
