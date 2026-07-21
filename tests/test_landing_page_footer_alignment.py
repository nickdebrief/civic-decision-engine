import re
import unittest
from pathlib import Path

from api.public_navigation import public_footer, public_primary_navigation


PUBLIC_INDEX = Path("api/static/index.html")


class LandingPageFooterAlignmentTests(unittest.TestCase):
    @staticmethod
    def public_index_html() -> str:
        return PUBLIC_INDEX.read_text(encoding="utf-8")

    @staticmethod
    def css_rule(content: str, selector: str) -> str:
        match = re.search(rf"{re.escape(selector)}\s*\{{(?P<body>.*?)\n\s*\}}", content, flags=re.DOTALL)
        if not match:
            raise AssertionError(f"Missing CSS selector: {selector}")
        return match.group("body")

    def test_landing_footer_is_inside_primary_wrap(self):
        content = self.public_index_html()
        wrap_start = content.index('<div class="wrap">')
        footer_start = content.index('<footer class="public-footer">')
        wrap_end = content.index("</body>")
        self.assertLess(wrap_start, footer_start)
        self.assertLess(footer_start, wrap_end)

    def test_landing_footer_uses_parent_content_grid(self):
        content = self.public_index_html()
        wrap_rule = self.css_rule(content, ".wrap")
        footer_rule = self.css_rule(content, ".public-footer")
        self.assertIn("max-width: 1400px;", wrap_rule)
        self.assertIn("padding: 40px 24px 64px;", wrap_rule)
        self.assertIn("width: 100%;", footer_rule)
        self.assertNotIn("max-width: 1400px;", footer_rule)
        self.assertNotIn("margin-left: auto;", footer_rule)
        self.assertNotIn("margin-right: auto;", footer_rule)

    def test_landing_footer_identity_and_links_remain_present(self):
        content = self.public_index_html()
        self.assertIn("Platform version v13.0", content)
        for href, label in (
            ("/archive", "Archive"),
            ("/records", "Records"),
            ("/documents", "Public Document Library"),
            ("/transmissions", "Public Transmission Library"),
            ("/admin", "Administration"),
        ):
            with self.subTest(label=label):
                self.assertIn(f'href="{href}"', content)
                self.assertIn(label, content)

    def test_shared_public_footer_and_navigation_are_unchanged(self):
        footer = public_footer()
        navigation = public_primary_navigation(active="archive")
        self.assertIn("Platform version v13.0", footer)
        self.assertIn('href="/archive" aria-current="page"', navigation)
        self.assertIn('href="/transmissions"', navigation)


if __name__ == "__main__":
    unittest.main()
