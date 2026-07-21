import os
from pathlib import Path
from unittest.mock import patch

from tests.test_admin_session import FakeRequest
from tests.test_governed_public_transmissions import GovernedPublicTransmissionTests

from api.platform_identity import PLATFORM_VERSION_LABEL
from api.public_navigation import public_primary_navigation
from api.routes import admin_session, transmissions


README = Path("README.md")
PUBLIC_INDEX = Path("api/static/index.html")
RELEASE_NOTE = Path("docs/releases/CDE_V13_0_1_PUBLIC_TRANSMISSION_UX_REFINEMENTS.md")


class PublicTransmissionUxRefinementTests(GovernedPublicTransmissionTests):
    def test_active_platform_identity_renders_v13_0(self):
        self.assertEqual(PLATFORM_VERSION_LABEL, "v13.0")
        navigation = public_primary_navigation(active="transmissions")
        self.assertIn("Platform version v13.0", navigation)
        self.assertNotIn("Platform version v13.A", navigation)

    def test_homepage_footer_alignment_and_identity(self):
        content = PUBLIC_INDEX.read_text(encoding="utf-8")
        self.assertIn("Platform version v13.0", content)
        self.assertIn("max-width: 1400px;", content)
        self.assertIn("margin-left: auto;", content)
        self.assertIn("margin-right: auto;", content)
        self.assertIn("min-width: 0;", content)

    def test_admin_dashboard_card_uses_refined_transmission_title(self):
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
        self.assertIn("<h2>Transmissions</h2>", response.content)
        self.assertNotIn("<h2>Public Transmissions</h2>", response.content)
        self.assertIn("Open Transmission Intake", response.content)

    def test_transmission_pages_use_included_governed_object_language(self):
        index = transmissions.public_transmission_library().content
        detail = transmissions.public_transmission_page(self.transmission["public_reference"]).content
        admin_detail = admin_session._render_transmission_admin_detail(
            self.transmission,
            self.attachments,
            [],
            admin_session={"username": "admin-user"},
        )
        combined = index + detail + admin_detail
        self.assertIn("Included governed objects", combined)
        self.assertIn("Included governed objects remain independently governed", combined)
        self.assertIn("Each referenced object keeps its own identity", combined)
        self.assertNotIn("Transmission contents", combined)
        self.assertNotIn("enclosed files", combined)
        self.assertNotIn("bundled", combined)

    def test_release_documentation_records_refinement_without_governance_change(self):
        readme = README.read_text(encoding="utf-8")
        release_note = RELEASE_NOTE.read_text(encoding="utf-8")
        self.assertIn("Current release: v13.0.1", readme)
        self.assertIn("### CDE v13.0.1 — Public Transmission UX Refinements", readme)
        self.assertIn("Refinement improves clarity without changing governance.", release_note)
        self.assertIn("No\nmigration is introduced.", release_note)
