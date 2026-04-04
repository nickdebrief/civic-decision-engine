import json
import sys
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
) -> tuple[int, int, list[str]]:
    changed = 0
    unchanged = 0
    lines: list[str] = []

    all_keys = sorted(set(old.keys()) | set(new.keys()))
    for key in all_keys:
        old_val = old.get(key)
        new_val = new.get(key)

        if isinstance(old_val, dict) and isinstance(new_val, dict):
            sub_changed, sub_unchanged, sub_lines = compare_dict(old_val, new_val)
            changed += sub_changed
            unchanged += sub_unchanged
            lines.extend(sub_lines)
        else:
            did_change, line = compare_values(key, old_val, new_val)
            lines.append(line)
            if did_change:
                changed += 1
            else:
                unchanged += 1

    return changed, unchanged, lines


def print_section(title: str) -> None:
    print(f"\n{title}")
    print("-" * len(title))


def main() -> None:
    if len(sys.argv) != 3:
        print("Usage: python compare_runs.py <old_run.json> <new_run.json>")
        raise SystemExit(1)

    old_path = Path(sys.argv[1])
    new_path = Path(sys.argv[2])

    if not old_path.exists():
        print(f"Error: file not found -> {old_path}")
        raise SystemExit(1)

    if not new_path.exists():
        print(f"Error: file not found -> {new_path}")
        raise SystemExit(1)

    old_payload = load_json(str(old_path))
    new_payload = load_json(str(new_path))

    old_meta = old_payload.get("run_metadata", {})
    new_meta = new_payload.get("run_metadata", {})

    old_result = get_first_result(old_payload)
    new_result = get_first_result(new_payload)

    metadata_changed = 0
    metadata_unchanged = 0
    result_changed = 0
    result_unchanged = 0

    print("\nRun Comparison")
    print("==============")
    print(f"Old File: {old_path}")
    print(f"New File: {new_path}")

    print_section("Metadata")
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
        print(line)
        if did_change:
            metadata_changed += 1
        else:
            metadata_unchanged += 1

    print_section("Top Level")
    top_fields = [
        ("system_reference", old_result.get("system_reference"), new_result.get("system_reference")),
        ("title", old_result.get("title"), new_result.get("title")),
        ("domain", old_result.get("domain"), new_result.get("domain")),
        ("declared_purpose", old_result.get("declared_purpose"), new_result.get("declared_purpose")),
    ]

    for label, old_val, new_val in top_fields:
        did_change, line = compare_values(label, old_val, new_val)
        print(line)
        if did_change:
            result_changed += 1
        else:
            result_unchanged += 1

    print_section("Signals")
    changed, unchanged, lines = compare_dict(
        old_result.get("signals", {}),
        new_result.get("signals", {}),
    )
    for line in lines:
        print(line)
    result_changed += changed
    result_unchanged += unchanged

    print_section("Assessment")
    changed, unchanged, lines = compare_dict(
        old_result.get("assessment", {}),
        new_result.get("assessment", {}),
    )
    for line in lines:
        print(line)
    result_changed += changed
    result_unchanged += unchanged

    total_changed = metadata_changed + result_changed
    total_unchanged = metadata_unchanged + result_unchanged

    print_section("Summary")
    print(f"Metadata changes: {metadata_changed}")
    print(f"Metadata unchanged: {metadata_unchanged}")
    print(f"Result changes: {result_changed}")
    print(f"Result unchanged: {result_unchanged}")
    print(f"Total changed fields: {total_changed}")
    print(f"Total unchanged fields: {total_unchanged}")

    if result_changed == 0:
        print("Behavioural change detected: no")
    else:
        print("Behavioural change detected: yes")

    if metadata_changed > 0 and result_changed == 0:
        print("Interpretation: new run recorded, but no result-level change detected.")
    elif result_changed > 0:
        print("Interpretation: result-level changes detected between runs.")
    else:
        print("Interpretation: no changes detected.")
        

if __name__ == "__main__":
    main()