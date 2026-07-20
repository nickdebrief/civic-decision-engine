import hashlib
import io
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from api.document_intake import (
    STATUS_LABELS,
    document_intake_duplicate_detail,
    list_intake_documents,
    list_pending_documents,
    load_pending_document,
    store_pending_document,
)
from tests.test_admin_session import FakeHTTPException, FakeRequest, install_fastapi_stubs

install_fastapi_stubs()

from api.routes import admin_session, documents


PDF_BYTES = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF\n"
JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x02strike-jpeg\xff\xd9"
PNG_BYTES = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDRstrike-png"
JP2_BYTES = b"\x00\x00\x00\x0cjP  \r\n\x87\n\x00\x00\x00\x14ftypjp2 \x00\x00\x00\x00jp2 "


class AdminDocumentIntakeTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "pending"
        self.db_path = Path(self.temp_dir.name) / "records.db"
        conn = sqlite3.connect(self.db_path)
        conn.execute("CREATE TABLE records (reference TEXT, verification_hash TEXT)")
        conn.execute("INSERT INTO records VALUES ('existing', 'unchanged')")
        conn.commit()
        conn.close()
        self.env = patch.dict(
            os.environ,
            {
                "ADMIN_USERNAME": "admin-user",
                "ADMIN_PASSWORD": "admin-password",
                "CDE_ADMIN_SESSION_SECRET": "session-secret",
                "CDE_DOCUMENT_INTAKE_ROOT": str(self.root),
                "CDE_DOCUMENT_INTAKE_MAX_BYTES": "1048576",
            },
            clear=False,
        )
        self.env.start()
        self.original_db_path = admin_session.DB_PATH
        admin_session.DB_PATH = self.db_path
        self.session = admin_session.create_admin_session("admin-user")
        self.request = FakeRequest(
            cookies={admin_session.SESSION_COOKIE_NAME: self.session}
        )

    def tearDown(self):
        admin_session.DB_PATH = self.original_db_path
        self.env.stop()
        self.temp_dir.cleanup()

    def metadata(self):
        return {
            "title": "Administrative decision",
            "institution_source": "Civic Office",
            "document_date": "2026-07-08",
            "category": "Decision",
            "description": "Pending administrative source document.",
            "visibility": "private",
            "notes": "Awaiting explicit approval.",
            "reference_identifier": "INT-2026-001",
        }

    def upload(self, **overrides):
        data = overrides.pop("data", PDF_BYTES)
        filename = overrides.pop("filename", "decision.pdf")
        content_type = overrides.pop("content_type", "application/pdf")
        request = overrides.pop("request", self.request)
        values = self.metadata()
        values.update(overrides)
        file = SimpleNamespace(
            filename=filename,
            content_type=content_type,
            file=io.BytesIO(data),
        )
        return admin_session.admin_document_intake_upload(
            request=request,
            file=file,
            **values,
        )

    def transition(self, new_status, note=None, request=None):
        intake_id = hashlib.sha256(PDF_BYTES).hexdigest()
        return admin_session.admin_document_intake_status_update(
            intake_id,
            request or self.request,
            new_status=new_status,
            admin_note=note,
        )

    @staticmethod
    def response_text(response):
        return response.content

    def test_authenticated_admin_page_uses_existing_session(self):
        response = admin_session.admin_document_intake_page(self.request)
        content = self.response_text(response)
        self.assertIn("Admin Document Intake", content)
        self.assertIn("/api/admin/session/document-intake", content)
        self.assertIn("This upload has not created or modified any public record.", content)
        self.assertIn("Signed in as:", content)
        self.assertIn("<strong>admin-user</strong>", content)

    def test_unauthenticated_page_and_upload_are_denied(self):
        with self.assertRaises(FakeHTTPException) as page_ctx:
            admin_session.admin_document_intake_page(FakeRequest())
        self.assertEqual(page_ctx.exception.status_code, 401)

        with self.assertRaises(FakeHTTPException) as upload_ctx:
            self.upload(request=FakeRequest())
        self.assertEqual(upload_ctx.exception.status_code, 401)
        self.assertEqual(list_pending_documents(root=self.root), [])

    def test_pdf_upload_persists_private_pending_metadata_and_hash(self):
        response = self.upload()
        expected_hash = hashlib.sha256(PDF_BYTES).hexdigest()
        item = load_pending_document(expected_hash, root=self.root)
        content = self.response_text(response)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(item["status"], "pending")
        self.assertEqual(item["status_history"][0]["new_status"], "pending")
        self.assertEqual(item["status_history"][0]["actor"], "admin-user")
        self.assertEqual(item["document_type"], "pdf")
        self.assertEqual(item["document_format"], "PDF")
        self.assertEqual(item["content_type"], "application/pdf")
        self.assertEqual(item["original_filename"], "decision.pdf")
        self.assertEqual(item["sha256_hash"], expected_hash)
        self.assertEqual(item["file_size_bytes"], len(PDF_BYTES))
        self.assertEqual(item["title"], "Administrative decision")
        self.assertEqual(item["institution_source"], "Civic Office")
        self.assertEqual(item["reference_identifier"], "INT-2026-001")
        self.assertFalse(item["public_record_mutation"])
        self.assertIn(expected_hash, content)
        self.assertIn("Pending Document Preview", content)
        self.assertIn("This upload has not created or modified any public record.", content)
        self.assertIn("Signed in as:", content)
        self.assertIn("<strong>admin-user</strong>", content)

        stored_file = Path(item["proposed_storage_location"])
        self.assertTrue(stored_file.is_file())
        self.assertEqual(stored_file.read_bytes(), PDF_BYTES)
        self.assertTrue(str(stored_file).startswith(str(self.root.resolve())))

    def test_original_filename_is_preserved_without_path_traversal(self):
        self.upload(filename="../../private/source.PDF")
        item = list_pending_documents(root=self.root)[0]
        self.assertEqual(item["original_filename"], "source.PDF")
        self.assertNotIn("..", Path(item["proposed_storage_location"]).parts)

    def test_valid_image_uploads_preserve_bytes_type_and_session_actor(self):
        cases = (
            ("Strike_001.jpg", "image/jpeg", JPEG_BYTES, "jpeg", "JPEG"),
            ("Strike_002.jpeg", "image/jpeg", JPEG_BYTES + b"-jpeg", "jpeg", "JPEG"),
            ("Strike_003.png", "image/png", PNG_BYTES, "png", "PNG"),
            ("STRIKE_004.JPG", "text/plain", JPEG_BYTES + b"-upper", "jpeg", "JPEG"),
            ("STRIKE_005.PNG", "application/octet-stream", PNG_BYTES + b"-upper", "png", "PNG"),
        )
        for filename, content_type, data, document_type, label in cases:
            with self.subTest(filename=filename):
                response = self.upload(
                    filename=filename,
                    content_type=content_type,
                    data=data,
                    title=f"{filename} record",
                )
                expected_hash = hashlib.sha256(data).hexdigest()
                item = load_pending_document(expected_hash, root=self.root)
                self.assertEqual(response.status_code, 201)
                self.assertEqual(item["document_type"], document_type)
                self.assertEqual(item["document_format"], label)
                self.assertEqual(item["sha256_hash"], expected_hash)
                self.assertEqual(item["status_history"][0]["actor"], "admin-user")
                self.assertEqual(Path(item["proposed_storage_location"]).read_bytes(), data)
                self.assertEqual(item["original_filename"], filename)

    def test_invalid_extension_and_signature_cases_are_rejected(self):
        cases = (
            {"filename": "decision.txt"},
            {"data": b"not a pdf"},
            {"filename": "Strike_001.gif", "data": JPEG_BYTES, "content_type": "image/jpeg"},
            {"filename": "Strike_001.webp", "data": JPEG_BYTES, "content_type": "image/jpeg"},
            {"filename": "Strike_001.svg", "data": b"<svg></svg>", "content_type": "image/svg+xml"},
            {"filename": "Strike_001.bmp", "data": b"BMfixture", "content_type": "image/bmp"},
            {"filename": "Strike_001.tiff", "data": b"II*\x00", "content_type": "image/tiff"},
            {"filename": "Strike_001.exe", "data": b"MZfixture", "content_type": "application/octet-stream"},
            {"filename": "Strike_001", "data": JPEG_BYTES, "content_type": "image/jpeg"},
            {"filename": "renamed.jpg", "data": b"MZfixture", "content_type": "image/jpeg"},
            {"filename": "html.png", "data": b"<html><script></script></html>", "content_type": "image/png"},
            {"filename": "svg.pdf", "data": b"<svg></svg>", "content_type": "application/pdf"},
        )
        for case in cases:
            with self.subTest(case=case), self.assertRaises(FakeHTTPException) as ctx:
                self.upload(**case)
            self.assertIn(ctx.exception.status_code, {400, 415})
        self.assertEqual(list_pending_documents(root=self.root), [])

    def test_extension_and_detected_type_must_match(self):
        cases = (
            {"filename": "png-renamed.jpg", "data": PNG_BYTES, "content_type": "image/jpeg"},
            {"filename": "jpeg-renamed.png", "data": JPEG_BYTES, "content_type": "image/png"},
            {"filename": "pdf-renamed.jpg", "data": PDF_BYTES, "content_type": "image/jpeg"},
        )
        for case in cases:
            with self.subTest(case=case), self.assertRaises(FakeHTTPException) as ctx:
                self.upload(**case)
            self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(list_pending_documents(root=self.root), [])

    def test_jpeg2000_named_as_jpeg_is_rejected_with_admin_diagnostic(self):
        with self.assertRaises(FakeHTTPException) as ctx:
            self.upload(
                data=JP2_BYTES,
                filename="HR_Walk_In_Clinic_Receipt_2018_Redacted.jpeg",
                content_type="image/jpeg",
            )

        self.assertEqual(ctx.exception.status_code, 415)
        detail = ctx.exception.detail
        self.assertEqual(detail["code"], "document_intake_file_type_not_allowed")
        self.assertEqual(detail["filename"], "HR_Walk_In_Clinic_Receipt_2018_Redacted.jpeg")
        self.assertEqual(detail["extension"], ".jpeg")
        self.assertEqual(detail["expected_format"], "jpeg")
        self.assertEqual(detail["detected_format"], "jpeg2000")
        self.assertEqual(detail["detected_mime_type"], "image/jp2")
        self.assertIn("JPEG 2000", detail["message"])
        self.assertIn("Export the file explicitly as JPEG", detail["message"])
        self.assertEqual(list_pending_documents(root=self.root), [])

    def test_empty_upload_is_rejected(self):
        with self.assertRaises(FakeHTTPException) as ctx:
            self.upload(data=b"", filename="empty.png", content_type="image/png")
        self.assertEqual(ctx.exception.status_code, 400)

    def test_size_limit_is_enforced_before_persistence(self):
        with patch.dict(os.environ, {"CDE_DOCUMENT_INTAKE_MAX_BYTES": "8"}):
            with self.assertRaises(FakeHTTPException) as ctx:
                self.upload(data=PNG_BYTES, filename="large.png", content_type="image/png")
        self.assertEqual(ctx.exception.status_code, 413)
        self.assertEqual(list_pending_documents(root=self.root), [])

    def test_duplicate_pending_intake_returns_structured_actionable_detail(self):
        self.upload()
        with self.assertRaises(FakeHTTPException) as ctx:
            self.upload()

        self.assertEqual(ctx.exception.status_code, 409)
        detail = ctx.exception.detail
        expected_hash = hashlib.sha256(PDF_BYTES).hexdigest()
        self.assertEqual(detail["detail"], "document_intake_duplicate")
        self.assertEqual(detail["code"], "document_intake_duplicate")
        self.assertEqual(detail["duplicate_reason"], "sha256")
        self.assertIn("Pending Intake", detail["message"])
        self.assertEqual(detail["existing_document"]["id"], expected_hash)
        self.assertEqual(detail["existing_document"]["title"], "Administrative decision")
        self.assertEqual(detail["existing_document"]["reference_identifier"], "INT-2026-001")
        self.assertEqual(detail["existing_document"]["lifecycle_state"], "pending")
        self.assertEqual(detail["existing_document"]["lifecycle_label"], "Pending Intake")
        self.assertEqual(detail["recommended_action"], "Continue review of the existing pending document.")
        self.assertEqual(detail["admin_url"], f"/admin/document-intake/{expected_hash}")
        self.assertEqual(len(list_intake_documents(root=self.root)), 1)

    def test_duplicate_pending_html_panel_has_safe_continue_review_action(self):
        self.upload()
        html_request = FakeRequest(
            cookies={admin_session.SESSION_COOKIE_NAME: self.session},
            query_params={"return_to": "https://evil.example/admin"},
        )
        html_request.headers = {"accept": "text/html"}

        response = self.upload(request=html_request)
        expected_hash = hashlib.sha256(PDF_BYTES).hexdigest()
        content = self.response_text(response)

        self.assertEqual(response.status_code, 409)
        self.assertIn("Duplicate document detected", content)
        self.assertIn("This document already exists in Pending Intake and is awaiting review.", content)
        self.assertIn("Administrative decision", content)
        self.assertIn("INT-2026-001", content)
        self.assertIn("Pending Intake", content)
        self.assertIn("Matched by", content)
        self.assertIn("SHA-256", content)
        self.assertIn("Continue review", content)
        self.assertIn(f'href="/admin/document-intake/{expected_hash}"', content)
        self.assertNotIn("evil.example", content)
        self.assertNotIn("Traceback", content)
        self.assertEqual(len(list_intake_documents(root=self.root)), 1)

    def test_duplicate_approved_and_published_states_have_lifecycle_guidance(self):
        self.upload()
        self.transition("under_review", "Review started.")
        self.transition("approved", "Approved.")
        with self.assertRaises(FakeHTTPException) as approved_ctx:
            self.upload()

        approved_detail = approved_ctx.exception.detail
        self.assertEqual(approved_ctx.exception.status_code, 409)
        self.assertEqual(approved_detail["detail"], "document_intake_duplicate")
        self.assertEqual(approved_detail["existing_document"]["lifecycle_state"], "approved")
        self.assertEqual(approved_detail["existing_document"]["lifecycle_label"], "Approved")
        self.assertIn("approved but not yet declared published", approved_detail["message"])
        self.assertEqual(
            approved_detail["recommended_action"],
            "Continue the publication workflow for the existing document.",
        )

        self.transition("published", "Published.")
        with self.assertRaises(FakeHTTPException) as published_ctx:
            self.upload()

        published_detail = published_ctx.exception.detail
        self.assertEqual(published_ctx.exception.status_code, 409)
        self.assertEqual(published_detail["detail"], "document_intake_duplicate")
        self.assertEqual(published_detail["existing_document"]["lifecycle_state"], "published")
        self.assertEqual(published_detail["existing_document"]["lifecycle_label"], "Published")
        self.assertIn("already been declared published", published_detail["message"])
        self.assertEqual(
            published_detail["recommended_action"],
            "Open the existing published document instead of creating a duplicate intake.",
        )
        self.assertEqual(len(list_intake_documents(root=self.root)), 1)

    def test_duplicate_detail_helper_identifies_existing_sha256_record(self):
        self.upload()
        detail = document_intake_duplicate_detail(PDF_BYTES, root=self.root)
        self.assertEqual(detail["detail"], "document_intake_duplicate")
        self.assertEqual(detail["duplicate_reason"], "sha256")
        self.assertEqual(detail["existing_document"]["lifecycle_label"], "Pending Intake")
        self.assertEqual(detail["existing_document"]["title"], "Administrative decision")

    def test_public_routes_do_not_expose_admin_duplicate_metadata(self):
        self.upload()
        self.transition("under_review", "Review started.")
        self.transition("approved", "Approved.")
        self.transition("published", "Published.")
        intake_id = hashlib.sha256(PDF_BYTES).hexdigest()

        content = documents.public_document_page(intake_id).content
        self.assertNotIn("document_intake_duplicate", content)
        self.assertNotIn("Duplicate document detected", content)
        self.assertNotIn("Continue review of the existing pending document.", content)

    def test_preview_requires_authentication_and_has_no_file_serving_route(self):
        self.upload()
        intake_id = hashlib.sha256(PDF_BYTES).hexdigest()
        response = admin_session.admin_document_intake_preview_page(
            intake_id, self.request
        )
        content = self.response_text(response)
        self.assertIn("Proposed storage location", content)
        self.assertNotIn("download", content.lower())
        with self.assertRaises(FakeHTTPException) as ctx:
            admin_session.admin_document_intake_preview_page(
                intake_id, FakeRequest()
            )
        self.assertEqual(ctx.exception.status_code, 401)

    def test_authenticated_image_preview_serves_original_private_bytes(self):
        self.upload(data=JPEG_BYTES, filename="Strike_001.jpg", content_type="image/jpeg")
        intake_id = hashlib.sha256(JPEG_BYTES).hexdigest()
        page = admin_session.admin_document_intake_preview_page(intake_id, self.request).content
        self.assertIn('class="admin-document-image-preview"', page)
        self.assertIn(f'/admin/document-intake/{intake_id}/preview', page)
        response = admin_session.admin_document_intake_image_preview(
            intake_id, self.request
        )
        self.assertEqual(response.media_type, "image/jpeg")
        self.assertEqual(Path(response.path).read_bytes(), JPEG_BYTES)
        with self.assertRaises(FakeHTTPException) as unauth_ctx:
            admin_session.admin_document_intake_image_preview(intake_id, FakeRequest())
        self.assertEqual(unauth_ctx.exception.status_code, 401)

    def test_png_preview_serves_original_bytes_and_pdf_preview_route_is_not_available(self):
        self.upload(data=PNG_BYTES, filename="Strike_003.png", content_type="image/png")
        png_id = hashlib.sha256(PNG_BYTES).hexdigest()
        png_response = admin_session.admin_document_intake_image_preview(
            png_id, self.request
        )
        self.assertEqual(png_response.media_type, "image/png")
        self.assertEqual(Path(png_response.path).read_bytes(), PNG_BYTES)

        self.upload()
        pdf_id = hashlib.sha256(PDF_BYTES).hexdigest()
        with self.assertRaises(FakeHTTPException) as ctx:
            admin_session.admin_document_intake_image_preview(pdf_id, self.request)
        self.assertEqual(ctx.exception.status_code, 404)

    def test_upload_does_not_mutate_public_records_or_attachment_tables(self):
        conn = sqlite3.connect(self.db_path)
        before = conn.execute("SELECT * FROM records").fetchall()
        before_tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        conn.close()

        self.upload()

        conn = sqlite3.connect(self.db_path)
        after = conn.execute("SELECT * FROM records").fetchall()
        after_tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        conn.close()
        self.assertEqual(after, before)
        self.assertEqual(after_tables, before_tables)

    def test_sidecar_json_is_stable_and_contains_no_file_bytes(self):
        item = store_pending_document(
            data=PDF_BYTES,
            original_filename="direct.pdf",
            content_type="application/pdf",
            uploaded_at="2026-07-08T12:00:00Z",
            root=self.root,
            **self.metadata(),
        )
        sidecar = self.root / item["intake_id"] / "metadata.json"
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
        self.assertEqual(payload, item)
        self.assertNotIn("%PDF", sidecar.read_text(encoding="utf-8"))

    def test_lifecycle_status_labels_are_complete(self):
        self.assertEqual(
            set(STATUS_LABELS),
            {"pending", "under_review", "approved", "published", "archived", "rejected"},
        )

    def test_pending_can_move_to_under_review_and_approved(self):
        self.upload()
        review_response = self.transition("under_review", "Review started.")
        self.assertIn("Under Review", self.response_text(review_response))
        approved_response = self.transition("approved", "Metadata verified.")
        self.assertIn("Approved", self.response_text(approved_response))

        item = list_intake_documents(root=self.root)[0]
        self.assertEqual(item["status"], "approved")
        self.assertEqual(
            [entry["new_status"] for entry in item["status_history"]],
            ["pending", "under_review", "approved"],
        )
        self.assertEqual(item["status_history"][-1]["actor"], "admin-user")

    def test_image_lifecycle_uses_existing_transitions_and_session_actor(self):
        self.upload(data=PNG_BYTES, filename="Strike_003.png", content_type="image/png")
        intake_id = hashlib.sha256(PNG_BYTES).hexdigest()
        for status, note in (
            ("under_review", "Image review started."),
            ("approved", "Image approved."),
            ("published", "Image published."),
        ):
            response = admin_session.admin_document_intake_status_update(
                intake_id,
                self.request,
                new_status=status,
                admin_note=note,
            )
            self.assertIn(STATUS_LABELS[status], self.response_text(response))
        item = load_pending_document(intake_id, root=self.root)
        self.assertEqual(item["status"], "published")
        self.assertEqual(
            [entry["new_status"] for entry in item["status_history"]],
            ["pending", "under_review", "approved", "published"],
        )
        self.assertTrue(
            all(entry["actor"] == "admin-user" for entry in item["status_history"])
        )
        self.assertIn("Image published.", {entry.get("note") for entry in item["status_history"]})

    def test_client_cannot_override_lifecycle_actor_identity(self):
        self.upload()
        intake_id = hashlib.sha256(PDF_BYTES).hexdigest()
        with self.assertRaises(TypeError):
            admin_session.admin_document_intake_status_update(
                intake_id,
                self.request,
                new_status="under_review",
                admin_note="Review started.",
                actor="mallory",
            )

        self.transition("under_review", "Review started.")
        item = load_pending_document(intake_id, root=self.root)
        self.assertEqual(item["status_history"][-1]["actor"], "admin-user")
        self.assertNotIn(
            "mallory",
            {str(entry.get("actor")) for entry in item["status_history"]},
        )

    def test_client_supplied_username_cannot_override_displayed_identity(self):
        session = admin_session.create_admin_session("session-user")
        request = FakeRequest(
            cookies={admin_session.SESSION_COOKIE_NAME: session},
            query_params={"username": "mallory", "actor": "mallory"},
        )
        content = self.response_text(admin_session.admin_document_intake_page(request))
        self.assertIn("<strong>session-user</strong>", content)
        self.assertNotIn("<strong>mallory</strong>", content)

    def test_status_history_actor_column_has_readable_styling_hook(self):
        response = self.upload()
        content = self.response_text(response)
        self.assertIn('class="status-history-wrapper audit-table-wrapper"', content)
        self.assertIn('<table class="status-history audit-history-table">', content)
        self.assertIn('<th class="history-timestamp">Timestamp</th>', content)
        self.assertIn('<th class="history-status history-previous-status">Previous status</th>', content)
        self.assertIn('<th class="history-status history-new-status">New status</th>', content)
        self.assertIn('<th class="status-history-actor history-actor">Actor</th>', content)
        self.assertIn('<th class="status-history-note history-note">Note</th>', content)
        self.assertIn('<td class="status-history-actor history-actor">admin-user</td>', content)
        self.assertIn("min-width:120px", content)
        self.assertIn("min-width:180px", content)
        self.assertIn("min-width:145px", content)
        self.assertIn("status-history-note", content)
        self.assertIn("Pending Intake", content)
        self.assertIn("Initial state", content)

    def test_status_history_preserves_long_actor_and_note_text(self):
        item = store_pending_document(
            data=b"%PDF-1.7\nlong-actor\n%%EOF\n",
            original_filename="long-actor.pdf",
            content_type="application/pdf",
            uploaded_at="2026-07-08T12:00:00Z",
            root=self.root,
            **self.metadata(),
        )
        long_actor = "administrator-with-a-very-long-session-derived-identifier"
        long_note = "Retain full internal note text for lifecycle review."
        item["status_history"][0]["actor"] = long_actor
        item["status_history"][0]["note"] = long_note
        content = admin_session._render_document_intake_preview(
            item,
            admin_session={"username": "admin-user"},
        )
        self.assertIn(long_actor, content)
        self.assertIn(long_note, content)
        self.assertIn(f'<td class="status-history-actor history-actor">{long_actor}</td>', content)
        self.assertIn("overflow-wrap:anywhere", content)

    def test_direct_helper_historical_default_actor_remains_unchanged(self):
        item = store_pending_document(
            data=b"%PDF-1.7\nhistorical\n%%EOF\n",
            original_filename="historical.pdf",
            content_type="application/pdf",
            uploaded_at="2026-07-08T12:00:00Z",
            root=self.root,
            **self.metadata(),
        )

        self.assertEqual(item["status_history"][0]["actor"], "admin")

    def test_under_review_can_be_rejected_then_archived(self):
        self.upload()
        self.transition("under_review")
        self.transition("rejected", "Outside intake scope.")
        response = self.transition("archived", "Retained privately.")
        item = list_intake_documents(root=self.root)[0]
        self.assertEqual(item["status"], "archived")
        self.assertIn("Archived", self.response_text(response))
        self.assertEqual(item["status_history"][-2]["new_status"], "rejected")

    def test_approved_can_be_archived_without_publication(self):
        self.upload()
        self.transition("under_review")
        self.transition("approved")
        self.transition("archived")
        self.assertEqual(list_intake_documents(root=self.root)[0]["status"], "archived")

    def test_published_is_declarative_and_can_be_archived(self):
        self.upload()
        self.transition("under_review")
        self.transition("approved")

        conn = sqlite3.connect(self.db_path)
        before = conn.execute("SELECT * FROM records").fetchall()
        before_tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        conn.close()

        response = self.transition("published", "Publication status declared.")
        item = list_intake_documents(root=self.root)[0]
        self.assertEqual(item["status"], "published")
        self.assertFalse(item["public_record_mutation"])
        self.assertIn("Public availability occurs only after", self.response_text(response))

        conn = sqlite3.connect(self.db_path)
        after = conn.execute("SELECT * FROM records").fetchall()
        after_tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        conn.close()
        self.assertEqual(after, before)
        self.assertEqual(after_tables, before_tables)

        self.transition("archived")
        self.assertEqual(list_intake_documents(root=self.root)[0]["status"], "archived")

    def test_invalid_transition_is_rejected_without_metadata_change(self):
        self.upload()
        intake_id = hashlib.sha256(PDF_BYTES).hexdigest()
        metadata_path = self.root / intake_id / "metadata.json"
        before = metadata_path.read_bytes()
        with self.assertRaises(FakeHTTPException) as ctx:
            self.transition("approved")
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.detail, "document_intake_transition_invalid")
        self.assertEqual(metadata_path.read_bytes(), before)

    def test_unauthenticated_status_and_notes_updates_are_denied(self):
        self.upload()
        with self.assertRaises(FakeHTTPException) as status_ctx:
            self.transition("under_review", request=FakeRequest())
        self.assertEqual(status_ctx.exception.status_code, 401)

        intake_id = hashlib.sha256(PDF_BYTES).hexdigest()
        with self.assertRaises(FakeHTTPException) as notes_ctx:
            admin_session.admin_document_intake_notes_update(
                intake_id, FakeRequest(), notes="private"
            )
        self.assertEqual(notes_ctx.exception.status_code, 401)
        self.assertEqual(load_pending_document(intake_id, root=self.root)["status"], "pending")

    def test_internal_notes_can_be_updated_and_remain_in_private_sidecar(self):
        self.upload()
        intake_id = hashlib.sha256(PDF_BYTES).hexdigest()
        response = admin_session.admin_document_intake_notes_update(
            intake_id,
            self.request,
            notes="Internal review note; do not publish.",
        )
        item = load_pending_document(intake_id, root=self.root)
        self.assertEqual(item["notes"], "Internal review note; do not publish.")
        self.assertIn("Internal review note; do not publish.", self.response_text(response))
        self.assertNotIn("download", self.response_text(response).lower())

    def test_management_page_lists_all_lifecycle_states_and_contextual_action(self):
        self.upload()
        self.transition("under_review")
        response = admin_session.admin_document_intake_page(self.request)
        content = self.response_text(response)
        self.assertIn("Intake management", content)
        self.assertIn("Under Review", content)
        self.assertIn("Review", content)


if __name__ == "__main__":
    unittest.main()
