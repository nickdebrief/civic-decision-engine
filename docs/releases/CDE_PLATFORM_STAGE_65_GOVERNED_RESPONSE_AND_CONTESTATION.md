# CDE Platform Stage 65 — Governed Response and Contestation

Status: Implemented · pending merge · pending deployment

## Governing principle

**RESPONSE IS NOT RESOLUTION**

A response may dispute, qualify, or contextualise a governed allegation. Its
preservation does not, by itself, resolve the matter. Recording a response
establishes only that it was made or preserved in an identified governed
source; it does not establish truth, falsity, proof, disproof, admission,
exoneration, credibility, legal effect, finding, or determination.

Stage 65 keeps the allegation, response, source evidence, observation,
inference, and determination as distinct domains. It does not change the
target allegation, and it does not introduce authority or determination
architecture.

## Procedural and source model

Each human-recorded response links to exactly one existing Stage 64 governed
allegation through an explicit procedural relationship. The target is not a
source binding and cannot be an inference, observation, response, or arbitrary
free-text identity. Multiple responses and competing accounts may coexist.

Response categories are limited to `substantive_response`, `partial_response`,
`contextual_response`, `procedural_objection`, `request_for_particulars`,
`correction_of_attribution`, and `express_declination`. The last category is
permitted only where a governed source expressly records the declination;
silence is never converted into a response object or express declination.

Representation is labelled `verbatim` or `faithful_paraphrase` and depends on
a human declaration. The implementation does not claim machine verification,
OCR, extraction, fuzzy matching, sentiment analysis, credibility scoring, or
automated merits analysis.

Response bindings are explicitly role-labelled: `response_source`,
`notice_source`, `contextual_source`, and `contrary_source` during creation;
`withdrawal_source` is available only to the separate withdrawal workflow.
Notice does not establish receipt, understanding, or procedural adequacy.
Responses and contrary material do not automatically resolve allegations.

## Review and lifecycle

The lifecycle is `recorded`, `accepted_as_attributed_response`,
`requires_attribution_correction`, `not_accepted_as_attributed`, `superseded`,
or `withdrawn`. Review confirms attribution and faithful representation only.
Reviews, supersessions, and withdrawals are append-only and independently
idempotent; self-review is visible. A superseded response cannot later be
withdrawn, and a withdrawn response cannot later be superseded. The original
response, allegation link, bindings, and history remain inspectable.

Withdrawal does not prove the response false, the allegation true, or the
matter resolved. Administrative attribution correction is not withdrawal by
the attributed respondent and is not a merits determination.

## Administrative boundary

Stage 65 provides authenticated administrator-only listing, inspection,
creation, review, supersession, and withdrawal surfaces. GET inspection is
read-only and does not initialise Stage 65 persistence. There is no public
route, serializer, navigation, search, export, feed, publication eligibility,
automatic extraction, response generation, LLM integration, scoring, or
production response creation.

Stage 60–64.1 behaviour remains unchanged. No synthetic “no response” object
is created; an absence observation, if already present in the governed record,
remains an observation and is not upgraded by Stage 65.

Mutation routes use the established authenticated administrator session
boundary. The session is signed, expiring, `HttpOnly`, `Secure`, and
`SameSite=Strict`. The repository has no general CSRF token or Origin/Referer
validation layer; Stage 65 does not claim those controls or introduce a new
request-forgery mechanism. All Stage 65 writes remain non-GET authenticated
form operations and use the same boundary as existing administrative writes.
