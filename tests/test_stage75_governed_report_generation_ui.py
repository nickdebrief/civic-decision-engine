from html.parser import HTMLParser
import unittest
from unittest.mock import Mock, patch

from tests.test_admin_session import install_fastapi_stubs

install_fastapi_stubs()

from api.routes import admin_session


DECLARATION = (
    "I confirm that generation acts only on the approved frozen report specification, "
    "creates validated internal artifacts, is not approval or publication, and does "
    "not replace or alter the underlying record."
)


class _FormParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.forms = []
        self.current = None
        self.label = None
        self.button = None
        self.nested_forms = False
        self.nested_labels = False

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "form":
            if self.current is not None:
                self.nested_forms = True
            self.current = {
                "attrs": attributes,
                "inputs": [],
                "labels": [],
                "buttons": [],
                "text": [],
            }
            self.forms.append(self.current)
        if self.current is None:
            return
        if tag == "input":
            self.current["inputs"].append(attributes)
        elif tag == "label":
            if self.label is not None:
                self.nested_labels = True
            self.label = {"attrs": attributes, "text": []}
            self.current["labels"].append(self.label)
        elif tag == "button":
            self.button = []

    def handle_endtag(self, tag):
        if tag == "label":
            self.label = None
        elif tag == "button":
            if self.current is not None and self.button is not None:
                self.current["buttons"].append("".join(self.button))
            self.button = None
        elif tag == "form":
            self.current = None

    def handle_data(self, data):
        if self.current is not None:
            self.current["text"].append(data)
        if self.label is not None:
            self.label["text"].append(data)
        if self.button is not None:
            self.button.append(data)


def _detail(status="approved_for_generation"):
    return {
        "id": 1,
        "lifecycle_status": status,
        "created_by": "nick",
        "versions": [{
            "requested_formats": ["docx", "html", "pdf"],
            "specification_digest": "fixture-specification-digest",
        }],
    }


class Stage75GovernedReportGenerationUITests(unittest.TestCase):
    def test_generation_declaration_is_visible_and_associated(self):
        html = admin_session._stage75_transition_forms(
            _detail(), session={"username": "nick", "role": "admin"}
        )

        self.assertEqual(html.count(DECLARATION), 1)
        self.assertIn(
            '<form class="qualification governed-generation-action" method="post" '
            'action="/api/admin/session/governed-reports/1/generate">',
            html,
        )
        self.assertIn(
            '<label for="stage75-generation-declaration-1" '
            'class="governed-declaration-control">',
            html,
        )
        self.assertIn(
            '<input id="stage75-generation-declaration-1" type="checkbox" '
            'name="acknowledged" value="1" required>',
            html,
        )
        self.assertNotIn('id="stage75-generation-declaration-1" checked', html)
        self.assertNotIn(
            '<label>Generation declaration<input type="checkbox"', html
        )

    def test_generation_and_supersession_are_distinct_forms(self):
        html = admin_session._stage75_transition_forms(
            _detail(), session={"username": "nick", "role": "admin"}
        )
        parser = _FormParser()
        parser.feed(html)
        forms = parser.forms

        self.assertEqual(len(forms), 2)
        generation, supersession = forms
        self.assertFalse(parser.nested_forms)
        self.assertFalse(parser.nested_labels)
        self.assertEqual(
            generation["attrs"]["action"],
            "/api/admin/session/governed-reports/1/generate",
        )
        self.assertEqual(
            supersession["attrs"]["action"],
            "/api/admin/session/governed-reports/1/supersede",
        )
        self.assertIn("governed-generation-action", generation["attrs"]["class"])
        self.assertIn("governed-supersession-action", supersession["attrs"]["class"])
        self.assertEqual(generation["buttons"], ["Generate validated docx, html, pdf artifacts"])
        self.assertEqual(supersession["buttons"], ["Supersede report version"])
        self.assertNotIn(
            "replacement_report_id",
            {item.get("name") for item in generation["inputs"]},
        )
        self.assertIn(
            "acknowledged",
            {item.get("name") for item in supersession["inputs"]},
        )
        self.assertNotIn(
            "stage75-generation-declaration-1",
            {item.get("id") for item in supersession["inputs"]},
        )
        self.assertEqual(
            generation["labels"][0]["attrs"].get("for"),
            "stage75-generation-declaration-1",
        )
        self.assertIn(DECLARATION, "".join(generation["labels"][0]["text"]))

    def test_generation_action_has_wrapping_and_separation_styles(self):
        html = admin_session._stage75_html(
            session={"username": "nick", "role": "admin"},
            reports=[],
            candidates={},
            detail=_detail(),
        )

        self.assertIn(
            ".governed-declaration-control span{min-width:0;overflow-wrap:anywhere}",
            html,
        )
        self.assertIn(".governed-generation-action{margin-bottom:28px}", html)
        self.assertIn(
            ".governed-generation-confirmation{border:0;padding:0;margin:0;min-width:0}",
            html,
        )
        self.assertIn(".governed-supersession-action{margin-top:28px}", html)

    def test_generation_server_contract_remains_required_and_enqueue_only(self):
        with patch.object(admin_session, "require_admin_session", return_value={"username": "nick"}):
            with self.assertRaises(Exception) as missing:
                admin_session.admin_governed_report_generate(
                    "1", object(), acknowledged=None, idempotency_key=""
                )
        self.assertEqual(missing.exception.status_code, 409)

        connection = Mock()
        with (
            patch.object(admin_session, "require_admin_session", return_value={"username": "nick"}),
            patch.object(admin_session, "get_db", return_value=connection),
            patch.object(
                admin_session.rg77,
                "enqueue_generation",
                return_value={"report_id": 1},
            ) as enqueue,
            patch.object(admin_session, "admin_governed_report_detail"),
        ):
            admin_session.admin_governed_report_generate(
                "1", object(), acknowledged="1", idempotency_key="ui-test"
            )
        enqueue.assert_called_once_with(
            connection,
            report_id="1",
            actor="nick",
            governed_action="enqueue_generation",
            idempotency_key="ui-test",
        )


if __name__ == "__main__":
    unittest.main()
