import os
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.test_admin_session import FakeRequest, install_fastapi_stubs

install_fastapi_stubs()

from api.platform_identity import (
    PLATFORM_NAME,
    PLATFORM_SHORT_NAME,
    PLATFORM_TAGLINE,
    PLATFORM_VERSION,
    PLATFORM_VERSION_LABEL,
    platform_page_title,
)
from api.public_navigation import public_primary_navigation
from api.routes import admin_session


README = Path("README.md")
PUBLIC_INDEX = Path("api/static/index.html")
RELEASE_NOTE = Path("docs/releases/CDE_V13_A_PLATFORM_IDENTITY_TRANSITION.md")


class PlatformIdentityTransitionTests(unittest.TestCase):
    def test_canonical_identity_constants(self):
        self.assertEqual(PLATFORM_NAME, "Civic Decision Engine")
        self.assertEqual(PLATFORM_SHORT_NAME, "CDE")
        self.assertEqual(PLATFORM_VERSION, "13.0")
        self.assertEqual(PLATFORM_VERSION_LABEL, "v13.0")
        self.assertEqual(PLATFORM_TAGLINE, "Independent · Transparent · Traceable")
        self.assertEqual(
            platform_page_title("Public Archive Explorer"),
            "Public Archive Explorer — Civic Decision Engine",
        )

    def test_public_navigation_renders_canonical_identity(self):
        html = public_primary_navigation(active="archive")
        self.assertIn('aria-label="Civic Decision Engine home"', html)
        self.assertIn(">CDE</span>", html)
        self.assertIn("Civic Decision Engine", html)
        self.assertIn("Independent · Transparent · Traceable", html)
        self.assertIn("Platform version v13.0", html)
        self.assertIn('href="/archive" aria-current="page"', html)
        self.assertNotIn("Civic Decisions Engine", html)
        self.assertNotIn("C.D.E.", html)

    def test_homepage_footer_uses_v13_identity(self):
        content = PUBLIC_INDEX.read_text(encoding="utf-8")
        self.assertIn(
            "Civic Decision Engine &mdash; Independent &middot; Transparent &middot; Traceable &mdash; Platform version v13.0",
            content,
        )
        self.assertIn("civic-decision-engine v13.0", content)
        self.assertIn("Civic Decision Engine v13.0", content)
        self.assertIn('href="/admin" target="_blank" rel="noopener noreferrer">Administration</a>', content)
        self.assertNotIn("Civic Decisions Engine", content)

    def test_admin_console_renders_identity_without_removing_navigation(self):
        with patch.dict(
            os.environ,
            {
                "ADMIN_USERNAME": "admin-user",
                "ADMIN_PASSWORD": "admin-password",
                "CDE_ADMIN_SESSION_SECRET": "session-secret",
            },
            clear=False,
        ):
            session = admin_session.create_admin_session("admin-user")
            response = admin_session.admin_dashboard_page(
                FakeRequest(cookies={admin_session.SESSION_COOKIE_NAME: session})
            )
        self.assertIn("Civic Decision Engine", response.content)
        self.assertIn("Independent · Transparent · Traceable", response.content)
        self.assertIn("Platform version v13.0", response.content)
        self.assertIn("CDE Administration Console", response.content)
        self.assertIn('href="/archive">Public Archive Explorer</a>', response.content)
        self.assertIn('href="/documents">Public Document Library</a>', response.content)
        self.assertIn("Signed in as:", response.content)

    def test_release_documentation_records_identity_transition(self):
        readme = README.read_text(encoding="utf-8")
        release_note = RELEASE_NOTE.read_text(encoding="utf-8")
        self.assertIn("Current release: v13.0.1", readme)
        self.assertIn("### CDE v13.0 — Governed Public Transmissions", readme)
        self.assertIn("### CDE v13.A — Platform Identity Transition", readme)
        self.assertIn(
            "Platform identity should reflect the governance architecture without changing it.",
            readme,
        )
        self.assertIn(
            "v13.A prepares the Civic Decision Engine for the v13 era. It does not introduce Governed Public Transmissions.",
            release_note,
        )
        self.assertIn("## Governance Invariants", release_note)

    def test_historical_v12_references_remain_historical(self):
        readme = README.read_text(encoding="utf-8")
        self.assertIn("## What v12 introduces", readme)
        self.assertIn("### CDE v12.28 — Public Document Preview Enhancements", readme)
        self.assertIn("docs/releases/README_v12.md", readme)


if __name__ == "__main__":
    unittest.main()
