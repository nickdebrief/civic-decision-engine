# Civic Decision Engine (CDE)

A system for diagnosing institutional behaviour.

Observation sometimes becomes clearer when structure is applied.

Not designed for attention. 
Designed for understanding.

---

Not designed for attention. Designed for understanding.

Now publicly accessible:
https://civic-decision-engine-production.up.railway.app/

---

## What this is

The Civic Decision Engine is a diagnostic system.

It does not argue a case.
It classifies and interprets institutional behaviour based on structured inputs.

---

## What it does

Given one or more civic cases, the system:

* structures the case into a standard form
* detects behavioural conditions (e.g. delay, escalation)
* identifies progression across cases
* interprets the pattern as a system state

Outputs are:

* Timeline analysis → what is happening
* Pattern analysis → what it means

---

## Specifications

These documents define the formal structure and meaning of the system outputs.

- **Conditions Layer Specification v1.0**  
  [View (Markdown)](docs/specs/conditions-layer-spec-v1.md)  
  [Download (.docx)](docs/specs/conditions-layer-spec-v1.docx)

These documents define the formal structure and meaning of the system outputs.

The schema guarantees structure. The specification defines interpretation.

---

## Live Application

https://civic-decision-engine-production.up.railway.app/

No setup required. Paste a case or compare multiple cases directly.

## Cross-Case Analysis

The system supports cross-case comparison to identify repeated structural behaviour across submissions.

Cross-case comparison operates independently and does not persist results.

This mode reveals patterns.
It does not create records.

---

## One working example

This example shows a transition from delay to escalation.

Request

```text

curl -X POST "http://127.0.0.1:8000/analysis/timeline" \
-H "Content-Type: application/json" \
-d '{
  "cases": [
    {
      "strike_reference": "Strike-Example-001",
      "case_title": "Administrative complaint awaiting substantive response",
      "civic_domain": "local_government",
      "decision_trigger": "Acknowledged but no substantive response",
      "urgency": "medium",
      "institutions": ["Local Authority"],
      "case_lifecycle": {
        "current_stage": "awaiting_response",
        "status": "active",
        "stalled": false,
        "days_open": 20
      }
    },
    {
      "strike_reference": "Strike-Example-002",
      "case_title": "Unresolved complaint with missed deadline",
      "civic_domain": "local_government",
      "decision_trigger": "No response beyond deadline",
      "urgency": "high",
      "institutions": ["Local Authority"],
      "case_lifecycle": {
        "current_stage": "awaiting_response",
        "status": "active",
        "stalled": true,
        "days_open": 90
      }
    }
  ]
}'
```

---
## Expected output (simplified)

The system detects a transition 
from early delay 
to escalation:

```text

{
  "results": [
    {
      "conditions": [
        "TRANSFER_OF_BURDEN",
        "ESCALATION_WITHOUT_RESPONSE"
      ],
      "trajectory": "Deteriorating",
      "moment_of_change": {
        "from": "TRANSFER_OF_BURDEN",
        "to": "ESCALATION_WITHOUT_RESPONSE"
      }
    }
  ]
}
```
## This is then interpreted as:

## Pattern interpretation

The sequence shows deterioration:

From delayed procedural burden  
to escalation without response.

```text

{
  "pattern_summary": "Transition from TRANSFER_OF_BURDEN to ESCALATION_WITHOUT_RESPONSE detected within submitted sequence.",
  "pattern_interpretation": "The submitted sequence shows deterioration from delayed procedural burden to escalation without response.",
  "system_state": "TRANSITION_TO_ESCALATION",
  "signals": [
    "TRANSITION_DETECTED",
    "ESCALATION_WITHOUT_RESPONSE_PRESENT"
  ]
}
```
---

## Key principle

The system does not determine outcomes.

It makes visible:

* when delay becomes pattern
* when pattern becomes structure
* when structure no longer requires explanation

---

## Run locally
```text
uvicorn api.main:app --reload
```

## Then open:
```text
http://127.0.0.1:8000/docs
```
---

## Status

Active development (v10)
Conditions Layer integrated
Timeline + Pattern analysis operational
---

The record does not argue.

It becomes clear enough 
to be returned to.

