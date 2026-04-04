import argparse
import json
from pathlib import Path
from typing import Any


def load_json(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_first_result(payload: dict[str, Any]) -> dict[str, Any]:
    results = payload.get("results", [])
    if not results:
        return {}
    return results[0]


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


def print_section(title: str) -> None:
    print(f"\n{title}")
    print("-" * len(title))


def build_comparison(old_path: Path, new_path: Path) -> dict[str, Any]:
    old_payload = load_json(str(old_path))
    new_payload = load_json(str(new_path))

    old_meta = old_payload.get("run_metadata", {})
    new_meta = new_payload.get("run_metadata", {})

    old_result = get_first_result(old_payload)
    new_result = get_first_result(new_payload)

    metadata_changed = 0
    metadata_unchanged = 0
    metadata_lines: list[str] = []
    metadata_structured: dict[str, dict[str, Any]] = {}

    metadata_fields = [
        ("run_id", old_meta.get("run_id"), new_meta.get("run_id")),
        ("generated_at", old_meta.get("generated_at"), new_meta.get("generated_at")),
        ("mode", old_meta.get("mode"), new_meta.get("mode")),
        ("input_path", old_meta.get("input_path"), new_meta.get("input_path")),
        ("schema_path", old_meta.get("schema_path"), new_meta.get("schema_path")),
        ("case_count", old_meta.get("case_count"), new_meta.get("case_count")),
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

    top_level_changed = 0
    top_level_unchanged = 0
    top_level_lines: list[str] = []
    top_level_structured: dict[str, dict[str, Any]] = {}

    top_fields = [
        ("system_reference", old_result.get("system_reference"), new_result.get("system_reference")),
        ("title", old_result.get("title"), new_result.get("title")),
        ("domain", old_result.get("domain"), new_result.get("domain")),
        ("declared_purpose", old_result.get("declared_purpose"), new_result.get("declared_purpose")),
    ]

    for label, old_val, new_val in top_fields:
        did_change, line = compare_values(label, old_val, new_val)
        top_level_lines.append(line)
        top_level_structured[label] = {
            "changed": did_change,
            "old": old_val,
            "new": new_val,
        }
        if did_change:
            top_level_changed += 1
        else:
            top_level_unchanged += 1

    signals_changed, signals_unchanged, signals_lines, signals_structured = compare_dict(
        old_result.get("signals", {}),
        new_result.get("signals", {}),
    )

    assessment_changed, assessment_unchanged, assessment_lines, assessment_structured = compare_dict(
        old_result.get("assessment", {}),
        new_result.get("assessment", {}),
    )

    result_changed = top_level_changed + signals_changed + assessment_changed
    result_unchanged = top_level_unchanged + signals_unchanged + assessment_unchanged

    total_changed = metadata_changed + result_changed
    total_unchanged = metadata_unchanged + result_unchanged

    if result_changed == 0:
        interpretation = "new run recorded, but no result-level change detected."
        behavioural_change_detected = False
    else:
        interpretation = "result-level changes detected between runs."
        behavioural_change_detected = True

    return {
        "comparison_metadata": {
            "old_file": str(old_path),
            "new_file": str(new_path),
        },
        "metadata": {
            "changed": metadata_changed,
            "unchanged": metadata_unchanged,
            "fields": metadata_structured,
            "lines": metadata_lines,
        },
        "top_level": {
            "changed": top_level_changed,
            "unchanged": top_level_unchanged,
            "fields": top_level_structured,
            "lines": top_level_lines,
        },
        "signals": {
            "changed": signals_changed,
            "unchanged": signals_unchanged,
            "fields": signals_structured,
            "lines": signals_lines,
        },
        "assessment": {
            "changed": assessment_changed,
            "unchanged": assessment_unchanged,
            "fields": assessment_structured,
            "lines": assessment_lines,
        },
        "summary": {
            "metadata_changes": metadata_changed,
            "metadata_unchanged": metadata_unchanged,
            "result_changes": result_changed,
            "result_unchanged": result_unchanged,
            "total_changed_fields": total_changed,
            "total_unchanged_fields": total_unchanged,
            "behavioural_change_detected": behavioural_change_detected,
            "interpretation": interpretation,
        },
    }


def print_human_readable(comparison: dict[str, Any]) -> None:
    print("\nRun Comparison")
    print("==============")
    print(f"Old File: {comparison['comparison_metadata']['old_file']}")
    print(f"New File: {comparison['comparison_metadata']['new_file']}")

    print_section("Metadata")
    for line in comparison["metadata"]["lines"]:
        print(line)

    print_section("Top Level")
    for line in comparison["top_level"]["lines"]:
        print(line)

    print_section("Signals")
    for line in comparison["signals"]["lines"]:
        print(line)

    print_section("Assessment")
    for line in comparison["assessment"]["lines"]:
        print(line)

    summary = comparison["summary"]

    print_section("Summary")
    print(f"Metadata changes: {summary['metadata_changes']}")
    print(f"Metadata unchanged: {summary['metadata_unchanged']}")
    print(f"Result changes: {summary['result_changes']}")
    print(f"Result unchanged: {summary['result_unchanged']}")
    print(f"Total changed fields: {summary['total_changed_fields']}")
    print(f"Total unchanged fields: {summary['total_unchanged_fields']}")
    print(
        f"Behavioural change detected: {'yes' if summary['behavioural_change_detected'] else 'no'}"
    )
    print(f"Interpretation: {summary['interpretation']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare two CDE run outputs")
    parser.add_argument("old_run", help="Path to the older run JSON file")
    parser.add_argument("new_run", help="Path to the newer run JSON file")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print comparison as machine-readable JSON",
    )
    parser.add_argument(
        "--export",
        help="Path to save comparison JSON output",
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

    comparison = build_comparison(old_path, new_path)

    if args.export:
        export_path = Path(args.export)
        export_path.parent.mkdir(parents=True, exist_ok=True)
        with open(export_path, "w", encoding="utf-8") as f:
            json.dump(comparison, f, indent=2)
        print(f"Exported comparison -> {export_path}")

    if args.json:
        print(json.dumps(comparison, indent=2))
    else:
        print_human_readable(comparison)


if __name__ == "__main__":
    main()