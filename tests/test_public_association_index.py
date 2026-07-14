import asyncio
import hashlib
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from api.document_intake import store_pending_document, update_intake_status
from tests.test_admin_session import FakeRequest, install_fastapi_stubs

install_fastapi_stubs()

from api import record_document_associations as rda
from api.routes import admin_session, associations as association_routes, documents, records

PDF_BYTES = b"%PDF-1.7\nassociation-index\n%%EOF\n"
JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01association-index\xff\xd9"
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


class PublicAssociationIndexTests(unittest.TestCase):
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
        self.document_id = self._published_document(PDF_BYTES, "main.pdf", "Main Published Document", "DOC-MAIN-001", "Civic Office", "Decision")
        self.image_id = self._published_document(JPEG_BYTES, "visual.jpg", "Visual Published Document", "DOC-VIS-002", "Archive Office", "Public Record Image")
        self.png_id = self._published_document(PNG_BYTES, "diagram.png", "Diagram Published Document", "DOC-DIA-003", "Civic Office", "Diagram")
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
        self._insert_record(conn, "REC-INDEX-001", "Index record summary.", "Stable", "2026-07-13T09:00:00Z")
        self._insert_record(conn, "REC-INDEX-002", "Second index record.", "Escalating", "2026-07-12T09:00:00Z")
        self._insert_record(conn, "REC-HIDDEN-003", "Hidden record summary.", "Hidden", "2026-07-11T09:00:00Z")
        conn.commit()
        conn.close()

    def _insert_record(self, conn, reference, finding, trajectory, generated_at):
        digest = hashlib.sha256(reference.encode()).hexdigest()
        conn.execute(
            """
            INSERT INTO records (
                reference, version, generated_at, trajectory, system_state,
                conditions_json, signals_json, finding, report_json, language,
                generated_by, verification_hash, exported_at, is_latest, source_narrative
            ) VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, 'en', 'Civic Decision Engine', ?, ?, 1, '')
            """,
            (
                reference,
                generated_at,
                trajectory,
                f"State for {reference}.",
                '["Institutional Delay"]',
                "[]",
                finding,
                "{}",
                digest,
                generated_at,
            ),
        )

    def _published_document(self, data, filename, title, reference, source, category):
        item = store_pending_document(
            data=data,
            original_filename=filename,
            content_type="application/octet-stream",
            title=title,
            institution_source=source,
            document_date="2026-07-13",
            category=category,
            description=f"Description for {title}.",
            visibility="private",
            notes="Private document note.",
            reference_identifier=reference,
            actor="admin-user",
            uploaded_at="2026-07-13T10:00:00Z",
            root=self.root,
        )
        for status, timestamp in (
            ("under_review", "2026-07-13T11:00:00Z"),
            ("approved", "2026-07-13T12:00:00Z"),
            ("published", "2026-07-13T13:00:00Z"),
        ):
            update_intake_status(item["intake_id"], status, actor="admin-user", note=f"{status} note", changed_at=timestamp, root=self.root)
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
                record_reference=kwargs.get("record_reference", "REC-INDEX-001"),
                document_id=kwargs.get("document_id", self.document_id),
                relationship_type=kwargs.get("relationship_type", "supporting_document"),
                public_label=kwargs.get("public_label", "Supporting document"),
                public_note=kwargs.get("public_note", "Public index note."),
                admin_note=kwargs.get("admin_note", "Private administrative index note."),
                is_public=kwargs.get("is_public", True),
                actor="admin-user",
                created_at=kwargs.get("created_at", "2026-07-13T14:00:00Z"),
                root=self.root,
            )
        finally:
            conn.close()

    def _index(self, **params):
        return association_routes.public_association_index(**params).content

    def test_public_index_loads_without_authentication_and_has_boundary(self):
        association = self._create()
        content = self._index()
        self.assertIn("Public Record–Document Associations", content)
        self.assertIn("Total matching public associations:", content)
        self.assertIn(association["public_reference"], content)
        self.assertIn("declared and governed relationships", content)
        self.assertNotIn("Administration Console", content)
        self.assertNotIn("Signed in as", content)
        self.assertNotIn("Private administrative index note", content)
        self.assertNotIn("previous_state_json", content)
        self.assertNotIn(str(self.root), content)

    def test_public_index_eligibility_is_dynamic_and_public_only(self):
        visible = self._create(public_note="Visible note.")
        private = self._create(document_id=self.image_id, relationship_type="related_document", public_label="Private label", is_public=False, public_note="Private public-note text")
        inactive = self._create(document_id=self.png_id, relationship_type="source_document", public_label="Inactive label", public_note="Inactive public-note text")
        admin_session.admin_association_deactivate(inactive["id"], self.request, "Deactivate hidden association.")
        hidden_record = self._create(record_reference="REC-HIDDEN-003", document_id=self.image_id, relationship_type="publication_context", public_label="Hidden record", public_note="Hidden record note")
        conn = self._conn()
        conn.execute("UPDATE records SET is_latest = 0 WHERE reference = 'REC-HIDDEN-003'")
        conn.commit()
        conn.close()
        content = self._index()
        self.assertIn(visible["public_reference"], content)
        self.assertNotIn(private["public_reference"], content)
        self.assertNotIn(inactive["public_reference"], content)
        self.assertNotIn(hidden_record["public_reference"], content)
        self.assertNotIn("Private public-note text", content)
        self.assertNotIn("Inactive public-note text", content)
        self.assertNotIn("Hidden record note", content)
        admin_session.admin_association_reactivate(inactive["id"], self.request, "Reactivate.")
        content_after = self._index()
        self.assertIn(inactive["public_reference"], content_after)
        self.assertEqual(rda.get_association(self._conn(), inactive["id"])["public_reference"], inactive["public_reference"])

    def test_search_matches_public_safe_fields_only(self):
        association = self._create(public_label="Open civic link", public_note="Needle public note")
        self.assertIn(association["public_reference"], self._index(q=association["public_reference"].lower()))
        self.assertIn(association["public_reference"], self._index(q="index-001"))
        self.assertIn(association["public_reference"], self._index(q="doc-main"))
        self.assertIn(association["public_reference"], self._index(q="main published"))
        self.assertIn(association["public_reference"], self._index(q="needle public"))
        self.assertIn(association["public_reference"], self._index(q="civic office"))
        self.assertIn(association["public_reference"], self._index(q="decision"))
        self.assertIn("Total matching public associations:</strong> 0", self._index(q="Private administrative index"))
        self.assertIn("Total matching public associations:</strong> 0", self._index(q="' OR 1=1 --"))

    def test_filters_and_active_filter_summary(self):
        first = self._create(public_label="Supporting document", created_at="2026-07-13T14:00:00Z")
        second = self._create(record_reference="REC-INDEX-002", document_id=self.image_id, relationship_type="preserved_visual_record", public_label="Visual archive", public_note="Image note", created_at="2026-07-12T14:00:00Z")
        self.assertIn(first["public_reference"], self._index(relationship_type="supporting_document"))
        self.assertNotIn(second["public_reference"], self._index(relationship_type="supporting_document"))
        self.assertIn(second["public_reference"], self._index(record_reference="index-002"))
        self.assertIn(second["public_reference"], self._index(document_reference="vis-002"))
        self.assertIn(second["public_reference"], self._index(institution="Archive Office"))
        self.assertIn(second["public_reference"], self._index(category="Public Record Image"))
        self.assertIn(second["public_reference"], self._index(document_format="JPEG"))
        self.assertIn(first["public_reference"], self._index(created_year="2026"))
        invalid = self._index(relationship_type="not-real", created_year="not-year", document_format="exe")
        self.assertIn(first["public_reference"], invalid)
        self.assertIn(second["public_reference"], invalid)
        self.assertIn("Relationship type: supporting_document", self._index(relationship_type="supporting_document"))

    def test_pagination_preserves_filters_and_ordering(self):
        relationship_types = list(rda.RELATIONSHIP_TYPES)
        document_ids = [self.document_id, self.image_id, self.png_id]
        record_refs = ["REC-INDEX-001", "REC-INDEX-002"]
        references = []
        for index in range(11):
            association = self._create(
                record_reference=record_refs[index % len(record_refs)],
                document_id=document_ids[index % len(document_ids)],
                relationship_type=relationship_types[index % len(relationship_types)],
                public_label=f"Page label {index}",
                public_note="Page marker",
                created_at=f"2026-07-13T14:{index:02d}:00Z",
            )
            references.append(association["public_reference"])
        page_one = self._index(page_size=10, page=1, q="page marker")
        page_two = self._index(page_size=10, page=2, q="page marker")
        self.assertIn("Page 1 of 2", page_one)
        self.assertIn("page=2", page_one)
        self.assertIn("q=page+marker", page_one)
        self.assertIn("Page 2 of 2", page_two)
        first_page_refs = {ref for ref in references if ref in page_one}
        second_page_refs = {ref for ref in references if ref in page_two}
        self.assertEqual(len(first_page_refs), 10)
        self.assertEqual(len(second_page_refs), 1)
        self.assertTrue(first_page_refs.isdisjoint(second_page_refs))
        excessive = self._index(page_size=999, page="not-a-page")
        self.assertIn("Page 1 of 1", excessive)

    def test_result_rendering_links_and_detail_back_link(self):
        association = self._create(public_label="Renderable label", public_note="Renderable note")
        content = self._index()
        self.assertIn(association["public_reference"], content)
        self.assertIn("Renderable label", content)
        self.assertIn("Renderable note", content)
        self.assertIn("REC-INDEX-001", content)
        self.assertIn("Index record summary.", content)
        self.assertIn("Main Published Document", content)
        self.assertIn("DOC-MAIN-001", content)
        self.assertIn("Civic Office", content)
        self.assertIn("Decision", content)
        self.assertIn(f'href="/associations/{association["public_reference"]}"', content)
        self.assertIn('href="/verify/REC-INDEX-001"', content)
        self.assertIn(f'href="/documents/{self.document_id}"', content)
        self.assertNotIn(f'>{association["id"]}<', content)
        detail = association_routes.public_association_page(association["public_reference"]).content
        self.assertIn('href="/associations">Back to Public Association Index</a>', detail)

    def test_empty_states_do_not_disclose_hidden_counts(self):
        self.assertIn("No eligible public associations are currently listed.", self._index())
        hidden = self._create(is_public=False, public_note="Hidden private association")
        content = self._index(q="no-match")
        self.assertIn("Total matching public associations:</strong> 0", content)
        self.assertIn("No public associations match the selected filters.", content)
        self.assertNotIn(hidden["public_reference"], content)
        self.assertNotIn("Hidden private association", content)

    def test_regression_existing_detail_and_reciprocal_links_remain(self):
        association = self._create(public_label="Regression link")
        detail = association_routes.public_association_page(association["public_reference"]).content
        self.assertIn("Association Pathway", detail)
        self.assertIn("Association created.", detail)
        record_page = asyncio.run(records.verify_record("REC-INDEX-001")).content
        document_page = documents.public_document_page(self.document_id).content
        self.assertIn(f'/associations/{association["public_reference"]}', record_page)
        self.assertIn(f'/documents/{self.document_id}', record_page)
        self.assertIn(f'/associations/{association["public_reference"]}', document_page)
        self.assertIn('/verify/REC-INDEX-001', document_page)
        self.assertNotIn("Private administrative index note", detail)
        self.assertNotIn("Private administrative index note", record_page)
        self.assertNotIn("Private administrative index note", document_page)


if __name__ == "__main__":
    unittest.main()
