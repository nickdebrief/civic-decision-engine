import asyncio
import unittest

from tests.test_admin_session import install_fastapi_stubs
from tests import test_public_archive_explorer as archive_fixture

install_fastapi_stubs()

from api.routes import admin_session, records


class PublicNavigationCompletionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = archive_fixture.PublicArchiveExplorerTests(
            methodName="test_landing_displays_counts_and_public_object_types"
        )
        self.fixture.setUp()

    def tearDown(self):
        self.fixture.tearDown()

    def record_page(self, return_to: str | None = None) -> str:
        return asyncio.run(
            records.verify_record("CMP-MC-20191202-001", return_to=return_to)
        ).content

    def test_canonical_record_uses_public_navigation_model(self):
        content = self.record_page()
        self.assertIn('aria-label="Primary public navigation"', content)
        self.assertIn('<a href="/archive">Archive</a>', content)
        self.assertIn('aria-label="Breadcrumb"', content)
        self.assertIn(">Home</a>", content)
        self.assertIn(">Archive</a>", content)
        self.assertIn(">Canonical Records</a>", content)
        self.assertIn('<span aria-current="page">Initial Complaint to the Medical Council of Ireland</span>', content)
        self.assertIn("object-type-badge-canonical-record", content)
        self.assertIn("Object type: Canonical Record", content)
        self.assertIn("Back to Archive Explorer", content)
        self.assertIn('href="/archive"', content)

    def test_canonical_record_preserves_valid_archive_return_state(self):
        content = self.record_page(
            "/archive?search=Medical+Council&type=canonical_record&sort=reference&page=2"
        )
        self.assertIn(
            'href="/archive?search=Medical+Council&amp;type=canonical_record&amp;sort=reference&amp;page=2"',
            content,
        )

    def test_canonical_record_rejects_unsafe_archive_return_state(self):
        unsafe_values = (
            "https://example.com/archive?search=Medical",
            "//example.com/archive",
            "/admin",
            "/documents",
            "/archive?unsupported=value",
        )
        for unsafe in unsafe_values:
            with self.subTest(unsafe=unsafe):
                content = self.record_page(unsafe)
                self.assertIn('href="/archive"', content)
                self.assertNotIn("example.com", content)
                self.assertNotIn("unsupported=value", content)

    def test_shared_admin_navigation_links_public_archive_and_document_library(self):
        content = admin_session._render_admin_console_navigation(
            admin_session={"username": "admin-user"}
        )
        self.assertIn('aria-label="Administration Console"', content)
        self.assertIn('href="/archive">Public Archive Explorer</a>', content)
        self.assertIn('href="/documents">Public Document Library</a>', content)
        self.assertIn("Signed in as:", content)
        self.assertIn("<strong>admin-user</strong>", content)

    def test_public_navigation_does_not_expose_admin_links(self):
        content = self.record_page()
        public_nav = content.split('aria-label="Primary public navigation"', 1)[1].split("</nav>", 1)[0]
        self.assertNotIn("/admin", public_nav)
        self.assertNotIn("Administration", public_nav)


if __name__ == "__main__":
    unittest.main()
