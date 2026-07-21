import json
import os
import tempfile
import unittest
import zipfile
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from api.document_intake import (
    list_intake_documents,
    load_pending_document,
    store_pending_document,
    update_intake_status,
)
from api.public_document_preview import render_public_document_preview
from tests.test_admin_session import install_fastapi_stubs

install_fastapi_stubs()

from api.routes import documents


PDF_BYTES = b"%PDF-1.7\npreview pdf\n%%EOF\n"
JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01preview-jpeg\xff\xd9"
PNG_BYTES = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDRpreview-png"
M4A_BYTES = b"\x00\x00\x00\x18ftypM4A \x00\x00\x00\x00preview audio"
RTF_BYTES = b"{\\rtf1\\ansi Preview rich text document.}"


def xlsx_bytes() -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as package:
        package.writestr(
            "[Content_Types].xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
</Types>""",
        )
        package.writestr(
            "xl/workbook.xml",
            """<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheets><sheet name="Preview" sheetId="1"/></sheets></workbook>""",
        )
        package.writestr("xl/worksheets/sheet1.xml", "<worksheet/>")
    return buffer.getvalue()


class PublicDocumentPreviewEnhancementTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "pending"
        self.env = patch.dict(
            os.environ,
            {"CDE_DOCUMENT_INTAKE_ROOT": str(self.root)},
            clear=False,
        )
        self.env.start()
        self.pdf_id = self._published(
            PDF_BYTES,
            filename="preview.pdf",
            content_type="application/pdf",
            title="Preview PDF Document",
            reference="PREVIEW-PDF-001",
        )
        self.jpeg_id = self._published(
            JPEG_BYTES,
            filename="preview.jpg",
            content_type="image/jpeg",
            title='Preview JPEG "Quoted" Image',
            reference="PREVIEW-JPEG-001",
        )
        self.png_id = self._published(
            PNG_BYTES,
            filename="preview.png",
            content_type="image/png",
            title="Preview PNG Image",
            reference="PREVIEW-PNG-001",
        )
        self.rtf_id = self._published(
            RTF_BYTES,
            filename="preview.rtf",
            content_type="application/rtf",
            title="Preview RTF Document",
            reference="PREVIEW-RTF-001",
        )
        self.xlsx_id = self._published(
            xlsx_bytes(),
            filename="preview.xlsx",
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            title="Preview Spreadsheet Document",
            reference="PREVIEW-XLSX-001",
        )
        self.audio_id = self._published(
            M4A_BYTES,
            filename="preview.m4a",
            content_type="audio/mp4",
            title="Preview Audio Document",
            reference="PREVIEW-AUDIO-001",
        )
        self.private_image_id = self._stored(
            JPEG_BYTES + b"-private",
            filename="private.jpg",
            content_type="image/jpeg",
            title="Private Preview Image",
            reference="PRIVATE-PREVIEW-001",
            publish=False,
        )

    def tearDown(self):
        self.env.stop()
        self.temp_dir.cleanup()

    def _stored(self, data, *, filename, content_type, title, reference, publish=True):
        item = store_pending_document(
            data=data,
            original_filename=filename,
            content_type=content_type,
            title=title,
            institution_source="Preview Institution",
            document_date="2026-07-20",
            category="Preview",
            description=f"Description for {title}.",
            visibility="private",
            notes="Private notes.",
            reference_identifier=reference,
            uploaded_at="2026-07-20T10:00:00Z",
            root=self.root,
        )
        if publish:
            for status, timestamp in (
                ("under_review", "2026-07-20T11:00:00Z"),
                ("approved", "2026-07-20T12:00:00Z"),
                ("published", "2026-07-20T13:00:00Z"),
            ):
                update_intake_status(
                    item["intake_id"],
                    status,
                    actor="preview-admin",
                    note=f"{status} note.",
                    changed_at=timestamp,
                    root=self.root,
                )
        return item["intake_id"]

    def _published(self, *args, **kwargs):
        return self._stored(*args, publish=True, **kwargs)

    @staticmethod
    def content(response):
        return response.content

    def test_library_renders_preview_column_without_losing_reference_or_title_link(self):
        content = self.content(documents.public_document_library())
        self.assertIn("<th>Preview</th>", content)
        self.assertIn("<th>Optional Reference Identifier</th>", content)
        self.assertIn(f'<a href="/documents/{self.pdf_id}">Preview PDF Document</a>', content)
        self.assertIn("6 published documents.", content)
        self.assertIn("PREVIEW-PDF-001", content)
        self.assertNotIn("Private Preview Image", content)

    def test_image_documents_render_constrained_accessible_thumbnails(self):
        content = self.content(documents.public_document_library())
        self.assertIn(f'href="/documents/{self.jpeg_id}" aria-label="Open Published Document: Preview JPEG &quot;Quoted&quot; Image"', content)
        self.assertIn(f'src="/documents/{self.jpeg_id}/view"', content)
        self.assertIn('alt="Preview of Preview JPEG &quot;Quoted&quot; Image"', content)
        self.assertIn(f'src="/documents/{self.png_id}/view"', content)
        self.assertIn("public-document-thumbnail", content)
        self.assertIn("object-fit:contain", content)
        self.assertIn("width:112px", content)
        self.assertIn("height:84px", content)
        self.assertIn("Preview image", content)

    def test_non_image_documents_render_visible_fallback_previews(self):
        content = self.content(documents.public_document_library())
        for label, action in (
            ("PDF", "Open PDF document"),
            ("Rich Text", "Open Rich Text document"),
            ("Spreadsheet", "Open Spreadsheet document"),
            ("Audio", "Open Audio document"),
        ):
            with self.subTest(label=label):
                self.assertIn(f'<span class="preview-media-label">{label}</span>', content)
                self.assertIn(action, content)
        self.assertIn(f'href="/documents/{self.rtf_id}"', content)
        self.assertIn(f'href="/documents/{self.xlsx_id}"', content)
        self.assertIn(f'href="/documents/{self.audio_id}"', content)

    def test_missing_preview_file_falls_back_without_leaking_storage_path(self):
        item = load_pending_document(self.jpeg_id, root=self.root)
        Path(item["proposed_storage_location"]).unlink()
        content = self.content(documents.public_document_library())
        self.assertIn("Preview unavailable", content)
        self.assertIn(f'href="/documents/{self.jpeg_id}"', content)
        self.assertNotIn(str(self.root), content)
        self.assertIn("Preview PNG Image", content)

    def test_preview_helper_handles_unknown_media_as_generic_file(self):
        item = load_pending_document(self.pdf_id, root=self.root)
        item["document_type"] = "mystery"
        preview = render_public_document_preview(item, root=self.root)
        self.assertIn("File", preview)
        self.assertIn("Open Published Document", preview)
        self.assertIn(f'href="/documents/{self.pdf_id}"', preview)

    def test_preview_rendering_does_not_create_or_mutate_governed_document(self):
        before_items = list_intake_documents(root=self.root)
        before = {
            item["intake_id"]: {
                "status": item.get("status"),
                "sha256_hash": item.get("sha256_hash"),
                "reference_identifier": item.get("reference_identifier"),
                "history": json.dumps(item.get("status_history") or [], sort_keys=True),
            }
            for item in before_items
        }
        documents.public_document_library()
        after_items = list_intake_documents(root=self.root)
        after = {
            item["intake_id"]: {
                "status": item.get("status"),
                "sha256_hash": item.get("sha256_hash"),
                "reference_identifier": item.get("reference_identifier"),
                "history": json.dumps(item.get("status_history") or [], sort_keys=True),
            }
            for item in after_items
        }
        self.assertEqual(before, after)
        self.assertEqual(len(before_items), len(after_items))

    def test_responsive_accessible_table_markup_is_present(self):
        content = self.content(documents.public_document_library())
        self.assertIn('role="region" aria-label="Published documents table"', content)
        self.assertIn("document-preview-cell", content)
        self.assertIn("@media(max-width:800px)", content)
        self.assertIn("preview-action", content)
        self.assertIn("outline:3px solid #2e8b9a", content)


if __name__ == "__main__":
    unittest.main()
