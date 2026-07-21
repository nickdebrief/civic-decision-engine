import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from api.document_intake import (
    build_document_search_text,
    load_pending_document,
    reindex_published_document_search,
    store_pending_document,
    update_intake_status,
)
from tests.test_admin_session import FakeFileResponse, FakeHTTPException, FakeRequest, install_fastapi_stubs

install_fastapi_stubs()

from api.routes import admin_session, documents


JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x02public-jpeg\xff\xd9"
PNG_BYTES = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDRpublic-png"


class PublicDocumentLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "pending"
        self.env = patch.dict(
            os.environ,
            {"CDE_DOCUMENT_INTAKE_ROOT": str(self.root)},
            clear=False,
        )
        self.env.start()
        self.ids = {}
        for index, status in enumerate(
            ("pending", "under_review", "approved", "published", "archived", "rejected"),
            start=1,
        ):
            data = f"%PDF-1.7\nfixture-{status}\n%%EOF\n".encode()
            item = store_pending_document(
                data=data,
                original_filename=f"{status}.pdf",
                content_type="application/pdf",
                title=f"{status.replace('_', ' ').title()} Document",
                institution_source="Civic Office" if status == "published" else "Private Office",
                document_date=f"202{index}-01-0{index}",
                category="Decision" if status == "published" else "Private",
                description=f"Description for {status}.",
                visibility="private",
                notes="Private administrative notes.",
                reference_identifier=f"REF-{status.upper()}",
                uploaded_at=f"2026-01-0{index}T10:00:00Z",
                root=self.root,
            )
            self.ids[status] = item["intake_id"]
            self._move_to(status, item["intake_id"])
        self.jpeg_id = self._store_document(
            data=JPEG_BYTES,
            original_filename="Strike_001.jpg",
            content_type="image/jpeg",
            title="Published JPEG Image",
            category="Public Record Image",
            reference_identifier="STRIKE-001",
        )
        self.png_id = self._store_document(
            data=PNG_BYTES,
            original_filename="Strike_003.png",
            content_type="image/png",
            title="Published PNG Image",
            category="Public Record Image",
            reference_identifier="STRIKE-003",
        )
        self.private_jpeg_id = self._store_document(
            data=JPEG_BYTES + b"-private",
            original_filename="Private_Strike.jpg",
            content_type="image/jpeg",
            title="Private JPEG Image",
            category="Private",
            reference_identifier="PRIVATE-STRIKE",
            publish=False,
        )

    def tearDown(self):
        self.env.stop()
        self.temp_dir.cleanup()

    def _move_to(self, target, intake_id):
        paths = {
            "pending": (),
            "under_review": ("under_review",),
            "approved": ("under_review", "approved"),
            "published": ("under_review", "approved", "published"),
            "rejected": ("under_review", "rejected"),
            "archived": ("under_review", "approved", "archived"),
        }
        for step_number, status in enumerate(paths[target], start=1):
            changed_at = (
                "2026-07-08T12:00:00Z"
                if status == "published"
                else f"2026-07-08T11:0{step_number}:00Z"
            )
            update_intake_status(
                intake_id,
                status,
                changed_at=changed_at,
                root=self.root,
            )

    def _store_document(
        self,
        *,
        data,
        original_filename,
        content_type,
        title,
        category,
        reference_identifier,
        publish=True,
    ):
        item = store_pending_document(
            data=data,
            original_filename=original_filename,
            content_type=content_type,
            title=title,
            institution_source="Nick Moloney",
            document_date="2026-07-09",
            category=category,
            description=f"Description for {title}.",
            visibility="private",
            notes="Private administrative notes.",
            reference_identifier=reference_identifier,
            uploaded_at="2026-07-09T10:00:00Z",
            root=self.root,
        )
        if publish:
            update_intake_status(
                item["intake_id"],
                "under_review",
                actor="nick",
                note="Review started.",
                changed_at="2026-07-09T11:00:00Z",
                root=self.root,
            )
            update_intake_status(
                item["intake_id"],
                "approved",
                actor="nick",
                note="Approved for publication.",
                changed_at="2026-07-09T12:00:00Z",
                root=self.root,
            )
            update_intake_status(
                item["intake_id"],
                "published",
                actor="nick",
                note="Published to Public Document Library.",
                changed_at="2026-07-09T13:00:00Z",
                root=self.root,
            )
        return item["intake_id"]

    @staticmethod
    def content(response):
        return response.content

    def _write_metadata(self, document_id, metadata):
        metadata_path = self.root / document_id / "metadata.json"

        metadata_path.write_text(
            json.dumps(metadata, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def _store_expanded_search_fixture(self, *, publish=True):
        data = (
            b"%PDF-1.7\nexpanded-search-fixture-published\n%%EOF\n"
            if publish
            else b"%PDF-1.7\nexpanded-search-fixture-private\n%%EOF\n"
        )
        item = store_pending_document(
            data=data,
            original_filename="evidence_package.pdf",
            content_type="application/pdf",
            title="Initial Complaint Evidence Package",
            institution_source="Nick Moloney",
            document_date="2019-12-02",
            category="Complaint Evidence",
            description="Council correspondence and supporting documents for the intake package.",
            visibility="private",
            notes="Private administrative notes.",
            reference_identifier="NM-EVID-PKG-20191202-001",
            uploaded_at="2026-07-15T09:00:00Z",
            root=self.root,
        )
        if publish:
            update_intake_status(
                item["intake_id"],
                "under_review",
                actor="nick",
                note="Review started.",
                changed_at="2026-07-16T10:00:00Z",
                root=self.root,
            )
            update_intake_status(
                item["intake_id"],
                "approved",
                actor="nick",
                note="Approved.",
                changed_at="2026-07-16T11:00:00Z",
                root=self.root,
            )
            update_intake_status(
                item["intake_id"],
                "published",
                actor="nick",
                note="Published.",
                changed_at="2026-07-16T12:00:00Z",
                root=self.root,
            )
        metadata = load_pending_document(item["intake_id"], root=self.root)
        metadata["original_filename"] = "1st_Files_for_complaints@mirl.zip"
        metadata["ocr_text"] = "OCR-only memorandum transcript."
        metadata["body_text"] = "Body-only procedural bundle marker."
        metadata["tags"] = ["medical", "council-tag", "evidence-package-tag"]
        self._write_metadata(item["intake_id"], metadata)
        return item["intake_id"]

    def test_library_contains_only_published_documents(self):
        response = documents.public_document_library(
            q=None, institution=None, category=None, publication_year=None
        )
        content = self.content(response)
        self.assertIn("Published Document", content)
        for status in ("Pending", "Under Review", "Approved", "Archived", "Rejected"):
            self.assertNotIn(f">{status} Document<", content)
        self.assertIn("3 published documents.", content)
        self.assertIn("Publication does not certify legal status", content)
        self.assertIn("Published JPEG Image", content)
        self.assertIn("Published PNG Image", content)
        self.assertNotIn("Private JPEG Image", content)

    def test_search_matches_title_institution_category_and_reference(self):
        for query in ("Published Document", "Civic Office", "Decision", "REF-PUBLISHED"):
            with self.subTest(query=query):
                response = documents.public_document_library(
                    q=query, institution=None, category=None, publication_year=None
                )
                self.assertIn("Published Document", self.content(response))
        for query, expected in (
            ("Nick Moloney", "Published JPEG Image"),
            ("Public Record Image", "Published PNG Image"),
            ("STRIKE-001", "Published JPEG Image"),
        ):
            with self.subTest(query=query):
                response = documents.public_document_library(
                    q=query, institution=None, category=None, publication_year=None
                )
                self.assertIn(expected, self.content(response))
        response = documents.public_document_library(
            q="no match", institution=None, category=None, publication_year=None
        )
        self.assertIn("No published documents match", self.content(response))

    def test_search_matches_expanded_public_document_fields(self):
        self._store_expanded_search_fixture()
        for query in (
            "Medical Council",
            "Initial Complaint",
            "Nick Moloney",
            "Evidence Package",
            "NM-EVID-PKG-20191202-001",
            "2019-12-02",
            "2026-07-16",
            "1st_Files_for_complaints@mirl.zip",
            "correspondence",
            "council-tag",
            "OCR-only",
            "Body-only",
            "initial correspondence",
            "medical",
            "nm-evid-pkg",
            "20191202",
        ):
            with self.subTest(query=query):
                response = documents.public_document_library(
                    q=query,
                    institution=None,
                    category=None,
                    publication_year=None,
                )
                content = self.content(response)
                self.assertIn("Initial Complaint Evidence Package", content)
                self.assertIn("NM-EVID-PKG-20191202-001", content)

    def test_search_handles_empty_null_and_serialized_tag_values(self):
        document_id = self._store_expanded_search_fixture()
        metadata = load_pending_document(document_id, root=self.root)
        metadata["ocr_text"] = None
        metadata["body_text"] = ""
        metadata["tags"] = json.dumps(["serialized-tag-only", "Council Archive"])
        self._write_metadata(document_id, metadata)

        search_text = build_document_search_text(metadata)
        self.assertIn("serialized-tag-only", search_text)
        self.assertIn("council archive", search_text)
        response = documents.public_document_library(
            q="serialized-tag-only",
            institution=None,
            category=None,
            publication_year=None,
        )
        self.assertIn("Initial Complaint Evidence Package", self.content(response))

    def test_search_excludes_unpublished_documents_with_matching_metadata(self):
        self._store_expanded_search_fixture(publish=False)
        response = documents.public_document_library(
            q="NM-EVID-PKG-20191202-001",
            institution=None,
            category=None,
            publication_year=None,
        )
        self.assertNotIn("Initial Complaint Evidence Package", self.content(response))

    def test_existing_published_documents_are_searchable_after_reindex_backfill(self):
        self._store_expanded_search_fixture()
        result = reindex_published_document_search(root=self.root)
        self.assertGreaterEqual(result["indexed"], 1)
        self.assertEqual([], result["failures"])
        response = documents.public_document_library(
            q="1st_Files_for_complaints@mirl.zip",
            institution=None,
            category=None,
            publication_year=None,
        )
        self.assertIn("Initial Complaint Evidence Package", self.content(response))

    def test_institution_category_and_publication_year_filters(self):
        matching = documents.public_document_library(
            q=None,
            institution="Civic Office",
            category="Decision",
            publication_year="2026",
        )
        self.assertIn("Published Document", self.content(matching))
        for field, value in (
            ("institution", "Private Office"),
            ("category", "Private"),
            ("publication_year", "2025"),
        ):
            arguments = {
                "q": None,
                "institution": None,
                "category": None,
                "publication_year": None,
            }
            arguments[field] = value
            with self.subTest(field=field):
                response = documents.public_document_library(**arguments)
                self.assertIn("No published documents match", self.content(response))

    def test_published_document_page_displays_metadata_hash_download_and_provenance(self):
        document_id = self.ids["published"]
        response = documents.public_document_page(document_id)
        content = self.content(response)
        digest = hashlib.sha256(b"%PDF-1.7\nfixture-published\n%%EOF\n").hexdigest()
        self.assertIn("Published Document", content)
        self.assertIn("2026-07-08", content)
        self.assertIn(digest, content)
        self.assertIn(f'/documents/{document_id}/download', content)
        self.assertIn("Document Format", content)
        self.assertIn("PDF", content)
        self.assertIn("Publication Provenance", content)
        self.assertIn("Publication Pathway", content)
        self.assertIn("Server-detected document format", content)
        self.assertIn("Original filename", content)
        self.assertIn("published.pdf", content)
        self.assertIn("File size", content)
        self.assertIn("SHA-256 digest", content)
        self.assertIn("Initial intake actor", content)
        self.assertIn("Review actor", content)
        self.assertIn("Approval actor", content)
        self.assertIn("Publication actor", content)
        self.assertIn("Public presentation mode", content)
        self.assertIn("Downloadable PDF", content)
        self.assertIn("Original PDF download available", content)
        self.assertIn("The SHA-256 digest identifies the exact original bytes", content)
        self.assertNotIn("digital signature", content.lower())
        self.assertNotIn("proves truth", content.lower())
        self.assertNotIn("approval proves", content.lower())
        self.assertNotIn("Signed in as", content)
        self.assertNotIn("Private administrative notes", content)
        self.assertNotIn(str(self.root), content)
        self.assertNotIn('class="public-document-image"', content)

    def test_published_pdf_download_returns_original_filename(self):
        response = documents.public_document_download(self.ids["published"])
        self.assertIsInstance(response, FakeFileResponse)
        self.assertEqual(response.media_type, "application/pdf")
        self.assertEqual(response.filename, "published.pdf")
        self.assertTrue(Path(response.path).is_file())
        self.assertTrue(str(Path(response.path)).startswith(str(self.root.resolve())))

    def test_published_image_pages_render_constrained_image_and_format_labels(self):
        for document_id, title, label in (
            (self.jpeg_id, "Published JPEG Image", "JPEG"),
            (self.png_id, "Published PNG Image", "PNG"),
        ):
            with self.subTest(title=title):
                content = self.content(documents.public_document_page(document_id))
                self.assertIn(title, content)
                self.assertIn(f"<td>{label}</td>", content)
                self.assertIn('class="public-document-image"', content)
                self.assertIn('max-width:100%', content)
                self.assertIn(f'alt="{title}"', content)
                self.assertIn(f'/documents/{document_id}/view', content)
                self.assertIn(f'/documents/{document_id}/download', content)
                self.assertIn("View image", content)
                self.assertIn("Download original image", content)

    def test_published_image_view_returns_exact_bytes_inline_and_media_types(self):
        cases = (
            (self.jpeg_id, "image/jpeg", "Strike_001.jpg", JPEG_BYTES),
            (self.png_id, "image/png", "Strike_003.png", PNG_BYTES),
        )
        for document_id, media_type, filename, expected_bytes in cases:
            with self.subTest(filename=filename):
                response = documents.public_document_image_view(document_id)
                self.assertIsInstance(response, FakeFileResponse)
                self.assertEqual(response.media_type, media_type)
                self.assertEqual(Path(response.path).read_bytes(), expected_bytes)
                self.assertIn(
                    "inline",
                    response.headers.get("Content-Disposition", ""),
                )
                self.assertIn(filename, response.headers.get("Content-Disposition", ""))

    def test_published_image_downloads_return_exact_bytes_attachment_and_media_types(self):
        cases = (
            (self.jpeg_id, "image/jpeg", "Strike_001.jpg", JPEG_BYTES),
            (self.png_id, "image/png", "Strike_003.png", PNG_BYTES),
        )
        for document_id, media_type, filename, expected_bytes in cases:
            with self.subTest(filename=filename):
                response = documents.public_document_download(document_id)
                self.assertIsInstance(response, FakeFileResponse)
                self.assertEqual(response.media_type, media_type)
                self.assertEqual(response.filename, filename)
                self.assertEqual(Path(response.path).read_bytes(), expected_bytes)
                self.assertIn(
                    "attachment",
                    response.headers.get("Content-Disposition", ""),
                )
                self.assertIn(filename, response.headers.get("Content-Disposition", ""))

    def test_every_private_state_is_inaccessible_by_page_and_download(self):
        for status in ("pending", "under_review", "approved", "archived", "rejected"):
            with self.subTest(status=status):
                with self.assertRaises(FakeHTTPException) as page_ctx:
                    documents.public_document_page(self.ids[status])
                self.assertEqual(page_ctx.exception.status_code, 404)
                with self.assertRaises(FakeHTTPException) as download_ctx:
                    documents.public_document_download(self.ids[status])
                self.assertEqual(download_ctx.exception.status_code, 404)
                with self.assertRaises(FakeHTTPException) as view_ctx:
                    documents.public_document_image_view(self.ids[status])
                self.assertEqual(view_ctx.exception.status_code, 404)
        with self.assertRaises(FakeHTTPException):
            documents.public_document_page(self.private_jpeg_id)
        with self.assertRaises(FakeHTTPException):
            documents.public_document_download(self.private_jpeg_id)
        with self.assertRaises(FakeHTTPException):
            documents.public_document_image_view(self.private_jpeg_id)

    def test_pdf_is_not_served_through_public_image_view_route(self):
        with self.assertRaises(FakeHTTPException) as ctx:
            documents.public_document_image_view(self.ids["published"])
        self.assertEqual(ctx.exception.status_code, 404)

    def test_archiving_a_published_document_revokes_page_and_download(self):
        document_id = self.ids["published"]
        self.assertIn(
            "Published Document",
            self.content(documents.public_document_page(document_id)),
        )
        update_intake_status(
            document_id,
            "archived",
            changed_at="2026-07-08T13:00:00Z",
            root=self.root,
        )
        with self.assertRaises(FakeHTTPException):
            documents.public_document_page(document_id)
        with self.assertRaises(FakeHTTPException):
            documents.public_document_download(document_id)
        with self.assertRaises(FakeHTTPException):
            documents.public_document_image_view(document_id)
        library = documents.public_document_library(
            q=None, institution=None, category=None, publication_year=None
        )
        self.assertNotIn(">Published Document<", self.content(library))

    def test_published_image_pages_include_expanded_provenance_modes(self):
        for document_id, title, label, mode in (
            (self.jpeg_id, "Published JPEG Image", "JPEG", "Inline image view and original-file download"),
            (self.png_id, "Published PNG Image", "PNG", "Inline image view and original-file download"),
        ):
            with self.subTest(title=title):
                content = self.content(documents.public_document_page(document_id))
                self.assertIn("Publication Provenance", content)
                self.assertIn("Publication Pathway", content)
                self.assertIn("Server-detected document format", content)
                self.assertIn(label, content)
                self.assertIn(mode, content)
                self.assertIn("Original image download available", content)
                self.assertIn("nick", content)
                self.assertIn("Published to Public Document Library.", content)

    def test_publication_pathway_preserves_stored_events_chronologically(self):
        content = self.content(documents.public_document_page(self.jpeg_id))
        expected = [
            "2026-07-09T10:00:00Z",
            "2026-07-09T11:00:00Z",
            "2026-07-09T12:00:00Z",
            "2026-07-09T13:00:00Z",
        ]
        positions = [content.index(value) for value in expected]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("Initial state", content)
        self.assertIn("Pending Intake", content)
        self.assertIn("Under Review", content)
        self.assertIn("Approved", content)
        self.assertIn("Published", content)
        self.assertIn("admin", content)
        self.assertIn("nick", content)
        self.assertEqual(content.count("Published to Public Document Library."), 1)

    def test_publication_timestamp_uses_earliest_published_transition(self):
        metadata = load_pending_document(self.jpeg_id, root=self.root)
        metadata["status_history"].append(
            {
                "previous_status": "approved",
                "new_status": "published",
                "timestamp": "2026-07-10T13:00:00Z",
                "actor": "admin",
                "note": "Historical duplicate publish marker.",
            }
        )
        metadata["publication_date"] = "2026-07-10T13:00:00Z"
        self._write_metadata(self.jpeg_id, metadata)
        content = self.content(documents.public_document_page(self.jpeg_id))
        self.assertIn("Publication timestamp", content)
        self.assertIn("2026-07-09T13:00:00Z", content)
        self.assertIn("2026-07-10T13:00:00Z", content)
        self.assertIn("Historical duplicate publish marker.", content)

    def test_missing_optional_and_historical_fields_render_neutrally(self):
        metadata = load_pending_document(self.ids["published"], root=self.root)
        metadata.pop("document_type", None)
        metadata.pop("content_type", None)
        metadata["reference_identifier"] = None
        metadata["status_history"][1].pop("actor", None)
        metadata["status_history"][2]["note"] = ""
        self._write_metadata(self.ids["published"], metadata)
        content = self.content(documents.public_document_page(self.ids["published"]))
        self.assertIn("PDF", content)
        self.assertIn("Optional Reference Identifier", content)
        self.assertIn("—", content)
        self.assertIn("Publication Pathway", content)

    def test_public_provenance_escapes_malicious_metadata(self):
        metadata = load_pending_document(self.jpeg_id, root=self.root)
        metadata["title"] = '<script>alert("title")</script>'
        metadata["original_filename"] = '<img src=x onerror=alert(1)>.jpg'
        metadata["reference_identifier"] = '<b>REF</b>'
        metadata["status_history"][1]["actor"] = '<script>actor</script>'
        metadata["status_history"][1]["note"] = '<img src=x onerror=alert(2)>'
        self._write_metadata(self.jpeg_id, metadata)
        content = self.content(documents.public_document_page(self.jpeg_id))
        self.assertIn("&lt;script&gt;alert", content)
        self.assertIn("&lt;img src=x onerror=alert", content)
        self.assertIn("&lt;b&gt;REF&lt;/b&gt;", content)
        self.assertNotIn('<script>alert("title")</script>', content)
        self.assertNotIn('<img src=x onerror=alert(2)>', content)

    def test_public_provenance_has_semantic_classes_and_no_mutation_forms(self):
        content = self.content(documents.public_document_page(self.jpeg_id))
        for snippet in (
            'class="publication-provenance"',
            'class="publication-provenance-grid"',
            'class="publication-provenance-label"',
            'class="publication-provenance-value"',
            'class="publication-pathway-wrapper"',
            'class="publication-pathway-table"',
            'class="publication-pathway-timestamp"',
            'class="publication-pathway-previous-status"',
            'class="publication-pathway-new-status"',
            'class="publication-pathway-actor"',
            'class="publication-pathway-note"',
            'class="provenance-boundary"',
            "overflow-wrap:anywhere",
            "overflow-x:auto",
        ):
            self.assertIn(snippet, content)
        self.assertNotIn('name="new_status"', content)
        self.assertNotIn("Declare published", content)
        self.assertNotIn("Update private notes", content)

    def test_public_provenance_does_not_add_public_audit_endpoint(self):
        self.assertFalse(hasattr(documents, "public_audit_page"))
        with self.assertRaises(FakeHTTPException):
            admin_session.admin_audit_page(FakeRequest())

    def test_unknown_and_malformed_ids_do_not_expose_files(self):
        for document_id in ("missing", "0" * 64):
            with self.subTest(document_id=document_id), self.assertRaises(
                FakeHTTPException
            ) as ctx:
                documents.public_document_download(document_id)
            self.assertEqual(ctx.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
