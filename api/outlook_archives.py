from __future__ import annotations

import importlib
import os
from pathlib import Path
from typing import Any, Protocol


OUTLOOK_ARCHIVE_PARSER_MODULE_ENV = "CDE_OUTLOOK_ARCHIVE_PARSER_MODULE"
OUTLOOK_ARCHIVE_PARSER_CLASS_ENV = "CDE_OUTLOOK_ARCHIVE_PARSER_CLASS"
OUTLOOK_ARCHIVE_PARSER_VERSION_ENV = "CDE_OUTLOOK_ARCHIVE_PARSER_VERSION"

OUTLOOK_ARCHIVE_BOUNDARY = (
    "Microsoft Outlook PST and OST archives are preserved as original bytes. "
    "CDE Platform Stage 39B records archive-level preservation, hash "
    "verification, job progress, and parser readiness only; it does not expose "
    "mailbox contents, extract messages, publish mailbox data, or promote "
    "contained items into separate governed records."
)


class OutlookArchiveParser(Protocol):
    """Contract for future PST/OST parser implementations."""

    def supports(self, file_path: Path) -> bool:
        ...

    def inspect(self, file_path: Path) -> dict[str, Any]:
        ...


def configured_outlook_archive_parser() -> OutlookArchiveParser | None:
    """Load a configured parser without making it mandatory for intake."""
    configured_module = os.getenv(OUTLOOK_ARCHIVE_PARSER_MODULE_ENV, "").strip()
    configured_class = os.getenv(OUTLOOK_ARCHIVE_PARSER_CLASS_ENV, "OutlookArchiveParser").strip()
    if not configured_module:
        return None
    module = importlib.import_module(configured_module)
    parser_factory = getattr(module, configured_class, None)
    if parser_factory is None and all(
        hasattr(module, attr) for attr in ("supports", "inspect")
    ):
        return module  # type: ignore[return-value]
    if parser_factory is None:
        raise RuntimeError("configured_outlook_archive_parser_missing")
    parser = parser_factory()
    if not all(hasattr(parser, attr) for attr in ("supports", "inspect")):
        raise RuntimeError("configured_outlook_archive_parser_invalid")
    return parser


def outlook_archive_type(document_type: str | None) -> str:
    normalized = str(document_type or "").strip().lower()
    if normalized == "pst":
        return "PST"
    if normalized == "ost":
        return "OST"
    return "Outlook Archive"


def outlook_archive_type_label(document_type: str | None) -> str:
    archive_type = outlook_archive_type(document_type)
    if archive_type == "PST":
        return "Microsoft Outlook Personal Storage (PST)"
    if archive_type == "OST":
        return "Microsoft Outlook Offline Storage (OST)"
    return "Microsoft Outlook Archive"


def outlook_archive_parser_status() -> dict[str, Any]:
    """Return bounded parser availability metadata without requiring a dependency."""
    configured_module = os.getenv(OUTLOOK_ARCHIVE_PARSER_MODULE_ENV, "").strip()
    configured_version = os.getenv(OUTLOOK_ARCHIVE_PARSER_VERSION_ENV, "").strip()
    if not configured_module:
        return {
            "parser_available": False,
            "parser_status": "parser_not_configured",
            "parser_status_message": "Parser not configured.",
            "parser_version": configured_version or None,
            "parser_module": None,
    }
    try:
        module = importlib.import_module(configured_module)
        configured_class = os.getenv(
            OUTLOOK_ARCHIVE_PARSER_CLASS_ENV,
            "OutlookArchiveParser",
        ).strip()
        parser_factory = getattr(module, configured_class, None)
        if parser_factory is None and not all(
            hasattr(module, attr) for attr in ("supports", "inspect")
        ):
            raise RuntimeError("configured_outlook_archive_parser_missing")
    except Exception:
        return {
            "parser_available": False,
            "parser_status": "parser_initialisation_failed",
            "parser_status_message": "Configured parser could not be initialised.",
            "parser_version": configured_version or None,
            "parser_module": configured_module,
        }
    return {
        "parser_available": True,
        "parser_status": "parser_available",
        "parser_status_message": "Parser configured.",
        "parser_version": configured_version or getattr(module, "__version__", None),
        "parser_module": configured_module,
    }


def build_outlook_archive_metadata(
    *,
    data: bytes,
    filename: str,
    document_type: str,
    content_type: str | None,
    uploaded_at: str,
    actor: str,
) -> dict[str, Any]:
    parser_status = outlook_archive_parser_status()
    return {
        "source_format": "outlook_archive",
        "archive_type": outlook_archive_type(document_type),
        "archive_type_label": outlook_archive_type_label(document_type),
        "original_filename": filename,
        "file_size_bytes": len(data),
        "declared_mime_type": str(content_type or "").split(";", 1)[0].strip() or None,
        "upload_timestamp": uploaded_at,
        "uploader": str(actor or "admin"),
        "parser_contract": "OutlookArchiveParser",
        "parser_available": parser_status["parser_available"],
        "parser_status": parser_status["parser_status"],
        "parser_status_message": parser_status["parser_status_message"],
        "parser_version": parser_status["parser_version"],
        "parser_module": parser_status["parser_module"],
        "mailbox_discovery_performed": False,
        "message_extraction_performed": False,
        "attachment_extraction_performed": False,
        "canonical_record_generation_performed": False,
        "governance_boundary": OUTLOOK_ARCHIVE_BOUNDARY,
    }


def outlook_archive_search_values(document: dict[str, Any]) -> list[Any]:
    metadata = document.get("outlook_archive_metadata")
    if not isinstance(metadata, dict):
        return []
    return [
        metadata.get("archive_type"),
        metadata.get("archive_type_label"),
        metadata.get("original_filename"),
        metadata.get("parser_status"),
        metadata.get("parser_status_message"),
        metadata.get("parser_version"),
    ]
