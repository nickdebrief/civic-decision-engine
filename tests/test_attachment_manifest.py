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


class AttachmentManifestTests(unittest.TestCase):
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
        self.reference = "Strike-LA-20260530-001"
        self.verification_hash = self.insert_record(self.reference)

    def tearDown(self):
        self.records.DB_PATH = self.original_db_path
        self.temp_dir.cleanup()

    def insert_record(self, reference):
        conditions = ["Institutional Delay", "Transfer of Burden"]
        generated_at = "2026-05-30T09:00:00Z"
        finding = "Attachment manifest expansion must not change canonical hashing."
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
                    "2026-05-30T09:05:00Z",
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
        document_date="2026-05-30",
        document_date_precision="day",
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
                        ?, ?, ?, '2026-05-30T10:00:00Z', ?, ?)
                """,
                (
                    self.reference,
                    filename,
                    "a" * 64,
                    visibility,
                    redaction_status,
                    "Attachment title",
                    "Attachment description",
                    "Attachment source",
                    document_date,
                    document_date_precision,
                    publication_status,
                    is_latest,
                    is_deleted,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def manifest(self):
        return asyncio.run(self.records.record_manifest(self.reference)).content

    def test_manifest_contains_empty_attachments_array_without_attachments(self):
        payload = self.manifest()

        self.assertIn("attachments", payload)
        self.assertEqual(payload["attachments"], [])
        self.assertEqual(
            payload["attachment_integrity_note"],
            {
                "canonical_record_hash_unchanged": True,
                "attachment_hashes_independent": True,
            },
        )

    def test_public_attachment_metadata_appears_without_storage_fields(self):
        self.insert_attachment()

        attachment = self.manifest()["attachments"][0]

        self.assertEqual(
            set(attachment.keys()),
            {
                "attachment_id",
                "attachment_version",
                "filename",
                "content_type",
                "file_size_bytes",
                "sha256_hash",
                "visibility",
                "redaction_status",
                "title",
                "description",
                "source_label",
                "document_date",
                "document_date_precision",
                "uploaded_at",
                "download_url",
            },
        )
        self.assertEqual(attachment["filename"], "example.pdf")
        self.assertEqual(attachment["content_type"], "application/pdf")
        self.assertEqual(attachment["file_size_bytes"], 12345)
        self.assertEqual(attachment["sha256_hash"], "a" * 64)
        self.assertEqual(attachment["visibility"], "public")
        self.assertEqual(attachment["redaction_status"], "none")
        self.assertEqual(attachment["title"], "Attachment title")
        self.assertEqual(attachment["description"], "Attachment description")
        self.assertEqual(attachment["source_label"], "Attachment source")
        self.assertEqual(attachment["document_date"], "2026-05-30")
        self.assertEqual(attachment["document_date_precision"], "day")
        self.assertEqual(attachment["uploaded_at"], "2026-05-30T10:00:00Z")
        self.assertIsNone(attachment["download_url"])
        encoded = json.dumps(self.manifest(), sort_keys=True)
        self.assertNotIn("storage_path", encoded)
        self.assertNotIn("stored_filename", encoded)
        self.assertNotIn("/private/path", encoded)

    def test_unknown_document_date_appears_as_null_and_unknown(self):
        self.insert_attachment(document_date=None, document_date_precision="unknown")

        attachment = self.manifest()["attachments"][0]

        self.assertIsNone(attachment["document_date"])
        self.assertEqual(attachment["document_date_precision"], "unknown")

    def test_private_deleted_and_withheld_attachments_are_excluded(self):
        self.insert_attachment(visibility="private", filename="private.pdf")
        self.insert_attachment(is_deleted=1, filename="deleted.pdf")
        self.insert_attachment(redaction_status="withheld", filename="withheld.pdf")

        self.assertEqual(self.manifest()["attachments"], [])

    def test_publication_status_filters_public_manifest_attachments(self):
        self.insert_attachment(filename="internal.pdf", publication_status="internal")
        self.insert_attachment(filename="withdrawn.pdf", publication_status="withdrawn")
        self.insert_attachment(filename="published.pdf", publication_status="published")
        self.insert_attachment(
            filename="published-withheld.pdf",
            publication_status="published",
            redaction_status="withheld",
        )
        self.insert_attachment(
            filename="published-deleted.pdf",
            publication_status="published",
            is_deleted=1,
        )

        attachments = self.manifest()["attachments"]

        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments[0]["filename"], "published.pdf")

    def test_canonical_hash_and_serialization_remain_identical_after_attachment(self):
        before = self.manifest()
        before_hash = before["verification_hash"]
        before_serialization = before["recomputation_instruction"][
            "canonical_serialization"
        ]

        self.insert_attachment()
        after = self.manifest()

        self.assertEqual(after["verification_hash"], before_hash)
        self.assertEqual(after["verification_hash"], self.verification_hash)
        self.assertEqual(
            after["recomputation_instruction"]["canonical_serialization"],
            before_serialization,
        )
        self.assertEqual(after["canonical_fields"], before["canonical_fields"])

    def test_existing_api_verify_response_remains_unchanged(self):
        self.insert_attachment()

        response = asyncio.run(self.records.api_verify_record(self.reference)).content

        self.assertEqual(
            set(response.keys()),
            {
                "reference",
                "finding",
                "trajectory",
                "conditions",
                "system_state",
                "verification_hash",
                "version",
            },
        )
        self.assertNotIn("attachments", response)
        self.assertEqual(response["verification_hash"], self.verification_hash)


if __name__ == "__main__":
    unittest.main()
