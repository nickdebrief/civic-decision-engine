import asyncio
import hashlib
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from api.document_intake import store_pending_document, update_intake_status
from tests.test_admin_session import FakeHTTPException, FakeRequest, install_fastapi_stubs

install_fastapi_stubs()

from api import record_document_associations as associations
from api.routes import admin_session, documents, records


PDF_BYTES = b"%PDF-1.7\nassociation\n%%EOF\n"
JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01association-jpeg\xff\xd9"


class PublicRecordDocumentAssociationTests(unittest.TestCase):
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
                "RECORDS_DB_PATH": str(self.db_path),
            },
            clear=False,
        )
        self.env.start()
        self.original_admin_db = admin_session.DB_PATH
        self.original_records_db = records.DB_PATH
        self.original_association_db = associations.DB_PATH
        admin_session.DB_PATH = self.db_path
        records.DB_PATH = self.db_path
        associations.DB_PATH = self.db_path
        self._init_records_db()
        self.document_id = self._published_document(
            PDF_BYTES,
            filename="published.pdf",
            title="Published Association Document",
            reference="DOC-001",
            actor="nick",
        )
        self.image_id = self._published_document(
            JPEG_BYTES,
            filename="strike.jpg",
            title="Published Strike Image",
            reference="STRIKE-001",
            actor="nick",
        )
        self.pending_document_id = self._pending_document()
        session = admin_session.create_admin_session("admin-user")
        self.request = FakeRequest(cookies={admin_session.SESSION_COOKIE_NAME: session})

    def tearDown(self):
        admin_session.DB_PATH = self.original_admin_db
        records.DB_PATH = self.original_records_db
        associations.DB_PATH = self.original_association_db
        self.env.stop()
        self.temp_dir.cleanup()

    def _init_records_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """
            CREATE TABLE records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reference TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 1,
                supersedes TEXT,
                generated_at TEXT NOT NULL,
                trajectory TEXT,
                system_state TEXT,
                conditions_json TEXT,
                signals_json TEXT,
                finding TEXT,
                report_json TEXT,
                language TEXT NOT NULL DEFAULT 'en',
                generated_by TEXT NOT NULL DEFAULT 'Civic Decision Engine',
                verification_hash TEXT NOT NULL,
                exported_at TEXT NOT NULL,
                is_latest INTEGER NOT NULL DEFAULT 1,
                source_narrative TEXT
            )
            """
        )
        digest = hashlib.sha256(b"record-one").hexdigest()
        conn.execute(
            """
            INSERT INTO records (
                reference, version, generated_at, trajectory, system_state,
                conditions_json, signals_json, finding, report_json, language,
                generated_by, verification_hash, exported_at, is_latest, source_narrative
            ) VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, 'en', 'Civic Decision Engine', ?, ?, 1, '')
            """,
            (
                "REC-2026-001",
                "2026-07-01T09:00:00Z",
                "Stable",
                "Record system state",
                '["Institutional Delay"]',
                "[]",
                "Public record finding summary.",
                "{}",
                digest,
                "2026-07-01T10:00:00Z",
            ),
        )
        conn.commit()
        conn.close()

    def _published_document(self, data, *, filename, title, reference, actor):
        item = store_pending_document(
            data=data,
            original_filename=filename,
            content_type="application/octet-stream",
            title=title,
            institution_source="Civic Office",
            document_date="2026-07-09",
            category="Public Record Image" if filename.endswith(".jpg") else "Decision",
            description=f"Description for {title}.",
            visibility="private",
            notes="Private administrative notes must remain private.",
            reference_identifier=reference,
            actor="admin",
            uploaded_at="2026-07-09T10:00:00Z",
            root=self.root,
        )
        for status, timestamp, note in (
            ("under_review", "2026-07-09T11:00:00Z", "Review started."),
            ("approved", "2026-07-09T12:00:00Z", "Approved."),
            ("published", "2026-07-09T13:00:00Z", "Published."),
        ):
            update_intake_status(
                item["intake_id"],
                status,
                actor=actor,
                note=note,
                changed_at=timestamp,
                root=self.root,
            )
        return item["intake_id"]

    def _pending_document(self):
        item = store_pending_document(
            data=b"%PDF-1.7\npending\n%%EOF\n",
            original_filename="pending.pdf",
            content_type="application/pdf",
            title="Pending Association Document",
            institution_source="Private Office",
            document_date="2026-07-09",
            category="Private",
            description="Pending document.",
            visibility="private",
            notes="Private note.",
            reference_identifier="PENDING-001",
            root=self.root,
        )
        return item["intake_id"]

    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        associations.ensure_association_tables(conn)
        return conn

    def _create_association(self, **kwargs):
        conn = self._conn()
        try:
            return associations.create_association(
                conn,
                record_reference=kwargs.get("record_reference", "REC-2026-001"),
                document_id=kwargs.get("document_id", self.document_id),
                relationship_type=kwargs.get("relationship_type", "supporting_document"),
                public_label=kwargs.get("public_label", "Supporting document"),
                public_note=kwargs.get("public_note", "Public relationship note."),
                admin_note=kwargs.get("admin_note", "Private association note."),
                is_public=kwargs.get("is_public", True),
                actor=kwargs.get("actor", "admin-user"),
                created_at=kwargs.get("created_at", "2026-07-10T09:00:00Z"),
                root=self.root,
            )
        finally:
            conn.close()

    def test_admin_association_pages_require_authentication(self):
        with self.assertRaises(FakeHTTPException) as index_ctx:
            admin_session.admin_associations_page(FakeRequest())
        self.assertEqual(index_ctx.exception.status_code, 401)
        with self.assertRaises(FakeHTTPException) as new_ctx:
            admin_session.admin_association_new_page(FakeRequest())
        self.assertEqual(new_ctx.exception.status_code, 401)
        content = admin_session.admin_associations_page(self.request).content
        self.assertIn("Record–Document Associations", content)
        self.assertIn("Signed in as:", content)
        self.assertIn("Create association", content)

    def test_valid_association_uses_session_actor_and_creates_history(self):
        response = admin_session.admin_association_create(
            self.request,
            record_reference="REC-2026-001",
            document_id=self.document_id,
            relationship_type="source_document",
            public_label="Source document",
            public_note="Public note.",
            admin_note="Private admin note.",
            is_public="1",
        )
        self.assertEqual(response.status_code, 201)
        content = response.content
        self.assertIn("Source document", content)
        self.assertIn("admin-user", content)
        self.assertIn("Private admin note.", content)
        conn = self._conn()
        try:
            row = conn.execute("SELECT * FROM record_document_associations").fetchone()
            self.assertEqual(row["created_by"], "admin-user")
            self.assertEqual(row["record_reference"], "REC-2026-001")
            self.assertEqual(row["document_id"], self.document_id)
            history = associations.association_history(conn, row["id"])
            self.assertEqual(len(history), 1)
            self.assertEqual(history[0]["action_type"], "created")
            self.assertEqual(history[0]["actor"], "admin-user")
        finally:
            conn.close()

    def test_client_supplied_actor_cannot_override_attribution(self):
        request = FakeRequest(
            cookies={admin_session.SESSION_COOKIE_NAME: admin_session.create_admin_session("session-user")},
            query_params={"actor": "mallory", "username": "mallory"},
        )
        response = admin_session.admin_association_create(
            request,
            record_reference="REC-2026-001",
            document_id=self.image_id,
            relationship_type="preserved_visual_record",
            public_label="Preserved visual record",
            public_note="Image note.",
            admin_note="Admin note.",
            is_public="1",
        )
        self.assertIn("session-user", response.content)
        self.assertNotIn("mallory", response.content)
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT created_by FROM record_document_associations WHERE document_id = ?",
                (self.image_id,),
            ).fetchone()
            self.assertEqual(row["created_by"], "session-user")
        finally:
            conn.close()

    def test_missing_unpublished_invalid_and_duplicate_associations_are_rejected(self):
        with self.assertRaises(FakeHTTPException) as missing_record:
            admin_session.admin_association_create(
                self.request, "MISSING", self.document_id, "supporting_document", "", "", "note", "1"
            )
        self.assertEqual(missing_record.exception.status_code, 404)
        with self.assertRaises(FakeHTTPException) as unpublished:
            admin_session.admin_association_create(
                self.request, "REC-2026-001", self.pending_document_id, "supporting_document", "", "", "note", "1"
            )
        self.assertEqual(unpublished.exception.status_code, 404)
        with self.assertRaises(FakeHTTPException) as invalid_type:
            admin_session.admin_association_create(
                self.request, "REC-2026-001", self.document_id, "invented", "", "", "note", "1"
            )
        self.assertEqual(invalid_type.exception.status_code, 409)
        self._create_association()
        with self.assertRaises(FakeHTTPException) as duplicate:
            admin_session.admin_association_create(
                self.request, "REC-2026-001", self.document_id, "supporting_document", "", "", "note", "1"
            )
        self.assertEqual(duplicate.exception.status_code, 409)

    def test_update_preserves_record_document_and_creation_values(self):
        association = self._create_association(actor="original-admin")
        response = admin_session.admin_association_update(
            association["id"],
            self.request,
            relationship_type="related_document",
            public_label="Related document",
            public_note="Updated public note.",
            admin_note="Updated private note.",
            is_public="0",
        )
        self.assertIn("Related document", response.content)
        conn = self._conn()
        try:
            row = associations.get_association(conn, association["id"])
            self.assertEqual(row["record_reference"], "REC-2026-001")
            self.assertEqual(row["document_id"], self.document_id)
            self.assertEqual(row["created_by"], "original-admin")
            self.assertEqual(row["updated_by"], "admin-user")
            self.assertEqual(row["is_public"], 0)
            history = associations.association_history(conn, association["id"])
            self.assertEqual([item["action_type"] for item in history], ["created", "updated"])
        finally:
            conn.close()

    def test_deactivation_and_reactivation_are_explicit_and_preserve_history(self):
        association = self._create_association()
        deactivated = admin_session.admin_association_deactivate(
            association["id"], self.request, deactivation_note="Incorrect link."
        ).content
        self.assertIn("Inactive", deactivated)
        self.assertIn("Incorrect link.", deactivated)
        conn = self._conn()
        try:
            row = associations.get_association(conn, association["id"])
            self.assertEqual(row["is_active"], 0)
            self.assertEqual(row["deactivated_by"], "admin-user")
            history = associations.association_history(conn, association["id"])
            self.assertEqual(history[-1]["action_type"], "deactivated")
        finally:
            conn.close()
        reactivated = admin_session.admin_association_reactivate(
            association["id"], self.request, reactivation_note="Restored."
        ).content
        self.assertIn("Active", reactivated)
        conn = self._conn()
        try:
            history = associations.association_history(conn, association["id"])
            self.assertEqual([item["action_type"] for item in history], ["created", "deactivated", "reactivated"])
        finally:
            conn.close()

    def test_deactivation_requires_note_and_no_delete_control_is_rendered(self):
        association = self._create_association()
        with self.assertRaises(FakeHTTPException):
            admin_session.admin_association_deactivate(association["id"], self.request, deactivation_note="")
        detail = admin_session.admin_association_detail_page(association["id"], self.request).content
        self.assertNotIn("Delete association", detail)
        self.assertNotIn("method=\"delete\"", detail.lower())

    def test_association_index_filters_paginates_and_hides_private_paths(self):
        self._create_association(actor="alpha", created_at="2026-07-10T09:00:00Z")
        self._create_association(
            document_id=self.image_id,
            relationship_type="preserved_visual_record",
            public_label="Preserved visual record",
            actor="beta",
            created_at="2026-07-11T09:00:00Z",
        )
        content = admin_session.admin_associations_page(
            self.request, q="Strike", relationship_type="preserved_visual_record", actor="beta", page_size=1
        ).content
        self.assertIn("Total matching associations:</strong> 1", content)
        self.assertIn("Published Strike Image", content)
        self.assertIn("STRIKE-001", content)
        self.assertIn("Page 1 of 1", content)
        self.assertIn('class="association-table-wrapper"', content)
        self.assertNotIn(str(self.root), content)
        self.assertNotIn("Private administrative notes", content)
        invalid = admin_session.admin_associations_page(self.request, page="bad", page_size=500).content
        self.assertIn('name="page_size" type="number" min="1" max="100" value="100"', invalid)

    def test_public_record_page_shows_only_active_public_eligible_associations(self):
        association = self._create_association(public_note="Public facing note.")
        content = asyncio.run(records.verify_record("REC-2026-001")).content
        self.assertIn("Associated Public Documents", content)
        self.assertIn("Published Association Document", content)
        self.assertIn("DOC-001", content)
        self.assertIn("Supporting document", content)
        self.assertIn("Public facing note.", content)
        self.assertIn(f'href="/documents/{self.document_id}"', content)
        self.assertIn("does not by itself establish evidential sufficiency", content)
        self.assertNotIn("Private association note", content)
        self.assertNotIn(str(self.root), content)
        self.assertIn(hashlib.sha256(b"record-one").hexdigest(), content)
        admin_session.admin_association_deactivate(association["id"], self.request, "No longer public.")
        hidden = asyncio.run(records.verify_record("REC-2026-001")).content
        self.assertNotIn("Associated Public Documents", hidden)
        self.assertNotIn("Published Association Document", hidden)

    def test_public_document_page_shows_associated_records_without_changing_provenance(self):
        self._create_association(public_note="Visible only on record side.")
        content = documents.public_document_page(self.document_id).content
        self.assertIn("Associated Civic Records", content)
        self.assertIn("REC-2026-001", content)
        self.assertIn("Public record finding summary.", content)
        self.assertIn('href="/verify/REC-2026-001"', content)
        self.assertIn("Association records a declared relationship", content)
        self.assertIn("Publication Provenance", content)
        self.assertIn("Publication Pathway", content)
        self.assertNotIn("Private association note", content)
        self.assertNotIn("Visible only on record side.", content)
        self.assertEqual(content.count("Published."), 1)

    def test_non_public_and_ineligible_associations_do_not_render_publicly(self):
        private_assoc = self._create_association(is_public=False)
        record_content = asyncio.run(records.verify_record("REC-2026-001")).content
        document_content = documents.public_document_page(self.document_id).content
        self.assertNotIn("Associated Public Documents", record_content)
        self.assertNotIn("Associated Civic Records", document_content)
        admin_session.admin_association_update(
            private_assoc["id"],
            self.request,
            "supporting_document",
            "Supporting document",
            "Public note.",
            "Admin note.",
            "1",
        )
        update_intake_status(
            self.document_id,
            "archived",
            actor="admin-user",
            note="Archived.",
            changed_at="2026-07-10T14:00:00Z",
            root=self.root,
        )
        record_content = asyncio.run(records.verify_record("REC-2026-001")).content
        self.assertNotIn("Associated Public Documents", record_content)
        detail = admin_session.admin_association_detail_page(private_assoc["id"], self.request).content
        self.assertIn("Linked object is not currently publicly eligible", detail)

    def test_association_does_not_change_document_hash_or_public_document_behaviour(self):
        before = documents.public_document_page(self.image_id).content
        self._create_association(
            document_id=self.image_id,
            relationship_type="preserved_visual_record",
            public_label="Preserved visual record",
        )
        after = documents.public_document_page(self.image_id).content
        self.assertIn("Publication Provenance", after)
        self.assertIn("Publication Pathway", after)
        digest = hashlib.sha256(JPEG_BYTES).hexdigest()
        self.assertIn(digest, after)
        self.assertIn(digest, before)
        view = documents.public_document_image_view(self.image_id)
        download = documents.public_document_download(self.image_id)
        self.assertIn("inline", view.headers.get("Content-Disposition", ""))
        self.assertIn("attachment", download.headers.get("Content-Disposition", ""))
        self.assertEqual(Path(view.path).read_bytes(), JPEG_BYTES)
        self.assertEqual(Path(download.path).read_bytes(), JPEG_BYTES)

    def test_public_pages_do_not_expose_admin_identity_or_public_mutation_controls(self):
        self._create_association()
        record_content = asyncio.run(records.verify_record("REC-2026-001")).content
        document_content = documents.public_document_page(self.document_id).content
        for content in (record_content, document_content):
            self.assertNotIn("Signed in as", content)
            self.assertNotIn("Update association", content)
            self.assertNotIn("Deactivate association", content)
            self.assertNotIn("/api/admin/session/associations", content)
            self.assertNotIn("session-secret", content)
            self.assertNotIn("admin-password", content)


if __name__ == "__main__":
    unittest.main()
