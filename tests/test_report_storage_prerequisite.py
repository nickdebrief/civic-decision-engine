import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_report_storage_runtime.py"


def load_validator():
    spec = importlib.util.spec_from_file_location("check_report_storage_runtime", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ReportStoragePrerequisiteTests(unittest.TestCase):
    def setUp(self):
        self.module = load_validator()
        self.temp = tempfile.TemporaryDirectory(prefix="stage77-storage-test-", dir=str(Path(tempfile.gettempdir()).resolve()))
        self.root = Path(self.temp.name) / "durable"
        self.root.mkdir()
        self.database = self.root / "records.db"
        self.artifacts = self.root / "cde-governed-reports"
        self.database.write_bytes(b"synthetic placeholder")
        self.artifacts.mkdir()
        self.env = {
            "RECORDS_DB_PATH": str(self.database),
            "CDE_REPORT_ARTIFACT_ROOT": str(self.artifacts),
        }

    def tearDown(self):
        self.temp.cleanup()

    def validate(self, env=None, root=None, database=None, artifacts=None, mode="durable"):
        return self.module.validate_storage(
            env or self.env,
            mode=mode,
            durable_root=root or self.root,
            expected_database_path=database or self.database,
            expected_artifact_root=artifacts or self.artifacts,
        )

    def test_valid_explicit_durable_configuration_passes_without_writing(self):
        before = sorted(path.relative_to(self.root).as_posix() for path in self.root.rglob("*"))
        self.validate()
        after = sorted(path.relative_to(self.root).as_posix() for path in self.root.rglob("*"))
        self.assertEqual(before, after)

    def test_missing_approved_artifact_leaf_is_accepted_without_creation(self):
        self.artifacts.rmdir()
        self.assertFalse(self.artifacts.exists())
        self.validate()
        self.assertFalse(self.artifacts.exists())

    def test_missing_nested_artifact_structure_is_rejected(self):
        nested = self.root / "missing" / "cde-governed-reports"
        env = dict(self.env)
        env["CDE_REPORT_ARTIFACT_ROOT"] = str(nested)
        with self.assertRaisesRegex(self.module.StorageValidationError, "artifact_root_invalid"):
            self.validate(env, artifacts=nested)

    def test_missing_and_blank_variables_fail_closed(self):
        for key, expected in (("RECORDS_DB_PATH", "database_variable_missing"), ("CDE_REPORT_ARTIFACT_ROOT", "artifact_variable_missing")):
            with self.subTest(key=key):
                env = dict(self.env)
                env.pop(key)
                with self.assertRaisesRegex(self.module.StorageValidationError, expected):
                    self.validate(env)
        for key in self.env:
            env = dict(self.env)
            env[key] = "  "
            with self.subTest(key=key):
                with self.assertRaisesRegex(self.module.StorageValidationError, "blank_path"):
                    self.validate(env)

    def test_relative_tmp_outside_and_traversal_paths_fail(self):
        variants = (
            ("RECORDS_DB_PATH", "records.db", "relative_path"),
            ("CDE_REPORT_ARTIFACT_ROOT", "/tmp/reports", "temporary_path"),
            ("CDE_REPORT_ARTIFACT_ROOT", str(self.root.parent / "outside"), "outside_durable_root"),
            ("CDE_REPORT_ARTIFACT_ROOT", str(self.root / ".." / "other"), "traversal"),
        )
        for key, value, expected in variants:
            with self.subTest(key=key, value=value):
                env = dict(self.env)
                env[key] = value
                with self.assertRaisesRegex(self.module.StorageValidationError, expected):
                    self.validate(env)

    def test_normalization_whitespace_and_casing_variants_fail(self):
        variants = (
            ("RECORDS_DB_PATH", str(self.database) + "/", "outside_durable_root"),
            ("CDE_REPORT_ARTIFACT_ROOT", str(self.artifacts) + "/", "outside_durable_root"),
            ("RECORDS_DB_PATH", str(self.database).replace("/", "//", 1), "outside_durable_root"),
            ("CDE_REPORT_ARTIFACT_ROOT", " " + str(self.artifacts), "relative_path"),
        )
        for key, value, expected in variants:
            with self.subTest(key=key, value=value):
                env = dict(self.env)
                env[key] = value
                with self.assertRaisesRegex(self.module.StorageValidationError, expected):
                    self.validate(env)

    def test_overlap_and_database_inside_artifact_root_fail(self):
        env = dict(self.env)
        env["CDE_REPORT_ARTIFACT_ROOT"] = str(self.database)
        with self.assertRaisesRegex(self.module.StorageValidationError, "overlap"):
            self.validate(env)
        nested = self.artifacts / "records.db"
        nested.write_bytes(b"synthetic")
        env = dict(self.env)
        env["RECORDS_DB_PATH"] = str(nested)
        with self.assertRaisesRegex(self.module.StorageValidationError, "overlap"):
            self.validate(env)

    def test_symlink_root_and_intermediate_component_fail_without_following(self):
        link_root = Path(self.temp.name) / "link-root"
        link_root.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(self.module.StorageValidationError, "symlink_component"):
            self.validate(root=link_root, database=link_root / "records.db", artifacts=link_root / "cde-governed-reports")
        link_parent = self.root / "linked"
        link_parent.symlink_to(self.artifacts, target_is_directory=True)
        env = dict(self.env)
        env["CDE_REPORT_ARTIFACT_ROOT"] = str(link_parent)
        with self.assertRaisesRegex(self.module.StorageValidationError, "symlink_component"):
            self.validate(env, artifacts=link_parent)

        leaf_target = self.root / "leaf-target"
        leaf_target.mkdir()
        leaf_link = self.root / "cde-governed-reports-link"
        leaf_link.symlink_to(leaf_target, target_is_directory=True)
        env = dict(self.env)
        env["CDE_REPORT_ARTIFACT_ROOT"] = str(leaf_link)
        with self.assertRaisesRegex(self.module.StorageValidationError, "symlink_component"):
            self.validate(env, artifacts=leaf_link)

        dangling = self.root / "dangling"
        dangling.symlink_to(self.root / "does-not-exist", target_is_directory=True)
        env = dict(self.env)
        env["CDE_REPORT_ARTIFACT_ROOT"] = str(dangling)
        with self.assertRaisesRegex(self.module.StorageValidationError, "symlink_component"):
            self.validate(env, artifacts=dangling)

        outside_database = Path(self.temp.name) / "outside.db"
        outside_database.write_bytes(b"outside")
        database_link = self.root / "records-link.db"
        database_link.symlink_to(outside_database)
        env = dict(self.env)
        env["RECORDS_DB_PATH"] = str(database_link)
        with self.assertRaisesRegex(self.module.StorageValidationError, "symlink_component"):
            self.validate(env, database=database_link)

    def test_existing_database_and_artifact_types_are_required(self):
        self.database.unlink()
        with self.assertRaisesRegex(self.module.StorageValidationError, "metadata_inspection_failure"):
            self.validate()
        self.database.write_bytes(b"synthetic")
        self.artifacts.rmdir()
        self.artifacts.write_bytes(b"not a directory")
        with self.assertRaisesRegex(self.module.StorageValidationError, "artifact_root_invalid"):
            self.validate()

    def test_metadata_failure_is_bounded(self):
        with patch.object(self.module.Path, "lstat", side_effect=OSError("private path")):
            with self.assertRaisesRegex(self.module.StorageValidationError, "durable_root_missing"):
                self.validate()

    def test_durable_root_must_be_suitable_for_later_leaf_creation(self):
        with patch.object(self.module.os, "access", return_value=False):
            with self.assertRaisesRegex(self.module.StorageValidationError, "durable_root_not_writable"):
                self.validate()

    def test_validator_does_not_import_sqlite_or_fastapi(self):
        source = SCRIPT.read_text(encoding="utf-8").lower()
        self.assertNotIn("sqlite", source)
        self.assertNotIn("fastapi", source)
        self.assertNotIn("socket", source)
        self.assertNotIn("write_text", source)
        self.assertNotIn("mkdir", source)

    def test_output_is_bounded_and_does_not_include_paths_or_exception_text(self):
        completed = subprocess.run([sys.executable, str(SCRIPT), "--mode", "durable"], capture_output=True, text=True, check=False)
        self.assertEqual(completed.returncode, 1)
        self.assertRegex(completed.stdout, r"^stage77_storage_prerequisite=failed code=[a-z_]+$")
        self.assertEqual(completed.stderr, "")
        self.assertNotIn(str(self.root), completed.stdout)
        self.assertNotIn("Traceback", completed.stdout)

    def test_non_durable_mode_is_not_accepted(self):
        with self.assertRaisesRegex(self.module.StorageValidationError, "unexpected_diagnostic_failure"):
            self.validate(mode="development")

    def test_start_command_replica_restart_and_gate_contract_are_unchanged(self):
        config = json.loads((ROOT / "railway.json").read_text(encoding="utf-8"))
        self.assertEqual(config["deploy"]["startCommand"], "uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000}")
        self.assertEqual(config["deploy"]["numReplicas"], 1)
        self.assertEqual(config["deploy"]["restartPolicyType"], "ON_FAILURE")
        self.assertEqual(config["deploy"]["preDeployCommand"], ["sh scripts/check_pdf_predeploy_gate.sh"])

    def test_no_stage77_ledger_entry_or_public_route_was_added(self):
        ledger = (ROOT / "docs" / "releases" / "CDE_PLATFORM_STAGE_LEDGER.md").read_text(encoding="utf-8")
        self.assertNotIn("| 77 |", ledger)
        main_source = (ROOT / "api" / "main.py").read_text(encoding="utf-8")
        self.assertNotIn("check_report_storage_runtime", main_source)


if __name__ == "__main__":
    unittest.main()
