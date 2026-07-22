import os
import sqlite3
import unittest
from unittest.mock import patch

from tests.test_admin_session import FakeRequest, install_fastapi_stubs
from tests import test_public_archive_explorer as archive_fixture

install_fastapi_stubs()

from api import archive_collection_memberships as acm
from api import public_transmissions as trm
from api.document_intake import store_pending_document, update_intake_status
from api.routes import admin_session, archive, collections, traceability, transmissions


class GovernedPublicTransmissionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = archive_fixture.PublicArchiveExplorerTests(
            methodName="test_landing_displays_counts_and_public_object_types"
        )
        self.fixture.setUp()
        self.original_trm_db_path = trm.DB_PATH
        trm.DB_PATH = self.fixture.db_path
        self.transmission, self.attachments = self._published_transmission_with_attachments()

    def tearDown(self):
        trm.DB_PATH = self.original_trm_db_path
        self.fixture.tearDown()

    def _conn(self):
        conn = sqlite3.connect(self.fixture.db_path)
        conn.row_factory = sqlite3.Row
        trm.ensure_transmission_tables(conn)
        acm.ensure_membership_tables(conn)
        return conn

    def _admin_request(self):
        token = admin_session.create_admin_session("admin-user")
        return FakeRequest(cookies={admin_session.SESSION_COOKIE_NAME: token})

    def _published_pdf(self, *, title: str, reference_identifier: str, suffix: bytes, uploaded_at: str):
        item = store_pending_document(
            data=b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF\n" + suffix,
            original_filename=f"{reference_identifier}.pdf",
            content_type="application/pdf",
            title=title,
            institution_source="Medical Council of Ireland",
            document_date="2026-07-24",
            category="Correspondence",
            description=f"{title} fixture.",
            visibility="private",
            notes="Private note.",
            reference_identifier=reference_identifier,
            keywords=f"{title}, Transmission Intake",
            actor="admin-user",
            uploaded_at=uploaded_at,
            root=self.fixture.root,
        )
        for index, status in enumerate(("under_review", "approved", "published"), start=1):
            item = update_intake_status(
                item["intake_id"],
                status,
                actor="admin-user",
                note=f"{status} note",
                changed_at=f"2026-07-24T08:0{index}:00Z",
                root=self.fixture.root,
            )
        return item

    def _published_transmission_with_attachments(self):
        conn = self._conn()
        try:
            transmission = trm.create_transmission(
                conn,
                title="Cover email transmitting Woodstock usage workbook",
                summary="Communication context for transmitting the governed Woodstock workbook and related public objects.",
                sender="Nick Moloney",
                recipient="Medical Council of Ireland",
                transmission_date="2026-07-24",
                communication_method="email",
                subject="Please find attached Woodstock usage workbook",
                covering_message="Please find attached the governed workbook and related public references.",
                external_reference="MSG-WOODSTOCK-20260724",
                transmission_identifier="email-woodstock-001",
                admin_notes="Private transmission note.",
                publication_status="pending",
                public_visibility=False,
                actor="admin-user",
                created_at="2026-07-24T09:00:00Z",
            )
            trm.update_transmission_status(
                conn,
                transmission["id"],
                new_status="review",
                public_visibility=False,
                actor="admin-user",
                note="Begin review.",
                updated_at="2026-07-24T09:10:00Z",
            )
            trm.update_transmission_status(
                conn,
                transmission["id"],
                new_status="approved",
                public_visibility=False,
                actor="admin-user",
                note="Approved for publication.",
                updated_at="2026-07-24T09:20:00Z",
            )
            transmission = trm.update_transmission_status(
                conn,
                transmission["id"],
                new_status="published",
                public_visibility=True,
                actor="admin-user",
                note="Declared Published.",
                updated_at="2026-07-24T09:30:00Z",
            )
            attachments = [
                trm.add_transmission_attachment(
                    conn,
                    transmission_id=transmission["id"],
                    object_type="published_document",
                    object_reference=self.fixture.document["intake_id"],
                    relationship_label="Transmitted document",
                    public_note="Workbook transmitted with the covering communication.",
                    actor="admin-user",
                    created_at="2026-07-24T09:40:00Z",
                    root=self.fixture.root,
                ),
                trm.add_transmission_attachment(
                    conn,
                    transmission_id=transmission["id"],
                    object_type="canonical_record",
                    object_reference="CMP-MC-20191202-001",
                    relationship_label="Referenced record",
                    public_note="Canonical Complaint record referenced in the communication.",
                    actor="admin-user",
                    created_at="2026-07-24T09:41:00Z",
                    root=self.fixture.root,
                ),
                trm.add_transmission_attachment(
                    conn,
                    transmission_id=transmission["id"],
                    object_type="record_document_association",
                    object_reference=self.fixture.association["public_reference"],
                    relationship_label="Referenced association",
                    public_note="Association referenced in the communication.",
                    actor="admin-user",
                    created_at="2026-07-24T09:42:00Z",
                    root=self.fixture.root,
                ),
                trm.add_transmission_attachment(
                    conn,
                    transmission_id=transmission["id"],
                    object_type="public_collection",
                    object_reference=self.fixture.collection["public_reference"],
                    relationship_label="Referenced collection",
                    public_note="Collection referenced in the communication.",
                    actor="admin-user",
                    created_at="2026-07-24T09:43:00Z",
                    root=self.fixture.root,
                ),
            ]
            return transmission, attachments
        finally:
            conn.close()

    def test_transmission_has_independent_identity_lifecycle_and_metadata(self):
        self.assertRegex(self.transmission["public_reference"], r"^TRM-2026-\d{4}$")
        self.assertEqual(self.transmission["publication_status"], "published")
        self.assertEqual(self.transmission["public_visibility"], 1)
        self.assertEqual(self.transmission["communication_method"], "email")
        self.assertEqual(trm.method_label("email"), "Email")
        self.assertEqual(trm.status_label("published"), "Published")
        self.assertIn("Please find attached", self.transmission["covering_message"])
        self.assertNotEqual(self.transmission["public_reference"], self.fixture.document["reference_identifier"])

    def test_invalid_method_and_duplicate_attachment_are_rejected(self):
        conn = self._conn()
        try:
            with self.assertRaisesRegex(ValueError, "transmission_method_invalid"):
                trm.create_transmission(
                    conn,
                    title="Invalid method",
                    summary="Invalid method test.",
                    sender="Sender",
                    recipient="Recipient",
                    transmission_date="2026-07-24",
                    communication_method="free-text-message",
                    actor="admin-user",
                )
            with self.assertRaisesRegex(ValueError, "transmission_attachment_duplicate_active"):
                trm.add_transmission_attachment(
                    conn,
                    transmission_id=self.transmission["id"],
                    object_type="published_document",
                    object_reference=self.fixture.document["intake_id"],
                    actor="admin-user",
                    root=self.fixture.root,
                )
        finally:
            conn.close()

    def test_transmission_intake_page_searches_and_selects_governed_documents(self):
        content = admin_session.admin_transmissions_page(
            self._admin_request(),
            document_search="Woodstock",
        ).content

        self.assertIn("Included Governed Documents", content)
        self.assertIn("Search published documents", content)
        self.assertIn(self.fixture.document["document_identifier"], content)
        self.assertIn("Add document", content)
        self.assertIn("Selected Documents", content)
        self.assertIn("0 documents selected", content)
        self.assertIn('id="selected-documents-count"', content)
        self.assertIn('aria-live="polite"', content)
        self.assertIn("1 document selected", content)
        self.assertIn("documents selected", content)
        self.assertIn("Document Identifiers — JavaScript unavailable", content)
        self.assertIn("<noscript>", content)
        self.assertIn("included_document_identifiers_text", content)
        self.assertIn("Remove", content)
        self.assertIn("Remove ${escapeHtml(reference)} from selected Documents", content)
        self.assertNotIn("Document Identifiers for non-JavaScript entry", content)
        self.assertIn("A Transmission references these Documents through governed inclusion relationships", content)

    def test_selected_document_input_parser_uses_one_canonical_source(self):
        attachments = admin_session._transmission_document_attachment_inputs(
            [self.fixture.document["document_identifier"]],
            ["Selected list label"],
            ["Selected list note."],
            "DOC-2026-000064\nDOC-2026-000067",
        )

        self.assertEqual(
            attachments,
            [
                {
                    "document_reference": self.fixture.document["document_identifier"],
                    "relationship_label": "Selected list label",
                    "public_note": "Selected list note.",
                }
            ],
        )

        fallback = admin_session._transmission_document_attachment_inputs(
            [],
            [],
            [],
            "DOC-2026-000064\n\n DOC-2026-000067 ",
        )

        self.assertEqual(
            fallback,
            [
                {
                    "document_reference": "DOC-2026-000064",
                    "relationship_label": "Transmitted document",
                    "public_note": "",
                },
                {
                    "document_reference": "DOC-2026-000067",
                    "relationship_label": "Transmitted document",
                    "public_note": "",
                },
            ],
        )

    def test_create_transmission_with_one_selected_document_from_intake(self):
        response = admin_session.admin_create_transmission(
            request=self._admin_request(),
            title="Cover email with one selected document",
            summary="Transmission created with a selected governed Document.",
            sender="Nick Moloney",
            recipient="Medical Council of Ireland",
            transmission_date="2026-07-24",
            communication_method="email",
            subject="One governed document",
            covering_message="Please find the governed document reference.",
            publication_status="pending",
            public_visibility="0",
            included_document_reference=[self.fixture.document["document_identifier"]],
            included_document_relationship_label=["Cover attachment"],
            included_document_public_note=["Selected during intake."],
            included_document_identifiers_text=None,
        )
        transmission_id = int(str(response.headers["Location"]).rsplit("/", 1)[1])
        conn = self._conn()
        try:
            attachments = trm.list_transmission_attachments(conn, transmission_id, root=self.fixture.root)
            history = trm.transmission_history(conn, transmission_id)
        finally:
            conn.close()

        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments[0]["object_reference"], self.fixture.document["intake_id"])
        self.assertEqual(attachments[0]["object_public_reference"], self.fixture.document["document_identifier"])
        self.assertEqual(attachments[0]["relationship_label"], "Cover attachment")
        self.assertRegex(attachments[0]["attachment_reference"], r"^TRM-ATT-\d{8}-\d{3}$")
        self.assertEqual([item["action_type"] for item in history], ["created", "attachment_added"])

    def test_create_transmission_with_multiple_selected_documents_preserves_order(self):
        second = self._published_pdf(
            title="Second governed document for transmission",
            reference_identifier="NM-TRM-DOC-002",
            suffix=b"second",
            uploaded_at="2026-07-24T08:20:00Z",
        )
        conn = self._conn()
        try:
            transmission = trm.create_transmission_with_document_attachments(
                conn,
                title="Cover email with multiple selected documents",
                summary="Transmission created with multiple governed Documents.",
                sender="Nick Moloney",
                recipient="Medical Council of Ireland",
                transmission_date="2026-07-24",
                communication_method="email",
                document_attachments=[
                    {
                        "document_reference": self.fixture.document["document_identifier"],
                        "relationship_label": "First transmitted document",
                        "public_note": "First note.",
                    },
                    {
                        "document_reference": second["document_identifier"],
                        "relationship_label": "Second transmitted document",
                        "public_note": "Second note.",
                    },
                ],
                actor="admin-user",
                created_at="2026-07-24T08:30:00Z",
                root=self.fixture.root,
            )
            attachments = trm.list_transmission_attachments(conn, transmission["id"], root=self.fixture.root)
            history = trm.transmission_history(conn, transmission["id"])
        finally:
            conn.close()

        self.assertEqual([item["position"] for item in attachments], [1, 2])
        self.assertEqual(
            [item["object_reference"] for item in attachments],
            [self.fixture.document["intake_id"], second["intake_id"]],
        )
        self.assertEqual(len({item["attachment_reference"] for item in attachments}), 2)
        self.assertEqual(
            [item["action_type"] for item in history],
            ["created", "attachment_added", "attachment_added"],
        )

    def test_no_javascript_multiline_fallback_creates_documents_in_order(self):
        second = self._published_pdf(
            title="Fallback governed document for transmission",
            reference_identifier="NM-TRM-DOC-FALLBACK",
            suffix=b"fallback",
            uploaded_at="2026-07-24T08:25:00Z",
        )
        response = admin_session.admin_create_transmission(
            request=self._admin_request(),
            title="No JavaScript fallback transmission",
            summary="Transmission created from multiline fallback Document Identifiers.",
            sender="Nick Moloney",
            recipient="Medical Council of Ireland",
            transmission_date="2026-07-24",
            communication_method="email",
            subject="Fallback governed documents",
            covering_message="Please find the governed document references.",
            publication_status="pending",
            public_visibility="0",
            included_document_reference=[],
            included_document_relationship_label=[],
            included_document_public_note=[],
            included_document_identifiers_text=(
                f"{self.fixture.document['document_identifier']}\n"
                f"{second['document_identifier']}"
            ),
        )
        transmission_id = int(str(response.headers["Location"]).rsplit("/", 1)[1])
        conn = self._conn()
        try:
            attachments = trm.list_transmission_attachments(conn, transmission_id, root=self.fixture.root)
        finally:
            conn.close()

        self.assertEqual([item["object_reference"] for item in attachments], [self.fixture.document["intake_id"], second["intake_id"]])
        self.assertEqual([item["position"] for item in attachments], [1, 2])
        self.assertEqual([item["relationship_label"] for item in attachments], ["Transmitted document", "Transmitted document"])

    def test_no_javascript_fallback_rejects_unknown_identifier_atomically(self):
        conn = self._conn()
        try:
            before = len(trm.list_transmissions(conn))
        finally:
            conn.close()

        with self.assertRaises(Exception) as raised:
            admin_session.admin_create_transmission(
                request=self._admin_request(),
                title="Rejected fallback transmission",
                summary="Unknown fallback identifier must not partially persist.",
                sender="Nick Moloney",
                recipient="Medical Council of Ireland",
                transmission_date="2026-07-24",
                communication_method="email",
                subject="Rejected governed documents",
                covering_message="Please find the governed document references.",
                publication_status="pending",
                public_visibility="0",
                included_document_reference=[],
                included_document_relationship_label=[],
                included_document_public_note=[],
                included_document_identifiers_text="DOC-2099-999999",
            )

        conn = self._conn()
        try:
            after = len(trm.list_transmissions(conn))
        finally:
            conn.close()

        self.assertIn("transmission_document_not_public", str(raised.exception))
        self.assertEqual(after, before)

    def test_duplicate_unknown_and_unpublished_selected_documents_are_rejected_atomically(self):
        unpublished = store_pending_document(
            data=b"%PDF-1.7\npending\n%%EOF\n",
            original_filename="pending.pdf",
            content_type="application/pdf",
            title="Unpublished governed document",
            institution_source="Medical Council of Ireland",
            document_date="2026-07-24",
            category="Correspondence",
            description="Pending only.",
            visibility="private",
            notes="Private note.",
            reference_identifier="NM-TRM-PENDING",
            actor="admin-user",
            uploaded_at="2026-07-24T08:40:00Z",
            root=self.fixture.root,
        )
        conn = self._conn()
        try:
            before = len(trm.list_transmissions(conn))
            cases = [
                [
                    {"document_reference": self.fixture.document["document_identifier"]},
                    {"document_reference": self.fixture.document["document_identifier"]},
                ],
                [{"document_reference": "DOC-2099-999999"}],
                [{"document_reference": unpublished["document_identifier"]}],
            ]
            for attachments in cases:
                with self.assertRaises(ValueError):
                    trm.create_transmission_with_document_attachments(
                        conn,
                        title="Rejected transmission",
                        summary="This should not persist.",
                        sender="Sender",
                        recipient="Recipient",
                        transmission_date="2026-07-24",
                        communication_method="email",
                        document_attachments=attachments,
                        actor="admin-user",
                        root=self.fixture.root,
                    )
            after = len(trm.list_transmissions(conn))
        finally:
            conn.close()

        self.assertEqual(after, before)

    def test_transmission_without_initial_documents_and_post_creation_addition_still_work(self):
        conn = self._conn()
        try:
            transmission = trm.create_transmission_with_document_attachments(
                conn,
                title="Transmission without selected documents",
                summary="No included Documents at creation remains valid.",
                sender="Sender",
                recipient="Recipient",
                transmission_date="2026-07-24",
                communication_method="email",
                document_attachments=[],
                actor="admin-user",
                root=self.fixture.root,
            )
            self.assertEqual(trm.list_transmission_attachments(conn, transmission["id"], root=self.fixture.root), [])
            attachment = trm.add_transmission_attachment(
                conn,
                transmission_id=transmission["id"],
                object_type="published_document",
                object_reference=self.fixture.document["document_identifier"],
                actor="admin-user",
                root=self.fixture.root,
            )
        finally:
            conn.close()

        self.assertEqual(attachment["object_reference"], self.fixture.document["intake_id"])

    def test_public_library_search_and_detail_render(self):
        index = transmissions.public_transmission_library(q="Nick Moloney Woodstock").content
        self.assertIn("Public Transmission Library", index)
        self.assertIn(self.transmission["public_reference"], index)
        self.assertIn("Nick Moloney", index)
        self.assertIn("Medical Council of Ireland", index)
        self.assertIn("Email", index)
        detail = transmissions.public_transmission_page(self.transmission["public_reference"]).content
        self.assertIn("Documents preserve content. Transmissions preserve context.", detail)
        self.assertIn("Covering Communication", detail)
        self.assertIn("Included Governed Objects", detail)
        self.assertIn(self.fixture.document["reference_identifier"], detail)
        self.assertIn("CMP-MC-20191202-001", detail)
        self.assertIn(self.fixture.association["public_reference"], detail)
        self.assertIn(self.fixture.collection["public_reference"], detail)
        self.assertNotIn("Private transmission note", detail)

    def test_public_archive_includes_transmission_search_result(self):
        content = archive.public_archive_explorer(search="MSG-WOODSTOCK").content
        self.assertIn("Public Transmission", content)
        self.assertIn("Open Transmission", content)
        self.assertIn(self.transmission["public_reference"], content)
        type_page = archive.public_archive_explorer(type="public_transmission").content
        self.assertIn(self.transmission["public_reference"], type_page)
        self.assertNotIn(self.fixture.association["public_reference"], type_page)

    def test_traceability_renders_transmission_as_governed_node(self):
        content = traceability.public_traceability_map(search=self.transmission["public_reference"]).content
        self.assertIn("Transmission Traceability View", content)
        self.assertIn("Public Transmission", content)
        self.assertIn("communicates", content)
        self.assertIn("Open Transmission", content)
        self.assertIn("Open Published Document", content)
        self.assertIn(self.fixture.document["reference_identifier"], content)
        self.assertIn("A Transmission governs communication context", content)

    def test_collection_can_reference_public_transmission(self):
        conn = self._conn()
        try:
            membership = acm.create_membership(
                conn,
                collection_id=self.fixture.collection["id"],
                member_type="public_transmission",
                member_reference=self.transmission["public_reference"],
                actor="admin-user",
                membership_note="Transmission member.",
                display_sequence=2,
                created_at="2026-07-24T10:00:00Z",
                root=self.fixture.root,
            )
            for status in ("reviewed", "approved", "active"):
                acm.transition_membership(
                    conn,
                    membership["membership_reference"],
                    new_status=status,
                    actor="admin-user",
                    root=self.fixture.root,
                )
        finally:
            conn.close()
        content = collections.public_collection_page(self.fixture.collection["public_reference"]).content
        self.assertIn("Public Transmission", content)
        self.assertIn(self.transmission["public_reference"], content)
        self.assertIn("does not own, contain, or absorb", content)

    def test_admin_navigation_and_management_pages_render(self):
        with patch.dict(
            os.environ,
            {
                "ADMIN_USERNAME": "admin-user",
                "ADMIN_PASSWORD": "admin-password",
                "CDE_ADMIN_SESSION_SECRET": "session-secret",
            },
            clear=False,
        ):
            session = admin_session.create_admin_session("admin-user")
            request = FakeRequest(cookies={admin_session.SESSION_COOKIE_NAME: session})
            dashboard = admin_session.admin_dashboard_page(request).content
            management = admin_session.admin_transmissions_page(request).content
            detail = admin_session.admin_transmission_detail_page(self.transmission["id"], request).content
        self.assertIn("Transmission Intake", dashboard)
        self.assertIn("Transmission Management", dashboard)
        self.assertIn("<h2>Transmissions</h2>", dashboard)
        self.assertIn("Create Public Transmission", management)
        self.assertIn(self.transmission["public_reference"], management)
        self.assertIn("Include governed public object", detail)
        self.assertIn("Transmission history", detail)

    def test_existing_document_identity_hash_and_public_object_references_are_unchanged(self):
        self.assertEqual(self.fixture.document["reference_identifier"], "NM-XLS-WOODSTOCK-2019-001")
        self.assertIn("sha256_hash", self.fixture.document)
        self.assertNotEqual(self.transmission["public_reference"], self.fixture.document["sha256_hash"])
        self.assertEqual(self.fixture.association["record_reference"], "CMP-MC-20191202-001")
        self.assertEqual(self.fixture.collection["public_reference"].startswith("CDE-COLL-"), True)


if __name__ == "__main__":
    unittest.main()
