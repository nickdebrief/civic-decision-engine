#!/bin/sh
set -eu
export PYTHONUNBUFFERED=1

printf '%s\n' 'stage77_storage_prerequisite=start'
python scripts/check_report_storage_runtime.py --mode durable
printf '%s\n' 'stage77_storage_prerequisite=passed'

exec uvicorn api.main:app --host 0.0.0.0 --port "${PORT:-8000}"
