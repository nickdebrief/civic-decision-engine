# Stage 17A — Record Dependency

## Purpose

Stage 17A begins the Record Governance layer by adding Record Dependency to the
read-only Admin Record Evidence view.

Record Dependency exposes which visible record components and outputs depend on
existing evidence targets and their current evidence states.

## Relationship to Stage 15 Evidence Assessment

Stage 15 answers what evidence exists, whether it is sufficient, whether the
record is complete, and what evidence is still required.

Stage 17A reuses those existing target states. It does not recalculate or alter
Stage 15 sufficiency, completeness, or requirements.

## Relationship to Stage 16 Evidence Governance

Stage 16 exposes standards, justification, confidence, traceability, lineage,
and provenance for evidence.

Stage 17A uses the existing target state values produced by the evidence
governance stack. It does not change Stage 16A through Stage 16F outputs.

## Record Governance Role

Record Dependency is a visibility-only governance layer. It identifies the
record components and visible record outputs associated with each condition,
signal, finding, and record target.

It does not infer hidden dependencies, simulate record changes, predict
outcomes, or mutate record values.

## Dependency Summary Fields

The summary displays:

- Total Conditions
- Total Signals
- Total Findings
- Total Record Outputs
- Total Dependency Relationships
- Evidence-Supported Dependencies
- Unsupported Dependencies

Evidence-supported dependencies are dependency rows whose target has one or more
active support relationships. Unsupported dependencies have zero active support
relationships.

## Condition Dependency Fields

Each condition dependency displays:

- Condition
- Active Supports
- Sufficiency
- Completeness
- Confidence
- Dependent Outputs

Dependent outputs include the record reference, current trajectory, and current
finding.

## Signal Dependency Fields

Each signal dependency displays:

- Signal
- Active Supports
- Sufficiency
- Completeness
- Confidence
- Dependent Outputs

Dependent outputs include the record reference, current trajectory, and current
finding.

## Finding Dependency Fields

Each finding dependency displays:

- Finding
- Active Supports
- Sufficiency
- Completeness
- Confidence
- Dependent Outputs

Dependent outputs include the record reference and current trajectory.

## Record Dependency Fields

Record-level dependency information displays:

- Record Reference
- Dependent Conditions
- Dependent Signals
- Dependent Findings
- Current Trajectory
- Current Finding
- Record Sufficiency
- Record Completeness
- Record Confidence
- Record Active Supports

## Admin-Only Scope

Stage 17A is admin-only and read-only. It does not add upload functionality,
public file access, public download routes, public evidence pages, public record
mutation, or mutation controls.

## Verification Boundaries

Stage 17A does not change canonical verification hashes, public manifests,
schemas, record versioning, attachment storage, relationship storage, or Stage
11-16 deterministic progression logic.

## Example

For `Strike-LA-20260710-004`, the condition `Escalation Without Response`
depends on visible record outputs including the record reference, current
trajectory, and current finding. Its dependency row displays the existing active
support count, sufficiency, completeness, and confidence state without changing
those values.
