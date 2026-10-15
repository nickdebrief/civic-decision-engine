"""Legacy FastAPI-stub coverage for the Stage 81 private admin page."""
import importlib
import os
import sqlite3
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from api import governed_defect_register as register


class _Router:
    def get(self, *_args, **_kwargs): return lambda function: function
    def post(self, *_args, **_kwargs): return lambda function: function
    def patch(self, *_args, **_kwargs): return lambda function: function


class _Exception(Exception):
    def __init__(self, status_code=None, detail=None):
        super().__init__(detail); self.status_code, self.detail = status_code, detail


class _Response:
    def __init__(self, content=None, status_code=200, media_type=None, headers=None):
        self.content, self.status_code, self.media_type, self.headers = content, status_code, media_type, headers or {}


class _Request:
    def __init__(self, token): self.cookies = {"cde_admin_session": token}


def _install_stubs():
    fastapi = types.ModuleType("fastapi")
    fastapi.APIRouter, fastapi.HTTPException = _Router, _Exception
    fastapi.Query = fastapi.Form = fastapi.File = lambda default=None, **_kwargs: default
    fastapi.Request, fastapi.UploadFile = _Request, object
    responses = types.ModuleType("fastapi.responses")
    responses.HTMLResponse = responses.JSONResponse = responses.RedirectResponse = responses.FileResponse = _Response
    sys.modules["fastapi"], sys.modules["fastapi.responses"] = fastapi, responses


class GovernedDefectRegisterAdminTests(unittest.TestCase):
    def setUp(self):
        _install_stubs()
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = f"{self.temp.name}/records.db"
        self.old_env = dict(os.environ)
        os.environ.update({"CDE_ADMIN_SESSION_SECRET": "stub-secret"})
        sys.modules.pop("api.routes.admin_session", None)
        self.module = importlib.import_module("api.routes.admin_session")
        self.old_path, self.module.DB_PATH = self.module.DB_PATH, self.module.Path(self.db_path)
        self.token = self.module.create_admin_session("stub-admin")

    def tearDown(self):
        self.module.DB_PATH = self.old_path
        os.environ.clear(); os.environ.update(self.old_env)
        self.temp.cleanup()

    def test_private_admin_page_renders_navigation_and_never_exposes_a_public_route(self):
        response = self.module.admin_governed_defect_register(_Request(self.token))
        self.assertEqual(response.headers["Cache-Control"], "private, no-store")
        self.assertIn("Defect &amp; Correction Register", response.content)
        self.assertIn("report intake is disabled", response.content)
        with self.assertRaises(_Exception) as raised:
            self.module.require_admin_session(_Request("invalid"))

    def test_verified_original_with_downstream_work_has_private_prominent_notice(self):
        item = {
            "entry_identifier": "CDE-DEF-SYNTHETIC-001", "title": "Synthetic", "lifecycle_state": "closed",
            "assessment_classification": "confirmed_defect", "closure": {"outcome": "correction_verified"},
            "revalidations": [{"requirement_identifier": "CDE-DEF-SYNTHETIC-001:RV-001", "outcome": "open", "owner_reference": "admin-b"}],
            "history": [],
        }
        with patch.object(self.module.gdr81, "get_entry", return_value=item):
            response = self.module.admin_governed_defect_register_entry(item["entry_identifier"], _Request(self.token))
        self.assertEqual(response.headers["Cache-Control"], "private, no-store")
        self.assertIn("Original correction verified — downstream work outstanding.", response.content)

    def test_historical_or_not_required_rows_do_not_inflate_downstream_notice(self):
        item = {
            "entry_identifier": "CDE-DEF-SYNTHETIC-002", "title": "Synthetic", "lifecycle_state": "closed",
            "assessment_classification": "confirmed_defect", "closure": {"outcome": "correction_verified"},
            "revalidations": [
                {"requirement_identifier": "CDE-DEF-SYNTHETIC-002:RV-001", "outcome": "superseded", "owner_reference": "admin-b"},
                {"requirement_identifier": "CDE-DEF-SYNTHETIC-002:RV-002", "outcome": "not_required", "owner_reference": "admin-b"},
            ],
            "history": [],
        }
        with patch.object(self.module.gdr81, "get_entry", return_value=item):
            response = self.module.admin_governed_defect_register_entry(item["entry_identifier"], _Request(self.token))
        self.assertNotIn("Original correction verified — downstream work outstanding.", response.content)
