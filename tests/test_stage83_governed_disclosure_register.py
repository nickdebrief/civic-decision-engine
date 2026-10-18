"""Synthetic-only Stage 83 service coverage."""
import base64
import hashlib
import hmac
import json
import os
import sqlite3
import time
import unittest

from api import governed_disclosure_register as register
from api import governed_defect_register as defects


def _token(username="admin-a"):
    payload = {"role": "admin", "username": username, "issued_at": int(time.time()), "expires_at": int(time.time()) + 3600}
    encoded = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).rstrip(b"=").decode()
    signature = base64.urlsafe_b64encode(hmac.new(os.environ["CDE_ADMIN_SESSION_SECRET"].encode(), encoded.encode(), hashlib.sha256).digest()).rstrip(b"=").decode()
    return f"{encoded}.{signature}"


class DisclosureRegisterTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:"); self.conn.row_factory = sqlite3.Row
        register.ensure_tables(self.conn)
        self.conn.execute("INSERT INTO governed_disclosure_synthetic_authorities(rule_identity,authority_identity,approver_username,revision,requires_review,available) VALUES(?,?,?,?,?,?)", ("synthetic-rule-v1", "synthetic-authority-v1", "admin-a", 1, 0, 1))
        self.conn.execute("INSERT INTO governed_disclosure_synthetic_authorities(rule_identity,authority_identity,approver_username,revision,requires_review,available) VALUES(?,?,?,?,?,?)", ("rule", "synthetic-authority-v1", "admin-a", 1, 0, 1))
        self.conn.commit()
        self.old = os.environ.get("CDE_ADMIN_SESSION_SECRET"); os.environ["CDE_ADMIN_SESSION_SECRET"] = "stage83-test-secret"
        self.token = _token()
        self.seed()

    def tearDown(self):
        if self.old is None: os.environ.pop("CDE_ADMIN_SESSION_SECRET", None)
        else: os.environ["CDE_ADMIN_SESSION_SECRET"] = self.old
        self.conn.close()

    def seed(self, identifier="DREQ-SYN-1", items=("ITEM-1",)):
        now = "2026-10-18T00:00:00Z"
        request = self.conn.execute("INSERT INTO governed_disclosure_requests(request_identifier,request_revision,procedural_state,version,created_at,created_by,updated_at,updated_by) VALUES(?,?,?,?,?,?,?,?)", (identifier, 1, "recorded", 1, now, "fixture", now, "fixture")).lastrowid
        for key in items:
            self.conn.execute("INSERT INTO governed_disclosure_items(request_id,item_identifier,object_type,object_identity,object_version,item_revision,assessment_state,approval_state,outcome,applicability_state,conditions_json,hold_json,version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (request, key, "record_version", f"synthetic-{key}", "v1", 1, "unassessed", "not_recorded", "none", "not_evaluated", "{}", "{}", 1))
        self.conn.commit(); return identifier

    def item(self, identifier="DREQ-SYN-1"):
        return register.get_request(self.conn, identifier)

    def complete_and_approve(self, identifier="DREQ-SYN-1", key="ITEM-1", version=1, outcome="withhold"):
        started = register.begin_assessment(self.conn, request_identifier=identifier, item_identifier=key, actor=self.token, expected_version=version, idempotency_key=f"{key}-start-{version}", reason="synthetic assessment")
        complete = register.complete_assessment(self.conn, request_identifier=identifier, item_identifier=key, basis="synthetic basis", evidence=[{"reference": "synthetic-evidence"}], limitations="synthetic limits", rule_identity="synthetic-rule-v1", authority_identity="synthetic-authority-v1", actor=self.token, expected_version=started["resulting_version"], idempotency_key=f"{key}-complete-{version}", reason="complete")
        proposed = register.record_outcome(self.conn, request_identifier=identifier, item_identifier=key, outcome=outcome, details={"reason": "synthetic"}, actor=self.token, expected_version=complete["resulting_version"], idempotency_key=f"{key}-outcome-{version}", reason="propose")
        return register.approve_outcome(self.conn, request_identifier=identifier, item_identifier=key, outcome_revision=1, synthetic_rule_authority="synthetic-authority-v1", actor=self.token, expected_version=proposed["resulting_version"], idempotency_key=f"{key}-approve-{version}", reason="synthetic approval")

    def authoritative_stage81(self, identifier="DREG-REL-1"):
        """Seed a fully bound Stage 81 correction only in disposable storage."""
        defects.ensure_tables(self.conn)
        stamp = "2026-10-18T00:00:00Z"
        action = {"action_id": f"action-{identifier}", "agreed_version": 2,
                  "acceptance_criteria_identity": "synthetic-criteria",
                  "acceptance_criteria": ["criterion"],
                  "execution_status": "execution_substantiated", "execution_reference_id": 0}
        entry_id = self.conn.execute("""INSERT INTO governed_defect_register_entries
          (entry_identifier,title,description,affected_component,observed_behavior,expected_behavior,expectation_source,reporter_source,lifecycle_state,assessment_classification,priority,owner_reference,impact_status,deferral_json,closure_json,preservation_hold_json,retention_review_json,active_action_json,synthetic_attestation_json,version,created_at,created_by,updated_at,updated_by)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
          (identifier,"s","s","c","o","e","x","fixture","closed","confirmed_defect","unprioritised",None,"not_performed",None,None,None,None,"{}","{}",1,stamp,"fixture",stamp,"fixture")).lastrowid
        checks = defects._json([{"step":"relationship_substantiated","status":"passed"}])
        execution_id = self.conn.execute("INSERT INTO governed_defect_register_references(entry_id,entry_identifier,reference_type,reference_value,relation,neutral_label,supplier_identity,validator_identity,validation_steps_json,created_at,created_by) VALUES(?,?,?,?,?,?,?,?,?,?,?)", (entry_id,identifier,"git_commit","execution","execution_evidence","execution",None,None,checks,stamp,"fixture")).lastrowid
        action["execution_reference_id"] = execution_id
        binding = defects._json({"action_id":action["action_id"],"action_agreed_version":2,"acceptance_criteria_identity":"synthetic-criteria","execution_reference_id":execution_id,"artifact_reference_type":"git_commit","artifact_reference_value":"artifact"})
        artifact_id = self.conn.execute("INSERT INTO governed_defect_register_references(entry_id,entry_identifier,reference_type,reference_value,relation,neutral_label,supplier_identity,validator_identity,validation_steps_json,verification_binding_json,created_at,created_by) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (entry_id,identifier,"git_commit","artifact","verification_evidence","artifact",None,None,checks,binding,stamp,"fixture")).lastrowid
        closure = defects._json({"outcome":"correction_verified","verification":{"action_id":action["action_id"],"execution_reference_id":execution_id,"artifact_reference_id":artifact_id,"criteria_results":{"criterion":"passed"}}})
        self.conn.execute("UPDATE governed_defect_register_entries SET active_action_json=?,closure_json=? WHERE id=?", (defects._json(action),closure,entry_id)); self.conn.commit()
        return identifier

    def test_real_admission_is_disabled_and_forged_actor_fails(self):
        with self.assertRaisesRegex(ValueError, "admission_disabled"): register.create_request(self.conn, {})
        with self.assertRaisesRegex(ValueError, "authenticated_actor_required"):
            register.begin_assessment(self.conn, request_identifier="DREQ-SYN-1", item_identifier="ITEM-1", actor={"username": "admin-a"}, expected_version=1, idempotency_key="forged", reason="bad")
        self.assertEqual(self.item()["version"], 1)

    def test_complete_whole_item_path_closes_and_historical_retry_is_labelled(self):
        approved = self.complete_and_approve()
        closed = register.close_request(self.conn, request_identifier="DREQ-SYN-1", actor=self.token, expected_version=approved["resulting_version"], idempotency_key="close", reason="all accounted")
        replay = register.close_request(self.conn, request_identifier="DREQ-SYN-1", actor=self.token, expected_version=approved["resulting_version"], idempotency_key="close", reason="all accounted")
        self.assertTrue(replay["historical_receipt"]); self.assertEqual(closed["resulting_version"], 6)
        self.assertEqual(self.item()["summary"]["state"], "closed")

    def test_admin_identity_is_not_synthetic_rule_authority(self):
        started = register.begin_assessment(self.conn, request_identifier="DREQ-SYN-1", item_identifier="ITEM-1", actor=self.token, expected_version=1, idempotency_key="start", reason="start")
        done = register.complete_assessment(self.conn, request_identifier="DREQ-SYN-1", item_identifier="ITEM-1", basis="basis", evidence=[{"x": "y"}], limitations="limits", rule_identity="rule", authority_identity="synthetic-authority-v1", actor=self.token, expected_version=started["resulting_version"], idempotency_key="done", reason="done")
        proposed = register.record_outcome(self.conn, request_identifier="DREQ-SYN-1", item_identifier="ITEM-1", outcome="decline", details={"why": "synthetic"}, actor=self.token, expected_version=done["resulting_version"], idempotency_key="out", reason="out")
        with self.assertRaisesRegex(ValueError, "approval_binding_mismatch"):
            register.approve_outcome(self.conn, request_identifier="DREQ-SYN-1", item_identifier="ITEM-1", outcome_revision=1, synthetic_rule_authority="admin-a", actor=self.token, expected_version=proposed["resulting_version"], idempotency_key="bad", reason="bad")
        self.assertEqual(self.item()["version"], proposed["resulting_version"])

    def test_amendment_same_text_resets_and_closed_request_reopens_atomically(self):
        approved = self.complete_and_approve()
        closed = register.close_request(self.conn, request_identifier="DREQ-SYN-1", actor=self.token, expected_version=approved["resulting_version"], idempotency_key="close", reason="close")
        changed = register.amend_item(self.conn, request_identifier="DREQ-SYN-1", item_identifier="ITEM-1", object_version="v1", actor=self.token, expected_version=closed["resulting_version"], idempotency_key="same-text-amend", reason="same text creates revision")
        item = self.item(); self.assertEqual(item["procedural_state"], "reopened")
        self.assertEqual(item["items"][0]["assessment_state"], "under_assessment")
        self.assertEqual(item["items"][0]["outcome"], "none")
        self.assertEqual(changed["resulting_version"], closed["resulting_version"] + 1)

    def test_mixed_summary_and_closure_are_exhaustive(self):
        self.seed("DREQ-SYN-2", ("ONE", "TWO"))
        started = register.begin_assessment(self.conn, request_identifier="DREQ-SYN-2", item_identifier="ONE", actor=self.token, expected_version=1, idempotency_key="one-start", reason="start")
        awaiting = register.request_information(self.conn, request_identifier="DREQ-SYN-2", item_identifier="ONE", missing_information="synthetic detail", review_point="synthetic trigger", actor=self.token, expected_version=started["resulting_version"], idempotency_key="one-info", reason="wait")
        self.assertEqual(self.item("DREQ-SYN-2")["summary"]["state"], "awaiting_information")
        with self.assertRaisesRegex(ValueError, "closure_incomplete"):
            register.close_request(self.conn, request_identifier="DREQ-SYN-2", actor=self.token, expected_version=awaiting["resulting_version"], idempotency_key="bad-close", reason="not all items")

    def test_stale_assessment_and_concurrent_version_leave_no_partial_outcome(self):
        started = register.begin_assessment(self.conn, request_identifier="DREQ-SYN-1", item_identifier="ITEM-1", actor=self.token, expected_version=1, idempotency_key="start", reason="start")
        done = register.complete_assessment(self.conn, request_identifier="DREQ-SYN-1", item_identifier="ITEM-1", basis="basis", evidence=[{"x": "y"}], limitations="limits", rule_identity="rule", authority_identity="synthetic-authority-v1", actor=self.token, expected_version=started["resulting_version"], idempotency_key="done", reason="done")
        register.amend_item(self.conn, request_identifier="DREQ-SYN-1", item_identifier="ITEM-1", object_version="v2", actor=self.token, expected_version=done["resulting_version"], idempotency_key="amend", reason="changed")
        with self.assertRaisesRegex(ValueError, "version_conflict"):
            register.record_outcome(self.conn, request_identifier="DREQ-SYN-1", item_identifier="ITEM-1", outcome="withhold", details={}, actor=self.token, expected_version=done["resulting_version"], idempotency_key="stale", reason="stale")
        self.assertEqual(self.conn.execute("SELECT count(*) FROM governed_disclosure_outcomes").fetchone()[0], 0)

    def test_unknown_matching_authority_and_request_revision_reuse_fail(self):
        started = register.begin_assessment(self.conn, request_identifier="DREQ-SYN-1", item_identifier="ITEM-1", actor=self.token, expected_version=1, idempotency_key="a-start", reason="start")
        with self.assertRaisesRegex(ValueError, "authority_unavailable"):
            register.complete_assessment(self.conn, request_identifier="DREQ-SYN-1", item_identifier="ITEM-1", basis="basis", evidence=[{"x":"y"}], limitations="limits", rule_identity="invented", authority_identity="invented", actor=self.token, expected_version=started["resulting_version"], idempotency_key="invented", reason="bad")
        self.assertEqual(self.item()["version"], started["resulting_version"])
        self.seed("DREQ-SYN-MULTI", ("A", "B"))
        a = self.complete_and_approve("DREQ-SYN-MULTI", "A", 1)
        b = self.complete_and_approve("DREQ-SYN-MULTI", "B", a["resulting_version"])
        amended = register.amend_item(self.conn, request_identifier="DREQ-SYN-MULTI", item_identifier="A", object_version="v2", actor=self.token, expected_version=b["resulting_version"], idempotency_key="multi-amend", reason="change")
        item = self.item("DREQ-SYN-MULTI")
        self.assertEqual([row["approval_state"] for row in item["items"]], ["not_recorded", "not_recorded"])
        with self.assertRaisesRegex(ValueError, "closure_incomplete"):
            register.close_request(self.conn, request_identifier="DREQ-SYN-MULTI", actor=self.token, expected_version=amended["resulting_version"], idempotency_key="multi-close", reason="stale")

    def test_authority_fixture_revision_change_invalidates_pending_outcome_without_writes(self):
        started = register.begin_assessment(self.conn, request_identifier="DREQ-SYN-1", item_identifier="ITEM-1", actor=self.token, expected_version=1, idempotency_key="rev-start", reason="start")
        complete = register.complete_assessment(self.conn, request_identifier="DREQ-SYN-1", item_identifier="ITEM-1", basis="basis", evidence=[{"x":"y"}], limitations="limits", rule_identity="synthetic-rule-v1", authority_identity="synthetic-authority-v1", actor=self.token, expected_version=started["resulting_version"], idempotency_key="rev-complete", reason="complete")
        proposed = register.record_outcome(self.conn, request_identifier="DREQ-SYN-1", item_identifier="ITEM-1", outcome="withhold", details={"reason":"synthetic"}, actor=self.token, expected_version=complete["resulting_version"], idempotency_key="rev-outcome", reason="outcome")
        self.conn.execute("INSERT INTO governed_disclosure_synthetic_authorities(rule_identity,authority_identity,approver_username,revision,requires_review,available) VALUES(?,?,?,?,?,?)", ("synthetic-rule-v1", "synthetic-authority-v1", "admin-a", 2, 0, 1)); self.conn.commit()
        approvals = self.conn.execute("SELECT count(*) FROM governed_disclosure_approvals").fetchone()[0]
        with self.assertRaisesRegex(ValueError, "approval_binding_mismatch"):
            register.approve_outcome(self.conn, request_identifier="DREQ-SYN-1", item_identifier="ITEM-1", outcome_revision=1, synthetic_rule_authority="synthetic-authority-v1", actor=self.token, expected_version=proposed["resulting_version"], idempotency_key="rev-stale", reason="stale")
        self.assertEqual(self.conn.execute("SELECT count(*) FROM governed_disclosure_approvals").fetchone()[0], approvals)
        reset = register.reassess(self.conn, request_identifier="DREQ-SYN-1", item_identifier="ITEM-1", actor=self.token, expected_version=proposed["resulting_version"], idempotency_key="rev-reassess", reason="authority changed")
        self.assertEqual(self.item()["items"][0]["assessment_state"], "under_assessment")
        self.assertEqual(reset["resulting_version"], proposed["resulting_version"] + 1)

    def test_withdrawal_requires_bound_assessment_and_preserves_obligations(self):
        started = register.begin_assessment(self.conn, request_identifier="DREQ-SYN-1", item_identifier="ITEM-1", actor=self.token, expected_version=1, idempotency_key="wd-start", reason="start")
        complete = register.complete_assessment(self.conn, request_identifier="DREQ-SYN-1", item_identifier="ITEM-1", basis="basis", evidence=[{"x":"y"}], limitations="limits", rule_identity="synthetic-rule-v1", authority_identity="synthetic-authority-v1", actor=self.token, expected_version=started["resulting_version"], idempotency_key="wd-complete", reason="complete")
        with self.assertRaisesRegex(ValueError, "outcome_assessment_required"):
            register.record_outcome(self.conn, request_identifier="DREQ-SYN-1", item_identifier="ITEM-1", outcome="withdrawn", details={"reason":"generic"}, actor=self.token, expected_version=complete["resulting_version"], idempotency_key="wd-generic", reason="generic")
        assessed = register.record_outcome_assessment(self.conn, request_identifier="DREQ-SYN-1", item_identifier="ITEM-1", proposed_outcome="withdrawn", basis="withdrawal basis", evidence=[{"reference":"synthetic"}], validation_scope="synthetic scope", assessment_scope="item", limitations="limits", obligations=[{"description":"retain follow-up", "owner":"admin-a", "status":"open"}], actor=self.token, expected_version=complete["resulting_version"], idempotency_key="wd-assess", reason="assess")
        proposed = register.record_outcome(self.conn, request_identifier="DREQ-SYN-1", item_identifier="ITEM-1", outcome="withdrawn", details={"reason":"withdrawn"}, actor=self.token, expected_version=assessed["resulting_version"], idempotency_key="wd-outcome", reason="outcome")
        approved = register.approve_outcome(self.conn, request_identifier="DREQ-SYN-1", item_identifier="ITEM-1", outcome_revision=1, synthetic_rule_authority="synthetic-authority-v1", actor=self.token, expected_version=proposed["resulting_version"], idempotency_key="wd-approve", reason="approve")
        viewed = self.item(); self.assertEqual(approved["resulting_version"], 6)
        self.assertEqual(viewed["active_obligations"][0]["description"], "retain follow-up")

    def test_supersession_requires_bound_assessment_and_generic_link_rejects(self):
        self.seed("DREQ-SUP", ("OLD", "NEW")); version = 1
        for key in ("OLD", "NEW"):
            started = register.begin_assessment(self.conn, request_identifier="DREQ-SUP", item_identifier=key, actor=self.token, expected_version=version, idempotency_key=f"{key}-start", reason="start")
            complete = register.complete_assessment(self.conn, request_identifier="DREQ-SUP", item_identifier=key, basis="basis", evidence=[{"x":key}], limitations="limits", rule_identity="synthetic-rule-v1", authority_identity="synthetic-authority-v1", actor=self.token, expected_version=started["resulting_version"], idempotency_key=f"{key}-complete", reason="complete")
            version = complete["resulting_version"]
        with self.assertRaisesRegex(ValueError, "successor_assessment_required"):
            register.link_successor(self.conn, request_identifier="DREQ-SUP", predecessor_item_identifier="OLD", successor_item_identifier="NEW", basis="generic", limitations="limits", actor=self.token, expected_version=version, idempotency_key="generic-link", reason="generic")
        assessed = register.record_outcome_assessment(self.conn, request_identifier="DREQ-SUP", item_identifier="OLD", proposed_outcome="superseded", basis="successor basis", evidence=[{"reference":"synthetic"}], validation_scope="synthetic scope", assessment_scope="both items", limitations="limits", obligations=[], successor_item_identifier="NEW", actor=self.token, expected_version=version, idempotency_key="sup-assess", reason="assess")
        proposed = register.record_outcome(self.conn, request_identifier="DREQ-SUP", item_identifier="OLD", outcome="superseded", details={"reason":"successor"}, actor=self.token, expected_version=assessed["resulting_version"], idempotency_key="sup-outcome", reason="outcome")
        approved = register.approve_outcome(self.conn, request_identifier="DREQ-SUP", item_identifier="OLD", outcome_revision=1, synthetic_rule_authority="synthetic-authority-v1", actor=self.token, expected_version=proposed["resulting_version"], idempotency_key="sup-approve", reason="approve")
        self.assertEqual(self.conn.execute("SELECT count(*) FROM governed_disclosure_relationships").fetchone()[0], 1)
        register.amend_item(self.conn, request_identifier="DREQ-SUP", item_identifier="NEW", object_version="v2", actor=self.token, expected_version=approved["resulting_version"], idempotency_key="sup-amend", reason="changed successor")
        self.assertEqual(self.item("DREQ-SUP")["items"][0]["applicability_state"], "not_evaluated")

    def test_passive_stage81_link_requires_exact_current_target(self):
        defects.ensure_tables(self.conn)
        now = "2026-10-18T00:00:00Z"
        self.conn.execute("INSERT INTO governed_defect_register_entries(entry_identifier,title,description,affected_component,observed_behavior,expected_behavior,expectation_source,reporter_source,lifecycle_state,assessment_classification,priority,owner_reference,impact_status,deferral_json,closure_json,preservation_hold_json,retention_review_json,active_action_json,synthetic_attestation_json,version,created_at,created_by,updated_at,updated_by) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", ("CDE-DEF-SYN-1", "synthetic", "synthetic", "component", "observed", "expected", "test", "fixture", "reported", "unassessed", "unprioritised", None, "not_performed", None, None, None, None, None, "{}", 1, now, "fixture", now, "fixture"))
        self.conn.commit()
        started = register.begin_assessment(self.conn, request_identifier="DREQ-SYN-1", item_identifier="ITEM-1", actor=self.token, expected_version=1, idempotency_key="link-start", reason="start")
        complete = register.complete_assessment(self.conn, request_identifier="DREQ-SYN-1", item_identifier="ITEM-1", basis="basis", evidence=[{"x":"y"}], limitations="limits", rule_identity="synthetic-rule-v1", authority_identity="synthetic-authority-v1", actor=self.token, expected_version=started["resulting_version"], idempotency_key="link-complete", reason="complete")
        linked = register.link_passive_workflow(self.conn, request_identifier="DREQ-SYN-1", item_identifier="ITEM-1", workflow_kind="stage81", target_identifier="CDE-DEF-SYN-1", target_revision=1, relationship_scope="synthetic item context", basis="bounded relationship judgment", limitations="synthetic limits", actor=self.token, expected_version=complete["resulting_version"], idempotency_key="link-good", reason="link")
        self.assertEqual(self.item()["workflow_links"][0]["state"], "current")
        self.conn.execute("UPDATE governed_defect_register_entries SET version=2 WHERE entry_identifier='CDE-DEF-SYN-1'"); self.conn.commit()
        self.assertEqual(self.item()["workflow_links"][0]["state"], "stale")
        with self.assertRaisesRegex(ValueError, "workflow_binding_unavailable"):
            register.link_passive_workflow(self.conn, request_identifier="DREQ-SYN-1", item_identifier="ITEM-1", workflow_kind="stage81", target_identifier="missing", target_revision=1, relationship_scope="scope", basis="basis", limitations="limits", actor=self.token, expected_version=linked["resulting_version"], idempotency_key="link-missing", reason="bad")

    def test_fixture_defined_review_must_bind_exact_outcome(self):
        self.conn.execute("INSERT INTO governed_disclosure_synthetic_authorities(rule_identity,authority_identity,approver_username,revision,requires_review,available) VALUES(?,?,?,?,?,?)", ("review-rule", "review-authority", "admin-a", 1, 1, 1)); self.conn.commit()
        started = register.begin_assessment(self.conn, request_identifier="DREQ-SYN-1", item_identifier="ITEM-1", actor=self.token, expected_version=1, idempotency_key="review-start", reason="start")
        complete = register.complete_assessment(self.conn, request_identifier="DREQ-SYN-1", item_identifier="ITEM-1", basis="basis", evidence=[{"x":"y"}], limitations="limits", rule_identity="review-rule", authority_identity="review-authority", actor=self.token, expected_version=started["resulting_version"], idempotency_key="review-complete", reason="complete")
        proposed = register.record_outcome(self.conn, request_identifier="DREQ-SYN-1", item_identifier="ITEM-1", outcome="decline", details={"reason":"synthetic"}, actor=self.token, expected_version=complete["resulting_version"], idempotency_key="review-outcome", reason="outcome")
        with self.assertRaisesRegex(ValueError, "required_review_unavailable"):
            register.approve_outcome(self.conn, request_identifier="DREQ-SYN-1", item_identifier="ITEM-1", outcome_revision=1, synthetic_rule_authority="review-authority", actor=self.token, expected_version=proposed["resulting_version"], idempotency_key="review-missing", reason="approve")
        outcome_id = self.conn.execute("SELECT id FROM governed_disclosure_outcomes").fetchone()[0]
        fixture = self.conn.execute("SELECT id,revision FROM governed_disclosure_synthetic_authorities WHERE rule_identity='review-rule'").fetchone()
        self.conn.execute("INSERT INTO governed_disclosure_synthetic_reviews(outcome_id,authority_fixture_id,authority_fixture_revision,reviewer_username,recorded_at) VALUES(?,?,?,?,?)", (outcome_id, fixture[0], fixture[1], "synthetic-review", "2026-10-18T00:00:00Z")); self.conn.commit()
        approved = register.approve_outcome(self.conn, request_identifier="DREQ-SYN-1", item_identifier="ITEM-1", outcome_revision=1, synthetic_rule_authority="review-authority", actor=self.token, expected_version=proposed["resulting_version"], idempotency_key="review-ok", reason="approve")
        self.assertEqual(approved["resulting_version"], proposed["resulting_version"] + 1)

    def test_required_stage81_relationship_blocks_stale_approval_and_closure_but_context_does_not(self):
        source = self.authoritative_stage81()
        started = register.begin_assessment(self.conn, request_identifier="DREQ-SYN-1", item_identifier="ITEM-1", actor=self.token, expected_version=1, idempotency_key="req-start", reason="start")
        complete = register.complete_assessment(self.conn, request_identifier="DREQ-SYN-1", item_identifier="ITEM-1", basis="basis", evidence=[{"x":"y"}], limitations="limits", rule_identity="synthetic-rule-v1", authority_identity="synthetic-authority-v1", actor=self.token, expected_version=started["resulting_version"], idempotency_key="req-complete", reason="complete")
        required = register.link_passive_workflow(self.conn, request_identifier="DREQ-SYN-1", item_identifier="ITEM-1", workflow_kind="stage81", target_identifier=source, target_revision=1, relationship_scope="decision depends on exact correction", basis="reasoned relationship judgment", limitations="synthetic limits", relationship_purpose="required", actor=self.token, expected_version=complete["resulting_version"], idempotency_key="req-link", reason="bind")
        relationship_id = self.conn.execute("SELECT id FROM governed_disclosure_workflow_links WHERE relationship_purpose='required'").fetchone()[0]
        proposed = register.record_outcome(self.conn, request_identifier="DREQ-SYN-1", item_identifier="ITEM-1", outcome="withhold", details={"why":"synthetic"}, required_relationship_ids=[relationship_id], actor=self.token, expected_version=required["resulting_version"], idempotency_key="req-outcome", reason="outcome")
        self.conn.execute("UPDATE governed_defect_register_entries SET version=2 WHERE entry_identifier=?", (source,)); self.conn.commit()
        before = self.conn.execute("SELECT count(*) FROM governed_disclosure_approvals").fetchone()[0]
        with self.assertRaisesRegex(ValueError, "approval_binding_mismatch"):
            register.approve_outcome(self.conn, request_identifier="DREQ-SYN-1", item_identifier="ITEM-1", outcome_revision=1, synthetic_rule_authority="synthetic-authority-v1", actor=self.token, expected_version=proposed["resulting_version"], idempotency_key="req-stale", reason="stale")
        self.assertEqual(self.conn.execute("SELECT count(*) FROM governed_disclosure_approvals").fetchone()[0], before)
        self.assertEqual(self.item()["items"][0]["applicability_state"], "not_evaluated")
        self.assertEqual(self.item()["workflow_links"][0]["state"], "stale")

        # A context-only link does not become a dependency merely because its
        # source later changes.  It remains visible but cannot silently affect
        # the separately approved decision.
        self.seed("DREQ-CONTEXT")
        start = register.begin_assessment(self.conn, request_identifier="DREQ-CONTEXT", item_identifier="ITEM-1", actor=self.token, expected_version=1, idempotency_key="ctx-start", reason="start")
        done = register.complete_assessment(self.conn, request_identifier="DREQ-CONTEXT", item_identifier="ITEM-1", basis="basis", evidence=[{"x":"y"}], limitations="limits", rule_identity="synthetic-rule-v1", authority_identity="synthetic-authority-v1", actor=self.token, expected_version=start["resulting_version"], idempotency_key="ctx-complete", reason="complete")
        context = register.link_passive_workflow(self.conn, request_identifier="DREQ-CONTEXT", item_identifier="ITEM-1", workflow_kind="stage81", target_identifier=source, target_revision=2, relationship_scope="context only", basis="context judgment", limitations="limits", actor=self.token, expected_version=done["resulting_version"], idempotency_key="ctx-link", reason="context")
        proposal = register.record_outcome(self.conn, request_identifier="DREQ-CONTEXT", item_identifier="ITEM-1", outcome="decline", details={"why":"synthetic"}, actor=self.token, expected_version=context["resulting_version"], idempotency_key="ctx-outcome", reason="outcome")
        approval = register.approve_outcome(self.conn, request_identifier="DREQ-CONTEXT", item_identifier="ITEM-1", outcome_revision=1, synthetic_rule_authority="synthetic-authority-v1", actor=self.token, expected_version=proposal["resulting_version"], idempotency_key="ctx-approve", reason="approve")
        self.conn.execute("UPDATE governed_defect_register_entries SET version=3 WHERE entry_identifier=?", (source,)); self.conn.commit()
        closed = register.close_request(self.conn, request_identifier="DREQ-CONTEXT", actor=self.token, expected_version=approval["resulting_version"], idempotency_key="ctx-close", reason="context not a dependency")
        self.assertEqual(closed["resulting_version"], approval["resulting_version"] + 1)

    def test_required_stage81_relationship_rechecks_after_approval_and_blocks_closure(self):
        source = self.authoritative_stage81("DREG-REL-CLOSE")
        started = register.begin_assessment(self.conn, request_identifier="DREQ-SYN-1", item_identifier="ITEM-1", actor=self.token, expected_version=1, idempotency_key="close-start", reason="start")
        complete = register.complete_assessment(self.conn, request_identifier="DREQ-SYN-1", item_identifier="ITEM-1", basis="basis", evidence=[{"x":"y"}], limitations="limits", rule_identity="synthetic-rule-v1", authority_identity="synthetic-authority-v1", actor=self.token, expected_version=started["resulting_version"], idempotency_key="close-complete", reason="complete")
        linked = register.link_passive_workflow(self.conn, request_identifier="DREQ-SYN-1", item_identifier="ITEM-1", workflow_kind="stage81", target_identifier=source, target_revision=1, relationship_scope="closure dependency", basis="reasoned relationship judgment", limitations="limits", relationship_purpose="required", actor=self.token, expected_version=complete["resulting_version"], idempotency_key="close-link", reason="bind")
        relation_id = self.conn.execute("SELECT id FROM governed_disclosure_workflow_links WHERE relationship_purpose='required'").fetchone()[0]
        proposed = register.record_outcome(self.conn, request_identifier="DREQ-SYN-1", item_identifier="ITEM-1", outcome="withhold", details={"why":"synthetic"}, required_relationship_ids=[relation_id], actor=self.token, expected_version=linked["resulting_version"], idempotency_key="close-outcome", reason="outcome")
        approved = register.approve_outcome(self.conn, request_identifier="DREQ-SYN-1", item_identifier="ITEM-1", outcome_revision=1, synthetic_rule_authority="synthetic-authority-v1", actor=self.token, expected_version=proposed["resulting_version"], idempotency_key="close-approve", reason="approve")
        self.conn.execute("UPDATE governed_defect_register_entries SET version=2 WHERE entry_identifier=?", (source,)); self.conn.commit()
        before = self.conn.execute("SELECT count(*) FROM governed_disclosure_history").fetchone()[0]
        with self.assertRaisesRegex(ValueError, "closure_incomplete"):
            register.close_request(self.conn, request_identifier="DREQ-SYN-1", actor=self.token, expected_version=approved["resulting_version"], idempotency_key="close-stale", reason="stale dependency")
        self.assertEqual(self.conn.execute("SELECT count(*) FROM governed_disclosure_history").fetchone()[0], before)
        viewed = self.item()
        self.assertEqual(viewed["summary"]["state"], "decision_pending")
        self.assertEqual(viewed["workflow_links"][0]["state"], "stale")

    def test_closed_request_requires_explicit_atomic_reopen_before_reassessment(self):
        source = self.authoritative_stage81("DREG-REOPEN")
        started = register.begin_assessment(self.conn, request_identifier="DREQ-SYN-1", item_identifier="ITEM-1", actor=self.token, expected_version=1, idempotency_key="reopen-start", reason="start")
        complete = register.complete_assessment(self.conn, request_identifier="DREQ-SYN-1", item_identifier="ITEM-1", basis="basis", evidence=[{"x":"y"}], limitations="limits", rule_identity="synthetic-rule-v1", authority_identity="synthetic-authority-v1", actor=self.token, expected_version=started["resulting_version"], idempotency_key="reopen-complete", reason="complete")
        linked = register.link_passive_workflow(self.conn, request_identifier="DREQ-SYN-1", item_identifier="ITEM-1", workflow_kind="stage81", target_identifier=source, target_revision=1, relationship_scope="required for closure", basis="relationship judgment", limitations="limits", relationship_purpose="required", actor=self.token, expected_version=complete["resulting_version"], idempotency_key="reopen-link", reason="link")
        relationship_id = self.conn.execute("SELECT id FROM governed_disclosure_workflow_links WHERE relationship_purpose='required'").fetchone()[0]
        proposed = register.record_outcome(self.conn, request_identifier="DREQ-SYN-1", item_identifier="ITEM-1", outcome="withhold", details={"why":"synthetic"}, required_relationship_ids=[relationship_id], actor=self.token, expected_version=linked["resulting_version"], idempotency_key="reopen-outcome", reason="outcome")
        approved = register.approve_outcome(self.conn, request_identifier="DREQ-SYN-1", item_identifier="ITEM-1", outcome_revision=1, synthetic_rule_authority="synthetic-authority-v1", actor=self.token, expected_version=proposed["resulting_version"], idempotency_key="reopen-approval", reason="approval")
        closed = register.close_request(self.conn, request_identifier="DREQ-SYN-1", actor=self.token, expected_version=approved["resulting_version"], idempotency_key="reopen-close", reason="close")
        self.conn.execute("UPDATE governed_defect_register_entries SET version=2 WHERE entry_identifier=?", (source,)); self.conn.commit()
        before = (self.conn.execute("SELECT count(*) FROM governed_disclosure_history").fetchone()[0], self.item()["procedural_state"], self.item()["items"][0]["assessment_state"])
        self.assertEqual(self.item()["summary"]["state"], "closed_reassessment_required")
        with self.assertRaisesRegex(ValueError, "reopening_required"):
            register.reassess(self.conn, request_identifier="DREQ-SYN-1", item_identifier="ITEM-1", actor=self.token, expected_version=closed["resulting_version"], idempotency_key="direct-reassess", reason="stale source")
        self.assertEqual((self.conn.execute("SELECT count(*) FROM governed_disclosure_history").fetchone()[0], self.item()["procedural_state"], self.item()["items"][0]["assessment_state"]), before)
        with self.assertRaisesRegex(ValueError, "version_conflict"):
            register.reopen_request(self.conn, request_identifier="DREQ-SYN-1", item_identifiers=["ITEM-1"], actor=self.token, expected_version=closed["resulting_version"] - 1, idempotency_key="stale-reopen", reason="reopen")
        reopened = register.reopen_request(self.conn, request_identifier="DREQ-SYN-1", item_identifiers=["ITEM-1"], actor=self.token, expected_version=closed["resulting_version"], idempotency_key="reopen", reason="reopen after stale dependency")
        replay = register.reopen_request(self.conn, request_identifier="DREQ-SYN-1", item_identifiers=["ITEM-1"], actor=self.token, expected_version=closed["resulting_version"], idempotency_key="reopen", reason="reopen after stale dependency")
        self.assertTrue(replay["historical_receipt"])
        view = self.item(); self.assertEqual(view["procedural_state"], "reopened")
        self.assertEqual(view["items"][0]["assessment_state"], "under_assessment")
        self.assertEqual(view["history"][-1]["event_type"], "reopened")
        self.assertEqual(reopened["resulting_version"], closed["resulting_version"] + 1)


if __name__ == "__main__": unittest.main()
