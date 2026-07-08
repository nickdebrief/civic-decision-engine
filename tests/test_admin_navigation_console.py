import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from api.document_intake import store_pending_document, update_intake_status
from tests.test_admin_session import FakeHTTPException, FakeRequest, install_fastapi_stubs

install_fastapi_stubs()

from api.routes import admin_session


class AdminNavigationConsoleTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "pending"
        self.env = patch.dict(
            os.environ,
            {
                "CDE_ADMIN_PASSWORD": "admin-password",
                "CDE_ADMIN_SESSION_SECRET": "session-secret",
                "CDE_DOCUMENT_INTAKE_ROOT": str(self.root),
            },
            clear=False,
        )
        self.env.start()
        session = admin_session.create_admin_session()
        self.request = FakeRequest(
            cookies={admin_session.SESSION_COOKIE_NAME: session}
        )
        self.pending_id = self._store("Pending", b"%PDF-1.7\npending\n%%EOF")
        self.review_id = self._store("Review", b"%PDF-1.7\nreview\n%%EOF")
        update_intake_status(self.review_id, "under_review", root=self.root)

    def tearDown(self):
        self.env.stop()
        self.temp_dir.cleanup()

    def _store(self, title, data):
        item = store_pending_document(
            data=data,
            original_filename=f"{title.lower()}.pdf",
            content_type="application/pdf",
            title=f"{title} Document",
            institution_source="Civic Office",
            document_date="2026-07-08",
            category="Decision",
            description="Administrative intake document.",
            visibility="private",
            notes="Private note.",
            root=self.root,
        )
        return item["intake_id"]

    def test_authenticated_dashboard_loads_with_all_required_links(self):
        response = admin_session.admin_dashboard_page(self.request)
        content = response.content
        self.assertIn("CDE Administration Console", content)
        self.assertIn('href="/admin"', content)
        self.assertIn('href="/admin/document-intake#new-intake"', content)
        self.assertIn('href="/admin/document-intake#intake-management"', content)
        self.assertIn('href="/admin#open-record-evidence"', content)
        self.assertIn('href="/documents"', content)
        self.assertIn('/api/admin/session/logout', content)

    def test_unauthenticated_dashboard_is_denied(self):
        with self.assertRaises(FakeHTTPException) as ctx:
            admin_session.admin_dashboard_page(FakeRequest())
        self.assertEqual(ctx.exception.status_code, 401)

    def test_dashboard_displays_lifecycle_counts_and_review_queue_links(self):
        content = admin_session.admin_dashboard_page(self.request).content
        self.assertIn("Pending Intake</th><td>1", content)
        self.assertIn("Under Review</th><td>1", content)
        self.assertIn("Approved</th><td>0", content)
        self.assertIn("Published</th><td>0", content)
        self.assertIn("Archived</th><td>0", content)
        self.assertIn("Rejected</th><td>0", content)
        self.assertIn(f'/admin/document-intake/{self.pending_id}', content)
        self.assertIn(f'/admin/document-intake/{self.review_id}', content)

    def test_dashboard_renders_four_first_class_summary_cards(self):
        content = admin_session.admin_dashboard_page(self.request).content
        self.assertIn('aria-label="Administration summary"', content)
        for heading in (
            "Pending Intake",
            "Review Queue",
            "Record Evidence",
            "Public Library",
        ):
            self.assertIn(f"<h2>{heading}</h2>", content)
        self.assertIn('<span class="summary-value">1</span>', content)
        self.assertIn('<span class="summary-value">2</span>', content)
        self.assertIn('href="#open-record-evidence"', content)
        self.assertIn('href="/documents"', content)

    def test_record_evidence_card_describes_existing_inspection_capabilities(self):
        content = admin_session.admin_dashboard_page(self.request).content
        self.assertIn('id="open-record-evidence"', content)
        self.assertIn("determination traces", content)
        self.assertIn("dependency and stability views", content)
        self.assertIn("provenance", content)
        self.assertIn("Full Inspection report modes", content)
        self.assertIn('aria-label="Record reference"', content)
        self.assertIn("Open Record Evidence</button>", content)

    def test_shared_navigation_uses_current_record_reference_when_available(self):
        content = admin_session._render_admin_console_navigation("RECORD-2026-001")
        self.assertIn("Administration / Dashboard", content)
        self.assertIn("Document Intake", content)
        self.assertIn("Intake Management", content)
        self.assertIn(
            'href="/admin/records/RECORD-2026-001/evidence"', content
        )
        self.assertIn("Public Library", content)

    def test_intake_and_review_pages_include_shared_navigation(self):
        intake = admin_session.admin_document_intake_page(self.request).content
        review = admin_session.admin_document_intake_preview_page(
            self.pending_id, self.request
        ).content
        for content in (intake, review):
            self.assertIn('aria-label="Administration Console"', content)
            self.assertIn('href="/admin"', content)
            self.assertIn('href="/documents"', content)

    def test_private_review_link_remains_admin_protected(self):
        with self.assertRaises(FakeHTTPException) as ctx:
            admin_session.admin_document_intake_preview_page(
                self.pending_id, FakeRequest()
            )
        self.assertEqual(ctx.exception.status_code, 401)

    def test_login_contract_is_preserved(self):
        response = admin_session.admin_session_login("admin-password")
        self.assertEqual(response.content, {"ok": True, "role": "admin"})
        self.assertIn("cde_admin_session=", response.headers["Set-Cookie"])


if __name__ == "__main__":
    unittest.main()
