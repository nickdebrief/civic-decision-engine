import hashlib
import io
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from tests.test_admin_session import FakeRequest, install_fastapi_stubs

install_fastapi_stubs()

from api.archive_projection_access import (
    get_archive_thread,
    list_archive_folders,
    list_archive_messages,
    list_archive_threads,
    search_archive_projection,
)
from api.document_intake import (
    build_document_search_text,
    intake_document_file,
    is_gmail_takeout_document,
    store_pending_document,
    update_intake_status,
    validate_document_file,
)
from api.gmail_takeout import (
    GmailTakeoutError,
    GmailTakeoutParser,
    package_gmail_takeout_directory,
    project_gmail_takeout_document,
)
from api.mailbox_relationship_graph import build_gmail_takeout_relationship_graph
from api.outlook_archive_attachments import (
    build_outlook_attachment_promotion_provenance,
    list_outlook_attachments,
    validate_archive_attachment_promotion,
)
from api.outlook_archive_promotion import (
    build_outlook_message_promotion_provenance,
    validate_archive_message_promotion,
)
from api.routes import admin_session, documents


def _message(*, labels: str, suffix: str = "", attachment: bool = True) -> bytes:
    body = (
        b'MIME-Version: 1.0\nContent-Type: multipart/mixed; boundary="cde"\n\n'
        b"--cde\nContent-Type: text/plain; charset=utf-8\n\nGoverned Gmail body.\n"
    )
    if attachment:
        body += (
            b'--cde\nContent-Type: text/plain; name="evidence.txt"\n'
            b'Content-Disposition: attachment; filename="evidence.txt"\n'
            b"Content-Transfer-Encoding: base64\n\naGVsbG8=\n"
        )
    body += b"--cde--\n"
    return (
        f"From sender@example.com Mon Jan  1 12:00:00 2024\n"
        f"Subject: Governed Gmail message{suffix}\n"
        "From: Alice Example <alice@example.com>\n"
        "To: Bob Example <bob@example.org>\n"
        "Date: Mon, 1 Jan 2024 12:00:00 +0000\n"
        "Message-ID: <governed-gmail@example.com>\n"
        "References: <earlier@example.com>\n"
        f"X-Gmail-Labels: {labels}\n"
        "X-GM-THRID: 123456789\n"
    ).encode() + body


def _takeout_zip() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as package:
        package.writestr("Takeout/Mail/All mail Including Spam and Trash.mbox", _message(labels="Inbox,Important"))
        package.writestr("Takeout/Mail/Project.mbox", _message(labels="Project", suffix=" duplicate", attachment=False))
    return buffer.getvalue()


class GmailTakeoutSupportTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "pending"
        self.env = patch.dict(
            os.environ,
            {
                "ADMIN_USERNAME": "gmail-admin",
                "ADMIN_PASSWORD": "admin-password",
                "CDE_ADMIN_SESSION_SECRET": "session-secret",
                "CDE_DOCUMENT_INTAKE_ROOT": str(self.root),
            },
            clear=False,
        )
        self.env.start()
        session = admin_session.create_admin_session("gmail-admin")
        self.request = FakeRequest(cookies={admin_session.SESSION_COOKIE_NAME: session})
        self.archive_bytes = _takeout_zip()

    def tearDown(self):
        self.env.stop()
        self.temp_dir.cleanup()

    def _store(self):
        return store_pending_document(
            data=self.archive_bytes,
            original_filename="takeout.zip",
            content_type="application/octet-stream",
            title="Governed Gmail Takeout",
            institution_source="Example Institution",
            document_date="2024-01-01",
            category="Mailbox Archive",
            description="Preserved Gmail Takeout export.",
            visibility="private",
            notes="Private fixture.",
            actor="gmail-admin",
            root=self.root,
        )

    def _project(self):
        item = self._store()
        result = project_gmail_takeout_document(
            item["intake_id"], actor="gmail-admin", root=self.root
        )
        return item, result

    def test_zip_intake_preserves_exact_bytes_and_hashes(self):
        item = self._store()
        path, stored = intake_document_file(item["intake_id"], metadata=item, root=self.root)
        self.assertTrue(is_gmail_takeout_document(stored))
        self.assertEqual(path.read_bytes(), self.archive_bytes)
        self.assertEqual(item["sha256_hash"], hashlib.sha256(self.archive_bytes).hexdigest())
        self.assertEqual(item["sha512_hash"], hashlib.sha512(self.archive_bytes).hexdigest())
        self.assertEqual(item["gmail_takeout_metadata"]["parser_contract"], "ArchiveParser")
        self.assertIn("gmail takeout", build_document_search_text(item))

    def test_server_rejects_generic_zip_and_unsafe_directory_paths(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as package:
            package.writestr("unrelated.txt", "not Gmail")
        with self.assertRaisesRegex(ValueError, "gmail_takeout_mail_not_found"):
            validate_document_file(buffer.getvalue(), "fake.zip", "application/octet-stream")
        with self.assertRaises(GmailTakeoutError):
            package_gmail_takeout_directory([("../Takeout/Mail/Inbox.mbox", b"unsafe")])

    def test_extracted_directory_adapter_and_deterministic_envelope(self):
        entries = [("Takeout/Mail/Inbox.mbox", _message(labels="Inbox"))]
        first = package_gmail_takeout_directory(entries)
        second = package_gmail_takeout_directory(entries)
        self.assertEqual(first, second)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "Takeout" / "Mail"
            root.mkdir(parents=True)
            source = root / "Inbox.mbox"
            source.write_bytes(entries[0][1])
            parser = GmailTakeoutParser()
            self.assertTrue(parser.supports(Path(directory)))
            self.assertEqual(len(parser.project(Path(directory))["messages"]), 1)

    def test_projection_deduplicates_message_identity_and_preserves_labels_threads_and_body(self):
        item, result = self._project()
        projection = result["projection"]
        self.assertEqual(len(projection["messages"]), 1)
        message = projection["messages"][0]
        self.assertEqual(message["message_id"], "<governed-gmail@example.com>")
        self.assertEqual(message["thread_id"], "123456789")
        self.assertEqual(message["labels"], ["All mail Including Spam and Trash", "Important", "Inbox", "Project"])
        self.assertIn("Governed Gmail body", message["plain_text_preview"])
        self.assertEqual(len(projection["threads"]), 1)
        self.assertEqual(len(list_archive_messages(item["intake_id"], root=self.root)), 1)
        self.assertEqual(len(list_archive_folders(item["intake_id"], root=self.root)), 4)
        thread = get_archive_thread(item["intake_id"], "123456789", root=self.root)
        self.assertEqual(thread, list_archive_threads(item["intake_id"], root=self.root)[0])
        self.assertEqual(search_archive_projection(item["intake_id"], "Project", root=self.root)[0]["type"], "folder")

    def test_attachments_reuse_stage39e_identity_and_governance(self):
        item, result = self._project()
        attachments = list_outlook_attachments(item["intake_id"], root=self.root)
        self.assertEqual(len(attachments), 1)
        attachment = attachments[0]
        self.assertRegex(attachment["attachment_id"], r"^ATT-[A-F0-9]{24}$")
        self.assertEqual(attachment["sha256_hash"], hashlib.sha256(b"hello").hexdigest())
        self.assertEqual(attachment["provenance"]["archive_source"], "gmail_takeout")
        context = validate_archive_attachment_promotion(
            item["intake_id"], attachment["attachment_id"], root=self.root
        )
        provenance = build_outlook_attachment_promotion_provenance(
            context, administrator="gmail-admin", promoted_at="2024-01-02T00:00:00Z"
        )
        self.assertIn("123456789", provenance["provenance_chain"])
        self.assertEqual(result["projection"]["statistics"]["attachment_count"], 1)

    def test_message_promotion_uses_existing_workflow_with_complete_provenance(self):
        item, result = self._project()
        message = result["projection"]["messages"][0]
        context = validate_archive_message_promotion(
            item["intake_id"], message["projection_id"], root=self.root
        )
        provenance = build_outlook_message_promotion_provenance(
            context, administrator="gmail-admin", promoted_at="2024-01-02T00:00:00Z"
        )
        self.assertEqual(provenance["archive_source"], "gmail_takeout")
        self.assertEqual(provenance["thread_identifier"], "123456789")
        self.assertEqual(provenance["message_projection_id"], message["projection_id"])

    def test_private_graph_contains_archive_labels_threads_messages_and_attachments(self):
        item, result = self._project()
        graph = build_gmail_takeout_relationship_graph(
            item,
            result["projection"],
            list_outlook_attachments(item["intake_id"], root=self.root),
        )
        self.assertTrue(
            {"Intake Record", "Label", "Thread", "Email", "Attachment", "Person"}.issubset(
                {node["type"] for node in graph["nodes"]}
            )
        )
        self.assertTrue(
            {"Contains", "Labeled As", "In Thread", "Has Attachment"}.issubset(
                {edge["relationship_type"] for edge in graph["edges"]}
            )
        )
        api_graph = admin_session.admin_outlook_archive_attachment_graph_api(
            item["intake_id"], self.request
        )
        self.assertEqual(api_graph, graph)

    def test_admin_inspectors_show_private_projection_and_public_page_is_metadata_only(self):
        item, result = self._project()
        message = result["projection"]["messages"][0]
        page = admin_session.admin_outlook_archive_message_projection_page(
            item["intake_id"], message["projection_id"], self.request
        ).content
        self.assertIn("Governed Gmail body", page)
        self.assertIn("Promote to Canonical Record", page)
        self.assertIn("Labels", page)
        with self.assertRaises(Exception):
            admin_session.admin_outlook_archive_projection_api(item["intake_id"], FakeRequest())
        published = item
        for status in ("under_review", "approved", "published"):
            published = update_intake_status(
                item["intake_id"], status, actor="gmail-admin", root=self.root
            )
        public_page = documents._render_document(published)
        self.assertIn("Google Takeout Archive Overview", public_page)
        self.assertNotIn("Governed Gmail body", public_page)
        self.assertNotIn("evidence.txt", public_page)
        self.assertNotIn(f'/documents/{item["intake_id"]}/download', public_page)
        with self.assertRaises(Exception):
            documents.public_document_download(item["intake_id"])


if __name__ == "__main__":
    unittest.main()
