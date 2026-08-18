import sqlite3
import unittest
from pathlib import Path

from api import record_governed_challenges as challenges
from api import record_governed_decision_authorities as authorities
from api import record_governed_determinations as determinations


class Stage68GovernedChallengeTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("CREATE TABLE records (reference TEXT PRIMARY KEY, version TEXT, generated_at TEXT)")
        self.conn.execute("INSERT INTO records VALUES ('REC-68','1','2026-01-01')")
        self.authority_id, self.mandate_id = self._authority("Decision Office")
        self.determination_id = self._determination(self.authority_id, self.mandate_id)["id"]

    def tearDown(self):
        self.conn.close()

    def _authority(self, label):
        item = authorities.create_authority(
            self.conn, holder_kind="office", holder_label=label, institution_context="CDE",
            office_role_capacity="Review office", named_holder=None, holder_effective_period="2026-01-01",
            attribution_context="Governance record", rationale="Preserve authority", qualification="Source-backed",
            limitations="May be incomplete", qualification_contract={"epistemic_label":"authority", "source_basis_present":True, "not_conferral":True, "not_appointment_validation":True, "not_jurisdiction":True, "not_lawfulness":True, "not_determination":True, "alternatives_possible":True},
            recorder_declaration={"acknowledged":True}, bindings=[{"source_type":"canonical_record", "source_id":"REC-68", "binding_role":"authority_basis_source"}],
            mandate={"mandate_basis_category":"governance_instrument", "title_label":"Review mandate", "subject_matter_scope":"challenge records", "procedural_scope":"review recording", "territorial_organisational_scope":"CDE", "affected_class":"determination", "effective_from":"2026-01-01", "effective_to":"2026-12-31", "express_limitations":"No legal validation", "conditions_prerequisites":"Source-backed", "delegation_status":"not_delegated", "rationale":"Preserve mandate", "qualification":"Source-backed", "limitations":"May be incomplete"},
            actor="admin", actor_role="administrator")
        authorities.review_authority(self.conn, authority_id=item["id"], mandate_id=None, disposition="accepted_as_source_backed_authority_record", rationale="Retain", boundary_declaration={"acknowledged":True}, actor="reviewer", actor_role="administrator")
        authorities.review_authority(self.conn, authority_id=item["id"], mandate_id=item["mandates"][0]["id"], disposition="accepted_as_source_backed_authority_record", rationale="Retain", boundary_declaration={"acknowledged":True}, actor="reviewer", actor_role="administrator")
        return item["id"], item["mandates"][0]["id"]

    def _determination(self, authority_id, mandate_id, title="Recorded decision"):
        return determinations.create_determination(
            self.conn, determination_category="merits_determination", title_label=title,
            formal_outcome="Outcome as represented", representation_mode="faithful_paraphrase", issues_determined="Issue",
            reasons="Reasons as represented", reasons_status="reasons_recorded", decision_date_or_period="2026-06-01",
            recorded_date="2026-06-02", affected_subject_or_class="REC-68", finality_description=None,
            implementation_or_remedy=None, qualification="Source-bound determination", limitations="Correctness not established",
            qualification_contract={"epistemic_label":"determination", "source_basis_present":True, "not_validation":True, "not_jurisdiction":True, "not_lawfulness":True, "not_correctness":True, "not_enforceability":True, "not_finality":True},
            authority_id=authority_id, mandate_id=mandate_id, authority_mandate_declaration={"acknowledged":True},
            scope_declaration={"acknowledged":True}, representation_declaration={"acknowledged":True, "mode":"faithful_paraphrase"},
            recorder_declaration={"acknowledged":True}, linking_declaration={"acknowledged":True},
            bindings=[{"source_type":"canonical_record", "source_id":"REC-68", "binding_role":"determination_source"}],
            governed_objects=[], actor="admin", actor_role="administrator")

    def _create(self, **overrides):
        payload = dict(challenge_form="appeal", title_label="Appeal record", target_determination_id=self.determination_id,
            applicant_label="Applicant A", applicant_kind="natural_person", applicant_capacity="Applicant",
            reviewing_forum_label="Review office", reviewing_authority_id=self.authority_id, reviewing_mandate_id=self.mandate_id,
            grounds="Grounds as stated", filing_date_or_period="2026-06-03", recorded_date="2026-06-04",
            affected_subject_or_proceeding="REC-68", procedural_status_at_creation="initiated as recorded",
            rationale="Preserve challenge", limitations="May remain pending or unresolved",
            qualification_contract={"epistemic_label":"challenge_proceeding", "source_basis_present":True, "target_determination_present":True, "not_suspension":True, "not_reversal":True, "not_legal_effect":True},
            recorder_declaration={"acknowledged":True}, bindings=[{"source_type":"canonical_record", "source_id":"REC-68", "binding_role":"initiation_source"}], actor="admin", actor_role="administrator")
        payload.update(overrides)
        return challenges.create_challenge(self.conn, **payload)

    def test_valid_creation_is_source_bound_and_does_not_mutate_target(self):
        before = determinations.get_determination(self.conn, self.determination_id)
        item = self._create()
        after = determinations.get_determination(self.conn, self.determination_id)
        self.assertEqual(item["target_determination"]["determination_id"], self.determination_id)
        self.assertEqual(before, after)
        self.assertEqual(item["status"], "initiated")
        self.assertEqual(item["qualification_contract"]["not_reversal"], True)

    def test_closed_vocabularies_target_and_source_contract(self):
        with self.assertRaisesRegex(ValueError, "challenge_form_invalid"):
            self._create(challenge_form="outcome")
        with self.assertRaisesRegex(ValueError, "applicant_kind_invalid"):
            self._create(applicant_kind="inference")
        with self.assertRaisesRegex(ValueError, "target_determination_not_found"):
            self._create(target_determination_id=999)
        with self.assertRaisesRegex(ValueError, "initiation_source_required"):
            self._create(bindings=[{"source_type":"canonical_record", "source_id":"REC-68", "binding_role":"contextual_source"}])
        with self.assertRaisesRegex(ValueError, "binding_invalid"):
            self._create(bindings=[{"source_type":"governed_inference", "source_id":"1", "binding_role":"initiation_source"}])

    def test_creation_idempotency_and_invalid_multi_binding_rollback(self):
        first = self._create(idempotency_key="challenge-create-1")
        retry = self._create(idempotency_key="challenge-create-1")
        self.assertEqual(first["id"], retry["id"])
        with self.assertRaisesRegex(ValueError, "source_not_found"):
            self._create(bindings=[{"source_type":"canonical_record", "source_id":"REC-68", "binding_role":"initiation_source"}, {"source_type":"canonical_record", "source_id":"MISSING", "binding_role":"grounds_source"}])
        self.assertEqual(len(challenges.list_challenges(self.conn)), 1)

    def test_review_event_and_terminal_resolution_are_append_only(self):
        item = self._create()
        reviewed = challenges.review_challenge(self.conn, challenge_id=item["id"], disposition="accepted_as_governed_challenge_record", rationale="Retain provenance", boundary_declaration={"acknowledged":True}, actor="admin", actor_role="administrator")
        self.assertEqual(reviewed["reviews"][0]["is_self_review"], 1)
        self.assertEqual(reviewed["status"], "accepted_as_governed_challenge_record")
        event = challenges.record_event(self.conn, challenge_id=item["id"], event_type="permission_requested", event_description="Permission requested as recorded", event_date_or_period="2026-06-05", rationale="Preserve event", event_bindings=[{"source_type":"canonical_record", "source_id":"REC-68", "binding_role":"procedural_event_source"}], boundary_declaration={"acknowledged":True}, actor="admin", actor_role="administrator")
        self.assertEqual(event["status"], "permission_pending")
        granted = challenges.record_event(self.conn, challenge_id=item["id"], event_type="permission_granted_as_recorded", event_description="Permission granted as recorded", event_date_or_period="2026-06-06", rationale="Preserve event", event_bindings=[{"source_type":"canonical_record", "source_id":"REC-68", "binding_role":"procedural_event_source"}], boundary_declaration={"acknowledged":True}, actor="admin", actor_role="administrator")
        self.assertEqual(granted["status"], "permission_event_recorded")

    def test_outcome_is_separate_and_does_not_create_effect(self):
        item = self._create()
        with self.assertRaisesRegex(ValueError, "must_be_distinct"):
            challenges.record_outcome(self.conn, challenge_id=item["id"], outcome_type="varied_as_recorded", outcome_text="Outcome as represented", outcome_date_or_period="2026-07-01", outcome_source={"source_type":"canonical_record", "source_id":"REC-68"}, outcome_determination_id=self.determination_id, rationale="Preserve outcome", boundary_declaration={"acknowledged":True}, actor="admin", actor_role="administrator")
        outcome_determination = self._determination(self.authority_id, self.mandate_id, title="Recorded outcome decision")
        outcome = challenges.record_outcome(self.conn, challenge_id=item["id"], outcome_type="varied_as_recorded", outcome_text="Outcome as represented", outcome_date_or_period="2026-07-01", outcome_source={"source_type":"canonical_record", "source_id":"REC-68"}, outcome_determination_id=outcome_determination["id"], rationale="Preserve outcome", boundary_declaration={"acknowledged":True}, actor="admin", actor_role="administrator")
        self.assertEqual(outcome["status"], "outcome_recorded")
        self.assertEqual(len(outcome["outcomes"]), 1)
        self.assertEqual(outcome["outcomes"][0]["outcome_determination_id"], outcome_determination["id"])
        self.assertEqual(len(determinations.get_determination(self.conn, self.determination_id)["effect_events"]), 0)

    def test_supersession_requires_same_target_and_preserves_original(self):
        original = self._create()
        replacement = self._create(title_label="Corrected appeal")
        result = challenges.supersede_challenge(self.conn, challenge_id=original["id"], replacement_challenge_id=replacement["id"], rationale="Correct representation", actor="admin", actor_role="administrator", idempotency_key="challenge-supersession-1")
        self.assertEqual(result["status"], "superseded")
        retry = challenges.supersede_challenge(self.conn, challenge_id=original["id"], replacement_challenge_id=replacement["id"], rationale="Correct representation", actor="admin", actor_role="administrator", idempotency_key="challenge-supersession-1")
        self.assertEqual(retry["status"], "superseded")
        self.assertEqual(challenges.get_challenge(self.conn, replacement["id"])["status"], "initiated")
        self.assertEqual(challenges.get_challenge(self.conn, original["id"])["applicant_label"], "Applicant A")

    def test_admin_surface_has_neutral_source_selection_and_no_public_surface(self):
        source = Path("api/routes/admin_session.py").read_text(encoding="utf-8")
        stage68 = source[source.index("def _stage68_targets"):]
        self.assertIn("/admin/governed-challenges", stage68)
        self.assertIn("Choose challenged determination", stage68)
        self.assertIn("Choose governed source", stage68)
        self.assertIn("Choose binding role", stage68)
        self.assertIn('id="stage68-source-payload" name="bindings_json" value=""', stage68)
        self.assertIn("CHALLENGE IS NOT REVERSAL", stage68)
        self.assertIn("No source selected.", stage68)
        self.assertIn("aria-label", stage68)
        self.assertNotIn("/api/challenges", stage68)

    def test_read_only_diagnostic_does_not_initialize_tables(self):
        path = "/tmp/stage68-nonexistent.db"
        result = challenges.read_challenge_diagnostic(db_path=path)
        self.assertEqual(result["challenges"], [])
        self.assertFalse(challenges._table_exists(self.conn, "record_governed_challenge_proceedings"))


if __name__ == "__main__":
    unittest.main()
