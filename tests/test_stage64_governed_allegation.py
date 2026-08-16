import inspect
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from tests.test_admin_session import FakeHTTPException, FakeRequest, install_fastapi_stubs

install_fastapi_stubs()

from api import record_document_associations as associations
from api import record_governed_allegations as allegations
from api.routes import admin_session, associations as public_association_routes


class Stage64GovernedAllegationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "records.db"
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        associations.ensure_association_tables(self.conn)
        self._insert_association(1, "REC-64", "supporting_document", "2026-01-01T00:00:00Z")
        self._insert_association(2, "REC-64", "context_document", "2026-02-01T00:00:00Z")
        self.conn.execute("CREATE TABLE records (reference TEXT PRIMARY KEY, version INTEGER, generated_at TEXT)")
        self.conn.execute("INSERT INTO records VALUES ('REC-64', 1, '2026-01-01T00:00:00Z')")
        self.conn.execute(
            "CREATE TABLE record_pattern_observations (id INTEGER PRIMARY KEY, status TEXT, created_at TEXT)"
        )
        self.conn.execute("INSERT INTO record_pattern_observations VALUES (7, 'accepted', '2026-03-01T00:00:00Z')")
        self.conn.execute("INSERT INTO record_pattern_observations VALUES (8, 'candidate', '2026-03-02T00:00:00Z')")
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        self.temp_dir.cleanup()

    def _insert_association(self, ident, record, relationship, created):
        self.conn.execute(
            """INSERT INTO record_document_associations
               (id, public_reference, record_reference, document_id, relationship_type,
                public_label, is_active, is_public, created_at, created_by, updated_at, updated_by)
               VALUES (?, ?, ?, ?, ?, ?, 1, 1, ?, 'admin', ?, 'admin')""",
            (ident, f"CDE-ASSOC-64-{ident}", record, f"doc-{ident}", relationship, relationship, created, created),
        )

    def _contract(self, limitations="The allegation may remain disputed or unresolved."):
        return {
            "epistemic_label": "allegation",
            "attribution_present": True,
            "source_basis_present": True,
            "not_evidence": True,
            "not_observation": True,
            "not_inference": True,
            "not_determination": True,
            "not_confirmation": True,
            "alternatives_possible": True,
            "limitations": limitations,
        }

    def _binding(self, source_type="record_document_association", source_id="1", role="attribution_source"):
        return {"source_type": source_type, "source_id": source_id, "binding_role": role}

    def _create(self, *, text="The source reported a delayed response.", mode="faithful_paraphrase", bindings=None, key=None):
        return allegations.create_allegation(
            self.conn,
            allegation_category="reported_conduct",
            allegation_text=text,
            representation_mode=mode,
            representation_contract={"human_verified": True, "faithful_representation": mode == "faithful_paraphrase", "exact_source_wording": mode == "verbatim"},
            attributed_source_label="Named reporting institution",
            attribution_context="Written communication preserved in the governed record.",
            subject_label="Administrative unit",
            alleged_period="2026-01",
            made_or_recorded_at="2026-02-03T00:00:00Z",
            rationale="Preserve the attributed proposition without resolving its truth.",
            qualification="This proposition is preserved as an allegation attributed to the identified source.",
            limitations="The allegation may remain disputed or unresolved.",
            qualification_contract=self._contract(),
            bindings=bindings or [self._binding()],
            actor="author",
            actor_role="admin",
            author_declaration={"acknowledged": True},
            idempotency_key=key,
            created_at="2026-04-01T00:00:00Z",
        )

    def _review(self, ident, disposition="accepted_as_attributed_allegation", actor="reviewer", key=None, at="2026-04-02T00:00:00Z"):
        return allegations.review_allegation(
            self.conn,
            ident,
            disposition=disposition,
            rationale="Review attribution and representation only.",
            boundary_declaration={"acknowledged": True},
            actor=actor,
            actor_role="admin",
            reviewed_at=at,
            idempotency_key=key,
        )

    def test_creation_requires_attribution_and_preserves_source_roles(self):
        item = self._create(bindings=[
            self._binding("record_document_association", "1", "attribution_source"),
            self._binding("canonical_record", "REC-64", "contextual_source"),
            self._binding("record_document_association", "2", "response_source"),
            self._binding("accepted_pattern_observation", "7", "contrary_source"),
        ])
        self.assertEqual(item["status"], "recorded")
        self.assertEqual({row["binding_role"] for row in item["bindings"]}, {"attribution_source", "contextual_source", "response_source", "contrary_source"})
        with self.assertRaisesRegex(ValueError, "attribution_source_required"):
            self._create(bindings=[self._binding(role="contextual_source")])

    def test_representation_modes_and_structured_qualification_are_limited(self):
        self.assertEqual(self._create(mode="verbatim")["representation_mode"], "verbatim")
        self.assertEqual(self._create(mode="faithful_paraphrase")["representation_mode"], "faithful_paraphrase")
        with self.assertRaisesRegex(ValueError, "representation_mode_invalid"):
            self._create(mode="summary")
        with self.assertRaisesRegex(ValueError, "exact_wording_required"):
            allegations.create_allegation(
                self.conn, allegation_category="reported_statement", allegation_text="x",
                representation_mode="verbatim", representation_contract={"human_verified": True},
                attributed_source_label="source", attribution_context="context", subject_label="subject",
                alleged_period=None, made_or_recorded_at=None, rationale="r", qualification="q",
                limitations="l", qualification_contract=self._contract(), bindings=[self._binding()],
                actor="author", actor_role="admin", author_declaration={"acknowledged": True},
            )
        with self.assertRaisesRegex(ValueError, "qualification_contract_incomplete"):
            allegations.create_allegation(
                self.conn, allegation_category="reported_statement", allegation_text="x",
                representation_mode="verbatim", representation_contract={"human_verified": True, "exact_source_wording": True},
                attributed_source_label="source", attribution_context="context", subject_label="subject",
                alleged_period=None, made_or_recorded_at=None, rationale="r", qualification="q",
                limitations="l", qualification_contract={"epistemic_label": "allegation"},
                bindings=[self._binding()], actor="author", actor_role="admin",
                author_declaration={"acknowledged": True},
            )
        with self.assertRaisesRegex(ValueError, "author_boundary"):
            allegations.create_allegation(
                self.conn, allegation_category="reported_statement", allegation_text="x",
                representation_mode="verbatim", representation_contract={"human_verified": True, "exact_source_wording": True},
                attributed_source_label="source", attribution_context="context", subject_label="subject",
                alleged_period=None, made_or_recorded_at=None, rationale="r", qualification="q",
                limitations="l", qualification_contract=self._contract(), bindings=[self._binding()],
                actor="author", actor_role="admin", author_declaration={"acknowledged": False},
            )

    def test_invalid_source_types_and_unaccepted_observation_fail_transactionally(self):
        with self.assertRaisesRegex(ValueError, "source_type_invalid"):
            self._create(bindings=[self._binding("governed_inference", "1")])
        with self.assertRaisesRegex(ValueError, "observation_not_accepted"):
            self._create(bindings=[self._binding("accepted_pattern_observation", "8")])
        with self.assertRaisesRegex(ValueError, "source_not_found"):
            self._create(bindings=[self._binding("record_document_association", "999")])
        self.assertFalse(allegations._table_exists(self.conn, "record_governed_allegations"))

    def test_repeated_sources_do_not_create_confirmation_or_corroboration(self):
        first = self._create(key="repeat-a")
        second = self._create(key="repeat-b")
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(first["status"], "recorded")
        self.assertEqual(second["status"], "recorded")
        self.assertNotIn("confirmed", first["status"])
        self.assertNotIn("corroborated", second["status"])
        self.assertNotIn("admission", first["status"])
        self.assertNotIn("agreement", second["status"])
        self.assertNotIn("response_source", {row["binding_role"] for row in first["bindings"]})

    def test_creation_retry_and_semantic_conflict_are_idempotent(self):
        first = self._create(key="same-allegation-key")
        retry = self._create(key="same-allegation-key")
        self.assertEqual(first["id"], retry["id"])
        with self.assertRaisesRegex(ValueError, "idempotency_conflict"):
            self._create(text="A materially different attributed proposition.", key="same-allegation-key")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM record_governed_allegations").fetchone()[0], 1)

    def test_review_is_append_only_self_review_and_not_truth_confirmation(self):
        item = self._create()
        accepted = self._review(item["id"], actor="author")
        self.assertEqual(accepted["status"], "accepted_as_attributed_allegation")
        self.assertEqual(accepted["reviews"][0]["is_self_review"], 1)
        self.assertNotIn("confirmed", accepted["status"])
        self._review(item["id"], disposition="requires_attribution_correction", actor="reviewer", at="2026-04-03T00:00:00Z")
        self.assertEqual(len(allegations.get_allegation(self.conn, item["id"])["reviews"]), 2)

    def test_review_retry_and_boundary_declaration_are_governed(self):
        item = self._create()
        first = self._review(item["id"], key="review-key")
        retry = self._review(item["id"], key="review-key")
        self.assertEqual(first["id"], retry["id"])
        with self.assertRaisesRegex(ValueError, "review_idempotency_conflict"):
            self._review(item["id"], disposition="not_accepted_as_attributed", key="review-key")
        with self.assertRaisesRegex(ValueError, "review_boundary"):
            allegations.review_allegation(self.conn, item["id"], disposition="not_accepted_as_attributed", rationale="r", boundary_declaration={"acknowledged": False}, actor="reviewer", actor_role="admin")

    def test_competing_allegations_and_allegation_binding_are_separate(self):
        first = self._create(text="The source described one account.")
        second = self._create(text="The source described a competing account.")
        self.assertNotEqual(first["id"], second["id"])
        with self.assertRaisesRegex(ValueError, "source_type_invalid"):
            self._create(bindings=[self._binding("governed_allegation", str(first["id"]))])

    def test_supersession_preserves_original_rejects_cycles_and_precedence_is_correct(self):
        original = self._create(text="Original attributed account.")
        replacement = self._create(text="Corrected attributed account.")
        self._review(original["id"], actor="reviewer")
        superseded = allegations.supersede_allegation(self.conn, original["id"], replacement_allegation_id=replacement["id"], rationale="Corrected representation.", actor="reviewer", actor_role="admin", occurred_at="2026-04-04T00:00:00Z", idempotency_key="supersede-key")
        self.assertEqual(superseded["status"], "superseded")
        self.assertEqual(allegations.get_allegation(self.conn, original["id"])["allegation_text"], "Original attributed account.")
        retry = allegations.supersede_allegation(self.conn, original["id"], replacement_allegation_id=replacement["id"], rationale="Corrected representation.", actor="reviewer", actor_role="admin", idempotency_key="supersede-key")
        self.assertEqual(retry["status"], "superseded")
        with self.assertRaisesRegex(ValueError, "self_reference"):
            allegations.supersede_allegation(self.conn, replacement["id"], replacement_allegation_id=replacement["id"], rationale="cycle", actor="reviewer", actor_role="admin")
        with self.assertRaisesRegex(ValueError, "supersession_cycle"):
            allegations.supersede_allegation(self.conn, replacement["id"], replacement_allegation_id=original["id"], rationale="cycle", actor="reviewer", actor_role="admin")

    def test_withdrawal_requires_source_preserves_original_and_is_not_falsehood(self):
        item = self._create()
        with self.assertRaisesRegex(ValueError, "withdrawal_source_required"):
            allegations.withdraw_allegation(self.conn, item["id"], withdrawal_type="attributed_source_withdrawal", rationale="withdraw", withdrawal_bindings=[self._binding(role="contextual_source")], actor="reviewer", actor_role="admin")
        self._review(item["id"], actor="reviewer", at="2026-04-03T00:00:00Z")
        withdrawn = allegations.withdraw_allegation(self.conn, item["id"], withdrawal_type="attributed_source_withdrawal", rationale="Attributed source withdrew the allegation.", withdrawal_bindings=[self._binding("record_document_association", "2", "withdrawal_source")], actor="reviewer", actor_role="admin", occurred_at="2026-04-05T00:00:00Z", idempotency_key="withdraw-key")
        self.assertEqual(withdrawn["status"], "withdrawn")
        self.assertEqual(allegations.get_allegation(self.conn, item["id"])["allegation_text"], "The source reported a delayed response.")
        self.assertEqual(withdrawn["withdrawals"][0]["withdrawal_type"], "attributed_source_withdrawal")
        retry = allegations.withdraw_allegation(self.conn, item["id"], withdrawal_type="attributed_source_withdrawal", rationale="Attributed source withdrew the allegation.", withdrawal_bindings=[self._binding("record_document_association", "2", "withdrawal_source")], actor="reviewer", actor_role="admin", idempotency_key="withdraw-key")
        self.assertEqual(retry["status"], "withdrawn")
        self.assertNotIn("false", withdrawn["status"])

        supersession_target = self._create(text="Replacement after withdrawal.")
        with self.assertRaisesRegex(ValueError, "supersession_terminal"):
            allegations.supersede_allegation(
                self.conn, item["id"], replacement_allegation_id=supersession_target["id"],
                rationale="late supersession", actor="reviewer", actor_role="admin",
            )

    def test_supersession_blocks_later_withdrawal(self):
        original = self._create(text="Original before supersession.")
        replacement = self._create(text="Replacement account.")
        allegations.supersede_allegation(
            self.conn, original["id"], replacement_allegation_id=replacement["id"],
            rationale="Replace representation.", actor="reviewer", actor_role="admin",
            occurred_at="2026-04-04T00:00:00Z", idempotency_key="terminal-supersession",
        )
        with self.assertRaisesRegex(ValueError, "withdrawal_terminal"):
            allegations.withdraw_allegation(
                self.conn, original["id"], withdrawal_type="administrative_attribution_correction",
                rationale="late withdrawal", withdrawal_bindings=[self._binding("record_document_association", "2", "withdrawal_source")],
                actor="reviewer", actor_role="admin",
            )

    def test_hostile_text_is_escaped_in_admin_detail_and_no_public_surface_exists(self):
        item = self._create(text="<script>alert('x')</script>")
        html = admin_session._render_governed_allegation_page({"allegations": [item]}, admin_session={"username": "admin"}, allegation=item)
        self.assertIn("ATTRIBUTION IS NOT CONFIRMATION", html)
        self.assertIn("not itself evidence, proof, confirmation", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("<script>alert", html)
        source = inspect.getsource(admin_session)
        self.assertNotIn('get("/governed-allegations"', source)
        self.assertNotIn("record_governed_allegation", inspect.getsource(public_association_routes))

    def test_authenticated_get_is_read_only_and_auth_precedes_reader_and_writer(self):
        request = FakeRequest(cookies={})
        reader = Mock()
        writer = Mock()
        with patch.object(admin_session, "require_admin_session", side_effect=FakeHTTPException(401, "admin_session_unauthorized")), \
             patch.object(admin_session.rga, "read_allegation_diagnostic", reader), \
             patch.object(admin_session.rga, "create_allegation", writer):
            with self.assertRaises(FakeHTTPException):
                admin_session.admin_governed_allegations_page(request)
            with self.assertRaises(FakeHTTPException):
                admin_session.admin_governed_allegation_create(request, allegation_category="reported_statement", allegation_text="x", representation_mode="verbatim", attributed_source_label="source", attribution_context="context", subject_label="subject", alleged_period=None, made_or_recorded_at=None, rationale="r", qualification="q", limitations="l", bindings_json="[]", boundary_acknowledged="1", idempotency_key=None)
        reader.assert_not_called()
        writer.assert_not_called()
        self.conn.close()
        request = FakeRequest(cookies={"cde_admin_session": "signed"})
        with patch.object(admin_session, "require_admin_session", return_value={"role": "admin", "username": "admin"}), patch.object(admin_session, "DB_PATH", self.db_path):
            response = admin_session.admin_governed_allegations_page(request)
        self.assertEqual(response.status_code, 200)
        check = sqlite3.connect(self.db_path)
        self.assertIsNone(check.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='record_governed_allegations'").fetchone())
        check.close()


if __name__ == "__main__":
    unittest.main()
