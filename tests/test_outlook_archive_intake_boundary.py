import hashlib
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
    is_outlook_archive_document,
    store_pending_document,
    update_intake_status,
    validate_document_file,
)
from tests.test_admin_session import FakeRequest, install_fastapi_stubs

install_fastapi_stubs()

from api.public_document_preview import render_public_document_preview
from api.routes import admin_session, archive, documents


PST_BYTES = b"CDE Platform Stage 39A preserved PST boundary bytes.\x00\x01outlook archive"
OST_BYTES = b"CDE Platform Stage 39A preserved OST boundary bytes.\x02\x03offline archive"


class OutlookArchiveIntakeBoundaryTests(unittest.TestCase):
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
            },
            clear=False,
        )
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp_dir.cleanup()

    def _store(self, data: bytes = PST_BYTES, **overrides):
        values = {
            "data": data,
            "original_filename": "outlook-archive.pst",
            "content_type": "application/octet-stream",
            "title": "Preserved Outlook Archive",
            "institution_source": "Civic Outlook Source",
            "document_date": "2026-07-29",
            "category": "Outlook Archive",
            "description": "Native Outlook archive preserved as a governed evidence object.",
            "visibility": "private",
            "notes": "Private Outlook archive intake note.",
            "reference_identifier": "OUTLOOK-ARCHIVE-001",
            "keywords": "pst, outlook, archive",
            "actor": "archive-admin",
            "uploaded_at": "2026-07-29T10:00:00Z",
            "root": self.root,
        }
        values.update(overrides)
        return store_pending_document(**values)

    def _publish(self, item):
        for status, timestamp in (
            ("under_review", "2026-07-29T11:00:00Z"),
            ("approved", "2026-07-29T12:00:00Z"),
            ("published", "2026-07-29T13:00:00Z"),
        ):
            item = update_intake_status(
                item["intake_id"],
                status,
                actor="archive-admin",
                note=f"{status} note",
                changed_at=timestamp,
                root=self.root,
            )
        return item

    def test_validate_document_file_accepts_pst_and_ost_extensions_without_parser(self):
        self.assertEqual(
            validate_document_file(PST_BYTES, "mailbox.pst", "application/octet-stream"),
            ("pst", "application/vnd.ms-outlook-pst", "mailbox.pst"),
        )
        self.assertEqual(
            validate_document_file(OST_BYTES, "mailbox.ost", "application/octet-stream"),
            ("ost", "application/vnd.ms-outlook-ost", "mailbox.ost"),
        )
        with self.assertRaisesRegex(ValueError, "document_intake_file_required"):
            validate_document_file(b"", "empty.pst", "application/vnd.ms-outlook-pst")
        with self.assertRaisesRegex(ValueError, "document_intake_file_type_not_allowed"):
            validate_document_file(PST_BYTES, "mailbox.pdf", "application/pdf")

    def test_pst_intake_preserves_bytes_hashes_and_parser_boundary(self):
        item = self._store()

        self.assertEqual(item["document_type"], "pst")
        self.assertEqual(item["document_format"], "Microsoft Outlook Personal Storage Archive")
        self.assertEqual(item["media_family"], "mailbox")
        self.assertEqual(item["sha256_hash"], hashlib.sha256(PST_BYTES).hexdigest())
        self.assertEqual(item["sha512_hash"], hashlib.sha512(PST_BYTES).hexdigest())
        self.assertTrue(is_outlook_archive_document(item))
        self.assertFalse(is_mailbox_document(item))
        self.assertEqual(document_media_type(item), "application/vnd.ms-outlook-pst")
        self.assertNotIn("email_metadata", item)
        metadata = item["outlook_archive_metadata"]
        self.assertEqual(metadata["archive_type"], "PST")
        self.assertEqual(metadata["parser_status"], "parser_not_configured")
        self.assertEqual(metadata["parser_status_message"], "Parser not configured.")
        self.assertFalse(metadata["mailbox_discovery_performed"])
        self.assertFalse(metadata["message_extraction_performed"])
        self.assertFalse(metadata["canonical_record_generation_performed"])
        file_path, _metadata = intake_document_file(item["intake_id"], root=self.root)
        self.assertEqual(Path(file_path).read_bytes(), PST_BYTES)

    def test_ost_intake_records_offline_storage_archive_type(self):
        item = self._store(
            OST_BYTES,
            original_filename="offline-cache.ost",
            content_type="application/vnd.ms-outlook-ost",
            keywords="ost, outlook",
        )

        self.assertEqual(item["document_type"], "ost")
        self.assertEqual(item["document_format"], "Microsoft Outlook Offline Storage Archive")
        self.assertEqual(item["outlook_archive_metadata"]["archive_type"], "OST")
        self.assertEqual(item["sha512_hash"], hashlib.sha512(OST_BYTES).hexdigest())
        self.assertEqual(document_media_type(item), "application/vnd.ms-outlook-ost")

    def test_admin_intake_accept_notice_and_preview_include_outlook_archives(self):
        request = FakeRequest(
            cookies={
                admin_session.SESSION_COOKIE_NAME: admin_session.create_admin_session("archive-admin")
            }
        )
        page = admin_session.admin_document_intake_page(request).content
        accept_values = admin_session.DOCUMENT_INTAKE_FILE_ACCEPT.split(",")

        for value in (
            ".pst",
            "application/vnd.ms-outlook-pst",
            "application/x-pst",
            ".ost",
            "application/vnd.ms-outlook-ost",
            "application/x-ost",
            ".eml",
            ".msg",
            ".emlx",
            ".mbox",
        ):
            self.assertIn(value, accept_values)
        self.assertIn("Microsoft Outlook Personal Storage Archive (.pst)", page)
        self.assertIn("Microsoft Outlook Offline Storage Archive (.ost)", page)

        item = self._store()
        preview = admin_session.admin_document_intake_preview_page(
            item["intake_id"], request
        ).content
        self.assertIn("SHA-512", preview)
        self.assertIn("Parser not configured.", preview)
        self.assertIn("Not performed in CDE Platform Stage 39B", preview)
        self.assertIn("does not expose mailbox contents, extract messages", preview)

    def test_published_outlook_archive_public_page_preview_endpoints_and_download(self):
        item = self._publish(self._store())

        page = documents.public_document_page(item["intake_id"]).content
        self.assertIn("Outlook Archive Overview", page)
        self.assertIn("Microsoft Outlook PST and OST archives are preserved as original bytes", page)
        self.assertIn("SHA-512 digest", page)
        self.assertIn("Parser not configured.", page)
        self.assertIn("Download original .pst", page)
        self.assertNotIn("Mailbox Message Index", page)
        self.assertNotIn("Relationship Graph", page)

        preview = render_public_document_preview(item, root=self.root)
        self.assertIn("Outlook Archive", preview)
        self.assertIn("Open Outlook Archive", preview)

        metadata_payload = archive.public_outlook_archive_metadata(item["intake_id"])
        self.assertEqual(metadata_payload["archive_type"], "PST")
        self.assertEqual(metadata_payload["sha512_hash"], item["sha512_hash"])
        self.assertFalse(metadata_payload["message_extraction_performed"])
        status_payload = archive.public_outlook_archive_status(item["intake_id"])
        self.assertEqual(status_payload["parser_status"], "parser_not_configured")
        self.assertFalse(status_payload["mailbox_discovery_performed"])

        file_path, _metadata = intake_document_file(item["intake_id"], root=self.root)
        self.assertEqual(Path(file_path).read_bytes(), PST_BYTES)

    def test_outlook_archive_search_includes_safe_boundary_metadata(self):
        item = self._store()
        search_text = build_document_search_text(item)

        self.assertIn("preserved outlook archive", search_text)
        self.assertIn("microsoft outlook personal storage", search_text)
        self.assertIn("parser_not_configured", search_text)
        self.assertIn("parser not configured.", search_text)


if __name__ == "__main__":
    unittest.main()
