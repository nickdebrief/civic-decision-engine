import hashlib
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from api.document_intake import (
    find_document_by_reference,
    list_published_documents,
    load_pending_document,
    load_published_document,
    prepare_intake_status_transition,
    store_pending_document,
    store_private_original_source_media,
)
from tests.test_admin_session import FakeRequest, FakeUploadFile, install_fastapi_stubs

install_fastapi_stubs()

from api import record_document_associations as associations
from api.routes import admin_session, documents, records


M4A_BYTES = b"\x00\x00\x00\x18ftypM4A \x00\x00\x00\x00synthetic m4a"
MP3_BYTES = b"ID3\x04\x00\x00\x00\x00\x00\x15synthetic mp3"
WAV_BYTES = b"RIFF\x24\x00\x00\x00WAVEfmt synthetic wav"
MP4_BYTES = b"\x00\x00\x00\x18ftypisom\x00\x00\x00\x00synthetic mp4"


class PrivateOriginalSourceMediaTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "intake"
        self.db_path = Path(self.temp_dir.name) / "records.db"
        self.env = patch.dict(
            os.environ,
            {"CDE_DOCUMENT_INTAKE_ROOT": str(self.root), "RECORDS_DB_PATH": str(self.db_path)},
            clear=False,
        )
        self.env.start()
        self.original_admin_db = admin_session.DB_PATH
        self.original_records_db = records.DB_PATH
        self.original_association_db = associations.DB_PATH
        admin_session.DB_PATH = self.db_path
        records.DB_PATH = self.db_path
        associations.DB_PATH = self.db_path
        sqlite3.connect(self.db_path).close()

    def tearDown(self):
        admin_session.DB_PATH = self.original_admin_db
        records.DB_PATH = self.original_records_db
        associations.DB_PATH = self.original_association_db
        self.env.stop()
        self.temp_dir.cleanup()

    def _store(self, *, data=MP4_BYTES, filename="source.mp4", content_type="video/mp4", **overrides):
        values = {
            "data": data,
            "original_filename": filename,
            "content_type": content_type,
            "title": "Synthetic private original",
            "institution_source": "Operator-supplied source",
            "document_date": "2026-10-10",
            "category": "Private original source media",
            "description": "Synthetic fixture only.",
            "notes": "Private only.",
            "source_platform": None,
            "source_account": None,
            "source_url": None,
            "source_publication_date": None,
            "source_publication_date_precision": "unknown",
            "operator_capture_date": "2026-10-10",
            "operator_capture_date_precision": "day",
            "source_completeness": "unknown",
            "root": self.root,
        }
        values.update(overrides)
        return store_private_original_source_media(**values)

    def test_supported_media_preserves_exact_bytes_digest_and_private_source_identity(self):
        cases = (
            ("source.m4a", "audio/mp4", M4A_BYTES, "m4a"),
            ("source.mp3", "audio/mpeg", MP3_BYTES, "mp3"),
            ("source.wav", "audio/wav", WAV_BYTES, "wav"),
            ("source.mp4", "video/mp4", MP4_BYTES, "mp4"),
        )
        for filename, content_type, data, document_type in cases:
            with self.subTest(filename=filename):
                item = self._store(data=data, filename=filename, content_type=content_type)
                private = item["private_original_source_media"]
                self.assertEqual(item["document_type"], document_type)
                self.assertEqual(item["sha256_hash"], hashlib.sha256(data).hexdigest())
                self.assertEqual(
                    Path(item["proposed_storage_location"]).read_bytes(), data
                )
                self.assertEqual(
                    private["original_source_identity"],
                    f"source-sha256:{item['sha256_hash']}",
                )
                self.assertIsNone(private["derivative_of_original_source_identity"])
                self.assertEqual(item["visibility"], "private")

    def test_unknown_and_known_provenance_remain_explicit_and_dates_stay_distinct(self):
        item = self._store(
            source_platform="Example Platform",
            source_account="example-account",
            source_url="https://example.invalid/source/1",
            source_publication_date="2024-02",
            source_publication_date_precision="month",
            operator_capture_date="2026-10-10T09:30:00Z",
            operator_capture_date_precision="timestamp",
            source_completeness="excerpt",
            uploaded_at="2026-10-10T10:00:00Z",
        )
        details = item["private_original_source_media"]
        self.assertEqual(details["source_platform"], {"known": True, "value": "Example Platform"})
        self.assertEqual(details["source_publication_date"], {"precision": "month", "value": "2024-02"})
        self.assertEqual(details["operator_capture_date"], {"precision": "timestamp", "value": "2026-10-10T09:30:00Z"})
        self.assertEqual(details["source_completeness"], "excerpt")
        self.assertEqual(item["upload_date"], "2026-10-10T10:00:00Z")
        unknown = self._store(data=MP3_BYTES, filename="unknown.mp3", content_type="audio/mpeg")
        self.assertEqual(unknown["private_original_source_media"]["source_url"], {"known": False, "value": None})

    def test_metadata_and_mp4_signature_validation_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "private_source_media_source_publication_date_invalid"):
            self._store(source_publication_date="2024-02", source_publication_date_precision="day")
        with self.assertRaisesRegex(ValueError, "private_source_media_completeness_invalid"):
            self._store(source_completeness="partial")
        with self.assertRaisesRegex(ValueError, "document_intake_file_type_not_allowed"):
            self._store(data=b"\x00\x00\x00\x18ftypqt  synthetic", filename="source.mp4")
        with self.assertRaisesRegex(ValueError, "document_intake_file_type_not_allowed"):
            self._store(data=MP4_BYTES, filename="source.m4a", content_type="audio/mp4")

    def test_private_source_rejects_non_media_without_creating_an_intake_directory(self):
        with self.assertRaisesRegex(ValueError, "private_source_media_type_not_allowed"):
            self._store(
                data=b"%PDF-1.7\nsynthetic\n%%EOF\n",
                filename="source.pdf",
                content_type="application/pdf",
            )
        self.assertFalse(self.root.exists())

    def test_limit_is_the_existing_twenty_five_mib_guard(self):
        with patch.dict(os.environ, {"CDE_DOCUMENT_INTAKE_MAX_BYTES": "1"}, clear=False):
            with self.assertRaisesRegex(ValueError, "document_intake_file_too_large"):
                self._store()

    def test_private_subtype_cannot_publish_or_reach_public_listing_association_view_or_download(self):
        item = self._store()
        with self.assertRaisesRegex(ValueError, "private_source_media_publication_forbidden"):
            prepare_intake_status_transition(
                item["intake_id"], "published", note="Attempt publication.", root=self.root
            )

        # Synthetic corruption must not bypass the independent public readers.
        metadata_path = self.root / item["intake_id"] / "metadata.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata["status"] = "published"
        metadata["publication_date"] = "2026-10-10T11:00:00Z"
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

        self.assertNotIn(item["intake_id"], {row["intake_id"] for row in list_published_documents(root=self.root)})
        self.assertIsNone(find_document_by_reference(item["intake_id"], root=self.root, published_only=True))
        self.assertIsNone(associations.published_document_context(item["intake_id"], root=self.root))
        with self.assertRaisesRegex(ValueError, "public_document_not_found"):
            load_published_document(item["intake_id"], root=self.root)
        for handler in (
            documents.public_document_page,
            documents.public_document_image_view,
            documents.public_document_download,
        ):
            with self.subTest(handler=handler.__name__), self.assertRaises(Exception):
                handler(item["intake_id"])

    def test_private_source_upload_endpoint_requires_admin_session(self):
        with self.assertRaises(Exception):
            admin_session.admin_private_original_source_media_upload(
                FakeRequest(),
                title="Synthetic",
                institution_source="Operator",
                document_date="2026-10-10",
                category="Private original source media",
                description="Synthetic.",
                notes="Private.",
                file=FakeUploadFile(MP4_BYTES, filename="source.mp4", content_type="video/mp4"),
            )

    def test_public_record_association_excludes_forced_private_status_and_keeps_legitimate_document(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute(
            "CREATE TABLE records (reference TEXT, version INTEGER, is_latest INTEGER, finding TEXT)"
        )
        conn.execute(
            "INSERT INTO records VALUES ('REC-PRIVATE-001', 1, 1, 'Synthetic public record')"
        )
        associations.ensure_association_tables(conn)

        private = self._store()
        private_path = self.root / private["intake_id"] / "metadata.json"
        private_metadata = json.loads(private_path.read_text(encoding="utf-8"))
        private_metadata["status"] = "published"
        private_path.write_text(json.dumps(private_metadata), encoding="utf-8")

        public = store_pending_document(
            data=b"%PDF-1.7\npublic synthetic\n%%EOF\n",
            original_filename="public.pdf",
            content_type="application/pdf",
            title="Legitimate published document",
            institution_source="Civic Office",
            document_date="2026-10-10",
            category="Decision",
            description="Synthetic fixture.",
            visibility="private",
            notes="Private note.",
            root=self.root,
        )
        public_path = self.root / public["intake_id"] / "metadata.json"
        public_metadata = json.loads(public_path.read_text(encoding="utf-8"))
        public_metadata["status"] = "published"
        public_path.write_text(json.dumps(public_metadata), encoding="utf-8")

        for index, document in enumerate((private, public), start=1):
            conn.execute(
                """
                INSERT INTO record_document_associations (
                    public_reference, record_reference, document_id,
                    relationship_type, public_label, is_active, is_public,
                    created_at, created_by, updated_at, updated_by
                ) VALUES (?, 'REC-PRIVATE-001', ?, 'supporting_document', ?, 1, 1,
                    '2026-10-10T10:00:00Z', 'synthetic', '2026-10-10T10:00:00Z', 'synthetic')
                """,
                (f"CDE-ASSOC-20261010-{index:03d}", document["intake_id"], f"Association {index}"),
            )
        conn.commit()
        public_rows = associations.public_associations_for_record(
            conn, "REC-PRIVATE-001", root=self.root
        )
        conn.close()

        self.assertEqual([row["document_id"] for row in public_rows], [public["intake_id"]])
        exposed = json.dumps(public_rows)
        self.assertNotIn(private["intake_id"], exposed)
        self.assertNotIn("Synthetic private original", exposed)


if __name__ == "__main__":
    unittest.main()
