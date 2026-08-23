"""Validate durable governed-report storage without opening application data."""

from __future__ import annotations

import argparse
import os
import stat
import sys
from pathlib import Path
from typing import Mapping


MODE_DURABLE = "durable"
DATABASE_VARIABLE = "RECORDS_DB_PATH"
ARTIFACT_VARIABLE = "CDE_REPORT_ARTIFACT_ROOT"
DEFAULT_DURABLE_ROOT = Path("/data")
DEFAULT_DATABASE_PATH = Path("/data/records.db")
DEFAULT_ARTIFACT_ROOT = Path("/data/cde-governed-reports")

FAILURE_CODES = frozenset(
    {
        "database_variable_missing",
        "artifact_variable_missing",
        "blank_path",
        "relative_path",
        "outside_durable_root",
        "temporary_path",
        "traversal",
        "overlap",
        "symlink_component",
        "durable_root_missing",
        "durable_root_not_directory",
        "durable_root_not_writable",
        "database_path_invalid",
        "artifact_root_invalid",
        "metadata_inspection_failure",
        "unexpected_diagnostic_failure",
    }
)


class StorageValidationError(ValueError):
    def __init__(self, code: str):
        self.code = code if code in FAILURE_CODES else "unexpected_diagnostic_failure"
        super().__init__(self.code)


def _path_value(environ: Mapping[str, str], variable: str) -> str:
    value = environ.get(variable)
    if value is None:
        code = "database_variable_missing" if variable == DATABASE_VARIABLE else "artifact_variable_missing"
        raise StorageValidationError(code)
    if not value.strip():
        raise StorageValidationError("blank_path")
    return value


def _validate_path_shape(value: str, durable_root: Path) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise StorageValidationError("relative_path")
    if any(part in {".", ".."} for part in path.parts):
        raise StorageValidationError("traversal")
    if str(path) == "/tmp" or str(path).startswith("/tmp/"):
        raise StorageValidationError("temporary_path")
    try:
        path.relative_to(durable_root)
    except ValueError:
        raise StorageValidationError("outside_durable_root") from None
    return path


def _lstat(path: Path) -> os.stat_result:
    try:
        return path.lstat()
    except FileNotFoundError:
        raise StorageValidationError("metadata_inspection_failure") from None
    except OSError:
        raise StorageValidationError("metadata_inspection_failure") from None


def _reject_symlink_components(path: Path) -> None:
    current = Path(path.anchor)
    for component in path.parts[1:]:
        current /= component
        try:
            if current.is_symlink():
                raise StorageValidationError("symlink_component")
        except OSError:
            raise StorageValidationError("metadata_inspection_failure") from None


def _validate_durable_root(durable_root: Path) -> None:
    try:
        root_stat = _lstat(durable_root)
    except StorageValidationError:
        raise StorageValidationError("durable_root_missing") from None
    if stat.S_ISLNK(root_stat.st_mode):
        raise StorageValidationError("symlink_component")
    if not stat.S_ISDIR(root_stat.st_mode):
        raise StorageValidationError("durable_root_not_directory")
    try:
        if not os.access(durable_root, os.W_OK | os.X_OK):
            raise StorageValidationError("durable_root_not_writable")
    except OSError:
        raise StorageValidationError("metadata_inspection_failure") from None


def _validate_existing_database(path: Path) -> None:
    metadata = _lstat(path)
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise StorageValidationError("database_path_invalid")


def _validate_artifact_root(path: Path, durable_root: Path) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        # Stage 75 creates this exact leaf during the first deliberate
        # generation. The durable mount must already exist; nested missing
        # structure remains unsafe.
        if path.parent == durable_root and path.name == DEFAULT_ARTIFACT_ROOT.name:
            return
        raise StorageValidationError("artifact_root_invalid") from None
    except OSError:
        raise StorageValidationError("metadata_inspection_failure") from None
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise StorageValidationError("artifact_root_invalid")


def validate_storage(
    environ: Mapping[str, str] | None = None,
    *,
    mode: str = MODE_DURABLE,
    durable_root: Path = DEFAULT_DURABLE_ROOT,
    expected_database_path: Path = DEFAULT_DATABASE_PATH,
    expected_artifact_root: Path = DEFAULT_ARTIFACT_ROOT,
) -> None:
    if mode != MODE_DURABLE:
        raise StorageValidationError("unexpected_diagnostic_failure")
    environment = os.environ if environ is None else environ
    _validate_durable_root(durable_root)
    database_value = _path_value(environment, DATABASE_VARIABLE)
    artifact_value = _path_value(environment, ARTIFACT_VARIABLE)
    database_path = _validate_path_shape(database_value, durable_root)
    artifact_path = _validate_path_shape(artifact_value, durable_root)
    if database_path == artifact_path:
        raise StorageValidationError("overlap")
    try:
        if database_path.is_relative_to(artifact_path) or artifact_path.is_relative_to(database_path):
            raise StorageValidationError("overlap")
    except AttributeError:
        if str(database_path).startswith(str(artifact_path) + os.sep) or str(artifact_path).startswith(str(database_path) + os.sep):
            raise StorageValidationError("overlap")
    if database_value != str(expected_database_path) or artifact_value != str(expected_artifact_root):
        raise StorageValidationError("outside_durable_root")
    _reject_symlink_components(database_path)
    _reject_symlink_components(artifact_path)
    _validate_existing_database(database_path)
    _validate_artifact_root(artifact_path, durable_root)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=(MODE_DURABLE,), default=MODE_DURABLE)
    args = parser.parse_args(argv)
    try:
        validate_storage(mode=args.mode)
    except StorageValidationError as error:
        print(f"stage77_storage_prerequisite=failed code={error.code}")
        return 1
    except Exception:
        print("stage77_storage_prerequisite=failed code=unexpected_diagnostic_failure")
        return 1
    print("stage77_storage_prerequisite=passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
