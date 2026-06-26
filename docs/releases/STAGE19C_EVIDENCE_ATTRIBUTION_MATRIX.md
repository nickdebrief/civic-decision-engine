# Stage 19C - Evidence Attribution Matrix

## Purpose

Stage 19C adds the Evidence Attribution Matrix to the Methodology Provenance &
Explainability layer. It shows which visible evidence elements are attributed to
existing conditions, trajectory outputs, administrative outputs, record evolution
outputs, determination trace steps, and rule citations.

The matrix attributes evidence to outputs. It does not validate evidence,
determine truth, decide real-world sufficiency, or create new evidence.

## Relationship to CREF Methodology

CREF requires visible conclusions to remain inspectable from the record itself.
Stage 19C supports that principle by making the evidence-to-output relationship
visible in a deterministic matrix.

## Relationship to Stage 19A

Stage 19A builds the Determination Trace: visible record, observed evidence,
applied rules, conditions, trajectory, and determination. Stage 19C consumes that
trace and attributes visible evidence sources to the trace steps where possible.

## Relationship to Stage 19B

Stage 19B builds the Rule Citation Layer. Stage 19C consumes the citation layer
and attributes visible evidence sources to rule family citations, condition
citations, trajectory citations, administrative citations, and record evolution
citations where possible.

## Evidence Attribution Model

The matrix is derived only from visible record data and existing analysis
outputs. It collects visible evidence sources and maps them to existing outputs.
Unsupported outputs are reported when an output exists but the matrix cannot
attribute a visible evidence source to it.

Unsupported does not mean false, invalid, or unreliable. It means only that the
matrix did not attribute a visible source.

## Evidence Source Extraction

Evidence sources may be extracted from visible fields already present in the
admin/session flow, including:

- visible record identifiers and context
- observed evidence from the determination trace
- detected conditions
- trajectory fields and signals
- administrative outputs
- record evolution classifications
- rule family labels
- determination trace outputs
- visible attachment metadata where already available

Absent fields are not invented.

## Attribution Categories

Stage 19C renders attribution categories for:

- condition attribution
- trajectory attribution
- administrative attribution
- record evolution attribution
- determination trace attribution
- rule citation attribution
- unsupported outputs

Each attribution entry identifies output type, output name, output value,
attributed evidence identifiers, attribution basis, support state, and
limitations.

## Support State Rules

Support states are deterministic:

- `Attributed` means one or more visible evidence sources were attributed.
- `Partially Attributed` means visible evidence was attributed but the output is
  represented by a broader multi-source category.
- `No Visible Evidence Attributed` means no visible evidence source was mapped by
  the matrix.

## Unsupported Output Handling

Unsupported outputs are listed separately with a reason and limitation. Stage
19C does not treat unsupported outputs as false, invalid, or disproven.

## Attribution State Rules

The attribution summary reports one of:

- `No Evidence Attribution Available`
- `Partial Evidence Attribution Matrix`
- `Evidence Attribution Matrix Available`

The state is derived from the presence of visible evidence sources, attribution
entries, and unsupported outputs.

## Limitations

Stage 19C does not determine truth, liability, intent, blame, wrongdoing,
factual correctness, or real-world sufficiency. It does not validate evidence,
create evidence, create rules, create conditions, or modify the record.

## Deterministic Constraints

Stage 19C is deterministic, read-only, visibility-only, idempotent, and
non-mutating. It introduces no database writes, schema changes, migrations,
background jobs, public route changes, upload/download changes, canonical hash
changes, attachment hash changes, external API calls, or external data
retrieval.

## Admin-Only Visibility

The Evidence Attribution Matrix is rendered only inside the Admin Record
Evidence view. It adds no public endpoint and does not change public record
visibility.

## Non-Mutating Behavior

Stage 19C reads existing visible record data and existing analysis outputs only.
It does not alter records, versions, evidence, attachments, classifications,
verification hashes, or canonical serialization.

## Expected Fixture Behavior

For current single-record admin fixtures with visible conditions, administrative
outputs, record evolution outputs, and Stage 19A/19B outputs, Stage 19C renders
an available attribution matrix. Evidence source identifiers are deterministic
within the output and attribution path steps remain ordered.
