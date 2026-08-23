"""One-service Stage 77 supervisor for Uvicorn and one report worker."""
from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import sys
import time


def _stop(process: subprocess.Popen[str], deadline: float) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    while process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.05)
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def main() -> int:
    db_path = os.environ.get("RECORDS_DB_PATH", "records.db")
    port = os.environ.get("CDE_RUNTIME_PORT", os.environ.get("PORT", "8000"))
    env = dict(os.environ)
    env.update({"PYTHONUNBUFFERED": "1", "RECORDS_DB_PATH": db_path, "CDE_REPORT_ARTIFACT_ROOT": os.environ.get("CDE_REPORT_ARTIFACT_ROOT", "")})
    app = subprocess.Popen([sys.executable, "-m", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", port], start_new_session=True, env=env)
    worker = subprocess.Popen([sys.executable, "-m", "api.governed_report_worker"], start_new_session=True, env=env)
    draining = False

    def shutdown(*_args: object) -> None:
        nonlocal draining
        if draining:
            return
        draining = True
        print("stage77_supervisor=drain_start", flush=True)
        deadline = time.monotonic() + 30
        _stop(worker, deadline)
        _stop(app, deadline)
        print("stage77_supervisor=children_reaped", flush=True)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    while not draining:
        app_code = app.poll()
        worker_code = worker.poll()
        if app_code is not None or worker_code is not None:
            if app_code is None:
                _stop(app, time.monotonic() + 5)
            if worker_code is None:
                _stop(worker, time.monotonic() + 5)
            print(f"stage77_supervisor=child_failure app={app_code is not None} worker={worker_code is not None}", flush=True)
            return 1
        time.sleep(0.2)
    app_code = app.wait()
    worker_code = worker.wait()
    return 0 if app_code == 0 and worker_code == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
