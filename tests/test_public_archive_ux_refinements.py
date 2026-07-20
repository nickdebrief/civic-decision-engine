import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.test_admin_session import install_fastapi_stubs
from tests import test_public_archive_explorer as archive_fixture

install_fastapi_stubs()

from api import archive_collections as ac
from api import record_document_associations as rda
from api.routes import archive, records


class PublicArchiveUXRefinementsTests(unittest.TestCase):
    def setUp(self):
        self.fixture = archive_fixture.PublicArchiveExplorerTests(
            methodName="test_landing_displays_counts_and_public_object_types"
        )
        self.fixture.setUp()

    def tearDown(self):
        self.fixture.tearDown()

    def page(self, **params):
        return self.fixture.page(**params)

    def test_archive_hierarchy_and_boundary_order_are_clear(self):
        content = self.page()
        self.assertIn("Public Archive Explorer", content)
        self.assertIn("discovery interface over existing governed public objects", content)
        self.assertIn("Public Object Totals", content)
        self.assertIn("Current Archive View", content)
        self.assertIn("Search and Filters", content)
        self.assertIn("Archive Results", content)
        self.assertLess(content.index("Public Object Totals"), content.index("Current Archive View"))
        self.assertLess(content.index("Current Archive View"), content.index("Search and Filters"))
        self.assertLess(content.index("Search and Filters"), content.index("Archive Results"))
        self.assertIn("Every result links to the governed object that owns its identity", content)

    def test_result_cards_use_specific_action_labels_and_public_metadata(self):
        content = self.page(search="woodstock")
        self.assertIn("Open Canonical Record", content)
        self.assertIn("Open Published Document", content)
        self.assertIn("Open Association", content)
        self.assertIn("Open Collection", content)
        self.assertIn("Relevant date", content)
        self.assertIn("Institution / source", content)
        self.assertIn("Category", content)
        self.assertIn("Media type", content)
        self.assertIn("Spreadsheet", content)
        self.assertIn("NM-XLS-WOODSTOCK-2019-001", content)
        self.assertNotIn("Open governed object", content)

    def test_filters_active_summary_and_count_links_are_human_readable(self):
        content = self.page(
            search="woodstock",
            type="published_document",
            media="spreadsheet",
            sort="alphabetical",
        )
        self.assertIn('href="/archive?type=published_document"', content)
        self.assertIn('aria-label="Show Published Documents"', content)
        self.assertIn("<strong>Object type:</strong> Published Document", content)
        self.assertIn("<strong>Media type:</strong> Spreadsheet", content)
        self.assertIn("<strong>Sort:</strong> Alphabetical", content)
        self.assertIn('value="published_document" selected', content)
        self.assertIn('value="spreadsheet" selected', content)
        self.assertIn('value="alphabetical" selected', content)
        self.assertIn('href="/archive">Clear filters</a>', content)

    def test_pagination_preserves_query_state_and_omits_meaningless_links(self):
        page_one = self.page(search="woodstock", page_size=10, page=1)
        self.assertIn("Page 1 of 2", page_one)
        self.assertIn("Next page", page_one)
        self.assertIn("search=woodstock", page_one)
        self.assertIn("page_size=10", page_one)
        self.assertNotIn(">Previous page</a>", page_one)

        page_two = self.page(search="woodstock", page_size=10, page=2)
        self.assertIn("Page 2 of 2", page_two)
        self.assertIn("Previous page", page_two)
        self.assertNotIn(">Next page</a>", page_two)

        single_page = self.page(type="published_document", media="spreadsheet")
        self.assertNotIn('<nav class="archive-pagination"', single_page)

    def test_no_match_state_is_distinct_and_does_not_expose_private_objects(self):
        content = self.page(search="no-such-public-object")
        self.assertIn("No public objects matched the current filters.", content)
        self.assertIn("Clear filters", content)
        self.assertNotIn("Page 1 of 1", content)
        self.assertNotIn("Private spreadsheet note", content)
        self.assertNotIn("Private association note", content)

    def test_empty_archive_state_is_distinct_from_filtered_no_matches(self):
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
                    content = archive.public_archive_explorer().content
            finally:
                ac.DB_PATH, rda.DB_PATH, records.DB_PATH = originals

        self.assertIn("No eligible public objects are currently listed.", content)
        self.assertNotIn("No public objects matched the current filters.", content)
        self.assertNotIn("Page 1 of 1", content)

    def test_responsive_and_accessibility_markup_is_present(self):
        content = self.page()
        self.assertIn('aria-label="Breadcrumb"', content)
        self.assertIn('aria-labelledby="archive-filters-heading"', content)
        self.assertIn('aria-labelledby="archive-results-heading"', content)
        self.assertIn('aria-live="polite"', content)
        self.assertIn("archive-filter-help", content)
        self.assertIn("@media(max-width:640px)", content)
        self.assertIn('aria-label="Open Published Document:', content)


if __name__ == "__main__":
    unittest.main()
