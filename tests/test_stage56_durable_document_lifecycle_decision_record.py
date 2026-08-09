import hashlib
import json
import os
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from api import document_lifecycle_events as dle
from api.document_intake import (
    load_pending_document,
    store_pending_document,
    update_intake_status,
)
from api.email_attachment_preservation import list_source_attachments
from tests.test_admin_session import FakeHTTPException, FakeRequest, install_fastapi_stubs

install_fastapi_stubs()

from api.routes import admin_session, documents


PDF_BYTES = b"%PDF-1.7\nstage-56\n%%EOF\n"
EMAIL_WITH_ATTACHMENT = b"""From: Source <source@example.test>
To: Recipient <recipient@example.test>
Subject: Stage 56 lifecycle independence
Date: Sun, 9 Aug 2026 09:00:00 +0000
Message-ID: <stage56-independence@example.test>
MIME-Version: 1.0
Content-Type: multipart/mixed; boundary="STAGE56"

--STAGE56
Content-Type: text/plain; charset=utf-8

Synthetic source email.
--STAGE56
Content-Type: application/pdf
Content-Disposition: attachment; filename="independent.pdf"
Content-Transfer-Encoding: base64

JVBERi0xLjcKc3RhZ2UtNTYtYXR0YWNobWVudAolJUVPRgo=
--STAGE56--
"""


class Stage56DurableLifecycleDecisionRecordTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base = Path(self.temp_dir.name)
        self.root = self.base / "pending"
        self.db_path = self.base / "records.db"
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
            cookies={admin_session.SESSION_COOKIE_NAME: session},
            query_params={},
        )
        self.item = self._store()

    def tearDown(self):
        admin_session.DB_PATH = self.original_db_path
        self.env.stop()
        self.temp_dir.cleanup()

    def _store(self, data=PDF_BYTES, **overrides):
        values = {
            "original_filename": "stage-56.pdf",
            "content_type": "application/pdf",
            "title": "Stage 56 governed decision",
            "institution_source": "Civic Office",
            "document_date": "2026-08-09",
            "category": "Decision",
            "description": "Synthetic lifecycle decision fixture.",
            "visibility": "private",
            "notes": "Private intake context.",
            "reference_identifier": "STAGE-56-TEST",
            "actor": "intake-admin",
            "uploaded_at": "2026-08-09T09:00:00Z",
            "root": self.root,
        }
        values.update(overrides)
        return store_pending_document(data=data, **values)

    def _transition(self, status, note=None, **overrides):
        values = {
            "actor": "admin-user",
            "actor_role": "admin",
            "note": note,
            "root": self.root,
            "lifecycle_db_path": self.db_path,
        }
        values.update(overrides)
        return update_intake_status(self.item["intake_id"], status, **values)

    def _events(self):
        return dle.list_lifecycle_decisions(
            intake_id=self.item["intake_id"], db_path=self.db_path
        )

    def _metadata_path(self):
        return self.root / self.item["intake_id"] / "metadata.json"

    def _registry_identifier(self):
        conn = sqlite3.connect(self.root / ".document_identifiers.sqlite3")
        try:
            row = conn.execute(
                "SELECT document_identifier FROM document_identifiers WHERE intake_id = ?",
                (self.item["intake_id"],),
            ).fetchone()
            return str(row[0]) if row else None
        finally:
            conn.close()

    def test_schema_initialization_is_idempotent_and_creates_no_history(self):
        for _ in range(2):
            conn = dle.get_db(self.db_path)
            conn.close()
        conn = sqlite3.connect(self.db_path)
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(document_lifecycle_decision_events)")
        }
        indexes = {
            row[1] for row in conn.execute("PRAGMA index_list(document_lifecycle_decision_events)")
        }
        count = conn.execute("SELECT COUNT(*) FROM document_lifecycle_decision_events").fetchone()[0]
        conn.close()
        self.assertEqual(count, 0)
        self.assertTrue(
            {
                "decision_key",
                "intake_id",
                "decision_sequence",
                "document_identifier",
                "previous_status",
                "new_status",
                "decided_at",
                "actor",
                "actor_role",
                "rationale",
                "sha256_hash",
                "sha512_hash",
                "digest_status",
            }.issubset(columns)
        )
        self.assertIn("idx_lifecycle_events_document_history", indexes)
        self.assertNotIn("update_lifecycle_event", dir(dle))
        self.assertNotIn("delete_lifecycle_event", dir(dle))

    def test_database_enforces_required_rationale_null_empty_and_whitespace(self):
        conn = dle.get_db(self.db_path)
        insert_sql = """
            INSERT INTO document_lifecycle_decision_events (
                decision_key, intake_id, decision_sequence, document_identifier,
                previous_status, new_status, decided_at, actor, actor_role,
                rationale, sha256_hash, sha512_hash, digest_status
            ) VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, NULL, 'recorded')
        """
        previous_states = {
            "approved": "under_review",
            "published": "approved",
            "rejected": "under_review",
            "archived": "published",
        }
        sequence = 0
        try:
            for new_status, previous_status in previous_states.items():
                for rationale in (None, "", "   "):
                    sequence += 1
                    with self.subTest(new_status=new_status, rationale=rationale):
                        with self.assertRaises(sqlite3.IntegrityError):
                            conn.execute(
                                insert_sql,
                                (
                                    f"{sequence:064x}",
                                    "a" * 64,
                                    sequence,
                                    previous_status,
                                    new_status,
                                    "2026-08-09T10:00:00Z",
                                    "admin-user",
                                    "admin",
                                    rationale,
                                    "b" * 64,
                                ),
                            )
                        conn.rollback()

            conn.execute(
                insert_sql,
                (
                    "f" * 64,
                    "c" * 64,
                    1,
                    "pending",
                    "under_review",
                    "2026-08-09T10:00:00Z",
                    "admin-user",
                    "admin",
                    None,
                    "d" * 64,
                ),
            )
            conn.commit()
            self.assertEqual(
                conn.execute(
                    "SELECT rationale FROM document_lifecycle_decision_events"
                ).fetchone()[0],
                None,
            )
        finally:
            conn.close()

    def test_valid_transition_records_exact_identity_state_actor_role_time_and_digest(self):
        result = self._transition(
            "under_review",
            "  Begin governed review.  ",
            changed_at="2026-08-09T10:00:00Z",
        )
        event = self._events()[0]
        self.assertEqual(event["intake_id"], self.item["intake_id"])
        self.assertEqual(self.item["document_identifier"], self._registry_identifier())
        self.assertEqual(event["document_identifier"], self.item["document_identifier"])
        self.assertEqual(event["previous_status"], "pending")
        self.assertEqual(event["new_status"], "under_review")
        self.assertEqual(event["decided_at"], "2026-08-09T10:00:00Z")
        self.assertEqual(event["actor"], "admin-user")
        self.assertEqual(event["actor_role"], "admin")
        self.assertEqual(event["rationale"], "Begin governed review.")
        self.assertEqual(event["sha256_hash"], hashlib.sha256(PDF_BYTES).hexdigest())
        self.assertEqual(event["digest_status"], "recorded")
        self.assertEqual(
            result["status_history"][-1]["lifecycle_decision_key"], event["decision_key"]
        )

    def test_sha512_is_snapshotted_only_when_already_available(self):
        metadata = json.loads(self._metadata_path().read_text(encoding="utf-8"))
        metadata["sha512_hash"] = hashlib.sha512(PDF_BYTES).hexdigest()
        self._metadata_path().write_text(json.dumps(metadata), encoding="utf-8")
        self._transition("under_review", "Review archive hashes.")
        self.assertEqual(self._events()[0]["sha512_hash"], hashlib.sha512(PDF_BYTES).hexdigest())

    def test_session_route_uses_verified_actor_and_role_and_rejects_spoof_parameters(self):
        response = admin_session.admin_document_intake_status_update(
            self.item["intake_id"],
            self.request,
            new_status="under_review",
            admin_note="Session-governed review.",
        )
        self.assertEqual(response.status_code, 200)
        event = self._events()[0]
        self.assertEqual((event["actor"], event["actor_role"]), ("admin-user", "admin"))
        with self.assertRaises(TypeError):
            admin_session.admin_document_intake_status_update(
                self.item["intake_id"],
                self.request,
                new_status="approved",
                admin_note="Approved.",
                actor="mallory",
                actor_role="owner",
            )

    def test_direct_helper_marks_unverified_role_as_unavailable(self):
        update_intake_status(
            self.item["intake_id"],
            "under_review",
            actor="internal-process",
            note="Internal governed call.",
            root=self.root,
            lifecycle_db_path=self.db_path,
        )
        self.assertEqual(self._events()[0]["actor_role"], "unavailable")

    def test_required_rationale_and_server_length_limit_fail_without_mutation(self):
        self._transition("under_review")
        before = self._metadata_path().read_bytes()
        for note, error in ((None, "document_intake_rationale_required"), (" " * 3, "document_intake_rationale_required"), ("x" * 501, "document_intake_rationale_too_long")):
            with self.subTest(error=error), self.assertRaisesRegex(ValueError, error):
                self._transition("approved", note)
            self.assertEqual(self._metadata_path().read_bytes(), before)
            self.assertEqual(len(self._events()), 1)

    def test_required_rationale_applies_to_publication_rejection_and_archive(self):
        transitions = (
            ("approved", "published"),
            ("under_review", "rejected"),
            ("approved", "archived"),
            ("rejected", "archived"),
            ("published", "archived"),
        )
        for index, (start, target) in enumerate(transitions):
            with self.subTest(start=start, target=target):
                data = PDF_BYTES + str(index).encode()
                item = self._store(data=data, original_filename=f"case-{index}.pdf")
                self.item = item
                self._transition("under_review")
                if start == "approved" or start == "published":
                    self._transition("approved", "Approved fixture.")
                elif start == "rejected":
                    self._transition("rejected", "Rejected fixture.")
                if start == "published":
                    self._transition("published", "Published fixture.")
                with self.assertRaisesRegex(ValueError, "document_intake_rationale_required"):
                    self._transition(target)

    def test_under_review_rationale_remains_optional(self):
        result = self._transition("under_review")
        self.assertEqual(result["status"], "under_review")
        self.assertIsNone(self._events()[0]["rationale"])

    def test_invalid_transition_records_nothing_and_preserves_metadata(self):
        before = self._metadata_path().read_bytes()
        with self.assertRaisesRegex(ValueError, "document_intake_transition_invalid"):
            self._transition("approved", "Cannot skip review.")
        self.assertEqual(self._events(), [])
        self.assertEqual(self._metadata_path().read_bytes(), before)

    def test_approval_and_publication_without_sha256_fail_closed(self):
        self._transition("under_review")
        metadata = json.loads(self._metadata_path().read_text(encoding="utf-8"))
        metadata.pop("sha256_hash", None)
        self._metadata_path().write_text(json.dumps(metadata), encoding="utf-8")
        before = self._metadata_path().read_bytes()
        with self.assertRaisesRegex(ValueError, "document_intake_decision_hash_required"):
            self._transition("approved", "Approve exact content.")
        self.assertEqual(self._metadata_path().read_bytes(), before)
        self.assertEqual(len(self._events()), 1)

        metadata["status"] = "approved"
        metadata["status_history"].append(
            {"previous_status": "under_review", "new_status": "approved", "timestamp": "legacy", "actor": "legacy", "note": "Legacy approval."}
        )
        self._metadata_path().write_text(json.dumps(metadata), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "document_intake_decision_hash_required"):
            self._transition("published", "Publish exact content.")

    def test_rejection_and_archive_allow_explicitly_unavailable_hash(self):
        self._transition("under_review")
        metadata = json.loads(self._metadata_path().read_text(encoding="utf-8"))
        metadata.pop("sha256_hash", None)
        self._metadata_path().write_text(json.dumps(metadata), encoding="utf-8")
        self._transition("rejected", "Withdraw incomplete legacy evidence.")
        event = self._events()[-1]
        self.assertIsNone(event["sha256_hash"])
        self.assertEqual(event["digest_status"], "unavailable")
        self._transition("archived", "Archive rejected legacy evidence.")
        self.assertEqual(self._events()[-1]["digest_status"], "unavailable")

    def test_sqlite_failure_prevents_metadata_transition(self):
        before = self._metadata_path().read_bytes()
        with patch("api.document_intake.record_lifecycle_decision", side_effect=sqlite3.OperationalError("locked")):
            with self.assertRaises(sqlite3.OperationalError):
                self._transition("under_review", "Review.")
        self.assertEqual(self._metadata_path().read_bytes(), before)
        self.assertEqual(self._events(), [])

    def test_projection_failure_retains_event_and_identical_retry_reconciles(self):
        before = self._metadata_path().read_bytes()
        with patch("api.document_intake._write_metadata", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self._transition("under_review", "Recoverable review.", changed_at="2026-08-09T11:00:00Z")
        self.assertEqual(self._metadata_path().read_bytes(), before)
        self.assertEqual(len(self._events()), 1)
        audit = admin_session._render_admin_audit_page(
            [load_pending_document(self.item["intake_id"], root=self.root)],
            durable_events=self._events(),
        )
        self.assertIn("Decision recorded; metadata projection pending", audit)
        result = self._transition(
            "under_review", "Recoverable review.", changed_at="2026-08-09T12:00:00Z"
        )
        self.assertEqual(result["status"], "under_review")
        self.assertEqual(len(self._events()), 1)
        self.assertEqual(result["status_history"][-1]["timestamp"], "2026-08-09T11:00:00Z")

    def test_conflicting_retry_is_rejected_and_original_decision_is_preserved(self):
        with patch("api.document_intake._write_metadata", side_effect=OSError("projection failed")):
            with self.assertRaises(OSError):
                self._transition("under_review", "Original decision.")
        with self.assertRaisesRegex(ValueError, "lifecycle_decision_conflict"):
            self._transition("under_review", "Conflicting decision.")
        self.assertEqual(len(self._events()), 1)
        self.assertEqual(self._events()[0]["rationale"], "Original decision.")

    def test_successful_identical_retry_does_not_duplicate_event_or_history(self):
        first = self._transition("under_review", "Review once.")
        second = self._transition("under_review", "Review once.")
        self.assertEqual(first, second)
        self.assertEqual(len(self._events()), 1)
        self.assertEqual(len(second["status_history"]), 2)

    def test_competing_decisions_from_same_state_have_one_winner(self):
        self._transition("under_review")

        def decide(target, note):
            try:
                return self._transition(target, note)["status"]
            except (ValueError, sqlite3.Error):
                return "rejected-by-coordinator"

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(
                pool.map(
                    lambda args: decide(*args),
                    (("approved", "Approve concurrently."), ("rejected", "Reject concurrently.")),
                )
            )
        self.assertEqual(outcomes.count("rejected-by-coordinator"), 1)
        self.assertIn(load_pending_document(self.item["intake_id"], root=self.root)["status"], {"approved", "rejected"})
        self.assertEqual(len(self._events()), 2)

    def test_legacy_sidecar_history_remains_visible_without_fabricated_event(self):
        self.assertEqual(self._events(), [])
        content = admin_session._render_document_intake_preview(self.item, lifecycle_events=[])
        self.assertIn("Legacy sidecar history", content)
        self.assertNotIn("Durable decision record</td>", content)

    def test_missing_document_identifier_is_supported_without_invention(self):
        metadata = json.loads(self._metadata_path().read_text(encoding="utf-8"))
        metadata.pop("document_identifier", None)
        self._metadata_path().write_text(json.dumps(metadata), encoding="utf-8")
        registry_path = self.root / ".document_identifiers.sqlite3"
        conn = sqlite3.connect(registry_path)
        conn.execute(
            "DELETE FROM document_identifiers WHERE intake_id = ?",
            (self.item["intake_id"],),
        )
        conn.commit()
        conn.close()
        registry_before = registry_path.read_bytes()

        result = self._transition("under_review", "Review legacy document.")

        self.assertNotIn("document_identifier", result)
        self.assertIsNone(self._events()[0]["document_identifier"])
        self.assertEqual(registry_path.read_bytes(), registry_before)

    def test_registry_identifier_is_authoritative_for_durable_event_and_projection(self):
        registry_identifier = self._registry_identifier()
        metadata = json.loads(self._metadata_path().read_text(encoding="utf-8"))
        metadata["document_identifier"] = "DOC-2099-999999"
        self._metadata_path().write_text(json.dumps(metadata), encoding="utf-8")
        registry_path = self.root / ".document_identifiers.sqlite3"
        registry_before = registry_path.read_bytes()

        result = self._transition("under_review", "Review authoritative identity.")

        self.assertEqual(registry_identifier, self._registry_identifier())
        self.assertEqual(self._events()[0]["document_identifier"], registry_identifier)
        self.assertEqual(result["document_identifier"], registry_identifier)
        self.assertEqual(
            json.loads(self._metadata_path().read_text(encoding="utf-8"))[
                "document_identifier"
            ],
            registry_identifier,
        )
        self.assertEqual(registry_path.read_bytes(), registry_before)

    def test_legacy_metadata_identifier_is_used_without_registry_allocation(self):
        legacy_identifier = "DOC-2020-000777"
        metadata = json.loads(self._metadata_path().read_text(encoding="utf-8"))
        metadata["document_identifier"] = legacy_identifier
        self._metadata_path().write_text(json.dumps(metadata), encoding="utf-8")
        registry_path = self.root / ".document_identifiers.sqlite3"
        conn = sqlite3.connect(registry_path)
        conn.execute(
            "DELETE FROM document_identifiers WHERE intake_id = ?",
            (self.item["intake_id"],),
        )
        conn.commit()
        conn.close()
        registry_before = registry_path.read_bytes()

        result = self._transition("under_review", "Review legacy identity.")

        self.assertEqual(self._events()[0]["document_identifier"], legacy_identifier)
        self.assertEqual(result["document_identifier"], legacy_identifier)
        self.assertIsNone(self._registry_identifier())
        self.assertEqual(registry_path.read_bytes(), registry_before)

    def test_status_history_publication_date_and_public_eligibility_remain_compatible(self):
        self._transition("under_review")
        self._transition("approved", "Approved for publication.")
        published = self._transition(
            "published", "Publication authorised.", changed_at="2026-08-09T13:00:00Z"
        )
        self.assertEqual(published["publication_date"], "2026-08-09T13:00:00Z")
        self.assertEqual(
            [event["new_status"] for event in published["status_history"]],
            ["pending", "under_review", "approved", "published"],
        )
        self.assertIn("Stage 56 governed decision", documents.public_document_library().content)

    def test_admin_status_history_and_global_audit_distinguish_durable_evidence(self):
        self._transition("under_review", "Review for audit.")
        events = self._events()
        detail = admin_session._render_document_intake_preview(
            load_pending_document(self.item["intake_id"], root=self.root),
            lifecycle_events=events,
        )
        audit = admin_session._render_admin_audit_page(
            [load_pending_document(self.item["intake_id"], root=self.root)],
            durable_events=events,
        )
        for content in (detail, audit):
            self.assertIn("Durable decision record — correctly projected", content)
            self.assertIn("Review for audit.", content)
        self.assertIn(self.item["sha256_hash"], detail)

    def test_admin_audit_identifies_inconsistent_metadata_projection(self):
        self._transition("under_review", "Review for consistency.")
        metadata = json.loads(self._metadata_path().read_text(encoding="utf-8"))
        metadata["status_history"][-1]["actor"] = "tampered-account"
        detail = admin_session._render_document_intake_preview(
            metadata, lifecycle_events=self._events()
        )
        audit = admin_session._render_admin_audit_page(
            [metadata], durable_events=self._events()
        )
        for content in (detail, audit):
            self.assertIn("Decision record / metadata projection inconsistent", content)

    def test_projection_classification_detects_current_metadata_tampering_without_repair(self):
        tamper_cases = {
            "status": "approved",
            "status_updated_at": "2026-08-09T00:00:00Z",
            "publication_date": "2026-08-08T00:00:00Z",
            "status_history": "tampered",
        }
        for index, (field, replacement) in enumerate(tamper_cases.items()):
            with self.subTest(field=field):
                self.item = self._store(
                    data=PDF_BYTES + str(index).encode(),
                    original_filename=f"projection-{index}.pdf",
                )
                self._transition("under_review")
                self._transition("approved", "Approve projection fixture.")
                self._transition("published", "Publish projection fixture.")
                metadata = json.loads(self._metadata_path().read_text(encoding="utf-8"))
                if field == "status_history":
                    metadata["status_history"][-1]["actor"] = replacement
                else:
                    metadata[field] = replacement
                self._metadata_path().write_text(json.dumps(metadata), encoding="utf-8")
                before = self._metadata_path().read_bytes()
                events = self._events()

                response = admin_session.admin_document_intake_preview_page(
                    self.item["intake_id"], self.request
                )
                audit = admin_session._render_admin_audit_page(
                    [metadata], durable_events=events
                )

                self.assertIn(
                    "Decision record / metadata projection inconsistent",
                    response.content,
                )
                self.assertIn(
                    "Decision record / metadata projection inconsistent", audit
                )
                self.assertEqual(self._metadata_path().read_bytes(), before)

    def test_admin_get_is_read_only_and_does_not_reconcile_pending_event(self):
        with patch("api.document_intake._write_metadata", side_effect=OSError("projection failed")):
            with self.assertRaises(OSError):
                self._transition("under_review", "Pending projection.")
        tracked = [self._metadata_path(), self.db_path]
        before = {path: path.read_bytes() for path in tracked}
        before_paths = sorted(str(path.relative_to(self.base)) for path in self.base.rglob("*"))
        response = admin_session.admin_document_intake_preview_page(
            self.item["intake_id"], self.request
        )
        self.assertIn("Decision recorded; metadata projection pending", response.content)
        after = {path: path.read_bytes() for path in tracked}
        after_paths = sorted(str(path.relative_to(self.base)) for path in self.base.rglob("*"))
        self.assertEqual(after, before)
        self.assertEqual(after_paths, before_paths)

    def test_legacy_published_get_does_not_create_governance_database(self):
        metadata = json.loads(self._metadata_path().read_text(encoding="utf-8"))
        metadata["status"] = "published"
        metadata["status_updated_at"] = "2026-08-01T12:00:00Z"
        metadata["publication_date"] = "2026-08-01T12:00:00Z"
        metadata["status_history"].append(
            {
                "previous_status": "approved",
                "new_status": "published",
                "timestamp": "2026-08-01T12:00:00Z",
                "actor": "legacy-admin",
                "note": "Legacy publication.",
            }
        )
        self._metadata_path().write_text(json.dumps(metadata), encoding="utf-8")
        self.assertFalse(self.db_path.exists())
        before_paths = sorted(str(path.relative_to(self.base)) for path in self.base.rglob("*"))
        before_bytes = {
            str(path.relative_to(self.base)): path.read_bytes()
            for path in self.base.rglob("*")
            if path.is_file()
        }

        response = admin_session.admin_document_intake_preview_page(
            self.item["intake_id"], self.request
        )

        after_paths = sorted(str(path.relative_to(self.base)) for path in self.base.rglob("*"))
        after_bytes = {
            str(path.relative_to(self.base)): path.read_bytes()
            for path in self.base.rglob("*")
            if path.is_file()
        }
        self.assertEqual(response.status_code, 200)
        self.assertIn("Legacy sidecar history", response.content)
        self.assertFalse(self.db_path.exists())
        self.assertEqual(after_paths, before_paths)
        self.assertEqual(after_bytes, before_bytes)

    def test_no_message_document_canonical_record_or_new_public_route_side_effect(self):
        self._transition("under_review")
        conn = sqlite3.connect(self.db_path)
        tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        conn.close()
        self.assertNotIn("canonical_records", tables)
        self.assertEqual(len(list(self.root.glob("*/metadata.json"))), 1)
        source = Path(documents.__file__).read_text(encoding="utf-8")
        self.assertNotIn("document_lifecycle_decision_events", source)

    def test_source_and_attachment_lifecycle_decisions_do_not_propagate(self):
        source = self._store(
            data=EMAIL_WITH_ATTACHMENT,
            original_filename="stage-56-source.eml",
            content_type="message/rfc822",
            title="Stage 56 source email",
            category="Email Correspondence",
        )
        relationships = list_source_attachments(source["intake_id"], root=self.root)
        self.assertEqual(len(relationships), 1)
        attachment_id = relationships[0]["attachment_document_id"]
        self.assertIsNotNone(attachment_id)

        self.assertEqual(
            dle.list_lifecycle_decisions(
                intake_id=source["intake_id"], db_path=self.db_path
            ),
            [],
        )
        self.assertEqual(
            dle.list_lifecycle_decisions(
                intake_id=attachment_id, db_path=self.db_path
            ),
            [],
        )

        update_intake_status(
            source["intake_id"],
            "under_review",
            actor="admin-user",
            actor_role="admin",
            note="Review source independently.",
            root=self.root,
            lifecycle_db_path=self.db_path,
        )
        source_events = dle.list_lifecycle_decisions(
            intake_id=source["intake_id"], db_path=self.db_path
        )
        attachment_events = dle.list_lifecycle_decisions(
            intake_id=attachment_id, db_path=self.db_path
        )
        self.assertEqual(len(source_events), 1)
        self.assertEqual(source_events[0]["intake_id"], source["intake_id"])
        self.assertEqual(attachment_events, [])

        update_intake_status(
            attachment_id,
            "under_review",
            actor="admin-user",
            actor_role="admin",
            note="Review attachment independently.",
            root=self.root,
            lifecycle_db_path=self.db_path,
        )
        source_events = dle.list_lifecycle_decisions(
            intake_id=source["intake_id"], db_path=self.db_path
        )
        attachment_events = dle.list_lifecycle_decisions(
            intake_id=attachment_id, db_path=self.db_path
        )
        self.assertEqual(len(source_events), 1)
        self.assertEqual(len(attachment_events), 1)
        self.assertEqual(attachment_events[0]["intake_id"], attachment_id)


if __name__ == "__main__":
    unittest.main()
