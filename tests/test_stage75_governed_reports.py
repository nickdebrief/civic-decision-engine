import json
import importlib
import re
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from api import record_governed_reports as reports
from api.report_rendering import render_frozen_report


class Stage75PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.record = {"reference": "CR-1", "title": "Canonical record", "finding": "Original wording", "status": "recorded", "version": 1}
        self.artifact_root = tempfile.TemporaryDirectory()
        reports.REPORT_ROOT = Path(self.artifact_root.name)

    def tearDown(self):
        self.conn.close()
        self.artifact_root.cleanup()

    def create(self, **overrides):
        values = dict(title="Internal report", purpose="Review selected record", audience="Administrators", distribution_class="internal_working", canonical_record_reference="CR-1", document_ids=[], association_ids=[], sections=[{"title": "Record", "blocks": [{"content_type": "verbatim_source", "text": "Original wording", "source_identity": {"object_kind": "canonical_record", "object_id": "CR-1"}, "inclusion_rationale": "Deliberately selected."}]}], exclusions=[], requested_formats=["docx", "html"], rendering_profile="internal", template_version="cde-internal-v1", actor="creator", actor_role="administrator", idempotency_key="create-1")
        values.update(overrides)
        return reports.create_report(self.conn, **values)

    @patch.object(reports.rda, "record_context")
    def test_frozen_specification_and_idempotent_replay(self, record_context):
        record_context.return_value = self.record
        item = self.create()
        replay = self.create()
        self.assertEqual(item["id"], replay["id"])
        self.assertEqual(item["versions"][0]["publication_engine_version"], "2.0.0")
        self.assertEqual(len(item["versions"][0]["specification_digest"]), 64)
        with self.assertRaisesRegex(ValueError, "idempotency_conflict"):
            self.create(title="Changed title")

    @patch.object(reports.rda, "record_context")
    def test_controlled_formats_and_unknown_fields_fail_before_persistence(self, record_context):
        record_context.return_value = self.record
        with self.assertRaisesRegex(ValueError, "companion_formats_required"):
            self.create(requested_formats=["pdf"])
        for malformed in (["PDF", "docx", "html"], [" pdf", "docx", "html"], ["docx", "html", "DOCX"]):
            with self.assertRaisesRegex(ValueError, "output_formats_invalid"):
                self.create(requested_formats=malformed)
        with self.assertRaisesRegex(ValueError, "block_invalid"):
            self.create(sections=[{"title": "Record", "blocks": [{"content_type": "verbatim_source", "text": "x", "source_identity": {"object_kind": "canonical_record", "object_id": "CR-1"}, "inclusion_rationale": "x", "unknown": True}]}])
        self.assertEqual(reports.list_reports(self.conn), [])

    @patch.object(reports.rda, "record_context")
    def test_block_cannot_reference_unselected_object(self, record_context):
        record_context.return_value = self.record
        with self.assertRaisesRegex(ValueError, "block_source_mismatch"):
            self.create(sections=[{"title": "Record", "blocks": [{"content_type": "verbatim_source", "text": "Private", "source_identity": {"object_kind": "published_document", "object_id": "not-selected"}, "inclusion_rationale": "Attempted injection."}]}])

    @patch.object(reports.rda, "record_context")
    def test_digest_canonicalizes_mapping_order_and_unordered_formats_but_not_sections(self, record_context):
        record_context.return_value = self.record
        item = self.create(requested_formats=["html", "docx"])
        specification = item["versions"][0]["specification"]
        reordered = {key: specification[key] for key in reversed(list(specification))}
        reordered["requested_formats"] = ["docx", "html"]
        self.assertEqual(reports.specification_digest(specification), reports.specification_digest(reordered))
        changed = json.loads(json.dumps(specification))
        changed["sections"] = [{"order": 0, "title": "First", "blocks": [{"order": 0, "content_type": "qualification", "text": "First", "source_identity": {"object_kind": "canonical_record", "object_id": "CR-1"}, "attribution": "", "inclusion_rationale": "Selected."}]}, {"order": 1, "title": "Second", "blocks": [{"order": 0, "content_type": "limitation", "text": "Second", "source_identity": {"object_kind": "canonical_record", "object_id": "CR-1"}, "attribution": "", "inclusion_rationale": "Selected."}]}]
        original = json.loads(json.dumps(specification))
        original["sections"] = list(changed["sections"])
        changed["sections"] = list(reversed(changed["sections"]))
        self.assertNotEqual(reports.specification_digest(original), reports.specification_digest(changed))
        with self.assertRaisesRegex(ValueError, "output_formats_invalid"):
            self.create(requested_formats=["docx", "docx"])

    @patch.object(reports.rda, "record_context")
    def test_create_key_conflicts_on_actor_and_material_payload(self, record_context):
        record_context.return_value = self.record
        self.create()
        with self.assertRaisesRegex(ValueError, "idempotency_conflict"):
            self.create(actor="different-actor")
        with self.assertRaisesRegex(ValueError, "idempotency_conflict"):
            self.create(purpose="Different purpose")

    @patch.object(reports.rda, "record_context")
    def test_review_actor_separation_and_append_only_lifecycle(self, record_context):
        record_context.return_value = self.record
        item = self.create()
        with self.assertRaisesRegex(ValueError, "actor_must_differ"):
            reports.transition_report(self.conn, report_id=item["id"], resulting_status="assembly_reviewed", rationale="Reviewed assembly", actor="creator", actor_role="administrator", declaration={"acknowledged": True}, idempotency_key="review-1")
        item = reports.transition_report(self.conn, report_id=item["id"], resulting_status="assembly_reviewed", rationale="Reviewed assembly", actor="reviewer", actor_role="administrator", declaration={"acknowledged": True}, idempotency_key="review-1")
        self.assertEqual(item["lifecycle_status"], "assembly_reviewed")
        self.assertEqual(item["events"][0]["event_type"], "created")
        self.assertEqual(item["events"][1]["resulting_status"], "assembly_reviewed")

    @patch.object(reports.rda, "record_context")
    def test_invalid_transition_matrix_and_terminal_replay(self, record_context):
        record_context.return_value = self.record
        item = self.create()
        with self.assertRaisesRegex(ValueError, "transition_invalid"):
            reports.transition_report(self.conn, report_id=item["id"], resulting_status="generated", rationale="No", actor="reviewer", actor_role="administrator", declaration={"acknowledged": True}, idempotency_key="invalid-1")
        with self.assertRaisesRegex(ValueError, "transition_invalid"):
            reports.transition_report(self.conn, report_id=item["id"], resulting_status="superseded", rationale="No", actor="reviewer", actor_role="administrator", declaration={"acknowledged": True}, idempotency_key="invalid-2")
        item = reports.transition_report(self.conn, report_id=item["id"], resulting_status="withdrawn", rationale="Withdrawn deliberately", actor="creator", actor_role="administrator", declaration={"acknowledged": True}, idempotency_key="withdraw-1")
        replay = reports.transition_report(self.conn, report_id=item["id"], resulting_status="withdrawn", rationale="Withdrawn deliberately", actor="creator", actor_role="administrator", declaration={"acknowledged": True}, idempotency_key="withdraw-1")
        self.assertEqual(replay["lifecycle_status"], "withdrawn")
        with self.assertRaisesRegex(ValueError, "transition_invalid"):
            reports.transition_report(self.conn, report_id=item["id"], resulting_status="assembly_reviewed", rationale="Late", actor="reviewer", actor_role="administrator", declaration={"acknowledged": True}, idempotency_key="late-1")

    @patch.object(reports.rda, "record_context")
    def test_supersession_requires_distinct_same_record_and_prevents_self_reference(self, record_context):
        record_context.return_value = self.record
        source = self.create(idempotency_key="source")
        replacement = self.create(idempotency_key="replacement", title="Replacement report")
        with self.assertRaisesRegex(ValueError, "target_invalid"):
            reports.supersede_report(self.conn, report_id=source["id"], replacement_report_id=source["id"], rationale="Self", actor="admin", actor_role="administrator", declaration={"acknowledged": True}, idempotency_key="self")
        result = reports.supersede_report(self.conn, report_id=source["id"], replacement_report_id=replacement["id"], rationale="Correction", actor="admin", actor_role="administrator", declaration={"acknowledged": True}, idempotency_key="supersede")
        self.assertEqual(result["lifecycle_status"], "superseded")
        replay = reports.supersede_report(self.conn, report_id=source["id"], replacement_report_id=replacement["id"], rationale="Correction", actor="admin", actor_role="administrator", declaration={"acknowledged": True}, idempotency_key="supersede")
        self.assertEqual(len(replay["events"]), len(result["events"]))

    @patch.object(reports.rda, "record_context")
    def test_specification_digest_mismatch_is_rejected(self, record_context):
        record_context.return_value = self.record
        item = self.create()
        for status, actor, key in (("assembly_reviewed", "reviewer", "review-digest"), ("privacy_reviewed", "privacy", "privacy-digest"), ("redaction_reviewed", "redactor", "redaction-digest"), ("approved_for_generation", "approver", "approve-digest")):
            item = reports.transition_report(self.conn, report_id=item["id"], resulting_status=status, rationale="Deliberate review", actor=actor, actor_role="administrator", declaration={"acknowledged": True}, idempotency_key=key)
        self.conn.execute("UPDATE record_governed_report_versions SET specification_json=? WHERE id=?", (json.dumps({"tampered": True}), item["versions"][0]["id"]))
        self.conn.commit()
        with self.assertRaisesRegex(ValueError, "digest_mismatch"):
            reports.generate_report(self.conn, report_id=item["id"], actor="generator", actor_role="administrator", idempotency_key="generation-1")

    @patch.object(reports.rda, "record_context")
    def test_creation_rolls_back_after_report_row_before_version(self, record_context):
        record_context.return_value = self.record
        reports.ensure_report_tables(self.conn)
        self.conn.execute("CREATE TRIGGER fail_stage75_version BEFORE INSERT ON record_governed_report_versions BEGIN SELECT RAISE(ABORT, 'controlled failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.create()
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM record_governed_reports").fetchone()[0], 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM record_governed_report_events").fetchone()[0], 0)

    @patch.object(reports.rda, "record_context")
    def test_generation_request_rolls_back_all_rows_after_attempt_write_failure(self, record_context):
        record_context.return_value = self.record
        item = self.create()
        for status, actor, key in (("assembly_reviewed", "reviewer", "request-assembly"), ("privacy_reviewed", "privacy", "request-privacy"), ("redaction_reviewed", "redactor", "request-redaction"), ("approved_for_generation", "approver", "request-approval")):
            item = reports.transition_report(self.conn, report_id=item["id"], resulting_status=status, rationale="Review", actor=actor, actor_role="administrator", declaration={"acknowledged": True}, idempotency_key=key)
        self.conn.execute("CREATE TRIGGER fail_stage75_generation_event BEFORE INSERT ON record_governed_report_events WHEN NEW.event_type='generation_requested' BEGIN SELECT RAISE(ABORT, 'controlled generation failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            reports.generate_report(self.conn, report_id=item["id"], actor="generator", actor_role="administrator", idempotency_key="request-generation")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM record_governed_report_generation_attempts").fetchone()[0], 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM record_governed_report_events WHERE event_type='generation_requested'").fetchone()[0], 0)
        self.assertEqual(reports.get_report(self.conn, item["id"])["lifecycle_status"], "approved_for_generation")

    @patch.object(reports.rda, "record_context")
    def test_lifecycle_event_savepoint_rolls_back_status_and_event(self, record_context):
        record_context.return_value = self.record
        item = self.create()
        self.conn.execute("CREATE TRIGGER fail_stage75_lifecycle_event BEFORE INSERT ON record_governed_report_events WHEN NEW.event_type='assembly_reviewed' BEGIN SELECT RAISE(ABORT, 'controlled lifecycle failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            reports.transition_report(self.conn, report_id=item["id"], resulting_status="assembly_reviewed", rationale="Review", actor="reviewer", actor_role="administrator", declaration={"acknowledged": True}, idempotency_key="lifecycle-rollback")
        retained = reports.get_report(self.conn, item["id"])
        self.assertEqual(retained["lifecycle_status"], "draft_specification")
        self.assertEqual(len(retained["events"]), 1)
        self.conn.execute("DROP TRIGGER fail_stage75_lifecycle_event")
        retried = reports.transition_report(self.conn, report_id=item["id"], resulting_status="assembly_reviewed", rationale="Review", actor="reviewer", actor_role="administrator", declaration={"acknowledged": True}, idempotency_key="lifecycle-rollback")
        self.assertEqual(retried["lifecycle_status"], "assembly_reviewed")

    @patch.object(reports.rda, "record_context")
    def test_artifact_registration_failure_rolls_back_artifacts_and_cleans_files(self, record_context):
        record_context.return_value = self.record
        item = self.create()
        for status, actor, key in (("assembly_reviewed", "reviewer", "artifact-assembly"), ("privacy_reviewed", "privacy", "artifact-privacy"), ("redaction_reviewed", "redactor", "artifact-redaction"), ("approved_for_generation", "approver", "artifact-approval")):
            item = reports.transition_report(self.conn, report_id=item["id"], resulting_status=status, rationale="Review", actor=actor, actor_role="administrator", declaration={"acknowledged": True}, idempotency_key=key)
        def fake_render(specification, digest, output_dir):
            output_dir.mkdir(parents=True, exist_ok=True)
            path = output_dir / "report.docx"
            path.write_text("validated", encoding="utf-8")
            return {"artifacts": [{"format": "docx", "path": str(path), "sha256": __import__("hashlib").sha256(path.read_bytes()).hexdigest(), "size_bytes": path.stat().st_size, "renderer_version": "2.0.0"}], "diagnostics": []}
        self.conn.execute("CREATE TRIGGER fail_stage75_artifact_registration BEFORE INSERT ON record_governed_report_artifacts BEGIN SELECT RAISE(ABORT, 'controlled artifact failure'); END")
        with patch("api.report_rendering.render_frozen_report", side_effect=fake_render):
            with self.assertRaisesRegex(ValueError, "artifact_registration_failed"):
                reports.generate_report(self.conn, report_id=item["id"], actor="generator", actor_role="administrator", idempotency_key="artifact-registration")
        retained = reports.get_report(self.conn, item["id"])
        self.assertEqual(retained["artifacts"], [])
        self.assertEqual(retained["lifecycle_status"], "validation_failed")
        self.assertFalse((reports.REPORT_ROOT / str(item["id"])).exists())

    @patch.object(reports.rda, "record_context")
    def test_generation_revalidates_primary_record_after_approval(self, record_context):
        record_context.side_effect = [self.record, self.record | {"finding": "Changed after assembly"}]
        item = self.create()
        for status, actor, key in (("assembly_reviewed", "reviewer", "stale-assembly"), ("privacy_reviewed", "privacy", "stale-privacy"), ("redaction_reviewed", "redactor", "stale-redaction"), ("approved_for_generation", "approver", "stale-approval")):
            item = reports.transition_report(self.conn, report_id=item["id"], resulting_status=status, rationale="Review", actor=actor, actor_role="administrator", declaration={"acknowledged": True}, idempotency_key=key)
        with self.assertRaisesRegex(ValueError, "canonical_record_changed"):
            reports.generate_report(self.conn, report_id=item["id"], actor="generator", actor_role="administrator", idempotency_key="stale-generation")

    @patch.object(reports.rda, "published_document_context")
    @patch.object(reports.rda, "record_context")
    def test_generation_revalidates_selected_document_presence_and_digest(self, record_context, document_context):
        record_context.return_value = self.record
        document = {"document_id": "DOC-1", "title": "Selected source", "status": "published", "sha256_hash": "a" * 64, "document_identifier": "DOC-1"}
        document_context.side_effect = [document, None]
        item = self.create(document_ids=["DOC-1"], sections=[{"title": "Source", "blocks": [{"content_type": "verbatim_source", "text": "Selected source text", "source_identity": {"object_kind": "published_document", "object_id": "DOC-1"}, "inclusion_rationale": "Selected deliberately."}]}])
        for status, actor, key in (("assembly_reviewed", "reviewer", "source-assembly"), ("privacy_reviewed", "privacy", "source-privacy"), ("redaction_reviewed", "redactor", "source-redaction"), ("approved_for_generation", "approver", "source-approval")):
            item = reports.transition_report(self.conn, report_id=item["id"], resulting_status=status, rationale="Review", actor=actor, actor_role="administrator", declaration={"acknowledged": True}, idempotency_key=key)
        with self.assertRaisesRegex(ValueError, "published_document_ineligible|source_changed_or_hash_mismatch"):
            reports.generate_report(self.conn, report_id=item["id"], actor="generator", actor_role="administrator", idempotency_key="source-generation")
        self.assertEqual(reports.get_report(self.conn, item["id"])["artifacts"], [])

    @patch.object(reports.rda, "published_document_context")
    @patch.object(reports.rda, "record_context")
    def test_generation_rejects_changed_selected_document_digest(self, record_context, document_context):
        record_context.return_value = self.record
        document_context.side_effect = [
            {"document_id": "DOC-2", "title": "Selected source", "status": "published", "sha256_hash": "b" * 64, "document_identifier": "DOC-2"},
            {"document_id": "DOC-2", "title": "Selected source", "status": "published", "sha256_hash": "c" * 64, "document_identifier": "DOC-2"},
        ]
        item = self.create(document_ids=["DOC-2"])
        for status, actor, key in (("assembly_reviewed", "reviewer", "digest-assembly"), ("privacy_reviewed", "privacy", "digest-privacy"), ("redaction_reviewed", "redactor", "digest-redaction"), ("approved_for_generation", "approver", "digest-approval")):
            item = reports.transition_report(self.conn, report_id=item["id"], resulting_status=status, rationale="Review", actor=actor, actor_role="administrator", declaration={"acknowledged": True}, idempotency_key=key)
        with self.assertRaisesRegex(ValueError, "source_changed_or_hash_mismatch"):
            reports.generate_report(self.conn, report_id=item["id"], actor="generator", actor_role="administrator", idempotency_key="digest-generation")

    @patch.object(reports, "_association_snapshot")
    @patch.object(reports.rda, "record_context")
    def test_generation_revalidates_removed_deactivated_and_relinked_association(self, record_context, association_snapshot):
        record_context.return_value = self.record
        selected = {"association_id": 7, "record_reference": "CR-1", "document_id": "DOC-7", "relationship_type": "context", "document_sha256": "d" * 64}
        cases = [
            (ValueError("governed_report_association_not_found"), "removed"),
            (ValueError("governed_report_association_ineligible"), "deactivated"),
            (selected | {"record_reference": "CR-2"}, "relinked"),
        ]
        for invalid_snapshot, label in cases:
            with self.subTest(label=label):
                association_snapshot.side_effect = [selected, invalid_snapshot]
                item = self.create(association_ids=["7"], sections=[{"title": "Association", "blocks": [{"content_type": "verbatim_source", "text": "Association context", "source_identity": {"object_kind": "record_document_association", "object_id": "7"}, "inclusion_rationale": "Selected deliberately."}]}], idempotency_key=f"association-{label}")
                for status, actor, key in (("assembly_reviewed", "reviewer", f"{label}-assembly"), ("privacy_reviewed", "privacy", f"{label}-privacy"), ("redaction_reviewed", "redactor", f"{label}-redaction"), ("approved_for_generation", "approver", f"{label}-approval")):
                    item = reports.transition_report(self.conn, report_id=item["id"], resulting_status=status, rationale="Review", actor=actor, actor_role="administrator", declaration={"acknowledged": True}, idempotency_key=key)
                with self.assertRaisesRegex(ValueError, "association_not_found|association_ineligible|association_changed"):
                    reports.generate_report(self.conn, report_id=item["id"], actor="generator", actor_role="administrator", idempotency_key=f"{label}-generation")
                self.assertEqual(reports.get_report(self.conn, item["id"])["artifacts"], [])

    @patch.object(reports.rda, "record_context")
    def test_renderer_failure_is_retained_without_artifact(self, record_context):
        record_context.return_value = self.record
        item = self.create()
        for status, actor, key in (("assembly_reviewed", "reviewer", "fail-assembly"), ("privacy_reviewed", "privacy", "fail-privacy"), ("redaction_reviewed", "redactor", "fail-redaction"), ("approved_for_generation", "approver", "fail-approval")):
            item = reports.transition_report(self.conn, report_id=item["id"], resulting_status=status, rationale="Review", actor=actor, actor_role="administrator", declaration={"acknowledged": True}, idempotency_key=key)
        with patch("api.report_rendering.render_frozen_report", side_effect=ValueError("renderer failed")):
            with self.assertRaisesRegex(ValueError, "generation_failed"):
                reports.generate_report(self.conn, report_id=item["id"], actor="generator", actor_role="administrator", idempotency_key="failed-generation")
        retained = reports.get_report(self.conn, item["id"])
        self.assertEqual(retained["lifecycle_status"], "validation_failed")
        self.assertEqual(retained["artifacts"], [])
        with patch("api.report_rendering.render_frozen_report") as renderer:
            with self.assertRaisesRegex(ValueError, "generation_failed"):
                reports.generate_report(self.conn, report_id=item["id"], actor="generator", actor_role="administrator", idempotency_key="failed-generation")
            renderer.assert_not_called()

    @patch.object(reports.rda, "record_context")
    def test_partial_renderer_output_is_removed_on_failure(self, record_context):
        record_context.return_value = self.record
        item = self.create()
        for status, actor, key in (("assembly_reviewed", "reviewer", "partial-assembly"), ("privacy_reviewed", "privacy", "partial-privacy"), ("redaction_reviewed", "redactor", "partial-redaction"), ("approved_for_generation", "approver", "partial-approval")):
            item = reports.transition_report(self.conn, report_id=item["id"], resulting_status=status, rationale="Review", actor=actor, actor_role="administrator", declaration={"acknowledged": True}, idempotency_key=key)
        def fail_after_partial(*_args, **_kwargs):
            target = reports.REPORT_ROOT / str(item["id"]) / "1"
            target.mkdir(parents=True)
            (target / "report.docx").write_text("partial", encoding="utf-8")
            raise ValueError("failed after docx")
        with patch("api.report_rendering.render_frozen_report", side_effect=fail_after_partial):
            with self.assertRaisesRegex(ValueError, "generation_failed"):
                reports.generate_report(self.conn, report_id=item["id"], actor="generator", actor_role="administrator", idempotency_key="partial-generation")
        self.assertFalse((reports.REPORT_ROOT / str(item["id"])).exists())


    @patch.object(reports.rda, "record_context")
    def test_identical_generation_replay_does_not_invoke_renderer_again(self, record_context):
        record_context.return_value = self.record
        item = self.create()
        for status, actor, key in (("assembly_reviewed", "reviewer", "replay-assembly"), ("privacy_reviewed", "privacy", "replay-privacy"), ("redaction_reviewed", "redactor", "replay-redaction"), ("approved_for_generation", "approver", "replay-approval")):
            item = reports.transition_report(self.conn, report_id=item["id"], resulting_status=status, rationale="Review", actor=actor, actor_role="administrator", declaration={"acknowledged": True}, idempotency_key=key)
        def fake_render(specification, digest, output_dir):
            output_dir.mkdir(parents=True, exist_ok=True)
            artifacts = []
            for format_name in ("docx", "html"):
                path = output_dir / f"report.{format_name}"
                path.write_text("validated", encoding="utf-8")
                artifacts.append({"format": format_name, "path": str(path), "sha256": __import__("hashlib").sha256(path.read_bytes()).hexdigest(), "size_bytes": path.stat().st_size, "renderer_version": "2.0.0"})
            return {"artifacts": artifacts, "diagnostics": []}
        with patch("api.report_rendering.render_frozen_report", side_effect=fake_render) as renderer:
            first = reports.generate_report(self.conn, report_id=item["id"], actor="generator", actor_role="administrator", idempotency_key="replay-generation")
            second = reports.generate_report(self.conn, report_id=item["id"], actor="generator", actor_role="administrator", idempotency_key="replay-generation")
        self.assertEqual(renderer.call_count, 1)
        self.assertEqual(first["id"], second["id"])


class Stage75BoundaryTests(unittest.TestCase):
    def test_authenticated_admin_form_is_deliberate_and_has_no_raw_json_editors(self):
        from tests.test_admin_session import install_fastapi_stubs
        install_fastapi_stubs()
        from api.routes.admin_session import _stage75_html
        html = _stage75_html(session={"username": "reviewer", "_current_path": "/admin/governed-reports"}, reports=[], candidates={"records": [], "documents": [], "associations": []})
        self.assertIn("Choose a Canonical Record", html)
        self.assertIn("Choose Published Documents", html)
        self.assertIn("Choose record–document associations", html)
        self.assertIn("THE RECORD MUST PRESERVE THE ORIGINAL LANGUAGE", html)
        self.assertIn('value="pdf">PDF (requires DOCX and HTML validation)</option>', html)
        self.assertIn("A PDF PRESENTS THE APPROVED REPORT SPECIFICATION", html)
        self.assertNotIn("bindings_json", html)
        self.assertNotIn("references_json", html)
        self.assertEqual(html.count('aria-current="page"'), 1)

    def test_constants_exclude_pdf_and_use_documented_engine(self):
        self.assertEqual(reports.PUBLICATION_ENGINE_VERSION, "2.0.0")
        self.assertEqual(reports.OUTPUT_FORMATS, {"docx", "html", "pdf"})
        self.assertIn("pdf", reports.OUTPUT_FORMATS)
        self.assertEqual(reports.REPORT_TYPES, {"canonical_record_report"})

    def test_adapter_has_no_persistence_or_database_dependency(self):
        source = Path(__file__).parents[1].joinpath("scripts/evidence_led_governance_pipeline/report_adapter.py").read_text(encoding="utf-8")
        self.assertNotIn("record_governed_reports", source)
        self.assertNotIn("sqlite", source)

    def test_import_does_not_invoke_renderer(self):
        import api.report_rendering as rendering
        with patch.object(subprocess, "run") as run:
            importlib.reload(rendering)
        run.assert_not_called()

    def test_public_app_has_no_stage75_public_route(self):
        source = Path(__file__).parents[1].joinpath("api/routes/admin_session.py").read_text(encoding="utf-8")
        paths = re.findall(r'@router\.(?:get|post)\("([^"]*governed-reports[^"]*)"', source)
        self.assertTrue(paths)
        self.assertTrue(all(path.startswith("/admin/") or path.startswith("/api/admin/") for path in paths))

    def test_private_download_joins_report_version_artifact_and_uses_no_store(self):
        source = Path(__file__).parents[1].joinpath("api/routes/admin_session.py").read_text(encoding="utf-8")
        self.assertIn("JOIN record_governed_report_versions", source)
        self.assertIn("v.report_id=?", source)
        self.assertIn('"Cache-Control": "private, no-store"', source)
        self.assertIn("hashlib.sha256(path.read_bytes())", source)

    def test_private_artifact_route_rejects_unauthenticated_and_malformed_identifiers(self):
        from tests.test_admin_session import FakeHTTPException, FakeRequest, install_fastapi_stubs
        install_fastapi_stubs()
        from api.routes import admin_session
        with patch.object(admin_session, "require_admin_session", side_effect=FakeHTTPException(401, "admin_session_unauthorized")):
            with self.assertRaises(FakeHTTPException) as unauthenticated:
                admin_session.admin_governed_report_artifact("1", "1", FakeRequest())
        self.assertEqual(unauthenticated.exception.status_code, 401)
        with patch.object(admin_session, "require_admin_session", return_value={"username": "admin", "role": "admin"}):
            with self.assertRaises(FakeHTTPException) as malformed:
                admin_session.admin_governed_report_artifact("../1", "1/2", FakeRequest())
        self.assertEqual(malformed.exception.status_code, 404)

    def test_private_artifact_route_rejects_wrong_owner_ungenerated_invalid_withdrawn_and_missing_bytes(self):
        from tests.test_admin_session import FakeHTTPException, FakeRequest, install_fastapi_stubs
        install_fastapi_stubs()
        from api.routes import admin_session
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "reports.db"
            artifact_path = Path(directory) / "report.docx"
            artifact_path.write_bytes(b"private artifact")
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            with patch.object(reports.rda, "record_context", return_value={"reference": "CR-1", "title": "Record", "finding": "Original", "status": "recorded", "version": 1}):
                first = reports.create_report(conn, title="First", purpose="Review", audience="Admin", distribution_class="internal_working", canonical_record_reference="CR-1", document_ids=[], association_ids=[], sections=[{"title": "Record", "blocks": [{"content_type": "verbatim_source", "text": "Original", "source_identity": {"object_kind": "canonical_record", "object_id": "CR-1"}, "inclusion_rationale": "Selected."}]}], exclusions=[], requested_formats=["docx"], rendering_profile="internal", template_version="v1", actor="creator", actor_role="admin", idempotency_key="artifact-first")
                second = reports.create_report(conn, title="Second", purpose="Review", audience="Admin", distribution_class="internal_working", canonical_record_reference="CR-1", document_ids=[], association_ids=[], sections=[{"title": "Record", "blocks": [{"content_type": "verbatim_source", "text": "Original", "source_identity": {"object_kind": "canonical_record", "object_id": "CR-1"}, "inclusion_rationale": "Selected."}]}], exclusions=[], requested_formats=["docx"], rendering_profile="internal", template_version="v1", actor="creator", actor_role="admin", idempotency_key="artifact-second")
            version_id = first["versions"][0]["id"]
            conn.execute("INSERT INTO record_governed_report_artifacts (version_id,format,storage_reference,sha256,size_bytes,renderer_version,template_version,generated_at,validation_state,diagnostics_json,lifecycle_status) VALUES (?,?,?,?,?,?,?,?,?,?,?)", (version_id, "docx", str(artifact_path), __import__("hashlib").sha256(artifact_path.read_bytes()).hexdigest(), artifact_path.stat().st_size, "2.0.0", "v1", "now", "valid", "[]", "current"))
            artifact_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.commit(); conn.close()

            def open_db():
                connection = sqlite3.connect(db_path)
                connection.row_factory = sqlite3.Row
                return connection

            def assert_not_served(report_id, current_artifact_id=artifact_id):
                with patch.object(admin_session, "require_admin_session", return_value={"username": "admin", "role": "admin"}), patch.object(admin_session, "get_db", side_effect=open_db), patch.object(admin_session.rg75, "REPORT_ROOT", Path(directory)):
                    with self.assertRaises(FakeHTTPException) as error:
                        admin_session.admin_governed_report_artifact(str(report_id), str(current_artifact_id), FakeRequest())
                self.assertEqual(error.exception.status_code, 404)

            assert_not_served(first["id"])  # ungenerated report/version
            assert_not_served(second["id"])  # wrong report owner
            connection = sqlite3.connect(db_path)
            connection.execute("UPDATE record_governed_reports SET lifecycle_status='generated' WHERE id=?", (first["id"],))
            connection.execute("UPDATE record_governed_report_versions SET lifecycle_status='generated' WHERE id=?", (version_id,))
            connection.execute("UPDATE record_governed_report_artifacts SET validation_state='failed' WHERE id=?", (artifact_id,))
            connection.commit(); connection.close()
            assert_not_served(first["id"])  # invalid validation state
            connection = sqlite3.connect(db_path); connection.execute("UPDATE record_governed_report_artifacts SET validation_state='valid',storage_reference=? WHERE id=?", (str(Path(directory) / "missing.docx"), artifact_id)); connection.commit(); connection.close()
            assert_not_served(first["id"])  # missing bytes
            connection = sqlite3.connect(db_path); connection.execute("UPDATE record_governed_report_artifacts SET storage_reference=?,sha256=? WHERE id=?", (str(artifact_path), "0" * 64, artifact_id)); connection.commit(); connection.close()
            assert_not_served(first["id"])  # digest mismatch
            for status in ("withdrawn", "superseded"):
                connection = sqlite3.connect(db_path); connection.execute("UPDATE record_governed_report_artifacts SET sha256=? WHERE id=?", (__import__("hashlib").sha256(artifact_path.read_bytes()).hexdigest(), artifact_id)); connection.execute("UPDATE record_governed_reports SET lifecycle_status=? WHERE id=?", (status, first["id"])); connection.commit(); connection.close()
                assert_not_served(first["id"])  # withdrawn/superseded owner

    def test_read_only_listing_does_not_invoke_generation_or_rendering(self):
        from tests.test_admin_session import FakeHTTPException, FakeRequest, install_fastapi_stubs
        install_fastapi_stubs()
        from api.routes import admin_session
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        with patch.object(admin_session, "require_admin_session", return_value={"username": "admin", "role": "admin"}), patch.object(admin_session, "get_db", return_value=conn), patch.object(admin_session.rg75, "generate_report") as generate, patch("api.report_rendering.render_frozen_report") as render:
            response = admin_session.admin_governed_reports(FakeRequest())
            diagnostics = admin_session.admin_governed_reports_diagnostics(FakeRequest())
            with self.assertRaises(FakeHTTPException):
                admin_session.admin_governed_report_detail("malformed", FakeRequest())
            with self.assertRaises(FakeHTTPException):
                admin_session.admin_governed_report_artifact("malformed", "malformed", FakeRequest())
        conn.close()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(diagnostics.status_code, 200)
        generate.assert_not_called()
        render.assert_not_called()

    def test_frozen_specification_renders_docx_and_html_through_v2_adapter(self):
        specification = {"specification_schema_version": reports.SPECIFICATION_SCHEMA_VERSION, "report_type": "canonical_record_report", "title": "Internal report", "purpose": "Review", "intended_audience": "Administrators", "distribution_class": "internal_working", "primary_record": {"reference": "CR-1", "title": "Record", "description": "Original wording", "status": "recorded"}, "selected_documents": [], "selected_associations": [], "sections": [{"order": 0, "title": "Record", "blocks": [{"order": 0, "content_type": "verbatim_source", "text": "Original wording", "source_identity": {"object_kind": "canonical_record", "object_id": "CR-1"}, "attribution": "", "inclusion_rationale": "Deliberately selected."}]}], "exclusions": [], "qualifications": [reports.BOUNDARY], "requested_formats": ["docx", "html"], "publication_engine_version": "2.0.0", "rendering_profile": "internal", "template_version": "cde-internal-v1"}
        with tempfile.TemporaryDirectory() as directory:
            result = render_frozen_report(specification, reports.specification_digest(specification), Path(directory))
            self.assertEqual({item["format"] for item in result["artifacts"]}, {"docx", "html"})
            self.assertTrue(all(Path(item["path"]).is_file() for item in result["artifacts"]))

    def test_renderer_escapes_untrusted_text_and_preserves_required_disclosures(self):
        block_types = ["verbatim_source", "faithful_paraphrase", "administrative_summary", "qualification", "limitation", "redaction_notice"]
        blocks = [{"order": index, "content_type": content_type, "text": f"<b>{content_type}</b>", "source_identity": {"object_kind": "canonical_record", "object_id": "CR-1"}, "attribution": "source", "inclusion_rationale": "Deliberately selected."} for index, content_type in enumerate(block_types)]
        specification = {"specification_schema_version": reports.SPECIFICATION_SCHEMA_VERSION, "report_type": "canonical_record_report", "title": "<script>bad</script>", "purpose": "Review", "intended_audience": "Administrators", "distribution_class": "internal_working", "primary_record": {"reference": "CR-1", "title": "Record", "description": "<img src=x onerror=alert(1)>", "status": "recorded"}, "selected_documents": [], "selected_associations": [], "sections": [{"order": 0, "title": "Record", "blocks": blocks}], "exclusions": [{"object_kind": "private_source", "object_id": "secret", "rationale": "Private source excluded."}], "qualifications": [reports.BOUNDARY], "requested_formats": ["docx", "html"], "publication_engine_version": "2.0.0", "rendering_profile": "internal", "template_version": "cde-internal-v1"}
        with tempfile.TemporaryDirectory() as directory:
            result = render_frozen_report(specification, reports.specification_digest(specification), Path(directory))
            html = Path(next(item["path"] for item in result["artifacts"] if item["format"] == "html")).read_text(encoding="utf-8")
            self.assertNotIn("<script>bad</script>", html)
            self.assertIn("Administrative summary:", html)
            self.assertIn("Qualification:", html)
            self.assertIn("Exclusion:", html)
            labels = ["Original wording", "Faithful paraphrase", "Administrative summary", "Qualification", "Limitation", "Redaction notice"]
            positions = [html.index(f"{label}:") for label in labels]
            self.assertEqual(positions, sorted(positions))

    def test_cross_format_validation_rejects_omitted_html_text(self):
        specification = {"specification_schema_version": reports.SPECIFICATION_SCHEMA_VERSION, "report_type": "canonical_record_report", "title": "Internal report", "purpose": "Review", "intended_audience": "Administrators", "distribution_class": "internal_working", "primary_record": {"reference": "CR-1", "title": "Record", "description": "Original wording", "status": "recorded"}, "selected_documents": [], "selected_associations": [], "sections": [{"order": 0, "title": "Record", "blocks": [{"order": 0, "content_type": "verbatim_source", "text": "Original wording", "source_identity": {"object_kind": "canonical_record", "object_id": "CR-1"}, "attribution": "", "inclusion_rationale": "Selected."}]}], "exclusions": [], "qualifications": [reports.BOUNDARY], "requested_formats": ["docx", "html"], "publication_engine_version": "2.0.0", "rendering_profile": "internal", "template_version": "cde-internal-v1"}
        with tempfile.TemporaryDirectory() as directory:
            result = render_frozen_report(specification, reports.specification_digest(specification), Path(directory))
            html_path = Path(next(item["path"] for item in result["artifacts"] if item["format"] == "html"))
            html_path.write_text(html_path.read_text(encoding="utf-8").replace("Original wording", "Omitted wording"), encoding="utf-8")
            engine_root = Path(__file__).parents[1] / "scripts" / "evidence_led_governance_pipeline"
            sys.path.insert(0, str(engine_root))
            try:
                from output_validation import validate_cross_format_equivalence
                from report_adapter import make_book
                validation, audit = validate_cross_format_equivalence(make_book(specification), docx_path=Path(next(item["path"] for item in result["artifacts"] if item["format"] == "docx")), html_path=html_path)
            finally:
                sys.path.pop(0)
            self.assertFalse(validation.ok)
            self.assertTrue(audit.missing_html)

    def test_stage75_equivalence_rejects_reorder_label_and_qualification_divergence(self):
        specification = {"specification_schema_version": reports.SPECIFICATION_SCHEMA_VERSION, "report_type": "canonical_record_report", "title": "Internal report", "purpose": "Review", "intended_audience": "Administrators", "distribution_class": "internal_working", "primary_record": {"reference": "CR-1", "title": "Record", "description": "Original wording", "status": "recorded"}, "selected_documents": [], "selected_associations": [], "sections": [{"order": 0, "title": "First section", "blocks": [{"order": 0, "content_type": "verbatim_source", "text": "First wording", "source_identity": {"object_kind": "canonical_record", "object_id": "CR-1"}, "attribution": "Named source", "inclusion_rationale": "First rationale."}]}, {"order": 1, "title": "Second section", "blocks": [{"order": 0, "content_type": "administrative_summary", "text": "Second wording", "source_identity": {"object_kind": "canonical_record", "object_id": "CR-1"}, "attribution": "Named source", "inclusion_rationale": "Second rationale."}]}], "exclusions": [], "qualifications": [reports.BOUNDARY], "requested_formats": ["docx", "html"], "publication_engine_version": "2.0.0", "rendering_profile": "internal", "template_version": "cde-internal-v1"}
        engine_root = Path(__file__).parents[1] / "scripts" / "evidence_led_governance_pipeline"
        sys.path.insert(0, str(engine_root))
        try:
            from report_adapter import make_book, ordered_content_is_preserved
        finally:
            sys.path.pop(0)
        with tempfile.TemporaryDirectory() as directory:
            result = render_frozen_report(specification, reports.specification_digest(specification), Path(directory))
            docx_path = Path(next(item["path"] for item in result["artifacts"] if item["format"] == "docx"))
            html_path = Path(next(item["path"] for item in result["artifacts"] if item["format"] == "html"))
            original_html = html_path.read_text(encoding="utf-8")
            mutations = {
                "reordered_sections": original_html.replace("First wording", "TEMP").replace("Second wording", "First wording").replace("TEMP", "Second wording"),
                "missing_original_label": original_html.replace("Original wording: First wording", "First wording"),
                "summary_as_original": original_html.replace("Administrative summary:", "Original wording:"),
                "missing_qualification": original_html.replace(reports.BOUNDARY, ""),
            }
            for label, mutated in mutations.items():
                with self.subTest(label=label):
                    html_path.write_text(mutated, encoding="utf-8")
                    self.assertFalse(ordered_content_is_preserved(make_book(specification), docx_path=docx_path, html_path=html_path))
                    html_path.write_text(original_html, encoding="utf-8")

    def test_private_metadata_canaries_are_absent_from_rendered_artifacts(self):
        specification = {"specification_schema_version": reports.SPECIFICATION_SCHEMA_VERSION, "report_type": "canonical_record_report", "title": "Internal report", "purpose": "Review", "intended_audience": "Administrators", "distribution_class": "internal_working", "primary_record": {"reference": "CR-1", "title": "Record", "description": "Approved wording", "status": "recorded"}, "selected_documents": [], "selected_associations": [], "sections": [{"order": 0, "title": "Record", "blocks": [{"order": 0, "content_type": "verbatim_source", "text": "Approved wording", "source_identity": {"object_kind": "canonical_record", "object_id": "CR-1"}, "attribution": "", "inclusion_rationale": "Selected."}]}], "exclusions": [], "qualifications": [reports.BOUNDARY], "requested_formats": ["docx", "html"], "publication_engine_version": "2.0.0", "rendering_profile": "internal", "template_version": "cde-internal-v1"}
        private_canaries = ["/private/database.sqlite", "/tmp/cde-stage75-secret", "idempotency-secret", "reviewer-secret", "private source text"]
        with tempfile.TemporaryDirectory() as directory:
            result = render_frozen_report(specification, reports.specification_digest(specification), Path(directory))
            html = Path(next(item["path"] for item in result["artifacts"] if item["format"] == "html")).read_text(encoding="utf-8")
            docx_path = Path(next(item["path"] for item in result["artifacts"] if item["format"] == "docx"))
            with zipfile.ZipFile(docx_path) as package:
                docx_payload = b"".join(package.read(name) for name in package.namelist())
            for canary in private_canaries:
                self.assertNotIn(canary, html)
                self.assertNotIn(canary.encode(), docx_payload)

    def test_renderer_rejects_symlink_or_outside_artifact_path(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.NamedTemporaryFile() as outside:
            payload = {"specification_digest": "d" * 64, "diagnostics": [], "artifacts": [{"format": "html", "path": outside.name, "sha256": "d" * 64, "size_bytes": 1, "renderer_version": "2.0.0"}]}
            completed = subprocess.CompletedProcess([], 0, stdout=json.dumps(payload), stderr="")
            specification = {"publication_engine_version": "2.0.0"}
            digest = reports.specification_digest(specification)
            payload["specification_digest"] = digest
            completed.stdout = json.dumps(payload)
            fake_process = subprocess.CompletedProcess([], 0, stdout=completed.stdout, stderr="")
            process = Mock()
            process.returncode = fake_process.returncode
            process.communicate.return_value = (fake_process.stdout, fake_process.stderr)
            with patch("api.report_rendering.subprocess.Popen", return_value=process) as popen:
                with self.assertRaisesRegex(ValueError, "path_invalid"):
                    render_frozen_report(specification, digest, Path(directory) / "private")
            self.assertTrue(popen.call_args.kwargs["start_new_session"])

    def test_renderer_timeout_terminates_isolated_process_group(self):
        specification = {"publication_engine_version": "2.0.0"}
        digest = reports.specification_digest(specification)
        process = Mock()
        process.communicate.side_effect = subprocess.TimeoutExpired("adapter", 210)
        with tempfile.TemporaryDirectory() as directory, patch("api.report_rendering.subprocess.Popen", return_value=process), patch("api.report_rendering._terminate_process_group") as terminate:
            with self.assertRaisesRegex(ValueError, "renderer_timeout"):
                render_frozen_report(specification, digest, Path(directory) / "private")
        terminate.assert_called_once_with(process)


    def test_server_submission_contract_works_without_json_editor_or_javascript(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        with patch.object(reports.rda, "record_context", return_value={"reference": "CR-1", "title": "Record", "finding": "Original", "status": "recorded", "version": 1}):
            item = reports.create_report(
                conn,
                title="No-script report",
                purpose="Review",
                audience="Administrators",
                distribution_class="internal_working",
                canonical_record_reference="CR-1",
                document_ids=[],
                association_ids=[],
                sections=[{"title": "Record", "blocks": [{"content_type": "verbatim_source", "text": "Original", "source_identity": {"object_kind": "canonical_record", "object_id": "CR-1"}, "inclusion_rationale": "Selected."}]}],
                exclusions=[],
                requested_formats=["docx", "html"],
                rendering_profile="internal",
                template_version="cde-internal-v1",
                actor="creator",
                actor_role="administrator",
                idempotency_key="no-script-create",
            )
        conn.close()
        self.assertEqual(item["versions"][0]["specification"]["selected_documents"], [])
        self.assertEqual(item["versions"][0]["specification"]["selected_associations"], [])

    def test_artifact_paths_are_server_generated_and_confined(self):
        source = Path(__file__).parents[1].joinpath("api/report_rendering.py").read_text(encoding="utf-8")
        persistence = Path(__file__).parents[1].joinpath("api/record_governed_reports.py").read_text(encoding="utf-8")
        self.assertIn("tempfile.TemporaryDirectory", source)
        self.assertIn("output_dir / source.name", source)
        self.assertIn("REPORT_ROOT / str(report_id) / str(version[\"version_number\"])", persistence)
        self.assertIn("governed-report-{numeric_report}.{row[1]}", Path(__file__).parents[1].joinpath("api/routes/admin_session.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
