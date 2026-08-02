import asyncio
import hashlib
import json
import os
import sqlite3
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

from api.document_intake import store_pending_document, update_intake_status
from api import canonical_record_types
from api import archive_collection_memberships
from api import record_indexing
from tests.test_admin_session import FakeHTTPException, FakeRequest, install_fastapi_stubs

install_fastapi_stubs()

from api import record_document_associations as associations
from api.routes import admin_session, documents, records


PDF_BYTES = b"%PDF-1.7\ncanonical-record-types\n%%EOF\n"


class SimpleRecordResponse:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)
        self.content = kwargs


class CanonicalRecordTypesTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "pending"
        self.db_path = Path(self.temp_dir.name) / "records.db"
        self.env = patch.dict(
            os.environ,
            {
                "ADMIN_USERNAME": "admin-user",
                "ADMIN_PASSWORD": "admin-password",
                "CDE_ADMIN_SESSION_SECRET": "session-secret",
                "CDE_DOCUMENT_INTAKE_ROOT": str(self.root),
                "RECORDS_DB_PATH": str(self.db_path),
            },
            clear=False,
        )
        self.env.start()
        self.original_admin_db = admin_session.DB_PATH
        self.original_records_db = records.DB_PATH
        self.original_association_db = associations.DB_PATH
        self.original_record_response = records.RecordResponse
        admin_session.DB_PATH = self.db_path
        records.DB_PATH = self.db_path
        records.RecordResponse = SimpleRecordResponse
        associations.DB_PATH = self.db_path
        self._init_legacy_records_db()
        self.document_id = self._published_document(
            reference="NM-EVID-PKG-20191202-001"
        )
        session = admin_session.create_admin_session("admin-user")
        self.request = FakeRequest(cookies={admin_session.SESSION_COOKIE_NAME: session})

    def tearDown(self):
        admin_session.DB_PATH = self.original_admin_db
        records.DB_PATH = self.original_records_db
        records.RecordResponse = self.original_record_response
        associations.DB_PATH = self.original_association_db
        self.env.stop()
        self.temp_dir.cleanup()

    def _init_legacy_records_db(self):
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
        self._insert_legacy_record(
            conn,
            "Strike-LA-20260606-038",
            "Trajectory recorded as stable.",
            trajectory="Stable",
            system_state="Stable public record system state.",
        )
        conn.commit()
        conn.close()

    def _insert_legacy_record(
        self,
        conn,
        reference,
        finding,
        *,
        trajectory,
        system_state,
    ):
        digest = records.compute_verification_hash(
            reference,
            "2026-07-01T09:00:00Z",
            finding,
            trajectory,
            ["PUBLIC_ACCOUNTABILITY"],
            system_state,
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
                reference,
                "2026-07-01T09:00:00Z",
                trajectory,
                system_state,
                json.dumps(["PUBLIC_ACCOUNTABILITY"]),
                "[]",
                finding,
                "{}",
                digest,
                "2026-07-01T10:00:00Z",
            ),
        )

    def _published_document(self, *, reference):
        item = store_pending_document(
            data=PDF_BYTES,
            original_filename="initial-complaint-evidence-package.pdf",
            content_type="application/pdf",
            title="Initial Complaint Evidence Package - Medical Council of Ireland",
            institution_source="Medical Council of Ireland",
            document_date="2019-12-02",
            category="Evidence Package",
            description="Published document for canonical complaint association.",
            visibility="private",
            notes="Private administrative notes.",
            reference_identifier=reference,
            actor="admin-user",
            uploaded_at="2026-07-16T10:00:00Z",
            root=self.root,
        )
        for status, timestamp, note in (
            ("under_review", "2026-07-16T11:00:00Z", "Review started."),
            ("approved", "2026-07-16T12:00:00Z", "Approved."),
            ("published", "2026-07-16T13:00:00Z", "Published."),
        ):
            update_intake_status(
                item["intake_id"],
                status,
                actor="admin-user",
                note=note,
                changed_at=timestamp,
                root=self.root,
            )
        return item["intake_id"]

    def _complaint_payload(self, **overrides):
        payload = {
            "reference": "CMP-MC-20191202-001",
            "record_type": "complaint",
            "generated_at": "2019-12-02T09:00:00Z",
            "trajectory": "Submitted",
            "system_state": "Formal complaint submitted.",
            "conditions": ["FORMAL_COMPLAINT_SUBMITTED"],
            "signals": ["INITIAL_EVIDENCE_PACKAGE_PRESENT"],
            "finding": (
                "Formal complaint submitted to the Medical Council of Ireland "
                "on 2 December 2019."
            ),
            "report": {"summary": "Initial complaint record."},
            "language": "en",
            "source_narrative": (
                "Formal complaint submitted to the Medical Council of Ireland "
                "on 2 December 2019, accompanied by supporting material."
            ),
        }
        payload.update(overrides)
        return SimpleNamespace(**payload)

    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        associations.ensure_association_tables(conn)
        return conn

    def _create_complaint_record(self):
        return asyncio.run(records.create_record(self._complaint_payload()))

    def test_legacy_records_without_record_type_behave_as_strike(self):
        conn = self._conn()
        try:
            records.ensure_record_type_column(conn)
            records.ensure_record_type_column(conn)
            row = conn.execute(
                "SELECT record_type FROM records WHERE reference = ?",
                ("Strike-LA-20260606-038",),
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(row["record_type"], "strike")

        response = asyncio.run(records.api_records_index(record_type="strike"))
        self.assertEqual(response.content["records"][0]["record_type"], "strike")
        self.assertEqual(response.content["records"][0]["record_type_label"], "Strike")
        page = asyncio.run(records.verify_record("Strike-LA-20260606-038")).content
        self.assertIn("Record Type", page)
        self.assertIn("Strike", page)

    def test_complaint_record_can_be_created_and_hash_semantics_are_unchanged(self):
        response = self._create_complaint_record()
        self.assertEqual(response.reference, "CMP-MC-20191202-001")
        self.assertEqual(response.content["record_type"], "complaint")

        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT * FROM records WHERE reference = ? AND is_latest = 1",
                ("CMP-MC-20191202-001",),
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(row["record_type"], "complaint")
        expected_hash = records.compute_verification_hash(
            row["reference"],
            row["generated_at"],
            row["finding"],
            row["trajectory"],
            json.loads(row["conditions_json"]),
            row["system_state"],
            row["generated_by"],
        )
        self.assertEqual(row["verification_hash"], expected_hash)

    def test_clinical_record_type_enum_and_selector_order(self):
        expected_clinical_types = {
            "clinical_episode": "Clinical Episode",
            "medical_event": "Medical Event",
            "treatment_episode": "Treatment Episode",
            "care_episode": "Care Episode",
            "clinical_record": "Clinical Record",
        }
        self.assertEqual(
            {
                member.value: canonical_record_types.RECORD_TYPE_LABELS[member.value]
                for member in (
                    canonical_record_types.CanonicalRecordType.CLINICAL_EPISODE,
                    canonical_record_types.CanonicalRecordType.MEDICAL_EVENT,
                    canonical_record_types.CanonicalRecordType.TREATMENT_EPISODE,
                    canonical_record_types.CanonicalRecordType.CARE_EPISODE,
                    canonical_record_types.CanonicalRecordType.CLINICAL_RECORD,
                )
            },
            expected_clinical_types,
        )
        self.assertEqual(records.RECORD_TYPE_LABELS, canonical_record_types.RECORD_TYPE_LABELS)
        self.assertEqual(record_indexing.RECORD_TYPE_LABELS, records.RECORD_TYPE_LABELS)
        self.assertEqual(
            archive_collection_memberships.RECORD_TYPE_LABELS,
            records.RECORD_TYPE_LABELS,
        )

        options = admin_session._record_type_options("clinical_record")
        ordered_values = [f'value="{value}"' for value in records.RECORD_TYPE_LABELS]
        positions = [options.index(value) for value in ordered_values]
        self.assertEqual(positions, sorted(positions))
        for value, label in expected_clinical_types.items():
            self.assertIn(f'value="{value}"', options)
            self.assertIn(f">{label}</option>", options)
        self.assertIn('value="clinical_record" selected', options)
        self.assertLess(
            options.index('value="administrative_action"'),
            options.index('value="clinical_episode"'),
        )
        self.assertLess(
            options.index('value="clinical_record"'),
            options.index('value="public_submission"'),
        )

        page = admin_session.admin_canonical_record_from_document_page(
            self.document_id, self.request
        ).content
        for label in expected_clinical_types.values():
            self.assertIn(f">{label}</option>", page)
        self.assertIn('value="complaint" selected', page)

    def test_clinical_record_types_create_update_filter_and_serialize(self):
        expected_hash = None
        for index, record_type in enumerate(
            (
                "clinical_episode",
                "medical_event",
                "treatment_episode",
                "care_episode",
                "clinical_record",
            ),
            start=1,
        ):
            reference = f"CLIN-MC-20260802-{index:03d}"
            response = asyncio.run(
                records.create_record(
                    self._complaint_payload(
                        reference=reference,
                        record_type=record_type,
                        generated_at=f"2026-08-02T09:{index:02d}:00Z",
                    )
                )
            )
            self.assertEqual(response.content["record_type"], record_type)
            self.assertEqual(response.content["version"], 1)
            if record_type == "medical_event":
                expected_hash = response.content["verification_hash"]

        indexed = asyncio.run(records.api_records_index(record_type="medical_event"))
        self.assertEqual(len(indexed.content["records"]), 1)
        self.assertEqual(indexed.content["records"][0]["record_type"], "medical_event")
        self.assertEqual(
            indexed.content["records"][0]["record_type_label"], "Medical Event"
        )
        filtered = asyncio.run(records.records_index(record_type="medical_event")).content
        self.assertIn("CLIN-MC-20260802-002", filtered)
        self.assertIn("Medical Event", filtered)
        self.assertNotIn("CLIN-MC-20260802-001", filtered)

        indexed_fields = record_indexing.build_indexed_fields(
            {"reference": "CLIN-MC-20260802-002", "record_type": "medical_event"}
        )
        self.assertEqual(indexed_fields["record_type"], "medical_event")
        self.assertEqual(indexed_fields["record_type_label"], "Medical Event")

        update = asyncio.run(
            records.create_record(
                self._complaint_payload(
                    reference="CLIN-MC-20260802-002",
                    record_type="treatment_episode",
                    generated_at="2026-08-02T10:02:00Z",
                    trajectory="Treatment reviewed",
                )
            )
        )
        self.assertEqual(update.content["record_type"], "treatment_episode")
        self.assertEqual(update.content["version"], 2)
        self.assertTrue(update.content["is_superseding"])

        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT version, record_type, verification_hash, is_latest "
                "FROM records WHERE reference = ? ORDER BY version",
                ("CLIN-MC-20260802-002",),
            ).fetchall()
        finally:
            conn.close()
        self.assertEqual(
            [(row["version"], row["record_type"], row["is_latest"]) for row in rows],
            [(1, "medical_event", 0), (2, "treatment_episode", 1)],
        )
        self.assertEqual(rows[0]["verification_hash"], expected_hash)

    def test_unsupported_record_type_is_rejected(self):
        with self.assertRaises(FakeHTTPException) as ctx:
            asyncio.run(
                records.create_record(
                    self._complaint_payload(
                        reference="BAD-RECORD-TYPE-001",
                        record_type="unsupported",
                    )
                )
            )
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(ctx.exception.detail, "record_type_invalid")

    def test_record_type_is_visible_searchable_and_filterable_publicly(self):
        self._create_complaint_record()
        page = asyncio.run(records.verify_record("CMP-MC-20191202-001")).content
        self.assertIn("Record Type", page)
        self.assertIn("Complaint", page)

        index = asyncio.run(records.records_index(search="Complaint")).content
        self.assertIn("CMP-MC-20191202-001", index)
        self.assertIn("Complaint", index)

        filtered = asyncio.run(records.records_index(record_type="complaint")).content
        self.assertIn("CMP-MC-20191202-001", filtered)
        self.assertIn("Complaint", filtered)
        self.assertNotIn("Strike-LA-20260606-038", filtered)

    def test_complaint_records_are_selectable_for_record_document_association(self):
        self._create_complaint_record()
        content = admin_session.admin_association_new_page(self.request).content
        option = re_search_option(content, "CMP-MC-20191202-001")
        self.assertIn('value="CMP-MC-20191202-001"', option)
        self.assertIn(">CMP-MC-20191202-001 — Complaint — MC — Submitted</option>", option)
        self.assertIn('data-record-type="complaint"', option)
        self.assertIn("complaint", option.lower())

        before_doc = documents.public_document_page(self.document_id).content
        response = admin_session.admin_association_create(
            self.request,
            record_reference="CMP-MC-20191202-001",
            document_id=self.document_id,
            relationship_type="supporting_document",
            public_label="Initial complaint evidence package",
            public_note="Evidence package associated with the complaint record.",
            admin_note="Governed canonical record type association.",
            is_public="1",
        )
        self.assertEqual(response.status_code, 201)

        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT * FROM record_document_associations WHERE record_reference = ?",
                ("CMP-MC-20191202-001",),
            ).fetchone()
            record_hash = conn.execute(
                "SELECT verification_hash FROM records WHERE reference = ?",
                ("CMP-MC-20191202-001",),
            ).fetchone()["verification_hash"]
        finally:
            conn.close()
        self.assertEqual(row["document_id"], self.document_id)
        self.assertEqual(row["created_by"], "admin-user")
        self.assertTrue(str(row["public_reference"]).startswith("CDE-ASSOC-"))
        self.assertIn(hashlib.sha256(PDF_BYTES).hexdigest(), before_doc)
        self.assertEqual(
            record_hash,
            records.compute_verification_hash(
                "CMP-MC-20191202-001",
                "2019-12-02T09:00:00Z",
                (
                    "Formal complaint submitted to the Medical Council of Ireland "
                    "on 2 December 2019."
                ),
                "Submitted",
                ["FORMAL_COMPLAINT_SUBMITTED"],
                "Formal complaint submitted.",
            ),
        )


def re_search_option(content: str, value: str) -> str:
    needle = f'value="{value}"'
    start = content.index("<option", max(0, content.index(needle) - 160))
    end = content.index("</option>", content.index(needle)) + len("</option>")
    return content[start:end]


if __name__ == "__main__":
    unittest.main()
