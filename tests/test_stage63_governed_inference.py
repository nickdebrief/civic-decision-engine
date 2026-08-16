import inspect
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from tests.test_admin_session import FakeHTTPException, FakeRequest, install_fastapi_stubs

install_fastapi_stubs()

from api import record_document_associations as associations
from api import record_governed_inferences as inferences
from api.routes import admin_session, associations as public_association_routes


class Stage63GovernedInferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "records.db"
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        associations.ensure_association_tables(self.conn)
        self._insert_association(1, "REC-63", "supporting_document", "2026-01-01T00:00:00Z")
        self._insert_association(2, "REC-63", "related_document", "2026-02-01T00:00:00Z")
        self.conn.execute("CREATE TABLE records (reference TEXT PRIMARY KEY, version INTEGER, generated_at TEXT)")
        self.conn.execute("INSERT INTO records VALUES ('REC-63', 1, '2026-01-01T00:00:00Z')")
        self.conn.execute(
            """CREATE TABLE record_pattern_observations (
               id INTEGER PRIMARY KEY, status TEXT NOT NULL, created_at TEXT NOT NULL
            )"""
        )
        self.conn.execute("INSERT INTO record_pattern_observations VALUES (7, 'accepted', '2026-03-01T00:00:00Z')")
        self.conn.execute("INSERT INTO record_pattern_observations VALUES (8, 'candidate', '2026-03-02T00:00:00Z')")
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
            (ident, f"CDE-ASSOC-63-{ident}", record, f"doc-{ident}", relationship,
             relationship, created, created),
        )

    def _contract(self, limitations="Alternative interpretations remain possible."):
        return {
            "epistemic_label": "inference",
            "source_basis_present": True,
            "alternatives_possible": True,
            "not_evidence": True,
            "not_determination": True,
            "limitations": limitations,
        }

    def _binding(self, source_type="record_document_association", source_id="1", role="primary_support"):
        return {"source_type": source_type, "source_id": source_id, "binding_role": role}

    def _create(self, *, proposition="The sequence may reflect separated administrative handling.", bindings=None, key=None):
        return inferences.create_inference(
            self.conn,
            inference_type="procedural",
            proposition=proposition,
            rationale="The governed source sequence is being preserved for review.",
            qualification="This is a qualified interpretation, not evidence or a determination.",
            qualification_contract=self._contract(),
            bindings=bindings or [self._binding()],
            actor="author",
            actor_role="admin",
            author_declaration={"acknowledged": True},
            idempotency_key=key,
            created_at="2026-04-01T00:00:00Z",
        )

    def test_creation_requires_valid_binding_and_preserves_multiple_and_contrary_sources(self):
        inference = self._create(bindings=[
            self._binding("record_document_association", "1", "primary_support"),
            self._binding("canonical_record", "REC-63", "contextual_support"),
            self._binding("accepted_pattern_observation", "7", "contrary_evidence"),
        ])
        self.assertEqual(len(inference["bindings"]), 3)
        self.assertEqual(
            {row["binding_role"] for row in inference["bindings"]},
            {"primary_support", "contextual_support", "contrary_evidence"},
        )
        with self.assertRaisesRegex(ValueError, "source_not_found"):
            self._create(bindings=[self._binding(source_id="999")])

    def test_source_objects_are_not_mutated_and_unaccepted_observation_fails(self):
        before = [dict(row) for row in self.conn.execute("SELECT * FROM record_document_associations ORDER BY id")]
        self._create()
        after = [dict(row) for row in self.conn.execute("SELECT * FROM record_document_associations ORDER BY id")]
        self.assertEqual(before, after)
        with self.assertRaisesRegex(ValueError, "observation_not_accepted"):
            self._create(bindings=[self._binding("accepted_pattern_observation", "8")])

    def test_controlled_types_and_human_authoring_are_enforced(self):
        with self.assertRaisesRegex(ValueError, "type_invalid"):
            inferences.create_inference(
                self.conn, inference_type="explanatory", proposition="x", rationale="r",
                qualification="q", qualification_contract=self._contract(), bindings=[self._binding()],
                actor="author", actor_role="admin", author_declaration={"acknowledged": True},
            )
        with self.assertRaisesRegex(ValueError, "authoring_mode_invalid"):
            self._create_with_mode("llm_generated")

    def _create_with_mode(self, mode):
        return inferences.create_inference(
            self.conn, inference_type="procedural", proposition="x", rationale="r",
            qualification="q", qualification_contract=self._contract(), bindings=[self._binding()],
            actor="author", actor_role="admin", author_declaration={"acknowledged": True},
            authoring_mode=mode,
        )

    def test_structured_qualification_and_author_declaration_are_required(self):
        with self.assertRaisesRegex(ValueError, "qualification_contract_incomplete"):
            inferences.create_inference(
                self.conn, inference_type="contextual", proposition="x", rationale="r", qualification="q",
                qualification_contract={"epistemic_label": "inference"}, bindings=[self._binding()],
                actor="author", actor_role="admin", author_declaration={"acknowledged": True},
            )
        with self.assertRaisesRegex(ValueError, "limitations_required"):
            inferences.create_inference(
                self.conn, inference_type="contextual", proposition="x", rationale="r", qualification="q",
                qualification_contract=self._contract(""), bindings=[self._binding()],
                actor="author", actor_role="admin", author_declaration={"acknowledged": True},
            )
        with self.assertRaisesRegex(ValueError, "boundary_declaration_required"):
            inferences.create_inference(
                self.conn, inference_type="contextual", proposition="x", rationale="r", qualification="q",
                qualification_contract=self._contract(), bindings=[self._binding()],
                actor="author", actor_role="admin", author_declaration={"acknowledged": False},
            )

    def test_competing_inferences_coexist_and_inference_binding_is_rejected(self):
        first = self._create(proposition="The sequence may reflect separated handling.")
        second = self._create(proposition="The sequence may reflect an unresolved handoff.")
        self.assertNotEqual(first["id"], second["id"])
        with self.assertRaisesRegex(ValueError, "source_type_invalid"):
            self._create(bindings=[self._binding("governed_inference", str(first["id"]))])

    def test_creation_retry_and_semantic_conflict_are_governed(self):
        first = self._create(key="same-create-key")
        retry = self._create(key="same-create-key")
        self.assertEqual(first["id"], retry["id"])
        with self.assertRaisesRegex(ValueError, "idempotency_conflict"):
            self._create(proposition="A materially different proposition.", key="same-create-key")

    def test_review_history_self_review_and_later_rejection_are_preserved(self):
        inference = self._create()
        accepted = inferences.review_inference(
            self.conn, inference["id"], status="accepted_as_inference", rationale="Retain as qualified inference.",
            qualification_assessment={"within_stage63_boundary": True, "qualification_adequate": True, "no_prohibited_class_asserted": True},
            prohibited_class_assessment={"within_stage63_boundary": True, "qualification_adequate": True, "no_prohibited_class_asserted": True},
            contrary_evidence_note="Alternative explanations remain possible.", actor="author", actor_role="admin",
        )
        self.assertEqual(accepted["status"], "accepted_as_inference")
        self.assertEqual(accepted["reviews"][0]["is_self_review"], 1)
        rejected = inferences.review_inference(
            self.conn, inference["id"], status="rejected", rationale="Later review rejects retention.",
            qualification_assessment={"within_stage63_boundary": True, "qualification_adequate": True, "no_prohibited_class_asserted": True},
            prohibited_class_assessment={"within_stage63_boundary": True, "qualification_adequate": True, "no_prohibited_class_asserted": True},
            contrary_evidence_note="Contrary evidence is now material.", actor="reviewer", actor_role="admin",
        )
        self.assertEqual(rejected["status"], "rejected")
        self.assertEqual([item["status"] for item in rejected["reviews"]], ["accepted_as_inference", "rejected"])

    def test_supersession_preserves_original_and_is_idempotent(self):
        original = self._create()
        replacement = self._create(proposition="A more precise qualified interpretation.")
        inferences.review_inference(
            self.conn, original["id"], status="accepted_as_inference",
            rationale="Retain the qualified inference.",
            qualification_assessment={"within_stage63_boundary": True, "qualification_adequate": True, "no_prohibited_class_asserted": True},
            prohibited_class_assessment={"within_stage63_boundary": True, "qualification_adequate": True, "no_prohibited_class_asserted": True},
            contrary_evidence_note="Alternatives remain possible.", actor="reviewer", actor_role="admin",
        )
        superseded = inferences.supersede_inference(
            self.conn, original["id"], replacement_inference_id=replacement["id"],
            rationale="A more precise inference replaces the earlier wording.", actor="reviewer", actor_role="admin",
            idempotency_key="supersede-1",
        )
        retry = inferences.supersede_inference(
            self.conn, original["id"], replacement_inference_id=replacement["id"],
            rationale="A more precise inference replaces the earlier wording.", actor="reviewer", actor_role="admin",
            idempotency_key="supersede-1",
        )
        self.assertEqual(superseded["status"], "superseded")
        self.assertEqual(retry["supersessions"][0]["replacement_inference_id"], replacement["id"])
        resolved = inferences.get_inference(self.conn, original["id"])
        self.assertEqual(resolved["status"], "superseded")
        self.assertEqual(original["proposition"], resolved["proposition"])

    def test_no_edit_endpoint_and_no_public_surface_or_legacy_reuse(self):
        source = inspect.getsource(admin_session)
        self.assertNotIn("governed-inferences/{inference_id}/edit", source)
        self.assertNotIn("record_governed_inference", inspect.getsource(public_association_routes))
        self.assertNotIn("from api.routes.pattern", inspect.getsource(admin_session))

    def test_get_authentication_precedes_reader_and_get_does_not_initialize_tables(self):
        request = FakeRequest(cookies={})
        reader = Mock()
        with patch.object(admin_session, "require_admin_session", side_effect=FakeHTTPException(401, "admin_session_unauthorized")), \
             patch.object(admin_session.rgi, "read_inference_diagnostic", reader):
            with self.assertRaises(FakeHTTPException):
                admin_session.admin_governed_inferences_page(request)
        reader.assert_not_called()

        self.conn.close()
        request = FakeRequest(cookies={"cde_admin_session": "signed"})
        with patch.object(admin_session, "require_admin_session", return_value={"role": "admin", "username": "admin"}), \
             patch.object(admin_session, "DB_PATH", self.db_path):
            response = admin_session.admin_governed_inferences_page(request)
        self.assertEqual(response.status_code, 200)
        check = sqlite3.connect(self.db_path)
        self.assertIsNone(check.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='record_governed_inferences'").fetchone())
        check.close()

    def test_post_authentication_precedes_inference_writer(self):
        request = FakeRequest(cookies={})
        writer = Mock()
        with patch.object(admin_session, "require_admin_session", side_effect=FakeHTTPException(401, "admin_session_unauthorized")), \
             patch.object(admin_session.rgi, "create_inference", writer):
            with self.assertRaises(FakeHTTPException):
                admin_session.admin_governed_inference_create(
                    request,
                    inference_type="procedural",
                    proposition="A qualified proposition.",
                    rationale="A governed rationale.",
                    qualification="This is an inference, not evidence or a determination.",
                    limitations="Alternative interpretations remain possible.",
                    bindings_json='[{"source_type":"record_document_association","source_id":"1","binding_role":"primary_support"}]',
                    boundary_acknowledged="1",
                    idempotency_key="auth-before-write",
                )
        writer.assert_not_called()


if __name__ == "__main__":
    unittest.main()
