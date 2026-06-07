import contextlib
import io
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from api.attachments import attachment_sha256, ensure_attachment_tables
from scripts.list_record_attachments import build_attachment_listing, main


REFERENCE = "Strike-OT-20260602-ATTACH-TEST"


def make_connection(db_path=":memory:"):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reference TEXT NOT NULL,
            version INTEGER NOT NULL DEFAULT 1,
            verification_hash TEXT NOT NULL,
            is_latest INTEGER NOT NULL DEFAULT 1,
            UNIQUE(reference, version)
        )
    """)
    conn.execute(
        """
        INSERT INTO records (reference, version, verification_hash, is_latest)
        VALUES (?, 1, ?, 1)
        """,
        (REFERENCE, "a" * 64),
    )
    ensure_attachment_tables(conn)
    return conn


def insert_attachment(conn, **overrides):
    values = {
        "reference": REFERENCE,
        "record_version": 1,
        "attachment_version": 1,
        "filename": "evidence.pdf",
        "stored_filename": "attachment-1-v1-abcd1234.pdf",
        "storage_path": "/data/attachments/Strike-OT-20260602-ATTACH-TEST/v1/attachments/attachment-1-v1-abcd1234.pdf",
        "content_type": "application/pdf",
        "file_size_bytes": 12,
        "sha256_hash": "abcd" * 16,
        "visibility": "public",
        "redaction_status": "none",
        "title": "Attachment title",
        "description": "Attachment description",
        "source_label": "Attachment source",
        "document_date": "2026-06-02",
        "document_date_precision": "day",
        "uploaded_at": "2026-06-02T09:00:00Z",
        "is_latest": 1,
        "is_deleted": 0,
    }
    values.update(overrides)
    columns = ", ".join(values.keys())
    placeholders = ", ".join("?" for _ in values)
    conn.execute(
        f"INSERT INTO record_attachments ({columns}) VALUES ({placeholders})",
        list(values.values()),
    )
    conn.commit()


class ListRecordAttachmentsTests(unittest.TestCase):
    def test_lists_attachments_for_reference_with_required_metadata(self):
        conn = make_connection()
        insert_attachment(conn)

        payload = build_attachment_listing(conn, reference=REFERENCE)
        attachment = payload["attachments"][0]

        self.assertEqual(payload["reference"], REFERENCE)
        self.assertEqual(payload["attachment_count"], 1)
        self.assertFalse(payload["verified_files"])
        self.assertEqual(
            set(attachment.keys()),
            {
                "attachment_id",
                "reference",
                "record_version",
                "attachment_version",
                "filename",
                "content_type",
                "file_size_bytes",
                "sha256_hash",
                "visibility",
                "redaction_status",
                "title",
                "description",
                "source_label",
                "classification",
                "publication_status",
                "document_date",
                "document_date_precision",
                "uploaded_at",
                "is_latest",
                "is_deleted",
                "appears_in_public_manifest",
                "active_relationships",
            },
        )
        self.assertEqual(attachment["filename"], "evidence.pdf")
        self.assertEqual(attachment["content_type"], "application/pdf")
        self.assertEqual(attachment["title"], "Attachment title")
        self.assertEqual(attachment["classification"], "other")
        self.assertEqual(attachment["publication_status"], "internal")
        self.assertEqual(attachment["document_date"], "2026-06-02")
        self.assertEqual(attachment["active_relationships"], [])
        self.assertNotIn("storage_path", attachment)
        self.assertNotIn("stored_filename", attachment)

    def test_unknown_reference_returns_empty_attachments(self):
        conn = make_connection()

        payload = build_attachment_listing(conn, reference="Strike-OT-20990101-MISSING")

        self.assertEqual(payload["attachment_count"], 0)
        self.assertEqual(payload["attachments"], [])

    def test_public_manifest_eligibility_rules(self):
        conn = make_connection()
        cases = (
            ("public.pdf", "public", "none", 1, 0, "published", True),
            ("internal.pdf", "public", "none", 1, 0, "internal", False),
            ("withdrawn.pdf", "public", "none", 1, 0, "withdrawn", False),
            ("private.pdf", "private", "none", 1, 0, "published", False),
            ("withheld.pdf", "public", "withheld", 1, 0, "published", False),
            ("deleted.pdf", "public", "none", 1, 1, "published", False),
            ("old.pdf", "public", "none", 0, 0, "published", False),
        )
        for filename, visibility, redaction_status, is_latest, is_deleted, publication_status, _ in cases:
            insert_attachment(
                conn,
                filename=filename,
                stored_filename=f"{filename}.stored",
                visibility=visibility,
                redaction_status=redaction_status,
                is_latest=is_latest,
                is_deleted=is_deleted,
                publication_status=publication_status,
            )

        payload = build_attachment_listing(conn, reference=REFERENCE)
        actual = {
            item["filename"]: item["appears_in_public_manifest"]
            for item in payload["attachments"]
        }

        for filename, _, _, _, _, _, expected in cases:
            with self.subTest(filename=filename):
                self.assertEqual(actual[filename], expected)

    def test_verify_files_reports_existing_matching_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data = b"synthetic evidence bytes"
            file_path = (
                root
                / REFERENCE
                / "v1"
                / "attachments"
                / "attachment-1-v1-matching.txt"
            )
            file_path.parent.mkdir(parents=True)
            file_path.write_bytes(data)

            conn = make_connection()
            insert_attachment(
                conn,
                filename="matching.txt",
                stored_filename=file_path.name,
                storage_path=str(file_path),
                content_type="text/plain",
                file_size_bytes=len(data),
                sha256_hash=attachment_sha256(data),
            )

            attachment = build_attachment_listing(
                conn,
                reference=REFERENCE,
                verify_files=True,
                attachment_root=root,
            )["attachments"][0]

            self.assertTrue(attachment["file_exists"])
            self.assertTrue(attachment["file_sha256_matches"])
            self.assertNotIn("storage_path", attachment)
            self.assertNotIn("stored_filename", attachment)

    def test_verify_files_reports_changed_bytes_mismatch(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            original = b"original bytes"
            file_path = root / REFERENCE / "v1" / "attachments" / "changed.txt"
            file_path.parent.mkdir(parents=True)
            file_path.write_bytes(b"changed bytes")

            conn = make_connection()
            insert_attachment(
                conn,
                filename="changed.txt",
                stored_filename=file_path.name,
                storage_path=str(file_path),
                content_type="text/plain",
                file_size_bytes=len(original),
                sha256_hash=attachment_sha256(original),
            )

            attachment = build_attachment_listing(
                conn,
                reference=REFERENCE,
                verify_files=True,
                attachment_root=root,
            )["attachments"][0]

            self.assertTrue(attachment["file_exists"])
            self.assertFalse(attachment["file_sha256_matches"])

    def test_verify_files_reports_missing_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            conn = make_connection()
            insert_attachment(
                conn,
                storage_path=str(root / REFERENCE / "v1" / "attachments" / "missing.txt"),
            )

            attachment = build_attachment_listing(
                conn,
                reference=REFERENCE,
                verify_files=True,
                attachment_root=root,
            )["attachments"][0]

            self.assertFalse(attachment["file_exists"])
            self.assertIsNone(attachment["file_sha256_matches"])

    def test_cli_outputs_json_without_requiring_or_exposing_admin_token(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "records.db"
            conn = make_connection(db_path)
            try:
                insert_attachment(conn)
            finally:
                conn.close()

            stdout = io.StringIO()
            with patch.dict(
                os.environ,
                {"CDE_ADMIN_TOKEN": "do-not-print-this-token"},
                clear=False,
            ):
                with contextlib.redirect_stdout(stdout):
                    exit_code = main(
                        [
                            "--reference",
                            REFERENCE,
                            "--db-path",
                            str(db_path),
                            "--pretty",
                        ]
                    )

            payload = json.loads(stdout.getvalue())
            serialized = json.dumps(payload)

            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["attachment_count"], 1)
            self.assertNotIn("do-not-print-this-token", serialized)
            self.assertNotIn("CDE_ADMIN_TOKEN", serialized)
            self.assertNotIn("storage_path", serialized)
            self.assertNotIn("stored_filename", serialized)


if __name__ == "__main__":
    unittest.main()
