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
        print(f"- {actor.get('role_in_case')} : {actor.get('name')}")

    print("\nEvidence Bundle")
    print("---------------")
    print(f"{len(case.get('evidence_bundle', []))} item(s)")

    print("\nDeadlines")
    print("---------")
    print(f"{len(case.get('deadlines', []))} deadline(s)")

    print("\nTimeline")
    print("--------")
    print(f"{len(case.get('timeline', []))} event(s)")

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