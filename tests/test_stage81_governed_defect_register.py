"""Synthetic service coverage for the restricted Stage 81 foundation."""
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from api import governed_defect_register as register


class GovernedDefectRegisterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.conn = sqlite3.connect(f"{self.temp.name}/register.db")
        self.conn.row_factory = sqlite3.Row
        self.old_owner = os.environ.get(register.OWNER_USERNAME_ENV)
        os.environ[register.OWNER_USERNAME_ENV] = "owner-admin"

    def tearDown(self):
        self.conn.close()
        self.temp.cleanup()
        if self.old_owner is None:
            os.environ.pop(register.OWNER_USERNAME_ENV, None)
        else:
            os.environ[register.OWNER_USERNAME_ENV] = self.old_owner

    def fixture(self, identifier="CDE-DEF-SYNTHETIC-001"):
        """Test-only direct seed; no application admission path exists."""
        register.ensure_tables(self.conn)
        now = "2026-01-01T00:00:00Z"
        cursor = self.conn.execute(
            """INSERT INTO governed_defect_register_entries
            (entry_identifier,title,description,affected_component,observed_behavior,
             expected_behavior,expectation_source,reporter_source,lifecycle_state,
             assessment_classification,priority,owner_reference,impact_status,
             deferral_json,closure_json,preservation_hold_json,retention_review_json,
             active_action_json,synthetic_attestation_json,version,created_at,created_by,
             updated_at,updated_by)
             VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (identifier, "Synthetic fixture", "No real report content.", "synthetic",
             "observed", "expected", "synthetic test", "synthetic test",
             "reported", "unassessed", "unprioritised", None, "not_performed", None,
             None, None, None, None, "fixture-only", 1, now, "fixture-seed", now,
             "fixture-seed"),
        )
        item = {"id": cursor.lastrowid, "entry_identifier": identifier}
        register._event(self.conn, item, event_type="fixture_seeded", actor="fixture-seed",
                        reason="isolated_synthetic_fixture", prior_version=0,
                        resulting_version=1, details={"synthetic_only": True})
        self.conn.commit()
        return identifier

    def item(self, entry):
        return register.get_entry(self.conn, entry)

    def reference(self, entry, version, relation, value, key, steps, verification_binding=None):
        return register.add_reference(
            self.conn, entry_identifier=entry, reference_type="git_commit",
            reference_value=value, relation=relation, neutral_label=f"synthetic {relation}",
            supplier_identity="operator assertion", validation_steps=steps, actor="admin-a",
            expected_version=version, idempotency_key=key, reason="synthetic reference",
            verification_binding=verification_binding,
        )

    @staticmethod
    def checks(*passed):
        return [{"step": step, "status": "passed" if step in passed else "not_performed",
                 "validated_at": "2026-01-02T00:00:00Z", "limits": "synthetic only"}
                for step in sorted(register.VALIDATION_STEPS)]

    @staticmethod
    def verification_binding(action, execution_reference_id, artifact_value):
        return {
            "action_id": action["action_id"],
            "action_agreed_version": action["agreed_version"],
            "acceptance_criteria_identity": action["acceptance_criteria_identity"],
            "execution_reference_id": execution_reference_id,
            "artifact_reference_type": "git_commit",
            "artifact_reference_value": artifact_value,
        }

    def action_ready(self):
        entry = self.fixture()
        r = register.assess(self.conn, entry_identifier=entry, classification="confirmed_defect",
                            assessment_reason="synthetically reproduced", checked_scope="synthetic only",
                            limitations="fixture", actor="admin-a", expected_version=1,
                            idempotency_key="assess")
        r = self.reference(entry, r["resulting_version"], "action_target", "action-commit", "action-ref",
                           self.checks("relationship_substantiated"))
        action_reference_id = self.item(entry)["references"][-1]["id"]
        r = register.transition(self.conn, entry_identifier=entry, new_state="action_agreed",
                                reason="synthetic action", actor="admin-a",
                                expected_version=r["resulting_version"], idempotency_key="agree",
                                action_scope="bounded corrective action",
                                acceptance_criteria=["criterion one", "criterion two"],
                                action_reference_id=action_reference_id)
        r = self.reference(entry, r["resulting_version"], "execution_evidence", "execution-commit",
                           "execution-ref", self.checks("relationship_substantiated"))
        execution_reference_id = self.item(entry)["references"][-1]["id"]
        r = register.transition(self.conn, entry_identifier=entry, new_state="awaiting_verification",
                                reason="substantiated synthetic execution", actor="admin-a",
                                expected_version=r["resulting_version"], idempotency_key="await",
                                execution_status="execution_substantiated",
                                execution_reference_id=execution_reference_id)
        action = self.item(entry)["active_action"]
        r = self.reference(entry, r["resulting_version"], "verification_evidence", "checked-artifact",
                           "artifact-ref", self.checks("relationship_substantiated",
                                                        "target_identity_or_content_verified"),
                           self.verification_binding(action, execution_reference_id, "checked-artifact"))
        artifact_reference_id = self.item(entry)["references"][-1]["id"]
        return entry, r, execution_reference_id, artifact_reference_id

    def test_general_admission_is_disabled_without_a_configurable_synthetic_bypass(self):
        with self.assertRaisesRegex(ValueError, "report_admission_disabled"):
            register.create_entry(self.conn, title="Claimed synthetic", description="content",
                                  affected_component="x", observed_behavior="x", expected_behavior="x",
                                  expectation_source="x", reporter_source="x", actor="admin-a",
                                  expected_version=0, idempotency_key="create",
                                  synthetic_attestation={"classification": "synthetic_non_sensitive", "attested": True})
        register.ensure_tables(self.conn)
        self.assertEqual(self.conn.execute("SELECT count(*) FROM governed_defect_register_entries").fetchone()[0], 0)

    def test_verified_closure_is_bound_to_action_execution_artifact_and_all_criteria(self):
        entry, r, execution_ref, artifact_ref = self.action_ready()
        action = self.item(entry)["active_action"]
        before = self.item(entry)
        with self.assertRaisesRegex(ValueError, "verification_execution_mismatch"):
            register.transition(self.conn, entry_identifier=entry, new_state="closed", reason="unrelated",
                                actor="admin-a", expected_version=r["resulting_version"], idempotency_key="bad-close",
                                execution_status="execution_substantiated", closure_outcome="correction_verified",
                                verification={"action_id": action["action_id"], "execution_reference_id": artifact_ref,
                                              "artifact_reference_id": artifact_ref,
                                              "criteria_results": {"criterion one": "passed", "criterion two": "passed"}})
        self.assertEqual(self.item(entry)["version"], before["version"])
        with self.assertRaisesRegex(ValueError, "verification_criteria_incomplete"):
            register.transition(self.conn, entry_identifier=entry, new_state="closed", reason="incomplete",
                                actor="admin-a", expected_version=r["resulting_version"], idempotency_key="incomplete-close",
                                execution_status="execution_substantiated", closure_outcome="correction_verified",
                                verification={"action_id": action["action_id"], "execution_reference_id": execution_ref,
                                              "artifact_reference_id": artifact_ref,
                                              "criteria_results": {"criterion one": "passed"}})
        closed = register.transition(self.conn, entry_identifier=entry, new_state="closed", reason="all checked",
                                     actor="admin-a", expected_version=r["resulting_version"], idempotency_key="close",
                                     execution_status="execution_substantiated", closure_outcome="correction_verified",
                                     verification={"action_id": action["action_id"], "execution_reference_id": execution_ref,
                                                   "artifact_reference_id": artifact_ref,
                                                   "criteria_results": {"criterion one": "passed", "criterion two": "passed"},
                                                   "review_claim_unverified": "claimed external review"})
        item = self.item(entry)
        self.assertEqual(item["lifecycle_state"], "closed")
        self.assertEqual(item["closure"]["verification"]["artifact_reference_id"], artifact_ref)
        self.assertEqual(closed["resulting_version"], r["resulting_version"] + 1)

    def test_fully_validated_unrelated_artifact_cannot_close_or_partially_write(self):
        entry, r, execution_ref, artifact_ref = self.action_ready()
        item = self.item(entry)
        # Simulates a retained, pre-binding same-entry artifact: generic checks
        # alone must never establish its relationship to this active action.
        cursor = self.conn.execute(
            """INSERT INTO governed_defect_register_references
            (entry_id,entry_identifier,reference_type,reference_value,relation,neutral_label,
             supplier_identity,validator_identity,validation_steps_json,verification_binding_json,
             created_at,created_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (item["id"], entry, "git_commit", "unrelated-artifact", "verification_evidence",
             "synthetic unrelated artifact", "operator assertion", None,
             register._json(self.checks("relationship_substantiated", "target_identity_or_content_verified")),
             None, "2026-01-02T00:00:00Z", "fixture-seed"),
        )
        self.conn.commit()
        unrelated_artifact = cursor.lastrowid
        before = self.item(entry)
        action = before["active_action"]
        with self.assertRaisesRegex(ValueError, "verification_binding_mismatch"):
            register.transition(self.conn, entry_identifier=entry, new_state="closed", reason="unrelated artifact",
                                actor="admin-a", expected_version=before["version"], idempotency_key="unrelated-artifact-close",
                                execution_status="execution_substantiated", closure_outcome="correction_verified",
                                verification={"action_id": action["action_id"], "execution_reference_id": execution_ref,
                                              "artifact_reference_id": unrelated_artifact,
                                              "criteria_results": {criterion: "passed" for criterion in action["acceptance_criteria"]}})
        after_rejection = self.item(entry)
        self.assertEqual(after_rejection["version"], before["version"])
        self.assertEqual(len(after_rejection["history"]), len(before["history"]))
        closed = register.transition(self.conn, entry_identifier=entry, new_state="closed", reason="bound artifact",
                                     actor="admin-a", expected_version=after_rejection["version"], idempotency_key="bound-artifact-close",
                                     execution_status="execution_substantiated", closure_outcome="correction_verified",
                                     verification={"action_id": action["action_id"], "execution_reference_id": execution_ref,
                                                   "artifact_reference_id": artifact_ref,
                                                   "criteria_results": {criterion: "passed" for criterion in action["acceptance_criteria"]}})
        self.assertEqual(closed["resulting_version"], before["version"] + 1)

    def test_superseded_action_cannot_be_used_for_a_later_verified_closure(self):
        entry, r, _execution_ref, _artifact_ref = self.action_ready()
        old_action = self.item(entry)["active_action"]
        r = register.transition(self.conn, entry_identifier=entry, new_state="under_assessment",
                                reason="new synthetic evidence", actor="admin-a",
                                expected_version=r["resulting_version"], idempotency_key="return")
        r = self.reference(entry, r["resulting_version"], "action_target", "replacement-action",
                           "replacement-ref", self.checks("relationship_substantiated"))
        replacement_ref = self.item(entry)["references"][-1]["id"]
        r = register.transition(self.conn, entry_identifier=entry, new_state="action_agreed",
                                reason="replacement action", actor="admin-a",
                                expected_version=r["resulting_version"], idempotency_key="replace",
                                action_scope="replacement", acceptance_criteria=["replacement criterion"],
                                action_reference_id=replacement_ref)
        new_action = self.item(entry)["active_action"]
        self.assertNotEqual(new_action["action_id"], old_action["action_id"])
        r = self.reference(entry, r["resulting_version"], "execution_evidence", "replacement-execution",
                           "replacement-execution-ref", self.checks("relationship_substantiated"))
        execution_ref = self.item(entry)["references"][-1]["id"]
        r = register.transition(self.conn, entry_identifier=entry, new_state="awaiting_verification",
                                reason="replacement execution", actor="admin-a",
                                expected_version=r["resulting_version"], idempotency_key="replacement-await",
                                execution_status="execution_substantiated", execution_reference_id=execution_ref)
        new_action = self.item(entry)["active_action"]
        r = self.reference(entry, r["resulting_version"], "verification_evidence", "replacement-artifact",
                           "replacement-artifact-ref", self.checks("relationship_substantiated", "target_identity_or_content_verified"),
                           self.verification_binding(new_action, execution_ref, "replacement-artifact"))
        artifact_ref = self.item(entry)["references"][-1]["id"]
        with self.assertRaisesRegex(ValueError, "verification_action_stale"):
            register.transition(self.conn, entry_identifier=entry, new_state="closed", reason="old action",
                                actor="admin-a", expected_version=r["resulting_version"], idempotency_key="stale-action-close",
                                execution_status="execution_substantiated", closure_outcome="correction_verified",
                                verification={"action_id": old_action["action_id"], "execution_reference_id": execution_ref,
                                              "artifact_reference_id": artifact_ref,
                                              "criteria_results": {"replacement criterion": "passed"}})

    def test_unverified_identity_claims_cannot_elevate_validation_or_review(self):
        entry = self.fixture()
        with self.assertRaisesRegex(ValueError, "unverified_claim_elevation_rejected"):
            self.reference(entry, 1, "assessment_evidence", "claim-ref", "bad-validator", [{
                "step": "syntax_validated", "status": "passed", "validator_identity": "owner-admin",
                "validated_at": "2026-01-02T00:00:00Z", "limits": "claimed"}])
        self.assertEqual(self.item(entry)["version"], 1)
        r = self.reference(entry, 1, "assessment_evidence", "claim-ref", "claim-validator", [{
            "step": "syntax_validated", "status": "passed", "validator_claim_unverified": "named claimant",
            "validated_at": "2026-01-02T00:00:00Z", "limits": "format only"}])
        step = self.item(entry)["references"][0]["validation_steps"][0]
        self.assertEqual(step["recorded_by_actor"], "admin-a")
        self.assertEqual(step["validator_claim_unverified"], "named claimant")
        self.assertEqual(r["resulting_version"], 2)

    def test_impact_requires_basis_and_limits_and_retention_schedule_is_derived(self):
        entry = self.fixture()
        with self.assertRaisesRegex(ValueError, "basis_and_limits_required"):
            register.add_impact(self.conn, entry_identifier=entry, target_reference="synthetic-target",
                                status="assessed_unaffected", assessment_basis="checked", actor="admin-a",
                                expected_version=1, idempotency_key="bad-impact", reason="missing limits")
        r = register.set_owner_priority_deferral(self.conn, entry_identifier=entry, actor="admin-a",
                                                 expected_version=1, idempotency_key="defer", reason="defer",
                                                 deferral={"owner_reference": "admin-b", "reason": "wait",
                                                            "review_on": "2026-01-15T00:00:00Z", "review_trigger": "new evidence"})
        with patch.object(register, "utc_now", return_value="2026-01-10T00:00:00Z"):
            with self.assertRaisesRegex(ValueError, "retention_review_not_due"):
                register.record_retention_review(self.conn, entry_identifier=entry, what_remains_necessary="fixture",
                                                 actor="admin-a", expected_version=r["resulting_version"],
                                                 idempotency_key="too-early", reason="early")
        with patch.object(register, "utc_now", return_value="2026-01-15T00:00:00Z"):
            r = register.record_retention_review(self.conn, entry_identifier=entry, what_remains_necessary="fixture",
                                                 actor="admin-a", expected_version=r["resulting_version"],
                                                 idempotency_key="due", reason="due")
        item = self.item(entry)
        self.assertEqual(item["retention_review"]["next_review_date"], "2026-04-15T00:00:00Z")
        self.assertEqual(item["retention_review"]["active_deferral_trigger"], "new evidence")

    def test_owner_only_hold_and_exact_retry_receipt_remain_atomic(self):
        entry = self.fixture()
        with self.assertRaisesRegex(ValueError, "owner_authority_required"):
            register.set_hold(self.conn, entry_identifier=entry, active=True, scope="scope", review_date="2026-12-01T00:00:00Z",
                              reason="claim", actor="admin-a", expected_version=1, idempotency_key="hold")
        r = register.set_hold(self.conn, entry_identifier=entry, active=True, scope="scope", review_date="2026-12-01T00:00:00Z",
                              reason="owner decision", actor="owner-admin", expected_version=1, idempotency_key="owner-hold")
        replay = register.set_hold(self.conn, entry_identifier=entry, active=True, scope="scope", review_date="2026-12-01T00:00:00Z",
                                   reason="owner decision", actor="owner-admin", expected_version=1, idempotency_key="owner-hold")
        self.assertTrue(replay["historical_receipt"])
        self.assertEqual(r["resulting_version"], 2)
        self.assertTrue(self.item(entry)["preservation_hold"]["active"])
