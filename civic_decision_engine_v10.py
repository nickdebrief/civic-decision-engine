#!/usr/bin/env python3
"""
Civic Decision Engine
Version: 10
Author: Nick Moloney
Build: 2026-03-15
License: MIT
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, List

from jsonschema import Draft7Validator

SYSTEM_SRC_DIR = Path(__file__).resolve().parent / "examples" / "src"
if str(SYSTEM_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SYSTEM_SRC_DIR))

from system_analysis import main as system_analysis_main

# ============================================================
# Configuration
# ============================================================

SCHEMA_PATH = Path("schema/civic_case.schema.json")
SAMPLE_CASE_PATH = Path("examples/sample_case.json")

EXAMPLE_CASES = [
    Path("examples/civic_case_001.json"),
    Path("examples/civic_case_003.json"),
    Path("examples/civic_case_002.json"),
]

# ============================================================
# JSON Utilities
# ============================================================


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)

# ============================================================
# Behaviour Extraction (Core V10 Layer)
# ============================================================


def extract_behaviour_summary(case: dict[str, Any]) -> dict[str, Any]:
    lifecycle = case.get("case_lifecycle", {})

    status = lifecycle.get("status")
    stalled = lifecycle.get("stalled")
    days_open = lifecycle.get("days_open", 0)
    stage = lifecycle.get("current_stage")
    mode = lifecycle.get("recommended_mode")

    # Behaviour classification
    if stalled or (stage == "awaiting_response" and days_open >= 30):
        posture = "Withdrawn"
        engagement = "Very low"
        escalation = "High"
        label = "Resistance"

    elif status == "active" and stage == "awaiting_response" and mode == "hold_and_prepare" and days_open >= 10:
        posture = "Defensive"
        engagement = "Low"
        escalation = "Increasing"
        label = "Partial engagement"

    elif status == "active" and days_open >= 7:
        posture = "Cautious"
        engagement = "Moderate"
        escalation = "Watch"
        label = "Delayed response"

    else:
        posture = "Neutral"
        engagement = "Normal"
        escalation = "Low"
        label = "Response"

    posture_scores = {
        "Neutral": 1,
        "Cautious": 2,
        "Defensive": 3,
        "Withdrawn": 3}
    engagement_scores = {"Normal": 1, "Moderate": 2, "Low": 3, "Very low": 3}
    escalation_scores = {"Low": 1, "Watch": 2, "Increasing": 3, "High": 3}

    index = (
        posture_scores[posture]
        + engagement_scores[engagement]
        + escalation_scores[escalation]
    )

    return {
        "case": case.get("strike_reference"),
        "label": label,
        "index": index,
        "posture": posture,
        "engagement": engagement,
        "escalation": escalation,
    }


def format_civic_result(case: dict[str, Any]) -> dict[str, Any]:
    summary = extract_behaviour_summary(case)

    return {
        "system_reference": case.get("strike_reference"),
        "title": case.get("case_title"),
        "domain": "civic_case_analysis",
        "declared_purpose": (
            case.get("case_description")
            or case.get("decision_trigger")
            or case.get("recall_question")
        ),
        "signals": {
            "posture": summary["posture"],
            "engagement": summary["engagement"],
            "escalation": summary["escalation"],
            "behaviour_index": summary["index"],
        },
        "assessment": {
            "label": summary["label"],
            "interpretation": (
                f"Institutional behaviour classified as {summary['label']} "
                f"with posture {summary['posture']}."
            ),
        },
    }


def build_civic_run_metadata(
        input_path: Path | None, case_count: int) -> dict[str, Any]:
    now = datetime.now(timezone.utc)

    return {
        "run_id": f"civic-analysis-{now.strftime('%Y-%m-%d-%H%M%S')}",
        "generated_at": now.isoformat(),
        "mode": "civic_analysis",
        "input_path": str(input_path) if input_path else None,
        "schema_path": str(SCHEMA_PATH),
        "batch": False,
        "validation_enabled": True,
        "computed_signals": True,
        "computed_assessment": True,
        "case_count": case_count,
    }


def export_json_output(output: dict[str, Any], path: str) -> None:
    export_path = Path(path)
    export_path.parent.mkdir(parents=True, exist_ok=True)
    export_path.write_text(json.dumps(output, indent=2))
    print(f"\nExported results -> {export_path}")

# ============================================================
# Adaptation Layer (NEW IN V10)
# ============================================================


def print_adaptation_analysis(cases: List[dict[str, Any]]) -> None:
    print("\n══════════════════════════════")
    print("Adaptation Analysis (V10)")
    print("══════════════════════════════")

    summaries = [extract_behaviour_summary(c) for c in cases]

    labels = [s["label"] for s in summaries]
    indices = [s["index"] for s in summaries]

    print("Case sequence       :", " → ".join([s["case"] for s in summaries]))
    print("Behaviour indices   :", " → ".join(map(str, indices)))
    print("Progression         :", " → ".join(labels))

    if indices == sorted(indices):
        trajectory = "Deteriorating"
    elif indices == sorted(indices, reverse=True):
        trajectory = "Improving"
    else:
        trajectory = "Mixed"

    print("Trajectory          :", trajectory)

    print("\nInterpretation")
    print("--------------")

    if trajectory == "Deteriorating":
        print(
            "Behaviour shows increasing institutional resistance or containment over time.")
    elif trajectory == "Improving":
        print("Behaviour shows improving engagement and resolution trajectory.")
    else:
        print("Behaviour is mixed or transitional across cases.")

# ============================================================
# Audit Logs (Clean Separation)
# ============================================================


def write_case_snapshot(case: dict[str, Any]) -> None:
    path = Path("audit_logs/case_analysis_log.json")
    path.parent.mkdir(exist_ok=True)

    entry = {
        "timestamp": date.today().isoformat(),
        "case": case.get("strike_reference"),
        "title": case.get("case_title"),
    }

    data = []
    if path.exists():
        data = json.loads(path.read_text())

    data.append(entry)
    path.write_text(json.dumps(data, indent=2))


def append_engine_history(case: dict[str, Any]) -> None:
    path = Path("audit_logs/civic_engine_audit_log.json")
    path.parent.mkdir(exist_ok=True)

    summary = extract_behaviour_summary(case)

    data = []
    if path.exists():
        data = json.loads(path.read_text())

    data.append({
        "timestamp": date.today().isoformat(),
        "case": summary["case"],
        "behaviour_index": summary["index"],
        "label": summary["label"],
    })

    path.write_text(json.dumps(data, indent=2))

# ============================================================
# Validation Engine
# ============================================================


def validate_case(case_path: Path, schema_path: Path) -> dict[str, Any] | None:
    schema = load_json(schema_path)
    case_data = load_json(case_path)

    validator = Draft7Validator(schema)
    errors = sorted(
        validator.iter_errors(case_data),
        key=lambda e: list(
            e.path))

    if errors:
        print("\nValidation failed.\n")
        for error in errors:
            print(error.message)
        return None

    print("\nValidation successful.")
    return case_data

# ============================================================
# CLI
# ============================================================


def main() -> None:
    parser = argparse.ArgumentParser(description="Civic Decision Engine v10")

    parser.add_argument(
        "--mode",
        choices=["civic", "system"],
        default="civic",
        help="Run Civic Case Mode or System Analysis Mode",
    )
    parser.add_argument(
        "--input",
        help="Path to input file or directory",
    )
    parser.add_argument(
        "--batch",
        action="store_true",
        help="Process all JSON files in a directory",
    )
    parser.add_argument(
        "--schema",
        default="schema/system_case.schema.json",
        help="Path to schema file",
    )
    parser.add_argument(
        "--raw-signals",
        action="store_true",
        help="Use raw signals from case JSON",
    )
    parser.add_argument(
        "--raw-assessment",
        action="store_true",
        help="Use raw assessment from case JSON",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print JSON output",
    )
    parser.add_argument(
        "--no-validate",
        action="store_true",
        help="Skip schema validation",
    )
    parser.add_argument(
        "--export",
        help="Path to save JSON output",
    )
    parser.add_argument(
        "--export-md",
        help="Path to save Markdown output",
    )

    args = parser.parse_args()

    # ============================================================
    # SYSTEM MODE
    # ============================================================

    if args.mode == "system":
        system_argv = ["system_analysis.py"]

        if args.input:
            system_argv.append(args.input)
        else:
            raise SystemExit("System mode requires --input")

        if args.batch:
            system_argv.append("--batch")
        if args.schema:
            system_argv.extend(["--schema", args.schema])
        if args.raw_signals:
            system_argv.append("--raw-signals")
        if args.raw_assessment:
            system_argv.append("--raw-assessment")
        if args.json:
            system_argv.append("--json")
        if args.no_validate:
            system_argv.append("--no-validate")
        if args.export:
            system_argv.extend(["--export", args.export])
        if args.export_md:
            system_argv.extend(["--export-md", args.export_md])

        original_argv = sys.argv[:]
        try:
            sys.argv = system_argv
            system_analysis_main()
        finally:
            sys.argv = original_argv

        return

    # ============================================================
    # CIVIC MODE (existing menu)
    # ============================================================

    print("Civic Decision Engine — Version 10")
    print("1) Validate sample case")
    print("2) Validate case by path")
    print("3) Run adaptation analysis (example cases)")

    choice = input("\nChoose option: ").strip()

    if choice == "1":
        case = validate_case(SAMPLE_CASE_PATH, SCHEMA_PATH)
        if case:
            result = format_civic_result(case)
            metadata = build_civic_run_metadata(SAMPLE_CASE_PATH, 1)

            output = {
                "run_metadata": metadata,
                "results": [result],
            }

            print(json.dumps(output, indent=2))

            if args.export:
                export_json_output(output, args.export)

            write_case_snapshot(case)
            append_engine_history(case)

    elif choice == "2":
        path = Path(input("Enter case path: ").strip())
        case = validate_case(path, SCHEMA_PATH)
        if case:
            result = format_civic_result(case)
            metadata = build_civic_run_metadata(path, 1)

            output = {
                "run_metadata": metadata,
                "results": [result],
            }

            print(json.dumps(output, indent=2))

            if args.export:
                export_json_output(output, args.export)

            write_case_snapshot(case)
            append_engine_history(case)

    elif choice == "3":
        cases = [load_json(p) for p in EXAMPLE_CASES]
        print_adaptation_analysis(cases)

    else:
        print("Invalid choice.")

# ============================================================

if __name__ == "__main__":
    main()
