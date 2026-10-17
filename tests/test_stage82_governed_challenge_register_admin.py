"""Legacy FastAPI-stub coverage for Stage 82's private admission boundary."""
import importlib
import os
import sys
import tempfile
import types
import unittest


class _Router:
    def get(self, *_args, **_kwargs): return lambda function: function
    def post(self, *_args, **_kwargs): return lambda function: function
    def patch(self, *_args, **_kwargs): return lambda function: function


class _Exception(Exception):
    def __init__(self, status_code=None, detail=None): super().__init__(detail); self.status_code, self.detail = status_code, detail


class _Response:
    def __init__(self, content=None, status_code=200, media_type=None, headers=None): self.content, self.status_code, self.headers = content, status_code, headers or {}


class _Request:
    def __init__(self, token): self.cookies = {"cde_admin_session": token}


def _stubs():
    fastapi = types.ModuleType("fastapi"); fastapi.APIRouter = fastapi.HTTPException = _Router
    fastapi.HTTPException = _Exception; fastapi.Query = fastapi.Form = fastapi.File = lambda default=None, **_kwargs: default
    fastapi.Request, fastapi.UploadFile = _Request, object
    responses = types.ModuleType("fastapi.responses"); responses.HTMLResponse = responses.JSONResponse = responses.RedirectResponse = responses.FileResponse = _Response
    sys.modules["fastapi"], sys.modules["fastapi.responses"] = fastapi, responses


class ChallengeAdminTests(unittest.TestCase):
    def setUp(self):
        _stubs(); self.temp = tempfile.TemporaryDirectory(); self.old = dict(os.environ)
        os.environ["CDE_ADMIN_SESSION_SECRET"] = "synthetic-secret"; sys.modules.pop("api.routes.admin_session", None)
        self.module = importlib.import_module("api.routes.admin_session"); self.token = self.module.create_admin_session("admin-a")

    def tearDown(self): os.environ.clear(); os.environ.update(self.old); self.temp.cleanup()

    def test_private_page_and_no_public_challenge_admission(self):
        response = self.module.admin_governed_challenge_register(_Request(self.token))
        self.assertEqual(response.headers["Cache-Control"], "private, no-store")
        self.assertIn("Challenge", response.content)
        with self.assertRaises(_Exception): self.module.require_admin_session(_Request("bad"))


if __name__ == "__main__": unittest.main()
