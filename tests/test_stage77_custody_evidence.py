"""Neutral isolated regressions for the Stage 77 custody-evidence registry."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from api import governed_custody_evidence as evidence
from api import governed_report_jobs as jobs
from api import governed_report_qualifications as qualifications


class Stage77CustodyEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "store"; self.root.mkdir(mode=0o700)
        self.conn = sqlite3.connect(Path(self.temp.name) / "records.db"); self.conn.row_factory = sqlite3.Row
        evidence.ensure_custody_evidence_tables(self.conn)
        self.runtime = {"project_id": "11111111-1111-1111-1111-111111111111", "service_id": "22222222-2222-2222-2222-222222222222", "environment_id": "33333333-3333-3333-3333-333333333333", "deployment_id": "44444444-4444-4444-4444-444444444444", "git_commit_sha": "a" * 40}
        self.capture_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        self.report = {"id": 7, "lifecycle_status": "validation_failed", "versions": [{"id": 11, "specification_digest": "b" * 64, "specification": {"requested_formats": ["html"]}}]}
        self.job1, self.job2, self.topology = {"id": 41, "state": "failed_terminal"}, {"id": 42, "state": "failed_terminal", "retry_of_job_id": 41}, "c" * 64
        self.qualification = {"id": 71, "digest": "d" * 64}
        self._install_mandate()

    def tearDown(self):
        self.conn.close(); self.temp.cleanup()

    def _mandate(self):
        return {"report_id": 7, "report_version_id": 11, "purpose": evidence.PURPOSE, "predecessor_job_ids": [41, 42], "topology_digest": self.topology, "specification_digest": "b" * 64, "qualification_id": 71, "qualification_digest": "d" * 64, "declaration": "declaration", "rationale": "rationale", "runtime": self.runtime}

    def _install_mandate(self):
        self.conn.execute("CREATE TABLE stage77_custody_v2_mandates (id TEXT PRIMARY KEY, report_id INTEGER, report_version_id INTEGER, predecessor_job_1_id INTEGER, predecessor_job_2_id INTEGER, mandate_json TEXT, mandate_digest TEXT, idempotency_key TEXT, state TEXT, declaration TEXT, rationale TEXT)")
        self.conn.execute("INSERT INTO stage77_custody_v2_mandates VALUES(?,?,?,?,?,?,?,?,?,?,?)", ("mandate-1", 7, 11, 41, 42, evidence.canonical(self._mandate()).decode(), "e" * 64, "mandate-key", "created", "declaration", "rationale"))
        self.conn.commit()

    def _facts(self):
        return {
            "database_capture": {"database_id": "db", "capture_digest": "1" * 64, "capture_completed_at": self.capture_at},
            "database_digest": {"database_id": "db", "capture_digest": "1" * 64},
            "checkpoint_wal_shm": {"database_id": "db", "checkpoint": "complete", "wal": "absent", "shm": "absent"},
            "custody_points_1_5": {"points_1_5_id": "points", "points_1_5_digest": "2" * 64},
            "archive_export": {"archive_id": "archive", "archive_digest": "3" * 64, "export_id": "export", "export_digest": "4" * 64},
            "receipt": {"receipt_id": "receipt", "receipt_digest": "5" * 64, "archive_digest": "3" * 64, "export_digest": "4" * 64},
            "recovery_verification": {"recovery_verification_id": "recovery", "recovery_verification_digest": "6" * 64, "database_id": "db", "capture_digest": "1" * 64},
            "runtime_authority": dict(self.runtime),
            "artifact_inventory": {"artifact_inventory_id": "inventory", "artifact_inventory_digest": "7" * 64},
        }

    def _manifest(self, identifier, facts=None):
        facts = self._facts() if facts is None else facts
        return {"id": identifier, "mandate_id": "mandate-1", "mandate_digest": "e" * 64, "mandate_idempotency_key": "mandate-key", "report_id": 7, "report_version_id": 11, "job1_id": 41, "job2_id": 42, "runtime": self.runtime, "capture_completed_at": self.capture_at, "idempotency_key": "registry-" + identifier, "specification_digest": "b" * 64, "qualification_id": 71, "qualification_digest": "d" * 64, "declaration": "declaration", "rationale": "rationale", "objects": [{"role": role, "filename": role + ".json", "media_type": "application/json"} for role in evidence.ROLES], "facts": facts}

    def _package(self, identifier="evidence-1", facts=None):
        package = self.root / identifier; package.mkdir(mode=0o700)
        manifest = self._manifest(identifier, facts)
        for role, value in manifest["facts"].items(): (package / (role + ".json")).write_bytes(evidence.canonical(value))
        (package / "manifest.json").write_bytes(evidence.canonical(manifest))
        return package

    def _register(self, identifier="evidence-1", *, runtime=None, report=None, topology=None, qualification=None):
        runtime_patch = {"side_effect": runtime} if isinstance(runtime, Exception) else {"return_value": self.runtime if runtime is None else runtime}
        with patch.dict(os.environ, {"CDE_STAGE77_CUSTODY_EVIDENCE_V1_STORE_ROOT": str(self.root)}, clear=False), patch.object(jobs, "custody_v2_runtime_authority", **runtime_patch), patch.object(jobs.reports, "get_report", return_value=self.report if report is None else report), patch.object(jobs.reports, "specification_digest", return_value="b" * 64), patch.object(jobs, "_post_correction_topology", return_value=(self.job1, self.job2, self.topology) if topology is None else topology), patch.object(qualifications, "latest_final", return_value=self.qualification if qualification is None else qualification):
            return evidence.register_from_store(self.conn, evidence_set_id=identifier, mandate_id="mandate-1", report_id=7, report_version_id=11, actor="controller", occurred_at=self.capture_at)

    def _rewrite_manifest(self, package, mutate):
        manifest = evidence.strict_json((package / "manifest.json").read_text()); mutate(manifest)
        (package / "manifest.json").write_bytes(evidence.canonical(manifest))

    def _recovery_tool(self):
        path = Path(__file__).parents[1] / "scripts" / "manage_stage77_recovery.py"
        spec = importlib.util.spec_from_file_location("stage77_recovery_tool_test", path)
        module = importlib.util.module_from_spec(spec); assert spec.loader is not None
        spec.loader.exec_module(module)
        return module

    def _capture_source(self, source_root, identifier):
        package = source_root / identifier; package.mkdir(mode=0o700)
        manifest = self._manifest(identifier)
        authority = {key: value for key, value in manifest.items() if key not in {"objects", "facts"}}
        (package / "registry-authority.json").write_bytes(evidence.canonical(authority))
        for role, value in manifest["facts"].items():
            (package / (role + ".json")).write_bytes(evidence.canonical(value))
        return package

    def test_canonical_contract_is_closed_and_stable(self):
        self.assertEqual(evidence.canonical({"b": 1, "a": True}), b'{"a":true,"b":1}')
        self.assertEqual(evidence.digest({"a": 1, "payload_digest": "x"}), evidence.digest({"a": 1}))
        for value in ({"x": None}, {"x": 1.5}, {"x": object()}):
            with self.assertRaises(ValueError): evidence.canonical(value)
        with self.assertRaisesRegex(ValueError, "duplicate_key"): evidence.strict_json('{"a":1,"a":2}')

    def test_closed_role_inventory_rejects_missing_duplicate_unknown_and_extra(self):
        self.assertEqual(len(evidence.ROLES), 9)
        for name, mutate in (
            ("missing", lambda m: m.update(objects=m["objects"][:-1])),
            ("duplicate", lambda m: m["objects"].__setitem__(1, dict(m["objects"][0]))),
            ("unknown", lambda m: m["objects"].__setitem__(0, {"role": "unknown", "filename": "unknown.json", "media_type": "application/json"})),
            ("extra", lambda m: m["objects"].append({"role": "unknown", "filename": "unknown.json", "media_type": "application/json"})),
        ):
            with self.subTest(case=name):
                package = self._package("evidence-" + name); self._rewrite_manifest(package, mutate)
                with self.assertRaisesRegex(ValueError, "roles_invalid"): self._register("evidence-" + name)

    def test_registers_complete_fixed_layout_and_bounded_receipt_projection(self):
        self._package(); row = self._register()
        self.assertEqual((row["id"], row["state"], row["mandate_id"]), ("evidence-1", "registered", "mandate-1"))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM stage77_custody_evidence_objects").fetchone()[0], len(evidence.ROLES))
        receipt = {key: row[key] for key in ("id", "payload_digest", "state", "mandate_id", "report_id", "report_version_id", "created_at")}
        text = json.dumps(receipt); self.assertNotIn(str(self.root), text); self.assertNotIn("payload_json", text)

    def test_identifier_traversal_and_symlinked_components_fail_closed(self):
        self._package()
        with self.assertRaisesRegex(ValueError, "input_invalid"): self._register("../evidence-1")
        (self.root / "evidence-1" / "manifest.json").unlink(); (self.root / "evidence-1" / "manifest.json").symlink_to(self.root / "evidence-1" / "receipt.json")
        with self.assertRaisesRegex(ValueError, "manifest_missing"): self._register()

    def test_symlinked_root_package_and_object_fail_closed(self):
        self._package("evidence-object")
        package = self.root / "evidence-object"
        (package / "archive_export.json").unlink(); (package / "archive_export.json").symlink_to(package / "receipt.json")
        with self.assertRaisesRegex(ValueError, "object_missing"): self._register("evidence-object")
        linked_root = Path(self.temp.name) / "linked-root"; linked_root.symlink_to(self.root, target_is_directory=True)
        with patch.dict(os.environ, {"CDE_STAGE77_CUSTODY_EVIDENCE_V1_STORE_ROOT": str(linked_root)}, clear=False):
            with self.assertRaisesRegex(ValueError, "store_unavailable"):
                evidence.register_from_store(self.conn, evidence_set_id="evidence-object", mandate_id="mandate-1", report_id=7, report_version_id=11, actor="controller", occurred_at=self.capture_at)

    def test_nonregular_missing_and_altered_retained_objects_fail_closed(self):
        package = self._package(); (package / "receipt.json").unlink(); (package / "receipt.json").mkdir()
        with self.assertRaisesRegex(ValueError, "object_missing"): self._register()
        package = self._package("evidence-altered"); (package / "archive_export.json").write_bytes(evidence.canonical({"archive_id": "other"}))
        with self.assertRaisesRegex(ValueError, "retained_fact_mismatch"): self._register("evidence-altered")

    def test_unknown_manifest_false_digest_and_size_or_byte_drift_fail_closed(self):
        package = self._package(); self._rewrite_manifest(package, lambda m: m.update(unknown="x"))
        with self.assertRaisesRegex(ValueError, "manifest_invalid"): self._register()
        package = self._package("evidence-digest"); self._rewrite_manifest(package, lambda m: m.update(mandate_digest="f" * 64))
        with self.assertRaisesRegex(ValueError, "mandate_mismatch"): self._register("evidence-digest")
        package = self._package("evidence-byte"); (package / "database_capture.json").write_bytes(b'{}')
        with self.assertRaisesRegex(ValueError, "retained_fact_mismatch"): self._register("evidence-byte")

    def test_store_preparation_rehashes_sizes_and_is_byte_identically_idempotent(self):
        source = Path(self.temp.name) / "capture"; source.mkdir(mode=0o700); self._capture_source(source, "prepared-1")
        tool = self._recovery_tool()
        with patch.dict(os.environ, {"CDE_STAGE77_CUSTODY_CAPTURE_SOURCE_ROOT": str(source), "CDE_STAGE77_CUSTODY_EVIDENCE_V1_STORE_ROOT": str(self.root)}, clear=False):
            first = tool.prepare_evidence_store("prepared-1"); second = tool.prepare_evidence_store("prepared-1")
        self.assertEqual((first["status"], second["status"], first["manifest_digest"]), ("prepared", "already_prepared", second["manifest_digest"]))
        object_data = (self.root / "prepared-1" / "database_capture.json").read_bytes()
        self.assertEqual(hashlib.sha256(object_data).hexdigest(), hashlib.sha256(evidence.canonical(self._facts()["database_capture"])).hexdigest())
        self.assertEqual(len(object_data), len(evidence.canonical(self._facts()["database_capture"])))

    def test_store_preparation_rejects_conflicting_existing_destination(self):
        source = Path(self.temp.name) / "capture"; source.mkdir(mode=0o700); package = self._capture_source(source, "prepared-conflict")
        tool = self._recovery_tool()
        with patch.dict(os.environ, {"CDE_STAGE77_CUSTODY_CAPTURE_SOURCE_ROOT": str(source), "CDE_STAGE77_CUSTODY_EVIDENCE_V1_STORE_ROOT": str(self.root)}, clear=False):
            tool.prepare_evidence_store("prepared-conflict")
            (package / "archive_export.json").write_bytes(evidence.canonical({"archive_id": "changed"}))
            with self.assertRaises(ValueError): tool.prepare_evidence_store("prepared-conflict")

    def test_authority_selection_cannot_supply_roles_paths_digests_or_runtime(self):
        self._package()
        with self.assertRaises(TypeError):
            evidence.register_from_store(self.conn, evidence_set_id="evidence-1", mandate_id="mandate-1", report_id=7, report_version_id=11, actor="controller", occurred_at=self.capture_at, runtime=self.runtime)
        with self.assertRaises(TypeError):
            evidence.register_from_store(self.conn, evidence_set_id="evidence-1", mandate_id="mandate-1", report_id=7, report_version_id=11, actor="controller", occurred_at=self.capture_at, objects=[])

    def test_mandate_report_version_topology_qualification_spec_and_declaration_mismatches_fail(self):
        cases = (
            ("mandate", None, None, None, "UPDATE stage77_custody_v2_mandates SET state='invalidated'"),
            ("report", {**self.report, "lifecycle_status": "generated"}, None, None, None),
            ("topology", None, ({"id": 99}, self.job2, self.topology), None, None),
            ("qualification", None, None, {"id": 99, "digest": "0" * 64}, None),
        )
        for name, report, topology, qualification, sql in cases:
            with self.subTest(case=name):
                self._package("evidence-" + name)
                if sql: self.conn.execute(sql); self.conn.commit()
                with self.assertRaises(ValueError): self._register("evidence-" + name, report=report, topology=topology, qualification=qualification)
                self.conn.execute("UPDATE stage77_custody_v2_mandates SET state='created'"); self.conn.commit()
        for key in ("declaration", "rationale", "mandate_idempotency_key", "specification_digest"):
            package = self._package("evidence-" + key); self._rewrite_manifest(package, lambda m, key=key: m.update({key: "0" * 64 if key == "specification_digest" else "other"}))
            with self.assertRaises(ValueError): self._register("evidence-" + key)

    def test_database_checkpoint_points_archive_receipt_recovery_inventory_and_runtime_drift_fail(self):
        cases = (("database_digest", "database_id", "other"), ("checkpoint_wal_shm", "database_id", "other"), ("custody_points_1_5", "points_1_5_digest", "not-a-digest"), ("receipt", "archive_digest", "0" * 64), ("recovery_verification", "capture_digest", "0" * 64), ("artifact_inventory", "artifact_inventory_digest", "not-a-digest"))
        for number, (role, key, value) in enumerate(cases):
            with self.subTest(role=role):
                facts = self._facts(); facts[role][key] = value; self._package(f"evidence-fact-{number}", facts)
                with self.assertRaises(ValueError): self._register(f"evidence-fact-{number}")
        self._package("evidence-runtime")
        with self.assertRaises(ValueError): self._register("evidence-runtime", runtime={**self.runtime, "git_commit_sha": "f" * 40})

    def test_stale_capture_and_missing_runtime_fail_closed(self):
        self.capture_at = "2000-01-01T00:00:00Z"; self._package("evidence-stale")
        with self.assertRaisesRegex(ValueError, "capture_stale"): self._register("evidence-stale")
        self.capture_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"); self._package("evidence-runtime")
        with self.assertRaisesRegex(ValueError, "runtime_authority_invalid"):
            self._register("evidence-runtime", runtime=ValueError("stage77_custody_v2_runtime_authority_invalid"))

    def test_duplicate_registration_and_conflicting_duplicate_are_distinct(self):
        self._package(); first = self._register(); second = self._register(); self.assertEqual(first["id"], second["id"])
        self._rewrite_manifest(self.root / "evidence-1", lambda m: m.update(idempotency_key="different"))
        with self.assertRaises(ValueError): self._register()

    def test_immutable_rows_append_only_events_and_forward_only_states(self):
        self._package(); row = self._register()
        with self.assertRaises(sqlite3.DatabaseError): self.conn.execute("UPDATE stage77_custody_evidence_sets SET mandate_id='other' WHERE id=?", (row["id"],))
        with self.assertRaises(sqlite3.DatabaseError): self.conn.execute("DELETE FROM stage77_custody_evidence_events WHERE evidence_set_id=?", (row["id"],))
        self.conn.execute("UPDATE stage77_custody_evidence_sets SET state='consumed' WHERE id=?", (row["id"],))
        with self.assertRaises(sqlite3.DatabaseError): self.conn.execute("UPDATE stage77_custody_evidence_sets SET state='registered' WHERE id=?", (row["id"],))


if __name__ == "__main__":
    unittest.main()
