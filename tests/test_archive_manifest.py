import asyncio
import hashlib
import importlib
import json
import os
import sqlite3
import sys
import tempfile
import types
import unittest
from pathlib import Path


class FakeAPIRouter:
    def get(self, *args, **kwargs):
        return lambda func: func

    def post(self, *args, **kwargs):
        return lambda func: func


class FakeResponse:
    def __init__(self, content=None, status_code=200, media_type=None, headers=None):
        self.content = content
        self.status_code = status_code
        self.media_type = media_type
        self.headers = headers or {}


def install_fastapi_stubs():
    fastapi = types.ModuleType("fastapi")
    fastapi.APIRouter = FakeAPIRouter
    fastapi.HTTPException = Exception
    fastapi.Query = lambda default=None, **kwargs: default

    responses = types.ModuleType("fastapi.responses")
    responses.HTMLResponse = FakeResponse
    responses.JSONResponse = FakeResponse
    responses.Response = FakeResponse

    models = types.ModuleType("api.models")
    models.RecordPayload = type("RecordPayload", (), {})
    models.RecordResponse = type("RecordResponse", (), {})

    sys.modules.setdefault("fastapi", fastapi)
    sys.modules.setdefault("fastapi.responses", responses)
    sys.modules.setdefault("api.models", models)


class ArchiveManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        install_fastapi_stubs()
        cls.import_temp_dir = tempfile.TemporaryDirectory()
        os.environ["RECORDS_DB_PATH"] = str(
            Path(cls.import_temp_dir.name) / "import-records.db"
        )
        cls.records = importlib.import_module("api.routes.records")

    @classmethod
    def tearDownClass(cls):
        cls.import_temp_dir.cleanup()

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "records.db"
        self.original_db_path = self.records.DB_PATH
        self.records.DB_PATH = self.db_path
        self.records.init_db()

    def tearDown(self):
        self.records.DB_PATH = self.original_db_path
        self.temp_dir.cleanup()

    def insert_record(
        self,
        reference="Strike-LA-20260523-001",
        version=1,
        is_latest=1,
        exported_at="2026-05-23T10:00:00Z",
    ):
        conditions = ["Institutional Delay", "Transfer of Burden"]
        generated_at = "2026-05-23T09:00:00Z"
        finding = "Institutional delay remains visible in the record."
        trajectory = "Deteriorating"
        system_state = "Awaiting substantive response"
        generated_by = "Civic Decision Engine"
        verification_hash = self.records.compute_verification_hash(
            reference=reference,
            generated_at=generated_at,
            finding=finding,
            trajectory=trajectory,
            conditions=conditions,
            system_state=system_state,
            generated_by=generated_by,
        )

        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                """
                INSERT INTO records (
                    reference, version, supersedes, generated_at, trajectory,
                    system_state, conditions_json, signals_json, finding,
                    report_json, language, generated_by, verification_hash,
                    exported_at, is_latest, source_narrative
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    reference,
                    version,
                    None,
                    generated_at,
                    trajectory,
                    system_state,
                    json.dumps(conditions),
                    "[]",
                    finding,
                    json.dumps({"private": "private report payload"}),
                    "en",
                    generated_by,
                    verification_hash,
                    exported_at,
                    is_latest,
                    "private source narrative",
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def manifest(self):
        return asyncio.run(self.records.archive_manifest()).content

    def test_archive_manifest_returns_json_inventory(self):
        payload = self.manifest()

        self.assertEqual(payload["manifest_version"], "1.0")
        self.assertEqual(
            payload["manifest_type"], "civic_decision_engine_archive_inventory"
        )
        self.assertIn("generated_at", payload)
        self.assertIn("archive", payload)
        self.assertIn("record_scope", payload)
        self.assertEqual(payload["canonical_index_policy_version"], "canonical-public-v1")
        self.assertIn("records", payload)
        self.assertIn("checksum", payload)

    def test_archive_manifest_includes_latest_records_only(self):
        self.insert_record(reference="Strike-LA-20260523-001", is_latest=1)
        self.insert_record(reference="Strike-LA-20260523-002", is_latest=0)

        payload = self.manifest()
        references = [record["reference"] for record in payload["records"]]

        self.assertEqual(references, ["Strike-LA-20260523-001"])

    def test_record_entries_use_allowed_inventory_fields_only(self):
        self.insert_record(reference="Strike-LA-20260523-003")

        record = self.manifest()["records"][0]

        self.assertEqual(
            set(record.keys()),
            {
                "reference",
                "version",
                "verification_hash",
                "exported_at",
                "trajectory",
                "institution_type",
                "verify_url",
                "manifest_url",
            },
        )

    def test_manifest_excludes_private_raw_and_semantic_fields(self):
        self.insert_record(reference="Strike-LA-20260523-004")

        encoded = json.dumps(self.manifest(), sort_keys=True)

        self.assertNotIn("source_narrative", encoded)
        self.assertNotIn("report_json", encoded)
        self.assertNotIn("raw_input", encoded)
        self.assertNotIn("private source narrative", encoded)
        self.assertNotIn("private report payload", encoded)
        self.assertNotIn("embedding", encoded.lower())
        self.assertNotIn("semantic", encoded.lower())

    def test_checksum_is_deterministic_for_same_records_array(self):
        self.insert_record(reference="Strike-LA-20260523-005")

        first = self.manifest()
        second = self.manifest()
        expected = hashlib.sha256(
            json.dumps(
                first["records"], separators=(",", ":"), sort_keys=True
            ).encode("utf-8")
        ).hexdigest()

        self.assertEqual(first["checksum"]["algorithm"], "SHA-256")
        self.assertEqual(first["checksum"]["scope"], "records array canonical JSON")
        self.assertEqual(first["checksum"]["content_hash"], expected)
        self.assertEqual(
            first["checksum"]["content_hash"],
            second["checksum"]["content_hash"],
        )

    def test_counts_and_latest_exported_at_are_present(self):
        self.insert_record(
            reference="Strike-LA-20260523-006",
            exported_at="2026-05-23T10:00:00Z",
        )
        self.insert_record(
            reference="Strike-LA-20260523-007",
            exported_at="2026-05-24T10:00:00Z",
        )

        payload = self.manifest()

        self.assertEqual(payload["counts"]["total_latest_records"], 2)
        self.assertEqual(payload["latest_exported_at"], "2026-05-24T10:00:00Z")
        self.assertEqual(
            payload["pagination"],
            {
                "paginated": False,
                "limit": None,
                "offset": None,
                "next_url": None,
            },
        )

    def test_sitemap_includes_archive_manifest(self):
        response = asyncio.run(self.records.sitemap())

        self.assertIn("/archive-manifest.json", response.content)


if __name__ == "__main__":
    unittest.main()
