import hashlib
import os
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


def pdf_bytes(label: str) -> bytes:
    return f"%PDF-1.7\n1 0 obj\n<< /Label ({label}) >>\nendobj\n%%EOF\n".encode("utf-8")


class CollectionOrderedSequenceContinuityTests(unittest.TestCase):
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

    def _collection(self, title="Sequence Collection", *, is_public=True):
        conn = self._conn()
        try:
            return ac.create_collection(
                conn,
                title=title,
                subtitle="Ordered sequence",
                institution_source="Nick Moloney",
                category="public_accountability_archive",
                description="Governed ordered collection.",
                public_note="Public note.",
                admin_note="Private note.",
                date_from="2026-07-10",
                date_to=None,
                is_public=is_public,
                actor="admin-user",
                created_at="2026-07-18T10:00:00Z",
            )
        finally:
            conn.close()

    def _document(self, label: str, *, title: str | None = None, reference: str | None = None, document_date: str = "2026-07-10", published: bool = True):
        data = pdf_bytes(label)
        item = store_pending_document(
            data=data,
            original_filename=f"{label}.pdf",
            content_type="application/pdf",
            title=title or f"Document {label}",
            institution_source="Nick Moloney",
            document_date=document_date,
            category="Public Record Image",
            description=f"Document {label} for sequence tests.",
            visibility="private",
            notes="Private intake note.",
            reference_identifier=reference or f"DOC-{label}",
            actor="admin-user",
            root=self.root,
        )
        if published:
            for status in ("under_review", "approved", "published"):
                item = update_intake_status(item["intake_id"], status, actor="admin-user", note=f"{status} note", root=self.root)
        return item

    def _membership(self, collection, document, sequence, *, created_at: str = "2026-07-18T11:00:00Z", activate: bool = True):
        conn = self._conn()
        try:
            member = acm.create_membership(
                conn,
                collection_id=collection["id"],
                document_id=document["intake_id"],
                actor="admin-user",
                membership_note=f"Membership {sequence}",
                display_sequence=sequence,
                created_at=created_at,
                root=self.root,
            )
            if activate:
                for status in ("reviewed", "approved", "active"):
                    member = acm.transition_membership(
                        conn,
                        member["membership_reference"],
                        new_status=status,
                        actor="admin-user",
                        note=f"{status} note",
                        timestamp=f"2026-07-18T11:{sequence:02d}:00Z",
                        root=self.root,
                    )
            return member
        finally:
            conn.close()

    def test_active_memberships_order_by_sequence_not_document_metadata(self):
        collection = self._collection()
        late_a = self._document("A", title="Zulu", document_date="2026-12-31")
        early_b = self._document("B", title="Alpha", document_date="2026-01-01")
        middle_c = self._document("C", title="Middle", document_date="2026-06-01")
        self._membership(collection, late_a, 3, created_at="2026-07-18T11:03:00Z")
        self._membership(collection, early_b, 1, created_at="2026-07-18T11:01:00Z")
        self._membership(collection, middle_c, 2, created_at="2026-07-18T11:02:00Z")
        conn = self._conn()
        try:
            sequence = acm.collection_sequence(conn, collection["id"], root=self.root)
        finally:
            conn.close()
        self.assertEqual(sequence["state"], "continuous")
        self.assertEqual([item["document_reference"] for item in sequence["members"]], ["DOC-B", "DOC-C", "DOC-A"])
        self.assertEqual(sequence["members"][0]["previous_membership_reference"], None)
        self.assertEqual(sequence["members"][1]["sequence_position"], 2)
        self.assertEqual(sequence["members"][2]["next_membership_reference"], None)

    def test_sequence_validation_conflicts_and_history_preserve_document(self):
        collection = self._collection()
        doc_one = self._document("ONE")
        doc_two = self._document("TWO")
        first = self._membership(collection, doc_one, 1)
        second = self._membership(collection, doc_two, 2)
        before = load_pending_document(doc_two["intake_id"], root=self.root)
        conn = self._conn()
        try:
            with self.assertRaisesRegex(ValueError, "collection_membership_sequence_invalid"):
                acm.update_sequence(conn, second["membership_reference"], display_sequence=0, actor="admin-user", note="zero", root=self.root)
            with self.assertRaisesRegex(ValueError, "collection_membership_sequence_invalid"):
                acm.update_sequence(conn, second["membership_reference"], display_sequence=-1, actor="admin-user", note="negative", root=self.root)
            with self.assertRaisesRegex(ValueError, "collection_membership_sequence_conflict"):
                acm.update_sequence(conn, second["membership_reference"], display_sequence=1, actor="admin-user", note="conflict", root=self.root)
            updated = acm.update_sequence(conn, second["membership_reference"], display_sequence=3, actor="admin-user", note="Move to create visible gap.", timestamp="2026-07-18T12:00:00Z", root=self.root)
            history = acm.membership_history(conn, second["id"])
            sequence = acm.collection_sequence(conn, collection["id"], root=self.root)
        finally:
            conn.close()
        after = load_pending_document(doc_two["intake_id"], root=self.root)
        self.assertEqual(updated["display_sequence"], 3)
        self.assertIn("sequence_changed", [item["action_type"] for item in history])
        self.assertEqual(history[-1]["timestamp"], "2026-07-18T12:00:00Z")
        self.assertEqual(history[-1]["actor"], "admin-user")
        self.assertIn('"display_sequence": 2', history[-1]["previous_state_json"])
        self.assertIn('"display_sequence": 3', history[-1]["new_state_json"])
        self.assertEqual(sequence["state"], "gap_present")
        self.assertEqual(sequence["missing_positions"], [2])
        self.assertEqual(after["sha256_hash"], hashlib.sha256(pdf_bytes("TWO")).hexdigest())
        self.assertEqual(after["status"], before["status"])
        self.assertEqual(after["status_history"], before["status_history"])
        self.assertNotEqual(first["membership_reference"], second["membership_reference"])

    def test_continuity_states_for_empty_single_gap_duplicate_and_invalid(self):
        actually_empty = self._collection("Actually Empty")
        empty_collection = self._collection("Empty")
        single_collection = self._collection("Single")
        duplicate_collection = self._collection("Duplicate")
        invalid_collection = self._collection("Invalid")
        self._membership(single_collection, self._document("S"), 1)
        gap_first = self._membership(empty_collection, self._document("G1"), 1)
        self._membership(empty_collection, self._document("G3"), 3)
        self._membership(duplicate_collection, self._document("D1"), 1)
        dupe_two = self._membership(duplicate_collection, self._document("D2"), 2)
        self._membership(invalid_collection, self._document("I1"), 1)
        conn = self._conn()
        try:
            conn.execute("UPDATE archive_collection_memberships SET display_sequence = 1 WHERE membership_reference = ?", (dupe_two["membership_reference"],))
            conn.execute("UPDATE archive_collection_memberships SET display_sequence = 0 WHERE collection_id = ?", (invalid_collection["id"],))
            conn.commit()
            empty = acm.collection_sequence(conn, actually_empty["id"], root=self.root)
            single = acm.collection_sequence(conn, single_collection["id"], root=self.root)
            gap = acm.collection_sequence(conn, empty_collection["id"], root=self.root)
            duplicate = acm.collection_sequence(conn, duplicate_collection["id"], root=self.root)
            invalid = acm.collection_sequence(conn, invalid_collection["id"], root=self.root)
        finally:
            conn.close()
        self.assertEqual(empty["state"], "empty")
        self.assertEqual(single["state"], "single_member")
        self.assertEqual(gap["state"], "gap_present")
        self.assertEqual(gap_first["display_sequence"], 1)
        self.assertEqual(duplicate["state"], "duplicate_position")
        self.assertEqual(invalid["state"], "invalid_position")

    def test_deactivation_restore_and_same_position_in_different_collections(self):
        collection = self._collection()
        other_collection = self._collection("Other")
        first = self._membership(collection, self._document("A"), 1)
        second = self._membership(collection, self._document("B"), 2)
        other = self._membership(other_collection, self._document("C"), 1)
        conn = self._conn()
        try:
            inactive = acm.transition_membership(conn, first["membership_reference"], new_status="inactive", actor="admin-user", note="Remove.", root=self.root)
            sequence = acm.collection_sequence(conn, collection["id"], root=self.root)
        finally:
            conn.close()
        replacement = self._membership(collection, self._document("D"), 1)
        conn = self._conn()
        try:
            with self.assertRaisesRegex(ValueError, "collection_membership_restore_position_conflict"):
                acm.transition_membership(conn, first["membership_reference"], new_status="active", actor="admin-user", note="Restore.", root=self.root)
            restored = acm.transition_membership(conn, first["membership_reference"], new_status="active", display_sequence=3, actor="admin-user", note="Restore at new position.", root=self.root)
            history = acm.membership_history(conn, first["id"])
        finally:
            conn.close()
        self.assertEqual(inactive["membership_status"], "inactive")
        self.assertEqual([item["display_sequence"] for item in sequence["members"]], [2])
        self.assertEqual(restored["display_sequence"], 3)
        self.assertEqual(other["display_sequence"], 1)
        self.assertIn("restored", [item["action_type"] for item in history])
        self.assertNotEqual(replacement["membership_reference"], first["membership_reference"])
        self.assertEqual(second["display_sequence"], 2)

    def test_admin_ui_shows_sequence_overview_position_and_action(self):
        collection = self._collection()
        first = self._membership(collection, self._document("A"), 1)
        second = self._membership(collection, self._document("B"), 3)
        detail = admin_session.admin_collection_detail_page(collection["id"], self.request).content
        self.assertIn("Collection Sequence", detail)
        self.assertIn("Continuity state:</strong> Gap Present", detail)
        self.assertIn("Missing positions:</strong> 2", detail)
        self.assertIn("collection-sequence-table", detail)
        self.assertIn("Beginning of collection sequence", detail)
        membership_detail = admin_session.admin_collection_membership_detail_page(collection["id"], second["membership_reference"], self.request).content
        self.assertIn("Position within active sequence", membership_detail)
        self.assertIn("1 of 2", admin_session.admin_collection_membership_detail_page(collection["id"], first["membership_reference"], self.request).content)
        self.assertIn("Change sequence position", membership_detail)
        self.assertIn("Sequence Pathway", membership_detail)
        with self.assertRaises(FakeHTTPException) as ctx:
            admin_session.admin_collection_membership_sequence(collection["id"], second["membership_reference"], FakeRequest(), "4", "No auth.")
        self.assertEqual(ctx.exception.status_code, 401)

    def test_public_projected_sequence_hides_ineligible_members(self):
        collection = self._collection(is_public=True)
        public_one = self._document("P1", title="Public One", reference="PUB-001")
        hidden = self._document("HIDDEN", title="Hidden Middle", reference="HID-002", published=False)
        public_three = self._document("P3", title="Public Three", reference="PUB-003")
        m1 = self._membership(collection, public_one, 1)
        m2 = self._membership(collection, hidden, 2)
        m3 = self._membership(collection, public_three, 3)
        content = collection_routes.public_collection_page(collection["public_reference"]).content
        self.assertIn("Member 1 of 2", content)
        self.assertIn("Member 2 of 2", content)
        self.assertIn("Previous in collection", content)
        self.assertIn("Next in collection", content)
        self.assertIn(f'/documents/{public_one["intake_id"]}', content)
        self.assertIn(f'/documents/{public_three["intake_id"]}', content)
        self.assertNotIn("Hidden Middle", content)
        self.assertNotIn(m2["membership_reference"], content)
        self.assertNotIn("Member 3 of", content)
        self.assertIn("Sequence records navigational continuity only", content)
        self.assertNotIn("Private intake note", content)
        self.assertNotIn("Signed in as", content)
        self.assertIn(m1["membership_reference"], content)
        self.assertIn(m3["membership_reference"], content)


if __name__ == "__main__":
    unittest.main()
