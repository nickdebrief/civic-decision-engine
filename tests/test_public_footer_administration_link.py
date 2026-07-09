import os
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.test_admin_session import FakeRequest, install_fastapi_stubs

install_fastapi_stubs()

from api.routes import admin_session


PUBLIC_INDEX = Path("api/static/index.html")


class PublicFooterAdministrationLinkTests(unittest.TestCase):
    @staticmethod
    def public_index_html():
        return PUBLIC_INDEX.read_text(encoding="utf-8")

    def test_public_footer_contains_discreet_administration_link(self):
        content = self.public_index_html()
        self.assertIn('<div class="public-footer-right">', content)
        self.assertIn('Civic Decision Engine v12 &mdash;', content)
        self.assertIn('<span data-i18n="hero_record">The record does not argue.</span>', content)
        self.assertIn('<a class="public-footer-link" href="/admin" target="_blank" rel="noopener noreferrer">Administration</a>', content)
        self.assertIn('.public-footer-link {\n      font-size: 0.82rem;', content)
        self.assertLess(
            content.index('Civic Decision Engine v12 &mdash;'),
            content.index('href="/admin" target="_blank" rel="noopener noreferrer">Administration</a>'),
        )

    def test_administration_link_has_required_target_attributes(self):
        content = self.public_index_html()
        self.assertIn('class="public-footer-link" href="/admin"', content)
        self.assertIn('target="_blank"', content)
        self.assertIn('rel="noopener noreferrer"', content)

    def test_existing_public_footer_navigation_remains_present(self):
        content = self.public_index_html()
        for href, label in (
            ('/records', 'Records'),
            ('/conditions', 'Conditions'),
            ('/patterns', 'Patterns'),
            ('/stats', 'Stats'),
            ('/graph', 'Graph'),
            ('/api/docs', 'API docs'),
        ):
            with self.subTest(label=label):
                self.assertIn(f'href="{href}"', content)
                self.assertIn(f'>{label}</a>', content)

    def test_footer_does_not_expose_private_administrative_state(self):
        footer = self.public_index_html().split('<footer class="public-footer">', 1)[1]
        for private_text in (
            'Pending Intake',
            'Under Review',
            'Approved',
            'Archived',
            'Rejected',
            'Review Queue',
            'private intake',
            'lifecycle count',
        ):
            with self.subTest(private_text=private_text):
                self.assertNotIn(private_text, footer)

    def test_unauthenticated_admin_link_route_renders_login_ui(self):
        response = admin_session.admin_dashboard_page(FakeRequest())
        self.assertIn("Civic Decision Engine Admin", response.content)
        self.assertIn('type="password"', response.content)
        self.assertIn('/api/admin/session/login', response.content)
        self.assertNotIn('{"detail":"admin_session_unauthorized"}', response.content)

    def test_authenticated_admin_behavior_remains_unchanged(self):
        with patch.dict(
            os.environ,
            {
                'CDE_ADMIN_PASSWORD': 'admin-password',
                'CDE_ADMIN_SESSION_SECRET': 'session-secret',
            },
            clear=False,
        ):
            session = admin_session.create_admin_session()
            response = admin_session.admin_dashboard_page(
                FakeRequest(cookies={admin_session.SESSION_COOKIE_NAME: session})
            )
        self.assertIn('CDE Administration Console', response.content)
        self.assertIn('href="/admin/document-intake#new-intake"', response.content)


if __name__ == "__main__":
    unittest.main()
