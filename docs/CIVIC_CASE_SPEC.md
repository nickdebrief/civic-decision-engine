# Civic Case Specification

The Civic Decision Engine processes structured civic case records.

A civic case represents a documented interaction between an individual
or organisation and an institution, typically involving a complaint,
request, regulatory issue, or oversight matter.

Cases are represented as structured JSON files and validated against
the `civic_case.schema.json` schema.


## Purpose

The Civic Case Specification defines the structure required for a case
to be processed by the Civic Decision Engine.

It ensures that:

- evidence is documented
- timelines are traceable
- institutional actors are identified
- lifecycle stage is explicit


## Case Structure

A civic case includes several core components:

• Case Metadata  
• Institutional Context  
• Actors  
• Evidence Bundle  
• Timeline  
• Lifecycle State  
• Escalation Context  


## Example Case

Example cases can be found in:

examples/sample_case.json

{
“case_id”: “strike_742”,
“title”: “Example civic complaint”,
“institution”: “Example Institution”,
“created”: “2026-03-01”
}

## Actors

Actors represent the parties involved in the case.

Actors may include:

- complainant
- institutional staff
- oversight bodies
- regulators

Example:

“actors”: [
{
“name”: “Complainant”,
“role”: “citizen”
},
{
“name”: “Institution”,
“role”: “respondent”
}
]

## Evidence Bundle

Evidence forms the factual basis of the case.

Examples of evidence include:

- documents
- emails
- photographs
- official letters
- public records

Evidence entries should contain:

- description
- source
- reference link if available


## Timeline

The timeline records key procedural events.

Examples include:

- complaint submission
- institutional response
- deadline expiry
- escalation action


Example:

“timeline”: [
{
“date”: “2026-03-01”,
“event”: “complaint_submitted”
},
{
“date”: “2026-03-15”,
“event”: “response_deadline”
}
]

## Lifecycle State

Each case is assigned a lifecycle state that reflects procedural progress.

Possible states include:

- intake
- internal_process
- awaiting_response
- escalation_ready
- external_review
- resolved
- archived


Lifecycle diagnostics within the Civic Decision Engine evaluate
the stability and posture of the current stage.


## Escalation Context

Escalation fields describe the oversight pathways relevant to the case.

Examples include:

- regulatory authority
- ombudsman review
- judicial review
- administrative appeal


## Validation

All case files should validate against:

schema/civic_case.schema.json

Schema validation ensures that required fields are present and
data structure remains consistent across cases.


## Future Extensions

Future versions of the Civic Case Specification may include:

- institutional network identifiers
- jurisdiction mapping
- evidence confidence scoring
- cross-case linkage


## Author

The Civic Case Specification is part of the Civic Decision Engine
framework developed by **Nick Moloney**.