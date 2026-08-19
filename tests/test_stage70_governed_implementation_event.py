import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from api import record_governed_implementation_events as events


class Stage70ImplementationEventTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.remedy = {"id": 9, "status": "accepted_as_represented_direction", "determination": {"determination_id": 3}}

    def tearDown(self):
        self.conn.close()

    def source(self, role="event_source", source_id="DOC-70"):
        return [{"source_type": "published_document", "source_id": source_id, "binding_role": role}]

    def base(self, **overrides):
        values = dict(
            event_category="implementation_reported", epistemic_basis="attributed_report",
            title_label="Implementation report", event_description="A source reports an action.",
            representation_mode="faithful_paraphrase", attributed_participant="Institution",
            represented_capacity="Respondent", represented_event_date_or_period="2026-08-01",
            recorded_date="2026-08-02", represented_amount_quantity_extent=None,
            represented_deadline_or_extension=None, verification_method=None,
            verification_conclusion=None, rationale="Preserve the represented event.",
            qualification=events.QUALIFICATION_BOUNDARY, limitations=events.LIMITATIONS_BOUNDARY,
            qualification_contract={"epistemic_label": "implementation_or_compliance_event", "remedy_link_present": True, "source_basis_present": True, "not_implementation_verified": True, "not_compliance_status": True, "not_breach_finding": True, "not_legal_effect": True},
            author_declaration={"acknowledged": True}, representation_declaration={"acknowledged": True},
            conditional_declaration=None, remedy_id=9, bindings=self.source(), governed_objects=None,
            actor="admin", actor_role="administrator", idempotency_key=None,
        )
        values.update(overrides)
        remedy_value = values.pop("_remedy", self.remedy)
        source_side_effect = values.pop("_source_side_effect", lambda conn, item, **_: dict(item))
        with patch.object(events.remedies, "get_remedy", return_value=remedy_value), patch.object(events.inferences, "_source_binding", side_effect=source_side_effect):
            return events.create_implementation_event(self.conn, **values)

    def test_valid_event_links_exactly_one_remedy_and_is_idempotent(self):
        item = self.base(idempotency_key="event-1")
        retry = self.base(idempotency_key="event-1")
        self.assertEqual(item["id"], retry["id"])
        self.assertEqual(item["remedy"]["remedy_id"], 9)
        self.assertEqual(item["status"], "recorded")

    def test_closed_categories_bases_and_neutral_values_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "category_required"):
            self.base(event_category="")
        with self.assertRaisesRegex(ValueError, "category_invalid"):
            self.base(event_category="implemented")
        with self.assertRaisesRegex(ValueError, "epistemic_basis_required"):
            self.base(epistemic_basis="")
        with self.assertRaisesRegex(ValueError, "basis_mismatch"):
            self.base(event_category="compliance_evidence_submitted", epistemic_basis="attributed_report")
        with self.assertRaisesRegex(ValueError, "representation_mode_invalid"):
            self.base(representation_mode="machine_verified")

    def test_structured_declarations_and_qualification_are_required(self):
        with self.assertRaisesRegex(ValueError, "author_declaration"):
            self.base(author_declaration={"acknowledged": False})
        with self.assertRaisesRegex(ValueError, "representation_declaration"):
            self.base(representation_declaration={"acknowledged": False})
        with self.assertRaisesRegex(ValueError, "qualification_contract"):
            self.base(qualification_contract={})
        with self.assertRaisesRegex(ValueError, "conditional_declaration_inapplicable"):
            self.base(conditional_declaration={"acknowledged": True})

    def test_source_roles_and_conditional_requirements_are_strict(self):
        with self.assertRaisesRegex(ValueError, "source_required"):
            self.base(bindings=self.source("contextual_source"))
        with self.assertRaisesRegex(ValueError, "binding_invalid"):
            self.base(bindings=[{"source_type": "governed_inference", "source_id": "1", "binding_role": "event_source"}])
        with self.assertRaisesRegex(ValueError, "verification_source_required"):
            self.base(event_category="verification_performed", epistemic_basis="independent_verification_record", verification_method="Interview", verification_conclusion="verification_inconclusive", conditional_declaration={"acknowledged": True})
        with self.assertRaisesRegex(ValueError, "extension_source_required"):
            self.base(event_category="deadline_extension_recorded", represented_deadline_or_extension="Extended", conditional_declaration={"acknowledged": True})

    def test_verification_is_attributed_and_not_automatically_verified(self):
        item = self.base(event_category="verification_performed", epistemic_basis="independent_verification_record", verification_method="Document review", verification_conclusion="verification_inconclusive", conditional_declaration={"acknowledged": True}, bindings=self.source() + self.source("verification_source", "VER-70"))
        self.assertEqual(item["verification_conclusion"], "verification_inconclusive")
        self.assertNotIn(item["status"], {"implemented", "compliant", "verified_implementation"})

    def test_non_compliance_requires_an_existing_allegation_object(self):
        with self.assertRaisesRegex(ValueError, "allegation_link_required"):
            self.base(event_category="non_compliance_alleged", conditional_declaration={"acknowledged": True})
        self.conn.execute("CREATE TABLE record_governed_allegations (id INTEGER PRIMARY KEY, status TEXT)")
        self.conn.execute("INSERT INTO record_governed_allegations VALUES (4, 'accepted_as_attributed_allegation')")
        item = self.base(event_category="non_compliance_alleged", conditional_declaration={"acknowledged": True}, governed_objects=[{"object_type": "governed_allegation", "object_id": 4, "relationship_role": "allegation_context"}])
        self.assertEqual(item["governed_objects"][0]["object_type"], "governed_allegation")

    def test_formal_completion_requires_distinct_eligible_determination(self):
        self.conn.execute("CREATE TABLE record_governed_determinations (id INTEGER PRIMARY KEY, status TEXT)")
        self.conn.execute("INSERT INTO record_governed_determinations VALUES (3, 'accepted_as_attributed_determination_record')")
        self.conn.execute("INSERT INTO record_governed_determinations VALUES (8, 'accepted_as_attributed_determination_record')")
        with patch.object(events.determinations, "get_determination", return_value={"id": 3, "status": "accepted_as_attributed_determination_record"}):
            with self.assertRaisesRegex(ValueError, "formal_determination_must_be_distinct"):
                self.base(event_category="implementation_completed_as_formally_determined", epistemic_basis="formal_determination", conditional_declaration={"acknowledged": True}, governed_objects=[{"object_type": "governed_determination", "object_id": 3, "relationship_role": "formal_completion_determination"}])
        self.remedy["determination"] = {"determination_id": 3}
        with patch.object(events.determinations, "get_determination", return_value={"id": 8, "status": "accepted_as_attributed_determination_record"}):
            item = self.base(event_category="implementation_completed_as_formally_determined", epistemic_basis="formal_determination", conditional_declaration={"acknowledged": True}, governed_objects=[{"object_type": "governed_determination", "object_id": 8, "relationship_role": "formal_completion_determination"}])
        self.assertEqual(item["governed_objects"][0]["object_id"], 8)

    def test_invalid_multi_binding_rolls_back_event_link_objects_and_bindings(self):
        calls = [{"source_type": "published_document", "source_id": "DOC-70", "binding_role": "event_source"}, ValueError("source_not_found")]
        with self.assertRaisesRegex(ValueError, "source_not_found"):
            self.base(bindings=self.source() + self.source("contextual_source", "MISSING"), _source_side_effect=calls)
        self.assertFalse(events._table_exists(self.conn, "record_governed_implementation_events"))

    def test_review_and_supersession_are_append_only_and_idempotent(self):
        item = self.base()
        reviewed = events.review_implementation_event(self.conn, event_id=item["id"], disposition="accepted_as_represented_event", rationale="Faithful preservation", boundary_declaration={"acknowledged": True}, actor="admin", actor_role="administrator", idempotency_key="review-70")
        self.assertEqual(reviewed["status"], "accepted_as_represented_event")
        self.assertEqual(reviewed["reviews"][0]["is_self_review"], 1)
        replacement = self.base(title_label="Corrected report")
        result = events.supersede_implementation_event(self.conn, event_id=item["id"], replacement_event_id=replacement["id"], rationale="Correct representation", actor="admin", actor_role="administrator", idempotency_key="sup-70")
        self.assertEqual(result["status"], "superseded")
        self.assertEqual(events.supersede_implementation_event(self.conn, event_id=item["id"], replacement_event_id=replacement["id"], rationale="Correct representation", actor="admin", actor_role="administrator", idempotency_key="sup-70")["status"], "superseded")
        self.assertEqual(events.get_implementation_event(self.conn, item["id"])["event_description"], "A source reports an action.")

    def test_supersession_requires_same_remedy_and_rejects_cycles(self):
        first = self.base()
        other = {**self.remedy, "id": 10}
        second = self.base(idempotency_key="event-other", remedy_id=10, _remedy=other)
        with self.assertRaisesRegex(ValueError, "remedy_mismatch"):
            events.supersede_implementation_event(self.conn, event_id=first["id"], replacement_event_id=second["id"], rationale="No", actor="admin", actor_role="administrator")
        with self.assertRaisesRegex(ValueError, "self_supersession"):
            events.supersede_implementation_event(self.conn, event_id=first["id"], replacement_event_id=first["id"], rationale="No", actor="admin", actor_role="administrator")

    def test_read_only_diagnostic_does_not_initialize_stage70_tables(self):
        with tempfile.NamedTemporaryFile(suffix=".db") as handle:
            result = events.read_implementation_event_diagnostic(db_path=handle.name)
            self.assertFalse(result["implementation_event_table_present"])
        self.assertFalse(events._table_exists(self.conn, "record_governed_implementation_events"))

    def test_admin_surface_is_neutral_authenticated_and_epistemically_restrained(self):
        source = Path("api/routes/admin_session.py").read_text(encoding="utf-8")
        stage = source[source.index("def _stage70_remedies"):]
        for phrase in ("/admin/governed-implementation-events", "Implementation and Compliance Events", "Choose event category", "Choose epistemic basis", "Choose represented remedy or direction", "Choose governed source", "Choose binding role", 'id="stage70-source-payload" name="bindings_json" value=""', 'id="stage70-object-payload" name="governed_objects_json" value=""', "IMPLEMENTATION REPORTED IS NOT IMPLEMENTATION VERIFIED"):
            self.assertIn(phrase, stage)
        self.assertNotIn('<textarea name="bindings_json"', stage)
        self.assertNotIn("compliance_score", stage)

    def test_stage70_is_not_public_or_automated(self):
        source = Path("api/routes/admin_session.py").read_text(encoding="utf-8")
        self.assertNotIn('@router.get("/governed-implementation-events"', source)
        self.assertNotIn("automatic_compliance", source)
        self.assertNotIn("deadline_monitor", source)
        self.assertNotIn("compliance_score", source)


if __name__ == "__main__":
    unittest.main()
