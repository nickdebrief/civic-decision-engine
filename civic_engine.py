#!/usr/bin/env python3

"""
Civic Decision Engine — Version 9
Behaviour Scoring & Lifecycle Intelligence

Version 9 introduces a behavioural analysis layer that evaluates
institutional response patterns within civic cases.

New capabilities:
- Institutional behaviour detection
- Behaviour scoring (posture, engagement, escalation)
- Behaviour index for escalation signalling
- Integrated lifecycle diagnostics

Copyright (c) 2026 Nick Moloney
Licensed under the MIT License
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from datetime import date
from jsonschema import Draft7Validator


SCHEMA_PATH = Path("schema/civic_case.schema.json")
SAMPLE_CASE_PATH = Path("examples/sample_case.json")


def load_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        raise FileNotFoundError(f"File not found: {path}")
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in {path}: {e}")


def print_case_summary(case: dict[str, Any]) -> None:
    print("\nCivic Case Loaded")
    print("──────────────────")

    institutions = case.get("institutions", [])
    first_institution = institutions[0] if institutions else "None recorded"

    print(f"Strike Reference : {case.get('strike_reference')}")
    print(f"Title            : {case.get('case_title')}")
    print(f"Domain           : {case.get('civic_domain')}")
    print(f"Institution      : {first_institution}")
    print(f"Urgency          : {case.get('urgency')}")
    lifecycle = case.get("case_lifecycle", {})

    print("\nCase Lifecycle")
    print("--------------")
    print(f"Stage            : {lifecycle.get('current_stage')}")
    print(f"Status           : {lifecycle.get('status')}")
    print(f"Stalled          : {lifecycle.get('stalled')}")
    print(f"Days open        : {lifecycle.get('days_open')}")
    print(f"Next decision    : {lifecycle.get('next_decision_point')}")
    print(f"Next deadline    : {lifecycle.get('next_deadline')}")
    print(f"Recommended mode : {lifecycle.get('recommended_mode')}")
    print("\nActors")
    print("------")
    for actor in case.get("actors", []):
        name = actor.get("name", "Unknown")
        role = actor.get("role_in_case", "unspecified role")
        print(f"- {name} — {role}")

    print("\nEvidence Bundle")
    print("---------------")
    print(f"Evidence items     : {len(case.get('evidence_bundle', []))}")
    print(f"Deadlines          : {len(case.get('deadlines', []))}")
    print(f"Timeline events    : {len(case.get('timeline', []))}")

    print("\nEscalation Paths")
    print("----------------")
    paths = case.get("escalation_paths", [])
    print(f"{len(paths)} path(s)")
    for path in paths:
        print(
            f"- {path.get('name')} "
            f"[jurisdiction: {path.get('jurisdiction_fit')}, "
            f"evidence: {path.get('evidence_readiness')}, "
            f"deadline: {path.get('deadline_pressure')}]"
        )

    print("\nLinked Cases")
    print("------------")
    linked = case.get("linked_cases", [])
    print(f"{len(linked)} linked case(s)")

    print("\nStructural Insight")
    print("------------------")
    print(case.get("structural_insight"))

    print("\nDecision Note")
    print("-------------")
    print(case.get("decision_note"))

    print("\nLearning Capture")
    print("----------------")
    print(case.get("learning_capture"))


def print_pattern_analysis(case: dict[str, Any]) -> None:
    print("\nPattern Analysis")
    print("----------------")

    linked_cases = case.get("linked_cases", [])
    institutions = case.get("institutions", [])
    escalation_paths = case.get("escalation_paths", [])

    if len(linked_cases) >= 2:
        print("Pattern signal      : Strong")
        print("Interpretation      : Multiple linked cases suggest a repeating institutional pattern.")
    elif len(linked_cases) == 1:
        print("Pattern signal      : Moderate")
        print("Interpretation      : One linked case suggests this may be more than an isolated event.")
    else:
        print("Pattern signal      : Low")
        print("Interpretation      : No linked cases recorded yet; may still be an isolated issue.")

    print(f"Institutions mapped : {len(institutions)}")
    print(f"Escalation paths    : {len(escalation_paths)}")

    strong_paths = []
    pressure_paths = []

    for path in escalation_paths:
        evidence = path.get("evidence_readiness")
        jurisdiction = path.get("jurisdiction_fit")
        deadline = path.get("deadline_pressure")

        if evidence == "high" and jurisdiction in {"yes", "partial"}:
            strong_paths.append(path.get("name"))

        if deadline == "high":
            pressure_paths.append(path.get("name"))

    print("\nEscalation Readiness")
    print("--------------------")
    if strong_paths:
        print("Most prepared paths :")
        for name in strong_paths:
            print(f"- {name}")
    else:
        print("Most prepared paths : None clearly ready yet")

    if pressure_paths:
        print("\nDeadline-sensitive paths :")
        for name in pressure_paths:
            print(f"- {name}")
    else:
        print("\nDeadline-sensitive paths : None flagged")

    print("\nCase Health")
    print("-----------")

    evidence_levels = [p.get("evidence_readiness") for p in escalation_paths]
    deadline_levels = [p.get("deadline_pressure") for p in escalation_paths]

    if "high" in evidence_levels:
        evidence_status = "HIGH"
    elif "medium" in evidence_levels:
        evidence_status = "MEDIUM"
    else:
        evidence_status = "LOW"

    if "high" in deadline_levels:
        deadline_status = "HIGH"
    elif "medium" in deadline_levels:
        deadline_status = "MEDIUM"
    else:
        deadline_status = "LOW"

    pattern_level = (
        "HIGH" if len(linked_cases) >= 2
        else "MODERATE" if len(linked_cases) == 1
        else "LOW"
    )

    print(f"Evidence strength   : {evidence_status}")
    print(f"Deadline pressure   : {deadline_status}")
    print(f"Pattern signal      : {pattern_level}")
    
def print_lifecycle_diagnostics(case: dict[str, Any]) -> None:
    print("\nLifecycle Diagnostics")
    print("---------------------")

    lifecycle = case.get("case_lifecycle", {})

    stage = lifecycle.get("current_stage")
    status = lifecycle.get("status")
    stalled = lifecycle.get("stalled")
    days_open = lifecycle.get("days_open", 0)
    next_deadline = lifecycle.get("next_deadline")
    recommended_mode = lifecycle.get("recommended_mode")

    days_remaining = None
    if next_deadline:
        deadline_date = date.fromisoformat(next_deadline)
        today = date.today()
        days_remaining = (deadline_date - today).days

    if stalled:
        stage_stability = "Unstable"
    elif status == "active":
        stage_stability = "OK"
    else:
        stage_stability = "Monitor"

    if days_remaining is not None:
        if days_remaining <= 3:
            deadline_proximity = "High"
        elif days_remaining <= 10:
            deadline_proximity = "Near"
        else:
            deadline_proximity = "Low"
    else:
        deadline_proximity = "Unknown"

    if stage == "awaiting_response":
        case_momentum = "Waiting on institution"
    elif stage == "escalation_ready":
        case_momentum = "Ready to escalate"
    elif stage == "external_review":
        case_momentum = "Under external review"
    elif stage == "resolved":
        case_momentum = "Closed"
    else:
        case_momentum = "In progress"

    stance_labels = {
        "observe": "Observe",
        "hold_and_prepare": "Hold and prepare",
        "escalate": "Escalate",
        "stabilise": "Stabilise",
        "close_out": "Close out",
    }

    print(f"Stage stability     : {stage_stability}")

    if days_remaining is not None:
        print(f"Deadline proximity  : {deadline_proximity} ({days_remaining} days remaining)")
    else:
        print(f"Deadline proximity  : {deadline_proximity}")

    print(f"Case momentum       : {case_momentum}")
    print(f"Recommended stance  : {stance_labels.get(recommended_mode, recommended_mode)}")
    print(f"Next deadline       : {next_deadline}")

def print_institution_behaviour(case: dict[str, Any]) -> None:
    print("\nInstitution Behaviour")
    print("---------------------")

    lifecycle = case.get("case_lifecycle", {})

    status = lifecycle.get("status")
    stalled = lifecycle.get("stalled")
    days_open = lifecycle.get("days_open", 0)
    stage = lifecycle.get("current_stage")
    recommended_mode = lifecycle.get("recommended_mode")

    behaviour = "Responsive"
    posture = "Neutral"
    engagement = "Normal"
    escalation_signal = "Low"

    if stalled or (stage == "awaiting_response" and days_open >= 30):
        behaviour = "Non-responsive"
        posture = "Withdrawn"
        engagement = "Very low"
        escalation_signal = "High"

    elif (
        status == "active"
        and stage == "awaiting_response"
        and recommended_mode == "hold_and_prepare"
        and days_open >= 10
    ):
        behaviour = "Procedural containment"
        posture = "Defensive"
        engagement = "Low"
        escalation_signal = "Increasing"

    elif (
        status == "active"
        and stage in {"internal_process", "awaiting_response"}
        and days_open >= 7
    ):
        behaviour = "Delayed response"
        posture = "Cautious"
        engagement = "Moderate"
        escalation_signal = "Watch"

    print(f"Behaviour pattern : {behaviour}")
    print(f"Institution posture: {posture}")
    print(f"Engagement level  : {engagement}")
    print(f"Escalation signal : {escalation_signal}")   

def print_behaviour_score(case: dict[str, Any]) -> None:
    print("\nInstitution Behaviour Score")
    print("---------------------------")

    lifecycle = case.get("case_lifecycle", {})

    status = lifecycle.get("status")
    stalled = lifecycle.get("stalled")
    days_open = lifecycle.get("days_open", 0)
    stage = lifecycle.get("current_stage")
    recommended_mode = lifecycle.get("recommended_mode")

    behaviour = "Responsive"
    posture = "Neutral"
    engagement = "Normal"
    escalation_signal = "Low"

    if stalled or (stage == "awaiting_response" and days_open >= 30):
        behaviour = "Non-responsive"
        posture = "Withdrawn"
        engagement = "Very low"
        escalation_signal = "High"

    elif (
        status == "active"
        and stage == "awaiting_response"
        and recommended_mode == "hold_and_prepare"
        and days_open >= 10
    ):
        behaviour = "Procedural containment"
        posture = "Defensive"
        engagement = "Low"
        escalation_signal = "Increasing"

    elif (
        status == "active"
        and stage in {"internal_process", "awaiting_response"}
        and days_open >= 7
    ):
        behaviour = "Delayed response"
        posture = "Cautious"
        engagement = "Moderate"
        escalation_signal = "Watch"

    posture_scores = {
        "Neutral": 1,
        "Cautious": 2,
        "Defensive": 3,
        "Withdrawn": 3,
    }

    engagement_scores = {
        "Normal": 1,
        "Moderate": 2,
        "Low": 3,
        "Very low": 3,
    }

    escalation_scores = {
        "Low": 1,
        "Watch": 2,
        "Increasing": 3,
        "High": 3,
    }

    posture_score = posture_scores.get(posture, 1)
    engagement_score = engagement_scores.get(engagement, 1)
    escalation_score = escalation_scores.get(escalation_signal, 1)

    behaviour_index = posture_score + engagement_score + escalation_score

    if behaviour_index >= 8:
        interpretation = "Strong institutional resistance or containment detected"
    elif behaviour_index >= 6:
        interpretation = "Elevated institutional friction detected"
    elif behaviour_index >= 4:
        interpretation = "Moderate behavioural caution detected"
    else:
        interpretation = "Low behavioural concern"

    print(f"Posture score     : {posture_score} / 3")
    print(f"Engagement score  : {engagement_score} / 3")
    print(f"Escalation score  : {escalation_score} / 3")
    print(f"Behaviour index   : {behaviour_index} / 9")
    print(f"Interpretation    : {interpretation}")       

def score_escalation_paths(case: dict[str, Any]) -> None:
    print("\nEscalation Ranking")
    print("------------------")

    escalation_paths = case.get("escalation_paths", [])

    if not escalation_paths:
        print("No escalation paths recorded.")
        return

    jurisdiction_scores = {"yes": 3, "partial": 2, "no": 0}
    evidence_scores = {"high": 3, "medium": 2, "low": 1}
    deadline_scores = {"high": 3, "medium": 2, "low": 1}
    risk_scores = {"low": 3, "medium": 2, "high": 1}

    ranked_paths = []

    for path in escalation_paths:
        score = 0
        score += jurisdiction_scores.get(path.get("jurisdiction_fit"), 0)
        score += evidence_scores.get(path.get("evidence_readiness"), 0)
        score += deadline_scores.get(path.get("deadline_pressure"), 0)
        score += risk_scores.get(path.get("risk_level"), 0)

        ranked_paths.append((path.get("name", "Unnamed path"), score))

    ranked_paths.sort(key=lambda x: x[1], reverse=True)

    for i, (name, score) in enumerate(ranked_paths, start=1):
        print(f"{i}. {name}   score: {score}")


def print_overall_view(case: dict[str, Any]) -> None:
    print("\nOverall View")
    print("------------")

    linked_cases = case.get("linked_cases", [])
    escalation_paths = case.get("escalation_paths", [])

    strong_paths = [
        p for p in escalation_paths
        if p.get("evidence_readiness") == "high"
        and p.get("jurisdiction_fit") in {"yes", "partial"}
    ]

    if linked_cases and strong_paths:
        print("This case shows pattern potential and has at least one reasonably prepared escalation route.")
    elif linked_cases:
        print("This case shows pattern potential, but escalation readiness may need strengthening.")
    elif strong_paths:
        print("This case does not yet show a strong repeat-pattern signal, but escalation routes are available.")
    else:
        print("This case needs more pattern evidence and stronger escalation preparation before major next steps.")


def validate_case(case_path: Path, schema_path: Path) -> bool:
    schema = load_json(schema_path)
    case_data = load_json(case_path)

    validator = Draft7Validator(schema)
    errors = sorted(validator.iter_errors(case_data), key=lambda e: list(e.path))

    if errors:
        print("\nValidation failed.\n")
        for i, error in enumerate(errors, start=1):
            location = " → ".join(str(p) for p in error.path) if error.path else "(root)"
            print(f"{i}. Location: {location}")
            print(f"   Message: {error.message}\n")
        return False

    print("\nValidation successful.")
    print(f"Case file '{case_path}' matches schema '{schema_path}'.\n")

    print_case_summary(case_data)

    print("\n══════════════════════════════")
    print("Civic Case Analysis")
    print("══════════════════════════════")

    print_pattern_analysis(case_data)
    print_lifecycle_diagnostics(case_data)
    print_institution_behaviour(case_data)
    print_behaviour_score(case_data)
    score_escalation_paths(case_data)
    print_overall_view(case_data)

    return True


def main() -> None:
    print("Civic Decision Engine — Version 9")
    print("1) Validate sample case")
    print("2) Validate a case file by path")

    choice = input("\nChoose 1 or 2: ").strip()

    if choice == "1":
        validate_case(SAMPLE_CASE_PATH, SCHEMA_PATH)
    elif choice == "2":
        case_input = input("Enter path to case JSON file: ").strip()
        validate_case(Path(case_input), SCHEMA_PATH)
    else:
        print("Invalid choice.")


if __name__ == "__main__":
    main()