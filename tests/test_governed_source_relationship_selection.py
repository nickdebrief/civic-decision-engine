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


PDF_BYTES = b"%PDF-1.7\nstage-47\n%%EOF\n"


class GovernedSourceRelationshipSelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "pending"
        self.db_path = Path(self.temp_dir.name) / "records.db"
        self.env = patch.dict(
            os.environ,
            {
                "ADMIN_USERNAME": "admin-user",
                "ADMIN_PASSWORD": "admin-password",
                "CDE_ADMIN_SESSION_SECRET": "stage-47-secret",
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
        self.source_document = self._published_document(
            title="Croom Admission – 19 June 2018",
            reference="CROOM-ADMISSION-20180619",
        )
        self.additional_document = self._published_document(
            title="Croom Supporting Clinical Note",
            reference="CROOM-SUPPORT-20180619",
        )
        self._init_records_db()
        session = admin_session.create_admin_session("admin-user")
        self.request = FakeRequest(
            cookies={admin_session.SESSION_COOKIE_NAME: session}
        )

    def tearDown(self):
        admin_session.DB_PATH = self.original_admin_db
        records.DB_PATH = self.original_records_db
        associations.DB_PATH = self.original_association_db
        self.env.stop()
        self.temp_dir.cleanup()

    def _published_document(self, *, title: str, reference: str) -> dict:
        item = store_pending_document(
            data=PDF_BYTES + reference.encode("utf-8"),
            original_filename=f"{reference}.pdf",
            content_type="application/pdf",
            title=title,
            institution_source="Croom Hospital",
            document_date="2018-06-19",
            category="Hospital Admission / Administrative Record",
            description=f"Published fixture for {title}.",
            visibility="private",
            notes="Private administrative notes.",
            reference_identifier=reference,
            actor="admin-user",
            uploaded_at="2026-08-03T09:00:00Z",
            root=self.root,
        )
        for status, timestamp in (
            ("under_review", "2026-08-03T09:10:00Z"),
            ("approved", "2026-08-03T09:20:00Z"),
            ("published", "2026-08-03T09:30:00Z"),
        ):
            update_intake_status(
                item["intake_id"],
                status,
                actor="admin-user",
                note=f"{status}.",
                changed_at=timestamp,
                root=self.root,
            )
        return item

    def _init_records_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """
            CREATE TABLE records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reference TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 1,
                record_type TEXT,
                record_title TEXT,
                institution TEXT,
                generated_at TEXT NOT NULL,
                trajectory TEXT,
                system_state TEXT,
                finding TEXT,
                language TEXT NOT NULL DEFAULT 'en',
                verification_hash TEXT NOT NULL,
                exported_at TEXT NOT NULL,
                is_latest INTEGER NOT NULL DEFAULT 1,
                source_document_id TEXT,
                source_document_reference TEXT
            )
            """
        )
        self._insert_record(
            conn,
            reference="CARE-CROOM-20180619-001",
            title="Croom Admission Clinical Episode",
            source_document_id=self.source_document["intake_id"],
            source_document_reference="CROOM-ADMISSION-20180619",
        )
        self._insert_record(
            conn,
            reference="CARE-CROOM-20180619-002",
            title="Legacy Clinical Episode Without Source",
            source_document_id=None,
            source_document_reference=None,
        )
        conn.commit()
        conn.close()

    def _insert_record(
        self,
        conn,
        *,
        reference: str,
        title: str,
        source_document_id: str | None,
        source_document_reference: str | None,
    ):
        conn.execute(
            """
            INSERT INTO records (
                reference, version, record_type, record_title, institution,
                generated_at, trajectory, system_state, finding, language,
                verification_hash, exported_at, is_latest,
                source_document_id, source_document_reference
            ) VALUES (?, 1, 'clinical_episode', ?, 'Croom Hospital', ?,
                      'Submitted', 'Governed', ?, 'en', ?, ?, 1, ?, ?)
            """,
            (
                reference,
                title,
                "2026-08-03T10:00:00Z",
                title,
                hashlib.sha256(reference.encode("utf-8")).hexdigest(),
                "2026-08-03T10:00:00Z",
                source_document_id,
                source_document_reference,
            ),
        )

    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        associations.ensure_association_tables(conn)
        return conn

    def _create(self, *, record_reference: str, relationship_type: str):
        return admin_session.admin_association_create(
            self.request,
            record_reference=record_reference,
            document_id=self.additional_document["intake_id"],
            relationship_type=relationship_type,
            public_label="",
            public_note="",
            admin_note="Stage 47 governed relationship.",
            is_public="1",
        )

    def test_source_backed_record_exposes_locked_source_state_and_guidance(self):
        content = admin_session.admin_association_new_page(self.request).content
        self.assertIn('data-has-authoritative-source="true"', content)
        self.assertIn("Authoritative source document (already established)", content)
        self.assertIn("sourceOption.disabled = Boolean(hasAuthoritativeSource)", content)
        self.assertIn(
            "This Canonical Record already has its authoritative source Published Document.",
            content,
        )
        self.assertIn("Additional Published Documents should normally be associated", content)

    def test_existing_source_document_context_is_displayed(self):
        content = admin_session.admin_association_new_page(self.request).content
        self.assertIn("Authoritative source", content)
        self.assertIn("Croom Admission – 19 June 2018", content)
        self.assertIn(self.source_document["document_identifier"], content)
        self.assertIn(
            f'href="/documents/{self.source_document["intake_id"]}"',
            content,
        )
        self.assertIn("Open Published Document →", content)

    def test_supporting_and_related_relationships_remain_selectable(self):
        content = admin_session.admin_association_new_page(self.request).content
        self.assertIn(
            '<option value="supporting_document">Supporting document</option>',
            content,
        )
        self.assertIn(
            '<option value="related_document">Related document</option>',
            content,
        )
        self.assertEqual(
            self._create(
                record_reference="CARE-CROOM-20180619-001",
                relationship_type="supporting_document",
            ).status_code,
            201,
        )
        self.assertEqual(
            self._create(
                record_reference="CARE-CROOM-20180619-001",
                relationship_type="related_document",
            ).status_code,
            201,
        )

    def test_direct_source_submission_is_rejected_for_source_backed_record(self):
        with self.assertRaises(FakeHTTPException) as ctx:
            self._create(
                record_reference="CARE-CROOM-20180619-001",
                relationship_type="source_document",
            )
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(
            ctx.exception.detail,
            "association_authoritative_source_already_assigned",
        )

    def test_record_without_source_retains_source_document_behaviour(self):
        content = admin_session.admin_association_new_page(self.request).content
        self.assertIn('data-has-authoritative-source="false"', content)
        self.assertIn('<option value="source_document">Source document</option>', content)
        response = self._create(
            record_reference="CARE-CROOM-20180619-002",
            relationship_type="source_document",
        )
        self.assertEqual(response.status_code, 201)
        with self.assertRaises(FakeHTTPException) as ctx:
            admin_session.admin_association_create(
                self.request,
                record_reference="CARE-CROOM-20180619-002",
                document_id=self.source_document["intake_id"],
                relationship_type="source_document",
                public_label="",
                public_note="",
                admin_note="Attempted second source.",
                is_public="1",
            )
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(
            ctx.exception.detail,
            "association_authoritative_source_already_assigned",
        )

    def test_update_cannot_convert_supporting_relationship_to_second_source(self):
        response = self._create(
            record_reference="CARE-CROOM-20180619-001",
            relationship_type="supporting_document",
        )
        self.assertIn(
            '<option value="source_document" disabled>'
            "Authoritative source document (already established)</option>",
            response.content,
        )
        with self.assertRaises(FakeHTTPException) as ctx:
            admin_session.admin_association_update(
                1,
                self.request,
                relationship_type="source_document",
                public_label="Source document",
                public_note="",
                admin_note="Attempted source reassignment.",
                is_public="1",
            )
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(
            ctx.exception.detail,
            "association_authoritative_source_already_assigned",
        )
        self.assertEqual(response.status_code, 201)
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT relationship_type FROM record_document_associations WHERE id = 1"
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(row["relationship_type"], "supporting_document")

    def test_existing_associations_and_source_provenance_remain_unchanged(self):
        self._create(
            record_reference="CARE-CROOM-20180619-001",
            relationship_type="evidence_audit",
        )
        conn = self._conn()
        try:
            record = conn.execute(
                "SELECT source_document_id, source_document_reference FROM records "
                "WHERE reference = 'CARE-CROOM-20180619-001'"
            ).fetchone()
            association = conn.execute(
                "SELECT relationship_type FROM record_document_associations"
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(record["source_document_id"], self.source_document["intake_id"])
        self.assertEqual(
            record["source_document_reference"], "CROOM-ADMISSION-20180619"
        )
        self.assertEqual(association["relationship_type"], "evidence_audit")

    def test_authentication_and_public_behaviour_are_unchanged(self):
        with self.assertRaises(FakeHTTPException) as ctx:
            admin_session.admin_association_new_page(FakeRequest())
        self.assertEqual(ctx.exception.status_code, 401)
        public_document = documents.public_document_page(
            self.source_document["intake_id"]
        ).content
        self.assertIn("Publication Provenance", public_document)
        self.assertNotIn("source-relationship-guidance", public_document)
        self.assertNotIn("Authoritative source document (already established)", public_document)


if __name__ == "__main__":
    unittest.main()
