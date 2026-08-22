"""Isolated Stage 75 bridge to the documented Publication Engine v2.0.0."""

from __future__ import annotations

import json
import hashlib
import os
import signal
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping

from api.record_governed_reports import canonical_json


ENGINE_VERSION = "2.0.0"
ADAPTER_TIMEOUT_SECONDS = 210
ADAPTER = Path(__file__).resolve().parents[1] / "scripts" / "evidence_led_governance_pipeline" / "report_adapter.py"


def _terminate_process_group(process: subprocess.Popen[str]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.communicate(timeout=5)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def render_frozen_report(specification: Mapping[str, Any], digest: str, output_dir: Path) -> dict[str, Any]:
    if specification.get("publication_engine_version") != ENGINE_VERSION:
        raise ValueError("governed_report_publication_engine_version_invalid")
    if __import__("hashlib").sha256(canonical_json(specification).encode("utf-8")).hexdigest() != digest:
        raise ValueError("governed_report_specification_digest_mismatch")
    promoted = []
    with tempfile.TemporaryDirectory(prefix="cde-stage75-") as temp:
        request = Path(temp) / "specification.json"
        staged_output = Path(temp) / "output"
        staged_output.mkdir()
        request.write_text(json.dumps({"specification": specification, "digest": digest}, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        command = [sys.executable, str(ADAPTER), str(request), str(staged_output)]
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
            env={"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(ADAPTER.parent)},
        )
        try:
            stdout, stderr = process.communicate(timeout=ADAPTER_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            _terminate_process_group(process)
            raise ValueError("governed_report_renderer_timeout") from None
        completed = subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
        if completed.returncode != 0:
            raise ValueError("governed_report_renderer_failed")
        try:
            result = json.loads(completed.stdout)
        except json.JSONDecodeError:
            raise ValueError("governed_report_renderer_invalid_diagnostics") from None
        if result.get("specification_digest") != digest or not result.get("artifacts"):
            raise ValueError("governed_report_renderer_validation_failed")
        output_dir.mkdir(parents=True, exist_ok=True)
        for item in result["artifacts"]:
            source = Path(item["path"]).resolve()
            if source.parent != staged_output.resolve() or not source.is_file():
                raise ValueError("governed_report_renderer_path_invalid")
            destination = output_dir / source.name
            if destination.exists() or destination.is_symlink():
                raise ValueError("governed_report_renderer_artifact_exists")
            staged_destination = output_dir / f".{source.name}.stage75-{os.getpid()}"
            shutil.copy2(source, staged_destination)
            os.replace(staged_destination, destination)
            item["path"] = str(destination)
            item["sha256"] = hashlib.sha256(destination.read_bytes()).hexdigest()
            item["size_bytes"] = destination.stat().st_size
            promoted.append(item)
        result["artifacts"] = promoted
    return result
