import base64
import hashlib
import io
import importlib
import json
import os
import re
import sqlite3
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from api.attachments import (
    ensure_attachment_tables,
    public_evidence_manifest_attachments,
    public_manifest_attachments,
)


class FakeAPIRouter:
    def get(self, *args, **kwargs):
        return lambda func: func

    def post(self, *args, **kwargs):
        return lambda func: func

    def patch(self, *args, **kwargs):
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

    def delete_cookie(
        self, *, key, httponly=False, secure=False, samesite=None, **_kwargs
    ):
        parts = [f"{key}=", "Max-Age=0"]
        if httponly:
            parts.append("HttpOnly")
        if secure:
            parts.append("Secure")
        if samesite:
            parts.append(f"SameSite={samesite.capitalize()}")
        self.headers["Set-Cookie"] = "; ".join(parts)


def install_fastapi_stubs():
    fastapi = sys.modules.get("fastapi") or types.ModuleType("fastapi")
    fastapi.APIRouter = FakeAPIRouter
    fastapi.File = lambda default=None, **kwargs: default
    fastapi.Form = lambda default=None, **kwargs: default
    fastapi.Header = lambda default=None, **kwargs: default
    fastapi.HTTPException = FakeHTTPException
    fastapi.Query = lambda default=None, **kwargs: default
    fastapi.Request = FakeRequest
    fastapi.UploadFile = object

    responses = sys.modules.get("fastapi.responses") or types.ModuleType(
        "fastapi.responses"
    )
    responses.HTMLResponse = FakeResponse
    responses.JSONResponse = FakeJSONResponse
    responses.Response = FakeResponse

    models = types.ModuleType("api.models")
    models.RecordPayload = type("RecordPayload", (), {})
    models.RecordResponse = type("RecordResponse", (), {})

    sys.modules["fastapi"] = fastapi
    sys.modules["fastapi.responses"] = responses
    sys.modules.setdefault("api.models", models)


class FakeRequest:
    def __init__(self, cookies=None):
        self.cookies = cookies or {}


class FakeUploadFile:
    def __init__(
        self,
        data: bytes,
        *,
        filename: str = "evidence.txt",
        content_type: str = "text/plain",
    ):
        self.filename = filename
        self.content_type = content_type
        self.file = io.BytesIO(data)


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
                "ADMIN_TEMP_UPLOAD_ENABLED": "false",
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

    def test_stage17f_governance_summary_renders_classification_states(self):
        def governance(classification):
            return {
                "summary": {
                    "total_governance_layers": 5,
                    "supported_governance_layers": 5,
                    "unsupported_governance_layers": 0,
                    "dependency_classification": "Supported",
                    "impact_classification": "Evidence-Supported Impact",
                    "stability_classification": "Stable",
                    "reproducibility_classification": "Reproducible",
                    "integrity_classification": "High Integrity",
                    "governance_classification": classification,
                },
                "reviews": {
                    "dependency": {
                        "classification": "Supported",
                        "evidence_supported": 5,
                        "unsupported": 0,
                    },
                    "impact": {
                        "classification": "Evidence-Supported Impact",
                        "evidence_supported": 5,
                        "unsupported": 0,
                    },
                    "stability": {
                        "classification": "Stable",
                        "stable": 5,
                        "limited_stability": 0,
                        "unstable": 0,
                    },
                    "reproducibility": {
                        "classification": "Reproducible",
                        "reproducible": 5,
                        "limited_reproducibility": 0,
                        "non_reproducible": 0,
                    },
                    "integrity": {
                        "classification": "High Integrity",
                        "high_integrity": 5,
                        "limited_integrity": 0,
                        "compromised_integrity": 0,
                    },
                },
                "record": {
                    "reference": "Strike-LA-20260710-004",
                    "trajectory": "Stable",
                    "finding": "Trajectory recorded as Stable.",
                    "dependency_classification": "Supported",
                    "impact_classification": "Evidence-Supported Impact",
                    "stability_classification": "Stable",
                    "reproducibility_classification": "Reproducible",
                    "integrity_classification": "High Integrity",
                    "governance_classification": classification,
                },
            }

        classify = self.admin_session._stage17f_governance_classification

        self.assertEqual(
            "Governance Gap",
            classify(
                "Unsupported",
                "Evidence-Supported Impact",
                "Stable",
                "Reproducible",
                "High Integrity",
            ),
        )
        self.assertEqual(
            "Governed",
            classify(
                "Supported",
                "Evidence-Supported Impact",
                "Stable",
                "Reproducible",
                "High Integrity",
            ),
        )
        self.assertEqual(
            "Partially Governed",
            classify(
                "Supported",
                "Evidence-Supported Impact",
                "Limited Stability",
                "Limited Reproducibility",
                "Limited Integrity",
            ),
        )

        for classification in (
            "Governed",
            "Partially Governed",
            "Governance Gap",
        ):
            rendered = self.admin_session._render_stage17f_governance_summary_content(
                governance(classification)
            )
            self.assertIn(
                f"<td>Governance Classification</td><td>{classification}</td>",
                rendered,
            )
            self.assertIn("<h3>Dependency Review</h3>", rendered)
            self.assertIn("<h3>Impact Review</h3>", rendered)
            self.assertIn("<h3>Stability Review</h3>", rendered)
            self.assertIn("<h3>Reproducibility Review</h3>", rendered)
            self.assertIn("<h3>Integrity Review</h3>", rendered)

    def test_stage17g_governance_continuity_renders_classification_states(self):
        def continuity(classification):
            return {
                "summary": {
                    "total_continuity_layers": 5,
                    "continuous_layers": 5 if classification == "Continuous Governance" else 0,
                    "partial_continuity_layers": (
                        5 if classification == "Partial Continuity" else 0
                    ),
                    "discontinuous_layers": (
                        5 if classification == "Governance Discontinuity" else 0
                    ),
                    "governance_classification": {
                        "Continuous Governance": "Governed",
                        "Partial Continuity": "Partially Governed",
                        "Governance Discontinuity": "Governance Gap",
                    }[classification],
                    "continuity_classification": classification,
                },
                "reviews": {
                    "dependency": {
                        "classification": "Supported",
                        "evidence_supported": 5,
                        "unsupported": 0,
                        "continuity_state": "Continuous",
                    },
                    "impact": {
                        "classification": "Evidence-Supported Impact",
                        "evidence_supported": 5,
                        "unsupported": 0,
                        "continuity_state": "Continuous",
                    },
                    "stability": {
                        "classification": "Stable",
                        "stable": 5,
                        "limited_stability": 0,
                        "unstable": 0,
                        "continuity_state": "Continuous",
                    },
                    "reproducibility": {
                        "classification": "Reproducible",
                        "reproducible": 5,
                        "limited_reproducibility": 0,
                        "non_reproducible": 0,
                        "continuity_state": "Continuous",
                    },
                    "integrity": {
                        "classification": "High Integrity",
                        "high_integrity": 5,
                        "limited_integrity": 0,
                        "compromised_integrity": 0,
                        "continuity_state": "Continuous",
                    },
                },
                "record": {
                    "reference": "Strike-LA-20260710-004",
                    "trajectory": "Stable",
                    "finding": "Trajectory recorded as Stable.",
                    "governance_classification": {
                        "Continuous Governance": "Governed",
                        "Partial Continuity": "Partially Governed",
                        "Governance Discontinuity": "Governance Gap",
                    }[classification],
                    "dependency_classification": "Supported",
                    "impact_classification": "Evidence-Supported Impact",
                    "stability_classification": "Stable",
                    "reproducibility_classification": "Reproducible",
                    "integrity_classification": "High Integrity",
                    "continuity_classification": classification,
                },
            }

        classify = self.admin_session._stage17g_continuity_classification

        self.assertEqual(
            "Governance Discontinuity",
            classify(
                "Unsupported",
                "Evidence-Supported Impact",
                "Stable",
                "Reproducible",
                "High Integrity",
                "Partially Governed",
            ),
        )
        self.assertEqual(
            "Continuous Governance",
            classify(
                "Supported",
                "Evidence-Supported Impact",
                "Stable",
                "Reproducible",
                "High Integrity",
                "Governed",
            ),
        )
        self.assertEqual(
            "Partial Continuity",
            classify(
                "Supported",
                "Evidence-Supported Impact",
                "Limited Stability",
                "Limited Reproducibility",
                "Limited Integrity",
                "Partially Governed",
            ),
        )

        for classification in (
            "Continuous Governance",
            "Partial Continuity",
            "Governance Discontinuity",
        ):
            rendered = (
                self.admin_session._render_stage17g_governance_continuity_content(
                    continuity(classification)
                )
            )
            self.assertIn(
                f"<td>Continuity Classification</td><td>{classification}</td>",
                rendered,
            )
            self.assertIn("<h3>Dependency Continuity</h3>", rendered)
            self.assertIn("<h3>Impact Continuity</h3>", rendered)
            self.assertIn("<h3>Stability Continuity</h3>", rendered)
            self.assertIn("<h3>Reproducibility Continuity</h3>", rendered)
            self.assertIn("<h3>Integrity Continuity</h3>", rendered)


    def test_stage17h_governance_change_log_renders_classification_states(self):
        def change_log(classification):
            return {
                "summary": {
                    "total_governance_layers": 5,
                    "active_governance_layers": 5,
                    "current_governance_classification": {
                        "No Recorded Change": "Governed",
                        "Limited Change": "Partially Governed",
                        "Significant Change": "Governance Gap",
                    }[classification],
                    "current_continuity_classification": {
                        "No Recorded Change": "Continuous Governance",
                        "Limited Change": "Partial Continuity",
                        "Significant Change": "Governance Discontinuity",
                    }[classification],
                    "governance_change_state": classification,
                },
                "reviews": {
                    "dependency": {
                        "classification": "Supported",
                        "evidence_supported": 5,
                        "unsupported": 0,
                        "change_state": classification,
                    },
                    "impact": {
                        "classification": "Evidence-Supported Impact",
                        "evidence_supported": 5,
                        "unsupported": 0,
                        "change_state": classification,
                    },
                    "stability": {
                        "classification": "Stable",
                        "stable": 5,
                        "limited_stability": 0,
                        "unstable": 0,
                        "change_state": classification,
                    },
                    "reproducibility": {
                        "classification": "Reproducible",
                        "reproducible": 5,
                        "limited_reproducibility": 0,
                        "non_reproducible": 0,
                        "change_state": classification,
                    },
                    "integrity": {
                        "classification": "High Integrity",
                        "high_integrity": 5,
                        "limited_integrity": 0,
                        "compromised_integrity": 0,
                        "change_state": classification,
                    },
                    "governance": {
                        "governance_classification": {
                            "No Recorded Change": "Governed",
                            "Limited Change": "Partially Governed",
                            "Significant Change": "Governance Gap",
                        }[classification],
                        "continuity_classification": {
                            "No Recorded Change": "Continuous Governance",
                            "Limited Change": "Partial Continuity",
                            "Significant Change": "Governance Discontinuity",
                        }[classification],
                        "change_state": classification,
                    },
                },
                "record": {
                    "reference": "Strike-LA-20260710-004",
                    "trajectory": "Stable",
                    "finding": "Trajectory recorded as Stable.",
                    "dependency_classification": "Supported",
                    "impact_classification": "Evidence-Supported Impact",
                    "stability_classification": "Stable",
                    "reproducibility_classification": "Reproducible",
                    "integrity_classification": "High Integrity",
                    "governance_classification": {
                        "No Recorded Change": "Governed",
                        "Limited Change": "Partially Governed",
                        "Significant Change": "Governance Gap",
                    }[classification],
                    "continuity_classification": {
                        "No Recorded Change": "Continuous Governance",
                        "Limited Change": "Partial Continuity",
                        "Significant Change": "Governance Discontinuity",
                    }[classification],
                    "governance_change_state": classification,
                },
            }

        classify = self.admin_session._stage17h_governance_change_state

        self.assertEqual(
            "Significant Change",
            classify(
                "Supported",
                "Evidence-Supported Impact",
                "Unstable",
                "Reproducible",
                "High Integrity",
                "Partially Governed",
                "Partial Continuity",
            ),
        )
        self.assertEqual(
            "Limited Change",
            classify(
                "Supported",
                "Evidence-Supported Impact",
                "Limited Stability",
                "Reproducible",
                "High Integrity",
                "Partially Governed",
                "Partial Continuity",
            ),
        )
        self.assertEqual(
            "No Recorded Change",
            classify(
                "Supported",
                "Evidence-Supported Impact",
                "Stable",
                "Reproducible",
                "High Integrity",
                "Governed",
                "Continuous Governance",
            ),
        )

        for classification in (
            "No Recorded Change",
            "Limited Change",
            "Significant Change",
        ):
            rendered = self.admin_session._render_stage17h_governance_change_log_content(
                change_log(classification)
            )
            self.assertIn(
                f"<td>Governance Change State</td><td>{classification}</td>",
                rendered,
            )
            self.assertIn("<h3>Dependency Change Review</h3>", rendered)
            self.assertIn("<h3>Impact Change Review</h3>", rendered)
            self.assertIn("<h3>Stability Change Review</h3>", rendered)
            self.assertIn("<h3>Reproducibility Change Review</h3>", rendered)
            self.assertIn("<h3>Integrity Change Review</h3>", rendered)
            self.assertIn("<h3>Governance Change Review</h3>", rendered)


    def test_stage17i_governance_trajectory_renders_classification_states(self):
        def trajectory(classification):
            return {
                "summary": {
                    "total_trajectory_layers": 6,
                    "progression_layers": 6 if classification == "Governance Progression" else 0,
                    "persistent_layers": 6 if classification == "Governance Persistence" else 0,
                    "regression_layers": 6 if classification == "Governance Regression" else 0,
                    "current_governance_classification": {
                        "Governance Progression": "Governed",
                        "Governance Persistence": "Partially Governed",
                        "Governance Regression": "Governance Gap",
                    }[classification],
                    "current_continuity_classification": {
                        "Governance Progression": "Continuous Governance",
                        "Governance Persistence": "Partial Continuity",
                        "Governance Regression": "Governance Discontinuity",
                    }[classification],
                    "current_change_state": {
                        "Governance Progression": "No Recorded Change",
                        "Governance Persistence": "Limited Change",
                        "Governance Regression": "Significant Change",
                    }[classification],
                    "governance_trajectory": classification,
                },
                "reviews": {
                    "dependency": {
                        "classification": "Supported",
                        "evidence_supported": 5,
                        "unsupported": 0,
                        "trajectory_state": "Progression",
                    },
                    "impact": {
                        "classification": "Evidence-Supported Impact",
                        "evidence_supported": 5,
                        "unsupported": 0,
                        "trajectory_state": "Progression",
                    },
                    "stability": {
                        "classification": "Stable",
                        "stable": 5,
                        "limited_stability": 0,
                        "unstable": 0,
                        "trajectory_state": "Progression",
                    },
                    "reproducibility": {
                        "classification": "Reproducible",
                        "reproducible": 5,
                        "limited_reproducibility": 0,
                        "non_reproducible": 0,
                        "trajectory_state": "Progression",
                    },
                    "integrity": {
                        "classification": "High Integrity",
                        "high_integrity": 5,
                        "limited_integrity": 0,
                        "compromised_integrity": 0,
                        "trajectory_state": "Progression",
                    },
                    "governance": {
                        "governance_classification": {
                            "Governance Progression": "Governed",
                            "Governance Persistence": "Partially Governed",
                            "Governance Regression": "Governance Gap",
                        }[classification],
                        "continuity_classification": {
                            "Governance Progression": "Continuous Governance",
                            "Governance Persistence": "Partial Continuity",
                            "Governance Regression": "Governance Discontinuity",
                        }[classification],
                        "change_state": {
                            "Governance Progression": "No Recorded Change",
                            "Governance Persistence": "Limited Change",
                            "Governance Regression": "Significant Change",
                        }[classification],
                        "trajectory_state": {
                            "Governance Progression": "Progression",
                            "Governance Persistence": "Persistent",
                            "Governance Regression": "Regression",
                        }[classification],
                    },
                },
                "record": {
                    "reference": "Strike-LA-20260710-004",
                    "trajectory": "Stable",
                    "finding": "Trajectory recorded as Stable.",
                    "governance_classification": {
                        "Governance Progression": "Governed",
                        "Governance Persistence": "Partially Governed",
                        "Governance Regression": "Governance Gap",
                    }[classification],
                    "continuity_classification": {
                        "Governance Progression": "Continuous Governance",
                        "Governance Persistence": "Partial Continuity",
                        "Governance Regression": "Governance Discontinuity",
                    }[classification],
                    "governance_change_state": {
                        "Governance Progression": "No Recorded Change",
                        "Governance Persistence": "Limited Change",
                        "Governance Regression": "Significant Change",
                    }[classification],
                    "dependency_classification": "Supported",
                    "impact_classification": "Evidence-Supported Impact",
                    "stability_classification": "Stable",
                    "reproducibility_classification": "Reproducible",
                    "integrity_classification": "High Integrity",
                    "governance_trajectory": classification,
                },
            }

        classify = self.admin_session._stage17i_governance_trajectory

        self.assertEqual(
            "Governance Regression",
            classify(
                "Supported",
                "Evidence-Supported Impact",
                "Unstable",
                "Reproducible",
                "High Integrity",
                "Partially Governed",
                "Partial Continuity",
                "Limited Change",
            ),
        )
        self.assertEqual(
            "Governance Progression",
            classify(
                "Supported",
                "Evidence-Supported Impact",
                "Stable",
                "Reproducible",
                "High Integrity",
                "Governed",
                "Continuous Governance",
                "No Recorded Change",
            ),
        )
        self.assertEqual(
            "Governance Persistence",
            classify(
                "Supported",
                "Evidence-Supported Impact",
                "Limited Stability",
                "Reproducible",
                "High Integrity",
                "Partially Governed",
                "Partial Continuity",
                "Limited Change",
            ),
        )

        for classification in (
            "Governance Progression",
            "Governance Persistence",
            "Governance Regression",
        ):
            rendered = self.admin_session._render_stage17i_governance_trajectory_content(
                trajectory(classification)
            )
            self.assertIn(
                f"<td>Governance Trajectory</td><td>{classification}</td>",
                rendered,
            )
            self.assertIn("<h3>Dependency Trajectory</h3>", rendered)
            self.assertIn("<h3>Impact Trajectory</h3>", rendered)
            self.assertIn("<h3>Stability Trajectory</h3>", rendered)
            self.assertIn("<h3>Reproducibility Trajectory</h3>", rendered)
            self.assertIn("<h3>Integrity Trajectory</h3>", rendered)
            self.assertIn("<h3>Governance Trajectory Review</h3>", rendered)

    def session_from_response(self, response):
        cookie = response.headers["Set-Cookie"]
        prefix = f"{self.admin_session.SESSION_COOKIE_NAME}="
        self.assertTrue(cookie.startswith(prefix))
        return cookie[len(prefix) :].split(";", 1)[0]

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
        self.assertEqual(
            getattr(ctx.exception, "detail", None), "admin_session_unauthorized"
        )
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
                        FakeRequest({self.admin_session.SESSION_COOKIE_NAME: session})
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
                trajectory TEXT,
                system_state TEXT,
                conditions_json TEXT,
                signals_json TEXT,
                finding TEXT,
                source_narrative TEXT,
                report_json TEXT,
                is_latest INTEGER NOT NULL DEFAULT 1,
                UNIQUE(reference, version)
            )
        """)
        conn.execute(
            """
            INSERT INTO records (
                reference, version, verification_hash, trajectory, system_state,
                conditions_json, signals_json, finding, source_narrative,
                report_json, is_latest
            )
            VALUES ('Strike-OT-20260604-ADMIN', 1, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (
                "c" * 64,
                "Stable",
                "Persistent resistance without adaptation",
                json.dumps(
                    [
                        "INSTITUTIONAL_DELAY",
                        "PROCEDURAL_DEFLECTION",
                        "REPEATED_CONTACT_WITHOUT_RESOLUTION",
                        "Transfer of Burden",
                        "Escalation Without Response",
                    ]
                ),
                json.dumps(["Missing Response", {"name": "Procedural Loop"}]),
                "Finding <requires> review",
                "private source narrative must stay hidden",
                json.dumps({"private": "report json must stay hidden"}),
            ),
        )
        ensure_attachment_tables(conn)
        conn.commit()
        return conn

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
            "publication_status": "internal",
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

    def fetch_attachment_row(self, db_path, attachment_id=1):
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            return dict(
                conn.execute(
                    "SELECT * FROM record_attachments WHERE id = ?",
                    (attachment_id,),
                ).fetchone()
            )
        finally:
            conn.close()

    def insert_attachment_audit_event(self, conn, **overrides):
        values = {
            "attachment_id": 7,
            "reference": "Strike-OT-20260604-ADMIN",
            "record_version": 1,
            "event_type": "attachment_metadata_viewed",
            "actor": "admin",
            "occurred_at": "2026-06-04T13:00:00Z",
            "metadata_json": json.dumps(
                {
                    "note": "Audit <script>alert('x')</script>",
                    "storage_path": "/private/path/internal-public.pdf",
                    "source_narrative": "private raw narrative",
                },
                sort_keys=True,
            ),
            "request_id": "req-admin-001",
            "ip_hash": "ip-hash-hidden",
            "user_agent_hash": "ua-hash-hidden",
        }
        values.update(overrides)
        columns = ", ".join(values.keys())
        placeholders = ", ".join("?" for _ in values)
        conn.execute(
            f"INSERT INTO attachment_audit_events ({columns}) VALUES ({placeholders})",
            list(values.values()),
        )
        conn.commit()

    def insert_attachment_relationship(self, conn, **overrides):
        values = {
            "reference": "Strike-OT-20260604-ADMIN",
            "record_version": 1,
            "attachment_id": 1,
            "relationship_type": "supports",
            "target_type": "condition",
            "target_key": "Transfer of Burden",
            "is_active": 1,
            "created_at": "2026-06-04T13:30:00Z",
            "created_by": "admin",
        }
        values.update(overrides)
        columns = ", ".join(values.keys())
        placeholders = ", ".join("?" for _ in values)
        conn.execute(
            f"INSERT INTO record_attachment_relationships ({columns}) VALUES ({placeholders})",
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
            self.insert_attachment_relationship(conn)
            self.insert_attachment_relationship(
                conn,
                relationship_type="context_for",
                target_type="condition",
                target_key="INSTITUTIONAL_DELAY",
            )
            self.insert_attachment_relationship(
                conn,
                relationship_type="supports",
                target_type="condition",
                target_key="INSTITUTIONAL_DELAY",
            )
            self.insert_attachment_relationship(
                conn,
                relationship_type="supports",
                target_type="signal",
                target_key="Missing Response",
            )
            self.insert_attachment_relationship(
                conn,
                relationship_type="contradicts",
                target_type="condition",
                target_key="REMOVED_RELATIONSHIP_TARGET",
                is_active=0,
            )
            self.insert_attachment_audit_event(
                conn,
                attachment_id=8,
                event_type="attachment_created",
                actor="admin",
                occurred_at="2026-06-04T12:30:00Z",
                request_id="req-admin-older",
            )
            self.insert_attachment_audit_event(
                conn,
                attachment_id=9,
                event_type="attachment_visibility_reviewed",
                actor="reviewer",
                occurred_at="2026-06-04T14:00:00Z",
                metadata_json=json.dumps(
                    {
                        "note": "Reviewed <script>alert('x')</script>",
                        "storage_path": "/private/path/internal-audit.pdf",
                        "source_narrative": "private raw narrative",
                    },
                    sort_keys=True,
                ),
                request_id="req-admin-newer",
            )
            self.insert_attachment_audit_event(
                conn,
                attachment_id=11,
                event_type="attachment_metadata_corrected",
                actor="admin",
                occurred_at="2026-06-04T16:00:00Z",
                metadata_json=json.dumps({"changed_fields": ["title"]}),
                request_id="req-admin-corrected",
            )
            self.insert_attachment_audit_event(
                conn,
                attachment_id=1,
                event_type="attachment_relationship_added",
                actor="admin",
                occurred_at="2026-06-04T15:30:00Z",
                metadata_json=json.dumps(
                    {
                        "relationship_id": 1,
                        "relationship_type": "supports",
                        "target_type": "condition",
                        "target_key": "Transfer of Burden",
                    },
                    sort_keys=True,
                ),
                request_id="req-relationship-added",
            )
            self.insert_attachment_audit_event(
                conn,
                attachment_id=None,
                event_type="synthetic_audit_verification",
                actor="admin",
                occurred_at="2026-06-04T11:32:00Z",
                metadata_json=json.dumps({"purpose": "local verification"}),
                request_id="req-synthetic",
            )
            self.insert_attachment_audit_event(
                conn,
                reference="Strike-OT-20260604-OTHER",
                attachment_id=10,
                event_type="other_record_event",
                occurred_at="2026-06-04T15:00:00Z",
                metadata_json=json.dumps({"note": "Other record audit event"}),
                request_id="req-other",
            )
            conn.close()
            try:
                with self.env():
                    with patch.object(
                        self.admin_session.time, "time", return_value=200
                    ):
                        response = self.admin_session.admin_record_attachments_page(
                            "Strike-OT-20260604-ADMIN",
                            self.valid_request(),
                        )
            finally:
                self.admin_session.DB_PATH = original_db_path

        content = response.content

        self.assertIn("Admin Attachment Management", content)
        self.assertIn('class="admin-watermark print-watermark"', content)
        self.assertIn('aria-hidden="true"', content)
        self.assertIn("print-color-adjust: exact", content)
        self.assertIn(">v12</text>", content)
        self.assertIn("Strike-OT-20260604-ADMIN", content)
        self.assertIn("Record summary", content)
        self.assertIn("Current attachments", content)
        self.assertIn("Administrative capabilities", content)
        self.assertIn("Implemented", content)
        self.assertIn("Planned", content)
        self.assertNotIn("Future management actions", content)
        self.assertNotIn("Future controls planned:", content)
        self.assertIn("metadata correction", content)
        self.assertIn("withhold / restore", content)
        self.assertIn("soft-delete", content)
        self.assertIn("audit trail review", content)
        self.assertIn("visibility workflow", content)
        self.assertIn("publication workflow", content)
        self.assertIn("public file serving", content)
        self.assertIn("Audit trail", content)
        self.assertNotIn("Audit trail placeholder", content)
        self.assertNotIn(
            "Audit trail display is planned for a later Stage 5B step.",
            content,
        )
        self.assertNotIn("No audit events are displayed in Step 4A.", content)
        self.assertIn("Governance notice", content)
        self.assertIn("Record version", content)
        self.assertIn(
            'href="/admin/records/Strike-OT-20260604-ADMIN/evidence"',
            content,
        )
        self.assertIn("View record evidence by target", content)
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
        self.assertIn("Classification", content)
        self.assertIn("Publication status", content)
        self.assertIn(">other<", content)
        self.assertIn(">internal<", content)
        self.assertIn("2026-06-04", content)
        self.assertIn("day", content)
        self.assertIn("2026-06-04T12:00:00Z", content)
        self.assertIn('<details class="attachment-card" open>', content)
        self.assertIn('<details class="audit-event" open>', content)
        self.assertIn(
            'class="attachment-metadata-update-form classification-update-form"',
            content,
        )
        self.assertIn("data-classification-update-form", content)
        self.assertIn(
            'action="/api/admin/session/records/Strike-OT-20260604-ADMIN/attachments/1/classification"',
            content,
        )
        self.assertIn('data-method="PATCH"', content)
        self.assertIn('method="post"', content)
        self.assertIn('name="classification"', content)
        self.assertIn('<option value="evidence">evidence</option>', content)
        self.assertIn(
            '<option value="correspondence">correspondence</option>',
            content,
        )
        self.assertIn('<option value="decision">decision</option>', content)
        self.assertIn(
            '<option value="medical_record">medical_record</option>',
            content,
        )
        self.assertIn(
            '<option value="legal_filing">legal_filing</option>',
            content,
        )
        self.assertIn('<option value="photograph">photograph</option>', content)
        self.assertIn('<option value="media">media</option>', content)
        self.assertIn('<option value="research">research</option>', content)
        self.assertIn('<option value="other" selected>other</option>', content)
        self.assertIn("Update classification", content)
        self.assertIn(
            'class="attachment-metadata-update-form publication-update-form"', content
        )
        self.assertIn("data-publication-update-form", content)
        self.assertIn(
            'action="/api/admin/session/records/Strike-OT-20260604-ADMIN/attachments/1/publication"',
            content,
        )
        self.assertIn('data-json-field="publication_status"', content)
        self.assertIn('name="publication_status"', content)
        self.assertIn('<option value="internal" selected>internal</option>', content)
        self.assertIn('<option value="published">published</option>', content)
        self.assertIn('<option value="withdrawn">withdrawn</option>', content)
        self.assertIn("Update publication", content)
        self.assertIn(
            "Controlled administrative metadata/publication workflow action only.",
            content,
        )
        self.assertIn(
            'class="attachment-metadata-update-form visibility-update-form"', content
        )
        self.assertIn("data-visibility-update-form", content)
        self.assertIn(
            'action="/api/admin/session/records/Strike-OT-20260604-ADMIN/attachments/1/visibility"',
            content,
        )
        self.assertIn('data-json-field="visibility"', content)
        self.assertIn('name="visibility"', content)
        self.assertIn('<option value="private">private</option>', content)
        self.assertIn('<option value="public" selected>public</option>', content)
        self.assertIn("Update visibility", content)
        self.assertIn(
            "Controlled administrative visibility workflow action only.", content
        )
        self.assertIn("Evidence Relationships (4)", content)
        self.assertIn("Evidence Coverage", content)
        self.assertIn("<strong>Status:</strong> Partial", content)
        self.assertIn(
            "<strong>Reason:</strong> Conditions remain unlinked. Signals remain unlinked. Findings remain unlinked. Record targets remain unlinked.",
            content,
        )
        self.assertIn("<td>Conditions linked</td><td>2 / 5</td>", content)
        self.assertIn("<td>Signals linked</td><td>1 / 2</td>", content)
        self.assertIn("<td>Findings linked</td><td>0 / 1</td>", content)
        self.assertIn("<td>Records linked</td><td>0 / 1</td>", content)
        self.assertIn("Unlinked Conditions", content)
        self.assertIn("<li>Procedural Deflection</li>", content)
        self.assertIn("<li>Repeated Contact Without Resolution</li>", content)
        self.assertIn("<li>Escalation Without Response</li>", content)
        self.assertIn(
            '<details class="relationship-group relationship-group-condition" open>',
            content,
        )
        self.assertIn("<summary>Conditions (3)</summary>", content)
        self.assertIn(
            '<details class="relationship-group relationship-group-signal">',
            content,
        )
        self.assertIn("<summary>Signals (1)</summary>", content)
        self.assertNotIn("relationship-group-finding", content)
        self.assertNotIn("relationship-group-record", content)
        self.assertIn('class="relationship-card"', content)
        self.assertIn("supports • condition", content)
        self.assertIn("context_for • condition", content)
        self.assertIn("supports • signal", content)
        self.assertIn("→ Transfer of Burden", content)
        self.assertIn("→ Institutional Delay", content)
        self.assertIn("→ Missing Response", content)
        self.assertIn('data-target-key="INSTITUTIONAL_DELAY"', content)
        self.assertNotIn("REMOVED_RELATIONSHIP_TARGET", content)
        self.assertNotIn("→ Removed Relationship Target", content)
        self.assertIn('class="attachment-relationship-form"', content)
        self.assertIn("data-relationship-add-form", content)
        self.assertIn(
            'action="/api/admin/session/records/Strike-OT-20260604-ADMIN/attachments/1/relationships"',
            content,
        )
        self.assertIn('name="relationship_type"', content)
        self.assertIn('<option value="supports">supports</option>', content)
        self.assertIn('<option value="contradicts">contradicts</option>', content)
        self.assertIn('<option value="context_for">context_for</option>', content)
        self.assertIn('name="target_type"', content)
        self.assertIn('<option value="condition">condition</option>', content)
        self.assertIn('<option value="signal">signal</option>', content)
        self.assertIn('<option value="finding">finding</option>', content)
        self.assertIn('<option value="record">record</option>', content)
        self.assertIn('name="target_key"', content)
        self.assertIn("data-target-key-select", content)
        self.assertNotIn('input name="target_key"', content)
        self.assertIn(
            '<option value="INSTITUTIONAL_DELAY">Institutional Delay</option>',
            content,
        )
        self.assertIn(
            '<option value="PROCEDURAL_DEFLECTION">Procedural Deflection</option>',
            content,
        )
        self.assertIn(
            '<option value="REPEATED_CONTACT_WITHOUT_RESOLUTION">Repeated Contact Without Resolution</option>',
            content,
        )
        self.assertIn(
            '<option value="Transfer of Burden">Transfer of Burden</option>',
            content,
        )
        self.assertIn(
            '<option value="Escalation Without Response">Escalation Without Response</option>',
            content,
        )
        self.assertIn('"condition": [', content)
        self.assertIn('"INSTITUTIONAL_DELAY"', content)
        self.assertIn('"PROCEDURAL_DEFLECTION"', content)
        self.assertIn('"REPEATED_CONTACT_WITHOUT_RESOLUTION"', content)
        self.assertIn("guidedTargetDisplayLabel", content)
        self.assertIn("option.value = value", content)
        self.assertIn('"signal": ["Missing Response", "Procedural Loop"]', content)
        self.assertIn('"finding": ["Finding \\u003crequires\\u003e review"]', content)
        self.assertIn('"record": ["Strike-OT-20260604-ADMIN"]', content)
        self.assertIn("No available targets", content)
        self.assertIn("RELATIONSHIP_TARGET_OPTIONS", content)
        self.assertIn("updateTargetKeyOptions", content)
        self.assertIn("Add relationship", content)
        self.assertIn("data-relationship-remove-form", content)
        self.assertIn(
            'action="/api/admin/session/records/Strike-OT-20260604-ADMIN/attachments/1/relationships/1/remove"',
            content,
        )
        self.assertIn("Remove relationship", content)
        self.assertIn(
            "Controlled administrative evidence-linking action only.", content
        )
        self.assertIn("Controlled administrative metadata action only.", content)
        self.assertIn('method: "PATCH"', content)
        self.assertIn('<span class="summary-title">Public attachment</span>', content)
        self.assertIn(
            '<span class="summary-meta">other • active • public • none • internal</span>',
            content,
        )
        self.assertIn(
            '<span class="summary-time">2026-06-04 12:00 UTC</span>',
            content,
        )
        self.assertIn('<span class="summary-title">Private attachment</span>', content)
        self.assertIn(
            '<span class="summary-meta">other • active • private • none • internal</span>',
            content,
        )
        self.assertIn('<span class="summary-title">Withheld attachment</span>', content)
        self.assertIn(
            '<span class="summary-meta">other • withheld • public • withheld • internal</span>',
            content,
        )
        self.assertIn('<span class="summary-title">Deleted attachment</span>', content)
        self.assertIn(
            '<span class="summary-meta">other • deleted • public • none • internal</span>',
            content,
        )
        self.assertIn("2026-06-04T14:00:00Z", content)
        self.assertIn("2026-06-04T12:30:00Z", content)
        self.assertLess(
            content.index("2026-06-04T16:00:00Z"),
            content.index("2026-06-04T14:00:00Z"),
        )
        self.assertLess(
            content.index("2026-06-04T14:00:00Z"),
            content.index("2026-06-04T12:30:00Z"),
        )
        self.assertIn('<span class="event-badge">[metadata corrected]</span>', content)
        self.assertIn(
            '<span class="event-badge">[classification updated]</span>',
            self.admin_session._render_admin_audit_events(
                [
                    {
                        "attachment_id": 1,
                        "event_type": "attachment_classification_updated",
                        "actor": "admin",
                        "occurred_at": "2026-06-04T16:30:00Z",
                        "record_version": 1,
                        "request_id": "req-classification",
                        "metadata_json": None,
                    }
                ]
            ),
        )
        self.assertIn(
            '<span class="event-badge">[publication updated]</span>',
            self.admin_session._render_admin_audit_events(
                [
                    {
                        "attachment_id": 1,
                        "event_type": "attachment_publication_updated",
                        "actor": "admin",
                        "occurred_at": "2026-06-04T16:45:00Z",
                        "record_version": 1,
                        "request_id": "req-publication",
                        "metadata_json": None,
                    }
                ]
            ),
        )
        self.assertIn(
            '<span class="event-badge">[visibility updated]</span>',
            self.admin_session._render_admin_audit_events(
                [
                    {
                        "attachment_id": 1,
                        "event_type": "attachment_visibility_updated",
                        "actor": "admin",
                        "occurred_at": "2026-06-04T16:50:00Z",
                        "record_version": 1,
                        "request_id": "req-visibility",
                        "metadata_json": None,
                    }
                ]
            ),
        )
        self.assertIn(
            '<span class="event-badge">[relationship added]</span>',
            content,
        )
        self.assertIn(
            '<span class="event-badge">[synthetic verification]</span>',
            content,
        )
        self.assertIn(
            '<span class="event-badge">[audit event]</span>',
            content,
        )
        self.assertIn(
            '<span class="summary-title">attachment_metadata_corrected</span>',
            content,
        )
        self.assertIn(
            '<span class="summary-meta">Attachment 11 • admin • 2026-06-04 16:00 UTC</span>',
            content,
        )
        self.assertIn(
            '<span class="summary-title">synthetic_audit_verification</span>',
            content,
        )
        self.assertIn(
            '<span class="summary-meta">admin • 2026-06-04 11:32 UTC</span>',
            content,
        )
        self.assertIn("attachment_visibility_reviewed", content)
        self.assertIn("attachment_created", content)
        self.assertIn("reviewer", content)
        self.assertIn("Attachment ID", content)
        self.assertIn(">9<", content)
        self.assertIn("Request ID", content)
        self.assertIn("req-admin-newer", content)
        self.assertIn("metadata_json", content)
        self.assertIn(
            "Reviewed &lt;script&gt;alert(&#x27;x&#x27;)&lt;/script&gt;", content
        )
        self.assertIn("<script>", content)
        self.assertNotIn("Reviewed <script>alert", content)
        self.assertNotIn("other_record_event", content)
        self.assertNotIn("req-other", content)
        self.assertNotIn("private raw narrative", content)
        self.assertNotIn("private source narrative must stay hidden", content)
        self.assertNotIn("report json must stay hidden", content)
        self.assertIn(
            "Administrative attachment management is controlled in this stage.",
            content,
        )
        self.assertIn(
            "Classification, publication status, and visibility metadata updates are available from this page.",
            content,
        )
        self.assertIn(
            "Temporary admin upload is disabled.",
            content,
        )
        self.assertIn("No public download, public file access, or canonical verification changes are introduced.", content)
        self.assertNotIn("Temporary admin attachment upload", content)
        self.assertNotIn("Temporary admin upload utility for evidence verification.", content)
        self.assertNotIn('class="temporary-upload-form"', content)
        self.assertNotIn('enctype="multipart/form-data"', content)
        self.assertNotIn(
            'action="/api/admin/session/records/Strike-OT-20260604-ADMIN/attachments/temp-upload"',
            content,
        )
        self.assertNotIn('name="record_reference"', content)
        self.assertNotIn('name="target_label"', content)
        self.assertNotIn('name="attachment_title"', content)
        self.assertNotIn('name="file"', content)
        self.assertNotIn('type="file"', content)
        self.assertNotIn("Upload attachment", content)

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
        self.assertIn(
            'href="/admin/records/Strike-OT-20260604-ADMIN/evidence"',
            content,
        )
        self.assertNotIn('class="temporary-upload-form"', content)
        self.assertNotIn("Download attachment", content)
        self.assertNotIn("Edit attachment", content)
        self.assertNotIn("Delete attachment", content)
        self.assertNotIn("Restore attachment", content)
        self.assertNotIn("Withhold attachment", content)
        self.assertNotIn("Publish attachment", content)
        self.assertNotIn("Download attachment", content)

    def test_temporary_admin_attachment_upload_flag_disabled_by_default(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(self.admin_session.admin_temp_upload_enabled())

    def test_temporary_admin_attachment_upload_form_renders_when_enabled(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            conn.close()
            try:
                with self.env(), patch.dict(
                    os.environ,
                    {"ADMIN_TEMP_UPLOAD_ENABLED": "true"},
                    clear=False,
                ):
                    response = self.admin_session.admin_record_attachments_page(
                        "Strike-OT-20260604-ADMIN",
                        self.valid_request(),
                    )
            finally:
                self.admin_session.DB_PATH = original_db_path

        content = response.content
        self.assertIn("Temporary admin attachment upload", content)
        self.assertIn("Temporary admin upload utility for evidence verification.", content)
        self.assertIn('class="temporary-upload-form"', content)
        self.assertIn('enctype="multipart/form-data"', content)
        self.assertIn(
            'action="/api/admin/session/records/Strike-OT-20260604-ADMIN/attachments/temp-upload"',
            content,
        )
        self.assertIn('name="record_reference"', content)
        self.assertIn('name="target_type"', content)
        self.assertIn('name="target_label"', content)
        self.assertIn('name="attachment_title"', content)
        self.assertIn('name="description"', content)
        self.assertIn('name="file"', content)
        self.assertIn('type="file"', content)
        self.assertIn("Upload attachment", content)

    def test_temporary_admin_attachment_upload_post_blocked_when_disabled(self):
        with self.env():
            with self.assertRaises(Exception) as ctx:
                self.admin_session.temporary_admin_attachment_upload_route(
                    "Strike-OT-20260604-ADMIN",
                    self.valid_request(),
                    record_reference="Strike-OT-20260604-ADMIN",
                    target_type="condition",
                    target_label="Escalation Without Response",
                    attachment_title="Blocked upload",
                    description=None,
                    file=FakeUploadFile(b"blocked"),
                )

        self.assertEqual(getattr(ctx.exception, "status_code", None), 404)
        self.assertEqual(getattr(ctx.exception, "detail", None), "temporary_upload_disabled")

    def test_temporary_admin_attachment_upload_links_target_and_updates_evidence_coverage(self):
        data = b"temporary evidence bytes for escalation without response"
        expected_sha = hashlib.sha256(data).hexdigest()
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            attachment_root = Path(temp_dir) / "attachments"
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            conn.execute(
                """
                UPDATE records
                SET reference = ?,
                    conditions_json = ?,
                    signals_json = ?,
                    finding = ?
                WHERE reference = ?
                """,
                (
                    "Strike-LA-20260710-004",
                    json.dumps(["Escalation Without Response"]),
                    json.dumps(
                        [
                            "No Recurring Transition",
                            "Dominant Resistance",
                            "Partial Institutional Response",
                            "Administrative Delay Pattern",
                        ]
                    ),
                    "Trajectory recorded as Stable",
                    "Strike-OT-20260604-ADMIN",
                ),
            )
            before_hash = conn.execute(
                "SELECT verification_hash FROM records WHERE reference = ?",
                ("Strike-LA-20260710-004",),
            ).fetchone()["verification_hash"]
            conn.commit()
            conn.close()

            try:
                with self.env(), patch.dict(
                    os.environ,
                    {
                        "ADMIN_TEMP_UPLOAD_ENABLED": "true",
                        "CDE_ATTACHMENT_ROOT": str(attachment_root),
                    },
                    clear=False,
                ):
                    before_response = self.admin_session.admin_record_evidence_page(
                        "Strike-LA-20260710-004",
                        self.valid_request(),
                    )
                    upload_response = (
                        self.admin_session.temporary_admin_attachment_upload_route(
                            "Strike-LA-20260710-004",
                            self.valid_request(),
                            record_reference="Strike-LA-20260710-004",
                            target_type="condition",
                            target_label="Escalation Without Response",
                            attachment_title="Test evidence — escalation without response",
                            description="Temporary verification upload",
                            file=FakeUploadFile(
                                data,
                                filename="escalation-evidence.txt",
                                content_type="text/plain",
                            ),
                        )
                    )
                    after_response = self.admin_session.admin_record_evidence_page(
                        "Strike-LA-20260710-004",
                        self.valid_request(),
                    )

                conn = sqlite3.connect(self.admin_session.DB_PATH)
                conn.row_factory = sqlite3.Row
                try:
                    attachment = conn.execute(
                        "SELECT * FROM record_attachments WHERE reference = ?",
                        ("Strike-LA-20260710-004",),
                    ).fetchone()
                    relationship = conn.execute(
                        """
                        SELECT * FROM record_attachment_relationships
                        WHERE reference = ? AND attachment_id = ?
                        """,
                        ("Strike-LA-20260710-004", attachment["id"]),
                    ).fetchone()
                    after_hash = conn.execute(
                        "SELECT verification_hash FROM records WHERE reference = ?",
                        ("Strike-LA-20260710-004",),
                    ).fetchone()["verification_hash"]
                    stored_file_exists = Path(attachment["storage_path"]).exists()
                finally:
                    conn.close()
            finally:
                self.admin_session.DB_PATH = original_db_path

        self.assertEqual(upload_response.content["ok"], True)
        self.assertEqual(
            upload_response.content["attachment"]["title"],
            "Test evidence — escalation without response",
        )
        self.assertEqual(upload_response.content["attachment"]["sha256_hash"], expected_sha)
        self.assertNotIn("storage_path", upload_response.content["attachment"])
        self.assertNotIn("stored_filename", upload_response.content["attachment"])
        self.assertEqual(attachment["filename"], "escalation-evidence.txt")
        self.assertEqual(attachment["content_type"], "text/plain")
        self.assertEqual(attachment["file_size_bytes"], len(data))
        self.assertEqual(attachment["sha256_hash"], expected_sha)
        self.assertEqual(attachment["classification"], "evidence")
        self.assertEqual(attachment["visibility"], "private")
        self.assertEqual(attachment["publication_status"], "internal")
        self.assertTrue(stored_file_exists)
        self.assertEqual(relationship["relationship_type"], "supports")
        self.assertEqual(relationship["target_type"], "condition")
        self.assertEqual(relationship["target_key"], "Escalation Without Response")
        self.assertEqual(relationship["is_active"], 1)
        self.assertEqual(before_hash, after_hash)

        before_content = before_response.content
        after_content = after_response.content
        self.assertIn("<td>Conditions Supported</td><td>0 / 1</td>", before_content)
        self.assertIn("<td>Overall Coverage</td><td>Unsupported</td>", before_content)
        self.assertIn("Evidence Sufficiency", before_content)
        self.assertIn("<td>Conditions Sufficiency</td><td>Unsupported</td>", before_content)
        self.assertIn("<td>Overall Sufficiency</td><td>Unsupported</td>", before_content)
        self.assertIn("Evidence Completeness", before_content)
        self.assertIn("<td>Conditions Completeness</td><td>Incomplete</td>", before_content)
        self.assertIn("<td>Overall Completeness</td><td>Incomplete</td>", before_content)
        self.assertIn("Evidence Requirements", before_content)
        self.assertIn("<td>Overall Requirement Status</td><td>outstanding</td>", before_content)
        self.assertIn("Evidence Standards", before_content)
        self.assertIn("Current deterministic standard", before_content)
        self.assertIn("Evidence Justification", before_content)
        self.assertIn("Evidence Confidence", before_content)
        self.assertIn("Evidence Traceability", before_content)
        self.assertIn("Evidence Lineage", before_content)
        self.assertIn("Evidence Provenance", before_content)
        self.assertIn("<td>Conditions Supported</td><td>1 / 1</td>", after_content)
        self.assertIn("<td>Overall Coverage</td><td>Partial</td>", after_content)
        self.assertIn("<td>Conditions Sufficiency</td><td>Partial</td>", after_content)
        self.assertIn("<td>Signals Sufficiency</td><td>Unsupported</td>", after_content)
        self.assertIn("<td>Findings Sufficiency</td><td>Unsupported</td>", after_content)
        self.assertIn("<td>Record Sufficiency</td><td>Unsupported</td>", after_content)
        self.assertIn("<td>Overall Sufficiency</td><td>Partial</td>", after_content)
        self.assertIn("<td>Conditions Completeness</td><td>Incomplete</td>", after_content)
        self.assertIn("<td>Signals Completeness</td><td>Incomplete</td>", after_content)
        self.assertIn("<td>Findings Completeness</td><td>Incomplete</td>", after_content)
        self.assertIn("<td>Record Completeness</td><td>Incomplete</td>", after_content)
        self.assertIn("<td>Overall Completeness</td><td>Incomplete</td>", after_content)
        self.assertIn("<td>Complete Targets</td><td>0</td>", after_content)
        self.assertIn("<td>Incomplete Targets</td><td>7</td>", after_content)
        self.assertIn("<td>Completeness Percentage</td><td>0%</td>", after_content)
        self.assertIn("<td>Conditions Requirement Status</td><td>outstanding</td>", after_content)
        self.assertIn("<td>Condition Additional Attachments Required</td><td>1</td>", after_content)
        self.assertIn("<td>Signals Requirement Status</td><td>outstanding</td>", after_content)
        self.assertIn("<td>Signal Additional Attachments Required</td><td>8</td>", after_content)
        self.assertIn("<td>Findings Requirement Status</td><td>outstanding</td>", after_content)
        self.assertIn("<td>Finding Additional Attachments Required</td><td>2</td>", after_content)
        self.assertIn("<td>Record Requirement Status</td><td>outstanding</td>", after_content)
        self.assertIn("<td>Record Additional Attachments Required</td><td>2</td>", after_content)
        self.assertIn("<td>Overall Requirement Status</td><td>outstanding</td>", after_content)
        self.assertIn("<td>Targets Requiring Evidence</td><td>7</td>", after_content)
        self.assertIn("<td>Additional Attachments Required</td><td>13</td>", after_content)
        self.assertIn("Evidence Standards", after_content)
        self.assertIn("<td>Standard Type</td><td>Current deterministic standard</td>", after_content)
        self.assertIn("<td>Minimum for Partial</td><td>1 active supporting attachment</td>", after_content)
        self.assertIn("<td>Minimum for Sufficient</td><td>2 active supporting attachments</td>", after_content)
        self.assertIn("<td>Minimum for Strong</td><td>3 active supporting attachments</td>", after_content)
        self.assertIn("<td>Completion Threshold</td><td>sufficient or strong</td>", after_content)
        self.assertIn(
            "<td>Requirement Basis</td><td>additional attachments required to reach sufficient</td>",
            after_content,
        )
        self.assertIn(
            "<td>Relationship Scope</td><td>active supports relationships only</td>",
            after_content,
        )
        self.assertIn("Unsupported targets require 2 additional supporting attachments.", after_content)
        self.assertIn("Partial targets require 1 additional supporting attachment.", after_content)
        self.assertIn(
            "Sufficient and strong targets require no additional supporting attachments.",
            after_content,
        )
        self.assertIn("Evidence Justification", after_content)
        self.assertIn("<h3>Condition Justification</h3>", after_content)
        self.assertIn("<h3>Signal Justification</h3>", after_content)
        self.assertIn("<h3>Finding Justification</h3>", after_content)
        self.assertIn("<h3>Record Justification</h3>", after_content)
        self.assertIn("<td>Active supports</td><td>1</td>", after_content)
        self.assertIn("<td>Sufficiency</td><td>Partial</td>", after_content)
        self.assertIn("<td>Completeness</td><td>Incomplete</td>", after_content)
        self.assertIn("<td>Additional attachments required</td><td>1</td>", after_content)
        self.assertIn(
            "<td>Standard applied</td><td>Partial = 1 active support; Sufficient = 2 active supports</td>",
            after_content,
        )
        self.assertIn(
            "This target is classified as Partial because it has 1 active support. It remains Incomplete because completion requires Sufficient or Strong sufficiency. It requires 1 additional supporting attachment to reach Sufficient.",
            after_content,
        )
        self.assertIn("<td>Active supports</td><td>0</td>", after_content)
        self.assertIn("<td>Sufficiency</td><td>Unsupported</td>", after_content)
        self.assertIn("<td>Additional attachments required</td><td>2</td>", after_content)
        self.assertIn(
            "<td>Standard applied</td><td>Unsupported = 0 active supports; Sufficient = 2 active supports</td>",
            after_content,
        )
        self.assertIn("Evidence Confidence", after_content)
        self.assertIn("<td>Conditions Confidence</td><td>Limited Confidence</td>", after_content)
        self.assertIn("<td>Signals Confidence</td><td>Low Confidence</td>", after_content)
        self.assertIn("<td>Findings Confidence</td><td>Low Confidence</td>", after_content)
        self.assertIn("<td>Record Confidence</td><td>Low Confidence</td>", after_content)
        self.assertIn("<td>Overall Confidence</td><td>Limited Confidence</td>", after_content)
        self.assertIn("<h3>Condition Confidence</h3>", after_content)
        self.assertIn("<h3>Signal Confidence</h3>", after_content)
        self.assertIn("<td>Confidence</td><td>Limited Confidence</td>", after_content)
        self.assertIn("<td>Confidence</td><td>Low Confidence</td>", after_content)
        self.assertIn(
            "<td>Reason</td><td>Target has Partial sufficiency and is not Complete.</td>",
            after_content,
        )
        self.assertIn(
            "<td>Reason</td><td>Target has Unsupported sufficiency and is not Complete.</td>",
            after_content,
        )
        self.assertIn("Evidence Traceability", after_content)
        self.assertIn("<td>Total Traced Targets</td><td>7</td>", after_content)
        self.assertIn("<td>Total Traced Relationships</td><td>1</td>", after_content)
        self.assertIn(
            "<td>Total Supporting Attachments Referenced</td><td>1</td>",
            after_content,
        )
        self.assertIn("<h3>Condition Traceability</h3>", after_content)
        self.assertIn("<h3>Signal Traceability</h3>", after_content)
        self.assertIn("<h3>Finding Traceability</h3>", after_content)
        self.assertIn("<h3>Record Traceability</h3>", after_content)
        self.assertIn("<td>Active supports count</td><td>1</td>", after_content)
        self.assertIn(
            "<td>Supporting attachment titles</td><td>Test evidence — escalation without response</td>",
            after_content,
        )
        self.assertIn("<td>Relationship type(s)</td><td>supports</td>", after_content)
        self.assertIn("<td>Sufficiency state</td><td>Partial</td>", after_content)
        self.assertIn("<td>Completeness state</td><td>Incomplete</td>", after_content)
        self.assertIn("<td>Confidence state</td><td>Limited Confidence</td>", after_content)
        self.assertIn("<td>Active supports count</td><td>0</td>", after_content)
        self.assertIn(
            "<td>Supporting attachment titles</td><td>No supporting attachment titles.</td>",
            after_content,
        )
        self.assertIn(
            "<td>Relationship type(s)</td><td>No active supports relationships.</td>",
            after_content,
        )
        self.assertIn("Evidence Lineage", after_content)
        self.assertIn("Evidence Lineage Summary", after_content)
        self.assertIn("<td>Total Lineage Targets</td><td>7</td>", after_content)
        self.assertIn("<td>Total Relationship Events</td><td>1</td>", after_content)
        self.assertIn("<td>Active Support Relationships</td><td>1</td>", after_content)
        self.assertIn("<td>Inactive / Removed Relationships</td><td>0</td>", after_content)
        self.assertIn("<td>Targets With Lineage</td><td>1</td>", after_content)
        self.assertIn("<td>Targets Without Lineage</td><td>6</td>", after_content)
        self.assertIn("<h3>Condition Lineage</h3>", after_content)
        self.assertIn("<h3>Signal Lineage</h3>", after_content)
        self.assertIn("<h3>Finding Lineage</h3>", after_content)
        self.assertIn("<h3>Record Lineage</h3>", after_content)
        self.assertIn("<td>Total relationship events</td><td>1</td>", after_content)
        self.assertIn("<td>Active support relationships</td><td>1</td>", after_content)
        self.assertIn("<td>Inactive / removed relationships</td><td>0</td>", after_content)
        self.assertIn("<td>First support created at</td><td>", after_content)
        self.assertIn("<td>Latest support created at</td><td>", after_content)
        self.assertIn(
            "<td>Active supporting attachments</td><td>Test evidence — escalation without response</td>",
            after_content,
        )
        self.assertIn("<td>Current sufficiency</td><td>Partial</td>", after_content)
        self.assertIn("<td>Current completeness</td><td>Incomplete</td>", after_content)
        self.assertIn("<td>Current confidence</td><td>Limited Confidence</td>", after_content)
        self.assertIn("<h5>Lineage Events</h5>", after_content)
        self.assertIn("supports relationship created by admin at", after_content)
        self.assertIn("— active — Attachment", after_content)
        self.assertIn("No recorded evidence lineage events.", after_content)
        self.assertIn("Evidence Provenance", after_content)
        self.assertIn("Provenance Summary", after_content)
        self.assertIn("<td>Total Attachments Referenced</td><td>1</td>", after_content)
        self.assertIn(
            "<td>Total Active Support Relationships</td><td>1</td>",
            after_content,
        )
        self.assertIn(
            "<td>Total Provenance Records Available</td><td>1</td>",
            after_content,
        )
        self.assertIn("<td>Attachments With Provenance</td><td>1</td>", after_content)
        self.assertIn("<td>Attachments Missing Provenance</td><td>0</td>", after_content)
        self.assertIn("<h3>Test evidence — escalation without response</h3>", after_content)
        self.assertIn("<td>Attachment ID</td><td>1</td>", after_content)
        self.assertIn(
            "<td>Attachment Title</td><td>Test evidence — escalation without response</td>",
            after_content,
        )
        self.assertIn("<td>Current Status</td><td>active</td>", after_content)
        self.assertIn("<td>Active Relationships</td><td>1</td>", after_content)
        self.assertIn("<td>Supported Targets</td><td>1</td>", after_content)
        self.assertIn("<li>Escalation Without Response</li>", after_content)
        self.assertIn("Relationship Created At", after_content)
        self.assertIn("<td>supports</td>", after_content)
        self.assertIn("<td>active</td>", after_content)
        self.assertIn("Record Dependency", after_content)
        self.assertIn("Dependency Summary", after_content)
        self.assertIn("<td>Total Conditions</td><td>1</td>", after_content)
        self.assertIn("<td>Total Signals</td><td>4</td>", after_content)
        self.assertIn("<td>Total Findings</td><td>1</td>", after_content)
        self.assertIn("<td>Total Record Outputs</td><td>4</td>", after_content)
        self.assertIn("<td>Total Dependency Relationships</td><td>7</td>", after_content)
        self.assertIn("<td>Evidence-Supported Dependencies</td><td>1</td>", after_content)
        self.assertIn("<td>Unsupported Dependencies</td><td>6</td>", after_content)
        self.assertIn("<h3>Condition Dependencies</h3>", after_content)
        self.assertIn("<h3>Signal Dependencies</h3>", after_content)
        self.assertIn("<h3>Finding Dependencies</h3>", after_content)
        self.assertIn("<h3>Record Dependencies</h3>", after_content)
        self.assertIn("<td>Condition</td><td>Escalation Without Response</td>", after_content)
        self.assertIn("<td>Active Supports</td><td>1</td>", after_content)
        self.assertIn("<td>Sufficiency</td><td>Partial</td>", after_content)
        self.assertIn("<td>Completeness</td><td>Incomplete</td>", after_content)
        self.assertIn("<td>Confidence</td><td>Limited Confidence</td>", after_content)
        self.assertIn("<h5>Dependent Outputs</h5>", after_content)
        self.assertIn("<li>Strike-LA-20260710-004</li>", after_content)
        self.assertIn("<li>Trajectory: Stable</li>", after_content)
        self.assertIn("<li>Finding: Trajectory recorded as Stable</li>", after_content)
        self.assertIn("<td>Record Reference</td><td>Strike-LA-20260710-004</td>", after_content)
        self.assertIn("<td>Dependent Conditions</td><td>1</td>", after_content)
        self.assertIn("<td>Dependent Signals</td><td>4</td>", after_content)
        self.assertIn("<td>Dependent Findings</td><td>1</td>", after_content)
        self.assertIn("<td>Current Trajectory</td><td>Stable</td>", after_content)
        self.assertIn("<td>Current Finding</td><td>Trajectory recorded as Stable</td>", after_content)
        self.assertIn("<td>Record Sufficiency</td><td>Unsupported</td>", after_content)
        self.assertIn("<td>Record Completeness</td><td>Incomplete</td>", after_content)
        self.assertIn("<td>Record Confidence</td><td>Low Confidence</td>", after_content)
        self.assertIn("<td>Record Active Supports</td><td>0</td>", after_content)
        self.assertIn("Record Impact", after_content)
        self.assertIn("Impact Summary", after_content)
        self.assertIn("<td>Total Impacted Outputs</td><td>3</td>", after_content)
        self.assertIn(
            "<td>Total Conditions Affecting Outputs</td><td>1</td>",
            after_content,
        )
        self.assertIn(
            "<td>Total Signals Affecting Outputs</td><td>4</td>",
            after_content,
        )
        self.assertIn(
            "<td>Total Findings Affecting Outputs</td><td>1</td>",
            after_content,
        )
        self.assertIn(
            "<td>Evidence-Supported Impacts</td><td>0</td>",
            after_content,
        )
        self.assertIn("<td>Unsupported Impacts</td><td>6</td>", after_content)
        self.assertIn("<h3>Condition Impact</h3>", after_content)
        self.assertIn("<h3>Signal Impact</h3>", after_content)
        self.assertIn("<h3>Finding Impact</h3>", after_content)
        self.assertIn("<h3>Record Impact</h3>", after_content)
        self.assertIn(
            "<td>Impact Classification</td><td>Unsupported Impact</td>",
            after_content,
        )
        self.assertIn("<h5>Impacted Outputs</h5>", after_content)
        self.assertIn("<td>Trajectory</td><td>Stable</td>", after_content)
        self.assertIn(
            "<td>Finding</td><td>Trajectory recorded as Stable</td>",
            after_content,
        )
        self.assertIn("<td>Impacting Conditions</td><td>1</td>", after_content)
        self.assertIn("<td>Impacting Signals</td><td>4</td>", after_content)
        self.assertIn("<td>Impacting Findings</td><td>1</td>", after_content)
        self.assertIn("Record Stability", after_content)
        self.assertIn("Stability Summary", after_content)
        self.assertIn("<td>Total Stability Targets</td><td>6</td>", after_content)
        self.assertIn("<td>Stable Targets</td><td>0</td>", after_content)
        self.assertIn("<td>Limited Stability Targets</td><td>1</td>", after_content)
        self.assertIn("<td>Unstable Targets</td><td>5</td>", after_content)
        self.assertIn(
            "<td>Evidence-Supported Stability Targets</td><td>0</td>",
            after_content,
        )
        self.assertIn(
            "<td>Unsupported Stability Targets</td><td>6</td>",
            after_content,
        )
        self.assertIn("<h3>Condition Stability</h3>", after_content)
        self.assertIn("<h3>Signal Stability</h3>", after_content)
        self.assertIn("<h3>Finding Stability</h3>", after_content)
        self.assertIn("<h3>Record Stability</h3>", after_content)
        self.assertIn(
            "<td>Stability Classification</td><td>Limited Stability</td>",
            after_content,
        )
        self.assertIn(
            "<td>Stability Classification</td><td>Unstable</td>",
            after_content,
        )
        self.assertIn("<h5>Affected Outputs</h5>", after_content)
        self.assertIn("<td>Supporting Conditions</td><td>1</td>", after_content)
        self.assertIn("<td>Supporting Signals</td><td>4</td>", after_content)
        self.assertIn("<td>Supporting Findings</td><td>1</td>", after_content)
        self.assertIn("<td>Record Confidence</td><td>Low Confidence</td>", after_content)
        self.assertIn(
            "<td>Record Stability Classification</td><td>Unstable</td>",
            after_content,
        )
        self.assertIn("Record Reproducibility", after_content)
        self.assertIn("Reproducibility Summary", after_content)
        self.assertIn(
            "<td>Total Reproducibility Targets</td><td>6</td>",
            after_content,
        )
        self.assertIn("<td>Reproducible Targets</td><td>0</td>", after_content)
        self.assertIn(
            "<td>Limited Reproducibility Targets</td><td>1</td>",
            after_content,
        )
        self.assertIn("<td>Non-Reproducible Targets</td><td>5</td>", after_content)
        self.assertIn("<td>Evidence-Supported Targets</td><td>0</td>", after_content)
        self.assertIn("<td>Unsupported Targets</td><td>6</td>", after_content)
        self.assertIn("<h3>Condition Reproducibility</h3>", after_content)
        self.assertIn("<h3>Signal Reproducibility</h3>", after_content)
        self.assertIn("<h3>Finding Reproducibility</h3>", after_content)
        self.assertIn("<h3>Record Reproducibility</h3>", after_content)
        self.assertIn("<td>Stability</td><td>Limited Stability</td>", after_content)
        self.assertIn(
            "<td>Reproducibility Classification</td><td>Limited Reproducibility</td>",
            after_content,
        )
        self.assertIn(
            "<td>Reproducibility Classification</td><td>Non-Reproducible</td>",
            after_content,
        )
        self.assertIn(
            "<td>Record Stability</td><td>Unstable</td>",
            after_content,
        )
        self.assertIn(
            "<td>Record Reproducibility Classification</td><td>Non-Reproducible</td>",
            after_content,
        )
        self.assertIn("Record Integrity", after_content)
        self.assertIn("Integrity Summary", after_content)
        self.assertIn("<td>Total Integrity Targets</td><td>6</td>", after_content)
        self.assertIn("<td>High Integrity Targets</td><td>0</td>", after_content)
        self.assertIn("<td>Limited Integrity Targets</td><td>1</td>", after_content)
        self.assertIn("<td>Compromised Integrity Targets</td><td>5</td>", after_content)
        self.assertIn(
            "<td>Evidence-Supported Integrity Targets</td><td>1</td>",
            after_content,
        )
        self.assertIn("<td>Unsupported Integrity Targets</td><td>5</td>", after_content)
        self.assertIn("<h3>Condition Integrity</h3>", after_content)
        self.assertIn("<h3>Signal Integrity</h3>", after_content)
        self.assertIn("<h3>Finding Integrity</h3>", after_content)
        self.assertIn("<h3>Record Integrity</h3>", after_content)
        self.assertIn(
            "<td>Integrity Classification</td><td>Limited Integrity</td>",
            after_content,
        )
        self.assertIn(
            "<td>Integrity Classification</td><td>Compromised Integrity</td>",
            after_content,
        )
        self.assertIn(
            "<td>Reproducibility</td><td>Limited Reproducibility</td>",
            after_content,
        )
        self.assertIn(
            "<td>Record Reproducibility</td><td>Non-Reproducible</td>",
            after_content,
        )
        self.assertIn(
            "<td>Record Integrity Classification</td><td>Compromised Integrity</td>",
            after_content,
        )
        self.assertIn("Record Governance Summary", after_content)
        self.assertIn("Governance Summary", after_content)
        self.assertIn("<td>Total Governance Layers</td><td>5</td>", after_content)
        self.assertIn("<td>Supported Governance Layers</td><td>0</td>", after_content)
        self.assertIn("<td>Unsupported Governance Layers</td><td>5</td>", after_content)
        self.assertIn("<td>Dependency Classification</td><td>Unsupported</td>", after_content)
        self.assertIn(
            "<td>Impact Classification</td><td>Unsupported Impact</td>",
            after_content,
        )
        self.assertIn("<td>Stability Classification</td><td>Unstable</td>", after_content)
        self.assertIn(
            "<td>Reproducibility Classification</td><td>Non-Reproducible</td>",
            after_content,
        )
        self.assertIn(
            "<td>Integrity Classification</td><td>Compromised Integrity</td>",
            after_content,
        )
        self.assertIn(
            "<td>Governance Classification</td><td>Governance Gap</td>",
            after_content,
        )
        self.assertIn("<h3>Dependency Review</h3>", after_content)
        self.assertIn("<h3>Impact Review</h3>", after_content)
        self.assertIn("<h3>Stability Review</h3>", after_content)
        self.assertIn("<h3>Reproducibility Review</h3>", after_content)
        self.assertIn("<h3>Integrity Review</h3>", after_content)
        self.assertIn("Record Governance Continuity", after_content)
        self.assertIn("Continuity Summary", after_content)
        self.assertIn("<td>Total Continuity Layers</td><td>5</td>", after_content)
        self.assertIn("<td>Continuous Layers</td><td>0</td>", after_content)
        self.assertIn("<td>Partial Continuity Layers</td><td>0</td>", after_content)
        self.assertIn("<td>Discontinuous Layers</td><td>5</td>", after_content)
        self.assertIn(
            "<td>Continuity Classification</td><td>Governance Discontinuity</td>",
            after_content,
        )
        self.assertIn("<h3>Dependency Continuity</h3>", after_content)
        self.assertIn("<h3>Impact Continuity</h3>", after_content)
        self.assertIn("<h3>Stability Continuity</h3>", after_content)
        self.assertIn("<h3>Reproducibility Continuity</h3>", after_content)
        self.assertIn("<h3>Integrity Continuity</h3>", after_content)
        self.assertIn("Record Governance Change Log", after_content)
        self.assertIn("Change Log Summary", after_content)
        self.assertIn("<td>Total Governance Layers</td><td>5</td>", after_content)
        self.assertIn("<td>Active Governance Layers</td><td>5</td>", after_content)
        self.assertIn(
            "<td>Current Governance Classification</td><td>Governance Gap</td>",
            after_content,
        )
        self.assertIn(
            "<td>Current Continuity Classification</td><td>Governance Discontinuity</td>",
            after_content,
        )
        self.assertIn(
            "<td>Governance Change State</td><td>Significant Change</td>",
            after_content,
        )
        self.assertIn("<h3>Dependency Change Review</h3>", after_content)
        self.assertIn("<h3>Impact Change Review</h3>", after_content)
        self.assertIn("<h3>Stability Change Review</h3>", after_content)
        self.assertIn("<h3>Reproducibility Change Review</h3>", after_content)
        self.assertIn("<h3>Integrity Change Review</h3>", after_content)
        self.assertIn("<h3>Governance Change Review</h3>", after_content)
        self.assertIn("Record Governance Trajectory", after_content)
        self.assertIn("Trajectory Summary", after_content)
        self.assertIn("<td>Total Trajectory Layers</td><td>6</td>", after_content)
        self.assertIn("<td>Progression Layers</td><td>0</td>", after_content)
        self.assertIn("<td>Persistent Layers</td><td>0</td>", after_content)
        self.assertIn("<td>Regression Layers</td><td>6</td>", after_content)
        self.assertIn(
            "<td>Governance Trajectory</td><td>Governance Regression</td>",
            after_content,
        )
        self.assertIn("<h3>Dependency Trajectory</h3>", after_content)
        self.assertIn("<h3>Impact Trajectory</h3>", after_content)
        self.assertIn("<h3>Stability Trajectory</h3>", after_content)
        self.assertIn("<h3>Reproducibility Trajectory</h3>", after_content)
        self.assertIn("<h3>Integrity Trajectory</h3>", after_content)
        self.assertIn("<h3>Governance Trajectory Review</h3>", after_content)
        self.assertIn(
            "This target is classified as Unsupported because it has 0 active supports. It remains Incomplete because completion requires Sufficient or Strong sufficiency. It requires 2 additional supporting attachments to reach Sufficient.",
            after_content,
        )
        self.assertIn(
            "Escalation Without Response — Partial — 1 supporting attachment",
            after_content,
        )
        self.assertIn(
            "Escalation Without Response — Incomplete — Partial sufficiency — 1 supporting attachment",
            after_content,
        )
        self.assertIn(
            "No Recurring Transition — Incomplete — Unsupported sufficiency — 0 supporting attachments",
            after_content,
        )
        self.assertIn(
            "Trajectory recorded as Stable — Incomplete — Unsupported sufficiency — 0 supporting attachments",
            after_content,
        )
        self.assertIn(
            "Strike-LA-20260710-004 — Incomplete — Unsupported sufficiency — 0 supporting attachments",
            after_content,
        )
        self.assertIn(
            "Escalation Without Response — 1 additional supporting attachment required to reach sufficient",
            after_content,
        )
        self.assertIn(
            "No Recurring Transition — 2 additional supporting attachments required to reach sufficient",
            after_content,
        )
        self.assertIn(
            "Dominant Resistance — 2 additional supporting attachments required to reach sufficient",
            after_content,
        )
        self.assertIn(
            "Partial Institutional Response — 2 additional supporting attachments required to reach sufficient",
            after_content,
        )
        self.assertIn(
            "Administrative Delay Pattern — 2 additional supporting attachments required to reach sufficient",
            after_content,
        )
        self.assertIn(
            "Trajectory recorded as Stable — 2 additional supporting attachments required to reach sufficient",
            after_content,
        )
        self.assertIn(
            "Strike-LA-20260710-004 — 2 additional supporting attachments required to reach sufficient",
            after_content,
        )
        self.assertIn("Test evidence — escalation without response", after_content)
        self.assertIn("Escalation Without Response", after_content)
        self.assertNotIn("storage_path", after_content)
        self.assertNotIn("stored_filename", after_content)
        self.assertNotIn("Download attachment", after_content)
        self.assertNotIn("Upload attachment", after_content)

    def test_temporary_admin_attachment_upload_adds_no_public_download_route(self):
        source = Path("api/routes/admin_session.py").read_text(encoding="utf-8")

        self.assertIn(
            '"/api/admin/session/records/{reference}/attachments/temp-upload"',
            source,
        )
        self.assertNotIn("/attachments/{attachment_id}/download", source)
        self.assertNotIn("download_attachment", source)

    def test_admin_record_evidence_view_groups_supporting_attachments_safely(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            self.insert_admin_attachment(
                conn,
                title="Condition evidence",
                classification="evidence",
                publication_status="published",
                visibility="public",
                sha256_hash="a" * 64,
            )
            self.insert_admin_attachment(
                conn,
                title="Signal and finding evidence",
                filename="signal.pdf",
                stored_filename="internal-signal.pdf",
                storage_path="/private/path/internal-signal.pdf",
                classification="research",
                publication_status="internal",
                visibility="private",
                sha256_hash="b" * 64,
            )
            self.insert_admin_attachment(
                conn,
                title="Deleted linked evidence",
                filename="deleted-linked.pdf",
                stored_filename="internal-deleted-linked.pdf",
                storage_path="/private/path/internal-deleted-linked.pdf",
                is_deleted=1,
                sha256_hash="e" * 64,
            )
            attachment_ids = [
                row["id"]
                for row in conn.execute(
                    "SELECT id FROM record_attachments ORDER BY id"
                ).fetchall()
            ]
            condition_attachment_id = attachment_ids[0]
            signal_attachment_id = attachment_ids[1]
            deleted_attachment_id = attachment_ids[2]
            self.insert_attachment_relationship(
                conn,
                attachment_id=condition_attachment_id,
                target_type="condition",
                target_key="INSTITUTIONAL_DELAY",
            )
            self.insert_attachment_relationship(
                conn,
                attachment_id=condition_attachment_id,
                target_type="condition",
                target_key="INSTITUTIONAL_DELAY",
            )
            self.insert_attachment_relationship(
                conn,
                attachment_id=condition_attachment_id,
                relationship_type="context_for",
                target_type="record",
                target_key="Strike-OT-20260604-ADMIN",
            )
            self.insert_attachment_relationship(
                conn,
                attachment_id=signal_attachment_id,
                target_type="signal",
                target_key="Missing Response",
            )
            self.insert_attachment_relationship(
                conn,
                attachment_id=condition_attachment_id,
                target_type="signal",
                target_key="Missing Response",
            )
            self.insert_attachment_relationship(
                conn,
                attachment_id=signal_attachment_id,
                relationship_type="context_for",
                target_type="finding",
                target_key="Finding <requires> review",
            )
            self.insert_attachment_relationship(
                conn,
                attachment_id=deleted_attachment_id,
                target_type="condition",
                target_key="PROCEDURAL_DEFLECTION",
            )
            self.insert_attachment_relationship(
                conn,
                attachment_id=condition_attachment_id,
                target_type="condition",
                target_key="Escalation Without Response",
                is_active=0,
            )
            before_manifest = public_evidence_manifest_attachments(
                conn,
                reference="Strike-OT-20260604-ADMIN",
                record_version=1,
            )
            conn.close()
            try:
                with self.env():
                    response = self.admin_session.admin_record_evidence_page(
                        "Strike-OT-20260604-ADMIN",
                        self.valid_request(),
                    )
                conn = sqlite3.connect(self.admin_session.DB_PATH)
                conn.row_factory = sqlite3.Row
                try:
                    after_manifest = public_evidence_manifest_attachments(
                        conn,
                        reference="Strike-OT-20260604-ADMIN",
                        record_version=1,
                    )
                finally:
                    conn.close()
            finally:
                self.admin_session.DB_PATH = original_db_path

        content = response.content

        self.assertIn("Admin Record Evidence", content)
        self.assertIn('class="admin-watermark print-watermark"', content)
        self.assertIn('aria-hidden="true"', content)
        self.assertIn("print-color-adjust: exact", content)
        self.assertIn(">v12</text>", content)
        self.assertIn("details {", content)
        self.assertIn("<details", content)
        self.assertIn("<summary>", content)
        self.assertIn("break-inside: avoid", content)
        self.assertIn("details:not([open]) > *:not(summary)", content)
        self.assertIn("Evidence Assessment", content)
        self.assertIn("Administrative Workflow", content)
        self.assertIn("Review Status", content)
        self.assertIn("Implementation Path", content)
        self.assertIn("Outcome Detail", content)
        self.assertIn("Supporting Evidence", content)
        self.assertIn(
            "Stage 7F evidence sufficiency and Stage 7G evidence readiness.",
            content,
        )
        self.assertIn(
            "Stage 8A through Stage 8E administrative workflow reasoning.",
            content,
        )
        self.assertIn(
            "Stage 9A through Stage 9D review classification and preconditions.",
            content,
        )
        self.assertIn(
            "Stage 10A implementation action and Stage 10B implementation basis.",
            content,
        )
        self.assertIn(
            "Stage 11B through Stage 11D outcome basis, preconditions, and summary.",
            content,
        )
        self.assertIn("Evidence by record target", content)
        self.assertIn("Record Evidence Coverage", content)
        self.assertIn("<td>Conditions Supported</td><td>1 / 5</td>", content)
        self.assertIn("<td>Signals Supported</td><td>1 / 2</td>", content)
        self.assertIn("<td>Findings Supported</td><td>1 / 1</td>", content)
        self.assertIn("<td>Record Supported</td><td>1 / 1</td>", content)
        self.assertIn("<td>Overall Coverage</td><td>Partial</td>", content)
        self.assertIn("Evidence Sufficiency", content)
        self.assertIn("<td>Conditions Sufficiency</td><td>Partial</td>", content)
        self.assertIn("<td>Signals Sufficiency</td><td>Partial</td>", content)
        self.assertIn("<td>Findings Sufficiency</td><td>Unsupported</td>", content)
        self.assertIn("<td>Record Sufficiency</td><td>Unsupported</td>", content)
        self.assertIn("<td>Overall Sufficiency</td><td>Partial</td>", content)
        self.assertIn("Evidence Completeness", content)
        self.assertIn("<td>Conditions Completeness</td><td>Partial</td>", content)
        self.assertIn("<td>Signals Completeness</td><td>Partial</td>", content)
        self.assertIn("<td>Findings Completeness</td><td>Incomplete</td>", content)
        self.assertIn("<td>Record Completeness</td><td>Incomplete</td>", content)
        self.assertIn("<td>Overall Completeness</td><td>Partial</td>", content)
        self.assertIn("<td>Complete Targets</td><td>2</td>", content)
        self.assertIn("<td>Incomplete Targets</td><td>7</td>", content)
        self.assertIn("<td>Completeness Percentage</td><td>22.2%</td>", content)
        self.assertIn("Evidence Requirements", content)
        self.assertIn("<td>Conditions Requirement Status</td><td>outstanding</td>", content)
        self.assertIn("<td>Condition Additional Attachments Required</td><td>8</td>", content)
        self.assertIn("<td>Signals Requirement Status</td><td>outstanding</td>", content)
        self.assertIn("<td>Signal Additional Attachments Required</td><td>2</td>", content)
        self.assertIn("<td>Findings Requirement Status</td><td>outstanding</td>", content)
        self.assertIn("<td>Finding Additional Attachments Required</td><td>2</td>", content)
        self.assertIn("<td>Record Requirement Status</td><td>outstanding</td>", content)
        self.assertIn("<td>Record Additional Attachments Required</td><td>2</td>", content)
        self.assertIn("<td>Overall Requirement Status</td><td>outstanding</td>", content)
        self.assertIn("<td>Targets Requiring Evidence</td><td>7</td>", content)
        self.assertIn("<td>Additional Attachments Required</td><td>14</td>", content)
        self.assertIn("Evidence Standards", content)
        self.assertIn("<td>Standard Type</td><td>Current deterministic standard</td>", content)
        self.assertIn("<td>Minimum for Partial</td><td>1 active supporting attachment</td>", content)
        self.assertIn("<td>Minimum for Sufficient</td><td>2 active supporting attachments</td>", content)
        self.assertIn("<td>Minimum for Strong</td><td>3 active supporting attachments</td>", content)
        self.assertIn("<td>Completion Threshold</td><td>sufficient or strong</td>", content)
        self.assertIn(
            "<td>Requirement Basis</td><td>additional attachments required to reach sufficient</td>",
            content,
        )
        self.assertIn(
            "<td>Relationship Scope</td><td>active supports relationships only</td>",
            content,
        )
        self.assertIn("Evidence Justification", content)
        self.assertIn("<td>Sufficiency</td><td>Sufficient</td>", content)
        self.assertIn("<td>Completeness</td><td>Complete</td>", content)
        self.assertIn("<td>Additional attachments required</td><td>0</td>", content)
        self.assertIn(
            "<td>Standard applied</td><td>Sufficient = 2 active supports</td>",
            content,
        )
        self.assertIn(
            "This target is classified as Sufficient because it has 2 active supports. It is Complete because completion requires Sufficient or Strong sufficiency. No additional supporting attachments are required.",
            content,
        )
        self.assertIn("Evidence Confidence", content)
        self.assertIn("<td>Conditions Confidence</td><td>Limited Confidence</td>", content)
        self.assertIn("<td>Signals Confidence</td><td>Limited Confidence</td>", content)
        self.assertIn("<td>Findings Confidence</td><td>Low Confidence</td>", content)
        self.assertIn("<td>Record Confidence</td><td>Low Confidence</td>", content)
        self.assertIn("<td>Overall Confidence</td><td>Limited Confidence</td>", content)
        self.assertIn(
            "<td>Reason</td><td>Target has Sufficient sufficiency and meets the completion threshold.</td>",
            content,
        )
        self.assertIn(
            "<td>Reason</td><td>Target has Unsupported sufficiency and is not Complete.</td>",
            content,
        )
        self.assertIn("Evidence Traceability", content)
        self.assertIn("<td>Total Traced Targets</td><td>9</td>", content)
        self.assertIn("<td>Total Traced Relationships</td><td>4</td>", content)
        self.assertIn(
            "<td>Total Supporting Attachments Referenced</td><td>2</td>",
            content,
        )
        self.assertIn("<h3>Condition Traceability</h3>", content)
        self.assertIn("<h3>Signal Traceability</h3>", content)
        self.assertIn("<h3>Finding Traceability</h3>", content)
        self.assertIn("<h3>Record Traceability</h3>", content)
        self.assertIn("<h4>Institutional Delay</h4>", content)
        self.assertIn("<td>Active supports count</td><td>2</td>", content)
        self.assertIn(
            "<td>Supporting attachment titles</td><td>Condition evidence</td>",
            content,
        )
        self.assertIn("<td>Relationship type(s)</td><td>supports</td>", content)
        self.assertIn("<td>Sufficiency state</td><td>Sufficient</td>", content)
        self.assertIn("<td>Completeness state</td><td>Complete</td>", content)
        self.assertIn("<td>Confidence state</td><td>High Confidence</td>", content)
        self.assertIn(
            "<td>Justification summary</td><td>This target is classified as Sufficient because it has 2 active supports. It is Complete because completion requires Sufficient or Strong sufficiency. No additional supporting attachments are required.</td>",
            content,
        )
        self.assertIn("<h4>Procedural Deflection</h4>", content)
        self.assertIn("<td>Active supports count</td><td>0</td>", content)
        self.assertIn(
            "<td>Supporting attachment titles</td><td>No supporting attachment titles.</td>",
            content,
        )
        self.assertIn(
            "<td>Relationship type(s)</td><td>No active supports relationships.</td>",
            content,
        )
        self.assertIn("<td>Sufficiency state</td><td>Unsupported</td>", content)
        self.assertIn("<td>Completeness state</td><td>Incomplete</td>", content)
        self.assertIn("<td>Confidence state</td><td>Low Confidence</td>", content)
        self.assertIn(
            "<td>Supporting attachment titles</td><td>Condition evidence, Signal and finding evidence</td>",
            content,
        )
        traceability_content = content[
            content.index("<h2>Evidence Traceability</h2>") :
        ]
        self.assertNotIn("Deleted linked evidence", traceability_content)
        self.assertNotIn("context_for", traceability_content)
        self.assertIn("Evidence Lineage", content)
        self.assertIn("Evidence Lineage Summary", content)
        self.assertIn("<td>Total Lineage Targets</td><td>9</td>", content)
        self.assertIn("<td>Total Relationship Events</td><td>5</td>", content)
        self.assertIn("<td>Active Support Relationships</td><td>4</td>", content)
        self.assertIn("<td>Inactive / Removed Relationships</td><td>1</td>", content)
        self.assertIn("<td>Targets With Lineage</td><td>3</td>", content)
        self.assertIn("<td>Targets Without Lineage</td><td>6</td>", content)
        self.assertIn("<h3>Condition Lineage</h3>", content)
        self.assertIn("<h3>Signal Lineage</h3>", content)
        self.assertIn("<h3>Finding Lineage</h3>", content)
        self.assertIn("<h3>Record Lineage</h3>", content)
        self.assertIn("<td>Total relationship events</td><td>2</td>", content)
        self.assertIn("<td>Active support relationships</td><td>2</td>", content)
        self.assertIn("<td>Inactive / removed relationships</td><td>0</td>", content)
        self.assertIn(
            "<td>First support created at</td><td>2026-06-04T13:30:00Z</td>",
            content,
        )
        self.assertIn(
            "<td>Latest support created at</td><td>2026-06-04T13:30:00Z</td>",
            content,
        )
        self.assertIn(
            "<td>Active supporting attachments</td><td>Condition evidence</td>",
            content,
        )
        self.assertIn("<td>Current sufficiency</td><td>Sufficient</td>", content)
        self.assertIn("<td>Current completeness</td><td>Complete</td>", content)
        self.assertIn("<td>Current confidence</td><td>High Confidence</td>", content)
        self.assertIn("<td>Total relationship events</td><td>0</td>", content)
        self.assertIn("<td>First support created at</td><td>Not recorded</td>", content)
        self.assertIn(
            "<td>Active supporting attachments</td><td>No active supporting attachments.</td>",
            content,
        )
        self.assertIn("No recorded evidence lineage events.", content)
        self.assertIn(
            "supports relationship created by admin at 2026-06-04T13:30:00Z — active — Attachment 1: Condition evidence",
            content,
        )
        self.assertIn(
            "supports relationship created by admin at 2026-06-04T13:30:00Z — removed — Attachment 1: Condition evidence",
            content,
        )
        lineage_content = content[content.index("<h2>Evidence Lineage</h2>") :]
        self.assertNotIn("Deleted linked evidence", lineage_content)
        self.assertNotIn("context_for", lineage_content)
        self.assertIn("Evidence Provenance", content)
        self.assertIn("Provenance Summary", content)
        self.assertIn("<td>Total Attachments Referenced</td><td>2</td>", content)
        self.assertIn(
            "<td>Total Active Support Relationships</td><td>4</td>",
            content,
        )
        self.assertIn(
            "<td>Total Provenance Records Available</td><td>2</td>",
            content,
        )
        self.assertIn("<td>Attachments With Provenance</td><td>2</td>", content)
        self.assertIn("<td>Attachments Missing Provenance</td><td>0</td>", content)
        self.assertIn("<h3>Condition evidence</h3>", content)
        self.assertIn("<h3>Signal and finding evidence</h3>", content)
        self.assertIn("<td>Attachment ID</td><td>1</td>", content)
        self.assertIn("<td>Attachment Title</td><td>Condition evidence</td>", content)
        self.assertIn("<td>Source Label</td><td>Attachment source</td>", content)
        self.assertIn("<td>Created At</td><td>2026-06-04</td>", content)
        self.assertIn("<td>Uploaded At</td><td>2026-06-04T12:00:00Z</td>", content)
        self.assertIn("<td>Current Status</td><td>active</td>", content)
        self.assertIn("<td>Active Relationships</td><td>3</td>", content)
        self.assertIn("<td>Supported Targets</td><td>2</td>", content)
        self.assertIn("<li>Institutional Delay</li>", content)
        self.assertIn("<li>Missing Response</li>", content)
        self.assertIn("Relationship Created At", content)
        self.assertIn("Relationship Type", content)
        self.assertIn("<td>2026-06-04T13:30:00Z</td>", content)
        self.assertIn("<td>supports</td>", content)
        self.assertIn("<td>active</td>", content)
        provenance_content = content[
            content.index("<h2>Evidence Provenance</h2>") :
        ]
        self.assertNotIn("Deleted linked evidence", provenance_content)
        self.assertNotIn("context_for", provenance_content)
        self.assertIn("Record Dependency", content)
        self.assertIn("Dependency Summary", content)
        self.assertIn("<td>Total Conditions</td><td>5</td>", content)
        self.assertIn("<td>Total Signals</td><td>2</td>", content)
        self.assertIn("<td>Total Findings</td><td>1</td>", content)
        self.assertIn("<td>Total Record Outputs</td><td>4</td>", content)
        self.assertIn("<td>Total Dependency Relationships</td><td>9</td>", content)
        self.assertIn("<td>Evidence-Supported Dependencies</td><td>2</td>", content)
        self.assertIn("<td>Unsupported Dependencies</td><td>7</td>", content)
        self.assertIn("<h3>Condition Dependencies</h3>", content)
        self.assertIn("<h3>Signal Dependencies</h3>", content)
        self.assertIn("<h3>Finding Dependencies</h3>", content)
        self.assertIn("<h3>Record Dependencies</h3>", content)
        self.assertIn("<td>Condition</td><td>Institutional Delay</td>", content)
        self.assertIn("<td>Active Supports</td><td>2</td>", content)
        self.assertIn("<td>Sufficiency</td><td>Sufficient</td>", content)
        self.assertIn("<td>Completeness</td><td>Complete</td>", content)
        self.assertIn("<td>Confidence</td><td>High Confidence</td>", content)
        self.assertIn("<h5>Dependent Outputs</h5>", content)
        self.assertIn("<li>Strike-OT-20260604-ADMIN</li>", content)
        self.assertIn("<li>Trajectory: Stable</li>", content)
        self.assertIn("<li>Finding: Finding &lt;requires&gt; review</li>", content)
        self.assertIn("<td>Record Reference</td><td>Strike-OT-20260604-ADMIN</td>", content)
        self.assertIn("<td>Dependent Conditions</td><td>5</td>", content)
        self.assertIn("<td>Dependent Signals</td><td>2</td>", content)
        self.assertIn("<td>Dependent Findings</td><td>1</td>", content)
        self.assertIn("<td>Current Trajectory</td><td>Stable</td>", content)
        self.assertIn("<td>Current Finding</td><td>Finding &lt;requires&gt; review</td>", content)
        self.assertIn("<td>Record Sufficiency</td><td>Unsupported</td>", content)
        self.assertIn("<td>Record Completeness</td><td>Incomplete</td>", content)
        self.assertIn("<td>Record Confidence</td><td>Low Confidence</td>", content)
        self.assertIn("<td>Record Active Supports</td><td>0</td>", content)
        self.assertIn("Record Impact", content)
        self.assertIn("Impact Summary", content)
        self.assertIn("<td>Total Impacted Outputs</td><td>3</td>", content)
        self.assertIn(
            "<td>Total Conditions Affecting Outputs</td><td>5</td>",
            content,
        )
        self.assertIn(
            "<td>Total Signals Affecting Outputs</td><td>2</td>",
            content,
        )
        self.assertIn(
            "<td>Total Findings Affecting Outputs</td><td>1</td>",
            content,
        )
        self.assertIn("<td>Evidence-Supported Impacts</td><td>2</td>", content)
        self.assertIn("<td>Unsupported Impacts</td><td>6</td>", content)
        self.assertIn("<h3>Condition Impact</h3>", content)
        self.assertIn("<h3>Signal Impact</h3>", content)
        self.assertIn("<h3>Finding Impact</h3>", content)
        self.assertIn("<h3>Record Impact</h3>", content)
        self.assertIn(
            "<td>Impact Classification</td><td>Evidence-Supported Impact</td>",
            content,
        )
        self.assertIn(
            "<td>Impact Classification</td><td>Unsupported Impact</td>",
            content,
        )
        self.assertIn("<h5>Impacted Outputs</h5>", content)
        self.assertIn("<td>Trajectory</td><td>Stable</td>", content)
        self.assertIn("<td>Finding</td><td>Finding &lt;requires&gt; review</td>", content)
        self.assertIn("<td>Impacting Conditions</td><td>5</td>", content)
        self.assertIn("<td>Impacting Signals</td><td>2</td>", content)
        self.assertIn("<td>Impacting Findings</td><td>1</td>", content)
        self.assertIn("Record Stability", content)
        self.assertIn("Stability Summary", content)
        self.assertIn("<td>Total Stability Targets</td><td>8</td>", content)
        self.assertIn("<td>Stable Targets</td><td>2</td>", content)
        self.assertIn("<td>Limited Stability Targets</td><td>0</td>", content)
        self.assertIn("<td>Unstable Targets</td><td>6</td>", content)
        self.assertIn(
            "<td>Evidence-Supported Stability Targets</td><td>2</td>",
            content,
        )
        self.assertIn("<td>Unsupported Stability Targets</td><td>6</td>", content)
        self.assertIn("<h3>Condition Stability</h3>", content)
        self.assertIn("<h3>Signal Stability</h3>", content)
        self.assertIn("<h3>Finding Stability</h3>", content)
        self.assertIn("<h3>Record Stability</h3>", content)
        self.assertIn(
            "<td>Stability Classification</td><td>Stable</td>",
            content,
        )
        self.assertIn(
            "<td>Stability Classification</td><td>Unstable</td>",
            content,
        )
        self.assertIn("<h5>Affected Outputs</h5>", content)
        self.assertIn("<td>Supporting Conditions</td><td>5</td>", content)
        self.assertIn("<td>Supporting Signals</td><td>2</td>", content)
        self.assertIn("<td>Supporting Findings</td><td>1</td>", content)
        self.assertIn("<td>Record Confidence</td><td>Low Confidence</td>", content)
        self.assertIn(
            "<td>Record Stability Classification</td><td>Unstable</td>",
            content,
        )
        self.assertIn("Record Reproducibility", content)
        self.assertIn("Reproducibility Summary", content)
        self.assertIn("<td>Total Reproducibility Targets</td><td>8</td>", content)
        self.assertIn("<td>Reproducible Targets</td><td>2</td>", content)
        self.assertIn(
            "<td>Limited Reproducibility Targets</td><td>0</td>",
            content,
        )
        self.assertIn("<td>Non-Reproducible Targets</td><td>6</td>", content)
        self.assertIn("<td>Evidence-Supported Targets</td><td>2</td>", content)
        self.assertIn("<td>Unsupported Targets</td><td>6</td>", content)
        self.assertIn("<h3>Condition Reproducibility</h3>", content)
        self.assertIn("<h3>Signal Reproducibility</h3>", content)
        self.assertIn("<h3>Finding Reproducibility</h3>", content)
        self.assertIn("<h3>Record Reproducibility</h3>", content)
        self.assertIn("<td>Stability</td><td>Stable</td>", content)
        self.assertIn(
            "<td>Reproducibility Classification</td><td>Reproducible</td>",
            content,
        )
        self.assertIn(
            "<td>Reproducibility Classification</td><td>Non-Reproducible</td>",
            content,
        )
        self.assertIn("<td>Record Stability</td><td>Unstable</td>", content)
        self.assertIn(
            "<td>Record Reproducibility Classification</td><td>Non-Reproducible</td>",
            content,
        )
        self.assertIn("Record Integrity", content)
        self.assertIn("Integrity Summary", content)
        self.assertIn("<td>Total Integrity Targets</td><td>8</td>", content)
        self.assertIn("<td>High Integrity Targets</td><td>2</td>", content)
        self.assertIn("<td>Limited Integrity Targets</td><td>0</td>", content)
        self.assertIn("<td>Compromised Integrity Targets</td><td>6</td>", content)
        self.assertIn(
            "<td>Evidence-Supported Integrity Targets</td><td>2</td>",
            content,
        )
        self.assertIn("<td>Unsupported Integrity Targets</td><td>6</td>", content)
        self.assertIn("<h3>Condition Integrity</h3>", content)
        self.assertIn("<h3>Signal Integrity</h3>", content)
        self.assertIn("<h3>Finding Integrity</h3>", content)
        self.assertIn("<h3>Record Integrity</h3>", content)
        self.assertIn(
            "<td>Integrity Classification</td><td>High Integrity</td>",
            content,
        )
        self.assertIn(
            "<td>Integrity Classification</td><td>Compromised Integrity</td>",
            content,
        )
        self.assertIn("<td>Reproducibility</td><td>Reproducible</td>", content)
        self.assertIn(
            "<td>Record Reproducibility</td><td>Non-Reproducible</td>",
            content,
        )
        self.assertIn(
            "<td>Record Integrity Classification</td><td>Compromised Integrity</td>",
            content,
        )
        self.assertIn("Record Governance Summary", content)
        self.assertIn("Governance Summary", content)
        self.assertIn("<td>Total Governance Layers</td><td>5</td>", content)
        self.assertIn("<td>Supported Governance Layers</td><td>0</td>", content)
        self.assertIn("<td>Unsupported Governance Layers</td><td>5</td>", content)
        self.assertIn("<td>Dependency Classification</td><td>Unsupported</td>", content)
        self.assertIn(
            "<td>Impact Classification</td><td>Unsupported Impact</td>",
            content,
        )
        self.assertIn("<td>Stability Classification</td><td>Unstable</td>", content)
        self.assertIn(
            "<td>Reproducibility Classification</td><td>Non-Reproducible</td>",
            content,
        )
        self.assertIn(
            "<td>Integrity Classification</td><td>Compromised Integrity</td>",
            content,
        )
        self.assertIn(
            "<td>Governance Classification</td><td>Governance Gap</td>",
            content,
        )
        self.assertIn("<h3>Dependency Review</h3>", content)
        self.assertIn("<h3>Impact Review</h3>", content)
        self.assertIn("<h3>Stability Review</h3>", content)
        self.assertIn("<h3>Reproducibility Review</h3>", content)
        self.assertIn("<h3>Integrity Review</h3>", content)
        self.assertIn("Record Governance Continuity", content)
        self.assertIn("Continuity Summary", content)
        self.assertIn("<td>Total Continuity Layers</td><td>5</td>", content)
        self.assertIn("<td>Continuous Layers</td><td>0</td>", content)
        self.assertIn("<td>Partial Continuity Layers</td><td>0</td>", content)
        self.assertIn("<td>Discontinuous Layers</td><td>5</td>", content)
        self.assertIn(
            "<td>Continuity Classification</td><td>Governance Discontinuity</td>",
            content,
        )
        self.assertIn("<h3>Dependency Continuity</h3>", content)
        self.assertIn("<h3>Impact Continuity</h3>", content)
        self.assertIn("<h3>Stability Continuity</h3>", content)
        self.assertIn("<h3>Reproducibility Continuity</h3>", content)
        self.assertIn("<h3>Integrity Continuity</h3>", content)
        self.assertIn("Record Governance Change Log", content)
        self.assertIn("Change Log Summary", content)
        self.assertIn("<td>Total Governance Layers</td><td>5</td>", content)
        self.assertIn("<td>Active Governance Layers</td><td>5</td>", content)
        self.assertIn(
            "<td>Governance Change State</td><td>Significant Change</td>",
            content,
        )
        self.assertIn("<h3>Dependency Change Review</h3>", content)
        self.assertIn("<h3>Impact Change Review</h3>", content)
        self.assertIn("<h3>Stability Change Review</h3>", content)
        self.assertIn("<h3>Reproducibility Change Review</h3>", content)
        self.assertIn("<h3>Integrity Change Review</h3>", content)
        self.assertIn("<h3>Governance Change Review</h3>", content)
        self.assertIn("Record Governance Trajectory", content)
        self.assertIn("Trajectory Summary", content)
        self.assertIn("<td>Total Trajectory Layers</td><td>6</td>", content)
        self.assertIn("<td>Progression Layers</td><td>0</td>", content)
        self.assertIn("<td>Persistent Layers</td><td>0</td>", content)
        self.assertIn("<td>Regression Layers</td><td>6</td>", content)
        self.assertIn(
            "<td>Governance Trajectory</td><td>Governance Regression</td>",
            content,
        )
        self.assertIn("<h3>Dependency Trajectory</h3>", content)
        self.assertIn("<h3>Impact Trajectory</h3>", content)
        self.assertIn("<h3>Stability Trajectory</h3>", content)
        self.assertIn("<h3>Reproducibility Trajectory</h3>", content)
        self.assertIn("<h3>Integrity Trajectory</h3>", content)
        self.assertIn("<h3>Governance Trajectory Review</h3>", content)
        self.assertIn(
            "Institutional Delay — Sufficient — 1 supporting attachment",
            content,
        )
        self.assertIn(
            "Institutional Delay — Complete — Sufficient sufficiency — 1 supporting attachment",
            content,
        )
        self.assertIn(
            "Procedural Deflection — Unsupported — 0 supporting attachments",
            content,
        )
        self.assertIn(
            "Procedural Deflection — Incomplete — Unsupported sufficiency — 0 supporting attachments",
            content,
        )
        self.assertIn(
            "Procedural Deflection — 2 additional supporting attachments required to reach sufficient",
            content,
        )
        self.assertIn(
            "Finding &lt;requires&gt; review — Unsupported — 0 supporting attachments",
            content,
        )
        self.assertIn(
            "Finding &lt;requires&gt; review — Incomplete — Unsupported sufficiency — 0 supporting attachments",
            content,
        )
        self.assertIn(
            "Strike-OT-20260604-ADMIN — Unsupported — 0 supporting attachments",
            content,
        )
        self.assertIn(
            "Strike-OT-20260604-ADMIN — Incomplete — Unsupported sufficiency — 0 supporting attachments",
            content,
        )
        self.assertIn(
            "Strike-OT-20260604-ADMIN — 2 additional supporting attachments required to reach sufficient",
            content,
        )
        self.assertIn("print-admin-section-body", content)
        self.assertIn("Evidence Gap Summary", content)
        self.assertIn("<td>Supported Targets</td><td>4</td>", content)
        self.assertIn("<td>Unsupported Targets</td><td>5</td>", content)
        self.assertIn("<td>Evidence Gap Count</td><td>5</td>", content)
        self.assertIn("<td>Coverage Percentage</td><td>44.4%</td>", content)
        self.assertIn("<td>Condition Gaps</td><td>4</td>", content)
        self.assertIn("<td>Signal Gaps</td><td>1</td>", content)
        self.assertIn("<td>Finding Gaps</td><td>0</td>", content)
        self.assertIn("<td>Record Gaps</td><td>0</td>", content)
        self.assertIn("Outstanding Gaps", content)
        self.assertIn("<li>Signal — Procedural Loop</li>", content)
        self.assertIn("<li>Condition — Procedural Deflection</li>", content)
        self.assertNotIn("<li>Condition — Institutional Delay</li>", content)
        self.assertIn("Stage 7F — Evidence Sufficiency", content)
        self.assertIn('class="stage7f-sufficiency-table"', content)
        self.assertIn('class="target-cell"', content)
        self.assertIn('class="sufficiency-cell"', content)
        self.assertIn(".stage7f-sufficiency-table .target-cell", content)
        self.assertIn(".stage7f-sufficiency-table .sufficiency-cell", content)
        self.assertIn("word-break: normal", content)
        self.assertIn("overflow-wrap: break-word", content)
        self.assertIn("overflow-wrap: normal", content)
        self.assertIn("white-space: nowrap", content)
        self.assertIn("line-height: 1.3", content)
        self.assertIn(".stage7f-sufficiency-table th:nth-child(2) { width: 30%; }", content)
        self.assertIn(".stage7f-sufficiency-table th:nth-child(5) { width: 16%; }", content)
        self.assertIn(
            "Sufficiency is classified deterministically from existing attachment",
            content,
        )
        self.assertIn(
            '<td>Condition</td><td class="target-cell">Institutional Delay</td><td>1</td><td>2</td><td class="sufficiency-cell">Reinforced</td>',
            content,
        )
        self.assertIn(
            '<td>Signal</td><td class="target-cell">Missing Response</td><td>2</td><td>2</td><td class="sufficiency-cell">Corroborated</td>',
            content,
        )
        self.assertIn(
            '<td>Finding</td><td class="target-cell">Finding &lt;requires&gt; review</td><td>1</td><td>1</td><td class="sufficiency-cell">Minimal</td>',
            content,
        )
        self.assertIn(
            '<td>Signal</td><td class="target-cell">Procedural Loop</td><td>0</td><td>0</td><td class="sufficiency-cell">Unsupported</td>',
            content,
        )
        self.assertIn("Stage 7G — Evidence Readiness", content)
        self.assertIn(
            "Readiness is classified deterministically from existing coverage",
            content,
        )
        self.assertIn(
            '<td>Readiness Classification</td><td><span class="readiness-badge readiness-gaps-present">Evidence Gaps Present</span></td>',
            content,
        )
        self.assertIn(".readiness-badge", content)
        self.assertIn(".readiness-ready", content)
        self.assertIn(".readiness-partially-ready", content)
        self.assertIn(".readiness-gaps-present", content)
        self.assertIn(".readiness-unsupported", content)
        self.assertIn(
            "<td>Sufficiency Basis</td><td>5 Unsupported, 2 Minimal, 1 Corroborated, 1 Reinforced</td>",
            content,
        )
        self.assertIn("Stage 8A — Administrative Action", content)
        self.assertIn(
            "Administrative action is classified deterministically from the",
            content,
        )
        self.assertIn(
            '<td>Administrative Action</td><td><span class="admin-action-badge admin-action-resolve-evidence-gaps">Resolve Evidence Gaps</span></td>',
            content,
        )
        self.assertIn(
            "<td>Action Basis</td><td>Administrative action is Resolve Evidence Gaps because unsupported targets or evidence gaps remain.</td>",
            content,
        )
        self.assertIn("Stage 8B — Action Rationale", content)
        self.assertIn(
            "Action rationale is derived deterministically from readiness and",
            content,
        )
        self.assertIn('<ol class="action-rationale-list">', content)
        self.assertIn(
            "<li>Readiness classified as Evidence Gaps Present</li>",
            content,
        )
        self.assertIn("<li>Unsupported targets remain</li>", content)
        self.assertIn("<li>Evidence gaps remain</li>", content)
        self.assertIn(
            "<li>Administrative action classified as Resolve Evidence Gaps</li>",
            content,
        )
        self.assertIn("Stage 8C — Completion Requirements", content)
        self.assertIn(
            "Completion requirements are derived deterministically from the current",
            content,
        )
        self.assertIn('<ol class="completion-requirements-list">', content)
        self.assertIn("<li>Unsupported targets must be resolved.</li>", content)
        self.assertIn("<li>Evidence gaps must be resolved.</li>", content)
        self.assertIn("Stage 8D — Workflow State", content)
        self.assertIn(
            "Workflow state is classified deterministically from readiness and",
            content,
        )
        self.assertIn(
            '<td>Workflow State</td><td><span class="workflow-state-badge workflow-state-evidence-review">Evidence Review</span></td>',
            content,
        )
        self.assertIn(
            "<td>State Description</td><td>Evidence has been collected but gaps remain.</td>",
            content,
        )
        self.assertIn("Stage 8E — Transition Conditions", content)
        self.assertIn(
            "Transition conditions are derived deterministically from workflow",
            content,
        )
        self.assertIn("<td>Transition Target</td><td>Administrative Review</td>", content)
        self.assertIn('<ol class="transition-conditions-list">', content)
        self.assertIn("<li>Unsupported targets must be resolved.</li>", content)
        self.assertIn("<li>Evidence gaps must be resolved.</li>", content)
        self.assertIn(
            "<li>Workflow state may advance to Administrative Review.</li>",
            content,
        )
        self.assertIn("Stage 9A — Administrative Disposition", content)
        self.assertIn(
            "Administrative disposition is classified deterministically from",
            content,
        )
        self.assertIn(
            '<td>Administrative Disposition</td><td><span class="disposition-badge disposition-open">Open</span></td>',
            content,
        )
        self.assertIn(
            "<td>Disposition Description</td><td>The record remains within active evidence workflow.</td>",
            content,
        )
        self.assertIn("Stage 9B — Disposition Basis", content)
        self.assertIn(
            "Disposition basis is derived deterministically from workflow,",
            content,
        )
        self.assertIn('<ol class="disposition-basis-list">', content)
        self.assertIn(
            "<li>Workflow state classified as Evidence Review.</li>",
            content,
        )
        self.assertIn(
            "<li>Readiness classified as Evidence Gaps Present.</li>",
            content,
        )
        self.assertIn(
            "<li>Administrative action classified as Resolve Evidence Gaps.</li>",
            content,
        )
        self.assertIn(
            "<li>Administrative disposition classified as Open.</li>",
            content,
        )
        self.assertIn("Stage 9C — Review Eligibility", content)
        self.assertIn(
            "Review eligibility is classified deterministically from",
            content,
        )
        self.assertIn(
            '<td>Review Eligibility</td><td><span class="eligibility-badge eligibility-not-eligible">Not Eligible</span></td>',
            content,
        )
        self.assertIn(
            "<td>Eligibility Description</td><td>The record has not yet satisfied review requirements.</td>",
            content,
        )
        self.assertIn("Stage 9D — Review Preconditions", content)
        self.assertIn(
            "Review preconditions are derived deterministically from review",
            content,
        )
        self.assertIn(
            "<td>Precondition Target</td><td>Conditionally Eligible</td>",
            content,
        )
        self.assertIn('<ol class="review-preconditions-list">', content)
        self.assertIn(
            "<li>Workflow transition conditions must be satisfied.</li>",
            content,
        )
        self.assertIn(
            "<li>Administrative disposition must advance beyond Open.</li>",
            content,
        )
        self.assertIn(
            "<li>Review eligibility may advance when workflow requirements are satisfied.</li>",
            content,
        )
        self.assertIn("Stage 9E — Administrative Status Summary", content)
        self.assertIn(
            "Administrative status is summarized deterministically from",
            content,
        )
        self.assertIn(
            '<td>Administrative Status</td><td><span class="administrative-status-badge administrative-status-active-review">Active Evidence Review</span></td>',
            content,
        )
        self.assertIn(
            "<td>Status Description</td><td>Evidence remains under review and review eligibility requirements have not yet been satisfied.</td>",
            content,
        )
        self.assertIn("Stage 10A — Implementation Action", content)
        self.assertIn(
            "Implementation action is classified deterministically from",
            content,
        )
        self.assertIn(
            '<td>Implementation Action</td><td><span class="implementation-action-badge implementation-action-none">No Implementation Action</span></td>',
            content,
        )
        self.assertIn(
            "<td>Implementation Description</td><td>No implementation action is available while evidence review remains active.</td>",
            content,
        )
        self.assertIn("Stage 10B — Implementation Basis", content)
        self.assertIn(
            "Implementation basis is derived deterministically from",
            content,
        )
        self.assertIn('<ol class="implementation-basis-list">', content)
        self.assertIn(
            "<li>Administrative status classified as Active Evidence Review.</li>",
            content,
        )
        self.assertIn(
            "<li>Administrative disposition classified as Open.</li>",
            content,
        )
        self.assertIn(
            "<li>Review eligibility classified as Not Eligible.</li>",
            content,
        )
        self.assertIn(
            "<li>Workflow state classified as Evidence Review.</li>",
            content,
        )
        self.assertIn(
            "<li>Readiness classified as Evidence Gaps Present.</li>",
            content,
        )
        self.assertIn(
            "<li>Implementation action classified as No Implementation Action.</li>",
            content,
        )
        self.assertIn("Stage 10C — Effective State", content)
        self.assertIn(
            "Effective state is derived deterministically from implementation",
            content,
        )
        self.assertIn(
            '<td>Effective State</td><td><span class="effective-state-badge effective-state-evidence-review-continues">Evidence Review Continues</span></td>',
            content,
        )
        self.assertIn(
            "<td>Effective Description</td><td>Evidence review remains active and no implementation action has been applied.</td>",
            content,
        )
        self.assertIn("Stage 11A — Outcome Classification", content)
        self.assertIn(
            "Outcome is classified deterministically from effective state values",
            content,
        )
        self.assertIn(
            '<td>Outcome</td><td><span class="outcome-badge outcome-ongoing-review">Ongoing Review</span></td>',
            content,
        )
        self.assertIn(
            "<td>Outcome Description</td><td>The record remains in ongoing review because evidence review continues.</td>",
            content,
        )
        self.assertIn("Stage 11B — Outcome Basis", content)
        self.assertIn(
            "Outcome basis is derived deterministically from outcome, effective",
            content,
        )
        self.assertIn('<ol class="outcome-basis-list">', content)
        self.assertIn(
            "<li>Administrative status classified as Active Evidence Review.</li>",
            content,
        )
        self.assertIn(
            "<li>Implementation action classified as No Implementation Action.</li>",
            content,
        )
        self.assertIn(
            "<li>Effective state classified as Evidence Review Continues.</li>",
            content,
        )
        self.assertIn("<li>Outcome classified as Ongoing Review.</li>", content)
        self.assertIn("Stage 11C — Outcome Preconditions", content)
        self.assertIn(
            "Outcome preconditions are derived deterministically from outcome,",
            content,
        )
        self.assertIn(
            "<td>Precondition Target</td><td>Review Awaiting Determination</td>",
            content,
        )
        self.assertIn('<ol class="outcome-preconditions-list">', content)
        self.assertIn(
            "<li>Review eligibility requirements must be satisfied.</li>",
            content,
        )
        self.assertIn(
            "<li>Administrative disposition must advance beyond Open.</li>",
            content,
        )
        self.assertIn(
            "<li>Implementation action must advance beyond No Implementation Action.</li>",
            content,
        )
        self.assertIn(
            "<li>Effective state may advance when review conditions are satisfied.</li>",
            content,
        )
        self.assertIn("Stage 11D — Outcome Summary", content)
        self.assertIn(
            "Outcome summary is derived deterministically from outcome, effective",
            content,
        )
        self.assertIn("<td>Outcome Summary</td><td>Ongoing Review</td>", content)
        self.assertIn(
            "<td>Summary Description</td><td>The record remains in ongoing review. Evidence review continues, no implementation action has been applied, and outcome advancement depends upon satisfaction of review eligibility and administrative progression requirements.</td>",
            content,
        )
        self.assertIn("Stage 11E — Outcome Readiness", content)
        self.assertIn(
            "Outcome readiness is classified deterministically from outcome,",
            content,
        )
        self.assertIn(
            '<td>Outcome Readiness</td><td><span class="outcome-readiness-badge outcome-readiness-not-ready">Not Ready</span></td>',
            content,
        )
        self.assertIn(
            "<td>Readiness Description</td><td>The outcome cannot advance while review eligibility and administrative progression requirements remain unsatisfied.</td>",
            content,
        )
        self.assertIn("Stage 11F — Outcome Target", content)
        self.assertIn(
            "Outcome target is classified deterministically from outcome, outcome",
            content,
        )
        self.assertIn(
            '<td>Outcome Target</td><td><span class="outcome-target-badge outcome-target-review-awaiting-determination">Review Awaiting Determination</span></td>',
            content,
        )
        self.assertIn(
            "<td>Target Description</td><td>The next target outcome is administrative review awaiting determination once review eligibility and progression requirements are satisfied.</td>",
            content,
        )
        self.assertIn("Stage 12A — Resolution Classification", content)
        self.assertIn(
            "Resolution is classified deterministically from outcome, outcome",
            content,
        )
        self.assertIn(
            '<td>Resolution Classification</td><td><span class="resolution-badge resolution-unresolved">Unresolved</span></td>',
            content,
        )
        self.assertIn(
            "<td>Resolution Description</td><td>The matter remains unresolved because the current outcome has not reached an implemented administrative determination state.</td>",
            content,
        )
        self.assertIn("Stage 12B — Resolution Preconditions", content)
        self.assertIn(
            "Resolution preconditions are derived deterministically from",
            content,
        )
        self.assertIn("<td>Precondition Target</td><td>Conditionally Resolved</td>", content)
        self.assertIn("<h3>Resolution Preconditions</h3>", content)
        self.assertIn(
            "<li>Review eligibility requirements must be satisfied.</li>",
            content,
        )
        self.assertIn(
            "<li>Administrative disposition must advance beyond Open.</li>",
            content,
        )
        self.assertIn(
            "<li>Outcome readiness must advance beyond Not Ready.</li>",
            content,
        )
        self.assertIn(
            "<li>Implementation action must advance beyond No Implementation Action.</li>",
            content,
        )
        self.assertIn(
            "<li>Effective state must advance beyond Evidence Review Continues.</li>",
            content,
        )
        self.assertIn("Stage 12C — Resolution Pathway", content)
        self.assertIn(
            "Resolution pathway identifies the deterministic sequence of",
            content,
        )
        self.assertIn(
            "<td>Resolution Pathway</td><td>REVIEW ELIGIBILITY PENDING</td>",
            content,
        )
        self.assertIn(
            "<td>Pathway Description</td><td>The current matter remains within the review pathway while review eligibility requirements remain pending.</td>",
            content,
        )
        self.assertIn(
            "<td>Resolution Preconditions Target</td><td>Conditionally Resolved</td>",
            content,
        )
        self.assertLess(
            content.index("Stage 12B — Resolution Preconditions"),
            content.index("Stage 12C — Resolution Pathway"),
        )
        self.assertLess(
            content.index("Stage 12C — Resolution Pathway"),
            content.index("Supporting Evidence"),
        )
        self.assertIn("Stage 12D — Resolution Readiness", content)
        self.assertIn(
            "Resolution readiness is classified deterministically from resolution,",
            content,
        )
        self.assertIn(
            '<td>Resolution Readiness</td><td><span class="resolution-readiness-badge resolution-readiness-not-ready">Not Ready</span></td>',
            content,
        )
        self.assertIn(
            "<td>Readiness Description</td><td>Resolution readiness has not been achieved because one or more prerequisite administrative conditions remain outstanding.</td>",
            content,
        )
        self.assertLess(
            content.index("Stage 12C — Resolution Pathway"),
            content.index("Stage 12D — Resolution Readiness"),
        )
        self.assertLess(
            content.index("Stage 12D — Resolution Readiness"),
            content.index("Supporting Evidence"),
        )
        self.assertIn("Stage 12E — Resolution Determination", content)
        self.assertIn(
            "Resolution determination is classified deterministically from",
            content,
        )
        self.assertIn(
            '<td>Resolution Determination</td><td><span class="resolution-determination-badge resolution-determination-not-available">Determination Not Available</span></td>',
            content,
        )
        self.assertIn(
            "<td>Determination Description</td><td>Resolution determination is not available because prerequisite review and readiness conditions remain unsatisfied.</td>",
            content,
        )
        self.assertLess(
            content.index("Stage 12D — Resolution Readiness"),
            content.index("Stage 12E — Resolution Determination"),
        )
        self.assertLess(
            content.index("Stage 12E — Resolution Determination"),
            content.index("Supporting Evidence"),
        )
        self.assertIn("Stage 12F — Resolution Completion", content)
        self.assertIn(
            "Resolution completion is classified deterministically from",
            content,
        )
        self.assertIn(
            '<td>Resolution Completion</td><td><span class="resolution-completion-badge resolution-completion-not-complete">Not Complete</span></td>',
            content,
        )
        self.assertIn(
            "<td>Completion Description</td><td>Resolution completion has not been reached because prerequisite determination and readiness conditions remain unsatisfied.</td>",
            content,
        )
        self.assertLess(
            content.index("Stage 12E — Resolution Determination"),
            content.index("Stage 12F — Resolution Completion"),
        )
        self.assertLess(
            content.index("Stage 12F — Resolution Completion"),
            content.index("Supporting Evidence"),
        )
        self.assertIn("Stage 13A — Closure Classification", content)
        self.assertIn(
            "Closure is classified deterministically from resolution, completion,",
            content,
        )
        self.assertIn(
            '<td>Closure Classification</td><td><span class="closure-badge closure-open">Open</span></td>',
            content,
        )
        self.assertIn(
            "<td>Closure Description</td><td>The matter remains open because resolution completion has not been reached.</td>",
            content,
        )
        self.assertLess(
            content.index("Stage 12F — Resolution Completion"),
            content.index("Stage 13A — Closure Classification"),
        )
        self.assertLess(
            content.index("Stage 13A — Closure Classification"),
            content.index("Supporting Evidence"),
        )
        self.assertIn("Stage 13B — Closure Preconditions", content)
        self.assertIn(
            "Closure preconditions are derived deterministically from closure,",
            content,
        )
        self.assertIn(
            '<td>Closure Preconditions</td><td><span class="closure-precondition-badge closure-outstanding">Closure Preconditions Outstanding</span></td>',
            content,
        )
        self.assertIn(
            "<td>Precondition Description</td><td>Closure requirements remain outstanding and must be satisfied before the matter can advance.</td>",
            content,
        )
        self.assertIn("<h3>Closure Preconditions</h3>", content)
        self.assertIn(
            "<li>Resolution completion must advance beyond Not Complete.</li>",
            content,
        )
        self.assertIn(
            "<li>Resolution determination must become available.</li>",
            content,
        )
        self.assertIn(
            "<li>Resolution readiness must advance beyond Not Ready.</li>",
            content,
        )
        self.assertIn(
            "<li>Administrative review requirements must be satisfied.</li>",
            content,
        )
        self.assertIn(
            "<li>Effective state must advance beyond Evidence Review Continues.</li>",
            content,
        )
        self.assertLess(
            content.index("Stage 13A — Closure Classification"),
            content.index("Stage 13B — Closure Preconditions"),
        )
        self.assertLess(
            content.index("Stage 13B — Closure Preconditions"),
            content.index("Supporting Evidence"),
        )
        self.assertIn("Stage 13C — Closure Pathway", content)
        self.assertIn(
            "Closure pathway identifies the deterministic sequence of",
            content,
        )
        self.assertIn(
            '<td>Closure Pathway</td><td><span class="closure-pathway-badge closure-eligibility-pending">Closure Eligibility Pending</span></td>',
            content,
        )
        self.assertIn(
            "<td>Pathway Description</td><td>The matter remains within the closure pathway while closure eligibility requirements remain outstanding.</td>",
            content,
        )
        self.assertLess(
            content.index("Stage 13B — Closure Preconditions"),
            content.index("Stage 13C — Closure Pathway"),
        )
        self.assertLess(
            content.index("Stage 13C — Closure Pathway"),
            content.index("Supporting Evidence"),
        )
        self.assertIn("Stage 13D — Closure Readiness", content)
        self.assertIn(
            "Closure readiness is classified deterministically from closure,",
            content,
        )
        self.assertIn(
            '<td>Closure Readiness</td><td><span class="closure-readiness-badge closure-readiness-not-ready">Not Ready</span></td>',
            content,
        )
        self.assertIn(
            "<td>Readiness Description</td><td>Closure readiness has not been achieved because one or more prerequisite closure conditions remain outstanding.</td>",
            content,
        )
        self.assertLess(
            content.index("Stage 13C — Closure Pathway"),
            content.index("Stage 13D — Closure Readiness"),
        )
        self.assertLess(
            content.index("Stage 13D — Closure Readiness"),
            content.index("Supporting Evidence"),
        )
        self.assertIn("Stage 13E — Closure Determination", content)
        self.assertIn(
            "Closure determination is classified deterministically from closure,",
            content,
        )
        self.assertIn(
            '<td>Closure Determination</td><td><span class="closure-determination-badge closure-determination-not-available">Determination Not Available</span></td>',
            content,
        )
        self.assertIn(
            "<td>Determination Description</td><td>Closure determination is not available because prerequisite closure conditions remain unsatisfied.</td>",
            content,
        )
        self.assertLess(
            content.index("Stage 13D — Closure Readiness"),
            content.index("Stage 13E — Closure Determination"),
        )
        self.assertLess(
            content.index("Stage 13E — Closure Determination"),
            content.index("Supporting Evidence"),
        )
        self.assertIn("Stage 13F — Closure Completion", content)
        self.assertIn(
            "Closure completion is classified deterministically from closure,",
            content,
        )
        self.assertIn(
            '<td>Closure Completion</td><td><span class="closure-completion-badge closure-completion-not-complete">Not Complete</span></td>',
            content,
        )
        self.assertIn(
            "<td>Completion Description</td><td>Closure completion has not been reached because prerequisite closure determination conditions remain unsatisfied.</td>",
            content,
        )
        self.assertLess(
            content.index("Stage 13E — Closure Determination"),
            content.index("Stage 13F — Closure Completion"),
        )
        self.assertLess(
            content.index("Stage 13F — Closure Completion"),
            content.index("Supporting Evidence"),
        )
        self.assertIn("Stage 14A — Archive Classification", content)
        self.assertIn(
            "Archive classification is determined from closure, resolution,",
            content,
        )
        self.assertIn(
            '<td>Archive Classification</td><td><span class="archive-classification-badge archive-classification-not-archivable">Not Archivable</span></td>',
            content,
        )
        self.assertIn(
            "<td>Description</td><td>Archive classification has not been achieved because closure completion requirements remain unsatisfied.</td>",
            content,
        )
        self.assertLess(
            content.index("Stage 13F — Closure Completion"),
            content.index("Stage 14A — Archive Classification"),
        )
        self.assertLess(
            content.index("Stage 14A — Archive Classification"),
            content.index("Supporting Evidence"),
        )
        self.assertIn("Stage 14B — Archive Preconditions", content)
        self.assertIn(
            "Archive preconditions are derived deterministically from archive,",
            content,
        )
        self.assertIn(
            '<td>Archive Preconditions</td><td><span class="archive-preconditions-badge archive-preconditions-outstanding">Archive Preconditions Outstanding</span></td>',
            content,
        )
        self.assertIn(
            "<td>Description</td><td>Archive requirements remain outstanding and must be satisfied before archive progression can occur.</td>",
            content,
        )
        self.assertIn("<h3>Archive Preconditions</h3>", content)
        self.assertIn(
            "<li>Closure completion must advance beyond Not Complete.</li>",
            content,
        )
        self.assertIn(
            "<li>Closure determination must become available.</li>",
            content,
        )
        self.assertIn(
            "<li>Closure readiness must advance beyond Not Ready.</li>",
            content,
        )
        self.assertIn(
            "<li>Administrative archive requirements must be satisfied.</li>",
            content,
        )
        self.assertIn(
            "<li>Effective state must advance beyond Evidence Review Continues.</li>",
            content,
        )
        self.assertLess(
            content.index("Stage 14A — Archive Classification"),
            content.index("Stage 14B — Archive Preconditions"),
        )
        self.assertLess(
            content.index("Stage 14B — Archive Preconditions"),
            content.index("Supporting Evidence"),
        )
        self.assertIn("Stage 14C — Archive Pathway", content)
        self.assertIn(
            "Archive pathway identifies the deterministic sequence of archive",
            content,
        )
        self.assertIn(
            '<td>Archive Pathway</td><td><span class="archive-pathway-badge archive-pathway-eligibility-pending">Archive Eligibility Pending</span></td>',
            content,
        )
        self.assertIn(
            "<td>Description</td><td>The matter remains within the archive pathway while archive eligibility requirements remain outstanding.</td>",
            content,
        )
        self.assertLess(
            content.index("Stage 14B — Archive Preconditions"),
            content.index("Stage 14C — Archive Pathway"),
        )
        self.assertLess(
            content.index("Stage 14C — Archive Pathway"),
            content.index("Supporting Evidence"),
        )
        self.assertIn("Stage 14D — Archive Readiness", content)
        self.assertIn(
            "Archive readiness is classified deterministically from archive,",
            content,
        )
        self.assertIn(
            '<td>Archive Readiness</td><td><span class="archive-readiness-badge archive-readiness-not-ready">Not Ready</span></td>',
            content,
        )
        self.assertIn(
            "<td>Description</td><td>Archive readiness has not been achieved because one or more prerequisite archive conditions remain outstanding.</td>",
            content,
        )
        self.assertLess(
            content.index("Stage 14C — Archive Pathway"),
            content.index("Stage 14D — Archive Readiness"),
        )
        self.assertLess(
            content.index("Stage 14D — Archive Readiness"),
            content.index("Supporting Evidence"),
        )
        self.assertIn("Stage 14E — Archive Determination", content)
        self.assertIn(
            "Archive determination is classified deterministically from archive,",
            content,
        )
        self.assertIn(
            '<td>Archive Determination</td><td><span class="archive-determination-badge archive-determination-not-available">Determination Not Available</span></td>',
            content,
        )
        self.assertIn(
            "<td>Description</td><td>Archive determination is not available because prerequisite archive conditions remain unsatisfied.</td>",
            content,
        )
        self.assertLess(
            content.index("Stage 14D — Archive Readiness"),
            content.index("Stage 14E — Archive Determination"),
        )
        self.assertLess(
            content.index("Stage 14E — Archive Determination"),
            content.index("Supporting Evidence"),
        )
        self.assertIn("Stage 14F — Archive Completion", content)
        self.assertIn(
            "Archive completion is classified deterministically from archive,",
            content,
        )
        self.assertIn(
            '<td>Archive Completion</td><td><span class="archive-completion-badge archive-completion-not-complete">Not Complete</span></td>',
            content,
        )
        self.assertIn(
            "<td>Description</td><td>Archive completion has not been reached because prerequisite archive determination conditions remain unsatisfied.</td>",
            content,
        )
        self.assertLess(
            content.index("Stage 14E — Archive Determination"),
            content.index("Stage 14F — Archive Completion"),
        )
        self.assertLess(
            content.index("Stage 14F — Archive Completion"),
            content.index("Supporting Evidence"),
        )
        self.assertIn("<details", content)
        self.assertIn("<summary", content)
        self.assertIn("admin-section-group", content)
        self.assertIn(
            'class="admin-section-group evidence-coverage-admin-group" open',
            content,
        )
        self.assertIn(
            'class="admin-section-group archive-analysis-admin-group" open',
            content,
        )
        self.assertIn(
            'class="admin-section-group administrative-workflow-admin-group"',
            content,
        )
        self.assertIn(
            'class="admin-section-group outcome-analysis-admin-group"',
            content,
        )
        self.assertIn(
            'class="admin-section-group resolution-analysis-admin-group"',
            content,
        )
        self.assertIn(
            'class="admin-section-group closure-analysis-admin-group"',
            content,
        )
        self.assertIn(
            'class="admin-section-group supporting-evidence-admin-group"',
            content,
        )
        self.assertIn("Evidence Coverage", content)
        self.assertIn("Administrative Workflow", content)
        self.assertIn("Outcome Analysis — Stages 11A–11F", content)
        self.assertIn("Resolution Analysis — Stages 12A–12F", content)
        self.assertIn("Closure Analysis — Stages 13A–13F", content)
        self.assertIn("Archive Analysis — Stages 14A–14F", content)
        self.assertIn("Supporting Evidence", content)
        self.assertLess(
            content.index("Administrative Workflow"),
            content.index("Outcome Analysis — Stages 11A–11F"),
        )
        self.assertLess(
            content.index("Outcome Analysis — Stages 11A–11F"),
            content.index("Resolution Analysis — Stages 12A–12F"),
        )
        self.assertLess(
            content.index("Resolution Analysis — Stages 12A–12F"),
            content.index("Closure Analysis — Stages 13A–13F"),
        )
        self.assertLess(
            content.index("Closure Analysis — Stages 13A–13F"),
            content.index("Archive Analysis — Stages 14A–14F"),
        )
        self.assertLess(
            content.index("Archive Analysis — Stages 14A–14F"),
            content.index("Supporting Evidence"),
        )
        self.assertLess(
            content.index("Supporting Evidence"),
            content.index("Evidence Coverage"),
        )
        governance_start = content.index(
            'class="admin-section-group evidence-coverage-admin-group"'
        )
        governance_content = content[governance_start:]
        self.assertLess(
            governance_content.index("Evidence Coverage"),
            governance_content.index("<h2>Evidence Sufficiency</h2>"),
        )
        self.assertLess(
            governance_content.index("<h2>Evidence Sufficiency</h2>"),
            governance_content.index("<h2>Evidence Completeness</h2>"),
        )
        self.assertLess(
            governance_content.index("<h2>Evidence Completeness</h2>"),
            governance_content.index("<h2>Evidence Requirements</h2>"),
        )
        self.assertLess(
            governance_content.index("<h2>Evidence Requirements</h2>"),
            governance_content.index("<h2>Evidence Standards</h2>"),
        )
        self.assertLess(
            governance_content.index("<h2>Evidence Standards</h2>"),
            governance_content.index("<h2>Evidence Justification</h2>"),
        )
        self.assertLess(
            governance_content.index("<h2>Evidence Justification</h2>"),
            governance_content.index("<h2>Evidence Confidence</h2>"),
        )
        self.assertLess(
            governance_content.index("<h2>Evidence Confidence</h2>"),
            governance_content.index("<h2>Evidence Traceability</h2>"),
        )
        self.assertLess(
            governance_content.index("<h2>Evidence Traceability</h2>"),
            governance_content.index("<h2>Evidence Lineage</h2>"),
        )
        self.assertLess(
            governance_content.index("<h2>Evidence Lineage</h2>"),
            governance_content.index("<h2>Evidence Provenance</h2>"),
        )
        self.assertLess(
            governance_content.index("<h2>Evidence Provenance</h2>"),
            governance_content.index("<h2>Record Dependency</h2>"),
        )
        self.assertLess(
            governance_content.index("<h2>Record Dependency</h2>"),
            governance_content.index("<h2>Record Impact</h2>"),
        )
        self.assertLess(
            governance_content.index("<h2>Record Impact</h2>"),
            governance_content.index("<h2>Record Stability</h2>"),
        )
        self.assertLess(
            governance_content.index("<h2>Record Stability</h2>"),
            governance_content.index("<h2>Record Reproducibility</h2>"),
        )
        self.assertLess(
            governance_content.index("<h2>Record Reproducibility</h2>"),
            governance_content.index("<h2>Record Integrity</h2>"),
        )
        self.assertLess(
            governance_content.index("<h2>Record Integrity</h2>"),
            governance_content.index("<h2>Record Governance Summary</h2>"),
        )
        self.assertLess(
            governance_content.index("<h2>Record Governance Summary</h2>"),
            governance_content.index("<h2>Record Governance Continuity</h2>"),
        )
        self.assertLess(
            governance_content.index("<h2>Record Governance Continuity</h2>"),
            governance_content.index("<h2>Record Governance Change Log</h2>"),
        )
        self.assertLess(
            governance_content.index("<h2>Record Governance Change Log</h2>"),
            governance_content.index("<h2>Record Governance Trajectory</h2>"),
        )
        self.assertIn(
            "Expand to inspect deterministic administrative reasoning.",
            content,
        )
        self.assertIn(".admin-section-group", content)
        self.assertIn(".admin-section-summary", content)
        self.assertIn(".admin-section-body", content)
        self.assertIn(".admin-section-hint", content)
        self.assertIn(".admin-section-count", content)
        self.assertIn(".print-admin-section-body", content)
        self.assertIn("@media screen", content)
        self.assertIn("@media print", content)
        self.assertIn(
            '<section class="print-admin-section-body archive-analysis-admin-group-print"',
            content,
        )
        self.assertIn(
            '<section class="print-admin-section-body evidence-coverage-admin-group-print"',
            content,
        )
        print_governance_content = content[
            content.index(
                '<section class="print-admin-section-body evidence-coverage-admin-group-print"'
            ) :
        ]
        self.assertIn("<h2>Record Impact</h2>", print_governance_content)
        self.assertIn("<h2>Record Stability</h2>", print_governance_content)
        self.assertIn("<h2>Record Reproducibility</h2>", print_governance_content)
        self.assertIn("<h2>Record Integrity</h2>", print_governance_content)
        self.assertIn("<h2>Record Governance Summary</h2>", print_governance_content)
        self.assertIn(
            "<h2>Record Governance Continuity</h2>",
            print_governance_content,
        )
        self.assertIn(
            "<h2>Record Governance Change Log</h2>",
            print_governance_content,
        )
        self.assertIn(
            "<h2>Record Governance Trajectory</h2>",
            print_governance_content,
        )
        self.assertIn(
            "details.admin-section-group > .admin-section-body",
            content,
        )
        self.assertIn("display: none !important;", content)
        self.assertIn(
            ".print-admin-section-body {\n        display: block !important;",
            content,
        )
        self.assertIn(
            ".admin-section-group:not([open]) > .admin-section-body",
            content,
        )
        for stage in (
            "Stage 12A — Resolution Classification",
            "Stage 12B — Resolution Preconditions",
            "Stage 12C — Resolution Pathway",
            "Stage 12D — Resolution Readiness",
            "Stage 12E — Resolution Determination",
            "Stage 12F — Resolution Completion",
            "Stage 13A — Closure Classification",
            "Stage 13B — Closure Preconditions",
            "Stage 13C — Closure Pathway",
            "Stage 13D — Closure Readiness",
            "Stage 13E — Closure Determination",
            "Stage 13F — Closure Completion",
            "Stage 14A — Archive Classification",
            "Stage 14B — Archive Preconditions",
            "Stage 14C — Archive Pathway",
            "Stage 14D — Archive Readiness",
            "Stage 14E — Archive Determination",
            "Stage 14F — Archive Completion",
        ):
            self.assertIn(stage, content)
        self.assertIn(".resolution-readiness-badge", content)
        self.assertIn(".resolution-readiness-not-ready", content)
        self.assertIn(".resolution-readiness-conditionally-ready", content)
        self.assertIn(".resolution-readiness-ready", content)
        self.assertIn(".resolution-readiness-resolved", content)
        self.assertIn(".resolution-determination-badge", content)
        self.assertIn(".resolution-determination-not-available", content)
        self.assertIn(".resolution-determination-pending", content)
        self.assertIn(".resolution-determination-required", content)
        self.assertIn(".resolution-determination-issued", content)
        self.assertIn(".resolution-determination-complete", content)
        self.assertIn(".resolution-completion-badge", content)
        self.assertIn(".resolution-completion-not-complete", content)
        self.assertIn(".resolution-completion-pending", content)
        self.assertIn(".resolution-completion-required", content)
        self.assertIn(".resolution-completion-confirmed", content)
        self.assertIn(".resolution-completion-failed", content)
        self.assertIn(".closure-badge", content)
        self.assertIn(".closure-open", content)
        self.assertIn(".closure-pending", content)
        self.assertIn(".closure-without-resolution", content)
        self.assertIn(".closure-with-resolution", content)
        self.assertIn(".closure-failed", content)
        self.assertIn(".closure-precondition-badge", content)
        self.assertIn(".closure-ready", content)
        self.assertIn(".closure-conditional", content)
        self.assertIn(".closure-outstanding", content)
        self.assertIn(".closure-blocked", content)
        self.assertIn(".closure-pathway-badge", content)
        self.assertIn(".closure-eligibility-pending", content)
        self.assertIn(".closure-readiness-pending", content)
        self.assertIn(".closure-determination-pending", content)
        self.assertIn(".closure-confirmation-pending", content)
        self.assertIn(".closure-complete", content)
        self.assertIn(".closure-readiness-badge", content)
        self.assertIn(".closure-readiness-ready", content)
        self.assertIn(".closure-readiness-not-ready", content)
        self.assertIn(".closure-determination-badge", content)
        self.assertIn(".closure-determination-not-available", content)
        self.assertIn(".closure-determination-pending", content)
        self.assertIn(".closure-determination-required", content)
        self.assertIn(".closure-determination-issued", content)
        self.assertIn(".closure-determination-complete", content)
        self.assertIn(".closure-completion-badge", content)
        self.assertIn(".closure-completion-not-complete", content)
        self.assertIn(".closure-completion-pending", content)
        self.assertIn(".closure-completion-in-progress", content)
        self.assertIn(".closure-completion-complete", content)
        self.assertIn(".archive-classification-badge", content)
        self.assertIn(".archive-classification-not-archivable", content)
        self.assertIn(".archive-classification-eligible", content)
        self.assertIn(".archive-classification-archived", content)
        self.assertIn(".archive-preconditions-badge", content)
        self.assertIn(".archive-preconditions-outstanding", content)
        self.assertIn(".archive-preconditions-satisfied", content)
        self.assertIn(".archive-pathway-badge", content)
        self.assertIn(".archive-pathway-eligibility-pending", content)
        self.assertIn(".archive-pathway-determination-pending", content)
        self.assertIn(".archive-pathway-ready", content)
        self.assertIn(".archive-pathway-archived", content)
        self.assertIn(".archive-readiness-badge", content)
        self.assertIn(".archive-readiness-not-ready", content)
        self.assertIn(".archive-readiness-ready", content)
        self.assertIn(".archive-readiness-archived", content)
        self.assertIn(".archive-determination-badge", content)
        self.assertIn(".archive-determination-not-available", content)
        self.assertIn(".archive-determination-eligible", content)
        self.assertIn(".archive-determination-archived", content)
        self.assertIn(".archive-completion-badge", content)
        self.assertIn(".archive-completion-not-complete", content)
        self.assertIn(".archive-completion-complete", content)
        self.assertIn(".workflow-state-badge", content)
        self.assertIn(".workflow-state-evidence-collection", content)
        self.assertIn(".workflow-state-evidence-review", content)
        self.assertIn(".workflow-state-administrative-review", content)
        self.assertIn(".workflow-state-formal-review-ready", content)
        self.assertIn(".disposition-badge", content)
        self.assertIn(".disposition-open", content)
        self.assertIn(".disposition-pending-review", content)
        self.assertIn(".disposition-ready-review", content)
        self.assertIn(".eligibility-badge", content)
        self.assertIn(".eligibility-not-eligible", content)
        self.assertIn(".eligibility-conditionally-eligible", content)
        self.assertIn(".eligibility-eligible", content)
        self.assertIn(".administrative-status-badge", content)
        self.assertIn(".administrative-status-active-collection", content)
        self.assertIn(".administrative-status-active-review", content)
        self.assertIn(".administrative-status-pending-review", content)
        self.assertIn(".administrative-status-ready-review", content)
        self.assertIn(".implementation-action-badge", content)
        self.assertIn(".implementation-action-none", content)
        self.assertIn(".implementation-action-await-review", content)
        self.assertIn(".implementation-action-formal-review", content)
        self.assertIn(".effective-state-badge", content)
        self.assertIn(".effective-state-evidence-review-continues", content)
        self.assertIn(".effective-state-administrative-review-pending", content)
        self.assertIn(".effective-state-formal-review-ready", content)
        self.assertIn(".outcome-badge", content)
        self.assertIn(".outcome-ongoing-review", content)
        self.assertIn(".outcome-awaiting-determination", content)
        self.assertIn(".outcome-ready-determination", content)
        self.assertIn(".outcome-readiness-badge", content)
        self.assertIn(".outcome-readiness-not-ready", content)
        self.assertIn(".outcome-readiness-conditionally-ready", content)
        self.assertIn(".outcome-readiness-ready", content)
        self.assertIn(".outcome-target-badge", content)
        self.assertIn(".outcome-target-review-awaiting-determination", content)
        self.assertIn(".outcome-target-ready-for-determination", content)
        self.assertIn(".outcome-target-determination-pending", content)
        self.assertIn(".resolution-badge", content)
        self.assertIn(".resolution-unresolved", content)
        self.assertIn(".resolution-partially-resolved", content)
        self.assertIn(".resolution-conditionally-resolved", content)
        self.assertIn(".resolution-resolved", content)
        self.assertIn(".resolution-failed", content)
        self.assertIn(".admin-action-badge", content)
        self.assertIn(".admin-action-collect-initial-evidence", content)
        self.assertIn(".admin-action-resolve-evidence-gaps", content)
        self.assertIn(".admin-action-proceed-review", content)
        self.assertIn(".admin-action-formal-review", content)
        self.assertIn(
            'class="evidence-section evidence-section-condition" open', content
        )
        self.assertIn('class="evidence-section evidence-section-signal"', content)
        self.assertIn('class="evidence-section evidence-section-finding"', content)
        self.assertIn('class="evidence-section evidence-section-record"', content)
        self.assertIn("Conditions", content)
        self.assertIn("Signals", content)
        self.assertIn("Findings", content)
        self.assertIn("Record", content)
        self.assertIn("Institutional Delay", content)
        self.assertIn("Missing Response", content)
        self.assertIn("Finding &lt;requires&gt; review", content)
        self.assertIn("Strike-OT-20260604-ADMIN", content)
        self.assertIn("Coverage: Supported", content)
        self.assertIn("Coverage: Unsupported", content)
        self.assertIn("Evidence Gap: No", content)
        self.assertIn("Evidence Gap: Yes", content)
        self.assertIn("1 supporting attachment", content)
        self.assertIn("2 supporting relationships", content)
        self.assertIn("0 supporting relationships", content)
        self.assertIn("Relationship Types", content)
        self.assertIn("<li>supports: 2</li>", content)
        self.assertIn("<h5>Relationships</h5>", content)
        self.assertIn("Relationship Trace", content)
        self.assertIn("Relationship Type", content)
        self.assertIn("Target Type", content)
        self.assertIn("Target Key", content)
        self.assertIn("Attachment Identifier", content)
        self.assertIn("Attachment Title", content)
        screen_content = re.sub(
            r'<section class="print-admin-section-body.*?</section>',
            "",
            content,
            flags=re.DOTALL,
        )
        self.assertEqual(
            screen_content.count("supports → condition → Institutional Delay"),
            2,
        )
        self.assertIn("context_for → finding → Finding &lt;requires&gt; review", content)
        self.assertIn("context_for → record → Strike-OT-20260604-ADMIN", content)
        self.assertIn("<dd>supports</dd>", content)
        self.assertIn("<dd>condition</dd>", content)
        self.assertIn("<dd>Institutional Delay</dd>", content)
        self.assertIn("<dd>1</dd>", content)
        self.assertIn("<dd>Condition evidence</dd>", content)
        self.assertIn(
            "<strong>Coverage rationale:</strong> Supported because 2 active attachment relationships support this target.",
            content,
        )
        self.assertIn(
            "<strong>Coverage rationale:</strong> Supported because Attachment 2 supports this target.",
            content,
        )
        self.assertIn(
            "<strong>Gap rationale:</strong> No active attachment relationships support this target.",
            content,
        )
        self.assertIn("Attachment 1 — Condition evidence", content)
        self.assertIn("Attachment 2 — Signal and finding evidence", content)
        self.assertIn("<td>Classification</td><td>evidence</td>", content)
        self.assertIn("<td>Publication status</td><td>published</td>", content)
        self.assertIn("<td>Visibility</td><td>public</td>", content)
        self.assertIn("<td>Redaction status</td><td>none</td>", content)
        self.assertIn("<td>Lifecycle state</td><td>active</td>", content)
        self.assertIn("<td>Document date</td><td>2026-06-04</td>", content)
        self.assertIn("a" * 64, content)
        self.assertIn("No supporting attachments linked.", content)
        self.assertNotIn("Deleted linked evidence", content)
        self.assertNotIn("Attachment 3 — Deleted linked evidence", content)
        self.assertNotIn("supports → condition → Procedural Deflection", content)
        self.assertNotIn("supports → condition → Escalation Without Response", content)
        self.assertNotIn("internal-public.pdf", content)
        self.assertNotIn("internal-signal.pdf", content)
        self.assertNotIn("storage_path", content)
        self.assertNotIn("stored_filename", content)
        self.assertNotIn("/private/path", content)
        self.assertNotIn("file bytes", content)
        self.assertNotIn("source narrative", content.lower())
        self.assertNotIn("report json", content.lower())
        self.assertNotIn("CDE_ADMIN_TOKEN", content)
        self.assertNotIn("server-only-token", content)
        self.assertNotIn("Upload attachment", content)
        self.assertNotIn("Download attachment", content)
        self.assertNotIn("Add relationship", content)
        self.assertNotIn("Remove relationship", content)
        self.assertNotIn("workflow mutation", content.lower())
        self.assertIn(
            'href="/admin/records/Strike-OT-20260604-ADMIN/attachments"',
            content,
        )
        self.assertEqual(before_manifest, after_manifest)

    def test_admin_record_evidence_coverage_unsupported_when_no_targets_linked(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            self.insert_admin_attachment(conn)
            conn.close()
            try:
                with self.env():
                    response = self.admin_session.admin_record_evidence_page(
                        "Strike-OT-20260604-ADMIN",
                        self.valid_request(),
                    )
            finally:
                self.admin_session.DB_PATH = original_db_path

        content = response.content

        self.assertIn("Record Evidence Coverage", content)
        self.assertIn("Evidence Gap Summary", content)
        self.assertIn("<td>Conditions Supported</td><td>0 / 5</td>", content)
        self.assertIn("<td>Signals Supported</td><td>0 / 2</td>", content)
        self.assertIn("<td>Findings Supported</td><td>0 / 1</td>", content)
        self.assertIn("<td>Record Supported</td><td>0 / 1</td>", content)
        self.assertIn("<td>Overall Coverage</td><td>Unsupported</td>", content)
        self.assertIn("<td>Conditions Sufficiency</td><td>Unsupported</td>", content)
        self.assertIn("<td>Signals Sufficiency</td><td>Unsupported</td>", content)
        self.assertIn("<td>Findings Sufficiency</td><td>Unsupported</td>", content)
        self.assertIn("<td>Record Sufficiency</td><td>Unsupported</td>", content)
        self.assertIn("<td>Overall Sufficiency</td><td>Unsupported</td>", content)
        self.assertIn("<td>Conditions Completeness</td><td>Incomplete</td>", content)
        self.assertIn("<td>Signals Completeness</td><td>Incomplete</td>", content)
        self.assertIn("<td>Findings Completeness</td><td>Incomplete</td>", content)
        self.assertIn("<td>Record Completeness</td><td>Incomplete</td>", content)
        self.assertIn("<td>Overall Completeness</td><td>Incomplete</td>", content)
        self.assertIn("<td>Complete Targets</td><td>0</td>", content)
        self.assertIn("<td>Incomplete Targets</td><td>9</td>", content)
        self.assertIn("<td>Completeness Percentage</td><td>0%</td>", content)
        self.assertIn("<td>Overall Requirement Status</td><td>outstanding</td>", content)
        self.assertIn("<td>Targets Requiring Evidence</td><td>9</td>", content)
        self.assertIn("<td>Additional Attachments Required</td><td>18</td>", content)
        self.assertIn("<td>Supported Targets</td><td>0</td>", content)
        self.assertIn("<td>Unsupported Targets</td><td>9</td>", content)
        self.assertIn("<td>Evidence Gap Count</td><td>9</td>", content)
        self.assertIn("<td>Coverage Percentage</td><td>0.0%</td>", content)
        self.assertIn("<td>Condition Gaps</td><td>5</td>", content)
        self.assertIn("<td>Signal Gaps</td><td>2</td>", content)
        self.assertIn("<td>Finding Gaps</td><td>1</td>", content)
        self.assertIn("<td>Record Gaps</td><td>1</td>", content)
        self.assertIn("Stage 7F — Evidence Sufficiency", content)
        self.assertIn(
            '<td>Condition</td><td class="target-cell">Institutional Delay</td><td>0</td><td>0</td><td class="sufficiency-cell">Unsupported</td>',
            content,
        )
        self.assertIn("Stage 7G — Evidence Readiness", content)
        self.assertIn(
            '<td>Readiness Classification</td><td><span class="readiness-badge readiness-unsupported">Unsupported</span></td>',
            content,
        )
        self.assertIn("Stage 8A — Administrative Action", content)
        self.assertIn(
            '<td>Administrative Action</td><td><span class="admin-action-badge admin-action-collect-initial-evidence">Collect Initial Evidence</span></td>',
            content,
        )
        self.assertIn(
            "<td>Action Basis</td><td>Administrative action is Collect Initial Evidence because no targets are currently supported.</td>",
            content,
        )
        self.assertIn("Stage 8B — Action Rationale", content)
        self.assertIn("<li>Readiness classified as Unsupported</li>", content)
        self.assertIn("<li>No supported targets identified</li>", content)
        self.assertIn(
            "<li>Administrative action classified as Collect Initial Evidence</li>",
            content,
        )
        self.assertIn("Stage 8C — Completion Requirements", content)
        self.assertIn(
            "<li>At least one target must become supported.</li>",
            content,
        )
        self.assertIn(
            "<li>Evidence support must be established.</li>",
            content,
        )
        self.assertIn("Stage 8D — Workflow State", content)
        self.assertIn(
            '<td>Workflow State</td><td><span class="workflow-state-badge workflow-state-evidence-collection">Evidence Collection</span></td>',
            content,
        )
        self.assertIn(
            "<td>State Description</td><td>Evidence support is still being established.</td>",
            content,
        )
        self.assertIn("Stage 8E — Transition Conditions", content)
        self.assertIn("<td>Transition Target</td><td>Evidence Review</td>", content)
        self.assertIn(
            "<li>At least one target must become supported.</li>",
            content,
        )
        self.assertIn(
            "<li>Evidence support must be established.</li>",
            content,
        )
        self.assertIn(
            "<li>Workflow state may advance to Evidence Review.</li>",
            content,
        )
        self.assertIn("Stage 9A — Administrative Disposition", content)
        self.assertIn(
            '<td>Administrative Disposition</td><td><span class="disposition-badge disposition-open">Open</span></td>',
            content,
        )
        self.assertIn(
            "<td>Disposition Description</td><td>The record remains within active evidence workflow.</td>",
            content,
        )
        self.assertIn("<td>Sufficiency Basis</td><td>9 Unsupported</td>", content)
        self.assertIn("<li>Signal — Missing Response</li>", content)
        self.assertIn("<li>Signal — Procedural Loop</li>", content)
        self.assertIn("<li>Finding — Finding &lt;requires&gt; review</li>", content)
        self.assertIn("<li>Record — Strike-OT-20260604-ADMIN</li>", content)
        self.assertIn("Coverage: Unsupported", content)
        self.assertIn("Evidence Gap: Yes", content)
        self.assertIn("0 supporting attachments", content)
        self.assertIn("0 supporting relationships", content)
        self.assertIn(
            "<strong>Gap rationale:</strong> No active attachment relationships support this target.",
            content,
        )
        self.assertIn("No active relationship types.", content)
        self.assertNotIn("Relationship Trace", content)

    def test_admin_record_evidence_coverage_complete_when_all_targets_linked(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            conn.execute(
                """
                UPDATE records
                SET conditions_json = ?, signals_json = ?, finding = ?
                WHERE reference = 'Strike-OT-20260604-ADMIN'
                """,
                (
                    json.dumps(["INSTITUTIONAL_DELAY"]),
                    json.dumps(["Missing Response"]),
                    "Finding <requires> review",
                ),
            )
            self.insert_admin_attachment(conn, title="Complete evidence")
            self.insert_attachment_relationship(
                conn,
                target_type="condition",
                target_key="INSTITUTIONAL_DELAY",
            )
            self.insert_attachment_relationship(
                conn,
                target_type="condition",
                target_key="INSTITUTIONAL_DELAY",
            )
            self.insert_attachment_relationship(
                conn,
                target_type="signal",
                target_key="Missing Response",
            )
            self.insert_attachment_relationship(
                conn,
                relationship_type="context_for",
                target_type="finding",
                target_key="Finding <requires> review",
            )
            self.insert_attachment_relationship(
                conn,
                relationship_type="context_for",
                target_type="record",
                target_key="Strike-OT-20260604-ADMIN",
            )
            conn.close()
            try:
                with self.env():
                    response = self.admin_session.admin_record_evidence_page(
                        "Strike-OT-20260604-ADMIN",
                        self.valid_request(),
                    )
            finally:
                self.admin_session.DB_PATH = original_db_path

        content = response.content

        self.assertIn("<td>Conditions Supported</td><td>1 / 1</td>", content)
        self.assertIn("<td>Signals Supported</td><td>1 / 1</td>", content)
        self.assertIn("<td>Findings Supported</td><td>1 / 1</td>", content)
        self.assertIn("<td>Record Supported</td><td>1 / 1</td>", content)
        self.assertIn("<td>Overall Coverage</td><td>Complete</td>", content)
        self.assertIn("<td>Conditions Sufficiency</td><td>Sufficient</td>", content)
        self.assertIn("<td>Signals Sufficiency</td><td>Partial</td>", content)
        self.assertIn("<td>Findings Sufficiency</td><td>Unsupported</td>", content)
        self.assertIn("<td>Record Sufficiency</td><td>Unsupported</td>", content)
        self.assertIn("<td>Overall Sufficiency</td><td>Partial</td>", content)
        self.assertIn("<td>Conditions Completeness</td><td>Complete</td>", content)
        self.assertIn("<td>Signals Completeness</td><td>Incomplete</td>", content)
        self.assertIn("<td>Findings Completeness</td><td>Incomplete</td>", content)
        self.assertIn("<td>Record Completeness</td><td>Incomplete</td>", content)
        self.assertIn("<td>Overall Completeness</td><td>Partial</td>", content)
        self.assertIn("<td>Complete Targets</td><td>1</td>", content)
        self.assertIn("<td>Incomplete Targets</td><td>3</td>", content)
        self.assertIn("<td>Completeness Percentage</td><td>25%</td>", content)
        self.assertIn("<td>Overall Requirement Status</td><td>outstanding</td>", content)
        self.assertIn("<td>Targets Requiring Evidence</td><td>3</td>", content)
        self.assertIn("<td>Additional Attachments Required</td><td>5</td>", content)
        self.assertIn("<td>Supported Targets</td><td>4</td>", content)
        self.assertIn("<td>Unsupported Targets</td><td>0</td>", content)
        self.assertIn("<td>Evidence Gap Count</td><td>0</td>", content)
        self.assertIn("<td>Coverage Percentage</td><td>100.0%</td>", content)
        self.assertIn("<td>Condition Gaps</td><td>0</td>", content)
        self.assertIn("<td>Signal Gaps</td><td>0</td>", content)
        self.assertIn("<td>Finding Gaps</td><td>0</td>", content)
        self.assertIn("<td>Record Gaps</td><td>0</td>", content)
        self.assertIn("Stage 7F — Evidence Sufficiency", content)
        self.assertIn(
            '<td>Condition</td><td class="target-cell">Institutional Delay</td><td>1</td><td>2</td><td class="sufficiency-cell">Reinforced</td>',
            content,
        )
        self.assertIn("Stage 7G — Evidence Readiness", content)
        self.assertIn(
            '<td>Readiness Classification</td><td><span class="readiness-badge readiness-ready">Ready</span></td>',
            content,
        )
        self.assertIn("Stage 8A — Administrative Action", content)
        self.assertIn(
            '<td>Administrative Action</td><td><span class="admin-action-badge admin-action-formal-review">Eligible for Formal Review</span></td>',
            content,
        )
        self.assertIn(
            "<td>Action Basis</td><td>Administrative action is Eligible for Formal Review because the record has no evidence gaps and includes corroborated or reinforced support.</td>",
            content,
        )
        self.assertIn("Stage 8B — Action Rationale", content)
        self.assertIn("<li>Readiness classified as Ready</li>", content)
        self.assertIn("<li>No unsupported targets remain</li>", content)
        self.assertIn("<li>No evidence gaps remain</li>", content)
        self.assertIn(
            "<li>Corroborated or reinforced support identified</li>",
            content,
        )
        self.assertIn(
            "<li>Administrative action classified as Eligible for Formal Review</li>",
            content,
        )
        self.assertIn("Stage 8C — Completion Requirements", content)
        self.assertIn(
            "<li>No additional evidence requirements identified.</li>",
            content,
        )
        self.assertIn("Stage 8D — Workflow State", content)
        self.assertIn(
            '<td>Workflow State</td><td><span class="workflow-state-badge workflow-state-formal-review-ready">Formal Review Ready</span></td>',
            content,
        )
        self.assertIn(
            "<td>State Description</td><td>Evidence requirements have been satisfied for formal review.</td>",
            content,
        )
        self.assertIn("Stage 8E — Transition Conditions", content)
        self.assertIn(
            "<td>Transition Target</td><td>No further workflow state identified</td>",
            content,
        )
        self.assertIn(
            "<li>No additional workflow transition conditions identified.</li>",
            content,
        )
        self.assertIn("Stage 9A — Administrative Disposition", content)
        self.assertIn(
            '<td>Administrative Disposition</td><td><span class="disposition-badge disposition-ready-review">Ready for Review</span></td>',
            content,
        )
        self.assertIn(
            "<td>Disposition Description</td><td>The record satisfies current workflow requirements for formal review.</td>",
            content,
        )
        self.assertIn("Stage 9B — Disposition Basis", content)
        self.assertIn(
            "<li>Workflow state classified as Formal Review Ready.</li>",
            content,
        )
        self.assertIn(
            "<li>Administrative disposition classified as Ready for Review.</li>",
            content,
        )
        self.assertIn("Stage 9C — Review Eligibility", content)
        self.assertIn(
            '<td>Review Eligibility</td><td><span class="eligibility-badge eligibility-eligible">Eligible</span></td>',
            content,
        )
        self.assertIn(
            "<td>Eligibility Description</td><td>The record satisfies current requirements for review.</td>",
            content,
        )
        self.assertIn("Stage 9D — Review Preconditions", content)
        self.assertIn(
            "<td>Precondition Target</td><td>No further review eligibility state identified</td>",
            content,
        )
        self.assertIn(
            "<li>No additional review preconditions identified.</li>",
            content,
        )
        self.assertIn("Stage 9E — Administrative Status Summary", content)
        self.assertIn(
            '<td>Administrative Status</td><td><span class="administrative-status-badge administrative-status-ready-review">Ready for Formal Review</span></td>',
            content,
        )
        self.assertIn(
            "<td>Status Description</td><td>The record satisfies current administrative review requirements.</td>",
            content,
        )
        self.assertIn("Stage 10A — Implementation Action", content)
        self.assertIn(
            '<td>Implementation Action</td><td><span class="implementation-action-badge implementation-action-formal-review">Prepare Formal Review Implementation</span></td>',
            content,
        )
        self.assertIn(
            "<td>Implementation Description</td><td>The record is ready for formal review implementation planning.</td>",
            content,
        )
        self.assertIn("Stage 10B — Implementation Basis", content)
        self.assertIn(
            "<li>Administrative status classified as Ready for Formal Review.</li>",
            content,
        )
        self.assertIn(
            "<li>Implementation action classified as Prepare Formal Review Implementation.</li>",
            content,
        )
        self.assertIn("Stage 10C — Effective State", content)
        self.assertIn(
            '<td>Effective State</td><td><span class="effective-state-badge effective-state-formal-review-ready">Formal Review Ready</span></td>',
            content,
        )
        self.assertIn(
            "<td>Effective Description</td><td>The record is ready for formal review implementation planning.</td>",
            content,
        )
        self.assertIn("Stage 11A — Outcome Classification", content)
        self.assertIn(
            '<td>Outcome</td><td><span class="outcome-badge outcome-ready-determination">Ready For Determination</span></td>',
            content,
        )
        self.assertIn(
            "<td>Outcome Description</td><td>The record is ready for formal review determination.</td>",
            content,
        )
        self.assertIn("Stage 11B — Outcome Basis", content)
        self.assertIn(
            "<li>Administrative status classified as Ready for Formal Review.</li>",
            content,
        )
        self.assertIn(
            "<li>Implementation action classified as Prepare Formal Review Implementation.</li>",
            content,
        )
        self.assertIn(
            "<li>Effective state classified as Formal Review Ready.</li>",
            content,
        )
        self.assertIn(
            "<li>Outcome classified as Ready For Determination.</li>",
            content,
        )
        self.assertIn("Stage 11C — Outcome Preconditions", content)
        self.assertIn(
            "<td>Precondition Target</td><td>Determination Completion</td>",
            content,
        )
        self.assertIn(
            "<li>Formal review determination may proceed.</li>",
            content,
        )
        self.assertIn(
            "<li>Outcome advancement depends on determination completion.</li>",
            content,
        )
        self.assertIn("Stage 11D — Outcome Summary", content)
        self.assertIn(
            "<td>Outcome Summary</td><td>Ready For Determination</td>",
            content,
        )
        self.assertIn(
            "<td>Summary Description</td><td>The record has satisfied review progression requirements and is ready for formal determination. Outcome advancement depends upon completion of the determination process.</td>",
            content,
        )
        self.assertIn("Stage 11E — Outcome Readiness", content)
        self.assertIn(
            '<td>Outcome Readiness</td><td><span class="outcome-readiness-badge outcome-readiness-ready">Ready</span></td>',
            content,
        )
        self.assertIn(
            "<td>Readiness Description</td><td>The outcome is ready to proceed to determination.</td>",
            content,
        )
        self.assertIn("Stage 11F — Outcome Target", content)
        self.assertIn(
            '<td>Outcome Target</td><td><span class="outcome-target-badge outcome-target-determination-pending">Determination Pending</span></td>',
            content,
        )
        self.assertIn(
            "<td>Target Description</td><td>The next target outcome is pending determination completion.</td>",
            content,
        )
        self.assertIn("Stage 12A — Resolution Classification", content)
        self.assertIn(
            '<td>Resolution Classification</td><td><span class="resolution-badge resolution-partially-resolved">Partially Resolved</span></td>',
            content,
        )
        self.assertIn(
            "<td>Resolution Description</td><td>The matter has advanced toward resolution but administrative determination or implementation remains incomplete.</td>",
            content,
        )
        self.assertIn("Stage 12B — Resolution Preconditions", content)
        self.assertIn("<td>Precondition Target</td><td>Conditionally Resolved</td>", content)
        self.assertIn(
            "<li>Administrative determination must be completed.</li>",
            content,
        )
        self.assertIn("Stage 12C — Resolution Pathway", content)
        self.assertIn(
            "<td>Resolution Pathway</td><td>DETERMINATION PATHWAY ACTIVE</td>",
            content,
        )
        self.assertIn(
            "<td>Pathway Description</td><td>The matter has reached the determination pathway and remains pending completion of administrative determination.</td>",
            content,
        )
        self.assertIn("Stage 12D — Resolution Readiness", content)
        self.assertIn(
            '<td>Resolution Readiness</td><td><span class="resolution-readiness-badge resolution-readiness-conditionally-ready">Conditionally Ready</span></td>',
            content,
        )
        self.assertIn(
            "<td>Readiness Description</td><td>Resolution readiness is partially established, but further administrative progression remains required.</td>",
            content,
        )
        self.assertIn("Stage 12E — Resolution Determination", content)
        self.assertIn(
            '<td>Resolution Determination</td><td><span class="resolution-determination-badge resolution-determination-required">Determination Required</span></td>',
            content,
        )
        self.assertIn(
            "<td>Determination Description</td><td>Resolution determination is required before the matter can advance toward implementation or completion.</td>",
            content,
        )
        self.assertIn("Stage 12F — Resolution Completion", content)
        self.assertIn(
            '<td>Resolution Completion</td><td><span class="resolution-completion-badge resolution-completion-required">Completion Required</span></td>',
            content,
        )
        self.assertIn(
            "<td>Completion Description</td><td>Resolution completion is required before the matter can be treated as administratively resolved.</td>",
            content,
        )
        self.assertIn("Stage 13A — Closure Classification", content)
        self.assertIn(
            '<td>Closure Classification</td><td><span class="closure-badge closure-pending">Pending Closure</span></td>',
            content,
        )
        self.assertIn(
            "<td>Closure Description</td><td>The matter has advanced toward closure, but completion or confirmation requirements remain outstanding.</td>",
            content,
        )
        self.assertIn("Stage 13B — Closure Preconditions", content)
        self.assertIn(
            '<td>Closure Preconditions</td><td><span class="closure-precondition-badge closure-conditional">Conditionally Closable</span></td>',
            content,
        )
        self.assertIn(
            "<td>Precondition Description</td><td>The matter is approaching closure but one or more completion requirements remain outstanding.</td>",
            content,
        )
        self.assertIn("Stage 13C — Closure Pathway", content)
        self.assertIn(
            '<td>Closure Pathway</td><td><span class="closure-pathway-badge closure-determination-pending">Closure Determination Pending</span></td>',
            content,
        )
        self.assertIn(
            "<td>Pathway Description</td><td>The matter is awaiting closure determination following satisfaction of prerequisite readiness requirements.</td>",
            content,
        )
        self.assertIn("Stage 13D — Closure Readiness", content)
        self.assertIn("Stage 13E — Closure Determination", content)
        self.assertIn("Stage 13F — Closure Completion", content)
        self.assertIn("Stage 14A — Archive Classification", content)
        self.assertIn("Stage 14B — Archive Preconditions", content)
        self.assertIn("Stage 14C — Archive Pathway", content)
        self.assertIn("Stage 14D — Archive Readiness", content)
        self.assertIn("Stage 14E — Archive Determination", content)
        self.assertIn("Stage 14F — Archive Completion", content)
        self.assertIn(
            "<td>Sufficiency Basis</td><td>3 Minimal, 1 Reinforced</td>",
            content,
        )
        self.assertIn("No outstanding evidence gaps.", content)
        self.assertNotIn("Coverage: Unsupported", content)
        self.assertNotIn("Evidence Gap: Yes", content)
        self.assertIn("Coverage: Supported", content)
        self.assertIn("Evidence Gap: No", content)
        self.assertIn("1 supporting relationship", content)
        self.assertIn("<li>supports</li>", content)
        self.assertIn("<li>context_for</li>", content)

    def test_admin_record_evidence_completeness_complete_when_all_targets_sufficient(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            conn.execute(
                """
                UPDATE records
                SET conditions_json = ?, signals_json = ?, finding = ?
                WHERE reference = 'Strike-OT-20260604-ADMIN'
                """,
                (
                    json.dumps(["INSTITUTIONAL_DELAY"]),
                    json.dumps([]),
                    "",
                ),
            )
            self.insert_admin_attachment(conn, title="First complete evidence")
            self.insert_admin_attachment(
                conn,
                title="Second complete evidence",
                filename="second-complete.pdf",
                stored_filename="internal-second-complete.pdf",
                storage_path="/private/path/internal-second-complete.pdf",
                sha256_hash="e" * 64,
            )
            for attachment_id in (1, 2):
                self.insert_attachment_relationship(
                    conn,
                    attachment_id=attachment_id,
                    target_type="condition",
                    target_key="INSTITUTIONAL_DELAY",
                )
                self.insert_attachment_relationship(
                    conn,
                    attachment_id=attachment_id,
                    target_type="record",
                    target_key="Strike-OT-20260604-ADMIN",
                )
            conn.close()
            try:
                with self.env():
                    response = self.admin_session.admin_record_evidence_page(
                        "Strike-OT-20260604-ADMIN",
                        self.valid_request(),
                    )
            finally:
                self.admin_session.DB_PATH = original_db_path

        content = response.content

        self.assertIn("Evidence Completeness", content)
        self.assertIn("<td>Conditions Completeness</td><td>Complete</td>", content)
        self.assertIn("<td>Signals Completeness</td><td>Not Applicable</td>", content)
        self.assertIn("<td>Findings Completeness</td><td>Not Applicable</td>", content)
        self.assertIn("<td>Record Completeness</td><td>Complete</td>", content)
        self.assertIn("<td>Overall Completeness</td><td>Complete</td>", content)
        self.assertIn("<td>Complete Targets</td><td>2</td>", content)
        self.assertIn("<td>Incomplete Targets</td><td>0</td>", content)
        self.assertIn("<td>Completeness Percentage</td><td>100%</td>", content)
        self.assertIn("<td>Conditions Requirement Status</td><td>none_required</td>", content)
        self.assertIn("<td>Record Requirement Status</td><td>none_required</td>", content)
        self.assertIn("<td>Overall Requirement Status</td><td>none_required</td>", content)
        self.assertIn("<td>Targets Requiring Evidence</td><td>0</td>", content)
        self.assertIn("<td>Additional Attachments Required</td><td>0</td>", content)
        self.assertIn("No additional evidence required.", content)
        self.assertIn(
            "Institutional Delay — Complete — Sufficient sufficiency — 2 supporting attachments",
            content,
        )
        self.assertIn(
            "Strike-OT-20260604-ADMIN — Complete — Sufficient sufficiency — 2 supporting attachments",
            content,
        )

    def test_evidence_sufficiency_classification_helper_is_deterministic(self):
        self.assertEqual(
            self.admin_session.classify_evidence_sufficiency(0, 0),
            "Unsupported",
        )
        self.assertEqual(
            self.admin_session.classify_evidence_sufficiency(1, 1),
            "Minimal",
        )
        self.assertEqual(
            self.admin_session.classify_evidence_sufficiency(2, 2),
            "Corroborated",
        )
        self.assertEqual(
            self.admin_session.classify_evidence_sufficiency(1, 2),
            "Reinforced",
        )
        self.assertEqual(
            self.admin_session.classify_evidence_sufficiency(0, 1),
            "Minimal",
        )

    def test_stage15d_evidence_sufficiency_helpers_are_deterministic(self):
        self.assertEqual(
            self.admin_session._classify_stage15d_target_sufficiency(0),
            "Unsupported",
        )
        self.assertEqual(
            self.admin_session._classify_stage15d_target_sufficiency(1),
            "Partial",
        )
        self.assertEqual(
            self.admin_session._classify_stage15d_target_sufficiency(2),
            "Sufficient",
        )
        self.assertEqual(
            self.admin_session._classify_stage15d_target_sufficiency(3),
            "Strong",
        )
        self.assertEqual(
            self.admin_session._classify_stage15d_group_sufficiency([]),
            "Unsupported",
        )
        self.assertEqual(
            self.admin_session._classify_stage15d_group_sufficiency(
                [{"sufficiency": "Unsupported"}]
            ),
            "Unsupported",
        )
        self.assertEqual(
            self.admin_session._classify_stage15d_group_sufficiency(
                [{"sufficiency": "Partial"}, {"sufficiency": "Unsupported"}]
            ),
            "Partial",
        )
        self.assertEqual(
            self.admin_session._classify_stage15d_group_sufficiency(
                [{"sufficiency": "Sufficient"}, {"sufficiency": "Strong"}]
            ),
            "Sufficient",
        )
        self.assertEqual(
            self.admin_session._classify_stage15d_group_sufficiency(
                [{"sufficiency": "Strong"}, {"sufficiency": "Strong"}]
            ),
            "Strong",
        )

    def test_stage15e_evidence_completeness_helpers_are_deterministic(self):
        self.assertFalse(
            self.admin_session._stage15e_target_is_complete("Unsupported")
        )
        self.assertFalse(
            self.admin_session._stage15e_target_is_complete("Partial")
        )
        self.assertTrue(
            self.admin_session._stage15e_target_is_complete("Sufficient")
        )
        self.assertTrue(self.admin_session._stage15e_target_is_complete("Strong"))
        self.assertEqual(
            self.admin_session._classify_stage15e_group_completeness([]),
            "Not Applicable",
        )
        self.assertEqual(
            self.admin_session._classify_stage15e_group_completeness(
                [{"is_complete": False}]
            ),
            "Incomplete",
        )
        self.assertEqual(
            self.admin_session._classify_stage15e_group_completeness(
                [{"is_complete": True}, {"is_complete": False}]
            ),
            "Partial",
        )
        self.assertEqual(
            self.admin_session._classify_stage15e_group_completeness(
                [{"is_complete": True}, {"is_complete": True}]
            ),
            "Complete",
        )
        self.assertEqual(
            self.admin_session._classify_stage15e_overall_completeness(0, 4),
            "Incomplete",
        )
        self.assertEqual(
            self.admin_session._classify_stage15e_overall_completeness(1, 4),
            "Partial",
        )
        self.assertEqual(
            self.admin_session._classify_stage15e_overall_completeness(4, 4),
            "Complete",
        )
        self.assertEqual(
            self.admin_session._format_stage15e_percentage(0, 7),
            "0%",
        )
        self.assertEqual(
            self.admin_session._format_stage15e_percentage(1, 4),
            "25%",
        )
        self.assertEqual(
            self.admin_session._format_stage15e_percentage(1, 9),
            "11.1%",
        )
        self.assertEqual(
            self.admin_session._format_stage15e_percentage(4, 4),
            "100%",
        )

    def test_stage15f_evidence_requirements_helpers_are_deterministic(self):
        self.assertEqual(
            self.admin_session._stage15f_additional_attachments_required(0),
            2,
        )
        self.assertEqual(
            self.admin_session._stage15f_additional_attachments_required(1),
            1,
        )
        self.assertEqual(
            self.admin_session._stage15f_additional_attachments_required(2),
            0,
        )
        self.assertEqual(
            self.admin_session._stage15f_additional_attachments_required(3),
            0,
        )
        self.assertEqual(
            self.admin_session._classify_stage15f_group_requirement_status([]),
            "not_applicable",
        )
        self.assertEqual(
            self.admin_session._classify_stage15f_group_requirement_status(
                [{"additional_required": 2}, {"additional_required": 0}]
            ),
            "outstanding",
        )
        self.assertEqual(
            self.admin_session._classify_stage15f_group_requirement_status(
                [{"additional_required": 0}, {"additional_required": 0}]
            ),
            "none_required",
        )
        self.assertEqual(
            self.admin_session._classify_stage15f_overall_requirement_status(1),
            "outstanding",
        )
        self.assertEqual(
            self.admin_session._classify_stage15f_overall_requirement_status(0),
            "none_required",
        )

    def test_stage16b_evidence_justification_helpers_are_deterministic(self):
        self.assertEqual(
            self.admin_session._stage16b_standard_applied("Unsupported"),
            "Unsupported = 0 active supports; Sufficient = 2 active supports",
        )
        self.assertEqual(
            self.admin_session._stage16b_standard_applied("Partial"),
            "Partial = 1 active support; Sufficient = 2 active supports",
        )
        self.assertEqual(
            self.admin_session._stage16b_standard_applied("Sufficient"),
            "Sufficient = 2 active supports",
        )
        self.assertEqual(
            self.admin_session._stage16b_standard_applied("Strong"),
            "Strong = 3 or more active supports",
        )
        self.assertEqual(
            self.admin_session._stage16b_justification_sentence(
                support_count=3,
                sufficiency="Strong",
                completeness="Complete",
                additional_required=0,
            ),
            "This target is classified as Strong because it has 3 active supports. "
            "It is Complete because completion requires Sufficient or Strong "
            "sufficiency. No additional supporting attachments are required.",
        )

    def test_stage16c_evidence_confidence_helpers_are_deterministic(self):
        self.assertEqual(
            self.admin_session._classify_stage16c_evidence_confidence(
                "Unsupported",
                "Incomplete",
            ),
            "Low Confidence",
        )
        self.assertEqual(
            self.admin_session._classify_stage16c_evidence_confidence(
                "Partial",
                "Incomplete",
            ),
            "Limited Confidence",
        )
        self.assertEqual(
            self.admin_session._classify_stage16c_evidence_confidence(
                "Sufficient",
                "Complete",
            ),
            "High Confidence",
        )
        self.assertEqual(
            self.admin_session._classify_stage16c_evidence_confidence(
                "Strong",
                "Complete",
            ),
            "Very High Confidence",
        )
        self.assertEqual(
            self.admin_session._classify_stage16c_evidence_confidence(
                "Sufficient",
                "Incomplete",
            ),
            "Limited Confidence",
        )
        self.assertEqual(
            self.admin_session._classify_stage16c_evidence_confidence(
                "Strong",
                "Incomplete",
            ),
            "Limited Confidence",
        )
        self.assertEqual(
            self.admin_session._stage16c_confidence_reason(
                "Strong",
                "Complete",
            ),
            "Target has Strong sufficiency and meets the completion threshold.",
        )

    def test_evidence_readiness_classification_helper_is_deterministic(self):
        self.assertEqual(
            self.admin_session.classify_evidence_readiness(
                0,
                4,
                4,
                ["Unsupported", "Unsupported", "Unsupported", "Unsupported"],
            ),
            "Unsupported",
        )
        self.assertEqual(
            self.admin_session.classify_evidence_readiness(
                2,
                1,
                1,
                ["Minimal", "Minimal", "Unsupported"],
            ),
            "Evidence Gaps Present",
        )
        self.assertEqual(
            self.admin_session.classify_evidence_readiness(
                3,
                0,
                0,
                ["Minimal", "Minimal", "Minimal"],
            ),
            "Partially Ready",
        )
        self.assertEqual(
            self.admin_session.classify_evidence_readiness(
                3,
                0,
                0,
                ["Minimal", "Reinforced", "Corroborated"],
            ),
            "Ready",
        )

    def test_administrative_action_helpers_are_deterministic(self):
        self.assertEqual(
            self.admin_session.classify_administrative_action("Unsupported"),
            "Collect Initial Evidence",
        )
        self.assertEqual(
            self.admin_session.classify_administrative_action(
                "Evidence Gaps Present"
            ),
            "Resolve Evidence Gaps",
        )
        self.assertEqual(
            self.admin_session.classify_administrative_action("Partially Ready"),
            "Proceed to Administrative Review",
        )
        self.assertEqual(
            self.admin_session.classify_administrative_action("Ready"),
            "Eligible for Formal Review",
        )
        self.assertEqual(
            self.admin_session.describe_administrative_action_basis(
                "Unsupported",
                0,
                4,
                4,
            ),
            "Administrative action is Collect Initial Evidence because no targets are currently supported.",
        )
        self.assertEqual(
            self.admin_session.describe_administrative_action_basis(
                "Evidence Gaps Present",
                2,
                1,
                1,
            ),
            "Administrative action is Resolve Evidence Gaps because unsupported targets or evidence gaps remain.",
        )
        self.assertEqual(
            self.admin_session.describe_administrative_action_basis(
                "Partially Ready",
                3,
                0,
                0,
            ),
            "Administrative action is Proceed to Administrative Review because all targets are supported but sufficiency remains minimal.",
        )
        self.assertEqual(
            self.admin_session.describe_administrative_action_basis(
                "Ready",
                3,
                0,
                0,
            ),
            "Administrative action is Eligible for Formal Review because the record has no evidence gaps and includes corroborated or reinforced support.",
        )

    def test_action_rationale_trace_helper_is_deterministic(self):
        self.assertEqual(
            self.admin_session.build_action_rationale_trace(
                "Unsupported",
                "Collect Initial Evidence",
                0,
                4,
                4,
            ),
            [
                "Readiness classified as Unsupported",
                "No supported targets identified",
                "Administrative action classified as Collect Initial Evidence",
            ],
        )
        self.assertEqual(
            self.admin_session.build_action_rationale_trace(
                "Evidence Gaps Present",
                "Resolve Evidence Gaps",
                2,
                1,
                1,
            ),
            [
                "Readiness classified as Evidence Gaps Present",
                "Unsupported targets remain",
                "Evidence gaps remain",
                "Administrative action classified as Resolve Evidence Gaps",
            ],
        )
        self.assertEqual(
            self.admin_session.build_action_rationale_trace(
                "Partially Ready",
                "Proceed to Administrative Review",
                3,
                0,
                0,
            ),
            [
                "Readiness classified as Partially Ready",
                "All targets currently supported",
                "Support remains minimal",
                "Administrative action classified as Proceed to Administrative Review",
            ],
        )
        self.assertEqual(
            self.admin_session.build_action_rationale_trace(
                "Ready",
                "Eligible for Formal Review",
                3,
                0,
                0,
            ),
            [
                "Readiness classified as Ready",
                "No unsupported targets remain",
                "No evidence gaps remain",
                "Corroborated or reinforced support identified",
                "Administrative action classified as Eligible for Formal Review",
            ],
        )

    def test_completion_requirements_helper_is_deterministic(self):
        self.assertEqual(
            self.admin_session.build_completion_requirements(
                "Unsupported",
                "Collect Initial Evidence",
                0,
                4,
                4,
                ["Unsupported", "Unsupported"],
            ),
            [
                "At least one target must become supported.",
                "Evidence support must be established.",
            ],
        )
        self.assertEqual(
            self.admin_session.build_completion_requirements(
                "Evidence Gaps Present",
                "Resolve Evidence Gaps",
                2,
                1,
                1,
                ["Minimal", "Unsupported"],
            ),
            [
                "Unsupported targets must be resolved.",
                "Evidence gaps must be resolved.",
            ],
        )
        self.assertEqual(
            self.admin_session.build_completion_requirements(
                "Partially Ready",
                "Proceed to Administrative Review",
                3,
                0,
                0,
                ["Minimal", "Minimal", "Minimal"],
            ),
            [
                "At least one target must achieve corroborated or reinforced support.",
            ],
        )
        self.assertEqual(
            self.admin_session.build_completion_requirements(
                "Ready",
                "Eligible for Formal Review",
                3,
                0,
                0,
                ["Minimal", "Reinforced"],
            ),
            ["No additional evidence requirements identified."],
        )

    def test_workflow_state_helpers_are_deterministic(self):
        self.assertEqual(
            self.admin_session.classify_workflow_state(
                "Unsupported",
                "Collect Initial Evidence",
            ),
            "Evidence Collection",
        )
        self.assertEqual(
            self.admin_session.classify_workflow_state(
                "Evidence Gaps Present",
                "Resolve Evidence Gaps",
            ),
            "Evidence Review",
        )
        self.assertEqual(
            self.admin_session.classify_workflow_state(
                "Partially Ready",
                "Proceed to Administrative Review",
            ),
            "Administrative Review",
        )
        self.assertEqual(
            self.admin_session.classify_workflow_state(
                "Ready",
                "Eligible for Formal Review",
            ),
            "Formal Review Ready",
        )
        self.assertEqual(
            self.admin_session.describe_workflow_state("Evidence Collection"),
            "Evidence support is still being established.",
        )
        self.assertEqual(
            self.admin_session.describe_workflow_state("Evidence Review"),
            "Evidence has been collected but gaps remain.",
        )
        self.assertEqual(
            self.admin_session.describe_workflow_state("Administrative Review"),
            "Evidence support is complete but remains minimally supported.",
        )
        self.assertEqual(
            self.admin_session.describe_workflow_state("Formal Review Ready"),
            "Evidence requirements have been satisfied for formal review.",
        )

    def test_transition_condition_helpers_are_deterministic(self):
        self.assertEqual(
            self.admin_session.describe_transition_target("Evidence Collection"),
            "Evidence Review",
        )
        self.assertEqual(
            self.admin_session.describe_transition_target("Evidence Review"),
            "Administrative Review",
        )
        self.assertEqual(
            self.admin_session.describe_transition_target(
                "Administrative Review"
            ),
            "Formal Review Ready",
        )
        self.assertEqual(
            self.admin_session.describe_transition_target("Formal Review Ready"),
            "No further workflow state identified",
        )
        self.assertEqual(
            self.admin_session.build_transition_conditions(
                "Evidence Collection",
                "Unsupported",
                "Collect Initial Evidence",
                [
                    "At least one target must become supported.",
                    "Evidence support must be established.",
                ],
            ),
            [
                "At least one target must become supported.",
                "Evidence support must be established.",
                "Workflow state may advance to Evidence Review.",
            ],
        )
        self.assertEqual(
            self.admin_session.build_transition_conditions(
                "Evidence Review",
                "Evidence Gaps Present",
                "Resolve Evidence Gaps",
                [
                    "Unsupported targets must be resolved.",
                    "Evidence gaps must be resolved.",
                ],
            ),
            [
                "Unsupported targets must be resolved.",
                "Evidence gaps must be resolved.",
                "Workflow state may advance to Administrative Review.",
            ],
        )
        self.assertEqual(
            self.admin_session.build_transition_conditions(
                "Administrative Review",
                "Partially Ready",
                "Proceed to Administrative Review",
                [
                    "At least one target must achieve corroborated or reinforced support.",
                ],
            ),
            [
                "Corroborated or reinforced support must be identified.",
                "Workflow state may advance to Formal Review Ready.",
            ],
        )
        self.assertEqual(
            self.admin_session.build_transition_conditions(
                "Formal Review Ready",
                "Ready",
                "Eligible for Formal Review",
                ["No additional evidence requirements identified."],
            ),
            ["No additional workflow transition conditions identified."],
        )

    def test_administrative_disposition_helpers_are_deterministic(self):
        self.assertEqual(
            self.admin_session.classify_administrative_disposition(
                "Evidence Collection"
            ),
            "Open",
        )
        self.assertEqual(
            self.admin_session.classify_administrative_disposition(
                "Evidence Review"
            ),
            "Open",
        )
        self.assertEqual(
            self.admin_session.classify_administrative_disposition(
                "Administrative Review"
            ),
            "Pending Review",
        )
        self.assertEqual(
            self.admin_session.classify_administrative_disposition(
                "Formal Review Ready"
            ),
            "Ready for Review",
        )
        self.assertEqual(
            self.admin_session.describe_administrative_disposition("Open"),
            "The record remains within active evidence workflow.",
        )
        self.assertEqual(
            self.admin_session.describe_administrative_disposition(
                "Pending Review"
            ),
            (
                "The record has satisfied evidence workflow requirements and "
                "awaits administrative review."
            ),
        )
        self.assertEqual(
            self.admin_session.describe_administrative_disposition(
                "Ready for Review"
            ),
            (
                "The record satisfies current workflow requirements for formal review."
            ),
        )
        self.assertEqual(
            self.admin_session.build_disposition_basis_trace(
                "Open",
                "Evidence Review",
                "Evidence Gaps Present",
                "Resolve Evidence Gaps",
            ),
            [
                "Workflow state classified as Evidence Review.",
                "Readiness classified as Evidence Gaps Present.",
                "Administrative action classified as Resolve Evidence Gaps.",
                "Administrative disposition classified as Open.",
            ],
        )
        self.assertEqual(
            self.admin_session.build_disposition_basis_trace(
                "Pending Review",
                "Administrative Review",
                "Partially Ready",
                "Proceed to Administrative Review",
            ),
            [
                "Workflow state classified as Administrative Review.",
                "Administrative disposition classified as Pending Review.",
            ],
        )
        self.assertEqual(
            self.admin_session.build_disposition_basis_trace(
                "Ready for Review",
                "Formal Review Ready",
                "Ready",
                "Eligible for Formal Review",
            ),
            [
                "Workflow state classified as Formal Review Ready.",
                "Administrative disposition classified as Ready for Review.",
            ],
        )
        self.assertEqual(
            self.admin_session.classify_review_eligibility("Open"),
            "Not Eligible",
        )
        self.assertEqual(
            self.admin_session.classify_review_eligibility("Pending Review"),
            "Conditionally Eligible",
        )
        self.assertEqual(
            self.admin_session.classify_review_eligibility("Ready for Review"),
            "Eligible",
        )
        self.assertEqual(
            self.admin_session.describe_review_eligibility("Not Eligible"),
            "The record has not yet satisfied review requirements.",
        )
        self.assertEqual(
            self.admin_session.describe_review_eligibility(
                "Conditionally Eligible"
            ),
            (
                "The record may proceed to review subject to administrative "
                "assessment."
            ),
        )
        self.assertEqual(
            self.admin_session.describe_review_eligibility("Eligible"),
            "The record satisfies current requirements for review.",
        )
        self.assertEqual(
            self.admin_session.describe_review_precondition_target(
                "Not Eligible"
            ),
            "Conditionally Eligible",
        )
        self.assertEqual(
            self.admin_session.describe_review_precondition_target(
                "Conditionally Eligible"
            ),
            "Eligible",
        )
        self.assertEqual(
            self.admin_session.describe_review_precondition_target("Eligible"),
            "No further review eligibility state identified",
        )
        self.assertEqual(
            self.admin_session.build_review_preconditions(
                "Not Eligible",
                "Open",
                "Evidence Review",
                [
                    "Unsupported targets must be resolved.",
                    "Evidence gaps must be resolved.",
                ],
            ),
            [
                "Workflow transition conditions must be satisfied.",
                "Administrative disposition must advance beyond Open.",
                (
                    "Review eligibility may advance when workflow "
                    "requirements are satisfied."
                ),
            ],
        )
        self.assertEqual(
            self.admin_session.build_review_preconditions(
                "Conditionally Eligible",
                "Pending Review",
                "Administrative Review",
                [
                    "Corroborated or reinforced support must be identified.",
                ],
            ),
            [
                "Administrative review requirements must be satisfied.",
                "Review eligibility may advance to Eligible.",
            ],
        )
        self.assertEqual(
            self.admin_session.build_review_preconditions(
                "Eligible",
                "Ready for Review",
                "Formal Review Ready",
                ["No additional workflow transition conditions identified."],
            ),
            ["No additional review preconditions identified."],
        )
        self.assertEqual(
            self.admin_session.build_administrative_status_summary(
                "Open",
                "Not Eligible",
                "Evidence Review",
                "Evidence Gaps Present",
            ),
            {
                "status": "Active Evidence Review",
                "description": (
                    "Evidence remains under review and review eligibility "
                    "requirements have not yet been satisfied."
                ),
            },
        )
        self.assertEqual(
            self.admin_session.build_administrative_status_summary(
                "Pending Review",
                "Conditionally Eligible",
                "Administrative Review",
                "Partially Ready",
            ),
            {
                "status": "Pending Administrative Review",
                "description": (
                    "The record may proceed to administrative review subject "
                    "to assessment."
                ),
            },
        )
        self.assertEqual(
            self.admin_session.build_administrative_status_summary(
                "Ready for Review",
                "Eligible",
                "Formal Review Ready",
                "Ready",
            ),
            {
                "status": "Ready for Formal Review",
                "description": (
                    "The record satisfies current administrative review "
                    "requirements."
                ),
            },
        )
        self.assertEqual(
            self.admin_session.classify_implementation_action(
                "Active Evidence Review"
            ),
            "No Implementation Action",
        )
        self.assertEqual(
            self.admin_session.classify_implementation_action(
                "Pending Administrative Review"
            ),
            "Await Review Determination",
        )
        self.assertEqual(
            self.admin_session.classify_implementation_action(
                "Ready for Formal Review"
            ),
            "Prepare Formal Review Implementation",
        )
        self.assertEqual(
            self.admin_session.describe_implementation_action(
                "No Implementation Action"
            ),
            (
                "No implementation action is available while evidence review "
                "remains active."
            ),
        )
        self.assertEqual(
            self.admin_session.describe_implementation_action(
                "Await Review Determination"
            ),
            (
                "Implementation is deferred until administrative review "
                "produces a determination."
            ),
        )
        self.assertEqual(
            self.admin_session.describe_implementation_action(
                "Prepare Formal Review Implementation"
            ),
            "The record is ready for formal review implementation planning.",
        )
        self.assertEqual(
            self.admin_session.build_implementation_basis_trace(
                "No Implementation Action",
                "Active Evidence Review",
                "Open",
                "Not Eligible",
                "Evidence Review",
                "Evidence Gaps Present",
            ),
            [
                "Administrative status classified as Active Evidence Review.",
                "Administrative disposition classified as Open.",
                "Review eligibility classified as Not Eligible.",
                "Workflow state classified as Evidence Review.",
                "Readiness classified as Evidence Gaps Present.",
                "Implementation action classified as No Implementation Action.",
            ],
        )
        self.assertEqual(
            self.admin_session.build_implementation_basis_trace(
                "Await Review Determination",
                "Pending Administrative Review",
                "Pending Review",
                "Conditionally Eligible",
                "Administrative Review",
                "Partially Ready",
            ),
            [
                "Administrative status classified as Pending Administrative Review.",
                "Administrative disposition classified as Pending Review.",
                "Review eligibility classified as Conditionally Eligible.",
                "Workflow state classified as Administrative Review.",
                "Readiness classified as Partially Ready.",
                "Implementation action classified as Await Review Determination.",
            ],
        )
        self.assertEqual(
            self.admin_session.build_implementation_basis_trace(
                "Prepare Formal Review Implementation",
                "Ready for Formal Review",
                "Ready for Review",
                "Eligible",
                "Formal Review Ready",
                "Ready",
            ),
            [
                "Administrative status classified as Ready for Formal Review.",
                "Administrative disposition classified as Ready for Review.",
                "Review eligibility classified as Eligible.",
                "Workflow state classified as Formal Review Ready.",
                "Readiness classified as Ready.",
                (
                    "Implementation action classified as Prepare Formal Review "
                    "Implementation."
                ),
            ],
        )
        self.assertEqual(
            self.admin_session.classify_effective_state(
                "No Implementation Action",
                "Active Evidence Review",
            ),
            "Evidence Review Continues",
        )
        self.assertEqual(
            self.admin_session.classify_effective_state(
                "Await Review Determination",
                "Pending Administrative Review",
            ),
            "Administrative Review Pending",
        )
        self.assertEqual(
            self.admin_session.classify_effective_state(
                "Prepare Formal Review Implementation",
                "Ready for Formal Review",
            ),
            "Formal Review Ready",
        )
        self.assertEqual(
            self.admin_session.describe_effective_state(
                "Evidence Review Continues"
            ),
            (
                "Evidence review remains active and no implementation action "
                "has been applied."
            ),
        )
        self.assertEqual(
            self.admin_session.describe_effective_state(
                "Administrative Review Pending"
            ),
            (
                "Administrative review remains pending before implementation "
                "can proceed."
            ),
        )
        self.assertEqual(
            self.admin_session.describe_effective_state("Formal Review Ready"),
            "The record is ready for formal review implementation planning.",
        )
        self.assertEqual(
            self.admin_session.classify_outcome("Evidence Review Continues"),
            "Ongoing Review",
        )
        self.assertEqual(
            self.admin_session.classify_outcome(
                "Administrative Review Pending"
            ),
            "Review Awaiting Determination",
        )
        self.assertEqual(
            self.admin_session.classify_outcome("Formal Review Ready"),
            "Ready For Determination",
        )
        self.assertEqual(
            self.admin_session.describe_outcome("Ongoing Review"),
            (
                "The record remains in ongoing review because evidence review "
                "continues."
            ),
        )
        self.assertEqual(
            self.admin_session.describe_outcome(
                "Review Awaiting Determination"
            ),
            "The record is awaiting an administrative review determination.",
        )
        self.assertEqual(
            self.admin_session.describe_outcome("Ready For Determination"),
            "The record is ready for formal review determination.",
        )
        self.assertEqual(
            self.admin_session.build_outcome_basis_trace(
                "Ongoing Review",
                "Evidence Review Continues",
                "No Implementation Action",
                "Active Evidence Review",
            ),
            [
                "Administrative status classified as Active Evidence Review.",
                "Implementation action classified as No Implementation Action.",
                "Effective state classified as Evidence Review Continues.",
                "Outcome classified as Ongoing Review.",
            ],
        )
        self.assertEqual(
            self.admin_session.build_outcome_basis_trace(
                "Review Awaiting Determination",
                "Administrative Review Pending",
                "Await Review Determination",
                "Pending Administrative Review",
            ),
            [
                "Administrative status classified as Pending Administrative Review.",
                "Implementation action classified as Await Review Determination.",
                "Effective state classified as Administrative Review Pending.",
                "Outcome classified as Review Awaiting Determination.",
            ],
        )
        self.assertEqual(
            self.admin_session.build_outcome_basis_trace(
                "Ready For Determination",
                "Formal Review Ready",
                "Prepare Formal Review Implementation",
                "Ready for Formal Review",
            ),
            [
                "Administrative status classified as Ready for Formal Review.",
                (
                    "Implementation action classified as Prepare Formal Review "
                    "Implementation."
                ),
                "Effective state classified as Formal Review Ready.",
                "Outcome classified as Ready For Determination.",
            ],
        )
        self.assertEqual(
            self.admin_session.build_outcome_preconditions(
                "Ongoing Review",
                "Evidence Review Continues",
                "No Implementation Action",
                "Active Evidence Review",
                "Not Eligible",
            ),
            [
                "Review eligibility requirements must be satisfied.",
                "Administrative disposition must advance beyond Open.",
                "Implementation action must advance beyond No Implementation Action.",
                "Effective state may advance when review conditions are satisfied.",
            ],
        )
        self.assertEqual(
            self.admin_session.build_outcome_preconditions(
                "Review Awaiting Determination",
                "Administrative Review Pending",
                "Await Review Determination",
                "Pending Administrative Review",
                "Conditionally Eligible",
            ),
            [
                "Administrative review determination must be completed.",
                "Outcome may advance when determination requirements are satisfied.",
            ],
        )
        self.assertEqual(
            self.admin_session.build_outcome_preconditions(
                "Ready For Determination",
                "Formal Review Ready",
                "Prepare Formal Review Implementation",
                "Ready for Formal Review",
                "Eligible",
            ),
            [
                "Formal review determination may proceed.",
                "Outcome advancement depends on determination completion.",
            ],
        )
        self.assertEqual(
            self.admin_session.build_outcome_summary(
                "Ongoing Review",
                [
                    "Administrative status classified as Active Evidence Review.",
                    "Implementation action classified as No Implementation Action.",
                    "Effective state classified as Evidence Review Continues.",
                    "Outcome classified as Ongoing Review.",
                ],
                [
                    "Review eligibility requirements must be satisfied.",
                    "Administrative disposition must advance beyond Open.",
                    "Implementation action must advance beyond No Implementation Action.",
                    "Effective state may advance when review conditions are satisfied.",
                ],
                "Evidence Review Continues",
                "No Implementation Action",
                "Active Evidence Review",
            ),
            {
                "outcome": "Ongoing Review",
                "description": (
                    "The record remains in ongoing review. Evidence review "
                    "continues, no implementation action has been applied, "
                    "and outcome advancement depends upon satisfaction of "
                    "review eligibility and administrative progression "
                    "requirements."
                ),
            },
        )
        self.assertEqual(
            self.admin_session.build_outcome_summary(
                "Review Awaiting Determination",
                [
                    "Administrative status classified as Pending Administrative Review.",
                    "Implementation action classified as Await Review Determination.",
                    "Effective state classified as Administrative Review Pending.",
                    "Outcome classified as Review Awaiting Determination.",
                ],
                [
                    "Administrative review determination must be completed.",
                    "Outcome may advance when determination requirements are satisfied.",
                ],
                "Administrative Review Pending",
                "Await Review Determination",
                "Pending Administrative Review",
            ),
            {
                "outcome": "Review Awaiting Determination",
                "description": (
                    "The record has advanced beyond active evidence review "
                    "and is awaiting administrative determination. Outcome "
                    "advancement depends upon completion of the required "
                    "review determination process."
                ),
            },
        )
        self.assertEqual(
            self.admin_session.build_outcome_summary(
                "Ready For Determination",
                [
                    "Administrative status classified as Ready for Formal Review.",
                    (
                        "Implementation action classified as Prepare Formal Review "
                        "Implementation."
                    ),
                    "Effective state classified as Formal Review Ready.",
                    "Outcome classified as Ready For Determination.",
                ],
                [
                    "Formal review determination may proceed.",
                    "Outcome advancement depends on determination completion.",
                ],
                "Formal Review Ready",
                "Prepare Formal Review Implementation",
                "Ready for Formal Review",
            ),
            {
                "outcome": "Ready For Determination",
                "description": (
                    "The record has satisfied review progression requirements "
                    "and is ready for formal determination. Outcome "
                    "advancement depends upon completion of the determination "
                    "process."
                ),
            },
        )
        self.assertEqual(
            self.admin_session.classify_outcome_readiness(
                "Ongoing Review",
                [
                    "Review eligibility requirements must be satisfied.",
                    "Administrative disposition must advance beyond Open.",
                ],
                "Not Eligible",
                "Active Evidence Review",
                "Evidence Review Continues",
            ),
            "Not Ready",
        )
        self.assertEqual(
            self.admin_session.classify_outcome_readiness(
                "Review Awaiting Determination",
                [
                    "Administrative review determination must be completed.",
                    "Outcome may advance when determination requirements are satisfied.",
                ],
                "Conditionally Eligible",
                "Pending Administrative Review",
                "Administrative Review Pending",
            ),
            "Conditionally Ready",
        )
        self.assertEqual(
            self.admin_session.classify_outcome_readiness(
                "Ready For Determination",
                [
                    "Formal review determination may proceed.",
                    "Outcome advancement depends on determination completion.",
                ],
                "Eligible",
                "Ready for Formal Review",
                "Formal Review Ready",
            ),
            "Ready",
        )
        self.assertEqual(
            self.admin_session.describe_outcome_readiness("Not Ready"),
            (
                "The outcome cannot advance while review eligibility and "
                "administrative progression requirements remain unsatisfied."
            ),
        )
        self.assertEqual(
            self.admin_session.describe_outcome_readiness(
                "Conditionally Ready"
            ),
            (
                "The outcome may advance when administrative review "
                "requirements are satisfied."
            ),
        )
        self.assertEqual(
            self.admin_session.describe_outcome_readiness("Ready"),
            "The outcome is ready to proceed to determination.",
        )
        self.assertEqual(
            self.admin_session.classify_outcome_target(
                "Ongoing Review",
                "Not Ready",
                "Evidence Review Continues",
                "Not Eligible",
                "Active Evidence Review",
            ),
            "Review Awaiting Determination",
        )
        self.assertEqual(
            self.admin_session.classify_outcome_target(
                "Review Awaiting Determination",
                "Conditionally Ready",
                "Administrative Review Pending",
                "Conditionally Eligible",
                "Pending Administrative Review",
            ),
            "Ready For Determination",
        )
        self.assertEqual(
            self.admin_session.classify_outcome_target(
                "Ready For Determination",
                "Ready",
                "Formal Review Ready",
                "Eligible",
                "Ready for Formal Review",
            ),
            "Determination Pending",
        )
        self.assertEqual(
            self.admin_session.describe_outcome_target(
                "Review Awaiting Determination"
            ),
            (
                "The next target outcome is administrative review awaiting "
                "determination once review eligibility and progression "
                "requirements are satisfied."
            ),
        )
        self.assertEqual(
            self.admin_session.describe_outcome_target(
                "Ready For Determination"
            ),
            (
                "The next target outcome is readiness for determination once "
                "administrative review requirements are satisfied."
            ),
        )
        self.assertEqual(
            self.admin_session.describe_outcome_target(
                "Determination Pending"
            ),
            "The next target outcome is pending determination completion.",
        )
        self.assertEqual(
            self.admin_session.classify_resolution(
                "Ongoing Review",
                "Not Ready",
                "Review Awaiting Determination",
                "Evidence Review Continues",
                "No Implementation Action",
                "Active Evidence Review",
            ),
            "Unresolved",
        )
        self.assertEqual(
            self.admin_session.classify_resolution(
                "Ready For Determination",
                "Ready",
                "Determination Pending",
                "Formal Review Ready",
                "Prepare Formal Review Implementation",
                "Ready for Formal Review",
            ),
            "Partially Resolved",
        )
        self.assertEqual(
            self.admin_session.classify_resolution(
                "Determination Issued",
                "Ready",
                "Determination Pending",
                "Formal Review Ready",
                "Implementation Required",
                "Ready for Formal Review",
            ),
            "Conditionally Resolved",
        )
        self.assertEqual(
            self.admin_session.classify_resolution(
                "Corrective Action Implemented",
                "Ready",
                "Determination Pending",
                "Corrective Action Effective",
                "Prepare Formal Review Implementation",
                "Ready for Formal Review",
            ),
            "Resolved",
        )
        self.assertEqual(
            self.admin_session.classify_resolution(
                "Corrective Action Reversed",
                "Ready",
                "Determination Pending",
                "Implementation Failed",
                "Implementation Failed",
                "Ready for Formal Review",
            ),
            "Resolution Failed",
        )
        self.assertEqual(
            self.admin_session.describe_resolution("Unresolved"),
            (
                "The matter remains unresolved because the current outcome "
                "has not reached an implemented administrative determination "
                "state."
            ),
        )
        self.assertEqual(
            self.admin_session.describe_resolution("Partially Resolved"),
            (
                "The matter has advanced toward resolution but administrative "
                "determination or implementation remains incomplete."
            ),
        )
        self.assertEqual(
            self.admin_session.describe_resolution("Conditionally Resolved"),
            (
                "The matter has reached a conditional resolution state, but "
                "implementation or confirmation requirements remain "
                "outstanding."
            ),
        )
        self.assertEqual(
            self.admin_session.describe_resolution("Resolved"),
            (
                "The matter has reached a resolved state because the required "
                "administrative action has been implemented and is effective."
            ),
        )
        self.assertEqual(
            self.admin_session.describe_resolution("Resolution Failed"),
            (
                "The matter has not resolved because the required corrective "
                "or administrative action failed, reversed, or did not take "
                "effect."
            ),
        )
        self.assertEqual(
            self.admin_session.build_resolution_preconditions(
                "Unresolved",
                "Ongoing Review",
                "Not Ready",
                "Review Awaiting Determination",
                "Evidence Review Continues",
                "No Implementation Action",
                "Active Evidence Review",
                "Not Eligible",
            ),
            [
                "Review eligibility requirements must be satisfied.",
                "Administrative disposition must advance beyond Open.",
                "Outcome readiness must advance beyond Not Ready.",
                "Implementation action must advance beyond No Implementation Action.",
                "Effective state must advance beyond Evidence Review Continues.",
            ],
        )
        self.assertEqual(
            self.admin_session.build_resolution_preconditions(
                "Partially Resolved",
                "Ready For Determination",
                "Ready",
                "Determination Pending",
                "Formal Review Ready",
                "Prepare Formal Review Implementation",
                "Ready for Formal Review",
                "Eligible",
            ),
            [
                "Administrative determination must be completed.",
                "Implementation requirements must be identified.",
                "Effective state must advance beyond Formal Review Ready.",
            ],
        )
        self.assertEqual(
            self.admin_session.build_resolution_preconditions(
                "Conditionally Resolved",
                "Determination Issued",
                "Ready",
                "Determination Pending",
                "Formal Review Ready",
                "Implementation Required",
                "Ready for Formal Review",
                "Eligible",
            ),
            [
                "Implementation requirements must be satisfied.",
                "Resolution effectiveness must be confirmed.",
            ],
        )
        self.assertEqual(
            self.admin_session.build_resolution_preconditions(
                "Resolved",
                "Corrective Action Implemented",
                "Ready",
                "Determination Pending",
                "Corrective Action Effective",
                "Prepare Formal Review Implementation",
                "Ready for Formal Review",
                "Eligible",
            ),
            ["No additional resolution preconditions identified."],
        )
        self.assertEqual(
            self.admin_session.build_resolution_preconditions(
                "Resolution Failed",
                "Corrective Action Reversed",
                "Ready",
                "Determination Pending",
                "Implementation Failed",
                "Implementation Failed",
                "Ready for Formal Review",
                "Eligible",
            ),
            [
                "Failed or reversed administrative action must be corrected.",
                "Resolution state must be re-established through effective action.",
            ],
        )
        self.assertEqual(
            self.admin_session.describe_resolution_preconditions("Unresolved"),
            (
                "Resolution preconditions identify the deterministic "
                "requirements that must be satisfied before the current "
                "Unresolved state can advance."
            ),
        )
        self.assertEqual(
            self.admin_session._classify_resolution_pathway(
                resolution="Unresolved",
                resolution_preconditions=[
                    "Outcome readiness must advance beyond Not Ready.",
                ],
                outcome_target="Review Awaiting Determination",
                outcome_readiness="Not Ready",
                effective_state="Evidence Review Continues",
                review_eligibility="Eligible",
                administrative_status="Active Evidence Review",
                implementation_action="No Implementation Action",
            ),
            "REVIEW PATHWAY ACTIVE",
        )
        self.assertEqual(
            self.admin_session._classify_resolution_pathway(
                resolution="Unresolved",
                resolution_preconditions=[
                    "Review eligibility requirements must be satisfied.",
                ],
                outcome_target="Review Awaiting Determination",
                outcome_readiness="Not Ready",
                effective_state="Evidence Review Continues",
                review_eligibility="Not Eligible",
                administrative_status="Active Evidence Review",
                implementation_action="No Implementation Action",
            ),
            "REVIEW ELIGIBILITY PENDING",
        )
        self.assertEqual(
            self.admin_session._classify_resolution_pathway(
                resolution="Conditionally Resolved",
                resolution_preconditions=[
                    "Resolution effectiveness must be confirmed.",
                ],
                outcome_target="Determination Pending",
                outcome_readiness="Ready",
                effective_state="Formal Review Ready",
                review_eligibility="Eligible",
                administrative_status="Ready for Formal Review",
                implementation_action="Prepare Formal Review Implementation",
            ),
            "IMPLEMENTATION PATHWAY ACTIVE",
        )
        self.assertEqual(
            self.admin_session._classify_resolution_pathway(
                resolution="Conditionally Resolved",
                resolution_preconditions=[
                    "Implementation requirements must be satisfied.",
                ],
                outcome_target="Determination Pending",
                outcome_readiness="Ready",
                effective_state="Formal Review Ready",
                review_eligibility="Eligible",
                administrative_status="Ready for Formal Review",
                implementation_action="Implementation Required",
            ),
            "IMPLEMENTATION AWAITING ACTION",
        )
        self.assertEqual(
            self.admin_session._classify_resolution_pathway(
                resolution="Partially Resolved",
                resolution_preconditions=[
                    "Administrative determination must be completed.",
                ],
                outcome_target="Determination Pending",
                outcome_readiness="Ready",
                effective_state="Formal Review Ready",
                review_eligibility="Eligible",
                administrative_status="Ready for Formal Review",
                implementation_action="Prepare Formal Review Implementation",
            ),
            "DETERMINATION PATHWAY ACTIVE",
        )
        self.assertEqual(
            self.admin_session._classify_resolution_pathway(
                resolution="Resolved",
                resolution_preconditions=[],
                outcome_target="Determination Pending",
                outcome_readiness="Ready",
                effective_state="Corrective Action Effective",
                review_eligibility="Eligible",
                administrative_status="Ready for Formal Review",
                implementation_action="Prepare Formal Review Implementation",
            ),
            "RESOLUTION PATHWAY COMPLETE",
        )
        self.assertEqual(
            self.admin_session._describe_resolution_pathway(
                "REVIEW PATHWAY ACTIVE"
            ),
            (
                "The current matter remains within the administrative review "
                "pathway and must satisfy review progression requirements "
                "before advancing."
            ),
        )
        self.assertEqual(
            self.admin_session._describe_resolution_pathway(
                "IMPLEMENTATION PATHWAY ACTIVE"
            ),
            (
                "The matter has progressed beyond review and remains within "
                "the implementation pathway."
            ),
        )
        self.assertEqual(
            self.admin_session._describe_resolution_pathway(
                "RESOLUTION PATHWAY COMPLETE"
            ),
            "All resolution pathway requirements have been satisfied.",
        )
        self.assertEqual(
            self.admin_session._classify_resolution_readiness(
                resolution="Unresolved",
                resolution_preconditions=[
                    "Review eligibility requirements must be satisfied.",
                ],
                resolution_pathway="REVIEW ELIGIBILITY PENDING",
                outcome_readiness="Not Ready",
                review_eligibility="Not Eligible",
                administrative_status="Active Evidence Review",
                implementation_action="No Implementation Action",
                effective_state="Evidence Review Continues",
            ),
            "Not Ready",
        )
        self.assertEqual(
            self.admin_session._classify_resolution_readiness(
                resolution="Unresolved",
                resolution_preconditions=[],
                resolution_pathway="REVIEW PATHWAY ACTIVE",
                outcome_readiness="Conditionally Ready",
                review_eligibility="Eligible",
                administrative_status="Pending Administrative Review",
                implementation_action="Await Review Determination",
                effective_state="Administrative Review Pending",
            ),
            "Conditionally Ready",
        )
        self.assertEqual(
            self.admin_session._classify_resolution_readiness(
                resolution="Partially Resolved",
                resolution_preconditions=[
                    "Administrative determination must be completed.",
                ],
                resolution_pathway="DETERMINATION PATHWAY ACTIVE",
                outcome_readiness="Ready",
                review_eligibility="Eligible",
                administrative_status="Ready for Formal Review",
                implementation_action="Prepare Formal Review Implementation",
                effective_state="Formal Review Ready",
            ),
            "Conditionally Ready",
        )
        self.assertEqual(
            self.admin_session._classify_resolution_readiness(
                resolution="Conditionally Resolved",
                resolution_preconditions=[
                    "Resolution effectiveness must be confirmed.",
                ],
                resolution_pathway="IMPLEMENTATION PATHWAY ACTIVE",
                outcome_readiness="Ready",
                review_eligibility="Eligible",
                administrative_status="Ready for Formal Review",
                implementation_action="Prepare Formal Review Implementation",
                effective_state="Formal Review Ready",
            ),
            "Ready",
        )
        self.assertEqual(
            self.admin_session._classify_resolution_readiness(
                resolution="Resolved",
                resolution_preconditions=[],
                resolution_pathway="RESOLUTION PATHWAY COMPLETE",
                outcome_readiness="Ready",
                review_eligibility="Eligible",
                administrative_status="Ready for Formal Review",
                implementation_action="Prepare Formal Review Implementation",
                effective_state="Corrective Action Effective",
            ),
            "Resolved",
        )
        self.assertEqual(
            self.admin_session._describe_resolution_readiness("Not Ready"),
            (
                "Resolution readiness has not been achieved because one or "
                "more prerequisite administrative conditions remain "
                "outstanding."
            ),
        )
        self.assertEqual(
            self.admin_session._describe_resolution_readiness(
                "Conditionally Ready"
            ),
            (
                "Resolution readiness is partially established, but further "
                "administrative progression remains required."
            ),
        )
        self.assertEqual(
            self.admin_session._describe_resolution_readiness("Ready"),
            (
                "Resolution readiness has been established and the matter may "
                "proceed toward determination, implementation, or confirmation."
            ),
        )
        self.assertEqual(
            self.admin_session._describe_resolution_readiness("Resolved"),
            (
                "Resolution readiness assessment is complete because the "
                "matter has already reached a resolved administrative state."
            ),
        )
        self.assertEqual(
            self.admin_session._classify_resolution_determination(
                resolution="Unresolved",
                resolution_preconditions=[
                    "Review eligibility requirements must be satisfied.",
                ],
                resolution_pathway="REVIEW ELIGIBILITY PENDING",
                resolution_readiness="Not Ready",
                outcome_target="Review Awaiting Determination",
                outcome_readiness="Not Ready",
                review_eligibility="Not Eligible",
                administrative_status="Active Evidence Review",
                implementation_action="No Implementation Action",
                effective_state="Evidence Review Continues",
            ),
            "Determination Not Available",
        )
        self.assertEqual(
            self.admin_session._classify_resolution_determination(
                resolution="Unresolved",
                resolution_preconditions=[],
                resolution_pathway="REVIEW PATHWAY ACTIVE",
                resolution_readiness="Conditionally Ready",
                outcome_target="Ready For Determination",
                outcome_readiness="Conditionally Ready",
                review_eligibility="Conditionally Eligible",
                administrative_status="Pending Administrative Review",
                implementation_action="Await Review Determination",
                effective_state="Administrative Review Pending",
            ),
            "Determination Pending",
        )
        self.assertEqual(
            self.admin_session._classify_resolution_determination(
                resolution="Partially Resolved",
                resolution_preconditions=[
                    "Administrative determination must be completed.",
                ],
                resolution_pathway="DETERMINATION PATHWAY ACTIVE",
                resolution_readiness="Conditionally Ready",
                outcome_target="Determination Pending",
                outcome_readiness="Ready",
                review_eligibility="Eligible",
                administrative_status="Ready for Formal Review",
                implementation_action="Prepare Formal Review Implementation",
                effective_state="Formal Review Ready",
            ),
            "Determination Required",
        )
        self.assertEqual(
            self.admin_session._classify_resolution_determination(
                resolution="Conditionally Resolved",
                resolution_preconditions=[
                    "Resolution effectiveness must be confirmed.",
                ],
                resolution_pathway="IMPLEMENTATION PATHWAY ACTIVE",
                resolution_readiness="Ready",
                outcome_target="Determination Pending",
                outcome_readiness="Ready",
                review_eligibility="Eligible",
                administrative_status="Ready for Formal Review",
                implementation_action="Prepare Formal Review Implementation",
                effective_state="Formal Review Ready",
            ),
            "Determination Issued",
        )
        self.assertEqual(
            self.admin_session._classify_resolution_determination(
                resolution="Resolved",
                resolution_preconditions=[],
                resolution_pathway="RESOLUTION PATHWAY COMPLETE",
                resolution_readiness="Resolved",
                outcome_target="Determination Pending",
                outcome_readiness="Ready",
                review_eligibility="Eligible",
                administrative_status="Ready for Formal Review",
                implementation_action="Prepare Formal Review Implementation",
                effective_state="Corrective Action Effective",
            ),
            "Determination Complete",
        )
        self.assertEqual(
            self.admin_session._describe_resolution_determination(
                "Determination Not Available"
            ),
            (
                "Resolution determination is not available because "
                "prerequisite review and readiness conditions remain "
                "unsatisfied."
            ),
        )
        self.assertEqual(
            self.admin_session._describe_resolution_determination(
                "Determination Pending"
            ),
            (
                "Resolution determination is pending because the matter "
                "remains within the review pathway."
            ),
        )
        self.assertEqual(
            self.admin_session._describe_resolution_determination(
                "Determination Required"
            ),
            (
                "Resolution determination is required before the matter can "
                "advance toward implementation or completion."
            ),
        )
        self.assertEqual(
            self.admin_session._describe_resolution_determination(
                "Determination Issued"
            ),
            (
                "Resolution determination has been issued, but implementation "
                "or confirmation remains outstanding."
            ),
        )
        self.assertEqual(
            self.admin_session._describe_resolution_determination(
                "Determination Complete"
            ),
            (
                "Resolution determination is complete because the matter has "
                "reached a resolved administrative state."
            ),
        )
        self.assertEqual(
            self.admin_session._classify_resolution_completion(
                resolution="Unresolved",
                resolution_preconditions=[
                    "Review eligibility requirements must be satisfied.",
                ],
                resolution_pathway="REVIEW ELIGIBILITY PENDING",
                resolution_readiness="Not Ready",
                resolution_determination="Determination Not Available",
                outcome_target="Review Awaiting Determination",
                outcome_readiness="Not Ready",
                review_eligibility="Not Eligible",
                administrative_status="Active Evidence Review",
                implementation_action="No Implementation Action",
                effective_state="Evidence Review Continues",
            ),
            "Not Complete",
        )
        self.assertEqual(
            self.admin_session._classify_resolution_completion(
                resolution="Unresolved",
                resolution_preconditions=[],
                resolution_pathway="REVIEW PATHWAY ACTIVE",
                resolution_readiness="Conditionally Ready",
                resolution_determination="Determination Pending",
                outcome_target="Ready For Determination",
                outcome_readiness="Conditionally Ready",
                review_eligibility="Conditionally Eligible",
                administrative_status="Pending Administrative Review",
                implementation_action="Await Review Determination",
                effective_state="Administrative Review Pending",
            ),
            "Completion Pending",
        )
        self.assertEqual(
            self.admin_session._classify_resolution_completion(
                resolution="Partially Resolved",
                resolution_preconditions=[
                    "Administrative determination must be completed.",
                ],
                resolution_pathway="DETERMINATION PATHWAY ACTIVE",
                resolution_readiness="Conditionally Ready",
                resolution_determination="Determination Required",
                outcome_target="Determination Pending",
                outcome_readiness="Ready",
                review_eligibility="Eligible",
                administrative_status="Ready for Formal Review",
                implementation_action="Prepare Formal Review Implementation",
                effective_state="Formal Review Ready",
            ),
            "Completion Required",
        )
        self.assertEqual(
            self.admin_session._classify_resolution_completion(
                resolution="Resolved",
                resolution_preconditions=[],
                resolution_pathway="RESOLUTION PATHWAY COMPLETE",
                resolution_readiness="Resolved",
                resolution_determination="Determination Complete",
                outcome_target="Determination Pending",
                outcome_readiness="Ready",
                review_eligibility="Eligible",
                administrative_status="Ready for Formal Review",
                implementation_action="Prepare Formal Review Implementation",
                effective_state="Corrective Action Effective",
            ),
            "Completion Confirmed",
        )
        self.assertEqual(
            self.admin_session._classify_resolution_completion(
                resolution="Resolution Failed",
                resolution_preconditions=[],
                resolution_pathway="IMPLEMENTATION PATHWAY ACTIVE",
                resolution_readiness="Ready",
                resolution_determination="Determination Issued",
                outcome_target="Determination Pending",
                outcome_readiness="Ready",
                review_eligibility="Eligible",
                administrative_status="Ready for Formal Review",
                implementation_action="Prepare Formal Review Implementation",
                effective_state="Implementation Failed",
            ),
            "Completion Failed",
        )
        self.assertEqual(
            self.admin_session._describe_resolution_completion("Not Complete"),
            (
                "Resolution completion has not been reached because "
                "prerequisite determination and readiness conditions remain "
                "unsatisfied."
            ),
        )
        self.assertEqual(
            self.admin_session._describe_resolution_completion(
                "Completion Pending"
            ),
            (
                "Resolution completion remains pending because determination, "
                "implementation, or confirmation requirements remain "
                "outstanding."
            ),
        )
        self.assertEqual(
            self.admin_session._describe_resolution_completion(
                "Completion Required"
            ),
            (
                "Resolution completion is required before the matter can be "
                "treated as administratively resolved."
            ),
        )
        self.assertEqual(
            self.admin_session._describe_resolution_completion(
                "Completion Confirmed"
            ),
            (
                "Resolution completion has been confirmed because the matter "
                "has reached a resolved administrative state."
            ),
        )
        self.assertEqual(
            self.admin_session._describe_resolution_completion(
                "Completion Failed"
            ),
            (
                "Resolution completion failed because the required corrective "
                "or administrative action did not take effect."
            ),
        )
        self.assertEqual(
            self.admin_session._classify_closure(
                resolution="Unresolved",
                resolution_completion="Not Complete",
                resolution_determination="Determination Not Available",
                resolution_readiness="Not Ready",
                resolution_pathway="REVIEW ELIGIBILITY PENDING",
                outcome_target="Review Awaiting Determination",
                administrative_status="Active Evidence Review",
                implementation_action="No Implementation Action",
                effective_state="Evidence Review Continues",
            ),
            "Open",
        )
        self.assertEqual(
            self.admin_session._classify_closure(
                resolution="Partially Resolved",
                resolution_completion="Completion Required",
                resolution_determination="Determination Required",
                resolution_readiness="Conditionally Ready",
                resolution_pathway="DETERMINATION PATHWAY ACTIVE",
                outcome_target="Determination Pending",
                administrative_status="Ready for Formal Review",
                implementation_action="Prepare Formal Review Implementation",
                effective_state="Formal Review Ready",
            ),
            "Pending Closure",
        )
        self.assertEqual(
            self.admin_session._classify_closure(
                resolution="Unresolved",
                resolution_completion="Completion Confirmed",
                resolution_determination="Determination Complete",
                resolution_readiness="Resolved",
                resolution_pathway="RESOLUTION PATHWAY COMPLETE",
                outcome_target="Determination Pending",
                administrative_status="Ready for Formal Review",
                implementation_action="Prepare Formal Review Implementation",
                effective_state="Corrective Action Effective",
            ),
            "Closed Without Resolution",
        )
        self.assertEqual(
            self.admin_session._classify_closure(
                resolution="Resolved",
                resolution_completion="Completion Confirmed",
                resolution_determination="Determination Complete",
                resolution_readiness="Resolved",
                resolution_pathway="RESOLUTION PATHWAY COMPLETE",
                outcome_target="Determination Pending",
                administrative_status="Ready for Formal Review",
                implementation_action="Prepare Formal Review Implementation",
                effective_state="Corrective Action Effective",
            ),
            "Closed With Resolution",
        )
        self.assertEqual(
            self.admin_session._classify_closure(
                resolution="Resolution Failed",
                resolution_completion="Completion Failed",
                resolution_determination="Determination Issued",
                resolution_readiness="Ready",
                resolution_pathway="IMPLEMENTATION PATHWAY ACTIVE",
                outcome_target="Determination Pending",
                administrative_status="Ready for Formal Review",
                implementation_action="Prepare Formal Review Implementation",
                effective_state="Implementation Failed",
            ),
            "Closure Failed",
        )
        self.assertEqual(
            self.admin_session._describe_closure("Open"),
            (
                "The matter remains open because resolution completion has "
                "not been reached."
            ),
        )
        self.assertEqual(
            self.admin_session._describe_closure("Pending Closure"),
            (
                "The matter has advanced toward closure, but completion or "
                "confirmation requirements remain outstanding."
            ),
        )
        self.assertEqual(
            self.admin_session._describe_closure("Closed Without Resolution"),
            (
                "The matter has been closed without reaching a resolved "
                "administrative state."
            ),
        )
        self.assertEqual(
            self.admin_session._describe_closure("Closed With Resolution"),
            (
                "The matter has been closed after reaching a resolved "
                "administrative state."
            ),
        )
        self.assertEqual(
            self.admin_session._describe_closure("Closure Failed"),
            (
                "Closure failed because the required resolution or completion "
                "state did not take effect."
            ),
        )
        self.assertEqual(
            self.admin_session._classify_closure_preconditions(
                closure="Closed With Resolution",
                resolution="Resolved",
                resolution_completion="Completion Confirmed",
                resolution_determination="Determination Complete",
                resolution_readiness="Resolved",
                resolution_pathway="RESOLUTION PATHWAY COMPLETE",
                outcome_target="Determination Pending",
                administrative_status="Ready for Formal Review",
                implementation_action="Prepare Formal Review Implementation",
                effective_state="Corrective Action Effective",
            ),
            "Closure Ready",
        )
        self.assertEqual(
            self.admin_session._classify_closure_preconditions(
                closure="Pending Closure",
                resolution="Partially Resolved",
                resolution_completion="Completion Required",
                resolution_determination="Determination Required",
                resolution_readiness="Conditionally Ready",
                resolution_pathway="DETERMINATION PATHWAY ACTIVE",
                outcome_target="Determination Pending",
                administrative_status="Ready for Formal Review",
                implementation_action="Prepare Formal Review Implementation",
                effective_state="Formal Review Ready",
            ),
            "Conditionally Closable",
        )
        self.assertEqual(
            self.admin_session._classify_closure_preconditions(
                closure="Open",
                resolution="Unresolved",
                resolution_completion="Not Complete",
                resolution_determination="Determination Not Available",
                resolution_readiness="Not Ready",
                resolution_pathway="REVIEW ELIGIBILITY PENDING",
                outcome_target="Review Awaiting Determination",
                administrative_status="Active Evidence Review",
                implementation_action="No Implementation Action",
                effective_state="Evidence Review Continues",
            ),
            "Closure Preconditions Outstanding",
        )
        self.assertEqual(
            self.admin_session._classify_closure_preconditions(
                closure="Closure Failed",
                resolution="Resolution Failed",
                resolution_completion="Completion Failed",
                resolution_determination="Determination Issued",
                resolution_readiness="Ready",
                resolution_pathway="IMPLEMENTATION PATHWAY ACTIVE",
                outcome_target="Determination Pending",
                administrative_status="Ready for Formal Review",
                implementation_action="Prepare Formal Review Implementation",
                effective_state="Implementation Failed",
            ),
            "Closure Blocked",
        )
        self.assertEqual(
            self.admin_session._describe_closure_preconditions(
                "Closure Ready"
            ),
            "All deterministic closure requirements have been satisfied.",
        )
        self.assertEqual(
            self.admin_session._describe_closure_preconditions(
                "Conditionally Closable"
            ),
            (
                "The matter is approaching closure but one or more completion "
                "requirements remain outstanding."
            ),
        )
        self.assertEqual(
            self.admin_session._describe_closure_preconditions(
                "Closure Preconditions Outstanding"
            ),
            (
                "Closure requirements remain outstanding and must be "
                "satisfied before the matter can advance."
            ),
        )
        self.assertEqual(
            self.admin_session._describe_closure_preconditions(
                "Closure Blocked"
            ),
            (
                "Closure cannot proceed because prerequisite completion or "
                "determination conditions have failed."
            ),
        )
        self.assertEqual(
            self.admin_session._classify_closure_pathway(
                closure="Open",
                closure_preconditions="Closure Preconditions Outstanding",
                resolution="Unresolved",
                resolution_completion="Not Complete",
                resolution_determination="Determination Not Available",
                resolution_readiness="Not Ready",
                resolution_pathway="REVIEW ELIGIBILITY PENDING",
                outcome_target="Review Awaiting Determination",
                administrative_status="Active Evidence Review",
                implementation_action="No Implementation Action",
                effective_state="Evidence Review Continues",
            ),
            "Closure Eligibility Pending",
        )
        self.assertEqual(
            self.admin_session._classify_closure_pathway(
                closure="Pending Closure",
                closure_preconditions="Conditionally Closable",
                resolution="Conditionally Resolved",
                resolution_completion="Completion Required",
                resolution_determination="Determination Complete",
                resolution_readiness="Ready",
                resolution_pathway="REVIEW PATHWAY ACTIVE",
                outcome_target="Ready For Determination",
                administrative_status="Pending Administrative Review",
                implementation_action="Await Review Determination",
                effective_state="Administrative Review Pending",
            ),
            "Closure Readiness Pending",
        )
        self.assertEqual(
            self.admin_session._classify_closure_pathway(
                closure="Pending Closure",
                closure_preconditions="Conditionally Closable",
                resolution="Partially Resolved",
                resolution_completion="Completion Required",
                resolution_determination="Determination Required",
                resolution_readiness="Conditionally Ready",
                resolution_pathway="DETERMINATION PATHWAY ACTIVE",
                outcome_target="Determination Pending",
                administrative_status="Ready for Formal Review",
                implementation_action="Prepare Formal Review Implementation",
                effective_state="Formal Review Ready",
            ),
            "Closure Determination Pending",
        )
        self.assertEqual(
            self.admin_session._classify_closure_pathway(
                closure="Pending Closure",
                closure_preconditions="Closure Ready",
                resolution="Resolved",
                resolution_completion="Completion Confirmed",
                resolution_determination="Determination Complete",
                resolution_readiness="Resolved",
                resolution_pathway="RESOLUTION PATHWAY COMPLETE",
                outcome_target="Determination Pending",
                administrative_status="Ready for Formal Review",
                implementation_action="Prepare Formal Review Implementation",
                effective_state="Corrective Action Effective",
            ),
            "Closure Confirmation Pending",
        )
        self.assertEqual(
            self.admin_session._classify_closure_pathway(
                closure="Closed With Resolution",
                closure_preconditions="Closure Ready",
                resolution="Resolved",
                resolution_completion="Completion Confirmed",
                resolution_determination="Determination Complete",
                resolution_readiness="Resolved",
                resolution_pathway="RESOLUTION PATHWAY COMPLETE",
                outcome_target="Determination Pending",
                administrative_status="Ready for Formal Review",
                implementation_action="Prepare Formal Review Implementation",
                effective_state="Corrective Action Effective",
            ),
            "Closure Complete",
        )
        self.assertEqual(
            self.admin_session._describe_closure_pathway(
                "Closure Eligibility Pending"
            ),
            (
                "The matter remains within the closure pathway while closure "
                "eligibility requirements remain outstanding."
            ),
        )
        self.assertEqual(
            self.admin_session._describe_closure_pathway(
                "Closure Readiness Pending"
            ),
            (
                "The matter has advanced beyond eligibility review but "
                "closure readiness requirements remain outstanding."
            ),
        )
        self.assertEqual(
            self.admin_session._describe_closure_pathway(
                "Closure Determination Pending"
            ),
            (
                "The matter is awaiting closure determination following "
                "satisfaction of prerequisite readiness requirements."
            ),
        )
        self.assertEqual(
            self.admin_session._describe_closure_pathway(
                "Closure Confirmation Pending"
            ),
            "The matter is awaiting final closure confirmation.",
        )
        self.assertEqual(
            self.admin_session._describe_closure_pathway("Closure Complete"),
            "The closure pathway has completed.",
        )
        self.assertEqual(
            self.admin_session._classify_closure_readiness(
                closure_classification="Closable",
                closure_preconditions="Satisfied",
                closure_pathway="Closure Available",
                resolution_classification="Resolved",
                resolution_completion="Complete",
                resolution_determination="Available",
                resolution_readiness="Ready",
                outcome_readiness="Ready",
                review_eligibility="Eligible",
                administrative_status="Ready for Formal Review",
                implementation_action="Prepare Formal Review Implementation",
                effective_state="Formal Review Ready",
            ),
            "Ready",
        )
        self.assertEqual(
            self.admin_session._classify_closure_readiness(
                closure_classification="Open",
                closure_preconditions="Closure Preconditions Outstanding",
                closure_pathway="Closure Eligibility Pending",
                resolution_classification="Unresolved",
                resolution_completion="Not Complete",
                resolution_determination="Determination Not Available",
                resolution_readiness="Not Ready",
                outcome_readiness="Not Ready",
                review_eligibility="Not Eligible",
                administrative_status="Active Evidence Review",
                implementation_action="No Implementation Action",
                effective_state="Evidence Review Continues",
            ),
            "Not Ready",
        )
        self.assertEqual(
            self.admin_session._describe_closure_readiness("Ready"),
            (
                "Closure readiness has been achieved because all "
                "prerequisite closure conditions have been satisfied."
            ),
        )
        self.assertEqual(
            self.admin_session._describe_closure_readiness("Not Ready"),
            (
                "Closure readiness has not been achieved because one or more "
                "prerequisite closure conditions remain outstanding."
            ),
        )
        self.assertEqual(
            self.admin_session._classify_closure_determination(
                closure_classification="Open",
                closure_preconditions="Closure Preconditions Outstanding",
                closure_pathway="Closure Eligibility Pending",
                closure_readiness="Not Ready",
                resolution_classification="Unresolved",
                resolution_completion="Not Complete",
                resolution_determination="Determination Not Available",
                outcome_readiness="Not Ready",
                review_eligibility="Not Eligible",
                administrative_status="Active Evidence Review",
                implementation_action="No Implementation Action",
                effective_state="Evidence Review Continues",
            ),
            "Determination Not Available",
        )
        self.assertEqual(
            self.admin_session._classify_closure_determination(
                closure_classification="Pending Closure",
                closure_preconditions="Conditionally Closable",
                closure_pathway="Closure Readiness Pending",
                closure_readiness="Ready",
                resolution_classification="Conditionally Resolved",
                resolution_completion="Completion Required",
                resolution_determination="Determination Pending",
                outcome_readiness="Conditionally Ready",
                review_eligibility="Conditionally Eligible",
                administrative_status="Pending Administrative Review",
                implementation_action="Await Review Determination",
                effective_state="Administrative Review Pending",
            ),
            "Determination Pending",
        )
        self.assertEqual(
            self.admin_session._classify_closure_determination(
                closure_classification="Pending Closure",
                closure_preconditions="Conditionally Closable",
                closure_pathway="Closure Determination Pending",
                closure_readiness="Not Ready",
                resolution_classification="Partially Resolved",
                resolution_completion="Completion Required",
                resolution_determination="Determination Required",
                outcome_readiness="Ready",
                review_eligibility="Eligible",
                administrative_status="Ready for Formal Review",
                implementation_action="Prepare Formal Review Implementation",
                effective_state="Formal Review Ready",
            ),
            "Determination Required",
        )
        self.assertEqual(
            self.admin_session._classify_closure_determination(
                closure_classification="Pending Closure",
                closure_preconditions="Closure Ready",
                closure_pathway="Closure Confirmation Pending",
                closure_readiness="Ready",
                resolution_classification="Resolved",
                resolution_completion="Completion Confirmed",
                resolution_determination="Determination Issued",
                outcome_readiness="Ready",
                review_eligibility="Eligible",
                administrative_status="Ready for Formal Review",
                implementation_action="Prepare Formal Review Implementation",
                effective_state="Formal Review Ready",
            ),
            "Determination Issued",
        )
        self.assertEqual(
            self.admin_session._classify_closure_determination(
                closure_classification="Closed With Resolution",
                closure_preconditions="Closure Ready",
                closure_pathway="Closure Complete",
                closure_readiness="Ready",
                resolution_classification="Resolved",
                resolution_completion="Completion Confirmed",
                resolution_determination="Determination Complete",
                outcome_readiness="Ready",
                review_eligibility="Eligible",
                administrative_status="Ready for Formal Review",
                implementation_action="Prepare Formal Review Implementation",
                effective_state="Formal Review Ready",
            ),
            "Determination Complete",
        )
        self.assertEqual(
            self.admin_session._describe_closure_determination(
                "Determination Not Available"
            ),
            (
                "Closure determination is not available because prerequisite "
                "closure conditions remain unsatisfied."
            ),
        )
        self.assertEqual(
            self.admin_session._describe_closure_determination(
                "Determination Pending"
            ),
            (
                "Closure determination remains pending while closure "
                "readiness requirements are being satisfied."
            ),
        )
        self.assertEqual(
            self.admin_session._describe_closure_determination(
                "Determination Required"
            ),
            (
                "Closure determination is required before the matter can "
                "advance toward closure confirmation."
            ),
        )
        self.assertEqual(
            self.admin_session._describe_closure_determination(
                "Determination Issued"
            ),
            (
                "Closure determination has been issued and is awaiting "
                "closure confirmation."
            ),
        )
        self.assertEqual(
            self.admin_session._describe_closure_determination(
                "Determination Complete"
            ),
            (
                "Closure determination is complete because the matter has "
                "reached a closure state."
            ),
        )
        self.assertEqual(
            self.admin_session._classify_closure_completion(
                closure_classification="Open",
                closure_preconditions="Closure Preconditions Outstanding",
                closure_pathway="Closure Eligibility Pending",
                closure_readiness="Not Ready",
                closure_determination="Determination Not Available",
                resolution_classification="Unresolved",
                resolution_completion="Not Complete",
                resolution_determination="Determination Not Available",
                outcome_readiness="Not Ready",
                review_eligibility="Not Eligible",
                administrative_status="Active Evidence Review",
                implementation_action="No Implementation Action",
                effective_state="Evidence Review Continues",
            ),
            "Not Complete",
        )
        self.assertEqual(
            self.admin_session._classify_closure_completion(
                closure_classification="Pending Closure",
                closure_preconditions="Conditionally Closable",
                closure_pathway="Closure Readiness Pending",
                closure_readiness="Ready",
                closure_determination="Determination Pending",
                resolution_classification="Conditionally Resolved",
                resolution_completion="Completion Required",
                resolution_determination="Determination Pending",
                outcome_readiness="Conditionally Ready",
                review_eligibility="Conditionally Eligible",
                administrative_status="Pending Administrative Review",
                implementation_action="Await Review Determination",
                effective_state="Administrative Review Pending",
            ),
            "Completion Pending",
        )
        self.assertEqual(
            self.admin_session._classify_closure_completion(
                closure_classification="Pending Closure",
                closure_preconditions="Closure Ready",
                closure_pathway="Closure Confirmation Pending",
                closure_readiness="Ready",
                closure_determination="Determination Issued",
                resolution_classification="Resolved",
                resolution_completion="Completion Confirmed",
                resolution_determination="Determination Issued",
                outcome_readiness="Ready",
                review_eligibility="Eligible",
                administrative_status="Ready for Formal Review",
                implementation_action="Prepare Formal Review Implementation",
                effective_state="Formal Review Ready",
            ),
            "Completion In Progress",
        )
        self.assertEqual(
            self.admin_session._classify_closure_completion(
                closure_classification="Closed With Resolution",
                closure_preconditions="Closure Ready",
                closure_pathway="Closure Complete",
                closure_readiness="Ready",
                closure_determination="Determination Complete",
                resolution_classification="Resolved",
                resolution_completion="Completion Confirmed",
                resolution_determination="Determination Complete",
                outcome_readiness="Ready",
                review_eligibility="Eligible",
                administrative_status="Ready for Formal Review",
                implementation_action="Prepare Formal Review Implementation",
                effective_state="Formal Review Ready",
            ),
            "Complete",
        )
        self.assertEqual(
            self.admin_session._describe_closure_completion("Not Complete"),
            (
                "Closure completion has not been reached because prerequisite "
                "closure determination conditions remain unsatisfied."
            ),
        )
        self.assertEqual(
            self.admin_session._describe_closure_completion(
                "Completion Pending"
            ),
            (
                "Closure completion remains pending while closure "
                "determination requirements are being satisfied."
            ),
        )
        self.assertEqual(
            self.admin_session._describe_closure_completion(
                "Completion In Progress"
            ),
            (
                "Closure completion is in progress pending final closure "
                "confirmation."
            ),
        )
        self.assertEqual(
            self.admin_session._describe_closure_completion("Complete"),
            (
                "Closure completion has been achieved because the matter has "
                "reached a closure state."
            ),
        )
        self.assertEqual(
            self.admin_session._archive_classification(
                closure_classification="Open",
                closure_completion="Not Complete",
                closure_determination="Determination Not Available",
                closure_readiness="Not Ready",
                resolution_classification="Unresolved",
                resolution_completion="Not Complete",
                resolution_determination="Determination Not Available",
                outcome_readiness="Not Ready",
                review_eligibility="Not Eligible",
                administrative_status="Active Evidence Review",
                implementation_action="No Implementation Action",
                effective_state="Evidence Review Continues",
            ),
            "Not Archivable",
        )
        self.assertEqual(
            self.admin_session._archive_classification(
                closure_classification="Closed With Resolution",
                closure_completion="Complete",
                closure_determination="Determination Complete",
                closure_readiness="Ready",
                resolution_classification="Resolved",
                resolution_completion="Completion Confirmed",
                resolution_determination="Determination Complete",
                outcome_readiness="Ready",
                review_eligibility="Eligible",
                administrative_status="Ready for Formal Review",
                implementation_action="Prepare Formal Review Implementation",
                effective_state="Formal Review Ready",
            ),
            "Archive Eligible",
        )
        self.assertEqual(
            self.admin_session._archive_classification(
                closure_classification="Closed With Resolution",
                closure_completion="Complete",
                closure_determination="Determination Complete",
                closure_readiness="Ready",
                resolution_classification="Resolved",
                resolution_completion="Completion Confirmed",
                resolution_determination="Determination Complete",
                outcome_readiness="Ready",
                review_eligibility="Eligible",
                administrative_status="Archived",
                implementation_action="Prepare Formal Review Implementation",
                effective_state="Archived",
            ),
            "Archived",
        )
        self.assertEqual(
            self.admin_session._describe_archive_classification(
                "Not Archivable"
            ),
            (
                "Archive classification has not been achieved because closure "
                "completion requirements remain unsatisfied."
            ),
        )
        self.assertEqual(
            self.admin_session._describe_archive_classification(
                "Archive Eligible"
            ),
            (
                "The matter satisfies archive classification requirements "
                "and may proceed to archive evaluation."
            ),
        )
        self.assertEqual(
            self.admin_session._describe_archive_classification("Archived"),
            "The matter has reached an archived administrative state.",
        )
        self.assertEqual(
            self.admin_session._archive_preconditions(
                archive_classification="Not Archivable",
                closure_classification="Open",
                closure_completion="Not Complete",
                closure_determination="Determination Not Available",
                closure_readiness="Not Ready",
                resolution_classification="Unresolved",
                resolution_completion="Not Complete",
                resolution_determination="Determination Not Available",
                outcome_readiness="Not Ready",
                review_eligibility="Not Eligible",
                administrative_status="Active Evidence Review",
                implementation_action="No Implementation Action",
                effective_state="Evidence Review Continues",
            ),
            "Archive Preconditions Outstanding",
        )
        self.assertEqual(
            self.admin_session._archive_preconditions(
                archive_classification="Archive Eligible",
                closure_classification="Closed With Resolution",
                closure_completion="Complete",
                closure_determination="Determination Complete",
                closure_readiness="Ready",
                resolution_classification="Resolved",
                resolution_completion="Completion Confirmed",
                resolution_determination="Determination Complete",
                outcome_readiness="Ready",
                review_eligibility="Eligible",
                administrative_status="Ready for Formal Review",
                implementation_action="Prepare Formal Review Implementation",
                effective_state="Formal Review Ready",
            ),
            "Archive Preconditions Satisfied",
        )
        self.assertEqual(
            self.admin_session._archive_preconditions(
                archive_classification="Archived",
                closure_classification="Closed With Resolution",
                closure_completion="Complete",
                closure_determination="Determination Complete",
                closure_readiness="Ready",
                resolution_classification="Resolved",
                resolution_completion="Completion Confirmed",
                resolution_determination="Determination Complete",
                outcome_readiness="Ready",
                review_eligibility="Eligible",
                administrative_status="Archived",
                implementation_action="Prepare Formal Review Implementation",
                effective_state="Archived",
            ),
            "Archive Preconditions Satisfied",
        )
        self.assertEqual(
            self.admin_session._describe_archive_preconditions(
                "Archive Preconditions Outstanding"
            ),
            (
                "Archive requirements remain outstanding and must be "
                "satisfied before archive progression can occur."
            ),
        )
        self.assertEqual(
            self.admin_session._describe_archive_preconditions(
                "Archive Preconditions Satisfied"
            ),
            (
                "Archive requirements have been satisfied and archive "
                "progression may continue."
            ),
        )
        self.assertEqual(
            self.admin_session._archive_pathway(
                archive_classification="Not Archivable",
                archive_preconditions="Archive Preconditions Outstanding",
                closure_classification="Open",
                closure_completion="Not Complete",
                closure_determination="Determination Not Available",
                closure_readiness="Not Ready",
                resolution_classification="Unresolved",
                resolution_completion="Not Complete",
                resolution_determination="Determination Not Available",
                outcome_readiness="Not Ready",
                review_eligibility="Not Eligible",
                administrative_status="Active Evidence Review",
                implementation_action="No Implementation Action",
                effective_state="Evidence Review Continues",
            ),
            "Archive Eligibility Pending",
        )
        self.assertEqual(
            self.admin_session._archive_pathway(
                archive_classification="Archive Eligible",
                archive_preconditions="Archive Preconditions Satisfied",
                closure_classification="Closed With Resolution",
                closure_completion="Complete",
                closure_determination="Determination Complete",
                closure_readiness="Ready",
                resolution_classification="Resolved",
                resolution_completion="Completion Confirmed",
                resolution_determination="Determination Complete",
                outcome_readiness="Ready",
                review_eligibility="Eligible",
                administrative_status="Ready for Formal Review",
                implementation_action="Prepare Formal Review Implementation",
                effective_state="Formal Review Ready",
            ),
            "Archive Determination Pending",
        )
        self.assertEqual(
            self.admin_session._archive_pathway(
                archive_classification="Archive Eligible",
                archive_preconditions="Archive Preconditions Satisfied",
                closure_classification="Closed With Resolution",
                closure_completion="Complete",
                closure_determination="Determination Complete",
                closure_readiness="Ready",
                resolution_classification="Resolved",
                resolution_completion="Completion Confirmed",
                resolution_determination="Determination Complete",
                outcome_readiness="Ready",
                review_eligibility="Eligible",
                administrative_status="Ready for Archive Completion",
                implementation_action="Prepare Formal Review Implementation",
                effective_state="Archive Ready",
            ),
            "Archive Ready",
        )
        self.assertEqual(
            self.admin_session._archive_pathway(
                archive_classification="Archived",
                archive_preconditions="Archive Preconditions Satisfied",
                closure_classification="Closed With Resolution",
                closure_completion="Complete",
                closure_determination="Determination Complete",
                closure_readiness="Ready",
                resolution_classification="Resolved",
                resolution_completion="Completion Confirmed",
                resolution_determination="Determination Complete",
                outcome_readiness="Ready",
                review_eligibility="Eligible",
                administrative_status="Archived",
                implementation_action="Prepare Formal Review Implementation",
                effective_state="Archived",
            ),
            "Archived",
        )
        self.assertEqual(
            self.admin_session._describe_archive_pathway(
                "Archive Eligibility Pending"
            ),
            (
                "The matter remains within the archive pathway while archive "
                "eligibility requirements remain outstanding."
            ),
        )
        self.assertEqual(
            self.admin_session._describe_archive_pathway(
                "Archive Determination Pending"
            ),
            (
                "Archive eligibility requirements have been satisfied and "
                "archive determination may proceed."
            ),
        )
        self.assertEqual(
            self.admin_session._describe_archive_pathway("Archive Ready"),
            (
                "Archive requirements have been satisfied and the matter is "
                "ready for archive completion."
            ),
        )
        self.assertEqual(
            self.admin_session._describe_archive_pathway("Archived"),
            "The matter has completed archive progression.",
        )
        self.assertEqual(
            self.admin_session._archive_readiness(
                archive_classification="Not Archivable",
                archive_preconditions="Archive Preconditions Outstanding",
                archive_pathway="Archive Eligibility Pending",
                closure_classification="Open",
                closure_completion="Not Complete",
                closure_determination="Determination Not Available",
                closure_readiness="Not Ready",
                resolution_classification="Unresolved",
                resolution_completion="Not Complete",
                resolution_determination="Determination Not Available",
                outcome_readiness="Not Ready",
                review_eligibility="Not Eligible",
                administrative_status="Active Evidence Review",
                implementation_action="No Implementation Action",
                effective_state="Evidence Review Continues",
            ),
            "Not Ready",
        )
        self.assertEqual(
            self.admin_session._archive_readiness(
                archive_classification="Archive Eligible",
                archive_preconditions="Archive Preconditions Satisfied",
                archive_pathway="Archive Determination Pending",
                closure_classification="Closed With Resolution",
                closure_completion="Complete",
                closure_determination="Determination Complete",
                closure_readiness="Ready",
                resolution_classification="Resolved",
                resolution_completion="Completion Confirmed",
                resolution_determination="Determination Complete",
                outcome_readiness="Ready",
                review_eligibility="Eligible",
                administrative_status="Ready for Formal Review",
                implementation_action="Prepare Formal Review Implementation",
                effective_state="Formal Review Ready",
            ),
            "Ready",
        )
        self.assertEqual(
            self.admin_session._archive_readiness(
                archive_classification="Archived",
                archive_preconditions="Archive Preconditions Satisfied",
                archive_pathway="Archived",
                closure_classification="Closed With Resolution",
                closure_completion="Complete",
                closure_determination="Determination Complete",
                closure_readiness="Ready",
                resolution_classification="Resolved",
                resolution_completion="Completion Confirmed",
                resolution_determination="Determination Complete",
                outcome_readiness="Ready",
                review_eligibility="Eligible",
                administrative_status="Archived",
                implementation_action="Prepare Formal Review Implementation",
                effective_state="Archived",
            ),
            "Archived",
        )
        self.assertEqual(
            self.admin_session._describe_archive_readiness("Not Ready"),
            (
                "Archive readiness has not been achieved because one or more "
                "prerequisite archive conditions remain outstanding."
            ),
        )
        self.assertEqual(
            self.admin_session._describe_archive_readiness("Ready"),
            (
                "Archive readiness has been achieved and archive "
                "determination may proceed."
            ),
        )
        self.assertEqual(
            self.admin_session._describe_archive_readiness("Archived"),
            (
                "Archive readiness has been satisfied and the matter has "
                "completed archive progression."
            ),
        )
        self.assertEqual(
            self.admin_session._archive_determination(
                archive_classification="Not Archivable",
                archive_preconditions="Archive Preconditions Outstanding",
                archive_pathway="Archive Eligibility Pending",
                archive_readiness="Not Ready",
                closure_classification="Open",
                closure_completion="Not Complete",
                closure_determination="Determination Not Available",
                closure_readiness="Not Ready",
                resolution_classification="Unresolved",
                resolution_completion="Not Complete",
                resolution_determination="Determination Not Available",
                outcome_readiness="Not Ready",
                review_eligibility="Not Eligible",
                administrative_status="Active Evidence Review",
                implementation_action="No Implementation Action",
                effective_state="Evidence Review Continues",
            ),
            "Determination Not Available",
        )
        self.assertEqual(
            self.admin_session._archive_determination(
                archive_classification="Archive Eligible",
                archive_preconditions="Archive Preconditions Satisfied",
                archive_pathway="Archive Determination Pending",
                archive_readiness="Ready",
                closure_classification="Closed With Resolution",
                closure_completion="Complete",
                closure_determination="Determination Complete",
                closure_readiness="Ready",
                resolution_classification="Resolved",
                resolution_completion="Completion Confirmed",
                resolution_determination="Determination Complete",
                outcome_readiness="Ready",
                review_eligibility="Eligible",
                administrative_status="Ready for Formal Review",
                implementation_action="Prepare Formal Review Implementation",
                effective_state="Formal Review Ready",
            ),
            "Archive Eligible",
        )
        self.assertEqual(
            self.admin_session._archive_determination(
                archive_classification="Archived",
                archive_preconditions="Archive Preconditions Satisfied",
                archive_pathway="Archived",
                archive_readiness="Archived",
                closure_classification="Closed With Resolution",
                closure_completion="Complete",
                closure_determination="Determination Complete",
                closure_readiness="Ready",
                resolution_classification="Resolved",
                resolution_completion="Completion Confirmed",
                resolution_determination="Determination Complete",
                outcome_readiness="Ready",
                review_eligibility="Eligible",
                administrative_status="Archived",
                implementation_action="Prepare Formal Review Implementation",
                effective_state="Archived",
            ),
            "Archived",
        )
        self.assertEqual(
            self.admin_session._describe_archive_determination(
                "Determination Not Available"
            ),
            (
                "Archive determination is not available because prerequisite "
                "archive conditions remain unsatisfied."
            ),
        )
        self.assertEqual(
            self.admin_session._describe_archive_determination(
                "Archive Eligible"
            ),
            (
                "Archive determination confirms that archive requirements "
                "have been satisfied."
            ),
        )
        self.assertEqual(
            self.admin_session._describe_archive_determination("Archived"),
            (
                "Archive determination confirms that archive progression "
                "has completed."
            ),
        )
        self.assertEqual(
            self.admin_session._archive_completion(
                archive_classification="Not Archivable",
                archive_preconditions="Archive Preconditions Outstanding",
                archive_pathway="Archive Eligibility Pending",
                archive_readiness="Not Ready",
                archive_determination="Determination Not Available",
                closure_classification="Open",
                closure_completion="Not Complete",
                closure_determination="Determination Not Available",
                closure_readiness="Not Ready",
                resolution_classification="Unresolved",
                resolution_completion="Not Complete",
                resolution_determination="Determination Not Available",
                outcome_readiness="Not Ready",
                review_eligibility="Not Eligible",
                administrative_status="Active Evidence Review",
                implementation_action="No Implementation Action",
                effective_state="Evidence Review Continues",
            ),
            "Not Complete",
        )
        self.assertEqual(
            self.admin_session._archive_completion(
                archive_classification="Archived",
                archive_preconditions="Archive Preconditions Satisfied",
                archive_pathway="Archived",
                archive_readiness="Archived",
                archive_determination="Archived",
                closure_classification="Closed With Resolution",
                closure_completion="Complete",
                closure_determination="Determination Complete",
                closure_readiness="Ready",
                resolution_classification="Resolved",
                resolution_completion="Completion Confirmed",
                resolution_determination="Determination Complete",
                outcome_readiness="Ready",
                review_eligibility="Eligible",
                administrative_status="Archived",
                implementation_action="Prepare Formal Review Implementation",
                effective_state="Archived",
            ),
            "Complete",
        )
        self.assertEqual(
            self.admin_session._describe_archive_completion("Not Complete"),
            (
                "Archive completion has not been reached because "
                "prerequisite archive determination conditions remain "
                "unsatisfied."
            ),
        )
        self.assertEqual(
            self.admin_session._describe_archive_completion("Complete"),
            (
                "Archive completion confirms that archive progression has "
                "concluded."
            ),
        )

    def test_admin_record_evidence_view_requires_session(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            conn.close()
            try:
                with self.env():
                    with self.assertRaises(Exception) as ctx:
                        self.admin_session.admin_record_evidence_page(
                            "Strike-OT-20260604-ADMIN",
                            FakeRequest(),
                        )
            finally:
                self.admin_session.DB_PATH = original_db_path

        self.assertEqual(getattr(ctx.exception, "status_code", None), 401)

    def test_admin_relationship_form_renders_no_available_targets_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            conn.execute("""
                UPDATE records
                SET conditions_json = '[]', signals_json = '[]', finding = ''
                WHERE reference = 'Strike-OT-20260604-ADMIN'
                """)
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

        self.assertIn(
            '<option value="" disabled selected>No available targets</option>',
            content,
        )
        self.assertIn("Evidence Relationships (0)", content)
        self.assertIn("<strong>Status:</strong> Unlinked", content)
        self.assertIn(
            "<strong>Reason:</strong> No active evidence relationships have been created.",
            content,
        )
        self.assertIn("<td>Conditions linked</td><td>0 / 0</td>", content)
        self.assertIn("<td>Signals linked</td><td>0 / 0</td>", content)
        self.assertIn("<td>Findings linked</td><td>0 / 0</td>", content)
        self.assertIn("<td>Records linked</td><td>0 / 1</td>", content)
        self.assertIn("No active evidence relationships.", content)
        self.assertIn("data-relationship-submit disabled", content)

    def test_admin_relationship_coverage_explains_partial_after_conditions_complete(
        self,
    ):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            self.insert_admin_attachment(conn)
            for condition in (
                "INSTITUTIONAL_DELAY",
                "PROCEDURAL_DEFLECTION",
                "REPEATED_CONTACT_WITHOUT_RESOLUTION",
                "Transfer of Burden",
                "Escalation Without Response",
            ):
                self.insert_attachment_relationship(
                    conn,
                    target_type="condition",
                    target_key=condition,
                )
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

        self.assertIn("Evidence Relationships (5)", content)
        self.assertIn("<strong>Status:</strong> Partial", content)
        self.assertIn(
            "<strong>Reason:</strong> Conditions complete. Signals, findings, or record targets remain unlinked.",
            content,
        )
        self.assertIn("<td>Conditions linked</td><td>5 / 5</td>", content)
        self.assertIn("<td>Signals linked</td><td>0 / 2</td>", content)
        self.assertIn("<td>Findings linked</td><td>0 / 1</td>", content)
        self.assertIn("<td>Records linked</td><td>0 / 1</td>", content)
        self.assertIn("<summary>Conditions (5)</summary>", content)
        self.assertNotIn("Unlinked Conditions", content)

    def test_admin_relationship_coverage_complete_when_all_targets_are_linked(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            conn.execute(
                """
                UPDATE records
                SET conditions_json = ?, signals_json = '[]', finding = ''
                WHERE reference = 'Strike-OT-20260604-ADMIN'
                """,
                (json.dumps(["TRANSFER_OF_BURDEN"]),),
            )
            self.insert_admin_attachment(conn)
            self.insert_attachment_relationship(
                conn,
                target_type="condition",
                target_key="TRANSFER_OF_BURDEN",
            )
            self.insert_attachment_relationship(
                conn,
                relationship_type="context_for",
                target_type="record",
                target_key="Strike-OT-20260604-ADMIN",
            )
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

        self.assertIn("Evidence Relationships (2)", content)
        self.assertIn("<strong>Status:</strong> Complete", content)
        self.assertIn(
            "<strong>Reason:</strong> All available targets are linked.", content
        )
        self.assertIn("<td>Conditions linked</td><td>1 / 1</td>", content)
        self.assertIn("<td>Signals linked</td><td>0 / 0</td>", content)
        self.assertIn("<td>Findings linked</td><td>0 / 0</td>", content)
        self.assertIn("<td>Records linked</td><td>1 / 1</td>", content)
        self.assertIn("<summary>Conditions (1)</summary>", content)
        self.assertIn("<summary>Records (1)</summary>", content)
        self.assertIn("→ Transfer Of Burden", content)
        self.assertIn('data-target-key="TRANSFER_OF_BURDEN"', content)
        self.assertNotIn("Unlinked Conditions", content)

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
        self.assertIn(
            "No audit events are currently recorded for this record.",
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

    def test_metadata_correction_requires_admin_session(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            self.insert_admin_attachment(conn)
            attachment_id = conn.execute(
                "SELECT id FROM record_attachments"
            ).fetchone()["id"]
            conn.close()
            try:
                with self.env():
                    with self.assertRaises(Exception) as ctx:
                        self.admin_session.correct_attachment_metadata_route(
                            "Strike-OT-20260604-ADMIN",
                            attachment_id,
                            FakeRequest(),
                            {"title": "Corrected title"},
                        )
            finally:
                self.admin_session.DB_PATH = original_db_path

        self.assertEqual(getattr(ctx.exception, "status_code", None), 401)

    def test_metadata_correction_updates_allowed_fields_and_writes_audit_event(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            stored_path = Path(temp_dir) / "attachment.pdf"
            stored_bytes = b"%PDF-1.4 unchanged"
            stored_path.write_bytes(stored_bytes)
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            self.insert_admin_attachment(
                conn,
                storage_path=str(stored_path),
                stored_filename=stored_path.name,
                title="Original title",
                description="Original description",
                source_label="Original source",
                document_date="2026-06-04",
                document_date_precision="day",
                publication_status="published",
                redaction_note="Original redaction note",
            )
            attachment_id = conn.execute(
                "SELECT id FROM record_attachments"
            ).fetchone()["id"]
            before = dict(
                conn.execute(
                    "SELECT * FROM record_attachments WHERE id = ?",
                    (attachment_id,),
                ).fetchone()
            )
            before_manifest = public_manifest_attachments(
                conn,
                reference="Strike-OT-20260604-ADMIN",
                record_version=1,
            )
            conn.close()
            try:
                with self.env():
                    response = self.admin_session.correct_attachment_metadata_route(
                        "Strike-OT-20260604-ADMIN",
                        attachment_id,
                        self.valid_request(),
                        {
                            "title": "Corrected title",
                            "description": "Corrected description",
                            "source_label": "Corrected source",
                            "document_date": "2026-06",
                            "document_date_precision": "month",
                            "redaction_note": "Corrected redaction note",
                        },
                    )
                conn = sqlite3.connect(self.admin_session.DB_PATH)
                conn.row_factory = sqlite3.Row
                try:
                    after = dict(
                        conn.execute(
                            "SELECT * FROM record_attachments WHERE id = ?",
                            (attachment_id,),
                        ).fetchone()
                    )
                    audit = dict(
                        conn.execute("SELECT * FROM attachment_audit_events").fetchone()
                    )
                    after_manifest = public_manifest_attachments(
                        conn,
                        reference="Strike-OT-20260604-ADMIN",
                        record_version=1,
                    )
                    stored_file_bytes_after = stored_path.read_bytes()
                finally:
                    conn.close()
            finally:
                self.admin_session.DB_PATH = original_db_path

        serialized_response = json.dumps(response.content, sort_keys=True)
        audit_metadata = json.loads(audit["metadata_json"])

        self.assertTrue(response.content["ok"])
        self.assertEqual(response.content["attachment"]["title"], "Corrected title")
        self.assertEqual(
            response.content["attachment"]["description"], "Corrected description"
        )
        self.assertEqual(
            response.content["attachment"]["source_label"], "Corrected source"
        )
        self.assertEqual(response.content["attachment"]["document_date"], "2026-06")
        self.assertEqual(
            response.content["attachment"]["document_date_precision"], "month"
        )
        self.assertEqual(
            response.content["changed_fields"],
            [
                "title",
                "description",
                "source_label",
                "document_date",
                "document_date_precision",
                "redaction_note",
            ],
        )
        self.assertEqual(after["title"], "Corrected title")
        self.assertEqual(after["description"], "Corrected description")
        self.assertEqual(after["source_label"], "Corrected source")
        self.assertEqual(after["document_date"], "2026-06")
        self.assertEqual(after["document_date_precision"], "month")
        self.assertEqual(after["redaction_note"], "Corrected redaction note")
        self.assertEqual(after["sha256_hash"], before["sha256_hash"])
        self.assertEqual(after["storage_path"], before["storage_path"])
        self.assertEqual(after["stored_filename"], before["stored_filename"])
        self.assertEqual(stored_file_bytes_after, stored_bytes)
        for immutable in (
            "reference",
            "record_version",
            "attachment_version",
            "filename",
            "stored_filename",
            "storage_path",
            "content_type",
            "file_size_bytes",
            "sha256_hash",
            "visibility",
            "redaction_status",
            "publication_status",
            "is_latest",
            "is_deleted",
            "uploaded_at",
        ):
            self.assertEqual(after[immutable], before[immutable])
        self.assertEqual(audit["event_type"], "attachment_metadata_corrected")
        self.assertEqual(audit["reference"], "Strike-OT-20260604-ADMIN")
        self.assertEqual(audit["attachment_id"], attachment_id)
        self.assertEqual(audit["record_version"], 1)
        self.assertEqual(
            audit_metadata["changed_fields"],
            [
                "title",
                "description",
                "source_label",
                "document_date",
                "document_date_precision",
                "redaction_note",
            ],
        )
        self.assertEqual(audit_metadata["previous_values"]["title"], "Original title")
        self.assertEqual(audit_metadata["new_values"]["title"], "Corrected title")
        self.assertEqual(before_manifest[0]["title"], "Original title")
        self.assertEqual(after_manifest[0]["title"], "Corrected title")
        self.assertEqual(after_manifest[0]["filename"], before_manifest[0]["filename"])
        self.assertNotIn("storage_path", serialized_response)
        self.assertNotIn("stored_filename", serialized_response)
        self.assertNotIn(str(stored_path), serialized_response)
        self.assertNotIn("server-only-token", serialized_response)
        self.assertNotIn("CDE_ADMIN_TOKEN", serialized_response)
        self.assertNotIn("storage_path", audit["metadata_json"])
        self.assertNotIn("stored_filename", audit["metadata_json"])
        self.assertNotIn("CDE_ADMIN_TOKEN", audit["metadata_json"])

    def test_metadata_correction_allows_empty_optional_values_as_null(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            self.insert_admin_attachment(conn)
            attachment_id = conn.execute(
                "SELECT id FROM record_attachments"
            ).fetchone()["id"]
            conn.close()
            try:
                with self.env():
                    response = self.admin_session.correct_attachment_metadata_route(
                        "Strike-OT-20260604-ADMIN",
                        attachment_id,
                        self.valid_request(),
                        {
                            "title": "",
                            "description": None,
                            "source_label": "",
                            "document_date": None,
                            "document_date_precision": "unknown",
                            "redaction_note": "",
                        },
                    )
                after = self.fetch_attachment_row(
                    self.admin_session.DB_PATH, attachment_id
                )
            finally:
                self.admin_session.DB_PATH = original_db_path

        self.assertIsNone(after["title"])
        self.assertIsNone(after["description"])
        self.assertIsNone(after["source_label"])
        self.assertIsNone(after["document_date"])
        self.assertEqual(after["document_date_precision"], "unknown")
        self.assertIsNone(after["redaction_note"])
        self.assertEqual(
            response.content["attachment"]["document_date_precision"], "unknown"
        )

    def test_metadata_correction_rejects_unknown_field(self):
        self.assert_metadata_correction_rejected(
            {"unexpected": "value"},
            400,
            "metadata_field_unknown",
        )

    def test_metadata_correction_rejects_immutable_field(self):
        self.assert_metadata_correction_rejected(
            {"sha256_hash": "e" * 64},
            400,
            "metadata_field_immutable",
        )

    def test_metadata_correction_rejects_invalid_document_date(self):
        self.assert_metadata_correction_rejected(
            {"document_date": "2026-02-31", "document_date_precision": "day"},
            400,
            "document_date_invalid",
        )

    def test_metadata_correction_wrong_reference_and_missing_attachment_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            self.insert_admin_attachment(conn)
            attachment_id = conn.execute(
                "SELECT id FROM record_attachments"
            ).fetchone()["id"]
            conn.close()
            try:
                with self.env():
                    with self.assertRaises(Exception) as wrong_ref:
                        self.admin_session.correct_attachment_metadata_route(
                            "Strike-OT-20260604-WRONG",
                            attachment_id,
                            self.valid_request(),
                            {"title": "Corrected title"},
                        )
                    with self.assertRaises(Exception) as missing:
                        self.admin_session.correct_attachment_metadata_route(
                            "Strike-OT-20260604-ADMIN",
                            attachment_id + 99,
                            self.valid_request(),
                            {"title": "Corrected title"},
                        )
                after = self.fetch_attachment_row(
                    self.admin_session.DB_PATH, attachment_id
                )
            finally:
                self.admin_session.DB_PATH = original_db_path

        self.assertEqual(getattr(wrong_ref.exception, "status_code", None), 404)
        self.assertEqual(getattr(missing.exception, "status_code", None), 404)
        self.assertEqual(after["title"], "Public attachment")

    def test_classification_update_requires_admin_session(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            self.insert_admin_attachment(conn)
            attachment_id = conn.execute(
                "SELECT id FROM record_attachments"
            ).fetchone()["id"]
            conn.close()
            try:
                with self.env():
                    with self.assertRaises(Exception) as ctx:
                        self.admin_session.update_attachment_classification_route(
                            "Strike-OT-20260604-ADMIN",
                            attachment_id,
                            FakeRequest(),
                            {"classification": "medical_record"},
                        )
            finally:
                self.admin_session.DB_PATH = original_db_path

        self.assertEqual(getattr(ctx.exception, "status_code", None), 401)

    def test_classification_update_only_changes_classification_and_writes_audit_event(
        self,
    ):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            stored_path = Path(temp_dir) / "attachment.pdf"
            stored_bytes = b"%PDF-1.4 classification unchanged"
            stored_path.write_bytes(stored_bytes)
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            self.insert_admin_attachment(
                conn,
                storage_path=str(stored_path),
                stored_filename=stored_path.name,
                classification="other",
            )
            attachment_id = conn.execute(
                "SELECT id FROM record_attachments"
            ).fetchone()["id"]
            before = dict(
                conn.execute(
                    "SELECT * FROM record_attachments WHERE id = ?",
                    (attachment_id,),
                ).fetchone()
            )
            before_manifest = public_manifest_attachments(
                conn,
                reference="Strike-OT-20260604-ADMIN",
                record_version=1,
            )
            conn.close()
            try:
                with self.env():
                    response = (
                        self.admin_session.update_attachment_classification_route(
                            "Strike-OT-20260604-ADMIN",
                            attachment_id,
                            self.valid_request(),
                            {"classification": "medical_record"},
                        )
                    )
                conn = sqlite3.connect(self.admin_session.DB_PATH)
                conn.row_factory = sqlite3.Row
                try:
                    after = dict(
                        conn.execute(
                            "SELECT * FROM record_attachments WHERE id = ?",
                            (attachment_id,),
                        ).fetchone()
                    )
                    audit = dict(
                        conn.execute("SELECT * FROM attachment_audit_events").fetchone()
                    )
                    after_manifest = public_manifest_attachments(
                        conn,
                        reference="Strike-OT-20260604-ADMIN",
                        record_version=1,
                    )
                    stored_file_bytes_after = stored_path.read_bytes()
                finally:
                    conn.close()
                with self.env():
                    page_response = self.admin_session.admin_record_attachments_page(
                        "Strike-OT-20260604-ADMIN",
                        self.valid_request(),
                    )
            finally:
                self.admin_session.DB_PATH = original_db_path

        serialized_response = json.dumps(response.content, sort_keys=True)
        audit_metadata = json.loads(audit["metadata_json"])
        page_content = page_response.content

        self.assertTrue(response.content["ok"])
        self.assertEqual(
            response.content["attachment"]["classification"], "medical_record"
        )
        self.assertEqual(before["classification"], "other")
        self.assertEqual(after["classification"], "medical_record")
        for preserved in (
            "reference",
            "record_version",
            "attachment_version",
            "filename",
            "stored_filename",
            "storage_path",
            "content_type",
            "file_size_bytes",
            "sha256_hash",
            "visibility",
            "redaction_status",
            "is_latest",
            "is_deleted",
            "uploaded_at",
        ):
            self.assertEqual(after[preserved], before[preserved])
        self.assertEqual(stored_file_bytes_after, stored_bytes)
        self.assertEqual(before_manifest, after_manifest)
        self.assertEqual(audit["event_type"], "attachment_classification_updated")
        self.assertEqual(audit["reference"], "Strike-OT-20260604-ADMIN")
        self.assertEqual(audit["attachment_id"], attachment_id)
        self.assertEqual(audit["record_version"], 1)
        self.assertEqual(audit_metadata["previous_classification"], "other")
        self.assertEqual(audit_metadata["new_classification"], "medical_record")
        self.assertIn(
            '<span class="summary-meta">medical_record • active • public • none • internal</span>',
            page_content,
        )
        self.assertIn("<td>Classification</td><td>medical_record</td>", page_content)
        self.assertIn(
            '<span class="event-badge">[classification updated]</span>',
            page_content,
        )
        self.assertNotIn("storage_path", audit["metadata_json"])
        self.assertNotIn("stored_filename", audit["metadata_json"])
        self.assertNotIn(str(stored_path), audit["metadata_json"])
        self.assertNotIn("CDE_ADMIN_TOKEN", audit["metadata_json"])
        self.assertNotIn("storage_path", serialized_response)
        self.assertNotIn("stored_filename", serialized_response)
        self.assertNotIn(str(stored_path), serialized_response)
        self.assertNotIn("server-only-token", serialized_response)
        self.assertNotIn("CDE_ADMIN_TOKEN", serialized_response)

    def test_classification_update_rejects_invalid_payload(self):
        self.assert_classification_update_rejected(
            {"classification": "secret_internal"},
            400,
            "classification_invalid",
        )
        self.assert_classification_update_rejected(
            {"classification": "medical_record", "storage_path": "/private/file.pdf"},
            400,
            "classification_payload_invalid",
        )

    def test_classification_update_wrong_reference_and_missing_attachment_rejected(
        self,
    ):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            self.insert_admin_attachment(conn)
            attachment_id = conn.execute(
                "SELECT id FROM record_attachments"
            ).fetchone()["id"]
            before = dict(
                conn.execute(
                    "SELECT * FROM record_attachments WHERE id = ?",
                    (attachment_id,),
                ).fetchone()
            )
            conn.close()
            try:
                with self.env():
                    with self.assertRaises(Exception) as wrong_ref:
                        self.admin_session.update_attachment_classification_route(
                            "Strike-OT-20260604-WRONG",
                            attachment_id,
                            self.valid_request(),
                            {"classification": "medical_record"},
                        )
                    with self.assertRaises(Exception) as missing:
                        self.admin_session.update_attachment_classification_route(
                            "Strike-OT-20260604-ADMIN",
                            attachment_id + 99,
                            self.valid_request(),
                            {"classification": "medical_record"},
                        )
                after = self.fetch_attachment_row(
                    self.admin_session.DB_PATH, attachment_id
                )
                conn = sqlite3.connect(self.admin_session.DB_PATH)
                try:
                    audit_count = conn.execute(
                        "SELECT COUNT(*) FROM attachment_audit_events"
                    ).fetchone()[0]
                finally:
                    conn.close()
            finally:
                self.admin_session.DB_PATH = original_db_path

        self.assertEqual(getattr(wrong_ref.exception, "status_code", None), 404)
        self.assertEqual(getattr(missing.exception, "status_code", None), 404)
        self.assertEqual(after, before)
        self.assertEqual(audit_count, 0)

    def test_publication_update_requires_admin_session(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            self.insert_admin_attachment(conn)
            attachment_id = conn.execute(
                "SELECT id FROM record_attachments"
            ).fetchone()["id"]
            conn.close()
            try:
                with self.env():
                    with self.assertRaises(Exception) as ctx:
                        self.admin_session.update_attachment_publication_route(
                            "Strike-OT-20260604-ADMIN",
                            attachment_id,
                            FakeRequest(),
                            {"publication_status": "published"},
                        )
            finally:
                self.admin_session.DB_PATH = original_db_path

        self.assertEqual(getattr(ctx.exception, "status_code", None), 401)

    def test_publication_update_only_changes_status_and_writes_audit_event(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            stored_path = Path(temp_dir) / "attachment.pdf"
            stored_bytes = b"%PDF-1.4 publication unchanged"
            stored_path.write_bytes(stored_bytes)
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            self.insert_admin_attachment(
                conn,
                storage_path=str(stored_path),
                stored_filename=stored_path.name,
                classification="evidence",
                publication_status="internal",
            )
            attachment_id = conn.execute(
                "SELECT id FROM record_attachments"
            ).fetchone()["id"]
            before = dict(
                conn.execute(
                    "SELECT * FROM record_attachments WHERE id = ?",
                    (attachment_id,),
                ).fetchone()
            )
            before_manifest = public_manifest_attachments(
                conn,
                reference="Strike-OT-20260604-ADMIN",
                record_version=1,
            )
            conn.close()
            try:
                with self.env():
                    response = self.admin_session.update_attachment_publication_route(
                        "Strike-OT-20260604-ADMIN",
                        attachment_id,
                        self.valid_request(),
                        {"publication_status": "published"},
                    )
                conn = sqlite3.connect(self.admin_session.DB_PATH)
                conn.row_factory = sqlite3.Row
                try:
                    after = dict(
                        conn.execute(
                            "SELECT * FROM record_attachments WHERE id = ?",
                            (attachment_id,),
                        ).fetchone()
                    )
                    audit = dict(
                        conn.execute("SELECT * FROM attachment_audit_events").fetchone()
                    )
                    after_manifest = public_manifest_attachments(
                        conn,
                        reference="Strike-OT-20260604-ADMIN",
                        record_version=1,
                    )
                    stored_file_bytes_after = stored_path.read_bytes()
                finally:
                    conn.close()
                with self.env():
                    page_response = self.admin_session.admin_record_attachments_page(
                        "Strike-OT-20260604-ADMIN",
                        self.valid_request(),
                    )
            finally:
                self.admin_session.DB_PATH = original_db_path

        serialized_response = json.dumps(response.content, sort_keys=True)
        audit_metadata = json.loads(audit["metadata_json"])
        page_content = page_response.content

        self.assertTrue(response.content["ok"])
        self.assertEqual(
            response.content["attachment"]["publication_status"], "published"
        )
        self.assertEqual(before["publication_status"], "internal")
        self.assertEqual(after["publication_status"], "published")
        for preserved in (
            "reference",
            "record_version",
            "attachment_version",
            "filename",
            "stored_filename",
            "storage_path",
            "content_type",
            "file_size_bytes",
            "sha256_hash",
            "visibility",
            "redaction_status",
            "classification",
            "is_latest",
            "is_deleted",
            "uploaded_at",
        ):
            self.assertEqual(after[preserved], before[preserved])
        self.assertEqual(stored_file_bytes_after, stored_bytes)
        self.assertEqual(before_manifest, [])
        self.assertEqual(len(after_manifest), 1)
        self.assertEqual(after_manifest[0]["filename"], before["filename"])
        self.assertEqual(audit["event_type"], "attachment_publication_updated")
        self.assertEqual(audit["reference"], "Strike-OT-20260604-ADMIN")
        self.assertEqual(audit["attachment_id"], attachment_id)
        self.assertEqual(audit["record_version"], 1)
        self.assertEqual(audit_metadata["previous_publication_status"], "internal")
        self.assertEqual(audit_metadata["new_publication_status"], "published")
        self.assertIn(
            '<span class="summary-meta">evidence • active • public • none • published</span>',
            page_content,
        )
        self.assertIn("<td>Publication status</td><td>published</td>", page_content)
        self.assertIn(
            '<span class="event-badge">[publication updated]</span>',
            page_content,
        )
        self.assertNotIn("storage_path", audit["metadata_json"])
        self.assertNotIn("stored_filename", audit["metadata_json"])
        self.assertNotIn(str(stored_path), audit["metadata_json"])
        self.assertNotIn("CDE_ADMIN_TOKEN", audit["metadata_json"])
        self.assertNotIn("storage_path", serialized_response)
        self.assertNotIn("stored_filename", serialized_response)
        self.assertNotIn(str(stored_path), serialized_response)
        self.assertNotIn("server-only-token", serialized_response)
        self.assertNotIn("CDE_ADMIN_TOKEN", serialized_response)

    def test_publication_update_rejects_invalid_payload(self):
        self.assert_publication_update_rejected(
            {"publication_status": "public_now"},
            400,
            "publication_status_invalid",
        )
        self.assert_publication_update_rejected(
            {"publication_status": "published", "storage_path": "/private/file.pdf"},
            400,
            "publication_payload_invalid",
        )

    def test_publication_update_wrong_reference_and_missing_attachment_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            self.insert_admin_attachment(conn)
            attachment_id = conn.execute(
                "SELECT id FROM record_attachments"
            ).fetchone()["id"]
            before = dict(
                conn.execute(
                    "SELECT * FROM record_attachments WHERE id = ?",
                    (attachment_id,),
                ).fetchone()
            )
            conn.close()
            try:
                with self.env():
                    with self.assertRaises(Exception) as wrong_ref:
                        self.admin_session.update_attachment_publication_route(
                            "Strike-OT-20260604-WRONG",
                            attachment_id,
                            self.valid_request(),
                            {"publication_status": "published"},
                        )
                    with self.assertRaises(Exception) as missing:
                        self.admin_session.update_attachment_publication_route(
                            "Strike-OT-20260604-ADMIN",
                            attachment_id + 99,
                            self.valid_request(),
                            {"publication_status": "published"},
                        )
                after = self.fetch_attachment_row(
                    self.admin_session.DB_PATH, attachment_id
                )
                conn = sqlite3.connect(self.admin_session.DB_PATH)
                try:
                    audit_count = conn.execute(
                        "SELECT COUNT(*) FROM attachment_audit_events"
                    ).fetchone()[0]
                finally:
                    conn.close()
            finally:
                self.admin_session.DB_PATH = original_db_path

        self.assertEqual(getattr(wrong_ref.exception, "status_code", None), 404)
        self.assertEqual(getattr(missing.exception, "status_code", None), 404)
        self.assertEqual(after, before)
        self.assertEqual(audit_count, 0)

    def test_visibility_update_requires_admin_session(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            self.insert_admin_attachment(conn)
            attachment_id = conn.execute(
                "SELECT id FROM record_attachments"
            ).fetchone()["id"]
            conn.close()
            try:
                with self.env():
                    with self.assertRaises(Exception) as ctx:
                        self.admin_session.update_attachment_visibility_route(
                            "Strike-OT-20260604-ADMIN",
                            attachment_id,
                            FakeRequest(),
                            {"visibility": "public"},
                        )
            finally:
                self.admin_session.DB_PATH = original_db_path

        self.assertEqual(getattr(ctx.exception, "status_code", None), 401)

    def test_visibility_update_only_changes_visibility_and_writes_audit_event(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            stored_path = Path(temp_dir) / "attachment.pdf"
            stored_bytes = b"%PDF-1.4 visibility unchanged"
            stored_path.write_bytes(stored_bytes)
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            self.insert_admin_attachment(
                conn,
                storage_path=str(stored_path),
                stored_filename=stored_path.name,
                classification="evidence",
                publication_status="published",
                visibility="private",
            )
            attachment_id = conn.execute(
                "SELECT id FROM record_attachments"
            ).fetchone()["id"]
            before = dict(
                conn.execute(
                    "SELECT * FROM record_attachments WHERE id = ?",
                    (attachment_id,),
                ).fetchone()
            )
            before_manifest = public_manifest_attachments(
                conn,
                reference="Strike-OT-20260604-ADMIN",
                record_version=1,
            )
            before_evidence_manifest = public_evidence_manifest_attachments(
                conn,
                reference="Strike-OT-20260604-ADMIN",
                record_version=1,
            )
            conn.close()
            try:
                with self.env():
                    response = self.admin_session.update_attachment_visibility_route(
                        "Strike-OT-20260604-ADMIN",
                        attachment_id,
                        self.valid_request(),
                        {"visibility": "public"},
                    )
                conn = sqlite3.connect(self.admin_session.DB_PATH)
                conn.row_factory = sqlite3.Row
                try:
                    after = dict(
                        conn.execute(
                            "SELECT * FROM record_attachments WHERE id = ?",
                            (attachment_id,),
                        ).fetchone()
                    )
                    audit = dict(
                        conn.execute("SELECT * FROM attachment_audit_events").fetchone()
                    )
                    after_manifest = public_manifest_attachments(
                        conn,
                        reference="Strike-OT-20260604-ADMIN",
                        record_version=1,
                    )
                    after_evidence_manifest = public_evidence_manifest_attachments(
                        conn,
                        reference="Strike-OT-20260604-ADMIN",
                        record_version=1,
                    )
                    stored_file_bytes_after = stored_path.read_bytes()
                finally:
                    conn.close()
                with self.env():
                    page_response = self.admin_session.admin_record_attachments_page(
                        "Strike-OT-20260604-ADMIN",
                        self.valid_request(),
                    )
            finally:
                self.admin_session.DB_PATH = original_db_path

        serialized_response = json.dumps(response.content, sort_keys=True)
        audit_metadata = json.loads(audit["metadata_json"])
        page_content = page_response.content

        self.assertTrue(response.content["ok"])
        self.assertEqual(response.content["attachment"]["visibility"], "public")
        self.assertEqual(before["visibility"], "private")
        self.assertEqual(after["visibility"], "public")
        for preserved in (
            "reference",
            "record_version",
            "attachment_version",
            "filename",
            "stored_filename",
            "storage_path",
            "content_type",
            "file_size_bytes",
            "sha256_hash",
            "classification",
            "publication_status",
            "redaction_status",
            "is_latest",
            "is_deleted",
            "uploaded_at",
        ):
            self.assertEqual(after[preserved], before[preserved])
        self.assertEqual(stored_file_bytes_after, stored_bytes)
        self.assertEqual(before_manifest, [])
        self.assertEqual(before_evidence_manifest, [])
        self.assertEqual(len(after_manifest), 1)
        self.assertEqual(after_manifest[0]["filename"], before["filename"])
        self.assertEqual(len(after_evidence_manifest), 1)
        self.assertEqual(after_evidence_manifest[0]["filename"], before["filename"])
        self.assertEqual(audit["event_type"], "attachment_visibility_updated")
        self.assertEqual(audit["reference"], "Strike-OT-20260604-ADMIN")
        self.assertEqual(audit["attachment_id"], attachment_id)
        self.assertEqual(audit["record_version"], 1)
        self.assertEqual(audit_metadata["previous_visibility"], "private")
        self.assertEqual(audit_metadata["new_visibility"], "public")
        self.assertIn(
            '<span class="summary-meta">evidence • active • public • none • published</span>',
            page_content,
        )
        self.assertIn("<td>Visibility</td><td>public</td>", page_content)
        self.assertIn(
            '<span class="event-badge">[visibility updated]</span>',
            page_content,
        )
        self.assertNotIn("storage_path", audit["metadata_json"])
        self.assertNotIn("stored_filename", audit["metadata_json"])
        self.assertNotIn(str(stored_path), audit["metadata_json"])
        self.assertNotIn("CDE_ADMIN_TOKEN", audit["metadata_json"])
        self.assertNotIn("storage_path", serialized_response)
        self.assertNotIn("stored_filename", serialized_response)
        self.assertNotIn(str(stored_path), serialized_response)
        self.assertNotIn("server-only-token", serialized_response)
        self.assertNotIn("CDE_ADMIN_TOKEN", serialized_response)

    def test_visibility_update_rejects_invalid_payload(self):
        self.assert_visibility_update_rejected(
            {"visibility": "restricted"},
            400,
            "visibility_invalid",
        )
        self.assert_visibility_update_rejected(
            {"visibility": "public", "storage_path": "/private/file.pdf"},
            400,
            "visibility_payload_invalid",
        )

    def test_visibility_update_wrong_reference_and_missing_attachment_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            self.insert_admin_attachment(conn)
            attachment_id = conn.execute(
                "SELECT id FROM record_attachments"
            ).fetchone()["id"]
            before = dict(
                conn.execute(
                    "SELECT * FROM record_attachments WHERE id = ?",
                    (attachment_id,),
                ).fetchone()
            )
            conn.close()
            try:
                with self.env():
                    with self.assertRaises(Exception) as wrong_ref:
                        self.admin_session.update_attachment_visibility_route(
                            "Strike-OT-20260604-WRONG",
                            attachment_id,
                            self.valid_request(),
                            {"visibility": "public"},
                        )
                    with self.assertRaises(Exception) as missing:
                        self.admin_session.update_attachment_visibility_route(
                            "Strike-OT-20260604-ADMIN",
                            attachment_id + 99,
                            self.valid_request(),
                            {"visibility": "public"},
                        )
                after = self.fetch_attachment_row(
                    self.admin_session.DB_PATH, attachment_id
                )
                conn = sqlite3.connect(self.admin_session.DB_PATH)
                try:
                    audit_count = conn.execute(
                        "SELECT COUNT(*) FROM attachment_audit_events"
                    ).fetchone()[0]
                finally:
                    conn.close()
            finally:
                self.admin_session.DB_PATH = original_db_path

        self.assertEqual(getattr(wrong_ref.exception, "status_code", None), 404)
        self.assertEqual(getattr(missing.exception, "status_code", None), 404)
        self.assertEqual(after, before)
        self.assertEqual(audit_count, 0)

    def test_relationship_add_requires_admin_session(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            self.insert_admin_attachment(conn)
            attachment_id = conn.execute(
                "SELECT id FROM record_attachments"
            ).fetchone()["id"]
            conn.close()
            try:
                with self.env():
                    with self.assertRaises(Exception) as ctx:
                        self.admin_session.add_attachment_relationship_route(
                            "Strike-OT-20260604-ADMIN",
                            attachment_id,
                            FakeRequest(),
                            {
                                "relationship_type": "supports",
                                "target_type": "condition",
                                "target_key": "Transfer of Burden",
                            },
                        )
            finally:
                self.admin_session.DB_PATH = original_db_path

        self.assertEqual(getattr(ctx.exception, "status_code", None), 401)

    def test_relationship_add_trims_target_key_preserves_attachment_and_writes_audit_event(
        self,
    ):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            stored_path = Path(temp_dir) / "attachment.pdf"
            stored_bytes = b"%PDF-1.4 relationship unchanged"
            stored_path.write_bytes(stored_bytes)
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            self.insert_admin_attachment(
                conn,
                storage_path=str(stored_path),
                stored_filename=stored_path.name,
                classification="evidence",
                publication_status="published",
            )
            attachment_id = conn.execute(
                "SELECT id FROM record_attachments"
            ).fetchone()["id"]
            before = dict(
                conn.execute(
                    "SELECT * FROM record_attachments WHERE id = ?",
                    (attachment_id,),
                ).fetchone()
            )
            before_manifest = public_manifest_attachments(
                conn,
                reference="Strike-OT-20260604-ADMIN",
                record_version=1,
            )
            conn.close()
            try:
                with self.env():
                    response = self.admin_session.add_attachment_relationship_route(
                        "Strike-OT-20260604-ADMIN",
                        attachment_id,
                        self.valid_request(),
                        {
                            "relationship_type": "supports",
                            "target_type": "condition",
                            "target_key": "  Transfer of Burden  ",
                        },
                    )
                conn = sqlite3.connect(self.admin_session.DB_PATH)
                conn.row_factory = sqlite3.Row
                try:
                    after = dict(
                        conn.execute(
                            "SELECT * FROM record_attachments WHERE id = ?",
                            (attachment_id,),
                        ).fetchone()
                    )
                    relationship = dict(
                        conn.execute(
                            "SELECT * FROM record_attachment_relationships"
                        ).fetchone()
                    )
                    audit = dict(
                        conn.execute("SELECT * FROM attachment_audit_events").fetchone()
                    )
                    after_manifest = public_manifest_attachments(
                        conn,
                        reference="Strike-OT-20260604-ADMIN",
                        record_version=1,
                    )
                    stored_file_bytes_after = stored_path.read_bytes()
                finally:
                    conn.close()
                with self.env():
                    page_response = self.admin_session.admin_record_attachments_page(
                        "Strike-OT-20260604-ADMIN",
                        self.valid_request(),
                    )
            finally:
                self.admin_session.DB_PATH = original_db_path

        serialized_response = json.dumps(response.content, sort_keys=True)
        audit_metadata = json.loads(audit["metadata_json"])
        page_content = page_response.content

        self.assertTrue(response.content["ok"])
        self.assertEqual(
            response.content["relationship"]["target_key"], "Transfer of Burden"
        )
        self.assertEqual(relationship["relationship_type"], "supports")
        self.assertEqual(relationship["target_type"], "condition")
        self.assertEqual(relationship["target_key"], "Transfer of Burden")
        self.assertEqual(relationship["is_active"], 1)
        self.assertEqual(after, before)
        self.assertEqual(stored_file_bytes_after, stored_bytes)
        self.assertEqual(after_manifest, before_manifest)
        self.assertEqual(audit["event_type"], "attachment_relationship_added")
        self.assertEqual(audit_metadata["relationship_id"], relationship["id"])
        self.assertEqual(audit_metadata["relationship_type"], "supports")
        self.assertEqual(audit_metadata["target_type"], "condition")
        self.assertEqual(audit_metadata["target_key"], "Transfer of Burden")
        self.assertIn("Evidence Relationships (1)", page_content)
        self.assertIn("supports • condition", page_content)
        self.assertIn("→ Transfer of Burden", page_content)
        self.assertIn('data-target-key="Transfer of Burden"', page_content)
        self.assertIn(
            '<span class="event-badge">[relationship added]</span>',
            page_content,
        )
        for field in (
            "sha256_hash",
            "classification",
            "publication_status",
            "visibility",
            "redaction_status",
            "is_deleted",
        ):
            self.assertEqual(after[field], before[field])
        self.assertNotIn("storage_path", serialized_response)
        self.assertNotIn("stored_filename", serialized_response)
        self.assertNotIn("CDE_ADMIN_TOKEN", serialized_response)
        self.assertNotIn("storage_path", audit["metadata_json"])
        self.assertNotIn("stored_filename", audit["metadata_json"])
        self.assertNotIn("CDE_ADMIN_TOKEN", audit["metadata_json"])

    def test_relationship_add_rejects_invalid_payloads_and_reference_errors(self):
        invalid_payloads = (
            {
                "relationship_type": "unknown",
                "target_type": "condition",
                "target_key": "Transfer",
            },
            {
                "relationship_type": "supports",
                "target_type": "unknown",
                "target_key": "Transfer",
            },
            {
                "relationship_type": "supports",
                "target_type": "condition",
                "target_key": "   ",
            },
            {
                "relationship_type": "supports",
                "target_type": "condition",
                "target_key": "x" * 201,
            },
        )
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                self.assert_relationship_add_rejected(
                    payload, 400, "relationship_payload_invalid"
                )

        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            self.insert_admin_attachment(conn)
            attachment_id = conn.execute(
                "SELECT id FROM record_attachments"
            ).fetchone()["id"]
            before = self.fetch_attachment_row(
                self.admin_session.DB_PATH, attachment_id
            )
            conn.close()
            try:
                with self.env():
                    with self.assertRaises(Exception) as wrong_ref:
                        self.admin_session.add_attachment_relationship_route(
                            "Strike-OT-20260604-WRONG",
                            attachment_id,
                            self.valid_request(),
                            {
                                "relationship_type": "supports",
                                "target_type": "condition",
                                "target_key": "Transfer",
                            },
                        )
                    with self.assertRaises(Exception) as missing:
                        self.admin_session.add_attachment_relationship_route(
                            "Strike-OT-20260604-ADMIN",
                            attachment_id + 99,
                            self.valid_request(),
                            {
                                "relationship_type": "supports",
                                "target_type": "condition",
                                "target_key": "Transfer",
                            },
                        )
                after = self.fetch_attachment_row(
                    self.admin_session.DB_PATH, attachment_id
                )
                conn = sqlite3.connect(self.admin_session.DB_PATH)
                try:
                    relationship_count = conn.execute(
                        "SELECT COUNT(*) FROM record_attachment_relationships"
                    ).fetchone()[0]
                finally:
                    conn.close()
            finally:
                self.admin_session.DB_PATH = original_db_path

        self.assertEqual(getattr(wrong_ref.exception, "status_code", None), 404)
        self.assertEqual(getattr(missing.exception, "status_code", None), 404)
        self.assertEqual(after, before)
        self.assertEqual(relationship_count, 0)

    def test_relationship_remove_marks_inactive_and_writes_audit_event(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            self.insert_admin_attachment(conn)
            attachment_id = conn.execute(
                "SELECT id FROM record_attachments"
            ).fetchone()["id"]
            self.insert_attachment_relationship(conn, attachment_id=attachment_id)
            relationship_id = conn.execute(
                "SELECT id FROM record_attachment_relationships"
            ).fetchone()["id"]
            before = self.fetch_attachment_row(
                self.admin_session.DB_PATH, attachment_id
            )
            conn.close()
            try:
                with self.env():
                    response = self.admin_session.remove_attachment_relationship_route(
                        "Strike-OT-20260604-ADMIN",
                        attachment_id,
                        relationship_id,
                        self.valid_request(),
                    )
                conn = sqlite3.connect(self.admin_session.DB_PATH)
                conn.row_factory = sqlite3.Row
                try:
                    after = self.fetch_attachment_row(
                        self.admin_session.DB_PATH, attachment_id
                    )
                    relationship = dict(
                        conn.execute(
                            "SELECT * FROM record_attachment_relationships WHERE id = ?",
                            (relationship_id,),
                        ).fetchone()
                    )
                    audit = dict(
                        conn.execute("SELECT * FROM attachment_audit_events").fetchone()
                    )
                finally:
                    conn.close()
                with self.env():
                    page_response = self.admin_session.admin_record_attachments_page(
                        "Strike-OT-20260604-ADMIN",
                        self.valid_request(),
                    )
            finally:
                self.admin_session.DB_PATH = original_db_path

        audit_metadata = json.loads(audit["metadata_json"])
        page_content = page_response.content

        self.assertTrue(response.content["ok"])
        self.assertEqual(relationship["is_active"], 0)
        self.assertIsNotNone(relationship["removed_at"])
        self.assertEqual(relationship["removed_by"], "admin")
        self.assertEqual(after, before)
        self.assertEqual(audit["event_type"], "attachment_relationship_removed")
        self.assertEqual(audit_metadata["relationship_id"], relationship_id)
        self.assertEqual(audit_metadata["target_key"], "Transfer of Burden")
        self.assertNotIn("→ Transfer of Burden", page_content)
        self.assertIn("No active evidence relationships.", page_content)
        self.assertIn(
            '<span class="event-badge">[relationship removed]</span>',
            page_content,
        )

    def test_relationship_remove_uses_relationship_id_not_duplicate_target_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            self.insert_admin_attachment(conn)
            attachment_id = conn.execute(
                "SELECT id FROM record_attachments"
            ).fetchone()["id"]
            self.insert_attachment_relationship(
                conn,
                attachment_id=attachment_id,
                target_key="INSTITUTIONAL_DELAY",
            )
            self.insert_attachment_relationship(
                conn,
                attachment_id=attachment_id,
                target_key="INSTITUTIONAL_DELAY",
            )
            relationship_ids = [
                row["id"]
                for row in conn.execute(
                    "SELECT id FROM record_attachment_relationships ORDER BY id"
                ).fetchall()
            ]
            conn.close()
            try:
                with self.env():
                    response = self.admin_session.remove_attachment_relationship_route(
                        "Strike-OT-20260604-ADMIN",
                        attachment_id,
                        relationship_ids[0],
                        self.valid_request(),
                    )
                conn = sqlite3.connect(self.admin_session.DB_PATH)
                conn.row_factory = sqlite3.Row
                try:
                    relationships = [
                        dict(row)
                        for row in conn.execute(
                            "SELECT id, is_active, target_key "
                            "FROM record_attachment_relationships ORDER BY id"
                        ).fetchall()
                    ]
                    audit = dict(
                        conn.execute("SELECT * FROM attachment_audit_events").fetchone()
                    )
                finally:
                    conn.close()
            finally:
                self.admin_session.DB_PATH = original_db_path

        audit_metadata = json.loads(audit["metadata_json"])

        self.assertTrue(response.content["ok"])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(relationships[0]["id"], relationship_ids[0])
        self.assertEqual(relationships[0]["is_active"], 0)
        self.assertEqual(relationships[1]["id"], relationship_ids[1])
        self.assertEqual(relationships[1]["is_active"], 1)
        self.assertEqual(relationships[0]["target_key"], "INSTITUTIONAL_DELAY")
        self.assertEqual(relationships[1]["target_key"], "INSTITUTIONAL_DELAY")
        self.assertEqual(audit["event_type"], "attachment_relationship_removed")
        self.assertEqual(audit_metadata["relationship_id"], relationship_ids[0])
        self.assertEqual(audit_metadata["target_key"], "INSTITUTIONAL_DELAY")

    def test_lifecycle_routes_require_admin_session(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            self.insert_admin_attachment(conn)
            attachment_id = conn.execute(
                "SELECT id FROM record_attachments"
            ).fetchone()["id"]
            conn.close()
            try:
                with self.env():
                    for route in (
                        self.admin_session.withhold_attachment_route,
                        self.admin_session.restore_attachment_route,
                        self.admin_session.soft_delete_attachment_route,
                    ):
                        with self.subTest(route=route.__name__):
                            with self.assertRaises(Exception) as ctx:
                                route(
                                    "Strike-OT-20260604-ADMIN",
                                    attachment_id,
                                    FakeRequest(),
                                )
                            self.assertEqual(
                                getattr(ctx.exception, "status_code", None),
                                401,
                            )
            finally:
                self.admin_session.DB_PATH = original_db_path

    def test_withhold_sets_withheld_hides_manifest_and_writes_audit_event(self):
        result = self.run_lifecycle_action(
            self.admin_session.withhold_attachment_route,
            initial_redaction_status="none",
            initial_is_deleted=0,
        )

        self.assertEqual(result["response"].content["action"], "withhold")
        self.assertEqual(result["after"]["redaction_status"], "withheld")
        self.assertEqual(result["after"]["is_deleted"], 0)
        self.assertEqual(result["after_manifest"], [])
        self.assertEqual(result["audit"]["event_type"], "attachment_withheld")
        self.assertEqual(result["audit_metadata"]["action"], "withhold")
        self.assertEqual(result["audit_metadata"]["previous_redaction_status"], "none")
        self.assertEqual(result["audit_metadata"]["new_redaction_status"], "withheld")
        self.assertEqual(result["audit_metadata"]["previous_is_deleted"], 0)
        self.assertEqual(result["audit_metadata"]["new_is_deleted"], 0)

    def test_soft_delete_sets_deleted_hides_manifest_and_writes_audit_event(self):
        result = self.run_lifecycle_action(
            self.admin_session.soft_delete_attachment_route,
            initial_redaction_status="none",
            initial_is_deleted=0,
        )

        self.assertEqual(result["response"].content["action"], "soft-delete")
        self.assertEqual(result["after"]["redaction_status"], "none")
        self.assertEqual(result["after"]["is_deleted"], 1)
        self.assertEqual(result["after_manifest"], [])
        self.assertEqual(result["audit"]["event_type"], "attachment_soft_deleted")
        self.assertEqual(result["audit_metadata"]["action"], "soft-delete")
        self.assertEqual(result["audit_metadata"]["previous_redaction_status"], "none")
        self.assertEqual(result["audit_metadata"]["new_redaction_status"], "none")
        self.assertEqual(result["audit_metadata"]["previous_is_deleted"], 0)
        self.assertEqual(result["audit_metadata"]["new_is_deleted"], 1)

    def test_restore_clears_deleted_and_withheld_state_and_writes_audit_event(self):
        result = self.run_lifecycle_action(
            self.admin_session.restore_attachment_route,
            initial_redaction_status="withheld",
            initial_is_deleted=1,
        )

        self.assertEqual(result["response"].content["action"], "restore")
        self.assertEqual(result["after"]["redaction_status"], "none")
        self.assertEqual(result["after"]["is_deleted"], 0)
        self.assertEqual(len(result["after_manifest"]), 1)
        self.assertEqual(result["audit"]["event_type"], "attachment_restored")
        self.assertEqual(result["audit_metadata"]["action"], "restore")
        self.assertEqual(
            result["audit_metadata"]["previous_redaction_status"], "withheld"
        )
        self.assertEqual(result["audit_metadata"]["new_redaction_status"], "none")
        self.assertEqual(result["audit_metadata"]["previous_is_deleted"], 1)
        self.assertEqual(result["audit_metadata"]["new_is_deleted"], 0)

    def test_lifecycle_routes_wrong_reference_and_missing_attachment_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            self.insert_admin_attachment(conn)
            attachment_id = conn.execute(
                "SELECT id FROM record_attachments"
            ).fetchone()["id"]
            before = dict(
                conn.execute(
                    "SELECT * FROM record_attachments WHERE id = ?",
                    (attachment_id,),
                ).fetchone()
            )
            conn.close()
            try:
                with self.env():
                    with self.assertRaises(Exception) as wrong_ref:
                        self.admin_session.withhold_attachment_route(
                            "Strike-OT-20260604-WRONG",
                            attachment_id,
                            self.valid_request(),
                        )
                    with self.assertRaises(Exception) as missing:
                        self.admin_session.soft_delete_attachment_route(
                            "Strike-OT-20260604-ADMIN",
                            attachment_id + 99,
                            self.valid_request(),
                        )
                after = self.fetch_attachment_row(
                    self.admin_session.DB_PATH, attachment_id
                )
                conn = sqlite3.connect(self.admin_session.DB_PATH)
                try:
                    audit_count = conn.execute(
                        "SELECT COUNT(*) FROM attachment_audit_events"
                    ).fetchone()[0]
                finally:
                    conn.close()
            finally:
                self.admin_session.DB_PATH = original_db_path

        self.assertEqual(getattr(wrong_ref.exception, "status_code", None), 404)
        self.assertEqual(getattr(missing.exception, "status_code", None), 404)
        self.assertEqual(after, before)
        self.assertEqual(audit_count, 0)

    def test_lifecycle_idempotent_action_records_explicit_audit_event(self):
        result = self.run_lifecycle_action(
            self.admin_session.withhold_attachment_route,
            initial_redaction_status="withheld",
            initial_is_deleted=0,
        )

        self.assertEqual(result["after"]["redaction_status"], "withheld")
        self.assertEqual(result["after"]["is_deleted"], 0)
        self.assertEqual(result["audit"]["event_type"], "attachment_withheld")
        self.assertEqual(
            result["audit_metadata"]["previous_redaction_status"], "withheld"
        )
        self.assertEqual(result["audit_metadata"]["new_redaction_status"], "withheld")

    def run_lifecycle_action(
        self,
        route,
        *,
        initial_redaction_status,
        initial_is_deleted,
    ):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            stored_path = Path(temp_dir) / "attachment.pdf"
            stored_bytes = b"%PDF-1.4 lifecycle unchanged"
            stored_path.write_bytes(stored_bytes)
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            self.insert_admin_attachment(
                conn,
                storage_path=str(stored_path),
                stored_filename=stored_path.name,
                redaction_status=initial_redaction_status,
                is_deleted=initial_is_deleted,
                publication_status="published",
            )
            attachment_id = conn.execute(
                "SELECT id FROM record_attachments"
            ).fetchone()["id"]
            before = dict(
                conn.execute(
                    "SELECT * FROM record_attachments WHERE id = ?",
                    (attachment_id,),
                ).fetchone()
            )
            conn.close()
            try:
                with self.env():
                    response = route(
                        "Strike-OT-20260604-ADMIN",
                        attachment_id,
                        self.valid_request(),
                    )
                conn = sqlite3.connect(self.admin_session.DB_PATH)
                conn.row_factory = sqlite3.Row
                try:
                    after = dict(
                        conn.execute(
                            "SELECT * FROM record_attachments WHERE id = ?",
                            (attachment_id,),
                        ).fetchone()
                    )
                    audit = dict(
                        conn.execute("SELECT * FROM attachment_audit_events").fetchone()
                    )
                    after_manifest = public_manifest_attachments(
                        conn,
                        reference="Strike-OT-20260604-ADMIN",
                        record_version=1,
                    )
                    stored_file_exists_after = stored_path.exists()
                    stored_file_bytes_after = stored_path.read_bytes()
                finally:
                    conn.close()
            finally:
                self.admin_session.DB_PATH = original_db_path

        serialized_response = json.dumps(response.content, sort_keys=True)
        audit_metadata = json.loads(audit["metadata_json"])

        self.assertTrue(response.content["ok"])
        self.assertEqual(response.content["attachment"]["attachment_id"], attachment_id)
        self.assertEqual(after["sha256_hash"], before["sha256_hash"])
        self.assertEqual(after["storage_path"], before["storage_path"])
        self.assertEqual(after["stored_filename"], before["stored_filename"])
        self.assertEqual(after["filename"], before["filename"])
        self.assertEqual(after["content_type"], before["content_type"])
        self.assertEqual(after["file_size_bytes"], before["file_size_bytes"])
        self.assertEqual(after["record_version"], before["record_version"])
        self.assertEqual(after["attachment_version"], before["attachment_version"])
        self.assertEqual(after["uploaded_at"], before["uploaded_at"])
        self.assertTrue(stored_file_exists_after)
        self.assertEqual(stored_file_bytes_after, stored_bytes)
        self.assertEqual(audit["reference"], "Strike-OT-20260604-ADMIN")
        self.assertEqual(audit["attachment_id"], attachment_id)
        self.assertEqual(audit["record_version"], 1)
        self.assertIn("previous_redaction_status", audit_metadata)
        self.assertIn("new_redaction_status", audit_metadata)
        self.assertIn("previous_is_deleted", audit_metadata)
        self.assertIn("new_is_deleted", audit_metadata)
        self.assertNotIn("storage_path", audit["metadata_json"])
        self.assertNotIn("stored_filename", audit["metadata_json"])
        self.assertNotIn(str(stored_path), audit["metadata_json"])
        self.assertNotIn("server-only-token", serialized_response)
        self.assertNotIn("CDE_ADMIN_TOKEN", serialized_response)
        self.assertNotIn("CDE_ADMIN_TOKEN", audit["metadata_json"])
        self.assertNotIn("storage_path", serialized_response)
        self.assertNotIn("stored_filename", serialized_response)
        self.assertNotIn(str(stored_path), serialized_response)

        return {
            "response": response,
            "before": before,
            "after": after,
            "audit": audit,
            "audit_metadata": audit_metadata,
            "after_manifest": after_manifest,
        }

    def assert_metadata_correction_rejected(self, payload, status_code, detail):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            self.insert_admin_attachment(conn)
            attachment_id = conn.execute(
                "SELECT id FROM record_attachments"
            ).fetchone()["id"]
            before = dict(
                conn.execute(
                    "SELECT * FROM record_attachments WHERE id = ?",
                    (attachment_id,),
                ).fetchone()
            )
            conn.close()
            try:
                with self.env():
                    with self.assertRaises(Exception) as ctx:
                        self.admin_session.correct_attachment_metadata_route(
                            "Strike-OT-20260604-ADMIN",
                            attachment_id,
                            self.valid_request(),
                            payload,
                        )
                after = self.fetch_attachment_row(
                    self.admin_session.DB_PATH, attachment_id
                )
                conn = sqlite3.connect(self.admin_session.DB_PATH)
                try:
                    audit_count = conn.execute(
                        "SELECT COUNT(*) FROM attachment_audit_events"
                    ).fetchone()[0]
                finally:
                    conn.close()
            finally:
                self.admin_session.DB_PATH = original_db_path

        self.assertEqual(getattr(ctx.exception, "status_code", None), status_code)
        self.assertEqual(getattr(ctx.exception, "detail", None), detail)
        self.assertEqual(after, before)
        self.assertEqual(audit_count, 0)

    def assert_classification_update_rejected(self, payload, status_code, detail):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            self.insert_admin_attachment(conn)
            attachment_id = conn.execute(
                "SELECT id FROM record_attachments"
            ).fetchone()["id"]
            before = dict(
                conn.execute(
                    "SELECT * FROM record_attachments WHERE id = ?",
                    (attachment_id,),
                ).fetchone()
            )
            conn.close()
            try:
                with self.env():
                    with self.assertRaises(Exception) as ctx:
                        self.admin_session.update_attachment_classification_route(
                            "Strike-OT-20260604-ADMIN",
                            attachment_id,
                            self.valid_request(),
                            payload,
                        )
                after = self.fetch_attachment_row(
                    self.admin_session.DB_PATH, attachment_id
                )
                conn = sqlite3.connect(self.admin_session.DB_PATH)
                try:
                    audit_count = conn.execute(
                        "SELECT COUNT(*) FROM attachment_audit_events"
                    ).fetchone()[0]
                finally:
                    conn.close()
            finally:
                self.admin_session.DB_PATH = original_db_path

        self.assertEqual(getattr(ctx.exception, "status_code", None), status_code)
        self.assertEqual(getattr(ctx.exception, "detail", None), detail)
        self.assertEqual(after, before)
        self.assertEqual(audit_count, 0)

    def assert_publication_update_rejected(self, payload, status_code, detail):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            self.insert_admin_attachment(conn)
            attachment_id = conn.execute(
                "SELECT id FROM record_attachments"
            ).fetchone()["id"]
            before = dict(
                conn.execute(
                    "SELECT * FROM record_attachments WHERE id = ?",
                    (attachment_id,),
                ).fetchone()
            )
            conn.close()
            try:
                with self.env():
                    with self.assertRaises(Exception) as ctx:
                        self.admin_session.update_attachment_publication_route(
                            "Strike-OT-20260604-ADMIN",
                            attachment_id,
                            self.valid_request(),
                            payload,
                        )
                after = self.fetch_attachment_row(
                    self.admin_session.DB_PATH, attachment_id
                )
                conn = sqlite3.connect(self.admin_session.DB_PATH)
                try:
                    audit_count = conn.execute(
                        "SELECT COUNT(*) FROM attachment_audit_events"
                    ).fetchone()[0]
                finally:
                    conn.close()
            finally:
                self.admin_session.DB_PATH = original_db_path

        self.assertEqual(getattr(ctx.exception, "status_code", None), status_code)
        self.assertEqual(getattr(ctx.exception, "detail", None), detail)
        self.assertEqual(after, before)
        self.assertEqual(audit_count, 0)

    def assert_visibility_update_rejected(self, payload, status_code, detail):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            self.insert_admin_attachment(conn)
            attachment_id = conn.execute(
                "SELECT id FROM record_attachments"
            ).fetchone()["id"]
            before = dict(
                conn.execute(
                    "SELECT * FROM record_attachments WHERE id = ?",
                    (attachment_id,),
                ).fetchone()
            )
            conn.close()
            try:
                with self.env():
                    with self.assertRaises(Exception) as ctx:
                        self.admin_session.update_attachment_visibility_route(
                            "Strike-OT-20260604-ADMIN",
                            attachment_id,
                            self.valid_request(),
                            payload,
                        )
                after = self.fetch_attachment_row(
                    self.admin_session.DB_PATH, attachment_id
                )
                conn = sqlite3.connect(self.admin_session.DB_PATH)
                try:
                    audit_count = conn.execute(
                        "SELECT COUNT(*) FROM attachment_audit_events"
                    ).fetchone()[0]
                finally:
                    conn.close()
            finally:
                self.admin_session.DB_PATH = original_db_path

        self.assertEqual(getattr(ctx.exception, "status_code", None), status_code)
        self.assertEqual(getattr(ctx.exception, "detail", None), detail)
        self.assertEqual(after, before)
        self.assertEqual(audit_count, 0)

    def assert_relationship_add_rejected(self, payload, status_code, detail):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            self.insert_admin_attachment(conn)
            attachment_id = conn.execute(
                "SELECT id FROM record_attachments"
            ).fetchone()["id"]
            before = self.fetch_attachment_row(
                self.admin_session.DB_PATH, attachment_id
            )
            conn.close()
            try:
                with self.env():
                    with self.assertRaises(Exception) as ctx:
                        self.admin_session.add_attachment_relationship_route(
                            "Strike-OT-20260604-ADMIN",
                            attachment_id,
                            self.valid_request(),
                            payload,
                        )
                after = self.fetch_attachment_row(
                    self.admin_session.DB_PATH, attachment_id
                )
                conn = sqlite3.connect(self.admin_session.DB_PATH)
                try:
                    relationship_count = conn.execute(
                        "SELECT COUNT(*) FROM record_attachment_relationships"
                    ).fetchone()[0]
                finally:
                    conn.close()
            finally:
                self.admin_session.DB_PATH = original_db_path

        self.assertEqual(getattr(ctx.exception, "status_code", None), status_code)
        self.assertEqual(getattr(ctx.exception, "detail", None), detail)
        self.assertEqual(after, before)
        self.assertEqual(relationship_count, 0)


if __name__ == "__main__":
    unittest.main()
