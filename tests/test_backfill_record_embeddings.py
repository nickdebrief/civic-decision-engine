import json
import os
import sqlite3
import unittest
from unittest.mock import patch

from api.record_indexing import indexed_fields_hash
from api.semantic_search import INDEX_POLICY_VERSION
from scripts.backfill_record_embeddings import (
    LOCAL_TEST_EMBEDDING_MODEL,
    backfill_record_embeddings,
    build_embedding_provider,
    deterministic_local_embedding,
)


def make_connection():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE records (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            reference         TEXT NOT NULL,
            version           INTEGER NOT NULL DEFAULT 1,
            supersedes        TEXT,
            generated_at      TEXT NOT NULL,
            trajectory        TEXT,
            system_state      TEXT,
            conditions_json   TEXT,
            signals_json      TEXT,
            finding           TEXT,
            report_json       TEXT,
            language          TEXT NOT NULL DEFAULT 'en',
            generated_by      TEXT NOT NULL DEFAULT 'Civic Decision Engine',
            verification_hash TEXT NOT NULL,
            exported_at       TEXT NOT NULL,
            is_latest         INTEGER NOT NULL DEFAULT 1,
            source_narrative  TEXT
        )
        """
    )
    return conn


def insert_record(
    conn,
    *,
    reference,
    finding,
    conditions,
    is_latest=1,
    source_narrative="",
    report_json=None,
    exported_at="2026-05-21T10:05:00Z",
):
    conn.execute(
        """
        INSERT INTO records (
            reference, version, supersedes, generated_at,
            trajectory, system_state, conditions_json,
            signals_json, finding, report_json, language,
            generated_by, verification_hash, exported_at, is_latest,
            source_narrative
        ) VALUES (?, 1, NULL, '2026-05-21T10:00:00Z',
                  'Deteriorating', 'Transition to Escalation', ?,
                  '[]', ?, ?, 'en', 'Civic Decision Engine', ?,
                  ?, ?, ?)
        """,
        (
            reference,
            json.dumps(conditions),
            finding,
            report_json if report_json is not None else "{}",
            f"hash-{reference}",
            exported_at,
            is_latest,
            source_narrative,
        ),
    )


class BackfillRecordEmbeddingsTests(unittest.TestCase):
    def test_deterministic_local_embedding_is_stable(self):
        first = deterministic_local_embedding("same text")
        second = deterministic_local_embedding("same text")

        self.assertEqual(first, second)
        self.assertEqual(len(first), 16)

    def test_backfill_inserts_latest_records_only(self):
        conn = make_connection()
        insert_record(
            conn,
            reference="Strike-LA-20260521-001",
            finding="Latest canonical finding.",
            conditions=["Institutional Delay"],
            is_latest=1,
        )
        insert_record(
            conn,
            reference="Strike-LA-20260521-002",
            finding="Superseded canonical finding.",
            conditions=["Transfer of Burden"],
            is_latest=0,
        )

        result = backfill_record_embeddings(conn)
        rows = conn.execute("SELECT * FROM record_embeddings").fetchall()

        self.assertEqual(result["selected"], 1)
        self.assertEqual(result["inserted"], 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["reference"], "Strike-LA-20260521-001")

    def test_backfill_is_idempotent(self):
        conn = make_connection()
        insert_record(
            conn,
            reference="Strike-LA-20260521-003",
            finding="Canonical finding.",
            conditions=["Institutional Delay"],
        )

        first = backfill_record_embeddings(conn)
        second = backfill_record_embeddings(conn)
        count = conn.execute("SELECT COUNT(*) FROM record_embeddings").fetchone()[0]

        self.assertEqual(first["inserted"], 1)
        self.assertEqual(second["inserted"], 0)
        self.assertEqual(second["skipped"], 1)
        self.assertEqual(count, 1)

    def test_dry_run_does_not_insert_rows(self):
        conn = make_connection()
        insert_record(
            conn,
            reference="Strike-LA-20260521-004",
            finding="Canonical finding.",
            conditions=["Institutional Delay"],
        )

        result = backfill_record_embeddings(conn, dry_run=True)
        count = conn.execute("SELECT COUNT(*) FROM record_embeddings").fetchone()[0]

        self.assertTrue(result["dry_run"])
        self.assertEqual(result["planned"], 1)
        self.assertEqual(result["inserted"], 0)
        self.assertEqual(count, 0)

    def test_limit_controls_number_of_latest_records_processed(self):
        conn = make_connection()
        insert_record(
            conn,
            reference="Strike-LA-20260521-005",
            finding="First canonical finding.",
            conditions=["Institutional Delay"],
            exported_at="2026-05-21T10:00:00Z",
        )
        insert_record(
            conn,
            reference="Strike-LA-20260521-006",
            finding="Second canonical finding.",
            conditions=["Transfer of Burden"],
            exported_at="2026-05-21T10:01:00Z",
        )

        result = backfill_record_embeddings(conn, limit=1)
        rows = conn.execute("SELECT * FROM record_embeddings").fetchall()

        self.assertEqual(result["selected"], 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["reference"], "Strike-LA-20260521-005")

    def test_backfill_stores_expected_model_and_content_hash(self):
        conn = make_connection()
        insert_record(
            conn,
            reference="Strike-LA-20260521-007",
            finding="Canonical finding.",
            conditions=["Institutional Delay"],
        )

        backfill_record_embeddings(conn)
        record = conn.execute("SELECT * FROM records WHERE is_latest = 1").fetchone()
        embedding = conn.execute("SELECT * FROM record_embeddings").fetchone()

        self.assertEqual(
            embedding["embedding_model"], f"local:{LOCAL_TEST_EMBEDDING_MODEL}"
        )
        self.assertEqual(embedding["content_hash"], indexed_fields_hash(record))
        self.assertEqual(embedding["derived_from_hash"], indexed_fields_hash(record))
        self.assertEqual(embedding["index_policy_version"], INDEX_POLICY_VERSION)
        self.assertEqual(embedding["embedding_dimensions"], 16)
        self.assertEqual(embedding["provider_kind"], "local")

    def test_backfill_excludes_source_narrative_report_json_and_raw_input(self):
        conn = make_connection()
        insert_record(
            conn,
            reference="Strike-LA-20260521-008",
            finding="Canonical finding.",
            conditions=["Institutional Delay"],
            source_narrative="private narrative only",
            report_json=json.dumps({"raw_input": "raw input only"}),
        )

        backfill_record_embeddings(conn)
        embedding = conn.execute("SELECT * FROM record_embeddings").fetchone()
        indexed_fields = embedding["indexed_fields_json"]

        self.assertIn("Canonical finding", indexed_fields)
        self.assertNotIn("source_narrative", indexed_fields)
        self.assertNotIn("report_json", indexed_fields)
        self.assertNotIn("raw_input", indexed_fields)
        self.assertNotIn("private narrative only", indexed_fields)
        self.assertNotIn("raw input only", indexed_fields)

    def test_semantic_content_hash_ignores_excluded_field_changes(self):
        conn = make_connection()
        insert_record(
            conn,
            reference="Strike-LA-20260521-014",
            finding="Canonical finding.",
            conditions=["Institutional Delay"],
            source_narrative="first private narrative",
            report_json=json.dumps({"raw_input": "first raw input"}),
        )
        before = conn.execute("SELECT * FROM records WHERE is_latest = 1").fetchone()
        before_hash = indexed_fields_hash(before)

        conn.execute(
            """
            UPDATE records
            SET source_narrative = ?, report_json = ?
            WHERE reference = ?
            """,
            (
                "second private narrative",
                json.dumps({"raw_input": "second raw input"}),
                "Strike-LA-20260521-014",
            ),
        )
        after = conn.execute("SELECT * FROM records WHERE is_latest = 1").fetchone()
        after_hash = indexed_fields_hash(after)

        backfill_record_embeddings(conn)
        embedding = conn.execute("SELECT * FROM record_embeddings").fetchone()

        self.assertEqual(before_hash, after_hash)
        self.assertEqual(embedding["content_hash"], before_hash)
        self.assertEqual(embedding["derived_from_hash"], before_hash)

    def test_embedding_json_is_local_deterministic_vector(self):
        conn = make_connection()
        insert_record(
            conn,
            reference="Strike-LA-20260521-009",
            finding="Canonical finding.",
            conditions=["Institutional Delay"],
        )

        backfill_record_embeddings(conn)
        embedding = conn.execute("SELECT * FROM record_embeddings").fetchone()
        vector = json.loads(embedding["embedding_json"])

        self.assertEqual(len(vector), 16)
        self.assertTrue(all(isinstance(value, float) for value in vector))

    def test_fake_provider_is_called_for_latest_records_only(self):
        class FakeProvider:
            label = "fake:test-model"

            def __init__(self):
                self.inputs = []

            def embed(self, text):
                self.inputs.append(text)
                return [0.1, 0.2, 0.3]

        conn = make_connection()
        provider = FakeProvider()
        insert_record(
            conn,
            reference="Strike-LA-20260521-010",
            finding="Latest canonical finding.",
            conditions=["Institutional Delay"],
            is_latest=1,
        )
        insert_record(
            conn,
            reference="Strike-LA-20260521-011",
            finding="Superseded canonical finding.",
            conditions=["Transfer of Burden"],
            is_latest=0,
        )

        result = backfill_record_embeddings(conn, provider=provider)
        embedding = conn.execute("SELECT * FROM record_embeddings").fetchone()

        self.assertEqual(result["inserted"], 1)
        self.assertEqual(provider.inputs, [provider.inputs[0]])
        self.assertEqual(len(provider.inputs), 1)
        self.assertIn("Latest canonical finding.", provider.inputs[0])
        self.assertNotIn("Superseded canonical finding.", provider.inputs[0])
        self.assertEqual(embedding["embedding_model"], "fake:test-model")
        self.assertEqual(json.loads(embedding["embedding_json"]), [0.1, 0.2, 0.3])

    def test_fake_provider_never_receives_excluded_fields(self):
        class FakeProvider:
            label = "fake:test-model"

            def __init__(self):
                self.inputs = []

            def embed(self, text):
                self.inputs.append(text)
                return [0.1, 0.2, 0.3]

        conn = make_connection()
        provider = FakeProvider()
        insert_record(
            conn,
            reference="Strike-LA-20260521-012",
            finding="Canonical finding.",
            conditions=["Institutional Delay"],
            source_narrative="private narrative only",
            report_json=json.dumps({"raw_input": "raw input only"}),
        )

        backfill_record_embeddings(conn, provider=provider)

        self.assertEqual(len(provider.inputs), 1)
        self.assertIn("Canonical finding.", provider.inputs[0])
        self.assertNotIn("private narrative only", provider.inputs[0])
        self.assertNotIn("raw input only", provider.inputs[0])

    def test_dry_run_does_not_call_provider(self):
        class ExplodingProvider:
            label = "fake:explode"

            def embed(self, text):
                raise AssertionError("provider should not be called during dry-run")

        conn = make_connection()
        insert_record(
            conn,
            reference="Strike-LA-20260521-013",
            finding="Canonical finding.",
            conditions=["Institutional Delay"],
        )

        result = backfill_record_embeddings(
            conn, dry_run=True, provider=ExplodingProvider()
        )
        count = conn.execute("SELECT COUNT(*) FROM record_embeddings").fetchone()[0]

        self.assertEqual(result["planned"], 1)
        self.assertEqual(result["inserted"], 0)
        self.assertEqual(count, 0)

    def test_remote_provider_requires_api_key_only_when_not_dry_run(self):
        env = {
            key: value
            for key, value in os.environ.items()
            if key not in {"REMOTE_EMBEDDING_API_KEY", "REMOTE_EMBEDDING_CLIENT"}
        }
        with patch.dict(os.environ, env, clear=True):
            dry_run_provider = build_embedding_provider("remote", dry_run=True)
            self.assertEqual(dry_run_provider.label, "remote:remote-embedding-model")

            with self.assertRaises(RuntimeError) as ctx:
                build_embedding_provider("remote", dry_run=False)

        self.assertIn("REMOTE_EMBEDDING_API_KEY", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
