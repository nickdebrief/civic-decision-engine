"""Real-ASGI boundary coverage for the private Stage 81 register handlers."""
import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path


class GovernedDefectRegisterAsgiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "records.db"
        self.old_env = {name: os.environ.get(name) for name in (
            "RECORDS_DB_PATH", "CDE_ADMIN_SESSION_SECRET", "CDE_DEFECT_REGISTER_OWNER_USERNAME")}
        os.environ.update({"RECORDS_DB_PATH": str(self.db_path), "CDE_ADMIN_SESSION_SECRET": "synthetic-admin-secret", "CDE_DEFECT_REGISTER_OWNER_USERNAME": "authenticated-admin"})
        from api.routes import admin_session
        self.admin_session = admin_session
        self.old_db_path = admin_session.DB_PATH
        admin_session.DB_PATH = self.db_path
        self.token = admin_session.create_admin_session("authenticated-admin")

    def tearDown(self):
        self.admin_session.DB_PATH = self.old_db_path
        for name, value in self.old_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        self.temp.cleanup()

    def request(self, method, path, payload=None, cookie=None):
        from api.main import app
        body = b"" if payload is None else json.dumps(payload).encode()
        headers = [(b"host", b"localhost")]
        if payload is not None:
            headers.append((b"content-type", b"application/json"))
        if cookie:
            headers.append((b"cookie", cookie.encode()))
        sent, delivered = [], False
        async def receive():
            nonlocal delivered
            if delivered:
                return {"type": "http.disconnect"}
            delivered = True
            return {"type": "http.request", "body": body, "more_body": False}
        async def send(message):
            sent.append(message)
        scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method, "scheme": "http", "path": path, "raw_path": path.encode(), "query_string": b"", "headers": headers, "client": ("127.0.0.1", 1), "server": ("localhost", 80)}
        asyncio.run(app(scope, receive, send))
        start = next(message for message in sent if message["type"] == "http.response.start")
        return start, b"".join(message.get("body", b"") for message in sent if message["type"] == "http.response.body")

    def payload(self):
        return {"title": "Synthetic", "description": "Synthetic non-sensitive fixture", "affected_component": "synthetic", "observed_behavior": "observed", "expected_behavior": "expected", "expectation_source": "synthetic criterion", "reporter_source": "synthetic source", "expected_version": 0, "idempotency_key": "asgi-create", "synthetic_attestation": {"classification": "synthetic_non_sensitive", "attested": True}}

    def test_private_api_requires_session_and_disables_general_admission(self):
        start, _ = self.request("POST", "/api/admin/session/governed-defects", self.payload())
        self.assertEqual(start["status"], 401)
        cookie = f"cde_admin_session={self.token}"
        start, body = self.request("POST", "/api/admin/session/governed-defects", self.payload(), cookie)
        self.assertEqual(start["status"], 409)
        self.assertEqual(dict(start["headers"])[b"cache-control"], b"private, no-store")
        self.assertIn(b"report_admission_disabled", body)
        start, body = self.request("GET", "/governed-defects")
        self.assertEqual(start["status"], 404)
