# Civic Decision Engine Architecture

The Civic Decision Engine is a prototype framework designed to analyse
decision environments involving institutions, procedures, and evidence.

The Civic Decision Engine builds on the Civic Recall Pipeline model.

Reference implementation:
https://github.com/nickdebrief/civic_recall_pipeline

Core components include:

1. Decision Trigger
2. Institutional Field
3. Actor Incentives
4. Evidence Bundle
5. Timeline / Chronology
6. Escalation Pathways
7. Decision Structure Mapping
8. Learning Capture


The Civic Decision Engine processes structured civic case records and produces
interpretable analysis signals.

The Civic Decision Engine evaluates cases through a layered processing pipeline:

1. Case Input
2. Schema Validation
3. Case Summary
4. Pattern Analysis
5. Lifecycle Diagnostics
6. Escalation Ranking
7. Overall View

                    Civic Decision Engine
                           (V9)
                             │
                             │
                ┌────────────▼────────────┐
                │        Case Input        │
                │      JSON Case File      │
                │   (examples/sample_case) │
                └────────────┬────────────┘
                             │
                             │
                ┌────────────▼────────────┐
                │      Schema Layer        │
                │  civic_case.schema.json  │
                │                          │
                │  • structure validation  │
                │  • required fields       │
                │  • lifecycle model       │
                └────────────┬────────────┘
                             │
                             │
                ┌────────────▼────────────┐
                │     Case Summary         │
                │                          │
                │  • strike reference      │
                │  • institution           │
                │  • lifecycle state       │
                │  • actors                │
                │  • evidence bundle       │
                │  • timeline              │
                └────────────┬────────────┘
                             │
                             │
                ┌────────────▼────────────┐
                │     Pattern Analysis     │
                │                          │
                │  • evidence strength     │
                │  • deadline pressure     │
                │  • pattern signal        │
                │  • escalation readiness  │
                └────────────┬────────────┘
                             │
                             │
                ┌────────────▼────────────┐
                │  Lifecycle Diagnostics   │
                │      (V9 addition)       │
                │                          │
                │  • stage stability       │
                │  • deadline proximity    │
                │  • case momentum         │
                │  • recommended stance    │
                └────────────┬────────────┘
                             │
                             │
                ┌────────────▼────────────┐
                │   Escalation Ranking     │
                │                          │
                │  • jurisdiction score    │
                │  • evidence score        │
                │  • deadline score        │
                │  • risk score            │
                └────────────┬────────────┘
                             │
                             │
                ┌────────────▼────────────┐
                │       Overall View       │
                │                          │
                │  Final interpretation of │
                │  case posture & options  │
                └──────────────────────────┘

The system is based on the Civic Recall Pipeline concept developed by
Nick Moloney.

                    Civic Case Lifecycle

            ┌───────────────────────────┐
            │           intake          │
            │  Case is created and     │
            │  evidence bundle begins  │
            └─────────────┬────────────┘
                          │
                          ▼
            ┌───────────────────────────┐
            │      internal_process     │
            │  Institution handling    │
            │  complaint internally    │
            └─────────────┬────────────┘
                          │
                          ▼
            ┌───────────────────────────┐
            │     awaiting_response     │
            │  Waiting for response     │
            │  within procedural window │
            └─────────────┬────────────┘
                          │
                          ▼
            ┌───────────────────────────┐
            │     escalation_ready      │
            │  Internal deadline        │
            │  expired or inadequate    │
            │  response received        │
            └─────────────┬────────────┘
                          │
                          ▼
            ┌───────────────────────────┐
            │      external_review      │
            │  Oversight or regulator   │
            │  reviews the complaint    │
            └─────────────┬────────────┘
                          │
                          ▼
            ┌───────────────────────────┐
            │         resolved          │
            │  Case outcome determined  │
            │  or process completed     │
            └─────────────┬────────────┘
                          │
                          ▼
            ┌───────────────────────────┐
            │          archived         │
            │  Case preserved for       │
            │  learning and pattern     │
            │  analysis                 │
            └───────────────────────────┘

The lifecycle model describes the procedural progression of a civic case.
Lifecycle diagnostics within the engine evaluate the stability of the
current stage, proximity to procedural deadlines, and the appropriate
strategic posture (observe, hold and prepare, escalate, stabilise, close out).

Future development will include:

- institutional network mapping
- escalation success heuristics
- portfolio analytics
- decision environment simulation
