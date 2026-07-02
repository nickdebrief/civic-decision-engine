# Civic Decision Engine (CDE)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.21033426.svg)](https://doi.org/10.5281/zenodo.21033426)
[![OSF](https://img.shields.io/badge/OSF-Project-blue)](https://osf.io/wz29x/)
[![GitHub](https://img.shields.io/badge/GitHub-Repository-black)](https://github.com/nickdebrief/civic-decision-engine)

<img width="512" alt="Civic Decision Engine v12" src="docs/releases/assets/v12-seal.png" />

An open, deterministic framework for evaluating visible civic records and record-derived administrative outputs through inspectable evidence relationships, dependency mappings, pathway stability analysis, and reproducible report generation.

---

## Key Capabilities
- Structured civic record evaluation
- Evidence relationship mapping
- Administrative dependency mapping
- Pathway stability analysis
- Reproducible report generation
- Public verification and citation export

---

## Design Principles

- Deterministic evaluation
- Explicit methodological limitations
- Inspectable evidence relationships
- Reproducible outputs
- Versioned and citable artefacts
- Public verification and transparency

---

## Research Artefacts
- DOI: https://doi.org/10.5281/zenodo.21033426
- OSF Project: [Open Science Framework (OSF)](https://osf.io/wz29x/)
- GitHub Repository: https://github.com/nickdebrief/civic-decision-engine

---

A public civic record and verification system for structured institutional analysis.

Observation sometimes becomes clearer when structure is applied.

Not designed for attention.  
Designed for understanding.

---

Current release: v12

Release documentation:
- [`docs/releases/README_v12.md`](docs/releases/README_v12.md)

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

## What v12 introduces

Version 12 introduces additive attachment infrastructure for referenced evidence
artifacts while preserving canonical record verification hashes and canonical
serialization.

New capabilities include:

- Additive attachment infrastructure for referenced evidence artifacts
- Independent SHA-256 hashing for attachment content
- Attachment metadata projection through public record manifests
- Optional source-document date metadata
- Privacy filtering for private, withheld, and deleted attachments
- Admin-only upload infrastructure protected by `CDE_ADMIN_TOKEN`
- Local read-only attachment inspection tooling
- Controlled production verification using synthetic test artifacts
- Preservation of canonical record verification hashes and canonical serialization

Attachments are additive and non-canonical. They do not replace canonical
records, alter verification hashes, or change public record creation behavior.

v12 does not include public attachment downloads, public attachment serving,
attachment search, OCR, PDF text extraction, semantic indexing of attachment
content, or a public upload UI.

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

## Stage 19D — Determination Report

Provides a deterministic report layer that assembles and describes visible
record data and existing framework outputs, including conditions, trajectories,
administrative outputs, record evolution outputs, determination traces, rule
citations, and evidence attribution outputs.

The report is descriptive only and does not perform new analysis or create new
findings.

---

## Stage 19E — Sufficiency Boundaries

Identifies visible support boundaries for existing framework outputs by
classifying whether outputs are supported, partially supported, or unsupported
within the Evidence Attribution Matrix.

The layer evaluates visible support inside the framework only and does not
determine truth, legal sufficiency, evidential sufficiency in the real world,
liability, intent, blame, or factual correctness.

---

## Stage 19F — Counterfactual Visibility

Identifies which framework layers and evidence categories are visibly present
or not represented in the current record-derived outputs.

The layer is descriptive only. It does not generate hypothetical scenarios,
assign meaning to absence, infer intent, predict outcomes, validate evidence,
determine truth, or modify the record.

---

## Stage 19G — Explainability Certification

Provides an internal explainability certification layer that evaluates whether
required Stage 19 explainability components are present and inspectable for a
record.

The certification is internal to the framework only and does not certify truth,
legality, liability, factual correctness, real-world evidential sufficiency,
intent, blame, or wrongdoing.

---

## Stage 20 — Framework Self-Description & Reflexive Methodology

Provides deterministic self-description of CREF identity, purpose, scope,
implemented guarantees, declared constraints, reasoning architecture, and
reflexive methodology.

Stage 20 describes only implemented framework definitions and outputs. It does
not create methodology, introduce reasoning, infer facts, validate evidence,
determine truth or liability, or modify records.

---

## Stage 21 — Report Structure & Output Modes

Organises the Admin Record Evidence view into Executive Report, Review Report,
and Full Inspection Report modes. Executive mode presents concise current-state
and progression summaries; Review mode adds trace, citation, attribution, and
boundary summaries; Full Inspection mode preserves every existing report
section and supporting-evidence detail.

Stage 21 changes presentation and report composition only. It does not change
framework reasoning, evidence relationships, thresholds, classifications,
hashes, or record data. Full Inspection Report remains the default mode.

---

## Stage 22 — Determination Dependency Mapping

Adds deterministic structural maps showing which visible framework outputs are
required by later determinations and which downstream outputs depend on each
available node. The map covers administrative state, outcome, resolution,
closure, archive, explainability, self-description, and report-mode outputs.

Executive mode shows dependency summary and the key administrative path;
Review mode adds key upstream and downstream mappings; Full Inspection mode
shows every dependency node and mapping. Stage 22 is read-only inspection only
and does not change reasoning, evidence, thresholds, classifications, hashes,
or record data.

---

## Stage 23 — Pathway Stability Analysis

Evaluates the structural stability of eight existing determination pathways
using Stage 22 dependency availability, evidence readiness, sufficiency and
completeness, and existing administrative readiness outputs. Pathways are
classified as stable, partially stable, evidence-sensitive, unstable, or not
available without altering their underlying values.

Executive mode presents the stability state and administrative path summary;
Review mode adds stability inputs, key pathway classifications, sensitivity
indicators, and paths; Full Inspection mode presents the complete stability
analysis. Stage 23 is deterministic structural inspection only. It does not
predict outcomes, validate evidence, change dependencies, or modify records.

---

## Stage 24 — Record State Transition History

Adds a deterministic history view for eleven existing administrative outputs,
from evidence readiness through archive classification. Each entry shows its
current state, any explicitly visible prior state, Stage 22 dependency basis,
and Stage 23 stability basis. Missing prior states remain `Not Available` and
are labelled `Current State Only`.

Executive mode presents a concise transition overview; Review mode adds the
transition summary table; Full Inspection mode presents every transition basis
and limitation. Stage 24 does not reconstruct missing history, predict future
states, change classifications, or modify records.

---

## Stage 25 — Output Provenance Layer

Adds deterministic provenance for fourteen visible framework outputs: eleven
administrative states plus dependency mapping, pathway stability, and
transition history. Each entry identifies its producing stage and declared
helper, visible input basis, dependency basis, stability basis, transition
basis, provenance label, and methodological limitation.

Executive mode presents a concise provenance overview; Review mode adds the
provenance summary table; Full Inspection mode exposes every provenance basis.
Stage 25 does not infer hidden inputs or missing helpers, validate evidence,
change classifications, or modify records.

---

## Stage 26 — Deterministic Replay Mode

Adds a deterministic replay sequence for fifteen visible framework outputs:
the fourteen Stage 25 provenance entries and the provenance layer state itself.
Each replay step preserves the existing output value, producing stage and
declared helper, visible input basis, dependency basis, stability basis,
transition basis, provenance basis, replay result, and limitation.

Executive mode presents a concise replay overview; Review mode adds the replay
summary table; Full Inspection mode exposes every replay basis. Stage 26
restates existing outputs in stable order only. It does not simulate alternate
outcomes, reclassify records, validate evidence, infer hidden inputs, write to
the database, or modify records.

---

## Stage 27 — Framework Integrity Verification

Adds deterministic integrity verification for the visible framework inspection
stack. Fourteen checks cover the Stage 21 report-mode contract, Stage 22–26
preservation counts, replay coverage, current administrative output presence,
declared limitation visibility, and non-mutating/public-API boundaries.

Executive mode presents a concise integrity overview; Review mode adds the
integrity summary table; Full Inspection mode exposes expected and observed
states, verification results and bases, affected outputs, and limitations for
every check. Stage 27 verifies framework structure only. It does not validate
evidence, determine truth, reclassify outputs, infer hidden inputs, alter public
APIs, write to the database, or modify records.

---

## Stage 28 — Administrative Audit Package

Adds a deterministic ten-section administrative package containing the visible
record identifier, current administrative outputs, evidence readiness,
dependency mapping, pathway stability, transition history, output provenance,
deterministic replay, framework integrity verification, and methodological
limitations.

Executive mode presents a concise package overview; Review mode adds the audit
package summary table; Full Inspection mode exposes every visible basis,
included output, preservation basis, and limitation. Stage 28 packages existing
visible outputs only. It is not a legal audit and does not validate evidence,
determine truth, reclassify outputs, infer hidden inputs, alter public APIs,
write to the database, or modify records.

---

## Stage 29 — Methodological Conformance Certification

Adds deterministic certification of the visible framework stack against its
declared methodological boundaries. Nineteen checks cover report modes,
preservation counts, replay consistency, integrity and audit-package state,
visible administrative inputs, limitation visibility, and classification,
non-mutation, database, and public-API boundaries.

Executive mode presents a concise certification overview; Review mode adds the
certification summary table; Full Inspection mode exposes every declared
requirement, observed state, conformance result and basis, affected output, and
limitation. Stage 29 certifies visible internal conformance only. It is not a
legal certification or external compliance audit and does not validate
evidence, reclassify outputs, alter public APIs, write to the database, or
modify records.

---

## Stage 30 — Reflexive Closure

Adds a deterministic endpoint for the visible framework inspection sequence.
Twenty-three checks confirm report-mode preservation, Stage 22–29 structure,
replay coverage, visible administrative inputs, methodological boundaries, and
the explicit distinction between reflexive inspection closure and underlying
case or legal closure.

Executive mode presents a concise closure overview; Review mode adds the
closure summary table; Full Inspection mode exposes every expected and observed
state, closure result and basis, affected output, and limitation. Stage 30
closes only the visible inspection sequence. It does not close the case,
determine legal or evidential sufficiency, validate evidence, reclassify
outputs, alter public APIs, write to the database, or modify records.

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

Active development (v12)

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

---

## Associated Research

The Civic Record Evaluation Framework (CREF) is accompanied by published research materials:

- Version 1.0 – Foundational methodology paper
- Version 2.0 – Reflexive methodology and framework self-description paper

Research materials:
- DOI: https://doi.org/10.5281/zenodo.21033426
- Open Science Framework: https://osf.io/wz29x/
