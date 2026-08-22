#!/bin/sh
set -eu

printf '%s\n' 'stage76_gate_runtime_check=start'
python scripts/check_pdf_runtime.py
printf '%s\n' 'stage76_gate_runtime_check=passed'

printf '%s\n' 'stage76_gate_synthetic_check=start'
python scripts/check_pdf_synthetic_conversion.py
printf '%s\n' 'stage76_gate_synthetic_check=passed'
