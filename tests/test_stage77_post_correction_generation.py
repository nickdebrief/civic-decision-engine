import sqlite3
import unittest

from api import governed_report_jobs as jobs
from api import governed_report_recovery as recovery


class PostCorrectionGenerationContractTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(
            """
            CREATE TABLE record_governed_reports (id INTEGER PRIMARY KEY, lifecycle_status TEXT);
            CREATE TABLE record_governed_report_versions (id INTEGER PRIMARY KEY, report_id INTEGER);
            """
        )
        jobs.ensure_job_tables(self.conn)
        jobs.ensure_post_correction_tables(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_authorization_tables_and_one_to_one_indexes_exist(self):
        tables = {row[0] for row in self.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertIn("stage77_post_correction_authorizations", tables)
        self.assertIn("stage77_post_correction_execution_links", tables)
        indexes = {row[1] for row in self.conn.execute("PRAGMA index_list(stage77_report_jobs)")}
        self.assertIn("idx_stage77_jobs_post_correction_authorization", indexes)

    def test_exact_post_correction_schema_selects_new_contract_with_zero_rows(self):
        contract, _evidence, _evidence_digest, _links, _links_digest = recovery._database_contract(self.conn)
        self.assertEqual(contract, "post_correction_aware")

    def test_partial_post_correction_schema_fails_closed(self):
        self.conn.execute("DROP TABLE stage77_post_correction_execution_links")
        with self.assertRaisesRegex(ValueError, "post_correction_schema_incompatible"):
            recovery._database_contract(self.conn)

    def test_generic_retry_rejects_a_retry_predecessor(self):
        self.conn.execute("INSERT INTO record_governed_reports VALUES(1,'validation_failed')")
        self.conn.execute("INSERT INTO record_governed_report_versions VALUES(1,1)")
        self.conn.execute(
            "INSERT INTO stage77_report_jobs(report_id,report_version_id,specification_digest,requested_formats_json,rendering_profile,template_version,publication_engine_version,requesting_actor,governed_action,requested_at,state,attempt_count,max_attempts,next_eligible_at,idempotency_key,retry_of_job_id,schema_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (1, 1, "a" * 64, "[]", "internal", "cde-internal-v1", "2.0.0", "nick", jobs.DIAGNOSTIC_RETRY_ACTION, jobs.utc_now(), "failed_terminal", 1, 3, jobs.utc_now(), "job-2", 1, jobs.JOB_SCHEMA_VERSION),
        )
        self.conn.commit()
        with self.assertRaisesRegex(ValueError, "retry_of_retry_forbidden"):
            jobs.retry_job(self.conn, 1, "nick")

    def test_post_correction_action_is_not_a_retry(self):
        self.assertNotEqual(jobs.POST_CORRECTION_ACTION, jobs.DIAGNOSTIC_RETRY_ACTION)
        self.assertEqual(jobs.POST_CORRECTION_ACTION.find("retry"), -1)


if __name__ == "__main__":
    unittest.main()
