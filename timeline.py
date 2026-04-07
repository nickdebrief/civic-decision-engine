#!/usr/bin/env python3
"""
CDE Timeline Generator

Reads the audit log and produces a structured timeline of events
and transitions per case reference.

Detects:
- moment of change
- condition refinement
- behavioural direction
"""

from __future__ import annotations

import json
from pathlib import Path
from collections import defaultdict


AUDIT_LOG_PATH = Path("audit_logs/civic_engine_audit_log.json")


# ----------------------------
# Ranking helpers
# ----------------------------

LABEL_ORDER = [
    "Partial engagement",
    "Administrative containment",
    "Resistance",
]

CONDITION_ORDER = [
    "STABILITY_WITHOUT_CONFIRMATION",
    "ACKNOWLEDGEMENT_WITHOUT_ACTION",
    "TRANSFER_OF_BURDEN",
    "PARTIAL_ENGAGEMENT",
    "ADMINISTRATIVE_CONTAINMENT",
    "ESCALATION_WITHOUT_RESPONSE",
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


# ----------------------------
# Load audit log
# ----------------------------

def load_audit_log():
    if not AUDIT_LOG_PATH.exists():
        raise FileNotFoundError(f"Missing audit log: {AUDIT_LOG_PATH}")

    with open(AUDIT_LOG_PATH, "r") as f:
        return json.load(f)


# ----------------------------
# Build timeline
# ----------------------------

def build_timeline(audit_log):
    timeline = defaultdict(list)

    for entry in audit_log:
        case = entry.get("case")

        timeline[case].append({
            "timestamp": entry.get("timestamp"),
            "label": entry.get("label"),
            "condition": entry.get("condition"),
            "behaviour_index": entry.get("behaviour_index"),
        })

    return timeline


# ----------------------------
# Analyse transitions
# ----------------------------

def analyse_case(events):
    transitions = []

    for i in range(1, len(events)):
        prev = events[i - 1]
        curr = events[i]

        prev_condition = prev.get("condition")
        curr_condition = curr.get("condition")

        prev_index = prev.get("behaviour_index", 0)
        curr_index = curr.get("behaviour_index", 0)

        index_change = curr_index - prev_index

        # ----------------------------
        # Direction logic
        # ----------------------------

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
                # NEW: structural / refinement logic

                if prev_condition is None or curr_condition is None:
                    direction = "structural_update"

                elif (
                    prev.get("label") == curr.get("label")
                    and prev.get("behaviour_index") == curr.get("behaviour_index")
                    and prev_condition != curr_condition
                ):
                    direction = "condition_refined"

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
            "from_index": prev_index,
            "to_index": curr_index,
            "direction": direction,
        })

    return transitions


# ----------------------------
# Output
# ----------------------------

def print_timeline(timeline):
    print("\nCDE Case Timeline")
    print("=================\n")

    for case, events in timeline.items():
        print(f"Case: {case}")
        print(f"  Events     : {len(events)}")

        transitions = analyse_case(events)

        print(f"  Trajectory : mixed\n")

        if transitions:
                   moment = next(
            (t for t in transitions if t["direction"] == "deteriorating"),
            None,
        )

        if moment:
            print("  Moment of Change")
            print(
                f"    {moment['from_event']} → {moment['to_event']}  |  "
                f"{moment['from_label']} → {moment['to_label']}  |  "
                f"{moment['from_condition']} → {moment['to_condition']}"
            )
            print()

        print("  Events")
        for e in events:
            print(
                f"    {e['timestamp']}  |  {e['label']}  |  {e['condition']}  |  index: {e['behaviour_index']}"
            )

        print("\n  Transitions")
        for t in transitions:
            print(
                f"    {t['from_event']} → {t['to_event']}  |  "
                f"{t['from_label']} → {t['to_label']}  |  "
                f"{t['from_condition']} → {t['to_condition']}  |  "
                f"{t['direction']}"
            )

        print()


# ----------------------------
# Main
# ----------------------------

def main():
    audit_log = load_audit_log()
    timeline = build_timeline(audit_log)
    print_timeline(timeline)


if __name__ == "__main__":
    main()