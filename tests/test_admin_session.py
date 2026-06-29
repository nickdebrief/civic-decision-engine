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
    def __init__(self, cookies=None, query_params=None):
        self.cookies = cookies or {}
        self.query_params = query_params or {}


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


    def test_stage17j_governance_pattern_detection_renders_classification_states(self):
        def pattern(classification):
            return {
                "summary": {
                    "total_pattern_layers": 6,
                    "pattern_matching_layers": 6 if classification == "Recurring Governance Pattern" else 0,
                    "non_pattern_layers": 6 if classification == "No Governance Pattern" else 0,
                    "governance_classification": {
                        "Recurring Governance Pattern": "Governance Gap",
                        "Limited Governance Pattern": "Partially Governed",
                        "No Governance Pattern": "Governed",
                    }[classification],
                    "continuity_classification": {
                        "Recurring Governance Pattern": "Governance Discontinuity",
                        "Limited Governance Pattern": "Partial Continuity",
                        "No Governance Pattern": "Continuous Governance",
                    }[classification],
                    "governance_change_state": {
                        "Recurring Governance Pattern": "Significant Change",
                        "Limited Governance Pattern": "Limited Change",
                        "No Governance Pattern": "No Recorded Change",
                    }[classification],
                    "governance_trajectory": {
                        "Recurring Governance Pattern": "Governance Regression",
                        "Limited Governance Pattern": "Governance Persistence",
                        "No Governance Pattern": "Governance Progression",
                    }[classification],
                    "governance_pattern_classification": classification,
                },
                "reviews": {
                    "dependency": {
                        "classification": "Supported",
                        "evidence_supported": 5,
                        "unsupported": 0,
                        "pattern_state": "No Pattern",
                    },
                    "impact": {
                        "classification": "Evidence-Supported Impact",
                        "evidence_supported": 5,
                        "unsupported": 0,
                        "pattern_state": "No Pattern",
                    },
                    "stability": {
                        "classification": "Stable",
                        "stable": 5,
                        "limited_stability": 0,
                        "unstable": 0,
                        "pattern_state": "No Pattern",
                    },
                    "reproducibility": {
                        "classification": "Reproducible",
                        "reproducible": 5,
                        "limited_reproducibility": 0,
                        "non_reproducible": 0,
                        "pattern_state": "No Pattern",
                    },
                    "integrity": {
                        "classification": "High Integrity",
                        "high_integrity": 5,
                        "limited_integrity": 0,
                        "compromised_integrity": 0,
                        "pattern_state": "No Pattern",
                    },
                    "governance": {
                        "governance_classification": {
                            "Recurring Governance Pattern": "Governance Gap",
                            "Limited Governance Pattern": "Partially Governed",
                            "No Governance Pattern": "Governed",
                        }[classification],
                        "continuity_classification": {
                            "Recurring Governance Pattern": "Governance Discontinuity",
                            "Limited Governance Pattern": "Partial Continuity",
                            "No Governance Pattern": "Continuous Governance",
                        }[classification],
                        "change_state": {
                            "Recurring Governance Pattern": "Significant Change",
                            "Limited Governance Pattern": "Limited Change",
                            "No Governance Pattern": "No Recorded Change",
                        }[classification],
                        "governance_trajectory": {
                            "Recurring Governance Pattern": "Governance Regression",
                            "Limited Governance Pattern": "Governance Persistence",
                            "No Governance Pattern": "Governance Progression",
                        }[classification],
                        "pattern_state": {
                            "Recurring Governance Pattern": "Pattern-Matching",
                            "Limited Governance Pattern": "Limited Pattern",
                            "No Governance Pattern": "No Pattern",
                        }[classification],
                    },
                },
                "record": {
                    "reference": "Strike-LA-20260710-004",
                    "trajectory": "Stable",
                    "finding": "Trajectory recorded as Stable.",
                    "governance_classification": {
                        "Recurring Governance Pattern": "Governance Gap",
                        "Limited Governance Pattern": "Partially Governed",
                        "No Governance Pattern": "Governed",
                    }[classification],
                    "continuity_classification": {
                        "Recurring Governance Pattern": "Governance Discontinuity",
                        "Limited Governance Pattern": "Partial Continuity",
                        "No Governance Pattern": "Continuous Governance",
                    }[classification],
                    "governance_change_state": {
                        "Recurring Governance Pattern": "Significant Change",
                        "Limited Governance Pattern": "Limited Change",
                        "No Governance Pattern": "No Recorded Change",
                    }[classification],
                    "governance_trajectory": {
                        "Recurring Governance Pattern": "Governance Regression",
                        "Limited Governance Pattern": "Governance Persistence",
                        "No Governance Pattern": "Governance Progression",
                    }[classification],
                    "dependency_classification": "Supported",
                    "impact_classification": "Evidence-Supported Impact",
                    "stability_classification": "Stable",
                    "reproducibility_classification": "Reproducible",
                    "integrity_classification": "High Integrity",
                    "governance_pattern_classification": classification,
                },
            }

        classify = self.admin_session._stage17j_governance_pattern_classification

        self.assertEqual(
            "Recurring Governance Pattern",
            classify(
                "Unsupported",
                "Unsupported Impact",
                "Unstable",
                "Non-Reproducible",
                "Compromised Integrity",
                "Governance Gap",
                "Governance Discontinuity",
                "Significant Change",
                "Governance Regression",
            ),
        )
        self.assertEqual(
            "Limited Governance Pattern",
            classify(
                "Supported",
                "Evidence-Supported Impact",
                "Limited Stability",
                "Reproducible",
                "High Integrity",
                "Partially Governed",
                "Partial Continuity",
                "Limited Change",
                "Governance Persistence",
            ),
        )
        self.assertEqual(
            "No Governance Pattern",
            classify(
                "Supported",
                "Evidence-Supported Impact",
                "Stable",
                "Reproducible",
                "High Integrity",
                "Governed",
                "Continuous Governance",
                "No Recorded Change",
                "Governance Progression",
            ),
        )

        for classification in (
            "Recurring Governance Pattern",
            "Limited Governance Pattern",
            "No Governance Pattern",
        ):
            rendered = self.admin_session._render_stage17j_governance_pattern_detection_content(
                pattern(classification)
            )
            self.assertIn(
                f"<td>Governance Pattern Classification</td><td>{classification}</td>",
                rendered,
            )
            self.assertIn("<h3>Dependency Pattern Review</h3>", rendered)
            self.assertIn("<h3>Impact Pattern Review</h3>", rendered)
            self.assertIn("<h3>Stability Pattern Review</h3>", rendered)
            self.assertIn("<h3>Reproducibility Pattern Review</h3>", rendered)
            self.assertIn("<h3>Integrity Pattern Review</h3>", rendered)
            self.assertIn("<h3>Governance Pattern Review</h3>", rendered)


    def test_stage17k_governance_consistency_renders_classification_states(self):
        def consistency(classification):
            return {
                "summary": {
                    "total_governance_layers": 5,
                    "consistent_layers": 5 if classification == "Consistent Governance" else 0,
                    "inconsistent_layers": 5 if classification == "Governance Inconsistency" else 0,
                    "governance_classification": {
                        "Consistent Governance": "Governed",
                        "Partially Consistent": "Partially Governed",
                        "Governance Inconsistency": "Governance Gap",
                    }[classification],
                    "continuity_classification": {
                        "Consistent Governance": "Continuous Governance",
                        "Partially Consistent": "Partial Continuity",
                        "Governance Inconsistency": "Governance Discontinuity",
                    }[classification],
                    "change_classification": {
                        "Consistent Governance": "No Recorded Change",
                        "Partially Consistent": "Limited Change",
                        "Governance Inconsistency": "Significant Change",
                    }[classification],
                    "trajectory_classification": {
                        "Consistent Governance": "Governance Progression",
                        "Partially Consistent": "Governance Persistence",
                        "Governance Inconsistency": "Governance Regression",
                    }[classification],
                    "pattern_classification": {
                        "Consistent Governance": "Limited Governance Pattern",
                        "Partially Consistent": "Limited Governance Pattern",
                        "Governance Inconsistency": "Recurring Governance Pattern",
                    }[classification],
                    "consistency_classification": classification,
                },
                "reviews": {
                    "governance": {
                        "classification": "Governed",
                        "governance_state": "Governed",
                        "consistency_state": "Consistent",
                    },
                    "continuity": {
                        "classification": "Continuous Governance",
                        "continuity_state": "Continuous Governance",
                        "consistency_state": "Consistent",
                    },
                    "change": {
                        "classification": "No Recorded Change",
                        "change_state": "No Recorded Change",
                        "consistency_state": "Consistent",
                    },
                    "trajectory": {
                        "classification": "Governance Progression",
                        "trajectory_state": "Governance Progression",
                        "consistency_state": "Consistent",
                    },
                    "pattern": {
                        "classification": "Limited Governance Pattern",
                        "pattern_state": "Limited Governance Pattern",
                        "consistency_state": "Consistent",
                    },
                },
                "record": {
                    "reference": "Strike-LA-20260710-004",
                    "trajectory": "Stable",
                    "finding": "Trajectory recorded as Stable.",
                    "governance_classification": "Governed",
                    "continuity_classification": "Continuous Governance",
                    "governance_change_state": "No Recorded Change",
                    "governance_trajectory": "Governance Progression",
                    "governance_pattern_classification": "Limited Governance Pattern",
                    "consistency_classification": classification,
                },
            }

        classify = self.admin_session._stage17k_consistency_classification

        self.assertEqual(
            "Governance Inconsistency",
            classify(
                "Governance Gap",
                "Governance Discontinuity",
                "Significant Change",
                "Governance Regression",
                "Recurring Governance Pattern",
            ),
        )
        self.assertEqual(
            "Consistent Governance",
            classify(
                "Governed",
                "Continuous Governance",
                "No Recorded Change",
                "Governance Progression",
                "Limited Governance Pattern",
            ),
        )
        self.assertEqual(
            "Partially Consistent",
            classify(
                "Partially Governed",
                "Partial Continuity",
                "Limited Change",
                "Governance Persistence",
                "Limited Governance Pattern",
            ),
        )

        for classification in (
            "Consistent Governance",
            "Partially Consistent",
            "Governance Inconsistency",
        ):
            rendered = self.admin_session._render_stage17k_governance_consistency_content(
                consistency(classification)
            )
            self.assertIn(
                f"<td>Consistency Classification</td><td>{classification}</td>",
                rendered,
            )
            self.assertIn("<h3>Governance Review</h3>", rendered)
            self.assertIn("<h3>Continuity Review</h3>", rendered)
            self.assertIn("<h3>Change Review</h3>", rendered)
            self.assertIn("<h3>Trajectory Review</h3>", rendered)
            self.assertIn("<h3>Pattern Review</h3>", rendered)


    def test_stage17l_governance_relationships_renders_classification_states(self):
        def relationships(classification):
            return {
                "summary": {
                    "total_governance_layers": 6,
                    "related_governance_layers": 6,
                    "aligned_relationships": 6 if classification == "Aligned Governance Relationships" else 0,
                    "conflicting_relationships": 6 if classification == "Governance Relationship Conflict" else 0,
                    "governance_classification": {
                        "Aligned Governance Relationships": "Governed",
                        "Related Governance Relationships": "Partially Governed",
                        "Governance Relationship Conflict": "Governance Gap",
                    }[classification],
                    "continuity_classification": {
                        "Aligned Governance Relationships": "Continuous Governance",
                        "Related Governance Relationships": "Partial Continuity",
                        "Governance Relationship Conflict": "Governance Discontinuity",
                    }[classification],
                    "change_classification": {
                        "Aligned Governance Relationships": "No Recorded Change",
                        "Related Governance Relationships": "Limited Change",
                        "Governance Relationship Conflict": "Significant Change",
                    }[classification],
                    "trajectory_classification": {
                        "Aligned Governance Relationships": "Governance Progression",
                        "Related Governance Relationships": "Governance Persistence",
                        "Governance Relationship Conflict": "Governance Regression",
                    }[classification],
                    "pattern_classification": {
                        "Aligned Governance Relationships": "Limited Governance Pattern",
                        "Related Governance Relationships": "Limited Governance Pattern",
                        "Governance Relationship Conflict": "Recurring Governance Pattern",
                    }[classification],
                    "consistency_classification": {
                        "Aligned Governance Relationships": "Consistent Governance",
                        "Related Governance Relationships": "Partially Consistent",
                        "Governance Relationship Conflict": "Governance Inconsistency",
                    }[classification],
                    "relationship_classification": classification,
                },
                "reviews": {
                    "governance": {
                        "classification": "Governed",
                        "governance_state": "Governed",
                        "relationship_state": "Aligned",
                    },
                    "continuity": {
                        "classification": "Continuous Governance",
                        "continuity_state": "Continuous Governance",
                        "relationship_state": "Aligned",
                    },
                    "change": {
                        "classification": "No Recorded Change",
                        "change_state": "No Recorded Change",
                        "relationship_state": "Aligned",
                    },
                    "trajectory": {
                        "classification": "Governance Progression",
                        "trajectory_state": "Governance Progression",
                        "relationship_state": "Aligned",
                    },
                    "pattern": {
                        "classification": "Limited Governance Pattern",
                        "pattern_state": "Limited Governance Pattern",
                        "relationship_state": "Aligned",
                    },
                    "consistency": {
                        "classification": "Consistent Governance",
                        "consistency_state": "Consistent Governance",
                        "relationship_state": "Aligned",
                    },
                },
                "record": {
                    "reference": "Strike-LA-20260710-004",
                    "trajectory": "Stable",
                    "finding": "Trajectory recorded as Stable.",
                    "governance_classification": "Governed",
                    "continuity_classification": "Continuous Governance",
                    "governance_change_state": "No Recorded Change",
                    "governance_trajectory": "Governance Progression",
                    "governance_pattern_classification": "Limited Governance Pattern",
                    "consistency_classification": "Consistent Governance",
                    "relationship_classification": classification,
                },
            }

        classify = self.admin_session._stage17l_relationship_classification

        self.assertEqual(
            "Governance Relationship Conflict",
            classify(
                "Governance Gap",
                "Governance Discontinuity",
                "Significant Change",
                "Governance Regression",
                "Recurring Governance Pattern",
                "Governance Inconsistency",
            ),
        )
        self.assertEqual(
            "Aligned Governance Relationships",
            classify(
                "Governed",
                "Continuous Governance",
                "No Recorded Change",
                "Governance Progression",
                "Limited Governance Pattern",
                "Consistent Governance",
            ),
        )
        self.assertEqual(
            "Related Governance Relationships",
            classify(
                "Partially Governed",
                "Partial Continuity",
                "Limited Change",
                "Governance Persistence",
                "Limited Governance Pattern",
                "Partially Consistent",
            ),
        )

        for classification in (
            "Aligned Governance Relationships",
            "Related Governance Relationships",
            "Governance Relationship Conflict",
        ):
            rendered = self.admin_session._render_stage17l_governance_relationships_content(
                relationships(classification)
            )
            self.assertIn(
                f"<td>Relationship Classification</td><td>{classification}</td>",
                rendered,
            )
            self.assertIn("<h3>Governance Relationship Review</h3>", rendered)
            self.assertIn("<h3>Continuity Relationship Review</h3>", rendered)
            self.assertIn("<h3>Change Relationship Review</h3>", rendered)
            self.assertIn("<h3>Trajectory Relationship Review</h3>", rendered)
            self.assertIn("<h3>Pattern Relationship Review</h3>", rendered)
            self.assertIn("<h3>Consistency Relationship Review</h3>", rendered)

    def test_stage17m_governance_traceability_renders_classification_states(self):
        def traceability(classification):
            return {
                "summary": {
                    "total_traceability_layers": 7,
                    "traceable_layers": 7
                    if classification == "Fully Traceable Governance"
                    else 3,
                    "untraceable_layers": 0
                    if classification == "Fully Traceable Governance"
                    else 4,
                    "governance_classification": "Governed"
                    if classification != "Untraceable Governance"
                    else "",
                    "continuity_classification": "Continuous Governance",
                    "change_classification": "No Recorded Change",
                    "trajectory_classification": "Governance Progression",
                    "pattern_classification": "Limited Governance Pattern",
                    "consistency_classification": "Consistent Governance",
                    "relationship_classification": "Aligned Governance Relationships"
                    if classification != "Untraceable Governance"
                    else "",
                    "traceability_classification": classification,
                },
                "reviews": {
                    "governance": {
                        "classification": "Governed",
                        "upstream_source": "Governance Summary",
                        "traceability_state": "Traceable",
                    },
                    "continuity": {
                        "classification": "Continuous Governance",
                        "upstream_source": "Governance Summary",
                        "traceability_state": "Traceable",
                    },
                    "change": {
                        "classification": "No Recorded Change",
                        "upstream_source": "Governance Continuity",
                        "traceability_state": "Traceable",
                    },
                    "trajectory": {
                        "classification": "Governance Progression",
                        "upstream_source": "Governance Change Log",
                        "traceability_state": "Traceable",
                    },
                    "pattern": {
                        "classification": "Limited Governance Pattern",
                        "upstream_source": "Governance Trajectory",
                        "traceability_state": "Traceable",
                    },
                    "consistency": {
                        "classification": "Consistent Governance",
                        "upstream_source": "Governance Pattern Detection",
                        "traceability_state": "Traceable",
                    },
                    "relationships": {
                        "classification": "Aligned Governance Relationships",
                        "upstream_source": "Governance Consistency",
                        "traceability_state": "Traceable",
                    },
                },
                "record": {
                    "reference": "Strike-LA-20260710-004",
                    "trajectory": "Stable",
                    "finding": "Trajectory recorded as Stable.",
                    "governance_classification": "Governed",
                    "continuity_classification": "Continuous Governance",
                    "governance_change_state": "No Recorded Change",
                    "governance_trajectory": "Governance Progression",
                    "governance_pattern_classification": "Limited Governance Pattern",
                    "consistency_classification": "Consistent Governance",
                    "relationship_classification": "Aligned Governance Relationships",
                    "traceability_classification": classification,
                },
            }

        classify = self.admin_session._stage17m_traceability_classification

        self.assertEqual(
            "Untraceable Governance",
            classify(
                "",
                "Continuous Governance",
                "No Recorded Change",
                "Governance Progression",
                "Limited Governance Pattern",
                "Consistent Governance",
                "Aligned Governance Relationships",
            ),
        )
        self.assertEqual(
            "Fully Traceable Governance",
            classify(
                "Governed",
                "Continuous Governance",
                "No Recorded Change",
                "Governance Progression",
                "Limited Governance Pattern",
                "Consistent Governance",
                "Aligned Governance Relationships",
            ),
        )
        self.assertEqual(
            "Partially Traceable Governance",
            classify(
                "Governed",
                "",
                "No Recorded Change",
                "Governance Progression",
                "Limited Governance Pattern",
                "Consistent Governance",
                "Aligned Governance Relationships",
            ),
        )

        for classification in (
            "Fully Traceable Governance",
            "Partially Traceable Governance",
            "Untraceable Governance",
        ):
            rendered = self.admin_session._render_stage17m_governance_traceability_content(
                traceability(classification)
            )
            self.assertIn(
                f"<td>Traceability Classification</td><td>{classification}</td>",
                rendered,
            )
            self.assertIn("<h3>Governance Traceability Review</h3>", rendered)
            self.assertIn("<h3>Continuity Traceability Review</h3>", rendered)
            self.assertIn("<h3>Change Traceability Review</h3>", rendered)
            self.assertIn("<h3>Trajectory Traceability Review</h3>", rendered)
            self.assertIn("<h3>Pattern Traceability Review</h3>", rendered)
            self.assertIn("<h3>Consistency Traceability Review</h3>", rendered)
            self.assertIn("<h3>Relationships Traceability Review</h3>", rendered)

    def test_stage17n_governance_coverage_renders_classification_states(self):
        def coverage(classification):
            unsupported = classification == "Full Governance Coverage"
            return {
                "summary": {
                    "total_governance_layers": 8,
                    "present_governance_layers": 8
                    if classification != "No Governance Coverage"
                    else 0,
                    "missing_governance_layers": 1
                    if classification == "Partial Governance Coverage"
                    else 0,
                    "populated_governance_layers": 8
                    if classification != "No Governance Coverage"
                    else 0,
                    "unsupported_governance_layers": 7 if unsupported else 0,
                    "governance_classification": "Governance Gap"
                    if unsupported
                    else "Governed",
                    "continuity_classification": "Governance Discontinuity"
                    if unsupported
                    else "Continuous Governance",
                    "change_classification": "Significant Change"
                    if unsupported
                    else "No Recorded Change",
                    "trajectory_classification": "Governance Regression"
                    if unsupported
                    else "Governance Progression",
                    "pattern_classification": "Recurring Governance Pattern"
                    if unsupported
                    else "Limited Governance Pattern",
                    "consistency_classification": "Governance Inconsistency"
                    if unsupported
                    else "Consistent Governance",
                    "relationship_classification": "Governance Relationship Conflict"
                    if unsupported
                    else "Aligned Governance Relationships",
                    "traceability_classification": "Fully Traceable Governance",
                    "coverage_classification": classification,
                },
                "reviews": {
                    "governance": {
                        "classification": "Governance Gap"
                        if unsupported
                        else "Governed",
                        "coverage_source": "Governance Summary",
                        "coverage_state": "Unsupported" if unsupported else "Present",
                    },
                    "continuity": {
                        "classification": "Continuous Governance",
                        "coverage_source": "Governance Continuity",
                        "coverage_state": "Present",
                    },
                    "change": {
                        "classification": "No Recorded Change",
                        "coverage_source": "Governance Change Log",
                        "coverage_state": "Present",
                    },
                    "trajectory": {
                        "classification": "Governance Progression",
                        "coverage_source": "Governance Trajectory",
                        "coverage_state": "Present",
                    },
                    "pattern": {
                        "classification": "Limited Governance Pattern",
                        "coverage_source": "Governance Pattern Detection",
                        "coverage_state": "Present",
                    },
                    "consistency": {
                        "classification": "Consistent Governance",
                        "coverage_source": "Governance Consistency",
                        "coverage_state": "Present",
                    },
                    "relationships": {
                        "classification": "Aligned Governance Relationships",
                        "coverage_source": "Governance Relationships",
                        "coverage_state": "Present",
                    },
                    "traceability": {
                        "classification": "Fully Traceable Governance",
                        "coverage_source": "Governance Traceability",
                        "coverage_state": "Present",
                    },
                },
                "record": {
                    "reference": "Strike-LA-20260710-004",
                    "trajectory": "Stable",
                    "finding": "Trajectory recorded as Stable.",
                    "governance_classification": "Governance Gap"
                    if unsupported
                    else "Governed",
                    "continuity_classification": "Governance Discontinuity"
                    if unsupported
                    else "Continuous Governance",
                    "governance_change_state": "Significant Change"
                    if unsupported
                    else "No Recorded Change",
                    "governance_trajectory": "Governance Regression"
                    if unsupported
                    else "Governance Progression",
                    "governance_pattern_classification": "Recurring Governance Pattern"
                    if unsupported
                    else "Limited Governance Pattern",
                    "consistency_classification": "Governance Inconsistency"
                    if unsupported
                    else "Consistent Governance",
                    "relationship_classification": "Governance Relationship Conflict"
                    if unsupported
                    else "Aligned Governance Relationships",
                    "traceability_classification": "Fully Traceable Governance",
                    "coverage_classification": classification,
                },
            }

        classify = self.admin_session._stage17n_coverage_classification

        self.assertEqual(
            "No Governance Coverage",
            classify("", "", "", "", "", "", "", ""),
        )
        self.assertEqual(
            "Partial Governance Coverage",
            classify(
                "Governed",
                "",
                "No Recorded Change",
                "Governance Progression",
                "Limited Governance Pattern",
                "Consistent Governance",
                "Aligned Governance Relationships",
                "Fully Traceable Governance",
            ),
        )
        self.assertEqual(
            "Full Governance Coverage",
            classify(
                "Governance Gap",
                "Governance Discontinuity",
                "Significant Change",
                "Governance Regression",
                "Recurring Governance Pattern",
                "Governance Inconsistency",
                "Governance Relationship Conflict",
                "Fully Traceable Governance",
            ),
        )
        self.assertEqual(
            "Unsupported",
            self.admin_session._stage17n_coverage_state("Governance Gap"),
        )

        for classification in (
            "Full Governance Coverage",
            "Partial Governance Coverage",
            "Limited Governance Coverage",
            "No Governance Coverage",
        ):
            rendered = self.admin_session._render_stage17n_governance_coverage_content(
                coverage(classification)
            )
            self.assertIn(
                f"<td>Coverage Classification</td><td>{classification}</td>",
                rendered,
            )
            self.assertIn("<h3>Governance Coverage Review</h3>", rendered)
            self.assertIn("<h3>Continuity Coverage Review</h3>", rendered)
            self.assertIn("<h3>Change Coverage Review</h3>", rendered)
            self.assertIn("<h3>Trajectory Coverage Review</h3>", rendered)
            self.assertIn("<h3>Pattern Coverage Review</h3>", rendered)
            self.assertIn("<h3>Consistency Coverage Review</h3>", rendered)
            self.assertIn("<h3>Relationships Coverage Review</h3>", rendered)
            self.assertIn("<h3>Traceability Coverage Review</h3>", rendered)

    def test_stage17o_governance_chain_review_renders_classification_states(self):
        def chain_review(classification):
            breakdown = classification == "Governance Chain Breakdown"
            return {
                "summary": {
                    "total_governance_chain_layers": 9,
                    "present_chain_layers": 9
                    if classification != "Partial Governance Chain"
                    else 8,
                    "missing_chain_layers": 1
                    if classification == "Partial Governance Chain"
                    else 0,
                    "traceable_chain_layers": 9,
                    "covered_chain_layers": 9,
                    "unsupported_chain_layers": 3 if breakdown else 0,
                    "governance_classification": "Governance Gap"
                    if breakdown
                    else "Governed",
                    "continuity_classification": "Continuous Governance",
                    "change_classification": "No Recorded Change",
                    "trajectory_classification": "Governance Progression",
                    "pattern_classification": "Limited Governance Pattern",
                    "consistency_classification": "Governance Inconsistency"
                    if breakdown
                    else "Consistent Governance",
                    "relationship_classification": "Governance Relationship Conflict"
                    if breakdown
                    else "Aligned Governance Relationships",
                    "traceability_classification": "Fully Traceable Governance",
                    "coverage_classification": "Full Governance Coverage",
                    "chain_review_classification": classification,
                },
                "reviews": {
                    "governance": {
                        "classification": "Governance Gap"
                        if breakdown
                        else "Governed",
                        "chain_source": "Governance Summary",
                        "chain_state": "Breakdown" if breakdown else "Present",
                    },
                    "continuity": {
                        "classification": "Continuous Governance",
                        "chain_source": "Governance Continuity",
                        "chain_state": "Present",
                    },
                    "change": {
                        "classification": "No Recorded Change",
                        "chain_source": "Governance Change Log",
                        "chain_state": "Present",
                    },
                    "trajectory": {
                        "classification": "Governance Progression",
                        "chain_source": "Governance Trajectory",
                        "chain_state": "Present",
                    },
                    "pattern": {
                        "classification": "Limited Governance Pattern",
                        "chain_source": "Governance Pattern Detection",
                        "chain_state": "Present",
                    },
                    "consistency": {
                        "classification": "Governance Inconsistency"
                        if breakdown
                        else "Consistent Governance",
                        "chain_source": "Governance Consistency",
                        "chain_state": "Breakdown" if breakdown else "Present",
                    },
                    "relationships": {
                        "classification": "Governance Relationship Conflict"
                        if breakdown
                        else "Aligned Governance Relationships",
                        "chain_source": "Governance Relationships",
                        "chain_state": "Breakdown" if breakdown else "Present",
                    },
                    "traceability": {
                        "classification": "Fully Traceable Governance",
                        "chain_source": "Governance Traceability",
                        "chain_state": "Present",
                    },
                    "coverage": {
                        "classification": "Full Governance Coverage",
                        "chain_source": "Governance Coverage",
                        "chain_state": "Present",
                    },
                },
                "record": {
                    "reference": "Strike-LA-20260710-004",
                    "trajectory": "Stable",
                    "finding": "Trajectory recorded as Stable.",
                    "governance_classification": "Governance Gap"
                    if breakdown
                    else "Governed",
                    "continuity_classification": "Continuous Governance",
                    "governance_change_state": "No Recorded Change",
                    "governance_trajectory": "Governance Progression",
                    "governance_pattern_classification": "Limited Governance Pattern",
                    "consistency_classification": "Governance Inconsistency"
                    if breakdown
                    else "Consistent Governance",
                    "relationship_classification": "Governance Relationship Conflict"
                    if breakdown
                    else "Aligned Governance Relationships",
                    "traceability_classification": "Fully Traceable Governance",
                    "coverage_classification": "Full Governance Coverage",
                    "chain_review_classification": classification,
                },
            }

        classify = self.admin_session._stage17o_chain_review_classification

        self.assertEqual(
            "Governance Chain Breakdown",
            classify(
                "Governance Gap",
                "Continuous Governance",
                "No Recorded Change",
                "Governance Progression",
                "Limited Governance Pattern",
                "Consistent Governance",
                "Aligned Governance Relationships",
                "Fully Traceable Governance",
                "Full Governance Coverage",
            ),
        )
        self.assertEqual(
            "Partial Governance Chain",
            classify(
                "Governed",
                "",
                "No Recorded Change",
                "Governance Progression",
                "Limited Governance Pattern",
                "Consistent Governance",
                "Aligned Governance Relationships",
                "Fully Traceable Governance",
                "Full Governance Coverage",
            ),
        )
        self.assertEqual(
            "Complete Governance Chain",
            classify(
                "Governed",
                "Continuous Governance",
                "No Recorded Change",
                "Governance Progression",
                "Limited Governance Pattern",
                "Consistent Governance",
                "Aligned Governance Relationships",
                "Fully Traceable Governance",
                "Full Governance Coverage",
            ),
        )
        self.assertEqual(
            "Breakdown",
            self.admin_session._stage17o_chain_state("Governance Gap"),
        )

        for classification in (
            "Complete Governance Chain",
            "Partial Governance Chain",
            "Governance Chain Breakdown",
        ):
            rendered = self.admin_session._render_stage17o_governance_chain_review_content(
                chain_review(classification)
            )
            self.assertIn(
                f"<td>Chain Review Classification</td><td>{classification}</td>",
                rendered,
            )
            self.assertIn("<h3>Governance Chain Layer Review</h3>", rendered)
            self.assertIn("<h3>Continuity Chain Layer Review</h3>", rendered)
            self.assertIn("<h3>Change Chain Layer Review</h3>", rendered)
            self.assertIn("<h3>Trajectory Chain Layer Review</h3>", rendered)
            self.assertIn("<h3>Pattern Chain Layer Review</h3>", rendered)
            self.assertIn("<h3>Consistency Chain Layer Review</h3>", rendered)
            self.assertIn("<h3>Relationships Chain Layer Review</h3>", rendered)
            self.assertIn("<h3>Traceability Chain Layer Review</h3>", rendered)
            self.assertIn("<h3>Coverage Chain Layer Review</h3>", rendered)

    def test_stage18a_record_evolution_summary_renders_classification_states(self):
        initial = {
            "reference": "Strike-LA-20260710-004",
            "version": 1,
            "supersedes": None,
            "generated_at": "2026-06-04T12:00:00Z",
            "exported_at": "2026-06-04T12:05:00Z",
            "is_latest": 1,
            "trajectory": "Stable",
            "system_state": "PERSISTENT_RESISTANCE_WITHOUT_ADAPTATION",
            "finding": "Trajectory recorded as Stable.",
            "verification_hash": "hash-v1",
        }
        evolved = {
            **initial,
            "version": 2,
            "supersedes": "Strike-LA-20260710-004:v1",
            "verification_hash": "hash-v2",
        }
        superseded = {
            **initial,
            "is_latest": 0,
        }
        history = [
            {
                "reference": "Strike-LA-20260710-004",
                "version": 1,
                "is_latest": 0,
                "supersedes": None,
                "generated_at": "2026-06-04T12:00:00Z",
                "verification_hash": "hash-v1",
            },
            {
                "reference": "Strike-LA-20260710-004",
                "version": 2,
                "is_latest": 1,
                "supersedes": "Strike-LA-20260710-004:v1",
                "generated_at": "2026-06-05T12:00:00Z",
                "verification_hash": "hash-v2",
            },
        ]
        initial_history = [
            {
                "reference": "Strike-LA-20260710-004",
                "version": 1,
                "is_latest": 1,
                "supersedes": None,
                "generated_at": "2026-06-04T12:00:00Z",
                "verification_hash": "hash-v1",
            }
        ]

        classify = self.admin_session._stage18a_evolution_classification

        self.assertEqual("Initial Record State", classify(initial, initial_history))
        self.assertEqual("Evolved Record State", classify(evolved, history))
        self.assertEqual("Superseded Record State", classify(superseded, history))
        self.assertEqual("Unresolved Evolution State", classify({}, []))

        self.assertEqual(
            "Strike-LA-20260710-004:v2",
            self.admin_session._stage18a_superseded_by(superseded, history),
        )

        for metadata, lineage, expected in (
            (initial, initial_history, "Initial Record State"),
            (evolved, history, "Evolved Record State"),
            (superseded, history, "Superseded Record State"),
            ({}, [], "Unresolved Evolution State"),
        ):
            rendered = self.admin_session._render_stage18a_evolution_summary_content(
                self.admin_session._record_stage18a_evolution_summary(
                    metadata,
                    lineage,
                )
            )
            self.assertIn(
                f"<td>Evolution Classification</td><td>{expected}</td>",
                rendered,
            )
            self.assertIn("<h3>Evolution Summary</h3>", rendered)
            self.assertIn("<h3>Version Lineage Review</h3>", rendered)
            self.assertIn("<h3>Record Evolution Details</h3>", rendered)
            self.assertIn("Verification Hash", rendered)

    def test_stage18b_record_evolution_continuity_renders_classification_states(self):
        base = {
            "reference": "Strike-LA-20260710-004",
            "version": 2,
            "supersedes": "Strike-LA-20260710-004:v1",
            "generated_at": "2026-06-05T12:00:00Z",
            "exported_at": "2026-06-05T12:05:00Z",
            "is_latest": 1,
            "trajectory": "Stable",
            "system_state": "PERSISTENT_RESISTANCE_WITHOUT_ADAPTATION",
            "finding": "Trajectory recorded as Stable.",
            "verification_hash": "hash-v2",
        }
        continuous_history = [
            {
                "reference": "Strike-LA-20260710-004",
                "version": 1,
                "is_latest": 0,
                "supersedes": None,
                "generated_at": "2026-06-04T12:00:00Z",
                "verification_hash": "hash-v1",
            },
            {
                "reference": "Strike-LA-20260710-004",
                "version": 2,
                "is_latest": 1,
                "supersedes": "Strike-LA-20260710-004:v1",
                "generated_at": "2026-06-05T12:00:00Z",
                "verification_hash": "hash-v2",
            },
        ]
        partial = {**base, "version": 1, "supersedes": None}
        partial_history = [
            {
                "reference": "Strike-LA-20260710-004",
                "version": 1,
                "is_latest": 1,
                "supersedes": None,
                "generated_at": "2026-06-04T12:00:00Z",
                "verification_hash": "hash-v1",
            }
        ]
        gap_history = [
            {
                "reference": "Strike-LA-20260710-004",
                "version": 1,
                "is_latest": 0,
                "supersedes": None,
                "generated_at": "2026-06-04T12:00:00Z",
                "verification_hash": "hash-v1",
            },
            {
                "reference": "Strike-LA-20260710-004",
                "version": 3,
                "is_latest": 1,
                "supersedes": "Strike-LA-20260710-004:v2",
                "generated_at": "2026-06-06T12:00:00Z",
                "verification_hash": "hash-v3",
            },
        ]

        classify = self.admin_session._stage18b_continuity_classification

        self.assertEqual("Continuous Evolution", classify(base, continuous_history))
        self.assertEqual(
            "Partial Evolution Continuity",
            classify(partial, partial_history),
        )
        self.assertEqual("Evolution Discontinuity", classify(base, gap_history))
        self.assertEqual("Unresolved Evolution Continuity", classify({}, []))
        self.assertEqual(1, self.admin_session._stage18b_version_gap_count(gap_history))
        self.assertEqual(
            (1, 1),
            self.admin_session._stage18b_supersession_counts(gap_history),
        )

        for metadata, lineage, expected in (
            (base, continuous_history, "Continuous Evolution"),
            (partial, partial_history, "Partial Evolution Continuity"),
            (base, gap_history, "Evolution Discontinuity"),
            ({}, [], "Unresolved Evolution Continuity"),
        ):
            rendered = self.admin_session._render_stage18b_evolution_continuity_content(
                self.admin_session._record_stage18b_evolution_continuity(
                    metadata,
                    lineage,
                )
            )
            self.assertIn(
                f"<td>Continuity Classification</td><td>{expected}</td>",
                rendered,
            )
            self.assertIn("<h3>Continuity Summary</h3>", rendered)
            self.assertIn("<h3>Version Continuity Review</h3>", rendered)
            self.assertIn("<h3>Supersession Continuity Review</h3>", rendered)
            self.assertIn("<h3>Reference Continuity Review</h3>", rendered)
            self.assertIn("<h3>Lineage Continuity Review</h3>", rendered)
            self.assertIn("<h3>Record Evolution Continuity</h3>", rendered)
            self.assertIn("Version Gap Count", rendered)
            self.assertIn("Supersession Link Count", rendered)
            self.assertIn("Broken Supersession Links", rendered)

    def test_stage18c_record_evolution_change_log_renders_classification_states(self):
        def version_row(version, *, latest=0, finding="Finding v1", hash_value=None):
            return {
                "reference": "Strike-LA-20260710-004",
                "version": version,
                "is_latest": latest,
                "supersedes": None
                if version == 1
                else f"Strike-LA-20260710-004:v{version - 1}",
                "generated_at": f"2026-06-0{version}T12:00:00Z",
                "verification_hash": hash_value or f"hash-v{version}",
                "trajectory": "Stable",
                "system_state": "PERSISTENT_RESISTANCE_WITHOUT_ADAPTATION",
                "finding": finding,
                "conditions_json": "[\"Escalation Without Response\"]",
                "signals_json": "[\"No Recurring Transition\"]",
                "generated_by": "civic-decision-engine",
            }

        base = {
            "reference": "Strike-LA-20260710-004",
            "version": 2,
            "supersedes": "Strike-LA-20260710-004:v1",
            "generated_at": "2026-06-02T12:00:00Z",
            "exported_at": "2026-06-02T12:05:00Z",
            "is_latest": 1,
            "trajectory": "Stable",
            "system_state": "PERSISTENT_RESISTANCE_WITHOUT_ADAPTATION",
            "finding": "Finding v2",
            "verification_hash": "hash-v2",
        }
        single_history = [version_row(1, latest=1)]
        recorded_history = [
            version_row(1, hash_value="shared-hash"),
            version_row(2, latest=1, finding="Finding v2", hash_value="shared-hash"),
        ]
        extensive_history = [
            version_row(1),
            version_row(2, finding="Finding v2"),
            version_row(3, latest=1, finding="Finding v3"),
        ]

        classify = self.admin_session._stage18c_change_log_classification

        self.assertEqual(
            "No Recorded Changes",
            classify({**base, "version": 1, "supersedes": None}, single_history),
        )
        self.assertEqual(
            "Recorded Changes Present",
            classify(base, recorded_history),
        )
        self.assertEqual(
            "Extensive Change History",
            classify({**base, "version": 3}, extensive_history),
        )
        self.assertEqual("Unresolved Change Log", classify({}, []))

        for metadata, lineage, expected in (
            ({**base, "version": 1, "supersedes": None}, single_history, "No Recorded Changes"),
            (base, recorded_history, "Recorded Changes Present"),
            ({**base, "version": 3}, extensive_history, "Extensive Change History"),
            ({}, [], "Unresolved Change Log"),
        ):
            rendered = self.admin_session._render_stage18c_evolution_change_log_content(
                self.admin_session._record_stage18c_evolution_change_log(
                    metadata,
                    lineage,
                )
            )
            self.assertIn(
                f"<td>Change Log Classification</td><td>{expected}</td>",
                rendered,
            )
            self.assertIn("<h3>Change Log Summary</h3>", rendered)
            self.assertIn("<h3>Version Change Review</h3>", rendered)
            self.assertIn("<h3>Version Transition Review</h3>", rendered)
            self.assertIn("<h3>Field Change Review</h3>", rendered)
            self.assertIn("<h3>Record Evolution Change Log</h3>", rendered)
            self.assertIn("Version Transitions", rendered)
            self.assertIn("Changed Versions", rendered)
            self.assertIn("Unchanged Versions", rendered)
            self.assertIn("Field Changes", rendered)
            self.assertIn("Stable Fields", rendered)

        single_rendered = self.admin_session._render_stage18c_evolution_change_log_content(
            self.admin_session._record_stage18c_evolution_change_log(
                {**base, "version": 1, "supersedes": None},
                single_history,
            )
        )
        self.assertIn("<th>Transition State</th>", single_rendered)
        self.assertIn("<td>No Transition</td>", single_rendered)
        self.assertIn("<td>Not Applicable</td>", single_rendered)

    def test_stage18d_record_evolution_trajectory_renders_classification_states(self):
        def version_row(
            version,
            *,
            latest=0,
            finding="Finding v1",
            hash_value="shared-hash",
            generated_at=None,
            supersedes=None,
        ):
            return {
                "reference": "Strike-LA-20260710-004",
                "version": version,
                "is_latest": latest,
                "supersedes": supersedes
                if supersedes is not None
                else (
                    None
                    if version == 1
                    else f"Strike-LA-20260710-004:v{version - 1}"
                ),
                "generated_at": generated_at or f"2026-06-0{version}T12:00:00Z",
                "verification_hash": hash_value,
                "trajectory": "Stable",
                "system_state": "PERSISTENT_RESISTANCE_WITHOUT_ADAPTATION",
                "finding": finding,
                "conditions_json": "[\"Escalation Without Response\"]",
                "signals_json": "[\"No Recurring Transition\"]",
                "generated_by": "civic-decision-engine",
            }

        base = {
            "reference": "Strike-LA-20260710-004",
            "version": 2,
            "supersedes": "Strike-LA-20260710-004:v1",
            "generated_at": "2026-06-02T12:00:00Z",
            "exported_at": "2026-06-02T12:05:00Z",
            "is_latest": 1,
            "trajectory": "Stable",
            "system_state": "PERSISTENT_RESISTANCE_WITHOUT_ADAPTATION",
            "finding": "Finding v1",
            "verification_hash": "shared-hash",
        }
        initial_metadata = {**base, "version": 1, "supersedes": None}
        initial_history = [version_row(1, latest=1)]
        stable_history = [
            version_row(1),
            version_row(2, latest=1),
        ]
        active_history = [
            version_row(1, hash_value="stable-hash"),
            version_row(
                2,
                latest=1,
                finding="Finding v2",
                hash_value="stable-hash",
            ),
        ]
        fragmented_history = [
            version_row(1),
            version_row(
                3,
                latest=1,
                supersedes="Strike-LA-20260710-004:v2",
            ),
        ]

        classify = self.admin_session._stage18d_trajectory_classification

        self.assertEqual(
            "Initial Evolution Trajectory",
            classify(initial_metadata, initial_history),
        )
        self.assertEqual("Stable Evolution Trajectory", classify(base, stable_history))
        self.assertEqual("Active Evolution Trajectory", classify(base, active_history))
        self.assertEqual(
            "Fragmented Evolution Trajectory",
            classify({**base, "version": 3}, fragmented_history),
        )
        self.assertEqual("Unresolved Evolution Trajectory", classify({}, []))
        self.assertEqual(
            "Single Timestamp",
            self.admin_session._stage18d_timestamp_order_state(initial_history),
        )
        self.assertEqual(
            "Ordered",
            self.admin_session._stage18d_timestamp_order_state(stable_history),
        )
        self.assertEqual(
            "Out Of Order",
            self.admin_session._stage18d_timestamp_order_state(
                [
                    version_row(1, generated_at="2026-06-02T12:00:00Z"),
                    version_row(2, generated_at="2026-06-01T12:00:00Z"),
                ]
            ),
        )
        self.assertEqual(
            ("Complete", 2, 0),
            self.admin_session._stage18d_verification_hash_coverage(
                stable_history
            ),
        )

        for metadata, lineage, expected in (
            (initial_metadata, initial_history, "Initial Evolution Trajectory"),
            (base, stable_history, "Stable Evolution Trajectory"),
            (base, active_history, "Active Evolution Trajectory"),
            (
                {**base, "version": 3},
                fragmented_history,
                "Fragmented Evolution Trajectory",
            ),
            ({}, [], "Unresolved Evolution Trajectory"),
        ):
            rendered = self.admin_session._render_stage18d_evolution_trajectory_content(
                self.admin_session._record_stage18d_evolution_trajectory(
                    metadata,
                    lineage,
                )
            )
            self.assertIn(
                f"<td>Trajectory Classification</td><td>{expected}</td>",
                rendered,
            )
            self.assertIn("<h3>Trajectory Summary</h3>", rendered)
            self.assertIn("<h3>Version Trajectory Review</h3>", rendered)
            self.assertIn("<h3>Supersession Trajectory Review</h3>", rendered)
            self.assertIn("<h3>Lineage Trajectory Review</h3>", rendered)
            self.assertIn("<h3>Timestamp Trajectory Review</h3>", rendered)
            self.assertIn("<h3>Verification Hash Trajectory Review</h3>", rendered)
            self.assertIn("<h3>Record Evolution Trajectory</h3>", rendered)
            self.assertIn("Timestamp Order State", rendered)
            self.assertIn("Verification Hash Coverage", rendered)

    def test_stage18e_record_evolution_relationships_renders_classification_states(self):
        def version_row(
            version,
            *,
            latest=0,
            finding="Finding v1",
            hash_value="shared-hash",
            generated_at=None,
            supersedes=None,
        ):
            return {
                "reference": "Strike-LA-20260710-004",
                "version": version,
                "is_latest": latest,
                "supersedes": supersedes
                if supersedes is not None
                else (
                    None
                    if version == 1
                    else f"Strike-LA-20260710-004:v{version - 1}"
                ),
                "generated_at": generated_at or f"2026-06-0{version}T12:00:00Z",
                "verification_hash": hash_value,
                "trajectory": "Stable",
                "system_state": "PERSISTENT_RESISTANCE_WITHOUT_ADAPTATION",
                "finding": finding,
                "conditions_json": "[\"Escalation Without Response\"]",
                "signals_json": "[\"No Recurring Transition\"]",
                "generated_by": "civic-decision-engine",
            }

        base = {
            "reference": "Strike-LA-20260710-004",
            "version": 2,
            "supersedes": "Strike-LA-20260710-004:v1",
            "generated_at": "2026-06-02T12:00:00Z",
            "exported_at": "2026-06-02T12:05:00Z",
            "is_latest": 1,
            "trajectory": "Stable",
            "system_state": "PERSISTENT_RESISTANCE_WITHOUT_ADAPTATION",
            "finding": "Finding v1",
            "verification_hash": "shared-hash",
        }
        single_history = [version_row(1, latest=1)]
        full_history = [version_row(1), version_row(2, latest=1)]
        connected_history = [
            version_row(1, hash_value="shared-hash"),
            version_row(2, latest=1, hash_value=""),
        ]
        limited_history = [
            version_row(1),
            version_row(
                3,
                latest=1,
                supersedes="Strike-LA-20260710-004:v2",
            ),
        ]
        multi_history = [
            version_row(1),
            version_row(2),
            version_row(3, latest=1),
        ]

        def relationships(metadata, lineage):
            return self.admin_session._record_stage18e_evolution_relationships(
                metadata,
                lineage,
            )

        single = relationships({**base, "version": 1, "supersedes": None}, single_history)
        full = relationships(base, full_history)
        connected = relationships(base, connected_history)
        limited = relationships({**base, "version": 3}, limited_history)
        multi = relationships({**base, "version": 3}, multi_history)

        self.assertEqual(
            "No Evolution Relationships",
            single["summary"]["relationship_classification"],
        )
        self.assertEqual(
            "Fully Related Evolution Chain",
            full["summary"]["relationship_classification"],
        )
        self.assertEqual(
            "Connected Evolution Relationships",
            connected["summary"]["relationship_classification"],
        )
        self.assertEqual(
            "Limited Evolution Relationships",
            limited["summary"]["relationship_classification"],
        )
        self.assertEqual(
            "Single Version",
            single["reviews"]["version"]["version_relationship_state"],
        )
        self.assertEqual(
            "Sequential Versions",
            full["reviews"]["version"]["version_relationship_state"],
        )
        self.assertEqual(
            "Multi-Version Chain",
            multi["reviews"]["version"]["version_relationship_state"],
        )
        self.assertEqual(
            "No Relationship",
            single["reviews"]["supersession"]["relationship_state"],
        )
        self.assertEqual(
            "Connected Relationship",
            full["reviews"]["supersession"]["relationship_state"],
        )
        self.assertEqual(
            "Complete Relationship",
            full["reviews"]["verification"]["verification_relationship_state"],
        )
        self.assertEqual(
            "Partial Relationship",
            connected["reviews"]["verification"]["verification_relationship_state"],
        )
        self.assertEqual(
            "Incomplete Relationship",
            relationships(
                base,
                [version_row(1, hash_value=""), version_row(2, latest=1, hash_value="")],
            )["reviews"]["verification"]["verification_relationship_state"],
        )

        for relationship_set, expected in (
            (single, "No Evolution Relationships"),
            (full, "Fully Related Evolution Chain"),
            (connected, "Connected Evolution Relationships"),
            (limited, "Limited Evolution Relationships"),
        ):
            rendered = self.admin_session._render_stage18e_evolution_relationships_content(
                relationship_set
            )
            self.assertIn(
                f"<td>Relationship Classification</td><td>{expected}</td>",
                rendered,
            )
            self.assertIn("<h3>Relationship Summary</h3>", rendered)
            self.assertIn("<h3>Version Relationship Review</h3>", rendered)
            self.assertIn("<h3>Supersession Relationship Review</h3>", rendered)
            self.assertIn("<h3>Timestamp Relationship Review</h3>", rendered)
            self.assertIn("<h3>Verification Relationship Review</h3>", rendered)
            self.assertIn("<h3>Evolution Relationship Review</h3>", rendered)
            self.assertIn("<h3>Record Evolution Relationships</h3>", rendered)

    def test_stage18f_record_evolution_traceability_renders_classification_states(self):
        def version_row(
            version,
            *,
            latest=0,
            hash_value="shared-hash",
            generated_at="default",
            supersedes=None,
        ):
            return {
                "reference": "Strike-LA-20260710-004",
                "version": version,
                "is_latest": latest,
                "supersedes": supersedes
                if supersedes is not None
                else (
                    None
                    if version == 1
                    else f"Strike-LA-20260710-004:v{version - 1}"
                ),
                "generated_at": None
                if generated_at is None
                else (
                    f"2026-06-0{version}T12:00:00Z"
                    if generated_at == "default"
                    else generated_at
                ),
                "verification_hash": hash_value,
                "trajectory": "Stable",
                "system_state": "PERSISTENT_RESISTANCE_WITHOUT_ADAPTATION",
                "finding": "Finding v1",
                "conditions_json": "[\"Escalation Without Response\"]",
                "signals_json": "[\"No Recurring Transition\"]",
                "generated_by": "civic-decision-engine",
            }

        base = {
            "reference": "Strike-LA-20260710-004",
            "version": 2,
            "supersedes": "Strike-LA-20260710-004:v1",
            "generated_at": "2026-06-02T12:00:00Z",
            "exported_at": "2026-06-02T12:05:00Z",
            "is_latest": 1,
            "trajectory": "Stable",
            "system_state": "PERSISTENT_RESISTANCE_WITHOUT_ADAPTATION",
            "finding": "Finding v1",
            "verification_hash": "shared-hash",
        }
        single_metadata = {**base, "version": 1, "supersedes": None}
        single_history = [version_row(1, latest=1)]
        full_history = [version_row(1), version_row(2, latest=1)]
        broken_history = [
            version_row(1),
            version_row(
                3,
                latest=1,
                supersedes="Strike-LA-20260710-004:v2",
            ),
        ]
        no_timestamp_history = [
            version_row(1, generated_at=None, hash_value=""),
            version_row(2, latest=1, generated_at=None, hash_value=""),
        ]

        def traceability(metadata, lineage):
            return self.admin_session._record_stage18f_evolution_traceability(
                metadata,
                lineage,
            )

        single = traceability(single_metadata, single_history)
        full = traceability(base, full_history)
        broken = traceability({**base, "version": 3}, broken_history)
        untraceable = traceability(base, no_timestamp_history)

        self.assertEqual(
            "Partial Evolution Traceability",
            single["summary"]["traceability_classification"],
        )
        self.assertEqual(
            "Fully Traceable Evolution",
            full["summary"]["traceability_classification"],
        )
        self.assertEqual(
            "Broken Evolution Traceability",
            broken["summary"]["traceability_classification"],
        )
        self.assertEqual(
            "Untraceable Evolution",
            untraceable["summary"]["traceability_classification"],
        )
        self.assertEqual(1, single["summary"]["traceable_versions"])
        self.assertEqual(0, single["summary"]["untraceable_versions"])
        self.assertEqual(1, single["summary"]["traceable_timestamps"])
        self.assertEqual(0, single["summary"]["missing_timestamps"])
        self.assertEqual(1, single["summary"]["traceable_verification_hashes"])
        self.assertEqual(0, single["summary"]["missing_verification_hashes"])
        self.assertEqual(
            "Single Version Traceability",
            single["reviews"]["version"]["traceability_state"],
        )
        self.assertEqual(
            "No Supersession Links",
            single["reviews"]["supersession"]["traceability_state"],
        )
        self.assertEqual(
            "Single Timestamp Traceability",
            single["reviews"]["timestamp"]["traceability_state"],
        )
        self.assertEqual(
            "Single Verification Traceability",
            single["reviews"]["verification"]["traceability_state"],
        )

        for traceability_set, expected in (
            (full, "Fully Traceable Evolution"),
            (single, "Partial Evolution Traceability"),
            (untraceable, "Untraceable Evolution"),
            (broken, "Broken Evolution Traceability"),
        ):
            rendered = self.admin_session._render_stage18f_evolution_traceability_content(
                traceability_set
            )
            self.assertIn(
                f"<td>Traceability Classification</td><td>{expected}</td>",
                rendered,
            )
            self.assertIn("<h3>Traceability Summary</h3>", rendered)
            self.assertIn("<h3>Version Traceability Review</h3>", rendered)
            self.assertIn("<h3>Supersession Traceability Review</h3>", rendered)
            self.assertIn("<h3>Timestamp Traceability Review</h3>", rendered)
            self.assertIn("<h3>Verification Traceability Review</h3>", rendered)
            self.assertIn("<h3>Evolution Traceability Review</h3>", rendered)
            self.assertIn("<h3>Record Evolution Traceability</h3>", rendered)
            self.assertIn("Traceable Versions", rendered)
            self.assertIn("Untraceable Versions", rendered)
            self.assertIn("Traceable Timestamps", rendered)
            self.assertIn("Missing Timestamps", rendered)
            self.assertIn("Traceable Verification Hashes", rendered)
            self.assertIn("Missing Verification Hashes", rendered)

    def test_stage18g_record_evolution_coverage_renders_classification_states(self):
        def version_row(
            version,
            *,
            latest=0,
            hash_value="shared-hash",
            generated_at="default",
            supersedes=None,
        ):
            return {
                "reference": "Strike-LA-20260710-004",
                "version": version,
                "is_latest": latest,
                "supersedes": supersedes
                if supersedes is not None
                else (
                    None
                    if version == 1
                    else f"Strike-LA-20260710-004:v{version - 1}"
                ),
                "generated_at": None
                if generated_at is None
                else (
                    f"2026-06-0{version}T12:00:00Z"
                    if generated_at == "default"
                    else generated_at
                ),
                "verification_hash": hash_value,
                "trajectory": "Stable",
                "system_state": "PERSISTENT_RESISTANCE_WITHOUT_ADAPTATION",
                "finding": "Finding v1",
                "conditions_json": "[\"Escalation Without Response\"]",
                "signals_json": "[\"No Recurring Transition\"]",
                "generated_by": "civic-decision-engine",
            }

        base = {
            "reference": "Strike-LA-20260710-004",
            "version": 2,
            "supersedes": "Strike-LA-20260710-004:v1",
            "generated_at": "2026-06-02T12:00:00Z",
            "exported_at": "2026-06-02T12:05:00Z",
            "is_latest": 1,
            "trajectory": "Stable",
            "system_state": "PERSISTENT_RESISTANCE_WITHOUT_ADAPTATION",
            "finding": "Finding v1",
            "verification_hash": "shared-hash",
        }
        single_metadata = {**base, "version": 1, "supersedes": None}
        single_history = [version_row(1, latest=1)]
        full_history = [version_row(1), version_row(2, latest=1)]
        limited_history = [
            version_row(1, generated_at=None),
            version_row(2, latest=1),
        ]
        no_coverage_metadata = {
            **base,
            "version": 1,
            "supersedes": None,
            "generated_at": None,
            "verification_hash": None,
        }

        def coverage(metadata, lineage):
            return self.admin_session._record_stage18g_evolution_coverage(
                metadata,
                lineage,
            )

        single = coverage(single_metadata, single_history)
        full = coverage(base, full_history)
        limited = coverage(base, limited_history)
        no_coverage = coverage(no_coverage_metadata, [])
        unresolved = coverage({}, [])

        self.assertEqual(
            "Partial Evolution Coverage",
            single["summary"]["coverage_classification"],
        )
        self.assertEqual(
            "No Evolution Relationships",
            single["summary"]["relationship_classification"],
        )
        self.assertEqual(
            "Partial Evolution Traceability",
            single["summary"]["traceability_classification"],
        )
        self.assertEqual(0, single["summary"]["missing_versions"])
        self.assertEqual(0, single["summary"]["missing_timestamps"])
        self.assertEqual(0, single["summary"]["missing_verification_hashes"])
        self.assertEqual(0, single["summary"]["missing_evolution_outputs"])
        self.assertEqual(
            "Full Evolution Coverage",
            full["summary"]["coverage_classification"],
        )
        self.assertEqual(
            "Limited Evolution Coverage",
            limited["summary"]["coverage_classification"],
        )
        self.assertEqual(
            "No Evolution Coverage",
            no_coverage["summary"]["coverage_classification"],
        )
        self.assertEqual(
            "Unresolved Evolution Coverage",
            unresolved["summary"]["coverage_classification"],
        )
        self.assertEqual(1, single["summary"]["covered_versions"])
        self.assertEqual(0, single["summary"]["missing_versions"])
        self.assertEqual(1, single["summary"]["covered_timestamps"])
        self.assertEqual(0, single["summary"]["missing_timestamps"])
        self.assertEqual(1, single["summary"]["covered_verification_hashes"])
        self.assertEqual(0, single["summary"]["missing_verification_hashes"])
        self.assertEqual(6, single["summary"]["covered_evolution_outputs"])
        self.assertEqual(0, single["summary"]["missing_evolution_outputs"])
        self.assertEqual(
            "Single Version Coverage",
            single["reviews"]["version"]["coverage_state"],
        )
        self.assertEqual(
            "No Supersession Coverage",
            single["reviews"]["supersession"]["coverage_state"],
        )
        self.assertEqual(
            "Single Timestamp Coverage",
            single["reviews"]["timestamp"]["coverage_state"],
        )
        self.assertEqual(
            "Single Verification Coverage",
            single["reviews"]["verification"]["coverage_state"],
        )

        for coverage_set, expected in (
            (full, "Full Evolution Coverage"),
            (single, "Partial Evolution Coverage"),
            (limited, "Limited Evolution Coverage"),
            (no_coverage, "No Evolution Coverage"),
            (unresolved, "Unresolved Evolution Coverage"),
        ):
            rendered = self.admin_session._render_stage18g_evolution_coverage_content(
                coverage_set
            )
            self.assertIn(
                f"<td>Coverage Classification</td><td>{expected}</td>",
                rendered,
            )
            self.assertIn("<h3>Coverage Summary</h3>", rendered)
            self.assertIn("<h3>Version Coverage Review</h3>", rendered)
            self.assertIn("<h3>Supersession Coverage Review</h3>", rendered)
            self.assertIn("<h3>Timestamp Coverage Review</h3>", rendered)
            self.assertIn("<h3>Verification Coverage Review</h3>", rendered)
            self.assertIn("<h3>Evolution Output Coverage Review</h3>", rendered)
            self.assertIn("<h3>Record Evolution Coverage</h3>", rendered)
            self.assertIn("Covered Versions", rendered)
            self.assertIn("Missing Versions", rendered)
            self.assertIn("Covered Timestamps", rendered)
            self.assertIn("Missing Timestamps", rendered)
            self.assertIn("Covered Verification Hashes", rendered)
            self.assertIn("Missing Verification Hashes", rendered)
            self.assertIn("Covered Evolution Outputs", rendered)
            self.assertIn("Missing Evolution Outputs", rendered)

    def test_stage18h_record_evolution_review_renders_classification_states(self):
        def version_row(
            version,
            *,
            latest=0,
            hash_value="shared-hash",
            generated_at="default",
            supersedes=None,
        ):
            return {
                "reference": "Strike-LA-20260710-004",
                "version": version,
                "is_latest": latest,
                "supersedes": supersedes
                if supersedes is not None
                else (
                    None
                    if version == 1
                    else f"Strike-LA-20260710-004:v{version - 1}"
                ),
                "generated_at": None
                if generated_at is None
                else (
                    f"2026-06-0{version}T12:00:00Z"
                    if generated_at == "default"
                    else generated_at
                ),
                "verification_hash": hash_value,
                "trajectory": "Stable",
                "system_state": "PERSISTENT_RESISTANCE_WITHOUT_ADAPTATION",
                "finding": "Finding v1",
                "conditions_json": "[\"Escalation Without Response\"]",
                "signals_json": "[\"No Recurring Transition\"]",
                "generated_by": "civic-decision-engine",
            }

        base = {
            "reference": "Strike-LA-20260710-004",
            "version": 2,
            "supersedes": "Strike-LA-20260710-004:v1",
            "generated_at": "2026-06-02T12:00:00Z",
            "exported_at": "2026-06-02T12:05:00Z",
            "is_latest": 1,
            "trajectory": "Stable",
            "system_state": "PERSISTENT_RESISTANCE_WITHOUT_ADAPTATION",
            "finding": "Finding v1",
            "verification_hash": "shared-hash",
        }
        single_metadata = {**base, "version": 1, "supersedes": None}
        single_history = [version_row(1, latest=1)]
        full_history = [version_row(1), version_row(2, latest=1)]
        limited_history = [
            version_row(1, generated_at=None),
            version_row(2, latest=1),
        ]
        no_review_metadata = {
            **base,
            "version": 1,
            "supersedes": None,
            "generated_at": None,
            "verification_hash": None,
        }

        def review(metadata, lineage):
            return self.admin_session._record_stage18h_evolution_review(
                metadata,
                lineage,
            )

        single = review(single_metadata, single_history)
        full = review(base, full_history)
        limited = review(base, limited_history)
        no_review = review(no_review_metadata, [])
        unresolved = review({}, [])

        self.assertEqual(
            "Partial Evolution Review",
            single["summary"]["review_classification"],
        )
        self.assertEqual(1, single["summary"]["reviewable_versions"])
        self.assertEqual(0, single["summary"]["unreviewable_versions"])
        self.assertEqual(7, single["summary"]["reviewable_evolution_outputs"])
        self.assertEqual(0, single["summary"]["missing_evolution_outputs"])
        self.assertEqual(0, single["summary"]["missing_coverage_components"])
        self.assertEqual(
            "Single Reviewable Version",
            single["reviews"]["version"]["review_state"],
        )
        self.assertEqual(
            "Partially Reviewable Evolution Outputs",
            single["reviews"]["evolution_output"]["review_state"],
        )
        self.assertEqual(
            "Partially Covered Review",
            single["reviews"]["coverage"]["review_state"],
        )
        self.assertEqual(
            "Partially Traceable Review",
            single["reviews"]["traceability"]["review_state"],
        )
        self.assertEqual(
            "No Relationship Review",
            single["reviews"]["relationship"]["review_state"],
        )
        self.assertEqual(
            "Complete Evolution Review",
            full["summary"]["review_classification"],
        )
        self.assertEqual(
            "Limited Evolution Review",
            limited["summary"]["review_classification"],
        )
        self.assertEqual(
            "No Evolution Review",
            no_review["summary"]["review_classification"],
        )
        self.assertEqual(
            "Unresolved Evolution Review",
            unresolved["summary"]["review_classification"],
        )

        for review_set, expected in (
            (full, "Complete Evolution Review"),
            (single, "Partial Evolution Review"),
            (limited, "Limited Evolution Review"),
            (no_review, "No Evolution Review"),
            (unresolved, "Unresolved Evolution Review"),
        ):
            rendered = self.admin_session._render_stage18h_evolution_review_content(
                review_set
            )
            self.assertIn(
                f"<td>Review Classification</td><td>{expected}</td>",
                rendered,
            )
            self.assertIn("<h3>Review Summary</h3>", rendered)
            self.assertIn("<h3>Version Review</h3>", rendered)
            self.assertIn("<h3>Evolution Output Review</h3>", rendered)
            self.assertIn("<h3>Coverage Review</h3>", rendered)
            self.assertIn("<h3>Traceability Review</h3>", rendered)
            self.assertIn("<h3>Relationship Review</h3>", rendered)
            self.assertIn("<h3>Record Evolution Review</h3>", rendered)
            self.assertIn("Reviewable Versions", rendered)
            self.assertIn("Unreviewable Versions", rendered)
            self.assertIn("Reviewable Evolution Outputs", rendered)
            self.assertIn("Missing Evolution Outputs", rendered)
            self.assertIn("Limited Evolution Outputs", rendered)
            self.assertIn("Missing Coverage Components", rendered)

    def test_stage18i_record_evolution_readiness_renders_classification_states(self):
        def version_row(
            version,
            *,
            latest=0,
            hash_value="shared-hash",
            generated_at="default",
            supersedes=None,
        ):
            return {
                "reference": "Strike-LA-20260710-004",
                "version": version,
                "is_latest": latest,
                "supersedes": supersedes
                if supersedes is not None
                else (
                    None
                    if version == 1
                    else f"Strike-LA-20260710-004:v{version - 1}"
                ),
                "generated_at": None
                if generated_at is None
                else (
                    f"2026-06-0{version}T12:00:00Z"
                    if generated_at == "default"
                    else generated_at
                ),
                "verification_hash": hash_value,
                "trajectory": "Stable",
                "system_state": "PERSISTENT_RESISTANCE_WITHOUT_ADAPTATION",
                "finding": "Finding v1",
                "conditions_json": "[\"Escalation Without Response\"]",
                "signals_json": "[\"No Recurring Transition\"]",
                "generated_by": "civic-decision-engine",
            }

        base = {
            "reference": "Strike-LA-20260710-004",
            "version": 2,
            "supersedes": "Strike-LA-20260710-004:v1",
            "generated_at": "2026-06-02T12:00:00Z",
            "exported_at": "2026-06-02T12:05:00Z",
            "is_latest": 1,
            "trajectory": "Stable",
            "system_state": "PERSISTENT_RESISTANCE_WITHOUT_ADAPTATION",
            "finding": "Finding v1",
            "verification_hash": "shared-hash",
        }
        single_metadata = {**base, "version": 1, "supersedes": None}
        single_history = [version_row(1, latest=1)]
        full_history = [version_row(1), version_row(2, latest=1)]
        limited_history = [
            version_row(1, generated_at=None),
            version_row(2, latest=1),
        ]
        no_readiness_metadata = {
            **base,
            "version": 1,
            "supersedes": None,
            "generated_at": None,
            "verification_hash": None,
        }

        def readiness(metadata, lineage):
            return self.admin_session._record_stage18i_evolution_readiness(
                metadata,
                lineage,
            )

        single = readiness(single_metadata, single_history)
        full = readiness(base, full_history)
        limited = readiness(base, limited_history)
        no_readiness = readiness(no_readiness_metadata, [])
        unresolved = readiness({}, [])

        self.assertEqual(
            "Partially Evolution Ready",
            single["summary"]["readiness_classification"],
        )
        self.assertEqual(1, single["summary"]["reviewable_versions"])
        self.assertEqual(1, single["summary"]["traceable_versions"])
        self.assertEqual(1, single["summary"]["covered_versions"])
        self.assertEqual(8, single["summary"]["reviewable_evolution_outputs"])
        self.assertEqual(0, single["summary"]["missing_evolution_outputs"])
        self.assertEqual(0, single["summary"]["missing_coverage_components"])
        self.assertEqual(
            "Partially Version Ready",
            single["reviews"]["version"]["readiness_state"],
        )
        self.assertEqual(
            "Partially Coverage Ready",
            single["reviews"]["coverage"]["readiness_state"],
        )
        self.assertEqual(
            "Partially Traceability Ready",
            single["reviews"]["traceability"]["readiness_state"],
        )
        self.assertEqual(
            "Partially Review Ready",
            single["reviews"]["review"]["readiness_state"],
        )
        self.assertEqual(
            "Partially Ready Evolution Chain",
            single["reviews"]["evolution"]["readiness_state"],
        )
        self.assertEqual(
            "Fully Evolution Ready",
            full["summary"]["readiness_classification"],
        )
        self.assertEqual(
            "Limited Evolution Readiness",
            limited["summary"]["readiness_classification"],
        )
        self.assertEqual(
            "No Evolution Readiness",
            no_readiness["summary"]["readiness_classification"],
        )
        self.assertEqual(
            "Unresolved Evolution Readiness",
            unresolved["summary"]["readiness_classification"],
        )

        for readiness_set, expected in (
            (full, "Fully Evolution Ready"),
            (single, "Partially Evolution Ready"),
            (limited, "Limited Evolution Readiness"),
            (no_readiness, "No Evolution Readiness"),
            (unresolved, "Unresolved Evolution Readiness"),
        ):
            rendered = (
                self.admin_session._render_stage18i_evolution_readiness_content(
                    readiness_set
                )
            )
            self.assertIn(
                f"<td>Readiness Classification</td><td>{expected}</td>",
                rendered,
            )
            self.assertIn("<h3>Readiness Summary</h3>", rendered)
            self.assertIn("<h3>Version Readiness Review</h3>", rendered)
            self.assertIn("<h3>Coverage Readiness Review</h3>", rendered)
            self.assertIn("<h3>Traceability Readiness Review</h3>", rendered)
            self.assertIn("<h3>Review Readiness Review</h3>", rendered)
            self.assertIn("<h3>Evolution Readiness Review</h3>", rendered)
            self.assertIn("<h3>Record Evolution Readiness</h3>", rendered)
            self.assertIn("Reviewable Versions", rendered)
            self.assertIn("Traceable Versions", rendered)
            self.assertIn("Covered Versions", rendered)
            self.assertIn("Reviewable Evolution Outputs", rendered)
            self.assertIn("Missing Evolution Outputs", rendered)
            self.assertIn("Limited Evolution Outputs", rendered)
            self.assertIn("Missing Coverage Components", rendered)

    def test_stage18j_record_evolution_completeness_renders_classification_states(self):
        def version_row(
            version,
            *,
            latest=0,
            hash_value="shared-hash",
            generated_at="default",
            supersedes=None,
        ):
            return {
                "reference": "Strike-LA-20260710-004",
                "version": version,
                "is_latest": latest,
                "supersedes": supersedes
                if supersedes is not None
                else (
                    None
                    if version == 1
                    else f"Strike-LA-20260710-004:v{version - 1}"
                ),
                "generated_at": None
                if generated_at is None
                else (
                    f"2026-06-0{version}T12:00:00Z"
                    if generated_at == "default"
                    else generated_at
                ),
                "verification_hash": hash_value,
                "trajectory": "Stable",
                "system_state": "PERSISTENT_RESISTANCE_WITHOUT_ADAPTATION",
                "finding": "Finding v1",
                "conditions_json": "[\"Escalation Without Response\"]",
                "signals_json": "[\"No Recurring Transition\"]",
                "generated_by": "civic-decision-engine",
            }

        base = {
            "reference": "Strike-LA-20260710-004",
            "version": 2,
            "supersedes": "Strike-LA-20260710-004:v1",
            "generated_at": "2026-06-02T12:00:00Z",
            "exported_at": "2026-06-02T12:05:00Z",
            "is_latest": 1,
            "trajectory": "Stable",
            "system_state": "PERSISTENT_RESISTANCE_WITHOUT_ADAPTATION",
            "finding": "Finding v1",
            "verification_hash": "shared-hash",
        }
        single_metadata = {**base, "version": 1, "supersedes": None}
        single_history = [version_row(1, latest=1)]
        full_history = [version_row(1), version_row(2, latest=1)]
        limited_history = [
            version_row(1, generated_at=None),
            version_row(2, latest=1),
        ]
        no_completeness_metadata = {
            **base,
            "version": 1,
            "supersedes": None,
            "generated_at": None,
            "verification_hash": None,
        }

        def completeness(metadata, lineage):
            return self.admin_session._record_stage18j_evolution_completeness(
                metadata,
                lineage,
            )

        single = completeness(single_metadata, single_history)
        full = completeness(base, full_history)
        limited = completeness(base, limited_history)
        no_completeness = completeness(no_completeness_metadata, [])
        unresolved = completeness({}, [])

        self.assertEqual(
            "Partially Complete Evolution Chain",
            single["summary"]["completeness_classification"],
        )
        self.assertEqual(1, single["summary"]["complete_versions"])
        self.assertEqual(0, single["summary"]["incomplete_versions"])
        self.assertEqual(9, single["summary"]["complete_evolution_outputs"])
        self.assertEqual(0, single["summary"]["missing_evolution_outputs"])
        self.assertEqual(4, single["summary"]["complete_coverage_components"])
        self.assertEqual(0, single["summary"]["missing_coverage_components"])
        self.assertEqual(4, single["summary"]["complete_readiness_components"])
        self.assertEqual(0, single["summary"]["missing_readiness_components"])
        self.assertEqual(
            "Partially Complete Version Chain",
            single["reviews"]["version"]["completeness_state"],
        )
        self.assertEqual(
            "Complete Evolution Outputs",
            single["reviews"]["evolution_output"]["completeness_state"],
        )
        self.assertEqual(
            "Partially Complete Coverage Components",
            single["reviews"]["coverage"]["completeness_state"],
        )
        self.assertEqual(
            "Partially Complete Review Components",
            single["reviews"]["review"]["completeness_state"],
        )
        self.assertEqual(
            "Partially Complete Readiness Components",
            single["reviews"]["readiness"]["completeness_state"],
        )
        self.assertEqual(
            "Partially Complete Evolution Chain",
            single["reviews"]["evolution"]["completeness_state"],
        )
        self.assertEqual(
            "Complete Evolution Chain",
            full["summary"]["completeness_classification"],
        )
        self.assertEqual(
            "Limited Evolution Completeness",
            limited["summary"]["completeness_classification"],
        )
        self.assertEqual(
            "No Evolution Completeness",
            no_completeness["summary"]["completeness_classification"],
        )
        self.assertEqual(
            "Unresolved Evolution Completeness",
            unresolved["summary"]["completeness_classification"],
        )

        for completeness_set, expected in (
            (full, "Complete Evolution Chain"),
            (single, "Partially Complete Evolution Chain"),
            (limited, "Limited Evolution Completeness"),
            (no_completeness, "No Evolution Completeness"),
            (unresolved, "Unresolved Evolution Completeness"),
        ):
            rendered = self.admin_session._render_stage18j_evolution_completeness_content(
                completeness_set
            )
            self.assertIn(
                f"<td>Completeness Classification</td><td>{expected}</td>",
                rendered,
            )
            self.assertIn("<h3>Completeness Summary</h3>", rendered)
            self.assertIn("<h3>Version Completeness Review</h3>", rendered)
            self.assertIn(
                "<h3>Evolution Output Completeness Review</h3>",
                rendered,
            )
            self.assertIn("<h3>Coverage Completeness Review</h3>", rendered)
            self.assertIn("<h3>Review Completeness Review</h3>", rendered)
            self.assertIn("<h3>Readiness Completeness Review</h3>", rendered)
            self.assertIn("<h3>Evolution Completeness Review</h3>", rendered)
            self.assertIn("<h3>Record Evolution Completeness</h3>", rendered)
            self.assertIn("Complete Versions", rendered)
            self.assertIn("Incomplete Versions", rendered)
            self.assertIn("Complete Evolution Outputs", rendered)
            self.assertIn("Missing Evolution Outputs", rendered)
            self.assertIn("Complete Coverage Components", rendered)
            self.assertIn("Missing Coverage Components", rendered)
            self.assertIn("Complete Readiness Components", rendered)
            self.assertIn("Missing Readiness Components", rendered)

    def test_stage18k_record_evolution_sufficiency_renders_classification_states(self):
        def version_row(
            version,
            *,
            latest=0,
            hash_value="shared-hash",
            generated_at="default",
            supersedes=None,
        ):
            return {
                "reference": "Strike-LA-20260710-004",
                "version": version,
                "is_latest": latest,
                "supersedes": supersedes
                if supersedes is not None
                else (
                    None
                    if version == 1
                    else f"Strike-LA-20260710-004:v{version - 1}"
                ),
                "generated_at": None
                if generated_at is None
                else (
                    f"2026-06-0{version}T12:00:00Z"
                    if generated_at == "default"
                    else generated_at
                ),
                "verification_hash": hash_value,
                "trajectory": "Stable",
                "system_state": "PERSISTENT_RESISTANCE_WITHOUT_ADAPTATION",
                "finding": "Finding v1",
                "conditions_json": "[\"Escalation Without Response\"]",
                "signals_json": "[\"No Recurring Transition\"]",
                "generated_by": "civic-decision-engine",
            }

        base = {
            "reference": "Strike-LA-20260710-004",
            "version": 2,
            "supersedes": "Strike-LA-20260710-004:v1",
            "generated_at": "2026-06-02T12:00:00Z",
            "exported_at": "2026-06-02T12:05:00Z",
            "is_latest": 1,
            "trajectory": "Stable",
            "system_state": "PERSISTENT_RESISTANCE_WITHOUT_ADAPTATION",
            "finding": "Finding v1",
            "verification_hash": "shared-hash",
        }
        single_metadata = {**base, "version": 1, "supersedes": None}
        single_history = [version_row(1, latest=1)]
        full_history = [version_row(1), version_row(2, latest=1)]
        limited_history = [
            version_row(1, generated_at=None),
            version_row(2, latest=1),
        ]
        no_information_metadata = {
            **base,
            "version": 1,
            "supersedes": None,
            "generated_at": None,
            "verification_hash": None,
        }

        def sufficiency(metadata, lineage):
            return self.admin_session._record_stage18k_evolution_sufficiency(
                metadata,
                lineage,
            )

        single = sufficiency(single_metadata, single_history)
        full = sufficiency(base, full_history)
        limited = sufficiency(base, limited_history)
        no_information = sufficiency(no_information_metadata, [])
        unresolved = sufficiency({}, [])

        self.assertEqual(
            "Partially Sufficient Evolution Information",
            single["summary"]["sufficiency_classification"],
        )
        self.assertEqual(1, single["summary"]["sufficient_versions"])
        self.assertEqual(0, single["summary"]["insufficient_versions"])
        self.assertEqual(10, single["summary"]["sufficient_evolution_outputs"])
        self.assertEqual(0, single["summary"]["missing_evolution_outputs"])
        self.assertEqual(4, single["summary"]["sufficient_coverage_components"])
        self.assertEqual(0, single["summary"]["missing_coverage_components"])
        self.assertEqual(4, single["summary"]["sufficient_readiness_components"])
        self.assertEqual(0, single["summary"]["missing_readiness_components"])
        self.assertEqual(5, single["summary"]["sufficient_completeness_components"])
        self.assertEqual(0, single["summary"]["missing_completeness_components"])
        self.assertEqual(
            "Partially Sufficient Version Chain",
            single["reviews"]["version"]["sufficiency_state"],
        )
        self.assertEqual(
            "Sufficient Evolution Outputs",
            single["reviews"]["evolution_output"]["sufficiency_state"],
        )
        self.assertEqual(
            "Partially Sufficient Coverage Components",
            single["reviews"]["coverage"]["sufficiency_state"],
        )
        self.assertEqual(
            "Partially Sufficient Review Components",
            single["reviews"]["review"]["sufficiency_state"],
        )
        self.assertEqual(
            "Partially Sufficient Readiness Components",
            single["reviews"]["readiness"]["sufficiency_state"],
        )
        self.assertEqual(
            "Partially Sufficient Completeness Components",
            single["reviews"]["completeness"]["sufficiency_state"],
        )
        self.assertEqual(
            "Partially Sufficient Evolution Information",
            single["reviews"]["evolution"]["sufficiency_state"],
        )
        self.assertEqual(
            "Sufficient Evolution Information",
            full["summary"]["sufficiency_classification"],
        )
        self.assertEqual(
            "Limited Evolution Information",
            limited["summary"]["sufficiency_classification"],
        )
        self.assertEqual(
            "No Evolution Information",
            no_information["summary"]["sufficiency_classification"],
        )
        self.assertEqual(
            "Unresolved Evolution Information",
            unresolved["summary"]["sufficiency_classification"],
        )

        for sufficiency_set, expected in (
            (full, "Sufficient Evolution Information"),
            (single, "Partially Sufficient Evolution Information"),
            (limited, "Limited Evolution Information"),
            (no_information, "No Evolution Information"),
            (unresolved, "Unresolved Evolution Information"),
        ):
            rendered = self.admin_session._render_stage18k_evolution_sufficiency_content(
                sufficiency_set
            )
            self.assertIn(
                f"<td>Sufficiency Classification</td><td>{expected}</td>",
                rendered,
            )
            self.assertIn("<h3>Sufficiency Summary</h3>", rendered)
            self.assertIn("<h3>Version Sufficiency Review</h3>", rendered)
            self.assertIn("<h3>Evolution Output Sufficiency Review</h3>", rendered)
            self.assertIn("<h3>Coverage Sufficiency Review</h3>", rendered)
            self.assertIn("<h3>Review Sufficiency Review</h3>", rendered)
            self.assertIn("<h3>Readiness Sufficiency Review</h3>", rendered)
            self.assertIn("<h3>Completeness Sufficiency Review</h3>", rendered)
            self.assertIn("<h3>Evolution Sufficiency Review</h3>", rendered)
            self.assertIn("<h3>Record Evolution Sufficiency</h3>", rendered)
            self.assertIn("Sufficient Versions", rendered)
            self.assertIn("Insufficient Versions", rendered)
            self.assertIn("Sufficient Evolution Outputs", rendered)
            self.assertIn("Missing Evolution Outputs", rendered)
            self.assertIn("Sufficient Coverage Components", rendered)
            self.assertIn("Missing Coverage Components", rendered)
            self.assertIn("Sufficient Readiness Components", rendered)
            self.assertIn("Missing Readiness Components", rendered)
            self.assertIn("Sufficient Completeness Components", rendered)
            self.assertIn("Missing Completeness Components", rendered)

    def test_stage18l_record_evolution_consistency_renders_classification_states(self):
        def version_row(
            version,
            *,
            latest=0,
            hash_value="shared-hash",
            generated_at="default",
            supersedes=None,
        ):
            return {
                "reference": "Strike-LA-20260710-004",
                "version": version,
                "is_latest": latest,
                "supersedes": supersedes
                if supersedes is not None
                else (
                    None
                    if version == 1
                    else f"Strike-LA-20260710-004:v{version - 1}"
                ),
                "generated_at": None
                if generated_at is None
                else (
                    f"2026-06-0{version}T12:00:00Z"
                    if generated_at == "default"
                    else generated_at
                ),
                "verification_hash": hash_value,
                "trajectory": "Stable",
                "system_state": "PERSISTENT_RESISTANCE_WITHOUT_ADAPTATION",
                "finding": "Finding v1",
                "conditions_json": "[\"Escalation Without Response\"]",
                "signals_json": "[\"No Recurring Transition\"]",
                "generated_by": "civic-decision-engine",
            }

        base = {
            "reference": "Strike-LA-20260710-004",
            "version": 2,
            "supersedes": "Strike-LA-20260710-004:v1",
            "generated_at": "2026-06-02T12:00:00Z",
            "exported_at": "2026-06-02T12:05:00Z",
            "is_latest": 1,
            "trajectory": "Stable",
            "system_state": "PERSISTENT_RESISTANCE_WITHOUT_ADAPTATION",
            "finding": "Finding v1",
            "verification_hash": "shared-hash",
        }
        single_metadata = {**base, "version": 1, "supersedes": None}
        single_history = [version_row(1, latest=1)]
        full_history = [version_row(1), version_row(2, latest=1)]
        limited_history = [
            version_row(1, generated_at=None),
            version_row(2, latest=1),
        ]
        inconsistent_history = [
            version_row(1, generated_at="2026-06-03T12:00:00Z"),
            version_row(2, latest=1, generated_at="2026-06-02T12:00:00Z"),
        ]
        no_consistency_metadata = {
            **base,
            "version": 1,
            "supersedes": None,
            "generated_at": None,
            "verification_hash": None,
        }

        def consistency(metadata, lineage):
            return self.admin_session._record_stage18l_evolution_consistency(
                metadata,
                lineage,
            )

        single = consistency(single_metadata, single_history)
        full = consistency(base, full_history)
        limited = consistency(base, limited_history)
        inconsistent = consistency(base, inconsistent_history)
        no_consistency = consistency(no_consistency_metadata, [])
        unresolved = consistency({}, [])

        self.assertEqual(
            "Partially Consistent Evolution Chain",
            single["summary"]["consistency_classification"],
        )
        self.assertEqual(1, single["summary"]["consistent_versions"])
        self.assertEqual(0, single["summary"]["inconsistent_versions"])
        self.assertEqual(0, single["summary"]["consistent_supersession_links"])
        self.assertEqual(0, single["summary"]["inconsistent_supersession_links"])
        self.assertEqual(1, single["summary"]["consistent_timestamps"])
        self.assertEqual(0, single["summary"]["inconsistent_timestamps"])
        self.assertEqual(1, single["summary"]["consistent_verification_hashes"])
        self.assertEqual(0, single["summary"]["inconsistent_verification_hashes"])
        self.assertEqual(11, single["summary"]["consistent_evolution_outputs"])
        self.assertEqual(0, single["summary"]["inconsistent_evolution_outputs"])
        self.assertEqual(0, single["summary"]["missing_evolution_outputs"])
        self.assertEqual(
            "Partially Consistent Version Chain",
            single["reviews"]["version"]["consistency_state"],
        )
        self.assertEqual(
            "Partially Consistent Supersession Chain",
            single["reviews"]["supersession"]["consistency_state"],
        )
        self.assertEqual(
            "Partially Consistent Timestamp Chain",
            single["reviews"]["timestamp"]["consistency_state"],
        )
        self.assertEqual(
            "Partially Consistent Verification Chain",
            single["reviews"]["verification"]["consistency_state"],
        )
        self.assertEqual(
            "Partially Consistent Evolution Outputs",
            single["reviews"]["evolution_output"]["consistency_state"],
        )
        self.assertEqual(
            "Consistent Evolution Chain",
            full["summary"]["consistency_classification"],
        )
        self.assertEqual(
            "Limited Evolution Consistency",
            limited["summary"]["consistency_classification"],
        )
        self.assertEqual(
            "Inconsistent Evolution Chain",
            inconsistent["summary"]["consistency_classification"],
        )
        self.assertEqual(
            "No Evolution Consistency",
            no_consistency["summary"]["consistency_classification"],
        )
        self.assertEqual(
            "Unresolved Evolution Consistency",
            unresolved["summary"]["consistency_classification"],
        )

        for consistency_set, expected in (
            (full, "Consistent Evolution Chain"),
            (single, "Partially Consistent Evolution Chain"),
            (limited, "Limited Evolution Consistency"),
            (inconsistent, "Inconsistent Evolution Chain"),
            (no_consistency, "No Evolution Consistency"),
            (unresolved, "Unresolved Evolution Consistency"),
        ):
            rendered = self.admin_session._render_stage18l_evolution_consistency_content(
                consistency_set
            )
            self.assertIn(
                f"<td>Consistency Classification</td><td>{expected}</td>",
                rendered,
            )
            self.assertIn("<h3>Consistency Summary</h3>", rendered)
            self.assertIn("<h3>Version Consistency Review</h3>", rendered)
            self.assertIn("<h3>Supersession Consistency Review</h3>", rendered)
            self.assertIn("<h3>Timestamp Consistency Review</h3>", rendered)
            self.assertIn("<h3>Verification Consistency Review</h3>", rendered)
            self.assertIn("<h3>Evolution Output Consistency Review</h3>", rendered)
            self.assertIn("<h3>Evolution Consistency Review</h3>", rendered)
            self.assertIn("<h3>Record Evolution Consistency</h3>", rendered)
            self.assertIn("Consistent Versions", rendered)
            self.assertIn("Inconsistent Versions", rendered)
            self.assertIn("Consistent Supersession Links", rendered)
            self.assertIn("Inconsistent Supersession Links", rendered)
            self.assertIn("Consistent Timestamps", rendered)
            self.assertIn("Inconsistent Timestamps", rendered)
            self.assertIn("Consistent Verification Hashes", rendered)
            self.assertIn("Inconsistent Verification Hashes", rendered)
            self.assertIn("Consistent Evolution Outputs", rendered)
            self.assertIn("Inconsistent Evolution Outputs", rendered)
            self.assertIn("Missing Evolution Outputs", rendered)

    def test_stage18m_record_evolution_integrity_renders_classification_states(self):
        def version_row(
            version,
            *,
            latest=0,
            hash_value="shared-hash",
            generated_at="default",
            supersedes=None,
        ):
            return {
                "reference": "Strike-LA-20260710-004",
                "version": version,
                "is_latest": latest,
                "supersedes": supersedes
                if supersedes is not None
                else (
                    None
                    if version == 1
                    else f"Strike-LA-20260710-004:v{version - 1}"
                ),
                "generated_at": None
                if generated_at is None
                else (
                    f"2026-06-0{version}T12:00:00Z"
                    if generated_at == "default"
                    else generated_at
                ),
                "verification_hash": hash_value,
                "trajectory": "Stable",
                "system_state": "PERSISTENT_RESISTANCE_WITHOUT_ADAPTATION",
                "finding": "Finding v1",
                "conditions_json": "[\"Escalation Without Response\"]",
                "signals_json": "[\"No Recurring Transition\"]",
                "generated_by": "civic-decision-engine",
            }

        base = {
            "reference": "Strike-LA-20260710-004",
            "version": 2,
            "supersedes": "Strike-LA-20260710-004:v1",
            "generated_at": "2026-06-02T12:00:00Z",
            "exported_at": "2026-06-02T12:05:00Z",
            "is_latest": 1,
            "trajectory": "Stable",
            "system_state": "PERSISTENT_RESISTANCE_WITHOUT_ADAPTATION",
            "finding": "Finding v1",
            "verification_hash": "shared-hash",
        }
        single_metadata = {**base, "version": 1, "supersedes": None}
        single_history = [version_row(1, latest=1)]
        full_history = [version_row(1), version_row(2, latest=1)]
        limited_history = [
            version_row(1, generated_at=None),
            version_row(2, latest=1),
        ]
        broken_history = [
            version_row(1, generated_at="2026-06-03T12:00:00Z"),
            version_row(2, latest=1, generated_at="2026-06-02T12:00:00Z"),
        ]
        no_integrity_metadata = {
            **base,
            "version": 1,
            "supersedes": None,
            "generated_at": None,
            "verification_hash": None,
        }

        def integrity(metadata, lineage):
            return self.admin_session._record_stage18m_evolution_integrity(
                metadata,
                lineage,
            )

        single = integrity(single_metadata, single_history)
        full = integrity(base, full_history)
        limited = integrity(base, limited_history)
        broken = integrity(base, broken_history)
        no_integrity = integrity(no_integrity_metadata, [])
        unresolved = integrity({}, [])

        self.assertEqual(
            "Partial Evolution Integrity",
            single["summary"]["integrity_classification"],
        )
        self.assertEqual(1, single["summary"]["intact_versions"])
        self.assertEqual(0, single["summary"]["broken_versions"])
        self.assertEqual(0, single["summary"]["intact_supersession_links"])
        self.assertEqual(0, single["summary"]["broken_supersession_links"])
        self.assertEqual(1, single["summary"]["intact_timestamps"])
        self.assertEqual(0, single["summary"]["broken_timestamps"])
        self.assertEqual(1, single["summary"]["intact_verification_hashes"])
        self.assertEqual(0, single["summary"]["broken_verification_hashes"])
        self.assertEqual(12, single["summary"]["intact_evolution_outputs"])
        self.assertEqual(0, single["summary"]["broken_evolution_outputs"])
        self.assertEqual(0, single["summary"]["missing_evolution_outputs"])
        self.assertEqual(
            "Partially Intact Version Chain",
            single["reviews"]["version"]["integrity_state"],
        )
        self.assertEqual(
            "Partially Intact Supersession Chain",
            single["reviews"]["supersession"]["integrity_state"],
        )
        self.assertEqual(
            "Partially Intact Timestamp Chain",
            single["reviews"]["timestamp"]["integrity_state"],
        )
        self.assertEqual(
            "Partially Intact Verification Chain",
            single["reviews"]["verification"]["integrity_state"],
        )
        self.assertEqual(
            "Partially Intact Evolution Outputs",
            single["reviews"]["evolution_output"]["integrity_state"],
        )
        self.assertEqual(
            "Full Evolution Integrity",
            full["summary"]["integrity_classification"],
        )
        self.assertEqual(
            "Limited Evolution Integrity",
            limited["summary"]["integrity_classification"],
        )
        self.assertEqual(
            "Broken Evolution Integrity",
            broken["summary"]["integrity_classification"],
        )
        self.assertEqual(
            "No Evolution Integrity",
            no_integrity["summary"]["integrity_classification"],
        )
        self.assertEqual(
            "Unresolved Evolution Integrity",
            unresolved["summary"]["integrity_classification"],
        )

        for integrity_set, expected in (
            (full, "Full Evolution Integrity"),
            (single, "Partial Evolution Integrity"),
            (limited, "Limited Evolution Integrity"),
            (broken, "Broken Evolution Integrity"),
            (no_integrity, "No Evolution Integrity"),
            (unresolved, "Unresolved Evolution Integrity"),
        ):
            rendered = self.admin_session._render_stage18m_evolution_integrity_content(
                integrity_set
            )
            self.assertIn(
                f"<td>Integrity Classification</td><td>{expected}</td>",
                rendered,
            )
            self.assertIn("<h3>Integrity Summary</h3>", rendered)
            self.assertIn("<h3>Version Integrity Review</h3>", rendered)
            self.assertIn("<h3>Supersession Integrity Review</h3>", rendered)
            self.assertIn("<h3>Timestamp Integrity Review</h3>", rendered)
            self.assertIn("<h3>Verification Integrity Review</h3>", rendered)
            self.assertIn("<h3>Evolution Output Integrity Review</h3>", rendered)
            self.assertIn("<h3>Evolution Integrity Review</h3>", rendered)
            self.assertIn("<h3>Record Evolution Integrity</h3>", rendered)
            self.assertIn("Intact Versions", rendered)
            self.assertIn("Broken Versions", rendered)
            self.assertIn("Intact Supersession Links", rendered)
            self.assertIn("Broken Supersession Links", rendered)
            self.assertIn("Intact Timestamps", rendered)
            self.assertIn("Broken Timestamps", rendered)
            self.assertIn("Intact Verification Hashes", rendered)
            self.assertIn("Broken Verification Hashes", rendered)
            self.assertIn("Intact Evolution Outputs", rendered)
            self.assertIn("Broken Evolution Outputs", rendered)
            self.assertIn("Missing Evolution Outputs", rendered)

    def test_stage18n_record_evolution_reliability_renders_classification_states(self):
        def version_row(
            version,
            *,
            latest=0,
            hash_value="shared-hash",
            generated_at="default",
            supersedes=None,
        ):
            return {
                "reference": "Strike-LA-20260710-004",
                "version": version,
                "is_latest": latest,
                "supersedes": supersedes
                if supersedes is not None
                else (
                    None
                    if version == 1
                    else f"Strike-LA-20260710-004:v{version - 1}"
                ),
                "generated_at": None
                if generated_at is None
                else (
                    f"2026-06-0{version}T12:00:00Z"
                    if generated_at == "default"
                    else generated_at
                ),
                "verification_hash": hash_value,
                "trajectory": "Stable",
                "system_state": "PERSISTENT_RESISTANCE_WITHOUT_ADAPTATION",
                "finding": "Finding v1",
                "conditions_json": "[\"Escalation Without Response\"]",
                "signals_json": "[\"No Recurring Transition\"]",
                "generated_by": "civic-decision-engine",
            }

        base = {
            "reference": "Strike-LA-20260710-004",
            "version": 2,
            "supersedes": "Strike-LA-20260710-004:v1",
            "generated_at": "2026-06-02T12:00:00Z",
            "exported_at": "2026-06-02T12:05:00Z",
            "is_latest": 1,
            "trajectory": "Stable",
            "system_state": "PERSISTENT_RESISTANCE_WITHOUT_ADAPTATION",
            "finding": "Finding v1",
            "verification_hash": "shared-hash",
        }
        single_metadata = {**base, "version": 1, "supersedes": None}
        single_history = [version_row(1, latest=1)]
        full_history = [version_row(1), version_row(2, latest=1)]
        limited_history = [
            version_row(1, generated_at=None),
            version_row(2, latest=1),
        ]
        unreliable_history = [
            version_row(1, generated_at="2026-06-03T12:00:00Z"),
            version_row(2, latest=1, generated_at="2026-06-02T12:00:00Z"),
        ]
        no_reliability_metadata = {
            **base,
            "version": 1,
            "supersedes": None,
            "generated_at": None,
            "verification_hash": None,
        }

        def reliability(metadata, lineage):
            return self.admin_session._record_stage18n_evolution_reliability(
                metadata,
                lineage,
            )

        single = reliability(single_metadata, single_history)
        full = reliability(base, full_history)
        limited = reliability(base, limited_history)
        unreliable = reliability(base, unreliable_history)
        no_reliability = reliability(no_reliability_metadata, [])
        unresolved = reliability({}, [])

        self.assertEqual(
            "Partially Reliable Evolution Chain",
            single["summary"]["reliability_classification"],
        )
        self.assertEqual(1, single["summary"]["reliable_versions"])
        self.assertEqual(0, single["summary"]["unreliable_versions"])
        self.assertEqual(0, single["summary"]["reliable_supersession_links"])
        self.assertEqual(0, single["summary"]["unreliable_supersession_links"])
        self.assertEqual(1, single["summary"]["reliable_timestamps"])
        self.assertEqual(0, single["summary"]["unreliable_timestamps"])
        self.assertEqual(1, single["summary"]["reliable_verification_hashes"])
        self.assertEqual(0, single["summary"]["unreliable_verification_hashes"])
        self.assertEqual(13, single["summary"]["reliable_evolution_outputs"])
        self.assertEqual(0, single["summary"]["unreliable_evolution_outputs"])
        self.assertEqual(0, single["summary"]["missing_evolution_outputs"])
        self.assertEqual(
            "Partially Reliable Version Chain",
            single["reviews"]["version"]["reliability_state"],
        )
        self.assertEqual(
            "Partially Reliable Supersession Chain",
            single["reviews"]["supersession"]["reliability_state"],
        )
        self.assertEqual(
            "Partially Reliable Timestamp Chain",
            single["reviews"]["timestamp"]["reliability_state"],
        )
        self.assertEqual(
            "Partially Reliable Verification Chain",
            single["reviews"]["verification"]["reliability_state"],
        )
        self.assertEqual(
            "Partially Reliable Evolution Outputs",
            single["reviews"]["evolution_output"]["reliability_state"],
        )
        self.assertEqual(
            "Reliable Evolution Chain",
            full["summary"]["reliability_classification"],
        )
        self.assertEqual(
            "Limited Evolution Reliability",
            limited["summary"]["reliability_classification"],
        )
        self.assertEqual(
            "Unreliable Evolution Chain",
            unreliable["summary"]["reliability_classification"],
        )
        self.assertEqual(
            "No Evolution Reliability",
            no_reliability["summary"]["reliability_classification"],
        )
        self.assertEqual(
            "Unresolved Evolution Reliability",
            unresolved["summary"]["reliability_classification"],
        )

        for reliability_set, expected in (
            (full, "Reliable Evolution Chain"),
            (single, "Partially Reliable Evolution Chain"),
            (limited, "Limited Evolution Reliability"),
            (unreliable, "Unreliable Evolution Chain"),
            (no_reliability, "No Evolution Reliability"),
            (unresolved, "Unresolved Evolution Reliability"),
        ):
            rendered = self.admin_session._render_stage18n_evolution_reliability_content(
                reliability_set
            )
            self.assertIn(
                f"<td>Reliability Classification</td><td>{expected}</td>",
                rendered,
            )
            self.assertIn("<h3>Reliability Summary</h3>", rendered)
            self.assertIn("<h3>Version Reliability Review</h3>", rendered)
            self.assertIn("<h3>Supersession Reliability Review</h3>", rendered)
            self.assertIn("<h3>Timestamp Reliability Review</h3>", rendered)
            self.assertIn("<h3>Verification Reliability Review</h3>", rendered)
            self.assertIn("<h3>Evolution Output Reliability Review</h3>", rendered)
            self.assertIn("<h3>Evolution Reliability Review</h3>", rendered)
            self.assertIn("<h3>Record Evolution Reliability</h3>", rendered)
            self.assertIn("Reliable Versions", rendered)
            self.assertIn("Unreliable Versions", rendered)
            self.assertIn("Reliable Supersession Links", rendered)
            self.assertIn("Unreliable Supersession Links", rendered)
            self.assertIn("Reliable Timestamps", rendered)
            self.assertIn("Unreliable Timestamps", rendered)
            self.assertIn("Reliable Verification Hashes", rendered)
            self.assertIn("Unreliable Verification Hashes", rendered)
            self.assertIn("Reliable Evolution Outputs", rendered)
            self.assertIn("Unreliable Evolution Outputs", rendered)
            self.assertIn("Missing Evolution Outputs", rendered)

    def test_stage18o_record_evolution_certification_renders_classification_states(self):
        def version_row(
            version,
            *,
            latest=0,
            hash_value="shared-hash",
            generated_at="default",
            supersedes=None,
        ):
            return {
                "reference": "Strike-LA-20260710-004",
                "version": version,
                "is_latest": latest,
                "supersedes": supersedes
                if supersedes is not None
                else (
                    None
                    if version == 1
                    else f"Strike-LA-20260710-004:v{version - 1}"
                ),
                "generated_at": None
                if generated_at is None
                else (
                    f"2026-06-0{version}T12:00:00Z"
                    if generated_at == "default"
                    else generated_at
                ),
                "verification_hash": hash_value,
                "trajectory": "Stable",
                "system_state": "PERSISTENT_RESISTANCE_WITHOUT_ADAPTATION",
                "finding": "Finding v1",
                "conditions_json": "[\"Escalation Without Response\"]",
                "signals_json": "[\"No Recurring Transition\"]",
                "generated_by": "civic-decision-engine",
            }

        base = {
            "reference": "Strike-LA-20260710-004",
            "version": 2,
            "supersedes": "Strike-LA-20260710-004:v1",
            "generated_at": "2026-06-02T12:00:00Z",
            "exported_at": "2026-06-02T12:05:00Z",
            "is_latest": 1,
            "trajectory": "Stable",
            "system_state": "PERSISTENT_RESISTANCE_WITHOUT_ADAPTATION",
            "finding": "Finding v1",
            "verification_hash": "shared-hash",
        }
        single_metadata = {**base, "version": 1, "supersedes": None}
        single_history = [version_row(1, latest=1)]
        full_history = [version_row(1), version_row(2, latest=1)]
        limited_history = [
            version_row(1, generated_at=None),
            version_row(2, latest=1),
        ]
        non_certifiable_history = [
            version_row(1, generated_at="2026-06-03T12:00:00Z"),
            version_row(2, latest=1, generated_at="2026-06-02T12:00:00Z"),
        ]
        no_certification_metadata = {
            **base,
            "version": 1,
            "supersedes": None,
            "generated_at": None,
            "verification_hash": None,
        }

        def certification(metadata, lineage):
            return self.admin_session._record_stage18o_evolution_certification(
                metadata,
                lineage,
            )

        single = certification(single_metadata, single_history)
        full = certification(base, full_history)
        limited = certification(base, limited_history)
        non_certifiable = certification(base, non_certifiable_history)
        no_certification = certification(no_certification_metadata, [])
        unresolved = certification({}, [])

        self.assertEqual(
            "Partial Evolution Certification",
            single["summary"]["certification_classification"],
        )
        self.assertEqual(1, single["summary"]["certifiable_versions"])
        self.assertEqual(0, single["summary"]["non_certifiable_versions"])
        self.assertEqual(0, single["summary"]["certifiable_supersession_links"])
        self.assertEqual(0, single["summary"]["non_certifiable_supersession_links"])
        self.assertEqual(1, single["summary"]["certifiable_timestamps"])
        self.assertEqual(0, single["summary"]["non_certifiable_timestamps"])
        self.assertEqual(1, single["summary"]["certifiable_verification_hashes"])
        self.assertEqual(0, single["summary"]["non_certifiable_verification_hashes"])
        self.assertEqual(14, single["summary"]["certifiable_evolution_outputs"])
        self.assertEqual(0, single["summary"]["non_certifiable_evolution_outputs"])
        self.assertEqual(0, single["summary"]["missing_evolution_outputs"])
        self.assertEqual(
            "Partially Certifiable Version Chain",
            single["reviews"]["version"]["certification_state"],
        )
        self.assertEqual(
            "Partially Certifiable Supersession Chain",
            single["reviews"]["supersession"]["certification_state"],
        )
        self.assertEqual(
            "Partially Certifiable Timestamp Chain",
            single["reviews"]["timestamp"]["certification_state"],
        )
        self.assertEqual(
            "Partially Certifiable Verification Chain",
            single["reviews"]["verification"]["certification_state"],
        )
        self.assertEqual(
            "Partially Certifiable Evolution Outputs",
            single["reviews"]["evolution_output"]["certification_state"],
        )
        self.assertEqual(
            "Certified Evolution Chain",
            full["summary"]["certification_classification"],
        )
        self.assertEqual(
            "Limited Evolution Certification",
            limited["summary"]["certification_classification"],
        )
        self.assertEqual(
            "Non-Certifiable Evolution Chain",
            non_certifiable["summary"]["certification_classification"],
        )
        self.assertEqual(
            "No Certification Available",
            no_certification["summary"]["certification_classification"],
        )
        self.assertEqual(
            "Unresolved Evolution Certification",
            unresolved["summary"]["certification_classification"],
        )

        for certification_set, expected in (
            (full, "Certified Evolution Chain"),
            (single, "Partial Evolution Certification"),
            (limited, "Limited Evolution Certification"),
            (non_certifiable, "Non-Certifiable Evolution Chain"),
            (no_certification, "No Certification Available"),
            (unresolved, "Unresolved Evolution Certification"),
        ):
            rendered = self.admin_session._render_stage18o_evolution_certification_content(
                certification_set
            )
            self.assertIn(
                f"<td>Certification Classification</td><td>{expected}</td>",
                rendered,
            )
            self.assertIn("<h3>Certification Summary</h3>", rendered)
            self.assertIn("<h3>Version Certification Review</h3>", rendered)
            self.assertIn("<h3>Supersession Certification Review</h3>", rendered)
            self.assertIn("<h3>Timestamp Certification Review</h3>", rendered)
            self.assertIn("<h3>Verification Certification Review</h3>", rendered)
            self.assertIn("<h3>Evolution Output Certification Review</h3>", rendered)
            self.assertIn("<h3>Evolution Certification Review</h3>", rendered)
            self.assertIn("<h3>Record Evolution Certification</h3>", rendered)
            self.assertIn("Certifiable Versions", rendered)
            self.assertIn("Non-Certifiable Versions", rendered)
            self.assertIn("Certifiable Supersession Links", rendered)
            self.assertIn("Non-Certifiable Supersession Links", rendered)
            self.assertIn("Certifiable Timestamps", rendered)
            self.assertIn("Non-Certifiable Timestamps", rendered)
            self.assertIn("Certifiable Verification Hashes", rendered)
            self.assertIn("Non-Certifiable Verification Hashes", rendered)
            self.assertIn("Certifiable Evolution Outputs", rendered)
            self.assertIn("Non-Certifiable Evolution Outputs", rendered)
            self.assertIn("Missing Evolution Outputs", rendered)

    def test_stage18p_record_evolution_accreditation_renders_classification_states(self):
        def version_row(
            version,
            *,
            latest=0,
            hash_value="shared-hash",
            generated_at="default",
            supersedes=None,
        ):
            return {
                "reference": "Strike-LA-20260710-004",
                "version": version,
                "is_latest": latest,
                "supersedes": supersedes
                if supersedes is not None
                else (
                    None
                    if version == 1
                    else f"Strike-LA-20260710-004:v{version - 1}"
                ),
                "generated_at": None
                if generated_at is None
                else (
                    f"2026-06-0{version}T12:00:00Z"
                    if generated_at == "default"
                    else generated_at
                ),
                "verification_hash": hash_value,
                "trajectory": "Stable",
                "system_state": "PERSISTENT_RESISTANCE_WITHOUT_ADAPTATION",
                "finding": "Finding v1",
                "conditions_json": "[\"Escalation Without Response\"]",
                "signals_json": "[\"No Recurring Transition\"]",
                "generated_by": "civic-decision-engine",
            }

        base = {
            "reference": "Strike-LA-20260710-004",
            "version": 2,
            "supersedes": "Strike-LA-20260710-004:v1",
            "generated_at": "2026-06-02T12:00:00Z",
            "exported_at": "2026-06-02T12:05:00Z",
            "is_latest": 1,
            "trajectory": "Stable",
            "system_state": "PERSISTENT_RESISTANCE_WITHOUT_ADAPTATION",
            "finding": "Finding v1",
            "verification_hash": "shared-hash",
        }
        single_metadata = {**base, "version": 1, "supersedes": None}
        single_history = [version_row(1, latest=1)]
        full_history = [version_row(1), version_row(2, latest=1)]
        limited_history = [
            version_row(1, generated_at=None),
            version_row(2, latest=1),
        ]
        not_accredited_history = [
            version_row(1, generated_at="2026-06-03T12:00:00Z"),
            version_row(2, latest=1, generated_at="2026-06-02T12:00:00Z"),
        ]
        no_accreditation_metadata = {
            **base,
            "version": 1,
            "supersedes": None,
            "generated_at": None,
            "verification_hash": None,
        }

        def accreditation(metadata, lineage):
            return self.admin_session._record_stage18p_evolution_accreditation(
                metadata,
                lineage,
            )

        single = accreditation(single_metadata, single_history)
        full = accreditation(base, full_history)
        limited = accreditation(base, limited_history)
        not_accredited = accreditation(base, not_accredited_history)
        no_accreditation = accreditation(no_accreditation_metadata, [])
        unresolved = accreditation({}, [])

        self.assertEqual(
            "Partially Accredited Evolution Chain",
            single["summary"]["accreditation_classification"],
        )
        self.assertEqual(1, single["summary"]["accreditable_versions"])
        self.assertEqual(0, single["summary"]["non_accreditable_versions"])
        self.assertEqual(0, single["summary"]["accreditable_supersession_links"])
        self.assertEqual(0, single["summary"]["non_accreditable_supersession_links"])
        self.assertEqual(1, single["summary"]["accreditable_timestamps"])
        self.assertEqual(0, single["summary"]["non_accreditable_timestamps"])
        self.assertEqual(1, single["summary"]["accreditable_verification_hashes"])
        self.assertEqual(0, single["summary"]["non_accreditable_verification_hashes"])
        self.assertEqual(15, single["summary"]["accreditable_evolution_outputs"])
        self.assertEqual(0, single["summary"]["non_accreditable_evolution_outputs"])
        self.assertEqual(0, single["summary"]["missing_evolution_outputs"])
        self.assertEqual(
            "Partially Accredited Version Chain",
            single["reviews"]["version"]["accreditation_state"],
        )
        self.assertEqual(
            "Partially Accredited Supersession Chain",
            single["reviews"]["supersession"]["accreditation_state"],
        )
        self.assertEqual(
            "Partially Accredited Timestamp Chain",
            single["reviews"]["timestamp"]["accreditation_state"],
        )
        self.assertEqual(
            "Partially Accredited Verification Chain",
            single["reviews"]["verification"]["accreditation_state"],
        )
        self.assertEqual(
            "Partially Accredited Evolution Outputs",
            single["reviews"]["evolution_output"]["accreditation_state"],
        )
        self.assertEqual(
            "Fully Accredited Evolution Chain",
            full["summary"]["accreditation_classification"],
        )
        self.assertEqual(
            "Limited Evolution Accreditation",
            limited["summary"]["accreditation_classification"],
        )
        self.assertEqual(
            "Not Accredited Evolution Chain",
            not_accredited["summary"]["accreditation_classification"],
        )
        self.assertEqual(
            "No Evolution Accreditation",
            no_accreditation["summary"]["accreditation_classification"],
        )
        self.assertEqual(
            "Unresolved Evolution Accreditation",
            unresolved["summary"]["accreditation_classification"],
        )

        for accreditation_set, expected in (
            (full, "Fully Accredited Evolution Chain"),
            (single, "Partially Accredited Evolution Chain"),
            (limited, "Limited Evolution Accreditation"),
            (not_accredited, "Not Accredited Evolution Chain"),
            (no_accreditation, "No Evolution Accreditation"),
            (unresolved, "Unresolved Evolution Accreditation"),
        ):
            rendered = self.admin_session._render_stage18p_evolution_accreditation_content(
                accreditation_set
            )
            self.assertIn(
                f"<td>Accreditation Classification</td><td>{expected}</td>",
                rendered,
            )
            self.assertIn("<h3>Accreditation Summary</h3>", rendered)
            self.assertIn("<h3>Version Accreditation Review</h3>", rendered)
            self.assertIn("<h3>Supersession Accreditation Review</h3>", rendered)
            self.assertIn("<h3>Timestamp Accreditation Review</h3>", rendered)
            self.assertIn("<h3>Verification Accreditation Review</h3>", rendered)
            self.assertIn("<h3>Evolution Output Accreditation Review</h3>", rendered)
            self.assertIn("<h3>Evolution Accreditation Review</h3>", rendered)
            self.assertIn("<h3>Record Evolution Accreditation</h3>", rendered)
            self.assertIn("Accreditable Versions", rendered)
            self.assertIn("Non-Accreditable Versions", rendered)
            self.assertIn("Accreditable Supersession Links", rendered)
            self.assertIn("Non-Accreditable Supersession Links", rendered)
            self.assertIn("Accreditable Timestamps", rendered)
            self.assertIn("Non-Accreditable Timestamps", rendered)
            self.assertIn("Accreditable Verification Hashes", rendered)
            self.assertIn("Non-Accreditable Verification Hashes", rendered)
            self.assertIn("Accreditable Evolution Outputs", rendered)
            self.assertIn("Non-Accreditable Evolution Outputs", rendered)
            self.assertIn("Missing Evolution Outputs", rendered)

    def test_stage18q_record_evolution_auditability_renders_classification_states(self):
        def version_row(
            version,
            *,
            latest=0,
            hash_value="shared-hash",
            generated_at="default",
            supersedes=None,
        ):
            return {
                "reference": "Strike-LA-20260710-004",
                "version": version,
                "is_latest": latest,
                "supersedes": supersedes
                if supersedes is not None
                else (
                    None
                    if version == 1
                    else f"Strike-LA-20260710-004:v{version - 1}"
                ),
                "generated_at": None
                if generated_at is None
                else (
                    f"2026-06-0{version}T12:00:00Z"
                    if generated_at == "default"
                    else generated_at
                ),
                "verification_hash": hash_value,
                "trajectory": "Stable",
                "system_state": "PERSISTENT_RESISTANCE_WITHOUT_ADAPTATION",
                "finding": "Finding v1",
                "conditions_json": "[\"Escalation Without Response\"]",
                "signals_json": "[\"No Recurring Transition\"]",
                "generated_by": "civic-decision-engine",
            }

        base = {
            "reference": "Strike-LA-20260710-004",
            "version": 2,
            "supersedes": "Strike-LA-20260710-004:v1",
            "generated_at": "2026-06-02T12:00:00Z",
            "exported_at": "2026-06-02T12:05:00Z",
            "is_latest": 1,
            "trajectory": "Stable",
            "system_state": "PERSISTENT_RESISTANCE_WITHOUT_ADAPTATION",
            "finding": "Finding v1",
            "verification_hash": "shared-hash",
        }
        single_metadata = {**base, "version": 1, "supersedes": None}
        single_history = [version_row(1, latest=1)]
        full_history = [version_row(1), version_row(2, latest=1)]
        limited_history = [
            version_row(1, generated_at=None),
            version_row(2, latest=1),
        ]
        not_auditable_history = [
            version_row(1, generated_at="2026-06-03T12:00:00Z"),
            version_row(2, latest=1, generated_at="2026-06-02T12:00:00Z"),
        ]
        no_auditability_metadata = {
            **base,
            "version": 1,
            "supersedes": None,
            "generated_at": None,
            "verification_hash": None,
        }

        def auditability(metadata, lineage):
            return self.admin_session._record_stage18q_evolution_auditability(
                metadata,
                lineage,
            )

        single = auditability(single_metadata, single_history)
        full = auditability(base, full_history)
        limited = auditability(base, limited_history)
        not_auditable = auditability(base, not_auditable_history)
        no_auditability = auditability(no_auditability_metadata, [])
        unresolved = auditability({}, [])

        self.assertEqual(
            "Partially Auditable Evolution Chain",
            single["summary"]["auditability_classification"],
        )
        self.assertEqual(1, single["summary"]["auditable_versions"])
        self.assertEqual(0, single["summary"]["non_auditable_versions"])
        self.assertEqual(0, single["summary"]["auditable_supersession_links"])
        self.assertEqual(0, single["summary"]["non_auditable_supersession_links"])
        self.assertEqual(1, single["summary"]["auditable_timestamps"])
        self.assertEqual(0, single["summary"]["non_auditable_timestamps"])
        self.assertEqual(1, single["summary"]["auditable_verification_hashes"])
        self.assertEqual(0, single["summary"]["non_auditable_verification_hashes"])
        self.assertEqual(16, single["summary"]["auditable_evolution_outputs"])
        self.assertEqual(0, single["summary"]["non_auditable_evolution_outputs"])
        self.assertEqual(0, single["summary"]["missing_evolution_outputs"])
        self.assertEqual(
            "Partially Auditable Version Chain",
            single["reviews"]["version"]["auditability_state"],
        )
        self.assertEqual(
            "Partially Auditable Supersession Chain",
            single["reviews"]["supersession"]["auditability_state"],
        )
        self.assertEqual(
            "Partially Auditable Timestamp Chain",
            single["reviews"]["timestamp"]["auditability_state"],
        )
        self.assertEqual(
            "Partially Auditable Verification Chain",
            single["reviews"]["verification"]["auditability_state"],
        )
        self.assertEqual(
            "Partially Auditable Evolution Outputs",
            single["reviews"]["evolution_output"]["auditability_state"],
        )
        self.assertEqual(
            "Fully Auditable Evolution Chain",
            full["summary"]["auditability_classification"],
        )
        self.assertEqual(
            "Limited Evolution Auditability",
            limited["summary"]["auditability_classification"],
        )
        self.assertEqual(
            "Not Auditable Evolution Chain",
            not_auditable["summary"]["auditability_classification"],
        )
        self.assertEqual(
            "No Evolution Auditability",
            no_auditability["summary"]["auditability_classification"],
        )
        self.assertEqual(
            "Unresolved Evolution Auditability",
            unresolved["summary"]["auditability_classification"],
        )

        for auditability_set, expected in (
            (full, "Fully Auditable Evolution Chain"),
            (single, "Partially Auditable Evolution Chain"),
            (limited, "Limited Evolution Auditability"),
            (not_auditable, "Not Auditable Evolution Chain"),
            (no_auditability, "No Evolution Auditability"),
            (unresolved, "Unresolved Evolution Auditability"),
        ):
            rendered = self.admin_session._render_stage18q_evolution_auditability_content(
                auditability_set
            )
            self.assertIn(
                f"<td>Auditability Classification</td><td>{expected}</td>",
                rendered,
            )
            self.assertIn("<h3>Auditability Summary</h3>", rendered)
            self.assertIn("<h3>Version Auditability Review</h3>", rendered)
            self.assertIn("<h3>Supersession Auditability Review</h3>", rendered)
            self.assertIn("<h3>Timestamp Auditability Review</h3>", rendered)
            self.assertIn("<h3>Verification Auditability Review</h3>", rendered)
            self.assertIn("<h3>Evolution Output Auditability Review</h3>", rendered)
            self.assertIn("<h3>Evolution Auditability Review</h3>", rendered)
            self.assertIn("<h3>Record Evolution Auditability</h3>", rendered)
            self.assertIn("Auditable Versions", rendered)
            self.assertIn("Non-Auditable Versions", rendered)
            self.assertIn("Auditable Supersession Links", rendered)
            self.assertIn("Non-Auditable Supersession Links", rendered)
            self.assertIn("Auditable Timestamps", rendered)
            self.assertIn("Non-Auditable Timestamps", rendered)
            self.assertIn("Auditable Verification Hashes", rendered)
            self.assertIn("Non-Auditable Verification Hashes", rendered)
            self.assertIn("Auditable Evolution Outputs", rendered)
            self.assertIn("Non-Auditable Evolution Outputs", rendered)
            self.assertIn("Missing Evolution Outputs", rendered)

    def test_stage18r_record_evolution_reproducibility_renders_classification_states(self):
        def version_row(
            version,
            *,
            latest=0,
            hash_value="shared-hash",
            generated_at="default",
            supersedes=None,
        ):
            return {
                "reference": "Strike-LA-20260710-004",
                "version": version,
                "is_latest": latest,
                "supersedes": supersedes
                if supersedes is not None
                else (
                    None
                    if version == 1
                    else f"Strike-LA-20260710-004:v{version - 1}"
                ),
                "generated_at": None
                if generated_at is None
                else (
                    f"2026-06-0{version}T12:00:00Z"
                    if generated_at == "default"
                    else generated_at
                ),
                "verification_hash": hash_value,
                "trajectory": "Stable",
                "system_state": "PERSISTENT_RESISTANCE_WITHOUT_ADAPTATION",
                "finding": "Finding v1",
                "conditions_json": "[\"Escalation Without Response\"]",
                "signals_json": "[\"No Recurring Transition\"]",
                "generated_by": "civic-decision-engine",
            }

        base = {
            "reference": "Strike-LA-20260710-004",
            "version": 2,
            "supersedes": "Strike-LA-20260710-004:v1",
            "generated_at": "2026-06-02T12:00:00Z",
            "exported_at": "2026-06-02T12:05:00Z",
            "is_latest": 1,
            "trajectory": "Stable",
            "system_state": "PERSISTENT_RESISTANCE_WITHOUT_ADAPTATION",
            "finding": "Finding v1",
            "verification_hash": "shared-hash",
        }
        single_metadata = {**base, "version": 1, "supersedes": None}
        single_history = [version_row(1, latest=1)]
        full_history = [version_row(1), version_row(2, latest=1)]
        limited_history = [
            version_row(1, generated_at=None),
            version_row(2, latest=1),
        ]
        non_reproducible_history = [
            version_row(1, generated_at="2026-06-03T12:00:00Z"),
            version_row(2, latest=1, generated_at="2026-06-02T12:00:00Z"),
        ]

        def reproducibility(metadata, lineage):
            return self.admin_session._record_stage18r_evolution_reproducibility(
                metadata,
                lineage,
            )

        single = reproducibility(single_metadata, single_history)
        full = reproducibility(base, full_history)
        limited = reproducibility(base, limited_history)
        non_reproducible = reproducibility(base, non_reproducible_history)
        unresolved = reproducibility({}, [])

        self.assertEqual(
            "Partially Reproducible Evolution Chain",
            single["summary"]["reproducibility_classification"],
        )
        self.assertEqual(1, single["summary"]["reproducible_versions"])
        self.assertEqual(0, single["summary"]["non_reproducible_versions"])
        self.assertEqual(0, single["summary"]["reproducible_supersession_links"])
        self.assertEqual(0, single["summary"]["non_reproducible_supersession_links"])
        self.assertEqual(1, single["summary"]["reproducible_timestamps"])
        self.assertEqual(0, single["summary"]["non_reproducible_timestamps"])
        self.assertEqual(1, single["summary"]["reproducible_verification_hashes"])
        self.assertEqual(0, single["summary"]["non_reproducible_verification_hashes"])
        self.assertEqual(17, single["summary"]["reproducible_evolution_outputs"])
        self.assertEqual(0, single["summary"]["non_reproducible_evolution_outputs"])
        self.assertEqual(0, single["summary"]["missing_evolution_outputs"])
        self.assertEqual(
            "Partially Reproducible Version Chain",
            single["reviews"]["version"]["reproducibility_state"],
        )
        self.assertEqual(
            "Partially Reproducible Supersession Chain",
            single["reviews"]["supersession"]["reproducibility_state"],
        )
        self.assertEqual(
            "Partially Reproducible Timestamp Chain",
            single["reviews"]["timestamp"]["reproducibility_state"],
        )
        self.assertEqual(
            "Partially Reproducible Verification Chain",
            single["reviews"]["verification"]["reproducibility_state"],
        )
        self.assertEqual(
            "Partially Reproducible Evolution Outputs",
            single["reviews"]["evolution_output"]["reproducibility_state"],
        )
        self.assertEqual(
            "Reproducible Evolution Chain",
            full["summary"]["reproducibility_classification"],
        )
        self.assertEqual(
            "Partially Reproducible Evolution Chain",
            limited["summary"]["reproducibility_classification"],
        )
        self.assertEqual(
            "Non-Reproducible Evolution Chain",
            non_reproducible["summary"]["reproducibility_classification"],
        )
        self.assertEqual(
            "Non-Reproducible Evolution Chain",
            unresolved["summary"]["reproducibility_classification"],
        )
        self.assertEqual(single, reproducibility(single_metadata, single_history))

        for reproducibility_set, expected in (
            (full, "Reproducible Evolution Chain"),
            (single, "Partially Reproducible Evolution Chain"),
            (limited, "Partially Reproducible Evolution Chain"),
            (non_reproducible, "Non-Reproducible Evolution Chain"),
            (unresolved, "Non-Reproducible Evolution Chain"),
        ):
            rendered = self.admin_session._render_stage18r_evolution_reproducibility_content(
                reproducibility_set
            )
            self.assertIn(
                f"<td>Reproducibility Classification</td><td>{expected}</td>",
                rendered,
            )
            self.assertIn("<h3>Reproducibility Summary</h3>", rendered)
            self.assertIn("<h3>Version Reproducibility Review</h3>", rendered)
            self.assertIn("<h3>Supersession Reproducibility Review</h3>", rendered)
            self.assertIn("<h3>Timestamp Reproducibility Review</h3>", rendered)
            self.assertIn("<h3>Verification Reproducibility Review</h3>", rendered)
            self.assertIn(
                "<h3>Evolution Output Reproducibility Review</h3>",
                rendered,
            )
            self.assertIn("<h3>Evolution Reproducibility Review</h3>", rendered)
            self.assertIn("<h3>Record Evolution Reproducibility</h3>", rendered)
            self.assertIn("Reproducible Versions", rendered)
            self.assertIn("Non-Reproducible Versions", rendered)
            self.assertIn("Reproducible Supersession Links", rendered)
            self.assertIn("Non-Reproducible Supersession Links", rendered)
            self.assertIn("Reproducible Timestamps", rendered)
            self.assertIn("Non-Reproducible Timestamps", rendered)
            self.assertIn("Reproducible Verification Hashes", rendered)
            self.assertIn("Non-Reproducible Verification Hashes", rendered)
            self.assertIn("Reproducible Evolution Outputs", rendered)
            self.assertIn("Non-Reproducible Evolution Outputs", rendered)
            self.assertIn("Missing Evolution Outputs", rendered)

    def test_stage18s_record_evolution_transparency_renders_classification_states(self):
        def version_row(
            version,
            *,
            latest=0,
            hash_value="shared-hash",
            generated_at="default",
            supersedes=None,
        ):
            return {
                "reference": "Strike-LA-20260710-004",
                "version": version,
                "is_latest": latest,
                "supersedes": supersedes
                if supersedes is not None
                else (
                    None
                    if version == 1
                    else f"Strike-LA-20260710-004:v{version - 1}"
                ),
                "generated_at": None
                if generated_at is None
                else (
                    f"2026-06-0{version}T12:00:00Z"
                    if generated_at == "default"
                    else generated_at
                ),
                "verification_hash": hash_value,
                "trajectory": "Stable",
                "system_state": "PERSISTENT_RESISTANCE_WITHOUT_ADAPTATION",
                "finding": "Finding v1",
                "conditions_json": "[\"Escalation Without Response\"]",
                "signals_json": "[\"No Recurring Transition\"]",
                "generated_by": "civic-decision-engine",
            }

        base = {
            "reference": "Strike-LA-20260710-004",
            "version": 2,
            "supersedes": "Strike-LA-20260710-004:v1",
            "generated_at": "2026-06-02T12:00:00Z",
            "exported_at": "2026-06-02T12:05:00Z",
            "is_latest": 1,
            "trajectory": "Stable",
            "system_state": "PERSISTENT_RESISTANCE_WITHOUT_ADAPTATION",
            "finding": "Finding v1",
            "verification_hash": "shared-hash",
        }
        single_metadata = {**base, "version": 1, "supersedes": None}
        single_history = [version_row(1, latest=1)]
        full_history = [version_row(1), version_row(2, latest=1)]
        limited_history = [
            version_row(1, generated_at=None),
            version_row(2, latest=1),
        ]
        non_transparent_history = [
            version_row(1, generated_at="2026-06-03T12:00:00Z"),
            version_row(2, latest=1, generated_at="2026-06-02T12:00:00Z"),
        ]

        def transparency(metadata, lineage):
            return self.admin_session._record_stage18s_evolution_transparency(
                metadata,
                lineage,
            )

        single = transparency(single_metadata, single_history)
        full = transparency(base, full_history)
        limited = transparency(base, limited_history)
        non_transparent = transparency(base, non_transparent_history)
        unresolved = transparency({}, [])

        self.assertEqual(
            "Partially Transparent Evolution Chain",
            single["summary"]["transparency_classification"],
        )
        self.assertEqual(1, single["summary"]["transparent_versions"])
        self.assertEqual(0, single["summary"]["non_transparent_versions"])
        self.assertEqual(0, single["summary"]["transparent_supersession_links"])
        self.assertEqual(0, single["summary"]["non_transparent_supersession_links"])
        self.assertEqual(1, single["summary"]["transparent_timestamps"])
        self.assertEqual(0, single["summary"]["non_transparent_timestamps"])
        self.assertEqual(1, single["summary"]["transparent_verification_hashes"])
        self.assertEqual(0, single["summary"]["non_transparent_verification_hashes"])
        self.assertEqual(18, single["summary"]["transparent_evolution_outputs"])
        self.assertEqual(0, single["summary"]["non_transparent_evolution_outputs"])
        self.assertEqual(0, single["summary"]["missing_evolution_outputs"])
        self.assertEqual(
            "Partially Transparent Version Chain",
            single["reviews"]["version"]["transparency_state"],
        )
        self.assertEqual(
            "Partially Transparent Supersession Chain",
            single["reviews"]["supersession"]["transparency_state"],
        )
        self.assertEqual(
            "Partially Transparent Timestamp Chain",
            single["reviews"]["timestamp"]["transparency_state"],
        )
        self.assertEqual(
            "Partially Transparent Verification Chain",
            single["reviews"]["verification"]["transparency_state"],
        )
        self.assertEqual(
            "Partially Transparent Evolution Outputs",
            single["reviews"]["evolution_output"]["transparency_state"],
        )
        self.assertEqual(
            "Transparent Evolution Chain",
            full["summary"]["transparency_classification"],
        )
        self.assertEqual(
            "Partially Transparent Evolution Chain",
            limited["summary"]["transparency_classification"],
        )
        self.assertEqual(
            "Non-Transparent Evolution Chain",
            non_transparent["summary"]["transparency_classification"],
        )
        self.assertEqual(
            "Non-Transparent Evolution Chain",
            unresolved["summary"]["transparency_classification"],
        )
        self.assertEqual(single, transparency(single_metadata, single_history))

        for transparency_set, expected in (
            (full, "Transparent Evolution Chain"),
            (single, "Partially Transparent Evolution Chain"),
            (limited, "Partially Transparent Evolution Chain"),
            (non_transparent, "Non-Transparent Evolution Chain"),
            (unresolved, "Non-Transparent Evolution Chain"),
        ):
            rendered = self.admin_session._render_stage18s_evolution_transparency_content(
                transparency_set
            )
            self.assertIn(
                f"<td>Transparency Classification</td><td>{expected}</td>",
                rendered,
            )
            self.assertIn("<h3>Transparency Summary</h3>", rendered)
            self.assertIn("<h3>Version Transparency Review</h3>", rendered)
            self.assertIn("<h3>Supersession Transparency Review</h3>", rendered)
            self.assertIn("<h3>Timestamp Transparency Review</h3>", rendered)
            self.assertIn("<h3>Verification Transparency Review</h3>", rendered)
            self.assertIn("<h3>Evolution Output Transparency Review</h3>", rendered)
            self.assertIn("<h3>Evolution Transparency Review</h3>", rendered)
            self.assertIn("<h3>Record Evolution Transparency</h3>", rendered)
            self.assertIn("Transparent Versions", rendered)
            self.assertIn("Non-Transparent Versions", rendered)
            self.assertIn("Transparent Supersession Links", rendered)
            self.assertIn("Non-Transparent Supersession Links", rendered)
            self.assertIn("Transparent Timestamps", rendered)
            self.assertIn("Non-Transparent Timestamps", rendered)
            self.assertIn("Transparent Verification Hashes", rendered)
            self.assertIn("Non-Transparent Verification Hashes", rendered)
            self.assertIn("Transparent Evolution Outputs", rendered)
            self.assertIn("Non-Transparent Evolution Outputs", rendered)
            self.assertIn("Missing Evolution Outputs", rendered)

    def test_stage18t_record_evolution_accountability_renders_classification_states(self):
        def version_row(
            version,
            *,
            latest=0,
            hash_value="shared-hash",
            generated_at="default",
            generated_by="civic-decision-engine",
            supersedes=None,
        ):
            return {
                "reference": "Strike-LA-20260710-004",
                "version": version,
                "is_latest": latest,
                "supersedes": supersedes
                if supersedes is not None
                else (
                    None
                    if version == 1
                    else f"Strike-LA-20260710-004:v{version - 1}"
                ),
                "generated_at": None
                if generated_at is None
                else (
                    f"2026-06-0{version}T12:00:00Z"
                    if generated_at == "default"
                    else generated_at
                ),
                "verification_hash": hash_value,
                "trajectory": "Stable",
                "system_state": "PERSISTENT_RESISTANCE_WITHOUT_ADAPTATION",
                "finding": "Finding v1",
                "conditions_json": "[\"Escalation Without Response\"]",
                "signals_json": "[\"No Recurring Transition\"]",
                "generated_by": generated_by,
            }

        base = {
            "reference": "Strike-LA-20260710-004",
            "version": 2,
            "supersedes": "Strike-LA-20260710-004:v1",
            "generated_at": "2026-06-02T12:00:00Z",
            "exported_at": "2026-06-02T12:05:00Z",
            "is_latest": 1,
            "trajectory": "Stable",
            "system_state": "PERSISTENT_RESISTANCE_WITHOUT_ADAPTATION",
            "finding": "Finding v1",
            "verification_hash": "shared-hash",
            "generated_by": "civic-decision-engine",
        }
        single_metadata = {**base, "version": 1, "supersedes": None}
        single_history = [version_row(1, latest=1)]
        full_history = [version_row(1), version_row(2, latest=1)]
        partial_history = [
            version_row(1, generated_by=None),
            version_row(2, latest=1),
        ]
        non_accountable_history = [
            version_row(1, generated_at="2026-06-03T12:00:00Z"),
            version_row(2, latest=1, generated_at="2026-06-02T12:00:00Z"),
        ]

        def accountability(metadata, lineage):
            return self.admin_session._record_stage18t_evolution_accountability(
                metadata,
                lineage,
            )

        single = accountability(single_metadata, single_history)
        full = accountability(base, full_history)
        partial = accountability(base, partial_history)
        non_accountable = accountability(base, non_accountable_history)
        unresolved = accountability({}, [])

        self.assertEqual(
            "Partially Accountable Evolution Chain",
            single["summary"]["accountability_classification"],
        )
        self.assertEqual(1, single["summary"]["accountable_versions"])
        self.assertEqual(0, single["summary"]["non_accountable_versions"])
        self.assertEqual(0, single["summary"]["accountable_supersession_links"])
        self.assertEqual(0, single["summary"]["non_accountable_supersession_links"])
        self.assertEqual(1, single["summary"]["accountable_timestamps"])
        self.assertEqual(0, single["summary"]["non_accountable_timestamps"])
        self.assertEqual(1, single["summary"]["accountable_verification_hashes"])
        self.assertEqual(0, single["summary"]["non_accountable_verification_hashes"])
        self.assertEqual(1, single["summary"]["accountable_generated_by_values"])
        self.assertEqual(0, single["summary"]["non_accountable_generated_by_values"])
        self.assertEqual(0, single["summary"]["missing_generated_by_values"])
        self.assertEqual(19, single["summary"]["accountable_evolution_outputs"])
        self.assertEqual(0, single["summary"]["non_accountable_evolution_outputs"])
        self.assertEqual(0, single["summary"]["missing_evolution_outputs"])
        self.assertEqual(
            "Partially Accountable Version Chain",
            single["reviews"]["version"]["accountability_state"],
        )
        self.assertEqual(
            "Partially Accountable Supersession Chain",
            single["reviews"]["supersession"]["accountability_state"],
        )
        self.assertEqual(
            "Partially Accountable Timestamp Chain",
            single["reviews"]["timestamp"]["accountability_state"],
        )
        self.assertEqual(
            "Partially Accountable Verification Chain",
            single["reviews"]["verification"]["accountability_state"],
        )
        self.assertEqual(
            "Partially Accountable Generated-By Chain",
            single["reviews"]["generated_by"]["accountability_state"],
        )
        self.assertEqual(
            "Partially Accountable Evolution Outputs",
            single["reviews"]["evolution_output"]["accountability_state"],
        )
        self.assertEqual(
            "Accountable Evolution Chain",
            full["summary"]["accountability_classification"],
        )
        self.assertEqual(
            "Partially Accountable Evolution Chain",
            partial["summary"]["accountability_classification"],
        )
        self.assertEqual(1, partial["summary"]["missing_generated_by_values"])
        self.assertEqual(
            "Limited Generated-By Accountability",
            partial["reviews"]["generated_by"]["accountability_state"],
        )
        self.assertEqual(
            "Non-Accountable Evolution Chain",
            non_accountable["summary"]["accountability_classification"],
        )
        self.assertEqual(
            "Non-Accountable Evolution Chain",
            unresolved["summary"]["accountability_classification"],
        )
        self.assertEqual(single, accountability(single_metadata, single_history))

        for accountability_set, expected in (
            (full, "Accountable Evolution Chain"),
            (single, "Partially Accountable Evolution Chain"),
            (partial, "Partially Accountable Evolution Chain"),
            (non_accountable, "Non-Accountable Evolution Chain"),
            (unresolved, "Non-Accountable Evolution Chain"),
        ):
            rendered = self.admin_session._render_stage18t_evolution_accountability_content(
                accountability_set
            )
            self.assertIn(
                f"<td>Accountability Classification</td><td>{expected}</td>",
                rendered,
            )
            self.assertIn("<h3>Accountability Summary</h3>", rendered)
            self.assertIn("<h3>Version Accountability Review</h3>", rendered)
            self.assertIn("<h3>Supersession Accountability Review</h3>", rendered)
            self.assertIn("<h3>Timestamp Accountability Review</h3>", rendered)
            self.assertIn("<h3>Verification Accountability Review</h3>", rendered)
            self.assertIn("<h3>Generated-By Accountability Review</h3>", rendered)
            self.assertIn("<h3>Evolution Output Accountability Review</h3>", rendered)
            self.assertIn("<h3>Evolution Accountability Review</h3>", rendered)
            self.assertIn("<h3>Record Evolution Accountability</h3>", rendered)
            self.assertIn("Accountable Versions", rendered)
            self.assertIn("Non-Accountable Versions", rendered)
            self.assertIn("Accountable Supersession Links", rendered)
            self.assertIn("Non-Accountable Supersession Links", rendered)
            self.assertIn("Accountable Timestamps", rendered)
            self.assertIn("Non-Accountable Timestamps", rendered)
            self.assertIn("Accountable Verification Hashes", rendered)
            self.assertIn("Non-Accountable Verification Hashes", rendered)
            self.assertIn("Accountable Generated-By Values", rendered)
            self.assertIn("Non-Accountable Generated-By Values", rendered)
            self.assertIn("Missing Generated-By Values", rendered)
            self.assertIn("Accountable Evolution Outputs", rendered)
            self.assertIn("Non-Accountable Evolution Outputs", rendered)
            self.assertIn("Missing Evolution Outputs", rendered)

    def test_stage19a_determination_trace_builds_visible_pathway(self):
        evidence_groups = {
            "condition": [
                {"target_label": "Escalation Without Response", "attachments": []}
            ],
            "signal": [
                {"target_label": "Dominant Resistance", "attachments": []}
            ],
        }
        record_outputs = {
            "reference": "Strike-LA-20260710-004",
            "case_title": "Administrative complaint awaiting response",
            "civic_domain": "local_government",
            "institutions": ["Local Authority"],
            "decision_trigger": "No response beyond deadline",
            "case_lifecycle": {
                "current_stage": "awaiting_response",
                "status": "active",
                "stalled": True,
                "days_open": 90,
            },
            "urgency": "high",
            "trajectory": "Deteriorating",
            "system_state": "TRANSITION_TO_ESCALATION",
            "moment_of_change": {
                "from": "TRANSFER_OF_BURDEN",
                "to": "ESCALATION_WITHOUT_RESPONSE",
            },
            "pattern_interpretation": "Delay has escalated without response.",
            "finding": "Trajectory recorded as Deteriorating",
        }
        trace = self.admin_session.build_determination_trace(
            record_outputs=record_outputs,
            evidence_groups=evidence_groups,
            administrative_outputs={"Administrative Action": "Escalate Review"},
            stage18_outputs={
                "Evolution Classification": "Initial Record State",
            },
        )

        self.assertEqual("Strike-LA-20260710-004", trace["record_reference"])
        self.assertEqual(
            "Administrative complaint awaiting response",
            trace["case_title"],
        )
        self.assertEqual(
            "local_government",
            trace["visible_record"]["civic_domain"],
        )
        self.assertEqual(["Local Authority"], trace["visible_record"]["institutions"])
        self.assertEqual(["Escalation Without Response"], trace["conditions"])
        self.assertEqual("Deteriorating", trace["trajectory"]["trajectory"])
        self.assertEqual(
            "Determination derived from visible record evolution",
            trace["determination"],
        )
        self.assertEqual(
            [1, 2, 3, 4, 5, 6],
            [step["step"] for step in trace["trace_path"]],
        )
        self.assertEqual(
            [
                "Visible Record",
                "Observed Evidence",
                "Applied Rules",
                "Conditions",
                "Trajectory",
                "Determination",
            ],
            [step["label"] for step in trace["trace_path"]],
        )
        self.assertIn("Conditions Layer", trace["applied_rules"])
        self.assertIn("Trajectory Classification", trace["applied_rules"])
        self.assertIn("Administrative Evaluation Layer", trace["applied_rules"])
        self.assertIn("Record Evolution Analysis", trace["applied_rules"])
        self.assertIn(
            "Stage 19A does not determine truth.",
            trace["limitations"],
        )
        self.assertIn(
            "Stage 19A evaluates only visible record-derived analysis pathways.",
            trace["limitations"],
        )
        self.assertEqual(
            trace,
            self.admin_session.build_determination_trace(
                record_outputs=record_outputs,
                evidence_groups=evidence_groups,
                administrative_outputs={"Administrative Action": "Escalate Review"},
                stage18_outputs={
                    "Evolution Classification": "Initial Record State",
                },
            ),
        )

        rendered = self.admin_session._render_determination_trace_content(trace)
        self.assertIn("<h3>Trace Summary</h3>", rendered)
        self.assertIn("<h3>Visible Record</h3>", rendered)
        self.assertIn("<h3>Observed Evidence</h3>", rendered)
        self.assertIn("<h3>Applied Rules</h3>", rendered)
        self.assertIn("<h3>Conditions</h3>", rendered)
        self.assertIn("<h3>Trajectory</h3>", rendered)
        self.assertIn("<h3>Trace Path</h3>", rendered)
        self.assertIn("<h3>Limitations</h3>", rendered)
        self.assertIn("<td>Conditions Count</td><td>1</td>", rendered)
        self.assertIn("<td>Trace Steps Count</td><td>6</td>", rendered)

    def test_stage19a_determination_trace_does_not_infer_missing_values(self):
        trace = self.admin_session.build_determination_trace(
            record_outputs={"reference": "REC-1"},
            evidence_groups={},
            administrative_outputs={},
            stage18_outputs={},
        )

        self.assertEqual("REC-1", trace["record_reference"])
        self.assertNotIn("case_title", trace["visible_record"])
        self.assertNotIn("institutions", trace["visible_record"])
        self.assertEqual([], trace["conditions"])
        self.assertEqual({}, trace["trajectory"])
        self.assertEqual([], trace["applied_rules"])
        self.assertEqual("No determination available", trace["determination"])

        falsey_trace = self.admin_session.build_determination_trace(
            record_outputs={
                "reference": "REC-2",
                "case_lifecycle": {
                    "status": "active",
                    "stalled": False,
                    "days_open": 0,
                },
            },
            administrative_outputs={},
            stage18_outputs={},
        )
        self.assertEqual(0, falsey_trace["visible_record"]["days_open"])
        self.assertIn(
            {"label": "Stalled State", "value": False},
            falsey_trace["observed_evidence"],
        )

    def test_stage19a_determination_trace_derivation_order(self):
        no_outputs = self.admin_session.build_determination_trace(
            administrative_outputs={},
            stage18_outputs={},
        )
        conditions_only = self.admin_session.build_determination_trace(
            evidence_groups={
                "condition": [
                    {"target_label": "Transfer Of Burden", "attachments": []}
                ]
            },
            administrative_outputs={},
            stage18_outputs={},
        )
        conditions_trajectory = self.admin_session.build_determination_trace(
            record_outputs={"trajectory": "Stable"},
            evidence_groups={
                "condition": [
                    {"target_label": "Transfer Of Burden", "attachments": []}
                ]
            },
            administrative_outputs={},
            stage18_outputs={},
        )
        administrative = self.admin_session.build_determination_trace(
            evidence_groups={
                "condition": [
                    {"target_label": "Transfer Of Burden", "attachments": []}
                ]
            },
            administrative_outputs={"Workflow State": "Review Active"},
            stage18_outputs={},
        )
        evolution = self.admin_session.build_determination_trace(
            evidence_groups={
                "condition": [
                    {"target_label": "Transfer Of Burden", "attachments": []}
                ]
            },
            administrative_outputs={"Workflow State": "Review Active"},
            stage18_outputs={
                "Evolution Classification": "Initial Record State",
            },
        )

        self.assertEqual("No determination available", no_outputs["determination"])
        self.assertEqual(
            "Determination derived from visible record structure",
            conditions_only["determination"],
        )
        self.assertEqual(
            "Determination derived from visible conditions and trajectory",
            conditions_trajectory["determination"],
        )
        self.assertEqual(
            "Determination derived from visible administrative evaluation",
            administrative["determination"],
        )
        self.assertEqual(
            "Determination derived from visible record evolution",
            evolution["determination"],
        )

    def test_stage19b_rule_citation_layer_builds_from_determination_trace(self):
        trace = self.admin_session.build_determination_trace(
            record_outputs={
                "reference": "Strike-LA-20260710-004",
                "case_title": "Administrative complaint awaiting response",
                "decision_trigger": "No response beyond deadline",
                "case_lifecycle": {"status": "active", "days_open": 90},
                "trajectory": "Deteriorating",
                "system_state": "TRANSITION_TO_ESCALATION",
                "signals": ["Dominant Resistance"],
                "pattern_interpretation": "Delay escalated without response.",
            },
            evidence_groups={
                "condition": [
                    {"target_label": "Escalation Without Response", "attachments": []}
                ]
            },
            administrative_outputs={
                "Administrative Action": "Escalate Review",
            },
            stage18_outputs={
                "Evolution Classification": "Initial Record State",
            },
        )
        citation_layer = self.admin_session.build_rule_citation_layer(
            determination_trace=trace
        )

        summary = citation_layer["citation_summary"]
        self.assertEqual(
            "Strike-LA-20260710-004",
            citation_layer["record_reference"],
        )
        self.assertEqual(
            "Administrative complaint awaiting response",
            citation_layer["case_title"],
        )
        self.assertEqual("Rule Citation Layer Available", summary["citation_state"])
        self.assertEqual(7, summary["rule_families_count"])
        self.assertEqual(1, summary["condition_citations_count"])
        self.assertEqual(1, summary["trajectory_citations_count"])
        self.assertEqual(1, summary["administrative_citations_count"])
        self.assertEqual(1, summary["record_evolution_citations_count"])
        self.assertEqual(11, summary["total_citations_count"])
        self.assertEqual(
            [1, 2, 3, 4, 5, 6, 7],
            [step["step"] for step in citation_layer["citation_path"]],
        )
        self.assertEqual(
            [
                "Visible Determination Trace",
                "Applied Rule Families",
                "Condition Citations",
                "Trajectory Citations",
                "Administrative Citations",
                "Record Evolution Citations",
                "Rule Citation Layer",
            ],
            [step["label"] for step in citation_layer["citation_path"]],
        )
        rule_families = [
            citation["rule_family"] for citation in citation_layer["rule_citations"]
        ]
        self.assertIn("Conditions Layer", rule_families)
        self.assertIn("Trajectory Classification", rule_families)
        self.assertIn("Administrative Evaluation Layer", rule_families)
        self.assertIn("Record Evolution Analysis", rule_families)
        self.assertIn("Determination Trace", rule_families)
        self.assertEqual(
            "Escalation Without Response",
            citation_layer["condition_citations"][0]["condition"],
        )
        self.assertEqual(
            "Definition not available in visible rule set",
            citation_layer["condition_citations"][0]["definition_reference"],
        )
        self.assertEqual(
            "Visible condition output",
            citation_layer["condition_citations"][0]["source_type"],
        )
        self.assertEqual(
            "Deteriorating",
            citation_layer["trajectory_citations"][0]["trajectory"],
        )
        self.assertEqual(
            "Administrative Action",
            citation_layer["administrative_citations"][0]["output_name"],
        )
        self.assertEqual(
            "Evolution Classification",
            citation_layer["record_evolution_citations"][0]["output_name"],
        )
        self.assertIn(
            "Stage 19B does not create new rules.",
            citation_layer["limitations"],
        )
        self.assertIn(
            "Stage 19B cites only visible rule families and existing outputs.",
            citation_layer["limitations"],
        )
        self.assertEqual(
            citation_layer,
            self.admin_session.build_rule_citation_layer(determination_trace=trace),
        )

        rendered = self.admin_session._render_rule_citation_layer_content(
            citation_layer
        )
        self.assertIn("<h3>Citation Summary</h3>", rendered)
        self.assertIn("<h3>Rule Family Citations</h3>", rendered)
        self.assertIn("<h3>Condition Citations</h3>", rendered)
        self.assertIn("<h3>Trajectory Citations</h3>", rendered)
        self.assertIn("<h3>Administrative Citations</h3>", rendered)
        self.assertIn("<h3>Record Evolution Citations</h3>", rendered)
        self.assertIn("<h3>Citation Path</h3>", rendered)
        self.assertIn("<h3>Limitations</h3>", rendered)
        self.assertIn(
            "<td>Citation State</td><td>Rule Citation Layer Available</td>",
            rendered,
        )

    def test_stage19b_rule_citation_layer_handles_absent_and_partial_outputs(self):
        no_citations = self.admin_session.build_rule_citation_layer(
            determination_trace={
                "record_reference": "REC-1",
                "case_title": None,
                "applied_rules": [],
                "conditions": [],
                "trajectory": {},
                "observed_evidence": [],
                "determination": "No determination available",
            }
        )
        partial = self.admin_session.build_rule_citation_layer(
            determination_trace={
                "record_reference": "REC-2",
                "case_title": None,
                "applied_rules": ["Conditions Layer"],
                "conditions": [],
                "trajectory": {},
                "observed_evidence": [],
                "determination": "Determination derived from visible record structure",
            }
        )
        trajectory_only = self.admin_session.build_rule_citation_layer(
            determination_trace={
                "record_reference": "REC-3",
                "case_title": None,
                "applied_rules": ["Trajectory Classification"],
                "conditions": [],
                "trajectory": {"trajectory": "Stable"},
                "observed_evidence": [],
                "determination": "Determination derived from visible conditions and trajectory",
            }
        )

        self.assertEqual(
            "No Rule Citations Available",
            no_citations["citation_summary"]["citation_state"],
        )
        self.assertEqual([], no_citations["rule_citations"])
        self.assertEqual([], no_citations["condition_citations"])
        self.assertEqual([], no_citations["trajectory_citations"])
        self.assertEqual([], no_citations["administrative_citations"])
        self.assertEqual([], no_citations["record_evolution_citations"])
        self.assertEqual(
            "Partial Rule Citation Layer",
            partial["citation_summary"]["citation_state"],
        )
        self.assertEqual(2, partial["citation_summary"]["rule_families_count"])
        self.assertEqual([], partial["condition_citations"])
        self.assertEqual(
            "Rule Citation Layer Available",
            trajectory_only["citation_summary"]["citation_state"],
        )
        self.assertEqual(1, trajectory_only["citation_summary"]["trajectory_citations_count"])

    def test_stage19c_evidence_attribution_matrix_builds_from_trace_and_citations(self):
        trace = self.admin_session.build_determination_trace(
            record_outputs={
                "reference": "Strike-LA-20260710-004",
                "case_title": "Administrative complaint awaiting response",
                "decision_trigger": "No response beyond deadline",
                "case_lifecycle": {"status": "active", "days_open": 90},
                "trajectory": "Deteriorating",
                "system_state": "TRANSITION_TO_ESCALATION",
                "signals": ["Dominant Resistance"],
                "pattern_interpretation": "Delay escalated without response.",
                "finding": "Trajectory recorded as Deteriorating",
            },
            evidence_groups={
                "condition": [
                    {"target_label": "Escalation Without Response", "attachments": []}
                ]
            },
            administrative_outputs={
                "Administrative Action": "Escalate Review",
            },
            stage18_outputs={
                "Evolution Classification": "Initial Record State",
            },
        )
        citation_layer = self.admin_session.build_rule_citation_layer(
            determination_trace=trace
        )
        matrix = self.admin_session.build_evidence_attribution_matrix(
            determination_trace=trace,
            rule_citation_layer=citation_layer,
        )

        summary = matrix["attribution_summary"]
        self.assertEqual(
            "Strike-LA-20260710-004",
            matrix["record_reference"],
        )
        self.assertEqual(
            "Administrative complaint awaiting response",
            matrix["case_title"],
        )
        self.assertEqual(
            "Evidence Attribution Matrix Available",
            summary["attribution_state"],
        )
        self.assertGreater(summary["evidence_sources_count"], 0)
        self.assertEqual(1, summary["condition_attributions_count"])
        self.assertGreater(summary["trajectory_attributions_count"], 0)
        self.assertEqual(1, summary["administrative_attributions_count"])
        self.assertEqual(1, summary["record_evolution_attributions_count"])
        self.assertEqual(6, summary["determination_trace_attributions_count"])
        self.assertEqual(11, summary["rule_citation_attributions_count"])
        self.assertEqual(0, summary["unsupported_outputs_count"])
        self.assertEqual(
            [1, 2, 3, 4, 5, 6, 7, 8, 9],
            [step["step"] for step in matrix["attribution_path"]],
        )
        self.assertEqual(
            [
                "Visible Record Evidence",
                "Evidence Sources",
                "Condition Attribution",
                "Trajectory Attribution",
                "Administrative Attribution",
                "Record Evolution Attribution",
                "Determination Trace Attribution",
                "Rule Citation Attribution",
                "Evidence Attribution Matrix",
            ],
            [step["label"] for step in matrix["attribution_path"]],
        )
        self.assertEqual("EV-001", matrix["evidence_sources"][0]["evidence_id"])
        self.assertEqual(
            "EV-002",
            matrix["evidence_sources"][1]["evidence_id"],
        )
        self.assertEqual(
            "Escalation Without Response",
            matrix["condition_attribution"][0]["output_name"],
        )
        self.assertTrue(
            matrix["condition_attribution"][0]["attributed_evidence_ids"]
        )
        self.assertEqual(
            "Attributed",
            matrix["condition_attribution"][0]["support_state"],
        )
        self.assertTrue(matrix["trajectory_attribution"])
        self.assertTrue(matrix["administrative_attribution"])
        self.assertTrue(matrix["record_evolution_attribution"])
        self.assertTrue(matrix["determination_trace_attribution"])
        self.assertTrue(matrix["rule_citation_attribution"])
        self.assertIn(
            "Stage 19C does not validate evidence.",
            matrix["limitations"],
        )
        self.assertIn(
            "Stage 19C attributes only visible evidence elements to existing outputs.",
            matrix["limitations"],
        )
        self.assertEqual(
            matrix,
            self.admin_session.build_evidence_attribution_matrix(
                determination_trace=trace,
                rule_citation_layer=citation_layer,
            ),
        )

        rendered = self.admin_session._render_evidence_attribution_matrix_content(
            matrix
        )
        self.assertIn("<h3>Attribution Summary</h3>", rendered)
        self.assertIn("<h3>Evidence Sources</h3>", rendered)
        self.assertIn("<h3>Condition Attribution</h3>", rendered)
        self.assertIn("<h3>Trajectory Attribution</h3>", rendered)
        self.assertIn("<h3>Administrative Attribution</h3>", rendered)
        self.assertIn("<h3>Record Evolution Attribution</h3>", rendered)
        self.assertIn("<h3>Determination Trace Attribution</h3>", rendered)
        self.assertIn("<h3>Rule Citation Attribution</h3>", rendered)
        self.assertIn("<h3>Unsupported Outputs</h3>", rendered)
        self.assertIn("<h3>Attribution Path</h3>", rendered)
        self.assertIn("<h3>Limitations</h3>", rendered)
        self.assertIn(
            "<td>Attribution State</td><td>Evidence Attribution Matrix Available</td>",
            rendered,
        )

    def test_stage19c_evidence_attribution_matrix_handles_absent_and_partial_outputs(self):
        no_attribution = self.admin_session.build_evidence_attribution_matrix(
            determination_trace={
                "record_reference": "REC-1",
                "case_title": None,
                "visible_record": {},
                "observed_evidence": [],
                "applied_rules": [],
                "conditions": [],
                "trajectory": {},
                "determination": "No determination available",
                "trace_path": [],
            },
            rule_citation_layer={
                "rule_citations": [],
                "condition_citations": [],
                "trajectory_citations": [],
                "administrative_citations": [],
                "record_evolution_citations": [],
            },
        )
        partial = self.admin_session.build_evidence_attribution_matrix(
            determination_trace={
                "record_reference": "REC-2",
                "case_title": None,
                "visible_record": {},
                "observed_evidence": [],
                "applied_rules": [],
                "conditions": [],
                "trajectory": {},
                "determination": "No determination available",
                "trace_path": [],
            },
            rule_citation_layer={
                "rule_citations": [
                    {
                        "rule_family": "Conditions Layer",
                        "citation_label": "Conditions Layer Specification",
                    }
                ],
                "condition_citations": [],
                "trajectory_citations": [],
                "administrative_citations": [],
                "record_evolution_citations": [],
            },
        )
        trace_without_trajectory = self.admin_session.build_determination_trace(
            record_outputs={"reference": "REC-3"},
            administrative_outputs={},
            stage18_outputs={},
        )
        no_trajectory = self.admin_session.build_evidence_attribution_matrix(
            determination_trace=trace_without_trajectory,
            rule_citation_layer=self.admin_session.build_rule_citation_layer(
                determination_trace=trace_without_trajectory,
            ),
        )

        self.assertEqual(
            "No Evidence Attribution Available",
            no_attribution["attribution_summary"]["attribution_state"],
        )
        self.assertEqual([], no_attribution["evidence_sources"])
        self.assertEqual([], no_attribution["condition_attribution"])
        self.assertEqual([], no_attribution["trajectory_attribution"])
        self.assertEqual([], no_attribution["administrative_attribution"])
        self.assertEqual([], no_attribution["record_evolution_attribution"])
        self.assertEqual([], no_attribution["unsupported_outputs"])
        self.assertEqual(
            "Partial Evidence Attribution Matrix",
            partial["attribution_summary"]["attribution_state"],
        )
        self.assertEqual(1, partial["attribution_summary"]["unsupported_outputs_count"])
        self.assertEqual(
            "Conditions Layer",
            partial["unsupported_outputs"][0]["output_name"],
        )
        self.assertIn(
            "Unsupported does not mean false or invalid.",
            partial["unsupported_outputs"][0]["limitations"],
        )
        self.assertEqual([], no_trajectory["trajectory_attribution"])

    def test_stage19d_determination_report_assembles_existing_outputs(self):
        trace = {
            "visible_record": {
                "record_reference": "Strike-LA-20260710-004",
                "case_title": "Administrative complaint awaiting response",
            },
            "observed_evidence": [
                {
                    "label": "Administrative Outputs",
                    "value": {"Administrative Action": "Escalate Review"},
                },
                {
                    "label": "Record Evolution Outputs",
                    "value": {"Evolution Classification": "Initial Record State"},
                },
            ],
            "conditions": ["Escalation Without Response"],
            "trajectory": {"trajectory": "Deteriorating"},
            "trace_path": [{"step": 1, "label": "Visible Record"}],
        }
        citation_layer = {"rule_citations": [{"rule_family": "Conditions Layer"}]}
        attribution_matrix = {
            "attribution_summary": {
                "attribution_state": "Evidence Attribution Matrix Available"
            }
        }
        original_inputs = json.loads(
            json.dumps([trace, citation_layer, attribution_matrix])
        )

        report = self.admin_session.build_determination_report(
            determination_trace=trace,
            rule_citation_layer=citation_layer,
            evidence_attribution_matrix=attribution_matrix,
        )

        self.assertEqual("Determination Report Available", report["report_state"])
        self.assertEqual(
            [
                "Visible Record",
                "Conditions",
                "Trajectory",
                "Administrative Outputs",
                "Record Evolution",
                "Determination Trace",
                "Rule Citation Layer",
                "Evidence Attribution Matrix",
            ],
            [section["section_name"] for section in report["report_sections"]],
        )
        self.assertEqual(
            [
                "Visible Record",
                "Conditions",
                "Trajectory",
                "Administrative Outputs",
                "Record Evolution",
                "Determination Trace",
                "Rule Citation Layer",
                "Evidence Attribution Matrix",
                "Determination Report",
            ],
            [step["label"] for step in report["report_path"]],
        )
        self.assertEqual(
            list(range(1, 10)),
            [step["step"] for step in report["report_path"]],
        )
        self.assertIn(
            "This report summarises visible record data",
            report["report_summary"],
        )
        self.assertIn(
            "Stage 19D only describes existing outputs.",
            report["limitations"],
        )
        self.assertEqual(
            report,
            self.admin_session.build_determination_report(
                determination_trace=trace,
                rule_citation_layer=citation_layer,
                evidence_attribution_matrix=attribution_matrix,
            ),
        )
        self.assertEqual(
            original_inputs,
            [trace, citation_layer, attribution_matrix],
        )

        rendered = self.admin_session._render_determination_report_content(report)
        self.assertIn("<h3>Report Overview</h3>", rendered)
        self.assertIn("<h3>Report Summary</h3>", rendered)
        self.assertIn("<h3>Report Sections</h3>", rendered)
        self.assertIn("<h3>Report Path</h3>", rendered)
        self.assertIn("<h3>Limitations</h3>", rendered)
        self.assertIn(
            "<td>Report State</td><td>Determination Report Available</td>",
            rendered,
        )

    def test_stage19d_determination_report_handles_unavailable_outputs(self):
        report = self.admin_session.build_determination_report()

        self.assertEqual(
            "Determination Report Unavailable",
            report["report_state"],
        )
        self.assertEqual(
            "No Stage 19 outputs are available for a determination report.",
            report["report_summary"],
        )
        self.assertEqual(8, len(report["report_sections"]))
        self.assertTrue(
            all(
                section["section_summary"].endswith("outputs unavailable.")
                for section in report["report_sections"]
            )
        )
        self.assertEqual(
            "determination report unavailable",
            report["report_path"][-1]["output"],
        )

    def test_stage19e_sufficiency_boundaries_map_stage19c_support_states(self):
        matrix = {
            "condition_attribution": [
                {
                    "output_type": "Condition",
                    "output_name": "Escalation Without Response",
                    "output_value": "Escalation Without Response",
                    "support_state": "Attributed",
                    "attributed_evidence_ids": ["EV-001", "EV-002"],
                }
            ],
            "trajectory_attribution": [
                {
                    "output_type": "Trajectory",
                    "output_name": "Trajectory",
                    "output_value": "Deteriorating",
                    "support_state": "Partially Attributed",
                    "attributed_evidence_ids": ["EV-003"],
                }
            ],
            "administrative_attribution": [
                {
                    "output_type": "Administrative",
                    "output_name": "Administrative Action",
                    "output_value": "Escalate Review",
                    "support_state": "No Visible Evidence Attributed",
                    "attributed_evidence_ids": [],
                }
            ],
            "unsupported_outputs": [
                {
                    "output_type": "Administrative",
                    "output_name": "Administrative Action",
                    "output_value": "Escalate Review",
                }
            ],
        }
        original_matrix = json.loads(json.dumps(matrix))

        boundaries = self.admin_session.build_sufficiency_boundaries(
            evidence_attribution_matrix=matrix,
        )

        self.assertEqual(
            "Sufficiency Boundaries Available",
            boundaries["boundary_state"],
        )
        self.assertEqual(
            {
                "boundary_state": "Sufficiency Boundaries Available",
                "supported_outputs_count": 1,
                "partially_supported_outputs_count": 1,
                "unsupported_outputs_count": 1,
                "total_outputs_evaluated": 3,
                "source_layer": "Stage 19C Evidence Attribution Matrix",
                "limitation_summary": (
                    "Sufficiency boundaries describe visible support inside "
                    "the framework only and do not determine real-world "
                    "sufficiency."
                ),
            },
            boundaries["boundary_summary"],
        )
        supported = boundaries["supported_outputs"][0]
        self.assertEqual("Supported", supported["support_state"])
        self.assertEqual("Attributed", supported["source_support_state"])
        self.assertEqual(["EV-001", "EV-002"], supported["attributed_evidence_ids"])
        self.assertEqual("Visible Support Present", supported["boundary_label"])
        partial = boundaries["partially_supported_outputs"][0]
        self.assertEqual("Partially Supported", partial["support_state"])
        self.assertEqual("Partially Attributed", partial["source_support_state"])
        unsupported = boundaries["unsupported_outputs"][0]
        self.assertEqual(
            "Unsupported Within Visible Attribution",
            unsupported["support_state"],
        )
        self.assertEqual(
            "No Visible Evidence Attributed",
            unsupported["source_support_state"],
        )
        self.assertEqual([], unsupported["attributed_evidence_ids"])
        self.assertEqual(
            [
                "Evidence Attribution Matrix",
                "Attributed Outputs",
                "Partially Attributed Outputs",
                "Unsupported Outputs",
                "Sufficiency Boundary Classification",
            ],
            [step["label"] for step in boundaries["boundary_path"]],
        )
        self.assertEqual(
            list(range(1, 6)),
            [step["step"] for step in boundaries["boundary_path"]],
        )
        self.assertIn(
            "Stage 19E does not determine legal sufficiency.",
            boundaries["limitations"],
        )
        self.assertIn(
            "Stage 19E evaluates only visible support boundaries inside the framework.",
            boundaries["limitations"],
        )
        self.assertEqual(
            boundaries,
            self.admin_session.build_sufficiency_boundaries(
                evidence_attribution_matrix=matrix,
            ),
        )
        self.assertEqual(original_matrix, matrix)

        rendered = self.admin_session._render_sufficiency_boundaries_content(
            boundaries
        )
        self.assertIn("<h3>Boundary Overview</h3>", rendered)
        self.assertIn("<h3>Boundary Summary</h3>", rendered)
        self.assertIn("<h3>Supported Outputs</h3>", rendered)
        self.assertIn("<h3>Partially Supported Outputs</h3>", rendered)
        self.assertIn("<h3>Unsupported Outputs</h3>", rendered)
        self.assertIn("<h3>Boundary Path</h3>", rendered)
        self.assertIn("<h3>Limitations</h3>", rendered)
        self.assertIn(
            "<td>Boundary State</td><td>Sufficiency Boundaries Available</td>",
            rendered,
        )

    def test_stage19e_sufficiency_boundaries_handle_partial_and_unavailable_states(self):
        partial_matrix = {
            "trajectory_attribution": [
                {
                    "output_type": "Trajectory",
                    "output_name": "Trajectory",
                    "output_value": "Initial",
                    "support_state": "Partially Attributed",
                    "attributed_evidence_ids": ["EV-001"],
                }
            ],
            "unsupported_outputs": [
                {
                    "output_type": "Administrative",
                    "output_name": "Administrative Status",
                    "output_value": "Pending",
                }
            ],
        }

        partial = self.admin_session.build_sufficiency_boundaries(
            evidence_attribution_matrix=partial_matrix,
        )
        unavailable = self.admin_session.build_sufficiency_boundaries()

        self.assertEqual(
            "Partial Sufficiency Boundaries",
            partial["boundary_state"],
        )
        self.assertEqual(0, partial["boundary_summary"]["supported_outputs_count"])
        self.assertEqual(
            1,
            partial["boundary_summary"]["partially_supported_outputs_count"],
        )
        self.assertEqual(1, partial["boundary_summary"]["unsupported_outputs_count"])
        self.assertEqual(
            "Sufficiency Boundaries Unavailable",
            unavailable["boundary_state"],
        )
        self.assertEqual(0, unavailable["boundary_summary"]["total_outputs_evaluated"])
        self.assertEqual([], unavailable["supported_outputs"])
        self.assertEqual([], unavailable["partially_supported_outputs"])
        self.assertEqual([], unavailable["unsupported_outputs"])

    def test_stage19f_counterfactual_visibility_maps_visible_and_absent_layers(self):
        trace = {
            "visible_record": {"record_reference": "REC-19F"},
            "observed_evidence": [],
            "conditions": ["Escalation Without Response"],
            "trajectory": {},
        }
        matrix = {
            "evidence_sources": [
                {
                    "evidence_id": "EV-001",
                    "evidence_label": "Record Reference",
                    "evidence_type": "Visible Record",
                },
                {
                    "evidence_id": "EV-002",
                    "evidence_label": "Condition: Escalation Without Response",
                    "evidence_type": "Condition Output",
                },
            ],
            "condition_attribution": [
                {
                    "output_name": "Escalation Without Response",
                    "support_state": "Attributed",
                    "attributed_evidence_ids": ["EV-002"],
                }
            ],
        }
        report = {"report_state": "Determination Report Available"}
        boundaries = {
            "boundary_state": "Sufficiency Boundaries Available",
            "supported_outputs": [
                {"attributed_evidence_ids": ["EV-002"]}
            ],
            "partially_supported_outputs": [],
        }
        original_inputs = json.loads(json.dumps([trace, matrix, report, boundaries]))

        visibility = self.admin_session.build_counterfactual_visibility(
            determination_trace=trace,
            evidence_attribution_matrix=matrix,
            determination_report=report,
            sufficiency_boundaries=boundaries,
        )

        self.assertEqual(
            "Counterfactual Visibility Available",
            visibility["visibility_state"],
        )
        self.assertEqual(6, len(visibility["visible_layers"]))
        self.assertEqual(4, len(visibility["non_visible_layers"]))
        self.assertEqual(
            {
                "Trajectory",
                "Administrative Outputs",
                "Record Evolution",
                "Rule Citation Layer",
            },
            {layer["layer_name"] for layer in visibility["non_visible_layers"]},
        )
        condition_layer = next(
            layer
            for layer in visibility["visible_layers"]
            if layer["layer_name"] == "Conditions"
        )
        visible_record_layer = next(
            layer
            for layer in visibility["visible_layers"]
            if layer["layer_name"] == "Visible Record"
        )
        self.assertEqual(
            "Attributed",
            visible_record_layer["source_support_state"],
        )
        self.assertEqual(
            ["EV-001"],
            visible_record_layer["supporting_evidence_ids"],
        )
        self.assertEqual("Visible", condition_layer["visibility_state"])
        self.assertEqual("Attributed", condition_layer["source_support_state"])
        self.assertEqual(["EV-002"], condition_layer["supporting_evidence_ids"])
        self.assertEqual(
            "Visible Support Present",
            condition_layer["visibility_label"],
        )
        self.assertEqual(2, len(visibility["visible_evidence_elements"]))
        self.assertEqual(7, len(visibility["non_visible_evidence_elements"]))
        self.assertIn(
            "Evidence category: Attachment Metadata",
            {
                item["evidence_identifier"]
                for item in visibility["non_visible_evidence_elements"]
            },
        )
        summary = visibility["visibility_summary"]
        self.assertEqual(6, summary["visible_framework_layers_count"])
        self.assertEqual(4, summary["non_visible_framework_layers_count"])
        self.assertEqual(2, summary["visible_evidence_count"])
        self.assertEqual(7, summary["non_visible_evidence_count"])
        self.assertEqual(
            [
                "Visible Record",
                "Framework Layers Evaluated",
                "Visible Layers",
                "Non-Visible Layers",
                "Evidence Visibility",
                "Counterfactual Visibility Classification",
            ],
            [step["label"] for step in visibility["counterfactual_path"]],
        )
        self.assertEqual(
            list(range(1, 7)),
            [step["step"] for step in visibility["counterfactual_path"]],
        )
        self.assertIn(
            "Stage 19F does not generate hypothetical scenarios.",
            visibility["limitations"],
        )
        self.assertIn(
            "Stage 19F evaluates only visible and non-visible representation inside the framework.",
            visibility["limitations"],
        )
        self.assertEqual(
            visibility,
            self.admin_session.build_counterfactual_visibility(
                determination_trace=trace,
                evidence_attribution_matrix=matrix,
                determination_report=report,
                sufficiency_boundaries=boundaries,
            ),
        )
        self.assertEqual(original_inputs, [trace, matrix, report, boundaries])

        rendered = self.admin_session._render_counterfactual_visibility_content(
            visibility
        )
        self.assertIn("<h3>Boundary Overview</h3>", rendered)
        self.assertIn("<h3>Visibility Summary</h3>", rendered)
        self.assertIn("<h3>Visible Layers</h3>", rendered)
        self.assertIn("<h3>Non-Visible Layers</h3>", rendered)
        self.assertIn("<h3>Visible Evidence Elements</h3>", rendered)
        self.assertIn("<h3>Non-Visible Evidence Elements</h3>", rendered)
        self.assertIn("<h3>Counterfactual Path</h3>", rendered)
        self.assertIn("<h3>Limitations</h3>", rendered)
        self.assertIn(
            "<td>Visibility State</td><td>Counterfactual Visibility Available</td>",
            rendered,
        )

    def test_stage19f_counterfactual_visibility_handles_partial_and_unavailable_states(self):
        partial = self.admin_session.build_counterfactual_visibility(
            determination_trace={
                "visible_record": {"record_reference": "REC-PARTIAL"}
            }
        )
        unavailable = self.admin_session.build_counterfactual_visibility()

        self.assertEqual(
            "Partial Counterfactual Visibility",
            partial["visibility_state"],
        )
        self.assertEqual(2, len(partial["visible_layers"]))
        self.assertEqual(8, len(partial["non_visible_layers"]))
        self.assertEqual(
            "Counterfactual Visibility Unavailable",
            unavailable["visibility_state"],
        )
        self.assertEqual([], unavailable["visible_layers"])
        self.assertEqual(10, len(unavailable["non_visible_layers"]))
        self.assertEqual([], unavailable["visible_evidence_elements"])
        self.assertEqual(9, len(unavailable["non_visible_evidence_elements"]))

    def test_stage19g_explainability_certification_certifies_available_components(self):
        inputs = {
            "determination_trace": {
                "visible_record": {"record_reference": "REC-19G"},
                "trace_path": [{"step": 1, "label": "Visible Record"}],
            },
            "rule_citation_layer": {
                "citation_summary": {
                    "citation_state": "Rule Citation Layer Available"
                }
            },
            "evidence_attribution_matrix": {
                "attribution_summary": {
                    "attribution_state": "Evidence Attribution Matrix Available"
                }
            },
            "determination_report": {
                "report_state": "Determination Report Available"
            },
            "sufficiency_boundaries": {
                "boundary_state": "Sufficiency Boundaries Available"
            },
            "counterfactual_visibility": {
                "visibility_state": "Counterfactual Visibility Available"
            },
        }
        original_inputs = json.loads(json.dumps(inputs))

        certification = self.admin_session.build_explainability_certification(
            **inputs
        )

        self.assertEqual(
            "Explainability Certified",
            certification["certification_state"],
        )
        self.assertEqual(6, len(certification["certified_components"]))
        self.assertEqual([], certification["partially_certified_components"])
        self.assertEqual([], certification["uncertified_components"])
        summary = certification["certification_summary"]
        self.assertEqual(6, summary["required_components_count"])
        self.assertEqual(6, summary["certified_components_count"])
        self.assertEqual(0, summary["partially_certified_components_count"])
        self.assertEqual(0, summary["uncertified_components_count"])
        trace_component = certification["certified_components"][0]
        self.assertEqual("Determination Trace", trace_component["component_name"])
        self.assertEqual("Stage 19A", trace_component["source_stage"])
        self.assertEqual("Available", trace_component["availability_state"])
        self.assertEqual("Certified", trace_component["certification_state"])
        self.assertEqual(
            "Explainability Component Present",
            trace_component["certification_label"],
        )
        self.assertEqual(
            [
                "Determination Trace",
                "Rule Citation Layer",
                "Evidence Attribution Matrix",
                "Determination Report",
                "Sufficiency Boundaries",
                "Counterfactual Visibility",
                "Explainability Certification",
            ],
            [step["label"] for step in certification["certification_path"]],
        )
        self.assertEqual(
            list(range(1, 8)),
            [step["step"] for step in certification["certification_path"]],
        )
        self.assertEqual(
            "explainability certification available",
            certification["certification_path"][-1]["output"],
        )
        self.assertIn(
            "Stage 19G does not certify factual truth.",
            certification["limitations"],
        )
        self.assertIn(
            "Stage 19G certifies only internal framework explainability.",
            certification["limitations"],
        )
        self.assertEqual(
            certification,
            self.admin_session.build_explainability_certification(**inputs),
        )
        self.assertEqual(original_inputs, inputs)

        rendered = self.admin_session._render_explainability_certification_content(
            certification
        )
        self.assertIn("<h3>Certification Overview</h3>", rendered)
        self.assertIn("<h3>Certification Summary</h3>", rendered)
        self.assertIn("<h3>Certified Components</h3>", rendered)
        self.assertIn("<h3>Partially Certified Components</h3>", rendered)
        self.assertIn("<h3>Uncertified Components</h3>", rendered)
        self.assertIn("<h3>Certification Path</h3>", rendered)
        self.assertIn("<h3>Limitations</h3>", rendered)
        self.assertIn(
            "<td>Certification State</td><td>Explainability Certified</td>",
            rendered,
        )

    def test_stage19g_explainability_certification_handles_partial_and_missing_components(self):
        partial = self.admin_session.build_explainability_certification(
            determination_trace={"trace_path": [{"step": 1}]},
            rule_citation_layer={
                "citation_summary": {
                    "citation_state": "Partial Rule Citation Layer"
                }
            },
            evidence_attribution_matrix={
                "attribution_summary": {
                    "attribution_state": "No Evidence Attribution Available"
                }
            },
            determination_report={
                "report_state": "Determination Report Unavailable"
            },
            sufficiency_boundaries={
                "boundary_state": "Partial Sufficiency Boundaries"
            },
            counterfactual_visibility={
                "visibility_state": "Partial Counterfactual Visibility"
            },
        )
        uncertified = self.admin_session.build_explainability_certification()

        self.assertEqual(
            "Explainability Partially Certified",
            partial["certification_state"],
        )
        self.assertEqual([], partial["certified_components"])
        self.assertEqual(4, len(partial["partially_certified_components"]))
        self.assertEqual(2, len(partial["uncertified_components"]))
        partial_component = partial["partially_certified_components"][0]
        self.assertEqual("Partially Available", partial_component["availability_state"])
        self.assertEqual(
            "Partially Certified",
            partial_component["certification_state"],
        )
        self.assertEqual(
            "Explainability Component Partially Present",
            partial_component["certification_label"],
        )
        missing_component = partial["uncertified_components"][0]
        self.assertEqual("Unavailable", missing_component["availability_state"])
        self.assertEqual("Not Certified", missing_component["certification_state"])
        self.assertEqual(
            "Explainability Component Not Present",
            missing_component["certification_label"],
        )
        self.assertEqual(
            "Explainability Not Certified",
            uncertified["certification_state"],
        )
        self.assertEqual([], uncertified["certified_components"])
        self.assertEqual([], uncertified["partially_certified_components"])
        self.assertEqual(6, len(uncertified["uncertified_components"]))
        self.assertEqual(
            "explainability certification unavailable",
            uncertified["certification_path"][-1]["output"],
        )

    def test_stage20_framework_self_description_is_deterministic_and_complete(self):
        self_description = self.admin_session.build_framework_self_description()

        identity = self_description["framework_identity"]
        self.assertEqual(
            "Civic Record Evaluation Framework",
            identity["framework_name"],
        )
        self.assertEqual("CREF", identity["framework_acronym"])
        self.assertEqual("CREF Stage 20", identity["framework_version"])
        self.assertEqual(
            "Deterministic Record Evaluation Framework",
            identity["framework_type"],
        )
        self.assertEqual(
            "Structured Evaluation of Visible Record Data",
            identity["framework_purpose_label"],
        )
        purpose = self_description["purpose_description"]
        self.assertIn("visible civic records", purpose["why_the_framework_exists"])
        self.assertIn("Deterministic classifications", purpose["what_it_produces"])
        scope = self_description["scope_description"]
        self.assertEqual(5, len(scope["inputs"]))
        self.assertEqual(9, len(scope["outputs"]))
        self.assertEqual(3, len(scope["operational_boundaries"]))
        self.assertIn("No external truth determination", scope["operational_boundaries"])

        framework_description = self_description["framework_description"]
        self.assertEqual(
            "Civic Record Evaluation Framework",
            framework_description["framework_name"],
        )
        self.assertEqual(
            "Deterministic Record Evaluation Methodology",
            framework_description["methodology_type"],
        )
        self.assertEqual(
            "Methodological Boundaries Declared",
            framework_description["boundary_definition_state"],
        )

        architecture = self_description["framework_architecture"]
        self.assertEqual(
            [
                "Visible Record Layer",
                "Conditions Layer",
                "Pattern Interpretation Layer",
                "Trajectory Classification Layer",
                "Administrative Evaluation Layer",
                "Record Evolution Layer",
                "Determination Trace Layer",
                "Rule Citation Layer",
                "Evidence Attribution Layer",
                "Explainability Certification Layer",
                "Framework Self-Description Layer",
            ],
            [layer["layer_name"] for layer in architecture],
        )
        self.assertTrue(
            all(layer["output_state"] == "Implemented" for layer in architecture)
        )
        guarantees = self_description["framework_guarantees"]
        self.assertEqual(8, len(guarantees))
        self.assertIn(
            "Rule Visibility",
            {guarantee["guarantee_name"] for guarantee in guarantees},
        )
        self.assertTrue(
            all(
                guarantee["availability_state"] == "Available"
                for guarantee in guarantees
            )
        )
        constraints = self_description["framework_constraints"]
        self.assertEqual(16, len(constraints))
        self.assertIn(
            "Does Not Determine Truth",
            {constraint["constraint"] for constraint in constraints},
        )
        self.assertIn(
            "Does Not Modify Records",
            {constraint["constraint"] for constraint in constraints},
        )
        reflexive = self_description["reflexive_methodology"]
        self.assertEqual(
            "Framework Self-Description Available",
            reflexive["state"],
        )
        self.assertEqual(7, len(reflexive["implemented_stage_families"]))
        for key in (
            "what_it_does",
            "what_it_does_not_do",
            "how_it_reasons",
            "how_outputs_are_produced",
            "which_evidence_supports_outputs",
            "which_rules_support_reasoning",
            "which_boundaries_constrain_interpretation",
        ):
            self.assertTrue(reflexive[key])
        summary = self_description["framework_self_description_summary"]
        self.assertEqual(
            "Civic Record Evaluation Framework (CREF), CREF Stage 20",
            summary["framework_identity"],
        )
        self.assertEqual(
            "8 implemented guarantees available",
            summary["guarantees"],
        )
        self.assertEqual(
            "16 declared constraints visible",
            summary["constraints"],
        )
        self.assertEqual(
            "11 implemented layers described",
            summary["architecture"],
        )
        path = self_description["self_description_path"]
        self.assertEqual(
            [
                "Framework Documentation",
                "Implemented Stages",
                "Methodological Principles",
                "Framework Description",
                "Guarantees",
                "Limitations",
                "Reflexive Methodology",
            ],
            [step["label"] for step in path],
        )
        self.assertEqual(list(range(1, 8)), [step["step"] for step in path])
        self.assertIn(
            "Stage 20 does not create methodology.",
            self_description["limitations"],
        )
        self.assertIn(
            "Stage 20 does not introduce new reasoning.",
            self_description["limitations"],
        )
        self.assertIn(
            "Stage 20 does not perform self-improvement.",
            self_description["limitations"],
        )
        self.assertIn(
            "Stage 20 does not change framework behaviour.",
            self_description["limitations"],
        )
        self.assertIn(
            "Stage 20 describes only what already exists within the implemented framework.",
            self_description["limitations"],
        )
        self.assertEqual(
            self_description,
            self.admin_session.build_framework_self_description(),
        )

        rendered = self.admin_session._render_framework_self_description_content(
            self_description
        )
        self.assertIn("<h3>Framework Self-Description Summary</h3>", rendered)
        self.assertIn("<h3>Framework Description</h3>", rendered)
        self.assertIn("<h3>Framework Identity</h3>", rendered)
        self.assertIn("<h3>Purpose Description</h3>", rendered)
        self.assertIn("<h3>Scope Description</h3>", rendered)
        self.assertIn("<h3>Framework Architecture</h3>", rendered)
        self.assertIn("<h3>Framework Guarantees</h3>", rendered)
        self.assertIn("<h3>Framework Constraints</h3>", rendered)
        self.assertIn("<h3>Reflexive Methodology</h3>", rendered)
        self.assertIn("<h3>Self-Description Path</h3>", rendered)
        self.assertIn("<h3>Framework Limitations</h3>", rendered)
        self.assertIn(
            "<td>Framework Name</td><td>Civic Record Evaluation Framework</td>",
            rendered,
        )

    def test_stage21_report_mode_classification_and_structure_are_deterministic(self):
        classify = self.admin_session.classify_report_mode

        self.assertEqual("Executive Report", classify("executive"))
        self.assertEqual("Review Report", classify("review"))
        self.assertEqual("Full Inspection Report", classify("full"))
        self.assertEqual("Full Inspection Report", classify(None))
        self.assertEqual("Full Inspection Report", classify("unsupported"))

        review = self.admin_session.build_stage21_report_structure("review")
        self.assertEqual("review", review["report_mode"])
        self.assertEqual("Review Report", review["report_mode_label"])
        self.assertEqual(3, len(review["available_report_modes"]))
        self.assertEqual(11, len(review["section_index"]))
        self.assertEqual(
            list(range(1, 12)),
            [section["section_number"] for section in review["section_index"]],
        )
        self.assertIn(
            "This report mode is a summary view.",
            review["limitations"],
        )
        self.assertEqual(
            review,
            self.admin_session.build_stage21_report_structure("review"),
        )

    def test_stage21_report_modes_preserve_values_and_scope_output(self):
        evidence_groups = {
            "condition": [
                {
                    "target_label": "Escalation Without Response",
                    "attachments": [],
                    "relationship_count": 0,
                    "relationship_type_counts": {},
                }
            ],
            "signal": [],
            "finding": [],
            "record": [],
        }
        inputs = {
            "reference": "CREF-STAGE21-001",
            "record_version": 1,
            "evidence_groups": evidence_groups,
            "record_outputs": {
                "reference": "CREF-STAGE21-001",
                "case_title": "Stage 21 fixture",
                "conditions": ["Escalation Without Response"],
            },
            "record_metadata": {
                "reference": "CREF-STAGE21-001",
                "version": 1,
                "generated_at": "2026-06-29T10:00:00Z",
                "verification_hash": "a" * 64,
            },
            "version_history": [
                {
                    "reference": "CREF-STAGE21-001",
                    "version": 1,
                    "generated_at": "2026-06-29T10:00:00Z",
                    "verification_hash": "a" * 64,
                    "is_latest": 1,
                }
            ],
        }

        default_full = self.admin_session.render_admin_record_evidence_page(**inputs)
        explicit_full = self.admin_session.render_admin_record_evidence_page(
            **inputs,
            report_mode="full",
        )
        executive = self.admin_session.render_admin_record_evidence_page(
            **inputs,
            report_mode="executive",
        )
        review = self.admin_session.render_admin_record_evidence_page(
            **inputs,
            report_mode="review",
        )

        for content, mode in (
            (default_full, "Full Inspection Report"),
            (explicit_full, "Full Inspection Report"),
            (executive, "Executive Report"),
            (review, "Review Report"),
        ):
            self.assertIn("Report Navigation", content)
            self.assertIn("Report Section Index", content)
            self.assertIn(f"<td>Current Report Mode</td><td>{mode}</td>", content)
            self.assertIn("CREF-STAGE21-001", content)
            self.assertIn("Unsupported", content)
            self.assertIn("Report Mode Limitations", content)

        self.assertIn("Executive Report Summary", executive)
        self.assertIn("Administrative State Table", executive)
        self.assertIn("Evidence State Summary", executive)
        self.assertIn("Progression Requirements Table", executive)
        self.assertIn("Determination Trace Summary", executive)
        self.assertIn("Framework Limitations", executive)
        self.assertNotIn("stage19c-evidence-attribution-matrix", executive)
        self.assertNotIn("supporting-evidence-admin-group", executive)
        self.assertIn(
            "Full inspection remains available in Full Inspection Report mode.",
            executive,
        )

        self.assertIn("Review Support Detail", review)
        self.assertIn("Target-Level Evidence Summary", review)
        self.assertIn("Rule Citation Summary", review)
        self.assertIn("Evidence Attribution Summary", review)
        self.assertIn("Sufficiency Boundaries Summary", review)
        self.assertIn("Counterfactual Visibility Summary", review)
        self.assertIn("Explainability Certification Summary", review)
        self.assertIn("<h2>Determination Trace</h2>", review)
        self.assertNotIn("stage19c-evidence-attribution-matrix", review)

        for section in (
            "Administrative Workflow",
            "Outcome Analysis",
            "Resolution Analysis",
            "Closure Analysis",
            "Archive Analysis",
            "Supporting Evidence",
            "Record Evolution Accountability",
            "Determination Trace",
            "Rule Citation Layer",
            "Evidence Attribution Matrix",
            "Sufficiency Boundaries",
            "Counterfactual Visibility",
            "Explainability Certification",
            "Framework Self-Description",
        ):
            self.assertIn(section, explicit_full)
        self.assertIn(
            "This mode preserves the complete visible framework inspection record.",
            explicit_full,
        )
        self.assertEqual(default_full, explicit_full)

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

    def valid_request(self, report_mode=None):
        with self.env():
            session = self.admin_session.create_admin_session()
        query_params = (
            {"report_mode": report_mode}
            if report_mode is not None
            else {}
        )
        return FakeRequest(
            {self.admin_session.SESSION_COOKIE_NAME: session},
            query_params=query_params,
        )

    def test_stage21_admin_route_selects_report_mode_from_query_parameter(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            conn.close()
            try:
                with self.env():
                    executive_response = self.admin_session.admin_record_evidence_page(
                        "Strike-OT-20260604-ADMIN",
                        self.valid_request("executive"),
                    )
                    fallback_response = self.admin_session.admin_record_evidence_page(
                        "Strike-OT-20260604-ADMIN",
                        self.valid_request("unknown"),
                    )
            finally:
                self.admin_session.DB_PATH = original_db_path

        self.assertIn(
            "<td>Current Report Mode</td><td>Executive Report</td>",
            executive_response.content,
        )
        self.assertNotIn(
            "stage19c-evidence-attribution-matrix",
            executive_response.content,
        )
        self.assertIn(
            "<td>Current Report Mode</td><td>Full Inspection Report</td>",
            fallback_response.content,
        )
        self.assertIn(
            "stage19c-evidence-attribution-matrix",
            fallback_response.content,
        )

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
        self.assertIn("Governance Pattern Detection", after_content)
        self.assertIn("Pattern Summary", after_content)
        self.assertIn("<td>Total Pattern Layers</td><td>6</td>", after_content)
        self.assertIn("<td>Pattern-Matching Layers</td><td>6</td>", after_content)
        self.assertIn("<td>Non-Pattern Layers</td><td>0</td>", after_content)
        self.assertIn(
            "<td>Governance Pattern Classification</td><td>Recurring Governance Pattern</td>",
            after_content,
        )
        self.assertIn("<h3>Dependency Pattern Review</h3>", after_content)
        self.assertIn("<h3>Impact Pattern Review</h3>", after_content)
        self.assertIn("<h3>Stability Pattern Review</h3>", after_content)
        self.assertIn("<h3>Reproducibility Pattern Review</h3>", after_content)
        self.assertIn("<h3>Integrity Pattern Review</h3>", after_content)
        self.assertIn("<h3>Governance Pattern Review</h3>", after_content)
        self.assertIn("Governance Consistency", after_content)
        self.assertIn("Consistency Summary", after_content)
        self.assertIn("<td>Total Governance Layers</td><td>5</td>", after_content)
        self.assertIn("<td>Consistent Layers</td><td>0</td>", after_content)
        self.assertIn("<td>Inconsistent Layers</td><td>5</td>", after_content)
        self.assertIn(
            "<td>Consistency Classification</td><td>Governance Inconsistency</td>",
            after_content,
        )
        self.assertIn("<h3>Governance Review</h3>", after_content)
        self.assertIn("<h3>Continuity Review</h3>", after_content)
        self.assertIn("<h3>Change Review</h3>", after_content)
        self.assertIn("<h3>Trajectory Review</h3>", after_content)
        self.assertIn("<h3>Pattern Review</h3>", after_content)
        self.assertIn("Governance Relationships", after_content)
        self.assertIn("Relationship Summary", after_content)
        self.assertIn("<td>Total Governance Layers</td><td>6</td>", after_content)
        self.assertIn("<td>Related Governance Layers</td><td>6</td>", after_content)
        self.assertIn("<td>Aligned Relationships</td><td>0</td>", after_content)
        self.assertIn("<td>Conflicting Relationships</td><td>6</td>", after_content)
        self.assertIn(
            "<td>Relationship Classification</td><td>Governance Relationship Conflict</td>",
            after_content,
        )
        self.assertIn("<h3>Governance Relationship Review</h3>", after_content)
        self.assertIn("<h3>Continuity Relationship Review</h3>", after_content)
        self.assertIn("<h3>Change Relationship Review</h3>", after_content)
        self.assertIn("<h3>Trajectory Relationship Review</h3>", after_content)
        self.assertIn("<h3>Pattern Relationship Review</h3>", after_content)
        self.assertIn("<h3>Consistency Relationship Review</h3>", after_content)
        self.assertIn("Governance Traceability", after_content)
        self.assertIn("Traceability Summary", after_content)
        self.assertIn("<td>Total Traceability Layers</td><td>7</td>", after_content)
        self.assertIn("<td>Traceable Layers</td><td>7</td>", after_content)
        self.assertIn("<td>Untraceable Layers</td><td>0</td>", after_content)
        self.assertIn(
            "<td>Traceability Classification</td><td>Fully Traceable Governance</td>",
            after_content,
        )
        self.assertIn("<h3>Governance Traceability Review</h3>", after_content)
        self.assertIn("<h3>Continuity Traceability Review</h3>", after_content)
        self.assertIn("<h3>Change Traceability Review</h3>", after_content)
        self.assertIn("<h3>Trajectory Traceability Review</h3>", after_content)
        self.assertIn("<h3>Pattern Traceability Review</h3>", after_content)
        self.assertIn("<h3>Consistency Traceability Review</h3>", after_content)
        self.assertIn("<h3>Relationships Traceability Review</h3>", after_content)
        self.assertIn("Governance Coverage", after_content)
        self.assertIn("Coverage Summary", after_content)
        self.assertIn("<td>Total Governance Layers</td><td>8</td>", after_content)
        self.assertIn("<td>Present Governance Layers</td><td>8</td>", after_content)
        self.assertIn("<td>Missing Governance Layers</td><td>0</td>", after_content)
        self.assertIn("<td>Populated Governance Layers</td><td>8</td>", after_content)
        self.assertIn("<td>Unsupported Governance Layers</td><td>7</td>", after_content)
        self.assertIn(
            "<td>Coverage Classification</td><td>Full Governance Coverage</td>",
            after_content,
        )
        self.assertIn("<h3>Governance Coverage Review</h3>", after_content)
        self.assertIn("<h3>Continuity Coverage Review</h3>", after_content)
        self.assertIn("<h3>Change Coverage Review</h3>", after_content)
        self.assertIn("<h3>Trajectory Coverage Review</h3>", after_content)
        self.assertIn("<h3>Pattern Coverage Review</h3>", after_content)
        self.assertIn("<h3>Consistency Coverage Review</h3>", after_content)
        self.assertIn("<h3>Relationships Coverage Review</h3>", after_content)
        self.assertIn("<h3>Traceability Coverage Review</h3>", after_content)
        self.assertIn("Governance Chain Review", after_content)
        self.assertIn("Chain Review Summary", after_content)
        self.assertIn(
            "<td>Total Governance Chain Layers</td><td>9</td>",
            after_content,
        )
        self.assertIn("<td>Present Chain Layers</td><td>9</td>", after_content)
        self.assertIn("<td>Missing Chain Layers</td><td>0</td>", after_content)
        self.assertIn("<td>Traceable Chain Layers</td><td>8</td>", after_content)
        self.assertIn("<td>Covered Chain Layers</td><td>8</td>", after_content)
        self.assertIn("<td>Unsupported Chain Layers</td><td>3</td>", after_content)
        self.assertIn(
            "<td>Chain Review Classification</td><td>Governance Chain Breakdown</td>",
            after_content,
        )
        self.assertIn("<h3>Governance Chain Layer Review</h3>", after_content)
        self.assertIn("<h3>Continuity Chain Layer Review</h3>", after_content)
        self.assertIn("<h3>Change Chain Layer Review</h3>", after_content)
        self.assertIn("<h3>Trajectory Chain Layer Review</h3>", after_content)
        self.assertIn("<h3>Pattern Chain Layer Review</h3>", after_content)
        self.assertIn("<h3>Consistency Chain Layer Review</h3>", after_content)
        self.assertIn("<h3>Relationships Chain Layer Review</h3>", after_content)
        self.assertIn("<h3>Traceability Chain Layer Review</h3>", after_content)
        self.assertIn("<h3>Coverage Chain Layer Review</h3>", after_content)
        self.assertIn("Record Evolution Summary", after_content)
        self.assertIn("Evolution Summary", after_content)
        self.assertIn("Version Lineage Review", after_content)
        self.assertIn("Record Evolution Details", after_content)
        self.assertIn("<td>Current Version</td><td>1</td>", after_content)
        self.assertIn("<td>Is Latest Version</td><td>true</td>", after_content)
        self.assertIn("<td>Supersedes</td><td>None</td>", after_content)
        self.assertIn("<td>Superseded By</td><td>None</td>", after_content)
        self.assertIn("<td>Lineage Versions</td><td>1</td>", after_content)
        self.assertIn("<td>Earliest Version</td><td>1</td>", after_content)
        self.assertIn("<td>Latest Version</td><td>1</td>", after_content)
        self.assertIn(
            "<td>Evolution Classification</td><td>Initial Record State</td>",
            after_content,
        )
        self.assertIn("<th>Verification Hash</th>", after_content)
        self.assertIn("<th>Lineage State</th>", after_content)
        self.assertIn("Record Evolution Continuity", after_content)
        self.assertIn("Continuity Summary", after_content)
        self.assertIn("Version Continuity Review", after_content)
        self.assertIn("Supersession Continuity Review", after_content)
        self.assertIn("Reference Continuity Review", after_content)
        self.assertIn("Lineage Continuity Review", after_content)
        self.assertIn("<td>Version Gap Count</td><td>0</td>", after_content)
        self.assertIn(
            "<td>Supersession Link Count</td><td>0</td>",
            after_content,
        )
        self.assertIn(
            "<td>Broken Supersession Links</td><td>0</td>",
            after_content,
        )
        self.assertIn(
            "<td>Continuity Classification</td><td>Partial Evolution Continuity</td>",
            after_content,
        )
        self.assertIn("<td>Continuity State</td><td>Limited</td>", after_content)
        self.assertIn(
            "<td>Continuity State</td><td>No Supersession</td>",
            after_content,
        )
        self.assertIn(
            "<td>Reference Continuity State</td><td>Single Reference</td>",
            after_content,
        )
        self.assertIn("Record Evolution Change Log", after_content)
        self.assertIn("Change Log Summary", after_content)
        self.assertIn("Version Change Review", after_content)
        self.assertIn("Version Transition Review", after_content)
        self.assertIn("Field Change Review", after_content)
        self.assertIn("<td>Total Versions</td><td>1</td>", after_content)
        self.assertIn("<td>Version Transitions</td><td>0</td>", after_content)
        self.assertIn("<td>Changed Versions</td><td>0</td>", after_content)
        self.assertIn("<td>Unchanged Versions</td><td>1</td>", after_content)
        self.assertIn("<td>Field Changes</td><td>0</td>", after_content)
        self.assertIn("<td>Stable Fields</td><td>0</td>", after_content)
        self.assertIn(
            "<td>Change Log Classification</td><td>No Recorded Changes</td>",
            after_content,
        )
        self.assertIn("<td>No Transition</td>", after_content)
        self.assertIn("<td>Not Applicable</td>", after_content)
        self.assertIn("Record Evolution Trajectory", after_content)
        self.assertIn("Trajectory Summary", after_content)
        self.assertIn("Version Trajectory Review", after_content)
        self.assertIn("Supersession Trajectory Review", after_content)
        self.assertIn("Lineage Trajectory Review", after_content)
        self.assertIn("Timestamp Trajectory Review", after_content)
        self.assertIn("Verification Hash Trajectory Review", after_content)
        self.assertIn(
            "<td>Timestamp Order State</td><td>Missing Timestamp</td>",
            after_content,
        )
        self.assertIn(
            "<td>Verification Hash Coverage</td><td>Complete</td>",
            after_content,
        )
        self.assertIn(
            "<td>Trajectory Classification</td><td>Initial Evolution Trajectory</td>",
            after_content,
        )
        self.assertIn("Record Evolution Relationships", after_content)
        self.assertIn("Relationship Summary", after_content)
        self.assertIn("Version Relationship Review", after_content)
        self.assertIn("Supersession Relationship Review", after_content)
        self.assertIn("Timestamp Relationship Review", after_content)
        self.assertIn("Verification Relationship Review", after_content)
        self.assertIn("Evolution Relationship Review", after_content)
        self.assertIn(
            "Record evolution relationships are derived deterministically from existing record metadata, lineage history, continuity outputs, change log outputs, trajectory outputs, supersession fields, timestamps, and verification hashes only.",
            after_content,
        )
        self.assertIn(
            "<td>Version Relationships</td><td>Single Version</td>",
            after_content,
        )
        self.assertIn(
            "<td>Supersession Relationships</td><td>No Relationship</td>",
            after_content,
        )
        self.assertIn(
            "<td>Timestamp Relationships</td><td>Single Timestamp</td>",
            after_content,
        )
        self.assertIn(
            "<td>Verification Relationships</td><td>Complete Relationship</td>",
            after_content,
        )
        self.assertIn(
            "<td>Relationship Classification</td><td>No Evolution Relationships</td>",
            after_content,
        )
        self.assertIn("Record Evolution Traceability", after_content)
        self.assertIn("Traceability Summary", after_content)
        self.assertIn("Version Traceability Review", after_content)
        self.assertIn("Supersession Traceability Review", after_content)
        self.assertIn("Timestamp Traceability Review", after_content)
        self.assertIn("Verification Traceability Review", after_content)
        self.assertIn("Evolution Traceability Review", after_content)
        self.assertIn("<td>Traceable Versions</td><td>1</td>", after_content)
        self.assertIn("<td>Untraceable Versions</td><td>0</td>", after_content)
        self.assertIn("<td>Traceable Timestamps</td><td>0</td>", after_content)
        self.assertIn("<td>Missing Timestamps</td><td>1</td>", after_content)
        self.assertIn(
            "<td>Traceable Verification Hashes</td><td>1</td>",
            after_content,
        )
        self.assertIn(
            "<td>Missing Verification Hashes</td><td>0</td>",
            after_content,
        )
        self.assertIn(
            "<td>Traceability Classification</td><td>Untraceable Evolution</td>",
            after_content,
        )
        self.assertIn("Record Evolution Coverage", after_content)
        self.assertIn("Coverage Summary", after_content)
        self.assertIn("Version Coverage Review", after_content)
        self.assertIn("Supersession Coverage Review", after_content)
        self.assertIn("Timestamp Coverage Review", after_content)
        self.assertIn("Verification Coverage Review", after_content)
        self.assertIn("Evolution Output Coverage Review", after_content)
        self.assertIn("<td>Covered Versions</td><td>1</td>", after_content)
        self.assertIn("<td>Missing Versions</td><td>0</td>", after_content)
        self.assertIn("<td>Covered Supersession Links</td><td>0</td>", after_content)
        self.assertIn("<td>Missing Supersession Links</td><td>0</td>", after_content)
        self.assertIn("<td>Covered Timestamps</td><td>0</td>", after_content)
        self.assertIn("<td>Missing Timestamps</td><td>1</td>", after_content)
        self.assertIn(
            "<td>Covered Verification Hashes</td><td>1</td>",
            after_content,
        )
        self.assertIn(
            "<td>Missing Verification Hashes</td><td>0</td>",
            after_content,
        )
        self.assertIn("<td>Covered Evolution Outputs</td><td>6</td>", after_content)
        self.assertIn("<td>Missing Evolution Outputs</td><td>0</td>", after_content)
        self.assertIn(
            "<td>Coverage Classification</td><td>Limited Evolution Coverage</td>",
            after_content,
        )
        self.assertIn("Record Evolution Review", after_content)
        self.assertIn("Review Summary", after_content)
        self.assertIn("Version Review", after_content)
        self.assertIn("Evolution Output Review", after_content)
        self.assertIn("Coverage Review", after_content)
        self.assertIn("Traceability Review", after_content)
        self.assertIn("Relationship Review", after_content)
        self.assertIn("<td>Reviewable Versions</td><td>1</td>", after_content)
        self.assertIn("<td>Unreviewable Versions</td><td>0</td>", after_content)
        self.assertIn(
            "<td>Reviewable Evolution Outputs</td><td>7</td>",
            after_content,
        )
        self.assertIn("<td>Missing Evolution Outputs</td><td>0</td>", after_content)
        self.assertIn(
            "<td>Review Classification</td><td>Unresolved Evolution Review</td>",
            after_content,
        )
        self.assertIn("Record Evolution Readiness", after_content)
        self.assertIn("Readiness Summary", after_content)
        self.assertIn("Version Readiness Review", after_content)
        self.assertIn("Coverage Readiness Review", after_content)
        self.assertIn("Traceability Readiness Review", after_content)
        self.assertIn("Review Readiness Review", after_content)
        self.assertIn("Evolution Readiness Review", after_content)
        self.assertIn("<td>Reviewable Versions</td><td>1</td>", after_content)
        self.assertIn("<td>Traceable Versions</td><td>1</td>", after_content)
        self.assertIn("<td>Covered Versions</td><td>1</td>", after_content)
        self.assertIn(
            "<td>Reviewable Evolution Outputs</td><td>8</td>",
            after_content,
        )
        self.assertIn("<td>Missing Evolution Outputs</td><td>0</td>", after_content)
        self.assertIn(
            "<td>Readiness Classification</td><td>Unresolved Evolution Readiness</td>",
            after_content,
        )
        self.assertIn("Record Evolution Completeness", after_content)
        self.assertIn("Completeness Summary", after_content)
        self.assertIn("Version Completeness Review", after_content)
        self.assertIn("Evolution Output Completeness Review", after_content)
        self.assertIn("Coverage Completeness Review", after_content)
        self.assertIn("Review Completeness Review", after_content)
        self.assertIn("Readiness Completeness Review", after_content)
        self.assertIn("Evolution Completeness Review", after_content)
        self.assertIn("<td>Complete Versions</td><td>0</td>", after_content)
        self.assertIn("<td>Incomplete Versions</td><td>1</td>", after_content)
        self.assertIn(
            "<td>Complete Evolution Outputs</td><td>9</td>",
            after_content,
        )
        self.assertIn("<td>Missing Evolution Outputs</td><td>0</td>", after_content)
        self.assertIn(
            "<td>Completeness Classification</td><td>Unresolved Evolution Completeness</td>",
            after_content,
        )
        self.assertIn("Record Evolution Sufficiency", after_content)
        self.assertIn("Sufficiency Summary", after_content)
        self.assertIn("Version Sufficiency Review", after_content)
        self.assertIn("Evolution Output Sufficiency Review", after_content)
        self.assertIn("Coverage Sufficiency Review", after_content)
        self.assertIn("Review Sufficiency Review", after_content)
        self.assertIn("Readiness Sufficiency Review", after_content)
        self.assertIn("Completeness Sufficiency Review", after_content)
        self.assertIn("Evolution Sufficiency Review", after_content)
        self.assertIn("<td>Sufficient Versions</td><td>0</td>", after_content)
        self.assertIn("<td>Insufficient Versions</td><td>1</td>", after_content)
        self.assertIn(
            "<td>Sufficient Evolution Outputs</td><td>10</td>",
            after_content,
        )
        self.assertIn("<td>Missing Evolution Outputs</td><td>0</td>", after_content)
        self.assertIn(
            "<td>Sufficiency Classification</td><td>Unresolved Evolution Information</td>",
            after_content,
        )
        self.assertIn("Record Evolution Consistency", after_content)
        self.assertIn("Consistency Summary", after_content)
        self.assertIn("Version Consistency Review", after_content)
        self.assertIn("Supersession Consistency Review", after_content)
        self.assertIn("Timestamp Consistency Review", after_content)
        self.assertIn("Verification Consistency Review", after_content)
        self.assertIn("Evolution Output Consistency Review", after_content)
        self.assertIn("Evolution Consistency Review", after_content)
        self.assertIn("<td>Consistent Versions</td><td>1</td>", after_content)
        self.assertIn("<td>Inconsistent Versions</td><td>0</td>", after_content)
        self.assertIn(
            "<td>Consistent Supersession Links</td><td>0</td>",
            after_content,
        )
        self.assertIn(
            "<td>Inconsistent Supersession Links</td><td>0</td>",
            after_content,
        )
        self.assertIn("<td>Consistent Timestamps</td><td>0</td>", after_content)
        self.assertIn("<td>Inconsistent Timestamps</td><td>0</td>", after_content)
        self.assertIn(
            "<td>Consistent Verification Hashes</td><td>1</td>",
            after_content,
        )
        self.assertIn(
            "<td>Inconsistent Verification Hashes</td><td>0</td>",
            after_content,
        )
        self.assertIn(
            "<td>Consistent Evolution Outputs</td><td>11</td>",
            after_content,
        )
        self.assertIn(
            "<td>Inconsistent Evolution Outputs</td><td>0</td>",
            after_content,
        )
        self.assertIn("<td>Missing Evolution Outputs</td><td>0</td>", after_content)
        self.assertIn(
            "<td>Consistency Classification</td><td>Unresolved Evolution Consistency</td>",
            after_content,
        )
        self.assertIn("Record Evolution Integrity", after_content)
        self.assertIn("Integrity Summary", after_content)
        self.assertIn("Version Integrity Review", after_content)
        self.assertIn("Supersession Integrity Review", after_content)
        self.assertIn("Timestamp Integrity Review", after_content)
        self.assertIn("Verification Integrity Review", after_content)
        self.assertIn("Evolution Output Integrity Review", after_content)
        self.assertIn("Evolution Integrity Review", after_content)
        self.assertIn("<td>Intact Versions</td><td>1</td>", after_content)
        self.assertIn("<td>Broken Versions</td><td>0</td>", after_content)
        self.assertIn(
            "<td>Intact Supersession Links</td><td>0</td>",
            after_content,
        )
        self.assertIn(
            "<td>Broken Supersession Links</td><td>0</td>",
            after_content,
        )
        self.assertIn("<td>Intact Timestamps</td><td>0</td>", after_content)
        self.assertIn("<td>Broken Timestamps</td><td>0</td>", after_content)
        self.assertIn(
            "<td>Intact Verification Hashes</td><td>1</td>",
            after_content,
        )
        self.assertIn(
            "<td>Broken Verification Hashes</td><td>0</td>",
            after_content,
        )
        self.assertIn(
            "<td>Intact Evolution Outputs</td><td>12</td>",
            after_content,
        )
        self.assertIn(
            "<td>Broken Evolution Outputs</td><td>0</td>",
            after_content,
        )
        self.assertIn("<td>Missing Evolution Outputs</td><td>0</td>", after_content)
        self.assertIn(
            "<td>Integrity Classification</td><td>Unresolved Evolution Integrity</td>",
            after_content,
        )
        self.assertIn("Record Evolution Reliability", after_content)
        self.assertIn("Reliability Summary", after_content)
        self.assertIn("Version Reliability Review", after_content)
        self.assertIn("Supersession Reliability Review", after_content)
        self.assertIn("Timestamp Reliability Review", after_content)
        self.assertIn("Verification Reliability Review", after_content)
        self.assertIn("Evolution Output Reliability Review", after_content)
        self.assertIn("Evolution Reliability Review", after_content)
        self.assertIn("<td>Reliable Versions</td><td>1</td>", after_content)
        self.assertIn("<td>Unreliable Versions</td><td>0</td>", after_content)
        self.assertIn(
            "<td>Reliable Supersession Links</td><td>0</td>",
            after_content,
        )
        self.assertIn(
            "<td>Unreliable Supersession Links</td><td>0</td>",
            after_content,
        )
        self.assertIn("<td>Reliable Timestamps</td><td>0</td>", after_content)
        self.assertIn("<td>Unreliable Timestamps</td><td>0</td>", after_content)
        self.assertIn(
            "<td>Reliable Verification Hashes</td><td>1</td>",
            after_content,
        )
        self.assertIn(
            "<td>Unreliable Verification Hashes</td><td>0</td>",
            after_content,
        )
        self.assertIn(
            "<td>Reliable Evolution Outputs</td><td>13</td>",
            after_content,
        )
        self.assertIn(
            "<td>Unreliable Evolution Outputs</td><td>0</td>",
            after_content,
        )
        self.assertIn("<td>Missing Evolution Outputs</td><td>0</td>", after_content)
        self.assertIn(
            "<td>Reliability Classification</td><td>Unresolved Evolution Reliability</td>",
            after_content,
        )
        self.assertIn("Record Evolution Certification", after_content)
        self.assertIn("Certification Summary", after_content)
        self.assertIn("Version Certification Review", after_content)
        self.assertIn("Supersession Certification Review", after_content)
        self.assertIn("Timestamp Certification Review", after_content)
        self.assertIn("Verification Certification Review", after_content)
        self.assertIn("Evolution Output Certification Review", after_content)
        self.assertIn("Evolution Certification Review", after_content)
        self.assertIn("<td>Certifiable Versions</td><td>1</td>", after_content)
        self.assertIn("<td>Non-Certifiable Versions</td><td>0</td>", after_content)
        self.assertIn(
            "<td>Certifiable Supersession Links</td><td>0</td>",
            after_content,
        )
        self.assertIn(
            "<td>Non-Certifiable Supersession Links</td><td>0</td>",
            after_content,
        )
        self.assertIn("<td>Certifiable Timestamps</td><td>0</td>", after_content)
        self.assertIn("<td>Non-Certifiable Timestamps</td><td>0</td>", after_content)
        self.assertIn(
            "<td>Certifiable Verification Hashes</td><td>1</td>",
            after_content,
        )
        self.assertIn(
            "<td>Non-Certifiable Verification Hashes</td><td>0</td>",
            after_content,
        )
        self.assertIn(
            "<td>Certifiable Evolution Outputs</td><td>14</td>",
            after_content,
        )
        self.assertIn(
            "<td>Non-Certifiable Evolution Outputs</td><td>0</td>",
            after_content,
        )
        self.assertIn("<td>Missing Evolution Outputs</td><td>0</td>", after_content)
        self.assertIn(
            "<td>Certification Classification</td><td>Unresolved Evolution Certification</td>",
            after_content,
        )
        self.assertIn("Record Evolution Accreditation", after_content)
        self.assertIn("Accreditation Summary", after_content)
        self.assertIn("Version Accreditation Review", after_content)
        self.assertIn("Supersession Accreditation Review", after_content)
        self.assertIn("Timestamp Accreditation Review", after_content)
        self.assertIn("Verification Accreditation Review", after_content)
        self.assertIn("Evolution Output Accreditation Review", after_content)
        self.assertIn("Evolution Accreditation Review", after_content)
        self.assertIn("<td>Accreditable Versions</td><td>1</td>", after_content)
        self.assertIn("<td>Non-Accreditable Versions</td><td>0</td>", after_content)
        self.assertIn(
            "<td>Accreditable Supersession Links</td><td>0</td>",
            after_content,
        )
        self.assertIn(
            "<td>Non-Accreditable Supersession Links</td><td>0</td>",
            after_content,
        )
        self.assertIn("<td>Accreditable Timestamps</td><td>0</td>", after_content)
        self.assertIn("<td>Non-Accreditable Timestamps</td><td>0</td>", after_content)
        self.assertIn(
            "<td>Accreditable Verification Hashes</td><td>1</td>",
            after_content,
        )
        self.assertIn(
            "<td>Non-Accreditable Verification Hashes</td><td>0</td>",
            after_content,
        )
        self.assertIn(
            "<td>Accreditable Evolution Outputs</td><td>15</td>",
            after_content,
        )
        self.assertIn(
            "<td>Non-Accreditable Evolution Outputs</td><td>0</td>",
            after_content,
        )
        self.assertIn("<td>Missing Evolution Outputs</td><td>0</td>", after_content)
        self.assertIn(
            "<td>Accreditation Classification</td><td>Unresolved Evolution Accreditation</td>",
            after_content,
        )
        self.assertIn("Record Evolution Auditability", after_content)
        self.assertIn("Auditability Summary", after_content)
        self.assertIn("Version Auditability Review", after_content)
        self.assertIn("Supersession Auditability Review", after_content)
        self.assertIn("Timestamp Auditability Review", after_content)
        self.assertIn("Verification Auditability Review", after_content)
        self.assertIn("Evolution Output Auditability Review", after_content)
        self.assertIn("Evolution Auditability Review", after_content)
        self.assertIn("<td>Auditable Versions</td><td>1</td>", after_content)
        self.assertIn("<td>Non-Auditable Versions</td><td>0</td>", after_content)
        self.assertIn(
            "<td>Auditable Supersession Links</td><td>0</td>",
            after_content,
        )
        self.assertIn(
            "<td>Non-Auditable Supersession Links</td><td>0</td>",
            after_content,
        )
        self.assertIn("<td>Auditable Timestamps</td><td>0</td>", after_content)
        self.assertIn("<td>Non-Auditable Timestamps</td><td>0</td>", after_content)
        self.assertIn(
            "<td>Auditable Verification Hashes</td><td>1</td>",
            after_content,
        )
        self.assertIn(
            "<td>Non-Auditable Verification Hashes</td><td>0</td>",
            after_content,
        )
        self.assertIn(
            "<td>Auditable Evolution Outputs</td><td>16</td>",
            after_content,
        )
        self.assertIn(
            "<td>Non-Auditable Evolution Outputs</td><td>0</td>",
            after_content,
        )
        self.assertIn("<td>Missing Evolution Outputs</td><td>0</td>", after_content)
        self.assertIn(
            "<td>Auditability Classification</td><td>Unresolved Evolution Auditability</td>",
            after_content,
        )
        self.assertIn("Record Evolution Reproducibility", after_content)
        self.assertIn("Reproducibility Summary", after_content)
        self.assertIn("Version Reproducibility Review", after_content)
        self.assertIn("Supersession Reproducibility Review", after_content)
        self.assertIn("Timestamp Reproducibility Review", after_content)
        self.assertIn("Verification Reproducibility Review", after_content)
        self.assertIn("Evolution Output Reproducibility Review", after_content)
        self.assertIn("Evolution Reproducibility Review", after_content)
        self.assertIn("<td>Reproducible Versions</td><td>1</td>", after_content)
        self.assertIn("<td>Non-Reproducible Versions</td><td>0</td>", after_content)
        self.assertIn(
            "<td>Reproducible Supersession Links</td><td>0</td>",
            after_content,
        )
        self.assertIn(
            "<td>Non-Reproducible Supersession Links</td><td>0</td>",
            after_content,
        )
        self.assertIn("<td>Reproducible Timestamps</td><td>0</td>", after_content)
        self.assertIn(
            "<td>Non-Reproducible Timestamps</td><td>0</td>",
            after_content,
        )
        self.assertIn(
            "<td>Reproducible Verification Hashes</td><td>1</td>",
            after_content,
        )
        self.assertIn(
            "<td>Non-Reproducible Verification Hashes</td><td>0</td>",
            after_content,
        )
        self.assertIn(
            "<td>Reproducible Evolution Outputs</td><td>17</td>",
            after_content,
        )
        self.assertIn(
            "<td>Non-Reproducible Evolution Outputs</td><td>0</td>",
            after_content,
        )
        self.assertIn("<td>Missing Evolution Outputs</td><td>0</td>", after_content)
        self.assertIn(
            "<td>Reproducibility Classification</td><td>Non-Reproducible Evolution Chain</td>",
            after_content,
        )
        self.assertIn("Record Evolution Transparency", after_content)
        self.assertIn("Transparency Summary", after_content)
        self.assertIn("Version Transparency Review", after_content)
        self.assertIn("Supersession Transparency Review", after_content)
        self.assertIn("Timestamp Transparency Review", after_content)
        self.assertIn("Verification Transparency Review", after_content)
        self.assertIn("Evolution Output Transparency Review", after_content)
        self.assertIn("Evolution Transparency Review", after_content)
        self.assertIn("<td>Transparent Versions</td><td>1</td>", after_content)
        self.assertIn("<td>Non-Transparent Versions</td><td>0</td>", after_content)
        self.assertIn(
            "<td>Transparent Supersession Links</td><td>0</td>",
            after_content,
        )
        self.assertIn(
            "<td>Non-Transparent Supersession Links</td><td>0</td>",
            after_content,
        )
        self.assertIn("<td>Transparent Timestamps</td><td>0</td>", after_content)
        self.assertIn(
            "<td>Non-Transparent Timestamps</td><td>0</td>",
            after_content,
        )
        self.assertIn(
            "<td>Transparent Verification Hashes</td><td>1</td>",
            after_content,
        )
        self.assertIn(
            "<td>Non-Transparent Verification Hashes</td><td>0</td>",
            after_content,
        )
        self.assertIn(
            "<td>Transparent Evolution Outputs</td><td>17</td>",
            after_content,
        )
        self.assertIn(
            "<td>Non-Transparent Evolution Outputs</td><td>1</td>",
            after_content,
        )
        self.assertIn("<td>Missing Evolution Outputs</td><td>0</td>", after_content)
        self.assertIn(
            "<td>Transparency Classification</td><td>Non-Transparent Evolution Chain</td>",
            after_content,
        )
        self.assertIn("Record Evolution Accountability", after_content)
        self.assertIn("Accountability Summary", after_content)
        self.assertIn("Version Accountability Review", after_content)
        self.assertIn("Supersession Accountability Review", after_content)
        self.assertIn("Timestamp Accountability Review", after_content)
        self.assertIn("Verification Accountability Review", after_content)
        self.assertIn("Generated-By Accountability Review", after_content)
        self.assertIn("Evolution Output Accountability Review", after_content)
        self.assertIn("Evolution Accountability Review", after_content)
        self.assertIn("<td>Accountable Versions</td><td>1</td>", after_content)
        self.assertIn("<td>Non-Accountable Versions</td><td>0</td>", after_content)
        self.assertIn(
            "<td>Accountable Supersession Links</td><td>0</td>",
            after_content,
        )
        self.assertIn(
            "<td>Non-Accountable Supersession Links</td><td>0</td>",
            after_content,
        )
        self.assertIn("<td>Accountable Timestamps</td><td>0</td>", after_content)
        self.assertIn(
            "<td>Non-Accountable Timestamps</td><td>0</td>",
            after_content,
        )
        self.assertIn(
            "<td>Accountable Verification Hashes</td><td>1</td>",
            after_content,
        )
        self.assertIn(
            "<td>Non-Accountable Verification Hashes</td><td>0</td>",
            after_content,
        )
        self.assertIn(
            "<td>Accountable Generated-By Values</td><td>0</td>",
            after_content,
        )
        self.assertIn(
            "<td>Non-Accountable Generated-By Values</td><td>0</td>",
            after_content,
        )
        self.assertIn(
            "<td>Missing Generated-By Values</td><td>1</td>",
            after_content,
        )
        self.assertIn(
            "<td>Accountable Evolution Outputs</td><td>17</td>",
            after_content,
        )
        self.assertIn(
            "<td>Non-Accountable Evolution Outputs</td><td>2</td>",
            after_content,
        )
        self.assertIn("<td>Missing Evolution Outputs</td><td>0</td>", after_content)
        self.assertIn(
            "<td>Accountability Classification</td><td>Non-Accountable Evolution Chain</td>",
            after_content,
        )
        self.assertIn("Determination Trace", after_content)
        self.assertIn("Trace Summary", after_content)
        self.assertIn("Visible Record", after_content)
        self.assertIn("Observed Evidence", after_content)
        self.assertIn("Applied Rules", after_content)
        self.assertIn("Trace Path", after_content)
        self.assertIn("Limitations", after_content)
        self.assertIn(
            "<td>Determination</td><td>Determination derived from visible record evolution</td>",
            after_content,
        )
        self.assertIn("<td>Conditions Count</td><td>1</td>", after_content)
        self.assertIn("<td>Trace Steps Count</td><td>6</td>", after_content)
        self.assertIn("Rule Citation Layer", after_content)
        self.assertIn("Citation Summary", after_content)
        self.assertIn("Rule Family Citations", after_content)
        self.assertIn("Condition Citations", after_content)
        self.assertIn("Trajectory Citations", after_content)
        self.assertIn("Administrative Citations", after_content)
        self.assertIn("Record Evolution Citations", after_content)
        self.assertIn("Citation Path", after_content)
        self.assertIn(
            "<td>Citation State</td><td>Rule Citation Layer Available</td>",
            after_content,
        )
        self.assertIn("Evidence Attribution Matrix", after_content)
        self.assertIn("Attribution Summary", after_content)
        self.assertIn("Evidence Sources", after_content)
        self.assertIn("Condition Attribution", after_content)
        self.assertIn("Trajectory Attribution", after_content)
        self.assertIn("Administrative Attribution", after_content)
        self.assertIn("Record Evolution Attribution", after_content)
        self.assertIn("Determination Trace Attribution", after_content)
        self.assertIn("Rule Citation Attribution", after_content)
        self.assertIn("Unsupported Outputs", after_content)
        self.assertIn("Attribution Path", after_content)
        self.assertIn(
            "<td>Attribution State</td><td>Evidence Attribution Matrix Available</td>",
            after_content,
        )
        self.assertIn("Determination Report", after_content)
        self.assertIn("Report Overview", after_content)
        self.assertIn("Report Summary", after_content)
        self.assertIn("Report Sections", after_content)
        self.assertIn("Report Path", after_content)
        self.assertIn(
            "<td>Report State</td><td>Determination Report Available</td>",
            after_content,
        )
        self.assertIn("Sufficiency Boundaries", after_content)
        self.assertIn("Boundary Overview", after_content)
        self.assertIn("Boundary Summary", after_content)
        self.assertIn("Supported Outputs", after_content)
        self.assertIn("Partially Supported Outputs", after_content)
        self.assertIn("Unsupported Outputs", after_content)
        self.assertIn("Boundary Path", after_content)
        self.assertIn(
            "<td>Boundary State</td><td>Sufficiency Boundaries Available</td>",
            after_content,
        )
        self.assertIn("Counterfactual Visibility", after_content)
        self.assertIn("Visibility Summary", after_content)
        self.assertIn("Visible Layers", after_content)
        self.assertIn("Non-Visible Layers", after_content)
        self.assertIn("Visible Evidence Elements", after_content)
        self.assertIn("Non-Visible Evidence Elements", after_content)
        self.assertIn("Counterfactual Path", after_content)
        self.assertIn(
            "<td>Visibility State</td><td>Counterfactual Visibility Available</td>",
            after_content,
        )
        self.assertIn("Explainability Certification", after_content)
        self.assertIn("Certification Overview", after_content)
        self.assertIn("Certification Summary", after_content)
        self.assertIn("Certified Components", after_content)
        self.assertIn("Partially Certified Components", after_content)
        self.assertIn("Uncertified Components", after_content)
        self.assertIn("Certification Path", after_content)
        self.assertIn(
            "<td>Certification State</td><td>Explainability Certified</td>",
            after_content,
        )
        self.assertIn("Framework Self-Description", after_content)
        self.assertIn("Framework Description", after_content)
        self.assertIn("Framework Identity", after_content)
        self.assertIn("Purpose Description", after_content)
        self.assertIn("Scope Description", after_content)
        self.assertIn("Framework Architecture", after_content)
        self.assertIn("Framework Guarantees", after_content)
        self.assertIn("Framework Constraints", after_content)
        self.assertIn("Framework Limitations", after_content)
        self.assertIn("Reflexive Methodology", after_content)
        self.assertIn("Self-Description Path", after_content)
        self.assertIn(
            "<td>Reflexive Methodology State</td><td>Framework Self-Description Available</td>",
            after_content,
        )
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
        self.assertIn("Governance Pattern Detection", content)
        self.assertIn("Pattern Summary", content)
        self.assertIn("<td>Total Pattern Layers</td><td>6</td>", content)
        self.assertIn("<td>Pattern-Matching Layers</td><td>6</td>", content)
        self.assertIn("<td>Non-Pattern Layers</td><td>0</td>", content)
        self.assertIn(
            "<td>Governance Pattern Classification</td><td>Recurring Governance Pattern</td>",
            content,
        )
        self.assertIn("<h3>Dependency Pattern Review</h3>", content)
        self.assertIn("<h3>Impact Pattern Review</h3>", content)
        self.assertIn("<h3>Stability Pattern Review</h3>", content)
        self.assertIn("<h3>Reproducibility Pattern Review</h3>", content)
        self.assertIn("<h3>Integrity Pattern Review</h3>", content)
        self.assertIn("<h3>Governance Pattern Review</h3>", content)
        self.assertIn("Governance Consistency", content)
        self.assertIn("Consistency Summary", content)
        self.assertIn("<td>Total Governance Layers</td><td>5</td>", content)
        self.assertIn("<td>Consistent Layers</td><td>0</td>", content)
        self.assertIn("<td>Inconsistent Layers</td><td>5</td>", content)
        self.assertIn(
            "<td>Consistency Classification</td><td>Governance Inconsistency</td>",
            content,
        )
        self.assertIn("<h3>Governance Review</h3>", content)
        self.assertIn("<h3>Continuity Review</h3>", content)
        self.assertIn("<h3>Change Review</h3>", content)
        self.assertIn("<h3>Trajectory Review</h3>", content)
        self.assertIn("<h3>Pattern Review</h3>", content)
        self.assertIn("Governance Relationships", content)
        self.assertIn("Relationship Summary", content)
        self.assertIn("<td>Total Governance Layers</td><td>6</td>", content)
        self.assertIn("<td>Related Governance Layers</td><td>6</td>", content)
        self.assertIn("<td>Aligned Relationships</td><td>0</td>", content)
        self.assertIn("<td>Conflicting Relationships</td><td>6</td>", content)
        self.assertIn(
            "<td>Relationship Classification</td><td>Governance Relationship Conflict</td>",
            content,
        )
        self.assertIn("<h3>Governance Relationship Review</h3>", content)
        self.assertIn("<h3>Continuity Relationship Review</h3>", content)
        self.assertIn("<h3>Change Relationship Review</h3>", content)
        self.assertIn("<h3>Trajectory Relationship Review</h3>", content)
        self.assertIn("<h3>Pattern Relationship Review</h3>", content)
        self.assertIn("<h3>Consistency Relationship Review</h3>", content)
        self.assertIn("Governance Traceability", content)
        self.assertIn("Traceability Summary", content)
        self.assertIn("<td>Total Traceability Layers</td><td>7</td>", content)
        self.assertIn("<td>Traceable Layers</td><td>7</td>", content)
        self.assertIn("<td>Untraceable Layers</td><td>0</td>", content)
        self.assertIn(
            "<td>Traceability Classification</td><td>Fully Traceable Governance</td>",
            content,
        )
        self.assertIn("<h3>Governance Traceability Review</h3>", content)
        self.assertIn("<h3>Continuity Traceability Review</h3>", content)
        self.assertIn("<h3>Change Traceability Review</h3>", content)
        self.assertIn("<h3>Trajectory Traceability Review</h3>", content)
        self.assertIn("<h3>Pattern Traceability Review</h3>", content)
        self.assertIn("<h3>Consistency Traceability Review</h3>", content)
        self.assertIn("<h3>Relationships Traceability Review</h3>", content)
        self.assertIn("Governance Coverage", content)
        self.assertIn("Coverage Summary", content)
        self.assertIn("<td>Total Governance Layers</td><td>8</td>", content)
        self.assertIn("<td>Present Governance Layers</td><td>8</td>", content)
        self.assertIn("<td>Missing Governance Layers</td><td>0</td>", content)
        self.assertIn("<td>Populated Governance Layers</td><td>8</td>", content)
        self.assertIn("<td>Unsupported Governance Layers</td><td>7</td>", content)
        self.assertIn(
            "<td>Coverage Classification</td><td>Full Governance Coverage</td>",
            content,
        )
        self.assertIn("<h3>Governance Coverage Review</h3>", content)
        self.assertIn("<h3>Continuity Coverage Review</h3>", content)
        self.assertIn("<h3>Change Coverage Review</h3>", content)
        self.assertIn("<h3>Trajectory Coverage Review</h3>", content)
        self.assertIn("<h3>Pattern Coverage Review</h3>", content)
        self.assertIn("<h3>Consistency Coverage Review</h3>", content)
        self.assertIn("<h3>Relationships Coverage Review</h3>", content)
        self.assertIn("<h3>Traceability Coverage Review</h3>", content)
        self.assertIn("Governance Chain Review", content)
        self.assertIn("Chain Review Summary", content)
        self.assertIn("<td>Total Governance Chain Layers</td><td>9</td>", content)
        self.assertIn("<td>Present Chain Layers</td><td>9</td>", content)
        self.assertIn("<td>Missing Chain Layers</td><td>0</td>", content)
        self.assertIn("<td>Traceable Chain Layers</td><td>8</td>", content)
        self.assertIn("<td>Covered Chain Layers</td><td>8</td>", content)
        self.assertIn("<td>Unsupported Chain Layers</td><td>3</td>", content)
        self.assertIn(
            "<td>Chain Review Classification</td><td>Governance Chain Breakdown</td>",
            content,
        )
        self.assertIn("<h3>Governance Chain Layer Review</h3>", content)
        self.assertIn("<h3>Continuity Chain Layer Review</h3>", content)
        self.assertIn("<h3>Change Chain Layer Review</h3>", content)
        self.assertIn("<h3>Trajectory Chain Layer Review</h3>", content)
        self.assertIn("<h3>Pattern Chain Layer Review</h3>", content)
        self.assertIn("<h3>Consistency Chain Layer Review</h3>", content)
        self.assertIn("<h3>Relationships Chain Layer Review</h3>", content)
        self.assertIn("<h3>Traceability Chain Layer Review</h3>", content)
        self.assertIn("<h3>Coverage Chain Layer Review</h3>", content)
        self.assertIn("Record Evolution Summary", content)
        self.assertIn("Evolution Summary", content)
        self.assertIn("Version Lineage Review", content)
        self.assertIn("Record Evolution Details", content)
        self.assertIn("<td>Current Version</td><td>1</td>", content)
        self.assertIn("<td>Is Latest Version</td><td>true</td>", content)
        self.assertIn("<td>Supersedes</td><td>None</td>", content)
        self.assertIn("<td>Superseded By</td><td>None</td>", content)
        self.assertIn("<td>Lineage Versions</td><td>1</td>", content)
        self.assertIn("<td>Earliest Version</td><td>1</td>", content)
        self.assertIn("<td>Latest Version</td><td>1</td>", content)
        self.assertIn(
            "<td>Evolution Classification</td><td>Initial Record State</td>",
            content,
        )
        self.assertIn("<th>Verification Hash</th>", content)
        self.assertIn("<th>Lineage State</th>", content)
        self.assertIn("Record Evolution Continuity", content)
        self.assertIn("Continuity Summary", content)
        self.assertIn("Version Continuity Review", content)
        self.assertIn("Supersession Continuity Review", content)
        self.assertIn("Reference Continuity Review", content)
        self.assertIn("Lineage Continuity Review", content)
        self.assertIn("<td>Version Gap Count</td><td>0</td>", content)
        self.assertIn("<td>Supersession Link Count</td><td>0</td>", content)
        self.assertIn("<td>Broken Supersession Links</td><td>0</td>", content)
        self.assertIn(
            "<td>Continuity Classification</td><td>Partial Evolution Continuity</td>",
            content,
        )
        self.assertIn("<td>Continuity State</td><td>Limited</td>", content)
        self.assertIn("<td>Continuity State</td><td>No Supersession</td>", content)
        self.assertIn(
            "<td>Reference Continuity State</td><td>Single Reference</td>",
            content,
        )
        self.assertIn("Record Evolution Change Log", content)
        self.assertIn("Change Log Summary", content)
        self.assertIn("Version Change Review", content)
        self.assertIn("Version Transition Review", content)
        self.assertIn("Field Change Review", content)
        self.assertIn("<td>Total Versions</td><td>1</td>", content)
        self.assertIn("<td>Version Transitions</td><td>0</td>", content)
        self.assertIn("<td>Changed Versions</td><td>0</td>", content)
        self.assertIn("<td>Unchanged Versions</td><td>1</td>", content)
        self.assertIn("<td>Field Changes</td><td>0</td>", content)
        self.assertIn("<td>Stable Fields</td><td>0</td>", content)
        self.assertIn(
            "<td>Change Log Classification</td><td>No Recorded Changes</td>",
            content,
        )
        self.assertIn("<td>No Transition</td>", content)
        self.assertIn("<td>Not Applicable</td>", content)
        self.assertIn("Record Evolution Trajectory", content)
        self.assertIn("Trajectory Summary", content)
        self.assertIn("Version Trajectory Review", content)
        self.assertIn("Supersession Trajectory Review", content)
        self.assertIn("Lineage Trajectory Review", content)
        self.assertIn("Timestamp Trajectory Review", content)
        self.assertIn("Verification Hash Trajectory Review", content)
        self.assertIn(
            "<td>Timestamp Order State</td><td>Missing Timestamp</td>",
            content,
        )
        self.assertIn(
            "<td>Verification Hash Coverage</td><td>Complete</td>",
            content,
        )
        self.assertIn(
            "<td>Trajectory Classification</td><td>Initial Evolution Trajectory</td>",
            content,
        )
        self.assertIn("Record Evolution Relationships", content)
        self.assertIn("Relationship Summary", content)
        self.assertIn("Version Relationship Review", content)
        self.assertIn("Supersession Relationship Review", content)
        self.assertIn("Timestamp Relationship Review", content)
        self.assertIn("Verification Relationship Review", content)
        self.assertIn("Evolution Relationship Review", content)
        self.assertIn(
            "Record evolution relationships are derived deterministically from existing record metadata, lineage history, continuity outputs, change log outputs, trajectory outputs, supersession fields, timestamps, and verification hashes only.",
            content,
        )
        self.assertIn("<td>Version Relationships</td><td>Single Version</td>", content)
        self.assertIn(
            "<td>Supersession Relationships</td><td>No Relationship</td>",
            content,
        )
        self.assertIn(
            "<td>Timestamp Relationships</td><td>Single Timestamp</td>",
            content,
        )
        self.assertIn(
            "<td>Verification Relationships</td><td>Complete Relationship</td>",
            content,
        )
        self.assertIn(
            "<td>Relationship Classification</td><td>No Evolution Relationships</td>",
            content,
        )
        self.assertIn("Record Evolution Traceability", content)
        self.assertIn("Traceability Summary", content)
        self.assertIn("Version Traceability Review", content)
        self.assertIn("Supersession Traceability Review", content)
        self.assertIn("Timestamp Traceability Review", content)
        self.assertIn("Verification Traceability Review", content)
        self.assertIn("Evolution Traceability Review", content)
        self.assertIn("<td>Traceable Versions</td><td>1</td>", content)
        self.assertIn("<td>Untraceable Versions</td><td>0</td>", content)
        self.assertIn("<td>Traceable Timestamps</td><td>0</td>", content)
        self.assertIn("<td>Missing Timestamps</td><td>1</td>", content)
        self.assertIn(
            "<td>Traceable Verification Hashes</td><td>1</td>",
            content,
        )
        self.assertIn("<td>Missing Verification Hashes</td><td>0</td>", content)
        self.assertIn(
            "<td>Traceability Classification</td><td>Untraceable Evolution</td>",
            content,
        )
        self.assertIn("Record Evolution Coverage", content)
        self.assertIn("Coverage Summary", content)
        self.assertIn("Version Coverage Review", content)
        self.assertIn("Supersession Coverage Review", content)
        self.assertIn("Timestamp Coverage Review", content)
        self.assertIn("Verification Coverage Review", content)
        self.assertIn("Evolution Output Coverage Review", content)
        self.assertIn("<td>Covered Versions</td><td>1</td>", content)
        self.assertIn("<td>Missing Versions</td><td>0</td>", content)
        self.assertIn("<td>Covered Supersession Links</td><td>0</td>", content)
        self.assertIn("<td>Missing Supersession Links</td><td>0</td>", content)
        self.assertIn("<td>Covered Timestamps</td><td>0</td>", content)
        self.assertIn("<td>Missing Timestamps</td><td>1</td>", content)
        self.assertIn("<td>Covered Verification Hashes</td><td>1</td>", content)
        self.assertIn("<td>Missing Verification Hashes</td><td>0</td>", content)
        self.assertIn("<td>Covered Evolution Outputs</td><td>6</td>", content)
        self.assertIn("<td>Missing Evolution Outputs</td><td>0</td>", content)
        self.assertIn(
            "<td>Coverage Classification</td><td>Limited Evolution Coverage</td>",
            content,
        )
        self.assertIn("Record Evolution Review", content)
        self.assertIn("Review Summary", content)
        self.assertIn("Version Review", content)
        self.assertIn("Evolution Output Review", content)
        self.assertIn("Coverage Review", content)
        self.assertIn("Traceability Review", content)
        self.assertIn("Relationship Review", content)
        self.assertIn("<td>Reviewable Versions</td><td>1</td>", content)
        self.assertIn("<td>Unreviewable Versions</td><td>0</td>", content)
        self.assertIn("<td>Reviewable Evolution Outputs</td><td>7</td>", content)
        self.assertIn("<td>Missing Evolution Outputs</td><td>0</td>", content)
        self.assertIn(
            "<td>Review Classification</td><td>Unresolved Evolution Review</td>",
            content,
        )
        self.assertIn("Record Evolution Readiness", content)
        self.assertIn("Readiness Summary", content)
        self.assertIn("Version Readiness Review", content)
        self.assertIn("Coverage Readiness Review", content)
        self.assertIn("Traceability Readiness Review", content)
        self.assertIn("Review Readiness Review", content)
        self.assertIn("Evolution Readiness Review", content)
        self.assertIn("<td>Reviewable Versions</td><td>1</td>", content)
        self.assertIn("<td>Traceable Versions</td><td>1</td>", content)
        self.assertIn("<td>Covered Versions</td><td>1</td>", content)
        self.assertIn("<td>Reviewable Evolution Outputs</td><td>8</td>", content)
        self.assertIn("<td>Missing Evolution Outputs</td><td>0</td>", content)
        self.assertIn(
            "<td>Readiness Classification</td><td>Unresolved Evolution Readiness</td>",
            content,
        )
        self.assertIn("Record Evolution Completeness", content)
        self.assertIn("Completeness Summary", content)
        self.assertIn("Version Completeness Review", content)
        self.assertIn("Evolution Output Completeness Review", content)
        self.assertIn("Coverage Completeness Review", content)
        self.assertIn("Review Completeness Review", content)
        self.assertIn("Readiness Completeness Review", content)
        self.assertIn("Evolution Completeness Review", content)
        self.assertIn("<td>Complete Versions</td><td>0</td>", content)
        self.assertIn("<td>Incomplete Versions</td><td>1</td>", content)
        self.assertIn("<td>Complete Evolution Outputs</td><td>9</td>", content)
        self.assertIn("<td>Missing Evolution Outputs</td><td>0</td>", content)
        self.assertIn(
            "<td>Completeness Classification</td><td>Unresolved Evolution Completeness</td>",
            content,
        )
        self.assertIn("Record Evolution Sufficiency", content)
        self.assertIn("Sufficiency Summary", content)
        self.assertIn("Version Sufficiency Review", content)
        self.assertIn("Evolution Output Sufficiency Review", content)
        self.assertIn("Coverage Sufficiency Review", content)
        self.assertIn("Review Sufficiency Review", content)
        self.assertIn("Readiness Sufficiency Review", content)
        self.assertIn("Completeness Sufficiency Review", content)
        self.assertIn("Evolution Sufficiency Review", content)
        self.assertIn("<td>Sufficient Versions</td><td>0</td>", content)
        self.assertIn("<td>Insufficient Versions</td><td>1</td>", content)
        self.assertIn("<td>Sufficient Evolution Outputs</td><td>10</td>", content)
        self.assertIn("<td>Missing Evolution Outputs</td><td>0</td>", content)
        self.assertIn(
            "<td>Sufficiency Classification</td><td>Unresolved Evolution Information</td>",
            content,
        )
        self.assertIn("Record Evolution Consistency", content)
        self.assertIn("Consistency Summary", content)
        self.assertIn("Version Consistency Review", content)
        self.assertIn("Supersession Consistency Review", content)
        self.assertIn("Timestamp Consistency Review", content)
        self.assertIn("Verification Consistency Review", content)
        self.assertIn("Evolution Output Consistency Review", content)
        self.assertIn("Evolution Consistency Review", content)
        self.assertIn("<td>Consistent Versions</td><td>1</td>", content)
        self.assertIn("<td>Inconsistent Versions</td><td>0</td>", content)
        self.assertIn(
            "<td>Consistent Supersession Links</td><td>0</td>",
            content,
        )
        self.assertIn(
            "<td>Inconsistent Supersession Links</td><td>0</td>",
            content,
        )
        self.assertIn("<td>Consistent Timestamps</td><td>0</td>", content)
        self.assertIn("<td>Inconsistent Timestamps</td><td>0</td>", content)
        self.assertIn(
            "<td>Consistent Verification Hashes</td><td>1</td>",
            content,
        )
        self.assertIn(
            "<td>Inconsistent Verification Hashes</td><td>0</td>",
            content,
        )
        self.assertIn(
            "<td>Consistent Evolution Outputs</td><td>11</td>",
            content,
        )
        self.assertIn(
            "<td>Inconsistent Evolution Outputs</td><td>0</td>",
            content,
        )
        self.assertIn("<td>Missing Evolution Outputs</td><td>0</td>", content)
        self.assertIn(
            "<td>Consistency Classification</td><td>Unresolved Evolution Consistency</td>",
            content,
        )
        self.assertIn("Record Evolution Integrity", content)
        self.assertIn("Integrity Summary", content)
        self.assertIn("Version Integrity Review", content)
        self.assertIn("Supersession Integrity Review", content)
        self.assertIn("Timestamp Integrity Review", content)
        self.assertIn("Verification Integrity Review", content)
        self.assertIn("Evolution Output Integrity Review", content)
        self.assertIn("Evolution Integrity Review", content)
        self.assertIn("<td>Intact Versions</td><td>1</td>", content)
        self.assertIn("<td>Broken Versions</td><td>0</td>", content)
        self.assertIn(
            "<td>Intact Supersession Links</td><td>0</td>",
            content,
        )
        self.assertIn(
            "<td>Broken Supersession Links</td><td>0</td>",
            content,
        )
        self.assertIn("<td>Intact Timestamps</td><td>0</td>", content)
        self.assertIn("<td>Broken Timestamps</td><td>0</td>", content)
        self.assertIn(
            "<td>Intact Verification Hashes</td><td>1</td>",
            content,
        )
        self.assertIn(
            "<td>Broken Verification Hashes</td><td>0</td>",
            content,
        )
        self.assertIn(
            "<td>Intact Evolution Outputs</td><td>12</td>",
            content,
        )
        self.assertIn(
            "<td>Broken Evolution Outputs</td><td>0</td>",
            content,
        )
        self.assertIn("<td>Missing Evolution Outputs</td><td>0</td>", content)
        self.assertIn(
            "<td>Integrity Classification</td><td>Unresolved Evolution Integrity</td>",
            content,
        )
        self.assertIn("Record Evolution Reliability", content)
        self.assertIn("Reliability Summary", content)
        self.assertIn("Version Reliability Review", content)
        self.assertIn("Supersession Reliability Review", content)
        self.assertIn("Timestamp Reliability Review", content)
        self.assertIn("Verification Reliability Review", content)
        self.assertIn("Evolution Output Reliability Review", content)
        self.assertIn("Evolution Reliability Review", content)
        self.assertIn("<td>Reliable Versions</td><td>1</td>", content)
        self.assertIn("<td>Unreliable Versions</td><td>0</td>", content)
        self.assertIn(
            "<td>Reliable Supersession Links</td><td>0</td>",
            content,
        )
        self.assertIn(
            "<td>Unreliable Supersession Links</td><td>0</td>",
            content,
        )
        self.assertIn("<td>Reliable Timestamps</td><td>0</td>", content)
        self.assertIn("<td>Unreliable Timestamps</td><td>0</td>", content)
        self.assertIn(
            "<td>Reliable Verification Hashes</td><td>1</td>",
            content,
        )
        self.assertIn(
            "<td>Unreliable Verification Hashes</td><td>0</td>",
            content,
        )
        self.assertIn(
            "<td>Reliable Evolution Outputs</td><td>13</td>",
            content,
        )
        self.assertIn(
            "<td>Unreliable Evolution Outputs</td><td>0</td>",
            content,
        )
        self.assertIn("<td>Missing Evolution Outputs</td><td>0</td>", content)
        self.assertIn(
            "<td>Reliability Classification</td><td>Unresolved Evolution Reliability</td>",
            content,
        )
        self.assertIn("Record Evolution Certification", content)
        self.assertIn("Certification Summary", content)
        self.assertIn("Version Certification Review", content)
        self.assertIn("Supersession Certification Review", content)
        self.assertIn("Timestamp Certification Review", content)
        self.assertIn("Verification Certification Review", content)
        self.assertIn("Evolution Output Certification Review", content)
        self.assertIn("Evolution Certification Review", content)
        self.assertIn("<td>Certifiable Versions</td><td>1</td>", content)
        self.assertIn("<td>Non-Certifiable Versions</td><td>0</td>", content)
        self.assertIn(
            "<td>Certifiable Supersession Links</td><td>0</td>",
            content,
        )
        self.assertIn(
            "<td>Non-Certifiable Supersession Links</td><td>0</td>",
            content,
        )
        self.assertIn("<td>Certifiable Timestamps</td><td>0</td>", content)
        self.assertIn("<td>Non-Certifiable Timestamps</td><td>0</td>", content)
        self.assertIn(
            "<td>Certifiable Verification Hashes</td><td>1</td>",
            content,
        )
        self.assertIn(
            "<td>Non-Certifiable Verification Hashes</td><td>0</td>",
            content,
        )
        self.assertIn(
            "<td>Certifiable Evolution Outputs</td><td>14</td>",
            content,
        )
        self.assertIn(
            "<td>Non-Certifiable Evolution Outputs</td><td>0</td>",
            content,
        )
        self.assertIn("<td>Missing Evolution Outputs</td><td>0</td>", content)
        self.assertIn(
            "<td>Certification Classification</td><td>Unresolved Evolution Certification</td>",
            content,
        )
        self.assertIn("Record Evolution Accreditation", content)
        self.assertIn("Accreditation Summary", content)
        self.assertIn("Version Accreditation Review", content)
        self.assertIn("Supersession Accreditation Review", content)
        self.assertIn("Timestamp Accreditation Review", content)
        self.assertIn("Verification Accreditation Review", content)
        self.assertIn("Evolution Output Accreditation Review", content)
        self.assertIn("Evolution Accreditation Review", content)
        self.assertIn("<td>Accreditable Versions</td><td>1</td>", content)
        self.assertIn("<td>Non-Accreditable Versions</td><td>0</td>", content)
        self.assertIn(
            "<td>Accreditable Supersession Links</td><td>0</td>",
            content,
        )
        self.assertIn(
            "<td>Non-Accreditable Supersession Links</td><td>0</td>",
            content,
        )
        self.assertIn("<td>Accreditable Timestamps</td><td>0</td>", content)
        self.assertIn("<td>Non-Accreditable Timestamps</td><td>0</td>", content)
        self.assertIn(
            "<td>Accreditable Verification Hashes</td><td>1</td>",
            content,
        )
        self.assertIn(
            "<td>Non-Accreditable Verification Hashes</td><td>0</td>",
            content,
        )
        self.assertIn(
            "<td>Accreditable Evolution Outputs</td><td>15</td>",
            content,
        )
        self.assertIn(
            "<td>Non-Accreditable Evolution Outputs</td><td>0</td>",
            content,
        )
        self.assertIn("<td>Missing Evolution Outputs</td><td>0</td>", content)
        self.assertIn(
            "<td>Accreditation Classification</td><td>Unresolved Evolution Accreditation</td>",
            content,
        )
        self.assertIn("Record Evolution Auditability", content)
        self.assertIn("Auditability Summary", content)
        self.assertIn("Version Auditability Review", content)
        self.assertIn("Supersession Auditability Review", content)
        self.assertIn("Timestamp Auditability Review", content)
        self.assertIn("Verification Auditability Review", content)
        self.assertIn("Evolution Output Auditability Review", content)
        self.assertIn("Evolution Auditability Review", content)
        self.assertIn("<td>Auditable Versions</td><td>1</td>", content)
        self.assertIn("<td>Non-Auditable Versions</td><td>0</td>", content)
        self.assertIn(
            "<td>Auditable Supersession Links</td><td>0</td>",
            content,
        )
        self.assertIn(
            "<td>Non-Auditable Supersession Links</td><td>0</td>",
            content,
        )
        self.assertIn("<td>Auditable Timestamps</td><td>0</td>", content)
        self.assertIn("<td>Non-Auditable Timestamps</td><td>0</td>", content)
        self.assertIn(
            "<td>Auditable Verification Hashes</td><td>1</td>",
            content,
        )
        self.assertIn(
            "<td>Non-Auditable Verification Hashes</td><td>0</td>",
            content,
        )
        self.assertIn(
            "<td>Auditable Evolution Outputs</td><td>16</td>",
            content,
        )
        self.assertIn(
            "<td>Non-Auditable Evolution Outputs</td><td>0</td>",
            content,
        )
        self.assertIn("<td>Missing Evolution Outputs</td><td>0</td>", content)
        self.assertIn(
            "<td>Auditability Classification</td><td>Unresolved Evolution Auditability</td>",
            content,
        )
        self.assertIn("Record Evolution Reproducibility", content)
        self.assertIn("Reproducibility Summary", content)
        self.assertIn("Version Reproducibility Review", content)
        self.assertIn("Supersession Reproducibility Review", content)
        self.assertIn("Timestamp Reproducibility Review", content)
        self.assertIn("Verification Reproducibility Review", content)
        self.assertIn("Evolution Output Reproducibility Review", content)
        self.assertIn("Evolution Reproducibility Review", content)
        self.assertIn("<td>Reproducible Versions</td><td>1</td>", content)
        self.assertIn("<td>Non-Reproducible Versions</td><td>0</td>", content)
        self.assertIn(
            "<td>Reproducible Supersession Links</td><td>0</td>",
            content,
        )
        self.assertIn(
            "<td>Non-Reproducible Supersession Links</td><td>0</td>",
            content,
        )
        self.assertIn("<td>Reproducible Timestamps</td><td>0</td>", content)
        self.assertIn("<td>Non-Reproducible Timestamps</td><td>0</td>", content)
        self.assertIn(
            "<td>Reproducible Verification Hashes</td><td>1</td>",
            content,
        )
        self.assertIn(
            "<td>Non-Reproducible Verification Hashes</td><td>0</td>",
            content,
        )
        self.assertIn(
            "<td>Reproducible Evolution Outputs</td><td>17</td>",
            content,
        )
        self.assertIn(
            "<td>Non-Reproducible Evolution Outputs</td><td>0</td>",
            content,
        )
        self.assertIn("<td>Missing Evolution Outputs</td><td>0</td>", content)
        self.assertIn(
            "<td>Reproducibility Classification</td><td>Non-Reproducible Evolution Chain</td>",
            content,
        )
        self.assertIn("Record Evolution Transparency", content)
        self.assertIn("Transparency Summary", content)
        self.assertIn("Version Transparency Review", content)
        self.assertIn("Supersession Transparency Review", content)
        self.assertIn("Timestamp Transparency Review", content)
        self.assertIn("Verification Transparency Review", content)
        self.assertIn("Evolution Output Transparency Review", content)
        self.assertIn("Evolution Transparency Review", content)
        self.assertIn("<td>Transparent Versions</td><td>1</td>", content)
        self.assertIn("<td>Non-Transparent Versions</td><td>0</td>", content)
        self.assertIn(
            "<td>Transparent Supersession Links</td><td>0</td>",
            content,
        )
        self.assertIn(
            "<td>Non-Transparent Supersession Links</td><td>0</td>",
            content,
        )
        self.assertIn("<td>Transparent Timestamps</td><td>0</td>", content)
        self.assertIn("<td>Non-Transparent Timestamps</td><td>0</td>", content)
        self.assertIn(
            "<td>Transparent Verification Hashes</td><td>1</td>",
            content,
        )
        self.assertIn(
            "<td>Non-Transparent Verification Hashes</td><td>0</td>",
            content,
        )
        self.assertIn(
            "<td>Transparent Evolution Outputs</td><td>17</td>",
            content,
        )
        self.assertIn(
            "<td>Non-Transparent Evolution Outputs</td><td>1</td>",
            content,
        )
        self.assertIn("<td>Missing Evolution Outputs</td><td>0</td>", content)
        self.assertIn(
            "<td>Transparency Classification</td><td>Non-Transparent Evolution Chain</td>",
            content,
        )
        self.assertIn("Record Evolution Accountability", content)
        self.assertIn("Accountability Summary", content)
        self.assertIn("Version Accountability Review", content)
        self.assertIn("Supersession Accountability Review", content)
        self.assertIn("Timestamp Accountability Review", content)
        self.assertIn("Verification Accountability Review", content)
        self.assertIn("Generated-By Accountability Review", content)
        self.assertIn("Evolution Output Accountability Review", content)
        self.assertIn("Evolution Accountability Review", content)
        self.assertIn("<td>Accountable Versions</td><td>1</td>", content)
        self.assertIn("<td>Non-Accountable Versions</td><td>0</td>", content)
        self.assertIn(
            "<td>Accountable Supersession Links</td><td>0</td>",
            content,
        )
        self.assertIn(
            "<td>Non-Accountable Supersession Links</td><td>0</td>",
            content,
        )
        self.assertIn("<td>Accountable Timestamps</td><td>0</td>", content)
        self.assertIn("<td>Non-Accountable Timestamps</td><td>0</td>", content)
        self.assertIn(
            "<td>Accountable Verification Hashes</td><td>1</td>",
            content,
        )
        self.assertIn(
            "<td>Non-Accountable Verification Hashes</td><td>0</td>",
            content,
        )
        self.assertIn(
            "<td>Accountable Generated-By Values</td><td>0</td>",
            content,
        )
        self.assertIn(
            "<td>Non-Accountable Generated-By Values</td><td>0</td>",
            content,
        )
        self.assertIn("<td>Missing Generated-By Values</td><td>1</td>", content)
        self.assertIn(
            "<td>Accountable Evolution Outputs</td><td>17</td>",
            content,
        )
        self.assertIn(
            "<td>Non-Accountable Evolution Outputs</td><td>2</td>",
            content,
        )
        self.assertIn("<td>Missing Evolution Outputs</td><td>0</td>", content)
        self.assertIn(
            "<td>Accountability Classification</td><td>Non-Accountable Evolution Chain</td>",
            content,
        )
        self.assertIn("Determination Trace", content)
        self.assertIn("Trace Summary", content)
        self.assertIn("Visible Record", content)
        self.assertIn("Observed Evidence", content)
        self.assertIn("Applied Rules", content)
        self.assertIn("Trace Path", content)
        self.assertIn("Limitations", content)
        self.assertIn(
            "<td>Determination</td><td>Determination derived from visible record evolution</td>",
            content,
        )
        self.assertIn("<td>Conditions Count</td><td>5</td>", content)
        self.assertIn("<td>Trace Steps Count</td><td>6</td>", content)
        self.assertIn("Rule Citation Layer", content)
        self.assertIn("Citation Summary", content)
        self.assertIn("Rule Family Citations", content)
        self.assertIn("Condition Citations", content)
        self.assertIn("Trajectory Citations", content)
        self.assertIn("Administrative Citations", content)
        self.assertIn("Record Evolution Citations", content)
        self.assertIn("Citation Path", content)
        self.assertIn(
            "<td>Citation State</td><td>Rule Citation Layer Available</td>",
            content,
        )
        self.assertIn("Evidence Attribution Matrix", content)
        self.assertIn("Attribution Summary", content)
        self.assertIn("Evidence Sources", content)
        self.assertIn("Condition Attribution", content)
        self.assertIn("Trajectory Attribution", content)
        self.assertIn("Administrative Attribution", content)
        self.assertIn("Record Evolution Attribution", content)
        self.assertIn("Determination Trace Attribution", content)
        self.assertIn("Rule Citation Attribution", content)
        self.assertIn("Unsupported Outputs", content)
        self.assertIn("Attribution Path", content)
        self.assertIn(
            "<td>Attribution State</td><td>Evidence Attribution Matrix Available</td>",
            content,
        )
        self.assertIn("Determination Report", content)
        self.assertIn("Report Overview", content)
        self.assertIn("Report Summary", content)
        self.assertIn("Report Sections", content)
        self.assertIn("Report Path", content)
        self.assertIn(
            "<td>Report State</td><td>Determination Report Available</td>",
            content,
        )
        self.assertIn("Sufficiency Boundaries", content)
        self.assertIn("Boundary Overview", content)
        self.assertIn("Boundary Summary", content)
        self.assertIn("Supported Outputs", content)
        self.assertIn("Partially Supported Outputs", content)
        self.assertIn("Unsupported Outputs", content)
        self.assertIn("Boundary Path", content)
        self.assertIn(
            "<td>Boundary State</td><td>Sufficiency Boundaries Available</td>",
            content,
        )
        self.assertIn("Counterfactual Visibility", content)
        self.assertIn("Visibility Summary", content)
        self.assertIn("Visible Layers", content)
        self.assertIn("Non-Visible Layers", content)
        self.assertIn("Visible Evidence Elements", content)
        self.assertIn("Non-Visible Evidence Elements", content)
        self.assertIn("Counterfactual Path", content)
        self.assertIn(
            "<td>Visibility State</td><td>Counterfactual Visibility Available</td>",
            content,
        )
        self.assertIn("Explainability Certification", content)
        self.assertIn("Certification Overview", content)
        self.assertIn("Certification Summary", content)
        self.assertIn("Certified Components", content)
        self.assertIn("Partially Certified Components", content)
        self.assertIn("Uncertified Components", content)
        self.assertIn("Certification Path", content)
        self.assertIn(
            "<td>Certification State</td><td>Explainability Certified</td>",
            content,
        )
        self.assertIn("Framework Self-Description", content)
        self.assertIn("Framework Description", content)
        self.assertIn("Framework Identity", content)
        self.assertIn("Purpose Description", content)
        self.assertIn("Scope Description", content)
        self.assertIn("Framework Architecture", content)
        self.assertIn("Framework Guarantees", content)
        self.assertIn("Framework Constraints", content)
        self.assertIn("Framework Limitations", content)
        self.assertIn("Reflexive Methodology", content)
        self.assertIn("Self-Description Path", content)
        self.assertIn(
            "<td>Reflexive Methodology State</td><td>Framework Self-Description Available</td>",
            content,
        )
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
        self.assertLess(
            governance_content.index("<h2>Record Governance Trajectory</h2>"),
            governance_content.index("<h2>Governance Pattern Detection</h2>"),
        )
        self.assertLess(
            governance_content.index("<h2>Governance Pattern Detection</h2>"),
            governance_content.index("<h2>Governance Consistency</h2>"),
        )
        self.assertLess(
            governance_content.index("<h2>Governance Consistency</h2>"),
            governance_content.index("<h2>Governance Relationships</h2>"),
        )
        self.assertLess(
            governance_content.index("<h2>Governance Relationships</h2>"),
            governance_content.index("<h2>Governance Traceability</h2>"),
        )
        self.assertLess(
            governance_content.index("<h2>Governance Traceability</h2>"),
            governance_content.index("<h2>Governance Coverage</h2>"),
        )
        self.assertLess(
            governance_content.index("<h2>Governance Coverage</h2>"),
            governance_content.index("<h2>Governance Chain Review</h2>"),
        )
        self.assertLess(
            governance_content.index("<h2>Governance Chain Review</h2>"),
            governance_content.index("<h2>Record Evolution Summary</h2>"),
        )
        self.assertLess(
            governance_content.index("<h2>Record Evolution Summary</h2>"),
            governance_content.index("<h2>Record Evolution Continuity</h2>"),
        )
        self.assertLess(
            governance_content.index("<h2>Record Evolution Continuity</h2>"),
            governance_content.index("<h2>Record Evolution Change Log</h2>"),
        )
        self.assertLess(
            governance_content.index("<h2>Record Evolution Change Log</h2>"),
            governance_content.index("<h2>Record Evolution Trajectory</h2>"),
        )
        self.assertLess(
            governance_content.index("<h2>Record Evolution Trajectory</h2>"),
            governance_content.index("<h2>Record Evolution Relationships</h2>"),
        )
        self.assertLess(
            governance_content.index("<h2>Record Evolution Relationships</h2>"),
            governance_content.index("<h2>Record Evolution Traceability</h2>"),
        )
        self.assertLess(
            governance_content.index("<h2>Record Evolution Traceability</h2>"),
            governance_content.index("<h2>Record Evolution Coverage</h2>"),
        )
        self.assertLess(
            governance_content.index("<h2>Record Evolution Coverage</h2>"),
            governance_content.index("<h2>Record Evolution Review</h2>"),
        )
        self.assertLess(
            governance_content.index("<h2>Record Evolution Review</h2>"),
            governance_content.index("<h2>Record Evolution Readiness</h2>"),
        )
        self.assertLess(
            governance_content.index("<h2>Record Evolution Readiness</h2>"),
            governance_content.index("<h2>Record Evolution Completeness</h2>"),
        )
        self.assertLess(
            governance_content.index("<h2>Record Evolution Completeness</h2>"),
            governance_content.index("<h2>Record Evolution Sufficiency</h2>"),
        )
        self.assertLess(
            governance_content.index("<h2>Record Evolution Sufficiency</h2>"),
            governance_content.index("<h2>Record Evolution Consistency</h2>"),
        )
        self.assertLess(
            governance_content.index("<h2>Record Evolution Consistency</h2>"),
            governance_content.index("<h2>Record Evolution Integrity</h2>"),
        )
        self.assertLess(
            governance_content.index("<h2>Record Evolution Integrity</h2>"),
            governance_content.index("<h2>Record Evolution Reliability</h2>"),
        )
        self.assertLess(
            governance_content.index("<h2>Record Evolution Reliability</h2>"),
            governance_content.index("<h2>Record Evolution Certification</h2>"),
        )
        self.assertLess(
            governance_content.index("<h2>Record Evolution Certification</h2>"),
            governance_content.index("<h2>Record Evolution Accreditation</h2>"),
        )
        self.assertLess(
            governance_content.index("<h2>Record Evolution Accreditation</h2>"),
            governance_content.index("<h2>Record Evolution Auditability</h2>"),
        )
        self.assertLess(
            governance_content.index("<h2>Record Evolution Auditability</h2>"),
            governance_content.index("<h2>Record Evolution Reproducibility</h2>"),
        )
        self.assertLess(
            governance_content.index("<h2>Record Evolution Reproducibility</h2>"),
            governance_content.index("<h2>Record Evolution Transparency</h2>"),
        )
        self.assertLess(
            governance_content.index("<h2>Record Evolution Transparency</h2>"),
            governance_content.index("<h2>Record Evolution Accountability</h2>"),
        )
        self.assertLess(
            governance_content.index("<h2>Record Evolution Accountability</h2>"),
            governance_content.index("<h2>Determination Trace</h2>"),
        )
        self.assertLess(
            governance_content.index("<h2>Determination Trace</h2>"),
            governance_content.index("<h2>Rule Citation Layer</h2>"),
        )
        self.assertLess(
            governance_content.index("<h2>Rule Citation Layer</h2>"),
            governance_content.index("<h2>Evidence Attribution Matrix</h2>"),
        )
        self.assertLess(
            governance_content.index("<h2>Evidence Attribution Matrix</h2>"),
            governance_content.index("<h2>Determination Report</h2>"),
        )
        self.assertLess(
            governance_content.index("<h2>Determination Report</h2>"),
            governance_content.index("<h2>Sufficiency Boundaries</h2>"),
        )
        self.assertLess(
            governance_content.index("<h2>Sufficiency Boundaries</h2>"),
            governance_content.index("<h2>Counterfactual Visibility</h2>"),
        )
        self.assertLess(
            governance_content.index("<h2>Counterfactual Visibility</h2>"),
            governance_content.index("<h2>Explainability Certification</h2>"),
        )
        self.assertLess(
            governance_content.index("<h2>Explainability Certification</h2>"),
            governance_content.index(
                "<h2>Framework Self-Description &amp; Reflexive Methodology</h2>"
            ),
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
            "<h2>Governance Pattern Detection</h2>",
            print_governance_content,
        )
        self.assertIn("<h2>Governance Consistency</h2>", print_governance_content)
        self.assertIn("<h2>Governance Relationships</h2>", print_governance_content)
        self.assertIn("<h2>Governance Traceability</h2>", print_governance_content)
        self.assertIn("<h2>Governance Coverage</h2>", print_governance_content)
        self.assertIn("<h2>Governance Chain Review</h2>", print_governance_content)
        self.assertIn("<h2>Record Evolution Summary</h2>", print_governance_content)
        self.assertIn("<h2>Record Evolution Continuity</h2>", print_governance_content)
        self.assertIn("<h2>Record Evolution Change Log</h2>", print_governance_content)
        self.assertIn("<h2>Record Evolution Trajectory</h2>", print_governance_content)
        self.assertIn("<h2>Record Evolution Relationships</h2>", print_governance_content)
        self.assertIn("<h2>Record Evolution Traceability</h2>", print_governance_content)
        self.assertIn("<h2>Record Evolution Coverage</h2>", print_governance_content)
        self.assertIn("<h2>Record Evolution Review</h2>", print_governance_content)
        self.assertIn("<h2>Record Evolution Readiness</h2>", print_governance_content)
        self.assertIn("<h2>Record Evolution Completeness</h2>", print_governance_content)
        self.assertIn("<h2>Record Evolution Sufficiency</h2>", print_governance_content)
        self.assertIn("<h2>Record Evolution Consistency</h2>", print_governance_content)
        self.assertIn("<h2>Record Evolution Integrity</h2>", print_governance_content)
        self.assertIn("<h2>Record Evolution Reliability</h2>", print_governance_content)
        self.assertIn("<h2>Record Evolution Certification</h2>", print_governance_content)
        self.assertIn("<h2>Record Evolution Accreditation</h2>", print_governance_content)
        self.assertIn("<h2>Record Evolution Auditability</h2>", print_governance_content)
        self.assertIn("<h2>Record Evolution Reproducibility</h2>", print_governance_content)
        self.assertIn("<h2>Record Evolution Transparency</h2>", print_governance_content)
        self.assertIn("<h2>Record Evolution Accountability</h2>", print_governance_content)
        self.assertIn("<h2>Determination Trace</h2>", print_governance_content)
        self.assertIn("<h3>Trace Summary</h3>", print_governance_content)
        self.assertIn("<h3>Trace Path</h3>", print_governance_content)
        self.assertIn("<h3>Limitations</h3>", print_governance_content)
        self.assertIn("<h2>Rule Citation Layer</h2>", print_governance_content)
        self.assertIn("<h3>Citation Summary</h3>", print_governance_content)
        self.assertIn("<h3>Citation Path</h3>", print_governance_content)
        self.assertIn(
            "<h2>Evidence Attribution Matrix</h2>",
            print_governance_content,
        )
        self.assertIn("<h3>Attribution Summary</h3>", print_governance_content)
        self.assertIn("<h3>Evidence Sources</h3>", print_governance_content)
        self.assertIn("<h3>Attribution Path</h3>", print_governance_content)
        self.assertIn("<h2>Determination Report</h2>", print_governance_content)
        self.assertIn("<h3>Report Overview</h3>", print_governance_content)
        self.assertIn("<h3>Report Sections</h3>", print_governance_content)
        self.assertIn("<h3>Report Path</h3>", print_governance_content)
        self.assertIn("<h2>Sufficiency Boundaries</h2>", print_governance_content)
        self.assertIn("<h3>Boundary Overview</h3>", print_governance_content)
        self.assertIn("<h3>Boundary Summary</h3>", print_governance_content)
        self.assertIn("<h3>Boundary Path</h3>", print_governance_content)
        self.assertIn("<h2>Counterfactual Visibility</h2>", print_governance_content)
        self.assertIn("<h3>Visibility Summary</h3>", print_governance_content)
        self.assertIn("<h3>Visible Layers</h3>", print_governance_content)
        self.assertIn("<h3>Non-Visible Layers</h3>", print_governance_content)
        self.assertIn("<h3>Counterfactual Path</h3>", print_governance_content)
        self.assertIn("<h2>Explainability Certification</h2>", print_governance_content)
        self.assertIn("<h3>Certification Overview</h3>", print_governance_content)
        self.assertIn("<h3>Certification Summary</h3>", print_governance_content)
        self.assertIn("<h3>Certification Path</h3>", print_governance_content)
        self.assertIn(
            "<h2>Framework Self-Description &amp; Reflexive Methodology</h2>",
            print_governance_content,
        )
        self.assertIn(
            "<h3>Framework Self-Description Summary</h3>",
            print_governance_content,
        )
        self.assertIn("<h3>Framework Description</h3>", print_governance_content)
        self.assertIn("<h3>Framework Architecture</h3>", print_governance_content)
        self.assertIn("<h3>Framework Guarantees</h3>", print_governance_content)
        self.assertIn("<h3>Framework Constraints</h3>", print_governance_content)
        self.assertIn("<h3>Framework Limitations</h3>", print_governance_content)
        self.assertIn("<h3>Self-Description Path</h3>", print_governance_content)
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
