import os
import signal
import sqlite3
import subprocess
import tempfile
import unittest
import importlib.util
from api import governed_report_jobs as jobs
from api import governed_custody_evidence as custody_evidence
from api import main as application_main
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "scripts" / "start_cde_runtime.sh"


class Stage77RuntimeStartTests(unittest.TestCase):
    def test_application_startup_registers_and_reaches_the_custody_initializer_once(self):
        self.assertIn(
            application_main.initialize_stage77_custody_authority,
            application_main.app.router.on_startup,
        )
        connection = Mock()
        with patch.object(application_main.sqlite3, "connect", return_value=connection) as connect, patch.object(jobs, "ensure_custody_v2_tables") as ensure:
            application_main.initialize_stage77_custody_authority()
        connect.assert_called_once_with(os.environ.get("RECORDS_DB_PATH", "records.db"))
        self.assertIs(connection.row_factory, sqlite3.Row)
        ensure.assert_called_once_with(connection)
        connection.commit.assert_called_once()
        connection.close.assert_called_once()

    def test_v2_initializer_reaches_registry_initializer_exactly_once(self):
        connection = sqlite3.connect(":memory:")
        try:
            with patch.object(custody_evidence, "ensure_custody_evidence_tables", wraps=custody_evidence.ensure_custody_evidence_tables) as ensure:
                jobs.ensure_custody_v2_tables(connection)
            ensure.assert_called_once_with(connection)
        finally:
            connection.close()

    def test_startup_initialization_is_idempotent_and_creates_registry_schema_indexes_and_guards(self):
        with tempfile.TemporaryDirectory(prefix="stage77-startup-schema-") as temp:
            database_path = Path(temp) / "isolated.sqlite3"
            with patch.dict(os.environ, {"RECORDS_DB_PATH": str(database_path)}, clear=False):
                application_main.initialize_stage77_custody_authority()
                application_main.initialize_stage77_custody_authority()
            connection = sqlite3.connect(database_path)
            try:
                tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                indexes = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='index'")}
                triggers = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
                self.assertTrue({"stage77_custody_evidence_sets", "stage77_custody_evidence_objects", "stage77_custody_evidence_events", "stage77_custody_v2_mandates", "stage77_custody_v2_attestations", "stage77_custody_v2_events"} <= tables)
                self.assertIn("idx_stage77_custody_v2_attestation_report", indexes)
                self.assertIn("stage77_custody_evidence_set_no_delete", triggers)
                self.assertIn("stage77_custody_v2_attestation_authority_immutable", triggers)
                for table in ("stage77_custody_v2_mandates", "stage77_custody_evidence_sets", "stage77_custody_evidence_events", "stage77_custody_v2_attestations", "stage77_report_jobs"):
                    self.assertEqual(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0)
            finally:
                connection.close()

    def test_startup_failure_propagates_and_closes_the_established_connection(self):
        connection = Mock()
        with patch.object(application_main.sqlite3, "connect", return_value=connection), patch.object(jobs, "ensure_custody_v2_tables", side_effect=sqlite3.DatabaseError("schema failure")):
            with self.assertRaisesRegex(sqlite3.DatabaseError, "schema failure"):
                application_main.initialize_stage77_custody_authority()
        connection.commit.assert_not_called()
        connection.close.assert_called_once()

    def test_initialization_does_not_add_routes_or_change_legacy_v1_schema(self):
        routes_before = tuple((route.path, tuple(sorted(getattr(route, "methods", ())))) for route in application_main.app.routes)
        with tempfile.TemporaryDirectory(prefix="stage77-startup-routes-") as temp:
            database_path = Path(temp) / "isolated.sqlite3"
            legacy = sqlite3.connect(database_path)
            try:
                legacy.execute("CREATE TABLE stage77_post_correction_custody_attestations (id TEXT PRIMARY KEY, legacy_marker TEXT NOT NULL)")
                legacy.execute("INSERT INTO stage77_post_correction_custody_attestations VALUES ('legacy-1','preserved')")
                legacy.commit()
            finally:
                legacy.close()
            with patch.dict(os.environ, {"RECORDS_DB_PATH": str(database_path)}, clear=False):
                application_main.initialize_stage77_custody_authority()
            connection = sqlite3.connect(database_path)
            try:
                tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                self.assertIn("stage77_post_correction_custody_attestations", tables)
                self.assertEqual(connection.execute("SELECT legacy_marker FROM stage77_post_correction_custody_attestations WHERE id='legacy-1'").fetchone()[0], "preserved")
                self.assertNotIn("stage77_custody_evidence_registrar", {path for path, _methods in routes_before})
                self.assertEqual(routes_before, tuple((route.path, tuple(sorted(getattr(route, "methods", ())))) for route in application_main.app.routes))
            finally:
                connection.close()

    def test_v2_runtime_start_is_inert_before_activation_and_closed_when_malformed(self):
        with patch.dict(os.environ, {jobs.CUSTODY_V2_ENABLE_ENV: ""}, clear=False):
            self.assertIsNone(jobs.validate_custody_v2_runtime_start())
        with patch.dict(os.environ, {jobs.CUSTODY_V2_ENABLE_ENV: "unexpected"}, clear=False):
            with self.assertRaisesRegex(ValueError, "activation_invalid"):
                jobs.validate_custody_v2_runtime_start()

    def _run_wrapper(self, storage_status=0, port=None):
        with tempfile.TemporaryDirectory(prefix="stage77-wrapper-test-") as temp:
            directory = Path(temp)
            log = directory / "calls.log"
            fake_python = directory / "python"
            fake_python.write_text(
                "#!/bin/sh\n"
                "printf 'python:%s\\n' \"$*\" >> \"$LOG\"\n"
                "case \"$1\" in\n"
                f"  scripts/check_report_storage_runtime.py) exit {storage_status} ;;\n"
                "  scripts/cde_runtime_supervisor.py) printf 'port:%s\\n' \"$CDE_RUNTIME_PORT\" >> \"$LOG\"; exit 17 ;;\n"
                "esac\nexit 19\n",
                encoding="utf-8",
            )
            fake_python.chmod(0o700)
            environment = {**os.environ, "PATH": f"{directory}:/usr/bin:/bin", "LOG": str(log)}
            if port is None:
                environment.pop("PORT", None)
            else:
                environment["PORT"] = port
            completed = subprocess.run(["sh", str(WRAPPER)], cwd=ROOT, env=environment, capture_output=True, text=True, check=False)
            return completed, log.read_text(encoding="utf-8").splitlines() if log.exists() else []

    def test_success_runs_storage_once_then_supervisor_once(self):
        completed, calls = self._run_wrapper()
        self.assertEqual(completed.returncode, 17)
        self.assertEqual(calls, ["python:scripts/check_report_storage_runtime.py --mode durable", "python:scripts/cde_runtime_supervisor.py", "port:8000"])

    def test_explicit_port_is_passed_as_data(self):
        completed, calls = self._run_wrapper(port="9000;never-execute")
        self.assertEqual(completed.returncode, 17)
        self.assertEqual(calls[-1], "port:9000;never-execute")

    def test_failure_never_starts_supervisor(self):
        completed, calls = self._run_wrapper(storage_status=23)
        self.assertEqual(completed.returncode, 23)
        self.assertEqual(calls, ["python:scripts/check_report_storage_runtime.py --mode durable"])

    def test_signal_reaches_final_supervisor_process(self):
        with tempfile.TemporaryDirectory(prefix="stage77-signal-test-") as temp:
            directory = Path(temp)
            fake_python = directory / "python"
            fake_python.write_text("#!/bin/sh\ncase \"$1\" in scripts/check_report_storage_runtime.py) exit 0;; scripts/cde_runtime_supervisor.py) trap 'exit 42' TERM INT; while :; do sleep 1; done;; esac\n", encoding="utf-8")
            fake_python.chmod(0o700)
            environment = {**os.environ, "PATH": f"{directory}:/usr/bin:/bin"}
            process = subprocess.Popen(["sh", str(WRAPPER)], cwd=ROOT, env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                __import__("time").sleep(0.2)
                self.assertIsNone(process.poll())
                process.send_signal(signal.SIGTERM)
                self.assertEqual(process.wait(timeout=5), 42)
            finally:
                if process.poll() is None:
                    process.kill()

    def test_wrapper_is_bounded_and_non_mutating(self):
        source = WRAPPER.read_text(encoding="utf-8")
        self.assertIn("set -eu", source)
        self.assertIn("exec python scripts/cde_runtime_supervisor.py", source)
        self.assertNotIn("&", source)
        self.assertNotIn("--reload", source)
        self.assertNotIn("mkdir", source)
        self.assertNotIn("touch", source)
        self.assertNotIn("set -x", source)

    def test_supervisor_starts_distinct_children_and_drains_both(self):
        spec = importlib.util.spec_from_file_location("stage77_supervisor", ROOT / "scripts" / "cde_runtime_supervisor.py")
        supervisor = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(supervisor)
        class Child:
            _next_pid = 100
            def __init__(self):
                self.pid = Child._next_pid
                Child._next_pid += 1
            def poll(self):
                return None
            def wait(self):
                return 0
        calls = []
        handlers = {}
        def fake_popen(command, **kwargs):
            calls.append((command, kwargs))
            if command[-1] == "api.governed_report_worker":
                os.write(kwargs["pass_fds"][0], b"ready\n")
            return Child()
        def fake_signal(signum, handler):
            handlers[signum] = handler
        sleeps = []
        def fake_sleep(_seconds):
            sleeps.append(True)
            if len(sleeps) == 1:
                handlers[signal.SIGTERM]()
        output = StringIO()
        with patch.object(supervisor.subprocess, "Popen", side_effect=fake_popen), patch.object(supervisor.signal, "signal", side_effect=fake_signal), patch.object(supervisor, "_stop"), patch.object(supervisor.time, "sleep", side_effect=fake_sleep), patch.dict(os.environ, {"CDE_RUNTIME_PORT": "9123"}), redirect_stdout(output):
            self.assertEqual(supervisor.main(), 0)
        self.assertEqual([call[0][2] for call in calls], ["uvicorn", "api.governed_report_worker"])
        self.assertIn("--host", calls[0][0])
        self.assertIn("0.0.0.0", calls[0][0])
        self.assertIn("9123", calls[0][0])
        self.assertTrue(all(call[1]["start_new_session"] for call in calls))
        markers = [line for line in output.getvalue().splitlines() if line.startswith("stage77_")]
        self.assertEqual(markers, [
            "stage77_supervisor=start",
            "stage77_supervisor_application_child=started",
            "stage77_supervisor_worker_child=started",
            "stage77_supervisor_attestation=ready protocol=1 application_child=alive worker_child=ready",
            "stage77_supervisor=ready",
            "stage77_supervisor=drain_start",
            "stage77_supervisor=children_reaped",
        ])

    def test_worker_token_must_be_exactly_once_and_followed_by_eof(self):
        spec = importlib.util.spec_from_file_location("stage77_supervisor", ROOT / "scripts" / "cde_runtime_supervisor.py")
        supervisor = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(supervisor)
        class Child:
            def poll(self):
                return None
        for payload, expected in ((b"ready\n", True), (b"rea", False), (b"xready\n", False), (b"ready\nready\n", False)):
            read_fd, write_fd = os.pipe()
            os.write(write_fd, payload)
            os.close(write_fd)
            self.assertEqual(supervisor._await_worker_ready(Child(), Child(), read_fd), expected, payload)

    def test_attestation_is_absent_before_valid_worker_token(self):
        spec = importlib.util.spec_from_file_location("stage77_supervisor", ROOT / "scripts" / "cde_runtime_supervisor.py")
        supervisor = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(supervisor)
        class Child:
            def __init__(self):
                self.pid = 400
            def poll(self):
                return None
            def wait(self):
                return 0
        def fake_popen(_command, **_kwargs):
            return Child()
        output = StringIO()
        with patch.object(supervisor.subprocess, "Popen", side_effect=fake_popen), patch.object(supervisor, "_await_worker_ready", return_value=False), patch.object(supervisor, "_child_failure", return_value=0), patch.object(supervisor, "_stop"), patch.object(supervisor.signal, "signal"), patch.dict(os.environ, {"CDE_RUNTIME_PORT": "9123"}), redirect_stdout(output):
            self.assertEqual(supervisor.main(), 1)
        self.assertNotIn("stage77_supervisor_attestation=ready", output.getvalue())

    def test_attestation_has_fixed_allow_listed_fields(self):
        marker = "stage77_supervisor_attestation=ready protocol=1 application_child=alive worker_child=ready"
        self.assertEqual(marker.count("="), 4)
        self.assertNotRegex(marker, r"(?:pid|path|timestamp|fd|secret|environment|database|job)")

    def test_worker_command_receives_readiness_fd(self):
        spec = importlib.util.spec_from_file_location("stage77_supervisor", ROOT / "scripts" / "cde_runtime_supervisor.py")
        supervisor = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(supervisor)
        class Child:
            _next_pid = 300
            def __init__(self):
                self.pid = Child._next_pid
                Child._next_pid += 1
            def poll(self):
                return 0 if self.pid == 300 else None
            def wait(self):
                return 0
        calls = []
        def fake_popen(command, **kwargs):
            calls.append((command, kwargs))
            if command[-1] == "api.governed_report_worker":
                os.write(kwargs["pass_fds"][0], b"ready\n")
            return Child()
        with patch.object(supervisor.subprocess, "Popen", side_effect=fake_popen), patch.object(supervisor, "_stop"), patch.dict(os.environ, {"CDE_RUNTIME_PORT": "9123"}), patch.object(supervisor, "_child_failure", return_value=1):
            self.assertEqual(supervisor.main(), 1)
        self.assertEqual(calls[1][1]["pass_fds"], (calls[1][1]["pass_fds"][0],))
        self.assertEqual(calls[1][1]["env"]["CDE_WORKER_READY_FD"], str(calls[1][1]["pass_fds"][0]))


if __name__ == "__main__":
    unittest.main()
