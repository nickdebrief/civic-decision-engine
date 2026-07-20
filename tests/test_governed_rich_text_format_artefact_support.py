import hashlib
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from api.document_intake import (
    build_document_search_text,
    document_media_type,
    intake_document_file,
    is_rich_text_document,
    store_pending_document,
    update_intake_status,
    validate_document_file,
)
from tests.test_admin_session import FakeRequest, install_fastapi_stubs

install_fastapi_stubs()

from api import archive_collection_memberships as acm
from api import archive_collections as ac
from api import record_document_associations as rda
from api.routes import (
    admin_session,
    archive,
    associations as association_routes,
    collections as collection_routes,
    documents,
)


RTF_BYTES = b"{\\rtf1\\ansi\\deff0 {\\fonttbl {\\f0 Arial;}}\\f0\\fs24 Reply email preserved as a local note.}"
RTF_WITH_BOM_AND_SPACE = b"\xef\xbb\xbf \r\n\t{\\rtf1\\ansi Redacted reply email.}"
PDF_BYTES = b"%PDF-1.7\nrtf regression\n%%EOF\n"
JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01rtf-regression\xff\xd9"
PNG_BYTES = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDRrtf-regression"
M4A_BYTES = b"\x00\x00\x00\x18ftypM4A \x00\x00\x00\x00audio"
MP3_BYTES = b"ID3\x04\x00\x00\x00\x00\x00\x15audio"
WAV_BYTES = b"RIFF\x24\x00\x00\x00WAVEfmt audio"


class GovernedRichTextFormatArtefactSupportTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "pending"
        self.db_path = Path(self.temp_dir.name) / "records.db"
        self.env = patch.dict(
            os.environ,
            {
                "ADMIN_USERNAME": "admin-user",
                "ADMIN_PASSWORD": "admin-password",
                "CDE_ADMIN_SESSION_SECRET": "session-secret",
                "CDE_DOCUMENT_INTAKE_ROOT": str(self.root),
                "RECORDS_DB_PATH": str(self.db_path),
            },
            clear=False,
        )
        self.env.start()
        self.originals = (
            admin_session.DB_PATH,
            ac.DB_PATH,
            rda.DB_PATH,
            archive.records.DB_PATH,
        )
        admin_session.DB_PATH = self.db_path
        ac.DB_PATH = self.db_path
        rda.DB_PATH = self.db_path
        archive.records.DB_PATH = self.db_path
        self.request = FakeRequest(
            cookies={
                admin_session.SESSION_COOKIE_NAME: admin_session.create_admin_session(
                    "admin-user"
                )
            }
        )
        self._init_records()

    def tearDown(self):
        (
            admin_session.DB_PATH,
            ac.DB_PATH,
            rda.DB_PATH,
            archive.records.DB_PATH,
        ) = self.originals
        self.env.stop()
        self.temp_dir.cleanup()

    def _init_records(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """
            CREATE TABLE records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reference TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 1,
                generated_at TEXT NOT NULL,
                trajectory TEXT,
                system_state TEXT,
                conditions_json TEXT,
                signals_json TEXT,
                finding TEXT,
                report_json TEXT,
                language TEXT NOT NULL DEFAULT 'en',
                generated_by TEXT NOT NULL DEFAULT 'Civic Decision Engine',
                verification_hash TEXT NOT NULL,
                exported_at TEXT NOT NULL,
                is_latest INTEGER NOT NULL DEFAULT 1,
                source_narrative TEXT,
                record_type TEXT,
                record_title TEXT,
                institution TEXT,
                event_date TEXT,
                summary TEXT
            )
            """
        )
        digest = hashlib.sha256(b"CMP-MC-20191202-001").hexdigest()
        conn.execute(
            """
            INSERT INTO records (
                reference, generated_at, trajectory, system_state,
                conditions_json, signals_json, finding, report_json, language,
                generated_by, verification_hash, exported_at, is_latest,
                source_narrative, record_type, record_title, institution,
                event_date, summary
            ) VALUES (
                'CMP-MC-20191202-001', '2026-07-25T09:00:00Z',
                'Submitted', 'Published complaint record.', '[]', '[]',
                'Formal complaint submitted to the Medical Council of Ireland.',
                '{}', 'en', 'Civic Decision Engine', ?,
                '2026-07-25T10:00:00Z', 1, '', 'complaint',
                'Initial Complaint to the Medical Council of Ireland',
                'Medical Council of Ireland', '2019-12-02',
                'Formal complaint submitted to the Medical Council of Ireland.'
            )
            """,
            (digest,),
        )
        conn.commit()
        conn.close()

    def _metadata(self, **overrides):
        data = {
            "original_filename": "Reply_Email_Local_Note.rtf",
            "content_type": "application/rtf",
            "title": "Reply Email Local Note",
            "institution_source": "Medical Council of Ireland",
            "document_date": "2019-12-02",
            "category": "Correspondence",
            "description": "Original reply email preserved as a local Rich Text Format note.",
            "visibility": "private",
            "notes": "Private RTF intake note.",
            "reference_identifier": "NM-RTF-REPLY-20191202-001",
            "keywords": "Medical Council, Reply Email, Rich Text, 2019",
            "actor": "admin-user",
            "root": self.root,
        }
        data.update(overrides)
        return data

    def _store(self, data=RTF_BYTES, **overrides):
        return store_pending_document(data=data, **self._metadata(**overrides))

    def _publish(self, item):
        for status in ("under_review", "approved", "published"):
            item = update_intake_status(
                item["intake_id"],
                status,
                actor="admin-user",
                note=f"{status} note",
                root=self.root,
            )
        return item

    def test_valid_rtf_upload_preserves_original_bytes_type_filename_and_sha(self):
        for content_type in ("application/rtf", "text/rtf", "application/x-rtf"):
            with self.subTest(content_type=content_type):
                data = RTF_BYTES + content_type.encode("ascii")
                item = self._store(data, content_type=content_type)
                digest = hashlib.sha256(data).hexdigest()

                self.assertEqual(item["document_type"], "rtf")
                self.assertEqual(item["document_format"], "RTF")
                self.assertEqual(item["content_type"], "application/rtf")
                self.assertEqual(item["media_family"], "rich_text")
                self.assertEqual(item["sha256_hash"], digest)
                self.assertEqual(item["original_filename"], "Reply_Email_Local_Note.rtf")
                self.assertTrue(is_rich_text_document(item))
                self.assertEqual(document_media_type(item), "application/rtf")
                file_path, _ = intake_document_file(item["intake_id"], root=self.root)
                self.assertEqual(Path(file_path).read_bytes(), data)

    def test_rtf_header_validation_accepts_safe_variants_and_rejects_masquerades(self):
        self.assertEqual(
            validate_document_file(RTF_WITH_BOM_AND_SPACE, "note.rtf", "text/rtf")[0],
            "rtf",
        )
        for data, filename, error in (
            (b"", "empty.rtf", "document_intake_file_required"),
            (b"plain text", "plain.rtf", "document_intake_file_type_not_allowed"),
            (PDF_BYTES, "renamed.rtf", "document_intake_file_type_mismatch"),
            (b"MZ\x00\x00binary", "binary.rtf", "document_intake_file_type_not_allowed"),
            (b"{\\foo1 not rtf}", "malformed.rtf", "document_intake_file_type_not_allowed"),
            (b"{\\rtf", "missing-close.rtf", "document_intake_file_type_not_allowed"),
            (RTF_BYTES, "wrong.pdf", "document_intake_file_type_mismatch"),
        ):
            with self.subTest(filename=filename):
                with self.assertRaisesRegex(ValueError, error):
                    validate_document_file(data, filename, "application/rtf")

    def test_rtf_lifecycle_public_page_download_library_archive_and_association(self):
        item = self._publish(self._store())
        page = documents.public_document_page(item["intake_id"]).content
        self.assertIn("Rich Text Format Artefact", page)
        self.assertIn("Download original RTF", page)
        self.assertIn("<td>RTF</td>", page)
        self.assertIn("<td>Rich Text</td>", page)
        self.assertIn(item["sha256_hash"], page)
        self.assertIn("Publication Provenance", page)
        self.assertNotIn("Private RTF intake note", page)

        download = documents.public_document_download(item["intake_id"])
        self.assertEqual(download.media_type, "application/rtf")
        self.assertIn("attachment", download.headers["Content-Disposition"])
        self.assertEqual(download.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(Path(download.path).read_bytes(), RTF_BYTES)

        searchable = build_document_search_text(item)
        self.assertIn("rich text", searchable)
        self.assertIn("reply email", searchable)
        self.assertIn(item["reference_identifier"], documents.public_document_library(q="NM-RTF-REPLY").content)
        self.assertIn(item["title"], documents.public_document_library(q="Rich Text").content)
        self.assertIn(item["title"], archive.public_archive_explorer(media="rich_text").content)
        self.assertIn(item["title"], archive.public_archive_explorer(search="rtf").content)

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            association = rda.create_association(
                conn,
                record_reference="CMP-MC-20191202-001",
                document_id=item["intake_id"],
                relationship_type="supporting_document",
                public_label="Supporting RTF note",
                public_note="Published RTF artefact preserved as a governed source note.",
                admin_note="Private association note.",
                is_public=True,
                actor="admin-user",
                root=self.root,
            )
            collection = ac.create_collection(
                conn,
                title="RTF Collection",
                subtitle="Rich Text member",
                institution_source="Medical Council of Ireland",
                category="documentary_archive",
                description="Collection including an RTF artefact.",
                public_note="Public collection note.",
                admin_note="Private collection note.",
                date_from="2019-12-02",
                date_to=None,
                is_public=True,
                actor="admin-user",
            )
            membership = acm.create_membership(
                conn,
                collection_id=collection["id"],
                document_id=item["intake_id"],
                actor="admin-user",
                membership_note="RTF membership.",
                display_sequence=1,
                root=self.root,
            )
            for status in ("reviewed", "approved", "active"):
                acm.transition_membership(
                    conn,
                    membership["membership_reference"],
                    new_status=status,
                    actor="admin-user",
                    root=self.root,
                )
        finally:
            conn.close()

        association_page = association_routes.public_association_page(
            association["public_reference"]
        ).content
        self.assertIn("Supporting RTF note", association_page)
        self.assertIn(item["title"], association_page)
        self.assertIn("RTF", association_page)
        collection_page = collection_routes.public_collection_page(collection["public_reference"]).content
        self.assertIn("Governed Collection Members", collection_page)
        self.assertIn(item["title"], collection_page)
        self.assertIn("RTF", collection_page)

    def test_unpublished_rtf_is_not_publicly_accessible(self):
        item = self._store()
        with self.assertRaises(Exception) as page_ctx:
            documents.public_document_page(item["intake_id"])
        self.assertEqual(getattr(page_ctx.exception, "status_code", None), 404)
        self.assertNotIn(item["title"], documents.public_document_library(q="Reply Email").content)

    def test_existing_supported_formats_remain_accepted(self):
        cases = (
            (PDF_BYTES, "document.pdf", "application/pdf", "pdf"),
            (JPEG_BYTES, "image.jpg", "image/jpeg", "jpeg"),
            (PNG_BYTES, "image.png", "image/png", "png"),
            (M4A_BYTES, "audio.m4a", "audio/mp4", "m4a"),
            (MP3_BYTES, "audio.mp3", "audio/mpeg", "mp3"),
            (WAV_BYTES, "audio.wav", "audio/wav", "wav"),
        )
        for data, filename, content_type, expected in cases:
            with self.subTest(filename=filename):
                detected, _media_type, _safe_filename = validate_document_file(
                    data, filename, content_type
                )
                self.assertEqual(detected, expected)

    def test_admin_upload_form_lists_rich_text_format(self):
        content = admin_session.admin_document_intake_page(self.request).content
        self.assertIn(".rtf", content)
        self.assertIn("application/rtf", content)
        self.assertIn("Rich Text Format (.rtf)", content)


if __name__ == "__main__":
    unittest.main()
