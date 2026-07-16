import asyncio
import hashlib
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from api.document_intake import store_pending_document, update_intake_status
from tests.test_admin_session import FakeHTTPException, FakeRequest, install_fastapi_stubs

install_fastapi_stubs()

from api import record_document_associations as associations
from api.routes import admin_session, documents, records


PDF_BYTES = b"%PDF-1.7\nrecord-selection\n%%EOF\n"


class RecordDocumentAssociationRecordSelectionTests(unittest.TestCase):
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
        self.original_admin_db = admin_session.DB_PATH
        self.original_records_db = records.DB_PATH
        self.original_association_db = associations.DB_PATH
        admin_session.DB_PATH = self.db_path
        records.DB_PATH = self.db_path
        associations.DB_PATH = self.db_path
        self._init_records_db()
        self.document_id = self._published_document(reference="NM-EVID-INV-20191202-001")
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
                source_narrative TEXT
            )
            """
        )
        self._insert_record(conn, "REC-2026-002", "Second public record.", is_latest=1)
        self._insert_record(conn, "REC-2026-001", "First public record.", is_latest=1)
        self._insert_record(conn, "PRIVATE-2026-001", "Superseded private record.", is_latest=0)
        conn.commit()
        conn.close()

    def _insert_record(self, conn, reference, finding, *, is_latest):
        digest = hashlib.sha256(reference.encode("utf-8")).hexdigest()
        conn.execute(
            """
            INSERT INTO records (
                reference, version, generated_at, trajectory, system_state,
                conditions_json, signals_json, finding, report_json, language,
                generated_by, verification_hash, exported_at, is_latest, source_narrative
            ) VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, 'en', 'Civic Decision Engine', ?, ?, ?, '')
            """,
            (
                reference,
                "2026-07-01T09:00:00Z",
                "Stable",
                "Record system state",
                "[]",
                "[]",
                finding,
                "{}",
                digest,
                "2026-07-01T10:00:00Z",
                int(is_latest),
            ),
        )

    def _published_document(self, *, reference):
        item = store_pending_document(
            data=PDF_BYTES,
            original_filename="published.pdf",
            content_type="application/pdf",
            title="Contents of ZIP Archive — Initial Medical Council Complaint",
            institution_source="Civic Office",
            document_date="2026-07-09",
            category="Decision",
            description="Published document for association selection.",
            visibility="private",
            notes="Private administrative notes.",
            reference_identifier=reference,
            actor="admin",
            uploaded_at="2026-07-09T10:00:00Z",
            root=self.root,
        )
        for status, timestamp, note in (
            ("under_review", "2026-07-09T11:00:00Z", "Review started."),
            ("approved", "2026-07-09T12:00:00Z", "Approved."),
            ("published", "2026-07-09T13:00:00Z", "Published."),
        ):
            update_intake_status(
                item["intake_id"],
                status,
                actor="admin-user",
                note=note,
                changed_at=timestamp,
                root=self.root,
            )
        return item["intake_id"]

    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        associations.ensure_association_tables(conn)
        return conn

    def _association_count(self):
        conn = self._conn()
        try:
            return conn.execute("SELECT COUNT(*) FROM record_document_associations").fetchone()[0]
        finally:
            conn.close()

    def _create(self, record_reference="REC-2026-001"):
        return admin_session.admin_association_create(
            self.request,
            record_reference=record_reference,
            document_id=self.document_id,
            relationship_type="supporting_document",
            public_label="Supporting document",
            public_note="Public note.",
            admin_note="Administrative note.",
            is_public="1",
        )

    def test_create_page_renders_public_record_selector_not_free_text(self):
        content = admin_session.admin_association_new_page(self.request).content
        self.assertIn("Public CDE record", content)
        self.assertIn('<select name="record_reference" required>', content)
        self.assertNotIn('<input name="record_reference"', content)
        self.assertIn('value="REC-2026-001">REC-2026-001 — First public record.', content)
        self.assertIn('value="REC-2026-002">REC-2026-002 — Second public record.', content)
        self.assertLess(content.index('value="REC-2026-001"'), content.index('value="REC-2026-002"'))
        self.assertNotIn("PRIVATE-2026-001", content)
        self.assertIn("Published document", content)
        self.assertIn("NM-EVID-INV-20191202-001", content)
        self.assertIn("Select the public CDE record that the published document will support", content)
        self.assertIn("Select each object independently", content)

    def test_valid_selection_stores_exact_canonical_reference_and_preserves_metadata(self):
        before_doc = documents.public_document_page(self.document_id).content
        conn = self._conn()
        try:
            before_hash = conn.execute(
                "SELECT verification_hash FROM records WHERE reference = ? AND is_latest = 1",
                ("REC-2026-001",),
            ).fetchone()["verification_hash"]
        finally:
            conn.close()
        response = self._create(record_reference=" REC-2026-001 ")
        self.assertEqual(response.status_code, 201)
        conn = self._conn()
        try:
            row = conn.execute("SELECT * FROM record_document_associations").fetchone()
            self.assertEqual(row["record_reference"], "REC-2026-001")
            self.assertEqual(row["document_id"], self.document_id)
            self.assertEqual(row["created_by"], "admin-user")
            self.assertEqual(row["public_label"], "Supporting document")
            self.assertEqual(row["public_note"], "Public note.")
            self.assertEqual(row["admin_note"], "Administrative note.")
            self.assertEqual(row["relationship_type"], "supporting_document")
            self.assertEqual(row["is_public"], 1)
            self.assertTrue(str(row["public_reference"]).startswith("CDE-ASSOC-"))
            history = associations.association_history(conn, row["id"])
            self.assertEqual([item["action_type"] for item in history], ["created"])
            after_hash = conn.execute(
                "SELECT verification_hash FROM records WHERE reference = ? AND is_latest = 1",
                ("REC-2026-001",),
            ).fetchone()["verification_hash"]
        finally:
            conn.close()
        self.assertEqual(before_hash, after_hash)
        after_doc = documents.public_document_page(self.document_id).content
        self.assertIn("Publication Provenance", after_doc)
        self.assertIn(hashlib.sha256(PDF_BYTES).hexdigest(), after_doc)
        self.assertIn(hashlib.sha256(PDF_BYTES).hexdigest(), before_doc)

    def test_invalid_record_submissions_are_rejected_without_creating_associations(self):
        invalid_cases = {
            "": "association_record_required",
            "   ": "association_record_required",
            "UNKNOWN-001": "association_record_not_found",
            "PRIVATE-2026-001": "association_record_not_public",
            "REC-2026-001 — First public record.": "association_record_not_found",
            "Record REC-2026-001": "association_record_not_found",
            "NM-EVID-INV-20191202-001": "association_record_reference_is_document",
            "REC-2026-001, REC-2026-002": "association_record_multiple_not_allowed",
            "REC-2026-001; REC-2026-002": "association_record_multiple_not_allowed",
            "REC-2026-001\nREC-2026-002": "association_record_multiple_not_allowed",
            "REC-2026": "association_record_not_found",
        }
        for value, expected_detail in invalid_cases.items():
            with self.subTest(value=value):
                before = self._association_count()
                with self.assertRaises(FakeHTTPException) as ctx:
                    self._create(record_reference=value)
                self.assertEqual(ctx.exception.detail, expected_detail)
                self.assertEqual(self._association_count(), before)

    def test_duplicate_and_existing_behaviour_remain_unchanged(self):
        self._create()
        with self.assertRaises(FakeHTTPException) as duplicate:
            self._create()
        self.assertEqual(duplicate.exception.detail, "association_duplicate_active")
        detail = admin_session.admin_association_detail_page(1, self.request).content
        self.assertIn("Record–Document Association", detail)
        self.assertIn("REC-2026-001", detail)
        self.assertIn("NM-EVID-INV-20191202-001", detail)
        self.assertIn("Association history", detail)

    def test_empty_state_when_no_eligible_public_records_exist(self):
        conn = self._conn()
        try:
            conn.execute("UPDATE records SET is_latest = 0")
            conn.commit()
        finally:
            conn.close()
        content = admin_session.admin_association_new_page(self.request).content
        self.assertIn("No eligible public CDE records are currently available for association.", content)
        self.assertNotIn('<select name="record_reference" required>', content)
        self.assertIn('disabled aria-disabled="true"', content)
        self.assertNotIn("PRIVATE-2026-001", content)

    def test_authentication_and_existing_pages_remain_available(self):
        with self.assertRaises(FakeHTTPException) as create_page:
            admin_session.admin_association_new_page(FakeRequest())
        self.assertEqual(create_page.exception.status_code, 401)
        with self.assertRaises(FakeHTTPException) as mutation:
            admin_session.admin_association_create(
                FakeRequest(),
                "REC-2026-001",
                self.document_id,
                "supporting_document",
                "",
                "",
                "note",
                "1",
            )
        self.assertEqual(mutation.exception.status_code, 401)
        self.assertIn("Public records", asyncio.run(records.records_index()).content)
        self.assertIn("Public Document Library", documents.public_document_library().content)
        self.assertIn("Record–Document Associations", admin_session.admin_associations_page(self.request).content)
        self.assertIn("CDE Administration Console", admin_session.admin_dashboard_page(self.request).content)


if __name__ == "__main__":
    unittest.main()
