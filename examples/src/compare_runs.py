#!/usr/bin/env python3
"""
CDE Compare Runs
Compares two CDE run outputs and detects behavioural transitions.
Transition-aware: surfaces moment of change from audit log.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


LABEL_ORDER = ["Response", "Delayed response", "Partial engagement", "Resistance"]


def label_rank(label: str) -> int:
    try:
        return LABEL_ORDER.index(label)
    except ValueError:
        return -1


def load_json(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_results_by_reference(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    results = payload.get("results", [])
    return {
        r.get("system_reference", f"result_{i}"): r
        for i, r in enumerate(results)
    }


def compare_values(label: str, old: Any, new: Any) -> tuple[bool, str]:
    if old == new:
        return False, f"= {label}: unchanged ({old})"
    return True, f"Δ {label}: {old} -> {new}"


def compare_dict(
    old: dict[str, Any],
    new: dict[str, Any],
) -> tuple[int, int, list[str], dict[str, dict[str, Any]]]:
    changed = 0
    unchanged = 0
    lines: list[str] = []
    structured: dict[str, dict[str, Any]] = {}

    all_keys = sorted(set(old.keys()) | set(new.keys()))
    for key in all_keys:
        old_val = old.get(key)
        new_val = new.get(key)

        if isinstance(old_val, dict) and isinstance(new_val, dict):
            sub_changed, sub_unchanged, sub_lines, sub_structured = compare_dict(
                old_val, new_val
            )
            changed += sub_changed
            unchanged += sub_unchanged
            lines.extend(sub_lines)
            structured[key] = {
                "type": "nested",
                "changes": sub_structured,
            }
        else:
            did_change, line = compare_values(key, old_val, new_val)
            lines.append(line)
            structured[key] = {
                "changed": did_change,
                "old": old_val,
                "new": new_val,
            }
            if did_change:
                changed += 1
            else:
                unchanged += 1

    return changed, unchanged, lines, structured


def load_moment_of_change(log_path: Path, reference: str) -> dict[str, Any] | None:
    if not log_path.exists():
        return None

    entries = json.loads(log_path.read_text())

    case_entries = [e for e in entries if e.get("case") == reference]
    if len(case_entries) < 2:
        return None

    case_entries_sorted = sorted(case_entries, key=lambda e: e.get("timestamp", ""))

    for i in range(1, len(case_entries_sorted)):
        prev = case_entries_sorted[i - 1]
        curr = case_entries_sorted[i]

        index_change = curr.get("behaviour_index", 0) - prev.get("behaviour_index", 0)

        if index_change != 0:
            direction = "deteriorating" if index_change > 0 else "improving"
        else:
            prev_rank = label_rank(prev.get("label", ""))
            curr_rank = label_rank(curr.get("label", ""))
            if curr_rank > prev_rank:
                direction = "deteriorating"
            elif curr_rank < prev_rank:
                direction = "improving"
            else:
                direction = "stable"

        if direction == "deteriorating":
            return {
                "from_event": prev.get("timestamp"),
                "to_event": curr.get("timestamp"),
                "from_label": prev.get("label"),
                "to_label": curr.get("label"),
                "from_index": prev.get("behaviour_index"),
                "to_index": curr.get("behaviour_index"),
                "direction": direction,
            }

    return None


def detect_transition_state(
    old_payload: dict[str, Any],
    new_payload: dict[str, Any],
    timeline_path: Path | None = None,
) -> dict[str, Any]:
    old_results = get_results_by_reference(old_payload)
    new_results = get_results_by_reference(new_payload)

    all_references = sorted(set(old_results.keys()) | set(new_results.keys()))
    transition_states: dict[str, dict[str, Any]] = {}

    for ref in all_references:
        old_result = old_results.get(ref, {})
        new_result = new_results.get(ref, {})

        old_label = old_result.get("assessment", {}).get("label", "")
        new_label = new_result.get("assessment", {}).get("label", "")
        old_index = old_result.get("signals", {}).get("behaviour_index", 0)
        new_index = new_result.get("signals", {}).get("behaviour_index", 0)
        old_condition = old_result.get("condition")
        new_condition = new_result.get("condition")
        index_change = new_index - old_index
        old_rank = label_rank(old_label)
        new_rank = label_rank(new_label)

        if index_change != 0:
            direction = "deteriorating" if index_change > 0 else "improving"
        elif new_rank > old_rank:
            direction = "deteriorating"
        elif new_rank < old_rank:
            direction = "improving"
        else:
            direction = "stable"

        moment = None
        if timeline_path:
            moment = load_moment_of_change(timeline_path, ref)

        old_generated = old_payload.get("run_metadata", {}).get("generated_at", "")
        new_generated = new_payload.get("run_metadata", {}).get("generated_at", "")

        if moment is None:
            transition_status = "no_transition_recorded"
            transition_label = "No transition recorded in either run"
        else:
            moment_time = moment.get("to_event", "")
            moment_before_old = moment_time <= old_generated[:10]
            moment_between = old_generated[:10] < moment_time <= new_generated[:10]

            if moment_before_old:
                transition_status = "first_transition_already_occurred"
                transition_label = "First transition already occurred"
            elif moment_between:
                transition_status = "new_transition_detected"
                transition_label = "New transition detected"
            else:
                transition_status = "no_new_transition"
                transition_label = "No new transition since prior run"

        transition_states[ref] = {
            "reference": ref,
            "old_label": old_label,
            "new_label": new_label,
            "old_index": old_index,
            "new_index": new_index,
            "old_condition": old_condition,
            "new_condition": new_condition,
            "condition_changed": old_condition != new_condition,
            "direction": direction,
            "transition_status": transition_status,
            "transition_label": transition_label,
            "moment_of_change": moment,
        }

    return transition_states


def print_section(title: str) -> None:
    print(f"\n{title}")
    print("-" * len(title))


def build_comparison(
    old_path: Path,
    new_path: Path,
    timeline_path: Path | None = None,
) -> dict[str, Any]:
    old_payload = load_json(str(old_path))
    new_payload = load_json(str(new_path))

    old_meta = old_payload.get("run_metadata", {})
    new_meta = new_payload.get("run_metadata", {})

    old_results = get_results_by_reference(old_payload)
    new_results = get_results_by_reference(new_payload)

    all_references = sorted(set(old_results.keys()) | set(new_results.keys()))

    old_run_id = old_meta.get("run_id")
    new_run_id = new_meta.get("run_id")
    old_lineage = old_meta.get("lineage", {})
    new_lineage = new_meta.get("lineage", {})
    old_depth = old_lineage.get("depth", 1)
    new_depth = new_lineage.get("depth", old_depth + 1)
    new_parent_id = new_lineage.get("previous_run_id")
    lineage_continuity = new_parent_id == old_run_id

    lineage = {
        "old_run_id": old_run_id,
        "new_run_id": new_run_id,
        "new_parent_run_id": new_parent_id,
        "old_depth": old_depth,
        "new_depth": new_depth,
        "lineage_continuity": lineage_continuity,
    }

    metadata_structured: dict[str, dict[str, Any]] = {}
    metadata_lines: list[str] = []
    metadata_changed = 0
    metadata_unchanged = 0

    metadata_fields = [
        ("run_id", old_meta.get("run_id"), new_meta.get("run_id")),
        ("generated_at", old_meta.get("generated_at"), new_meta.get("generated_at")),
        ("mode", old_meta.get("mode"), new_meta.get("mode")),
        ("input_path", old_meta.get("input_path"), new_meta.get("input_path")),
        ("schema_path", old_meta.get("schema_path"), new_meta.get("schema_path")),
        ("case_count", old_meta.get("case_count"), new_meta.get("case_count")),
        (
            "previous_run_id",
            old_lineage.get("previous_run_id"),
            new_lineage.get("previous_run_id"),
        ),
        ("lineage_depth", old_lineage.get("depth"), new_lineage.get("depth")),
        ("lineage_version", old_lineage.get("version"), new_lineage.get("version")),
    ]

    for label, old_val, new_val in metadata_fields:
        did_change, line = compare_values(label, old_val, new_val)
        metadata_lines.append(line)
        metadata_structured[label] = {
            "changed": did_change,
            "old": old_val,
            "new": new_val,
        }
        if did_change:
            metadata_changed += 1
        else:
            metadata_unchanged += 1

    result_comparisons: dict[str, dict[str, Any]] = {}
    total_result_changed = 0
    total_result_unchanged = 0
    any_behavioural_change = False

    for ref in all_references:
        old_result = old_results.get(ref, {})
        new_result = new_results.get(ref, {})

        old_condition = old_result.get("condition")
        new_condition = new_result.get("condition")

        if not old_result:
            result_comparisons[ref] = {"status": "added", "result": new_result}
            any_behavioural_change = True
            continue

        if not new_result:
            result_comparisons[ref] = {"status": "removed", "result": old_result}
            any_behavioural_change = True
            continue

        top_fields = [
            (
                "system_reference",
                old_result.get("system_reference"),
                new_result.get("system_reference"),
            ),
            ("title", old_result.get("title"), new_result.get("title")),
            ("domain", old_result.get("domain"), new_result.get("domain")),
            (
                "declared_purpose",
                old_result.get("declared_purpose"),
                new_result.get("declared_purpose"),
            ),
        ]

        top_changed = 0
        top_unchanged = 0
        top_lines: list[str] = []
        top_structured: dict[str, dict[str, Any]] = {}

        for label, old_val, new_val in top_fields:
            did_change, line = compare_values(label, old_val, new_val)
            top_lines.append(line)
            top_structured[label] = {
                "changed": did_change,
                "old": old_val,
                "new": new_val,
            }
            if did_change:
                top_changed += 1
            else:
                top_unchanged += 1

        signals_changed, signals_unchanged, signals_lines, signals_structured = compare_dict(
            old_result.get("signals", {}),
            new_result.get("signals", {}),
        )

        (
            assessment_changed,
            assessment_unchanged,
            assessment_lines,
            assessment_structured,
        ) = compare_dict(
            old_result.get("assessment", {}),
            new_result.get("assessment", {}),
        )

        condition_changed = 0
        condition_unchanged = 0
        condition_lines: list[str] = []
        condition_structured: dict[str, dict[str, Any]] = {}

        did_change, line = compare_values("condition", old_condition, new_condition)
        condition_lines.append(line)
        condition_structured["condition"] = {
            "changed": did_change,
            "old": old_condition,
            "new": new_condition,
        }
        if did_change:
            condition_changed += 1
        else:
            condition_unchanged += 1

        result_changed = top_changed + signals_changed + assessment_changed + condition_changed
        result_unchanged = top_unchanged + signals_unchanged + assessment_unchanged + condition_unchanged

        total_result_changed += result_changed
        total_result_unchanged += result_unchanged

        if result_changed > 0:
            any_behavioural_change = True

        result_comparisons[ref] = {
            "status": "compared",
            "top_level": {
                "changed": top_changed,
                "unchanged": top_unchanged,
                "fields": top_structured,
                "lines": top_lines,
            },
            "signals": {
                "changed": signals_changed,
                "unchanged": signals_unchanged,
                "fields": signals_structured,
                "lines": signals_lines,
            },
            "condition": {
                "changed": condition_changed,
                "unchanged": condition_unchanged,
                "fields": condition_structured,
                "lines": condition_lines,
            },
            "assessment": {
                "changed": assessment_changed,
                "unchanged": assessment_unchanged,
                "fields": assessment_structured,
                "lines": assessment_lines,
            },
            "result_changes": result_changed,
            "result_unchanged": result_unchanged,
        }

    transition_states = detect_transition_state(old_payload, new_payload, timeline_path)

    interpretation = (
        "result-level changes detected between runs."
        if any_behavioural_change
        else "new run recorded, but no result-level change detected."
    )

    return {
        "comparison_metadata": {
            "old_file": str(old_path),
            "new_file": str(new_path),
        },
        "lineage": lineage,
        "metadata": {
            "changed": metadata_changed,
            "unchanged": metadata_unchanged,
            "fields": metadata_structured,
            "lines": metadata_lines,
        },
        "results": result_comparisons,
        "transition_states": transition_states,
        "summary": {
            "references_compared": len(all_references),
            "metadata_changes": metadata_changed,
            "metadata_unchanged": metadata_unchanged,
            "total_result_changes": total_result_changed,
            "total_result_unchanged": total_result_unchanged,
            "behavioural_change_detected": any_behavioural_change,
            "interpretation": interpretation,
        },
    }


def print_human_readable(comparison: dict[str, Any]) -> None:
    print("\nRun Comparison")
    print("==============")
    print(f"Old File: {comparison['comparison_metadata']['old_file']}")
    print(f"New File: {comparison['comparison_metadata']['new_file']}")

    lineage = comparison.get("lineage", {})
    if lineage:
        print_section("Lineage")
        print(f"Old Run ID         : {lineage.get('old_run_id')}")
        print(f"New Run ID         : {lineage.get('new_run_id')}")
        print(f"New Parent Run ID  : {lineage.get('new_parent_run_id')}")
        print(f"Depth Change       : {lineage.get('old_depth')} -> {lineage.get('new_depth')}")
        print(
            f"Lineage Continuity : {'yes' if lineage.get('lineage_continuity') else 'no'}"
        )

    print_section("Metadata")
    for line in comparison["metadata"]["lines"]:
        print(line)

    for ref, result in comparison.get("results", {}).items():
        print_section(f"Result: {ref}")

        if result["status"] == "added":
            print("  [added in new run]")
            continue
        if result["status"] == "removed":
            print("  [removed — present in old run only]")
            continue

        print("\n  Top Level")
        for line in result["top_level"]["lines"]:
            print(f"  {line}")

        print("\n  Signals")
        for line in result["signals"]["lines"]:
            print(f"  {line}")

        print("\n  Condition")
        for line in result["condition"]["lines"]:
            print(f"  {line}")

        print("\n  Assessment")
        for line in result["assessment"]["lines"]:
            print(f"  {line}")

        print(f"\n  Result changes: {result['result_changes']}")

    transition_states = comparison.get("transition_states", {})
    if transition_states:
        print_section("Transition States")
        for ref, state in transition_states.items():
            print(f"\n  Reference : {ref}")
            print(f"  Status    : {state['transition_label']}")
            print(f"  Direction : {state['direction']}")
            if state.get("moment_of_change"):
                m = state["moment_of_change"]
                print(
                    f"  Moment of Change : "
                    f"{m.get('from_event')} → {m.get('to_event')}  |  "
                    f"{m.get('from_label')} → {m.get('to_label')}  |  "
                    f"index {m.get('from_index')} → {m.get('to_index')}"
                )

    summary = comparison["summary"]
    print_section("Summary")
    print(f"References compared       : {summary['references_compared']}")
    print(f"Metadata changes          : {summary['metadata_changes']}")
    print(f"Total result changes      : {summary['total_result_changes']}")
    print(
        f"Behavioural change        : {'yes' if summary['behavioural_change_detected'] else 'no'}"
    )
    print(f"Interpretation            : {summary['interpretation']}")


def export_markdown(comparison: dict[str, Any], export_path: str) -> None:
    path = Path(export_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    meta = comparison["comparison_metadata"]
    summary = comparison["summary"]
    lineage = comparison.get("lineage", {})

    lines = [
        "# Run Comparison Report",
        "",
        "## Files",
        "",
        f"- **Old File:** {meta['old_file']}",
        f"- **New File:** {meta['new_file']}",
        "",
    ]

    if lineage:
        lines += [
            "## Lineage",
            "",
            f"- **Old Run ID:** {lineage.get('old_run_id')}",
            f"- **New Run ID:** {lineage.get('new_run_id')}",
            f"- **New Parent Run ID:** {lineage.get('new_parent_run_id')}",
            f"- **Depth Change:** {lineage.get('old_depth')} → {lineage.get('new_depth')}",
            f"- **Lineage Continuity:** {'yes' if lineage.get('lineage_continuity') else 'no'}",
            "",
        ]

    lines += ["## Metadata", ""]
    lines.extend(comparison["metadata"]["lines"])
    lines.append("")

    transition_states = comparison.get("transition_states", {})
    if transition_states:
        lines += ["## Transition States", ""]
        for ref, state in transition_states.items():
            lines += [
                f"### {ref}",
                "",
                f"- **Status:** {state['transition_label']}",
                f"- **Direction:** {state['direction']}",
            ]
            if state.get("moment_of_change"):
                m = state["moment_of_change"]
                lines.append(
                    f"- **Moment of Change:** "
                    f"`{m.get('from_event')}` → `{m.get('to_event')}` — "
                    f"{m.get('from_label')} → {m.get('to_label')} — "
                    f"index {m.get('from_index')} → {m.get('to_index')}"
                )
            lines.append("")

    lines += [
        "## Summary",
        "",
        f"- **References Compared:** {summary['references_compared']}",
        f"- **Metadata Changes:** {summary['metadata_changes']}",
        f"- **Metadata Unchanged:** {summary['metadata_unchanged']}",
        f"- **Total Result Changes:** {summary['total_result_changes']}",
        f"- **Total Result Unchanged:** {summary['total_result_unchanged']}",
        f"- **Behavioural Change Detected:** {'Yes' if summary['behavioural_change_detected'] else 'No'}",
        f"- **Interpretation:** {summary['interpretation']}",
        "",
    ]

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines).rstrip() + "\n")

    print(f"Exported Markdown report -> {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare two CDE run outputs")
    parser.add_argument("old_run", help="Path to the older run JSON file")
    parser.add_argument("new_run", help="Path to the newer run JSON file")
    parser.add_argument(
        "--timeline",
        help="Path to audit log JSON file for transition state detection",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print comparison as machine-readable JSON",
    )
    parser.add_argument(
        "--export",
        help="Path to save comparison JSON output",
    )
    parser.add_argument(
        "--export-md",
        help="Path to save Markdown comparison report",
    )

    args = parser.parse_args()

    old_path = Path(args.old_run)
    new_path = Path(args.new_run)

    if not old_path.exists():
        print(f"Error: file not found -> {old_path}")
        raise SystemExit(1)

    if not new_path.exists():
        print(f"Error: file not found -> {new_path}")
        raise SystemExit(1)

    timeline_path = Path(args.timeline) if args.timeline else None

    comparison = build_comparison(old_path, new_path, timeline_path)

    if args.export:
        export_path = Path(args.export)
        export_path.parent.mkdir(parents=True, exist_ok=True)
        with open(export_path, "w", encoding="utf-8") as f:
            json.dump(comparison, f, indent=2)
        print(f"Exported comparison -> {export_path}")

    if args.export_md:
        export_markdown(comparison, args.export_md)

    if args.json:
        print(json.dumps(comparison, indent=2))
    else:
        print_human_readable(comparison)


if __name__ == "__main__":
    main()
