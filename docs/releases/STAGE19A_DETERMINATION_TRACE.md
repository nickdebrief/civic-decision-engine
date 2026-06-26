# Stage 19A — Determination Trace

## Purpose

Stage 19A introduces the Determination Trace as the first component of the
Methodology Provenance & Explainability layer.

The purpose is to make CREF determinations inspectable by showing how a visible
determination pathway is formed from the visible record, observed evidence,
applied rule families, existing conditions, trajectory information, and the
resulting determination summary.

CREF does not ask an administrator to trust a conclusion. It shows how the
visible conclusion pathway was derived from visible record information.

## Relationship to CREF Methodology

CREF is a deterministic methodology for evaluating what can be concluded from
civic records using only visible record information.

Stage 19A supports that methodology by exposing a structured pathway:

Visible Record -> Observed Evidence -> Applied Rules -> Conditions ->
Trajectory -> Determination

The trace is administrative and explanatory. It does not create new findings,
does not establish truth, and does not alter any existing CREF classification.

## Trace Model

The determination trace is built by `build_determination_trace`.

The helper returns a deterministic dictionary containing:

- `record_reference`
- `case_title`
- `visible_record`
- `observed_evidence`
- `applied_rules`
- `conditions`
- `trajectory`
- `determination`
- `trace_path`
- `limitations`

The trace path is ordered and always follows the same six-step structure:

1. Visible Record
2. Observed Evidence
3. Applied Rules
4. Conditions
5. Trajectory
6. Determination

## Inputs

Stage 19A uses existing visible data already available to the admin record
evidence flow, including where present:

- record reference
- case title
- civic domain
- decision trigger
- institutions
- lifecycle/status fields
- detected conditions
- trajectory classification
- moment of change
- pattern interpretation
- existing administrative evaluation outputs
- existing Stage 18 record evolution outputs

No external sources are used.

## Outputs

Stage 19A renders a read-only admin section titled `Determination Trace`.

The section includes:

- Trace Summary
- Visible Record
- Observed Evidence
- Applied Rules
- Conditions
- Trajectory
- Trace Path
- Limitations

The output is visibility-only. It exposes the pathway already available from
the record and existing analysis outputs.

## Determination Derivation Rules

The determination summary is derived deterministically in this order:

1. If existing record evolution outputs are available, render
   `Determination derived from visible record evolution`.
2. If administrative evaluation outputs are available, render
   `Determination derived from visible administrative evaluation`.
3. If existing conditions and trajectory information are available, render
   `Determination derived from visible conditions and trajectory`.
4. If existing conditions are available, render
   `Determination derived from visible record structure`.
5. If none of those outputs are available, render
   `No determination available`.

These values summarize the visible derivation pathway. They do not introduce a
new legal, factual, or evidential determination.

## Limitations

Stage 19A always displays limitations stating that it:

- does not determine truth
- does not determine liability
- does not infer intent
- does not assign blame
- does not validate evidence
- does not modify the record
- evaluates only visible record-derived analysis pathways

## Deterministic Constraints

Stage 19A is deterministic, read-only, visibility-only, idempotent, and
non-mutating.

It does not perform:

- database writes
- schema changes
- migrations
- background jobs
- public route changes
- upload/download changes
- canonical hash changes
- attachment hash changes
- external API calls
- external data retrieval

It does not infer hidden intent, liability, wrongdoing, truth, or correctness.

## Admin-Only Visibility

The Determination Trace renders only inside the Admin Record Evidence view. It
does not add public routes, public API fields, public downloads, or publication
behavior.

## Non-Mutating Behavior

Stage 19A only reads existing visible record data and existing analysis outputs.
It does not mutate records, versions, evidence, attachments, verification
hashes, or canonical serialization.

## Expected Fixture Behavior

For the current single-record admin evidence fixtures, Stage 19A renders:

- a visible record reference
- existing condition targets
- existing signal targets where available
- existing finding and trajectory values where available
- existing administrative evaluation outputs
- existing Stage 18 evolution outputs
- a six-step trace path
- fixed limitations

Where Stage 18 outputs are visible, the determination summary renders:

`Determination derived from visible record evolution`

Where no existing outputs are available, the determination summary renders:

`No determination available`
