from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from io import BytesIO
from pathlib import Path
from tests.test_admin_session import FakeRequest, install_fastapi_stubs

install_fastapi_stubs()

from fastapi import HTTPException

from api.archive_projection_access import load_archive_projection
from api.document_intake import load_pending_document
from api.imap_acquisition import (
    IMAP_MANIFEST_PATH,
    ImapAcquisitionError,
    ImapAcquisitionParser,
    ImapAcquisitionSettings,
    acquire_imap_archive,
    acquire_imap_document,
    validate_imap_acquisition_archive,
)
from api.mailbox_relationship_graph import build_imap_acquisition_relationship_graph
from api.outlook_archive_attachments import (
    list_outlook_attachments,
    validate_archive_attachment_promotion,
)
from api.outlook_archive_promotion import (
    build_outlook_message_promotion_provenance,
    validate_archive_message_promotion,
)
from api.routes.admin_session import admin_imap_acquisition_summary_api
from api.routes import documents


RAW_ONE = (
    b"Message-ID: <one@example.test>\r\n"
    b"Date: Tue, 1 Aug 2026 09:00:00 +0000\r\n"
    b"From: Alice <alice@example.test>\r\n"
    b"To: Bob <bob@example.test>\r\n"
    b"Subject: First IMAP message\r\n"
    b"MIME-Version: 1.0\r\n"
    b"Content-Type: multipart/mixed; boundary=stage41\r\n\r\n"
    b"--stage41\r\nContent-Type: text/plain; charset=utf-8\r\n\r\nBody one.\r\n"
    b"--stage41\r\nContent-Type: text/plain\r\n"
    b"Content-Disposition: attachment; filename=evidence.txt\r\n\r\n"
    b"attachment evidence\r\n--stage41--\r\n"
)
RAW_TWO = (
    b"Message-ID: <two@example.test>\r\n"
    b"In-Reply-To: <one@example.test>\r\n"
    b"References: <one@example.test>\r\n"
    b"Date: Tue, 1 Aug 2026 10:00:00 +0000\r\n"
    b"From: Bob <bob@example.test>\r\n"
    b"To: Alice <alice@example.test>\r\n"
    b"Subject: Re: First IMAP message\r\n\r\nBody two.\r\n"
)


class FakeImapClient:
    def __init__(self, settings: ImapAcquisitionSettings):
        self.settings = settings
        self.current = ""
        self.logged_out = False
        self.closed = 0
        self.login_values: tuple[str, str] | None = None
        self.folders = {
            "INBOX": ("7001", {"41": RAW_ONE, "42": RAW_TWO}),
            "Sent Items": ("7002", {"7": RAW_TWO}),
        }

    def login(self, username: str, password: str):
        self.login_values = (username, password)
        return "OK", [b"authenticated"]

    def list(self):
        return "OK", [
            b'(\\HasNoChildren) "/" "INBOX"',
            b'(\\HasNoChildren) "/" "Sent Items"',
        ]

    def select(self, mailbox: str, readonly: bool = False):
        self.current = mailbox.strip('"').replace(r'\"', '"').replace(r"\\", "\\")
        if not readonly or self.current not in self.folders:
            return "NO", [b"unavailable"]
        return "OK", [str(len(self.folders[self.current][1])).encode("ascii")]

    def response(self, name: str):
        if name == "UIDVALIDITY" and self.current:
            return "UIDVALIDITY", [self.folders[self.current][0].encode("ascii")]
        return None, None

    def uid(self, command: str, *args):
        if command.casefold() == "search":
            values = " ".join(self.folders[self.current][1]).encode("ascii")
            return "OK", [values]
        if command.casefold() == "fetch":
            uid = str(args[0])
            raw = self.folders[self.current][1][uid]
            return "OK", [(f"1 (UID {uid} RFC822 {{{len(raw)}}}".encode("ascii"), raw), b")"]
        return "NO", []

    def close(self):
        self.closed += 1
        self.current = ""
        return "OK", [b"closed"]

    def logout(self):
        self.logged_out = True
        return "BYE", [b"logout"]


def settings(*folders: str) -> ImapAcquisitionSettings:
    return ImapAcquisitionSettings(
        hostname="imap.example.test",
        port=993,
        tls_mode="ssl",
        username="private-login@example.test",
        password="stage41-super-secret",
        mailbox_identifier="Governed Research Mailbox",
        selected_folders=tuple(folders or ("INBOX",)),
    )


class ImapAcquisitionTests(unittest.TestCase):
    def acquire(self, *folders: str):
        clients: list[FakeImapClient] = []

        def factory(value):
            client = FakeImapClient(value)
            clients.append(client)
            return client

        result = acquire_imap_archive(
            settings(*folders),
            client_factory=factory,
            acquired_at="2026-08-01T12:00:00Z",
            acquisition_id="IMAP-0123456789ABCDEF01234567",
        )
        return result, clients[0]

    def test_acquisition_discovers_folders_and_preserves_uids_and_exact_bytes(self):
        result, client = self.acquire("INBOX", "Sent Items")
        manifest = validate_imap_acquisition_archive(result.archive_bytes)
        self.assertEqual([folder["name"] for folder in manifest["selected_folders"]], ["INBOX", "Sent Items"])
        self.assertEqual(manifest["selected_folders"][0]["uidvalidity"], "7001")
        self.assertEqual(manifest["selected_folders"][0]["uids"], ["41", "42"])
        self.assertEqual(len(manifest["messages"]), 3)
        with zipfile.ZipFile(BytesIO(result.archive_bytes)) as package:
            first = manifest["messages"][0]
            self.assertEqual(package.read(first["path"]), RAW_ONE)
            self.assertIn(IMAP_MANIFEST_PATH, package.namelist())
        self.assertEqual(client.login_values, ("private-login@example.test", "stage41-super-secret"))
        self.assertEqual(client.closed, 2)
        self.assertTrue(client.logged_out)

    def test_credentials_never_enter_manifest_archive_or_settings_repr(self):
        result, _client = self.acquire("INBOX")
        serialized = json.dumps(result.manifest, sort_keys=True)
        self.assertNotIn("stage41-super-secret", serialized)
        self.assertNotIn("private-login@example.test", serialized)
        self.assertNotIn("stage41-super-secret", result.archive_bytes.decode("latin-1"))
        self.assertNotIn("stage41-super-secret", repr(settings("INBOX")))
        self.assertNotIn("private-login@example.test", repr(settings("INBOX")))

    def test_acquisition_is_deterministic_for_fixed_identity_and_server_snapshot(self):
        first, _ = self.acquire("INBOX")
        second, _ = self.acquire("INBOX")
        self.assertEqual(first.archive_bytes, second.archive_bytes)
        self.assertEqual(first.manifest["acquisition_hash"], second.manifest["acquisition_hash"])

    def test_selected_folder_must_exist_and_session_closes(self):
        clients: list[FakeImapClient] = []

        def factory(value):
            client = FakeImapClient(value)
            clients.append(client)
            return client

        with self.assertRaisesRegex(ImapAcquisitionError, "imap_acquisition_selected_folder_unavailable"):
            acquire_imap_archive(settings("Missing"), client_factory=factory)
        self.assertTrue(clients[0].logged_out)

    def test_parser_implements_source_neutral_archive_contract(self):
        result, _ = self.acquire("INBOX")
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "snapshot.zip"
            path.write_bytes(result.archive_bytes)
            parser = ImapAcquisitionParser()
            self.assertTrue(parser.supports(path))
            self.assertEqual(parser.inspect(path)["archive_validity"], "valid_imap_acquisition")
            projection = parser.project(path)
            repeated = parser.project(path)
            self.assertEqual(projection["source_format"], "imap_acquisition")
            self.assertEqual(len(projection["folders"]), 1)
            self.assertEqual(len(projection["messages"]), 2)
            self.assertEqual(len(projection["threads"]), 1)
            self.assertEqual(
                [item["projection_id"] for item in projection["messages"]],
                [item["projection_id"] for item in repeated["messages"]],
            )
            self.assertEqual(projection["threads"], repeated["threads"])
            self.assertEqual(len(list(parser.iter_attachments())), 1)

    def test_duplicate_uid_response_creates_one_message_within_acquisition(self):
        class DuplicateUidClient(FakeImapClient):
            def uid(self, command: str, *args):
                if command.casefold() == "search":
                    return "OK", [b"41 41"]
                return super().uid(command, *args)

        result = acquire_imap_archive(
            settings("INBOX"),
            client_factory=DuplicateUidClient,
            acquired_at="2026-08-01T12:00:00Z",
            acquisition_id="IMAP-0123456789ABCDEF01234567",
        )
        self.assertEqual(len(result.manifest["messages"]), 1)
        self.assertEqual(result.manifest["messages"][0]["uid"], "41")

    def test_document_projection_attachment_graph_and_promotion_reuse(self):
        clients: list[FakeImapClient] = []

        def factory(value):
            client = FakeImapClient(value)
            clients.append(client)
            return client

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = acquire_imap_document(
                settings("INBOX"),
                title="IMAP evidence acquisition",
                institution_source="Example Institution",
                document_date="2026-08-01",
                category="Email archive",
                description="Explicit governed IMAP snapshot.",
                visibility="private",
                notes="Administrative acquisition.",
                actor="admin-user",
                root=root,
                client_factory=factory,
                acquired_at="2026-08-01T12:00:00Z",
                acquisition_id="IMAP-0123456789ABCDEF01234567",
            )
            document_id = result["document"]["intake_id"]
            document = load_pending_document(document_id, root=root)
            projection = load_archive_projection(document_id, root=root)
            attachments = list_outlook_attachments(document_id, root=root)
            self.assertEqual(document["document_type"], "imap_acquisition")
            self.assertEqual(document["status"], "pending")
            self.assertEqual(document["imap_acquisition_metadata"]["acquisition_progress"], 100)
            self.assertEqual(projection["statistics"]["message_count"], 2)
            self.assertEqual(len(attachments), 1)
            self.assertEqual(attachments[0]["provenance"]["archive_source"], "imap_acquisition")

            message = projection["messages"][0]
            context = validate_archive_message_promotion(
                document_id, message["projection_id"], root=root
            )
            provenance = build_outlook_message_promotion_provenance(
                context, administrator="admin-user"
            )
            self.assertEqual(provenance["archive_source"], "imap_acquisition")
            self.assertEqual(provenance["imap_uid"], message["source_uid"])
            attachment_context = validate_archive_attachment_promotion(
                document_id, attachments[0]["attachment_id"], root=root
            )
            self.assertEqual(
                attachment_context.message_context.message["projection_id"],
                attachments[0]["provenance"]["message_projection_id"],
            )

            graph = build_imap_acquisition_relationship_graph(document, projection, attachments)
            node_types = {node["type"] for node in graph["nodes"]}
            relationships = {edge["relationship_type"] for edge in graph["edges"]}
            self.assertTrue({"IMAP Acquisition", "Folder", "Thread", "Email", "Attachment"}.issubset(node_types))
            self.assertIn("Contains", relationships)
            self.assertIn("Has Attachment", relationships)

            persisted = json.dumps(
                {
                    "document": document,
                    "projection": projection,
                    "attachments": attachments,
                    "graph": graph,
                },
                sort_keys=True,
            )
            self.assertNotIn("stage41-super-secret", persisted)
            self.assertNotIn("private-login@example.test", persisted)
            public_html = documents._render_imap_acquisition_document(document)
            self.assertIn("IMAP Acquisition Overview", public_html)
            self.assertNotIn("imap.example.test", public_html)
            self.assertNotIn("Governed Research Mailbox", public_html)
            self.assertNotIn("INBOX", public_html)
            self.assertNotIn("First IMAP message", public_html)

    def test_summary_api_requires_administrator_session(self):
        with self.assertRaises(HTTPException) as raised:
            admin_imap_acquisition_summary_api("0" * 64, FakeRequest(cookies={}))
        self.assertEqual(raised.exception.status_code, 401)

    def test_tampered_message_fails_archive_validation(self):
        result, _ = self.acquire("INBOX")
        source = BytesIO(result.archive_bytes)
        target = BytesIO()
        with zipfile.ZipFile(source) as original, zipfile.ZipFile(
            target, "w", compression=zipfile.ZIP_STORED
        ) as modified:
            for name in original.namelist():
                data = original.read(name)
                if name.endswith(".eml"):
                    data += b"tampered"
                modified.writestr(name, data)
        with self.assertRaisesRegex(ImapAcquisitionError, "imap_acquisition_message_size_invalid"):
            validate_imap_acquisition_archive(target.getvalue())


if __name__ == "__main__":
    unittest.main()
