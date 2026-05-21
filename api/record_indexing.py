from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any


INDEXED_RECORD_FIELDS = (
    "reference",
    "generated_at",
    "finding",
    "trajectory",
    "conditions",
    "system_state",
    "generated_by",
)


def _value(record: Mapping[str, Any], field: str, default: Any = "") -> Any:
    try:
        value = record[field]
    except (KeyError, IndexError):
        value = default
    return default if value is None else value


def parse_conditions(record: Mapping[str, Any]) -> list[str]:
    raw_conditions = _value(record, "conditions_json", "[]")
    if isinstance(raw_conditions, list):
        return [str(item) for item in raw_conditions if item]

    try:
        parsed = json.loads(raw_conditions or "[]")
    except (TypeError, json.JSONDecodeError):
        return []

    if not isinstance(parsed, list):
        return []

    return [str(item) for item in parsed if item]


def build_indexed_fields(record: Mapping[str, Any]) -> dict[str, Any]:
    """Return canonical public fields used for archive search indexing."""
    conditions = parse_conditions(record)
    return {
        "reference": str(_value(record, "reference")),
        "generated_at": str(_value(record, "generated_at")),
        "finding": str(_value(record, "finding")),
        "trajectory": str(_value(record, "trajectory")),
        "conditions": conditions,
        "system_state": str(_value(record, "system_state")),
        "generated_by": str(_value(record, "generated_by", "Civic Decision Engine")),
    }


def build_indexable_text(record: Mapping[str, Any]) -> str:
    fields = build_indexed_fields(record)
    parts: list[str] = []
    for field in INDEXED_RECORD_FIELDS:
        value = fields[field]
        if isinstance(value, list):
            parts.extend(str(item) for item in value if item)
        elif value:
            parts.append(str(value))
    return "\n".join(parts)


def indexed_fields_hash(record: Mapping[str, Any]) -> str:
    fields = build_indexed_fields(record)
    payload = json.dumps(fields, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def indexed_fields_json(record: Mapping[str, Any]) -> str:
    fields = build_indexed_fields(record)
    return json.dumps(fields, separators=(",", ":"), sort_keys=True)


def build_snippet(record: Mapping[str, Any], query: str, length: int = 220) -> str:
    text = build_indexable_text(record).replace("\n", " ").strip()
    if not text:
        return ""

    normalized_text = text.lower()
    normalized_query = query.lower().strip()
    start = normalized_text.find(normalized_query) if normalized_query else -1

    if start < 0:
        return text[:length].strip()

    window_start = max(0, start - 60)
    window_end = min(len(text), start + len(query) + 120)
    snippet = text[window_start:window_end].strip()

    if window_start > 0:
        snippet = "..." + snippet
    if window_end < len(text):
        snippet = snippet + "..."

    return snippet[: length + 6].strip()
