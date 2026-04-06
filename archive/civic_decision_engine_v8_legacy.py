# ARCHIVED VERSION
# This file is no longer active. See civic_decision_engine_v10.py

#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Tuple, Set
from datetime import date, datetime
from pathlib import Path
import json, re, csv, html

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
    return CivicActor(ask("Name: "), ask("Actor type: "), ask("Role in this case: "), ask("Main incentive / pressure: "), ask("Likely behaviour under that incentive: "))

def ask_evidence() -> EvidenceItem:
    print("\nAdd evidence item")
    return EvidenceItem(ask("Evidence label: "), ask("Evidence type: "), ask("Why is this relevant? "), ask("Evidence strength (high / medium / low): "), ask("Linked timeline label if any: "))

def ask_deadline() -> DeadlineItem:
    print("\nAdd deadline item")
    return DeadlineItem(ask("Deadline label: "), ask("Due date (YYYY-MM-DD): "), ask("What happens if this is missed? "))

def ask_timeline_event() -> TimelineEvent:
    print("\nAdd timeline / chronology event")
    return TimelineEvent(ask("Event date (YYYY-MM-DD): "), ask("Short event label: "), ask("Event type: "), ask("Description: "))

def ask_path() -> EscalationPath:
    print("\nAdd escalation / response path")
    return EscalationPath(
        ask("Path name: "), ask("Route type: "), ask("What triggers this path? "), ask("Likely system response: "),
        ask("Time horizon (short / medium / long): "), ask("Risk level (low / medium / high): "),
        ask("Jurisdiction fit (yes / partial / no): "), ask("Evidence readiness (high / medium / low): "),
        ask("Deadline pressure (high / medium / low): "), ask("Outcome status if known (successful / partial / failed / unknown): "),
        ask("Outcome note if known: ")
    )

def ask_linked_case() -> LinkedCaseRef:
    print("\nAdd linked case reference")
    return LinkedCaseRef(ask("Linked strike reference: "), ask("Relationship type (same institution / same issue / evidence overlap / escalation lineage / other): "), ask("Link note: "))

def capture_case() -> CivicRecallCase:
    print("\n=== Civic Recall Pipeline Decision Engine — Version 8 ===\n")
    case = CivicRecallCase(
        ask("Strike reference / recall ID: "), ask("Case title: "), ask("Civic domain: "), ask("Decision trigger: "),
        ask("Recall question ('What should I do next?'): "), ask("Priority to protect: "), ask("Desired outcome: "),
        ask("Urgency (low / medium / high): "), ask_list("\nList the institutions / bodies involved:"),
        ask_list("\nList governing procedures, deadlines, routes, or formal rules:"), ask_list("\nList active constraints:")
    )
    while ask("\nAdd actor record? (y/n): ").lower() == "y": case.actors.append(ask_actor())
    while ask("\nAdd evidence item? (y/n): ").lower() == "y": case.evidence_bundle.append(ask_evidence())
    while ask("\nAdd deadline item? (y/n): ").lower() == "y": case.deadlines.append(ask_deadline())
    while ask("\nAdd timeline event? (y/n): ").lower() == "y": case.timeline.append(ask_timeline_event())
    while ask("\nAdd escalation / response path? (y/n): ").lower() == "y": case.escalation_paths.append(ask_path())
    while ask("\nAdd linked case reference? (y/n): ").lower() == "y": case.linked_cases.append(ask_linked_case())
    case.structural_insight = ask("\nStructural insight: ")
    case.personal_positioning = ask("Personal positioning: ")
    case.decision_note = ask("Decision note: ")
    case.learning_capture = ask("Learning capture: ")
    return case

def safe_parse_date(s: str) -> Optional[date]:
    try: return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError: return None

def deadline_status(deadline: DeadlineItem) -> str:
    d = safe_parse_date(deadline.due_date)
    if d is None: return "invalid-date"
    delta = (d - date.today()).days
    if delta < 0: return f"overdue by {-delta} day(s)"
    if delta == 0: return "due today"
    if delta <= 7: return f"due soon ({delta} day(s))"
    return f"upcoming ({delta} day(s))"

def score_path(path: EscalationPath) -> int:
    jurisdiction_map = {"yes": 4, "partial": 2, "no": 0}
    evidence_map = {"high": 3, "medium": 2, "low": 1}
    deadline_map = {"low": 2, "medium": 1, "high": 0}
    risk_penalty = {"low": 0, "medium": -1, "high": -2}
    time_bonus = {"short": 2, "medium": 1, "long": 0}
    outcome_bonus = {"successful": 2, "partial": 1, "failed": -1, "unknown": 0, "": 0}
    return (
        jurisdiction_map.get(path.jurisdiction_fit.lower(), 0)
        + evidence_map.get(path.evidence_readiness.lower(), 0)
        + deadline_map.get(path.deadline_pressure.lower(), 0)
        + time_bonus.get(path.time_horizon.lower(), 0)
        + risk_penalty.get(path.risk_level.lower(), 0)
        + outcome_bonus.get(path.outcome_status.lower(), 0)
    )

def rank_paths(paths: List[EscalationPath]) -> List[Tuple[EscalationPath, int]]:
    ranked = [(p, score_path(p)) for p in paths]
    ranked.sort(key=lambda x: x[1], reverse=True)
    return ranked

def normalized_tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))

def similarity_score(case_a: CivicRecallCase, case_b: CivicRecallCase) -> int:
    score = 0
    if case_a.civic_domain.lower() == case_b.civic_domain.lower(): score += 4
    score += min(len({i.lower() for i in case_a.institutions} & {i.lower() for i in case_b.institutions}), 5)
    score += min(len({p.route_type.lower() for p in case_a.escalation_paths} & {p.route_type.lower() for p in case_b.escalation_paths}), 3)
    score += min(len(normalized_tokens(case_a.user_priority + " " + case_a.decision_trigger) & normalized_tokens(case_b.user_priority + " " + case_b.decision_trigger)), 5)
    return score

def evidence_strength_score(case: CivicRecallCase) -> Tuple[int, str]:
    weights = {"high": 3, "medium": 2, "low": 1}
    if not case.evidence_bundle: return 0, "No evidence captured."
    total = sum(weights.get(e.strength.lower(), 0) for e in case.evidence_bundle)
    avg = total / len(case.evidence_bundle)
    label = "Strong evidence bundle" if avg >= 2.5 else "Moderate evidence bundle" if avg >= 1.75 else "Weak evidence bundle"
    return total, label

def timeline_sorted(case: CivicRecallCase) -> List[TimelineEvent]:
    return sorted(case.timeline, key=lambda e: (safe_parse_date(e.event_date) is None, safe_parse_date(e.event_date) or date.max, e.label.lower()))

def evidence_gap_detection(case: CivicRecallCase) -> List[str]:
    gaps: List[str] = []
    if not case.evidence_bundle:
        gaps.append("No evidence bundle recorded.")
    else:
        has_timeline = any(e.evidence_type.lower() == "timeline" for e in case.evidence_bundle)
        has_letter_email = any(e.evidence_type.lower() in {"letter", "email"} for e in case.evidence_bundle)
        if not has_timeline and not case.timeline: gaps.append("No chronology source detected — add a timeline or chronology note.")
        if not has_letter_email: gaps.append("No primary correspondence evidence detected — add letters or emails where possible.")
        if sum(1 for e in case.evidence_bundle if e.strength.lower() == "low") >= max(1, len(case.evidence_bundle)//2):
            gaps.append("A large share of the evidence bundle is low-strength — strengthen with primary records.")
    if not case.actors: gaps.append("No actor mapping recorded — incentives and likely behaviour remain under-mapped.")
    if not case.escalation_paths: gaps.append("No escalation paths recorded — no structured next-step comparison is possible.")
    if case.escalation_paths and all(p.jurisdiction_fit.lower() in {"partial","no"} for p in case.escalation_paths):
        gaps.append("No escalation path currently shows strong jurisdiction fit.")
    return gaps

def generate_framing_note(path: EscalationPath) -> str:
    notes: List[str] = []
    fit, evidence, deadline = path.jurisdiction_fit.lower(), path.evidence_readiness.lower(), path.deadline_pressure.lower()
    notes.append("Frame the issue directly within the stated remit." if fit == "yes" else "Narrow the issue and translate it into remit-aligned language." if fit == "partial" else "This path appears weak on remit; avoid overcommitting without reframing.")
    notes.append("Lead with the strongest evidence and chronology." if evidence == "high" else "Tighten the bundle and remove weaker material before escalation." if evidence == "medium" else "Build the evidence bundle further before relying on this path.")
    notes.append("Preserve procedural footing immediately, even if only with a holding response." if deadline == "high" else "Balance speed with cleaner framing." if deadline == "medium" else "Use available time to improve clarity, chronology, and structure.")
    return " ".join(notes)

def jurisdiction_template(route_type: str) -> str:
    templates = {
        "internal complaint": "Template focus: preserve procedural footing, identify the exact issue, state the remedy sought, and anchor the chronology tightly.",
        "external oversight": "Template focus: frame strictly within remit, define the complaint in narrow terms, attach only the strongest evidence, and show prior internal engagement.",
        "legal": "Template focus: identify legal issue, timeline, documentary record, remedy sought, and costs / risk considerations.",
        "media": "Template focus: distinguish public-interest narrative from formal remedy, avoid overclaiming, and anchor statements in verifiable records.",
        "public record": "Template focus: preserve chronology, evidence links, dates, and official responses in a neutral, auditable format.",
    }
    return templates.get(route_type.lower(), "Template focus: define the issue clearly, state the route, show the chronology, and anchor claims in evidence.")

def recommended_next_action(case: CivicRecallCase) -> str:
    if not case.escalation_paths: return "No recommendation available because no escalation paths are recorded."
    top_path, top_score = rank_paths(case.escalation_paths)[0]
    lines = [f"Highest-ranked path: {top_path.name} (score {top_score}).",
             f"Reason: jurisdiction fit = {top_path.jurisdiction_fit}, evidence readiness = {top_path.evidence_readiness}, deadline pressure = {top_path.deadline_pressure}."]
    gaps = evidence_gap_detection(case)
    if gaps:
        lines.append("Before acting, close the most important evidence / structure gaps.")
        lines.extend([f"- {g}" for g in gaps[:3]])
    lines.append(f"Recommended framing: {generate_framing_note(top_path)}")
    lines.append(f"Jurisdiction template: {jurisdiction_template(top_path.route_type)}")
    return "\n".join(lines)

def load_case_memory(filepath: str) -> Optional[CivicRecallCase]:
    try:
        payload = json.loads(Path(filepath).read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"File not found: {filepath}"); return None
    except json.JSONDecodeError:
        print(f"Could not parse JSON: {filepath}"); return None
    actors = [CivicActor(**a) for a in payload.get("actors", [])]
    evidence = []
    for e in payload.get("evidence_bundle", []):
        e.setdefault("strength", "medium"); e.setdefault("linked_timeline_label", ""); evidence.append(EvidenceItem(**e))
    deadlines = [DeadlineItem(**d) for d in payload.get("deadlines", [])]
    timeline = [TimelineEvent(**t) for t in payload.get("timeline", [])]
    paths = []
    for p in payload.get("escalation_paths", []):
        p.setdefault("outcome_status", "unknown"); p.setdefault("outcome_note", ""); paths.append(EscalationPath(**p))
    links = [LinkedCaseRef(**l) for l in payload.get("linked_cases", [])]
    try:
        return CivicRecallCase(
            payload["strike_reference"], payload["case_title"], payload["civic_domain"], payload["decision_trigger"],
            payload["recall_question"], payload["user_priority"], payload["desired_outcome"], payload["urgency"],
            payload.get("institutions", []), payload.get("rules_or_procedures", []), payload.get("constraints", []),
            actors, evidence, deadlines, timeline, paths, links,
            payload.get("structural_insight", ""), payload.get("personal_positioning", ""),
            payload.get("decision_note", ""), payload.get("learning_capture", "")
        )
    except KeyError as exc:
        print(f"Missing required field in JSON: {exc}"); return None

def load_case_directory(directory: str) -> List[CivicRecallCase]:
    folder = Path(directory)
    if not folder.exists() or not folder.is_dir(): return []
    out: List[CivicRecallCase] = []
    for path in folder.glob("*.json"):
        case = load_case_memory(str(path))
        if case is not None: out.append(case)
    return out

def pattern_recall(cases: List[CivicRecallCase]) -> str:
    if not cases: return "No prior cases loaded for pattern recall."
    domain_count: Dict[str,int] = {}; institution_count: Dict[str,int] = {}; route_count: Dict[str,int] = {}
    for case in cases:
        domain_count[case.civic_domain] = domain_count.get(case.civic_domain, 0) + 1
        for inst in case.institutions: institution_count[inst] = institution_count.get(inst, 0) + 1
        for path in case.escalation_paths: route_count[path.route_type] = route_count.get(path.route_type, 0) + 1
    top = lambda d: sorted(d.items(), key=lambda x: (-x[1], x[0]))[:5]
    lines = ["PATTERN RECALL ACROSS PRIOR CASES", f"Loaded cases: {len(cases)}", "\nTop civic domains:"]
    for k,v in top(domain_count): lines.append(f"- {k}: {v}")
    lines.append("\nTop institutions:")
    for k,v in top(institution_count): lines.append(f"- {k}: {v}")
    lines.append("\nTop escalation route types:")
    for k,v in top(route_count): lines.append(f"- {k}: {v}")
    return "\n".join(lines)

def multi_case_learning_summary(cases: List[CivicRecallCase]) -> str:
    if not cases: return "No cases loaded for multi-case learning summary."
    urgency: Dict[str,int] = {}; evidence_totals: List[int] = []; gap_counts = 0
    for case in cases:
        urgency[case.urgency] = urgency.get(case.urgency, 0) + 1
        s,_ = evidence_strength_score(case); evidence_totals.append(s)
        if evidence_gap_detection(case): gap_counts += 1
    avg = sum(evidence_totals) / len(evidence_totals) if evidence_totals else 0
    lines = ["MULTI-CASE LEARNING SUMMARY", f"Loaded cases: {len(cases)}", f"Average evidence strength score: {avg:.2f}", f"Cases with one or more detected gaps: {gap_counts}", "\nUrgency distribution:"]
    for k,v in sorted(urgency.items()): lines.append(f"- {k}: {v}")
    return "\n".join(lines)

def escalation_success_heuristics(cases: List[CivicRecallCase]) -> str:
    if not cases: return "No cases loaded for escalation success heuristics."
    memory: Dict[str, Dict[str,int]] = {}
    for case in cases:
        for path in case.escalation_paths:
            rt = path.route_type or "unknown"
            memory.setdefault(rt, {"successful":0,"partial":0,"failed":0,"unknown":0})
            status = (path.outcome_status or "unknown").lower()
            if status not in memory[rt]: status = "unknown"
            memory[rt][status] += 1
    lines = ["ESCALATION SUCCESS HEURISTICS"]
    for route, stats in sorted(memory.items()):
        total = sum(stats.values()) or 1
        score = (stats["successful"] + 0.5 * stats["partial"]) / total
        lines.append(f"- {route}: heuristic score {score:.2f} based on {total} observed path(s)")
    return "\n".join(lines)

def cross_case_deadline_pressure_analysis(cases: List[CivicRecallCase]) -> str:
    if not cases: return "No cases loaded for deadline pressure analysis."
    pressure = {"high":0,"medium":0,"low":0,"unknown":0}; overdue_cases = 0
    for case in cases:
        if any("overdue" in deadline_status(dl) for dl in case.deadlines): overdue_cases += 1
        for path in case.escalation_paths:
            key = (path.deadline_pressure or "unknown").lower()
            pressure[key if key in pressure else "unknown"] += 1
    lines = ["CROSS-CASE DEADLINE PRESSURE ANALYSIS", f"Cases with overdue deadlines detected: {overdue_cases}"]
    for k,v in pressure.items(): lines.append(f"- {k}: {v}")
    return "\n".join(lines)

def institution_lineage_graph(cases: List[CivicRecallCase]) -> str:
    if not cases: return "No cases loaded for institution lineage graph."
    edges: Dict[Tuple[str,str], int] = {}
    for case in cases:
        uniq = sorted(set(case.institutions))
        for i in range(len(uniq)):
            for j in range(i+1, len(uniq)):
                edge = (uniq[i], uniq[j]); edges[edge] = edges.get(edge, 0) + 1
    if not edges: return "INSTITUTION LINEAGE GRAPH\nNo institutional edges detected."
    lines = ["INSTITUTION LINEAGE GRAPH"]
    for (a,b), count in sorted(edges.items(), key=lambda x: (-x[1], x[0][0], x[0][1])):
        lines.append(f"{a} --({count})--> {b}")
    return "\n".join(lines)

def linked_case_chain_tracing(start_ref: str, cases: List[CivicRecallCase]) -> str:
    if not cases: return "No cases loaded for linked-case chain tracing."
    lookup = {case.strike_reference: case for case in cases}
    if start_ref not in lookup: return f"Linked-case chain start not found: {start_ref}"
    visited: Set[str] = set(); lines = ["LINKED-CASE CHAIN TRACING"]
    def walk(ref: str, depth: int = 0):
        if ref in visited:
            lines.append("  "*depth + f"- {ref} (already visited)"); return
        visited.add(ref)
        case = lookup.get(ref)
        if case is None:
            lines.append("  "*depth + f"- {ref} (missing case data)"); return
        lines.append("  "*depth + f"- {case.strike_reference}: {case.case_title}")
        for link in case.linked_cases:
            lines.append("  "*(depth+1) + f"↳ {link.relationship_type}: {link.note}")
            walk(link.strike_reference, depth+2)
    walk(start_ref); return "\n".join(lines)

def generate_case_dashboard(case: CivicRecallCase) -> str:
    evidence_total, evidence_label = evidence_strength_score(case)
    gaps = evidence_gap_detection(case)
    top_path = rank_paths(case.escalation_paths)[0][0].name if case.escalation_paths else "none"
    return "\n".join([
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
    ])

def export_case(case: CivicRecallCase, filepath: str) -> None:
    Path(filepath).write_text(json.dumps(asdict(case), indent=2, ensure_ascii=False), encoding="utf-8")

def export_case_library_csv(cases: List[CivicRecallCase], filepath: str) -> None:
    fields = ["strike_reference","case_title","civic_domain","urgency","institution_count","actor_count","evidence_count","deadline_count","timeline_count","path_count","linked_case_count","evidence_score","top_path","gap_count"]
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields); writer.writeheader()
        for case in cases:
            evidence_score, _ = evidence_strength_score(case)
            top_path = rank_paths(case.escalation_paths)[0][0].name if case.escalation_paths else ""
            writer.writerow({
                "strike_reference": case.strike_reference, "case_title": case.case_title, "civic_domain": case.civic_domain,
                "urgency": case.urgency, "institution_count": len(case.institutions), "actor_count": len(case.actors),
                "evidence_count": len(case.evidence_bundle), "deadline_count": len(case.deadlines), "timeline_count": len(case.timeline),
                "path_count": len(case.escalation_paths), "linked_case_count": len(case.linked_cases),
                "evidence_score": evidence_score, "top_path": top_path, "gap_count": len(evidence_gap_detection(case))
            })

def export_html_dashboard(cases: List[CivicRecallCase], filepath: str) -> None:
    cards = []
    for case in cases:
        cards.append(f'<div class="card"><h3>{html.escape(case.strike_reference)} — {html.escape(case.case_title)}</h3><pre>{html.escape(generate_case_dashboard(case))}</pre></div>')
    doc = f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>Civic Recall Portfolio Dashboard</title>
<style>body{{font-family:Arial,sans-serif;margin:24px;background:#f7f7f7;color:#222}} .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:16px}} .card{{background:white;border:1px solid #ddd;border-radius:10px;padding:16px}} pre{{white-space:pre-wrap;background:#fafafa;padding:12px;border-radius:8px;border:1px solid #eee}}</style>
</head><body><h1>Civic Recall Portfolio Dashboard</h1>
<div class="grid">
<div class="card"><h2>Portfolio Learning Summary</h2><pre>{html.escape(multi_case_learning_summary(cases))}</pre></div>
<div class="card"><h2>Pattern Recall</h2><pre>{html.escape(pattern_recall(cases))}</pre></div>
<div class="card"><h2>Institution Lineage Graph</h2><pre>{html.escape(institution_lineage_graph(cases))}</pre></div>
<div class="card"><h2>Escalation Success Heuristics</h2><pre>{html.escape(escalation_success_heuristics(cases))}</pre></div>
<div class="card"><h2>Deadline Pressure Analysis</h2><pre>{html.escape(cross_case_deadline_pressure_analysis(cases))}</pre></div>
</div><h2>Case Dashboards</h2><div class="grid">{''.join(cards)}</div></body></html>"""
    Path(filepath).write_text(doc, encoding="utf-8")

def demo_case() -> CivicRecallCase:
    return CivicRecallCase(
        "Strike-Demo-08","Oversight escalation after procedural narrowing","governance / regulatory oversight",
        "An institution issued a procedural response that narrowed the issue and avoided substance.",
        "What should I do next to preserve the record and escalate within the strongest remit?",
        "truth, accountability, and record preservation","Choose the strongest next path without losing procedural footing","medium",
        ["Primary institution","External oversight body"],
        ["Internal complaint route","External admissibility threshold","Reply deadline in 14 days"],
        ["Time and energy","Need for clean evidence framing","Procedural narrowing by institutions"],
        [
            CivicActor("Primary institution","institution","original decision-maker","contain exposure while appearing procedurally compliant","issue narrow procedural replies"),
            CivicActor("Oversight body","oversight","external reviewer","remain within formal remit and evidence threshold","review only what is precisely framed"),
        ],
        [
            EvidenceItem("Institution reply letter","letter","Shows procedural framing and narrowing of scope","high","Procedural reply received"),
            EvidenceItem("Chronology note","timeline","Preserves event sequence and escalation logic","high","Chronology drafted"),
            EvidenceItem("Working note","note","Captures interpretation but not a primary record","low",""),
        ],
        [DeadlineItem("Internal reply window","2026-03-16","Loss of procedural footing and weaker internal record")],
        [
            TimelineEvent("2026-03-01","Initial complaint sent","contact","Initial complaint submitted to primary institution."),
            TimelineEvent("2026-03-05","Procedural reply received","reply","Institution responded procedurally and narrowed the issue."),
            TimelineEvent("2026-03-07","Chronology drafted","evidence","Timeline note created to preserve the sequence of events."),
        ],
        [
            EscalationPath("Refine and reply internally","internal complaint","Need to preserve process and sharpen the record","Further procedural correspondence","short","low","yes","high","high","partial","Internal footing preserved but substance still narrowed."),
            EscalationPath("External oversight escalation","external oversight","Internal route shown to be insufficient or exhausted","Admissibility review and request for tightly framed evidence","medium","medium","partial","medium","low","unknown",""),
            EscalationPath("Broad media escalation","media","Frustration with procedural narrowing","Public attention but no direct formal remedy","short","high","no","medium","low","failed","Attention gained but formal remedy did not improve."),
        ],
        [
            LinkedCaseRef("Strike-701","same institution","Earlier interaction with the same body may show repeated procedural narrowing."),
            LinkedCaseRef("Strike-688","evidence overlap","Shares chronology and correspondence themes."),
        ],
        "The system privileges procedure over substance unless the issue is tightly framed within remit.",
        "The citizen has the chronology and evidence, but must convert lived experience into procedurally admissible structure.",
        "Lean toward preserving the internal footing first, then escalate externally with a cleaner framed bundle.",
        "Effective escalation depends on remit-fit, chronology, and evidence framing rather than raw volume alone."
    )

def main() -> None:
    print("Civic Recall Pipeline Decision Engine — Version 8")
    print("1) Run interactive recall capture")
    print("2) Show demo case")
    print("3) Load prior JSON case memory")
    print("4) Recall patterns from a directory of prior JSON cases")
    print("5) Load one case + compare against a directory of prior JSON cases")
    print("6) Load case directory + generate learning summaries / CSV export")
    print("7) Load case directory + export HTML dashboard")
    print("8) Load case directory + trace linked-case chain")
    choice = ask("\nChoose 1, 2, 3, 4, 5, 6, 7, or 8: ")
    if choice == "1":
        case = capture_case()
        print("\n=== Case Dashboard ===\n"); print(generate_case_dashboard(case))
        print("\n=== Recommended Next Action ===\n"); print(recommended_next_action(case))
        if ask("\nExport this recall case to JSON? (y/n): ").lower() == "y":
            filename = ask("Filename (e.g. civic_recall_case_v8.json): "); export_case(case, filename); print(f"Saved JSON to {filename}")
        return
    if choice == "2":
        case = demo_case()
        print("\n=== Case Dashboard ===\n"); print(generate_case_dashboard(case))
        print("\n=== Recommended Next Action ===\n"); print(recommended_next_action(case)); return
    if choice == "3":
        case = load_case_memory(ask("Enter path to prior JSON case: "))
        if case is None: return
        print("\n=== Case Dashboard ===\n"); print(generate_case_dashboard(case))
        print("\n=== Recommended Next Action ===\n"); print(recommended_next_action(case)); return
    if choice == "4":
        cases = load_case_directory(ask("Enter directory path containing prior JSON cases: "))
        print("\n=== Pattern Recall ===\n"); print(pattern_recall(cases))
        print("\n=== Institution Lineage Graph ===\n"); print(institution_lineage_graph(cases)); return
    if choice == "5":
        case = load_case_memory(ask("Enter path to target JSON case: "))
        if case is None: return
        comparison_cases = load_case_directory(ask("Enter directory path containing comparison JSON cases: "))
        print("\n=== Cross-Case Similarity Matching ===\n"); print(cross_case_similarity(case, comparison_cases)); return
    if choice == "6":
        cases = load_case_directory(ask("Enter directory path containing prior JSON cases: "))
        print("\n=== Multi-Case Learning Summary ===\n"); print(multi_case_learning_summary(cases))
        print("\n=== Escalation Success Heuristics ===\n"); print(escalation_success_heuristics(cases))
        print("\n=== Deadline Pressure Analysis ===\n"); print(cross_case_deadline_pressure_analysis(cases))
        if ask("\nExport case library CSV? (y/n): ").lower() == "y":
            csv_name = ask("CSV filename (e.g. civic_case_library_v8.csv): "); export_case_library_csv(cases, csv_name); print(f"Saved CSV to {csv_name}")
        return
    if choice == "7":
        cases = load_case_directory(ask("Enter directory path containing prior JSON cases: "))
        html_name = ask("HTML filename (e.g. civic_portfolio_dashboard_v8.html): "); export_html_dashboard(cases, html_name); print(f"Saved HTML dashboard to {html_name}"); return
    if choice == "8":
        cases = load_case_directory(ask("Enter directory path containing prior JSON cases: "))
        print("\n=== Linked-Case Chain Tracing ===\n"); print(linked_case_chain_tracing(ask("Enter strike reference to trace: "), cases)); return
    print("Invalid choice.")

if __name__ == "__main__":
    main()
