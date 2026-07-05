# Stage 37 — Framework Stewardship Declaration

## Purpose

Stage 37 adds a deterministic, read-only declaration of how the Civic Record
Evaluation Framework methodology is preserved and maintained. It follows the
Stage 36 self-containment certification by making stewardship responsibilities
and their boundaries visible without assigning ownership or authority.

## Scope

The declaration is derived exclusively from declared framework metadata and
visible outputs from Stages 21–36. It contains 25 stewardship declarations and
seven relationship declarations covering methodology custody, documentation,
governance continuity, structural preservation, implementation independence,
future-stage boundaries, and visible source material.

## Stewardship Relationships

The seven declared relationships are:

1. Methodology Custodian — preservation and maintenance of declared CREF.
2. Software Independence — stewardship does not require a particular runtime.
3. Documentation Stewardship — visible documentation and boundaries are maintained.
4. Governance Continuity — Stage 31–37 outputs remain inspectable.
5. Non-Mutation Boundary — stewardship does not modify records or prior outputs.
6. Future Boundary — Stages 38–40 remain undeclared and unimplemented.
7. Stewardship Source — declarations use visible outputs and metadata only.

## Deterministic Behaviour

The complete fixture produces:

- 25 stewardship declarations;
- 21 declared responsibilities;
- 4 declarations with limitations;
- 0 unavailable declarations;
- 0 stewardship gaps; and
- 7 relationship declarations.

Identical inputs produce identical dictionaries. Input dictionaries are copied
and are not mutated.

## Report Modes

- **Executive Report:** stewardship overview and concise limitations.
- **Review Report:** overview, seven relationships, and full limitations.
- **Full Inspection Report:** overview, relationships, all 25 declaration rows,
  and full limitations.

Full Inspection remains the default report mode. Stage 37 follows Stage 36 in
all three modes.

## Limitations

Stage 37 is not legal ownership, accreditation, institutional authority, or an
external adoption approval. It does not validate evidence, determine truth or
liability, infer intent or undocumented implementations, certify software
portability, or modify records. It does not change classifications, thresholds,
dependencies, evidence relationships, transition history, provenance, replay,
integrity, audit, certification, continuity, governance, lineage, lifecycle, or
self-containment outputs.

## Preservation And Non-Mutation Guarantees

The implementation preserves all prior Stage 22–36 counts and behavior. It adds
no schema or migration, performs no database write, changes no route or public
API contract, alters no canonical or attachment hash, and introduces no upload,
download, external retrieval, classification, dependency, or mutation behavior.

## Validation Results

Validation covers compilation, whitespace checks, conflict-marker checks, the
admin test suite, the full test suite, preservation counts, and desktop/mobile
rendering for Executive, Review, and Full Inspection report modes.

## Implementation Summary

Stage 37 adds a deterministic builder and scoped admin renderers to
`api/routes/admin_session.py`, regression tests to `tests/test_admin_session.py`,
this release document, and a README summary. No application persistence or
public behavior is changed.
