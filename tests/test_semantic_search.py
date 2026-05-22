import json
import os
import sqlite3
import unittest
from unittest.mock import patch

from api.semantic_search import (
    cosine_similarity,
    ensure_embedding_tables,
    parse_embedding,
    search_records,
    semantic_search_enabled,
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
    trajectory="Deteriorating",
    system_state="Transition to Escalation",
    source_narrative="",
    report_json=None,
    generated_at="2026-05-21T10:00:00Z",
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
        ) VALUES (?, 1, NULL, ?, ?, ?, ?, '[]', ?, ?, 'en',
                  'Civic Decision Engine', ?, ?, ?, ?)
        """,
        (
            reference,
            generated_at,
            trajectory,
            system_state,
            json.dumps(conditions),
            finding,
            report_json if report_json is not None else "{}",
            f"hash-{reference}",
            exported_at,
            is_latest,
            source_narrative,
        ),
    )


class SemanticSearchTests(unittest.TestCase):
    def test_semantic_search_enabled_defaults_to_false(self):
        env = {k: v for k, v in os.environ.items() if k != "SEMANTIC_SEARCH_ENABLED"}
        with patch.dict(os.environ, env, clear=True):
            self.assertFalse(semantic_search_enabled())

    def test_semantic_search_enabled_false_like_values(self):
        for value in ("false", "0", "no", "off", ""):
            with self.subTest(value=value):
                with patch.dict(os.environ, {"SEMANTIC_SEARCH_ENABLED": value}):
                    self.assertFalse(semantic_search_enabled())

    def test_semantic_search_enabled_true_like_values(self):
        for value in ("true", "1", "yes", "on"):
            with self.subTest(value=value):
                with patch.dict(os.environ, {"SEMANTIC_SEARCH_ENABLED": value}):
                    self.assertTrue(semantic_search_enabled())

    def test_ensure_embedding_tables_creates_table_and_indexes(self):
        conn = make_connection()

        ensure_embedding_tables(conn)

        table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name = 'record_embeddings'"
        ).fetchone()
        indexes = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            ).fetchall()
        }
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(record_embeddings)").fetchall()
        }

        self.assertIsNotNone(table)
        self.assertIn("idx_record_embeddings_ref_version", indexes)
        self.assertIn("idx_record_embeddings_record_model", indexes)
        self.assertIn("index_policy_version", columns)
        self.assertIn("embedding_dimensions", columns)
        self.assertIn("provider_kind", columns)
        self.assertIn("derived_from_hash", columns)

    def test_search_records_uses_keyword_fallback_by_default(self):
        conn = make_connection()
        insert_record(
            conn,
            reference="Strike-LA-20260521-001",
            finding="Institutional delay is visible.",
            conditions=["Institutional Delay"],
        )

        with patch.dict(os.environ, {}, clear=True):
            result = search_records(conn, "Institutional delay")

        self.assertEqual(result["mode"], "keyword_fallback")
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["records"][0]["reference"], "Strike-LA-20260521-001")

    def test_fallback_search_only_uses_latest_records(self):
        conn = make_connection()
        insert_record(
            conn,
            reference="Strike-LA-20260521-001",
            finding="Visible current finding.",
            conditions=["Institutional Delay"],
            is_latest=1,
        )
        insert_record(
            conn,
            reference="Strike-LA-20260521-002",
            finding="Only superseded finding.",
            conditions=["Institutional Delay"],
            is_latest=0,
        )

        result = search_records(conn, "superseded finding")

        self.assertEqual(result["total"], 0)
        self.assertEqual(result["records"], [])

    def test_fallback_search_matches_canonical_fields(self):
        conn = make_connection()
        insert_record(
            conn,
            reference="Strike-HS-20260521-010",
            generated_at="2026-05-21T12:34:00Z",
            finding="Canonical finding about delay.",
            trajectory="Deteriorating",
            system_state="Transition to Escalation",
            conditions=["Transfer of Burden"],
        )

        for query in (
            "Strike-HS-20260521-010",
            "2026-05-21T12:34:00Z",
            "Canonical finding",
            "Deteriorating",
            "Transition to Escalation",
            "Transfer of Burden",
            "Civic Decision Engine",
        ):
            with self.subTest(query=query):
                self.assertEqual(search_records(conn, query)["total"], 1)

    def test_fallback_search_excludes_source_narrative_report_json_and_raw_input(self):
        conn = make_connection()
        insert_record(
            conn,
            reference="Strike-LA-20260521-003",
            finding="Canonical public finding.",
            conditions=["Institutional Delay"],
            source_narrative="private narrative only",
            report_json=json.dumps({"raw_input": "raw input only"}),
        )

        self.assertEqual(search_records(conn, "private narrative only")["total"], 0)
        self.assertEqual(search_records(conn, "raw input only")["total"], 0)

    def test_fallback_search_respects_trajectory_and_institution_filters(self):
        conn = make_connection()
        insert_record(
            conn,
            reference="Strike-LA-20260521-004",
            finding="Shared searchable phrase.",
            conditions=["Institutional Delay"],
            trajectory="Deteriorating",
        )
        insert_record(
            conn,
            reference="Strike-HS-20260521-005",
            finding="Shared searchable phrase.",
            conditions=["Institutional Delay"],
            trajectory="Stable",
        )

        by_institution = search_records(
            conn, "Shared searchable phrase", institution="LA"
        )
        by_trajectory = search_records(
            conn, "Shared searchable phrase", trajectory="Stable"
        )

        self.assertEqual(by_institution["total"], 1)
        self.assertEqual(
            by_institution["records"][0]["reference"], "Strike-LA-20260521-004"
        )
        self.assertEqual(by_trajectory["total"], 1)
        self.assertEqual(
            by_trajectory["records"][0]["reference"], "Strike-HS-20260521-005"
        )

    def test_empty_query_returns_no_records(self):
        conn = make_connection()
        insert_record(
            conn,
            reference="Strike-LA-20260521-006",
            finding="Canonical public finding.",
            conditions=["Institutional Delay"],
        )

        result = search_records(conn, "   ")

        self.assertEqual(result["mode"], "empty")
        self.assertEqual(result["total"], 0)
        self.assertEqual(result["records"], [])

    def test_parse_embedding(self):
        self.assertEqual(parse_embedding("[1, 2.5, 3]"), [1.0, 2.5, 3.0])
        self.assertEqual(parse_embedding('{"bad": "shape"}'), [])
        self.assertEqual(parse_embedding("[1, \"bad\"]"), [])
        self.assertEqual(parse_embedding("not json"), [])

    def test_cosine_similarity(self):
        self.assertAlmostEqual(cosine_similarity([1.0, 0.0], [1.0, 0.0]), 1.0)
        self.assertAlmostEqual(cosine_similarity([1.0, 0.0], [0.0, 1.0]), 0.0)
        self.assertEqual(cosine_similarity([1.0], [1.0, 2.0]), 0.0)
        self.assertEqual(cosine_similarity([], []), 0.0)


if __name__ == "__main__":
    unittest.main()
