import json
import os
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from api import source_media_transcripts as transcripts
from api.document_intake import store_pending_document, store_private_original_source_media


MP4_BYTES = b"\x00\x00\x00\x18ftypisom\x00\x00\x00\x00synthetic stage 80.1"


class GovernedTranscriptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "intake"
        self.conn = sqlite3.connect(Path(self.temp.name) / "transcripts.sqlite")
        self.conn.row_factory = sqlite3.Row
        self.env = patch.dict(os.environ, {"CDE_DOCUMENT_INTAKE_ROOT": str(self.root)}, clear=False)
        self.env.start()
        self.source = store_private_original_source_media(
            data=MP4_BYTES, original_filename="synthetic.mp4", content_type="video/mp4",
            title="Synthetic", institution_source="Synthetic", document_date="2026-10-11",
            category="Synthetic", description="Synthetic", notes="Synthetic", root=self.root,
        )

    def tearDown(self):
        self.conn.close(); self.env.stop(); self.temp.cleanup()

    def _payload(self, **changes):
        value = {
            "source_language": "en", "transcription_method": "manual_entry",
            "responsible_tool": "operator editor", "responsible_tool_version": "1",
            "declared_duration_ms": 10_000,
            "utterances": [
                {"start_ms": 0, "end_ms": 1200, "text": "[inaudible] opening", "speaker_state": "unknown", "inaudible_note": "first word unclear", "uncertainty_note": "low confidence"},
                {"start_ms": 1000, "end_ms": 2200, "text": "Overlapping response", "speaker_state": "attributed", "speaker_label": "Participant A", "speaker_basis": "operator-provided context", "overlaps_speech": True},
                {"start_ms": 2300, "end_ms": 3000, "text": "Closing", "speaker_state": "identified", "speaker_label": "Named person", "speaker_basis": "self-identification in recording"},
            ],
            "translations": [{"target_language": "ga", "translation_text": "Aistriúchán", "translation_method": "manual_translation", "translation_authority": "operator translation"}],
        }
        value.update(changes)
        return value

    def test_private_manual_transcript_binds_exact_source_and_preserves_claim_qualification(self):
        item = transcripts.create_transcript_version(self.conn, source_intake_id=self.source["intake_id"], payload=self._payload(), actor="authenticated-admin", root=self.root)
        self.assertEqual(item["version_number"], 1)
        self.assertEqual(item["source_sha256"], self.source["sha256_hash"])
        self.assertEqual(item["original_source_identity"], self.source["private_original_source_media"]["original_source_identity"])
        self.assertEqual([x["ordinal"] for x in item["utterances"]], [1, 2, 3])
        self.assertEqual(item["utterances"][1]["overlaps_speech"], 1)
        self.assertEqual(item["translations"][0]["target_language"], "ga")
        self.assertIn("operator claims", item["operator_claim_notice"])

    def test_corrections_are_append_only_and_stale_requests_fail(self):
        first = transcripts.create_transcript_version(self.conn, source_intake_id=self.source["intake_id"], payload=self._payload(), actor="admin", root=self.root)
        corrected = self._payload(correction_reason="Corrected wording", utterances=[{"start_ms": 0, "end_ms": 100, "text": "Corrected", "speaker_state": "unknown"}])
        second = transcripts.create_transcript_version(self.conn, source_intake_id=self.source["intake_id"], payload=corrected, actor="admin", root=self.root, expected_version=1)
        self.assertEqual(second["version_number"], 2)
        self.assertEqual(second["supersedes_transcript_id"], first["id"])
        self.assertEqual(transcripts.get_transcript(self.conn, source_intake_id=self.source["intake_id"], version=1, root=self.root)["utterances"][0]["text"], "[inaudible] opening")
        with self.assertRaisesRegex(ValueError, "transcript_version_conflict"):
            transcripts.create_transcript_version(self.conn, source_intake_id=self.source["intake_id"], payload=corrected, actor="admin", root=self.root, expected_version=1)

    def test_correction_audit_and_rejections_preserve_existing_versions(self):
        first = transcripts.create_transcript_version(
            self.conn, source_intake_id=self.source["intake_id"], payload=self._payload(),
            actor="authenticated-admin", root=self.root,
        )
        first_before = transcripts.get_transcript(
            self.conn, source_intake_id=self.source["intake_id"], version=1, root=self.root,
        )
        corrected = self._payload(
            correction_reason="Corrected synthetic wording",
            utterances=[{"start_ms": 0, "end_ms": 100, "text": "Corrected", "speaker_state": "unknown"}],
            translations=[{
                "target_language": "ga", "translation_text": "Aistriúchán ceartaithe",
                "translation_method": "manual_translation", "translation_authority": "operator translation",
            }],
        )
        second = transcripts.create_transcript_version(
            self.conn, source_intake_id=self.source["intake_id"], payload=corrected,
            actor="authenticated-admin", root=self.root, expected_version=1,
        )
        self.assertEqual(second["version_number"], 2)
        first_after = transcripts.get_transcript(
            self.conn, source_intake_id=self.source["intake_id"], version=1, root=self.root,
        )
        self.assertEqual(first_after["utterances"], first_before["utterances"])
        self.assertEqual(first_after["translations"], first_before["translations"])
        audit = self.conn.execute(
            "SELECT event_type,actor,event_at,detail_json FROM source_media_transcript_audit_events "
            "WHERE transcript_id=?", (second["id"],)
        ).fetchone()
        self.assertEqual(audit["event_type"], "corrected")
        self.assertEqual(audit["actor"], "authenticated-admin")
        self.assertRegex(audit["event_at"], r"^\d{4}-\d{2}-\d{2}T.*Z$")
        self.assertEqual(json.loads(audit["detail_json"]), {"operator_claims": True, "version": 2})
        counts_before = tuple(self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in (
            "source_media_transcripts", "source_media_transcript_utterances",
            "source_media_transcript_translations", "source_media_transcript_audit_events",
        ))
        with self.assertRaisesRegex(ValueError, "transcript_correction_reason_required"):
            transcripts.create_transcript_version(
                self.conn, source_intake_id=self.source["intake_id"],
                payload=self._payload(correction_reason=None), actor="authenticated-admin",
                root=self.root, expected_version=2,
            )
        with self.assertRaisesRegex(ValueError, "transcript_version_conflict"):
            transcripts.create_transcript_version(
                self.conn, source_intake_id=self.source["intake_id"], payload=corrected,
                actor="authenticated-admin", root=self.root, expected_version=1,
            )
        counts_after = tuple(self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in (
            "source_media_transcripts", "source_media_transcript_utterances",
            "source_media_transcript_translations", "source_media_transcript_audit_events",
        ))
        self.assertEqual(counts_after, counts_before)

    def test_competing_connection_with_same_expected_version_is_rejected(self):
        db_path = Path(self.temp.name) / "competing.sqlite"
        first_conn = sqlite3.connect(db_path); first_conn.row_factory = sqlite3.Row
        second_conn = sqlite3.connect(db_path); second_conn.row_factory = sqlite3.Row
        try:
            transcripts.create_transcript_version(first_conn, source_intake_id=self.source["intake_id"], payload=self._payload(), actor="admin-a", root=self.root, expected_version=0)
            with self.assertRaisesRegex(ValueError, "transcript_version_conflict"):
                transcripts.create_transcript_version(second_conn, source_intake_id=self.source["intake_id"], payload=self._payload(), actor="admin-b", root=self.root, expected_version=0)
        finally:
            first_conn.close(); second_conn.close()

    def test_overlapping_writer_attempts_have_one_successor_and_consistent_audit(self):
        db_path = Path(self.temp.name) / "overlap.sqlite"
        bootstrap = sqlite3.connect(db_path)
        try:
            transcripts.ensure_transcript_tables(bootstrap)
            bootstrap.commit()
        finally:
            bootstrap.close()
        first_lock = sqlite3.connect(db_path, timeout=0)
        second_lock = sqlite3.connect(db_path, timeout=0)
        try:
            # This is real SQLite contention: writer one holds the lock while
            # writer two issues its own BEGIN IMMEDIATE and receives SQLITE_BUSY.
            first_lock.execute("BEGIN IMMEDIATE")
            with self.assertRaisesRegex(sqlite3.OperationalError, "locked|busy"):
                second_lock.execute("BEGIN IMMEDIATE")
        finally:
            first_lock.rollback()
            first_lock.close()
            second_lock.close()

        first_conn = sqlite3.connect(db_path); first_conn.row_factory = sqlite3.Row
        second_conn = sqlite3.connect(db_path); second_conn.row_factory = sqlite3.Row
        try:
            item = transcripts.create_transcript_version(first_conn, source_intake_id=self.source["intake_id"], payload=self._payload(), actor="first", root=self.root, expected_version=0)
            self.assertEqual(item["version_number"], 1)
            with self.assertRaisesRegex(ValueError, "transcript_version_conflict"):
                transcripts.create_transcript_version(second_conn, source_intake_id=self.source["intake_id"], payload=self._payload(), actor="second", root=self.root, expected_version=0)
        finally:
            first_conn.close(); second_conn.close()
        conn = sqlite3.connect(db_path); conn.row_factory = sqlite3.Row
        try:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM source_media_transcripts").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM source_media_transcript_audit_events").fetchone()[0], 1)
        finally:
            conn.close()

    def test_bounds_and_invalid_claims_fail_closed(self):
        bad = self._payload(utterances=[{"start_ms": 0, "end_ms": 1, "text": "x", "speaker_state": "identified", "speaker_label": "Person"}])
        with self.assertRaisesRegex(ValueError, "transcript_speaker_basis_required"):
            transcripts.create_transcript_version(self.conn, source_intake_id=self.source["intake_id"], payload=bad, actor="admin", root=self.root)
        with self.assertRaisesRegex(ValueError, "transcript_interval_invalid"):
            transcripts.create_transcript_version(self.conn, source_intake_id=self.source["intake_id"], payload=self._payload(utterances=[{"start_ms": 5, "end_ms": 4, "text": "x", "speaker_state": "unknown"}]), actor="admin", root=self.root)
        with self.assertRaisesRegex(ValueError, "transcript_import_too_large"):
            transcripts.create_transcript_version(self.conn, source_intake_id=self.source["intake_id"], payload={"x": "x" * (transcripts.MAX_IMPORT_BYTES + 1)}, actor="admin", root=self.root)

    def test_changed_source_bytes_or_nonprivate_source_are_rejected(self):
        Path(self.source["proposed_storage_location"]).write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "transcript_source_digest_mismatch"):
            transcripts.create_transcript_version(self.conn, source_intake_id=self.source["intake_id"], payload=self._payload(), actor="admin", root=self.root)

    def test_schema_is_additive_and_source_does_not_gain_public_access(self):
        transcripts.ensure_transcript_tables(self.conn)
        names = {row[0] for row in self.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertTrue({"source_media_transcripts", "source_media_transcript_utterances", "source_media_transcript_translations", "source_media_transcript_audit_events"}.issubset(names))
        self.assertEqual(self.source["visibility"], "private")
        self.assertEqual(self.source["status"], "pending")

    def test_public_stage80_paths_remain_ineligible_for_transcript_source(self):
        from api.document_intake import load_published_document, list_published_documents
        with self.assertRaisesRegex(ValueError, "public_document_not_found"):
            load_published_document(self.source["intake_id"], root=self.root)
        self.assertEqual(list_published_documents(root=self.root), [])

    def test_missing_and_ineligible_sources_fail_without_partial_rows(self):
        with self.assertRaisesRegex(ValueError, "transcript_source_not_found"):
            transcripts.create_transcript_version(self.conn, source_intake_id="missing", payload=self._payload(), actor="admin", root=self.root)
        ordinary = store_pending_document(
            data=b"%PDF-1.7\nsynthetic\n%%EOF\n", original_filename="ordinary.pdf", content_type="application/pdf",
            title="Ordinary", institution_source="Synthetic", document_date="2026-10-11", category="Synthetic",
            description="Synthetic", visibility="private", notes="Synthetic", root=self.root,
        )
        with self.assertRaisesRegex(ValueError, "transcript_source_not_private_original_media"):
            transcripts.create_transcript_version(self.conn, source_intake_id=ordinary["intake_id"], payload=self._payload(), actor="admin", root=self.root)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='source_media_transcripts'").fetchone()[0], 0)
