# Civic Decision Engine

Observation sometimes becomes clearer when structure is applied.

## Why this project exists

Civic processes often involve complex interactions between citizens,
institutions, procedures, and timelines.

Individual cases can appear fragmented or ambiguous when viewed only
through documents, correspondence, or isolated events.

The Civic Decision Engine explores whether applying structured models
to civic cases can help reveal patterns in institutional decision
environments.

By representing cases as structured records containing actors,
evidence, timelines, and procedural stages, the framework attempts to
produce interpretable analytical signals about case posture,
escalation readiness, and decision structure.

The goal is not to automate decisions, but to make civic processes
more observable and understandable.

## Project Status

Civic Decision Engine — **v10**

Prototype analytical framework for modelling civic decision environments.

Current focus:

• framework architecture  
• civic case structure  
• analytical signal modelling  

Future development may explore:

• institutional pattern analysis  
• multi-case comparison  
• visual analysis interfaces


## Architecture Overview

Conceptual flow of the Civic Decision Engine.

The engine applies structured analysis to civic cases involving
institutions, actors, timelines, and evidence.

```
Real-world civic interaction
            ↓
     Structured civic case
            ↓
    Civic Decision Engine
            ↓
     Analytical signals
            ↓
   Interpretable insights
```

Full architecture documentation:

[Architecture Documentation](docs/ARCHITECTURE.md)

---

## Adaptation Layer (v10)

Building on the core architecture, the Adaptation Layer introduces
a structured way to observe how institutional behaviour shifts over time.

While individual cases can appear complex or ambiguous, comparing multiple structured cases allows patterns to emerge across timelines, responses, and escalation pathways.

This layer focuses on behavioural movement rather than isolated events.

### What it captures

- Changes in institutional behaviour across cases  
- Movement between response, partial engagement, and resistance  
- The relationship between escalation, timing, and engagement patterns  

### Behavioural progression

Example cases illustrate a common progression:

response → partial engagement → resistance

This progression does not assume intent.  
It reflects observable changes in engagement and response patterns over time.

### Interpretation

By comparing structured cases, the engine enables:

- Identification of emerging patterns  
- Recognition of stabilisation or deterioration  
- Understanding of when escalation may become necessary  

This is not designed to judge outcomes or assign blame.

It is designed to make behavioural change visible.

---

## Example Civic Case

```json
{
  "case_id": "strike_742",
  "institution": "Example Authority",
  "lifecycle_state": "awaiting_response",
  "actors": [
    "citizen",
    "institution"
  ],
  "timeline": [
    {
      "date": "2026-02-01",
      "event": "complaint_submitted"
    },
    {
      "date": "2026-02-10",
      "event": "institution_acknowledged"
    }
  ],
  "evidence_bundle": [
    "email_correspondence",
    "document_record"
  ]
}
```

## Example Analysis Signals

```
Evidence strength:       high
Deadline pressure:       medium
Case momentum:           active
Escalation readiness:    moderate
```
### Example Cases

- `civic_case_001.json` — baseline procedural case
- `civic_case_002.json` — delayed response with escalation signal

These examples demonstrate how the engine distinguishes between  
standard institutional processing and emerging containment dynamics  
through behavioural scoring and structured case comparison.

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Civic Case Specification](docs/CIVIC_CASE_SPEC.md)
- [Decision Model](docs/DECISION_MODEL.md)
- [Philosophy](docs/PHILOSOPHY.md)

