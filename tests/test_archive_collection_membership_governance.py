import hashlib
import os
import re
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from api.document_intake import load_pending_document, store_pending_document, update_intake_status
from tests.test_admin_session import FakeHTTPException, FakeRequest, install_fastapi_stubs

install_fastapi_stubs()

from api import archive_collection_memberships as acm
from api import archive_collections as ac
from api.routes import admin_session, collections as collection_routes


PDF_BYTES = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF\n"
ALT_PDF_BYTES = b"%PDF-1.7\n2 0 obj\n<<>>\nendobj\n%%EOF\n"


class ArchiveCollectionMembershipGovernanceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "records.db"
        self.root = Path(self.temp_dir.name) / "pending"
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
        self.originals = (admin_session.DB_PATH, ac.DB_PATH)
        admin_session.DB_PATH = self.db_path
        ac.DB_PATH = self.db_path
        self.request = FakeRequest(cookies={admin_session.SESSION_COOKIE_NAME: admin_session.create_admin_session("admin-user")})

    def tearDown(self):
        admin_session.DB_PATH, ac.DB_PATH = self.originals
        self.env.stop()
        self.temp_dir.cleanup()

    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        acm.ensure_membership_tables(conn)
        return conn

    def _collection(self, *, title="Strike Archive", is_public=True):
        conn = self._conn()
        try:
            return ac.create_collection(
                conn,
                title=title,
                subtitle="Structured member document sequence",
                institution_source="Nick Moloney",
                category="public_accountability_archive",
                description="Governed archive collection.",
                public_note="Public collection note.",
                admin_note="Private collection note.",
                date_from="2026-07-10",
                date_to=None,
                is_public=is_public,
                actor="admin-user",
                created_at="2026-07-17T10:00:00Z",
            )
        finally:
            conn.close()

    def _document(self, data=PDF_BYTES, *, title="Strike 001", reference="STRIKE-001", status="pending"):
        item = store_pending_document(
            data=data,
            original_filename=f"{reference}.pdf",
            content_type="application/pdf",
            title=title,
            institution_source="Nick Moloney",
            document_date="2026-07-10",
            category="Public Record Image",
            description="Document for governed collection membership.",
            visibility="private",
            notes="Private intake note.",
            reference_identifier=reference,
            actor="admin-user",
            root=self.root,
        )
        if status == "published":
            for new_status in ("under_review", "approved", "published"):
                item = update_intake_status(item["intake_id"], new_status, actor="admin-user", note=f"{new_status} note", root=self.root)
        return item

    def _membership(self, collection=None, document=None, **kwargs):
        collection = collection or self._collection()
        document = document or self._document()
        conn = self._conn()
        try:
            return acm.create_membership(
                conn,
                collection_id=collection["id"],
                document_id=document["intake_id"],
                actor=kwargs.get("actor", "admin-user"),
                membership_note=kwargs.get("membership_note", "Governed membership note."),
                display_sequence=kwargs.get("display_sequence", 10),
                created_at=kwargs.get("created_at", "2026-07-17T11:00:00Z"),
                root=self.root,
            )
        finally:
            conn.close()

    def test_schema_initialisation_reference_and_creation_history(self):
        collection = self._collection()
        document = self._document()
        membership = self._membership(collection, document)
        self.assertRegex(membership["membership_reference"], r"^CDE-MEM-20260717-\d{3}$")
        self.assertEqual(membership["membership_status"], "draft")
        self.assertEqual(membership["document_title"], "Strike 001")
        self.assertEqual(membership["document_reference"], "STRIKE-001")
        conn = self._conn()
        try:
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()}
            indexes = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'").fetchall()}
            history = acm.membership_history(conn, membership["id"])
        finally:
            conn.close()
        self.assertIn("archive_collection_memberships", tables)
        self.assertIn("archive_collection_membership_history", tables)
        self.assertIn("idx_archive_collection_memberships_reference", indexes)
        self.assertEqual(history[0]["action_type"], "created")
        self.assertEqual(history[0]["actor"], "admin-user")
        self.assertEqual(history[0]["timestamp"], "2026-07-17T11:00:00Z")

    def test_membership_lifecycle_sequence_and_history_are_governed(self):
        membership = self._membership()
        conn = self._conn()
        try:
            reviewed = acm.transition_membership(conn, membership["membership_reference"], new_status="reviewed", actor="admin-user", note="Reviewed.", timestamp="2026-07-17T11:10:00Z", root=self.root)
            approved = acm.transition_membership(conn, membership["membership_reference"], new_status="approved", actor="admin-user", note="Approved.", timestamp="2026-07-17T11:20:00Z", root=self.root)
            active = acm.transition_membership(conn, membership["membership_reference"], new_status="active", actor="admin-user", note="Activated.", timestamp="2026-07-17T11:30:00Z", root=self.root)
            sequenced = acm.update_sequence(conn, membership["membership_reference"], display_sequence=5, actor="admin-user", note="Move earlier.", timestamp="2026-07-17T11:40:00Z", root=self.root)
            inactive = acm.transition_membership(conn, membership["membership_reference"], new_status="inactive", actor="admin-user", note="Removed.", timestamp="2026-07-17T11:50:00Z", root=self.root)
            restored = acm.transition_membership(conn, membership["membership_reference"], new_status="active", actor="admin-user", note="Restored.", timestamp="2026-07-17T12:00:00Z", root=self.root)
            history = acm.membership_history(conn, membership["id"])
            with self.assertRaisesRegex(ValueError, "membership_transition_invalid"):
                acm.transition_membership(conn, membership["membership_reference"], new_status="approved", actor="admin-user", root=self.root)
        finally:
            conn.close()
        self.assertEqual(reviewed["membership_status"], "reviewed")
        self.assertEqual(approved["membership_status"], "approved")
        self.assertEqual(active["membership_status"], "active")
        self.assertEqual(sequenced["display_sequence"], 5)
        self.assertEqual(inactive["membership_status"], "inactive")
        self.assertEqual(inactive["is_active"], 0)
        self.assertEqual(restored["membership_reference"], membership["membership_reference"])
        self.assertEqual([item["action_type"] for item in history], ["created", "reviewed", "approved", "activated", "sequence_changed", "removed", "restored"])

    def test_admin_routes_render_membership_workflow_and_preserve_session_actor(self):
        collection = self._collection()
        document = self._document()
        add_page = admin_session.admin_collection_membership_new_page(collection["id"], self.request).content
        self.assertIn("Add document", add_page)
        self.assertIn(document["intake_id"], add_page)
        response = admin_session.admin_collection_membership_create(
            collection["id"],
            self.request,
            document["intake_id"],
            "Create governed membership.",
            "12",
            "",
            "",
        )
        content = response.content
        self.assertIn("Collection Membership", content)
        self.assertIn("CDE-MEM-", content)
        self.assertIn("admin-user", content)
        self.assertNotIn('name="actor"', content)
        detail_reference = re.search(r"CDE-MEM-\d{8}-\d{3}", content).group(0)
        detail = admin_session.admin_collection_membership_detail_page(collection["id"], detail_reference, self.request).content
        self.assertIn("Membership history", detail)
        self.assertIn("Display sequence", detail)
        collection_detail = admin_session.admin_collection_detail_page(collection["id"], self.request).content
        self.assertIn("Collection Members", collection_detail)
        self.assertIn("Open membership", collection_detail)
        with self.assertRaises(FakeHTTPException) as unauthenticated:
            admin_session.admin_collection_membership_new_page(collection["id"], FakeRequest())
        self.assertEqual(unauthenticated.exception.status_code, 401)

    def test_public_collection_lists_only_active_published_members_ordered_by_sequence(self):
        collection = self._collection(is_public=True)
        public_doc = self._document(PDF_BYTES, title="Published Strike", reference="STRIKE-001", status="published")
        hidden_doc = self._document(ALT_PDF_BYTES, title="Pending Strike", reference="STRIKE-002", status="pending")
        public_member = self._membership(collection, public_doc, display_sequence=20)
        hidden_member = self._membership(collection, hidden_doc, display_sequence=10, created_at="2026-07-17T11:01:00Z")
        conn = self._conn()
        try:
            for member in (public_member, hidden_member):
                acm.transition_membership(conn, member["membership_reference"], new_status="reviewed", actor="admin-user", root=self.root)
                acm.transition_membership(conn, member["membership_reference"], new_status="approved", actor="admin-user", root=self.root)
                acm.transition_membership(conn, member["membership_reference"], new_status="active", actor="admin-user", root=self.root)
        finally:
            conn.close()
        content = collection_routes.public_collection_page(collection["public_reference"]).content
        self.assertIn("Governed Member Documents", content)
        self.assertIn(public_member["membership_reference"], content)
        self.assertIn("Published Strike", content)
        self.assertIn(f'href="/documents/{public_doc["intake_id"]}"', content)
        self.assertNotIn(hidden_member["membership_reference"], content)
        self.assertNotIn("Pending Strike", content)
        self.assertNotIn("Private intake note", content)
        self.assertNotIn("Signed in as", content)

    def test_duplicate_active_membership_is_rejected_but_multiple_collections_are_allowed(self):
        document = self._document()
        first_collection = self._collection(title="First")
        second_collection = self._collection(title="Second")
        self._membership(first_collection, document)
        with self.assertRaisesRegex(ValueError, "membership_duplicate_active"):
            self._membership(first_collection, document, created_at="2026-07-17T11:05:00Z")
        second = self._membership(second_collection, document, created_at="2026-07-17T11:06:00Z")
        self.assertEqual(second["collection_id"], second_collection["id"])

    def test_membership_does_not_mutate_document_identity_lifecycle_or_hash(self):
        collection = self._collection()
        document = self._document()
        before = load_pending_document(document["intake_id"], root=self.root)
        self._membership(collection, document)
        after = load_pending_document(document["intake_id"], root=self.root)
        self.assertEqual(after["intake_id"], before["intake_id"])
        self.assertEqual(after["status"], before["status"])
        self.assertEqual(after["sha256_hash"], hashlib.sha256(PDF_BYTES).hexdigest())
        self.assertEqual(after["status_history"], before["status_history"])
        self.assertEqual(Path(after["proposed_storage_location"]).read_bytes(), PDF_BYTES)


if __name__ == "__main__":
    unittest.main()
