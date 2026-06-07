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
        classification="evidence",
    ):
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.execute(
                """
                INSERT INTO record_attachments (
                    reference, record_version, attachment_version,
                    filename, stored_filename, storage_path,
                    content_type, file_size_bytes, sha256_hash,
                    visibility, redaction_status, title, description,
                    source_label, classification, document_date,
                    document_date_precision, publication_status,
                    uploaded_at, is_latest, is_deleted
                )
                VALUES (?, 1, 1, ?, 'stored.pdf', '/private/path/stored.pdf',
                        'application/pdf', 12345, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, '2026-05-30T10:00:00Z', ?, ?)
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
                    classification,
                    document_date,
                    document_date_precision,
                    publication_status,
                    is_latest,
                    is_deleted,
                ),
            )
            attachment_id = int(cursor.lastrowid)
            conn.commit()
        finally:
            conn.close()
        return attachment_id

    def insert_relationship(
        self,
        attachment_id,
        *,
        relationship_type="supports",
        target_type="condition",
        target_key="Transfer of Burden",
        is_active=1,
    ):
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                """
                INSERT INTO record_attachment_relationships (
                    reference, record_version, attachment_id, relationship_type,
                    target_type, target_key, is_active, created_at, created_by
                )
                VALUES (?, 1, ?, ?, ?, ?, ?, '2026-05-30T10:30:00Z', 'admin')
                """,
                (
                    self.reference,
                    attachment_id,
                    relationship_type,
                    target_type,
                    target_key,
                    is_active,
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

    def public_evidence_manifest(self):
        return asyncio.run(
            self.records.public_evidence_manifest(self.reference)
        ).content

    def public_evidence_page(self):
        return asyncio.run(
            self.records.public_evidence_manifest_page(self.reference)
        ).content

    def test_public_evidence_manifest_includes_only_eligible_published_attachments(self):
        published_id = self.insert_attachment(filename="published.pdf")
        self.insert_attachment(filename="internal.pdf", publication_status="internal")
        self.insert_attachment(filename="withdrawn.pdf", publication_status="withdrawn")
        self.insert_attachment(
            filename="private.pdf",
            visibility="private",
            publication_status="published",
        )
        self.insert_attachment(
            filename="withheld.pdf",
            redaction_status="withheld",
            publication_status="published",
        )
        self.insert_attachment(
            filename="deleted.pdf",
            is_deleted=1,
            publication_status="published",
        )
        self.insert_relationship(published_id)
        self.insert_relationship(
            published_id,
            target_key="Inactive relationship",
            is_active=0,
        )

        payload = self.public_evidence_manifest()
        encoded = json.dumps(payload, sort_keys=True)

        self.assertEqual(payload["manifest_type"], "civic_decision_engine_public_evidence")
        self.assertEqual(payload["reference"], self.reference)
        self.assertEqual(payload["record_version"], 1)
        self.assertEqual(len(payload["attachments"]), 1)
        attachment = payload["attachments"][0]
        self.assertEqual(
            set(attachment.keys()),
            {
                "attachment_id",
                "record_version",
                "title",
                "description",
                "source_label",
                "classification",
                "publication_status",
                "filename",
                "content_type",
                "file_size",
                "sha256_hash",
                "document_date",
                "document_date_precision",
                "uploaded_at",
                "relationships",
            },
        )
        self.assertEqual(attachment["attachment_id"], published_id)
        self.assertEqual(attachment["filename"], "published.pdf")
        self.assertEqual(attachment["classification"], "evidence")
        self.assertEqual(attachment["publication_status"], "published")
        self.assertEqual(attachment["file_size"], 12345)
        self.assertEqual(
            attachment["relationships"],
            [
                {
                    "relationship_type": "supports",
                    "target_type": "condition",
                    "target_key": "Transfer of Burden",
                }
            ],
        )
        self.assertNotIn("internal.pdf", encoded)
        self.assertNotIn("withdrawn.pdf", encoded)
        self.assertNotIn("private.pdf", encoded)
        self.assertNotIn("withheld.pdf", encoded)
        self.assertNotIn("deleted.pdf", encoded)
        self.assertNotIn("Inactive relationship", encoded)
        self.assertNotIn("storage_path", encoded)
        self.assertNotIn("stored_filename", encoded)
        self.assertNotIn("/private/path", encoded)
        self.assertNotIn("download_url", encoded)
        self.assertNotIn("file bytes", encoded.lower())

    def test_public_evidence_html_renders_attachment_relationship_and_empty_state(self):
        attachment_id = self.insert_attachment(filename="public-evidence.pdf")
        self.insert_relationship(attachment_id)

        html = self.public_evidence_page()

        self.assertIn("Public Evidence Manifest", html)
        self.assertIn(self.reference, html)
        self.assertIn("public-evidence.pdf", html)
        self.assertIn("evidence", html)
        self.assertIn("published", html)
        self.assertIn("2026-05-30", html)
        self.assertIn("application/pdf", html)
        self.assertIn("12345", html)
        self.assertIn("a" * 64, html)
        self.assertIn("Attachment source", html)
        self.assertIn("supports • condition • Transfer of Burden", html)
        self.assertIn(
            "This public evidence manifest is read-only. It verifies published "
            "attachment metadata only. No file download or file access is provided.",
            html,
        )
        self.assertNotIn("storage_path", html)
        self.assertNotIn("stored_filename", html)
        self.assertNotIn("/private/path", html)
        self.assertNotIn("CDE_ADMIN_TOKEN", html)
        self.assertNotIn("<form", html)
        self.assertNotIn("<button", html)
        self.assertNotIn("Update classification", html)
        self.assertNotIn("Add relationship", html)
        self.assertNotIn("Remove relationship", html)

        empty_reference = "Strike-LA-20260530-EMPTY"
        self.insert_record(empty_reference)
        original_reference = self.reference
        self.reference = empty_reference
        try:
            empty_html = self.public_evidence_page()
        finally:
            self.reference = original_reference
        self.assertIn(
            "No published public evidence is currently available for this record.",
            empty_html,
        )

    def test_public_evidence_manifest_does_not_change_record_verification_behavior(self):
        before_manifest = self.manifest()
        before_verify = asyncio.run(self.records.api_verify_record(self.reference)).content
        attachment_id = self.insert_attachment()
        self.insert_relationship(attachment_id)

        evidence_manifest = self.public_evidence_manifest()
        after_manifest = self.manifest()
        after_verify = asyncio.run(self.records.api_verify_record(self.reference)).content

        self.assertEqual(after_manifest["verification_hash"], before_manifest["verification_hash"])
        self.assertEqual(after_manifest["canonical_fields"], before_manifest["canonical_fields"])
        self.assertEqual(
            after_manifest["recomputation_instruction"]["canonical_serialization"],
            before_manifest["recomputation_instruction"]["canonical_serialization"],
        )
        self.assertEqual(after_verify, before_verify)
        self.assertEqual(evidence_manifest["attachments"][0]["relationships"][0]["target_key"], "Transfer of Burden")


if __name__ == "__main__":
    unittest.main()
