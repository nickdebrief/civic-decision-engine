from __future__ import annotations

import json
import inspect
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from api.document_intake import (
    load_pending_document_read_only,
    store_pending_document,
)
from api.email_attachment_preservation import REGISTRY_FILENAME, list_archive_attachments
from tests.test_admin_session import FakeRequest, install_fastapi_stubs
from tests.test_stage53_mbox_attachment_preservation import _build_stage53_mbox


install_fastapi_stubs()

from api.routes import admin_session  # noqa: E402


class Stage54AppleMailMailboxRelationshipProjectionNavigationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "pending"
        self.environment = patch.dict(
            os.environ,
            {
                "CDE_DOCUMENT_INTAKE_ROOT": str(self.root),
                "ADMIN_USERNAME": "stage54-admin",
                "ADMIN_PASSWORD": "password",
                "CDE_ADMIN_SESSION_SECRET": "stage54-secret",
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
                    "stage54-admin"
                )
            }
        )

    def _store(self):
        return store_pending_document(
            data=_build_stage53_mbox(),
            original_filename="stage54-source.mbox",
            content_type="application/mbox",
            title="Stage 54 authoritative mailbox",
            institution_source="Civic Evidence Office",
            document_date="2026-08-08",
            category="Email Correspondence",
            description="Synthetic Stage 54 mailbox.",
            visibility="private",
            notes="Synthetic test evidence only.",
            actor="stage54-admin",
            uploaded_at="2026-08-08T09:00:00Z",
            root=self.root,
        )

    def _route(self, source: dict, message_index: object = 1):
        return admin_session.admin_outlook_archive_message_projection_page(
            source["intake_id"], str(message_index), self._request()
        )

    def _metadata_path(self, source: dict) -> Path:
        return self.root / source["intake_id"] / "metadata.json"

    def _replace_messages(self, source: dict, messages: list[dict]) -> None:
        path = self._metadata_path(source)
        metadata = json.loads(path.read_text(encoding="utf-8"))
        metadata["email_metadata"]["messages"] = messages
        path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    @staticmethod
    def _http_status(context) -> int | None:
        return getattr(context.exception, "status_code", None)

    def _filesystem_snapshot(self) -> tuple[tuple[str, ...], dict[str, bytes]]:
        paths = tuple(
            sorted(str(path.relative_to(self.root)) for path in self.root.rglob("*"))
        )
        files = {
            str(path.relative_to(self.root)): path.read_bytes()
            for path in self.root.rglob("*")
            if path.is_file()
        }
        return paths, files

    def test_existing_authenticated_route_resolves_mbox_projection(self):
        source = self._store()
        html = self._route(source, 1).content
        self.assertIn("Contained Message Projection", html)
        self.assertIn(f"{source['intake_id']}:message:1", html)
        self.assertIn("mbox attachment one", html)
        self.assertIn("sender@example.test", html)
        self.assertIn("recipient@example.test", html)
        self.assertIn("Message-ID (provenance only)", html)
        self.assertIn("&lt;mbox-attach-1@example.test&gt;", html)
        self.assertIn(source["document_identifier"], html)
        self.assertIn(
            f'/admin/document-intake/{source["intake_id"]}#governed-email-attachment-relationships',
            html,
        )
        self.assertNotIn("Message one body", html)
        self.assertNotIn("Promote to Canonical Record", html)

    def test_authentication_is_required(self):
        source = self._store()
        with self.assertRaises(Exception):
            admin_session.admin_outlook_archive_message_projection_page(
                source["intake_id"], "1", FakeRequest(cookies={})
            )

    def test_invalid_absent_and_ambiguous_message_indexes_fail_safely(self):
        source = self._store()
        for value in ("abc", "0", "-1", "1.0", "999"):
            with self.subTest(value=value), self.assertRaises(Exception) as context:
                self._route(source, value)
            self.assertEqual(self._http_status(context), 404)

        metadata = json.loads(self._metadata_path(source).read_text(encoding="utf-8"))
        messages = list(metadata["email_metadata"]["messages"])
        messages.append(dict(messages[0]))
        self._replace_messages(source, messages)
        with self.assertRaises(Exception) as context:
            self._route(source, 1)
        self.assertEqual(self._http_status(context), 404)

    def test_projection_metadata_fields_and_date_fallback_are_source_derived(self):
        source = self._store()
        metadata = json.loads(self._metadata_path(source).read_text(encoding="utf-8"))
        message = metadata["email_metadata"]["messages"][0]
        message["sender_raw"] = "sender-header@example.test"
        message["reply_to_raw"] = "reply@example.test"
        message["cc_raw"] = "copy@example.test"
        message["bcc_raw"] = "hidden@example.test"
        message["date_header_parsed"] = ""
        self._replace_messages(source, metadata["email_metadata"]["messages"])

        html = self._route(source, 1).content
        for expected in (
            "sender-header@example.test",
            "recipient@example.test",
            "copy@example.test",
            "reply@example.test",
            "Tue, 21 Jul 2026 11:30:00 +0000",
            message["message_digest"],
            f"{message['byte_start']}–{message['byte_end']}",
            "parsed",
        ):
            self.assertIn(expected, html)
        self.assertNotIn("hidden@example.test", html)
        self.assertNotIn("<th>BCC</th>", html)

    def test_unparsed_projection_remains_visible_without_fabricated_headers(self):
        source = self._store()
        metadata = json.loads(self._metadata_path(source).read_text(encoding="utf-8"))
        message = metadata["email_metadata"]["messages"][2]
        for key in (
            "subject_decoded",
            "sender_raw",
            "from_raw",
            "to_raw",
            "cc_raw",
            "reply_to_raw",
            "date_header_parsed",
            "date_header_raw",
            "message_id",
        ):
            message.pop(key, None)
        message["parsed"] = False
        message["parse_status"] = "warning"
        message["parser_warnings"] = ["synthetic-parse-warning"]
        self._replace_messages(source, metadata["email_metadata"]["messages"])

        html = self._route(source, 3).content
        self.assertIn("<th>Message index</th><td>3</td>", html)
        self.assertIn("synthetic-parse-warning", html)
        self.assertIn(message["message_digest"], html)
        self.assertNotIn("<th>Subject</th>", html)
        self.assertNotIn("<th>Sender / From</th>", html)
        self.assertNotIn("Message-ID (provenance only)", html)

    def test_selected_message_relationships_are_scoped_ordered_and_failure_safe(self):
        source = self._store()
        relationships = list_archive_attachments(source["intake_id"], root=self.root)
        message_two = [
            relationship
            for relationship in relationships
            if relationship["source_email_object_id"].endswith(":message:2")
        ]
        html = self._route(source, 2).content
        self.assertIn("report-2.pdf", html)
        self.assertIn("forwarded.eml", html)
        self.assertNotIn("report-1.pdf", html)
        self.assertLess(html.index("report-2.pdf"), html.index("forwarded.eml"))

        registry = self.root / REGISTRY_FILENAME
        conn = sqlite3.connect(registry)
        try:
            for relationship in message_two:
                conn.execute(
                    "UPDATE email_attachment_relationships SET attachment_index = 1 WHERE relationship_id = ?",
                    (relationship["relationship_id"],),
                )
            conn.commit()
        finally:
            conn.close()
        html = self._route(source, 2).content
        ordered_ids = sorted(relationship["relationship_id"] for relationship in message_two)
        self.assertLess(html.index(ordered_ids[0]), html.index(ordered_ids[1]))

        failed = self._route(source, 4).content
        self.assertIn("failed", failed)
        self.assertIn("No attachment Published Document", failed)
        self.assertIn("Inspect metadata", failed)
        self.assertNotIn("Open Published Document", failed)

    def test_stage53_1_groups_link_only_exact_matched_messages(self):
        source = self._store()
        relationships = list_archive_attachments(
            source["intake_id"], root=self.root, load_documents=False
        )
        malformed = dict(relationships[0])
        malformed["relationship_id"] = "EAR-UNRESOLVED-STAGE54"
        malformed["source_email_object_id"] = "wrong:message:1"
        html = admin_session._render_admin_mailbox_attachment_relationship_navigation(
            source, relationships + [malformed]
        )
        self.assertIn(
            f'/admin/archive/{source["intake_id"]}/messages/1', html
        )
        unresolved = html[html.index("Unresolved message relationship") :]
        self.assertNotIn("Open message projection", unresolved)
        self.assertIn("attachment_page=2", admin_session._render_admin_mailbox_attachment_relationship_navigation(
            {
                **source,
                "email_metadata": {
                    "messages": [
                        {"message_index": index, "parsed": True}
                        for index in range(1, 31)
                    ]
                },
            },
            [
                {
                    **relationships[0],
                    "relationship_id": f"EAR-{index:024d}",
                    "source_email_object_id": f"{source['intake_id']}:message:{index}",
                    "attachment_document_id": None,
                    "extraction_status": "failed",
                }
                for index in range(1, 31)
            ],
        ))

    def test_attachment_source_backlink_requires_exact_mbox_provenance(self):
        source = self._store()
        relationship = list_archive_attachments(source["intake_id"], root=self.root)[0]
        attachment = relationship["attachment_document"]
        html = admin_session.admin_document_intake_preview_page(
            attachment["intake_id"], self._request()
        ).content
        self.assertIn(
            f'/admin/archive/{source["intake_id"]}/messages/1', html
        )
        malformed = dict(relationship)
        malformed["source_document"] = source
        malformed["source_email_object_id"] = f"{source['intake_id']}:message:0"
        self.assertIsNone(admin_session._mailbox_message_projection_href(malformed))

    def test_read_only_loader_does_not_assign_or_persist_defaults(self):
        source = self._store()
        metadata_path = self._metadata_path(source)
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata.pop("document_identifier", None)
        metadata.pop("keywords", None)
        metadata.pop("tags", None)
        metadata_path.write_text(
            json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        identifier_registry = self.root / ".document_identifiers.sqlite3"
        before_metadata = metadata_path.read_bytes()
        before_registry = identifier_registry.read_bytes()

        loaded = load_pending_document_read_only(source["intake_id"], root=self.root)
        self.assertNotIn("document_identifier", loaded)
        self.assertEqual(loaded["keywords"], [])
        self.assertEqual(metadata_path.read_bytes(), before_metadata)
        self.assertEqual(identifier_registry.read_bytes(), before_registry)

    def test_stage54_get_is_byte_and_path_stable_and_does_not_read_mbox(self):
        source = self._store()
        before = self._filesystem_snapshot()
        original_open = Path.open

        def guarded_open(path, *args, **kwargs):
            if path.suffix == ".mbox":
                raise AssertionError("authoritative MBOX bytes must not be opened")
            return original_open(path, *args, **kwargs)

        with patch.object(Path, "open", guarded_open):
            response = self._route(source, 2)
        self.assertIn("Contained Message Projection", response.content)
        self.assertEqual(self._filesystem_snapshot(), before)

    def test_scale_fixture_queries_and_hydrates_only_selected_message(self):
        archive_id = "a" * 64
        messages = [
            {
                "message_index": index,
                "parsed": True,
                "parse_status": "parsed",
                "parser_warnings": [],
                "message_byte_size": 100 + index,
                "message_digest": f"{index:064x}",
                "attachment_count": 4 if index <= 4 else 3,
            }
            for index in range(1, 70)
        ]
        source = {
            "intake_id": archive_id,
            "document_identifier": "DOC-2026-000001",
            "document_type": "mbox",
            "email_metadata": {"messages": messages},
        }
        relationships = []
        ordinal = 1
        for message_index in range(1, 70):
            count = 4 if message_index <= 4 else 3
            for attachment_index in range(1, count + 1):
                relationships.append(
                    {
                        "relationship_id": f"EAR-{ordinal:024d}",
                        "source_email_object_id": f"{archive_id}:message:{message_index}",
                        "relationship_type": "Email attachment",
                        "attachment_index": attachment_index,
                        "display_title": f"Attachment {ordinal}",
                        "attachment_document_id": f"{ordinal:064x}",
                        "extraction_status": "preserved",
                    }
                )
                ordinal += 1
        self.assertEqual(len(relationships), 211)
        selected = [
            row
            for row in relationships
            if row["source_email_object_id"] == f"{archive_id}:message:40"
        ]
        hydrated: list[str] = []

        def hydrate(rows, **kwargs):
            self.assertTrue(kwargs["read_only"])
            hydrated.extend(row["relationship_id"] for row in rows)
            return [
                {
                    **row,
                    "attachment_document": {
                        "intake_id": row["attachment_document_id"],
                        "document_identifier": f"DOC-{row['relationship_id']}",
                        "status": "pending",
                    },
                }
                for row in rows
            ]

        with (
            patch.object(admin_session, "load_pending_document_read_only", return_value=source),
            patch.object(
                admin_session,
                "list_email_source_attachments",
                return_value=selected,
            ) as query,
            patch.object(
                admin_session,
                "hydrate_email_attachment_documents",
                side_effect=hydrate,
            ),
        ):
            response = admin_session.admin_outlook_archive_message_projection_page(
                archive_id, "40", self._request()
            )
        query.assert_called_once_with(
            f"{archive_id}:message:40", root=self.root, load_documents=False
        )
        self.assertEqual(hydrated, [row["relationship_id"] for row in selected])
        self.assertEqual(len(hydrated), 3)
        self.assertIn("Contained Message Projection", response.content)

    def test_non_mbox_and_public_route_contracts_remain_unchanged(self):
        self.assertEqual(
            admin_session.admin_outlook_archive_message_projection_page.__module__,
            "api.routes.admin_session",
        )
        route_source = inspect.getsource(
            admin_session.admin_outlook_archive_message_projection_page
        )
        self.assertIn(
            '/admin/archive/{document_id}/messages/{message_id}', route_source
        )


if __name__ == "__main__":
    unittest.main()
