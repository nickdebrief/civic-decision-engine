import re
import unittest

from tests.test_admin_session import install_fastapi_stubs

install_fastapi_stubs()

from api.routes import admin_session


def _relative_luminance(colour: str) -> float:
    channels = [int(colour[index : index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [
        channel / 12.92
        if channel <= 0.04045
        else ((channel + 0.055) / 1.055) ** 2.4
        for channel in channels
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast_ratio(foreground: str, background: str) -> float:
    lighter, darker = sorted(
        (_relative_luminance(foreground), _relative_luminance(background)),
        reverse=True,
    )
    return (lighter + 0.05) / (darker + 0.05)


class AuthoritativeSourceVisualEmphasisTests(unittest.TestCase):
    def setUp(self):
        self.source_id = "source-document-id"
        self.html = admin_session._render_association_form_page(
            admin_session={"username": "admin-user"},
            records=[
                {
                    "reference": "CARE-CROOM-20180619-001",
                    "record_type": "clinical_episode",
                    "record_title": "Croom Admission Clinical Episode",
                    "institution": "Croom Hospital",
                    "authoritative_source_document": {
                        "intake_id": self.source_id,
                        "title": "Croom Admission – 19 June 2018",
                        "document_identifier": "DOC-2026-000118",
                        "source_document_available": True,
                    },
                }
            ],
            documents=[],
        )

    def test_panel_and_primary_evidence_badge_render(self):
        self.assertIn('class="authoritative-source-context"', self.html)
        self.assertIn('class="authoritative-source-badge">Primary evidence</span>', self.html)

    def test_accessible_heading_and_decorative_document_icon_render(self):
        self.assertIn(
            'aria-labelledby="authoritative-source-heading-0"', self.html
        )
        self.assertIn('id="authoritative-source-heading-0"', self.html)
        self.assertIn("Authoritative source Published Document", self.html)
        self.assertIn(
            'class="authoritative-source-icon" aria-hidden="true">&#128196;</span>',
            self.html,
        )

    def test_source_hierarchy_and_existing_link_are_preserved(self):
        title_index = self.html.index("Croom Admission – 19 June 2018")
        identifier_index = self.html.index("DOC-2026-000118")
        link_index = self.html.index("Open Published Document →")
        self.assertLess(title_index, identifier_index)
        self.assertLess(identifier_index, link_index)
        self.assertIn('class="authoritative-source-title"', self.html)
        self.assertIn('class="authoritative-source-identifier"', self.html)
        self.assertIn('class="authoritative-source-action"', self.html)
        self.assertIn(f'href="/documents/{self.source_id}"', self.html)

    def test_light_and_dark_mode_styles_are_scoped_to_the_panel(self):
        styles = admin_session.ASSOCIATION_AUTHORITATIVE_SOURCE_STYLES
        self.assertIn(".record-selection-control .authoritative-source-context", styles)
        self.assertIn("background: #edf7f6", styles)
        self.assertIn("border-left: 4px solid #2e8b9a", styles)
        self.assertIn("border-radius: 4px", styles)
        self.assertIn("@media (prefers-color-scheme: dark)", styles)
        self.assertIn("background: #173f42", styles)
        self.assertNotIn("table", styles)

    def test_theme_colours_meet_normal_text_contrast_threshold(self):
        self.assertGreaterEqual(_contrast_ratio("#245d61", "#edf7f6"), 4.5)
        self.assertGreaterEqual(_contrast_ratio("#b9ebe7", "#173f42"), 4.5)

    def test_keyboard_focus_and_semantic_content_remain_available(self):
        self.assertRegex(
            self.html,
            re.compile(r"a:focus-visible[^}]*outline:2px solid #245d61"),
        )
        self.assertIn("Primary evidence", self.html)
        self.assertIn("Open Published Document →", self.html)


if __name__ == "__main__":
    unittest.main()
