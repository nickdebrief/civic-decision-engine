import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.test_admin_session import FakeRequest, install_fastapi_stubs

install_fastapi_stubs()

from api.document_intake import load_pending_document, store_pending_document
from api.outlook_archive_jobs import create_archive_inspection_job, run_archive_inspection_job
from api.outlook_archive_projections import (
    get_projection_folder,
    get_projection_message,
    load_outlook_archive_projection,
    projection_path,
    projection_statistics,
    search_projection_metadata,
)
from api.routes import admin_session, archive, documents


PST_BYTES = b"CDE Platform Stage 39C projection archive bytes.\n" * 128


class FakeProjectionParser:
    def supports(self, file_path: Path) -> bool:
        return file_path.suffix == ".pst"

    def inspect(self, file_path: Path):
        return {
            "archive_validity": "plausible_outlook_archive",
            "mailbox_count": 1,
            "top_level_folder_count": 2,
            "archive_health": "projectable",
            "parser_warnings": ["recoverable folder warning"],
        }

    def project(self, file_path: Path):
        return {
            "mailbox_name": "Civic Outlook Mailbox",
            "folders": [
                {
                    "folder_id": "folder-inbox",
                    "name": "Inbox",
                    "path": "Mailbox/Inbox",
                    "source_identifier": "entry-folder-inbox",
                    "message_count": 1,
                    "subfolder_count": 1,
                    "attachment_count": 1,
                    "projected_size_bytes": 2048,
                },
                {
                    "folder_id": "folder-case",
                    "parent_id": "folder-inbox",
                    "name": "Case A",
                    "path": "Mailbox/Inbox/Case A",
                    "source_identifier": "entry-folder-case",
                    "message_count": 1,
                    "subfolder_count": 0,
                    "attachment_count": 0,
                    "projected_size_bytes": 1024,
                },
            ],
            "messages": [
                {
                    "projection_id": "message-001",
                    "message_id": "<case-a@example.test>",
                    "subject": "Case A intake correspondence",
                    "sender": "alice@example.test",
                    "recipients": ["oversight@example.test"],
                    "cc": ["records@example.test"],
                    "sent_timestamp": "2026-07-30T09:30:00Z",
                    "received_timestamp": "2026-07-30T09:31:00Z",
                    "message_class": "IPM.Note",
                    "conversation_id": "conversation-case-a",
                    "thread_index": "thread-index-001",
                    "attachment_count": 1,
                    "read_status": "read",
                    "importance": "normal",
                    "categories": ["Case A", "Intake"],
                    "folder_id": "folder-inbox",
                    "folder_path": "Mailbox/Inbox",
                    "source_identifier": "entry-message-001",
                },
                {
                    "projection_id": "message-002",
                    "message_id": "<nested@example.test>",
                    "subject": "Nested folder update",
                    "sender": "bob@example.test",
                    "recipients": ["alice@example.test"],
                    "sent_timestamp": "2026-07-30T10:00:00Z",
                    "message_class": "IPM.Note",
                    "conversation_id": "conversation-case-a",
                    "thread_index": "thread-index-002",
                    "attachment_count": 0,
                    "read_status": "unread",
                    "importance": "high",
                    "categories": ["Case A"],
                    "folder_id": "folder-case",
                    "folder_path": "Mailbox/Inbox/Case A",
                    "source_identifier": "entry-message-002",
                },
            ],
            "projection_warnings": ["metadata-only projection warning"],
        }


class OutlookArchiveProjectionTests(unittest.TestCase):
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
                "CDE_OUTLOOK_ARCHIVE_PARSER_MODULE": __name__,
                "CDE_OUTLOOK_ARCHIVE_PARSER_CLASS": "FakeProjectionParser",
                "CDE_OUTLOOK_ARCHIVE_PARSER_VERSION": "fake-projection-parser-1.0",
            },
            clear=False,
        )
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp_dir.cleanup()

    def _request(self):
        return FakeRequest(
            cookies={
                admin_session.SESSION_COOKIE_NAME: admin_session.create_admin_session("archive-admin")
            }
        )

    def _store(self):
        return store_pending_document(
            data=PST_BYTES,
            original_filename="stage39c-archive.pst",
            content_type="application/octet-stream",
            title="Stage 39C Outlook Archive",
            institution_source="CDE Platform Archive Source",
            document_date="2026-07-30",
            category="Outlook Archive",
            description="Preserved Outlook archive for Stage 39C projection.",
            visibility="private",
            notes="Projection test fixture.",
            reference_identifier="CDE-PLATFORM-STAGE39C-001",
            keywords="pst, outlook, projection",
            actor="archive-admin",
            uploaded_at="2026-07-30T09:00:00Z",
            root=self.root,
        )

    def _project(self):
        item = self._store()
        job = create_archive_inspection_job(item["intake_id"], actor="archive-admin", root=self.root)
        completed = run_archive_inspection_job(job["job_id"], root=self.root)
        return item, completed, load_outlook_archive_projection(item["intake_id"], root=self.root)

    def test_parser_backed_job_creates_folder_and_message_projection(self):
        item, job, projection = self._project()

        self.assertEqual(job["status"], "completed")
        self.assertIn("Projecting", [entry["phase"] for entry in job["history"]])
        self.assertEqual(projection["projection_state"], "projected")
        self.assertEqual(projection["mailbox"]["name"], "Civic Outlook Mailbox")
        self.assertEqual(len(projection["folders"]), 2)
        self.assertEqual(len(projection["messages"]), 2)
        self.assertTrue(projection_path(item["intake_id"], root=self.root).exists())
        metadata = load_pending_document(item["intake_id"], root=self.root)["outlook_archive_metadata"]
        self.assertTrue(metadata["folder_projection_performed"])
        self.assertTrue(metadata["message_projection_performed"])
        self.assertEqual(metadata["projected_folder_count"], 2)
        self.assertEqual(metadata["projected_message_count"], 2)

    def test_nested_folder_message_metadata_and_provenance_are_preserved(self):
        item, job, projection = self._project()

        folder = get_projection_folder(item["intake_id"], "folder-case", root=self.root)
        self.assertEqual(folder["parent_id"], "folder-inbox")
        self.assertEqual(folder["folder_path"], "Mailbox/Inbox/Case A")
        self.assertEqual(folder["provenance"]["archive_id"], item["intake_id"])
        self.assertEqual(folder["provenance"]["job_id"], job["job_id"])
        self.assertEqual(folder["provenance"]["parser_version"], "fake-projection-parser-1.0")

        message = get_projection_message(item["intake_id"], "message-001", root=self.root)
        self.assertEqual(message["subject"], "Case A intake correspondence")
        self.assertEqual(message["sender"], "alice@example.test")
        self.assertEqual(message["recipients"], ["oversight@example.test"])
        self.assertEqual(message["attachment_count"], 1)
        self.assertNotIn("body", message)
        self.assertNotIn("attachments", message)
        self.assertEqual(message["provenance"]["source_identifier"], "entry-message-001")
        self.assertEqual(projection["warnings"], ["metadata-only projection warning"])

    def test_projection_statistics_and_metadata_search(self):
        item, _job, _projection = self._project()

        stats = projection_statistics(item["intake_id"], root=self.root)
        self.assertEqual(stats["folder_count"], 2)
        self.assertEqual(stats["message_count"], 2)
        self.assertEqual(stats["subfolder_count"], 1)
        self.assertEqual(stats["attachment_count"], 1)

        subject_results = search_projection_metadata(item["intake_id"], "intake correspondence", root=self.root)
        self.assertEqual(subject_results[0]["type"], "message")
        sender_results = search_projection_metadata(item["intake_id"], "bob@example.test", root=self.root)
        self.assertEqual(sender_results[0]["item"]["projection_id"], "message-002")
        folder_results = search_projection_metadata(item["intake_id"], "Mailbox/Inbox/Case A", root=self.root)
        self.assertTrue(any(result["type"] == "folder" for result in folder_results))

    def test_projection_rebuild_replaces_sidecar_without_touching_archive(self):
        item, _job, projection = self._project()
        first_timestamp = projection["projection_timestamp"]

        second_job = create_archive_inspection_job(item["intake_id"], actor="archive-admin", root=self.root)
        run_archive_inspection_job(second_job["job_id"], root=self.root)
        rebuilt = load_outlook_archive_projection(item["intake_id"], root=self.root)

        self.assertIn(rebuilt["projection_state"], {"projected", "rebuilt"})
        self.assertEqual(rebuilt.get("previous_projection_timestamp"), first_timestamp)
        archived_file = Path(load_pending_document(item["intake_id"], root=self.root)["proposed_storage_location"])
        self.assertEqual(archived_file.read_bytes(), PST_BYTES)

    def test_admin_browser_and_projection_apis_are_admin_only_metadata(self):
        item, _job, _projection = self._project()
        request = self._request()

        page = admin_session.admin_outlook_archive_projection_page(item["intake_id"], request).content
        self.assertIn("Outlook Archive Projection", page)
        self.assertIn("Case A intake correspondence", page)
        self.assertIn("No message body", admin_session.admin_outlook_archive_message_projection_page(item["intake_id"], "message-001", request).content)
        self.assertIn("Mailbox/Inbox/Case A", admin_session.admin_outlook_archive_folder_projection_page(item["intake_id"], "folder-case", request).content)

        projection_payload = admin_session.admin_outlook_archive_projection_api(item["intake_id"], request)
        self.assertEqual(projection_payload["statistics"]["message_count"], 2)
        self.assertEqual(len(admin_session.admin_outlook_archive_folders_api(item["intake_id"], request)["folders"]), 2)
        self.assertEqual(
            admin_session.admin_outlook_archive_folder_api(item["intake_id"], "folder-inbox", request)["name"],
            "Inbox",
        )
        self.assertEqual(len(admin_session.admin_outlook_archive_messages_api(item["intake_id"], request)["messages"]), 2)
        self.assertEqual(
            admin_session.admin_outlook_archive_message_api(item["intake_id"], "message-002", request)["importance"],
            "high",
        )
        self.assertEqual(admin_session.admin_outlook_archive_statistics_api(item["intake_id"], request)["message_count"], 2)
        self.assertTrue(admin_session.admin_outlook_archive_projection_search_api(item["intake_id"], request, q="Case A")["results"])

    def test_public_archive_endpoints_do_not_expose_projected_mailbox_details(self):
        item, _job, _projection = self._project()
        for status in ("under_review", "approved", "published"):
            item = admin_session.update_intake_status(
                item["intake_id"],
                status,
                actor="archive-admin",
                note=f"{status} note",
                root=self.root,
            )

        payload = archive.public_outlook_archive_metadata(item["intake_id"])
        self.assertEqual(payload["projection_state"], "projected")
        self.assertTrue(payload["folder_projection_performed"])
        self.assertTrue(payload["message_projection_performed"])
        self.assertNotIn("folders", payload)
        self.assertNotIn("messages", payload)
        self.assertNotIn("Case A intake correspondence", str(payload))

        public_page = documents.public_document_page(item["intake_id"]).content
        self.assertIn("Administrative only in CDE Platform Stage 39C", public_page)
        self.assertNotIn("alice@example.test", public_page)
        self.assertNotIn("Case A intake correspondence", public_page)


if __name__ == "__main__":
    unittest.main()
