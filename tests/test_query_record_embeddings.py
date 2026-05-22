import json
import sqlite3
import unittest

from api.semantic_search import ensure_embedding_tables
from scripts.backfill_record_embeddings import backfill_record_embeddings
from scripts.query_record_embeddings import query_record_embeddings


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
    ensure_embedding_tables(conn)
    return conn


def insert_record(
    conn,
    *,
    reference,
    finding,
    conditions=None,
    is_latest=1,
    source_narrative="",
    report_json=None,
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
                  '2026-05-21T10:05:00Z', ?, ?)
        """,
        (
            reference,
            json.dumps(conditions or ["Institutional Delay"]),
            finding,
            report_json if report_json is not None else "{}",
            f"hash-{reference}",
            is_latest,
            source_narrative,
        ),
    )


class FakeProvider:
    label = "fake:test-model"

    def __init__(self, vector):
        self.vector = vector
        self.inputs = []

    def embed(self, text):
        self.inputs.append(text)
        return self.vector


class QueryRecordEmbeddingsTests(unittest.TestCase):
    def test_query_returns_json_safe_semantic_results(self):
        conn = make_connection()
        provider = FakeProvider([1.0, 0.0])
        insert_record(
            conn,
            reference="Strike-LA-20260521-001",
            finding="Canonical finding.",
        )
        backfill_record_embeddings(conn, provider=provider)
        provider.inputs.clear()

        result = query_record_embeddings(conn, "canonical query", provider=provider)

        self.assertEqual(result["query"], "canonical query")
        self.assertEqual(result["mode"], "semantic")
        self.assertEqual(result["embedding_model"], "fake:test-model")
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["records"][0]["reference"], "Strike-LA-20260521-001")
        json.dumps(result)

    def test_query_matches_only_selected_embedding_model_label(self):
        conn = make_connection()
        insert_record(
            conn,
            reference="Strike-LA-20260521-002",
            finding="Canonical finding.",
        )
        backfill_record_embeddings(conn, provider=FakeProvider([1.0, 0.0]))

        other_provider = FakeProvider([1.0, 0.0])
        other_provider.label = "fake:other-model"
        result = query_record_embeddings(conn, "canonical query", provider=other_provider)

        self.assertEqual(result["total"], 0)
        self.assertEqual(result["records"], [])

    def test_query_excludes_private_and_raw_fields(self):
        conn = make_connection()
        provider = FakeProvider([1.0, 0.0])
        insert_record(
            conn,
            reference="Strike-LA-20260521-003",
            finding="Canonical finding.",
            source_narrative="private narrative only",
            report_json=json.dumps({"raw_input": "raw input only"}),
        )
        backfill_record_embeddings(conn, provider=provider)
        provider.inputs.clear()

        result = query_record_embeddings(conn, "canonical query", provider=provider)
        serialized = json.dumps(result)

        self.assertNotIn("private narrative only", serialized)
        self.assertNotIn("raw input only", serialized)
        self.assertNotIn("source_narrative", serialized)
        self.assertNotIn("report_json", serialized)

    def test_query_hybrid_is_opt_in(self):
        conn = make_connection()
        provider = FakeProvider([1.0, 0.0])
        insert_record(
            conn,
            reference="Strike-LA-20260521-004",
            finding="Canonical delay keyword.",
        )
        backfill_record_embeddings(conn, provider=provider)
        provider.inputs.clear()

        semantic = query_record_embeddings(conn, "delay keyword", provider=provider)
        hybrid = query_record_embeddings(
            conn,
            "delay keyword",
            provider=provider,
            hybrid=True,
            semantic_weight=0.5,
            keyword_weight=0.5,
        )

        self.assertEqual(semantic["mode"], "semantic")
        self.assertEqual(hybrid["mode"], "hybrid")
        self.assertIn("keyword_score", hybrid["records"][0])

    def test_empty_query_does_not_call_provider(self):
        conn = make_connection()
        provider = FakeProvider([1.0, 0.0])

        result = query_record_embeddings(conn, "   ", provider=provider)

        self.assertEqual(result["mode"], "empty")
        self.assertEqual(provider.inputs, [])


if __name__ == "__main__":
    unittest.main()
