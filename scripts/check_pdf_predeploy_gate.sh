#!/bin/sh
set -eu
export PYTHONUNBUFFERED=1

printf '%s\n' 'stage77_storage_prerequisite=start'
python scripts/check_report_storage_runtime.py --mode durable
printf '%s\n' 'stage77_storage_prerequisite=passed'

printf '%s\n' 'stage76_gate_runtime_check=start'
python scripts/check_pdf_runtime.py
printf '%s\n' 'stage76_gate_runtime_check=passed'

printf '%s\n' 'stage76_gate_synthetic_check=start'
python scripts/check_pdf_synthetic_conversion.py
printf '%s\n' 'stage76_gate_synthetic_check=passed'

printf '%s\n' 'stage76_gate_adapter_check=start'
python scripts/check_stage76_adapter_synthetic.py
printf '%s\n' 'stage76_gate_adapter_check=passed'
