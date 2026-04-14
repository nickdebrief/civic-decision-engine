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

OUTPUT_ROOT = Path("outputs")


def build_civic_markdown(output: dict[str, Any]) -> str:
    metadata = output["run_metadata"]
    result = output["results"][0]

    lines = [
        "# Civic Run",
        "",
        f"**Run ID:** {metadata['run_id']}",
        f"**Generated:** {metadata['generated_at']}",
        f"**Version:** {metadata['lineage']['version']}",
        "",
        "## Result",
        "",
        f"- System Reference: {result.get('system_reference', '')}",
        f"- Title: {result.get('title', '')}",
        f"- Condition: {result.get('condition', '')}",
        f"- Label: {result.get('assessment', {}).get('label', '')}",
        f"- Interpretation: {result.get('assessment', {}).get('interpretation', '')}",
        "",
        "## Signals",
        f"- Posture: {result.get('signals', {}).get('posture', '')}",
        f"- Engagement: {result.get('signals', {}).get('engagement', '')}",
        f"- Escalation: {result.get('signals', {}).get('escalation', '')}",
        f"- Behaviour Index: {result.get('signals', {}).get('behaviour_index', '')}",
    ]

    return "\n".join(lines)


def build_compare_markdown(output: dict[str, Any]) -> str:
    metadata = output["run_metadata"]

    lines = [
        "# Compare Run",
        "",
        f"**Run ID:** {metadata['run_id']}",
        "",
        f"**Generated:** {metadata['generated_at']}",
        "",
        f"**Version:** {metadata['lineage']['version']}",
        "",
        "## Results",
        "",
    ]

    for i, result in enumerate(output.get("results", []), start=1):
        moment_of_change = result.get("moment_of_change")

        lines.extend(
            [
                f"### Result {i}",
                f"- Case Sequence: {' → '.join(result.get('case_sequence', []))}",
                f"- Behaviour Indices: {' → '.join(map(str, result.get('behaviour_indices', [])))}",
                f"- Progression: {' → '.join(result.get('progression', []))}",
                f"- Trajectory: {result.get('trajectory', '')}",
            ]
        )

        if moment_of_change:
            lines.append(
                f"- Moment of Change: {moment_of_change['from']} → {moment_of_change['to']} "
                f"(Run {moment_of_change['at_index']})"
            )

        lines.extend(
            [
                f"- Interpretation: {result.get('interpretation', '')}",
                "",
            ]
        )

    return "\n".join(lines)


def build_timeline_markdown(output: dict[str, Any]) -> str:
    metadata = output["run_metadata"]

    lines = [
        "# Timeline Run",
        "",
        f"**Run ID:** {metadata['run_id']}",
        "",
        f"**Generated:** {metadata['generated_at']}",
        "",
        f"**Version:** {metadata['lineage']['version']}",
        "",
        "## Timeline Summary",
        "",
    ]

    for i, result in enumerate(output.get("results", []), start=1):
        run_sequence = result.get("run_sequence", [])
        progression = result.get("progression", [])
        trajectory = result.get("trajectory", "")
        interpretation = result.get("interpretation", "")
        moment_of_change = result.get("moment_of_change")

        lines.extend(
            [
                f"### Sequence {i}",
                f"- Run Sequence: {' → '.join(run_sequence)}",
                f"- Progression: {' → '.join(progression)}",
                f"- Trajectory: {trajectory}",
            ]
        )

        # ✅ Only include if it exists
        if moment_of_change:
            lines.append(
                f"- Moment of Change: {moment_of_change['from']} → {moment_of_change['to']} "
                f"(Run {moment_of_change['at_index']})"
            )

        lines.extend(
            [
                f"- Interpretation: {interpretation}",
                "",
            ]
        )

    return "\n".join(lines)


def build_timeline_output(case: dict[str, Any]) -> dict[str, Any]:
    run_id = (
        f"timeline-analysis-{datetime.now(timezone.utc).strftime('%Y-%m-%d-%H%M%S')}"
    )

    return {
        "run_metadata": {
            "run_id": run_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "mode": "timeline_analysis",
            "case_count": 1,
            "lineage": {"version": "v10"},
        },
        "results": [
            {
                "system_reference": case.get("strike_reference", ""),
                "title": case.get("case_title", ""),
                "timeline": case.get("timeline", []),
            }
        ],
    }


def save_run_snapshot(category: str, run_id: str, data: dict[str, Any]) -> Path:
    run_dir = OUTPUT_ROOT / category / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    json_path = run_dir / "result.json"
    with json_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")

    md_path = run_dir / "summary.md"
    if category == "civic":
        md_content = build_civic_markdown(data)
    elif category == "compare":
        md_content = build_compare_markdown(data)
    elif category == "timeline":
        md_content = build_timeline_markdown(data)
    else:
        md_content = "# Run Summary\n"

    md_path.write_text(md_content, encoding="utf-8")

    return json_path


def load_stored_civic_runs() -> list[dict[str, Any]]:
    run_files = sorted(Path("outputs/civic").glob("*/result.json"))

    runs: list[dict[str, Any]] = []
    for run_file in run_files:
        with run_file.open("r", encoding="utf-8") as f:
            runs.append(json.load(f))

    return runs


def interpret_timeline_result(
    behaviour_indices: list[int],
    conditions: list[str],
    progression: list[str],
    trajectory: str,
    moment_of_change: dict[str, Any] | None,
) -> str:
    if not behaviour_indices:
        return "No stored runs were available for timeline interpretation."

    if trajectory == "Stable" and moment_of_change is None:
        return "Behaviour remained stable across stored runs with no detected moment of change."

    if trajectory == "Deteriorating" and moment_of_change is not None:
        return (
            f"Behaviour deteriorated across stored runs, with a change from "
            f"{moment_of_change['from']} to {moment_of_change['to']} at run {moment_of_change['at_index']}."
        )

    if trajectory == "Improving" and moment_of_change is not None:
        return (
            f"Behaviour improved across stored runs, with a change from "
            f"{moment_of_change['from']} to {moment_of_change['to']} at run {moment_of_change['at_index']}."
        )

    if trajectory == "Mixed" and moment_of_change is not None:
        return (
            f"Behaviour changed across stored runs, with the first detected shift from "
            f"{moment_of_change['from']} to {moment_of_change['to']} at run {moment_of_change['at_index']}."
        )

    if trajectory == "Mixed":
        return "Behaviour varied across stored runs without a single clear directional pattern."

    return (
        "Timeline interpretation was generated, but no stronger pattern was detected."
    )


def build_timeline_output_from_runs(
    stored_runs: list[dict[str, Any]],
) -> dict[str, Any]:
    run_id = (
        f"timeline-analysis-{datetime.now(timezone.utc).strftime('%Y-%m-%d-%H%M%S')}"
    )

    run_sequence: list[str] = []
    case_sequence: list[str] = []
    behaviour_indices: list[int] = []
    conditions: list[str] = []
    progression: list[str] = []

    for run in stored_runs:
        metadata = run.get("run_metadata", {})
        results = run.get("results", [])
        if not results:
            continue

        result = results[0]

        run_sequence.append(metadata.get("run_id", ""))
        case_sequence.append(result.get("system_reference", ""))
        behaviour_indices.append(result.get("signals", {}).get("behaviour_index", 0))
        conditions.append(result.get("condition", ""))
        progression.append(result.get("assessment", {}).get("label", ""))

    if len(set(behaviour_indices)) == 1:
        trajectory = "Stable"
    elif behaviour_indices == sorted(behaviour_indices):
        trajectory = "Deteriorating"
    elif behaviour_indices == sorted(behaviour_indices, reverse=True):
        trajectory = "Improving"
    else:
        trajectory = "Mixed"

    moment_of_change = None
    for i in range(1, len(conditions)):
        if conditions[i] != conditions[i - 1]:
            moment_of_change = {
                "from": conditions[i - 1],
                "to": conditions[i],
                "at_index": i + 1,
            }
            break

    interpretation = interpret_timeline_result(
        behaviour_indices,
        conditions,
        progression,
        trajectory,
        moment_of_change,
    )
    return {
        "run_metadata": {
            "run_id": run_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "mode": "timeline_analysis",
            "source": "outputs/civic/",
            "case_count": len(case_sequence),
            "lineage": {
                "version": "v10",
            },
        },
        "results": [
            {
                "run_sequence": run_sequence,
                "case_sequence": case_sequence,
                "behaviour_indices": behaviour_indices,
                "conditions": conditions,
                "progression": progression,
                "trajectory": trajectory,
                "moment_of_change": moment_of_change,
                "interpretation": interpretation,
            }
        ],
    }


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
    resolution_status = lifecycle.get("resolution_status")

    if status == "closed" and resolution_status == "unresolved":
        posture = "Withdrawn"
        engagement = "Very low"
        escalation = "High"
        label = "Resistance"

    elif stalled or (stage == "awaiting_response" and days_open >= 30):
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
    if (
        posture in ["Neutral", "Cautious", "Defensive"]
        and engagement == "Low"
        and escalation in ["Increasing", "High"]
    ):
        return "ACKNOWLEDGEMENT_WITHOUT_ACTION"
    if (
        label == "Delayed response"
        and posture == "Cautious"
        and engagement == "Moderate"
        and escalation == "Watch"
    ):
        return "TRANSFER_OF_BURDEN"

    if label == "Partial engagement":
        return "PARTIAL_ENGAGEMENT"

    if posture == "Defensive" and engagement == "Low":
        return "ADMINISTRATIVE_CONTAINMENT"

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


def print_timeline_analysis(output: dict[str, Any]) -> None:
    print("\n══════════════════════════════")
    print("Timeline Analysis (V10)")
    print("══════════════════════════════")

    results = output.get("results", [])
    if not results:
        print("No timeline results available.")
        return

    r = results[0]

    run_sequence = r.get("run_sequence", [])
    progression = r.get("progression", [])
    trajectory = r.get("trajectory", "")
    interpretation = r.get("interpretation", "")

    print("Run sequence      :", " → ".join(run_sequence))
    print("Progression       :", " → ".join(progression))
    print("Trajectory        :", trajectory)

    moment_of_change = r.get("moment_of_change")
    if moment_of_change:
        print("\nMoment of Change")
        print("----------------")
        print(
            f"{moment_of_change['from']} → {moment_of_change['to']} "
            f"(Run {moment_of_change['at_index']})"
        )

    print("\nInterpretation")
    print("--------------")
    print(interpretation)


def print_adaptation_analysis(cases: list[dict[str, Any]]) -> dict[str, Any]:
    print("\n══════════════════════════════")
    print("Adaptation Analysis (V10)")
    print("══════════════════════════════")

    summaries = [extract_behaviour_summary(c) for c in cases]

    labels = [s["label"] for s in summaries]
    indices = [s["index"] for s in summaries]
    case_sequence = [s["case"] for s in summaries]

    if len(set(indices)) == 1:
        trajectory = "Stable"
    elif indices == sorted(indices):
        trajectory = "Deteriorating"
    elif indices == sorted(indices, reverse=True):
        trajectory = "Improving"
    else:
        trajectory = "Mixed"

    moment_of_change = None
    for i in range(1, len(labels)):
        if labels[i] != labels[i - 1]:
            moment_of_change = {
                "from": labels[i - 1],
                "to": labels[i],
                "at_index": i + 1,
            }
            break

    print("Case sequence      :", " → ".join(case_sequence))
    print("Progression        :", " → ".join(labels))
    print("Trajectory         :", trajectory)

    if moment_of_change:
        print("\nMoment of Change")
        print("----------------")
        print(
            f"{moment_of_change['from']} → {moment_of_change['to']} "
            f"(Run {moment_of_change['at_index']})"
        )

    if trajectory == "Stable" and moment_of_change is None:
        interpretation = "Behaviour remained stable across compared cases with no detected moment of change."
    elif trajectory == "Deteriorating" and moment_of_change is not None:
        interpretation = (
            f"Behaviour shows increasing institutional resistance or containment over time, "
            f"with a shift from {moment_of_change['from']} to {moment_of_change['to']} at run {moment_of_change['at_index']}."
        )
    elif trajectory == "Improving" and moment_of_change is not None:
        interpretation = (
            f"Behaviour shows improving engagement over time, with a shift from "
            f"{moment_of_change['from']} to {moment_of_change['to']} at run {moment_of_change['at_index']}."
        )
    elif trajectory == "Mixed" and moment_of_change is not None:
        interpretation = (
            f"Behaviour changes across compared cases, with the first detected shift from "
            f"{moment_of_change['from']} to {moment_of_change['to']} at run {moment_of_change['at_index']}."
        )
    else:
        interpretation = "Behaviour varies across compared cases without a single clear directional pattern."

    print("\nInterpretation")
    print("--------------")
    print(interpretation)

    output = {
        "run_metadata": {
            "run_id": f"compare-analysis-{datetime.now(timezone.utc).strftime('%Y-%m-%d-%H%M%S')}",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "mode": "compare_analysis",
            "case_count": len(cases),
            "lineage": {
                "version": "v10",
            },
        },
        "results": [
            {
                "case_sequence": case_sequence,
                "behaviour_indices": indices,
                "progression": labels,
                "trajectory": trajectory,
                "moment_of_change": moment_of_change,
                "interpretation": interpretation,
            }
        ],
    }

    return output


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

    data.append(
        {
            "timestamp": date.today().isoformat(),
            "case": summary["case"],
            "behaviour_index": summary["index"],
            "label": summary["label"],
            "condition": condition,
        }
    )

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
    print("4) Run timeline analysis (stored runs)")

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
            print("Validation successful.")
            print(json.dumps(output, indent=2))

            saved_path = save_run_snapshot(
                "civic", output["run_metadata"]["run_id"], output
            )
            print(f"\nSaved output → {saved_path}")

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
            saved_path = save_run_snapshot(
                "civic", output["run_metadata"]["run_id"], output
            )
            print(f"\nSaved output → {saved_path}")

            if args.export:
                export_json_output(output, args.export)

            write_case_snapshot(case)
            append_engine_history(case)

    elif choice == "3":
        cases = [load_json(p) for p in EXAMPLE_CASES]
        compare_output = print_adaptation_analysis(cases)

        saved_path = save_run_snapshot(
            "compare",
            compare_output["run_metadata"]["run_id"],
            compare_output,
        )
        print(f"\nSaved output → {saved_path}")

    elif choice == "4":
        stored_runs = load_stored_civic_runs()

        if not stored_runs:
            print("No stored civic runs found in outputs/civic/.")
        else:
            timeline_output = build_timeline_output_from_runs(stored_runs)
            print_timeline_analysis(timeline_output)

            # Optional debug view
            # print(json.dumps(timeline_output, indent=2))

            saved_path = save_run_snapshot(
                "timeline",
                timeline_output["run_metadata"]["run_id"],
                timeline_output,
            )
            print(f"\nSaved output → {saved_path}")
    else:
        print("Invalid choice.")


# ============================================================

if __name__ == "__main__":
    main()
