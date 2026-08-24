"""Import-safe Stage 77 worker entry point."""
from __future__ import annotations

import os
import signal
import threading

from api.governed_report_jobs import worker_loop


def _announce_ready() -> None:
    print("stage77_worker=ready", flush=True)
    raw_fd = os.environ.get("CDE_WORKER_READY_FD")
    if raw_fd is None:
        return
    try:
        fd = int(raw_fd)
        os.write(fd, b"ready\n")
        os.close(fd)
    except (OSError, ValueError):
        print("stage77_worker=readiness_signal_failed", flush=True)
        raise


def main() -> int:
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    return worker_loop(os.environ.get("RECORDS_DB_PATH", "records.db"), stop, _announce_ready)


if __name__ == "__main__":
    raise SystemExit(main())
