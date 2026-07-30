import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.test_admin_session import FakeRequest, install_fastapi_stubs

install_fastapi_stubs()

from api.document_intake import intake_document_file, load_pending_document, store_pending_document
from api.outlook_archive_jobs import (
    ARCHIVE_JOB_CHUNK_BYTES,
    archive_job_status,
    cancel_archive_job,
    create_archive_inspection_job,
    list_archive_jobs,
    load_archive_job,
    retry_archive_job,
    run_archive_inspection_job,
)
from api.routes import admin_session, archive, documents


PST_BYTES = (b"CDE Platform Stage 39B preserved PST archive bytes.\n" * 4096) + b"\x00pst"


class FakeOutlookArchiveParser:
    def supports(self, file_path: Path) -> bool:
        return file_path.suffix == ".pst"

    def inspect(self, file_path: Path):
        return {
            "archive_validity": "plausible_outlook_archive",
            "mailbox_count": 2,
            "top_level_folder_count": 4,
            "archive_health": "healthy",
            "parser_warnings": ["bounded parser warning"],
        }


class OutlookArchiveJobTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "pending"
        self.env = patch.dict(
            os.environ,
            {
                "ADMIN_USERNAME": "archive-admin",
                "ADMIN_PASSWORD": "admin-password",
                "CDE_ADMIN_SESSION_SECRET": "session-secret",
                "CDE_DOCUMENT_INTAKE_ROOT": str(self.root),
                "CDE_OUTLOOK_ARCHIVE_JOB_RUN_MODE": "inline",
            },
            clear=False,
        )
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp_dir.cleanup()

    def _store(self, data: bytes = PST_BYTES):
        return store_pending_document(
            data=data,
            original_filename="stage39b-archive.pst",
            content_type="application/octet-stream",
            title="Stage 39B Outlook Archive",
            institution_source="CDE Platform Archive Source",
            document_date="2026-07-30",
            category="Outlook Archive",
            description="Preserved Outlook archive for Stage 39B job testing.",
            visibility="private",
            notes="Archive job test fixture.",
            reference_identifier="CDE-PLATFORM-STAGE39B-001",
            keywords="pst, outlook, stage39b",
            actor="archive-admin",
            uploaded_at="2026-07-30T09:00:00Z",
            root=self.root,
        )

    def _request(self):
        return FakeRequest(
            cookies={
                admin_session.SESSION_COOKIE_NAME: admin_session.create_admin_session("archive-admin")
            }
        )

    def test_archive_intake_records_preservation_metadata_before_inspection(self):
        item = self._store()
        metadata = item["outlook_archive_metadata"]

        self.assertTrue(metadata["preservation_complete"])
        self.assertEqual(metadata["hash_verification_status"], "verified")
        self.assertEqual(metadata["preservation_timestamp"], item["upload_date"])
        self.assertEqual(metadata["preservation_completed_at"], item["upload_date"])
        self.assertEqual(metadata["inspection_complete"], False)
        self.assertIsNone(metadata["latest_archive_job_id"])
        self.assertEqual(Path(metadata["storage_path"]).read_bytes(), PST_BYTES)

    def test_archive_job_creation_is_durable_and_metadata_only(self):
        item = self._store()

        job = create_archive_inspection_job(
            item["intake_id"],
            actor="archive-admin",
            root=self.root,
        )

        self.assertTrue(job["job_id"].startswith("outlook-job-"))
        self.assertEqual(job["status"], "queued")
        self.assertEqual(job["phase"], "Queued")
        self.assertEqual(job["document_id"], item["intake_id"])
        self.assertEqual(job["preservation"]["archive_size_bytes"], len(PST_BYTES))
        self.assertIn("Uploaded", [entry["phase"] for entry in job["history"]])
        reloaded = load_archive_job(job["job_id"], root=self.root)
        self.assertEqual(reloaded["job_id"], job["job_id"])

        metadata = load_pending_document(item["intake_id"], root=self.root)["outlook_archive_metadata"]
        self.assertEqual(metadata["latest_archive_job_id"], job["job_id"])
        self.assertNotIn("folders", metadata)
        self.assertNotIn("messages", metadata)

    def test_parser_unavailable_completes_preservation_job_without_extraction(self):
        item = self._store()
        job = create_archive_inspection_job(item["intake_id"], actor="archive-admin", root=self.root)

        completed = run_archive_inspection_job(job["job_id"], root=self.root)

        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["progress_percent"], 100)
        self.assertFalse(completed["inspection"]["inspection_complete"])
        self.assertEqual(completed["inspection"]["archive_health"], "parser_not_configured")
        self.assertGreaterEqual(
            len(PST_BYTES),
            ARCHIVE_JOB_CHUNK_BYTES // 8,
        )
        metadata = load_pending_document(item["intake_id"], root=self.root)["outlook_archive_metadata"]
        self.assertEqual(metadata["hash_verification_status"], "verified")
        self.assertFalse(metadata["inspection_complete"])
        self.assertFalse(metadata["message_extraction_performed"])
        self.assertFalse(metadata["canonical_record_generation_performed"])
        file_path, _metadata = intake_document_file(item["intake_id"], root=self.root)
        self.assertEqual(Path(file_path).read_bytes(), PST_BYTES)
        self.assertEqual(hashlib.sha256(PST_BYTES).hexdigest(), metadata.get("sha256_hash", item["sha256_hash"]))

    def test_configured_parser_records_lightweight_inspection_only(self):
        with patch.dict(
            os.environ,
            {
                "CDE_OUTLOOK_ARCHIVE_PARSER_MODULE": __name__,
                "CDE_OUTLOOK_ARCHIVE_PARSER_CLASS": "FakeOutlookArchiveParser",
                "CDE_OUTLOOK_ARCHIVE_PARSER_VERSION": "fake-parser-1.0",
            },
            clear=False,
        ):
            item = self._store()
            job = create_archive_inspection_job(item["intake_id"], actor="archive-admin", root=self.root)
            completed = run_archive_inspection_job(job["job_id"], root=self.root)

        self.assertEqual(completed["status"], "completed")
        self.assertTrue(completed["inspection"]["inspection_complete"])
        self.assertEqual(completed["inspection"]["mailbox_count"], 2)
        self.assertEqual(completed["inspection"]["top_level_folder_count"], 4)
        self.assertEqual(completed["parser"]["parser_version"], "fake-parser-1.0")
        self.assertIn("bounded parser warning", completed["warnings"])

        metadata = load_pending_document(item["intake_id"], root=self.root)["outlook_archive_metadata"]
        self.assertTrue(metadata["inspection_complete"])
        self.assertEqual(metadata["archive_health"], "healthy")
        self.assertEqual(metadata["mailbox_count"], 2)
        self.assertFalse(metadata["message_extraction_performed"])

    def test_retry_and_cancel_update_durable_job_state(self):
        item = self._store()
        job = create_archive_inspection_job(item["intake_id"], actor="archive-admin", root=self.root)

        cancelled = cancel_archive_job(job["job_id"], actor="archive-admin", root=self.root)
        self.assertEqual(cancelled["status"], "cancelled")

        retried = retry_archive_job(job["job_id"], actor="archive-admin", root=self.root)
        self.assertEqual(retried["status"], "completed")
        self.assertEqual(retried["retry_count"], 1)
        self.assertEqual(load_archive_job(job["job_id"], root=self.root)["status"], "completed")

    def test_admin_pages_and_apis_expose_job_metadata(self):
        request = self._request()
        item = self._store()

        page = admin_session.admin_document_intake_page(request).content
        self.assertIn("Archive Jobs", page)
        self.assertIn("Open Archive Jobs dashboard", page)
        preview = admin_session.admin_document_intake_preview_page(item["intake_id"], request).content
        self.assertIn("Queue archive inspection", preview)
        self.assertIn("CDE Platform Stage 39B", preview)

        response = admin_session.admin_archive_inspection_job_create(item["intake_id"], request)
        self.assertEqual(response.status_code, 202)
        self.assertIn("Archive Job", response.content)

        jobs_payload = admin_session.admin_archive_jobs_api(request)
        self.assertEqual(len(jobs_payload["jobs"]), 1)
        job_id = jobs_payload["jobs"][0]["job_id"]
        self.assertEqual(
            admin_session.admin_archive_job_status_api(job_id, request)["status"],
            "completed",
        )
        logs_payload = admin_session.admin_archive_job_logs_api(job_id, request)
        self.assertEqual(logs_payload["job_id"], job_id)
        self.assertTrue(logs_payload["logs"])
        self.assertNotIn(PST_BYTES[:20].decode("utf-8", errors="ignore"), json.dumps(logs_payload))

        jobs_page = admin_session.admin_archive_jobs_page(request).content
        self.assertIn(job_id, jobs_page)
        detail_page = admin_session.admin_archive_job_page(job_id, request).content
        self.assertIn("Structured logs", detail_page)

    def test_public_archive_status_includes_preservation_not_mailbox_contents(self):
        item = self._store()
        job = create_archive_inspection_job(item["intake_id"], actor="archive-admin", root=self.root)
        run_archive_inspection_job(job["job_id"], root=self.root)
        for status in ("under_review", "approved", "published"):
            item = admin_session.update_intake_status(
                item["intake_id"],
                status,
                actor="archive-admin",
                note=f"{status} note",
                root=self.root,
            )

        payload = archive.public_outlook_archive_metadata(item["intake_id"])
        self.assertTrue(payload["preservation_complete"])
        self.assertEqual(payload["hash_verification_status"], "verified")
        self.assertFalse(payload["inspection_complete"])
        self.assertNotIn("mailbox_count", payload)
        self.assertNotIn("top_level_folder_count", payload)

        status_payload = archive.public_outlook_archive_status(item["intake_id"])
        self.assertTrue(status_payload["preservation_complete"])
        self.assertFalse(status_payload["message_extraction_performed"])
        public_page = documents.public_document_page(item["intake_id"]).content
        self.assertIn("Preservation complete", public_page)
        self.assertIn("Not performed in CDE Platform Stage 39B", public_page)
        self.assertNotIn("Mailbox Message Index", public_page)

    def test_checksum_mismatch_fails_job_without_removing_preserved_archive(self):
        item = self._store()
        job = create_archive_inspection_job(item["intake_id"], actor="archive-admin", root=self.root)
        file_path, _metadata = intake_document_file(item["intake_id"], root=self.root)
        Path(file_path).write_bytes(PST_BYTES + b"tampered")

        failed = run_archive_inspection_job(job["job_id"], root=self.root)

        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["error_code"], "archive_job_checksum_mismatch")
        metadata = load_pending_document(item["intake_id"], root=self.root)["outlook_archive_metadata"]
        self.assertEqual(metadata["hash_verification_status"], "failed")
        self.assertTrue(Path(file_path).exists())

    def test_job_list_is_deterministic_and_metadata_only(self):
        first = self._store()
        second = self._store(PST_BYTES + b"second")

        first_job = create_archive_inspection_job(first["intake_id"], root=self.root)
        second_job = create_archive_inspection_job(second["intake_id"], root=self.root)

        listed_ids = [job["job_id"] for job in list_archive_jobs(root=self.root)]
        self.assertEqual(sorted(listed_ids), sorted([first_job["job_id"], second_job["job_id"]]))
        self.assertEqual(archive_job_status(second_job)["status"], "queued")


if __name__ == "__main__":
    unittest.main()
