import sqlite3
import unittest
from pathlib import Path

from api import record_governed_decision_authorities as authorities
from api import record_governed_determinations as determinations


class Stage671DeterminationLinkingTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("CREATE TABLE records (reference TEXT PRIMARY KEY, version TEXT, generated_at TEXT)")
        self.conn.execute("INSERT INTO records VALUES ('REC-1','1','2026-01-01')")

    def tearDown(self):
        self.conn.close()

    def _authority(self):
        item = authorities.create_authority(
            self.conn, holder_kind="office", holder_label="Decision Office", institution_context="CDE",
            office_role_capacity="Administrative decision office", named_holder=None,
            holder_effective_period="2026-01-01", attribution_context="Governance record",
            rationale="Preserve authority representation", qualification="Source-backed representation",
            limitations="May be incomplete", qualification_contract={"epistemic_label":"authority", "source_basis_present":True, "not_conferral":True, "not_appointment_validation":True, "not_jurisdiction":True, "not_lawfulness":True, "not_determination":True, "alternatives_possible":True},
            recorder_declaration={"acknowledged":True}, bindings=[{"source_type":"canonical_record", "source_id":"REC-1", "binding_role":"authority_basis_source"}],
            mandate={"mandate_basis_category":"governance_instrument", "title_label":"Decision mandate", "subject_matter_scope":"records", "procedural_scope":"decision recording", "territorial_organisational_scope":"CDE", "affected_class":"record", "effective_from":"2026-01-01", "effective_to":"2026-12-31", "express_limitations":"No legal validation", "conditions_prerequisites":"Source-backed record", "delegation_status":"not_delegated", "rationale":"Preserve mandate representation", "qualification":"Source-backed representation", "limitations":"May be incomplete"},
            actor="admin", actor_role="administrator")
        authorities.review_authority(self.conn, authority_id=item["id"], mandate_id=None, disposition="accepted_as_source_backed_authority_record", rationale="Retain authority", boundary_declaration={"acknowledged":True}, actor="reviewer", actor_role="administrator")
        authorities.review_authority(self.conn, authority_id=item["id"], mandate_id=item["mandates"][0]["id"], disposition="accepted_as_source_backed_authority_record", rationale="Retain mandate", boundary_declaration={"acknowledged":True}, actor="reviewer", actor_role="administrator")
        return item["id"], item["mandates"][0]["id"]

    def _create(self, **overrides):
        authority_id, mandate_id = self._authority()
        payload = dict(
            determination_category="merits_determination", title_label="Recorded conclusion", formal_outcome="The source records an outcome.", representation_mode="faithful_paraphrase", issues_determined="Issue A", reasons="Reasons as represented.", reasons_status="reasons_recorded", decision_date_or_period="2026-06-01", recorded_date="2026-06-02", affected_subject_or_class="REC-1", finality_description=None, implementation_or_remedy=None, qualification="Source-bound determination record", limitations="Correctness is not established", qualification_contract={"epistemic_label":"determination", "source_basis_present":True, "not_validation":True, "not_jurisdiction":True, "not_lawfulness":True, "not_correctness":True, "not_enforceability":True, "not_finality":True}, authority_id=authority_id, mandate_id=mandate_id, authority_mandate_declaration={"acknowledged":True}, scope_declaration={"acknowledged":True}, representation_declaration={"acknowledged":True, "mode":"faithful_paraphrase"}, recorder_declaration={"acknowledged":True}, linking_declaration={"acknowledged":True}, bindings=[{"source_type":"canonical_record", "source_id":"REC-1", "binding_role":"determination_source"}], governed_objects=[], actor="admin", actor_role="administrator")
        payload.update(overrides)
        return determinations.create_determination(self.conn, **payload)

    def test_linking_declaration_is_required_and_persisted(self):
        with self.assertRaisesRegex(ValueError, "linking_declaration_required"):
            self._create(linking_declaration=None)
        item = self._create()
        self.assertEqual(item["scope_declaration"]["linking_declaration"]["boundary"], "connection_is_not_reliance")

    def test_object_link_is_separate_from_source_binding(self):
        authority_id, mandate_id = self._authority()
        item = self._create(authority_id=authority_id, mandate_id=mandate_id, governed_objects=[{"object_type":"decision_authority", "object_id":authority_id, "relationship_role":"authority_context"}])
        self.assertEqual(item["bindings"][0]["binding_role"], "determination_source")
        self.assertEqual(item["governed_objects"][0]["relationship_role"], "authority_context")

    def test_object_link_unknown_fields_and_duplicates_fail_transactionally(self):
        authority_id, mandate_id = self._authority()
        link = {"object_type":"decision_authority", "object_id":authority_id, "relationship_role":"authority_context"}
        with self.assertRaisesRegex(ValueError, "object_link_invalid"):
            self._create(authority_id=authority_id, mandate_id=mandate_id, governed_objects=[{**link, "inferred":True}])
        with self.assertRaisesRegex(ValueError, "duplicate_object_link"):
            self._create(authority_id=authority_id, mandate_id=mandate_id, governed_objects=[link, link])
        self.assertFalse(determinations._table_exists(self.conn, "record_governed_determinations"))

    def test_neutral_empty_and_separate_admin_controls_are_present(self):
        source = Path("api/routes/admin_session.py").read_text(encoding="utf-8")
        for phrase in (
            "Choose authority and mandate", "Choose a source", "Choose binding role",
            "Choose a governed object", "Choose link role", "No source selected.",
            "No governed object selected.", "connection does not establish reliance",
            'field_name: str = \"determination_bindings_json\"', 'name=\"governed_objects_json\"',
            "linking_acknowledged", "Governed-object links",
        ):
            self.assertIn(phrase, source)
        selector = source.split("def _stage67_source_selector", 1)[1].split("def _stage67_object_candidates", 1)[0]
        self.assertNotIn("textarea", selector)
        self.assertIn("_stage67_object_candidates", source)

    def test_stage67_candidate_reads_are_read_only_when_tables_absent(self):
        with sqlite3.connect(":memory:") as conn:
            self.assertFalse(determinations._table_exists(conn, "record_governed_determinations"))
        self.assertEqual(determinations.read_determination_diagnostic(db_path=Path("/tmp/does-not-exist-stage67.db"))["determinations"], [])


if __name__ == "__main__":
    unittest.main()
