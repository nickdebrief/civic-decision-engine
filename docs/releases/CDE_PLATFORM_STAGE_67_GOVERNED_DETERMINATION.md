# CDE Platform Stage 67 — Governed Determination

**Status:** Implemented · pending merge · pending deployment

## Purpose and boundary

Stage 67 preserves a formal conclusion attributed to an identified Stage 66 decision authority acting under an identified Stage 66 mandate. The governing principle is:

> **DETERMINATION REQUIRES AUTHORITY, MANDATE AND REASONS**
> A conclusion becomes a governed determination only when its responsible authority, mandate, source, issues, outcome and reasons are preserved.

The CDE records a source-backed representation; it does not make, validate, or evaluate the determination. Recording does not establish factual or legal correctness, lawfulness, jurisdiction, enforceability, fairness, independence, impartiality, or finality.

## Governance model

Determinations are human-recorded, immutable at creation, source-bound, administrator-only, and linked to exactly one accepted Stage 66 authority/mandate pair. Categories and representation modes are deliberate closed vocabularies. The source, authority, mandate, scope, representation, and recorder declarations are independently validated. Reasons are preserved as represented; when the source records no reasons, that absence requires an explicit governed limitation and no reasons are invented.

Referenced observations, inferences, allegations, responses, and authority context remain separately typed governed objects. They are not converted into evidence or determination merely because they are linked as considered objects.

## History and effect events

Review is append-only and accepts attribution and faithful preservation only. Supersession creates a new record and preserves the earlier determination. Appeal, review proceeding, variation, stay, revocation, setting aside, implementation, and replacement are append-only represented effect events. The CDE does not collapse those events into a legal status or calculate legal effect.

## Administrative, security, and publication boundary

Stage 67 provides authenticated administrator listing, detail, creation, review, supersession, and effect-event surfaces. GET inspection uses read-only access and does not initialise Stage 67 persistence. There are no public routes, serializers, navigation entries, exports, feeds, publication rules, automation, scoring, legal-effect calculation, or AI/LLM integration.

The existing administrator boundary remains in force: signed expiring `HttpOnly`, `Secure`, `SameSite=Strict` session cookies and non-GET mutations. The repository has no dedicated CSRF token or Origin/Referer validation; Stage 67 does not claim those controls or redesign them.

## Deployment boundary

Stage 67 creates no production determination or production data. It must be separately reviewed, merged, deployed, and production-verified. Its implementation does not alter Stage 60–66.1 semantics.
