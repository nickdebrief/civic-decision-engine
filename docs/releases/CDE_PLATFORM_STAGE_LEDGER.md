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
| 49 | Independent Email Attachment Preservation and Governed Relationships | email-attachment-preservation | — | 2026-08-05 | `7d9902875ce9ee44d72282ace624dbaaffe3a8ca` | [#312](https://github.com/nickdebrief/civic-decision-engine/pull/312) | [Stage 49](CDE_PLATFORM_STAGE_49_INDEPENDENT_EMAIL_ATTACHMENT_PRESERVATION_AND_GOVERNED_RELATIONSHIPS.md) | Implemented · merged · deployed |
| 51 | Standalone Outlook MSG Attachment Preservation | email-attachment-preservation | — | 2026-08-07 | `1382046f64568684521a77f2a610ba699c8f046c` | [#314](https://github.com/nickdebrief/civic-decision-engine/pull/314) | [Stage 51](CDE_PLATFORM_STAGE_51_STANDALONE_OUTLOOK_MSG_ATTACHMENT_PRESERVATION.md) | Implemented · merged · deployed |
| 52 | Standalone Apple Mail EMLX Attachment Preservation | email-attachment-preservation | — | 2026-08-07 | `08cd7f32fe5728d5ca24937d061e95edd042fdc3` | [#316](https://github.com/nickdebrief/civic-decision-engine/pull/316) | [Stage 52](CDE_PLATFORM_STAGE_52_STANDALONE_APPLE_EMLX_ATTACHMENT_PRESERVATION.md) | Implemented · merged · deployed |
| 53 | Apple Mail Mailbox (.mbox) Authoritative Mailbox Preservation | email-attachment-preservation | — | 2026-08-08 | `78ac4e14258017eff811376bdb23e00dd13e1689` | [#317](https://github.com/nickdebrief/civic-decision-engine/pull/317) | [Stage 53](CDE_PLATFORM_STAGE_53_MBOX_AUTHORITATIVE_MAILBOX_PRESERVATION.md) | Implemented · merged · deployed |
| 53.1 | Mailbox Attachment Relationship Navigation | email-attachment-preservation | 53 | 2026-08-08 | `9970d0aa5b442eeac0a02c3150f63bc84973a197` | [#318](https://github.com/nickdebrief/civic-decision-engine/pull/318) | [Stage 53.1](CDE_PLATFORM_STAGE_53_1_MAILBOX_ATTACHMENT_RELATIONSHIP_NAVIGATION.md) | Implemented · merged · deployed |
| 54 | Apple Mail Mailbox Relationship Projection and Navigation | mailbox-relationship-navigation | — | 2026-08-08 | `74769f4b071a87159f6e1bb44e79f557a0594993` | [#319](https://github.com/nickdebrief/civic-decision-engine/pull/319) | [Stage 54](CDE_PLATFORM_STAGE_54_APPLE_MAIL_MAILBOX_RELATIONSHIP_PROJECTION_AND_NAVIGATION.md) | Implemented · merged · deployed |
| 55 | Attachment Published Document Source Context and Navigation | attachment-source-context-navigation | — | 2026-08-08 | `b9e01d81782f2a605fc3bdea88b64af450c1ee5c` | [#321](https://github.com/nickdebrief/civic-decision-engine/pull/321) | [Stage 55](CDE_PLATFORM_STAGE_55_ATTACHMENT_PUBLISHED_DOCUMENT_SOURCE_CONTEXT_AND_NAVIGATION.md) | Implemented · merged · deployed |
| 56 | Durable Document Lifecycle Decision Record | document-lifecycle-governance | — | 2026-08-09 | `647c23dd4222cbcf704eaf0a93a4447b74b55c61` | [#323](https://github.com/nickdebrief/civic-decision-engine/pull/323) | [Stage 56](CDE_PLATFORM_STAGE_56_DURABLE_DOCUMENT_LIFECYCLE_DECISION_RECORD.md) | Implemented · merged · deployed |
| 57 | Governed Lifecycle Decision Confirmation | lifecycle-decision-confirmation | — | 2026-08-09 | `e949f3363f3a10d132e7add78717f858d007abd5` | [#325](https://github.com/nickdebrief/civic-decision-engine/pull/325) | [Stage 57](CDE_PLATFORM_STAGE_57_GOVERNED_LIFECYCLE_DECISION_CONFIRMATION.md) | Implemented · merged · deployed |
| 58 | Governed Document Reconsideration and Lifecycle Episodes | document-lifecycle-episodes | — | 2026-08-10 | `7820418807269f448125cd5019c553a273ff0bea` | [#326](https://github.com/nickdebrief/civic-decision-engine/pull/326), [#327](https://github.com/nickdebrief/civic-decision-engine/pull/327), [#328](https://github.com/nickdebrief/civic-decision-engine/pull/328) | [Stage 58](CDE_PLATFORM_STAGE_58_GOVERNED_DOCUMENT_RECONSIDERATION_AND_LIFECYCLE_EPISODES.md) | Implemented · merged · deployed |
| 59 | Lifecycle Episode Presentation | lifecycle-episode-presentation | — | 2026-08-10 | `c9c740c43297d70b6286c0aadd650568c5dd6cce` | [#330](https://github.com/nickdebrief/civic-decision-engine/pull/330), [#331](https://github.com/nickdebrief/civic-decision-engine/pull/331) | [Stage 59](CDE_PLATFORM_STAGE_59_LIFECYCLE_EPISODE_PRESENTATION.md) | Implemented · merged · deployed |
| 60 | Governed Decision Application-Layer Abstraction | governed-decision-abstraction | — | 2026-08-11 | `ea9a67b33065e263b2d5e56f2a7a012fda56e7c9` | [#334](https://github.com/nickdebrief/civic-decision-engine/pull/334) | [Stage 60](CDE_PLATFORM_STAGE_60_GOVERNED_DECISION_APPLICATION_LAYER_ABSTRACTION.md) | Implemented · merged · deployed |
| 61 | Relationship-Domain Governed Decision Recording | relationship-governed-decisions | — | 2026-08-11 | `b28e6c7bde5bf78062f400641deea19fe7d40f8f` | [#336](https://github.com/nickdebrief/civic-decision-engine/pull/336) | [Stage 61](CDE_PLATFORM_STAGE_61_RELATIONSHIP_DOMAIN_GOVERNED_DECISION_RECORDING.md) | Implemented · merged · deployed |
| 61.1 | Relationship Governed Decision Administrative Inspection | relationship-governed-decisions | 61 | 2026-08-11 | `12879cc00ed3bc1493e1ba205bc5820fdfcc6b98` | [#337](https://github.com/nickdebrief/civic-decision-engine/pull/337) | [Stage 61.1](CDE_PLATFORM_STAGE_61_1_RELATIONSHIP_GOVERNED_DECISION_ADMINISTRATIVE_INSPECTION.md) | Implemented · merged · deployed |
| 61.2 | Governed Relationship Correction | relationship-governed-decisions | 61 | 2026-08-11 | `58b72bdb3eeff4222accc9f66c500d7a795bd9d5` | [#339](https://github.com/nickdebrief/civic-decision-engine/pull/339) | [Stage 61.2](CDE_PLATFORM_STAGE_61_2_GOVERNED_RELATIONSHIP_CORRECTION.md) | Implemented · merged · deployed |

## Historical Numbering Correction

The work now designated CDE Platform Stages 43, 44, and 44.1 was originally
documented as Stages 40A, 40B, and 40B.1 after CDE Platform Stages 41 and 42 had
already been merged and deployed. Those suffixes incorrectly implied that the
clinical Canonical Record work extended CDE Platform Stage 40 — Gmail Takeout.

The canonical documentation was corrected to preserve the integrity and
chronology of the CDE Platform sequence. Git commits, commit hashes, pull
requests, branches, deployment records, and release history remain unchanged.

## Stage 58 Closure Evidence

Stage 58 implementation and correctness lineage: PR #326 merged as
`70f2b447c8d7fc55826c31f5a7c2a1153d2ea351`; episode-aware administrative
reconciliation correction, PR #327, merged as
`9e48ca6b40c0c668a546ad96671158a44fe36ea3`; and episode-aware lifecycle
confirmation correction, PR #328, merged as
`7820418807269f448125cd5019c553a273ff0bea`.

Production verification of DOC-2026-000131 established that Episode 1 remains
preserved through `Pending Intake → Under Review → Rejected → Archived`, while
the same preserved document entered a subsequent governed Episode 2 and
progressed through `Pending Intake → Under Review → Approved → Published`.
The original lifecycle remains historical evidence; Archived remains terminal
within Episode 1; no `Archived → Pending Intake` transition was manufactured;
and Episode 2 is the durable active episode. The document identity, preserved
bytes, recorded digests, and source relationships remained unchanged.

Durable episode identity is authoritative over compatibility metadata.
Historical lifecycle evidence is integrity-checked, active-episode
reconciliation and confirmation revalidation remain strict and fail closed,
and documents without lifecycle episodes retain Stage 56 behavior. Public
eligibility remains active-episode-aware and fail closed, and GET/rendering
remains observational. No preservation, document identity, provenance,
relationship, schema, or lifecycle-state semantics were changed by the
corrective work.

The Public Document Library and other document-facing views may still flatten
episode presentation. That is follow-on presentation work and is not a Stage
58 correctness blocker.

## Stage 59 Closure Evidence

Stage 59 implementation, PR #330, merged as
`557abd50393944e5844e0f9bec359ba424a1ec31`. The post-merge Public Document
Library long-title presentation correction, PR #331, merged as
`c9c740c43297d70b6286c0aadd650568c5dd6cce`.

Stage 59 introduced a read-only lifecycle episode presentation assembler that
preserves implicit Episode 1 without schema backfill and presents the original
and subsequent governed lifecycle episodes separately. Current publication
status is separated from historical lifecycle outcomes, publication
provenance is associated with the active publishing episode, and administrator
history and audit presentation include episode context. Public collection
views expose only public-safe lifecycle summaries and do not expose internal
`LEP-*` identifiers or private governance evidence. Stage 58 fail-closed public
eligibility remains authoritative; lifecycle authority, confirmation,
reconciliation, schema, preservation, relationship, identifier, and
production-data semantics are unchanged.

The Public Document Library replaced the former wide table presentation with
responsive structured document rows. Complete Document Identifiers and
document-opening actions remain available, and the narrow-screen presentation
does not depend on the former 1040px minimum-width table layout.

Production verification of DOC-2026-000131 established Current status:
Published and lifecycle summary `Published · Governed reconsideration`.
Original lifecycle evidence remains separately visible, including Episode 1
rejection and archival, while `Subsequent governed consideration — Episode 2`
is separately visible and owns the current publication outcome. No flattened
`Archived → Pending` transition is presented.

The deployed Public Document Library was also verified with the long filename
`UN_ESCALATION_PRI_ACCESS_NICK_MOLONEY.pdf`. It wraps within its structured-row
region without colliding with Institution / Source. The view preserves the
complete `DOC-2026-000131` Document Identifier, Current status: Published,
`Published · Governed reconsideration` context, institution/source, category,
publication date, description, and the document-opening action.

Stage 59 remains presentation-only: no lifecycle, governance, eligibility,
schema, preservation, relationship, identifier, publication, or production
data behavior was changed by its implementation or presentation correction.

## Stage 60 Closure Evidence

Stage 60 implementation commit `79d4937c7cd4cd291c2fe356100c05af6abcb6c5`,
PR #334, was merged to `main` as the single-parent squash commit
`ea9a67b33065e263b2d5e56f2a7a012fda56e7c9` at `2026-08-11T09:09:33Z`.
Production deployment was subsequently verified active on Railway under the
GitHub delivery `Implement CDE Platform Stage 60 governed decision abstraction
(#334)`.

Stage 60 established an immutable, passive `GovernedDecision`
application-layer contract with opaque domain-owned subject identity, actor and
role attribution, decision time, optional decision type and state values,
optional rationale, opaque evidence references, optional opaque context, and
optional idempotency identity. A Published Document adapter represents existing
Stage 56 durable lifecycle decision evidence without changing its storage,
decision key, intake identity, Document Identifier, sequence, hashes, actor,
role, rationale, timestamp, or lifecycle episode context.

Stage 60 establishes contract feasibility only. It does not establish a
generic governance authority or second production decision domain. Existing
Stage 56–59 lifecycle authority, authorization, reconciliation, confirmation,
publication eligibility, persistence, schema, migration, historical backfill,
decision-key generation, decision sequences, episode identity, preservation,
evidence relationships, identifier allocation, disclosure rules, and
production-data semantics remain authoritative and unchanged. The contract
does not validate decisions, authorize operations, establish evidential
sufficiency, impose episode semantics, or require shared lifecycle states,
authority rules, or consequences across domains.

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
