import inspect
import re
import unittest
from unittest.mock import patch

from tests.test_admin_session import install_fastapi_stubs

install_fastapi_stubs()

from api.routes import documents


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


class _Connection:
    def close(self):
        return None


class AssociationCardVisualRefinementTests(unittest.TestCase):
    def setUp(self):
        self.association = {
            "public_reference": "CDE-ASSOC-20260805-001",
            "record_reference": "CLE-UHL-20180619-001",
            "public_label": "Supporting document",
            "record_title": "Croom Admission clinical episode",
            "record_generated_at": "2018-06-19T10:30:00Z",
            "record_trajectory": "Clinical episode",
        }

    def _section(self, associations):
        with (
            patch.object(documents.rda, "get_db", return_value=_Connection()),
            patch.object(
                documents.rda,
                "public_associations_for_document",
                return_value=associations,
            ),
        ):
            return documents._render_associated_records({"intake_id": "document-1"})

    def test_notice_reuses_readable_publication_provenance_treatment(self):
        html = self._section([self.association])
        wording = (
            "Association records a declared relationship between independently preserved "
            "objects. It does not by itself establish proof, sufficiency, factual truth, "
            "legal status, or external validation."
        )
        self.assertIn(wording, html)
        self.assertIn('class="association-boundary provenance-boundary"', html)
        notice_tag = re.search(r'<p class="association-boundary[^"]*">', html).group(0)
        self.assertNotIn("muted", notice_tag)

    def test_card_uses_required_semantic_reading_order(self):
        html = documents._render_associated_record_card(self.association)
        ordered_fragments = (
            "Canonical Record</p>",
            "CLE-UHL-20180619-001</a></h3>",
            "Supporting document</span>",
            "Association summary</p>",
            'class="association-card__metadata"',
            'class="association-card__actions"',
        )
        positions = [html.index(fragment) for fragment in ordered_fragments]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("Croom Admission clinical episode", html)

    def test_relationship_badge_preserves_exact_persisted_value(self):
        relationship = "Methodology reference / extended governed relationship"
        html = documents._render_associated_record_card(
            {**self.association, "public_label": relationship}
        )
        self.assertIn(
            f'<span class="association-card__badge">{relationship}</span>', html
        )
        self.assertIn("overflow-wrap: anywhere", documents.ASSOCIATION_CARD_STYLES)
        self.assertIn("white-space: normal", documents.ASSOCIATION_CARD_STYLES)

    def test_metadata_is_grouped_semantically_and_omits_empty_rows(self):
        html = documents._render_associated_record_card(self.association)
        self.assertIn('<dl class="association-card__metadata">', html)
        self.assertIn("<dt>Generated date</dt><dd>2018-06-19</dd>", html)
        self.assertIn("<dt>Trajectory</dt><dd>Clinical episode</dd>", html)

        empty = documents._render_associated_record_card(
            {
                **self.association,
                "record_generated_at": None,
                "record_trajectory": None,
            }
        )
        self.assertNotIn('class="association-card__metadata"', empty)
        self.assertNotIn("Generated date", empty)
        self.assertNotIn("Trajectory", empty)

    def test_actions_are_button_styled_links_with_existing_urls(self):
        html = documents._render_associated_record_card(self.association)
        self.assertIn(
            'class="button-link association-card__action association-card__action--primary" '
            'href="/verify/CLE-UHL-20180619-001">Open Canonical Record</a>',
            html,
        )
        self.assertIn(
            'class="button-link button-link--secondary association-card__action '
            'association-card__action--secondary" '
            'href="/associations/CDE-ASSOC-20260805-001">View association</a>',
            html,
        )
        self.assertIn(".association-card a:focus-visible", documents.ASSOCIATION_CARD_STYLES)

    def test_multiple_associations_render_independent_cards_in_backend_order(self):
        second = {
            **self.association,
            "public_reference": "CDE-ASSOC-20260805-002",
            "record_reference": "CLE-UHL-20180619-002",
            "public_label": "Related document",
            "record_title": "Second governed record",
        }
        html = self._section([self.association, second])
        self.assertEqual(html.count('class="association-card"'), 2)
        self.assertLess(
            html.index("CLE-UHL-20180619-001"),
            html.index("CLE-UHL-20180619-002"),
        )
        self.assertIn('href="/associations/CDE-ASSOC-20260805-001"', html)
        self.assertIn('href="/associations/CDE-ASSOC-20260805-002"', html)
        cards = re.findall(r'<article class="association-card".*?</article>', html, re.S)
        self.assertEqual(len(cards), 2)
        self.assertIn("Supporting document", cards[0])
        self.assertNotIn("Related document", cards[0])
        self.assertIn("Related document", cards[1])
        self.assertNotRegex("".join(cards), r'\sid="[^"]+"')

    def test_zero_associations_preserves_existing_empty_state(self):
        self.assertEqual(self._section([]), "")

    def test_styles_are_scoped_responsive_dark_and_accessible(self):
        styles = documents.ASSOCIATION_CARD_STYLES
        self.assertIn(".associated-records", styles)
        self.assertIn("@media (max-width: 560px)", styles)
        self.assertIn("grid-template-columns: 1fr", styles)
        self.assertIn("flex: 1 1 100%", styles)
        self.assertIn("@media (prefers-color-scheme: dark)", styles)
        self.assertIn("#8dd5dd", styles)
        self.assertIn("outline-color: #8dd5dd", styles)
        self.assertNotRegex(styles, r'(^|\n)(body|table|a)\s*\{')
        self.assertGreaterEqual(_contrast_ratio("#ffffff", "#245d61"), 4.5)
        self.assertGreaterEqual(_contrast_ratio("#b9ebe7", "#173f42"), 4.5)

    def test_public_document_page_includes_component_styles_without_changing_provenance(self):
        source = inspect.getsource(documents._render_document)
        self.assertIn("ASSOCIATION_CARD_STYLES", source)
        self.assertIn("_render_publication_provenance(item)", source)
        self.assertIn("_render_associated_records(item)", source)


if __name__ == "__main__":
    unittest.main()
