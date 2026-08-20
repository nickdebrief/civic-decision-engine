import re
import unittest

from tests.test_admin_session import install_fastapi_stubs

install_fastapi_stubs()

from api.routes import admin_session


ADMIN_SESSION = {"username": "ui-test", "role": "admin"}


def _checkbox_labels(html: str) -> list[tuple[str, str, str]]:
    return re.findall(
        r'<label for="([^"]+)" class="governed-declaration-control">'
        r'<input id="([^"]+)" type="checkbox"[^>]*>'
        r'<span(?: id="[^"]+")?>(.*?)</span></label>',
        html,
        re.DOTALL,
    )


class Stage721DeclarationCheckboxUITests(unittest.TestCase):
    def test_inference_declaration_uses_shared_control(self):
        html = admin_session._render_governed_inference_page(
            {"inferences": []}, admin_session=ADMIN_SESSION
        )
        self.assertIn('id="stage63-boundary"', html)
        self.assertIn('name="boundary_acknowledged" value="1" required', html)
        self.assertIn("I confirm this is human-authored, qualified, source-bound", html)
        self._assert_controls(html)

    def test_allegation_declarations_use_shared_controls(self):
        html = admin_session._render_governed_allegation_page(
            {"allegations": []}, admin_session=ADMIN_SESSION, source_candidates=[]
        )
        self.assertIn('id="stage64-representation"', html)
        self.assertIn('id="stage64-author-boundary"', html)
        self.assertIn("does not establish the truth of the proposition", html)
        self._assert_controls(html)

    def test_response_declarations_use_shared_controls(self):
        html = admin_session._render_governed_response_page(
            {"responses": []},
            admin_session=ADMIN_SESSION,
            candidates=[],
            allegations_list=[],
        )
        for control_id in (
            "stage65-express-declination",
            "stage65-representation",
            "stage65-recorder-boundary",
        ):
            self.assertIn(f'id="{control_id}"', html)
        self.assertIn("does not establish truth, falsity, or resolution", html)
        self._assert_controls(html)

    def test_pathway_declaration_uses_shared_control(self):
        html = admin_session._stage72_html(
            admin_session=ADMIN_SESSION,
            diagnostic={"links": []},
            candidates=[],
            canonical=[],
            sources=[],
        )
        self.assertIn('id="stage72-reliance-declaration"', html)
        self.assertIn(
            "not a finding of correctness, sufficiency, reasonableness or legal effect",
            html,
        )
        self._assert_controls(html)

    def test_procedural_time_declaration_remains_neutral_and_disabled(self):
        html = admin_session._stage71_html(
            admin_session=ADMIN_SESSION,
            diagnostic={"records": []},
            sources=[],
            objects=[],
        )
        self.assertIn('id="stage71-notice-declaration-checkbox"', html)
        self.assertIn('name="declaration_acknowledged" value="1" disabled', html)
        self.assertNotIn('id="stage71-notice-declaration-checkbox" checked', html)
        self._assert_controls(html)

    def test_shared_css_is_scoped_to_declaration_checkboxes(self):
        html = admin_session._stage72_html(
            admin_session=ADMIN_SESSION,
            diagnostic={"links": []},
            candidates=[],
            canonical=[],
            sources=[],
        )
        self.assertIn(".governed-declaration-control {", html)
        self.assertIn(
            '.governed-declaration-control input[type="checkbox"] {\n  width: auto;',
            html,
        )
        self.assertNotIn("input {\n  width: auto", html)

    def test_controls_are_unique_associated_and_unchecked(self):
        pages = [
            admin_session._render_governed_inference_page(
                {"inferences": []}, admin_session=ADMIN_SESSION
            ),
            admin_session._render_governed_allegation_page(
                {"allegations": []}, admin_session=ADMIN_SESSION, source_candidates=[]
            ),
            admin_session._render_governed_response_page(
                {"responses": []},
                admin_session=ADMIN_SESSION,
                candidates=[],
                allegations_list=[],
            ),
            admin_session._stage72_html(
                admin_session=ADMIN_SESSION,
                diagnostic={"links": []},
                candidates=[],
                canonical=[],
                sources=[],
            ),
        ]
        for html in pages:
            controls = _checkbox_labels(html)
            self.assertTrue(controls)
            ids = [control_id for _, control_id, _ in controls]
            self.assertEqual(len(ids), len(set(ids)))
            for label_id, control_id, _ in controls:
                self.assertEqual(label_id, control_id)
                self.assertNotRegex(
                    html[html.find(f'id="{control_id}"') : html.find(f'id="{control_id}"') + 160],
                    r'\bchecked\b',
                )

    def _assert_controls(self, html: str):
        controls = _checkbox_labels(html)
        self.assertTrue(controls)
        self.assertEqual(len(controls), len(set(control_id for _, control_id, _ in controls)))
        self.assertNotIn('class="governed-declaration-control"><input type="checkbox"', html)


if __name__ == "__main__":
    unittest.main()
