from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from api.document_intake import load_pending_document, store_pending_document
from api.email_attachment_preservation import (
    REGISTRY_FILENAME,
    list_attachment_sources,
)
from tests.test_admin_session import FakeRequest, install_fastapi_stubs
from tests.test_mbox_archive_support import mbox

install_fastapi_stubs()

from api.routes import admin_session  # noqa: E402
from tests.test_stage49_email_attachment_preservation import (  # noqa: E402
    MULTI_ATTACHMENT_EML,
)
from tests.test_stage51_outlook_msg_attachment_preservation import (  # noqa: E402
    _build_stage51_msg,
)
from tests.test_stage52_apple_emlx_attachment_preservation import (  # noqa: E402
    _build_stage52_emlx,
)


def _build_mbox_with_attachment() -> bytes:
    msg = b"""From: sender@example.test
To: recipient@example.test
Subject: mbox source message
Date: Tue, 21 Jul 2026 10:30:00 +0000
Message-ID: <mbox-source@example.test>
MIME-Version: 1.0
Content-Type: multipart/mixed; boundary="MIX"

--MIX
Content-Type: text/plain; charset=utf-8

Body.
--MIX
Content-Type: application/pdf
Content-Disposition: attachment; filename="source.pdf"
Content-Transfer-Encoding: base64

JVBERi0xLjQKc3RhZ2U1NQo=
--MIX--
"""
    return mbox(msg, separators=[b"From sender@example.test Tue Jul 21 10:30:00 2026\n"])


class Stage55AttachmentSourceContextTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "pending"
        self.environment = patch.dict(
            os.environ,
            {
                "CDE_DOCUMENT_INTAKE_ROOT": str(self.root),
                "ADMIN_USERNAME": "stage55-admin",
                "ADMIN_PASSWORD": "password",
                "CDE_ADMIN_SESSION_SECRET": "stage55-secret",
            },
            clear=False,
        )
        self.environment.start()
        self._source_docs: list[dict] = []

    def tearDown(self):
        self.environment.stop()
        self.temporary.cleanup()

    def _admin_session_request(self):
        return FakeRequest(
            cookies={
                admin_session.SESSION_COOKIE_NAME: admin_session.create_admin_session(
                    "stage55-admin"
                )
            }
        )

    def _store_eml_source(self) -> dict:
        source = store_pending_document(
            data=MULTI_ATTACHMENT_EML,
            original_filename="source.eml",
            content_type="message/rfc822",
            title="EML source",
            institution_source="Civic Evidence Office",
            document_date="2026-08-08",
            category="Email",
            description="EML source.",
            visibility="private",
            notes="none",
            actor="stage55-admin",
            uploaded_at="2026-08-08T10:00:00Z",
            root=self.root,
        )
        self._source_docs.append(source)
        return source

    def _store_msg_source(self) -> dict:
        source = store_pending_document(
            data=_build_stage51_msg(),
            original_filename="source.msg",
            content_type="application/vnd.ms-outlook",
            title="MSG source",
            institution_source="Civic Evidence Office",
            document_date="2026-08-08",
            category="Email",
            description="MSG source.",
            visibility="private",
            notes="none",
            actor="stage55-admin",
            uploaded_at="2026-08-08T10:00:00Z",
            root=self.root,
        )
        self._source_docs.append(source)
        return source

    def _store_emlx_source(self) -> dict:
        source = store_pending_document(
            data=_build_stage52_emlx(),
            original_filename="source.emlx",
            content_type="application/octet-stream",
            title="EMLX source",
            institution_source="Civic Evidence Office",
            document_date="2026-08-08",
            category="Email",
            description="EMLX source.",
            visibility="private",
            notes="none",
            actor="stage55-admin",
            uploaded_at="2026-08-08T10:00:00Z",
            root=self.root,
        )
        self._source_docs.append(source)
        return source

    def _store_mbox_source(self) -> dict:
        source = store_pending_document(
            data=_build_mbox_with_attachment(),
            original_filename="source.mbox",
            content_type="application/mbox",
            title="MBOX source",
            institution_source="Civic Evidence Office",
            document_date="2026-08-08",
            category="Email",
            description="MBOX source.",
            visibility="private",
            notes="none",
            actor="stage55-admin",
            uploaded_at="2026-08-08T10:00:00Z",
            root=self.root,
        )
        self._source_docs.append(source)
        return source

    def _first_attachment_doc(self, source: dict) -> dict:
        from api.email_attachment_preservation import list_source_attachments

        relationships = list_source_attachments(source["intake_id"], root=self.root)
        return relationships[0]["attachment_document"]

    def _render_admin(self, intake_id: str) -> str:
        return admin_session.admin_document_intake_preview_page(
            intake_id, self._admin_session_request()
        ).content

    def test_standalone_eml_source_context_card(self):
        source = self._store_eml_source()
        attachment = self._first_attachment_doc(source)
        html = self._render_admin(attachment["intake_id"])
        self.assertIn("Source Context", html)
        self.assertIn(source["document_identifier"], html)
        self.assertIn("RFC 5322 EML", html)
        self.assertIn(
            f'/admin/document-intake/{source["intake_id"]}', html
        )
        self.assertIn("Open source document", html)
        self.assertIn("Email attachment", html)
        self.assertIn("rfc5322_eml", html)

    def test_standalone_msg_source_context_card(self):
        source = self._store_msg_source()
        attachment = self._first_attachment_doc(source)
        html = self._render_admin(attachment["intake_id"])
        self.assertIn("Source Context", html)
        self.assertIn(source["document_identifier"], html)
        self.assertIn("Outlook MSG", html)
        self.assertIn(
            f'/admin/document-intake/{source["intake_id"]}', html
        )

    def test_standalone_emlx_source_context_card(self):
        source = self._store_emlx_source()
        attachment = self._first_attachment_doc(source)
        html = self._render_admin(attachment["intake_id"])
        self.assertIn("Source Context", html)
        self.assertIn(source["document_identifier"], html)
        self.assertIn("Apple Mail EMLX", html)

    def test_mbox_source_context_with_message_projection_and_mailbox_links(self):
        source = self._store_mbox_source()
        from api.email_attachment_preservation import list_archive_attachments

        relationships = list_archive_attachments(source["intake_id"], root=self.root)
        attachment_doc = relationships[0]["attachment_document"]
        html = self._render_admin(attachment_doc["intake_id"])
        self.assertIn("Source Context", html)
        self.assertIn("MBOX contained message", html)
        self.assertIn("mbox_message", html)
        self.assertIn("Open message projection", html)
        self.assertIn("Open authoritative mailbox", html)
        self.assertIn(
            f"/admin/archive/{source['intake_id']}/messages/", html
        )
        self.assertIn(
            f"/admin/document-intake/{source['intake_id']}", html
        )

    def test_relationship_id_and_type_visible(self):
        source = self._store_eml_source()
        attachment = self._first_attachment_doc(source)
        html = self._render_admin(attachment["intake_id"])
        from api.email_attachment_preservation import list_source_attachments

        rel = list_source_attachments(source["intake_id"], root=self.root)[0]
        self.assertIn(rel["relationship_id"], html)
        self.assertIn("Email attachment", html)

    def test_attachment_index_and_pathway_visible(self):
        source = self._store_eml_source()
        attachment = self._first_attachment_doc(source)
        html = self._render_admin(attachment["intake_id"])
        self.assertIn("Attachment index", html)
        self.assertIn("Source pathway", html)
        self.assertIn("rfc5322_eml", html)

    def test_source_document_identifier_visible(self):
        source = self._store_eml_source()
        attachment = self._first_attachment_doc(source)
        html = self._render_admin(attachment["intake_id"])
        self.assertIn("Source document", html)
        self.assertIn(source["document_identifier"], html)

    def test_message_id_treated_as_provenance_only(self):
        source = self._store_eml_source()
        attachment = self._first_attachment_doc(source)
        html = self._render_admin(attachment["intake_id"])
        self.assertIn("Message-ID (provenance)", html)
        # HTML-escaped form of <stage49@example.test>
        self.assertIn("&lt;stage49@example.test&gt;", html)

    def test_no_heuristic_navigation_from_filename(self):
        source = self._store_eml_source()
        attachment = self._first_attachment_doc(source)
        html = self._render_admin(attachment["intake_id"])
        # The source document link must be from governed intake_id, not a
        # filename-derived path
        self.assertIn("Open source document", html)
        # No link derived from attachment filename
        self.assertNotIn(f"/admin/document-intake/report.pdf", html)

    def test_missing_source_shows_source_unavailable(self):
        source = self._store_eml_source()
        attachment = self._first_attachment_doc(source)
        # Delete the source document's metadata to simulate missing source
        source_meta = self.root / source["intake_id"] / "metadata.json"
        source_meta.unlink()
        html = self._render_admin(attachment["intake_id"])
        self.assertIn("Source unavailable", html)
        # Relationship ID still visible
        from api.email_attachment_preservation import list_attachment_sources

        rel = list_attachment_sources(attachment["intake_id"], root=self.root, load_documents=False)[0]
        self.assertIn(rel["relationship_id"], html)

    def test_read_only_get_does_not_mutate_identifier_registry(self):
        source = self._store_eml_source()
        attachment = self._first_attachment_doc(source)
        # Snapshot the document identifier registry before
        registry_path = self.root / ".document_identifiers.sqlite3"
        before_size = registry_path.stat().st_size if registry_path.exists() else 0
        before_mtime = registry_path.stat().st_mtime_ns if registry_path.exists() else 0

        self._render_admin(attachment["intake_id"])

        after_size = registry_path.stat().st_size if registry_path.exists() else 0
        after_mtime = registry_path.stat().st_mtime_ns if registry_path.exists() else 0
        self.assertEqual(before_size, after_size)
        self.assertEqual(before_mtime, after_mtime)

    def test_read_only_get_does_not_mutate_relationship_registry(self):
        source = self._store_eml_source()
        attachment = self._first_attachment_doc(source)
        registry_path = self.root / REGISTRY_FILENAME
        before_size = registry_path.stat().st_size if registry_path.exists() else 0

        self._render_admin(attachment["intake_id"])

        after_size = registry_path.stat().st_size if registry_path.exists() else 0
        self.assertEqual(before_size, after_size)

    def test_read_only_get_does_not_mutate_source_metadata(self):
        source = self._store_eml_source()
        attachment = self._first_attachment_doc(source)
        source_meta_path = self.root / source["intake_id"] / "metadata.json"
        before = source_meta_path.read_bytes()

        self._render_admin(attachment["intake_id"])

        after = source_meta_path.read_bytes()
        self.assertEqual(before, after)

    def test_read_only_get_does_not_mutate_attachment_metadata(self):
        source = self._store_eml_source()
        attachment = self._first_attachment_doc(source)
        att_meta_path = self.root / attachment["intake_id"] / "metadata.json"
        before = att_meta_path.read_bytes()

        self._render_admin(attachment["intake_id"])

        after = att_meta_path.read_bytes()
        self.assertEqual(before, after)

    def test_read_only_get_does_not_change_directory_structure(self):
        source = self._store_eml_source()
        attachment = self._first_attachment_doc(source)
        dirs_before = {p.name for p in self.root.iterdir() if p.is_dir()}

        self._render_admin(attachment["intake_id"])

        dirs_after = {p.name for p in self.root.iterdir() if p.is_dir()}
        self.assertEqual(dirs_before, dirs_after)

    def test_read_only_get_does_not_create_canonical_record(self):
        source = self._store_eml_source()
        attachment = self._first_attachment_doc(source)
        rda_path = self.root / ".record_document_associations.sqlite3"
        before = rda_path.exists()

        self._render_admin(attachment["intake_id"])

        self.assertEqual(before, rda_path.exists())

    def test_no_canonical_record_or_published_document_created_during_get(self):
        source = self._store_eml_source()
        attachment = self._first_attachment_doc(source)
        dirs_before = {p.name for p in self.root.iterdir() if p.is_dir()}

        self._render_admin(attachment["intake_id"])

        dirs_after = {p.name for p in self.root.iterdir() if p.is_dir()}
        # No new intake directories created
        self.assertEqual(dirs_before, dirs_after)

    def test_list_attachment_sources_read_only_mode(self):
        source = self._store_eml_source()
        attachment = self._first_attachment_doc(source)
        # With read_only=True, the source_document should still load
        rels = list_attachment_sources(
            attachment["intake_id"], root=self.root, read_only=True
        )
        self.assertTrue(len(rels) >= 1)
        self.assertIsInstance(rels[0].get("source_document"), dict)

    def test_list_attachment_sources_load_documents_false(self):
        source = self._store_eml_source()
        attachment = self._first_attachment_doc(source)
        rels = list_attachment_sources(
            attachment["intake_id"], root=self.root, load_documents=False
        )
        self.assertTrue(len(rels) >= 1)
        self.assertNotIn("source_document", rels[0])

    def test_pending_source_remains_administratively_navigable(self):
        source = self._store_eml_source()  # source is pending
        attachment = self._first_attachment_doc(source)
        html = self._render_admin(attachment["intake_id"])
        # Admin can navigate regardless of source lifecycle
        self.assertIn("Open source document", html)
        self.assertIn(
            f'/admin/document-intake/{source["intake_id"]}', html
        )

    def test_existing_stage50_source_email_rendering_unchanged(self):
        # Source-email direction (non-attachment document) should still use the
        # Stage 50 9-column table, not the source-context card.
        source = self._store_eml_source()
        html = self._render_admin(source["intake_id"])
        self.assertIn("Governed Email Attachment Relationships", html)
        self.assertIn("Original filename", html)
        self.assertIn("Open Published Document", html)

    def test_projected_message_navigation_uses_existing_route_format(self):
        # Verify the _projected_message_projection_href helper handles
        # the {archive_id}:message:{projection_id} format correctly
        relationship = {
            "source_email_kind": "projected_message",
            "source_email_document_id": "abc123",
            "source_email_object_id": "abc123:message:projection-xyz",
        }
        href = admin_session._projected_message_projection_href(relationship)
        self.assertIsNotNone(href)
        self.assertIn("/admin/archive/abc123/messages/projection-xyz", href)

    def test_projected_message_rejects_unsafe_projection_id(self):
        relationship = {
            "source_email_kind": "projected_message",
            "source_email_document_id": "abc123",
            "source_email_object_id": "abc123:message:bad/projection",
        }
        href = admin_session._projected_message_projection_href(relationship)
        self.assertIsNone(href)

    def test_public_attachment_page_not_modified_by_stage55(self):
        # Stage 55 is admin-only; verify documents.py is not in the diff
        import subprocess

        result = subprocess.run(
            ["git", "diff", "--name-only", "main", "--", "api/routes/documents.py"],
            capture_output=True,
            text=True,
            cwd=str(self.root.parent.parent),
        )
        self.assertEqual(result.stdout.strip(), "")


if __name__ == "__main__":
    unittest.main()
