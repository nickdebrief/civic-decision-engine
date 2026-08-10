import json
import os
import re
import sqlite3
import tempfile
import unittest
from html import unescape
from pathlib import Path
from unittest.mock import patch

from tests.test_admin_session import FakeHTTPException, FakeRequest, install_fastapi_stubs

install_fastapi_stubs()

from api import document_lifecycle_events as lifecycle_events
from api import document_lifecycle_episodes as lifecycle_episodes
from api.document_intake import (
    load_published_document,
    list_published_documents,
    project_reconsideration_episode,
    store_pending_document,
    update_intake_status,
)
from api.routes import admin_session
from api.routes.documents import _render_publication_pathway


PDF_BYTES = b"%PDF-1.7\nstage-58-reconsideration\n%%EOF\n"


def token_from(response) -> str:
    match = re.search(r'name="confirmation_token" value="([^"]+)"', str(response.content))
    if not match:
        raise AssertionError("reconsideration token not rendered")
    return unescape(match.group(1))


class Stage58GovernedDocumentReconsiderationTests(unittest.TestCase):
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
                "CDE_ADMIN_SESSION_SECRET": "stage-58-session-secret",
                "CDE_STAGE58_RECONSIDERATION_ENABLED": "true",
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
            cookies={admin_session.SESSION_COOKIE_NAME: session}, query_params={}
        )

    def tearDown(self):
        admin_session.DB_PATH = self.original_db_path
        self.env.stop()
        self.temp_dir.cleanup()

    def _store(self, suffix=""):
        return store_pending_document(
            data=PDF_BYTES + suffix.encode(),
            original_filename=f"stage-58{suffix}.pdf",
            content_type="application/pdf",
            title="Stage 58 reconsideration fixture",
            institution_source="Civic Office",
            document_date="2026-08-10",
            category="Decision",
            description="Synthetic reconsideration fixture.",
            visibility="private",
            notes="Synthetic administrative context.",
            reference_identifier=f"STAGE-58{suffix}",
            actor="intake-admin",
            uploaded_at="2026-08-10T09:00:00Z",
            root=self.root,
        )

    def _events(self, intake_id):
        return lifecycle_events.list_lifecycle_decisions(
            intake_id=intake_id, db_path=self.db_path
        )

    def _archive(self, item):
        update_intake_status(
            item["intake_id"], "under_review", actor="admin-user", actor_role="admin",
            note="Review started.", root=self.root, lifecycle_db_path=self.db_path,
        )
        update_intake_status(
            item["intake_id"], "rejected", actor="admin-user", actor_role="admin",
            note="Original rejection decision.", root=self.root, lifecycle_db_path=self.db_path,
        )
        return update_intake_status(
            item["intake_id"], "archived", actor="admin-user", actor_role="admin",
            note="Original archival decision.", root=self.root, lifecycle_db_path=self.db_path,
        )

    def _prepare(self, item, rationale="Reconsider after additional governance review."):
        return admin_session.admin_document_intake_reconsideration_prepare(
            item["intake_id"], self.request, reconsideration_rationale=rationale
        )

    def _confirm(self, item, response):
        return admin_session.admin_document_intake_reconsideration_confirm(
            item["intake_id"], self.request, confirmation_token=token_from(response)
        )

    def test_schema_is_idempotent_and_has_no_historical_episode_rows(self):
        conn = sqlite3.connect(self.db_path)
        lifecycle_episodes.ensure_lifecycle_episode_table(conn)
        lifecycle_episodes.ensure_lifecycle_episode_table(conn)
        columns = {
            row[1] for row in conn.execute(
                "PRAGMA table_info(document_lifecycle_decision_events)"
            )
        }
        self.assertIn("episode_id", columns)
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM document_lifecycle_episodes").fetchone()[0],
            0,
        )
        conn.close()

    def test_stage56_rows_survive_additive_upgrade_unchanged(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "CREATE TABLE document_lifecycle_decision_events ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, decision_key TEXT NOT NULL UNIQUE, "
            "intake_id TEXT NOT NULL, decision_sequence INTEGER NOT NULL, "
            "document_identifier TEXT, previous_status TEXT NOT NULL, new_status TEXT NOT NULL, "
            "decided_at TEXT NOT NULL, actor TEXT NOT NULL, actor_role TEXT NOT NULL, "
            "rationale TEXT, sha256_hash TEXT, sha512_hash TEXT, digest_status TEXT NOT NULL, "
            "UNIQUE(intake_id, decision_sequence))"
        )
        values = ("a" * 64, "b" * 64, 1, "DOC-2026-000001", "pending", "under_review", "t", "actor", "admin", None, "c" * 64, None, "recorded")
        conn.execute(
            "INSERT INTO document_lifecycle_decision_events "
            "(decision_key,intake_id,decision_sequence,document_identifier,previous_status,new_status,decided_at,actor,actor_role,rationale,sha256_hash,sha512_hash,digest_status) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", values
        )
        before = conn.execute("SELECT * FROM document_lifecycle_decision_events").fetchall()
        lifecycle_episodes.ensure_lifecycle_episode_table(conn)
        after = conn.execute(
            "SELECT id,decision_key,intake_id,decision_sequence,document_identifier,previous_status,new_status,decided_at,actor,actor_role,rationale,sha256_hash,sha512_hash,digest_status FROM document_lifecycle_decision_events"
        ).fetchall()
        self.assertEqual(before, after)
        self.assertIsNone(conn.execute("SELECT episode_id FROM document_lifecycle_decision_events").fetchone()[0])
        conn.close()

    def test_reconsideration_proposal_is_observational(self):
        item = self._store()
        self._archive(item)
        metadata_path = self.root / item["intake_id"] / "metadata.json"
        before_metadata = metadata_path.read_bytes()
        before_events = self._events(item["intake_id"])
        response = self._prepare(item)
        self.assertIn("governed reconsideration", str(response.content))
        self.assertIn("Confirm Reconsideration", str(response.content))
        self.assertEqual(metadata_path.read_bytes(), before_metadata)
        self.assertEqual(self._events(item["intake_id"]), before_events)
        self.assertEqual(lifecycle_episodes.list_lifecycle_episodes(db_path=self.db_path), [])

    def test_reconsideration_write_gate_keeps_episode_reads_available(self):
        item = self._store()
        self._archive(item)
        self._confirm(item, self._prepare(item))
        metadata = json.loads(
            (self.root / item["intake_id"] / "metadata.json").read_bytes()
        )
        with patch.dict(os.environ, {"CDE_STAGE58_RECONSIDERATION_ENABLED": "false"}):
            preview = admin_session._render_document_intake_preview(
                metadata,
                lifecycle_events=self._events(item["intake_id"]),
            )
            self.assertIn("Lifecycle Episodes", preview)
            self.assertNotIn("Review Reconsideration", preview)
            with self.assertRaises(FakeHTTPException):
                self._prepare(item)

    def test_confirmation_creates_pending_episode_without_archived_pending_event(self):
        item = self._store()
        self._archive(item)
        before = self._events(item["intake_id"])
        self._confirm(item, self._prepare(item))
        episodes = lifecycle_episodes.list_lifecycle_episodes(
            intake_id=item["intake_id"], db_path=self.db_path
        )
        self.assertEqual(len(episodes), 1)
        self.assertEqual(episodes[0]["initial_status"], "pending")
        self.assertEqual(len(self._events(item["intake_id"])), len(before))
        metadata = json.loads((self.root / item["intake_id"] / "metadata.json").read_bytes())
        self.assertEqual(metadata["status"], "pending")
        self.assertEqual(metadata["active_episode_id"], episodes[0]["episode_id"])
        self.assertFalse(
            any(
                event.get("previous_status") == "archived"
                and event.get("new_status") == "pending"
                for event in self._events(item["intake_id"])
            )
        )

    def test_historical_episode_archive_is_not_classified_against_episode_two_projection(self):
        item = self._store()
        self._archive(item)
        self._confirm(item, self._prepare(item))
        metadata = json.loads(
            (self.root / item["intake_id"] / "metadata.json").read_bytes()
        )
        events = self._events(item["intake_id"])
        detail = admin_session._render_document_intake_preview(
            metadata, lifecycle_events=events
        )
        note_offset = detail.index("Original archival decision.")
        archive_row = detail[detail.rfind("<tr>", 0, note_offset) :].split(
            "</tr>", 1
        )[0]
        self.assertIn("Rejected", archive_row)
        self.assertIn("Archived", archive_row)
        self.assertIn("Durable decision record — historical episode", archive_row)
        self.assertNotIn(
            "Decision record / metadata projection inconsistent", archive_row
        )
        self.assertIn("Current durable state", detail)
        self.assertIn("Pending Intake", detail)
        self.assertEqual(metadata["status"], "pending")
        self.assertEqual(list_published_documents(root=self.root), [])

    def test_active_episode_projection_tampering_remains_inconsistent(self):
        item = self._store()
        self._archive(item)
        self._confirm(item, self._prepare(item))
        episode = lifecycle_episodes.list_lifecycle_episodes(
            intake_id=item["intake_id"], db_path=self.db_path
        )[0]
        update_intake_status(
            item["intake_id"], "under_review", actor="admin-user", actor_role="admin",
            note="Episode review started.", root=self.root,
            lifecycle_db_path=self.db_path, episode_id=episode["episode_id"],
        )
        metadata_path = self.root / item["intake_id"] / "metadata.json"
        metadata = json.loads(metadata_path.read_bytes())
        metadata["status"] = "published"
        detail = admin_session._render_document_intake_preview(
            metadata, lifecycle_events=self._events(item["intake_id"])
        )
        active_row = detail.split("Episode review started.", 1)[1].split(
            "</tr>", 1
        )[0]
        self.assertIn(
            "Decision record / metadata projection inconsistent", active_row
        )
        self.assertEqual(metadata["status"], "published")
        self.assertEqual(list_published_documents(root=self.root), [])

    def test_tampered_active_episode_id_does_not_hide_active_event(self):
        item = self._store()
        self._archive(item)
        self._confirm(item, self._prepare(item))
        episode = lifecycle_episodes.list_lifecycle_episodes(
            intake_id=item["intake_id"], db_path=self.db_path
        )[0]
        update_intake_status(
            item["intake_id"], "under_review", actor="admin-user", actor_role="admin",
            note="Episode review started.", root=self.root,
            lifecycle_db_path=self.db_path, episode_id=episode["episode_id"],
        )
        metadata = json.loads(
            (self.root / item["intake_id"] / "metadata.json").read_bytes()
        )
        metadata["active_episode_id"] = "LEP-" + "b" * 64
        detail = admin_session._render_document_intake_preview(
            metadata, lifecycle_events=self._events(item["intake_id"])
        )
        active_row = detail.split("Episode review started.", 1)[1].split(
            "</tr>", 1
        )[0]
        self.assertIn(
            "Decision record / metadata projection inconsistent", active_row
        )
        self.assertNotIn("Durable decision record — historical episode", active_row)

    def test_missing_active_episode_id_fails_closed_for_active_event(self):
        item = self._store()
        self._archive(item)
        self._confirm(item, self._prepare(item))
        episode = lifecycle_episodes.list_lifecycle_episodes(
            intake_id=item["intake_id"], db_path=self.db_path
        )[0]
        update_intake_status(
            item["intake_id"], "under_review", actor="admin-user", actor_role="admin",
            note="Episode review started.", root=self.root,
            lifecycle_db_path=self.db_path, episode_id=episode["episode_id"],
        )
        metadata = json.loads(
            (self.root / item["intake_id"] / "metadata.json").read_bytes()
        )
        metadata.pop("active_episode_id", None)
        detail = admin_session._render_document_intake_preview(
            metadata, lifecycle_events=self._events(item["intake_id"])
        )
        active_row = detail.split("Episode review started.", 1)[1].split(
            "</tr>", 1
        )[0]
        self.assertIn(
            "Decision record / metadata projection inconsistent", active_row
        )

    def test_historical_status_history_tampering_remains_inconsistent(self):
        item = self._store()
        self._archive(item)
        self._confirm(item, self._prepare(item))
        metadata = json.loads(
            (self.root / item["intake_id"] / "metadata.json").read_bytes()
        )
        archive_entry = next(
            entry
            for entry in metadata["status_history"]
            if entry.get("note") == "Original archival decision."
        )
        archive_entry["actor"] = "tampered-account"
        detail = admin_session._render_document_intake_preview(
            metadata, lifecycle_events=self._events(item["intake_id"])
        )
        archive_row = detail.split("Original archival decision.", 1)[1].split(
            "</tr>", 1
        )[0]
        self.assertIn(
            "Decision record / metadata projection inconsistent", archive_row
        )
        self.assertNotIn("Durable decision record — historical episode", archive_row)

    def test_episode_transition_uses_episode_id_and_continues_global_sequence(self):
        item = self._store()
        self._archive(item)
        self._confirm(item, self._prepare(item))
        episode = lifecycle_episodes.list_lifecycle_episodes(
            intake_id=item["intake_id"], db_path=self.db_path
        )[0]
        update_intake_status(
            item["intake_id"], "under_review", actor="admin-user", actor_role="admin",
            note="Review reconsidered.", root=self.root, lifecycle_db_path=self.db_path,
            episode_id=episode["episode_id"],
        )
        events = self._events(item["intake_id"])
        self.assertEqual(events[-1]["episode_id"], episode["episode_id"])
        self.assertEqual(events[-1]["decision_sequence"], 4)
        self.assertEqual(events[2]["new_status"], "archived")

    def test_duplicate_confirmation_is_idempotent(self):
        item = self._store()
        self._archive(item)
        response = self._prepare(item)
        self._confirm(item, response)
        self._confirm(item, response)
        self.assertEqual(len(lifecycle_episodes.list_lifecycle_episodes(intake_id=item["intake_id"], db_path=self.db_path)), 1)
        self.assertEqual(len(self._events(item["intake_id"])), 3)

    def test_reconsideration_confirmation_replay_after_episode_advances_is_stale(self):
        item = self._store()
        self._archive(item)
        response = self._prepare(item)
        self._confirm(item, response)
        episode = lifecycle_episodes.list_lifecycle_episodes(intake_id=item["intake_id"], db_path=self.db_path)[0]
        update_intake_status(
            item["intake_id"], "under_review", actor="admin-user", actor_role="admin",
            note="Episode review started.", root=self.root, lifecycle_db_path=self.db_path,
            episode_id=episode["episode_id"],
        )
        with self.assertRaises(FakeHTTPException):
            self._confirm(item, response)

    def test_registry_identifier_wins_over_tampered_metadata(self):
        item = self._store()
        self._archive(item)
        metadata_path = self.root / item["intake_id"] / "metadata.json"
        metadata = json.loads(metadata_path.read_bytes())
        registry = metadata["document_identifier"]
        metadata["document_identifier"] = "DOC-2099-999999"
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
        response = self._prepare(item)
        self._confirm(item, response)
        episode = lifecycle_episodes.list_lifecycle_episodes(intake_id=item["intake_id"], db_path=self.db_path)[0]
        self.assertEqual(episode["document_identifier"], registry)
        final = json.loads(metadata_path.read_bytes())
        self.assertEqual(final["document_identifier"], registry)

    def test_missing_registry_assignment_rejects_without_allocating(self):
        item = self._store()
        self._archive(item)
        registry_path = self.root / ".document_identifiers.sqlite3"
        registry_path.unlink()
        with self.assertRaises(FakeHTTPException):
            self._prepare(item)
        self.assertFalse(registry_path.exists())
        self.assertEqual(lifecycle_episodes.list_lifecycle_episodes(db_path=self.db_path), [])

    def test_legacy_sidecar_only_archive_is_not_eligible(self):
        item = self._store()
        metadata_path = self.root / item["intake_id"] / "metadata.json"
        metadata = json.loads(metadata_path.read_bytes())
        metadata["status"] = "archived"
        metadata["status_history"].append({"previous_status": "rejected", "new_status": "archived", "timestamp": "2026-08-10T10:00:00Z"})
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
        with self.assertRaises(FakeHTTPException):
            self._prepare(item)

    def test_tampered_reconsideration_token_fails_closed(self):
        item = self._store()
        self._archive(item)
        response = self._prepare(item)
        token = token_from(response)
        encoded, signature = token.split(".", 1)
        payload = json.loads(admin_session._b64decode(encoded).decode())
        for key, value in {
            "episode_id": "LEP-" + "0" * 64,
            "prior_terminal_decision_key": "0" * 64,
            "rationale": "changed",
            "document_identifier": "DOC-2099-000001",
            "sha256_hash": "0" * 64,
        }.items():
            with self.subTest(key=key):
                changed = dict(payload)
                changed[key] = value
                encoded_changed = admin_session._b64encode(json.dumps(changed, sort_keys=True, separators=(",", ":")).encode())
                with self.assertRaises(FakeHTTPException):
                    admin_session.admin_document_intake_reconsideration_confirm(
                        item["intake_id"], self.request,
                        confirmation_token=encoded_changed + "." + signature,
                    )
        self.assertEqual(len(lifecycle_episodes.list_lifecycle_episodes(db_path=self.db_path)), 0)

    def test_projection_failure_leaves_durable_episode_and_private_legacy_projection(self):
        item = self._store()
        self._archive(item)
        response = self._prepare(item)
        token = token_from(response)
        payload = admin_session._verify_reconsideration_confirmation_token(token)
        prior = self._events(item["intake_id"])[-1]
        episode, _ = lifecycle_episodes.create_reconsideration_episode(
            intake_id=item["intake_id"], document_identifier=payload["document_identifier"],
            sha256_hash=payload["sha256_hash"], sha512_hash=payload["sha512_hash"],
            prior_terminal_decision_key=prior["decision_key"], actor="admin-user",
            actor_role="admin", rationale=payload["rationale"], db_path=self.db_path,
        )
        metadata = json.loads((self.root / item["intake_id"] / "metadata.json").read_bytes())
        self.assertEqual(metadata["status"], "archived")
        self.assertEqual(episode["initial_status"], "pending")
        self.assertEqual(list_published_documents(root=self.root), [])

    def test_source_and_attachment_lifecycle_ids_are_independent(self):
        source = self._store("-source")
        attachment = self._store("-attachment")
        self._archive(source)
        self._archive(attachment)
        self._confirm(source, self._prepare(source))
        self.assertEqual(lifecycle_episodes.list_lifecycle_episodes(intake_id=source["intake_id"], db_path=self.db_path)[0]["intake_id"], source["intake_id"])
        self.assertEqual(lifecycle_episodes.list_lifecycle_episodes(intake_id=attachment["intake_id"], db_path=self.db_path), [])

    def test_public_pathway_separates_original_and_reconsideration_lifecycles(self):
        item = self._store()
        self._archive(item)
        self._confirm(item, self._prepare(item))
        episode = lifecycle_episodes.list_lifecycle_episodes(
            intake_id=item["intake_id"], db_path=self.db_path
        )[0]
        update_intake_status(
            item["intake_id"], "under_review", actor="admin-user", actor_role="admin",
            note="Reconsidered review started.", root=self.root,
            lifecycle_db_path=self.db_path, episode_id=episode["episode_id"],
        )
        update_intake_status(
            item["intake_id"], "approved", actor="admin-user", actor_role="admin",
            note="Reconsidered approval.", root=self.root,
            lifecycle_db_path=self.db_path, episode_id=episode["episode_id"],
        )
        update_intake_status(
            item["intake_id"], "published", actor="admin-user", actor_role="admin",
            note="Reconsidered publication.", root=self.root,
            lifecycle_db_path=self.db_path, episode_id=episode["episode_id"],
        )
        final_metadata = json.loads(
            (self.root / item["intake_id"] / "metadata.json").read_bytes()
        )
        pathway = _render_publication_pathway(final_metadata)
        self.assertIn("Original lifecycle", pathway)
        self.assertIn("Subsequent governed consideration — Episode 2", pathway)
        self.assertIn("Original rejection decision.", pathway)
        self.assertIn("Reconsidered publication.", pathway)
        original_section = pathway.split("Subsequent governed consideration", 1)[0]
        self.assertNotIn("Reconsidered publication.", original_section)

    def test_public_eligibility_fails_closed_on_episode_projection_tampering(self):
        item = self._store()
        self._archive(item)
        self._confirm(item, self._prepare(item))
        episode = lifecycle_episodes.list_lifecycle_episodes(
            intake_id=item["intake_id"], db_path=self.db_path
        )[0]
        for status in ("under_review", "approved", "published"):
            update_intake_status(
                item["intake_id"], status, actor="admin-user", actor_role="admin",
                note=f"Episode {status}.", root=self.root,
                lifecycle_db_path=self.db_path, episode_id=episode["episode_id"],
            )
        metadata_path = self.root / item["intake_id"] / "metadata.json"
        original = metadata_path.read_bytes()
        for field, replacement in (
            ("status", "approved"),
            ("status_updated_at", "2026-08-10T00:00:00Z"),
            ("publication_date", "2026-08-10T00:00:00Z"),
        ):
            with self.subTest(field=field):
                metadata = json.loads(original)
                metadata[field] = replacement
                metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
                self.assertEqual(list_published_documents(root=self.root), [])
                with self.assertRaises(ValueError):
                    load_published_document(item["intake_id"], root=self.root)
        metadata_path.write_bytes(original)


if __name__ == "__main__":
    unittest.main()
