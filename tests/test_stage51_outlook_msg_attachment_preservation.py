from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from api.document_intake import (
    intake_document_file,
    load_pending_document,
    store_pending_document,
    update_intake_status,
)
from api.email_attachment_preservation import (
    REGISTRY_FILENAME,
    list_attachment_sources,
    list_source_attachments,
    preserve_outlook_msg_attachments,
)
from api.email_documents import extract_outlook_msg_attachment_payloads
from tests.test_admin_session import FakeRequest, install_fastapi_stubs
from tests.test_outlook_msg_support import (
    _int32,
    _utf16,
    build_cfb,
)

install_fastapi_stubs()

from api.routes import admin_session  # noqa: E402


def _build_stage51_msg(
    *,
    attachment_bytes: bytes = b"%PDF-1.4 stage51\n",
    attachment_filename: str = "Civic_Decision_Engine_User_Handbook_v2.0.pdf",
    attachment_mime: str = "application/pdf",
    embedded_bytes: bytes | None = b"opaque embedded msg bytes",
    zero_byte_attachment: bool = False,
) -> bytes:
    """Build a bounded synthetic standalone .msg with governed attachment groups.

    Reuses the CFB construction helpers from ``tests.test_outlook_msg_support``
    so the fixture exercises the real Stage 35B compound-file parser. Group
    ordering follows the source order used by ``parse_outlook_msg_metadata``.
    """

    root_streams = {
        "__properties_version1.0": b"\x00" * 32,
        "__substg1.0_001A001F": _utf16("IPM.Note"),
        "__substg1.0_0037001F": _utf16("Stage 51 Outlook governed message"),
        "__substg1.0_0C1A001F": _utf16("Stage 51 Sender"),
        "__substg1.0_0C1F001F": _utf16("sender@example.test"),
        "__substg1.0_1035001F": _utf16("<stage51-msg@example.test>"),
        "__substg1.0_00390040": b"\x00" * 8,
        "__substg1.0_1000001F": _utf16("Stage 51 plain body."),
    }
    storages = {
        "__attach_version1.0_#00000000": {
            "__substg1.0_3704001F": _utf16("short.pdf"),
            "__substg1.0_3707001F": _utf16(attachment_filename),
            "__substg1.0_370E001F": _utf16(attachment_mime),
            "__substg1.0_3712001F": _utf16("<attachment-1>"),
            "__substg1.0_37050003": _int32(1),
            "__substg1.0_37010102": attachment_bytes,
        },
    }
    if embedded_bytes is not None:
        storages["__attach_version1.0_#00000001"] = {
            "__substg1.0_3704001F": _utf16("forwarded.msg"),
            "__substg1.0_3707001F": _utf16("forwarded.msg"),
            "__substg1.0_370E001F": _utf16("application/vnd.ms-outlook"),
            "__substg1.0_37050003": _int32(5),
            "__substg1.0_37010102": embedded_bytes,
        }
    if zero_byte_attachment:
        zero_key = "__attach_version1.0_#0000000%d" % (2 if embedded_bytes is not None else 1)
        storages[zero_key] = {
            "__substg1.0_3704001F": _utf16("empty.dat"),
            "__substg1.0_3707001F": _utf16("empty.dat"),
            "__substg1.0_370E001F": _utf16("application/octet-stream"),
            "__substg1.0_37050003": _int32(1),
            "__substg1.0_37010102": b"",
        }
    return build_cfb(root_streams, storages)


class Stage51OutlookMsgAttachmentPreservationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "pending"
        self.environment = patch.dict(
            os.environ,
            {
                "CDE_DOCUMENT_INTAKE_ROOT": str(self.root),
                "ADMIN_USERNAME": "stage51-admin",
                "ADMIN_PASSWORD": "password",
                "CDE_ADMIN_SESSION_SECRET": "stage51-secret",
            },
            clear=False,
        )
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        self.temporary.cleanup()

    def _store(self, data: bytes | None = None, *, title: str = "Stage 51 source msg"):
        return store_pending_document(
            data=data or _build_stage51_msg(),
            original_filename="stage51-source.msg",
            content_type="application/vnd.ms-outlook",
            title=title,
            institution_source="Civic Evidence Office",
            document_date="2026-08-06",
            category="Email Correspondence",
            description="A preserved standalone Outlook message.",
            visibility="private",
            notes="Governed Stage 51 intake.",
            actor="stage51-admin",
            uploaded_at="2026-08-06T10:00:00Z",
            root=self.root,
        )

    def _publish(self, item: dict):
        for status, timestamp in (
            ("under_review", "2026-08-06T11:00:00Z"),
            ("approved", "2026-08-06T12:00:00Z"),
            ("published", "2026-08-06T13:00:00Z"),
        ):
            item = update_intake_status(
                item["intake_id"],
                status,
                actor="stage51-admin",
                changed_at=timestamp,
                root=self.root,
            )
        return item

    def _admin_session_request(self):
        return FakeRequest(
            cookies={
                admin_session.SESSION_COOKIE_NAME: admin_session.create_admin_session(
                    "stage51-admin"
                )
            }
        )

    def test_extractor_returns_attachment_payloads_in_source_order(self):
        data = _build_stage51_msg()
        payloads = extract_outlook_msg_attachment_payloads(data)
        self.assertEqual([item["attachment_index"] for item in payloads], [1, 2])
        self.assertEqual(payloads[0]["payload"], b"%PDF-1.4 stage51\n")
        self.assertEqual(
            payloads[0]["original_filename"],
            "Civic_Decision_Engine_User_Handbook_v2.0.pdf",
        )
        self.assertEqual(payloads[0]["mime_type"], "application/pdf")
        self.assertEqual(payloads[0]["content_id"], "<attachment-1>")
        self.assertFalse(payloads[0]["inline_status"])
        # Embedded message is surfaced opaquely with its bytes; not expanded.
        self.assertTrue(payloads[1]["is_attached_message"])
        self.assertEqual(payloads[1]["payload"], b"opaque embedded msg bytes")

    def test_intake_preserves_independent_pending_documents_and_relationships(self):
        source = self._store()
        relationships = list_source_attachments(source["intake_id"], root=self.root)
        self.assertEqual(len(relationships), 2)
        self.assertEqual(
            [item["relationship_type"] for item in relationships],
            ["Email attachment", "Email attachment"],
        )
        self.assertEqual([item["attachment_index"] for item in relationships], [1, 2])
        self.assertTrue(
            all(item["source_pathway"] == "outlook_msg" for item in relationships)
        )

        first = relationships[0]
        attachment = first["attachment_document"]
        self.assertEqual(attachment["status"], "pending")
        self.assertEqual(attachment["document_type"], "email_attachment")
        expected = b"%PDF-1.4 stage51\n"
        self.assertEqual(attachment["sha256_hash"], hashlib.sha256(expected).hexdigest())
        self.assertEqual(attachment["sha512_hash"], hashlib.sha512(expected).hexdigest())
        self.assertNotIn("canonical_record_reference", attachment)
        file_path, _ = intake_document_file(attachment["intake_id"], root=self.root)
        self.assertEqual(file_path.read_bytes(), expected)

        # The source metadata carries the Stage 49/51 preservation summary.
        refreshed_source = load_pending_document(source["intake_id"], root=self.root)
        summary = refreshed_source.get("email_attachment_preservation") or []
        self.assertEqual(len(summary), 2)
        self.assertEqual({item["extraction_status"] for item in summary}, {"preserved"})

    def test_reprocessing_is_idempotent_without_duplicate_documents_or_rows(self):
        source = self._store()
        before = list_source_attachments(source["intake_id"], root=self.root)
        file_path, _ = intake_document_file(source["intake_id"], root=self.root)

        retry = preserve_outlook_msg_attachments(
            source, file_path.read_bytes(), root=self.root
        )
        after = list_source_attachments(source["intake_id"], root=self.root)

        self.assertEqual(
            [item["relationship_id"] for item in retry],
            [item["relationship_id"] for item in before],
        )
        self.assertEqual(
            [item["relationship_id"] for item in after],
            [item["relationship_id"] for item in before],
        )
        self.assertEqual(
            [item["attachment_document_id"] for item in after],
            [item["attachment_document_id"] for item in before],
        )

    def test_embedded_message_is_preserved_opaquely_without_recursion(self):
        source = self._store()
        relationships = list_source_attachments(source["intake_id"], root=self.root)
        embedded = next(
            item for item in relationships if item["attachment_index"] == 2
        )
        attachment = embedded["attachment_document"]
        file_path, _ = intake_document_file(attachment["intake_id"], root=self.root)
        # The embedded message bytes are preserved verbatim; Stage 51 does not
        # recurse into any nested attachments.
        self.assertEqual(file_path.read_bytes(), b"opaque embedded msg bytes")
        inverse = list_attachment_sources(attachment["intake_id"], root=self.root)
        self.assertEqual(len(inverse), 1)

    def test_zero_byte_occurrence_records_failed_row_without_document(self):
        data = _build_stage51_msg(
            embedded_bytes=None, zero_byte_attachment=True
        )
        source = self._store(data)
        relationships = list_source_attachments(source["intake_id"], root=self.root)
        # One preserved normal attachment, one failed zero-byte occurrence.
        self.assertEqual(len(relationships), 2)
        statuses = {item["extraction_status"] for item in relationships}
        self.assertEqual(statuses, {"preserved", "failed"})
        failed = next(
            item for item in relationships if item["extraction_status"] == "failed"
        )
        self.assertIsNone(failed["attachment_document_id"])
        self.assertEqual(failed["extraction_failure_reason"], "email_attachment_empty_payload")
        self.assertEqual(failed["source_pathway"], "outlook_msg")

    def test_failed_preservation_records_failure_without_false_document_link(self):
        with patch(
            "api.email_attachment_preservation.store_email_attachment_document",
            side_effect=ValueError("governed storage unavailable"),
        ):
            source = self._store()
        relationships = list_source_attachments(source["intake_id"], root=self.root)
        self.assertEqual(len(relationships), 2)
        self.assertTrue(all(item["extraction_status"] == "failed" for item in relationships))
        self.assertTrue(all(item["attachment_document_id"] is None for item in relationships))
        self.assertTrue(
            all("storage unavailable" in item["extraction_failure_reason"] for item in relationships)
        )

    def test_stage50_admin_section_lights_up_for_msg_source(self):
        source = self._store()
        request = self._admin_session_request()
        preview = admin_session.admin_document_intake_preview_page(
            source["intake_id"], request
        ).content
        # Stage 50 navigation lights up automatically once rows exist.
        self.assertIn("Governed Email Attachment Relationships", preview)
        self.assertIn("Open Published Document", preview)
        relationships = list_source_attachments(source["intake_id"], root=self.root)
        first = relationships[0]
        attachment = first["attachment_document"]
        self.assertIn(attachment["document_identifier"], preview)
        self.assertIn(f"/admin/document-intake/{attachment['intake_id']}", preview)

    def test_backfill_dry_run_is_write_free(self):
        # Model a pre-Stage-51 .msg intake: Stage 35B metadata present, no
        # Stage 49 state. This is constructed by ingesting with the preservation
        # entrypoint disabled (no relationship rows created at all), not by
        # deleting newly-created state.
        with patch(
            "api.email_attachment_preservation.preserve_outlook_msg_attachments",
            return_value=[],
        ):
            source = self._store()
        registry_path = self.root / REGISTRY_FILENAME
        self.assertFalse(registry_path.exists())
        intake_dirs_before = {p.name for p in self.root.iterdir() if p.is_dir()}
        metadata_before = (self.root / source["intake_id"] / "metadata.json").read_text()

        from scripts.backfill_email_attachment_preservation import run as run_backfill

        dry_run = run_backfill(root=self.root, limit=10, dry_run=True)
        self.assertEqual(dry_run["processed"], 1)
        self.assertEqual(dry_run["created"], 2)
        # Dry-run creates no registry, no intake directories, no document
        # identifiers, and mutates no source metadata.
        self.assertFalse(registry_path.exists())
        intake_dirs_after = {p.name for p in self.root.iterdir() if p.is_dir()}
        self.assertEqual(intake_dirs_before, intake_dirs_after)
        metadata_after = (self.root / source["intake_id"] / "metadata.json").read_text()
        self.assertEqual(metadata_before, metadata_after)

    def test_backfill_creates_missing_objects_then_is_idempotent(self):
        with patch(
            "api.email_attachment_preservation.preserve_outlook_msg_attachments",
            return_value=[],
        ):
            source = self._store()

        from scripts.backfill_email_attachment_preservation import run as run_backfill

        first = run_backfill(root=self.root, limit=10, dry_run=False)
        self.assertEqual(first["processed"], 1)
        self.assertEqual(first["created"], 2)
        self.assertEqual(first["linked"], 2)
        relationships = list_source_attachments(source["intake_id"], root=self.root)
        self.assertEqual(len(relationships), 2)

        second = run_backfill(root=self.root, limit=10, dry_run=False)
        self.assertEqual(second["created"], 0)
        self.assertEqual(second["already_present"], 2)
        relationships_after = list_source_attachments(source["intake_id"], root=self.root)
        self.assertEqual(
            [item["relationship_id"] for item in relationships_after],
            [item["relationship_id"] for item in relationships],
        )

    def test_preservation_metadata_excludes_email_body_and_raw_submitted_text(self):
        source = self._store()
        relationships = list_source_attachments(source["intake_id"], root=self.root)
        for relationship in relationships:
            metadata = relationship.get("source_metadata") or {}
            serialised = json.dumps(metadata, sort_keys=True)
            self.assertNotIn("Stage 51 plain body", serialised)
            self.assertNotIn("plain_text_body", serialised)
            self.assertNotIn("sanitized_html_body", serialised)


if __name__ == "__main__":
    unittest.main()
