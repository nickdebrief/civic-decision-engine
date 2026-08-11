import sqlite3
import unittest
from unittest.mock import MagicMock, patch

from api import record_document_association_decisions as decisions
from api import record_document_associations as associations


class Stage61RelationshipDecisionTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        associations.ensure_association_tables(self.conn)
        self.context = patch.multiple(
            associations,
            validate_public_record_reference=lambda conn, reference, root=None: reference,
            published_document_context=lambda document_id, root=None: {
                "intake_id": document_id,
                "reference_identifier": "DOC-TEST-001",
            },
            public_record_context=lambda conn, reference: {"reference": reference},
            record_has_authoritative_source=lambda record, conn=None: False,
        )
        self.context.start()

    def tearDown(self):
        self.context.stop()
        self.conn.close()

    def _create(
        self,
        *,
        key="create-1",
        rationale="Create the association after review.",
        actor="admin-user",
    ):
        return associations.create_association(
            self.conn,
            record_reference="REC-TEST-001",
            document_id="DOC-TEST-001",
            relationship_type="supporting_document",
            public_label="Supporting document",
            public_note="Public relationship note.",
            admin_note="Private relationship note.",
            is_public=True,
            actor=actor,
            actor_role="admin",
            rationale=rationale,
            idempotency_key=key,
            created_at="2026-08-11T10:00:00Z",
        )

    def test_four_governed_operations_map_to_passive_stage60_contract(self):
        association = self._create()
        associations.update_association(
            self.conn,
            association["id"],
            relationship_type="related_document",
            public_label="Related document",
            public_note="Updated public note.",
            admin_note="Updated private note.",
            is_public=True,
            actor="admin-user",
            actor_role="admin",
            rationale="The relationship was reclassified after review.",
            idempotency_key="reclassify-1",
            updated_at="2026-08-11T10:01:00Z",
        )
        associations.deactivate_association(
            self.conn,
            association["id"],
            actor="admin-user",
            actor_role="admin",
            note="Temporarily inactive.",
            rationale="The relationship is no longer active.",
            idempotency_key="deactivate-1",
            deactivated_at="2026-08-11T10:02:00Z",
        )
        associations.reactivate_association(
            self.conn,
            association["id"],
            actor="admin-user",
            actor_role="admin",
            note="Restored.",
            rationale="The relationship was reviewed and restored.",
            idempotency_key="reactivate-1",
            reactivated_at="2026-08-11T10:03:00Z",
        )

        rows = decisions.list_decisions(self.conn, association["id"])
        self.assertEqual(
            [row["decision_type"] for row in rows],
            [
                "association_created",
                "relationship_reclassified",
                "association_deactivated",
                "association_reactivated",
            ],
        )
        self.assertEqual(rows[0]["association_id"], association["id"])
        self.assertEqual(rows[0]["actor_role"], "admin")
        self.assertEqual(rows[1]["previous_state"]["relationship_type"], "supporting_document")
        self.assertEqual(rows[1]["resulting_state"]["relationship_type"], "related_document")
        adapted = decisions.adapt_decision(rows[1])
        self.assertEqual(adapted.subject.subject_type, "record_document_association")
        self.assertEqual(adapted.subject.subject_id, str(association["id"]))
        self.assertEqual(adapted.decision_type, "relationship_reclassified")
        self.assertEqual(adapted.actor_role, "admin")
        self.assertEqual(adapted.idempotency_key, "reclassify-1")
        self.assertNotEqual(adapted.decision_id, adapted.subject.subject_id)

    def test_note_and_visibility_only_updates_do_not_create_decisions(self):
        association = self._create()
        before = len(decisions.list_decisions(self.conn, association["id"]))
        associations.update_association(
            self.conn,
            association["id"],
            relationship_type="supporting_document",
            public_label="Updated label",
            public_note="Updated public note.",
            admin_note="Updated administrative note.",
            is_public=False,
            actor="admin-user",
            updated_at="2026-08-11T10:01:00Z",
        )
        self.assertEqual(len(decisions.list_decisions(self.conn, association["id"])), before)

    def test_missing_rationale_and_validation_fail_before_decision(self):
        with self.assertRaisesRegex(ValueError, "rationale_required"):
            self._create(rationale="")
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM record_document_associations").fetchone()[0],
            0,
        )
        with self.assertRaisesRegex(ValueError, "relationship_type_invalid"):
            associations.create_association(
                self.conn,
                record_reference="REC-TEST-001",
                document_id="DOC-TEST-001",
                relationship_type="invalid",
                actor="admin-user",
                actor_role="admin",
                rationale="This must fail validation.",
            )
        self.assertFalse(
            self.conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                ("record_document_association_decisions",),
            ).fetchone()
        )

    def test_explicit_idempotency_retry_reuses_result_and_conflict_fails_closed(self):
        first = self._create(key="retry-1")
        retry = self._create(key="retry-1")
        self.assertEqual(retry["id"], first["id"])
        self.assertEqual(len(decisions.list_decisions(self.conn, first["id"])), 1)
        with self.assertRaisesRegex(ValueError, "idempotency_conflict"):
            self._create(key="retry-1", rationale="A materially different request.")
        self.assertEqual(len(decisions.list_decisions(self.conn, first["id"])), 1)

    def test_same_key_for_different_association_fails_closed(self):
        first = self._create(key="subject-conflict")
        with self.assertRaisesRegex(ValueError, "idempotency_conflict"):
            associations.create_association(
                self.conn,
                record_reference="REC-TEST-002",
                document_id="DOC-TEST-002",
                relationship_type="supporting_document",
                actor="admin-user",
                actor_role="admin",
                rationale="A different association subject.",
                idempotency_key="subject-conflict",
            )
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM record_document_associations").fetchone()[0],
            1,
        )
        self.assertEqual(len(decisions.list_decisions(self.conn, first["id"])), 1)
        self.assertEqual(associations.association_history(self.conn, first["id"])[0]["action_type"], "created")

    def test_same_key_for_different_decision_type_fails_closed(self):
        association = self._create(key="type-conflict")
        with self.assertRaisesRegex(ValueError, "idempotency_conflict"):
            associations.deactivate_association(
                self.conn,
                association["id"],
                actor="admin-user",
                actor_role="admin",
                note="Deactivate.",
                rationale="A different governed operation.",
                idempotency_key="type-conflict",
            )
        self.assertEqual(associations.get_association(self.conn, association["id"])["is_active"], 1)
        self.assertEqual(len(decisions.list_decisions(self.conn, association["id"])), 1)
        self.assertEqual(len(associations.association_history(self.conn, association["id"])), 1)

    def test_same_key_for_different_resulting_relationship_state_fails_closed(self):
        association = self._create(key="state-create")
        associations.update_association(
            self.conn,
            association["id"],
            relationship_type="related_document",
            public_label="Related",
            public_note="Public.",
            admin_note="Private.",
            is_public=True,
            actor="admin-user",
            actor_role="admin",
            rationale="First classification.",
            idempotency_key="state-conflict",
        )
        with self.assertRaisesRegex(ValueError, "idempotency_conflict"):
            associations.update_association(
                self.conn,
                association["id"],
                relationship_type="publication_context",
                public_label="Publication context",
                public_note="Public.",
                admin_note="Private.",
                is_public=True,
                actor="admin-user",
                actor_role="admin",
                rationale="Conflicting resulting classification.",
                idempotency_key="state-conflict",
            )
        current = associations.get_association(self.conn, association["id"])
        self.assertEqual(current["relationship_type"], "related_document")
        self.assertEqual(len(decisions.list_decisions(self.conn, association["id"])), 2)
        self.assertEqual(len(associations.association_history(self.conn, association["id"])), 2)

    def test_decision_and_history_are_atomic_when_decision_recording_fails(self):
        with patch.object(
            decisions,
            "record_decision",
            side_effect=RuntimeError("injected decision failure"),
        ):
            with self.assertRaisesRegex(RuntimeError, "injected decision failure"):
                self._create(key="atomic-1")
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM record_document_associations").fetchone()[0],
            0,
        )
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM record_document_association_history").fetchone()[0],
            0,
        )

    def test_history_insert_failure_rolls_back_mutation_and_decision(self):
        with patch.object(
            associations,
            "_record_history",
            side_effect=RuntimeError("injected history failure"),
        ):
            with self.assertRaisesRegex(RuntimeError, "injected history failure"):
                self._create(key="history-atomic-1")
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM record_document_associations").fetchone()[0],
            0,
        )
        self.assertEqual(decisions.list_decisions(self.conn, 1), [])
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM record_document_association_history").fetchone()[0],
            0,
        )

    def test_association_mutation_failure_leaves_no_history_or_decision(self):
        class FailingConnection:
            def __init__(self, connection):
                self.connection = connection

            def execute(self, sql, *args):
                if "INSERT INTO record_document_associations" in str(sql):
                    raise sqlite3.IntegrityError("injected association mutation failure")
                return self.connection.execute(sql, *args)

            def rollback(self):
                return self.connection.rollback()

            def commit(self):
                return self.connection.commit()

            def __getattr__(self, name):
                return getattr(self.connection, name)

        failing = FailingConnection(self.conn)
        with self.assertRaisesRegex(sqlite3.IntegrityError, "injected association mutation failure"):
            associations.create_association(
                failing,
                record_reference="REC-TEST-001",
                document_id="DOC-TEST-001",
                relationship_type="supporting_document",
                actor="admin-user",
                actor_role="admin",
                rationale="The mutation should fail atomically.",
                idempotency_key="mutation-atomic-1",
            )
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM record_document_associations").fetchone()[0],
            0,
        )
        self.assertEqual(decisions.list_decisions(self.conn, 1), [])
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM record_document_association_history").fetchone()[0],
            0,
        )

    def test_public_association_endpoint_does_not_disclose_stage61_decision_data(self):
        from api.routes import associations as public_association_routes

        association = self._create(
            key="public-disclosure-1", actor="stage61-private-actor"
        )
        row = {
            "id": association["id"],
            "public_reference": "CDE-ASSOC-20260811-001",
            "record_reference": "REC-TEST-001",
            "document_id": "DOC-TEST-001",
            "relationship_type": "supporting_document",
            "public_label": "Supporting document",
            "public_note": "Public relationship note.",
            "created_at": "2026-08-11T10:00:00Z",
            "created_by": "existing-public-actor",
            "is_active": 1,
            "is_public": 1,
            "record_title": "Public record",
            "document_title": "Public document",
            "document_reference_identifier": "DOC-TEST-001",
        }
        connection = MagicMock()
        with patch.object(public_association_routes.rda, "get_db", return_value=connection), \
             patch.object(public_association_routes.rda, "get_public_association", return_value=row), \
             patch.object(public_association_routes.rda, "public_association_history", return_value=[]):
            response = public_association_routes.public_association_page(
                row["public_reference"]
            )
        content = getattr(response, "content", None)
        if content is None:
            content = response.body.decode("utf-8")
        self.assertIn("CDE-ASSOC-20260811-001", content)
        self.assertIn("Public document", content)
        for secret in (
            "record-document-association-decision:",
            "public-disclosure-1",
            "stage61-private-actor",
            "actor_role",
            "private rationale",
            "evidence_references",
            "context_reference",
            "association_id",
        ):
            self.assertNotIn(secret, content)

    def test_historical_association_history_is_not_backfilled_as_decision(self):
        self.conn.execute(
            """
            INSERT INTO record_document_associations (
                public_reference, record_reference, document_id,
                document_reference_identifier, relationship_type, public_label,
                is_active, is_public, created_at, created_by, updated_at, updated_by
            ) VALUES (?, ?, ?, ?, ?, ?, 1, 1, ?, ?, ?, ?)
            """,
            (
                "CDE-ASSOC-20260810-001",
                "REC-HIST-001",
                "DOC-HIST-001",
                "DOC-HIST-001",
                "supporting_document",
                "Supporting document",
                "2026-08-10T10:00:00Z",
                "historical-admin",
                "2026-08-10T10:00:00Z",
                "historical-admin",
            ),
        )
        association_id = self.conn.execute(
            "SELECT id FROM record_document_associations"
        ).fetchone()[0]
        self.conn.execute(
            """
            INSERT INTO record_document_association_history (
                association_id, action_type, timestamp, actor,
                previous_state_json, new_state_json, note
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                association_id,
                "created",
                "2026-08-10T10:00:00Z",
                "historical-admin",
                None,
                '{"is_active": true}',
                "Historical audit note",
            ),
        )
        self.conn.commit()
        before_association = dict(associations.get_association(self.conn, association_id))
        before_history = [dict(row) for row in associations.association_history(self.conn, association_id)]

        self.assertEqual(decisions.list_decisions(self.conn, association_id), [])
        decisions.ensure_decision_table(self.conn)
        self.assertEqual(decisions.list_decisions(self.conn, association_id), [])
        self.assertEqual(associations.get_association(self.conn, association_id), before_association)
        self.assertEqual(associations.association_history(self.conn, association_id), before_history)

    def test_adapter_and_reads_do_not_initialize_or_write_decision_evidence(self):
        fresh = sqlite3.connect(":memory:")
        fresh.row_factory = sqlite3.Row
        self.assertEqual(decisions.list_decisions(fresh, 1), [])
        self.assertFalse(
            fresh.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                ("record_document_association_decisions",),
            ).fetchone()
        )
        fresh.close()


if __name__ == "__main__":
    unittest.main()
