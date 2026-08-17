# CDE Platform Stage 66 — Governed Decision Authority and Mandate

**Status:** Implemented · pending merge · pending deployment

## Purpose

Stage 66 preserves a source-bound representation of who or what body is represented as holding decision authority and the mandate within which that authority is represented as operating. It does not make, validate, approve, or publish a determination.

> **AUTHORITY PRECEDES DETERMINATION**
> A conclusion becomes a determination only when made by an authority acting within an evidenced mandate.

Recording an authority or mandate does not confer authority, validate an appointment or delegation, establish jurisdiction, establish legal competence, or determine that an act was lawfully authorised. Review accepts source-backed representation only.

## Governance boundary

Evidence, observation, inference, allegation, response, authority, mandate, and determination remain separate domains. A title, signature, institutional affiliation, repetition, silence, or authorship does not automatically establish authority. Absence of an end date does not imply indefinite continuation, and cessation does not determine that earlier acts were invalid.

Authority identity is separate from mandate identity. The initial holder kinds are `institution`, `office`, `role`, `named_person`, and `panel_or_body`. Mandate basis categories are limited to statutory, regulatory, appointment, delegation, governance, court or tribunal, contractual, and other formal instruments. These labels describe the represented source basis; they do not validate the instrument or its legal effect.

## Sources and appointment

Every authority and mandate requires a governed `authority_basis_source`. Contextual and contrary sources may coexist but cannot satisfy that requirement. Governed inferences, allegations, responses, arbitrary URLs, and unsupported objects are rejected. An accepted Stage 62 observation may provide context but cannot be the sole authority basis.

Named-person records require a represented office, role, panel, institution, or capacity, an appointment source, and an explicit human declaration that the source is represented as recording appointment or occupancy. This is not machine verification.

## Delegation and periods

Delegated mandates require an existing delegating authority and mandate, an express delegation source, represented delegated scope, represented effective period, limitations, and an explicit human declaration. Parent scope is never silently inherited, and recursive delegation is rejected. The parent record remains unchanged.

Source-described periods, CDE recording dates, review dates, and cessation dates remain distinct. The interface uses restrained terms such as “represented effective period,” “no recorded end date,” and “cessation recorded.” It does not display “currently authorised,” “legally active,” or “jurisdiction confirmed.”

## Review, correction, and cessation

Creation is immutable. Review is append-only and records the reviewer, rationale, boundary declaration, timestamp, and self-review marker. `accepted_as_source_backed_authority_record` means only that the representation is appropriate to retain as source-backed; it does not confer authority, validate appointment or delegation, establish jurisdiction, or determine legality.

Material correction uses a new record and append-only supersession. Original authority, mandate, scope, period, limitations, bindings, and review history remain inspectable. Supersession does not prove the earlier record invalid.

Cessation is append-only and requires a governed `cessation_source`. Initial cessation types are `expiry_recorded`, `revocation_recorded`, `resignation_recorded`, `termination_recorded`, `replacement_recorded`, and `other_cessation_recorded`. Cessation does not delete the record or determine the legal effect of cessation. A superseded record cannot later be ceased, and a ceased record cannot later be superseded.

## Administrative and security boundary

Stage 66 is human-recorded, authenticated administrator-only, source-bound, and non-public. It adds administrative listing, detail, creation, review, supersession, and cessation surfaces. GET inspection uses read-only access and does not initialise Stage 66 persistence or create records. There are no public routes, serializers, navigation entries, exports, feeds, publication rules, authority graphs, determination routes, automated interpretation, scoring, or AI/LLM integration.

The existing admin session boundary is preserved: signed expiring session cookie, `HttpOnly`, `Secure`, `SameSite=Strict`, and non-GET mutation routes. The repository does not currently provide a dedicated CSRF token or Origin/Referer validation mechanism; Stage 66 does not claim those controls or introduce a repository-wide redesign.

## Validation and deployment boundary

Focused tests cover authority/mandate separation, source selection and revalidation, appointment and delegation declarations, immutable and append-only history, idempotency, terminal lifecycle ordering, read-only inspection, escaping, authentication boundary, public-route absence, and compatibility with Stages 60–65.

Stage 66 is an implementation-only local stage until separately merged and deployed. It creates no production authority, mandate, review, supersession, cessation, determination, or other production data.
