import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from api.document_intake import (
    intake_document_file,
    store_streaming_mbox_pending_document,
    update_intake_status,
)
from api.email_documents import parse_mbox_archive_metadata_from_file
from tests.test_admin_session import FakeRequest, FakeUploadFile, install_fastapi_stubs
from tests.test_mbox_archive_support import mbox, message
from tests.test_streaming_mbox_ingestion import ChunkedReader

install_fastapi_stubs()

from api.routes import admin_session, documents


def _wrapped_text(prefix: str, repeat: int) -> str:
    return "\n".join(f"{prefix} {index:04d} " + ("governed preview text " * 8) for index in range(repeat))


def _large_plain_message(*, subject: str = "Large contained message", repeat: int = 160) -> bytes:
    return message(
        subject=subject,
        message_id=f"<{subject.lower().replace(' ', '-')}-plain@example.test>",
        body=_wrapped_text("Large plain body", repeat),
    )


def _large_html_message() -> bytes:
    body = "<html><body>" + "".join(
        f"<p>Large HTML body {index:04d} with searchable governed text.</p>"
        for index in range(180)
    ) + '<script>alert(1)</script><img src="https://tracker.example/pixel.png"></body></html>'
    return message(
        subject="Large HTML contained message",
        message_id="<large-html@example.test>",
        body=body,
        content_type="text/html; charset=utf-8",
    )


def _large_attachment_message() -> bytes:
    attachment_payload = "\n".join("QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVo=" for _ in range(220))
    return b"""From: Attachment Sender <attach@example.test>
To: Bob Recipient <bob@example.test>
Subject: Large attachment contained message
Date: Tue, 21 Jul 2026 11:30:00 +0000
Message-ID: <large-attachment@example.test>
MIME-Version: 1.0
Content-Type: multipart/mixed; boundary="MIXED"

--MIXED
Content-Type: text/plain; charset=utf-8

Attachment-heavy message preview.
--MIXED
Content-Type: application/pdf
Content-Disposition: attachment; filename="../../large-report.pdf"
Content-ID: <large-attachment-1>
Content-Transfer-Encoding: base64

""" + attachment_payload.encode("ascii") + b"""
--MIXED--
"""


class StreamingMBOXLargeMessageSupportTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "pending"
        self.env = patch.dict(
            os.environ,
            {
                "ADMIN_USERNAME": "large-message-admin",
                "ADMIN_PASSWORD": "admin-password",
                "CDE_ADMIN_SESSION_SECRET": "session-secret",
                "CDE_DOCUMENT_INTAKE_ROOT": str(self.root),
                "CDE_DOCUMENT_INTAKE_MAX_BYTES": "512",
                "MAX_STREAMING_MBOX_UPLOAD_BYTES": str(2 * 1024 * 1024),
                "STREAMING_MBOX_CHUNK_BYTES": "1024",
                "STREAMING_MBOX_MIN_FREE_BYTES": "0",
            },
            clear=False,
        )
        self.env.start()
        self.patches = [
            patch("api.email_documents.MAX_MBOX_MESSAGE_IN_MEMORY_BYTES", 512),
            patch("api.email_documents.MAX_MBOX_MESSAGE_BYTES", 64 * 1024),
            patch("api.email_documents.MAX_MBOX_MESSAGE_INDEX_BYTES", 4096),
            patch("api.email_documents.MAX_MBOX_MESSAGE_PREVIEW_BYTES", 4096),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.env.stop()
        self.temp_dir.cleanup()

    def _store(self, data: bytes, **overrides):
        values = {
            "file_handle": ChunkedReader(data, max_chunk=1500),
            "original_filename": "large-contained-message.mbox",
            "content_type": "application/octet-stream",
            "title": "Large Contained Message Mailbox",
            "institution_source": "Apple Mail",
            "document_date": "2026-07-27",
            "category": "Mailbox Archive",
            "description": "Mailbox with a large contained message.",
            "visibility": "private",
            "notes": "CDE Platform Stage 37A large message test.",
            "reference_identifier": "STAGE37A-MBOX",
            "keywords": "large message, mbox",
            "actor": "large-message-admin",
            "uploaded_at": "2026-07-27T10:00:00Z",
            "root": self.root,
        }
        values.update(overrides)
        return store_streaming_mbox_pending_document(**values)

    def test_large_plain_message_uses_file_backed_projection_and_preserves_bytes(self):
        first = _large_plain_message(subject="Large contained first")
        second = message(subject="Small contained second", message_id="<small-second@example.test>")
        data = mbox(first, second)

        item = self._store(data)
        metadata = item["email_metadata"]
        messages = metadata["messages"]

        self.assertEqual(metadata["message_count"], 2)
        self.assertEqual([entry["message_index"] for entry in messages], [1, 2])
        self.assertEqual(messages[0]["preview_mode"], "file_backed_bounded")
        self.assertTrue(messages[0]["preview_truncated"])
        self.assertIn("MBOXLargeMessageFileBackedProjection", messages[0]["parser_warnings"])
        self.assertEqual(messages[0]["message_digest"], hashlib.sha256(first).hexdigest())
        self.assertEqual(messages[0]["byte_end"] - messages[0]["byte_start"], len(first))
        self.assertIn("Large plain body", messages[0]["plain_text_preview"])
        self.assertEqual(messages[1]["preview_mode"], "in_memory")
        file_path, _metadata = intake_document_file(item["intake_id"], root=self.root)
        self.assertEqual(Path(file_path).read_bytes(), data)

    def test_large_html_and_attachment_messages_are_bounded_and_metadata_only(self):
        data = mbox(_large_html_message(), _large_attachment_message())

        item = self._store(data)
        first, second = item["email_metadata"]["messages"]

        self.assertEqual(first["preview_mode"], "file_backed_bounded")
        self.assertTrue(first["html_preview_available"])
        self.assertIn("Large HTML body", first["sanitized_html_preview"])
        self.assertNotIn("<script", first["sanitized_html_preview"])
        self.assertNotIn("https://tracker.example", first["sanitized_html_preview"])

        self.assertEqual(second["preview_mode"], "file_backed_bounded")
        self.assertEqual(second["attachment_count"], 1)
        self.assertEqual(second["attachments_metadata"][0]["filename"], "../../large-report.pdf")
        self.assertNotIn("attachment_bytes", second["attachments_metadata"][0])

    def test_hard_message_limit_error_reports_message_specific_fields_and_no_document(self):
        too_large = _large_plain_message(repeat=80)
        data = mbox(too_large)
        with patch("api.email_documents.MAX_MBOX_MESSAGE_BYTES", len(too_large) - 1):
            with self.assertRaisesRegex(ValueError, "document_intake_mbox_message_too_large") as raised:
                self._store(data)
        error = raised.exception
        self.assertEqual(getattr(error, "message_index"), 1)
        self.assertEqual(getattr(error, "message_size_bytes"), len(too_large))
        self.assertEqual(getattr(error, "configured_message_maximum_bytes"), len(too_large) - 1)
        governed_dirs = [path for path in self.root.iterdir() if path.is_dir() and path.name != "_streaming_mbox_tmp"]
        self.assertEqual(governed_dirs, [])

        request = FakeRequest(
            cookies={
                admin_session.SESSION_COOKIE_NAME: admin_session.create_admin_session("large-message-admin")
            }
        )
        with patch("api.email_documents.MAX_MBOX_MESSAGE_BYTES", len(too_large) - 1):
            with self.assertRaises(Exception) as route_error:
                admin_session.admin_streaming_mbox_intake_upload(
                    request,
                    title="Too Large Contained Message",
                    institution_source="Apple Mail",
                    document_date="2026-07-27",
                    category="Mailbox Archive",
                    description="Should fail before document creation.",
                    visibility="private",
                    notes="No document should be created.",
                    file=FakeUploadFile(data, filename="too-large-contained.mbox"),
                )
        detail = getattr(route_error.exception, "detail", {})
        self.assertEqual(detail["detail"], "document_intake_mbox_message_too_large")
        self.assertEqual(detail["configured_archive_maximum_bytes"], 2 * 1024 * 1024)
        self.assertEqual(detail["configured_message_maximum_bytes"], len(too_large) - 1)
        self.assertEqual(detail["message_size_bytes"], len(too_large))
        self.assertEqual(detail["message_index"], 1)
        self.assertFalse(detail["document_created"])
        self.assertNotIn("configured_maximum_bytes", detail)
        self.assertNotIn(str(self.root), str(detail))

    def test_public_message_detail_exposes_bounded_preview_fields(self):
        data = mbox(_large_plain_message())
        item = self._store(data)
        for status in ("under_review", "approved", "published"):
            item = update_intake_status(
                item["intake_id"],
                status,
                actor="large-message-admin",
                note=f"{status} note",
                root=self.root,
            )
        page = documents.public_document_page(item["intake_id"], message=1).content
        self.assertIn("Message size", page)
        self.assertIn("Preview mode", page)
        self.assertIn("file_backed_bounded", page)
        self.assertIn("Preview truncated", page)
        self.assertIn("Contained-message digest", page)

    def test_admin_ui_distinguishes_archive_and_contained_message_limits(self):
        request = FakeRequest(
            cookies={
                admin_session.SESSION_COOKIE_NAME: admin_session.create_admin_session("large-message-admin")
            }
        )
        page = admin_session.admin_document_intake_page(request).content
        self.assertIn("Maximum governed streaming MBOX upload size", page)
        self.assertIn("Contained messages are separately bounded", page)
        self.assertIn("bounded file-backed previews", page)

    def test_parser_file_path_accepts_message_exactly_at_hard_limit(self):
        data = mbox(_large_plain_message(repeat=20))
        path = self.root / "exact-limit.mbox"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        first_size = len(_large_plain_message(repeat=20))
        with patch("api.email_documents.MAX_MBOX_MESSAGE_BYTES", first_size):
            metadata = parse_mbox_archive_metadata_from_file(path, max_archive_bytes=len(data))
        self.assertEqual(metadata["message_count"], 1)
        self.assertEqual(metadata["messages"][0]["message_byte_size"], first_size)


if __name__ == "__main__":
    unittest.main()
