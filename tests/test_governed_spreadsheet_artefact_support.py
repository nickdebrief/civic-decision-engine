import hashlib
import os
import sqlite3
import tempfile
import unittest
import zipfile
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from api.document_intake import (
    build_document_search_text,
    document_media_type,
    intake_document_file,
    is_spreadsheet_document,
    load_pending_document,
    store_pending_document,
    update_intake_status,
    validate_document_file,
)
from tests.test_admin_session import FakeRequest, install_fastapi_stubs

install_fastapi_stubs()

from api import archive_collection_memberships as acm
from api import archive_collections as ac
from api import record_document_associations as rda
from api.routes import admin_session, collections as collection_routes, documents


PDF_BYTES = b"%PDF-1.7\nspreadsheet regression\n%%EOF\n"
JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01spreadsheet-regression\xff\xd9"
PNG_BYTES = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDRspreadsheet-regression"
M4A_BYTES = b"\x00\x00\x00\x18ftypM4A \x00\x00\x00\x00audio"
MP3_BYTES = b"ID3\x04\x00\x00\x00\x00\x00\x15audio"
WAV_BYTES = b"RIFF\x24\x00\x00\x00WAVEfmt audio"


def _xlsx_bytes(
    *,
    sheet_names=("Usage", "Summary"),
    hidden=False,
    macro=False,
    unsafe_path=False,
    arbitrary=False,
    external_link=False,
    bomb=False,
) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as package:
        if arbitrary:
            package.writestr("not-a-workbook.txt", "plain zip")
            return buffer.getvalue()
        content_type = (
            "application/vnd.ms-excel.sheet.macroEnabled.main+xml"
            if macro
            else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"
        )
        package.writestr(
            "[Content_Types].xml",
            f"""<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="{content_type}"/>
</Types>""",
        )
        sheets = "".join(
            f'<sheet name="{name}" sheetId="{index}" r:id="rId{index}"{" state=\"hidden\"" if hidden and index == 1 else ""}/>'
            for index, name in enumerate(sheet_names, start=1)
        )
        package.writestr(
            "xl/workbook.xml",
            f"""<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>{sheets}</sheets><calcPr calcMode="manual"/></workbook>""",
        )
        package.writestr("xl/worksheets/sheet1.xml", "<worksheet/>")
        if macro:
            package.writestr("xl/vbaProject.bin", b"macro")
        if unsafe_path:
            package.writestr("../evil.txt", "unsafe")
        if external_link:
            package.writestr("xl/externalLinks/externalLink1.xml", "<externalLink/>")
        if bomb:
            package.writestr("xl/worksheets/big.xml", b"A" * (6 * 1024 * 1024))
    return buffer.getvalue()


def _directory_entry(name: str, object_type: int, start_sector: int = 0, size: int = 0) -> bytes:
    entry = bytearray(128)
    raw_name = (name + "\x00").encode("utf-16le")
    entry[: len(raw_name)] = raw_name
    entry[64:66] = len(raw_name).to_bytes(2, "little")
    entry[66] = object_type
    entry[116:120] = start_sector.to_bytes(4, "little", signed=False)
    entry[120:128] = size.to_bytes(8, "little", signed=False)
    return bytes(entry)


def _xls_ole_bytes(*, workbook=True, word=False, encrypted=False, macro=False, corrupt=False) -> bytes:
    if corrupt:
        return b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1corrupt"
    header = bytearray(512)
    header[:8] = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
    header[26:28] = (0x003E).to_bytes(2, "little")
    header[28:30] = (0x0003).to_bytes(2, "little")
    header[30:32] = (9).to_bytes(2, "little")
    header[32:34] = (6).to_bytes(2, "little")
    header[44:48] = (1).to_bytes(4, "little")
    header[48:52] = (1).to_bytes(4, "little")
    header[56:60] = (4096).to_bytes(4, "little")
    header[60:64] = (0xFFFFFFFF).to_bytes(4, "little")
    header[68:72] = (0xFFFFFFFF).to_bytes(4, "little")
    for offset in range(76, 512, 4):
        header[offset : offset + 4] = (0xFFFFFFFF).to_bytes(4, "little")
    header[76:80] = (0).to_bytes(4, "little")

    fat = bytearray(512)
    entries = [0xFFFFFFFD, 0xFFFFFFFE, 0xFFFFFFFE]
    entries.extend([0xFFFFFFFF] * 125)
    for index, value in enumerate(entries):
        fat[index * 4 : index * 4 + 4] = value.to_bytes(4, "little")

    directory = bytearray(512)
    directory[0:128] = _directory_entry("Root Entry", 5)
    stream_name = "WordDocument" if word else "Workbook" if workbook else "NotWorkbook"
    if encrypted:
        stream_name = "EncryptionInfo"
    if macro:
        stream_name = "VBA"
    directory[128:256] = _directory_entry(stream_name, 2, start_sector=2, size=8)
    stream = b"Workbook" + b"\x00" * (512 - 8)
    return bytes(header + fat + directory + stream)


class GovernedSpreadsheetArtefactSupportTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "pending"
        self.db_path = Path(self.temp_dir.name) / "records.db"
        self.env = patch.dict(
            os.environ,
            {
                "ADMIN_USERNAME": "admin-user",
                "ADMIN_PASSWORD": "admin-password",
                "CDE_ADMIN_SESSION_SECRET": "session-secret",
                "CDE_DOCUMENT_INTAKE_ROOT": str(self.root),
                "RECORDS_DB_PATH": str(self.db_path),
            },
            clear=False,
        )
        self.env.start()
        self.originals = (admin_session.DB_PATH, ac.DB_PATH, rda.DB_PATH)
        admin_session.DB_PATH = self.db_path
        ac.DB_PATH = self.db_path
        rda.DB_PATH = self.db_path
        self.request = FakeRequest(cookies={admin_session.SESSION_COOKIE_NAME: admin_session.create_admin_session("admin-user")})
        self._init_records()

    def tearDown(self):
        admin_session.DB_PATH, ac.DB_PATH, rda.DB_PATH = self.originals
        self.env.stop()
        self.temp_dir.cleanup()

    def _init_records(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """
            CREATE TABLE records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reference TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 1,
                generated_at TEXT NOT NULL,
                trajectory TEXT,
                system_state TEXT,
                finding TEXT,
                report_json TEXT,
                language TEXT NOT NULL DEFAULT 'en',
                verification_hash TEXT NOT NULL,
                exported_at TEXT NOT NULL,
                is_latest INTEGER NOT NULL DEFAULT 1
            )
            """
        )
        conn.execute(
            """
            INSERT INTO records (
                reference, generated_at, trajectory, system_state, finding,
                report_json, verification_hash, exported_at, is_latest
            ) VALUES (
                'CMP-MC-20191202-001', '2026-07-22T09:00:00Z', 'Submitted',
                'Published', 'Complaint record summary.', '{}', 'record-hash',
                '2026-07-22T10:00:00Z', 1
            )
            """
        )
        conn.commit()
        conn.close()

    def _metadata(self, **overrides):
        data = {
            "original_filename": "Nick_Moloney_Member_Usage_Woodstock_2019.xlsx",
            "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "title": "Nick Moloney Member Usage Woodstock 2019",
            "institution_source": "Woodstock",
            "document_date": "2019-12-31",
            "category": "Spreadsheet",
            "description": "Legacy member usage workbook.",
            "visibility": "private",
            "notes": "Private spreadsheet intake note.",
            "reference_identifier": "NM-XLS-WOODSTOCK-2019-001",
            "keywords": "Woodstock, Member Usage, Spreadsheet, 2019",
            "actor": "admin-user",
            "root": self.root,
        }
        data.update(overrides)
        return data

    def _store(self, data: bytes, **overrides):
        return store_pending_document(data=data, **self._metadata(**overrides))

    def _publish(self, item):
        for status in ("under_review", "approved", "published"):
            item = update_intake_status(
                item["intake_id"],
                status,
                actor="admin-user",
                note=f"{status} note",
                root=self.root,
            )
        return item

    def test_valid_xls_and_xlsx_uploads_preserve_bytes_and_metadata(self):
        xls_bytes = _xls_ole_bytes()
        xlsx_bytes = _xlsx_bytes(sheet_names=("Members", "Usage"))
        xls = self._store(
            xls_bytes,
            original_filename="Nick_Moloney_Member_Usage_Woodstock_2019.xls",
            content_type="application/vnd.ms-excel",
        )
        xlsx = self._store(xlsx_bytes)

        self.assertEqual(xls["document_type"], "xls")
        self.assertEqual(xls["document_format"], "XLS")
        self.assertEqual(xls["content_type"], "application/vnd.ms-excel")
        self.assertEqual(xlsx["document_type"], "xlsx")
        self.assertEqual(xlsx["document_format"], "XLSX")
        self.assertTrue(is_spreadsheet_document(xlsx))
        self.assertEqual(document_media_type(xlsx), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        self.assertEqual(xlsx["workbook_metadata"]["worksheet_names"], ["Members", "Usage"])
        self.assertEqual(xlsx["workbook_metadata"]["calculation_mode"], "manual")
        self.assertEqual(hashlib.sha256(xlsx_bytes).hexdigest(), xlsx["sha256_hash"])
        file_path, _ = intake_document_file(xlsx["intake_id"], root=self.root)
        self.assertEqual(Path(file_path).read_bytes(), xlsx_bytes)

    def test_spreadsheet_lifecycle_public_page_download_search_association_and_collection(self):
        xlsx_bytes = _xlsx_bytes(sheet_names=("Woodstock Usage", "Summary"))
        item = self._publish(self._store(xlsx_bytes))
        page = documents.public_document_page(item["intake_id"]).content
        self.assertIn("Spreadsheet Artefact", page)
        self.assertIn("Download original spreadsheet", page)
        self.assertIn("Woodstock Usage", page)
        self.assertIn("XLSX", page)
        self.assertNotIn("Private spreadsheet intake note", page)

        download = documents.public_document_download(item["intake_id"])
        self.assertEqual(download.media_type, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        self.assertIn("attachment", download.headers["Content-Disposition"])
        self.assertIn("nosniff", download.headers["X-Content-Type-Options"])

        self.assertIn("woodstock usage", build_document_search_text(item))
        self.assertIn(item["reference_identifier"], documents.public_document_library(q="NM-XLS-WOODSTOCK").content)
        self.assertIn(item["title"], documents.public_document_library(q="xlsx").content)

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            association = rda.create_association(
                conn,
                record_reference="CMP-MC-20191202-001",
                document_id=item["intake_id"],
                relationship_type="supporting_document",
                public_label="Supporting spreadsheet",
                public_note="Published spreadsheet preserved as a governed artefact.",
                admin_note="Private association note.",
                is_public=True,
                actor="admin-user",
                root=self.root,
            )
            collection = ac.create_collection(
                conn,
                title="Spreadsheet Collection",
                subtitle="Workbook member",
                institution_source="Woodstock",
                category="documentary_archive",
                description="Collection including a spreadsheet artefact.",
                public_note="Public note.",
                admin_note="Private note.",
                date_from="2019-01-01",
                date_to=None,
                is_public=True,
                actor="admin-user",
            )
            membership = acm.create_membership(
                conn,
                collection_id=collection["id"],
                document_id=item["intake_id"],
                actor="admin-user",
                membership_note="Spreadsheet membership.",
                display_sequence=1,
                root=self.root,
            )
            for status in ("reviewed", "approved", "active"):
                acm.transition_membership(
                    conn,
                    membership["membership_reference"],
                    new_status=status,
                    actor="admin-user",
                    root=self.root,
                )
        finally:
            conn.close()
        self.assertIn("Supporting spreadsheet", documents.public_document_page(item["intake_id"]).content)
        collection_page = collection_routes.public_collection_page(collection["public_reference"]).content
        self.assertIn("Governed Member Documents", collection_page)
        self.assertIn("XLSX", collection_page)
        self.assertIn(item["title"], collection_page)
        self.assertTrue(association["public_reference"].startswith("CDE-ASSOC-"))

    def test_invalid_spreadsheet_uploads_are_rejected(self):
        cases = (
            (b"not excel", "plain.xls", "application/vnd.ms-excel", "document_intake_file_type_not_allowed"),
            (_xlsx_bytes(arbitrary=True), "plain.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "document_intake_invalid_workbook"),
            (_xls_ole_bytes(workbook=False), "generic.xls", "application/vnd.ms-excel", "document_intake_invalid_workbook"),
            (_xls_ole_bytes(word=True), "word.xls", "application/vnd.ms-excel", "document_intake_invalid_workbook"),
            (_xls_ole_bytes(corrupt=True), "corrupt.xls", "application/vnd.ms-excel", "document_intake_invalid_workbook"),
            (b"PK\x03\x04corrupt", "corrupt.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "document_intake_invalid_workbook"),
            (_xls_ole_bytes(), "renamed.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "document_intake_file_type_mismatch"),
            (_xlsx_bytes(), "renamed.xls", "application/vnd.ms-excel", "document_intake_file_type_mismatch"),
            (_xls_ole_bytes(encrypted=True), "encrypted.xls", "application/vnd.ms-excel", "document_intake_password_protected_workbook"),
            (_xlsx_bytes(macro=True), "macro.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "document_intake_macro_enabled_workbook"),
            (_xlsx_bytes(unsafe_path=True), "unsafe.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "document_intake_unsafe_workbook_package"),
            (_xlsx_bytes(external_link=True), "external.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "document_intake_unsafe_workbook_package"),
            (_xlsx_bytes(bomb=True), "bomb.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "document_intake_workbook_package_too_large"),
            (_xlsx_bytes(), "unsupported.ods", "application/vnd.oasis.opendocument.spreadsheet", "document_intake_file_type_not_allowed"),
        )
        for data, filename, content_type, error in cases:
            with self.subTest(filename=filename):
                with self.assertRaisesRegex(ValueError, error):
                    validate_document_file(data, filename, content_type)

    def test_existing_supported_formats_remain_accepted(self):
        cases = (
            (PDF_BYTES, "document.pdf", "application/pdf", "pdf"),
            (JPEG_BYTES, "image.jpg", "image/jpeg", "jpeg"),
            (PNG_BYTES, "image.png", "image/png", "png"),
            (M4A_BYTES, "audio.m4a", "audio/mp4", "m4a"),
            (MP3_BYTES, "audio.mp3", "audio/mpeg", "mp3"),
            (WAV_BYTES, "audio.wav", "audio/wav", "wav"),
        )
        for data, filename, content_type, expected in cases:
            with self.subTest(filename=filename):
                detected, _media, _filename = validate_document_file(data, filename, content_type)
                self.assertEqual(detected, expected)

    def test_admin_upload_form_lists_spreadsheet_formats(self):
        content = admin_session.admin_document_intake_page(self.request).content
        self.assertIn(".xls", content)
        self.assertIn(".xlsx", content)
        self.assertIn("Excel 97-2003 Workbook (.xls)", content)
        self.assertIn("Excel Workbook (.xlsx)", content)


if __name__ == "__main__":
    unittest.main()
