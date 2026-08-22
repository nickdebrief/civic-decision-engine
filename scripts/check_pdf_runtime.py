#!/usr/bin/env python3
"""Read-only prerequisite diagnostic for the future governed PDF capability.

This diagnostic checks the runtime toolchain only. It never imports the CDE
application, opens its database, invokes an HTTP route, or performs a
conversion.
"""

from __future__ import annotations

import importlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


REQUIRED_COMMANDS = ("pdfinfo", "pdftotext", "fc-list")
LIBREOFFICE_COMMANDS = ("libreoffice", "soffice")
OPTIONAL_COMMANDS = ("pdfdetach",)
REQUIRED_FONTS = ("DejaVu Sans", "Liberation Sans")
VERSION_ARGUMENTS = {"pdfinfo": "-v", "pdftotext": "-v", "pdfdetach": "-v"}
REQUIRED_PYPDF_VERSION = "5.9.0"
VERSION_OUTPUT_LIMIT = 512


def _command_version(command: str) -> str | None:
    try:
        result = subprocess.run(
            [command, VERSION_ARGUMENTS.get(command, "--version")],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired, UnicodeError):
        return None
    if result.returncode != 0:
        return None
    output = (result.stdout or result.stderr).strip()
    if not output:
        return None
    return output.splitlines()[0][:VERSION_OUTPUT_LIMIT]


def _font_family_available(family: str) -> bool:
    try:
        result = subprocess.run(
            ["fc-match", "-f", "%{family}\n", family],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired, UnicodeError):
        return False
    return result.returncode == 0 and family.lower() in result.stdout.lower()


def _module_version(module_name: str) -> str | None:
    try:
        module = importlib.import_module(module_name)
    except Exception:
        return None
    return str(getattr(module, "__version__", "available"))


def _temporary_directory_check() -> tuple[bool, str]:
    temporary_root = Path(tempfile.gettempdir()).resolve()
    data_root = Path("/data").resolve()
    if data_root.exists() and (temporary_root == data_root or data_root in temporary_root.parents or temporary_root in data_root.parents):
        return False, f"temporary root overlaps /data: {temporary_root}"
    directory_path: Path | None = None
    try:
        with tempfile.TemporaryDirectory(prefix="cde-pdf-runtime-") as directory:
            directory_path = Path(directory)
            probe = Path(directory) / "probe"
            probe.write_text("runtime probe\n", encoding="utf-8")
            if probe.read_text(encoding="utf-8") != "runtime probe\n":
                return False, "temporary write/read probe failed"
            if probe.exists():
                probe.unlink()
    except OSError as exc:
        return False, f"temporary directory unavailable: {type(exc).__name__}"
    if directory_path is None or directory_path.exists():
        return False, "temporary directory cleanup failed"
    return True, f"{temporary_root} (ephemeral check completed)"


def collect_diagnostic() -> tuple[dict[str, Any], bool]:
    report: dict[str, Any] = {
        "python": {"executable": sys.executable, "version": sys.version.split()[0]},
        "commands": {},
        "fonts": {},
        "python_modules": {},
        "temporary_directory": {},
    }
    mandatory_ok = True
    for command in REQUIRED_COMMANDS + LIBREOFFICE_COMMANDS:
        path = shutil.which(command)
        available = path is not None
        report["commands"][command] = {"path": path, "version": _command_version(command) if available else None}
        mandatory_ok &= command in LIBREOFFICE_COMMANDS or (available and report["commands"][command]["version"] is not None)
    libreoffice_ready = any(
        report["commands"][command]["path"] is not None and report["commands"][command]["version"] is not None
        for command in LIBREOFFICE_COMMANDS
    )
    mandatory_ok &= libreoffice_ready
    for command in OPTIONAL_COMMANDS:
        path = shutil.which(command)
        report["commands"][command] = {"path": path, "version": _command_version(command) if path else None, "optional": True}
    for family in REQUIRED_FONTS:
        available = bool(shutil.which("fc-match")) and _font_family_available(family)
        report["fonts"][family] = available
        mandatory_ok &= available
    pypdf_version = _module_version("pypdf")
    report["python_modules"]["pypdf"] = {"importable": pypdf_version is not None, "version": pypdf_version}
    mandatory_ok &= pypdf_version == REQUIRED_PYPDF_VERSION
    temporary_ok, temporary_detail = _temporary_directory_check()
    report["temporary_directory"] = {"ok": temporary_ok, "detail": temporary_detail, "data_path_separate": not Path("/data").exists() or Path(tempfile.gettempdir()).resolve() != Path("/data").resolve()}
    mandatory_ok &= temporary_ok
    return report, mandatory_ok


def main() -> int:
    import json

    report, ok = collect_diagnostic()
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
