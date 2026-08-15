import inspect
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from tests.test_admin_session import FakeHTTPException, FakeRequest, install_fastapi_stubs

install_fastapi_stubs()

from api import record_document_associations as associations
from api import record_pattern_observations as observations
from api.routes import admin_session, associations as public_association_routes


class Stage62GovernedPatternObservationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "records.db"
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        associations.ensure_association_tables(self.conn)
        self._insert_association(1, "REC-62", "supporting_document", "2026-01-01T00:00:00Z")
        self._insert_association(2, "REC-62", "supporting_document", "2026-02-01T00:00:00Z")
        self._insert_association(3, "REC-62", "related_document", "2026-03-01T00:00:00Z")
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        self.temp_dir.cleanup()

    def _insert_association(self, ident, record, relationship, created):
        self.conn.execute(
            """INSERT INTO record_document_associations
               (id, public_reference, record_reference, document_id,
                relationship_type, public_label, is_active, is_public,
                created_at, created_by, updated_at, updated_by)
               VALUES (?, ?, ?, ?, ?, ?, 1, 1, ?, 'admin', ?, 'admin')""",
            (ident, f"CDE-ASSOC-62-{ident}", record, f"doc-{ident}", relationship,
             relationship, created, created),
        )

    def test_only_exact_repeated_governed_relationships_produce_candidates(self):
        candidates = observations.recurrence_candidates(self.conn)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["record_reference"], "REC-62")
        self.assertEqual(candidates[0]["relationship_type"], "supporting_document")
        self.assertEqual(candidates[0]["source_count"], 2)
        self.assertEqual([row["id"] for row in candidates[0]["bindings"]], [1, 2])

    def test_single_occurrence_does_not_produce_candidate(self):
        self.assertEqual(
            observations.recurrence_candidates(self.conn, relationship_type="related_document"),
            [],
        )

    def test_candidate_preserves_sources_and_is_idempotent(self):
        before = [dict(row) for row in self.conn.execute(
            "SELECT * FROM record_document_associations ORDER BY id"
        )]
        first = observations.create_candidate_observation(
            self.conn,
            record_reference="REC-62",
            relationship_type="supporting_document",
            actor="admin",
            actor_role="admin",
            rationale="The repeated governed relationship is being recorded for review.",
            created_at="2026-04-01T00:00:00Z",
        )
        retry = observations.create_candidate_observation(
            self.conn,
            record_reference="REC-62",
            relationship_type="supporting_document",
            actor="admin",
            actor_role="admin",
            rationale="The repeated governed relationship is being recorded for review.",
            created_at="2026-05-01T00:00:00Z",
        )
        self.assertEqual(retry["id"], first["id"])
        self.assertEqual(
            [dict(row) for row in self.conn.execute("SELECT * FROM record_document_associations ORDER BY id")],
            before,
        )
        self.assertEqual(first["status"], "candidate")
        self.assertNotIn("intent", first["request_payload"])
        self.assertNotIn("motive", first["request_payload"])
        self.assertNotIn("wrongdoing", first["request_payload"])
        with self.assertRaisesRegex(ValueError, "idempotency_conflict"):
            observations.create_candidate_observation(
                self.conn,
                record_reference="REC-62",
                relationship_type="supporting_document",
                actor="admin",
                actor_role="admin",
                rationale="A different semantic command.",
                idempotency_key=first["idempotency_key"],
            )

    def test_review_is_governed_and_history_is_retained(self):
        observation = observations.create_candidate_observation(
            self.conn,
            record_reference="REC-62",
            relationship_type="supporting_document",
            actor="admin",
            actor_role="admin",
            rationale="Review the recurrence as a governed observation.",
        )
        observations.review_observation(
            self.conn, observation["id"], status="deferred", actor="reviewer",
            actor_role="admin", rationale="Insufficient administrative context.",
        )
        reviewed = observations.review_observation(
            self.conn, observation["id"], status="rejected", actor="reviewer",
            actor_role="admin", rationale="Do not accept this candidate.",
        )
        self.assertEqual(reviewed["status"], "rejected")
        self.assertEqual([row["status"] for row in reviewed["reviews"]], ["deferred", "rejected"])

    def test_read_path_does_not_initialize_observation_table(self):
        self.conn.close()
        diagnostic = observations.read_observation_diagnostic(db_path=self.db_path)
        self.assertEqual(diagnostic["status"], "ok")
        check = sqlite3.connect(self.db_path)
        self.assertIsNone(check.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='record_pattern_observations'"
        ).fetchone())
        check.close()

    def test_admin_authentication_precedes_pattern_reader(self):
        request = FakeRequest(cookies={})
        reader = Mock()
        with patch.object(admin_session, "require_admin_session", side_effect=FakeHTTPException(401, "admin_session_unauthorized")), \
             patch.object(admin_session.rpo, "read_observation_diagnostic", reader):
            with self.assertRaises(FakeHTTPException):
                admin_session.admin_pattern_observations_page(request)
        reader.assert_not_called()

    def test_admin_authentication_precedes_pattern_writer(self):
        request = FakeRequest(cookies={})
        writer = Mock()
        with patch.object(admin_session, "require_admin_session", side_effect=FakeHTTPException(401, "admin_session_unauthorized")), \
             patch.object(admin_session.rpo, "create_candidate_observation", writer):
            with self.assertRaises(FakeHTTPException):
                admin_session.admin_pattern_observation_create(
                    request, "REC-62", "supporting_document", "rationale", None
                )
        writer.assert_not_called()

    def test_authenticated_get_route_is_observational_when_table_is_absent(self):
        self.conn.close()
        request = FakeRequest(cookies={"cde_admin_session": "signed"})
        with patch.object(admin_session, "require_admin_session", return_value={"role": "admin", "username": "admin"}), \
             patch.object(admin_session, "DB_PATH", self.db_path):
            response = admin_session.admin_pattern_observations_page(request)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Deterministic recurrence candidates", response.content)
        check = sqlite3.connect(self.db_path)
        self.assertIsNone(check.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='record_pattern_observations'"
        ).fetchone())
        check.close()

    def test_stage62_has_no_public_route_or_public_observation_fields(self):
        self.assertNotIn("record_pattern_observation", inspect.getsource(public_association_routes))

    def test_correction_history_remains_binding_not_rewritten(self):
        observation = observations.create_candidate_observation(
            self.conn,
            record_reference="REC-62",
            relationship_type="supporting_document",
            actor="admin",
            actor_role="admin",
            rationale="Original governed bindings remain the source evidence.",
        )
        self.conn.execute(
            "UPDATE record_document_associations SET is_active = 0 WHERE id = 1"
        )
        self.conn.commit()
        reloaded = observations.get_observation(self.conn, observation["id"])
        self.assertEqual([row["association_id"] for row in reloaded["bindings"]], [1, 2])


if __name__ == "__main__":
    unittest.main()
