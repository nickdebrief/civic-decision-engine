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
            "notes": "CDE Platform Stage 38C live inspector binding fixture.",
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

        self.assertIn("CDE Platform Stage 38C — Live Relationship Inspector Binding", page)
        self.assertIn('href="#mailbox-relationship-graph">Relationship Graph</a>', page)
        self.assertIn(f'data-mailbox-graph-endpoint="/api/mailbox/graph?document={item["intake_id"]}"', page)
        self.assertIn('id="mailbox-relationship-graph-canvas"', page)
        self.assertIn('id="mailbox-graph-fit"', page)
        self.assertIn("DOMContentLoaded", page)
        self.assertIn("Relationship Inspector", page)
        self.assertNotIn("Node Information", page)

    def test_stage38a_label_visibility_zoom_theme_and_legend_controls_render(self):
        item = self._publish(self._store_mailbox())
        page = documents.public_document_page(item["intake_id"]).content

        self.assertIn("Relationship Graph Theme", page)
        self.assertIn('value="standard" checked', page)
        self.assertIn('value="high-contrast"', page)
        self.assertIn('localStorage.setItem(THEME_STORAGE_KEY, theme)', page)
        self.assertIn("LABEL_ZOOM_THRESHOLD = 1.35", page)
        self.assertIn('text.setAttribute("class", "mailbox-graph-label")', page)
        self.assertIn('text.setAttribute("opacity", labelVisible', page)
        self.assertIn("degreeLeaders.has(node.id)", page)
        self.assertIn("mailbox-graph-hover-glow", page)
        for label in ("Person", "Institution", "Email", "Case", "Reference", "Attachment", "Intake Record"):
            self.assertIn(f"> {label}</span>", page)

    def test_stage38a_search_cluster_selection_and_keyboard_controls_render(self):
        item = self._publish(self._store_mailbox())
        page = documents.public_document_page(item["intake_id"]).content

        self.assertIn('id="mailbox-graph-search"', page)
        self.assertIn('id="mailbox-graph-search-button"', page)
        self.assertIn("function runSearch()", page)
        self.assertIn("searchMatches.add(node.id)", page)
        self.assertIn('id="mailbox-graph-cluster-mode"', page)
        self.assertIn("function expandCluster(node)", page)
        self.assertIn("node.type === \"Cluster\"", page)
        self.assertIn("function updateInfoPanel(node)", page)
        self.assertIn("Open message", page)
        self.assertIn("Filter by institution", page)
        self.assertIn("Filter by person", page)
        self.assertIn("Filter by case", page)
        self.assertIn("Filter by reference", page)
        self.assertIn("event.key === \"ArrowRight\"", page)
        self.assertIn('group.addEventListener("dblclick"', page)
        self.assertIn("nodeDragState", page)
        self.assertIn('id="mailbox-graph-reset-layout"', page)

    def test_stage38a_performance_and_theme_scope_contracts_render(self):
        item = self._publish(self._store_mailbox())
        page = documents.public_document_page(item["intake_id"]).content

        self.assertIn("layoutCache = new Map()", page)
        self.assertIn("cachedLayoutKey", page)
        self.assertIn("currentNodeSet()", page)
        self.assertIn("visibleGraph.nodes", page)
        self.assertIn('.public-mbox-relationship-graph[data-graph-theme="high-contrast"]', page)
        self.assertNotIn("body[data-graph-theme", page)

    def test_stage38c_empty_relationship_inspector_renders_without_placeholder_text(self):
        item = self._publish(self._store_mailbox())
        page = documents.public_document_page(item["intake_id"]).content

        self.assertIn('class="mailbox-graph-info-panel relationship-inspector"', page)
        self.assertIn("Click or search for any node to inspect it.", page)
        self.assertIn("The Inspector will display:", page)
        self.assertIn("<li>relationship summary</li>", page)
        self.assertIn("<li>connected entities</li>", page)
        self.assertIn("<li>metadata</li>", page)
        self.assertIn("<li>available actions</li>", page)
        self.assertNotIn("lorem", page.lower())

    def test_stage38c_node_type_inspector_fields_and_quick_actions_render(self):
        item = self._publish(self._store_mailbox())
        page = documents.public_document_page(item["intake_id"]).content

        for function_name in (
            "function metadataRows(node)",
            "function neighbourSummary(node)",
            "function quickActions(node)",
            "function bindInspectorActions(node)",
        ):
            self.assertIn(function_name, page)
        for field in (
            "Institution name",
            "Institution type",
            "Connected emails",
            "Connected people",
            "Name",
            "Emails",
            "Subject",
            "Sender",
            "Recipients",
            "Reference number",
            "Case identifier",
            "Filename",
            "Record title",
            "Publication status",
        ):
            self.assertIn(field, page)
        for action in (
            "Open related messages",
            "Highlight neighbours",
            "Filter by institution",
            "Filter by person",
            "Open message",
            "Highlight thread",
            "Show reply chain",
            "Highlight attachments",
            "Filter mailbox",
            "Highlight reuse",
            "Open record",
            "Highlight provenance",
        ):
            self.assertIn(action, page)

    def test_stage38c_uses_one_live_selection_path_for_pointer_search_keyboard_and_actions(self):
        item = self._publish(self._store_mailbox())
        page = documents.public_document_page(item["intake_id"]).content

        self.assertIn("function selectGraphNode(nodeId, selectionSource, options)", page)
        self.assertIn('selectGraphNode(node.id, "click")', page)
        self.assertIn('selectGraphNode(node.id, "pointerup")', page)
        self.assertIn('selectGraphNode(node.id, "keyboard")', page)
        self.assertIn('selectGraphNode(first.id, "search", {center: true, highlightIds})', page)
        self.assertIn('selectGraphNode(node.id, "quick-action", {center: true})', page)
        self.assertIn('selectGraphNode(memberId, "cluster-expand", {center: true})', page)
        self.assertNotIn("updateInfoPanel(selectedNode ? node : null)", page)
        self.assertNotIn("updateInfoPanel(first)", page)
        self.assertIn('group.setAttribute("aria-selected", selectedNode === node.id ? "true" : "false")', page)
        self.assertIn("Relationship Inspector selection could not resolve node", page)

    def test_stage38c_clears_only_through_explicit_stale_keyboard_or_canvas_paths(self):
        item = self._publish(self._store_mailbox())
        page = documents.public_document_page(item["intake_id"]).content

        self.assertIn('id="mailbox-graph-clear-selection"', page)
        self.assertIn('clearSelectionButton.addEventListener("click", () => clearGraphSelection("control"))', page)
        self.assertIn('clearGraphSelection("canvas")', page)
        self.assertIn('clearGraphSelection("canvas-pointerup")', page)
        self.assertIn('clearGraphSelection("keyboard")', page)
        self.assertIn('clearGraphSelection("stale")', page)
        self.assertIn("suppressNextNodeClick", page)
        self.assertIn("suppressNextCanvasClick", page)
        self.assertIn("event.stopPropagation();", page)
        self.assertIn("nodeDragMoved", page)
        self.assertIn("canvasDragMoved", page)
        self.assertNotIn('if (node.type === "Cluster") expandCluster(node);', page)

    def test_stage38c_cluster_and_common_inspector_fields_render(self):
        item = self._publish(self._store_mailbox())
        page = documents.public_document_page(item["intake_id"]).content

        for field in (
            "Stable node ID",
            "Relationship Summary",
            "Unique neighbour count",
            "Neighbour types",
            "Connected institutions",
            "Connected people",
            "Connected cases",
            "Connected references",
            "Connected attachments",
            "Cluster type",
            "Cluster size",
            "Represented node types",
            "Total internal relationships",
            "External relationships",
            "Representative nodes",
        ):
            self.assertIn(field, page)
        self.assertIn("function visibleNodeById(id)", page)
        self.assertIn("const members = node.metadata && Array.isArray(node.metadata.cluster_members)", page)

    def test_stage38c_inspector_reuses_cached_graph_payload_without_extra_api_request(self):
        item = self._publish(self._store_mailbox())
        page = documents.public_document_page(item["intake_id"]).content

        self.assertEqual(page.count("fetch(url.toString()"), 1)
        self.assertIn("const resolved = visibleNodeById(nodeId);", page)
        self.assertIn("graph.nodeMap = new Map(graph.nodes.map((node) => [node.id, node]));", page)
        self.assertIn("previousSelection && graph.nodeMap.has(previousSelection)", page)


if __name__ == "__main__":
    unittest.main()
