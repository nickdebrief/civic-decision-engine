import json
import sqlite3
import unittest

from api.semantic_search import (
    ensure_embedding_tables,
    hybrid_retrieve_records,
    semantic_retrieve_records,
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
    ensure_embedding_tables(conn)
    return conn


def insert_record(
    conn,
    *,
    reference,
    finding,
    conditions=None,
    embedding=None,
    embedding_model="local:test-model",
    is_latest=1,
    trajectory="Deteriorating",
    system_state="Transition to Escalation",
    source_narrative="private narrative only",
    report_json=None,
    exported_at="2026-05-21T10:05:00Z",
):
    cur = conn.execute(
        """
        INSERT INTO records (
            reference, version, supersedes, generated_at,
            trajectory, system_state, conditions_json,
            signals_json, finding, report_json, language,
            generated_by, verification_hash, exported_at, is_latest,
            source_narrative
        ) VALUES (?, 1, NULL, '2026-05-21T10:00:00Z',
                  ?, ?, ?, '[]', ?, ?, 'en',
                  'Civic Decision Engine', ?, ?, ?, ?)
        """,
        (
            reference,
            trajectory,
            system_state,
            json.dumps(conditions or ["Institutional Delay"]),
            finding,
            report_json if report_json is not None else json.dumps({"raw_input": "raw input only"}),
            f"hash-{reference}",
            exported_at,
            is_latest,
            source_narrative,
        ),
    )
    record_id = cur.lastrowid
    if embedding is not None:
        conn.execute(
            """
            INSERT INTO record_embeddings (
                record_id, reference, version, content_hash,
                embedding_model, embedding_json, indexed_fields_json
            ) VALUES (?, ?, 1, ?, ?, ?, ?)
            """,
            (
                record_id,
                reference,
                f"hash-{reference}",
                embedding_model,
                json.dumps(embedding),
                json.dumps({"reference": reference, "finding": finding}),
            ),
        )
    return record_id


class SemanticRetrievalTests(unittest.TestCase):
    def test_semantic_retrieval_returns_ranked_latest_records(self):
        conn = make_connection()
        insert_record(
            conn,
            reference="Strike-LA-20260521-001",
            finding="Near match.",
            embedding=[1.0, 0.0],
            exported_at="2026-05-21T10:00:00Z",
        )
        insert_record(
            conn,
            reference="Strike-LA-20260521-002",
            finding="Far match.",
            embedding=[0.0, 1.0],
            exported_at="2026-05-21T10:01:00Z",
        )

        result = semantic_retrieve_records(
            conn,
            [1.0, 0.0],
            embedding_model="local:test-model",
            limit=10,
            threshold=0.0,
        )

        self.assertEqual(result["total"], 2)
        self.assertEqual(result["records"][0]["reference"], "Strike-LA-20260521-001")
        self.assertGreater(
            result["records"][0]["semantic_score"],
            result["records"][1]["semantic_score"],
        )

    def test_semantic_retrieval_filters_latest_records_and_model_label(self):
        conn = make_connection()
        insert_record(
            conn,
            reference="Strike-LA-20260521-003",
            finding="Latest right model.",
            embedding=[1.0, 0.0],
            embedding_model="local:test-model",
            is_latest=1,
        )
        insert_record(
            conn,
            reference="Strike-LA-20260521-004",
            finding="Superseded right model.",
            embedding=[1.0, 0.0],
            embedding_model="local:test-model",
            is_latest=0,
        )
        insert_record(
            conn,
            reference="Strike-LA-20260521-005",
            finding="Latest wrong model.",
            embedding=[1.0, 0.0],
            embedding_model="remote:test-model",
            is_latest=1,
        )

        result = semantic_retrieve_records(
            conn,
            [1.0, 0.0],
            embedding_model="local:test-model",
        )

        self.assertEqual(result["total"], 1)
        self.assertEqual(result["records"][0]["reference"], "Strike-LA-20260521-003")

    def test_semantic_retrieval_applies_threshold_and_filters(self):
        conn = make_connection()
        insert_record(
            conn,
            reference="Strike-LA-20260521-006",
            finding="Local authority match.",
            embedding=[1.0, 0.0],
            trajectory="Deteriorating",
        )
        insert_record(
            conn,
            reference="Strike-HS-20260521-007",
            finding="Health service match.",
            embedding=[0.9, 0.1],
            trajectory="Stable",
        )

        result = semantic_retrieve_records(
            conn,
            [1.0, 0.0],
            embedding_model="local:test-model",
            threshold=0.95,
            institution="LA",
            trajectory="Deteriorating",
        )

        self.assertEqual(result["total"], 1)
        self.assertEqual(result["records"][0]["reference"], "Strike-LA-20260521-006")

    def test_semantic_retrieval_skips_invalid_or_mismatched_embeddings(self):
        conn = make_connection()
        record_id = insert_record(
            conn,
            reference="Strike-LA-20260521-008",
            finding="Invalid embedding.",
            embedding=None,
        )
        conn.execute(
            """
            INSERT INTO record_embeddings (
                record_id, reference, version, content_hash,
                embedding_model, embedding_json, indexed_fields_json
            ) VALUES (?, 'Strike-LA-20260521-008', 1, 'hash', 'local:test-model',
                      'not json', '{}')
            """,
            (record_id,),
        )
        insert_record(
            conn,
            reference="Strike-LA-20260521-009",
            finding="Dimension mismatch.",
            embedding=[1.0, 0.0, 0.0],
        )

        result = semantic_retrieve_records(
            conn,
            [1.0, 0.0],
            embedding_model="local:test-model",
            threshold=0.1,
        )

        self.assertEqual(result["total"], 0)

    def test_semantic_retrieval_does_not_return_private_or_raw_fields(self):
        conn = make_connection()
        insert_record(
            conn,
            reference="Strike-LA-20260521-010",
            finding="Canonical finding.",
            embedding=[1.0, 0.0],
            source_narrative="private narrative only",
            report_json=json.dumps({"raw_input": "raw input only"}),
        )

        result = semantic_retrieve_records(
            conn,
            [1.0, 0.0],
            embedding_model="local:test-model",
        )
        record = result["records"][0]
        serialized = json.dumps(record)

        self.assertNotIn("source_narrative", record)
        self.assertNotIn("report_json", record)
        self.assertNotIn("private narrative only", serialized)
        self.assertNotIn("raw input only", serialized)

    def test_hybrid_retrieval_blends_semantic_and_keyword_scores(self):
        conn = make_connection()
        insert_record(
            conn,
            reference="Strike-LA-20260521-011",
            finding="Canonical delay keyword.",
            embedding=[1.0, 0.0],
        )
        insert_record(
            conn,
            reference="Strike-LA-20260521-012",
            finding="Canonical delay keyword.",
            embedding=[0.0, 1.0],
        )

        result = hybrid_retrieve_records(
            conn,
            "delay keyword",
            [1.0, 0.0],
            embedding_model="local:test-model",
            threshold=0.0,
            semantic_weight=0.7,
            keyword_weight=0.3,
        )

        self.assertEqual(result["mode"], "hybrid")
        self.assertEqual(result["records"][0]["reference"], "Strike-LA-20260521-011")
        self.assertIn("semantic_score", result["records"][0])
        self.assertIn("keyword_score", result["records"][0])

    def test_hybrid_retrieval_does_not_add_keyword_only_records(self):
        conn = make_connection()
        insert_record(
            conn,
            reference="Strike-LA-20260521-013",
            finding="Keyword only delay phrase.",
            embedding=None,
        )
        insert_record(
            conn,
            reference="Strike-LA-20260521-014",
            finding="Semantic candidate.",
            embedding=[1.0, 0.0],
        )

        result = hybrid_retrieve_records(
            conn,
            "Keyword only delay phrase",
            [1.0, 0.0],
            embedding_model="local:test-model",
            threshold=0.0,
        )

        self.assertEqual(result["total"], 1)
        self.assertEqual(result["records"][0]["reference"], "Strike-LA-20260521-014")


if __name__ == "__main__":
    unittest.main()
