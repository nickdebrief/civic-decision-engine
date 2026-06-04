import base64
import importlib
import json
import os
import sys
import types
import unittest
from unittest.mock import patch


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


if __name__ == "__main__":
    unittest.main()
