from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from api.document_intake import store_pending_document
from api.email_attachment_preservation import (
    REGISTRY_FILENAME,
    list_archive_attachments,
)
from tests.test_admin_session import FakeRequest, install_fastapi_stubs
from tests.test_stage49_email_attachment_preservation import MULTI_ATTACHMENT_EML
from tests.test_stage51_outlook_msg_attachment_preservation import _build_stage51_msg
from tests.test_stage52_apple_emlx_attachment_preservation import _build_stage52_emlx
from tests.test_stage53_mbox_attachment_preservation import _build_stage53_mbox


install_fastapi_stubs()

from api.routes import admin_session  # noqa: E402


class Stage531MailboxAttachmentRelationshipNavigationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "pending"
        self.environment = patch.dict(
            os.environ,
            {
                "CDE_DOCUMENT_INTAKE_ROOT": str(self.root),
                "ADMIN_USERNAME": "stage53-1-admin",
                "ADMIN_PASSWORD": "password",
                "CDE_ADMIN_SESSION_SECRET": "stage53-1-secret",
            },
            clear=False,
        )
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        self.temporary.cleanup()

    def _request(self):
        return FakeRequest(
            cookies={
                admin_session.SESSION_COOKIE_NAME: admin_session.create_admin_session(
                    "stage53-1-admin"
                )
            }
        )

    @staticmethod
    def _message(message_index: int) -> dict:
        return {
            "message_index": message_index,
            "subject_decoded": f"Subject {message_index}",
            "sender_raw": f"sender{message_index}@example.test",
            "date_header_parsed": f"2026-08-{(message_index % 28) + 1:02d}T10:00:00Z",
            "attachment_count": 1,
            "message_id": f"<message-{message_index}@example.test>",
        }

    @classmethod
    def _item(cls, message_count: int = 3) -> dict:
        archive_id = "a" * 64
        return {
            "intake_id": archive_id,
            "document_type": "mbox",
            "email_metadata": {
                "messages": [cls._message(index) for index in range(1, message_count + 1)]
            },
        }

    @staticmethod
    def _relationship(
        message_index: int,
        attachment_index: int,
        *,
        ordinal: int | None = None,
        source_email_object_id: str | None = None,
        failed: bool = False,
    ) -> dict:
        archive_id = "a" * 64
        ordinal = ordinal if ordinal is not None else message_index * 100 + attachment_index
        document_id = None if failed else f"{ordinal:064x}"
        relationship = {
            "relationship_id": f"EAR-{ordinal:024d}",
            "source_email_object_id": source_email_object_id
            or f"{archive_id}:message:{message_index}",
            "relationship_type": "Email attachment",
            "attachment_index": attachment_index,
            "original_filename": f"attachment-{message_index}-{attachment_index}.pdf",
            "display_title": f"Attachment {attachment_index}",
            "attachment_document_id": document_id,
            "extraction_status": "failed" if failed else "preserved",
            "extraction_failure_reason": "synthetic failure" if failed else None,
        }
        if document_id:
            relationship["attachment_document"] = {
                "intake_id": document_id,
                "document_identifier": f"DOC-2026-{ordinal:06d}",
                "status": "pending",
            }
        return relationship

    @staticmethod
    def _identity_hydration(relationships, **_kwargs):
        return [dict(relationship) for relationship in relationships]

    def _render(self, item, relationships, *, page=1, page_size=25):
        with patch.object(
            admin_session,
            "hydrate_email_attachment_documents",
            side_effect=self._identity_hydration,
        ):
            return admin_session._render_admin_mailbox_attachment_relationship_navigation(
                item,
                relationships,
                attachment_page=page,
                attachment_page_size=page_size,
            )

    def _store(self, data: bytes, filename: str, content_type: str):
        return store_pending_document(
            data=data,
            original_filename=filename,
            content_type=content_type,
            title=f"Stage 53.1 {filename}",
            institution_source="Civic Evidence Office",
            document_date="2026-08-08",
            category="Email Correspondence",
            description="Synthetic governed email evidence.",
            visibility="private",
            notes="Stage 53.1 test.",
            actor="stage53-1-admin",
            uploaded_at="2026-08-08T10:00:00Z",
            root=self.root,
        )

    def test_groups_by_exact_source_identity_and_numeric_message_order(self):
        item = self._item(12)
        relationships = [
            self._relationship(10, 1),
            self._relationship(2, 1),
            self._relationship(1, 1),
        ]
        groups = admin_session._mailbox_attachment_relationship_groups(item, relationships)
        self.assertEqual([group["message_index"] for group in groups], [1, 2, 10])
        self.assertEqual(sum(len(group["relationships"]) for group in groups), 3)

    def test_attachment_order_is_numeric_then_relationship_id(self):
        item = self._item(1)
        relationships = [
            self._relationship(1, 10, ordinal=30),
            self._relationship(1, 2, ordinal=20),
            self._relationship(1, 2, ordinal=10),
        ]
        ordered = admin_session._mailbox_attachment_relationship_groups(item, relationships)[0][
            "relationships"
        ]
        self.assertEqual(
            [(row["attachment_index"], row["relationship_id"]) for row in ordered],
            [(2, "EAR-000000000000000000000010"), (2, "EAR-000000000000000000000020"), (10, "EAR-000000000000000000000030")],
        )

    def test_message_summary_counts_metadata_and_native_collapsed_disclosure(self):
        item = self._item(1)
        relationships = [self._relationship(1, 1), self._relationship(1, 2)]
        html = self._render(item, relationships)
        self.assertIn("2 attachment relationships across 1 message", html)
        self.assertIn("<details class=\"mailbox-attachment-group\">", html)
        self.assertNotIn("<details class=\"mailbox-attachment-group\" open", html)
        self.assertIn("Message 1", html)
        self.assertIn("Subject 1", html)
        self.assertIn("sender1@example.test", html)
        self.assertIn("2026-08-02T10:00:00Z", html)
        self.assertIn("Attachment relationships: 2", html)

    def test_stage50_row_fields_and_actions_remain_inside_message_group(self):
        item = self._item(1)
        relationship = self._relationship(1, 3, ordinal=103)
        html = self._render(item, [relationship])
        for expected in (
            "Original filename",
            "Relationship",
            "Published Document",
            "Lifecycle status",
            "Relationship ID",
            "Extraction status",
            "Attachment document ID",
            relationship["original_filename"],
            relationship["relationship_id"],
            relationship["attachment_document"]["document_identifier"],
            "Pending Intake",
            "Open Published Document",
            "Inspect metadata",
        ):
            self.assertIn(expected, html)

    def test_failed_relationship_remains_visible_without_false_document_link(self):
        relationship = self._relationship(1, 1, failed=True)
        html = self._render(self._item(1), [relationship])
        self.assertIn(relationship["relationship_id"], html)
        self.assertIn("failed", html)
        self.assertIn("No attachment Published Document", html)
        self.assertNotIn("Open Published Document", html)

    def test_malformed_unmatched_and_ambiguous_relationships_use_fallback(self):
        item = self._item(2)
        item["email_metadata"]["messages"].append(self._message(2))
        relationships = [
            self._relationship(1, 1, source_email_object_id="wrong:message:1"),
            self._relationship(2, 1),
            self._relationship(3, 1),
            self._relationship(1, 2, source_email_object_id=f"{'a' * 64}:message:0"),
        ]
        groups = admin_session._mailbox_attachment_relationship_groups(item, relationships)
        self.assertEqual(len(groups), 1)
        self.assertTrue(groups[0]["unresolved"])
        self.assertEqual(len(groups[0]["relationships"]), 4)
        html = self._render(item, relationships)
        self.assertIn("Unresolved message relationship", html)
        self.assertIn("Unresolved relationships:</strong> 4", html)
        for relationship in relationships:
            self.assertIn(relationship["relationship_id"], html)

    def test_default_pagination_uses_complete_message_groups(self):
        item = self._item(26)
        relationships = [
            self._relationship(message_index, attachment_index)
            for message_index in range(1, 27)
            for attachment_index in (1, 2)
        ]
        page_one = self._render(item, relationships)
        page_two = self._render(item, relationships, page=2)
        self.assertIn("Page 1 of 2", page_one)
        self.assertEqual(page_one.count('<details class="mailbox-attachment-group">'), 25)
        self.assertEqual(page_two.count('<details class="mailbox-attachment-group">'), 1)
        for attachment_index in (1, 2):
            self.assertIn(f"attachment-26-{attachment_index}.pdf", page_two)
            self.assertNotIn(f"attachment-26-{attachment_index}.pdf", page_one)

    def test_page_size_is_bounded_and_page_is_clamped(self):
        item = self._item(120)
        relationships = [self._relationship(index, 1) for index in range(1, 121)]
        bounded = self._render(item, relationships, page=1, page_size=500)
        clamped = self._render(item, relationships, page=999, page_size=25)
        self.assertIn("Page 1 of 2", bounded)
        self.assertEqual(bounded.count('<details class="mailbox-attachment-group">'), 100)
        self.assertIn("Page 5 of 5", clamped)
        self.assertIn("Message 120", clamped)

    def test_pagination_links_preserve_page_size_and_use_dedicated_parameters(self):
        item = self._item(30)
        relationships = [self._relationship(index, 1) for index in range(1, 31)]
        html = self._render(item, relationships, page=2, page_size=10)
        self.assertIn("attachment_page=1&amp;attachment_page_size=10", html)
        self.assertIn("attachment_page=3&amp;attachment_page_size=10", html)
        self.assertNotIn("?page=", html)

    def test_lazy_hydration_receives_only_visible_message_groups(self):
        item = self._item(30)
        relationships = [self._relationship(index, 1) for index in range(1, 31)]
        hydrated_ids: list[str] = []

        def hydrate(rows, **kwargs):
            self.assertTrue(kwargs["read_only"])
            hydrated_ids.extend(row["relationship_id"] for row in rows)
            return self._identity_hydration(rows)

        with patch.object(
            admin_session, "hydrate_email_attachment_documents", side_effect=hydrate
        ):
            admin_session._render_admin_mailbox_attachment_relationship_navigation(
                item, relationships, attachment_page=2, attachment_page_size=10
            )
        expected = [self._relationship(index, 1)["relationship_id"] for index in range(11, 21)]
        self.assertEqual(hydrated_ids, expected)

    def test_scale_fixture_renders_211_relationships_exactly_once_by_complete_group(self):
        item = self._item(69)
        relationships = []
        ordinal = 1
        for message_index in range(1, 70):
            count = 4 if message_index <= 4 else 3
            for attachment_index in range(1, count + 1):
                relationships.append(
                    self._relationship(
                        message_index, attachment_index, ordinal=ordinal
                    )
                )
                ordinal += 1
        self.assertEqual(len(relationships), 211)

        pages = []
        hydrated_page_counts = []
        for page in (1, 2, 3):
            hydrated_ids: list[str] = []

            def hydrate(rows, **kwargs):
                self.assertTrue(kwargs["read_only"])
                hydrated_ids.extend(row["relationship_id"] for row in rows)
                return self._identity_hydration(rows)

            with patch.object(
                admin_session,
                "hydrate_email_attachment_documents",
                side_effect=hydrate,
            ):
                pages.append(
                    admin_session._render_admin_mailbox_attachment_relationship_navigation(
                        item, relationships, attachment_page=page
                    )
                )
            hydrated_page_counts.append(len(hydrated_ids))
        for relationship in relationships:
            self.assertEqual(
                sum(
                    page.count(f">{relationship['relationship_id']}<")
                    for page in pages
                ),
                1,
            )
        self.assertEqual(
            [page.count('<details class="mailbox-attachment-group">') for page in pages],
            [25, 25, 19],
        )
        self.assertEqual(hydrated_page_counts, [79, 75, 57])
        self.assertIn("211 attachment relationships across 69 messages", pages[0])

    def test_list_archive_attachments_default_eager_and_opt_out_lightweight(self):
        source = self._store(
            _build_stage53_mbox(), "stage53-1-source.mbox", "application/mbox"
        )
        eager = list_archive_attachments(source["intake_id"], root=self.root)
        lightweight = list_archive_attachments(
            source["intake_id"], root=self.root, load_documents=False
        )
        self.assertTrue(any(row.get("attachment_document") for row in eager))
        self.assertTrue(all("attachment_document" not in row for row in lightweight))
        self.assertEqual(
            [row["relationship_id"] for row in eager],
            [row["relationship_id"] for row in lightweight],
        )

    def test_lightweight_archive_query_does_not_create_registry_state(self):
        self.root.mkdir(parents=True)
        registry_path = self.root / REGISTRY_FILENAME
        self.assertEqual(
            list_archive_attachments("a" * 64, root=self.root, load_documents=False),
            [],
        )
        self.assertFalse(registry_path.exists())

    def test_mbox_admin_get_does_not_mutate_relationship_or_source_metadata(self):
        source = self._store(
            _build_stage53_mbox(), "stage53-1-read-only.mbox", "application/mbox"
        )
        registry_path = self.root / REGISTRY_FILENAME
        source_metadata_path = self.root / source["intake_id"] / "metadata.json"
        relationship_bytes = registry_path.read_bytes()
        source_metadata_bytes = source_metadata_path.read_bytes()
        attachment_metadata = {
            path: path.read_bytes()
            for path in self.root.glob("*/metadata.json")
            if path != source_metadata_path
        }

        response = admin_session.admin_document_intake_preview_page(
            source["intake_id"], self._request()
        )
        self.assertIn("mailbox-attachment-group", response.content)
        self.assertEqual(registry_path.read_bytes(), relationship_bytes)
        self.assertEqual(source_metadata_path.read_bytes(), source_metadata_bytes)
        self.assertEqual(
            {path: path.read_bytes() for path in attachment_metadata}, attachment_metadata
        )

    def test_standalone_eml_msg_and_emlx_retain_flat_stage50_presentation(self):
        cases = (
            (MULTI_ATTACHMENT_EML, "source.eml", "message/rfc822"),
            (_build_stage51_msg(), "source.msg", "application/vnd.ms-outlook"),
            (_build_stage52_emlx(), "source.emlx", "application/octet-stream"),
        )
        for data, filename, content_type in cases:
            with self.subTest(filename=filename):
                source = self._store(data, filename, content_type)
                html = admin_session.admin_document_intake_preview_page(
                    source["intake_id"], self._request()
                ).content
                self.assertIn("Governed Email Attachment Relationships", html)
                self.assertIn("Open Published Document", html)
                self.assertIn("<th>Original filename</th>", html)
                self.assertNotIn('<details class="mailbox-attachment-group">', html)
                self.assertNotIn("Mailbox attachment relationship summary", html)
                self.assertNotIn("attachment_page=", html)

    def test_grouped_navigation_is_admin_only_and_does_not_change_public_routes(self):
        source = self._store(
            _build_stage53_mbox(), "stage53-1-private.mbox", "application/mbox"
        )
        with self.assertRaises(Exception):
            admin_session.admin_document_intake_preview_page(
                source["intake_id"], FakeRequest(cookies={})
            )
        self.assertEqual(
            admin_session.admin_document_intake_preview_page.__module__,
            "api.routes.admin_session",
        )


if __name__ == "__main__":
    unittest.main()
