import asyncio
import unittest

from tests.test_admin_session import install_fastapi_stubs
from tests import test_public_archive_explorer as archive_fixture

install_fastapi_stubs()

from api.public_navigation import append_archive_return, sanitize_archive_return
from api.routes import archive, associations, collections, documents, records


class PublicNavigationInformationArchitectureTests(unittest.TestCase):
    def setUp(self):
        self.fixture = archive_fixture.PublicArchiveExplorerTests(
            methodName="test_landing_displays_counts_and_public_object_types"
        )
        self.fixture.setUp()

    def tearDown(self):
        self.fixture.tearDown()

    def test_archive_primary_navigation_and_breadcrumb(self):
        content = self.fixture.page()
        self.assertIn('aria-label="Primary public navigation"', content)
        self.assertIn('<a href="/archive" aria-current="page">Archive</a>', content)
        self.assertIn('aria-label="Breadcrumb"', content)
        self.assertIn('<span aria-current="page">Archive</span>', content)
        self.assertNotIn('href="/admin"', content)
        self.assertNotIn(">Administration<", content)

    def test_archive_results_use_badges_and_safe_return_state(self):
        content = self.fixture.page(search="woodstock", type="published_document", media="spreadsheet")
        self.assertIn("object-type-badge", content)
        self.assertIn("Published Document", content)
        self.assertIn("return_to=%2Farchive", content)
        self.assertIn("search%3Dwoodstock", content)
        self.assertIn("type%3Dpublished_document", content)
        self.assertIn("media%3Dspreadsheet", content)

    def test_public_document_breadcrumb_badge_and_return_link(self):
        return_to = "/archive?search=woodstock&media=spreadsheet"
        content = documents.public_document_page(self.fixture.document["intake_id"], return_to=return_to).content
        self.assertIn('aria-label="Breadcrumb"', content)
        self.assertIn("Published Documents", content)
        self.assertIn("Woodstock Member Usage 2019", content)
        self.assertIn("Back to Archive Explorer", content)
        self.assertIn('href="/archive?search=woodstock&amp;media=spreadsheet"', content)
        self.assertIn("object-type-badge-published-document", content)
        self.assertIn("Associated Civic Records", content)
        self.assertIn("View association", content)

    def test_public_association_breadcrumb_badges_and_endpoints(self):
        content = associations.public_association_page(
            self.fixture.association["public_reference"],
            return_to="/archive?type=record_document_association",
        ).content
        self.assertIn('aria-label="Breadcrumb"', content)
        self.assertIn("Associations", content)
        self.assertIn("Back to Archive Explorer", content)
        self.assertIn("object-type-badge-association", content)
        self.assertIn("object-type-badge-canonical-record", content)
        self.assertIn("object-type-badge-published-document", content)
        self.assertIn("View civic record", content)
        self.assertIn("View published document", content)

    def test_public_collection_breadcrumb_badges_and_member_links(self):
        content = collections.public_collection_page(
            self.fixture.collection["public_reference"],
            return_to="/archive?type=public_collection",
        ).content
        self.assertIn('aria-label="Breadcrumb"', content)
        self.assertIn("Collections", content)
        self.assertIn("Back to Archive Explorer", content)
        self.assertIn("object-type-badge-collection", content)
        self.assertIn("object-type-badge-published-document", content)
        self.assertIn("Woodstock Member Usage 2019", content)
        self.assertIn(f'/documents/{self.fixture.document["intake_id"]}', content)

    def test_public_record_breadcrumb_badge_and_return_link(self):
        content = asyncio.run(
            records.verify_record(
                "CMP-MC-20191202-001",
                return_to="/archive?search=Medical+Council&type=canonical_record",
            )
        ).content
        self.assertIn('aria-label="Breadcrumb"', content)
        self.assertIn("Canonical Records", content)
        self.assertIn("Back to Archive Explorer", content)
        self.assertIn("object-type-badge-canonical-record", content)
        self.assertIn('href="/archive?search=Medical+Council&amp;type=canonical_record"', content)
        self.assertIn("Associated Public Documents", content)

    def test_invalid_archive_return_values_fall_back(self):
        for unsafe in (
            "https://example.com/archive?search=woodstock",
            "//example.com/archive",
            "/admin",
            "/documents/abc",
            "archive?search=woodstock",
        ):
            self.assertEqual("/archive", sanitize_archive_return(unsafe))
        self.assertEqual(
            "/documents/example?return_to=%2Farchive",
            append_archive_return("/documents/example", "https://example.com/archive"),
        )
        content = documents.public_document_page(
            self.fixture.document["intake_id"],
            return_to="https://example.com/archive?search=woodstock",
        ).content
        self.assertIn('href="/archive"', content)
        self.assertNotIn("example.com", content)


if __name__ == "__main__":
    unittest.main()
