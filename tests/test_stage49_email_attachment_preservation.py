from __future__ import annotations

import hashlib
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from api.document_intake import (
    intake_document_file,
    load_pending_document,
    store_pending_document,
    update_intake_status,
)
from api.email_attachment_preservation import (
    REGISTRY_FILENAME,
    list_attachment_sources,
    list_source_attachments,
    preserve_rfc5322_attachments,
)
from api.email_documents import extract_email_attachment_payloads
from api.attachment_governance import govern_attachment_bytes
from api.outlook_archive_promotion import OutlookArchivePromotionContext
from scripts.backfill_email_attachment_preservation import run as run_backfill
from tests.test_admin_session import FakeRequest, install_fastapi_stubs


install_fastapi_stubs()

from api.routes import admin_session, documents


MULTI_ATTACHMENT_EML = b"""From: Sender <sender@example.test>
To: Recipient <recipient@example.test>
Subject: Independent attachments
Date: Wed, 5 Aug 2026 10:00:00 +0000
Message-ID: <stage49@example.test>
MIME-Version: 1.0
Content-Type: multipart/mixed; boundary="MIX"

--MIX
Content-Type: text/plain; charset=utf-8

The body is not an attachment.
--MIX
Content-Type: application/pdf
Content-Disposition: attachment; filename="report.pdf"
Content-ID: <report>
Content-Transfer-Encoding: base64

JVBERi0xLjQKc3RhZ2U0OQo=
--MIX
Content-Type: image/png
Content-Disposition: inline; filename="report.pdf"
Content-ID: <inline-image>
Content-Transfer-Encoding: base64

iVBORw0KGgo=
--MIX
Content-Type: application/octet-stream
Content-Disposition: attachment
Content-Transfer-Encoding: base64


--MIX--
"""

EMBEDDED_MESSAGE_EML = b"""From: Sender <sender@example.test>
To: Recipient <recipient@example.test>
Subject: Embedded message
Message-ID: <outer@example.test>
MIME-Version: 1.0
Content-Type: multipart/mixed; boundary="OUTER"

--OUTER
Content-Type: text/plain

See attached message.
--OUTER
Content-Type: message/rfc822
Content-Disposition: attachment; filename="forwarded.eml"

From: Inner <inner@example.test>
To: Recipient <recipient@example.test>
Subject: Inner message
Message-ID: <inner@example.test>

Inner body.
--OUTER--
"""


class Stage49EmailAttachmentPreservationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "pending"
        self.environment = patch.dict(
            os.environ,
            {
                "CDE_DOCUMENT_INTAKE_ROOT": str(self.root),
                "ADMIN_USERNAME": "stage49-admin",
                "ADMIN_PASSWORD": "password",
                "CDE_ADMIN_SESSION_SECRET": "stage49-secret",
            },
            clear=False,
        )
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        self.temporary.cleanup()

    def _store(self, data: bytes = MULTI_ATTACHMENT_EML, *, title: str = "Source email"):
        return store_pending_document(
            data=data,
            original_filename="source.eml",
            content_type="message/rfc822",
            title=title,
            institution_source="Civic Evidence Office",
            document_date="2026-08-05",
            category="Email Correspondence",
            description="A preserved source email.",
            visibility="private",
            notes="Governed intake.",
            actor="stage49-admin",
            uploaded_at="2026-08-05T10:15:00Z",
            root=self.root,
        )

    def _publish(self, item: dict):
        for status, timestamp in (
            ("under_review", "2026-08-05T11:00:00Z"),
            ("approved", "2026-08-05T12:00:00Z"),
            ("published", "2026-08-05T13:00:00Z"),
        ):
            item = update_intake_status(
                item["intake_id"],
                status,
                actor="stage49-admin",
                changed_at=timestamp,
                root=self.root,
            )
        return item

    def test_mime_extraction_preserves_order_inline_state_filenames_and_exact_bytes(self):
        payloads = extract_email_attachment_payloads(MULTI_ATTACHMENT_EML)
        self.assertEqual([item["attachment_index"] for item in payloads], [1, 2, 3])
        self.assertEqual(payloads[0]["payload"], b"%PDF-1.4\nstage49\n")
        self.assertEqual(payloads[0]["original_filename"], "report.pdf")
        self.assertFalse(payloads[0]["inline_status"])
        self.assertEqual(payloads[1]["original_filename"], "report.pdf")
        self.assertTrue(payloads[1]["inline_status"])
        self.assertIsNone(payloads[2]["original_filename"])
        self.assertEqual(payloads[2]["display_title"], "Attachment 3")
        self.assertEqual(payloads[2]["payload"], b"")

        embedded = extract_email_attachment_payloads(EMBEDDED_MESSAGE_EML)
        self.assertEqual(len(embedded), 1)
        self.assertTrue(embedded[0]["is_attached_message"])
        self.assertEqual(embedded[0]["mime_type"], "message/rfc822")
        self.assertIn(b"Subject: Inner message", embedded[0]["payload"])

    def test_intake_creates_independent_pending_documents_relationships_and_hashes(self):
        source = self._store()
        relationships = list_source_attachments(source["intake_id"], root=self.root)
        self.assertEqual(len(relationships), 3)
        self.assertEqual(
            [item["relationship_type"] for item in relationships],
            ["Email attachment"] * 3,
        )
        self.assertEqual([item["attachment_index"] for item in relationships], [1, 2, 3])
        self.assertEqual(len({item["attachment_document_id"] for item in relationships}), 3)

        first = relationships[0]
        attachment = first["attachment_document"]
        self.assertEqual(attachment["status"], "pending")
        self.assertEqual(attachment["document_type"], "email_attachment")
        self.assertEqual(attachment["category"], "Email Attachment")
        self.assertNotIn("canonical_record_reference", attachment)
        file_path, _ = intake_document_file(attachment["intake_id"], root=self.root)
        expected = b"%PDF-1.4\nstage49\n"
        self.assertEqual(file_path.read_bytes(), expected)
        self.assertEqual(attachment["sha256_hash"], hashlib.sha256(expected).hexdigest())
        self.assertEqual(attachment["sha512_hash"], hashlib.sha512(expected).hexdigest())
        provenance = attachment["attachment_preservation_metadata"]
        self.assertEqual(provenance["parent_email_preservation_identifier"], source["intake_id"])
        self.assertEqual(provenance["source_message_identifier"], "<stage49@example.test>")
        self.assertEqual(provenance["content_id"], "<report>")

        conn = sqlite3.connect(self.root / REGISTRY_FILENAME)
        try:
            indexes = {
                row[1]
                for row in conn.execute("PRAGMA index_list(email_attachment_relationships)")
            }
        finally:
            conn.close()
        self.assertTrue(
            {
                "idx_email_attachment_relationship_source",
                "idx_email_attachment_relationship_attachment",
                "idx_email_attachment_relationship_archive",
                "idx_email_attachment_relationship_type",
            }.issubset(indexes)
        )

    def test_display_filename_is_path_safe_while_source_value_remains_governed_metadata(self):
        unsafe = MULTI_ATTACHMENT_EML.replace(
            b'filename="report.pdf"', b'filename="../../report.pdf"', 1
        )
        source = self._store(unsafe)
        relationship = list_source_attachments(source["intake_id"], root=self.root)[0]
        self.assertEqual(relationship["display_title"], "report.pdf")
        self.assertEqual(relationship["original_filename"], "report.pdf")
        self.assertEqual(
            relationship["source_metadata"]["source_reported_original_filename"],
            "../../report.pdf",
        )

    def test_reprocessing_is_idempotent_but_same_bytes_in_another_email_are_distinct(self):
        first_source = self._store()
        first_path, _ = intake_document_file(first_source["intake_id"], root=self.root)
        first_retry = preserve_rfc5322_attachments(
            first_source, first_path.read_bytes(), root=self.root
        )
        first_relationships = list_source_attachments(first_source["intake_id"], root=self.root)
        self.assertEqual(
            [item["relationship_id"] for item in first_retry],
            [item["relationship_id"] for item in first_relationships],
        )

        second_data = MULTI_ATTACHMENT_EML.replace(
            b"<stage49@example.test>", b"<stage49-second@example.test>"
        )
        second_source = self._store(second_data, title="Second source email")
        second_relationships = list_source_attachments(second_source["intake_id"], root=self.root)
        self.assertNotEqual(
            first_relationships[0]["attachment_document_id"],
            second_relationships[0]["attachment_document_id"],
        )
        self.assertEqual(first_relationships[0]["sha256_hash"], second_relationships[0]["sha256_hash"])

    def test_failed_preservation_remains_visible_without_false_document_link(self):
        with patch(
            "api.email_attachment_preservation.store_email_attachment_document",
            side_effect=ValueError("governed storage unavailable"),
        ):
            source = self._store()
        relationships = list_source_attachments(source["intake_id"], root=self.root)
        self.assertEqual(len(relationships), 3)
        self.assertTrue(all(item["extraction_status"] == "failed" for item in relationships))
        self.assertTrue(all(item["attachment_document_id"] is None for item in relationships))
        self.assertTrue(all("storage unavailable" in item["extraction_failure_reason"] for item in relationships))

    def test_public_source_and_inverse_pages_respect_independent_lifecycle(self):
        source = self._publish(self._store())
        relationships = list_source_attachments(source["intake_id"], root=self.root)
        pending_page = documents.public_document_page(source["intake_id"]).content
        self.assertIn("Independently preserved attachments (3)", pending_page)
        self.assertIn("has not completed the Published Document lifecycle", pending_page)
        self.assertNotIn(
            f'/documents/{relationships[0]["attachment_document_id"]}', pending_page
        )

        attachment = self._publish(relationships[0]["attachment_document"])
        source_page = documents.public_document_page(source["intake_id"]).content
        self.assertIn("Email attachment", source_page)
        self.assertIn("Open Published Document", source_page)
        self.assertIn(f'/documents/{attachment["intake_id"]}', source_page)

        attachment_page = documents.public_document_page(attachment["intake_id"]).content
        self.assertIn("Attached to email", attachment_page)
        self.assertIn(source["document_identifier"], attachment_page)
        self.assertIn("Open source email", attachment_page)
        relationship_page = documents.public_email_attachment_relationship_page(
            relationships[0]["relationship_id"]
        ).content
        self.assertIn(source["document_identifier"], relationship_page)
        self.assertIn(attachment["document_identifier"], relationship_page)

    def test_administrative_metadata_endpoints_are_protected_and_return_no_bytes(self):
        source = self._store()
        unauthenticated = FakeRequest(cookies={})
        with self.assertRaises(Exception):
            admin_session.admin_email_attachment_relationships_api(
                source["intake_id"], unauthenticated
            )
        request = FakeRequest(
            cookies={
                admin_session.SESSION_COOKIE_NAME: admin_session.create_admin_session(
                    "stage49-admin"
                )
            }
        )
        payload = admin_session.admin_email_attachment_relationships_api(
            source["intake_id"], request
        )
        self.assertEqual(payload["relationship_type"], "Email attachment")
        self.assertEqual(len(payload["relationships"]), 3)
        self.assertNotIn("%PDF", str(payload))
        preview = admin_session.admin_document_intake_preview_page(
            source["intake_id"], request
        ).content
        self.assertIn("Governed Email Attachment Relationships", preview)

    def _admin_session_request(self):
        return FakeRequest(
            cookies={
                admin_session.SESSION_COOKIE_NAME: admin_session.create_admin_session(
                    "stage49-admin"
                )
            }
        )

    def test_admin_attachment_table_shows_stage50_navigation_fields(self):
        source = self._store()
        request = self._admin_session_request()
        relationships = list_source_attachments(source["intake_id"], root=self.root)
        first = relationships[0]
        attachment = first["attachment_document"]

        preview = admin_session.admin_document_intake_preview_page(
            source["intake_id"], request
        ).content

        # Stage 50 navigable evidence fields.
        self.assertIn("<th>Original filename</th>", preview)
        self.assertIn("<th>Relationship</th>", preview)
        self.assertIn("<th>Published Document</th>", preview)
        self.assertIn("<th>Lifecycle status</th>", preview)
        self.assertIn("<th>Action</th>", preview)
        self.assertIn("Email attachment", preview)
        self.assertIn(first["original_filename"], preview)
        self.assertIn(attachment["document_identifier"], preview)
        self.assertIn(
            f"/admin/document-intake/{attachment['intake_id']}", preview
        )
        self.assertIn("Open Published Document", preview)
        # Current lifecycle status is sourced from STATUS_LABELS.
        self.assertIn("Pending Intake", preview)

    def test_admin_attachment_table_failed_rows_show_not_created_without_doc_link(self):
        with patch(
            "api.email_attachment_preservation.store_email_attachment_document",
            side_effect=ValueError("governed storage unavailable"),
        ):
            source = self._store()
        request = self._admin_session_request()
        preview = admin_session.admin_document_intake_preview_page(
            source["intake_id"], request
        ).content

        # Failed rows must not advertise a Published Document.
        self.assertIn("Not created", preview)
        self.assertIn("No attachment Published Document", preview)
        # No administrative document action is rendered for failed rows. The
        # admin chrome contains other ``/admin/document-intake`` navigation
        # links, so the assertion targets the Stage 50 action label itself.
        self.assertNotIn("Open Published Document", preview)
        # Technical preservation metadata remains visible.
        self.assertIn("failed", preview)
        self.assertIn("<th>Relationship ID</th>", preview)
        self.assertIn("<th>Index</th>", preview)
        self.assertIn("<th>Extraction status</th>", preview)
        self.assertIn("<th>Attachment document ID</th>", preview)

    def test_admin_attachment_table_preserves_technical_metadata_columns(self):
        source = self._store()
        request = self._admin_session_request()
        relationships = list_source_attachments(source["intake_id"], root=self.root)
        first = relationships[0]
        attachment = first["attachment_document"]

        preview = admin_session.admin_document_intake_preview_page(
            source["intake_id"], request
        ).content

        # Technical preservation metadata columns are retained as secondary
        # columns even after the Stage 50 navigable fields are added.
        self.assertIn(first["relationship_id"], preview)
        self.assertIn(str(first["attachment_index"]), preview)
        self.assertIn(first["extraction_status"], preview)
        self.assertIn(attachment["intake_id"], preview)
        # The existing relationship metadata inspector action is retained.
        self.assertIn(
            f"/api/admin/session/email-attachment-relationships/{first['relationship_id']}",
            preview,
        )
        self.assertIn("Inspect metadata", preview)

    def test_archive_attachment_bytes_create_projected_message_relationship(self):
        source = {
            "intake_id": "a" * 64,
            "document_identifier": "DOC-2026-000099",
            "title": "IMAP acquisition",
            "institution_source": "Civic Evidence Office",
            "document_date": "2026-08-05",
            "visibility": "private",
            "upload_date": "2026-08-05T09:00:00Z",
        }
        context = OutlookArchivePromotionContext(
            document=source,
            projection={"projection_version": "v1"},
            folder={"folder_id": "folder-1", "path": "Inbox"},
            message={
                "projection_id": "message-1",
                "message_id": "<archive-message@example.test>",
                "folder_id": "folder-1",
                "folder_path": "Inbox",
                "thread_id": "thread-1",
                "provenance": {"parser_version": "imap-v1"},
            },
            job={"job_id": "job-1"},
        )
        governed = govern_attachment_bytes(
            context,
            data=b"archive attachment",
            filename="archive.txt",
            mime_type="text/plain",
            source_attachment_id="part-2",
            attachment_index=2,
            acquisition_source="imap_acquisition",
            extracted_at="2026-08-05T10:00:00Z",
            root=self.root,
        )
        occurrence = governed["provenance"]
        self.assertEqual(occurrence["published_document_preservation_status"], "preserved")
        attachment_document = load_pending_document(
            occurrence["attachment_document_id"], root=self.root
        )
        self.assertEqual(attachment_document["status"], "pending")
        projected = list_source_attachments(
            f'{source["intake_id"]}:message:message-1', root=self.root
        )
        self.assertEqual(projected[0]["attachment_index"], 2)
        self.assertEqual(projected[0]["source_email_kind"], "projected_message")

    def test_backfill_is_bounded_dry_run_and_idempotent(self):
        source = self._store()
        # Simulate a pre-Stage 49 EML while retaining authoritative parser metadata.
        registry = self.root / REGISTRY_FILENAME
        registry.unlink()
        for relationship in list(self.root.iterdir()):
            if relationship.is_dir() and relationship.name != source["intake_id"]:
                for child in relationship.iterdir():
                    child.unlink()
                relationship.rmdir()
        metadata_path = self.root / source["intake_id"] / "metadata.json"
        metadata = load_pending_document(source["intake_id"], root=self.root)
        metadata.pop("email_attachment_preservation", None)
        metadata_path.write_text(__import__("json").dumps(metadata), encoding="utf-8")

        dry_run = run_backfill(root=self.root, limit=1, dry_run=True)
        self.assertEqual(dry_run["processed"], 1)
        self.assertEqual(dry_run["created"], 3)
        self.assertFalse(registry.exists())
        first = run_backfill(root=self.root, limit=1, dry_run=False)
        self.assertEqual(first["created"], 3)
        second = run_backfill(root=self.root, limit=1, dry_run=False)
        self.assertEqual(second["already_present"], 3)
        self.assertEqual(second["created"], 0)
        self.assertEqual(second["linked"], 0)

    def test_inverse_lookup_preserves_one_occurrence_without_record_document_association(self):
        source = self._store()
        relationship = list_source_attachments(source["intake_id"], root=self.root)[0]
        inverse = list_attachment_sources(
            relationship["attachment_document_id"], root=self.root
        )
        self.assertEqual([item["relationship_id"] for item in inverse], [relationship["relationship_id"]])
        self.assertFalse((self.root / ".record_document_associations.sqlite3").exists())


if __name__ == "__main__":
    unittest.main()
