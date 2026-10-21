"""Real-ASGI containment checks for the Stage 84 private foundation."""
import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path


class RetentionRegisterAsgiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.db = Path(self.temp.name) / "records.db"
        self.old = {key: os.environ.get(key) for key in ("RECORDS_DB_PATH", "CDE_ADMIN_SESSION_SECRET")}
        os.environ.update({"RECORDS_DB_PATH": str(self.db), "CDE_ADMIN_SESSION_SECRET": "stage84-asgi-secret"})
        from api.routes import admin_session
        self.admin, self.old_path = admin_session, admin_session.DB_PATH; self.admin.DB_PATH = self.db; self.token = self.admin.create_admin_session("owner-a")

    def tearDown(self):
        self.admin.DB_PATH = self.old_path
        for key, value in self.old.items():
            if value is None: os.environ.pop(key, None)
            else: os.environ[key] = value
        self.temp.cleanup()

    def request(self, method, path, payload=None, cookie=None):
        from api.main import app
        body = b"" if payload is None else json.dumps(payload).encode(); headers=[(b"host",b"localhost")]
        if payload is not None: headers.append((b"content-type",b"application/json"))
        if cookie: headers.append((b"cookie",cookie.encode()))
        sent=[]; delivered=False
        async def receive():
            nonlocal delivered
            if delivered: return {"type":"http.disconnect"}
            delivered=True; return {"type":"http.request","body":body,"more_body":False}
        async def send(message): sent.append(message)
        asyncio.run(app({"type":"http","asgi":{"version":"3.0"},"http_version":"1.1","method":method,"scheme":"http","path":path,"raw_path":path.encode(),"query_string":b"","headers":headers,"client":("127.0.0.1",1),"server":("localhost",80)},receive,send))
        return next(x for x in sent if x["type"]=="http.response.start"), b"".join(x.get("body",b"") for x in sent if x["type"]=="http.response.body")

    def test_admission_is_private_and_disabled(self):
        path="/api/admin/session/governed-retention-register"
        start,_ = self.request("POST",path,{"restricted":"must-not-retain"}); self.assertEqual(start["status"],401)
        start,body = self.request("POST",path,{"restricted":"must-not-retain"},f"cde_admin_session={self.token}")
        self.assertEqual(start["status"],409); self.assertEqual(dict(start["headers"])[b"cache-control"],b"private, no-store")
        self.assertIn(b"retention_register_admission_disabled",body)
        start,_ = self.request("GET","/governed-retention-register"); self.assertEqual(start["status"],404)


if __name__ == "__main__": unittest.main()
