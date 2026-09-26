from html.parser import HTMLParser
import asyncio
import os
import unittest
from api import governed_report_publications as stage79_publications
from unittest.mock import Mock, patch

from tests.test_admin_session import FakeHTTPException, FakeRequest, install_fastapi_stubs

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


class _RegistrarForm:
    """Minimal duplicate-preserving form fixture for the private registrar."""

    def __init__(self, items):
        self._items = list(items)

    def multi_items(self):
        return list(self._items)


class _RegistrarRequest(FakeRequest):
    def __init__(self, items=()):
        super().__init__()
        self._form = _RegistrarForm(items)

    async def form(self):
        return self._form


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
    def test_publication_review_summary_is_internal_and_not_publication(self):
        detail = _detail("generated")
        detail["publication_review_details"] = [{
            "id": 9, "report_version_id": 2, "governed_job_id": 7,
            "governed_attempt_count": 1, "artifact_set_digest": "a" * 64,
            "privacy_redaction_status": "cleared", "eligibility_outcome": "eligible",
            "lifecycle_status": "eligible", "created_by": "reviewer", "created_at": "now",
            "artifacts": [{"artifact_id": 3, "format": "pdf", "sha256": "b" * 64, "size_bytes": 12}],
            "events": [{"event_type": "eligibility_determined", "actor": "reviewer", "occurred_at": "now", "rationale": "bounded"}],
        }]
        html = admin_session._stage75_html(session={"username": "nick", "role": "admin"}, reports=[], candidates={}, detail=detail)
        self.assertIn("Registered does not mean eligible for publication.", html)
        self.assertIn("Eligible for publication does not mean published.", html)
        self.assertIn("Frozen artifact-set digest", html)
        self.assertIn("eligibility_determined", html)
        self.assertNotIn('href="/reports/9"', html)

    def test_generation_attempts_render_bounded_history_and_unavailable_diagnostics(self):
        detail = _detail("validation_failed")
        detail["job_attempts"] = [
            {"job_id": 1, "report_id": 1, "report_version_id": 2, "attempt_count": 1, "predecessor_job_id": None, "successor_job_id": 2, "state": "failed_terminal", "failure_phase": "rendering", "failure_code": "adapter_input_invalid", "diagnostic_status": "available", "requested_at": "requested-1", "started_at": "started-1", "terminal_at": "terminal-1", "requested_formats": ["docx", "pdf"], "specification_digest": "a" * 64, "qualification_id": 7, "qualification_digest": "b" * 64, "rendering_profile": "internal", "template_version": "v1", "publication_engine_version": "2.0.0"},
            {"job_id": 2, "report_id": 1, "report_version_id": 2, "attempt_count": 1, "predecessor_job_id": 1, "successor_job_id": None, "state": "failed_terminal", "failure_phase": None, "failure_code": None, "diagnostic_status": "unavailable", "requested_at": "requested-2", "started_at": None, "terminal_at": "terminal-2", "requested_formats": ["docx", "pdf"], "specification_digest": "a" * 64, "qualification_id": 7, "qualification_digest": "b" * 64, "rendering_profile": "internal", "template_version": "v1", "publication_engine_version": "2.0.0"},
        ]
        html = admin_session._stage75_html(session={"username": "nick", "role": "admin"}, reports=[], candidates={}, detail=detail)

        self.assertIn("Generation attempts — internal only", html)
        self.assertIn("1 / 1", html)
        self.assertIn("2 / 1", html)
        self.assertIn("adapter_input_invalid", html)
        self.assertGreaterEqual(html.count("Unavailable"), 3)
        self.assertIn("Attempts are preserved historical authority", html)
        self.assertNotIn("traceback", html)
        self.assertNotIn("/tmp/", html)
        self.assertNotIn("secret-token", html)
        self.assertNotIn("private-artifact-url", html)
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


class Stage77CustodyV2PresentationTests(unittest.TestCase):
    def test_detail_template_marks_v2_as_private_and_pre_activation_safe(self):
        source = admin_session._stage75_html.__code__.co_consts
        text = " ".join(part for part in source if isinstance(part, str))
        self.assertIn("V2 custody authority", text)
        self.assertIn("closed historical authority", text)


class Stage77CustodyEvidenceRegistrarUITests(unittest.TestCase):
    """Route tests keep the controller-owned verifier behind the admin boundary."""

    session = {"username": "custody-admin", "role": "admin"}
    selection = {
        "evidence_set_id": "evidence-set-1",
        "mandate_id": "mandate-1",
        "report_id": "7",
        "report_version_id": "11",
    }

    def _items(self, *, csrf_token="valid", extra=()):
        return [("csrf_token", csrf_token), *self.selection.items(), *extra]

    def _receipt(self):
        return {
            "id": "evidence-set-1",
            "payload_digest": "a" * 64,
            "state": "registered",
            "mandate_id": "mandate-1",
            "report_id": 7,
            "report_version_id": 11,
            "created_at": "2026-09-20T00:00:00Z",
            "private_path": "/controller/private/evidence-set-1",
            "raw_evidence": "retained-content",
            "signature": "secret-signature",
        }

    def test_registrar_get_and_post_reject_unauthenticated_or_non_admin_sessions(self):
        with patch.object(admin_session, "require_admin_session", side_effect=FakeHTTPException(401, "unauthorized")):
            get = admin_session.admin_custody_evidence_registrar_form(FakeRequest())
            post = asyncio.run(admin_session.admin_custody_evidence_registrar_register(_RegistrarRequest()))
        self.assertEqual((get.status_code, post.status_code), (401, 401))
        self.assertEqual(get.headers["Cache-Control"], "private, no-store")
        self.assertEqual(post.headers["Cache-Control"], "private, no-store")
        with patch.object(admin_session, "require_admin_session", return_value={"username": "viewer", "role": "viewer"}):
            response = admin_session.admin_custody_evidence_registrar_form(FakeRequest())
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.headers["Cache-Control"], "private, no-store")

    def test_registrar_get_is_private_read_only_form_with_only_bounded_selection_inputs(self):
        with patch.dict(os.environ, {"CDE_ADMIN_SESSION_SECRET": "test-session-secret"}, clear=False), patch.object(admin_session, "require_admin_session", return_value=self.session), patch.object(admin_session, "get_db") as database, patch.object(admin_session.custody_evidence, "register_from_store") as register:
            response = admin_session.admin_custody_evidence_registrar_form(FakeRequest())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Cache-Control"], "private, no-store")
        parser = _FormParser(); parser.feed(response.content)
        self.assertEqual(len(parser.forms), 1)
        form = parser.forms[0]
        self.assertEqual(form["attrs"]["method"], "post")
        self.assertEqual(form["attrs"]["action"], admin_session._CUSTODY_REGISTRAR_API_PATH)
        self.assertEqual({item.get("name") for item in form["inputs"]}, {"csrf_token", "evidence_set_id", "mandate_id", "report_id", "report_version_id"})
        database.assert_not_called(); register.assert_not_called()
        self.assertNotIn("/sitemap", response.content)
        self.assertNotIn("public", form["attrs"]["action"])

    def test_registrar_post_requires_exact_valid_csrf_and_strict_selection_schema(self):
        with patch.dict(os.environ, {"CDE_ADMIN_SESSION_SECRET": "test-session-secret"}, clear=False):
            valid = admin_session._custody_registrar_token(self.session)
            expired = admin_session._custody_registrar_token(self.session, now=0)
            other_actor = admin_session._custody_registrar_token({"username": "other", "role": "admin"})
            for token in ("", "not-a-token", expired, other_actor):
                with patch.object(admin_session, "require_admin_session", return_value=self.session), patch.object(admin_session.custody_evidence, "register_from_store") as register:
                    response = asyncio.run(admin_session.admin_custody_evidence_registrar_register(_RegistrarRequest(self._items(csrf_token=token))))
                self.assertEqual(response.status_code, 409)
                self.assertEqual(response.headers["Cache-Control"], "private, no-store")
                register.assert_not_called()
            for extra in (("payload", "caller-proof"), ("digest", "b" * 64), ("runtime", "claimed"), ("path", "/tmp/evidence"), ("role", "database_capture")):
                with patch.object(admin_session, "require_admin_session", return_value=self.session), patch.object(admin_session.custody_evidence, "register_from_store") as register:
                    response = asyncio.run(admin_session.admin_custody_evidence_registrar_register(_RegistrarRequest(self._items(csrf_token=valid, extra=(extra,)))))
                self.assertEqual(response.status_code, 400)
                register.assert_not_called()

    def test_registrar_post_delegates_only_to_store_boundary_and_renders_bounded_receipt(self):
        connection = Mock()
        with patch.dict(os.environ, {"CDE_ADMIN_SESSION_SECRET": "test-session-secret"}, clear=False):
            token = admin_session._custody_registrar_token(self.session)
            with patch.object(admin_session, "require_admin_session", return_value=self.session), patch.object(admin_session, "get_db", return_value=connection), patch.object(admin_session.custody_evidence, "register_from_store", return_value=self._receipt()) as register, patch.object(admin_session.custody_evidence, "_register_verified") as low_level, patch.object(admin_session.rg77, "enqueue_generation") as enqueue:
                response = asyncio.run(admin_session.admin_custody_evidence_registrar_register(_RegistrarRequest(self._items(csrf_token=token))))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Cache-Control"], "private, no-store")
        register.assert_called_once_with(connection, evidence_set_id="evidence-set-1", mandate_id="mandate-1", report_id=7, report_version_id=11, actor="custody-admin", occurred_at=unittest.mock.ANY)
        low_level.assert_not_called(); enqueue.assert_not_called()
        self.assertEqual(connection.execute.call_args_list[0].args, ("BEGIN IMMEDIATE",))
        connection.commit.assert_called_once(); connection.close.assert_called_once()
        for permitted in ("evidence-set-1", "a" * 64, "registered", "mandate-1", "2026-09-20T00:00:00Z"):
            self.assertIn(permitted, response.content)
        for forbidden in ("/controller/private", "retained-content", "secret-signature", "raw_evidence", "private_path", "database_capture"):
            self.assertNotIn(forbidden, response.content)

    def test_registrar_duplicate_replay_is_bounded_idempotently_and_conflicts_do_not_leak_inputs(self):
        connection = Mock()
        with patch.dict(os.environ, {"CDE_ADMIN_SESSION_SECRET": "test-session-secret"}, clear=False):
            token = admin_session._custody_registrar_token(self.session)
            request = _RegistrarRequest(self._items(csrf_token=token))
            with patch.object(admin_session, "require_admin_session", return_value=self.session), patch.object(admin_session, "get_db", return_value=connection), patch.object(admin_session.custody_evidence, "register_from_store", return_value=self._receipt()) as register:
                first = asyncio.run(admin_session.admin_custody_evidence_registrar_register(request))
                second = asyncio.run(admin_session.admin_custody_evidence_registrar_register(_RegistrarRequest(self._items(csrf_token=token))))
            self.assertEqual((first.status_code, second.status_code), (200, 200))
            self.assertEqual(first.content, second.content)
            self.assertEqual(register.call_count, 2)
            with patch.object(admin_session, "require_admin_session", return_value=self.session), patch.object(admin_session, "get_db", return_value=connection), patch.object(admin_session.custody_evidence, "register_from_store", side_effect=ValueError("prior private input: /controller/private")):
                conflict = asyncio.run(admin_session.admin_custody_evidence_registrar_register(_RegistrarRequest(self._items(csrf_token=token))))
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.headers["Cache-Control"], "private, no-store")
        self.assertIn("Controller-owned custody evidence registrar", conflict.content)
        self.assertIn("The request could not be completed.", conflict.content)
        for private_value in ("No authority was registered", "/controller/private", "evidence-set-1", "mandate-1", "secret-signature", "database_capture", "report content", "registered", "attestation"):
            self.assertNotIn(private_value, conflict.content)
        self.assertTrue(connection.execute.call_args_list)
        self.assertTrue(all(call.args == ("BEGIN IMMEDIATE",) for call in connection.execute.call_args_list))


if __name__ == "__main__":
    unittest.main()
