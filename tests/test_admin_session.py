import base64
import hashlib
import importlib
import json
import os
import sqlite3
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from api.attachments import (
    ensure_attachment_tables,
    public_evidence_manifest_attachments,
    public_manifest_attachments,
)


class FakeAPIRouter:
    def get(self, *args, **kwargs):
        return lambda func: func

    def post(self, *args, **kwargs):
        return lambda func: func

    def patch(self, *args, **kwargs):
        return lambda func: func


class FakeHTTPException(Exception):
    def __init__(self, status_code=None, detail=None):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class FakeResponse:
    def __init__(self, content=None, status_code=200, media_type=None, headers=None):
        self.content = content
        self.status_code = status_code
        self.media_type = media_type
        self.headers = headers or {}


class FakeJSONResponse(FakeResponse):
    def set_cookie(
        self,
        *,
        key,
        value,
        max_age=None,
        httponly=False,
        secure=False,
        samesite=None,
        **_kwargs,
    ):
        parts = [f"{key}={value}"]
        if max_age is not None:
            parts.append(f"Max-Age={max_age}")
        if httponly:
            parts.append("HttpOnly")
        if secure:
            parts.append("Secure")
        if samesite:
            parts.append(f"SameSite={samesite.capitalize()}")
        self.headers["Set-Cookie"] = "; ".join(parts)

    def delete_cookie(
        self, *, key, httponly=False, secure=False, samesite=None, **_kwargs
    ):
        parts = [f"{key}=", "Max-Age=0"]
        if httponly:
            parts.append("HttpOnly")
        if secure:
            parts.append("Secure")
        if samesite:
            parts.append(f"SameSite={samesite.capitalize()}")
        self.headers["Set-Cookie"] = "; ".join(parts)


def install_fastapi_stubs():
    fastapi = sys.modules.get("fastapi") or types.ModuleType("fastapi")
    fastapi.APIRouter = FakeAPIRouter
    fastapi.File = lambda default=None, **kwargs: default
    fastapi.Form = lambda default=None, **kwargs: default
    fastapi.Header = lambda default=None, **kwargs: default
    fastapi.HTTPException = FakeHTTPException
    fastapi.Query = lambda default=None, **kwargs: default
    fastapi.Request = FakeRequest
    fastapi.UploadFile = object

    responses = sys.modules.get("fastapi.responses") or types.ModuleType(
        "fastapi.responses"
    )
    responses.HTMLResponse = FakeResponse
    responses.JSONResponse = FakeJSONResponse
    responses.Response = FakeResponse

    models = types.ModuleType("api.models")
    models.RecordPayload = type("RecordPayload", (), {})
    models.RecordResponse = type("RecordResponse", (), {})

    sys.modules["fastapi"] = fastapi
    sys.modules["fastapi.responses"] = responses
    sys.modules.setdefault("api.models", models)


class FakeRequest:
    def __init__(self, cookies=None):
        self.cookies = cookies or {}


class AdminSessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        install_fastapi_stubs()
        cls.admin_session = importlib.import_module("api.routes.admin_session")

    def env(self):
        return patch.dict(
            os.environ,
            {
                "CDE_ADMIN_PASSWORD": "admin-password",
                "CDE_ADMIN_SESSION_SECRET": "session-secret",
                "CDE_ADMIN_TOKEN": "server-only-token",
            },
            clear=False,
        )

    def assert_no_admin_token_exposed(self, response):
        serialized = json.dumps(
            {
                "content": getattr(response, "content", None),
                "headers": getattr(response, "headers", {}),
            },
            sort_keys=True,
        )
        self.assertNotIn("server-only-token", serialized)
        self.assertNotIn("CDE_ADMIN_TOKEN", serialized)

    def session_from_response(self, response):
        cookie = response.headers["Set-Cookie"]
        prefix = f"{self.admin_session.SESSION_COOKIE_NAME}="
        self.assertTrue(cookie.startswith(prefix))
        return cookie[len(prefix) :].split(";", 1)[0]

    def test_login_page_renders_without_cde_admin_token(self):
        with self.env():
            response = self.admin_session.admin_login_page()

        self.assertIn("Civic Decision Engine Admin", response.content)
        self.assertIn('type="password"', response.content)
        self.assertNotIn("server-only-token", response.content)
        self.assertNotIn("CDE_ADMIN_TOKEN", response.content)
        self.assertNotIn("Upload", response.content)
        self.assertNotIn("attachment", response.content.lower())

    def test_successful_login_sets_secure_httponly_strict_cookie(self):
        with self.env():
            response = self.admin_session.admin_session_login("admin-password")

        cookie = response.headers["Set-Cookie"]

        self.assertEqual(response.content, {"ok": True, "role": "admin"})
        self.assertIn("cde_admin_session=", cookie)
        self.assertIn("Max-Age=3600", cookie)
        self.assertIn("HttpOnly", cookie)
        self.assertIn("Secure", cookie)
        self.assertIn("SameSite=Strict", cookie)
        self.assert_no_admin_token_exposed(response)

    def test_session_payload_contains_only_allowed_fields(self):
        with self.env():
            response = self.admin_session.admin_session_login("admin-password")

        session = self.session_from_response(response)
        payload_b64 = session.split(".", 1)[0]
        padding = "=" * (-len(payload_b64) % 4)
        payload = json.loads(
            base64.urlsafe_b64decode((payload_b64 + padding).encode("ascii")).decode(
                "utf-8"
            )
        )

        self.assertEqual(set(payload.keys()), {"role", "issued_at", "expires_at"})
        self.assertEqual(payload["role"], "admin")

    def test_invalid_login_returns_401_without_secret_details(self):
        with self.env():
            with self.assertRaises(Exception) as ctx:
                self.admin_session.admin_session_login("wrong-password")

        self.assertEqual(getattr(ctx.exception, "status_code", None), 401)
        self.assertEqual(
            getattr(ctx.exception, "detail", None), "admin_session_unauthorized"
        )
        self.assertNotIn("server-only-token", getattr(ctx.exception, "detail", ""))
        self.assertNotIn("admin-password", getattr(ctx.exception, "detail", ""))

    def test_missing_session_fails_require_admin_session(self):
        with self.env():
            with self.assertRaises(Exception) as ctx:
                self.admin_session.require_admin_session(FakeRequest())

        self.assertEqual(getattr(ctx.exception, "status_code", None), 401)

    def test_expired_session_fails_require_admin_session(self):
        with self.env():
            session = self.admin_session.create_admin_session(now=100)

        with self.env():
            with patch.object(self.admin_session.time, "time", return_value=3701):
                with self.assertRaises(Exception) as ctx:
                    self.admin_session.require_admin_session(
                        FakeRequest({self.admin_session.SESSION_COOKIE_NAME: session})
                    )

        self.assertEqual(getattr(ctx.exception, "status_code", None), 401)

    def test_valid_session_passes_require_admin_session(self):
        with self.env():
            session = self.admin_session.create_admin_session(now=100)

        with self.env():
            with patch.object(self.admin_session.time, "time", return_value=200):
                payload = self.admin_session.require_admin_session(
                    FakeRequest({self.admin_session.SESSION_COOKIE_NAME: session})
                )

        self.assertEqual(payload["role"], "admin")
        self.assertEqual(set(payload.keys()), {"role", "issued_at", "expires_at"})

    def test_logout_clears_cookie(self):
        response = self.admin_session.admin_session_logout()
        cookie = response.headers["Set-Cookie"]

        self.assertEqual(response.content, {"ok": True})
        self.assertIn("cde_admin_session=", cookie)
        self.assertIn("Max-Age=0", cookie)
        self.assertIn("HttpOnly", cookie)
        self.assertIn("Secure", cookie)
        self.assertIn("SameSite=Strict", cookie)
        self.assert_no_admin_token_exposed(response)

    def make_admin_listing_db(self, db_path):
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("""
            CREATE TABLE records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reference TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 1,
                verification_hash TEXT NOT NULL,
                conditions_json TEXT,
                signals_json TEXT,
                finding TEXT,
                source_narrative TEXT,
                report_json TEXT,
                is_latest INTEGER NOT NULL DEFAULT 1,
                UNIQUE(reference, version)
            )
        """)
        conn.execute(
            """
            INSERT INTO records (
                reference, version, verification_hash, conditions_json,
                signals_json, finding, source_narrative, report_json, is_latest
            )
            VALUES ('Strike-OT-20260604-ADMIN', 1, ?, ?, ?, ?, ?, ?, 1)
            """,
            (
                "c" * 64,
                json.dumps(
                    [
                        "INSTITUTIONAL_DELAY",
                        "PROCEDURAL_DEFLECTION",
                        "REPEATED_CONTACT_WITHOUT_RESOLUTION",
                        "Transfer of Burden",
                        "Escalation Without Response",
                    ]
                ),
                json.dumps(["Missing Response", {"name": "Procedural Loop"}]),
                "Finding <requires> review",
                "private source narrative must stay hidden",
                json.dumps({"private": "report json must stay hidden"}),
            ),
        )
        ensure_attachment_tables(conn)
        conn.commit()
        return conn

    def insert_admin_attachment(self, conn, **overrides):
        values = {
            "reference": "Strike-OT-20260604-ADMIN",
            "record_version": 1,
            "attachment_version": 1,
            "filename": "public.pdf",
            "stored_filename": "internal-public.pdf",
            "storage_path": "/private/path/internal-public.pdf",
            "content_type": "application/pdf",
            "file_size_bytes": 12345,
            "sha256_hash": "d" * 64,
            "visibility": "public",
            "redaction_status": "none",
            "title": "Public attachment",
            "description": "Attachment description",
            "source_label": "Attachment source",
            "document_date": "2026-06-04",
            "document_date_precision": "day",
            "publication_status": "internal",
            "uploaded_at": "2026-06-04T12:00:00Z",
            "is_latest": 1,
            "is_deleted": 0,
        }
        values.update(overrides)
        columns = ", ".join(values.keys())
        placeholders = ", ".join("?" for _ in values)
        conn.execute(
            f"INSERT INTO record_attachments ({columns}) VALUES ({placeholders})",
            list(values.values()),
        )
        conn.commit()

    def fetch_attachment_row(self, db_path, attachment_id=1):
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            return dict(
                conn.execute(
                    "SELECT * FROM record_attachments WHERE id = ?",
                    (attachment_id,),
                ).fetchone()
            )
        finally:
            conn.close()

    def insert_attachment_audit_event(self, conn, **overrides):
        values = {
            "attachment_id": 7,
            "reference": "Strike-OT-20260604-ADMIN",
            "record_version": 1,
            "event_type": "attachment_metadata_viewed",
            "actor": "admin",
            "occurred_at": "2026-06-04T13:00:00Z",
            "metadata_json": json.dumps(
                {
                    "note": "Audit <script>alert('x')</script>",
                    "storage_path": "/private/path/internal-public.pdf",
                    "source_narrative": "private raw narrative",
                },
                sort_keys=True,
            ),
            "request_id": "req-admin-001",
            "ip_hash": "ip-hash-hidden",
            "user_agent_hash": "ua-hash-hidden",
        }
        values.update(overrides)
        columns = ", ".join(values.keys())
        placeholders = ", ".join("?" for _ in values)
        conn.execute(
            f"INSERT INTO attachment_audit_events ({columns}) VALUES ({placeholders})",
            list(values.values()),
        )
        conn.commit()

    def insert_attachment_relationship(self, conn, **overrides):
        values = {
            "reference": "Strike-OT-20260604-ADMIN",
            "record_version": 1,
            "attachment_id": 1,
            "relationship_type": "supports",
            "target_type": "condition",
            "target_key": "Transfer of Burden",
            "is_active": 1,
            "created_at": "2026-06-04T13:30:00Z",
            "created_by": "admin",
        }
        values.update(overrides)
        columns = ", ".join(values.keys())
        placeholders = ", ".join("?" for _ in values)
        conn.execute(
            f"INSERT INTO record_attachment_relationships ({columns}) VALUES ({placeholders})",
            list(values.values()),
        )
        conn.commit()

    def valid_request(self):
        with self.env():
            session = self.admin_session.create_admin_session()
        return FakeRequest({self.admin_session.SESSION_COOKIE_NAME: session})

    def test_admin_attachment_listing_requires_session(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            conn.close()
            try:
                with self.env():
                    with self.assertRaises(Exception) as ctx:
                        self.admin_session.admin_record_attachments_page(
                            "Strike-OT-20260604-ADMIN",
                            FakeRequest(),
                        )
            finally:
                self.admin_session.DB_PATH = original_db_path

        self.assertEqual(getattr(ctx.exception, "status_code", None), 401)

    def test_admin_attachment_listing_displays_all_attachment_states(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            self.insert_admin_attachment(conn)
            self.insert_admin_attachment(
                conn,
                filename="private.pdf",
                stored_filename="internal-private.pdf",
                storage_path="/private/path/internal-private.pdf",
                visibility="private",
                title="Private attachment",
            )
            self.insert_admin_attachment(
                conn,
                filename="withheld.pdf",
                stored_filename="internal-withheld.pdf",
                storage_path="/private/path/internal-withheld.pdf",
                redaction_status="withheld",
                title="Withheld attachment",
            )
            self.insert_admin_attachment(
                conn,
                filename="deleted.pdf",
                stored_filename="internal-deleted.pdf",
                storage_path="/private/path/internal-deleted.pdf",
                is_deleted=1,
                title="Deleted attachment",
            )
            self.insert_attachment_relationship(conn)
            self.insert_attachment_relationship(
                conn,
                relationship_type="context_for",
                target_type="condition",
                target_key="INSTITUTIONAL_DELAY",
            )
            self.insert_attachment_relationship(
                conn,
                relationship_type="supports",
                target_type="condition",
                target_key="INSTITUTIONAL_DELAY",
            )
            self.insert_attachment_relationship(
                conn,
                relationship_type="supports",
                target_type="signal",
                target_key="Missing Response",
            )
            self.insert_attachment_relationship(
                conn,
                relationship_type="contradicts",
                target_type="condition",
                target_key="REMOVED_RELATIONSHIP_TARGET",
                is_active=0,
            )
            self.insert_attachment_audit_event(
                conn,
                attachment_id=8,
                event_type="attachment_created",
                actor="admin",
                occurred_at="2026-06-04T12:30:00Z",
                request_id="req-admin-older",
            )
            self.insert_attachment_audit_event(
                conn,
                attachment_id=9,
                event_type="attachment_visibility_reviewed",
                actor="reviewer",
                occurred_at="2026-06-04T14:00:00Z",
                metadata_json=json.dumps(
                    {
                        "note": "Reviewed <script>alert('x')</script>",
                        "storage_path": "/private/path/internal-audit.pdf",
                        "source_narrative": "private raw narrative",
                    },
                    sort_keys=True,
                ),
                request_id="req-admin-newer",
            )
            self.insert_attachment_audit_event(
                conn,
                attachment_id=11,
                event_type="attachment_metadata_corrected",
                actor="admin",
                occurred_at="2026-06-04T16:00:00Z",
                metadata_json=json.dumps({"changed_fields": ["title"]}),
                request_id="req-admin-corrected",
            )
            self.insert_attachment_audit_event(
                conn,
                attachment_id=1,
                event_type="attachment_relationship_added",
                actor="admin",
                occurred_at="2026-06-04T15:30:00Z",
                metadata_json=json.dumps(
                    {
                        "relationship_id": 1,
                        "relationship_type": "supports",
                        "target_type": "condition",
                        "target_key": "Transfer of Burden",
                    },
                    sort_keys=True,
                ),
                request_id="req-relationship-added",
            )
            self.insert_attachment_audit_event(
                conn,
                attachment_id=None,
                event_type="synthetic_audit_verification",
                actor="admin",
                occurred_at="2026-06-04T11:32:00Z",
                metadata_json=json.dumps({"purpose": "local verification"}),
                request_id="req-synthetic",
            )
            self.insert_attachment_audit_event(
                conn,
                reference="Strike-OT-20260604-OTHER",
                attachment_id=10,
                event_type="other_record_event",
                occurred_at="2026-06-04T15:00:00Z",
                metadata_json=json.dumps({"note": "Other record audit event"}),
                request_id="req-other",
            )
            conn.close()
            try:
                with self.env():
                    with patch.object(
                        self.admin_session.time, "time", return_value=200
                    ):
                        response = self.admin_session.admin_record_attachments_page(
                            "Strike-OT-20260604-ADMIN",
                            self.valid_request(),
                        )
            finally:
                self.admin_session.DB_PATH = original_db_path

        content = response.content

        self.assertIn("Admin Attachment Management", content)
        self.assertIn('class="admin-watermark print-watermark"', content)
        self.assertIn('aria-hidden="true"', content)
        self.assertIn("print-color-adjust: exact", content)
        self.assertIn(">v12</text>", content)
        self.assertIn("Strike-OT-20260604-ADMIN", content)
        self.assertIn("Record summary", content)
        self.assertIn("Current attachments", content)
        self.assertIn("Administrative capabilities", content)
        self.assertIn("Implemented", content)
        self.assertIn("Planned", content)
        self.assertNotIn("Future management actions", content)
        self.assertNotIn("Future controls planned:", content)
        self.assertIn("metadata correction", content)
        self.assertIn("withhold / restore", content)
        self.assertIn("soft-delete", content)
        self.assertIn("audit trail review", content)
        self.assertIn("visibility workflow", content)
        self.assertIn("publication workflow", content)
        self.assertIn("public file serving", content)
        self.assertIn("Audit trail", content)
        self.assertNotIn("Audit trail placeholder", content)
        self.assertNotIn(
            "Audit trail display is planned for a later Stage 5B step.",
            content,
        )
        self.assertNotIn("No audit events are displayed in Step 4A.", content)
        self.assertIn("Governance notice", content)
        self.assertIn("Record version", content)
        self.assertIn(
            'href="/admin/records/Strike-OT-20260604-ADMIN/evidence"',
            content,
        )
        self.assertIn("View record evidence by target", content)
        self.assertIn("Public attachment", content)
        self.assertIn("Private attachment", content)
        self.assertIn("Withheld attachment", content)
        self.assertIn("Deleted attachment", content)
        self.assertIn("public.pdf", content)
        self.assertIn("private.pdf", content)
        self.assertIn("withheld.pdf", content)
        self.assertIn("deleted.pdf", content)
        self.assertIn("application/pdf", content)
        self.assertIn("12345", content)
        self.assertIn("d" * 64, content)
        self.assertIn("public", content)
        self.assertIn("private", content)
        self.assertIn("withheld", content)
        self.assertIn("deleted", content)
        self.assertIn("Attachment description", content)
        self.assertIn("Attachment source", content)
        self.assertIn("Classification", content)
        self.assertIn("Publication status", content)
        self.assertIn(">other<", content)
        self.assertIn(">internal<", content)
        self.assertIn("2026-06-04", content)
        self.assertIn("day", content)
        self.assertIn("2026-06-04T12:00:00Z", content)
        self.assertIn('<details class="attachment-card" open>', content)
        self.assertIn('<details class="audit-event" open>', content)
        self.assertIn(
            'class="attachment-metadata-update-form classification-update-form"',
            content,
        )
        self.assertIn("data-classification-update-form", content)
        self.assertIn(
            'action="/api/admin/session/records/Strike-OT-20260604-ADMIN/attachments/1/classification"',
            content,
        )
        self.assertIn('data-method="PATCH"', content)
        self.assertIn('method="post"', content)
        self.assertIn('name="classification"', content)
        self.assertIn('<option value="evidence">evidence</option>', content)
        self.assertIn(
            '<option value="correspondence">correspondence</option>',
            content,
        )
        self.assertIn('<option value="decision">decision</option>', content)
        self.assertIn(
            '<option value="medical_record">medical_record</option>',
            content,
        )
        self.assertIn(
            '<option value="legal_filing">legal_filing</option>',
            content,
        )
        self.assertIn('<option value="photograph">photograph</option>', content)
        self.assertIn('<option value="media">media</option>', content)
        self.assertIn('<option value="research">research</option>', content)
        self.assertIn('<option value="other" selected>other</option>', content)
        self.assertIn("Update classification", content)
        self.assertIn(
            'class="attachment-metadata-update-form publication-update-form"', content
        )
        self.assertIn("data-publication-update-form", content)
        self.assertIn(
            'action="/api/admin/session/records/Strike-OT-20260604-ADMIN/attachments/1/publication"',
            content,
        )
        self.assertIn('data-json-field="publication_status"', content)
        self.assertIn('name="publication_status"', content)
        self.assertIn('<option value="internal" selected>internal</option>', content)
        self.assertIn('<option value="published">published</option>', content)
        self.assertIn('<option value="withdrawn">withdrawn</option>', content)
        self.assertIn("Update publication", content)
        self.assertIn(
            "Controlled administrative metadata/publication workflow action only.",
            content,
        )
        self.assertIn(
            'class="attachment-metadata-update-form visibility-update-form"', content
        )
        self.assertIn("data-visibility-update-form", content)
        self.assertIn(
            'action="/api/admin/session/records/Strike-OT-20260604-ADMIN/attachments/1/visibility"',
            content,
        )
        self.assertIn('data-json-field="visibility"', content)
        self.assertIn('name="visibility"', content)
        self.assertIn('<option value="private">private</option>', content)
        self.assertIn('<option value="public" selected>public</option>', content)
        self.assertIn("Update visibility", content)
        self.assertIn(
            "Controlled administrative visibility workflow action only.", content
        )
        self.assertIn("Evidence Relationships (4)", content)
        self.assertIn("Evidence Coverage", content)
        self.assertIn("<strong>Status:</strong> Partial", content)
        self.assertIn(
            "<strong>Reason:</strong> Conditions remain unlinked. Signals remain unlinked. Findings remain unlinked. Record targets remain unlinked.",
            content,
        )
        self.assertIn("<td>Conditions linked</td><td>2 / 5</td>", content)
        self.assertIn("<td>Signals linked</td><td>1 / 2</td>", content)
        self.assertIn("<td>Findings linked</td><td>0 / 1</td>", content)
        self.assertIn("<td>Records linked</td><td>0 / 1</td>", content)
        self.assertIn("Unlinked Conditions", content)
        self.assertIn("<li>Procedural Deflection</li>", content)
        self.assertIn("<li>Repeated Contact Without Resolution</li>", content)
        self.assertIn("<li>Escalation Without Response</li>", content)
        self.assertIn(
            '<details class="relationship-group relationship-group-condition" open>',
            content,
        )
        self.assertIn("<summary>Conditions (3)</summary>", content)
        self.assertIn(
            '<details class="relationship-group relationship-group-signal">',
            content,
        )
        self.assertIn("<summary>Signals (1)</summary>", content)
        self.assertNotIn("relationship-group-finding", content)
        self.assertNotIn("relationship-group-record", content)
        self.assertIn('class="relationship-card"', content)
        self.assertIn("supports • condition", content)
        self.assertIn("context_for • condition", content)
        self.assertIn("supports • signal", content)
        self.assertIn("→ Transfer of Burden", content)
        self.assertIn("→ Institutional Delay", content)
        self.assertIn("→ Missing Response", content)
        self.assertIn('data-target-key="INSTITUTIONAL_DELAY"', content)
        self.assertNotIn("REMOVED_RELATIONSHIP_TARGET", content)
        self.assertNotIn("→ Removed Relationship Target", content)
        self.assertIn('class="attachment-relationship-form"', content)
        self.assertIn("data-relationship-add-form", content)
        self.assertIn(
            'action="/api/admin/session/records/Strike-OT-20260604-ADMIN/attachments/1/relationships"',
            content,
        )
        self.assertIn('name="relationship_type"', content)
        self.assertIn('<option value="supports">supports</option>', content)
        self.assertIn('<option value="contradicts">contradicts</option>', content)
        self.assertIn('<option value="context_for">context_for</option>', content)
        self.assertIn('name="target_type"', content)
        self.assertIn('<option value="condition">condition</option>', content)
        self.assertIn('<option value="signal">signal</option>', content)
        self.assertIn('<option value="finding">finding</option>', content)
        self.assertIn('<option value="record">record</option>', content)
        self.assertIn('name="target_key"', content)
        self.assertIn("data-target-key-select", content)
        self.assertNotIn('input name="target_key"', content)
        self.assertIn(
            '<option value="INSTITUTIONAL_DELAY">Institutional Delay</option>',
            content,
        )
        self.assertIn(
            '<option value="PROCEDURAL_DEFLECTION">Procedural Deflection</option>',
            content,
        )
        self.assertIn(
            '<option value="REPEATED_CONTACT_WITHOUT_RESOLUTION">Repeated Contact Without Resolution</option>',
            content,
        )
        self.assertIn(
            '<option value="Transfer of Burden">Transfer of Burden</option>',
            content,
        )
        self.assertIn(
            '<option value="Escalation Without Response">Escalation Without Response</option>',
            content,
        )
        self.assertIn('"condition": [', content)
        self.assertIn('"INSTITUTIONAL_DELAY"', content)
        self.assertIn('"PROCEDURAL_DEFLECTION"', content)
        self.assertIn('"REPEATED_CONTACT_WITHOUT_RESOLUTION"', content)
        self.assertIn("guidedTargetDisplayLabel", content)
        self.assertIn("option.value = value", content)
        self.assertIn('"signal": ["Missing Response", "Procedural Loop"]', content)
        self.assertIn('"finding": ["Finding \\u003crequires\\u003e review"]', content)
        self.assertIn('"record": ["Strike-OT-20260604-ADMIN"]', content)
        self.assertIn("No available targets", content)
        self.assertIn("RELATIONSHIP_TARGET_OPTIONS", content)
        self.assertIn("updateTargetKeyOptions", content)
        self.assertIn("Add relationship", content)
        self.assertIn("data-relationship-remove-form", content)
        self.assertIn(
            'action="/api/admin/session/records/Strike-OT-20260604-ADMIN/attachments/1/relationships/1/remove"',
            content,
        )
        self.assertIn("Remove relationship", content)
        self.assertIn(
            "Controlled administrative evidence-linking action only.", content
        )
        self.assertIn("Controlled administrative metadata action only.", content)
        self.assertIn('method: "PATCH"', content)
        self.assertIn('<span class="summary-title">Public attachment</span>', content)
        self.assertIn(
            '<span class="summary-meta">other • active • public • none • internal</span>',
            content,
        )
        self.assertIn(
            '<span class="summary-time">2026-06-04 12:00 UTC</span>',
            content,
        )
        self.assertIn('<span class="summary-title">Private attachment</span>', content)
        self.assertIn(
            '<span class="summary-meta">other • active • private • none • internal</span>',
            content,
        )
        self.assertIn('<span class="summary-title">Withheld attachment</span>', content)
        self.assertIn(
            '<span class="summary-meta">other • withheld • public • withheld • internal</span>',
            content,
        )
        self.assertIn('<span class="summary-title">Deleted attachment</span>', content)
        self.assertIn(
            '<span class="summary-meta">other • deleted • public • none • internal</span>',
            content,
        )
        self.assertIn("2026-06-04T14:00:00Z", content)
        self.assertIn("2026-06-04T12:30:00Z", content)
        self.assertLess(
            content.index("2026-06-04T16:00:00Z"),
            content.index("2026-06-04T14:00:00Z"),
        )
        self.assertLess(
            content.index("2026-06-04T14:00:00Z"),
            content.index("2026-06-04T12:30:00Z"),
        )
        self.assertIn('<span class="event-badge">[metadata corrected]</span>', content)
        self.assertIn(
            '<span class="event-badge">[classification updated]</span>',
            self.admin_session._render_admin_audit_events(
                [
                    {
                        "attachment_id": 1,
                        "event_type": "attachment_classification_updated",
                        "actor": "admin",
                        "occurred_at": "2026-06-04T16:30:00Z",
                        "record_version": 1,
                        "request_id": "req-classification",
                        "metadata_json": None,
                    }
                ]
            ),
        )
        self.assertIn(
            '<span class="event-badge">[publication updated]</span>',
            self.admin_session._render_admin_audit_events(
                [
                    {
                        "attachment_id": 1,
                        "event_type": "attachment_publication_updated",
                        "actor": "admin",
                        "occurred_at": "2026-06-04T16:45:00Z",
                        "record_version": 1,
                        "request_id": "req-publication",
                        "metadata_json": None,
                    }
                ]
            ),
        )
        self.assertIn(
            '<span class="event-badge">[visibility updated]</span>',
            self.admin_session._render_admin_audit_events(
                [
                    {
                        "attachment_id": 1,
                        "event_type": "attachment_visibility_updated",
                        "actor": "admin",
                        "occurred_at": "2026-06-04T16:50:00Z",
                        "record_version": 1,
                        "request_id": "req-visibility",
                        "metadata_json": None,
                    }
                ]
            ),
        )
        self.assertIn(
            '<span class="event-badge">[relationship added]</span>',
            content,
        )
        self.assertIn(
            '<span class="event-badge">[synthetic verification]</span>',
            content,
        )
        self.assertIn(
            '<span class="event-badge">[audit event]</span>',
            content,
        )
        self.assertIn(
            '<span class="summary-title">attachment_metadata_corrected</span>',
            content,
        )
        self.assertIn(
            '<span class="summary-meta">Attachment 11 • admin • 2026-06-04 16:00 UTC</span>',
            content,
        )
        self.assertIn(
            '<span class="summary-title">synthetic_audit_verification</span>',
            content,
        )
        self.assertIn(
            '<span class="summary-meta">admin • 2026-06-04 11:32 UTC</span>',
            content,
        )
        self.assertIn("attachment_visibility_reviewed", content)
        self.assertIn("attachment_created", content)
        self.assertIn("reviewer", content)
        self.assertIn("Attachment ID", content)
        self.assertIn(">9<", content)
        self.assertIn("Request ID", content)
        self.assertIn("req-admin-newer", content)
        self.assertIn("metadata_json", content)
        self.assertIn(
            "Reviewed &lt;script&gt;alert(&#x27;x&#x27;)&lt;/script&gt;", content
        )
        self.assertIn("<script>", content)
        self.assertNotIn("Reviewed <script>alert", content)
        self.assertNotIn("other_record_event", content)
        self.assertNotIn("req-other", content)
        self.assertNotIn("private raw narrative", content)
        self.assertNotIn("private source narrative must stay hidden", content)
        self.assertNotIn("report json must stay hidden", content)
        self.assertIn(
            "Administrative attachment management is controlled in this stage.",
            content,
        )
        self.assertIn(
            "Classification, publication status, and visibility metadata updates are available from this page.",
            content,
        )
        self.assertIn(
            "No upload, edit, delete, restore, withhold, publish, correction, or download actions are available.",
            content,
        )

    def test_admin_attachment_listing_exposes_no_paths_tokens_or_controls(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            self.insert_admin_attachment(conn)
            conn.close()
            try:
                with self.env():
                    response = self.admin_session.admin_record_attachments_page(
                        "Strike-OT-20260604-ADMIN",
                        self.valid_request(),
                    )
            finally:
                self.admin_session.DB_PATH = original_db_path

        content = response.content

        self.assertNotIn("storage_path", content)
        self.assertNotIn("stored_filename", content)
        self.assertNotIn("internal-public.pdf", content)
        self.assertNotIn("/private/path", content)
        self.assertNotIn("server-only-token", content)
        self.assertNotIn("CDE_ADMIN_TOKEN", content)
        self.assertIn(
            'href="/admin/records/Strike-OT-20260604-ADMIN/evidence"',
            content,
        )
        self.assertNotIn("<textarea", content)
        self.assertNotIn("Download attachment", content)
        self.assertNotIn("Upload attachment", content)
        self.assertNotIn("Edit attachment", content)
        self.assertNotIn("Delete attachment", content)
        self.assertNotIn("Restore attachment", content)
        self.assertNotIn("Withhold attachment", content)
        self.assertNotIn("Publish attachment", content)
        self.assertNotIn("Download attachment", content)

    def test_admin_record_evidence_view_groups_supporting_attachments_safely(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            self.insert_admin_attachment(
                conn,
                title="Condition evidence",
                classification="evidence",
                publication_status="published",
                visibility="public",
                sha256_hash="a" * 64,
            )
            self.insert_admin_attachment(
                conn,
                title="Signal and finding evidence",
                filename="signal.pdf",
                stored_filename="internal-signal.pdf",
                storage_path="/private/path/internal-signal.pdf",
                classification="research",
                publication_status="internal",
                visibility="private",
                sha256_hash="b" * 64,
            )
            self.insert_admin_attachment(
                conn,
                title="Deleted linked evidence",
                filename="deleted-linked.pdf",
                stored_filename="internal-deleted-linked.pdf",
                storage_path="/private/path/internal-deleted-linked.pdf",
                is_deleted=1,
                sha256_hash="e" * 64,
            )
            attachment_ids = [
                row["id"]
                for row in conn.execute(
                    "SELECT id FROM record_attachments ORDER BY id"
                ).fetchall()
            ]
            condition_attachment_id = attachment_ids[0]
            signal_attachment_id = attachment_ids[1]
            deleted_attachment_id = attachment_ids[2]
            self.insert_attachment_relationship(
                conn,
                attachment_id=condition_attachment_id,
                target_type="condition",
                target_key="INSTITUTIONAL_DELAY",
            )
            self.insert_attachment_relationship(
                conn,
                attachment_id=condition_attachment_id,
                target_type="condition",
                target_key="INSTITUTIONAL_DELAY",
            )
            self.insert_attachment_relationship(
                conn,
                attachment_id=condition_attachment_id,
                relationship_type="context_for",
                target_type="record",
                target_key="Strike-OT-20260604-ADMIN",
            )
            self.insert_attachment_relationship(
                conn,
                attachment_id=signal_attachment_id,
                target_type="signal",
                target_key="Missing Response",
            )
            self.insert_attachment_relationship(
                conn,
                attachment_id=signal_attachment_id,
                relationship_type="context_for",
                target_type="finding",
                target_key="Finding <requires> review",
            )
            self.insert_attachment_relationship(
                conn,
                attachment_id=deleted_attachment_id,
                target_type="condition",
                target_key="PROCEDURAL_DEFLECTION",
            )
            self.insert_attachment_relationship(
                conn,
                attachment_id=condition_attachment_id,
                target_type="condition",
                target_key="Escalation Without Response",
                is_active=0,
            )
            before_manifest = public_evidence_manifest_attachments(
                conn,
                reference="Strike-OT-20260604-ADMIN",
                record_version=1,
            )
            conn.close()
            try:
                with self.env():
                    response = self.admin_session.admin_record_evidence_page(
                        "Strike-OT-20260604-ADMIN",
                        self.valid_request(),
                    )
                conn = sqlite3.connect(self.admin_session.DB_PATH)
                conn.row_factory = sqlite3.Row
                try:
                    after_manifest = public_evidence_manifest_attachments(
                        conn,
                        reference="Strike-OT-20260604-ADMIN",
                        record_version=1,
                    )
                finally:
                    conn.close()
            finally:
                self.admin_session.DB_PATH = original_db_path

        content = response.content

        self.assertIn("Admin Record Evidence", content)
        self.assertIn('class="admin-watermark print-watermark"', content)
        self.assertIn('aria-hidden="true"', content)
        self.assertIn("print-color-adjust: exact", content)
        self.assertIn(">v12</text>", content)
        self.assertIn("details {", content)
        self.assertIn("break-inside: avoid", content)
        self.assertIn("Evidence by record target", content)
        self.assertIn("Record Evidence Coverage", content)
        self.assertIn("<td>Conditions Supported</td><td>1 / 5</td>", content)
        self.assertIn("<td>Signals Supported</td><td>1 / 2</td>", content)
        self.assertIn("<td>Findings Supported</td><td>1 / 1</td>", content)
        self.assertIn("<td>Record Supported</td><td>1 / 1</td>", content)
        self.assertIn("<td>Overall Coverage</td><td>Partial</td>", content)
        self.assertIn(
            'class="evidence-section evidence-section-condition" open', content
        )
        self.assertIn('class="evidence-section evidence-section-signal"', content)
        self.assertIn('class="evidence-section evidence-section-finding"', content)
        self.assertIn('class="evidence-section evidence-section-record"', content)
        self.assertIn("Conditions", content)
        self.assertIn("Signals", content)
        self.assertIn("Findings", content)
        self.assertIn("Record", content)
        self.assertIn("Institutional Delay", content)
        self.assertIn("Missing Response", content)
        self.assertIn("Finding &lt;requires&gt; review", content)
        self.assertIn("Strike-OT-20260604-ADMIN", content)
        self.assertIn("Coverage: Supported", content)
        self.assertIn("Coverage: Unsupported", content)
        self.assertIn("1 supporting attachment", content)
        self.assertIn("Attachment 1 — Condition evidence", content)
        self.assertIn("Attachment 2 — Signal and finding evidence", content)
        self.assertIn("<td>Classification</td><td>evidence</td>", content)
        self.assertIn("<td>Publication status</td><td>published</td>", content)
        self.assertIn("<td>Visibility</td><td>public</td>", content)
        self.assertIn("<td>Redaction status</td><td>none</td>", content)
        self.assertIn("<td>Lifecycle state</td><td>active</td>", content)
        self.assertIn("<td>Document date</td><td>2026-06-04</td>", content)
        self.assertIn("a" * 64, content)
        self.assertIn("No supporting attachments linked.", content)
        self.assertNotIn("Deleted linked evidence", content)
        self.assertNotIn("Attachment 3 — Deleted linked evidence", content)
        self.assertNotIn("internal-public.pdf", content)
        self.assertNotIn("internal-signal.pdf", content)
        self.assertNotIn("storage_path", content)
        self.assertNotIn("stored_filename", content)
        self.assertNotIn("/private/path", content)
        self.assertNotIn("file bytes", content)
        self.assertNotIn("source narrative", content.lower())
        self.assertNotIn("report json", content.lower())
        self.assertNotIn("CDE_ADMIN_TOKEN", content)
        self.assertNotIn("server-only-token", content)
        self.assertNotIn("Upload attachment", content)
        self.assertNotIn("Download attachment", content)
        self.assertNotIn("Add relationship", content)
        self.assertNotIn("Remove relationship", content)
        self.assertIn(
            'href="/admin/records/Strike-OT-20260604-ADMIN/attachments"',
            content,
        )
        self.assertEqual(before_manifest, after_manifest)

    def test_admin_record_evidence_coverage_unsupported_when_no_targets_linked(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            self.insert_admin_attachment(conn)
            conn.close()
            try:
                with self.env():
                    response = self.admin_session.admin_record_evidence_page(
                        "Strike-OT-20260604-ADMIN",
                        self.valid_request(),
                    )
            finally:
                self.admin_session.DB_PATH = original_db_path

        content = response.content

        self.assertIn("Record Evidence Coverage", content)
        self.assertIn("<td>Conditions Supported</td><td>0 / 5</td>", content)
        self.assertIn("<td>Signals Supported</td><td>0 / 2</td>", content)
        self.assertIn("<td>Findings Supported</td><td>0 / 1</td>", content)
        self.assertIn("<td>Record Supported</td><td>0 / 1</td>", content)
        self.assertIn("<td>Overall Coverage</td><td>Unsupported</td>", content)
        self.assertIn("Coverage: Unsupported", content)
        self.assertIn("0 supporting attachments", content)

    def test_admin_record_evidence_coverage_complete_when_all_targets_linked(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            conn.execute(
                """
                UPDATE records
                SET conditions_json = ?, signals_json = ?, finding = ?
                WHERE reference = 'Strike-OT-20260604-ADMIN'
                """,
                (
                    json.dumps(["INSTITUTIONAL_DELAY"]),
                    json.dumps(["Missing Response"]),
                    "Finding <requires> review",
                ),
            )
            self.insert_admin_attachment(conn, title="Complete evidence")
            self.insert_attachment_relationship(
                conn,
                target_type="condition",
                target_key="INSTITUTIONAL_DELAY",
            )
            self.insert_attachment_relationship(
                conn,
                target_type="signal",
                target_key="Missing Response",
            )
            self.insert_attachment_relationship(
                conn,
                relationship_type="context_for",
                target_type="finding",
                target_key="Finding <requires> review",
            )
            self.insert_attachment_relationship(
                conn,
                relationship_type="context_for",
                target_type="record",
                target_key="Strike-OT-20260604-ADMIN",
            )
            conn.close()
            try:
                with self.env():
                    response = self.admin_session.admin_record_evidence_page(
                        "Strike-OT-20260604-ADMIN",
                        self.valid_request(),
                    )
            finally:
                self.admin_session.DB_PATH = original_db_path

        content = response.content

        self.assertIn("<td>Conditions Supported</td><td>1 / 1</td>", content)
        self.assertIn("<td>Signals Supported</td><td>1 / 1</td>", content)
        self.assertIn("<td>Findings Supported</td><td>1 / 1</td>", content)
        self.assertIn("<td>Record Supported</td><td>1 / 1</td>", content)
        self.assertIn("<td>Overall Coverage</td><td>Complete</td>", content)
        self.assertNotIn("Coverage: Unsupported", content)
        self.assertIn("Coverage: Supported", content)

    def test_admin_record_evidence_view_requires_session(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            conn.close()
            try:
                with self.env():
                    with self.assertRaises(Exception) as ctx:
                        self.admin_session.admin_record_evidence_page(
                            "Strike-OT-20260604-ADMIN",
                            FakeRequest(),
                        )
            finally:
                self.admin_session.DB_PATH = original_db_path

        self.assertEqual(getattr(ctx.exception, "status_code", None), 401)

    def test_admin_relationship_form_renders_no_available_targets_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            conn.execute("""
                UPDATE records
                SET conditions_json = '[]', signals_json = '[]', finding = ''
                WHERE reference = 'Strike-OT-20260604-ADMIN'
                """)
            self.insert_admin_attachment(conn)
            conn.close()
            try:
                with self.env():
                    response = self.admin_session.admin_record_attachments_page(
                        "Strike-OT-20260604-ADMIN",
                        self.valid_request(),
                    )
            finally:
                self.admin_session.DB_PATH = original_db_path

        content = response.content

        self.assertIn(
            '<option value="" disabled selected>No available targets</option>',
            content,
        )
        self.assertIn("Evidence Relationships (0)", content)
        self.assertIn("<strong>Status:</strong> Unlinked", content)
        self.assertIn(
            "<strong>Reason:</strong> No active evidence relationships have been created.",
            content,
        )
        self.assertIn("<td>Conditions linked</td><td>0 / 0</td>", content)
        self.assertIn("<td>Signals linked</td><td>0 / 0</td>", content)
        self.assertIn("<td>Findings linked</td><td>0 / 0</td>", content)
        self.assertIn("<td>Records linked</td><td>0 / 1</td>", content)
        self.assertIn("No active evidence relationships.", content)
        self.assertIn("data-relationship-submit disabled", content)

    def test_admin_relationship_coverage_explains_partial_after_conditions_complete(
        self,
    ):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            self.insert_admin_attachment(conn)
            for condition in (
                "INSTITUTIONAL_DELAY",
                "PROCEDURAL_DEFLECTION",
                "REPEATED_CONTACT_WITHOUT_RESOLUTION",
                "Transfer of Burden",
                "Escalation Without Response",
            ):
                self.insert_attachment_relationship(
                    conn,
                    target_type="condition",
                    target_key=condition,
                )
            conn.close()
            try:
                with self.env():
                    response = self.admin_session.admin_record_attachments_page(
                        "Strike-OT-20260604-ADMIN",
                        self.valid_request(),
                    )
            finally:
                self.admin_session.DB_PATH = original_db_path

        content = response.content

        self.assertIn("Evidence Relationships (5)", content)
        self.assertIn("<strong>Status:</strong> Partial", content)
        self.assertIn(
            "<strong>Reason:</strong> Conditions complete. Signals, findings, or record targets remain unlinked.",
            content,
        )
        self.assertIn("<td>Conditions linked</td><td>5 / 5</td>", content)
        self.assertIn("<td>Signals linked</td><td>0 / 2</td>", content)
        self.assertIn("<td>Findings linked</td><td>0 / 1</td>", content)
        self.assertIn("<td>Records linked</td><td>0 / 1</td>", content)
        self.assertIn("<summary>Conditions (5)</summary>", content)
        self.assertNotIn("Unlinked Conditions", content)

    def test_admin_relationship_coverage_complete_when_all_targets_are_linked(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            conn.execute(
                """
                UPDATE records
                SET conditions_json = ?, signals_json = '[]', finding = ''
                WHERE reference = 'Strike-OT-20260604-ADMIN'
                """,
                (json.dumps(["TRANSFER_OF_BURDEN"]),),
            )
            self.insert_admin_attachment(conn)
            self.insert_attachment_relationship(
                conn,
                target_type="condition",
                target_key="TRANSFER_OF_BURDEN",
            )
            self.insert_attachment_relationship(
                conn,
                relationship_type="context_for",
                target_type="record",
                target_key="Strike-OT-20260604-ADMIN",
            )
            conn.close()
            try:
                with self.env():
                    response = self.admin_session.admin_record_attachments_page(
                        "Strike-OT-20260604-ADMIN",
                        self.valid_request(),
                    )
            finally:
                self.admin_session.DB_PATH = original_db_path

        content = response.content

        self.assertIn("Evidence Relationships (2)", content)
        self.assertIn("<strong>Status:</strong> Complete", content)
        self.assertIn(
            "<strong>Reason:</strong> All available targets are linked.", content
        )
        self.assertIn("<td>Conditions linked</td><td>1 / 1</td>", content)
        self.assertIn("<td>Signals linked</td><td>0 / 0</td>", content)
        self.assertIn("<td>Findings linked</td><td>0 / 0</td>", content)
        self.assertIn("<td>Records linked</td><td>1 / 1</td>", content)
        self.assertIn("<summary>Conditions (1)</summary>", content)
        self.assertIn("<summary>Records (1)</summary>", content)
        self.assertIn("→ Transfer Of Burden", content)
        self.assertIn('data-target-key="TRANSFER_OF_BURDEN"', content)
        self.assertNotIn("Unlinked Conditions", content)

    def test_admin_attachment_listing_empty_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            conn.close()
            try:
                with self.env():
                    response = self.admin_session.admin_record_attachments_page(
                        "Strike-OT-20260604-ADMIN",
                        self.valid_request(),
                    )
            finally:
                self.admin_session.DB_PATH = original_db_path

        self.assertIn(
            "No attachments are currently associated with this record.",
            response.content,
        )
        self.assertIn(
            "No audit events are currently recorded for this record.",
            response.content,
        )

    def test_admin_attachment_listing_does_not_change_canonical_hashing(self):
        canonical = {
            "reference": "Strike-OT-20260604-ADMIN",
            "generated_at": "2026-06-04T12:00:00Z",
            "finding": "Admin listing must not change canonical hashing.",
            "trajectory": "Stable",
            "conditions": sorted(["Transfer of Burden", "Institutional Delay"]),
            "system_state": "Canonical record unchanged",
            "generated_by": "Civic Decision Engine",
        }
        payload = json.dumps(canonical, separators=(",", ":"), sort_keys=True)
        actual = hashlib.sha256(payload.encode("utf-8")).hexdigest()

        self.assertEqual(
            actual,
            "4c3ef9bbe432d5c72a5e2853dbe32a17cd97fa7ac415d3a1ab5c79479c7fac59",
        )

    def test_json_attachment_listing_requires_session(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            conn.close()
            try:
                with self.env():
                    with self.assertRaises(Exception) as ctx:
                        self.admin_session.list_record_attachments_route(
                            "Strike-OT-20260604-ADMIN",
                            FakeRequest(),
                        )
            finally:
                self.admin_session.DB_PATH = original_db_path

        self.assertEqual(getattr(ctx.exception, "status_code", None), 401)

    def test_json_attachment_listing_returns_metadata_without_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            self.insert_admin_attachment(conn)
            conn.close()
            try:
                with self.env():
                    response = self.admin_session.list_record_attachments_route(
                        "Strike-OT-20260604-ADMIN",
                        self.valid_request(),
                    )
            finally:
                self.admin_session.DB_PATH = original_db_path

        serialized = json.dumps(response.content, sort_keys=True)

        self.assertEqual(response.content["attachment_count"], 1)
        self.assertIn("Public attachment", serialized)
        self.assertIn("public.pdf", serialized)
        self.assertNotIn("storage_path", serialized)
        self.assertNotIn("stored_filename", serialized)
        self.assertNotIn("/private/path", serialized)
        self.assertNotIn("internal-public.pdf", serialized)
        self.assertNotIn("server-only-token", serialized)
        self.assertNotIn("CDE_ADMIN_TOKEN", serialized)

    def test_metadata_correction_requires_admin_session(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            self.insert_admin_attachment(conn)
            attachment_id = conn.execute(
                "SELECT id FROM record_attachments"
            ).fetchone()["id"]
            conn.close()
            try:
                with self.env():
                    with self.assertRaises(Exception) as ctx:
                        self.admin_session.correct_attachment_metadata_route(
                            "Strike-OT-20260604-ADMIN",
                            attachment_id,
                            FakeRequest(),
                            {"title": "Corrected title"},
                        )
            finally:
                self.admin_session.DB_PATH = original_db_path

        self.assertEqual(getattr(ctx.exception, "status_code", None), 401)

    def test_metadata_correction_updates_allowed_fields_and_writes_audit_event(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            stored_path = Path(temp_dir) / "attachment.pdf"
            stored_bytes = b"%PDF-1.4 unchanged"
            stored_path.write_bytes(stored_bytes)
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            self.insert_admin_attachment(
                conn,
                storage_path=str(stored_path),
                stored_filename=stored_path.name,
                title="Original title",
                description="Original description",
                source_label="Original source",
                document_date="2026-06-04",
                document_date_precision="day",
                publication_status="published",
                redaction_note="Original redaction note",
            )
            attachment_id = conn.execute(
                "SELECT id FROM record_attachments"
            ).fetchone()["id"]
            before = dict(
                conn.execute(
                    "SELECT * FROM record_attachments WHERE id = ?",
                    (attachment_id,),
                ).fetchone()
            )
            before_manifest = public_manifest_attachments(
                conn,
                reference="Strike-OT-20260604-ADMIN",
                record_version=1,
            )
            conn.close()
            try:
                with self.env():
                    response = self.admin_session.correct_attachment_metadata_route(
                        "Strike-OT-20260604-ADMIN",
                        attachment_id,
                        self.valid_request(),
                        {
                            "title": "Corrected title",
                            "description": "Corrected description",
                            "source_label": "Corrected source",
                            "document_date": "2026-06",
                            "document_date_precision": "month",
                            "redaction_note": "Corrected redaction note",
                        },
                    )
                conn = sqlite3.connect(self.admin_session.DB_PATH)
                conn.row_factory = sqlite3.Row
                try:
                    after = dict(
                        conn.execute(
                            "SELECT * FROM record_attachments WHERE id = ?",
                            (attachment_id,),
                        ).fetchone()
                    )
                    audit = dict(
                        conn.execute("SELECT * FROM attachment_audit_events").fetchone()
                    )
                    after_manifest = public_manifest_attachments(
                        conn,
                        reference="Strike-OT-20260604-ADMIN",
                        record_version=1,
                    )
                    stored_file_bytes_after = stored_path.read_bytes()
                finally:
                    conn.close()
            finally:
                self.admin_session.DB_PATH = original_db_path

        serialized_response = json.dumps(response.content, sort_keys=True)
        audit_metadata = json.loads(audit["metadata_json"])

        self.assertTrue(response.content["ok"])
        self.assertEqual(response.content["attachment"]["title"], "Corrected title")
        self.assertEqual(
            response.content["attachment"]["description"], "Corrected description"
        )
        self.assertEqual(
            response.content["attachment"]["source_label"], "Corrected source"
        )
        self.assertEqual(response.content["attachment"]["document_date"], "2026-06")
        self.assertEqual(
            response.content["attachment"]["document_date_precision"], "month"
        )
        self.assertEqual(
            response.content["changed_fields"],
            [
                "title",
                "description",
                "source_label",
                "document_date",
                "document_date_precision",
                "redaction_note",
            ],
        )
        self.assertEqual(after["title"], "Corrected title")
        self.assertEqual(after["description"], "Corrected description")
        self.assertEqual(after["source_label"], "Corrected source")
        self.assertEqual(after["document_date"], "2026-06")
        self.assertEqual(after["document_date_precision"], "month")
        self.assertEqual(after["redaction_note"], "Corrected redaction note")
        self.assertEqual(after["sha256_hash"], before["sha256_hash"])
        self.assertEqual(after["storage_path"], before["storage_path"])
        self.assertEqual(after["stored_filename"], before["stored_filename"])
        self.assertEqual(stored_file_bytes_after, stored_bytes)
        for immutable in (
            "reference",
            "record_version",
            "attachment_version",
            "filename",
            "stored_filename",
            "storage_path",
            "content_type",
            "file_size_bytes",
            "sha256_hash",
            "visibility",
            "redaction_status",
            "publication_status",
            "is_latest",
            "is_deleted",
            "uploaded_at",
        ):
            self.assertEqual(after[immutable], before[immutable])
        self.assertEqual(audit["event_type"], "attachment_metadata_corrected")
        self.assertEqual(audit["reference"], "Strike-OT-20260604-ADMIN")
        self.assertEqual(audit["attachment_id"], attachment_id)
        self.assertEqual(audit["record_version"], 1)
        self.assertEqual(
            audit_metadata["changed_fields"],
            [
                "title",
                "description",
                "source_label",
                "document_date",
                "document_date_precision",
                "redaction_note",
            ],
        )
        self.assertEqual(audit_metadata["previous_values"]["title"], "Original title")
        self.assertEqual(audit_metadata["new_values"]["title"], "Corrected title")
        self.assertEqual(before_manifest[0]["title"], "Original title")
        self.assertEqual(after_manifest[0]["title"], "Corrected title")
        self.assertEqual(after_manifest[0]["filename"], before_manifest[0]["filename"])
        self.assertNotIn("storage_path", serialized_response)
        self.assertNotIn("stored_filename", serialized_response)
        self.assertNotIn(str(stored_path), serialized_response)
        self.assertNotIn("server-only-token", serialized_response)
        self.assertNotIn("CDE_ADMIN_TOKEN", serialized_response)
        self.assertNotIn("storage_path", audit["metadata_json"])
        self.assertNotIn("stored_filename", audit["metadata_json"])
        self.assertNotIn("CDE_ADMIN_TOKEN", audit["metadata_json"])

    def test_metadata_correction_allows_empty_optional_values_as_null(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            self.insert_admin_attachment(conn)
            attachment_id = conn.execute(
                "SELECT id FROM record_attachments"
            ).fetchone()["id"]
            conn.close()
            try:
                with self.env():
                    response = self.admin_session.correct_attachment_metadata_route(
                        "Strike-OT-20260604-ADMIN",
                        attachment_id,
                        self.valid_request(),
                        {
                            "title": "",
                            "description": None,
                            "source_label": "",
                            "document_date": None,
                            "document_date_precision": "unknown",
                            "redaction_note": "",
                        },
                    )
                after = self.fetch_attachment_row(
                    self.admin_session.DB_PATH, attachment_id
                )
            finally:
                self.admin_session.DB_PATH = original_db_path

        self.assertIsNone(after["title"])
        self.assertIsNone(after["description"])
        self.assertIsNone(after["source_label"])
        self.assertIsNone(after["document_date"])
        self.assertEqual(after["document_date_precision"], "unknown")
        self.assertIsNone(after["redaction_note"])
        self.assertEqual(
            response.content["attachment"]["document_date_precision"], "unknown"
        )

    def test_metadata_correction_rejects_unknown_field(self):
        self.assert_metadata_correction_rejected(
            {"unexpected": "value"},
            400,
            "metadata_field_unknown",
        )

    def test_metadata_correction_rejects_immutable_field(self):
        self.assert_metadata_correction_rejected(
            {"sha256_hash": "e" * 64},
            400,
            "metadata_field_immutable",
        )

    def test_metadata_correction_rejects_invalid_document_date(self):
        self.assert_metadata_correction_rejected(
            {"document_date": "2026-02-31", "document_date_precision": "day"},
            400,
            "document_date_invalid",
        )

    def test_metadata_correction_wrong_reference_and_missing_attachment_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            self.insert_admin_attachment(conn)
            attachment_id = conn.execute(
                "SELECT id FROM record_attachments"
            ).fetchone()["id"]
            conn.close()
            try:
                with self.env():
                    with self.assertRaises(Exception) as wrong_ref:
                        self.admin_session.correct_attachment_metadata_route(
                            "Strike-OT-20260604-WRONG",
                            attachment_id,
                            self.valid_request(),
                            {"title": "Corrected title"},
                        )
                    with self.assertRaises(Exception) as missing:
                        self.admin_session.correct_attachment_metadata_route(
                            "Strike-OT-20260604-ADMIN",
                            attachment_id + 99,
                            self.valid_request(),
                            {"title": "Corrected title"},
                        )
                after = self.fetch_attachment_row(
                    self.admin_session.DB_PATH, attachment_id
                )
            finally:
                self.admin_session.DB_PATH = original_db_path

        self.assertEqual(getattr(wrong_ref.exception, "status_code", None), 404)
        self.assertEqual(getattr(missing.exception, "status_code", None), 404)
        self.assertEqual(after["title"], "Public attachment")

    def test_classification_update_requires_admin_session(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            self.insert_admin_attachment(conn)
            attachment_id = conn.execute(
                "SELECT id FROM record_attachments"
            ).fetchone()["id"]
            conn.close()
            try:
                with self.env():
                    with self.assertRaises(Exception) as ctx:
                        self.admin_session.update_attachment_classification_route(
                            "Strike-OT-20260604-ADMIN",
                            attachment_id,
                            FakeRequest(),
                            {"classification": "medical_record"},
                        )
            finally:
                self.admin_session.DB_PATH = original_db_path

        self.assertEqual(getattr(ctx.exception, "status_code", None), 401)

    def test_classification_update_only_changes_classification_and_writes_audit_event(
        self,
    ):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            stored_path = Path(temp_dir) / "attachment.pdf"
            stored_bytes = b"%PDF-1.4 classification unchanged"
            stored_path.write_bytes(stored_bytes)
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            self.insert_admin_attachment(
                conn,
                storage_path=str(stored_path),
                stored_filename=stored_path.name,
                classification="other",
            )
            attachment_id = conn.execute(
                "SELECT id FROM record_attachments"
            ).fetchone()["id"]
            before = dict(
                conn.execute(
                    "SELECT * FROM record_attachments WHERE id = ?",
                    (attachment_id,),
                ).fetchone()
            )
            before_manifest = public_manifest_attachments(
                conn,
                reference="Strike-OT-20260604-ADMIN",
                record_version=1,
            )
            conn.close()
            try:
                with self.env():
                    response = (
                        self.admin_session.update_attachment_classification_route(
                            "Strike-OT-20260604-ADMIN",
                            attachment_id,
                            self.valid_request(),
                            {"classification": "medical_record"},
                        )
                    )
                conn = sqlite3.connect(self.admin_session.DB_PATH)
                conn.row_factory = sqlite3.Row
                try:
                    after = dict(
                        conn.execute(
                            "SELECT * FROM record_attachments WHERE id = ?",
                            (attachment_id,),
                        ).fetchone()
                    )
                    audit = dict(
                        conn.execute("SELECT * FROM attachment_audit_events").fetchone()
                    )
                    after_manifest = public_manifest_attachments(
                        conn,
                        reference="Strike-OT-20260604-ADMIN",
                        record_version=1,
                    )
                    stored_file_bytes_after = stored_path.read_bytes()
                finally:
                    conn.close()
                with self.env():
                    page_response = self.admin_session.admin_record_attachments_page(
                        "Strike-OT-20260604-ADMIN",
                        self.valid_request(),
                    )
            finally:
                self.admin_session.DB_PATH = original_db_path

        serialized_response = json.dumps(response.content, sort_keys=True)
        audit_metadata = json.loads(audit["metadata_json"])
        page_content = page_response.content

        self.assertTrue(response.content["ok"])
        self.assertEqual(
            response.content["attachment"]["classification"], "medical_record"
        )
        self.assertEqual(before["classification"], "other")
        self.assertEqual(after["classification"], "medical_record")
        for preserved in (
            "reference",
            "record_version",
            "attachment_version",
            "filename",
            "stored_filename",
            "storage_path",
            "content_type",
            "file_size_bytes",
            "sha256_hash",
            "visibility",
            "redaction_status",
            "is_latest",
            "is_deleted",
            "uploaded_at",
        ):
            self.assertEqual(after[preserved], before[preserved])
        self.assertEqual(stored_file_bytes_after, stored_bytes)
        self.assertEqual(before_manifest, after_manifest)
        self.assertEqual(audit["event_type"], "attachment_classification_updated")
        self.assertEqual(audit["reference"], "Strike-OT-20260604-ADMIN")
        self.assertEqual(audit["attachment_id"], attachment_id)
        self.assertEqual(audit["record_version"], 1)
        self.assertEqual(audit_metadata["previous_classification"], "other")
        self.assertEqual(audit_metadata["new_classification"], "medical_record")
        self.assertIn(
            '<span class="summary-meta">medical_record • active • public • none • internal</span>',
            page_content,
        )
        self.assertIn("<td>Classification</td><td>medical_record</td>", page_content)
        self.assertIn(
            '<span class="event-badge">[classification updated]</span>',
            page_content,
        )
        self.assertNotIn("storage_path", audit["metadata_json"])
        self.assertNotIn("stored_filename", audit["metadata_json"])
        self.assertNotIn(str(stored_path), audit["metadata_json"])
        self.assertNotIn("CDE_ADMIN_TOKEN", audit["metadata_json"])
        self.assertNotIn("storage_path", serialized_response)
        self.assertNotIn("stored_filename", serialized_response)
        self.assertNotIn(str(stored_path), serialized_response)
        self.assertNotIn("server-only-token", serialized_response)
        self.assertNotIn("CDE_ADMIN_TOKEN", serialized_response)

    def test_classification_update_rejects_invalid_payload(self):
        self.assert_classification_update_rejected(
            {"classification": "secret_internal"},
            400,
            "classification_invalid",
        )
        self.assert_classification_update_rejected(
            {"classification": "medical_record", "storage_path": "/private/file.pdf"},
            400,
            "classification_payload_invalid",
        )

    def test_classification_update_wrong_reference_and_missing_attachment_rejected(
        self,
    ):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            self.insert_admin_attachment(conn)
            attachment_id = conn.execute(
                "SELECT id FROM record_attachments"
            ).fetchone()["id"]
            before = dict(
                conn.execute(
                    "SELECT * FROM record_attachments WHERE id = ?",
                    (attachment_id,),
                ).fetchone()
            )
            conn.close()
            try:
                with self.env():
                    with self.assertRaises(Exception) as wrong_ref:
                        self.admin_session.update_attachment_classification_route(
                            "Strike-OT-20260604-WRONG",
                            attachment_id,
                            self.valid_request(),
                            {"classification": "medical_record"},
                        )
                    with self.assertRaises(Exception) as missing:
                        self.admin_session.update_attachment_classification_route(
                            "Strike-OT-20260604-ADMIN",
                            attachment_id + 99,
                            self.valid_request(),
                            {"classification": "medical_record"},
                        )
                after = self.fetch_attachment_row(
                    self.admin_session.DB_PATH, attachment_id
                )
                conn = sqlite3.connect(self.admin_session.DB_PATH)
                try:
                    audit_count = conn.execute(
                        "SELECT COUNT(*) FROM attachment_audit_events"
                    ).fetchone()[0]
                finally:
                    conn.close()
            finally:
                self.admin_session.DB_PATH = original_db_path

        self.assertEqual(getattr(wrong_ref.exception, "status_code", None), 404)
        self.assertEqual(getattr(missing.exception, "status_code", None), 404)
        self.assertEqual(after, before)
        self.assertEqual(audit_count, 0)

    def test_publication_update_requires_admin_session(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            self.insert_admin_attachment(conn)
            attachment_id = conn.execute(
                "SELECT id FROM record_attachments"
            ).fetchone()["id"]
            conn.close()
            try:
                with self.env():
                    with self.assertRaises(Exception) as ctx:
                        self.admin_session.update_attachment_publication_route(
                            "Strike-OT-20260604-ADMIN",
                            attachment_id,
                            FakeRequest(),
                            {"publication_status": "published"},
                        )
            finally:
                self.admin_session.DB_PATH = original_db_path

        self.assertEqual(getattr(ctx.exception, "status_code", None), 401)

    def test_publication_update_only_changes_status_and_writes_audit_event(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            stored_path = Path(temp_dir) / "attachment.pdf"
            stored_bytes = b"%PDF-1.4 publication unchanged"
            stored_path.write_bytes(stored_bytes)
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            self.insert_admin_attachment(
                conn,
                storage_path=str(stored_path),
                stored_filename=stored_path.name,
                classification="evidence",
                publication_status="internal",
            )
            attachment_id = conn.execute(
                "SELECT id FROM record_attachments"
            ).fetchone()["id"]
            before = dict(
                conn.execute(
                    "SELECT * FROM record_attachments WHERE id = ?",
                    (attachment_id,),
                ).fetchone()
            )
            before_manifest = public_manifest_attachments(
                conn,
                reference="Strike-OT-20260604-ADMIN",
                record_version=1,
            )
            conn.close()
            try:
                with self.env():
                    response = self.admin_session.update_attachment_publication_route(
                        "Strike-OT-20260604-ADMIN",
                        attachment_id,
                        self.valid_request(),
                        {"publication_status": "published"},
                    )
                conn = sqlite3.connect(self.admin_session.DB_PATH)
                conn.row_factory = sqlite3.Row
                try:
                    after = dict(
                        conn.execute(
                            "SELECT * FROM record_attachments WHERE id = ?",
                            (attachment_id,),
                        ).fetchone()
                    )
                    audit = dict(
                        conn.execute("SELECT * FROM attachment_audit_events").fetchone()
                    )
                    after_manifest = public_manifest_attachments(
                        conn,
                        reference="Strike-OT-20260604-ADMIN",
                        record_version=1,
                    )
                    stored_file_bytes_after = stored_path.read_bytes()
                finally:
                    conn.close()
                with self.env():
                    page_response = self.admin_session.admin_record_attachments_page(
                        "Strike-OT-20260604-ADMIN",
                        self.valid_request(),
                    )
            finally:
                self.admin_session.DB_PATH = original_db_path

        serialized_response = json.dumps(response.content, sort_keys=True)
        audit_metadata = json.loads(audit["metadata_json"])
        page_content = page_response.content

        self.assertTrue(response.content["ok"])
        self.assertEqual(
            response.content["attachment"]["publication_status"], "published"
        )
        self.assertEqual(before["publication_status"], "internal")
        self.assertEqual(after["publication_status"], "published")
        for preserved in (
            "reference",
            "record_version",
            "attachment_version",
            "filename",
            "stored_filename",
            "storage_path",
            "content_type",
            "file_size_bytes",
            "sha256_hash",
            "visibility",
            "redaction_status",
            "classification",
            "is_latest",
            "is_deleted",
            "uploaded_at",
        ):
            self.assertEqual(after[preserved], before[preserved])
        self.assertEqual(stored_file_bytes_after, stored_bytes)
        self.assertEqual(before_manifest, [])
        self.assertEqual(len(after_manifest), 1)
        self.assertEqual(after_manifest[0]["filename"], before["filename"])
        self.assertEqual(audit["event_type"], "attachment_publication_updated")
        self.assertEqual(audit["reference"], "Strike-OT-20260604-ADMIN")
        self.assertEqual(audit["attachment_id"], attachment_id)
        self.assertEqual(audit["record_version"], 1)
        self.assertEqual(audit_metadata["previous_publication_status"], "internal")
        self.assertEqual(audit_metadata["new_publication_status"], "published")
        self.assertIn(
            '<span class="summary-meta">evidence • active • public • none • published</span>',
            page_content,
        )
        self.assertIn("<td>Publication status</td><td>published</td>", page_content)
        self.assertIn(
            '<span class="event-badge">[publication updated]</span>',
            page_content,
        )
        self.assertNotIn("storage_path", audit["metadata_json"])
        self.assertNotIn("stored_filename", audit["metadata_json"])
        self.assertNotIn(str(stored_path), audit["metadata_json"])
        self.assertNotIn("CDE_ADMIN_TOKEN", audit["metadata_json"])
        self.assertNotIn("storage_path", serialized_response)
        self.assertNotIn("stored_filename", serialized_response)
        self.assertNotIn(str(stored_path), serialized_response)
        self.assertNotIn("server-only-token", serialized_response)
        self.assertNotIn("CDE_ADMIN_TOKEN", serialized_response)

    def test_publication_update_rejects_invalid_payload(self):
        self.assert_publication_update_rejected(
            {"publication_status": "public_now"},
            400,
            "publication_status_invalid",
        )
        self.assert_publication_update_rejected(
            {"publication_status": "published", "storage_path": "/private/file.pdf"},
            400,
            "publication_payload_invalid",
        )

    def test_publication_update_wrong_reference_and_missing_attachment_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            self.insert_admin_attachment(conn)
            attachment_id = conn.execute(
                "SELECT id FROM record_attachments"
            ).fetchone()["id"]
            before = dict(
                conn.execute(
                    "SELECT * FROM record_attachments WHERE id = ?",
                    (attachment_id,),
                ).fetchone()
            )
            conn.close()
            try:
                with self.env():
                    with self.assertRaises(Exception) as wrong_ref:
                        self.admin_session.update_attachment_publication_route(
                            "Strike-OT-20260604-WRONG",
                            attachment_id,
                            self.valid_request(),
                            {"publication_status": "published"},
                        )
                    with self.assertRaises(Exception) as missing:
                        self.admin_session.update_attachment_publication_route(
                            "Strike-OT-20260604-ADMIN",
                            attachment_id + 99,
                            self.valid_request(),
                            {"publication_status": "published"},
                        )
                after = self.fetch_attachment_row(
                    self.admin_session.DB_PATH, attachment_id
                )
                conn = sqlite3.connect(self.admin_session.DB_PATH)
                try:
                    audit_count = conn.execute(
                        "SELECT COUNT(*) FROM attachment_audit_events"
                    ).fetchone()[0]
                finally:
                    conn.close()
            finally:
                self.admin_session.DB_PATH = original_db_path

        self.assertEqual(getattr(wrong_ref.exception, "status_code", None), 404)
        self.assertEqual(getattr(missing.exception, "status_code", None), 404)
        self.assertEqual(after, before)
        self.assertEqual(audit_count, 0)

    def test_visibility_update_requires_admin_session(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            self.insert_admin_attachment(conn)
            attachment_id = conn.execute(
                "SELECT id FROM record_attachments"
            ).fetchone()["id"]
            conn.close()
            try:
                with self.env():
                    with self.assertRaises(Exception) as ctx:
                        self.admin_session.update_attachment_visibility_route(
                            "Strike-OT-20260604-ADMIN",
                            attachment_id,
                            FakeRequest(),
                            {"visibility": "public"},
                        )
            finally:
                self.admin_session.DB_PATH = original_db_path

        self.assertEqual(getattr(ctx.exception, "status_code", None), 401)

    def test_visibility_update_only_changes_visibility_and_writes_audit_event(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            stored_path = Path(temp_dir) / "attachment.pdf"
            stored_bytes = b"%PDF-1.4 visibility unchanged"
            stored_path.write_bytes(stored_bytes)
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            self.insert_admin_attachment(
                conn,
                storage_path=str(stored_path),
                stored_filename=stored_path.name,
                classification="evidence",
                publication_status="published",
                visibility="private",
            )
            attachment_id = conn.execute(
                "SELECT id FROM record_attachments"
            ).fetchone()["id"]
            before = dict(
                conn.execute(
                    "SELECT * FROM record_attachments WHERE id = ?",
                    (attachment_id,),
                ).fetchone()
            )
            before_manifest = public_manifest_attachments(
                conn,
                reference="Strike-OT-20260604-ADMIN",
                record_version=1,
            )
            before_evidence_manifest = public_evidence_manifest_attachments(
                conn,
                reference="Strike-OT-20260604-ADMIN",
                record_version=1,
            )
            conn.close()
            try:
                with self.env():
                    response = self.admin_session.update_attachment_visibility_route(
                        "Strike-OT-20260604-ADMIN",
                        attachment_id,
                        self.valid_request(),
                        {"visibility": "public"},
                    )
                conn = sqlite3.connect(self.admin_session.DB_PATH)
                conn.row_factory = sqlite3.Row
                try:
                    after = dict(
                        conn.execute(
                            "SELECT * FROM record_attachments WHERE id = ?",
                            (attachment_id,),
                        ).fetchone()
                    )
                    audit = dict(
                        conn.execute("SELECT * FROM attachment_audit_events").fetchone()
                    )
                    after_manifest = public_manifest_attachments(
                        conn,
                        reference="Strike-OT-20260604-ADMIN",
                        record_version=1,
                    )
                    after_evidence_manifest = public_evidence_manifest_attachments(
                        conn,
                        reference="Strike-OT-20260604-ADMIN",
                        record_version=1,
                    )
                    stored_file_bytes_after = stored_path.read_bytes()
                finally:
                    conn.close()
                with self.env():
                    page_response = self.admin_session.admin_record_attachments_page(
                        "Strike-OT-20260604-ADMIN",
                        self.valid_request(),
                    )
            finally:
                self.admin_session.DB_PATH = original_db_path

        serialized_response = json.dumps(response.content, sort_keys=True)
        audit_metadata = json.loads(audit["metadata_json"])
        page_content = page_response.content

        self.assertTrue(response.content["ok"])
        self.assertEqual(response.content["attachment"]["visibility"], "public")
        self.assertEqual(before["visibility"], "private")
        self.assertEqual(after["visibility"], "public")
        for preserved in (
            "reference",
            "record_version",
            "attachment_version",
            "filename",
            "stored_filename",
            "storage_path",
            "content_type",
            "file_size_bytes",
            "sha256_hash",
            "classification",
            "publication_status",
            "redaction_status",
            "is_latest",
            "is_deleted",
            "uploaded_at",
        ):
            self.assertEqual(after[preserved], before[preserved])
        self.assertEqual(stored_file_bytes_after, stored_bytes)
        self.assertEqual(before_manifest, [])
        self.assertEqual(before_evidence_manifest, [])
        self.assertEqual(len(after_manifest), 1)
        self.assertEqual(after_manifest[0]["filename"], before["filename"])
        self.assertEqual(len(after_evidence_manifest), 1)
        self.assertEqual(after_evidence_manifest[0]["filename"], before["filename"])
        self.assertEqual(audit["event_type"], "attachment_visibility_updated")
        self.assertEqual(audit["reference"], "Strike-OT-20260604-ADMIN")
        self.assertEqual(audit["attachment_id"], attachment_id)
        self.assertEqual(audit["record_version"], 1)
        self.assertEqual(audit_metadata["previous_visibility"], "private")
        self.assertEqual(audit_metadata["new_visibility"], "public")
        self.assertIn(
            '<span class="summary-meta">evidence • active • public • none • published</span>',
            page_content,
        )
        self.assertIn("<td>Visibility</td><td>public</td>", page_content)
        self.assertIn(
            '<span class="event-badge">[visibility updated]</span>',
            page_content,
        )
        self.assertNotIn("storage_path", audit["metadata_json"])
        self.assertNotIn("stored_filename", audit["metadata_json"])
        self.assertNotIn(str(stored_path), audit["metadata_json"])
        self.assertNotIn("CDE_ADMIN_TOKEN", audit["metadata_json"])
        self.assertNotIn("storage_path", serialized_response)
        self.assertNotIn("stored_filename", serialized_response)
        self.assertNotIn(str(stored_path), serialized_response)
        self.assertNotIn("server-only-token", serialized_response)
        self.assertNotIn("CDE_ADMIN_TOKEN", serialized_response)

    def test_visibility_update_rejects_invalid_payload(self):
        self.assert_visibility_update_rejected(
            {"visibility": "restricted"},
            400,
            "visibility_invalid",
        )
        self.assert_visibility_update_rejected(
            {"visibility": "public", "storage_path": "/private/file.pdf"},
            400,
            "visibility_payload_invalid",
        )

    def test_visibility_update_wrong_reference_and_missing_attachment_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            self.insert_admin_attachment(conn)
            attachment_id = conn.execute(
                "SELECT id FROM record_attachments"
            ).fetchone()["id"]
            before = dict(
                conn.execute(
                    "SELECT * FROM record_attachments WHERE id = ?",
                    (attachment_id,),
                ).fetchone()
            )
            conn.close()
            try:
                with self.env():
                    with self.assertRaises(Exception) as wrong_ref:
                        self.admin_session.update_attachment_visibility_route(
                            "Strike-OT-20260604-WRONG",
                            attachment_id,
                            self.valid_request(),
                            {"visibility": "public"},
                        )
                    with self.assertRaises(Exception) as missing:
                        self.admin_session.update_attachment_visibility_route(
                            "Strike-OT-20260604-ADMIN",
                            attachment_id + 99,
                            self.valid_request(),
                            {"visibility": "public"},
                        )
                after = self.fetch_attachment_row(
                    self.admin_session.DB_PATH, attachment_id
                )
                conn = sqlite3.connect(self.admin_session.DB_PATH)
                try:
                    audit_count = conn.execute(
                        "SELECT COUNT(*) FROM attachment_audit_events"
                    ).fetchone()[0]
                finally:
                    conn.close()
            finally:
                self.admin_session.DB_PATH = original_db_path

        self.assertEqual(getattr(wrong_ref.exception, "status_code", None), 404)
        self.assertEqual(getattr(missing.exception, "status_code", None), 404)
        self.assertEqual(after, before)
        self.assertEqual(audit_count, 0)

    def test_relationship_add_requires_admin_session(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            self.insert_admin_attachment(conn)
            attachment_id = conn.execute(
                "SELECT id FROM record_attachments"
            ).fetchone()["id"]
            conn.close()
            try:
                with self.env():
                    with self.assertRaises(Exception) as ctx:
                        self.admin_session.add_attachment_relationship_route(
                            "Strike-OT-20260604-ADMIN",
                            attachment_id,
                            FakeRequest(),
                            {
                                "relationship_type": "supports",
                                "target_type": "condition",
                                "target_key": "Transfer of Burden",
                            },
                        )
            finally:
                self.admin_session.DB_PATH = original_db_path

        self.assertEqual(getattr(ctx.exception, "status_code", None), 401)

    def test_relationship_add_trims_target_key_preserves_attachment_and_writes_audit_event(
        self,
    ):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            stored_path = Path(temp_dir) / "attachment.pdf"
            stored_bytes = b"%PDF-1.4 relationship unchanged"
            stored_path.write_bytes(stored_bytes)
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            self.insert_admin_attachment(
                conn,
                storage_path=str(stored_path),
                stored_filename=stored_path.name,
                classification="evidence",
                publication_status="published",
            )
            attachment_id = conn.execute(
                "SELECT id FROM record_attachments"
            ).fetchone()["id"]
            before = dict(
                conn.execute(
                    "SELECT * FROM record_attachments WHERE id = ?",
                    (attachment_id,),
                ).fetchone()
            )
            before_manifest = public_manifest_attachments(
                conn,
                reference="Strike-OT-20260604-ADMIN",
                record_version=1,
            )
            conn.close()
            try:
                with self.env():
                    response = self.admin_session.add_attachment_relationship_route(
                        "Strike-OT-20260604-ADMIN",
                        attachment_id,
                        self.valid_request(),
                        {
                            "relationship_type": "supports",
                            "target_type": "condition",
                            "target_key": "  Transfer of Burden  ",
                        },
                    )
                conn = sqlite3.connect(self.admin_session.DB_PATH)
                conn.row_factory = sqlite3.Row
                try:
                    after = dict(
                        conn.execute(
                            "SELECT * FROM record_attachments WHERE id = ?",
                            (attachment_id,),
                        ).fetchone()
                    )
                    relationship = dict(
                        conn.execute(
                            "SELECT * FROM record_attachment_relationships"
                        ).fetchone()
                    )
                    audit = dict(
                        conn.execute("SELECT * FROM attachment_audit_events").fetchone()
                    )
                    after_manifest = public_manifest_attachments(
                        conn,
                        reference="Strike-OT-20260604-ADMIN",
                        record_version=1,
                    )
                    stored_file_bytes_after = stored_path.read_bytes()
                finally:
                    conn.close()
                with self.env():
                    page_response = self.admin_session.admin_record_attachments_page(
                        "Strike-OT-20260604-ADMIN",
                        self.valid_request(),
                    )
            finally:
                self.admin_session.DB_PATH = original_db_path

        serialized_response = json.dumps(response.content, sort_keys=True)
        audit_metadata = json.loads(audit["metadata_json"])
        page_content = page_response.content

        self.assertTrue(response.content["ok"])
        self.assertEqual(
            response.content["relationship"]["target_key"], "Transfer of Burden"
        )
        self.assertEqual(relationship["relationship_type"], "supports")
        self.assertEqual(relationship["target_type"], "condition")
        self.assertEqual(relationship["target_key"], "Transfer of Burden")
        self.assertEqual(relationship["is_active"], 1)
        self.assertEqual(after, before)
        self.assertEqual(stored_file_bytes_after, stored_bytes)
        self.assertEqual(after_manifest, before_manifest)
        self.assertEqual(audit["event_type"], "attachment_relationship_added")
        self.assertEqual(audit_metadata["relationship_id"], relationship["id"])
        self.assertEqual(audit_metadata["relationship_type"], "supports")
        self.assertEqual(audit_metadata["target_type"], "condition")
        self.assertEqual(audit_metadata["target_key"], "Transfer of Burden")
        self.assertIn("Evidence Relationships (1)", page_content)
        self.assertIn("supports • condition", page_content)
        self.assertIn("→ Transfer of Burden", page_content)
        self.assertIn('data-target-key="Transfer of Burden"', page_content)
        self.assertIn(
            '<span class="event-badge">[relationship added]</span>',
            page_content,
        )
        for field in (
            "sha256_hash",
            "classification",
            "publication_status",
            "visibility",
            "redaction_status",
            "is_deleted",
        ):
            self.assertEqual(after[field], before[field])
        self.assertNotIn("storage_path", serialized_response)
        self.assertNotIn("stored_filename", serialized_response)
        self.assertNotIn("CDE_ADMIN_TOKEN", serialized_response)
        self.assertNotIn("storage_path", audit["metadata_json"])
        self.assertNotIn("stored_filename", audit["metadata_json"])
        self.assertNotIn("CDE_ADMIN_TOKEN", audit["metadata_json"])

    def test_relationship_add_rejects_invalid_payloads_and_reference_errors(self):
        invalid_payloads = (
            {
                "relationship_type": "unknown",
                "target_type": "condition",
                "target_key": "Transfer",
            },
            {
                "relationship_type": "supports",
                "target_type": "unknown",
                "target_key": "Transfer",
            },
            {
                "relationship_type": "supports",
                "target_type": "condition",
                "target_key": "   ",
            },
            {
                "relationship_type": "supports",
                "target_type": "condition",
                "target_key": "x" * 201,
            },
        )
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                self.assert_relationship_add_rejected(
                    payload, 400, "relationship_payload_invalid"
                )

        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            self.insert_admin_attachment(conn)
            attachment_id = conn.execute(
                "SELECT id FROM record_attachments"
            ).fetchone()["id"]
            before = self.fetch_attachment_row(
                self.admin_session.DB_PATH, attachment_id
            )
            conn.close()
            try:
                with self.env():
                    with self.assertRaises(Exception) as wrong_ref:
                        self.admin_session.add_attachment_relationship_route(
                            "Strike-OT-20260604-WRONG",
                            attachment_id,
                            self.valid_request(),
                            {
                                "relationship_type": "supports",
                                "target_type": "condition",
                                "target_key": "Transfer",
                            },
                        )
                    with self.assertRaises(Exception) as missing:
                        self.admin_session.add_attachment_relationship_route(
                            "Strike-OT-20260604-ADMIN",
                            attachment_id + 99,
                            self.valid_request(),
                            {
                                "relationship_type": "supports",
                                "target_type": "condition",
                                "target_key": "Transfer",
                            },
                        )
                after = self.fetch_attachment_row(
                    self.admin_session.DB_PATH, attachment_id
                )
                conn = sqlite3.connect(self.admin_session.DB_PATH)
                try:
                    relationship_count = conn.execute(
                        "SELECT COUNT(*) FROM record_attachment_relationships"
                    ).fetchone()[0]
                finally:
                    conn.close()
            finally:
                self.admin_session.DB_PATH = original_db_path

        self.assertEqual(getattr(wrong_ref.exception, "status_code", None), 404)
        self.assertEqual(getattr(missing.exception, "status_code", None), 404)
        self.assertEqual(after, before)
        self.assertEqual(relationship_count, 0)

    def test_relationship_remove_marks_inactive_and_writes_audit_event(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            self.insert_admin_attachment(conn)
            attachment_id = conn.execute(
                "SELECT id FROM record_attachments"
            ).fetchone()["id"]
            self.insert_attachment_relationship(conn, attachment_id=attachment_id)
            relationship_id = conn.execute(
                "SELECT id FROM record_attachment_relationships"
            ).fetchone()["id"]
            before = self.fetch_attachment_row(
                self.admin_session.DB_PATH, attachment_id
            )
            conn.close()
            try:
                with self.env():
                    response = self.admin_session.remove_attachment_relationship_route(
                        "Strike-OT-20260604-ADMIN",
                        attachment_id,
                        relationship_id,
                        self.valid_request(),
                    )
                conn = sqlite3.connect(self.admin_session.DB_PATH)
                conn.row_factory = sqlite3.Row
                try:
                    after = self.fetch_attachment_row(
                        self.admin_session.DB_PATH, attachment_id
                    )
                    relationship = dict(
                        conn.execute(
                            "SELECT * FROM record_attachment_relationships WHERE id = ?",
                            (relationship_id,),
                        ).fetchone()
                    )
                    audit = dict(
                        conn.execute("SELECT * FROM attachment_audit_events").fetchone()
                    )
                finally:
                    conn.close()
                with self.env():
                    page_response = self.admin_session.admin_record_attachments_page(
                        "Strike-OT-20260604-ADMIN",
                        self.valid_request(),
                    )
            finally:
                self.admin_session.DB_PATH = original_db_path

        audit_metadata = json.loads(audit["metadata_json"])
        page_content = page_response.content

        self.assertTrue(response.content["ok"])
        self.assertEqual(relationship["is_active"], 0)
        self.assertIsNotNone(relationship["removed_at"])
        self.assertEqual(relationship["removed_by"], "admin")
        self.assertEqual(after, before)
        self.assertEqual(audit["event_type"], "attachment_relationship_removed")
        self.assertEqual(audit_metadata["relationship_id"], relationship_id)
        self.assertEqual(audit_metadata["target_key"], "Transfer of Burden")
        self.assertNotIn("→ Transfer of Burden", page_content)
        self.assertIn("No active evidence relationships.", page_content)
        self.assertIn(
            '<span class="event-badge">[relationship removed]</span>',
            page_content,
        )

    def test_relationship_remove_uses_relationship_id_not_duplicate_target_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            self.insert_admin_attachment(conn)
            attachment_id = conn.execute(
                "SELECT id FROM record_attachments"
            ).fetchone()["id"]
            self.insert_attachment_relationship(
                conn,
                attachment_id=attachment_id,
                target_key="INSTITUTIONAL_DELAY",
            )
            self.insert_attachment_relationship(
                conn,
                attachment_id=attachment_id,
                target_key="INSTITUTIONAL_DELAY",
            )
            relationship_ids = [
                row["id"]
                for row in conn.execute(
                    "SELECT id FROM record_attachment_relationships ORDER BY id"
                ).fetchall()
            ]
            conn.close()
            try:
                with self.env():
                    response = self.admin_session.remove_attachment_relationship_route(
                        "Strike-OT-20260604-ADMIN",
                        attachment_id,
                        relationship_ids[0],
                        self.valid_request(),
                    )
                conn = sqlite3.connect(self.admin_session.DB_PATH)
                conn.row_factory = sqlite3.Row
                try:
                    relationships = [
                        dict(row)
                        for row in conn.execute(
                            "SELECT id, is_active, target_key "
                            "FROM record_attachment_relationships ORDER BY id"
                        ).fetchall()
                    ]
                    audit = dict(
                        conn.execute("SELECT * FROM attachment_audit_events").fetchone()
                    )
                finally:
                    conn.close()
            finally:
                self.admin_session.DB_PATH = original_db_path

        audit_metadata = json.loads(audit["metadata_json"])

        self.assertTrue(response.content["ok"])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(relationships[0]["id"], relationship_ids[0])
        self.assertEqual(relationships[0]["is_active"], 0)
        self.assertEqual(relationships[1]["id"], relationship_ids[1])
        self.assertEqual(relationships[1]["is_active"], 1)
        self.assertEqual(relationships[0]["target_key"], "INSTITUTIONAL_DELAY")
        self.assertEqual(relationships[1]["target_key"], "INSTITUTIONAL_DELAY")
        self.assertEqual(audit["event_type"], "attachment_relationship_removed")
        self.assertEqual(audit_metadata["relationship_id"], relationship_ids[0])
        self.assertEqual(audit_metadata["target_key"], "INSTITUTIONAL_DELAY")

    def test_lifecycle_routes_require_admin_session(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            self.insert_admin_attachment(conn)
            attachment_id = conn.execute(
                "SELECT id FROM record_attachments"
            ).fetchone()["id"]
            conn.close()
            try:
                with self.env():
                    for route in (
                        self.admin_session.withhold_attachment_route,
                        self.admin_session.restore_attachment_route,
                        self.admin_session.soft_delete_attachment_route,
                    ):
                        with self.subTest(route=route.__name__):
                            with self.assertRaises(Exception) as ctx:
                                route(
                                    "Strike-OT-20260604-ADMIN",
                                    attachment_id,
                                    FakeRequest(),
                                )
                            self.assertEqual(
                                getattr(ctx.exception, "status_code", None),
                                401,
                            )
            finally:
                self.admin_session.DB_PATH = original_db_path

    def test_withhold_sets_withheld_hides_manifest_and_writes_audit_event(self):
        result = self.run_lifecycle_action(
            self.admin_session.withhold_attachment_route,
            initial_redaction_status="none",
            initial_is_deleted=0,
        )

        self.assertEqual(result["response"].content["action"], "withhold")
        self.assertEqual(result["after"]["redaction_status"], "withheld")
        self.assertEqual(result["after"]["is_deleted"], 0)
        self.assertEqual(result["after_manifest"], [])
        self.assertEqual(result["audit"]["event_type"], "attachment_withheld")
        self.assertEqual(result["audit_metadata"]["action"], "withhold")
        self.assertEqual(result["audit_metadata"]["previous_redaction_status"], "none")
        self.assertEqual(result["audit_metadata"]["new_redaction_status"], "withheld")
        self.assertEqual(result["audit_metadata"]["previous_is_deleted"], 0)
        self.assertEqual(result["audit_metadata"]["new_is_deleted"], 0)

    def test_soft_delete_sets_deleted_hides_manifest_and_writes_audit_event(self):
        result = self.run_lifecycle_action(
            self.admin_session.soft_delete_attachment_route,
            initial_redaction_status="none",
            initial_is_deleted=0,
        )

        self.assertEqual(result["response"].content["action"], "soft-delete")
        self.assertEqual(result["after"]["redaction_status"], "none")
        self.assertEqual(result["after"]["is_deleted"], 1)
        self.assertEqual(result["after_manifest"], [])
        self.assertEqual(result["audit"]["event_type"], "attachment_soft_deleted")
        self.assertEqual(result["audit_metadata"]["action"], "soft-delete")
        self.assertEqual(result["audit_metadata"]["previous_redaction_status"], "none")
        self.assertEqual(result["audit_metadata"]["new_redaction_status"], "none")
        self.assertEqual(result["audit_metadata"]["previous_is_deleted"], 0)
        self.assertEqual(result["audit_metadata"]["new_is_deleted"], 1)

    def test_restore_clears_deleted_and_withheld_state_and_writes_audit_event(self):
        result = self.run_lifecycle_action(
            self.admin_session.restore_attachment_route,
            initial_redaction_status="withheld",
            initial_is_deleted=1,
        )

        self.assertEqual(result["response"].content["action"], "restore")
        self.assertEqual(result["after"]["redaction_status"], "none")
        self.assertEqual(result["after"]["is_deleted"], 0)
        self.assertEqual(len(result["after_manifest"]), 1)
        self.assertEqual(result["audit"]["event_type"], "attachment_restored")
        self.assertEqual(result["audit_metadata"]["action"], "restore")
        self.assertEqual(
            result["audit_metadata"]["previous_redaction_status"], "withheld"
        )
        self.assertEqual(result["audit_metadata"]["new_redaction_status"], "none")
        self.assertEqual(result["audit_metadata"]["previous_is_deleted"], 1)
        self.assertEqual(result["audit_metadata"]["new_is_deleted"], 0)

    def test_lifecycle_routes_wrong_reference_and_missing_attachment_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            self.insert_admin_attachment(conn)
            attachment_id = conn.execute(
                "SELECT id FROM record_attachments"
            ).fetchone()["id"]
            before = dict(
                conn.execute(
                    "SELECT * FROM record_attachments WHERE id = ?",
                    (attachment_id,),
                ).fetchone()
            )
            conn.close()
            try:
                with self.env():
                    with self.assertRaises(Exception) as wrong_ref:
                        self.admin_session.withhold_attachment_route(
                            "Strike-OT-20260604-WRONG",
                            attachment_id,
                            self.valid_request(),
                        )
                    with self.assertRaises(Exception) as missing:
                        self.admin_session.soft_delete_attachment_route(
                            "Strike-OT-20260604-ADMIN",
                            attachment_id + 99,
                            self.valid_request(),
                        )
                after = self.fetch_attachment_row(
                    self.admin_session.DB_PATH, attachment_id
                )
                conn = sqlite3.connect(self.admin_session.DB_PATH)
                try:
                    audit_count = conn.execute(
                        "SELECT COUNT(*) FROM attachment_audit_events"
                    ).fetchone()[0]
                finally:
                    conn.close()
            finally:
                self.admin_session.DB_PATH = original_db_path

        self.assertEqual(getattr(wrong_ref.exception, "status_code", None), 404)
        self.assertEqual(getattr(missing.exception, "status_code", None), 404)
        self.assertEqual(after, before)
        self.assertEqual(audit_count, 0)

    def test_lifecycle_idempotent_action_records_explicit_audit_event(self):
        result = self.run_lifecycle_action(
            self.admin_session.withhold_attachment_route,
            initial_redaction_status="withheld",
            initial_is_deleted=0,
        )

        self.assertEqual(result["after"]["redaction_status"], "withheld")
        self.assertEqual(result["after"]["is_deleted"], 0)
        self.assertEqual(result["audit"]["event_type"], "attachment_withheld")
        self.assertEqual(
            result["audit_metadata"]["previous_redaction_status"], "withheld"
        )
        self.assertEqual(result["audit_metadata"]["new_redaction_status"], "withheld")

    def run_lifecycle_action(
        self,
        route,
        *,
        initial_redaction_status,
        initial_is_deleted,
    ):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            stored_path = Path(temp_dir) / "attachment.pdf"
            stored_bytes = b"%PDF-1.4 lifecycle unchanged"
            stored_path.write_bytes(stored_bytes)
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            self.insert_admin_attachment(
                conn,
                storage_path=str(stored_path),
                stored_filename=stored_path.name,
                redaction_status=initial_redaction_status,
                is_deleted=initial_is_deleted,
                publication_status="published",
            )
            attachment_id = conn.execute(
                "SELECT id FROM record_attachments"
            ).fetchone()["id"]
            before = dict(
                conn.execute(
                    "SELECT * FROM record_attachments WHERE id = ?",
                    (attachment_id,),
                ).fetchone()
            )
            conn.close()
            try:
                with self.env():
                    response = route(
                        "Strike-OT-20260604-ADMIN",
                        attachment_id,
                        self.valid_request(),
                    )
                conn = sqlite3.connect(self.admin_session.DB_PATH)
                conn.row_factory = sqlite3.Row
                try:
                    after = dict(
                        conn.execute(
                            "SELECT * FROM record_attachments WHERE id = ?",
                            (attachment_id,),
                        ).fetchone()
                    )
                    audit = dict(
                        conn.execute("SELECT * FROM attachment_audit_events").fetchone()
                    )
                    after_manifest = public_manifest_attachments(
                        conn,
                        reference="Strike-OT-20260604-ADMIN",
                        record_version=1,
                    )
                    stored_file_exists_after = stored_path.exists()
                    stored_file_bytes_after = stored_path.read_bytes()
                finally:
                    conn.close()
            finally:
                self.admin_session.DB_PATH = original_db_path

        serialized_response = json.dumps(response.content, sort_keys=True)
        audit_metadata = json.loads(audit["metadata_json"])

        self.assertTrue(response.content["ok"])
        self.assertEqual(response.content["attachment"]["attachment_id"], attachment_id)
        self.assertEqual(after["sha256_hash"], before["sha256_hash"])
        self.assertEqual(after["storage_path"], before["storage_path"])
        self.assertEqual(after["stored_filename"], before["stored_filename"])
        self.assertEqual(after["filename"], before["filename"])
        self.assertEqual(after["content_type"], before["content_type"])
        self.assertEqual(after["file_size_bytes"], before["file_size_bytes"])
        self.assertEqual(after["record_version"], before["record_version"])
        self.assertEqual(after["attachment_version"], before["attachment_version"])
        self.assertEqual(after["uploaded_at"], before["uploaded_at"])
        self.assertTrue(stored_file_exists_after)
        self.assertEqual(stored_file_bytes_after, stored_bytes)
        self.assertEqual(audit["reference"], "Strike-OT-20260604-ADMIN")
        self.assertEqual(audit["attachment_id"], attachment_id)
        self.assertEqual(audit["record_version"], 1)
        self.assertIn("previous_redaction_status", audit_metadata)
        self.assertIn("new_redaction_status", audit_metadata)
        self.assertIn("previous_is_deleted", audit_metadata)
        self.assertIn("new_is_deleted", audit_metadata)
        self.assertNotIn("storage_path", audit["metadata_json"])
        self.assertNotIn("stored_filename", audit["metadata_json"])
        self.assertNotIn(str(stored_path), audit["metadata_json"])
        self.assertNotIn("server-only-token", serialized_response)
        self.assertNotIn("CDE_ADMIN_TOKEN", serialized_response)
        self.assertNotIn("CDE_ADMIN_TOKEN", audit["metadata_json"])
        self.assertNotIn("storage_path", serialized_response)
        self.assertNotIn("stored_filename", serialized_response)
        self.assertNotIn(str(stored_path), serialized_response)

        return {
            "response": response,
            "before": before,
            "after": after,
            "audit": audit,
            "audit_metadata": audit_metadata,
            "after_manifest": after_manifest,
        }

    def assert_metadata_correction_rejected(self, payload, status_code, detail):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            self.insert_admin_attachment(conn)
            attachment_id = conn.execute(
                "SELECT id FROM record_attachments"
            ).fetchone()["id"]
            before = dict(
                conn.execute(
                    "SELECT * FROM record_attachments WHERE id = ?",
                    (attachment_id,),
                ).fetchone()
            )
            conn.close()
            try:
                with self.env():
                    with self.assertRaises(Exception) as ctx:
                        self.admin_session.correct_attachment_metadata_route(
                            "Strike-OT-20260604-ADMIN",
                            attachment_id,
                            self.valid_request(),
                            payload,
                        )
                after = self.fetch_attachment_row(
                    self.admin_session.DB_PATH, attachment_id
                )
                conn = sqlite3.connect(self.admin_session.DB_PATH)
                try:
                    audit_count = conn.execute(
                        "SELECT COUNT(*) FROM attachment_audit_events"
                    ).fetchone()[0]
                finally:
                    conn.close()
            finally:
                self.admin_session.DB_PATH = original_db_path

        self.assertEqual(getattr(ctx.exception, "status_code", None), status_code)
        self.assertEqual(getattr(ctx.exception, "detail", None), detail)
        self.assertEqual(after, before)
        self.assertEqual(audit_count, 0)

    def assert_classification_update_rejected(self, payload, status_code, detail):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            self.insert_admin_attachment(conn)
            attachment_id = conn.execute(
                "SELECT id FROM record_attachments"
            ).fetchone()["id"]
            before = dict(
                conn.execute(
                    "SELECT * FROM record_attachments WHERE id = ?",
                    (attachment_id,),
                ).fetchone()
            )
            conn.close()
            try:
                with self.env():
                    with self.assertRaises(Exception) as ctx:
                        self.admin_session.update_attachment_classification_route(
                            "Strike-OT-20260604-ADMIN",
                            attachment_id,
                            self.valid_request(),
                            payload,
                        )
                after = self.fetch_attachment_row(
                    self.admin_session.DB_PATH, attachment_id
                )
                conn = sqlite3.connect(self.admin_session.DB_PATH)
                try:
                    audit_count = conn.execute(
                        "SELECT COUNT(*) FROM attachment_audit_events"
                    ).fetchone()[0]
                finally:
                    conn.close()
            finally:
                self.admin_session.DB_PATH = original_db_path

        self.assertEqual(getattr(ctx.exception, "status_code", None), status_code)
        self.assertEqual(getattr(ctx.exception, "detail", None), detail)
        self.assertEqual(after, before)
        self.assertEqual(audit_count, 0)

    def assert_publication_update_rejected(self, payload, status_code, detail):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            self.insert_admin_attachment(conn)
            attachment_id = conn.execute(
                "SELECT id FROM record_attachments"
            ).fetchone()["id"]
            before = dict(
                conn.execute(
                    "SELECT * FROM record_attachments WHERE id = ?",
                    (attachment_id,),
                ).fetchone()
            )
            conn.close()
            try:
                with self.env():
                    with self.assertRaises(Exception) as ctx:
                        self.admin_session.update_attachment_publication_route(
                            "Strike-OT-20260604-ADMIN",
                            attachment_id,
                            self.valid_request(),
                            payload,
                        )
                after = self.fetch_attachment_row(
                    self.admin_session.DB_PATH, attachment_id
                )
                conn = sqlite3.connect(self.admin_session.DB_PATH)
                try:
                    audit_count = conn.execute(
                        "SELECT COUNT(*) FROM attachment_audit_events"
                    ).fetchone()[0]
                finally:
                    conn.close()
            finally:
                self.admin_session.DB_PATH = original_db_path

        self.assertEqual(getattr(ctx.exception, "status_code", None), status_code)
        self.assertEqual(getattr(ctx.exception, "detail", None), detail)
        self.assertEqual(after, before)
        self.assertEqual(audit_count, 0)

    def assert_visibility_update_rejected(self, payload, status_code, detail):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            self.insert_admin_attachment(conn)
            attachment_id = conn.execute(
                "SELECT id FROM record_attachments"
            ).fetchone()["id"]
            before = dict(
                conn.execute(
                    "SELECT * FROM record_attachments WHERE id = ?",
                    (attachment_id,),
                ).fetchone()
            )
            conn.close()
            try:
                with self.env():
                    with self.assertRaises(Exception) as ctx:
                        self.admin_session.update_attachment_visibility_route(
                            "Strike-OT-20260604-ADMIN",
                            attachment_id,
                            self.valid_request(),
                            payload,
                        )
                after = self.fetch_attachment_row(
                    self.admin_session.DB_PATH, attachment_id
                )
                conn = sqlite3.connect(self.admin_session.DB_PATH)
                try:
                    audit_count = conn.execute(
                        "SELECT COUNT(*) FROM attachment_audit_events"
                    ).fetchone()[0]
                finally:
                    conn.close()
            finally:
                self.admin_session.DB_PATH = original_db_path

        self.assertEqual(getattr(ctx.exception, "status_code", None), status_code)
        self.assertEqual(getattr(ctx.exception, "detail", None), detail)
        self.assertEqual(after, before)
        self.assertEqual(audit_count, 0)

    def assert_relationship_add_rejected(self, payload, status_code, detail):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = self.admin_session.DB_PATH
            self.admin_session.DB_PATH = Path(temp_dir) / "records.db"
            conn = self.make_admin_listing_db(self.admin_session.DB_PATH)
            self.insert_admin_attachment(conn)
            attachment_id = conn.execute(
                "SELECT id FROM record_attachments"
            ).fetchone()["id"]
            before = self.fetch_attachment_row(
                self.admin_session.DB_PATH, attachment_id
            )
            conn.close()
            try:
                with self.env():
                    with self.assertRaises(Exception) as ctx:
                        self.admin_session.add_attachment_relationship_route(
                            "Strike-OT-20260604-ADMIN",
                            attachment_id,
                            self.valid_request(),
                            payload,
                        )
                after = self.fetch_attachment_row(
                    self.admin_session.DB_PATH, attachment_id
                )
                conn = sqlite3.connect(self.admin_session.DB_PATH)
                try:
                    relationship_count = conn.execute(
                        "SELECT COUNT(*) FROM record_attachment_relationships"
                    ).fetchone()[0]
                finally:
                    conn.close()
            finally:
                self.admin_session.DB_PATH = original_db_path

        self.assertEqual(getattr(ctx.exception, "status_code", None), status_code)
        self.assertEqual(getattr(ctx.exception, "detail", None), detail)
        self.assertEqual(after, before)
        self.assertEqual(relationship_count, 0)


if __name__ == "__main__":
    unittest.main()
