"""Import-safe Stage 77 worker entry point."""
from __future__ import annotations

import os
import signal
import threading

from api.governed_report_jobs import worker_loop


def main() -> int:
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    return worker_loop(os.environ.get("RECORDS_DB_PATH", "records.db"), stop)


if __name__ == "__main__":
    raise SystemExit(main())
