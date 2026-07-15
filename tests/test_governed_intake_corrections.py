import hashlib
import io
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from api.document_intake import load_pending_document, store_pending_document
from tests.test_admin_session import FakeHTTPException, FakeRequest, install_fastapi_stubs

install_fastapi_stubs()

from api import archive_collections as ac
from api import document_intake_corrections as dic
from api.routes import admin_session


PDF_BYTES = b"%PDF-1.7\ncorrection-source\n%%EOF\n"
SECOND_PDF_BYTES = b"%PDF-1.7\nsecond-source\n%%EOF\n"


class GovernedIntakeCorrectionTests(unittest.TestCase):
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
            cookies={admin_session.SESSION_COOKIE_NAME: admin_session.create_admin_session("admin-user")}
        )

    def tearDown(self):
        admin_session.DB_PATH, dic.DB_PATH, ac.DB_PATH = self.originals
        self.env.stop()
        self.temp_dir.cleanup()

    def _metadata(self, **overrides):
        metadata = {
            "title": "Wrong metadata title",
            "institution_source": "Civic Office",
            "document_date": "2026-07-15",
            "category": "Correction Source",
            "description": "Document with metadata assigned to the wrong preserved bytes.",
            "visibility": "private",
            "notes": "Private source note.",
            "reference_identifier": "WRONG-001",
        }
        metadata.update(overrides)
        return metadata

    def _store_source(self, data=PDF_BYTES):
        return store_pending_document(
            data=data,
            original_filename="source.pdf",
            content_type="application/pdf",
            actor="admin-user",
            root=self.root,
            **self._metadata(),
        )

    def _archive_source(self, data=PDF_BYTES):
        item = self._store_source(data)
        intake_id = item["intake_id"]
        for status, note in (
            ("under_review", "Begin source review."),
            ("approved", "Approve before archive."),
            ("archived", "Archived after identifying metadata mismatch."),
        ):
            admin_session.admin_document_intake_status_update(
                intake_id,
                self.request,
                new_status=status,
                admin_note=note,
            )
        return load_pending_document(intake_id, root=self.root)

    def _create_correction(self, source_id):
        return admin_session.admin_intake_correction_create(
            self.request,
            source_id,
            "metadata_document_mismatch",
            "The preserved bytes were assigned to the wrong public title.",
            "Correct the intake metadata while preserving exact bytes and source history.",
            "Corrected title",
            "Corrected description.",
            "Corrected Source",
            "Corrected Category",
            "2026-07-16",
            "CORR-001",
            "private",
            "Corrected private notes.",
        )

    def _authorise(self, reference):
        for state, note in (
            ("under_review", "Correction review started."),
            ("reviewed", "Correction reviewed."),
            ("authorised", "Correction authorised."),
        ):
            response = admin_session.admin_intake_correction_transition(
                reference,
                self.request,
                new_state=state,
                note=note,
            )
            self.assertIn(reference, response.content)

    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        dic.ensure_correction_tables(conn)
        return conn

    def test_correction_pages_require_authentication_and_navigation_is_present(self):
        with self.assertRaises(FakeHTTPException) as ctx:
            admin_session.admin_intake_corrections_page(FakeRequest())
        self.assertEqual(ctx.exception.status_code, 401)
        dashboard = admin_session.admin_dashboard_page(self.request).content
        self.assertIn("Manage Intake Corrections", dashboard)
        self.assertIn('href="/admin/intake-corrections"', dashboard)

    def test_source_must_be_archived_before_correction_can_start(self):
        active = self._store_source()
        with self.assertRaises(FakeHTTPException) as route_ctx:
            admin_session.admin_intake_correction_new_page(active["intake_id"], self.request)
        self.assertEqual(route_ctx.exception.status_code, 409)
        self.assertEqual(route_ctx.exception.detail, "intake_correction_source_not_archived")
        conn = self._conn()
        try:
            with self.assertRaisesRegex(ValueError, "intake_correction_source_not_archived"):
                dic.create_correction(
                    conn,
                    source_intake_id=active["intake_id"],
                    correction_type="metadata_document_mismatch",
                    correction_reason="Wrong metadata.",
                    correction_description="Wrong metadata.",
                    corrected_title="Corrected",
                    corrected_description="Corrected.",
                    corrected_institution_source="Corrected Source",
                    corrected_category="Corrected Category",
                    corrected_document_date="2026-07-16",
                    corrected_reference_identifier="CORR-001",
                    corrected_visibility="private",
                    corrected_notes="Corrected note.",
                    actor="admin-user",
                    root=self.root,
                )
        finally:
            conn.close()

    def test_correction_lifecycle_creates_corrected_pending_intake_with_exact_same_bytes(self):
        source = self._archive_source()
        response = self._create_correction(source["intake_id"])
        self.assertEqual(response.status_code, 201)
        self.assertIn("CDE-CORR-", response.content)
        conn = self._conn()
        try:
            correction = dic.list_corrections(conn)[0]
            reference = correction["correction_reference"]
        finally:
            conn.close()

        self._authorise(reference)
        completed = admin_session.admin_intake_correction_execute(reference, self.request)
        self.assertIn("completed", completed.content)

        conn = self._conn()
        try:
            correction = dic.get_correction(conn, reference)
            history = dic.correction_history(conn, reference)
        finally:
            conn.close()
        destination_id = correction["destination_intake_id"]
        self.assertIsNotNone(destination_id)
        self.assertNotEqual(destination_id, source["intake_id"])
        self.assertEqual(correction["source_sha256"], source["sha256_hash"])
        self.assertEqual(correction["destination_sha256"], source["sha256_hash"])
        self.assertEqual(correction["correction_state"], "completed")
        self.assertEqual([event["action"] for event in history], [
            "created",
            "review_started",
            "reviewed",
            "authorised",
            "corrected_intake_created",
            "completed",
        ])
        self.assertTrue(all(event["actor"] == "admin-user" for event in history))

        source_after = load_pending_document(source["intake_id"], root=self.root)
        destination = load_pending_document(destination_id, root=self.root)
        self.assertEqual(source_after["status"], "archived")
        self.assertEqual(source_after["title"], "Wrong metadata title")
        self.assertEqual(destination["status"], "pending")
        self.assertEqual(destination["title"], "Corrected title")
        self.assertEqual(destination["reference_identifier"], "CORR-001")
        self.assertTrue(destination["created_through_correction"])
        self.assertEqual(destination["correction_reference"], reference)
        self.assertEqual(destination["correction_source_intake_id"], source["intake_id"])
        self.assertEqual(destination["sha256_hash"], source["sha256_hash"])
        source_file = next((self.root / source["intake_id"]).glob("pending-*"))
        destination_file = next((self.root / destination_id).glob("pending-*"))
        self.assertEqual(source_file.read_bytes(), PDF_BYTES)
        self.assertEqual(destination_file.read_bytes(), PDF_BYTES)
        self.assertEqual(hashlib.sha256(destination_file.read_bytes()).hexdigest(), source["sha256_hash"])

        with self.assertRaisesRegex(ValueError, "document_intake_duplicate"):
            store_pending_document(
                data=PDF_BYTES,
                original_filename="duplicate.pdf",
                content_type="application/pdf",
                actor="admin-user",
                root=self.root,
                **self._metadata(title="Duplicate attempt"),
            )

    def test_execution_is_idempotently_rejected_after_completion(self):
        source = self._archive_source()
        self._create_correction(source["intake_id"])
        conn = self._conn()
        try:
            reference = dic.list_corrections(conn)[0]["correction_reference"]
        finally:
            conn.close()
        self._authorise(reference)
        first = admin_session.admin_intake_correction_execute(reference, self.request)
        self.assertIn("completed", first.content)
        with self.assertRaises(FakeHTTPException) as ctx:
            admin_session.admin_intake_correction_execute(reference, self.request)
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.detail, "intake_correction_authorisation_required")
        conn = self._conn()
        try:
            corrections = dic.list_corrections(conn)
        finally:
            conn.close()
        self.assertEqual(len(corrections), 1)

    def test_actor_identity_cannot_be_overridden_by_client_arguments(self):
        source = self._archive_source()
        with self.assertRaises(TypeError):
            admin_session.admin_intake_correction_create(
                self.request,
                source["intake_id"],
                "metadata_document_mismatch",
                "Reason.",
                "Description.",
                "Corrected title",
                "Corrected description.",
                "Corrected Source",
                "Corrected Category",
                "2026-07-16",
                "CORR-001",
                "private",
                "Notes.",
                actor="mallory",
            )
        self._create_correction(source["intake_id"])
        conn = self._conn()
        try:
            correction = dic.list_corrections(conn)[0]
            history = dic.correction_history(conn, correction["correction_reference"])
        finally:
            conn.close()
        self.assertEqual(correction["created_by"], "admin-user")
        self.assertNotIn("mallory", {event["actor"] for event in history})

    def test_source_and_destination_lineage_notices_render(self):
        source = self._archive_source()
        archived_page = admin_session.admin_document_intake_preview_page(source["intake_id"], self.request).content
        self.assertIn("Governed correction available", archived_page)
        self.assertIn(f'/admin/document-intake/{source["intake_id"]}/correction/new', archived_page)

        self._create_correction(source["intake_id"])
        conn = self._conn()
        try:
            reference = dic.list_corrections(conn)[0]["correction_reference"]
        finally:
            conn.close()
        self._authorise(reference)
        admin_session.admin_intake_correction_execute(reference, self.request)
        conn = self._conn()
        try:
            correction = dic.get_correction(conn, reference)
        finally:
            conn.close()
        source_page = admin_session.admin_document_intake_preview_page(source["intake_id"], self.request).content
        destination_page = admin_session.admin_document_intake_preview_page(correction["destination_intake_id"], self.request).content
        self.assertIn("completed corrected intake identity", source_page)
        self.assertIn(reference, source_page)
        self.assertIn(correction["destination_intake_id"], source_page)
        self.assertIn("created through a completed governed correction", destination_page)
        self.assertIn(source["intake_id"], destination_page)
        self.assertIn(source["sha256_hash"], destination_page)

    def test_correction_index_filters_by_source_destination_state_and_actor(self):
        source = self._archive_source()
        self._create_correction(source["intake_id"])
        conn = self._conn()
        try:
            reference = dic.list_corrections(conn)[0]["correction_reference"]
        finally:
            conn.close()
        self._authorise(reference)
        admin_session.admin_intake_correction_execute(reference, self.request)
        conn = self._conn()
        try:
            correction = dic.get_correction(conn, reference)
        finally:
            conn.close()
        self.assertIn(reference, admin_session.admin_intake_corrections_page(self.request, correction_reference=reference).content)
        self.assertIn(reference, admin_session.admin_intake_corrections_page(self.request, source_intake=source["intake_id"]).content)
        self.assertIn(reference, admin_session.admin_intake_corrections_page(self.request, destination_intake=correction["destination_intake_id"]).content)
        self.assertIn(reference, admin_session.admin_intake_corrections_page(self.request, correction_state="completed").content)
        self.assertIn(reference, admin_session.admin_intake_corrections_page(self.request, created_actor="admin-user").content)

    def test_correction_table_schema_is_idempotent_and_reference_is_server_generated(self):
        conn = self._conn()
        try:
            dic.ensure_correction_tables(conn)
            dic.ensure_correction_tables(conn)
            tables = {
                row[0]
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            }
            indexes = {
                row[0]
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()
            }
        finally:
            conn.close()
        self.assertIn("document_intake_corrections", tables)
        self.assertIn("document_intake_correction_history", tables)
        self.assertIn("idx_document_intake_corrections_reference", indexes)

        source = self._archive_source()
        self._create_correction(source["intake_id"])
        conn = self._conn()
        try:
            correction = dic.list_corrections(conn)[0]
        finally:
            conn.close()
        self.assertRegex(correction["correction_reference"], r"^CDE-CORR-20\d{6}-\d{3}$")
        self.assertNotEqual(correction["correction_reference"], str(correction["id"]))

    def test_archive_collection_admin_table_readability_refinement_is_present(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        ac.ensure_collection_tables(conn)
        try:
            collection = ac.create_collection(
                conn,
                title="Collection",
                subtitle="",
                institution_source="CDE",
                category="framework_publications",
                description="Archive collection.",
                public_note="Public note.",
                admin_note="Private note.",
                date_from="2026-07-01",
                date_to="2026-07-15",
                is_public=True,
                actor="admin-user",
                created_at="2026-07-15T10:00:00Z",
            )
            ac.update_collection(
                conn,
                collection["id"],
                title="Collection Updated",
                subtitle="",
                institution_source="CDE",
                category="framework_publications",
                description="Archive collection updated.",
                public_note="Public note.",
                admin_note="Private note updated.",
                date_from="2026-07-01",
                date_to="2026-07-15",
                is_public=True,
                actor="admin-user",
            )
            history = ac.collection_history(conn, collection["id"])
            updated = ac.get_collection(conn, collection["id"])
        finally:
            conn.close()
        index = admin_session.admin_collections_page(self.request).content
        detail = admin_session.admin_collection_detail_page(collection["id"], self.request).content
        self.assertIn("collection-admin-date-range", index)
        self.assertIn("collection-admin-visibility", index)
        self.assertIn("collection-admin-status", index)
        self.assertIn("min-width:165px", index)
        self.assertIn("min-width:130px;white-space:nowrap", index)
        self.assertIn('class="collection-history-state-details"', detail)
        self.assertIn("<summary>State details</summary>", detail)
        self.assertIn("<pre>", detail)
        self.assertIn("Private note updated.", detail)
        self.assertEqual(updated["id"], collection["id"])
        self.assertGreaterEqual(len(history), 2)


if __name__ == "__main__":
    unittest.main()
