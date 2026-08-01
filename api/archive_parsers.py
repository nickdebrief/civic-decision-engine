from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Protocol


class ArchiveParser(Protocol):
    """Source-neutral contract for governed mailbox archive adapters."""

    source_format: str

    def supports(self, file_path: Path) -> bool:
        ...

    def inspect(self, file_path: Path) -> dict[str, Any]:
        ...

    def project(self, file_path: Path) -> dict[str, Any]:
        ...

    def iter_attachments(self) -> Iterable[dict[str, Any]]:
        ...
