# CDE Platform Stage Ledger

## Purpose

This document is the authoritative stage index, release index, and chronology
for the current CDE Platform sequence. Earlier CDE Platform milestones remain
documented in their individual release notes; this ledger records the sequence
from CDE Platform Stage 40 onward, where monotonic numbering protection begins.

## Canonical Sequence

| Stage | Title | Capability | Parent | Merged | Merge commit | PR | Release note | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 40 | Gmail Takeout | mail-archive-acquisition | — | 2026-08-01 | `5c38322a24dbd2cee13800477de2c038d399692f` | [#298](https://github.com/nickdebrief/civic-decision-engine/pull/298) | [Stage 40](CDE_PLATFORM_STAGE_40_GMAIL_TAKEOUT.md) | Implemented · merged · deployed |
| 41 | IMAP Acquisition | mail-archive-acquisition | — | 2026-08-01 | `2b419217e8123b225e002a33117830f4ea2610ed` | [#299](https://github.com/nickdebrief/civic-decision-engine/pull/299) | [Stage 41](CDE_PLATFORM_STAGE_41_IMAP_ACQUISITION.md) | Implemented · merged · deployed |
| 42 | Unified Attachment Governance | attachment-governance | — | 2026-08-01 | `2cdf51bac128d47274a1f1bee930b5e8190db201` | [#300](https://github.com/nickdebrief/civic-decision-engine/pull/300) | [Stage 42](CDE_PLATFORM_STAGE_42_UNIFIED_ATTACHMENT_GOVERNANCE.md) | Implemented · merged · deployed |
| 43 | Clinical Canonical Record Types | canonical-record-classification | — | 2026-08-02 | `1765151fab6ba4f6f4d3a7676cd771297f0f2454` | [#303](https://github.com/nickdebrief/civic-decision-engine/pull/303) | [Stage 43](CDE_PLATFORM_STAGE_43_CLINICAL_CANONICAL_RECORD_TYPES.md) | Implemented · merged · deployed |
| 44 | Canonical Record Type Recommendation | canonical-record-type-recommendation | — | 2026-08-02 | `27c5b1942a99e79b972885204b8a676c3da390d1` | [#304](https://github.com/nickdebrief/civic-decision-engine/pull/304) | [Stage 44](CDE_PLATFORM_STAGE_44_CANONICAL_RECORD_TYPE_RECOMMENDATION.md) | Implemented · merged · deployed |
| 44.1 | Composite Category Recommendation Coverage | canonical-record-type-recommendation | 44 | 2026-08-02 | `c097bcaef467010491a0380ebc20977e5629e3d0` | [#305](https://github.com/nickdebrief/civic-decision-engine/pull/305) | [Stage 44.1](CDE_PLATFORM_STAGE_44_1_COMPOSITE_CATEGORY_RECOMMENDATION_COVERAGE.md) | Implemented · merged · deployed |
| 45 | Canonical Record Creation State on Published Documents | canonical-record-source-state | — | 2026-08-03 | `22991d661cbff7d492af758e7feae9cc4a85ae6e` | [#307](https://github.com/nickdebrief/civic-decision-engine/pull/307) | [Stage 45](CDE_PLATFORM_STAGE_45_CANONICAL_RECORD_CREATION_STATE.md) | Implemented · merged · deployed |
| 46 | Publication Provenance Value Contrast | publication-provenance-presentation | — | 2026-08-03 | `578b5d5f9b96e667e9d46ed2d9d987dcd7c05119` | [#308](https://github.com/nickdebrief/civic-decision-engine/pull/308) | [Stage 46](CDE_PLATFORM_STAGE_46_PUBLICATION_PROVENANCE_VALUE_CONTRAST.md) | Implemented · merged · deployed |
| 47 | Governed Source Relationship Selection | record-document-association-governance | — | 2026-08-03 | `ed91da9e225d5a3874b02d2bb21406fc1acfe2d5` | [#309](https://github.com/nickdebrief/civic-decision-engine/pull/309) | [Stage 47](CDE_PLATFORM_STAGE_47_GOVERNED_SOURCE_RELATIONSHIP_SELECTION.md) | Implemented · merged · deployed |
| 47.1 | Authoritative Source Visual Emphasis | record-document-association-governance | 47 | 2026-08-03 | `51b4cbab660c671c8272bc0cf605abea4e49f821` | [#310](https://github.com/nickdebrief/civic-decision-engine/pull/310) | [Stage 47.1](CDE_PLATFORM_STAGE_47_1_AUTHORITATIVE_SOURCE_VISUAL_EMPHASIS.md) | Implemented · merged · deployed |
| 48 | Association Card Visual Refinement and Scalable Relationship Presentation | record-document-association-presentation | — | 2026-08-05 | `dcc4809223449374561beda7db675e0bfc628475` | [#311](https://github.com/nickdebrief/civic-decision-engine/pull/311) | [Stage 48](CDE_PLATFORM_STAGE_48_ASSOCIATION_CARD_VISUAL_REFINEMENT_AND_SCALABLE_RELATIONSHIP_PRESENTATION.md) | Implemented · merged · deployed |
| 49 | Independent Email Attachment Preservation and Governed Relationships | email-attachment-preservation | — | — | `—` | — | [Stage 49](CDE_PLATFORM_STAGE_49_INDEPENDENT_EMAIL_ATTACHMENT_PRESERVATION_AND_GOVERNED_RELATIONSHIPS.md) | Implemented · pending merge · pending deployment |

## Historical Numbering Correction

The work now designated CDE Platform Stages 43, 44, and 44.1 was originally
documented as Stages 40A, 40B, and 40B.1 after CDE Platform Stages 41 and 42 had
already been merged and deployed. Those suffixes incorrectly implied that the
clinical Canonical Record work extended CDE Platform Stage 40 — Gmail Takeout.

The canonical documentation was corrected to preserve the integrity and
chronology of the CDE Platform sequence. Git commits, commit hashes, pull
requests, branches, deployment records, and release history remain unchanged.

## Ledger Rules

- New canonical stages must be appended in increasing numerical order.
- A top-level stage number may appear only once.
- A decimal suffix must identify its parent stage and use the same capability.
- Every ledger entry must link to one release note whose heading uses the same
  canonical stage number and title.
- One terminal implemented stage may carry pending merge and deployment fields
  while its feature branch is under review; completed entries require immutable
  merge metadata.
- Historical Git subjects may retain superseded numbering because Git history
  is immutable; canonical repository documentation must use this ledger.
