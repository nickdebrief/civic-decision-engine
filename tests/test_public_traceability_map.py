import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.test_admin_session import install_fastapi_stubs
from tests import test_public_archive_explorer as archive_fixture

install_fastapi_stubs()

from api import archive_collection_memberships as acm
from api import archive_collections as ac
from api import record_document_associations as rda
from api.public_navigation import sanitize_traceability_return
from api.routes import archive, documents, records, traceability


class PublicTraceabilityMapTests(unittest.TestCase):
    def setUp(self):
        self.fixture = archive_fixture.PublicArchiveExplorerTests(
            methodName="test_landing_displays_counts_and_public_object_types"
        )
        self.fixture.setUp()
        self.second_association = self._add_second_public_association()
        self.private_association = self._add_private_association()
        self.inactive_association = self._add_inactive_association()

    def tearDown(self):
        self.fixture.tearDown()

    def _conn(self):
        conn = sqlite3.connect(self.fixture.db_path)
        conn.row_factory = sqlite3.Row
        acm.ensure_membership_tables(conn)
        return conn

    def _add_second_public_association(self):
        conn = self._conn()
        try:
            association = rda.create_association(
                conn,
                record_reference="CMP-MC-20191202-001",
                document_id=self.fixture.document["intake_id"],
                relationship_type="source_document",
                public_label="Source spreadsheet",
                public_note="Second declared public relationship for the same governed endpoints.",
                admin_note="Private second association note.",
                is_public=True,
                actor="admin-user",
                created_at="2026-07-23T11:30:00Z",
                root=self.fixture.root,
            )
            membership = acm.create_membership(
                conn,
                collection_id=self.fixture.collection["id"],
                member_type="record_document_association",
                member_reference=association["public_reference"],
                actor="admin-user",
                membership_note="Association membership.",
                display_sequence=2,
                created_at="2026-07-23T12:20:00Z",
                root=self.fixture.root,
            )
            for status in ("reviewed", "approved", "active"):
                acm.transition_membership(
                    conn,
                    membership["membership_reference"],
                    new_status=status,
                    actor="admin-user",
                    root=self.fixture.root,
                )
            return association
        finally:
            conn.close()

    def _add_private_association(self):
        conn = self._conn()
        try:
            return rda.create_association(
                conn,
                record_reference="Strike-LA-20260710-004",
                document_id=self.fixture.document["intake_id"],
                relationship_type="related_document",
                public_label="Private related spreadsheet",
                public_note="This public note should not appear while private.",
                admin_note="Private association note.",
                is_public=False,
                actor="admin-user",
                created_at="2026-07-23T11:40:00Z",
                root=self.fixture.root,
            )
        finally:
            conn.close()

    def _add_inactive_association(self):
        conn = self._conn()
        try:
            association = rda.create_association(
                conn,
                record_reference="Strike-LA-20260710-004",
                document_id=self.fixture.document["intake_id"],
                relationship_type="methodology_reference",
                public_label="Inactive methodology spreadsheet",
                public_note="This inactive public note should not appear.",
                admin_note="Private association note.",
                is_public=True,
                actor="admin-user",
                created_at="2026-07-23T11:50:00Z",
                root=self.fixture.root,
            )
            rda.deactivate_association(
                conn,
                association["id"],
                actor="admin-user",
                note="Deactivate for traceability test.",
            )
            return association
        finally:
            conn.close()

    def page(self, **params):
        return traceability.public_traceability_map(**params).content

    def test_route_navigation_boundary_and_legend_render(self):
        content = self.page()
        self.assertIn("Public Traceability Map", content)
        self.assertIn('<a href="/traceability" aria-current="page">Traceability</a>', content)
        self.assertIn('aria-label="Breadcrumb"', content)
        self.assertIn("visualises declared relationships", content)
        self.assertIn("does not create or infer relationships", content)
        self.assertIn("not itself a governed object", content)
        self.assertIn("does not prove that no private", content)
        self.assertIn("Traceability reveals declared relationships without erasing", content)
        self.assertIn("Legend", content)
        self.assertIn("Declared Relationship", content)
        self.assertIn("Archive", archive.public_archive_explorer().content)

    def test_association_chain_renders_association_as_governed_node(self):
        content = self.page()
        self.assertIn("Canonical Record", content)
        self.assertIn("Governed Association", content)
        self.assertIn("Published Document", content)
        self.assertIn("declared by", content)
        self.assertIn("links to", content)
        self.assertIn(self.fixture.association["public_reference"], content)
        self.assertIn(self.second_association["public_reference"], content)
        self.assertIn("Supporting spreadsheet", content)
        self.assertIn("Source spreadsheet", content)
        self.assertIn("Open Canonical Record", content)
        self.assertIn("Open Association", content)
        self.assertIn("Open Published Document", content)
        self.assertIn("Structured Accessible View", content)
        self.assertNotIn("Private second association note", content)

    def test_public_eligibility_excludes_private_and_inactive_relationships(self):
        content = self.page()
        self.assertNotIn(str(self.private_association["public_reference"]), content)
        self.assertNotIn("This public note should not appear while private.", content)
        self.assertNotIn(str(self.inactive_association["public_reference"]), content)
        self.assertNotIn("This inactive public note should not appear.", content)

    def test_collection_membership_uses_non_containment_language(self):
        content = self.page(collection=self.fixture.collection["public_reference"])
        self.assertIn("Governed Collection Membership", content)
        self.assertIn(self.fixture.collection["public_reference"], content)
        self.assertIn("declares governed membership", content)
        self.assertIn("does not own, contain, or absorb", content)
        self.assertIn("Open Collection", content)

    def test_filters_active_summary_counts_and_pagination(self):
        content = self.page(
            search="woodstock",
            record="CMP-MC-20191202-001",
            relationship_type="source_document",
            media="spreadsheet",
            page_size=10,
        )
        self.assertIn("<strong>Canonical Record:</strong> CMP-MC-20191202-001", content)
        self.assertIn("<strong>Relationship type:</strong> Source document", content)
        self.assertIn("<strong>Media type:</strong> Spreadsheet", content)
        self.assertIn("<strong>Page:</strong> 1 of 1", content)
        self.assertIn('value="10" selected', content)
        self.assertIn("page_size%3D10", content)
        self.assertIn('value="source_document" selected', content)
        self.assertIn("relationship_type%3Dsource_document", content)
        self.assertIn("Published Documents shown", content)
        self.assertIn("Traceability chains shown", content)
        self.assertIn("Source spreadsheet", content)
        self.assertNotIn("Supporting spreadsheet</h3>", content)

    def test_document_collection_institution_year_and_no_match_filters(self):
        document_page = self.page(document=self.fixture.document["reference_identifier"])
        self.assertIn("Woodstock Member Usage 2019", document_page)
        self.assertIn("Supporting spreadsheet", document_page)
        institution_page = self.page(institution="Woodstock")
        self.assertIn("Woodstock", institution_page)
        year_page = self.page(year="2026", document_year="2019")
        self.assertIn("Woodstock Member Usage 2019", year_page)
        no_match = self.page(search="no-such-public-chain")
        self.assertIn("No public traceability relationships matched the current filters.", no_match)
        self.assertIn("Clear filters", no_match)
        self.assertNotIn("Page 1 of 1", no_match)

    def test_unique_counts_do_not_duplicate_record_or_document_identity(self):
        content = self.page(record="CMP-MC-20191202-001")
        self.assertIn("<span>Canonical Records shown</span><strong>1</strong>", content)
        self.assertIn("<span>Published Documents shown</span><strong>1</strong>", content)
        self.assertIn("<span>Governed Associations shown</span><strong>2</strong>", content)
        self.assertIn("<span>Traceability chains shown</span><strong>2</strong>", content)

    def test_empty_and_disconnected_states_are_distinct(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "pending"
            db_path = Path(temp_dir) / "records.db"
            conn = sqlite3.connect(db_path)
            conn.execute(
                """
                CREATE TABLE records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    reference TEXT NOT NULL,
                    record_type TEXT NOT NULL DEFAULT 'strike',
                    record_title TEXT,
                    title TEXT,
                    institution TEXT,
                    event_date TEXT,
                    summary TEXT,
                    version INTEGER NOT NULL DEFAULT 1,
                    generated_at TEXT NOT NULL,
                    trajectory TEXT,
                    system_state TEXT,
                    finding TEXT,
                    conditions_json TEXT,
                    report_json TEXT,
                    language TEXT NOT NULL DEFAULT 'en',
                    generated_by TEXT,
                    verification_hash TEXT NOT NULL,
                    exported_at TEXT NOT NULL,
                    is_latest INTEGER NOT NULL DEFAULT 1
                )
                """
            )
            conn.commit()
            conn.close()
            originals = (ac.DB_PATH, rda.DB_PATH, records.DB_PATH)
            try:
                ac.DB_PATH = db_path
                rda.DB_PATH = db_path
                records.DB_PATH = db_path
                with patch.dict(os.environ, {"CDE_DOCUMENT_INTAKE_ROOT": str(root)}, clear=False):
                    empty = traceability.public_traceability_map().content
            finally:
                ac.DB_PATH, rda.DB_PATH, records.DB_PATH = originals
        self.assertIn("No publicly eligible traceability relationships are currently available.", empty)

        conn = self._conn()
        try:
            empty_collection = ac.create_collection(
                conn,
                title="Empty Traceability Collection",
                institution_source="CDE",
                category="documentary_archive",
                description="Public collection with no active traceability members.",
                actor="admin-user",
                is_public=True,
                created_at="2026-07-23T13:00:00Z",
            )
        finally:
            conn.close()
        disconnected = self.page(collection=empty_collection["public_reference"])
        self.assertIn("Public object has no declared relationship in the selected view", disconnected)
        self.assertIn("private, administrative, historical or unpublished relationships", disconnected)

    def test_safe_traceability_return_helper_rejects_unsafe_values(self):
        self.assertEqual(
            "/traceability?search=woodstock&page=2",
            sanitize_traceability_return("/traceability?search=woodstock&page=2&unsupported=x"),
        )
        for unsafe in (
            "https://example.com/traceability?search=woodstock",
            "//example.com/traceability",
            "/admin",
            "/archive",
            "traceability?search=woodstock",
        ):
            with self.subTest(unsafe=unsafe):
                self.assertEqual("/traceability", sanitize_traceability_return(unsafe))

    def test_primary_public_navigation_includes_traceability_on_adjacent_pages(self):
        self.assertIn('href="/traceability">Traceability</a>', documents.public_document_page(self.fixture.document["intake_id"]).content)
        self.assertIn('href="/traceability">Traceability</a>', archive.public_archive_explorer().content)


if __name__ == "__main__":
    unittest.main()
