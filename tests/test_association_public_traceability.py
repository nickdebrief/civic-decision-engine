import asyncio
import hashlib
import os
import re
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from api.document_intake import store_pending_document, update_intake_status
from tests.test_admin_session import FakeHTTPException, FakeRequest, install_fastapi_stubs

install_fastapi_stubs()

from api import record_document_associations as rda
from api.routes import admin_session, associations as association_routes, documents, records

PDF_BYTES = b"%PDF-1.7\ntraceability\n%%EOF\n"
JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01traceability-jpeg\xff\xd9"


class AssociationPublicTraceabilityTests(unittest.TestCase):
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
        self.originals = (admin_session.DB_PATH, records.DB_PATH, rda.DB_PATH)
        admin_session.DB_PATH = self.db_path
        records.DB_PATH = self.db_path
        rda.DB_PATH = self.db_path
        self._init_records()
        self.document_id = self._published_document(PDF_BYTES, "published.pdf", "Published Document", "DOC-TRACE-001")
        self.image_id = self._published_document(JPEG_BYTES, "image.jpg", "Published Image", "IMG-TRACE-001")
        self.pending_id = self._pending_document()
        self.request = FakeRequest(cookies={admin_session.SESSION_COOKIE_NAME: admin_session.create_admin_session("admin-user")})

    def tearDown(self):
        admin_session.DB_PATH, records.DB_PATH, rda.DB_PATH = self.originals
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
        digest = hashlib.sha256(b"trace-record").hexdigest()
        conn.execute(
            """
            INSERT INTO records (
                reference, version, generated_at, trajectory, system_state,
                conditions_json, signals_json, finding, report_json, language,
                generated_by, verification_hash, exported_at, is_latest, source_narrative
            ) VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, 'en', 'Civic Decision Engine', ?, ?, 1, '')
            """,
            (
                "REC-TRACE-001",
                "2026-07-13T09:00:00Z",
                "Stable",
                "Traceability state.",
                '["Institutional Delay"]',
                "[]",
                "Traceability record summary.",
                "{}",
                digest,
                "2026-07-13T10:00:00Z",
            ),
        )
        conn.commit()
        conn.close()

    def _published_document(self, data, filename, title, reference):
        item = store_pending_document(
            data=data,
            original_filename=filename,
            content_type="application/octet-stream",
            title=title,
            institution_source="Civic Office",
            document_date="2026-07-13",
            category="Decision",
            description=f"Description for {title}.",
            visibility="private",
            notes="Private document note.",
            reference_identifier=reference,
            actor="admin",
            uploaded_at="2026-07-13T10:00:00Z",
            root=self.root,
        )
        for status, timestamp in (
            ("under_review", "2026-07-13T11:00:00Z"),
            ("approved", "2026-07-13T12:00:00Z"),
            ("published", "2026-07-13T13:00:00Z"),
        ):
            update_intake_status(item["intake_id"], status, actor="nick", note=f"{status} note", changed_at=timestamp, root=self.root)
        return item["intake_id"]

    def _pending_document(self):
        item = store_pending_document(
            data=b"%PDF-1.7\npending\n%%EOF\n",
            original_filename="pending.pdf",
            content_type="application/pdf",
            title="Pending Document",
            institution_source="Private Office",
            document_date="2026-07-13",
            category="Private",
            description="Pending.",
            visibility="private",
            notes="Private.",
            reference_identifier="PENDING-TRACE",
            root=self.root,
        )
        return item["intake_id"]

    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rda.ensure_association_tables(conn)
        return conn

    def _create(self, **kwargs):
        conn = self._conn()
        try:
            return rda.create_association(
                conn,
                record_reference=kwargs.get("record_reference", "REC-TRACE-001"),
                document_id=kwargs.get("document_id", self.document_id),
                relationship_type=kwargs.get("relationship_type", "supporting_document"),
                public_label=kwargs.get("public_label", "Supporting document"),
                public_note=kwargs.get("public_note", "Public association note."),
                admin_note=kwargs.get("admin_note", "Private administrative association note."),
                is_public=kwargs.get("is_public", True),
                actor=kwargs.get("actor", "admin-user"),
                created_at=kwargs.get("created_at", "2026-07-13T14:00:00Z"),
                root=self.root,
            )
        finally:
            conn.close()

    def test_public_reference_generation_is_server_generated_unique_and_immutable(self):
        first = self._create(public_label="Client label")
        second = self._create(document_id=self.image_id, relationship_type="preserved_visual_record", public_label="Preserved visual record")
        self.assertRegex(first["public_reference"], r"^CDE-ASSOC-20260713-\d{3}$")
        self.assertNotEqual(first["public_reference"], second["public_reference"])
        self.assertNotEqual(first["public_reference"], str(first["id"]))
        admin_session.admin_association_update(first["id"], self.request, "related_document", "Related document", "Updated public note.", "Updated private note.", "1")
        admin_session.admin_association_deactivate(first["id"], self.request, "Deactivate privately.")
        admin_session.admin_association_reactivate(first["id"], self.request, "Reactivate privately.")
        conn = self._conn()
        try:
            updated = rda.get_association(conn, first["id"])
            self.assertEqual(updated["public_reference"], first["public_reference"])
            self.assertEqual(updated["created_by"], "admin-user")
            self.assertEqual(updated["created_at"], "2026-07-13T14:00:00Z")
        finally:
            conn.close()

    def test_existing_v12_11_association_backfill_preserves_original_values(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute(
            """
            CREATE TABLE record_document_associations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                record_reference TEXT NOT NULL,
                document_id TEXT NOT NULL,
                document_reference_identifier TEXT,
                relationship_type TEXT NOT NULL,
                public_label TEXT NOT NULL,
                public_note TEXT,
                admin_note TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                is_public INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                created_by TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                updated_by TEXT NOT NULL,
                deactivated_at TEXT,
                deactivated_by TEXT,
                deactivation_note TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE record_document_association_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                association_id INTEGER NOT NULL,
                action_type TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                actor TEXT NOT NULL,
                previous_state_json TEXT,
                new_state_json TEXT,
                note TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO record_document_associations (
                record_reference, document_id, document_reference_identifier,
                relationship_type, public_label, public_note, admin_note,
                is_active, is_public, created_at, created_by, updated_at, updated_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, 1, ?, ?, ?, ?)
            """,
            (
                "REC-TRACE-001",
                self.document_id,
                "DOC-TRACE-001",
                "supporting_document",
                "Supporting document",
                "Public note.",
                "Private legacy note.",
                "2026-07-13T08:00:00Z",
                "admin",
                "2026-07-13T08:00:00Z",
                "admin",
            ),
        )
        conn.execute("INSERT INTO record_document_association_history (association_id, action_type, timestamp, actor, note) VALUES (1, 'created', '2026-07-13T08:00:00Z', 'admin', 'Legacy created.')")
        conn.commit()
        rda.ensure_association_tables(conn)
        first = dict(conn.execute("SELECT * FROM record_document_associations WHERE id = 1").fetchone())
        history_count = conn.execute("SELECT COUNT(*) FROM record_document_association_history").fetchone()[0]
        rda.ensure_association_tables(conn)
        second = dict(conn.execute("SELECT * FROM record_document_associations WHERE id = 1").fetchone())
        self.assertEqual(first["public_reference"], second["public_reference"])
        self.assertEqual(first["created_by"], "admin")
        self.assertEqual(first["created_at"], "2026-07-13T08:00:00Z")
        self.assertEqual(first["relationship_type"], "supporting_document")
        self.assertEqual(first["admin_note"], "Private legacy note.")
        self.assertEqual(history_count, 1)
        self.assertRegex(first["public_reference"], r"^CDE-ASSOC-20260713-\d{3}$")
        conn.close()

    def test_public_association_page_renders_public_safe_traceability(self):
        association = self._create()
        content = association_routes.public_association_page(association["public_reference"]).content
        self.assertIn("Public Record–Document Association", content)
        self.assertIn(association["public_reference"], content)
        self.assertIn("Supporting document", content)
        self.assertIn("Public association note.", content)
        self.assertIn("2026-07-13T14:00:00Z", content)
        self.assertIn("admin-user", content)
        self.assertIn("Active", content)
        self.assertIn("Public", content)
        self.assertIn("Traceability record summary.", content)
        self.assertIn("REC-TRACE-001", content)
        self.assertIn("Published Document", content)
        self.assertIn("DOC-TRACE-001", content)
        self.assertIn("Civic Office", content)
        self.assertIn("PDF", content)
        self.assertIn(f'href="/verify/REC-TRACE-001"', content)
        self.assertIn(f'href="/documents/{self.document_id}"', content)
        self.assertIn("Association Pathway", content)
        self.assertIn("Association created.", content)
        self.assertIn("does not make the linked document evidence", content)
        self.assertNotIn("Private administrative association note", content)
        self.assertNotIn("previous_state_json", content)
        self.assertNotIn("new_state_json", content)
        self.assertNotIn(str(self.root), content)
        self.assertNotIn("Signed in as", content)

    def test_public_route_eligibility_and_reference_behaviour(self):
        association = self._create()
        self.assertEqual(association_routes.public_association_page(association["public_reference"]).status_code, 200)
        for bad_reference in ("1", "CDE-ASSOC-19990101-999", "not-a-reference"):
            with self.subTest(bad_reference=bad_reference), self.assertRaises(FakeHTTPException):
                association_routes.public_association_page(bad_reference)
        admin_session.admin_association_deactivate(association["id"], self.request, "Deactivate privately.")
        with self.assertRaises(FakeHTTPException):
            association_routes.public_association_page(association["public_reference"])
        admin_session.admin_association_reactivate(association["id"], self.request, "Reactivate privately.")
        self.assertEqual(association_routes.public_association_page(association["public_reference"]).status_code, 200)
        update_intake_status(self.document_id, "archived", actor="admin-user", note="Archive.", changed_at="2026-07-13T16:00:00Z", root=self.root)
        with self.assertRaises(FakeHTTPException):
            association_routes.public_association_page(association["public_reference"])

    def test_record_and_document_pages_link_to_public_association(self):
        association = self._create()
        record_content = asyncio.run(records.verify_record("REC-TRACE-001")).content
        document_content = documents.public_document_page(self.document_id).content
        for content in (record_content, document_content):
            self.assertIn("View association", content)
            self.assertIn(f'/associations/{association["public_reference"]}', content)
        self.assertIn(f'href="/documents/{self.document_id}"', record_content)
        self.assertIn('href="/verify/REC-TRACE-001"', document_content)
        self.assertIn("Associated Public Documents", record_content)
        self.assertIn("Associated Civic Records", document_content)

    def test_public_association_pathway_is_separate_and_public_safe(self):
        association = self._create()
        admin_session.admin_association_update(association["id"], self.request, "related_document", "Related document", "Updated public note.", "Private update note.", "1")
        admin_session.admin_association_deactivate(association["id"], self.request, "Private deactivation note.")
        admin_session.admin_association_reactivate(association["id"], self.request, "Private reactivation note.")
        content = association_routes.public_association_page(association["public_reference"]).content
        self.assertIn("Created", content)
        self.assertIn("Updated", content)
        self.assertIn("Reactivated", content)
        self.assertIn("Public association fields updated", content)
        self.assertIn("Association Pathway", content)
        self.assertIn("separate from record verification history", content)
        self.assertNotIn("Private update note", content)
        self.assertNotIn("Private deactivation note", content)
        self.assertNotIn("Private reactivation note", content)
        self.assertNotIn("Publication Pathway</h2>", content)
        self.assertIn("Administrative Audit", content)
        self.assertNotIn("/admin/audit", content)
        self.assertNotIn("{&quot;", content)

    def test_admin_index_and_detail_show_public_reference_and_url(self):
        association = self._create()
        index = admin_session.admin_associations_page(self.request, q=association["public_reference"]).content
        self.assertIn("Public association reference", index)
        self.assertIn(association["public_reference"], index)
        self.assertIn("Total matching associations:</strong> 1", index)
        detail = admin_session.admin_association_detail_page(association["id"], self.request).content
        self.assertIn("Public association reference", detail)
        self.assertIn("Public association URL", detail)
        self.assertIn(f"/associations/{association['public_reference']}", detail)
        self.assertIn("Open public association", detail)
        self.assertNotIn('name="public_reference"', detail)
        admin_session.admin_association_deactivate(association["id"], self.request, "Private deactivation.")
        unavailable = admin_session.admin_association_detail_page(association["id"], self.request).content
        self.assertIn("Public association page is not currently available.", unavailable)

    def test_public_association_index_lists_only_public_eligible_associations(self):
        public_assoc = self._create()
        private_assoc = self._create(document_id=self.image_id, relationship_type="preserved_visual_record", public_label="Preserved visual record", is_public=False)
        content = association_routes.public_association_index().content
        self.assertIn("Public Record–Document Associations", content)
        self.assertIn(public_assoc["public_reference"], content)
        self.assertNotIn(private_assoc["public_reference"], content)
        self.assertIn("View association", content)
        self.assertIn("View record", content)
        self.assertIn("View document", content)
        filtered = association_routes.public_association_index(q="no-match").content
        self.assertIn("No public record-document associations match", filtered)

    def test_regression_document_record_hashes_and_file_behaviour_unchanged(self):
        association = self._create()
        record_content = asyncio.run(records.verify_record("REC-TRACE-001")).content
        self.assertIn(hashlib.sha256(b"trace-record").hexdigest(), record_content)
        document_content = documents.public_document_page(self.document_id).content
        self.assertIn(hashlib.sha256(PDF_BYTES).hexdigest(), document_content)
        self.assertIn("Publication Provenance", document_content)
        self.assertIn("Publication Pathway", document_content)
        view = documents.public_document_image_view(self.image_id)
        download = documents.public_document_download(self.image_id)
        self.assertIn("inline", view.headers.get("Content-Disposition", ""))
        self.assertIn("attachment", download.headers.get("Content-Disposition", ""))
        self.assertEqual(Path(view.path).read_bytes(), JPEG_BYTES)
        self.assertEqual(Path(download.path).read_bytes(), JPEG_BYTES)
        self.assertFalse(hasattr(association_routes, "public_association_mutation"))
        self.assertIn(association["public_reference"], association_routes.public_association_page(association["public_reference"]).content)


if __name__ == "__main__":
    unittest.main()
