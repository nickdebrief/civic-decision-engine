import inspect
import sqlite3
import unittest
from unittest.mock import patch

from tests.test_stage64_governed_allegation import Stage64GovernedAllegationTests

from api import record_governed_allegations as allegations
from api.routes import admin_session


class Stage641GovernedAllegationSourceSelectionTests(Stage64GovernedAllegationTests):
    def test_candidates_are_read_only_and_include_only_eligible_existing_types(self):
        before = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'record_governed_allegation%'"
        ).fetchall()
        candidates = allegations.read_source_candidates(self.db_path)
        after = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'record_governed_allegation%'"
        ).fetchall()
        self.assertEqual(before, after)
        self.assertEqual(
            {item["source_type"] for item in candidates},
            {"canonical_record", "record_document_association", "accepted_pattern_observation"},
        )
        self.assertTrue(any(item["source_id"] == "1" for item in candidates))
        self.assertTrue(any(item["source_id"] == "REC-64" for item in candidates))
        self.assertTrue(any(item["source_id"] == "7" for item in candidates))
        self.assertFalse(any(item["source_id"] == "8" for item in candidates))

    def test_published_document_candidate_is_deliberately_listed(self):
        with patch(
            "api.document_intake.list_published_documents",
            return_value=[{"document_identifier": "DOC-64-1", "title": "<Published title>", "status": "published"}],
        ):
            candidates = allegations.read_source_candidates(self.db_path)
        document = next(item for item in candidates if item["source_type"] == "published_document")
        self.assertEqual(document["source_id"], "DOC-64-1")
        self.assertEqual(document["status"], "Published document")
        self.assertEqual(document["label"], "DOC-64-1 — <Published title>")

    def test_creation_form_requires_deliberate_structured_selection(self):
        candidates = allegations.read_source_candidates(self.db_path)
        html = admin_session._render_governed_allegation_page(
            {"allegations": []}, admin_session={"username": "admin"}, source_candidates=candidates
        )
        self.assertNotIn("Attribution source bindings JSON", html)
        self.assertNotIn('source_id\\\":\\\"1\\\"', html)
        self.assertIn('name="bindings_json"', html)
        self.assertIn('value=""', html)
        self.assertIn("Add selected source", html)
        self.assertIn("Remove", html)
        self.assertIn("attribution_source", html)
        self.assertIn("contextual_source", html)
        self.assertIn("response_source", html)
        self.assertIn("contrary_source", html)
        self.assertNotIn('option value="withdrawal_source"', html.split("id=\"allegation-source-selector\"")[1].split("id=\"withdrawal-source-selector\"")[0])
        self.assertIn("Source selection establishes attribution and provenance only", html)

    def test_withdrawal_selector_is_separate_and_has_no_creation_roles(self):
        item = self._create()
        html = admin_session._render_governed_allegation_page(
            {"allegations": [item]}, admin_session={"username": "admin"}, allegation=item, source_candidates=[]
        )
        withdrawal = html.split('id="withdrawal-source-selector"', 1)[1].split('</section>', 1)[0]
        self.assertIn('option value="withdrawal_source"', withdrawal)
        self.assertNotIn('option value="attribution_source"', withdrawal)
        self.assertNotIn("withdrawal_bindings_json\" required>[{", html)

    def test_source_metadata_is_escaped_and_controls_are_named(self):
        html = admin_session._render_governed_allegation_source_selector(
            [{"source_type": "canonical_record", "source_id": "<id>", "label": "<title>", "status": "<status>", "description": "<description>"}],
            hidden_name="bindings_json", prefix="test-source",
        )
        self.assertIn("&lt;id&gt;", html)
        self.assertIn("&lt;title&gt;", html)
        self.assertIn('for="test-source-type"', html)
        self.assertIn('for="test-source-search"', html)
        self.assertIn('for="test-source-candidate"', html)
        self.assertIn('for="test-source-role"', html)
        self.assertIn("setAttribute('aria-label'", html)
        self.assertIn("source_type_invalid", inspect.getsource(allegations._canonical_bindings))

    def test_tampered_binding_fields_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "unknown_field"):
            self._create(bindings=[{
                "source_type": "record_document_association",
                "source_id": "1",
                "binding_role": "attribution_source",
                "unexpected": "tampered",
            }])
        self.assertFalse(allegations._table_exists(self.conn, "record_governed_allegations"))


if __name__ == "__main__":
    unittest.main()
