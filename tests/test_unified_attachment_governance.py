from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from api.attachment_governance import (
    AttachmentGovernanceError,
    govern_attachment_bytes,
    list_attachments,
    load_attachment,
    mark_attachment_promoted,
)
from api.mailbox_relationship_graph import build_attachment_relationship_graph
from api.outlook_archive_promotion import OutlookArchivePromotionContext


ATTACHMENT_BYTES = b"Unified attachment evidence.\n"


def context(source: str, archive_id: str) -> OutlookArchivePromotionContext:
    folder_id = f"folder-{source}"
    thread_id = f"thread-{source}"
    message_id = f"message-{source}"
    return OutlookArchivePromotionContext(
        document={
            "intake_id": archive_id,
            "document_identifier": f"ARCHIVE-{source.upper()}",
            "title": f"{source} archive",
            "institution_source": "Civic Evidence Office",
            "status": "pending",
            "sha256_hash": hashlib.sha256(source.encode("utf-8")).hexdigest(),
            "uploaded_at": "2026-08-01T08:00:00Z",
        },
        projection={"projection_version": "projection-v1", "messages": []},
        folder={"folder_id": folder_id, "path": f"Mailbox/{source}"},
        message={
            "projection_id": message_id,
            "message_id": f"<{message_id}@example.test>",
            "subject": f"{source} attachment message",
            "sender": "sender@example.test",
            "recipients": ["recipient@example.test"],
            "folder_id": folder_id,
            "folder_path": f"Mailbox/{source}",
            "thread_id": thread_id,
            "provenance": {
                "parser_version": f"{source}-parser-1",
                "acquisition_timestamp": "2026-08-01T09:00:00Z",
            },
        },
        job={"job_id": f"job-{source}"},
    )


class UnifiedAttachmentGovernanceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def _govern(self, source: str, *, filename: str | None = None):
        archive_id = f"archive-{source}"
        return govern_attachment_bytes(
            context(source, archive_id),
            data=ATTACHMENT_BYTES,
            filename=filename or f"{source}-evidence.txt",
            mime_type="text/plain",
            source_attachment_id=f"source-{source}-1",
            acquisition_source=source,
            extracted_at="2026-08-01T10:00:00Z",
            root=self.root,
        )

    def test_identity_is_content_deterministic_across_outlook_gmail_and_imap(self):
        outlook = self._govern("outlook_archive")
        gmail = self._govern("gmail_takeout")
        imap = self._govern("imap_acquisition")

        expected_id = "ATT-" + hashlib.sha256(ATTACHMENT_BYTES).hexdigest()[:24].upper()
        self.assertEqual(
            {outlook["attachment_id"], gmail["attachment_id"], imap["attachment_id"]},
            {expected_id},
        )
        self.assertEqual(imap["occurrence_count"], 3)
        self.assertEqual(
            {item["acquisition_source"] for item in imap["provenance_records"]},
            {"outlook_archive", "gmail_takeout", "imap_acquisition"},
        )

        stored = list((self.root / ".governed_attachments").rglob("original.bin"))
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0].read_bytes(), ATTACHMENT_BYTES)

    def test_metadata_is_normalized_and_contains_both_hashes(self):
        attachment = self._govern("gmail_takeout", filename="Evidence.PDF")
        self.assertEqual(attachment["extension"], "pdf")
        self.assertEqual(attachment["mime_type"], "text/plain")
        self.assertEqual(attachment["file_size_bytes"], len(ATTACHMENT_BYTES))
        self.assertEqual(attachment["sha256_hash"], hashlib.sha256(ATTACHMENT_BYTES).hexdigest())
        self.assertEqual(attachment["sha512_hash"], hashlib.sha512(ATTACHMENT_BYTES).hexdigest())
        self.assertEqual(attachment["evidence_status"], "governed_private_evidence")
        self.assertEqual(attachment["acquisition_source"], "gmail_takeout")
        encoded = json.dumps(attachment)
        self.assertNotIn(ATTACHMENT_BYTES.decode("ascii").strip(), encoded)
        self.assertNotIn("original.bin", encoded)

    def test_duplicate_references_preserve_each_provenance_chain(self):
        first = self._govern("outlook_archive")
        self._govern("imap_acquisition")
        loaded = load_attachment(
            "archive-outlook_archive", first["attachment_id"], root=self.root
        )
        self.assertEqual(loaded["occurrence_count"], 2)
        self.assertEqual(len(loaded["duplicate_references"]), 1)
        duplicate = loaded["duplicate_references"][0]
        self.assertEqual(duplicate["archive_id"], "archive-imap_acquisition")
        self.assertEqual(duplicate["acquisition_source"], "imap_acquisition")

        with self.assertRaises(AttachmentGovernanceError) as error:
            govern_attachment_bytes(
                context("outlook_archive", "archive-outlook_archive"),
                data=ATTACHMENT_BYTES,
                filename="changed-name.txt",
                mime_type="text/plain",
                source_attachment_id="source-outlook_archive-1",
                acquisition_source="outlook_archive",
                extracted_at="2026-08-01T10:00:00Z",
                root=self.root,
            )
        self.assertEqual(error.exception.code, "attachment_occurrence_identity_collision")

    def test_promotion_history_and_linkage_are_shared_without_automatic_promotion(self):
        first = self._govern("gmail_takeout")
        self._govern("imap_acquisition")
        self.assertEqual(first["promotion_status"], "eligible")
        updated = mark_attachment_promoted(
            "archive-gmail_takeout",
            first["attachment_id"],
            canonical_record_reference="CR-2026-001",
            administrator="governance-admin",
            promoted_at="2026-08-01T12:00:00Z",
            root=self.root,
        )
        self.assertEqual(updated["promotion_status"], "promoted")
        self.assertEqual(updated["canonical_record_reference"], "CR-2026-001")
        self.assertEqual(len(updated["promotion_history"]), 1)
        from_imap = load_attachment(
            "archive-imap_acquisition", first["attachment_id"], root=self.root
        )
        self.assertEqual(from_imap["canonical_record_reference"], "CR-2026-001")

    def test_graph_uses_source_neutral_chain_and_canonical_link(self):
        attachment = self._govern("imap_acquisition")
        attachment = mark_attachment_promoted(
            "archive-imap_acquisition",
            attachment["attachment_id"],
            canonical_record_reference="CR-2026-002",
            administrator="governance-admin",
            promoted_at="2026-08-01T12:00:00Z",
            root=self.root,
        )
        message = context("imap_acquisition", "archive-imap_acquisition").message
        projection = {"messages": [message]}
        document = context("imap_acquisition", "archive-imap_acquisition").document
        graph = build_attachment_relationship_graph(document, projection, [attachment])
        node_types = {node["type"] for node in graph["nodes"]}
        relationships = {edge["relationship_type"] for edge in graph["edges"]}
        self.assertTrue(
            {"Intake Record", "Folder", "Thread", "Email", "Attachment", "Canonical Record"}
            .issubset(node_types)
        )
        self.assertTrue({"Contains", "Has Attachment", "Promoted To"}.issubset(relationships))
        attachment_node = next(node for node in graph["nodes"] if node["type"] == "Attachment")
        self.assertEqual(attachment_node["metadata"]["sha512_hash"], attachment["sha512_hash"])

    def test_archive_listing_is_private_metadata_only(self):
        attachment = self._govern("outlook_archive")
        listed = list_attachments("archive-outlook_archive", root=self.root)
        self.assertEqual([item["attachment_id"] for item in listed], [attachment["attachment_id"]])
        self.assertEqual(list_attachments("archive-gmail_takeout", root=self.root), [])


if __name__ == "__main__":
    unittest.main()
