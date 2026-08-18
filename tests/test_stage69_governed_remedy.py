import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from api import record_governed_remedies as remedies


class Stage69RemedyTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.determination = {"id": 7, "status": "accepted_as_attributed_determination_record"}

    def tearDown(self):
        self.conn.close()

    def bindings(self, role="direction_source"):
        return [{"source_type": "canonical_record", "source_id": "REC-69", "binding_role": role}]

    def make(self, **overrides):
        values = dict(remedy_category="record_correction", direction_type="mandatory_direction", title_label="Correct the record", remedy_text="The determination represents a correction.", representation_mode="faithful_paraphrase", beneficiary_or_affected_party="Affected party", obligated_party="Institution", amount=None, currency=None, performance_period_or_deadline=None, conditions_prerequisites=None, scope="Represented scope", limitations=remedies.LIMITATIONS_BOUNDARY, implementation_description=None, rationale="Preserve the represented direction", qualification=remedies.QUALIFICATION_BOUNDARY, determination_id=7, qualification_contract={"epistemic_label":"remedy_or_direction", "determination_link_present":True, "source_basis_present":True, "not_implementation":True, "not_compliance":True, "not_enforcement":True, "not_legal_effect":True}, author_declaration={"acknowledged":True}, representation_declaration={"acknowledged":True}, no_remedy_declaration=None, bindings=self.bindings(), actor="admin", actor_role="administrator")
        values.update(overrides)
        with patch.object(remedies.determinations, "get_determination", return_value=self.determination), patch.object(remedies.inferences, "_source_binding", side_effect=lambda conn, item, **_: dict(item)):
            return remedies.create_remedy(self.conn, **values)

    def test_valid_creation_is_determination_linked_and_idempotent(self):
        item = self.make(idempotency_key="remedy-1")
        retry = self.make(idempotency_key="remedy-1")
        self.assertEqual(item["id"], retry["id"])
        self.assertEqual(item["determination"]["determination_id"], 7)
        self.assertEqual(item["status"], "recorded")

    def test_closed_vocabularies_and_neutral_values_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "category_required"):
            self.make(remedy_category="")
        with self.assertRaisesRegex(ValueError, "category_invalid"):
            self.make(remedy_category="implementation")
        with self.assertRaisesRegex(ValueError, "direction_type_required"):
            self.make(direction_type="")
        with self.assertRaisesRegex(ValueError, "direction_type_invalid"):
            self.make(direction_type="enforced")
        with self.assertRaisesRegex(ValueError, "representation_mode_invalid"):
            self.make(representation_mode="machine_verified")

    def test_required_declarations_and_qualification_are_structured(self):
        with self.assertRaisesRegex(ValueError, "author_declaration"):
            self.make(author_declaration={"acknowledged":False})
        with self.assertRaisesRegex(ValueError, "representation_declaration"):
            self.make(representation_declaration={"acknowledged":False})
        with self.assertRaisesRegex(ValueError, "qualification_contract"):
            self.make(qualification_contract={})

    def test_direction_source_is_required_and_roles_are_closed(self):
        with self.assertRaisesRegex(ValueError, "direction_source_required"):
            self.make(bindings=self.bindings("contextual_source"))
        with self.assertRaisesRegex(ValueError, "binding_invalid"):
            self.make(bindings=[{"source_type":"governed_inference", "source_id":"1", "binding_role":"direction_source"}])
        with self.assertRaisesRegex(ValueError, "binding_invalid"):
            self.make(bindings=[{"source_type":"canonical_record", "source_id":"REC-69", "binding_role":"implementation_proof"}])

    def test_invalid_multi_binding_rolls_back_complete_write(self):
        with patch.object(remedies.determinations, "get_determination", return_value=self.determination), patch.object(remedies.inferences, "_source_binding", side_effect=[{"source_type":"canonical_record", "source_id":"REC-69", "binding_role":"direction_source"}, ValueError("source_not_found")]):
            with self.assertRaisesRegex(ValueError, "source_not_found"):
                remedies.create_remedy(self.conn, **{**self._base_without_context(), "bindings": self.bindings() + [{"source_type":"canonical_record", "source_id":"MISSING", "binding_role":"contextual_source"}]})
        self.assertFalse(remedies._table_exists(self.conn, "record_governed_remedies"))

    def _base_without_context(self):
        return dict(remedy_category="record_correction", direction_type="mandatory_direction", title_label="Correct", remedy_text="Direction", representation_mode="faithful_paraphrase", beneficiary_or_affected_party=None, obligated_party=None, amount=None, currency=None, performance_period_or_deadline=None, conditions_prerequisites=None, scope=None, limitations=remedies.LIMITATIONS_BOUNDARY, implementation_description=None, rationale="Preserve", qualification=remedies.QUALIFICATION_BOUNDARY, determination_id=7, qualification_contract={"epistemic_label":"remedy_or_direction", "determination_link_present":True, "source_basis_present":True, "not_implementation":True, "not_compliance":True, "not_enforcement":True, "not_legal_effect":True}, author_declaration={"acknowledged":True}, representation_declaration={"acknowledged":True}, no_remedy_declaration=None, actor="admin", actor_role="administrator")

    def test_no_remedy_requires_express_declaration_and_rejects_affirmative_fields(self):
        with self.assertRaisesRegex(ValueError, "no_remedy_declaration"):
            self.make(remedy_category="no_remedy_directed", direction_type="no_direction", remedy_text="", beneficiary_or_affected_party=None, obligated_party=None, scope=None, no_remedy_declaration={"acknowledged":False})
        with self.assertRaisesRegex(ValueError, "no_remedy_affirmative_fields"):
            self.make(remedy_category="no_remedy_directed", direction_type="no_direction", remedy_text="", no_remedy_declaration={"acknowledged":True}, amount="100")
        with self.assertRaisesRegex(ValueError, "no_remedy_affirmative_fields"):
            self.make(remedy_category="no_remedy_directed", direction_type="no_direction", remedy_text="", obligated_party=None, beneficiary_or_affected_party="Party", no_remedy_declaration={"acknowledged":True})
        with self.assertRaisesRegex(ValueError, "no_remedy_affirmative_fields"):
            self.make(remedy_category="no_remedy_directed", direction_type="no_direction", remedy_text="", obligated_party=None, conditions_prerequisites="Condition", no_remedy_declaration={"acknowledged":True})
        item = self.make(remedy_category="no_remedy_directed", direction_type="no_direction", remedy_text="", beneficiary_or_affected_party=None, obligated_party=None, scope=None, no_remedy_declaration={"acknowledged":True})
        self.assertEqual(item["remedy_category"], "no_remedy_directed")

    def test_review_is_append_only_self_review_and_supersession_preserves_original(self):
        item = self.make()
        reviewed = remedies.review_remedy(self.conn, remedy_id=item["id"], disposition="accepted_as_represented_direction", rationale="Preserve attribution", boundary_declaration={"acknowledged":True}, actor="admin", actor_role="administrator", idempotency_key="review-1")
        self.assertEqual(reviewed["status"], "accepted_as_represented_direction")
        self.assertEqual(reviewed["reviews"][0]["is_self_review"], 1)
        replacement = self.make(title_label="Corrected direction")
        result = remedies.supersede_remedy(self.conn, remedy_id=item["id"], replacement_remedy_id=replacement["id"], rationale="Correct representation", actor="admin", actor_role="administrator", idempotency_key="sup-1")
        self.assertEqual(result["status"], "superseded")
        self.assertEqual(remedies.get_remedy(self.conn, item["id"])["remedy_text"], "The determination represents a correction.")
        self.assertEqual(remedies.supersede_remedy(self.conn, remedy_id=item["id"], replacement_remedy_id=replacement["id"], rationale="Correct representation", actor="admin", actor_role="administrator", idempotency_key="sup-1")["status"], "superseded")

    def test_competing_remedies_and_status_language_remain_epistemically_restrained(self):
        first = self.make(direction_type="recommendation", title_label="Recommended correction")
        second = self.make(direction_type="conditional_direction", title_label="Conditional correction")
        self.assertEqual(first["determination"]["determination_id"], second["determination"]["determination_id"])
        self.assertNotIn(first["status"], {"implemented", "complied_with", "satisfied", "enforced"})

    def test_read_only_diagnostic_does_not_initialize_tables(self):
        with tempfile.NamedTemporaryFile(suffix=".db") as handle:
            result = remedies.read_remedy_diagnostic(db_path=handle.name)
            self.assertFalse(result["remedy_table_present"])
        self.assertFalse(remedies._table_exists(self.conn, "record_governed_remedies"))

    def test_admin_surface_is_neutral_and_publicly_scoped(self):
        source = Path("api/routes/admin_session.py").read_text(encoding="utf-8")
        stage = source[source.index("def _stage69_sources"):]
        for phrase in ("/admin/governed-remedies", "Remedies and Directions", "Choose remedy category", "Choose direction type", "Choose represented determination", "Choose governed source", "Choose binding role", 'id="stage69-source-payload" name="bindings_json" value=""', "DIRECTION IS NOT IMPLEMENTATION", "No source selected."):
            self.assertIn(phrase, stage)
        self.assertNotIn('<textarea name="bindings_json"', stage)
        self.assertNotIn("/api/remedies", stage)


if __name__ == "__main__":
    unittest.main()
