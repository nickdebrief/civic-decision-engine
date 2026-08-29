import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from api.document_intake import (
    build_document_search_text,
    document_media_type,
    intake_document_file,
    is_mailbox_document,
    list_published_documents,
    load_pending_document,
    store_pending_document,
    update_intake_status,
    validate_document_file,
)
from api.email_documents import parse_mbox_archive_metadata
from tests.test_admin_session import FakeRequest, install_fastapi_stubs

install_fastapi_stubs()

from api.public_document_preview import render_public_document_preview
from api.routes import admin_session, archive, documents


def message(
    *,
    sender: str = "Alice Sender <alice@example.test>",
    recipient: str = "Bob Recipient <bob@example.test>",
    subject: str = "MBOX governed message",
    message_id: str = "<mbox-001@example.test>",
    date: str = "Tue, 21 Jul 2026 10:30:00 +0000",
    body: str = "Preserved mailbox body for discovery.",
    content_type: str = "text/plain; charset=utf-8",
) -> bytes:
    return f"""From: {sender}
To: {recipient}
Cc: Casey Copy <casey@example.test>
Subject: {subject}
Date: {date}
Message-ID: {message_id}
MIME-Version: 1.0
Content-Type: {content_type}

{body}
""".encode("utf-8")


def html_message() -> bytes:
    return message(
        sender="HTML Sender <html@example.test>",
        subject="HTML mailbox message",
        message_id="<mbox-html@example.test>",
        body='<html><body><p onclick="bad()">Visible HTML mailbox text</p><script>alert(1)</script><img src="https://tracker.example/pixel.png"><a href="javascript:alert(1)">bad</a></body></html>',
        content_type="text/html; charset=utf-8",
    )


def attachment_message() -> bytes:
    return b"""From: Attachment Sender <attach@example.test>
To: Bob Recipient <bob@example.test>
Subject: MBOX attachment message
Date: Tue, 21 Jul 2026 11:30:00 +0000
Message-ID: <mbox-attachment@example.test>
MIME-Version: 1.0
Content-Type: multipart/mixed; boundary="MIXED"

--MIXED
Content-Type: text/plain; charset=utf-8

Attached mailbox note.
--MIXED
Content-Type: application/pdf
Content-Disposition: attachment; filename="../../unsafe-name.pdf"
Content-ID: <attachment-1>

%PDF-attachment-bytes
--MIXED--
"""


def mbox(*messages: bytes, separators: list[bytes] | None = None) -> bytes:
    default_separators = [
        b"From alice@example.test Tue Jul 21 10:30:00 2026\n",
        b"From html@example.test Tue Jul 21 11:30:00 2026\n",
        b"From attach@example.test Tue Jul 21 12:30:00 2026\n",
        b"From duplicate@example.test Tue Jul 21 13:30:00 2026\n",
    ]
    separators = separators or default_separators
    chunks: list[bytes] = []
    for index, msg in enumerate(messages):
        chunks.append(separators[index])
        chunks.append(msg)
    return b"".join(chunks)


class MBOXArchiveSupportTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "pending"
        self.env = patch.dict(
            os.environ,
            {
                "ADMIN_USERNAME": "mbox-admin",
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

    def _store(self, data: bytes | None = None, **overrides):
        values = {
            "data": data or mbox(message()),
            "original_filename": "governed-mailbox.mbox",
            "content_type": "application/mbox",
            "title": "Governed MBOX Archive",
            "institution_source": "Civic Mailbox Source",
            "document_date": "2026-07-27",
            "category": "Mailbox Archive",
            "description": "Native MBOX archive preserved as a governed container document.",
            "visibility": "private",
            "notes": "Private mailbox intake note.",
            "reference_identifier": "MBOX-REF-001",
            "keywords": "mbox, mailbox, correspondence",
            "actor": "mbox-admin",
            "uploaded_at": "2026-07-27T10:00:00Z",
            "root": self.root,
        }
        values.update(overrides)
        return store_pending_document(**values)

    def _publish(self, item):
        for status, timestamp in (
            ("under_review", "2026-07-27T11:00:00Z"),
            ("approved", "2026-07-27T12:00:00Z"),
            ("published", "2026-07-27T13:00:00Z"),
        ):
            item = update_intake_status(
                item["intake_id"],
                status,
                actor="mbox-admin",
                note=f"{status} note",
                changed_at=timestamp,
                root=self.root,
            )
        return item

    def _numbered_mbox(self, count: int) -> bytes:
        messages = [
            message(
                sender=f"Sender {index:03d} <sender-{index:03d}@example.test>",
                recipient=f"Recipient {index:03d} <recipient-{index:03d}@example.test>",
                subject=f"Mailbox page message {index:03d}",
                message_id=f"<mbox-page-{index:03d}@example.test>",
                date=f"Tue, 21 Jul 2026 10:{index % 60:02d}:00 +0000",
                body=f"Synthetic mailbox body {index:03d}.",
            )
            for index in range(1, count + 1)
        ]
        separators = [
            f"From sender-{index:03d}@example.test Tue Jul 21 10:{index % 60:02d}:00 2026\n".encode()
            for index in range(1, count + 1)
        ]
        return mbox(*messages, separators=separators)

    def _published_numbered_mailbox(self, count: int):
        data = self._numbered_mbox(count)
        if count == 0:
            data = mbox(
                message(
                    subject="Mailbox zero fixture placeholder",
                    message_id="<mbox-page-zero-placeholder@example.test>",
                    body="Synthetic placeholder removed from zero-message metadata.",
                )
            )
        item = self._publish(
            self._store(
                data,
                title=f"Synthetic {count} message mailbox",
                reference_identifier=f"MBOX-PAGE-{count:03d}",
            )
        )
        if count:
            return item
        stored = load_pending_document(item["intake_id"], root=self.root)
        stored["email_metadata"]["messages"] = []
        stored["email_metadata"]["message_count"] = 0
        stored["email_metadata"]["parsed_message_count"] = 0
        stored["email_metadata"]["unparsed_message_count"] = 0
        stored["email_metadata"]["warning_message_count"] = 0
        stored["email_metadata"]["attachment_total"] = 0
        stored["email_metadata"]["message_ids_present"] = 0
        stored["email_metadata"]["message_ids_missing"] = 0
        stored["email_metadata"]["exact_duplicate_count"] = 0
        stored["email_metadata"]["earliest_message_date"] = None
        stored["email_metadata"]["latest_message_date"] = None
        metadata_path = self.root / item["intake_id"] / "metadata.json"
        metadata_path.write_text(json.dumps(stored, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return stored

    @staticmethod
    def _message_index_table(page: str) -> str:
        start = page.index('<table class="public-mbox-message-index"')
        end = page.index("</table>", start)
        return page[start:end]

    @staticmethod
    def _message_subjects(page: str) -> set[str]:
        table = MBOXArchiveSupportTests._message_index_table(page)
        return {
            f"Mailbox page message {index:03d}"
            for index in range(1, 80)
            if f"Mailbox page message {index:03d}" in table
        }

    def test_valid_mbox_upload_preserves_original_bytes_and_indexes_messages(self):
        data = mbox(message(), html_message(), attachment_message())
        item = self._store(data)
        digest = hashlib.sha256(data).hexdigest()

        self.assertEqual(item["document_type"], "mbox")
        self.assertEqual(item["document_format"], "MBOX Mailbox Archive")
        self.assertEqual(item["content_type"], "application/mbox")
        self.assertEqual(item["media_family"], "mailbox")
        self.assertEqual(item["sha256_hash"], digest)
        self.assertTrue(is_mailbox_document(item))
        self.assertEqual(document_media_type(item), "application/mbox")
        metadata = item["email_metadata"]
        self.assertEqual(metadata["source_format"], "mbox")
        self.assertEqual(metadata["message_count"], 3)
        self.assertEqual(metadata["parsed_message_count"], 3)
        self.assertEqual(metadata["attachment_total"], 1)
        self.assertEqual([m["message_index"] for m in metadata["messages"]], [1, 2, 3])
        self.assertEqual(metadata["messages"][2]["attachments_metadata"][0]["filename"], "../../unsafe-name.pdf")
        file_path, _metadata = intake_document_file(item["intake_id"], root=self.root)
        self.assertEqual(Path(file_path).read_bytes(), data)

    def test_mbox_parser_handles_escaped_from_lines_duplicates_and_recoverable_messages(self):
        duplicate = message(subject="Duplicate mailbox message", message_id="<dup@example.test>")
        body_from = message(
            subject="Body From line",
            message_id="<body-from@example.test>",
            body="First line\nFrom not-a-boundary inside body\n>From escaped body line",
        )
        recoverable = b"X-Archive-Noise: historical fragment\n\nBody without recognisable RFC 5322 message fields.\n"
        metadata = parse_mbox_archive_metadata(mbox(body_from, duplicate, duplicate, recoverable))

        self.assertEqual(metadata["message_count"], 4)
        self.assertEqual(metadata["parsed_message_count"], 3)
        self.assertEqual(metadata["unparsed_message_count"], 1)
        self.assertEqual(metadata["detected_mbox_variant"], "mboxrd")
        self.assertEqual(metadata["exact_duplicate_count"], 2)
        self.assertTrue(metadata["messages"][1]["duplicate_candidate"])
        self.assertTrue(metadata["messages"][2]["duplicate_candidate"])
        self.assertEqual(metadata["messages"][0]["subject_decoded"], "Body From line")

    def test_mbox_validation_rejects_masquerades_and_resource_limit_excesses(self):
        valid = mbox(message())
        self.assertEqual(validate_document_file(valid, "mailbox.mbox", "application/mbox")[0], "mbox")
        for data, filename, error in (
            (b"", "empty.mbox", "document_intake_file_required"),
            (b"plain text", "plain.mbox", "document_intake_file_type_not_allowed"),
            (b"From not a real separator\nFrom: A\n\nBody", "fake.mbox", "document_intake_file_type_mismatch"),
            (b"%PDF-1.7\nrenamed\n%%EOF\n", "renamed.mbox", "document_intake_file_type_mismatch"),
            (valid, "wrong.eml", "document_intake_file_type_mismatch"),
        ):
            with self.subTest(filename=filename):
                with self.assertRaisesRegex(ValueError, error):
                    validate_document_file(data, filename, "application/mbox")

        with patch("api.email_documents.MAX_MBOX_MESSAGES", 1):
            with self.assertRaisesRegex(ValueError, "document_intake_mbox_too_many_messages"):
                validate_document_file(mbox(message(), message(message_id="<two@example.test>")), "too-many.mbox", "application/mbox")
        with patch("api.email_documents.MAX_MBOX_MESSAGE_BYTES", 50):
            with self.assertRaisesRegex(ValueError, "document_intake_mbox_message_too_large"):
                validate_document_file(valid, "too-large.mbox", "application/mbox")
        with patch("api.email_documents.MAX_MBOX_LINE_BYTES", 20):
            with self.assertRaisesRegex(ValueError, "document_intake_mbox_line_too_large"):
                validate_document_file(valid, "line-too-large.mbox", "application/mbox")

    def test_document_intake_accept_configuration_supports_apple_mail_mbox_exports(self):
        request = FakeRequest(
            cookies={
                admin_session.SESSION_COOKIE_NAME: admin_session.create_admin_session("mbox-admin")
            }
        )
        page = admin_session.admin_document_intake_page(request).content
        accept_values = admin_session.DOCUMENT_INTAKE_FILE_ACCEPT.split(",")

        self.assertIn(".mbox", accept_values)
        self.assertIn("application/mbox", accept_values)
        self.assertIn("text/mbox", accept_values)
        self.assertIn("application/octet-stream", accept_values)
        for existing_email_value in (
            ".eml",
            "message/rfc822",
            ".msg",
            "application/vnd.ms-outlook",
            ".emlx",
            "application/x-apple-mail",
        ):
            self.assertIn(existing_email_value, accept_values)
        self.assertIn(f'accept="{admin_session.DOCUMENT_INTAKE_FILE_ACCEPT}"', page)
        self.assertIn("Apple Mail exports an .mbox package", page)
        self.assertIn("table_of_contents file is not the mailbox archive", page)
        self.assertIn("Current governed Document Intake maximum upload size: 25 MB", page)

    def test_apple_mail_internal_mbox_copy_requires_extension_and_server_validation(self):
        valid = mbox(message())
        self.assertEqual(validate_document_file(valid, "mailbox.mbox", "application/octet-stream")[0], "mbox")
        with self.assertRaisesRegex(ValueError, "document_intake_file_type_not_allowed"):
            validate_document_file(valid, "mbox", "application/octet-stream")
        with self.assertRaisesRegex(ValueError, "document_intake_file_type_not_allowed"):
            validate_document_file(b"Apple Mail table of contents", "table_of_contents.mbox", "application/octet-stream")
        with self.assertRaisesRegex(ValueError, "document_intake_file_type_mismatch"):
            validate_document_file(b"%PDF-1.7\nrenamed\n%%EOF\n", "renamed.mbox", "application/octet-stream")

    def test_large_mbox_upload_boundary_reports_governed_error(self):
        valid = mbox(message())
        with patch.dict(os.environ, {"CDE_DOCUMENT_INTAKE_MAX_BYTES": "32"}):
            with self.assertRaisesRegex(ValueError, "document_intake_file_too_large"):
                validate_document_file(valid, "large-mailbox.mbox", "application/octet-stream")

    def test_published_mbox_public_page_search_archive_preview_and_download(self):
        data = mbox(message(subject="Searchable first message"), html_message(), attachment_message())
        item = self._publish(self._store(data))
        page = documents.public_document_page(item["intake_id"], message="2").content

        self.assertIn("Mailbox Overview", page)
        self.assertIn("Mailbox Message Index", page)
        self.assertIn("Message Detail", page)
        self.assertIn("Mailbox Governance Boundary", page)
        self.assertIn("Parsed mailbox and message metadata reflects fields contained", page)
        self.assertIn("HTML mailbox message", page)
        self.assertIn("Visible HTML mailbox text", page)
        self.assertNotIn("<script>alert", page.lower())
        self.assertNotIn("https://tracker.example", page)
        self.assertIn("Download original .mbox", page)
        self.assertIn("MBOX Mailbox Archive", page)
        self.assertIn("<td>Mailbox</td>", page)

        search_text = build_document_search_text(item)
        self.assertIn("searchable first message", search_text)
        self.assertIn("html sender", search_text)
        self.assertIn("unsafe-name.pdf", search_text)
        self.assertEqual(
            [document["intake_id"] for document in list_published_documents(query="unsafe-name.pdf", root=self.root)],
            [item["intake_id"]],
        )
        archive_page = archive.public_archive_explorer(media="mailbox").content
        self.assertIn("Mailbox Archive", archive_page)
        self.assertIn("Governed MBOX Archive", archive_page)
        preview = render_public_document_preview(item, root=self.root)
        self.assertIn("MBOX Archive", preview)
        self.assertIn("Open MBOX Archive", preview)

        response = documents.public_document_download(item["intake_id"])
        self.assertEqual(response.media_type, "application/mbox")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertIn("attachment", response.headers["Content-Disposition"])
        self.assertEqual(Path(response.path).read_bytes(), data)

    def test_published_mbox_zero_one_and_exact_page_size_have_no_pagination_controls(self):
        for count, summary in (
            (0, "Showing messages 0-0 of 0. Page 1 of 1."),
            (1, "Showing messages 1-1 of 1. Page 1 of 1."),
            (25, "Showing messages 1-25 of 25. Page 1 of 1."),
        ):
            with self.subTest(count=count):
                item = self._published_numbered_mailbox(count)
                page = documents.public_document_page(item["intake_id"]).content
                self.assertIn(summary, page)
                self.assertNotIn("mailbox-message-pagination", page)
                self.assertNotIn("Next page", page)
                self.assertNotIn("Previous page", page)

    def test_published_mbox_twenty_six_messages_exposes_second_page(self):
        item = self._published_numbered_mailbox(26)
        page_one = documents.public_document_page(item["intake_id"]).content
        page_two = documents.public_document_page(item["intake_id"], page="2").content
        self.assertIn("Showing messages 1-25 of 26. Page 1 of 2.", page_one)
        self.assertIn("Showing messages 26-26 of 26. Page 2 of 2.", page_two)
        self.assertIn(f'/documents/{item["intake_id"]}?page=2#mailbox-message-index', page_one)
        self.assertIn(f'/documents/{item["intake_id"]}?page=1#mailbox-message-index', page_two)
        self.assertNotIn("Previous page", page_one)
        self.assertNotIn("Next page", page_two)
        self.assertEqual(self._message_subjects(page_one), {f"Mailbox page message {index:03d}" for index in range(1, 26)})
        self.assertEqual(self._message_subjects(page_two), {"Mailbox page message 026"})
        self.assertFalse(self._message_subjects(page_one) & self._message_subjects(page_two))

    def test_published_mbox_thirty_four_message_pages_do_not_overlap_or_omit_messages(self):
        item = self._published_numbered_mailbox(34)
        page_one = documents.public_document_page(item["intake_id"], page="1").content
        page_two = documents.public_document_page(item["intake_id"], page="2").content
        first_subjects = self._message_subjects(page_one)
        second_subjects = self._message_subjects(page_two)
        self.assertIn("Showing messages 1-25 of 34. Page 1 of 2.", page_one)
        self.assertIn("Showing messages 26-34 of 34. Page 2 of 2.", page_two)
        self.assertEqual(first_subjects, {f"Mailbox page message {index:03d}" for index in range(1, 26)})
        self.assertEqual(second_subjects, {f"Mailbox page message {index:03d}" for index in range(26, 35)})
        self.assertEqual(first_subjects | second_subjects, {f"Mailbox page message {index:03d}" for index in range(1, 35)})
        self.assertFalse(first_subjects & second_subjects)
        self.assertEqual(
            page_one.count(
                f'aria-current="page" href="/documents/{item["intake_id"]}?page=1#mailbox-message-index"'
            ),
            2,
        )
        self.assertIn('aria-label="Mailbox message index page 2"', page_one)
        self.assertIn('id="mailbox-message-index"', page_one)
        self.assertNotIn("Mailbox page message 026", self._message_index_table(page_one))
        self.assertNotIn("Mailbox page message 025", self._message_index_table(page_two))

    def test_published_mbox_fifty_and_fifty_one_message_page_counts(self):
        fifty = self._published_numbered_mailbox(50)
        fifty_one = self._published_numbered_mailbox(51)
        page_two = documents.public_document_page(fifty["intake_id"], page="2").content
        middle = documents.public_document_page(fifty_one["intake_id"], page="2").content
        last = documents.public_document_page(fifty_one["intake_id"], page="3").content
        self.assertIn("Showing messages 26-50 of 50. Page 2 of 2.", page_two)
        self.assertIn("Showing messages 26-50 of 51. Page 2 of 3.", middle)
        self.assertIn("Showing messages 51-51 of 51. Page 3 of 3.", last)
        self.assertIn("Previous page", middle)
        self.assertIn("Next page", middle)
        self.assertNotIn("Next page", last)

    def test_published_mbox_invalid_page_inputs_are_bounded(self):
        item = self._published_numbered_mailbox(34)
        for value in (None, "0", "-2", "not-an-integer", "true", ["1", "2"]):
            with self.subTest(value=value):
                page = documents.public_document_page(item["intake_id"], page=value).content
                self.assertIn("Showing messages 1-25 of 34. Page 1 of 2.", page)
        clamped = documents.public_document_page(item["intake_id"], page="999999999").content
        self.assertIn("Showing messages 26-34 of 34. Page 2 of 2.", clamped)

    def test_published_mbox_detail_and_download_behaviour_are_unchanged_by_pagination(self):
        data = self._numbered_mbox(34)
        item = self._publish(self._store(data))
        page_one = documents.public_document_page(item["intake_id"], page="1").content
        self.assertIn(f'/documents/{item["intake_id"]}?message=1', page_one)
        self.assertIn(f'/documents/{item["intake_id"]}?message=25', page_one)
        self.assertNotIn(f'/documents/{item["intake_id"]}?message=26', page_one)
        detail = documents.public_document_page(item["intake_id"], message="26", page="2").content
        self.assertIn("Message Detail", detail)
        self.assertIn("Mailbox page message 026", detail)
        self.assertIn("Showing messages 26-34 of 34. Page 2 of 2.", detail)
        response = documents.public_document_download(item["intake_id"])
        self.assertEqual(response.media_type, "application/mbox")
        self.assertEqual(Path(response.path).read_bytes(), data)

    def test_published_mbox_pagination_preserves_publication_enforcement_and_archive_bytes(self):
        data = self._numbered_mbox(26)
        pending = self._store(data, title="Private pagination mailbox")
        with self.assertRaises(Exception):
            documents.public_document_page(pending["intake_id"], page="2")
        item = self._publish(pending)
        before = Path(intake_document_file(item["intake_id"], root=self.root)[0]).read_bytes()
        documents.public_document_page(item["intake_id"], page="2")
        after = Path(intake_document_file(item["intake_id"], root=self.root)[0]).read_bytes()
        self.assertEqual(before, data)
        self.assertEqual(after, data)

    def test_pending_mbox_private_admin_form_and_review_boundary(self):
        item = self._store()
        with self.assertRaises(Exception):
            documents.public_document_page(item["intake_id"])

        request = FakeRequest(
            cookies={
                admin_session.SESSION_COOKIE_NAME: admin_session.create_admin_session("mbox-admin")
            }
        )
        admin_page = admin_session.admin_document_intake_page(request).content
        self.assertIn("MBOX Mailbox Archive (.mbox)", admin_page)
        review_page = admin_session.admin_document_intake_preview_page(item["intake_id"], request).content
        self.assertIn("MBOX mailbox archives are preserved as original bytes", review_page)
        self.assertIn("MBOX Mailbox Archive", review_page)


if __name__ == "__main__":
    unittest.main()
