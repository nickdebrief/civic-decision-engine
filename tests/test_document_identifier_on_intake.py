import hashlib
import json
import os
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from api import public_transmissions as trm
from api import record_document_associations as rda
from api.document_intake import (
    backfill_document_identifiers,
    build_document_search_text,
    load_pending_document,
    load_published_document,
    store_pending_document,
    update_intake_notes,
    update_intake_status,
)


PDF_BYTES = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF\n"


class DocumentIdentifierOnIntakeTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "pending"
        self.db_path = Path(self.temp_dir.name) / "records.db"
        self.env = patch.dict(
            os.environ,
            {
                "CDE_DOCUMENT_INTAKE_ROOT": str(self.root),
                "CDE_DOCUMENT_INTAKE_MAX_BYTES": "1048576",
            },
            clear=False,
        )
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp_dir.cleanup()

    def _store(self, *, data: bytes = PDF_BYTES, reference_identifier: str | None = "EXT-001"):
        return store_pending_document(
            data=data,
            original_filename="document.pdf",
            content_type="application/pdf",
            title="Governed source document",
            institution_source="Civic Office",
            document_date="2026-07-21",
            category="Evidence",
            description="Document identifier test fixture.",
            visibility="private",
            notes="Private intake note.",
            reference_identifier=reference_identifier,
            keywords=["identifier", "intake"],
            actor="admin-user",
            uploaded_at="2026-07-21T10:00:00Z",
            root=self.root,
        )

    def _publish(self, item: dict):
        intake_id = item["intake_id"]
        update_intake_status(
            intake_id,
            "under_review",
            actor="admin-user",
            note="Begin review.",
            changed_at="2026-07-21T10:10:00Z",
            root=self.root,
        )
        update_intake_status(
            intake_id,
            "approved",
            actor="admin-user",
            note="Approved.",
            changed_at="2026-07-21T10:20:00Z",
            root=self.root,
        )
        return update_intake_status(
            intake_id,
            "published",
            actor="admin-user",
            note="Declared Published.",
            changed_at="2026-07-21T10:30:00Z",
            root=self.root,
        )

    def _connection_with_public_record(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute(
            """
            CREATE TABLE records (
                reference TEXT PRIMARY KEY,
                is_latest INTEGER NOT NULL,
                record_type TEXT,
                title TEXT,
                finding TEXT,
                generated_at TEXT,
                exported_at TEXT,
                version TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO records (
                reference, is_latest, record_type, title, finding,
                generated_at, exported_at, version
            ) VALUES (?, 1, ?, ?, ?, ?, ?, ?)
            """,
            (
                "CMP-DOC-IDENTIFIER-001",
                "complaint",
                "Document Identifier Record",
                "Record linked to document identifier fixture.",
                "2026-07-21T09:00:00Z",
                "2026-07-21T09:05:00Z",
                "1",
            ),
        )
        conn.commit()
        return conn

    def test_identifier_is_assigned_before_initial_lifecycle_event(self):
        item = self._store()

        self.assertRegex(item["document_identifier"], r"^DOC-2026-\d{6}$")
        self.assertEqual(item["status"], "pending")
        self.assertEqual(
            item["status_history"][0]["document_identifier"],
            item["document_identifier"],
        )
        self.assertIn(item["document_identifier"].casefold(), build_document_search_text(item))

    def test_blank_optional_reference_identifier_remains_valid(self):
        item = self._store(reference_identifier="")
        loaded = load_pending_document(item["intake_id"], root=self.root)

        self.assertIsNone(loaded["reference_identifier"])
        self.assertRegex(loaded["document_identifier"], r"^DOC-2026-\d{6}$")

    def test_identifier_is_unique_and_immutable_across_updates_and_publication(self):
        item = self._store()
        original_identifier = item["document_identifier"]

        update_intake_notes(item["intake_id"], "Updated notes.", root=self.root)
        after_notes = load_pending_document(item["intake_id"], root=self.root)
        self.assertEqual(after_notes["document_identifier"], original_identifier)

        metadata_path = self.root / item["intake_id"] / "metadata.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata["document_identifier"] = "DOC-2099-999999"
        metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")

        published = self._publish(item)
        self.assertEqual(published["document_identifier"], original_identifier)
        self.assertEqual(
            load_published_document(original_identifier, root=self.root)["intake_id"],
            item["intake_id"],
        )

    def test_concurrent_document_creation_does_not_reuse_identifiers(self):
        def create(index: int) -> str:
            payload = f"concurrent-{index}".encode("ascii")
            return self._store(data=PDF_BYTES + payload)["document_identifier"]

        with ThreadPoolExecutor(max_workers=8) as executor:
            identifiers = list(executor.map(create, range(16)))

        self.assertEqual(len(identifiers), len(set(identifiers)))
        self.assertTrue(all(identifier.startswith("DOC-2026-") for identifier in identifiers))

    def test_backfill_assigns_missing_identifiers_and_preserves_existing_identifiers(self):
        first = self._store(data=PDF_BYTES + b"legacy-one")
        second = self._store(data=PDF_BYTES + b"legacy-two")
        preserved_identifier = "DOC-2024-000777"
        for item, identifier in ((first, ""), (second, preserved_identifier)):
            metadata_path = self.root / item["intake_id"] / "metadata.json"
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            if identifier:
                metadata["document_identifier"] = identifier
            else:
                metadata.pop("document_identifier", None)
            for event in metadata.get("status_history", []):
                event.pop("document_identifier", None)
            metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
        (self.root / ".document_identifiers.sqlite3").unlink(missing_ok=True)

        result = backfill_document_identifiers(root=self.root)

        self.assertEqual(result["scanned"], 2)
        self.assertEqual(result["assigned"], 1)
        self.assertEqual(result["preserved"], 1)
        self.assertRegex(
            load_pending_document(first["intake_id"], root=self.root)["document_identifier"],
            r"^DOC-2026-\d{6}$",
        )
        self.assertEqual(
            load_pending_document(second["intake_id"], root=self.root)["document_identifier"],
            preserved_identifier,
        )

    def test_association_and_transmission_use_existing_document_identifier(self):
        item = self._publish(self._store(reference_identifier="EXT-DOC-001"))
        conn = self._connection_with_public_record()
        try:
            association = rda.create_association(
                conn,
                record_reference="CMP-DOC-IDENTIFIER-001",
                document_id=item["document_identifier"],
                relationship_type="supporting_document",
                public_label="Supporting document",
                public_note="Uses the existing governed document.",
                admin_note="No duplicate document identity.",
                actor="admin-user",
                created_at="2026-07-21T11:00:00Z",
                root=self.root,
            )
            self.assertEqual(association["document_id"], item["intake_id"])

            transmission = trm.create_transmission(
                conn,
                title="Transmission using document identifier",
                summary="Communication context for an existing governed document.",
                sender="Civic Office",
                recipient="Public",
                transmission_date="2026-07-21",
                communication_method="email",
                subject="Existing document transmitted",
                covering_message="Please find the governed document reference.",
                publication_status="published",
                public_visibility=True,
                actor="admin-user",
                created_at="2026-07-21T11:10:00Z",
            )
            attachment = trm.add_transmission_attachment(
                conn,
                transmission_id=transmission["id"],
                object_type="published_document",
                object_reference=item["document_identifier"],
                relationship_label="Included governed object",
                actor="admin-user",
                created_at="2026-07-21T11:15:00Z",
                root=self.root,
            )
        finally:
            conn.close()

        self.assertEqual(attachment["object_reference"], item["intake_id"])
        self.assertEqual(attachment["object_public_reference"], item["document_identifier"])
        self.assertEqual(attachment["object_secondary_reference"], "EXT-DOC-001")
        self.assertEqual(
            hashlib.sha256((self.root / item["intake_id"] / item["stored_filename"]).read_bytes()).hexdigest(),
            item["sha256_hash"],
        )


if __name__ == "__main__":
    unittest.main()
