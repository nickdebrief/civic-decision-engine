#!/usr/bin/env python3
"""
Civic Decision Engine
Version: 10
Author: Nick Moloney
Build: 2026-04-05
License: MIT
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

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


def read_previous_run_id(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        data = load_json(path)
        return data.get("run_metadata", {}).get("run_id")
    except Exception:
        return None


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

    if stalled or (stage == "awaiting_response" and days_open >= 30):
        posture = "Withdrawn"
        engagement = "Very low"
        escalation = "High"
        label = "Resistance"

    elif (
        status == "active"
        and stage == "awaiting_response"
        and mode == "hold_and_prepare"
        and days_open >= 10
    ):
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
        "Withdrawn": 3,
    }
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

def classify_condition(summary: dict[str, Any]) -> str:
    posture = summary.get("posture")
    engagement = summary.get("engagement")
    escalation = summary.get("escalation")
    label = summary.get("label")

    if escalation == "High" and engagement in ["Low", "Very low"]:
        return "ESCALATION_WITHOUT_RESPONSE"

    if posture == "Withdrawn" or engagement == "Very low":
        return "RESISTANCE"

    if label == "Partial engagement":
        return "PARTIAL_ENGAGEMENT"

    if posture == "Defensive" and engagement == "Low":
        return "ADMINISTRATIVE_CONTAINMENT"

    if label == "Response" and engagement == "Normal" and escalation == "Low":
        return "ACKNOWLEDGEMENT_WITHOUT_ACTION"

    if label == "Delayed response" and posture == "Cautious":
        return "TRANSFER_OF_BURDEN"

    if posture in ["Neutral", "Cautious"]:
        return "STABILITY_WITHOUT_CONFIRMATION"

    return "UNCLASSIFIED"


def format_civic_result(case: dict[str, Any]) -> dict[str, Any]:
    summary = extract_behaviour_summary(case)
    condition = classify_condition(summary)

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
        "condition": condition,
        "assessment": {
            "label": summary["label"],
            "interpretation": (
                f"Institutional behaviour classified as {summary['label']} "
                f"with posture {summary['posture']}."
            ),
        },
    }


def build_civic_run_metadata(
    input_path: Path | None,
    case_count: int,
    previous_run_id: str | None = None,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    depth = 1 if previous_run_id is None else 2

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
        "lineage": {
            "previous_run_id": previous_run_id,
            "depth": depth,
            "version": "v10",
        },
    }


def export_json_output(output: dict[str, Any], path: str) -> None:
    export_path = Path(path)
    export_path.parent.mkdir(parents=True, exist_ok=True)
    export_path.write_text(json.dumps(output, indent=2))
    print(f"\nExported results -> {export_path}")


# ============================================================
# Adaptation Layer (NEW IN V10)
# ============================================================


def print_adaptation_analysis(cases: list[dict[str, Any]]) -> None:
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
            "Behaviour shows increasing institutional resistance or containment over time."
        )
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
    condition = classify_condition(summary)

    data = []
    if path.exists():
        data = json.loads(path.read_text())

    data.append({
        "timestamp": date.today().isoformat(),
        "case": summary["case"],
        "behaviour_index": summary["index"],
        "label": summary["label"],
        "condition": condition,
    })

    path.write_text(json.dumps(data, indent=2))

# ============================================================
# Validation Engine
# ============================================================


def validate_case(case_path: Path, schema_path: Path) -> dict[str, Any] | None:
    schema = load_json(schema_path)
    case_data = load_json(case_path)

    validator = Draft7Validator(schema)
    errors = sorted(validator.iter_errors(case_data), key=lambda e: list(e.path))

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
        choices=["civic", "system", "compare"],
        default="civic",
        help="Run Civic Case Mode, System Analysis Mode, or Compare Mode",
    )
    parser.add_argument(
        "--input",
        help="Path to input file or directory",
    )
    parser.add_argument(
        "--previous-run",
        help="Path to previous run JSON file to establish lineage continuity",
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
    parser.add_argument(
        "--compare-with",
        help="Path to older run JSON file (required for compare mode)",
    )
    parser.add_argument(
        "--timeline",
        help="Path to audit log JSON file for transition state detection",
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
    # COMPARE MODE
    # ============================================================

    if args.mode == "compare":
        from compare_runs import build_comparison, export_markdown, print_human_readable

        if not args.input:
            raise SystemExit("Compare mode requires --input (new run path)")
        if not args.compare_with:
            raise SystemExit("Compare mode requires --compare-with (old run path)")

        old_path = Path(args.compare_with)
        new_path = Path(args.input)

        if not old_path.exists():
            raise SystemExit(f"File not found: {old_path}")
        if not new_path.exists():
            raise SystemExit(f"File not found: {new_path}")

        timeline_path = Path(args.timeline) if args.timeline else None

        comparison = build_comparison(old_path, new_path, timeline_path)

        if args.export:
            export_path = Path(args.export)
            export_path.parent.mkdir(parents=True, exist_ok=True)
            with open(export_path, "w", encoding="utf-8") as f:
                json.dump(comparison, f, indent=2)
            print(f"\nExported comparison -> {export_path}")

        if args.export_md:
            export_markdown(comparison, args.export_md)

        if args.json:
            print(json.dumps(comparison, indent=2))
        else:
            print_human_readable(comparison)

        return

    # ============================================================
    # CIVIC MODE
    # ============================================================

    print("Civic Decision Engine — Version 10")
    print("1) Validate sample case")
    print("2) Validate case by path")
    print("3) Run adaptation analysis (example cases)")

    choice = input("\nChoose option: ").strip()

    if choice == "1":
        case = validate_case(SAMPLE_CASE_PATH, SCHEMA_PATH)
        if case:
            previous_run_id = None
            if args.previous_run:
                previous_run_id = read_previous_run_id(Path(args.previous_run))

            result = format_civic_result(case)
            metadata = build_civic_run_metadata(
                SAMPLE_CASE_PATH,
                1,
                previous_run_id,
            )

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
            previous_run_id = None
            if args.previous_run:
                previous_run_id = read_previous_run_id(Path(args.previous_run))

            result = format_civic_result(case)
            metadata = build_civic_run_metadata(
                path,
                1,
                previous_run_id,
            )

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