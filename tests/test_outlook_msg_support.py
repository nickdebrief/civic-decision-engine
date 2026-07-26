import hashlib
import os
import struct
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from api.document_intake import (
    build_document_search_text,
    document_media_type,
    intake_document_file,
    is_email_document,
    list_published_documents,
    store_pending_document,
    update_intake_status,
    validate_document_file,
)
from api.email_documents import parse_outlook_msg_metadata
from tests.test_admin_session import FakeRequest, install_fastapi_stubs

install_fastapi_stubs()

from api.public_document_preview import render_public_document_preview
from api.routes import admin_session, archive, documents


CFB_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
ENDOFCHAIN = 0xFFFFFFFE
FREESECT = 0xFFFFFFFF
FATSECT = 0xFFFFFFFD
SECTOR_SIZE = 512


def _utf16(value: str) -> bytes:
    return value.encode("utf-16-le") + b"\x00\x00"


def _int32(value: int) -> bytes:
    return struct.pack("<i", value)


def _filetime(value: str) -> bytes:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    epoch = datetime(1601, 1, 1, tzinfo=timezone.utc)
    return struct.pack("<Q", int((dt - epoch).total_seconds() * 10_000_000))


def _dir_entry(
    name: str,
    object_type: int,
    *,
    left: int = FREESECT,
    right: int = FREESECT,
    child: int = FREESECT,
    start_sector: int = ENDOFCHAIN,
    stream_size: int = 0,
) -> bytes:
    raw = bytearray(128)
    encoded_name = name.encode("utf-16-le") + b"\x00\x00"
    raw[: min(len(encoded_name), 64)] = encoded_name[:64]
    struct.pack_into("<H", raw, 64, min(len(encoded_name), 64))
    raw[66] = object_type
    raw[67] = 1
    struct.pack_into("<III", raw, 68, left, right, child)
    struct.pack_into("<I", raw, 116, start_sector)
    struct.pack_into("<Q", raw, 120, stream_size)
    return bytes(raw)


def _chain_siblings(indexes: list[int], entries: list[dict]) -> int:
    if not indexes:
        return FREESECT
    for current, next_index in zip(indexes, indexes[1:]):
        entries[current]["right"] = next_index
    return indexes[0]


def build_msg_file(
    *,
    subject: str = "Outlook governed message",
    plain_body: str = "Plain Outlook body for search.",
    html_body: str = '<html><body><p onclick="bad()">HTML Outlook body</p><script>alert(1)</script><img src="https://tracker.example/pixel.png"><a href="javascript:alert(1)">bad</a></body></html>',
    sender_name: str = "Outlook Sender",
    sender_email: str = "sender@example.test",
    sender_smtp: str = "sender.smtp@example.test",
    sent_rep_name: str = "Representative Sender",
    sent_rep_email: str = "rep@example.test",
    to_name: str = "Outlook Recipient",
    to_email: str = "recipient@example.test",
    cc_name: str = "Copy Recipient",
    cc_email: str = "copy@example.test",
    bcc_email: str = "hidden@example.test",
    attachment_filename: str = "../../unsafe-name.pdf",
    embedded_attachment: bool = True,
    include_msg_properties: bool = True,
) -> bytes:
    root_streams: dict[str, bytes] = {}
    if include_msg_properties:
        root_streams.update(
            {
                "__properties_version1.0": b"\x00" * 32,
                "__substg1.0_001A001F": _utf16("IPM.Note"),
                "__substg1.0_0037001F": _utf16(subject),
                "__substg1.0_0C1A001F": _utf16(sender_name),
                "__substg1.0_0C1F001F": _utf16(sender_email),
                "__substg1.0_5D01001F": _utf16(sender_smtp),
                "__substg1.0_0042001F": _utf16(sent_rep_name),
                "__substg1.0_0065001F": _utf16(sent_rep_email),
                "__substg1.0_1035001F": _utf16("<outlook-message-001@example.test>"),
                "__substg1.0_1042001F": _utf16("<previous-outlook@example.test>"),
                "__substg1.0_1039001F": _utf16("<root-outlook@example.test> <previous-outlook@example.test>"),
                "__substg1.0_0070001F": _utf16("Outlook Conversation Topic"),
                "__substg1.0_00390040": _filetime("2026-07-22T10:00:00Z"),
                "__substg1.0_0E060040": _filetime("2026-07-22T10:05:00Z"),
                "__substg1.0_30070040": _filetime("2026-07-22T09:55:00Z"),
                "__substg1.0_30080040": _filetime("2026-07-22T10:10:00Z"),
                "__substg1.0_1000001F": _utf16(plain_body),
                "__substg1.0_10130102": html_body.encode("utf-8"),
                "__substg1.0_10090102": b"{\\rtf1 compressed-placeholder}",
            }
        )
    storages = {
        "__recip_version1.0_#00000000": {
            "__substg1.0_3001001F": _utf16(to_name),
            "__substg1.0_3003001F": _utf16(to_email),
            "__substg1.0_39FE001F": _utf16(to_email),
            "__substg1.0_0C150003": _int32(1),
        },
        "__recip_version1.0_#00000001": {
            "__substg1.0_3001001F": _utf16(cc_name),
            "__substg1.0_3003001F": _utf16(cc_email),
            "__substg1.0_0C150003": _int32(2),
        },
        "__recip_version1.0_#00000002": {
            "__substg1.0_3001001F": _utf16("Hidden Recipient"),
            "__substg1.0_3003001F": _utf16(bcc_email),
            "__substg1.0_0C150003": _int32(3),
        },
        "__attach_version1.0_#00000000": {
            "__substg1.0_3704001F": _utf16("short.pdf"),
            "__substg1.0_3707001F": _utf16(attachment_filename),
            "__substg1.0_370E001F": _utf16("application/pdf"),
            "__substg1.0_3712001F": _utf16("<attachment-1>"),
            "__substg1.0_37050003": _int32(1),
            "__substg1.0_37010102": b"%PDF attachment bytes",
        },
    }
    if embedded_attachment:
        storages["__attach_version1.0_#00000001"] = {
            "__substg1.0_3704001F": _utf16("embedded-message.msg"),
            "__substg1.0_370E001F": _utf16("application/vnd.ms-outlook"),
            "__substg1.0_37050003": _int32(5),
            "__substg1.0_37010102": b"embedded msg bytes",
        }
    return build_cfb(root_streams, storages)


def build_cfb(root_streams: dict[str, bytes], storages: dict[str, dict[str, bytes]] | None = None) -> bytes:
    storages = storages or {}
    entries: list[dict] = [
        {"name": "Root Entry", "type": 5, "child": FREESECT, "left": FREESECT, "right": FREESECT, "start": ENDOFCHAIN, "size": 0}
    ]
    stream_payloads: list[tuple[int, bytes]] = []

    def add_stream(name: str, payload: bytes) -> int:
        index = len(entries)
        entries.append({"name": name, "type": 2, "child": FREESECT, "left": FREESECT, "right": FREESECT, "start": ENDOFCHAIN, "size": len(payload)})
        stream_payloads.append((index, payload))
        return index

    root_children = [add_stream(name, payload) for name, payload in root_streams.items()]
    for storage_name, storage_streams in storages.items():
        storage_index = len(entries)
        entries.append({"name": storage_name, "type": 1, "child": FREESECT, "left": FREESECT, "right": FREESECT, "start": ENDOFCHAIN, "size": 0})
        child_indexes = [add_stream(name, payload) for name, payload in storage_streams.items()]
        entries[storage_index]["child"] = _chain_siblings(child_indexes, entries)
        root_children.append(storage_index)
    entries[0]["child"] = _chain_siblings(root_children, entries)

    sectors: list[bytes] = []
    fat: list[int] = []
    for entry_index, payload in stream_payloads:
        padded = payload + b"\x00" * ((SECTOR_SIZE - len(payload) % SECTOR_SIZE) % SECTOR_SIZE)
        sector_ids = []
        for offset in range(0, len(padded) or SECTOR_SIZE, SECTOR_SIZE):
            sector_ids.append(len(sectors))
            sectors.append(padded[offset : offset + SECTOR_SIZE].ljust(SECTOR_SIZE, b"\x00"))
            fat.append(ENDOFCHAIN)
        for current, next_sector in zip(sector_ids, sector_ids[1:]):
            fat[current] = next_sector
        entries[entry_index]["start"] = sector_ids[0]

    directory_bytes = b"".join(
        _dir_entry(
            entry["name"],
            entry["type"],
            left=entry["left"],
            right=entry["right"],
            child=entry["child"],
            start_sector=entry["start"],
            stream_size=entry["size"],
        )
        for entry in entries
    )
    directory_bytes = directory_bytes + b"\x00" * ((SECTOR_SIZE - len(directory_bytes) % SECTOR_SIZE) % SECTOR_SIZE)
    directory_start = len(sectors)
    directory_sector_ids = []
    for offset in range(0, len(directory_bytes), SECTOR_SIZE):
        directory_sector_ids.append(len(sectors))
        sectors.append(directory_bytes[offset : offset + SECTOR_SIZE])
        fat.append(ENDOFCHAIN)
    for current, next_sector in zip(directory_sector_ids, directory_sector_ids[1:]):
        fat[current] = next_sector

    fat_sector = len(sectors)
    fat.append(FATSECT)
    fat_bytes = b"".join(struct.pack("<I", value) for value in fat)
    fat_bytes = fat_bytes.ljust(SECTOR_SIZE, b"\xff")
    sectors.append(fat_bytes[:SECTOR_SIZE])

    header = bytearray(512)
    header[:8] = CFB_SIGNATURE
    header[24:26] = b"\x3e\x00"
    header[26:28] = b"\x03\x00"
    header[28:30] = b"\xfe\xff"
    struct.pack_into("<H", header, 30, 9)
    struct.pack_into("<H", header, 32, 6)
    struct.pack_into("<I", header, 44, 1)
    struct.pack_into("<I", header, 48, directory_start)
    struct.pack_into("<I", header, 56, 4096)
    struct.pack_into("<I", header, 60, ENDOFCHAIN)
    struct.pack_into("<I", header, 68, ENDOFCHAIN)
    for offset in range(76, 512, 4):
        struct.pack_into("<I", header, offset, FREESECT)
    struct.pack_into("<I", header, 76, fat_sector)
    return bytes(header) + b"".join(sectors)


class OutlookMessageSupportTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "pending"
        self.env = patch.dict(
            os.environ,
            {
                "ADMIN_USERNAME": "msg-admin",
                "ADMIN_PASSWORD": "admin-password",
                "CDE_ADMIN_SESSION_SECRET": "session-secret",
                "CDE_DOCUMENT_INTAKE_ROOT": str(self.root),
            },
            clear=False,
        )
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp_dir.cleanup()

    def _store(self, data: bytes, **overrides):
        values = {
            "original_filename": "governed-outlook-message.msg",
            "content_type": "application/vnd.ms-outlook",
            "title": "Governed Outlook Message",
            "institution_source": "Outlook Source",
            "document_date": "2026-07-22",
            "category": "Email Correspondence",
            "description": "Native Microsoft Outlook message preserved as a governed document.",
            "visibility": "private",
            "notes": "Private Outlook message intake note.",
            "reference_identifier": "MSG-REF-001",
            "keywords": "outlook, msg, correspondence",
            "actor": "msg-admin",
            "uploaded_at": "2026-07-22T10:00:00Z",
            "root": self.root,
        }
        values.update(overrides)
        return store_pending_document(data=data, **values)

    def _publish(self, item):
        for status, timestamp in (
            ("under_review", "2026-07-22T11:00:00Z"),
            ("approved", "2026-07-22T12:00:00Z"),
            ("published", "2026-07-22T13:00:00Z"),
        ):
            item = update_intake_status(
                item["intake_id"],
                status,
                actor="msg-admin",
                note=f"{status} note",
                changed_at=timestamp,
                root=self.root,
            )
        return item

    def test_valid_msg_upload_preserves_original_bytes_and_extracts_mapi_projection(self):
        for content_type in ("application/vnd.ms-outlook", "application/x-msg", "application/msoutlook"):
            with self.subTest(content_type=content_type):
                data = build_msg_file(subject=f"Outlook subject {content_type}")
                item = self._store(data, content_type=content_type)
                digest = hashlib.sha256(data).hexdigest()

                self.assertEqual(item["document_type"], "msg")
                self.assertEqual(item["document_format"], "Microsoft Outlook Message")
                self.assertEqual(item["content_type"], "application/vnd.ms-outlook")
                self.assertEqual(item["media_family"], "email")
                self.assertEqual(item["sha256_hash"], digest)
                self.assertTrue(is_email_document(item))
                self.assertEqual(document_media_type(item), "application/vnd.ms-outlook")
                self.assertEqual(item["email_metadata"]["source_format"], "outlook_msg")
                self.assertEqual(item["email_metadata"]["message_class"], "IPM.Note")
                self.assertIn("Outlook subject", item["email_metadata"]["subject_decoded"])
                self.assertEqual(item["email_metadata"]["sender_name"], "Outlook Sender")
                self.assertEqual(item["email_metadata"]["sent_representing_name"], "Representative Sender")
                self.assertIn("Outlook Recipient", item["email_metadata"]["to_raw"])
                self.assertIn("Copy Recipient", item["email_metadata"]["cc_raw"])
                self.assertIn("hidden@example.test", item["email_metadata"]["bcc_raw"])
                self.assertEqual(item["email_metadata"]["message_id"], "<outlook-message-001@example.test>")
                self.assertEqual(item["email_metadata"]["conversation_topic"], "Outlook Conversation Topic")
                self.assertEqual(item["email_metadata"]["attachment_count"], 2)
                self.assertEqual(item["email_metadata"]["embedded_message_count"], 1)
                self.assertTrue(item["email_metadata"]["rtf_body_present"])
                file_path, _metadata = intake_document_file(item["intake_id"], root=self.root)
                self.assertEqual(Path(file_path).read_bytes(), data)

    def test_msg_parser_sanitizes_html_and_lists_attachment_metadata_only(self):
        metadata = parse_outlook_msg_metadata(build_msg_file())
        self.assertIn("HTML Outlook body", metadata["body_search_text"])
        self.assertIn("remote image suppressed", metadata["body_search_text"])
        self.assertNotIn("<script", metadata["sanitized_html_body"].lower())
        self.assertNotIn("onclick", metadata["sanitized_html_body"].lower())
        self.assertNotIn("https://tracker.example", metadata["sanitized_html_body"])
        self.assertNotIn("javascript:", metadata["sanitized_html_body"].lower())
        attachment = metadata["attachments_metadata"][0]
        self.assertEqual(attachment["filename"], "../../unsafe-name.pdf")
        self.assertEqual(attachment["media_type"], "application/pdf")
        self.assertEqual(attachment["content_id"], "<attachment-1>")
        self.assertFalse(attachment["is_embedded_message"])
        self.assertTrue(metadata["attachments_metadata"][1]["is_embedded_message"])

    def test_msg_validation_rejects_masquerades_and_bounded_limit_excesses(self):
        data = build_msg_file()
        self.assertEqual(validate_document_file(data, "message.msg", "application/vnd.ms-outlook")[0], "msg")
        for payload, filename, error in (
            (b"", "empty.msg", "document_intake_file_required"),
            (b"not cfb", "plain.msg", "document_intake_file_type_not_allowed"),
            (build_cfb({}, {}), "generic.msg", "document_intake_file_type_not_allowed"),
            (b"%PDF-1.7\nrenamed\n%%EOF\n", "renamed.msg", "document_intake_file_type_mismatch"),
            (data, "wrong.pdf", "document_intake_file_type_mismatch"),
        ):
            with self.subTest(filename=filename):
                with self.assertRaisesRegex(ValueError, error):
                    validate_document_file(payload, filename, "application/vnd.ms-outlook")

        with patch("api.email_documents.MAX_MSG_STREAM_COUNT", 2):
            with self.assertRaisesRegex(ValueError, "document_intake_msg_stream_limit_exceeded"):
                validate_document_file(data, "too-many-streams.msg", "application/vnd.ms-outlook")
        with patch("api.email_documents.MAX_MSG_BODY_BYTES", 10):
            with self.assertRaisesRegex(ValueError, "document_intake_msg_body_too_large|document_intake_msg_property_too_large"):
                self._store(build_msg_file(plain_body="x" * 200), original_filename="too-large.msg")
        too_many_embedded = build_msg_file(embedded_attachment=True)
        with patch("api.email_documents.MAX_MSG_EMBEDDED_DEPTH", 0):
            with self.assertRaisesRegex(ValueError, "document_intake_msg_embedded_message_too_deep"):
                validate_document_file(too_many_embedded, "embedded.msg", "application/vnd.ms-outlook")

    def test_published_msg_public_page_preview_search_archive_and_download(self):
        data = build_msg_file()
        item = self._publish(self._store(data))
        page = documents.public_document_page(item["intake_id"]).content

        self.assertIn("Email Overview", page)
        self.assertIn("Parsed Outlook metadata reflects fields contained", page)
        self.assertIn("Sent on behalf of", page)
        self.assertIn("Message sent time recorded in source", page)
        self.assertIn("Delivery time recorded in source", page)
        self.assertIn("Outlook Conversation Topic", page)
        self.assertIn("An Outlook RTF body is present", page)
        self.assertIn("../../unsafe-name.pdf", page)
        self.assertIn("embedded-message.msg", page)
        self.assertIn("Download original .msg", page)
        self.assertIn("<td>Microsoft Outlook Message</td>", page)
        self.assertIn("<td>Email</td>", page)

        search_text = build_document_search_text(item)
        self.assertIn("outlook sender", search_text)
        self.assertIn("representative sender", search_text)
        self.assertIn("recipient@example.test", search_text)
        self.assertIn("outlook-message-001@example.test", search_text)
        self.assertIn("outlook conversation topic", search_text)
        self.assertIn("plain outlook body", search_text)
        self.assertIn("unsafe-name.pdf", search_text)
        self.assertNotIn("hidden@example.test", search_text)
        self.assertEqual(
            [document["intake_id"] for document in list_published_documents(query="outlook-message-001", root=self.root)],
            [item["intake_id"]],
        )

        library = documents.public_document_library(q="Outlook Conversation Topic").content
        self.assertIn("1 published document.", library)
        self.assertIn("Outlook Message", library)
        self.assertIn("Open Outlook Message", library)
        archive_page = archive.public_archive_explorer(media="email").content
        self.assertIn("Governed Outlook Message", archive_page)
        preview = render_public_document_preview(item, root=self.root)
        self.assertIn("Outlook Message", preview)
        self.assertIn("Open Outlook Message", preview)

        response = documents.public_document_download(item["intake_id"])
        self.assertEqual(response.media_type, "application/vnd.ms-outlook")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertIn("attachment", response.headers["Content-Disposition"])
        self.assertEqual(Path(response.path).read_bytes(), data)

    def test_pending_msg_private_admin_form_and_review_boundary(self):
        item = self._store(build_msg_file())
        with self.assertRaises(Exception):
            documents.public_document_page(item["intake_id"])

        request = FakeRequest(
            cookies={
                admin_session.SESSION_COOKIE_NAME: admin_session.create_admin_session("msg-admin")
            }
        )
        admin_page = admin_session.admin_document_intake_page(request).content
        self.assertIn("Microsoft Outlook Message (.msg)", admin_page)
        review_page = admin_session.admin_document_intake_preview_page(item["intake_id"], request).content
        self.assertIn("MAPI properties", review_page)
        self.assertIn("Microsoft Outlook Message", review_page)


if __name__ == "__main__":
    unittest.main()
