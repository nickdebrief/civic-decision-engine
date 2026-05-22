import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from api.semantic_search import INDEX_POLICY_VERSION, ensure_embedding_tables
from scripts.backfill_record_embeddings import backfill_record_embeddings
from scripts.run_semantic_experiments import (
    NON_AUTHORITATIVE_NOTICE,
    ensure_no_excluded_fields,
    run_semantic_experiments,
    selected_experiments,
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
    conditions,
    trajectory="Deteriorating",
    source_narrative="private narrative only",
    report_json=None,
    is_latest=1,
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
                  ?, 'Transition to Escalation', ?,
                  '[]', ?, ?, 'en', 'Civic Decision Engine', ?,
                  '2026-05-21T10:05:00Z', ?, ?)
        """,
        (
            reference,
            trajectory,
            json.dumps(conditions),
            finding,
            report_json if report_json is not None else json.dumps({"raw_input": "raw input only"}),
            f"hash-{reference}",
            is_latest,
            source_narrative,
        ),
    )


class FakeProvider:
    label = "fake:test-model"

    def __init__(self, vector=None):
        self.vector = vector or [1.0, 0.0]
        self.inputs = []

    def embed(self, text):
        self.inputs.append(text)
        return self.vector


def seeded_connection(provider):
    conn = make_connection()
    insert_record(
        conn,
        reference="Strike-LA-20260521-001",
        finding="Institutional delay without substantive response.",
        conditions=["Institutional Delay"],
        trajectory="Deteriorating",
    )
    insert_record(
        conn,
        reference="Strike-HS-20260521-002",
        finding="Transfer of burden and repeated contact.",
        conditions=["Transfer of Burden"],
        trajectory="Stable",
    )
    insert_record(
        conn,
        reference="Strike-LA-20260521-003",
        finding="Superseded private raw record.",
        conditions=["Escalation Without Response"],
        trajectory="Deteriorating",
        is_latest=0,
    )
    backfill_record_embeddings(conn, provider=provider)
    provider.inputs.clear()
    return conn


class RunSemanticExperimentsTests(unittest.TestCase):
    def test_selected_experiments_defaults_to_all(self):
        self.assertEqual(
            selected_experiments(None),
            [
                "condition-proximity",
                "institutional-recurrence",
                "trajectory-similarity",
                "multilingual-alignment",
            ],
        )
        self.assertEqual(selected_experiments(["all"]), selected_experiments(None))
        self.assertEqual(
            selected_experiments(["condition-proximity"]), ["condition-proximity"]
        )

    def test_condition_proximity_writes_json_output(self):
        provider = FakeProvider()
        conn = seeded_connection(provider)
        query_sets = {
            "condition-proximity": [
                {
                    "id": "delay",
                    "query": "institutional delay without response",
                }
            ]
        }

        with tempfile.TemporaryDirectory() as tmp:
            summary = run_semantic_experiments(
                conn,
                provider=provider,
                output_dir=tmp,
                run_id="test-run",
                experiments=["condition-proximity"],
                query_sets=query_sets,
            )
            output = Path(tmp) / "test-run_condition_proximity.json"
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(summary["run_id"], "test-run")
        self.assertTrue(payload["derived_metadata_only"])
        self.assertEqual(payload["non_authoritative_notice"], NON_AUTHORITATIVE_NOTICE)
        self.assertEqual(payload["experiment"], "condition-proximity")
        self.assertEqual(payload["index_policy_version"], INDEX_POLICY_VERSION)
        self.assertEqual(payload["queries"][0]["id"], "delay")

    def test_institutional_recurrence_applies_institution_filter(self):
        provider = FakeProvider()
        conn = seeded_connection(provider)
        query_sets = {
            "institutional-recurrence": [
                {
                    "id": "local_authority",
                    "query": "delay",
                    "institution": "LA",
                }
            ]
        }

        with tempfile.TemporaryDirectory() as tmp:
            run_semantic_experiments(
                conn,
                provider=provider,
                output_dir=tmp,
                run_id="inst",
                experiments=["institutional-recurrence"],
                query_sets=query_sets,
            )
            payload = json.loads(
                (Path(tmp) / "inst_institutional_recurrence.json").read_text(
                    encoding="utf-8"
                )
            )

        records = payload["queries"][0]["result"]["records"]
        self.assertTrue(records)
        self.assertTrue(all(record["reference"].startswith("Strike-LA-") for record in records))

    def test_trajectory_similarity_applies_trajectory_filter(self):
        provider = FakeProvider()
        conn = seeded_connection(provider)
        query_sets = {
            "trajectory-similarity": [
                {
                    "id": "stable",
                    "query": "repeated contact",
                    "trajectory": "Stable",
                }
            ]
        }

        with tempfile.TemporaryDirectory() as tmp:
            run_semantic_experiments(
                conn,
                provider=provider,
                output_dir=tmp,
                run_id="traj",
                experiments=["trajectory-similarity"],
                query_sets=query_sets,
            )
            payload = json.loads(
                (Path(tmp) / "traj_trajectory_similarity.json").read_text(
                    encoding="utf-8"
                )
            )

        records = payload["queries"][0]["result"]["records"]
        self.assertTrue(records)
        self.assertTrue(all(record["trajectory"] == "Stable" for record in records))

    def test_multilingual_alignment_writes_overlap_metrics(self):
        provider = FakeProvider()
        conn = seeded_connection(provider)
        query_sets = {
            "multilingual-alignment": [
                {
                    "id": "delay_alignment",
                    "queries": {
                        "en": "institutional delay",
                        "fr": "retard institutionnel",
                    },
                }
            ]
        }

        with tempfile.TemporaryDirectory() as tmp:
            run_semantic_experiments(
                conn,
                provider=provider,
                output_dir=tmp,
                run_id="multi",
                experiments=["multilingual-alignment"],
                query_sets=query_sets,
            )
            payload = json.loads(
                (Path(tmp) / "multi_multilingual_alignment.json").read_text(
                    encoding="utf-8"
                )
            )

        query = payload["queries"][0]
        self.assertIn("languages", query)
        self.assertIn("overlap", query)
        self.assertIn("jaccard", query["overlap"])

    def test_all_experiments_writes_all_outputs_and_summary(self):
        provider = FakeProvider()
        conn = seeded_connection(provider)

        with tempfile.TemporaryDirectory() as tmp:
            summary = run_semantic_experiments(
                conn,
                provider=provider,
                output_dir=tmp,
                run_id="all-run",
                experiments=["all"],
            )
            files = {Path(path).name for path in summary["files"]}

        self.assertIn("all-run_condition_proximity.json", files)
        self.assertIn("all-run_institutional_recurrence.json", files)
        self.assertIn("all-run_trajectory_similarity.json", files)
        self.assertIn("all-run_multilingual_alignment.json", files)
        self.assertIn("all-run_summary.json", files)

    def test_hybrid_flag_is_reflected_in_output_parameters(self):
        provider = FakeProvider()
        conn = seeded_connection(provider)

        with tempfile.TemporaryDirectory() as tmp:
            run_semantic_experiments(
                conn,
                provider=provider,
                output_dir=tmp,
                run_id="hybrid",
                experiments=["condition-proximity"],
                hybrid=True,
                semantic_weight=0.5,
                keyword_weight=0.5,
            )
            payload = json.loads(
                (Path(tmp) / "hybrid_condition_proximity.json").read_text(
                    encoding="utf-8"
                )
            )

        self.assertTrue(payload["parameters"]["hybrid"])
        self.assertEqual(payload["parameters"]["semantic_weight"], 0.5)
        self.assertEqual(payload["parameters"]["keyword_weight"], 0.5)

    def test_output_excludes_private_and_raw_fields(self):
        provider = FakeProvider()
        conn = seeded_connection(provider)

        with tempfile.TemporaryDirectory() as tmp:
            run_semantic_experiments(
                conn,
                provider=provider,
                output_dir=tmp,
                run_id="safe",
                experiments=["all"],
            )
            serialized = "\n".join(
                path.read_text(encoding="utf-8") for path in Path(tmp).glob("*.json")
            )

        self.assertNotIn("source_narrative", serialized)
        self.assertNotIn("report_json", serialized)
        self.assertNotIn("raw_input", serialized)
        self.assertNotIn("private narrative", serialized)
        self.assertNotIn("raw input", serialized)

    def test_refuses_to_overwrite_without_flag(self):
        provider = FakeProvider()
        conn = seeded_connection(provider)

        with tempfile.TemporaryDirectory() as tmp:
            run_semantic_experiments(
                conn,
                provider=provider,
                output_dir=tmp,
                run_id="same",
                experiments=["condition-proximity"],
            )
            with self.assertRaises(FileExistsError):
                run_semantic_experiments(
                    conn,
                    provider=provider,
                    output_dir=tmp,
                    run_id="same",
                    experiments=["condition-proximity"],
                )
            run_semantic_experiments(
                conn,
                provider=provider,
                output_dir=tmp,
                run_id="same",
                experiments=["condition-proximity"],
                overwrite=True,
            )

    def test_excluded_field_guard_rejects_payloads(self):
        with self.assertRaises(ValueError):
            ensure_no_excluded_fields({"source_narrative": "private narrative"})


if __name__ == "__main__":
    unittest.main()
