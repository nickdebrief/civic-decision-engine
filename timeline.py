#!/usr/bin/env python3
"""
CDE Timeline Generator
Reads the audit log and produces a structured timeline of events
and transitions per case reference.
Detects the moment of change — the first point of behavioural deterioration.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


AUDIT_LOG_PATH = Path("audit_logs/civic_engine_audit_log.json")

LABEL_ORDER = ["Response", "Delayed response", "Partial engagement", "Resistance"]

CONDITION_ORDER = [
    "STABILITY_WITHOUT_CONFIRMATION",
    "PARTIAL_ENGAGEMENT",
    "ADMINISTRATIVE_CONTAINMENT",
    "CLOSURE_WITHOUT_RESOLUTION",
    "RESISTANCE",
]


def label_rank(label: str) -> int:
    try:
        return LABEL_ORDER.index(label)
    except ValueError:
        return -1


def condition_rank(condition: str) -> int:
    try:
        return CONDITION_ORDER.index(condition)
    except ValueError:
        return -1


def load_audit_log(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return json.loads(path.read_text())


def detect_moment_of_change(
    transitions: list[dict[str, Any]]
) -> dict[str, Any] | None:
    meaningful = [t for t in transitions if t["direction"] != "structural_update"]

    for i, t in enumerate(meaningful):
        if t["direction"] == "deteriorating":
            if i == 0 or meaningful[i - 1]["direction"] != "deteriorating":
                return t
    return None

def build_timeline(entries: list[dict[str, Any]]) -> dict[str, Any]:
    cases: dict[str, list[dict[str, Any]]] = {}

    for entry in entries:
        ref = entry.get("case", "unknown")
        if ref not in cases:
            cases[ref] = []
        cases[ref].append(entry)

    timeline: dict[str, Any] = {}

    for ref, events in cases.items():
        events_sorted = sorted(events, key=lambda e: e.get("timestamp", ""))

        transitions: list[dict[str, Any]] = []
        for i in range(1, len(events_sorted)):
            prev = events_sorted[i - 1]
            curr = events_sorted[i]

            prev_condition = prev.get("condition")
            curr_condition = curr.get("condition")

            index_change = (
                curr.get("behaviour_index", 0) - prev.get("behaviour_index", 0)
            )

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
                    if prev_condition is None or curr_condition is None:
                        direction = "structural_update"
                    else:
                        prev_condition_rank = condition_rank(prev_condition)
                        curr_condition_rank = condition_rank(curr_condition)

                        if curr_condition_rank > prev_condition_rank:
                            direction = "deteriorating"
                        elif curr_condition_rank < prev_condition_rank:
                            direction = "improving"
                        else:
                            direction = "stable"

            transitions.append({
                "from_event": prev.get("timestamp"),
                "to_event": curr.get("timestamp"),
                "from_label": prev.get("label"),
                "to_label": curr.get("label"),
                "from_condition": prev_condition,
                "to_condition": curr_condition,
                "from_index": prev.get("behaviour_index"),
                "to_index": curr.get("behaviour_index"),
                "index_change": index_change,
                "direction": direction,
            })

        moment_of_change = detect_moment_of_change(transitions)

        timeline[ref] = {
            "case_reference": ref,
            "event_count": len(events_sorted),
            "events": events_sorted,
            "transitions": transitions,
            "overall_trajectory": _overall_trajectory(events_sorted, transitions),
            "moment_of_change": moment_of_change,
        }

    return timeline


def _overall_trajectory(
    events: list[dict[str, Any]],
    transitions: list[dict[str, Any]],
) -> str:
    if len(events) < 2:
        return "single_event"

    meaningful = [t for t in transitions if t["direction"] != "structural_update"]

    if not meaningful:
        return "stable"

    directions = [t["direction"] for t in meaningful]

    if "deteriorating" in directions and "improving" not in directions:
        return "deteriorating"
    if "improving" in directions and "deteriorating" not in directions:
        return "improving"
    if all(d == "stable" for d in directions):
        return "stable"

    return "mixed"


def print_timeline(timeline: dict[str, Any]) -> None:
    print("\nCDE Case Timeline")
    print("=================")

    for ref, data in timeline.items():
        print(f"\nCase: {ref}")
        print(f"  Events     : {data['event_count']}")
        print(f"  Trajectory : {data['overall_trajectory']}")

        if data.get("moment_of_change"):
            m = data["moment_of_change"]
            print(
                f"\n  Moment of Change"
                f"\n    {m['from_event']} → {m['to_event']}  |  "
                f"{m['from_label']} → {m['to_label']}  |  "
                f"{m['from_condition']} → {m['to_condition']}  |  "
                f"index {m['from_index']} → {m['to_index']}"
            )

        print("\n  Events")
        for e in data["events"]:
            print(
                f"    {e.get('timestamp')}  |  "
                f"{e.get('label')}  |  "
                f"{e.get('condition')}  |  "
                f"index: {e.get('behaviour_index')}"
            )

        if data["transitions"]:
            print("\n  Transitions")
            for t in data["transitions"]:
                print(
                    f"    {t['from_event']} → {t['to_event']}  |  "
                    f"{t['from_label']} → {t['to_label']}  |  "
                    f"{t['from_condition']} → {t['to_condition']}  |  "
                    f"index {t['from_index']} → {t['to_index']}  |  "
                    f"{t['direction']}"
                )


def main() -> None:
    parser = argparse.ArgumentParser(description="CDE Timeline Generator")
    parser.add_argument(
        "--log",
        default=str(AUDIT_LOG_PATH),
        help="Path to audit log JSON file",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print timeline as JSON",
    )
    parser.add_argument(
        "--export",
        help="Path to export timeline JSON",
    )
    parser.add_argument(
        "--export-md",
        help="Path to export timeline as Markdown",
    )
    parser.add_argument(
        "--case",
        help="Filter timeline to a specific case reference",
    )

    args = parser.parse_args()

    entries = load_audit_log(Path(args.log))

    if not entries:
        print("No audit log entries found.")
        return

    timeline = build_timeline(entries)

    if args.case:
        if args.case not in timeline:
            print(f"Case reference not found: {args.case}")
            return
        timeline = {args.case: timeline[args.case]}

    if args.export:
        export_path = Path(args.export)
        export_path.parent.mkdir(parents=True, exist_ok=True)
        export_path.write_text(json.dumps(timeline, indent=2))
        print(f"Exported timeline -> {export_path}")

    if args.export_md:
        export_path = Path(args.export_md)
        export_path.parent.mkdir(parents=True, exist_ok=True)
        lines = ["# CDE Case Timeline", ""]

        for ref, data in timeline.items():
            lines += [
                f"## Case: {ref}",
                "",
                f"- **Events:** {data['event_count']}",
                f"- **Trajectory:** {data['overall_trajectory']}",
            ]

            if data.get("moment_of_change"):
                m = data["moment_of_change"]
                lines += [
                    "",
                    "### Moment of Change",
                    "",
                    (
                        f"- `{m['from_event']}` → `{m['to_event']}` — "
                        f"{m['from_label']} → {m['to_label']} — "
                        f"{m['from_condition']} → {m['to_condition']} — "
                        f"index {m['from_index']} → {m['to_index']}"
                    ),
                ]

            lines += ["", "### Events", ""]
            for e in data["events"]:
                lines.append(
                    f"- `{e.get('timestamp')}` — "
                    f"{e.get('label')} — "
                    f"{e.get('condition')} — "
                    f"index: {e.get('behaviour_index')}"
                )

            if data["transitions"]:
                lines += ["", "### Transitions", ""]
                for t in data["transitions"]:
                    lines.append(
                        f"- `{t['from_event']}` → `{t['to_event']}` — "
                        f"{t['from_label']} → {t['to_label']} — "
                        f"{t['from_condition']} → {t['to_condition']} — "
                        f"index {t['from_index']} → {t['to_index']} — "
                        f"{t['direction']}"
                    )

            lines.append("")

        export_path.write_text("\n".join(lines))
        print(f"Exported Markdown timeline -> {export_path}")

    if args.json:
        print(json.dumps(timeline, indent=2))
    else:
        print_timeline(timeline)


if __name__ == "__main__":
    main()