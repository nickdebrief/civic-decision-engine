import os
import asyncio
import unittest
from api import governed_report_publications as stage79_publications
from unittest.mock import patch

from api import public_origin


class CanonicalPublicOriginTests(unittest.TestCase):
    def asgi_get(self, path, host, query=b"", method="GET"):
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
            "headers": [(b"host", host.encode())],
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
