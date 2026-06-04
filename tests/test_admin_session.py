import asyncio
import base64
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
from unittest.mock import patch

from api.attachments import ensure_attachment_tables


class FakeAPIRouter:
    def get(self, *args, **kwargs):
        return lambda func: func

    def post(self, *args, **kwargs):
        return lambda func: func


class FakeHTTPException(Exception):
    def __init__(self, status_code=None, detail=None):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class FakeResponse:
    def __init__(self, content=None, status_code=200, media_type=None, headers=None):
        self.content = content
        self.status_code = status_code
        self.media_type = media_type
        self.headers = headers or {}


class FakeJSONResponse(FakeResponse):
    def set_cookie(
        self,
        *,
        key,
        value,
        max_age=None,
        httponly=False,
        secure=False,
        samesite=None,
        **_kwargs,
    ):
        parts = [f"{key}={value}"]
        if max_age is not None:
            parts.append(f"Max-Age={max_age}")
        if httponly:
            parts.append("HttpOnly")
        if secure:
            parts.append("Secure")
        if samesite:
            parts.append(f"SameSite={samesite.capitalize()}")
        self.headers["Set-Cookie"] = "; ".join(parts)

    def delete_cookie(self, *, key, httponly=False, secure=False, samesite=None, **_kwargs):
        parts = [f"{key}=", "Max-Age=0"]
        if httponly:
            parts.append("HttpOnly")
        if secure:
            parts.append("Secure")
        if samesite:
            parts.append(f"SameSite={samesite.capitalize()}")
        self.headers["Set-Cookie"] = "; ".join(parts)


def install_fastapi_stubs():
    fastapi = types.ModuleType("fastapi")
    fastapi.APIRouter = FakeAPIRouter
    fastapi.File = lambda default=None, **kwargs: default
    fastapi.Form = lambda default=None, **kwargs: default
    fastapi.Header = lambda default=None, **kwargs: default
    fastapi.HTTPException = FakeHTTPException
    fastapi.Query = lambda default=None, **kwargs: default
    fastapi.UploadFile = object

    responses = types.ModuleType("fastapi.responses")
    responses.HTMLResponse = FakeResponse
    responses.JSONResponse = FakeJSONResponse
    responses.Response = FakeResponse

    models = types.ModuleType("api.models")
    models.RecordPayload = type("RecordPayload", (), {})
    models.RecordResponse = type("RecordResponse", (), {})

    sys.modules.setdefault("fastapi", fastapi)
    sys.modules.setdefault("fastapi.responses", responses)
    sys.modules.setdefault("api.models", models)


class FakeRequest:
    def __init__(self, cookies=None):
        self.cookies = cookies or {}


class FakeUploadFile:
    def __init__(self, filename, content_type, data):
        self.filename = filename
        self.content_type = content_type
        self._data = data

    async def read(self):
        return self._data


class AdminSessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        install_fastapi_stubs()
        cls.admin_session = importlib.import_module("api.routes.admin_session")

    def env(self):
        return patch.dict(
            os.environ,
            {
                "CDE_ADMIN_PASSWORD": "admin-password",
                "CDE_ADMIN_SESSION_SECRET": "session-secret",
                "CDE_ADMIN_TOKEN": "server-only-token",
            },
            clear=False,
        )

    def assert_no_admin_token_exposed(self, response):
        serialized = json.dumps(
            {
                "content": getattr(response, "content", None),
                "headers": getattr(response, "headers", {}),
            },
            sort_keys=True,
        )
        self.assertNotIn("server-only-token", serialized)
        self.assertNotIn("CDE_ADMIN_TOKEN", serialized)

    def session_from_response(self, response):
        cookie = response.headers["Set-Cookie"]
        prefix = f"{self.admin_session.SESSION_COOKIE_NAME}="
        self.assertTrue(cookie.startswith(prefix))
        return cookie[len(prefix):].split(";", 1)[0]

    def test_login_page_renders_without_cde_admin_token(self):
        with self.env():
            response = self.admin_session.admin_login_page()

        self.assertIn("Civic Decision Engine Admin", response.content)
        self.assertIn('type="password"', response.content)
        self.assertNotIn("server-only-token", response.content)
        self.assertNotIn("CDE_ADMIN_TOKEN", response.content)
        self.assertNotIn("Upload", response.content)
        self.assertNotIn("attachment", response.content.lower())

    def test_successful_login_sets_secure_httponly_strict_cookie(self):
        with self.env():
            response = self.admin_session.admin_session_login("admin-password")

        cookie = response.headers["Set-Cookie"]

        self.assertEqual(response.content, {"ok": True, "role": "admin"})
        self.assertIn("cde_admin_session=", cookie)
        self.assertIn("Max-Age=3600", cookie)
        self.assertIn("HttpOnly", cookie)
        self.assertIn("Secure", cookie)
        self.assertIn("SameSite=Strict", cookie)
        self.assert_no_admin_token_exposed(response)

    def test_session_payload_contains_only_allowed_fields(self):
        with self.env():
            response = self.admin_session.admin_session_login("admin-password")

        session = self.session_from_response(response)
        payload_b64 = session.split(".", 1)[0]
        padding = "=" * (-len(payload_b64) % 4)
        payload = json.loads(
            base64.urlsafe_b64decode((payload_b64 + padding).encode("ascii")).decode(
                "utf-8"
            )
        )

        self.assertEqual(set(payload.keys()), {"role", "issued_at", "expires_at"})
        self.assertEqual(payload["role"], "admin")

    def test_invalid_login_returns_401_without_secret_details(self):
        with self.env():
            with self.assertRaises(Exception) as ctx:
                self.admin_session.admin_session_login("wrong-password")

        self.assertEqual(getattr(ctx.exception, "status_code", None), 401)
        self.assertEqual(getattr(ctx.exception, "detail", None), "admin_session_unauthorized")
        self.assertNotIn("server-only-token", getattr(ctx.exception, "detail", ""))
        self.assertNotIn("admin-password", getattr(ctx.exception, "detail", ""))

    def test_missing_session_fails_require_admin_session(self):
        with self.env():
            with self.assertRaises(Exception) as ctx:
                self.admin_session.require_admin_session(FakeRequest())

        self.assertEqual(getattr(ctx.exception, "status_code", None), 401)

    def test_expired_session_fails_require_admin_session(self):
        with self.env():
            session = self.admin_session.create_admin_session(now=100)

        with self.env():
            with patch.object(self.admin_session.time, "time", return_value=3701):
                with self.assertRaises(Exception) as ctx:
                    self.admin_session.require_admin_session(
                        FakeRequest(
                            {self.admin_session.SESSION_COOKIE_NAME: session}
                        )
                    )

        self.assertEqual(getattr(ctx.exception, "status_code", None), 401)

    def test_valid_session_passes_require_admin_session(self):
        with self.env():
            session = self.admin_session.create_admin_session(now=100)

        with self.env():
            with patch.object(self.admin_session.time, "time", return_value=200):
                payload = self.admin_session.require_admin_session(
                    FakeRequest({self.admin_session.SESSION_COOKIE_NAME: session})
                )

        self.assertEqual(payload["role"], "admin")
        self.assertEqual(set(payload.keys()), {"role", "issued_at", "expires_at"})

    def test_logout_clears_cookie(self):
        response = self.admin_session.admin_session_logout()
        cookie = response.headers["Set-Cookie"]

        self.assertEqual(response.content, {"ok": True})
        self.assertIn("cde_admin_session=", cookie)
        self.assertIn("Max-Age=0", cookie)
        self.assertIn("HttpOnly", cookie)
        self.assertIn("Secure", cookie)
        self.assertIn("SameSite=Strict", cookie)
        self.assert_no_admin_token_exposed(response)

    def make_admin_listing_db(self, db_path):
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("""
            CREATE TABLE records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reference TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 1,
                verification_hash TEXT NOT NULL,
                is_latest INTEGER NOT NULL DEFAULT 1,
                UNIQUE(reference, version)
            )
        """)
        conn.execute(
            """
            INSERT INTO records (reference, version, verification_hash, is_latest)
            VALUES ('Strike-OT-20260604-ADMIN', 1, ?, 1)
            """,
            ("c" * 64,),
        )
        ensure_attachment_tables(conn)
        conn.commit()
        return conn

    def attachment_file_count(self, attachment_root):
        root = Path(attachment_root)
        if not root.exists():
            return 0
        return len([path for path in root.rglob("*") if path.is_file()])

    def insert_admin_attachment(self, conn, **overrides):
        values = {
            "reference": "Strike-OT-20260604-ADMIN",
            "record_version": 1,
            "attachment_version": 1,
            "filename": "public.pdf",
            "stored_filename": "internal-public.pdf",
            "storage_path": "/private/path/internal-public.pdf",
            "content_type": "application/pdf",
            "file_size_bytes": 12345,
            "sha256_hash": "d" * 64,
            "visibility": "public",
            "redaction_status": "none",
            "title": "Public attachment",
            "description": "Attachment description",
            "source_label": "Attachment source",
            "document_date": "2026-06-04",
            "document_date_precision": "day",
            "uploaded_at": "2026-06-04T12:00:00Z",
            "is_latest": 1,
            "is_deleted": 0,
        }
        values.update(overrides)
        columns = ", ".join(values.keys())
        placeholders = ", ".join("?" for _ in values)
        conn.execute(
            f"INSERT INTO record_attachments ({columns}) VALUES ({placeholders})",
            list(values.values()),
        )
        conn.commit()

    def valid_request(self):
        with self.env():
            session = self.admin_session.create_admin_session()
        return FakeRequest({self.admin_session.SESSION_COOKIE_NAME: session})

    def test_admin_attachment_listing_requires_session(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            conn.close()
            try:
                with self.env():
                    with self.assertRaises(Exception) as ctx:
                        self.admin_session.admin_record_attachments_page(
                            "Strike-OT-20260604-ADMIN",
                            FakeRequest(),
                        )
            finally:
                self.admin_session.DB_PATH = original_db_path

        self.assertEqual(getattr(ctx.exception, "status_code", None), 401)

    def test_admin_attachment_listing_displays_all_attachment_states(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            self.insert_admin_attachment(conn)
            self.insert_admin_attachment(
                conn,
                filename="private.pdf",
                stored_filename="internal-private.pdf",
                storage_path="/private/path/internal-private.pdf",
                visibility="private",
                title="Private attachment",
            )
            self.insert_admin_attachment(
                conn,
                filename="withheld.pdf",
                stored_filename="internal-withheld.pdf",
                storage_path="/private/path/internal-withheld.pdf",
                redaction_status="withheld",
                title="Withheld attachment",
            )
            self.insert_admin_attachment(
                conn,
                filename="deleted.pdf",
                stored_filename="internal-deleted.pdf",
                storage_path="/private/path/internal-deleted.pdf",
                is_deleted=1,
                title="Deleted attachment",
            )
            conn.close()
            try:
                with self.env():
                    with patch.object(self.admin_session.time, "time", return_value=200):
                        response = self.admin_session.admin_record_attachments_page(
                            "Strike-OT-20260604-ADMIN",
                            self.valid_request(),
                        )
            finally:
                self.admin_session.DB_PATH = original_db_path

        content = response.content

        self.assertIn("Admin Attachment Listing", content)
        self.assertIn("Strike-OT-20260604-ADMIN", content)
        self.assertIn("Record version", content)
        self.assertIn("Public attachment", content)
        self.assertIn("Private attachment", content)
        self.assertIn("Withheld attachment", content)
        self.assertIn("Deleted attachment", content)
        self.assertIn("public.pdf", content)
        self.assertIn("private.pdf", content)
        self.assertIn("withheld.pdf", content)
        self.assertIn("deleted.pdf", content)
        self.assertIn("application/pdf", content)
        self.assertIn("12345", content)
        self.assertIn("d" * 64, content)
        self.assertIn("public", content)
        self.assertIn("private", content)
        self.assertIn("withheld", content)
        self.assertIn("deleted", content)
        self.assertIn("Attachment description", content)
        self.assertIn("Attachment source", content)
        self.assertIn("2026-06-04", content)
        self.assertIn("day", content)
        self.assertIn("2026-06-04T12:00:00Z", content)
        self.assertIn(
            "Administrative attachment visibility only.",
            content,
        )

    def test_admin_attachment_listing_exposes_no_paths_tokens_or_controls(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            self.insert_admin_attachment(conn)
            conn.close()
            try:
                with self.env():
                    response = self.admin_session.admin_record_attachments_page(
                        "Strike-OT-20260604-ADMIN",
                        self.valid_request(),
                    )
            finally:
                self.admin_session.DB_PATH = original_db_path

        content = response.content

        self.assertNotIn("storage_path", content)
        self.assertNotIn("stored_filename", content)
        self.assertNotIn("internal-public.pdf", content)
        self.assertNotIn("/private/path", content)
        self.assertNotIn("server-only-token", content)
        self.assertNotIn("CDE_ADMIN_TOKEN", content)
        self.assertNotIn("<button", content)
        self.assertNotIn("<form", content)
        self.assertNotIn("Download attachment", content)
        self.assertNotIn("Upload attachment", content)
        self.assertNotIn("Edit attachment", content)
        self.assertNotIn("Delete attachment", content)
        self.assertNotIn("Restore attachment", content)
        self.assertNotIn("Withhold attachment", content)
        self.assertNotIn("Publish attachment", content)

    def test_admin_attachment_listing_empty_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            conn.close()
            try:
                with self.env():
                    response = self.admin_session.admin_record_attachments_page(
                        "Strike-OT-20260604-ADMIN",
                        self.valid_request(),
                    )
            finally:
                self.admin_session.DB_PATH = original_db_path

        self.assertIn(
            "No attachments are currently associated with this record.",
            response.content,
        )

    def test_admin_attachment_listing_does_not_change_canonical_hashing(self):
        canonical = {
            "reference": "Strike-OT-20260604-ADMIN",
            "generated_at": "2026-06-04T12:00:00Z",
            "finding": "Admin listing must not change canonical hashing.",
            "trajectory": "Stable",
            "conditions": sorted(["Transfer of Burden", "Institutional Delay"]),
            "system_state": "Canonical record unchanged",
            "generated_by": "Civic Decision Engine",
        }
        payload = json.dumps(canonical, separators=(",", ":"), sort_keys=True)
        actual = hashlib.sha256(payload.encode("utf-8")).hexdigest()

        self.assertEqual(
            actual,
            "4c3ef9bbe432d5c72a5e2853dbe32a17cd97fa7ac415d3a1ab5c79479c7fac59",
        )

    def test_json_attachment_listing_requires_session(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            conn.close()
            try:
                with self.env():
                    with self.assertRaises(Exception) as ctx:
                        self.admin_session.list_record_attachments_route(
                            "Strike-OT-20260604-ADMIN",
                            FakeRequest(),
                        )
            finally:
                self.admin_session.DB_PATH = original_db_path

        self.assertEqual(getattr(ctx.exception, "status_code", None), 401)

    def test_json_attachment_listing_returns_metadata_without_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            self.insert_admin_attachment(conn)
            conn.close()
            try:
                with self.env():
                    response = self.admin_session.list_record_attachments_route(
                        "Strike-OT-20260604-ADMIN",
                        self.valid_request(),
                    )
            finally:
                self.admin_session.DB_PATH = original_db_path

        serialized = json.dumps(response.content, sort_keys=True)

        self.assertEqual(response.content["attachment_count"], 1)
        self.assertIn("Public attachment", serialized)
        self.assertIn("public.pdf", serialized)
        self.assertNotIn("storage_path", serialized)
        self.assertNotIn("stored_filename", serialized)
        self.assertNotIn("/private/path", serialized)
        self.assertNotIn("internal-public.pdf", serialized)
        self.assertNotIn("server-only-token", serialized)
        self.assertNotIn("CDE_ADMIN_TOKEN", serialized)

    def test_pdf_upload_route_requires_session(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            conn.close()
            try:
                with self.env():
                    with self.assertRaises(Exception) as ctx:
                        asyncio.run(
                            self.admin_session.upload_record_attachment_route(
                                "Strike-OT-20260604-ADMIN",
                                FakeRequest(),
                                file=FakeUploadFile(
                                    "evidence.pdf",
                                    "application/pdf",
                                    b"%PDF-1.4 synthetic",
                                ),
                            )
                        )
            finally:
                self.admin_session.DB_PATH = original_db_path

        self.assertEqual(getattr(ctx.exception, "status_code", None), 401)

    def test_pdf_upload_route_stores_metadata_and_file_without_exposing_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            attachment_root = Path(temp_dir) / "attachments"
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            conn.close()
            data = b"%PDF-1.4 synthetic evidence bytes"
            try:
                with self.env():
                    with patch.dict(
                        os.environ,
                        {"CDE_ATTACHMENT_ROOT": str(attachment_root)},
                        clear=False,
                    ):
                        response = asyncio.run(
                            self.admin_session.upload_record_attachment_route(
                                "Strike-OT-20260604-ADMIN",
                                self.valid_request(),
                                file=FakeUploadFile(
                                    "../../evidence.pdf",
                                    "application/pdf",
                                    data,
                                ),
                                visibility="private",
                                redaction_status="none",
                                title="Uploaded PDF",
                                description="Controlled PDF upload.",
                                source_label="Admin test",
                                document_date="2026-06-04",
                                document_date_precision="day",
                            )
                        )

                conn = sqlite3.connect(self.admin_session.DB_PATH)
                conn.row_factory = sqlite3.Row
                try:
                    row = conn.execute("SELECT * FROM record_attachments").fetchone()
                finally:
                    conn.close()
                stored_path = Path(row["storage_path"])
                stored_file_exists = stored_path.is_file()
                stored_file_bytes = stored_path.read_bytes() if stored_file_exists else b""
                stored_file_count = self.attachment_file_count(attachment_root)
            finally:
                self.admin_session.DB_PATH = original_db_path

        serialized = json.dumps(response.content, sort_keys=True)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.content["attachment"]["filename"], "evidence.pdf")
        self.assertEqual(response.content["attachment"]["content_type"], "application/pdf")
        self.assertEqual(response.content["attachment"]["sha256_hash"], hashlib.sha256(data).hexdigest())
        self.assertEqual(row["sha256_hash"], hashlib.sha256(data).hexdigest())
        self.assertEqual(row["file_size_bytes"], len(data))
        self.assertTrue(stored_file_exists)
        self.assertEqual(stored_file_bytes, data)
        self.assertEqual(stored_file_count, 1)
        self.assertNotIn("storage_path", serialized)
        self.assertNotIn("stored_filename", serialized)
        self.assertNotIn(str(attachment_root), serialized)
        self.assertNotIn("server-only-token", serialized)
        self.assertNotIn("CDE_ADMIN_TOKEN", serialized)

    def test_pdf_upload_route_rejects_unsupported_content_type_before_persistence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            attachment_root = Path(temp_dir) / "attachments"
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            conn.close()
            try:
                with self.env():
                    with patch.dict(
                        os.environ,
                        {"CDE_ATTACHMENT_ROOT": str(attachment_root)},
                        clear=False,
                    ):
                        with self.assertRaises(Exception) as ctx:
                            asyncio.run(
                                self.admin_session.upload_record_attachment_route(
                                    "Strike-OT-20260604-ADMIN",
                                    self.valid_request(),
                                    file=FakeUploadFile(
                                        "evidence.txt",
                                        "text/plain",
                                        b"not a pdf",
                                    ),
                                )
                            )
                conn = sqlite3.connect(self.admin_session.DB_PATH)
                try:
                    row = conn.execute("SELECT * FROM record_attachments").fetchone()
                finally:
                    conn.close()
            finally:
                self.admin_session.DB_PATH = original_db_path

        self.assertEqual(getattr(ctx.exception, "status_code", None), 415)
        self.assertIsNone(row)
        self.assertEqual(self.attachment_file_count(attachment_root), 0)

    def test_pdf_upload_route_enforces_size_limit_before_persistence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            attachment_root = Path(temp_dir) / "attachments"
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            conn.close()
            try:
                with self.env():
                    with patch.dict(
                        os.environ,
                        {
                            "CDE_ATTACHMENT_ROOT": str(attachment_root),
                            "CDE_ATTACHMENT_MAX_BYTES": "4",
                        },
                        clear=False,
                    ):
                        with self.assertRaises(Exception) as ctx:
                            asyncio.run(
                                self.admin_session.upload_record_attachment_route(
                                    "Strike-OT-20260604-ADMIN",
                                    self.valid_request(),
                                    file=FakeUploadFile(
                                        "evidence.pdf",
                                        "application/pdf",
                                        b"%PDF-1.4 synthetic",
                                    ),
                                )
                            )
                conn = sqlite3.connect(self.admin_session.DB_PATH)
                try:
                    row = conn.execute("SELECT * FROM record_attachments").fetchone()
                finally:
                    conn.close()
            finally:
                self.admin_session.DB_PATH = original_db_path

        self.assertEqual(getattr(ctx.exception, "status_code", None), 413)
        self.assertIsNone(row)
        self.assertEqual(self.attachment_file_count(attachment_root), 0)


if __name__ == "__main__":
    unittest.main()
