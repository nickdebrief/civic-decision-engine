import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from api.document_intake import store_pending_document, update_intake_status
from tests.test_admin_session import FakeHTTPException, FakeRequest, install_fastapi_stubs

install_fastapi_stubs()

from api import archive_collection_memberships as acm
from api import archive_collections as ac
from api import record_document_associations as rda
from api.routes import admin_session, collections as collection_routes, records


PDF_BYTES = b"%PDF-1.7\npublic collection member\n%%EOF\n"


class PublicCollectionPagesTests(unittest.TestCase):
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
            records.DB_PATH,
        )
        admin_session.DB_PATH = self.db_path
        ac.DB_PATH = self.db_path
        rda.DB_PATH = self.db_path
        records.DB_PATH = self.db_path
        self.request = FakeRequest(
            cookies={admin_session.SESSION_COOKIE_NAME: admin_session.create_admin_session("admin-user")}
        )
        self._init_records()

    def tearDown(self):
        admin_session.DB_PATH, ac.DB_PATH, rda.DB_PATH, records.DB_PATH = self.originals
        self.env.stop()
        self.temp_dir.cleanup()

    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        acm.ensure_membership_tables(conn)
        return conn

    def _init_records(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """
            CREATE TABLE records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reference TEXT NOT NULL,
                record_type TEXT NOT NULL DEFAULT 'strike',
                title TEXT,
                institution TEXT,
                summary TEXT,
                version INTEGER NOT NULL DEFAULT 1,
                generated_at TEXT NOT NULL,
                trajectory TEXT,
                system_state TEXT,
                finding TEXT,
                report_json TEXT,
                language TEXT NOT NULL DEFAULT 'en',
                verification_hash TEXT NOT NULL,
                exported_at TEXT NOT NULL,
                is_latest INTEGER NOT NULL DEFAULT 1
            )
            """
        )
        conn.execute(
            """
            INSERT INTO records (
                reference, record_type, title, institution, summary, generated_at,
                trajectory, system_state, finding, report_json, verification_hash,
                exported_at, is_latest
            ) VALUES (
                'CMP-MC-20191202-001', 'complaint',
                'Initial Complaint to the Medical Council of Ireland',
                'Medical Council of Ireland',
                'Formal complaint submitted with supporting material.',
                '2026-07-20T09:00:00Z', 'Submitted', 'Published',
                'Complaint record summary.', '{}', 'record-hash',
                '2026-07-20T10:00:00Z', 1
            )
            """
        )
        conn.commit()
        conn.close()

    def _collection(self, *, is_public=True):
        conn = self._conn()
        try:
            return ac.create_collection(
                conn,
                title="Medical Council Complaint Collection",
                subtitle="Governed public collection",
                institution_source="Medical Council of Ireland",
                category="documentary_archive",
                description="A curated collection of independently governed public objects.",
                public_note="Public collection note.",
                admin_note="Administrative collection note.",
                date_from="2019-12-02",
                date_to=None,
                is_public=is_public,
                actor="admin-user",
                created_at="2026-07-21T10:00:00Z",
            )
        finally:
            conn.close()

    def _document(self, *, title="Initial Complaint Evidence Package", reference="NM-EVID-PKG-20191202-001", status="published"):
        item = store_pending_document(
            data=PDF_BYTES,
            original_filename=f"{reference}.pdf",
            content_type="application/pdf",
            title=title,
            institution_source="Medical Council of Ireland",
            document_date="2019-12-02",
            category="Evidence Package",
            description="Published document summary.",
            visibility="private",
            notes="Private document note.",
            reference_identifier=reference,
            actor="admin-user",
            root=self.root,
        )
        if status == "published":
            for new_status in ("under_review", "approved", "published"):
                update_intake_status(
                    item["intake_id"],
                    new_status,
                    actor="admin-user",
                    note=f"{new_status} note",
                    root=self.root,
                )
        return item

    def _association(self, document):
        conn = self._conn()
        try:
            return rda.create_association(
                conn,
                record_reference="CMP-MC-20191202-001",
                document_id=document["intake_id"],
                relationship_type="supporting_document",
                public_label="Supporting evidence package",
                public_note="Public association note.",
                admin_note="Private association note.",
                is_public=True,
                actor="admin-user",
                created_at="2026-07-21T11:00:00Z",
                root=self.root,
            )
        finally:
            conn.close()

    def _activate(self, membership_reference):
        conn = self._conn()
        try:
            for status in ("reviewed", "approved", "active"):
                acm.transition_membership(
                    conn,
                    membership_reference,
                    new_status=status,
                    actor="admin-user",
                    note=f"{status} note",
                    root=self.root,
                )
        finally:
            conn.close()

    def test_membership_schema_is_backward_compatible_and_typed(self):
        conn = self._conn()
        try:
            columns = {
                row[1]
                for row in conn.execute("PRAGMA table_info(archive_collection_memberships)").fetchall()
            }
            indexes = {
                row[0]
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'").fetchall()
            }
            acm.ensure_membership_tables(conn)
        finally:
            conn.close()
        self.assertIn("member_type", columns)
        self.assertIn("member_reference", columns)
        self.assertIn("section_label", columns)
        self.assertIn("curator_note", columns)
        self.assertIn("idx_archive_collection_memberships_member_reference", indexes)

    def test_public_collection_renders_records_documents_and_associations(self):
        collection = self._collection()
        document = self._document()
        association = self._association(document)
        conn = self._conn()
        try:
            record_member = acm.create_membership(
                conn,
                collection_id=collection["id"],
                member_type="canonical_record",
                member_reference="CMP-MC-20191202-001",
                actor="admin-user",
                membership_note="Record member.",
                section_label="Complaint",
                display_sequence=1,
                root=self.root,
            )
            document_member = acm.create_membership(
                conn,
                collection_id=collection["id"],
                document_id=document["intake_id"],
                actor="admin-user",
                membership_note="Document member.",
                section_label="Evidence",
                display_sequence=2,
                root=self.root,
            )
            association_member = acm.create_membership(
                conn,
                collection_id=collection["id"],
                member_type="record_document_association",
                member_reference=association["public_reference"],
                actor="admin-user",
                membership_note="Association member.",
                curator_note="Private curator note.",
                display_sequence=3,
                root=self.root,
            )
        finally:
            conn.close()
        for member in (record_member, document_member, association_member):
            self._activate(member["membership_reference"])

        content = collection_routes.public_collection_page(collection["public_reference"]).content
        self.assertIn("Governed Collection Members", content)
        self.assertIn('aria-label="Governed Collection Members table"', content)
        self.assertIn("public-collection-members-table governance-table governance-table--dense", content)
        self.assertIn("public-collection-member-reference table-cell--identifier", content)
        self.assertIn("public-collection-member-document table-cell--content", content)
        self.assertIn("public-collection-member-section table-cell--label", content)
        self.assertIn('aria-label="Collection Pathway table"', content)
        self.assertIn("public-collection-pathway-table governance-table governance-table--dense", content)
        self.assertIn("Canonical Record", content)
        self.assertIn("Published Document", content)
        self.assertIn("Record-Document Association", content)
        self.assertIn("CMP-MC-20191202-001", content)
        self.assertIn("Initial Complaint to the Medical Council of Ireland", content)
        self.assertIn(f'href="/verify/CMP-MC-20191202-001"', content)
        self.assertIn(f'href="/documents/{document["intake_id"]}"', content)
        self.assertIn(f'href="/associations/{association["public_reference"]}"', content)
        self.assertIn("Supporting evidence package", content)
        self.assertIn("Visible member count", content)
        self.assertIn(">3<", content)
        self.assertNotIn("Private curator note", content)
        self.assertNotIn("Private association note", content)
        self.assertNotIn("Private document note", content)
        self.assertNotIn("Signed in as", content)
        self.assertNotIn("word-break:break-all", content)

    def test_unavailable_members_are_omitted_without_deleting_membership(self):
        collection = self._collection()
        hidden_document = self._document(title="Pending hidden document", reference="HIDDEN-DOC-001", status="pending")
        conn = self._conn()
        try:
            membership = acm.create_membership(
                conn,
                collection_id=collection["id"],
                document_id=hidden_document["intake_id"],
                actor="admin-user",
                membership_note="Pending document membership.",
                display_sequence=1,
                root=self.root,
            )
        finally:
            conn.close()
        self._activate(membership["membership_reference"])

        content = collection_routes.public_collection_page(collection["public_reference"]).content
        self.assertIn("No active governed public members", content)
        self.assertNotIn("Pending hidden document", content)
        conn = self._conn()
        try:
            stored = acm.get_membership(conn, membership["id"])
        finally:
            conn.close()
        self.assertEqual(stored["membership_reference"], membership["membership_reference"])

    def test_duplicate_membership_and_unsupported_member_types_are_rejected(self):
        collection = self._collection()
        conn = self._conn()
        try:
            first = acm.create_membership(
                conn,
                collection_id=collection["id"],
                member_type="canonical_record",
                member_reference="CMP-MC-20191202-001",
                actor="admin-user",
                membership_note="Record member.",
                display_sequence=1,
                root=self.root,
            )
            with self.assertRaisesRegex(ValueError, "membership_duplicate_active"):
                acm.create_membership(
                    conn,
                    collection_id=collection["id"],
                    member_type="canonical_record",
                    member_reference="CMP-MC-20191202-001",
                    actor="admin-user",
                    membership_note="Duplicate.",
                    display_sequence=2,
                    root=self.root,
                )
            with self.assertRaisesRegex(ValueError, "collection_member_type_unsupported"):
                acm.create_membership(
                    conn,
                    collection_id=collection["id"],
                    member_type="unsupported",
                    member_reference="CMP-MC-20191202-001",
                    actor="admin-user",
                    membership_note="Unsupported.",
                    root=self.root,
                )
        finally:
            conn.close()
        self.assertEqual(first["member_type"], "canonical_record")

    def test_admin_add_member_page_lists_supported_member_types(self):
        collection = self._collection()
        document = self._document()
        association = self._association(document)
        content = admin_session.admin_collection_membership_new_page(collection["id"], self.request).content
        self.assertIn("Add member", content)
        self.assertIn("Canonical Record", content)
        self.assertIn("Published Document", content)
        self.assertIn("Record-Document Association", content)
        self.assertIn("CMP-MC-20191202-001", content)
        self.assertIn(document["intake_id"], content)
        self.assertIn(association["public_reference"], content)
        with self.assertRaises(FakeHTTPException) as unauthenticated:
            admin_session.admin_collection_membership_new_page(collection["id"], FakeRequest())
        self.assertEqual(unauthenticated.exception.status_code, 401)


if __name__ == "__main__":
    unittest.main()
