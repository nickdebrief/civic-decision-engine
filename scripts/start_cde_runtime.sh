#!/bin/sh
set -eu
export PYTHONUNBUFFERED=1

printf '%s\n' 'stage77_storage_prerequisite=start'
python scripts/check_report_storage_runtime.py --mode durable
printf '%s\n' 'stage77_storage_prerequisite=passed'

export CDE_RUNTIME_PORT="${PORT:-8000}"
exec python scripts/cde_runtime_supervisor.py
