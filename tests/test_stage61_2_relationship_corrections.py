import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.test_admin_session import FakeHTTPException, FakeRequest, install_fastapi_stubs

install_fastapi_stubs()

from api import record_document_association_corrections as corrections
from api import record_document_association_decisions as decisions
from api import record_document_associations as associations
from api.routes import admin_session, associations as public_association_routes


class Stage612RelationshipCorrectionTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        associations.ensure_association_tables(self.conn)
        self.documents = {
            "wrong-document": {"intake_id": "wrong-document", "reference_identifier": "DOC-2026-000118"},
            "right-document": {"intake_id": "right-document", "reference_identifier": "DOC-2026-000123"},
            "new-document": {"intake_id": "new-document", "reference_identifier": "DOC-2026-000124"},
        }
        self.context = patch.multiple(
            associations,
            validate_public_record_reference=lambda conn, reference, root=None: reference,
            published_document_context=lambda document_id, root=None: self.documents.get(document_id),
            public_record_context=lambda conn, reference: {"reference": reference},
            record_has_authoritative_source=lambda record, conn=None: False,
        )
        self.context.start()

    def tearDown(self):
        self.context.stop()
        self.conn.close()

    def _create(self, document_id, *, key, record="REC-61-2", relationship="supporting_document"):
        return associations.create_association(
            self.conn,
            record_reference=record,
            document_id=document_id,
            relationship_type=relationship,
            public_label="Supporting document",
            public_note="Public relationship note",
            admin_note="Private relationship note",
            is_public=True,
            actor="nick",
            actor_role="admin",
            rationale="The relationship was reviewed.",
            idempotency_key=key,
            created_at="2026-08-11T14:00:00Z",
        )

    def _correct(self, original, replacement, *, key="correction-1", rationale="The persisted binding should no longer govern."):
        return corrections.correct_association(
            self.conn,
            original_association_id=original["id"],
            resolution_mode="reuse_existing",
            replacement_association_id=replacement["id"],
            rationale=rationale,
            actor="nick",
            actor_role="admin",
            evidence_references=[{"reference_type": "association_decision", "reference_id": str(original["id"])}],
            context_reference="stage-61-2-review",
            idempotency_key=key,
            decided_at="2026-08-11T15:00:00Z",
        )

    def test_reuse_preserves_original_and_records_correction_projection(self):
        original = self._create("wrong-document", key="original-1")
        replacement = self._create("right-document", key="replacement-1")
        before = dict(original)
        before_history = associations.association_history(self.conn, original["id"])
        before_decisions = decisions.list_decisions(self.conn, original["id"])

        correction = self._correct(original, replacement)

        current_original = associations.get_association(self.conn, original["id"])
        current_replacement = associations.get_association(self.conn, replacement["id"])
        after_decisions = decisions.list_decisions(self.conn, original["id"])
        after_history = associations.association_history(self.conn, original["id"])
        self.assertEqual(current_original["id"], before["id"])
        self.assertEqual(current_original["document_id"], before["document_id"])
        self.assertEqual(current_original["record_reference"], before["record_reference"])
        self.assertEqual(current_original["public_reference"], before["public_reference"])
        self.assertEqual(current_original["created_at"], before["created_at"])
        self.assertEqual(current_original["created_by"], before["created_by"])
        self.assertEqual(after_history[0], before_history[0])
        self.assertEqual(after_decisions[0], before_decisions[0])
        self.assertEqual(current_original["is_active"], 0)
        self.assertEqual(current_replacement["is_active"], 1)
        self.assertEqual(correction["replacement_association_id"], replacement["id"])
        self.assertNotEqual(correction["idempotency_key"], str(original["id"]))
        self.assertEqual(correction["original_decision_id"], decisions.list_decisions(self.conn, original["id"])[0]["id"])
        adapted = corrections.adapt_correction(correction)
        self.assertEqual(adapted.decision_id, f"record-document-association-correction:{correction['id']}")
        self.assertNotEqual(adapted.decision_id, str(original["id"]))
        self.assertEqual(adapted.subject.subject_id, str(original["id"]))
        self.assertEqual(adapted.decision_type, "association_corrected")
        self.assertEqual(
            [item["decision_type"] for item in decisions.list_decisions(self.conn, original["id"])],
            ["association_created", "association_deactivated"],
        )

    def test_retry_is_idempotent_and_semantic_conflict_fails_closed(self):
        original = self._create("wrong-document", key="original-2")
        replacement = self._create("right-document", key="replacement-2")
        first = self._correct(original, replacement, key="correction-retry")
        retry = self._correct(original, replacement, key="correction-retry")
        self.assertEqual(retry["id"], first["id"])
        self.assertEqual(len(corrections.list_corrections(self.conn, original["id"])), 1)
        self.assertEqual(len(decisions.list_decisions(self.conn, original["id"])), 2)
        with self.assertRaisesRegex(ValueError, "idempotency_conflict"):
            self._correct(original, replacement, key="correction-retry", rationale="A different determination.")
        self.assertEqual(associations.get_association(self.conn, original["id"])["is_active"], 0)

    def test_replacement_validation_and_missing_original_decision_fail_closed(self):
        original = self._create("wrong-document", key="original-3")
        inactive = self._create("right-document", key="replacement-3")
        associations.deactivate_association(
            self.conn, inactive["id"], actor="nick", actor_role="admin",
            note="Inactive replacement", rationale="It is not active.", idempotency_key="inactive-3"
        )
        with self.assertRaisesRegex(ValueError, "replacement_inactive"):
            self._correct(original, inactive, key="correction-inactive")
        with self.assertRaisesRegex(ValueError, "replacement_is_original"):
            self._correct(original, original, key="correction-original")
        self.conn.execute("DELETE FROM record_document_association_decisions WHERE association_id = ?", (original["id"],))
        self.conn.commit()
        with self.assertRaisesRegex(ValueError, "original_decision_missing"):
            self._correct(original, inactive, key="correction-missing")
        self.assertEqual(len(corrections.list_corrections(self.conn, original["id"])), 0)

    def test_inactive_original_fails_closed_but_committed_retry_reuses_result(self):
        original = self._create("wrong-document", key="original-inactive")
        replacement = self._create("right-document", key="replacement-inactive")
        first = self._correct(original, replacement, key="correction-inactive-original")
        retry = self._correct(original, replacement, key="correction-inactive-original")
        self.assertEqual(retry["id"], first["id"])
        with self.assertRaisesRegex(ValueError, "original_inactive"):
            self._correct(original, replacement, key="new-correction-after-deactivation")

    def test_create_new_is_atomic_and_uses_distinct_child_keys(self):
        original = self._create("wrong-document", key="original-4")
        correction = corrections.correct_association(
            self.conn,
            original_association_id=original["id"],
            resolution_mode="create_new",
            replacement_record_reference="REC-61-2",
            replacement_document_id="new-document",
            replacement_relationship_type="related_document",
            rationale="Create the explicitly selected correct relationship.",
            actor="nick",
            actor_role="admin",
            idempotency_key="correction-new",
            decided_at="2026-08-11T16:00:00Z",
        )
        replacement = associations.get_association(self.conn, correction["replacement_association_id"])
        self.assertEqual(replacement["document_id"], "new-document")
        self.assertEqual(replacement["relationship_type"], "related_document")
        self.assertEqual(associations.get_association(self.conn, original["id"])["is_active"], 0)
        self.assertEqual(
            [item["idempotency_key"] for item in decisions.list_decisions(self.conn, original["id"])],
            ["original-4", "correction-new:deactivation"],
        )
        self.assertEqual(decisions.list_decisions(self.conn, replacement["id"])[0]["idempotency_key"], "correction-new:creation")
        retry = corrections.correct_association(
            self.conn,
            original_association_id=original["id"],
            resolution_mode="create_new",
            replacement_record_reference="REC-61-2",
            replacement_document_id="new-document",
            replacement_relationship_type="related_document",
            rationale="Create the explicitly selected correct relationship.",
            actor="nick",
            actor_role="admin",
            idempotency_key="correction-new",
        )
        self.assertEqual(retry["id"], correction["id"])
        self.assertEqual(len(corrections.list_corrections(self.conn, original["id"])), 1)
        self.assertEqual(len(decisions.list_decisions(self.conn, replacement["id"])), 1)

    def test_reader_does_not_initialize_correction_table(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "records.db"
            file_conn = sqlite3.connect(path)
            file_conn.row_factory = sqlite3.Row
            associations.ensure_association_tables(file_conn)
            file_conn.commit()
            file_conn.close()

            preview = corrections.read_correction_preview(1, db_path=path)

            self.assertEqual(preview["status"], "association_not_found")
            check = sqlite3.connect(path)
            self.assertIsNone(check.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                ("record_document_association_corrections",),
            ).fetchone())
            check.close()

    def test_failure_rolls_back_correction_and_deactivation(self):
        original = self._create("wrong-document", key="original-5")
        replacement = self._create("right-document", key="replacement-5")
        with patch.object(associations, "deactivate_association", side_effect=RuntimeError("injected")):
            with self.assertRaisesRegex(RuntimeError, "injected"):
                self._correct(original, replacement, key="correction-rollback")
        self.assertEqual(associations.get_association(self.conn, original["id"])["is_active"], 1)
        self.assertEqual(len(corrections.list_corrections(self.conn, original["id"])), 0)
        self.assertEqual(len(decisions.list_decisions(self.conn, original["id"])), 1)

    def test_correction_routes_authenticate_before_reader_or_writer(self):
        request = FakeRequest()
        auth_error = FakeHTTPException(401, "admin_session_unauthorized")
        with patch.object(admin_session, "require_admin_session", side_effect=auth_error), patch.object(
            corrections, "read_correction_preview"
        ) as reader:
            with self.assertRaises(FakeHTTPException):
                admin_session.admin_association_correction_page(1, request)
            reader.assert_not_called()
        with patch.object(admin_session, "require_admin_session", side_effect=auth_error), patch.object(
            corrections, "correct_association"
        ) as writer:
            with self.assertRaises(FakeHTTPException):
                admin_session.admin_association_correction(
                    1,
                    request,
                    resolution_mode="reuse_existing",
                    replacement_association_id=2,
                    rationale="Denied before evidence access.",
                )
            writer.assert_not_called()

    def test_authenticated_preview_does_not_initialize_or_mutate_correction_persistence(self):
        original = self._create("wrong-document", key="preview-original")
        replacement = self._create("right-document", key="preview-replacement")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "records.db"
            source = sqlite3.connect(path)
            self.conn.backup(source)
            source.commit()
            source.close()
            before_history = associations.association_history(self.conn, original["id"])
            before_decisions = decisions.list_decisions(self.conn, original["id"])
            with patch.object(admin_session, "require_admin_session", return_value={"username": "nick", "role": "admin"}), patch.object(
                admin_session, "DB_PATH", path
            ), patch.object(admin_session.rdd, "read_association_decision_diagnostic", return_value={"decisions": [], "warnings": []}):
                response = admin_session.admin_association_correction_page(
                    original["id"], FakeRequest(cookies={"cde_admin_session": "valid"})
                )
            self.assertEqual(response.status_code, 200)
            check = sqlite3.connect(path)
            self.assertIsNone(check.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                ("record_document_association_corrections",),
            ).fetchone())
            check.close()
            self.assertEqual(associations.get_association(self.conn, original["id"])["is_active"], 1)
            self.assertEqual(associations.get_association(self.conn, replacement["id"])["is_active"], 1)
            self.assertEqual(associations.association_history(self.conn, original["id"]), before_history)
            self.assertEqual(decisions.list_decisions(self.conn, original["id"]), before_decisions)

    def test_public_association_surface_excludes_correction_evidence(self):
        original = self._create("wrong-document", key="public-original")
        replacement = self._create("right-document", key="public-replacement")
        correction = self._correct(original, replacement, key="public-correction")
        secret_values = [
            "erroneous_association_binding",
            "The persisted binding should no longer govern.",
            "association_decision",
            "stage-61-2-review",
            "public-correction",
        ]
        item = {
            "public_reference": original["public_reference"],
            "relationship_type": original["relationship_type"],
            "public_label": original["public_label"],
            "public_note": original["public_note"],
            "created_at": original["created_at"],
            "created_by": original["created_by"],
            "is_active": 0,
            "is_public": original["is_public"],
            "record_reference": original["record_reference"],
            "document_id": original["document_id"],
            "document_title": "Published document",
            "document_reference_identifier": "DOC-2026-000118",
        }
        html = public_association_routes._render_association_page(item, [])
        self.assertIn(original["public_reference"], html)
        for value in secret_values:
            self.assertNotIn(value, html)
        for label in ("Correction ID", "Correction category", "Original decision ID", "Correction rationale", "Evidence references", "Context reference", "Idempotency key"):
            self.assertNotIn(label, html)
        self.assertNotIn("replacement_association_id", html)

    def _assert_rolled_back(self, original, replacement, before_history, before_decisions, key):
        self.assertEqual(associations.get_association(self.conn, original["id"])["is_active"], 1)
        self.assertEqual(associations.get_association(self.conn, original["id"])["document_id"], "wrong-document")
        self.assertEqual(associations.get_association(self.conn, replacement["id"])["is_active"], 1)
        self.assertEqual(associations.association_history(self.conn, original["id"]), before_history)
        self.assertEqual(decisions.list_decisions(self.conn, original["id"]), before_decisions)
        self.assertEqual(len(corrections.list_corrections(self.conn, original["id"])), 0)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM record_document_associations WHERE id > ?", (replacement["id"],)).fetchone()[0],
            0,
        )

    def test_deactivation_history_failure_rolls_back_every_consequence(self):
        original = self._create("wrong-document", key="history-original")
        replacement = self._create("right-document", key="history-replacement")
        before_history = associations.association_history(self.conn, original["id"])
        before_decisions = decisions.list_decisions(self.conn, original["id"])
        with patch.object(associations, "_record_history", side_effect=RuntimeError("history failure")):
            with self.assertRaisesRegex(RuntimeError, "history failure"):
                self._correct(original, replacement, key="history-failure")
        self._assert_rolled_back(original, replacement, before_history, before_decisions, "history-failure")

    def test_deactivation_decision_failure_rolls_back_every_consequence(self):
        original = self._create("wrong-document", key="decision-original")
        replacement = self._create("right-document", key="decision-replacement")
        before_history = associations.association_history(self.conn, original["id"])
        before_decisions = decisions.list_decisions(self.conn, original["id"])
        real_record = decisions.record_decision

        def fail_deactivation(*args, **kwargs):
            if kwargs.get("decision_type") == "association_deactivated":
                raise RuntimeError("decision failure")
            return real_record(*args, **kwargs)

        with patch.object(decisions, "record_decision", side_effect=fail_deactivation):
            with self.assertRaisesRegex(RuntimeError, "decision failure"):
                self._correct(original, replacement, key="decision-failure")
        self._assert_rolled_back(original, replacement, before_history, before_decisions, "decision-failure")

    def test_create_new_persistence_boundaries_roll_back(self):
        failure_cases = ("create", "replacement_history", "replacement_decision", "linkage")
        for failure in failure_cases:
            with self.subTest(failure=failure):
                record = f"REC-61-2-{failure}"
                original = self._create("wrong-document", key=f"boundary-original-{failure}", record=record)
                before_history = associations.association_history(self.conn, original["id"])
                before_decisions = decisions.list_decisions(self.conn, original["id"])
                if failure == "create":
                    failure_patch = patch.object(associations, "create_association", side_effect=RuntimeError("create failure"))
                elif failure == "replacement_history":
                    calls = {"count": 0}
                    real_history = associations._record_history

                    def fail_second_history(*args, **kwargs):
                        calls["count"] += 1
                        if calls["count"] == 2:
                            raise RuntimeError("replacement history failure")
                        return real_history(*args, **kwargs)

                    failure_patch = patch.object(associations, "_record_history", side_effect=fail_second_history)
                elif failure == "replacement_decision":
                    real_record = decisions.record_decision

                    def fail_creation_decision(*args, **kwargs):
                        if kwargs.get("decision_type") == "association_created":
                            raise RuntimeError("replacement decision failure")
                        return real_record(*args, **kwargs)

                    failure_patch = patch.object(decisions, "record_decision", side_effect=fail_creation_decision)
                else:
                    calls = {"count": 0}
                    real_get = corrections.get_correction

                    def fail_linkage(*args, **kwargs):
                        calls["count"] += 1
                        if calls["count"] == 2:
                            raise RuntimeError("linkage failure")
                        return real_get(*args, **kwargs)

                    failure_patch = patch.object(corrections, "get_correction", side_effect=fail_linkage)
                with failure_patch:
                    with self.assertRaisesRegex(RuntimeError, "failure"):
                        corrections.correct_association(
                            self.conn,
                            original_association_id=original["id"],
                            resolution_mode="create_new",
                            replacement_record_reference=record,
                            replacement_document_id="new-document",
                            replacement_relationship_type="related_document",
                            rationale="Boundary failure test.",
                            actor="nick",
                            actor_role="admin",
                            idempotency_key=f"boundary-{failure}",
                        )
                self.assertEqual(associations.get_association(self.conn, original["id"])["is_active"], 1)
                self.assertEqual(associations.association_history(self.conn, original["id"]), before_history)
                self.assertEqual(decisions.list_decisions(self.conn, original["id"]), before_decisions)
                self.assertEqual(len(corrections.list_corrections(self.conn, original["id"])), 0)
                self.assertEqual(
                    self.conn.execute(
                        "SELECT COUNT(*) FROM record_document_associations WHERE record_reference = ?",
                        (record,),
                    ).fetchone()[0],
                    1,
                )

    def test_legacy_association_requires_explicit_acknowledgement_without_synthetic_evidence(self):
        original = self._create("wrong-document", key="legacy-original")
        self.conn.execute("DELETE FROM record_document_association_decisions WHERE association_id = ?", (original["id"],))
        self.conn.commit()
        replacement = self._create("right-document", key="legacy-replacement")
        self.conn.execute("DELETE FROM record_document_association_decisions WHERE association_id = ?", (replacement["id"],))
        self.conn.commit()
        with self.assertRaisesRegex(ValueError, "original_decision_missing"):
            self._correct(original, replacement, key="legacy-denied")
        correction = corrections.correct_association(
            self.conn,
            original_association_id=original["id"],
            resolution_mode="reuse_existing",
            replacement_association_id=replacement["id"],
            rationale="Legacy association reviewed without fabricating historical decision evidence.",
            actor="nick",
            actor_role="admin",
            idempotency_key="legacy-approved",
            legacy_evidence_acknowledged=True,
        )
        self.assertIsNone(correction["original_decision_id"])
        self.assertEqual(decisions.list_decisions(self.conn, original["id"])[0]["decision_type"], "association_deactivated")
        self.assertEqual(len(associations.association_history(self.conn, original["id"])), 2)

    def test_multiple_replacement_candidates_require_exact_selection(self):
        original = self._create("wrong-document", key="candidate-original")
        first = self._create("right-document", key="candidate-first")
        second = self._create("new-document", key="candidate-second")
        before = associations.association_history(self.conn, original["id"])
        with self.assertRaisesRegex(ValueError, "replacement_required"):
            corrections.correct_association(
                self.conn,
                original_association_id=original["id"],
                resolution_mode="reuse_existing",
                rationale="An exact replacement must be selected.",
                actor="nick",
                actor_role="admin",
                idempotency_key="candidate-ambiguous",
            )
        self.assertEqual(associations.get_association(self.conn, original["id"])["is_active"], 1)
        self.assertEqual(associations.association_history(self.conn, original["id"]), before)
        self.assertEqual(len(corrections.list_corrections(self.conn, original["id"])), 0)
        self.assertEqual(associations.get_association(self.conn, first["id"])["is_active"], 1)
        self.assertEqual(associations.get_association(self.conn, second["id"])["is_active"], 1)


if __name__ == "__main__":
    unittest.main()
