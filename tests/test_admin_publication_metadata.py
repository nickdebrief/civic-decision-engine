import hashlib
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from api.document_intake import store_pending_document, update_intake_status
from tests.test_admin_session import FakeHTTPException, FakeRequest, install_fastapi_stubs


install_fastapi_stubs()

from api.routes import admin_session


PDF_BYTES = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF\n"
SENTINELS = (
    "private-note-sentinel",
    "correspondent-identity-sentinel",
    "message-body-sentinel",
    "attachment-name-sentinel",
    "storage-path-sentinel",
    "lifecycle-rationale-sentinel",
)


class AdminPublicationMetadataTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "pending"
        self.db_path = Path(self.temp_dir.name) / "records.db"
        sqlite3.connect(self.db_path).close()
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
        self.original_db_path = admin_session.DB_PATH
        admin_session.DB_PATH = self.db_path
        session = admin_session.create_admin_session("admin-user")
        self.request = FakeRequest(
            cookies={admin_session.SESSION_COOKIE_NAME: session}
        )

    def tearDown(self):
        admin_session.DB_PATH = self.original_db_path
        self.env.stop()
        self.temp_dir.cleanup()

    def _published_synthetic_document(self):
        item = store_pending_document(
            data=PDF_BYTES,
            original_filename="synthetic.pdf",
            content_type="application/pdf",
            title="Synthetic publication metadata fixture",
            institution_source="Synthetic test institution",
            document_date="2026-11-14",
            category="Synthetic",
            description=SENTINELS[2],
            visibility="private",
            notes=SENTINELS[0],
            reference_identifier="SYNTH-001",
            uploaded_at="2026-11-14T10:00:00Z",
            root=self.root,
        )
        intake_id = item["intake_id"]
        for status, changed_at in (
            ("under_review", "2026-11-14T10:01:00Z"),
            ("approved", "2026-11-14T10:02:00Z"),
            ("published", "2026-11-14T10:03:00Z"),
        ):
            update_intake_status(
                intake_id,
                status,
                actor="admin-user",
                actor_role="admin",
                note=SENTINELS[5],
                changed_at=changed_at,
                root=self.root,
                lifecycle_db_path=self.db_path,
            )

        metadata_path = self.root / intake_id / "metadata.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata.update(
            {
                "correspondent_identity": SENTINELS[1],
                "attachment_filename": SENTINELS[3],
                "proposed_storage_location": SENTINELS[4],
                "private_original_source_media": {"subtype": "not-private-source"},
            }
        )
        metadata_path.write_text(
            json.dumps(metadata, sort_keys=True), encoding="utf-8"
        )
        return intake_id, metadata_path

    def test_admin_response_is_scalar_allowlist_and_read_only(self):
        intake_id, metadata_path = self._published_synthetic_document()
        metadata_before = metadata_path.read_bytes()
        database_before = self.db_path.read_bytes()

        response = admin_session.admin_document_publication_metadata(
            intake_id, self.request
        )

        self.assertEqual(
            set(response),
            {
                "document_identifier",
                "document_type",
                "publication_lifecycle_state",
                "publication_decision_key",
                "publication_decision_timestamp",
                "publication_decision_actor",
                "publication_decision_actor_role",
                "source_sha256",
                "visibility",
                "private_original_source_media",
                "authority_reference",
                "original_mbox_publication_scope",
                "publication_policy_identifier",
                "limitations",
            },
        )
        self.assertTrue(
            all(
                isinstance(value, dict) and set(value).issubset({"state", "value", "basis"})
                for key, value in response.items()
                if key != "limitations"
            )
        )
        self.assertEqual(response["publication_lifecycle_state"]["value"], "published")
        self.assertEqual(response["publication_decision_actor"]["value"], "admin-user")
        self.assertEqual(response["publication_decision_actor_role"]["value"], "admin")
        self.assertEqual(response["source_sha256"]["value"], hashlib.sha256(PDF_BYTES).hexdigest())
        self.assertEqual(response["private_original_source_media"], {"state": "recorded", "value": False})
        for field in (
            "authority_reference",
            "original_mbox_publication_scope",
            "publication_policy_identifier",
        ):
            self.assertEqual(response[field], {"state": "not_recorded"})
        serialized = json.dumps(response, sort_keys=True)
        for sentinel in SENTINELS:
            self.assertNotIn(sentinel, serialized)
        self.assertEqual(metadata_path.read_bytes(), metadata_before)
        self.assertEqual(self.db_path.read_bytes(), database_before)

    def test_admin_detail_links_to_metadata_by_internal_intake_id(self):
        intake_id, metadata_path = self._published_synthetic_document()
        item = json.loads(metadata_path.read_text(encoding="utf-8"))
        item["intake_id"] = "a" * 64
        item["sha256_hash"] = "b" * 64
        item["document_identifier"] = "DOC-2026-000754"

        content = admin_session._render_document_intake_preview(
            item, lifecycle_events=[]
        )

        expected_href = f'/admin/documents/{item["intake_id"]}/publication-metadata'
        self.assertIn("View Publication Metadata", content)
        self.assertIn(expected_href, content)
        self.assertNotIn(
            f'/admin/documents/{item["document_identifier"]}/publication-metadata',
            content,
        )
        self.assertNotIn(
            f'/admin/documents/{item["sha256_hash"]}/publication-metadata',
            content,
        )

    def test_endpoint_denies_unauthenticated_and_non_admin_requests(self):
        intake_id, _ = self._published_synthetic_document()
        with self.assertRaises(FakeHTTPException) as unauthenticated:
            admin_session.admin_document_publication_metadata(intake_id, FakeRequest())
        self.assertEqual(unauthenticated.exception.status_code, 401)

        with patch.object(
            admin_session,
            "require_admin_session",
            return_value={"username": "viewer", "role": "viewer"},
        ):
            with self.assertRaises(FakeHTTPException) as non_admin:
                admin_session.admin_document_publication_metadata(
                    intake_id, self.request
                )
        self.assertEqual(non_admin.exception.status_code, 401)

        valid_session = self.session_token("admin-user", now=1_700_000_000)
        tampered_session = valid_session[:-1] + ("a" if valid_session[-1] != "a" else "b")
        for session in ("malformed", tampered_session, self.session_token("admin-user", now=0)):
            with self.assertRaises(FakeHTTPException) as rejected:
                admin_session.admin_document_publication_metadata(
                    intake_id,
                    FakeRequest(cookies={admin_session.SESSION_COOKIE_NAME: session}),
                )
            self.assertEqual(rejected.exception.status_code, 401)

    @staticmethod
    def session_token(username, *, now):
        return admin_session.create_admin_session(username, now=now)

    def test_missing_document_is_safe_and_evidence_states_are_validated(self):
        with self.assertRaises(FakeHTTPException) as missing:
            admin_session.admin_document_publication_metadata("a" * 64, self.request)
        self.assertEqual(missing.exception.status_code, 404)
        self.assertEqual(missing.exception.detail, "document_intake_not_found")

        self.assertEqual(
            admin_session._publication_metadata_evidence("recorded", value="synthetic"),
            {"state": "recorded", "value": "synthetic"},
        )
        self.assertEqual(
            admin_session._publication_metadata_evidence(
                "disputed", basis="governance-record-1"
            ),
            {"state": "disputed", "basis": "governance-record-1"},
        )
        with self.assertRaises(ValueError):
            admin_session._publication_metadata_evidence("not_recorded", value="x")
        with self.assertRaises(ValueError):
            admin_session._publication_metadata_evidence("not_applicable")

    def test_private_source_indicator_is_a_boolean_not_source_metadata(self):
        response = admin_session._publication_metadata_projection(
            {
                "document_identifier": "DOC-SYNTHETIC-001",
                "document_type": "mbox",
                "status": "published",
                "sha256_hash": "a" * 64,
                "visibility": "private",
                "private_original_source_media": {
                    "subtype": "private_original_source_media",
                    "storage_path": "storage-path-sentinel",
                    "reason": "private-note-sentinel",
                },
            },
            [],
        )
        self.assertEqual(
            response["private_original_source_media"],
            {"state": "recorded", "value": True},
        )
        serialized = json.dumps(response, sort_keys=True)
        self.assertNotIn("storage-path-sentinel", serialized)
        self.assertNotIn("private-note-sentinel", serialized)

    def test_later_nonpublication_state_does_not_expose_stale_decision(self):
        response = admin_session._publication_metadata_projection(
            {"document_identifier": "DOC-SYNTHETIC-002", "document_type": "pdf", "status": "archived", "sha256_hash": "b" * 64, "visibility": "private"},
            [{"new_status": "published", "decision_key": "historical-key", "decided_at": "2026-01-01T00:00:00Z", "actor": "actor", "actor_role": "admin"}],
        )
        for field in ("publication_decision_key", "publication_decision_timestamp", "publication_decision_actor", "publication_decision_actor_role"):
            self.assertEqual(response[field], {"state": "not_applicable", "basis": "current_lifecycle_not_published"})

    def test_lifecycle_reader_failure_is_content_free(self):
        intake_id, _ = self._published_synthetic_document()
        for error in (sqlite3.Error("private-note-sentinel"), OSError("private-note-sentinel")):
            with patch.object(admin_session, "list_lifecycle_decisions", side_effect=error):
                with self.assertRaises(FakeHTTPException) as failure:
                    admin_session.admin_document_publication_metadata(intake_id, self.request)
            self.assertEqual(failure.exception.status_code, 503)
            self.assertEqual(failure.exception.detail, "publication_metadata_unavailable")

    def test_malformed_lifecycle_rows_are_ignored_without_disclosure(self):
        response = admin_session._publication_metadata_projection(
            {"document_identifier": "DOC-SYNTHETIC-003", "document_type": "pdf", "status": "published", "sha256_hash": "c" * 64, "visibility": "private"},
            [None, "private-note-sentinel", {"new_status": 4}, {"new_status": "published"}],
        )
        self.assertEqual(response["publication_decision_key"], {"state": "unavailable"})
        self.assertNotIn("private-note-sentinel", json.dumps(response, sort_keys=True))


if __name__ == "__main__":
    unittest.main()
