import asyncio
import hashlib
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.test_admin_session import FakeRequest, install_fastapi_stubs

install_fastapi_stubs()

from api.document_intake import load_pending_document, store_pending_document, update_intake_status
from api.outlook_archive_jobs import (
    create_archive_inspection_job,
    load_archive_job,
    run_archive_inspection_job,
)
from api.outlook_archive_projections import projection_path
from api.outlook_archive_promotion import (
    OutlookArchivePromotionError,
    validate_outlook_message_promotion,
)
from api.routes import admin_session, archive, documents, records


PST_BYTES = b"CDE Platform Stage 39D governed promotion archive.\n" * 128


class FakePromotionParser:
    def supports(self, file_path: Path) -> bool:
        return file_path.suffix == ".pst"

    def inspect(self, _file_path: Path):
        return {
            "archive_validity": "plausible_outlook_archive",
            "mailbox_count": 1,
            "top_level_folder_count": 1,
            "archive_health": "projectable",
            "parser_warnings": [],
        }

    def project(self, _file_path: Path):
        return {
            "mailbox_name": "Governed Promotion Mailbox",
            "folders": [
                {
                    "folder_id": "folder-inbox",
                    "name": "Inbox",
                    "path": "Mailbox/Inbox",
                    "source_identifier": "folder-entry-id",
                    "message_count": 1,
                    "attachment_count": 0,
                }
            ],
            "messages": [
                {
                    "projection_id": "message-001",
                    "message_id": "<governed-promotion@example.test>",
                    "subject": "Governed promotion correspondence",
                    "sender": "sender@example.test",
                    "recipients": ["recipient@example.test"],
                    "sent_timestamp": "2026-07-31T10:15:00Z",
                    "message_class": "IPM.Note",
                    "conversation_id": "conversation-001",
                    "thread_index": "thread-001",
                    "attachment_count": 0,
                    "folder_id": "folder-inbox",
                    "folder_path": "Mailbox/Inbox",
                    "source_identifier": "message-entry-id",
                }
            ],
        }


class OutlookArchiveGovernedPromotionTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "pending"
        self.db_path = Path(self.temp_dir.name) / "records.db"
        self.env = patch.dict(
            os.environ,
            {
                "ADMIN_USERNAME": "promotion-admin",
                "ADMIN_PASSWORD": "admin-password",
                "CDE_ADMIN_SESSION_SECRET": "session-secret",
                "CDE_DOCUMENT_INTAKE_ROOT": str(self.root),
                "RECORDS_DB_PATH": str(self.db_path),
                "CDE_OUTLOOK_ARCHIVE_JOB_RUN_MODE": "inline",
                "CDE_OUTLOOK_ARCHIVE_PARSER_MODULE": __name__,
                "CDE_OUTLOOK_ARCHIVE_PARSER_CLASS": "FakePromotionParser",
                "CDE_OUTLOOK_ARCHIVE_PARSER_VERSION": "fake-promotion-parser-1.0",
            },
            clear=False,
        )
        self.env.start()
        self.original_admin_db = admin_session.DB_PATH
        self.original_records_db = records.DB_PATH
        admin_session.DB_PATH = self.db_path
        records.DB_PATH = self.db_path
        records.init_db()
        session = admin_session.create_admin_session("promotion-admin")
        self.request = FakeRequest(cookies={admin_session.SESSION_COOKIE_NAME: session})

    def tearDown(self):
        admin_session.DB_PATH = self.original_admin_db
        records.DB_PATH = self.original_records_db
        self.env.stop()
        self.temp_dir.cleanup()

    def _store_archive(self):
        return store_pending_document(
            data=PST_BYTES,
            original_filename="governed-promotion.pst",
            content_type="application/octet-stream",
            title="Governed Promotion Outlook Archive",
            institution_source="Civic Oversight Institution",
            document_date="2026-07-31",
            category="Outlook Archive",
            description="Preserved Outlook archive for governed promotion tests.",
            visibility="private",
            notes="Administrative fixture.",
            reference_identifier="CDE-STAGE39D-ARCHIVE-001",
            keywords="outlook, promotion",
            actor="promotion-admin",
            uploaded_at="2026-07-31T09:00:00Z",
            root=self.root,
        )

    def _project(self):
        item = self._store_archive()
        job = create_archive_inspection_job(
            item["intake_id"], actor="promotion-admin", root=self.root
        )
        completed = run_archive_inspection_job(job["job_id"], root=self.root)
        self.assertEqual(completed["status"], "completed")
        return item, completed

    def _record_count(self):
        with sqlite3.connect(self.db_path) as conn:
            return conn.execute("SELECT COUNT(*) FROM records").fetchone()[0]

    def _promote(self, item, *, confirm="1", reference="ADM-COI-20260731-001"):
        return admin_session.admin_outlook_archive_message_promotion_create(
            item["intake_id"],
            "message-001",
            self.request,
            record_type="administrative_action",
            reference=reference,
            record_title="Governed promotion correspondence",
            institution="Civic Oversight Institution",
            event_date="2026-07-31",
            summary="Governed correspondence promoted by explicit administrator decision.",
            trajectory="Submitted",
            system_state="Canonical Record created through governed promotion.",
            conditions="GOVERNED_MAILBOX_MESSAGE_PROMOTION",
            signals="EXPLICIT_ADMINISTRATIVE_PROMOTION",
            confirm_promotion=confirm,
        )

    def test_eligible_message_exposes_explicit_promotion_workflow_only(self):
        item, _job = self._project()
        self.assertEqual(self._record_count(), 0)

        detail = admin_session.admin_outlook_archive_message_projection_page(
            item["intake_id"], "message-001", self.request
        ).content
        self.assertIn("Message", detail)
        self.assertIn("Metadata", detail)
        self.assertIn("Relationships", detail)
        self.assertIn("Preview", detail)
        self.assertIn("Promote to Canonical Record", detail)
        self.assertIn("explicit administrator decision", detail)
        self.assertEqual(self._record_count(), 0)

        form = admin_session.admin_outlook_archive_message_promotion_page(
            item["intake_id"], "message-001", self.request
        ).content
        self.assertIn("Explicit administrative decision required", form)
        self.assertIn('name="confirm_promotion"', form)
        self.assertIn(hashlib.sha256(PST_BYTES).hexdigest(), form)

    def test_explicit_promotion_creates_ordinary_record_with_permanent_provenance(self):
        item, job = self._project()
        archive_before = load_pending_document(item["intake_id"], root=self.root)
        projection_before = projection_path(item["intake_id"], root=self.root).read_bytes()

        response = self._promote(item)
        self.assertEqual(response.status_code, 201)
        self.assertIn("explicit governed promotion", response.content)

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT * FROM records WHERE reference = ?",
                ("ADM-COI-20260731-001",),
            ).fetchone()
        finally:
            conn.close()
        self.assertIsNotNone(row)
        report = json.loads(row["report_json"])
        provenance = report["promotion_provenance"]
        self.assertEqual(provenance["archive_id"], item["intake_id"])
        self.assertEqual(provenance["folder_projection_id"], "folder-inbox")
        self.assertEqual(provenance["message_projection_id"], "message-001")
        self.assertEqual(
            provenance["message_identifier"], "<governed-promotion@example.test>"
        )
        self.assertEqual(provenance["extraction_job"], job["job_id"])
        self.assertEqual(provenance["administrator"], "promotion-admin")
        self.assertEqual(provenance["source_hash"], hashlib.sha256(PST_BYTES).hexdigest())
        self.assertEqual(provenance["projection_version"], "stage39c-projection-v1")
        self.assertTrue(provenance["promotion_timestamp"].endswith("Z"))
        self.assertEqual(row["source_document_id"], item["intake_id"])
        self.assertIn("preserved Outlook archive", row["source_narrative"])
        self.assertNotIn("promotion-admin", row["source_narrative"])
        self.assertEqual(
            load_pending_document(item["intake_id"], root=self.root)["sha256_hash"],
            archive_before["sha256_hash"],
        )
        self.assertEqual(
            projection_path(item["intake_id"], root=self.root).read_bytes(),
            projection_before,
        )

    def test_confirmation_and_duplicate_promotion_are_rejected(self):
        item, _job = self._project()
        with self.assertRaises(Exception) as missing_confirmation:
            self._promote(item, confirm=None)
        self.assertEqual(
            getattr(missing_confirmation.exception, "detail", None),
            "outlook_archive_promotion_confirmation_required",
        )
        self.assertEqual(self._record_count(), 0)

        self._promote(item)
        with self.assertRaises(Exception) as duplicate:
            self._promote(item, reference="ADM-COI-20260731-002")
        self.assertEqual(
            getattr(duplicate.exception, "detail", None),
            "outlook_archive_message_already_promoted",
        )
        self.assertEqual(self._record_count(), 1)

    def test_incomplete_or_invalid_projection_is_not_eligible(self):
        item, job = self._project()
        job_path = self.root / ".outlook_archive_jobs" / f"{job['job_id']}.json"
        job_payload = load_archive_job(job["job_id"], root=self.root)
        job_payload["status"] = "failed"
        job_path.write_text(json.dumps(job_payload), encoding="utf-8")
        with self.assertRaises(OutlookArchivePromotionError) as incomplete:
            validate_outlook_message_promotion(
                item["intake_id"], "message-001", root=self.root
            )
        self.assertEqual(
            incomplete.exception.code,
            "outlook_archive_promotion_extraction_incomplete",
        )

        job_payload["status"] = "completed"
        job_path.write_text(json.dumps(job_payload), encoding="utf-8")
        path = projection_path(item["intake_id"], root=self.root)
        projection = json.loads(path.read_text(encoding="utf-8"))
        projection["messages"][0]["provenance"].pop("source_identifier")
        path.write_text(json.dumps(projection), encoding="utf-8")
        with self.assertRaises(OutlookArchivePromotionError) as missing_provenance:
            validate_outlook_message_promotion(
                item["intake_id"], "message-001", root=self.root
            )
        self.assertEqual(
            missing_provenance.exception.code,
            "outlook_archive_promotion_provenance_missing",
        )

    def test_promotion_routes_are_admin_only_and_public_archive_remains_unchanged(self):
        item, _job = self._project()
        unauthorized = FakeRequest(cookies={})
        with self.assertRaises(Exception) as page_error:
            admin_session.admin_outlook_archive_message_promotion_page(
                item["intake_id"], "message-001", unauthorized
            )
        self.assertEqual(getattr(page_error.exception, "status_code", None), 401)

        self._promote(item)
        for status in ("under_review", "approved", "published"):
            update_intake_status(
                item["intake_id"],
                status,
                actor="promotion-admin",
                note=f"{status} archive lifecycle transition.",
                root=self.root,
            )
        public_metadata = archive.public_outlook_archive_metadata(item["intake_id"])
        public_page = documents.public_document_page(item["intake_id"]).content
        public_record = asyncio.run(records.verify_record("ADM-COI-20260731-001")).content
        self.assertNotIn("promotion_provenance", public_metadata)
        self.assertNotIn("Governed promotion correspondence", str(public_metadata))
        self.assertNotIn("Promote to Canonical Record", public_page)
        self.assertNotIn("sender@example.test", public_page)
        self.assertNotIn("promotion-admin", public_record)
        self.assertNotIn("message-entry-id", public_record)


if __name__ == "__main__":
    unittest.main()
