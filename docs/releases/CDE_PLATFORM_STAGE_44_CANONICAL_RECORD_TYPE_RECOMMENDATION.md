# CDE Platform Stage 44 — Canonical Record Type Recommendation

## Purpose

CDE Platform Stage 44 adds an advisory Record Type recommendation to the
authenticated **Create Canonical Record from Published Document** workflow.
The recommendation reduces repetitive selection while preserving administrator
authority over Canonical Record classification.

## Recommendation Model

The workflow reads only the Published Document category and consults one
centralized, explicit mapping. Existing category mappings remain unchanged, and
the following clinical mappings are added:

| Published Document category | Recommended Canonical Record Type |
| --- | --- |
| Hospital Admission | Clinical Episode |
| Admission Form | Clinical Episode |
| Consent Form | Clinical Record |
| Operation Record | Treatment Episode |
| Procedure Record | Treatment Episode |
| Pain Intervention Record | Medical Event |
| Clinical Assessment | Clinical Record |
| Medical Report | Clinical Record |
| Discharge Summary | Care Episode |
| Post-Operative Instructions | Care Episode |

Category matching converts the value to a string, removes surrounding
whitespace, applies case folding, and then performs an exact normalized-key
lookup. The workflow does not split slash values or use substring, fuzzy, or
keyword matching. If no mapping exists, it preserves the established default
and does not display the recommendation label.

## Administrator Authority

The recommended type is preselected and labelled **Recommended based on
Published Document category**. It is not locked. The administrator may select
any controlled Canonical Record Type before submitting the form, and that
submitted choice is authoritative.

The implementation performs no automatic save, record creation, relationship
creation, category modification, or post-creation update.

## Governance Boundary

The recommendation is UI assistance, not classification evidence. It does not
use AI, machine learning, OCR, document-body text, filename analysis, hidden
inference, or probabilistic reasoning. It does not alter publication,
provenance, hashing, verification, lifecycle, associations, permissions,
indexing, API serialization, or Public Archive behaviour.

Record Type remains semantic metadata and does not change evidence preservation
or governance.

## Documentation Alignment

The Canonical Record and administrator workflow documentation now describe the
advisory mapping. The next source-controlled edition of **Volume II — Platform
Operations** should document the editable recommendation in the creation
workflow. The next source-controlled edition of **Volume III — Investigator
Guide** should explain that recommendations carry no independent evidential or
clinical conclusion.

The repository contains published handbook PDFs rather than editable Volume II
and Volume III sources. Those published binaries are therefore not modified by
this implementation stage.

## Validation

Focused coverage verifies all clinical mappings, normalization, the unmapped
default, selector preselection, advisory visibility, administrator override,
and unchanged Record Type serialization and creation behaviour.
