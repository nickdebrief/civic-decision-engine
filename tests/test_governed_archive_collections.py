import os
import re
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.test_admin_session import FakeHTTPException, FakeRequest, install_fastapi_stubs

install_fastapi_stubs()

from api import archive_collections as ac
from api.routes import admin_session, collections as collection_routes


class GovernedArchiveCollectionsTests(unittest.TestCase):
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
        self.request = FakeRequest(
            cookies={admin_session.SESSION_COOKIE_NAME: admin_session.create_admin_session("admin-user")}
        )

    def tearDown(self):
        admin_session.DB_PATH, ac.DB_PATH = self.originals
        self.env.stop()
        self.temp_dir.cleanup()

    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        ac.ensure_collection_tables(conn)
        return conn

    def _create(self, **kwargs):
        conn = self._conn()
        try:
            return ac.create_collection(
                conn,
                title=kwargs.get("title", "Strike Archive"),
                subtitle=kwargs.get("subtitle", "Structured image-record sequence"),
                institution_source=kwargs.get("institution_source", "Nick Moloney"),
                category=kwargs.get("category", "public_accountability_archive"),
                description=kwargs.get("description", "Governed public archive preserving independently published documents."),
                public_note=kwargs.get("public_note", "Collection context only."),
                admin_note=kwargs.get("admin_note", "Private collection note."),
                date_from=kwargs.get("date_from", "2025-06-10"),
                date_to=kwargs.get("date_to"),
                is_public=kwargs.get("is_public", False),
                actor=kwargs.get("actor", "admin-user"),
                created_at=kwargs.get("created_at", "2026-07-15T10:00:00Z"),
            )
        finally:
            conn.close()

    def test_schema_initialisation_is_idempotent_and_adds_expected_indexes(self):
        conn = self._conn()
        ac.ensure_collection_tables(conn)
        ac.ensure_collection_tables(conn)
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        indexes = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            ).fetchall()
        }
        conn.close()
        self.assertIn("archive_collections", tables)
        self.assertIn("archive_collection_history", tables)
        self.assertIn("idx_archive_collections_public_reference", indexes)
        self.assertIn("idx_archive_collections_active_public", indexes)

    def test_admin_collection_pages_require_authentication(self):
        with self.assertRaises(FakeHTTPException) as ctx:
            admin_session.admin_collections_page(FakeRequest())
        self.assertEqual(ctx.exception.status_code, 401)
        with self.assertRaises(FakeHTTPException) as create_ctx:
            admin_session.admin_collection_new_page(FakeRequest())
        self.assertEqual(create_ctx.exception.status_code, 401)
        forged = FakeRequest(cookies={admin_session.SESSION_COOKIE_NAME: "forged.session"})
        with self.assertRaises(FakeHTTPException) as forged_ctx:
            admin_session.admin_collections_page(forged)
        self.assertEqual(forged_ctx.exception.status_code, 401)

    def test_admin_archive_collections_banner_reflects_membership_governance(self):
        content = admin_session.admin_collections_page(self.request).content
        self.assertNotIn("Document membership is not part of CDE v12.14.", content)
        self.assertIn(
            "Govern public archive identities through governed collection memberships.",
            content,
        )
        self.assertIn(
            "Documents, memberships, and collections each retain their own identity, lifecycle, provenance, and history while remaining independently governed.",
            content,
        )
        self.assertIn('href="/admin/collections/new"', content)
        collection = self._create()
        detail = admin_session.admin_collection_detail_page(collection["id"], self.request).content
        self.assertIn("Collection Members", detail)
        self.assertIn('href="/admin/collections/', detail)
        self.assertIn("/members/new", detail)

    def test_admin_navigation_and_dashboard_include_archive_collections(self):
        content = admin_session.admin_dashboard_page(self.request).content
        self.assertIn("Archive Collections", content)
        self.assertIn('href="/admin/collections"', content)
        self.assertIn("Create and govern public archive identities", content)
        self.assertIn("Signed in as:", content)
        self.assertIn("<strong>admin-user</strong>", content)

    def test_reference_generation_is_server_side_unique_and_immutable(self):
        first = self._create()
        second = self._create(title="Framework Publications", category="framework_publications")
        self.assertRegex(first["public_reference"], r"^CDE-COLL-20260715-\d{3}$")
        self.assertNotEqual(first["public_reference"], second["public_reference"])
        self.assertNotEqual(first["public_reference"], str(first["id"]))
        updated = admin_session.admin_collection_update(
            first["id"],
            self.request,
            "Strike Archive Updated",
            "Nick Moloney",
            "public_accountability_archive",
            "Updated description.",
            "1",
            "Updated subtitle",
            "2025-06-10",
            "",
            "Updated public note.",
            "Updated private note.",
        )
        self.assertIn(first["public_reference"], updated.content)
        admin_session.admin_collection_deactivate(first["id"], self.request, "Deactivate for test.")
        reactivated = admin_session.admin_collection_reactivate(first["id"], self.request, "Reactivate for test.")
        self.assertIn(first["public_reference"], reactivated.content)
        conn = self._conn()
        try:
            row = ac.get_collection(conn, first["id"])
            self.assertEqual(row["public_reference"], first["public_reference"])
            self.assertEqual(row["created_by"], "admin-user")
            self.assertEqual(row["created_at"], "2026-07-15T10:00:00Z")
        finally:
            conn.close()

    def test_creation_enforces_required_fields_controlled_category_and_private_default(self):
        created = self._create(is_public="")
        self.assertEqual(created["is_public"], 0)
        self.assertEqual(created["created_by"], "admin-user")
        conn = self._conn()
        try:
            history = ac.collection_history(conn, created["id"])
            self.assertEqual(len(history), 1)
            self.assertEqual(history[0]["action_type"], "created")
            self.assertEqual(history[0]["actor"], "admin-user")
        finally:
            conn.close()
        for kwargs, error in (
            ({"title": ""}, "collection_title_required"),
            ({"institution_source": ""}, "collection_institution_source_required"),
            ({"description": ""}, "collection_description_required"),
            ({"category": "not_a_category"}, "collection_category_invalid"),
        ):
            with self.assertRaisesRegex(ValueError, error):
                self._create(**kwargs)

    def test_date_validation_accepts_blank_and_rejects_invalid_ranges(self):
        blank = self._create(date_from="", date_to="")
        self.assertIsNone(blank["date_from"])
        self.assertIsNone(blank["date_to"])
        with self.assertRaisesRegex(ValueError, "collection_date_from_invalid"):
            self._create(date_from="2026/07/15")
        with self.assertRaisesRegex(ValueError, "collection_date_range_invalid"):
            self._create(date_from="2026-07-16", date_to="2026-07-15")

    def test_client_actor_and_reference_override_are_not_accepted(self):
        response = admin_session.admin_collection_create(
            self.request,
            "Client Override Attempt",
            "Nick Moloney",
            "public_accountability_archive",
            "Description.",
            "1",
            "Subtitle",
            "2025-06-10",
            "",
            "Public note.",
            "Private note.",
        )
        self.assertIn("CDE-COLL-", response.content)
        self.assertIn("admin-user", response.content)
        self.assertNotIn("mallory", response.content)
        self.assertNotIn("CLIENT-COLL-001", response.content)

    def test_update_preserves_creation_metadata_and_appends_history(self):
        created = self._create()
        response = admin_session.admin_collection_update(
            created["id"],
            self.request,
            "Updated Title",
            "Updated Source",
            "research_archive",
            "Updated description.",
            "1",
            "Updated subtitle",
            "2025-06-10",
            "2026-07-15",
            "Updated public note.",
            "Updated admin note.",
        )
        self.assertIn("Updated Title", response.content)
        conn = self._conn()
        try:
            row = ac.get_collection(conn, created["id"])
            history = ac.collection_history(conn, created["id"])
            self.assertEqual(row["created_by"], "admin-user")
            self.assertEqual(row["created_at"], "2026-07-15T10:00:00Z")
            self.assertEqual(row["updated_by"], "admin-user")
            self.assertEqual(row["category"], "research_archive")
            self.assertEqual(len(history), 2)
            self.assertIn("visibility_changed", {item["action_type"] for item in history})
        finally:
            conn.close()

    def test_deactivation_requires_note_and_reactivation_retains_reference(self):
        created = self._create(is_public=True)
        with self.assertRaises(FakeHTTPException) as ctx:
            admin_session.admin_collection_deactivate(created["id"], self.request, "")
        self.assertEqual(ctx.exception.status_code, 409)
        admin_session.admin_collection_deactivate(created["id"], self.request, "Deactivate collection.")
        conn = self._conn()
        try:
            inactive = ac.get_collection(conn, created["id"])
            self.assertEqual(inactive["is_active"], 0)
            self.assertEqual(inactive["deactivated_by"], "admin-user")
        finally:
            conn.close()
        content = collection_routes.public_collection_index().content
        self.assertNotIn(created["public_reference"], content)
        admin_session.admin_collection_reactivate(created["id"], self.request, "Reactivate collection.")
        conn = self._conn()
        try:
            active = ac.get_collection(conn, created["id"])
            self.assertEqual(active["public_reference"], created["public_reference"])
            self.assertEqual(active["is_active"], 1)
            self.assertIsNone(active["deactivation_note"])
        finally:
            conn.close()

    def test_admin_index_filters_pagination_and_private_notes_are_authenticated(self):
        visible = self._create(title="Strike Archive", is_public=True, admin_note="Private needle")
        self._create(title="Framework Collection", category="framework_publications", institution_source="CDE", created_at="2026-07-14T10:00:00Z")
        content = admin_session.admin_collections_page(self.request, q="Private needle", page_size=1).content
        self.assertIn(visible["public_reference"], content)
        self.assertIn("Private needle", content)
        self.assertIn("Page 1 of 1", content)
        by_category = admin_session.admin_collections_page(self.request, category="framework_publications").content
        self.assertIn("Framework Collection", by_category)
        self.assertNotIn("Strike Archive</td>", by_category)

    def test_public_collection_detail_requires_active_public_eligibility(self):
        private = self._create(is_public=False)
        public = self._create(title="Public Strike Archive", is_public=True)
        with self.assertRaises(FakeHTTPException) as private_ctx:
            collection_routes.public_collection_page(private["public_reference"])
        self.assertEqual(private_ctx.exception.status_code, 404)
        content = collection_routes.public_collection_page(public["public_reference"]).content
        self.assertIn("Public Archive Collection", content)
        self.assertIn(public["public_reference"], content)
        self.assertIn("Public Strike Archive", content)
        self.assertIn("Collection Governance Boundary", content)
        self.assertIn("No active governed member documents are currently publicly visible", content)
        self.assertNotIn("Private collection note", content)
        self.assertNotIn("Signed in as", content)
        self.assertNotIn("previous_state_json", content)
        admin_session.admin_collection_deactivate(public["id"], self.request, "Deactivate public.")
        with self.assertRaises(FakeHTTPException) as inactive_ctx:
            collection_routes.public_collection_page(public["public_reference"])
        self.assertEqual(inactive_ctx.exception.status_code, 404)

    def test_public_collection_pathway_is_public_safe(self):
        created = self._create(is_public=True)
        admin_session.admin_collection_update(
            created["id"],
            self.request,
            "Pathway Archive",
            "Nick Moloney",
            "public_accountability_archive",
            "Updated public-safe description.",
            "1",
            "",
            "2025-06-10",
            "",
            "Public pathway note.",
            "Private pathway note.",
        )
        content = collection_routes.public_collection_page(created["public_reference"]).content
        self.assertIn("Collection Pathway", content)
        self.assertIn("Created", content)
        self.assertIn("Updated", content)
        self.assertIn("admin-user", content)
        self.assertIn("Active, Public", content)
        self.assertNotIn("Private pathway note", content)
        self.assertNotIn("raw", content.lower())

    def test_public_collection_index_lists_only_eligible_collections_and_counts_safely(self):
        visible = self._create(title="Visible Strike Archive", is_public=True)
        private = self._create(title="Private Strike Archive", is_public=False, public_note="Hidden public note")
        inactive = self._create(title="Inactive Strike Archive", is_public=True)
        admin_session.admin_collection_deactivate(inactive["id"], self.request, "Deactivate hidden.")
        content = collection_routes.public_collection_index().content
        self.assertIn("Public Archive Collections", content)
        self.assertIn("Total matching public collections:</strong> 1", content)
        self.assertIn(visible["public_reference"], content)
        self.assertNotIn(private["public_reference"], content)
        self.assertNotIn(inactive["public_reference"], content)
        self.assertNotIn("Hidden public note", content)
        self.assertNotIn("Administration Console", content)
        self.assertIn("View collection", content)

    def test_public_index_search_filters_pagination_and_empty_states(self):
        first = self._create(title="Strike Archive", institution_source="Nick Moloney", category="public_accountability_archive", is_public=True)
        second = self._create(title="Framework Publications", institution_source="CDE", category="framework_publications", date_from="2026-07-01", date_to="2026-07-15", is_public=True, created_at="2026-07-14T10:00:00Z")
        self.assertIn(first["public_reference"], collection_routes.public_collection_index(q="strike").content)
        self.assertIn(second["public_reference"], collection_routes.public_collection_index(category="framework_publications").content)
        self.assertIn(second["public_reference"], collection_routes.public_collection_index(institution="CDE").content)
        self.assertIn(first["public_reference"], collection_routes.public_collection_index(created_year="2026").content)
        self.assertIn(second["public_reference"], collection_routes.public_collection_index(coverage_year="2026").content)
        for index in range(9):
            self._create(
                title=f"Paged Collection {index}",
                institution_source="Nick Moloney",
                is_public=True,
                created_at=f"2026-07-13T10:{index:02d}:00Z",
            )
        page_one = collection_routes.public_collection_index(page_size=10, page=1).content
        page_two = collection_routes.public_collection_index(page_size=10, page=2).content
        self.assertIn("Page 1 of 2", page_one)
        self.assertIn("page=2", page_one)
        self.assertIn("Page 2 of 2", page_two)
        self.assertIn("No public archive collections match the selected filters.", collection_routes.public_collection_index(q="not-present").content)

    def test_public_rendering_escapes_malicious_metadata(self):
        item = self._create(
            title="<script>alert(1)</script>",
            description="<b>Description</b>",
            public_note="<img src=x onerror=alert(1)>",
            is_public=True,
        )
        detail = collection_routes.public_collection_page(item["public_reference"]).content
        index = collection_routes.public_collection_index(q="script").content
        for content in (detail, index):
            self.assertNotIn("<script>alert(1)</script>", content)
            self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", content)
        self.assertIn("&lt;img src=x onerror=alert(1)&gt;", detail)

    def test_empty_collection_membership_state_does_not_mutate_public_documents(self):
        item = self._create(is_public=True)
        content = collection_routes.public_collection_page(item["public_reference"]).content
        self.assertIn("Governed Member Documents", content)
        self.assertIn("No active governed member documents are currently publicly visible", content)
        self.assertNotIn("Add document", content)
        self.assertNotIn("Remove document", content)
        self.assertTrue(hasattr(admin_session, "admin_collection_membership_create"))
        conn = self._conn()
        try:
            tables = {
                row[0]
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
            }
        finally:
            conn.close()
        self.assertIn("archive_collection_memberships", tables)
        conn = self._conn()
        try:
            member_count = conn.execute("SELECT COUNT(*) FROM archive_collection_memberships").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(member_count, 0)

    def test_public_pages_do_not_render_credentials_storage_or_admin_state(self):
        item = self._create(is_public=True)
        content = collection_routes.public_collection_page(item["public_reference"]).content
        index = collection_routes.public_collection_index().content
        serialized = content + index
        self.assertNotIn("admin-password", serialized)
        self.assertNotIn("session-secret", serialized)
        self.assertNotIn(str(self.db_path), serialized)
        self.assertNotIn(str(self.root), serialized)
        self.assertNotIn("Administrative note", content)
        self.assertNotIn("Private collection note", serialized)


if __name__ == "__main__":
    unittest.main()
