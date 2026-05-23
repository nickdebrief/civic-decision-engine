import asyncio
import importlib
import json
import os
import sqlite3
import sys
import tempfile
import types
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


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


class MachineDiscoverabilityTests(unittest.TestCase):
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
                    "{}",
                    "en",
                    generated_by,
                    verification_hash,
                    exported_at,
                    is_latest,
                    "Excluded source narrative.",
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def test_main_does_not_shadow_dynamic_sitemap_or_robots_routes(self):
        main_source = (REPO_ROOT / "api" / "main.py").read_text()

        self.assertNotIn('@app.get("/sitemap.xml")', main_source)
        self.assertNotIn('@app.get("/robots.txt")', main_source)

    def test_sitemap_is_dynamic_and_archive_oriented(self):
        self.insert_record(reference="Strike-LA-20260523-001", is_latest=1)
        self.insert_record(reference="Strike-LA-20260523-002", is_latest=0)

        response = asyncio.run(self.records.sitemap())
        content = response.content

        self.assertEqual(response.media_type, "application/xml")
        self.assertIn("<urlset", content)
        for path in (
            "/records",
            "/conditions",
            "/conditions/map",
            "/patterns",
            "/stats",
            "/stats/timeline",
            "/graph",
            "/api/docs",
        ):
            self.assertIn(path, content)
        self.assertIn("/verify/Strike-LA-20260523-001", content)
        self.assertNotIn("/verify/Strike-LA-20260523-002", content)

    def test_robots_policy_is_archive_friendly(self):
        response = asyncio.run(self.records.robots())

        self.assertEqual(response.media_type, "text/plain")
        self.assertEqual(
            response.content,
            "User-agent: *\n"
            "Allow: /\n"
            "\n"
            "Sitemap: https://civic-decision-engine-production.up.railway.app/sitemap.xml\n",
        )

    def test_verify_page_links_machine_readable_json_alternates(self):
        reference = "Strike-LA-20260523-003"
        self.insert_record(reference=reference)

        response = asyncio.run(self.records.verify_record(reference))
        content = response.content

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            f'<link rel="alternate" type="application/json" href="/verify/{reference}/manifest">',
            content,
        )
        self.assertIn(
            f'<link rel="alternate" type="application/json" href="/api/verify/{reference}">',
            content,
        )

    def test_root_page_has_plain_archive_links(self):
        content = (REPO_ROOT / "api" / "static" / "index.html").read_text()

        for href in (
            'href="/records"',
            'href="/conditions"',
            'href="/patterns"',
            'href="/stats"',
            'href="/graph"',
            'href="/api/docs"',
        ):
            self.assertIn(href, content)


if __name__ == "__main__":
    unittest.main()
