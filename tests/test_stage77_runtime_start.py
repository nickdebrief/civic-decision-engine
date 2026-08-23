import os
import signal
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "scripts" / "start_cde_runtime.sh"


class Stage77RuntimeStartTests(unittest.TestCase):
    def _run_wrapper(self, storage_status=0, port=None):
        with tempfile.TemporaryDirectory(prefix="stage77-wrapper-test-") as temp:
            directory = Path(temp)
            log = directory / "calls.log"
            fake_python = directory / "python"
            fake_uvicorn = directory / "uvicorn"
            fake_python.write_text(
                "#!/bin/sh\n"
                "printf 'python:%s\n' \"$*\" >> \"$LOG\"\n"
                f"exit {storage_status}\n",
                encoding="utf-8",
            )
            fake_uvicorn.write_text(
                "#!/bin/sh\n"
                "printf 'argc=%s\\n' \"$#\" >> \"$LOG\"\n"
                "for arg in \"$@\"; do printf 'arg=<%s>\\n' \"$arg\" >> \"$LOG\"; done\n"
                "exit 17\n",
                encoding="utf-8",
            )
            fake_python.chmod(0o700)
            fake_uvicorn.chmod(0o700)
            environment = {**os.environ, "PATH": f"{directory}:/usr/bin:/bin", "LOG": str(log)}
            if port is None:
                environment.pop("PORT", None)
            else:
                environment["PORT"] = port
            completed = subprocess.run(["sh", str(WRAPPER)], cwd=ROOT, env=environment, capture_output=True, text=True, check=False)
            return completed, log.read_text(encoding="utf-8").splitlines() if log.exists() else []

    def test_success_runs_storage_once_then_execs_uvicorn_once(self):
        completed, calls = self._run_wrapper(storage_status=0, port="9123")
        self.assertEqual(completed.returncode, 17)
        self.assertEqual(calls, [
            "python:scripts/check_report_storage_runtime.py --mode durable",
            "argc=5",
            "arg=<api.main:app>",
            "arg=<--host>",
            "arg=<0.0.0.0>",
            "arg=<--port>",
            "arg=<9123>",
        ])

    def test_failure_never_starts_uvicorn_and_propagates_status(self):
        completed, calls = self._run_wrapper(storage_status=23, port="9123")
        self.assertEqual(completed.returncode, 23)
        self.assertEqual(calls, ["python:scripts/check_report_storage_runtime.py --mode durable"])

    def test_default_port_is_preserved(self):
        completed, calls = self._run_wrapper(storage_status=0)
        self.assertEqual(completed.returncode, 17)
        self.assertEqual(calls[-1], "arg=<8000>")

    def test_hostile_port_values_are_data_and_never_executed(self):
        hostile = (
            "9000 9001",
            "9000;touch SHOULD_NOT_EXIST",
            "$(touch SHOULD_NOT_EXIST)",
            "9000'\"",
            "9000&|<>",
            "--bad-port",
            "",
            "9" * 4096,
        )
        for value in hostile:
            with self.subTest(value=value):
                completed, calls = self._run_wrapper(storage_status=0, port=value)
                self.assertEqual(completed.returncode, 17)
                self.assertEqual(calls[0], "python:scripts/check_report_storage_runtime.py --mode durable")
                self.assertEqual(calls[1], "argc=5")
                self.assertEqual(calls[-1], f"arg=<{value or '8000'}>")
        completed, calls = self._run_wrapper(storage_status=0, port="9000\n9001")
        self.assertEqual(completed.returncode, 17)
        self.assertEqual(calls[:2], ["python:scripts/check_report_storage_runtime.py --mode durable", "argc=5"])

    def test_signal_reaches_final_fake_uvicorn_and_exit_status_is_preserved(self):
        with tempfile.TemporaryDirectory(prefix="stage77-signal-test-") as temp:
            directory = Path(temp)
            fake_python = directory / "python"
            fake_uvicorn = directory / "uvicorn"
            ready = directory / "ready"
            fake_python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            fake_uvicorn.write_text(
                "#!/bin/sh\n"
                "printf ready > \"$READY\"\n"
                "trap 'exit 42' TERM INT\n"
                "while :; do sleep 1; done\n",
                encoding="utf-8",
            )
            fake_python.chmod(0o700)
            fake_uvicorn.chmod(0o700)
            environment = {**os.environ, "PATH": f"{directory}:/usr/bin:/bin", "READY": str(ready)}
            process = subprocess.Popen(["sh", str(WRAPPER)], cwd=ROOT, env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True)
            try:
                for _ in range(50):
                    if ready.exists():
                        break
                    if process.poll() is not None:
                        self.fail(f"wrapper exited before final process started: {process.returncode}")
                    __import__("time").sleep(0.01)
                self.assertTrue(ready.exists())
                process.send_signal(signal.SIGTERM)
                self.assertEqual(process.wait(timeout=5), 42)
            finally:
                if process.poll() is None:
                    process.kill()

    def test_wrapper_is_single_process_fail_closed_and_non_mutating(self):
        source = WRAPPER.read_text(encoding="utf-8")
        self.assertIn("set -eu", source)
        self.assertIn("exec uvicorn", source)
        self.assertNotIn("&", source)
        self.assertNotIn("--reload", source)
        self.assertNotIn("worker", source.lower())
        self.assertNotIn("mkdir", source)
        self.assertNotIn("touch", source)
        self.assertNotIn("set -x", source)


if __name__ == "__main__":
    unittest.main()
