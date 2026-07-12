import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from api.document_intake import store_pending_document, update_intake_status
from tests.test_admin_session import FakeFileResponse, FakeHTTPException, install_fastapi_stubs

install_fastapi_stubs()

from api.routes import documents


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
            self._move_to("published", item["intake_id"])
        return item["intake_id"]

    @staticmethod
    def content(response):
        return response.content

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
        self.assertIn("Published Document", content)
        self.assertIn("2026-07-08", content)
        self.assertIn(hashlib.sha256(b"%PDF-1.7\nfixture-published\n%%EOF\n").hexdigest(), content)
        self.assertIn(f'/documents/{document_id}/download', content)
        self.assertIn("Document Format", content)
        self.assertIn("PDF", content)
        self.assertIn("Provenance Summary", content)
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
                self.assertIn("View image", content)
                self.assertIn("Download original image", content)

    def test_published_image_downloads_return_exact_bytes_and_media_types(self):
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

    def test_every_private_state_is_inaccessible_by_page_and_download(self):
        for status in ("pending", "under_review", "approved", "archived", "rejected"):
            with self.subTest(status=status):
                with self.assertRaises(FakeHTTPException) as page_ctx:
                    documents.public_document_page(self.ids[status])
                self.assertEqual(page_ctx.exception.status_code, 404)
                with self.assertRaises(FakeHTTPException) as download_ctx:
                    documents.public_document_download(self.ids[status])
                self.assertEqual(download_ctx.exception.status_code, 404)
        with self.assertRaises(FakeHTTPException):
            documents.public_document_page(self.private_jpeg_id)
        with self.assertRaises(FakeHTTPException):
            documents.public_document_download(self.private_jpeg_id)

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
        library = documents.public_document_library(
            q=None, institution=None, category=None, publication_year=None
        )
        self.assertNotIn(">Published Document<", self.content(library))

    def test_unknown_and_malformed_ids_do_not_expose_files(self):
        for document_id in ("missing", "0" * 64):
            with self.subTest(document_id=document_id), self.assertRaises(
                FakeHTTPException
            ) as ctx:
                documents.public_document_download(document_id)
            self.assertEqual(ctx.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
