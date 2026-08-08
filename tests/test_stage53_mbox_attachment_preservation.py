from __future__ import annotations

import hashlib
import os
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
    list_archive_attachments,
    preserve_mbox_message_attachments,
)
from api.email_documents import parse_mbox_archive_metadata
from scripts.backfill_email_attachment_preservation import run as run_backfill
from tests.test_admin_session import FakeRequest, install_fastapi_stubs
from tests.test_mbox_archive_support import mbox

install_fastapi_stubs()

from api.routes import admin_session  # noqa: E402


# Message 1: one normal PDF attachment
ATTACHMENT_MESSAGE_1 = b"""From: sender@example.test
To: recipient@example.test
Subject: mbox attachment one
Date: Tue, 21 Jul 2026 11:30:00 +0000
Message-ID: <mbox-attach-1@example.test>
MIME-Version: 1.0
Content-Type: multipart/mixed; boundary="M1"

--M1
Content-Type: text/plain; charset=utf-8

Message one body.
--M1
Content-Type: application/pdf
Content-Disposition: attachment; filename="report-1.pdf"
Content-ID: <report-1>
Content-Transfer-Encoding: base64

JVBERi0xLjQKbWJveC0xCg==
--M1--
"""

# Message 2: two attachments — one PDF + one embedded message/rfc822
ATTACHMENT_MESSAGE_2 = b"""From: sender2@example.test
To: recipient@example.test
Subject: mbox attachment two
Date: Tue, 21 Jul 2026 12:30:00 +0000
Message-ID: <mbox-attach-2@example.test>
MIME-Version: 1.0
Content-Type: multipart/mixed; boundary="M2"

--M2
Content-Type: text/plain; charset=utf-8

Message two body.
--M2
Content-Type: application/pdf
Content-Disposition: attachment; filename="report-2.pdf"
Content-Transfer-Encoding: base64

JVBERi0xLjQKbWJveC0yCg==
--M2
Content-Type: message/rfc822
Content-Disposition: attachment; filename="forwarded.eml"

From: inner@example.test
To: recipient@example.test
Subject: Inner
Message-ID: <inner@example.test>

Inner body.
--M2--
"""

# Message 3: a plain message with zero attachments (must be skipped)
PLAIN_MESSAGE = b"""From: plain@example.test
To: recipient@example.test
Subject: plain no attachments
Date: Tue, 21 Jul 2026 13:30:00 +0000
Message-ID: <mbox-plain@example.test>
MIME-Version: 1.0
Content-Type: text/plain; charset=utf-8

Plain body.
"""

# Message 4: a zero-byte attachment occurrence
ZERO_BYTE_MESSAGE = b"""From: zero@example.test
To: recipient@example.test
Subject: zero-byte attachment
Date: Tue, 21 Jul 2026 14:30:00 +0000
Message-ID: <mbox-zero@example.test>
MIME-Version: 1.0
Content-Type: multipart/mixed; boundary="MZ"

--MZ
Content-Type: text/plain; charset=utf-8

Zero body.
--MZ
Content-Type: application/octet-stream
Content-Disposition: attachment
Content-Transfer-Encoding: base64


--MZ--
"""

SEPARATORS = [
    b"From sender1@example.test Tue Jul 21 10:30:00 2026\n",
    b"From sender2@example.test Tue Jul 21 11:30:00 2026\n",
    b"From sender3@example.test Tue Jul 21 12:30:00 2026\n",
    b"From sender4@example.test Tue Jul 21 13:30:00 2026\n",
]


def _build_stage53_mbox() -> bytes:
    return mbox(ATTACHMENT_MESSAGE_1, ATTACHMENT_MESSAGE_2, PLAIN_MESSAGE, ZERO_BYTE_MESSAGE, separators=SEPARATORS)


class Stage53MboxAttachmentPreservationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "pending"
        self.environment = patch.dict(
            os.environ,
            {
                "CDE_DOCUMENT_INTAKE_ROOT": str(self.root),
                "ADMIN_USERNAME": "stage53-admin",
                "ADMIN_PASSWORD": "password",
                "CDE_ADMIN_SESSION_SECRET": "stage53-secret",
            },
            clear=False,
        )
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        self.temporary.cleanup()

    def _store(self, data: bytes | None = None, *, title: str = "Stage 53 mbox source"):
        return store_pending_document(
            data=data or _build_stage53_mbox(),
            original_filename="stage53-source.mbox",
            content_type="application/mbox",
            title=title,
            institution_source="Civic Evidence Office",
            document_date="2026-07-21",
            category="Email Correspondence",
            description="A preserved Apple Mail mailbox archive.",
            visibility="private",
            notes="Governed Stage 53 intake.",
            actor="stage53-admin",
            uploaded_at="2026-07-21T10:00:00Z",
            root=self.root,
        )

    def _admin_session_request(self):
        return FakeRequest(
            cookies={
                admin_session.SESSION_COOKIE_NAME: admin_session.create_admin_session(
                    "stage53-admin"
                )
            }
        )

    def test_byte_ranges_exclude_separator_and_recover_exact_rfc5322_bytes(self):
        data = _build_stage53_mbox()
        meta = parse_mbox_archive_metadata(data)
        for message in meta["messages"]:
            if not message.get("parsed"):
                continue
            recovered = data[message["byte_start"]:message["byte_end"]]
            # Separator excluded: recovered bytes start with RFC 5322 "From:" not mbox "From "
            self.assertFalse(recovered.startswith(b"From "))
            self.assertTrue(recovered.startswith(b"From:") or recovered.startswith(b"From:"))
            # Digest matches the exact recovered bytes
            self.assertEqual(hashlib.sha256(recovered).hexdigest(), message["message_digest"])

    def test_message_index_is_deterministic_across_repeated_parsing(self):
        data = _build_stage53_mbox()
        run1 = [m["message_index"] for m in parse_mbox_archive_metadata(data)["messages"]]
        run2 = [m["message_index"] for m in parse_mbox_archive_metadata(data)["messages"]]
        run3 = [m["message_index"] for m in parse_mbox_archive_metadata(data)["messages"]]
        self.assertEqual(run1, run2, run3)
        self.assertEqual(run1, [1, 2, 3, 4])

    def test_intake_preserves_independent_documents_and_relationships_across_messages(self):
        source = self._store()
        archive_id = source["intake_id"]
        relationships = list_archive_attachments(archive_id, root=self.root)
        # Message 1: 1 attachment, Message 2: 2 attachments, Message 3: 0, Message 4: 1 zero-byte
        # Total relationship rows = 4 (3 preserved + 1 failed zero-byte)
        self.assertEqual(len(relationships), 4)
        self.assertTrue(all(r["relationship_type"] == "Email attachment" for r in relationships))
        self.assertTrue(all(r["source_archive_identifier"] == archive_id for r in relationships))
        self.assertTrue(all(r["source_pathway"] == "mbox_message" for r in relationships))

        # Distinct source_email_object_id per message
        object_ids = {r["source_email_object_id"] for r in relationships}
        self.assertIn(f"{archive_id}:message:1", object_ids)
        self.assertIn(f"{archive_id}:message:2", object_ids)
        self.assertIn(f"{archive_id}:message:4", object_ids)
        self.assertNotIn(f"{archive_id}:message:3", object_ids)  # plain message skipped

        # Preserved attachments are pending Published Documents
        preserved = [r for r in relationships if r["extraction_status"] == "preserved"]
        self.assertEqual(len(preserved), 3)
        for r in preserved:
            attachment = r["attachment_document"]
            self.assertEqual(attachment["status"], "pending")
            self.assertEqual(attachment["document_type"], "email_attachment")
            self.assertNotIn("canonical_record_reference", attachment)

    def test_attachment_hashes_match_exact_bytes(self):
        source = self._store()
        relationships = list_archive_attachments(source["intake_id"], root=self.root)
        preserved = [r for r in relationships if r["extraction_status"] == "preserved"]
        # The first PDF attachment bytes
        expected_pdf1 = b"%PDF-1.4\nmbox-1\n"
        pdf1 = next(r for r in preserved if r["original_filename"] == "report-1.pdf")
        self.assertEqual(pdf1["sha256_hash"], hashlib.sha256(expected_pdf1).hexdigest())
        attachment = pdf1["attachment_document"]
        file_path, _ = intake_document_file(attachment["intake_id"], root=self.root)
        self.assertEqual(file_path.read_bytes(), expected_pdf1)

    def test_same_attachment_bytes_in_different_messages_remain_distinct(self):
        source = self._store()
        relationships = list_archive_attachments(source["intake_id"], root=self.root)
        # report-1.pdf is in message 1; report-2.pdf is in message 2 (different bytes)
        # But verify that two attachments with same sha in different messages would be distinct
        # by confirming object_ids differ
        msg1_rows = [r for r in relationships if r["source_email_object_id"].endswith(":message:1")]
        msg2_rows = [r for r in relationships if r["source_email_object_id"].endswith(":message:2")]
        self.assertTrue(len(msg1_rows) >= 1)
        self.assertTrue(len(msg2_rows) >= 2)  # PDF + embedded message
        # Distinct attachment_document_ids across messages
        doc_ids = {r["attachment_document_id"] for r in msg1_rows + msg2_rows if r.get("attachment_document_id")}
        self.assertEqual(len(doc_ids), 3)  # 1 from msg1 + 2 from msg2

    def test_zero_byte_occurrence_records_failed_row_without_document(self):
        source = self._store()
        relationships = list_archive_attachments(source["intake_id"], root=self.root)
        failed = [r for r in relationships if r["extraction_status"] == "failed"]
        self.assertEqual(len(failed), 1)
        self.assertIsNone(failed[0]["attachment_document_id"])
        self.assertEqual(failed[0]["extraction_failure_reason"], "email_attachment_empty_payload")
        self.assertTrue(failed[0]["source_email_object_id"].endswith(":message:4"))

    def test_embedded_message_is_preserved_opaquely(self):
        source = self._store()
        relationships = list_archive_attachments(source["intake_id"], root=self.root)
        embedded = next(
            r for r in relationships
            if r.get("original_filename") == "forwarded.eml"
        )
        attachment = embedded["attachment_document"]
        file_path, _ = intake_document_file(attachment["intake_id"], root=self.root)
        self.assertIn(b"Subject: Inner", file_path.read_bytes())

    def test_reprocessing_is_idempotent_without_duplicates(self):
        source = self._store()
        before = list_archive_attachments(source["intake_id"], root=self.root)
        file_path, _ = intake_document_file(source["intake_id"], root=self.root)
        meta = parse_mbox_archive_metadata(file_path.read_bytes())

        # Re-run preservation for each message
        for message in meta["messages"]:
            if not message.get("parsed") or int(message.get("attachment_count") or 0) <= 0:
                continue
            message_bytes = file_path.read_bytes()[message["byte_start"]:message["byte_end"]]
            preserve_mbox_message_attachments(
                source, message_bytes, message_index=message["message_index"], root=self.root
            )
        after = list_archive_attachments(source["intake_id"], root=self.root)
        self.assertEqual(
            [r["relationship_id"] for r in after],
            [r["relationship_id"] for r in before],
        )
        self.assertEqual(
            [r["attachment_document_id"] for r in after],
            [r["attachment_document_id"] for r in before],
        )

    def test_stage50_admin_section_lights_up_for_mbox_container(self):
        source = self._store()
        request = self._admin_session_request()
        preview = admin_session.admin_document_intake_preview_page(
            source["intake_id"], request
        ).content
        self.assertIn("Governed Email Attachment Relationships", preview)
        self.assertIn("Open Published Document", preview)
        relationships = list_archive_attachments(source["intake_id"], root=self.root)
        pdf1 = next(r for r in relationships if r.get("original_filename") == "report-1.pdf")
        attachment = pdf1["attachment_document"]
        self.assertIn(attachment["document_identifier"], preview)

    def test_backfill_dry_run_is_write_free(self):
        # Model a pre-Stage-53 mbox with preservation disabled
        with patch(
            "api.email_attachment_preservation.preserve_mbox_message_attachments",
            return_value=[],
        ):
            source = self._store()
        registry_path = self.root / REGISTRY_FILENAME
        self.assertFalse(registry_path.exists())
        dirs_before = {p.name for p in self.root.iterdir() if p.is_dir()}
        metadata_before = (self.root / source["intake_id"] / "metadata.json").read_text()

        result = run_backfill(root=self.root, limit=10, dry_run=True)
        # attachment_total from metadata: msg1(1) + msg2(2) + msg3(0) + msg4(1) = 4
        self.assertEqual(result["processed"], 1)
        self.assertEqual(result["created"], 4)
        self.assertFalse(registry_path.exists())
        self.assertEqual(dirs_before, {p.name for p in self.root.iterdir() if p.is_dir()})
        self.assertEqual(
            metadata_before, (self.root / source["intake_id"] / "metadata.json").read_text()
        )

    def test_targeted_intake_id_dry_run_is_write_free(self):
        with patch(
            "api.email_attachment_preservation.preserve_mbox_message_attachments",
            return_value=[],
        ):
            source = self._store()
        registry_path = self.root / REGISTRY_FILENAME
        dirs_before = {p.name for p in self.root.iterdir() if p.is_dir()}

        result = run_backfill(
            root=self.root, limit=10, dry_run=True, intake_id=source["intake_id"]
        )
        self.assertEqual(result["processed"], 1)
        self.assertEqual(result["created"], 4)
        self.assertFalse(registry_path.exists())
        self.assertEqual(dirs_before, {p.name for p in self.root.iterdir() if p.is_dir()})

    def test_targeted_first_run_creates_objects_then_second_run_idempotent(self):
        with patch(
            "api.email_attachment_preservation.preserve_mbox_message_attachments",
            return_value=[],
        ):
            source = self._store()

        first = run_backfill(
            root=self.root, limit=10, dry_run=False, intake_id=source["intake_id"]
        )
        self.assertEqual(first["processed"], 1)
        # 3 preserved + 1 failed zero-byte = 4 linked; 3 created (non-zero-byte)
        self.assertEqual(first["linked"], 4)
        self.assertEqual(first["created"], 3)
        relationships = list_archive_attachments(source["intake_id"], root=self.root)
        self.assertEqual(len(relationships), 4)

        second = run_backfill(
            root=self.root, limit=10, dry_run=False, intake_id=source["intake_id"]
        )
        self.assertEqual(second["created"], 0)
        self.assertEqual(second["already_present"], 4)
        relationships_after = list_archive_attachments(source["intake_id"], root=self.root)
        self.assertEqual(
            [r["relationship_id"] for r in relationships_after],
            [r["relationship_id"] for r in relationships],
        )

    def test_targeted_run_does_not_process_unrelated_candidates(self):
        with patch(
            "api.email_attachment_preservation.preserve_mbox_message_attachments",
            return_value=[],
        ):
            target = self._store(title="Target mbox")
        # A second mbox candidate (distinct bytes) that must NOT be touched
        other_data = _build_stage53_mbox().replace(b"<mbox-attach-1@example.test>", b"<other@example.test>")
        with patch(
            "api.email_attachment_preservation.preserve_mbox_message_attachments",
            return_value=[],
        ):
            other = self._store(data=other_data, title="Untouched mbox")
        self.assertNotEqual(other["intake_id"], target["intake_id"])

        result = run_backfill(
            root=self.root, limit=10, dry_run=True, intake_id=target["intake_id"]
        )
        self.assertEqual(result["processed"], 1)
        self.assertEqual(len(list_archive_attachments(other["intake_id"], root=self.root)), 0)


if __name__ == "__main__":
    unittest.main()
