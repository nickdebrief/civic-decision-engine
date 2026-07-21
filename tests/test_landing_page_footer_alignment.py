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

    @staticmethod
    def footer_region(content: str, class_name: str) -> str:
        start_marker = f'<div class="{class_name}">'
        start = content.index(start_marker)
        end = content.index("</div>", start)
        return content[start:end]

    def test_landing_footer_shares_landing_application_wrapper(self):
        content = self.public_index_html()
        wrap_start = content.index('<div class="wrap">')
        main_start = content.index('<main class="landing-application">')
        main_end = content.index("</main>")
        footer_start = content.index('<footer class="public-footer">')
        footer_end = content.index("</footer>", footer_start)
        wrap_end = content.index("</div>", footer_end)
        self.assertLess(wrap_start, footer_start)
        self.assertLess(wrap_start, main_start)
        self.assertLess(main_start, main_end)
        self.assertLess(main_end, footer_start)
        self.assertLess(footer_start, wrap_end)
        self.assertLess(footer_end, wrap_end)
        self.assertLess(wrap_end, content.index("</body>"))

    def test_landing_footer_uses_parent_container_without_nested_grid(self):
        content = self.public_index_html()
        wrap_rule = self.css_rule(content, ".wrap")
        footer_rule = self.css_rule(content, ".public-footer")
        self.assertIn("max-width: 1400px;", wrap_rule)
        self.assertIn("padding: 40px 24px 64px;", wrap_rule)
        self.assertIn("width: 100%;", footer_rule)
        self.assertIn("display: grid;", footer_rule)
        self.assertIn("grid-template-columns: minmax(0, 1fr) minmax(220px, auto);", footer_rule)
        self.assertNotIn("max-width: 1400px;", footer_rule)
        self.assertNotIn("margin-left: auto;", footer_rule)
        self.assertNotIn("margin-right: auto;", footer_rule)
        self.assertNotIn('class="public-footer-wrap"', content)

    def test_landing_footer_has_two_semantic_regions(self):
        content = self.public_index_html()
        primary = self.footer_region(content, "public-footer__primary")
        identity = self.footer_region(content, "public-footer__identity")
        self.assertIn("Nick Moloney. All rights reserved.", primary)
        self.assertIn("Public attachment metadata", primary)
        self.assertIn('aria-label="Archive links"', primary)
        self.assertIn('href="/documents"', primary)
        self.assertIn("Civic Decision Engine", identity)
        self.assertIn("Independent &middot; Transparent &middot; Traceable", identity)
        self.assertIn("Platform version v13.0", identity)
        self.assertIn('href="/admin"', identity)
        self.assertNotIn('href="/admin"', primary)
        self.assertNotIn('class="public-footer__standalone-admin"', content)

    def test_landing_footer_responsive_single_column_rule_exists(self):
        content = self.public_index_html()
        self.assertIn("@media (max-width: 700px)", content)
        self.assertIn(".public-footer {\n        grid-template-columns: 1fr;", content)
        self.assertIn(".public-footer__identity {\n        align-items: flex-start;", content)

    def test_landing_application_markup_remains_intact(self):
        content = self.public_index_html()
        main_start = content.index('<main class="landing-application">')
        main_end = content.index("</main>")
        application_markup = content[main_start:main_end]
        self.assertIn('<section class="hero">', application_markup)
        self.assertIn('<section class="grid">', application_markup)
        self.assertIn('<div class="panel" id="inputPanel">', application_markup)
        self.assertIn('<div class="panel" id="outputPanel">', application_markup)
        self.assertNotIn('<footer class="public-footer">', application_markup)

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
