import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.test_admin_session import install_fastapi_stubs

install_fastapi_stubs()

from api import record_document_associations as associations
from api import record_governed_allegations as allegations
from api import record_governed_responses as responses


class Stage65GovernedResponseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "records.db"
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        associations.ensure_association_tables(self.conn)
        self.conn.execute("CREATE TABLE records (reference TEXT PRIMARY KEY, version INTEGER, generated_at TEXT)")
        self.conn.execute("INSERT INTO records VALUES ('REC-65', 1, '2026-01-01T00:00:00Z')")
        self.conn.execute("CREATE TABLE record_pattern_observations (id INTEGER PRIMARY KEY, status TEXT, created_at TEXT)")
        self.conn.execute("INSERT INTO record_pattern_observations VALUES (7, 'accepted', '2026-01-01T00:00:00Z')")
        self.conn.execute("INSERT INTO record_pattern_observations VALUES (8, 'candidate', '2026-01-01T00:00:00Z')")
        self.conn.execute("""INSERT INTO record_document_associations
            (id, public_reference, record_reference, document_id, relationship_type,
             public_label, is_active, is_public, created_at, created_by, updated_at, updated_by)
            VALUES (1, 'ASSOC-65', 'REC-65', 'DOC-65', 'response_source', 'Response source', 1, 1, '2026-01-01', 'admin', '2026-01-01', 'admin')""")
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        self.temp.cleanup()

    def binding(self, source_type="record_document_association", source_id="1", role="response_source"):
        return {"source_type": source_type, "source_id": source_id, "binding_role": role}

    def qualification(self, limitations="The response may coexist with the allegation and alternative accounts."):
        return {
            "epistemic_label": "response", "attribution_present": True,
            "source_basis_present": True, "not_evidence": True,
            "not_observation": True, "not_inference": True,
            "not_determination": True, "not_confirmation": True,
            "not_resolution": True, "not_admission": True,
            "alternatives_possible": True, "limitations": limitations,
        }

    def create_allegation(self, key="allegation-65"):
        return allegations.create_allegation(
            self.conn, allegation_category="reported_statement", allegation_text="The source reported a delay.",
            representation_mode="faithful_paraphrase", representation_contract={"human_verified": True, "faithful_representation": True},
            attributed_source_label="Reporting source", attribution_context="Written source", subject_label="Unit",
            alleged_period=None, made_or_recorded_at=None, rationale="Preserve the allegation.",
            qualification="This is an attributed allegation.", limitations="It may remain disputed.",
            qualification_contract={"epistemic_label":"allegation", "attribution_present":True, "source_basis_present":True, "not_evidence":True, "not_observation":True, "not_inference":True, "not_determination":True, "not_confirmation":True, "alternatives_possible":True, "limitations":"It may remain disputed."},
            bindings=[{"source_type":"record_document_association", "source_id":"1", "binding_role":"attribution_source"}],
            actor="author", actor_role="admin", author_declaration={"acknowledged": True}, idempotency_key=key,
        )

    def create(self, *, allegation_id=None, category="substantive_response", bindings=None, key="response-65", notice=None, mode="faithful_paraphrase", rep=None, recorder=None):
        return responses.create_response(
            self.conn, allegation_id=allegation_id or self.create_allegation()["id"], response_category=category,
            response_text="The respondent provided a contextual account.", representation_mode=mode,
            representation_contract=rep or {"human_verified": True, "faithful_representation": True},
            attributed_respondent_label="Respondent organisation", attribution_context="Governed communication",
            subject_label="Unit", respondent_capacity="authorised representative", response_period=None,
            recorded_at=None, notice_details=notice, rationale="Preserve participation without resolving the allegation.",
            qualification="This is a response, not a resolution.", limitations="Alternative accounts may coexist.",
            qualification_contract=self.qualification(), bindings=bindings or [self.binding()],
            recorder_declaration=recorder or {"acknowledged": True}, actor="author", actor_role="admin", idempotency_key=key,
        )

    def test_creation_requires_exact_allegation_and_response_source(self):
        allegation = self.create_allegation()
        item = self.create(allegation_id=allegation["id"])
        self.assertEqual(item["allegation_id"], allegation["id"])
        with self.assertRaisesRegex(ValueError, "response_source_required"):
            self.create(allegation_id=allegation["id"], bindings=[self.binding(role="contextual_source")], key="missing-source")
        with self.assertRaises((ValueError, TypeError)):
            self.create(allegation_id="not-an-id", key="bad-target")

    def test_target_and_source_domains_are_separate(self):
        allegation = self.create_allegation()
        with self.assertRaisesRegex(ValueError, "not_found|invalid"):
            self.create(allegation_id=999, key="missing-target")
        for source_type in ("governed_inference", "governed_allegation", "response"):
            with self.assertRaisesRegex(ValueError, "source_type_invalid"):
                self.create(allegation_id=allegation["id"], bindings=[self.binding(source_type=source_type)], key=source_type)
        with self.assertRaisesRegex(ValueError, "not_accepted"):
            self.create(allegation_id=allegation["id"], bindings=[self.binding(role="response_source", source_type="accepted_pattern_observation", source_id="8")], key="unaccepted")

    def test_closed_categories_modes_and_declarations(self):
        allegation = self.create_allegation()
        self.assertEqual(self.create(allegation_id=allegation["id"])["response_category"], "substantive_response")
        self.assertEqual(self.create(allegation_id=allegation["id"], category="express_declination", rep={"human_verified": True, "faithful_representation": True, "express_declination_source": True}, key="declination")["response_category"], "express_declination")
        with self.assertRaisesRegex(ValueError, "express_declination_source_declaration"):
            self.create(allegation_id=allegation["id"], category="express_declination", key="declination-missing-source-declaration")
        with self.assertRaisesRegex(ValueError, "category_invalid"):
            self.create(allegation_id=allegation["id"], category="confirmed", key="category")
        with self.assertRaisesRegex(ValueError, "exact_wording"):
            self.create(allegation_id=allegation["id"], mode="verbatim", rep={"human_verified": True}, key="verbatim")
        with self.assertRaisesRegex(ValueError, "recorder_boundary"):
            self.create(allegation_id=allegation["id"], recorder={"acknowledged": False}, key="declaration")

    def test_notice_and_roles_are_not_resolution(self):
        allegation = self.create_allegation()
        with self.assertRaisesRegex(ValueError, "notice_source_required"):
            self.create(allegation_id=allegation["id"], notice="Notice was recorded", key="notice-missing")
        item = self.create(allegation_id=allegation["id"], notice="Notice was sent", bindings=[self.binding(), self.binding(role="notice_source")], key="notice")
        self.assertEqual(item["status"], "recorded")
        with self.assertRaisesRegex(ValueError, "binding_role_invalid"):
            self.create(allegation_id=allegation["id"], bindings=[self.binding(role="withdrawal_source")], key="withdrawal-role")
        self.assertEqual(allegations.get_allegation(self.conn, allegation["id"])["status"], "recorded")

    def test_multiple_competing_responses_and_idempotency(self):
        allegation = self.create_allegation()
        first = self.create(allegation_id=allegation["id"], key="same")
        retry = self.create(allegation_id=allegation["id"], key="same")
        self.assertEqual(first["id"], retry["id"])
        with self.assertRaisesRegex(ValueError, "idempotency_conflict"):
            self.create(allegation_id=allegation["id"], key="same", category="partial_response")
        second = self.create(allegation_id=allegation["id"], key="competing")
        self.assertNotEqual(first["id"], second["id"])
        self.assertNotIn("confirmed", first["status"])

    def test_transaction_rolls_back_invalid_multi_binding(self):
        allegation = self.create_allegation()
        with self.assertRaisesRegex(ValueError, "source_not_found"):
            self.create(allegation_id=allegation["id"], bindings=[self.binding(), self.binding(source_id="999", role="contextual_source")], key="rollback")
        self.assertFalse(responses._table_exists(self.conn, "record_governed_responses"))

    def test_review_self_review_and_history_are_append_only(self):
        item = self.create()
        accepted = responses.review_response(self.conn, item["id"], disposition="accepted_as_attributed_response", rationale="Attribution and faithful representation only.", boundary_declaration={"acknowledged": True}, actor="author", actor_role="admin", idempotency_key="review")
        self.assertEqual(accepted["status"], "accepted_as_attributed_response")
        self.assertEqual(accepted["reviews"][0]["is_self_review"], 1)
        self.assertEqual(responses.review_response(self.conn, item["id"], disposition="accepted_as_attributed_response", rationale="Attribution and faithful representation only.", boundary_declaration={"acknowledged": True}, actor="author", actor_role="admin", idempotency_key="review")["id"], item["id"])
        with self.assertRaisesRegex(ValueError, "review_idempotency_conflict"):
            responses.review_response(self.conn, item["id"], disposition="not_accepted_as_attributed", rationale="different", boundary_declaration={"acknowledged": True}, actor="author", actor_role="admin", idempotency_key="review")

    def test_supersession_requires_same_target_and_preserves_original(self):
        allegation = self.create_allegation()
        original = self.create(allegation_id=allegation["id"], key="original")
        replacement = self.create(allegation_id=allegation["id"], key="replacement")
        result = responses.supersede_response(self.conn, original["id"], replacement_response_id=replacement["id"], rationale="A corrected representation is separately preserved.", actor="reviewer", actor_role="admin", idempotency_key="supersede")
        self.assertEqual(result["status"], "superseded")
        self.assertEqual(responses.get_response(self.conn, original["id"])["response_text"], original["response_text"])
        other_allegation = self.create_allegation("other-allegation-target")
        other = self.create(allegation_id=other_allegation["id"], key="other-allegation")
        still_active = self.create(allegation_id=allegation["id"], key="still-active")
        with self.assertRaisesRegex(ValueError, "target_mismatch"):
            responses.supersede_response(self.conn, still_active["id"], replacement_response_id=other["id"], rationale="bad", actor="x", actor_role="admin")

    def test_withdrawal_terminal_order_and_source(self):
        item = self.create()
        with self.assertRaisesRegex(ValueError, "binding_role_invalid"):
            responses.withdraw_response(self.conn, item["id"], withdrawal_type="attributed_respondent_withdrawal", rationale="source", withdrawal_bindings=[self.binding()], actor="author", actor_role="admin")
        withdrawn = responses.withdraw_response(self.conn, item["id"], withdrawal_type="attributed_respondent_withdrawal", rationale="The source records withdrawal; this does not resolve the allegation.", withdrawal_bindings=[self.binding(role="withdrawal_source")], actor="author", actor_role="admin", idempotency_key="withdraw")
        self.assertEqual(withdrawn["status"], "withdrawn")
        with self.assertRaisesRegex(ValueError, "supersession_terminal"):
            responses.supersede_response(self.conn, item["id"], replacement_response_id=self.create(key="replacement-after-withdrawal")["id"], rationale="late", actor="x", actor_role="admin")

    def test_contrary_contextual_and_response_sources_coexist_without_resolution(self):
        allegation = self.create_allegation()
        item = self.create(allegation_id=allegation["id"], bindings=[
            self.binding(role="response_source"),
            self.binding(role="contextual_source", source_type="canonical_record", source_id="REC-65"),
            self.binding(role="contrary_source", source_type="accepted_pattern_observation", source_id="7"),
        ])
        self.assertEqual({x["binding_role"] for x in item["bindings"]}, {"response_source", "contextual_source", "contrary_source"})
        self.assertEqual(allegations.get_allegation(self.conn, allegation["id"])["status"], "recorded")
        self.assertNotIn("resolved", item["status"])

    def test_silence_does_not_create_response_and_response_does_not_mutate_target(self):
        allegation = self.create_allegation()
        before = allegations.get_allegation(self.conn, allegation["id"])
        self.assertEqual(responses.read_response_diagnostic(db_path=self.path)["responses"], [])
        after = self.create(allegation_id=allegation["id"])
        target = allegations.get_allegation(self.conn, allegation["id"])
        self.assertEqual(target["allegation_text"], before["allegation_text"])
        self.assertEqual(target["status"], before["status"])
        self.assertEqual(after["status"], "recorded")

    def test_withdrawal_is_idempotent_and_supersession_terminal_is_symmetric(self):
        item = self.create(key="withdraw-idempotent")
        kwargs = dict(response_id=item["id"], withdrawal_type="administrative_attribution_correction", rationale="Correct the attribution record only.", withdrawal_bindings=[self.binding(role="withdrawal_source")], actor="admin", actor_role="admin", idempotency_key="withdraw-repeat")
        first = responses.withdraw_response(self.conn, **kwargs)
        retry = responses.withdraw_response(self.conn, **kwargs)
        self.assertEqual(first["id"], retry["id"])
        with self.assertRaisesRegex(ValueError, "withdrawal_idempotency_conflict"):
            responses.withdraw_response(self.conn, **{**kwargs, "rationale": "changed"})
        original = self.create(key="supersede-original")
        replacement = self.create(key="supersede-replacement")
        responses.supersede_response(self.conn, original["id"], replacement_response_id=replacement["id"], rationale="Replace representation.", actor="admin", actor_role="admin", idempotency_key="supersede-repeat")
        with self.assertRaisesRegex(ValueError, "withdrawal_terminal"):
            responses.withdraw_response(self.conn, response_id=original["id"], withdrawal_type="attributed_respondent_withdrawal", rationale="late", withdrawal_bindings=[self.binding(role="withdrawal_source")], actor="admin", actor_role="admin")

    def test_malformed_bindings_and_unknown_fields_fail_closed(self):
        allegation = self.create_allegation()
        with self.assertRaisesRegex(ValueError, "binding_invalid"):
            self.create(allegation_id=allegation["id"], bindings=["not-a-binding"], key="malformed")
        with self.assertRaisesRegex(ValueError, "binding_invalid"):
            self.create(allegation_id=allegation["id"], bindings=[{**self.binding(), "unexpected": "x"}], key="unknown")
        self.assertFalse(responses._table_exists(self.conn, "record_governed_responses"))

    def test_admin_rendering_is_restrained_and_source_transport_is_not_editable_json(self):
        import api.routes.admin_session as admin_session
        html = admin_session._render_governed_response_page({"responses": []}, admin_session={"username": "admin"}, candidates=[], allegations_list=[])
        self.assertIn("RESPONSE IS NOT RESOLUTION", html)
        self.assertIn("response_bindings_json", html)
        self.assertIn("No sources selected yet", html)
        self.assertIn('<option value="" selected>Choose an allegation</option>', html)
        self.assertIn('<option value="" selected>Choose a source</option>', html)
        self.assertNotIn('textarea name="response_bindings_json"', html)
        self.assertIn("express_declination_source_acknowledged", html)

    def test_get_is_read_only_and_public_surface_is_not_added(self):
        self.assertFalse(responses._table_exists(self.conn, "record_governed_responses"))
        self.assertEqual(responses.read_response_diagnostic(db_path=self.path)["responses"], [])
        self.assertFalse(responses._table_exists(self.conn, "record_governed_responses"))
        import inspect
        import api.routes.admin_session as admin_session
        source = inspect.getsource(admin_session)
        self.assertIn('/admin/governed-responses', source)
        self.assertNotIn('@router.get("/governed-responses"', source)


if __name__ == "__main__":
    unittest.main()
