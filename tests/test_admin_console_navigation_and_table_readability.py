import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from api.document_intake import load_pending_document, store_pending_document
from tests.test_admin_session import FakeHTTPException, FakeRequest, install_fastapi_stubs

install_fastapi_stubs()

from api import archive_collections as ac
from api import document_intake_corrections as dic
from api.routes import admin_session


PDF_BYTES = b"%PDF-1.7\nv12.16-admin-readability\n%%EOF\n"
CORRECTION_BYTES = b"%PDF-1.7\nv12.16-correction-source\n%%EOF\n"


class AdminConsoleNavigationAndTableReadabilityTests(unittest.TestCase):
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
                "CDE_DOCUMENT_INTAKE_MAX_BYTES": "1048576",
                "RECORDS_DB_PATH": str(self.db_path),
            },
            clear=False,
        )
        self.env.start()
        self.originals = (admin_session.DB_PATH, dic.DB_PATH, ac.DB_PATH)
        admin_session.DB_PATH = self.db_path
        dic.DB_PATH = self.db_path
        ac.DB_PATH = self.db_path
        self.request = FakeRequest(
            cookies={
                admin_session.SESSION_COOKIE_NAME: admin_session.create_admin_session(
                    "admin-user"
                )
            }
        )

    def tearDown(self):
        admin_session.DB_PATH, dic.DB_PATH, ac.DB_PATH = self.originals
        self.env.stop()
        self.temp_dir.cleanup()

    def _store_document(self, *, title="Long Governance Intake", data=PDF_BYTES):
        return store_pending_document(
            data=data,
            original_filename="long-governance-document-name.pdf",
            content_type="application/pdf",
            title=title,
            institution_source="Civic Office",
            document_date="2026-07-15",
            category="Governance Evidence",
            description="Administrative document for table readability tests.",
            visibility="private",
            notes="Private note.",
            actor="admin-user",
            reference_identifier="READ-001",
            root=self.root,
        )

    def _archive_source(self, *, data=CORRECTION_BYTES):
        item = self._store_document(
            title="Source intake with mismatched metadata",
            data=data,
        )
        for status, note in (
            ("under_review", "Begin source review."),
            ("approved", "Approve before correction."),
            ("archived", "Archived for governed correction."),
        ):
            admin_session.admin_document_intake_status_update(
                item["intake_id"],
                self.request,
                new_status=status,
                admin_note=note,
            )
        return load_pending_document(item["intake_id"], root=self.root)

    def _create_correction(self, *, data=CORRECTION_BYTES):
        source = self._archive_source(data=data)
        response = admin_session.admin_intake_correction_create(
            self.request,
            source["intake_id"],
            "metadata_document_mismatch",
            "Metadata mismatch confirmed.",
            "Correct metadata while preserving the exact uploaded bytes.",
            "Corrected governance title",
            "Corrected description.",
            "Corrected Source",
            "Corrected Category",
            "2026-07-16",
            "READ-CORR-001",
            "private",
            "Corrected private notes.",
        )
        self.assertEqual(response.status_code, 201)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            dic.ensure_correction_tables(conn)
            return dic.list_corrections(conn)[0]
        finally:
            conn.close()

    def _create_collection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            ac.ensure_collection_tables(conn)
            collection = ac.create_collection(
                conn,
                title="Strike Archive Governance Table",
                subtitle="Administrative collection identity",
                institution_source="Nick Moloney",
                category="public_accountability_archive",
                description="Governed archive collection for readability testing.",
                public_note="Public collection note.",
                admin_note="Private collection note.",
                date_from="2025-06-10",
                date_to="2026-07-15",
                is_public=False,
                actor="admin-user",
                created_at="2026-07-15T10:00:00Z",
            )
            return ac.update_collection(
                conn,
                collection["id"],
                title="Strike Archive Governance Table Updated",
                subtitle="Administrative collection identity",
                institution_source="Nick Moloney",
                category="public_accountability_archive",
                description="Updated governed archive collection.",
                public_note="Updated public note.",
                admin_note="Updated private note.",
                date_from="2025-06-10",
                date_to="2026-07-15",
                is_public=False,
                actor="admin-user",
            )
        finally:
            conn.close()

    def test_dashboard_has_first_class_document_intake_and_correction_cards(self):
        content = admin_session.admin_dashboard_page(self.request).content
        self.assertIn("admin-dashboard-grid", content)
        self.assertIn("Document Intake", content)
        self.assertIn("Intake Corrections", content)
        self.assertIn('href="/admin/document-intake#new-intake"', content)
        self.assertIn('href="/admin/intake-corrections"', content)
        self.assertIn("Open Intake Corrections", content)
        self.assertLess(
            content.index("<h2>Document Intake</h2>"),
            content.index("<h2>Pending Intake</h2>"),
        )
        self.assertLess(
            content.index("<h2>Review Queue</h2>"),
            content.index("<h2>Intake Corrections</h2>"),
        )
        self.assertLess(
            content.index("<h2>Intake Corrections</h2>"),
            content.index("<h2>Administrative Audit</h2>"),
        )

    def test_admin_pages_remain_protected(self):
        for route in (
            admin_session.admin_document_intake_page,
            admin_session.admin_intake_corrections_page,
            admin_session.admin_collections_page,
            admin_session.admin_audit_page,
        ):
            with self.assertRaises(FakeHTTPException):
                route(FakeRequest())

    def test_intake_management_table_has_readability_hooks(self):
        self._store_document()
        content = admin_session.admin_document_intake_page(self.request).content
        self.assertIn('class="admin-table-scroll intake-management-table-wrapper"', content)
        self.assertIn('class="admin-data-table intake-management-table"', content)
        for css_class in (
            "intake-title col-title",
            "intake-filename col-filename",
            "intake-status col-status",
            "intake-upload-date col-timestamp",
            "intake-actions col-actions",
        ):
            self.assertIn(css_class, content)
        self.assertIn("long-governance-document-name.pdf", content)

    def test_document_status_history_has_responsive_column_hooks(self):
        item = self._store_document()
        admin_session.admin_document_intake_status_update(
            item["intake_id"],
            self.request,
            new_status="under_review",
            admin_note="Begin review with a long note that should remain fully visible.",
        )
        content = admin_session.admin_document_intake_preview_page(
            item["intake_id"], self.request
        ).content
        self.assertIn('aria-label="Status history table"', content)
        self.assertIn('class="status-history-wrapper audit-table-wrapper"', content)
        self.assertIn('<col class="col-timestamp">', content)
        self.assertIn('<col class="col-status">', content)
        self.assertIn('<col class="col-actor">', content)
        self.assertIn('<col class="col-note">', content)
        self.assertIn("Begin review with a long note", content)
        self.assertIn("admin-user", content)

    def test_intake_corrections_index_and_pathway_have_readable_tables(self):
        correction = self._create_correction(
            data=b"%PDF-1.7\nv12.16-second-correction-source\n%%EOF\n"
        )
        index = admin_session.admin_intake_corrections_page(self.request).content
        self.assertIn('aria-label="Intake Corrections table"', index)
        self.assertIn("intake-corrections-table", index)
        self.assertIn("correction-reference col-reference", index)
        self.assertIn("correction-state col-state", index)

        detail = admin_session.admin_intake_correction_detail_page(
            correction["correction_reference"], self.request
        ).content
        self.assertIn('aria-label="Correction Pathway table"', detail)
        self.assertIn("correction-pathway-table admin-data-table", detail)
        self.assertIn("correction-pathway-timestamp col-timestamp", detail)
        self.assertIn("correction-pathway-state col-state", detail)
        self.assertIn("correction-pathway-note col-note", detail)
        self.assertIn("admin-user", detail)
        self.assertIn("Metadata mismatch confirmed.", detail)

    def test_archive_collection_index_and_history_have_readable_tables(self):
        collection = self._create_collection()
        index = admin_session.admin_collections_page(self.request).content
        self.assertIn('aria-label="Archive Collections table"', index)
        self.assertIn("collection-admin-table admin-data-table", index)
        self.assertIn("collection-admin-reference col-reference", index)
        self.assertIn("collection-admin-created col-timestamp", index)
        self.assertIn("collection-admin-actions col-actions", index)

        detail = admin_session.admin_collection_detail_page(
            collection["id"], self.request
        ).content
        self.assertIn('aria-label="Archive Collection history table"', detail)
        self.assertIn("collection-history-table admin-data-table", detail)
        self.assertIn("collection-history-timestamp col-timestamp", detail)
        self.assertIn("collection-history-note col-note", detail)
        self.assertIn('data-readability-class="history-state-details"', detail)
        self.assertIn("<summary>State details</summary>", detail)

    def test_administrative_audit_keeps_existing_events_with_shared_hooks(self):
        item = self._store_document()
        admin_session.admin_document_intake_status_update(
            item["intake_id"],
            self.request,
            new_status="under_review",
            admin_note="Audit table note.",
        )
        content = admin_session.admin_audit_page(self.request).content
        self.assertIn('aria-label="Administrative Audit table"', content)
        self.assertIn('class="audit-table-wrapper"', content)
        self.assertIn('<col class="col-timestamp">', content)
        self.assertIn('<col class="col-actor">', content)
        self.assertIn('<col class="col-note">', content)
        self.assertIn("Audit table note.", content)
        self.assertIn("admin-user", content)

    def test_duplicate_detection_and_correction_destination_behaviour_remain_unchanged(self):
        first = self._store_document(data=PDF_BYTES)
        with self.assertRaises(ValueError):
            store_pending_document(
                data=PDF_BYTES,
                original_filename="duplicate.pdf",
                content_type="application/pdf",
                title="Duplicate",
                institution_source="Civic Office",
                document_date="2026-07-15",
                category="Governance Evidence",
                description="Duplicate bytes.",
                visibility="private",
                notes="Private note.",
                actor="admin-user",
                root=self.root,
            )
        self.assertEqual(load_pending_document(first["intake_id"], root=self.root)["status"], "pending")

        correction = self._create_correction()
        for state, note in (
            ("under_review", "Correction review started."),
            ("reviewed", "Correction reviewed."),
            ("authorised", "Correction authorised."),
        ):
            admin_session.admin_intake_correction_transition(
                correction["correction_reference"],
                self.request,
                new_state=state,
                note=note,
            )
        admin_session.admin_intake_correction_execute(
            correction["correction_reference"], self.request
        )
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            dic.ensure_correction_tables(conn)
            completed = dic.get_correction(conn, correction["correction_reference"])
        finally:
            conn.close()
        destination = load_pending_document(completed["destination_intake_id"], root=self.root)
        self.assertEqual(destination["status"], "pending")
        self.assertEqual(destination["sha256_hash"], completed["source_sha256"])


if __name__ == "__main__":
    unittest.main()
