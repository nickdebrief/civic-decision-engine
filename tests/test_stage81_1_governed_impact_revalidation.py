"""Synthetic service coverage for Stage 81.1 downstream revalidation."""

from tests.test_stage81_governed_defect_register import GovernedDefectRegisterTests
from api import governed_defect_register as register


class Stage811ImpactRevalidationTests(GovernedDefectRegisterTests):
    def reference(self, entry, version, relation, value, key, steps, verification_binding=None,
                  revalidation_binding=None, target_binding=None, supersession_binding=None):
        if relation == "impact_target" and target_binding is None:
            target_binding = {
                "target_reference_type": "git_commit", "target_reference_value": value,
                "identity_kind": "exact_reference", "identity": value,
                "observed_at": "2026-01-03T00:00:00Z",
            }
        return register.add_reference(
            self.conn, entry_identifier=entry, reference_type="git_commit",
            reference_value=value, relation=relation, neutral_label=f"synthetic {relation}",
            supplier_identity="operator assertion", validation_steps=steps, actor="admin-a",
            expected_version=version, idempotency_key=key, reason="synthetic reference",
            verification_binding=verification_binding, revalidation_binding=revalidation_binding,
            target_binding=target_binding, supersession_binding=supersession_binding,
        )

    def _close_original(self):
        entry, receipt, execution_ref, artifact_ref = self.action_ready()
        action = self.item(entry)["active_action"]
        receipt = register.transition(
            self.conn, entry_identifier=entry, new_state="closed", reason="original verified",
            actor="admin-a", expected_version=receipt["resulting_version"], idempotency_key="original-close",
            execution_status="execution_substantiated", closure_outcome="correction_verified",
            verification={"action_id": action["action_id"], "execution_reference_id": execution_ref,
                          "artifact_reference_id": artifact_ref,
                          "criteria_results": {criterion: "passed" for criterion in action["acceptance_criteria"]}},
        )
        return entry, receipt, action, execution_ref

    def _requirement(self, *, target="target-version-1", criteria=None, predecessor=None, supersession_ref=None,
                     linked_workflow_requires_approval=False, target_identity_kind="exact_reference",
                     target_identity=None, observed_at="2026-01-03T00:00:00Z", target_binding=None):
        entry, receipt, action, execution_ref = self._close_original()
        receipt = register.add_impact(
            self.conn, entry_identifier=entry, target_reference=target, status="assessed_affected",
            assessment_basis="synthetic downstream assessment", assessment_limits="synthetic fixture only",
            follow_up_action="revalidate", owner_reference="admin-b", review_trigger="after correction",
            actor="admin-a", expected_version=receipt["resulting_version"], idempotency_key="impact", reason="impact recorded",
        )
        impact_id = self.item(entry)["impacts"][-1]["id"]
        identity = target if target_identity is None else target_identity
        receipt = self.reference(
            entry, receipt["resulting_version"], "impact_target", target, "target-ref",
            self.checks("relationship_substantiated", "target_identity_or_content_verified"),
            target_binding=target_binding or {
                "target_reference_type": "git_commit", "target_reference_value": target,
                "identity_kind": target_identity_kind, "identity": identity, "observed_at": observed_at,
            },
        )
        target_reference_id = self.item(entry)["references"][-1]["id"]
        authority_reference_id = None
        if linked_workflow_requires_approval:
            receipt = self.reference(entry, receipt["resulting_version"], "authority", "workflow-authority", "authority-ref", self.checks("relationship_substantiated"))
            authority_reference_id = self.item(entry)["references"][-1]["id"]
        receipt = register.create_revalidation_requirement(
            self.conn, entry_identifier=entry, impact_id=impact_id, target_reference_id=target_reference_id,
            target_identity_kind=target_identity_kind, target_identity=identity,
            observed_at=observed_at, assessment_scope="synthetic target",
            assessment_basis="synthetic assessment", assessment_limits="fixture limitations",
            acceptance_criteria=criteria or ["downstream criterion"], owner_reference="admin-b",
            due_at="2026-01-10T00:00:00Z", linked_workflow_requires_approval=linked_workflow_requires_approval,
            authority_reference_id=authority_reference_id,
            predecessor_requirement_identifier=predecessor, supersession_reference_id=supersession_ref,
            actor="admin-a", expected_version=receipt["resulting_version"], idempotency_key="requirement", reason="downstream requirement",
        )
        requirement = self.item(entry)["revalidations"][-1]
        return entry, receipt, action, execution_ref, requirement

    @staticmethod
    def _binding(requirement):
        action = requirement["origin_action"]
        return {
            "requirement_identifier": requirement["requirement_identifier"],
            "origin_action_id": action["action_id"],
            "origin_action_agreed_version": action["agreed_version"],
            "origin_acceptance_criteria_identity": action["acceptance_criteria_identity"],
            "execution_reference_id": requirement["execution_reference_id"],
            "target_reference_id": requirement["target_reference_id"],
            "target_identity": requirement["target_identity"],
            "criteria_identity": requirement["criteria_identity"],
        }

    def _await(self, entry, receipt, requirement):
        return register.transition_revalidation(
            self.conn, entry_identifier=entry, requirement_identifier=requirement["requirement_identifier"],
            outcome="awaiting_revalidation", actor="admin-a", expected_version=receipt["resulting_version"],
            idempotency_key="await-downstream", reason="ready for synthetic check",
        )

    def _artifact(self, entry, receipt, requirement, value="downstream-artifact"):
        binding = self._binding(requirement)
        binding.update({"artifact_reference_type": "git_commit", "artifact_reference_value": value})
        receipt = register.add_reference(
            self.conn, entry_identifier=entry, reference_type="git_commit", reference_value=value,
            relation="revalidation_evidence", neutral_label="synthetic revalidation artifact",
            supplier_identity="synthetic supplier", validation_steps=self.checks(
                "relationship_substantiated", "target_identity_or_content_verified"),
            revalidation_binding=binding, actor="admin-a", expected_version=receipt["resulting_version"],
            idempotency_key=f"artifact-{value}", reason="synthetic artifact",
        )
        return receipt, self.item(entry)["references"][-1]["id"]

    def _supersession(self, entry, receipt, predecessor, value="later-correction"):
        return self.reference(
            entry, receipt["resulting_version"], "supersedes", value, f"supersedes-{value}",
            self.checks("relationship_substantiated"),
            supersession_binding={
                "predecessor_requirement_identifier": predecessor["requirement_identifier"],
                "predecessor_origin_action_id": predecessor["origin_action"]["action_id"],
                "successor_origin_action_id": self.item(entry)["active_action"]["action_id"],
                "later_correction_reference_type": "git_commit",
                "later_correction_reference_value": value,
            },
        )

    def _later_substantiated_action(self, entry, receipt, *, criteria=None):
        receipt = register.transition(
            self.conn, entry_identifier=entry, new_state="under_assessment", reason="later correction assessed",
            actor="admin-a", expected_version=receipt["resulting_version"], idempotency_key="later-assessment",
        )
        receipt = self.reference(
            entry, receipt["resulting_version"], "action_target", "later-action-commit", "later-action-ref",
            self.checks("relationship_substantiated"),
        )
        action_reference_id = self.item(entry)["references"][-1]["id"]
        receipt = register.transition(
            self.conn, entry_identifier=entry, new_state="action_agreed", reason="later correction agreed",
            actor="admin-a", expected_version=receipt["resulting_version"], idempotency_key="later-agree",
            action_scope="later bounded correction", acceptance_criteria=criteria or ["criterion one", "criterion two"],
            action_reference_id=action_reference_id,
        )
        receipt = self.reference(
            entry, receipt["resulting_version"], "execution_evidence", "later-execution-commit", "later-execution-ref",
            self.checks("relationship_substantiated"),
        )
        execution_reference_id = self.item(entry)["references"][-1]["id"]
        receipt = register.transition(
            self.conn, entry_identifier=entry, new_state="awaiting_verification", reason="later execution substantiated",
            actor="admin-a", expected_version=receipt["resulting_version"], idempotency_key="later-await",
            execution_status="execution_substantiated", execution_reference_id=execution_reference_id,
        )
        return receipt, self.item(entry)["active_action"]

    def test_exact_bound_chain_passes_only_for_its_requirement(self):
        entry, receipt, _action, _execution, requirement = self._requirement()
        receipt = self._await(entry, receipt, requirement)
        receipt, artifact_id = self._artifact(entry, receipt, requirement)
        result = register.transition_revalidation(
            self.conn, entry_identifier=entry, requirement_identifier=requirement["requirement_identifier"],
            outcome="revalidation_passed", actor="admin-a", expected_version=receipt["resulting_version"],
            idempotency_key="downstream-pass", reason="criteria passed",
            verification={"artifact_reference_id": artifact_id,
                          "criteria_results": {"downstream criterion": "passed"}},
        )
        item = self.item(entry)
        self.assertEqual(item["revalidations"][0]["outcome"], "revalidation_passed")
        self.assertEqual(result["resulting_version"], receipt["resulting_version"] + 1)
        self.assertTrue(register.downstream_work_outstanding(self.conn, entry) is False)

    def test_unrelated_fully_validated_artifact_rejects_atomically(self):
        entry, receipt, _action, _execution, requirement = self._requirement()
        receipt = self._await(entry, receipt, requirement)
        item = self.item(entry)
        cursor = self.conn.execute(
            """INSERT INTO governed_defect_register_references
            (entry_id,entry_identifier,reference_type,reference_value,relation,neutral_label,
             supplier_identity,validator_identity,validation_steps_json,verification_binding_json,
             revalidation_binding_json,created_at,created_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (item["id"], entry, "git_commit", "unrelated-downstream", "revalidation_evidence",
             "synthetic unrelated", "synthetic supplier", None,
             register._json(self.checks("relationship_substantiated", "target_identity_or_content_verified")),
             None, None, "2026-01-03T00:00:00Z", "fixture-seed"),
        )
        self.conn.commit()
        before = self.item(entry)
        with self.assertRaisesRegex(ValueError, "revalidation_binding_mismatch"):
            register.transition_revalidation(
                self.conn, entry_identifier=entry, requirement_identifier=requirement["requirement_identifier"],
                outcome="revalidation_passed", actor="admin-a", expected_version=receipt["resulting_version"],
                idempotency_key="bad-downstream-pass", reason="unrelated evidence",
                verification={"artifact_reference_id": cursor.lastrowid,
                              "criteria_results": {"downstream criterion": "passed"}},
            )
        after = self.item(entry)
        self.assertEqual(after["version"], before["version"])
        self.assertEqual(after["revalidations"][0]["outcome"], "awaiting_revalidation")
        self.assertEqual(len(after["history"]), len(before["history"]))

    def test_mismatched_execution_target_or_criteria_binding_cannot_be_added(self):
        entry, receipt, _action, _execution, requirement = self._requirement()
        receipt = self._await(entry, receipt, requirement)
        for suffix, changed in (
            ("execution", {"execution_reference_id": 99999}),
            ("target", {"target_identity": "other-target"}),
            ("criteria", {"criteria_identity": "0" * 64}),
        ):
            binding = self._binding(requirement)
            binding.update(changed)
            binding.update({"artifact_reference_type": "git_commit", "artifact_reference_value": f"bad-{suffix}"})
            before = self.item(entry)
            with self.assertRaisesRegex(ValueError, "revalidation_binding_mismatch"):
                register.add_reference(
                    self.conn, entry_identifier=entry, reference_type="git_commit", reference_value=f"bad-{suffix}",
                    relation="revalidation_evidence", neutral_label="bad synthetic binding",
                    supplier_identity="synthetic supplier", validation_steps=self.checks(
                        "relationship_substantiated", "target_identity_or_content_verified"),
                    revalidation_binding=binding, actor="admin-a", expected_version=receipt["resulting_version"],
                    idempotency_key=f"bad-binding-{suffix}", reason="wrong relationship",
                )
            self.assertEqual(self.item(entry)["version"], before["version"])

    def test_successor_makes_prior_result_historical_and_rejects_reuse(self):
        entry, receipt, _action, _execution, requirement = self._requirement()
        receipt = self._await(entry, receipt, requirement)
        receipt, artifact_id = self._artifact(entry, receipt, requirement, "prior-artifact")
        receipt = self.reference(
            entry, receipt["resulting_version"], "impact_target", "target-version-2", "target-v2-ref",
            self.checks("relationship_substantiated", "target_identity_or_content_verified"),
            target_binding={"target_reference_type": "git_commit", "target_reference_value": "target-version-2",
                            "identity_kind": "exact_reference", "identity": "target-version-2",
                            "observed_at": "2026-01-04T00:00:00Z"},
        )
        target_v2_reference_id = self.item(entry)["references"][-1]["id"]
        receipt = self._supersession(entry, receipt, requirement)
        supersession_reference_id = self.item(entry)["references"][-1]["id"]
        impact_id = self.item(entry)["impacts"][-1]["id"]
        receipt = register.create_revalidation_requirement(
            self.conn, entry_identifier=entry, impact_id=impact_id, target_reference_id=target_v2_reference_id,
            target_identity_kind="exact_reference", target_identity="target-version-2",
            observed_at="2026-01-04T00:00:00Z", assessment_scope="changed target",
            assessment_basis="later correction relation", assessment_limits="synthetic only",
            acceptance_criteria=["downstream criterion two"], owner_reference="admin-b",
            review_trigger="replacement checked", predecessor_requirement_identifier=requirement["requirement_identifier"],
            supersession_reference_id=supersession_reference_id, actor="admin-a",
            expected_version=receipt["resulting_version"], idempotency_key="successor", reason="target changed",
        )
        requirements = self.item(entry)["revalidations"]
        self.assertEqual(requirements[0]["outcome"], "superseded")
        self.assertEqual(requirements[1]["outcome"], "open")
        with self.assertRaisesRegex(ValueError, "revalidation_transition_invalid"):
            register.transition_revalidation(
                self.conn, entry_identifier=entry, requirement_identifier=requirement["requirement_identifier"],
                outcome="revalidation_passed", actor="admin-a", expected_version=receipt["resulting_version"],
                idempotency_key="reuse-prior", reason="prior artifact reuse",
                verification={"artifact_reference_id": artifact_id,
                              "criteria_results": {"downstream criterion": "passed"}},
            )
        self.assertTrue(register.downstream_work_outstanding(self.conn, entry))

    def test_non_passing_conclusion_keeps_obligations_and_historical_retry(self):
        entry, receipt, _action, _execution, requirement = self._requirement()
        evidence_reference_id = requirement["target_reference_id"]
        receipt = register.transition_revalidation(
            self.conn, entry_identifier=entry, requirement_identifier=requirement["requirement_identifier"],
            outcome="concluded_without_passing", actor="admin-a", expected_version=receipt["resulting_version"],
            idempotency_key="conclude", reason="target unavailable",
            conclusion={"assessment_limitations": "target unavailable in synthetic fixture",
                        "unresolved_consequences": "downstream assurance remains incomplete",
                        "evidence_reference_ids": [evidence_reference_id],
                        "follow_up_disposition": {"work_remains": True, "description": "await target recovery",
                                                  "owner_reference": "admin-b", "review_trigger": "target becomes available"}},
        )
        replay = register.transition_revalidation(
            self.conn, entry_identifier=entry, requirement_identifier=requirement["requirement_identifier"],
            outcome="concluded_without_passing", actor="admin-a", expected_version=receipt["resulting_version"] - 1,
            idempotency_key="conclude", reason="target unavailable",
            conclusion={"assessment_limitations": "target unavailable in synthetic fixture",
                        "unresolved_consequences": "downstream assurance remains incomplete",
                        "evidence_reference_ids": [evidence_reference_id],
                        "follow_up_disposition": {"work_remains": True, "description": "await target recovery",
                                                  "owner_reference": "admin-b", "review_trigger": "target becomes available"}},
        )
        current = self.item(entry)["revalidations"][0]
        self.assertTrue(replay["historical_receipt"])
        self.assertEqual(current["outcome"], "concluded_without_passing")
        self.assertEqual(current["conclusion"]["follow_up_disposition"]["owner_reference"], "admin-b")
        self.assertTrue(register.downstream_work_outstanding(self.conn, entry))

    def test_non_passing_conclusion_cannot_replace_linked_workflow_approval(self):
        entry, receipt, _action, _execution, requirement = self._requirement(linked_workflow_requires_approval=True)
        before = self.item(entry)
        with self.assertRaisesRegex(ValueError, "revalidation_linked_approval_required"):
            register.transition_revalidation(
                self.conn, entry_identifier=entry, requirement_identifier=requirement["requirement_identifier"],
                outcome="concluded_without_passing", actor="admin-a", expected_version=receipt["resulting_version"],
                idempotency_key="blocked-conclusion", reason="attempted substitute",
                conclusion={"assessment_limitations": "synthetic limit", "unresolved_consequences": "unresolved",
                            "evidence_reference_ids": [requirement["target_reference_id"]],
                            "follow_up_disposition": {"work_remains": True, "description": "follow up",
                                                      "owner_reference": "admin-b", "review_trigger": "new evidence"}},
            )
        self.assertEqual(self.item(entry)["version"], before["version"])
        self.assertEqual(self.item(entry)["revalidations"][0]["outcome"], "open")

    def test_failed_revalidation_needs_bound_evidence_and_follow_up(self):
        entry, receipt, _action, _execution, requirement = self._requirement()
        receipt = self._await(entry, receipt, requirement)
        receipt, artifact_id = self._artifact(entry, receipt, requirement, "failed-artifact")
        before = self.item(entry)
        with self.assertRaisesRegex(ValueError, "failure_details_required"):
            register.transition_revalidation(
                self.conn, entry_identifier=entry, requirement_identifier=requirement["requirement_identifier"],
                outcome="revalidation_failed", actor="admin-a", expected_version=receipt["resulting_version"],
                idempotency_key="failed-without-details", reason="criterion failed",
                verification={"artifact_reference_id": artifact_id,
                              "criteria_results": {"downstream criterion": "failed"}},
            )
        self.assertEqual(self.item(entry)["version"], before["version"])
        result = register.transition_revalidation(
            self.conn, entry_identifier=entry, requirement_identifier=requirement["requirement_identifier"],
            outcome="revalidation_failed", actor="admin-a", expected_version=receipt["resulting_version"],
            idempotency_key="failed-with-details", reason="criterion failed",
            verification={"artifact_reference_id": artifact_id,
                          "criteria_results": {"downstream criterion": "failed"}},
            conclusion={"assessment_limitations": "synthetic failed check", "unresolved_consequences": "target remains unverified",
                        "follow_up_disposition": {"work_remains": True, "description": "repeat after repair",
                                                  "owner_reference": "admin-b", "due_at": "2026-01-12T00:00:00Z"}},
        )
        current = self.item(entry)["revalidations"][0]
        self.assertEqual(current["outcome"], "revalidation_failed")
        self.assertEqual(current["outcome_details"]["artifact_reference_id"], artifact_id)
        self.assertEqual(result["resulting_version"], receipt["resulting_version"] + 1)

    def test_snapshot_identity_requires_immutable_target_binding(self):
        digest = "c" * 64
        entry, receipt, _action, _execution, requirement = self._requirement(
            target="mutable-target", target_identity_kind="snapshot_digest", target_identity=digest,
            observed_at="2026-01-05T00:00:00Z",
        )
        before = self.item(entry)
        with self.assertRaisesRegex(ValueError, "target_binding_mismatch"):
            register.create_revalidation_requirement(
                self.conn, entry_identifier=entry, impact_id=before["impacts"][-1]["id"],
                target_reference_id=requirement["target_reference_id"], target_identity_kind="snapshot_digest",
                target_identity="a" * 64, observed_at="2026-01-05T00:00:00Z",
                assessment_scope="synthetic mismatch", assessment_basis="arbitrary digest",
                assessment_limits="fixture", acceptance_criteria=["other criterion"], owner_reference="admin-b",
                due_at="2026-01-12T00:00:00Z", actor="admin-a", expected_version=receipt["resulting_version"],
                idempotency_key="arbitrary-digest", reason="reject assertion",
            )
        self.assertEqual(self.item(entry)["version"], before["version"])
        self.assertEqual(len(self.item(entry)["revalidations"]), 1)
        receipt = self.reference(
            entry, receipt["resulting_version"], "impact_target", "different-mutable-target", "different-target-ref",
            self.checks("relationship_substantiated", "target_identity_or_content_verified"),
            target_binding={"target_reference_type": "git_commit", "target_reference_value": "different-mutable-target",
                            "identity_kind": "snapshot_digest", "identity": "d" * 64,
                            "observed_at": "2026-01-05T00:00:00Z"},
        )
        different_target_id = self.item(entry)["references"][-1]["id"]
        before = self.item(entry)
        with self.assertRaisesRegex(ValueError, "target_binding_mismatch"):
            register.create_revalidation_requirement(
                self.conn, entry_identifier=entry, impact_id=before["impacts"][-1]["id"],
                target_reference_id=different_target_id, target_identity_kind="snapshot_digest", target_identity=digest,
                observed_at="2026-01-05T00:00:00Z", assessment_scope="wrong evidence",
                assessment_basis="different content", assessment_limits="fixture", acceptance_criteria=["other criterion"],
                owner_reference="admin-b", due_at="2026-01-12T00:00:00Z", actor="admin-a",
                expected_version=receipt["resulting_version"], idempotency_key="different-content", reason="reject different evidence",
            )
        item = self.item(entry)
        self.assertEqual(item["version"], before["version"])
        self.assertEqual(item["revalidations"][0]["target_identity"], digest)
        self.assertEqual(item["references"][-1]["target_binding"]["identity"], "d" * 64)

    def test_unbound_or_wrong_supersession_cannot_retire_predecessor(self):
        entry, receipt, _action, _execution, predecessor = self._requirement()
        receipt = self.reference(
            entry, receipt["resulting_version"], "impact_target", "target-version-2", "target-v2-ref",
            self.checks("relationship_substantiated", "target_identity_or_content_verified"),
            target_binding={"target_reference_type": "git_commit", "target_reference_value": "target-version-2",
                            "identity_kind": "exact_reference", "identity": "target-version-2",
                            "observed_at": "2026-01-04T00:00:00Z"},
        )
        target_id = self.item(entry)["references"][-1]["id"]
        item = self.item(entry)
        cursor = self.conn.execute(
            """INSERT INTO governed_defect_register_references
            (entry_id,entry_identifier,reference_type,reference_value,relation,neutral_label,supplier_identity,
             validator_identity,validation_steps_json,created_at,created_by) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (item["id"], entry, "git_commit", "unbound-later-correction", "supersedes", "unbound synthetic",
             "synthetic supplier", None, register._json(self.checks("relationship_substantiated")),
             "2026-01-04T00:00:00Z", "fixture-seed"),
        )
        self.conn.commit()
        before = self.item(entry)
        with self.assertRaisesRegex(ValueError, "supersession_binding_mismatch"):
            register.create_revalidation_requirement(
                self.conn, entry_identifier=entry, impact_id=before["impacts"][-1]["id"], target_reference_id=target_id,
                target_identity_kind="exact_reference", target_identity="target-version-2", observed_at="2026-01-04T00:00:00Z",
                assessment_scope="changed target", assessment_basis="unbound reference", assessment_limits="fixture",
                acceptance_criteria=["criterion two"], owner_reference="admin-b", review_trigger="review",
                predecessor_requirement_identifier=predecessor["requirement_identifier"], supersession_reference_id=cursor.lastrowid,
                actor="admin-a", expected_version=receipt["resulting_version"], idempotency_key="unbound-successor", reason="reject unbound",
            )
        after = self.item(entry)
        self.assertEqual(after["version"], before["version"])
        self.assertEqual(after["revalidations"][0]["outcome"], "open")
        with self.assertRaisesRegex(ValueError, "supersession_binding_mismatch"):
            self.reference(
                entry, after["version"], "supersedes", "wrong-predecessor-correction", "wrong-predecessor-ref",
                self.checks("relationship_substantiated"),
                supersession_binding={
                    "predecessor_requirement_identifier": predecessor["requirement_identifier"],
                    "predecessor_origin_action_id": "wrong-action",
                    "successor_origin_action_id": predecessor["origin_action"]["action_id"],
                    "later_correction_reference_type": "git_commit",
                    "later_correction_reference_value": "wrong-predecessor-correction",
                },
            )
        self.assertEqual(self.item(entry)["version"], after["version"])

    def test_later_correction_can_succeed_with_same_target_and_criteria(self):
        entry, receipt, _action, _execution, predecessor = self._requirement()
        receipt, new_action = self._later_substantiated_action(entry, receipt)
        receipt = self._supersession(entry, receipt, predecessor, "later-correction-same-target")
        supersession_reference_id = self.item(entry)["references"][-1]["id"]
        receipt = register.create_revalidation_requirement(
            self.conn, entry_identifier=entry, impact_id=self.item(entry)["impacts"][-1]["id"],
            target_reference_id=predecessor["target_reference_id"], target_identity_kind="exact_reference",
            target_identity="target-version-1", observed_at="2026-01-03T00:00:00Z",
            assessment_scope="later correction", assessment_basis="new action changes applicability", assessment_limits="fixture",
            acceptance_criteria=["downstream criterion"], owner_reference="admin-b", review_trigger="later correction checked",
            predecessor_requirement_identifier=predecessor["requirement_identifier"], supersession_reference_id=supersession_reference_id,
            actor="admin-a", expected_version=receipt["resulting_version"], idempotency_key="same-target-successor", reason="later correction",
        )
        requirements = self.item(entry)["revalidations"]
        self.assertEqual(requirements[0]["outcome"], "superseded")
        self.assertEqual(requirements[1]["origin_action"]["action_id"], new_action["action_id"])
        self.assertEqual(requirements[1]["supersession_reference_id"], supersession_reference_id)
        with self.assertRaisesRegex(ValueError, "supersession_reused"):
            register.create_revalidation_requirement(
                self.conn, entry_identifier=entry, impact_id=self.item(entry)["impacts"][-1]["id"],
                target_reference_id=predecessor["target_reference_id"], target_identity_kind="exact_reference",
                target_identity="target-version-1", observed_at="2026-01-03T00:00:00Z",
                assessment_scope="reused", assessment_basis="reused relationship", assessment_limits="fixture",
                acceptance_criteria=["downstream criterion"], owner_reference="admin-b", review_trigger="later correction checked",
                predecessor_requirement_identifier=predecessor["requirement_identifier"], supersession_reference_id=supersession_reference_id,
                actor="admin-a", expected_version=receipt["resulting_version"], idempotency_key="reused-supersession", reason="reject reuse",
            )

    def test_criteria_change_successor_is_distinct_from_historical_result(self):
        entry, receipt, _action, _execution, predecessor = self._requirement()
        receipt = self._supersession(entry, receipt, predecessor, "later-criteria-correction")
        successor = register.create_revalidation_requirement(
            self.conn, entry_identifier=entry, impact_id=self.item(entry)["impacts"][-1]["id"],
            target_reference_id=predecessor["target_reference_id"], target_identity_kind="exact_reference",
            target_identity="target-version-1", observed_at="2026-01-03T00:00:00Z",
            assessment_scope="criteria changed", assessment_basis="later agreed criteria", assessment_limits="fixture",
            acceptance_criteria=["replacement criterion"], owner_reference="admin-b", review_trigger="criteria reviewed",
            predecessor_requirement_identifier=predecessor["requirement_identifier"],
            supersession_reference_id=self.item(entry)["references"][-1]["id"], actor="admin-a",
            expected_version=receipt["resulting_version"], idempotency_key="criteria-successor", reason="criteria changed",
        )
        requirements = self.item(entry)["revalidations"]
        self.assertEqual(requirements[0]["outcome"], "superseded")
        self.assertEqual(requirements[1]["criteria"], ["replacement criterion"])
        self.assertEqual(successor["resulting_version"], receipt["resulting_version"] + 1)

    def test_superseded_and_not_required_are_not_outstanding(self):
        entry, receipt, _action, _execution, predecessor = self._requirement()
        receipt = self.reference(
            entry, receipt["resulting_version"], "impact_target", "target-version-2", "status-target-ref",
            self.checks("relationship_substantiated", "target_identity_or_content_verified"),
            target_binding={"target_reference_type": "git_commit", "target_reference_value": "target-version-2",
                            "identity_kind": "exact_reference", "identity": "target-version-2",
                            "observed_at": "2026-01-04T00:00:00Z"},
        )
        target_id = self.item(entry)["references"][-1]["id"]
        receipt = self._supersession(entry, receipt, predecessor, "later-correction-status")
        successor = register.create_revalidation_requirement(
            self.conn, entry_identifier=entry, impact_id=self.item(entry)["impacts"][-1]["id"], target_reference_id=target_id,
            target_identity_kind="exact_reference", target_identity="target-version-2", observed_at="2026-01-04T00:00:00Z",
            assessment_scope="changed", assessment_basis="later", assessment_limits="fixture", acceptance_criteria=["criterion two"],
            owner_reference="admin-b", review_trigger="review", predecessor_requirement_identifier=predecessor["requirement_identifier"],
            supersession_reference_id=self.item(entry)["references"][-1]["id"], actor="admin-a",
            expected_version=receipt["resulting_version"], idempotency_key="status-successor", reason="replace",
        )
        successor_id = self.item(entry)["revalidations"][-1]["requirement_identifier"]
        register.transition_revalidation(
            self.conn, entry_identifier=entry, requirement_identifier=successor_id, outcome="not_required", actor="admin-a",
            expected_version=successor["resulting_version"], idempotency_key="status-not-required", reason="assessed unnecessary",
        )
        self.assertFalse(register.downstream_work_outstanding(self.conn, entry))
