import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from api.document_intake import store_pending_document, update_intake_status
from api.mailbox_relationship_graph import MailboxGraphFilters, build_mailbox_relationship_graph
from tests.test_admin_session import install_fastapi_stubs

install_fastapi_stubs()

from api.routes import documents


def mailbox_message(
    *,
    sender: str,
    recipient: str,
    subject: str,
    message_id: str,
    date: str = "Tue, 21 Jul 2026 10:30:00 +0000",
    cc: str = "Case Officer <case.officer@example.test>",
    in_reply_to: str = "",
    references: str = "",
    body: str = "CASE-2026-MCI-001 and REF-MCI-64 are mentioned in the preserved message body.",
) -> bytes:
    optional_headers = ""
    if in_reply_to:
        optional_headers += f"In-Reply-To: {in_reply_to}\n"
    if references:
        optional_headers += f"References: {references}\n"
    return f"""From: {sender}
To: {recipient}
Cc: {cc}
Subject: {subject}
Date: {date}
Message-ID: {message_id}
{optional_headers}MIME-Version: 1.0
Content-Type: text/plain; charset=utf-8

{body}
""".encode("utf-8")


def attachment_message() -> bytes:
    return b"""From: Attachment Sender <attachments@example.test>
To: Alice Advocate <alice@example.test>
Subject: CASE-2026-MCI-001 attachment reuse
Date: Tue, 21 Jul 2026 12:30:00 +0000
Message-ID: <case-attachment@example.test>
MIME-Version: 1.0
Content-Type: multipart/mixed; boundary="MIXED"

--MIXED
Content-Type: text/plain; charset=utf-8

Attachment metadata only.
--MIXED
Content-Type: application/pdf
Content-Disposition: attachment; filename="shared-reference.pdf"
Content-ID: <shared-attachment>

%PDF-bytes
--MIXED--
"""


def mbox(*messages: bytes) -> bytes:
    separators = [
        b"From alice@example.test Tue Jul 21 10:30:00 2026\n",
        b"From brendan@example.test Tue Jul 21 11:30:00 2026\n",
        b"From attachments@example.test Tue Jul 21 12:30:00 2026\n",
    ]
    chunks: list[bytes] = []
    for index, message in enumerate(messages):
        chunks.append(separators[index % len(separators)])
        chunks.append(message)
    return b"".join(chunks)


class MailboxRelationshipGraphTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "pending"
        self.env = patch.dict(
            os.environ,
            {
                "ADMIN_USERNAME": "graph-admin",
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

    def _publish(self, item):
        for status, timestamp in (
            ("under_review", "2026-07-27T11:00:00Z"),
            ("approved", "2026-07-27T12:00:00Z"),
            ("published", "2026-07-27T13:00:00Z"),
        ):
            item = update_intake_status(
                item["intake_id"],
                status,
                actor="graph-admin",
                note=f"{status} note",
                changed_at=timestamp,
                root=self.root,
            )
        return item

    def _store_mailbox(self, data: bytes | None = None, **overrides):
        values = {
            "data": data
            or mbox(
                mailbox_message(
                    sender="Alice Advocate <alice@example.test>",
                    recipient="Medical Council <records@medical.example.test>",
                    subject="CASE-2026-MCI-001 initial complaint REF-MCI-64",
                    message_id="<case-root@example.test>",
                ),
                mailbox_message(
                    sender="Brendan Conroy <brendan@example.test>",
                    recipient="Alice Advocate <alice@example.test>",
                    subject="Re: CASE-2026-MCI-001 initial complaint REF-MCI-64",
                    message_id="<case-reply@example.test>",
                    in_reply_to="<case-root@example.test>",
                    references="<case-root@example.test>",
                ),
                attachment_message(),
            ),
            "original_filename": "relationship-mailbox.mbox",
            "content_type": "application/mbox",
            "title": "CASE-2026-MCI-001 Relationship Mailbox",
            "institution_source": "Medical Council of Ireland",
            "document_date": "2026-07-27",
            "category": "Mailbox Archive",
            "description": "Mailbox archive for CASE-2026-MCI-001 and REF-MCI-64.",
            "visibility": "private",
            "notes": "CDE Platform Stage 38 relationship graph fixture.",
            "reference_identifier": "CASE-2026-MCI-001",
            "keywords": "relationship graph, CASE-2026-MCI-001, REF-MCI-64",
            "actor": "graph-admin",
            "uploaded_at": "2026-07-27T10:00:00Z",
            "root": self.root,
        }
        values.update(overrides)
        return store_pending_document(**values)

    def test_relationship_extraction_builds_required_node_and_edge_types(self):
        item = self._publish(self._store_mailbox())
        graph = build_mailbox_relationship_graph([item])

        node_types = {node["type"] for node in graph["nodes"]}
        edge_types = {edge["relationship_type"] for edge in graph["edges"]}

        self.assertTrue(
            {
                "Email",
                "Person",
                "Institution",
                "Case",
                "Reference Number",
                "Attachment",
                "Intake Record",
            }.issubset(node_types)
        )
        self.assertTrue(
            {
                "Sent By",
                "Sent To",
                "CC",
                "Replies To",
                "References",
                "Attached To",
                "Belongs To Case",
                "Created Intake",
                "Mentions Reference",
                "Related Communication",
            }.issubset(edge_types)
        )
        self.assertTrue(any(node["label"] == "shared-reference.pdf" for node in graph["nodes"]))

    def test_weighting_reply_chain_and_deterministic_ordering(self):
        item = self._publish(self._store_mailbox())
        first = build_mailbox_relationship_graph([item])
        second = build_mailbox_relationship_graph([item])

        self.assertEqual(first, second)
        reply_edges = [edge for edge in first["edges"] if edge["relationship_type"] == "Replies To"]
        self.assertTrue(reply_edges)
        self.assertGreaterEqual(reply_edges[0]["weight"], 6)

    def test_api_response_filters_graph_by_person_institution_case_reference_and_status(self):
        item = self._publish(self._store_mailbox())
        other = self._publish(
            self._store_mailbox(
                mbox(
                    mailbox_message(
                        sender="Other Sender <other@example.test>",
                        recipient="Unrelated Recipient <unrelated@example.test>",
                        subject="Unrelated mailbox",
                        message_id="<other@example.test>",
                        body="No shared relationship references.",
                    )
                ),
                title="Unrelated Mailbox",
                institution_source="Other Institution",
                reference_identifier="CASE-OTHER-001",
                original_filename="other-mailbox.mbox",
            )
        )
        graph = documents.mailbox_relationship_graph(
            document=item["intake_id"],
            institution="Medical Council",
            person="Alice",
            case_="CASE-2026-MCI-001",
            reference="REF-MCI-64",
            status="parsed",
        )

        self.assertIn("nodes", graph)
        self.assertIn("edges", graph)
        self.assertTrue(graph["nodes"])
        labels = {node["label"] for node in graph["nodes"]}
        self.assertIn("Medical Council of Ireland", labels)
        self.assertNotIn("Other Institution", labels)
        self.assertNotEqual(item["intake_id"], other["intake_id"])

    def test_api_supports_incremental_loading_for_large_mailboxes(self):
        messages = [
            mailbox_message(
                sender=f"Sender {index} <sender{index}@example.test>",
                recipient="Archive Reader <reader@example.test>",
                subject=f"CASE-2026-MCI-001 generated message {index}",
                message_id=f"<generated-{index}@example.test>",
            )
            for index in range(35)
        ]
        item = self._publish(self._store_mailbox(mbox(*messages)))

        graph = build_mailbox_relationship_graph(
            [item],
            filters=MailboxGraphFilters(document=item["intake_id"], offset=5, limit=10),
        )
        email_nodes = sorted(
            [node for node in graph["nodes"] if node["type"] == "Email"],
            key=lambda node: int(node["metadata"]["message_index"]),
        )

        self.assertEqual(len(email_nodes), 10)
        self.assertEqual(email_nodes[0]["metadata"]["message_index"], 6)
        self.assertEqual(email_nodes[-1]["metadata"]["message_index"], 15)

    def test_public_mailbox_page_exposes_relationship_graph_tab_and_controls(self):
        item = self._publish(self._store_mailbox())
        page = documents.public_document_page(item["intake_id"]).content

        self.assertIn("CDE Platform Stage 38 — Mailbox Relationship Graph", page)
        self.assertIn('href="#mailbox-relationship-graph">Relationship Graph</a>', page)
        self.assertIn(f'data-mailbox-graph-endpoint="/api/mailbox/graph?document={item["intake_id"]}"', page)
        self.assertIn('id="mailbox-relationship-graph-canvas"', page)
        self.assertIn('id="mailbox-graph-fit"', page)
        self.assertIn("DOMContentLoaded", page)
        self.assertIn("window.location.href = node.metadata.url", page)


if __name__ == "__main__":
    unittest.main()
