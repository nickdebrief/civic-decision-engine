"""Disposable synthetic-only Stage 84 decision-record coverage."""
import base64
import hashlib
import hmac
import json
import os
import sqlite3
import time
import unittest

from api import governed_retention_register as retention


def _token(username="owner-a"):
    payload = {"role": "admin", "username": username, "issued_at": int(time.time()), "expires_at": int(time.time()) + 3600}
    encoded = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).rstrip(b"=").decode()
    signature = base64.urlsafe_b64encode(hmac.new(os.environ["CDE_ADMIN_SESSION_SECRET"].encode(), encoded.encode(), hashlib.sha256).digest()).rstrip(b"=").decode()
    return f"{encoded}.{signature}"


class RetentionRegisterTests(unittest.TestCase):
    def _policy_document(self, due_invalidates=True, *, due_at="2099-01-01T00:00:00Z", identity="review-v1", subject_revision=1):
        point = {"identity": identity, "revision": 1, "due_at": due_at}
        return {
            "review_due_invalidates_current_reliance": due_invalidates,
            "permitted_subject_types": list(retention.SUBJECT_TYPES),
            "retention_purpose_basis": "synthetic governance test",
            "trigger_kind": "recorded_event",
            "trigger_evidence_identity": "synthetic-object",
            "trigger_evidence_revision": subject_revision,
            "review_points": [point],
            "eligibility_conditions": ["synthetic current inventory"],
            "ineligibility_conditions": list(retention.INELIGIBLE),
            "owner_authority_id": "synthetic-owner",
            "owner_authority_revision": 1,
            "reviewer_authority_id": "synthetic-reviewer",
            "reviewer_authority_revision": 1,
            "action_review_map": {
                "hold_placement": "owner_only",
                "hold_amendment": "owner_only",
                "hold_release": "owner_plus_independent_synthetic_review",
                "eligible_decision_approval": "owner_plus_independent_synthetic_review",
                "ineligible_decision_approval": "owner_plus_independent_synthetic_review",
            },
            "review_point_rule": point,
            "trigger_evidence": {"subject_identity": "synthetic-object", "subject_revision": subject_revision},
        }

    def setUp(self):
        self.db = sqlite3.connect(":memory:"); self.db.row_factory = sqlite3.Row; retention.ensure_tables(self.db)
        self.old = os.environ.get("CDE_ADMIN_SESSION_SECRET"); os.environ["CDE_ADMIN_SESSION_SECRET"] = "stage84-test-secret"
        self.owner = _token("owner-a")
        self.reviewer = _token("reviewer-b")
        self.db.execute("INSERT INTO governed_retention_policies(policy_id,revision,policy_json,available) VALUES(?,?,?,1)", ("policy-syn", 1, json.dumps(self._policy_document())))
        self.db.execute("INSERT INTO governed_retention_authorities(authority_id,revision,username,role,available) VALUES(?,?,?,?,1)", ("synthetic-owner", 1, "owner-a", "owner"))
        self.db.execute("INSERT INTO governed_retention_authorities(authority_id,revision,username,role,available) VALUES(?,?,?,?,1)", ("synthetic-reviewer", 1, "reviewer-b", "reviewer"))
        now = "2026-10-19T00:00:00Z"
        self.db.execute("INSERT INTO governed_retention_subjects(identifier,subject_type,subject_identity,subject_version,subject_revision,retention_review,inventory_state,eligibility_state,decision_state,approval_state,applicability_state,procedure_state,policy_id,policy_revision,version,created_at,created_by,updated_at,updated_by) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", ("SYN-1", "internal_object_version", "synthetic-object", "v1", 1, "not_due", "not_started", "not_assessed", "none", "not_recorded", "not_evaluated", "recorded", "policy-syn", 1, 1, now, "fixture", now, "fixture"))
        self.db.commit()

    def tearDown(self):
        if self.old is None: os.environ.pop("CDE_ADMIN_SESSION_SECRET", None)
        else: os.environ["CDE_ADMIN_SESSION_SECRET"] = self.old
        self.db.close()

    def _seed_current_approved_chain(self, *, outcome="eligible", review="assessed", procedure="under_review", version=50):
        """Disposable immutable chain fixture for recovery-path tests only."""
        decision = "proposed_eligible_for_future_scope" if outcome == "eligible" else "proposed_ineligible_for_future_scope"
        eligibility = "eligible_current" if outcome == "eligible" else "ineligible_current"
        inventory = "complete_with_limits" if outcome == "eligible" else "incomplete"
        self.db.execute("UPDATE governed_retention_subjects SET retention_review=?,inventory_state=?,eligibility_state=?,decision_state=?,approval_state='approved_current',applicability_state='current',procedure_state=?,version=? WHERE identifier='SYN-1'", (review, inventory, eligibility, decision, procedure, version))
        self.db.execute("INSERT INTO governed_retention_inventory_assessments(subject_id,subject_revision,subject_binding_json,policy_id,policy_revision,outcome,copies_json,evidence_json,limitations,actor,occurred_at) VALUES(1,1,'{}','policy-syn',1,?,?,?,'limits','owner-a','2026-10-19T00:00:00Z')", (inventory, '{}', '["inventory"]'))
        inventory_id = self.db.execute("SELECT last_insert_rowid()").fetchone()[0]
        bindings = json.dumps({"subject_revision": 1, "subject_binding_json": "{}", "policy_id": "policy-syn", "policy_revision": 1, "inventory_assessment_id": inventory_id}, sort_keys=True, separators=(",", ":"))
        self.db.execute("INSERT INTO governed_retention_assessments(subject_id,subject_revision,subject_binding_json,policy_id,policy_revision,outcome,blocker,evidence_json,limitations,next_review_json,actor,occurred_at) VALUES(1,1,'{}','policy-syn',1,?,NULL,'[\"evidence\"]','limits',NULL,'owner-a','2026-10-19T00:00:00Z')", (outcome,))
        assessment_id = self.db.execute("SELECT last_insert_rowid()").fetchone()[0]
        self.db.execute("INSERT INTO governed_retention_decisions(subject_id,assessment_id,revision,outcome,bindings_json,actor,occurred_at) VALUES(1,?,?,?,?,'owner-a','2026-10-19T00:00:00Z')", (assessment_id, assessment_id, outcome, bindings))
        decision_id = self.db.execute("SELECT last_insert_rowid()").fetchone()[0]
        self.db.execute("INSERT INTO governed_retention_reviews(subject_id,decision_id,action,revision,reviewer_fixture_id,reviewer_fixture_revision,reviewer,result,evidence_json,occurred_at) VALUES(1,?,'decision',?,'synthetic-reviewer',1,'reviewer-b','accepted','[\"review\"]','2026-10-19T00:00:00Z')", (decision_id, assessment_id))
        self.db.execute("INSERT INTO governed_retention_approvals(subject_id,decision_id,revision,owner_fixture_id,owner_fixture_revision,actor,occurred_at) VALUES(1,? ,?,'synthetic-owner',1,'owner-a','2026-10-19T00:00:00Z')", (decision_id, assessment_id))
        if review == "deferred":
            policy = json.loads(self.db.execute("SELECT policy_json FROM governed_retention_policies WHERE policy_id='policy-syn' AND revision=1").fetchone()[0])
            point = policy["review_points"][0]["identity"]
            details = {"next_point": point, "responsible": "owner-a", "subject_revision": 1,
                       "subject_binding_json": "{}", "policy_id": "policy-syn", "policy_revision": 1}
            outcome_code = "E" if outcome == "eligible" else "I"
            self.db.execute("INSERT INTO governed_retention_recurring_reviews(subject_id,outcome,procedure_state,state,policy_id,policy_revision,details_json,actor,occurred_at) VALUES(1,?,?, 'deferred','policy-syn',1,?,'owner-a','2026-10-19T00:00:00Z')", (outcome_code, procedure, json.dumps(details)))
        self.db.commit()

    def _seed_initial_deferral_history(self, point):
        payload = {"next_point": point, "responsible": "owner-a", "subject_revision": 1,
                   "subject_binding_json": "{}", "policy_id": "policy-syn", "policy_revision": 1}
        self.db.execute("INSERT INTO governed_retention_history(subject_id,operation_id,actor,reason,details_json,occurred_at) VALUES(1,'DF-01','owner-a','deferred',?,'2026-10-19T00:00:00Z')", (json.dumps({"payload": payload}),))
        self.db.commit()

    def _seed_recurring_deferral_history(self, *, outcome, procedure, point):
        details = {"next_point": point, "responsible": "owner-a", "subject_revision": 1,
                   "subject_binding_json": "{}", "policy_id": "policy-syn", "policy_revision": 1}
        self.db.execute("INSERT INTO governed_retention_recurring_reviews(subject_id,outcome,procedure_state,state,policy_id,policy_revision,details_json,actor,occurred_at) VALUES(1,?,?, 'deferred','policy-syn',1,?,'owner-a','2026-10-19T00:00:00Z')", ("E" if outcome == "eligible" else "I", procedure, json.dumps(details)))
        self.db.commit()

    def _seed_active_closure_history(self, *, outcome="ineligible"):
        self.db.execute("INSERT INTO governed_retention_history(subject_id,operation_id,actor,reason,details_json,occurred_at) VALUES(1,?,'owner-a','synthetic closure','{}','2026-10-19T00:00:00Z')", ("CL-01" if outcome == "eligible" else "CL-02",))
        self.db.commit()

    def _seed_current_hold_applicability(self, hold_identifier, *, revision=1, applicability="applicable"):
        payload = {"hold_identifier": hold_identifier, "hold_revision": revision,
                   "applicability": applicability, "subject_revision": 1,
                   "subject_binding_json": "{}", "policy_id": "policy-syn",
                   "policy_revision": 1}
        self.db.execute("INSERT INTO governed_retention_history(subject_id,operation_id,actor,reason,details_json,occurred_at) VALUES(1,'H-02','owner-a','synthetic applicability',?,'2026-10-19T00:00:00Z')", (json.dumps({"payload": payload}),))
        self.db.commit()

    def test_admission_disabled_and_initial_review_inventory_are_atomic(self):
        with self.assertRaisesRegex(ValueError, "admission_disabled"): retention.create_subject(self.db, {})
        started = retention.start_initial_review(self.db, subject_identifier="SYN-1", actor=self.owner, expected_version=1, idempotency_key="start", reason="synthetic")
        before_evidence_refusal = retention.get_subject(self.db, "SYN-1")
        with self.assertRaisesRegex(ValueError, "inventory_evidence_required"):
            retention.record_inventory(self.db, subject_identifier="SYN-1", outcome="incomplete", copies={"backups": {"status": "unknown"}}, evidence=[], limitations="limits", actor=self.owner, expected_version=2, idempotency_key="missing-inventory-evidence", reason="bad")
        after_evidence_refusal = retention.get_subject(self.db, "SYN-1")
        self.assertEqual((after_evidence_refusal["stored_tuple"], after_evidence_refusal["version"], after_evidence_refusal["history"]), (before_evidence_refusal["stored_tuple"], before_evidence_refusal["version"], before_evidence_refusal["history"]))
        self.assertEqual(started["resulting_version"], 2)
        with self.assertRaisesRegex(ValueError, "copy_classes_incomplete"):
            retention.record_inventory(self.db, subject_identifier="SYN-1", outcome="complete_with_limits", copies={}, evidence=["evidence"], limitations="limits", actor=self.owner, expected_version=2, idempotency_key="bad-inventory", reason="bad")
        self.assertEqual(retention.get_subject(self.db, "SYN-1")["version"], 2)
        copies = {name: {"applicable": True, "identity": name, "control": "synthetic"} for name in retention.COPY_CLASSES}
        complete = retention.record_inventory(self.db, subject_identifier="SYN-1", outcome="complete_with_limits", copies=copies, evidence=["synthetic"], limitations="limits", actor=self.owner, expected_version=2, idempotency_key="inventory", reason="inventory")
        self.assertEqual(complete["resulting_version"], 3)
        self.assertEqual(retention.get_subject(self.db, "SYN-1")["inventory_state"], "complete_with_limits")

    def test_ineligible_supported_blocker_can_coexist_with_inventory_gap(self):
        started = retention.start_initial_review(self.db, subject_identifier="SYN-1", actor=self.owner, expected_version=1, idempotency_key="start-i", reason="synthetic")
        incomplete = retention.record_inventory(self.db, subject_identifier="SYN-1", outcome="incomplete", copies={"backups": {"status": "unknown"}}, evidence=["gap"], limitations="unknown backups", actor=self.owner, expected_version=started["resulting_version"], idempotency_key="incomplete", reason="gap")
        # Complete review state is seeded only as a disposable fixture so this
        # test isolates D-02's supported-blocker rule from review mechanics.
        self.db.execute("UPDATE governed_retention_subjects SET retention_review='assessed',eligibility_state='pending_missing_information' WHERE identifier='SYN-1'"); self.db.commit()
        self.db.execute("INSERT INTO governed_retention_holds(subject_id,hold_identifier,revision,state,basis,evidence_json,scope,limitations,owner_fixture_id,owner_fixture_revision,actor,occurred_at) VALUES(1,'H-D02',1,'active','basis','[\"basis\"]','synthetic','limited','synthetic-owner',1,'owner-a','2026-10-19T00:00:00Z')"); self.db.commit()
        self._seed_current_hold_applicability("H-D02")
        assessed = retention.assess_decision(self.db, subject_identifier="SYN-1", outcome="ineligible", blocker="applicable_active_hold", evidence=["synthetic-hold"], limitations="inventory gap retained", next_review={"point":"2027-01-01", "responsible":"owner-a", "reason":"hold", "scope":"synthetic"}, actor=self.owner, expected_version=incomplete["resulting_version"], idempotency_key="ineligible", reason="hold")
        self.assertEqual(assessed["resulting_version"], 4)
        item = retention.get_subject(self.db, "SYN-1"); self.assertEqual(item["eligibility_state"], "ineligible_current"); self.assertEqual(item["inventory_state"], "incomplete")

    def test_active_hold_blocker_requires_actual_current_hold_without_partial_assessment(self):
        started = retention.start_initial_review(self.db, subject_identifier="SYN-1", actor=self.owner, expected_version=1, idempotency_key="d02-start", reason="start")
        gap = retention.record_inventory(self.db, subject_identifier="SYN-1", outcome="incomplete", copies={"backups":{"status":"unknown"}}, evidence=["gap"], limitations="gap", actor=self.owner, expected_version=started["resulting_version"], idempotency_key="d02-gap", reason="gap")
        self.db.execute("UPDATE governed_retention_subjects SET retention_review='assessed',eligibility_state='pending_missing_information' WHERE identifier='SYN-1'"); self.db.commit()
        before = retention.get_subject(self.db, "SYN-1")
        with self.assertRaisesRegex(ValueError, "active_hold_required"):
            retention.assess_decision(self.db, subject_identifier="SYN-1", outcome="ineligible", blocker="applicable_active_hold", evidence=["assertion"], limitations="gap", next_review={"point":"p","responsible":"owner-a", "reason":"hold", "scope":"synthetic"}, actor=self.owner, expected_version=gap["resulting_version"], idempotency_key="d02-no-hold", reason="hold")
        after = retention.get_subject(self.db, "SYN-1")
        self.assertEqual((after['stored_tuple'], after['version'], after['history']), (before['stored_tuple'], before['version'], before['history']))

    def test_ineligible_assessment_requires_bound_followup_reason_scope_without_writes(self):
        started = retention.start_initial_review(self.db, subject_identifier='SYN-1', actor=self.owner, expected_version=1, idempotency_key='follow-start', reason='start')
        gap = retention.record_inventory(self.db, subject_identifier='SYN-1', outcome='incomplete', copies={'backups': {'status':'unknown'}}, evidence=['gap'], limitations='gap', actor=self.owner, expected_version=started['resulting_version'], idempotency_key='follow-gap', reason='gap')
        self.db.execute("UPDATE governed_retention_subjects SET retention_review='assessed' WHERE identifier='SYN-1'"); self.db.commit()
        before = (retention.get_subject(self.db, 'SYN-1')['stored_tuple'], self.db.execute("SELECT count(*) FROM governed_retention_assessments").fetchone()[0], self.db.execute("SELECT count(*) FROM governed_retention_history").fetchone()[0])
        with self.assertRaisesRegex(ValueError, 'next_review_required'):
            retention.assess_decision(self.db, subject_identifier='SYN-1', outcome='ineligible', blocker='relevant_unresolved_obligation', evidence=['obligation'], limitations='gap', next_review={'point':'next','responsible':'owner-a'}, actor=self.owner, expected_version=gap['resulting_version'], idempotency_key='follow-refuse', reason='assess')
        self.assertEqual((retention.get_subject(self.db, 'SYN-1')['stored_tuple'], self.db.execute("SELECT count(*) FROM governed_retention_assessments").fetchone()[0], self.db.execute("SELECT count(*) FROM governed_retention_history").fetchone()[0]), before)

    def test_d01_pending_information_and_d04_unbound_followup_refuse_atomically(self):
        """D-01 cannot promote missing information; D-04 needs bound follow-up."""
        started = retention.start_initial_review(self.db, subject_identifier='SYN-1', actor=self.owner, expected_version=1, idempotency_key='d-phase-start', reason='start')
        gap = retention.record_inventory(self.db, subject_identifier='SYN-1', outcome='incomplete', copies={'backups': {'status': 'unknown'}}, evidence=['gap'], limitations='gap', actor=self.owner, expected_version=started['resulting_version'], idempotency_key='d-phase-gap', reason='gap')
        self.db.execute("UPDATE governed_retention_subjects SET retention_review='assessed' WHERE identifier='SYN-1'"); self.db.commit()
        before = (retention.get_subject(self.db, 'SYN-1')['stored_tuple'], self.db.execute("SELECT count(*) FROM governed_retention_assessments").fetchone()[0], self.db.execute("SELECT count(*) FROM governed_retention_history").fetchone()[0])
        with self.assertRaisesRegex(ValueError, 'eligibility_conditions_unsatisfied'):
            retention.assess_decision(self.db, subject_identifier='SYN-1', outcome='eligible', blocker=None, evidence=['conditions'], limitations='limits', next_review=None, actor=self.owner, expected_version=gap['resulting_version'], idempotency_key='d01-pending', reason='bad')
        self.assertEqual((retention.get_subject(self.db, 'SYN-1')['stored_tuple'], self.db.execute("SELECT count(*) FROM governed_retention_assessments").fetchone()[0], self.db.execute("SELECT count(*) FROM governed_retention_history").fetchone()[0]), before)
        # Direct immutable fixture rows model a malformed historical predecessor:
        # D-04 must not turn that row into a proposal merely because E is shaped.
        self.db.execute("INSERT INTO governed_retention_assessments(subject_id,subject_revision,subject_binding_json,policy_id,policy_revision,outcome,blocker,evidence_json,limitations,next_review_json,actor,occurred_at) VALUES(1,1,'{}','policy-syn',1,'ineligible','relevant_unresolved_obligation','[\"evidence\"]','gap',NULL,'owner-a','2026-10-19T00:00:00Z')")
        self.db.execute("UPDATE governed_retention_subjects SET eligibility_state='ineligible_current',version=? WHERE identifier='SYN-1'", (gap['resulting_version'],)); self.db.commit()
        before_proposal = (retention.get_subject(self.db, 'SYN-1')['stored_tuple'], self.db.execute("SELECT count(*) FROM governed_retention_decisions").fetchone()[0], self.db.execute("SELECT count(*) FROM governed_retention_history").fetchone()[0])
        with self.assertRaisesRegex(ValueError, 'next_review_required'):
            retention.propose_decision(self.db, subject_identifier='SYN-1', outcome='ineligible', actor=self.owner, expected_version=gap['resulting_version'], idempotency_key='d04-unbound', reason='bad')
        self.assertEqual((retention.get_subject(self.db, 'SYN-1')['stored_tuple'], self.db.execute("SELECT count(*) FROM governed_retention_decisions").fetchone()[0], self.db.execute("SELECT count(*) FROM governed_retention_history").fetchone()[0]), before_proposal)

    def test_d02_refuses_inventory_projection_that_disagrees_with_immutable_assessment(self):
        started = retention.start_initial_review(self.db, subject_identifier='SYN-1', actor=self.owner, expected_version=1, idempotency_key='d02-inventory-start', reason='start')
        gap = retention.record_inventory(self.db, subject_identifier='SYN-1', outcome='incomplete', copies={'backups': {'status':'unknown'}}, evidence=['gap'], limitations='gap', actor=self.owner, expected_version=started['resulting_version'], idempotency_key='d02-inventory-gap', reason='gap')
        # A direct malformed projection must not turn an immutable incomplete
        # inventory record into a complete/current assessment predecessor.
        self.db.execute("UPDATE governed_retention_subjects SET retention_review='assessed',inventory_state='complete_with_limits' WHERE identifier='SYN-1'"); self.db.commit()
        before = (retention.get_subject(self.db, 'SYN-1')['stored_tuple'], self.db.execute("SELECT count(*) FROM governed_retention_assessments").fetchone()[0], self.db.execute("SELECT count(*) FROM governed_retention_history").fetchone()[0])
        with self.assertRaisesRegex(ValueError, 'inventory_binding_invalid'):
            retention.assess_decision(self.db, subject_identifier='SYN-1', outcome='ineligible', blocker='relevant_unresolved_obligation', evidence=['obligation'], limitations='gap', next_review={'point':'next','responsible':'owner-a','reason':'obligation','scope':'synthetic'}, actor=self.owner, expected_version=gap['resulting_version'], idempotency_key='d02-inventory-mismatch', reason='assess')
        self.assertEqual((retention.get_subject(self.db, 'SYN-1')['stored_tuple'], self.db.execute("SELECT count(*) FROM governed_retention_assessments").fetchone()[0], self.db.execute("SELECT count(*) FROM governed_retention_history").fetchone()[0]), before)

    def test_invalid_synthetic_subject_binding_rejects_before_review_mutation(self):
        self.db.execute("UPDATE governed_retention_subjects SET subject_type='unapproved_subject_type' WHERE identifier='SYN-1'"); self.db.commit()
        before = dict(self.db.execute("SELECT * FROM governed_retention_subjects WHERE identifier='SYN-1'").fetchone())
        with self.assertRaisesRegex(ValueError, 'subject_type_invalid'):
            retention.start_initial_review(self.db, subject_identifier='SYN-1', actor=self.owner, expected_version=1, idempotency_key='bad-subject', reason='start')
        self.assertEqual(dict(self.db.execute("SELECT * FROM governed_retention_subjects WHERE identifier='SYN-1'").fetchone()), before)

    def test_structured_repository_commit_binding_is_required_and_immutable_at_use(self):
        binding = {'repository_identity':'synthetic/repo','commit_sha':'a' * 40}
        self.db.execute("UPDATE governed_retention_subjects SET subject_type='repository_commit',subject_identity=?,subject_version=?,subject_binding_json=? WHERE identifier='SYN-1'", ('synthetic/repo', 'a' * 40, json.dumps(binding))); self.db.commit()
        started = retention.start_initial_review(self.db, subject_identifier='SYN-1', actor=self.owner, expected_version=1, idempotency_key='commit-start', reason='start')
        self.assertEqual(started['operation'], 'SR-01')
        self.db.execute("UPDATE governed_retention_subjects SET subject_binding_json=? WHERE identifier='SYN-1'", (json.dumps({'repository_identity':'other/repo','commit_sha':'a' * 40}),)); self.db.commit()
        before = dict(self.db.execute("SELECT * FROM governed_retention_subjects WHERE identifier='SYN-1'").fetchone())
        with self.assertRaisesRegex(ValueError, 'subject_binding_invalid'):
            retention.complete_review(self.db, subject_identifier='SYN-1', evidence=['review'], limitations='limits', actor=self.owner, expected_version=started['resulting_version'], idempotency_key='commit-cross-repo', reason='complete')
        self.assertEqual(dict(self.db.execute("SELECT * FROM governed_retention_subjects WHERE identifier='SYN-1'").fetchone()), before)

    def test_structured_pull_request_requires_same_repository_observed_head_and_base(self):
        binding = {'repository_identity':'synthetic/repo','pull_request_number':47,'observed_head':{'repository_identity':'synthetic/repo','commit_sha':'b' * 40},'observed_base':{'repository_identity':'synthetic/repo','commit_sha':'c' * 40}}
        self.db.execute("UPDATE governed_retention_subjects SET subject_type='pull_request',subject_identity=?,subject_version=?,subject_binding_json=? WHERE identifier='SYN-1'", ('synthetic/repo', '47', json.dumps(binding))); self.db.commit()
        self.assertEqual(retention.start_initial_review(self.db, subject_identifier='SYN-1', actor=self.owner, expected_version=1, idempotency_key='pr-start', reason='start')['operation'], 'SR-01')
        binding['observed_base']['repository_identity'] = 'cross/repo'
        self.db.execute("UPDATE governed_retention_subjects SET subject_binding_json=? WHERE identifier='SYN-1'", (json.dumps(binding),)); self.db.commit()
        before = dict(self.db.execute("SELECT * FROM governed_retention_subjects WHERE identifier='SYN-1'").fetchone())
        with self.assertRaisesRegex(ValueError, 'subject_binding_invalid'):
            retention.record_inventory(self.db, subject_identifier='SYN-1', outcome='incomplete', copies={'backups':{'status':'unknown'}}, evidence=['e'], limitations='l', actor=self.owner, expected_version=2, idempotency_key='pr-cross-repo', reason='inventory')
        self.assertEqual(dict(self.db.execute("SELECT * FROM governed_retention_subjects WHERE identifier='SYN-1'").fetchone()), before)

    def test_repository_binding_successor_is_historical_and_invalidates_without_reliance_restore(self):
        first = {'repository_identity':'synthetic/repo','commit_sha':'a' * 40}
        second = {'repository_identity':'synthetic/repo','commit_sha':'b' * 40}
        self.db.execute("UPDATE governed_retention_subjects SET subject_type='repository_commit',subject_identity=?,subject_version=?,subject_binding_json=?,retention_review='assessed',inventory_state='complete_with_limits',eligibility_state='eligible_current',decision_state='proposed_eligible_for_future_scope',approval_state='approved_current',applicability_state='current',procedure_state='under_review',version=12 WHERE identifier='SYN-1'", ('synthetic/repo', 'a' * 40, json.dumps(first))); self.db.commit()
        changed = retention.replace_subject_binding(self.db, subject_identifier='SYN-1', subject_identity='synthetic/repo', subject_version='b' * 40, subject_binding=second, owner_authority='synthetic-owner', owner_revision=1, actor=self.owner, expected_version=12, idempotency_key='commit-successor', reason='synthetic successor')
        row = dict(self.db.execute("SELECT * FROM governed_retention_subjects WHERE identifier='SYN-1'").fetchone())
        self.assertEqual((row['subject_revision'], row['subject_binding_json'], row['eligibility_state'], row['approval_state'], row['applicability_state']), (2, json.dumps(second, sort_keys=True, separators=(',', ':')), 'stale', 'stale', 'reassessment_required'))
        event = json.loads(self.db.execute("SELECT details_json FROM governed_retention_history WHERE subject_id=1 ORDER BY id DESC LIMIT 1").fetchone()[0])['payload']
        self.assertEqual((event['prior_binding'], event['successor_binding']), (json.dumps(first), json.dumps(second, sort_keys=True, separators=(',', ':'))))
        self.assertEqual(changed['operation'], 'IV-01-O')

    def test_repository_binding_substitution_rejects_independent_review_without_writes(self):
        first = {'repository_identity':'synthetic/repo','commit_sha':'a' * 40}
        second = {'repository_identity':'synthetic/repo','commit_sha':'b' * 40}
        self.db.execute("UPDATE governed_retention_subjects SET subject_type='repository_commit',subject_identity=?,subject_version=?,subject_revision=1,subject_binding_json=?,retention_review='assessed',inventory_state='complete_with_limits',eligibility_state='eligible_current',decision_state='proposed_eligible_for_future_scope',approval_state='not_recorded',applicability_state='not_evaluated',procedure_state='under_review',version=21 WHERE identifier='SYN-1'", ('synthetic/repo', 'a' * 40, json.dumps(first)))
        self.db.execute("INSERT INTO governed_retention_assessments(subject_id,subject_revision,subject_binding_json,policy_id,policy_revision,outcome,blocker,evidence_json,limitations,next_review_json,actor,occurred_at) VALUES(1,1,?,'policy-syn',1,'eligible',NULL,'[\"evidence\"]','limits',NULL,'owner-a','2026-10-19T00:00:00Z')", (json.dumps(first),))
        self.db.execute("INSERT INTO governed_retention_decisions(subject_id,assessment_id,revision,outcome,bindings_json,actor,occurred_at) VALUES(1,1,1,'eligible',?,'owner-a','2026-10-19T00:00:00Z')", (json.dumps({'subject_revision':1,'subject_binding_json':json.dumps(first),'policy_id':'policy-syn','policy_revision':1}),)); self.db.commit()
        self.db.execute("UPDATE governed_retention_subjects SET subject_version=?,subject_revision=2,subject_binding_json=? WHERE identifier='SYN-1'", ('b' * 40, json.dumps(second))); self.db.commit()
        before = (dict(self.db.execute("SELECT * FROM governed_retention_subjects WHERE identifier='SYN-1'").fetchone()), self.db.execute("SELECT count(*) FROM governed_retention_reviews").fetchone()[0], self.db.execute("SELECT count(*) FROM governed_retention_history").fetchone()[0])
        with self.assertRaisesRegex(ValueError, 'decision_binding_invalid'):
            retention.independent_review(self.db, subject_identifier='SYN-1', reviewer_authority='synthetic-reviewer', reviewer_revision=1, actor=self.reviewer, expected_version=21, idempotency_key='commit-substitute', reason='review', evidence=['review'])
        after = (dict(self.db.execute("SELECT * FROM governed_retention_subjects WHERE identifier='SYN-1'").fetchone()), self.db.execute("SELECT count(*) FROM governed_retention_reviews").fetchone()[0], self.db.execute("SELECT count(*) FROM governed_retention_history").fetchone()[0])
        self.assertEqual(after, before)

    def test_stale_inventory_and_assessment_bindings_refuse_assessment_and_proposal_atomically(self):
        started = retention.start_initial_review(self.db, subject_identifier='SYN-1', actor=self.owner, expected_version=1, idempotency_key='bind-start', reason='start')
        copies = {name: {'applicable': True, 'identity': name, 'control': 'synthetic'} for name in retention.COPY_CLASSES}
        inventory = retention.record_inventory(self.db, subject_identifier='SYN-1', outcome='complete_with_limits', copies=copies, evidence=['inventory'], limitations='limits', actor=self.owner, expected_version=started['resulting_version'], idempotency_key='bind-inventory', reason='inventory')
        self.db.execute("UPDATE governed_retention_subjects SET subject_revision=2,subject_binding_json=? WHERE identifier='SYN-1'", (json.dumps({'synthetic_revision': 2}),)); self.db.commit()
        before = (dict(self.db.execute("SELECT * FROM governed_retention_subjects WHERE identifier='SYN-1'").fetchone()), self.db.execute("SELECT count(*) FROM governed_retention_assessments").fetchone()[0], self.db.execute("SELECT count(*) FROM governed_retention_history").fetchone()[0])
        with self.assertRaisesRegex(ValueError, 'inventory_binding_invalid'):
            retention.assess_decision(self.db, subject_identifier='SYN-1', outcome='eligible', blocker=None, evidence=['conditions'], limitations='limits', next_review=None, actor=self.owner, expected_version=inventory['resulting_version'], idempotency_key='bind-assess-refuse', reason='assess')
        self.assertEqual((dict(self.db.execute("SELECT * FROM governed_retention_subjects WHERE identifier='SYN-1'").fetchone()), self.db.execute("SELECT count(*) FROM governed_retention_assessments").fetchone()[0], self.db.execute("SELECT count(*) FROM governed_retention_history").fetchone()[0]), before)
        self.db.execute("UPDATE governed_retention_subjects SET subject_revision=1,subject_binding_json='{}',retention_review='assessed',eligibility_state='eligible_current' WHERE identifier='SYN-1'")
        self.db.execute("INSERT INTO governed_retention_assessments(subject_id,subject_revision,subject_binding_json,policy_id,policy_revision,outcome,blocker,evidence_json,limitations,next_review_json,actor,occurred_at) VALUES(1,1,'{}','policy-syn',1,'eligible',NULL,'[\"evidence\"]','limits',NULL,'owner-a','2026-10-19T00:00:00Z')"); self.db.commit()
        self.db.execute("UPDATE governed_retention_subjects SET subject_revision=2,subject_binding_json=? WHERE identifier='SYN-1'", (json.dumps({'synthetic_revision': 2}),)); self.db.commit()
        version = self.db.execute("SELECT version FROM governed_retention_subjects WHERE identifier='SYN-1'").fetchone()[0]
        before_history = self.db.execute("SELECT count(*) FROM governed_retention_history").fetchone()[0]
        with self.assertRaisesRegex(ValueError, 'assessment_binding_invalid'):
            retention.propose_decision(self.db, subject_identifier='SYN-1', outcome='eligible', actor=self.owner, expected_version=version, idempotency_key='bind-propose-refuse', reason='propose')
        self.assertEqual(self.db.execute("SELECT count(*) FROM governed_retention_history").fetchone()[0], before_history)

    def test_forged_actor_and_idempotency_conflict_leave_no_writes(self):
        with self.assertRaisesRegex(ValueError, "authenticated_actor_required"):
            retention.start_initial_review(self.db, subject_identifier="SYN-1", actor={"username":"owner-a"}, expected_version=1, idempotency_key="forged", reason="forged")
        good = retention.start_initial_review(self.db, subject_identifier="SYN-1", actor=self.owner, expected_version=1, idempotency_key="same", reason="one")
        before_retry = (retention.get_subject(self.db, "SYN-1")["stored_tuple"], retention.get_subject(self.db, "SYN-1")["version"], len(retention.get_subject(self.db, "SYN-1")["history"]), self.db.execute("SELECT receipt_json FROM governed_retention_receipts WHERE idempotency_key='same'").fetchone()[0])
        replay = retention.start_initial_review(self.db, subject_identifier="SYN-1", actor=self.owner, expected_version=1, idempotency_key="same", reason="one")
        self.assertEqual(good["resulting_version"], replay["resulting_version"])
        self.assertFalse(good["historical"])
        self.assertTrue(replay["historical"])
        self.assertEqual({key: value for key, value in replay.items() if key != "historical"}, {key: value for key, value in good.items() if key != "historical"})
        after_retry = (retention.get_subject(self.db, "SYN-1")["stored_tuple"], retention.get_subject(self.db, "SYN-1")["version"], len(retention.get_subject(self.db, "SYN-1")["history"]), self.db.execute("SELECT receipt_json FROM governed_retention_receipts WHERE idempotency_key='same'").fetchone()[0])
        self.assertEqual(after_retry, before_retry)
        with self.assertRaisesRegex(ValueError, "idempotency_conflict"):
            retention.start_initial_review(self.db, subject_identifier="SYN-1", actor=self.owner, expected_version=2, idempotency_key="same", reason="different")
        self.assertEqual(retention.get_subject(self.db, "SYN-1")["version"], 2)

    def test_owner_authorized_hold_retry_is_historical_without_receipt_mutation(self):
        started = retention.start_initial_review(self.db, subject_identifier="SYN-1", actor=self.owner, expected_version=1, idempotency_key="retry-owner-start", reason="start")
        first = retention.record_hold(self.db, subject_identifier="SYN-1", operation="place", hold_identifier="H-RETRY", owner_authority="synthetic-owner", owner_revision=1, evidence=["basis"], scope="scope", limitations="limits", actor=self.owner, expected_version=started["resulting_version"], idempotency_key="retry-owner-hold", reason="place")
        before_retry = (retention.get_subject(self.db, "SYN-1")["stored_tuple"], retention.get_subject(self.db, "SYN-1")["version"], len(retention.get_subject(self.db, "SYN-1")["history"]), self.db.execute("SELECT count(*) FROM governed_retention_holds").fetchone()[0], self.db.execute("SELECT receipt_json FROM governed_retention_receipts WHERE idempotency_key='retry-owner-hold'").fetchone()[0])
        replay = retention.record_hold(self.db, subject_identifier="SYN-1", operation="place", hold_identifier="H-RETRY", owner_authority="synthetic-owner", owner_revision=1, evidence=["basis"], scope="scope", limitations="limits", actor=self.owner, expected_version=started["resulting_version"], idempotency_key="retry-owner-hold", reason="place")
        self.assertFalse(first["historical"])
        self.assertTrue(replay["historical"])
        self.assertEqual({key: value for key, value in replay.items() if key != "historical"}, {key: value for key, value in first.items() if key != "historical"})
        after_retry = (retention.get_subject(self.db, "SYN-1")["stored_tuple"], retention.get_subject(self.db, "SYN-1")["version"], len(retention.get_subject(self.db, "SYN-1")["history"]), self.db.execute("SELECT count(*) FROM governed_retention_holds").fetchone()[0], self.db.execute("SELECT receipt_json FROM governed_retention_receipts WHERE idempotency_key='retry-owner-hold'").fetchone()[0])
        self.assertEqual(after_retry, before_retry)
        with self.assertRaisesRegex(ValueError, "idempotency_conflict"):
            retention.record_hold(self.db, subject_identifier="SYN-1", operation="place", hold_identifier="H-RETRY", owner_authority="synthetic-owner", owner_revision=1, evidence=["changed"], scope="scope", limitations="limits", actor=self.owner, expected_version=started["resulting_version"], idempotency_key="retry-owner-hold", reason="place")

    def test_policy_due_true_invalidates_an_approved_shape_without_reopening(self):
        self.db.execute("UPDATE governed_retention_policies SET policy_json=? WHERE policy_id='policy-syn' AND revision=1", (json.dumps(self._policy_document(True, due_at='2026-01-01T00:00:00Z')),)); self.db.commit()
        self._seed_current_approved_chain(procedure='closed', version=7)
        due = retention.apply_review_due(self.db, subject_identifier="SYN-1", reached_point="review-v1", actor=self.owner, expected_version=7, idempotency_key="due", reason="reached")
        self.assertEqual(due["resulting_version"], 8)
        item = retention.get_subject(self.db, "SYN-1")
        self.assertEqual(item["procedure_state"], "closed")
        self.assertEqual(item["applicability_state"], "reassessment_required")
        self.assertEqual(retention.render_private_status(item), "Closed — reassessment required")

    def test_review_information_and_initial_deferral_have_exact_recovery(self):
        started = retention.start_initial_review(self.db, subject_identifier="SYN-1", actor=self.owner, expected_version=1, idempotency_key="r-start", reason="start")
        waiting = retention.review_information(self.db, subject_identifier="SYN-1", resume=False, missing_information="source", actor=self.owner, expected_version=started["resulting_version"], idempotency_key="r-wait", reason="wait")
        before_resume = (retention.get_subject(self.db, "SYN-1")["stored_tuple"], retention.get_subject(self.db, "SYN-1")["version"], len(retention.get_subject(self.db, "SYN-1")["history"]))
        with self.assertRaisesRegex(ValueError, "review_resume_evidence_required"):
            retention.review_information(self.db, subject_identifier="SYN-1", resume=True, missing_information=None, actor=self.owner, expected_version=waiting["resulting_version"], idempotency_key="r-resume-empty", reason="resume")
        self.assertEqual((retention.get_subject(self.db, "SYN-1")["stored_tuple"], retention.get_subject(self.db, "SYN-1")["version"], len(retention.get_subject(self.db, "SYN-1")["history"])), before_resume)
        resumed = retention.review_information(self.db, subject_identifier="SYN-1", resume=True, missing_information="source", actor=self.owner, expected_version=waiting["resulting_version"], idempotency_key="r-resume", reason="resume")
        before_complete = (retention.get_subject(self.db, "SYN-1")["stored_tuple"], retention.get_subject(self.db, "SYN-1")["version"], len(retention.get_subject(self.db, "SYN-1")["history"]))
        with self.assertRaisesRegex(ValueError, "review_evidence_required"):
            retention.complete_review(self.db, subject_identifier="SYN-1", evidence=[], limitations="limits", actor=self.owner, expected_version=resumed["resulting_version"], idempotency_key="r-complete-empty", reason="complete")
        self.assertEqual((retention.get_subject(self.db, "SYN-1")["stored_tuple"], retention.get_subject(self.db, "SYN-1")["version"], len(retention.get_subject(self.db, "SYN-1")["history"])), before_complete)
        assessed = retention.complete_review(self.db, subject_identifier="SYN-1", evidence=["review"], limitations="limits", actor=self.owner, expected_version=resumed["resulting_version"], idempotency_key="r-complete", reason="complete")
        before_repeat_complete = (retention.get_subject(self.db, "SYN-1")["stored_tuple"], retention.get_subject(self.db, "SYN-1")["version"], len(retention.get_subject(self.db, "SYN-1")["history"]))
        with self.assertRaisesRegex(ValueError, "review_state_invalid"):
            retention.complete_review(self.db, subject_identifier="SYN-1", evidence=["repeat"], limitations="limits", actor=self.owner, expected_version=assessed["resulting_version"], idempotency_key="r-complete-repeat", reason="repeat")
        self.assertEqual((retention.get_subject(self.db, "SYN-1")["stored_tuple"], retention.get_subject(self.db, "SYN-1")["version"], len(retention.get_subject(self.db, "SYN-1")["history"])), before_repeat_complete)
        deferred = retention.defer_initial_review(self.db, subject_identifier="SYN-1", next_point="synthetic-point", responsible="owner-a", resume=False, actor=self.owner, expected_version=assessed["resulting_version"], idempotency_key="r-defer", reason="defer")
        self.assertEqual(retention.get_subject(self.db,"SYN-1")["retention_review"], "deferred")
        retention.defer_initial_review(self.db, subject_identifier="SYN-1", next_point="synthetic-point", responsible="owner-a", resume=True, actor=self.owner, expected_version=deferred["resulting_version"], idempotency_key="r-defer-resume", reason="resume")
        self.assertEqual(retention.get_subject(self.db,"SYN-1")["retention_review"], "under_assessment")

    def test_inventory_resumption_refuses_stale_snapshot_without_mutation(self):
        started = retention.start_initial_review(self.db, subject_identifier="SYN-1", actor=self.owner, expected_version=1, idempotency_key="inv-resume-start", reason="start")
        waiting = retention.record_inventory(self.db, subject_identifier="SYN-1", outcome="awaiting_information", copies={}, evidence=["missing"], limitations="limits", actor=self.owner, expected_version=started["resulting_version"], idempotency_key="inv-resume-wait", reason="wait")
        self.db.execute("UPDATE governed_retention_subjects SET subject_revision=2,subject_binding_json=? WHERE identifier='SYN-1'", (json.dumps({"synthetic_revision": 2}),)); self.db.commit()
        before = (dict(self.db.execute("SELECT * FROM governed_retention_subjects WHERE identifier='SYN-1'").fetchone()), self.db.execute("SELECT count(*) FROM governed_retention_history").fetchone()[0])
        with self.assertRaisesRegex(ValueError, "inventory_binding_invalid"):
            retention.resume_inventory(self.db, subject_identifier="SYN-1", recovered=True, actor=self.owner, expected_version=waiting["resulting_version"], idempotency_key="inv-resume-stale", reason="recover")
        self.assertEqual((dict(self.db.execute("SELECT * FROM governed_retention_subjects WHERE identifier='SYN-1'").fetchone()), self.db.execute("SELECT count(*) FROM governed_retention_history").fetchone()[0]), before)

    def test_inventory_result_cannot_overwrite_awaiting_information_without_resumption(self):
        started = retention.start_initial_review(self.db, subject_identifier="SYN-1", actor=self.owner, expected_version=1, idempotency_key="inv-phase-start", reason="start")
        waiting = retention.record_inventory(self.db, subject_identifier="SYN-1", outcome="awaiting_information", copies={}, evidence=["missing"], limitations="limits", actor=self.owner, expected_version=started["resulting_version"], idempotency_key="inv-phase-await", reason="await")
        before = (retention.get_subject(self.db, "SYN-1")["stored_tuple"], retention.get_subject(self.db, "SYN-1")["version"], len(retention.get_subject(self.db, "SYN-1")["history"]))
        with self.assertRaisesRegex(ValueError, "inventory_phase_invalid"):
            retention.record_inventory(self.db, subject_identifier="SYN-1", outcome="incomplete", copies={"backups": {"status": "unknown"}}, evidence=["late"], limitations="limits", actor=self.owner, expected_version=waiting["resulting_version"], idempotency_key="inv-phase-overwrite", reason="overwrite")
        self.assertEqual((retention.get_subject(self.db, "SYN-1")["stored_tuple"], retention.get_subject(self.db, "SYN-1")["version"], len(retention.get_subject(self.db, "SYN-1")["history"])), before)

    def test_eligible_assessment_requires_evidence_without_partial_write(self):
        started = retention.start_initial_review(self.db, subject_identifier="SYN-1", actor=self.owner, expected_version=1, idempotency_key="d01-evidence-start", reason="start")
        copies = {name: {"applicable": True, "identity": name, "control": "synthetic"} for name in retention.COPY_CLASSES}
        inventory = retention.record_inventory(self.db, subject_identifier="SYN-1", outcome="complete_with_limits", copies=copies, evidence=["inventory"], limitations="limits", actor=self.owner, expected_version=started["resulting_version"], idempotency_key="d01-evidence-inventory", reason="inventory")
        reviewed = retention.complete_review(self.db, subject_identifier="SYN-1", evidence=["review"], limitations="limits", actor=self.owner, expected_version=inventory["resulting_version"], idempotency_key="d01-evidence-review", reason="review")
        searched = retention.assess_hold_context(self.db, subject_identifier="SYN-1", hold_identifier=None, applicability=None, evidence=["search"], scope="synthetic", limitations="limits", actor=self.owner, expected_version=reviewed["resulting_version"], idempotency_key="d01-evidence-search", reason="search")
        before = (retention.get_subject(self.db, "SYN-1")["stored_tuple"], retention.get_subject(self.db, "SYN-1")["version"], len(retention.get_subject(self.db, "SYN-1")["history"]))
        with self.assertRaisesRegex(ValueError, "eligibility_evidence_required"):
            retention.assess_decision(self.db, subject_identifier="SYN-1", outcome="eligible", blocker=None, evidence=[], limitations="limits", next_review=None, actor=self.owner, expected_version=searched["resulting_version"], idempotency_key="d01-evidence-refuse", reason="assess")
        self.assertEqual((retention.get_subject(self.db, "SYN-1")["stored_tuple"], retention.get_subject(self.db, "SYN-1")["version"], len(retention.get_subject(self.db, "SYN-1")["history"])), before)

    def test_known_out_of_control_copy_blocks_eligible_assessment_atomically(self):
        started = retention.start_initial_review(self.db, subject_identifier="SYN-1", actor=self.owner, expected_version=1, idempotency_key="d01-control-start", reason="start")
        copies = {name: {"applicable": True, "identity": name, "control": "synthetic"} for name in retention.COPY_CLASSES}
        copies["backups"]["control"] = "out_of_control"
        inventory = retention.record_inventory(self.db, subject_identifier="SYN-1", outcome="complete_with_limits", copies=copies, evidence=["inventory"], limitations="limits", actor=self.owner, expected_version=started["resulting_version"], idempotency_key="d01-control-inventory", reason="inventory")
        reviewed = retention.complete_review(self.db, subject_identifier="SYN-1", evidence=["review"], limitations="limits", actor=self.owner, expected_version=inventory["resulting_version"], idempotency_key="d01-control-review", reason="review")
        searched = retention.assess_hold_context(self.db, subject_identifier="SYN-1", hold_identifier=None, applicability=None, evidence=["search"], scope="synthetic", limitations="limits", actor=self.owner, expected_version=reviewed["resulting_version"], idempotency_key="d01-control-search", reason="search")
        before = (retention.get_subject(self.db, "SYN-1")["stored_tuple"], retention.get_subject(self.db, "SYN-1")["version"], len(retention.get_subject(self.db, "SYN-1")["history"]))
        with self.assertRaisesRegex(ValueError, "eligibility_conditions_unsatisfied"):
            retention.assess_decision(self.db, subject_identifier="SYN-1", outcome="eligible", blocker=None, evidence=["conditions"], limitations="limits", next_review=None, actor=self.owner, expected_version=searched["resulting_version"], idempotency_key="d01-control-refuse", reason="assess")
        self.assertEqual((retention.get_subject(self.db, "SYN-1")["stored_tuple"], retention.get_subject(self.db, "SYN-1")["version"], len(retention.get_subject(self.db, "SYN-1")["history"])), before)

    def test_hold_search_is_observational_and_unknown_hold_rejects_without_write(self):
        started = retention.start_initial_review(self.db, subject_identifier="SYN-1", actor=self.owner, expected_version=1, idempotency_key="h-start", reason="start")
        before = retention.get_subject(self.db,"SYN-1")
        searched = retention.assess_hold_context(self.db, subject_identifier="SYN-1", hold_identifier=None, applicability=None, evidence=['search'], scope='synthetic', limitations='limited', actor=self.owner, expected_version=started["resulting_version"], idempotency_key="h-search", reason="bounded search")
        self.assertEqual(searched["resulting_version"], before["version"] + 1)
        after = retention.get_subject(self.db,"SYN-1"); self.assertEqual(after["decision_state"], "none")
        with self.assertRaisesRegex(ValueError,"hold_not_found"):
            retention.assess_hold_context(self.db, subject_identifier="SYN-1", hold_identifier="missing", applicability=True, evidence=['search'], scope='synthetic', limitations='limited', actor=self.owner, expected_version=after["version"], idempotency_key="h-missing", reason="bad")
        self.assertEqual(retention.get_subject(self.db,"SYN-1")["version"], after["version"])

    def test_rejected_shape_recovery_preserves_history_and_refuses_wrong_shape(self):
        self.db.execute("UPDATE governed_retention_subjects SET retention_review='assessed',inventory_state='complete_with_limits',eligibility_state='eligible_current',decision_state='proposed_eligible_for_future_scope',approval_state='not_approved',applicability_state='not_evaluated',procedure_state='under_review',version=9 WHERE identifier='SYN-1'")
        self.db.commit()
        before_refusal = (retention.get_subject(self.db, 'SYN-1')['stored_tuple'], self.db.execute("SELECT count(*) FROM governed_retention_history").fetchone()[0])
        with self.assertRaisesRegex(ValueError, 'rejection_recovery_binding_invalid'):
            retention.recover_rejected_proposal(self.db, subject_identifier='SYN-1', actor=self.owner, expected_version=9, idempotency_key='recover-unbound', reason='fresh assessment')
        self.assertEqual((retention.get_subject(self.db, 'SYN-1')['stored_tuple'], self.db.execute("SELECT count(*) FROM governed_retention_history").fetchone()[0]), before_refusal)
        bindings = json.dumps({'subject_revision':1, 'subject_binding_json':'{}', 'policy_id':'policy-syn', 'policy_revision':1}, sort_keys=True, separators=(',', ':'))
        self.db.execute("INSERT INTO governed_retention_assessments(subject_id,subject_revision,subject_binding_json,policy_id,policy_revision,outcome,blocker,evidence_json,limitations,next_review_json,actor,occurred_at) VALUES(1,1,'{}','policy-syn',1,'eligible',NULL,'[]','limits',NULL,'owner-a','2026-10-19T00:00:00Z')")
        self.db.execute("INSERT INTO governed_retention_decisions(subject_id,assessment_id,revision,outcome,bindings_json,actor,occurred_at) VALUES(1,1,1,'eligible',?,'owner-a','2026-10-19T00:00:00Z')", (bindings,))
        self.db.execute("INSERT INTO governed_retention_reviews(subject_id,decision_id,action,revision,reviewer_fixture_id,reviewer_fixture_revision,reviewer,result,evidence_json,occurred_at) VALUES(1,1,'decision',1,'synthetic-reviewer',1,'reviewer-b','accepted','[]','2026-10-19T00:00:00Z')")
        self.db.execute("INSERT INTO governed_retention_history(subject_id,operation_id,actor,reason,details_json,occurred_at) VALUES(1,'D-07-E','owner-a','rejected',?, '2026-10-19T00:00:00Z')", (json.dumps({'payload': {'decision_revision': 1, 'review_revision': 1, 'owner_authority':'synthetic-owner', 'owner_revision':1}}),)); self.db.commit()
        before = self.db.execute("SELECT count(*) FROM governed_retention_history").fetchone()[0]
        recovered = retention.recover_rejected_proposal(self.db, subject_identifier='SYN-1', actor=self.owner, expected_version=9, idempotency_key='recover', reason='fresh assessment')
        row = retention.get_subject(self.db,'SYN-1'); self.assertEqual(row['decision_state'],'none'); self.assertEqual(row['approval_state'],'not_recorded')
        self.assertEqual(self.db.execute("SELECT count(*) FROM governed_retention_history").fetchone()[0], before + 1)
        with self.assertRaisesRegex(ValueError,'rejection_recovery_state_invalid'):
            retention.recover_rejected_proposal(self.db, subject_identifier='SYN-1', actor=self.owner, expected_version=recovered['resulting_version'], idempotency_key='recover-bad', reason='bad')
        self.assertEqual(retention.get_subject(self.db,'SYN-1')['version'], recovered['resulting_version'])

    def test_invalidation_does_not_manufacture_approval_or_restore_currentness(self):
        self.db.execute("UPDATE governed_retention_subjects SET retention_review='assessed',inventory_state='complete_with_limits',eligibility_state='eligible_current',decision_state='proposed_eligible_for_future_scope',approval_state='not_recorded',applicability_state='not_evaluated',procedure_state='under_review',version=12 WHERE identifier='SYN-1'"); self.db.commit()
        invalid = retention.invalidate(self.db, subject_identifier='SYN-1', unavailable=False, basis='same-text-new-revision', actor=self.owner, expected_version=12, idempotency_key='invalidate', reason='changed')
        row=retention.get_subject(self.db,'SYN-1'); self.assertEqual(row['approval_state'],'not_recorded'); self.assertEqual(row['applicability_state'],'reassessment_required')
        retention.invalidate(self.db, subject_identifier='SYN-1', unavailable=False, basis='availability-returned', actor=self.owner, expected_version=invalid['resulting_version'], idempotency_key='invalidate-again', reason='observed')
        self.assertEqual(retention.get_subject(self.db,'SYN-1')['applicability_state'],'reassessment_required')

    def test_hold_release_requires_proposal_and_independent_review_atomically(self):
        started = retention.start_initial_review(self.db, subject_identifier="SYN-1", actor=self.owner, expected_version=1, idempotency_key="hold-start", reason="start")
        placed = retention.record_hold(self.db, subject_identifier="SYN-1", operation="place", hold_identifier="H-SYN-1", owner_authority="synthetic-owner", owner_revision=1, evidence=["basis"], scope="synthetic", limitations="limited", actor=self.owner, expected_version=started["resulting_version"], idempotency_key="hold-place", reason="place")
        with self.assertRaisesRegex(ValueError, "hold_release_evidence_required"):
            retention.propose_hold_release(self.db, subject_identifier="SYN-1", hold_identifier="H-SYN-1", evidence=None, actor=self.owner, expected_version=placed["resulting_version"], idempotency_key="hold-propose-missing-evidence", reason="propose")
        self.assertEqual(retention.get_subject(self.db, "SYN-1")["version"], placed["resulting_version"])
        proposed = retention.propose_hold_release(self.db, subject_identifier="SYN-1", hold_identifier="H-SYN-1", evidence=["release-basis"], actor=self.owner, expected_version=placed["resulting_version"], idempotency_key="hold-propose", reason="propose")
        with self.assertRaisesRegex(ValueError, "release_review_required"):
            retention.release_hold(self.db, subject_identifier="SYN-1", hold_identifier="H-SYN-1", owner_authority="synthetic-owner", owner_revision=1, evidence=["release"], scope="synthetic", limitations="limited", actor=self.owner, expected_version=proposed["resulting_version"], idempotency_key="hold-release-refuse", reason="release")
        refused = retention.get_subject(self.db, "SYN-1")
        self.assertEqual(refused["version"], proposed["resulting_version"])
        reviewed = retention.review_hold_release(self.db, subject_identifier="SYN-1", hold_identifier="H-SYN-1", reviewer_authority="synthetic-reviewer", reviewer_revision=1, evidence=["review"], scope="synthetic", limitations="limited", actor=self.reviewer, expected_version=proposed["resulting_version"], idempotency_key="hold-review", reason="review")
        self.db.execute("UPDATE governed_retention_authorities SET available=0 WHERE authority_id='synthetic-reviewer' AND revision=1 AND role='reviewer'"); self.db.commit()
        before = retention.get_subject(self.db, "SYN-1")
        before_counts = tuple(self.db.execute("SELECT (SELECT count(*) FROM governed_retention_holds), (SELECT count(*) FROM governed_retention_history), (SELECT count(*) FROM governed_retention_receipts)").fetchone())
        with self.assertRaisesRegex(ValueError, "authority_unavailable"):
            retention.release_hold(self.db, subject_identifier="SYN-1", hold_identifier="H-SYN-1", owner_authority="synthetic-owner", owner_revision=1, evidence=["release"], scope="synthetic", limitations="limited", actor=self.owner, expected_version=reviewed["resulting_version"], idempotency_key="hold-release-stale-reviewer", reason="release")
        after = retention.get_subject(self.db, "SYN-1")
        after_counts = tuple(self.db.execute("SELECT (SELECT count(*) FROM governed_retention_holds), (SELECT count(*) FROM governed_retention_history), (SELECT count(*) FROM governed_retention_receipts)").fetchone())
        self.assertEqual((after['stored_tuple'], after['version'], after_counts), (before['stored_tuple'], before['version'], before_counts))
        self.db.execute("UPDATE governed_retention_authorities SET available=1 WHERE authority_id='synthetic-reviewer' AND revision=1 AND role='reviewer'"); self.db.commit()
        released = retention.release_hold(self.db, subject_identifier="SYN-1", hold_identifier="H-SYN-1", owner_authority="synthetic-owner", owner_revision=1, evidence=["release"], scope="synthetic", limitations="limited", actor=self.owner, expected_version=reviewed["resulting_version"], idempotency_key="hold-release", reason="release")
        item = retention.get_subject(self.db, "SYN-1")
        self.assertEqual(item["version"], released["resulting_version"])
        self.assertEqual(item["active_holds"], [])

    def test_hold_release_review_requires_bound_scope_and_limits_without_partial_write(self):
        started = retention.start_initial_review(self.db, subject_identifier="SYN-1", actor=self.owner, expected_version=1, idempotency_key="h07-start", reason="start")
        placed = retention.record_hold(self.db, subject_identifier="SYN-1", operation="place", hold_identifier="H-H07", owner_authority="synthetic-owner", owner_revision=1, evidence=["basis"], scope="scope", limitations="limits", actor=self.owner, expected_version=started["resulting_version"], idempotency_key="h07-place", reason="place")
        proposed = retention.propose_hold_release(self.db, subject_identifier="SYN-1", hold_identifier="H-H07", evidence=["release basis"], actor=self.owner, expected_version=placed["resulting_version"], idempotency_key="h07-propose", reason="propose")
        before = (retention.get_subject(self.db, "SYN-1")["stored_tuple"], retention.get_subject(self.db, "SYN-1")["version"], self.db.execute("SELECT count(*) FROM governed_retention_reviews").fetchone()[0], self.db.execute("SELECT count(*) FROM governed_retention_history").fetchone()[0])
        with self.assertRaisesRegex(ValueError, "hold_scope_required"):
            retention.review_hold_release(self.db, subject_identifier="SYN-1", hold_identifier="H-H07", reviewer_authority="synthetic-reviewer", reviewer_revision=1, evidence=["review"], scope=None, limitations="limits", actor=self.reviewer, expected_version=proposed["resulting_version"], idempotency_key="h07-no-scope", reason="review")
        after = (retention.get_subject(self.db, "SYN-1")["stored_tuple"], retention.get_subject(self.db, "SYN-1")["version"], self.db.execute("SELECT count(*) FROM governed_retention_reviews").fetchone()[0], self.db.execute("SELECT count(*) FROM governed_retention_history").fetchone()[0])
        self.assertEqual(after, before)
        reviewed = retention.review_hold_release(self.db, subject_identifier="SYN-1", hold_identifier="H-H07", reviewer_authority="synthetic-reviewer", reviewer_revision=1, evidence=["review"], scope="scope", limitations="limits", actor=self.reviewer, expected_version=proposed["resulting_version"], idempotency_key="h07-ok", reason="review")
        stored = json.loads(self.db.execute("SELECT evidence_json FROM governed_retention_reviews WHERE subject_id=1 AND action='hold_release' ORDER BY id DESC LIMIT 1").fetchone()[0])
        self.assertEqual(stored, {"evidence": ["review"], "scope": "scope", "limitations": "limits"})
        self.assertEqual(reviewed["operation"], "H-07")

    def test_hold_release_rejects_legacy_review_without_scope_or_limits_atomically(self):
        started = retention.start_initial_review(self.db, subject_identifier="SYN-1", actor=self.owner, expected_version=1, idempotency_key="h08-start", reason="start")
        placed = retention.record_hold(self.db, subject_identifier="SYN-1", operation="place", hold_identifier="H-H08", owner_authority="synthetic-owner", owner_revision=1, evidence=["basis"], scope="scope", limitations="limits", actor=self.owner, expected_version=started["resulting_version"], idempotency_key="h08-place", reason="place")
        proposed = retention.propose_hold_release(self.db, subject_identifier="SYN-1", hold_identifier="H-H08", evidence=["release basis"], actor=self.owner, expected_version=placed["resulting_version"], idempotency_key="h08-propose", reason="propose")
        action = self.db.execute("SELECT * FROM governed_retention_hold_actions WHERE subject_id=1 AND action='release' ORDER BY id DESC LIMIT 1").fetchone()
        self.db.execute("INSERT INTO governed_retention_reviews(subject_id,decision_id,action,revision,reviewer_fixture_id,reviewer_fixture_revision,reviewer,result,evidence_json,occurred_at) VALUES(?,?,?,?,?,?,?,?,?,?)", (1, action["id"], "hold_release", action["revision"], "synthetic-reviewer", 1, self.reviewer, "accepted", '[\"legacy-evidence\"]', "2026-10-19T00:00:00Z"))
        self.db.commit()
        before = (retention.get_subject(self.db, "SYN-1")["stored_tuple"], retention.get_subject(self.db, "SYN-1")["version"], self.db.execute("SELECT count(*) FROM governed_retention_holds").fetchone()[0], self.db.execute("SELECT count(*) FROM governed_retention_history").fetchone()[0])
        with self.assertRaisesRegex(ValueError, "hold_release_review_required"):
            retention.release_hold(self.db, subject_identifier="SYN-1", hold_identifier="H-H08", owner_authority="synthetic-owner", owner_revision=1, evidence=["release"], scope="scope", limitations="limits", actor=self.owner, expected_version=proposed["resulting_version"], idempotency_key="h08-legacy-review", reason="release")
        after = (retention.get_subject(self.db, "SYN-1")["stored_tuple"], retention.get_subject(self.db, "SYN-1")["version"], self.db.execute("SELECT count(*) FROM governed_retention_holds").fetchone()[0], self.db.execute("SELECT count(*) FROM governed_retention_history").fetchone()[0])
        self.assertEqual(after, before)

    def test_open_release_with_decision_only_unavailable_evidence_preserves_history(self):
        started = retention.start_initial_review(self.db, subject_identifier="SYN-1", actor=self.owner, expected_version=1, idempotency_key="h08u-start", reason="start")
        placed = retention.record_hold(self.db, subject_identifier="SYN-1", operation="place", hold_identifier="H-H08U", owner_authority="synthetic-owner", owner_revision=1, evidence=["basis"], scope="scope", limitations="limits", actor=self.owner, expected_version=started["resulting_version"], idempotency_key="h08u-place", reason="place")
        proposed = retention.propose_hold_release(self.db, subject_identifier="SYN-1", hold_identifier="H-H08U", evidence=["release basis"], actor=self.owner, expected_version=placed["resulting_version"], idempotency_key="h08u-propose", reason="propose")
        reviewed = retention.review_hold_release(self.db, subject_identifier="SYN-1", hold_identifier="H-H08U", reviewer_authority="synthetic-reviewer", reviewer_revision=1, evidence=["review"], scope="scope", limitations="limits", actor=self.reviewer, expected_version=proposed["resulting_version"], idempotency_key="h08u-review", reason="review")
        self.db.execute("UPDATE governed_retention_subjects SET retention_review='assessed',inventory_state='incomplete',eligibility_state='ineligible_current',decision_state='proposed_ineligible_for_future_scope',approval_state='approved_current',applicability_state='unavailable',procedure_state='under_review',version=? WHERE identifier='SYN-1'", (reviewed["resulting_version"],))
        self.db.execute("INSERT INTO governed_retention_assessments(subject_id,subject_revision,subject_binding_json,policy_id,policy_revision,outcome,blocker,evidence_json,limitations,next_review_json,actor,occurred_at) VALUES(1,1,'{}','policy-syn',1,'ineligible','applicable_active_hold','[\"hold\"]','limits','{}','owner-a','2026-10-19T00:00:00Z')")
        self.db.execute("INSERT INTO governed_retention_decisions(subject_id,assessment_id,revision,outcome,bindings_json,actor,occurred_at) VALUES(1,1,1,'ineligible','{}','owner-a','2026-10-19T00:00:00Z')")
        self.db.execute("INSERT INTO governed_retention_approvals(subject_id,decision_id,revision,owner_fixture_id,owner_fixture_revision,actor,occurred_at) VALUES(1,1,1,'synthetic-owner',1,'owner-a','2026-10-19T00:00:00Z')")
        self.db.commit()
        history_before = self.db.execute("SELECT count(*) FROM governed_retention_history").fetchone()[0]
        released = retention.release_hold(self.db, subject_identifier="SYN-1", hold_identifier="H-H08U", owner_authority="synthetic-owner", owner_revision=1, evidence=["release"], scope="scope", limitations="limits", actor=self.owner, expected_version=reviewed["resulting_version"], idempotency_key="h08u-release", reason="release")
        item = retention.get_subject(self.db, "SYN-1")
        self.assertEqual((released["operation"], item["tuple"]), ("H-08", ("assessed", "incomplete", "unavailable", "proposed_ineligible_for_future_scope", "unavailable", "unavailable", "under_review")))
        self.assertEqual(self.db.execute("SELECT count(*) FROM governed_retention_history").fetchone()[0], history_before + 1)
        self.assertEqual(self.db.execute("SELECT state FROM governed_retention_holds WHERE subject_id=1 AND hold_identifier='H-H08U' ORDER BY revision DESC LIMIT 1").fetchone()[0], "released")

    def test_closed_release_requires_attributable_active_closure_without_writes(self):
        started = retention.start_initial_review(self.db, subject_identifier='SYN-1', actor=self.owner, expected_version=1, idempotency_key='h10-start', reason='start')
        placed = retention.record_hold(self.db, subject_identifier='SYN-1', operation='place', hold_identifier='H-H10-GUARD', owner_authority='synthetic-owner', owner_revision=1, evidence=['basis'], scope='scope', limitations='limits', actor=self.owner, expected_version=started['resulting_version'], idempotency_key='h10-place', reason='place')
        proposed = retention.propose_hold_release(self.db, subject_identifier='SYN-1', hold_identifier='H-H10-GUARD', evidence=['proposal'], actor=self.owner, expected_version=placed['resulting_version'], idempotency_key='h10-propose', reason='propose')
        reviewed = retention.review_hold_release(self.db, subject_identifier='SYN-1', hold_identifier='H-H10-GUARD', reviewer_authority='synthetic-reviewer', reviewer_revision=1, evidence=['review'], scope='scope', limitations='limits', actor=self.reviewer, expected_version=proposed['resulting_version'], idempotency_key='h10-review', reason='review')
        self.db.execute("UPDATE governed_retention_subjects SET procedure_state='closed' WHERE identifier='SYN-1'"); self.db.commit()
        before = (retention.get_subject(self.db, 'SYN-1')['stored_tuple'], self.db.execute("SELECT count(*) FROM governed_retention_holds").fetchone()[0], self.db.execute("SELECT count(*) FROM governed_retention_history").fetchone()[0])
        with self.assertRaisesRegex(ValueError, 'active_closure_history_required'):
            retention.release_hold(self.db, subject_identifier='SYN-1', hold_identifier='H-H10-GUARD', owner_authority='synthetic-owner', owner_revision=1, evidence=['release'], scope='scope', limitations='limits', actor=self.owner, expected_version=reviewed['resulting_version'], idempotency_key='h10-fake-closed', reason='release')
        self.assertEqual((retention.get_subject(self.db, 'SYN-1')['stored_tuple'], self.db.execute("SELECT count(*) FROM governed_retention_holds").fetchone()[0], self.db.execute("SELECT count(*) FROM governed_retention_history").fetchone()[0]), before)

    def test_policy_bound_owner_fixture_refuses_hold_write_atomically(self):
        started = retention.start_initial_review(self.db, subject_identifier="SYN-1", actor=self.owner, expected_version=1, idempotency_key="policy-owner-start", reason="start")
        policy = self._policy_document()
        policy["owner_authority_id"] = "other-owner"
        self.db.execute("UPDATE governed_retention_policies SET policy_json=? WHERE policy_id='policy-syn' AND revision=1", (json.dumps(policy),)); self.db.commit()
        before = (retention.get_subject(self.db, "SYN-1")["stored_tuple"], retention.get_subject(self.db, "SYN-1")["version"], len(retention.get_subject(self.db, "SYN-1")["history"]), self.db.execute("SELECT count(*) FROM governed_retention_holds").fetchone()[0])
        with self.assertRaisesRegex(ValueError, "policy_authority_binding_invalid"):
            retention.record_hold(self.db, subject_identifier="SYN-1", operation="place", hold_identifier="H-POLICY-OWNER", owner_authority="synthetic-owner", owner_revision=1, evidence=["basis"], scope="scope", limitations="limits", actor=self.owner, expected_version=started["resulting_version"], idempotency_key="policy-owner-refuse", reason="place")
        after = (retention.get_subject(self.db, "SYN-1")["stored_tuple"], retention.get_subject(self.db, "SYN-1")["version"], len(retention.get_subject(self.db, "SYN-1")["history"]), self.db.execute("SELECT count(*) FROM governed_retention_holds").fetchone()[0])
        self.assertEqual(after, before)

    def test_policy_bound_reviewer_and_action_map_refuse_release_review_atomically(self):
        started = retention.start_initial_review(self.db, subject_identifier="SYN-1", actor=self.owner, expected_version=1, idempotency_key="policy-review-start", reason="start")
        placed = retention.record_hold(self.db, subject_identifier="SYN-1", operation="place", hold_identifier="H-POLICY-REVIEW", owner_authority="synthetic-owner", owner_revision=1, evidence=["basis"], scope="scope", limitations="limits", actor=self.owner, expected_version=started["resulting_version"], idempotency_key="policy-review-place", reason="place")
        proposed = retention.propose_hold_release(self.db, subject_identifier="SYN-1", hold_identifier="H-POLICY-REVIEW", evidence=["release basis"], actor=self.owner, expected_version=placed["resulting_version"], idempotency_key="policy-review-propose", reason="propose")
        policy = self._policy_document()
        policy["reviewer_authority_id"] = "other-reviewer"
        self.db.execute("UPDATE governed_retention_policies SET policy_json=? WHERE policy_id='policy-syn' AND revision=1", (json.dumps(policy),)); self.db.commit()
        before = (retention.get_subject(self.db, "SYN-1")["stored_tuple"], retention.get_subject(self.db, "SYN-1")["version"], self.db.execute("SELECT count(*) FROM governed_retention_reviews").fetchone()[0], self.db.execute("SELECT count(*) FROM governed_retention_history").fetchone()[0])
        with self.assertRaisesRegex(ValueError, "policy_authority_binding_invalid"):
            retention.review_hold_release(self.db, subject_identifier="SYN-1", hold_identifier="H-POLICY-REVIEW", reviewer_authority="synthetic-reviewer", reviewer_revision=1, evidence=["review"], scope="scope", limitations="limits", actor=self.reviewer, expected_version=proposed["resulting_version"], idempotency_key="policy-review-refuse", reason="review")
        after = (retention.get_subject(self.db, "SYN-1")["stored_tuple"], retention.get_subject(self.db, "SYN-1")["version"], self.db.execute("SELECT count(*) FROM governed_retention_reviews").fetchone()[0], self.db.execute("SELECT count(*) FROM governed_retention_history").fetchone()[0])
        self.assertEqual(after, before)

    def test_policy_missing_required_action_map_entry_refuses_before_hold_mutation(self):
        started = retention.start_initial_review(self.db, subject_identifier="SYN-1", actor=self.owner, expected_version=1, idempotency_key="map-start", reason="start")
        policy = self._policy_document()
        del policy["action_review_map"]["hold_amendment"]
        self.db.execute("UPDATE governed_retention_policies SET policy_json=? WHERE policy_id='policy-syn' AND revision=1", (json.dumps(policy),)); self.db.commit()
        before_row = dict(self.db.execute("SELECT retention_review,inventory_state,eligibility_state,decision_state,approval_state,applicability_state,procedure_state,version FROM governed_retention_subjects WHERE identifier='SYN-1'").fetchone())
        before = (before_row, self.db.execute("SELECT count(*) FROM governed_retention_holds").fetchone()[0], self.db.execute("SELECT count(*) FROM governed_retention_history").fetchone()[0])
        with self.assertRaisesRegex(ValueError, "policy_schema_invalid"):
            retention.record_hold(self.db, subject_identifier="SYN-1", operation="place", hold_identifier="H-MAP", owner_authority="synthetic-owner", owner_revision=1, evidence=["basis"], scope="scope", limitations="limits", actor=self.owner, expected_version=started["resulting_version"], idempotency_key="map-refuse", reason="place")
        after_row = dict(self.db.execute("SELECT retention_review,inventory_state,eligibility_state,decision_state,approval_state,applicability_state,procedure_state,version FROM governed_retention_subjects WHERE identifier='SYN-1'").fetchone())
        after = (after_row, self.db.execute("SELECT count(*) FROM governed_retention_holds").fetchone()[0], self.db.execute("SELECT count(*) FROM governed_retention_history").fetchone()[0])
        self.assertEqual(after, before)

    def test_open_hold_placement_phase_selects_invalidation_without_restoring_history(self):
        phases = (
            ("A", "none", "not_recorded", "eligible_current", "current", "not_recorded", "stale", "reassessment_required"),
            ("P", "proposed_eligible_for_future_scope", "not_recorded", "eligible_current", "not_evaluated", "not_recorded", "stale", "reassessment_required"),
            ("R", "proposed_eligible_for_future_scope", "not_approved", "eligible_current", "not_evaluated", "not_approved", "stale", "reassessment_required"),
            ("O", "proposed_eligible_for_future_scope", "approved_current", "eligible_current", "current", "stale", "stale", "reassessment_required"),
            ("U", "proposed_eligible_for_future_scope", "unavailable", "unavailable", "unavailable", "unavailable", "unavailable", "unavailable"),
        )
        for index, (label, decision, approval, eligibility, applicability, expected_approval, expected_eligibility, expected_applicability) in enumerate(phases):
            with self.subTest(phase=label):
                version = 40 + index
                self.db.execute("UPDATE governed_retention_subjects SET retention_review='assessed',inventory_state='incomplete',eligibility_state=?,decision_state=?,approval_state=?,applicability_state=?,procedure_state='under_review',version=? WHERE identifier='SYN-1'", (eligibility, decision, approval, applicability, version)); self.db.commit()
                result = retention.record_hold(self.db, subject_identifier="SYN-1", operation="place", hold_identifier=f"H-PHASE-{label}", owner_authority="synthetic-owner", owner_revision=1, evidence=["basis"], scope="scope", limitations="limits", actor=self.owner, expected_version=version, idempotency_key=f"hold-phase-{label}", reason="place")
                row = retention.get_subject(self.db, "SYN-1")
                self.assertEqual((row["eligibility_state"], row["approval_state"], row["applicability_state"]), (expected_eligibility, expected_approval, expected_applicability))
                self.assertEqual(result["operation"], "H-03")

    def test_hold_amendment_phase_requires_exact_review_and_refuses_without_mutation(self):
        self.db.execute("UPDATE governed_retention_subjects SET retention_review='assessed',inventory_state='incomplete',eligibility_state='eligible_current',decision_state='proposed_eligible_for_future_scope',approval_state='not_approved',applicability_state='not_evaluated',procedure_state='under_review',version=41 WHERE identifier='SYN-1'")
        self.db.execute("INSERT INTO governed_retention_holds(subject_id,hold_identifier,revision,state,basis,evidence_json,scope,limitations,owner_fixture_id,owner_fixture_revision,actor,occurred_at) VALUES(1,'H-PHASE-AMEND',1,'active','basis','[]','scope','limits','synthetic-owner',1,'owner-a','2026-10-19T00:00:00Z')"); self.db.commit()
        before = (retention.get_subject(self.db, "SYN-1")["stored_tuple"], retention.get_subject(self.db, "SYN-1")["version"], self.db.execute("SELECT count(*) FROM governed_retention_holds").fetchone()[0], self.db.execute("SELECT count(*) FROM governed_retention_history").fetchone()[0])
        with self.assertRaisesRegex(ValueError, "hold_amendment_review_required"):
            retention.record_hold(self.db, subject_identifier="SYN-1", operation="amend", hold_identifier="H-PHASE-AMEND", owner_authority="synthetic-owner", owner_revision=1, evidence=["basis"], scope="new", limitations="limits", actor=self.owner, expected_version=41, idempotency_key="phase-amend-refuse", reason="amend")
        self.assertEqual((retention.get_subject(self.db, "SYN-1")["stored_tuple"], retention.get_subject(self.db, "SYN-1")["version"], self.db.execute("SELECT count(*) FROM governed_retention_holds").fetchone()[0], self.db.execute("SELECT count(*) FROM governed_retention_history").fetchone()[0]), before)
        payload = {"hold":"H-PHASE-AMEND", "hold_revision":1, "subject_revision":1, "subject_binding_json":"{}", "policy_id":"policy-syn", "policy_revision":1}
        self.db.execute("INSERT INTO governed_retention_history(subject_id,operation_id,actor,reason,details_json,occurred_at) VALUES(1,'H-05','owner-a','review',?,'2026-10-19T00:00:00Z')", (json.dumps({"payload":payload}),)); self.db.commit()
        amended = retention.record_hold(self.db, subject_identifier="SYN-1", operation="amend", hold_identifier="H-PHASE-AMEND", owner_authority="synthetic-owner", owner_revision=1, evidence=["basis"], scope="new", limitations="limits", actor=self.owner, expected_version=41, idempotency_key="phase-amend", reason="amend")
        row = retention.get_subject(self.db, "SYN-1")
        self.assertEqual((amended["operation"], row["eligibility_state"], row["approval_state"], row["applicability_state"]), ("H-04", "stale", "not_approved", "reassessment_required"))

    def test_release_action_subject_policy_binding_refuses_review_without_partial_write(self):
        started = retention.start_initial_review(self.db, subject_identifier='SYN-1', actor=self.owner, expected_version=1, idempotency_key='hbind-start', reason='start')
        placed = retention.record_hold(self.db, subject_identifier='SYN-1', operation='place', hold_identifier='H-BIND', owner_authority='synthetic-owner', owner_revision=1, evidence=['basis'], scope='scope', limitations='limits', actor=self.owner, expected_version=started['resulting_version'], idempotency_key='hbind-place', reason='place')
        proposed = retention.propose_hold_release(self.db, subject_identifier='SYN-1', hold_identifier='H-BIND', evidence=['basis'], actor=self.owner, expected_version=placed['resulting_version'], idempotency_key='hbind-propose', reason='propose')
        self.db.execute("UPDATE governed_retention_subjects SET subject_revision=2,subject_binding_json=? WHERE identifier='SYN-1'", (json.dumps({'synthetic_revision': 2}),)); self.db.commit()
        before = (dict(self.db.execute("SELECT * FROM governed_retention_subjects WHERE identifier='SYN-1'").fetchone()), self.db.execute("SELECT count(*) FROM governed_retention_reviews").fetchone()[0], self.db.execute("SELECT count(*) FROM governed_retention_history").fetchone()[0])
        with self.assertRaisesRegex(ValueError, 'hold_release_binding_invalid'):
            retention.review_hold_release(self.db, subject_identifier='SYN-1', hold_identifier='H-BIND', reviewer_authority='synthetic-reviewer', reviewer_revision=1, evidence=['review'], scope='scope', limitations='limits', actor=self.reviewer, expected_version=proposed['resulting_version'], idempotency_key='hbind-review', reason='review')
        after = (dict(self.db.execute("SELECT * FROM governed_retention_subjects WHERE identifier='SYN-1'").fetchone()), self.db.execute("SELECT count(*) FROM governed_retention_reviews").fetchone()[0], self.db.execute("SELECT count(*) FROM governed_retention_history").fetchone()[0])
        self.assertEqual(after, before)

    def test_hold_applicability_rejects_caller_boolean_and_observational_review_is_nonconsequential(self):
        started = retention.start_initial_review(self.db, subject_identifier='SYN-1', actor=self.owner, expected_version=1, idempotency_key='obs-start', reason='start')
        placed = retention.record_hold(self.db, subject_identifier='SYN-1', operation='place', hold_identifier='H-OBS', owner_authority='synthetic-owner', owner_revision=1, evidence=['basis'], scope='scope', limitations='limits', actor=self.owner, expected_version=started['resulting_version'], idempotency_key='obs-place', reason='place')
        with self.assertRaisesRegex(ValueError, 'applicability_assessment_required'):
            retention.assess_hold_context(self.db, subject_identifier='SYN-1', hold_identifier='H-OBS', applicability=True, evidence=['evidence'], scope='scope', limitations='limits', actor=self.owner, expected_version=placed['resulting_version'], idempotency_key='obs-bool', reason='bad')
        self.assertEqual(retention.get_subject(self.db, 'SYN-1')['version'], placed['resulting_version'])
        reviewed = retention.review_hold_observational(self.db, subject_identifier='SYN-1', hold_identifier='H-OBS', findings='observed', next_point='next', actor=self.owner, expected_version=placed['resulting_version'], idempotency_key='obs-review', reason='review')
        item = retention.get_subject(self.db, 'SYN-1')
        self.assertEqual((item['eligibility_state'], item['decision_state']), ('stale','none'))
        self.assertEqual(reviewed['operation'], 'H-05')

    def test_hold_applicability_requires_exact_current_bounded_search_without_partial_write(self):
        started = retention.start_initial_review(self.db, subject_identifier='SYN-1', actor=self.owner, expected_version=1, idempotency_key='hctx-start', reason='start')
        placed = retention.record_hold(self.db, subject_identifier='SYN-1', operation='place', hold_identifier='H-CTX', owner_authority='synthetic-owner', owner_revision=1, evidence=['basis'], scope='scope', limitations='limits', actor=self.owner, expected_version=started['resulting_version'], idempotency_key='hctx-place', reason='place')
        before = (retention.get_subject(self.db, 'SYN-1')['stored_tuple'], self.db.execute("SELECT count(*) FROM governed_retention_history").fetchone()[0])
        with self.assertRaisesRegex(ValueError, 'hold_search_binding_required'):
            retention.assess_hold_context(self.db, subject_identifier='SYN-1', hold_identifier='H-CTX', applicability='applicable', evidence=['assessment'], scope='scope', limitations='limits', actor=self.owner, expected_version=placed['resulting_version'], idempotency_key='hctx-no-search', reason='assess')
        self.assertEqual((retention.get_subject(self.db, 'SYN-1')['stored_tuple'], self.db.execute("SELECT count(*) FROM governed_retention_history").fetchone()[0]), before)
        searched = retention.assess_hold_context(self.db, subject_identifier='SYN-1', hold_identifier=None, applicability=None, evidence=['search'], scope='scope', limitations='limits', actor=self.owner, expected_version=placed['resulting_version'], idempotency_key='hctx-search', reason='search')
        assessed = retention.assess_hold_context(self.db, subject_identifier='SYN-1', hold_identifier='H-CTX', applicability='applicable', evidence=['assessment'], scope='scope', limitations='limits', actor=self.owner, expected_version=searched['resulting_version'], idempotency_key='hctx-assess', reason='assess')
        self.assertEqual(assessed['operation'], 'H-02')

    def test_hold_amendment_refuses_review_bound_to_prior_subject_evidence(self):
        started = retention.start_initial_review(self.db, subject_identifier='SYN-1', actor=self.owner, expected_version=1, idempotency_key='hamend-start', reason='start')
        placed = retention.record_hold(self.db, subject_identifier='SYN-1', operation='place', hold_identifier='H-AMEND-BIND', owner_authority='synthetic-owner', owner_revision=1, evidence=['basis'], scope='scope', limitations='limits', actor=self.owner, expected_version=started['resulting_version'], idempotency_key='hamend-place', reason='place')
        reviewed = retention.review_hold_observational(self.db, subject_identifier='SYN-1', hold_identifier='H-AMEND-BIND', findings='reviewed', next_point='next', actor=self.owner, expected_version=placed['resulting_version'], idempotency_key='hamend-review', reason='review')
        self.db.execute("UPDATE governed_retention_subjects SET subject_revision=2,subject_binding_json=? WHERE identifier='SYN-1'", (json.dumps({'synthetic_revision': 2}),)); self.db.commit()
        before = (self.db.execute("SELECT count(*) FROM governed_retention_holds").fetchone()[0], self.db.execute("SELECT count(*) FROM governed_retention_history").fetchone()[0], self.db.execute("SELECT version FROM governed_retention_subjects WHERE identifier='SYN-1'").fetchone()[0])
        with self.assertRaisesRegex(ValueError, 'amendment_review_required'):
            retention.record_hold(self.db, subject_identifier='SYN-1', operation='amend', hold_identifier='H-AMEND-BIND', owner_authority='synthetic-owner', owner_revision=1, evidence=['amended'], scope='scope2', limitations='limits', actor=self.owner, expected_version=reviewed['resulting_version'], idempotency_key='hamend-refuse', reason='amend')
        self.assertEqual((self.db.execute("SELECT count(*) FROM governed_retention_holds").fetchone()[0], self.db.execute("SELECT count(*) FROM governed_retention_history").fetchone()[0], self.db.execute("SELECT version FROM governed_retention_subjects WHERE identifier='SYN-1'").fetchone()[0]), before)

    def test_false_policy_closed_observational_cycle_preserves_current_decision(self):
        self.db.execute("UPDATE governed_retention_policies SET policy_json=? WHERE policy_id='policy-syn' AND revision=1", (json.dumps(self._policy_document(False, identity='rr-point', due_at='2026-01-01T00:00:00Z')),))
        self.db.commit()
        started_initial = retention.start_initial_review(self.db, subject_identifier='SYN-1', actor=self.owner, expected_version=1, idempotency_key='rr-initial', reason='start')
        copies = {name: {'applicable': True, 'identity': name, 'control': 'synthetic'} for name in retention.COPY_CLASSES}
        inventory = retention.record_inventory(self.db, subject_identifier='SYN-1', outcome='complete_with_limits', copies=copies, evidence=['inventory'], limitations='limits', actor=self.owner, expected_version=started_initial['resulting_version'], idempotency_key='rr-inventory', reason='inventory')
        assessed_review = retention.complete_review(self.db, subject_identifier='SYN-1', evidence=['review'], limitations='limits', actor=self.owner, expected_version=inventory['resulting_version'], idempotency_key='rr-initial-complete', reason='complete')
        searched = retention.assess_hold_context(self.db, subject_identifier='SYN-1', hold_identifier=None, applicability=None, evidence=['search'], scope='synthetic', limitations='limits', actor=self.owner, expected_version=assessed_review['resulting_version'], idempotency_key='rr-search', reason='search')
        assessed = retention.assess_decision(self.db, subject_identifier='SYN-1', outcome='eligible', blocker=None, evidence=['conditions'], limitations='limits', next_review=None, actor=self.owner, expected_version=searched['resulting_version'], idempotency_key='rr-assess', reason='assess')
        proposed = retention.propose_decision(self.db, subject_identifier='SYN-1', outcome='eligible', actor=self.owner, expected_version=assessed['resulting_version'], idempotency_key='rr-propose', reason='propose')
        reviewed = retention.independent_review(self.db, subject_identifier='SYN-1', reviewer_authority='synthetic-reviewer', reviewer_revision=1, actor=self.reviewer, expected_version=proposed['resulting_version'], idempotency_key='rr-review', reason='review', evidence=['review'])
        approved = retention.owner_decision(self.db, subject_identifier='SYN-1', approve=True, owner_authority='synthetic-owner', owner_revision=1, actor=self.owner, expected_version=reviewed['resulting_version'], idempotency_key='rr-approve', reason='approve')
        closed = retention.close(self.db, subject_identifier='SYN-1', actor=self.owner, expected_version=approved['resulting_version'], idempotency_key='rr-close', reason='close')
        due = retention.apply_review_due(self.db, subject_identifier='SYN-1', reached_point='rr-point', actor=self.owner, expected_version=closed['resulting_version'], idempotency_key='rr-due', reason='due')
        started = retention.recurring_review(self.db, subject_identifier='SYN-1', action='start', actor=self.owner, expected_version=due['resulting_version'], idempotency_key='rr-start', reason='start')
        waiting = retention.recurring_review(self.db, subject_identifier='SYN-1', action='await_information', details={'missing_information':'review source'}, actor=self.owner, expected_version=started['resulting_version'], idempotency_key='rr-await', reason='await')
        resumed = retention.recurring_review(self.db, subject_identifier='SYN-1', action='resume_information', details={'evidence':'new source'}, actor=self.owner, expected_version=waiting['resulting_version'], idempotency_key='rr-resume', reason='resume')
        deferred = retention.recurring_review(self.db, subject_identifier='SYN-1', action='defer', details={'next_point':'later', 'responsible':'owner-a'}, actor=self.owner, expected_version=resumed['resulting_version'], idempotency_key='rr-defer', reason='defer')
        due_again = retention.recurring_review(self.db, subject_identifier='SYN-1', action='resume_deferred', details={'resumption_basis':'point reached'}, actor=self.owner, expected_version=deferred['resulting_version'], idempotency_key='rr-deferred-resume', reason='resume deferred')
        complete = retention.recurring_review(self.db, subject_identifier='SYN-1', action='complete', details={'next_point':'next', 'responsible':'owner-a'}, actor=self.owner, expected_version=due_again['resulting_version'], idempotency_key='rr-complete', reason='complete')
        item = retention.get_subject(self.db, 'SYN-1')
        # The completed observational review did not create a replacement
        # fixture point, so the original reached point remains prominent on
        # retrieval without invalidating this false-policy chain.
        self.assertEqual((item['retention_review'], item['approval_state'], item['applicability_state'], item['procedure_state']), ('assessed','approved_current','current','closed'))
        with self.assertRaisesRegex(ValueError, 'recurring_review_start_invalid'):
            retention.recurring_review(self.db, subject_identifier='SYN-1', action='start', actor=self.owner, expected_version=complete['resulting_version'], idempotency_key='rr-again', reason='bad')
        self.assertEqual(retention.get_subject(self.db, 'SYN-1')['version'], complete['resulting_version'])

    def test_false_policy_recurring_review_refuses_unbound_approved_tuple_without_writes(self):
        self.db.execute("UPDATE governed_retention_policies SET policy_json=? WHERE policy_id='policy-syn' AND revision=1", (json.dumps(self._policy_document(False, identity='unbound-cycle', due_at='2026-01-01T00:00:00Z')),))
        self.db.execute("UPDATE governed_retention_subjects SET retention_review='due',inventory_state='complete_with_limits',eligibility_state='eligible_current',decision_state='proposed_eligible_for_future_scope',approval_state='approved_current',applicability_state='current',procedure_state='closed',version=31 WHERE identifier='SYN-1'"); self.db.commit()
        before = (dict(self.db.execute("SELECT * FROM governed_retention_subjects WHERE identifier='SYN-1'").fetchone()), self.db.execute("SELECT count(*) FROM governed_retention_recurring_reviews").fetchone()[0], self.db.execute("SELECT count(*) FROM governed_retention_history").fetchone()[0])
        with self.assertRaisesRegex(ValueError, 'recurring_review_binding_invalid'):
            retention.recurring_review(self.db, subject_identifier='SYN-1', action='start', actor=self.owner, expected_version=31, idempotency_key='unbound-cycle-start', reason='start')
        after = (dict(self.db.execute("SELECT * FROM governed_retention_subjects WHERE identifier='SYN-1'").fetchone()), self.db.execute("SELECT count(*) FROM governed_retention_recurring_reviews").fetchone()[0], self.db.execute("SELECT count(*) FROM governed_retention_history").fetchone()[0])
        self.assertEqual(after, before)

    def test_rd_and_rr_refuse_approved_chain_without_immutable_inventory_predecessor(self):
        """A real decision/review/approval still cannot omit proposal inventory."""
        self.db.execute("UPDATE governed_retention_policies SET policy_json=? WHERE policy_id='policy-syn' AND revision=1", (json.dumps(self._policy_document(False, identity='missing-inventory-chain', due_at='2026-01-01T00:00:00Z')),))
        self.db.execute("UPDATE governed_retention_subjects SET retention_review='assessed',inventory_state='complete_with_limits',eligibility_state='eligible_current',decision_state='proposed_eligible_for_future_scope',approval_state='approved_current',applicability_state='current',procedure_state='under_review',version=33 WHERE identifier='SYN-1'")
        self.db.execute("INSERT INTO governed_retention_assessments(subject_id,subject_revision,subject_binding_json,policy_id,policy_revision,outcome,blocker,evidence_json,limitations,next_review_json,actor,occurred_at) VALUES(1,1,'{}','policy-syn',1,'eligible',NULL,'[\"evidence\"]','limits',NULL,'owner-a','2026-10-19T00:00:00Z')")
        assessment_id = self.db.execute("SELECT last_insert_rowid()").fetchone()[0]
        # This direct fixture deliberately omits inventory_assessment_id.
        bindings = json.dumps({'subject_revision':1, 'subject_binding_json':'{}', 'policy_id':'policy-syn', 'policy_revision':1})
        self.db.execute("INSERT INTO governed_retention_decisions(subject_id,assessment_id,revision,outcome,bindings_json,actor,occurred_at) VALUES(1,?,?, 'eligible',?,'owner-a','2026-10-19T00:00:00Z')", (assessment_id, assessment_id, bindings))
        decision_id = self.db.execute("SELECT last_insert_rowid()").fetchone()[0]
        self.db.execute("INSERT INTO governed_retention_reviews(subject_id,decision_id,action,revision,reviewer_fixture_id,reviewer_fixture_revision,reviewer,result,evidence_json,occurred_at) VALUES(1,?,'decision',?,'synthetic-reviewer',1,'reviewer-b','accepted','[\"review\"]','2026-10-19T00:00:00Z')", (decision_id, assessment_id))
        self.db.execute("INSERT INTO governed_retention_approvals(subject_id,decision_id,revision,owner_fixture_id,owner_fixture_revision,actor,occurred_at) VALUES(1,?,?,'synthetic-owner',1,'owner-a','2026-10-19T00:00:00Z')", (decision_id, assessment_id)); self.db.commit()
        before = (retention.get_subject(self.db, 'SYN-1')['stored_tuple'], self.db.execute("SELECT count(*) FROM governed_retention_history").fetchone()[0], self.db.execute("SELECT count(*) FROM governed_retention_recurring_reviews").fetchone()[0])
        with self.assertRaisesRegex(ValueError, 'recurring_review_binding_invalid'):
            retention.apply_review_due(self.db, subject_identifier='SYN-1', reached_point='missing-inventory-chain', actor=self.owner, expected_version=33, idempotency_key='missing-inventory-rd', reason='due')
        self.db.execute("UPDATE governed_retention_subjects SET retention_review='due' WHERE identifier='SYN-1'"); self.db.commit()
        with self.assertRaisesRegex(ValueError, 'recurring_review_binding_invalid'):
            retention.recurring_review(self.db, subject_identifier='SYN-1', action='start', actor=self.owner, expected_version=33, idempotency_key='missing-inventory-rr', reason='start')
        after = (retention.get_subject(self.db, 'SYN-1')['stored_tuple'], self.db.execute("SELECT count(*) FROM governed_retention_history").fetchone()[0], self.db.execute("SELECT count(*) FROM governed_retention_recurring_reviews").fetchone()[0])
        self.assertEqual(after, (('due','complete_with_limits','eligible_current','proposed_eligible_for_future_scope','approved_current','current','under_review'), before[1], before[2]))

    def test_rd_rr_refuse_cross_shaped_approved_history_without_writes(self):
        self.db.execute("UPDATE governed_retention_policies SET policy_json=? WHERE policy_id='policy-syn' AND revision=1", (json.dumps(self._policy_document(False, identity='cross-shaped-chain', due_at='2026-01-01T00:00:00Z')),))
        self.db.commit()
        self._seed_current_approved_chain(version=34)
        self.db.execute("UPDATE governed_retention_subjects SET eligibility_state='ineligible_current' WHERE identifier='SYN-1'"); self.db.commit()
        before = (retention.get_subject(self.db, 'SYN-1')['stored_tuple'], self.db.execute("SELECT count(*) FROM governed_retention_history").fetchone()[0])
        with self.assertRaisesRegex(ValueError, 'recurring_review_binding_invalid'):
            retention.apply_review_due(self.db, subject_identifier='SYN-1', reached_point='cross-shaped-chain', actor=self.owner, expected_version=34, idempotency_key='cross-shaped-rd', reason='due')
        self.assertEqual((retention.get_subject(self.db, 'SYN-1')['stored_tuple'], self.db.execute("SELECT count(*) FROM governed_retention_history").fetchone()[0]), before)

    def test_rd_refuses_historical_review_that_is_not_independent_without_writes(self):
        self.db.execute("UPDATE governed_retention_policies SET policy_json=? WHERE policy_id='policy-syn' AND revision=1", (json.dumps(self._policy_document(False, identity='self-reviewed-chain', due_at='2026-01-01T00:00:00Z')),))
        self.db.commit()
        self._seed_current_approved_chain(version=35)
        decision = self.db.execute("SELECT * FROM governed_retention_decisions WHERE subject_id=1 ORDER BY id DESC LIMIT 1").fetchone()
        # The appended immutable row is deliberately malformed historical
        # evidence: it must not supersede the valid independent review.
        self.db.execute("INSERT INTO governed_retention_reviews(subject_id,decision_id,action,revision,reviewer_fixture_id,reviewer_fixture_revision,reviewer,result,evidence_json,occurred_at) VALUES(1,?,'decision',?,'synthetic-reviewer',1,'owner-a','accepted','[\"forged\"]','2026-10-20T00:00:00Z')", (decision['id'], decision['revision'])); self.db.commit()
        before = (retention.get_subject(self.db, 'SYN-1')['stored_tuple'], self.db.execute("SELECT count(*) FROM governed_retention_history").fetchone()[0])
        with self.assertRaisesRegex(ValueError, 'recurring_review_binding_invalid'):
            retention.apply_review_due(self.db, subject_identifier='SYN-1', reached_point='self-reviewed-chain', actor=self.owner, expected_version=35, idempotency_key='self-reviewed-rd', reason='due')
        self.assertEqual((retention.get_subject(self.db, 'SYN-1')['stored_tuple'], self.db.execute("SELECT count(*) FROM governed_retention_history").fetchone()[0]), before)

    def test_deferred_predecision_due_preserves_absence_of_approval_for_true_and_false(self):
        for policy_value, key in ((True, 'true'), (False, 'false')):
            self.db.execute("UPDATE governed_retention_policies SET policy_json=? WHERE policy_id='policy-syn' AND revision=1", (json.dumps(self._policy_document(policy_value, identity=f'{key}-point', due_at='2026-01-01T00:00:00Z')),))
            self.db.execute("UPDATE governed_retention_subjects SET retention_review='deferred',inventory_state='incomplete',eligibility_state='pending_missing_information',decision_state='none',approval_state='not_recorded',applicability_state='not_evaluated',procedure_state='under_review',version=? WHERE identifier='SYN-1'", (30 if policy_value else 40,))
            self.db.commit()
            self._seed_initial_deferral_history(f'{key}-point')
            due = retention.apply_review_due(self.db, subject_identifier='SYN-1', reached_point=f'{key}-point', actor=self.owner, expected_version=30 if policy_value else 40, idempotency_key=f'{key}-deferred-due', reason='point reached')
            item = retention.get_subject(self.db, 'SYN-1')
            self.assertEqual((item['retention_review'], item['decision_state'], item['approval_state'], item['applicability_state']), ('due','none','not_recorded','not_evaluated'))
            self.assertEqual(due['operation'], 'RD-05' if policy_value else 'RD-06')

    def test_false_deferred_approved_due_preserves_current_open_and_closed(self):
        self.db.execute("UPDATE governed_retention_policies SET policy_json=? WHERE policy_id='policy-syn' AND revision=1", (json.dumps(self._policy_document(False, identity='under_review-deferred')),))
        for procedure, version, expected_op in (('under_review', 56, 'RD-09'), ('closed', 57, 'RD-10')):
            self.db.execute("UPDATE governed_retention_policies SET policy_json=? WHERE policy_id='policy-syn' AND revision=1", (json.dumps(self._policy_document(False, identity=f'{procedure}-deferred', due_at='2026-01-01T00:00:00Z')),))
            self._seed_current_approved_chain(review='deferred', procedure=procedure, version=version)
            due = retention.apply_review_due(self.db, subject_identifier='SYN-1', reached_point=f'{procedure}-deferred', actor=self.owner, expected_version=version, idempotency_key=f'{procedure}-false-due', reason='due')
            item = retention.get_subject(self.db, 'SYN-1')
            self.assertEqual((due['operation'],item['retention_review'],item['approval_state'],item['applicability_state'],item['procedure_state']), (expected_op,'due','approved_current','current',procedure))

    def test_true_due_recovery_is_open_only_and_preserves_history(self):
        self.db.execute("UPDATE governed_retention_policies SET policy_json=? WHERE policy_id='policy-syn' AND revision=1", (json.dumps(self._policy_document(True, due_at='2026-01-01T00:00:00Z')),))
        self._seed_current_approved_chain(version=50)
        due = retention.apply_review_due(self.db, subject_identifier='SYN-1', reached_point='review-v1', actor=self.owner, expected_version=50, idempotency_key='true-due-observation', reason='due')
        recovered = retention.recover_true_due(self.db, subject_identifier='SYN-1', owner_authority='synthetic-owner', owner_revision=1, actor=self.owner, expected_version=due['resulting_version'], idempotency_key='true-due-recover', reason='fresh assessment')
        item = retention.get_subject(self.db, 'SYN-1')
        # The stored recovery result is a fresh assessment.  The private
        # projection remains visibly due until a policy-consistent next point
        # is recorded, so it cannot make the reached point disappear.
        self.assertEqual(item['stored_tuple'], ('under_assessment','complete_with_limits','under_assessment','none','not_recorded','not_evaluated','under_review'))
        self.assertEqual(item['tuple'][0], 'due')
        self.assertEqual(recovered['operation'], 'TRD-01-E')
        self.db.execute("UPDATE governed_retention_subjects SET procedure_state='closed',retention_review='due',decision_state='proposed_eligible_for_future_scope',approval_state='stale',applicability_state='reassessment_required',eligibility_state='stale',version=? WHERE identifier='SYN-1'", (recovered['resulting_version'],)); self.db.commit()
        with self.assertRaisesRegex(ValueError, 'true_due_recovery_state_invalid'):
            retention.recover_true_due(self.db, subject_identifier='SYN-1', owner_authority='synthetic-owner', owner_revision=1, actor=self.owner, expected_version=recovered['resulting_version'], idempotency_key='true-due-closed', reason='bad')

    def test_true_deferred_due_invalidates_open_and_keeps_closed_historical(self):
        self.db.execute("UPDATE governed_retention_policies SET policy_json=? WHERE policy_id='policy-syn' AND revision=1", (json.dumps(self._policy_document(True, identity='deferred-v1', due_at='2026-01-01T00:00:00Z')),))
        self._seed_current_approved_chain(review='deferred', version=55)
        due = retention.apply_review_due(self.db, subject_identifier='SYN-1', reached_point='deferred-v1', actor=self.owner, expected_version=55, idempotency_key='deferred-due-open', reason='due')
        self.assertEqual(due['operation'], 'RD-07')
        recovered = retention.recover_true_due(self.db, subject_identifier='SYN-1', owner_authority='synthetic-owner', owner_revision=1, actor=self.owner, expected_version=due['resulting_version'], idempotency_key='deferred-due-recover', reason='reassess')
        self.db.execute("UPDATE governed_retention_policies SET policy_json=? WHERE policy_id='policy-syn' AND revision=1", (json.dumps(self._policy_document(True, identity='deferred-v2', due_at='2026-01-01T00:00:00Z')),))
        self.db.execute("UPDATE governed_retention_subjects SET retention_review='deferred',eligibility_state='eligible_current',decision_state='proposed_eligible_for_future_scope',approval_state='approved_current',applicability_state='current',procedure_state='closed',version=? WHERE identifier='SYN-1'", (recovered['resulting_version'],)); self.db.commit()
        self._seed_recurring_deferral_history(outcome='eligible', procedure='closed', point='deferred-v2')
        closed_due = retention.apply_review_due(self.db, subject_identifier='SYN-1', reached_point='deferred-v2', actor=self.owner, expected_version=recovered['resulting_version'], idempotency_key='deferred-due-closed', reason='due')
        item = retention.get_subject(self.db, 'SYN-1')
        self.assertEqual((closed_due['operation'],item['procedure_state'],item['applicability_state']), ('RD-08','closed','reassessment_required'))

    def test_explicit_invalidation_recovery_and_reconsideration_are_open_only(self):
        self.db.execute("UPDATE governed_retention_subjects SET retention_review='assessed',inventory_state='complete_with_limits',eligibility_state='stale',decision_state='proposed_eligible_for_future_scope',approval_state='stale',applicability_state='reassessment_required',procedure_state='under_review',version=60 WHERE identifier='SYN-1'"); self.db.commit()
        self.db.execute("INSERT INTO governed_retention_assessments(subject_id,subject_revision,policy_id,policy_revision,outcome,blocker,evidence_json,limitations,next_review_json,actor,occurred_at) VALUES(1,1,'policy-syn',1,'eligible',NULL,'[]','limits',NULL,'owner-a','2026-10-19T00:00:00Z')"); self.db.commit()
        self.db.execute("INSERT INTO governed_retention_decisions(subject_id,assessment_id,revision,outcome,bindings_json,actor,occurred_at) VALUES(1,1,1,'eligible','{}','owner-a','2026-10-19T00:00:00Z')")
        self.db.execute("INSERT INTO governed_retention_approvals(subject_id,decision_id,revision,owner_fixture_id,owner_fixture_revision,actor,occurred_at) VALUES(1,1,1,'synthetic-owner',1,'owner-a','2026-10-19T00:00:00Z')")
        self.db.commit()
        with self.assertRaisesRegex(ValueError, 'reassessment_outcome_binding_invalid'):
            retention.reassess_after_invalidation(self.db, subject_identifier='SYN-1', outcome='ineligible', owner_authority='synthetic-owner', owner_revision=1, actor=self.owner, expected_version=60, idempotency_key='rs02-wrong', reason='wrong')
        self.assertEqual(retention.get_subject(self.db, 'SYN-1')['version'], 60)
        with self.assertRaisesRegex(ValueError, 'reassessment_invalidation_binding_invalid'):
            retention.reassess_after_invalidation(self.db, subject_identifier='SYN-1', outcome='eligible', owner_authority='synthetic-owner', owner_revision=1, actor=self.owner, expected_version=60, idempotency_key='rs02-no-iv', reason='unbound')
        self.db.execute("INSERT INTO governed_retention_history(subject_id,operation_id,actor,reason,details_json,occurred_at) VALUES(1,'IV-01-O','owner-a','changed','{}','2026-10-19T00:00:00Z')"); self.db.commit()
        self.db.execute("UPDATE governed_retention_authorities SET available=0 WHERE authority_id='synthetic-owner' AND revision=1 AND role='owner'"); self.db.commit()
        before = (retention.get_subject(self.db, 'SYN-1')['stored_tuple'], self.db.execute("SELECT count(*) FROM governed_retention_history").fetchone()[0])
        with self.assertRaisesRegex(ValueError, 'authority_unavailable'):
            retention.reassess_after_invalidation(self.db, subject_identifier='SYN-1', outcome='eligible', owner_authority='synthetic-owner', owner_revision=1, actor=self.owner, expected_version=60, idempotency_key='rs02-stale-owner', reason='stale')
        self.assertEqual((retention.get_subject(self.db, 'SYN-1')['stored_tuple'], self.db.execute("SELECT count(*) FROM governed_retention_history").fetchone()[0]), before)
        self.db.execute("UPDATE governed_retention_authorities SET available=1 WHERE authority_id='synthetic-owner' AND revision=1 AND role='owner'"); self.db.commit()
        recovered = retention.reassess_after_invalidation(self.db, subject_identifier='SYN-1', outcome='eligible', owner_authority='synthetic-owner', owner_revision=1, actor=self.owner, expected_version=60, idempotency_key='rs02', reason='reassess')
        item = retention.get_subject(self.db, 'SYN-1')
        self.assertEqual(item['tuple'], ('assessed','complete_with_limits','under_assessment','none','not_recorded','not_evaluated','under_review'))
        self.db.execute("UPDATE governed_retention_subjects SET eligibility_state='eligible_current',decision_state='proposed_eligible_for_future_scope',approval_state='approved_current',applicability_state='current',version=? WHERE identifier='SYN-1'", (recovered['resulting_version'],)); self.db.commit()
        before_unbound = (retention.get_subject(self.db, 'SYN-1')['stored_tuple'], self.db.execute("SELECT count(*) FROM governed_retention_history").fetchone()[0])
        with self.assertRaisesRegex(ValueError, 'recurring_review_binding_invalid'):
            retention.voluntary_reconsideration(self.db, subject_identifier='SYN-1', actor=self.owner, expected_version=recovered['resulting_version'], idempotency_key='rc01-unbound', reason='reconsider')
        self.assertEqual((retention.get_subject(self.db, 'SYN-1')['stored_tuple'], self.db.execute("SELECT count(*) FROM governed_retention_history").fetchone()[0]), before_unbound)
        self._seed_current_approved_chain(version=recovered['resulting_version'])
        reconsidered = retention.voluntary_reconsideration(self.db, subject_identifier='SYN-1', actor=self.owner, expected_version=recovered['resulting_version'], idempotency_key='rc01', reason='reconsider')
        self.assertEqual(retention.get_subject(self.db, 'SYN-1')['decision_state'], 'none')
        self.db.execute("UPDATE governed_retention_subjects SET procedure_state='closed',version=? WHERE identifier='SYN-1'", (reconsidered['resulting_version'],)); self.db.commit()
        with self.assertRaisesRegex(ValueError, 'reconsideration_state_invalid'):
            retention.voluntary_reconsideration(self.db, subject_identifier='SYN-1', actor=self.owner, expected_version=reconsidered['resulting_version'], idempotency_key='rc01-closed', reason='bad')

    def test_repeated_rejected_invalidation_preserves_rejection_without_approval(self):
        self.db.execute("UPDATE governed_retention_subjects SET retention_review='assessed',inventory_state='complete_with_limits',eligibility_state='eligible_current',decision_state='proposed_eligible_for_future_scope',approval_state='not_approved',applicability_state='not_evaluated',procedure_state='under_review',version=80 WHERE identifier='SYN-1'")
        self.db.execute("INSERT INTO governed_retention_history(subject_id,operation_id,actor,reason,details_json,occurred_at) VALUES(1,'D-07-E','owner-a','rejected','{}','2026-10-19T00:00:00Z')"); self.db.commit()
        first = retention.invalidate(self.db, subject_identifier='SYN-1', unavailable=False, basis='fixture-r2', actor=self.owner, expected_version=80, idempotency_key='r2-first', reason='changed')
        second = retention.invalidate(self.db, subject_identifier='SYN-1', unavailable=True, basis='fixture-r2b', actor=self.owner, expected_version=first['resulting_version'], idempotency_key='r2-second', reason='unavailable')
        item = retention.get_subject(self.db, 'SYN-1')
        self.assertEqual((item['approval_state'], item['applicability_state']), ('not_approved','unavailable'))
        self.assertEqual(second['operation'], 'IV-01-R2')

    def test_proposed_and_approved_repeated_invalidation_preserve_real_history(self):
        self.db.execute("UPDATE governed_retention_subjects SET retention_review='assessed',inventory_state='complete_with_limits',eligibility_state='eligible_current',decision_state='proposed_eligible_for_future_scope',approval_state='not_recorded',applicability_state='not_evaluated',procedure_state='under_review',version=81 WHERE identifier='SYN-1'"); self.db.commit()
        proposed = retention.invalidate(self.db, subject_identifier='SYN-1', unavailable=False, basis='proposal-change', actor=self.owner, expected_version=81, idempotency_key='p-first', reason='changed')
        self.assertEqual(proposed['operation'], 'IV-01-P')
        repeat = retention.invalidate(self.db, subject_identifier='SYN-1', unavailable=True, basis='proposal-unavailable', actor=self.owner, expected_version=proposed['resulting_version'], idempotency_key='p-repeat', reason='unavailable')
        item = retention.get_subject(self.db, 'SYN-1'); self.assertEqual((repeat['operation'],item['approval_state'],item['applicability_state']), ('IV-01-P2','not_recorded','unavailable'))
        self.db.execute("UPDATE governed_retention_subjects SET eligibility_state='eligible_current',approval_state='approved_current',applicability_state='current',version=? WHERE identifier='SYN-1'", (repeat['resulting_version'],)); self.db.commit()
        approved = retention.invalidate(self.db, subject_identifier='SYN-1', unavailable=False, basis='approval-change', actor=self.owner, expected_version=repeat['resulting_version'], idempotency_key='o-first', reason='changed')
        returned = retention.invalidate(self.db, subject_identifier='SYN-1', unavailable=False, basis='availability-returned', actor=self.owner, expected_version=approved['resulting_version'], idempotency_key='o-repeat', reason='returned')
        row = retention.get_subject(self.db, 'SYN-1')
        self.assertEqual((approved['operation'],returned['operation'],row['approval_state'],row['applicability_state']), ('IV-01-O','IV-01-O2','stale','reassessment_required'))

    def test_inventory_start_has_phase_guard_and_cannot_touch_proposed_chain(self):
        started = retention.start_initial_review(self.db, subject_identifier='SYN-1', actor=self.owner, expected_version=1, idempotency_key='inv-start-review', reason='start')
        inventory = retention.start_inventory_assessment(self.db, subject_identifier='SYN-1', actor=self.owner, expected_version=started['resulting_version'], idempotency_key='inv-start', reason='inventory')
        self.assertEqual(inventory['operation'], 'INV-01')
        self.db.execute("UPDATE governed_retention_subjects SET decision_state='proposed_eligible_for_future_scope',eligibility_state='eligible_current',version=? WHERE identifier='SYN-1'", (inventory['resulting_version'],)); self.db.commit()
        with self.assertRaisesRegex(ValueError, 'inventory_phase_invalid'):
            retention.start_inventory_assessment(self.db, subject_identifier='SYN-1', actor=self.owner, expected_version=inventory['resulting_version'], idempotency_key='inv-proposed', reason='bad')
        self.assertEqual(retention.get_subject(self.db, 'SYN-1')['version'], inventory['resulting_version'])

    def test_unavailable_inventory_observation_and_recovery_do_not_promote_completeness(self):
        started = retention.start_initial_review(self.db, subject_identifier='SYN-1', actor=self.owner, expected_version=1, idempotency_key='u-start', reason='start')
        unavailable = retention.record_inventory(self.db, subject_identifier='SYN-1', outcome='unavailable', copies={}, evidence=['offline'], limitations='source unavailable', actor=self.owner, expected_version=started['resulting_version'], idempotency_key='u-record', reason='unavailable')
        observed = retention.resume_inventory(self.db, subject_identifier='SYN-1', recovered=False, actor=self.owner, expected_version=unavailable['resulting_version'], idempotency_key='u-observe', reason='still unavailable')
        self.assertEqual(retention.get_subject(self.db, 'SYN-1')['tuple'][1:6], ('unavailable','unavailable','none','not_recorded','unavailable'))
        recovered = retention.resume_inventory(self.db, subject_identifier='SYN-1', recovered=True, actor=self.owner, expected_version=observed['resulting_version'], idempotency_key='u-recover', reason='available')
        item = retention.get_subject(self.db, 'SYN-1')
        self.assertEqual((item['inventory_state'],item['eligibility_state'],item['applicability_state']), ('under_assessment','under_assessment','not_evaluated'))
        self.assertEqual(recovered['operation'], 'INV-07')

    def test_closed_hold_amendment_invalidates_without_reopening(self):
        self.db.execute("UPDATE governed_retention_subjects SET retention_review='assessed',inventory_state='incomplete',eligibility_state='ineligible_current',decision_state='proposed_ineligible_for_future_scope',approval_state='approved_current',applicability_state='current',procedure_state='closed',version=90 WHERE identifier='SYN-1'")
        self.db.execute("INSERT INTO governed_retention_holds(subject_id,hold_identifier,revision,state,basis,evidence_json,scope,limitations,owner_fixture_id,owner_fixture_revision,actor,occurred_at) VALUES(1,'H-AMEND',1,'active','basis','[]','scope','limits','synthetic-owner',1,'owner-a','2026-10-19T00:00:00Z')"); self.db.commit()
        self._seed_active_closure_history(outcome='ineligible')
        with self.assertRaisesRegex(ValueError, 'amendment_review_required'):
            retention.record_hold(self.db, subject_identifier='SYN-1', operation='amend', hold_identifier='H-AMEND', owner_authority='synthetic-owner', owner_revision=1, evidence=['amended'], scope='new scope', limitations='limits', actor=self.owner, expected_version=90, idempotency_key='closed-amend-refused', reason='amend')
        self.assertEqual(retention.get_subject(self.db, 'SYN-1')['version'], 90)
        self.db.execute("INSERT INTO governed_retention_history(subject_id,operation_id,actor,reason,details_json,occurred_at) VALUES(1,'H-05','owner-a','review',?, '2026-10-19T00:00:00Z')", (json.dumps({'payload': {'hold':'H-AMEND','hold_revision':1,'subject_revision':1,'subject_binding_json':'{}','policy_id':'policy-syn','policy_revision':1}}),)); self.db.commit()
        amended = retention.record_hold(self.db, subject_identifier='SYN-1', operation='amend', hold_identifier='H-AMEND', owner_authority='synthetic-owner', owner_revision=1, evidence=['amended'], scope='new scope', limitations='limits', actor=self.owner, expected_version=90, idempotency_key='closed-amend', reason='amend')
        item = retention.get_subject(self.db, 'SYN-1')
        self.assertEqual((item['procedure_state'],item['eligibility_state'],item['approval_state'],item['applicability_state']), ('closed','stale','stale','reassessment_required'))
        self.assertEqual(amended['operation'], 'H-09')

    def test_closed_reviewed_hold_release_preserves_closure_and_invalidates(self):
        started = retention.start_initial_review(self.db, subject_identifier='SYN-1', actor=self.owner, expected_version=1, idempotency_key='rel-start', reason='start')
        placed = retention.record_hold(self.db, subject_identifier='SYN-1', operation='place', hold_identifier='H-REL-CLOSED', owner_authority='synthetic-owner', owner_revision=1, evidence=['basis'], scope='scope', limitations='limits', actor=self.owner, expected_version=started['resulting_version'], idempotency_key='rel-place', reason='place')
        proposed = retention.propose_hold_release(self.db, subject_identifier='SYN-1', hold_identifier='H-REL-CLOSED', evidence=['proposal'], actor=self.owner, expected_version=placed['resulting_version'], idempotency_key='rel-propose', reason='propose')
        reviewed = retention.review_hold_release(self.db, subject_identifier='SYN-1', hold_identifier='H-REL-CLOSED', reviewer_authority='synthetic-reviewer', reviewer_revision=1, evidence=['review'], scope='scope', limitations='limits', actor=self.reviewer, expected_version=proposed['resulting_version'], idempotency_key='rel-review', reason='review')
        self.db.execute("UPDATE governed_retention_subjects SET retention_review='assessed',inventory_state='incomplete',eligibility_state='ineligible_current',decision_state='proposed_ineligible_for_future_scope',approval_state='approved_current',applicability_state='current',procedure_state='closed',version=? WHERE identifier='SYN-1'", (reviewed['resulting_version'],)); self.db.commit()
        self._seed_active_closure_history(outcome='ineligible')
        released = retention.release_hold(self.db, subject_identifier='SYN-1', hold_identifier='H-REL-CLOSED', owner_authority='synthetic-owner', owner_revision=1, evidence=['release'], scope='scope', limitations='limits', actor=self.owner, expected_version=reviewed['resulting_version'], idempotency_key='rel-release', reason='release')
        item = retention.get_subject(self.db, 'SYN-1')
        self.assertEqual((item['procedure_state'],item['applicability_state'],item['approval_state']), ('closed','reassessment_required','stale'))
        self.assertEqual(released['operation'], 'H-10')

    def test_eligible_closure_requires_bound_review_approval_and_hold_search(self):
        started = retention.start_initial_review(self.db, subject_identifier='SYN-1', actor=self.owner, expected_version=1, idempotency_key='c-start', reason='start')
        copies = {name: {'applicable': True, 'identity': name, 'control': 'synthetic'} for name in retention.COPY_CLASSES}
        inventory = retention.record_inventory(self.db, subject_identifier='SYN-1', outcome='complete_with_limits', copies=copies, evidence=['inventory'], limitations='limits', actor=self.owner, expected_version=started['resulting_version'], idempotency_key='c-inventory', reason='inventory')
        reviewed = retention.complete_review(self.db, subject_identifier='SYN-1', evidence=['review'], limitations='limits', actor=self.owner, expected_version=inventory['resulting_version'], idempotency_key='c-review', reason='review')
        searched = retention.assess_hold_context(self.db, subject_identifier='SYN-1', hold_identifier=None, applicability=None, evidence=['search'], scope='synthetic', limitations='limited', actor=self.owner, expected_version=reviewed['resulting_version'], idempotency_key='c-search', reason='search')
        assessed = retention.assess_decision(self.db, subject_identifier='SYN-1', outcome='eligible', blocker=None, evidence=['conditions'], limitations='limits', next_review=None, actor=self.owner, expected_version=searched['resulting_version'], idempotency_key='c-assess', reason='eligible')
        proposed = retention.propose_decision(self.db, subject_identifier='SYN-1', outcome='eligible', actor=self.owner, expected_version=assessed['resulting_version'], idempotency_key='c-propose', reason='propose')
        self.db.execute("INSERT INTO governed_retention_authorities(authority_id,revision,username,role,available) VALUES(?,?,?,?,1)", ('assessor-reviewer', 1, 'owner-a', 'reviewer')); self.db.commit()
        with self.assertRaisesRegex(ValueError, 'policy_authority_binding_invalid'):
            retention.independent_review(self.db, subject_identifier='SYN-1', reviewer_authority='assessor-reviewer', reviewer_revision=1, actor=self.owner, expected_version=proposed['resulting_version'], idempotency_key='c-self-review', reason='bad', evidence=['review'])
        self.assertEqual(retention.get_subject(self.db, 'SYN-1')['version'], proposed['resulting_version'])
        reviewed_proposal = retention.independent_review(self.db, subject_identifier='SYN-1', reviewer_authority='synthetic-reviewer', reviewer_revision=1, actor=self.reviewer, expected_version=proposed['resulting_version'], idempotency_key='c-independent', reason='review', evidence=['review'])
        approved = retention.owner_decision(self.db, subject_identifier='SYN-1', approve=True, owner_authority='synthetic-owner', owner_revision=1, actor=self.owner, expected_version=reviewed_proposal['resulting_version'], idempotency_key='c-approve', reason='approve')
        self.db.execute("UPDATE governed_retention_authorities SET available=0 WHERE authority_id='synthetic-owner' AND revision=1 AND role='owner'"); self.db.commit()
        before = retention.get_subject(self.db, 'SYN-1')
        with self.assertRaisesRegex(ValueError, 'authority_unavailable'):
            retention.close(self.db, subject_identifier='SYN-1', actor=self.owner, expected_version=approved['resulting_version'], idempotency_key='c-close-stale-owner', reason='close')
        after = retention.get_subject(self.db, 'SYN-1')
        self.assertEqual((after['stored_tuple'], after['version'], after['history']), (before['stored_tuple'], before['version'], before['history']))
        self.db.execute("UPDATE governed_retention_authorities SET available=1 WHERE authority_id='synthetic-owner' AND revision=1 AND role='owner'"); self.db.commit()
        closed = retention.close(self.db, subject_identifier='SYN-1', actor=self.owner, expected_version=approved['resulting_version'], idempotency_key='c-close', reason='close')
        self.assertEqual(retention.get_subject(self.db, 'SYN-1')['procedure_state'], 'closed')
        self.assertEqual(closed['operation'], 'CL-01')

    def test_reopen_and_atomic_reopen_plus_place_preserve_inventory_state(self):
        self.db.execute("UPDATE governed_retention_subjects SET retention_review='assessed',inventory_state='incomplete',eligibility_state='ineligible_current',decision_state='proposed_ineligible_for_future_scope',approval_state='approved_current',applicability_state='current',procedure_state='closed',version=70 WHERE identifier='SYN-1'"); self.db.commit()
        self.db.execute("INSERT INTO governed_retention_inventory_assessments(subject_id,subject_revision,subject_binding_json,policy_id,policy_revision,outcome,copies_json,evidence_json,limitations,actor,occurred_at) VALUES(1,1,'{}','policy-syn',1,'incomplete','{}','[\"gap\"]','limits','owner-a','2026-10-19T00:00:00Z')"); self.db.commit()
        before = (retention.get_subject(self.db, 'SYN-1')['stored_tuple'], self.db.execute("SELECT count(*) FROM governed_retention_history").fetchone()[0])
        with self.assertRaisesRegex(ValueError, 'active_closure_history_required'):
            retention.reopen(self.db, subject_identifier='SYN-1', scope='synthetic subject', actor=self.owner, expected_version=70, idempotency_key='reopen-unbound', reason='scope')
        self.assertEqual((retention.get_subject(self.db, 'SYN-1')['stored_tuple'], self.db.execute("SELECT count(*) FROM governed_retention_history").fetchone()[0]), before)
        self._seed_active_closure_history()
        reopened = retention.reopen(self.db, subject_identifier='SYN-1', scope='synthetic subject', actor=self.owner, expected_version=70, idempotency_key='reopen', reason='scope')
        resumed = retention.resume_after_reopen(self.db, subject_identifier='SYN-1', actor=self.owner, expected_version=reopened['resulting_version'], idempotency_key='resume-reopen', reason='resume')
        self.assertEqual(retention.get_subject(self.db, 'SYN-1')['tuple'], ('assessed','incomplete','under_assessment','none','not_recorded','not_evaluated','under_review'))
        self.db.execute("UPDATE governed_retention_subjects SET procedure_state='closed',eligibility_state='ineligible_current',decision_state='proposed_ineligible_for_future_scope',approval_state='approved_current',applicability_state='current',version=? WHERE identifier='SYN-1'", (resumed['resulting_version'],)); self.db.commit()
        self._seed_active_closure_history()
        placed = retention.record_hold(self.db, subject_identifier='SYN-1', operation='place', hold_identifier='H-CLOSED', owner_authority='synthetic-owner', owner_revision=1, evidence=['basis'], scope='scope', limitations='limits', actor=self.owner, expected_version=resumed['resulting_version'], idempotency_key='reopen-place', reason='place')
        item = retention.get_subject(self.db, 'SYN-1')
        self.assertEqual(item['tuple'], ('assessed','incomplete','under_assessment','none','not_recorded','not_evaluated','reopened'))
        self.assertEqual(placed['operation'], 'H-11')
        event = json.loads(item['history'][-1]['details_json'])['payload']
        self.assertEqual((event['hold'], event['reopen_scope']), ('H-CLOSED', 'scope'))

    def test_h11_refuses_policy_mismatched_owner_without_reopen_or_hold_write(self):
        self.db.execute("UPDATE governed_retention_subjects SET retention_review='assessed',inventory_state='incomplete',eligibility_state='ineligible_current',decision_state='proposed_ineligible_for_future_scope',approval_state='approved_current',applicability_state='current',procedure_state='closed',version=73 WHERE identifier='SYN-1'")
        self.db.commit(); self._seed_active_closure_history(outcome='ineligible')
        policy = self._policy_document(); policy['owner_authority_id'] = 'wrong-owner'
        self.db.execute("UPDATE governed_retention_policies SET policy_json=? WHERE policy_id='policy-syn' AND revision=1", (json.dumps(policy),)); self.db.commit()
        before = (retention.get_subject(self.db, 'SYN-1')['tuple'], retention.get_subject(self.db, 'SYN-1')['version'], self.db.execute("SELECT count(*) FROM governed_retention_holds").fetchone()[0], self.db.execute("SELECT count(*) FROM governed_retention_history").fetchone()[0])
        with self.assertRaisesRegex(ValueError, 'policy_authority_binding_invalid'):
            retention.record_hold(self.db, subject_identifier='SYN-1', operation='place', hold_identifier='H-H11-AUTH', owner_authority='synthetic-owner', owner_revision=1, evidence=['basis'], scope='scope', limitations='limits', actor=self.owner, expected_version=73, idempotency_key='h11-owner-bad', reason='place')
        after = (retention.get_subject(self.db, 'SYN-1')['tuple'], retention.get_subject(self.db, 'SYN-1')['version'], self.db.execute("SELECT count(*) FROM governed_retention_holds").fetchone()[0], self.db.execute("SELECT count(*) FROM governed_retention_history").fetchone()[0])
        self.assertEqual(after, before)

    def test_reopen_preserves_unavailable_inventory_until_explicit_recovery(self):
        self.db.execute("UPDATE governed_retention_subjects SET retention_review='assessed',inventory_state='unavailable',eligibility_state='unavailable',decision_state='proposed_ineligible_for_future_scope',approval_state='approved_current',applicability_state='current',procedure_state='closed',version=71 WHERE identifier='SYN-1'"); self.db.commit()
        self.db.execute("INSERT INTO governed_retention_inventory_assessments(subject_id,subject_revision,subject_binding_json,policy_id,policy_revision,outcome,copies_json,evidence_json,limitations,actor,occurred_at) VALUES(1,1,'{}','policy-syn',1,'unavailable','{}','[\"offline\"]','limits','owner-a','2026-10-19T00:00:00Z')"); self.db.commit()
        self._seed_active_closure_history()
        reopened = retention.reopen(self.db, subject_identifier='SYN-1', scope='synthetic', actor=self.owner, expected_version=71, idempotency_key='unavailable-reopen', reason='scope')
        resumed = retention.resume_after_reopen(self.db, subject_identifier='SYN-1', actor=self.owner, expected_version=reopened['resulting_version'], idempotency_key='unavailable-resume', reason='resume')
        item = retention.get_subject(self.db, 'SYN-1')
        self.assertEqual(item['tuple'], ('assessed','unavailable','unavailable','none','not_recorded','unavailable','under_review'))
        self.assertEqual(resumed['operation'], 'RM-01')

    def test_reopen_resume_refuses_missing_inventory_and_demotes_superseded_snapshot(self):
        self.db.execute("UPDATE governed_retention_subjects SET retention_review='assessed',inventory_state='complete_with_limits',eligibility_state='eligible_current',decision_state='proposed_eligible_for_future_scope',approval_state='approved_current',applicability_state='current',procedure_state='closed',version=72 WHERE identifier='SYN-1'"); self.db.commit()
        self._seed_active_closure_history(outcome='eligible')
        reopened = retention.reopen(self.db, subject_identifier='SYN-1', scope='synthetic', actor=self.owner, expected_version=72, idempotency_key='rm-missing-reopen', reason='scope')
        before = (retention.get_subject(self.db, 'SYN-1')['stored_tuple'], self.db.execute("SELECT count(*) FROM governed_retention_history").fetchone()[0])
        with self.assertRaisesRegex(ValueError, 'inventory_binding_missing'):
            retention.resume_after_reopen(self.db, subject_identifier='SYN-1', actor=self.owner, expected_version=reopened['resulting_version'], idempotency_key='rm-missing', reason='resume')
        self.assertEqual((retention.get_subject(self.db, 'SYN-1')['stored_tuple'], self.db.execute("SELECT count(*) FROM governed_retention_history").fetchone()[0]), before)
        self.db.execute("INSERT INTO governed_retention_inventory_assessments(subject_id,subject_revision,subject_binding_json,policy_id,policy_revision,outcome,copies_json,evidence_json,limitations,actor,occurred_at) VALUES(1,1,'{}','policy-syn',1,'complete_with_limits','{}','[\"inventory\"]','limits','owner-a','2026-10-19T00:00:00Z')")
        self.db.execute("UPDATE governed_retention_subjects SET subject_revision=2,subject_binding_json=? WHERE identifier='SYN-1'", (json.dumps({'synthetic_revision': 2}),)); self.db.commit()
        resumed = retention.resume_after_reopen(self.db, subject_identifier='SYN-1', actor=self.owner, expected_version=reopened['resulting_version'], idempotency_key='rm-superseded', reason='resume')
        item = dict(self.db.execute("SELECT * FROM governed_retention_subjects WHERE identifier='SYN-1'").fetchone())
        self.assertEqual((resumed['operation'], item['inventory_state'], item['eligibility_state'], item['applicability_state'], item['procedure_state']), ('RM-01','under_assessment','under_assessment','not_evaluated','under_review'))

    def test_closure_refusal_leaves_subject_and_history_unchanged(self):
        self.db.execute("UPDATE governed_retention_subjects SET retention_review='assessed',inventory_state='complete_with_limits',eligibility_state='eligible_current',decision_state='proposed_eligible_for_future_scope',approval_state='approved_current',applicability_state='current',procedure_state='under_review',version=110 WHERE identifier='SYN-1'")
        self.db.execute("INSERT INTO governed_retention_decisions(subject_id,assessment_id,revision,outcome,bindings_json,actor,occurred_at) VALUES(1,1,1,'eligible','{}','owner-a','2026-10-20T00:00:00Z')")
        self.db.commit()
        before = retention.get_subject(self.db, 'SYN-1')
        with self.assertRaisesRegex(ValueError, 'closure_review_approval_binding_invalid'):
            retention.close(self.db, subject_identifier='SYN-1', actor=self.owner, expected_version=110, idempotency_key='closure-refusal', reason='close')
        after = retention.get_subject(self.db, 'SYN-1')
        self.assertEqual(after['tuple'], before['tuple'])
        self.assertEqual(after['version'], before['version'])
        self.assertEqual(after['history'], before['history'])

    def test_ineligible_closure_refuses_missing_next_review_without_mutation(self):
        self._seed_current_approved_chain(outcome='ineligible', review='assessed', procedure='under_review', version=140)
        before = retention.get_subject(self.db, 'SYN-1')
        with self.assertRaisesRegex(ValueError, 'next_review_required'):
            retention.close(self.db, subject_identifier='SYN-1', actor=self.owner, expected_version=140, idempotency_key='cl02-missing-next', reason='close')
        after = retention.get_subject(self.db, 'SYN-1')
        self.assertEqual((after['tuple'], after['version'], after['history']), (before['tuple'], before['version'], before['history']))

    def test_ineligible_closure_refuses_stale_next_review_binding_without_mutation(self):
        self._seed_current_approved_chain(outcome='ineligible', review='assessed', procedure='under_review', version=141)
        inv = self.db.execute("SELECT id FROM governed_retention_inventory_assessments WHERE subject_id=1 ORDER BY id DESC LIMIT 1").fetchone()[0]
        bindings = json.dumps({'subject_revision':1, 'subject_binding_json':'{}', 'policy_id':'policy-syn', 'policy_revision':1, 'inventory_assessment_id':inv}, sort_keys=True, separators=(',', ':'))
        stale = json.dumps({'point':'next','responsible':'owner-a','reason':'hold','scope':'scope','subject_revision':1,'subject_binding_json':'{}','policy_id':'policy-syn','policy_revision':2})
        self.db.execute("INSERT INTO governed_retention_assessments(subject_id,subject_revision,subject_binding_json,policy_id,policy_revision,outcome,blocker,evidence_json,limitations,next_review_json,actor,occurred_at) VALUES(1,1,'{}','policy-syn',1,'ineligible','applicable_active_hold','[\"hold\"]','gap',?,'owner-a','2026-10-19T00:00:00Z')", (stale,))
        assessment = self.db.execute("SELECT last_insert_rowid()").fetchone()[0]
        self.db.execute("INSERT INTO governed_retention_decisions(subject_id,assessment_id,revision,outcome,bindings_json,actor,occurred_at) VALUES(1,?,2,'ineligible',?,'owner-a','2026-10-19T00:00:00Z')", (assessment, bindings))
        decision = self.db.execute("SELECT last_insert_rowid()").fetchone()[0]
        self.db.execute("INSERT INTO governed_retention_reviews(subject_id,decision_id,action,revision,reviewer_fixture_id,reviewer_fixture_revision,reviewer,result,evidence_json,occurred_at) VALUES(1,?,'decision',2,'synthetic-reviewer',1,'reviewer-b','accepted','[\"review\"]','2026-10-19T00:00:00Z')", (decision,))
        self.db.execute("INSERT INTO governed_retention_approvals(subject_id,decision_id,revision,owner_fixture_id,owner_fixture_revision,actor,occurred_at) VALUES(1,?,2,'synthetic-owner',1,'owner-a','2026-10-19T00:00:00Z')", (decision,)); self.db.commit()
        before = retention.get_subject(self.db, 'SYN-1')
        with self.assertRaisesRegex(ValueError, 'next_review_required'):
            retention.close(self.db, subject_identifier='SYN-1', actor=self.owner, expected_version=141, idempotency_key='cl02-stale-next', reason='close')
        after = retention.get_subject(self.db, 'SYN-1')
        self.assertEqual((after['tuple'], after['version'], after['history']), (before['tuple'], before['version'], before['history']))

    def test_due_derivation_rejects_future_and_mismatched_fixture_without_writes(self):
        self.db.execute("UPDATE governed_retention_subjects SET retention_review='assessed',inventory_state='complete_with_limits',eligibility_state='eligible_current',decision_state='proposed_eligible_for_future_scope',approval_state='approved_current',applicability_state='current',procedure_state='under_review',version=111 WHERE identifier='SYN-1'")
        self.db.execute("UPDATE governed_retention_policies SET policy_json=? WHERE policy_id='policy-syn' AND revision=1", (json.dumps(self._policy_document(True, due_at='2099-01-01T00:00:00Z', identity='future')),)); self.db.commit()
        before = retention.get_subject(self.db, 'SYN-1')
        with self.assertRaisesRegex(ValueError, 'review_point_not_reached'):
            retention.apply_review_due(self.db, subject_identifier='SYN-1', reached_point='future', actor=self.owner, expected_version=111, idempotency_key='future-refusal', reason='due')
        self.assertEqual(retention.get_subject(self.db, 'SYN-1')['version'], before['version'])
        self.db.execute("UPDATE governed_retention_policies SET policy_json=? WHERE policy_id='policy-syn' AND revision=1", (json.dumps(self._policy_document(True, identity='wrong', subject_revision=2)),)); self.db.commit()
        with self.assertRaisesRegex(ValueError, 'trigger_evidence_mismatch'):
            retention.apply_review_due(self.db, subject_identifier='SYN-1', reached_point='wrong', actor=self.owner, expected_version=111, idempotency_key='mismatch-refusal', reason='due')
        self.assertEqual(
            [dict(x) for x in self.db.execute("SELECT * FROM governed_retention_history WHERE subject_id=1 ORDER BY id")],
            before['history'],
        )

    def test_private_retrieval_derives_true_due_before_observation_without_writes(self):
        self.db.execute("UPDATE governed_retention_policies SET policy_json=? WHERE policy_id='policy-syn' AND revision=1", (json.dumps(self._policy_document(True, due_at='2026-01-01T00:00:00Z', identity='derived-true')),))
        self.db.execute("UPDATE governed_retention_subjects SET retention_review='assessed',inventory_state='complete_with_limits',eligibility_state='eligible_current',decision_state='proposed_eligible_for_future_scope',approval_state='approved_current',applicability_state='current',procedure_state='closed',version=120 WHERE identifier='SYN-1'")
        self.db.commit()
        before = retention.get_subject(self.db, 'SYN-1')
        self.assertEqual(before['stored_tuple'], ('assessed','complete_with_limits','eligible_current','proposed_eligible_for_future_scope','approved_current','current','closed'))
        self.assertEqual(before['tuple'], ('due','complete_with_limits','stale','proposed_eligible_for_future_scope','stale','reassessment_required','closed'))
        self.assertTrue(before['derived_review_due'])
        self.assertEqual(before['derived_review_point'], {'identity':'derived-true','revision':1,'due_at':'2026-01-01T00:00:00Z','subject_revision':1})
        self.assertEqual(retention.render_private_status(before), 'Closed — reassessment required')
        self.assertEqual(before['history'], [])
        again = retention.get_subject(self.db, 'SYN-1')
        self.assertEqual(again['version'], 120)
        self.assertEqual(again['history'], [])
        with self.assertRaisesRegex(ValueError, 'review_due_currentness_required'):
            retention.close(self.db, subject_identifier='SYN-1', actor=self.owner, expected_version=120, idempotency_key='derived-close-refusal', reason='close')
        after = retention.get_subject(self.db, 'SYN-1')
        self.assertEqual(after['stored_tuple'], before['stored_tuple'])
        self.assertEqual(after['version'], 120)
        self.assertEqual(after['history'], [])

    def test_false_derived_due_is_prominent_without_currentness_mutation_or_bypass(self):
        self.db.execute("UPDATE governed_retention_policies SET policy_json=? WHERE policy_id='policy-syn' AND revision=1", (json.dumps(self._policy_document(False, due_at='2026-01-01T00:00:00Z', identity='derived-false')),))
        self.db.execute("UPDATE governed_retention_subjects SET retention_review='assessed',inventory_state='complete_with_limits',eligibility_state='eligible_current',decision_state='proposed_eligible_for_future_scope',approval_state='approved_current',applicability_state='current',procedure_state='under_review',version=121 WHERE identifier='SYN-1'")
        self.db.commit()
        item = retention.get_subject(self.db, 'SYN-1')
        self.assertEqual(item['tuple'], ('due','complete_with_limits','eligible_current','proposed_eligible_for_future_scope','approved_current','current','under_review'))
        self.assertTrue(item['derived_review_due'])
        before = retention.get_subject(self.db, 'SYN-1')
        with self.assertRaisesRegex(ValueError, 'review_point_invalid'):
            retention.apply_review_due(self.db, subject_identifier='SYN-1', reached_point='caller-selected-bypass', actor=self.owner, expected_version=121, idempotency_key='wrong-derived-point', reason='due')
        after = retention.get_subject(self.db, 'SYN-1')
        self.assertEqual(after['stored_tuple'], before['stored_tuple'])
        self.assertEqual(after['history'], before['history'])
        self.assertEqual(after['version'], 121)

    def test_invalid_or_mismatched_current_fixture_fails_closed_without_due_write(self):
        self.db.execute("UPDATE governed_retention_subjects SET retention_review='assessed',inventory_state='complete_with_limits',eligibility_state='eligible_current',decision_state='proposed_eligible_for_future_scope',approval_state='approved_current',applicability_state='current',procedure_state='under_review',version=122 WHERE identifier='SYN-1'")
        malformed = self._policy_document(True, due_at='2026-01-01T00:00:00Z', identity='bad')
        malformed['trigger_evidence'] = {'subject_identity':'other','subject_revision':1}
        self.db.execute("UPDATE governed_retention_policies SET policy_json=? WHERE policy_id='policy-syn' AND revision=1", (json.dumps(malformed),)); self.db.commit()
        before_row = dict(self.db.execute("SELECT * FROM governed_retention_subjects WHERE identifier='SYN-1'").fetchone())
        before_history = self.db.execute("SELECT count(*) FROM governed_retention_history").fetchone()[0]
        with self.assertRaisesRegex(ValueError, 'trigger_evidence_mismatch'):
            retention.get_subject(self.db, 'SYN-1')
        with self.assertRaisesRegex(ValueError, 'trigger_evidence_mismatch'):
            retention.apply_review_due(self.db, subject_identifier='SYN-1', reached_point='bad', actor=self.owner, expected_version=122, idempotency_key='bad-policy', reason='due')
        after_row = dict(self.db.execute("SELECT * FROM governed_retention_subjects WHERE identifier='SYN-1'").fetchone())
        self.assertEqual(after_row, before_row)
        self.assertEqual(self.db.execute("SELECT count(*) FROM governed_retention_history").fetchone()[0], before_history)

    def test_missing_review_due_boolean_is_rd12_unavailable_projection_without_writes(self):
        self.db.execute("UPDATE governed_retention_subjects SET retention_review='assessed',inventory_state='complete_with_limits',eligibility_state='eligible_current',decision_state='proposed_eligible_for_future_scope',approval_state='approved_current',applicability_state='current',procedure_state='closed',version=126 WHERE identifier='SYN-1'")
        invalid = self._policy_document(True)
        invalid.pop('review_due_invalidates_current_reliance')
        self.db.execute("UPDATE governed_retention_policies SET policy_json=? WHERE policy_id='policy-syn' AND revision=1", (json.dumps(invalid),)); self.db.commit()
        item = retention.get_subject(self.db, 'SYN-1')
        self.assertEqual(item['stored_tuple'], ('assessed','complete_with_limits','eligible_current','proposed_eligible_for_future_scope','approved_current','current','closed'))
        self.assertEqual(item['tuple'], ('assessed','complete_with_limits','unavailable','proposed_eligible_for_future_scope','unavailable','unavailable','closed'))
        self.assertEqual(retention.render_private_status(item), 'Closed — reassessment required')
        before = dict(self.db.execute("SELECT * FROM governed_retention_subjects WHERE identifier='SYN-1'").fetchone())
        with self.assertRaisesRegex(ValueError, 'review_due_invalid'):
            retention.close(self.db, subject_identifier='SYN-1', actor=self.owner, expected_version=126, idempotency_key='rd12-close', reason='close')
        self.assertEqual(dict(self.db.execute("SELECT * FROM governed_retention_subjects WHERE identifier='SYN-1'").fetchone()), before)
        with self.assertRaisesRegex(ValueError, 'review_due_invalid'):
            retention.apply_review_due(self.db, subject_identifier='SYN-1', reached_point='review-v1', actor=self.owner, expected_version=126, idempotency_key='rd12-observe', reason='due')
        self.assertEqual(dict(self.db.execute("SELECT * FROM governed_retention_subjects WHERE identifier='SYN-1'").fetchone()), before)

    def test_rd11_deferred_proposal_is_refused_without_history_or_projection_write(self):
        self.db.execute("UPDATE governed_retention_policies SET policy_json=? WHERE policy_id='policy-syn' AND revision=1", (json.dumps(self._policy_document(False, due_at='2026-01-01T00:00:00Z', identity='deferred-proposal')),))
        self.db.execute("UPDATE governed_retention_subjects SET retention_review='deferred',inventory_state='complete_with_limits',eligibility_state='eligible_current',decision_state='proposed_eligible_for_future_scope',approval_state='not_recorded',applicability_state='not_evaluated',procedure_state='under_review',version=127 WHERE identifier='SYN-1'"); self.db.commit()
        before = retention.get_subject(self.db, 'SYN-1')
        with self.assertRaisesRegex(ValueError, 'deferred_review_binding_invalid'):
            retention.apply_review_due(self.db, subject_identifier='SYN-1', reached_point='deferred-proposal', actor=self.owner, expected_version=127, idempotency_key='rd11', reason='due')
        after = retention.get_subject(self.db, 'SYN-1')
        self.assertEqual((after['stored_tuple'], after['version'], after['history']), (before['stored_tuple'], before['version'], before['history']))

    def test_false_policy_closed_ineligible_observational_cycle_preserves_current_chain(self):
        self.db.execute("UPDATE governed_retention_policies SET policy_json=? WHERE policy_id='policy-syn' AND revision=1", (json.dumps(self._policy_document(False, due_at='2026-01-01T00:00:00Z', identity='closed-i-cycle')),))
        self.db.commit()
        started_initial = retention.start_initial_review(self.db, subject_identifier='SYN-1', actor=self.owner, expected_version=1, idempotency_key='ci-initial', reason='start')
        incomplete = retention.record_inventory(self.db, subject_identifier='SYN-1', outcome='incomplete', copies={'backups': {'status': 'unknown'}}, evidence=['gap'], limitations='gap', actor=self.owner, expected_version=started_initial['resulting_version'], idempotency_key='ci-inventory', reason='inventory')
        assessed_review = retention.complete_review(self.db, subject_identifier='SYN-1', evidence=['review'], limitations='limits', actor=self.owner, expected_version=incomplete['resulting_version'], idempotency_key='ci-initial-complete', reason='complete')
        assessed = retention.assess_decision(self.db, subject_identifier='SYN-1', outcome='ineligible', blocker='relevant_unresolved_obligation', evidence=['attributable obligation'], limitations='gap', next_review={'point':'next', 'responsible':'owner-a', 'reason':'obligation', 'scope':'synthetic'}, actor=self.owner, expected_version=assessed_review['resulting_version'], idempotency_key='ci-assess', reason='assess')
        proposed = retention.propose_decision(self.db, subject_identifier='SYN-1', outcome='ineligible', actor=self.owner, expected_version=assessed['resulting_version'], idempotency_key='ci-propose', reason='propose')
        reviewed = retention.independent_review(self.db, subject_identifier='SYN-1', reviewer_authority='synthetic-reviewer', reviewer_revision=1, actor=self.reviewer, expected_version=proposed['resulting_version'], idempotency_key='ci-review', reason='review', evidence=['review'])
        approved = retention.owner_decision(self.db, subject_identifier='SYN-1', approve=True, owner_authority='synthetic-owner', owner_revision=1, actor=self.owner, expected_version=reviewed['resulting_version'], idempotency_key='ci-approve', reason='approve')
        closed = retention.close(self.db, subject_identifier='SYN-1', actor=self.owner, expected_version=approved['resulting_version'], idempotency_key='ci-close', reason='close')
        due = retention.apply_review_due(self.db, subject_identifier='SYN-1', reached_point='closed-i-cycle', actor=self.owner, expected_version=closed['resulting_version'], idempotency_key='ci-due', reason='due')
        started = retention.recurring_review(self.db, subject_identifier='SYN-1', action='start', actor=self.owner, expected_version=due['resulting_version'], idempotency_key='ci-start', reason='start')
        waiting = retention.recurring_review(self.db, subject_identifier='SYN-1', action='await_information', actor=self.owner, expected_version=started['resulting_version'], idempotency_key='ci-wait', reason='wait', details={'missing_information':'scope'})
        resumed = retention.recurring_review(self.db, subject_identifier='SYN-1', action='resume_information', actor=self.owner, expected_version=waiting['resulting_version'], idempotency_key='ci-resume-info', reason='resume', details={'evidence':'bound-source'})
        deferred = retention.recurring_review(self.db, subject_identifier='SYN-1', action='defer', actor=self.owner, expected_version=resumed['resulting_version'], idempotency_key='ci-defer', reason='defer', details={'next_point':'policy-point-2','responsible':'owner-a'})
        resumed_deferred = retention.recurring_review(self.db, subject_identifier='SYN-1', action='resume_deferred', actor=self.owner, expected_version=deferred['resulting_version'], idempotency_key='ci-resume-deferred', reason='resume', details={'resumption_basis':'recorded trigger'})
        finished = retention.recurring_review(self.db, subject_identifier='SYN-1', action='complete', actor=self.owner, expected_version=resumed_deferred['resulting_version'], idempotency_key='ci-complete', reason='complete', details={'next_point':'policy-point-3','responsible':'owner-a'})
        item = retention.get_subject(self.db, 'SYN-1')
        self.assertEqual((finished['operation'], item['tuple']), ('RR-CI-04', ('assessed','incomplete','ineligible_current','proposed_ineligible_for_future_scope','approved_current','current','closed')))

    def test_false_policy_open_ineligible_recurring_cycle_and_refusal(self):
        self.db.execute("UPDATE governed_retention_policies SET policy_json=? WHERE policy_id='policy-syn' AND revision=1", (json.dumps(self._policy_document(False, due_at='2026-01-01T00:00:00Z', identity='open-i-cycle')),))
        self.db.commit()
        self._seed_current_approved_chain(outcome='ineligible', review='assessed', procedure='under_review', version=151)
        due = retention.apply_review_due(self.db, subject_identifier='SYN-1', reached_point='open-i-cycle', actor=self.owner, expected_version=151, idempotency_key='oi-due', reason='due')
        started = retention.recurring_review(self.db, subject_identifier='SYN-1', action='start', actor=self.owner, expected_version=due['resulting_version'], idempotency_key='oi-start', reason='start')
        before = retention.get_subject(self.db, 'SYN-1')
        with self.assertRaisesRegex(ValueError, 'missing_information_required'):
            retention.recurring_review(self.db, subject_identifier='SYN-1', action='await_information', actor=self.owner, expected_version=started['resulting_version'], idempotency_key='oi-await-bad', reason='await')
        refused = retention.get_subject(self.db, 'SYN-1')
        self.assertEqual((refused['tuple'], refused['version'], refused['history']), (before['tuple'], before['version'], before['history']))
        waiting = retention.recurring_review(self.db, subject_identifier='SYN-1', action='await_information', actor=self.owner, expected_version=started['resulting_version'], idempotency_key='oi-await', reason='await', details={'missing_information':'scope','responsible':'owner-a'})
        resumed = retention.recurring_review(self.db, subject_identifier='SYN-1', action='resume_information', actor=self.owner, expected_version=waiting['resulting_version'], idempotency_key='oi-resume', reason='resume', details={'evidence':['bound']})
        deferred = retention.recurring_review(self.db, subject_identifier='SYN-1', action='defer', actor=self.owner, expected_version=resumed['resulting_version'], idempotency_key='oi-defer', reason='defer', details={'next_point':'open-i-next','responsible':'owner-a'})
        due_again = retention.recurring_review(self.db, subject_identifier='SYN-1', action='resume_deferred', actor=self.owner, expected_version=deferred['resulting_version'], idempotency_key='oi-resume-deferred', reason='resume', details={'resumption_basis':'recorded'})
        completed = retention.recurring_review(self.db, subject_identifier='SYN-1', action='complete', actor=self.owner, expected_version=due_again['resulting_version'], idempotency_key='oi-complete', reason='complete', details={'next_point':'open-i-final','responsible':'owner-a'})
        item = retention.get_subject(self.db, 'SYN-1')
        self.assertEqual((completed['operation'], item['tuple']), ('RR-I-04', ('assessed','incomplete','ineligible_current','proposed_ineligible_for_future_scope','approved_current','current','under_review')))

    def test_false_policy_open_eligible_recurring_cycle_and_refusal(self):
        self.db.execute("UPDATE governed_retention_policies SET policy_json=? WHERE policy_id='policy-syn' AND revision=1", (json.dumps(self._policy_document(False, due_at='2026-01-01T00:00:00Z', identity='open-e-cycle')),))
        self.db.commit(); self._seed_current_approved_chain(outcome='eligible', review='assessed', procedure='under_review', version=153)
        due = retention.apply_review_due(self.db, subject_identifier='SYN-1', reached_point='open-e-cycle', actor=self.owner, expected_version=153, idempotency_key='oe-due', reason='due')
        started = retention.recurring_review(self.db, subject_identifier='SYN-1', action='start', actor=self.owner, expected_version=due['resulting_version'], idempotency_key='oe-start', reason='start')
        before = retention.get_subject(self.db, 'SYN-1')
        with self.assertRaisesRegex(ValueError, 'recurring_review_resume_invalid'):
            retention.recurring_review(self.db, subject_identifier='SYN-1', action='resume_information', actor=self.owner, expected_version=started['resulting_version'], idempotency_key='oe-wrong-phase', reason='bad', details={'evidence':['x']})
        refused = retention.get_subject(self.db, 'SYN-1')
        self.assertEqual((refused['tuple'], refused['version'], refused['history']), (before['tuple'], before['version'], before['history']))
        waiting = retention.recurring_review(self.db, subject_identifier='SYN-1', action='await_information', actor=self.owner, expected_version=started['resulting_version'], idempotency_key='oe-await', reason='await', details={'missing_information':'scope','responsible':'owner-a'})
        resumed = retention.recurring_review(self.db, subject_identifier='SYN-1', action='resume_information', actor=self.owner, expected_version=waiting['resulting_version'], idempotency_key='oe-resume', reason='resume', details={'evidence':['bound']})
        deferred = retention.recurring_review(self.db, subject_identifier='SYN-1', action='defer', actor=self.owner, expected_version=resumed['resulting_version'], idempotency_key='oe-defer', reason='defer', details={'next_point':'open-e-next','responsible':'owner-a'})
        due_again = retention.recurring_review(self.db, subject_identifier='SYN-1', action='resume_deferred', actor=self.owner, expected_version=deferred['resulting_version'], idempotency_key='oe-resume-deferred', reason='resume', details={'resumption_basis':'recorded'})
        completed = retention.recurring_review(self.db, subject_identifier='SYN-1', action='complete', actor=self.owner, expected_version=due_again['resulting_version'], idempotency_key='oe-complete', reason='complete', details={'next_point':'open-e-final','responsible':'owner-a'})
        item = retention.get_subject(self.db, 'SYN-1')
        self.assertEqual((completed['operation'], item['tuple']), ('RR-E-04', ('assessed','complete_with_limits','eligible_current','proposed_eligible_for_future_scope','approved_current','current','under_review')))

    def test_mismatched_false_policy_completion_does_not_suppress_due_projection(self):
        self.db.execute("UPDATE governed_retention_policies SET policy_json=? WHERE policy_id='policy-syn' AND revision=1", (json.dumps(self._policy_document(False, due_at='2026-01-01T00:00:00Z', identity='completion-binding')),))
        self.db.commit(); self._seed_current_approved_chain(outcome='ineligible', review='assessed', procedure='under_review', version=152)
        details = json.dumps({'next_point':'future','responsible':'owner-a','subject_revision':1,'subject_binding_json':'{}','policy_id':'policy-syn','policy_revision':1,'completed_point_identity':'wrong-point','completed_point_revision':1})
        self.db.execute("INSERT INTO governed_retention_recurring_reviews(subject_id,outcome,procedure_state,state,policy_id,policy_revision,details_json,actor,occurred_at) VALUES(1,'I','under_review','completed','policy-syn',1,?,'owner-a','2026-10-19T00:00:00Z')", (details,)); self.db.commit()
        item = retention.get_subject(self.db, 'SYN-1')
        self.assertEqual((item['retention_review'], item['approval_state'], item['applicability_state']), ('due','approved_current','current'))

    def test_fixture_successors_are_immutable_and_invalidate_without_restoring_reliance(self):
        self.db.execute("UPDATE governed_retention_subjects SET retention_review='assessed',inventory_state='complete_with_limits',eligibility_state='eligible_current',decision_state='proposed_eligible_for_future_scope',approval_state='approved_current',applicability_state='current',procedure_state='under_review',version=129 WHERE identifier='SYN-1'"); self.db.commit()
        successor_policy = self._policy_document(False, due_at='2099-01-01T00:00:00Z', identity='policy-r2')
        policy_change = retention.replace_policy_fixture(self.db, subject_identifier='SYN-1', policy_document=successor_policy, owner_authority='synthetic-owner', owner_revision=1, actor=self.owner, expected_version=129, idempotency_key='policy-r2', reason='same-content successor')
        item = retention.get_subject(self.db, 'SYN-1')
        self.assertEqual((item['policy_revision'], item['stored_tuple'][2:6]), (2, ('stale','proposed_eligible_for_future_scope','stale','reassessment_required')))
        self.assertEqual(json.loads(self.db.execute("SELECT policy_json FROM governed_retention_policies WHERE policy_id='policy-syn' AND revision=1").fetchone()[0])['review_due_invalidates_current_reliance'], True)
        self.assertEqual(self.db.execute("SELECT count(*) FROM governed_retention_policies WHERE policy_id='policy-syn'").fetchone()[0], 2)
        repeated_policy = retention.replace_policy_fixture(self.db, subject_identifier='SYN-1', policy_document=successor_policy, owner_authority='synthetic-owner', owner_revision=1, actor=self.owner, expected_version=policy_change['resulting_version'], idempotency_key='policy-r3', reason='same-content repeat')
        self.assertEqual(retention.get_subject(self.db, 'SYN-1')['policy_revision'], 3)
        self.assertEqual(self.db.execute("SELECT count(*) FROM governed_retention_policies WHERE policy_id='policy-syn'").fetchone()[0], 3)
        self.db.execute("UPDATE governed_retention_subjects SET eligibility_state='eligible_current',approval_state='approved_current',applicability_state='current',version=? WHERE identifier='SYN-1'", (repeated_policy['resulting_version'],)); self.db.commit()
        reviewer_change = retention.replace_authority_fixture(self.db, subject_identifier='SYN-1', authority_id='synthetic-reviewer', role='reviewer', successor_username='reviewer-b', owner_authority='synthetic-owner', owner_revision=1, actor=self.owner, expected_version=repeated_policy['resulting_version'], idempotency_key='reviewer-r2', reason='replacement')
        self.assertEqual(self.db.execute("SELECT count(*) FROM governed_retention_authorities WHERE authority_id='synthetic-reviewer' AND role='reviewer'").fetchone()[0], 2)
        self.assertEqual(retention.get_subject(self.db, 'SYN-1')['stored_tuple'][2:6], ('stale','proposed_eligible_for_future_scope','stale','reassessment_required'))
        # A stale authority replacement itself did not fabricate a new approval.
        self.assertEqual(reviewer_change['operation'], 'IV-01-O')
        owner_change = retention.replace_authority_fixture(self.db, subject_identifier='SYN-1', authority_id='synthetic-owner', role='owner', successor_username='owner-a', owner_authority='synthetic-owner', owner_revision=1, actor=self.owner, expected_version=reviewer_change['resulting_version'], idempotency_key='owner-r2', reason='replacement')
        before = retention.get_subject(self.db, 'SYN-1')
        with self.assertRaisesRegex(ValueError, 'authority_unavailable'):
            retention.record_hold(self.db, subject_identifier='SYN-1', operation='place', hold_identifier='H-STALE-OWNER', owner_authority='synthetic-owner', owner_revision=1, evidence=['basis'], scope='scope', limitations='limits', actor=self.owner, expected_version=owner_change['resulting_version'], idempotency_key='stale-owner', reason='place')
        after = retention.get_subject(self.db, 'SYN-1')
        self.assertEqual((after['stored_tuple'], after['version'], after['history']), (before['stored_tuple'], before['version'], before['history']))

    def test_returned_availability_requires_explicit_reassessment_and_never_restores_approval(self):
        self.db.execute("UPDATE governed_retention_subjects SET retention_review='assessed',inventory_state='complete_with_limits',eligibility_state='eligible_current',decision_state='proposed_eligible_for_future_scope',approval_state='approved_current',applicability_state='current',procedure_state='under_review',version=130 WHERE identifier='SYN-1'")
        self.db.execute("INSERT INTO governed_retention_assessments(subject_id,subject_revision,policy_id,policy_revision,outcome,blocker,evidence_json,limitations,next_review_json,actor,occurred_at) VALUES(1,1,'policy-syn',1,'eligible',NULL,'[\"conditions\"]','limits',NULL,'owner-a','2026-10-20T00:00:00Z')")
        self.db.execute("INSERT INTO governed_retention_decisions(subject_id,assessment_id,revision,outcome,bindings_json,actor,occurred_at) VALUES(1,1,1,'eligible','{}','owner-a','2026-10-20T00:00:00Z')")
        self.db.execute("INSERT INTO governed_retention_approvals(subject_id,decision_id,revision,owner_fixture_id,owner_fixture_revision,actor,occurred_at) VALUES(1,1,1,'synthetic-owner',1,'owner-a','2026-10-20T00:00:00Z')")
        self.db.commit()
        unavailable = retention.invalidate(self.db, subject_identifier='SYN-1', unavailable=True, basis='authority-source-unavailable', actor=self.owner, expected_version=130, idempotency_key='availability-down', reason='unavailable')
        returned = retention.invalidate(self.db, subject_identifier='SYN-1', unavailable=False, basis='authority-source-returned', actor=self.owner, expected_version=unavailable['resulting_version'], idempotency_key='availability-returned', reason='returned')
        item = retention.get_subject(self.db, 'SYN-1')
        self.assertEqual((returned['operation'], item['stored_tuple'][2:6]), ('IV-01-O2', ('stale','proposed_eligible_for_future_scope','stale','reassessment_required')))
        with self.assertRaisesRegex(ValueError, 'closure_current_approval_required'):
            retention.close(self.db, subject_identifier='SYN-1', actor=self.owner, expected_version=returned['resulting_version'], idempotency_key='return-close', reason='close')
        recovered = retention.reassess_after_invalidation(self.db, subject_identifier='SYN-1', outcome='eligible', owner_authority='synthetic-owner', owner_revision=1, actor=self.owner, expected_version=returned['resulting_version'], idempotency_key='return-reassess', reason='fresh assessment')
        after = retention.get_subject(self.db, 'SYN-1')
        self.assertEqual((recovered['operation'], after['stored_tuple'][2:6]), ('RS-02-E', ('under_assessment','none','not_recorded','not_evaluated')))

    def test_rs02_ineligible_requires_phase_matched_invalidation_and_preserves_history(self):
        self.db.execute("UPDATE governed_retention_subjects SET retention_review='assessed',inventory_state='incomplete',eligibility_state='stale',decision_state='none',approval_state='not_recorded',applicability_state='reassessment_required',procedure_state='under_review',version=161 WHERE identifier='SYN-1'")
        self.db.execute("INSERT INTO governed_retention_assessments(subject_id,subject_revision,subject_binding_json,policy_id,policy_revision,outcome,blocker,evidence_json,limitations,next_review_json,actor,occurred_at) VALUES(1,1,'{}','policy-syn',1,'ineligible','applicable_active_hold','[\"hold\"]','gap','{}','owner-a','2026-10-19T00:00:00Z')")
        self.db.execute("INSERT INTO governed_retention_history(subject_id,operation_id,actor,reason,details_json,occurred_at) VALUES(1,'IV-01-P','owner-a','changed','{}','2026-10-19T00:00:00Z')")
        self.db.commit()
        before = (retention.get_subject(self.db, 'SYN-1')['stored_tuple'], retention.get_subject(self.db, 'SYN-1')['version'], self.db.execute("SELECT count(*) FROM governed_retention_history").fetchone()[0])
        with self.assertRaisesRegex(ValueError, 'reassessment_invalidation_binding_invalid'):
            retention.reassess_after_invalidation(self.db, subject_identifier='SYN-1', outcome='ineligible', owner_authority='synthetic-owner', owner_revision=1, actor=self.owner, expected_version=161, idempotency_key='rs02-i-wrong-phase', reason='wrong phase')
        self.assertEqual((retention.get_subject(self.db, 'SYN-1')['stored_tuple'], retention.get_subject(self.db, 'SYN-1')['version'], self.db.execute("SELECT count(*) FROM governed_retention_history").fetchone()[0]), before)
        self.db.execute("INSERT INTO governed_retention_history(subject_id,operation_id,actor,reason,details_json,occurred_at) VALUES(1,'IV-01-A','owner-a','changed','{}','2026-10-19T00:00:01Z')")
        self.db.commit()
        recovered = retention.reassess_after_invalidation(self.db, subject_identifier='SYN-1', outcome='ineligible', owner_authority='synthetic-owner', owner_revision=1, actor=self.owner, expected_version=161, idempotency_key='rs02-i', reason='fresh assessment')
        item = retention.get_subject(self.db, 'SYN-1')
        self.assertEqual((recovered['operation'], item['tuple']), ('RS-02-I', ('assessed','incomplete','under_assessment','none','not_recorded','not_evaluated','under_review')))

    def test_rs02_proposed_and_unavailable_chains_require_immutable_predecessors(self):
        # P: a real proposed decision is required; IV-01-P alone is not enough.
        self.db.execute("UPDATE governed_retention_subjects SET retention_review='assessed',inventory_state='complete_with_limits',eligibility_state='stale',decision_state='proposed_eligible_for_future_scope',approval_state='not_recorded',applicability_state='reassessment_required',procedure_state='under_review',version=171 WHERE identifier='SYN-1'")
        self.db.execute("INSERT INTO governed_retention_assessments(subject_id,subject_revision,subject_binding_json,policy_id,policy_revision,outcome,blocker,evidence_json,limitations,next_review_json,actor,occurred_at) VALUES(1,1,'{}','policy-syn',1,'eligible',NULL,'[\"conditions\"]','limits',NULL,'owner-a','2026-10-19T00:00:00Z')")
        self.db.execute("INSERT INTO governed_retention_history(subject_id,operation_id,actor,reason,details_json,occurred_at) VALUES(1,'IV-01-P','owner-a','changed','{}','2026-10-19T00:00:00Z')")
        self.db.commit()
        before = (retention.get_subject(self.db, 'SYN-1')['stored_tuple'], retention.get_subject(self.db, 'SYN-1')['version'], self.db.execute("SELECT count(*) FROM governed_retention_history").fetchone()[0])
        with self.assertRaisesRegex(ValueError, 'reassessment_decision_binding_invalid'):
            retention.reassess_after_invalidation(self.db, subject_identifier='SYN-1', outcome='eligible', owner_authority='synthetic-owner', owner_revision=1, actor=self.owner, expected_version=171, idempotency_key='rs02-p-missing-decision', reason='bad')
        self.assertEqual((retention.get_subject(self.db, 'SYN-1')['stored_tuple'], retention.get_subject(self.db, 'SYN-1')['version'], self.db.execute("SELECT count(*) FROM governed_retention_history").fetchone()[0]), before)
        self.db.execute("INSERT INTO governed_retention_decisions(subject_id,assessment_id,revision,outcome,bindings_json,actor,occurred_at) VALUES(1,1,1,'eligible','{}','owner-a','2026-10-19T00:00:00Z')")
        self.db.commit()
        recovered = retention.reassess_after_invalidation(self.db, subject_identifier='SYN-1', outcome='eligible', owner_authority='synthetic-owner', owner_revision=1, actor=self.owner, expected_version=171, idempotency_key='rs02-p', reason='fresh')
        self.assertEqual((recovered['operation'], retention.get_subject(self.db, 'SYN-1')['tuple']), ('RS-02-E', ('assessed','complete_with_limits','under_assessment','none','not_recorded','not_evaluated','under_review')))

    def test_rs02_unavailable_preserves_unavailability_without_restoring_reliance(self):
        self.db.execute("UPDATE governed_retention_subjects SET retention_review='assessed',inventory_state='unavailable',eligibility_state='unavailable',decision_state='none',approval_state='not_recorded',applicability_state='unavailable',procedure_state='under_review',version=172 WHERE identifier='SYN-1'")
        self.db.execute("INSERT INTO governed_retention_assessments(subject_id,subject_revision,subject_binding_json,policy_id,policy_revision,outcome,blocker,evidence_json,limitations,next_review_json,actor,occurred_at) VALUES(1,1,'{}','policy-syn',1,'ineligible','applicable_active_hold','[\"hold\"]','unavailable','{}','owner-a','2026-10-19T00:00:00Z')")
        self.db.execute("INSERT INTO governed_retention_history(subject_id,operation_id,actor,reason,details_json,occurred_at) VALUES(1,'IV-01-A','owner-a','unavailable','{}','2026-10-19T00:00:00Z')")
        self.db.commit()
        before = (retention.get_subject(self.db, 'SYN-1')['stored_tuple'], retention.get_subject(self.db, 'SYN-1')['version'], self.db.execute("SELECT count(*) FROM governed_retention_history").fetchone()[0])
        with self.assertRaisesRegex(ValueError, 'authority_unavailable'):
            self.db.execute("UPDATE governed_retention_authorities SET available=0 WHERE authority_id='synthetic-owner' AND revision=1 AND role='owner'"); self.db.commit()
            retention.reassess_after_invalidation(self.db, subject_identifier='SYN-1', outcome='ineligible', owner_authority='synthetic-owner', owner_revision=1, actor=self.owner, expected_version=172, idempotency_key='rs02-u-stale-owner', reason='bad')
        self.assertEqual((retention.get_subject(self.db, 'SYN-1')['stored_tuple'], retention.get_subject(self.db, 'SYN-1')['version'], self.db.execute("SELECT count(*) FROM governed_retention_history").fetchone()[0]), before)
        self.db.execute("UPDATE governed_retention_authorities SET available=1 WHERE authority_id='synthetic-owner' AND revision=1 AND role='owner'"); self.db.commit()
        recovered = retention.reassess_after_invalidation(self.db, subject_identifier='SYN-1', outcome='ineligible', owner_authority='synthetic-owner', owner_revision=1, actor=self.owner, expected_version=172, idempotency_key='rs02-u', reason='fresh')
        self.assertEqual((recovered['operation'], retention.get_subject(self.db, 'SYN-1')['tuple']), ('RS-02-I', ('assessed','unavailable','unavailable','none','not_recorded','unavailable','under_review')))

    def test_due_observation_replay_is_historical_not_a_second_currentness_event(self):
        self.db.execute("UPDATE governed_retention_policies SET policy_json=? WHERE policy_id='policy-syn' AND revision=1", (json.dumps(self._policy_document(True, due_at='2026-01-01T00:00:00Z', identity='replay-point')),))
        self._seed_current_approved_chain(version=123)
        first = retention.apply_review_due(self.db, subject_identifier='SYN-1', reached_point='replay-point', actor=self.owner, expected_version=123, idempotency_key='same-due', reason='due')
        replay = retention.apply_review_due(self.db, subject_identifier='SYN-1', reached_point='replay-point', actor=self.owner, expected_version=123, idempotency_key='same-due', reason='due')
        self.assertEqual((first['resulting_version'], replay['resulting_version'], replay['historical']), (124, 124, True))
        self.assertEqual(self.db.execute("SELECT count(*) FROM governed_retention_history WHERE subject_id=1 AND operation_id='RD-01'").fetchone()[0], 1)

    def test_ineligible_closure_keeps_inventory_gap_and_bound_followup(self):
        started = retention.start_initial_review(self.db, subject_identifier='SYN-1', actor=self.owner, expected_version=1, idempotency_key='i-start', reason='start')
        gap = retention.record_inventory(self.db, subject_identifier='SYN-1', outcome='incomplete', copies={'backups': {'status':'unknown'}}, evidence=['gap'], limitations='gap', actor=self.owner, expected_version=started['resulting_version'], idempotency_key='i-gap', reason='gap')
        self.db.execute("UPDATE governed_retention_subjects SET retention_review='assessed' WHERE identifier='SYN-1'")
        self.db.execute("INSERT INTO governed_retention_holds(subject_id,hold_identifier,revision,state,basis,evidence_json,scope,limitations,owner_fixture_id,owner_fixture_revision,actor,occurred_at) VALUES(1,'H-BLOCK',1,'active','basis','[]','scope','limits','synthetic-owner',1,'owner-a','2026-10-19T00:00:00Z')")
        self.db.commit()
        self._seed_current_hold_applicability('H-BLOCK')
        assessed = retention.assess_decision(self.db, subject_identifier='SYN-1', outcome='ineligible', blocker='applicable_active_hold', evidence=['hold'], limitations='gap retained', next_review={'point':'2027-01-01','responsible':'owner-a', 'reason':'hold', 'scope':'synthetic'}, actor=self.owner, expected_version=gap['resulting_version'], idempotency_key='i-assess', reason='blocked')
        proposed = retention.propose_decision(self.db, subject_identifier='SYN-1', outcome='ineligible', actor=self.owner, expected_version=assessed['resulting_version'], idempotency_key='i-propose', reason='propose')
        reviewed = retention.independent_review(self.db, subject_identifier='SYN-1', reviewer_authority='synthetic-reviewer', reviewer_revision=1, actor=self.reviewer, expected_version=proposed['resulting_version'], idempotency_key='i-review', reason='review', evidence=['review'])
        approved = retention.owner_decision(self.db, subject_identifier='SYN-1', approve=True, owner_authority='synthetic-owner', owner_revision=1, actor=self.owner, expected_version=reviewed['resulting_version'], idempotency_key='i-approve', reason='approve')
        closed = retention.close(self.db, subject_identifier='SYN-1', actor=self.owner, expected_version=approved['resulting_version'], idempotency_key='i-close', reason='close')
        item = retention.get_subject(self.db, 'SYN-1')
        self.assertEqual((item['inventory_state'],item['eligibility_state'],item['procedure_state']), ('incomplete','ineligible_current','closed'))
        self.assertEqual(closed['operation'], 'CL-02')

    def test_owner_rejection_requires_review_and_recovery_keeps_rejection_history(self):
        started = retention.start_initial_review(self.db, subject_identifier='SYN-1', actor=self.owner, expected_version=1, idempotency_key='rj-start', reason='start')
        copies = {name: {'applicable': True, 'identity': name, 'control': 'synthetic'} for name in retention.COPY_CLASSES}
        inventory = retention.record_inventory(self.db, subject_identifier='SYN-1', outcome='complete_with_limits', copies=copies, evidence=['inventory'], limitations='limits', actor=self.owner, expected_version=started['resulting_version'], idempotency_key='rj-inventory', reason='inventory')
        complete = retention.complete_review(self.db, subject_identifier='SYN-1', evidence=['review'], limitations='limits', actor=self.owner, expected_version=inventory['resulting_version'], idempotency_key='rj-complete', reason='complete')
        assessed = retention.assess_decision(self.db, subject_identifier='SYN-1', outcome='eligible', blocker=None, evidence=['conditions'], limitations='limits', next_review=None, actor=self.owner, expected_version=complete['resulting_version'], idempotency_key='rj-assess', reason='assess')
        proposed = retention.propose_decision(self.db, subject_identifier='SYN-1', outcome='eligible', actor=self.owner, expected_version=assessed['resulting_version'], idempotency_key='rj-propose', reason='propose')
        with self.assertRaisesRegex(ValueError, 'independent_review_required'):
            retention.owner_decision(self.db, subject_identifier='SYN-1', approve=False, owner_authority='synthetic-owner', owner_revision=1, actor=self.owner, expected_version=proposed['resulting_version'], idempotency_key='rj-missing-review', reason='reject')
        review = retention.independent_review(self.db, subject_identifier='SYN-1', reviewer_authority='synthetic-reviewer', reviewer_revision=1, actor=self.reviewer, expected_version=proposed['resulting_version'], idempotency_key='rj-review', reason='review', evidence=['review'])
        rejected = retention.owner_decision(self.db, subject_identifier='SYN-1', approve=False, owner_authority='synthetic-owner', owner_revision=1, actor=self.owner, expected_version=review['resulting_version'], idempotency_key='rj-reject', reason='reject')
        recovered = retention.recover_rejected_proposal(self.db, subject_identifier='SYN-1', actor=self.owner, expected_version=rejected['resulting_version'], idempotency_key='rj-recover', reason='reassess')
        history = retention.get_subject(self.db, 'SYN-1')['history']
        self.assertIn('D-07-E', [event['operation_id'] for event in history])
        rejection = next(event for event in history if event['operation_id'] == 'D-07-E')
        payload = json.loads(rejection['details_json'])['payload']
        self.assertEqual((payload['assessment_id'], payload['decision_revision'], payload['review_revision'], payload['subject_revision'], payload['policy_revision']), (1, 1, 1, 1, 1))
        self.assertEqual(retention.get_subject(self.db, 'SYN-1')['tuple'][2:6], ('under_assessment','none','not_recorded','not_evaluated'))
        self.assertEqual(recovered['operation'], 'RS-01-E')

    def test_ineligible_rejection_and_recovery_preserve_immutable_predecessors(self):
        started = retention.start_initial_review(self.db, subject_identifier='SYN-1', actor=self.owner, expected_version=1, idempotency_key='rji-start', reason='start')
        gap = retention.record_inventory(self.db, subject_identifier='SYN-1', outcome='incomplete', copies={'backup': {'status':'unknown'}}, evidence=['gap'], limitations='gap', actor=self.owner, expected_version=started['resulting_version'], idempotency_key='rji-gap', reason='gap')
        self.db.execute("UPDATE governed_retention_subjects SET retention_review='assessed' WHERE identifier='SYN-1'")
        self.db.execute("INSERT INTO governed_retention_holds(subject_id,hold_identifier,revision,state,basis,evidence_json,scope,limitations,owner_fixture_id,owner_fixture_revision,actor,occurred_at) VALUES(1,'H-RJI',1,'active','basis','[]','scope','limits','synthetic-owner',1,'owner-a','2026-10-19T00:00:00Z')")
        self.db.commit(); self._seed_current_hold_applicability('H-RJI')
        assessed = retention.assess_decision(self.db, subject_identifier='SYN-1', outcome='ineligible', blocker='applicable_active_hold', evidence=['hold'], limitations='gap', next_review={'point':'next','responsible':'owner-a','reason':'hold','scope':'scope'}, actor=self.owner, expected_version=gap['resulting_version'], idempotency_key='rji-assess', reason='assess')
        proposed = retention.propose_decision(self.db, subject_identifier='SYN-1', outcome='ineligible', actor=self.owner, expected_version=assessed['resulting_version'], idempotency_key='rji-propose', reason='propose')
        reviewed = retention.independent_review(self.db, subject_identifier='SYN-1', reviewer_authority='synthetic-reviewer', reviewer_revision=1, actor=self.reviewer, expected_version=proposed['resulting_version'], idempotency_key='rji-review', reason='review', evidence=['review'])
        rejected = retention.owner_decision(self.db, subject_identifier='SYN-1', approve=False, owner_authority='synthetic-owner', owner_revision=1, actor=self.owner, expected_version=reviewed['resulting_version'], idempotency_key='rji-reject', reason='reject')
        before = (retention.get_subject(self.db, 'SYN-1')['tuple'], self.db.execute("SELECT count(*) FROM governed_retention_history").fetchone()[0])
        with self.assertRaisesRegex(ValueError, 'retention_version_conflict'):
            retention.recover_rejected_proposal(self.db, subject_identifier='SYN-1', actor=self.owner, expected_version=rejected['resulting_version'] - 1, idempotency_key='rji-stale', reason='recover')
        self.assertEqual((retention.get_subject(self.db, 'SYN-1')['tuple'], self.db.execute("SELECT count(*) FROM governed_retention_history").fetchone()[0]), before)
        recovered = retention.recover_rejected_proposal(self.db, subject_identifier='SYN-1', actor=self.owner, expected_version=rejected['resulting_version'], idempotency_key='rji-recover', reason='recover')
        self.assertEqual((recovered['operation'], retention.get_subject(self.db, 'SYN-1')['tuple']), ('RS-01-I', ('assessed','incomplete','under_assessment','none','not_recorded','not_evaluated','under_review')))

    def test_rejection_refuses_stale_reviewer_fixture_without_partial_history(self):
        started = retention.start_initial_review(self.db, subject_identifier='SYN-1', actor=self.owner, expected_version=1, idempotency_key='d7-start', reason='start')
        copies = {name: {'applicable': True, 'identity': name, 'control': 'synthetic'} for name in retention.COPY_CLASSES}
        inventory = retention.record_inventory(self.db, subject_identifier='SYN-1', outcome='complete_with_limits', copies=copies, evidence=['inventory'], limitations='limits', actor=self.owner, expected_version=started['resulting_version'], idempotency_key='d7-inventory', reason='inventory')
        completed = retention.complete_review(self.db, subject_identifier='SYN-1', evidence=['review'], limitations='limits', actor=self.owner, expected_version=inventory['resulting_version'], idempotency_key='d7-complete', reason='complete')
        assessed = retention.assess_decision(self.db, subject_identifier='SYN-1', outcome='eligible', blocker=None, evidence=['conditions'], limitations='limits', next_review=None, actor=self.owner, expected_version=completed['resulting_version'], idempotency_key='d7-assess', reason='assess')
        proposed = retention.propose_decision(self.db, subject_identifier='SYN-1', outcome='eligible', actor=self.owner, expected_version=assessed['resulting_version'], idempotency_key='d7-propose', reason='propose')
        reviewed = retention.independent_review(self.db, subject_identifier='SYN-1', reviewer_authority='synthetic-reviewer', reviewer_revision=1, actor=self.reviewer, expected_version=proposed['resulting_version'], idempotency_key='d7-review', reason='review', evidence=['review'])
        self.db.execute("UPDATE governed_retention_authorities SET available=0 WHERE authority_id='synthetic-reviewer' AND revision=1 AND role='reviewer'"); self.db.commit()
        before = retention.get_subject(self.db, 'SYN-1')
        before_rows = tuple(self.db.execute("SELECT (SELECT count(*) FROM governed_retention_decisions), (SELECT count(*) FROM governed_retention_reviews), (SELECT count(*) FROM governed_retention_history)").fetchone())
        with self.assertRaisesRegex(ValueError, 'authority_unavailable'):
            retention.owner_decision(self.db, subject_identifier='SYN-1', approve=False, owner_authority='synthetic-owner', owner_revision=1, actor=self.owner, expected_version=reviewed['resulting_version'], idempotency_key='d7-stale-reviewer', reason='reject')
        after = retention.get_subject(self.db, 'SYN-1')
        after_rows = tuple(self.db.execute("SELECT (SELECT count(*) FROM governed_retention_decisions), (SELECT count(*) FROM governed_retention_reviews), (SELECT count(*) FROM governed_retention_history)").fetchone())
        self.assertEqual((after['stored_tuple'], after['version'], after_rows), (before['stored_tuple'], before['version'], before_rows))


if __name__ == "__main__": unittest.main()
