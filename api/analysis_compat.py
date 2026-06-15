from __future__ import annotations

import re
from typing import Any

from api.models import CasesRequest


def normalize_analysis_request(payload: Any) -> CasesRequest:
    if isinstance(payload, CasesRequest):
        return payload
    if not isinstance(payload, dict):
        raise ValueError("analysis_payload_invalid")

    if "cases" in payload:
        payload = _normalize_case_references(payload)
        request = CasesRequest.model_validate(payload)
        if not request.cases:
            raise ValueError("analysis_cases_empty")
        return request

    if _looks_like_single_case(payload):
        case = dict(payload)
        if not case.get("strike_reference") and case.get("reference"):
            case["strike_reference"] = case["reference"]
        case.pop("reference", None)
        return CasesRequest.model_validate({"cases": [case]})

    narrative = _first_nonblank(payload.get("case_text"), payload.get("source_narrative"))
    if not narrative:
        raise ValueError("analysis_text_required")

    supplied_reference = _first_nonblank(
        payload.get("strike_reference"),
        payload.get("reference"),
    )
    institution_type = _safe_institution_type(
        payload.get("institution_type")
        or _institution_type_from_reference(supplied_reference)
    )
    case = {
        "strike_reference": supplied_reference
        or f"Strike-{institution_type}-PASTE-JSON",
        "case_title": payload.get("case_title") or "Pasted JSON civic analysis",
        "civic_domain": payload.get("civic_domain") or institution_type,
        "decision_trigger": payload.get("decision_trigger") or narrative,
        "recall_question": payload.get("recall_question"),
        "case_description": narrative,
        "user_priority": payload.get("user_priority"),
        "desired_outcome": payload.get("desired_outcome"),
        "urgency": payload.get("urgency") or "medium",
        "institutions": payload.get("institutions") or [institution_type],
        "case_lifecycle": payload.get("case_lifecycle")
        or {
            "status": "active",
            "stalled": True,
            "days_open": 45,
            "current_stage": "awaiting_response",
            "recommended_mode": "hold_and_prepare",
            "resolution_status": "unresolved",
        },
        "rules_or_procedures": payload.get("rules_or_procedures") or [],
        "constraints": payload.get("constraints") or [],
        "actors": payload.get("actors") or [],
        "evidence_bundle": payload.get("evidence_bundle") or [],
        "deadlines": payload.get("deadlines") or [],
        "timeline": payload.get("timeline") or [],
        "escalation_paths": payload.get("escalation_paths") or [],
        "linked_cases": payload.get("linked_cases") or [],
        "structural_insight": payload.get("structural_insight"),
        "personal_positioning": payload.get("personal_positioning"),
        "decision_note": payload.get("decision_note"),
        "learning_capture": payload.get("learning_capture"),
    }
    return CasesRequest.model_validate({"cases": [case]})


def _first_nonblank(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _normalize_case_references(payload: dict[str, Any]) -> dict[str, Any]:
    cases = payload.get("cases")
    if not isinstance(cases, list):
        return payload

    normalized_payload = dict(payload)
    normalized_cases: list[Any] = []
    for case in cases:
        if isinstance(case, dict):
            normalized_case = dict(case)
            if not normalized_case.get("strike_reference") and normalized_case.get("reference"):
                normalized_case["strike_reference"] = normalized_case["reference"]
            normalized_case.pop("reference", None)
            normalized_cases.append(normalized_case)
        else:
            normalized_cases.append(case)
    normalized_payload["cases"] = normalized_cases
    return normalized_payload


def _safe_institution_type(value: Any) -> str:
    if isinstance(value, str):
        normalized = value.strip().upper()
        if re.fullmatch(r"[A-Z0-9]{2,6}", normalized):
            return normalized
    return "OT"


def _institution_type_from_reference(value: Any) -> str | None:
    if isinstance(value, str):
        match = re.match(r"^Strike-([A-Za-z0-9]{2,6})-", value.strip())
        if match:
            return match.group(1)
    return None


def _looks_like_single_case(payload: dict[str, Any]) -> bool:
    if not _first_nonblank(payload.get("strike_reference"), payload.get("reference")):
        return False
    if not isinstance(payload.get("case_title"), str) or not payload["case_title"].strip():
        return False
    return any(
        isinstance(payload.get(key), str) and payload[key].strip()
        for key in ("decision_trigger", "case_description", "case_text", "source_narrative")
    )
