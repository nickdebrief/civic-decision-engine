import hashlib
import json
import sqlite3
import unittest

from api import governed_report_jobs as jobs
from api import governed_report_publication_reviews as reviews
from api import record_governed_reports as reports


DECLARATION = {"acknowledged": True, "human_recorded": True}


class Stage78EGovernedReportPublicationReviewTests(unittest.TestCase):
    QUALIFICATION_ID = 7
    QUALIFICATION_DIGEST = hashlib.sha256(b"stage78e-qualification").hexdigest()

    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        reports.ensure_report_tables(self.conn)
        jobs.ensure_job_tables(self.conn)
        self.conn.execute("INSERT INTO record_governed_reports (id,idempotency_key,schema_version,report_type,title,purpose,intended_audience,distribution_class,created_by,created_by_role,created_at,lifecycle_status,request_payload_json) VALUES (1,'report','v','x','title','purpose','admin','internal','creator','admin','now','generated','{}')")
        self.conn.execute("INSERT INTO record_governed_report_versions (id,report_id,version_number,canonical_record_reference,specification_schema_version,specification_json,specification_digest,requested_formats_json,publication_engine_version,rendering_profile,template_version,created_by,created_at,lifecycle_status) VALUES (2,1,1,'record','v','{}','spec','[\"docx\",\"pdf\"]','2.0.0','profile','template','creator','now','generated')")
        self.conn.execute("INSERT INTO stage77_report_jobs (id,report_id,report_version_id,specification_digest,requested_formats_json,rendering_profile,template_version,publication_engine_version,requesting_actor,governed_action,requested_at,state,attempt_count,max_attempts,next_eligible_at,idempotency_key,qualification_id,qualification_digest,schema_version) VALUES (3,1,2,'spec','[\"docx\",\"pdf\"]','profile','template','2.0.0','creator','generate','now','succeeded',1,1,'now','job',?,?, 'v')", (self.QUALIFICATION_ID, self.QUALIFICATION_DIGEST))
        for artifact_id, fmt, data in ((4, "docx", b"docx"), (5, "pdf", b"pdf")):
            self.conn.execute("INSERT INTO record_governed_report_artifacts (id,version_id,format,storage_reference,sha256,size_bytes,renderer_version,template_version,generated_at,validation_state,diagnostics_json,lifecycle_status,qualification_id,qualification_digest,governed_job_id,governed_attempt_count) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (artifact_id,2,fmt,"/registered/"+fmt,hashlib.sha256(data).hexdigest(),len(data),"renderer","template","now","valid","[]","current",self.QUALIFICATION_ID,self.QUALIFICATION_DIGEST,3,1))

    def tearDown(self):
        self.conn.close()

    def _open(self, key="open"):
        return reviews.open_review(self.conn, report_id=1, report_version_id=2, artifact_ids=[5,4], actor="reviewer", actor_role="admin", rationale="Review exact registered set.", declaration=DECLARATION, idempotency_key=key)

    def test_artifact_set_is_deterministic_version_bound_and_idempotent(self):
        first = self._open()
        second = self._open()
        self.assertEqual(first["id"], second["id"])
        expected = [{"id": 4, "format": "docx", "sha256": hashlib.sha256(b"docx").hexdigest(), "size_bytes": 4, "validation_state": "valid", "lifecycle_status": "current", "version_id": 2, "governed_job_id": 3, "governed_attempt_count": 1, "pdf_conversion_authority_digest": None, "qualification_id": self.QUALIFICATION_ID, "qualification_digest": self.QUALIFICATION_DIGEST}, {"id": 5, "format": "pdf", "sha256": hashlib.sha256(b"pdf").hexdigest(), "size_bytes": 3, "validation_state": "valid", "lifecycle_status": "current", "version_id": 2, "governed_job_id": 3, "governed_attempt_count": 1, "pdf_conversion_authority_digest": None, "qualification_id": self.QUALIFICATION_ID, "qualification_digest": self.QUALIFICATION_DIGEST}]
        self.assertEqual(first["artifact_set"], expected)
        self.assertEqual(first["artifact_set_digest"], hashlib.sha256(json.dumps(expected, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest())
        with self.assertRaisesRegex(ValueError, "incomplete"):
            reviews.open_review(self.conn, report_id=1, report_version_id=2, artifact_ids=[4], actor="reviewer", actor_role="admin", rationale="subset", declaration=DECLARATION, idempotency_key="subset")

    def test_assessment_and_eligibility_are_not_generation_or_publication(self):
        item = self._open()
        with self.assertRaisesRegex(ValueError, "prerequisite"):
            reviews.determine_eligibility(self.conn, review_id=item["id"], outcome="eligible", actor="decider", actor_role="admin", rationale="not yet", declaration=DECLARATION, idempotency_key="decision")
        item = reviews.record_privacy_redaction(self.conn, review_id=item["id"], status="cleared", actor="privacy", actor_role="admin", rationale="Cleared.", declaration=DECLARATION, idempotency_key="privacy")
        item = reviews.determine_eligibility(self.conn, review_id=item["id"], outcome="eligible", actor="decider", actor_role="admin", rationale="Eligible for future review.", declaration=DECLARATION, idempotency_key="decision")
        self.assertEqual(item["lifecycle_status"], "eligible")
        self.assertEqual(reviews.current_eligibility(self.conn, report_version_id=2, artifact_set_digest=item["artifact_set_digest"])["id"], item["id"])
        self.assertNotIn("published", {event["event_type"] for event in item["events"]})

    def test_cross_attempt_and_withdrawal_fail_closed_without_erasure(self):
        self.conn.execute("UPDATE record_governed_report_artifacts SET governed_attempt_count=2 WHERE id=5")
        with self.assertRaisesRegex(ValueError, "cross_attempt"):
            self._open()
        self.conn.execute("UPDATE record_governed_report_artifacts SET governed_attempt_count=1 WHERE id=5")
        item = self._open()
        withdrawn = reviews.withdraw_review(self.conn, review_id=item["id"], actor="reviewer", actor_role="admin", rationale="Withdrawn without changing report evidence.", declaration=DECLARATION, idempotency_key="withdraw")
        self.assertEqual(withdrawn["lifecycle_status"], "withdrawn")
        self.assertGreaterEqual(len(withdrawn["events"]), 2)
        with self.assertRaisesRegex(ValueError, "eligibility_absent"):
            reviews.current_eligibility(self.conn, report_version_id=2, artifact_set_digest=item["artifact_set_digest"])

    def test_open_review_requires_exact_succeeded_job_binding(self):
        for state in ("queued", "failed_terminal"):
            self.conn.execute("UPDATE stage77_report_jobs SET state=? WHERE id=3", (state,))
            with self.assertRaisesRegex(ValueError, "job_ineligible"):
                self._open("open-" + state)
        self.conn.execute("UPDATE stage77_report_jobs SET state='succeeded',report_id=9 WHERE id=3")
        with self.assertRaisesRegex(ValueError, "job_binding_invalid"):
            self._open("open-wrong-report")
        self.conn.execute("UPDATE stage77_report_jobs SET report_id=1,report_version_id=9 WHERE id=3")
        with self.assertRaisesRegex(ValueError, "job_binding_invalid"):
            self._open("open-wrong-version")
        self.conn.execute("UPDATE stage77_report_jobs SET report_version_id=2,attempt_count=2 WHERE id=3")
        with self.assertRaisesRegex(ValueError, "job_binding_invalid"):
            self._open("open-wrong-attempt")

    def test_open_review_rejects_missing_or_mismatched_qualification_authority(self):
        self.conn.execute("UPDATE stage77_report_jobs SET qualification_id=NULL WHERE id=3")
        with self.assertRaisesRegex(ValueError, "qualification"):
            self._open("open-null-job-qualification")
        self.conn.execute("UPDATE stage77_report_jobs SET qualification_id=? WHERE id=3", (self.QUALIFICATION_ID,))
        self.conn.execute("UPDATE record_governed_report_artifacts SET qualification_digest=NULL WHERE id=4")
        with self.assertRaisesRegex(ValueError, "qualification"):
            self._open("open-null-artifact-qualification")

    def test_current_eligibility_rebinds_every_frozen_artifact_field(self):
        item = self._open()
        reviews.record_privacy_redaction(self.conn, review_id=item["id"], status="cleared", actor="privacy", actor_role="admin", rationale="Cleared.", declaration=DECLARATION, idempotency_key="privacy-current")
        reviews.determine_eligibility(self.conn, review_id=item["id"], outcome="eligible", actor="decider", actor_role="admin", rationale="Eligible.", declaration=DECLARATION, idempotency_key="decision-current")
        self.assertEqual(reviews.current_eligibility(self.conn, report_version_id=2, artifact_set_digest=item["artifact_set_digest"])["id"], item["id"])
        changes = [
            ("DELETE FROM record_governed_report_artifacts WHERE id=5", ()),
            ("UPDATE record_governed_report_artifacts SET format='html' WHERE id=5", ()),
            ("UPDATE record_governed_report_artifacts SET sha256='changed' WHERE id=5", ()),
            ("UPDATE record_governed_report_artifacts SET size_bytes=99 WHERE id=5", ()),
            ("UPDATE record_governed_report_artifacts SET validation_state='invalid' WHERE id=5", ()),
            ("UPDATE record_governed_report_artifacts SET lifecycle_status='withdrawn' WHERE id=5", ()),
            ("UPDATE record_governed_report_artifacts SET governed_job_id=8 WHERE id=5", ()),
            ("UPDATE record_governed_report_artifacts SET governed_attempt_count=2 WHERE id=5", ()),
        ]
        for statement, params in changes:
            with self.subTest(statement=statement):
                snapshot = list(self.conn.iterdump())
                self.conn.execute(statement, params)
                with self.assertRaisesRegex(ValueError, "current_artifact_mismatch"):
                    reviews.current_eligibility(self.conn, report_version_id=2, artifact_set_digest=item["artifact_set_digest"])
                self.conn.close()
                self.conn = sqlite3.connect(":memory:")
                self.conn.row_factory = sqlite3.Row
                self.conn.executescript("\n".join(snapshot))


if __name__ == "__main__":
    unittest.main()
