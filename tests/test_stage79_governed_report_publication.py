import hashlib
import sqlite3
import unittest

from api import governed_report_jobs as jobs
from api import governed_report_publication_reviews as reviews
from api import governed_report_publications as publications
from api import record_governed_reports as reports


class Stage79GovernedReportPublicationTests(unittest.TestCase):
    QUALIFICATION_ID = 7
    QUALIFICATION_DIGEST = "a" * 64

    def setUp(self):
        self.conn = sqlite3.connect(":memory:"); self.conn.row_factory = sqlite3.Row
        reports.ensure_report_tables(self.conn); jobs.ensure_job_tables(self.conn)
        self.conn.execute("INSERT INTO record_governed_reports (id,idempotency_key,schema_version,report_type,title,purpose,intended_audience,distribution_class,created_by,created_by_role,created_at,lifecycle_status,request_payload_json) VALUES (1,'r','v','x','title','purpose','admin','internal','a','admin','now','generated','{}')")
        self.conn.execute("INSERT INTO record_governed_report_versions (id,report_id,version_number,canonical_record_reference,specification_schema_version,specification_json,specification_digest,requested_formats_json,publication_engine_version,rendering_profile,template_version,created_by,created_at,lifecycle_status) VALUES (2,1,1,'r','v','{}','spec','[\"docx\",\"pdf\"]','v','p','t','a','now','generated')")
        self.conn.execute("INSERT INTO stage77_report_jobs (id,report_id,report_version_id,specification_digest,requested_formats_json,rendering_profile,template_version,publication_engine_version,requesting_actor,governed_action,requested_at,state,attempt_count,max_attempts,next_eligible_at,idempotency_key,qualification_id,qualification_digest,schema_version) VALUES (3,1,2,'spec','[\"docx\",\"pdf\"]','p','t','v','a','generate','now','succeeded',1,1,'now','j',?,?, 'v')", (self.QUALIFICATION_ID, self.QUALIFICATION_DIGEST))
        for ident, fmt, raw in ((4,'docx',b'docx'),(5,'pdf',b'pdf')):
            self.conn.execute("INSERT INTO record_governed_report_artifacts (id,version_id,format,storage_reference,sha256,size_bytes,renderer_version,template_version,generated_at,validation_state,diagnostics_json,lifecycle_status,qualification_id,qualification_digest,governed_job_id,governed_attempt_count) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (ident,2,fmt,'private',hashlib.sha256(raw).hexdigest(),len(raw),'r','t','now','valid','[]','current',self.QUALIFICATION_ID,self.QUALIFICATION_DIGEST,3,1))
        review=reviews.open_review(self.conn,report_id=1,report_version_id=2,artifact_ids=[4,5],actor='reviewer',actor_role='admin',rationale='review',declaration={'acknowledged':True},idempotency_key='open')
        reviews.record_privacy_redaction(self.conn,review_id=review['id'],status='cleared',actor='privacy',actor_role='admin',rationale='clear',declaration={'acknowledged':True},idempotency_key='privacy')
        reviews.determine_eligibility(self.conn,review_id=review['id'],outcome='eligible',actor='decider',actor_role='admin',rationale='eligible',declaration={'acknowledged':True},idempotency_key='eligible')
        self.conn.commit()

    def tearDown(self): self.conn.close()
    def payload(self): return {'title':'Public title','summary':'Bounded public summary','language':'en','limitations':'Bounded limitations','epistemic_classification':'governed representation'}
    def publish(self,key='publish'):
        return publications.publish(self.conn,report_id=1,report_version_id=2,representation=self.payload(),actor='publisher',actor_role='admin',rationale='deliberate publication',declaration={'acknowledged':True,'boundary':publications.PUBLICATION_DECLARATION},idempotency_key=key)

    def test_current_eligible_snapshot_is_deterministic_and_public(self):
        item=self.publish(); public=publications.public_publication(self.conn,item['public_identifier'])
        self.assertEqual(public['publication_id'],item['id']); self.assertEqual(publications.digest(public),item['snapshot_digest'])
        self.assertEqual(public["qualification_authority"], {"id": self.QUALIFICATION_ID, "digest": self.QUALIFICATION_DIGEST})
        altered = dict(public); altered["qualification_authority"] = {"id": self.QUALIFICATION_ID, "digest": "b" * 64}
        self.assertNotEqual(publications.digest(altered), item["snapshot_digest"])
        self.assertNotIn('storage_reference', str(public)); self.assertNotIn('diagnostics', str(public))

    def test_missing_or_drifted_eligibility_fails_closed(self):
        self.conn.execute("UPDATE record_governed_report_artifacts SET sha256='changed' WHERE id=5")
        with self.assertRaisesRegex(ValueError,'eligibility_absent'): self.publish()

    def test_missing_null_malformed_or_mixed_qualification_fails_before_persistence(self):
        cases = (
            ("missing-id", "UPDATE record_governed_report_artifacts SET qualification_id=NULL WHERE id=4"),
            ("missing-digest", "UPDATE record_governed_report_artifacts SET qualification_digest=NULL WHERE id=4"),
            ("malformed-digest", "UPDATE record_governed_report_artifacts SET qualification_digest='not-a-digest' WHERE id=4"),
            ("mixed", "UPDATE record_governed_report_artifacts SET qualification_id=8 WHERE id=4"),
            ("job-mismatch", "UPDATE stage77_report_jobs SET qualification_digest='b' || substr(qualification_digest,2) WHERE id=3"),
        )
        for key, mutation in cases:
            with self.subTest(key=key):
                self.conn.execute(mutation)
                with self.assertRaisesRegex(ValueError, "eligibility_absent"):
                    self.publish(key)
                self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM record_governed_report_publications").fetchone()[0], 0)
                self.conn.rollback()

    def test_caller_cannot_supply_or_substitute_qualification_authority(self):
        self.conn.execute("UPDATE record_governed_report_artifacts SET qualification_id=NULL WHERE id=4")
        payload = self.payload(); payload["qualification_authority"] = {"id": self.QUALIFICATION_ID, "digest": self.QUALIFICATION_DIGEST}
        with self.assertRaisesRegex(ValueError, "representation_invalid"):
            publications.publish(self.conn, report_id=1, report_version_id=2, representation=payload, actor="publisher", actor_role="admin", rationale="deliberate publication", declaration={"acknowledged": True, "boundary": publications.PUBLICATION_DECLARATION}, idempotency_key="substitution")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM record_governed_report_publications").fetchone()[0], 0)

    def test_declaration_idempotency_conflict_withdrawal_and_tombstone(self):
        with self.assertRaisesRegex(ValueError,'declaration'): publications.publish(self.conn,report_id=1,report_version_id=2,representation=self.payload(),actor='a',actor_role='admin',rationale='x',declaration={},idempotency_key='bad')
        item=self.publish(); self.assertEqual(self.publish()['id'],item['id'])
        with self.assertRaisesRegex(ValueError,'conflict'):
            changed=self.payload(); changed['summary']='different'; publications.publish(self.conn,report_id=1,report_version_id=2,representation=changed,actor='publisher',actor_role='admin',rationale='deliberate publication',declaration={'acknowledged':True,'boundary':publications.PUBLICATION_DECLARATION},idempotency_key='publish')
        publications.withdraw(self.conn,item['id'],actor='publisher',actor_role='admin',rationale='withdraw',declaration={'acknowledged':True,'boundary':publications.PUBLICATION_DECLARATION},idempotency_key='withdraw'); self.conn.commit()
        self.assertTrue(publications.public_publication(self.conn,item['public_identifier'])['tombstone'])

if __name__ == '__main__': unittest.main()
