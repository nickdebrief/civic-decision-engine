import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from api.document_intake import (
    build_document_search_text,
    document_keywords_display,
    load_pending_document,
    normalize_document_keywords,
    store_pending_document,
    update_intake_status,
)
from tests.test_admin_session import FakeRequest, FakeUploadFile, install_fastapi_stubs

install_fastapi_stubs()

from api import document_intake_corrections as dic
from api.routes import admin_session, documents


PDF_BYTES = b"%PDF-1.7\nkeyword document\n%%EOF\n"


class GovernedDocumentKeywordsTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "intake"
        self.db_path = Path(self.temp_dir.name) / "records.db"
        self.env = patch.dict(
            os.environ,
            {
                "CDE_DOCUMENT_INTAKE_ROOT": str(self.root),
                "ADMIN_USERNAME": "nick",
                "ADMIN_PASSWORD": "admin-password",
                "CDE_ADMIN_SESSION_SECRET": "keyword-session-secret",
            },
            clear=False,
        )
        self.env.start()
        self.original_db_path = dic.DB_PATH
        dic.DB_PATH = self.db_path

    def tearDown(self):
        dic.DB_PATH = self.original_db_path
        self.env.stop()
        self.temp_dir.cleanup()

    def _session_request(self):
        session = admin_session.create_admin_session("nick")
        return FakeRequest({admin_session.SESSION_COOKIE_NAME: session})

    def _publish(self, intake_id: str):
        update_intake_status(
            intake_id,
            "under_review",
            actor="nick",
            note="Begin review.",
            changed_at="2026-07-17T10:00:00Z",
            root=self.root,
        )
        update_intake_status(
            intake_id,
            "approved",
            actor="nick",
            note="Approve.",
            changed_at="2026-07-17T11:00:00Z",
            root=self.root,
        )
        update_intake_status(
            intake_id,
            "published",
            actor="nick",
            note="Publish.",
            changed_at="2026-07-17T12:00:00Z",
            root=self.root,
        )

    def _archive(self, intake_id: str):
        update_intake_status(
            intake_id,
            "under_review",
            actor="nick",
            note="Begin review.",
            changed_at="2026-07-17T10:00:00Z",
            root=self.root,
        )
        update_intake_status(
            intake_id,
            "approved",
            actor="nick",
            note="Approve.",
            changed_at="2026-07-17T11:00:00Z",
            root=self.root,
        )
        update_intake_status(
            intake_id,
            "archived",
            actor="nick",
            note="Archive for correction.",
            changed_at="2026-07-17T12:00:00Z",
            root=self.root,
        )

    def _store_keyword_document(self, *, publish=True):
        item = store_pending_document(
            data=PDF_BYTES,
            original_filename="Email_Harmon_Flex_7_May_2019.pdf",
            content_type="application/pdf",
            title="Email — Flex — Bon Secours Pain Medicine",
            institution_source="Bon Secours Hospital Pain Medicine",
            document_date="2019-05-07",
            category="Correspondence",
            description=(
                "Email from Nick Moloney to harmonpainmedicine@bonsecours.ie "
                "referring to a discussion with Dominic."
            ),
            visibility="private",
            notes="Private administrative note.",
            reference_identifier="NM-EVID-EMAIL-20190507-001",
            keywords=(
                "Medical Council, Bon Secours, Dominic Harmon, Bridget, Email, "
                "Correspondence, 2019, Pain Medicine, medical council"
            ),
            actor="nick",
            uploaded_at="2026-07-17T09:00:00Z",
            root=self.root,
        )
        if publish:
            self._publish(item["intake_id"])
        return load_pending_document(item["intake_id"], root=self.root)

    def test_keyword_normalisation_preserves_phrases_and_removes_duplicates(self):
        keywords = normalize_document_keywords(
            "Medical Council, Bon Secours, Pain Medicine, medical council, , Bridget"
        )
        self.assertEqual(
            keywords,
            ["Medical Council", "Bon Secours", "Pain Medicine", "Bridget"],
        )
        self.assertEqual(
            normalize_document_keywords('["Dominic Harmon", "Email", "email"]'),
            ["Dominic Harmon", "Email"],
        )
        self.assertEqual(document_keywords_display(keywords), "Medical Council · Bon Secours · Pain Medicine · Bridget")

    def test_keywords_can_be_entered_during_admin_document_intake(self):
        response = admin_session.admin_document_intake_upload(
            self._session_request(),
            title="Email — Flex — Bon Secours Pain Medicine",
            institution_source="Bon Secours Hospital Pain Medicine",
            document_date="2019-05-07",
            category="Correspondence",
            description="Email from Nick Moloney to Dominic about photographs.",
            visibility="private",
            notes="Private administrative note.",
            reference_identifier="NM-EVID-EMAIL-20190507-001",
            keywords="Medical Council, Bon Secours, Dominic Harmon, Bridget",
            file=FakeUploadFile(
                PDF_BYTES,
                filename="Email_Harmon_Flex_7_May_2019.pdf",
                content_type="application/pdf",
            ),
        )
        content = str(response.content)
        self.assertEqual(response.status_code, 201)
        self.assertIn("Keywords", content)
        self.assertIn("Medical Council · Bon Secours · Dominic Harmon · Bridget", content)
        item = load_pending_document(next(self.root.glob("*/metadata.json")).parent.name, root=self.root)
        self.assertEqual(item["keywords"], ["Medical Council", "Bon Secours", "Dominic Harmon", "Bridget"])
        self.assertEqual(item["tags"], item["keywords"])

    def test_keywords_survive_publication_and_render_on_public_detail(self):
        item = self._store_keyword_document()
        rendered = documents.public_document_page(item["intake_id"])
        content = str(rendered.content)
        self.assertIn("Keywords", content)
        self.assertIn("Medical Council · Bon Secours · Dominic Harmon", content)
        self.assertEqual(load_pending_document(item["intake_id"], root=self.root)["sha256_hash"], item["sha256_hash"])

    def test_keyword_only_public_search_and_association_selector_search_work(self):
        item = self._store_keyword_document()
        for query in ("Dominic Harmon", "Bon Secours", "Bridget", "Pain Medicine", "2019"):
            with self.subTest(query=query):
                response = documents.public_document_library(
                    q=query,
                    institution=None,
                    category=None,
                    publication_year=None,
                )
                self.assertIn("Email — Flex — Bon Secours Pain Medicine", str(response.content))
        search_text = build_document_search_text(item)
        self.assertIn("dominic harmon", search_text)
        options = admin_session._association_document_options([item])
        self.assertIn('value="' + item["intake_id"] + '"', options)
        self.assertIn("dominic harmon", options)

    def test_existing_documents_without_keywords_remain_valid(self):
        item = store_pending_document(
            data=PDF_BYTES + b"legacy",
            original_filename="legacy.pdf",
            content_type="application/pdf",
            title="Legacy Published Document",
            institution_source="Civic Office",
            document_date="2026-07-16",
            category="Decision",
            description="Legacy document with no keyword metadata.",
            visibility="private",
            notes="Private note.",
            actor="nick",
            uploaded_at="2026-07-16T09:00:00Z",
            root=self.root,
        )
        self._publish(item["intake_id"])
        loaded = load_pending_document(item["intake_id"], root=self.root)
        self.assertEqual(loaded["keywords"], [])
        content = str(documents.public_document_page(item["intake_id"]).content)
        self.assertIn("Legacy Published Document", content)
        self.assertNotIn("<th>Keywords</th>", content)

    def test_keywords_are_preserved_through_governed_correction(self):
        source = self._store_keyword_document(publish=False)
        self._archive(source["intake_id"])
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            correction = dic.create_correction(
                conn,
                source_intake_id=source["intake_id"],
                correction_type="metadata_document_mismatch",
                correction_reason="Correct metadata keywords.",
                correction_description="Governed correction for discovery metadata.",
                corrected_title="Corrected Email",
                corrected_description="Corrected description.",
                corrected_institution_source="Bon Secours Hospital Pain Medicine",
                corrected_category="Correspondence",
                corrected_document_date="2019-05-07",
                corrected_reference_identifier="NM-EVID-EMAIL-20190507-CORR",
                corrected_visibility="private",
                corrected_notes="Corrected private note.",
                corrected_keywords="Medical Council, Dominic Harmon, Email",
                actor="nick",
                created_at="2026-07-17T13:00:00Z",
                root=self.root,
            )
            for state in ("under_review", "reviewed", "authorised"):
                correction = dic.transition_correction(
                    conn,
                    correction["correction_reference"],
                    new_state=state,
                    actor="nick",
                    note=f"Move to {state}.",
                    changed_at=f"2026-07-17T13:0{len(state) % 10}:00Z",
                )
            completed = dic.execute_correction(
                conn,
                correction["correction_reference"],
                actor="nick",
                executed_at="2026-07-17T14:00:00Z",
                root=self.root,
            )
            history = dic.correction_history(conn, correction["correction_reference"])
        finally:
            conn.close()
        destination = load_pending_document(completed["destination_intake_id"], root=self.root)
        self.assertEqual(destination["sha256_hash"], source["sha256_hash"])
        self.assertEqual(destination["keywords"], ["Medical Council", "Dominic Harmon", "Email"])
        self.assertEqual(destination["tags"], destination["keywords"])
        self.assertTrue(any(row["action"] == "corrected_intake_created" for row in history))


if __name__ == "__main__":
    unittest.main()
