import hashlib
import os
import tempfile
import unittest
from email.header import Header
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
from api.email_documents import parse_email_metadata
from tests.test_admin_session import FakeRequest, install_fastapi_stubs

install_fastapi_stubs()

from api.public_document_preview import render_public_document_preview
from api.routes import admin_session, archive, documents


PLAIN_EML = b"""From: Alice Sender <alice@example.test>
To: Bob Recipient <bob@example.test>
Cc: Casey Copy <casey@example.test>
Subject: Governance email preserved as source
Date: Tue, 21 Jul 2026 10:30:00 +0000
Message-ID: <governed-email-001@example.test>
In-Reply-To: <previous@example.test>
References: <root@example.test> <previous@example.test>
MIME-Version: 1.0
Content-Type: text/plain; charset=utf-8

This is the preserved plain text body for discovery.
"""

HTML_ONLY_EML = b"""From: HTML Sender <html@example.test>
To: Public Reader <reader@example.test>
Subject: HTML only email
Date: Tue, 21 Jul 2026 11:30:00 +0000
Message-ID: <html-email-001@example.test>
MIME-Version: 1.0
Content-Type: text/html; charset=utf-8

<html><body><h1>HTML body</h1><script>alert(1)</script><p onclick="bad()">Visible text</p><img src="https://tracker.example/pixel.png"><a href="javascript:alert(1)">bad link</a></body></html>
"""

MULTIPART_ALTERNATIVE_EML = b"""From: Multipart Sender <multi@example.test>
To: Bob Recipient <bob@example.test>
Subject: Multipart alternative email
Date: Tue, 21 Jul 2026 12:30:00 +0000
Message-ID: <multipart-alt-001@example.test>
MIME-Version: 1.0
Content-Type: multipart/alternative; boundary="ALT"

--ALT
Content-Type: text/plain; charset=utf-8

Plain alternative body.
--ALT
Content-Type: text/html; charset=utf-8

<p>HTML alternative body.</p>
--ALT--
"""

MIXED_ATTACHMENT_EML = b"""From: Attachment Sender <attach@example.test>
To: Bob Recipient <bob@example.test>
Subject: Email with attachment metadata
Date: Tue, 21 Jul 2026 13:30:00 +0000
Message-ID: <attachment-email-001@example.test>
MIME-Version: 1.0
Content-Type: multipart/mixed; boundary="MIXED"

--MIXED
Content-Type: text/plain; charset=utf-8

See attached local note.
--MIXED
Content-Type: application/pdf
Content-Disposition: attachment; filename="../../unsafe-name.pdf"
Content-ID: <attachment-1>

%PDF-attachment-bytes
--MIXED--
"""


def encoded_header_eml() -> bytes:
    subject = Header("Café correspondence", "utf-8").encode()
    from_name = Header("Áine Example", "utf-8").encode()
    return f"""From: {from_name} <aine@example.test>
To: Recipient <recipient@example.test>
Subject: {subject}
Date: Tue, 21 Jul 2026 14:30:00 +0000
Message-ID: <encoded-email-001@example.test>
MIME-Version: 1.0
Content-Type: text/plain; charset=utf-8

Encoded headers body.
""".encode("utf-8")


class RFC5322EmailSupportTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "pending"
        self.env = patch.dict(
            os.environ,
            {
                "ADMIN_USERNAME": "email-admin",
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

    def _store(self, data=PLAIN_EML, **overrides):
        values = {
            "original_filename": "governed-message.eml",
            "content_type": "message/rfc822",
            "title": "Governed Email Message",
            "institution_source": "Civic Email Source",
            "document_date": "2026-07-21",
            "category": "Email Correspondence",
            "description": "Native RFC 5322 email preserved as a governed document.",
            "visibility": "private",
            "notes": "Private email intake note.",
            "reference_identifier": "EMAIL-REF-001",
            "keywords": "email, RFC 5322, correspondence",
            "actor": "email-admin",
            "uploaded_at": "2026-07-21T10:00:00Z",
            "root": self.root,
        }
        values.update(overrides)
        return store_pending_document(data=data, **values)

    def _publish(self, item):
        for status, timestamp in (
            ("under_review", "2026-07-21T11:00:00Z"),
            ("approved", "2026-07-21T12:00:00Z"),
            ("published", "2026-07-21T13:00:00Z"),
        ):
            item = update_intake_status(
                item["intake_id"],
                status,
                actor="email-admin",
                note=f"{status} note",
                changed_at=timestamp,
                root=self.root,
            )
        return item

    def test_valid_eml_upload_preserves_original_bytes_and_extracts_metadata(self):
        for content_type in ("message/rfc822", "text/rfc822", "application/eml"):
            with self.subTest(content_type=content_type):
                data = PLAIN_EML + content_type.encode("ascii")
                item = self._store(data, content_type=content_type)
                digest = hashlib.sha256(data).hexdigest()

                self.assertEqual(item["document_type"], "eml")
                self.assertEqual(item["document_format"], "RFC 5322 Email")
                self.assertEqual(item["content_type"], "message/rfc822")
                self.assertEqual(item["media_family"], "email")
                self.assertEqual(item["sha256_hash"], digest)
                self.assertTrue(is_email_document(item))
                self.assertEqual(document_media_type(item), "message/rfc822")
                self.assertEqual(item["email_metadata"]["message_id"], "<governed-email-001@example.test>")
                self.assertEqual(item["email_metadata"]["subject_decoded"], "Governance email preserved as source")
                self.assertIn("Alice Sender", item["email_metadata"]["from_addresses"][0])
                self.assertIn("This is the preserved plain text body", item["email_metadata"]["plain_text_body"])
                file_path, _metadata = intake_document_file(item["intake_id"], root=self.root)
                self.assertEqual(Path(file_path).read_bytes(), data)

    def test_eml_parser_handles_html_multipart_attachment_and_encoded_headers(self):
        html = parse_email_metadata(HTML_ONLY_EML)
        self.assertIn("Visible text", html["body_search_text"])
        self.assertIn("remote image suppressed", html["body_search_text"])
        self.assertNotIn("<script", html["sanitized_html_body"].lower())
        self.assertNotIn("onclick", html["sanitized_html_body"].lower())
        self.assertNotIn("https://tracker.example", html["sanitized_html_body"])
        self.assertNotIn("javascript:", html["sanitized_html_body"].lower())

        alternative = parse_email_metadata(MULTIPART_ALTERNATIVE_EML)
        self.assertTrue(alternative["is_multipart"])
        self.assertIn("Plain alternative body.", alternative["plain_text_body"])
        self.assertIn("HTML alternative body.", alternative["body_search_text"])

        mixed = parse_email_metadata(MIXED_ATTACHMENT_EML)
        self.assertEqual(mixed["attachment_count"], 1)
        self.assertEqual(mixed["attachments_metadata"][0]["filename"], "../../unsafe-name.pdf")
        self.assertEqual(mixed["attachments_metadata"][0]["media_type"], "application/pdf")
        self.assertEqual(mixed["attachments_metadata"][0]["content_id"], "<attachment-1>")

        encoded = parse_email_metadata(encoded_header_eml())
        self.assertEqual(encoded["subject_decoded"], "Café correspondence")
        self.assertIn("Áine Example", encoded["from_addresses"][0])

    def test_eml_validation_rejects_masquerades_and_resource_limit_excesses(self):
        self.assertEqual(validate_document_file(PLAIN_EML, "message.eml", "message/rfc822")[0], "eml")
        for data, filename, error in (
            (b"", "empty.eml", "document_intake_file_required"),
            (b"plain text", "plain.eml", "document_intake_file_type_not_allowed"),
            (b"From: no body separator", "malformed.eml", "document_intake_file_type_not_allowed"),
            (b"%PDF-1.7\nrenamed\n%%EOF\n", "renamed.eml", "document_intake_file_type_mismatch"),
            (PLAIN_EML, "wrong.pdf", "document_intake_file_type_mismatch"),
        ):
            with self.subTest(filename=filename):
                with self.assertRaisesRegex(ValueError, error):
                    validate_document_file(data, filename, "message/rfc822")

        with patch("api.email_documents.MAX_MIME_PARTS", 2):
            with self.assertRaisesRegex(ValueError, "document_intake_email_too_many_parts"):
                validate_document_file(MULTIPART_ALTERNATIVE_EML, "too-many.eml", "message/rfc822")
        with patch("api.email_documents.MAX_TOTAL_DECODED_BYTES", 10):
            with self.assertRaisesRegex(ValueError, "document_intake_email_decoded_content_too_large"):
                validate_document_file(PLAIN_EML, "too-large.eml", "message/rfc822")

    def test_published_eml_public_page_preview_search_archive_and_download(self):
        item = self._publish(self._store(data=MIXED_ATTACHMENT_EML))
        page = documents.public_document_page(item["intake_id"]).content

        self.assertIn("Email Overview", page)
        self.assertIn("Message Body", page)
        self.assertIn("Attachments", page)
        self.assertIn("Email Governance Boundary", page)
        self.assertIn("Parsed email metadata reflects fields contained", page)
        self.assertIn("Email with attachment metadata", page)
        self.assertIn("../../unsafe-name.pdf", page)
        self.assertIn("Download original .eml", page)
        self.assertIn("<td>RFC 5322 Email</td>", page)
        self.assertIn("<td>Email</td>", page)

        search_text = build_document_search_text(item)
        self.assertIn("attachment-email-001@example.test", search_text)
        self.assertIn("attachment sender", search_text)
        self.assertIn("bob recipient", search_text)
        self.assertIn("see attached local note", search_text)
        self.assertIn("unsafe-name.pdf", search_text)

        self.assertEqual(
            [document["intake_id"] for document in list_published_documents(query="unsafe-name.pdf", root=self.root)],
            [item["intake_id"]],
        )
        library = documents.public_document_library(q="attachment-email-001").content
        self.assertIn("1 published document.", library)
        self.assertIn("RFC 5322 Email", library)
        self.assertIn("Open Email document", library)

        archive_page = archive.public_archive_explorer(media="email").content
        self.assertIn("Email", archive_page)
        self.assertIn("Governed Email Message", archive_page)

        preview = render_public_document_preview(item, root=self.root)
        self.assertIn("RFC 5322 Email", preview)
        self.assertIn("Open Email document", preview)

        response = documents.public_document_download(item["intake_id"])
        self.assertEqual(response.media_type, "message/rfc822")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertIn("attachment", response.headers["Content-Disposition"])
        self.assertEqual(Path(response.path).read_bytes(), MIXED_ATTACHMENT_EML)

    def test_pending_eml_remains_private_and_admin_preview_explains_boundary(self):
        item = self._store(data=HTML_ONLY_EML)
        with self.assertRaises(Exception):
            documents.public_document_page(item["intake_id"])

        request = FakeRequest(
            cookies={
                admin_session.SESSION_COOKIE_NAME: admin_session.create_admin_session("email-admin")
            }
        )
        admin_page = admin_session.admin_document_intake_page(request).content
        self.assertIn("RFC 5322 Email (.eml)", admin_page)
        review_page = admin_session.admin_document_intake_preview_page(item["intake_id"], request).content
        self.assertIn("RFC 5322 email artefacts are preserved as original bytes", review_page)
        self.assertIn("RFC 5322 Email", review_page)


if __name__ == "__main__":
    unittest.main()
