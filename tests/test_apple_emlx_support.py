import hashlib
import os
import plistlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from api.document_intake import (
    build_document_search_text,
    document_media_type,
    intake_document_file,
    is_email_document,
    list_published_documents,
    store_pending_document,
    update_intake_status,
    validate_document_file,
)
from api.email_documents import parse_apple_emlx_metadata
from tests.test_admin_session import FakeRequest, install_fastapi_stubs

install_fastapi_stubs()

from api.public_document_preview import render_public_document_preview
from api.routes import admin_session, archive, documents


PLAIN_MESSAGE = b"""From: Apple Sender <apple@example.test>
To: Public Reader <reader@example.test>
Cc: Copy Reader <copy@example.test>
Subject: Apple Mail governed message
Date: Thu, 23 Jul 2026 09:00:00 +0000
Message-ID: <apple-mail-001@example.test>
In-Reply-To: <apple-previous@example.test>
References: <apple-root@example.test> <apple-previous@example.test>
MIME-Version: 1.0
Content-Type: text/plain; charset=utf-8

Apple Mail plain body for governed discovery.
"""

HTML_ONLY_MESSAGE = b"""From: Apple HTML <html@example.test>
To: Public Reader <reader@example.test>
Subject: Apple Mail HTML only
Date: Thu, 23 Jul 2026 10:00:00 +0000
Message-ID: <apple-html-001@example.test>
MIME-Version: 1.0
Content-Type: text/html; charset=utf-8

<html><body><p onclick="bad()">Visible Apple HTML</p><script>alert(1)</script><img src="https://tracker.example/pixel.png"><a href="javascript:alert(1)">bad</a></body></html>
"""

MULTIPART_MESSAGE = b"""From: Apple Multipart <multi@example.test>
To: Public Reader <reader@example.test>
Subject: Apple Mail multipart
Date: Thu, 23 Jul 2026 11:00:00 +0000
Message-ID: <apple-multipart-001@example.test>
MIME-Version: 1.0
Content-Type: multipart/mixed; boundary="MIXED"

--MIXED
Content-Type: multipart/alternative; boundary="ALT"

--ALT
Content-Type: text/plain; charset=utf-8

Apple multipart plain body.
--ALT
Content-Type: text/html; charset=utf-8

<p>Apple multipart HTML body.</p>
--ALT--
--MIXED
Content-Type: application/pdf
Content-Disposition: attachment; filename="../../apple-unsafe.pdf"
Content-ID: <apple-attachment-1>

%PDF-apple-attachment
--MIXED--
"""


def emlx(message: bytes, trailing: bytes = b"") -> bytes:
    return str(len(message)).encode("ascii") + b"\n" + message + trailing


def xml_plist() -> bytes:
    return plistlib.dumps(
        {
            "flags": 7,
            "read": True,
            "replied": True,
            "forwarded": False,
            "flagged": True,
            "date_received": "2026-07-23T09:05:00Z",
            "mailbox_path": "/Users/private/Library/Mail/secret",
        },
        fmt=plistlib.FMT_XML,
    )


def binary_plist() -> bytes:
    return plistlib.dumps({"flags": 3, "read_state": False}, fmt=plistlib.FMT_BINARY)


class AppleMailEmlxSupportTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "pending"
        self.env = patch.dict(
            os.environ,
            {
                "ADMIN_USERNAME": "emlx-admin",
                "ADMIN_PASSWORD": "admin-password",
                "CDE_ADMIN_SESSION_SECRET": "session-secret",
                "CDE_DOCUMENT_INTAKE_ROOT": str(self.root),
            },
            clear=False,
        )
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp_dir.cleanup()

    def _store(self, data: bytes, **overrides):
        values = {
            "original_filename": "governed-apple-message.emlx",
            "content_type": "application/octet-stream",
            "title": "Governed Apple Mail Message",
            "institution_source": "Apple Mail Source",
            "document_date": "2026-07-23",
            "category": "Email Correspondence",
            "description": "Native Apple Mail message preserved as a governed document.",
            "visibility": "private",
            "notes": "Private Apple Mail intake note.",
            "reference_identifier": "EMLX-REF-001",
            "keywords": "apple mail, emlx, correspondence",
            "actor": "emlx-admin",
            "uploaded_at": "2026-07-23T10:00:00Z",
            "root": self.root,
        }
        values.update(overrides)
        return store_pending_document(data=data, **values)

    def _publish(self, item):
        for status, timestamp in (
            ("under_review", "2026-07-23T11:00:00Z"),
            ("approved", "2026-07-23T12:00:00Z"),
            ("published", "2026-07-23T13:00:00Z"),
        ):
            item = update_intake_status(
                item["intake_id"],
                status,
                actor="emlx-admin",
                note=f"{status} note",
                changed_at=timestamp,
                root=self.root,
            )
        return item

    def test_valid_emlx_upload_preserves_full_original_bytes_and_reuses_rfc5322_projection(self):
        for trailing in (b"", xml_plist(), binary_plist()):
            with self.subTest(trailing=bool(trailing)):
                data = emlx(PLAIN_MESSAGE, trailing)
                item = self._store(data)
                digest = hashlib.sha256(data).hexdigest()

                self.assertEqual(item["document_type"], "emlx")
                self.assertEqual(item["document_format"], "Apple Mail Message")
                self.assertEqual(item["content_type"], "application/octet-stream")
                self.assertEqual(item["media_family"], "email")
                self.assertEqual(item["sha256_hash"], digest)
                self.assertTrue(is_email_document(item))
                self.assertEqual(document_media_type(item), "application/octet-stream")
                self.assertEqual(item["email_metadata"]["source_format"], "apple_emlx")
                self.assertEqual(item["email_metadata"]["message_id"], "<apple-mail-001@example.test>")
                self.assertEqual(item["email_metadata"]["subject_decoded"], "Apple Mail governed message")
                self.assertIn("Apple Sender", item["email_metadata"]["from_addresses"][0])
                self.assertIn("Apple Mail plain body", item["email_metadata"]["plain_text_body"])
                self.assertEqual(item["email_metadata"]["emlx_declared_message_bytes"], len(PLAIN_MESSAGE))
                file_path, _metadata = intake_document_file(item["intake_id"], root=self.root)
                self.assertEqual(Path(file_path).read_bytes(), data)

    def test_emlx_parser_handles_html_multipart_attachments_and_apple_metadata(self):
        html = parse_apple_emlx_metadata(emlx(HTML_ONLY_MESSAGE))
        self.assertIn("Visible Apple HTML", html["body_search_text"])
        self.assertIn("remote image suppressed", html["body_search_text"])
        self.assertNotIn("<script", html["sanitized_html_body"].lower())
        self.assertNotIn("onclick", html["sanitized_html_body"].lower())
        self.assertNotIn("https://tracker.example", html["sanitized_html_body"])
        self.assertNotIn("javascript:", html["sanitized_html_body"].lower())

        multipart = parse_apple_emlx_metadata(emlx(MULTIPART_MESSAGE, xml_plist()))
        self.assertTrue(multipart["is_multipart"])
        self.assertIn("Apple multipart plain body", multipart["plain_text_body"])
        self.assertIn("Apple multipart HTML body", multipart["body_search_text"])
        self.assertEqual(multipart["attachment_count"], 1)
        self.assertEqual(multipart["attachments_metadata"][0]["filename"], "../../apple-unsafe.pdf")
        self.assertEqual(multipart["attachments_metadata"][0]["media_type"], "application/pdf")
        self.assertEqual(multipart["apple_mail_flags"], 7)
        self.assertTrue(multipart["apple_mail_read_state"])
        self.assertTrue(multipart["emlx_trailing_metadata_present"])
        self.assertNotIn("mailbox_path", build_document_search_text({"email_metadata": multipart}))

    def test_emlx_validation_rejects_masquerades_and_resource_limit_excesses(self):
        data = emlx(PLAIN_MESSAGE)
        self.assertEqual(validate_document_file(data, "message.emlx", "application/octet-stream")[0], "emlx")
        for payload, filename, error in (
            (b"", "empty.emlx", "document_intake_file_required"),
            (b"not-a-length\nFrom: A\n\nBody", "text.emlx", "document_intake_file_type_not_allowed"),
            (b"-1\nFrom: A\n\nBody", "negative.emlx", "document_intake_file_type_not_allowed"),
            (b"0\nFrom: A\n\nBody", "zero.emlx", "document_intake_file_type_not_allowed"),
            (b"999\nFrom: A\n\nBody", "truncated.emlx", "document_intake_emlx_truncated_message"),
            (emlx(b"From: no body separator"), "malformed.emlx", "document_intake_file_type_not_allowed"),
            (b"%PDF-1.7\nrenamed\n%%EOF\n", "renamed.emlx", "document_intake_file_type_mismatch"),
            (data, "wrong.pdf", "document_intake_file_type_mismatch"),
        ):
            with self.subTest(filename=filename):
                with self.assertRaisesRegex(ValueError, error):
                    validate_document_file(payload, filename, "application/octet-stream")

        with patch("api.email_documents.MAX_EMLX_FIRST_LINE_BYTES", 2):
            with self.assertRaisesRegex(ValueError, "document_intake_emlx_first_line_too_large"):
                validate_document_file(data, "line-too-long.emlx", "application/octet-stream")
        with patch("api.email_documents.MAX_EMLX_MESSAGE_BYTES", 10):
            with self.assertRaisesRegex(ValueError, "document_intake_emlx_message_too_large"):
                validate_document_file(data, "message-too-large.emlx", "application/octet-stream")
        with patch("api.email_documents.MAX_EMLX_TRAILING_METADATA_BYTES", 5):
            with self.assertRaisesRegex(ValueError, "document_intake_emlx_trailing_metadata_too_large"):
                validate_document_file(emlx(PLAIN_MESSAGE, b"0123456789"), "plist-too-large.emlx", "application/octet-stream")
        with self.assertRaisesRegex(ValueError, "document_intake_emlx_malformed_plist"):
            validate_document_file(emlx(PLAIN_MESSAGE, b"<?xml version='1.0'?><plist>"), "bad-plist.emlx", "application/octet-stream")

    def test_published_emlx_public_page_preview_search_archive_and_download(self):
        data = emlx(MULTIPART_MESSAGE, xml_plist())
        item = self._publish(self._store(data))
        page = documents.public_document_page(item["intake_id"]).content

        self.assertIn("Email Overview", page)
        self.assertIn("Apple Mail Metadata", page)
        self.assertIn("Message Body", page)
        self.assertIn("Attachments", page)
        self.assertIn("Email Governance Boundary", page)
        self.assertIn("Parsed Apple Mail and RFC 5322 metadata reflects fields contained", page)
        self.assertIn("Apple Mail multipart", page)
        self.assertIn("../../apple-unsafe.pdf", page)
        self.assertIn("Download original .emlx", page)
        self.assertIn("<td>Apple Mail Message</td>", page)
        self.assertIn("<td>Email</td>", page)
        self.assertIn("Apple Mail flags recorded in source", page)
        self.assertNotIn("/Users/private/Library/Mail/secret", page)

        search_text = build_document_search_text(item)
        self.assertIn("apple-multipart-001@example.test", search_text)
        self.assertIn("apple multipart", search_text)
        self.assertIn("reader@example.test", search_text)
        self.assertIn("apple-unsafe.pdf", search_text)
        self.assertNotIn("/users/private/library/mail/secret", search_text)
        self.assertEqual(
            [document["intake_id"] for document in list_published_documents(query="apple-unsafe.pdf", root=self.root)],
            [item["intake_id"]],
        )

        library = documents.public_document_library(q="apple-multipart-001").content
        self.assertIn("1 published document.", library)
        self.assertIn("Apple Mail Message", library)
        self.assertIn("Open Apple Mail Message", library)
        archive_page = archive.public_archive_explorer(media="email").content
        self.assertIn("Governed Apple Mail Message", archive_page)
        preview = render_public_document_preview(item, root=self.root)
        self.assertIn("Apple Mail Message", preview)
        self.assertIn("Open Apple Mail Message", preview)

        response = documents.public_document_download(item["intake_id"])
        self.assertEqual(response.media_type, "application/octet-stream")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertIn("attachment", response.headers["Content-Disposition"])
        self.assertEqual(Path(response.path).read_bytes(), data)

    def test_pending_emlx_private_admin_form_and_review_boundary(self):
        item = self._store(emlx(HTML_ONLY_MESSAGE))
        with self.assertRaises(Exception):
            documents.public_document_page(item["intake_id"])

        request = FakeRequest(
            cookies={
                admin_session.SESSION_COOKIE_NAME: admin_session.create_admin_session("emlx-admin")
            }
        )
        admin_page = admin_session.admin_document_intake_page(request).content
        self.assertIn("Apple Mail Message (.emlx)", admin_page)
        review_page = admin_session.admin_document_intake_preview_page(item["intake_id"], request).content
        self.assertIn("Apple Mail .emlx artefacts are preserved as original bytes", review_page)
        self.assertIn("Apple Mail Message", review_page)


if __name__ == "__main__":
    unittest.main()
