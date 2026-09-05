import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import io
from pathlib import Path
from unittest.mock import patch

from scripts import run_isolated_tests as launcher


class Completed:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class RunRecorder:
    def __init__(self, *, child_status=0, lsof_status=1, lsof_stdout="", mutate=None):
        self.child_status = child_status
        self.lsof_status = lsof_status
        self.lsof_stdout = lsof_stdout
        self.mutate = mutate
        self.calls = []
        self.child_calls = 0
        self.child_tmpdir_was_dir = None

    def __call__(self, command, **kwargs):
        self.calls.append((command, kwargs))
        if command and str(command[0]).endswith("lsof"):
            return Completed(self.lsof_status, self.lsof_stdout, "")
        self.child_calls += 1
        self.child_tmpdir_was_dir = Path(kwargs["env"]["TMPDIR"]).is_dir()
        if self.mutate is not None:
            self.mutate()
        return Completed(self.child_status)


class DeveloperDatabaseLauncherTests(unittest.TestCase):
    def setUp(self):
        self.root_dir = tempfile.TemporaryDirectory()
        self.repo = Path(self.root_dir.name)
        (self.repo / "scripts").mkdir()
        self.database = self.repo / "records.db"
        self.database.write_bytes(b"developer-database")
        self.temp_dirs = []
        self.cleaned = []

    def tearDown(self):
        for path in self.temp_dirs:
            shutil.rmtree(path, ignore_errors=True)
        self.root_dir.cleanup()

    def make_temp(self):
        path = Path(tempfile.mkdtemp(prefix="launcher-test-"))
        self.temp_dirs.append(path)
        return str(path)

    def cleanup(self, path):
        self.cleaned.append(Path(path))
        shutil.rmtree(path)

    def run_launcher(self, args, *, recorder=None, env=None):
        recorder = recorder or RunRecorder()
        with patch.object(launcher.shutil, "which", return_value="/usr/sbin/lsof"):
            status = launcher.run_isolated_tests(
                args,
                repo_root=self.repo,
                inherited_environment=env or {"EXISTING": "1"},
                run_process=recorder,
                temp_dir_factory=self.make_temp,
                cleanup=self.cleanup,
                stdout=io.StringIO(),
                stderr=io.StringIO(),
            )
        return status, recorder

    def test_repository_root_derivation(self):
        self.assertEqual(launcher.repository_root(), Path(launcher.__file__).resolve().parent.parent)

    def test_ordinary_file_identity_snapshot_and_sha256(self):
        identity = launcher.file_identity(self.database)
        self.assertTrue(identity.exists)
        self.assertEqual(identity.size, len(b"developer-database"))
        self.assertEqual(len(identity.sha256), 64)

    def test_sidecar_detection(self):
        (self.repo / "records.db-wal").write_bytes(b"wal")
        status, recorder = self.run_launcher(["unittest", "dummy"])
        self.assertEqual(status, launcher.CONTAINMENT_STATUS)
        self.assertEqual(recorder.child_calls, 0)

    def test_exact_before_after_equality_allows_child_status(self):
        status, recorder = self.run_launcher(["unittest", "dummy"], recorder=RunRecorder(child_status=7))
        self.assertEqual(status, 7)
        self.assertEqual(recorder.child_calls, 1)

    def test_content_mutation_with_same_size_is_detected(self):
        def mutate():
            self.database.write_bytes(b"Developer-database")
        status, _recorder = self.run_launcher(["unittest", "dummy"], recorder=RunRecorder(mutate=mutate))
        self.assertEqual(status, launcher.CONTAINMENT_STATUS)

    def test_mtime_only_mutation_is_detected(self):
        def mutate():
            stat = self.database.stat()
            os.utime(self.database, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
        status, _recorder = self.run_launcher(["unittest", "dummy"], recorder=RunRecorder(mutate=mutate))
        self.assertEqual(status, launcher.CONTAINMENT_STATUS)

    def test_replacement_inode_is_detected(self):
        def mutate():
            replacement = self.repo / "replacement.db"
            replacement.write_bytes(b"developer-database")
            replacement.replace(self.database)
        status, _recorder = self.run_launcher(["unittest", "dummy"], recorder=RunRecorder(mutate=mutate))
        self.assertEqual(status, launcher.CONTAINMENT_STATUS)

    def test_missing_to_created_database_transition_is_detected(self):
        self.database.unlink()
        def mutate():
            self.database.write_bytes(b"created")
        status, _recorder = self.run_launcher(["unittest", "dummy"], recorder=RunRecorder(mutate=mutate))
        self.assertEqual(status, launcher.CONTAINMENT_STATUS)

    def test_created_to_missing_database_transition_is_detected(self):
        def mutate():
            self.database.unlink()
        status, _recorder = self.run_launcher(["unittest", "dummy"], recorder=RunRecorder(mutate=mutate))
        self.assertEqual(status, launcher.CONTAINMENT_STATUS)

    def test_unsupported_framework_rejected_before_child_launch(self):
        status, recorder = self.run_launcher(["python", "-m", "unittest"])
        self.assertEqual(status, launcher.USAGE_STATUS)
        self.assertEqual(recorder.child_calls, 0)

    def test_raw_executable_command_rejected(self):
        status, recorder = self.run_launcher(["/usr/bin/python3", "-m", "unittest"])
        self.assertEqual(status, launcher.USAGE_STATUS)
        self.assertEqual(recorder.child_calls, 0)

    def test_child_argv_uses_module_invocation_and_shell_false(self):
        status, recorder = self.run_launcher(["pytest", "-q", "tests/example.py"])
        self.assertEqual(status, 0)
        child = [call for call in recorder.calls if not str(call[0][0]).endswith("lsof")][0]
        self.assertEqual(child[0], [sys.executable, "-m", "pytest", "-q", "tests/example.py"])
        self.assertFalse(child[1]["shell"])

    def test_child_receives_absolute_isolated_records_db_path(self):
        _status, recorder = self.run_launcher(["unittest", "dummy"])
        child = [call for call in recorder.calls if not str(call[0][0]).endswith("lsof")][0]
        value = Path(child[1]["env"]["RECORDS_DB_PATH"])
        self.assertTrue(value.is_absolute())
        self.assertNotEqual(value, self.database.resolve())
        self.assertFalse(value.exists())

    def test_child_receives_isolated_tmpdir(self):
        _status, recorder = self.run_launcher(["unittest", "dummy"])
        child = [call for call in recorder.calls if not str(call[0][0]).endswith("lsof")][0]
        tmpdir = Path(child[1]["env"]["TMPDIR"])
        self.assertTrue(tmpdir.is_absolute())
        self.assertTrue(recorder.child_tmpdir_was_dir)

    def test_child_receives_dont_write_bytecode(self):
        _status, recorder = self.run_launcher(["unittest", "dummy"])
        child = [call for call in recorder.calls if not str(call[0][0]).endswith("lsof")][0]
        self.assertEqual(child[1]["env"]["PYTHONDONTWRITEBYTECODE"], "1")

    def test_parent_environment_is_not_globally_mutated(self):
        before = dict(os.environ)
        self.run_launcher(["unittest", "dummy"], env={"RECORDS_DB_PATH": "/old", "TMPDIR": "/tmp"})
        self.assertEqual(dict(os.environ), before)

    def test_child_exit_status_is_preserved(self):
        status, _recorder = self.run_launcher(["unittest", "dummy"], recorder=RunRecorder(child_status=23))
        self.assertEqual(status, 23)

    def test_containment_failure_overrides_child_status(self):
        def mutate():
            self.database.write_bytes(b"changed")
        status, _recorder = self.run_launcher(["unittest", "dummy"], recorder=RunRecorder(child_status=0, mutate=mutate))
        self.assertEqual(status, launcher.CONTAINMENT_STATUS)

    def test_no_second_child_is_launched_after_containment_failure(self):
        def mutate():
            self.database.write_bytes(b"changed")
        status, recorder = self.run_launcher(["unittest", "dummy"], recorder=RunRecorder(mutate=mutate))
        self.assertEqual(status, launcher.CONTAINMENT_STATUS)
        self.assertEqual(recorder.child_calls, 1)

    def test_missing_lsof_fails_closed(self):
        with patch.object(launcher.shutil, "which", return_value=None):
            status = launcher.run_isolated_tests(
                ["unittest", "dummy"],
                repo_root=self.repo,
                run_process=RunRecorder(),
                temp_dir_factory=self.make_temp,
                cleanup=self.cleanup,
                stdout=io.StringIO(),
                stderr=io.StringIO(),
            )
        self.assertEqual(status, launcher.INFRASTRUCTURE_STATUS)

    def test_indeterminate_lsof_fails_closed(self):
        status, recorder = self.run_launcher(["unittest", "dummy"], recorder=RunRecorder(lsof_status=2, lsof_stdout=""))
        self.assertEqual(status, launcher.INFRASTRUCTURE_STATUS)
        self.assertEqual(recorder.child_calls, 0)

    def test_launcher_owned_directory_cleans_on_success(self):
        status, _recorder = self.run_launcher(["unittest", "dummy"])
        self.assertEqual(status, 0)
        self.assertTrue(self.cleaned)
        self.assertFalse(self.cleaned[0].exists())

    def test_containment_failure_preserves_launcher_owned_evidence(self):
        def mutate():
            self.database.write_bytes(b"changed")
        status, _recorder = self.run_launcher(["unittest", "dummy"], recorder=RunRecorder(mutate=mutate))
        self.assertEqual(status, launcher.CONTAINMENT_STATUS)
        self.assertFalse(self.cleaned)
        self.assertTrue(any(path.exists() for path in self.temp_dirs))

    def test_no_cleanup_targets_synthetic_developer_database_or_sidecars(self):
        sidecar = self.repo / "records.db-wal"
        sidecar.write_bytes(b"wal")
        status, _recorder = self.run_launcher(["unittest", "dummy"])
        self.assertEqual(status, launcher.CONTAINMENT_STATUS)
        self.assertTrue(self.database.exists())
        self.assertTrue(sidecar.exists())


if __name__ == "__main__":
    unittest.main()
