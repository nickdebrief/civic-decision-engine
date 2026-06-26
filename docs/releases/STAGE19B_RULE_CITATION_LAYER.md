# Stage 19B — Rule Citation Layer

## Purpose

Stage 19B adds the Rule Citation Layer to the Methodology Provenance &
Explainability layer.

Stage 19A shows how a determination pathway is formed. Stage 19B shows which
visible rule families, definitions, specifications, and deterministic
requirements support that pathway.

CREF does not ask an administrator to trust a determination. It exposes how the
determination was derived and what visible rule sources the derivation relies
on.

## Relationship to CREF Methodology

CREF evaluates civic records using visible record information only. The Rule
Citation Layer supports that methodology by making the rule references behind a
visible determination inspectable.

The layer cites visible rule families and existing outputs. It does not create
new rules, create new conditions, or add new conclusions.

## Relationship to Stage 19A

Stage 19B is downstream of Stage 19A.

Stage 19A produces a deterministic determination trace:

Visible Record -> Observed Evidence -> Applied Rules -> Conditions ->
Trajectory -> Determination

Stage 19B cites the rule families and visible outputs used by that trace:

Visible Determination Trace -> Applied Rule Families -> Condition Citations ->
Trajectory Citations -> Administrative Citations -> Record Evolution Citations
-> Rule Citation Layer

## Rule Citation Model

The helper `build_rule_citation_layer` returns a deterministic dictionary
containing:

- `record_reference`
- `case_title`
- `citation_summary`
- `rule_citations`
- `condition_citations`
- `trajectory_citations`
- `administrative_citations`
- `record_evolution_citations`
- `citation_path`
- `limitations`

The citation path is ordered and always follows the same seven-step structure:

1. Visible Determination Trace
2. Applied Rule Families
3. Condition Citations
4. Trajectory Citations
5. Administrative Citations
6. Record Evolution Citations
7. Rule Citation Layer

## Citation Sources

Stage 19B uses only visible data already present in the admin/session analysis
flow:

- Stage 19A determination trace
- applied rule families
- existing conditions
- existing trajectory outputs
- existing pattern interpretation outputs
- existing administrative evaluation outputs
- existing Stage 18 record evolution outputs
- existing repository documentation/specification references

No external sources are used.

## Condition Citation Model

Each existing condition receives a condition citation containing:

- condition
- citation label
- definition reference
- specification reference
- source type
- deterministic requirements
- limitations

Stage 19B does not infer condition definitions. When no visible definition is
available, it renders:

`Definition not available in visible rule set`

Condition citations do not create or modify conditions.

## Trajectory Citation Model

When trajectory information is present, Stage 19B renders a trajectory citation
covering:

- trajectory
- system state
- signals
- citation label
- specification reference
- deterministic requirements
- limitations

If trajectory information is absent, the trajectory citation list is empty.

## Administrative Citation Model

When administrative evaluation outputs are present, Stage 19B renders citation
entries for visible outputs such as:

- Evidence Readiness
- Administrative Action
- Workflow State
- Administrative Disposition
- Review Eligibility
- Administrative Status

Each citation identifies the visible output and the deterministic constraints
that govern it. Stage 19B does not create administrative findings.

## Record Evolution Citation Model

When Stage 18 record evolution outputs are present, Stage 19B renders citation
entries for visible classifications from the Record Evolution framework,
including Summary through Accountability outputs.

Record evolution citations use existing Stage 18 outputs only. They do not
alter classifications, repair lineage, or create new record evolution states.

## Citation State Rules

Stage 19B supports three deterministic citation states:

- `No Rule Citations Available`
- `Partial Rule Citation Layer`
- `Rule Citation Layer Available`

The state is evaluated as follows:

1. If no rule citations and no detail citations are present, render
   `No Rule Citations Available`.
2. If rule citations and one or more detail citations are present, render
   `Rule Citation Layer Available`.
3. Otherwise, render `Partial Rule Citation Layer`.

Detail citations include condition, trajectory, administrative, and record
evolution citations.

## Limitations

Stage 19B always displays limitations stating that it:

- does not determine truth
- does not determine liability
- does not infer intent
- does not assign blame
- does not validate evidence
- does not create new rules
- does not create new conditions
- does not modify the record
- cites only visible rule families and existing outputs

## Deterministic Constraints

Stage 19B is deterministic, read-only, visibility-only, idempotent, and
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
- new public endpoints

## Admin-Only Visibility

The Rule Citation Layer renders only inside the Admin Record Evidence view. It
does not add public routes, public API fields, public downloads, publication
behavior, or access-control changes.

## Non-Mutating Behavior

Stage 19B reads the Stage 19A trace and existing visible analysis outputs. It
does not mutate records, versions, evidence, attachments, verification hashes,
attachment hashes, or canonical serialization.

## Expected Fixture Behavior

For current admin evidence fixtures with visible conditions, trajectory,
administrative outputs, and Stage 18 outputs, Stage 19B renders:

- `Rule Citation Layer Available`
- rule family citations
- condition citations
- trajectory citations
- administrative citations
- record evolution citations
- a seven-step citation path
- fixed limitations

For records with no represented rule families or visible outputs, Stage 19B
renders:

`No Rule Citations Available`
