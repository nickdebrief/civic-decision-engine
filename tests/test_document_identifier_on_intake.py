import hashlib
import json
import os
import re
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from api import public_transmissions as transmissions
from api import record_document_associations as associations
from api.document_intake import (
    backfill_document_identifiers,
    build_document_search_text,
    find_document_by_reference,
    list_intake_documents,
    load_pending_document,
    load_published_document,
    store_pending_document,
    update_intake_notes,
    update_intake_status,
)


def pdf_bytes(label: bytes) -> bytes:
    return b"%PDF-1.7\n" + label + b"\n%%EOF\n"


class DocumentIdentifierOnIntakeTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "pending"
        self.db_path = Path(self.temp_dir.name) / "records.db"
        self.env = patch.dict(
            os.environ,
            {
                "CDE_DOCUMENT_INTAKE_ROOT": str(self.root),
                "RECORDS_DB_PATH": str(self.db_path),
                "PUBLIC_TRANSMISSIONS_DB_PATH": str(self.db_path),
            },
            clear=False,
        )
        self.env.start()
        self.original_association_db = associations.DB_PATH
        self.original_transmission_db = transmissions.DB_PATH
        associations.DB_PATH = self.db_path
        transmissions.DB_PATH = self.db_path
        self._init_records_db()

    def tearDown(self):
        associations.DB_PATH = self.original_association_db
        transmissions.DB_PATH = self.original_transmission_db
        self.env.stop()
        self.temp_dir.cleanup()

    def _init_records_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """
            CREATE TABLE records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reference TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 1,
                supersedes TEXT,
                generated_at TEXT NOT NULL,
                trajectory TEXT,
                system_state TEXT,
                conditions_json TEXT,
                signals_json TEXT,
                finding TEXT,
                report_json TEXT,
                language TEXT NOT NULL DEFAULT 'en',
                generated_by TEXT NOT NULL DEFAULT 'Civic Decision Engine',
                verification_hash TEXT NOT NULL,
                exported_at TEXT NOT NULL,
                is_latest INTEGER NOT NULL DEFAULT 1,
                source_narrative TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO records (
                reference, version, generated_at, trajectory, system_state,
                conditions_json, signals_json, finding, report_json, language,
                generated_by, verification_hash, exported_at, is_latest, source_narrative
            ) VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, 'en', 'Civic Decision Engine', ?, ?, 1, '')
            """,
            (
                "CMP-MC-20191202-001",
                "2026-07-21T09:00:00Z",
                "Stable",
                "Record system state",
                "[]",
                "[]",
                "Complaint public finding summary.",
                "{}",
                hashlib.sha256(b"record").hexdigest(),
                "2026-07-21T10:00:00Z",
            ),
        )
        conn.commit()
        conn.close()

    def _metadata(self, *, data=b"identity", reference_identifier="EXT-001", uploaded_at="2026-07-21T10:00:00Z"):
        return {
            "data": pdf_bytes(data),
            "original_filename": f"{data.decode('ascii', errors='ignore') or 'document'}.pdf",
            "content_type": "application/pdf",
            "title": f"Document {data.decode('ascii', errors='ignore') or 'identity'}",
            "institution_source": "Civic Office",
            "document_date": "2026-07-21",
            "category": "Governed Document",
            "description": "Document identifier regression fixture.",
            "visibility": "private",
            "notes": "Private notes.",
            "reference_identifier": reference_identifier,
            "actor": "admin-user",
            "uploaded_at": uploaded_at,
            "root": self.root,
        }

    def _store(self, **overrides):
        values = self._metadata(**{key: overrides.pop(key) for key in list(overrides) if key in {"data", "reference_identifier", "uploaded_at"}})
        values.update(overrides)
        return store_pending_document(**values)

    def _publish(self, item):
        for status, timestamp in (
            ("under_review", "2026-07-21T11:00:00Z"),
            ("approved", "2026-07-21T12:00:00Z"),
            ("published", "2026-07-21T13:00:00Z"),
        ):
            update_intake_status(
                item["intake_id"],
                status,
                actor="admin-user",
                note=f"Move to {status}.",
                changed_at=timestamp,
                root=self.root,
            )
        return load_pending_document(item["intake_id"], root=self.root)

    def test_identifier_is_assigned_before_initial_lifecycle_event(self):
        item = self._store()
        self.assertRegex(item["document_identifier"], r"^DOC-2026-\d{6}$")
        first_event = item["status_history"][0]
        self.assertEqual(first_event["new_status"], "pending")
        self.assertEqual(first_event["document_identifier"], item["document_identifier"])
        self.assertIn(item["document_identifier"].casefold(), build_document_search_text(item))

    def test_blank_optional_reference_identifier_remains_valid(self):
        item = self._store(data=b"blank-reference", reference_identifier="")
        self.assertIsNone(item["reference_identifier"])
        self.assertRegex(item["document_identifier"], r"^DOC-2026-\d{6}$")

    def test_identifier_is_unique_and_immutable_across_metadata_lifecycle_and_publication(self):
        first = self._store(data=b"first")
        second = self._store(data=b"second")
        self.assertNotEqual(first["document_identifier"], second["document_identifier"])
        original_identifier = first["document_identifier"]

        update_intake_notes(first["intake_id"], "Updated notes.", root=self.root)
        after_notes = load_pending_document(first["intake_id"], root=self.root)
        self.assertEqual(after_notes["document_identifier"], original_identifier)

        published = self._publish(first)
        self.assertEqual(published["document_identifier"], original_identifier)
        self.assertEqual(load_published_document(original_identifier, root=self.root)["intake_id"], first["intake_id"])

        metadata_path = self.root / first["intake_id"] / "metadata.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata["document_identifier"] = "DOC-2099-999999"
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
        repaired = update_intake_notes(first["intake_id"], "Repair attempted mutation.", root=self.root)
        self.assertEqual(repaired["document_identifier"], original_identifier)

    def test_concurrent_document_creation_does_not_reuse_identifiers(self):
        def create(index):
            return self._store(data=f"concurrent-{index}".encode("ascii"))["document_identifier"]

        with ThreadPoolExecutor(max_workers=6) as executor:
            identifiers = list(executor.map(create, range(12)))
        self.assertEqual(len(identifiers), len(set(identifiers)))
        self.assertTrue(all(re.fullmatch(r"DOC-2026-\d{6}", value) for value in identifiers))

    def test_backfill_assigns_missing_identifiers_and_preserves_existing_identifiers(self):
        legacy_bytes = pdf_bytes(b"legacy")
        legacy_digest = hashlib.sha256(legacy_bytes).hexdigest()
        legacy_dir = self.root / legacy_digest
        legacy_dir.mkdir(parents=True)
        legacy_file = legacy_dir / f"pending-{legacy_digest}.pdf"
        legacy_file.write_bytes(legacy_bytes)
        legacy_metadata = {
            "intake_id": legacy_digest,
            "status": "pending",
            "original_filename": "legacy.pdf",
            "stored_filename": legacy_file.name,
            "content_type": "application/pdf",
            "document_type": "pdf",
            "document_format": "PDF",
            "media_family": "document",
            "file_size_bytes": len(legacy_bytes),
            "sha256_hash": legacy_digest,
            "title": "Legacy document",
            "institution_source": "Civic Office",
            "document_date": "2024-01-01",
            "upload_date": "2024-01-01T00:00:00Z",
            "category": "Legacy",
            "description": "Legacy fixture.",
            "visibility": "private",
            "notes": "Legacy notes.",
            "reference_identifier": None,
            "keywords": [],
            "tags": [],
            "proposed_storage_location": str(legacy_file),
            "public_record_mutation": False,
            "status_updated_at": "2024-01-01T00:00:00Z",
            "status_history": [{"previous_status": None, "new_status": "pending", "timestamp": "2024-01-01T00:00:00Z", "actor": "legacy", "note": "Legacy import."}],
        }
        (legacy_dir / "metadata.json").write_text(json.dumps(legacy_metadata), encoding="utf-8")

        preserved_bytes = pdf_bytes(b"legacy-preserved")
        preserved_digest = hashlib.sha256(preserved_bytes).hexdigest()
        preserved_dir = self.root / preserved_digest
        preserved_dir.mkdir(parents=True)
        preserved_file = preserved_dir / f"pending-{preserved_digest}.pdf"
        preserved_file.write_bytes(preserved_bytes)
        preserved_metadata = dict(legacy_metadata)
        preserved_metadata.update(
            {
                "intake_id": preserved_digest,
                "document_identifier": "DOC-2024-000777",
                "stored_filename": preserved_file.name,
                "original_filename": "legacy-preserved.pdf",
                "sha256_hash": preserved_digest,
                "file_size_bytes": len(preserved_bytes),
                "title": "Legacy document with identifier",
                "proposed_storage_location": str(preserved_file),
            }
        )
        (preserved_dir / "metadata.json").write_text(json.dumps(preserved_metadata), encoding="utf-8")

        result = backfill_document_identifiers(root=self.root)
        self.assertEqual(result["assigned"], 1)
        self.assertEqual(result["preserved"], 1)
        legacy = load_pending_document(legacy_digest, root=self.root)
        self.assertRegex(legacy["document_identifier"], r"^DOC-2024-\d{6}$")
        self.assertEqual(load_pending_document(preserved_digest, root=self.root)["document_identifier"], "DOC-2024-000777")

    def test_association_and_transmission_use_existing_document_identifier(self):
        item = self._publish(self._store(data=b"relationship", reference_identifier="EXT-REL-001"))
        document_identifier = item["document_identifier"]
        self.assertEqual(find_document_by_reference(document_identifier, root=self.root)["intake_id"], item["intake_id"])

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            association = associations.create_association(
                conn,
                record_reference="CMP-MC-20191202-001",
                document_id=document_identifier,
                relationship_type="supporting_document",
                actor="admin-user",
                created_at="2026-07-21T14:00:00Z",
                root=self.root,
            )
            self.assertEqual(association["document_id"], item["intake_id"])
            enriched = associations.enrich_association(conn, association, root=self.root)
            self.assertEqual(enriched["document_identifier"], document_identifier)

            transmission = transmissions.create_transmission(
                conn,
                title="Transmission including existing document",
                summary="Transmission fixture.",
                sender="Sender",
                recipient="Recipient",
                transmission_date="2026-07-21",
                communication_method="email",
                publication_status="published",
                public_visibility=True,
                actor="admin-user",
                created_at="2026-07-21T15:00:00Z",
            )
            attachment = transmissions.add_transmission_attachment(
                conn,
                transmission_id=transmission["id"],
                object_type="published_document",
                object_reference=document_identifier,
                actor="admin-user",
                created_at="2026-07-21T15:10:00Z",
                root=self.root,
            )
            self.assertEqual(attachment["object_reference"], item["intake_id"])
            self.assertEqual(attachment["object_public_reference"], document_identifier)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
