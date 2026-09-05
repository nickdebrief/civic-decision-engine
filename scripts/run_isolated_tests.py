#!/usr/bin/env python3
"""Run repository tests behind a developer-database containment gate."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence


USAGE_STATUS = 64
CONTAINMENT_STATUS = 97
INFRASTRUCTURE_STATUS = 98
SUPPORTED_FRAMEWORKS = {"unittest", "pytest"}


@dataclass(frozen=True)
class FileIdentity:
    path: str
    exists: bool
    device: int | None = None
    inode: int | None = None
    size: int | None = None
    mtime_ns: int | None = None
    sha256: str | None = None


@dataclass(frozen=True)
class DatabaseSnapshot:
    database: FileIdentity
    wal: FileIdentity
    shm: FileIdentity


def repository_root() -> Path:
    return Path(__file__).resolve().parent.parent


def developer_database_path(repo_root: Path) -> Path:
    return (repo_root / "records.db").resolve()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_identity(path: Path) -> FileIdentity:
    resolved = path.resolve(strict=False)
    if not resolved.exists():
        return FileIdentity(path=str(resolved), exists=False)
    stat = resolved.stat()
    return FileIdentity(
        path=str(resolved),
        exists=True,
        device=stat.st_dev,
        inode=stat.st_ino,
        size=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
        sha256=_sha256(resolved),
    )


def snapshot_database(database: Path) -> DatabaseSnapshot:
    return DatabaseSnapshot(
        database=file_identity(database),
        wal=file_identity(database.with_name(database.name + "-wal")),
        shm=file_identity(database.with_name(database.name + "-shm")),
    )


def snapshot_changes(before: DatabaseSnapshot, after: DatabaseSnapshot) -> list[str]:
    changes: list[str] = []
    for field in ("database", "wal", "shm"):
        if getattr(before, field) != getattr(after, field):
            changes.append(field)
    return changes


def _no_open_handle(
    database: Path,
    *,
    run_process: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> bool:
    if not database.exists():
        return True
    lsof = shutil.which("lsof")
    if not lsof:
        raise RuntimeError("lsof_unavailable")
    result = run_process(
        [lsof, str(database)],
        shell=False,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 1 and not result.stdout.strip():
        return True
    if result.returncode == 0 and result.stdout.strip():
        return False
    raise RuntimeError("lsof_indeterminate")


def _validate_command(argv: Sequence[str]) -> tuple[str, list[str]]:
    if not argv:
        raise ValueError("test_framework_required")
    framework = argv[0]
    if framework not in SUPPORTED_FRAMEWORKS:
        raise ValueError("test_framework_unsupported")
    if any(not isinstance(value, str) or "\x00" in value for value in argv[1:]):
        raise ValueError("test_arguments_invalid")
    return framework, list(argv[1:])


def _prepare_environment(
    *,
    inherited: Mapping[str, str],
    temp_root: Path,
    developer_database: Path,
) -> dict[str, str]:
    isolated_tmp = (temp_root / "tmp").resolve()
    isolated_tmp.mkdir()
    isolated_db = (temp_root / "records.db").resolve()
    try:
        isolated_db.relative_to(temp_root.resolve())
        isolated_tmp.relative_to(temp_root.resolve())
    except ValueError as exc:
        raise RuntimeError("isolated_path_escape") from exc
    if isolated_db == developer_database or isolated_db.exists():
        raise RuntimeError("isolated_database_invalid")
    environment = dict(inherited)
    environment["RECORDS_DB_PATH"] = str(isolated_db)
    environment["TMPDIR"] = str(isolated_tmp)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return environment


def run_isolated_tests(
    argv: Sequence[str],
    *,
    repo_root: Path | None = None,
    inherited_environment: Mapping[str, str] | None = None,
    run_process: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    temp_dir_factory: Callable[[], str] | None = None,
    cleanup: Callable[[Path], None] | None = None,
    stdout=sys.stdout,
    stderr=sys.stderr,
) -> int:
    try:
        framework, test_args = _validate_command(argv)
    except ValueError as exc:
        print(str(exc), file=stderr)
        return USAGE_STATUS

    root = (repo_root or repository_root()).resolve()
    database = developer_database_path(root)
    cleanup_temp = cleanup or (lambda path: shutil.rmtree(path))
    make_temp = temp_dir_factory or (
        lambda: tempfile.mkdtemp(prefix="cde-isolated-tests-")
    )

    try:
        before = snapshot_database(database)
        if before.wal.exists or before.shm.exists:
            print("developer database sidecar present before test launch", file=stderr)
            return CONTAINMENT_STATUS
        if not _no_open_handle(database, run_process=run_process):
            print("developer database has an open handle before test launch", file=stderr)
            return CONTAINMENT_STATUS
    except RuntimeError as exc:
        print(f"developer database containment gate unavailable: {exc}", file=stderr)
        return INFRASTRUCTURE_STATUS

    temp_root = Path(make_temp()).resolve()
    keep_temp = True
    child_status = INFRASTRUCTURE_STATUS
    try:
        environment = _prepare_environment(
            inherited=inherited_environment or os.environ,
            temp_root=temp_root,
            developer_database=database,
        )
        command = [sys.executable, "-m", framework, *test_args]
        try:
            result = run_process(
                command,
                cwd=str(root),
                env=environment,
                shell=False,
                check=False,
            )
            child_status = int(result.returncode)
        except BaseException as exc:
            child_status = INFRASTRUCTURE_STATUS
            print(f"child test process failed before completion: {type(exc).__name__}", file=stderr)
        try:
            after = snapshot_database(database)
            changes = snapshot_changes(before, after)
            if changes:
                print(
                    "developer database containment failure: "
                    + ", ".join(changes)
                    + f"; retained launcher directory: {temp_root}",
                    file=stderr,
                )
                return CONTAINMENT_STATUS
            if after.wal.exists or after.shm.exists:
                print(
                    f"developer database sidecar appeared; retained launcher directory: {temp_root}",
                    file=stderr,
                )
                return CONTAINMENT_STATUS
            if not _no_open_handle(database, run_process=run_process):
                print(
                    f"developer database has an open handle after child exit; retained launcher directory: {temp_root}",
                    file=stderr,
                )
                return CONTAINMENT_STATUS
        except RuntimeError as exc:
            print(
                f"developer database containment gate unavailable after child exit: {exc}; "
                f"retained launcher directory: {temp_root}",
                file=stderr,
            )
            return INFRASTRUCTURE_STATUS
        keep_temp = False
        return child_status
    finally:
        if keep_temp:
            print(f"launcher-owned temporary directory retained: {temp_root}", file=stderr)
        else:
            cleanup_temp(temp_root)


def main(argv: Sequence[str] | None = None) -> int:
    return run_isolated_tests(sys.argv[1:] if argv is None else argv)


if __name__ == "__main__":
    raise SystemExit(main())
