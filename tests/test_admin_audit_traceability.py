import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from api.document_intake import (
    load_pending_document,
    store_pending_document,
    update_intake_status,
)
from tests.test_admin_session import FakeHTTPException, FakeRequest, install_fastapi_stubs
from tests.test_admin_document_intake import JPEG_BYTES, PNG_BYTES

install_fastapi_stubs()

from api.routes import admin_session, documents


PDF_BYTES = b"%PDF-1.7\naudit\n%%EOF"


class AdminAuditTraceabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "pending"
        self.env = patch.dict(
            os.environ,
            {
                "ADMIN_USERNAME": "admin-user",
                "ADMIN_PASSWORD": "admin-password",
                "CDE_ADMIN_SESSION_SECRET": "session-secret",
                "CDE_DOCUMENT_INTAKE_ROOT": str(self.root),
            },
            clear=False,
        )
        self.env.start()
        session = admin_session.create_admin_session("admin-user")
        self.request = FakeRequest(cookies={admin_session.SESSION_COOKIE_NAME: session})
        self.alpha_id = self._store(
            data=PDF_BYTES,
            filename="alpha.pdf",
            title="Alpha Governance Record",
            reference="REF-ALPHA",
            category="Governance",
            actor="admin",
            uploaded_at="2026-07-09T09:00:00Z",
        )
        update_intake_status(
            self.alpha_id,
            "under_review",
            actor="nick",
            note="Begin structured review.",
            changed_at="2026-07-10T10:00:00Z",
            root=self.root,
        )
        update_intake_status(
            self.alpha_id,
            "approved",
            actor="nick",
            note="Approved for publication review.",
            changed_at="2026-07-11T10:00:00Z",
            root=self.root,
        )
        self.beta_id = self._store(
            data=JPEG_BYTES,
            filename="strike_001.jpg",
            title="Strike Archive Image",
            reference="STRIKE-001",
            category="Public Record Image",
            actor="admin",
            uploaded_at="2026-07-09T09:00:00Z",
        )
        update_intake_status(
            self.beta_id,
            "under_review",
            actor="nick",
            note="Image review started.",
            changed_at="2026-07-12T08:00:00Z",
            root=self.root,
        )
        self.gamma_id = self._store(
            data=PNG_BYTES,
            filename="gamma.png",
            title="Gamma Record Without Reference",
            reference=None,
            category="Image",
            actor="admin",
            uploaded_at="2026-07-08T08:00:00Z",
        )

    def tearDown(self):
        self.env.stop()
        self.temp_dir.cleanup()

    def _store(self, *, data, filename, title, reference, category, actor, uploaded_at):
        item = store_pending_document(
            data=data,
            original_filename=filename,
            content_type="application/octet-stream",
            title=title,
            institution_source="Civic Office",
            document_date="2026-07-08",
            category=category,
            description=f"Description for {title}.",
            visibility="private",
            notes="Internal note.",
            reference_identifier=reference,
            actor=actor,
            uploaded_at=uploaded_at,
            root=self.root,
        )
        return item["intake_id"]

    def page(self, **kwargs):
        response = admin_session.admin_audit_page(self.request, **kwargs)
        return response.content

    def test_unauthenticated_and_invalid_sessions_cannot_access_audit_page(self):
        with self.assertRaises(FakeHTTPException) as unauthenticated:
            admin_session.admin_audit_page(FakeRequest())
        self.assertEqual(unauthenticated.exception.status_code, 401)
        with self.assertRaises(FakeHTTPException) as invalid:
            admin_session.admin_audit_page(
                FakeRequest(cookies={admin_session.SESSION_COOKIE_NAME: "forged"})
            )
        self.assertEqual(invalid.exception.status_code, 401)

    def test_authenticated_audit_page_renders_session_identity_without_secrets(self):
        content = self.page()
        self.assertIn("Administrative Audit", content)
        self.assertIn("Signed in as:", content)
        self.assertIn("<strong>admin-user</strong>", content)
        self.assertNotIn("admin-password", content)
        self.assertNotIn("session-secret", content)
        self.assertNotIn("CDE_ADMIN_SESSION_SECRET", content)
        login = admin_session.admin_dashboard_page(FakeRequest()).content
        self.assertNotIn("<strong>admin-user</strong>", login)

    def test_client_supplied_identity_does_not_override_signed_session_identity(self):
        request = FakeRequest(
            cookies={admin_session.SESSION_COOKIE_NAME: admin_session.create_admin_session("session-user")},
            query_params={"username": "mallory", "actor": "mallory"},
        )
        content = admin_session.admin_audit_page(request, actor="mallory").content
        self.assertIn("<strong>session-user</strong>", content)
        self.assertNotIn("<strong>mallory</strong>", content)
        self.assertIn("Total matching audit events:</strong> 0", content)

    def test_existing_lifecycle_history_events_are_rendered_without_rewriting_values(self):
        before = load_pending_document(self.alpha_id, root=self.root)["status_history"]
        content = self.page(q="Alpha")
        self.assertIn("Total matching audit events:</strong> 3", content)
        self.assertIn("Alpha Governance Record", content)
        self.assertIn("alpha.pdf", content)
        self.assertIn("REF-ALPHA", content)
        self.assertIn("2026-07-09T09:00:00Z", content)
        self.assertIn("Initial state", content)
        self.assertIn("Pending Intake", content)
        self.assertIn("Under Review", content)
        self.assertIn("Approved", content)
        self.assertIn("admin", content)
        self.assertIn("nick", content)
        self.assertIn("Begin structured review.", content)
        self.assertIn("Approved for publication review.", content)
        after = load_pending_document(self.alpha_id, root=self.root)["status_history"]
        self.assertEqual(before, after)

    def test_missing_reference_identifier_uses_neutral_display_without_inventing_value(self):
        content = self.page(q="Gamma")
        self.assertIn("Gamma Record Without Reference", content)
        self.assertIn("gamma.png", content)
        self.assertIn("—", content)
        self.assertNotIn("REF-GAMMA", content)

    def test_rows_link_to_correct_authenticated_review_page_and_hide_storage_paths(self):
        content = self.page(q="Strike")
        self.assertIn(f'href="/admin/document-intake/{self.beta_id}"', content)
        self.assertIn("Review document", content)
        self.assertNotIn(str(self.root), content)
        self.assertNotIn("pending-", content)

    def test_newest_first_ordering_and_equal_timestamp_ordering_are_deterministic(self):
        events = admin_session._collect_admin_audit_events(
            [load_pending_document(self.alpha_id, root=self.root), load_pending_document(self.beta_id, root=self.root)]
        )
        timestamps = [event["timestamp"] for event in events]
        self.assertEqual(timestamps, sorted(timestamps, reverse=True))
        equal_time_events = [event for event in events if event["timestamp"] == "2026-07-09T09:00:00Z"]
        self.assertEqual(
            equal_time_events,
            sorted(
                equal_time_events,
                key=lambda event: (event["timestamp"], event["intake_id"], event["event_index"]),
                reverse=True,
            ),
        )

    def test_pagination_limits_results_and_preserves_filters(self):
        content = self.page(q="Record", page=1, page_size=2)
        self.assertIn("Total matching audit events:</strong> 4", content)
        self.assertIn("Page 1 of 2", content)
        self.assertIn("Next page", content)
        self.assertIn("q=Record", content)
        self.assertIn("page=2", content)
        content_page_two = self.page(q="Record", page=2, page_size=2)
        self.assertIn("Page 2 of 2", content_page_two)
        invalid = self.page(q="Record", page="bad", page_size=500)
        self.assertIn("Page 1 of 1", invalid)
        self.assertIn('name="page_size" type="number" min="1" max="100" value="100"', invalid)

    def test_filters_apply_with_and_semantics(self):
        self.assertIn("Total matching audit events:</strong> 1", self.page(actor="nick", new_status="approved"))
        self.assertIn("Approved for publication review.", self.page(actor="nick", new_status="approved"))
        self.assertIn("Total matching audit events:</strong> 3", self.page(actor="admin", previous_status=""))
        self.assertIn("Total matching audit events:</strong> 1", self.page(current_status="approved", new_status="pending"))
        self.assertIn("Total matching audit events:</strong> 2", self.page(document_format="jpeg"))
        self.assertIn("Total matching audit events:</strong> 2", self.page(date_from="2026-07-10", date_to="2026-07-11"))
        self.assertIn("Total matching audit events:</strong> 1", self.page(q="STRIKE-001", actor="nick", new_status="under_review"))
        self.assertIn("Total matching audit events:</strong> 0", self.page(q="<script>"))
        self.assertIn("&lt;script&gt;", self.page(q="<script>"))

    def test_audit_page_is_read_only_and_does_not_render_lifecycle_controls(self):
        content = self.page()
        self.assertNotIn('/api/admin/session/document-intake/', content)
        self.assertNotIn("Declare published", content)
        self.assertNotIn("Update private notes", content)
        self.assertNotIn("Delete", content)
        self.assertNotIn("Archive</button>", content)

    def test_audit_table_has_semantic_classes_and_responsive_wrapper(self):
        content = self.page()
        for snippet in (
            'class="audit-table-wrapper"',
            'class="audit-table"',
            'class="audit-timestamp"',
            'class="audit-document"',
            'class="audit-reference"',
            'class="audit-filename"',
            'class="audit-previous-status"',
            'class="audit-new-status"',
            'class="audit-actor"',
            'class="audit-note"',
            'class="audit-current-status"',
            'class="audit-actions"',
            "min-width:180px",
            "min-width:145px",
            "min-width:120px",
            "min-width:260px",
        ):
            self.assertIn(snippet, content)
        self.assertIn("Begin structured review.", content)

    def test_shared_navigation_and_dashboard_include_administrative_audit(self):
        dashboard = admin_session.admin_dashboard_page(self.request).content
        self.assertIn("Administrative Audit", dashboard)
        self.assertIn('href="/admin/audit"', dashboard)
        self.assertIn("Open Administrative Audit", dashboard)
        audit = self.page()
        self.assertIn("Administration / Dashboard", audit)
        self.assertIn("Document Intake", audit)
        self.assertIn("Intake Management", audit)
        self.assertIn("Record Evidence", audit)
        self.assertIn("Public Document Library", audit)

    def test_public_document_and_image_behaviour_remains_unchanged(self):
        update_intake_status(
            self.beta_id,
            "approved",
            actor="nick",
            note="Approved image.",
            changed_at="2026-07-12T09:00:00Z",
            root=self.root,
        )
        update_intake_status(
            self.beta_id,
            "published",
            actor="nick",
            note="Published image.",
            changed_at="2026-07-12T10:00:00Z",
            root=self.root,
        )
        listed = documents.public_document_library().content
        self.assertIn("Strike Archive Image", listed)
        view = documents.public_document_image_view(self.beta_id)
        download = documents.public_document_download(self.beta_id)
        self.assertEqual(view.media_type, "image/jpeg")
        self.assertIn("inline", view.headers.get("Content-Disposition", ""))
        self.assertEqual(Path(view.path).read_bytes(), JPEG_BYTES)
        self.assertEqual(download.media_type, "image/jpeg")
        self.assertIn("attachment", download.headers.get("Content-Disposition", ""))
        self.assertEqual(Path(download.path).read_bytes(), JPEG_BYTES)

    def test_private_document_audit_entries_are_admin_only_and_not_publicly_listed(self):
        audit_content = self.page(q="Gamma")
        self.assertIn("Gamma Record Without Reference", audit_content)
        library_content = documents.public_document_library().content
        self.assertNotIn("Gamma Record Without Reference", library_content)
        with self.assertRaises(FakeHTTPException):
            documents.public_document_page(self.gamma_id)


if __name__ == "__main__":
    unittest.main()
