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
    load_pending_document,
    store_pending_document,
    update_intake_status,
)
from tests.test_admin_session import FakeFileResponse, FakeRequest, FakeUploadFile, install_fastapi_stubs

install_fastapi_stubs()

from api import record_document_associations as associations
from api.routes import admin_session, documents, records


PDF_BYTES = b"%PDF-1.7\nfixture\n%%EOF\n"
JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x02fixture\xff\xd9"
PNG_BYTES = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDRfixture"
M4A_BYTES = b"\x00\x00\x00\x18ftypM4A \x00\x00\x00\x00M4A fixture audio"
MP3_BYTES = b"ID3\x04\x00\x00\x00\x00\x00\x15fixture mp3 audio"
WAV_BYTES = b"RIFF\x24\x00\x00\x00WAVEfmt fixture wav audio"


class GovernedAudioArtefactSupportTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "intake"
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
        self.original_admin_db = admin_session.DB_PATH
        self.original_records_db = records.DB_PATH
        self.original_association_db = associations.DB_PATH
        admin_session.DB_PATH = self.db_path
        records.DB_PATH = self.db_path
        associations.DB_PATH = self.db_path
        self._init_records_db()
        session = admin_session.create_admin_session("admin-user")
        self.request = FakeRequest(cookies={admin_session.SESSION_COOKIE_NAME: session})

    def tearDown(self):
        admin_session.DB_PATH = self.original_admin_db
        records.DB_PATH = self.original_records_db
        associations.DB_PATH = self.original_association_db
        self.env.stop()
        self.temp_dir.cleanup()

    def _init_records_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """
            CREATE TABLE records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reference TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 1,
                supersedes TEXT,
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
                record_type TEXT
            )
            """
        )
        digest = hashlib.sha256(b"CMP-MC-20191202-001").hexdigest()
        conn.execute(
            """
            INSERT INTO records (
                reference, version, generated_at, trajectory, system_state,
                conditions_json, signals_json, finding, report_json, language,
                generated_by, verification_hash, exported_at, is_latest,
                source_narrative, record_type
            ) VALUES (
                'CMP-MC-20191202-001', 1, '2026-07-17T09:00:00Z',
                'Submitted', 'Complaint record context.', '[]', '[]',
                'Formal complaint submitted to the Medical Council of Ireland.',
                '{}', 'en', 'Civic Decision Engine', ?,
                '2026-07-17T10:00:00Z', 1, '', 'complaint'
            )
            """,
            (digest,),
        )
        conn.commit()
        conn.close()

    def _publish(self, intake_id: str):
        for status, timestamp in (
            ("under_review", "2026-07-17T10:00:00Z"),
            ("approved", "2026-07-17T11:00:00Z"),
            ("published", "2026-07-17T12:00:00Z"),
        ):
            update_intake_status(
                intake_id,
                status,
                actor="admin-user",
                note=f"Move to {status}.",
                changed_at=timestamp,
                root=self.root,
            )

    def _store_audio(self, *, data=M4A_BYTES, filename="AUD-20190719-WA0012.m4a", content_type="audio/x-m4a", publish=True):
        item = store_pending_document(
            data=data,
            original_filename=filename,
            content_type=content_type,
            title="Audio Recording — Yoga — Bon Secours Pain Medicine",
            institution_source="Bon Secours Hospital Pain Medicine",
            document_date="2019-07-19",
            category="Audio Recording",
            description=(
                "Original audio recording referenced in the email dated 29 July "
                "2019 and preserved in its original format."
            ),
            visibility="private",
            notes="Preserved as an original audio artefact.",
            reference_identifier="NM-AUDIO-20190719-001",
            keywords=(
                "Medical Council, Bon Secours, Dominic Harmon, Bridget, "
                "Audio Recording, Yoga, Pain Medicine, 2019"
            ),
            actor="admin-user",
            uploaded_at="2026-07-17T09:00:00Z",
            root=self.root,
        )
        if publish:
            self._publish(item["intake_id"])
        return load_pending_document(item["intake_id"], root=self.root)

    def test_valid_audio_intake_preserves_original_bytes_type_filename_and_sha(self):
        cases = (
            ("AUD-20190719-WA0012.m4a", "audio/x-m4a", M4A_BYTES, "m4a", "M4A", "audio/mp4"),
            ("recording.mp3", "audio/mpeg", MP3_BYTES, "mp3", "MP3", "audio/mpeg"),
            ("recording.wav", "audio/x-wav", WAV_BYTES, "wav", "WAV", "audio/wav"),
        )
        for filename, content_type, data, document_type, label, media_type in cases:
            with self.subTest(filename=filename):
                item = store_pending_document(
                    data=data,
                    original_filename=filename,
                    content_type=content_type,
                    title=f"{label} Audio",
                    institution_source="Bon Secours Hospital Pain Medicine",
                    document_date="2019-07-19",
                    category="Audio Recording",
                    description="Original governed audio artefact.",
                    visibility="private",
                    notes="Private note.",
                    actor="admin-user",
                    root=self.root,
                )
                digest = hashlib.sha256(data).hexdigest()
                self.assertEqual(item["document_type"], document_type)
                self.assertEqual(item["document_format"], label)
                self.assertEqual(item["content_type"], media_type)
                self.assertEqual(item["sha256_hash"], digest)
                self.assertEqual(item["original_filename"], filename)
                self.assertEqual(Path(item["proposed_storage_location"]).read_bytes(), data)

    def test_audio_upload_rejects_unsupported_and_mismatched_types(self):
        for filename, data, error in (
            ("audio.aac", M4A_BYTES, "document_intake_file_type_not_allowed"),
            ("audio.m4a", b"not audio", "document_intake_file_type_not_allowed"),
            ("audio.mp3", M4A_BYTES, "document_intake_file_type_mismatch"),
            ("audio.wav", MP3_BYTES, "document_intake_file_type_mismatch"),
            ("audio.m4a", PDF_BYTES, "document_intake_file_type_mismatch"),
            ("video-renamed.m4a", b"\x00\x00\x00\x18ftypisom\x00\x00\x00\x00", "document_intake_file_type_not_allowed"),
        ):
            with self.subTest(filename=filename):
                with self.assertRaisesRegex(ValueError, error):
                    store_pending_document(
                        data=data,
                        original_filename=filename,
                        content_type="application/octet-stream",
                        title="Rejected audio",
                        institution_source="Civic Office",
                        document_date="2019-07-19",
                        category="Audio Recording",
                        description="Rejected.",
                        visibility="private",
                        notes="Private note.",
                        root=self.root,
                    )

    def test_existing_pdf_jpeg_and_png_intake_remains_supported(self):
        for filename, data, content_type, expected in (
            ("file.pdf", PDF_BYTES, "application/pdf", "pdf"),
            ("image.jpg", JPEG_BYTES, "image/jpeg", "jpeg"),
            ("image.png", PNG_BYTES, "image/png", "png"),
        ):
            with self.subTest(filename=filename):
                item = store_pending_document(
                    data=data,
                    original_filename=filename,
                    content_type=content_type,
                    title="Existing format",
                    institution_source="Civic Office",
                    document_date="2026-07-17",
                    category="Decision",
                    description="Existing format regression.",
                    visibility="private",
                    notes="Private note.",
                    root=self.root,
                )
                self.assertEqual(item["document_type"], expected)

    def test_audio_lifecycle_public_page_search_view_and_download(self):
        item = self._store_audio()
        content = str(documents.public_document_page(item["intake_id"]).content)
        self.assertIn("Audio Recording — Yoga — Bon Secours Pain Medicine", content)
        self.assertIn("<td>M4A</td>", content)
        self.assertIn("<td>Audio</td>", content)
        self.assertIn('class="public-document-audio"', content)
        self.assertIn('preload="metadata"', content)
        self.assertIn(f'/documents/{item["intake_id"]}/view', content)
        self.assertIn("Download original audio", content)
        self.assertIn(item["sha256_hash"], content)
        self.assertIn("Publication Provenance", content)

        for query in ("Yoga", "Dominic Harmon", "Audio Recording", "Bon Secours", "NM-AUDIO-20190719-001"):
            with self.subTest(query=query):
                response = documents.public_document_library(
                    q=query,
                    institution=None,
                    category=None,
                    publication_year=None,
                )
                self.assertIn("Audio Recording — Yoga", str(response.content))

        view = documents.public_document_image_view(item["intake_id"])
        self.assertIsInstance(view, FakeFileResponse)
        self.assertEqual(view.media_type, "audio/mp4")
        self.assertEqual(Path(view.path).read_bytes(), M4A_BYTES)
        self.assertIn("inline", view.headers.get("Content-Disposition", ""))
        self.assertEqual(view.headers.get("X-Content-Type-Options"), "nosniff")

        download = documents.public_document_download(item["intake_id"])
        self.assertEqual(download.media_type, "audio/mp4")
        self.assertEqual(download.filename, "AUD-20190719-WA0012.m4a")
        self.assertEqual(Path(download.path).read_bytes(), M4A_BYTES)
        self.assertIn("attachment", download.headers.get("Content-Disposition", ""))

    def test_private_audio_is_not_publicly_available(self):
        item = self._store_audio(publish=False)
        with self.assertRaises(Exception):
            documents.public_document_page(item["intake_id"])
        with self.assertRaises(Exception):
            documents.public_document_image_view(item["intake_id"])
        with self.assertRaises(Exception):
            documents.public_document_download(item["intake_id"])

    def test_audio_is_discoverable_in_association_selector_by_keyword_and_reference(self):
        item = self._store_audio()
        self.assertIn("yoga", build_document_search_text(item))
        self.assertEqual(document_media_type(item), "audio/mp4")
        content = str(admin_session.admin_association_new_page(self.request).content)
        self.assertIn("Audio Recording — Yoga — Bon Secours Pain Medicine", content)
        self.assertIn("NM-AUDIO-20190719-001", content)
        option_start = content.index(f'value="{item["intake_id"]}"')
        option_end = content.index("</option>", option_start)
        option = content[option_start:option_end]
        self.assertIn("yoga", option)
        self.assertIn("M4A", option)

    def test_audio_can_be_linked_to_canonical_record_without_hash_changes(self):
        item = self._store_audio()
        before_hash = item["sha256_hash"]
        response = admin_session.admin_association_create(
            self.request,
            record_reference="CMP-MC-20191202-001",
            document_id=item["intake_id"],
            relationship_type="supporting_document",
            public_label="Supporting audio recording",
            public_note="Published audio recording preserved as a contemporaneous artefact.",
            admin_note="Created explicit governed association for audio artefact.",
            is_public="1",
        )
        self.assertEqual(response.status_code, 201)
        loaded = load_pending_document(item["intake_id"], root=self.root)
        self.assertEqual(loaded["sha256_hash"], before_hash)
        conn = sqlite3.connect(self.db_path)
        try:
            row = conn.execute(
                "SELECT document_id, record_reference FROM record_document_associations"
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(row[0], item["intake_id"])
        self.assertEqual(row[1], "CMP-MC-20191202-001")


if __name__ == "__main__":
    unittest.main()
