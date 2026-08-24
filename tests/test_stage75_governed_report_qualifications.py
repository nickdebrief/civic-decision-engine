import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from api import governed_report_qualifications as qualifications
from api import record_governed_reports as reports


class Stage75QualificationTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.root = tempfile.TemporaryDirectory()
        self.original_root = reports.REPORT_ROOT
        reports.REPORT_ROOT = Path(self.root.name)
        self.record = {"reference": "CR-1", "title": "Canonical record", "finding": "Original wording", "status": "recorded", "version": 1}

    def tearDown(self):
        reports.REPORT_ROOT = self.original_root
        self.connection.close()
        self.root.cleanup()

    def create(self, distribution_class="internal_working"):
        with patch.object(reports.rda, "record_context", return_value=self.record):
            return reports.create_report(
                self.connection,
                title="Internal report",
                purpose="Review selected record",
                audience="Administrators",
                distribution_class=distribution_class,
                canonical_record_reference="CR-1",
                document_ids=[],
                association_ids=[],
                sections=[{"title": "Record", "blocks": [{"content_type": "verbatim_source", "text": "Original wording", "source_identity": {"object_kind": "canonical_record", "object_id": "CR-1"}, "inclusion_rationale": "Deliberately selected."}]}],
                exclusions=[],
                requested_formats=["docx", "html"],
                rendering_profile="internal",
                template_version="cde-internal-v1",
                actor="nick",
                actor_role="administrator",
                idempotency_key="report-1",
            )

    def confirm_all(self, report_id):
        item = reports.get_report(self.connection, report_id)
        with patch.object(reports.rda, "record_context", return_value=self.record):
            for status, key in (("assembly_reviewed", "sole-assembly"), ("privacy_reviewed", "sole-privacy"), ("redaction_reviewed", "sole-redaction"), ("approved_for_generation", "sole-approval")):
                item = reports.confirm_creator_gate(
                    self.connection,
                    report_id=report_id,
                    resulting_status=status,
                    rationale=f"Deliberate {status} confirmation.",
                    actor="nick",
                    actor_role="administrator",
                    acknowledged=True,
                    idempotency_key=key,
                )
        return item

    def test_sole_path_requires_explicit_mode_and_preserves_frozen_version(self):
        with patch.dict(os.environ, {qualifications.REVIEW_MODE_ENV: qualifications.SOLE_MODE}):
            item = self.create()
            digest = item["versions"][0]["specification_digest"]
            with self.assertRaisesRegex(ValueError, "sole_confirmation_required"):
                reports.transition_report(self.connection, report_id=item["id"], resulting_status="assembly_reviewed", rationale="self", actor="nick", actor_role="administrator", declaration={"acknowledged": True}, idempotency_key="independent-self")
            item = self.confirm_all(item["id"])
            self.assertEqual(item["lifecycle_status"], "approved_for_generation")
            self.assertEqual(item["versions"][0]["specification_digest"], digest)
            rows = self.connection.execute("SELECT completed_gate,review_mode,disclosure_version,distribution_restriction FROM record_governed_report_qualifications ORDER BY revision_number").fetchall()
            self.assertEqual([row[0] for row in rows], list(qualifications.GATES))
            self.assertEqual({row[1] for row in rows}, {qualifications.SOLE_MODE})
            self.assertEqual({row[2] for row in rows}, {qualifications.DISCLOSURE_VERSION})
            self.assertEqual({row[3] for row in rows}, {"internal_working"})
            events = [row[0] for row in self.connection.execute("SELECT event_type FROM record_governed_report_events WHERE event_type LIKE 'creator_%' ORDER BY id")]
            self.assertEqual(events, list(qualifications.SOLE_EVENTS.values()))

    def test_invalid_mode_fails_closed_and_non_internal_distribution_is_rejected(self):
        for value in ("", " unknown", "sole_administrator "):
            with patch.dict(os.environ, {qualifications.REVIEW_MODE_ENV: value}):
                with self.assertRaisesRegex(ValueError, "review_mode_invalid"):
                    qualifications.configured_review_mode()
        with patch.dict(os.environ, {qualifications.REVIEW_MODE_ENV: qualifications.SOLE_MODE}):
            item = self.create(distribution_class="restricted_review")
            with patch.object(reports.rda, "record_context", return_value=self.record):
                with self.assertRaisesRegex(ValueError, "sole_distribution_invalid"):
                    reports.confirm_creator_gate(self.connection, report_id=item["id"], resulting_status="assembly_reviewed", rationale="Not allowed", actor="nick", actor_role="administrator", acknowledged=True, idempotency_key="restricted")
            self.assertEqual(reports.get_report(self.connection, item["id"])["lifecycle_status"], "draft_specification")

    def test_qualification_replay_and_conflicting_replay_are_bounded(self):
        with patch.dict(os.environ, {qualifications.REVIEW_MODE_ENV: qualifications.SOLE_MODE}):
            item = self.create()
            with patch.object(reports.rda, "record_context", return_value=self.record):
                first = reports.confirm_creator_gate(self.connection, report_id=item["id"], resulting_status="assembly_reviewed", rationale="First confirmation", actor="nick", actor_role="administrator", acknowledged=True, idempotency_key="same")
                replay = reports.confirm_creator_gate(self.connection, report_id=item["id"], resulting_status="assembly_reviewed", rationale="First confirmation", actor="nick", actor_role="administrator", acknowledged=True, idempotency_key="same")
                with self.assertRaisesRegex(ValueError, "idempotency_conflict"):
                    reports.confirm_creator_gate(self.connection, report_id=item["id"], resulting_status="assembly_reviewed", rationale="Changed", actor="nick", actor_role="administrator", acknowledged=True, idempotency_key="same")
            self.assertEqual(replay["lifecycle_status"], first["lifecycle_status"])
            self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM record_governed_report_qualifications").fetchone()[0], 1)

    def test_qualification_digest_tampering_fails_closed(self):
        with patch.dict(os.environ, {qualifications.REVIEW_MODE_ENV: qualifications.SOLE_MODE}):
            item = self.confirm_all(self.create()["id"])
            self.connection.execute("UPDATE record_governed_report_qualifications SET qualification_payload_json=? WHERE completed_gate='approval'", (json.dumps({"tampered": True}),))
            self.connection.commit()
            with self.assertRaisesRegex(ValueError, "qualification_digest_mismatch"):
                qualifications.latest_final(self.connection, item["id"])

    def test_independent_mode_creates_structured_qualification_without_disclosure(self):
        item = self.create()
        for status, actor, key in (("assembly_reviewed", "reviewer", "ind-assembly"), ("privacy_reviewed", "reviewer", "ind-privacy"), ("redaction_reviewed", "reviewer", "ind-redaction"), ("approved_for_generation", "reviewer", "ind-approval")):
            item = reports.transition_report(self.connection, report_id=item["id"], resulting_status=status, rationale="Independent gate", actor=actor, actor_role="administrator", declaration={"acknowledged": True}, idempotency_key=key)
        row = self.connection.execute("SELECT review_mode,disclosure_version FROM record_governed_report_qualifications WHERE completed_gate='approval'").fetchone()
        self.assertEqual(tuple(row), (qualifications.INDEPENDENT_MODE, "none"))
        self.assertEqual(item["versions"][0]["specification_digest"], reports.specification_digest(item["versions"][0]["specification"]))


if __name__ == "__main__":
    unittest.main()
