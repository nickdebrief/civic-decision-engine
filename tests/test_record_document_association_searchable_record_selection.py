import asyncio
import hashlib
import os
import re
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


PDF_BYTES = b"%PDF-1.7\nsearchable-selection\n%%EOF\n"
LONG_FINDING = (
    "The sequence has transitioned into escalation. Earlier delay has developed "
    "into escalation without response. This generated paragraph is intentionally "
    "long and repetitive so it should not dominate the native option label."
)


class SearchableRecordSelectionTests(unittest.TestCase):
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
        self.document_id = self._published_document(reference="NM-EVID-INV-20191202-001")
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
        self._insert_record(
            conn,
            "Strike-ED-20260510-006",
            LONG_FINDING,
            trajectory="Deteriorating",
            system_state="Trajectory recorded as deteriorating.",
            is_latest=1,
        )
        self._insert_record(
            conn,
            "Strike-LA-20260606-038",
            "Trajectory recorded as stable.",
            trajectory="Stable",
            system_state="Stable public record system state.",
            is_latest=1,
        )
        self._insert_record(
            conn,
            "PRIVATE-LA-20260606-001",
            "Private legacy record.",
            trajectory="Stable",
            system_state="Private state.",
            is_latest=0,
        )
        conn.commit()
        conn.close()

    def _insert_record(self, conn, reference, finding, *, trajectory, system_state, is_latest):
        digest = hashlib.sha256(reference.encode("utf-8")).hexdigest()
        conn.execute(
            """
            INSERT INTO records (
                reference, version, generated_at, trajectory, system_state,
                conditions_json, signals_json, finding, report_json, language,
                generated_by, verification_hash, exported_at, is_latest, source_narrative
            ) VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, 'en', 'Civic Decision Engine', ?, ?, ?, '')
            """,
            (
                reference,
                "2026-07-01T09:00:00Z",
                trajectory,
                system_state,
                "[]",
                "[]",
                finding,
                "{}",
                digest,
                "2026-07-01T10:00:00Z",
                int(is_latest),
            ),
        )

    def _published_document(self, *, reference):
        item = store_pending_document(
            data=PDF_BYTES,
            original_filename="published.pdf",
            content_type="application/pdf",
            title="Contents of ZIP Archive — Initial Medical Council Complaint",
            institution_source="Civic Office",
            document_date="2026-07-09",
            category="Decision",
            description="Published document for searchable selection.",
            visibility="private",
            notes="Private administrative notes.",
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

    def _content(self):
        return admin_session.admin_association_new_page(self.request).content

    def _option_html(self, content, reference):
        match = re.search(rf'<option value="{re.escape(reference)}"[^>]*>.*?</option>', content)
        self.assertIsNotNone(match)
        return match.group(0)

    def _association_count(self):
        conn = self._conn()
        try:
            return conn.execute("SELECT COUNT(*) FROM record_document_associations").fetchone()[0]
        finally:
            conn.close()

    def _create(self, record_reference):
        return admin_session.admin_association_create(
            self.request,
            record_reference=record_reference,
            document_id=self.document_id,
            relationship_type="supporting_document",
            public_label="Supporting document",
            public_note="Public note.",
            admin_note="Administrative note.",
            is_public="1",
        )

    def test_search_field_selector_placeholder_and_compact_labels_render(self):
        content = self._content()
        self.assertIn('<label for="record-search">Search public CDE records</label>', content)
        self.assertIn('id="record-search" type="search" autocomplete="off"', content)
        self.assertNotIn('name="record-search"', content)
        self.assertIn('id="record-reference" name="record_reference" required', content)
        self.assertIn('<option value="" selected disabled>Select a public CDE record</option>', content)
        first_option = self._option_html(content, "Strike-ED-20260510-006")
        second_option = self._option_html(content, "Strike-LA-20260606-038")
        self.assertIn(">Strike-ED-20260510-006 — ED — Deteriorating</option>", first_option)
        self.assertIn(">Strike-LA-20260606-038 — LA — Stable</option>", second_option)
        self.assertNotIn(LONG_FINDING, first_option.split(">")[-2])
        self.assertLess(content.index('value="Strike-ED-20260510-006"'), content.index('value="Strike-LA-20260606-038"'))
        self.assertNotIn("PRIVATE-LA-20260606-001", content)
        self.assertIn("Published document", content)

    def test_label_helper_fallbacks_are_deterministic_and_do_not_leak_internal_values(self):
        self.assertEqual(
            admin_session.build_record_selector_label(
                {"reference": "MC-20191202-001", "title": "Initial Medical Council Complaint"}
            ),
            "MC-20191202-001 — Initial Medical Council Complaint",
        )
        self.assertEqual(
            admin_session.build_record_selector_label(
                {"reference": "Strike-LA-20260606-038", "trajectory": "Stable"}
            ),
            "Strike-LA-20260606-038 — LA — Stable",
        )
        self.assertEqual(
            admin_session.build_record_selector_label({"reference": "REC-2026-001", "id": 99}),
            "REC-2026-001",
        )
        self.assertNotIn("None", admin_session.build_record_selector_label({"reference": "REC-2026-001"}))
        self.assertNotIn(" —  — ", admin_session.build_record_selector_label({"reference": "REC-2026-001"}))
        content = admin_session._association_record_options(
            [{"reference": "REC-<unsafe>", "title": "<script>alert(1)</script>"}]
        )
        self.assertIn("REC-&lt;unsafe&gt;", content)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", content)
        self.assertNotIn("<script>alert(1)</script>", content)

    def test_search_metadata_is_public_safe_and_does_not_change_values(self):
        content = self._content()
        option = self._option_html(content, "Strike-LA-20260606-038")
        self.assertIn('value="Strike-LA-20260606-038"', option)
        self.assertIn('data-reference="Strike-LA-20260606-038"', option)
        self.assertIn('data-institution="LA"', option)
        self.assertIn('data-trajectory="Stable"', option)
        self.assertIn('data-search="strike-la-20260606-038 la stable', option)
        self.assertNotIn("Private administrative notes", option)
        self.assertNotIn("NM-EVID-INV-20191202-001", option)
        self.assertIn("toLocaleLowerCase", content)
        self.assertIn("record-search-clear", content)
        self.assertIn("No eligible public CDE records match this search.", content)
        self.assertIn('aria-live="polite"', content)
        self.assertIn("keepSelected", content)
        self.assertNotRegex(content, r"option\.value\s*=[^=]")

    def test_selected_record_context_uses_public_metadata_only(self):
        content = self._content()
        self.assertIn('id="selected-record-context"', content)
        self.assertIn("Selected record", content)
        self.assertIn("Reference</th><td>Strike-LA-20260606-038", content)
        self.assertIn("Institution</th><td>LA", content)
        self.assertIn("Trajectory</th><td>Stable", content)
        self.assertIn("System state</th><td>Stable public record system state.", content)
        self.assertIn("Finding</th><td>Trajectory recorded as stable.", content)
        self.assertIn('href="/verify/Strike-LA-20260606-038"', content)
        self.assertIn("This panel is informational only and does not alter form submission.", content)
        self.assertNotIn("Private administrative notes", content)
        self.assertNotIn("session-secret", content)

    def test_valid_creation_still_stores_only_canonical_reference(self):
        before_doc = documents.public_document_page(self.document_id).content
        conn = self._conn()
        try:
            before_hash = conn.execute(
                "SELECT verification_hash FROM records WHERE reference = ? AND is_latest = 1",
                ("Strike-LA-20260606-038",),
            ).fetchone()["verification_hash"]
        finally:
            conn.close()
        response = self._create("Strike-LA-20260606-038")
        self.assertEqual(response.status_code, 201)
        conn = self._conn()
        try:
            row = conn.execute("SELECT * FROM record_document_associations").fetchone()
            self.assertEqual(row["record_reference"], "Strike-LA-20260606-038")
            self.assertEqual(row["document_id"], self.document_id)
            self.assertEqual(row["relationship_type"], "supporting_document")
            self.assertEqual(row["created_by"], "admin-user")
            self.assertEqual(row["public_label"], "Supporting document")
            self.assertEqual(row["public_note"], "Public note.")
            self.assertEqual(row["admin_note"], "Administrative note.")
            self.assertEqual(row["is_public"], 1)
            after_hash = conn.execute(
                "SELECT verification_hash FROM records WHERE reference = ? AND is_latest = 1",
                ("Strike-LA-20260606-038",),
            ).fetchone()["verification_hash"]
            history = associations.association_history(conn, row["id"])
            self.assertEqual([item["action_type"] for item in history], ["created"])
        finally:
            conn.close()
        self.assertEqual(before_hash, after_hash)
        after_doc = documents.public_document_page(self.document_id).content
        self.assertIn(hashlib.sha256(PDF_BYTES).hexdigest(), before_doc)
        self.assertIn(hashlib.sha256(PDF_BYTES).hexdigest(), after_doc)
        self.assertIn("Publication Provenance", after_doc)

    def test_invalid_creation_inputs_remain_rejected_without_creating_associations(self):
        invalid_cases = {
            "": "association_record_required",
            "Stable": "association_record_not_found",
            "Strike-LA-20260606-038 — LA — Stable": "association_record_not_found",
            "Strike-LA": "association_record_not_found",
            "Strike-LA-20260606-038, Strike-ED-20260510-006": "association_record_multiple_not_allowed",
            "NM-EVID-INV-20191202-001": "association_record_reference_is_document",
            "PRIVATE-LA-20260606-001": "association_record_not_public",
        }
        for value, expected in invalid_cases.items():
            with self.subTest(value=value):
                before = self._association_count()
                with self.assertRaises(FakeHTTPException) as ctx:
                    self._create(value)
                self.assertEqual(ctx.exception.detail, expected)
                self.assertEqual(self._association_count(), before)

    def test_duplicate_and_public_private_behaviour_remain_unchanged(self):
        self._create("Strike-LA-20260606-038")
        with self.assertRaises(FakeHTTPException) as duplicate:
            self._create("Strike-LA-20260606-038")
        self.assertEqual(duplicate.exception.detail, "association_duplicate_active")
        detail = admin_session.admin_association_detail_page(1, self.request).content
        self.assertIn("Record–Document Association", detail)
        self.assertIn("Strike-LA-20260606-038", detail)
        record_page = asyncio.run(records.verify_record("Strike-LA-20260606-038")).content
        self.assertIn("Associated Public Documents", record_page)
        self.assertIn("Contents of ZIP Archive", record_page)

    def test_existing_regression_pages_still_load(self):
        self.assertIn("Public records", asyncio.run(records.records_index()).content)
        self.assertIn("Public Document Library", documents.public_document_library().content)
        self.assertIn("Record–Document Associations", admin_session.admin_associations_page(self.request).content)
        self.assertIn("CDE Administration Console", admin_session.admin_dashboard_page(self.request).content)
        self.assertIn("Document Intake", admin_session.admin_document_intake_page(self.request).content)
        self.assertIn("Archive Collections", admin_session.admin_collections_page(self.request).content)


if __name__ == "__main__":
    unittest.main()
