#!/usr/bin/env python3
"""
Civic Recall Pipeline Decision Engine — Version 7
Author: Nick Moloney (concept)

New in Version 7:
- institution-specific scoring profiles
- timeline anomaly detection
- evidence chronology consistency checks
- interactive case linking
- portfolio-level dashboard markdown export
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Tuple
from datetime import date, datetime
from pathlib import Path
import json
import textwrap
import re
import csv

@dataclass
class CivicActor:
    name: str
    actor_type: str
    role_in_case: str
    incentive_or_pressure: str
    likely_behaviour: str

@dataclass
class EvidenceItem:
    label: str
    evidence_type: str
    relevance: str
    strength: str
    linked_timeline_label: str = ""

@dataclass
class DeadlineItem:
    label: str
    due_date: str
    consequence: str

@dataclass
class TimelineEvent:
    event_date: str
    label: str
    event_type: str
    description: str

@dataclass
class EscalationPath:
    name: str
    route_type: str
    trigger: str
    likely_response: str
    time_horizon: str
    risk_level: str
    jurisdiction_fit: str = ""
    evidence_readiness: str = ""
    deadline_pressure: str = ""
    outcome_status: str = ""
    outcome_note: str = ""

@dataclass
class LinkedCaseRef:
    strike_reference: str
    relationship_type: str
    note: str

@dataclass
class CivicRecallCase:
    strike_reference: str
    case_title: str
    civic_domain: str
    decision_trigger: str
    recall_question: str
    user_priority: str
    desired_outcome: str
    urgency: str
    institutions: List[str] = field(default_factory=list)
    rules_or_procedures: List[str] = field(default_factory=list)
    constraints: List[str] = field(default_factory=list)
    actors: List[CivicActor] = field(default_factory=list)
    evidence_bundle: List[EvidenceItem] = field(default_factory=list)
    deadlines: List[DeadlineItem] = field(default_factory=list)
    timeline: List[TimelineEvent] = field(default_factory=list)
    escalation_paths: List[EscalationPath] = field(default_factory=list)
    linked_cases: List[LinkedCaseRef] = field(default_factory=list)
    structural_insight: str = ""
    personal_positioning: str = ""
    decision_note: str = ""
    learning_capture: str = ""

def ask(prompt: str) -> str:
    return input(prompt).strip()

def ask_list(prompt: str) -> List[str]:
    print(prompt)
    print("Enter one item per line. Press Enter on a blank line when finished.")
    items: List[str] = []
    while True:
        item = input("> ").strip()
        if not item:
            break
        items.append(item)
    return items

def ask_actor() -> CivicActor:
    print("\nAdd civic actor / institution record")
    return CivicActor(
        name=ask("Name: "),
        actor_type=ask("Actor type: "),
        role_in_case=ask("Role in this case: "),
        incentive_or_pressure=ask("Main incentive / pressure: "),
        likely_behaviour=ask("Likely behaviour under that incentive: "),
    )

def ask_evidence() -> EvidenceItem:
    print("\nAdd evidence item")
    return EvidenceItem(
        label=ask("Evidence label: "),
        evidence_type=ask("Evidence type: "),
        relevance=ask("Why is this relevant? "),
        strength=ask("Evidence strength (high / medium / low): "),
        linked_timeline_label=ask("Linked timeline label if any: "),
    )

def ask_deadline() -> DeadlineItem:
    print("\nAdd deadline item")
    return DeadlineItem(
        label=ask("Deadline label: "),
        due_date=ask("Due date (YYYY-MM-DD): "),
        consequence=ask("What happens if this is missed? "),
    )

def ask_timeline_event() -> TimelineEvent:
    print("\nAdd timeline / chronology event")
    return TimelineEvent(
        event_date=ask("Event date (YYYY-MM-DD): "),
        label=ask("Short event label: "),
        event_type=ask("Event type: "),
        description=ask("Description: "),
    )

def ask_path() -> EscalationPath:
    print("\nAdd escalation / response path")
    return EscalationPath(
        name=ask("Path name: "),
        route_type=ask("Route type: "),
        trigger=ask("What triggers this path? "),
        likely_response=ask("Likely system response: "),
        time_horizon=ask("Time horizon (short / medium / long): "),
        risk_level=ask("Risk level (low / medium / high): "),
        jurisdiction_fit=ask("Jurisdiction fit (yes / partial / no): "),
        evidence_readiness=ask("Evidence readiness (high / medium / low): "),
        deadline_pressure=ask("Deadline pressure (high / medium / low): "),
        outcome_status=ask("Outcome status if known (successful / partial / failed / unknown): "),
        outcome_note=ask("Outcome note if known: "),
    )

def ask_linked_case() -> LinkedCaseRef:
    print("\nAdd linked case reference")
    return LinkedCaseRef(
        strike_reference=ask("Linked strike reference: "),
        relationship_type=ask("Relationship type (same institution / same issue / evidence overlap / escalation lineage / other): "),
        note=ask("Link note: "),
    )

def capture_case() -> CivicRecallCase:
    print("\n=== Civic Recall Pipeline Decision Engine — Version 7 ===\n")
    case = CivicRecallCase(
        strike_reference=ask("Strike reference / recall ID: "),
        case_title=ask("Case title: "),
        civic_domain=ask("Civic domain: "),
        decision_trigger=ask("Decision trigger: "),
        recall_question=ask("Recall question ('What should I do next?'): "),
        user_priority=ask("Priority to protect: "),
        desired_outcome=ask("Desired outcome: "),
        urgency=ask("Urgency (low / medium / high): "),
        institutions=ask_list("\nList the institutions / bodies involved:"),
        rules_or_procedures=ask_list("\nList governing procedures, deadlines, routes, or formal rules:"),
        constraints=ask_list("\nList active constraints:"),
    )
    while ask("\nAdd actor record? (y/n): ").lower() == "y":
        case.actors.append(ask_actor())
    while ask("\nAdd evidence item? (y/n): ").lower() == "y":
        case.evidence_bundle.append(ask_evidence())
    while ask("\nAdd deadline item? (y/n): ").lower() == "y":
        case.deadlines.append(ask_deadline())
    while ask("\nAdd timeline event? (y/n): ").lower() == "y":
        case.timeline.append(ask_timeline_event())
    while ask("\nAdd escalation / response path? (y/n): ").lower() == "y":
        case.escalation_paths.append(ask_path())
    while ask("\nAdd linked case reference? (y/n): ").lower() == "y":
        case.linked_cases.append(ask_linked_case())
    case.structural_insight = ask("\nStructural insight: ")
    case.personal_positioning = ask("Personal positioning: ")
    case.decision_note = ask("Decision note: ")
    case.learning_capture = ask("Learning capture: ")
    return case

def safe_parse_date(s: str) -> Optional[date]:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None

def deadline_status(deadline: DeadlineItem) -> str:
    d = safe_parse_date(deadline.due_date)
    if d is None:
        return "invalid-date"
    today = date.today()
    delta = (d - today).days
    if delta < 0:
        return f"overdue by {-delta} day(s)"
    if delta == 0:
        return "due today"
    if delta <= 7:
        return f"due soon ({delta} day(s))"
    return f"upcoming ({delta} day(s))"

def score_path(path: EscalationPath) -> int:
    score = 0
    jurisdiction_map = {"yes": 4, "partial": 2, "no": 0}
    evidence_map = {"high": 3, "medium": 2, "low": 1}
    deadline_map = {"low": 2, "medium": 1, "high": 0}
    risk_penalty = {"low": 0, "medium": -1, "high": -2}
    time_bonus = {"short": 2, "medium": 1, "long": 0}
    outcome_bonus = {"successful": 2, "partial": 1, "failed": -1, "unknown": 0, "": 0}
    score += jurisdiction_map.get(path.jurisdiction_fit.lower(), 0)
    score += evidence_map.get(path.evidence_readiness.lower(), 0)
    score += deadline_map.get(path.deadline_pressure.lower(), 0)
    score += time_bonus.get(path.time_horizon.lower(), 0)
    score += risk_penalty.get(path.risk_level.lower(), 0)
    score += outcome_bonus.get(path.outcome_status.lower(), 0)
    return score

def rank_paths(paths: List[EscalationPath]) -> List[Tuple[EscalationPath, int]]:
    ranked = [(path, score_path(path)) for path in paths]
    ranked.sort(key=lambda item: item[1], reverse=True)
    return ranked

def check_jurisdiction(case: CivicRecallCase) -> List[str]:
    notes: List[str] = []
    for path in case.escalation_paths:
        fit = path.jurisdiction_fit.lower()
        if fit == "no":
            notes.append(f"{path.name}: outside or weakly aligned to remit.")
        elif fit == "partial":
            notes.append(f"{path.name}: partial fit — tighten framing and remit alignment.")
        elif fit == "yes":
            notes.append(f"{path.name}: appears aligned with jurisdiction.")
        else:
            notes.append(f"{path.name}: jurisdiction fit not assessed.")
    return notes

def evidence_strength_score(case: CivicRecallCase) -> Tuple[int, str]:
    weights = {"high": 3, "medium": 2, "low": 1}
    if not case.evidence_bundle:
        return 0, "No evidence captured."
    total = sum(weights.get(item.strength.lower(), 0) for item in case.evidence_bundle)
    avg = total / len(case.evidence_bundle)
    if avg >= 2.5:
        label = "Strong evidence bundle"
    elif avg >= 1.75:
        label = "Moderate evidence bundle"
    else:
        label = "Weak evidence bundle"
    return total, label

def timeline_sorted(case: CivicRecallCase) -> List[TimelineEvent]:
    def sort_key(item: TimelineEvent):
        parsed = safe_parse_date(item.event_date)
        return (parsed is None, parsed or date.max, item.label.lower())
    return sorted(case.timeline, key=sort_key)

def generate_framing_note(path: EscalationPath) -> str:
    fit = path.jurisdiction_fit.lower()
    evidence = path.evidence_readiness.lower()
    deadline = path.deadline_pressure.lower()
    notes: List[str] = []
    if fit == "yes":
        notes.append("Frame the issue directly within the stated remit.")
    elif fit == "partial":
        notes.append("Narrow the issue and translate it into remit-aligned language.")
    else:
        notes.append("This path appears weak on remit; avoid overcommitting without reframing.")
    if evidence == "high":
        notes.append("Lead with the strongest evidence and chronology.")
    elif evidence == "medium":
        notes.append("Tighten the bundle and remove weaker material before escalation.")
    else:
        notes.append("Build the evidence bundle further before relying on this path.")
    if deadline == "high":
        notes.append("Preserve procedural footing immediately, even if only with a holding response.")
    elif deadline == "medium":
        notes.append("Balance speed with cleaner framing.")
    else:
        notes.append("Use available time to improve clarity, chronology, and structure.")
    return " ".join(notes)

def normalized_tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))

def similarity_score(case_a: CivicRecallCase, case_b: CivicRecallCase) -> int:
    score = 0
    if case_a.civic_domain.lower() == case_b.civic_domain.lower():
        score += 4
    inst_a = {i.lower() for i in case_a.institutions}
    inst_b = {i.lower() for i in case_b.institutions}
    score += min(len(inst_a & inst_b), 5)
    routes_a = {p.route_type.lower() for p in case_a.escalation_paths}
    routes_b = {p.route_type.lower() for p in case_b.escalation_paths}
    score += min(len(routes_a & routes_b), 3)
    tok_a = normalized_tokens(case_a.user_priority + " " + case_a.decision_trigger)
    tok_b = normalized_tokens(case_b.user_priority + " " + case_b.decision_trigger)
    score += min(len(tok_a & tok_b), 5)
    return score

def evidence_gap_detection(case: CivicRecallCase) -> List[str]:
    gaps: List[str] = []
    if not case.evidence_bundle:
        gaps.append("No evidence bundle recorded.")
    else:
        has_timeline = any(item.evidence_type.lower() == "timeline" for item in case.evidence_bundle)
        has_letter_email = any(item.evidence_type.lower() in {"letter", "email"} for item in case.evidence_bundle)
        if not has_timeline and not case.timeline:
            gaps.append("No chronology source detected — add a timeline or chronology note.")
        if not has_letter_email:
            gaps.append("No primary correspondence evidence detected — add letters or emails where possible.")
        low_count = sum(1 for item in case.evidence_bundle if item.strength.lower() == "low")
        if low_count >= max(1, len(case.evidence_bundle) // 2):
            gaps.append("A large share of the evidence bundle is low-strength — strengthen with primary records.")
    if not case.actors:
        gaps.append("No actor mapping recorded — incentives and likely behaviour remain under-mapped.")
    if not case.escalation_paths:
        gaps.append("No escalation paths recorded — no structured next-step comparison is possible.")
    partial_or_no = [p for p in case.escalation_paths if p.jurisdiction_fit.lower() in {"partial", "no"}]
    if case.escalation_paths and len(partial_or_no) == len(case.escalation_paths):
        gaps.append("No escalation path currently shows strong jurisdiction fit.")
    return gaps

def jurisdiction_template(route_type: str) -> str:
    rt = route_type.lower()
    templates = {
        "internal complaint": "Template focus: preserve procedural footing, identify the exact issue, state the remedy sought, and anchor the chronology tightly.",
        "external oversight": "Template focus: frame strictly within remit, define the complaint in narrow terms, attach only the strongest evidence, and show prior internal engagement.",
        "legal": "Template focus: identify legal issue, timeline, documentary record, remedy sought, and costs / risk considerations.",
        "media": "Template focus: distinguish public-interest narrative from formal remedy, avoid overclaiming, and anchor statements in verifiable records.",
        "public record": "Template focus: preserve chronology, evidence links, dates, and official responses in a neutral, auditable format.",
    }
    return templates.get(rt, "Template focus: define the issue clearly, state the route, show the chronology, and anchor claims in evidence.")

def recommended_next_action(case: CivicRecallCase) -> str:
    if not case.escalation_paths:
        return "No recommendation available because no escalation paths are recorded."
    ranked = rank_paths(case.escalation_paths)
    top_path, top_score = ranked[0]
    actions: List[str] = []
    actions.append(f"Highest-ranked path: {top_path.name} (score {top_score}).")
    actions.append(f"Reason: jurisdiction fit = {top_path.jurisdiction_fit}, evidence readiness = {top_path.evidence_readiness}, deadline pressure = {top_path.deadline_pressure}.")
    gaps = evidence_gap_detection(case)
    if gaps:
        actions.append("Before acting, close the most important evidence / structure gaps.")
        actions.extend([f"- {gap}" for gap in gaps[:3]])
    actions.append(f"Recommended framing: {generate_framing_note(top_path)}")
    actions.append(f"Jurisdiction template: {jurisdiction_template(top_path.route_type)}")
    return "\n".join(actions)

def load_case_memory(filepath: str) -> Optional[CivicRecallCase]:
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except FileNotFoundError:
        print(f"File not found: {filepath}")
        return None
    except json.JSONDecodeError:
        print(f"Could not parse JSON: {filepath}")
        return None
    try:
        actors = [CivicActor(**a) for a in payload.get("actors", [])]
        evidence = []
        for e in payload.get("evidence_bundle", []):
            if "strength" not in e:
                e["strength"] = "medium"
            if "linked_timeline_label" not in e:
                e["linked_timeline_label"] = ""
            evidence.append(EvidenceItem(**e))
        deadlines = [DeadlineItem(**d) for d in payload.get("deadlines", [])]
        timeline = [TimelineEvent(**t) for t in payload.get("timeline", [])]
        paths = []
        for p in payload.get("escalation_paths", []):
            if "outcome_status" not in p:
                p["outcome_status"] = "unknown"
            if "outcome_note" not in p:
                p["outcome_note"] = ""
            paths.append(EscalationPath(**p))
        links = [LinkedCaseRef(**l) for l in payload.get("linked_cases", [])]
        return CivicRecallCase(
            strike_reference=payload["strike_reference"],
            case_title=payload["case_title"],
            civic_domain=payload["civic_domain"],
            decision_trigger=payload["decision_trigger"],
            recall_question=payload["recall_question"],
            user_priority=payload["user_priority"],
            desired_outcome=payload["desired_outcome"],
            urgency=payload["urgency"],
            institutions=payload.get("institutions", []),
            rules_or_procedures=payload.get("rules_or_procedures", []),
            constraints=payload.get("constraints", []),
            actors=actors,
            evidence_bundle=evidence,
            deadlines=deadlines,
            timeline=timeline,
            escalation_paths=paths,
            linked_cases=links,
            structural_insight=payload.get("structural_insight", ""),
            personal_positioning=payload.get("personal_positioning", ""),
            decision_note=payload.get("decision_note", ""),
            learning_capture=payload.get("learning_capture", ""),
        )
    except KeyError as exc:
        print(f"Missing required field in JSON: {exc}")
        return None

def load_case_directory(directory: str) -> List[CivicRecallCase]:
    cases: List[CivicRecallCase] = []
    folder = Path(directory)
    if not folder.exists() or not folder.is_dir():
        return cases
    for path in folder.glob("*.json"):
        case = load_case_memory(str(path))
        if case is not None:
            cases.append(case)
    return cases

def pattern_recall(cases: List[CivicRecallCase]) -> str:
    if not cases:
        return "No prior cases loaded for pattern recall."
    domain_count: Dict[str, int] = {}
    institution_count: Dict[str, int] = {}
    route_count: Dict[str, int] = {}
    for case in cases:
        domain_count[case.civic_domain] = domain_count.get(case.civic_domain, 0) + 1
        for inst in case.institutions:
            institution_count[inst] = institution_count.get(inst, 0) + 1
        for path in case.escalation_paths:
            route_count[path.route_type] = route_count.get(path.route_type, 0) + 1
    def top_items(d: Dict[str, int], n: int = 5):
        return sorted(d.items(), key=lambda x: (-x[1], x[0]))[:n]
    lines = ["PATTERN RECALL ACROSS PRIOR CASES", f"Loaded cases: {len(cases)}", "\nTop civic domains:"]
    for k, v in top_items(domain_count):
        lines.append(f"- {k}: {v}")
    lines.append("\nTop institutions:")
    for k, v in top_items(institution_count):
        lines.append(f"- {k}: {v}")
    lines.append("\nTop escalation route types:")
    for k, v in top_items(route_count):
        lines.append(f"- {k}: {v}")
    return "\n".join(lines)

def multi_case_learning_summary(cases: List[CivicRecallCase]) -> str:
    if not cases:
        return "No cases loaded for multi-case learning summary."
    urgency_count: Dict[str, int] = {}
    evidence_totals: List[int] = []
    gap_counts = 0
    for case in cases:
        urgency_count[case.urgency] = urgency_count.get(case.urgency, 0) + 1
        score, _ = evidence_strength_score(case)
        evidence_totals.append(score)
        if evidence_gap_detection(case):
            gap_counts += 1
    avg_evidence = sum(evidence_totals) / len(evidence_totals) if evidence_totals else 0
    lines = ["MULTI-CASE LEARNING SUMMARY", f"Loaded cases: {len(cases)}", f"Average evidence strength score: {avg_evidence:.2f}", f"Cases with one or more detected gaps: {gap_counts}", "\nUrgency distribution:"]
    for k, v in sorted(urgency_count.items(), key=lambda x: x[0]):
        lines.append(f"- {k}: {v}")
    return "\n".join(lines)

def institution_behaviour_memory(cases: List[CivicRecallCase]) -> str:
    if not cases:
        return "No cases loaded for institution behaviour memory."
    memory: Dict[str, Dict[str, int]] = {}
    for case in cases:
        for actor in case.actors:
            key = actor.name
            if key not in memory:
                memory[key] = {}
            behaviour = actor.likely_behaviour.strip() or "unspecified"
            memory[key][behaviour] = memory[key].get(behaviour, 0) + 1
    lines = ["WEIGHTED INSTITUTION BEHAVIOUR MEMORY"]
    for inst, behaviours in sorted(memory.items()):
        lines.append(f"\n{inst}")
        ranked = sorted(behaviours.items(), key=lambda x: (-x[1], x[0]))
        for behaviour, count in ranked[:5]:
            lines.append(f"- {behaviour}: {count}")
    return "\n".join(lines)

def institution_scoring_profiles(cases: List[CivicRecallCase]) -> str:
    if not cases:
        return "No cases loaded for institution-specific scoring profiles."
    profiles: Dict[str, Dict[str, int]] = {}
    for case in cases:
        for actor in case.actors:
            name = actor.name
            if name not in profiles:
                profiles[name] = {"cases": 0, "high_evidence_cases": 0, "deadline_cases": 0}
            profiles[name]["cases"] += 1
            if any(e.strength.lower() == "high" for e in case.evidence_bundle):
                profiles[name]["high_evidence_cases"] += 1
            if case.deadlines:
                profiles[name]["deadline_cases"] += 1
    lines = ["INSTITUTION-SPECIFIC SCORING PROFILES"]
    for inst, stats in sorted(profiles.items()):
        lines.append(f"\n{inst}")
        lines.append(f"- cases observed: {stats['cases']}")
        lines.append(f"- high-evidence case presence: {stats['high_evidence_cases']}")
        lines.append(f"- deadline pressure presence: {stats['deadline_cases']}")
    return "\n".join(lines)

def path_outcome_feedback(cases: List[CivicRecallCase]) -> str:
    if not cases:
        return "No cases loaded for path outcome feedback."
    route_memory: Dict[str, Dict[str, int]] = {}
    for case in cases:
        for path in case.escalation_paths:
            rt = path.route_type or "unknown"
            if rt not in route_memory:
                route_memory[rt] = {"successful": 0, "partial": 0, "failed": 0, "unknown": 0}
            status = (path.outcome_status or "unknown").lower()
            if status not in route_memory[rt]:
                status = "unknown"
            route_memory[rt][status] += 1
    lines = ["PATH OUTCOME FEEDBACK LOOPS"]
    for route_type, stats in sorted(route_memory.items()):
        lines.append(f"\n{route_type}")
        for status, count in stats.items():
            lines.append(f"- {status}: {count}")
    return "\n".join(lines)

def cross_case_similarity(target_case: CivicRecallCase, cases: List[CivicRecallCase], top_n: int = 5) -> str:
    if not cases:
        return "No prior cases loaded for similarity matching."
    scored: List[Tuple[CivicRecallCase, int]] = []
    for case in cases:
        if case.strike_reference == target_case.strike_reference:
            continue
        scored.append((case, similarity_score(target_case, case)))
    if not scored:
        return "No comparable prior cases found."
    scored.sort(key=lambda item: item[1], reverse=True)
    lines = ["CROSS-CASE SIMILARITY MATCHING"]
    for idx, (case, score) in enumerate(scored[:top_n], start=1):
        lines.append(f"{idx}. {case.strike_reference} | {case.case_title} — similarity score {score}")
        lines.append(f"   domain: {case.civic_domain}")
        if case.institutions:
            lines.append(f"   institutions: {', '.join(case.institutions[:4])}")
    return "\n".join(lines)

def timeline_anomaly_detection(case: CivicRecallCase) -> str:
    if not case.timeline:
        return "TIMELINE ANOMALY DETECTION\nNo timeline events captured."
    anomalies: List[str] = []
    sorted_events = timeline_sorted(case)
    invalid_dates = [e.label for e in case.timeline if safe_parse_date(e.event_date) is None]
    for label in invalid_dates:
        anomalies.append(f"Invalid event date detected: {label}")
    for i in range(1, len(sorted_events)):
        prev = safe_parse_date(sorted_events[i - 1].event_date)
        curr = safe_parse_date(sorted_events[i].event_date)
        if prev and curr and curr < prev:
            anomalies.append(f"Out-of-order chronology between '{sorted_events[i - 1].label}' and '{sorted_events[i].label}'.")
    labels = [e.label.lower() for e in case.timeline]
    if len(labels) != len(set(labels)):
        anomalies.append("Duplicate timeline labels detected.")
    if not anomalies:
        return "TIMELINE ANOMALY DETECTION\nNo major timeline anomalies detected."
    return "TIMELINE ANOMALY DETECTION\n" + "\n".join(f"- {a}" for a in anomalies)

def evidence_chronology_consistency(case: CivicRecallCase) -> str:
    if not case.evidence_bundle:
        return "EVIDENCE / CHRONOLOGY CONSISTENCY\nNo evidence bundle captured."
    timeline_labels = {e.label.lower() for e in case.timeline}
    issues: List[str] = []
    for item in case.evidence_bundle:
        if item.linked_timeline_label:
            if item.linked_timeline_label.lower() not in timeline_labels:
                issues.append(f"{item.label}: linked timeline label '{item.linked_timeline_label}' not found.")
    if not case.timeline and any(item.linked_timeline_label for item in case.evidence_bundle):
        issues.append("Evidence items reference timeline labels but no timeline exists.")
    if not issues:
        return "EVIDENCE / CHRONOLOGY CONSISTENCY\nNo major evidence / chronology inconsistencies detected."
    return "EVIDENCE / CHRONOLOGY CONSISTENCY\n" + "\n".join(f"- {i}" for i in issues)

def generate_recall_map(case: CivicRecallCase) -> str:
    lines: List[str] = []
    lines.append(f"RECALL RECORD: {case.strike_reference}")
    lines.append(f"CASE TITLE: {case.case_title}")
    lines.append(f"CIVIC DOMAIN: {case.civic_domain}\n")
    lines.append("DECISION TRIGGER")
    lines.append(f"  -> {case.decision_trigger}\n")
    lines.append("RECALL QUESTION")
    lines.append(f"  -> {case.recall_question}\n")
    lines.append("PRIORITY TO PROTECT")
    lines.append(f"  -> {case.user_priority}\n")
    lines.append("DESIRED OUTCOME")
    lines.append(f"  -> {case.desired_outcome}\n")
    lines.append("INSTITUTIONAL FIELD")
    for inst in case.institutions or ["none recorded"]:
        lines.append(f"  - {inst}")
    lines.append("")
    lines.append("PROCEDURES / RULES / DEADLINES")
    for rule in case.rules_or_procedures or ["none recorded"]:
        lines.append(f"  - {rule}")
    lines.append("")
    lines.append("ACTIVE CONSTRAINTS")
    for c in case.constraints or ["none recorded"]:
        lines.append(f"  - {c}")
    lines.append("")
    lines.append("ACTORS -> INCENTIVES -> LIKELY BEHAVIOUR")
    if case.actors:
        for actor in case.actors:
            lines.append(f"  {actor.name} [{actor.actor_type}]")
            lines.append(f"    role: {actor.role_in_case}")
            lines.append(f"    incentive / pressure: {actor.incentive_or_pressure}")
            lines.append(f"    likely behaviour: {actor.likely_behaviour}")
    else:
        lines.append("  No actor records captured")
    lines.append("")
    lines.append("EVIDENCE BUNDLE")
    if case.evidence_bundle:
        for item in case.evidence_bundle:
            lines.append(f"  {item.label} [{item.evidence_type}]")
            lines.append(f"    relevance: {item.relevance}")
            lines.append(f"    strength: {item.strength}")
            if item.linked_timeline_label:
                lines.append(f"    linked timeline: {item.linked_timeline_label}")
    else:
        lines.append("  No evidence captured")
    lines.append("")
    lines.append("DEADLINE TRACKER")
    if case.deadlines:
        for dl in case.deadlines:
            lines.append(f"  {dl.label} -> {dl.due_date} ({deadline_status(dl)})")
            lines.append(f"    consequence: {dl.consequence}")
    else:
        lines.append("  No deadlines captured")
    lines.append("")
    lines.append("TIMELINE / CHRONOLOGY")
    if case.timeline:
        for event in timeline_sorted(case):
            lines.append(f"  {event.event_date} | {event.label} [{event.event_type}]")
            lines.append(f"    {event.description}")
    else:
        lines.append("  No timeline events captured")
    lines.append("")
    lines.append("ESCALATION / RESPONSE PATHS")
    if case.escalation_paths:
        for path in case.escalation_paths:
            lines.append(f"  {path.name} [{path.route_type}]")
            lines.append(f"    trigger: {path.trigger}")
            lines.append(f"    likely response: {path.likely_response}")
            lines.append(f"    time horizon: {path.time_horizon}")
            lines.append(f"    risk: {path.risk_level}")
            lines.append(f"    jurisdiction fit: {path.jurisdiction_fit}")
            lines.append(f"    evidence readiness: {path.evidence_readiness}")
            lines.append(f"    deadline pressure: {path.deadline_pressure}")
            lines.append(f"    outcome status: {path.outcome_status}")
            if path.outcome_note:
                lines.append(f"    outcome note: {path.outcome_note}")
    else:
        lines.append("  No paths captured")
    lines.append("")
    lines.append("LINKED CASES")
    if case.linked_cases:
        for link in case.linked_cases:
            lines.append(f"  {link.strike_reference} [{link.relationship_type}]")
            lines.append(f"    note: {link.note}")
    else:
        lines.append("  No linked cases recorded")
    lines.append("")
    lines.append("STRUCTURAL INSIGHT")
    lines.append(f"  -> {case.structural_insight or 'Not yet captured'}\n")
    lines.append("PERSONAL POSITIONING")
    lines.append(f"  -> {case.personal_positioning or 'Not yet captured'}\n")
    lines.append("DECISION NOTE")
    lines.append(f"  -> {case.decision_note or 'Not yet captured'}\n")
    lines.append("LEARNING CAPTURE")
    lines.append(f"  -> {case.learning_capture or 'Not yet captured'}")
    return "\n".join(lines)

def generate_case_dashboard(case: CivicRecallCase) -> str:
    evidence_total, evidence_label = evidence_strength_score(case)
    gaps = evidence_gap_detection(case)
    top_path = rank_paths(case.escalation_paths)[0][0].name if case.escalation_paths else "none"
    lines = [
        "CASE DASHBOARD",
        f"- Strike reference: {case.strike_reference}",
        f"- Domain: {case.civic_domain}",
        f"- Urgency: {case.urgency}",
        f"- Institutions: {len(case.institutions)}",
        f"- Actors: {len(case.actors)}",
        f"- Evidence items: {len(case.evidence_bundle)}",
        f"- Evidence score: {evidence_total} ({evidence_label})",
        f"- Deadlines: {len(case.deadlines)}",
        f"- Timeline events: {len(case.timeline)}",
        f"- Escalation paths: {len(case.escalation_paths)}",
        f"- Linked cases: {len(case.linked_cases)}",
        f"- Highest-ranked path: {top_path}",
        f"- Detected gaps: {len(gaps)}",
    ]
    return "\n".join(lines)

def generate_ascii_pipeline(case: CivicRecallCase) -> str:
    path_names = " | ".join(path.name for path in case.escalation_paths) if case.escalation_paths else "paths not yet mapped"
    actor_names = ", ".join(actor.name for actor in case.actors) if case.actors else "actors not yet mapped"
    return textwrap.dedent(f"""
    DECISION TRIGGER
      ↓
    {case.decision_trigger}
      ↓
    RECALL QUESTION
      ↓
    {case.recall_question}
      ↓
    PRIORITY TO PROTECT
      ↓
    {case.user_priority}
      ↓
    SYSTEM FIELD
      ↓
    Institutions / Procedures / Constraints
      ↓
    {actor_names}
      ↓
    EVIDENCE + TIMELINE + DEADLINES
      ↓
    STRUCTURAL INSIGHT
      ↓
    ESCALATION PATHS
      ↓
    {path_names}
      ↓
    DECISION
      ↓
    LEARNING CAPTURE
    """).strip()

def generate_path_ranking(case: CivicRecallCase) -> str:
    if not case.escalation_paths:
        return "No escalation paths captured."
    ranked = rank_paths(case.escalation_paths)
    lines = ["NEXT-PATH RANKING"]
    for idx, (path, score) in enumerate(ranked, start=1):
        lines.append(f"{idx}. {path.name} — score {score}")
        lines.append(f"   route: {path.route_type}")
        lines.append(f"   jurisdiction fit: {path.jurisdiction_fit}")
        lines.append(f"   evidence readiness: {path.evidence_readiness}")
        lines.append(f"   deadline pressure: {path.deadline_pressure}")
        lines.append(f"   likely response: {path.likely_response}")
        lines.append(f"   outcome status: {path.outcome_status}")
    return "\n".join(lines)

def generate_jurisdiction_report(case: CivicRecallCase) -> str:
    notes = check_jurisdiction(case)
    return "JURISDICTION CHECK\n" + "\n".join(f"- {n}" for n in notes) if notes else "No jurisdiction notes available."

def generate_evidence_report(case: CivicRecallCase) -> str:
    total, label = evidence_strength_score(case)
    return "\n".join(["EVIDENCE STRENGTH REPORT", f"Total strength score: {total}", f"Assessment: {label}"])

def generate_gap_report(case: CivicRecallCase) -> str:
    gaps = evidence_gap_detection(case)
    if not gaps:
        return "EVIDENCE / STRUCTURE GAP REPORT\nNo major gaps detected."
    lines = ["EVIDENCE / STRUCTURE GAP REPORT"]
    lines.extend(f"- {gap}" for gap in gaps)
    return "\n".join(lines)

def generate_framing_report(case: CivicRecallCase) -> str:
    if not case.escalation_paths:
        return "No escalation paths captured."
    lines = ["FRAMING NOTES FOR ESCALATION"]
    for path in case.escalation_paths:
        lines.append(f"- {path.name}: {generate_framing_note(path)}")
        lines.append(f"  {jurisdiction_template(path.route_type)}")
    return "\n".join(lines)

def generate_decision_structure_summary(case: CivicRecallCase) -> str:
    summary = [
        f"Case '{case.case_title}' sits in the domain of {case.civic_domain}.",
        f"The immediate trigger is: {case.decision_trigger}",
        f"The priority to protect is: {case.user_priority}.",
        f"{len(case.actors)} actor record(s), {len(case.evidence_bundle)} evidence item(s), {len(case.deadlines)} deadline(s), {len(case.timeline)} timeline event(s), and {len(case.escalation_paths)} path(s) are currently mapped.",
    ]
    if case.structural_insight:
        summary.append(f"Structural insight: {case.structural_insight}")
    if case.personal_positioning:
        summary.append(f"Personal positioning: {case.personal_positioning}")
    if case.decision_note:
        summary.append(f"Current decision direction: {case.decision_note}")
    return "\n".join(summary)

def export_case(case: CivicRecallCase, filepath: str) -> None:
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(asdict(case), f, indent=2, ensure_ascii=False)

def export_markdown_report(case: CivicRecallCase, filepath: str) -> None:
    md = []
    md.append(f"# Civic Recall Report — {case.strike_reference}")
    md.append("")
    md.append("## Dashboard")
    md.append("```")
    md.append(generate_case_dashboard(case))
    md.append("```")
    md.append("")
    md.append("## Timeline anomaly detection")
    md.append("```")
    md.append(timeline_anomaly_detection(case))
    md.append("```")
    md.append("")
    md.append("## Evidence / chronology consistency")
    md.append("```")
    md.append(evidence_chronology_consistency(case))
    md.append("```")
    md.append("")
    md.append(f"## Case title\n{case.case_title}")
    md.append("")
    md.append(f"## Civic domain\n{case.civic_domain}")
    md.append("")
    md.append(f"## Decision trigger\n{case.decision_trigger}")
    md.append("")
    md.append(f"## Recall question\n{case.recall_question}")
    md.append("")
    md.append(f"## Priority to protect\n{case.user_priority}")
    md.append("")
    md.append(f"## Desired outcome\n{case.desired_outcome}")
    md.append("")
    md.append("## Timeline")
    for event in timeline_sorted(case):
        md.append(f"- **{event.event_date}** — {event.label} [{event.event_type}] — {event.description}")
    md.append("")
    md.append("## Evidence report")
    md.append("```")
    md.append(generate_evidence_report(case))
    md.append("```")
    md.append("")
    md.append("## Gap report")
    md.append("```")
    md.append(generate_gap_report(case))
    md.append("```")
    md.append("")
    md.append("## Recommended next action")
    md.append("```")
    md.append(recommended_next_action(case))
    md.append("```")
    md.append("")
    md.append("## Next-path ranking")
    md.append("```")
    md.append(generate_path_ranking(case))
    md.append("```")
    md.append("")
    md.append("## Framing notes")
    md.append("```")
    md.append(generate_framing_report(case))
    md.append("```")
    md.append("")
    md.append("## Linked cases")
    if case.linked_cases:
        for link in case.linked_cases:
            md.append(f"- **{link.strike_reference}** [{link.relationship_type}] — {link.note}")
    else:
        md.append("- None recorded")
    md.append("")
    md.append("## Structural insight")
    md.append(case.structural_insight)
    md.append("")
    md.append("## Personal positioning")
    md.append(case.personal_positioning)
    md.append("")
    md.append("## Decision note")
    md.append(case.decision_note)
    md.append("")
    md.append("## Learning capture")
    md.append(case.learning_capture)
    md.append("")
    Path(filepath).write_text("\n".join(md), encoding="utf-8")

def export_case_library_csv(cases: List[CivicRecallCase], filepath: str) -> None:
    fieldnames = ["strike_reference", "case_title", "civic_domain", "urgency", "institution_count", "actor_count", "evidence_count", "deadline_count", "timeline_count", "path_count", "linked_case_count", "evidence_score", "top_path", "gap_count"]
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for case in cases:
            evidence_score, _ = evidence_strength_score(case)
            top_path = rank_paths(case.escalation_paths)[0][0].name if case.escalation_paths else ""
            writer.writerow({
                "strike_reference": case.strike_reference,
                "case_title": case.case_title,
                "civic_domain": case.civic_domain,
                "urgency": case.urgency,
                "institution_count": len(case.institutions),
                "actor_count": len(case.actors),
                "evidence_count": len(case.evidence_bundle),
                "deadline_count": len(case.deadlines),
                "timeline_count": len(case.timeline),
                "path_count": len(case.escalation_paths),
                "linked_case_count": len(case.linked_cases),
                "evidence_score": evidence_score,
                "top_path": top_path,
                "gap_count": len(evidence_gap_detection(case)),
            })

def export_portfolio_markdown(cases: List[CivicRecallCase], filepath: str) -> None:
    lines = ["# Civic Recall Portfolio Dashboard", ""]
    lines.append("## Portfolio learning summary")
    lines.append("```")
    lines.append(multi_case_learning_summary(cases))
    lines.append("```")
    lines.append("")
    lines.append("## Institution scoring profiles")
    lines.append("```")
    lines.append(institution_scoring_profiles(cases))
    lines.append("```")
    lines.append("")
    lines.append("## Institution behaviour memory")
    lines.append("```")
    lines.append(institution_behaviour_memory(cases))
    lines.append("```")
    lines.append("")
    lines.append("## Path outcome feedback")
    lines.append("```")
    lines.append(path_outcome_feedback(cases))
    lines.append("```")
    lines.append("")
    lines.append("## Pattern recall")
    lines.append("```")
    lines.append(pattern_recall(cases))
    lines.append("```")
    lines.append("")
    lines.append("## Case dashboards")
    for case in cases:
        lines.append(f"### {case.strike_reference} — {case.case_title}")
        lines.append("```")
        lines.append(generate_case_dashboard(case))
        lines.append("```")
        lines.append("")
    Path(filepath).write_text("\n".join(lines), encoding="utf-8")

def demo_case() -> CivicRecallCase:
    return CivicRecallCase(
        strike_reference="Strike-Demo-07",
        case_title="Oversight escalation after procedural narrowing",
        civic_domain="governance / regulatory oversight",
        decision_trigger="An institution issued a procedural response that narrowed the issue and avoided substance.",
        recall_question="What should I do next to preserve the record and escalate within the strongest remit?",
        user_priority="truth, accountability, and record preservation",
        desired_outcome="Choose the strongest next path without losing procedural footing",
        urgency="medium",
        institutions=["Primary institution", "External oversight body"],
        rules_or_procedures=["Internal complaint route", "External admissibility threshold", "Reply deadline in 14 days"],
        constraints=["Time and energy", "Need for clean evidence framing", "Procedural narrowing by institutions"],
        actors=[
            CivicActor("Primary institution", "institution", "original decision-maker", "contain exposure while appearing procedurally compliant", "issue narrow procedural replies"),
            CivicActor("Oversight body", "oversight", "external reviewer", "remain within formal remit and evidence threshold", "review only what is precisely framed"),
        ],
        evidence_bundle=[
            EvidenceItem("Institution reply letter", "letter", "Shows procedural framing and narrowing of scope", "high", "Procedural reply received"),
            EvidenceItem("Chronology note", "timeline", "Preserves event sequence and escalation logic", "high", "Chronology drafted"),
            EvidenceItem("Working note", "note", "Captures interpretation but not a primary record", "low", ""),
        ],
        deadlines=[DeadlineItem("Internal reply window", "2026-03-16", "Loss of procedural footing and weaker internal record")],
        timeline=[
            TimelineEvent("2026-03-01", "Initial complaint sent", "contact", "Initial complaint submitted to primary institution."),
            TimelineEvent("2026-03-05", "Procedural reply received", "reply", "Institution responded procedurally and narrowed the issue."),
            TimelineEvent("2026-03-07", "Chronology drafted", "evidence", "Timeline note created to preserve the sequence of events."),
        ],
        escalation_paths=[
            EscalationPath("Refine and reply internally", "internal complaint", "Need to preserve process and sharpen the record", "Further procedural correspondence", "short", "low", "yes", "high", "high", "partial", "Internal footing preserved but substance still narrowed."),
            EscalationPath("External oversight escalation", "external oversight", "Internal route shown to be insufficient or exhausted", "Admissibility review and request for tightly framed evidence", "medium", "medium", "partial", "medium", "low", "unknown", ""),
            EscalationPath("Broad media escalation", "media", "Frustration with procedural narrowing", "Public attention but no direct formal remedy", "short", "high", "no", "medium", "low", "failed", "Attention gained but formal remedy did not improve."),
        ],
        linked_cases=[
            LinkedCaseRef("Strike-701", "same institution", "Earlier interaction with the same body may show repeated procedural narrowing."),
            LinkedCaseRef("Strike-688", "evidence overlap", "Shares chronology and correspondence themes."),
        ],
        structural_insight="The system privileges procedure over substance unless the issue is tightly framed within remit.",
        personal_positioning="The citizen has the chronology and evidence, but must convert lived experience into procedurally admissible structure.",
        decision_note="Lean toward preserving the internal footing first, then escalate externally with a cleaner framed bundle.",
        learning_capture="Effective escalation depends on remit-fit, chronology, and evidence framing rather than raw volume alone.",
    )

def main() -> None:
    print("Civic Recall Pipeline Decision Engine — Version 7")
    print("1) Run interactive recall capture")
    print("2) Show demo case")
    print("3) Load prior JSON case memory")
    print("4) Recall patterns from a directory of prior JSON cases")
    print("5) Load one case + compare against a directory of prior JSON cases")
    print("6) Load case directory + generate learning summaries / CSV export")
    print("7) Load case directory + export portfolio Markdown dashboard")
    choice = ask("\nChoose 1, 2, 3, 4, 5, 6, or 7: ")
    comparison_cases: List[CivicRecallCase] = []
    if choice == "1":
        case = capture_case()
    elif choice == "3":
        filepath = ask("Enter path to prior JSON case: ")
        case = load_case_memory(filepath)
        if case is None:
            return
    elif choice == "4":
        directory = ask("Enter directory path containing prior JSON cases: ")
        cases = load_case_directory(directory)
        print("\n=== Pattern Recall ===\n")
        print(pattern_recall(cases))
        return
    elif choice == "5":
        filepath = ask("Enter path to target JSON case: ")
        case = load_case_memory(filepath)
        if case is None:
            return
        directory = ask("Enter directory path containing comparison JSON cases: ")
        comparison_cases = load_case_directory(directory)
    elif choice == "6":
        directory = ask("Enter directory path containing prior JSON cases: ")
        cases = load_case_directory(directory)
        print("\n=== Multi-Case Learning Summary ===\n")
        print(multi_case_learning_summary(cases))
        print("\n=== Institution Scoring Profiles ===\n")
        print(institution_scoring_profiles(cases))
        print("\n=== Institution Behaviour Memory ===\n")
        print(institution_behaviour_memory(cases))
        print("\n=== Path Outcome Feedback ===\n")
        print(path_outcome_feedback(cases))
        export_csv = ask("\nExport case library CSV? (y/n): ").lower()
        if export_csv == "y":
            csv_name = ask("CSV filename (e.g. civic_case_library_v7.csv): ")
            export_case_library_csv(cases, csv_name)
            print(f"Saved CSV to {csv_name}")
        return
    elif choice == "7":
        directory = ask("Enter directory path containing prior JSON cases: ")
        cases = load_case_directory(directory)
        md_name = ask("Markdown filename (e.g. civic_portfolio_dashboard_v7.md): ")
        export_portfolio_markdown(cases, md_name)
        print(f"Saved portfolio Markdown to {md_name}")
        return
    else:
        case = demo_case()

    print("\n=== Case Dashboard ===\n")
    print(generate_case_dashboard(case))
    print("\n=== Civic Recall Map ===\n")
    print(generate_recall_map(case))
    print("\n=== Civic Recall ASCII Pipeline ===\n")
    print(generate_ascii_pipeline(case))
    print("\n=== Decision Structure Summary ===\n")
    print(generate_decision_structure_summary(case))
    print("\n=== Jurisdiction Report ===\n")
    print(generate_jurisdiction_report(case))
    print("\n=== Evidence Report ===\n")
    print(generate_evidence_report(case))
    print("\n=== Gap Report ===\n")
    print(generate_gap_report(case))
    print("\n=== Timeline Anomaly Detection ===\n")
    print(timeline_anomaly_detection(case))
    print("\n=== Evidence / Chronology Consistency ===\n")
    print(evidence_chronology_consistency(case))
    print("\n=== Framing Report ===\n")
    print(generate_framing_report(case))
    print("\n=== Next-Path Ranking ===\n")
    print(generate_path_ranking(case))
    print("\n=== Recommended Next Action ===\n")
    print(recommended_next_action(case))
    if comparison_cases:
        print("\n=== Cross-Case Similarity Matching ===\n")
        print(cross_case_similarity(case, comparison_cases))
    save_json = ask("\nExport this recall case to JSON? (y/n): ").lower()
    if save_json == "y":
        filename = ask("Filename (e.g. civic_recall_case_v7.json): ")
        export_case(case, filename)
        print(f"Saved JSON to {filename}")
    save_md = ask("\nExport a Markdown report? (y/n): ").lower()
    if save_md == "y":
        md_name = ask("Markdown filename (e.g. civic_recall_report_v7.md): ")
        export_markdown_report(case, md_name)
        print(f"Saved Markdown report to {md_name}")

if __name__ == "__main__":
    main()
