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
    preserve_apple_emlx_attachments,
)
from api.email_documents import extract_apple_emlx_attachment_payloads
from scripts.backfill_email_attachment_preservation import run as run_backfill
from tests.test_admin_session import FakeRequest, install_fastapi_stubs
from tests.test_apple_emlx_support import MULTIPART_MESSAGE, emlx, xml_plist

install_fastapi_stubs()

from api.routes import admin_session  # noqa: E402


# A multi-attachment RFC 5322 message: one normal PDF attachment, one embedded
# message/rfc822 attachment, and one zero-byte attachment. Used to exercise the
# full Stage 52 policy surface (preserve, opaque-embedded, failed-zero-byte).
STAGE52_MESSAGE = b"""From: Stage 52 Sender <sender@example.test>
To: Recipient <recipient@example.test>
Subject: Stage 52 Apple Mail attachments
Date: Thu, 6 Aug 2026 10:00:00 +0000
Message-ID: <stage52-apple@example.test>
MIME-Version: 1.0
Content-Type: multipart/mixed; boundary="MIX"

--MIX
Content-Type: text/plain; charset=utf-8

Stage 52 Apple Mail body.
--MIX
Content-Type: application/pdf
Content-Disposition: attachment; filename="handbook.pdf"
Content-ID: <handbook>
Content-Transfer-Encoding: base64

JVBERi0xLjQKc3RhZ2U1Mgo=
--MIX
Content-Type: message/rfc822
Content-Disposition: attachment; filename="forwarded.eml"

From: Inner <inner@example.test>
To: Recipient <recipient@example.test>
Subject: Inner message
Message-ID: <inner@example.test>

Inner body.
--MIX
Content-Type: application/octet-stream
Content-Disposition: attachment
Content-Transfer-Encoding: base64


--MIX--
"""


def _build_stage52_emlx(*, trailing: bytes | None = None) -> bytes:
    """Wrap the Stage 52 multi-attachment message in an .emlx envelope."""

    return emlx(STAGE52_MESSAGE, trailing=trailing if trailing is not None else xml_plist())


class Stage52AppleEmlxAttachmentPreservationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "pending"
        self.environment = patch.dict(
            os.environ,
            {
                "CDE_DOCUMENT_INTAKE_ROOT": str(self.root),
                "ADMIN_USERNAME": "stage52-admin",
                "ADMIN_PASSWORD": "password",
                "CDE_ADMIN_SESSION_SECRET": "stage52-secret",
            },
            clear=False,
        )
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        self.temporary.cleanup()

    def _store(self, data: bytes | None = None, *, title: str = "Stage 52 source emlx"):
        return store_pending_document(
            data=data or _build_stage52_emlx(),
            original_filename="stage52-source.emlx",
            content_type="application/octet-stream",
            title=title,
            institution_source="Civic Evidence Office",
            document_date="2026-08-06",
            category="Email Correspondence",
            description="A preserved standalone Apple Mail message.",
            visibility="private",
            notes="Governed Stage 52 intake.",
            actor="stage52-admin",
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
                actor="stage52-admin",
                changed_at=timestamp,
                root=self.root,
            )
        return item

    def _admin_session_request(self):
        return FakeRequest(
            cookies={
                admin_session.SESSION_COOKIE_NAME: admin_session.create_admin_session(
                    "stage52-admin"
                )
            }
        )

    def test_extractor_recovers_rfc5322_bytes_and_reuses_existing_extractor(self):
        payloads = extract_apple_emlx_attachment_payloads(_build_stage52_emlx())
        # Three source-reported occurrences: PDF, embedded message, zero-byte.
        self.assertEqual([item["attachment_index"] for item in payloads], [1, 2, 3])
        self.assertEqual(payloads[0]["original_filename"], "handbook.pdf")
        self.assertEqual(payloads[0]["mime_type"], "application/pdf")
        self.assertEqual(payloads[0]["content_id"], "<handbook>")
        self.assertFalse(payloads[0]["inline_status"])
        self.assertEqual(payloads[0]["payload"], b"%PDF-1.4\nstage52\n")
        self.assertTrue(payloads[1]["is_attached_message"])
        self.assertIn(b"Subject: Inner message", payloads[1]["payload"])
        # The zero-byte attachment is surfaced as an empty payload occurrence.
        self.assertEqual(payloads[2]["payload"], b"")

    def test_extractor_preserves_apple_metadata_validation_and_plist_trailing(self):
        # The existing single-attachment fixture (with plist trailer) yields one
        # attachment, proving the wrapper + trailing-plist handling is intact.
        payloads = extract_apple_emlx_attachment_payloads(emlx(MULTIPART_MESSAGE, xml_plist()))
        self.assertEqual(len(payloads), 1)
        self.assertEqual(payloads[0]["original_filename"], "../../apple-unsafe.pdf")

    def test_intake_preserves_independent_pending_documents_and_relationships(self):
        source = self._store()
        relationships = list_source_attachments(source["intake_id"], root=self.root)
        # Two preserved (PDF + embedded) + one failed (zero-byte).
        self.assertEqual(len(relationships), 3)
        self.assertEqual(
            {item["relationship_type"] for item in relationships},
            {"Email attachment"},
        )
        self.assertTrue(
            all(item["source_pathway"] == "apple_emlx" for item in relationships)
        )
        self.assertEqual(
            [item["attachment_index"] for item in relationships], [1, 2, 3]
        )

        pdf = next(r for r in relationships if r["attachment_index"] == 1)
        attachment = pdf["attachment_document"]
        self.assertEqual(attachment["status"], "pending")
        self.assertEqual(attachment["document_type"], "email_attachment")
        expected = b"%PDF-1.4\nstage52\n"
        self.assertEqual(attachment["sha256_hash"], hashlib.sha256(expected).hexdigest())
        self.assertEqual(attachment["sha512_hash"], hashlib.sha512(expected).hexdigest())
        self.assertNotIn("canonical_record_reference", attachment)
        file_path, _ = intake_document_file(attachment["intake_id"], root=self.root)
        self.assertEqual(file_path.read_bytes(), expected)

        refreshed_source = load_pending_document(source["intake_id"], root=self.root)
        summary = refreshed_source.get("email_attachment_preservation") or []
        self.assertEqual(len(summary), 3)

    def test_zero_byte_occurrence_records_failed_row_without_document(self):
        source = self._store()
        relationships = list_source_attachments(source["intake_id"], root=self.root)
        failed = next(
            item for item in relationships if item["extraction_status"] == "failed"
        )
        self.assertEqual(failed["attachment_index"], 3)
        self.assertIsNone(failed["attachment_document_id"])
        self.assertEqual(failed["extraction_failure_reason"], "email_attachment_empty_payload")
        self.assertEqual(failed["source_pathway"], "apple_emlx")

    def test_embedded_message_is_preserved_opaquely_without_recursion(self):
        source = self._store()
        relationships = list_source_attachments(source["intake_id"], root=self.root)
        embedded = next(r for r in relationships if r["attachment_index"] == 2)
        attachment = embedded["attachment_document"]
        file_path, _ = intake_document_file(attachment["intake_id"], root=self.root)
        # The embedded message bytes are preserved verbatim; Stage 52 does not
        # recurse into any nested attachments.
        self.assertIn(b"Subject: Inner message", file_path.read_bytes())
        inverse = list_attachment_sources(attachment["intake_id"], root=self.root)
        self.assertEqual(len(inverse), 1)

    def test_reprocessing_is_idempotent_without_duplicate_documents_or_rows(self):
        source = self._store()
        before = list_source_attachments(source["intake_id"], root=self.root)
        file_path, _ = intake_document_file(source["intake_id"], root=self.root)
        retry = preserve_apple_emlx_attachments(source, file_path.read_bytes(), root=self.root)
        after = list_source_attachments(source["intake_id"], root=self.root)
        self.assertEqual(
            [r["relationship_id"] for r in retry],
            [r["relationship_id"] for r in before],
        )
        self.assertEqual(
            [r["relationship_id"] for r in after],
            [r["relationship_id"] for r in before],
        )
        self.assertEqual(
            [r["attachment_document_id"] for r in after],
            [r["attachment_document_id"] for r in before],
        )

    def test_stage50_admin_section_lights_up_for_emlx_source(self):
        source = self._store()
        request = self._admin_session_request()
        preview = admin_session.admin_document_intake_preview_page(
            source["intake_id"], request
        ).content
        self.assertIn("Governed Email Attachment Relationships", preview)
        self.assertIn("Open Published Document", preview)
        relationships = list_source_attachments(source["intake_id"], root=self.root)
        pdf = next(r for r in relationships if r["attachment_index"] == 1)
        attachment = pdf["attachment_document"]
        self.assertIn(attachment["document_identifier"], preview)
        self.assertIn(f"/admin/document-intake/{attachment['intake_id']}", preview)

    def test_preservation_metadata_excludes_email_body_and_raw_submitted_text(self):
        source = self._store()
        relationships = list_source_attachments(source["intake_id"], root=self.root)
        for relationship in relationships:
            metadata = relationship.get("source_metadata") or {}
            serialised = json.dumps(metadata, sort_keys=True)
            self.assertNotIn("Stage 52 Apple Mail body", serialised)
            self.assertNotIn("plain_text_body", serialised)
            self.assertNotIn("sanitized_html_body", serialised)

    def test_backfill_default_dry_run_is_write_free_and_includes_emlx(self):
        # Model a pre-Stage-52 .emlx intake with preservation disabled.
        with patch(
            "api.email_attachment_preservation.preserve_apple_emlx_attachments",
            return_value=[],
        ):
            source = self._store()
        registry_path = self.root / REGISTRY_FILENAME
        self.assertFalse(registry_path.exists())
        dirs_before = {p.name for p in self.root.iterdir() if p.is_dir()}
        metadata_before = (self.root / source["intake_id"] / "metadata.json").read_text()

        dry_run = run_backfill(root=self.root, limit=10, dry_run=True)
        self.assertEqual(dry_run["processed"], 1)
        self.assertEqual(dry_run["created"], 3)
        self.assertFalse(registry_path.exists())
        self.assertEqual(dirs_before, {p.name for p in self.root.iterdir() if p.is_dir()})
        self.assertEqual(
            metadata_before, (self.root / source["intake_id"] / "metadata.json").read_text()
        )

    def test_targeted_intake_id_dry_run_is_write_free(self):
        with patch(
            "api.email_attachment_preservation.preserve_apple_emlx_attachments",
            return_value=[],
        ):
            source = self._store()
        registry_path = self.root / REGISTRY_FILENAME
        dirs_before = {p.name for p in self.root.iterdir() if p.is_dir()}
        metadata_before = (self.root / source["intake_id"] / "metadata.json").read_text()

        dry_run = run_backfill(
            root=self.root, limit=10, dry_run=True, intake_id=source["intake_id"]
        )
        self.assertEqual(dry_run["processed"], 1)
        self.assertEqual(dry_run["created"], 3)
        self.assertFalse(registry_path.exists())
        self.assertEqual(dirs_before, {p.name for p in self.root.iterdir() if p.is_dir()})
        self.assertEqual(
            metadata_before, (self.root / source["intake_id"] / "metadata.json").read_text()
        )

    def test_targeted_first_run_creates_only_target_then_second_run_idempotent(self):
        with patch(
            "api.email_attachment_preservation.preserve_apple_emlx_attachments",
            return_value=[],
        ):
            source = self._store()

        first = run_backfill(
            root=self.root, limit=10, dry_run=False, intake_id=source["intake_id"]
        )
        self.assertEqual(first["processed"], 1)
        self.assertEqual(first["created"], 2)  # PDF + embedded; zero-byte is failed
        self.assertEqual(first["linked"], 3)
        relationships = list_source_attachments(source["intake_id"], root=self.root)
        self.assertEqual(len(relationships), 3)

        second = run_backfill(
            root=self.root, limit=10, dry_run=False, intake_id=source["intake_id"]
        )
        self.assertEqual(second["created"], 0)
        self.assertEqual(second["already_present"], 3)
        relationships_after = list_source_attachments(source["intake_id"], root=self.root)
        self.assertEqual(
            [r["relationship_id"] for r in relationships_after],
            [r["relationship_id"] for r in relationships],
        )

    def test_targeted_run_does_not_process_unrelated_candidates(self):
        with patch(
            "api.email_attachment_preservation.preserve_apple_emlx_attachments",
            return_value=[],
        ):
            target = self._store(title="Target emlx")
        # A second emlx candidate that must NOT be touched. Distinct bytes
        # (different Message-ID) so it gets a distinct intake_id.
        other_message = STAGE52_MESSAGE.replace(
            b"<stage52-apple@example.test>", b"<stage52-other@example.test>"
        )
        with patch(
            "api.email_attachment_preservation.preserve_apple_emlx_attachments",
            return_value=[],
        ):
            other = self._store(data=emlx(other_message, xml_plist()), title="Untouched emlx")
        self.assertNotEqual(other["intake_id"], target["intake_id"])

        result = run_backfill(
            root=self.root, limit=10, dry_run=True, intake_id=target["intake_id"]
        )
        self.assertEqual(result["processed"], 1)
        # The other candidate has no relationship rows.
        self.assertEqual(len(list_source_attachments(other["intake_id"], root=self.root)), 0)


if __name__ == "__main__":
    unittest.main()
