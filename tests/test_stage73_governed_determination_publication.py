import sqlite3
import re
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from api import record_governed_determination_publications as publications


class Stage73PublicationTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        publications.ensure_publication_tables(self.conn)
        self.determination = {"id": 7, "status": "accepted_as_attributed_determination_record", "authority_mandate": {"authority_id": 11, "mandate_id": 12}}
        self.create = dict(
            determination_id=7,
            representation_mode="approved_summary",
            public_title="A represented determination",
            public_representation="The approved public representation.",
            authority_representation="Authority as represented.",
            mandate_representation="Mandate as represented.",
            reasons_status="reasons_abridged_or_redacted",
            challenge_warning_status="no_linked_challenge_shown_in_snapshot",
            challenge_warning_text="No linked challenge is represented in this publication snapshot.",
            current_effect_status="effect_uncertain",
            current_effect_rationale="Current effect is represented as uncertain.",
            effect_as_of="2026-08-20",
            supersession_representation="No supersession is represented in this snapshot.",
            limitations="This representation is limited and does not establish correctness.",
            redaction_notice="Some material was redacted.",
            actor="reviewer",
            actor_role="administrator",
            idempotency_key="publication-7",
        )

    def tearDown(self):
        self.conn.close()

    def _create(self, *, key=None, title=None):
        with patch.object(publications.determinations, "get_determination", return_value=self.determination):
            payload = dict(self.create)
            if key is not None:
                payload["idempotency_key"] = "publication-" + key
            if title is not None:
                payload["public_title"] = title
            return publications.create_publication(self.conn, **payload)

    def _ready_for_approval(self, *, key="7"):
        item = self._create(key=key)
        common = {"publication_id": item["id"], "supporting_sources": [], "reviewer_role": "administrator"}
        item = publications.review_eligibility(self.conn, **common, status="eligible_for_review", rationale="Eligibility is represented for review only.", representation={"acknowledged": True, "human_recorded": True, "boundary": "eligibility_is_not_approval"}, reviewer="eligibility-" + key, idempotency_key="eligibility-" + key)
        item = publications.review_privacy(self.conn, **common, status="cleared_for_publication", rationale="Privacy review recorded.", representation={"acknowledged": True, "human_recorded": True, "boundary": "privacy_is_not_clearance_of_all_risk"}, reviewer="privacy-" + key, idempotency_key="privacy-" + key)
        item = publications.review_redaction(self.conn, **common, status="cleared_for_publication", rationale="Redaction review recorded.", representation={"acknowledged": True, "human_recorded": True, "boundary": "redaction_is_not_completeness"}, reviewer="redaction-" + key, idempotency_key="redaction-" + key)
        item = publications.inspect_authority(self.conn, **common, status="recorded_with_qualification", rationale="Authority inspected as represented.", representation={"acknowledged": True, "human_recorded": True, "boundary": "authority_is_not_legally_validated", "representation": "Authority remains as represented."}, reviewer="authority-" + key, idempotency_key="authority-" + key)
        item = publications.inspect_mandate(self.conn, **common, status="recorded_with_qualification", rationale="Mandate inspected as represented.", representation={"acknowledged": True, "human_recorded": True, "boundary": "mandate_is_not_legally_validated", "representation": "Mandate remains as represented."}, reviewer="mandate-" + key, idempotency_key="mandate-" + key)
        item = publications.record_publication_context(self.conn, **common, status="recorded", rationale="Publication context recorded.", representation={"acknowledged": True, "human_recorded": True, "boundary": "publication_context_is_not_legal_effect", "reasons_status": self.create["reasons_status"], "challenge_warning_status": self.create["challenge_warning_status"], "challenge_warning_text": self.create["challenge_warning_text"], "current_effect_status": self.create["current_effect_status"], "current_effect_rationale": self.create["current_effect_rationale"], "effect_as_of": self.create["effect_as_of"], "supersession_representation": self.create["supersession_representation"], "limitations": self.create["limitations"]}, reviewer="context-" + key, idempotency_key="context-" + key)
        return item

    def test_publication_is_separate_and_not_public_by_default(self):
        item = self._create()
        self.assertEqual(item["lifecycle_status"], "draft")
        self.assertEqual(item["eligibility_status"], "not_assessed")
        self.assertEqual(item["privacy_status"], "not_reviewed")
        self.assertEqual(item["redaction_status"], "not_reviewed")
        self.assertTrue(item["content_digest_valid"])
        with self.assertRaises(ValueError):
            publications.public_publication(self.conn, item["id"])
        conflicting = dict(self.create, public_title="A different representation")
        with patch.object(publications.determinations, "get_determination", return_value=self.determination):
            with self.assertRaisesRegex(ValueError, "idempotency_conflict"):
                publications.create_publication(self.conn, **conflicting)

    def test_reviews_are_explicit_and_publication_is_idempotent(self):
        item = self._create()
        self.assertEqual(self._create()["id"], item["id"])
        with patch.object(publications.determinations, "get_determination", return_value=self.determination):
            item = publications.review_eligibility(self.conn, publication_id=item["id"], status="eligible_for_review", rationale="Eligibility is represented for review only.", representation={"acknowledged": True, "human_recorded": True, "boundary": "eligibility_is_not_approval"}, supporting_sources=[], reviewer="eligibility-reviewer", reviewer_role="administrator", idempotency_key="eligibility-7")
        item = publications.review_privacy(self.conn, publication_id=item["id"], status="cleared_for_publication", rationale="Privacy review recorded.", representation={"acknowledged": True, "human_recorded": True, "boundary": "privacy_is_not_clearance_of_all_risk"}, supporting_sources=[], reviewer="privacy-reviewer", reviewer_role="administrator", idempotency_key="privacy-7")
        item = publications.review_redaction(self.conn, publication_id=item["id"], status="cleared_for_publication", rationale="Redaction review recorded.", representation={"acknowledged": True, "human_recorded": True, "boundary": "redaction_is_not_completeness"}, supporting_sources=[], reviewer="redaction-reviewer", reviewer_role="administrator", idempotency_key="redaction-7")
        item = publications.inspect_authority(self.conn, publication_id=item["id"], status="recorded_with_qualification", rationale="Authority inspected as represented.", representation={"acknowledged": True, "human_recorded": True, "boundary": "authority_is_not_legally_validated", "representation": "Authority remains as represented."}, supporting_sources=[], reviewer="authority-reviewer", reviewer_role="administrator", idempotency_key="authority-7")
        item = publications.inspect_mandate(self.conn, publication_id=item["id"], status="recorded_with_qualification", rationale="Mandate inspected as represented.", representation={"acknowledged": True, "human_recorded": True, "boundary": "mandate_is_not_legally_validated", "representation": "Mandate remains as represented."}, supporting_sources=[], reviewer="mandate-reviewer", reviewer_role="administrator", idempotency_key="mandate-7")
        item = publications.record_publication_context(self.conn, publication_id=item["id"], status="recorded", rationale="Publication context recorded.", representation={"acknowledged": True, "human_recorded": True, "boundary": "publication_context_is_not_legal_effect", "reasons_status": "reasons_abridged_or_redacted", "challenge_warning_status": "no_linked_challenge_shown_in_snapshot", "challenge_warning_text": self.create["challenge_warning_text"], "current_effect_status": "effect_uncertain", "current_effect_rationale": self.create["current_effect_rationale"], "effect_as_of": self.create["effect_as_of"], "supersession_representation": self.create["supersession_representation"], "limitations": self.create["limitations"]}, supporting_sources=[], reviewer="context-reviewer", reviewer_role="administrator", idempotency_key="context-7")
        item = publications.approve_publication(self.conn, publication_id=item["id"], rationale="Approval is a separate human action.", actor="approver", actor_role="administrator", idempotency_key="approve-7")
        self.assertEqual(item["lifecycle_status"], "approved_for_publication")
        item = publications.publish_publication(self.conn, publication_id=item["id"], rationale="Publication is explicit.", actor="publisher", actor_role="administrator", idempotency_key="publish-7")
        self.assertEqual(item["lifecycle_status"], "published")
        self.assertEqual(publications.public_publication(self.conn, item["id"])["content_digest"], item["content_digest"])
        with self.assertRaises(ValueError):
            publications.publish_publication(self.conn, publication_id=item["id"], rationale="different", actor="publisher", actor_role="administrator", idempotency_key="publish-7")

    def test_diagnostic_is_read_only_when_table_is_absent(self):
        with tempfile.NamedTemporaryFile() as handle:
            result = publications.read_publication_diagnostic(db_path=handle.name)
        self.assertFalse(result["publication_table_present"])

    def test_publication_gates_and_review_declarations_are_independent(self):
        item = self._create()
        with self.assertRaisesRegex(ValueError, "eligibility_required"):
            publications.approve_publication(self.conn, publication_id=item["id"], rationale="x", actor="approver", actor_role="administrator", idempotency_key="approve-gate")
        with self.assertRaisesRegex(ValueError, "declaration_required"):
            publications.review_eligibility(self.conn, publication_id=item["id"], status="eligible_for_review", rationale="x", representation={}, supporting_sources=[], reviewer="r", reviewer_role="administrator", idempotency_key="bad-declaration")
        item = publications.review_eligibility(self.conn, publication_id=item["id"], status="not_eligible", rationale="Not eligible.", representation={"acknowledged": True, "human_recorded": True, "boundary": "eligibility_is_not_approval"}, supporting_sources=[], reviewer="r", reviewer_role="administrator", idempotency_key="not-eligible")
        self.assertEqual(item["events"][-1]["lifecycle_status"], "draft")
        with self.assertRaisesRegex(ValueError, "eligibility_required"):
            publications.approve_publication(self.conn, publication_id=item["id"], rationale="x", actor="approver", actor_role="administrator", idempotency_key="approve-gate-2")

    def test_sensitive_canary_and_digest_mismatch_fail_closed(self):
        item = self._ready_for_approval(key="canary")
        item = publications.approve_publication(self.conn, publication_id=item["id"], rationale="Approval is separate.", actor="approver-canary", actor_role="administrator", idempotency_key="approve-canary")
        item = publications.publish_publication(self.conn, publication_id=item["id"], rationale="Explicit publication.", actor="publisher-canary", actor_role="administrator", idempotency_key="publish-canary")
        public = publications.public_publication(self.conn, item["id"])
        self.assertNotIn("PRIVATE-HEALTH-CANARY", str(public))
        for forbidden in ("reviewer", "publisher", "created_by", "idempotency_key", "request_payload_json", "reviews", "events"):
            self.assertNotIn(forbidden, public)
        self.conn.execute("UPDATE record_governed_determination_publications SET public_representation='PRIVATE-HEALTH-CANARY' WHERE id=?", (item["id"],))
        self.conn.commit()
        with self.assertRaisesRegex(ValueError, "digest_mismatch"):
            publications.public_publication(self.conn, item["id"])
        self.assertEqual(publications.list_publications(self.conn, public_only=True), [])

    def test_withdrawal_preserves_history_and_removes_current_public_visibility(self):
        item = self._ready_for_approval(key="withdraw")
        item = publications.approve_publication(self.conn, publication_id=item["id"], rationale="Approval.", actor="approver-withdraw", actor_role="administrator", idempotency_key="approve-withdraw")
        item = publications.publish_publication(self.conn, publication_id=item["id"], rationale="Publish.", actor="publisher-withdraw", actor_role="administrator", idempotency_key="publish-withdraw")
        digest = item["content_digest"]
        item = publications.withdraw_publication(self.conn, publication_id=item["id"], rationale="Withdraw from current public view.", actor="withdrawer", actor_role="administrator", idempotency_key="withdraw-1")
        self.assertEqual(item["lifecycle_status"], "withdrawn_from_publication")
        self.assertEqual(item["content_digest"], digest)
        self.assertEqual(publications.list_publications(self.conn, public_only=True), [])
        with self.assertRaisesRegex(ValueError, "not_public"):
            publications.public_publication(self.conn, item["id"])

    def test_actor_separation_and_context_gate_are_enforced(self):
        item = self._ready_for_approval(key="actors")
        with self.assertRaisesRegex(ValueError, "approver_must_be_separate"):
            publications.approve_publication(self.conn, publication_id=item["id"], rationale="Approval.", actor="eligibility-actors", actor_role="administrator", idempotency_key="approve-same")
        item = publications.approve_publication(self.conn, publication_id=item["id"], rationale="Approval.", actor="approver-actors", actor_role="administrator", idempotency_key="approve-actors")
        with self.assertRaisesRegex(ValueError, "publisher_must_be_separate"):
            publications.publish_publication(self.conn, publication_id=item["id"], rationale="Publish.", actor="approver-actors", actor_role="administrator", idempotency_key="publish-same")

    def test_authority_and_mandate_identity_is_retained_separately(self):
        item = self._create()
        self.assertEqual(item["authority_id"], 11)
        self.assertEqual(item["mandate_id"], 12)

    def test_invalid_determination_and_review_payloads_fail_closed(self):
        with patch.object(publications.determinations, "get_determination", return_value={"id": 7, "status": "not_accepted_as_attributed"}):
            with self.assertRaisesRegex(ValueError, "not_eligible"):
                publications.create_publication(self.conn, **self.create)
        with patch.object(publications.determinations, "get_determination", return_value={"id": 7, "status": "accepted_as_attributed_determination_record"}):
            with self.assertRaisesRegex(ValueError, "authority_mandate_missing"):
                publications.create_publication(self.conn, **self.create)
        item = self._create(key="invalid-review")
        with self.assertRaisesRegex(ValueError, "supporting_source_invalid"):
            publications.review_eligibility(self.conn, publication_id=item["id"], status="eligible_for_review", rationale="x", representation={"acknowledged": True}, supporting_sources=[{"private_field": "x"}], reviewer="reviewer", reviewer_role="administrator", idempotency_key="invalid-source")

    def test_supersession_requires_published_replacement_and_preserves_history(self):
        original = self._ready_for_approval(key="sup-original")
        original = publications.approve_publication(self.conn, publication_id=original["id"], rationale="Approval.", actor="approver-sup-original", actor_role="administrator", idempotency_key="approve-sup-original")
        original = publications.publish_publication(self.conn, publication_id=original["id"], rationale="Publish.", actor="publisher-sup-original", actor_role="administrator", idempotency_key="publish-sup-original")
        replacement = self._ready_for_approval(key="sup-replacement")
        with self.assertRaisesRegex(ValueError, "requires_published"):
            publications.supersede_publication(self.conn, publication_id=original["id"], replacement_publication_id=replacement["id"], rationale="Replacement is not public yet.", actor="superseder", actor_role="administrator", idempotency_key="sup-before-publish")
        replacement = publications.approve_publication(self.conn, publication_id=replacement["id"], rationale="Approval.", actor="approver-sup-replacement", actor_role="administrator", idempotency_key="approve-sup-replacement")
        replacement = publications.publish_publication(self.conn, publication_id=replacement["id"], rationale="Publish.", actor="publisher-sup-replacement", actor_role="administrator", idempotency_key="publish-sup-replacement")
        original = publications.supersede_publication(self.conn, publication_id=original["id"], replacement_publication_id=replacement["id"], rationale="Corrected publication replaces the historical version.", actor="superseder", actor_role="administrator", idempotency_key="supersede-1")
        self.assertEqual(original["lifecycle_status"], "superseded")
        self.assertTrue(original["supersessions"])
        self.assertEqual(publications.list_publications(self.conn, public_only=True)[0]["id"], replacement["id"])
        with self.assertRaisesRegex(ValueError, "self_supersession"):
            publications.supersede_publication(self.conn, publication_id=replacement["id"], replacement_publication_id=replacement["id"], rationale="Cycle.", actor="superseder", actor_role="administrator", idempotency_key="supersede-self")

    def test_public_boundary_contains_only_published_records(self):
        from api.routes import governed_determination_publications as public_routes
        with tempfile.NamedTemporaryFile() as handle, patch.object(public_routes, "DB_PATH", Path(handle.name)):
            response = public_routes.published_determinations()
            raw_content = getattr(response, "body", getattr(response, "content", ""))
            content = raw_content.decode() if isinstance(raw_content, bytes) else raw_content
            self.assertIn("No determination is public by default", content)
            with self.assertRaisesRegex(Exception, "published_determination_not_found"):
                public_routes.published_determination(999)

    def test_initial_admin_form_has_neutral_stage73_selections(self):
        from api.routes import admin_session

        html = admin_session._stage73_form(session={"username": "admin", "role": "admin"}, publications=[], candidates=[])
        expected = {
            "representation_mode": "Choose representation mode",
            "reasons_status": "Choose reasons status",
            "challenge_warning_status": "Choose challenge warning status",
            "current_effect_status": "Choose current-effect status",
        }
        for name, placeholder in expected.items():
            match = re.search(rf'<select[^>]*name="{name}"[^>]*>(.*?)</select>', html, re.DOTALL)
            self.assertIsNotNone(match, name)
            body = match.group(1)
            self.assertIn(f'<option value="" selected disabled>{placeholder}</option>', body)
            self.assertNotRegex(body, r'<option value="(?!")([^"]+)"[^>]*selected')
        self.assertNotIn("No linked challenge is represented in this publication snapshot.</textarea>", html)
        self.assertIn('name="challenge_warning_text" required data-stage73-challenge-text></textarea>', html)

    def test_contradictory_challenge_warning_is_rejected_server_side(self):
        payload = dict(self.create, challenge_warning_status="challenge_determined")
        with patch.object(publications.determinations, "get_determination", return_value=self.determination):
            with self.assertRaisesRegex(ValueError, "challenge_warning_text_incompatible"):
                publications.create_publication(self.conn, **payload)

    def test_neutral_or_placeholder_classifications_are_rejected(self):
        for field in ("representation_mode", "reasons_status", "challenge_warning_status", "current_effect_status"):
            payload = dict(self.create, **{field: ""})
            with patch.object(publications.determinations, "get_determination", return_value=self.determination):
                with self.assertRaises(ValueError):
                    publications.create_publication(self.conn, **payload)


if __name__ == "__main__":
    unittest.main()
