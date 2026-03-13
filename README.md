# Civic Decision Engine

![Version](https://img.shields.io/badge/version-v0.8-blue)
![License](https://img.shields.io/badge/license-MIT-green)

A decision analysis system built around the Civic Recall framework.

> A structured tool for mapping institutional disputes, evidence, procedures, and escalation strategies into clear decision records.

## Version 9 – Behaviour Scoring

Version 9 introduces a behavioural analysis layer to the Civic Decision Engine.

The engine now evaluates institutional response signals such as:

- procedural containment
- engagement level
- escalation signal

These signals are translated into a transparent **behaviour index**, helping
identify when institutional response patterns may indicate delay or
containment dynamics.

Pipeline:

Pattern → Lifecycle → Behaviour → Escalation → Overall interpretation

## Quick Start

Clone the repository and run the engine:

```
git clone https://github.com/nickdebrief/civic-decision-engine
cd civic-decision-engine
python3 civic_engine_v8.py
```
The Civic Decision Engine helps citizens transform complicated institutional interactions into structured, auditable decision records.

Instead of relying on memory, fragmented notes, or informal interpretation, the engine creates a clear analytical framework for understanding:
	•	institutions involved
	•	governing procedures
	•	actors and incentives
	•	evidence strength
	•	escalation routes
	•	procedural deadlines
	•	cross-case patterns

The goal is to help individuals maintain clarity, procedural footing, and institutional accountability when navigating complex systems.

## Core Concept

Civic disputes often become confusing because:
	•	institutions narrow issues procedurally
	•	timelines become fragmented
	•	evidence becomes scattered
	•	escalation routes become unclear

The Civic Decision Engine converts those situations into a structured decision map.

Each case becomes a Civic Decision Record containing:
	•	institutional field
	•	actors and incentives
	•	evidence bundle
	•	chronology
	•	deadlines
	•	escalation paths
	•	structural insight
	•	learning capture

This allows both single-case clarity and cross-case pattern analysis.

## Features (Version 8)

Version 8 introduces portfolio-level analysis in addition to case-level decision tools.

Case Analysis
	•	Interactive civic case capture
	•	Evidence strength scoring
	•	Escalation path ranking
	•	Jurisdiction fit assessment
	•	Timeline anomaly detection
	•	Evidence / chronology consistency checking
	•	Decision structure summaries
	•	Framing guidance for escalation

Cross-Case Intelligence
	•	Cross-case similarity matching
	•	Institution behaviour memory
	•	Escalation success heuristics
	•	Deadline pressure analysis
	•	Institution lineage graph

Export Tools
	•	JSON case storage
	•	Markdown report export
	•	CSV case library export
	•	Portfolio Markdown dashboard
	•	HTML dashboard visualization

## Installation

Clone the repository:

	git clone https://github.com/nickdebrief/civic-decision-engine
	cd civic-decision-engine

Run the engine: 

	python3 civic_engine.py

No external dependencies are required beyond the Python standard library.

Running the script opens an interactive menu.


    Civic Recall Pipeline Decision Engine — Version 8

    1) Run interactive recall capture
    2) Show demo case
    3) Load prior JSON case memory
    4) Recall patterns from a directory of prior JSON cases
    5) Compare one case with a library of prior cases
    6) Generate learning summaries across a case library
    7) Export Markdown portfolio dashboard
    8) Export HTML dashboard and lineage analysis

Typical workflows include:

Capture a new civic case

Option 1 allows you to document a situation as a structured recall record.

Analyse a case library

Options 4–8 allow pattern analysis across many cases.

Export dashboards

Cases can be exported to:
	•	JSON
	•	Markdown
	•	CSV
	•	HTML dashboards

## Example Case Structure

Each case is stored as structured JSON:
	{
	  "strike_reference": "Strike-701",
	  "case_title": "Regulatory oversight escalation",
	  "civic_domain": "governance / regulatory oversight",
	  "decision_trigger": "...",
	  "institutions": [],
	  "actors": [],
	  "evidence_bundle": [],
	  "timeline": [],
	  "escalation_paths": []
	}
This allows cases to be analysed individually or collectively.

## Project Goals

The Civic Decision Engine is designed to support:
	•	structured civic documentation
	•	procedural clarity in institutional disputes
	•	evidence preservation
	•	escalation decision analysis
	•	institutional pattern recognition

The project is intended as a practical tool for civic accountability analysis.

## Roadmap

Future development is planned for:

Version 9
	•	institution risk profiling
	•	escalation weighting by historical outcomes
	•	case clustering analysis
	•	timeline compression summaries
	•	JSON schema validation

Later Development
	•	visual institutional network graphs
	•	timeline visualisation
	•	case-comparison dashboards
	•	optional web interface

    civic-decision-engine/
    │
    ├── civic_decision_engine_v8.py
    ├── README.md
    ├── LICENSE
    │
    ├── examples/
    │   ├── demo_case.json
    │
    ├── docs/
    │   ├── civic_decision_framework.md
    │
    └── outputs/
        ├── example_dashboard.html

## License

MIT License

Copyright (c) 2026 Nick Moloney

Permission is granted to use, modify, and distribute this software under the terms of the MIT License.

## Acknowledgement

This project grew from long-term work documenting institutional decision processes and exploring how complex civic situations can be analysed in a structured, transparent way.

The goal is simple:

to help citizens think clearly when institutions become difficult to navigate.

