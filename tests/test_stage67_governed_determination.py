import sqlite3
import tempfile
import unittest
from pathlib import Path

from api import record_governed_decision_authorities as authorities
from api import record_governed_determinations as determination


class Stage67DeterminationTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("CREATE TABLE records (reference TEXT PRIMARY KEY, version TEXT, generated_at TEXT)")
        self.conn.execute("INSERT INTO records VALUES ('REC-1','1','2026-01-01')")

    def tearDown(self):
        self.conn.close()

    def q(self):
        return {"epistemic_label": "determination", "source_basis_present": True, "not_validation": True, "not_jurisdiction": True, "not_lawfulness": True, "not_correctness": True, "not_enforceability": True, "not_finality": True}

    def source(self, role="determination_source"):
        return [{"source_type": "canonical_record", "source_id": "REC-1", "binding_role": role}]

    def make_authority(self, review=True, variant=""):
        suffix = f" {variant}" if variant else ""
        item = authorities.create_authority(
            self.conn, holder_kind="office", holder_label=f"Decision Office{suffix}", institution_context="CDE",
            office_role_capacity="Administrative decision office", named_holder=None,
            holder_effective_period="2026-01-01", attribution_context="Governance record",
            rationale="Preserve authority representation", qualification="Source-backed representation",
            limitations="May be incomplete", qualification_contract={"epistemic_label":"authority", "source_basis_present":True, "not_conferral":True, "not_appointment_validation":True, "not_jurisdiction":True, "not_lawfulness":True, "not_determination":True, "alternatives_possible":True},
            recorder_declaration={"acknowledged": True}, bindings=self.source("authority_basis_source"),
            mandate={"mandate_basis_category":"governance_instrument", "title_label":f"Decision mandate{suffix}", "subject_matter_scope":"records", "procedural_scope":"decision recording", "territorial_organisational_scope":"CDE", "affected_class":"record", "effective_from":"2026-01-01", "effective_to":"2026-12-31", "express_limitations":"No legal validation", "conditions_prerequisites":"Source-backed record", "delegation_status":"not_delegated", "rationale":"Preserve mandate representation", "qualification":"Source-backed representation", "limitations":"May be incomplete"},
            actor="admin", actor_role="administrator")
        if review:
            authorities.review_authority(self.conn, authority_id=item["id"], mandate_id=None, disposition="accepted_as_source_backed_authority_record", rationale="Retain source-backed authority", boundary_declaration={"acknowledged":True}, actor="reviewer", actor_role="administrator")
            authorities.review_authority(self.conn, authority_id=item["id"], mandate_id=item["mandates"][0]["id"], disposition="accepted_as_source_backed_authority_record", rationale="Retain source-backed mandate", boundary_declaration={"acknowledged":True}, actor="reviewer", actor_role="administrator")
        return item["id"], item["mandates"][0]["id"]

    def make(self, **overrides):
        authority_id = overrides.pop("authority_id", None)
        mandate_id = overrides.pop("mandate_id", None)
        if authority_id is None or mandate_id is None:
            authority_id, mandate_id = self.make_authority()
        values = dict(
            determination_category="merits_determination", title_label="Recorded conclusion",
            formal_outcome="The source records an outcome.", representation_mode="faithful_paraphrase",
            issues_determined="Issue A", reasons="Reasons as represented by the source.", reasons_status="reasons_recorded",
            decision_date_or_period="2026-06-01", recorded_date="2026-06-02", affected_subject_or_class="REC-1",
            finality_description="Finality as represented", implementation_or_remedy=None,
            qualification="Source-bound determination record", limitations="Correctness is not established",
            qualification_contract=self.q(), authority_id=authority_id, mandate_id=mandate_id,
            authority_mandate_declaration={"acknowledged":True}, scope_declaration={"acknowledged":True},
            representation_declaration={"acknowledged":True, "mode":"faithful_paraphrase"}, recorder_declaration={"acknowledged":True},
            bindings=self.source(), governed_objects=[], actor="admin", actor_role="administrator",
        )
        values.update(overrides)
        return determination.create_determination(self.conn, **values)

    def test_valid_creation_and_distinct_authority_mandate_link(self):
        item = self.make()
        self.assertEqual(item["authoring_mode"], "human_recorded")
        self.assertEqual(item["status"], "recorded")
        self.assertEqual(item["authority_mandate"]["authority_id"], item["request_payload"]["authority_id"])
        self.assertEqual(set(item["authority_mandate"]), {"id", "determination_id", "authority_id", "mandate_id"})

    def test_closed_category_and_representation_modes_are_deliberate(self):
        with self.assertRaisesRegex(ValueError, "category_required"):
            self.make(determination_category="")
        with self.assertRaisesRegex(ValueError, "category_invalid"):
            self.make(determination_category="lawful")
        with self.assertRaisesRegex(ValueError, "representation_mode_required"):
            self.make(representation_mode="")
        with self.assertRaisesRegex(ValueError, "representation_mode_invalid"):
            self.make(representation_mode="machine_verified")

    def test_missing_or_unaccepted_authority_mandate_fails(self):
        authority_id, mandate_id = self.make_authority(review=False)
        with self.assertRaisesRegex(ValueError, "not_accepted"):
            self.make(authority_id=authority_id, mandate_id=mandate_id)

    def test_authority_mandate_mismatch_is_rejected(self):
        first_authority, first_mandate = self.make_authority()
        second_authority, _ = self.make_authority(variant="second")
        with self.assertRaisesRegex(ValueError, "mismatch"):
            determination._authority_mandate(self.conn, second_authority, first_mandate, None, {})

    def test_source_roles_and_object_links_are_separate_and_validated(self):
        item = self.make(bindings=self.source("determination_source") + self.source("reasons_source"))
        self.assertEqual({x["binding_role"] for x in item["bindings"]}, {"determination_source", "reasons_source"})
        with self.assertRaisesRegex(ValueError, "determination_source_required"):
            self.make(bindings=self.source("reasons_source"))
        with self.assertRaisesRegex(ValueError, "binding_invalid"):
            self.make(bindings=[{"source_type":"governed_inference", "source_id":"1", "binding_role":"determination_source"}])

    def test_empty_source_and_role_payload_rolls_back_everything(self):
        with self.assertRaisesRegex(ValueError, "binding_required"):
            self.make(bindings=[])
        self.assertFalse(determination._table_exists(self.conn, "record_governed_determinations"))
        self.assertTrue(self.conn.execute("SELECT 1 FROM record_governed_decision_authorities").fetchone())

    def test_dates_require_qualification_and_respect_mandate_period(self):
        with self.assertRaisesRegex(ValueError, "before_mandate"):
            self.make(decision_date_or_period="2025-12-01")
        with self.assertRaisesRegex(ValueError, "temporal_qualification"):
            self.make(decision_date_or_period="in the relevant period")
        item = self.make(decision_date_or_period="in the relevant period", scope_declaration={"acknowledged":True, "incomplete_dates_qualified":True})
        self.assertEqual(item["decision_date_or_period"], "in the relevant period")

    def test_later_authority_cessation_does_not_invalidate_earlier_determination(self):
        authority_id, mandate_id = self.make_authority()
        authorities.cease_authority_record(
            self.conn, object_type="mandate", object_id=mandate_id,
            cessation_type="expiry_recorded", cessation_date_or_period="2026-12-01",
            rationale="Source records later expiry", cessation_bindings=[{
                "source_type": "canonical_record", "source_id": "REC-1", "binding_role": "cessation_source"
            }], actor="admin", actor_role="administrator", idempotency_key="cessation-1"
        )
        item = self.make(authority_id=authority_id, mandate_id=mandate_id, decision_date_or_period="2026-06-01")
        self.assertEqual(item["status"], "recorded")
        with self.assertRaisesRegex(ValueError, "not_accepted"):
            self.make(authority_id=authority_id, mandate_id=mandate_id, decision_date_or_period="2027-01-01")

    def test_malformed_date_is_not_silently_reinterpreted(self):
        with self.assertRaisesRegex(ValueError, "temporal_qualification"):
            self.make(decision_date_or_period="2026-01-01-not-a-date")

    def test_reasons_boundary_and_declarations(self):
        with self.assertRaisesRegex(ValueError, "no_reasons_declaration"):
            self.make(reasons="", reasons_status="no_reasons_recorded_in_source")
        item = self.make(reasons="", reasons_status="no_reasons_recorded_in_source", authority_mandate_declaration={"acknowledged":True, "no_reasons_acknowledged":True})
        self.assertEqual(item["reasons"], "")
        with self.assertRaisesRegex(ValueError, "representation_declaration"):
            self.make(representation_declaration={"acknowledged":False, "mode":"faithful_paraphrase"})

    def test_creation_idempotency_and_referenced_objects_remain_separate(self):
        first = self.make(idempotency_key="determination-1")
        replay = self.make(idempotency_key="determination-1", authority_id=first["request_payload"]["authority_id"], mandate_id=first["request_payload"]["mandate_id"])
        self.assertEqual(first["id"], replay["id"])
        with self.assertRaisesRegex(ValueError, "idempotency_conflict"):
            self.make(idempotency_key="determination-1", authority_id=first["request_payload"]["authority_id"], mandate_id=first["request_payload"]["mandate_id"], formal_outcome="changed")

    def test_review_is_append_only_and_self_review_is_recorded(self):
        item = self.make()
        reviewed = determination.review_determination(self.conn, determination_id=item["id"], disposition="accepted_as_attributed_determination_record", rationale="Preserve attribution only", boundary_declaration={"acknowledged":True}, actor="admin", actor_role="administrator", idempotency_key="review-1")
        self.assertEqual(reviewed["status"], "accepted_as_attributed_determination_record")
        self.assertEqual(reviewed["reviews"][0]["is_self_review"], 1)

    def test_supersession_and_effect_events_preserve_record_and_effect(self):
        first = self.make(idempotency_key="d1")
        replacement = self.make(idempotency_key="d2")
        determination.supersede_determination(self.conn, determination_id=first["id"], replacement_determination_id=replacement["id"], rationale="More precise source record", actor="admin", actor_role="administrator", idempotency_key="sup-1")
        self.assertEqual(determination.get_determination(self.conn, first["id"])["status"], "superseded")
        event = determination.record_effect_event(self.conn, determination_id=replacement["id"], event_type="appeal_recorded", represented_date_or_period="2026-07-01", rationale="Source records appeal", qualification="Effect is represented only", effect_bindings=self.source("effect_event_source"), actor="admin", actor_role="administrator", idempotency_key="effect-1")
        self.assertEqual(event["effect_events"][0]["event_type"], "appeal_recorded")
        self.assertEqual(event["status"], "recorded")

    def test_read_only_diagnostic_and_admin_language(self):
        with tempfile.NamedTemporaryFile(suffix=".db") as handle:
            diagnostic = determination.read_determination_diagnostic(db_path=handle.name)
            self.assertFalse(diagnostic["determination_table_present"])
            check = sqlite3.connect(handle.name)
            self.assertIsNone(check.execute("SELECT name FROM sqlite_master WHERE name='record_governed_determinations'").fetchone())
            check.close()
        source = Path("api/routes/admin_session.py").read_text(encoding="utf-8")
        for phrase in (
            "DETERMINATION REQUIRES AUTHORITY, MANDATE AND REASONS",
            "Choose determination category",
            "Choose representation mode",
            "Choose reasons status",
            "Choose authority and mandate",
            "Choose binding role",
            'field_name: str = \"determination_bindings_json\"',
            'id=\"stage67-source-payload\"',
            'value=\"\"></section>',
            'for=\"stage67-category\"',
        ):
            self.assertIn(phrase, source)
        self.assertIn("escape(x[\"label\"])", source)
        self.assertNotIn("legally valid", source.lower())

    def test_public_and_legal_effect_boundaries_are_absent(self):
        from pathlib import Path
        source = Path("api/routes/admin_session.py").read_text(encoding="utf-8")
        self.assertIn('"/admin/governed-determinations"', source)
        self.assertNotIn('@router.get("/governed-determinations"', source)
        self.assertNotIn('@router.get("/api/governed-determinations"', source)
        self.assertNotIn("valid", determination.STATUSES)
        self.assertNotIn("lawful", determination.STATUSES)
        self.assertNotIn("overturned", determination.STATUSES)


if __name__ == "__main__":
    unittest.main()
