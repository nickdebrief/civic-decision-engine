import hashlib
import inspect
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.test_admin_session import FakeRequest, install_fastapi_stubs

install_fastapi_stubs()

from api.document_intake import store_pending_document
from api.mailbox_relationship_graph import build_outlook_attachment_relationship_graph
from api.outlook_archive_attachments import (
    OutlookAttachmentGovernanceError,
    govern_outlook_attachment_bytes,
    list_outlook_attachments,
    load_outlook_attachment,
    validate_outlook_attachment_promotion,
)
from api.outlook_archive_jobs import create_archive_inspection_job, run_archive_inspection_job
from api.outlook_archive_projections import load_outlook_archive_projection
from api.routes import admin_session, documents, records


PST_BYTES = b"CDE Platform Stage 39E attachment governance archive.\n" * 128
ATTACHMENT_BYTES = b"%PDF-1.7\nGoverned attachment evidence.\n%%EOF\n"


class FakeAttachmentParser:
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
            "mailbox_name": "Attachment Governance Mailbox",
            "folders": [
                {
                    "folder_id": "folder-inbox",
                    "name": "Inbox",
                    "path": "Mailbox/Inbox",
                    "source_identifier": "folder-entry-id",
                    "message_count": 1,
                    "attachment_count": 2,
                }
            ],
            "messages": [
                {
                    "projection_id": "message-001",
                    "message_id": "<attachment-governance@example.test>",
                    "subject": "Attachment governance correspondence",
                    "sender": "sender@example.test",
                    "recipients": ["recipient@example.test"],
                    "cc": ["oversight@example.test"],
                    "sent_timestamp": "2026-08-01T08:30:00Z",
                    "message_class": "IPM.Note",
                    "conversation_id": "conversation-001",
                    "thread_index": "thread-001",
                    "attachment_count": 2,
                    "folder_id": "folder-inbox",
                    "folder_path": "Mailbox/Inbox",
                    "source_identifier": "message-entry-id",
                }
            ],
        }


class OutlookArchiveAttachmentGovernanceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "pending"
        self.db_path = Path(self.temp_dir.name) / "records.db"
        self.env = patch.dict(
            os.environ,
            {
                "ADMIN_USERNAME": "attachment-admin",
                "ADMIN_PASSWORD": "admin-password",
                "CDE_ADMIN_SESSION_SECRET": "session-secret",
                "CDE_DOCUMENT_INTAKE_ROOT": str(self.root),
                "RECORDS_DB_PATH": str(self.db_path),
                "CDE_OUTLOOK_ARCHIVE_JOB_RUN_MODE": "inline",
                "CDE_OUTLOOK_ARCHIVE_PARSER_MODULE": __name__,
                "CDE_OUTLOOK_ARCHIVE_PARSER_CLASS": "FakeAttachmentParser",
                "CDE_OUTLOOK_ARCHIVE_PARSER_VERSION": "fake-attachment-parser-1.0",
            },
            clear=False,
        )
        self.env.start()
        self.original_admin_db = admin_session.DB_PATH
        self.original_records_db = records.DB_PATH
        admin_session.DB_PATH = self.db_path
        records.DB_PATH = self.db_path
        records.init_db()
        session = admin_session.create_admin_session("attachment-admin")
        self.request = FakeRequest(cookies={admin_session.SESSION_COOKIE_NAME: session})
        self.item = store_pending_document(
            data=PST_BYTES,
            original_filename="attachment-governance.pst",
            content_type="application/octet-stream",
            title="Attachment Governance Outlook Archive",
            institution_source="Civic Oversight Institution",
            document_date="2026-08-01",
            category="Outlook Archive",
            description="Preserved archive for attachment governance tests.",
            visibility="private",
            notes="Administrative fixture.",
            reference_identifier="CDE-STAGE39E-ARCHIVE-001",
            keywords="outlook, attachment, governance",
            actor="attachment-admin",
            uploaded_at="2026-08-01T08:00:00Z",
            root=self.root,
        )
        job = create_archive_inspection_job(
            self.item["intake_id"], actor="attachment-admin", root=self.root
        )
        self.job = run_archive_inspection_job(job["job_id"], root=self.root)
        self.assertEqual(self.job["status"], "completed")

    def tearDown(self):
        admin_session.DB_PATH = self.original_admin_db
        records.DB_PATH = self.original_records_db
        self.env.stop()
        self.temp_dir.cleanup()

    def _govern(self, *, source_id="attachment-entry-001", data=ATTACHMENT_BYTES):
        return govern_outlook_attachment_bytes(
            self.item["intake_id"],
            "message-001",
            data=data,
            filename="governed-evidence.pdf",
            mime_type="application/pdf",
            source_attachment_id=source_id,
            extracted_at="2026-08-01T09:00:00Z",
            root=self.root,
        )

    def _record_count(self):
        with sqlite3.connect(self.db_path) as conn:
            return conn.execute("SELECT COUNT(*) FROM records").fetchone()[0]

    def _promote(self, attachment, reference="ADM-COI-20260801-001"):
        return admin_session.admin_outlook_archive_attachment_promotion_create(
            self.item["intake_id"],
            attachment["attachment_id"],
            self.request,
            record_type="administrative_action",
            reference=reference,
            record_title="Governed evidence attachment",
            institution="Civic Oversight Institution",
            event_date="2026-08-01",
            summary="Attachment promoted by explicit administrator decision.",
            trajectory="Submitted",
            system_state="Canonical Record created through governed attachment promotion.",
            conditions="GOVERNED_MAILBOX_ATTACHMENT_PROMOTION",
            signals="EXPLICIT_ADMINISTRATIVE_PROMOTION",
            confirm_promotion="1",
        )

    def test_hashes_bytes_and_assigns_stable_identity_without_record(self):
        first = self._govern()
        second = self._govern()
        self.assertRegex(first["attachment_id"], r"^ATT-[A-F0-9]{24}$")
        self.assertEqual(first["attachment_id"], second["attachment_id"])
        self.assertEqual(first["sha256_hash"], hashlib.sha256(ATTACHMENT_BYTES).hexdigest())
        self.assertEqual(first["file_size_bytes"], len(ATTACHMENT_BYTES))
        self.assertEqual(first["mime_type"], "application/pdf")
        self.assertEqual(first["hash_verification_status"], "verified")
        self.assertEqual(self._record_count(), 0)
        stored = self.root / ".outlook_archive_attachments" / self.item["intake_id"] / first["attachment_id"] / "original.bin"
        self.assertEqual(stored.read_bytes(), ATTACHMENT_BYTES)

    def test_provenance_and_eligibility_are_bound_to_projection(self):
        attachment = self._govern()
        context = validate_outlook_attachment_promotion(
            self.item["intake_id"], attachment["attachment_id"], root=self.root
        )
        provenance = context.attachment["provenance"]
        self.assertEqual(provenance["archive_id"], self.item["intake_id"])
        self.assertEqual(provenance["folder_projection_id"], "folder-inbox")
        self.assertEqual(provenance["message_projection_id"], "message-001")
        self.assertEqual(provenance["source_attachment_identifier"], "attachment-entry-001")
        self.assertEqual(provenance["extraction_job"], self.job["job_id"])
        self.assertEqual(provenance["projection_version"], "stage39c-projection-v1")
        context.source_path.write_bytes(b"tampered")
        with self.assertRaises(OutlookAttachmentGovernanceError) as error:
            validate_outlook_attachment_promotion(
                self.item["intake_id"], attachment["attachment_id"], root=self.root
            )
        self.assertEqual(error.exception.code, "outlook_attachment_hash_verification_failed")

    def test_private_graph_contains_evidence_backed_attachment_relationships(self):
        attachment = self._govern()
        projection = load_outlook_archive_projection(self.item["intake_id"], root=self.root)
        graph = build_outlook_attachment_relationship_graph(
            self.item, projection, [attachment]
        )
        attachment_node = next(node for node in graph["nodes"] if node["type"] == "Attachment")
        self.assertEqual(attachment_node["metadata"]["sha256_hash"], attachment["sha256_hash"])
        self.assertEqual(attachment_node["metadata"]["originating_message"], "message-001")
        relationships = {edge["relationship_type"] for edge in graph["edges"]}
        self.assertTrue({"Has Attachment", "Attached To", "Belongs To Archive"}.issubset(relationships))
        self.assertIn("Related Communication", relationships)
        api_graph = admin_session.admin_outlook_archive_attachment_graph_api(
            self.item["intake_id"], self.request
        )
        self.assertEqual(api_graph, graph)

    def test_inspector_and_promotion_are_administrator_only(self):
        attachment = self._govern()
        page = admin_session.admin_outlook_archive_attachment_page(
            self.item["intake_id"], attachment["attachment_id"], self.request
        ).content
        for expected in (
            "Attachment Inspector",
            attachment["attachment_id"],
            attachment["sha256_hash"],
            "Originating archive",
            "Originating message",
            "Promote Attachment",
            "No attachment download",
        ):
            self.assertIn(expected, page)
        with self.assertRaises(Exception):
            admin_session.admin_outlook_archive_attachment_api(
                self.item["intake_id"], attachment["attachment_id"], FakeRequest()
            )
        public_source = inspect.getsource(documents)
        self.assertNotIn('@router.get("/archive/{document_id}/attachments', public_source)
        self.assertNotIn('@router.get("/api/archive/{document_id}/attachments', public_source)

    def test_explicit_promotion_creates_normal_record_with_complete_provenance(self):
        attachment = self._govern()
        response = self._promote(attachment)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(self._record_count(), 1)
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM records WHERE reference = ?", ("ADM-COI-20260801-001",)
            ).fetchone()
        report = json.loads(row["report_json"])
        provenance = report["attachment_promotion_provenance"]
        self.assertEqual(provenance["archive_id"], self.item["intake_id"])
        self.assertEqual(provenance["folder_projection_id"], "folder-inbox")
        self.assertEqual(provenance["message_projection_id"], "message-001")
        self.assertEqual(provenance["attachment_id"], attachment["attachment_id"])
        self.assertEqual(provenance["sha256_hash"], attachment["sha256_hash"])
        self.assertEqual(provenance["administrator"], "attachment-admin")
        self.assertEqual(
            provenance["provenance_chain"],
            [self.item["intake_id"], "folder-inbox", "message-001", attachment["attachment_id"]],
        )
        updated = load_outlook_attachment(
            self.item["intake_id"], attachment["attachment_id"], root=self.root
        )
        self.assertEqual(updated["promotion_status"], "promoted")
        self.assertEqual(updated["canonical_record_reference"], "ADM-COI-20260801-001")

    def test_duplicate_sha256_blocks_second_canonical_record_and_identifies_existing(self):
        first = self._govern(source_id="attachment-entry-001")
        second = self._govern(source_id="attachment-entry-002")
        self.assertNotEqual(first["attachment_id"], second["attachment_id"])
        self.assertEqual(first["sha256_hash"], second["sha256_hash"])
        self._promote(first)
        with self.assertRaises(Exception) as duplicate:
            self._promote(second, reference="ADM-COI-20260801-002")
        detail = getattr(duplicate.exception, "detail", {})
        self.assertEqual(detail["detail"], "outlook_attachment_duplicate_canonical_record")
        self.assertEqual(detail["existing_canonical_record"], "ADM-COI-20260801-001")
        self.assertEqual(self._record_count(), 1)

    def test_promotion_requires_explicit_confirmation(self):
        attachment = self._govern()
        with self.assertRaises(Exception) as error:
            admin_session.admin_outlook_archive_attachment_promotion_create(
                self.item["intake_id"],
                attachment["attachment_id"],
                self.request,
                record_type="administrative_action",
                reference="ADM-COI-20260801-003",
                record_title="Governed evidence attachment",
                institution="Civic Oversight Institution",
                event_date="2026-08-01",
                summary="No confirmation supplied.",
                trajectory="Submitted",
                system_state="Pending explicit decision.",
                conditions=None,
                signals=None,
                confirm_promotion=None,
            )
        self.assertEqual(
            getattr(error.exception, "detail", None),
            "outlook_attachment_promotion_confirmation_required",
        )
        self.assertEqual(self._record_count(), 0)

    def test_listing_exposes_metadata_only(self):
        attachment = self._govern()
        listed = list_outlook_attachments(self.item["intake_id"], root=self.root)
        self.assertEqual([item["attachment_id"] for item in listed], [attachment["attachment_id"]])
        encoded = json.dumps(listed)
        self.assertNotIn("original.bin", encoded)
        self.assertNotIn(ATTACHMENT_BYTES.decode("ascii"), encoded)


if __name__ == "__main__":
    unittest.main()
