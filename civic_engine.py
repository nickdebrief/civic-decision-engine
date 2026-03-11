#!/usr/bin/env python3
"""
Civic Decision Engine — Version 9
Schema validation + structured case loading
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

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

    print("\nOverall View")
    print("------------")
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