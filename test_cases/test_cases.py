import httpx
import json

BASE_URL = "http://127.0.0.1:8000"

cases = {
    "cases": [
        {
            "strike_reference": "Strike-Example-001",
            "case_title": "Administrative complaint awaiting substantive response",
            "civic_domain": "local_government",
            "decision_trigger": "A public body acknowledged the complaint but has not yet provided a substantive response.",
            "recall_question": "What is the appropriate next step to preserve the record while allowing reasonable time for response?",
            "user_priority": "clarity, procedural footing, and record integrity",
            "desired_outcome": "A timely substantive response and confirmation of procedural handling",
            "urgency": "medium",
            "institutions": ["Local Authority Complaints Office"],
            "case_lifecycle": {
                "current_stage": "awaiting_response",
                "status": "active",
                "stalled": False,
                "days_open": 20,
                "next_decision_point": "assess_internal_deadline_expiry",
                "next_deadline": "2026-03-25",
                "recommended_mode": "monitor_and_prepare",
            },
            "rules_or_procedures": [
                "Internal complaint procedure",
                "Response window of 20 working days",
            ],
            "constraints": [
                "Limited time and energy",
                "Need to maintain accurate chronology",
            ],
            "actors": [
                {
                    "name": "Citizen complainant",
                    "actor_type": "individual",
                    "role_in_case": "initiating and documenting the complaint",
                    "incentive_or_pressure": "seeking clarity and resolution",
                    "likely_behaviour": "monitor response timeframe and preserve records",
                },
                {
                    "name": "Complaints officer",
                    "actor_type": "institutional_actor",
                    "role_in_case": "handling the internal complaint process",
                    "incentive_or_pressure": "manage workload and respond within procedure",
                    "likely_behaviour": "provide response within expected timeframe or delay slightly",
                },
            ],
            "evidence_bundle": [
                {
                    "label": "Initial complaint email",
                    "evidence_type": "email",
                    "relevance": "Shows the original issue raised",
                    "strength": "high",
                    "linked_timeline_label": "Initial complaint submitted",
                },
                {
                    "label": "Acknowledgement reply",
                    "evidence_type": "email",
                    "relevance": "Confirms receipt of the complaint",
                    "strength": "high",
                    "linked_timeline_label": "Acknowledgement received",
                },
            ],
            "deadlines": [
                {
                    "label": "Internal response deadline",
                    "due_date": "2026-03-25",
                    "consequence": "If missed, escalation readiness increases",
                }
            ],
            "timeline": [
                {
                    "event_date": "2026-03-01",
                    "label": "Initial complaint submitted",
                    "event_type": "submission",
                    "description": "The complaint was submitted.",
                },
                {
                    "event_date": "2026-03-03",
                    "label": "Acknowledgement received",
                    "event_type": "acknowledgement",
                    "description": "Acknowledgement received without substantive reply.",
                },
            ],
            "escalation_paths": [
                {
                    "name": "Internal procedural follow-up",
                    "route_type": "internal_complaint",
                    "trigger": "Approaching internal deadline",
                    "likely_response": "Substantive reply or minor delay",
                    "time_horizon": "short",
                    "risk_level": "low",
                    "jurisdiction_fit": "yes",
                    "evidence_readiness": "high",
                    "deadline_pressure": "moderate",
                    "outcome_status": "unknown",
                    "outcome_note": "",
                }
            ],
            "linked_cases": [],
            "structural_insight": "Delay is present but remains within expected procedural bounds.",
            "personal_positioning": "The complainant is maintaining record integrity while allowing procedural timeframes to operate.",
            "decision_note": "Continue monitoring; prepare escalation only if the deadline is missed.",
            "learning_capture": "Early-stage delay should not be conflated with non-response; distinction is structural.",
        },
        {
            "strike_reference": "Strike-Example-002",
            "case_title": "Unresolved administrative complaint with extended delay and missed deadline",
            "civic_domain": "local_government",
            "decision_trigger": "A public body continued non-response beyond the stated internal deadline.",
            "recall_question": "What is the strongest next step to preserve the record and escalate appropriately?",
            "user_priority": "clarity, accountability, and procedural footing",
            "desired_outcome": "A formal response, procedural clarification, and an evidence-based escalation path",
            "urgency": "high",
            "institutions": ["Local Authority Complaints Office", "Oversight Body"],
            "case_lifecycle": {
                "current_stage": "awaiting_response",
                "status": "active",
                "stalled": True,
                "days_open": 90,
                "next_decision_point": "trigger_external_escalation",
                "next_deadline": "2026-04-01",
                "recommended_mode": "prepare_escalation",
            },
            "rules_or_procedures": [
                "Internal complaint procedure",
                "Response window of 20 working days",
                "External escalation route after internal process delay",
            ],
            "constraints": [
                "Limited time and energy",
                "Fragmented correspondence history",
                "Need to maintain an accurate chronology",
            ],
            "actors": [
                {
                    "name": "Citizen complainant",
                    "actor_type": "individual",
                    "role_in_case": "initiating and documenting the complaint",
                    "incentive_or_pressure": "seeking clarity, accountability, and resolution",
                    "likely_behaviour": "preserve records, escalate after missed deadlines",
                },
                {
                    "name": "Complaints officer",
                    "actor_type": "institutional_actor",
                    "role_in_case": "handling the internal complaint process",
                    "incentive_or_pressure": "manage workload and contain procedural exposure",
                    "likely_behaviour": "delay response or avoid escalation triggers",
                },
            ],
            "evidence_bundle": [
                {
                    "label": "Initial complaint email",
                    "evidence_type": "email",
                    "relevance": "Shows the original issue raised",
                    "strength": "high",
                    "linked_timeline_label": "Initial complaint submitted",
                },
                {
                    "label": "Acknowledgement reply",
                    "evidence_type": "email",
                    "relevance": "Confirms receipt of the complaint",
                    "strength": "high",
                    "linked_timeline_label": "Acknowledgement received",
                },
                {
                    "label": "Missed deadline note",
                    "evidence_type": "note",
                    "relevance": "Records that the response window expired without reply",
                    "strength": "high",
                    "linked_timeline_label": "Deadline passed without response",
                },
            ],
            "deadlines": [
                {
                    "label": "Internal response deadline",
                    "due_date": "2026-03-25",
                    "consequence": "Missed deadline strengthens escalation case",
                },
                {
                    "label": "Extended follow-up deadline",
                    "due_date": "2026-04-01",
                    "consequence": "Continued non-response confirms pattern of delay",
                },
            ],
            "timeline": [
                {
                    "event_date": "2026-03-01",
                    "label": "Initial complaint submitted",
                    "event_type": "submission",
                    "description": "The complaint was submitted.",
                },
                {
                    "event_date": "2026-03-03",
                    "label": "Acknowledgement received",
                    "event_type": "acknowledgement",
                    "description": "Acknowledgement without substantive reply.",
                },
                {
                    "event_date": "2026-03-25",
                    "label": "Deadline passed without response",
                    "event_type": "deadline",
                    "description": "No response received within the expected timeframe.",
                },
                {
                    "event_date": "2026-04-01",
                    "label": "Extended delay continues",
                    "event_type": "delay",
                    "description": "No response after extended period, confirming persistence.",
                },
            ],
            "escalation_paths": [
                {
                    "name": "Internal procedural follow-up",
                    "route_type": "internal_complaint",
                    "trigger": "Missed internal deadline",
                    "likely_response": "Minimal or delayed reply",
                    "time_horizon": "short",
                    "risk_level": "low",
                    "jurisdiction_fit": "yes",
                    "evidence_readiness": "high",
                    "deadline_pressure": "high",
                    "outcome_status": "unknown",
                    "outcome_note": "",
                }
            ],
            "linked_cases": [],
            "structural_insight": "Non-response has transitioned from delay to sustained pattern beyond defined procedural limits.",
            "personal_positioning": "The complainant is maintaining record integrity while preparing escalation.",
            "decision_note": "Internal deadline has passed; escalation readiness should now be prioritised.",
            "learning_capture": "Missed deadlines convert isolated delay into identifiable behavioural pattern.",
        },
    ]
}

response = httpx.post(f"http://127.0.0.1:8000/analysis/pattern", json=cases)

print("Status:", response.status_code)
data = response.json()
print(json.dumps(data, indent=2))

with open("case_1_2_timeline.json", "w") as f:
    json.dump(data, f, indent=2)
