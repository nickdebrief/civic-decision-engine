# CDE Platform Stage 74 — Governed Terminology Representations and Characterisations

Status: Implemented · pending merge · pending deployment

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
