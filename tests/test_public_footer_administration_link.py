import os
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.test_admin_session import FakeHTTPException, FakeRequest, install_fastapi_stubs

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
        self.assertIn('<a class="public-footer-link" href="/admin">Administration</a>', content)
        self.assertLess(
            content.index('Civic Decision Engine v12 &mdash;'),
            content.index('href="/admin">Administration</a>'),
        )

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

    def test_unauthenticated_admin_behavior_remains_unchanged(self):
        with self.assertRaises(FakeHTTPException) as ctx:
            admin_session.admin_dashboard_page(FakeRequest())
        self.assertEqual(ctx.exception.status_code, 401)

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
