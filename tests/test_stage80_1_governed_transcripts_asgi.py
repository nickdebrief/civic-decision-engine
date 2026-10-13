"""Real-ASGI coverage for Stage 80.1 private transcript endpoints."""
import asyncio
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from api.document_intake import store_private_original_source_media


MP4_BYTES = b"\x00\x00\x00\x18ftypisom\x00\x00\x00\x00synthetic asgi"


class GovernedTranscriptAsgiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_env = {key: os.environ.get(key) for key in ("CDE_DOCUMENT_INTAKE_ROOT", "RECORDS_DB_PATH", "CDE_ADMIN_SESSION_SECRET")}
        self.root = Path(self.temp.name) / "intake"
        self.db_path = Path(self.temp.name) / "records.db"
        os.environ.update({"CDE_DOCUMENT_INTAKE_ROOT": str(self.root), "RECORDS_DB_PATH": str(self.db_path), "CDE_ADMIN_SESSION_SECRET": "synthetic-admin-secret"})
        from api.routes import admin_session
        self.admin_session = admin_session
        self.old_db_path = admin_session.DB_PATH
        admin_session.DB_PATH = self.db_path
        self.source = store_private_original_source_media(
            data=MP4_BYTES, original_filename="synthetic.mp4", content_type="video/mp4",
            title="Synthetic", institution_source="Synthetic", document_date="2026-10-11",
            category="Synthetic", description="Synthetic", notes="Synthetic", root=self.root,
        )
        self.token = admin_session.create_admin_session("authenticated-admin")

    def tearDown(self):
        self.admin_session.DB_PATH = self.old_db_path
        for key, value in self.old_env.items():
            if value is None: os.environ.pop(key, None)
            else: os.environ[key] = value
        self.temp.cleanup()

    def asgi_request(self, method, path, *, payload=None, raw_body=None, cookie=None):
        from api.main import app
        body = raw_body if raw_body is not None else (b"" if payload is None else json.dumps(payload).encode("utf-8"))
        headers = [(b"host", b"localhost:8000")]
        if payload is not None or raw_body is not None: headers.append((b"content-type", b"application/json"))
        if cookie: headers.append((b"cookie", cookie.encode("ascii")))
        messages = []
        delivered = False
        async def receive():
            nonlocal delivered
            if delivered: return {"type": "http.disconnect"}
            delivered = True
            return {"type": "http.request", "body": body, "more_body": False}
        async def send(message): messages.append(message)
        scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method, "scheme": "http", "path": path, "raw_path": path.encode(), "query_string": b"", "headers": headers, "client": ("127.0.0.1", 1), "server": ("localhost", 8000)}
        asyncio.run(app(scope, receive, send))
        start = next(message for message in messages if message["type"] == "http.response.start")
        response = b"".join(message.get("body", b"") for message in messages if message["type"] == "http.response.body")
        return start, response

    def payload(self):
        return {"expected_version": 0, "source_language": "en", "transcription_method": "manual_entry", "responsible_actor": "untrusted", "utterances": [{"start_ms": 0, "end_ms": 10, "text": "Synthetic", "speaker_state": "unknown"}]}

    def test_real_asgi_route_enforces_session_parses_json_and_returns_no_store(self):
        path = f"/api/admin/session/private-source-media/{self.source['intake_id']}/transcripts"
        start, _ = self.asgi_request("POST", path, payload=self.payload())
        self.assertEqual(start["status"], 401)
        start, _ = self.asgi_request("POST", path, payload=self.payload(), cookie="cde_admin_session=invalid")
        self.assertEqual(start["status"], 401)
        start, body = self.asgi_request("POST", path, payload=self.payload(), cookie=f"cde_admin_session={self.token}")
        headers = dict(start["headers"])
        self.assertEqual(start["status"], 201)
        self.assertEqual(headers[b"cache-control"], b"private, no-store")
        item = json.loads(body)["transcript"]
        self.assertEqual(item["responsible_actor"], "authenticated-admin")
        start, _ = self.asgi_request("GET", f"{path}/1", cookie=f"cde_admin_session={self.token}")
        self.assertEqual(start["status"], 200)
        self.assertEqual(dict(start["headers"])[b"cache-control"], b"private, no-store")

    def test_real_asgi_rejects_invalid_json_without_creating_rows(self):
        path = f"/api/admin/session/private-source-media/{self.source['intake_id']}/transcripts"
        start, _ = self.asgi_request("POST", path, raw_body=b"{invalid", cookie=f"cde_admin_session={self.token}")
        self.assertEqual(start["status"], 400)
        conn = sqlite3.connect(self.db_path)
        try:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='source_media_transcripts'").fetchone()[0], 0)
        finally: conn.close()

    def _create_then_read(self):
        path = f"/api/admin/session/private-source-media/{self.source['intake_id']}/transcripts"
        cookie = f"cde_admin_session={self.token}"
        start, _ = self.asgi_request("POST", path, payload=self.payload(), cookie=cookie)
        self.assertEqual(start["status"], 201)
        start, body = self.asgi_request("GET", f"{path}/1", cookie=cookie)
        self.assertEqual(start["status"], 200)
        self.assertIn(b"Synthetic", body)
        return path, cookie

    def _transcript_state(self):
        conn = sqlite3.connect(self.db_path)
        try:
            return tuple(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in (
                "source_media_transcripts", "source_media_transcript_utterances",
                "source_media_transcript_translations", "source_media_transcript_audit_events",
            ))
        finally:
            conn.close()

    def test_real_asgi_missing_source_retrieval_does_not_leak_transcript_content(self):
        path, cookie = self._create_then_read()
        before = self._transcript_state()
        Path(self.source["proposed_storage_location"]).unlink()
        start, body = self.asgi_request("GET", f"{path}/1", cookie=cookie)
        self.assertEqual(start["status"], 404)
        for forbidden in (b"Synthetic", b"utterances", b"translations", b"speaker"):
            self.assertNotIn(forbidden, body)
        self.assertEqual(self._transcript_state(), before)

    def test_real_asgi_ineligible_source_retrieval_does_not_leak_transcript_content(self):
        path, cookie = self._create_then_read()
        before = self._transcript_state()
        metadata_path = self.root / self.source["intake_id"] / "metadata.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata.pop("private_original_source_media")
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
        start, body = self.asgi_request("GET", f"{path}/1", cookie=cookie)
        self.assertEqual(start["status"], 404)
        for forbidden in (b"Synthetic", b"utterances", b"translations", b"speaker"):
            self.assertNotIn(forbidden, body)
        self.assertEqual(self._transcript_state(), before)

    def test_real_asgi_identity_mismatch_retrieval_does_not_leak_transcript_content(self):
        path, cookie = self._create_then_read()
        before = self._transcript_state()
        metadata_path = self.root / self.source["intake_id"] / "metadata.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata["private_original_source_media"]["original_source_identity"] = "source-sha256:wrong"
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
        start, body = self.asgi_request("GET", f"{path}/1", cookie=cookie)
        self.assertEqual(start["status"], 404)
        for forbidden in (b"Synthetic", b"utterances", b"translations", b"speaker"):
            self.assertNotIn(forbidden, body)
        self.assertEqual(self._transcript_state(), before)

    def test_real_asgi_digest_mismatch_retrieval_does_not_leak_transcript_content(self):
        path, cookie = self._create_then_read()
        before = self._transcript_state()
        Path(self.source["proposed_storage_location"]).write_bytes(b"changed synthetic bytes")
        start, body = self.asgi_request("GET", f"{path}/1", cookie=cookie)
        self.assertEqual(start["status"], 404)
        for forbidden in (b"Synthetic", b"utterances", b"translations", b"speaker"):
            self.assertNotIn(forbidden, body)
        self.assertEqual(self._transcript_state(), before)
