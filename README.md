# Civic Decision Engine (CDE)

<img width="512" height="512" alt="android-chrome-512x512" src="https://github.com/user-attachments/assets/db217999-105c-4776-8c36-186ed2705f2f" />

---

A public civic record and verification system for structured institutional analysis.

Observation sometimes becomes clearer when structure is applied.

Not designed for attention.  
Designed for understanding.

---

## Live System

https://civic-decision-engine-production.up.railway.app/

---

## What this is

The Civic Decision Engine is a diagnostic system for analysing institutional behaviour through structured civic records.

It does not argue a case.  
It classifies and interprets institutional behaviour based on structured inputs.

The system is designed to make institutional progression visible through:
- conditions
- trajectories
- transitions
- structural continuation

---

## What v11 introduces

Version 11 completes the public verification and archive layer.

New capabilities include:

- Canonical citation exports (APA, MLA, BibTeX, CSL JSON)
- Public verification pages with SHA-256 integrity validation
- Searchable public record archive
- Scalable archive pagination
- Multilingual verification support
- Version lineage and verification continuity
- Public record indexing and filtering
- Structured archive navigation

This version marks the transition from a diagnostic engine to a publicly navigable civic record infrastructure.

---

## What it does

Given one or more civic cases, the system:

- structures the case into a standard form
- detects behavioural conditions
- identifies progression across cases
- classifies structural trajectories
- interprets the resulting system state

Outputs include:

- Timeline analysis → what is happening
- Pattern analysis → what it means
- Conditions analysis → what structure is present
- Public record generation → what is preserved

---

## Public Record Infrastructure

The Civic Decision Engine supports publicly verifiable civic records.

Each record includes:

- stable reference identifier
- verification URL
- SHA-256 integrity hash
- canonical citation exports
- version lineage
- export timestamp
- structured condition classification

Records are:
- independently verifiable
- versioned
- hash-preserved
- publicly accessible

The archive supports:
- filtering
- pagination
- server-side search
- multilingual verification views

---

## Continuation Map (v1.1)

This version introduces the structured `CONTINUATION_MAP`.

It does not predict outcomes.  
It reflects what structure tends to produce when conditions remain unchanged.

The map is derived from state, not interpretation.

This marks the transition from describing cases to identifying structural continuation.

---

## Conditions Layer

The Conditions Layer is the core diagnostic layer of the system.

Conditions are reusable structural classifications describing institutional behaviour patterns.

Examples include:

- `TRANSFER_OF_BURDEN`
- `ESCALATION_WITHOUT_RESPONSE`
- `STABILITY_WITHOUT_CONFIRMATION`

Conditions are:
- diagnostic
- reusable
- structurally defined
- independent of originating cases

This allows repeated institutional behaviour to be recognised across separate records and environments.

---

## Specifications

These documents define the formal structure and meaning of the system outputs.

### Conditions Layer Specification v1.0

- [View (Markdown)](docs/specs/conditions-layer-spec-v1.md)
- [Download (.docx)](docs/specs/conditions-layer-spec-v1.docx)

The schema guarantees structure.  
The specification defines interpretation.

---

## Live Application

https://civic-decision-engine-production.up.railway.app/

No setup required.

Users can:
- submit cases
- compare sequences
- browse records
- verify public records
- search archive entries
- explore condition patterns
- view structural trajectories

---

## Public Archive

The `/records` archive provides:

- public record indexing
- institution filtering
- trajectory filtering
- condition visibility
- server-side search
- scalable pagination
- verification routing

Each archive entry resolves to a canonical verification page.

---

## Cross-Case Analysis

The system supports cross-case comparison to identify repeated structural behaviour across submissions.

Cross-case comparison operates independently and does not persist results.

This mode reveals patterns.  
It does not create records.

---

## One working example

This example shows a transition from delay to escalation.

### Request

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

The system detects a transition from early delay to escalation:

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

---

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

## Verification Layer

Verification pages expose:

- canonical citations
- integrity hashes
- version lineage
- export timestamps
- permalink continuity
- multilingual rendering
- verification manifests

This allows records to be cited in:
- research
- journalism
- civic submissions
- administrative complaints
- public-interest documentation

---

## Key principle

The system does not determine outcomes.

It makes visible:

- when delay becomes pattern
- when pattern becomes structure
- when structure becomes persistent
- when continuation no longer requires explanation

---

## Run locally

```text
uvicorn api.main:app --reload
```

Then open:

```text
http://127.0.0.1:8000/docs
```

---

## System Architecture

Core components include:

- Conditions Layer
- Timeline Analysis
- Pattern Interpretation
- Public Record Verification
- Archive Infrastructure
- Verification Hashing
- Citation Infrastructure
- Continuation Mapping

---

## Status

Active development (v11)

Current operational layers:

- Conditions Layer integrated
- Timeline analysis operational
- Pattern analysis operational
- Public verification infrastructure operational
- Searchable archive infrastructure operational
- Citation infrastructure operational
- Version lineage operational

---

## Philosophy

The record does not argue.

It becomes clear enough  
to be returned to.
