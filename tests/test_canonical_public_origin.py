import os
import asyncio
import unittest
from pathlib import Path
from api import governed_report_publications as stage79_publications
from unittest.mock import patch

from api import public_origin


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
        self.assertNotIn(
            b"data-cde-clarity-consent",
            public_origin.inject_public_html_head(html, "/"),
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
        self.assertIn(b"data-cde-analytics-banner", first)
        self.assertIn(b"data-cde-analytics-accept", first)
        self.assertIn(b"data-cde-analytics-decline", first)
        self.assertIn(b"data-cde-analytics-choose", first)
        self.assertIn(b"data-cde-analytics-text=\\\"analytics_title\\\"", first)
        self.assertIn(b"data-cde-ga-choice", first)
        self.assertIn(b"data-cde-clarity-choice", first)
        self.assertIn(b"data-cde-analytics-i18n", first)
        self.assertIn(b"cde-i18n-applied", first)
        self.assertIn(b"ga:!!v.ga,clarity:!!v.clarity", first)
        self.assertNotIn(b"Accept optional analytics", first)

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
        self.assertIn(b"if(current){load(current);hide()}else{banner.hidden=false}", result)

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
        self.assertIn(b"data-cde-analytics-banner", body)
        self.assertIn(b"analytics_accept_both", body)
        self.assertIn(b"analytics_decline_both", body)
        self.assertIn(b"analytics_choose_separately", body)
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
                    "analytics_title",
                    "analytics_description",
                    "analytics_accept_both",
                    "analytics_decline_both",
                    "analytics_choose_separately",
                    "analytics_preferences",
                    "analytics_preferences_label",
                    "analytics_ga_choice",
                    "analytics_clarity_choice",
                    "analytics_save_choices",
                    "analytics_privacy_notice",
                    "privacy_notice",
                ):
                    self.assertIn(f"{key}:", block)

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
        self.assertEqual(result.count(b'class=\\"cde-analytics-action\\"'), 5)
        self.assertEqual(
            result.count(b"data-cde-analytics-decline data-cde-analytics-text"),
            2,
        )
        self.assertIn(b"banner.querySelector(\"[data-cde-analytics-accept]\")", result)
        self.assertIn(b"banner.querySelector(\"[data-cde-analytics-choose]\")", result)
        self.assertIn(b'href=\\"/privacy\\"', result)
        self.assertIn(b"analytics_privacy_notice", result)

    def test_privacy_notice_is_public_but_outside_analytics_eligibility(self):
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
        self.assertIn(b"Optional analytics status", body)
        self.assertIn(b"both its operational switch and your affirmative choice are valid", body)
        self.assertIn(b"separate, valid affirmative choice", body)
        self.assertIn(b"Controller: Nick Moloney", body)
        self.assertIn(b"nickdebrief@gmail.com", body)
        self.assertIn(b"cde_optional_analytics_preferences_v2", body)
        self.assertNotIn(b"data-cde-clarity-consent", body)
        self.assertNotIn(b"googletagmanager.com/gtag/js", body)
        self.assertNotIn(b"clarity.ms/tag/", body)
        self.assertFalse(public_origin.is_clarity_eligible_public_path("/privacy"))

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
