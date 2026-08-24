"""One-service Stage 77 supervisor for Uvicorn and one report worker."""
from __future__ import annotations

import os
import select
import signal
import subprocess
import sys
import time


STARTUP_DEADLINE_SECONDS = 10
WORKER_READY_TOKEN = b"ready\n"


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


def _child_failure(app, worker) -> int:
    app_exited = app.poll() is not None
    worker_exited = worker.poll() is not None
    if app_exited or worker_exited:
        deadline = time.monotonic() + 5
        if not app_exited:
            _stop(app, deadline)
        if not worker_exited:
            _stop(worker, deadline)
        print(f"stage77_supervisor=child_failure app={app_exited} worker={worker_exited}", flush=True)
        return 1
    return 0


def _await_worker_ready(app, worker, ready_fd: int) -> bool:
    deadline = time.monotonic() + STARTUP_DEADLINE_SECONDS
    received = bytearray()
    try:
        os.set_blocking(ready_fd, False)
        while time.monotonic() < deadline:
            if app.poll() is not None or worker.poll() is not None:
                return False
            readable, _, _ = select.select([ready_fd], [], [], 0.1)
            if readable:
                chunk = os.read(ready_fd, 64)
                if not chunk:
                    return received == WORKER_READY_TOKEN
                received.extend(chunk)
                if len(received) > len(WORKER_READY_TOKEN) or not WORKER_READY_TOKEN.startswith(received):
                    return False
                if received == WORKER_READY_TOKEN:
                    continue
        return False
    finally:
        os.close(ready_fd)


def main() -> int:
    print("stage77_supervisor=start", flush=True)
    db_path = os.environ.get("RECORDS_DB_PATH", "records.db")
    port = os.environ.get("CDE_RUNTIME_PORT", os.environ.get("PORT", "8000"))
    env = dict(os.environ)
    env.update({
        "PYTHONUNBUFFERED": "1",
        "RECORDS_DB_PATH": db_path,
        "CDE_REPORT_ARTIFACT_ROOT": os.environ.get("CDE_REPORT_ARTIFACT_ROOT", ""),
    })
    draining = False
    app = None
    worker = None

    def shutdown(*_args: object) -> None:
        nonlocal draining
        if draining:
            return
        draining = True
        print("stage77_supervisor=drain_start", flush=True)
        deadline = time.monotonic() + 30
        if worker is not None:
            _stop(worker, deadline)
        if app is not None:
            _stop(app, deadline)
        print("stage77_supervisor=children_reaped", flush=True)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    ready_read, ready_write = os.pipe()
    try:
        app = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", port],
            start_new_session=True,
            env=env,
        )
        print("stage77_supervisor_application_child=started", flush=True)
        env["CDE_WORKER_READY_FD"] = str(ready_write)
        worker = subprocess.Popen(
            [sys.executable, "-m", "api.governed_report_worker"],
            start_new_session=True,
            env=env,
            pass_fds=(ready_write,),
        )
        print("stage77_supervisor_worker_child=started", flush=True)
    except Exception:
        os.close(ready_read)
        if app is not None:
            _stop(app, time.monotonic() + 5)
            app.wait()
        print("stage77_supervisor=child_failure app=True worker=True", flush=True)
        return 1
    finally:
        os.close(ready_write)

    if not _await_worker_ready(app, worker, ready_read):
        if draining:
            app_code = app.wait()
            worker_code = worker.wait()
            return 0 if app_code == 0 and worker_code == 0 else 1
        if app.poll() is None and worker.poll() is None:
            print("stage77_supervisor=startup_failure code=worker_not_ready", flush=True)
        _child_failure(app, worker)
        if app.poll() is None:
            _stop(app, time.monotonic() + 5)
        if worker.poll() is None:
            _stop(worker, time.monotonic() + 5)
        app.wait()
        worker.wait()
        return 1

    if app.poll() is not None or worker.poll() is not None:
        _child_failure(app, worker)
        return 1
    print("stage77_supervisor_attestation=ready protocol=1 application_child=alive worker_child=ready", flush=True)
    print("stage77_supervisor=ready", flush=True)
    while not draining:
        if app.poll() is not None or worker.poll() is not None:
            return _child_failure(app, worker)
        time.sleep(0.2)
    app_code = app.wait()
    worker_code = worker.wait()
    return 0 if app_code == 0 and worker_code == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
