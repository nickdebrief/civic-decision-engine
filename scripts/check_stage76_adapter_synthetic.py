#!/usr/bin/env python3
"""Run the governed Stage 76 adapter against an in-memory synthetic report."""

from __future__ import annotations

import hashlib
import builtins
import html
import json
import re
import signal
import socket
import sys
import tempfile
import time
import zipfile
from contextlib import contextmanager
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterator


CHECK_TIMEOUT_SECONDS = 220
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_FORMATS = ("docx", "html", "pdf")
PRIVATE_TOKENS = ("/tmp", "/private/tmp", "/app", "/data", "secret", "password", "private_canary")
MARKERS = (
    "STAGE76_ADAPTER_TITLE",
    "STAGE76_ADAPTER_PURPOSE",
    "STAGE76_ORIGINAL_WORDING",
    "STAGE76_FAITHFUL_PARAPHRASE",
    "STAGE76_ADMINISTRATIVE_SUMMARY",
    "STAGE76_ATTRIBUTION",
    "STAGE76_INCLUSION_RATIONALE",
    "STAGE76_QUALIFICATION",
    "STAGE76_LIMITATION",
    "STAGE76_REDACTION_NOTICE",
)


class AdapterGateError(RuntimeError):
    """A stable, safe diagnostic for a failed adapter gate."""


ADAPTER_CLEANUP_STATUS = "failed"


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(specification: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical(specification).encode("utf-8")).hexdigest()


def _synthetic_specification() -> dict[str, Any]:
    source = {"object_kind": "synthetic_test", "object_id": "STAGE76_SYNTHETIC_SOURCE"}
    blocks = [
        ("verbatim_source", "STAGE76_ORIGINAL_WORDING"),
        ("faithful_paraphrase", "STAGE76_FAITHFUL_PARAPHRASE"),
        ("administrative_summary", "STAGE76_ADMINISTRATIVE_SUMMARY"),
        ("qualification", "STAGE76_QUALIFICATION"),
        ("limitation", "STAGE76_LIMITATION"),
        ("redaction_notice", "STAGE76_REDACTION_NOTICE"),
    ]
    return {
        "specification_schema_version": "stage75.report_specification.v1",
        "report_type": "canonical_record_report",
        "title": "STAGE76_ADAPTER_TITLE",
        "purpose": "STAGE76_ADAPTER_PURPOSE",
        "intended_audience": "STAGE76_ADAPTER_AUDIENCE",
        "distribution_class": "internal_working",
        "primary_record": {
            "reference": "STAGE76_SYNTHETIC_RECORD",
            "title": "STAGE76_SYNTHETIC_RECORD_TITLE",
            "description": "STAGE76_SYNTHETIC_RECORD_DESCRIPTION",
            "status": "recorded",
        },
        "selected_documents": [],
        "selected_associations": [],
        "sections": [
            {
                "order": 0,
                "title": "STAGE76_ADAPTER_SECTION",
                "blocks": [
                    {
                        "order": index,
                        "content_type": content_type,
                        "text": text,
                        "source_identity": source,
                        "attribution": "STAGE76_ATTRIBUTION",
                        "inclusion_rationale": "STAGE76_INCLUSION_RATIONALE",
                    }
                    for index, (content_type, text) in enumerate(blocks)
                ],
            }
        ],
        "exclusions": [],
        "qualifications": ["STAGE76_QUALIFICATION"],
        "requested_formats": list(EXPECTED_FORMATS),
        "publication_engine_version": "2.0.0",
        "rendering_profile": "internal",
        "template_version": "cde-internal-v1",
    }


def _confined_temporary_directory() -> tuple[tempfile.TemporaryDirectory[str], Path]:
    canonical_root = Path(tempfile.gettempdir()).resolve()
    holder = tempfile.TemporaryDirectory(prefix="stage76-adapter-gate-")
    logical = Path(holder.name)
    resolved = logical.resolve()
    try:
        if logical.is_symlink() or resolved.parent != canonical_root:
            raise AdapterGateError("temporary_directory_not_confined")
        if resolved in {Path("/"), canonical_root, Path.home().resolve(), Path.cwd().resolve()}:
            raise AdapterGateError("temporary_directory_unsafe")
        if any(resolved.iterdir()):
            raise AdapterGateError("temporary_directory_not_empty")
        return holder, resolved
    except Exception:
        holder.cleanup()
        raise


@contextmanager
def _prohibit_external_access() -> Iterator[None]:
    """Fail immediately if the synthetic gate attempts persistence or network access."""
    import sqlite3
    import urllib.request

    original_connect = sqlite3.connect
    original_socket = socket.socket
    original_create_connection = socket.create_connection
    original_urlopen = urllib.request.urlopen
    original_import = builtins.__import__

    def forbidden(*_args: Any, **_kwargs: Any) -> None:
        raise AdapterGateError("prohibited_external_access")

    def guarded_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "api.routes" or name.startswith("api.routes."):
            raise AdapterGateError("prohibited_route_import")
        return original_import(name, *args, **kwargs)

    sqlite3.connect = forbidden  # type: ignore[assignment]
    socket.socket = forbidden  # type: ignore[assignment]
    socket.create_connection = forbidden  # type: ignore[assignment]
    urllib.request.urlopen = forbidden  # type: ignore[assignment]
    builtins.__import__ = guarded_import
    try:
        yield
    finally:
        sqlite3.connect = original_connect  # type: ignore[assignment]
        socket.socket = original_socket  # type: ignore[assignment]
        socket.create_connection = original_create_connection  # type: ignore[assignment]
        urllib.request.urlopen = original_urlopen  # type: ignore[assignment]
        builtins.__import__ = original_import


def _read_docx_text(path: Path) -> str:
    with zipfile.ZipFile(path) as package:
        xml = package.read("word/document.xml").decode("utf-8", errors="strict")
    values = []
    for value in re.findall(r"<w:t(?: [^>]*)?>(.*?)</w:t>", xml, flags=re.DOTALL):
        values.append(html.unescape(value))
    return " ".join(values)


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _read_html_text(path: Path) -> str:
    parser = _TextParser()
    parser.feed(path.read_text(encoding="utf-8"))
    return " ".join(parser.parts)


def _assert_markers(text: str) -> None:
    positions: list[int] = []
    for marker in MARKERS:
        if text.count(marker) != 1:
            raise AdapterGateError("equivalence_failed")
        positions.append(text.index(marker))
    if positions != sorted(positions):
        raise AdapterGateError("equivalence_failed")


def _validate_specification(specification: dict[str, Any]) -> None:
    required = {
        "specification_schema_version", "report_type", "title", "purpose",
        "intended_audience", "distribution_class", "primary_record",
        "selected_documents", "selected_associations", "sections", "exclusions",
        "qualifications", "requested_formats", "publication_engine_version",
        "rendering_profile", "template_version",
    }
    if set(specification) != required:
        raise AdapterGateError("synthetic_specification_invalid")
    if specification["report_type"] != "canonical_record_report" or specification["publication_engine_version"] != "2.0.0":
        raise AdapterGateError("synthetic_specification_invalid")
    if specification["requested_formats"] != list(EXPECTED_FORMATS):
        raise AdapterGateError("synthetic_specification_invalid")
    sections = specification["sections"]
    if not isinstance(sections, list) or len(sections) != 1 or sections[0].get("order") != 0:
        raise AdapterGateError("synthetic_specification_invalid")
    if [block.get("text") for block in sections[0].get("blocks", [])] != list(MARKERS[2:4]) + [MARKERS[4], MARKERS[7], MARKERS[8], MARKERS[9]]:
        raise AdapterGateError("synthetic_specification_invalid")


def _validate_result(result: dict[str, Any], specification: dict[str, Any], digest: str, root: Path) -> None:
    if not isinstance(result, dict):
        raise AdapterGateError("adapter_return_contract_invalid")
    if result.get("specification_digest") != digest:
        raise AdapterGateError("specification_digest_failed")
    artifacts = result.get("artifacts")
    if not isinstance(artifacts, list) or any(not isinstance(item, dict) for item in artifacts):
        raise AdapterGateError("adapter_return_contract_invalid")
    if {item.get("format") for item in artifacts} != set(EXPECTED_FORMATS) or len(artifacts) != 3:
        raise AdapterGateError("missing_artifact_descriptors")
    for item in artifacts:
        try:
            path = Path(str(item.get("path", "")))
            resolved = path.resolve()
            regular = path.is_file() and path.stat().st_size > 0
        except (OSError, TypeError, ValueError):
            raise AdapterGateError("artifact_path_invalid") from None
        if path.is_symlink() or resolved.parent != root or not regular:
            raise AdapterGateError("artifact_path_invalid")
        try:
            actual_digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except (OSError, TypeError, ValueError):
            raise AdapterGateError("artifact_digest_failed") from None
        if actual_digest != item.get("sha256"):
            raise AdapterGateError("artifact_digest_failed")
        if path.stat().st_size != item.get("size_bytes"):
            raise AdapterGateError("adapter_return_contract_invalid")
    pdf_diagnostics = [item for item in result.get("diagnostics", []) if item.get("format") == "pdf"]
    if len(pdf_diagnostics) != 1:
        raise AdapterGateError("pdf_diagnostics_invalid")
    diagnostics = pdf_diagnostics[0]
    for key in ("libreoffice_version", "pdfinfo_version", "pypdf_version", "extraction_backend", "page_count", "size_bytes"):
        if not diagnostics.get(key):
            raise AdapterGateError("pdf_diagnostics_invalid")
    if diagnostics.get("pypdf_version") != "5.9.0" or diagnostics.get("ordered_content") != "ok" or diagnostics.get("metadata_attachments_annotations") != "ok":
        raise AdapterGateError("pdf_diagnostics_invalid")
    safe_result = {key: value for key, value in result.items() if key != "artifacts"}
    safe_diagnostics = [{key: value for key, value in item.items() if key not in {"path", "stdout", "stderr"}} for item in result.get("diagnostics", [])]
    safe_result["diagnostics"] = safe_diagnostics
    if any(token in _canonical(safe_result).lower() for token in PRIVATE_TOKENS):
        raise AdapterGateError("private_canary_detected")
    by_format = {item["format"]: Path(item["path"]) for item in artifacts}
    _assert_markers(_read_docx_text(by_format["docx"]))
    _assert_markers(_read_html_text(by_format["html"]))
    if _digest(specification) != digest:
        raise AdapterGateError("specification_mutated")


def run_check() -> None:
    global ADAPTER_CLEANUP_STATUS
    ADAPTER_CLEANUP_STATUS = "failed"
    if not REPOSITORY_ROOT.is_dir() or not (REPOSITORY_ROOT / "api").is_dir() or not (REPOSITORY_ROOT / "scripts").is_dir():
        raise AdapterGateError("repository_root_invalid")
    try:
        specification = _synthetic_specification()
        _validate_specification(specification)
    except AdapterGateError:
        raise
    except Exception:
        raise AdapterGateError("synthetic_specification_failed") from None
    before = _canonical(specification)
    try:
        digest = _digest(specification)
    except Exception:
        raise AdapterGateError("specification_digest_failed") from None
    holder, root = _confined_temporary_directory()
    deadline = time.monotonic() + CHECK_TIMEOUT_SECONDS
    primary_exception: BaseException | None = None
    try:
        if time.monotonic() >= deadline:
            raise AdapterGateError("adapter_gate_timeout")
        with _prohibit_external_access():
            if str(REPOSITORY_ROOT) not in sys.path:
                sys.path.insert(0, str(REPOSITORY_ROOT))
            try:
                from api.report_rendering import AdapterFailure, render_frozen_report
            except Exception:
                raise AdapterGateError("adapter_import_failed") from None

            try:
                result = render_frozen_report(specification, digest, root)
            except AdapterFailure as exc:
                detail = ""
                if exc.diagnostic:
                    if "failure_field" in exc.diagnostic:
                        detail = f":{exc.diagnostic['failure_field']}:{exc.diagnostic['failure_reason']}"
                    else:
                        detail = (
                            f":{exc.diagnostic['failure_location']}:{exc.diagnostic['failure_reason']}"
                            f":{exc.diagnostic['failure_step']}:{exc.diagnostic['failure_structure']}"
                            f":{exc.diagnostic['failure_operand']}:{exc.diagnostic['failure_operand_kind']}"
                        )
                raise AdapterGateError(f"{exc.phase}:{exc.code}:{exc.cleanup}{detail}") from None
            except TimeoutError:
                raise AdapterGateError("adapter_invocation_failed") from None
            except ValueError:
                raise AdapterGateError("adapter_reported_failure") from None
            except OSError:
                raise AdapterGateError("adapter_invocation_failed") from None
            except AdapterGateError:
                raise
            except Exception:
                raise AdapterGateError("unexpected_adapter_error") from None
        if _canonical(specification) != before:
            raise AdapterGateError("specification_mutated")
        if time.monotonic() > deadline:
            raise AdapterGateError("adapter_gate_timeout")
        try:
            _validate_result(result, specification, digest, root)
        except AdapterGateError:
            raise
        except (KeyError, TypeError, ValueError, OSError):
            raise AdapterGateError("adapter_return_contract_invalid") from None
        except Exception:
            raise AdapterGateError("unexpected_adapter_error") from None
    except BaseException as exc:
        primary_exception = exc

    cleanup_failed = False
    try:
        try:
            holder.cleanup()
        except Exception:
            cleanup_failed = True
        if root.exists():
            cleanup_failed = True
    except BaseException:
        cleanup_failed = True

    if cleanup_failed:
        ADAPTER_CLEANUP_STATUS = "failed"
        if primary_exception is None:
            raise AdapterGateError("cleanup_failed") from None
    else:
        ADAPTER_CLEANUP_STATUS = "passed"
    if primary_exception is not None:
        raise primary_exception


def _timeout_handler(_signum: int, _frame: object) -> None:
    raise AdapterGateError("adapter_gate_timeout")


def main() -> int:
    previous = signal.signal(signal.SIGALRM, _timeout_handler)
    signal.setitimer(signal.ITIMER_REAL, CHECK_TIMEOUT_SECONDS)
    try:
        run_check()
        print("stage76_adapter_gate=passed")
        return 0
    except AdapterGateError as exc:
        parts = str(exc).split(":")
        if len(parts) >= 3:
            if len(parts) in {5, 7, 9}:
                label = "location" if parts[3] in {"catalog_open_action", "catalog_additional_actions", "page_additional_actions", "annotation_action", "outline_action"} else "field"
                detail = f" {label}={parts[3]} reason={parts[4]}"
                if len(parts) == 7:
                    detail += f" step={parts[5]} structure={parts[6]}"
                if len(parts) == 9:
                    detail += f" step={parts[5]} structure={parts[6]} operand={parts[7]} operand_kind={parts[8]}"
            else:
                detail = ""
            print(f"stage76_adapter_gate=failed phase={parts[0]} code={parts[1]}{detail}", file=sys.stderr)
        else:
            print(f"stage76_adapter_gate=failed code={parts[0]}", file=sys.stderr)
        return 1
    except Exception:
        print("stage76_adapter_gate=failed code=unexpected_failure", file=sys.stderr)
        return 1
    finally:
        print(f"stage76_adapter_gate_cleanup={ADAPTER_CLEANUP_STATUS}", file=sys.stderr)
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


if __name__ == "__main__":
    raise SystemExit(main())
