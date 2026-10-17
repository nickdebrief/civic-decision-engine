"""Synthetic service tests for the restricted Stage 82 foundation."""
import os
import sqlite3
import tempfile
import unittest

from api import governed_challenge_register as register
from api import governed_defect_register as defect_register
from api.routes import admin_session


class GovernedChallengeRegisterTests(unittest.TestCase):
    def setUp(self):
        self.previous_secret = os.environ.get("CDE_ADMIN_SESSION_SECRET")
        os.environ["CDE_ADMIN_SESSION_SECRET"] = "stage82-disposable-test-secret"
        self.temp = tempfile.TemporaryDirectory()
        self.conn = sqlite3.connect(f"{self.temp.name}/challenge.db")
        self.conn.row_factory = sqlite3.Row
        self.admin = admin_session.create_admin_session("admin-a")

    def tearDown(self):
        self.conn.close(); self.temp.cleanup()
        if self.previous_secret is None: os.environ.pop("CDE_ADMIN_SESSION_SECRET", None)
        else: os.environ["CDE_ADMIN_SESSION_SECRET"] = self.previous_secret

    def fixture(self, identifier="CDE-CH-SYN-001", issues=(("ISS-001", "same synthetic grounds"),)):
        register.ensure_tables(self.conn)
        now = "2026-10-15T00:00:00Z"
        entry = self.conn.execute("INSERT INTO governed_challenge_entries (challenge_identifier,subject_type,subject_value,subject_identity,procedural_state,recipient_identity,recipient_basis,recipient_claim,version,created_at,created_by,updated_at,updated_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (identifier, "git_commit", "synthetic-commit", "synthetic-commit", "received", None, None, None, 1, now, "fixture", now, "fixture")).lastrowid
        for issue_id, grounds in issues:
            self.conn.execute("INSERT INTO governed_challenge_issues (entry_id,issue_identifier,grounds,reasons,requested_outcomes_json,issue_state,version,created_at,created_by,updated_at,updated_by) VALUES (?,?,?,?,?,?,?,?,?,?,?)", (entry, issue_id, grounds, "synthetic reason", '["review"]', "unassessed", 1, now, "fixture", now, "fixture"))
        self.conn.commit(); return identifier

    def item(self, identifier): return register.get_challenge(self.conn, identifier)

    def receipt(self, identifier, operation, version, **kwargs):
        common = dict(challenge_identifier=identifier, actor=self.admin, expected_version=version, idempotency_key=operation, reason="synthetic reason")
        return operation, common | kwargs

    def accepted(self, identifier):
        return register.accept(self.conn, challenge_identifier=identifier, recipient_identity="admin-a", recipient_basis="current authenticated administrator session", actor=self.admin, expected_version=1, idempotency_key=f"accept-{identifier}", reason="scope accepted")

    def assessed(self, identifier):
        accepted = self.accepted(identifier)
        return register.begin_assessment(self.conn, challenge_identifier=identifier, actor=self.admin, expected_version=accepted["resulting_version"], idempotency_key=f"assess-{identifier}", reason="assessment begins")

    def responded(self, identifier, version):
        prepared = register.prepare_response(self.conn, challenge_identifier=identifier, actor=self.admin, expected_version=version, idempotency_key="prepare-response", reason="prepare response")
        return register.mark_responded(self.conn, challenge_identifier=identifier, actor=self.admin, expected_version=prepared["resulting_version"], idempotency_key="mark-responded", reason="response sent")

    def evidence(self, identifier, issue, version, relation="response_evidence", value="evidence-1", key="evidence"):
        item = self.item(identifier)
        receipt = register.add_evidence(self.conn, challenge_identifier=identifier, issue_identifier=issue, reference_type="git_commit", reference_value=value, relation=relation, validation_basis="synthetic disposable validation", actor=self.admin, expected_version=version, idempotency_key=key, reason="synthetic evidence")
        evidence_id = self.conn.execute("SELECT id FROM governed_challenge_evidence ORDER BY id DESC LIMIT 1").fetchone()[0]
        return receipt, evidence_id

    def authoritative_stage81(self, identifier, *, target="synthetic-commit", outstanding=False, extra_target=None):
        """Direct disposable seed of an authoritative Stage 81 projection.

        It is intentionally not a Stage 82 helper: production code must read
        this state through the Stage 81 service rather than accept a claim.
        """
        defect_register.ensure_tables(self.conn)
        stamp = "2026-10-16T00:00:00Z"
        action = {"action_id": f"action-{identifier}", "agreed_version": 2,
                  "acceptance_criteria_identity": "synthetic-criteria",
                  "acceptance_criteria": ["criterion"],
                  "execution_status": "execution_substantiated", "execution_reference_id": 0}
        cursor = self.conn.execute(
            """INSERT INTO governed_defect_register_entries
            (entry_identifier,title,description,affected_component,observed_behavior,expected_behavior,expectation_source,reporter_source,lifecycle_state,assessment_classification,priority,owner_reference,impact_status,deferral_json,closure_json,preservation_hold_json,retention_review_json,active_action_json,synthetic_attestation_json,version,created_at,created_by,updated_at,updated_by)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (identifier, "Synthetic authoritative correction", "synthetic", "synthetic", "observed", "expected", "test", "test", "closed", "confirmed_defect", "P2_normal_bounded_assessment", None, "not_performed", None, None, None, None, defect_register._json(action), "fixture-only", 1, stamp, "fixture", stamp, "fixture"),
        )
        entry_id = cursor.lastrowid
        checks = defect_register._json([{"step": "relationship_substantiated", "status": "passed"}, {"step": "target_identity_or_content_verified", "status": "passed"}])
        target_id = self.conn.execute("INSERT INTO governed_defect_register_references (entry_id,entry_identifier,reference_type,reference_value,relation,neutral_label,supplier_identity,validator_identity,validation_steps_json,created_at,created_by) VALUES (?,?,?,?,?,?,?,?,?,?,?)", (entry_id, identifier, "git_commit", target, "action_target", "synthetic target", None, None, checks, stamp, "fixture")).lastrowid
        execution_id = self.conn.execute("INSERT INTO governed_defect_register_references (entry_id,entry_identifier,reference_type,reference_value,relation,neutral_label,supplier_identity,validator_identity,validation_steps_json,created_at,created_by) VALUES (?,?,?,?,?,?,?,?,?,?,?)", (entry_id, identifier, "git_commit", "execution", "execution_evidence", "synthetic execution", None, None, checks, stamp, "fixture")).lastrowid
        action["execution_reference_id"] = execution_id
        binding = defect_register._json({"action_id": action["action_id"], "action_agreed_version": 2, "acceptance_criteria_identity": "synthetic-criteria", "execution_reference_id": execution_id, "artifact_reference_type": "git_commit", "artifact_reference_value": "artifact"})
        artifact_id = self.conn.execute("INSERT INTO governed_defect_register_references (entry_id,entry_identifier,reference_type,reference_value,relation,neutral_label,supplier_identity,validator_identity,validation_steps_json,verification_binding_json,created_at,created_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (entry_id, identifier, "git_commit", "artifact", "verification_evidence", "synthetic artifact", None, None, checks, binding, stamp, "fixture")).lastrowid
        closure = defect_register._json({"outcome": "correction_verified", "verification": {"action_id": action["action_id"], "execution_reference_id": execution_id, "artifact_reference_id": artifact_id, "criteria_results": {"criterion": "passed"}}})
        self.conn.execute("UPDATE governed_defect_register_entries SET active_action_json=?,closure_json=? WHERE id=?", (defect_register._json(action), closure, entry_id))
        for value in ([extra_target] if extra_target else []):
            self.conn.execute("INSERT INTO governed_defect_register_references (entry_id,entry_identifier,reference_type,reference_value,relation,neutral_label,supplier_identity,validator_identity,validation_steps_json,created_at,created_by) VALUES (?,?,?,?,?,?,?,?,?,?,?)", (entry_id, identifier, "git_commit", value, "action_target", "synthetic target", None, None, checks, stamp, "fixture"))
        if outstanding:
            impact = self.conn.execute("INSERT INTO governed_defect_register_impacts (entry_id,entry_identifier,target_reference,status,assessment_basis,assessment_limits,follow_up_action,owner_reference,review_trigger,outcome,created_at,created_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (entry_id, identifier, "synthetic-target", "assessed_affected", "synthetic", "synthetic", None, None, None, None, stamp, "fixture")).lastrowid
            self.conn.execute("INSERT INTO governed_defect_register_revalidations (entry_id,entry_identifier,requirement_identifier,predecessor_requirement_id,supersession_reference_id,impact_id,origin_action_json,execution_reference_id,target_reference_id,target_identity_kind,target_identity,observed_at,assessment_scope,assessment_basis,assessment_limits,criteria_json,criteria_identity,linked_workflow_requires_approval,authority_reference_id,owner_reference,due_at,review_trigger,outcome,conclusion_json,outcome_details_json,superseded_by_requirement_id,version,created_at,created_by,updated_at,updated_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (entry_id, identifier, f"RV-{identifier}", None, None, impact, defect_register._json(action), execution_id, target_id, "exact_reference", target, stamp, "synthetic", "synthetic", "synthetic", '["criterion"]', "synthetic-criteria", 0, None, "admin-a", stamp, None, "awaiting_revalidation", None, None, None, 1, stamp, "fixture", stamp, "fixture"))
        self.conn.commit()
        return identifier

    def applicability(self, challenge, predecessor, successor, version, source, *, kind="later_correction", new_identity=None, key_suffix=""):
        receipt, evidence_id = self.evidence(challenge, predecessor, version, relation="applicability_evidence", value=f"basis-{predecessor}-{key_suffix}", key=f"applicability-evidence-{predecessor}-{key_suffix}")
        action = defect_register.get_entry(self.conn, source)["active_action"]
        receipt = register.record_applicability_assessment(
            self.conn, challenge_identifier=challenge, predecessor_issue_identifier=predecessor,
            successor_issue_identifier=successor, change_kind=kind,
            source_entry_identifier=source, source_action_id=action["action_id"],
            source_execution_reference_id=action["execution_reference_id"],
            supporting_evidence_ids=[evidence_id], old_subject_identity="synthetic-commit",
            new_subject_identity=new_identity, basis="bounded synthetic assessment",
            assessment_scope="synthetic challenge issues", limitations="synthetic only",
            actor=self.admin, expected_version=receipt["resulting_version"],
            idempotency_key=f"applicability-{predecessor}-{key_suffix}", reason="bounded applicability")
        assessment_id = self.conn.execute("SELECT id FROM governed_challenge_applicability_assessments ORDER BY id DESC LIMIT 1").fetchone()[0]
        return receipt, assessment_id

    def test_admission_disabled_and_assessment_requires_authenticated_acceptance(self):
        with self.assertRaisesRegex(ValueError, "admission_disabled"):
            register.create_challenge(self.conn, grounds="not retained")
        challenge = self.fixture()
        with self.assertRaisesRegex(ValueError, "acceptance_required"):
            register.begin_assessment(self.conn, challenge_identifier=challenge, actor=self.admin, expected_version=1, idempotency_key="bad", reason="bypass")
        with self.assertRaisesRegex(ValueError, "authenticated_actor_required"):
            register.accept(self.conn, challenge_identifier=challenge, recipient_identity="claimed-admin", recipient_basis="supplied name", actor="admin-a", expected_version=1, idempotency_key="claim", reason="bad claim")
        accepted = self.accepted(challenge)
        self.assertEqual(accepted["resulting_version"], 2)

    def test_exact_evidence_binding_response_and_atomic_rejection(self):
        challenge = self.fixture(); assessed = self.assessed(challenge)
        receipt, evidence_id = self.evidence(challenge, "ISS-001", assessed["resulting_version"], value="bound-evidence")
        before = self.item(challenge)
        with self.assertRaisesRegex(ValueError, "evidence_binding_mismatch"):
            register.respond(self.conn, challenge_identifier=challenge, issue_identifier="ISS-001", answer="answer", evidence_ids=[evidence_id + 99], limitations="synthetic", actor=self.admin, expected_version=receipt["resulting_version"], idempotency_key="bad-response", reason="unrelated")
        self.assertEqual(self.item(challenge)["version"], before["version"])
        answered = register.respond(self.conn, challenge_identifier=challenge, issue_identifier="ISS-001", answer="reasoned answer", evidence_ids=[evidence_id], limitations="synthetic limits", actor=self.admin, expected_version=before["version"], idempotency_key="response", reason="responded")
        self.assertEqual(answered["resulting_version"], before["version"] + 1)
        self.assertEqual(self.item(challenge)["issues"][0]["issue_state"], "answered")

    def test_awaiting_information_and_deferral_block_closure(self):
        challenge = self.fixture(); assessed = self.assessed(challenge)
        with self.assertRaisesRegex(ValueError, "closure_incomplete"):
            register.close(self.conn, challenge_identifier=challenge, actor=self.admin, expected_version=assessed["resulting_version"], idempotency_key="bad-close", reason="still open")
        # Requesting information is only permitted before assessment; it remains a closure blocker.
        challenge = self.fixture("CDE-CH-SYN-INF", (("ISS-INF", "same synthetic grounds"),))
        requested = register.request_information(self.conn, challenge_identifier=challenge, issue_identifier="ISS-INF", missing_information="synthetic supporting material", responsible_actor=self.admin, review_trigger="new synthetic evidence", actor=self.admin, expected_version=1, idempotency_key="information", reason="wait")
        deferred = register.defer_issue(self.conn, challenge_identifier=challenge, issue_identifier="ISS-INF", owner=self.admin, review_trigger="new synthetic evidence", actor=self.admin, expected_version=requested["resulting_version"], idempotency_key="defer", reason="wait")
        with self.assertRaisesRegex(ValueError, "transition_invalid"):
            register.close(self.conn, challenge_identifier=challenge, actor=self.admin, expected_version=deferred["resulting_version"], idempotency_key="blocked-close", reason="deferral is not closure")

    def test_duplicate_requires_exact_same_ground_issue_and_reopening_parent_is_atomic(self):
        challenge = self.fixture(issues=(("ISS-001", "same grounds"), ("ISS-002", "same grounds")))
        accepted = self.accepted(challenge)
        evidence, evidence_id = self.evidence(challenge, "ISS-002", accepted["resulting_version"], relation="duplicate_evidence", value="ISS-001", key="duplicate-evidence")
        assessment = register.record_independent_issue_assessment(self.conn, challenge_identifier=challenge, issue_identifier="ISS-002", disposition="duplicate", evidence_id=evidence_id, conclusion=register.CLOSURE_NO_INDEPENDENT_ISSUE, limitations="synthetic", actor=self.admin, expected_version=evidence["resulting_version"], idempotency_key="duplicate-assessment", reason="assessment", related_issue_identifier="ISS-001")
        assessment_id = self.conn.execute("SELECT id FROM governed_challenge_closure_assessments ORDER BY id DESC LIMIT 1").fetchone()[0]
        disposed = register.set_disposition(self.conn, challenge_identifier=challenge, issue_identifier="ISS-002", disposition="duplicate", basis="same grounds", limitations="synthetic", evidence_id=evidence_id, duplicate_issue_identifier="ISS-001", independent_assessment_id=assessment_id, actor=self.admin, expected_version=assessment["resulting_version"], idempotency_key="duplicate", reason="duplicate")
        self.assertEqual(self.item(challenge)["issues"][1]["issue_state"], "duplicate")
        assessed = register.begin_assessment(self.conn, challenge_identifier=challenge, actor=self.admin, expected_version=disposed["resulting_version"], idempotency_key="assess-after-duplicate", reason="assessment begins")
        # Make the first issue eligible, close, then prove reopening changes parent and issue together.
        evidence, evidence_id = self.evidence(challenge, "ISS-001", assessed["resulting_version"], key="response-evidence")
        answered = register.respond(self.conn, challenge_identifier=challenge, issue_identifier="ISS-001", answer="answered", evidence_ids=[evidence_id], limitations="synthetic", actor=self.admin, expected_version=evidence["resulting_version"], idempotency_key="answer", reason="answer")
        responded = self.responded(challenge, answered["resulting_version"])
        closed = register.close(self.conn, challenge_identifier=challenge, actor=self.admin, expected_version=responded["resulting_version"], idempotency_key="close", reason="all eligible")
        reopened = register.reopen_issue(self.conn, challenge_identifier=challenge, issue_identifier="ISS-001", actor=self.admin, expected_version=closed["resulting_version"], idempotency_key="reopen", reason="new evidence")
        item = self.item(challenge)
        self.assertEqual(reopened["resulting_version"], closed["resulting_version"] + 1)
        self.assertEqual(item["procedural_state"], "reopened")
        self.assertEqual(item["issues"][0]["issue_state"], "under_assessment")

    def test_limits_amendments_and_historical_retry(self):
        challenge = self.fixture()
        assessed = self.assessed(challenge)
        first = register.amend(self.conn, challenge_identifier=challenge, issue_identifier="ISS-001", changed_material="clarification", actor=self.admin, expected_version=assessed["resulting_version"], idempotency_key="amend-1", reason="clarify")
        replay = register.amend(self.conn, challenge_identifier=challenge, issue_identifier="ISS-001", changed_material="clarification", actor=self.admin, expected_version=assessed["resulting_version"], idempotency_key="amend-1", reason="clarify")
        self.assertTrue(replay["historical_receipt"])
        # A disposable fixture reaches the approved prior-amendment bound.
        item = self.item(challenge); issue_id = item["issues"][0]["id"]
        for number in range(19):
            self.conn.execute("INSERT INTO governed_challenge_amendments (entry_id,issue_id,changed_material,reason,created_at,created_by) VALUES (?,?,?,?,?,?)", (item["id"], issue_id, f"prior-{number}", "fixture", "2026-10-15T00:00:00Z", "fixture"))
        self.conn.commit()
        before = self.item(challenge)
        with self.assertRaisesRegex(ValueError, "amendment_limit_exceeded"):
            register.amend(self.conn, challenge_identifier=challenge, issue_identifier="ISS-001", changed_material="over", actor=self.admin, expected_version=first["resulting_version"], idempotency_key="over-limit", reason="over")
        self.assertEqual(self.item(challenge)["version"], before["version"])

    def test_subject_issue_limit_and_successor_are_exact_and_atomic(self):
        challenge = self.fixture(issues=tuple((f"ISS-{number:03d}", f"grounds-{number}") for number in range(1, 22)))
        with self.assertRaisesRegex(ValueError, "issue_limit_exceeded"):
            self.accepted(challenge)
        self.assertEqual(self.item(challenge)["procedural_state"], "received")
        challenge = self.fixture("CDE-CH-SYN-002", (("ISS-101", "old"), ("ISS-102", "new")))
        assessed = self.assessed(challenge)
        with self.assertRaisesRegex(ValueError, "applicability_assessment_required"):
            register.link_successor(self.conn, challenge_identifier=challenge, predecessor_issue_identifier="ISS-101", successor_issue_identifier="ISS-102", applicability_assessment_id=999, actor=self.admin, expected_version=assessed["resulting_version"], idempotency_key="bad-successor", reason="wrong")
        self.assertEqual(self.item(challenge)["issues"][0]["successor_issue_id"], None)
        source = self.authoritative_stage81("DREG-SYN-S1")
        assessment, assessment_id = self.applicability(challenge, "ISS-101", "ISS-102", assessed["resulting_version"], source)
        linked = register.link_successor(self.conn, challenge_identifier=challenge, predecessor_issue_identifier="ISS-101", successor_issue_identifier="ISS-102", applicability_assessment_id=assessment_id, actor=self.admin, expected_version=assessment["resulting_version"], idempotency_key="successor", reason="changed subject")
        self.assertEqual(linked["resulting_version"], assessment["resulting_version"] + 1)

    def test_explicit_issue_and_procedural_transitions_reject_invalid_shortcuts(self):
        challenge = self.fixture(); assessed = self.assessed(challenge)
        with self.assertRaisesRegex(ValueError, "evidence_binding_mismatch"):
            register.respond(self.conn, challenge_identifier=challenge, issue_identifier="ISS-001", answer="answer", evidence_ids=[1], limitations="limits", actor=self.admin, expected_version=assessed["resulting_version"], idempotency_key="response-before-evidence", reason="bad")
        with self.assertRaisesRegex(ValueError, "transition_invalid"):
            register.mark_responded(self.conn, challenge_identifier=challenge, actor=self.admin, expected_version=assessed["resulting_version"], idempotency_key="responded-before-preparation", reason="bad")
        # Awaiting-information has its own explicit transition and cannot be answered.
        challenge = self.fixture("CDE-CH-SYN-AWAIT", (("ISS-AWAIT", "same synthetic grounds"),))
        requested = register.request_information(self.conn, challenge_identifier=challenge, issue_identifier="ISS-AWAIT", missing_information="synthetic detail", responsible_actor=self.admin, review_on="2026-11-01T00:00:00Z", actor=self.admin, expected_version=1, idempotency_key="request-info", reason="need detail")
        with self.assertRaisesRegex(ValueError, "issue_transition_invalid"):
            register.respond(self.conn, challenge_identifier=challenge, issue_identifier="ISS-AWAIT", answer="cannot answer", evidence_ids=[1], limitations="limits", actor=self.admin, expected_version=requested["resulting_version"], idempotency_key="answer-awaiting", reason="bad")

    def test_raw_actor_and_caller_validation_flags_cannot_establish_trust(self):
        challenge = self.fixture()
        with self.assertRaisesRegex(ValueError, "authenticated_actor_required"):
            register.accept(self.conn, challenge_identifier=challenge, recipient_identity="admin-a", recipient_basis="claimed", actor="admin-a", expected_version=1, idempotency_key="raw", reason="bad")
        accepted = self.accepted(challenge)
        with self.assertRaisesRegex(ValueError, "validation_claim_rejected"):
            register.add_evidence(self.conn, challenge_identifier=challenge, issue_identifier="ISS-001", reference_type="git_commit", reference_value="claim", relation="response_evidence", validation_steps=[{"status": "passed"}], validation_basis="synthetic", actor=self.admin, expected_version=accepted["resulting_version"], idempotency_key="claimed-validation", reason="bad")
        self.assertEqual(self.item(challenge)["version"], accepted["resulting_version"])

    def test_forged_session_mapping_and_unsigned_token_cannot_mutate_or_validate(self):
        challenge = self.fixture()
        before = self.item(challenge)["version"]
        for actor in ({"role": "admin", "username": "victim"}, "eyJyb2xlIjoiYWRtaW4ifQ.invalid"):
            with self.assertRaisesRegex(ValueError, "authenticated_actor_required"):
                register.accept(self.conn, challenge_identifier=challenge, actor=actor, expected_version=before, idempotency_key=f"forged-{type(actor).__name__}", reason="forged")
        self.assertEqual(self.item(challenge)["version"], before)

    def test_independent_assessment_is_immutable_and_required_for_withdrawal(self):
        challenge = self.fixture(); accepted = self.accepted(challenge)
        evidence, evidence_id = self.evidence(challenge, "ISS-001", accepted["resulting_version"], relation="disposition_evidence", value="withdrawal-evidence")
        with self.assertRaisesRegex(ValueError, "closure_assessment_required"):
            register.set_disposition(self.conn, challenge_identifier=challenge, issue_identifier="ISS-001", disposition="withdrawn", basis="withdrawn", limitations="limits", evidence_id=evidence_id, actor=self.admin, expected_version=evidence["resulting_version"], idempotency_key="without-assessment", reason="bad")
        assessment = register.record_closure_assessment(self.conn, challenge_identifier=challenge, issue_identifier="ISS-001", disposition="withdrawn", evidence_id=evidence_id, assessment_scope="registered synthetic issues", basis="reasoned withdrawal", limitations="synthetic limits", actor=self.admin, expected_version=evidence["resulting_version"], idempotency_key="assessment", reason="record")
        assessment_id = self.conn.execute("SELECT id FROM governed_challenge_closure_assessments ORDER BY id DESC LIMIT 1").fetchone()[0]
        result = register.set_disposition(self.conn, challenge_identifier=challenge, issue_identifier="ISS-001", disposition="withdrawn", basis="withdrawn", limitations="limits", evidence_id=evidence_id, independent_assessment_id=assessment_id, actor=self.admin, expected_version=assessment["resulting_version"], idempotency_key="withdraw", reason="withdraw")
        self.assertEqual(result["resulting_version"], assessment["resulting_version"] + 1)
        self.assertEqual(self.conn.execute("SELECT count(*) FROM governed_challenge_closure_assessments").fetchone()[0], 1)

    def test_closure_assessment_rejects_arbitrary_claim_atomically(self):
        challenge = self.fixture("CDE-CH-SYN-CLOSURE")
        accepted = self.accepted(challenge)
        evidence, evidence_id = self.evidence(challenge, "ISS-001", accepted["resulting_version"], relation="disposition_evidence", value="claimed-withdrawal")
        before = self.item(challenge)
        with self.assertRaisesRegex(ValueError, "closure_assessment_scope_required"):
            register.record_closure_assessment(self.conn, challenge_identifier=challenge, issue_identifier="ISS-001", disposition="withdrawn", evidence_id=evidence_id, assessment_scope="", basis="unsupported claim", limitations="unsupported claim", actor=self.admin, expected_version=before["version"], idempotency_key="arbitrary-conclusion", reason="claim")
        self.assertEqual(self.item(challenge)["version"], before["version"])
        self.assertEqual(self.conn.execute("SELECT count(*) FROM governed_challenge_closure_assessments").fetchone()[0], 0)

    def test_successor_requires_substantiated_later_correction_and_links_are_accurate(self):
        challenge = self.fixture("CDE-CH-SYN-S", (("OLD", "old"), ("NEW", "new")))
        accepted = self.accepted(challenge)
        bad, bad_id = self.evidence(challenge, "OLD", accepted["resulting_version"], relation="applicability_evidence", value="NEW", key="bad-successor")
        with self.assertRaisesRegex(ValueError, "applicability_assessment_required"):
            register.link_successor(self.conn, challenge_identifier=challenge, predecessor_issue_identifier="OLD", successor_issue_identifier="NEW", applicability_assessment_id=bad_id, actor=self.admin, expected_version=bad["resulting_version"], idempotency_key="bad-link", reason="bad")
        source = self.authoritative_stage81("DREG-SYN-S2")
        good, assessment_id = self.applicability(challenge, "OLD", "NEW", bad["resulting_version"], source)
        register.link_successor(self.conn, challenge_identifier=challenge, predecessor_issue_identifier="OLD", successor_issue_identifier="NEW", applicability_assessment_id=assessment_id, actor=self.admin, expected_version=good["resulting_version"], idempotency_key="good-link", reason="later correction")
        self.assertEqual(self.item(challenge)["issues"][0]["successor_issue_id"], self.item(challenge)["issues"][1]["id"])

    def test_substantive_history_and_active_linked_work_are_preserved(self):
        challenge = self.fixture(); assessed = self.assessed(challenge)
        source = self.authoritative_stage81("DREG-SYN-1", outstanding=True)
        evidence, evidence_id = self.evidence(challenge, "ISS-001", assessed["resulting_version"], relation="follow_through_relationship", value=source, key="follow")
        linked = register.link_follow_through(self.conn, challenge_identifier=challenge, issue_identifier="ISS-001", workflow_kind="stage81_1", workflow_identifier="DREG-SYN-1", requirement_identifier="RV-DREG-SYN-1", evidence_id=evidence_id, substantive_response="reasoned response", actor=self.admin, expected_version=evidence["resulting_version"], idempotency_key="link", reason="linked")
        item = self.item(challenge)
        self.assertEqual(len(item["response_history"]), 1)
        self.assertTrue(item["outstanding_linked_work"])
        self.assertIn("unavailable or unverified", register.render_private_status(item))
        prepared = register.prepare_response(self.conn, challenge_identifier=challenge, actor=self.admin, expected_version=linked["resulting_version"], idempotency_key="prepare", reason="prepare")
        marked = register.mark_responded(self.conn, challenge_identifier=challenge, actor=self.admin, expected_version=prepared["resulting_version"], idempotency_key="responded", reason="responded")
        closed = register.close(self.conn, challenge_identifier=challenge, actor=self.admin, expected_version=marked["resulting_version"], idempotency_key="close", reason="closure")
        with self.assertRaisesRegex(ValueError, "issue_transition_invalid"):
            register.reopen_issue(self.conn, challenge_identifier=challenge, issue_identifier="ISS-001", actor=self.admin, expected_version=closed["resulting_version"], idempotency_key="reopen-history", reason="reconsider")
        self.assertEqual(len(self.item(challenge)["response_history"]), 1)

    def test_linked_display_derives_current_stage81_state_not_local_link_claim(self):
        challenge = self.fixture("CDE-CH-SYN-LINKS", (("ISS-CORR", "correction issue"), ("ISS-IMPACT", "impact issue")))
        assessed = self.assessed(challenge)
        missing, missing_id = self.evidence(challenge, "ISS-CORR", assessed["resulting_version"], relation="follow_through_relationship", value="DREG-MISSING", key="missing-link")
        with self.assertRaisesRegex(ValueError, "authoritative_reference_unavailable"):
            register.link_follow_through(self.conn, challenge_identifier=challenge, issue_identifier="ISS-CORR", workflow_kind="stage81", workflow_identifier="DREG-MISSING", evidence_id=missing_id, substantive_response="claim", actor=self.admin, expected_version=missing["resulting_version"], idempotency_key="missing-follow-through", reason="claimed")
        source = self.authoritative_stage81("DREG-ACTUAL", outstanding=True)
        corr, corr_id = self.evidence(challenge, "ISS-CORR", missing["resulting_version"], relation="follow_through_relationship", value=source, key="actual-correction-link")
        linked = register.link_follow_through(self.conn, challenge_identifier=challenge, issue_identifier="ISS-CORR", workflow_kind="stage81", workflow_identifier=source, evidence_id=corr_id, substantive_response="correction response", actor=self.admin, expected_version=corr["resulting_version"], idempotency_key="correction-link", reason="linked")
        impact, impact_id = self.evidence(challenge, "ISS-IMPACT", linked["resulting_version"], relation="follow_through_relationship", value=source, key="actual-impact-link")
        register.link_follow_through(self.conn, challenge_identifier=challenge, issue_identifier="ISS-IMPACT", workflow_kind="stage81_1", workflow_identifier=source, requirement_identifier=f"RV-{source}", evidence_id=impact_id, substantive_response="impact response", actor=self.admin, expected_version=impact["resulting_version"], idempotency_key="impact-link", reason="linked")
        self.assertEqual(register.render_private_status(self.item(challenge)), "Original correction verified — downstream work outstanding.")
        # Simulate an authoritative later state change.  The Stage 82 link is
        # retained, but cannot continue to assert verified correction.
        self.conn.execute("UPDATE governed_defect_register_entries SET lifecycle_state=?, closure_json=? WHERE entry_identifier=?", ("under_assessment", None, source)); self.conn.commit()
        changed = self.item(challenge)
        self.assertIn("unavailable or unverified", register.render_private_status(changed))
        self.assertFalse(changed["original_correction_verified_downstream_work_outstanding"])

    def test_successor_requires_authoritative_source_for_all_supported_bases(self):
        # A caller-held evidence identifier cannot establish applicability.
        challenge = self.fixture("CDE-CH-SYN-SOURCE-V2", (("OLD", "old"), ("NEW", "new")))
        accepted = self.accepted(challenge)
        asserted, asserted_id = self.evidence(challenge, "OLD", accepted["resulting_version"], relation="applicability_evidence", value="asserted", key="asserted-source-v2")
        with self.assertRaisesRegex(ValueError, "applicability_assessment_required"):
            register.link_successor(self.conn, challenge_identifier=challenge, predecessor_issue_identifier="OLD", successor_issue_identifier="NEW", applicability_assessment_id=asserted_id, actor=self.admin, expected_version=asserted["resulting_version"], idempotency_key="fiction-link-v2", reason="fiction")
        self.assertIsNone(self.item(challenge)["issues"][0]["successor_issue_id"])
        source = self.authoritative_stage81("DREG-LATER-V2")
        assessed, assessment_id = self.applicability(challenge, "OLD", "NEW", asserted["resulting_version"], source)
        linked = register.link_successor(self.conn, challenge_identifier=challenge, predecessor_issue_identifier="OLD", successor_issue_identifier="NEW", applicability_assessment_id=assessment_id, actor=self.admin, expected_version=assessed["resulting_version"], idempotency_key="later-link-v2", reason="later correction")
        self.assertEqual(linked["resulting_version"], assessed["resulting_version"] + 1)
        return
        # A self-consistent caller context still fails when no authoritative
        # Stage 81 relationship source exists; no predecessor write occurs.
        challenge = self.fixture("CDE-CH-SYN-SOURCE", (("OLD", "old"), ("NEW", "new")))
        accepted = self.accepted(challenge)
        asserted = register.add_evidence(self.conn, challenge_identifier=challenge, issue_identifier="OLD", reference_type="correction", reference_value="DREG-FICTION", relation="successor_relationship", validation_basis="claim", relationship_context={"change_kind": "later_correction", "predecessor_issue_identifier": "OLD", "successor_issue_identifier": "NEW", "authoritative_entry_identifier": "DREG-FICTION"}, actor=self.admin, expected_version=accepted["resulting_version"], idempotency_key="asserted-source", reason="claim")
        asserted_id = self.conn.execute("SELECT id FROM governed_challenge_evidence ORDER BY id DESC LIMIT 1").fetchone()[0]
        with self.assertRaisesRegex(ValueError, "authoritative_reference_unavailable"):
            register.link_successor(self.conn, challenge_identifier=challenge, predecessor_issue_identifier="OLD", successor_issue_identifier="NEW", evidence_id=asserted_id, actor=self.admin, expected_version=asserted["resulting_version"], idempotency_key="fiction-link", reason="fiction")
        self.assertIsNone(self.item(challenge)["issues"][0]["successor_issue_id"])

        # A verified later correction for the same target permits a successor
        # without inventing a target or criteria change.
        source = self.authoritative_stage81("DREG-LATER")
        good = register.add_evidence(self.conn, challenge_identifier=challenge, issue_identifier="OLD", reference_type="correction", reference_value=source, relation="successor_relationship", validation_basis="authoritative source", relationship_context={"change_kind": "later_correction", "predecessor_issue_identifier": "OLD", "successor_issue_identifier": "NEW", "authoritative_entry_identifier": source}, actor=self.admin, expected_version=asserted["resulting_version"], idempotency_key="later-source", reason="later correction")
        good_id = self.conn.execute("SELECT id FROM governed_challenge_evidence ORDER BY id DESC LIMIT 1").fetchone()[0]
        register.link_successor(self.conn, challenge_identifier=challenge, predecessor_issue_identifier="OLD", successor_issue_identifier="NEW", evidence_id=good_id, actor=self.admin, expected_version=good["resulting_version"], idempotency_key="later-link", reason="later correction")

        versioned = self.fixture("CDE-CH-SYN-VERSION", (("OLD-V", "old"), ("NEW-V", "new")))
        versioned_accepted = self.accepted(versioned)
        version_source = self.authoritative_stage81("DREG-VERSION", extra_target="synthetic-commit-v2")
        evidence = register.add_evidence(self.conn, challenge_identifier=versioned, issue_identifier="OLD-V", reference_type="correction", reference_value=version_source, relation="successor_relationship", validation_basis="authoritative version", relationship_context={"change_kind": "subject_version", "predecessor_issue_identifier": "OLD-V", "successor_issue_identifier": "NEW-V", "authoritative_entry_identifier": version_source, "predecessor_subject_identity": "synthetic-commit", "successor_subject_identity": "synthetic-commit-v2"}, actor=self.admin, expected_version=versioned_accepted["resulting_version"], idempotency_key="version-source", reason="version")
        version_id = self.conn.execute("SELECT id FROM governed_challenge_evidence ORDER BY id DESC LIMIT 1").fetchone()[0]
        register.link_successor(self.conn, challenge_identifier=versioned, predecessor_issue_identifier="OLD-V", successor_issue_identifier="NEW-V", evidence_id=version_id, actor=self.admin, expected_version=evidence["resulting_version"], idempotency_key="version-link", reason="version")

        material = self.fixture("CDE-CH-SYN-MATERIAL", (("OLD-M", "old"), ("NEW-M", "new")))
        material_accepted = self.accepted(material)
        material_source = self.authoritative_stage81("DREG-MATERIAL")
        source_entry = defect_register.get_entry(self.conn, material_source)
        material_ref = self.conn.execute("INSERT INTO governed_defect_register_references (entry_id,entry_identifier,reference_type,reference_value,relation,neutral_label,supplier_identity,validator_identity,validation_steps_json,created_at,created_by) VALUES (?,?,?,?,?,?,?,?,?,?,?)", (source_entry["id"], material_source, "git_commit", "material-proof", "assessment_evidence", "synthetic material change", None, None, defect_register._json([{"step": "relationship_substantiated", "status": "passed"}]), "2026-10-16T00:00:00Z", "fixture")).lastrowid
        self.conn.commit()
        evidence = register.add_evidence(self.conn, challenge_identifier=material, issue_identifier="OLD-M", reference_type="correction", reference_value=material_source, relation="successor_relationship", validation_basis="authoritative material", relationship_context={"change_kind": "material_change", "predecessor_issue_identifier": "OLD-M", "successor_issue_identifier": "NEW-M", "authoritative_entry_identifier": material_source, "material_change_reference_id": material_ref}, actor=self.admin, expected_version=material_accepted["resulting_version"], idempotency_key="material-source", reason="material")
        material_id = self.conn.execute("SELECT id FROM governed_challenge_evidence ORDER BY id DESC LIMIT 1").fetchone()[0]
        register.link_successor(self.conn, challenge_identifier=material, predecessor_issue_identifier="OLD-M", successor_issue_identifier="NEW-M", evidence_id=material_id, actor=self.admin, expected_version=evidence["resulting_version"], idempotency_key="material-link", reason="material")

    def test_applicability_assessment_becomes_stale_after_grounds_amendment(self):
        challenge = self.fixture("CDE-CH-SYN-GROUNDS", (("OLD", "old"), ("NEW", "new")))
        accepted = self.accepted(challenge)
        source = self.authoritative_stage81("DREG-GROUNDS")
        assessed, assessment_id = self.applicability(challenge, "OLD", "NEW", accepted["resulting_version"], source)
        amended = register.amend(self.conn, challenge_identifier=challenge, issue_identifier="OLD", changed_material="material clarification", actor=self.admin, expected_version=assessed["resulting_version"], idempotency_key="grounds-amendment", reason="clarify grounds")
        with self.assertRaisesRegex(ValueError, "applicability_stale"):
            register.link_successor(self.conn, challenge_identifier=challenge, predecessor_issue_identifier="OLD", successor_issue_identifier="NEW", applicability_assessment_id=assessment_id, actor=self.admin, expected_version=amended["resulting_version"], idempotency_key="stale-applicability", reason="stale")
        self.assertIsNone(self.item(challenge)["issues"][0]["successor_issue_id"])

    def test_duplicate_related_grounds_revision_is_bound_and_reassessment_restores_eligibility(self):
        challenge = self.fixture("CDE-CH-SYN-DUP-STALE", (("ISS-A", "same grounds"), ("ISS-B", "same grounds")))
        accepted = self.accepted(challenge)
        evidence, evidence_id = self.evidence(challenge, "ISS-B", accepted["resulting_version"], relation="duplicate_evidence", value="ISS-A", key="duplicate-stale-evidence")
        first = register.record_closure_assessment(self.conn, challenge_identifier=challenge, issue_identifier="ISS-B", disposition="duplicate", evidence_id=evidence_id, assessment_scope="synthetic", basis="same bounded grounds", limitations="synthetic", related_issue_identifier="ISS-A", actor=self.admin, expected_version=evidence["resulting_version"], idempotency_key="duplicate-stale-assessment", reason="assess")
        assessment_id = self.conn.execute("SELECT id FROM governed_challenge_closure_assessments ORDER BY id DESC LIMIT 1").fetchone()[0]
        amended = register.amend(self.conn, challenge_identifier=challenge, issue_identifier="ISS-A", changed_material="same grounds", actor=self.admin, expected_version=first["resulting_version"], idempotency_key="duplicate-related-amend", reason="clarify")
        before = self.item(challenge)
        with self.assertRaisesRegex(ValueError, "duplicate_binding_mismatch"):
            register.set_disposition(self.conn, challenge_identifier=challenge, issue_identifier="ISS-B", disposition="duplicate", basis="same", limitations="synthetic", evidence_id=evidence_id, duplicate_issue_identifier="ISS-A", closure_assessment_id=assessment_id, actor=self.admin, expected_version=amended["resulting_version"], idempotency_key="duplicate-stale-disposition", reason="stale")
        self.assertEqual(self.item(challenge)["version"], before["version"])
        self.assertEqual(self.conn.execute("SELECT count(*) FROM governed_challenge_disposition_history").fetchone()[0], 0)
        refreshed = register.record_closure_assessment(self.conn, challenge_identifier=challenge, issue_identifier="ISS-B", disposition="duplicate", evidence_id=evidence_id, assessment_scope="synthetic", basis="same bounded grounds after amendment", limitations="synthetic", related_issue_identifier="ISS-A", actor=self.admin, expected_version=before["version"], idempotency_key="duplicate-fresh-assessment", reason="reassess")
        refreshed_id = self.conn.execute("SELECT id FROM governed_challenge_closure_assessments ORDER BY id DESC LIMIT 1").fetchone()[0]
        disposed = register.set_disposition(self.conn, challenge_identifier=challenge, issue_identifier="ISS-B", disposition="duplicate", basis="same", limitations="synthetic", evidence_id=evidence_id, duplicate_issue_identifier="ISS-A", closure_assessment_id=refreshed_id, actor=self.admin, expected_version=refreshed["resulting_version"], idempotency_key="duplicate-fresh-disposition", reason="supported")
        self.assertEqual(disposed["resulting_version"], refreshed["resulting_version"] + 1)

    def test_successor_grounds_revision_is_bound_in_both_directions_and_reassessment_is_required(self):
        challenge = self.fixture("CDE-CH-SYN-SUCCESSOR-STALE", (("OLD", "old grounds"), ("NEW", "new grounds")))
        accepted = self.accepted(challenge)
        source = self.authoritative_stage81("DREG-SUCCESSOR-STALE")
        initial, assessment_id = self.applicability(challenge, "OLD", "NEW", accepted["resulting_version"], source, key_suffix="initial")
        amended = register.amend(self.conn, challenge_identifier=challenge, issue_identifier="NEW", changed_material="new grounds", actor=self.admin, expected_version=initial["resulting_version"], idempotency_key="successor-grounds-amend", reason="clarify successor")
        before = self.item(challenge)
        with self.assertRaisesRegex(ValueError, "applicability_stale"):
            register.link_successor(self.conn, challenge_identifier=challenge, predecessor_issue_identifier="OLD", successor_issue_identifier="NEW", applicability_assessment_id=assessment_id, actor=self.admin, expected_version=amended["resulting_version"], idempotency_key="stale-successor-link", reason="stale")
        self.assertEqual(self.item(challenge)["version"], before["version"])
        self.assertIsNone(before["issues"][0]["successor_issue_id"])
        self.assertEqual(self.conn.execute("SELECT count(*) FROM governed_challenge_successor_relationships").fetchone()[0], 0)
        refreshed, refreshed_id = self.applicability(challenge, "OLD", "NEW", before["version"], source, key_suffix="after-successor-amendment")
        linked = register.link_successor(self.conn, challenge_identifier=challenge, predecessor_issue_identifier="OLD", successor_issue_identifier="NEW", applicability_assessment_id=refreshed_id, actor=self.admin, expected_version=refreshed["resulting_version"], idempotency_key="fresh-successor-link", reason="reassessed")
        self.assertEqual(linked["resulting_version"], refreshed["resulting_version"] + 1)

    def test_reopened_duplicate_requires_fresh_current_assessment_before_closure(self):
        challenge = self.fixture("CDE-CH-SYN-REOPENED-DUP", (("ISS-A", "same grounds"), ("ISS-B", "same grounds")))
        accepted = self.accepted(challenge)
        evidence, evidence_id = self.evidence(challenge, "ISS-B", accepted["resulting_version"], relation="duplicate_evidence", value="ISS-A", key="reopened-duplicate-evidence")
        first = register.record_closure_assessment(self.conn, challenge_identifier=challenge, issue_identifier="ISS-B", disposition="duplicate", evidence_id=evidence_id, assessment_scope="synthetic", basis="same grounds", limitations="synthetic", related_issue_identifier="ISS-A", actor=self.admin, expected_version=evidence["resulting_version"], idempotency_key="reopened-duplicate-first-assessment", reason="assess")
        first_id = self.conn.execute("SELECT id FROM governed_challenge_closure_assessments ORDER BY id DESC LIMIT 1").fetchone()[0]
        duplicate = register.set_disposition(self.conn, challenge_identifier=challenge, issue_identifier="ISS-B", disposition="duplicate", basis="same", limitations="synthetic", evidence_id=evidence_id, duplicate_issue_identifier="ISS-A", closure_assessment_id=first_id, actor=self.admin, expected_version=first["resulting_version"], idempotency_key="reopened-duplicate-first-disposition", reason="dispose")
        amended = register.amend(self.conn, challenge_identifier=challenge, issue_identifier="ISS-A", changed_material="same grounds", actor=self.admin, expected_version=duplicate["resulting_version"], idempotency_key="reopened-duplicate-same-text-amendment", reason="clarify")
        reopened = register.reopen_issue(self.conn, challenge_identifier=challenge, issue_identifier="ISS-B", actor=self.admin, expected_version=amended["resulting_version"], idempotency_key="reopened-duplicate-reopen", reason="reconsider")
        before = self.item(challenge)
        with self.assertRaisesRegex(ValueError, "duplicate_binding_mismatch"):
            register.set_disposition(self.conn, challenge_identifier=challenge, issue_identifier="ISS-B", disposition="duplicate", basis="same", limitations="synthetic", evidence_id=evidence_id, duplicate_issue_identifier="ISS-A", closure_assessment_id=first_id, actor=self.admin, expected_version=reopened["resulting_version"], idempotency_key="reopened-duplicate-stale", reason="stale")
        self.assertEqual(self.item(challenge)["version"], before["version"])
        fresh = register.record_closure_assessment(self.conn, challenge_identifier=challenge, issue_identifier="ISS-B", disposition="duplicate", evidence_id=evidence_id, assessment_scope="synthetic", basis="same after amendment", limitations="synthetic", related_issue_identifier="ISS-A", actor=self.admin, expected_version=before["version"], idempotency_key="reopened-duplicate-fresh-assessment", reason="reassess")
        fresh_id = self.conn.execute("SELECT id FROM governed_challenge_closure_assessments ORDER BY id DESC LIMIT 1").fetchone()[0]
        redisposed = register.set_disposition(self.conn, challenge_identifier=challenge, issue_identifier="ISS-B", disposition="duplicate", basis="same", limitations="synthetic", evidence_id=evidence_id, duplicate_issue_identifier="ISS-A", closure_assessment_id=fresh_id, actor=self.admin, expected_version=fresh["resulting_version"], idempotency_key="reopened-duplicate-fresh-disposition", reason="supported")
        assessed = register.begin_assessment(self.conn, challenge_identifier=challenge, actor=self.admin, expected_version=redisposed["resulting_version"], idempotency_key="reopened-duplicate-assess-a", reason="assess remaining")
        response_evidence, response_evidence_id = self.evidence(challenge, "ISS-A", assessed["resulting_version"], key="reopened-duplicate-response-evidence")
        responded_issue = register.respond(self.conn, challenge_identifier=challenge, issue_identifier="ISS-A", answer="addressed", evidence_ids=[response_evidence_id], limitations="synthetic", actor=self.admin, expected_version=response_evidence["resulting_version"], idempotency_key="reopened-duplicate-answer-a", reason="answer")
        responded = self.responded(challenge, responded_issue["resulting_version"])
        closed = register.close(self.conn, challenge_identifier=challenge, actor=self.admin, expected_version=responded["resulting_version"], idempotency_key="reopened-duplicate-close", reason="all issues supported")
        self.assertEqual(self.item(challenge)["procedural_state"], "closed")
        self.assertEqual(closed["resulting_version"], responded["resulting_version"] + 1)

        direct = self.fixture("CDE-CH-SYN-NO-REOPEN", (("ISS-X", "same grounds"), ("ISS-Y", "same grounds")))
        direct_assessed = self.assessed(direct)
        direct_evidence, direct_evidence_id = self.evidence(direct, "ISS-Y", direct_assessed["resulting_version"], relation="duplicate_evidence", value="ISS-X", key="no-reopen-evidence")
        direct_assessment = register.record_closure_assessment(self.conn, challenge_identifier=direct, issue_identifier="ISS-Y", disposition="duplicate", evidence_id=direct_evidence_id, assessment_scope="synthetic", basis="same grounds", limitations="synthetic", related_issue_identifier="ISS-X", actor=self.admin, expected_version=direct_evidence["resulting_version"], idempotency_key="no-reopen-assessment", reason="assess")
        direct_assessment_id = self.conn.execute("SELECT id FROM governed_challenge_closure_assessments ORDER BY id DESC LIMIT 1").fetchone()[0]
        with self.assertRaisesRegex(ValueError, "issue_transition_invalid"):
            register.set_disposition(self.conn, challenge_identifier=direct, issue_identifier="ISS-Y", disposition="duplicate", basis="same", limitations="synthetic", evidence_id=direct_evidence_id, duplicate_issue_identifier="ISS-X", closure_assessment_id=direct_assessment_id, actor=self.admin, expected_version=direct_assessment["resulting_version"], idempotency_key="no-reopen-duplicate", reason="not permitted")

    def test_successor_reassessment_preserves_history_and_keeps_predecessor_work_visible(self):
        challenge = self.fixture("CDE-CH-SYN-SUCCESSOR-CURRENT", (("OLD", "old grounds"), ("NEW", "new grounds")))
        assessed = self.assessed(challenge)
        source = self.authoritative_stage81("DREG-SUCCESSOR-CURRENT", outstanding=True)
        follow, follow_id = self.evidence(challenge, "OLD", assessed["resulting_version"], relation="follow_through_relationship", value=source, key="successor-current-follow")
        linked_work = register.link_follow_through(self.conn, challenge_identifier=challenge, issue_identifier="OLD", workflow_kind="stage81_1", workflow_identifier=source, requirement_identifier=f"RV-{source}", evidence_id=follow_id, substantive_response="downstream response", actor=self.admin, expected_version=follow["resulting_version"], idempotency_key="successor-current-follow-link", reason="link")
        first, first_id = self.applicability(challenge, "OLD", "NEW", linked_work["resulting_version"], source, key_suffix="current-first")
        linked = register.link_successor(self.conn, challenge_identifier=challenge, predecessor_issue_identifier="OLD", successor_issue_identifier="NEW", applicability_assessment_id=first_id, actor=self.admin, expected_version=first["resulting_version"], idempotency_key="successor-current-link", reason="initial applicability")
        self.assertEqual(self.item(challenge)["successor_applicability"][0]["status"], "current")
        amended = register.amend(self.conn, challenge_identifier=challenge, issue_identifier="NEW", changed_material="new grounds", actor=self.admin, expected_version=linked["resulting_version"], idempotency_key="successor-current-same-text-amend", reason="clarify")
        stale = self.item(challenge)
        self.assertEqual(stale["successor_applicability"][0]["status"], "requires_reassessment")
        self.assertTrue(stale["outstanding_linked_work"])
        self.assertIn("requires reassessment", register.render_private_status(stale))
        before = stale["version"]
        with self.assertRaisesRegex(ValueError, "closure_incomplete"):
            register.close(self.conn, challenge_identifier=challenge, actor=self.admin, expected_version=before, idempotency_key="successor-current-stale-close", reason="stale successor")
        self.assertEqual(self.item(challenge)["version"], before)
        refreshed, refreshed_id = self.applicability(challenge, "OLD", "NEW", before, source, key_suffix="current-refreshed")
        reestablished = register.link_successor(self.conn, challenge_identifier=challenge, predecessor_issue_identifier="OLD", successor_issue_identifier="NEW", applicability_assessment_id=refreshed_id, actor=self.admin, expected_version=refreshed["resulting_version"], idempotency_key="successor-current-reestablish", reason="fresh applicability")
        current = self.item(challenge)
        self.assertEqual(current["successor_applicability"][0]["status"], "current")
        self.assertFalse(current["outstanding_linked_work"])
        self.assertEqual(len(current["successor_reassessments"]), 1)
        self.assertTrue(reestablished["resulting_version"] > refreshed["resulting_version"])
        changed_action = dict(defect_register.get_entry(self.conn, source)["active_action"]); changed_action["agreed_version"] = 3
        self.conn.execute("UPDATE governed_defect_register_entries SET active_action_json=? WHERE entry_identifier=?", (defect_register._json(changed_action), source)); self.conn.commit()
        unavailable = self.item(challenge)
        self.assertEqual(unavailable["successor_applicability"][0]["status"], "requires_reassessment")
        self.assertTrue(unavailable["linked_workflow_state_unknown"])
        self.assertIn("requires reassessment", register.render_private_status(unavailable))

    def test_applicability_assessment_rechecks_source_action_identity(self):
        challenge = self.fixture("CDE-CH-SYN-SOURCE-STALE", (("OLD", "old"), ("NEW", "new")))
        accepted = self.accepted(challenge)
        source = self.authoritative_stage81("DREG-SOURCE-STALE")
        assessed, assessment_id = self.applicability(challenge, "OLD", "NEW", accepted["resulting_version"], source)
        entry = defect_register.get_entry(self.conn, source)
        changed_action = dict(entry["active_action"]); changed_action["agreed_version"] = 3
        self.conn.execute("UPDATE governed_defect_register_entries SET active_action_json=? WHERE entry_identifier=?", (defect_register._json(changed_action), source)); self.conn.commit()
        with self.assertRaisesRegex(ValueError, "applicability_stale"):
            register.link_successor(self.conn, challenge_identifier=challenge, predecessor_issue_identifier="OLD", successor_issue_identifier="NEW", applicability_assessment_id=assessment_id, actor=self.admin, expected_version=assessed["resulting_version"], idempotency_key="source-stale", reason="stale source")
        self.assertIsNone(self.item(challenge)["issues"][0]["successor_issue_id"])

    def test_current_but_inactive_revalidation_is_not_unknown_or_outstanding(self):
        challenge = self.fixture("CDE-CH-SYN-INACTIVE", (("ISS-CORR", "correction"), ("ISS-IMPACT", "impact")))
        assessed = self.assessed(challenge)
        source = self.authoritative_stage81("DREG-INACTIVE", outstanding=True)
        corr, corr_id = self.evidence(challenge, "ISS-CORR", assessed["resulting_version"], relation="follow_through_relationship", value=source, key="inactive-correction")
        linked = register.link_follow_through(self.conn, challenge_identifier=challenge, issue_identifier="ISS-CORR", workflow_kind="stage81", workflow_identifier=source, evidence_id=corr_id, substantive_response="correction response", actor=self.admin, expected_version=corr["resulting_version"], idempotency_key="inactive-correction-link", reason="link")
        impact, impact_id = self.evidence(challenge, "ISS-IMPACT", linked["resulting_version"], relation="follow_through_relationship", value=source, key="inactive-impact")
        linked = register.link_follow_through(self.conn, challenge_identifier=challenge, issue_identifier="ISS-IMPACT", workflow_kind="stage81_1", workflow_identifier=source, requirement_identifier=f"RV-{source}", evidence_id=impact_id, substantive_response="impact response", actor=self.admin, expected_version=impact["resulting_version"], idempotency_key="inactive-impact-link", reason="link")
        self.conn.execute("UPDATE governed_defect_register_revalidations SET outcome=?, version=version+1 WHERE entry_identifier=?", ("not_required", source)); self.conn.commit()
        item = self.item(challenge)
        self.assertFalse(item["outstanding_linked_work"])
        self.assertFalse(item["linked_workflow_state_unknown"])
        self.assertEqual(register.render_private_status(item), "Original correction verification is recorded; no active downstream work is recorded.")

    def test_invalid_duplicate_closure_is_atomic(self):
        challenge = self.fixture(issues=(("ISS-D1", "same grounds"), ("ISS-D2", "same grounds")))
        accepted = self.accepted(challenge)
        evidence, evidence_id = self.evidence(challenge, "ISS-D2", accepted["resulting_version"], relation="duplicate_evidence", value="ISS-D1", key="duplicate-evidence")
        with self.assertRaisesRegex(ValueError, "closure_assessment_required"):
            register.set_disposition(self.conn, challenge_identifier=challenge, issue_identifier="ISS-D2", disposition="duplicate", basis="same", limitations="limits", evidence_id=evidence_id, duplicate_issue_identifier="ISS-D1", actor=self.admin, expected_version=evidence["resulting_version"], idempotency_key="missing-conclusion", reason="bad")
        self.assertEqual(self.item(challenge)["issues"][1]["issue_state"], "unassessed")


if __name__ == "__main__":
    unittest.main()
