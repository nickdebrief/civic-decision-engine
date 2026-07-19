import asyncio
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from api.document_intake import store_pending_document, update_intake_status
from tests.test_admin_session import install_fastapi_stubs
from tests.test_governed_spreadsheet_artefact_support import _xlsx_bytes

install_fastapi_stubs()

from api import archive_collection_memberships as acm
from api import archive_collections as ac
from api import record_document_associations as rda
from api.routes import archive, associations, collections, documents, records


class PublicArchiveExplorerTests(unittest.TestCase):
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
        self.originals = (ac.DB_PATH, rda.DB_PATH, records.DB_PATH)
        ac.DB_PATH = self.db_path
        rda.DB_PATH = self.db_path
        records.DB_PATH = self.db_path
        self._init_records()
        self.document = self._published_spreadsheet()
        self.association, self.collection = self._association_and_collection()

    def tearDown(self):
        ac.DB_PATH, rda.DB_PATH, records.DB_PATH = self.originals
        self.env.stop()
        self.temp_dir.cleanup()

    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        acm.ensure_membership_tables(conn)
        return conn

    def _init_records(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """
            CREATE TABLE records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reference TEXT NOT NULL,
                record_type TEXT NOT NULL DEFAULT 'strike',
                record_title TEXT,
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
        records_data = [
            (
                "CMP-MC-20191202-001",
                "complaint",
                "Initial Complaint to the Medical Council of Ireland",
                "Medical Council of Ireland",
                "2019-12-02",
                "Formal complaint submitted with supporting material.",
                "Submitted",
                "Published",
                "Complaint record summary.",
                "2026-07-23T09:30:00Z",
                "2026-07-23T10:00:00Z",
            ),
            (
                "Strike-LA-20260710-004",
                "strike",
                "Strike Archive Record",
                "Local Authority",
                "2026-07-10",
                "Strike sequence record.",
                "Stable",
                "Published",
                "Strike record summary.",
                "2026-07-22T09:30:00Z",
                "2026-07-22T10:00:00Z",
            ),
        ]
        conn.executemany(
            """
            INSERT INTO records (
                reference, record_type, record_title, institution, event_date,
                summary, trajectory, system_state, finding, conditions_json,
                report_json, generated_by, verification_hash, generated_at, exported_at, is_latest
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '[]', '{}', 'CDE', 'record-hash', ?, ?, 1)
            """,
            records_data,
        )
        for index in range(12):
            conn.execute(
                """
                INSERT INTO records (
                    reference, record_type, record_title, institution, event_date,
                    summary, trajectory, system_state, finding, conditions_json,
                    report_json, generated_by, verification_hash, generated_at, exported_at, is_latest
                ) VALUES (?, 'strike', ?, 'Woodstock', '2019-12-31',
                    'Woodstock supplemental public archive record.', 'Stable',
                    'Published', 'Supplemental Woodstock record.', '[]', '{}',
                    'CDE', 'record-hash', ?, ?, 1)
                """,
                (
                    f"Strike-WD-20191231-{index + 1:03d}",
                    f"Woodstock Supplemental Record {index + 1:03d}",
                    f"2026-07-21T09:{index:02d}:00Z",
                    f"2026-07-21T10:{index:02d}:00Z",
                ),
            )
        conn.commit()
        conn.close()

    def _published_spreadsheet(self):
        item = store_pending_document(
            data=_xlsx_bytes(sheet_names=("Woodstock Usage", "Summary")),
            original_filename="Nick_Moloney_Member_Usage_Woodstock_2019.xlsx",
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            title="Woodstock Member Usage 2019",
            institution_source="Woodstock",
            document_date="2019-12-31",
            category="Spreadsheet",
            description="Legacy member usage workbook.",
            visibility="private",
            notes="Private spreadsheet note.",
            reference_identifier="NM-XLS-WOODSTOCK-2019-001",
            keywords="Woodstock, Member Usage, Spreadsheet",
            actor="admin-user",
            uploaded_at="2026-07-23T09:00:00Z",
            root=self.root,
        )
        for status in ("under_review", "approved", "published"):
            item = update_intake_status(
                item["intake_id"],
                status,
                actor="admin-user",
                note=f"{status} note",
                changed_at=f"2026-07-23T09:0{len(status)}:00Z",
                root=self.root,
            )
        return item

    def _association_and_collection(self):
        conn = self._conn()
        try:
            association = rda.create_association(
                conn,
                record_reference="CMP-MC-20191202-001",
                document_id=self.document["intake_id"],
                relationship_type="supporting_document",
                public_label="Supporting spreadsheet",
                public_note="Published spreadsheet supporting the complaint record.",
                admin_note="Private association note.",
                is_public=True,
                actor="admin-user",
                created_at="2026-07-23T11:00:00Z",
                root=self.root,
            )
            collection = ac.create_collection(
                conn,
                title="Woodstock Archive Collection",
                subtitle="Spreadsheet material",
                institution_source="Woodstock",
                category="documentary_archive",
                description="Curated public collection containing the spreadsheet artefact.",
                public_note="Public collection note.",
                admin_note="Private collection note.",
                date_from="2019-01-01",
                date_to=None,
                is_public=True,
                actor="admin-user",
                created_at="2026-07-23T12:00:00Z",
            )
            membership = acm.create_membership(
                conn,
                collection_id=collection["id"],
                document_id=self.document["intake_id"],
                actor="admin-user",
                membership_note="Spreadsheet member.",
                display_sequence=1,
                created_at="2026-07-23T12:15:00Z",
                root=self.root,
            )
            for status in ("reviewed", "approved", "active"):
                acm.transition_membership(
                    conn,
                    membership["membership_reference"],
                    new_status=status,
                    actor="admin-user",
                    root=self.root,
                )
            return association, collection
        finally:
            conn.close()

    def page(self, **params):
        return archive.public_archive_explorer(**params).content

    def test_landing_displays_counts_and_public_object_types(self):
        content = self.page()
        self.assertIn("Public Archive Explorer", content)
        self.assertIn("Canonical Records", content)
        self.assertIn("Published Documents", content)
        self.assertIn("Record-Document Associations", content)
        self.assertIn("Governed Public Collections", content)
        self.assertIn("CMP-MC-20191202-001", content)
        self.assertIn("NM-XLS-WOODSTOCK-2019-001", content)
        self.assertIn(self.association["public_reference"], content)
        self.assertIn(self.collection["public_reference"], content)
        self.assertNotIn("Private spreadsheet note", content)
        self.assertNotIn("Private association note", content)
        self.assertNotIn("Private collection note", content)

    def test_search_filters_media_and_spreadsheet_metadata(self):
        self.assertIn("Woodstock Member Usage 2019", self.page(search="woodstock usage"))
        worksheet_search = self.page(search="Woodstock Usage")
        self.assertIn("Woodstock Member Usage 2019", worksheet_search)
        media_page = self.page(media="spreadsheet")
        self.assertIn("Woodstock Member Usage 2019", media_page)
        self.assertIn("Supporting spreadsheet", media_page)
        self.assertNotIn("Initial Complaint to the Medical Council", media_page)
        document_page = self.page(type="published_document", media="spreadsheet")
        self.assertIn("Woodstock Member Usage 2019", document_page)
        self.assertNotIn(self.association["public_reference"], document_page)

    def test_record_type_status_year_and_collection_filters(self):
        complaint_page = self.page(record_type="complaint")
        self.assertIn("Initial Complaint to the Medical Council", complaint_page)
        self.assertNotIn("Strike Archive Record", complaint_page)
        self.assertIn("Initial Complaint", self.page(status="published"))
        self.assertIn("Woodstock Member Usage 2019", self.page(year="2026"))
        self.assertIn("Woodstock Member Usage 2019", self.page(document_year="2019"))
        collection_page = self.page(collection=self.collection["public_reference"])
        self.assertIn("Woodstock Archive Collection", collection_page)
        self.assertIn("Woodstock Member Usage 2019", collection_page)
        self.assertNotIn("Strike Archive Record", collection_page)

    def test_sorting_pagination_and_query_persistence(self):
        alpha = self.page(sort="alphabetical")
        alpha_results = alpha.split('<section class="archive-results"', 1)[1]
        self.assertLess(alpha_results.index("Initial Complaint"), alpha_results.index("Woodstock Archive Collection"))
        reference = self.page(sort="reference")
        reference_results = reference.split('<section class="archive-results"', 1)[1]
        self.assertLess(reference_results.index("CMP-MC-20191202-001"), reference_results.index("NM-XLS-WOODSTOCK-2019-001"))
        page_one = self.page(page_size=10, page=1, search="woodstock")
        page_two = self.page(page_size=10, page=2, search="woodstock")
        self.assertIn("Page 1 of", page_one)
        self.assertIn("Next page", page_one)
        self.assertIn("search=woodstock", page_one)
        self.assertIn("Previous page", page_two)

    def test_public_pages_include_archive_back_links(self):
        self.assertIn("Back to Archive Explorer", documents.public_document_page(self.document["intake_id"]).content)
        self.assertIn("Back to Archive Explorer", associations.public_association_page(self.association["public_reference"]).content)
        self.assertIn("Back to Archive Explorer", collections.public_collection_page(self.collection["public_reference"]).content)
        record_content = asyncio.run(records.verify_record("CMP-MC-20191202-001")).content
        self.assertIn("Archive Explorer", record_content)


if __name__ == "__main__":
    unittest.main()
