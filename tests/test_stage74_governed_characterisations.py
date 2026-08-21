import json
import sqlite3
import unittest
from pathlib import Path

from api import record_governed_characterisations as characterisations
from tests.test_admin_session import install_fastapi_stubs

install_fastapi_stubs()

from api.routes import admin_session


class Stage74GovernedCharacterisationTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript("""
        CREATE TABLE records (reference TEXT PRIMARY KEY, title TEXT, status TEXT);
        INSERT INTO records VALUES ('REC-74', 'Governed record', 'recorded');
        CREATE TABLE record_governed_allegations (id INTEGER PRIMARY KEY, title TEXT, status TEXT);
        INSERT INTO record_governed_allegations VALUES (7, 'Attributed allegation', 'recorded');
        """)

    def tearDown(self):
        self.conn.close()

    def create(self, **overrides):
        values = dict(
            term_code="institutional_silence", vocabulary_version="1.0",
            representation_mode="verbatim", represented_wording="The source used the term institutional silence.",
            attribution_kind="identified_person", attributed_label="Represented speaker",
            attribution_source_type=None, attribution_source_id=None,
            external_source_description=None, epistemic_basis="attributed_source_language",
            rationale="Preserve the represented language.", limitations="Absence proves nothing absent.",
            jurisdictional_context=None, primary_object_kind="canonical_record", primary_object_id="REC-74",
            bindings=[], references=[], actor="creator", actor_role="administrator",
            declaration={"acknowledged": True}, idempotency_key="stage74-create-1",
        )
        values.update(overrides)
        return characterisations.create_characterisation(self.conn, **values)

    def test_closed_versioned_vocabulary_and_qualifications(self):
        self.assertEqual(set(characterisations.TERMS), {
            "victimisation", "retaliation", "harassment", "intimidation", "coercion",
            "control", "procedural_obstruction", "reframing", "institutional_silence",
            "repeated_contact_without_resolution",
        })
        self.assertEqual(characterisations.VOCABULARY_VERSION, "1.0")
        with self.assertRaisesRegex(ValueError, "term_version_invalid"):
            characterisations.vocabulary("institutional_silence", "9.0")
        self.assertIn("Absence", characterisations.vocabulary("institutional_silence")["exclusion_or_limitation_guidance"])
        self.assertIn("intent", characterisations.vocabulary("reframing")["exclusion_or_limitation_guidance"])
        self.assertIn("corroboration", characterisations.vocabulary("repeated_contact_without_resolution")["exclusion_or_limitation_guidance"])
        self.assertIn("legitimate", characterisations.vocabulary("control")["inclusion_guidance"])
        metadata = characterisations.vocabulary_metadata()
        metadata[0]["display_label"] = "tampered"
        self.assertNotEqual(characterisations.vocabulary_metadata()[0]["display_label"], "tampered")

    def test_creation_is_deliberate_distinct_from_attribution_and_finding(self):
        item = self.create()
        self.assertEqual(item["lifecycle_status"], "recorded_as_represented")
        self.assertEqual(item["created_by"], "creator")
        self.assertEqual(item["attributed_label"], "Represented speaker")
        self.assertNotIn("finding", item)
        with self.assertRaisesRegex(ValueError, "wording_required"):
            self.create(represented_wording="", idempotency_key="stage74-empty")
        with self.assertRaisesRegex(ValueError, "creation_declaration_required"):
            self.create(declaration={"acknowledged": False}, idempotency_key="stage74-declaration")

    def test_conditional_attribution_and_primary_object_validation(self):
        with self.assertRaisesRegex(ValueError, "attributed_label_required"):
            self.create(attribution_kind="identified_person", attributed_label="", idempotency_key="stage74-person")
        with self.assertRaisesRegex(ValueError, "external_source_required"):
            self.create(attribution_kind="external_source_as_represented", idempotency_key="stage74-external")
        with self.assertRaisesRegex(ValueError, "primary_object_not_found"):
            self.create(primary_object_id="MISSING", idempotency_key="stage74-object")
        with self.assertRaisesRegex(ValueError, "term_version_invalid"):
            self.create(term_code="unknown", idempotency_key="stage74-term")
        with self.assertRaisesRegex(ValueError, "fields_not_applicable"):
            self.create(attribution_kind="identified_person", attribution_source_type="canonical_record", attribution_source_id="REC-74", idempotency_key="stage74-mixed-attribution")
        with self.assertRaisesRegex(ValueError, "attribution_source_not_found"):
            self.create(attribution_kind="governed_source", attribution_source_type="canonical_record", attribution_source_id="MISSING", attributed_label=None, idempotency_key="stage74-source-attribution")

    def test_bindings_references_and_idempotency_are_strict(self):
        item = self.create(
            bindings=[{"source_type": "canonical_record", "source_id": "REC-74", "binding_role": "supporting_source"}],
            references=[{"object_kind": "governed_allegation", "object_id": "7", "relationship_role": "contextual_object"}],
        )
        retry = self.create(
            bindings=[{"source_type": "canonical_record", "source_id": "REC-74", "binding_role": "supporting_source"}],
            references=[{"object_kind": "governed_allegation", "object_id": "7", "relationship_role": "contextual_object"}],
        )
        self.assertEqual(item["id"], retry["id"])
        with self.assertRaisesRegex(ValueError, "idempotency_conflict"):
            self.create(represented_wording="different", bindings=[], references=[])
        with self.assertRaisesRegex(ValueError, "duplicate_binding"):
            self.create(idempotency_key="stage74-duplicate", bindings=[
                {"source_type": "canonical_record", "source_id": "REC-74", "binding_role": "supporting_source"},
                {"source_type": "canonical_record", "source_id": "REC-74", "binding_role": "supporting_source"},
            ])
        with self.assertRaisesRegex(ValueError, "source_not_found"):
            self.create(idempotency_key="stage74-unknown-source", bindings=[{"source_type": "canonical_record", "source_id": "MISSING", "binding_role": "supporting_source"}])
        with self.assertRaisesRegex(ValueError, "reference_invalid"):
            self.create(idempotency_key="stage74-invalid-reference-role", references=[{"object_kind": "governed_allegation", "object_id": "7", "relationship_role": "separately_governed_determination"}])

    def test_append_only_lifecycle_and_actor_separation(self):
        item = self.create()
        proposed = characterisations.propose_characterisation(self.conn, identifier=item["id"], rationale="Propose the represented term for review.", declaration={"acknowledged": True}, actor="creator", actor_role="administrator", idempotency_key="stage74-propose")
        self.assertEqual(proposed["lifecycle_status"], "proposed_as_characterisation")
        disputed = characterisations.dispute_characterisation(self.conn, identifier=item["id"], rationale="The use is disputed.", declaration={"acknowledged": True}, actor="other", actor_role="administrator", idempotency_key="stage74-dispute")
        self.assertEqual(disputed["lifecycle_status"], "disputed")
        with self.assertRaisesRegex(ValueError, "reviewer_must_differ"):
            characterisations.review_characterisation(self.conn, identifier=item["id"], outcome="reviewed_as_qualified_representation", rationale="Review.", declaration={"acknowledged": True}, actor="creator", actor_role="administrator", idempotency_key="stage74-review-self")
        reviewed = characterisations.review_characterisation(self.conn, identifier=item["id"], outcome="reviewed_as_qualified_representation", rationale="Retained only as a qualified representation.", declaration={"acknowledged": True}, actor="reviewer", actor_role="administrator", idempotency_key="stage74-review")
        self.assertEqual(reviewed["lifecycle_status"], "reviewed_as_qualified_representation")
        self.assertEqual(len(reviewed["history"]), 4)
        replay = characterisations.propose_characterisation(self.conn, identifier=item["id"], rationale="Propose the represented term for review.", declaration={"acknowledged": True}, actor="creator", actor_role="administrator", idempotency_key="stage74-propose")
        self.assertEqual(replay["id"], item["id"])
        with self.assertRaisesRegex(ValueError, "idempotency_conflict"):
            characterisations.propose_characterisation(self.conn, identifier=item["id"], rationale="Different actor reuse.", declaration={"acknowledged": True}, actor="other", actor_role="administrator", idempotency_key="stage74-propose")

    def test_later_dispute_preserves_each_prior_review_outcome(self):
        for index, outcome in enumerate(characterisations.REVIEW_OUTCOMES):
            item = self.create(idempotency_key=f"stage74-later-dispute-{index}")
            characterisations.propose_characterisation(
                self.conn, identifier=item["id"], rationale="Propose for review.",
                declaration={"acknowledged": True}, actor="creator",
                actor_role="administrator", idempotency_key=f"stage74-later-propose-{index}",
            )
            characterisations.review_characterisation(
                self.conn, identifier=item["id"], outcome=outcome,
                rationale=f"Review outcome: {outcome}.", declaration={"acknowledged": True},
                actor="reviewer", actor_role="administrator",
                idempotency_key=f"stage74-later-review-{index}",
            )
            disputed = characterisations.dispute_characterisation(
                self.conn, identifier=item["id"], rationale="Later contrary representation.",
                declaration={"acknowledged": True}, actor="challenger",
                actor_role="administrator", idempotency_key=f"stage74-later-dispute-event-{index}",
            )
            self.assertEqual(disputed["lifecycle_status"], "disputed")
            history = disputed["history"]
            review = next(event for event in history if event["event_type"] == "review")
            dispute = next(event for event in history if event["event_type"] == "disputed")
            self.assertEqual(review["resulting_status"], outcome)
            self.assertEqual(review["actor"], "reviewer")
            self.assertEqual(review["rationale"], f"Review outcome: {outcome}.")
            self.assertEqual(dispute["actor"], "challenger")
            self.assertEqual(dispute["rationale"], "Later contrary representation.")
            replay = characterisations.dispute_characterisation(
                self.conn, identifier=item["id"], rationale="Later contrary representation.",
                declaration={"acknowledged": True}, actor="challenger",
                actor_role="administrator", idempotency_key=f"stage74-later-dispute-event-{index}",
            )
            self.assertEqual(len(replay["history"]), len(history))
            with self.assertRaisesRegex(ValueError, "idempotency_conflict"):
                characterisations.dispute_characterisation(
                    self.conn, identifier=item["id"], rationale="Changed dispute.",
                    declaration={"acknowledged": True}, actor="challenger",
                    actor_role="administrator", idempotency_key=f"stage74-later-dispute-event-{index}",
                )

    def test_withdrawal_and_supersession_preserve_history(self):
        first = self.create()
        replacement = self.create(idempotency_key="stage74-replacement", represented_wording="A corrected represented wording.")
        superseded = characterisations.supersede_characterisation(self.conn, identifier=first["id"], replacement_id=replacement["id"], rationale="Preserve a corrected representation.", declaration={"acknowledged": True}, actor="reviewer", actor_role="administrator", idempotency_key="stage74-supersede")
        self.assertEqual(superseded["lifecycle_status"], "superseded")
        self.assertEqual(characterisations.get_characterisation(self.conn, first["id"])["represented_wording"], "The source used the term institutional silence.")
        with self.assertRaisesRegex(ValueError, "self_supersession"):
            characterisations.supersede_characterisation(self.conn, identifier=replacement["id"], replacement_id=replacement["id"], rationale="Cycle.", declaration={"acknowledged": True}, actor="reviewer", actor_role="administrator", idempotency_key="stage74-self")
        withdrawn = characterisations.withdraw_characterisation(self.conn, identifier=replacement["id"], rationale="Withdraw the representation.", declaration={"acknowledged": True}, actor="reviewer", actor_role="administrator", idempotency_key="stage74-withdraw")
        self.assertEqual(withdrawn["lifecycle_status"], "withdrawn")
        self.assertEqual(len(withdrawn["history"]), 2)
        replay = characterisations.withdraw_characterisation(self.conn, identifier=replacement["id"], rationale="Withdraw the representation.", declaration={"acknowledged": True}, actor="reviewer", actor_role="administrator", idempotency_key="stage74-withdraw")
        self.assertEqual(replay["lifecycle_status"], "withdrawn")

    def test_creation_rolls_back_when_event_persistence_fails(self):
        characterisations.ensure_characterisation_tables(self.conn)
        self.conn.execute("CREATE TRIGGER stage74_fail_event BEFORE INSERT ON record_governed_characterisation_events BEGIN SELECT RAISE(ABORT, 'forced event failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.create(idempotency_key="stage74-rollback")
        self.assertIsNone(self.conn.execute("SELECT 1 FROM record_governed_characterisations WHERE idempotency_key='stage74-rollback'").fetchone())

    def test_diagnostic_does_not_initialize_persistence(self):
        empty = sqlite3.connect(":memory:")
        empty.row_factory = sqlite3.Row
        diagnostic = characterisations.read_diagnostic(empty)
        self.assertFalse(diagnostic["characterisation_table_present"])
        self.assertEqual(diagnostic["count"], 0)
        self.assertFalse(empty.execute("SELECT 1 FROM sqlite_master WHERE name='record_governed_characterisations'").fetchone())
        empty.close()

    def test_admin_surface_is_authenticated_bounded_and_deliberately_empty(self):
        html = admin_session._stage74_html(admin_session={"username": "admin"}, items=[], candidates=[])
        self.assertIn("A TERM NAMES THE QUESTION", html)
        self.assertIn("Choose terminology", html)
        self.assertIn("Choose attribution kind", html)
        self.assertIn("Choose epistemic basis", html)
        self.assertIn("Choose primary governed object", html)
        self.assertIn("governed-declaration-control", html)
        self.assertIn("/admin/governed-characterisations", html)
        self.assertNotIn('option value="victimisation" selected', html)
        self.assertNotIn('option value="identified_person" selected', html)
        self.assertNotIn('option value="proposed_human_characterisation" selected', html)
        self.assertNotIn("/determinations", html)

    def test_admin_selection_controls_replace_raw_json_editors(self):
        html = admin_session._stage74_html(
            admin_session={"username": "admin"},
            items=[],
            candidates=[{"object_kind": "governed_allegation", "object_id": "7", "label": "Allegation 7", "status": "recorded"}],
            source_candidates=[{"source_type": "canonical_record", "source_id": "REC-<7>", "label": "Record <7>", "status": "Current"}],
            related_candidates=[{"object_kind": "governed_allegation", "object_id": "7", "label": "Allegation 7", "status": "recorded"}],
        )
        self.assertNotIn("Supporting source bindings JSON", html)
        self.assertNotIn("Related object references JSON", html)
        self.assertNotIn('<textarea id="stage74-bindings"', html)
        self.assertNotIn('<textarea id="stage74-references"', html)
        self.assertIn('id="stage74-source-candidate"', html)
        self.assertIn('id="stage74-source-role"', html)
        self.assertIn('id="stage74-source-add"', html)
        self.assertIn('id="stage74-selected-sources"', html)
        self.assertIn("No supporting source selected.", html)
        self.assertIn('id="stage74-related-candidate"', html)
        self.assertIn('id="stage74-related-role"', html)
        self.assertIn('id="stage74-related-add"', html)
        self.assertIn('id="stage74-selected-related"', html)
        self.assertIn("No related governed object selected.", html)
        self.assertIn("Record &lt;7&gt;", html)
        self.assertIn('aria-live="polite"', html)
        self.assertNotIn('value="victimisation" selected', html)

    def test_selection_controls_preserve_distinct_internal_payload_names(self):
        html = admin_session._stage74_html(admin_session={"username": "admin"}, items=[], candidates=[])
        self.assertIn('name="bindings_json"', html)
        self.assertIn('name="references_json"', html)
        self.assertIn('name="binding_source"', html)
        self.assertIn('name="binding_role"', html)
        self.assertIn('name="reference_object"', html)
        self.assertIn('name="reference_role"', html)
        self.assertIn("source.removeAttribute(\"name\")", html)
        self.assertIn("related.removeAttribute(\"name\")", html)
        self.assertIn("stage74-primary-changed", html)
        self.assertIn("sources.length=0", html)
        self.assertIn("relatedItems.length=0", html)

    def test_visible_hidden_selection_conflicts_fail_closed(self):
        with self.assertRaises(ValueError):
            admin_session._stage74_submission_lists(
                bindings_json='[{"source_type":"canonical_record","source_id":"A","binding_role":"supporting_source"}]',
                references_json="", binding_source="canonical_record::B", binding_role=None,
                reference_object=None, reference_role=None,
            )
        with self.assertRaises(ValueError):
            admin_session._stage74_submission_lists(
                bindings_json='[{"source_type":"canonical_record","source_id":"A","binding_role":"supporting_source"}]',
                references_json="", binding_source=None, binding_role="contrary_source",
                reference_object=None, reference_role=None,
            )
        with self.assertRaises(ValueError):
            admin_session._stage74_submission_lists(
                bindings_json="", references_json='[{"object_kind":"governed_allegation","object_id":"7","relationship_role":"contextual_object"}]',
                binding_source=None, binding_role=None, reference_object="governed_allegation::8", reference_role=None,
            )

    def test_javascript_independent_selection_payloads_are_structured(self):
        bindings, references = admin_session._stage74_submission_lists(
            bindings_json="", references_json="", binding_source="canonical_record::A", binding_role="supporting_source",
            reference_object="governed_allegation::7", reference_role="contextual_object",
        )
        self.assertEqual(bindings, [{"source_type": "canonical_record", "source_id": "A", "binding_role": "supporting_source"}])
        self.assertEqual(references, [{"object_kind": "governed_allegation", "object_id": "7", "relationship_role": "contextual_object"}])

    def test_detail_surface_exposes_only_append_only_neutral_actions(self):
        item = self.create()
        html = admin_session._stage74_html(admin_session={"username": "admin"}, items=[item], candidates=[], detail=item)
        self.assertIn("Propose characterisation", html)
        self.assertIn("Supersede representation", html)
        self.assertIn("does not convert the term into a finding", html)
        self.assertEqual(html.count('id="stage74-event-declaration"'), 1)
        self.assertNotIn("determined characterisation", html.lower())

    def test_stage74_navigation_is_one_authenticated_admin_section(self):
        html = admin_session._render_admin_console_navigation(
            admin_session={"username": "admin"},
            current_path="/admin/governed-characterisations/12/review",
        )
        self.assertEqual(html.count('aria-current="page"'), 1)
        self.assertIn('aria-current="page" href="/admin/governed-characterisations">Governed Terminology</a>', html)
        self.assertIn("#A65F2A", html)
        self.assertNotIn(":visited", html)

    def test_stage74_has_no_public_route_or_public_navigation(self):
        from api.public_navigation import public_primary_navigation

        source = Path("api/routes/admin_session.py").read_text(encoding="utf-8")
        self.assertNotIn('@router.get("/governed-characterisations"', source)
        self.assertNotIn('@router.get("/determinations"', source)
        self.assertNotIn("Governed Terminology", public_primary_navigation(active="archive"))


if __name__ == "__main__":
    unittest.main()
