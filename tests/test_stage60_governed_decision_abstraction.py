import unittest

from api.governed_decisions import (
    GovernedDecision,
    GovernedEvidenceReference,
    GovernedSubjectReference,
    PUBLISHED_DOCUMENT_DECISION_EVIDENCE_TYPE,
    adapt_published_document_decision,
)


class Stage60GovernedDecisionAbstractionTests(unittest.TestCase):
    def _event(self, *, episode_id=None):
        return {
            "decision_key": "d" * 64,
            "intake_id": "i" * 64,
            "document_identifier": "DOC-2026-000131",
            "decision_sequence": 6,
            "previous_status": "approved",
            "new_status": "published",
            "decided_at": "2026-08-10T12:00:00Z",
            "actor": "admin-user",
            "actor_role": "records-administrator",
            "rationale": "Publish after governed review.",
            "sha256_hash": "a" * 64,
            "sha512_hash": "b" * 128,
            "digest_status": "recorded",
            "episode_id": episode_id,
        }

    def test_published_document_event_maps_without_mutation(self):
        event = self._event(episode_id="LEP-" + "e" * 64)
        original = dict(event)

        decision = adapt_published_document_decision(event)

        self.assertEqual(event, original)
        self.assertEqual(decision.decision_id, event["decision_key"])
        self.assertEqual(decision.idempotency_key, event["decision_key"])
        self.assertEqual(decision.subject.subject_type, "published_document")
        self.assertEqual(decision.subject.subject_id, event["intake_id"])
        self.assertEqual(decision.previous_state, event["previous_status"])
        self.assertEqual(decision.resulting_state, event["new_status"])
        self.assertEqual(decision.actor, event["actor"])
        self.assertEqual(decision.actor_role, event["actor_role"])
        self.assertEqual(decision.decided_at, event["decided_at"])
        self.assertEqual(decision.rationale, event["rationale"])
        self.assertEqual(decision.context_reference, event["episode_id"])
        self.assertEqual(
            decision.evidence_references,
            (
                GovernedEvidenceReference(
                    PUBLISHED_DOCUMENT_DECISION_EVIDENCE_TYPE,
                    event["decision_key"],
                ),
            ),
        )
        self.assertNotIn("document_identifier", decision.as_dict())
        self.assertNotIn("sha256_hash", decision.as_dict())
        self.assertNotIn("sha512_hash", decision.as_dict())
        self.assertNotIn("decision_sequence", decision.as_dict())

    def test_implicit_episode_one_has_no_synthetic_context(self):
        decision = adapt_published_document_decision(self._event())

        self.assertIsNone(decision.context_reference)
        self.assertEqual(decision.subject.subject_id, "i" * 64)

    def test_optional_generic_fields_support_non_lifecycle_decisions(self):
        investigation = GovernedDecision(
            decision_id="investigation-decision-1",
            subject=GovernedSubjectReference("investigation", "INV-1"),
            actor="investigator-1",
            actor_role="lead-investigator",
            decided_at="2026-08-11T10:00:00Z",
            decision_type="finding",
            rationale=None,
            evidence_references=(
                GovernedEvidenceReference("investigation-evidence", "EVID-1"),
            ),
        )
        relationship = GovernedDecision(
            decision_id="relationship-decision-1",
            subject=GovernedSubjectReference("evidence_relationship", "REL-1"),
            actor="administrator-1",
            actor_role="relationship-reviewer",
            decided_at="2026-08-11T11:00:00Z",
            previous_state="proposed",
            resulting_state="confirmed",
            context_reference="review-cycle-1",
        )

        self.assertEqual(investigation.subject.subject_type, "investigation")
        self.assertIsNone(investigation.previous_state)
        self.assertEqual(relationship.subject.subject_type, "evidence_relationship")
        self.assertEqual(relationship.resulting_state, "confirmed")

    def test_generic_contract_does_not_validate_domain_state_vocabulary(self):
        decision = GovernedDecision(
            decision_id="domain-decision-1",
            subject=GovernedSubjectReference("custom_domain", "SUBJECT-1"),
            actor="actor-1",
            actor_role="role-1",
            decided_at="2026-08-11T12:00:00Z",
            previous_state="domain-specific-before",
            resulting_state="domain-specific-after",
        )

        self.assertEqual(decision.previous_state, "domain-specific-before")
        self.assertEqual(decision.resulting_state, "domain-specific-after")

    def test_adapter_is_passive_and_exposes_no_authority_operations(self):
        forbidden = {
            "transition",
            "decide",
            "approve",
            "publish",
            "reconcile",
            "confirm",
            "authorize",
            "allocate_identifier",
            "create_relationship",
            "mutate_subject",
        }

        self.assertFalse(forbidden.intersection(dir(GovernedDecision)))
        self.assertFalse(forbidden.intersection(dir(GovernedSubjectReference)))
        self.assertFalse(forbidden.intersection(dir(GovernedEvidenceReference)))

    def test_adapter_output_is_deterministic(self):
        event = self._event()

        self.assertEqual(
            adapt_published_document_decision(event),
            adapt_published_document_decision(dict(event)),
        )


if __name__ == "__main__":
    unittest.main()
