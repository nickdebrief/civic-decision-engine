import os
import asyncio
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from api import governed_report_publications as stage79_publications
from unittest.mock import patch

from api import public_origin


def _javascript_core() -> str | None:
    """Find the local JavaScriptCore shell used by the DOM-controller test."""
    for candidate in (
        shutil.which("jsc"),
        "/System/Library/Frameworks/JavaScriptCore.framework/Versions/A/Helpers/jsc",
    ):
        if candidate and Path(candidate).is_file():
            return candidate
    return None


def _run_generated_consent_controller(*, control: str, storage: dict | None, action: str) -> dict:
    """Execute the generated controller in a synthetic DOM with no network API.

    ``appendChild`` records attempted provider-loader insertion but never fetches
    a URL.  This is DOM behavior coverage, not provider-network evidence.
    """
    shell = _javascript_core()
    if shell is None:
        raise unittest.SkipTest("JavaScriptCore shell unavailable")
    source = re.search(
        r'<script data-cde-(?:clarity-consent|analytics-preferences-clear)="1"[^>]*>(.*?)</script>',
        control,
        re.DOTALL,
    ).group(1)
    harness = r'''
var initialStorage = __STORAGE__;
var action = __ACTION__;
function Element(tag) { this.tagName=tag; this.attrs={}; this.children=[]; this.handlers={}; this.hidden=false; this.removed=false; this.onload=null; this.checked=false; }
Element.prototype.setAttribute=function(k,v){this.attrs[k]=String(v)};
Element.prototype.getAttribute=function(k){return Object.prototype.hasOwnProperty.call(this.attrs,k)?this.attrs[k]:null};
Element.prototype.addEventListener=function(type,fn){(this.handlers[type]=this.handlers[type]||[]).push(fn)};
Element.prototype.dispatch=function(type){(this.handlers[type]||[]).slice().forEach(function(fn){fn({target:this})},this)};
Element.prototype.remove=function(){this.removed=true};
Element.prototype.focus=function(){};
Element.prototype.appendChild=function(node){this.children.push(node); return node};
function descendants(root){var found=[]; (root.children||[]).forEach(function(child){found.push(child); found=found.concat(descendants(child))}); return found}
function matches(node, selector) { var match=/^([a-z]+)?(?:\[([^=\]]+)(?:="([^"]*)")?\])?$/.exec(selector); if(!match){return false}; return (!match[1]||node.tagName===match[1]) && (!match[2]||node.getAttribute(match[2])!==null) && (!match[3]||node.getAttribute(match[2])===match[3]) && !node.removed }
function find(root, selector, all){var nodes=descendants(root).filter(function(node){return matches(node,selector)}); return all?nodes:(nodes[0]||null)}
Element.prototype.querySelector=function(selector){return find(this,selector,false)};
Element.prototype.querySelectorAll=function(selector){return find(this,selector,true)};
Object.defineProperty(Element.prototype,"innerHTML",{set:function(markup){var tags=markup.match(/<[^>]+>/g)||[]; for(var i=0;i<tags.length;i++){var tag=/^<([a-z]+)/.exec(tags[i]); if(!tag){continue}; var child=new Element(tag[1]); var attrs=tags[i].match(/[^\s=>]+(?:="[^"]*")?/g)||[]; for(var j=1;j<attrs.length;j++){var parts=attrs[j].split("="); child.setAttribute(parts[0],parts.length>1?parts.slice(1).join("=").replace(/^"|"$/g,""):"")} this.children.push(child)}}});
var document={readyState:action==="dispatch-ready-twice"?"loading":"complete",handlers:{},body:new Element("body"),head:new Element("head"),documentElement:{lang:"en"},createElement:function(tag){return new Element(tag)},addEventListener:function(type,fn){(this.handlers[type]=this.handlers[type]||[]).push(fn)},querySelector:function(selector){return find({children:[this.head,this.body]},selector,false)},querySelectorAll:function(selector){return find({children:[this.head,this.body]},selector,true)}};
document.head.appendChild=function(node){this.children.push(node); if(node.src){attempts.push(node.src)} return node};
document.body.appendChild=function(node){this.children.push(node); return node};
var cookieWrites=[], cookies=["_ga=test","_clck=test"]; Object.defineProperty(document,"cookie",{get:function(){return cookies.join("; ")},set:function(value){cookieWrites.push(value)}});
var values=initialStorage||{}; var localStorage={getItem:function(k){return Object.prototype.hasOwnProperty.call(values,k)?values[k]:null},setItem:function(k,v){values[k]=String(v)},removeItem:function(k){delete values[k]}};
var attempts=[]; var reloads=0; var i18n=action==="without-i18n"?null:{TRANSLATIONS:{en:{analytics_preferences:"Privacy preferences",analytics_title:"Optional analytics",analytics_description:"desc",analytics_accept_both:"Accept both",analytics_decline_both:"Decline both",analytics_choose_separately:"Choose separately",analytics_preferences_label:"Preferences",analytics_ga_choice:"GA",analytics_clarity_choice:"Clarity",analytics_save_choices:"Save",analytics_privacy_notice:"Privacy",analytics_clear_preferences:"Clear analytics preferences",analytics_providers_disabled:"Disabled",analytics_provider_disabled:"Currently disabled"}}}; var window={document:document,localStorage:localStorage,location:{hostname:"consent.local",reload:function(){reloads+=1}},dataLayer:[],CDE_I18N:i18n};
var location=window.location;
__SOURCE__
function click(selector){var node=document.querySelector(selector); if(!node){throw new Error("missing "+selector)} node.dispatch("click"); return node}
if(action==="ga-only"){document.querySelector("[data-cde-ga-choice]").checked=true; document.querySelector("[data-cde-clarity-choice]").checked=false; click("[data-cde-analytics-save]")}
if(action==="clarity-only"){document.querySelector("[data-cde-ga-choice]").checked=false; document.querySelector("[data-cde-clarity-choice]").checked=true; click("[data-cde-analytics-save]")}
if(action==="decline"){click("[data-cde-analytics-decline]")}
if(action==="dispatch-ready-twice"){(document.handlers.DOMContentLoaded||[]).forEach(function(fn){fn()});(document.handlers.DOMContentLoaded||[]).forEach(function(fn){fn()})}
if(action==="withdraw-ga"){click("[data-cde-clarity-preferences]"); document.querySelector("[data-cde-ga-choice]").checked=false; document.querySelector("[data-cde-clarity-choice]").checked=false; click("[data-cde-analytics-save]"); var pending=document.querySelector("script[data-cde-google-loader=\"1\"]"); if(pending&&pending.onload){pending.onload()}}
if(action==="clear"){click("[data-cde-analytics-preferences]"); click("[data-cde-analytics-clear-preferences]")}
print(JSON.stringify({attempts:attempts,reloads:reloads,storage:values,google:document.querySelectorAll("script[data-cde-google-loader=\"1\"]").length,clarity:document.querySelectorAll("script[data-cde-clarity-loader=\"1\"]").length,removedGoogle:document.head.children.filter(function(node){return node.getAttribute("data-cde-google-loader")==="1"&&node.removed}).length,removedClarity:document.head.children.filter(function(node){return node.getAttribute("data-cde-clarity-loader")==="1"&&node.removed}).length,cookieWrites:cookieWrites.length,clear:!!document.querySelector("[data-cde-analytics-clear-preferences]"),panelHidden:(document.querySelector("[data-cde-clarity-dialog]")||document.querySelector("[data-cde-analytics-disabled-panel]")).hidden,gaChoiceCount:document.querySelectorAll("[data-cde-ga-choice]").length,clarityChoiceCount:document.querySelectorAll("[data-cde-clarity-choice]").length,preferencesText:(document.querySelector("[data-cde-analytics-preferences]")||{}).textContent||""}));
'''.replace("__STORAGE__", json.dumps(storage or {})).replace("__ACTION__", json.dumps(action)).replace("__SOURCE__", source)
    with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8") as script:
        script.write(harness)
        script.flush()
        completed = subprocess.run([shell, script.name], check=False, capture_output=True, text=True)
    if completed.returncode:
        raise AssertionError(completed.stderr or completed.stdout)
    return json.loads(completed.stdout)


class CanonicalPublicOriginTests(unittest.TestCase):
    def asgi_get(self, path, host, query=b"", method="GET", extra_headers=()):
        from api.main import app

        messages = []

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            messages.append(message)

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": method,
            "scheme": "https",
            "path": path,
            "raw_path": path.encode(),
            "query_string": query,
            "headers": [(b"host", host.encode()), *extra_headers],
            "client": ("127.0.0.1", 1),
            "server": (host, 443),
        }
        asyncio.run(app(scope, receive, send))
        start = next(message for message in messages if message["type"] == "http.response.start")
        body = b"".join(message.get("body", b"") for message in messages if message["type"] == "http.response.body")
        return start, body

    def test_default_origin_is_fixed_https_domain(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                public_origin.canonical_public_origin(),
                "https://civicdecisionengine.ie",
            )

    def test_configuration_rejects_non_origin_values(self):
        for value in (
            "http://civicdecisionengine.ie",
            "https://civicdecisionengine.ie/extra",
            "https://civicdecisionengine.ie/?x=1",
        ):
            with self.subTest(value=value), patch.dict(
                os.environ,
                {public_origin.CANONICAL_PUBLIC_ORIGIN_ENV: value},
                clear=True,
            ):
                with self.assertRaisesRegex(RuntimeError, "canonical_public_origin_invalid"):
                    public_origin.canonical_public_origin()

    def test_only_approved_aliases_redirect_to_fixed_origin(self):
        self.assertEqual(
            public_origin.public_alias_redirect_location(
                "www.civicdecisionengine.ie", "/records", b"page=2"
            ),
            "https://civicdecisionengine.ie/records?page=2",
        )
        self.assertEqual(
            public_origin.public_alias_redirect_location(
                "civic-decision-engine-production.up.railway.app", "/verify/R-1", b""
            ),
            "https://civicdecisionengine.ie/verify/R-1",
        )
        for host in (
            "civicdecisionengine.ie",
            "localhost:8000",
            "attacker.example",
        ):
            with self.subTest(host=host):
                self.assertIsNone(public_origin.public_alias_redirect_location(host, "/records", b"x=1"))

    def test_canonical_injection_uses_path_only_and_replaces_existing_tag(self):
        html = (
            b'<html><head><link rel="canonical" href="https://attacker.example/x">'
            b'<link rel="canonical" href="/records"></head><body>ok</body></html>'
        )
        result = public_origin.inject_canonical_link(html, "/records")
        self.assertEqual(result.count(b'rel="canonical"'), 1)
        self.assertIn(
            b'https://civicdecisionengine.ie/records', result
        )
        self.assertNotIn(b"attacker.example", result)

    def test_optional_analytics_controls_are_separate_default_off_masked_and_idempotent(self):
        html = (
            b'<html><head><script async src="https://www.googletagmanager.com/gtag/js?id=G-8405RVT76Q"></script>'
            b'</head><body>public content</body></html>'
        )
        disabled = public_origin.inject_public_html_head(html, "/")
        self.assertNotIn(b"data-cde-clarity-consent", disabled)
        self.assertIn(b"data-cde-analytics-preferences-clear", disabled)
        self.assertNotIn(
            public_origin.GOOGLE_ANALYTICS_MEASUREMENT_ID,
            public_origin._ANALYTICS_PREFERENCES_CLEAR_CONTROL,
        )
        self.assertNotIn(
            public_origin.CLARITY_PROJECT_ID,
            public_origin._ANALYTICS_PREFERENCES_CLEAR_CONTROL,
        )
        with patch.dict(
            os.environ,
            {
                public_origin.CLARITY_ENABLED_ENV: "1",
                public_origin.GOOGLE_ANALYTICS_ENABLED_ENV: "1",
            },
            clear=False,
        ):
            first = public_origin.inject_public_html_head(html, "/")
            second = public_origin.inject_public_html_head(first, "/")

        self.assertEqual(first, second)
        self.assertEqual(first.count(b'data-cde-clarity-consent="1"'), 1)
        self.assertNotIn(b'<script src="https://www.clarity.ms/tag/', first)
        self.assertIn(b"ym9fkxdm29", first)
        self.assertIn(b"data-clarity-mask", first)
        self.assertIn(b"consentv2", first)
        self.assertIn(
            b'window.clarity("consentv2",{ad_Storage:"denied",analytics_Storage:"denied"})',
            first,
        )
        self.assertNotIn(b'window.clarity("consent",false)', first)
        self.assertIn(b"data-cde-google-loader", first)
        self.assertIn(b"window.gtag(\"consent\",\"update\"", first)
        self.assertIn(
            b'window.gtag("consent","default",{analytics_storage:"granted",ad_storage:"denied",ad_user_data:"denied",ad_personalization:"denied"})',
            first,
        )
        self.assertIn(
            b'window.gtag("consent","update",{analytics_storage:"denied",ad_storage:"denied",ad_user_data:"denied",ad_personalization:"denied"})',
            first,
        )
        self.assertIn(b"eraseGoogle", first)
        self.assertIn(b"eraseClarity", first)
        self.assertIn(b"G-8405RVT76Q", first)
        self.assertIn(b"cde_optional_analytics_preferences_v2", first)
        self.assertIn(b"cde_optional_analytics_consent_v1", first)
        self.assertIn(b"maxAge=7776000000", first)
        self.assertIn(b"data-cde-ga-choice", first)
        self.assertIn(b"data-cde-clarity-choice", first)
        self.assertIn(b"data-cde-analytics-decline", first)
        self.assertIn(b"data-cde-analytics-text=\\\"analytics_description\\\"", first)
        self.assertIn(b"data-cde-ga-choice", first)
        self.assertIn(b"data-cde-clarity-choice", first)
        self.assertIn(b"data-cde-analytics-i18n", first)
        self.assertIn(b"cde-i18n-applied", first)
        self.assertIn(b"ga:!!v.ga,clarity:!!v.clarity", first)
        self.assertNotIn(b"Accept optional analytics", first)

    def _controller(self, *, clarity=True, google=True) -> str:
        environment = {
            public_origin.CLARITY_ENABLED_ENV: "1" if clarity else "0",
            public_origin.GOOGLE_ANALYTICS_ENABLED_ENV: "1" if google else "0",
        }
        with patch.dict(os.environ, environment, clear=False):
            html = public_origin.inject_public_html_head(
                b"<html><head></head><body>public content</body></html>", "/"
            )
        return html.decode("utf-8")

    def test_generated_controller_executes_separate_choices_refusal_and_duplicate_prevention_without_network(self):
        controller = self._controller()
        no_choice = _run_generated_consent_controller(
            control=controller, storage=None, action="none"
        )
        self.assertEqual(no_choice["attempts"], [])
        self.assertEqual((no_choice["google"], no_choice["clarity"]), (0, 0))

        ga_choice = _run_generated_consent_controller(
            control=controller, storage=None, action="ga-only"
        )
        preference = json.loads(
            ga_choice["storage"]["cde_optional_analytics_preferences_v2"]
        )
        self.assertEqual((preference["ga"], preference["clarity"]), (True, False))
        self.assertEqual(ga_choice["attempts"], [])
        self.assertEqual(ga_choice["reloads"], 1)

        revisited = _run_generated_consent_controller(
            control=controller, storage=ga_choice["storage"], action="none"
        )
        self.assertEqual(len(revisited["attempts"]), 1)
        self.assertIn("googletagmanager.com/gtag/js", revisited["attempts"][0])
        self.assertEqual((revisited["google"], revisited["clarity"]), (1, 0))

        clarity_choice = _run_generated_consent_controller(
            control=controller, storage=None, action="clarity-only"
        )
        clarity_revisited = _run_generated_consent_controller(
            control=controller, storage=clarity_choice["storage"], action="none"
        )
        self.assertEqual(len(clarity_revisited["attempts"]), 1)
        self.assertIn("clarity.ms/tag", clarity_revisited["attempts"][0])
        self.assertEqual((clarity_revisited["google"], clarity_revisited["clarity"]), (0, 1))

        duplicate_guard = _run_generated_consent_controller(
            control=controller, storage=ga_choice["storage"], action="dispatch-ready-twice"
        )
        self.assertEqual(len(duplicate_guard["attempts"]), 1)

        declined = _run_generated_consent_controller(
            control=controller, storage=None, action="decline"
        )
        self.assertEqual(declined["attempts"], [])
        self.assertEqual(declined["reloads"], 1)
        self.assertEqual(
            json.loads(declined["storage"]["cde_optional_analytics_preferences_v2"]),
            {"v": 1, "ga": False, "clarity": False, "expires": unittest.mock.ANY},
        )

    def test_generated_controller_removes_pending_loader_and_invalidates_stale_callback_on_withdrawal(self):
        controller = self._controller()
        stored = {
            "cde_optional_analytics_preferences_v2": json.dumps(
                {"v": 1, "expires": 4102444800000, "ga": True, "clarity": True}
            )
        }
        result = _run_generated_consent_controller(
            control=controller, storage=stored, action="withdraw-ga"
        )
        self.assertEqual(len(result["attempts"]), 2)
        self.assertEqual((result["google"], result["clarity"]), (0, 0))
        self.assertEqual(result["removedGoogle"], 1)
        self.assertEqual(result["removedClarity"], 1)
        self.assertEqual(result["reloads"], 1)
        self.assertGreater(result["cookieWrites"], 0)
        self.assertEqual(
            json.loads(result["storage"]["cde_optional_analytics_preferences_v2"])["ga"],
            False,
        )

    def test_generated_controller_fails_closed_for_malformed_or_expired_preference(self):
        controller = self._controller()
        for value in (
            "not-json",
            json.dumps({"v": 1, "expires": 1, "ga": True, "clarity": False}),
            json.dumps({"v": 1, "expires": 4102444800000, "ga": "yes", "clarity": False}),
        ):
            with self.subTest(value=value):
                result = _run_generated_consent_controller(
                    control=controller,
                    storage={"cde_optional_analytics_preferences_v2": value},
                    action="none",
                )
                self.assertEqual(result["attempts"], [])
                self.assertEqual((result["google"], result["clarity"]), (0, 0))

    def test_identifier_free_clear_preferences_control_is_available_only_on_eligible_routes_when_disabled(self):
        with patch.dict(os.environ, {}, clear=True):
            control = public_origin.inject_public_html_head(
                b"<html><head></head><body>public content</body></html>", "/"
            ).decode("utf-8")
            excluded = public_origin.inject_public_html_head(
                b"<html><head></head><body>private</body></html>", "/records/R-1"
            )
        self.assertIn("data-cde-analytics-preferences-clear", control)
        self.assertNotIn(public_origin.GOOGLE_ANALYTICS_MEASUREMENT_ID, control)
        self.assertNotIn(public_origin.CLARITY_PROJECT_ID, control)
        self.assertNotIn("googletagmanager.com", control)
        self.assertNotIn("clarity.ms/tag", control)
        self.assertNotIn(b"data-cde-analytics-preferences-clear", excluded)
        cleared = _run_generated_consent_controller(
            control=control,
            storage={"cde_optional_analytics_preferences_v2": "valid-but-unneeded"},
            action="clear",
        )
        self.assertTrue(cleared["clear"])
        self.assertNotIn("cde_optional_analytics_preferences_v2", cleared["storage"])
        self.assertEqual(cleared["attempts"], [])
        self.assertEqual(cleared["reloads"], 1)

    def test_disabled_privacy_entry_is_visible_accessibly_styled_and_distinguishes_saved_preferences(self):
        with patch.dict(os.environ, {}, clear=True):
            control = public_origin.inject_public_html_head(
                b"<html><head></head><body>public content</body></html>", "/"
            ).decode("utf-8")
        self.assertIn('data-cde-analytics-style="1"', control)
        self.assertIn('entry.className="cde-analytics-entry"', control)
        self.assertIn('href=\\"/privacy\\"', control)
        self.assertIn("analytics_providers_disabled", control)
        self.assertIn("analytics_clear_preferences", control)
        self.assertIn("max-width:calc(100vw - 2rem)", control)
        self.assertIn(":focus-visible", control)
        self.assertNotIn("gtag/js", control)
        self.assertNotIn("clarity.ms/tag", control)

    def test_active_preferences_keep_unavailable_provider_distinct_from_saved_choice(self):
        controller = self._controller(clarity=False, google=True)
        self.assertIn('choices.innerHTML=(googleEnabled?', controller)
        self.assertIn("analytics_provider_disabled", controller)
        self.assertNotIn("data-cde-clarity-choice-row", controller)

    def test_unsaved_enabled_provider_opens_separate_choices_without_loading(self):
        result = _run_generated_consent_controller(
            control=self._controller(clarity=False, google=True), storage=None, action="none"
        )
        self.assertFalse(result["panelHidden"])
        self.assertEqual(result["gaChoiceCount"], 1)
        self.assertEqual(result["clarityChoiceCount"], 0)
        self.assertEqual(result["attempts"], [])

    def test_disabled_provider_panel_opens_from_persistent_preferences_control(self):
        with patch.dict(os.environ, {}, clear=True):
            control = public_origin.inject_public_html_head(
                b"<html><head></head><body>public content</body></html>", "/"
            ).decode("utf-8")
        result = _run_generated_consent_controller(control=control, storage=None, action="none")
        self.assertTrue(result["panelHidden"])
        self.assertTrue(result["clear"])
        self.assertIn('setAttribute("data-cde-analytics-disabled-panel","1")', control)
        self.assertIn('setAttribute("data-cde-analytics-preferences","1")', control)

    def test_disabled_preferences_control_has_visible_english_fallback_without_i18n(self):
        with patch.dict(os.environ, {}, clear=True):
            control = public_origin.inject_public_html_head(
                b"<html><head></head><body>public content</body></html>", "/"
            ).decode("utf-8")
        result = _run_generated_consent_controller(
            control=control, storage=None, action="without-i18n"
        )
        self.assertEqual(result["preferencesText"], "Privacy preferences")

    def test_disabled_provider_has_status_but_no_consent_input(self):
        result = _run_generated_consent_controller(
            control=self._controller(clarity=False, google=True), storage=None, action="none"
        )
        self.assertEqual(result["gaChoiceCount"], 1)
        self.assertEqual(result["clarityChoiceCount"], 0)

    def test_google_is_limited_to_the_query_free_home_page(self):
        html = b"<html><head></head><body>public content</body></html>"
        with patch.dict(
            os.environ,
            {
                public_origin.CLARITY_ENABLED_ENV: "1",
                public_origin.GOOGLE_ANALYTICS_ENABLED_ENV: "1",
            },
            clear=False,
        ):
            root = public_origin.inject_public_html_head(html, "/")
            archive = public_origin.inject_public_html_head(html, "/archive")
        root_result = _run_generated_consent_controller(
            control=root.decode(), storage=None, action="none"
        )
        archive_result = _run_generated_consent_controller(
            control=archive.decode(), storage=None, action="none"
        )
        self.assertEqual((root_result["gaChoiceCount"], root_result["clarityChoiceCount"]), (1, 1))
        self.assertEqual(
            (archive_result["gaChoiceCount"], archive_result["clarityChoiceCount"]),
            (0, 1),
        )
        self.assertNotIn(public_origin.GOOGLE_ANALYTICS_MEASUREMENT_ID.encode(), archive)
        self.assertIn(public_origin.CLARITY_PROJECT_ID.encode(), archive)

    def test_google_pageview_payload_uses_only_fixed_home_metadata(self):
        control = self._controller(clarity=False, google=True)
        self.assertIn(
            'var pageLocation="https://civicdecisionengine.ie/",'
            'pageTitle="Civic Decision Engine";',
            control,
        )
        self.assertIn("send_page_view:false", control)
        self.assertIn('page_referrer:"",ignore_referrer:true', control)
        self.assertIn(
            'window.gtag("event","page_view",{page_location:pageLocation,'
            'page_title:pageTitle,page_referrer:"",ignore_referrer:true})',
            control,
        )
        self.assertNotIn("document.location", control)
        self.assertNotIn("document.referrer", control)
        self.assertNotIn("document.title", control)

    def test_home_page_does_not_emit_custom_analytics_event_metadata(self):
        source = Path("api/static/index.html").read_text(encoding="utf-8")
        self.assertIn("function trackEvent(_eventName, _params = {})", source)
        self.assertNotIn('gtag("event", eventName', source)

    def test_privacy_notice_status_is_configuration_aware_without_identifiers(self):
        with patch.dict(os.environ, {}, clear=True):
            disabled = public_origin.privacy_notice_google_analytics_status()
        with patch.dict(
            os.environ,
            {
                public_origin.CLARITY_ENABLED_ENV: "1",
                public_origin.GOOGLE_ANALYTICS_ENABLED_ENV: "1",
            },
            clear=False,
        ):
            enabled = public_origin.privacy_notice_google_analytics_status()
        self.assertIn("Google Analytics loading is currently disabled", disabled)
        self.assertIn("Google Analytics loading is enabled only", enabled)
        self.assertNotIn(public_origin.GOOGLE_ANALYTICS_MEASUREMENT_ID, enabled)
        self.assertNotIn(public_origin.CLARITY_PROJECT_ID, enabled)

    def test_privacy_notice_status_fails_closed_for_incomplete_test_identifiers(self):
        environment = {
            public_origin.CANONICAL_PUBLIC_ORIGIN_ENV: "https://analytics-test.example.test",
            public_origin.ANALYTICS_TEST_MODE_ENV: "1",
            public_origin.ANALYTICS_TEST_ORIGIN_ENV: "https://analytics-test.example.test",
            public_origin.GOOGLE_ANALYTICS_ENABLED_ENV: "1",
            public_origin.CLARITY_ENABLED_ENV: "1",
        }
        with patch.dict(os.environ, environment, clear=True):
            status = public_origin.privacy_notice_google_analytics_status()
        self.assertIn("Google Analytics loading is currently disabled", status)

    def test_explicit_test_mode_uses_only_valid_nonproduction_identifiers(self):
        test_origin = "https://analytics-test.example.test"
        google_id = "G-TEST1234"
        clarity_id = "abc123def4"
        environment = {
            public_origin.CANONICAL_PUBLIC_ORIGIN_ENV: test_origin,
            public_origin.ANALYTICS_TEST_MODE_ENV: "1",
            public_origin.ANALYTICS_TEST_ORIGIN_ENV: test_origin,
            public_origin.ANALYTICS_TEST_GOOGLE_MEASUREMENT_ID_ENV: google_id,
            public_origin.ANALYTICS_TEST_CLARITY_PROJECT_ID_ENV: clarity_id,
            public_origin.CLARITY_ENABLED_ENV: "1",
            public_origin.GOOGLE_ANALYTICS_ENABLED_ENV: "1",
        }
        with patch.dict(os.environ, environment, clear=True):
            self.assertEqual(
                public_origin.analytics_identifier_configuration(),
                (google_id, clarity_id),
            )
            result = public_origin.inject_public_html_head(
                b"<html><head></head><body>synthetic</body></html>", "/"
            )

        self.assertIn(google_id.encode(), result)
        self.assertIn(clarity_id.encode(), result)
        self.assertNotIn(public_origin.GOOGLE_ANALYTICS_MEASUREMENT_ID.encode(), result)
        self.assertNotIn(public_origin.CLARITY_PROJECT_ID.encode(), result)
        self.assertLess(
            result.index(b'window.gtag("consent","default"'),
            result.index(b'window.gtag("config","G-TEST1234"'),
        )
        self.assertLess(
            result.index(b'window.gtag("config","G-TEST1234"'),
            result.index(b"gtag/js?id=G-TEST1234"),
        )

    def test_invalid_test_mode_never_falls_back_to_production_identifiers(self):
        baseline = {
            public_origin.CANONICAL_PUBLIC_ORIGIN_ENV: "https://analytics-test.example.test",
            public_origin.ANALYTICS_TEST_MODE_ENV: "1",
            public_origin.ANALYTICS_TEST_ORIGIN_ENV: "https://analytics-test.example.test",
            public_origin.ANALYTICS_TEST_GOOGLE_MEASUREMENT_ID_ENV: "G-TEST1234",
            public_origin.ANALYTICS_TEST_CLARITY_PROJECT_ID_ENV: "abc123def4",
            public_origin.CLARITY_ENABLED_ENV: "1",
            public_origin.GOOGLE_ANALYTICS_ENABLED_ENV: "1",
        }
        invalid = (
            {},
            {public_origin.ANALYTICS_TEST_GOOGLE_MEASUREMENT_ID_ENV: "bad\";alert(1)//"},
            {public_origin.ANALYTICS_TEST_CLARITY_PROJECT_ID_ENV: "bad<script>"},
            {
                public_origin.ANALYTICS_TEST_GOOGLE_MEASUREMENT_ID_ENV: public_origin.GOOGLE_ANALYTICS_MEASUREMENT_ID
            },
            {public_origin.ANALYTICS_TEST_CLARITY_PROJECT_ID_ENV: public_origin.CLARITY_PROJECT_ID},
            {public_origin.ANALYTICS_TEST_ORIGIN_ENV: "https://other-test.example.test"},
        )
        for override in invalid:
            with self.subTest(override=override):
                environment = {**baseline, **override}
                if not override:
                    environment.pop(public_origin.ANALYTICS_TEST_GOOGLE_MEASUREMENT_ID_ENV)
                with patch.dict(os.environ, environment, clear=True):
                    self.assertEqual(public_origin.analytics_identifier_configuration(), (None, None))
                    result = public_origin.inject_public_html_head(
                        b"<html><head></head><body>synthetic</body></html>", "/"
                    )
                self.assertNotIn(b"data-cde-clarity-consent", result)
                self.assertNotIn(public_origin.GOOGLE_ANALYTICS_MEASUREMENT_ID.encode(), result)
                self.assertNotIn(public_origin.CLARITY_PROJECT_ID.encode(), result)

    def test_test_mode_rejects_production_origins_and_known_aliases(self):
        for origin in (
            "https://civicdecisionengine.ie",
            "https://www.civicdecisionengine.ie",
            "https://civic-decision-engine-production.up.railway.app",
            "https://civicdecisionengine.ie.example.test",
            "https://civic-decision-engine-production.up.railway.app.example.test",
        ):
            with self.subTest(origin=origin), patch.dict(
                os.environ,
                {
                    public_origin.CANONICAL_PUBLIC_ORIGIN_ENV: origin,
                    public_origin.ANALYTICS_TEST_MODE_ENV: "1",
                    public_origin.ANALYTICS_TEST_ORIGIN_ENV: origin,
                    public_origin.ANALYTICS_TEST_GOOGLE_MEASUREMENT_ID_ENV: "G-TEST1234",
                    public_origin.ANALYTICS_TEST_CLARITY_PROJECT_ID_ENV: "abc123def4",
                },
                clear=True,
            ):
                self.assertEqual(public_origin.analytics_identifier_configuration(), (None, None))

    def test_request_host_and_forwarded_host_cannot_select_test_identifiers(self):
        environment = {
            public_origin.CANONICAL_PUBLIC_ORIGIN_ENV: "https://analytics-test.example.test",
            public_origin.ANALYTICS_TEST_MODE_ENV: "1",
            public_origin.ANALYTICS_TEST_ORIGIN_ENV: "https://analytics-test.example.test",
            public_origin.ANALYTICS_TEST_GOOGLE_MEASUREMENT_ID_ENV: "G-TEST1234",
            public_origin.ANALYTICS_TEST_CLARITY_PROJECT_ID_ENV: "abc123def4",
            public_origin.CLARITY_ENABLED_ENV: "1",
            public_origin.GOOGLE_ANALYTICS_ENABLED_ENV: "1",
        }
        with patch.dict(os.environ, environment, clear=True):
            _, body = self.asgi_get(
                "/",
                "civicdecisionengine.ie",
                extra_headers=((b"x-forwarded-host", b"attacker.example"),),
            )

        self.assertIn(b"G-TEST1234", body)
        self.assertIn(b"abc123def4", body)
        self.assertNotIn(public_origin.GOOGLE_ANALYTICS_MEASUREMENT_ID.encode(), body)
        self.assertNotIn(public_origin.CLARITY_PROJECT_ID.encode(), body)

    def test_optional_analytics_preference_schema_fails_closed_for_legacy_or_invalid_values(self):
        with patch.dict(
            os.environ,
            {
                public_origin.CLARITY_ENABLED_ENV: "1",
                public_origin.GOOGLE_ANALYTICS_ENABLED_ENV: "1",
            },
            clear=False,
        ):
            result = public_origin.inject_public_html_head(
                b"<html><head></head><body>ok</body></html>", "/"
            )
        self.assertIn(b"JSON.parse(raw)", result)
        self.assertIn(b"v.v!==1", result)
        self.assertIn(b"v.expires<=Date.now()", result)
        self.assertIn(b"typeof v.ga!==\"boolean\"", result)
        self.assertIn(b"typeof v.clarity!==\"boolean\"", result)
        self.assertIn(b"window.localStorage.removeItem(legacyKey)", result)
        self.assertIn(b"eraseGoogle();eraseClarity()", result)
        self.assertLess(
            result.index(b"window.gtag(\"consent\",\"default\""),
            result.index(b"window.gtag(\"config\""),
        )
        self.assertLess(
            result.index(b"q(\"consentv2\",{ad_Storage:\"denied\",analytics_Storage:\"granted\"})"),
            result.index(b"https://www.clarity.ms/tag/"),
        )
        self.assertIn(b"if(current){load(current);hide()}else if(googleEnabled||clarityEnabled){showChoices()}else{hide()}", result)

    def test_google_withdrawal_erases_observed_domain_scoped_cookie_variants_before_reload(self):
        """GA withdrawal must expire host and domain cookie scopes, not just host scope.

        The isolated-provider test observed ``_ga`` cookies scoped to the
        leading-dot test hostname and ``/``.  This verifies the actual ASGI
        response carries deletion attempts for that scope as well as host-only
        cookies and that the GA-only branch is ordered before the clean reload.
        """
        with patch.dict(
            os.environ,
            {
                public_origin.CLARITY_ENABLED_ENV: "1",
                public_origin.GOOGLE_ANALYTICS_ENABLED_ENV: "1",
            },
            clear=False,
        ):
            start, result = self.asgi_get("/", "civicdecisionengine.ie")

        self.assertEqual(start["status"], 200)
        self.assertIn(b'var labels=location.hostname.split("."),scopes=[""]', result)
        self.assertIn(b'scopes.push(";domain="+d,";domain=."+d)', result)
        self.assertIn(b'Max-Age=0;path=/"+scope+";SameSite=Lax', result)
        self.assertIn(b'function eraseGoogle(){erase(/^_ga(?:_|$)/)}', result)
        self.assertIn(b'if(!next.ga){removeLoaders("script[data-cde-google-loader=', result)
        self.assertIn(b'eraseGoogle();if(typeof window.gtag==="function")', result)
        self.assertIn(b'if(!next.clarity){removeLoaders("script[data-cde-clarity-loader=', result)
        self.assertIn(b'if(typeof window.clarity==="function")', result)
        self.assertLess(
            result.index(b'if(!next.ga){removeLoaders("script[data-cde-google-loader='),
            result.index(b'window.location.reload()'),
        )

    def test_ga_can_be_consent_gated_while_clarity_remains_disabled(self):
        with patch.dict(
            os.environ,
            {
                public_origin.CLARITY_ENABLED_ENV: "0",
                public_origin.GOOGLE_ANALYTICS_ENABLED_ENV: "1",
            },
            clear=False,
        ):
            result = public_origin.inject_public_html_head(
                b"<html><head></head><body>ok</body></html>", "/"
            )
        self.assertIn(b"googleEnabled=true", result)
        self.assertIn(b"clarityEnabled=false", result)
        self.assertNotIn(b'<script src="https://www.googletagmanager.com/', result)

    def test_clarity_control_is_excluded_from_private_dynamic_and_query_pages(self):
        html = b"<html><head></head><body>ok</body></html>"
        for path in (
            "/admin",
            "/api/docs",
            "/records",
            "/records/R-1",
            "/verify/R-1",
            "/documents/D-1",
            "/governed-reports/gr-1.json",
        ):
            with self.subTest(path=path):
                result = public_origin.inject_public_html_head(html, path)
                self.assertNotIn(b"data-cde-clarity-consent", result)

        with patch.dict(
            os.environ,
            {
                public_origin.CLARITY_ENABLED_ENV: "1",
                public_origin.GOOGLE_ANALYTICS_ENABLED_ENV: "1",
            },
            clear=False,
        ):
            start, body = self.asgi_get("/", "civicdecisionengine.ie", b"sensitive=1")
            self.assertEqual(start["status"], 200)
            self.assertNotIn(b"data-cde-clarity-consent", body)

    def test_only_explicit_public_paths_are_indexable(self):
        for path in ("/", "/records", "/determinations", "/verify/R-1"):
            with self.subTest(path=path):
                self.assertTrue(public_origin.is_public_indexable_path(path))
        for path in ("/admin", "/api/admin/records", "/health", "/api/records"):
            with self.subTest(path=path):
                self.assertFalse(public_origin.is_public_indexable_path(path))

    def test_governed_report_review_and_artifact_paths_are_not_public_or_indexable(self):
        for path in (
            "/governed-reports",
            "/governed-reports/",
            "/governed-reports/1",
            "/governed-reports/1/",
            "/governed-reports/1/artifacts/2",
            "/governed-reports/1/reviews",
            "/governed-reports/1/eligibility",
            "/governed-reports/gr-1.json/anything",
            "/governed-reports/gr-0.json",
            "/governed-reports/gr-01.json",
            "/governed-reports/gr-identifier.json",
            "/governed-reports/1.json",
            "/governed-reports/gr-1.pdf",
            "/governed-reports/gr-1%2Fartifacts%2F2.json",
            "/governed-reports/gr-1.json/../artifacts/2",
            "/admin/governed-reports/1/publication-reviews",
            "/api/admin/session/governed-reports/1/publication-reviews",
        ):
            with self.subTest(path=path):
                self.assertFalse(public_origin.is_public_indexable_path(path))
        start, body = self.asgi_get("/governed-reports/1", "civicdecisionengine.ie")
        self.assertEqual(start["status"], 404)
        self.assertNotIn(b"governed", body.lower())

    def test_exact_stage79_machine_readable_publication_path_is_indexable(self):
        for path in (
            "/governed-reports/gr-1.json",
            "/governed-reports/gr-42.json",
        ):
            with self.subTest(path=path):
                self.assertTrue(public_origin.is_public_indexable_path(path))
                self.assertEqual(
                    public_origin.canonical_url(path),
                    f"https://civicdecisionengine.ie{path}",
                )

    def test_asgi_redirects_only_public_aliases_and_preserves_path_query(self):
        start, _ = self.asgi_get("/records", "www.civicdecisionengine.ie", b"page=2")
        headers = dict(start["headers"])
        self.assertEqual(start["status"], 308)
        self.assertEqual(headers[b"location"], b"https://civicdecisionengine.ie/records?page=2")

        start, _ = self.asgi_get("/verify/R-1", "civic-decision-engine-production.up.railway.app")
        self.assertEqual(start["status"], 308)
        self.assertEqual(
            dict(start["headers"])[b"location"],
            b"https://civicdecisionengine.ie/verify/R-1",
        )

    def test_asgi_canonical_and_local_hosts_serve_root_with_fixed_metadata(self):
        for host in ("civicdecisionengine.ie", "localhost:8000", "attacker.example"):
            with self.subTest(host=host):
                start, body = self.asgi_get("/", host)
                self.assertEqual(start["status"], 200)
                self.assertEqual(body.count(b'rel="canonical"'), 1)
                self.assertIn(b'https://civicdecisionengine.ie/"', body)
                self.assertNotIn(b"data-cde-clarity-consent", body)

    def test_asgi_renders_one_default_off_separate_analytics_control_only_when_enabled(self):
        with patch.dict(
            os.environ,
            {
                public_origin.CLARITY_ENABLED_ENV: "1",
                public_origin.GOOGLE_ANALYTICS_ENABLED_ENV: "1",
            },
            clear=False,
        ):
            start, body = self.asgi_get("/", "civicdecisionengine.ie")
        self.assertEqual(start["status"], 200)
        self.assertEqual(body.count(b'data-cde-clarity-consent="1"'), 1)
        self.assertNotIn(b'<script src="https://www.clarity.ms/tag/', body)
        self.assertIn(b"analytics_decline_both", body)
        self.assertIn(b"analytics_preferences", body)
        self.assertIn(b"aria-labelledby", body)
        self.assertNotIn(b'<script async src="https://www.googletagmanager.com/', body)
        self.assertIn(b"data-cde-google-loader", body)

    def test_optional_analytics_strings_are_complete_for_every_supported_language(self):
        source = Path("api/static/translations.js").read_text(encoding="utf-8")
        for language in ("en", "ga", "fr", "de", "es", "pl", "ro", "uk"):
            with self.subTest(language=language):
                block_start = source.index(f"    {language}: {{")
                next_start = source.find("\n    },\n\n    ", block_start)
                block = source[block_start : next_start if next_start != -1 else None]
                for key in (
                    "analytics_description",
                    "analytics_decline_both",
                    "analytics_preferences",
                    "analytics_preferences_label",
                    "analytics_clear_preferences",
                    "analytics_providers_disabled",
                    "analytics_provider_disabled",
                    "analytics_ga_choice",
                    "analytics_clarity_choice",
                    "analytics_save_choices",
                    "analytics_privacy_notice",
                    "privacy_notice",
                ):
                    self.assertIn(f"{key}:", block)

    def test_analytics_banner_text_requires_operational_enablement_and_choice_in_every_language(self):
        source = Path("api/static/translations.js").read_text(encoding="utf-8")
        self.assertNotIn("Both are off unless you choose them.", source)
        for language in ("en", "ga", "fr", "de", "es", "pl", "ro", "uk"):
            with self.subTest(language=language):
                block_start = source.index(f"    {language}: {{")
                next_start = source.find("\n    },\n\n    ", block_start)
                block = source[block_start : next_start if next_start != -1 else None]
                description = re.search(
                    r'analytics_description:\s+"([^"]+)"', block
                )
                self.assertIsNotNone(description)
                self.assertIn("CDE", description.group(1))

    def test_optional_analytics_ui_has_equal_choice_actions_and_privacy_notice_link(self):
        with patch.dict(
            os.environ,
            {
                public_origin.CLARITY_ENABLED_ENV: "1",
                public_origin.GOOGLE_ANALYTICS_ENABLED_ENV: "1",
            },
            clear=False,
        ):
            result = public_origin.inject_public_html_head(
                b"<html><head></head><body>ok</body></html>", "/"
            )
        self.assertEqual(result.count(b'class=\\"cde-analytics-action\\"'), 2)
        self.assertEqual(result.count(b"data-cde-analytics-decline data-cde-analytics-text"), 1)
        self.assertIn(b"else if(googleEnabled||clarityEnabled){showChoices()}", result)
        self.assertIn(b"data-cde-analytics-choice-list", result)
        self.assertIn(b"choices.innerHTML=(googleEnabled?", result)
        self.assertIn(b'href=\\"/privacy\\"', result)
        self.assertIn(b"analytics_privacy_notice", result)

    def test_privacy_notice_is_public_but_outside_analytics_eligibility(self):
        with patch.dict(
            os.environ,
            {
                public_origin.CLARITY_ENABLED_ENV: "0",
                public_origin.GOOGLE_ANALYTICS_ENABLED_ENV: "0",
            },
            clear=False,
        ):
            start, body = self.asgi_get("/privacy", "civicdecisionengine.ie")

        self.assertEqual(start["status"], 200)
        self.assertIn(b"Optional analytics status", body)
        self.assertIn(b"Privacy and user choice", body)
        self.assertIn(
            b"does not depend on tracking or on your analytics choices", body
        )
        self.assertIn(
            b"does not undo information already collected by a provider", body
        )
        self.assertIn(b"separate operational enablement", body)
        self.assertIn(b"Microsoft Clarity \xe2\x80\x94 disabled", body)
        self.assertIn(b"treated as expired when CDE reads it", body)
        self.assertNotIn(b"temporary validation", body)
        self.assertIn(b"Controller: Nick Moloney", body)
        self.assertIn(b"nickdebrief@gmail.com", body)
        self.assertIn(b"cde_optional_analytics_preferences_v2", body)
        self.assertNotIn(b"data-cde-clarity-consent", body)
        self.assertNotIn(b"googletagmanager.com/gtag/js", body)
        self.assertNotIn(b"clarity.ms/tag/", body)
        self.assertFalse(public_origin.is_clarity_eligible_public_path("/privacy"))
        self.assertIn((b"cache-control", b"no-store"), start["headers"])

    def test_privacy_notice_enabled_google_status_retains_disabled_clarity_notice(self):
        with patch.dict(
            os.environ,
            {
                public_origin.CLARITY_ENABLED_ENV: "1",
                public_origin.GOOGLE_ANALYTICS_ENABLED_ENV: "1",
            },
            clear=False,
        ):
            start, body = self.asgi_get("/privacy", "civicdecisionengine.ie")
        self.assertEqual(start["status"], 200)
        self.assertIn(b"Google Analytics loading is enabled only", body)
        self.assertIn(b"Microsoft Clarity is disabled", body)
        self.assertIn(b"Microsoft Clarity \xe2\x80\x94 disabled", body)
        self.assertIn(b"Microsoft Clarity is currently disabled", body)
        self.assertNotIn(b"Google Analytics is currently disabled", body)
        self.assertIn(b"must disable and verify the stream\xe2\x80\x99s top-level Enhanced Measurement control", body)
        self.assertIn(b"does not itself emit scroll, outbound-click, site-search, form-interaction, video-engagement, or file-download events", body)
        self.assertIn(b"may still generate documented automatic events", body)
        self.assertNotIn(b"CDE does not enable enhanced measurement", body)

    def test_privacy_notice_link_is_present_in_the_public_footer(self):
        source = Path("api/static/index.html").read_text(encoding="utf-8")
        self.assertIn('href="/privacy" data-i18n="privacy_notice"', source)

    def test_root_has_no_historical_unconditional_google_analytics_loader(self):
        start, body = self.asgi_get("/", "civicdecisionengine.ie")

        self.assertEqual(start["status"], 200)
        self.assertNotIn(b"googletagmanager.com/gtag/js", body)
        self.assertNotIn(b'gtag("config"', body)
        self.assertNotIn(b"G-8405RVT76Q", body)

    def test_public_export_and_qr_dependencies_are_local_versioned_assets(self):
        source = Path("api/static/index.html").read_text(encoding="utf-8")
        assets = {
            "/static/vendor/html2canvas-1.4.1.min.js": "html2canvas-1.4.1.min.js",
            "/static/vendor/jspdf-2.5.1.umd.min.js": "jspdf-2.5.1.umd.min.js",
            "/static/vendor/qrcodejs-1.0.0.min.js": "qrcodejs-1.0.0.min.js",
        }
        self.assertNotIn("cdnjs.cloudflare.com", source)
        for url, filename in assets.items():
            with self.subTest(url=url):
                self.assertIn(f'src="{url}"', source)
                self.assertTrue((Path("api/static/vendor") / filename).is_file())

        start, body = self.asgi_get("/", "civicdecisionengine.ie")
        self.assertEqual(start["status"], 200)
        for url in assets:
            self.assertIn(url.encode(), body)

    def test_indexnow_ownership_key_is_fixed_text_and_respects_host_policy(self):
        key = "199f69ef74214688b3aff215441ae226"
        path = f"/{key}.txt"

        start, body = self.asgi_get(path, "civicdecisionengine.ie")
        headers = dict(start["headers"])
        self.assertEqual(start["status"], 200)
        self.assertEqual(body, key.encode("ascii"))
        self.assertTrue(headers[b"content-type"].startswith(b"text/plain"))
        self.assertNotIn(b"location", headers)

        head_start, _ = self.asgi_get(path, "civicdecisionengine.ie", method="HEAD")
        self.assertEqual(head_start["status"], 200)
        self.assertTrue(
            dict(head_start["headers"])[b"content-type"].startswith(b"text/plain")
        )

        for host in (
            "www.civicdecisionengine.ie",
            "civic-decision-engine-production.up.railway.app",
        ):
            with self.subTest(host=host):
                start, _ = self.asgi_get(path, host, b"source=alias")
                self.assertEqual(start["status"], 308)
                self.assertEqual(
                    dict(start["headers"])[b"location"],
                    f"https://civicdecisionengine.ie{path}?source=alias".encode("ascii"),
                )

        start, body = self.asgi_get(f"{path}/extra", "civicdecisionengine.ie")
        self.assertEqual(start["status"], 404)
        self.assertNotIn(key.encode("ascii"), body)
