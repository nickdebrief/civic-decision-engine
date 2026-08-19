import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from api import record_governed_procedural_time as pt


class Stage71ProceduralTimeTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("CREATE TABLE records (reference TEXT PRIMARY KEY, version TEXT, generated_at TEXT)")
        self.conn.execute("INSERT INTO records VALUES ('REC-71', '1', '2026-08-19T00:00:00Z')")

    def tearDown(self):
        self.conn.close()

    def source(self, role="notice_source"):
        return [{"source_type": "canonical_record", "source_id": "REC-71", "binding_role": role}]

    def subject(self):
        return [{"object_type": "canonical_record", "object_id": "REC-71", "relationship_role": "notice_concerns"}]

    def contract(self, kind="notice"):
        return {"epistemic_label": kind, "source_bound": True, "not_legal_effect": True}

    def make_notice(self, **overrides):
        values = dict(notice_category="notice_issued", title_label="Notice", notice_description="A notice as represented", issuing_label="Institution", issuing_capacity="Registrar", intended_recipient="Participant", issue_date_or_period="2026-08-01", dispatch_method="recorded method", procedural_subject="Proceeding REC-71", rationale="Preserve the record", qualification=pt.NOTICE_BOUNDARY, limitations=pt.LIMITATIONS_BOUNDARY, qualification_contract=self.contract(), declaration=None, bindings=self.source(), subject_links=self.subject(), actor="admin", actor_role="administrator", idempotency_key="notice-1")
        values.update(overrides)
        with patch.object(pt.inferences, "_source_binding", side_effect=lambda conn, item, **_: dict(item)):
            return pt.create_notice(self.conn, **values)

    def make_deadline(self, **overrides):
        values = dict(deadline_category="response_deadline", title_label="Response deadline", procedural_subject="Proceeding REC-71", trigger_event="Notice issued", trigger_date_or_period="2026-08-01", deadline_date_or_period="2026-08-15", date_precision="date", time_precision=None, time_zone="UTC", calculation_rule="source stated", counting_convention="calendar days", inclusivity="inclusive", conditions=None, affected_participant="Participant", rationale="Preserve the stated deadline", qualification=pt.DEADLINE_BOUNDARY, limitations=pt.LIMITATIONS_BOUNDARY, qualification_contract=self.contract("deadline"), bindings=[{"source_type":"canonical_record", "source_id":"REC-71", "binding_role":"deadline_source"}], subject_links=[{"object_type":"canonical_record", "object_id":"REC-71", "relationship_role":"deadline_applies_to"}], actor="admin", actor_role="administrator", idempotency_key="deadline-1")
        values.update(overrides)
        with patch.object(pt.inferences, "_source_binding", side_effect=lambda conn, item, **_: dict(item)):
            return pt.create_deadline(self.conn, **values)

    def test_notice_and_deadline_are_distinct_and_idempotent(self):
        notice = self.make_notice()
        self.assertEqual(pt.get_notice(self.conn, notice["id"])["record_kind"], "notice")
        self.assertEqual(self.make_notice()["id"], notice["id"])
        deadline = self.make_deadline()
        self.assertNotEqual((notice["record_kind"], notice["id"]), (deadline["record_kind"], deadline["id"]))
        self.assertEqual(self.make_deadline()["id"], deadline["id"])

    def test_closed_categories_subjects_sources_dates_and_declarations(self):
        with self.assertRaisesRegex(ValueError, "category_required"):
            self.make_notice(notice_category="")
        with self.assertRaisesRegex(ValueError, "category_invalid"):
            self.make_notice(notice_category="receipt_inferred")
        with self.assertRaisesRegex(ValueError, "primary_source"):
            self.make_notice(bindings=[{"source_type":"canonical_record", "source_id":"REC-71", "binding_role":"contextual_source"}])
        with self.assertRaisesRegex(ValueError, "date_invalid"):
            self.make_notice(issue_date_or_period="2026-99-99")
        with self.assertRaisesRegex(ValueError, "declaration_required"):
            self.make_notice(notice_category="notice_received_as_evidenced", bindings=self.source("receipt_source"), declaration={"acknowledged":False})
        with self.assertRaisesRegex(ValueError, "declaration_inapplicable"):
            self.make_notice(declaration={"acknowledged":True})

    def test_receipt_is_not_created_from_issue_and_subject_links_are_required(self):
        item = self.make_notice(notice_category="notice_received_as_evidenced", bindings=self.source("receipt_source"), declaration={"acknowledged":True, "category":"notice_received_as_evidenced"})
        self.assertEqual(item["notice_category"], "notice_received_as_evidenced")
        with self.assertRaisesRegex(ValueError, "subject_required"):
            self.make_notice(idempotency_key="notice-no-subject", subject_links=[])

    def test_deadline_extension_and_dispute_are_append_only_events(self):
        deadline = self.make_deadline()
        with patch.object(pt.inferences, "_source_binding", side_effect=lambda conn, item, **_: dict(item)):
            event = pt.record_event(self.conn, parent_kind="deadline", parent_id=deadline["id"], event_category="extension_requested", actor_label="Participant", actor_capacity="Applicant", represented_date_or_period="2026-08-10", represented_value="request", rationale="Preserve request", qualification=pt.DEADLINE_BOUNDARY, limitations=pt.LIMITATIONS_BOUNDARY, declaration=None, bindings=[{"source_type":"canonical_record", "source_id":"REC-71", "binding_role":"extension_request_source"}], actor="admin", actor_role="administrator", idempotency_key="event-1")
        self.assertEqual(event["event_category"], "extension_requested")
        self.assertEqual(pt.get_deadline(self.conn, deadline["id"])["deadline_date_or_period"], "2026-08-15")
        with self.assertRaisesRegex(ValueError, "declaration_required"):
            pt.record_event(self.conn, parent_kind="deadline", parent_id=deadline["id"], event_category="extension_granted", actor_label="Authority", actor_capacity="Office", represented_date_or_period="2026-08-10", represented_value="2026-08-20", rationale="Grant", qualification=pt.DEADLINE_BOUNDARY, limitations=pt.LIMITATIONS_BOUNDARY, declaration=None, bindings=[{"source_type":"canonical_record", "source_id":"REC-71", "binding_role":"extension_grant_source"}], actor="admin", actor_role="administrator")

    def test_deterministic_calculation_is_explicit_reproducible_and_not_lateness(self):
        deadline = self.make_deadline()
        result = pt.calculate_deadline(self.conn, deadline_id=deadline["id"], calculation_mode="calendar_days_after_explicit_trigger", trigger_input="2026-08-01", interval_days=14, inclusivity="inclusive", calculated_as_of="2026-08-15T12:00:00Z", time_zone="UTC", requested_by="admin", idempotency_key="calc-1")
        self.assertEqual(result["calculated_deadline"], "2026-08-15")
        self.assertEqual(result["result_category"], "deadline_reached_as_calculated")
        self.assertNotIn(result["result_category"], {"late", "out_of_time", "inadmissible", "defaulted"})
        self.assertEqual(pt.calculate_deadline(self.conn, deadline_id=deadline["id"], calculation_mode="calendar_days_after_explicit_trigger", trigger_input="2026-08-01", interval_days=14, inclusivity="inclusive", calculated_as_of="2026-08-15T12:00:00Z", time_zone="UTC", requested_by="admin", idempotency_key="calc-1")["id"], result["id"])
        with self.assertRaisesRegex(ValueError, "unsupported"):
            pt.calculate_deadline(self.conn, deadline_id=deadline["id"], calculation_mode="business_days", trigger_input="2026-08-01", interval_days=2, inclusivity="inclusive", calculated_as_of="2026-08-15T12:00:00Z", time_zone="UTC", requested_by="admin")

    def test_review_supersession_and_read_only_diagnostic(self):
        deadline = self.make_deadline()
        reviewed = pt.review_procedural_time(self.conn, target_kind="deadline", target_id=deadline["id"], disposition="accepted_as_source_bound_procedural_record", rationale="Preserve representation", boundary_declaration={"acknowledged":True}, actor="admin", actor_role="administrator", idempotency_key="review-1")
        self.assertEqual(reviewed["status"], "accepted_procedural_record")
        replacement = self.make_deadline(idempotency_key="deadline-2", title_label="Corrected deadline")
        self.assertEqual(pt.supersede_procedural_time(self.conn, target_kind="deadline", target_id=deadline["id"], replacement_kind="deadline", replacement_id=replacement["id"], rationale="Correction", actor="admin", actor_role="administrator", idempotency_key="sup-1")["status"], "superseded")
        with tempfile.NamedTemporaryFile(suffix=".db") as handle:
            diagnostic = pt.read_procedural_time_diagnostic(db_path=handle.name)
            self.assertFalse(diagnostic["notice_table_present"])
            self.assertFalse(diagnostic["deadline_table_present"])

    def test_admin_boundary_and_no_automation(self):
        source = Path("api/routes/admin_session.py").read_text(encoding="utf-8")
        self.assertEqual(source.count('href="/admin/governed-procedural-time"'), 1)
        self.assertIn('@router.get("/admin/governed-procedural-time"', source)
        self.assertIn("NOTICE ISSUED IS NOT NOTICE RECEIVED", source)
        self.assertIn("TIME CALCULATED IS NOT LATENESS DETERMINED", source)
        self.assertNotIn("deadline_monitor", source)
        self.assertNotIn("automatic_receipt", source)


if __name__ == "__main__":
    unittest.main()
