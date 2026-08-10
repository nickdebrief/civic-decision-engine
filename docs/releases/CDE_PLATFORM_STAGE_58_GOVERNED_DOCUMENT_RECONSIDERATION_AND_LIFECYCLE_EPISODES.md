# CDE Platform Stage 58 — Governed Document Reconsideration and Lifecycle Episodes

## Purpose

Stage 58 introduces governed reconsideration for an Archived preserved document without reversing, deleting, rewriting, or obscuring its prior lifecycle. Reconsideration creates history; it does not rewrite history.

Stage 56 durable decisions remain the authoritative evidence for the original lifecycle. Existing Stage 56 histories implicitly constitute the original lifecycle episode. Stage 58 does not manufacture historical Episode 1 rows or backfill historical events.

## Identity and Preservation

One reconsidered document retains its existing preserved bytes, canonical `intake_id`, authoritative registry-backed Document Identifier, and recorded digest evidence. Reconsideration does not create another intake, copy bytes, allocate another DOC identifier, create a Published Document, or alter email attachment relationships.

## Lifecycle Episodes

The existing lifecycle remains unchanged and `Archived` remains terminal within each episode. Stage 58 does not introduce `Archived -> Pending`.

A reconsideration initiation record creates a new episode whose initial status is `Pending Intake`. This is episode-initiation evidence, not a lifecycle transition from Archived to Pending. The first lifecycle decision in the new episode is `Pending -> Under Review`.

The new `document_lifecycle_episodes` table is stored in the existing governance SQLite database. Existing lifecycle decision events gain nullable prospective `episode_id` attribution. Existing rows retain null episode attribution, original decision keys, original sequence values, and original content. No synthetic Episode 1 records are created.

Episode identities are deterministic and derived from the schema version, canonical intake ID, prior terminal decision key, and episode type. Document identity and episode identity remain distinct.

## Evidence and Authority

Episode initiation requires a genuine latest Stage 56 durable `X -> Archived` decision, a registry-backed Document Identifier, matching recorded SHA-256, and matching SHA-512 where available. Missing or conflicting evidence fails closed. No identifier is allocated merely to permit reconsideration, and no fresh transition-time rehash is claimed.

The durable episode and lifecycle decision records are authoritative. Metadata and `status_history` remain compatibility/presentation projections. Episode status is derived from its recorded initial status and latest episode-scoped durable decision; no competing mutable `episode_state` authority is introduced.

Historical initiation evidence is application-level append-only. It is durable repository evidence, not cryptographically immutable or tamper-proof.

## Confirmation and Projection

Reconsideration uses the Stage 57 confirmation boundary: proposal, short-lived HMAC-signed confirmation, explicit `Confirm Reconsideration`, revalidation, durable episode insertion, and compatibility projection.

SQLite episode evidence and `metadata.json` do not share one atomic transaction. Event/episode-first recording, deterministic retry, fail-closed advancement, and explicit projection-pending/inconsistent visibility provide the recovery model. GET rendering is observational and does not reconcile or repair evidence.

New reconsideration writes are deployment-gated by `CDE_STAGE58_RECONSIDERATION_ENABLED`, which defaults to disabled. Episode readers, administrative history, and public eligibility checks remain available while the write gate is disabled. This permits readers to be activated before reconsideration writes and permits existing episodes to remain inspectable if new reconsideration is later disabled. Semantic rollback to a pre-Stage-58 runtime remains unsafe after an Episode 2 record exists.

## Publication Boundary

Reconsideration itself never publishes a document. Pending, Under Review, Approved, projection-pending, and projection-inconsistent episodes are not publicly eligible. Public eligibility is resolved from durable active-episode evidence and fails closed when it disagrees with metadata.

If a later episode is Published, the public Publication Pathway must distinguish the original lifecycle from the subsequent governed consideration. The original rejection and archival remain visible historical facts under the existing disclosure boundary; they are never presented as reversed or erased.

## Scope Boundaries

Stage 58 does not introduce:

- a new lifecycle state;
- a new Published Document identity;
- a second intake;
- copied evidence bytes;
- a new database file;
- a new hashing algorithm;
- a correction, reversal, reopening, or supersession mechanism;
- historical lifecycle backfill;
- source/attachment lifecycle propagation;
- Canonical Record creation;
- semantic truth adjudication.

Correction remains distinct from reconsideration. Correction addresses a governed metadata/document mismatch and may create a corrected destination intake. Reconsideration submits the same preserved evidence to a subsequent lifecycle episode.

Semantic rollback to Stage 57 is safe only before a reconsideration episode exists. Once Episode 2 exists, Stage 57 may technically read the additive schema but cannot safely interpret episode-aware evidence or publication state.
