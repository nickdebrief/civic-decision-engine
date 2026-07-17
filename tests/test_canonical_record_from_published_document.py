import asyncio
import hashlib
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from api.document_intake import load_pending_document, store_pending_document, update_intake_status
from tests.test_admin_session import FakeRequest, install_fastapi_stubs

install_fastapi_stubs()

from api import record_document_associations as associations
from api.routes import admin_session, documents, records


PDF_BYTES = b"%PDF-1.7\nmedical-council-evidence-package\n%%EOF\n"


class CanonicalRecordFromPublishedDocumentTests(unittest.TestCase):
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
        records.init_db()
        self.document_id = self._published_document()
        session = admin_session.create_admin_session("admin-user")
        self.request = FakeRequest(cookies={admin_session.SESSION_COOKIE_NAME: session})

    def tearDown(self):
        admin_session.DB_PATH = self.original_admin_db
        records.DB_PATH = self.original_records_db
        associations.DB_PATH = self.original_association_db
        self.env.stop()
        self.temp_dir.cleanup()

    def _published_document(self):
        item = store_pending_document(
            data=PDF_BYTES,
            original_filename="initial-complaint-evidence-package.pdf",
            content_type="application/pdf",
            title="Initial Complaint Evidence Package — Medical Council of Ireland",
            institution_source="Nick Moloney",
            document_date="2019-12-02",
            category="Evidence Package",
            description=(
                "Initial evidence package submitted with the formal Medical Council "
                "of Ireland complaint on 2 December 2019."
            ),
            visibility="private",
            notes="Private administrative notes.",
            reference_identifier="NM-EVID-PKG-20191202-001",
            actor="admin-user",
            uploaded_at="2026-07-16T10:00:00Z",
            root=self.root,
        )
        for status, timestamp, note in (
            ("under_review", "2026-07-16T11:00:00Z", "Review started."),
            ("approved", "2026-07-16T12:00:00Z", "Approved."),
            ("published", "2026-07-16T13:00:00Z", "Published."),
        ):
            update_intake_status(
                item["intake_id"],
                status,
                actor="admin-user",
                note=note,
                changed_at=timestamp,
                root=self.root,
            )
        return item["intake_id"]

    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        associations.ensure_association_tables(conn)
        return conn

    def _create_record(self, *, create_association=None):
        return admin_session.admin_canonical_record_from_document_create(
            self.document_id,
            self.request,
            record_type="complaint",
            reference="CMP-MC-20191202-001",
            record_title="Initial Complaint to the Medical Council of Ireland",
            institution="Medical Council of Ireland",
            event_date="2019-12-02",
            summary=(
                "Formal complaint submitted to the Medical Council of Ireland on "
                "2 December 2019, accompanied by an initial evidence package and "
                "supporting material."
            ),
            trajectory="Submitted",
            system_state="Complaint record created from Published document context.",
            conditions="FORMAL_COMPLAINT_SUBMITTED",
            signals="INITIAL_EVIDENCE_PACKAGE_PRESENT",
            source_narrative="Created from Published document: NM-EVID-PKG-20191202-001",
            create_association=create_association,
            association_public_label="Initial Complaint Evidence Package",
            association_public_note=(
                "Initial evidence package submitted with the formal Medical Council "
                "of Ireland complaint on 2 December 2019."
            ),
        )

    def test_published_document_admin_page_exposes_create_canonical_record_action(self):
        content = admin_session.admin_document_intake_preview_page(
            self.document_id, self.request
        ).content

        self.assertIn("Canonical record", content)
        self.assertIn("No canonical record linked", content)
        self.assertIn("Create canonical record from this document", content)
        self.assertIn(
            f"/admin/document-intake/{self.document_id}/canonical-record/new",
            content,
        )

    def test_create_form_prefills_medical_council_complaint_metadata(self):
        content = admin_session.admin_canonical_record_from_document_page(
            self.document_id, self.request
        ).content

        self.assertIn("Create Canonical Record from Published Document", content)
        self.assertIn('value="complaint" selected>Complaint</option>', content)
        self.assertIn('value="CMP-MC-20191202-001"', content)
        self.assertIn('value="Initial Complaint to the Medical Council of Ireland"', content)
        self.assertIn('value="Medical Council of Ireland"', content)
        self.assertIn('value="2019-12-02"', content)
        self.assertIn(
            "Formal complaint submitted to the Medical Council of Ireland on "
            "2 December 2019, accompanied by an initial evidence package",
            content,
        )
        self.assertIn("NM-EVID-PKG-20191202-001", content)
        self.assertIn(hashlib.sha256(PDF_BYTES).hexdigest(), content)
        self.assertIn("Document SHA-256 is preserved on the document", content)

    def test_create_record_preserves_document_identity_and_declining_association(self):
        before_document = load_pending_document(self.document_id, root=self.root)
        response = self._create_record(create_association=None)
        self.assertEqual(response.status_code, 201)
        self.assertIn("Canonical record created", response.content)

        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT * FROM records WHERE reference = ?",
                ("CMP-MC-20191202-001",),
            ).fetchone()
            association_count = conn.execute(
                "SELECT COUNT(*) FROM record_document_associations"
            ).fetchone()[0]
        finally:
            conn.close()
        after_document = load_pending_document(self.document_id, root=self.root)

        self.assertEqual(row["record_type"], "complaint")
        self.assertEqual(row["record_title"], "Initial Complaint to the Medical Council of Ireland")
        self.assertEqual(row["institution"], "Medical Council of Ireland")
        self.assertEqual(row["event_date"], "2019-12-02")
        self.assertEqual(row["source_document_reference"], "NM-EVID-PKG-20191202-001")
        self.assertEqual(row["source_document_id"], self.document_id)
        self.assertIn("Created from Published document", row["source_narrative"])
        self.assertNotEqual(row["verification_hash"], before_document["sha256_hash"])
        self.assertEqual(association_count, 0)
        self.assertEqual(before_document["sha256_hash"], after_document["sha256_hash"])
        self.assertEqual(before_document["status"], after_document["status"])

    def test_optional_association_creation_uses_existing_association_validation(self):
        response = self._create_record(create_association="1")
        self.assertEqual(response.status_code, 201)
        self.assertIn("Source document association created", response.content)

        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT * FROM record_document_associations WHERE record_reference = ?",
                ("CMP-MC-20191202-001",),
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(row["document_id"], self.document_id)
        self.assertEqual(row["relationship_type"], "supporting_document")
        self.assertEqual(row["public_label"], "Initial Complaint Evidence Package")
        self.assertEqual(row["created_by"], "admin-user")

    def test_duplicate_exact_source_link_displays_warning(self):
        self._create_record(create_association=None)
        content = admin_session.admin_canonical_record_from_document_page(
            self.document_id, self.request
        ).content
        self.assertIn("A canonical record may already exist for this Published document", content)
        self.assertIn("CMP-MC-20191202-001", content)

    def test_created_complaint_is_publicly_searchable_and_selectable(self):
        self._create_record(create_association=None)

        index = asyncio.run(records.records_index(search="Medical Council")).content
        self.assertIn("CMP-MC-20191202-001", index)
        self.assertIn("Complaint", index)
        date_index = asyncio.run(records.records_index(search="2019-12-02")).content
        self.assertIn("CMP-MC-20191202-001", date_index)

        selector = admin_session.admin_association_new_page(self.request).content
        self.assertIn('value="CMP-MC-20191202-001"', selector)
        self.assertIn("Complaint", selector)

        document_page = documents.public_document_page(self.document_id).content
        self.assertIn("Initial Complaint Evidence Package", document_page)
        self.assertIn("NM-EVID-PKG-20191202-001", document_page)


if __name__ == "__main__":
    unittest.main()
