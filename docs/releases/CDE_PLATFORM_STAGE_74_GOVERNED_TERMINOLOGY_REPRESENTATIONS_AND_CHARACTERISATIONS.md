# CDE Platform Stage 74 — Governed Terminology Representations and Characterisations

Status: Implemented · merged · deployed

## Boundary

Stage 74 records that an identified person or source deliberately used,
proposed, disputed or reviewed a controlled term in relation to an identified
governed object. A term names the question; the record must support the answer.

A term is not a finding. A relationship is not proof. Chronology is not
causation. Publication is not endorsement.

Stage 74 is an authenticated, append-only representation layer. It is not an
observation, inference, allegation, response, legal classification, formal
finding, determination, remedy, tag system or publication decision. It performs
no automated classification, inference, relationship creation or publication.

## Vocabulary

Vocabulary version `1.0` contains:

`victimisation`, `retaliation`, `harassment`, `intimidation`, `coercion`,
`control`, `procedural_obstruction`, `reframing`, `institutional_silence`, and
`repeated_contact_without_resolution`.

Metadata is versioned in application code and is not editable through the
administrative interface. A future vocabulary change requires an explicit
version. Existing metadata is not silently rewritten.

The terms are neutral editorial labels, not jurisdiction-neutral legal
definitions. In particular, institutional silence does not establish agreement,
refusal, knowledge, concealment or wrongdoing; reframing does not establish
intent, manipulation or deception; repetition is not corroboration or proof;
and control does not imply coercion or wrongdoing.

## Representation and provenance

Each record preserves a controlled term, vocabulary version, verbatim or
faithful-paraphrase wording, attribution, epistemic basis, rationale,
limitations, one primary governed object, deliberate source bindings and
related-object references.

Source bindings remain distinct from related governed objects. Stage 72 owns
pathway relationships and is not duplicated. Stage 67 remains the exclusive
owner of formal determinations. A Stage 67 determination may be referenced,
but Stage 74 cannot adopt a term as a determination through its own status.

## Lifecycle

Records begin as `recorded_as_represented`. Explicit human actions may propose,
dispute, review, withdraw or supersede a representation. Review outcomes are
limited to `reviewed_as_qualified_representation`, `rejected_as_representation`
and `unresolved`.

Withdrawal and supersession preserve the original record and event history.
Creator/reviewer separation is enforced for procedural review. Idempotent replay
returns the existing result; conflicting reuse fails safely.

## Administrative and public boundary

The authenticated administrative surface is available at
`/admin/governed-characterisations` and its detail, lifecycle and diagnostic
routes. Selectors are empty by default, declarations are explicit, and GET
inspection is read-only.

There is no public Stage 74 route, navigation entry, API field or Stage 73
publication integration. Terminology, wording, attribution, sources and
relationships are not copied into public output.

## Limitations

Stage 74 does not establish truth, legal applicability, corroboration,
liability, wrongdoing or legal effect. Absence from the governed record proves
none absent. Future work may separately consider vocabulary governance,
jurisdiction-specific qualification and explicitly reviewed publication
representations.

## Integration and deployment record

The implementation was merged through rebase as follows:

* implementation revision: `a257503216f0d8def9e57eacfdc2b44050509b32`;
* selector correction branch: `maintenance-stage-74-governed-selector-ui`;
* selector correction commit: `fc0b19c414c09db43f93a7df6738a9bf06334525`;
* selector correction pull request: `#388`;
* final deployed implementation revision: `4107f441b2c6d298aa7f072cf99577c796eb1d36`;
* deployment ID: `6022424210`;
* environment: `precious-gentleness / production`;
* deployment created: `2026-08-21T13:32:56Z`;
* deployment successful: `2026-08-21T13:33:25Z`.

The final validation used the same 22-file Stage 60–74 inventory in forward,
reverse and deterministic mixed order, with `312` tests passing in each run.
The full applicable regression passed `1,489` tests, excluding the legacy
`test_cases/test_cases.py` import-time localhost request. The Stage Ledger
validator, changed-file compilation, `git diff --check` and conflict scan all
passed. The earlier reported `495` compatibility count included Stage 49–59
files and was not the Stage 60–74 inventory; the current 22-file inventory is
the authoritative compatibility set.

Authenticated visual verification confirmed the governed selector workflow,
empty defaults, bounded responsive panels, compact declaration control and
the single copper Governed Terminology navigation marker. Production smoke
checks returned `200` for `/`, `/records` and `/determinations`; synthetic and
malformed publication details returned `404`; protected Stage 74 routes
returned `401`; and plausible public Stage 74 routes returned `404`.

No terminology representation was created in production. No production form
was submitted and no production data was mutated. Stage 67, Stage 72 and
Stage 73 persistence and semantics remain unchanged. No Stage 74.1 entry was
created.
